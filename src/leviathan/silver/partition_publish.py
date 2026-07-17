"""Exact, repairable registered-partition publication (SILVER-F013).

The legacy :func:`leviathan.storage.glue_partitions.ensure_partition` treats *any* ``AlreadyExists``
as success -- so a partition already registered at the WRONG S3 location (the plan's
"wrong registered-partition location survives retry" hazard) is silently accepted and the writer's
new data is never seen. F013 replaces that swallow with **write-then-verify-then-register as one
operation**:

  * ``AlreadyExists`` now FETCHES the existing partition and compares the *managed* StorageDescriptor
    (location, ordered columns/types, in/out format, SerDe, managed params -- via
    :mod:`leviathan.silver.catalog`, ignoring AWS dictionary noise). Exact match => idempotent
    success. Mismatch => a hard error UNLESS an explicit :class:`RepairPlan` authorizes updating that
    exact partition.
  * NEW partition: validate the immutable final object (HEAD nonzero + parquet + optional fingerprint)
    BEFORE registering. EXISTING partition needing new data: the producer writes/validates a NEW
    run-versioned directory and only the repair capability atomically re-points the Glue location --
    the currently-visible object is never overwritten first.
  * Structured :class:`PublicationResult` counts (created / existing / repaired / failed) plus a
    per-partition outcome list.
  * S3->Glue reconciliation (:meth:`reconcile_from_s3`) diffs BOTH the value set and the location /
    descriptor, not only which partition values exist.
  * :meth:`recover` rebuilds registered partitions from certified evidence: a run manifest, direct
    LIST/HEAD of the exact objects, allowed-root validation, nonzero parquet, and a schema-fingerprint
    match. S3 Inventory is used only to DISCOVER candidates, never as the sole recovery authority.

ESR SPECIAL CASE (step 8): ``silver_esr`` maps the ``as_of_date`` partition COLUMN value
(``"20260524"``) to an ``as_of=20260524/`` DIRECTORY. :func:`esr_partition_location` builds that
explicit location so recovery/registration never depends on MSCK (which would mis-derive the column
name from the directory key).

CANONICAL SAFETY: every ``create_partition`` / ``update_partition`` is gated on an
:class:`~leviathan.common.publish_guard.Authorization`. Without ``may_mutate_canonical`` the publisher
PLANS the actions (dry-run/shadow) and touches no canonical Glue object -- so a canonical publish
without a verified approval is denied end to end. When a :class:`Lease` is supplied, its fencing token
is re-checked immediately before every mutation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional, Sequence

from leviathan.common.logging import get_logger
from leviathan.common.publish_guard import Authorization
from leviathan.silver import catalog
from leviathan.silver.lease import Lease

logger = get_logger(__name__)


class PartitionOutcome(str, Enum):
    CREATED = "created"          # newly registered
    EXISTING = "existing"        # already present, exact managed match (idempotent no-op)
    REPAIRED = "repaired"        # existed at a wrong location/descriptor, repair-plan updated it
    FAILED = "failed"            # mismatch with no repair authority, or validation failed
    PLANNED = "planned"          # non-canonical mode: action recorded, catalog untouched


@dataclass(frozen=True)
class PartitionSpec:
    """One partition to publish: its ordered key values, its final S3 location, and (for a NEW
    partition) the exact immutable object to validate before registering."""

    values: list[str]
    location: str
    object_key: Optional[str] = None   # the immutable part-*.parquet under ``location`` to validate


@dataclass(frozen=True)
class RepairAuthorization:
    """Explicit, per-partition authority to UPDATE an already-registered partition's location/SD.
    A publish never repairs unless the exact value tuple is listed here (F013 step-1)."""

    values_allowlist: frozenset

    @classmethod
    def for_values(cls, values_list: Sequence[Sequence[str]]) -> "RepairAuthorization":
        return cls(frozenset(tuple(str(v) for v in vs) for vs in values_list))

    def permits(self, values: Sequence[str]) -> bool:
        return tuple(str(v) for v in values) in self.values_allowlist


@dataclass
class PartitionActionRecord:
    values: list[str]
    location: str
    outcome: PartitionOutcome
    detail: str = ""


@dataclass
class PublicationResult:
    created: int = 0
    existing: int = 0
    repaired: int = 0
    failed: int = 0
    planned: int = 0
    actions: list[PartitionActionRecord] = field(default_factory=list)

    def record(self, rec: PartitionActionRecord) -> None:
        self.actions.append(rec)
        setattr(self, rec.outcome.value, getattr(self, rec.outcome.value) + 1)

    @property
    def ok(self) -> bool:
        return self.failed == 0

    def as_dict(self) -> dict:
        return {
            "created": self.created,
            "existing": self.existing,
            "repaired": self.repaired,
            "failed": self.failed,
            "planned": self.planned,
            "actions": [
                {"values": a.values, "location": a.location,
                 "outcome": a.outcome.value, "detail": a.detail}
                for a in self.actions
            ],
        }


class PartitionPublishError(RuntimeError):
    """A partition could not be published exactly (wrong location, failed validation, lost lease)."""


# ---------------------------------------------------------------------------
# ESR as_of directory <-> column mapping (step 8).
# ---------------------------------------------------------------------------
def esr_partition_location(root: str, commodity_code, market_year, as_of_date: str) -> str:
    """Build the EXPLICIT ``silver_esr`` partition location. The ``as_of_date`` COLUMN value
    ``"20260524"`` maps to the ``as_of=20260524/`` DIRECTORY (note: directory key is ``as_of``, not
    ``as_of_date``). Never derive this via MSCK -- the directory/column name mismatch would break it.
    """
    base = root.rstrip("/")
    return (
        f"{base}/commodity_code={commodity_code}/market_year={market_year}"
        f"/as_of={as_of_date}/"
    )


def default_object_validator(
    s3_client: Any, bucket: str,
    *, min_bytes: int = 1, require_parquet_magic: bool = True,
) -> Callable[[str], tuple[bool, str]]:
    """Build an object validator: HEAD the key, assert nonzero (>= ``min_bytes``), and (optionally)
    that the first 4 bytes are the parquet ``PAR1`` magic. Returns ``(ok, detail)``. Injectable so
    tests supply their own; the real one issues one HEAD + one 4-byte ranged GET, no footer parse."""

    def _validate(object_key: str) -> tuple[bool, str]:
        try:
            head = s3_client.head_object(Bucket=bucket, Key=object_key)
        except Exception as exc:  # noqa: BLE001
            return False, f"HEAD failed: {exc}"
        size = int(head.get("ContentLength", 0))
        if size < min_bytes:
            return False, f"object {object_key} is {size} bytes (< {min_bytes})"
        if require_parquet_magic:
            try:
                resp = s3_client.get_object(Bucket=bucket, Key=object_key, Range="bytes=0-3")
                magic = resp["Body"].read()
            except Exception as exc:  # noqa: BLE001
                return False, f"magic-byte GET failed: {exc}"
            if magic != b"PAR1":
                return False, f"object {object_key} lacks PAR1 parquet magic (got {magic!r})"
        return True, "validated"

    return _validate


@dataclass
class PartitionPublisher:
    """Publishes registered partitions for one table with exact/repair semantics.

    ``glue_client`` / ``s3_client`` are injectable (tests mock them). ``auth`` is the publish-guard
    verdict: only ``auth.may_mutate_canonical`` performs real Glue writes; otherwise every action is
    PLANNED (catalog untouched). ``bucket`` + ``allowed_root`` bound where objects/locations may live.
    """

    database: str
    table: str
    bucket: str
    allowed_root: str
    glue_client: Any
    s3_client: Any
    auth: Authorization
    table_sd: Optional[dict] = None
    lease: Optional[Lease] = None
    fencing_token: Optional[int] = None
    object_validator: Optional[Callable[[str], tuple[bool, str]]] = None

    def __post_init__(self) -> None:
        if self.object_validator is None:
            self.object_validator = default_object_validator(self.s3_client, self.bucket)

    # -- helpers ------------------------------------------------------------------------------
    def _sd(self) -> dict:
        if self.table_sd is None:
            tbl = self.glue_client.get_table(DatabaseName=self.database, Name=self.table)["Table"]
            self.table_sd = tbl["StorageDescriptor"]
        return self.table_sd

    def _partition_input(self, values: Sequence[str], location: str) -> dict:
        sd = dict(self._sd())
        sd["Location"] = location
        sd.pop("SortColumns", None)
        return {"Values": [str(v) for v in values], "StorageDescriptor": sd}

    def _under_allowed_root(self, location: str) -> bool:
        return catalog._normalize_location(location).startswith(
            catalog._normalize_location(self.allowed_root)
        )

    def _fence(self) -> None:
        if self.lease is not None and self.fencing_token is not None:
            self.lease.recheck(self.fencing_token)  # raises LeaseLost -> aborts before mutation

    def _get_existing(self, values: Sequence[str]) -> Optional[dict]:
        try:
            return self.glue_client.get_partition(
                DatabaseName=self.database, TableName=self.table,
                PartitionValues=[str(v) for v in values],
            )["Partition"]
        except Exception as exc:  # noqa: BLE001
            if catalog is not None and _is_not_found(exc):
                return None
            raise

    # -- the core publish op ------------------------------------------------------------------
    def publish_one(
        self, spec: PartitionSpec, repair: Optional[RepairAuthorization] = None,
        *, validate_new: bool = True,
    ) -> PartitionActionRecord:
        """Publish exactly one partition: validate (new), then create / confirm-idempotent / repair.

        Never overwrites a visible object first: for an EXISTING partition the caller is expected to
        have already written a new run-versioned directory; here we only (optionally) re-point the
        Glue location under an explicit :class:`RepairAuthorization`."""
        if not self._under_allowed_root(spec.location):
            return self._fail(spec, f"location {spec.location!r} not under allowed root "
                                    f"{self.allowed_root!r}")

        existing = self._get_existing(spec.values)
        desired_sd = self._partition_input(spec.values, spec.location)["StorageDescriptor"]

        if existing is None:
            return self._create_new(spec, desired_sd, validate_new=validate_new)

        # already registered -> compare managed fields exactly.
        diffs = catalog.diff_storage_descriptor(existing.get("StorageDescriptor") or {}, desired_sd)
        if not diffs:
            return PartitionActionRecord(list(spec.values), spec.location,
                                         PartitionOutcome.EXISTING, "exact managed match")
        # mismatch: only an explicit repair authorization may update it.
        if repair is None or not repair.permits(spec.values):
            return self._fail(
                spec, f"registered at a DIFFERENT location/descriptor and no repair authority: "
                      f"{'; '.join(diffs)}",
            )
        return self._repair(spec, desired_sd, diffs, validate_new=validate_new)

    def publish(
        self, specs: Sequence[PartitionSpec], repair: Optional[RepairAuthorization] = None,
        *, validate_new: bool = True,
    ) -> PublicationResult:
        """Publish many partitions; partial batch failure is captured per-partition (never a
        half-applied silent success). Returns structured counts."""
        result = PublicationResult()
        for spec in specs:
            try:
                rec = self.publish_one(spec, repair, validate_new=validate_new)
            except Exception as exc:  # noqa: BLE001 -- record and continue; caller inspects failed>0
                rec = PartitionActionRecord(list(spec.values), spec.location,
                                            PartitionOutcome.FAILED, f"exception: {exc}")
            result.record(rec)
        logger.info("publish %s.%s -> %s", self.database, self.table,
                    {k: getattr(result, k) for k in ("created", "existing", "repaired", "failed", "planned")})
        return result

    # -- internal outcome builders ------------------------------------------------------------
    def _create_new(self, spec: PartitionSpec, desired_sd: dict, *, validate_new: bool) -> PartitionActionRecord:
        if validate_new:
            ok, detail = self._validate_object(spec)
            if not ok:
                return self._fail(spec, f"new-partition object validation failed: {detail}")
        if not self.auth.may_mutate_canonical:
            return PartitionActionRecord(list(spec.values), spec.location,
                                         PartitionOutcome.PLANNED, "create planned (non-canonical mode)")
        self._fence()
        self.glue_client.create_partition(
            DatabaseName=self.database, TableName=self.table,
            PartitionInput={"Values": [str(v) for v in spec.values], "StorageDescriptor": desired_sd},
        )
        return PartitionActionRecord(list(spec.values), spec.location,
                                     PartitionOutcome.CREATED, "registered new partition")

    def _repair(self, spec: PartitionSpec, desired_sd: dict, diffs: list[str], *, validate_new: bool) -> PartitionActionRecord:
        if validate_new and spec.object_key:
            ok, detail = self._validate_object(spec)
            if not ok:
                return self._fail(spec, f"repair target object validation failed: {detail}")
        if not self.auth.may_mutate_canonical:
            return PartitionActionRecord(list(spec.values), spec.location, PartitionOutcome.PLANNED,
                                         f"repair planned (non-canonical mode): {'; '.join(diffs)}")
        self._fence()
        self.glue_client.update_partition(
            DatabaseName=self.database, TableName=self.table,
            PartitionValueList=[str(v) for v in spec.values],
            PartitionInput={"Values": [str(v) for v in spec.values], "StorageDescriptor": desired_sd},
        )
        return PartitionActionRecord(list(spec.values), spec.location, PartitionOutcome.REPAIRED,
                                     f"atomically re-pointed: {'; '.join(diffs)}")

    def _validate_object(self, spec: PartitionSpec) -> tuple[bool, str]:
        if not spec.object_key:
            return False, "no object_key supplied to validate before registration"
        return self.object_validator(spec.object_key)

    def _fail(self, spec: PartitionSpec, detail: str) -> PartitionActionRecord:
        logger.warning("partition publish FAILED %s.%s %s: %s", self.database, self.table, spec.values, detail)
        return PartitionActionRecord(list(spec.values), spec.location, PartitionOutcome.FAILED, detail)

    # -- S3 -> Glue reconciliation (step 3) ---------------------------------------------------
    def reconcile_from_s3(self, live_partitions: Sequence[dict], s3_locations: dict) -> dict:
        """Diff registered partitions against S3 truth on BOTH axes: which value tuples exist AND
        whether the registered location matches the S3 location.

        ``live_partitions`` = ``get_partitions`` ``Partition`` dicts. ``s3_locations`` maps a value
        tuple (as a ``/``-joined string) to its true S3 location prefix (from LIST). Returns a report;
        does NOT mutate -- feed ``location_mismatch`` value tuples into a :class:`RepairAuthorization`.
        """
        reg = {"/".join(str(v) for v in p.get("Values", [])):
               catalog._normalize_location((p.get("StorageDescriptor") or {}).get("Location"))
               for p in live_partitions}
        s3keys = {k: catalog._normalize_location(v) for k, v in s3_locations.items()}
        missing_in_glue = sorted(set(s3keys) - set(reg))          # data on S3, not registered
        orphan_in_glue = sorted(set(reg) - set(s3keys))            # registered, no S3 data
        location_mismatch = sorted(k for k in (set(reg) & set(s3keys)) if reg[k] != s3keys[k])
        return {
            "table": self.table,
            "registered_count": len(reg),
            "s3_count": len(s3keys),
            "missing_in_glue": missing_in_glue,
            "orphan_in_glue": orphan_in_glue,
            "location_mismatch": [
                {"values": k.split("/"), "registered": reg[k], "s3": s3keys[k]}
                for k in location_mismatch
            ],
            "exact": not (missing_in_glue or orphan_in_glue or location_mismatch),
        }

    # -- recovery from certified evidence (steps 4 + 6) ---------------------------------------
    def recover(
        self, candidates: Sequence[PartitionSpec], *, run_manifest: Optional[dict],
        expected_fingerprint: Optional[str] = None,
        fingerprint_fn: Optional[Callable[[str], str]] = None,
        repair: Optional[RepairAuthorization] = None,
    ) -> PublicationResult:
        """Rebuild registered partitions from validated evidence. S3 Inventory (or any candidate
        source) only DISCOVERS ``candidates``; recovery additionally requires:
          * a CERTIFIED run manifest (``state == CERTIFIED``);
          * direct LIST/HEAD of the exact object (via the object validator -- nonzero + parquet);
          * allowed-root validation (rejected before any registration);
          * a schema-fingerprint match when ``expected_fingerprint`` + ``fingerprint_fn`` are given.
        Anything failing a check is FAILED, never registered."""
        if not run_manifest or str(run_manifest.get("state")) not in ("CERTIFIED", "ManifestState.CERTIFIED"):
            raise PartitionPublishError(
                "recovery requires a CERTIFIED run manifest (S3 Inventory alone is not authority)"
            )
        result = PublicationResult()
        for spec in candidates:
            if not self._under_allowed_root(spec.location):
                result.record(self._fail(spec, "candidate location outside allowed root"))
                continue
            ok, detail = self._validate_object(spec)
            if not ok:
                result.record(self._fail(spec, f"recovery object validation failed: {detail}"))
                continue
            if expected_fingerprint and fingerprint_fn is not None:
                got = fingerprint_fn(spec.object_key)
                if got != expected_fingerprint:
                    result.record(self._fail(
                        spec, f"schema fingerprint {got} != expected {expected_fingerprint}"))
                    continue
            result.record(self.publish_one(spec, repair, validate_new=False))
        return result

    # -- partition-filtered Athena smoke command (step 7) -------------------------------------
    def athena_smoke_sql(self, values: Sequence[str], partition_cols: Sequence[str]) -> str:
        """Return a BOUNDED, partition-FILTERED Athena smoke query for a just-published partition.
        Emitted as a gate artifact; it is sargable on the registered partition keys so it prunes
        catalog-side and cannot trigger the projection LIST-storm. R1 does not execute it."""
        preds = " AND ".join(
            f"{col} = '{val}'" for col, val in zip(partition_cols, [str(v) for v in values])
        )
        return (
            f"SELECT count(*) AS n FROM {self.database}.{self.table} "
            f"WHERE {preds}; -- expect n > 0 for the published partition"
        )


def _is_not_found(exc: BaseException) -> bool:
    resp = getattr(exc, "response", None)
    code = ""
    if isinstance(resp, dict):
        code = str(resp.get("Error", {}).get("Code", ""))
    name = type(exc).__name__
    return code in ("EntityNotFoundException", "EntityNotFound") or name == "EntityNotFoundException"
