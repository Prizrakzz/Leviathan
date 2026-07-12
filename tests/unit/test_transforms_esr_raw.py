"""Unit tests for the ESR raw → bronze transform.

Tests are pure Python — no S3/AWS mocking needed since transform_esr_json_to_bronze
has no side effects.
"""
from __future__ import annotations

import json

import pandas as pd
import pytest
from leviathan.transforms.raw_to_bronze.usda_esr import transform_esr_json_to_bronze

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

COMMODITY_CODE = 401
MARKET_YEAR    = 2025
AS_OF_DATE     = "20251009"
INGEST_DATE    = "2025-10-09"

# One record with `changes` present and one without.
_VALID_RECORDS = [
    {
        "commodityCode": 401,
        "countryCode": 351,
        "marketYear": 2025,
        "weekEndingDate": "2025-10-02",
        "netSales": 125000.5,
        "outstandingSales": 3200000.0,
        "weeklyExports": 85000.25,
        "cumulativeExports": 250000.0,
        "grossNewSales": 140000.5,
        "cancelations": 15000.0,
        "changes": 500.0,
        "unitId": 1,
    },
    {
        "commodityCode": 401,
        "countryCode": 218,
        "marketYear": 2025,
        "weekEndingDate": "2025-10-02",
        "netSales": 55000.0,
        "outstandingSales": 800000.0,
        "weeklyExports": 30000.0,
        "cumulativeExports": 90000.0,
        "grossNewSales": 55000.0,
        "cancelations": 0.0,
        # `changes` intentionally absent
        "unitId": 1,
    },
]


@pytest.fixture()
def valid_raw_bytes() -> bytes:
    return json.dumps(_VALID_RECORDS).encode()


@pytest.fixture()
def sample_fixture_bytes(tmp_path) -> bytes:
    """Load the canonical test fixture file."""
    import pathlib
    fixture = pathlib.Path(__file__).parents[1] / "fixtures" / "esr_sample.json"
    return fixture.read_bytes()


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

class TestHappyPath:
    def test_returns_dataframe(self, valid_raw_bytes: bytes) -> None:
        df = transform_esr_json_to_bronze(
            valid_raw_bytes, COMMODITY_CODE, MARKET_YEAR, AS_OF_DATE, INGEST_DATE
        )
        assert isinstance(df, pd.DataFrame)

    def test_row_count_matches_input(self, valid_raw_bytes: bytes) -> None:
        df = transform_esr_json_to_bronze(
            valid_raw_bytes, COMMODITY_CODE, MARKET_YEAR, AS_OF_DATE, INGEST_DATE
        )
        assert len(df) == len(_VALID_RECORDS)

    def test_columns_snake_case(self, valid_raw_bytes: bytes) -> None:
        df = transform_esr_json_to_bronze(
            valid_raw_bytes, COMMODITY_CODE, MARKET_YEAR, AS_OF_DATE, INGEST_DATE
        )
        expected_cols = {
            "commodity_code", "country_code", "market_year", "week_ending_date",
            "net_sales", "outstanding_sales", "weekly_exports", "cumulative_exports",
            "gross_new_sales", "cancelations", "changes", "unit_id",
            "as_of_date", "ingest_date", "source",
        }
        assert expected_cols.issubset(set(df.columns))

    def test_metadata_columns(self, valid_raw_bytes: bytes) -> None:
        df = transform_esr_json_to_bronze(
            valid_raw_bytes, COMMODITY_CODE, MARKET_YEAR, AS_OF_DATE, INGEST_DATE
        )
        assert (df["as_of_date"]   == AS_OF_DATE).all()
        assert (df["ingest_date"]  == INGEST_DATE).all()
        assert (df["source"]       == "usda_esr").all()

    def test_float_columns_are_float32(self, valid_raw_bytes: bytes) -> None:
        df = transform_esr_json_to_bronze(
            valid_raw_bytes, COMMODITY_CODE, MARKET_YEAR, AS_OF_DATE, INGEST_DATE
        )
        for col in ("net_sales", "outstanding_sales", "weekly_exports",
                    "cumulative_exports", "gross_new_sales", "cancelations", "changes"):
            assert df[col].dtype == "float32", f"{col} should be float32"

    def test_int_columns_are_Int16(self, valid_raw_bytes: bytes) -> None:
        df = transform_esr_json_to_bronze(
            valid_raw_bytes, COMMODITY_CODE, MARKET_YEAR, AS_OF_DATE, INGEST_DATE
        )
        for col in ("commodity_code", "country_code", "market_year", "unit_id"):
            assert str(df[col].dtype) == "Int16", f"{col} should be Int16"

    def test_week_ending_date_parsed(self, valid_raw_bytes: bytes) -> None:
        import datetime
        df = transform_esr_json_to_bronze(
            valid_raw_bytes, COMMODITY_CODE, MARKET_YEAR, AS_OF_DATE, INGEST_DATE
        )
        # Should be Python date objects (not strings).
        assert df["week_ending_date"].iloc[0] == datetime.date(2025, 10, 2)

    def test_fixture_file_loads_cleanly(self, sample_fixture_bytes: bytes) -> None:
        """The canonical test fixture should transform without error."""
        df = transform_esr_json_to_bronze(
            sample_fixture_bytes, COMMODITY_CODE, MARKET_YEAR, AS_OF_DATE, INGEST_DATE
        )
        assert len(df) == 5  # 5 rows in esr_sample.json


# ---------------------------------------------------------------------------
# Missing 'changes' field -> stays NULL (SILVER-F030 / INV-4: never synthesize 0.0)
# ---------------------------------------------------------------------------

class TestMissingChangesFieldStaysNull:
    def test_changes_absent_in_one_record_stays_null(self, valid_raw_bytes: bytes) -> None:
        """Second record in _VALID_RECORDS has no 'changes' key -> that row's changes is NaN,
        not 0.0 (INV-4). The present row keeps its real value."""
        df = transform_esr_json_to_bronze(
            valid_raw_bytes, COMMODITY_CODE, MARKET_YEAR, AS_OF_DATE, INGEST_DATE
        )
        assert df["changes"].isna().sum() == 1
        assert float(df["changes"].dropna().iloc[0]) == 500.0

    def test_changes_absent_in_all_records_is_all_null(self) -> None:
        """When NO record carries 'changes', the column exists but is all-NULL -- NEVER 0.0.

        A synthesized 0.0 is indistinguishable from a real zero revision (INV-4)."""
        records = [
            {k: v for k, v in r.items() if k != "changes"}
            for r in _VALID_RECORDS
        ]
        raw = json.dumps(records).encode()
        df = transform_esr_json_to_bronze(
            raw, COMMODITY_CODE, MARKET_YEAR, AS_OF_DATE, INGEST_DATE
        )
        assert "changes" in df.columns
        assert df["changes"].isna().all()
        assert (df["changes"] == 0.0).sum() == 0

    def test_changes_null_in_fixture_stays_null(self, sample_fixture_bytes: bytes) -> None:
        """esr_sample.json: rows 0-1 have real changes, rows 2-3 omit it, row 4 is explicit null
        -> exactly 3 NaN 'changes' values survive (INV-4), never coerced to 0.0."""
        df = transform_esr_json_to_bronze(
            sample_fixture_bytes, COMMODITY_CODE, MARKET_YEAR, AS_OF_DATE, INGEST_DATE
        )
        assert df["changes"].isna().sum() == 3
        assert (df["changes"] == 0.0).sum() == 0

    def test_changes_column_is_still_float32(self, valid_raw_bytes: bytes) -> None:
        """The nullable 'changes' column keeps the bronze float32 dtype (NaN is a valid float32)."""
        df = transform_esr_json_to_bronze(
            valid_raw_bytes, COMMODITY_CODE, MARKET_YEAR, AS_OF_DATE, INGEST_DATE
        )
        assert df["changes"].dtype == "float32"


# ---------------------------------------------------------------------------
# Unknown API fields -> schema-drift WARN, never a silent drop (SILVER-F030 / INV-1)
# ---------------------------------------------------------------------------

class TestUnknownApiFieldDriftAlert:
    def test_unknown_field_warns(self, caplog) -> None:
        """A camelCase field _FIELD_MAP does not know is surfaced as a WARN (schema drift),
        not silently dropped -- Raw retains it, but the operator is alerted."""
        import logging
        records = [
            {**_VALID_RECORDS[0], "newFangledMetric": 42.0, "anotherNewField": "x"},
        ]
        raw = json.dumps(records).encode()
        with caplog.at_level(logging.WARNING):
            df = transform_esr_json_to_bronze(
                raw, COMMODITY_CODE, MARKET_YEAR, AS_OF_DATE, INGEST_DATE
            )
        # the typed bronze schema stays clean (unknowns not promoted)...
        assert "newFangledMetric" not in df.columns
        assert "anotherNewField" not in df.columns
        # ...but a schema-drift alert names both unknown fields.
        drift = "\n".join(r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING)
        assert "schema drift" in drift.lower()
        assert "anotherNewField" in drift and "newFangledMetric" in drift

    def test_no_warn_when_all_fields_known(self, valid_raw_bytes: bytes, caplog) -> None:
        import logging
        with caplog.at_level(logging.WARNING):
            transform_esr_json_to_bronze(
                valid_raw_bytes, COMMODITY_CODE, MARKET_YEAR, AS_OF_DATE, INGEST_DATE
            )
        drift = [r for r in caplog.records
                 if r.levelno >= logging.WARNING and "schema drift" in r.getMessage().lower()]
        assert drift == []


# ---------------------------------------------------------------------------
# Empty array → ValueError
# ---------------------------------------------------------------------------

class TestEmptyArray:
    def test_empty_list_raises_value_error(self) -> None:
        raw = b"[]"
        with pytest.raises(ValueError, match="empty array"):
            transform_esr_json_to_bronze(
                raw, COMMODITY_CODE, MARKET_YEAR, AS_OF_DATE, INGEST_DATE
            )


# ---------------------------------------------------------------------------
# Bad JSON → JSONDecodeError
# ---------------------------------------------------------------------------

class TestBadJson:
    def test_invalid_json_raises_decode_error(self) -> None:
        raw = b"<html>Not found</html>"
        with pytest.raises(json.JSONDecodeError):
            transform_esr_json_to_bronze(
                raw, COMMODITY_CODE, MARKET_YEAR, AS_OF_DATE, INGEST_DATE
            )

    def test_truncated_json_raises_decode_error(self) -> None:
        raw = b'[{"commodityCode": 401, "market'  # truncated
        with pytest.raises(json.JSONDecodeError):
            transform_esr_json_to_bronze(
                raw, COMMODITY_CODE, MARKET_YEAR, AS_OF_DATE, INGEST_DATE
            )
