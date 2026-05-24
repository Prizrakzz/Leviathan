"""Unit tests for leviathan.transforms.raw_to_bronze.faostat_qcl."""
from __future__ import annotations

import csv
import io
import zipfile
from pathlib import Path

import pandas as pd
import pytest

from leviathan.transforms.raw_to_bronze.faostat_qcl import (
    add_bronze_metadata,
    clean_basic_types,
    filter_by_fao_item,
    find_csv_inside_zip,
    normalize_columns,
    snake_case,
    transform_faostat_qcl_zip_to_bronze,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FAOSTAT_COLUMNS = ["Area", "Item", "Element", "Year", "Unit", "Value", "Flag"]


def _make_faostat_zip(tmp_path: Path, rows: list[dict[str, str | int]]) -> Path:
    """Create a ZIP file containing a single FAOSTAT-like CSV."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_FAOSTAT_COLUMNS)
    writer.writeheader()
    writer.writerows(rows)

    zip_path = tmp_path / "faostat.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("FAOSTAT_data.csv", buf.getvalue())
    return zip_path


_SAMPLE_ROWS = [
    {"Area": "Ghana", "Item": "Cocoa beans", "Element": "Production",
     "Year": 2020, "Unit": "t", "Value": 800000, "Flag": "A"},
    {"Area": "Ghana", "Item": "Cocoa beans", "Element": "Area harvested",
     "Year": 2020, "Unit": "ha", "Value": 900000, "Flag": "A"},
    {"Area": "Ghana", "Item": "Cocoa beans", "Element": "Yield",
     "Year": 2020, "Unit": "hg/ha", "Value": 8888, "Flag": "A"},
    # Row that should be filtered out (wrong item)
    {"Area": "Ghana", "Item": "Maize", "Element": "Production",
     "Year": 2020, "Unit": "t", "Value": 1000, "Flag": "A"},
]


# ---------------------------------------------------------------------------
# snake_case
# ---------------------------------------------------------------------------

class TestSnakeCase:
    def test_camel_case_split(self):
        # snake_case works on any non-alphanumeric boundary, not camelCase
        assert snake_case("ItemCode") == "itemcode"

    def test_spaces_replaced(self):
        assert snake_case("Area Harvested") == "area_harvested"

    def test_already_snake_case(self):
        assert snake_case("year") == "year"

    def test_strips_leading_trailing_underscores(self):
        assert snake_case("  Year  ") == "year"

    def test_multiple_spaces_become_single_underscore(self):
        assert snake_case("flag  description") == "flag_description"

    def test_special_chars_replaced(self):
        result = snake_case("Value (1000 US$)")
        assert " " not in result
        assert result == result.lower()


# ---------------------------------------------------------------------------
# find_csv_inside_zip
# ---------------------------------------------------------------------------

class TestFindCsvInsideZip:
    def test_returns_csv_filename_string(self, tmp_path):
        zip_path = tmp_path / "test.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("data.csv", "col1,col2\n1,2\n")
        result = find_csv_inside_zip(zip_path)
        assert result == "data.csv"
        assert isinstance(result, str)

    def test_raises_file_not_found_when_no_csv(self, tmp_path):
        zip_path = tmp_path / "empty.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("readme.txt", "no csv here")
        with pytest.raises(FileNotFoundError):
            find_csv_inside_zip(zip_path)

    def test_returns_first_csv_when_multiple(self, tmp_path):
        zip_path = tmp_path / "multi.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("first.csv", "a,b\n1,2")
            zf.writestr("second.csv", "c,d\n3,4")
        result = find_csv_inside_zip(zip_path)
        assert result.endswith(".csv")


# ---------------------------------------------------------------------------
# normalize_columns
# ---------------------------------------------------------------------------

class TestNormalizeColumns:
    def test_column_names_snake_cased(self):
        df = pd.DataFrame(columns=["Area", "Item", "Element", "Year", "Unit", "Value", "Flag"])
        result = normalize_columns(df)
        assert list(result.columns) == ["area", "item", "element", "year", "unit", "value", "flag"]

    def test_original_df_unchanged(self):
        df = pd.DataFrame({"Item Code": [1], "Area": ["Ghana"]})
        normalize_columns(df)
        assert "Item Code" in df.columns

    def test_returns_new_dataframe(self):
        df = pd.DataFrame({"Col A": [1]})
        result = normalize_columns(df)
        assert result is not df


# ---------------------------------------------------------------------------
# clean_basic_types
# ---------------------------------------------------------------------------

class TestCleanBasicTypes:
    def test_year_coerced_to_int64(self):
        df = pd.DataFrame({"year": ["2020", "2021"], "value": ["100", "200"]})
        result = clean_basic_types(df)
        assert pd.api.types.is_integer_dtype(result["year"])

    def test_value_coerced_to_float(self):
        df = pd.DataFrame({"year": [2020], "value": ["123.45"]})
        result = clean_basic_types(df)
        assert pd.api.types.is_float_dtype(result["value"])

    def test_non_numeric_value_becomes_nan(self):
        df = pd.DataFrame({"year": [2020], "value": ["n/a"]})
        result = clean_basic_types(df)
        assert pd.isna(result["value"].iloc[0])


# ---------------------------------------------------------------------------
# filter_by_fao_item
# ---------------------------------------------------------------------------

class TestFilterByFaoItem:
    def _make_df(self) -> pd.DataFrame:
        return pd.DataFrame({
            "item": ["Cocoa beans", "Cocoa beans", "Cocoa beans", "Maize"],
            "element": ["Production", "Area harvested", "Yield", "Production"],
            "year": [2020, 2020, 2020, 2020],
            "value": [800000, 900000, 8888, 1000],
        })

    def test_filters_to_matching_item_only(self):
        df = self._make_df()
        result = filter_by_fao_item(df, "Cocoa beans")
        assert all(result["item"] == "Cocoa beans")
        assert "Maize" not in result["item"].values

    def test_all_three_target_elements_kept(self):
        df = self._make_df()
        result = filter_by_fao_item(df, "Cocoa beans")
        elements = set(result["element"].str.lower())
        assert elements == {"production", "area harvested", "yield"}

    def test_case_insensitive_item_match(self):
        df = pd.DataFrame({
            "item": ["cocoa beans"],
            "element": ["production"],
            "value": [100],
        })
        result = filter_by_fao_item(df, "Cocoa Beans")
        assert len(result) == 1

    def test_empty_result_when_item_not_found(self):
        df = self._make_df()
        result = filter_by_fao_item(df, "Wheat")
        assert result.empty

    def test_raises_if_item_column_missing(self):
        df = pd.DataFrame({"element": ["Production"]})
        with pytest.raises(ValueError, match="Missing required FAOSTAT columns"):
            filter_by_fao_item(df, "Cocoa beans")


# ---------------------------------------------------------------------------
# transform_faostat_qcl_zip_to_bronze (end-to-end)
# ---------------------------------------------------------------------------

class TestTransformFaostatQclZipToBronze:
    def test_returns_list_of_paths(self, tmp_path):
        zip_path = _make_faostat_zip(tmp_path, _SAMPLE_ROWS)
        output_dir = tmp_path / "bronze"
        result = transform_faostat_qcl_zip_to_bronze(
            zip_path=zip_path,
            output_dir=output_dir,
            ingest_date="2024-01-01",
            commodity="cocoa",
            fao_item_name="Cocoa beans",
        )
        assert isinstance(result, list)
        assert all(isinstance(p, Path) for p in result)

    def test_parquet_files_created(self, tmp_path):
        zip_path = _make_faostat_zip(tmp_path, _SAMPLE_ROWS)
        output_dir = tmp_path / "bronze"
        paths = transform_faostat_qcl_zip_to_bronze(
            zip_path=zip_path,
            output_dir=output_dir,
            ingest_date="2024-01-01",
            commodity="cocoa",
            fao_item_name="Cocoa beans",
        )
        assert len(paths) >= 1
        for p in paths:
            assert p.exists()
            assert p.suffix == ".parquet"

    def test_output_partitioned_by_year(self, tmp_path):
        zip_path = _make_faostat_zip(tmp_path, _SAMPLE_ROWS)
        output_dir = tmp_path / "bronze"
        paths = transform_faostat_qcl_zip_to_bronze(
            zip_path=zip_path,
            output_dir=output_dir,
            ingest_date="2024-01-01",
            commodity="cocoa",
            fao_item_name="Cocoa beans",
        )
        assert any("year=2020" in str(p) for p in paths)

    def test_bronze_metadata_columns_present(self, tmp_path):
        zip_path = _make_faostat_zip(tmp_path, _SAMPLE_ROWS)
        output_dir = tmp_path / "bronze"
        paths = transform_faostat_qcl_zip_to_bronze(
            zip_path=zip_path,
            output_dir=output_dir,
            ingest_date="2024-01-01",
            commodity="cocoa",
            fao_item_name="Cocoa beans",
        )
        df = pd.read_parquet(paths[0])
        for col in ("source", "dataset", "commodity", "ingest_date", "source_file_name"):
            assert col in df.columns, f"Missing column: {col}"

    def test_wrong_item_raises_value_error(self, tmp_path):
        zip_path = _make_faostat_zip(tmp_path, _SAMPLE_ROWS)
        with pytest.raises(ValueError, match="No rows found"):
            transform_faostat_qcl_zip_to_bronze(
                zip_path=zip_path,
                output_dir=tmp_path / "bronze",
                ingest_date="2024-01-01",
                commodity="wheat",
                fao_item_name="Wheat",
            )

    def test_missing_zip_raises_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            transform_faostat_qcl_zip_to_bronze(
                zip_path=tmp_path / "nonexistent.zip",
                output_dir=tmp_path / "bronze",
                ingest_date="2024-01-01",
                commodity="cocoa",
                fao_item_name="Cocoa beans",
            )

    def test_maize_rows_excluded(self, tmp_path):
        zip_path = _make_faostat_zip(tmp_path, _SAMPLE_ROWS)
        output_dir = tmp_path / "bronze"
        paths = transform_faostat_qcl_zip_to_bronze(
            zip_path=zip_path,
            output_dir=output_dir,
            ingest_date="2024-01-01",
            commodity="cocoa",
            fao_item_name="Cocoa beans",
        )
        df = pd.read_parquet(paths[0])
        assert "Maize" not in df["item"].values
