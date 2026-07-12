"""SILVER-F014 (Milestone R1) -- two-role validator/publisher separation, code side.

These pin the *code* half of F014: the role NAMES live in one place
(``leviathan.common.constants``) and ``publish_guard`` consumes them so the
canonical role-ARN pattern is not a duplicated string literal, the gated
**publisher** role is recognised as canonical-capable, and the read-only
**validator** role can NEVER publish canonical (deny-first, even as an assumed
-role session and even with an otherwise-valid signed approval).

Fully hermetic: no boto3, no network, no AWS -- the guard only decides.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import pytest
from leviathan.common.constants import (
    IAM_ROLE_NAME_PREFIX,
    SILVER_PUBLISHER_ROLE_NAME,
    SILVER_VALIDATOR_ROLE_NAME,
)
from leviathan.common.publish_guard import (
    PROD_ACCOUNT_ID,
    PROD_ENVIRONMENT,
    PublishApproval,
    PublishMode,
    PublishTarget,
    ReadinessPublishDenied,
    authorize_publish,
    check_environment,
    is_readiness_context,
    sign_approval,
)

_SECRET = "r0-placeholder-secret"
_PUBLISHER_ROLE = f"arn:aws:iam::{PROD_ACCOUNT_ID}:role/{SILVER_PUBLISHER_ROLE_NAME}"
_VALIDATOR_ROLE = f"arn:aws:iam::{PROD_ACCOUNT_ID}:role/{SILVER_VALIDATOR_ROLE_NAME}"
# The exact hole closed by the deny-first wiring: a validator *assumed-role session*
# would otherwise be admitted by the broad `assumed-role/leviathan-dev-*` branch.
_VALIDATOR_ASSUMED = (
    f"arn:aws:sts::{PROD_ACCOUNT_ID}:assumed-role/{SILVER_VALIDATOR_ROLE_NAME}/val-session"
)


def _target(role_arn: str) -> PublishTarget:
    return PublishTarget(
        account_id=PROD_ACCOUNT_ID,
        bucket="leviathan-dev-shahem-001",
        database="leviathan_dev",
        prefix="silver/esr/",
        role_arn=role_arn,
        table="silver_esr_compact",
    )


def _approval() -> PublishApproval:
    fields = dict(
        environment="leviathan_dev",
        table="silver_esr_compact",
        registry_hash="reg-abc123",
        git_sha="deadbeef",
        expiry=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
    )
    return PublishApproval(signature=sign_approval(secret=_SECRET, **fields), **fields)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Constants: the single source of truth for the two role names.
# ---------------------------------------------------------------------------
def test_role_names_are_built_from_one_prefix() -> None:
    assert IAM_ROLE_NAME_PREFIX == "leviathan-dev"
    assert SILVER_VALIDATOR_ROLE_NAME == "leviathan-dev-silver-validator"
    assert SILVER_PUBLISHER_ROLE_NAME == "leviathan-dev-silver-publisher"


def test_publish_guard_pattern_sources_the_publisher_name_no_dup() -> None:
    # The pattern must be BUILT from the constant (re.escape'd), not a hand-copied
    # literal -- a rename of the role in one place cannot silently diverge.
    assert re.escape(SILVER_PUBLISHER_ROLE_NAME) in PROD_ENVIRONMENT.role_arn_pattern
    # ...and functionally: the exact publisher ARN matches, a renamed one does not.
    assert re.match(PROD_ENVIRONMENT.role_arn_pattern, _PUBLISHER_ROLE)
    assert not re.match(PROD_ENVIRONMENT.role_arn_pattern, _PUBLISHER_ROLE + "-renamed-x")
    # And the validator must NOT appear as a canonical-capable role in the pattern.
    assert re.escape(SILVER_VALIDATOR_ROLE_NAME) not in PROD_ENVIRONMENT.role_arn_pattern


# ---------------------------------------------------------------------------
# Publisher role -- the single canonical-capable identity.
# ---------------------------------------------------------------------------
def test_publisher_role_passes_environment_check() -> None:
    check_environment(_target(_PUBLISHER_ROLE))  # does not raise


def test_publisher_role_is_not_flagged_readiness() -> None:
    assert is_readiness_context(env={}, role_arn=_PUBLISHER_ROLE) is False


def test_publisher_role_canonical_with_approval_is_authorized() -> None:
    auth = authorize_publish(
        _target(_PUBLISHER_ROLE),
        mode=PublishMode.CANONICAL,
        approval=_approval(),
        env={},
        secret=_SECRET,
    )
    assert auth.may_mutate_canonical is True
    assert auth.mode is PublishMode.CANONICAL


# ---------------------------------------------------------------------------
# Validator role -- read-only, deny-first, can never publish canonical.
# ---------------------------------------------------------------------------
def test_validator_role_is_readiness_deny_first() -> None:
    assert is_readiness_context(env={}, role_arn=_VALIDATOR_ROLE) is True
    # the assumed-role session form (the closed hole) is denied too.
    assert is_readiness_context(env={}, role_arn=_VALIDATOR_ASSUMED) is True


def test_validator_role_cannot_select_canonical_even_with_approval() -> None:
    with pytest.raises(ReadinessPublishDenied):
        authorize_publish(
            _target(_VALIDATOR_ROLE),
            mode=PublishMode.CANONICAL,
            approval=_approval(),
            env={},
            secret=_SECRET,
        )


def test_validator_assumed_role_session_cannot_select_canonical() -> None:
    with pytest.raises(ReadinessPublishDenied):
        authorize_publish(
            _target(_VALIDATOR_ASSUMED),
            mode=PublishMode.CANONICAL,
            approval=_approval(),
            env={},
            secret=_SECRET,
        )
