"""Unit tests for the UNICA annual-by-state bronze → silver transform."""
from __future__ import annotations

import math

import pandas as pd
import pytest

from leviathan.transforms.bronze_to_silver.unica_annual_state import (
    OUTPUT_COLUMNS,
    transform_unica_annual_state,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

_VARS = [
    "cane_crushed_t",
    "sugar_produced_t",
    "ethanol_total_m3",
    "ethanol_hydrous_m3",
    "ethanol_anhydrous_m3",
]

# (variable, value) for São Paulo in 2014_2015
_SP_2014 = {
    "cane_crushed_t":       340_000_000.0,
    "sugar_produced_t":      27_000_000.0,
    "ethanol_total_m3":      12_000_000.0,
    "ethanol_hydrous_m3":     7_000_000.0,
    "ethanol_anhydrous_m3":   5_000_000.0,
}

# (variable, value) for Minas Gerais in 2014_2015
_MG_2014 = {
    "cane_crushed_t":        55_000_000.0,
    "sugar_produced_t":       4_000_000.0,
    "ethanol_total_m3":       2_500_000.0,
    "ethanol_hydrous_m3":     1_500_000.0,
    "ethanol_anhydrous_m3":   1_000_000.0,
}

# (variable, value) for São Paulo in 2015_2016
_SP_2015 = {
    "cane_crushed_t":       350_000_000.0,
    "sugar_produced_t":      28_000_000.0,
    "ethanol_total_m3":      13_000_000.0,
    "ethanol_hydrous_m3":     7_500_000.0,
    "ethanol_anhydrous_m3":   5_500_000.0,
}


def _make_bronze(
    seasons: dict[str, dict[str, dict[str, float]]],
    source: str = "unica",
) -> pd.DataFrame:
    """Build a minimal bronze DataFrame.

    Args:
        seasons: {harvest_year: {state_name: {variable: value}}}
    """
    rows = []
    for hy, states in seasons.items():
        for state, var_vals in states.items():
            for var, val in var_vals.items():
                rows.append({
                    "harvest_year": hy,
                    "period_label": state,
                    "variable": var,
                    "value": val,
                    "source": source,
                })
    return pd.DataFrame(rows)


def _two_season_bronze() -> pd.DataFrame:
    """Two seasons (2014_2015, 2015_2016), 2 states each (São Paulo, Minas Gerais)."""
    return _make_bronze({
        "2014_2015": {
            "São Paulo":    _SP_2014,
            "Minas Gerais": _MG_2014,
        },
        "2015_2016": {
            "São Paulo":    _SP_2015,
            "Minas Gerais": _MG_2014,  # same values for simplicity
        },
    })


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestOutputColumns:
    def test_output_columns_correct(self) -> None:
        df = transform_unica_annual_state(_two_season_bronze())
        assert list(df.columns) == OUTPUT_COLUMNS

    def test_output_columns_on_empty_input(self) -> None:
        empty = pd.DataFrame(columns=["harvest_year", "period_label", "variable", "value"])
        df = transform_unica_annual_state(empty)
        assert list(df.columns) == OUTPUT_COLUMNS
        assert len(df) == 0


class TestRowCount:
    def test_row_count_two_seasons_two_states(self) -> None:
        df = transform_unica_annual_state(_two_season_bronze())
        # 2 seasons × 2 states = 4 rows
        assert len(df) == 4

    def test_row_count_single_season(self) -> None:
        bronze = _make_bronze({"2014_2015": {"São Paulo": _SP_2014}})
        df = transform_unica_annual_state(bronze)
        assert len(df) == 1


class TestValues:
    def test_sao_paulo_2014_values(self) -> None:
        df = transform_unica_annual_state(_two_season_bronze())
        row = df[(df["harvest_year"] == "2014_2015") & (df["state_region"] == "São Paulo")]
        assert len(row) == 1
        r = row.iloc[0]
        assert r["cane_crushed_t"] == _SP_2014["cane_crushed_t"]
        assert r["sugar_produced_t"] == _SP_2014["sugar_produced_t"]
        assert r["ethanol_total_m3"] == _SP_2014["ethanol_total_m3"]
        assert r["ethanol_hydrous_m3"] == _SP_2014["ethanol_hydrous_m3"]
        assert r["ethanol_anhydrous_m3"] == _SP_2014["ethanol_anhydrous_m3"]

    def test_source_column_propagated(self) -> None:
        df = transform_unica_annual_state(_two_season_bronze())
        assert (df["source"] == "unica").all()

    def test_source_defaults_to_unica_when_absent(self) -> None:
        bronze = _two_season_bronze().drop(columns=["source"])
        df = transform_unica_annual_state(bronze)
        assert (df["source"] == "unica").all()


class TestSortOrder:
    def test_sorted_by_harvest_year_then_state(self) -> None:
        df = transform_unica_annual_state(_two_season_bronze())
        # harvest_year should be non-decreasing
        harvest_years = df["harvest_year"].tolist()
        assert harvest_years == sorted(harvest_years)
        # Within each season, state_region should be sorted
        for hy in df["harvest_year"].unique():
            states = df[df["harvest_year"] == hy]["state_region"].tolist()
            assert states == sorted(states)


class TestMissingColumnsError:
    def test_raises_if_harvest_year_missing(self) -> None:
        bronze = _two_season_bronze().drop(columns=["harvest_year"])
        with pytest.raises(ValueError, match="harvest_year"):
            transform_unica_annual_state(bronze)

    def test_raises_if_period_label_missing(self) -> None:
        bronze = _two_season_bronze().drop(columns=["period_label"])
        with pytest.raises(ValueError, match="period_label"):
            transform_unica_annual_state(bronze)

    def test_raises_if_variable_missing(self) -> None:
        bronze = _two_season_bronze().drop(columns=["variable"])
        with pytest.raises(ValueError, match="variable"):
            transform_unica_annual_state(bronze)

    def test_raises_if_value_missing(self) -> None:
        bronze = _two_season_bronze().drop(columns=["value"])
        with pytest.raises(ValueError, match="value"):
            transform_unica_annual_state(bronze)


class TestDeduplication:
    def test_duplicate_rows_deduplicated(self) -> None:
        bronze = _two_season_bronze()
        doubled = pd.concat([bronze, bronze], ignore_index=True)
        df = transform_unica_annual_state(doubled)
        # Should still be 4 rows, not 8
        assert len(df) == 4

    def test_duplicate_values_keep_first(self) -> None:
        bronze = _make_bronze({"2014_2015": {"São Paulo": _SP_2014}})
        # Add a second copy with different values for the same key
        alt = bronze.copy()
        alt["value"] = 999.0
        combined = pd.concat([bronze, alt], ignore_index=True)
        df = transform_unica_annual_state(combined)
        assert len(df) == 1
        assert df.iloc[0]["cane_crushed_t"] == _SP_2014["cane_crushed_t"]


class TestUnknownVariablesDropped:
    def test_unknown_variable_rows_dropped(self) -> None:
        bronze = _two_season_bronze()
        extra = bronze.iloc[:1].copy()
        extra["variable"] = "unknown_metric"
        combined = pd.concat([bronze, extra], ignore_index=True)
        df = transform_unica_annual_state(combined)
        assert len(df) == 4  # no extra row from unknown_metric

    def test_only_unknown_variables_returns_empty(self) -> None:
        bronze = _two_season_bronze()
        bronze["variable"] = "not_a_real_variable"
        df = transform_unica_annual_state(bronze)
        assert df.empty
        assert list(df.columns) == OUTPUT_COLUMNS


class TestStateRegionFiltering:
    def test_nan_period_label_dropped(self) -> None:
        bronze = _two_season_bronze()
        null_row = bronze.iloc[0:1].copy()
        null_row["period_label"] = None
        combined = pd.concat([bronze, null_row], ignore_index=True)
        df = transform_unica_annual_state(combined)
        # Should have same 4 rows; null state_region dropped
        assert len(df) == 4

    def test_empty_string_period_label_dropped(self) -> None:
        bronze = _two_season_bronze()
        empty_row = bronze.iloc[0:1].copy()
        empty_row["period_label"] = "   "
        combined = pd.concat([bronze, empty_row], ignore_index=True)
        df = transform_unica_annual_state(combined)
        assert len(df) == 4

    def test_period_label_renamed_to_state_region(self) -> None:
        df = transform_unica_annual_state(_two_season_bronze())
        assert "state_region" in df.columns
        assert "period_label" not in df.columns

    def test_state_region_values_correct(self) -> None:
        df = transform_unica_annual_state(_two_season_bronze())
        states = set(df[df["harvest_year"] == "2014_2015"]["state_region"].tolist())
        assert states == {"São Paulo", "Minas Gerais"}
