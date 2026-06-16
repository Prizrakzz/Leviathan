"""Unit tests for the USDA PSD bronze → silver transform.

Tests are pure Python — no S3/AWS dependencies.
The transform is called with pre-built DataFrames that mimic what the bronze
Parquet loader returns from real S3 data (probe-verified 2026-05-20).

Bronze schema (relevant columns):
    commodity_code (int), country_name (str), market_year (int),
    month_code (int), attribute_desc (str), unit_desc (str), value (float),
    release_date (str), commodity_desc (str)

Silver adds: leviathan_slug (fan-out), su_ratio, su_ratio_yoy_delta,
    *_revision cols, area_harvested_1000ha, yield_mt_ha.
"""
from __future__ import annotations

import pandas as pd
import pytest

from leviathan.transforms.bronze_to_silver.usda_psd import (
    _SILVER_COLS,
    transform_psd_bronze_to_silver,
)

# ---------------------------------------------------------------------------
# Test fixture helpers
# ---------------------------------------------------------------------------

_DEFAULT_ATTRS = {
    "Beginning Stocks": ("(1000 MT)", 100.0),
    "Production":       ("(1000 MT)", 200.0),
    "Imports":          ("(1000 MT)", 50.0),
    "Exports":          ("(1000 MT)", 80.0),
    "Ending Stocks":    ("(1000 MT)", 70.0),
    "Domestic Consumption": ("(1000 MT)", 200.0),
    "Area Harvested":   ("(1000 HA)", 500.0),
    "Yield":            ("(MT/HA)",   4.0),
}


def _make_bronze(
    commodity_code: int = 440000,    # corn
    country: str = "United States",
    market_year: int = 2024,
    month_code: int = 5,
    release_date: str = "2026-05-20",
    attrs: dict | None = None,
) -> pd.DataFrame:
    """Build a minimal bronze DataFrame with one row per attribute."""
    if attrs is None:
        attrs = _DEFAULT_ATTRS
    rows = []
    for attr_desc, (unit_desc, value) in attrs.items():
        rows.append({
            "commodity_code":  commodity_code,
            "commodity_desc":  "corn",
            "country_name":    country,
            "market_year":     market_year,
            "month_code":      month_code,
            "attribute_desc":  attr_desc,
            "unit_desc":       unit_desc,
            "value":           value,
            "release_date":    release_date,
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# TestFanOut
# ---------------------------------------------------------------------------

class TestFanOut:
    def test_corn_produces_five_slugs(self) -> None:
        # PSD corn (440000) fans out to every corn/maize futures slug, including
        # the two South African maize contracts added in the slug-map expansion.
        silver = transform_psd_bronze_to_silver([_make_bronze(commodity_code=440000)])
        slugs = set(silver["leviathan_slug"].unique())
        assert slugs == {
            "corn_cbot", "campinas_corn_reference_bmf", "french_maize_matif",
            "south_african_white_maize_jse", "south_african_yellow_maize_jse",
        }

    def test_cotton_produces_one_slug(self) -> None:
        silver = transform_psd_bronze_to_silver([_make_bronze(commodity_code=2631000, attrs={
            "Beginning Stocks":   ("1000 480 lb. Bales", 100.0),
            "Production":         ("1000 480 lb. Bales", 200.0),
            "Imports":            ("1000 480 lb. Bales", 50.0),
            "Exports":            ("1000 480 lb. Bales", 80.0),
            "Ending Stocks":      ("1000 480 lb. Bales", 70.0),
            "Domestic Use":       ("1000 480 lb. Bales", 200.0),
        })])
        slugs = set(silver["leviathan_slug"].unique())
        assert slugs == {"cotton"}

    def test_wheat_produces_four_slugs(self) -> None:
        silver = transform_psd_bronze_to_silver([_make_bronze(commodity_code=410000)])
        slugs = set(silver["leviathan_slug"].unique())
        assert slugs == {
            "hard_red_winter_wheat_kcbt",
            "soft_red_winter_wheat_cbot",
            "hard_red_spring_wheat_mgex",
            "french_wheat_matif",
        }

    def test_unknown_commodity_code_dropped(self) -> None:
        bronze = _make_bronze(commodity_code=99999)
        silver = transform_psd_bronze_to_silver([bronze])
        assert len(silver) == 0

    def test_rows_per_slug_equals_one_country_market_year(self) -> None:
        """Each corn row produces 5 slugs × 1 (country, market_year) = 5 rows."""
        silver = transform_psd_bronze_to_silver([_make_bronze(commodity_code=440000)])
        assert len(silver) == 5


# ---------------------------------------------------------------------------
# TestUnitConversion
# ---------------------------------------------------------------------------

class TestUnitConversion:
    def test_1000mt_multiplied_by_1000(self) -> None:
        """200 (1000 MT) × 1000 = 200,000 MT."""
        silver = transform_psd_bronze_to_silver([
            _make_bronze(commodity_code=440000, attrs={
                "Production": ("(1000 MT)", 200.0),
                "Ending Stocks": ("(1000 MT)", 70.0),
                "Domestic Consumption": ("(1000 MT)", 200.0),
            })
        ])
        row = silver[silver["leviathan_slug"] == "corn_cbot"].iloc[0]
        assert abs(row["production_mt"] - 200_000.0) < 0.01

    def test_cotton_bales_to_mt(self) -> None:
        """200 × 1000 bales × 217.724 kg/bale = 43,544,800 kg = 43,544.8 MT."""
        silver = transform_psd_bronze_to_silver([
            _make_bronze(commodity_code=2631000, attrs={
                "Production":   ("1000 480 lb. Bales", 200.0),
                "Ending Stocks": ("1000 480 lb. Bales", 70.0),
                "Domestic Use": ("1000 480 lb. Bales", 200.0),
            })
        ])
        row = silver[silver["leviathan_slug"] == "cotton"].iloc[0]
        assert abs(row["production_mt"] - 200.0 * 217.724) < 0.1

    def test_coffee_bags_to_mt(self) -> None:
        """100 × (1000 60 KG BAGS) × 60 = 6,000,000 kg = 6,000 MT."""
        silver = transform_psd_bronze_to_silver([
            _make_bronze(commodity_code=711100, attrs={
                "Production":         ("(1000 60 KG BAGS)", 100.0),
                "Ending Stocks":      ("(1000 60 KG BAGS)", 40.0),
                "Domestic Consumption": ("(1000 60 KG BAGS)", 90.0),
            })
        ])
        row = silver[silver["leviathan_slug"] == "arabica_coffee"].iloc[0]
        assert abs(row["production_mt"] - 100.0 * 60.0) < 0.01

    def test_area_harvested_factor_is_1(self) -> None:
        """500 (1000 HA) stays 500 (column name encodes unit)."""
        silver = transform_psd_bronze_to_silver([
            _make_bronze(commodity_code=440000, attrs={
                "Area Harvested":     ("(1000 HA)", 500.0),
                "Ending Stocks":      ("(1000 MT)", 70.0),
                "Domestic Consumption": ("(1000 MT)", 200.0),
            })
        ])
        row = silver[silver["leviathan_slug"] == "corn_cbot"].iloc[0]
        assert abs(row["area_harvested_1000ha"] - 500.0) < 0.01

    def test_yield_kg_ha_converted_to_mt_ha(self) -> None:
        """4000 KG/HA ÷ 1000 = 4.0 MT/HA."""
        silver = transform_psd_bronze_to_silver([
            _make_bronze(commodity_code=440000, attrs={
                "Yield":              ("(KG/HA)", 4000.0),
                "Ending Stocks":      ("(1000 MT)", 70.0),
                "Domestic Consumption": ("(1000 MT)", 200.0),
            })
        ])
        row = silver[silver["leviathan_slug"] == "corn_cbot"].iloc[0]
        assert abs(row["yield_mt_ha"] - 4.0) < 0.0001

    def test_yield_mt_ha_factor_is_1(self) -> None:
        """4.0 MT/HA stays 4.0."""
        silver = transform_psd_bronze_to_silver([
            _make_bronze(commodity_code=440000, attrs={
                "Yield":              ("(MT/HA)", 4.0),
                "Ending Stocks":      ("(1000 MT)", 70.0),
                "Domestic Consumption": ("(1000 MT)", 200.0),
            })
        ])
        row = silver[silver["leviathan_slug"] == "corn_cbot"].iloc[0]
        assert abs(row["yield_mt_ha"] - 4.0) < 0.0001

    def test_unknown_unit_raises(self) -> None:
        bronze = _make_bronze(commodity_code=440000, attrs={
            "Production": ("UNKNOWN_UNIT", 100.0),
            "Ending Stocks": ("(1000 MT)", 70.0),
            "Domestic Consumption": ("(1000 MT)", 200.0),
        })
        with pytest.raises(ValueError, match="unrecognised unit_desc"):
            transform_psd_bronze_to_silver([bronze])


# ---------------------------------------------------------------------------
# TestConsumptionAttrOverride
# ---------------------------------------------------------------------------

class TestConsumptionAttrOverride:
    def test_sugar_total_disappearance_becomes_consumption(self) -> None:
        silver = transform_psd_bronze_to_silver([
            _make_bronze(commodity_code=612000, attrs={
                "Ending Stocks":      ("(1000 MT)", 70.0),
                "Total Disappearance": ("(1000 MT)", 200.0),
            })
        ])
        row = silver[silver["leviathan_slug"] == "raw_sugar"].iloc[0]
        assert not pd.isna(row["consumption_mt"])
        assert abs(row["consumption_mt"] - 200_000.0) < 0.01

    def test_cotton_domestic_use_becomes_consumption(self) -> None:
        silver = transform_psd_bronze_to_silver([
            _make_bronze(commodity_code=2631000, attrs={
                "Ending Stocks": ("1000 480 lb. Bales", 70.0),
                "Domestic Use":  ("1000 480 lb. Bales", 200.0),
            })
        ])
        row = silver[silver["leviathan_slug"] == "cotton"].iloc[0]
        assert not pd.isna(row["consumption_mt"])

    def test_corn_domestic_consumption_unchanged(self) -> None:
        silver = transform_psd_bronze_to_silver([
            _make_bronze(commodity_code=440000, attrs={
                "Domestic Consumption": ("(1000 MT)", 200.0),
                "Ending Stocks":        ("(1000 MT)", 70.0),
            })
        ])
        row = silver[silver["leviathan_slug"] == "corn_cbot"].iloc[0]
        assert abs(row["consumption_mt"] - 200_000.0) < 0.01


# ---------------------------------------------------------------------------
# TestSuRatio
# ---------------------------------------------------------------------------

class TestSuRatio:
    def test_su_ratio_correct(self) -> None:
        """su_ratio = ending / consumption = 70,000 / 200,000 = 0.35."""
        silver = transform_psd_bronze_to_silver([
            _make_bronze(commodity_code=440000, attrs={
                "Ending Stocks":        ("(1000 MT)", 70.0),
                "Domestic Consumption": ("(1000 MT)", 200.0),
            })
        ])
        row = silver[silver["leviathan_slug"] == "corn_cbot"].iloc[0]
        assert abs(row["su_ratio"] - 0.35) < 0.0001

    def test_su_ratio_zero_consumption_is_nan(self) -> None:
        silver = transform_psd_bronze_to_silver([
            _make_bronze(commodity_code=440000, attrs={
                "Ending Stocks":        ("(1000 MT)", 70.0),
                "Domestic Consumption": ("(1000 MT)", 0.0),
            })
        ])
        row = silver[silver["leviathan_slug"] == "corn_cbot"].iloc[0]
        assert pd.isna(row["su_ratio"])

    def test_su_ratio_missing_ending_stocks_is_nan(self) -> None:
        silver = transform_psd_bronze_to_silver([
            _make_bronze(commodity_code=440000, attrs={
                "Domestic Consumption": ("(1000 MT)", 200.0),
            })
        ])
        row = silver[silver["leviathan_slug"] == "corn_cbot"].iloc[0]
        assert pd.isna(row["su_ratio"])


# ---------------------------------------------------------------------------
# TestSuRatioYoyDelta
# ---------------------------------------------------------------------------

class TestSuRatioYoyDelta:
    def _two_year_silver(self) -> pd.DataFrame:
        rows_2023 = _make_bronze(
            commodity_code=440000, market_year=2023,
            attrs={"Ending Stocks": ("(1000 MT)", 70.0), "Domestic Consumption": ("(1000 MT)", 200.0)},
        )
        rows_2024 = _make_bronze(
            commodity_code=440000, market_year=2024,
            attrs={"Ending Stocks": ("(1000 MT)", 90.0), "Domestic Consumption": ("(1000 MT)", 200.0)},
        )
        return transform_psd_bronze_to_silver([pd.concat([rows_2023, rows_2024], ignore_index=True)])

    def test_first_year_yoy_delta_is_nan(self) -> None:
        silver = self._two_year_silver()
        cbot = silver[silver["leviathan_slug"] == "corn_cbot"].sort_values("market_year")
        assert pd.isna(cbot.iloc[0]["su_ratio_yoy_delta"])

    def test_second_year_yoy_delta_is_correct(self) -> None:
        """su_ratio 2024=0.45, 2023=0.35 → delta=0.10."""
        silver = self._two_year_silver()
        cbot = silver[silver["leviathan_slug"] == "corn_cbot"].sort_values("market_year")
        delta = cbot.iloc[1]["su_ratio_yoy_delta"]
        assert abs(delta - 0.10) < 0.0001


# ---------------------------------------------------------------------------
# TestRevisionCols
# ---------------------------------------------------------------------------

class TestRevisionCols:
    def test_single_release_revision_all_nan(self) -> None:
        silver = transform_psd_bronze_to_silver([_make_bronze()])
        for col in ("production_mt_revision", "ending_stocks_mt_revision", "consumption_mt_revision"):
            assert silver[col].isna().all(), f"{col} should be all NaN with one release"

    def test_two_monthly_releases_revision_correct(self) -> None:
        """Two WASDE months (mc=5, mc=6) for one market_year give a month-on-month
        revision.

        Revisions diff by ``wasde_release_month`` (ascending) within
        (leviathan_slug, country, market_year): revision[M] = estimate[M] -
        estimate[M-1].  The earlier month has no prior estimate, so its revision
        is NaN; the later month carries the delta (in MT, after the 1000-MT unit
        scale-up).
        """
        mc5 = _make_bronze(
            commodity_code=440000, market_year=2024, month_code=5,
            attrs={"Production": ("(1000 MT)", 200.0), "Ending Stocks": ("(1000 MT)", 70.0),
                   "Domestic Consumption": ("(1000 MT)", 200.0)},
        )
        mc6 = _make_bronze(
            commodity_code=440000, market_year=2024, month_code=6,
            attrs={"Production": ("(1000 MT)", 210.0), "Ending Stocks": ("(1000 MT)", 75.0),
                   "Domestic Consumption": ("(1000 MT)", 202.0)},
        )
        silver = transform_psd_bronze_to_silver([pd.concat([mc5, mc6], ignore_index=True)])
        cbot = silver[silver["leviathan_slug"] == "corn_cbot"].sort_values("wasde_release_month")
        assert len(cbot) == 2
        early, late = cbot.iloc[0], cbot.iloc[1]
        # Earlier month: no prior estimate -> NaN revision.
        assert pd.isna(early["production_mt_revision"])
        # Later month: month-on-month delta, scaled to MT.
        assert late["production_mt_revision"] == pytest.approx(10_000.0)
        assert late["ending_stocks_mt_revision"] == pytest.approx(5_000.0)
        assert late["consumption_mt_revision"] == pytest.approx(2_000.0)

    def test_revision_groups_do_not_bleed(self) -> None:
        """Revisions for US and Brazil corn should be independent."""
        us_r1 = _make_bronze(
            commodity_code=440000, country="United States", market_year=2024,
            release_date="2026-05-20",
            attrs={"Production": ("(1000 MT)", 200.0), "Ending Stocks": ("(1000 MT)", 70.0),
                   "Domestic Consumption": ("(1000 MT)", 200.0)},
        )
        br_r1 = _make_bronze(
            commodity_code=440000, country="Brazil", market_year=2024,
            release_date="2026-05-20",
            attrs={"Production": ("(1000 MT)", 150.0), "Ending Stocks": ("(1000 MT)", 50.0),
                   "Domestic Consumption": ("(1000 MT)", 130.0)},
        )
        silver = transform_psd_bronze_to_silver([pd.concat([us_r1, br_r1], ignore_index=True)])
        # With single release, all revision cols must be NaN for both countries
        us_row = silver[(silver["leviathan_slug"] == "corn_cbot") & (silver["country"] == "United States")]
        br_row = silver[(silver["leviathan_slug"] == "corn_cbot") & (silver["country"] == "Brazil")]
        assert pd.isna(us_row.iloc[0]["production_mt_revision"])
        assert pd.isna(br_row.iloc[0]["production_mt_revision"])


# ---------------------------------------------------------------------------
# TestEdgeCases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_month_code_zero_passes_through(self) -> None:
        """Historical rows with month_code=0 are valid and should be retained."""
        bronze = _make_bronze(commodity_code=440000, month_code=0, market_year=1990)
        silver = transform_psd_bronze_to_silver([bronze])
        assert len(silver) > 0
        assert (silver["wasde_release_month"] == 0).all()

    def test_empty_input_raises(self) -> None:
        with pytest.raises(ValueError, match="at least one DataFrame"):
            transform_psd_bronze_to_silver([])

    def test_missing_required_column_raises(self) -> None:
        bronze = _make_bronze().drop(columns=["unit_desc"])
        with pytest.raises(ValueError, match="missing required columns"):
            transform_psd_bronze_to_silver([bronze])

    def test_all_zero_country_preserved(self) -> None:
        """Zero-production countries should not be dropped."""
        bronze = _make_bronze(
            commodity_code=440000, country="Andorra",
            attrs={"Production": ("(1000 MT)", 0.0), "Ending Stocks": ("(1000 MT)", 0.0),
                   "Domestic Consumption": ("(1000 MT)", 0.0)},
        )
        silver = transform_psd_bronze_to_silver([bronze])
        assert "Andorra" in silver["country"].values


# ---------------------------------------------------------------------------
# TestReleaseDateDerivation
# ---------------------------------------------------------------------------

class TestReleaseDateDerivation:
    """Verify that bronze's ingest-timestamp release_date is replaced with the
    computed WASDE calendar date based on (market_year, month_code, MYS)."""

    def test_corn_mc5_market_year_2024_date(self) -> None:
        """Corn (MYS=Sep=9), mc=5, market_year=2024 → January 2025 WASDE.

        total = 9 + 5 - 2 = 12 → cal_month = 12%12+1 = 1 (Jan), cal_year = 2024+1 = 2025.
        """
        silver = transform_psd_bronze_to_silver([
            _make_bronze(commodity_code=440000, month_code=5, market_year=2024)
        ])
        row = silver[silver["leviathan_slug"] == "corn_cbot"].iloc[0]
        assert row["release_date"] == "2025-01-10"

    def test_wheat_mc1_market_year_2024_date(self) -> None:
        """Wheat (MYS=Jun=6), mc=1, market_year=2024 → June 2024 WASDE.

        total = 6 + 1 - 2 = 5 → cal_month = 5%12+1 = 6 (Jun), cal_year = 2024+0 = 2024.
        """
        silver = transform_psd_bronze_to_silver([
            _make_bronze(commodity_code=410000, month_code=1, market_year=2024)
        ])
        row = silver[silver["leviathan_slug"] == "soft_red_winter_wheat_cbot"].iloc[0]
        assert row["release_date"] == "2024-06-10"

    def test_month_code_zero_maps_to_jan_1(self) -> None:
        """mc=0 (pre-tracking) → Jan 1 of market_year so it is always visible."""
        silver = transform_psd_bronze_to_silver([
            _make_bronze(commodity_code=440000, month_code=0, market_year=1990)
        ])
        row = silver[silver["leviathan_slug"] == "corn_cbot"].iloc[0]
        assert row["release_date"] == "1990-01-01"

    def test_ingest_date_not_stored(self) -> None:
        """The original bronze release_date (ingest timestamp) must not survive."""
        silver = transform_psd_bronze_to_silver([
            _make_bronze(commodity_code=440000, month_code=5, market_year=2024,
                         release_date="2026-05-20")
        ])
        assert "2026-05-20" not in silver["release_date"].values


# ---------------------------------------------------------------------------
# TestSchema
# ---------------------------------------------------------------------------

class TestSchema:
    def test_all_silver_cols_present(self) -> None:
        silver = transform_psd_bronze_to_silver([_make_bronze()])
        for col in _SILVER_COLS:
            assert col in silver.columns, f"Missing column: {col}"

    def test_no_extra_cols(self) -> None:
        silver = transform_psd_bronze_to_silver([_make_bronze()])
        assert list(silver.columns) == _SILVER_COLS

    def test_market_year_dtype_int16(self) -> None:
        silver = transform_psd_bronze_to_silver([_make_bronze()])
        assert str(silver["market_year"].dtype) == "Int16"

    def test_wasde_release_month_dtype_int8(self) -> None:
        silver = transform_psd_bronze_to_silver([_make_bronze()])
        assert str(silver["wasde_release_month"].dtype) == "Int8"

    def test_mass_cols_are_float64(self) -> None:
        silver = transform_psd_bronze_to_silver([_make_bronze()])
        for col in ("production_mt", "ending_stocks_mt", "consumption_mt",
                    "su_ratio", "area_harvested_1000ha", "yield_mt_ha"):
            assert silver[col].dtype == "float64", f"{col} should be float64"
