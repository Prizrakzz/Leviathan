from __future__ import annotations

from pathlib import Path

import pytest

# The [eda] extra backs this suite (nbformat/nbclient/jsonschema/matplotlib/IPython ride the
# EDA image, not the base dev env). A dev env without the extra SKIPS loudly instead of
# breaking collection -- the pdfplumber/[batch] precedent (test_pdfpage.py).
for _mod in ("nbformat", "nbclient", "jsonschema", "matplotlib", "IPython"):
    pytest.importorskip(_mod, reason="[eda] extra not installed")

import pyarrow as pa
import pyarrow.parquet as pq

from leviathan.eda.cli import _attach_exact_source_aggregates
from leviathan.eda.inventory import SilverTable, inventory_table
from leviathan.eda.source_aggregates import build_exact_source_aggregates


def _weather_contract() -> dict:
    return {
        "table_name": "silver_demo_weather",
        "layer": "silver",
        "s3_bucket": "test-leviathan",
        "s3_prefix": "silver/demo_weather",
        "s3_root": "s3://test-leviathan/silver/demo_weather",
        "domain": "weather",
        "partition_mode": "projected",
        "partition_keys": [
            {"name": "commodity", "glue_type": "string", "projected": True},
            {"name": "country", "glue_type": "string", "projected": True},
            {"name": "region", "glue_type": "string", "projected": True},
            {"name": "year", "glue_type": "int", "projected": True},
            {"name": "month", "glue_type": "int", "projected": True},
        ],
        "physical_columns": [
            {"name": "date", "glue_type": "date"},
            {"name": "variable", "glue_type": "string"},
            {"name": "value", "glue_type": "double"},
        ],
        "natural_key": [
            "commodity",
            "country",
            "region",
            "year",
            "month",
            "date",
            "variable",
        ],
        "value_columns": ["value"],
        "fingerprint": {},
    }


def test_exact_source_aggregates_scan_every_row_and_build_weather_tables(
    tmp_path: Path,
) -> None:
    contract = _weather_contract()
    rows = [
        {
            "date": f"{year}-{month:02d}-{day:02d}",
            "variable": variable,
            "value": (
                None
                if (region, year, month, variable, day) == ("north", 2024, 1, "rain", 1)
                else float(year - 2020 + month + day + (10 if variable == "temp" else 0))
            ),
        }
        for region in ("north", "south")
        for year in (2023, 2024)
        for month in (1, 2)
        for variable in ("rain", "temp")
        for day in (1, 2)
    ]
    for region in ("north", "south"):
        for year in (2023, 2024):
            for month in (1, 2):
                selected = [
                    row
                    for index, row in enumerate(rows)
                    if index // 8 == ((0 if region == "north" else 2) + (year - 2023))
                    and ((index // 4) % 2) + 1 == month
                ]
                target = (
                    tmp_path
                    / "silver/demo_weather"
                    / "commodity=cocoa"
                    / "country=GH"
                    / f"region={region}"
                    / f"year={year}"
                    / f"month={month}"
                    / "part.parquet"
                )
                target.parent.mkdir(parents=True, exist_ok=True)
                pq.write_table(pa.Table.from_pylist(selected), target, row_group_size=3)

    inventory = inventory_table(SilverTable("silver_demo_weather", contract), local_root=tmp_path)
    result = build_exact_source_aggregates(
        inventory,
        contract,
        {
            "observation_time_candidates": ["date"],
            "entity_columns": ["commodity", "country", "region"],
            "primary_measures": ["value"],
        },
        local_root=tmp_path,
        batch_size=2,
    )

    assert result["exactness"] == "exact"
    assert result["source_shape"] == [32, 8]
    assert result["source_object_count"] == 8
    assert result["column_statistics"]["value"]["null_count"] == 1
    assert result["column_statistics"]["value"]["finite_count"] == 31
    assert result["entity_coverage"]["region"]["distinct_count"] == 2
    assert result["time_coverage"] == {
        "column": "date",
        "min": "2023-01-01",
        "max": "2024-02-02",
    }
    by_year = result["chart_tables"]["rows_by_year"]
    assert by_year["records"] == [
        {"rows": 16, "year": 2023},
        {"rows": 16, "year": 2024},
    ]
    assert by_year["latest_period"] == {
        "status": "partial_through_latest_source_date",
        "through_date": "2024-02-02",
        "year": 2024,
    }
    assert "2024 partial through 2024-02-02" in by_year["title"]
    climatology = result["chart_tables"]["monthly_climatology__value"]
    assert climatology["row_count"] == 4
    assert {row["series"] for row in climatology["records"]} == {"rain", "temp"}
    assert climatology["scope"]["source_rows"] == 32
    anomaly_tables = {
        key: value
        for key, value in result["chart_tables"].items()
        if key.startswith("regional_anomaly__value__")
    }
    assert set(anomaly_tables) == {
        "regional_anomaly__value__rain",
        "regional_anomaly__value__temp",
    }
    for table in anomaly_tables.values():
        assert table["kind"] == "heatmap"
        assert table["value"] == "anomaly_z"
        assert table["scope"]["source_rows"] == 32
        assert {row["region"] for row in table["records"]} == {"north", "south"}
        assert {row["year"] for row in table["records"]} == {2023, 2024}
    assert len(result["aggregate_sha256"]) == 64


def test_exact_source_aggregates_support_compacted_hybrid_weather_layout(
    tmp_path: Path,
) -> None:
    contract = _weather_contract()
    contract["table_name"] = "silver_chirps"
    target = tmp_path / "silver/demo_weather" / "commodity=cocoa" / "year=2024" / "part.parquet"
    target.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.table(
            {
                "date": ["2024-01-01", "2024-01-02", "2024-02-01", "2024-02-02"],
                "variable": ["precipitation_mm"] * 4,
                "value": [1.0, 2.0, 3.0, 4.0],
                "country": ["GH", "GH", "GH", "GH"],
                "region": ["ashanti", "ashanti", "western", "western"],
                "month": [1, 1, 2, 2],
            }
        ),
        target,
        row_group_size=2,
    )
    inventory = inventory_table(
        SilverTable("silver_chirps", contract),
        local_root=tmp_path,
    )
    assert inventory.objects[0].partition_values == {
        "commodity": "cocoa",
        "year": "2024",
    }

    result = build_exact_source_aggregates(
        inventory,
        contract,
        {
            "observation_time_candidates": ["date"],
            "entity_columns": ["commodity", "country", "region"],
            "primary_measures": ["value"],
        },
        local_root=tmp_path,
        batch_size=2,
    )

    assert result["source_shape"] == [4, 8]
    assert result["source_object_count"] == 1
    assert result["entity_coverage"]["country"]["top_values"] == [{"rows": 4, "value": "GH"}]
    assert result["entity_coverage"]["region"]["distinct_count"] == 2
    assert result["chart_tables"]["rows_by_year"]["records"] == [{"rows": 4, "year": 2024}]
    climatology = result["chart_tables"]["monthly_climatology__value"]
    assert climatology["title"] == "Monthly climatology: daily precipitation"
    assert climatology["unit"] == "millimetres"
    assert "mean of all finite daily precipitation" in climatology["aggregation"]


def test_nasa_exact_aggregates_combine_temperature_and_prioritize_coverage_anomaly(
    tmp_path: Path,
) -> None:
    measures = [
        "temperature_2m_mean_c",
        "temperature_2m_max_c",
        "temperature_2m_min_c",
        "precipitation_mm",
        "relative_humidity_2m_pct",
        "wind_speed_2m_m_s",
    ]
    contract = {
        "table_name": "silver_nasa_power",
        "layer": "silver",
        "s3_bucket": "test-leviathan",
        "s3_prefix": "silver/nasa_power",
        "s3_root": "s3://test-leviathan/silver/nasa_power",
        "domain": "weather",
        "partition_mode": "flat",
        "partition_keys": [],
        "physical_columns": [
            {"name": "date", "glue_type": "date"},
            {"name": "commodity", "glue_type": "string"},
            {"name": "country", "glue_type": "string"},
            {"name": "region", "glue_type": "string"},
            {"name": "year", "glue_type": "int"},
            {"name": "month", "glue_type": "int"},
            *({"name": name, "glue_type": "double"} for name in measures),
        ],
        "natural_key": ["commodity", "country", "region", "date"],
        "value_columns": measures,
        "fingerprint": {},
    }
    rows = []
    for region_index, region in enumerate(("north", "south")):
        for year in (2023, 2024):
            for month in range(1, 13):
                base = float(month + (year - 2023) * 2 + region_index)
                rows.append(
                    {
                        "date": f"{year}-{month:02d}-15",
                        "commodity": "cocoa",
                        "country": "GH",
                        "region": region,
                        "year": year,
                        "month": month,
                        "temperature_2m_mean_c": 20.0 + base,
                        "temperature_2m_max_c": 25.0 + base,
                        "temperature_2m_min_c": 15.0 + base,
                        "precipitation_mm": base,
                        "relative_humidity_2m_pct": 50.0 + base,
                        "wind_speed_2m_m_s": 1.0 + base / 10.0,
                    }
                )
    target = tmp_path / "silver/nasa_power/part.parquet"
    target.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), target, row_group_size=7)
    inventory = inventory_table(
        SilverTable("silver_nasa_power", contract),
        local_root=tmp_path,
    )

    result = build_exact_source_aggregates(
        inventory,
        contract,
        {
            "observation_time_candidates": ["date"],
            "entity_columns": ["commodity", "country", "region"],
            "primary_measures": measures,
            "units": {
                "temperature_2m_mean_c": "degrees Celsius",
                "temperature_2m_max_c": "degrees Celsius",
                "temperature_2m_min_c": "degrees Celsius",
                "precipitation_mm": "millimetres",
                "relative_humidity_2m_pct": "percent",
                "wind_speed_2m_m_s": "metres per second",
            },
        },
        local_root=tmp_path,
        batch_size=9,
    )

    combined = result["chart_tables"]["monthly_climatology__temperature_2m_bundle"]
    assert combined["row_count"] == 36
    assert combined["unit"] == "degrees Celsius"
    assert {record["series"] for record in combined["records"]} == {
        "Mean temperature",
        "Maximum temperature",
        "Minimum temperature",
    }
    first_six = result["chart_priority"][:6]
    assert first_six[0] == "rows_by_region_year"
    assert "monthly_climatology__temperature_2m_bundle" in first_six
    assert any(key.startswith("regional_anomaly__") for key in first_six)
    assert not any(
        key in first_six
        for key in {
            "monthly_climatology__temperature_2m_mean_c",
            "monthly_climatology__temperature_2m_max_c",
            "monthly_climatology__temperature_2m_min_c",
        }
    )


def test_exact_source_census_insight_uses_reader_insight_contract() -> None:
    reader = {
        "column_dictionary": [],
        "reader_insights": [
            {
                "insight_id": "existing",
                "kind": "coverage",
                "status": "evaluated",
            }
        ],
    }
    aggregates = {
        "aggregate_sha256": "a" * 64,
        "column_statistics": {},
        "source_shape": [123, 7],
        "time_coverage": {
            "column": "date",
            "min": "2020-01-01",
            "max": "2025-12-31",
        },
    }

    _attach_exact_source_aggregates(reader, aggregates)

    insight = reader["reader_insights"][0]
    assert insight["insight_id"] == "exact-source-census"
    assert insight["kind"] == "coverage"
    assert insight["status"] == "evaluated"
    assert insight["columns"] == []
    assert insight["references"]["statistics"] == [
        "source_aggregates.source_shape",
        "source_aggregates.time_coverage",
    ]
    assert insight["source_rows"] == 123
    assert insight["analysis_rows"] == 123
    assert insight["exactness"] == "exact"
    assert "no target relationship" in insight["caveat"]


def test_exact_source_aggregates_replace_sampled_weather_null_insight() -> None:
    source_rows = 6_992_403
    null_count = 1_263
    null_rate = null_count / source_rows
    reader = {
        "column_dictionary": [],
        "reader_insights": [
            {
                "analysis_rows": 1_000_000,
                "columns": ["precipitation_mm", "temperature_2m_mean_c"],
                "exactness": "sampled",
                "insight_id": "missingness_hotspots",
                "kind": "missingness",
                "references": {"charts": [], "statistics": ["column_dictionary"]},
                "source_rows": source_rows,
                "statement": "Sampled null statement.",
                "status": "evaluated",
            }
        ],
    }
    aggregates = {
        "aggregate_sha256": "b" * 64,
        "column_statistics": {
            "precipitation_mm": {
                "null_count": null_count,
                "null_rate": null_rate,
            },
            "temperature_2m_mean_c": {"null_count": 0, "null_rate": 0.0},
        },
        "source_shape": [source_rows, 12],
        "time_coverage": {},
    }

    _attach_exact_source_aggregates(reader, aggregates)

    insight = next(
        item for item in reader["reader_insights"]
        if item["insight_id"] == "missingness_hotspots"
    )
    assert insight["exactness"] == "exact"
    assert insight["analysis_rows"] == source_rows
    assert insight["caveat"].startswith("Full-source descriptive census")
    assert insight["evidence"]["highest_null_count"] == null_count
    assert insight["evidence"]["highest_null_rate"] == null_rate
    assert "1,263 of 6,992,403 rows (0.0181%, exact source census)" in insight["statement"]
    assert "0.0%" not in insight["statement"]
    assert "source_aggregates.column_statistics" in insight["references"]["statistics"]
