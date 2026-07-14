"""BF-W1 ingest gates for jobs/batch/chirps_year_to_bronze_task.py.

Pins the two prevention mechanisms born from the post-rebuild census:
(1) the CHIRPS 50S-50N coverage filter -- out-of-band regions (Canadian canola,
    northern-EU wheat/rapeseed, 27 regions total live) never enter the location
    index, so no stage downstream can mint fabricated NaN rows for them;
(2) the all-null write-gate -- an all-null region-month writes NO partition
    (structural absence or unpublished source month), instead of the
    warn-and-write that carpeted the lake with the 2026-05-16 NaN vintage.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "chirps_year_to_bronze_task", _REPO / "jobs" / "batch" / "chirps_year_to_bronze_task.py")
task = importlib.util.module_from_spec(_spec)
sys.modules["chirps_year_to_bronze_task"] = task
_spec.loader.exec_module(task)  # type: ignore[union-attr]


def _region(country: str, region: str, lat: float, lon: float) -> dict:
    return {"country": country, "region": region, "latitude": lat, "longitude": lon}


class TestCoverageBandFilter:
    def test_out_of_band_regions_are_dropped(self):
        commodity_regions = {
            "canola_ice": [
                _region("canada", "ca_canola_alberta", 53.9, -116.6),      # > 50N: OUT
                _region("canada", "ca_canola_saskatchewan", 52.1, -106.3),  # > 50N: OUT
            ],
            "cocoa": [
                _region("ghana", "gh_main", 6.5, -1.6),                     # in band
            ],
        }
        flat, mapping = task._build_location_index(commodity_regions)
        names = {loc["region"] for loc in flat}
        assert names == {"gh_main"}
        assert "ca_canola_alberta" not in mapping
        assert "gh_main" in mapping

    def test_southern_limit_is_symmetric(self):
        commodity_regions = {
            "x": [_region("far_south", "fs_region", -55.0, 20.0),
                  _region("argentina", "ar_corn_buenos_aires", -36.0, -60.0)],
        }
        flat, _ = task._build_location_index(commodity_regions)
        assert {loc["region"] for loc in flat} == {"ar_corn_buenos_aires"}

    def test_boundary_region_is_kept(self):
        # exactly 50.0 is the edge of the product; keep it (the filter is strictly >)
        commodity_regions = {"x": [_region("france", "fr_edge", 50.0, 2.0)]}
        flat, _ = task._build_location_index(commodity_regions)
        assert len(flat) == 1


class TestAllNullWriteGate:
    def _run_month(self, monkeypatch, precip_value):
        """Drive _process_month with a stubbed fetch + in-memory S3; return written keys."""
        written: dict[str, bytes] = {}

        class FakeS3Exceptions:
            class ClientError(Exception):
                def __init__(self):
                    self.response = {"Error": {"Code": "404"}}

        class FakeS3:
            exceptions = FakeS3Exceptions

            def head_object(self, Bucket, Key):
                raise FakeS3Exceptions.ClientError()

            def put_object(self, Bucket, Key, Body, **kw):
                written[Key] = Body

        monkeypatch.setattr(task, "get_thread_local_s3_client", lambda region: FakeS3())
        monkeypatch.setattr(
            task, "fetch_chirps_daily_values",
            lambda y, m, d, locs: {loc["region"]: precip_value for loc in locs})

        flat, mapping = task._build_location_index(
            {"cocoa": [_region("ghana", "gh_main", 6.5, -1.6)]})
        n = task._process_month(
            aws_region="us-east-1", bucket="test-b", year=2017, month=1,
            flat_locations=flat, region_to_entries=mapping,
            ingest_date="2026-07-14", force_overwrite=True)
        return n, written

    def test_all_null_month_writes_no_partition(self, monkeypatch):
        n, written = self._run_month(monkeypatch, precip_value=None)
        assert n == 0
        assert not any(k.endswith(".parquet") for k in written)

    def test_real_month_still_writes(self, monkeypatch):
        n, written = self._run_month(monkeypatch, precip_value=3.2)
        assert n == 1
        assert any(k.endswith("part-000.parquet") for k in written)
        assert any(k.endswith("_meta.json") for k in written)
