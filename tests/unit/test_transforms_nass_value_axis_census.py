"""C-2: the NASS VALUE axis and its sibling COMMODITY axis, refused in writing.

``_ANNUAL_STAT_CATS`` and ``_ANNUAL_COMMODITY_MAP`` are the two widest gates in the estate's
bronze layer and neither had a refusal companion: 9,802,561 of 23,866,721 source rows (41.07%) sit
on stat cats the annual lane does not admit, and 1,104,138 of the 1,946,206 admitted-cat
NATIONAL/STATE rows sit on commodities the map has no key for. Both numbers are MEASURED -- one
stream of ``qs.crops.txt.gz`` (1,128,974,735 B, download_date=2026-08-18), banked as
``data/dec_p0/nass_statcat_census.json`` on 2026-08-25.

This module is the PIN on that measurement, built on the shape ``_RECORDED_CLASS_EXCLUSIONS``
proved in ``test_transforms_nass_annual_class_lane.py``:

  * the admitted axes and the recorded-exclusion registries PARTITION the measured census, so a
    member cannot be dropped without a written reason and a row count;
  * the registries are DOCUMENTATION WITH A TEST -- ``extract_usda_nass`` never reads them and its
    output is unchanged with both emptied;
  * THE DRIFT DIRECTION THAT MATTERS: admitting a member into a gate WITHOUT deleting its line from
    the registry fails here. A widened gate can never leave a stale refusal standing behind it.

Every literal below is a cell of that artifact. They are pinned rather than recomputed on purpose:
a test that re-derives its expectation from the code under test cannot go red.
"""
from __future__ import annotations

import gzip
import inspect
import io
import json
from pathlib import Path

import pandas as pd
import pytest
from leviathan.transforms.raw_to_bronze import usda_nass as bronze_module
from leviathan.transforms.raw_to_bronze.usda_nass import (
    _ANNUAL_COMMODITY_MAP,
    _ANNUAL_STAT_CATS,
    _CENSUS_ADMITTED_CAT_NATIONAL_STATE_ROWS,
    _CENSUS_ADMITTED_STAT_CAT_ROWS,
    _CENSUS_MAPPED_COMMODITY_ROWS,
    _CENSUS_PROGRESS_STAT_CAT_ROWS,
    _CENSUS_SOURCE_ROWS,
    _PROGRESS_STAT_CATS,
    _RECORDED_COMMODITY_EXCLUSIONS,
    _RECORDED_STAT_CAT_EXCLUSIONS,
    _TAKEN_BY_THE_PROGRESS_LANE,
    _VALUE_AXIS_CENSUS_ARTIFACT,
    extract_usda_nass,
)

# ---- the census cells, pinned as literals (data/dec_p0/nass_statcat_census.json, 2026-08-25) ----
CENSUS_ARTIFACT = "data/dec_p0/nass_statcat_census.json"
DISTINCT_STAT_CATS = 136
DISTINCT_RESIDUAL_STAT_CATS = 132
DISTINCT_NEVER_ENUMERATED_STAT_CATS = 130
RESIDUAL_STAT_CAT_ROWS = 9_802_561
NEVER_ENUMERATED_ROWS = 8_453_572

DISTINCT_COMMODITIES_NATIONAL_STATE = 165
DISTINCT_UNMAPPED_COMMODITIES = 153
UNMAPPED_COMMODITY_ROWS = 1_104_138

# The five the C-2 plan text named. Their counts are CONFIRMED by the census, unlike the two
# aggregate figures the same paragraph carried (see the SUGARBEETS and 194->153 tests below).
PLAN_NAMED_COMMODITIES: dict[str, int] = {
    "HAY": 217_825,
    "POTATOES": 101_994,
    "BEANS": 96_915,
    "TOBACCO": 65_499,
    "PEANUTS": 27_304,
}

# The two C-2 named on the value axis by construction, with their measured rows.
PLAN_NAMED_STAT_CATS: dict[str, int] = {
    "PRICE RECEIVED": 599_327,
    "STOCKS": 253_924,
}

# PROGRESS and CONDITION are admitted by exact string, so these four variants -- the bulk of the
# in-season residual -- are dark and must be registered like any other refusal.
MEASURED_PROGRESS_VARIANTS: dict[str, int] = {
    "CONDITION, PREVIOUS YEAR": 514_079,
    "CONDITION, 5 YEAR AVG": 423_291,
    "PROGRESS, 5 YEAR AVG": 344_588,
    "PROGRESS, PREVIOUS YEAR": 214_508,
}


def _rows(registry: dict[str, tuple[int, str]]) -> int:
    return sum(count for count, _reason in registry.values())


def _module_source() -> str:
    return Path(bronze_module.__file__).read_text(encoding="utf-8")


# =====================================================================================================
# THE VALUE AXIS -- statisticcat_desc.
# =====================================================================================================
class TestValueAxisRegistry:
    def test_the_registry_names_the_census_artifact_it_is_pinned_against(self) -> None:
        """A pin with no provenance is a magic number. The artifact path lives in the module so the
        next reader can re-open the measurement rather than re-derive it."""
        assert _VALUE_AXIS_CENSUS_ARTIFACT == CENSUS_ARTIFACT
        source = _module_source()
        assert "download_date=2026-08-18/qs.crops.txt.gz" in source
        assert "1,128,974,735 B" in source

    def test_admitting_a_stat_cat_requires_deleting_its_exclusion(self) -> None:
        """THE DRIFT DIRECTION THAT MATTERS. Widening ``_ANNUAL_STAT_CATS`` without removing the cat
        from the registry would leave a written refusal standing over a row the lane now keeps --
        exactly the silence this whole pattern exists to prevent."""
        overlap = set(_ANNUAL_STAT_CATS) & set(_RECORDED_STAT_CAT_EXCLUSIONS)
        assert overlap == set(), f"admitted and recorded as excluded: {sorted(overlap)}"

    def test_the_two_axes_partition_the_measured_census_by_row(self) -> None:
        """The completeness proof, and the one assertion that cannot be satisfied by a partial
        registry: the admitted rows plus every registered row must be the whole source object."""
        assert _CENSUS_SOURCE_ROWS == 23_866_721
        assert _CENSUS_ADMITTED_STAT_CAT_ROWS == 14_064_160
        assert _rows(_RECORDED_STAT_CAT_EXCLUSIONS) == RESIDUAL_STAT_CAT_ROWS
        assert _CENSUS_ADMITTED_STAT_CAT_ROWS + RESIDUAL_STAT_CAT_ROWS == _CENSUS_SOURCE_ROWS

    def test_the_two_axes_partition_the_measured_census_by_cat(self) -> None:
        assert len(_ANNUAL_STAT_CATS) == 4
        assert len(_RECORDED_STAT_CAT_EXCLUSIONS) == DISTINCT_RESIDUAL_STAT_CATS
        assert len(_ANNUAL_STAT_CATS) + len(_RECORDED_STAT_CAT_EXCLUSIONS) == DISTINCT_STAT_CATS

    def test_the_crop_progress_lane_cats_are_recorded_as_TAKEN_not_as_dark(self) -> None:
        """The plan text read the whole 41.07% residual as 'never enumerated anywhere'. It is not:
        ``_PROGRESS_STAT_CATS`` ADMITS 1,348,989 of those rows BY STAT CAT -- though the lane's
        8-key commodity gate then kills an unmeasured share of them (the TAKEN tag says so; the
        split is the census's one unmeasured cell). The registry records that as a status rather
        than a refusal, and the tagged set must BE the sibling frozenset -- so adding a cat to the
        crop-progress lane forces its entry to be retagged."""
        taken = {
            cat
            for cat, (_count, reason) in _RECORDED_STAT_CAT_EXCLUSIONS.items()
            if reason is _TAKEN_BY_THE_PROGRESS_LANE
        }
        assert taken == set(_PROGRESS_STAT_CATS) == {"PROGRESS", "CONDITION"}
        assert sum(_RECORDED_STAT_CAT_EXCLUSIONS[cat][0] for cat in taken) == _CENSUS_PROGRESS_STAT_CAT_ROWS
        assert _CENSUS_PROGRESS_STAT_CAT_ROWS == 1_348_989

    def test_the_honest_never_enumerated_figure_is_derivable_and_pinned(self) -> None:
        """AT LEAST 8,453,572 rows on 130 cats (35.42%), not 9.80M on 132 -- the correction C-2
        asked for, recorded in the file the correction is about. A FLOOR, not the truth: the
        progress lane's commodity gate kills an unmeasured share of the 1,348,989 subtracted here
        (PASTURELAND/HAY/PEANUTS among them), so the real never-served mass is larger -- the
        module states this beside the figure and the split rides the next census cut."""
        never = _rows(_RECORDED_STAT_CAT_EXCLUSIONS) - _CENSUS_PROGRESS_STAT_CAT_ROWS
        assert never == NEVER_ENUMERATED_ROWS
        assert (
            len(_RECORDED_STAT_CAT_EXCLUSIONS) - len(_PROGRESS_STAT_CATS)
            == DISTINCT_NEVER_ENUMERATED_STAT_CATS
        )
        assert "8,453,572" in _module_source()

    @pytest.mark.parametrize("cat,count", sorted(PLAN_NAMED_STAT_CATS.items()))
    def test_price_received_and_stocks_are_named_members(self, cat: str, count: int) -> None:
        """C-2 names both by construction. They are the two largest single row-lighting candidates
        on this axis and each carries its own reason, not a family one."""
        assert cat in _RECORDED_STAT_CAT_EXCLUSIONS
        assert _RECORDED_STAT_CAT_EXCLUSIONS[cat][0] == count
        assert "named by C-2 by construction" in _RECORDED_STAT_CAT_EXCLUSIONS[cat][1]

    @pytest.mark.parametrize("cat,count", sorted(MEASURED_PROGRESS_VARIANTS.items()))
    def test_exact_string_matching_leaves_the_progress_variants_dark(self, cat: str, count: int) -> None:
        """``comm.isin(_PROGRESS_STAT_CATS)`` is an exact-string match, so 'CONDITION, PREVIOUS YEAR'
        is NOT admitted by 'CONDITION'. 1,496,466 rows turn on that comma."""
        assert cat not in _PROGRESS_STAT_CATS
        assert _RECORDED_STAT_CAT_EXCLUSIONS[cat][0] == count
        assert _RECORDED_STAT_CAT_EXCLUSIONS[cat][1] is not _TAKEN_BY_THE_PROGRESS_LANE

    def test_every_registered_cat_carries_a_count_and_a_reason(self) -> None:
        for cat, entry in _RECORDED_STAT_CAT_EXCLUSIONS.items():
            count, reason = entry
            assert isinstance(count, int) and count > 0, cat
            assert isinstance(reason, str) and len(reason.split()) >= 8, cat


# =====================================================================================================
# THE COMMODITY AXIS -- commodity_desc, the sibling gap.
# =====================================================================================================
class TestCommodityAxisRegistry:
    def test_mapping_a_commodity_requires_deleting_its_exclusion(self) -> None:
        overlap = set(_ANNUAL_COMMODITY_MAP) & set(_RECORDED_COMMODITY_EXCLUSIONS)
        assert overlap == set(), f"mapped and recorded as excluded: {sorted(overlap)}"

    def test_the_two_axes_partition_the_national_state_census_by_row(self) -> None:
        assert _CENSUS_ADMITTED_CAT_NATIONAL_STATE_ROWS == 1_946_206
        assert _CENSUS_MAPPED_COMMODITY_ROWS == 842_068
        assert _rows(_RECORDED_COMMODITY_EXCLUSIONS) == UNMAPPED_COMMODITY_ROWS
        assert (
            _CENSUS_MAPPED_COMMODITY_ROWS + UNMAPPED_COMMODITY_ROWS
            == _CENSUS_ADMITTED_CAT_NATIONAL_STATE_ROWS
        )

    def test_the_two_axes_partition_the_national_state_census_by_commodity(self) -> None:
        assert len(_ANNUAL_COMMODITY_MAP) == 12
        assert len(_RECORDED_COMMODITY_EXCLUSIONS) == DISTINCT_UNMAPPED_COMMODITIES
        assert (
            len(_ANNUAL_COMMODITY_MAP) + len(_RECORDED_COMMODITY_EXCLUSIONS)
            == DISTINCT_COMMODITIES_NATIONAL_STATE
        )

    @pytest.mark.parametrize("commodity,count", sorted(PLAN_NAMED_COMMODITIES.items()))
    def test_the_plan_named_commodities_carry_their_measured_counts(
        self, commodity: str, count: int
    ) -> None:
        """These five the census CONFIRMED row for row. They are the top mass the C-2 paragraph
        quoted, and they are the reason this registry is enumerated rather than summarised."""
        assert _RECORDED_COMMODITY_EXCLUSIONS[commodity][0] == count

    def test_sugarbeets_is_mapped_and_therefore_absent_from_the_registry(self) -> None:
        """The plan's 1,123,488 counted SUGARBEETS as unmapped -- it was inferred against the pre-fix
        key 'SUGAR BEETS' (with a space), which matched nothing in the source. The 19,350-row delta
        is the whole correction to 1,104,138, and it is written down where the numbers live."""
        assert _ANNUAL_COMMODITY_MAP["SUGARBEETS"] == "raw_sugar"
        assert "SUGARBEETS" not in _RECORDED_COMMODITY_EXCLUSIONS
        source = _module_source()
        assert "1,123,488 dropped rows -> 1,104,138" in source
        assert "EXACTLY SUGARBEETS, 19,350 rows" in source

    def test_the_plans_194_unmapped_commodities_is_corrected_to_153_in_writing(self) -> None:
        """205 - 11 was computed against the ALL-AGG-LEVEL commodity count and applied to a
        NATIONAL/STATE question. Only 165 commodities carry admitted-cat rows at NATIONAL/STATE."""
        assert len(_RECORDED_COMMODITY_EXCLUSIONS) == 153
        assert "194 unmapped commodities -> 153" in _module_source()

    def test_no_map_key_is_dead(self) -> None:
        """TWO ASSERTIONS, honestly separated (the Lane-6 review caught the first docstring claiming
        the second): the IDENTITY pin below always runs; the LIVENESS pin -- every map key carries a
        non-zero admitted NATIONAL/STATE count in the census -- runs against the banked artifact
        (committed with this change) and is the failure mode the dead 'WHEAT, WINTER' /
        'SUGAR BEETS' keys were, caught on the other axis by D-EC P0."""
        assert set(_ANNUAL_COMMODITY_MAP) == {
            "CORN", "SOYBEANS", "WHEAT", "COTTON", "RICE", "SORGHUM", "OATS", "BARLEY",
            "SUGARCANE", "SUGARBEETS", "SUNFLOWER", "CANOLA",
        }
        artifact = Path(__file__).resolve().parents[2] / _VALUE_AXIS_CENSUS_ARTIFACT
        if not artifact.exists():
            pytest.skip(f"census artifact absent from this checkout: {_VALUE_AXIS_CENSUS_ARTIFACT}")
        mapped = json.loads(artifact.read_text(encoding="utf-8"))[
            "full_tallies"]["admitted_national_state_by_commodity"]
        dead = sorted(k for k in _ANNUAL_COMMODITY_MAP if int(mapped.get(k, 0)) <= 0)
        assert not dead, f"map key(s) with ZERO measured admitted NATIONAL/STATE rows: {dead}"

    def test_every_registered_commodity_carries_a_count_and_a_reason(self) -> None:
        for commodity, entry in _RECORDED_COMMODITY_EXCLUSIONS.items():
            count, reason = entry
            assert isinstance(count, int) and count > 0, commodity
            assert isinstance(reason, str) and len(reason.split()) >= 8, commodity


# =====================================================================================================
# THE SHAPE LAW -- documentation with a test, never control flow.
# =====================================================================================================
def _fixture_gz() -> bytes:
    """A synthetic QuickStats slab spanning both gates: two admitted cats on mapped commodities, an
    admitted cat on an UNMAPPED commodity (HAY), and a registered stat cat on a MAPPED one (STOCKS
    on CORN). The last two are the rows the registries describe, and they must stay dropped."""
    header = [
        "SOURCE_DESC", "COMMODITY_DESC", "CLASS_DESC", "STATISTICCAT_DESC", "UNIT_DESC",
        "AGG_LEVEL_DESC", "STATE_ALPHA", "YEAR", "VALUE", "CV_%",
    ]
    body = [
        ["SURVEY", "CORN", "ALL CLASSES", "PRODUCTION", "BU", "STATE", "IA", "2024", "2,400", "1.1"],
        ["SURVEY", "WHEAT", "WINTER", "YIELD", "BU / ACRE", "STATE", "KS", "2024", "48", "1.2"],
        ["SURVEY", "CORN", "ALL CLASSES", "PROGRESS", "PCT", "STATE", "IA", "2024", "77", "1.3"],
        # registered on the VALUE axis -- STOCKS on a mapped commodity
        ["SURVEY", "CORN", "ALL CLASSES", "STOCKS", "BU", "STATE", "IA", "2024", "900", "1.4"],
        # registered on the COMMODITY axis -- an admitted cat on an unmapped commodity
        ["SURVEY", "HAY", "", "PRODUCTION", "TONS", "STATE", "KS", "2024", "9", "1.5"],
    ]
    tsv = "\n".join("\t".join(line) for line in [header, *body]) + "\n"
    return gzip.compress(tsv.encode("latin-1"))


class TestRegistriesAreDocumentationNotControlFlow:
    def test_extract_never_reads_either_registry(self) -> None:
        """The static half of the law: if the transform grew a branch on a registry, the registry
        would stop being a record and start being a second, unversioned gate."""
        body = inspect.getsource(extract_usda_nass)
        assert "_RECORDED_STAT_CAT_EXCLUSIONS" not in body
        assert "_RECORDED_COMMODITY_EXCLUSIONS" not in body

    def test_emptying_both_registries_leaves_the_extract_identical(self, monkeypatch) -> None:
        """The behavioural half: same bytes in, same frames out, with the documentation deleted."""
        payload = _fixture_gz()
        before = extract_usda_nass(io.BytesIO(payload), download_date="2026-08-18")

        monkeypatch.setattr(bronze_module, "_RECORDED_STAT_CAT_EXCLUSIONS", {})
        monkeypatch.setattr(bronze_module, "_RECORDED_COMMODITY_EXCLUSIONS", {})
        after = extract_usda_nass(io.BytesIO(payload), download_date="2026-08-18")

        for key in ("annual", "crop_progress"):
            pd.testing.assert_frame_equal(before[key], after[key])

    def test_the_registered_rows_are_the_rows_that_get_dropped(self) -> None:
        """The registries describe REAL drops, not hypothetical ones: a registered stat cat on a
        mapped commodity and an admitted stat cat on a registered commodity both die at bronze."""
        series = extract_usda_nass(io.BytesIO(_fixture_gz()), download_date="2026-08-18")
        annual = series["annual"]

        assert "STOCKS" in _RECORDED_STAT_CAT_EXCLUSIONS
        assert "STOCKS" not in set(annual["statisticcat_desc"])
        assert "HAY" in _RECORDED_COMMODITY_EXCLUSIONS
        assert "HAY" not in set(annual["commodity_desc"])
        assert set(annual["commodity_desc"]) == {"CORN", "WHEAT"}
        assert set(series["crop_progress"]["statisticcat_desc"]) == {"PROGRESS"}
