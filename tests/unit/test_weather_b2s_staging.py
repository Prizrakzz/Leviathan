"""A-Wave-3 weather bronze->silver staging retrofit (SILVER-F047 layout coherence).

The three per-source b2s producers (chirps + cpc batch, nasa_power glue) now:
  * write MONTH-grain silver to the ``_staging`` tier (OUTSIDE the ``commodity=`` data plane) so
    compact_weather_silver can publish the coarse ``[commodity, year]`` object canonically without the
    feature extractor + gold reader double-reading month-grain;
  * run the shared zero-required-arg thin-contract runner (``--commodity all`` iterates discovered
    commodities, self-windowed to the current year; a named commodity is the all-years backfill);
  * self-window the bronze read to the current year on the daily 'all' path.

These tests exercise the pure/seam logic (staging keys, the argv scan, the year filter, and the
run_thin_contract loop) with stubbed S3/env -- no network.
"""
from __future__ import annotations

import datetime

import pytest

from jobs.batch.bronze_to_silver_chirps_task import ChirpsBronzeToSilver
from jobs.batch.cpc_bronze_to_silver_task import CpcSoilBronzeToSilver
from leviathan.storage import base_jobs
from leviathan.storage.base_jobs import BaseBronzeToSilverJob, _extract_cli_opt, filter_keys_by_year

_CUR = datetime.date.today().year


# ---------------------------------------------------------------------------
# argv scan (Batch + Glue: works on raw sys.argv, space AND equals forms)
# ---------------------------------------------------------------------------
def test_extract_cli_opt_space_equals_and_default():
    assert _extract_cli_opt(["--commodity", "all", "--bucket", "B"], "commodity") == "all"
    assert _extract_cli_opt(["--commodity=arabica_coffee"], "commodity") == "arabica_coffee"
    assert _extract_cli_opt(["--bucket", "B"], "commodity", "all") == "all"
    assert _extract_cli_opt(["--flag"], "flag", "x") == "x"  # trailing valueless flag -> default


# ---------------------------------------------------------------------------
# year-window filter (bounds the daily bronze read to the current year)
# ---------------------------------------------------------------------------
def test_filter_keys_by_year():
    keys = [
        "bronze/weather/source=chirps/commodity=c/country=x/region=y/year=2025/month=12/part-000.parquet",
        "bronze/weather/source=chirps/commodity=c/country=x/region=y/year=2026/month=07/part-000.parquet",
        "bronze/.../no-year-here/part.parquet",
    ]
    assert filter_keys_by_year(keys, 2026) == [keys[1]]
    assert filter_keys_by_year(keys, None) == keys  # None = every year (backfill)


# ---------------------------------------------------------------------------
# staging silver keys + prefix (OUTSIDE the commodity= data plane)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("cls,source", [(ChirpsBronzeToSilver, "chirps"), (CpcSoilBronzeToSilver, "cpc_soil")])
def test_b2s_writes_to_staging_tier(cls, source):
    job = cls(commodity="arabica_coffee", bucket="B", aws_region="R", force_overwrite=False)
    assert job.staging is True
    prefix = job.silver_prefix()
    assert prefix == f"silver/weather/source={source}/_staging/commodity=arabica_coffee/"
    key = job._silver_key({"country": "brazil", "region": "br_x", "year": 2026, "month": 7})
    assert key == (
        f"silver/weather/source={source}/_staging/commodity=arabica_coffee"
        "/country=brazil/region=br_x/year=2026/month=07/part-000.parquet"
    )
    # The staging key is a SIBLING of commodity= under source=, never nested under commodity=<c>/year=.
    assert "/_staging/" in key
    assert not key.startswith(f"silver/weather/source={source}/commodity=arabica_coffee/year=")


# ---------------------------------------------------------------------------
# thin-contract runner: 'all' iterates + current-year window; named = all-years backfill
# ---------------------------------------------------------------------------
class _RecordingJob(BaseBronzeToSilverJob):
    source = "chirps"
    staging = True
    constructed: list = []

    def __init__(self, **kw):
        super().__init__(**kw)
        _RecordingJob.constructed.append(
            (self.commodity, self.bucket, self.aws_region, self.force_overwrite, self.year_window)
        )

    def transform(self, df):  # pragma: no cover - not exercised
        return df

    def get_partitions(self, df):  # pragma: no cover
        return []

    def _silver_key(self, key_dict):  # pragma: no cover
        return "x"

    def run(self):  # no S3 -- the runner loop is what we assert
        pass


def _stub_config(monkeypatch):
    import leviathan.common.config as cfg
    monkeypatch.setattr(cfg, "load_env", lambda: None)
    monkeypatch.setattr(cfg, "get_required_env",
                        lambda k: {"LEVIATHAN_BUCKET": "B", "AWS_REGION": "R"}[k])


def test_run_thin_contract_all_iterates_current_year(monkeypatch):
    _RecordingJob.constructed = []
    _stub_config(monkeypatch)
    monkeypatch.setattr(base_jobs, "list_s3_keys", lambda *a, **k: [
        "bronze/weather/source=chirps/commodity=arabica_coffee/country=x/region=y/year=2026/month=07/part-000.parquet",
        "bronze/weather/source=chirps/commodity=corn_cbot/country=x/region=y/year=2026/month=07/part-000.parquet",
    ])
    _RecordingJob.run_thin_contract(["--commodity", "all", "--bucket", "B", "--aws_region", "R"])
    commodities = [c[0] for c in _RecordingJob.constructed]
    assert commodities == ["arabica_coffee", "corn_cbot"]
    assert all(yw == _CUR for *_rest, yw in _RecordingJob.constructed)  # current-year self-window


def test_run_thin_contract_named_commodity_is_all_years_backfill(monkeypatch):
    _RecordingJob.constructed = []
    _stub_config(monkeypatch)
    # No _discover_commodities call for a named commodity (assert by making list_s3_keys explode).
    monkeypatch.setattr(base_jobs, "list_s3_keys",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no discovery for a named commodity")))
    _RecordingJob.run_thin_contract(["--commodity", "arabica_coffee", "--bucket", "B", "--aws_region", "R"])
    assert _RecordingJob.constructed == [("arabica_coffee", "B", "R", False, None)]


def test_run_thin_contract_aggregates_failures_into_nonzero_exit(monkeypatch):
    _stub_config(monkeypatch)

    class _BoomJob(_RecordingJob):
        def run(self):
            raise RuntimeError("boom")

    monkeypatch.setattr(base_jobs, "list_s3_keys", lambda *a, **k: [
        "bronze/weather/source=chirps/commodity=arabica_coffee/country=x/region=y/year=2026/month=07/part-000.parquet",
    ])
    with pytest.raises(SystemExit):
        _BoomJob.run_thin_contract(["--commodity", "all", "--bucket", "B", "--aws_region", "R"])


# ---------------------------------------------------------------------------
# year_window bounds the base run()'s bronze read to that year
# ---------------------------------------------------------------------------
def test_base_run_filters_bronze_to_year_window(monkeypatch):
    job = ChirpsBronzeToSilver(commodity="arabica_coffee", bucket="B", aws_region="R",
                               force_overwrite=False, year_window=2026)
    listed = {
        "bronze/weather/source=chirps/commodity=arabica_coffee/country=x/region=y/year=2025/month=12/part-000.parquet": 1,
        "bronze/weather/source=chirps/commodity=arabica_coffee/country=x/region=y/year=2026/month=07/part-000.parquet": 2,
    }
    monkeypatch.setattr(base_jobs, "list_s3_keys_with_mtime", lambda *a, **k: dict(listed))
    read_keys: list[str] = []
    monkeypatch.setattr(job, "_read_one", lambda key: (read_keys.append(key) or (None, key)))
    # transform/get_partitions never reached (all reads return None -> RuntimeError before them).
    with pytest.raises(RuntimeError, match="failed to read"):
        job.run()
    assert read_keys == [k for k in listed if "year=2026" in k]  # only the current-year bronze read
