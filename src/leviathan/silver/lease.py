"""Single-operator S3-object lease lock with fencing (SILVER-F012 step 3, SILVER-F015).

WHY (and the scope this deliberately keeps small)
--------------------------------------------------
The original readiness design specified a per-role fleet of catalog locks. For a
single-operator remediation that is overweight (C-BETTER-3): the letter of F012 is a
*lightened* lock -- ONE lease, owner/run-id/TTL/heartbeat plus a monotonic **fencing
token** so a writer that lost its lease (crash, GC pause, clock skew) cannot mutate the
catalog after a newer holder took over. F015 reuses the exact same primitive, keyed by
``table + normalized partition set`` instead of the database, so two concurrent publishers
of the same partition set serialize.

MECHANISM (single-operator grade, documented)
---------------------------------------------
The lease is one JSON object at ``s3://<bucket>/<prefix>/_locks/<lock_id>.json``. Acquire /
heartbeat / release use S3 **conditional writes** (``IfNoneMatch='*'`` to create, ``IfMatch=
<etag>`` to overwrite) so a lost update between two processes fails closed with
``LeaseContended`` rather than silently clobbering. The fencing token is a monotonically
increasing integer stored in the object; it increments only when the lease is newly created
or *stolen* from an expired holder, never on a same-holder heartbeat. Every mutation path
(F012 apply/restore, F015 promote/catalog) calls :meth:`Lease.recheck` immediately before the
mutating AWS call: recheck re-reads the object and refuses (``LeaseLost``) unless the current
object is still owned by us, unexpired, and carries the exact token we were handed.

This is NOT a distributed lock service. It closes the single-operator failure modes the plan
enumerates (concurrent apply, expired lock, stolen lock, heartbeat loss, obsolete token) and
documents that a hostile multi-writer environment needs DynamoDB conditional writes instead.

NO CANONICAL MUTATION HERE
--------------------------
The lease object lives under a ``_locks/`` control prefix, never a data/partition prefix, and
this module performs no Glue or data mutation of its own -- it only arbitrates who may. Callers
still route the actual catalog/data write through :mod:`leviathan.common.publish_guard`.
"""
from __future__ import annotations

import hashlib
import json
import os
import socket
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Sequence

from leviathan.common.logging import get_logger

logger = get_logger(__name__)

LOCKS_PREFIX_SEGMENT = "_locks"
DEFAULT_TTL_SECONDS = 900  # 15 min: single-operator step is short; heartbeat renews long runs.


class LeaseError(RuntimeError):
    """Base for every lease failure. All are fail-closed (raised before any mutation)."""


class LeaseUnavailable(LeaseError):
    """Another live (unexpired) holder owns the lease -- a concurrent operator."""


class LeaseContended(LeaseError):
    """A conditional write lost a race (another process wrote the object first)."""


class LeaseLost(LeaseError):
    """The recheck failed: we no longer hold the lease, it expired, or our token is stale."""


def _now(now: Optional[datetime] = None) -> datetime:
    dt = now or datetime.now(timezone.utc)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _parse_iso(value: str) -> datetime:
    raw = (value or "").strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    dt = datetime.fromisoformat(raw)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def normalized_partition_set(partition_values: Optional[Sequence[Sequence[str]]]) -> str:
    """Order-independent digest of a set of partition value tuples (F015 lease key input).

    ``[["101","2000","20260524"], ...]`` -> a stable short hex. A table-level lease (F012, or a
    whole-table publish) passes ``None`` and gets the sentinel ``"_table"``."""
    if not partition_values:
        return "_table"
    rows = sorted("/".join(str(v) for v in tup) for tup in partition_values)
    digest = hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()
    return digest[:16]


def lease_lock_id(table: str, partition_values: Optional[Sequence[Sequence[str]]] = None) -> str:
    """The lock id for a (table, normalized partition set). Filesystem/S3-key safe."""
    return f"{table}.{normalized_partition_set(partition_values)}"


@dataclass(frozen=True)
class LeaseState:
    """The on-object lease record (serialized to the ``_locks/<id>.json`` body)."""

    lock_id: str
    owner: str
    run_id: str
    fencing_token: int
    acquired_at: str
    expires_at: str
    heartbeat_at: str

    def to_json(self) -> bytes:
        return json.dumps(
            {
                "lock_id": self.lock_id,
                "owner": self.owner,
                "run_id": self.run_id,
                "fencing_token": self.fencing_token,
                "acquired_at": self.acquired_at,
                "expires_at": self.expires_at,
                "heartbeat_at": self.heartbeat_at,
            },
            sort_keys=True,
        ).encode("utf-8")

    @classmethod
    def from_json(cls, raw: bytes) -> "LeaseState":
        d = json.loads(raw.decode("utf-8"))
        return cls(
            lock_id=d["lock_id"],
            owner=d["owner"],
            run_id=d["run_id"],
            fencing_token=int(d["fencing_token"]),
            acquired_at=d["acquired_at"],
            expires_at=d["expires_at"],
            heartbeat_at=d["heartbeat_at"],
        )

    def is_expired(self, now: Optional[datetime] = None) -> bool:
        return _now(now) > _parse_iso(self.expires_at)


def default_owner() -> str:
    """A stable-enough owner id for a single operator: user@host."""
    user = os.environ.get("USER") or os.environ.get("USERNAME") or "operator"
    try:
        host = socket.gethostname()
    except Exception:  # noqa: BLE001 -- best effort identity only
        host = "host"
    return f"{user}@{host}"


@dataclass
class Lease:
    """A held (or acquirable) lease over one lock id, backed by an S3 control object.

    Construct with the target ``bucket`` + control ``prefix`` (e.g. ``silver/``) and an S3
    client (injectable for tests). ``acquire`` returns the granted :class:`LeaseState`; callers
    keep :attr:`state` and pass ``state.fencing_token`` into every guarded mutation, calling
    :meth:`recheck` immediately before the mutating AWS call."""

    bucket: str
    prefix: str
    lock_id: str
    s3_client: Any
    owner: str = field(default_factory=default_owner)
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    ttl_seconds: int = DEFAULT_TTL_SECONDS
    state: Optional[LeaseState] = None

    @property
    def key(self) -> str:
        base = self.prefix.strip("/")
        seg = f"{base}/{LOCKS_PREFIX_SEGMENT}" if base else LOCKS_PREFIX_SEGMENT
        return f"{seg}/{self.lock_id}.json"

    # -- raw S3 helpers (all conditional-write aware) ----------------------------------------
    def _read(self) -> tuple[Optional[LeaseState], Optional[str]]:
        """Return (state, etag) or (None, None) if the object does not exist."""
        try:
            resp = self.s3_client.get_object(Bucket=self.bucket, Key=self.key)
        except Exception as exc:  # noqa: BLE001
            if _is_no_such_key(exc):
                return None, None
            raise
        body = resp["Body"].read()
        etag = (resp.get("ETag") or "").strip('"')
        return LeaseState.from_json(body), etag

    def _create(self, state: LeaseState) -> None:
        """Create the lock object; fail closed if it already exists (lost the create race)."""
        try:
            self.s3_client.put_object(
                Bucket=self.bucket, Key=self.key, Body=state.to_json(),
                IfNoneMatch="*", ContentType="application/json",
            )
        except Exception as exc:  # noqa: BLE001
            if _is_precondition_failed(exc):
                raise LeaseContended(
                    f"lease {self.lock_id}: another process created the lock concurrently"
                ) from exc
            raise

    def _overwrite(self, state: LeaseState, etag: str) -> None:
        """Overwrite only if the object still has ``etag`` (else another writer intervened)."""
        try:
            self.s3_client.put_object(
                Bucket=self.bucket, Key=self.key, Body=state.to_json(),
                IfMatch=etag, ContentType="application/json",
            )
        except Exception as exc:  # noqa: BLE001
            if _is_precondition_failed(exc):
                raise LeaseContended(
                    f"lease {self.lock_id}: object changed under us during overwrite"
                ) from exc
            raise

    # -- public lease operations -------------------------------------------------------------
    def acquire(self, now: Optional[datetime] = None) -> LeaseState:
        """Acquire (or reclaim an expired) lease. Raises :class:`LeaseUnavailable` if a live
        holder owns it. Fencing token increments on create/steal, so a stale prior holder can
        never win a later recheck."""
        now = _now(now)
        current, etag = self._read()
        if current is None:
            granted = self._mint(token=1, now=now)
            self._create(granted)
            self.state = granted
            logger.info("lease %s ACQUIRED (new) token=%d owner=%s", self.lock_id, 1, self.owner)
            return granted
        if not current.is_expired(now):
            if current.owner == self.owner and current.run_id == self.run_id:
                return self.heartbeat(now)  # re-entrant renew
            raise LeaseUnavailable(
                f"lease {self.lock_id} held by {current.owner}/{current.run_id} "
                f"until {current.expires_at}"
            )
        # expired -> steal, bumping the fencing token so the dead holder's token is now stale.
        granted = self._mint(token=current.fencing_token + 1, now=now)
        self._overwrite(granted, etag or "")
        self.state = granted
        logger.info(
            "lease %s STOLEN from expired holder %s token=%d->%d",
            self.lock_id, current.owner, current.fencing_token, granted.fencing_token,
        )
        return granted

    def heartbeat(self, now: Optional[datetime] = None) -> LeaseState:
        """Extend our lease TTL. Same fencing token (a heartbeat is not a new acquisition).
        Raises :class:`LeaseLost` if we no longer own it or the token drifted."""
        now = _now(now)
        current, etag = self._read()
        self._assert_ours(current, now)
        granted = self._mint(token=current.fencing_token, now=now)
        self._overwrite(granted, etag or "")
        self.state = granted
        return granted

    def recheck(self, token: int, now: Optional[datetime] = None) -> LeaseState:
        """The pre-mutation gate. Re-read the object and confirm WE still hold it, it is
        unexpired, and its token equals ``token``. Raises :class:`LeaseLost` otherwise -- the
        caller must abort the mutation. This is the fence: a stale writer with an old token is
        refused even though it thinks it holds the lease."""
        now = _now(now)
        current, _ = self._read()
        if current is None:
            raise LeaseLost(f"lease {self.lock_id}: lock object vanished before mutation")
        if current.owner != self.owner or current.run_id != self.run_id:
            raise LeaseLost(
                f"lease {self.lock_id}: now held by {current.owner}/{current.run_id} (fenced out)"
            )
        if current.is_expired(now):
            raise LeaseLost(f"lease {self.lock_id}: expired at {current.expires_at}")
        if current.fencing_token != token:
            raise LeaseLost(
                f"lease {self.lock_id}: fencing token {token} is stale "
                f"(current {current.fencing_token})"
            )
        return current

    def release(self, now: Optional[datetime] = None) -> None:
        """Release the lease if we still hold it. A no-op if it is gone or already stolen
        (never deletes another holder's lock)."""
        current, _ = self._read()
        if current is None:
            self.state = None
            return
        if current.owner == self.owner and current.run_id == self.run_id:
            try:
                self.s3_client.delete_object(Bucket=self.bucket, Key=self.key)
            except Exception as exc:  # noqa: BLE001
                if not _is_no_such_key(exc):
                    raise
        self.state = None

    def _assert_ours(self, current: Optional[LeaseState], now: datetime) -> None:
        if current is None:
            raise LeaseLost(f"lease {self.lock_id}: lock object missing")
        if current.owner != self.owner or current.run_id != self.run_id:
            raise LeaseLost(f"lease {self.lock_id}: held by {current.owner}/{current.run_id}")
        if current.is_expired(now):
            raise LeaseLost(f"lease {self.lock_id}: expired at {current.expires_at}")

    def _mint(self, *, token: int, now: datetime) -> LeaseState:
        return LeaseState(
            lock_id=self.lock_id,
            owner=self.owner,
            run_id=self.run_id,
            fencing_token=token,
            acquired_at=now.isoformat(),
            expires_at=(now + timedelta(seconds=self.ttl_seconds)).isoformat(),
            heartbeat_at=now.isoformat(),
        )


# ---------------------------------------------------------------------------
# botocore error shape helpers (kept tolerant so tests can raise plain ClientError-likes).
# ---------------------------------------------------------------------------
def _error_code(exc: BaseException) -> str:
    resp = getattr(exc, "response", None)
    if isinstance(resp, dict):
        return str(resp.get("Error", {}).get("Code", ""))
    return ""


def _is_no_such_key(exc: BaseException) -> bool:
    return _error_code(exc) in ("NoSuchKey", "404", "NotFound")


def _is_precondition_failed(exc: BaseException) -> bool:
    return _error_code(exc) in ("PreconditionFailed", "412", "ConditionalRequestConflict")
