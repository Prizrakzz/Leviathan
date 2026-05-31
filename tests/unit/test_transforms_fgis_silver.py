"""Unit tests for the FGIS bronze → silver transform.

Tests are pure Python — no S3/AWS dependencies.
"""
from __future__ import annotations

import datetime

import pandas as pd
import pytest

from leviathan.transforms.bronze_to_silver.usda_fgis import (
    _CLASS_TO_SLUG,
    _SLUG_MY_START_MONTH,
    _my_start_date,
    _week_of_my,
    _week_end_date,
    OUTPUT_COLUMNS,
    transform_fgis_bronze_to_silver,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_bronze(rows: list[dict]) -> pd.DataFrame:
    """Build a minimal FGIS bronze DataFrame from a list of row dicts."""
    defaults = {
        "class": "YC",
        "date": datetime.date(2024, 9, 7),
        "mt": 1000.0,
        "destination": "CHINA",
        "marketing_year": 2024,
        "source": "usda_fgis_export_inspections",
    }
    return pd.DataFrame([{**defaults, **r} for r in rows])


def _minimal_bronze() -> pd.DataFrame:
    """Two corn shipments to CHINA in the first two weeks of MY2024."""
    return _make_bronze([
        {"class": "YC", "date": datetime.date(2024, 9, 3), "mt": 5000.0},
        {"class": "YC", "date": datetime.date(2024, 9, 10), "mt": 3000.0},
    ])


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

class TestConstants:
    def test_class_to_slug_has_five_entries(self) -> None:
        assert len(_CLASS_TO_SLUG) == 5

    def test_corn_mapping(self) -> None:
        assert _CLASS_TO_SLUG["YC"] == "corn_cbot"

    def test_soybeans_mapping(self) -> None:
        assert _CLASS_TO_SLUG["YSB"] == "soybeans_cbot"

    def test_hrw_mapping(self) -> None:
        assert _CLASS_TO_SLUG["HRW"] == "hard_red_winter_wheat_kcbt"

    def test_hrs_mapping(self) -> None:
        assert _CLASS_TO_SLUG["HRS"] == "hard_red_spring_wheat_mgex"

    def test_srw_mapping(self) -> None:
        assert _CLASS_TO_SLUG["SRW"] == "soft_red_winter_wheat_cbot"

    def test_corn_my_start_september(self) -> None:
        assert _SLUG_MY_START_MONTH["corn_cbot"] == 9

    def test_soy_my_start_september(self) -> None:
        assert _SLUG_MY_START_MONTH["soybeans_cbot"] == 9

    def test_wheat_my_start_june(self) -> None:
        for slug in (
            "hard_red_winter_wheat_kcbt",
            "hard_red_spring_wheat_mgex",
            "soft_red_winter_wheat_cbot",
        ):
            assert _SLUG_MY_START_MONTH[slug] == 6


# ---------------------------------------------------------------------------
# Week helpers
# ---------------------------------------------------------------------------

class TestWeekHelpers:
    def test_my_start_corn_sep1(self) -> None:
        assert _my_start_date("corn_cbot", 2024) == datetime.date(2024, 9, 1)

    def test_my_start_wheat_jun1(self) -> None:
        assert _my_start_date("hard_red_winter_wheat_kcbt", 2024) == datetime.date(2024, 6, 1)

    def test_week_1_on_my_start_day(self) -> None:
        my_start = datetime.date(2024, 9, 1)
        assert _week_of_my(datetime.date(2024, 9, 1), my_start) == 1

    def test_week_1_on_last_day_of_first_week(self) -> None:
        my_start = datetime.date(2024, 9, 1)
        assert _week_of_my(datetime.date(2024, 9, 7), my_start) == 1

    def test_week_2_starts_on_day_8(self) -> None:
        my_start = datetime.date(2024, 9, 1)
        assert _week_of_my(datetime.date(2024, 9, 8), my_start) == 2

    def test_week_straddling_dec_jan_boundary(self) -> None:
        """Corn MY2024 week 18 should span into January 2025."""
        my_start = datetime.date(2024, 9, 1)
        jan_date = datetime.date(2025, 1, 5)
        week = _week_of_my(jan_date, my_start)
        assert week == 18  # (2025-01-05 - 2024-09-01).days = 126 → 126//7+1 = 18+1=19?
        # (2025-01-05 - 2024-09-01) = 126 days, 126//7=18, 18+1=19
        # Let me recalculate: Sep has 30 days, Oct 31, Nov 30, Dec 31 = 122 days
        # 2024-09-01 + 122 = 2024-12-31. Jan 5 = day 127 from Sep 1 (0-indexed).
        # Actually: (2025-01-05 - 2024-09-01).days = ?
        # Sep: 29 remaining days (Sep 1 is day 0), Oct: 31, Nov: 30, Dec: 31 → 121 days to end of Dec
        # Jan 5 = 121 + 5 = 126 days from Sep 1
        # 126 // 7 + 1 = 18 + 1 = 19
        # Fix the assertion:
        assert week == 19

    def test_week_straddling_dec_jan_boundary_correct(self) -> None:
        """Explicit check: 2025-01-05 is day 126 from 2024-09-01 → week 19."""
        my_start = datetime.date(2024, 9, 1)
        date = datetime.date(2025, 1, 5)
        delta_days = (date - my_start).days
        assert delta_days == 126
        assert _week_of_my(date, my_start) == 19

    def test_week_end_date_week1(self) -> None:
        my_start = datetime.date(2024, 9, 1)
        assert _week_end_date(1, my_start) == datetime.date(2024, 9, 7)

    def test_week_end_date_week2(self) -> None:
        my_start = datetime.date(2024, 9, 1)
        assert _week_end_date(2, my_start) == datetime.date(2024, 9, 14)


# ---------------------------------------------------------------------------
# Transform — happy path
# ---------------------------------------------------------------------------

class TestTransformHappyPath:
    def test_returns_dataframe(self) -> None:
        result = transform_fgis_bronze_to_silver(_minimal_bronze())
        assert isinstance(result, pd.DataFrame)

    def test_output_columns_match_schema(self) -> None:
        result = transform_fgis_bronze_to_silver(_minimal_bronze())
        assert list(result.columns) == OUTPUT_COLUMNS

    def test_slug_mapped_correctly(self) -> None:
        result = transform_fgis_bronze_to_silver(_minimal_bronze())
        assert (result["leviathan_slug"] == "corn_cbot").all()

    def test_destination_normalised_uppercase(self) -> None:
        df = _make_bronze([{"destination": " china "}])
        result = transform_fgis_bronze_to_silver(df)
        assert (result["destination_country"] == "CHINA").all()

    def test_weekly_sum_aggregation(self) -> None:
        """Two same-week shipments to the same destination → summed."""
        df = _make_bronze([
            {"date": datetime.date(2024, 9, 3), "mt": 4000.0},
            {"date": datetime.date(2024, 9, 5), "mt": 6000.0},
        ])
        result = transform_fgis_bronze_to_silver(df)
        assert len(result) == 1
        assert result["exports_mt_weekly"].iloc[0] == pytest.approx(10000.0)

    def test_separate_weeks_produce_separate_rows(self) -> None:
        result = transform_fgis_bronze_to_silver(_minimal_bronze())
        assert len(result) == 2
        assert result["week_of_marketing_year"].tolist() == [1, 2]

    def test_ctd_week1(self) -> None:
        result = transform_fgis_bronze_to_silver(_minimal_bronze())
        assert result["exports_mt_ctd"].iloc[0] == pytest.approx(5000.0)

    def test_ctd_week2_accumulates(self) -> None:
        result = transform_fgis_bronze_to_silver(_minimal_bronze())
        assert result["exports_mt_ctd"].iloc[1] == pytest.approx(8000.0)

    def test_ctd_resets_across_marketing_years(self) -> None:
        """MY2024 and MY2025 CTD should each start from zero."""
        df = _make_bronze([
            {"date": datetime.date(2024, 9, 3), "mt": 5000.0, "marketing_year": 2024},
            {"date": datetime.date(2025, 9, 3), "mt": 3000.0, "marketing_year": 2025},
        ])
        result = transform_fgis_bronze_to_silver(df)
        by_my = result.set_index("marketing_year")["exports_mt_ctd"]
        assert by_my[2024] == pytest.approx(5000.0)
        assert by_my[2025] == pytest.approx(3000.0)

    def test_ctd_resets_across_destination_countries(self) -> None:
        """CTD for JAPAN should be independent of CTD for CHINA."""
        df = _make_bronze([
            {"date": datetime.date(2024, 9, 3), "mt": 5000.0, "destination": "CHINA"},
            {"date": datetime.date(2024, 9, 3), "mt": 2000.0, "destination": "JAPAN"},
        ])
        result = transform_fgis_bronze_to_silver(df)
        china = result[result["destination_country"] == "CHINA"]["exports_mt_ctd"].iloc[0]
        japan = result[result["destination_country"] == "JAPAN"]["exports_mt_ctd"].iloc[0]
        assert china == pytest.approx(5000.0)
        assert japan == pytest.approx(2000.0)

    def test_week_ending_date_deterministic(self) -> None:
        """week_ending_date is based on MY start, not on the shipment date."""
        df = _make_bronze([{"date": datetime.date(2024, 9, 3), "mt": 1000.0}])
        result = transform_fgis_bronze_to_silver(df)
        # Week 1 of corn MY2024 ends Sep 7
        assert result["week_ending_date"].iloc[0] == datetime.date(2024, 9, 7)

    def test_multiple_slugs_in_same_dataframe(self) -> None:
        """Corn and wheat rows coexist; each gets the correct slug and MY start."""
        df = _make_bronze([
            {"class": "YC",  "date": datetime.date(2024, 9, 3), "mt": 1000.0},
            {"class": "HRW", "date": datetime.date(2024, 6, 5), "mt": 2000.0},
        ])
        result = transform_fgis_bronze_to_silver(df)
        slugs = set(result["leviathan_slug"])
        assert "corn_cbot" in slugs
        assert "hard_red_winter_wheat_kcbt" in slugs

    def test_wheat_week1_starts_june(self) -> None:
        df = _make_bronze([
            {"class": "HRW", "date": datetime.date(2024, 6, 2), "mt": 1000.0},
        ])
        result = transform_fgis_bronze_to_silver(df)
        assert result["week_of_marketing_year"].iloc[0] == 1
        assert result["week_ending_date"].iloc[0] == datetime.date(2024, 6, 7)

    def test_source_column_preserved(self) -> None:
        result = transform_fgis_bronze_to_silver(_minimal_bronze())
        assert (result["source"] == "usda_fgis_export_inspections").all()


# ---------------------------------------------------------------------------
# Transform — unmapped grains
# ---------------------------------------------------------------------------

class TestUnmappedGrains:
    def test_sorghum_silently_excluded(self) -> None:
        df = _make_bronze([
            {"class": "YC",      "mt": 1000.0},
            {"class": "SORGHUM", "mt": 500.0},
        ])
        result = transform_fgis_bronze_to_silver(df)
        assert "corn_cbot" in result["leviathan_slug"].values
        assert len(result[result["leviathan_slug"] == "SORGHUM"]) == 0

    def test_barley_silently_excluded(self) -> None:
        df = _make_bronze([{"class": "BARLEY", "mt": 100.0}])
        result = transform_fgis_bronze_to_silver(df)
        assert result.empty

    def test_empty_result_has_correct_schema(self) -> None:
        df = _make_bronze([{"class": "BARLEY", "mt": 100.0}])
        result = transform_fgis_bronze_to_silver(df)
        assert list(result.columns) == OUTPUT_COLUMNS

    def test_class_matching_is_case_insensitive(self) -> None:
        """Bronze class values are normalised to uppercase before mapping."""
        df = _make_bronze([{"class": "yc", "mt": 500.0}])
        result = transform_fgis_bronze_to_silver(df)
        assert len(result) == 1
        assert result["leviathan_slug"].iloc[0] == "corn_cbot"


# ---------------------------------------------------------------------------
# Transform — validation
# ---------------------------------------------------------------------------

class TestValidation:
    def test_missing_class_column_raises(self) -> None:
        df = _minimal_bronze().drop(columns=["class"])
        with pytest.raises(ValueError, match="class"):
            transform_fgis_bronze_to_silver(df)

    def test_missing_mt_column_raises(self) -> None:
        df = _minimal_bronze().drop(columns=["mt"])
        with pytest.raises(ValueError, match="mt"):
            transform_fgis_bronze_to_silver(df)

    def test_missing_destination_column_raises(self) -> None:
        df = _minimal_bronze().drop(columns=["destination"])
        with pytest.raises(ValueError, match="destination"):
            transform_fgis_bronze_to_silver(df)

    def test_missing_marketing_year_column_raises(self) -> None:
        df = _minimal_bronze().drop(columns=["marketing_year"])
        with pytest.raises(ValueError, match="marketing_year"):
            transform_fgis_bronze_to_silver(df)

    def test_error_message_lists_missing_columns(self) -> None:
        df = _minimal_bronze().drop(columns=["class", "mt"])
        with pytest.raises(ValueError) as exc_info:
            transform_fgis_bronze_to_silver(df)
        msg = str(exc_info.value)
        assert "class" in msg
        assert "mt" in msg

    def test_null_dates_dropped_with_warning(self) -> None:
        df = _make_bronze([
            {"date": None, "mt": 999.0},
            {"date": datetime.date(2024, 9, 3), "mt": 1000.0},
        ])
        result = transform_fgis_bronze_to_silver(df)
        # Only the valid-date row survives
        assert len(result) == 1

    def test_empty_input_returns_empty_schema(self) -> None:
        df = _minimal_bronze().iloc[0:0]
        result = transform_fgis_bronze_to_silver(df)
        assert result.empty
        assert list(result.columns) == OUTPUT_COLUMNS
