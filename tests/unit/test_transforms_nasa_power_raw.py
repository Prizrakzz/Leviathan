"""Unit tests for leviathan.transforms.raw_to_bronze.nasa_power."""
from __future__ import annotations

import pytest
from leviathan.transforms.raw_to_bronze.nasa_power import (
    nasa_power_payload_to_daily_dataframe,
    parse_nasa_power_date,
)

EXPECTED_COLS = {
    "date", "year", "month", "day",
    "source", "commodity", "country", "region",
    "ingest_date", "source_file_name",
    "t2m", "t2m_max", "t2m_min",
    "prectotcorr", "rh2m", "ws2m", "allsky_sfc_sw_dwn",
}


class TestParsNasaPowerDate:
    def test_yyyymmdd_to_iso(self):
        assert parse_nasa_power_date("20200101") == "2020-01-01"

    def test_end_of_month(self):
        assert parse_nasa_power_date("20201231") == "2020-12-31"


class TestNasaPowerPayloadToDailyDataframe:
    def test_shape(self, nasa_power_payload):
        df = nasa_power_payload_to_daily_dataframe(
            payload=nasa_power_payload,
            source_file_name="test.json",
            commodity="cocoa",
            country="ghana",
            region="gh_main",
            ingest_date="2024-01-01",
        )
        # 3 dates in the fixture
        assert len(df) == 3

    def test_columns(self, nasa_power_payload):
        df = nasa_power_payload_to_daily_dataframe(
            payload=nasa_power_payload,
            source_file_name="test.json",
            commodity="cocoa",
            country="ghana",
            region="gh_main",
            ingest_date="2024-01-01",
        )
        assert EXPECTED_COLS.issubset(set(df.columns))

    def test_date_values_are_iso_strings(self, nasa_power_payload):
        df = nasa_power_payload_to_daily_dataframe(
            payload=nasa_power_payload,
            source_file_name="test.json",
            commodity="cocoa",
            country="ghana",
            region="gh_main",
            ingest_date="2024-01-01",
        )
        # Dates should be ISO strings like "2020-01-01"
        for val in df["date"]:
            assert isinstance(val, str)
            assert len(val) == 10
            assert val[4] == "-" and val[7] == "-"

    def test_metadata_cols_are_stamped(self, nasa_power_payload):
        df = nasa_power_payload_to_daily_dataframe(
            payload=nasa_power_payload,
            source_file_name="myfile.json",
            commodity="cocoa",
            country="ghana",
            region="gh_main",
            ingest_date="2024-06-15",
        )
        assert (df["commodity"] == "cocoa").all()
        assert (df["country"] == "ghana").all()
        assert (df["region"] == "gh_main").all()
        assert (df["ingest_date"] == "2024-06-15").all()
        assert (df["source_file_name"] == "myfile.json").all()

    def test_missing_properties_parameter_raises(self):
        bad_payload = {"type": "Feature", "properties": {}}
        with pytest.raises(ValueError):
            nasa_power_payload_to_daily_dataframe(
                payload=bad_payload,
                source_file_name="bad.json",
                commodity="cocoa",
                country="ghana",
                region="gh_main",
                ingest_date="2024-01-01",
            )
