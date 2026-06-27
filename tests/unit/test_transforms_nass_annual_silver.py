"""Unit tests for USDA NASS annual bronze -> silver transform."""
from __future__ import annotations

import pandas as pd
import pytest

from leviathan.transforms.bronze_to_silver.usda_nass_annual import (
    ACRE_TO_HA,
    LB_PER_ACRE_TO_T_HA,
    LB_TO_MT,
    OUTPUT_COLUMNS,
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

    def test_excludes_non_all_class_rice_and_cottonseed_rows(self) -> None:
        rows = [
            _row(commodity_desc="RICE", statisticcat_desc="AREA PLANTED", unit_desc="ACRES", value=100.0),
            _row(commodity_desc="RICE", statisticcat_desc="AREA HARVESTED", unit_desc="ACRES", value=90.0),
            _row(commodity_desc="RICE", statisticcat_desc="YIELD", unit_desc="LB / ACRE", value=7_640.0),
            _row(commodity_desc="RICE", statisticcat_desc="PRODUCTION", unit_desc="CWT", value=6_876.0),
            _row(commodity_desc="RICE", class_desc="LONG GRAIN", statisticcat_desc="YIELD", unit_desc="LB / ACRE", value=7_670.0),
            _row(commodity_desc="COTTON", class_desc="COTTONSEED", statisticcat_desc="PRODUCTION", unit_desc="TONS", value=109_000.0),
        ]
        silver = transform_nass_annual_bronze_to_silver(pd.DataFrame(rows))
        assert len(silver) == 1
        assert silver.iloc[0]["leviathan_slug"] == "rough_rice_cbot"

    def test_excludes_aggregate_wheat(self) -> None:
        rows = _corn_rows(commodity_desc="WHEAT", class_desc="ALL CLASSES")
        silver = transform_nass_annual_bronze_to_silver(pd.DataFrame(rows))
        assert silver.empty

    def test_maps_contract_specific_winter_wheat_classes(self) -> None:
        rows = [
            *_corn_rows(commodity_desc="WHEAT, WINTER", class_desc="SOFT RED WINTER"),
            *_corn_rows(
                commodity_desc="WHEAT, WINTER",
                class_desc="HARD RED WINTER",
                state_alpha="KS",
            ),
        ]
        silver = transform_nass_annual_bronze_to_silver(pd.DataFrame(rows))
        assert set(silver["leviathan_slug"]) == {
            "soft_red_winter_wheat_cbot",
            "hard_red_winter_wheat_kcbt",
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
