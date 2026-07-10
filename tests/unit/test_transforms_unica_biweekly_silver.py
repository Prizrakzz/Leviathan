"""Unit tests for the UNICA biweekly bronze-to-silver transforms.

All tests are pure in-memory — no S3 or AWS dependencies.
"""
from __future__ import annotations

import datetime
from typing import Any

import pandas as pd
import pytest
from leviathan.transforms.bronze_to_silver.unica_biweekly import (
    CORN_ETHANOL_COLUMNS,
    MONTHLY_ETHANOL_SALES_COLUMNS,
    RELEASE_SERIES_COLUMNS,
    SEASON_HISTORY_COLUMNS,
    _resolve_fortnight_date,
    _resolve_position_date,
    transform_corn_ethanol,
    transform_monthly_ethanol_sales,
    transform_release_series,
    transform_season_history,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fp_row(**kw) -> dict[str, Any]:
    """Minimal fortnight_production bronze row."""
    base: dict[str, Any] = {
        "harvest_year":    "2023_2024",
        "idm":             "100",
        "doc_type":        "biweekly_new",
        "position_date":   "15/04/2023",
        "fortnight_label": "15/04",
        "fortnight_seq":   1,
        "region":          "centro_sul",
        "variable":        "cane_crushed",
        "period":          "current",
        "value":           1000.0,
        "unit":            "t",
        "ingest_date":     "2023-04-16",
    }
    base.update(kw)
    return base


def _ss_row(**kw) -> dict[str, Any]:
    """Minimal summary_snapshot bronze row."""
    base: dict[str, Any] = {
        "harvest_year":   "2023_2024",
        "idm":            "100",
        "doc_type":       "biweekly_new",
        "position_date":  "15/04/2023",
        "period_type":    "accumulated",
        "region":         "centro_sul",
        "variable":       "cane_crushed",
        "current_value":  1000.0,
        "prior_value":    900.0,
        "var_pct":        11.1,
        "unit":           "t",
        "ingest_date":    "2023-04-16",
    }
    base.update(kw)
    return base


def _ce_row(**kw) -> dict[str, Any]:
    """Minimal corn_ethanol bronze row."""
    base: dict[str, Any] = {
        "harvest_year":          "2023_2024",
        "idm":                   "100",
        "doc_type":              "biweekly_new",
        "position_date":         "15/04/2023",
        "fortnight_label":       "15/04",
        "fortnight_seq":         1,
        "anhydrous_quinzenal_kl": 50.0,
        "hydrous_quinzenal_kl":   30.0,
        "total_quinzenal_kl":     80.0,
        "anhydrous_accum_kl":    50.0,
        "hydrous_accum_kl":      30.0,
        "total_accum_kl":        80.0,
        "ingest_date":           "2023-04-16",
    }
    base.update(kw)
    return base


def _me_row(**kw) -> dict[str, Any]:
    """Minimal monthly_ethanol_sales bronze row."""
    base: dict[str, Any] = {
        "harvest_year":       "2023_2024",
        "idm":                "100",
        "doc_type":           "biweekly_new",
        "position_date":      "15/04/2023",
        "month_label":        "April",
        "month_num":          4,
        "is_partial":         True,
        "total_current_m3":   1000.0,
        "total_prior_m3":     900.0,
        "external_current_m3": 400.0,
        "external_prior_m3":   360.0,
        "internal_current_m3": 600.0,
        "internal_prior_m3":   540.0,
        "ingest_date":        "2023-04-16",
    }
    base.update(kw)
    return base


# ---------------------------------------------------------------------------
# TestResolveFortnight
# ---------------------------------------------------------------------------

class TestResolveFortnight:
    def test_april_maps_to_year_start(self):
        d = _resolve_fortnight_date("15/04", "2023_2024")
        assert d == datetime.date(2023, 4, 15)

    def test_january_maps_to_year_end(self):
        d = _resolve_fortnight_date("31/01", "2023_2024")
        assert d == datetime.date(2024, 1, 31)

    def test_none_label_returns_none(self):
        assert _resolve_fortnight_date(None, "2023_2024") is None

    def test_invalid_harvest_year_returns_none(self):
        assert _resolve_fortnight_date("15/04", "invalid") is None

    def test_december_maps_to_year_start(self):
        d = _resolve_fortnight_date("31/12", "2023_2024")
        assert d == datetime.date(2023, 12, 31)

    def test_march_maps_to_year_end(self):
        d = _resolve_fortnight_date("31/03", "2023_2024")
        assert d == datetime.date(2024, 3, 31)


class TestResolvePositionDate:
    def test_valid_ddmmyyyy(self):
        d = _resolve_position_date("15/04/2023")
        assert d == datetime.date(2023, 4, 15)

    def test_none_returns_none(self):
        assert _resolve_position_date(None) is None

    def test_invalid_returns_none(self):
        assert _resolve_position_date("not-a-date") is None


# ---------------------------------------------------------------------------
# TestTransformSeasonHistory
# ---------------------------------------------------------------------------

class TestTransformSeasonHistory:

    def _build_df(self, rows) -> pd.DataFrame:
        return pd.DataFrame(rows)

    def test_dedup_keeps_latest_position_date(self):
        """When two bulletins report the same slot, latest position_date wins."""
        rows = [
            _fp_row(idm="100", position_date="15/04/2023", value=1000.0),
            _fp_row(idm="200", position_date="30/04/2023", value=2000.0),
        ]
        df = transform_season_history(self._build_df(rows))
        assert len(df) == 1
        assert df.iloc[0]["cane_crushed_t"] == 2000.0
        assert df.iloc[0]["source_idm"] == "200"

    def test_prior_rows_excluded(self):
        """Rows with period='prior' must not appear in the output."""
        rows = [
            _fp_row(period="current", value=1000.0),
            _fp_row(period="prior",   value=999.0),
        ]
        df = transform_season_history(self._build_df(rows))
        assert len(df) == 1
        assert df.iloc[0]["cane_crushed_t"] == 1000.0

    def test_pivot_column_names_with_units(self):
        """Output must have unit-suffixed column names."""
        rows = [
            _fp_row(variable="cane_crushed",      value=1.0, unit="t"),
            _fp_row(variable="sugar_produced",     value=2.0, unit="t",   fortnight_seq=1),
            _fp_row(variable="ethanol_total",      value=3.0, unit="m3",  fortnight_seq=1),
            _fp_row(variable="ethanol_anhydrous",  value=4.0, unit="m3",  fortnight_seq=1),
            _fp_row(variable="ethanol_hydrous",    value=5.0, unit="m3",  fortnight_seq=1),
        ]
        df = transform_season_history(self._build_df(rows))
        for col in ["cane_crushed_t", "sugar_produced_t", "ethanol_total_m3",
                    "ethanol_anhydrous_m3", "ethanol_hydrous_m3"]:
            assert col in df.columns, f"Expected column '{col}' not found"

    def test_fortnight_date_populated(self):
        df = transform_season_history(self._build_df([_fp_row()]))
        assert df.iloc[0]["fortnight_date"] == datetime.date(2023, 4, 15)

    def test_missing_variable_gives_nan(self):
        """A variable not present in the data should produce a NaN column."""
        rows = [_fp_row(variable="cane_crushed", value=100.0)]
        df = transform_season_history(self._build_df(rows))
        assert pd.isna(df.iloc[0]["sugar_produced_t"])

    def test_output_columns_match_schema(self):
        df = transform_season_history(self._build_df([_fp_row()]))
        assert list(df.columns) == SEASON_HISTORY_COLUMNS

    def test_sort_order(self):
        """Output is sorted by (harvest_year, region, fortnight_seq)."""
        rows = [
            _fp_row(harvest_year="2022_2023", fortnight_seq=2, region="centro_sul"),
            _fp_row(harvest_year="2022_2023", fortnight_seq=1, region="centro_sul"),
            _fp_row(harvest_year="2023_2024", fortnight_seq=1, region="centro_sul"),
        ]
        df = transform_season_history(self._build_df(rows))
        tuples = list(zip(df["harvest_year"], df["region"], df["fortnight_seq"]))
        assert tuples == sorted(tuples)


# ---------------------------------------------------------------------------
# TestTransformReleaseSeries
# ---------------------------------------------------------------------------

class TestTransformReleaseSeries:

    def _build_df(self, rows) -> pd.DataFrame:
        return pd.DataFrame(rows)

    def test_accumulated_filter(self):
        """Only 'accumulated' period_type rows are included."""
        rows = [
            _ss_row(period_type="accumulated"),
            _ss_row(period_type="fortnightly"),
        ]
        df = transform_release_series(self._build_df(rows))
        assert len(df) == 1

    def test_double_ingestion_dedup(self):
        """Duplicate (harvest_year, position_date, region, variable) kept once."""
        rows = [_ss_row(), _ss_row()]
        df = transform_release_series(self._build_df(rows))
        assert len(df) == 1

    def test_both_current_and_prior_in_output(self):
        df = transform_release_series(self._build_df([_ss_row()]))
        assert "cane_crushed_current_t" in df.columns
        assert "cane_crushed_prior_t" in df.columns

    def test_output_columns_match_schema(self):
        """All RELEASE_SERIES_COLUMNS must be present."""
        rows = [
            _ss_row(variable=v)
            for v in ["cane_crushed", "sugar_produced", "ethanol_total",
                      "ethanol_anhydrous", "ethanol_hydrous"]
        ]
        df = transform_release_series(self._build_df(rows))
        for col in RELEASE_SERIES_COLUMNS:
            assert col in df.columns, f"Missing column: {col}"

    def test_sort_order(self):
        rows = [
            _ss_row(position_date="30/04/2023"),
            _ss_row(position_date="15/04/2023"),
        ]
        df = transform_release_series(self._build_df(rows))
        dates = df["position_date"].tolist()
        assert dates == sorted(dates)

    def test_values_preserved(self):
        row = _ss_row(variable="cane_crushed", current_value=999.0, prior_value=888.0)
        df = transform_release_series(self._build_df([row]))
        assert df.iloc[0]["cane_crushed_current_t"] == 999.0
        assert df.iloc[0]["cane_crushed_prior_t"] == 888.0


# ---------------------------------------------------------------------------
# TestTransformCornEthanol
# ---------------------------------------------------------------------------

class TestTransformCornEthanol:

    def _build_df(self, rows) -> pd.DataFrame:
        return pd.DataFrame(rows)

    def test_dedup_keeps_latest_position_date(self):
        rows = [
            _ce_row(idm="100", position_date="15/04/2023", total_quinzenal_kl=80.0),
            _ce_row(idm="200", position_date="30/04/2023", total_quinzenal_kl=90.0),
        ]
        df = transform_corn_ethanol(self._build_df(rows))
        assert len(df) == 1
        assert df.iloc[0]["total_quinzenal_kl"] == 90.0

    def test_fortnight_date_populated(self):
        df = transform_corn_ethanol(self._build_df([_ce_row()]))
        assert df.iloc[0]["fortnight_date"] == datetime.date(2023, 4, 15)

    def test_all_six_value_cols_preserved(self):
        df = transform_corn_ethanol(self._build_df([_ce_row()]))
        for col in ["anhydrous_quinzenal_kl", "hydrous_quinzenal_kl", "total_quinzenal_kl",
                    "anhydrous_accum_kl", "hydrous_accum_kl", "total_accum_kl"]:
            assert col in df.columns

    def test_output_columns_match_schema(self):
        df = transform_corn_ethanol(self._build_df([_ce_row()]))
        assert list(df.columns) == CORN_ETHANOL_COLUMNS


# ---------------------------------------------------------------------------
# TestTransformMonthlyEthanol
# ---------------------------------------------------------------------------

class TestTransformMonthlyEthanol:

    def _build_df(self, rows) -> pd.DataFrame:
        return pd.DataFrame(rows)

    def test_is_partial_false_preferred(self):
        """A final reading (is_partial=False) beats an earlier partial one."""
        rows = [
            _me_row(idm="100", position_date="15/04/2023", is_partial=True,
                    total_current_m3=500.0),
            _me_row(idm="200", position_date="30/04/2023", is_partial=False,
                    total_current_m3=1000.0),
        ]
        df = transform_monthly_ethanol_sales(self._build_df(rows))
        assert len(df) == 1
        assert df.iloc[0]["total_current_m3"] == 1000.0

    def test_partial_preferred_over_older_final_when_same_month(self):
        """Later partial beats older final in same month."""
        rows = [
            _me_row(idm="100", position_date="01/04/2023", is_partial=False,
                    total_current_m3=800.0),
            _me_row(idm="200", position_date="30/04/2023", is_partial=False,
                    total_current_m3=900.0),
        ]
        df = transform_monthly_ethanol_sales(self._build_df(rows))
        assert len(df) == 1
        assert df.iloc[0]["total_current_m3"] == 900.0

    def test_month_date_april_uses_year_start(self):
        df = transform_monthly_ethanol_sales(self._build_df([
            _me_row(harvest_year="2023_2024", month_num=4)
        ]))
        assert df.iloc[0]["month_date"] == "2023-04-01"

    def test_month_date_january_uses_year_end(self):
        df = transform_monthly_ethanol_sales(self._build_df([
            _me_row(harvest_year="2023_2024", month_num=1)
        ]))
        assert df.iloc[0]["month_date"] == "2024-01-01"

    def test_prior_values_preserved(self):
        row = _me_row(total_current_m3=1000.0, total_prior_m3=900.0)
        df = transform_monthly_ethanol_sales(self._build_df([row]))
        assert df.iloc[0]["total_prior_m3"] == 900.0

    def test_empty_input_returns_empty_with_correct_columns(self):
        df = transform_monthly_ethanol_sales(pd.DataFrame(columns=[
            "harvest_year", "idm", "month_num", "month_label",
            "is_partial", "position_date", "ingest_date",
            "total_current_m3", "total_prior_m3",
            "external_current_m3", "external_prior_m3",
            "internal_current_m3", "internal_prior_m3",
        ]))
        assert len(df) == 0
        for col in MONTHLY_ETHANOL_SALES_COLUMNS:
            assert col in df.columns

    def test_output_columns_match_schema(self):
        df = transform_monthly_ethanol_sales(self._build_df([_me_row()]))
        assert list(df.columns) == MONTHLY_ETHANOL_SALES_COLUMNS
