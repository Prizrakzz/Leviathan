"""Unit tests for the USDA PSD silver Batch task (F2 guard + A-W4 CLASS-B retrofit).

The F2 fail-closed release_date guard is exercised directly (pure Python, no S3/AWS): it is the
belt-and-suspenders check that aborts the run if the silver transform's clamp is ever bypassed
and a future-dated row survives to the write.

The A-W4 retrofit routes the flat ``silver_psd`` write through the shadow-first publisher via
``build_flat_publish``; ``--publish-mode`` defaults to dry-run (nothing written). Those tests
exercise ``_publish_psd`` directly with injected guard verdicts, proving the three-mode INV-6
contract.
"""
from __future__ import annotations

import pandas as pd
import pytest

from leviathan.silver.publisher import ManifestState
from leviathan.silver.registry import load_registry
from leviathan.storage.paths import silver_psd_key
from leviathan.transforms.bronze_to_silver.usda_psd import _SILVER_COLS

from jobs.batch import psd_silver_task as task
from tests.unit.silver.conftest import (
    FakeS3,
    canonical_authorization,
    dryrun_authorization,
    shadow_authorization,
)

_INGEST = "2026-05-20"

_CONTRACT = load_registry().table("silver_psd")
_BUCKET = _CONTRACT["s3_bucket"]          # where build_flat_publish writes (contract-pinned)
_SENTINEL = b"OLD-CANONICAL-PSD"


def _silver_df() -> pd.DataFrame:
    """One full 18-column canonical silver row (value columns non-null clear the 0.5 floor)."""
    return pd.DataFrame([{
        "leviathan_slug": "corn_cbot", "country": "united_states",
        "market_year": 2024, "wasde_release_month": 5, "release_date": "2026-05-10",
        "beginning_stocks_mt": 40.0, "production_mt": 380.0, "imports_mt": 1.0,
        "exports_mt": 60.0, "ending_stocks_mt": 45.0, "consumption_mt": 310.0,
        "area_harvested_1000ha": 33000.0, "yield_mt_ha": 11.5, "su_ratio": 0.145,
        "su_ratio_yoy_delta": None, "production_mt_revision": None,
        "ending_stocks_mt_revision": None, "consumption_mt_revision": None,
    }])


def _silver(release_dates: list[str]) -> pd.DataFrame:
    """Minimal silver frame carrying only the column the guard inspects."""
    return pd.DataFrame({
        "leviathan_slug": ["corn_cbot"] * len(release_dates),
        "release_date":   release_dates,
    })


def _bronze(release_date: str = _INGEST) -> pd.DataFrame:
    return pd.DataFrame({
        "commodity_code": [440000],
        "release_date":   [release_date],
    })


# ---------------------------------------------------------------------------
# TestSnapshotIngestDate
# ---------------------------------------------------------------------------

class TestSnapshotIngestDate:
    def test_single_partition(self) -> None:
        assert task._snapshot_ingest_date([_bronze("2026-05-20")]) == "2026-05-20"

    def test_newest_across_partitions(self) -> None:
        dfs = [_bronze("2026-01-15"), _bronze("2026-05-20"), _bronze("2025-11-01")]
        assert task._snapshot_ingest_date(dfs) == "2026-05-20"

    def test_no_release_dates_raises(self) -> None:
        with pytest.raises(ValueError, match="no bronze release_date"):
            task._snapshot_ingest_date([pd.DataFrame({"commodity_code": [440000]})])


# ---------------------------------------------------------------------------
# TestReleaseDateGuard
# ---------------------------------------------------------------------------

class TestReleaseDateGuard:
    def test_all_historical_passes(self) -> None:
        # Dates at/below the snapshot must not raise.
        task._assert_release_dates_not_future(
            _silver(["2001-01-10", "1990-01-01", _INGEST]), _INGEST
        )

    def test_equal_to_ingest_passes(self) -> None:
        # A row clamped exactly to the ingest date is allowed (not "future").
        task._assert_release_dates_not_future(_silver([_INGEST]), _INGEST)

    def test_future_row_raises(self) -> None:
        """A fabricated future date (clamp bypassed) must abort the producer."""
        fabricated = _silver(["2001-01-10", "2027-03-10"])
        with pytest.raises(ValueError, match="post-date the bronze snapshot"):
            task._assert_release_dates_not_future(fabricated, _INGEST)

    def test_future_row_message_names_count_and_example(self) -> None:
        fabricated = _silver(["2027-03-10", "2027-01-10"])
        with pytest.raises(ValueError) as exc:
            task._assert_release_dates_not_future(fabricated, _INGEST)
        msg = str(exc.value)
        assert "2 release_date" in msg          # count reported
        assert "2027-01-10" in msg              # sorted example surfaced
        assert _INGEST in msg                   # the bound reported

    def test_empty_silver_is_noop(self) -> None:
        task._assert_release_dates_not_future(_silver([]), _INGEST)


# ---------------------------------------------------------------------------
# TestGuardEndToEnd
# ---------------------------------------------------------------------------

class TestGuardEndToEnd:
    def test_snapshot_bound_then_guard_flags_bypass(self) -> None:
        """Derive the bound from bronze, then a bypassed future row trips the guard."""
        ingest = task._snapshot_ingest_date([_bronze(_INGEST)])
        with pytest.raises(ValueError, match="post-date the bronze snapshot"):
            task._assert_release_dates_not_future(_silver(["2027-03-10"]), ingest)


# ---------------------------------------------------------------------------
# TestShadowFirstPublish (A-W4 CLASS-B retrofit)
# ---------------------------------------------------------------------------

class TestShadowFirstPublish:
    def test_silver_columns_match_contract(self) -> None:
        contract_cols = [c["name"] for c in _CONTRACT["physical_columns"]]
        assert _SILVER_COLS == contract_cols

    def test_dry_run_writes_nothing_but_validates(self) -> None:
        # main() passes s3_client=None in dry-run; the plan reaches VALIDATED with nothing written.
        state = task._publish_psd(_silver_df(), _CONTRACT, dryrun_authorization(), None, _BUCKET,
                                  force_overwrite=True)
        assert state is ManifestState.VALIDATED

    def test_shadow_stages_to_shadow_only_and_leaves_canonical_byte_identical(self) -> None:
        s3 = FakeS3()
        canonical_key = silver_psd_key()
        s3.store[(_BUCKET, canonical_key)] = _SENTINEL          # pre-seed a canonical sentinel
        etag_before = s3._etag(_SENTINEL)

        state = task._publish_psd(_silver_df(), _CONTRACT, shadow_authorization(), s3, _BUCKET,
                                  force_overwrite=True)

        assert state is ManifestState.VALIDATED
        assert s3.store[(_BUCKET, canonical_key)] == _SENTINEL              # canonical untouched
        assert s3._etag(s3.store[(_BUCKET, canonical_key)]) == etag_before  # etag identical
        assert any("_shadow" in k for k in s3.keys())                      # staged under _shadow/
        # every data object other than canonical + the control-plane manifest lives under _shadow/
        for _, key in s3.store:
            if key == canonical_key or "/_manifests/" in key:
                continue
            assert "/_shadow/" in key

    def test_canonical_overwrites_the_psd_silver_object(self) -> None:
        s3 = FakeS3()
        canonical_key = silver_psd_key()
        s3.store[(_BUCKET, canonical_key)] = _SENTINEL

        state = task._publish_psd(_silver_df(), _CONTRACT, canonical_authorization(), s3, _BUCKET,
                                  force_overwrite=True)

        assert state is ManifestState.CERTIFIED
        assert (_BUCKET, canonical_key) in s3.store
        assert s3.store[(_BUCKET, canonical_key)] != _SENTINEL   # canonical overwritten
