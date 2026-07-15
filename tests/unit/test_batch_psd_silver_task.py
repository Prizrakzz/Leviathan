"""Unit tests for the USDA PSD silver Batch task guard helpers (F2).

Pure Python -- no S3/AWS.  The task's fail-closed release_date guard is exercised
directly: it is the belt-and-suspenders check that aborts the run if the silver
transform's clamp is ever bypassed and a future-dated row survives to the write.
"""
from __future__ import annotations

import pandas as pd
import pytest

from jobs.batch import psd_silver_task as task

_INGEST = "2026-05-20"


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
