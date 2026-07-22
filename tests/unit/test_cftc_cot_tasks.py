"""Unit tests for the CFTC COT bronze Batch task's weekly-orphan + dedup logic.

The bronze task (``jobs.batch.cftc_cot_bronze_task``) originally enumerated ONLY the
``disagg_futures/backfill/`` prefix, so the Friday ``fetch_cftc_cot --mode weekly``
snapshots landing under ``disagg_futures/year=YYYY/as_of=YYYYMMDD/`` were orphaned.
These tests exercise ``main()`` against fully synthetic in-memory S3 listings and
prove:

  * weekly futures snapshots are now ingested (new bronze partitions written);
  * a weekly report_date already covered by a backfill file is DROPPED at bronze
    time (deterministic precedence: backfill > weekly), never double-ingested;
  * the disagg_combined weekly tree is enumerated for accounting but NEVER parsed
    or written (silver_cot is futures-only);
  * an existing backfill bronze object still contributes its report_dates to the
    weekly dedup on an incremental re-run (harvest-from-bronze path).

AWS-free: the s3 client, list, and download seams are monkeypatched on the module.
"""
from __future__ import annotations

import csv
import io

import pandas as pd
import pytest

from jobs.batch import cftc_cot_bronze_task as task
from leviathan.transforms.raw_to_bronze.cftc_cot import _CANONICAL_COLUMNS

_BUCKET = "leviathan-test"                 # NEVER the prod bucket
_MARKET = "CORN - CHICAGO BOARD OF TRADE"  # maps to corn_cbot, no comma to quote
_N = len(_CANONICAL_COLUMNS)               # 191

# Column positions the parser reads by name (verified against _CANONICAL_COLUMNS).
_COL = {c: i for i, c in enumerate(_CANONICAL_COLUMNS)}


def _row(report_date: str) -> list[str]:
    """One 191-field FutOnly data row for the mapped CORN market at *report_date*."""
    fields = ["0"] * _N
    fields[_COL["Market_and_Exchange_Names"]] = _MARKET
    fields[_COL["As_of_Date_In_Form_YYMMDD"]] = report_date.replace("-", "")[2:]
    fields[_COL["Report_Date_as_YYYY-MM-DD"]] = report_date
    fields[_COL["CFTC_Contract_Market_Code"]] = "002602"
    fields[_COL["Open_Interest_All"]] = "1000"
    fields[_COL["M_Money_Positions_Long_All"]] = "200"
    fields[_COL["M_Money_Positions_Short_All"]] = "100"
    fields[_COL["M_Money_Positions_Spread_All"]] = "10"
    fields[_COL["FutOnly_or_Combined"]] = "FutOnly"
    return fields


def _cot_txt(report_dates: list[str]) -> bytes:
    """A headered futures-only COT TXT covering *report_dates* (one CORN row each)."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(_CANONICAL_COLUMNS)
    for d in report_dates:
        w.writerow(_row(d))
    return buf.getvalue().encode("utf-8")


class _FakeS3:
    """Minimal S3 with head_object (existence) + put_object (write capture)."""

    def __init__(self, existing: set[str] | None = None):
        self.existing = set(existing or ())
        self.puts: dict[str, bytes] = {}

    def head_object(self, Bucket, Key, **kw):
        if Key not in self.existing:
            from botocore.exceptions import ClientError
            raise ClientError({"Error": {"Code": "404", "Message": "404"}}, "HeadObject")
        return {"ContentLength": 1}

    def put_object(self, Bucket, Key, Body, **kw):
        self.puts[Key] = bytes(Body)
        return {"ETag": '"x"'}


@pytest.fixture
def wired(monkeypatch):
    """Install the module seams and return a controller to stage raw + run main()."""

    class Ctl:
        def __init__(self):
            self.raw: dict[str, bytes] = {}          # raw/bronze key -> bytes
            self.s3 = _FakeS3()

        def add_raw(self, key: str, report_dates: list[str]):
            self.raw[key] = _cot_txt(report_dates)

        def add_existing_bronze(self, key: str, report_dates: list[str]):
            self.s3.existing.add(key)
            df = pd.DataFrame({"report_date": report_dates, "leviathan_slug": ["corn_cbot"] * len(report_dates)})
            buf = io.BytesIO()
            df.to_parquet(buf, index=False, engine="pyarrow")
            self.raw[key] = buf.getvalue()

        def run(self, argv: list[str] | None = None):
            import sys
            monkeypatch.setattr(sys, "argv", ["cftc_cot_bronze_task.py", *(argv or [])])
            task.main()

    ctl = Ctl()

    def fake_list(bucket, prefix, suffix="", aws_region="us-east-1"):
        return [k for k in ctl.raw if k.startswith(prefix) and (not suffix or k.endswith(suffix))]

    def fake_download(bucket, key, s3_client):
        return ctl.raw[key]

    monkeypatch.setenv("LEVIATHAN_BUCKET", _BUCKET)
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setattr(task, "get_thread_local_s3_client", lambda region: ctl.s3)
    monkeypatch.setattr(task, "list_s3_keys", fake_list)
    monkeypatch.setattr(task, "s3_download_with_retry", fake_download)
    # load_env would try to read a real dotenv; neutralize it.
    monkeypatch.setattr(task, "load_env", lambda *a, **k: None)
    return ctl


_BK = "raw/production/source=cftc_cot/disagg_futures/backfill/"
_FUT = "raw/production/source=cftc_cot/disagg_futures/"
_COM = "raw/production/source=cftc_cot/disagg_combined/"


def test_weekly_orphan_snapshots_are_ingested(wired):
    wired.add_raw(f"{_BK}fut_disagg_2025.txt", ["2025-12-30"])
    wired.add_raw(f"{_FUT}year=2026/as_of=20260717/fut_disagg_20260717.txt", ["2026-07-07"])

    wired.run()

    puts = wired.s3.puts
    assert "bronze/production/source=cftc_cot/year=2025/part-000.parquet" in puts
    assert "bronze/production/source=cftc_cot/year=20260717/part-000.parquet" in puts
    # the weekly partition really carries the orphaned 2026 report_date
    wk = pd.read_parquet(io.BytesIO(puts["bronze/production/source=cftc_cot/year=20260717/part-000.parquet"]))
    assert set(wk["report_date"]) == {"2026-07-07"}


def test_weekly_row_covered_by_backfill_is_deduped_not_double_ingested(wired):
    # backfill 2025 covers 2025-12-30; a boundary-week weekly file (as_of Fri 2026-01-02)
    # carries report_date 2025-12-30 -- it must be dropped (backfill precedence).
    wired.add_raw(f"{_BK}fut_disagg_2025.txt", ["2025-12-23", "2025-12-30"])
    wired.add_raw(f"{_FUT}year=2026/as_of=20260102/fut_disagg_20260102.txt", ["2025-12-30"])

    wired.run()

    puts = wired.s3.puts
    assert "bronze/production/source=cftc_cot/year=2025/part-000.parquet" in puts
    # fully-covered weekly file writes NOTHING (deduped, not an error, not a partition)
    assert "bronze/production/source=cftc_cot/year=20260102/part-000.parquet" not in puts


def test_weekly_partially_covered_keeps_only_new_dates(wired):
    # An annual 2026 file that is PARTIAL (through 06-30); a weekly file spanning the
    # boundary keeps only the genuinely-new week. Proves dedup is report_date-level,
    # not year-level.
    wired.add_raw(f"{_BK}fut_disagg_2026.txt", ["2026-06-23", "2026-06-30"])
    wired.add_raw(f"{_FUT}year=2026/as_of=20260707/fut_disagg_20260707.txt", ["2026-06-30", "2026-07-07"])

    wired.run()

    key = "bronze/production/source=cftc_cot/year=20260707/part-000.parquet"
    assert key in wired.s3.puts
    kept = pd.read_parquet(io.BytesIO(wired.s3.puts[key]))
    assert set(kept["report_date"]) == {"2026-07-07"}  # 06-30 dropped as backfill-covered


def test_combined_weekly_tree_is_enumerated_but_never_ingested(wired):
    wired.add_raw(f"{_BK}fut_disagg_2025.txt", ["2025-12-30"])
    wired.add_raw(f"{_FUT}year=2026/as_of=20260717/fut_disagg_20260717.txt", ["2026-07-07"])
    # A combined weekly file present on disk -- it must be listed but NEVER parsed/written.
    wired.add_raw(f"{_COM}year=2026/as_of=20260717/com_disagg_20260717.txt", ["2026-07-07"])

    wired.run()

    puts = wired.s3.puts
    # combined never yields a bronze object; only futures partitions exist
    assert all("com_disagg" not in k for k in puts)
    assert len(puts) == 2  # backfill 2025 + weekly 20260717 only


def test_existing_backfill_bronze_still_dedups_weekly_on_rerun(wired):
    # Backfill bronze already written (skip re-write) -- its report_dates must still be
    # harvested so an overlapping weekly file is deduped on the incremental re-run.
    wired.add_raw(f"{_BK}fut_disagg_2025.txt", ["2025-12-30"])
    wired.add_existing_bronze(
        "bronze/production/source=cftc_cot/year=2025/part-000.parquet", ["2025-12-30"]
    )
    wired.add_raw(f"{_FUT}year=2026/as_of=20260102/fut_disagg_20260102.txt", ["2025-12-30"])

    wired.run()

    # backfill not rewritten; weekly fully covered -> nothing new written at all
    assert wired.s3.puts == {}


def test_dry_run_writes_nothing(wired):
    wired.add_raw(f"{_BK}fut_disagg_2025.txt", ["2025-12-30"])
    wired.add_raw(f"{_FUT}year=2026/as_of=20260717/fut_disagg_20260717.txt", ["2026-07-07"])

    wired.run(["--dry-run"])

    assert wired.s3.puts == {}
