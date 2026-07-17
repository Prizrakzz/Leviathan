"""S3 task-checkpoint + auto re-attach for fetch_modis_ndvi (AppEEARS resilience).

NASA's queue historically takes 6-45h for the 5-group request (May 24 2026 run:
first group 5h45m after submit, last 45h). The local data/batch_runs/ checkpoint
dies with the Batch container, so a restart used to resubmit all 5 tasks at the
back of the queue. These tests pin the new behavior: the submit record is
mirrored to ``raw/weather/source=modis_ndvi/run_id=<rid>/_tasks.json`` and a
fresh container RE-ATTACHES to live tasks instead of resubmitting.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import pytest

from jobs.ingest import fetch_modis_ndvi as mod

_USER, _PW = "u", "p"
_BUCKET, _REGION = "test-bucket", "us-east-1"


def _run_id(hours_ago: float = 3) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).strftime("%Y%m%dT%H%M%SZ")


def _record(run_id: str, end_date: date | None = None, groups: dict | None = None) -> dict:
    return {
        "run_id": run_id,
        "source": "modis_ndvi",
        "stage": "fetch",
        "end_date": (end_date or date.today()).isoformat(),
        "task_ids_by_group": groups or {
            "grains": "t-grains", "oilseeds": "t-oil", "palm_africa": "t-palm",
        },
    }


class _FakeStatusResp:
    def __init__(self, status_code: int, status: str = "processing"):
        self.status_code = status_code
        self._status = status

    def json(self) -> dict:
        return {"status": self._status}


def _wire(monkeypatch, *, tasks_keys, record, csv_keys, statuses):
    """Stub the S3 + AppEEARS seams for _find_reattachable_run."""
    def fake_list(bucket, prefix, suffix=None, aws_region=None):
        if suffix == mod._TASKS_FILENAME:
            return list(tasks_keys)
        if suffix == ".csv":
            return list(csv_keys)
        return []

    monkeypatch.setattr(mod, "list_s3_keys", fake_list)
    monkeypatch.setattr(mod, "download_s3_json", lambda b, k, r: dict(record))
    monkeypatch.setattr(
        mod, "_api_get",
        lambda path, u, p, **kw: _FakeStatusResp(*statuses.get(path.rsplit("/", 1)[-1], (404, ""))),
    )


# -- re-attach happy path -------------------------------------------------------

def test_reattaches_to_live_tasks_and_skips_uploaded_groups(monkeypatch):
    rid = _run_id()
    _wire(
        monkeypatch,
        tasks_keys=[mod._tasks_json_key(rid)],
        record=_record(rid),
        csv_keys=[f"{mod._RAW_PREFIX}run_id={rid}/group=grains/results.csv"],
        statuses={"t-oil": (200, "processing"), "t-palm": (200, "done")},
    )
    out = mod._find_reattachable_run(_BUCKET, _REGION, date.today(), _USER, _PW)
    assert out is not None
    assert out["run_id"] == rid
    assert out["alive_task_ids"] == {"oilseeds": "t-oil", "palm_africa": "t-palm"}
    assert list(out["already_done"]) == ["grains"]
    assert out["dead_groups"] == []


def test_dead_task_goes_to_resubmit_list(monkeypatch):
    rid = _run_id()
    _wire(
        monkeypatch,
        tasks_keys=[mod._tasks_json_key(rid)],
        record=_record(rid),
        csv_keys=[],
        statuses={
            "t-grains": (200, "processing"),
            "t-oil": (404, ""),               # purged server-side
            "t-palm": (200, "expired"),        # dead status
        },
    )
    out = mod._find_reattachable_run(_BUCKET, _REGION, date.today(), _USER, _PW)
    assert out is not None
    assert out["alive_task_ids"] == {"grains": "t-grains"}
    assert sorted(out["dead_groups"]) == ["oilseeds", "palm_africa"]


def test_newest_checkpoint_wins(monkeypatch):
    old_rid, new_rid = _run_id(hours_ago=30), _run_id(hours_ago=2)
    _wire(
        monkeypatch,
        tasks_keys=[mod._tasks_json_key(old_rid), mod._tasks_json_key(new_rid)],
        record=_record(new_rid),
        csv_keys=[],
        statuses={"t-grains": (200, "queued"), "t-oil": (200, "queued"), "t-palm": (200, "queued")},
    )
    out = mod._find_reattachable_run(_BUCKET, _REGION, date.today(), _USER, _PW)
    assert out is not None and out["run_id"] == new_rid


# -- decline conditions ---------------------------------------------------------

def test_declines_when_no_checkpoints(monkeypatch):
    _wire(monkeypatch, tasks_keys=[], record={}, csv_keys=[], statuses={})
    assert mod._find_reattachable_run(_BUCKET, _REGION, date.today(), _USER, _PW) is None


def test_declines_stale_checkpoint(monkeypatch):
    rid = (datetime.now(timezone.utc) - timedelta(days=mod._REATTACH_MAX_AGE_DAYS + 5)).strftime(
        "%Y%m%dT%H%M%SZ"
    )
    _wire(monkeypatch, tasks_keys=[mod._tasks_json_key(rid)], record=_record(rid),
          csv_keys=[], statuses={})
    assert mod._find_reattachable_run(_BUCKET, _REGION, date.today(), _USER, _PW) is None


def test_declines_window_mismatch(monkeypatch):
    rid = _run_id()
    far_end = date.today() - timedelta(days=mod._REATTACH_MAX_AGE_DAYS + 10)
    _wire(monkeypatch, tasks_keys=[mod._tasks_json_key(rid)],
          record=_record(rid, end_date=far_end), csv_keys=[], statuses={})
    assert mod._find_reattachable_run(_BUCKET, _REGION, date.today(), _USER, _PW) is None


def test_declines_fully_uploaded_run(monkeypatch):
    rid = _run_id()
    csvs = [
        f"{mod._RAW_PREFIX}run_id={rid}/group={g}/results.csv"
        for g in ("grains", "oilseeds", "palm_africa")
    ]
    _wire(monkeypatch, tasks_keys=[mod._tasks_json_key(rid)], record=_record(rid),
          csv_keys=csvs, statuses={})
    assert mod._find_reattachable_run(_BUCKET, _REGION, date.today(), _USER, _PW) is None


def test_declines_when_all_tasks_dead(monkeypatch):
    rid = _run_id()
    _wire(monkeypatch, tasks_keys=[mod._tasks_json_key(rid)], record=_record(rid),
          csv_keys=[], statuses={})  # every probe -> 404
    assert mod._find_reattachable_run(_BUCKET, _REGION, date.today(), _USER, _PW) is None


def test_fail_soft_on_s3_error(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("S3 unavailable")

    monkeypatch.setattr(mod, "list_s3_keys", boom)
    assert mod._find_reattachable_run(_BUCKET, _REGION, date.today(), _USER, _PW) is None


# -- checkpoint persistence -----------------------------------------------------

def test_persist_tasks_record_uploads_under_run_prefix(monkeypatch):
    captured: dict = {}

    def fake_upload(data, bucket, key, region):
        captured.update({"data": data, "bucket": bucket, "key": key, "region": region})

    monkeypatch.setattr(mod, "upload_bytes_to_s3", fake_upload)
    rid = _run_id()
    mod._persist_tasks_record(_record(rid), _BUCKET, _REGION)
    assert captured["key"] == f"{mod._RAW_PREFIX}run_id={rid}/{mod._TASKS_FILENAME}"
    assert json.loads(captured["data"])["task_ids_by_group"]["grains"] == "t-grains"


def test_persist_tasks_record_is_best_effort(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("no s3 for you")

    monkeypatch.setattr(mod, "upload_bytes_to_s3", boom)
    mod._persist_tasks_record(_record(_run_id()), _BUCKET, _REGION)  # must not raise


# -- bronze discovery must ignore checkpoint-only runs --------------------------

def test_bronze_discovery_ignores_checkpoint_only_run(monkeypatch):
    from jobs.batch import modis_ndvi_raw_to_bronze_task as bronze

    data_rid, empty_rid = "20260524T183717Z", "20260717T112349Z"
    keys = [
        f"{bronze._RAW_PREFIX}run_id={data_rid}/group=grains/results.csv",
        # crashed submission: checkpoint written, no CSVs ever uploaded
        f"{bronze._RAW_PREFIX}run_id={empty_rid}/_tasks.json",
    ]
    monkeypatch.setattr(bronze, "list_s3_keys", lambda *a, **k: list(keys))
    assert bronze._discover_max_run_id(_BUCKET, _REGION) == data_rid
