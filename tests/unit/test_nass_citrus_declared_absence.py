"""D-PR-25 (pipeline-reliability wave, failure class G): citrus SEASONAL ABSENCE is DECLARED.

Class G is "expected vendor ABSENCE treated as failure". Citrus is seasonally absent by design --
the forecast season runs October -> July, the schedule ``cron(0 18 13 1-7,10-12 ? *)`` skips months
8-9, and ``current_forecast_season`` falls forward in Aug/Sep -- so an out-of-season fire targets a
season whose raw prefix is EMPTY BY CONSTRUCTION. Independently the vendor has been paused since
2024-25/cit0725.pdf, so an in-season fire can find nothing either.

The ratified shape is exit 0 **with an explicit "source not published this season" record**:
never a FAIL, and never a silent skip. These tests pin all three halves of that -- the exit code,
the record, and the fact that the record does NOT appear when the vendor did publish -- across
BOTH season states.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest

_REPO = Path(__file__).resolve().parents[2]


def _load(rel: str, name: str):
    spec = importlib.util.spec_from_file_location(name, _REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


TASK = _load("jobs/batch/nass_citrus_bronze_task.py", "nass_citrus_bronze_task_dpr25")

# The two season states under test, both expressed as an EventBridge scheduled-time (the exact
# shape --asof carries on the real chain).
OUT_OF_SEASON_ASOF = "2026-08-15T18:00:00Z"   # Aug: closed period -> falls forward to 2026-27
IN_SEASON_ASOF = "2026-01-13T18:00:00Z"       # Jan: 2025-26 is open (opened 2025-10-01)

BUCKET = "leviathan-dev-shahem-001"


class _FakeS3:
    """Records put_object calls; raises on demand to exercise the best-effort persistence path."""

    def __init__(self, fail: bool = False):
        self.puts: list[dict] = []
        self.fail = fail

    def put_object(self, **kwargs):
        if self.fail:
            raise RuntimeError("s3 is down")
        self.puts.append(kwargs)
        return {}


@pytest.fixture
def s3_stub(monkeypatch):
    """Patch the storage seam ``_build_season_bronze`` imports at call time."""
    import leviathan.storage.s3 as S

    fake = _FakeS3()
    state = {"keys": [], "client": fake, "exists": False}

    monkeypatch.setattr(S, "get_thread_local_s3_client", lambda *a, **k: state["client"])
    monkeypatch.setattr(S, "list_s3_keys", lambda *a, **k: list(state["keys"]))
    monkeypatch.setattr(S, "s3_download_with_retry", lambda *a, **k: b"%PDF-fake")
    monkeypatch.setattr(S, "s3_object_exists", lambda *a, **k: state["exists"])
    return state


def _absence_puts(fake: _FakeS3) -> list[dict]:
    return [p for p in fake.puts if "declared_absence" in p["Key"]]


# ---------------------------------------------------------------------------
# Season arithmetic -- the classifier that decides WHICH absence this is
# ---------------------------------------------------------------------------
class TestSeasonOpenDate:
    def test_season_opens_1_october_of_its_start_year(self):
        assert TASK.season_open_date("2026-27") == dt.date(2026, 10, 1)
        assert TASK.season_open_date("2024-25") == dt.date(2024, 10, 1)

    def test_end_year_wrap_is_still_parsed_from_the_start_year(self):
        # '1999-00' wraps at the century; the OPEN date only ever reads the four-digit head.
        assert TASK.season_open_date("1999-00") == dt.date(1999, 10, 1)

    @pytest.mark.parametrize("bad", ["2026", "26-27", "2026-2027", "", "abcd-ef", "2026/27"])
    def test_malformed_season_raises_rather_than_declaring_an_absence(self, bad):
        # A typo in --season must NEVER be silently classified as an expected absence: that would
        # convert an operator error into a green fire with a fabricated record.
        with pytest.raises(ValueError):
            TASK.season_open_date(bad)


class TestAbsenceReason:
    def test_out_of_season_fire_is_season_not_open(self):
        from leviathan.transforms.raw_to_bronze.nass_citrus import current_forecast_season
        season = current_forecast_season(OUT_OF_SEASON_ASOF)
        assert season == "2026-27"                       # the Aug/Sep fall-forward
        assert TASK.absence_reason(season, OUT_OF_SEASON_ASOF) == \
            TASK.ABSENCE_REASON_SEASON_NOT_OPEN

    def test_in_season_fire_is_source_not_published(self):
        from leviathan.transforms.raw_to_bronze.nass_citrus import current_forecast_season
        season = current_forecast_season(IN_SEASON_ASOF)
        assert season == "2025-26"
        assert TASK.absence_reason(season, IN_SEASON_ASOF) == \
            TASK.ABSENCE_REASON_SOURCE_NOT_PUBLISHED

    def test_the_boundary_is_the_open_date_itself(self):
        # 30 Sep: cannot have published. 1 Oct: open, so an empty prefix is the vendor's silence.
        assert TASK.absence_reason("2026-27", "2026-09-30") == TASK.ABSENCE_REASON_SEASON_NOT_OPEN
        assert TASK.absence_reason("2026-27", "2026-10-01") == \
            TASK.ABSENCE_REASON_SOURCE_NOT_PUBLISHED

    def test_reasons_are_distinct_and_neither_is_a_failure_word(self):
        assert TASK.ABSENCE_REASON_SEASON_NOT_OPEN != TASK.ABSENCE_REASON_SOURCE_NOT_PUBLISHED


class TestDeclaredAbsenceRecord:
    def test_record_names_the_season_the_reason_and_the_prefix(self):
        rec = TASK.declared_absence_record(
            bucket=BUCKET, prefix="raw/production/source=usda_nass_citrus/season=2026-27/",
            season="2026-27", asof=OUT_OF_SEASON_ASOF)
        assert rec["record_type"] == "declared_absence"
        assert rec["decision"] == "D-PR-25"
        assert rec["source"] == "usda_nass_citrus"
        assert rec["report_type"] == "monthly_forecast"
        assert rec["season"] == "2026-27"
        assert rec["season_opens"] == "2026-10-01"
        assert rec["asof"] == OUT_OF_SEASON_ASOF
        assert rec["fire_date"] == "2026-08-15"
        assert rec["reason"] == TASK.ABSENCE_REASON_SEASON_NOT_OPEN
        assert rec["raw_objects_found"] == 0
        assert rec["raw_prefix"].startswith(f"s3://{BUCKET}/")
        assert rec["declared_at"]
        # The record must be self-describing on its own -- it outlives the job log.
        assert "2026-10-01" in rec["detail"]

    def test_in_season_record_says_the_vendor_published_nothing(self):
        rec = TASK.declared_absence_record(
            bucket=BUCKET, prefix="p/", season="2025-26", asof=IN_SEASON_ASOF)
        assert rec["reason"] == TASK.ABSENCE_REASON_SOURCE_NOT_PUBLISHED
        assert "open" in rec["detail"]

    def test_record_is_json_serialisable(self):
        rec = TASK.declared_absence_record(
            bucket=BUCKET, prefix="p/", season="2026-27", asof=OUT_OF_SEASON_ASOF)
        assert json.loads(json.dumps(rec, sort_keys=True)) == rec

    def test_key_is_one_object_per_season_and_fire_date(self):
        rec = TASK.declared_absence_record(
            bucket=BUCKET, prefix="p/", season="2026-27", asof=OUT_OF_SEASON_ASOF)
        key = TASK.absence_record_key(rec)
        assert key == ("raw_meta/declared_absence/source=usda_nass_citrus/"
                       "report_type=monthly_forecast/season=2026-27/2026-08-15.json")
        # A retry of the same fire overwrites in place rather than minting a second record.
        assert TASK.absence_record_key(rec) == key


# ---------------------------------------------------------------------------
# The producer itself -- both season states, end to end over a fake S3
# ---------------------------------------------------------------------------
class TestOutOfSeasonFire:
    def test_exits_zero_with_a_record_never_a_failure(self, s3_stub, caplog):
        s3_stub["keys"] = []                       # the empty season prefix, by construction
        with caplog.at_level("WARNING"):
            written, skipped, failed, absence = TASK._build_season_bronze(
                BUCKET, "2026-27", "us-east-1", skip_existing=False, dry_run=False,
                asof=OUT_OF_SEASON_ASOF)

        assert (written, skipped, failed) == (0, 0, 0)   # failed == 0 is what keeps main() at exit 0
        assert absence is not None
        assert absence["reason"] == TASK.ABSENCE_REASON_SEASON_NOT_OPEN

        # NOT A SILENT SKIP, half 1: the declaration is in the job log, marker-prefixed.
        marked = [r.getMessage() for r in caplog.records
                  if TASK.DECLARED_ABSENCE_MARKER in r.getMessage()]
        assert len(marked) == 1
        assert json.loads(marked[0].split(TASK.DECLARED_ABSENCE_MARKER, 1)[1].strip()) == absence

        # NOT A SILENT SKIP, half 2: the record is durable, and it is the ONLY thing written.
        puts = s3_stub["client"].puts
        assert len(puts) == 1
        assert puts[0]["Key"] == TASK.absence_record_key(absence)
        assert json.loads(puts[0]["Body"].decode("utf-8")) == absence
        assert puts[0]["ContentType"] == "application/json"

    def test_main_returns_without_a_nonzero_exit(self, s3_stub, monkeypatch):
        # The acceptance in one line: an out-of-season fire is a SUCCESS.
        s3_stub["keys"] = []
        monkeypatch.setenv("LEVIATHAN_BUCKET", BUCKET)
        monkeypatch.setenv("AWS_REGION", "us-east-1")
        monkeypatch.setattr(TASK, "load_env", lambda: None)
        monkeypatch.setattr(
            TASK.sys, "argv",
            ["nass_citrus_bronze_task.py", "--asof", OUT_OF_SEASON_ASOF])
        TASK.main()   # a SystemExit with a non-zero code would fail the test here
        assert len(_absence_puts(s3_stub["client"])) == 1

    def test_dry_run_declares_but_writes_nothing(self, s3_stub, caplog):
        s3_stub["keys"] = []
        with caplog.at_level("WARNING"):
            *_, absence = TASK._build_season_bronze(
                BUCKET, "2026-27", "us-east-1", skip_existing=False, dry_run=True,
                asof=OUT_OF_SEASON_ASOF)
        assert absence is not None
        assert s3_stub["client"].puts == []
        assert any(TASK.DECLARED_ABSENCE_MARKER in r.getMessage() for r in caplog.records)

    def test_a_failed_record_write_still_exits_zero(self, s3_stub, caplog):
        # Best-effort persistence: failing the fire because the RECORD could not be written would
        # manufacture the very red D-PR-25 removes. The marker line already carries the declaration.
        s3_stub["keys"] = []
        s3_stub["client"] = _FakeS3(fail=True)
        with caplog.at_level("WARNING"):
            written, skipped, failed, absence = TASK._build_season_bronze(
                BUCKET, "2026-27", "us-east-1", skip_existing=False, dry_run=False,
                asof=OUT_OF_SEASON_ASOF)
        assert (written, skipped, failed) == (0, 0, 0)
        assert absence is not None
        assert any(TASK.DECLARED_ABSENCE_MARKER in r.getMessage() for r in caplog.records)


class TestInSeasonFire:
    def test_open_season_with_no_vendor_publication_is_declared_not_skipped(self, s3_stub):
        s3_stub["keys"] = []
        written, skipped, failed, absence = TASK._build_season_bronze(
            BUCKET, "2025-26", "us-east-1", skip_existing=False, dry_run=False,
            asof=IN_SEASON_ASOF)
        assert (written, skipped, failed) == (0, 0, 0)
        assert absence["reason"] == TASK.ABSENCE_REASON_SOURCE_NOT_PUBLISHED
        assert absence["season"] == "2025-26"
        assert len(_absence_puts(s3_stub["client"])) == 1

    def test_a_published_season_writes_bronze_and_declares_NO_absence(self, s3_stub, monkeypatch):
        # The other side of the fence: once the vendor publishes, the declared-absence path must
        # never fire -- otherwise the record stops meaning anything.
        s3_stub["keys"] = ["raw/production/source=usda_nass_citrus/report_type=monthly_forecast/"
                           "season=2025-26/cit0126.pdf"]
        monkeypatch.setattr(
            TASK, "extract_nass_citrus_forecast_bronze",
            lambda *a, **k: pd.DataFrame({"report_month": [1], "value_1000_boxes": [5000.0]}))

        written, skipped, failed, absence = TASK._build_season_bronze(
            BUCKET, "2025-26", "us-east-1", skip_existing=False, dry_run=False,
            asof=IN_SEASON_ASOF)

        assert (written, skipped, failed) == (1, 0, 0)
        assert absence is None
        assert _absence_puts(s3_stub["client"]) == []
        assert len(s3_stub["client"].puts) == 1                  # the bronze parquet only
        assert s3_stub["client"].puts[0]["Key"].startswith("bronze/")

    def test_a_bad_pdf_is_still_a_hard_failure(self, s3_stub, monkeypatch):
        # D-PR-25 declares an ABSENCE, it does not soften a real parse fault into a green fire.
        s3_stub["keys"] = ["raw/production/source=usda_nass_citrus/report_type=monthly_forecast/"
                           "season=2025-26/cit0126.pdf"]

        def _boom(*a, **k):
            raise ValueError("corrupt page")

        monkeypatch.setattr(TASK, "extract_nass_citrus_forecast_bronze", _boom)
        written, skipped, failed, absence = TASK._build_season_bronze(
            BUCKET, "2025-26", "us-east-1", skip_existing=False, dry_run=False,
            asof=IN_SEASON_ASOF)
        assert (written, skipped, failed) == (0, 0, 1)   # main() exits 1 on failed
        assert absence is None
