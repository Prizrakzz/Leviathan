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

R1 (this module, behind ``LEVIATHAN_APPROVAL_MODE``): requirement (1) below is IMPLEMENTED. The
``kms`` mode replaces the shared-secret HMAC with KMS asymmetric ECDSA sign (mint) + cached
public-key verify (an asymmetric SIGN_VERIFY CMK; the private key never enters the process). The
``hmac`` mode stays the DEFAULT (R0 fallback, behaviour byte-identical to before) until the KMS
canary proves out. Requirements (2) and (3) are DELIBERATELY NOT implemented on the scheduled
self-mint path -- in a self-minting model the payload binding is not the control, the GATE is (a
stale / rolled-back self-mint still fails the freshly-run rebuild gate, INV-6). Do NOT represent the
registry_hash/git_sha binding as a stale-image or replay defence.
  (1) DONE: replace the shared-secret HMAC with KMS asymmetric ``Sign`` (mint) + cached-public-key
      verify. NO ``kms:Verify`` call is ever made -- an asymmetric SIGN_VERIFY signature is checked
      with the PUBLIC key, which is public, so verification needs no KMS permission or identity.
  (2) GATE-FIRST (not done here): cross-check ``registry_hash`` against the live registry hash and
      ``git_sha`` against the deployed image SHA at verify time.
  (3) GATE-FIRST (not done here): bind a single-use nonce / fencing token so an approval cannot be
      replayed.

The signing MODE is selected by ``LEVIATHAN_APPROVAL_MODE`` (``kms`` | ``hmac``; default ``hmac``).
KMS mint reads the CMK key id from ``LEVIATHAN_KMS_KEY_ID``; KMS verify reads the verification
public key from ``LEVIATHAN_KMS_PUBLIC_KEY_PEM`` (a PEM string) when present, otherwise fetches it
ONCE via ``kms:GetPublicKey`` for the key id and caches it in-process.
"""
from __future__ import annotations

import base64
import binascii
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
# R1 KMS-asymmetric approval-signing contract (the SFN promote task sets these for the scheduled
# self-mint path). ENV_APPROVAL_MODE selects hmac (R0 default) vs kms; ENV_KMS_KEY_ID names the
# SIGN_VERIFY CMK the mint path signs with; ENV_KMS_PUBLIC_KEY_PEM (optional) short-circuits the
# one-time kms:GetPublicKey fetch on the verify path.
ENV_APPROVAL_MODE = "LEVIATHAN_APPROVAL_MODE"
ENV_KMS_KEY_ID = "LEVIATHAN_KMS_KEY_ID"
ENV_KMS_PUBLIC_KEY_PEM = "LEVIATHAN_KMS_PUBLIC_KEY_PEM"

# The KMS SIGN_VERIFY signing algorithm this module mints + verifies with (ECC_NIST_P256 CMK).
KMS_SIGNING_ALGORITHM = "ECDSA_SHA_256"

# A role ARN (the caller's, or one declared in the environment) is a *readiness* identity when it
# matches this pattern. Readiness identities can never select canonical (deny-first, INV acceptance).
READINESS_ROLE_PATTERN = re.compile(r"(readiness|(^|[-_/])ci([-_/]|$))", re.IGNORECASE)


class PublishMode(str, Enum):
    """The three publish modes. ``dry-run`` is the default and mutates nothing canonical."""

    DRY_RUN = "dry-run"
    SHADOW = "shadow"
    CANONICAL = "canonical"


class ApprovalMode(str, Enum):
    """How a canonical approval is signed + verified. ``hmac`` is the R0 placeholder (default);
    ``kms`` is the R1 asymmetric signer (mint via ``kms:Sign``, verify via the cached public key)."""

    HMAC = "hmac"
    KMS = "kms"


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


# ---------------------------------------------------------------------------
# R1 KMS asymmetric signing (mint via kms:Sign; verify via the cached public key -- NO kms:Verify).
# ---------------------------------------------------------------------------
def resolve_approval_mode(
    mode: Optional[object] = None,
    env: Optional[Mapping[str, str]] = None,
) -> ApprovalMode:
    """Resolve the approval signing mode. Precedence: explicit ``mode`` arg >
    ``LEVIATHAN_APPROVAL_MODE`` env > default ``hmac`` (R0). An unrecognised value fails closed."""
    if isinstance(mode, ApprovalMode):
        return mode
    env = os.environ if env is None else env
    raw = mode if mode is not None else env.get(ENV_APPROVAL_MODE)
    if raw is None or str(raw).strip() == "":
        return ApprovalMode.HMAC
    try:
        return ApprovalMode(str(raw).strip().lower())
    except ValueError as exc:
        allowed = ", ".join(m.value for m in ApprovalMode)
        raise ApprovalError(
            f"unknown {ENV_APPROVAL_MODE} '{raw}': expected one of {allowed}"
        ) from exc


def _default_kms_client():
    """Build a real boto3 KMS client (only reached on the live KMS path; tests stub this seam)."""
    try:
        import boto3
    except ImportError as exc:  # pragma: no cover - boto3 is a runtime dependency
        raise ApprovalError(
            "boto3 is required for KMS approval signing but is not importable"
        ) from exc
    return boto3.client("kms")


def sign_approval_kms(
    *,
    environment: str,
    table: str,
    registry_hash: str,
    git_sha: str,
    expiry: str,
    key_id: Optional[str],
    kms_client: Optional[object] = None,
) -> str:
    """Sign the canonical approval payload with an asymmetric KMS CMK (``kms:Sign``, ECDSA_SHA_256).

    Returns the DER ECDSA signature base64-encoded (a JSON/env-safe string for ``PublishApproval.
    signature``). The private key never leaves KMS. Fails closed if no key id is supplied."""
    if not key_id:
        raise ApprovalError(
            f"cannot KMS-sign an approval without a CMK key id (set {ENV_KMS_KEY_ID})"
        )
    payload = _canonical_payload(
        environment=environment,
        table=table,
        registry_hash=registry_hash,
        git_sha=git_sha,
        expiry=expiry,
    )
    client = _default_kms_client() if kms_client is None else kms_client
    resp = client.sign(
        KeyId=key_id,
        Message=payload,
        MessageType="RAW",
        SigningAlgorithm=KMS_SIGNING_ALGORITHM,
    )
    signature = resp["Signature"]
    if not isinstance(signature, (bytes, bytearray)):
        signature = bytes(signature)
    return base64.b64encode(bytes(signature)).decode("ascii")


# In-process cache of verification public keys. Keyed by "pem:<sha256>" (inline PEM) or
# "kms:<key_id>" (fetched once via kms:GetPublicKey). Verification NEVER calls kms:Verify.
_KMS_PUBLIC_KEY_CACHE: dict = {}


def reset_public_key_cache() -> None:
    """Clear the in-process verification-public-key cache (test seam / key-rotation hook)."""
    _KMS_PUBLIC_KEY_CACHE.clear()


def _load_public_key_from_pem(pem: str) -> object:
    from cryptography.hazmat.primitives.serialization import load_pem_public_key

    raw = pem.encode("utf-8") if isinstance(pem, str) else pem
    try:
        return load_pem_public_key(raw)
    except (ValueError, TypeError) as exc:
        raise ApprovalError(
            f"could not parse {ENV_KMS_PUBLIC_KEY_PEM} as a PEM public key: {exc}"
        ) from exc


def _fetch_public_key_from_kms(key_id: str, kms_client: Optional[object] = None) -> object:
    from cryptography.hazmat.primitives.serialization import load_der_public_key

    client = _default_kms_client() if kms_client is None else kms_client
    resp = client.get_public_key(KeyId=key_id)
    der = resp["PublicKey"]
    if not isinstance(der, (bytes, bytearray)):
        der = bytes(der)
    try:
        return load_der_public_key(bytes(der))
    except (ValueError, TypeError) as exc:
        raise ApprovalError(
            f"kms:GetPublicKey for {key_id!r} did not return a parseable DER public key: {exc}"
        ) from exc


def get_kms_public_key(
    *,
    key_id: Optional[str] = None,
    public_key_pem: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
    kms_client: Optional[object] = None,
) -> object:
    """Return the cached ECDSA verification public key. Sourced from ``LEVIATHAN_KMS_PUBLIC_KEY_PEM``
    (or the ``public_key_pem`` arg) when present, else fetched ONCE via ``kms:GetPublicKey`` for the
    key id and cached in-process. This path performs signature verification locally and NEVER calls
    ``kms:Verify`` -- the validator identity needs no KMS grant. Fails closed if neither a PEM nor a
    key id is available."""
    env = os.environ if env is None else env
    pem = public_key_pem if public_key_pem is not None else env.get(ENV_KMS_PUBLIC_KEY_PEM)
    if pem:
        digest = hashlib.sha256(pem.encode("utf-8") if isinstance(pem, str) else pem).hexdigest()
        cache_key = f"pem:{digest}"
        cached = _KMS_PUBLIC_KEY_CACHE.get(cache_key)
        if cached is None:
            cached = _load_public_key_from_pem(pem)
            _KMS_PUBLIC_KEY_CACHE[cache_key] = cached
        return cached
    key_id = key_id if key_id is not None else env.get(ENV_KMS_KEY_ID)
    if not key_id:
        raise ApprovalError(
            f"no KMS public key available to verify approval "
            f"(set {ENV_KMS_PUBLIC_KEY_PEM} or {ENV_KMS_KEY_ID})"
        )
    cache_key = f"kms:{key_id}"
    cached = _KMS_PUBLIC_KEY_CACHE.get(cache_key)
    if cached is None:
        cached = _fetch_public_key_from_kms(key_id, kms_client=kms_client)
        _KMS_PUBLIC_KEY_CACHE[cache_key] = cached
    return cached


def verify_approval_kms(
    approval: PublishApproval,
    *,
    key_id: Optional[str] = None,
    public_key_pem: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
    kms_client: Optional[object] = None,
) -> None:
    """Verify a KMS-signed approval signature against the CACHED public key (no ``kms:Verify``).

    Raises :class:`ApprovalError` if the signature is malformed or does not verify. Binding + expiry
    are enforced by :func:`verify_approval` (this checks the cryptographic signature only)."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec

    public_key = get_kms_public_key(
        key_id=key_id, public_key_pem=public_key_pem, env=env, kms_client=kms_client
    )
    if not isinstance(public_key, ec.EllipticCurvePublicKey):
        raise ApprovalError(
            "KMS verification public key is not an ECDSA key; expected an ECC_NIST_P256 "
            f"SIGN_VERIFY CMK for {KMS_SIGNING_ALGORITHM}"
        )
    payload = _canonical_payload(
        environment=approval.environment,
        table=approval.table,
        registry_hash=approval.registry_hash,
        git_sha=approval.git_sha,
        expiry=approval.expiry,
    )
    try:
        signature = base64.b64decode(approval.signature or "", validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ApprovalError("approval signature is not valid base64 (KMS mode)") from exc
    try:
        public_key.verify(signature, payload, ec.ECDSA(hashes.SHA256()))
    except InvalidSignature as exc:
        raise ApprovalError(
            "approval signature is invalid (KMS asymmetric public-key verify failed)"
        ) from exc


def mint_approval(
    *,
    environment: str,
    table: str,
    registry_hash: str,
    git_sha: str,
    expiry: str,
    mode: Optional[object] = None,
    env: Optional[Mapping[str, str]] = None,
    secret: Optional[str] = None,
    key_id: Optional[str] = None,
    kms_client: Optional[object] = None,
) -> PublishApproval:
    """Build + sign a :class:`PublishApproval` in the resolved mode (``hmac`` R0 or ``kms`` R1).

    This is the mint seam the SFN promote task uses to self-issue a short-lived canonical grant with
    NO plaintext secret (kms mode) and NO human. Mode/key id are resolved from the environment when
    not passed explicitly."""
    resolved_mode = resolve_approval_mode(mode, env)
    if resolved_mode is ApprovalMode.KMS:
        env_map = os.environ if env is None else env
        resolved_key_id = key_id if key_id is not None else env_map.get(ENV_KMS_KEY_ID)
        signature = sign_approval_kms(
            environment=environment,
            table=table,
            registry_hash=registry_hash,
            git_sha=git_sha,
            expiry=expiry,
            key_id=resolved_key_id,
            kms_client=kms_client,
        )
    else:
        if secret is None:
            secret = os.environ.get(ENV_APPROVAL_SECRET)
        signature = sign_approval(
            environment=environment,
            table=table,
            registry_hash=registry_hash,
            git_sha=git_sha,
            expiry=expiry,
            secret=secret,
        )
    return PublishApproval(
        environment=environment,
        table=table,
        registry_hash=registry_hash,
        git_sha=git_sha,
        expiry=expiry,
        signature=signature,
    )


def verify_approval(
    approval: PublishApproval,
    target: PublishTarget,
    environment: PublishEnvironment = PROD_ENVIRONMENT,
    *,
    now: Optional[datetime] = None,
    secret: Optional[str] = None,
    mode: Optional[object] = None,
    env: Optional[Mapping[str, str]] = None,
    key_id: Optional[str] = None,
    public_key_pem: Optional[str] = None,
    kms_client: Optional[object] = None,
) -> None:
    """Fail closed unless the approval is (1) bound to this environment+table, (2) signed with a
    valid signature, and (3) unexpired. Raises :class:`ApprovalError` otherwise (before mutation).

    The signature check dispatches on the resolved :class:`ApprovalMode` (``LEVIATHAN_APPROVAL_MODE``,
    default ``hmac``). ``hmac`` is the R0 placeholder path (byte-identical to before); ``kms`` verifies
    the KMS asymmetric signature against the cached public key -- no ``kms:Verify`` call.

    Note: ``registry_hash``/``git_sha`` are covered by the signature but NOT cross-checked against
    live state, and no nonce is bound -- those remain GATE-FIRST controls (see module docstring).
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
    resolved_mode = resolve_approval_mode(mode, env)
    if resolved_mode is ApprovalMode.KMS:
        verify_approval_kms(
            approval,
            key_id=key_id,
            public_key_pem=public_key_pem,
            env=env,
            kms_client=kms_client,
        )
    else:
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
    approval_mode: Optional[object] = None,
    key_id: Optional[str] = None,
    public_key_pem: Optional[str] = None,
    kms_client: Optional[object] = None,
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
    if approval is None and resolve_approval_mode(env=env, mode=approval_mode) is ApprovalMode.KMS:
        # R1 scheduled self-mint (A-W1): in kms mode the promote container mints its own
        # short-lived approval via kms:Sign under the silver-publisher role. The payload binding
        # is NOT a stale-image/replay control on this path (plan Risk #1) -- GATE-FIRST +
        # SHADOW-FIRST + the kms:Sign IAM scope are the controls. Verification below runs in full.
        from datetime import timedelta as _timedelta
        _e = env if env is not None else os.environ
        approval = mint_approval(
            environment=environment.name,
            table=target.table or "",
            registry_hash=_e.get("LEVIATHAN_REGISTRY_HASH", "self-mint"),
            git_sha=_e.get("LEVIATHAN_GIT_SHA", "self-mint"),
            expiry=(datetime.now(timezone.utc) + _timedelta(minutes=30)).isoformat(),
            mode=ApprovalMode.KMS,
            env=env,
            key_id=key_id,
            kms_client=kms_client,
        )
        logger.info("publish approval SELF-MINTED via kms:Sign: table=%s", target.table)
    if approval is None:
        raise ApprovalError(
            "canonical publish requires a signed approval artifact "
            "(environment/table/registry-hash/git-SHA/expiry)"
        )
    verify_approval(  # raises on any problem
        approval,
        target,
        environment,
        now=now,
        secret=secret,
        mode=approval_mode,
        env=env,
        key_id=key_id,
        public_key_pem=public_key_pem,
        kms_client=kms_client,
    )
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
