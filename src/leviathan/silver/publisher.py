"""Common shadow-first controlled publisher + run manifest (SILVER-F015).

The single controlled-publish interface EVERY silver/bronze producer routes through. It closes the
code-lane D3 gap ("replay writes in place, guarded only by skip-existing -- no shadow path") and
INV-6 ("no failed publish makes unvalidated data query-visible") by making publication a staged,
validated, manifest-driven state machine:

    PLANNED -> DISCOVERED -> STAGED -> VALIDATED -> PUBLISHED -> CATALOGED -> CERTIFIED
                                                 \\-> FAILED / ROLLED_BACK

  * WRITE goes to a SHADOW prefix first (``--shadow-prefix`` / :meth:`Authorization.shadow_prefix`),
    never the canonical object. Only after VALIDATED does the manifest authorize PROMOTION (a
    server-side copy shadow->canonical) and then cataloging.
  * ``--publish-mode dry-run|shadow|canonical`` (default dry-run), resolved through
    :mod:`leviathan.common.publish_guard`:
      - dry-run  : nothing is written anywhere; the manifest is a plan (stops at VALIDATED, in-memory).
      - shadow   : objects ARE written to the shadow prefix and validated, but never promoted or
                   cataloged to canonical (``may_mutate_canonical`` is False).
      - canonical: shadow-stage -> validate -> promote -> catalog -> certify, but ONLY with a verified
                   signed approval (the guard raises otherwise BEFORE any write).
  * A conditional :class:`Lease` keyed by ``table + normalized partition set`` serializes two
    concurrent runs; its fencing token is re-checked immediately before every canonical mutation, so a
    stale/parallel writer that lost its lease cannot promote or catalog.
  * flat / projected / registered publish strategies (registered delegates to
    :class:`~leviathan.silver.partition_publish.PartitionPublisher` for exact/repairable registration).
  * Deterministic failure injection at four seams (before/after object write, before/after catalog
    change) drives the invariant tests: a failure never changes the live Glue pointer/partition and
    never deletes the last good object; an identical rerun is a no-op or an identical replacement.

The per-run manifest JSON (job, inputs+source-versions, code-SHA, registry-schema-version,
row-key-null metrics, object hashes, partition actions, guard mode, fencing token, validation result,
timings, state transitions) is written to the manifest store on every run -- FAILED runs included.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Optional, Sequence

from leviathan.common.logging import get_logger
from leviathan.common.publish_guard import Authorization, PublishMode
from leviathan.silver.lease import Lease, lease_lock_id
from leviathan.silver.partition_publish import (
    PartitionPublisher,
    PartitionSpec,
    RepairAuthorization,
)

logger = get_logger(__name__)


class ManifestState(str, Enum):
    PLANNED = "PLANNED"
    DISCOVERED = "DISCOVERED"
    STAGED = "STAGED"
    VALIDATED = "VALIDATED"
    PUBLISHED = "PUBLISHED"
    CATALOGED = "CATALOGED"
    CERTIFIED = "CERTIFIED"
    FAILED = "FAILED"
    ROLLED_BACK = "ROLLED_BACK"


# Legal forward transitions (plus FAILED/ROLLED_BACK reachable from any active state).
_LEGAL: dict[ManifestState, set[ManifestState]] = {
    ManifestState.PLANNED: {ManifestState.DISCOVERED},
    ManifestState.DISCOVERED: {ManifestState.STAGED},
    ManifestState.STAGED: {ManifestState.VALIDATED},
    ManifestState.VALIDATED: {ManifestState.PUBLISHED},
    ManifestState.PUBLISHED: {ManifestState.CATALOGED},
    ManifestState.CATALOGED: {ManifestState.CERTIFIED},
    ManifestState.CERTIFIED: set(),
    ManifestState.FAILED: set(),
    ManifestState.ROLLED_BACK: set(),
}
_TERMINAL = {ManifestState.CERTIFIED, ManifestState.FAILED, ManifestState.ROLLED_BACK}


class PublishStrategy(str, Enum):
    FLAT = "flat"              # unpartitioned prefix; objects discovered by LIST, no Glue partitions
    PROJECTED = "projected"    # partition projection; write objects, NEVER enumerate/register (INV-3)
    REGISTERED = "registered"  # register each partition exactly (PartitionPublisher)


class FailurePoint(str, Enum):
    """Seams where a test may inject a deterministic failure to prove the safety invariants."""

    BEFORE_OBJECT_WRITE = "before_object_write"
    AFTER_OBJECT_WRITE = "after_object_write"
    BEFORE_CATALOG = "before_catalog"
    AFTER_CATALOG = "after_catalog"


class PublisherError(RuntimeError):
    """A controlled-publish failure. The run manifest is transitioned to FAILED before this raises."""


class _InjectedFailure(RuntimeError):
    pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


@dataclass
class StagedObject:
    """One output object: its FINAL canonical key, the bytes to publish, its partition values (for a
    registered table), and optional row/null metrics for the V001-style validation hooks."""

    canonical_key: str
    body: bytes
    partition_values: Optional[list[str]] = None
    row_count: Optional[int] = None
    null_metrics: Optional[dict] = None       # {column: nonnull_fraction}
    schema_fingerprint: Optional[str] = None
    shadow_key: Optional[str] = None          # filled in during STAGED
    object_hash: Optional[str] = None         # filled in during STAGED

    def location_prefix(self) -> str:
        return self.canonical_key.rsplit("/", 1)[0] + "/"


@dataclass
class ValidationHooks:
    """V001-style row/schema/value gates run at STAGED->VALIDATED. Each returns ``(ok, detail)``.
    Defaults enforce nonzero rows and a per-column non-null floor; schema-fingerprint match is checked
    when an ``expected_fingerprint`` is supplied. All are overridable/injectable."""

    min_rows: int = 1
    min_nonnull_frac: float = 0.0
    floor_overrides: Optional[dict] = None   # OP-8 per-column floors; fall back to min_nonnull_frac
    expected_fingerprint: Optional[str] = None
    row_hook: Optional[Callable[[StagedObject], tuple[bool, str]]] = None
    value_hook: Optional[Callable[[StagedObject], tuple[bool, str]]] = None
    schema_hook: Optional[Callable[[StagedObject], tuple[bool, str]]] = None

    def run(self, obj: StagedObject) -> list[str]:
        problems: list[str] = []
        rh = self.row_hook or self._default_row
        vh = self.value_hook or self._default_value
        sh = self.schema_hook or self._default_schema
        for hook in (rh, vh, sh):
            ok, detail = hook(obj)
            if not ok:
                problems.append(detail)
        return problems

    def _default_row(self, obj: StagedObject) -> tuple[bool, str]:
        if obj.row_count is None:
            return True, "row_count not provided; skipped"
        if obj.row_count < self.min_rows:
            return False, f"row_count {obj.row_count} < min_rows {self.min_rows}"
        return True, "rows ok"

    def _default_value(self, obj: StagedObject) -> tuple[bool, str]:
        if not obj.null_metrics:
            return True, "null_metrics not provided; skipped"
        overrides = self.floor_overrides or {}
        bad = {c: f for c, f in obj.null_metrics.items()
               if f < overrides.get(c, self.min_nonnull_frac)}
        if bad:
            floors = {c: overrides.get(c, self.min_nonnull_frac) for c in bad}
            return False, f"columns below non-null floor {floors}: {bad}"
        return True, "value non-null ok"

    def _default_schema(self, obj: StagedObject) -> tuple[bool, str]:
        if not self.expected_fingerprint or obj.schema_fingerprint is None:
            return True, "schema fingerprint not checked"
        if obj.schema_fingerprint != self.expected_fingerprint:
            return False, (f"schema fingerprint {obj.schema_fingerprint} != expected "
                           f"{self.expected_fingerprint}")
        return True, "schema ok"


@dataclass
class RunManifest:
    """The per-run promotion authority + audit record. Written to the manifest store every run."""

    run_id: str
    job: str
    table: str
    database: str
    publish_mode: str
    strategy: str
    code_sha: Optional[str] = None
    registry_schema_version: Optional[int] = None
    inputs: list[dict] = field(default_factory=list)       # [{source, version, key}]
    outputs: list[dict] = field(default_factory=list)      # [{canonical_key, object_hash, values}]
    partition_actions: list[dict] = field(default_factory=list)
    row_key_null_metrics: dict = field(default_factory=dict)
    validation_result: dict = field(default_factory=dict)
    fencing_token: Optional[int] = None
    guard_mode: Optional[str] = None
    timings: dict = field(default_factory=dict)
    transitions: list[dict] = field(default_factory=list)
    state: ManifestState = ManifestState.PLANNED
    failure_reason: Optional[str] = None
    created_at: str = field(default_factory=_now_iso)

    def advance(self, to: ManifestState) -> None:
        if to in (ManifestState.FAILED, ManifestState.ROLLED_BACK):
            self._transition(to)
            return
        if self.state in _TERMINAL:
            raise PublisherError(f"manifest {self.run_id} is terminal ({self.state.value}); cannot advance")
        if to not in _LEGAL[self.state]:
            raise PublisherError(f"illegal manifest transition {self.state.value} -> {to.value}")
        self._transition(to)

    def fail(self, reason: str) -> None:
        self.failure_reason = reason
        self.advance(ManifestState.FAILED)

    def _transition(self, to: ManifestState) -> None:
        self.transitions.append({"from": self.state.value, "to": to.value, "at": _now_iso()})
        self.state = to

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "job": self.job,
            "table": self.table,
            "database": self.database,
            "publish_mode": self.publish_mode,
            "strategy": self.strategy,
            "code_sha": self.code_sha,
            "registry_schema_version": self.registry_schema_version,
            "inputs": self.inputs,
            "outputs": self.outputs,
            "partition_actions": self.partition_actions,
            "row_key_null_metrics": self.row_key_null_metrics,
            "validation_result": self.validation_result,
            "fencing_token": self.fencing_token,
            "guard_mode": self.guard_mode,
            "timings": self.timings,
            "transitions": self.transitions,
            "state": self.state.value,
            "failure_reason": self.failure_reason,
            "created_at": self.created_at,
        }

    def to_json(self) -> bytes:
        return json.dumps(self.to_dict(), sort_keys=True, indent=2).encode("utf-8")


@dataclass
class ShadowPublisher:
    """Shadow-first controlled publisher for one table + run.

    Clients (``s3_client`` / ``glue_client``) are injectable. ``auth`` is the publish-guard verdict.
    ``shadow_prefix`` overrides the guard-derived shadow location (the ``--shadow-prefix`` flag).
    ``manifest_store`` is a callable ``(key, bytes) -> None`` (S3 put or local write) invoked to
    persist the manifest each run; defaults to an S3 put under the control prefix.
    """

    job: str
    table: str
    database: str
    bucket: str
    canonical_root: str
    auth: Authorization
    s3_client: Any
    glue_client: Optional[Any] = None
    strategy: PublishStrategy = PublishStrategy.FLAT
    shadow_prefix: Optional[str] = None
    lease: Optional[Lease] = None
    fencing_token: Optional[int] = None
    validation: ValidationHooks = field(default_factory=ValidationHooks)
    manifest_store: Optional[Callable[[str, bytes], None]] = None
    code_sha: Optional[str] = None
    registry_schema_version: Optional[int] = None
    inject_failure: Optional[FailurePoint] = None
    run_id: Optional[str] = None
    reconcile_schema_widen: bool = False

    def __post_init__(self) -> None:
        if self.run_id is None:
            self.run_id = f"{self.table}-{int(time.time()*1000)}"
        self._manifest = RunManifest(
            run_id=self.run_id, job=self.job, table=self.table, database=self.database,
            publish_mode=self.auth.mode.value, strategy=self.strategy.value,
            code_sha=self.code_sha, registry_schema_version=self.registry_schema_version,
            fencing_token=self.fencing_token, guard_mode=self.auth.mode.value,
        )

    @property
    def manifest(self) -> RunManifest:
        return self._manifest

    def _root_key(self) -> str:
        """The canonical root as a BUCKET KEY (scheme/bucket stripped from an s3:// root).

        ``canonical_root`` arrives either as a plain key prefix or as a full s3:// URL
        (callers differ); every derived S3 KEY must use the key form -- using the URL form
        raw once minted literal 's3://<bucket>/...' object keys (BF-W1 shadow-rehearsal find)."""
        root = self.canonical_root.rstrip("/")
        if root.startswith("s3://"):
            rest = root[len("s3://"):]
            root = rest.split("/", 1)[1] if "/" in rest else ""
        return root.rstrip("/")

    def _shadow_key(self, canonical_key: str) -> str:
        """Map a canonical object key to its shadow-prefix twin.

        Shadow objects must live OUTSIDE every data-plane prefix a registered-partition
        location or the feature extractor lists. The per-directory form
        (``<partition dir>/_shadow/<name>``) staged objects INSIDE the future partition
        locations -- Athena ignores underscore-hidden paths, but
        ``extractors._paths_with_year_partitions`` does a raw LIST with a ``year=`` regex and
        would double-read every promoted row (BF-W1 shadow-rehearsal find). Root-level staging
        (``<table root>/_shadow/<relative key>``) sits outside every ``commodity=`` prefix; the
        per-directory form survives only as the fallback for keys outside the canonical root."""
        if self.shadow_prefix:
            base = self.shadow_prefix.rstrip("/")
            return f"{base}/{canonical_key.lstrip('/')}"
        root_key = self._root_key()
        if root_key and canonical_key.startswith(f"{root_key}/"):
            relative = canonical_key[len(root_key) + 1:]
            marker = self.auth.shadow_prefix("").strip("/")
            return f"{root_key}/{marker}/{relative}"
        # fallback (key outside the canonical root): <prefix>/_shadow/<...>
        prefix, _, name = canonical_key.rpartition("/")
        shadow_dir = self.auth.shadow_prefix(prefix)
        return f"{shadow_dir}{name}"

    def _persist_manifest(self) -> str:
        key = f"{self._root_key()}/_manifests/{self.run_id}.json"
        # never write the manifest under a data prefix that a table LISTs: _manifests is control-plane.
        body = self._manifest.to_json()
        store = self.manifest_store or self._default_manifest_store
        store(key, body)
        return key

    def _default_manifest_store(self, key: str, body: bytes) -> None:
        self.s3_client.put_object(Bucket=self.bucket, Key=key, Body=body,
                                  ContentType="application/json")

    def _maybe_fail(self, point: FailurePoint) -> None:
        if self.inject_failure is point:
            raise _InjectedFailure(f"injected failure at {point.value}")

    def _fence(self) -> None:
        if self.lease is not None and self.fencing_token is not None:
            self.lease.recheck(self.fencing_token)

    # -- the orchestrated run -----------------------------------------------------------------
    def run(self, objects: Sequence[StagedObject],
            repair: Optional[RepairAuthorization] = None) -> RunManifest:
        """Execute the controlled publish for ``objects``. Always returns the manifest (persisted),
        FAILED runs included. Raises :class:`PublisherError` only after the manifest is FAILED +
        persisted, so a failure never leaves canonical half-mutated."""
        t0 = time.time()
        m = self._manifest
        try:
            self._discover(objects)
            self._stage(objects)
            self._validate(objects)
            if not self.auth.may_mutate_canonical:
                # dry-run / shadow: stop before touching canonical. Nothing query-visible changed.
                m.timings["total_s"] = round(time.time() - t0, 4)
                self._persist_manifest()
                logger.info("publish %s halted at %s (mode=%s; canonical untouched)",
                            self.table, m.state.value, self.auth.mode.value)
                return m
            self._promote(objects)
            self._catalog(objects, repair)
            m.advance(ManifestState.CERTIFIED)
            m.timings["total_s"] = round(time.time() - t0, 4)
            self._persist_manifest()
            return m
        except Exception as exc:  # noqa: BLE001 -- any failure fails-closed + persists the manifest
            m.timings["total_s"] = round(time.time() - t0, 4)
            if m.state not in _TERMINAL:
                m.fail(f"{type(exc).__name__}: {exc}")
            self._persist_manifest()
            if isinstance(exc, _InjectedFailure):
                raise PublisherError(str(exc)) from exc
            raise PublisherError(f"controlled publish failed at {m.state.value}: {exc}") from exc

    def _discover(self, objects: Sequence[StagedObject]) -> None:
        m = self._manifest
        m.inputs = [{"canonical_key": o.canonical_key, "values": o.partition_values} for o in objects]
        m.advance(ManifestState.DISCOVERED)

    def _stage(self, objects: Sequence[StagedObject]) -> None:
        m = self._manifest
        t0 = time.time()
        for o in objects:
            o.object_hash = sha256_bytes(o.body)
            o.shadow_key = self._shadow_key(o.canonical_key)
            if self.auth.mode is PublishMode.DRY_RUN:
                continue  # dry-run stages nothing to S3; hashing/validation run in-memory
            self._maybe_fail(FailurePoint.BEFORE_OBJECT_WRITE)
            self.s3_client.put_object(Bucket=self.bucket, Key=o.shadow_key, Body=o.body)
            self._maybe_fail(FailurePoint.AFTER_OBJECT_WRITE)
        m.timings["stage_s"] = round(time.time() - t0, 4)
        m.advance(ManifestState.STAGED)

    def _validate(self, objects: Sequence[StagedObject]) -> None:
        m = self._manifest
        all_problems: dict[str, list[str]] = {}
        for o in objects:
            problems = self.validation.run(o)
            if problems:
                all_problems[o.canonical_key] = problems
            if o.null_metrics:
                m.row_key_null_metrics[o.canonical_key] = o.null_metrics
        m.validation_result = {"ok": not all_problems, "problems": all_problems}
        if all_problems:
            m.fail(f"validation failed: {all_problems}")
            raise PublisherError(f"validation failed: {all_problems}")
        m.advance(ManifestState.VALIDATED)

    def _promote(self, objects: Sequence[StagedObject]) -> None:
        """Copy each validated shadow object to its canonical key (server-side copy). Only reached in
        canonical mode. The canonical object is written here for the FIRST time -- never overwritten
        before validation."""
        m = self._manifest
        t0 = time.time()
        for o in objects:
            self._fence()
            self.s3_client.copy_object(
                Bucket=self.bucket,
                Key=o.canonical_key,
                CopySource={"Bucket": self.bucket, "Key": o.shadow_key},
            )
            m.outputs.append({"canonical_key": o.canonical_key, "object_hash": o.object_hash,
                              "values": o.partition_values})
        m.timings["promote_s"] = round(time.time() - t0, 4)
        m.advance(ManifestState.PUBLISHED)

    def _catalog(self, objects: Sequence[StagedObject],
                 repair: Optional[RepairAuthorization]) -> None:
        m = self._manifest
        self._maybe_fail(FailurePoint.BEFORE_CATALOG)
        if self.strategy is PublishStrategy.REGISTERED:
            if self.glue_client is None:
                raise PublisherError("registered strategy requires a glue_client")
            pub = PartitionPublisher(
                database=self.database, table=self.table, bucket=self.bucket,
                allowed_root=self.canonical_root, glue_client=self.glue_client,
                s3_client=self.s3_client, auth=self.auth, lease=self.lease,
                fencing_token=self.fencing_token,
                object_validator=lambda k: (True, "already validated in staging"),
                reconcile_schema_widen=self.reconcile_schema_widen,
            )
            specs = [
                PartitionSpec(values=o.partition_values or [],
                              location=f"s3://{self.bucket}/{o.location_prefix()}",
                              object_key=o.canonical_key)
                for o in objects if o.partition_values is not None
            ]
            result = pub.publish(specs, repair, validate_new=False)
            m.partition_actions = result.as_dict()["actions"]
            if not result.ok:
                raise PublisherError(f"partition cataloging failed: {result.failed} failed")
        else:
            # flat / projected: objects are discovered by LIST or projection; no Glue partition
            # registration. (INV-3: never enumerate/register a projected table.)
            m.partition_actions = [{"strategy": self.strategy.value, "note": "no partition registration"}]
        self._maybe_fail(FailurePoint.AFTER_CATALOG)
        m.advance(ManifestState.CATALOGED)


def build_lease_for(table: str, partition_values: Optional[Sequence[Sequence[str]]],
                    bucket: str, prefix: str, s3_client: Any, **kwargs) -> Lease:
    """Convenience: a partition-set-keyed lease for a publish run (F015 lease keying)."""
    return Lease(bucket=bucket, prefix=prefix, lock_id=lease_lock_id(table, partition_values),
                 s3_client=s3_client, **kwargs)
