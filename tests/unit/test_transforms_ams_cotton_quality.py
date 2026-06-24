from __future__ import annotations

import pandas as pd
import pytest

from leviathan.transforms.bronze_to_silver.usda_ams_cotton_quality import (
    transform_ams_cotton_quality_bronze_to_silver,
)
from leviathan.transforms.raw_to_bronze.usda_ams_cotton_quality import (
    extract_metrics_from_text,
)


def test_extract_metrics_from_text_conservatively_finds_annual_quality_values() -> None:
    text = """
    United States Cotton Quality
    Percent Tenderable 82.5
    Samples Classed 1,234,567
    Average Staple 36.2
    Average Micronaire 4.4
    Average Strength 30.1
    """
    rows = extract_metrics_from_text(
        text,
        season=2024,
        source_page=3,
        source_raw_key="raw.pdf",
        source_file_etag="etag",
    )
    metrics = {row["metric"]: row["value"] for row in rows}
    assert metrics["percent_tenderable"] == 82.5
    assert metrics["samples_classed"] == 1234567.0
    assert metrics["avg_staple"] == 36.2
    assert metrics["avg_micronaire"] == 4.4
    assert metrics["avg_strength"] == 30.1
    assert {row["geography"] for row in rows} == {"unknown"}
    assert {row["extraction_scope"] for row in rows} == {"raw_match"}


def test_ams_cotton_silver_pivots_metrics() -> None:
    bronze = pd.DataFrame([
        {"season": 2024, "geography": "us_total", "metric": "percent_tenderable", "value": 82.5, "source_page": 3, "source_raw_key": "raw.pdf", "source_file_etag": "etag"},
        {"season": 2024, "geography": "us_total", "metric": "samples_classed", "value": 123.0, "source_page": 3, "source_raw_key": "raw.pdf", "source_file_etag": "etag"},
    ])
    out = transform_ams_cotton_quality_bronze_to_silver(bronze)
    assert len(out) == 1
    assert out.iloc[0]["commodity"] == "cotton"
    assert out.iloc[0]["percent_tenderable"] == 82.5
    assert out.iloc[0]["samples_classed"] == 123.0
    assert out.iloc[0]["source_pages"] == "3"


def test_ams_cotton_silver_uses_only_tagged_national_rows() -> None:
    bronze = pd.DataFrame([
        {"season": 2024, "geography": "us_total", "extraction_scope": "national_summary", "metric": "percent_tenderable", "value": 82.5, "source_page": 3},
        {"season": 2024, "geography": "unknown", "extraction_scope": "regional_or_appendix", "metric": "percent_tenderable", "value": 65.0, "source_page": 9},
        {"season": 2024, "geography": "us_total", "extraction_scope": "national_summary", "metric": "samples_classed", "value": 123.0, "source_page": 3},
    ])
    out = transform_ams_cotton_quality_bronze_to_silver(bronze)
    assert len(out) == 1
    assert out.iloc[0]["percent_tenderable"] == 82.5
    assert out.iloc[0]["samples_classed"] == 123.0


def test_ams_cotton_silver_derives_national_rows_from_legacy_bronze() -> None:
    bronze = pd.DataFrame([
        {"season": 1986, "geography": "us_total", "metric": "avg_staple", "value": 34.6, "source_page": 1},
        {"season": 1986, "geography": "us_total", "metric": "percent_tenderable", "value": 44.1, "source_page": 2},
        {"season": 1986, "geography": "us_total", "metric": "percent_tenderable", "value": 56.5, "source_page": 3},
        {"season": 1986, "geography": "us_total", "metric": "percent_tenderable", "value": 26.6, "source_page": 7},
    ])
    out = transform_ams_cotton_quality_bronze_to_silver(bronze)
    assert len(out) == 1
    assert out.iloc[0]["avg_staple"] == 34.6
    assert out.iloc[0]["percent_tenderable"] == 44.1
    assert out.iloc[0]["source_pages"] == "1,2"


def test_ams_cotton_silver_conflicting_duplicate_metric_raises() -> None:
    bronze = pd.DataFrame([
        {"season": 2024, "geography": "us_total", "extraction_scope": "national_summary", "metric": "percent_tenderable", "value": 82.5, "source_page": 3},
        {"season": 2024, "geography": "us_total", "extraction_scope": "national_narrative", "metric": "percent_tenderable", "value": 83.0, "source_page": 4},
    ])
    with pytest.raises(ValueError, match="conflicting duplicate"):
        transform_ams_cotton_quality_bronze_to_silver(bronze)
