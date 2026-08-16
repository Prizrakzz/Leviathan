"""D-SG G2-1(b) -- the raw-vs-bronze staleness fence and the FGIS advance fence.

FGIS is a WEEKLY CUMULATIVE source: one CY{year}.csv that grows every Thursday,
staged under a NEW raw key (year={y}/as_of={YYYYMMDD}/) that maps to the SAME
bronze key (year={y}/part-000.parquet). Skipping on bronze EXISTENCE therefore
became permanently true after the first write: between 2026-07-17 and 2026-08-13
four fresh snapshots were downloaded, ranked first by _select_best_keys, and
discarded, while the job logged "written=0 skipped=44 errors=0" and exited 0.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone

import boto3
import pytest
from moto import mock_aws

from jobs.batch import fgis_task
from leviathan.common.ingest_fence import bronze_is_current, object_last_modified

BUCKET = "test-leviathan"
_RAW = "raw/production/source=usda_fgis_export_inspections"
_BRONZE = "bronze/production/source=usda_fgis_export_inspections"


def _raw_key(year: int, as_of: str) -> str:
    return f"{_RAW}/year={year}/as_of={as_of}/CY{year}.csv"


def _bronze_key(year: int) -> str:
    return f"{_BRONZE}/year={year}/part-000.parquet"


def _as_of(days_ago: int) -> str:
    return (datetime.now(timezone.utc).date() - timedelta(days=days_ago)).strftime("%Y%m%d")


# ---------------------------------------------------------------------------
# bronze_is_current
#
# The ORDERING cases use a stub client, not moto: moto stamps LastModified from
# the wall clock at 1-second resolution, so two puts in one test share a
# timestamp and the >= comparison cannot be exercised. The mtimes here are the
# measured ones -- bronze frozen 2026-07-17T07:22:53Z against raw as_of=20260813.
# ---------------------------------------------------------------------------

class _StubS3:
    def __init__(self, mtimes: dict[str, datetime]):
        self._mtimes = mtimes

    def head_object(self, Bucket: str, Key: str):  # noqa: N803 -- boto3 kwarg names
        if Key not in self._mtimes:
            raise KeyError(Key)
        return {"LastModified": self._mtimes[Key]}


def _utc(iso: str) -> datetime:
    return datetime.fromisoformat(iso).replace(tzinfo=timezone.utc)


def test_stale_bronze_is_rebuilt():
    """THE EXACT 2026-08-13 STATE: bronze frozen 07-17, raw restaged four times since."""
    s3 = _StubS3(
        {
            _bronze_key(2026): _utc("2026-07-17T07:22:53"),
            _raw_key(2026, "20260813"): _utc("2026-08-13T12:04:11"),
        }
    )
    assert bronze_is_current(s3, BUCKET, _raw_key(2026, "20260813"), _bronze_key(2026)) is False


def test_current_bronze_is_skipped():
    """Raw first, bronze second -- no churn, the skip path still works."""
    s3 = _StubS3(
        {
            _raw_key(2025, "20251231"): _utc("2025-12-31T12:00:00"),
            _bronze_key(2025): _utc("2025-12-31T12:00:31"),
        }
    )
    assert bronze_is_current(s3, BUCKET, _raw_key(2025, "20251231"), _bronze_key(2025)) is True


@mock_aws
def test_missing_bronze_rebuilds():
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket=BUCKET)
    s3.put_object(Bucket=BUCKET, Key=_raw_key(2026, "20260813"), Body=b"csv")

    assert bronze_is_current(s3, BUCKET, _raw_key(2026, "20260813"), _bronze_key(2026)) is False


@mock_aws
def test_missing_raw_rebuilds():
    """An unreadable raw mtime is UNCERTAINTY -- the fence fails toward rebuilding."""
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket=BUCKET)
    s3.put_object(Bucket=BUCKET, Key=_bronze_key(2026), Body=b"parquet")

    assert bronze_is_current(s3, BUCKET, _raw_key(2026, "20260813"), _bronze_key(2026)) is False


@mock_aws
def test_object_last_modified_is_tz_aware_or_none():
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket=BUCKET)
    s3.put_object(Bucket=BUCKET, Key=_bronze_key(2026), Body=b"parquet")

    lm = object_last_modified(s3, BUCKET, _bronze_key(2026))
    assert lm is not None and lm.tzinfo is not None
    assert object_last_modified(s3, BUCKET, "no/such/key") is None


# ---------------------------------------------------------------------------
# the fgis advance fence
# ---------------------------------------------------------------------------

@pytest.fixture()
def fgis_env(monkeypatch):
    monkeypatch.setenv("LEVIATHAN_BUCKET", BUCKET)
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setattr("leviathan.common.config.load_env", lambda *a, **k: None)
    monkeypatch.setattr(fgis_task, "load_env", lambda *a, **k: None)


def _run_main(monkeypatch, argv: list[str]) -> int | None:
    monkeypatch.setattr(sys, "argv", ["fgis_task.py", *argv])
    try:
        fgis_task.main()
    except SystemExit as exc:
        return exc.code
    return None


@mock_aws
def test_advance_fence_fires_on_discarded_snapshot(fgis_env, monkeypatch, caplog):
    """Bronze newer than raw (so nothing rebuilds) but the raw snapshot is 21 days old."""
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket=BUCKET)
    cy = datetime.now(timezone.utc).year
    s3.put_object(Bucket=BUCKET, Key=_raw_key(cy, _as_of(21)), Body=b"csv")
    s3.put_object(Bucket=BUCKET, Key=_bronze_key(cy), Body=b"parquet")

    with caplog.at_level("ERROR"):
        code = _run_main(monkeypatch, [])

    assert code == 1
    assert "ADVANCE FENCE" in caplog.text


@mock_aws
def test_advance_fence_fires_when_fresh_raw_is_not_consumed(fgis_env, monkeypatch, caplog):
    """The 08-13 shape: fresh raw, STALE bronze, and a skip that discards it must still red.

    Post-M-3 the fence asserts the STATE (bronze older than raw AND not rebuilt this run),
    so an idempotent re-run -- bronze already current, nothing rebuilt -- passes. The
    regression it pins is the original existence-skip defect: _process skipping while
    bronze is genuinely stale. moto cannot express bronze-older-than-raw (same-second
    LastModified), so the skip and the staleness are stubbed exactly as measured live
    (bronze 2026-07-17 vs raw as_of=20260813)."""
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket=BUCKET)
    cy = datetime.now(timezone.utc).year
    s3.put_object(Bucket=BUCKET, Key=_raw_key(cy, _as_of(1)), Body=b"csv")
    s3.put_object(Bucket=BUCKET, Key=_bronze_key(cy), Body=b"parquet")
    # The old defect, resurrected for the pin: skip regardless of staleness ...
    monkeypatch.setattr(fgis_task, "_process", lambda *a, **kw: ("skipped", "stub"))
    # ... while bronze is in fact OLDER than the newest raw (the fence's own check).
    monkeypatch.setattr(fgis_task, "bronze_is_current", lambda *a, **kw: False)

    with caplog.at_level("ERROR"):
        code = _run_main(monkeypatch, [])

    assert code == 1
    assert "NOT rebuilt" in caplog.text


@mock_aws
def test_advance_fence_passes_an_idempotent_rerun(fgis_env, monkeypatch, caplog):
    """Review M-3: bronze already current + nothing rebuilt = a routine re-run, NEVER a red.

    The operator refire / SFN re-execution shape: raw fresh, bronze consumed it on a prior
    run. The event-assertion version of the fence redded this and would have voided the G5
    streak on a routine action."""
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket=BUCKET)
    cy = datetime.now(timezone.utc).year
    s3.put_object(Bucket=BUCKET, Key=_raw_key(cy, _as_of(1)), Body=b"csv")
    s3.put_object(Bucket=BUCKET, Key=_bronze_key(cy), Body=b"parquet")
    monkeypatch.setattr(fgis_task, "_process", lambda *a, **kw: ("skipped", "stub"))
    monkeypatch.setattr(fgis_task, "bronze_is_current", lambda *a, **kw: True)

    code = _run_main(monkeypatch, [])

    assert code is None
    assert "ADVANCE FENCE OK" in caplog.text or code is None


@mock_aws
def test_advance_fence_fires_when_the_fetch_leg_is_dead(fgis_env, monkeypatch, caplog):
    """No raw for the current CY at all."""
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket=BUCKET)
    s3.put_object(Bucket=BUCKET, Key=f"{_RAW}/backfill/CY1999.csv", Body=b"csv")
    s3.put_object(Bucket=BUCKET, Key=_bronze_key(1999), Body=b"parquet")

    with caplog.at_level("ERROR"):
        code = _run_main(monkeypatch, [])

    assert code == 1
    assert "the weekly fetch leg is dead" in caplog.text


@mock_aws
def test_no_advance_fence_flag_stands_down(fgis_env, monkeypatch):
    """The declared escape hatch for a deliberate historical-only rerun."""
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket=BUCKET)
    s3.put_object(Bucket=BUCKET, Key=f"{_RAW}/backfill/CY1999.csv", Body=b"csv")
    s3.put_object(Bucket=BUCKET, Key=_bronze_key(1999), Body=b"parquet")

    assert _run_main(monkeypatch, ["--no-advance-fence"]) is None


@mock_aws
def test_advance_fence_passes_on_healthy_week(fgis_env, monkeypatch, caplog):
    """Raw as_of today, bronze absent -> the year rebuilds and the fence is satisfied."""
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket=BUCKET)
    cy = datetime.now(timezone.utc).year
    s3.put_object(Bucket=BUCKET, Key=_raw_key(cy, _as_of(0)), Body=b"csv")

    monkeypatch.setattr(
        fgis_task, "extract_fgis", lambda raw, year, ingest_date: _one_row_frame()
    )
    with caplog.at_level("INFO"):
        code = _run_main(monkeypatch, [])

    assert code is None
    assert "ADVANCE FENCE OK" in caplog.text


def _one_row_frame():
    import pandas as pd

    return pd.DataFrame({"a": [1]})
