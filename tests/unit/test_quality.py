"""Unit tests for leviathan.common.quality."""
from __future__ import annotations

import pandas as pd
import pytest
from leviathan.common.quality import (
    SILVER_REQUIRED_COLUMNS,
    check_data_types,
    check_deduplication,
    check_expected_entities,
    check_required_columns,
    check_required_nulls,
    check_value_ranges,
    run_silver_quality_checks,
)


@pytest.fixture()
def silver_df() -> pd.DataFrame:
    """Minimal valid silver DataFrame in long/tidy format."""
    return pd.DataFrame(
        {
            "date": ["2020-01-01", "2020-01-02"],
            "year": [2020, 2020],
            "month": [1, 1],
            "day": [1, 2],
            "country": ["ghana", "ghana"],
            "region": ["gh_main", "gh_main"],
            "commodity": ["cocoa", "cocoa"],
            "source": ["chirps", "chirps"],
            "ingest_date": ["2024-01-01", "2024-01-01"],
            "variable": ["precipitation_mm", "precipitation_mm"],
            "value": [5.2, 0.0],
        }
    )


# ---------------------------------------------------------------------------
# check_required_columns
# ---------------------------------------------------------------------------

class TestCheckRequiredColumns:
    def test_valid_df_returns_empty(self, silver_df):
        assert check_required_columns(silver_df) == []

    def test_missing_column_returned(self, silver_df):
        df = silver_df.drop(columns=["value"])
        missing = check_required_columns(df)
        assert "value" in missing

    def test_all_required_columns_listed(self, silver_df):
        # Verify the constant itself matches expectations
        for col in SILVER_REQUIRED_COLUMNS:
            assert col in silver_df.columns, f"fixture missing required column: {col}"


# ---------------------------------------------------------------------------
# check_required_nulls
# ---------------------------------------------------------------------------

class TestCheckRequiredNulls:
    def test_no_nulls_returns_empty(self, silver_df):
        assert check_required_nulls(silver_df) == {}

    def test_null_in_required_col_detected(self, silver_df):
        silver_df.loc[0, "value"] = None
        result = check_required_nulls(silver_df)
        assert result.get("value", 0) == 1

    def test_null_in_non_required_col_not_flagged(self, silver_df):
        silver_df["ingest_date"] = None
        # ingest_date is not in SILVER_REQUIRED_NON_NULL
        result = check_required_nulls(silver_df)
        assert "ingest_date" not in result


# ---------------------------------------------------------------------------
# check_data_types
# ---------------------------------------------------------------------------

class TestCheckDataTypes:
    def test_correct_types_returns_empty(self, silver_df):
        assert check_data_types(silver_df) == []

    def test_year_as_string_flagged(self, silver_df):
        silver_df["year"] = silver_df["year"].astype(str)
        mismatched = check_data_types(silver_df)
        assert "year" in mismatched

    def test_value_as_int_flagged(self, silver_df):
        silver_df["value"] = silver_df["value"].astype(int)
        mismatched = check_data_types(silver_df)
        assert "value" in mismatched


# ---------------------------------------------------------------------------
# check_deduplication
# ---------------------------------------------------------------------------

class TestCheckDeduplication:
    def test_unique_rows_returns_zero(self, silver_df):
        assert check_deduplication(silver_df) == 0

    def test_duplicate_natural_key_detected(self, silver_df):
        df_dup = pd.concat([silver_df, silver_df.iloc[[0]]], ignore_index=True)
        assert check_deduplication(df_dup) == 1

    def test_empty_df_returns_zero(self):
        assert check_deduplication(pd.DataFrame()) == 0


# ---------------------------------------------------------------------------
# check_value_ranges
# ---------------------------------------------------------------------------

class TestCheckValueRanges:
    def test_valid_values_returns_empty(self, silver_df):
        assert check_value_ranges(silver_df) == {}

    def test_negative_precipitation_flagged(self, silver_df):
        silver_df.loc[0, "value"] = -5.0
        violations = check_value_ranges(silver_df)
        assert "precipitation_mm" in violations
        assert violations["precipitation_mm"]["out_of_range_count"] == 1

    def test_excessive_temperature_flagged(self):
        df = pd.DataFrame(
            {
                "variable": ["temperature_2m_mean_c"],
                "value": [999.0],
            }
        )
        violations = check_value_ranges(df)
        assert "temperature_2m_mean_c" in violations

    def test_missing_variable_column_returns_empty(self):
        df = pd.DataFrame({"value": [5.0]})
        assert check_value_ranges(df) == {}


# ---------------------------------------------------------------------------
# check_expected_entities
# ---------------------------------------------------------------------------

class TestCheckExpectedEntities:
    def test_all_countries_present_returns_empty(self, silver_df):
        assert check_expected_entities(silver_df, ["ghana"]) == []

    def test_missing_country_detected(self, silver_df):
        missing = check_expected_entities(silver_df, ["ghana", "cote_divoire"])
        assert "cote_divoire" in missing

    def test_empty_expected_list_returns_empty(self, silver_df):
        assert check_expected_entities(silver_df, []) == []

    def test_missing_country_column_returns_empty(self):
        df = pd.DataFrame({"value": [1.0]})
        assert check_expected_entities(df, ["ghana"]) == []


# ---------------------------------------------------------------------------
# run_silver_quality_checks
# ---------------------------------------------------------------------------

class TestRunSilverQualityChecks:
    def test_valid_df_passes(self, silver_df):
        report = run_silver_quality_checks(silver_df, "cocoa", "chirps", ["ghana"])
        assert report["passed"] is True
        assert report["hard_failures"] == {}

    def test_report_contains_metadata(self, silver_df):
        report = run_silver_quality_checks(silver_df, "cocoa", "chirps")
        assert report["commodity"] == "cocoa"
        assert report["source"] == "chirps"
        assert report["row_count"] == len(silver_df)
        assert "checked_at" in report

    def test_missing_column_fails_hard(self, silver_df):
        df = silver_df.drop(columns=["value"])
        report = run_silver_quality_checks(df, "cocoa", "chirps")
        assert report["passed"] is False
        assert "missing_columns" in report["hard_failures"]

    def test_required_null_fails_hard(self, silver_df):
        silver_df.loc[0, "date"] = None
        report = run_silver_quality_checks(silver_df, "cocoa", "chirps")
        assert report["passed"] is False
        assert "required_nulls" in report["hard_failures"]

    def test_dtype_mismatch_fails_hard(self, silver_df):
        silver_df["year"] = silver_df["year"].astype(str)
        report = run_silver_quality_checks(silver_df, "cocoa", "chirps")
        assert report["passed"] is False
        assert "dtype_mismatch" in report["hard_failures"]

    def test_duplicate_key_fails_hard(self, silver_df):
        df_dup = pd.concat([silver_df, silver_df.iloc[[0]]], ignore_index=True)
        report = run_silver_quality_checks(df_dup, "cocoa", "chirps")
        assert report["passed"] is False
        assert "duplicate_natural_keys" in report["hard_failures"]

    def test_range_violation_is_soft_warning(self, silver_df):
        silver_df.loc[0, "value"] = -99.0  # out of range for precipitation_mm
        report = run_silver_quality_checks(silver_df, "cocoa", "chirps")
        # Soft warning — should still pass
        assert report["passed"] is True
        assert "range_violations" in report["warnings"]

    def test_missing_country_is_soft_warning(self, silver_df):
        report = run_silver_quality_checks(silver_df, "cocoa", "chirps", ["ghana", "cote_divoire"])
        assert report["passed"] is True
        assert "missing_countries" in report["warnings"]
        assert "cote_divoire" in report["warnings"]["missing_countries"]
