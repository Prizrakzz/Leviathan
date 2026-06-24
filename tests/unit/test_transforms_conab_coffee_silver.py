from __future__ import annotations

import pandas as pd
import pytest

from leviathan.transforms.bronze_to_silver.conab_coffee import (
    OUTPUT_COLUMNS,
    transform_conab_coffee_bronze_to_silver,
)


def _rows(survey: int, production: float, area: float = 100.0, yield_: float = 20.0):
    return [
        {
            "safra_year": 2025,
            "survey": survey,
            "commodity": "arabica_coffee",
            "sheet_name": "2 Cafe Arabica",
            "region": "BRASIL",
            "element": "production_thousand_bags",
            "value": production,
            "source_raw_key": f"raw/conab/survey={survey:02d}/file.xls",
            "source_file_etag": f"etag-{survey}",
        },
        {
            "safra_year": 2025,
            "survey": survey,
            "commodity": "arabica_coffee",
            "sheet_name": "2 Cafe Arabica",
            "region": "BRASIL",
            "element": "area_in_production_ha",
            "value": area,
            "source_raw_key": f"raw/conab/survey={survey:02d}/file.xls",
            "source_file_etag": f"etag-{survey}",
        },
        {
            "safra_year": 2025,
            "survey": survey,
            "commodity": "arabica_coffee",
            "sheet_name": "2 Cafe Arabica",
            "region": "BRASIL",
            "element": "yield_bags_per_ha",
            "value": yield_,
            "source_raw_key": f"raw/conab/survey={survey:02d}/file.xls",
            "source_file_etag": f"etag-{survey}",
        },
    ]


def test_conab_silver_pivots_and_computes_revisions() -> None:
    bronze = pd.DataFrame(_rows(1, 1000.0) + _rows(2, 1100.0, area=101.0, yield_=21.0))
    out = transform_conab_coffee_bronze_to_silver(bronze)
    assert list(out.columns) == OUTPUT_COLUMNS
    assert out["region"].unique().tolist() == ["brazil"]
    assert out["production_revision_thousand_bags"].tolist() == [0.0, 100.0]
    assert out["area_revision_ha"].tolist() == [0.0, 1.0]
    assert out["yield_revision_bags_per_ha"].tolist() == [0.0, 1.0]
    assert out["production_revision_pct"].iloc[1] == pytest.approx(0.1)
    assert out["production_revision_streak"].tolist() == [0, 1]
    assert out["is_repeated_survey"].tolist() == [False, False]


def test_conab_silver_marks_consecutive_identical_survey_tables() -> None:
    bronze = pd.DataFrame(_rows(1, 1000.0) + _rows(2, 1000.0))
    out = transform_conab_coffee_bronze_to_silver(bronze)
    repeated = out[out["survey_number"] == 2]
    assert repeated["is_repeated_survey"].eq(True).all()
    assert repeated["repeated_from_survey_number"].tolist() == [1]
    assert repeated["production_revision_thousand_bags"].tolist() == [0.0]


def test_conab_silver_blocks_non_consecutive_repeated_survey_tables() -> None:
    bronze = pd.DataFrame(
        _rows(1, 1000.0)
        + _rows(2, 1100.0)
        + _rows(3, 1000.0)
    )
    with pytest.raises(ValueError, match="non-consecutive repeated"):
        transform_conab_coffee_bronze_to_silver(bronze)


def test_conab_silver_excludes_total_area_and_tree_count_sheets() -> None:
    rows = _rows(1, 1000.0)
    rows.extend({**row, "sheet_name": "1 Cafe Total", "value": 9999.0} for row in _rows(1, 9999.0))
    rows.extend({**row, "sheet_name": "5 Cafe Arabica - Area", "value": 9999.0} for row in _rows(1, 9999.0))
    rows.extend({**row, "sheet_name": "8 Cafe Arabica - Cafeeiros", "value": 9999.0} for row in _rows(1, 9999.0))
    out = transform_conab_coffee_bronze_to_silver(pd.DataFrame(rows))
    assert len(out) == 1
    assert out.iloc[0]["worksheet"] == "2 Cafe Arabica"
    assert out.iloc[0]["production_thousand_bags"] == 1000.0


def test_conab_silver_rejects_conflicting_duplicate_values() -> None:
    rows = _rows(1, 1000.0)
    rows.append({**rows[0], "value": 1001.0})
    with pytest.raises(ValueError, match="conflicting duplicate"):
        transform_conab_coffee_bronze_to_silver(pd.DataFrame(rows))


def test_conab_silver_excludes_unknown_proxy_commodities() -> None:
    bronze = pd.DataFrame([{**row, "commodity": "total_coffee"} for row in _rows(1, 1000.0)])
    out = transform_conab_coffee_bronze_to_silver(bronze)
    assert out.empty
