"""A-Wave-3 thin-contract retrofit of the weather_daily FETCH/BRONZE Batch scripts.

The weather_daily descriptor invokes these with bare (or nearly bare) commands, so every argument must
default: ``--commodity all`` (iterate discovered commodities), ``--year``/``--start-year``/``--end-year``
self-window to the CURRENT calendar year, and ``--bucket``/``--aws_region`` fall back to the env. These
tests exercise the discovery + arg-resolution seams directly with stubbed S3/env (no network). The
named-commodity / explicit-year backfill invocation must keep working unchanged.
"""
from __future__ import annotations

import datetime
import sys

import pytest

import jobs.batch.chirps_to_bronze_task as chirps
import jobs.batch.cpc_raw_to_bronze_task as cpc_r2b
import jobs.batch.cpc_soil_to_raw_task as cpc_raw
import jobs.ingest.fetch_nasa_power as fnp

_CUR = datetime.date.today().year


# ---------------------------------------------------------------------------
# commodity discovery (shared 'all' sentinel over configs/geographies/*_regions.yaml)
# ---------------------------------------------------------------------------
_GEO_KEYS = [
    "configs/geographies/corn_cbot_regions.yaml",
    "configs/geographies/arabica_coffee_regions.yaml",
]


@pytest.mark.parametrize("mod", [fnp, chirps, cpc_r2b])
def test_discover_commodities_from_geography_configs(monkeypatch, mod):
    fn = getattr(mod, "discover_commodities", None) or getattr(mod, "_discover_commodities")
    monkeypatch.setattr(mod, "list_s3_keys", lambda *a, **k: list(_GEO_KEYS))
    assert fn("test-bucket", "us-east-1") == ["arabica_coffee", "corn_cbot"]


# ---------------------------------------------------------------------------
# fetch_nasa_power: current-year window default + upload-on default + 'all' loop
# ---------------------------------------------------------------------------
def _stub_fnp_env(monkeypatch):
    monkeypatch.setattr(fnp, "load_env", lambda: None)
    monkeypatch.setattr(fnp, "get_required_env",
                        lambda k: {"LEVIATHAN_BUCKET": "B", "AWS_REGION": "R"}[k])
    monkeypatch.setattr(fnp, "load_yaml", lambda *a, **k: {})


def test_fetch_nasa_power_thin_contract_defaults_current_year_upload_and_all(monkeypatch):
    _stub_fnp_env(monkeypatch)
    monkeypatch.setattr(fnp, "discover_commodities", lambda *a, **k: ["arabica_coffee", "corn_cbot"])
    calls = []
    monkeypatch.setattr(fnp, "_process_commodity",
                        lambda args, commodity, bucket, aws_region, source_config:
                        calls.append((commodity, args.start_year, args.end_year, args.upload, bucket)) or 0)
    monkeypatch.setattr(sys, "argv", ["fetch_nasa_power.py", "--commodity", "all", "--skip-existing-s3"])
    fnp.main()
    assert [c[0] for c in calls] == ["arabica_coffee", "corn_cbot"]
    for _c, sy, ey, upload, bucket in calls:
        assert sy == _CUR and ey == _CUR      # self-windowed to the current calendar year
        assert upload is True                 # --upload defaults ON for the cloud contract
        assert bucket == "B"


def test_fetch_nasa_power_named_commodity_and_explicit_years_backfill_unchanged(monkeypatch):
    _stub_fnp_env(monkeypatch)
    calls = []
    monkeypatch.setattr(fnp, "_process_commodity",
                        lambda args, commodity, bucket, aws_region, source_config:
                        calls.append((commodity, args.start_year, args.end_year, args.upload)) or 0)
    monkeypatch.setattr(sys, "argv", [
        "fetch_nasa_power.py", "--commodity", "arabica_coffee",
        "--start-year", "1981", "--end-year", "2020", "--no-upload",
    ])
    fnp.main()
    assert calls == [("arabica_coffee", 1981, 2020, False)]


def test_fetch_nasa_power_end_year_beyond_current_still_refused(monkeypatch):
    _stub_fnp_env(monkeypatch)
    monkeypatch.setattr(sys, "argv", [
        "fetch_nasa_power.py", "--commodity", "arabica_coffee",
        "--start-year", str(_CUR), "--end-year", str(_CUR + 1),
    ])
    with pytest.raises(SystemExit, match="exceeds MAX_INGEST_YEAR"):
        fnp.main()


# ---------------------------------------------------------------------------
# chirps_to_bronze: month self-window (future skip / past-year all / current-year sentinel)
# ---------------------------------------------------------------------------
class _FakeS3:
    def __init__(self, existing_keys):
        self.existing = set(existing_keys)

    def head_object(self, Bucket, Key):  # noqa: N803 -- boto3 kwarg names
        if Key in self.existing:
            return {}
        raise RuntimeError("404")


_LOCS = [{"country": "brazil", "region": "br_x", "latitude": 0.0, "longitude": 0.0}]


def test_chirps_months_future_year_is_empty():
    s3 = _FakeS3([])
    assert chirps._months_to_process(s3, "B", "arabica_coffee", _LOCS, _CUR + 1, False,
                                     datetime.date(_CUR, 7, 17)) == []


def test_chirps_months_past_year_is_all_twelve_backfill():
    """A prior year (the preserved backfill path) processes every month; write-time skip-existing
    still dedups, so behaviour is unchanged from before the retrofit."""
    s3 = _FakeS3([])
    assert chirps._months_to_process(s3, "B", "arabica_coffee", _LOCS, 2011, False,
                                     datetime.date(_CUR, 7, 17)) == list(range(1, 13))


def test_chirps_months_current_year_downloads_current_plus_missing_only():
    today = datetime.date(2026, 7, 17)
    # Jan..May present (complete past months), Jun MISSING (gap), Jul = current (always).
    present = [
        chirps.bronze_weather_key("chirps", "arabica_coffee", "brazil", "br_x", 2026, m, "part-000.parquet")
        for m in (1, 2, 3, 4, 5)
    ]
    s3 = _FakeS3(present)
    months = chirps._months_to_process(s3, "B", "arabica_coffee", _LOCS, 2026, False, today)
    assert months == [6, 7]  # self-heal the Jun gap + always refresh the current (Jul) month


def test_chirps_months_current_year_force_overwrite_redownloads_all_elapsed():
    today = datetime.date(2026, 7, 17)
    s3 = _FakeS3([])
    months = chirps._months_to_process(s3, "B", "arabica_coffee", _LOCS, 2026, True, today)
    assert months == [1, 2, 3, 4, 5, 6, 7]


def test_chirps_main_thin_contract_resolves_all_and_current_year(monkeypatch):
    monkeypatch.setattr(chirps, "load_env", lambda: None)
    monkeypatch.setattr(chirps, "get_required_env",
                        lambda k: {"LEVIATHAN_BUCKET": "B", "AWS_REGION": "R"}[k])
    monkeypatch.setattr(chirps, "_discover_commodities", lambda *a, **k: ["arabica_coffee", "corn_cbot"])
    seen = []
    monkeypatch.setattr(chirps, "_process_commodity",
                        lambda bucket, aws_region, commodity, year, ingest_date, force, today:
                        seen.append((commodity, year, bucket)))
    monkeypatch.setattr(sys, "argv", ["chirps_to_bronze_task.py"])
    chirps.main()
    assert [s[0] for s in seen] == ["arabica_coffee", "corn_cbot"]
    assert all(year == _CUR and bucket == "B" for _c, year, bucket in seen)


# ---------------------------------------------------------------------------
# cpc_soil_to_raw + cpc_raw_to_bronze: current-year default + env fallback
# ---------------------------------------------------------------------------
def test_cpc_soil_to_raw_defaults_current_year_and_env(monkeypatch):
    monkeypatch.setattr(cpc_raw, "load_env", lambda: None)
    monkeypatch.setattr(cpc_raw, "get_required_env",
                        lambda k: {"LEVIATHAN_BUCKET": "B", "AWS_REGION": "R"}[k])
    seen = {}
    monkeypatch.setattr(cpc_raw, "_process_year_via_daily_files",
                        lambda **kw: seen.update(kw) or (0, 0))
    monkeypatch.setattr(cpc_raw, "_process_year_via_tarball",
                        lambda **kw: (_ for _ in ()).throw(AssertionError("current year must use daily-files")))
    monkeypatch.setattr(sys, "argv", ["cpc_soil_to_raw_task.py"])
    cpc_raw.main()
    assert seen["year"] == _CUR and seen["bucket"] == "B" and seen["aws_region"] == "R"


def test_cpc_soil_to_raw_explicit_past_year_uses_tarball_backfill(monkeypatch):
    monkeypatch.setattr(cpc_raw, "load_env", lambda: None)
    monkeypatch.setattr(cpc_raw, "get_required_env",
                        lambda k: {"LEVIATHAN_BUCKET": "B", "AWS_REGION": "R"}[k])
    seen = {}
    monkeypatch.setattr(cpc_raw, "_process_year_via_tarball", lambda **kw: seen.update(kw) or (0, 0))
    monkeypatch.setattr(cpc_raw, "_process_year_via_daily_files",
                        lambda **kw: (_ for _ in ()).throw(AssertionError("past year must use tarball")))
    monkeypatch.setattr(sys, "argv", ["cpc_soil_to_raw_task.py", "--year", "2011"])
    cpc_raw.main()
    assert seen["year"] == 2011


def test_cpc_raw_to_bronze_defaults_current_year_all_commodities(monkeypatch):
    monkeypatch.setattr(cpc_r2b, "load_env", lambda: None)
    monkeypatch.setattr(cpc_r2b, "get_required_env",
                        lambda k: {"LEVIATHAN_BUCKET": "B", "AWS_REGION": "R"}[k])
    monkeypatch.setattr(cpc_r2b, "get_thread_local_s3_client", lambda *a, **k: object())
    monkeypatch.setattr(cpc_r2b, "_discover_commodities", lambda *a, **k: ["arabica_coffee", "corn_cbot"])
    monkeypatch.setattr(cpc_r2b, "load_commodity_regions", lambda *a, **k: _LOCS)
    seen = {}
    monkeypatch.setattr(cpc_r2b, "_process_year", lambda **kw: seen.update(kw))
    monkeypatch.setattr(sys, "argv", ["cpc_raw_to_bronze_task.py"])
    cpc_r2b.main()
    assert seen["year"] == _CUR and seen["bucket"] == "B"
    assert set(seen["all_commodity_locations"]) == {"arabica_coffee", "corn_cbot"}
