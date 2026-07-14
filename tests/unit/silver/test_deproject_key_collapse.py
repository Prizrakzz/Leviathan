"""F047 key collapse in jobs/utils/deproject_glue_table.py (BF-W1 live find).

BatchCreatePartition validates value-count against the table's PartitionKeys, so the
weather-trio flip must shrink [commodity, country, region, year, month] -> [commodity, year]
BEFORE --register can succeed ("The number of partition keys do not match the number of
partition values", live-proven on silver_chirps). Types are preserved from the live keys;
tables whose TARGETS grain already matches (ESR/WASDE precedent) are returned None (no-op).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location(
    "deproject_glue_table", _REPO / "jobs" / "utils" / "deproject_glue_table.py")
dp = importlib.util.module_from_spec(_spec)
sys.modules["deproject_glue_table"] = dp
_spec.loader.exec_module(dp)  # type: ignore[union-attr]

_WEATHER_LIVE = [
    {"Name": "commodity", "Type": "string"}, {"Name": "country", "Type": "string"},
    {"Name": "region", "Type": "string"}, {"Name": "year", "Type": "int"},
    {"Name": "month", "Type": "int"},
]


def test_weather_trio_collapses_to_commodity_year_preserving_types():
    for table in ("silver_chirps", "silver_nasa_power", "silver_cpc_soil"):
        out = dp.collapsed_partition_keys(table, _WEATHER_LIVE)
        assert out == [{"Name": "commodity", "Type": "string"},
                       {"Name": "year", "Type": "int"}], (table, out)


def test_matching_grain_is_a_noop():
    esr_live = [{"Name": "commodity_code", "Type": "string"},
                {"Name": "market_year", "Type": "string"},
                {"Name": "as_of_date", "Type": "string"}]
    assert dp.collapsed_partition_keys("silver_esr", esr_live) is None


def test_unknown_table_is_a_noop():
    assert dp.collapsed_partition_keys("silver_not_a_target", _WEATHER_LIVE) is None
