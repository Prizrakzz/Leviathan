"""Unit tests for USDA NASS crop-progress bronze -> silver transform."""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from leviathan.transforms.bronze_to_silver.usda_nass_crop_progress import (
    OUTPUT_COLUMNS,
    transform_nass_crop_progress_bronze_to_silver,
)


def _row(
    *,
    commodity_desc: str = "CORN",
    class_desc: str = "ALL CLASSES",
    statisticcat_desc: str = "PROGRESS",
    unit_desc: str,
    value: float,
    agg_level_desc: str = "STATE",
    state_alpha: str | None = "IA",
    year: int = 2024,
    week_ending: str = "2024-04-07",
    source_desc: str = "SURVEY",
    prodn_practice_desc: str = "ALL PRODUCTION PRACTICES",
    util_practice_desc: str = "ALL UTILIZATION PRACTICES",
) -> dict[str, object]:
    return {
        "leviathan_slug": "legacy_bronze_slug",
        "source_desc": source_desc,
        "commodity_desc": commodity_desc,
        "class_desc": class_desc,
        "prodn_practice_desc": prodn_practice_desc,
        "util_practice_desc": util_practice_desc,
        "domain_desc": "TOTAL",
        "domaincat_desc": "NOT SPECIFIED",
        "short_desc": f"{commodity_desc} - {unit_desc}",
        "statisticcat_desc": statisticcat_desc,
        "unit_desc": unit_desc,
        "agg_level_desc": agg_level_desc,
        "state_alpha": state_alpha,
        "state_name": "IOWA",
        "year": year,
        "week_ending": week_ending,
        "value": value,
        "download_date": "2026-05-20",
        "source": "usda_nass",
    }


class TestNassCropProgressSilverTransform:
    def test_outputs_expected_columns_and_date_fields(self) -> None:
        silver = transform_nass_crop_progress_bronze_to_silver(
            pd.DataFrame([_row(unit_desc="PCT PLANTED", value=2.0)])
        )
        assert list(silver.columns) == OUTPUT_COLUMNS
        assert len(silver) == 1
        row = silver.iloc[0]
        assert row["date"] == date(2024, 4, 7)
        assert row["week_of_year"] == 14

    def test_normalizes_national_and_state_rows(self) -> None:
        rows = [
            _row(unit_desc="PCT PLANTED", value=2.0, state_alpha="IA"),
            _row(
                unit_desc="PCT PLANTED",
                value=3.0,
                agg_level_desc="NATIONAL",
                state_alpha=None,
            ),
        ]
        silver = transform_nass_crop_progress_bronze_to_silver(pd.DataFrame(rows))
        assert set(silver["state"]) == {"IA", "US"}

    def test_canonical_crop_filtering_and_slug_remapping(self) -> None:
        rows = [
            _row(commodity_desc="CORN", class_desc="ALL CLASSES", unit_desc="PCT PLANTED", value=1.0),
            _row(commodity_desc="SOYBEANS", class_desc="ALL CLASSES", unit_desc="PCT PLANTED", value=2.0),
            _row(commodity_desc="RICE", class_desc="ALL CLASSES", unit_desc="PCT PLANTED", value=3.0),
            _row(commodity_desc="COTTON", class_desc="UPLAND", unit_desc="PCT PLANTED", value=4.0),
        ]
        silver = transform_nass_crop_progress_bronze_to_silver(pd.DataFrame(rows))
        assert set(silver["leviathan_slug"]) == {
            "corn_cbot",
            "soybeans_cbot",
            "rough_rice_cbot",
            "cotton",
        }

    def test_winter_and_spring_wheat_split(self) -> None:
        rows = [
            _row(
                commodity_desc="WHEAT",
                class_desc="WINTER",
                unit_desc="PCT PLANTED",
                value=1.0,
            ),
            _row(
                commodity_desc="WHEAT",
                class_desc="SPRING, (EXCL DURUM)",
                unit_desc="PCT PLANTED",
                value=2.0,
                state_alpha="ND",
            ),
        ]
        silver = transform_nass_crop_progress_bronze_to_silver(pd.DataFrame(rows))
        assert set(silver["leviathan_slug"]) == {
            "soft_red_winter_wheat_cbot",
            "hard_red_spring_wheat_mgex",
        }

    def test_excludes_proxy_and_non_canonical_classes(self) -> None:
        rows = [
            _row(commodity_desc="OATS", class_desc="ALL CLASSES", unit_desc="PCT PLANTED", value=1.0),
            _row(commodity_desc="BARLEY", class_desc="ALL CLASSES", unit_desc="PCT PLANTED", value=1.0),
            _row(commodity_desc="SORGHUM", class_desc="ALL CLASSES", unit_desc="PCT PLANTED", value=1.0),
            _row(commodity_desc="WHEAT", class_desc="SPRING, DURUM", unit_desc="PCT PLANTED", value=1.0),
            _row(commodity_desc="COTTON", class_desc="COTTONSEED", unit_desc="PCT PLANTED", value=1.0),
        ]
        silver = transform_nass_crop_progress_bronze_to_silver(pd.DataFrame(rows))
        assert silver.empty

    def test_condition_aggregation(self) -> None:
        rows = [
            _row(statisticcat_desc="CONDITION", unit_desc="PCT GOOD", value=52.0),
            _row(statisticcat_desc="CONDITION", unit_desc="PCT EXCELLENT", value=12.0),
            _row(statisticcat_desc="CONDITION", unit_desc="PCT POOR", value=8.0),
            _row(statisticcat_desc="CONDITION", unit_desc="PCT VERY POOR", value=2.0),
        ]
        silver = transform_nass_crop_progress_bronze_to_silver(pd.DataFrame(rows))
        row = silver.iloc[0]
        assert row["pct_good_excellent"] == pytest.approx(64.0)
        assert row["pct_poor_very_poor"] == pytest.approx(10.0)

    def test_condition_aggregate_is_null_when_component_missing(self) -> None:
        silver = transform_nass_crop_progress_bronze_to_silver(
            pd.DataFrame([
                _row(statisticcat_desc="CONDITION", unit_desc="PCT GOOD", value=52.0),
            ])
        )
        assert pd.isna(silver.iloc[0]["pct_good_excellent"])

    def test_progress_pivot(self) -> None:
        rows = [
            _row(unit_desc="PCT PLANTED", value=10.0),
            _row(unit_desc="PCT EMERGED", value=4.0),
            _row(unit_desc="PCT HARVESTED", value=1.0, util_practice_desc="GRAIN"),
        ]
        silver = transform_nass_crop_progress_bronze_to_silver(pd.DataFrame(rows))
        row = silver.iloc[0]
        assert row["pct_planted"] == pytest.approx(10.0)
        assert row["pct_emerged"] == pytest.approx(4.0)
        assert row["pct_harvested"] == pytest.approx(1.0)

    def test_corn_grain_harvest_preferred_over_silage_harvest(self) -> None:
        rows = [
            _row(unit_desc="PCT HARVESTED", value=42.0, util_practice_desc="GRAIN"),
            _row(unit_desc="PCT HARVESTED", value=5.0, util_practice_desc="SILAGE"),
        ]
        silver = transform_nass_crop_progress_bronze_to_silver(pd.DataFrame(rows))
        assert len(silver) == 1
        assert silver.iloc[0]["pct_harvested"] == pytest.approx(42.0)

    def test_conflicting_duplicate_metric_rows_raise(self) -> None:
        rows = [
            _row(unit_desc="PCT PLANTED", value=10.0),
            _row(unit_desc="PCT PLANTED", value=12.0),
        ]
        with pytest.raises(ValueError, match="conflicting duplicate metric rows"):
            transform_nass_crop_progress_bronze_to_silver(pd.DataFrame(rows))
