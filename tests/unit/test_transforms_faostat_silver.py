"""Unit tests for leviathan.transforms.bronze_to_silver.faostat_production (SILVER-F022).

The canonical ``silver_production`` body is the 12 registry physical columns -- commodity and year
are the projected partition keys (path-carried), never in the parquet body; ``variable`` is renamed
to ``metric``; ``country`` is the DISPLAY country + ``country_key`` the governed key.

FAO-6 adds the observation-flag half: ``is_official`` is derived from the release's OWN legend and an
unrecognised flag fails CLOSED. The legend is pinned against the ZIP that ships it, so a FAO scheme
change breaks the pin instead of silently re-inverting the column.
"""
from __future__ import annotations

import csv
import io
import zipfile
from pathlib import Path

import pandas as pd
import pytest
from leviathan.transforms.bronze_to_silver.faostat_production import (
    CANONICAL_PHYSICAL_COLUMNS,
    FLAG_SEMANTICS,
    NO_VALUE_FLAGS,
    OFFICIAL_FLAGS,
    FaostatMappingError,
    SilverProductionLayoutError,
    assert_canonical_production_key,
    transform_faostat_production_silver_df,
)

EXPECTED_COLS = set(CANONICAL_PHYSICAL_COLUMNS)

# The raw QCL bulk ZIP is a TRACKED repo artifact; the legend member inside it is ~170 bytes, so
# reading it costs nothing. skipif (not xfail) because its absence means a sparse/partial checkout,
# which is an environment fact, not a defect in the code under test.
_QCL_ZIP = Path(__file__).resolve().parents[2] / (
    "data/raw/production/faostat/qcl/Production_Crops_Livestock_E_All_Data_(Normalized).zip"
)
_FLAGS_MEMBER = "Production_Crops_Livestock_E_Flags.csv"
_needs_zip = pytest.mark.skipif(not _QCL_ZIP.exists(), reason=f"raw QCL ZIP not checked out: {_QCL_ZIP}")


@_needs_zip
def test_flag_semantics_match_the_release_legend():
    """DOCUMENTATION WITH A TEST: FLAG_SEMANTICS is the ZIP's own Flags.csv, verbatim. The legend and
    the data are ONE artefact, so the scheme can never be read off a stale doc -- and a FAO legend
    change lands here as a red test rather than as an inverted is_official column."""
    with zipfile.ZipFile(_QCL_ZIP) as z:
        rows = list(csv.reader(io.StringIO(z.read(_FLAGS_MEMBER).decode("utf-8-sig"))))
    legend = {r[0].strip(): r[1].strip() for r in rows[1:] if len(r) >= 2 and r[0].strip()}
    assert legend == FLAG_SEMANTICS
    assert OFFICIAL_FLAGS == {"A"} and legend["A"] == "Official figure"
    assert NO_VALUE_FLAGS == {"M"} and legend["M"].startswith("Missing value")
    # the four PRE-2022 keys the old NON_OFFICIAL_FLAGS set targeted are simply gone from the legend
    assert not ({"F", "Fc", "Im", "*"} & set(legend))


class TestTransformFaostatProductionSilverDf:
    def test_returns_list_of_year_df_tuples(self, faostat_bronze_df):
        result = transform_faostat_production_silver_df(faostat_bronze_df, commodity="cocoa")
        assert isinstance(result, list) and len(result) > 0
        for year, df in result:
            assert isinstance(year, int)
            assert isinstance(df, pd.DataFrame)

    def test_body_is_exactly_the_12_canonical_columns(self, faostat_bronze_df):
        _, df = transform_faostat_production_silver_df(faostat_bronze_df, commodity="cocoa")[0]
        assert list(df.columns) == CANONICAL_PHYSICAL_COLUMNS   # exact order (INV-2 writer schema)
        # commodity + year are partition keys -> NEVER in the body.
        assert "commodity" not in df.columns
        assert "year" not in df.columns

    def test_uses_metric_not_variable(self, faostat_bronze_df):
        _, df = transform_faostat_production_silver_df(faostat_bronze_df, commodity="cocoa")[0]
        assert "metric" in df.columns
        assert "variable" not in df.columns

    def test_preserves_display_country_and_derives_key(self):
        df = pd.DataFrame({
            "area": ["Cote d'Ivoire"], "item": ["Cocoa beans"], "element": ["Production"],
            "year": [2020], "unit": ["tonnes"], "value": [1.5e6], "flag": [""],
            "ingest_date": ["2024-01-01"],
        })
        _, silver = transform_faostat_production_silver_df(df, commodity="cocoa")[0]
        assert silver["country"].iloc[0] == "Cote d'Ivoire"          # display preserved
        assert silver["country_key"].iloc[0] == "cote_divoire"        # governed key derived

    def test_metric_mapping_capitalizes_and_maps(self):
        df = pd.DataFrame({
            "area": ["Ghana"], "item": ["Cocoa beans"], "element": ["PRODUCTION"],
            "year": [2020], "unit": ["tonnes"], "value": [9e5], "flag": ["A"],
            "ingest_date": ["2024-01-01"],
        })
        _, silver = transform_faostat_production_silver_df(df, commodity="cocoa")[0]
        assert (silver["metric"] == "production_quantity").all()

    def test_provenance_columns_defaulted(self, faostat_bronze_df):
        _, df = transform_faostat_production_silver_df(faostat_bronze_df, commodity="cocoa")[0]
        assert (df["source"] == "faostat").all()
        assert (df["dataset"] == "QCL").all()
        assert df["note"].isna().all()
        assert df["source_file_name"].isna().all()

    def test_is_official_flag_logic(self, faostat_bronze_df):
        """FAO-6: ``A`` is FAO's "Official figure". This pin previously asserted the OPPOSITE -- it was
        written against the PRE-2022 legend, in which the estate's flag set read A as non-official, and
        the release switched schemes underneath it. The old pin was wrong by schema drift, not by
        intent; the legend member shipped inside the QCL ZIP is the authority (see
        :func:`test_flag_semantics_match_the_release_legend`)."""
        _, df = transform_faostat_production_silver_df(faostat_bronze_df, commodity="cocoa")[0]
        flag_a_rows = df[df["flag"] == "A"]
        assert not flag_a_rows.empty
        assert flag_a_rows["is_official"].all()

    @pytest.mark.parametrize("flag", ["E", "I", "X", "M"])
    def test_non_official_flag_marked_correctly(self, flag):
        df = pd.DataFrame({
            "area": ["Ghana"], "item": ["Cocoa beans"], "element": ["Production"],
            "year": [2020], "unit": ["tonnes"], "value": [9e5], "flag": [flag],
            "ingest_date": ["2024-01-01"],
        })
        _, silver = transform_faostat_production_silver_df(df, commodity="cocoa")[0]
        assert not silver["is_official"].iloc[0]

    def test_missing_flag_drops_the_value(self):
        """``M`` == "Missing value; data cannot exist". THIS IS THE FORWARD GUARD, exercised on a frame
        the current vintage never emits (measured: all 94,355 live M rows print an EMPTY Value cell, so
        blanking moves zero rows today -- the Lane-4 review pinned that fact). If a future vintage
        prints a number beside M, it must be neither official NOR a value: the number goes, the flag
        stays as the reason."""
        df = pd.DataFrame({
            "area": ["Ghana", "Ghana"], "item": ["Cocoa beans"] * 2,
            "element": ["Production", "Area harvested"], "year": [2020, 2020],
            "unit": ["tonnes", "ha"], "value": [0.0, 1.0e6], "flag": ["M", "A"],
            "ingest_date": ["2024-01-01"] * 2,
        })
        _, silver = transform_faostat_production_silver_df(df, commodity="cocoa")[0]
        by_flag = silver.set_index("flag")
        assert pd.isna(by_flag.loc["M", "value"])          # the "cannot exist" zero never reaches serving
        assert by_flag.loc["A", "value"] == 1.0e6          # every other row is untouched
        assert pd.api.types.is_numeric_dtype(silver["value"])

    def test_a_numeric_m_row_still_collides_before_it_is_blanked(self):
        """ORDER IS THE FENCE (Lane-4 review, minor 1): blanking M BEFORE duplicate resolution would
        drop its number out of the conflict test (which ignores NaN), and keep="last" could then
        silently publish the blanked M row over a real official figure. Blanking runs AFTER the
        resolver, so a numeric M cell sharing a natural key with a disagreeing sibling RAISES --
        "never a silent last-wins", preserved by ordering."""
        df = pd.DataFrame({
            "area": ["Ghana", "Ghana"], "item": ["Cocoa beans"] * 2,
            "element": ["Production", "Production"], "year": [2020, 2020],
            "unit": ["tonnes", "tonnes"], "value": [123.0, 1.0e6], "flag": ["M", "A"],
            "ingest_date": ["2024-01-01"] * 2,
        })
        with pytest.raises(FaostatMappingError, match="conflicting duplicate"):
            transform_faostat_production_silver_df(df, commodity="cocoa")

    def test_blank_flag_is_not_official_but_keeps_its_value(self):
        """An ABSENT flag is an absence of an officiality ASSERTION, not a scheme change -- so it reads
        not-official (the only direction that cannot manufacture officialness) and keeps its number."""
        df = pd.DataFrame({
            "area": ["Ghana"], "item": ["Cocoa beans"], "element": ["Production"],
            "year": [2020], "unit": ["tonnes"], "value": [9e5], "flag": [""],
            "ingest_date": ["2024-01-01"],
        })
        _, silver = transform_faostat_production_silver_df(df, commodity="cocoa")[0]
        assert not silver["is_official"].iloc[0]
        assert silver["value"].iloc[0] == 9e5

    def test_unrecognised_flag_fails_closed(self):
        """A PRESENT flag outside the legend is a legend change, and publishing an is_official nobody
        has read is the failure this replaces. The four dead pre-2022 keys reach this branch."""
        df = pd.DataFrame({
            "area": ["Ghana"], "item": ["Cocoa beans"], "element": ["Production"],
            "year": [2020], "unit": ["tonnes"], "value": [9e5], "flag": ["Fc"],
            "ingest_date": ["2024-01-01"],
        })
        with pytest.raises(FaostatMappingError, match="absent from the release legend"):
            transform_faostat_production_silver_df(df, commodity="cocoa")

    def test_partition_years_are_ints(self, faostat_bronze_df):
        result = transform_faostat_production_silver_df(faostat_bronze_df, commodity="cocoa")
        assert all(isinstance(y, int) for y, _ in result)

    def test_missing_required_column_raises(self):
        with pytest.raises(ValueError, match="Missing required FAOSTAT bronze columns"):
            transform_faostat_production_silver_df(
                pd.DataFrame({"area": ["Ghana"], "year": [2020]}), commodity="cocoa"
            )

    def test_unknown_elements_are_dropped(self):
        df = pd.DataFrame({
            "area": ["Ghana"], "item": ["Cocoa beans"], "element": ["Some Unrecognized Element"],
            "year": [2020], "unit": ["tonnes"], "value": [1.0], "flag": ["A"],
            "ingest_date": ["2024-01-01"],
        })
        assert transform_faostat_production_silver_df(df, commodity="cocoa") == []

    def test_conflicting_duplicate_value_raises(self):
        df = pd.DataFrame({
            "area": ["Ghana", "Ghana"], "item": ["Cocoa beans", "Cocoa beans"],
            "element": ["Production", "Production"], "year": [2020, 2020],
            "unit": ["tonnes", "tonnes"], "value": [9e5, 8e5], "flag": ["", ""],
            "ingest_date": ["2024-01-01", "2024-01-01"],
        })
        with pytest.raises(FaostatMappingError, match="conflicting duplicate"):
            transform_faostat_production_silver_df(df, commodity="cocoa")

    def test_exact_duplicate_value_collapses(self):
        df = pd.DataFrame({
            "area": ["Ghana", "Ghana"], "item": ["Cocoa beans", "Cocoa beans"],
            "element": ["Production", "Production"], "year": [2020, 2020],
            "unit": ["tonnes", "tonnes"], "value": [9e5, 9e5], "flag": ["", ""],
            "ingest_date": ["2024-01-01", "2024-01-01"],
        })
        _, silver = transform_faostat_production_silver_df(df, commodity="cocoa")[0]
        assert len(silver) == 1


class TestCanonicalKeyGuard:
    def test_accepts_canonical_layout(self):
        key = "silver/production/commodity=cocoa/year=2020/part-000.parquet"
        assert assert_canonical_production_key(key) == key

    @pytest.mark.parametrize("bad", [
        "silver/production/source=faostat/commodity=cocoa/year=2020/part-000.parquet",
        "silver/production/year=2020/part-000.parquet",
        "silver/other/commodity=cocoa/year=2020/p.parquet",
    ])
    def test_refuses_non_canonical(self, bad):
        with pytest.raises(SilverProductionLayoutError):
            assert_canonical_production_key(bad)
