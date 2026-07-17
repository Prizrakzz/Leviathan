"""BaseRawToBronzeJob.run_thin_contract: the weather_daily Glue r2b entry.

Pins the contract that broke weather-R1 live (2026-07-17): the r2b Glue job is invoked
with arguments={} + DefaultArguments carrying only --bucket/--aws_region, so the entry
must default --commodity to the 'all' sentinel, discover commodities from the raw
prefix, self-window to the current year, and re-supply consumed opts exactly once per
commodity (getResolvedOptions takes the LAST occurrence; the local fallback the FIRST).
"""
from __future__ import annotations

import sys
from datetime import date

import pandas as pd
import pytest

from leviathan.storage import base_jobs
from leviathan.storage.base_jobs import BaseRawToBronzeJob

_RAW_KEYS = [
    "raw/weather/source=nasa_power/commodity=corn/country=us/region=x/year=2026/month=01/a.json",
    "raw/weather/source=nasa_power/commodity=corn/country=us/region=x/year=2025/month=12/b.json",
    "raw/weather/source=nasa_power/commodity=soybeans/country=br/region=y/year=2026/month=02/c.json",
]


class _FakeJob(BaseRawToBronzeJob):
    source = "nasa_power"
    calls: list[dict] = []
    fail_for: set[str] = set()

    def bronze_key(self, raw_key: str) -> str:
        return raw_key

    def transform(self, raw_bytes: bytes, raw_key: str) -> pd.DataFrame:
        return pd.DataFrame()

    def run(self) -> None:  # capture instead of touching S3
        if self.commodity in _FakeJob.fail_for:
            raise RuntimeError(f"boom {self.commodity}")
        _FakeJob.calls.append({
            "commodity": self.commodity,
            "bucket": self.bucket,
            "aws_region": self.aws_region,
            "year_window": self.year_window,
            "argv": list(sys.argv),
        })


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    _FakeJob.calls = []
    _FakeJob.fail_for = set()
    monkeypatch.setattr(sys, "argv", ["prog"])
    yield


def test_all_mode_discovers_and_windows_current_year(monkeypatch):
    monkeypatch.setattr(
        base_jobs, "list_s3_keys",
        lambda bucket, prefix, suffix=None, aws_region=None: list(_RAW_KEYS),
    )
    _FakeJob.run_thin_contract(["--bucket", "B", "--aws_region", "R"])
    assert [c["commodity"] for c in _FakeJob.calls] == ["corn", "soybeans"]
    assert all(c["year_window"] == date.today().year for c in _FakeJob.calls)
    assert all(c["bucket"] == "B" and c["aws_region"] == "R" for c in _FakeJob.calls)


def test_explicit_all_sentinel_not_duplicated_in_rebuilt_argv(monkeypatch):
    monkeypatch.setattr(
        base_jobs, "list_s3_keys",
        lambda bucket, prefix, suffix=None, aws_region=None: list(_RAW_KEYS),
    )
    _FakeJob.run_thin_contract(
        ["--commodity", "all", "--bucket", "B", "--aws_region", "R", "--ingest_date", "2026-07-17"]
    )
    for c in _FakeJob.calls:
        # exactly one --commodity in the rebuilt argv, and the passthrough survived
        assert c["argv"].count("--commodity") == 1
        assert c["argv"].count("--bucket") == 1
        assert "--ingest_date" in c["argv"]


def test_named_mode_backfills_all_years_without_discovery(monkeypatch):
    def _no_discovery(*a, **k):
        raise AssertionError("named-commodity mode must not LIST for discovery")

    monkeypatch.setattr(base_jobs, "list_s3_keys", _no_discovery)
    _FakeJob.run_thin_contract(["--commodity", "corn", "--bucket", "B", "--aws_region", "R"])
    assert len(_FakeJob.calls) == 1
    assert _FakeJob.calls[0]["commodity"] == "corn"
    assert _FakeJob.calls[0]["year_window"] is None


def test_env_defaults_for_bucket_and_region(monkeypatch):
    monkeypatch.setenv("LEVIATHAN_BUCKET", "env-bucket")
    monkeypatch.setenv("AWS_REGION", "env-region")
    monkeypatch.setattr(
        base_jobs, "list_s3_keys",
        lambda bucket, prefix, suffix=None, aws_region=None: list(_RAW_KEYS),
    )
    _FakeJob.run_thin_contract([])
    assert _FakeJob.calls and all(
        c["bucket"] == "env-bucket" and c["aws_region"] == "env-region" for c in _FakeJob.calls
    )


def test_one_commodity_failure_does_not_kill_the_rest(monkeypatch):
    monkeypatch.setattr(
        base_jobs, "list_s3_keys",
        lambda bucket, prefix, suffix=None, aws_region=None: list(_RAW_KEYS),
    )
    _FakeJob.fail_for = {"corn"}
    with pytest.raises(SystemExit):
        _FakeJob.run_thin_contract(["--bucket", "B", "--aws_region", "R"])
    assert [c["commodity"] for c in _FakeJob.calls] == ["soybeans"]


def test_run_year_window_filters_raw_listing(monkeypatch):
    listed: list[str] = []

    def _fake_list(bucket, prefix, suffix=None, aws_region=None):
        return list(_RAW_KEYS) if "raw/" in prefix else []

    monkeypatch.setattr(base_jobs, "list_s3_keys", _fake_list)
    monkeypatch.setattr(sys, "argv", ["prog", "--commodity", "corn", "--bucket", "B", "--aws_region", "R"])

    class _ListJob(_FakeJob):
        def run(self) -> None:  # real base run, but capture the processed keys
            BaseRawToBronzeJob.run(self)

        def _process_one(self, key, existing):  # type: ignore[override]
            listed.append(key)
            return ("skipped", key)

    job = _ListJob()
    job.year_window = 2026
    job.run()
    assert listed and all("year=2026" in k for k in listed)
