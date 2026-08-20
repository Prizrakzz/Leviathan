"""D-EC P0: the never-once-run NASS annual wheat/class lane.

The projection census (data/dec_p0/projection_census.json, family ``silver_nass_annual``) PROVED
by execution -- not inspection -- that this lane had never produced a row: the cluster loaded all
161 bronze objects under ``commodity=soft_red_winter_wheat_cbot`` (3,495,679 rows, commodity_desc
100% 'WHEAT') and the shipped transform returned 0 rows, because ``_canonical_slug`` keyed on
commodity_desc values NASS does not publish. Repairing the map exposed two further crashes hiding
behind it -- an unhandled ``BU / PLANTED ACRE`` yield unit and a preference rank that was not a
total order -- so the three are ONE defect and this module tests them together.

The fixtures below replicate the MEASURED source vocabulary, re-counted for this repair on bronze
years 1990/2022/2024 (25,271 NATIONAL/STATE wheat rows, 10,827 cotton): the 13 wheat
(commodity_desc, class_desc) pairs, the four cotton classes, and all three bushel yield units.
"""
from __future__ import annotations

import gzip
import io

import pandas as pd
import pytest
from leviathan.transforms.bronze_to_silver.usda_nass_annual import (
    _ANY_CLASS,
    _RECORDED_CLASS_EXCLUSIONS,
    _YIELD_DENOMINATOR_PREFERENCE,
    LB_PER_ACRE_TO_T_HA,
    LB_TO_MT,
    _canonical_slug,
    _is_recorded_exclusion,
    _metric_preference_rank,
    _yield_denominator,
    transform_nass_annual_bronze_to_silver,
)
from leviathan.transforms.bronze_to_silver.usda_nass_crop_progress import (
    _canonical_slug as _progress_slug,
)
from leviathan.transforms.raw_to_bronze import usda_nass as bronze_module
from leviathan.transforms.raw_to_bronze.usda_nass import (
    _ANNUAL_COMMODITY_MAP,
    extract_usda_nass,
)

WHEAT_BUSHEL_LB = 60.0

# The 13 measured (commodity_desc='WHEAT', class_desc) pairs with their NATIONAL/STATE row counts on
# bronze years 1990/2022/2024. Every one of them returned None from the shipped mapper.
MEASURED_WHEAT_CLASSES: tuple[tuple[str, int], ...] = (
    ("ALL CLASSES", 18_519),
    ("WINTER", 4_457),
    ("SPRING, (EXCL DURUM)", 1_287),
    ("SPRING, DURUM", 714),
    ("WINTER, RED, SOFT", 86),
    ("WINTER, RED, HARD", 83),
    ("SPRING, RED, HARD", 31),
    ("WINTER, WHITE, HARD", 29),
    ("WINTER, WHITE, SOFT", 27),
    ("WINTER, WHITE", 11),
    ("SPRING, WHITE, SOFT", 10),
    ("SPRING, WHITE, HARD", 10),
    ("SPRING, WHITE", 7),
)

# The four measured COTTON classes and the slug each one now reaches.
MEASURED_COTTON_CLASSES: dict[str, str] = {
    "ALL CLASSES": "cotton",
    "UPLAND": "upland_cotton",
    "PIMA": "pima_cotton",
    "COTTONSEED": "cottonseed",
}

# Measured wheat yield-unit universe: BU / ACRE 29,945 rows, BU / NET PLANTED ACRE 5,238,
# BU / PLANTED ACRE 51. The third one raised ValueError at the converter.
MEASURED_YIELD_UNITS: tuple[str, ...] = (
    "BU / ACRE",
    "BU / NET PLANTED ACRE",
    "BU / PLANTED ACRE",
)


def _row(
    *,
    commodity_desc: str,
    class_desc: str,
    statisticcat_desc: str,
    unit_desc: str,
    value: float,
    cv_pct: float = 1.2,
    agg_level_desc: str = "STATE",
    state_alpha: str | None = "KS",
    year: int = 2024,
) -> dict:
    """One bronze row in the shape the batch task hands the transform (see the sibling fixture)."""
    return {
        "leviathan_slug": "soft_red_winter_wheat_cbot",   # the bronze PARTITION bucket, not the slug
        "source_desc": "SURVEY",
        "sector_desc": "CROPS",
        "group_desc": "FIELD CROPS",
        "commodity_desc": commodity_desc,
        "class_desc": class_desc,
        "prodn_practice_desc": "ALL PRODUCTION PRACTICES",
        "util_practice_desc": "ALL UTILIZATION PRACTICES",
        "domain_desc": "TOTAL",
        "domaincat_desc": "NOT SPECIFIED",
        "short_desc": f"{commodity_desc}, {class_desc} - {statisticcat_desc}",
        "freq_desc": "ANNUAL",
        "reference_period_desc": "YEAR",
        "statisticcat_desc": statisticcat_desc,
        "unit_desc": unit_desc,
        "agg_level_desc": agg_level_desc,
        "state_alpha": state_alpha,
        "state_name": "KANSAS",
        "county_code": None,
        "county_name": None,
        "year": year,
        "value": value,
        "cv_pct": cv_pct,
        "download_date": "2026-08-18",
        "source": "usda_nass",
    }


def _wheat_rows(class_desc: str, **overrides) -> list[dict]:
    """The four annual stat cats for one wheat class, in the units NASS actually publishes."""
    common = {"commodity_desc": "WHEAT", "class_desc": class_desc, **overrides}
    return [
        _row(statisticcat_desc="AREA PLANTED", unit_desc="ACRES", value=100.0, cv_pct=0.1, **common),
        _row(statisticcat_desc="AREA HARVESTED", unit_desc="ACRES", value=90.0, cv_pct=0.2, **common),
        _row(statisticcat_desc="YIELD", unit_desc="BU / ACRE", value=50.0, cv_pct=0.3, **common),
        _row(statisticcat_desc="PRODUCTION", unit_desc="BU", value=4_500.0, cv_pct=0.4, **common),
    ]


# =====================================================================================================
# BRONZE -- the four dead map keys.
# =====================================================================================================
class TestBronzeCommodityMap:
    def test_dead_wheat_keys_are_gone_and_plain_wheat_is_the_only_wheat_key(self) -> None:
        """NASS publishes no 'WHEAT, WINTER'/'WHEAT, SPRING'/'WHEAT, DURUM' commodity_desc; those
        three keys matched nothing in the source's 278-value census and read as coverage that was
        never there. Every wheat class arrives under plain 'WHEAT'."""
        wheat_keys = {k for k in _ANNUAL_COMMODITY_MAP if k.startswith("WHEAT")}
        assert wheat_keys == {"WHEAT"}
        assert _ANNUAL_COMMODITY_MAP["WHEAT"] == "soft_red_winter_wheat_cbot"

    def test_sugarbeets_uses_the_source_spelling(self) -> None:
        assert "SUGAR BEETS" not in _ANNUAL_COMMODITY_MAP
        assert _ANNUAL_COMMODITY_MAP["SUGARBEETS"] == "raw_sugar"

    def test_module_docstring_no_longer_cites_a_nonexistent_map(self) -> None:
        """The docstring pointed readers at ``_NASS_SLUG_MAP``, which has never existed in this file."""
        doc = bronze_module.__doc__ or ""
        assert "_ANNUAL_COMMODITY_MAP" in doc
        assert "_PROGRESS_COMMODITY_MAP" in doc

    def test_extract_keeps_measured_wheat_classes_and_sugarbeets(self) -> None:
        """End to end on a synthetic QuickStats .gz: the repaired keys admit the rows the dead keys
        dropped, and a row spelled the dead way is NOT resurrected by accident."""
        header = [
            "SOURCE_DESC", "COMMODITY_DESC", "CLASS_DESC", "STATISTICCAT_DESC", "UNIT_DESC",
            "AGG_LEVEL_DESC", "STATE_ALPHA", "YEAR", "VALUE", "CV_%",
        ]
        body = [
            ["SURVEY", "WHEAT", "WINTER", "PRODUCTION", "BU", "STATE", "KS", "2024", "1,000", "1.1"],
            ["SURVEY", "WHEAT", "SPRING, (EXCL DURUM)", "YIELD", "BU / ACRE", "STATE", "ND", "2024", "48", "1.2"],
            ["SURVEY", "SUGARBEETS", "", "PRODUCTION", "TONS", "STATE", "MN", "2024", "500", "1.3"],
            ["SURVEY", "WHEAT, WINTER", "", "PRODUCTION", "BU", "STATE", "KS", "2024", "7", "1.4"],
            ["SURVEY", "HAY", "", "PRODUCTION", "TONS", "STATE", "KS", "2024", "9", "1.5"],
        ]
        tsv = "\n".join("\t".join(line) for line in [header, *body]) + "\n"
        payload = gzip.compress(tsv.encode("latin-1"))

        annual = extract_usda_nass(io.BytesIO(payload), download_date="2026-08-18")["annual"]

        assert set(annual["commodity_desc"]) == {"WHEAT", "SUGARBEETS"}
        assert set(annual.loc[annual["commodity_desc"] == "WHEAT", "class_desc"]) == {
            "WINTER", "SPRING, (EXCL DURUM)",
        }
        assert set(annual["leviathan_slug"]) == {"soft_red_winter_wheat_cbot", "raw_sugar"}
        assert annual.loc[annual["class_desc"] == "WINTER", "value"].iloc[0] == 1_000.0


# =====================================================================================================
# SILVER -- the class map, and the sibling convention it now mirrors.
# =====================================================================================================
class TestCanonicalSlugClassMap:
    def test_every_measured_wheat_pair_is_mapped_or_written_down(self) -> None:
        """The deliberate-subset law: a measured pair may be dropped, but never SILENTLY. This is
        the assertion the old lane could not have passed -- all 13 returned None, and the file's one
        comment covered only 'aggregate WHEAT' and durum.

        The BLANK class is in the sweep too: ``_canonical_slug('WHEAT', '')`` and the NaN that cleans
        to it both return None, so the pair needs its written reason like any other."""
        for class_desc, _rows in [*MEASURED_WHEAT_CLASSES, ("", 0)]:
            slug = _canonical_slug("WHEAT", class_desc)
            recorded = _is_recorded_exclusion("WHEAT", class_desc)
            assert slug is not None or recorded, f"{class_desc!r} is dropped with no written reason"
            assert not (slug is not None and recorded), f"{class_desc!r} is both mapped and excluded"

    def test_the_blank_wheat_class_is_refused_in_writing(self) -> None:
        """A wheat row with a null/absent class_desc is UNCLASSIFIABLE -- there is no basis for
        choosing between the winter and spring nodes -- and that refusal is now an EXACT-PAIR entry
        rather than an unexplained ``return None``. Note the asymmetry the reason records: for CORN
        a blank class IS the all-classes total and is KEPT."""
        assert _canonical_slug("WHEAT", "") is None
        assert _canonical_slug("WHEAT", float("nan")) is None
        assert ("WHEAT", "") in _RECORDED_CLASS_EXCLUSIONS
        assert "UNCLASSIFIABLE" in _RECORDED_CLASS_EXCLUSIONS[("WHEAT", "")]
        assert _canonical_slug("CORN", "") == "corn_cbot"

    def test_commodity_level_notes_use_the_sentinel_not_a_blank_class(self) -> None:
        """The two record kinds must not read alike. ('SORGHUM', '') looked like an exact pair on
        the blank class and would have stopped covering the commodity the day NASS published a class
        on it; ('SORGHUM', _ANY_CLASS) says what it means -- every class, published or not."""
        for commodity in ("SUGARCANE", "SUGARBEETS", "SORGHUM", "OATS", "BARLEY", "SUNFLOWER"):
            assert (commodity, _ANY_CLASS) in _RECORDED_CLASS_EXCLUSIONS, commodity
            assert (commodity, "") not in _RECORDED_CLASS_EXCLUSIONS, commodity
            # covered whether the class is blank today or a class NASS starts publishing tomorrow
            assert _is_recorded_exclusion(commodity, "")
            assert _is_recorded_exclusion(commodity, "SOME FUTURE CLASS")
            assert _canonical_slug(commodity, "SOME FUTURE CLASS") is None

    def test_the_sentinel_never_leaks_across_commodities(self) -> None:
        """A commodity-level note covers ITS commodity only -- WHEAT's exact pairs stay exact."""
        assert not _is_recorded_exclusion("WHEAT", "SOME FUTURE CLASS")
        assert not _is_recorded_exclusion("COTTON", "SOME FUTURE CLASS")
        assert ("WHEAT", _ANY_CLASS) not in _RECORDED_CLASS_EXCLUSIONS

    def test_exactly_the_two_sibling_classes_map(self) -> None:
        mapped = {
            class_desc: _canonical_slug("WHEAT", class_desc)
            for class_desc, _ in MEASURED_WHEAT_CLASSES
            if _canonical_slug("WHEAT", class_desc) is not None
        }
        assert mapped == {
            "WINTER": "soft_red_winter_wheat_cbot",
            "SPRING, (EXCL DURUM)": "hard_red_spring_wheat_mgex",
        }

    @pytest.mark.parametrize("class_desc", ["WINTER", "SPRING, (EXCL DURUM)", "SPRING, DURUM"])
    def test_wheat_convention_is_the_siblings_string_for_string(self, class_desc: str) -> None:
        """THE CONVENTION LAW. usda_nass_crop_progress.py:97-101 reads the same source vocabulary
        and its silver is healthy; this transform must not invent a second answer for the same
        string. (Cotton deliberately diverges -- see the cotton test below.)"""
        assert _canonical_slug("WHEAT", class_desc) == _progress_slug("WHEAT", class_desc)

    def test_winter_conflation_is_recorded_not_silently_resolved(self) -> None:
        """NASS's WINTER class is ALL winter wheat, so the SRW node carries HRW and white winter
        wheat too, and hard_red_winter_wheat_kcbt gets nothing. Both facts are written down."""
        assert _canonical_slug("WHEAT", "WINTER, RED, HARD") is None
        assert "collide with WINTER" in _RECORDED_CLASS_EXCLUSIONS[("WHEAT", "WINTER, RED, HARD")]
        source = _module_source()
        assert "hard_red_winter_wheat_kcbt still has NO annual lane" in source
        assert "SAME conflation the crop-progress lane already" in source

    def test_every_measured_cotton_class_reaches_its_own_slug(self) -> None:
        """UPLAND (23,214 measured rows), PIMA (5,424) and COTTONSEED (4,460) were all dropped.
        They cannot share ``cotton`` with the ALL CLASSES total: that total IS upland + pima, so one
        slug would carry two different numbers for one (state, year) and the uniqueness validator
        would reject the partition."""
        for class_desc, expected in MEASURED_COTTON_CLASSES.items():
            assert _canonical_slug("COTTON", class_desc) == expected
        assert len(set(MEASURED_COTTON_CLASSES.values())) == len(MEASURED_COTTON_CLASSES)

    def test_cotton_divergence_from_the_sibling_is_deliberate(self) -> None:
        """The sibling calls UPLAND ``cotton`` because crop progress publishes no ALL CLASSES row.
        Annual does, and it is the longer series (measured 1920: 70 NATIONAL/STATE ALL CLASSES rows
        against UPLAND's 6), so ``cotton`` keeps its basis and UPLAND gets its own slug."""
        assert _progress_slug("COTTON", "UPLAND") == "cotton"
        assert _canonical_slug("COTTON", "UPLAND") == "upland_cotton"
        assert _canonical_slug("COTTON", "ALL CLASSES") == "cotton"

    def test_pre_existing_slugs_are_untouched(self) -> None:
        assert _canonical_slug("CORN", "ALL CLASSES") == "corn_cbot"
        assert _canonical_slug("SOYBEANS", "ALL CLASSES") == "soybeans_cbot"
        assert _canonical_slug("RICE", "ALL CLASSES") == "rough_rice_cbot"
        assert _canonical_slug("CANOLA", "ALL CLASSES") == "canola_ice"


def _module_source() -> str:
    from pathlib import Path

    from leviathan.transforms.bronze_to_silver import usda_nass_annual

    return Path(usda_nass_annual.__file__).read_text(encoding="utf-8")


# =====================================================================================================
# SILVER -- the lane actually produces rows now.
# =====================================================================================================
class TestWheatLaneProducesRows:
    def test_winter_class_produces_soft_red_winter_rows(self) -> None:
        silver = transform_nass_annual_bronze_to_silver(pd.DataFrame(_wheat_rows("WINTER")))
        assert len(silver) == 1
        row = silver.iloc[0]
        assert row["leviathan_slug"] == "soft_red_winter_wheat_cbot"
        assert row["state"] == "KS" and row["year"] == 2024
        assert row["yield_t_ha"] == pytest.approx(50.0 * WHEAT_BUSHEL_LB * LB_PER_ACRE_TO_T_HA)
        assert row["production_mt"] == pytest.approx(4_500.0 * WHEAT_BUSHEL_LB * LB_TO_MT)

    def test_spring_excl_durum_produces_hard_red_spring_rows(self) -> None:
        rows = _wheat_rows("SPRING, (EXCL DURUM)", state_alpha="ND")
        silver = transform_nass_annual_bronze_to_silver(pd.DataFrame(rows))
        assert len(silver) == 1
        assert silver.iloc[0]["leviathan_slug"] == "hard_red_spring_wheat_mgex"
        assert silver.iloc[0]["state"] == "ND"

    def test_all_thirteen_measured_classes_in_one_frame_yield_exactly_two_slugs(self) -> None:
        """THE HEADLINE, inverted: the same 13 pairs that produced 0 rows now produce the two
        contract lanes and nothing else -- no double counting, no uniqueness crash."""
        rows: list[dict] = []
        for class_desc, _count in MEASURED_WHEAT_CLASSES:
            rows.extend(_wheat_rows(class_desc))
        silver = transform_nass_annual_bronze_to_silver(pd.DataFrame(rows))
        assert not silver.empty
        assert list(silver["leviathan_slug"]) == [
            "hard_red_spring_wheat_mgex",
            "soft_red_winter_wheat_cbot",
        ]

    def test_every_measured_cotton_class_survives_the_pivot_together(self) -> None:
        rows = [
            *[
                _row(commodity_desc="COTTON", class_desc=cls, statisticcat_desc="PRODUCTION",
                     unit_desc="480 LB BALES", value=10.0 + i)
                for i, cls in enumerate(("ALL CLASSES", "UPLAND", "PIMA"))
            ],
            # cottonseed is PRODUCTION in TONS only -- no area, no yield anywhere in the source.
            _row(commodity_desc="COTTON", class_desc="COTTONSEED", statisticcat_desc="PRODUCTION",
                 unit_desc="TONS", value=109_000.0),
        ]
        silver = transform_nass_annual_bronze_to_silver(pd.DataFrame(rows))
        assert set(silver["leviathan_slug"]) == set(MEASURED_COTTON_CLASSES.values())
        seed = silver.loc[silver["leviathan_slug"] == "cottonseed"].iloc[0]
        assert seed["production_mt"] == pytest.approx(109_000.0 * 0.90718474)
        assert pd.isna(seed["yield_t_ha"]) and pd.isna(seed["area_planted_ha"])


# =====================================================================================================
# CONVERTER -- the two crashes that only fire once the class map is fixed.
# =====================================================================================================
class TestYieldUnitConversion:
    @pytest.mark.parametrize("unit_desc", MEASURED_YIELD_UNITS)
    def test_every_measured_bushel_yield_unit_converts(self, unit_desc: str) -> None:
        """``BU / PLANTED ACRE`` (51 measured rows) raised 'Unsupported NASS yield unit' -- the first
        crash behind the dead map."""
        rows = _wheat_rows("WINTER")
        rows[2]["unit_desc"] = unit_desc
        silver = transform_nass_annual_bronze_to_silver(pd.DataFrame(rows))
        assert silver.iloc[0]["yield_t_ha"] == pytest.approx(
            50.0 * WHEAT_BUSHEL_LB * LB_PER_ACRE_TO_T_HA
        )

    def test_all_three_yield_units_coexist_without_a_uniqueness_crash(self) -> None:
        """The second crash: only the NET PLANTED unit was ranked, so ``BU / ACRE`` and
        ``BU / PLANTED ACRE`` tied at rank 0 with different converted values and
        _validate_metric_uniqueness raised."""
        rows = _wheat_rows("WINTER")
        rows.append(_row(commodity_desc="WHEAT", class_desc="WINTER", statisticcat_desc="YIELD",
                         unit_desc="BU / NET PLANTED ACRE", value=48.0))
        rows.append(_row(commodity_desc="WHEAT", class_desc="WINTER", statisticcat_desc="YIELD",
                         unit_desc="BU / PLANTED ACRE", value=47.0))

        silver = transform_nass_annual_bronze_to_silver(pd.DataFrame(rows))

        assert len(silver) == 1
        # the standard per-harvested-acre yield wins, exactly as it did before this repair.
        assert silver.iloc[0]["yield_t_ha"] == pytest.approx(
            50.0 * WHEAT_BUSHEL_LB * LB_PER_ACRE_TO_T_HA
        )

    def test_the_winner_is_deterministic_across_row_order_and_re_runs(self) -> None:
        """write_mode is overwrite: a winner that depended on row order would rewrite canonical
        objects with a different number every weekly run."""
        rows = _wheat_rows("WINTER")
        rows.append(_row(commodity_desc="WHEAT", class_desc="WINTER", statisticcat_desc="YIELD",
                         unit_desc="BU / NET PLANTED ACRE", value=48.0))
        rows.append(_row(commodity_desc="WHEAT", class_desc="WINTER", statisticcat_desc="YIELD",
                         unit_desc="BU / PLANTED ACRE", value=47.0))
        frame = pd.DataFrame(rows)
        reversed_frame = pd.DataFrame(list(reversed(rows)))

        first = transform_nass_annual_bronze_to_silver(frame)
        again = transform_nass_annual_bronze_to_silver(frame)
        flipped = transform_nass_annual_bronze_to_silver(reversed_frame)

        pd.testing.assert_frame_equal(first, again)
        assert flipped.iloc[0]["yield_t_ha"] == pytest.approx(first.iloc[0]["yield_t_ha"])


class TestYieldPreferenceRank:
    @staticmethod
    def _rank(unit: str, stat: str = "YIELD") -> int:
        return _metric_preference_rank(
            pd.Series({"statisticcat_desc_norm": stat, "unit_desc_norm": unit})
        )

    def test_rank_is_a_total_order_over_every_observed_yield_unit(self) -> None:
        """A TOTAL order: two units tie only when they share a denominator, which is the one case
        _validate_metric_uniqueness is designed to adjudicate."""
        observed = [
            "BU / ACRE", "LB / ACRE", "CWT / ACRE", "TONS / ACRE", "TON / ACRE",
            "BU / NET PLANTED ACRE", "LB / NET PLANTED ACRE",
            "BU / PLANTED ACRE",
        ]
        ranks = {unit: self._rank(unit) for unit in observed}
        assert ranks["BU / ACRE"] == ranks["LB / ACRE"] == ranks["CWT / ACRE"] == 0
        assert ranks["BU / NET PLANTED ACRE"] == ranks["LB / NET PLANTED ACRE"] == 1
        assert ranks["BU / PLANTED ACRE"] == 2
        assert sorted(set(ranks.values())) == [0, 1, 2]

    def test_unobserved_denominator_sorts_last_instead_of_tying(self) -> None:
        assert self._rank("BAGS / HECTARE") == len(_YIELD_DENOMINATOR_PREFERENCE)
        assert self._rank("BAGS / HECTARE") > self._rank("BU / PLANTED ACRE")

    def test_non_yield_statistics_are_never_ranked(self) -> None:
        assert self._rank("ACRES", stat="AREA PLANTED") == 0
        assert self._rank("BU", stat="PRODUCTION") == 0

    def test_denominator_parsing(self) -> None:
        assert _yield_denominator("BU / NET PLANTED ACRE") == "NET PLANTED ACRE"
        assert _yield_denominator("LB / ACRE") == "ACRE"
        assert _yield_denominator("ACRES") == ""
