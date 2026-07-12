"""Tests for jobs/batch/retire_projected_weather_task.py (BF-W1 month-grain retirement).

Pins the safety contract: (1) the country= prefix selector can never touch a compacted object,
(2) a year without its compacted part-000.parquet REFUSES the whole commodity before any mutation,
(3) the move is copy-then-delete into the backup prefix and a rerun is a resume (idempotent),
(4) dry-run plans without mutating. moto-backed; bucket name is a test name (the conftest
AWS-isolation guard denies prod names unconditionally).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

_REPO = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location(
    "retire_projected_weather_task", _REPO / "jobs" / "batch" / "retire_projected_weather_task.py")
retire = importlib.util.module_from_spec(_spec)
sys.modules["retire_projected_weather_task"] = retire
_spec.loader.exec_module(retire)  # type: ignore[union-attr]

BUCKET = "test-leviathan-retire"
REGION = "us-east-1"


class _Auth:
    """Minimal Authorization stand-in (the task only reads may_mutate_canonical + mode)."""

    class _Mode:
        value = "canonical"

    mode = _Mode()

    def __init__(self, may_mutate: bool) -> None:
        self.may_mutate_canonical = may_mutate


def _put(s3, key: str, body: bytes = b"x" * 16) -> None:
    s3.put_object(Bucket=BUCKET, Key=key, Body=body)


def _month_key(commodity: str, year: int, month: int) -> str:
    return (f"silver/weather/source=chirps/commodity={commodity}/country=ghana/"
            f"region=gh_main/year={year}/month={month:02d}/data.parquet")


def _compacted(commodity: str, year: int) -> str:
    return retire.compacted_key("chirps", commodity, year)


@pytest.fixture()
def s3():
    with mock_aws():
        client = boto3.client("s3", region_name=REGION)
        client.create_bucket(Bucket=BUCKET)
        yield client


def test_selector_never_matches_compacted_objects(s3):
    _put(s3, _month_key("cocoa", 2020, 1))
    _put(s3, _compacted("cocoa", 2020))
    keys = retire.month_grain_keys(BUCKET, "chirps", "cocoa", REGION)
    assert keys == [_month_key("cocoa", 2020, 1)]


def test_missing_compacted_year_refuses_before_any_mutation(s3):
    _put(s3, _month_key("cocoa", 2020, 1))
    _put(s3, _month_key("cocoa", 2021, 2))
    _put(s3, _compacted("cocoa", 2020))  # 2021 compacted object deliberately absent
    result = retire.retire_commodity(BUCKET, "chirps", "cocoa", REGION, _Auth(True))
    assert result["state"] == "refused_missing_compacted"
    assert result["missing_years"] == [2021]
    # nothing moved, nothing deleted
    assert retire.month_grain_keys(BUCKET, "chirps", "cocoa", REGION) != []
    listed = s3.list_objects_v2(Bucket=BUCKET, Prefix=retire._BACKUP_PREFIX)
    assert listed.get("KeyCount", 0) == 0


def test_empty_compacted_object_counts_as_missing(s3):
    _put(s3, _month_key("cocoa", 2020, 1))
    _put(s3, _compacted("cocoa", 2020), body=b"")
    result = retire.retire_commodity(BUCKET, "chirps", "cocoa", REGION, _Auth(True))
    assert result["state"] == "refused_missing_compacted"


def test_dry_run_plans_without_mutating(s3):
    _put(s3, _month_key("cocoa", 2020, 1))
    _put(s3, _compacted("cocoa", 2020))
    result = retire.retire_commodity(BUCKET, "chirps", "cocoa", REGION, _Auth(False))
    assert result["state"] == "planned"
    assert result["would_move"] == 1
    assert retire.month_grain_keys(BUCKET, "chirps", "cocoa", REGION) != []


def test_canonical_moves_to_backup_and_deletes(s3):
    months = [_month_key("cocoa", 2020, m) for m in (1, 2, 3)]
    for k in months:
        _put(s3, k)
    _put(s3, _compacted("cocoa", 2020))
    result = retire.retire_commodity(BUCKET, "chirps", "cocoa", REGION, _Auth(True))
    assert result["state"] == "retired"
    assert result["moved"] == 3
    assert retire.month_grain_keys(BUCKET, "chirps", "cocoa", REGION) == []
    for k in months:
        s3.head_object(Bucket=BUCKET, Key=f"{retire._BACKUP_PREFIX}/{k}")  # raises if absent
    # the compacted object is untouched
    s3.head_object(Bucket=BUCKET, Key=_compacted("cocoa", 2020))


def test_rerun_is_an_idempotent_resume(s3):
    _put(s3, _month_key("cocoa", 2020, 1))
    _put(s3, _compacted("cocoa", 2020))
    first = retire.retire_commodity(BUCKET, "chirps", "cocoa", REGION, _Auth(True))
    assert first["state"] == "retired" and first["moved"] == 1
    # simulate a resumed run over a partially-done tree: re-create one month object whose
    # backup copy already exists -- the rerun must not fail on the existing destination
    _put(s3, _month_key("cocoa", 2020, 1))
    second = retire.retire_commodity(BUCKET, "chirps", "cocoa", REGION, _Auth(True))
    assert second["state"] == "retired" and second["moved"] == 1
    assert retire.month_grain_keys(BUCKET, "chirps", "cocoa", REGION) == []
