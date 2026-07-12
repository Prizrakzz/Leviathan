"""SILVER-F045: CHIRPS silver value rebuild (shadow-proof; execution is BF-W1).

Covers the R2 shadow deliverables:
  * OP-2 confirm: the gold transform yields ZERO drought_z rows purely from all-NaN CHIRPS data (so the
    drought_z defer is data-gated, and a real rebuild is what un-defers it).
  * the value census (SILVER-V001) HARD-FAILS the current stale all-NaN silver and PASSES a rebuild that
    carries real precipitation -- the exact gate that distinguishes "present" from "usable".
  * the SILVER-V002 freshness contract (base_jobs.select_partitions_to_write) refreshes a silver
    partition whose bronze is newer (the stale-silver root cause) and no-ops when silver is fresh.
"""
from __future__ import annotations

import io

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from leviathan.silver import value_census as vc
from leviathan.storage.base_jobs import select_partitions_to_write
from leviathan.transforms.bronze_to_silver._weather_schema import CHIRPS_LONG_SCHEMA
from leviathan.transforms.gold.weather_z import METRIC_DROUGHT_Z, compute_weather_z


# ---------------------------------------------------------------------------
# OP-2: drought_z is data-gated (zero rows from NaN chirps).
# ---------------------------------------------------------------------------
def _chirps_long(precip_values, years):
    rows = []
    for y in years:
        for d in range(1, len(precip_values) + 1):
            rows.append({"country": "brazil", "region": "r1", "year": y, "month": 1, "day": d,
                         "variable": "precipitation_mm", "value": precip_values[d - 1]})
    return pd.DataFrame(rows)


class TestOP2DroughtDataGated:
    def test_all_nan_chirps_yields_zero_drought_rows(self):
        nan_chirps = _chirps_long([float("nan")] * 5, years=range(1990, 2015))
        gold = compute_weather_z("corn_cbot", nasa_power=None, chirps=nan_chirps)
        drought = gold[gold["metric"] == METRIC_DROUGHT_Z] if not gold.empty else gold
        assert len(drought) == 0

    def test_real_chirps_yields_drought_rows(self):
        """With real precip across enough prior years, drought_z DOES fire -- proving the NaN value
        (not the config) is the blocker the rebuild removes."""
        rng = np.random.default_rng(0)
        rows = []
        for y in range(1990, 2015):
            for day in range(1, 29):
                rows.append({"country": "brazil", "region": "r1", "year": y, "month": 1, "day": day,
                             "variable": "precipitation_mm", "value": float(rng.uniform(0, 10))})
        real_chirps = pd.DataFrame(rows)
        gold = compute_weather_z("corn_cbot", nasa_power=None, chirps=real_chirps,
                                 window_years=10, min_years=5)
        drought = gold[gold["metric"] == METRIC_DROUGHT_Z]
        assert len(drought) > 0


# ---------------------------------------------------------------------------
# SILVER-V001 value census: stale all-NaN FAILS, rebuild PASSES.
# ---------------------------------------------------------------------------
def _parquet_footer(value_col_values):
    df = pd.DataFrame({
        "date": pd.to_datetime(["2018-01-01", "2018-01-02", "2018-01-03"]).date,
        "year": [2018, 2018, 2018], "month": [1, 1, 1], "day": [1, 2, 3],
        "country": ["brazil"] * 3, "region": ["r1"] * 3, "commodity": ["corn_cbot"] * 3,
        "source": ["chirps"] * 3, "ingest_date": ["2026-06-16"] * 3,
        "variable": ["precipitation_mm"] * 3, "value": value_col_values,
    })
    table = pa.Table.from_pandas(df, schema=CHIRPS_LONG_SCHEMA, preserve_index=False)
    buf = io.BytesIO()
    pq.write_table(table, buf)
    return pq.ParquetFile(io.BytesIO(buf.getvalue())).metadata


def _census(value_values):
    md = _parquet_footer(value_values)
    stat = vc.file_column_stat(md, "value")
    col = vc.census_column([stat], "value")
    return vc.evaluate_gate("silver_chirps", {"value": col}, ["value"], 0.5)


class TestValueCensusGate:
    def test_stale_all_nan_hard_fails(self):
        rows = _census([float("nan"), float("nan"), float("nan")])
        assert any(r.kind == vc.KIND_ALL_NAN for r in rows)

    def test_rebuild_with_real_values_passes(self):
        rows = _census([3.2, 0.0, 1.1])
        assert rows == []

    def test_partial_below_floor_fails(self):
        # 1 of 3 non-null -> 0.33 < 0.5 floor.
        rows = _census([3.2, float("nan"), float("nan")])
        assert any(r.kind == vc.KIND_NONNULL_BELOW_FLOOR for r in rows)


# ---------------------------------------------------------------------------
# SILVER-V002 freshness: refresh a partition whose bronze is newer.
# ---------------------------------------------------------------------------
class TestFreshnessContract:
    def _parts(self):
        return [({"country": "brazil", "region": "r1", "year": 2018, "month": 1}, pd.DataFrame({"x": [1]}))]

    def _key(self, kd):
        return f"silver/weather/source=chirps/commodity=corn_cbot/country={kd['country']}/year={kd['year']}/part.parquet"

    def test_stale_silver_is_refreshed(self):
        key = self._key(self._parts()[0][0])
        to_write, skipped, stale = select_partitions_to_write(
            self._parts(), {key: 100.0}, bronze_max_mtime=200.0, silver_key_fn=self._key)
        assert len(to_write) == 1 and stale == [key] and skipped == 0

    def test_fresh_silver_is_skipped(self):
        key = self._key(self._parts()[0][0])
        to_write, skipped, stale = select_partitions_to_write(
            self._parts(), {key: 300.0}, bronze_max_mtime=200.0, silver_key_fn=self._key)
        assert to_write == [] and skipped == 1 and stale == []

    def test_missing_silver_is_written(self):
        to_write, skipped, stale = select_partitions_to_write(
            self._parts(), {}, bronze_max_mtime=200.0, silver_key_fn=self._key)
        assert len(to_write) == 1 and skipped == 0 and stale == []
