"""Readiness kill switch + fail-closed publish authorization (SILVER-F004, Milestone R0).

WHY THIS EXISTS
---------------
A live process was minting placeholder ``silver_model_predictions`` partitions on the *canonical*
Glue catalog every day (root cause: an un-mocked unit test whose write path news up a real
``boto3`` Glue client and calls ``create_partition`` on ``leviathan_dev`` with ``prediction_date=
date.today()``; see ``jobs/batch/train_commodity._write_predictions`` -> ``leviathan.storage.
glue_partitions.ensure_partition``). During the readiness campaign NO writer may publish to a
production surface. This module is the structural gate: a writer asks it for authorization *before*
any mutating AWS call, and it fails **closed** — the default mode is ``dry-run`` and canonical
publication is denied unless every environment invariant matches AND a valid signed approval
artifact is presented.

It writes nothing and mutates nothing itself. It only decides "may this caller mutate the canonical
surface, yes/no" and raises before returning if the answer is no.

THE ADOPTION CONTRACT (what other R0/R1 packages must do)
---------------------------------------------------------
Every writer that can touch a served surface (an S3 ``put_object`` under the canonical prefix, a
Glue ``create_partition`` / ``batch_create_partition`` / ``update_table`` on a served table) MUST,
before the first mutating call::

    from leviathan.common.publish_guard import authorize_publish, PublishTarget

    auth = authorize_publish(
        PublishTarget(
            account_id=sts_account_id,     # from sts.get_caller_identity()["Account"]
            bucket=bucket,
            database="leviathan_dev",
            prefix="silver/model_predictions/",
            role_arn=caller_role_arn,       # from sts.get_caller_identity()["Arn"]
            table="silver_model_predictions",
        ),
        argv=sys.argv,                      # picks up --publish-mode; default dry-run
        env=os.environ,
        approval=loaded_approval_or_None,   # only needed for canonical
    )
    if not auth.may_mutate_canonical:
        # dry-run  -> log the intended write and return (touch nothing), or
        # shadow    -> redirect the write to auth.shadow_prefix(prefix) (a NON-canonical location)
        ...
    else:
        # canonical, fully authorized -> proceed with the real put_object / create_partition
        ...

``authorize_publish`` is the ONLY entry point a writer needs. It resolves the mode, blocks readiness
roles from canonical, runs the fail-closed environment checks, and verifies the approval artifact —
raising a :class:`PublishGuardError` subclass before returning if anything is wrong.

THE APPROVAL ARTIFACT (canonical authority)
-------------------------------------------
Canonical mode requires a :class:`PublishApproval` bound to ``environment / table / registry_hash /
git_sha / expiry`` and signed. R0 uses a **placeholder** shared-secret HMAC-SHA256 scheme
(:func:`sign_approval` / :func:`verify_approval`) so the mechanism and its call sites exist and are
tested end to end. This is deliberately NOT production-grade key management.

R1 MUST harden this (documented handoff, do not ship canonical authority on the placeholder):
  * replace the shared-secret HMAC with **KMS asymmetric Sign/Verify** (an asymmetric CMK; the
    signing key never enters the process — mirrors the milestone-boundary KMS attestation, INV-9);
  * cross-check ``registry_hash`` against the live registry hash and ``git_sha`` against the merged
    fix SHA at verify time (R0 only checks the signature covers them, not that they are *current*);
  * bind the approval to a single-use nonce / fencing token so an approval cannot be replayed.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Mapping, Optional, Sequence

from leviathan.common.constants import (
    SILVER_PUBLISHER_ROLE_NAME,
    SILVER_VALIDATOR_ROLE_NAME,
)
from leviathan.common.logging import get_logger

logger = get_logger(__name__)

# Environment variables the guard reads (documented so callers/CI can set them explicitly).
ENV_PUBLISH_MODE = "LEVIATHAN_PUBLISH_MODE"
ENV_READINESS = "LEVIATHAN_READINESS"
ENV_ROLE_ARN = "LEVIATHAN_ROLE_ARN"
ENV_APPROVAL_SECRET = "LEVIATHAN_APPROVAL_SECRET"
ENV_APPROVAL_JSON = "LEVIATHAN_APPROVAL_JSON"

# A role ARN (the caller's, or one declared in the environment) is a *readiness* identity when it
# matches this pattern. Readiness identities can never select canonical (deny-first, INV acceptance).
READINESS_ROLE_PATTERN = re.compile(r"(readiness|(^|[-_/])ci([-_/]|$))", re.IGNORECASE)


class PublishMode(str, Enum):
    """The three publish modes. ``dry-run`` is the default and mutates nothing canonical."""

    DRY_RUN = "dry-run"
    SHADOW = "shadow"
    CANONICAL = "canonical"


# ---------------------------------------------------------------------------
# Exceptions — all fail-closed denials are a PublishGuardError subclass.
# ---------------------------------------------------------------------------
class PublishGuardError(RuntimeError):
    """Base class for every publish-authorization denial. Raised BEFORE any mutation."""


class PublishModeError(PublishGuardError):
    """An unknown / malformed ``--publish-mode`` value was supplied."""


class ReadinessPublishDenied(PublishGuardError):
    """A readiness identity attempted to select canonical. Never weaken this deny (F004 rollback)."""


class EnvironmentMismatch(PublishGuardError):
    """The publish target does not match the declared environment (account/bucket/db/prefix/role)."""


class ApprovalError(PublishGuardError):
    """The canonical approval artifact is missing, unsigned, expired, or not bound to this target."""


# ---------------------------------------------------------------------------
# Declared environment + the production default.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class PublishEnvironment:
    """The declared identity of a canonical environment. A publish target must match ALL fields."""

    name: str
    account_id: str
    bucket: str
    database: str
    prefix_allowlist: tuple[str, ...]
    role_arn_pattern: str  # regex a canonical publisher's role ARN must fully match


# The one canonical production account (used to build the role-ARN pattern below).
PROD_ACCOUNT_ID = "668891723125"


def _prod_role_arn_pattern(account_id: str) -> str:
    """Build the canonical-publisher role-ARN regex.

    The dedicated silver **publisher** role (SILVER-F014) is sourced from
    :data:`leviathan.common.constants.SILVER_PUBLISHER_ROLE_NAME` -- the single
    source of truth the Terraform ``modules/iam`` role name is built from -- so
    the name is never duplicated as a bare string literal here. The legacy
    ``sagemaker-training`` / ``batch-*`` / ``glue-*`` families stay recognised for
    backward compatibility (their canonical writes still require a signed
    approval); the read-only **validator** role is deliberately EXCLUDED and is
    additionally denied deny-first via :func:`_is_readiness_role`.
    """
    publisher = re.escape(SILVER_PUBLISHER_ROLE_NAME)  # leviathan-dev-silver-publisher
    # NOTE the service split: IAM ROLE ARNs live under arn:aws:iam::, but the ARN a RUNNING
    # task sees from sts get-caller-identity is the ASSUMED-ROLE form under arn:aws:sts:: --
    # an iam-only prefix rejected every legitimate Batch container (live-proven by the BF-W1
    # canonical retirement, which failed closed on
    # arn:aws:sts::...:assumed-role/leviathan-dev-batch-job-role/<session>).
    return (
        rf"^(arn:aws:iam::{account_id}:"
        rf"(role/(leviathan-dev-(sagemaker-training|batch-[a-z0-9-]+|glue-[a-z0-9-]+)|{publisher})"
        rf"|assumed-role/leviathan-dev-[a-z0-9-]+/.+)"
        rf"|arn:aws:sts::{account_id}:assumed-role/leviathan-dev-[a-z0-9-]+/.+)$"
    )


# The one canonical production environment (account/bucket/database from the live catalog + DDL).
# A canonical publisher must run in this account, against this bucket + Glue database, write under an
# allow-listed prefix, and assume a role whose ARN matches the pattern. Anything else fails closed.
PROD_ENVIRONMENT = PublishEnvironment(
    name="leviathan_dev",
    account_id=PROD_ACCOUNT_ID,
    bucket="leviathan-dev-shahem-001",
    database="leviathan_dev",
    prefix_allowlist=("silver/", "gold/"),
    role_arn_pattern=_prod_role_arn_pattern(PROD_ACCOUNT_ID),
)


@dataclass(frozen=True)
class PublishTarget:
    """What a writer intends to touch. Populated from the live STS identity + the write location."""

    account_id: str
    bucket: str
    database: str
    prefix: str
    role_arn: str
    table: Optional[str] = None


@dataclass(frozen=True)
class PublishApproval:
    """A signed grant of canonical authority, bound to one environment+table at a point in time.

    ``expiry`` is an ISO-8601 UTC timestamp. ``signature`` is produced by :func:`sign_approval`
    (R0: HMAC-SHA256 placeholder; R1: KMS asymmetric signature)."""

    environment: str
    table: str
    registry_hash: str
    git_sha: str
    expiry: str
    signature: str


@dataclass(frozen=True)
class Authorization:
    """The guard's verdict. ``may_mutate_canonical`` is the single bit a writer branches on."""

    mode: PublishMode
    may_mutate_canonical: bool
    readiness: bool
    reason: str = ""
    _shadow_marker: str = field(default="_shadow", repr=False)

    def require_canonical(self) -> None:
        """Convenience for canonical-only writers: raise unless canonical mutation is authorized."""
        if not self.may_mutate_canonical:
            raise PublishGuardError(
                f"canonical mutation not authorized (mode={self.mode.value}; {self.reason})"
            )

    def shadow_prefix(self, prefix: str) -> str:
        """Derive a NON-canonical shadow write location from a canonical prefix (shadow mode)."""
        cleaned = prefix.strip("/")
        return f"{cleaned}/{self._shadow_marker}/" if cleaned else f"{self._shadow_marker}/"


# ---------------------------------------------------------------------------
# Mode resolution + readiness detection.
# ---------------------------------------------------------------------------
def _parse_mode_from_argv(argv: Sequence[str]) -> Optional[str]:
    """Return the ``--publish-mode`` value from an argparse-style argv, or None if absent."""
    for i, tok in enumerate(argv):
        if tok == "--publish-mode":
            return argv[i + 1] if i + 1 < len(argv) else ""
        if tok.startswith("--publish-mode="):
            return tok.split("=", 1)[1]
    return None


def resolve_publish_mode(
    argv: Optional[Sequence[str]] = None,
    env: Optional[Mapping[str, str]] = None,
) -> PublishMode:
    """Resolve the publish mode. Precedence: caller-supplied ``--publish-mode`` >
    ``LEVIATHAN_PUBLISH_MODE`` env > default ``dry-run``. An unrecognised value fails closed with
    :class:`PublishModeError`."""
    env = os.environ if env is None else env
    raw: Optional[str] = None
    if argv is not None:
        raw = _parse_mode_from_argv(argv)
    if raw is None:
        raw = env.get(ENV_PUBLISH_MODE)
    if raw is None or raw == "":
        return PublishMode.DRY_RUN
    try:
        return PublishMode(raw.strip().lower())
    except ValueError as exc:
        allowed = ", ".join(m.value for m in PublishMode)
        raise PublishModeError(
            f"unknown --publish-mode '{raw}': expected one of {allowed}"
        ) from exc


def _truthy(value: Optional[str]) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _is_readiness_role(role_arn: Optional[str]) -> bool:
    if not role_arn:
        return False
    if READINESS_ROLE_PATTERN.search(role_arn) is not None:
        return True
    # The read-only silver validator (SILVER-F014) can never publish canonical: treat it
    # deny-first like a readiness identity so even an assumed-role session of it is refused
    # BEFORE the environment check (the broad assumed-role/ branch would otherwise admit it).
    return SILVER_VALIDATOR_ROLE_NAME in role_arn


def is_readiness_context(
    env: Optional[Mapping[str, str]] = None,
    role_arn: Optional[str] = None,
) -> bool:
    """True when the caller is a readiness identity: the ``LEVIATHAN_READINESS`` env flag is truthy,
    or the role ARN (argument or ``LEVIATHAN_ROLE_ARN`` env) matches
    :data:`READINESS_ROLE_PATTERN`."""
    env = os.environ if env is None else env
    if _truthy(env.get(ENV_READINESS)):
        return True
    if _is_readiness_role(role_arn):
        return True
    return _is_readiness_role(env.get(ENV_ROLE_ARN))


# ---------------------------------------------------------------------------
# Fail-closed environment checks.
# ---------------------------------------------------------------------------
def check_environment(
    target: PublishTarget,
    environment: PublishEnvironment = PROD_ENVIRONMENT,
) -> None:
    """Fail closed unless the target matches the declared environment on EVERY invariant:
    account id, bucket, database, prefix allowlist, and role-ARN pattern. Any missing/empty field is
    a mismatch. Raises :class:`EnvironmentMismatch` listing every violation (before any mutation)."""
    problems: list[str] = []
    if target.account_id != environment.account_id:
        problems.append(
            f"account_id={target.account_id!r} != declared {environment.account_id!r}"
        )
    if target.bucket != environment.bucket:
        problems.append(f"bucket={target.bucket!r} != declared {environment.bucket!r}")
    if target.database != environment.database:
        problems.append(f"database={target.database!r} != declared {environment.database!r}")
    if not target.prefix or not any(
        target.prefix.startswith(p) for p in environment.prefix_allowlist
    ):
        problems.append(
            f"prefix={target.prefix!r} not under allowlist {list(environment.prefix_allowlist)}"
        )
    if not target.role_arn or not re.match(environment.role_arn_pattern, target.role_arn):
        problems.append(
            f"role_arn={target.role_arn!r} does not match {environment.role_arn_pattern!r}"
        )
    if problems:
        raise EnvironmentMismatch(
            f"publish target does not match environment '{environment.name}': "
            + "; ".join(problems)
        )


# ---------------------------------------------------------------------------
# Approval artifact signing + verification (R0 placeholder HMAC; R1 -> KMS).
# ---------------------------------------------------------------------------
def _canonical_payload(
    *, environment: str, table: str, registry_hash: str, git_sha: str, expiry: str
) -> bytes:
    """Deterministic, order-fixed serialization of the signed fields (newline-joined k=v)."""
    parts = [
        f"environment={environment}",
        f"table={table}",
        f"registry_hash={registry_hash}",
        f"git_sha={git_sha}",
        f"expiry={expiry}",
    ]
    return "\n".join(parts).encode("utf-8")


def sign_approval(
    *,
    environment: str,
    table: str,
    registry_hash: str,
    git_sha: str,
    expiry: str,
    secret: str,
) -> str:
    """Produce the approval signature (R0 placeholder: HMAC-SHA256 over the canonical payload).

    R1 replaces this with a KMS ``Sign`` call against an asymmetric CMK; callers of this helper
    (the approval *issuer* and the verification path) are the only sites R1 must re-point."""
    if not secret:
        raise ApprovalError("cannot sign an approval without a signing secret/key")
    payload = _canonical_payload(
        environment=environment,
        table=table,
        registry_hash=registry_hash,
        git_sha=git_sha,
        expiry=expiry,
    )
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def _parse_iso_utc(value: str) -> datetime:
    raw = (value or "").strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ApprovalError(f"approval expiry is not ISO-8601: {value!r}") from exc
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def verify_approval(
    approval: PublishApproval,
    target: PublishTarget,
    environment: PublishEnvironment = PROD_ENVIRONMENT,
    *,
    now: Optional[datetime] = None,
    secret: Optional[str] = None,
) -> None:
    """Fail closed unless the approval is (1) bound to this environment+table, (2) signed with a
    valid signature, and (3) unexpired. Raises :class:`ApprovalError` otherwise (before mutation).

    R0 note: signature verification is the placeholder HMAC scheme; ``registry_hash``/``git_sha`` are
    covered by the signature but NOT cross-checked against live state until R1 (see module docstring).
    """
    if approval is None:  # defensive: callers should branch earlier
        raise ApprovalError("canonical publish requires a signed approval artifact")
    if approval.environment != environment.name:
        raise ApprovalError(
            f"approval environment {approval.environment!r} != target environment "
            f"{environment.name!r}"
        )
    if target.table is not None and approval.table != target.table:
        raise ApprovalError(
            f"approval table {approval.table!r} != target table {target.table!r}"
        )
    if secret is None:
        secret = os.environ.get(ENV_APPROVAL_SECRET)
    if not secret:
        raise ApprovalError(
            f"no signing secret available to verify approval (set {ENV_APPROVAL_SECRET})"
        )
    expected = sign_approval(
        environment=approval.environment,
        table=approval.table,
        registry_hash=approval.registry_hash,
        git_sha=approval.git_sha,
        expiry=approval.expiry,
        secret=secret,
    )
    if not hmac.compare_digest(expected, approval.signature or ""):
        raise ApprovalError("approval signature is invalid")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    if now > _parse_iso_utc(approval.expiry):
        raise ApprovalError(f"approval expired at {approval.expiry} (now {now.isoformat()})")


def load_approval_from_env(env: Optional[Mapping[str, str]] = None) -> Optional[PublishApproval]:
    """Deserialize a :class:`PublishApproval` from ``LEVIATHAN_APPROVAL_JSON``.

    This is the containerOverrides seam (BF-W1): a Batch task has no filesystem or argv channel
    for the approval artifact, so the orchestrator threads the signed approval as a JSON env var
    and the verifying process still holds ``LEVIATHAN_APPROVAL_SECRET`` separately. Absent/blank
    returns ``None`` (canonical then fails closed exactly as before); a PRESENT but malformed
    value raises :class:`ApprovalError` -- a garbled approval must never silently degrade into
    "no approval was provided"."""
    env = os.environ if env is None else env
    raw = (env.get(ENV_APPROVAL_JSON) or "").strip()
    if not raw:
        return None
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise TypeError(f"expected a JSON object, got {type(data).__name__}")
        return PublishApproval(**data)
    except (ValueError, TypeError) as exc:
        raise ApprovalError(
            f"{ENV_APPROVAL_JSON} is present but not a valid approval artifact: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# The one entry point writers call.
# ---------------------------------------------------------------------------
def authorize_publish(
    target: PublishTarget,
    *,
    mode: Optional[PublishMode] = None,
    approval: Optional[PublishApproval] = None,
    argv: Optional[Sequence[str]] = None,
    env: Optional[Mapping[str, str]] = None,
    environment: PublishEnvironment = PROD_ENVIRONMENT,
    now: Optional[datetime] = None,
    secret: Optional[str] = None,
) -> Authorization:
    """Authorize (or deny) a publish. The thin integration hook every writer adopts.

    Order (all denials raise BEFORE returning, i.e. before any mutation):
      1. resolve the mode (default ``dry-run``);
      2. readiness identity + canonical -> hard deny (:class:`ReadinessPublishDenied`);
      3. ``dry-run`` / ``shadow`` -> authorized but ``may_mutate_canonical=False``;
      4. ``canonical`` -> fail-closed environment checks, then a valid signed approval, else raise.
    """
    env = os.environ if env is None else env
    if mode is None:
        mode = resolve_publish_mode(argv, env)
    readiness = is_readiness_context(env, role_arn=target.role_arn)

    if mode is PublishMode.CANONICAL and readiness:
        raise ReadinessPublishDenied(
            "readiness identities cannot select --publish-mode canonical; "
            "canonical authority is reserved for a signed post-R4 approval"
        )

    if mode in (PublishMode.DRY_RUN, PublishMode.SHADOW):
        logger.info(
            "publish authorized non-canonical: mode=%s table=%s readiness=%s",
            mode.value, target.table, readiness,
        )
        return Authorization(
            mode=mode,
            may_mutate_canonical=False,
            readiness=readiness,
            reason="non-canonical mode never touches the canonical surface",
        )

    # mode is CANONICAL and caller is not a readiness identity.
    check_environment(target, environment)  # raises EnvironmentMismatch before any mutation
    if approval is None:
        approval = load_approval_from_env(env)
    if approval is None:
        raise ApprovalError(
            "canonical publish requires a signed approval artifact "
            "(environment/table/registry-hash/git-SHA/expiry)"
        )
    verify_approval(approval, target, environment, now=now, secret=secret)  # raises on any problem
    logger.info(
        "publish authorized CANONICAL: table=%s git_sha=%s expiry=%s",
        target.table, approval.git_sha, approval.expiry,
    )
    return Authorization(
        mode=PublishMode.CANONICAL,
        may_mutate_canonical=True,
        readiness=readiness,
        reason="environment matched and approval verified",
    )
