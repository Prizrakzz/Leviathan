"""Tests for jobs/batch/retire_fabricated_weather_task.py (BF-W1 fabrication retirement).

Pins the fail-closed contract: a single REAL value anywhere in the manifest -- silver or the
bronze twin -- refuses the run before any mutation; the retire set comes only from an explicit
manifest; the move is copy-then-delete into the backup prefix and a rerun resumes.
"""
from __future__ import annotations

import importlib.util
import io
import sys
from pathlib import Path

import boto3
import pandas as pd
import pytest
from moto import mock_aws

_REPO = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location(
    "retire_fabricated_weather_task",
    _REPO / "jobs" / "batch" / "retire_fabricated_weather_task.py")
retire = importlib.util.module_from_spec(_spec)
sys.modules["retire_fabricated_weather_task"] = retire
_spec.loader.exec_module(retire)  # type: ignore[union-attr]

BUCKET = "test-leviathan-fab"
REGION = "us-east-1"

SILVER = ("silver/weather/source=chirps/commodity=canola_ice/country=canada/"
          "region=ca_canola_alberta/year=1990/month=03/part-000.parquet")


def _parquet_bytes(col: str, values) -> bytes:
    buf = io.BytesIO()
    pd.DataFrame({col: values, "x": range(len(values))}).to_parquet(buf, index=False)
    return buf.getvalue()


@pytest.fixture()
def s3():
    with mock_aws():
        client = boto3.client("s3", region_name=REGION)
        client.create_bucket(Bucket=BUCKET)
        yield client


def test_bronze_twin_keys_mirror_the_partition():
    twins = retire.bronze_twin_keys(SILVER, "chirps")
    assert twins == [
        "bronze/weather/source=chirps/commodity=canola_ice/country=canada/"
        "region=ca_canola_alberta/year=1990/month=03/part-000.parquet",
        "bronze/weather/source=chirps/commodity=canola_ice/country=canada/"
        "region=ca_canola_alberta/year=1990/month=03/_meta.json",
    ]


def test_verify_ok_when_silver_and_bronze_both_all_nan(s3):
    s3.put_object(Bucket=BUCKET, Key=SILVER,
                  Body=_parquet_bytes("value", [float("nan")] * 5))
    s3.put_object(Bucket=BUCKET, Key=retire.bronze_twin_keys(SILVER, "chirps")[0],
                  Body=_parquet_bytes("precipitation_mm", [float("nan")] * 5))
    assert retire.verify_key(BUCKET, SILVER, "chirps", REGION) == (SILVER, "ok")


def test_verify_ok_when_bronze_absent(s3):
    s3.put_object(Bucket=BUCKET, Key=SILVER,
                  Body=_parquet_bytes("value", [float("nan")] * 5))
    assert retire.verify_key(BUCKET, SILVER, "chirps", REGION) == (SILVER, "ok")


def test_real_silver_refuses(s3):
    s3.put_object(Bucket=BUCKET, Key=SILVER, Body=_parquet_bytes("value", [1.0, 2.0]))
    assert retire.verify_key(BUCKET, SILVER, "chirps", REGION) == (SILVER, "refuse_silver_real")


def test_real_bronze_refuses_even_with_nan_silver(s3):
    # NaN silver + REAL bronze means "rebuild me", never "retire me"
    s3.put_object(Bucket=BUCKET, Key=SILVER,
                  Body=_parquet_bytes("value", [float("nan")] * 5))
    s3.put_object(Bucket=BUCKET, Key=retire.bronze_twin_keys(SILVER, "chirps")[0],
                  Body=_parquet_bytes("precipitation_mm", [4.2, 0.0]))
    assert retire.verify_key(BUCKET, SILVER, "chirps", REGION) == (SILVER, "refuse_bronze_real")


def test_absent_silver_is_already_gone(s3):
    assert retire.verify_key(BUCKET, SILVER, "chirps", REGION) == (SILVER, "already_gone")


def test_move_one_backs_up_then_deletes_and_resumes(s3):
    s3.put_object(Bucket=BUCKET, Key=SILVER,
                  Body=_parquet_bytes("value", [float("nan")] * 3))
    assert retire._move_one(BUCKET, SILVER, REGION) is True
    s3.head_object(Bucket=BUCKET, Key=f"{retire._BACKUP_PREFIX}/{SILVER}")  # backed up
    with pytest.raises(Exception):
        s3.head_object(Bucket=BUCKET, Key=SILVER)                            # deleted
    # resumed run over the already-moved key: no error, reports nothing to move
    assert retire._move_one(BUCKET, SILVER, REGION) is False
