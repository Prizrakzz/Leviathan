"""Unit tests for leviathan.common.constants."""
from __future__ import annotations

from leviathan.common.constants import (
    ALL_COMMODITIES,
    MIN_RAW_FILE_SIZES,
    SILVER_WEATHER_ID_COLS,
)


class TestAllCommodities:
    def test_len_is_31(self):
        assert len(ALL_COMMODITIES) == 31

    def test_no_duplicates(self):
        assert len(set(ALL_COMMODITIES)) == len(ALL_COMMODITIES)

    def test_all_lowercase_snake_case(self):
        for commodity in ALL_COMMODITIES:
            assert commodity == commodity.lower(), f"Not lowercase: {commodity!r}"
            assert " " not in commodity, f"Contains space: {commodity!r}"

    def test_contains_known_commodities(self):
        assert "cocoa" in ALL_COMMODITIES
        assert "corn_cbot" in ALL_COMMODITIES
        assert "arabica_coffee" in ALL_COMMODITIES

    def test_is_tuple(self):
        assert isinstance(ALL_COMMODITIES, tuple)


class TestMinRawFileSizes:
    def test_nasa_power_present(self):
        assert "nasa_power" in MIN_RAW_FILE_SIZES

    def test_faostat_qcl_key_name(self):
        # Key is "faostat_qcl" not "faostat"
        assert "faostat_qcl" in MIN_RAW_FILE_SIZES
        assert "faostat" not in MIN_RAW_FILE_SIZES

    def test_all_values_positive(self):
        assert all(v > 0 for v in MIN_RAW_FILE_SIZES.values())

    def test_all_keys_are_strings(self):
        assert all(isinstance(k, str) for k in MIN_RAW_FILE_SIZES)

    def test_all_values_are_ints(self):
        assert all(isinstance(v, int) for v in MIN_RAW_FILE_SIZES.values())


class TestSilverWeatherIdCols:
    def test_is_list_of_strings(self):
        assert isinstance(SILVER_WEATHER_ID_COLS, list)
        assert all(isinstance(c, str) for c in SILVER_WEATHER_ID_COLS)

    def test_length_is_9(self):
        assert len(SILVER_WEATHER_ID_COLS) == 9

    def test_contains_required_identity_columns(self):
        for col in ("date", "commodity", "country", "region", "source", "ingest_date"):
            assert col in SILVER_WEATHER_ID_COLS, f"Missing: {col!r}"

    def test_date_temporal_cols_present(self):
        for col in ("year", "month", "day"):
            assert col in SILVER_WEATHER_ID_COLS, f"Missing temporal col: {col!r}"
