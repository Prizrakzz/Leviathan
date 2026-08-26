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
    _REFUSED_UNITS,
    CANONICAL_PHYSICAL_COLUMNS,
    ELEMENT_TO_METRIC,
    FLAG_SEMANTICS,
    HEAD_COUNT_METRICS,
    LIVESTOCK_METRICS,
    METRIC_UNITS,
    NO_VALUE_FLAGS,
    OFFICIAL_FLAGS,
    PER_ANIMAL_RATE_METRICS,
    TONNAGE_METRICS,
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


_ELEMENT_CODES_MEMBER = "Production_Crops_Livestock_E_Elements.csv"


def _row(**over) -> pd.DataFrame:
    base = {
        "area": ["Brazil"], "item": ["Cattle"], "element": ["Stocks"], "year": [2020],
        "unit": ["An"], "value": [2.2e8], "flag": ["A"], "ingest_date": ["2026-05-11"],
    }
    base.update({k: v for k, v in over.items()})
    return pd.DataFrame(base)


class TestTheElementMapCarriesTheLivestockFive:
    """FAO-2 (a). BOTH DIRECTIONS, because either direction alone hides a real failure: a key with
    no metric drops rows silently at `isin(ELEMENT_TO_METRIC)`, and a metric with no key is a card
    entry that returns zero rows and reads as 'not published'."""

    _LIVESTOCK = {
        "Stocks": "live_animals",
        "Milk Animals": "milk_animals",
        "Laying": "laying_birds",
        "Producing Animals/Slaughtered": "animals_producing_or_slaughtered",
        "Yield/Carcass Weight": "yield_per_animal",
    }
    _CROP = {"Area harvested": "area_harvested", "Production": "production_quantity",
             "Yield": "yield"}

    def test_the_map_is_exactly_the_crop_three_plus_the_livestock_five(self):
        assert ELEMENT_TO_METRIC == {**self._CROP, **self._LIVESTOCK}

    def test_the_crop_three_are_untouched_byte_for_byte(self):
        # A widening must never re-base a live series. silver_production is served TODAY off these
        # three metric strings; a rename here is a silent zero-row card.
        for element, metric in self._CROP.items():
            assert ELEMENT_TO_METRIC[element] == metric

    def test_every_metric_name_is_unique(self):
        assert len(set(ELEMENT_TO_METRIC.values())) == len(ELEMENT_TO_METRIC)

    def test_stocks_is_NOT_named_stocks(self):
        """The rename IS the fence. In this estate `stocks` means balance-sheet ENDING STOCKS in
        tonnes -- silver_psd carries exactly that for cattle_beef / hogs / broilers_poultry -- so a
        metric literally called `stocks` holding head of cattle would be read as ending stocks by
        every consumer that has read a PSD number."""
        assert ELEMENT_TO_METRIC["Stocks"] == "live_animals"
        assert "stocks" not in set(ELEMENT_TO_METRIC.values())

    # the unit the release actually prints for each element (census-measured), so the row under test
    # clears the unit fence for the reason it is governed and not by accident
    _UNIT = {"Stocks": "An", "Milk Animals": "An", "Laying": "1000 An",
             "Producing Animals/Slaughtered": "An", "Yield/Carcass Weight": "kg/An"}

    @pytest.mark.parametrize("element", list(_LIVESTOCK))
    def test_the_legend_string_resolves_case_insensitively(self, element):
        unit = self._UNIT[element]
        got = transform_faostat_production_silver_df(
            _row(element=[element], unit=[unit]), commodity="cattle_beef")
        assert got and got[0][1]["metric"].iloc[0] == self._LIVESTOCK[element]
        # and the same string lower-cased resolves too -- the fold is case-insensitive, not lossy
        got_lower = transform_faostat_production_silver_df(
            _row(element=[element.lower()], unit=[unit]), commodity="cattle_beef")
        assert got_lower and got_lower[0][1]["metric"].iloc[0] == self._LIVESTOCK[element]

    @pytest.mark.parametrize("element", ["Producing Animals/Slaughtered",
                                         "Yield/Carcass Weight", "Milk Animals"])
    def test_the_old_capitalize_fold_would_have_dropped_this_element(self, element):
        """THE NON-VACUOUS PIN ON THE REGRESSION THIS CHANGE FIXES. `str.capitalize()` lower-cases
        everything after the first character, so three of the five livestock elements folded to a
        string absent from the map and were dropped at `isin(...)` with no error and no warning. It
        was invisible for the crop half only because all three crop element strings happen to be
        capitalize-STABLE, which is exactly the coincidence that let a lossy fold sit in a validated
        map. Asserted in the failing direction so the fold cannot come back."""
        assert element.capitalize() != element
        assert element.capitalize() not in ELEMENT_TO_METRIC
        assert element in ELEMENT_TO_METRIC
        # ... and the three that hid it
        for crop in ("Area harvested", "Production", "Yield"):
            assert crop.capitalize() == crop

    @_needs_zip
    def test_the_map_keys_are_the_releases_own_element_strings(self):
        """The keys are the legend's, byte-for-byte -- the FLAG_SEMANTICS posture on the element
        axis. A legend rename lands here as a red test, not as a silently emptied metric."""
        with zipfile.ZipFile(_QCL_ZIP) as z:
            rows = list(csv.reader(io.StringIO(z.read(_ELEMENT_CODES_MEMBER).decode("utf-8-sig"))))
        legend = {r[1].strip() for r in rows[1:] if len(r) >= 2}
        assert set(ELEMENT_TO_METRIC) <= legend
        # the two the map leaves out are the two the release prints ZERO rows for; they are refused
        # by name in raw_to_bronze.faostat_qcl._REFUSED_LEGEND_ELEMENTS
        assert legend - set(ELEMENT_TO_METRIC) == {"Extraction Rate", "Prod Popultn"}


class TestTheUnitFence:
    """FAO-2 (c). ``unit`` is a free string, so nothing structural stops a head count from being
    published under a metric a consumer sums with tonnes. Measured figures cite
    ``data/dec_p0/faostat_livestock_census.json``."""

    def test_every_mapped_metric_declares_its_units(self):
        assert set(METRIC_UNITS) == set(ELEMENT_TO_METRIC.values())

    def test_the_narration_classes_partition_the_metric_set(self):
        crop = {"area_harvested", "yield"}
        classes = HEAD_COUNT_METRICS | TONNAGE_METRICS | PER_ANIMAL_RATE_METRICS | crop
        assert classes == set(METRIC_UNITS)
        # and they are disjoint -- a metric in two narration classes is a fence that cannot be read
        assert not (HEAD_COUNT_METRICS & TONNAGE_METRICS)
        assert not (HEAD_COUNT_METRICS & PER_ANIMAL_RATE_METRICS)
        assert not (TONNAGE_METRICS & PER_ANIMAL_RATE_METRICS)
        assert LIVESTOCK_METRICS == HEAD_COUNT_METRICS | PER_ANIMAL_RATE_METRICS

    def test_no_head_count_metric_may_carry_a_mass_unit(self):
        # the whole point, asserted rather than commented
        for metric in HEAD_COUNT_METRICS:
            assert not (METRIC_UNITS[metric] & {"t", "kg", "ha", "kg/ha"}), metric
        assert METRIC_UNITS["production_quantity"] == {"t"}

    def test_the_cross_slug_1000x_trap_is_declared(self):
        """MEASURED: live_animals is `An` for cattle_beef (13,831 rows) and hogs (12,824) but
        `1000 An` for broilers_poultry (13,932). Both units are governed on ONE metric on purpose --
        the `Cows In Milk` disposition, carried honestly on the per-row unit column -- and this
        assertion is what makes the card's warning non-negotiable."""
        assert METRIC_UNITS["live_animals"] == {"An", "1000 An"}

    @pytest.mark.parametrize("metric,unit", sorted(_REFUSED_UNITS))
    def test_each_refused_pair_is_refused_and_says_why(self, metric, unit):
        assert unit not in METRIC_UNITS[metric]
        assert _REFUSED_UNITS[(metric, unit)]

    def test_a_livestock_metric_in_an_ungoverned_unit_raises(self):
        with pytest.raises(FaostatMappingError, match="does not govern"):
            transform_faostat_production_silver_df(
                _row(element=["Stocks"], unit=["t"]), commodity="cattle_beef")

    def test_the_egg_production_unit_is_refused_by_name_on_a_crop_metric_too(self):
        """The three pairs at _REFUSED_UNITS are fenced on ANY metric, including the three crop
        metrics that predate this lane -- `1000 No` on production_quantity is a thousand-eggs count
        published as a tonnage."""
        with pytest.raises(FaostatMappingError, match="REFUSED BY NAME"):
            transform_faostat_production_silver_df(
                _row(item=["Hen eggs in shell, fresh"], element=["Production"],
                     unit=["1000 No"]), commodity="broilers_poultry")

    def test_the_fence_runs_before_duplicate_resolution(self):
        """ORDERING, and it is a diagnosis question rather than a safety one -- both orders are
        fail-closed. The natural key is (country_key, metric, year) with NO unit, so two units on
        one key ALSO trip `_resolve_duplicates_or_raise`, but as a 'conflicting duplicate value',
        which sends the reader hunting a data defect when the answer is a units decision. MEASURED:
        admitting `Hen eggs in shell, fresh` puts `t` and `1000 No` on 13,801 of its 14,009
        (area, year) keys."""
        both = pd.DataFrame({
            "area": ["Brazil", "Brazil"], "item": ["Hen eggs in shell, fresh"] * 2,
            "element": ["Production", "Production"], "year": [2020, 2020],
            "unit": ["t", "1000 No"], "value": [3.0e6, 5.0e7], "flag": ["A", "A"],
            "ingest_date": ["2026-05-11"] * 2,
        })
        with pytest.raises(FaostatMappingError) as exc:
            transform_faostat_production_silver_df(both, commodity="broilers_poultry")
        assert "does not govern" in str(exc.value)
        assert "conflicting duplicate" not in str(exc.value)

    def test_a_governed_livestock_row_passes_through_with_its_unit_intact(self):
        _, silver = transform_faostat_production_silver_df(
            _row(item=["Chickens"], element=["Stocks"], unit=["1000 An"], value=[1.5e6]),
            commodity="broilers_poultry")[0]
        assert silver["metric"].iloc[0] == "live_animals"
        assert silver["unit"].iloc[0] == "1000 An"      # the compare key, never dropped
        assert set(silver.columns) == EXPECTED_COLS


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

    def test_a_same_key_multi_unit_pair_dies_with_the_units_named(self):
        """LANE-5 REVIEW MAJOR 3, scenario A: 'An' and '1000 An' are BOTH governed for
        live_animals, so pair-wise governance passes a single (country_key, metric, year) key
        printed in both scales -- and the value-conflict resolver would then mis-diagnose it as a
        VALUE conflict. The multi-unit guard must die FIRST, naming the units."""
        df = pd.DataFrame({
            "area": ["Brazil", "Brazil"], "item": ["Cattle"] * 2, "element": ["Stocks"] * 2,
            "year": [2020, 2020], "unit": ["An", "1000 An"], "value": [2.2e8, 2.2e5],
            "flag": ["A", "A"], "ingest_date": ["2026-05-11"] * 2,
        })
        with pytest.raises(FaostatMappingError, match="MORE THAN ONE unit"):
            transform_faostat_production_silver_df(df, commodity="cattle_beef")

    def test_a_same_key_multi_unit_pair_with_EQUAL_values_cannot_collapse_silently(self):
        """Scenario B, the silent-collapse path: equal values on both scales used to pass the
        conflict resolver (dropna + nunique==1) and keep='last' published ONE row under whichever
        unit survived -- the estate's headline 1000x metric wrong-scaled with no error. Unreachable
        on today's roster (no admitted (item, element) prints two units, measured); this pin is
        what makes the first admission that changes that die loudly."""
        df = pd.DataFrame({
            "area": ["Brazil", "Brazil"], "item": ["Cattle"] * 2, "element": ["Stocks"] * 2,
            "year": [2020, 2020], "unit": ["An", "1000 An"], "value": [1000.0, 1000.0],
            "flag": ["A", "A"], "ingest_date": ["2026-05-11"] * 2,
        })
        with pytest.raises(FaostatMappingError, match="MORE THAN ONE unit"):
            transform_faostat_production_silver_df(df, commodity="cattle_beef")

    def test_a_padded_unit_is_published_stripped(self):
        """The fence normalizes ON THE FRAME now (Lane-5 review minor): ' An ' must reach silver
        as 'An' -- the card declares the unit column AUTHORITATIVE, so the fence's own
        normalization cannot open a gap it does not close."""
        got = transform_faostat_production_silver_df(
            pd.DataFrame({"area": ["Brazil"], "item": ["Cattle"], "element": ["Stocks"],
                          "year": [2020], "unit": [" An "], "value": [2.2e8], "flag": ["A"],
                          "ingest_date": ["2026-05-11"]}), commodity="cattle_beef")
        assert got and got[0][1]["unit"].iloc[0] == "An"

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
