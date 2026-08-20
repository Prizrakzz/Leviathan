"""Unit tests for USDA NASS annual bronze -> silver transform."""
from __future__ import annotations

import pandas as pd
import pytest
from leviathan.transforms.bronze_to_silver.usda_nass_annual import (
    ACRE_TO_HA,
    LB_PER_ACRE_TO_T_HA,
    LB_TO_MT,
    OUTPUT_COLUMNS,
    PRE_DLD_OUTPUT_COLUMNS,
    _release_date,
    transform_nass_annual_bronze_to_silver,
)


def _row(
    *,
    commodity_desc: str = "CORN",
    class_desc: str = "ALL CLASSES",
    statisticcat_desc: str,
    unit_desc: str,
    value: float,
    cv_pct: float = 1.2,
    agg_level_desc: str = "STATE",
    state_alpha: str | None = "IA",
    year: int = 2024,
    source_desc: str = "SURVEY",
    prodn_practice_desc: str = "ALL PRODUCTION PRACTICES",
    util_practice_desc: str = "ALL UTILIZATION PRACTICES",
) -> dict:
    return {
        "leviathan_slug": "legacy_bronze_slug",
        "source_desc": source_desc,
        "sector_desc": "CROPS",
        "group_desc": "FIELD CROPS",
        "commodity_desc": commodity_desc,
        "class_desc": class_desc,
        "prodn_practice_desc": prodn_practice_desc,
        "util_practice_desc": util_practice_desc,
        "domain_desc": "TOTAL",
        "domaincat_desc": "NOT SPECIFIED",
        "short_desc": f"{commodity_desc} - {statisticcat_desc}",
        "freq_desc": "ANNUAL",
        "reference_period_desc": "YEAR",
        "statisticcat_desc": statisticcat_desc,
        "unit_desc": unit_desc,
        "agg_level_desc": agg_level_desc,
        "state_alpha": state_alpha,
        "state_name": "IOWA",
        "county_code": None,
        "county_name": None,
        "year": year,
        "value": value,
        "cv_pct": cv_pct,
        "download_date": "2026-05-20",
        "source": "usda_nass",
    }


def _corn_rows(**overrides) -> list[dict]:
    return [
        _row(statisticcat_desc="AREA PLANTED", unit_desc="ACRES", value=100.0, cv_pct=0.1, **overrides),
        _row(statisticcat_desc="AREA HARVESTED", unit_desc="ACRES", value=90.0, cv_pct=0.2, **overrides),
        _row(statisticcat_desc="YIELD", unit_desc="BU / ACRE", value=180.0, cv_pct=0.3, **overrides),
        _row(statisticcat_desc="PRODUCTION", unit_desc="BU", value=16_200.0, cv_pct=0.4, **overrides),
    ]


class TestNassAnnualSilverTransform:
    def test_outputs_expected_columns(self) -> None:
        silver = transform_nass_annual_bronze_to_silver(pd.DataFrame(_corn_rows()))
        assert list(silver.columns) == OUTPUT_COLUMNS

    def test_pivots_one_row_per_slug_state_year(self) -> None:
        silver = transform_nass_annual_bronze_to_silver(pd.DataFrame(_corn_rows()))
        assert len(silver) == 1
        row = silver.iloc[0]
        assert row["leviathan_slug"] == "corn_cbot"
        assert row["state"] == "IA"
        assert row["year"] == 2024
        assert row["marketing_year"] == 2024

    def test_converts_corn_area_yield_and_production(self) -> None:
        silver = transform_nass_annual_bronze_to_silver(pd.DataFrame(_corn_rows()))
        row = silver.iloc[0]
        assert row["area_planted_ha"] == pytest.approx(100.0 * ACRE_TO_HA)
        assert row["area_harvested_ha"] == pytest.approx(90.0 * ACRE_TO_HA)
        assert row["yield_t_ha"] == pytest.approx(180.0 * 56.0 * LB_PER_ACRE_TO_T_HA)
        assert row["production_mt"] == pytest.approx(16_200.0 * 56.0 * LB_TO_MT)

    def test_emits_metric_specific_cv_columns(self) -> None:
        silver = transform_nass_annual_bronze_to_silver(pd.DataFrame(_corn_rows()))
        row = silver.iloc[0]
        assert row["area_planted_cv_pct"] == pytest.approx(0.1)
        assert row["area_harvested_cv_pct"] == pytest.approx(0.2)
        assert row["yield_cv_pct"] == pytest.approx(0.3)
        assert row["production_cv_pct"] == pytest.approx(0.4)
        assert "cv_pct" not in silver.columns

    def test_drops_county_rows_and_fills_national_state(self) -> None:
        county = _row(
            statisticcat_desc="PRODUCTION",
            unit_desc="BU",
            value=1.0,
            agg_level_desc="COUNTY",
            state_alpha="IA",
        )
        national = _corn_rows(agg_level_desc="NATIONAL", state_alpha=None)
        silver = transform_nass_annual_bronze_to_silver(pd.DataFrame([county, *national]))
        assert len(silver) == 1
        assert silver.iloc[0]["state"] == "US"

    def test_drops_non_feature_pct_and_dollar_units(self) -> None:
        rows = [
            *_corn_rows(),
            _row(statisticcat_desc="AREA PLANTED", unit_desc="PCT BY SIZE GROUP", value=86.6),
            _row(statisticcat_desc="AREA PLANTED", unit_desc="PCT BY TYPE", value=91.0),
            _row(statisticcat_desc="PRODUCTION", unit_desc="$", value=123_456.0),
        ]
        silver = transform_nass_annual_bronze_to_silver(pd.DataFrame(rows))
        assert len(silver) == 1
        assert silver.iloc[0]["area_planted_ha"] == pytest.approx(100.0 * ACRE_TO_HA)
        assert silver.iloc[0]["production_mt"] == pytest.approx(16_200.0 * 56.0 * LB_TO_MT)

    def test_domain_total_filter_excludes_size_group_duplicates(self) -> None:
        rows = [
            *_corn_rows(),
            {
                **_row(statisticcat_desc="PRODUCTION", unit_desc="BU", value=99_999.0),
                "domain_desc": "AREA OPERATED",
                "domaincat_desc": "AREA OPERATED: (1,000 OR MORE ACRES)",
            },
        ]
        silver = transform_nass_annual_bronze_to_silver(pd.DataFrame(rows))
        assert len(silver) == 1
        assert silver.iloc[0]["production_mt"] == pytest.approx(16_200.0 * 56.0 * LB_TO_MT)

    def test_reference_period_year_filter_excludes_forecast_duplicates(self) -> None:
        rows = [
            *_corn_rows(),
            {
                **_row(statisticcat_desc="PRODUCTION", unit_desc="BU", value=99_999.0),
                "reference_period_desc": "YEAR - AUG FORECAST",
            },
        ]
        silver = transform_nass_annual_bronze_to_silver(pd.DataFrame(rows))
        assert len(silver) == 1
        assert silver.iloc[0]["production_mt"] == pytest.approx(16_200.0 * 56.0 * LB_TO_MT)

    def test_soybeans_recanonicalizes_to_existing_soybeans_slug(self) -> None:
        rows = _corn_rows(commodity_desc="SOYBEANS")
        rows[3]["value"] = 1_000.0
        silver = transform_nass_annual_bronze_to_silver(pd.DataFrame(rows))
        assert silver.iloc[0]["leviathan_slug"] == "soybeans_cbot"
        assert silver.iloc[0]["production_mt"] == pytest.approx(1_000.0 * 60.0 * LB_TO_MT)

    def test_supports_soybean_yield_per_net_planted_acre(self) -> None:
        rows = _corn_rows(commodity_desc="SOYBEANS")
        rows[2]["unit_desc"] = "BU / NET PLANTED ACRE"
        rows[2]["value"] = 30.0
        silver = transform_nass_annual_bronze_to_silver(pd.DataFrame(rows))
        assert silver.iloc[0]["yield_t_ha"] == pytest.approx(30.0 * 60.0 * LB_PER_ACRE_TO_T_HA)

    def test_prefers_standard_yield_when_net_planted_acre_duplicate_exists(self) -> None:
        rows = [
            *_corn_rows(commodity_desc="SOYBEANS"),
            _row(
                commodity_desc="SOYBEANS",
                statisticcat_desc="YIELD",
                unit_desc="BU / NET PLANTED ACRE",
                value=23.3,
            ),
        ]
        rows[2]["value"] = 23.5
        silver = transform_nass_annual_bronze_to_silver(pd.DataFrame(rows))
        assert silver.iloc[0]["yield_t_ha"] == pytest.approx(23.5 * 60.0 * LB_PER_ACRE_TO_T_HA)

    def test_supports_rice_lb_yield_per_net_planted_acre(self) -> None:
        rows = [
            _row(commodity_desc="RICE", statisticcat_desc="AREA PLANTED", unit_desc="ACRES", value=100.0),
            _row(commodity_desc="RICE", statisticcat_desc="AREA HARVESTED", unit_desc="ACRES", value=90.0),
            _row(commodity_desc="RICE", statisticcat_desc="YIELD", unit_desc="LB / NET PLANTED ACRE", value=4_000.0),
            _row(commodity_desc="RICE", statisticcat_desc="PRODUCTION", unit_desc="CWT", value=3_600.0),
        ]
        silver = transform_nass_annual_bronze_to_silver(pd.DataFrame(rows))
        assert silver.iloc[0]["yield_t_ha"] == pytest.approx(4_000.0 * LB_PER_ACRE_TO_T_HA)

    def test_excludes_non_all_class_rice_rows(self) -> None:
        """Rice milling classes stay excluded (rough_rice_cbot is fed by the ALL CLASSES total).
        D-EC P0: the COTTONSEED row that used to ride along in this fixture as a second EXCLUSION now
        has a home -- cottonseed is a declared tier-1 context node -- so it moved to the class-lane
        module and this test asserts only what it is named for."""
        rows = [
            _row(commodity_desc="RICE", statisticcat_desc="AREA PLANTED", unit_desc="ACRES", value=100.0),
            _row(commodity_desc="RICE", statisticcat_desc="AREA HARVESTED", unit_desc="ACRES", value=90.0),
            _row(commodity_desc="RICE", statisticcat_desc="YIELD", unit_desc="LB / ACRE", value=7_640.0),
            _row(commodity_desc="RICE", statisticcat_desc="PRODUCTION", unit_desc="CWT", value=6_876.0),
            _row(commodity_desc="RICE", class_desc="LONG GRAIN", statisticcat_desc="YIELD", unit_desc="LB / ACRE", value=7_670.0),
        ]
        silver = transform_nass_annual_bronze_to_silver(pd.DataFrame(rows))
        assert len(silver) == 1
        assert silver.iloc[0]["leviathan_slug"] == "rough_rice_cbot"

    def test_excludes_aggregate_wheat(self) -> None:
        rows = _corn_rows(commodity_desc="WHEAT", class_desc="ALL CLASSES")
        silver = transform_nass_annual_bronze_to_silver(pd.DataFrame(rows))
        assert silver.empty

    def test_maps_contract_specific_winter_wheat_classes(self) -> None:
        """D-EC P0: this test used to assert on commodity_desc values NASS DOES NOT PUBLISH
        ('WHEAT, WINTER' with class 'SOFT RED WINTER'/'HARD RED WINTER'), which is why it passed
        green over a lane that emitted zero rows for its whole life. Re-pointed at the MEASURED
        source strings -- commodity_desc='WHEAT', class on class_desc -- and at the sibling's
        convention. The hard-red-winter sub-class is a written refusal now (production-only, and it
        would collide with WINTER); see _RECORDED_CLASS_EXCLUSIONS and the class-lane test module."""
        rows = [
            *_corn_rows(commodity_desc="WHEAT", class_desc="WINTER"),
            *_corn_rows(
                commodity_desc="WHEAT",
                class_desc="SPRING, (EXCL DURUM)",
                state_alpha="ND",
            ),
        ]
        silver = transform_nass_annual_bronze_to_silver(pd.DataFrame(rows))
        assert set(silver["leviathan_slug"]) == {
            "soft_red_winter_wheat_cbot",
            "hard_red_spring_wheat_mgex",
        }

    def test_supports_cotton_bale_production_and_lb_yield(self) -> None:
        rows = [
            _row(commodity_desc="COTTON", statisticcat_desc="AREA PLANTED", unit_desc="ACRES", value=100.0),
            _row(commodity_desc="COTTON", statisticcat_desc="AREA HARVESTED", unit_desc="ACRES", value=90.0),
            _row(commodity_desc="COTTON", statisticcat_desc="YIELD", unit_desc="LB / ACRE", value=800.0),
            _row(commodity_desc="COTTON", statisticcat_desc="PRODUCTION", unit_desc="480 LB BALES", value=10.0),
        ]
        silver = transform_nass_annual_bronze_to_silver(pd.DataFrame(rows))
        row = silver.iloc[0]
        assert row["yield_t_ha"] == pytest.approx(800.0 * LB_PER_ACRE_TO_T_HA)
        assert row["production_mt"] == pytest.approx(10.0 * 480.0 * LB_TO_MT)

    def test_raises_on_unsupported_retained_unit(self) -> None:
        rows = _corn_rows()
        rows[2]["unit_desc"] = "BAGS / ACRE"
        with pytest.raises(ValueError, match="Unsupported NASS yield unit"):
            transform_nass_annual_bronze_to_silver(pd.DataFrame(rows))

    def test_conflicting_duplicate_metric_rows_raise(self) -> None:
        rows = _corn_rows()
        rows.append(
            _row(
                statisticcat_desc="PRODUCTION",
                unit_desc="BU",
                value=99_999.0,
                cv_pct=9.9,
            )
        )
        with pytest.raises(ValueError, match="conflicting duplicate metric rows"):
            transform_nass_annual_bronze_to_silver(pd.DataFrame(rows))


# =====================================================================================================
# D-LD pre-step D-LD-9a -- the DERIVED release_date vintage anchor.
#
# The blocker this closes, measured 2026-08-18 against every canonical object with pyarrow (593
# parquet objects, 14,631 rows): silver_nass_annual carried NO date, vintage, ingest or month column
# of ANY kind, so a numbers card had nothing to anchor its as-of guard on -- knowledge_col() returned
# None and query.build_sql raised "no knowledge/date column to anchor the as-of guard". `year` is the
# CROP year, not a knowledge date. The remedy is the conab survey_release_date idiom, coefficient for
# coefficient: ONE producer-derived, conservative, never-leak timing column.
# =====================================================================================================
class TestNassAnnualReleaseDateAnchor:
    def test_release_date_is_the_appended_tail_and_nothing_moved(self) -> None:
        """ADDITIVE: release_date is LAST (mirroring the Glue ADD COLUMNS append and the hand DDL),
        and the 14 pre-existing columns keep their exact order -- a reorder would silently rewrite
        593 canonical objects into a different physical layout."""
        assert OUTPUT_COLUMNS[-1] == "release_date"
        assert OUTPUT_COLUMNS[:-1] == PRE_DLD_OUTPUT_COLUMNS
        assert PRE_DLD_OUTPUT_COLUMNS == [
            "leviathan_slug", "country", "state", "year", "marketing_year",
            "area_planted_ha", "area_harvested_ha", "yield_t_ha", "production_mt",
            "area_planted_cv_pct", "area_harvested_cv_pct", "yield_cv_pct", "production_cv_pct",
            "source",
        ]

    def test_every_row_carries_a_stamp_parse_coverage(self) -> None:
        """PARSE COVERAGE: the anchor is a pure function of the crop year, which is non-null by
        construction (coerced + dropna'd before the pivot), so coverage is total -- 14,631/14,631 on
        the live canonical parquet, and 100% on every fixture here."""
        rows = [
            *_corn_rows(),
            *_corn_rows(state_alpha="IL"),
            *_corn_rows(commodity_desc="SOYBEANS", year=1924),
            *_corn_rows(agg_level_desc="NATIONAL", state_alpha=None, year=1866),
        ]
        silver = transform_nass_annual_bronze_to_silver(pd.DataFrame(rows))
        assert len(silver) == 4
        assert silver["release_date"].notna().all()
        assert (silver["release_date"] != "").all()
        assert silver["release_date"].map(lambda s: isinstance(s, str)).all()

    def test_stamp_is_february_first_of_the_year_after_the_crop_year(self) -> None:
        """USDA publishes the Crop Production ANNUAL SUMMARY for crop year Y in the second week of
        JANUARY of Y+1; the stamp is the first of the month STRICTLY AFTER that window."""
        silver = transform_nass_annual_bronze_to_silver(pd.DataFrame(_corn_rows(year=2025)))
        assert silver.iloc[0]["release_date"] == "2026-02-01"
        assert _release_date(1866) == "1867-02-01"
        assert _release_date(2026) == "2027-02-01"
        assert _release_date("2024") == "2025-02-01"      # str crop years derive identically

    @pytest.mark.parametrize("crop_year", [1866, 1895, 1924, 1990, 2024, 2025, 2026])
    def test_stamp_never_leaks_and_withholds_by_at_most_three_weeks(self, crop_year: int) -> None:
        """The ONE property that makes this leakage-safe: the derived date is always ON OR AFTER the
        real release (never before => zero leak), and never more than ~3 weeks after it (the real
        summary lands in the second week of January of Y+1, so Feb 1 is <= 25 days later)."""
        import datetime as _dt

        stamp = _dt.date.fromisoformat(_release_date(crop_year))
        real_release_window_end = _dt.date(crop_year + 1, 1, 15)   # NASS: second week of January
        assert stamp >= real_release_window_end                    # ZERO leak
        assert (stamp - real_release_window_end).days <= 25        # bounded withhold
        assert stamp > _dt.date(crop_year, 12, 31)                 # strictly after the crop year

    def test_stamps_are_monotone_in_crop_year_so_knowledge_desc_agrees_with_year_desc(self) -> None:
        """The latest-vintage ROW_NUMBER collapse orders by knowledge_date DESC; on this card that
        must agree with crop-year DESC or the newest crop year would not win its own grain."""
        stamps = [_release_date(y) for y in range(1866, 2036)]
        assert stamps == sorted(stamps)
        assert len(set(stamps)) == len(stamps)

    def test_stamp_is_deterministic_across_re_runs(self) -> None:
        """write_mode overwrite re-derives all 593 objects every weekly run; a non-deterministic
        stamp (e.g. anything reading the clock) would rewrite byte-identical data every Tuesday."""
        frame = pd.DataFrame(_corn_rows())
        first = transform_nass_annual_bronze_to_silver(frame)
        second = transform_nass_annual_bronze_to_silver(frame)
        pd.testing.assert_frame_equal(first, second)

    def test_null_crop_year_fails_loud_rather_than_stamping_null(self) -> None:
        """A null PIT anchor is worse than a crash: `null <= asof` is UNKNOWN in SQL, so the row
        would silently vanish from every as-of read instead of failing the run."""
        with pytest.raises(ValueError, match="null crop year"):
            _release_date(None)
        with pytest.raises(ValueError, match="null crop year"):
            _release_date(float("nan"))
        with pytest.raises(ValueError, match="not an integer"):
            _release_date("not-a-year")

    def test_empty_output_frame_still_declares_the_column(self) -> None:
        """The empty-slice path must carry the same 15-column shape, or a partition whose bronze
        yields nothing would concat into a ragged frame."""
        empty = transform_nass_annual_bronze_to_silver(
            pd.DataFrame(_corn_rows(commodity_desc="WHEAT", class_desc="ALL CLASSES"))
        )
        assert empty.empty
        assert list(empty.columns) == OUTPUT_COLUMNS

    def test_no_regression_the_measured_columns_are_untouched(self) -> None:
        """NO-REGRESSION: the anchor is a TIMING column only -- it never touches a measured value."""
        silver = transform_nass_annual_bronze_to_silver(pd.DataFrame(_corn_rows()))
        row = silver.iloc[0]
        assert list(silver.columns) == OUTPUT_COLUMNS
        assert row["area_planted_ha"] == pytest.approx(100.0 * ACRE_TO_HA)
        assert row["area_harvested_ha"] == pytest.approx(90.0 * ACRE_TO_HA)
        assert row["yield_t_ha"] == pytest.approx(180.0 * 56.0 * LB_PER_ACRE_TO_T_HA)
        assert row["production_mt"] == pytest.approx(16_200.0 * 56.0 * LB_TO_MT)
        assert row["marketing_year"] == 2024 and row["year"] == 2024
        assert row["source"] == "usda_nass" and row["country"] == "united_states"
