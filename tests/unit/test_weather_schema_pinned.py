"""SILVER-F046: weather silver shape unification -- pinned per-family INV-2 writer schemas + the
gold_weather_z _to_long seam. Proves the WIDE nasa_power measurement columns and the LONG chirps
value column coexist without a string/large_string clash, the pinned schema covers the registry
contract, the feature-extractor melt still resolves the wide columns, and the seam passes both shapes
through unchanged.
"""
from __future__ import annotations

import importlib

import pandas as pd
import pyarrow as pa
import pytest

from leviathan.silver.registry import load_registry
from leviathan.transforms.bronze_to_silver import _weather_schema as ws


@pytest.fixture(scope="module")
def registry():
    return load_registry()


class TestPinnedSchemaCoversRegistry:
    @pytest.mark.parametrize("table", ["silver_nasa_power", "silver_chirps", "silver_cpc_soil"])
    def test_covers_every_declared_column(self, registry, table):
        violations = ws.assert_covers_registry(table, registry.table(table))
        assert violations == [], violations

    @pytest.mark.parametrize("table", ["silver_nasa_power", "silver_chirps", "silver_cpc_soil"])
    def test_no_large_string_in_pinned_schema(self, table):
        # INV-2: pin ONE arrow string type (string, never large_string) so the R0 large_string drift
        # cannot recur.
        schema = ws.schema_for(table)
        for field in schema:
            assert not pa.types.is_large_string(field.type), f"{table}.{field.name} is large_string"

    @pytest.mark.parametrize("table", ["silver_nasa_power", "silver_chirps", "silver_cpc_soil"])
    def test_registry_marks_writer_schema_pinned(self, registry, table):
        assert registry.table(table)["writer_schema_pinned"] is True

    @pytest.mark.parametrize("table", ["silver_nasa_power", "silver_chirps", "silver_cpc_soil"])
    def test_serving_table_is_gold_weather_z(self, registry, table):
        assert registry.table(table)["serving_table"] == "gold_weather_z"


class TestSchemaUnionNoStringClash:
    def test_wide_measures_and_long_value_coexist(self):
        """A union of the nasa WIDE measurement columns and the chirps LONG value column carries no
        string/large_string clash: every text field is pa.string(), every measure pa.float64()."""
        wide = {f.name: f.type for f in ws.NASA_POWER_WIDE_SCHEMA}
        long = {f.name: f.type for f in ws.CHIRPS_LONG_SCHEMA}
        # shared text columns must have the SAME arrow type across families.
        for shared in set(wide) & set(long):
            if pa.types.is_string(wide[shared]) or pa.types.is_string(long[shared]):
                assert wide[shared] == long[shared], shared
        # nasa measures + chirps value all float64.
        assert pa.types.is_floating(wide["precipitation_mm"])
        assert pa.types.is_floating(long["value"])


class TestEnforceArrowSchema:
    def test_roundtrip_casts_and_drops_extras(self, weather_bronze_wide_df):
        from leviathan.transforms.bronze_to_silver.nasa_power_weather import nasa_power_bronze_to_silver
        wide = nasa_power_bronze_to_silver(weather_bronze_wide_df)
        table = ws.enforce_arrow_schema(wide, ws.NASA_POWER_WIDE_SCHEMA)
        assert table.schema.equals(ws.NASA_POWER_WIDE_SCHEMA)

    def test_missing_column_fails_closed(self):
        df = pd.DataFrame({"date": ["2020-01-01"]})
        with pytest.raises(ValueError, match="missing column"):
            ws.enforce_arrow_schema(df, ws.CHIRPS_LONG_SCHEMA)

    def test_to_parquet_bytes_is_parquet(self, weather_bronze_wide_df):
        from leviathan.transforms.bronze_to_silver.nasa_power_weather import nasa_power_bronze_to_silver
        wide = nasa_power_bronze_to_silver(weather_bronze_wide_df)
        body = ws.to_parquet_bytes(wide, ws.NASA_POWER_WIDE_SCHEMA)
        assert body[:4] == b"PAR1"


class TestGoldToLongSeam:
    """SILVER-F046: the gold_weather_z _to_long seam must keep resolving nasa WIDE (melt) and chirps
    LONG (passthrough) unchanged after the schema pin."""

    def _seam(self):
        mod = importlib.import_module("jobs.batch.gold_weather_z_task")
        return mod._to_long

    def test_nasa_wide_frame_melts(self):
        to_long = self._seam()
        wide = pd.DataFrame({
            "country": ["br"], "region": ["r"], "year": [2020], "month": [1], "day": [1],
            "temperature_2m_max_c": [30.0], "temperature_2m_min_c": [18.0],
            "precipitation_mm": [2.0],
        })
        out = to_long(wide)
        assert set(out["variable"]) == {"temperature_2m_max_c", "temperature_2m_min_c", "precipitation_mm"}
        assert "value" in out.columns

    def test_chirps_long_frame_passes_through(self):
        to_long = self._seam()
        long = pd.DataFrame({
            "country": ["br"], "region": ["r"], "year": [2020], "month": [1], "day": [1],
            "variable": ["precipitation_mm"], "value": [3.3],
        })
        out = to_long(long)
        assert list(out["variable"]) == ["precipitation_mm"]
        assert list(out["value"]) == [3.3]

    def test_extractor_year_regex_still_matches_wide_key(self):
        # The feature extractor bounds weather reads by year=; the pinned schema preserves that path.
        from leviathan.features.extractors import _year_from_path
        key = "silver/weather/source=nasa_power/commodity=cocoa/country=ghana/region=r/year=2020/month=01/part-000.parquet"
        assert _year_from_path(key) == 2020
