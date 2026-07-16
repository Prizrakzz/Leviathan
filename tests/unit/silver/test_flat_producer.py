"""SILVER-F062 flat-producer runtime: INV-2 writer-schema pin + common-publisher glue.

Pure Python -- no S3/AWS (dry-run needs no client). Covers the arrow-schema build, the all-null
measure -> double guard (closing the null-type hazard), the DataFrame<->contract shape check, the
dry-run publish (nothing written, stops at VALIDATED), and the standard CLI + authorize helpers.
"""
from __future__ import annotations

import io
import os

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from datetime import datetime, timedelta, timezone

from leviathan.common.publish_guard import (
    ApprovalError,
    PublishApproval,
    PublishMode,
    sign_approval,
)
from leviathan.silver import flat_producer as fp
from leviathan.silver import value_census as vc
from leviathan.silver.flat_producer import (
    add_standard_producer_args,
    arrow_type_for,
    authorize_for_contract,
    build_flat_publish,
    encode_parquet,
    null_metrics_for,
    pa_schema_from_contract,
)
from leviathan.silver.publisher import ManifestState
from leviathan.silver.registry import load_registry


@pytest.fixture(scope="module")
def contract():
    return load_registry().table("silver_mpoc_exports_by_country")


def _df(exports=(2.5e6, 1.8e6)):
    return pd.DataFrame({
        "year": [2023, 2023], "country": ["china", "india"],
        "exports_mt": list(exports), "source": ["mpoc", "mpoc"],
    })


class TestArrowSchema:
    def test_token_mapping(self):
        assert arrow_type_for("int64") == pa.int64()
        assert arrow_type_for("float64") == pa.float64()
        assert arrow_type_for("string") == pa.string()

    def test_unmapped_token_fails_closed(self):
        with pytest.raises(ValueError):
            arrow_type_for("decimal(10,2)")

    def test_schema_order_and_nullability(self, contract):
        sch = pa_schema_from_contract(contract)
        assert sch.names == ["year", "country", "exports_mt", "source"]
        assert sch.field("year").nullable is False        # natural-key column
        assert sch.field("exports_mt").nullable is True
        assert sch.field("exports_mt").type == pa.float64()


class TestEncode:
    def test_all_null_measure_is_double_not_null(self, contract):
        # the s3-lane null-type hazard: an all-null measure column must write as double.
        df = pd.DataFrame({"year": [2023], "country": ["china"], "exports_mt": [None],
                           "source": ["mpoc"]})
        t = pq.read_table(io.BytesIO(encode_parquet(df, contract)))
        assert t.schema.field("exports_mt").type == pa.float64()

    def test_shape_mismatch_fails_closed(self, contract):
        df = _df().drop(columns=["source"])
        with pytest.raises(ValueError):
            encode_parquet(df, contract)

    def test_extra_column_fails_closed(self, contract):
        df = _df().assign(bogus=1)
        with pytest.raises(ValueError):
            encode_parquet(df, contract)

    def test_null_metrics(self, contract):
        df = pd.DataFrame({"year": [1, 2], "country": ["a", "b"], "exports_mt": [1.0, None],
                           "source": ["x", "y"]})
        assert null_metrics_for(df, ["exports_mt"]) == {"exports_mt": 0.5}


class TestDryRunPublish:
    def test_stops_at_validated_nothing_written(self, contract):
        auth = authorize_for_contract(contract, publish_mode="dry-run")
        assert auth.mode is PublishMode.DRY_RUN and not auth.may_mutate_canonical
        plan = build_flat_publish(df=_df(), contract=contract,
                                  canonical_key="silver/mpoc_exports_by_country/part-000.parquet",
                                  auth=auth, s3_client=None, job="t")
        m = plan.run()
        assert m.state is ManifestState.VALIDATED
        assert m.outputs == []
        assert m.row_key_null_metrics["silver/mpoc_exports_by_country/part-000.parquet"]["exports_mt"] == 1.0

    def test_census_from_footer_matches(self, contract):
        body = encode_parquet(_df(exports=(2.5e6, None)), contract)
        md = pq.read_metadata(io.BytesIO(body))
        census = vc.census_column([vc.file_column_stat(md, "exports_mt")], "exports_mt")
        assert census.nonnull_fraction == 0.5 and not census.all_nan


class TestStandardCli:
    def test_publish_mode_default_dry_run(self):
        import argparse
        p = add_standard_producer_args(argparse.ArgumentParser())
        args = p.parse_args([])
        assert args.publish_mode == "dry-run"

    def test_shadow_and_canonical_choices(self):
        import argparse
        p = add_standard_producer_args(argparse.ArgumentParser())
        assert p.parse_args(["--publish-mode", "shadow"]).publish_mode == "shadow"
        with pytest.raises(SystemExit):
            p.parse_args(["--publish-mode", "bogus"])


# The STS identity a RUNNING Batch task actually presents (the arn:aws:sts:: assumed-role form);
# account/bucket/db all match the one canonical environment so check_environment passes.
_STS_ACCOUNT = "668891723125"
_STS_ARN = ("arn:aws:sts::668891723125:assumed-role/"
            "leviathan-dev-batch-job-role/f9c68238ffdd4a598d5eb2233393309e")
_SECRET = "r0-flat-producer-secret"


def _canonical_approval(table: str, secret: str = _SECRET, **over) -> PublishApproval:
    fields = dict(
        environment="leviathan_dev",
        table=table,
        registry_hash="reg-flat",
        git_sha="abc123",
        expiry=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
    )
    fields.update(over)
    return PublishApproval(signature=sign_approval(secret=secret, **fields), **fields)


class TestCanonicalIdentityResolution:
    """The flat_producer STS-identity gap: canonical publish (pink_sheet / mpob / mpob_annual)
    failed closed because authorize_for_contract built the PublishTarget with account_id=''/
    role_arn='' -- and check_environment (only reached on canonical) rejects an empty identity.
    The fix resolves the LIVE STS identity centrally, ONLY on the canonical path, ONLY when the
    caller supplied neither. dry-run/shadow stay fully offline."""

    def test_canonical_empty_args_resolves_via_sts_and_authorizes(self, contract, monkeypatch):
        calls = {"n": 0}

        def _stub():
            calls["n"] += 1
            return (_STS_ACCOUNT, _STS_ARN)

        monkeypatch.setattr(fp, "_resolve_caller_identity", _stub)
        monkeypatch.setenv("LEVIATHAN_APPROVAL_SECRET", _SECRET)
        approval = _canonical_approval(contract["table_name"])
        # Caller (task) passes NO account_id/role_arn -- exactly the pink_sheet/mpob call shape.
        auth = authorize_for_contract(contract, publish_mode="canonical", approval=approval)
        assert auth.may_mutate_canonical is True
        assert calls["n"] == 1  # STS seam consulted exactly once

    def test_canonical_empty_args_passes_check_environment(self, contract, monkeypatch):
        # With the identity resolved, check_environment no longer fails closed -- the NEXT gate is
        # the missing approval (ApprovalError), proving we got past the environment check that was
        # raising EnvironmentMismatch on account_id=''/role_arn=''.
        monkeypatch.setattr(fp, "_resolve_caller_identity", lambda: (_STS_ACCOUNT, _STS_ARN))
        with pytest.raises(ApprovalError):
            authorize_for_contract(contract, publish_mode="canonical")

    def test_dry_run_and_shadow_make_no_sts_call(self, contract, monkeypatch):
        def _boom():
            raise AssertionError("STS must never be resolved off the canonical path")

        monkeypatch.setattr(fp, "_resolve_caller_identity", _boom)
        for mode in ("dry-run", "shadow"):
            auth = authorize_for_contract(contract, publish_mode=mode)
            assert auth.may_mutate_canonical is False

    def test_explicit_identity_wins_no_sts_call(self, contract, monkeypatch):
        def _boom():
            raise AssertionError("explicit identity supplied; the STS seam must not run")

        monkeypatch.setattr(fp, "_resolve_caller_identity", _boom)
        monkeypatch.setenv("LEVIATHAN_APPROVAL_SECRET", _SECRET)
        approval = _canonical_approval(contract["table_name"])
        auth = authorize_for_contract(
            contract, publish_mode="canonical",
            account_id=_STS_ACCOUNT, role_arn=_STS_ARN, approval=approval,
        )
        assert auth.may_mutate_canonical is True

    def test_canonical_defaults_env_to_os_environ_for_self_mint(self, contract, monkeypatch):
        # The canonical self-mint reads LEVIATHAN_APPROVAL_MODE (+ the kms binding) from `env`. When
        # the caller passes no env, authorize_for_contract must hand authorize_publish the LIVE process
        # env on the canonical path -- else the guard sees {} and fails closed with ApprovalError (the
        # round-3 pink_sheet/mpob/mpob_annual promote failure; fnc passed only because it plumbed
        # env=os.environ). Capture the env authorize_publish actually receives.
        monkeypatch.setattr(fp, "_resolve_caller_identity", lambda: (_STS_ACCOUNT, _STS_ARN))
        monkeypatch.setenv("LEVIATHAN_APPROVAL_MODE", "kms")
        captured = {}

        def _rec(target, *, mode, approval, env):
            captured["env"] = env
            return object()

        monkeypatch.setattr(fp, "authorize_publish", _rec)
        fp.authorize_for_contract(contract, publish_mode="canonical")
        assert captured["env"] is os.environ
        assert captured["env"].get("LEVIATHAN_APPROVAL_MODE") == "kms"

    def test_non_canonical_env_stays_empty_offline(self, contract, monkeypatch):
        # dry-run/shadow never reach the approval gate -> keep the empty offline mapping (no live-env
        # leak), byte-identical to before the fix.
        captured = {}

        def _rec(target, *, mode, approval, env):
            captured["env"] = env
            return object()

        monkeypatch.setattr(fp, "authorize_publish", _rec)
        for mode in ("dry-run", "shadow"):
            fp.authorize_for_contract(contract, publish_mode=mode)
            assert captured["env"] == {}

    def test_explicit_env_wins_over_os_environ(self, contract, monkeypatch):
        monkeypatch.setattr(fp, "_resolve_caller_identity", lambda: (_STS_ACCOUNT, _STS_ARN))
        captured = {}

        def _rec(target, *, mode, approval, env):
            captured["env"] = env
            return object()

        monkeypatch.setattr(fp, "authorize_publish", _rec)
        my_env = {"LEVIATHAN_APPROVAL_MODE": "hmac"}
        fp.authorize_for_contract(contract, publish_mode="canonical", env=my_env)
        assert captured["env"] is my_env
