"""Delta-window MODIS fetch: stop re-extracting 26 years server-side every run.

The AppEEARS payload used to hardcode startDate 02-18-2000, so each biweekly
fetch made NASA re-extract the full history (a major driver of the 6-45h
queue+compute wait). These tests pin the delta derivation, the window fields on
the S3 checkpoint, the re-attach window-compatibility guard, and the r2b
recent-year refresh that delta-shaped CSVs depend on (a frozen current-year
bronze object would silently eat every delta run's new composites).
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import pytest

from jobs.ingest import fetch_modis_ndvi as mod

_BUCKET, _REGION = "test-bucket", "us-east-1"
_USER, _PW = "u", "p"


def _rid(days_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%Y%m%dT%H%M%SZ")


def _csv_key(rid: str, group: str = "grains") -> str:
    return f"{mod._RAW_PREFIX}run_id={rid}/group={group}/results.csv"


# -- _derive_delta_start --------------------------------------------------------

def test_delta_start_from_checkpoint_end_date(monkeypatch):
    rid = _rid(3)
    rec_end = date.today() - timedelta(days=3)
    monkeypatch.setattr(mod, "list_s3_keys", lambda *a, **k: [_csv_key(rid)])
    monkeypatch.setattr(
        mod, "download_s3_json",
        lambda b, k, r: {"end_date": rec_end.isoformat(), "task_ids_by_group": {}},
    )
    out = mod._derive_delta_start(_BUCKET, _REGION, date.today())
    expected = (rec_end - timedelta(days=mod._COMPOSITE_PERIOD_DAYS)).strftime("%m-%d-%Y")
    assert out == expected


def test_delta_start_falls_back_to_run_id_stamp(monkeypatch):
    rid = _rid(5)
    monkeypatch.setattr(mod, "list_s3_keys", lambda *a, **k: [_csv_key(rid)])

    def no_checkpoint(*a, **k):
        raise FileNotFoundError("pre-delta run has no _tasks.json")

    monkeypatch.setattr(mod, "download_s3_json", no_checkpoint)
    out = mod._derive_delta_start(_BUCKET, _REGION, date.today())
    rid_date = datetime.strptime(rid, "%Y%m%dT%H%M%SZ").date()
    expected = (rid_date - timedelta(days=mod._COMPOSITE_PERIOD_DAYS)).strftime("%m-%d-%Y")
    assert out == expected


def test_delta_start_newest_completed_run_wins(monkeypatch):
    old, new = _rid(40), _rid(2)
    monkeypatch.setattr(mod, "list_s3_keys", lambda *a, **k: [_csv_key(old), _csv_key(new)])

    def only_new(b, k, r):
        assert new in k, "must read the NEWEST completed run's checkpoint"
        raise FileNotFoundError

    monkeypatch.setattr(mod, "download_s3_json", only_new)
    out = mod._derive_delta_start(_BUCKET, _REGION, date.today())
    assert out is not None


def test_full_history_when_no_completed_runs(monkeypatch):
    monkeypatch.setattr(mod, "list_s3_keys", lambda *a, **k: [])
    assert mod._derive_delta_start(_BUCKET, _REGION, date.today()) is None


def test_delta_probe_fail_soft(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("S3 down")

    monkeypatch.setattr(mod, "list_s3_keys", boom)
    assert mod._derive_delta_start(_BUCKET, _REGION, date.today()) is None


def test_delta_start_clamped_before_requested_end(monkeypatch):
    rid = _rid(1)
    future_end = date.today() + timedelta(days=30)
    monkeypatch.setattr(mod, "list_s3_keys", lambda *a, **k: [_csv_key(rid)])
    monkeypatch.setattr(
        mod, "download_s3_json",
        lambda b, k, r: {"end_date": future_end.isoformat(), "task_ids_by_group": {}},
    )
    requested_end = date.today() - timedelta(days=5)
    out = mod._derive_delta_start(_BUCKET, _REGION, requested_end)
    assert datetime.strptime(out, "%m-%d-%Y").date() < requested_end


# -- submission payload ---------------------------------------------------------

def test_submit_payload_uses_provided_start(monkeypatch):
    captured: dict = {}

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"task_id": "t-1"}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["payload"] = json
        return _Resp()

    monkeypatch.setattr(mod.requests, "post", fake_post)
    mod._submit_one_task(
        group="grains", coords=[], end_date_appeears="07-17-2026",
        product="MOD13Q1.061", layers={"ndvi": "n", "quality": "q"},
        run_id="r", user=_USER, password=_PW, start_date_appeears="06-15-2026",
    )
    assert captured["payload"]["params"]["dates"][0]["startDate"] == "06-15-2026"


def test_submit_payload_defaults_to_full_history(monkeypatch):
    captured: dict = {}

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"task_id": "t-1"}

    monkeypatch.setattr(
        mod.requests, "post",
        lambda url, json=None, headers=None, timeout=None: captured.update(p=json) or _Resp(),
    )
    mod._submit_one_task(
        group="grains", coords=[], end_date_appeears="07-17-2026",
        product="MOD13Q1.061", layers={"ndvi": "n", "quality": "q"},
        run_id="r", user=_USER, password=_PW,
    )
    assert captured["p"]["params"]["dates"][0]["startDate"] == mod._FULL_HISTORY_START


# -- re-attach window-compatibility guard ---------------------------------------

def _wire_reattach(monkeypatch, record):
    rid = record["run_id"]
    def fake_list(bucket, prefix, suffix=None, aws_region=None):
        if suffix == mod._TASKS_FILENAME:
            return [mod._tasks_json_key(rid)]
        return []  # no CSVs uploaded yet

    monkeypatch.setattr(mod, "list_s3_keys", fake_list)
    monkeypatch.setattr(mod, "download_s3_json", lambda b, k, r: dict(record))

    class _Alive:
        status_code = 200

        def json(self):
            return {"status": "processing"}

    monkeypatch.setattr(mod, "_api_get", lambda *a, **k: _Alive())


def test_reattach_declines_window_narrower_than_manual_start(monkeypatch):
    rid = _rid(0.1)
    record = {
        "run_id": rid, "end_date": date.today().isoformat(),
        "start_date": (date.today() - timedelta(days=20)).isoformat(),
        "task_ids_by_group": {"grains": "t-1"},
    }
    _wire_reattach(monkeypatch, record)
    manual_start = date.today() - timedelta(days=365)
    out = mod._find_reattachable_run(_BUCKET, _REGION, date.today(), _USER, _PW, manual_start)
    assert out is None


def test_reattach_accepts_pre_delta_full_history_checkpoint(monkeypatch):
    rid = _rid(0.1)
    record = {  # pre-delta checkpoint: no start_date == full history == covers any start
        "run_id": rid, "end_date": date.today().isoformat(),
        "task_ids_by_group": {"grains": "t-1"},
    }
    _wire_reattach(monkeypatch, record)
    manual_start = date.today() - timedelta(days=365)
    out = mod._find_reattachable_run(_BUCKET, _REGION, date.today(), _USER, _PW, manual_start)
    assert out is not None and out["run_id"] == rid


def test_reattach_auto_mode_skips_start_check(monkeypatch):
    rid = _rid(0.1)
    record = {
        "run_id": rid, "end_date": date.today().isoformat(),
        "start_date": (date.today() - timedelta(days=20)).isoformat(),
        "task_ids_by_group": {"grains": "t-1"},
    }
    _wire_reattach(monkeypatch, record)
    out = mod._find_reattachable_run(_BUCKET, _REGION, date.today(), _USER, _PW, None)
    assert out is not None


# -- r2b recent-year refresh (delta correctness dependency) ---------------------

class _FakeS3:
    class exceptions:
        class ClientError(Exception):
            def __init__(self, code="404"):
                self.response = {"Error": {"Code": code}}

    def __init__(self, existing: set[str]):
        self.existing = existing
        self.puts: list[str] = []

    def head_object(self, Bucket, Key):
        if Key not in self.existing:
            raise self.exceptions.ClientError("404")

    def put_object(self, Bucket, Key, Body):
        self.puts.append(Key)


def _bronze_df():
    return pd.DataFrame({"ndvi": [0.5]})


def test_r2b_rewrites_current_year_despite_existing_object():
    from jobs.batch import modis_ndvi_raw_to_bronze_task as r2b
    from leviathan.storage.paths import bronze_modis_ndvi_key

    year = date.today().year
    key = bronze_modis_ndvi_key("corn", "us", "iowa", year)
    s3 = _FakeS3(existing={key})
    wrote = r2b._write_bronze_partition(
        s3, _BUCKET, "corn", "us", "iowa", year, _bronze_df(),
        force_overwrite=False, refresh_year_floor=year,
    )
    assert wrote and s3.puts == [key]


def test_r2b_still_skips_existing_old_year():
    from jobs.batch import modis_ndvi_raw_to_bronze_task as r2b
    from leviathan.storage.paths import bronze_modis_ndvi_key

    key = bronze_modis_ndvi_key("corn", "us", "iowa", 2019)
    s3 = _FakeS3(existing={key})
    wrote = r2b._write_bronze_partition(
        s3, _BUCKET, "corn", "us", "iowa", 2019, _bronze_df(),
        force_overwrite=False, refresh_year_floor=date.today().year,
    )
    assert not wrote and s3.puts == []


def test_r2b_writes_missing_old_year():
    from jobs.batch import modis_ndvi_raw_to_bronze_task as r2b

    s3 = _FakeS3(existing=set())
    wrote = r2b._write_bronze_partition(
        s3, _BUCKET, "corn", "us", "iowa", 2019, _bronze_df(),
        force_overwrite=False, refresh_year_floor=date.today().year,
    )
    assert wrote and len(s3.puts) == 1


def test_partial_run_not_a_delta_anchor(monkeypatch):
    """A run with a checkpoint but missing group CSVs must not anchor the window --
    the OLDER complete run wins, so the partial run's date range is never orphaned."""
    old_rid, new_rid = _rid(30), _rid(0.2)
    keys = [_csv_key(old_rid), _csv_key(new_rid, "grains")]  # new run: 1 of 3 groups

    def fake_list(bucket, prefix, suffix=None, aws_region=None):
        return list(keys) if suffix == ".csv" else []

    def fake_json(bucket, key, region):
        if new_rid in key:
            return {
                "end_date": date.today().isoformat(),
                "task_ids_by_group": {"grains": "t1", "oilseeds": "t2", "palm_africa": "t3"},
            }
        raise FileNotFoundError("old run is pre-checkpoint")

    monkeypatch.setattr(mod, "list_s3_keys", fake_list)
    monkeypatch.setattr(mod, "download_s3_json", fake_json)
    out = mod._derive_delta_start(_BUCKET, _REGION, date.today())
    old_date = datetime.strptime(old_rid, "%Y%m%dT%H%M%SZ").date()
    expected = (old_date - timedelta(days=mod._COMPOSITE_PERIOD_DAYS)).strftime("%m-%d-%Y")
    assert out == expected
