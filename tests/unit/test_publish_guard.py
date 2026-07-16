"""Tests for the readiness kill switch (SILVER-F004).

Pins the four package requirements: (1) a canonical write from a readiness context is denied before
any mutation, (2) a caller-supplied ``--publish-mode canonical`` without an approval artifact is
rejected, (3) ``dry-run`` is the default mode, and (4) the fail-closed environment checks trip on a
mismatched bucket / account. Fully hermetic: no boto3, no network, no AWS — the guard only decides,
it never mutates, so these assert on raised exceptions and return values only.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from leviathan.common.publish_guard import (
    ENV_APPROVAL_MODE,
    ENV_KMS_KEY_ID,
    ENV_KMS_PUBLIC_KEY_PEM,
    PROD_ENVIRONMENT,
    ApprovalError,
    ApprovalMode,
    Authorization,
    EnvironmentMismatch,
    PublishApproval,
    PublishGuardError,
    PublishMode,
    PublishModeError,
    PublishTarget,
    ReadinessPublishDenied,
    authorize_publish,
    check_environment,
    is_readiness_context,
    mint_approval,
    reset_public_key_cache,
    resolve_approval_mode,
    resolve_publish_mode,
    sign_approval,
    sign_approval_kms,
    load_approval_from_env,
    verify_approval,
    verify_approval_kms,
)

_SECRET = "r0-placeholder-secret"
_CANONICAL_ROLE = "arn:aws:iam::668891723125:role/leviathan-dev-sagemaker-training"
_READINESS_ROLE = "arn:aws:iam::668891723125:role/leviathan-dev-readiness-ci"


def _good_target(**over: object) -> PublishTarget:
    base = dict(
        account_id="668891723125",
        bucket="leviathan-dev-shahem-001",
        database="leviathan_dev",
        prefix="silver/model_predictions/",
        role_arn=_CANONICAL_ROLE,
        table="silver_model_predictions",
    )
    base.update(over)
    return PublishTarget(**base)  # type: ignore[arg-type]


def _valid_approval(**over: object) -> PublishApproval:
    expiry = over.pop(
        "expiry", (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    )
    fields = dict(
        environment="leviathan_dev",
        table="silver_model_predictions",
        registry_hash="reg-abc123",
        git_sha="deadbeef",
        expiry=expiry,
    )
    fields.update(over)
    signature = sign_approval(secret=_SECRET, **fields)  # type: ignore[arg-type]
    return PublishApproval(signature=signature, **fields)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# (3) dry-run is the default.
# ---------------------------------------------------------------------------
def test_dry_run_is_the_default_mode() -> None:
    assert resolve_publish_mode(argv=[], env={}) is PublishMode.DRY_RUN
    assert resolve_publish_mode(argv=["train_commodity.py"], env={}) is PublishMode.DRY_RUN


def test_default_authorization_never_mutates_canonical() -> None:
    auth = authorize_publish(_good_target(), argv=["prog"], env={})
    assert isinstance(auth, Authorization)
    assert auth.mode is PublishMode.DRY_RUN
    assert auth.may_mutate_canonical is False


def test_mode_precedence_argv_over_env() -> None:
    # caller-supplied --publish-mode wins over the env default.
    assert (
        resolve_publish_mode(argv=["p", "--publish-mode", "shadow"],
                             env={"LEVIATHAN_PUBLISH_MODE": "canonical"})
        is PublishMode.SHADOW
    )
    assert (
        resolve_publish_mode(argv=["p", "--publish-mode=shadow"], env={})
        is PublishMode.SHADOW
    )
    # env is used only when argv does not carry the flag.
    assert (
        resolve_publish_mode(argv=["p"], env={"LEVIATHAN_PUBLISH_MODE": "shadow"})
        is PublishMode.SHADOW
    )


def test_unknown_mode_fails_closed() -> None:
    with pytest.raises(PublishModeError):
        resolve_publish_mode(argv=["p", "--publish-mode", "publish-now"], env={})


def test_shadow_mode_is_authorized_but_non_canonical() -> None:
    auth = authorize_publish(_good_target(), mode=PublishMode.SHADOW, env={})
    assert auth.may_mutate_canonical is False
    # shadow writes route to a NON-canonical location.
    assert auth.shadow_prefix("silver/model_predictions/") == "silver/model_predictions/_shadow/"


# ---------------------------------------------------------------------------
# (1) canonical from a readiness context is denied before mutation.
# ---------------------------------------------------------------------------
def test_readiness_env_flag_cannot_select_canonical() -> None:
    with pytest.raises(ReadinessPublishDenied):
        authorize_publish(
            _good_target(),
            mode=PublishMode.CANONICAL,
            approval=_valid_approval(),
            env={"LEVIATHAN_READINESS": "1"},
            secret=_SECRET,
        )


def test_readiness_role_arn_cannot_select_canonical() -> None:
    # even with a perfectly valid approval + matching env, a readiness role is denied.
    with pytest.raises(ReadinessPublishDenied):
        authorize_publish(
            _good_target(role_arn=_READINESS_ROLE),
            mode=PublishMode.CANONICAL,
            approval=_valid_approval(),
            env={},
            secret=_SECRET,
        )


def test_readiness_cli_canonical_is_rejected() -> None:
    # the kill switch rejects a caller-supplied --publish-mode canonical from a readiness role.
    with pytest.raises(ReadinessPublishDenied):
        authorize_publish(
            _good_target(),
            argv=["train_commodity.py", "--publish-mode", "canonical"],
            approval=_valid_approval(),
            env={"LEVIATHAN_READINESS": "true"},
            secret=_SECRET,
        )


def test_is_readiness_context_detection() -> None:
    assert is_readiness_context(env={"LEVIATHAN_READINESS": "yes"}) is True
    assert is_readiness_context(env={}, role_arn=_READINESS_ROLE) is True
    assert is_readiness_context(env={"LEVIATHAN_ROLE_ARN": _READINESS_ROLE}) is True
    assert is_readiness_context(env={}, role_arn=_CANONICAL_ROLE) is False


# ---------------------------------------------------------------------------
# (2) --publish-mode canonical without an approval artifact is rejected.
# ---------------------------------------------------------------------------
def test_canonical_without_approval_is_rejected() -> None:
    with pytest.raises(ApprovalError):
        authorize_publish(
            _good_target(),
            argv=["train_commodity.py", "--publish-mode", "canonical"],
            approval=None,
            env={},
            secret=_SECRET,
        )


def test_canonical_with_valid_approval_is_authorized() -> None:
    auth = authorize_publish(
        _good_target(),
        mode=PublishMode.CANONICAL,
        approval=_valid_approval(),
        env={},
        secret=_SECRET,
    )
    assert auth.may_mutate_canonical is True
    assert auth.mode is PublishMode.CANONICAL
    auth.require_canonical()  # does not raise


def test_canonical_with_tampered_signature_is_rejected() -> None:
    bad = _valid_approval()
    tampered = PublishApproval(
        environment=bad.environment,
        table=bad.table,
        registry_hash="reg-DIFFERENT",  # payload changed, signature no longer covers it
        git_sha=bad.git_sha,
        expiry=bad.expiry,
        signature=bad.signature,
    )
    with pytest.raises(ApprovalError):
        authorize_publish(
            _good_target(), mode=PublishMode.CANONICAL, approval=tampered, env={}, secret=_SECRET
        )


def test_expired_approval_is_rejected() -> None:
    expired = _valid_approval(
        expiry=(datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    )
    with pytest.raises(ApprovalError):
        authorize_publish(
            _good_target(), mode=PublishMode.CANONICAL, approval=expired, env={}, secret=_SECRET
        )


def test_approval_for_other_table_is_rejected() -> None:
    other = _valid_approval(table="silver_esr")
    with pytest.raises(ApprovalError):
        authorize_publish(
            _good_target(), mode=PublishMode.CANONICAL, approval=other, env={}, secret=_SECRET
        )


def test_verify_without_secret_fails_closed() -> None:
    with pytest.raises(ApprovalError):
        verify_approval(_valid_approval(), _good_target(), secret="")


# ---------------------------------------------------------------------------
# (4) environment fail-closed checks trip on a mismatched bucket / account.
# ---------------------------------------------------------------------------
def test_environment_check_passes_for_matching_target() -> None:
    check_environment(_good_target())  # does not raise


def test_environment_check_trips_on_wrong_bucket() -> None:
    with pytest.raises(EnvironmentMismatch) as exc:
        check_environment(_good_target(bucket="some-other-bucket"))
    assert "bucket" in str(exc.value)


def test_environment_check_trips_on_wrong_account() -> None:
    with pytest.raises(EnvironmentMismatch) as exc:
        check_environment(_good_target(account_id="000000000000"))
    assert "account_id" in str(exc.value)


def test_environment_check_trips_on_stub_bucket_placeholder() -> None:
    # the exact pollution signature: the daily minter registered s3://bucket/... (literal "bucket").
    with pytest.raises(EnvironmentMismatch):
        check_environment(_good_target(bucket="bucket"))


def test_environment_check_trips_on_prefix_outside_allowlist() -> None:
    with pytest.raises(EnvironmentMismatch) as exc:
        check_environment(_good_target(prefix="scratch/pollution/"))
    assert "prefix" in str(exc.value)


def test_environment_check_trips_on_non_publisher_role() -> None:
    with pytest.raises(EnvironmentMismatch) as exc:
        check_environment(_good_target(role_arn="arn:aws:iam::668891723125:user/leviathan-dev"))
    assert "role_arn" in str(exc.value)


def test_canonical_denied_before_mutation_on_env_mismatch() -> None:
    # a canonical attempt against the wrong account raises the environment gate (not the approval).
    with pytest.raises(EnvironmentMismatch):
        authorize_publish(
            _good_target(account_id="000000000000"),
            mode=PublishMode.CANONICAL,
            approval=_valid_approval(),
            env={},
            secret=_SECRET,
        )


def test_all_denials_share_a_base_type() -> None:
    for exc in (ReadinessPublishDenied, EnvironmentMismatch, ApprovalError, PublishModeError):
        assert issubclass(exc, PublishGuardError)


def test_prod_environment_matches_live_catalog_identity() -> None:
    # the declared environment is pinned to the live account/bucket/database (the R0 baseline).
    assert PROD_ENVIRONMENT.account_id == "668891723125"
    assert PROD_ENVIRONMENT.bucket == "leviathan-dev-shahem-001"
    assert PROD_ENVIRONMENT.database == "leviathan_dev"


# ---------------------------------------------------------------------------
# (5) the LEVIATHAN_APPROVAL_JSON containerOverrides seam (BF-W1 loader).
# ---------------------------------------------------------------------------
def _approval_json(**over: object) -> str:
    import dataclasses
    import json as _json

    return _json.dumps(dataclasses.asdict(_valid_approval(**over)))


def test_load_approval_from_env_absent_is_none() -> None:
    assert load_approval_from_env({}) is None
    assert load_approval_from_env({"LEVIATHAN_APPROVAL_JSON": "   "}) is None


def test_load_approval_from_env_malformed_raises_not_none() -> None:
    # a garbled approval must never degrade into "no approval was provided"
    for bad in ('{"table": ', '"just-a-string"', '["a","list"]', '{"unknown_field": 1}'):
        with pytest.raises(ApprovalError):
            load_approval_from_env({"LEVIATHAN_APPROVAL_JSON": bad})


def test_canonical_via_env_json_is_authorized_end_to_end() -> None:
    auth = authorize_publish(
        _good_target(),
        argv=["compact_weather_silver_task.py", "--publish-mode", "canonical"],
        env={"LEVIATHAN_APPROVAL_JSON": _approval_json()},
        secret=_SECRET,
    )
    assert auth.may_mutate_canonical is True
    assert auth.mode is PublishMode.CANONICAL


def test_canonical_via_env_json_wrong_table_is_rejected() -> None:
    with pytest.raises(ApprovalError):
        authorize_publish(
            _good_target(),  # table=silver_model_predictions
            argv=["task.py", "--publish-mode", "canonical"],
            env={"LEVIATHAN_APPROVAL_JSON": _approval_json(table="silver_chirps")},
            secret=_SECRET,
        )


def test_canonical_via_env_json_expired_is_rejected() -> None:
    stale = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    with pytest.raises(ApprovalError):
        authorize_publish(
            _good_target(),
            argv=["task.py", "--publish-mode", "canonical"],
            env={"LEVIATHAN_APPROVAL_JSON": _approval_json(expiry=stale)},
            secret=_SECRET,
        )


def test_dry_run_never_parses_the_env_approval() -> None:
    # non-canonical modes return before the loader runs, so garbage is harmless there
    auth = authorize_publish(
        _good_target(),
        argv=["task.py"],
        env={"LEVIATHAN_APPROVAL_JSON": "{definitely-not-json"},
        secret=_SECRET,
    )
    assert auth.mode is PublishMode.DRY_RUN
    assert auth.may_mutate_canonical is False


# ---------------------------------------------------------------------------
# (6) the STS assumed-role identity a RUNNING task actually presents (BF-W1 live find).
# ---------------------------------------------------------------------------
def test_sts_assumed_role_batch_identity_is_accepted() -> None:
    # sts get-caller-identity inside a Batch container returns the arn:aws:sts:: form;
    # the iam-only pattern rejected every legitimate canonical publisher (retire job 6de055eb).
    sts_arn = ("arn:aws:sts::668891723125:assumed-role/"
               "leviathan-dev-batch-job-role/f9c68238ffdd4a598d5eb2233393309e")
    auth = authorize_publish(
        _good_target(role_arn=sts_arn),
        mode=PublishMode.CANONICAL,
        approval=_valid_approval(),
        env={},
        secret=_SECRET,
    )
    assert auth.may_mutate_canonical is True


def test_sts_assumed_role_foreign_name_still_rejected() -> None:
    for bad in (
        "arn:aws:sts::668891723125:assumed-role/other-project-role/session",
        "arn:aws:sts::000000000000:assumed-role/leviathan-dev-batch-job-role/session",
        "arn:aws:sts::668891723125:assumed-role/leviathan-dev-readiness-ci/session",
    ):
        with pytest.raises((EnvironmentMismatch, ReadinessPublishDenied)):
            authorize_publish(
                _good_target(role_arn=bad),
                mode=PublishMode.CANONICAL,
                approval=_valid_approval(),
                env={},
                secret=_SECRET,
            )


# ===========================================================================
# (7) R1 KMS-asymmetric approval signing (A-W1). A LOCAL ECDSA P-256 keypair simulates the CMK:
# the stub kms client "signs" with the private key (as kms:Sign would) and returns the SPKI public
# key (as kms:GetPublicKey would); the guard verifies against the CACHED public key with the
# `cryptography` package -- NO kms:Verify call is ever made. These stay fully hermetic (no boto3,
# no AWS): boto3 is never constructed because every path is handed a stub client or a PEM.
# ===========================================================================
from cryptography.hazmat.primitives import hashes, serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402

_KMS_KEY_ID = "arn:aws:kms:us-east-1:668891723125:key/11111111-2222-3333-4444-555555555555"


class _StubKmsClient:
    """Simulates the two KMS calls the R1 path uses. kms:Sign returns a real DER ECDSA signature
    (MessageType=RAW + ECDSA_SHA_256, exactly as KMS would); kms:GetPublicKey returns the DER SPKI
    public key. Records call counts so tests can prove the one-time GetPublicKey fetch is cached."""

    def __init__(self, private_key: "ec.EllipticCurvePrivateKey") -> None:
        self._private_key = private_key
        self.sign_calls = 0
        self.get_public_key_calls = 0

    def sign(self, *, KeyId: str, Message: bytes, MessageType: str, SigningAlgorithm: str) -> dict:
        assert MessageType == "RAW"
        assert SigningAlgorithm == "ECDSA_SHA_256"
        self.sign_calls += 1
        der = self._private_key.sign(Message, ec.ECDSA(hashes.SHA256()))
        return {"KeyId": KeyId, "Signature": der, "SigningAlgorithm": SigningAlgorithm}

    def get_public_key(self, *, KeyId: str) -> dict:
        self.get_public_key_calls += 1
        der = self._private_key.public_key().public_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        return {"KeyId": KeyId, "PublicKey": der, "KeyUsage": "SIGN_VERIFY"}


def _pem_of(private_key: "ec.EllipticCurvePrivateKey") -> str:
    return private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")


def _kms_fields(**over: object) -> dict:
    expiry = over.pop(
        "expiry", (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    )
    fields = dict(
        environment="leviathan_dev",
        table="silver_model_predictions",
        registry_hash="reg-abc123",
        git_sha="deadbeef",
        expiry=expiry,
    )
    fields.update(over)
    fields["expiry"] = expiry
    return fields


@pytest.fixture(autouse=True)
def _clear_public_key_cache():
    # the verification-public-key cache is module-global; keep each KMS test hermetic.
    reset_public_key_cache()
    yield
    reset_public_key_cache()


def test_resolve_approval_mode_default_is_hmac_and_kms_selectable() -> None:
    assert resolve_approval_mode(env={}) is ApprovalMode.HMAC
    assert resolve_approval_mode(env={ENV_APPROVAL_MODE: "kms"}) is ApprovalMode.KMS
    assert resolve_approval_mode("kms", env={}) is ApprovalMode.KMS
    # explicit arg beats env
    assert resolve_approval_mode("hmac", env={ENV_APPROVAL_MODE: "kms"}) is ApprovalMode.HMAC


def test_unknown_approval_mode_fails_closed() -> None:
    with pytest.raises(ApprovalError):
        resolve_approval_mode(env={ENV_APPROVAL_MODE: "sign-it-yourself"})


def test_kms_mint_then_verify_via_pem_is_green() -> None:
    priv = ec.generate_private_key(ec.SECP256R1())
    stub = _StubKmsClient(priv)
    approval = mint_approval(mode="kms", key_id=_KMS_KEY_ID, kms_client=stub, **_kms_fields())
    assert stub.sign_calls == 1
    # KMS signatures are base64(DER), NOT hex like the HMAC placeholder.
    assert approval.signature != sign_approval(secret=_SECRET, **_kms_fields(expiry=approval.expiry))
    auth = authorize_publish(
        _good_target(),
        mode=PublishMode.CANONICAL,
        approval=approval,
        env={},
        approval_mode="kms",
        public_key_pem=_pem_of(priv),
    )
    assert auth.may_mutate_canonical is True
    assert auth.mode is PublishMode.CANONICAL


def test_kms_verify_via_getpublickey_fetches_once_and_caches() -> None:
    priv = ec.generate_private_key(ec.SECP256R1())
    stub = _StubKmsClient(priv)
    approval = mint_approval(mode="kms", key_id=_KMS_KEY_ID, kms_client=stub, **_kms_fields())
    # two verifies against the same key id -> exactly one kms:GetPublicKey call (cached thereafter).
    for _ in range(2):
        verify_approval(
            approval, _good_target(), mode="kms", env={}, key_id=_KMS_KEY_ID, kms_client=stub
        )
    assert stub.get_public_key_calls == 1
    assert stub.sign_calls == 1


def test_kms_tampered_payload_fails_closed() -> None:
    priv = ec.generate_private_key(ec.SECP256R1())
    stub = _StubKmsClient(priv)
    good = mint_approval(mode="kms", key_id=_KMS_KEY_ID, kms_client=stub, **_kms_fields())
    tampered = PublishApproval(
        environment=good.environment,
        table=good.table,
        registry_hash="reg-DIFFERENT",  # payload changed; the ECDSA signature no longer covers it
        git_sha=good.git_sha,
        expiry=good.expiry,
        signature=good.signature,
    )
    with pytest.raises(ApprovalError):
        authorize_publish(
            _good_target(),
            mode=PublishMode.CANONICAL,
            approval=tampered,
            env={},
            approval_mode="kms",
            public_key_pem=_pem_of(priv),
        )


def test_kms_signature_from_other_key_fails_closed() -> None:
    signer = ec.generate_private_key(ec.SECP256R1())
    other = ec.generate_private_key(ec.SECP256R1())
    approval = mint_approval(
        mode="kms", key_id=_KMS_KEY_ID, kms_client=_StubKmsClient(signer), **_kms_fields()
    )
    with pytest.raises(ApprovalError):
        verify_approval_kms(approval, public_key_pem=_pem_of(other))


def test_kms_bad_base64_signature_fails_closed() -> None:
    priv = ec.generate_private_key(ec.SECP256R1())
    approval = mint_approval(
        mode="kms", key_id=_KMS_KEY_ID, kms_client=_StubKmsClient(priv), **_kms_fields()
    )
    broken = PublishApproval(
        environment=approval.environment,
        table=approval.table,
        registry_hash=approval.registry_hash,
        git_sha=approval.git_sha,
        expiry=approval.expiry,
        signature="not-base-64-@@@",
    )
    with pytest.raises(ApprovalError):
        verify_approval_kms(broken, public_key_pem=_pem_of(priv))


def test_kms_expired_approval_is_rejected() -> None:
    priv = ec.generate_private_key(ec.SECP256R1())
    stub = _StubKmsClient(priv)
    stale = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    approval = mint_approval(
        mode="kms", key_id=_KMS_KEY_ID, kms_client=stub, **_kms_fields(expiry=stale)
    )
    # signature is valid but the window has closed -> still fails closed on expiry.
    with pytest.raises(ApprovalError):
        authorize_publish(
            _good_target(),
            mode=PublishMode.CANONICAL,
            approval=approval,
            env={},
            approval_mode="kms",
            public_key_pem=_pem_of(priv),
        )


def test_kms_wrong_table_binding_is_rejected() -> None:
    priv = ec.generate_private_key(ec.SECP256R1())
    stub = _StubKmsClient(priv)
    approval = mint_approval(
        mode="kms", key_id=_KMS_KEY_ID, kms_client=stub, **_kms_fields(table="silver_esr")
    )
    with pytest.raises(ApprovalError):
        authorize_publish(
            _good_target(),  # table=silver_model_predictions
            mode=PublishMode.CANONICAL,
            approval=approval,
            env={},
            approval_mode="kms",
            public_key_pem=_pem_of(priv),
        )


def test_kms_missing_key_id_mint_fails_closed() -> None:
    # no key id in the arg and none in the environment -> mint refuses (never calls a real client).
    with pytest.raises(ApprovalError):
        mint_approval(mode="kms", key_id=None, env={}, **_kms_fields())


def test_kms_missing_public_key_verify_fails_closed() -> None:
    priv = ec.generate_private_key(ec.SECP256R1())
    approval = mint_approval(
        mode="kms", key_id=_KMS_KEY_ID, kms_client=_StubKmsClient(priv), **_kms_fields()
    )
    # verify in kms mode with neither a PEM nor a key id -> fails closed, no client constructed.
    with pytest.raises(ApprovalError):
        verify_approval(approval, _good_target(), mode="kms", env={})


def test_kms_mode_resolved_from_env_end_to_end() -> None:
    import dataclasses
    import json as _json

    priv = ec.generate_private_key(ec.SECP256R1())
    stub = _StubKmsClient(priv)
    approval = mint_approval(mode="kms", key_id=_KMS_KEY_ID, kms_client=stub, **_kms_fields())
    # the full SFN container seam: the signed approval is threaded as LEVIATHAN_APPROVAL_JSON, and
    # mode + verification PEM come from the env contract the promote task sets. No secret anywhere.
    auth = authorize_publish(
        _good_target(),
        argv=["silver_task.py", "--publish-mode", "canonical"],
        env={
            ENV_APPROVAL_MODE: "kms",
            ENV_KMS_PUBLIC_KEY_PEM: _pem_of(priv),
            "LEVIATHAN_APPROVAL_JSON": _json.dumps(dataclasses.asdict(approval)),
        },
    )
    assert auth.may_mutate_canonical is True


def test_kms_mint_resolves_key_id_from_env() -> None:
    # the SFN promote task passes the CMK via LEVIATHAN_KMS_KEY_ID, not an explicit arg.
    priv = ec.generate_private_key(ec.SECP256R1())
    stub = _StubKmsClient(priv)
    approval = mint_approval(
        mode="kms", env={ENV_KMS_KEY_ID: _KMS_KEY_ID}, kms_client=stub, **_kms_fields()
    )
    assert stub.sign_calls == 1
    verify_approval(approval, _good_target(), mode="kms", public_key_pem=_pem_of(priv))


def test_kms_signed_approval_rejected_under_hmac_mode() -> None:
    # a KMS (base64/DER) signature must not accidentally verify under the default HMAC path.
    priv = ec.generate_private_key(ec.SECP256R1())
    approval = mint_approval(
        mode="kms", key_id=_KMS_KEY_ID, kms_client=_StubKmsClient(priv), **_kms_fields()
    )
    with pytest.raises(ApprovalError):
        authorize_publish(
            _good_target(),
            mode=PublishMode.CANONICAL,
            approval=approval,
            env={},  # default mode = hmac
            secret=_SECRET,
        )


def test_hmac_mode_unchanged_when_mode_absent() -> None:
    # the R0 HMAC path is byte-identical: an approval signed with the placeholder secret still
    # verifies when no LEVIATHAN_APPROVAL_MODE is set (default hmac).
    auth = authorize_publish(
        _good_target(),
        mode=PublishMode.CANONICAL,
        approval=_valid_approval(),
        env={},
        secret=_SECRET,
    )
    assert auth.may_mutate_canonical is True
    # and an explicit hmac mode is equivalent.
    auth2 = authorize_publish(
        _good_target(),
        mode=PublishMode.CANONICAL,
        approval=_valid_approval(),
        env={ENV_APPROVAL_MODE: "hmac"},
        secret=_SECRET,
    )
    assert auth2.may_mutate_canonical is True


def test_sign_approval_kms_missing_key_id_fails_closed() -> None:
    priv = ec.generate_private_key(ec.SECP256R1())
    with pytest.raises(ApprovalError):
        sign_approval_kms(key_id="", kms_client=_StubKmsClient(priv), **_kms_fields())


class TestKmsSelfMint:
    """R1 scheduled self-mint: kms mode + no env approval -> authorize mints via kms:Sign."""

    def test_kms_mode_self_mints_and_authorizes(self):
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives import serialization
        import leviathan.common.publish_guard as pg
        priv = ec.generate_private_key(ec.SECP256R1())
        stub = _StubKmsClient(priv)
        pem = priv.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode()
        env = {
            "LEVIATHAN_APPROVAL_MODE": "kms",
            "LEVIATHAN_KMS_KEY_ID": "alias/test-signer",
            "LEVIATHAN_KMS_PUBLIC_KEY_PEM": pem,
        }
        target = pg.PublishTarget(
            account_id=pg.PROD_ENVIRONMENT.account_id,
            bucket=pg.PROD_ENVIRONMENT.bucket,
            database=pg.PROD_ENVIRONMENT.database,
            prefix=pg.PROD_ENVIRONMENT.prefix_allowlist[0],
            role_arn="arn:aws:iam::668891723125:role/leviathan-dev-silver-publisher",
            table="silver_fred_fx",
        )
        auth = pg.authorize_publish(
            target, mode=pg.PublishMode.CANONICAL, env=env, kms_client=stub,
        )
        assert auth.may_mutate_canonical is True

    def test_hmac_mode_still_requires_env_approval(self):
        import pytest as _pytest
        import leviathan.common.publish_guard as pg
        target = pg.PublishTarget(
            account_id=pg.PROD_ENVIRONMENT.account_id,
            bucket=pg.PROD_ENVIRONMENT.bucket,
            database=pg.PROD_ENVIRONMENT.database,
            prefix=pg.PROD_ENVIRONMENT.prefix_allowlist[0],
            role_arn="arn:aws:iam::668891723125:role/leviathan-dev-silver-publisher",
            table="silver_fred_fx",
        )
        with _pytest.raises(pg.ApprovalError):
            pg.authorize_publish(target, mode=pg.PublishMode.CANONICAL, env={})
