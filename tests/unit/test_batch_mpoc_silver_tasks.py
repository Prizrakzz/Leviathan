"""Wave-1 regression: the three MPOC silver Batch tasks must build a LIVE S3 client on the
shadow/canonical publish path.

The round-1 rewrite (commit 458f13b2) hard-wired ``s3_client=None`` into every
``build_flat_publish`` call in ``mpoc_{exports_by_country,stock_comparison,trade_stats_monthly}
_silver_task``. That is correct only for dry-run; a ``--publish-mode shadow`` run (SFN state
BatchSyncSilver, jobdef leviathan-dev-b3-flat-silver) reached the publisher's staging loop and
crashed with ``'NoneType' object has no attribute 'put_object'``. The fix builds the client
conditionally (``None if dry-run else get_thread_local_s3_client``), matching the working
``mpob_silver_task`` sibling.

Two layers are locked here:
  * the shared ``build_flat_publish`` seam now fails closed at plan-build time when a write mode is
    handed no client (an actionable ValueError, not the cryptic AttributeError);
  * each task's ``main()`` builds exactly one live client for shadow (stages under ``_shadow/``,
    canonical untouched) and NO client for dry-run (nothing written).

Pure/hermetic: an in-memory :class:`FakeS3` and a recording client factory replace all AWS.
"""
from __future__ import annotations

import datetime as dt
import sys

import pandas as pd
import pytest

from jobs.batch import mpoc_exports_by_country_silver_task as exports_task
from jobs.batch import mpoc_stock_comparison_silver_task as stock_task
from jobs.batch import mpoc_trade_stats_monthly_silver_task as monthly_task
from leviathan.silver.flat_producer import build_flat_publish
from leviathan.silver.publisher import ManifestState
from leviathan.silver.registry import load_registry
from leviathan.storage.paths import silver_mpoc_key
from tests.unit.silver.conftest import (
    FakeS3,
    canonical_authorization,
    dryrun_authorization,
    shadow_authorization,
)


# --------------------------------------------------------------------------- canned silver frames
# Each frame carries EXACTLY the contract's physical columns (encode_parquet is order-agnostic in
# but rejects any missing/extra column) with non-null measures that clear the 0.5 non-null floor.
def _monthly_df() -> pd.DataFrame:
    return pd.DataFrame({
        "year": [2023, 2023], "month": [1, 2],
        "exports_mt": [1_136_027.0, 1_126_127.0], "imports_mt": [144_937.0, 52_446.0],
        "source": ["mpoc", "mpoc"],
    })


def _exports_df() -> pd.DataFrame:
    # Mirrors transform_exports_by_country's v2 OUTPUT_COLUMNS exactly, incl. the derived PIT anchor
    # year_ending_date = date(year, 12, 31) (D-LD tranche 2). This fixture went STALE at the contract
    # un-hide (490ba6f1, 2026-08-18 18:17) and four publish-path tests sat red for a week -- the
    # producer, the contract and the live Glue catalog all carried the column (each verified
    # 2026-08-25); only this hand-rolled frame modelled the v1 shape. The assertion welds the fixture
    # to the transform's own column list so the next widening reds HERE with a readable message,
    # never in a downstream contract mismatch.
    df = pd.DataFrame({
        "year": [2023, 2023], "country": ["india", "china"],
        "exports_mt": [2_809_956.0, 1_466_864.0], "source": ["mpoc", "mpoc"],
        "year_ending_date": [dt.date(2023, 12, 31), dt.date(2023, 12, 31)],
    })
    from leviathan.transforms.bronze_to_silver.mpoc_exports_by_country import OUTPUT_COLUMNS
    assert list(df.columns) == OUTPUT_COLUMNS, (
        f"fixture drifted from the producer's OUTPUT_COLUMNS: {list(df.columns)} != {OUTPUT_COLUMNS}")
    return df


def _stock_df() -> pd.DataFrame:
    return pd.DataFrame({
        "country": ["china", "usa"], "oil_type": ["palm_oil", "soybean_oil"],
        "year": [2026, 2026], "month": [1, 1],
        "ending_stocks_mt": [709_200.0, 795_000.0], "source": ["mpoc", "mpoc"],
    })


# (task module, loader attr the task calls, transform attr, df builder, canonical key, table)
_SPECS = [
    pytest.param(monthly_task, "load_releases", "transform_trade_stats_monthly", _monthly_df,
                 silver_mpoc_key("trade_stats_monthly"), "silver_mpoc_trade_stats_monthly",
                 id="trade_stats_monthly"),
    pytest.param(exports_task, "load_releases", "transform_exports_by_country", _exports_df,
                 silver_mpoc_key("exports_by_country"), "silver_mpoc_exports_by_country",
                 id="exports_by_country"),
    pytest.param(stock_task, "load_release", "transform_stock_comparison", _stock_df,
                 silver_mpoc_key("stock_comparison"), "silver_mpoc_stock_comparison",
                 id="stock_comparison"),
]


def _wire(monkeypatch, task, loader_attr, transform_attr, df_builder):
    """Stub env + loader + transform + the S3 client factory. Returns ``(fake_s3, factory_calls)``."""
    monkeypatch.setattr(task, "load_env", lambda *a, **k: None)
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setattr(task, loader_attr, lambda *a, **k: [])          # no S3 read in the loader
    monkeypatch.setattr(task, transform_attr, lambda *a, **k: df_builder())
    s3 = FakeS3()
    calls: list[str] = []

    def _factory(region):
        calls.append(region)
        return s3

    # main() resolves ``get_thread_local_s3_client`` via a call-time import from leviathan.storage.s3,
    # so patch the source-module name (patching the task attribute would not take effect).
    monkeypatch.setattr("leviathan.storage.s3.get_thread_local_s3_client", _factory)
    return s3, calls


# =========================================================================== shared-seam fail-closed
class TestBuildFlatPublishRequiresClientForWrite:
    """The publisher STAGES to S3 in both shadow and canonical modes; ``build_flat_publish`` must
    reject a None client for a write mode at plan-build time (the mpoc Wave-1 crash mechanism)."""

    _KEY = "silver/mpoc_exports_by_country/part-000.parquet"

    @pytest.fixture(scope="class")
    def contract(self):
        return load_registry().table("silver_mpoc_exports_by_country")

    def test_shadow_without_client_fails_closed(self, contract):
        with pytest.raises(ValueError, match="requires a live s3_client"):
            build_flat_publish(df=_exports_df(), contract=contract, canonical_key=self._KEY,
                               auth=shadow_authorization(), s3_client=None, job="t")

    def test_canonical_without_client_fails_closed(self, contract):
        with pytest.raises(ValueError, match="requires a live s3_client"):
            build_flat_publish(df=_exports_df(), contract=contract, canonical_key=self._KEY,
                               auth=canonical_authorization(), s3_client=None, job="t")

    def test_dry_run_without_client_is_allowed(self, contract):
        # dry-run legitimately stages nothing; a None client stays valid and reaches VALIDATED.
        plan = build_flat_publish(df=_exports_df(), contract=contract, canonical_key=self._KEY,
                                  auth=dryrun_authorization(), s3_client=None, job="t")
        assert plan.run().state is ManifestState.VALIDATED

    def test_shadow_with_client_stages_to_shadow(self, contract):
        s3 = FakeS3()
        build_flat_publish(df=_exports_df(), contract=contract, canonical_key=self._KEY,
                           auth=shadow_authorization(), s3_client=s3, job="t").run()
        assert any("_shadow" in k for k in s3.keys())      # staged shadow-first
        assert self._KEY not in s3.keys()                  # canonical never touched


# =========================================================================== task-level wiring
@pytest.mark.parametrize("task, loader_attr, transform_attr, df_builder, canonical_key, table", _SPECS)
def test_shadow_builds_one_live_client_and_stages_to_shadow(
        monkeypatch, task, loader_attr, transform_attr, df_builder, canonical_key, table):
    s3, calls = _wire(monkeypatch, task, loader_attr, transform_attr, df_builder)
    monkeypatch.setattr(sys, "argv", ["prog", "--bucket", "leviathan-test",
                                      "--publish-mode", "shadow"])

    rc = task.main()

    assert rc == 0
    assert calls == ["us-east-1"]                          # exactly one live client, for the publish
    keys = s3.keys()
    assert any("_shadow" in k for k in keys)               # object staged shadow-first
    assert canonical_key not in keys                       # canonical untouched in shadow mode


@pytest.mark.parametrize("task, loader_attr, transform_attr, df_builder, canonical_key, table", _SPECS)
def test_dry_run_builds_no_client_and_writes_nothing(
        monkeypatch, task, loader_attr, transform_attr, df_builder, canonical_key, table):
    s3, calls = _wire(monkeypatch, task, loader_attr, transform_attr, df_builder)
    monkeypatch.setattr(sys, "argv", ["prog", "--bucket", "leviathan-test",
                                      "--publish-mode", "dry-run"])

    rc = task.main()

    assert rc == 0
    assert calls == []                                     # dry-run stages nothing -> no client built
    assert s3.keys() == []                                 # nothing written anywhere
