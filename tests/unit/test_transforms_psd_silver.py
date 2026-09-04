"""Unit tests for the USDA PSD bronze → silver transform.

Tests are pure Python — no S3/AWS dependencies.
The transform is called with pre-built DataFrames that mimic what the bronze
Parquet loader returns from real S3 data (probe-verified 2026-05-20).

Bronze schema (relevant columns):
    commodity_code (int), country_name (str), market_year (int),
    calendar_year (int), month_code (int), attribute_desc (str), unit_desc (str),
    value (float), release_date (str), commodity_desc (str)

Silver adds: leviathan_slug (fan-out), su_ratio, su_ratio_yoy_delta,
    *_revision cols, area_harvested_1000ha, yield_mt_ha.

THE CLOCK RE-ANCHOR (2026-09-04, lane E).  ``release_date`` is no longer computed
from a marketing-year rotation; it comes from the row's OWN
``(calendar_year, month_code)`` stamp plus the registered WASDE day for that
month.  Two things follow for this file and both are deliberate:

  * the fixture SUPPLIES ``calendar_year`` -- it is a required bronze column now,
    and the build fails closed without it;
  * every expected date is DERIVED from the fixture's stamp and the test's BANKED
    calendar (``tests/fixtures/wasde/release_calendar.json``), never hardcoded
    from an arithmetic formula.  A hardcoded date is how the retired rotation
    kept two of its own tests as defenders.

The banked calendar is a snapshot of the 472 registered ``silver_wasde``
partitions, written by ``scripts/silver/gen_wasde_release_calendar.py``.  The unit
suite reads it; NOTHING in ``src/`` or ``jobs/`` does -- a runtime module that
imported a baked calendar would red-stop ``psd_monthly`` every month.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
from leviathan.transforms.bronze_to_silver.usda_psd import (
    _PSD_COMMODITY_TO_SLUGS,
    _SILVER_COLS,
    _compute_psd_release_dates,
)
from leviathan.transforms.bronze_to_silver.usda_psd import (
    transform_psd_bronze_to_silver as _transform_psd_bronze_to_silver,
)

# ---------------------------------------------------------------------------
# The BANKED WASDE calendar (T10/P10: hermetic -- no Glue, no S3, no catalog)
# ---------------------------------------------------------------------------

_FIXTURE = (Path(__file__).resolve().parents[1] / "fixtures" / "wasde"
            / "release_calendar.json")
_BANKED = json.loads(_FIXTURE.read_text(encoding="ascii"))
CAL: dict[str, int] = {k: int(v) for k, v in _BANKED["calendar"].items()}


def transform_psd_bronze_to_silver(dfs, *, calendar=None, counters=None):
    """Every call in this file passes the BANKED calendar, through this one seam.

    ``calendar`` is keyword-only with NO DEFAULT on the real producer -- a default
    is a silent fallback to a stale or empty calendar.  This wrapper supplies the
    banked one so all 43 call sites read ONE clock and no test can accidentally
    drift onto a different calendar; ``TestTheCalendarIsRequired`` below pins the
    no-default law against the REAL function so the wrapper cannot hide it.
    """
    return _transform_psd_bronze_to_silver(
        dfs, calendar=CAL if calendar is None else calendar, counters=counters,
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
    calendar_year: int = 2026,       # the release's own calendar year -- THE CLOCK
    release_date: str = "2026-05-20",
    attrs: dict | None = None,
) -> pd.DataFrame:
    """Build a minimal bronze DataFrame with one row per attribute.

    ``calendar_year`` defaults to 2026 so the default fixture's stamp is
    (2026, month 5), consistent with the default ingest date 2026-05-20: a
    snapshot downloaded on 20 May 2026 carries the May 2026 release.
    """
    if attrs is None:
        attrs = _DEFAULT_ATTRS
    rows = []
    for attr_desc, (unit_desc, value) in attrs.items():
        rows.append({
            "commodity_code":  commodity_code,
            "commodity_desc":  "corn",
            "country_name":    country,
            "market_year":     market_year,
            "calendar_year":   calendar_year,
            "month_code":      month_code,
            "attribute_desc":  attr_desc,
            "unit_desc":       unit_desc,
            "value":           value,
            "release_date":    release_date,
        })
    return pd.DataFrame(rows)


def _expected(calendar_year: int, month_code: int) -> str:
    """The date the BANKED calendar says a stamp resolves to -- derived, never typed."""
    return "%04d-%02d-%02d" % (calendar_year, month_code,
                               CAL["%04d-%02d" % (calendar_year, month_code)])


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
        """Two consecutive releases of one market_year give a release-on-release revision.

        Revisions diff by ``release_date`` (ascending) within
        (leviathan_slug, country, market_year): revision[k] = estimate[release k] -
        estimate[release k-1].  The earlier release has no prior estimate, so its
        revision is NaN; the later one carries the delta (in MT, after the 1000-MT
        unit scale-up).

        THE TWO RELEASES ARRIVE IN TWO SNAPSHOTS, and that is not decoration: one
        bulk file carries ONE stamp per sheet-cell, so two stamps in a single input
        frame is a source-shape event the transform refuses (see
        ``TestStampConstancy``).
        """
        mc5 = _make_bronze(
            commodity_code=440000, market_year=2024, month_code=5, calendar_year=2026,
            release_date="2026-05-20",
            attrs={"Production": ("(1000 MT)", 200.0), "Ending Stocks": ("(1000 MT)", 70.0),
                   "Domestic Consumption": ("(1000 MT)", 200.0)},
        )
        mc6 = _make_bronze(
            commodity_code=440000, market_year=2024, month_code=6, calendar_year=2026,
            release_date="2026-06-15",
            attrs={"Production": ("(1000 MT)", 210.0), "Ending Stocks": ("(1000 MT)", 75.0),
                   "Domestic Consumption": ("(1000 MT)", 202.0)},
        )
        silver = transform_psd_bronze_to_silver([mc5, mc6])
        cbot = silver[silver["leviathan_slug"] == "corn_cbot"].sort_values("release_date")
        assert len(cbot) == 2
        early, late = cbot.iloc[0], cbot.iloc[1]
        assert list(cbot.release_date) == [_expected(2026, 5), _expected(2026, 6)]
        # Earlier release: no prior estimate -> NaN revision.
        assert pd.isna(early["production_mt_revision"])
        # Later release: release-on-release delta, scaled to MT.
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
    """bronze's ingest-timestamp release_date is replaced by the row's OWN STAMP.

    T2/P2 RE-ANCHOR.  These two date tests used to pin the marketing-year
    rotation's arithmetic and were, in the design's words, the rotation's last
    defenders.  What they pin now is the honest reading: the release_date of a row
    stamped (calendar_year, month_code) is the WASDE day registered for that
    calendar month, and the marketing year has nothing to do with it.  The
    expected value is DERIVED from the banked calendar via ``_expected`` so a
    calendar refresh cannot leave a stale literal behind.
    """

    def test_corn_mc5_calendar_year_2026_takes_the_may_2026_wasde_day(self) -> None:
        """Corn stamped (2026, month 5) is the MAY 2026 release, whatever its marketing year.

        The retired rotation read month_code 5 as an MY-relative index and rotated
        it by corn's MYS=9 to land on 2025-01-10 -- a date USDA never published for
        this row.  Corn's marketing year is irrelevant to WHEN a release came out.
        """
        silver = transform_psd_bronze_to_silver([
            _make_bronze(commodity_code=440000, month_code=5, market_year=2024,
                         calendar_year=2026)
        ])
        row = silver[silver["leviathan_slug"] == "corn_cbot"].iloc[0]
        assert row["release_date"] == _expected(2026, 5)

    def test_wheat_mc1_calendar_year_2024_takes_the_january_2024_wasde_day(self) -> None:
        """Wheat stamped (2024, month 1) is the JANUARY 2024 release.

        The rotation gave 2024-06-10 here by adding wheat's MYS=6; the stamp says
        January.  Two commodities stamped in the same month now share a date,
        which is exactly what a release calendar means.
        """
        silver = transform_psd_bronze_to_silver([
            _make_bronze(commodity_code=410000, month_code=1, market_year=2024,
                         calendar_year=2024)
        ])
        row = silver[silver["leviathan_slug"] == "soft_red_winter_wheat_cbot"].iloc[0]
        assert row["release_date"] == _expected(2024, 1)

    def test_two_sheets_in_one_stamp_month_share_the_release_day(self) -> None:
        """The clock is a CALENDAR, not a per-commodity formula."""
        corn = _make_bronze(commodity_code=440000, month_code=3, market_year=2024,
                            calendar_year=2026)
        wheat = _make_bronze(commodity_code=410000, month_code=3, market_year=2023,
                             calendar_year=2026)
        silver = transform_psd_bronze_to_silver([pd.concat([corn, wheat], ignore_index=True)])
        assert set(silver["release_date"]) == {_expected(2026, 3)}

    def test_month_code_zero_maps_to_jan_1(self) -> None:
        """mc=0 (pre-tracking) -> Jan 1 of MARKET_YEAR so it is always visible.

        P3, UNCHANGED AND LOAD-BEARING.  The assertion does not move.  Anchoring
        these rows on calendar_year instead was measured and refused: over 245,315
        in-scope mc==0 rows the two years differ on 26.7%, and switching would move
        59,544 rows EARLIER -- the leakage direction.  Keeping it is also what
        makes 30,715 wide rows byte-identical across the whole re-baseline.
        """
        silver = transform_psd_bronze_to_silver([
            _make_bronze(commodity_code=440000, month_code=0, market_year=1990,
                         calendar_year=1989)
        ])
        row = silver[silver["leviathan_slug"] == "corn_cbot"].iloc[0]
        assert row["release_date"] == "1990-01-01"

    def test_ingest_date_not_stored(self) -> None:
        """The original bronze release_date (ingest timestamp) must not survive."""
        silver = transform_psd_bronze_to_silver([
            _make_bronze(commodity_code=440000, month_code=5, market_year=2024,
                         calendar_year=2026, release_date="2026-05-20")
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


# ---------------------------------------------------------------------------
# TestReleaseDateClamp (F2)
# ---------------------------------------------------------------------------

class TestReleaseDateClamp:
    """T5/P5 RE-ANCHOR: the clamp is INERT under the honest clock, and it is KEPT.

    Its old premise -- "the MY-relative formula projects current-crop rows to
    FUTURE dates" -- is false now: a row's date comes from its own stamp, which is
    a release that has already happened.  MEASURED on three banked bronze
    snapshots the clamp fires ZERO times, under both candidate day rules, with the
    eight-code month-end set; under the retired rotation it fired on 78,738
    exploded rows.

    So the class asserts two things instead.  (a) It does not fire on honest
    input.  (b) When something DOES push a date past its snapshot it disposes of
    the row BY NAME and counts it -- it never silently substitutes and it never
    raises.  An inert fence that fires is a clock-regression alarm; deleting it
    would delete the alarm.
    """

    _INGEST = "2026-05-20"

    def test_the_clamp_is_inert_on_honest_input(self) -> None:
        """An ordinary stamped row is dated by the calendar and counted as such."""
        counters: dict = {}
        bronze = _make_bronze(commodity_code=440000, month_code=5, market_year=2026,
                              calendar_year=2026, release_date=self._INGEST)
        silver = transform_psd_bronze_to_silver([bronze], counters=counters)
        assert counters["n_clamped"] == 0
        assert counters["n_clamped_to_wasde_day"] == 0
        assert counters["n_clamped_to_ingest"] == 0
        assert (silver["release_date"] == _expected(2026, 5)).all()
        assert (silver["release_date"] <= self._INGEST).all()

    def test_a_wm_and_t_month_end_past_ingest_takes_the_registered_wasde_day(self) -> None:
        """Disposition ``clamped_to_wasde_day``, counted, never a raise.

        This is the ONE case the monthly path can actually produce: a World
        Markets and Trade sheet stamped in the SNAPSHOT's own month takes
        month-end, and month-end sits after a day-8-13 fetch.  Measured headroom
        today is 13 days over 333,744 stamped WM&T rows -- real, unfired, and not
        a reason to hard-fail a monthly job in a month the banked snapshots
        (May/July/August) cannot observe.  Cheese (240000) is a WM&T sheet.
        """
        counters: dict = {}
        bronze = _make_bronze(commodity_code=240000, month_code=5, market_year=2026,
                              calendar_year=2026, release_date="2026-05-13",
                              attrs={"Ending Stocks": ("(1000 MT)", 70.0),
                                     "Domestic Consumption": ("(1000 MT)", 200.0)})
        silver = transform_psd_bronze_to_silver([bronze], counters=counters)
        assert counters["n_clamped"] == len(bronze) * 1     # one slug for 240000
        assert counters["n_clamped_to_wasde_day"] == counters["n_clamped"]
        assert counters["n_clamped_to_ingest"] == 0
        assert counters["n_clamped_cross_month_declined"] == 0
        # It took a PUBLISHED day, not the download date.
        assert (silver["release_date"] == _expected(2026, 5)).all()
        assert (silver["release_date"] <= "2026-05-13").all()
        # AND THE DISPOSITION MOVED WITH THE DATE.  day_dispositions is a gate
        # reading; a clamped row still reporting 'month_end_wmt' would tell the
        # gate the PRE-clamp convention while n_clamped_to_wasde_day told it the
        # post-clamp one -- two counters describing one row and disagreeing.
        assert counters["day_dispositions"] == {"clamped_to_wasde_day": counters["n_clamped"]}
        assert "month_end_wmt" not in counters["day_dispositions"]

    def test_a_registered_day_that_is_ALSO_past_ingest_falls_back_to_the_ingest_date(self) -> None:
        """The second half of the clamp's condition, and it is not decoration.

        A circular stamped in the SNAPSHOT's own month can sit after the fetch on
        BOTH candidate days: month-end is late, and so is the registered WASDE day
        when the DAG fires on day 8 and the release lands on day 12. Substituting
        a date that is STILL in the future would leave the per-row bound violated
        for the task's own fail-closed guard to find as a hard abort. It is a
        named, counted disposition instead.
        """
        counters: dict = {}
        assert CAL["2026-05"] > 9, "this fixture needs a registered day later than the ingest day"
        bronze = _make_bronze(commodity_code=240000, month_code=5, market_year=2026,
                              calendar_year=2026, release_date="2026-05-09",
                              attrs={"Ending Stocks": ("(1000 MT)", 70.0),
                                     "Domestic Consumption": ("(1000 MT)", 200.0)})
        silver = transform_psd_bronze_to_silver([bronze], counters=counters)
        assert counters["n_clamped"] == counters["n_clamped_to_ingest"] > 0
        assert counters["n_clamped_to_wasde_day"] == 0
        assert (silver["release_date"] == "2026-05-09").all()

    def test_an_uncovered_month_past_ingest_falls_back_to_the_ingest_date(self) -> None:
        """Disposition ``clamped_to_ingest``: no registered day exists to take.

        2006-07 is one of the two months USDA published and silver_wasde has not
        ingested, so the clock dates it month-end (2006-07-31).  With an ingest
        date inside that month there is no published day to fall back to and the
        shipped bound -- the snapshot's own date -- is the only one left.
        """
        counters: dict = {}
        assert "2006-07" in _BANKED["uningested_months"]
        bronze = _make_bronze(commodity_code=440000, month_code=7, market_year=2006,
                              calendar_year=2006, release_date="2006-07-20")
        silver = transform_psd_bronze_to_silver([bronze], counters=counters)
        assert counters["n_clamped"] == counters["n_clamped_to_ingest"] > 0
        assert counters["n_clamped_to_wasde_day"] == 0
        assert (silver["release_date"] == "2006-07-20").all()

    def test_historical_row_unchanged_by_clamp(self) -> None:
        """A row stamped years before the snapshot is left exactly where it is."""
        bronze = _make_bronze(commodity_code=440000, month_code=6, market_year=2000,
                              calendar_year=2001, release_date=self._INGEST)
        raw = _compute_psd_release_dates(bronze, calendar=CAL)
        assert (raw == _expected(2001, 6)).all()      # historical, below the bound
        silver = transform_psd_bronze_to_silver([bronze])
        assert (silver["release_date"] == _expected(2001, 6)).all()

    def test_an_uncovered_stamp_month_takes_month_end_and_is_counted(self) -> None:
        """A month OUR silver_wasde does not carry is dated month-END, and named.

        Month-end is PIT-conservative: an absent calendar entry may only make a
        number appear LATER, never earlier.  2001-05 is one of the 28 months the
        banked calendar does not carry; the disposition is COUNTED and the stamp
        month is NAMED, because presenting a convention as a measurement without a
        counter is the fabricated-clock failure repeating one order of magnitude
        smaller.
        """
        counters: dict = {}
        assert "2001-05" not in CAL
        bronze = _make_bronze(commodity_code=440000, month_code=5, market_year=2000,
                              calendar_year=2001, release_date=self._INGEST)
        silver = transform_psd_bronze_to_silver([bronze], counters=counters)
        assert (silver["release_date"] == "2001-05-31").all()
        assert counters["n_month_end_fallback"] > 0
        assert counters["month_end_fallback_months"] == ["2001-05"]
        assert counters["n_month_end_fallback_wide"] == len(silver)
        assert counters["n_clamped"] == 0

    def test_month_code_zero_historical_unchanged(self) -> None:
        """mc=0 (pre-WASDE-tracking) anchors to Jan 1 and stays well below the bound."""
        bronze = _make_bronze(commodity_code=440000, month_code=0, market_year=1990,
                              calendar_year=1990, release_date=self._INGEST)
        silver = transform_psd_bronze_to_silver([bronze])
        assert (silver["release_date"] == "1990-01-01").all()

    def test_mixed_frame_clamps_only_the_offending_rows(self) -> None:
        """Historical and same-month WM&T rows in one frame: only the WM&T one moves."""
        counters: dict = {}
        hist = _make_bronze(commodity_code=440000, month_code=6, market_year=2000,
                            calendar_year=2001, release_date="2026-05-13")
        wmt = _make_bronze(commodity_code=240000, month_code=5, market_year=2026,
                           calendar_year=2026, release_date="2026-05-13",
                           attrs={"Ending Stocks": ("(1000 MT)", 70.0),
                                  "Domestic Consumption": ("(1000 MT)", 200.0)})
        silver = transform_psd_bronze_to_silver(
            [pd.concat([hist, wmt], ignore_index=True)], counters=counters)
        assert set(silver["release_date"]) == {_expected(2001, 6), _expected(2026, 5)}
        assert (silver["release_date"] <= "2026-05-13").all()
        assert counters["n_clamped_to_ingest"] == 0
        assert counters["n_clamped_to_wasde_day"] > 0

    def test_a_CROSS_MONTH_clamp_is_DECLINED_by_name_and_the_row_stays_in_its_stamp_month(
        self,
    ) -> None:
        """The clamp may never rewrite WHICH MONTH published a row.

        P21 -- release_date determines wasde_release_month -- is what step 10's
        dedup key rests on (it sheds wasde_release_month and claims to
        discriminate identically) and what lets the numbers card refuse to declare
        a vintage_tiebreak.  A WM&T sheet stamped 2026-08 inside a partition
        ingested 2026-07-30 would take '2026-07-30' under a bare ingest clamp, and
        that row would then carry wasde_release_month 8 with a July date: step 10
        would key two genuinely different vintages onto one date and drop one of
        them by bronze_ingest_date, silently.

        So the substitution is DECLINED, by a name the gate can read, and the row
        keeps a date INSIDE its own stamp month -- the registered WASDE day here,
        because 2026-08 has one.  The residual date is still after ingest, and that
        is deliberate: the task's fail-closed guard should abort, because a stamp
        month that post-dates the whole snapshot means the clock and the source
        have diverged, which is not something a clamp is allowed to paper over.
        """
        counters: dict = {}
        bronze = _make_bronze(commodity_code=240000, month_code=8, market_year=2026,
                              calendar_year=2026, release_date="2026-07-30",
                              attrs={"Ending Stocks": ("(1000 MT)", 70.0),
                                     "Domestic Consumption": ("(1000 MT)", 200.0)})
        silver = transform_psd_bronze_to_silver([bronze], counters=counters)
        assert counters["n_clamped"] == counters["n_clamped_cross_month_declined"] > 0
        assert counters["n_clamped_to_wasde_day"] == 0
        assert counters["n_clamped_to_ingest"] == 0
        assert (silver["release_date"] == _expected(2026, 8)).all()
        # P21 holds THROUGH the clamp, which is the whole point of declining.
        assert (silver["release_date"].str.slice(5, 7).astype(int)
                == silver["wasde_release_month"]).all()
        assert counters["day_dispositions"] == {
            "clamped_cross_month_declined": counters["n_clamped"]
        }

    def test_a_CROSS_MONTH_clamp_with_no_registered_day_takes_the_months_FIRST_day(
        self,
    ) -> None:
        """The other half of the declined branch: the earliest day the month offers.

        2001-05 is a month the banked calendar does not carry, so there is no
        published day to take.  The row falls to 2001-05-01 -- still inside its own
        stamp month, so P21 survives, and the earliest date that month can offer,
        which is as close to honouring the ingest bound as a date inside the stamp
        month can get.
        """
        counters: dict = {}
        assert "2001-05" not in CAL
        bronze = _make_bronze(commodity_code=240000, month_code=5, market_year=2001,
                              calendar_year=2001, release_date="2001-04-20",
                              attrs={"Ending Stocks": ("(1000 MT)", 70.0),
                                     "Domestic Consumption": ("(1000 MT)", 200.0)})
        silver = transform_psd_bronze_to_silver([bronze], counters=counters)
        assert counters["n_clamped"] == counters["n_clamped_cross_month_declined"] > 0
        assert (silver["release_date"] == "2001-05-01").all()
        assert (silver["release_date"].str.slice(5, 7).astype(int)
                == silver["wasde_release_month"]).all()

    def test_the_wide_fallback_counter_is_keyed_on_the_DISPOSITION_not_the_month(
        self,
    ) -> None:
        """A WM&T sheet inside an uncovered month is NOT a fallback row.

        Both conventions land on the same day -- the last of the stamp month -- so
        a counter that tests release_date's MONTH against month_end_fallback_months
        absorbs the WM&T rows and reports a different number wearing the same name.
        MEASURED on the three banked snapshots: 39 wide rows (5 in 2006-07, 34 in
        2008-10), which is why the month-keyed count read 51,454 where the
        disposition-keyed one reads 51,415.  Both numbers cards and gate G6 quote
        this counter.
        """
        counters: dict = {}
        assert "2001-05" not in CAL
        corn = _make_bronze(commodity_code=440000, month_code=5, market_year=2000,
                            calendar_year=2001, release_date=self._INGEST)
        cheese = _make_bronze(commodity_code=240000, month_code=5, market_year=2000,
                              calendar_year=2001, release_date=self._INGEST)
        silver = transform_psd_bronze_to_silver(
            [pd.concat([corn, cheese], ignore_index=True)], counters=counters)
        # One month, one date, two conventions.
        assert set(silver["release_date"]) == {"2001-05-31"}
        assert counters["month_end_fallback_months"] == ["2001-05"]
        assert counters["n_clamped"] == 0
        n_wmt_rows = int((silver["leviathan_slug"] == "cheese").sum())
        assert n_wmt_rows > 0
        assert counters["n_month_end_fallback_wide"] == len(silver) - n_wmt_rows
        assert counters["n_month_end_fallback_wide"] < len(silver)
        assert counters["day_dispositions"]["month_end_wmt"] > 0

    def test_clamp_preserves_release_date_dtype(self) -> None:
        """The clamp must not change release_date's object/string dtype."""
        clamped = transform_psd_bronze_to_silver([
            _make_bronze(commodity_code=240000, month_code=5, market_year=2026,
                         calendar_year=2026, release_date="2026-05-13",
                         attrs={"Ending Stocks": ("(1000 MT)", 70.0),
                                "Domestic Consumption": ("(1000 MT)", 200.0)})
        ])
        historical = transform_psd_bronze_to_silver([_make_bronze()])
        assert clamped["release_date"].dtype == object
        assert historical["release_date"].dtype == object
        # And the values remain plain ISO date strings, not Timestamps.
        assert all(isinstance(v, str) for v in clamped["release_date"])


# ---------------------------------------------------------------------------
# TestReprintDedup (2026-07-18): semi-annual sheets re-print the SAME
# (market_year, month_code) row in consecutive monthly bulk snapshots; the
# latest release must win, exactly once, before derived metrics are computed.
# ---------------------------------------------------------------------------

class TestReprintDedup:
    def test_reprinted_vintage_keeps_the_newest_snapshot_only(self) -> None:
        """ONE release re-printed by TWO snapshots collapses to ONE row, newest wins.

        RE-ANCHORED.  Both snapshots carry the SAME stamp (2025, month 12), so under
        the honest clock they carry the same release_date -- which is what a
        re-print IS.  The collapse therefore happens at step 10, keyed on
        release_date and ordered by bronze_ingest_date, and the JULY snapshot's
        revised production is the one that survives.  Under the retired rotation
        the two rows also shared a date, but for the wrong reason: the date was a
        function of (market_year, month_code) and could not tell a re-print from a
        different release.
        """
        may = _make_bronze(commodity_code=440000, market_year=2025, month_code=12,
                           calendar_year=2025, release_date="2026-05-20")
        july = _make_bronze(commodity_code=440000, market_year=2025, month_code=12,
                            calendar_year=2025, release_date="2026-07-17")
        # the re-print carries a revision: bump production in the July snapshot
        july.loc[july.attribute_desc == "Production", "value"] = (
            july.loc[july.attribute_desc == "Production", "value"] * 2)

        counters: dict = {}
        silver = transform_psd_bronze_to_silver([may, july], counters=counters)
        key = ["leviathan_slug", "country", "market_year", "release_date"]
        assert not silver.duplicated(subset=key).any(), "re-printed vintage rows survived dedup"
        one = silver[silver.leviathan_slug == "corn_cbot"]
        assert len(one) == 1
        assert one.release_date.iloc[0] == _expected(2025, 12)
        # the NEWER snapshot's value won, which is what "latest wins" has to mean
        assert one.production_mt.iloc[0] == pytest.approx(400_000.0)
        # and this is a re-print, not a recovered vintage: the retired key would
        # have deleted nothing here.
        assert counters["n_reprints_under_shipped_key"] == 0

    def test_distinct_months_are_never_collapsed(self) -> None:
        m5 = _make_bronze(commodity_code=440000, market_year=2025, month_code=5,
                          calendar_year=2026, release_date="2026-05-20")
        m6 = _make_bronze(commodity_code=440000, market_year=2025, month_code=6,
                          calendar_year=2026, release_date="2026-06-15")
        silver = transform_psd_bronze_to_silver([m5, m6])
        assert len(silver[silver.leviathan_slug == "corn_cbot"]) == 2


# ---------------------------------------------------------------------------
# T6 / P6 -- THE STAMP-CONSTANCY ASSERTION, IN TWO HALVES
# ---------------------------------------------------------------------------

class TestStampConstancy:
    """One RELEASE must carry one stamp per sheet-cell; two SNAPSHOTS need not.

    The second half is the load-bearing one.  MEASURED: 0 violations per banked
    snapshot, but 3,290 of 142,015 sheet-cells (2.32%) across three concatenated
    -- because a cell's stamp legitimately ADVANCES between monthly releases.  The
    monthly task feeds every distinct-ETag bronze partition from a bucket that
    holds nine, so an assertion that migrated onto the concat would raise on its
    first real fire and kill the build, not the data.
    """

    def test_two_stamps_for_one_cell_in_ONE_frame_raises(self) -> None:
        a = _make_bronze(commodity_code=440000, market_year=2025, month_code=5,
                         calendar_year=2026,
                         attrs={"Ending Stocks": ("(1000 MT)", 70.0)})
        b = _make_bronze(commodity_code=440000, market_year=2025, month_code=6,
                         calendar_year=2026,
                         attrs={"Production": ("(1000 MT)", 200.0)})
        with pytest.raises(ValueError, match="MORE THAN ONE"):
            transform_psd_bronze_to_silver([pd.concat([a, b], ignore_index=True)])

    def test_two_frames_disagreeing_on_one_cell_do_NOT_raise(self) -> None:
        """The stamp ADVANCING between snapshots is the normal case, not a defect."""
        counters: dict = {}
        older = _make_bronze(commodity_code=440000, market_year=2025, month_code=5,
                             calendar_year=2026, release_date="2026-05-20")
        newer = _make_bronze(commodity_code=440000, market_year=2025, month_code=6,
                             calendar_year=2026, release_date="2026-06-15")
        silver = transform_psd_bronze_to_silver([older, newer], counters=counters)
        assert counters["n_stamp_constancy_violations"] == 0
        assert set(silver["release_date"]) == {_expected(2026, 5), _expected(2026, 6)}

    def test_an_OUT_OF_SCOPE_code_with_two_stamps_does_NOT_stop_the_build(self) -> None:
        """The assertion is SCOPED to the codes this transform actually serves.

        It is called at step 1, BEFORE the step-3 commodity filter, because the
        per-INPUT-SNAPSHOT placement is load-bearing and must not be traded for the
        scoping.  So the scoping lives inside the helper instead.  MEASURED on the
        three banked snapshots: the raw frame carries 162,544 / 162,695 / 162,788
        sheet-cells against the 141,771 / 141,922 / 142,015 in-scope ones the
        assertion's own docstring quotes -- 20,773 cells across the 16 REFUSED
        codes.  Unfiltered, a stamp anomaly in a code the table never serves would
        hard-abort psd_monthly for a fact no reader can reach.

        11000 is one of the refused codes (see _PSD_UNMAPPED_CODES); step 3 drops
        its rows, so the frame that survives here is corn alone.
        """
        counters: dict = {}
        assert 11000 not in _PSD_COMMODITY_TO_SLUGS
        good = _make_bronze(commodity_code=440000, market_year=2025, month_code=5,
                            calendar_year=2026, release_date="2026-05-20")
        bad_a = _make_bronze(commodity_code=11000, market_year=2025, month_code=5,
                             calendar_year=2026, release_date="2026-05-20",
                             attrs={"Ending Stocks": ("(1000 MT)", 70.0)})
        bad_b = _make_bronze(commodity_code=11000, market_year=2025, month_code=6,
                             calendar_year=2026, release_date="2026-05-20",
                             attrs={"Production": ("(1000 MT)", 200.0)})
        silver = transform_psd_bronze_to_silver(
            [pd.concat([good, bad_a, bad_b], ignore_index=True)], counters=counters)
        assert counters["n_stamp_constancy_violations"] == 0
        assert set(silver["leviathan_slug"]) == set(_PSD_COMMODITY_TO_SLUGS[440000])

    def test_an_IN_SCOPE_code_with_two_stamps_still_raises(self) -> None:
        """The other side of the scoping: narrowing the population must not blunt it."""
        a = _make_bronze(commodity_code=440000, market_year=2025, month_code=5,
                         calendar_year=2026, attrs={"Ending Stocks": ("(1000 MT)", 70.0)})
        b = _make_bronze(commodity_code=440000, market_year=2025, month_code=6,
                         calendar_year=2026, attrs={"Production": ("(1000 MT)", 200.0)})
        noise = _make_bronze(commodity_code=11000, market_year=2025, month_code=5,
                             calendar_year=2026, attrs={"Production": ("(1000 MT)", 1.0)})
        with pytest.raises(ValueError, match="IN-SCOPE sheet-cell"):
            transform_psd_bronze_to_silver(
                [pd.concat([a, b, noise], ignore_index=True)])


# ---------------------------------------------------------------------------
# T7 / P7 -- STEP 10 KEEPS BOTH VINTAGES OF A SAME-MONTH, DIFFERENT-YEAR PAIR
# ---------------------------------------------------------------------------

class TestTwoVintagesOfOneCalendarMonth:
    """The 258 rows the retired step-11.5 key was deleting.

    ``wasde_release_month`` is a CALENDAR month now, so one marketing year can be
    printed in June 2023 AND in June 2026.  The retired latest-only key
    (slug, country, market_year, wasde_release_month) collapsed those two onto
    one row and threw the older away; measured over three banked bronze snapshots
    that is exactly 258 rows, and under an archive backfill it would cap every
    sheet-cell at twelve vintages forever.  The shape is pinned on the design's
    own two named pairs.
    """

    @staticmethod
    def _pair(commodity_code, slug, market_year, month_code, years, attrs_a, attrs_b):
        a = _make_bronze(commodity_code=commodity_code, market_year=market_year,
                         month_code=month_code, calendar_year=years[0],
                         release_date="2026-05-20", attrs=attrs_a)
        b = _make_bronze(commodity_code=commodity_code, market_year=market_year,
                         month_code=month_code, calendar_year=years[1],
                         release_date="2026-08-13", attrs=attrs_b)
        counters: dict = {}
        silver = transform_psd_bronze_to_silver([a, b], counters=counters)
        return silver[silver.leviathan_slug == slug].sort_values("release_date"), counters

    def test_barley_turkey_my2019_month_6_keeps_two_release_dates(self) -> None:
        """barley / Turkey / MY2019 / month 6: 2023-06 and 2026-06, both kept.

        The design's first named pair.  Both vintages carry the SAME su_ratio
        (0.090118 on the live object), so the pair survives even where the metric
        does not move -- the point is the DATE, not the value.
        """
        attrs = {"Ending Stocks": ("(1000 MT)", 70.0),
                 "Domestic Consumption": ("(1000 MT)", 200.0)}
        rows, counters = self._pair(430000, "barley", 2019, 6, (2023, 2026), attrs, attrs)
        assert len(rows) == 2
        assert list(rows.release_date) == [_expected(2023, 6), _expected(2026, 6)]
        assert set(rows.wasde_release_month) == {6}
        # ONE row is what the retired key would have left behind.
        assert counters["n_reprints_under_shipped_key"] == 1
        assert rows.su_ratio.round(6).tolist() == [0.35, 0.35]

    def test_milk_fluid_us_my2024_month_7_keeps_two_vintages_on_the_nan_path(self) -> None:
        """milk_fluid / United States / MY2024 / month 7: the NaN-path pin.

        The design's second named pair: Ending Stocks is ABSENT on this sheet, so
        su_ratio is NaN on both rows.  The pair must survive anyway -- a vintage is
        a fact about publication, not about whether a derived metric happens to be
        computable.  223000 is also a World Markets and Trade sheet, so both dates
        are month-END rather than the registered WASDE day.
        """
        attrs = {"Production": ("(1000 MT)", 200.0),
                 "Domestic Consumption": ("(1000 MT)", 200.0)}
        rows, counters = self._pair(223000, "milk_fluid", 2024, 7, (2025, 2026), attrs, attrs)
        assert len(rows) == 2
        assert list(rows.release_date) == ["2025-07-31", "2026-07-31"]
        assert rows.su_ratio.isna().all()
        assert counters["n_reprints_under_shipped_key"] == 1


# ---------------------------------------------------------------------------
# T8 / P8 -- STEP 13, THE LATEST-VINTAGE REDUCTION
# ---------------------------------------------------------------------------

class TestSuRatioYoyDeltaReduction:
    """No WITHIN-marketing-year delta is ever emitted under a year-over-year label.

    The reduction takes each (slug, country, calendar-month, market_year) group to
    its LATEST release_date, diffs adjacent marketing years there, and leaves every
    non-latest vintage NULL.  MEASURED against the live canonical over three banked
    bronze snapshots: BYTE-IDENTICAL -- 0 differing of 247,036 joined keys, non-null
    count unchanged at 211,890 -- so the column stays inside the flip's
    byte-identity pin and above its 0.6 contract floor.
    """

    @staticmethod
    def _frame(market_year, calendar_year, ending):
        return _make_bronze(commodity_code=440000, market_year=market_year,
                            month_code=6, calendar_year=calendar_year,
                            release_date="2026-08-13",
                            attrs={"Ending Stocks": ("(1000 MT)", ending),
                                   "Domestic Consumption": ("(1000 MT)", 200.0)})

    def test_the_non_latest_vintage_carries_null_and_the_latest_carries_the_yoy(self) -> None:
        # MY2023 printed once; MY2024 printed TWICE in the same calendar month of
        # two different years -- an old vintage and the current one.
        counters: dict = {}
        silver = transform_psd_bronze_to_silver([
            # the 2023 snapshot: MY2024's old vintage, su 0.30
            self._frame(2024, 2023, 60.0),
            # the 2026 snapshot: MY2023 at su 0.35 and MY2024's current print at 0.45
            pd.concat([self._frame(2023, 2026, 70.0),
                       self._frame(2024, 2026, 90.0)], ignore_index=True),
        ], counters=counters)
        cbot = (silver[silver.leviathan_slug == "corn_cbot"]
                .sort_values(["market_year", "release_date"]))
        assert len(cbot) == 3
        my2023, my2024_old, my2024_new = cbot.iloc[0], cbot.iloc[1], cbot.iloc[2]
        # the first marketing year in the group has no predecessor: DECLINED
        assert pd.isna(my2023["su_ratio_yoy_delta"])
        # the superseded vintage is not the year's current estimate: NULL
        assert my2024_old["release_date"] == _expected(2023, 6)
        assert pd.isna(my2024_old["su_ratio_yoy_delta"])
        # the latest vintage carries the YEAR-over-year move, 0.45 - 0.35
        assert my2024_new["release_date"] == _expected(2026, 6)
        assert my2024_new["su_ratio_yoy_delta"] == pytest.approx(0.10)
        # and the absent comparator is COUNTED, never silent
        assert counters["n_step13_declined_absent_comparator"] >= 1

    def test_no_within_marketing_year_delta_is_ever_emitted(self) -> None:
        """Two vintages of ONE marketing year must never diff against each other."""
        silver = transform_psd_bronze_to_silver([
            self._frame(2024, 2023, 60.0),
            self._frame(2024, 2026, 90.0),
        ])
        cbot = silver[silver.leviathan_slug == "corn_cbot"]
        assert len(cbot) == 2
        assert cbot["su_ratio_yoy_delta"].isna().all(), (
            "a 0.45 - 0.30 delta here would be a WITHIN-marketing-year revision "
            "wearing a year-over-year label"
        )


# ---------------------------------------------------------------------------
# T9 / P9 -- THE REVISION COLUMNS ARE ORDERED BY RELEASE DATE
# ---------------------------------------------------------------------------

class TestRevisionOrderWrapsTheCalendar:
    """A marketing year whose releases WRAP the calendar year still diffs forward.

    Corn's MY2024 runs calendar months 5..12 of 2024 and then 1..4 of 2025.  The
    retired sort was on wasde_release_month, which would put January 2025 BEFORE
    May 2024 and invert the sign of every revision for 38 of the 47 mapped codes --
    invisible today at ~2.5% column density, and wrong the moment an archive
    backfill makes it dense.
    """

    def test_january_of_the_next_year_is_the_LATER_release(self) -> None:
        def rows(calendar_year, month_code, production):
            return _make_bronze(commodity_code=440000, market_year=2024,
                                month_code=month_code, calendar_year=calendar_year,
                                release_date="2026-08-13",
                                attrs={"Production": ("(1000 MT)", production),
                                       "Ending Stocks": ("(1000 MT)", 70.0),
                                       "Domestic Consumption": ("(1000 MT)", 200.0)})

        # two SNAPSHOTS: the December 2024 release and the January 2025 one.
        silver = transform_psd_bronze_to_silver([rows(2024, 12, 200.0), rows(2025, 1, 210.0)])
        cbot = (silver[silver.leviathan_slug == "corn_cbot"]
                .sort_values("release_date"))
        assert list(cbot.release_date) == [_expected(2024, 12), _expected(2025, 1)]
        # December 2024 is the FIRST release of this pair -> no prior estimate
        assert pd.isna(cbot.iloc[0]["production_mt_revision"])
        # January 2025 is the SECOND -> +10,000 MT, positive because the sort is
        # chronological. A month-ordered sort would put it first and flip the sign.
        assert cbot.iloc[1]["production_mt_revision"] == pytest.approx(10_000.0)
        assert list(cbot.wasde_release_month) == [12, 1]


# ---------------------------------------------------------------------------
# T25 / P21 -- release_date DETERMINES wasde_release_month
# ---------------------------------------------------------------------------

class TestReleaseDateDeterminesTheMonth:
    """Two rulings lean on this invariant silently; this makes it explicit.

    (a) Step 10's dedup key sheds wasde_release_month and still discriminates
    identically.  (b) The numbers card refuses to declare a vintage_tiebreak,
    because a tie on release_date implies an identical wasde_release_month and the
    appended ORDER BY term could never break anything.
    """

    def test_every_stamped_row_and_every_mc_zero_row(self) -> None:
        frames = [
            _make_bronze(commodity_code=440000, market_year=2024, month_code=3,
                         calendar_year=2026, release_date="2026-08-13"),
            _make_bronze(commodity_code=410000, market_year=2023, month_code=11,
                         calendar_year=2025, release_date="2026-08-13"),
            _make_bronze(commodity_code=240000, market_year=2024, month_code=7,
                         calendar_year=2025, release_date="2026-08-13",
                         attrs={"Ending Stocks": ("(1000 MT)", 70.0),
                                "Domestic Consumption": ("(1000 MT)", 200.0)}),
            _make_bronze(commodity_code=440000, market_year=1990, month_code=0,
                         calendar_year=1989, release_date="2026-08-13"),
        ]
        silver = transform_psd_bronze_to_silver([pd.concat(frames, ignore_index=True)])
        stamped = silver[silver["wasde_release_month"] > 0]
        assert len(stamped) > 0
        assert (stamped["release_date"].str.slice(5, 7).astype(int)
                == stamped["wasde_release_month"]).all()
        zero = silver[silver["wasde_release_month"] == 0]
        assert len(zero) > 0
        assert (zero["release_date"] == "1990-01-01").all()


# ---------------------------------------------------------------------------
# THE CALENDAR IS REQUIRED, AND IT HAS NO DEFAULT
# ---------------------------------------------------------------------------

class TestTheCalendarIsRequired:
    """A default on the ``calendar`` keyword is a silent fallback to a stale one.

    Four signatures gained it and every one of them is keyword-only with no
    default.  This pins the wide producer's; the long companion's is pinned in
    tests/unit/test_psd_attributes_long.py.
    """

    def test_the_producer_refuses_to_run_without_a_calendar(self) -> None:
        with pytest.raises(TypeError, match="calendar"):
            _transform_psd_bronze_to_silver([_make_bronze()])

    def test_calendar_year_is_a_required_bronze_column(self) -> None:
        bronze = _make_bronze().drop(columns=["calendar_year"])
        with pytest.raises(ValueError, match="missing required columns"):
            transform_psd_bronze_to_silver([bronze])
