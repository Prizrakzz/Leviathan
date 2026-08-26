"""Data quality tests for silver FAOSTAT production invariants (SILVER-F022 canonical contract).

The transform emits the 12 canonical ``silver_production`` physical columns per (commodity, year)
partition: ``metric`` (not ``variable``), display ``country`` + governed ``country_key``, and the
provenance columns. commodity/year are the projected partition keys (not in the body).
"""
from __future__ import annotations

import pandas as pd
import pytest
from leviathan.transforms.bronze_to_silver.faostat_production import (
    CANONICAL_PHYSICAL_COLUMNS,
    ELEMENT_TO_METRIC,
    transform_faostat_production_silver_df,
)

# The three metrics a CROP bronze frame produces. Named rather than derived from ELEMENT_TO_METRIC:
# since FAO-2 that map also carries the livestock five, and a cocoa fixture can never produce them.
CROP_METRICS = {"production_quantity", "area_harvested", "yield"}


@pytest.fixture()
def silver_faostat_results(faostat_bronze_df: pd.DataFrame):
    """List of (year, silver_df) pairs from the fixture bronze FAOSTAT data."""
    return transform_faostat_production_silver_df(faostat_bronze_df, commodity="cocoa")


@pytest.fixture()
def silver_faostat_df(silver_faostat_results) -> pd.DataFrame:
    """Concatenated silver body across all year partitions."""
    return pd.concat([df for _, df in silver_faostat_results], ignore_index=True)


class TestSilverFaostatSchema:
    def test_returns_list_of_tuples(self, silver_faostat_results):
        assert isinstance(silver_faostat_results, list)
        for item in silver_faostat_results:
            assert isinstance(item, tuple) and len(item) == 2

    def test_body_is_exactly_the_canonical_columns(self, silver_faostat_df):
        assert list(silver_faostat_df.columns) == CANONICAL_PHYSICAL_COLUMNS

    def test_commodity_and_year_are_not_in_body(self, silver_faostat_df):
        assert "commodity" not in silver_faostat_df.columns
        assert "year" not in silver_faostat_df.columns

    def test_source_is_faostat(self, silver_faostat_df):
        assert (silver_faostat_df["source"] == "faostat").all()

    def test_country_key_is_lowercased(self, silver_faostat_df):
        for ck in silver_faostat_df["country_key"].unique():
            assert ck == ck.lower(), f"country_key not lowercased: {ck!r}"


class TestSilverFaostatMetric:
    def test_metric_values_are_standardized(self, silver_faostat_df):
        valid = set(ELEMENT_TO_METRIC.values())
        assert set(silver_faostat_df["metric"].unique()).issubset(valid)

    def test_all_three_crop_metrics_present(self, silver_faostat_df):
        """The fixture is a COCOA bronze frame, so the three CROP metrics are what it must produce --
        all three, none missing.

        This assertion used to read `== set(ELEMENT_TO_METRIC.values())`, which was true only while
        the map held exactly the crop three. FAO-2 (Lane 5) added the livestock five, and a crop
        fixture cannot produce `live_animals`; keeping the whole-map equality would have forced
        either a wrong assertion or a fixture that pretends cocoa has a herd. The equality is
        therefore re-aimed at what the fixture actually is, and the map-side check moves to
        `test_the_crop_metrics_are_a_strict_subset_of_the_map` below, which is the half that can
        still catch a dropped element."""
        assert set(silver_faostat_df["metric"].unique()) == CROP_METRICS

    def test_the_crop_metrics_are_a_strict_subset_of_the_map(self):
        """The map-side half, and it fails in the direction that matters: a crop metric renamed or
        dropped from ELEMENT_TO_METRIC lands here, and so does a livestock metric that stops being
        an addition and starts REPLACING one."""
        values = set(ELEMENT_TO_METRIC.values())
        assert CROP_METRICS < values, sorted(CROP_METRICS - values)
        assert values - CROP_METRICS == {
            "live_animals", "milk_animals", "laying_birds",
            "animals_producing_or_slaughtered", "yield_per_animal"}

    def test_no_raw_element_names_in_metric(self, silver_faostat_df):
        raw = {"Production", "Area harvested", "Yield"}
        assert not (set(silver_faostat_df["metric"].unique()) & raw)


class TestSilverFaostatValues:
    def test_value_column_is_numeric(self, silver_faostat_df):
        assert pd.api.types.is_numeric_dtype(silver_faostat_df["value"])

    def test_partition_years_numeric_and_in_range(self, silver_faostat_results):
        for year, _ in silver_faostat_results:
            assert isinstance(year, int)
            assert 1960 <= year <= 2100


class TestSilverFaostatIsOfficial:
    def test_is_official_is_boolean(self, silver_faostat_df):
        assert pd.api.types.is_bool_dtype(silver_faostat_df["is_official"])

    def test_flag_a_is_official(self, silver_faostat_df):
        """FAO-6: ``A`` is FAO's "Official figure". The pre-FAO-6 pin here asserted the opposite -- it
        was authored against the PRE-2022 legend and the release changed schemes under it, so
        ``is_official`` read TRUE on imputed and missing rows and FALSE on 70% official ones."""
        flag_a_rows = silver_faostat_df[silver_faostat_df["flag"] == "A"]
        # NOT `if not empty:` -- a fixture that stops carrying A rows would green the invariant this
        # test exists to hold in the corrected direction, leaving FAO-6 unpinned at this layer
        # (Lane-4 review, minor 4). A is 43.7% of the live file; an A-free frame is a fixture bug.
        assert not flag_a_rows.empty, "fixture carries no flag='A' rows -- the FAO-6 pin would be vacuous"
        assert flag_a_rows["is_official"].all()

    def test_only_flag_a_is_official(self, silver_faostat_df):
        assert set(silver_faostat_df.loc[silver_faostat_df["is_official"], "flag"].unique()) <= {"A"}

    def test_no_nulls_in_is_official(self, silver_faostat_df):
        assert silver_faostat_df["is_official"].notna().all()


class TestSilverFaostatYearPartitions:
    def test_fixture_produces_single_year_partition(self, silver_faostat_results):
        assert len(silver_faostat_results) == 1
        year, _ = silver_faostat_results[0]
        assert year == 2020
