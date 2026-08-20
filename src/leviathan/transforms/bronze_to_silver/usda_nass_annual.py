"""Silver transform for USDA NASS QuickStats annual crop data.

The bronze NASS layer intentionally keeps a broad annual slice from the bulk
QuickStats crops file, including county rows and a few proxy commodity mappings.
This transform narrows that data into production-forecasting features:
national/state only, standard metric units, and one wide row per
(leviathan_slug, state, year).

D-LD pre-step D-LD-9a (2026-08-18) ADDITIVELY appends one column, ``release_date``
-- the DERIVED vintage knowledge anchor. The measured physical table carried NO
date, vintage, ingest or month column of any kind (14 body columns over 593
canonical objects / 14,631 rows), so a numbers card had nothing to anchor its
point-in-time as-of guard on: ``knowledge_col()`` returned ``None`` and
``query.build_sql`` raised "no knowledge/date column to anchor the as-of guard".
``year`` is the CROP year, not a knowledge date. This is the same shape
WIRING_WAVE1 met on ``silver_conab_coffee`` (``survey_release_date``) and
``silver_sagis_weekly_exports`` (``week_ending_date``), and it is solved the same
way: one producer-derived, conservative, never-leak timing column. See
``_ANNUAL_SUMMARY_RELEASE`` below. The column NEVER touches a measured value.

D-EC P0 class-lane repair (2026-08-20)
--------------------------------------
The wheat lane had NEVER ONCE RUN. ``_canonical_slug`` keyed on commodity_desc values NASS does
not publish, so every bronze wheat row was dropped before the converter, hiding two further
crashes behind it (an unhandled ``BU / PLANTED ACRE`` yield unit and a yield-preference rank that
was not a total order). All three are fixed together -- they are one defect, discoverable only in
that order. The class vocabulary is now the sibling's, string for string, and every deliberate
drop is named in ``_RECORDED_CLASS_EXCLUSIONS``.

MEASURED BY REPLAY, not by inspection -- the repaired transform re-run over every real bronze
object of the affected partitions: wheat 161 objects / 3,495,679 rows goes from 0 silver rows to
6,582 (soft_red_winter_wheat_cbot 4,853 + hard_red_spring_wheat_mgex 1,729, 1909-2026, 46 states),
cotton 161 objects gains cottonseed 2,770 + upland_cotton 1,600 + pima_cotton 497 -- with ZERO
converter errors and ZERO duplicate keys. Replayed across ALL 872 bronze objects, every
pre-existing slug comes out BYTE-IDENTICAL against the pre-repair code -- corn_cbot 7,616,
soybeans_cbot 3,155, cotton 2,755, rough_rice_cbot 884, canola_ice 222, i.e. the full 14,632-row
live table unchanged, with 11,449 rows added beside it.

CATALOG RIDER: the repair lights partitions for ``soft_red_winter_wheat_cbot`` and
``hard_red_spring_wheat_mgex``, which the projection enum ALREADY carries
(configs/silver/tables/silver_nass_annual.yaml:196) -- it was authored expecting wheat. The three
new cotton-class slugs (``upland_cotton``, ``pima_cotton``, ``cottonseed``) are NOT in that enum
and will be physically-present-but-hidden until a gated ``SET TBLPROPERTIES`` migration adds them,
exactly as ``canola_ice`` is today (SILVER-F020). That migration is the orchestrator's step.
"""
from __future__ import annotations

import math

import pandas as pd

from leviathan.common.logging import get_logger

logger = get_logger(__name__)

ACRE_TO_HA = 0.40468564224
LB_TO_MT = 0.00045359237
LB_PER_ACRE_TO_T_HA = LB_TO_MT / ACRE_TO_HA
SHORT_TON_TO_MT = 0.90718474

STAT_TO_VALUE_COL = {
    "AREA PLANTED": "area_planted_ha",
    "AREA HARVESTED": "area_harvested_ha",
    "YIELD": "yield_t_ha",
    "PRODUCTION": "production_mt",
}

STAT_TO_CV_COL = {
    "AREA PLANTED": "area_planted_cv_pct",
    "AREA HARVESTED": "area_harvested_cv_pct",
    "YIELD": "yield_cv_pct",
    "PRODUCTION": "production_cv_pct",
}

OUTPUT_COLUMNS = [
    "leviathan_slug",
    "country",
    "state",
    "year",
    "marketing_year",
    "area_planted_ha",
    "area_harvested_ha",
    "yield_t_ha",
    "production_mt",
    "area_planted_cv_pct",
    "area_harvested_cv_pct",
    "yield_cv_pct",
    "production_cv_pct",
    "source",
    # D-LD pre-step D-LD-9a additive tail (kept LAST to mirror the Glue ADD COLUMNS append and the
    # hand DDL's appended column -- the conab survey_release_date discipline, column for column).
    "release_date",
]

# The 14 columns the producer emitted BEFORE the D-LD pre-step, in order. Frozen here so a future
# edit that reorders or drops a pre-existing column is a test failure rather than a silent silver
# rewrite of 593 canonical objects.
PRE_DLD_OUTPUT_COLUMNS = OUTPUT_COLUMNS[:-1]

_REQUIRED_COLS = frozenset({
    "commodity_desc",
    "statisticcat_desc",
    "unit_desc",
    "agg_level_desc",
    "state_alpha",
    "year",
    "value",
    "cv_pct",
    "source",
})

_BUSHEL_WEIGHTS_LB = {
    "corn_cbot": 56.0,
    "soybeans_cbot": 60.0,
    "soft_red_winter_wheat_cbot": 60.0,
    "hard_red_winter_wheat_kcbt": 60.0,
    "hard_red_spring_wheat_mgex": 60.0,
}

_SECONDARY_UTILIZATION = frozenset({
    "FORAGE",
    "GREENCHOP",
    "HAY",
    "HAYLAGE",
    "SEED",
    "SILAGE",
    "STOVER",
})

_NON_FEATURE_UNITS = frozenset({
    "$",
    "PCT BY SIZE GROUP",
    "PCT BY TYPE",
})


# ---------------------------------------------------------------------------
# release_date -- the derived, conservative, never-leak vintage anchor (D-LD pre-step D-LD-9a).
# ---------------------------------------------------------------------------
# USDA NASS publishes the Crop Production ANNUAL SUMMARY for crop year Y in the SECOND WEEK OF
# JANUARY of Y+1 (the settled acreage/yield/production this table carries). We stamp the FIRST DAY
# OF THE MONTH STRICTLY AFTER that window -- Feb 1 of Y+1 -- so the derived date is ALWAYS on/after
# the real release: the point-in-time as-of guard can never LEAK a crop year before its summary was
# actually published. It withholds by at most ~3 weeks, which is the SAFE direction.
#
# WHAT THIS VINTAGE DELIBERATELY DOES NOT SERVE: the IN-SEASON prints. NASS also publishes
# Prospective Plantings (Mar 31) and Acreage (Jun 30) for the CURRENT crop year, and those numbers
# land in this row the moment the weekly job re-reads QuickStats (a 2026 row with planted/harvested
# acreage and NULL yield/production exists today). ONE row carries ONE knowledge date, and the row
# is OVERWRITTEN each January with the settled production -- so stamping it June would leak the
# settled figure on every historical replay. In-season US acreage/pace is silver_nass_crop_progress.
#
# The stamp is a pure function of the crop year, so it is stable across re-runs and byte-identical
# for an unchanged partition. (year offset, month, day) is the single knob.
_ANNUAL_SUMMARY_RELEASE = (1, 2, 1)


def _release_date(crop_year: object) -> str:
    """Conservative ISO ``YYYY-MM-DD`` annual-summary release stamp for one NASS crop year.

    Raises on a missing/unparseable crop year -- fail-loud, because a null PIT anchor would silently
    drop the row from the leakage-safe as-of guard (``null <= asof`` is UNKNOWN in SQL, and the
    Python oracle looks the column up on the row dict)."""
    if crop_year is None or (isinstance(crop_year, float) and math.isnan(crop_year)):
        raise ValueError(
            "NASS annual silver cannot derive a leakage-safe release_date from a null crop year"
        )
    try:
        year = int(crop_year)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"NASS annual crop year {crop_year!r} is not an integer; cannot derive release_date"
        ) from exc
    yr_off, month, day = _ANNUAL_SUMMARY_RELEASE
    return f"{year + yr_off:04d}-{month:02d}-{day:02d}"


def _is_all_class(class_name: str) -> bool:
    return class_name in {"", "ALL CLASSES"}


def _empty_output() -> pd.DataFrame:
    return pd.DataFrame(columns=OUTPUT_COLUMNS)


def _clean_text(value: object) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    text = str(value).strip()
    if text.lower() in {"nan", "none", "<na>"}:
        return ""
    return " ".join(text.upper().split())


# ---------------------------------------------------------------------------
# commodity_desc + class_desc -> leviathan slug (D-EC P0 class-lane repair, 2026-08-20).
# ---------------------------------------------------------------------------
# THE STRINGS BELOW ARE MEASURED, NOT GUESSED. The map this replaces keyed on commodity_desc
# values NASS does not publish -- "WHEAT, SPRING" and "WHEAT, WINTER" -- so all 3,495,679 bronze
# rows under commodity=soft_red_winter_wheat_cbot fell through to the trailing ``return None``
# and this lane emitted ZERO wheat rows for its entire life (projection census family
# "silver_nass_annual", data/dec_p0/projection_census.json: 13 (commodity_desc, class_desc) pairs,
# 100% None, proven by running the shipped transform on real bronze). NASS carries EVERY wheat
# class under commodity_desc='WHEAT' and puts the class on class_desc.
#
# The 13 measured wheat pairs, re-counted here on bronze years 1990/2022/2024 (NATIONAL+STATE,
# 25,271 rows): ALL CLASSES 18,519 | WINTER 4,457 | SPRING, (EXCL DURUM) 1,287 |
# SPRING, DURUM 714 | WINTER, RED, SOFT 86 | WINTER, RED, HARD 83 | SPRING, RED, HARD 31 |
# WINTER, WHITE, HARD 29 | WINTER, WHITE, SOFT 27 | WINTER, WHITE 11 | SPRING, WHITE, SOFT 10 |
# SPRING, WHITE, HARD 10 | SPRING, WHITE 7.
#
# THE CLASS->SLUG CONVENTION IS THE SIBLING'S, STRING FOR STRING. usda_nass_crop_progress.py:97-101
# reads the SAME source vocabulary and already produces healthy silver (soft_red_winter_wheat_cbot
# 35,567 rows, hard_red_spring_wheat_mgex 7,827), so WINTER and SPRING, (EXCL DURUM) map exactly
# where they map there -- no agronomic re-derivation is invented here.
#
# THE COARSENESS THAT BUYS, recorded rather than hidden: NASS's WINTER class is ALL winter wheat
# (hard red + soft red + white), so filing it under soft_red_winter_wheat_cbot files HRW and white
# winter wheat under the SRW node. That is the SAME conflation the crop-progress lane already
# carries (census md:567) and it is a property of the source, not of this file: NASS publishes no
# separate SRW area or yield series at all. Likewise SPRING, (EXCL DURUM) is all non-durum spring
# wheat, filed under the HRS node.
_WHEAT_WINTER_CLASS = "WINTER"
_WHEAT_SPRING_CLASS = "SPRING, (EXCL DURUM)"

# The DELIBERATE subset, enumerated instead of left to the trailing ``return None``. This dict is
# DOCUMENTATION WITH A TEST, never control flow: ``_canonical_slug`` does not read it, but the unit
# suite asserts that every measured (commodity_desc, class_desc) pair is either mapped above or
# named here, so a future class can never be dropped silently the way the wheat lane was.
#
# TWO KINDS OF RECORD LIVE HERE and they are NOT interchangeable (separated 2026-08-20):
#   * an EXACT PAIR -- ``(commodity_desc, class_desc)`` spelled exactly as NASS publishes it. It
#     refuses THAT ONE CLASS and says nothing about the commodity's other classes.
#   * a COMMODITY-LEVEL note -- ``(commodity_desc, _ANY_CLASS)``. The WHOLE commodity is out of
#     scope, every class of it, published or not yet published.
# The six commodity-level notes below used to be keyed ``("SORGHUM", "")`` and so on, which READ as
# exact pairs on the blank class and would have quietly stopped covering the commodity the day NASS
# began publishing a class on it. The sentinel makes the two kinds impossible to confuse; use
# :func:`_is_recorded_exclusion` to ask the question rather than indexing the dict directly.
_ANY_CLASS = "*"

_RECORDED_CLASS_EXCLUSIONS: dict[tuple[str, str], str] = {
    ("WHEAT", "ALL CLASSES"): (
        "aggregate of every wheat class; there is no all-wheat contract node, and under any single "
        "wheat slug it would double-count the WINTER and SPRING rows -- _validate_metric_uniqueness "
        "would then reject the partition outright. MEASURED CONSEQUENCE, from replaying all 161 "
        "bronze objects: the earliest year that yields a row is 1909, because 1866-1908 carry ALL "
        "CLASSES only -- that stretch of US wheat stays dark on this axis"
    ),
    ("WHEAT", "SPRING, DURUM"): (
        "durum has no contract node; the sibling refuses it identically (crop_progress:104-106)"
    ),
    ("WHEAT", ""): (
        "a wheat row carrying a BLANK or NULL class is UNCLASSIFIABLE and is refused in writing. "
        "NASS puts every wheat class on class_desc, so an empty class_desc names no class at all and "
        "gives no basis for choosing between the winter (soft_red_winter_wheat_cbot) and spring "
        "(hard_red_spring_wheat_mgex) nodes -- a guess here would file one class's acreage under the "
        "other's contract. NOTE THE ASYMMETRY, which is the whole reason this entry exists: for CORN, "
        "SOYBEANS, RICE and CANOLA a blank class IS the all-classes total (``_is_all_class``) and is "
        "KEPT, while the wheat lane reads blank as MISSING INFORMATION. The measured class census "
        "carries no blank-class wheat row, so this covers the null/NaN arrival path and the case where "
        "bronze has no class_desc column at all (the transform then substitutes '' for every row)"
    ),
    # The nine sub-classes below are MEASURED to carry PRODUCTION only -- no AREA, no YIELD -- and
    # 231 of their 294 sample rows are PCT BY TYPE shares that _NON_FEATURE_UNITS already drops,
    # leaving 63 rows in BU. Filing e.g. WINTER, RED, SOFT under soft_red_winter_wheat_cbot would
    # collide with that state-year's WINTER row on (slug, state, year, statisticcat) with a
    # DIFFERENT value, which is exactly the conflict _validate_metric_uniqueness raises on.
    # CONSEQUENCE, stated plainly: hard_red_winter_wheat_kcbt still has NO annual lane. NASS annual
    # publishes no hard-red-winter area or yield anywhere, only that production sliver, so lighting
    # kcbt is a decision about shipping a production-only partition -- not a map key.
    ("WHEAT", "WINTER, RED, HARD"): "production-only sub-class; would collide with WINTER",
    ("WHEAT", "WINTER, RED, SOFT"): "production-only sub-class; would collide with WINTER",
    ("WHEAT", "WINTER, WHITE"): "production-only sub-class; would collide with WINTER",
    ("WHEAT", "WINTER, WHITE, HARD"): "production-only sub-class; would collide with WINTER",
    ("WHEAT", "WINTER, WHITE, SOFT"): "production-only sub-class; would collide with WINTER",
    ("WHEAT", "SPRING, RED, HARD"): "production-only sub-class; would collide with SPRING",
    ("WHEAT", "SPRING, WHITE"): "production-only sub-class; would collide with SPRING",
    ("WHEAT", "SPRING, WHITE, HARD"): "production-only sub-class; would collide with SPRING",
    ("WHEAT", "SPRING, WHITE, SOFT"): "production-only sub-class; would collide with SPRING",
    ("RICE", "LONG GRAIN"): "milling class; rough_rice_cbot is fed by the ALL CLASSES total",
    # ---- COMMODITY-LEVEL notes: EVERY class of these six, not just the blank one ----
    ("SUGARCANE", _ANY_CLASS): "sugar crops are outside this contract-targeted table",
    ("SUGARBEETS", _ANY_CLASS): "sugar crops are outside this contract-targeted table",
    ("SORGHUM", _ANY_CLASS): "coarse-grain proxy; the bronze map buckets it, silver does not adopt it",
    ("OATS", _ANY_CLASS): "coarse-grain proxy; the bronze map buckets it, silver does not adopt it",
    ("BARLEY", _ANY_CLASS): "coarse-grain proxy; the bronze map buckets it, silver does not adopt it",
    ("SUNFLOWER", _ANY_CLASS): "oilseed proxy; no contract node on this axis",
}


def _is_recorded_exclusion(commodity_desc: str, class_desc: str) -> bool:
    """True when this drop is WRITTEN DOWN -- as its own exact pair, or under the commodity-level
    note that covers every class of that commodity.

    The one supported way to query :data:`_RECORDED_CLASS_EXCLUSIONS`: indexing it directly is how
    the two record kinds get confused. Inputs are the CLEANED (upper, collapsed) strings that
    ``_canonical_slug`` works with."""
    return (
        (commodity_desc, class_desc) in _RECORDED_CLASS_EXCLUSIONS
        or (commodity_desc, _ANY_CLASS) in _RECORDED_CLASS_EXCLUSIONS
    )


def _canonical_slug(commodity_desc: object, class_desc: object) -> str | None:
    """Map one (``commodity_desc``, ``class_desc``) pair to a leviathan slug, or ``None`` to drop.

    Every ``None`` this returns for a MEASURED pair is named in ``_RECORDED_CLASS_EXCLUSIONS``
    above with its reason -- the deliberate-subset pattern. Silence is what produced the
    never-once-run wheat lane."""
    commodity = _clean_text(commodity_desc)
    class_name = _clean_text(class_desc)

    if commodity == "CORN":
        return "corn_cbot" if _is_all_class(class_name) else None
    if commodity == "SOYBEANS":
        return "soybeans_cbot" if _is_all_class(class_name) else None
    if commodity == "RICE":
        return "rough_rice_cbot" if _is_all_class(class_name) else None
    if commodity == "CANOLA":
        return "canola_ice" if _is_all_class(class_name) else None

    if commodity == "COTTON":
        # ``cotton`` KEEPS its ALL CLASSES basis. The sibling calls UPLAND ``cotton``, and this file
        # cannot follow it there without either double-counting (ALL CLASSES = upland + pima, so both
        # under one slug is the conflict the uniqueness validator raises on) or deleting history:
        # measured on bronze year 1920, ALL CLASSES carries 70 NATIONAL/STATE rows against UPLAND's 6.
        # So UPLAND and PIMA get slugs of their OWN -- the 23,214 + 5,424 measured rows this producer
        # used to throw away -- and the divergence from the sibling is recorded right here.
        if _is_all_class(class_name):
            return "cotton"
        if class_name == "UPLAND":
            return "upland_cotton"
        if class_name == "PIMA":
            return "pima_cotton"
        # cottonseed is a DECLARED tier-1 context node (commodity_hierarchy.yaml:134,184) with 2,956
        # measured dark propositions and no numeric lane anywhere in the estate; NASS holds 4,460
        # NATIONAL/STATE rows of it (PRODUCTION in TONS only -- no area, no yield).
        if class_name == "COTTONSEED":
            return "cottonseed"
        return None

    if commodity == "WHEAT":
        if class_name == _WHEAT_WINTER_CLASS:
            return "soft_red_winter_wheat_cbot"
        if class_name == _WHEAT_SPRING_CLASS:
            return "hard_red_spring_wheat_mgex"
        return None

    # Coarse-grain proxies, sunflower, and sugar crops reach this file only because the BRONZE map
    # buckets them onto an existing partition; they are excluded here, and named above.
    return None


def _filter_primary_rows(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()

    if "source_desc" in result.columns:
        source_desc = result["source_desc"].map(_clean_text)
        if (source_desc == "SURVEY").any():
            result = result.loc[source_desc == "SURVEY"].copy()

    if "domain_desc" in result.columns:
        domain = result["domain_desc"].map(_clean_text)
        if (domain == "TOTAL").any():
            result = result.loc[domain == "TOTAL"].copy()

    if "domaincat_desc" in result.columns:
        domaincat = result["domaincat_desc"].map(_clean_text)
        if (domaincat == "NOT SPECIFIED").any():
            result = result.loc[domaincat == "NOT SPECIFIED"].copy()

    if "reference_period_desc" in result.columns:
        reference_period = result["reference_period_desc"].map(_clean_text)
        if (reference_period == "YEAR").any():
            result = result.loc[reference_period == "YEAR"].copy()

    if "prodn_practice_desc" in result.columns:
        prodn = result["prodn_practice_desc"].map(_clean_text)
        result = result.loc[prodn.isin({"", "ALL PRODUCTION PRACTICES"})].copy()

    if "util_practice_desc" in result.columns:
        util = result["util_practice_desc"].map(_clean_text)
        result = result.loc[~util.isin(_SECONDARY_UTILIZATION)].copy()

    return result


def _bushel_weight(slug: str, unit_desc: str) -> float:
    try:
        return _BUSHEL_WEIGHTS_LB[slug]
    except KeyError as exc:
        raise ValueError(
            f"NASS annual unit {unit_desc!r} requires a bushel weight for {slug!r}"
        ) from exc


def _convert_value(row: pd.Series) -> float:
    value = row["value"]
    if pd.isna(value):
        return float("nan")

    stat = row["statisticcat_desc_norm"]
    unit = row["unit_desc_norm"]
    slug = row["leviathan_slug"]
    numeric = float(value)

    if stat in {"AREA PLANTED", "AREA HARVESTED"}:
        if unit == "ACRES":
            return numeric * ACRE_TO_HA
        if unit in {"HECTARES", "HA"}:
            return numeric
        raise ValueError(f"Unsupported NASS area unit {unit!r} for {slug!r}")

    if stat == "YIELD":
        # BU / PLANTED ACRE is the third measured bushel denominator (51 rows in the wheat yield-unit
        # census against BU / ACRE 29,945 and BU / NET PLANTED ACRE 5,238). It raised here the moment
        # the class map was repaired, because until then no wheat row ever reached this converter.
        if unit in {"BU / ACRE", "BU / NET PLANTED ACRE", "BU / PLANTED ACRE"}:
            return numeric * _bushel_weight(slug, unit) * LB_PER_ACRE_TO_T_HA
        if unit in {"LB / ACRE", "LB / NET PLANTED ACRE"}:
            return numeric * LB_PER_ACRE_TO_T_HA
        if unit == "CWT / ACRE":
            return numeric * 100.0 * LB_PER_ACRE_TO_T_HA
        if unit in {"TONS / ACRE", "TON / ACRE"}:
            return numeric * 2000.0 * LB_PER_ACRE_TO_T_HA
        raise ValueError(f"Unsupported NASS yield unit {unit!r} for {slug!r}")

    if stat == "PRODUCTION":
        if unit == "BU":
            return numeric * _bushel_weight(slug, unit) * LB_TO_MT
        if unit == "LB":
            return numeric * LB_TO_MT
        if unit == "CWT":
            return numeric * 100.0 * LB_TO_MT
        if unit in {"TONS", "TON"}:
            return numeric * SHORT_TON_TO_MT
        if unit == "480 LB BALES":
            return numeric * 480.0 * LB_TO_MT
        if unit in {"METRIC TONS", "METRIC TONNES", "MT"}:
            return numeric
        raise ValueError(f"Unsupported NASS production unit {unit!r} for {slug!r}")

    raise ValueError(f"Unsupported NASS statistic category {stat!r}")


# NASS publishes the SAME (slug, state, year) yield under more than one denominator -- measured on
# bronze wheat 1990/2022/2024, BU / ACRE (1,417 rows) and BU / NET PLANTED ACRE (173) collide on 116
# identical keys, and the cotton partition does the same with the LB pair. The old rank named only
# the two NET PLANTED units, so BU / ACRE and BU / PLANTED ACRE tied at rank 0 with DIFFERENT
# converted values and _validate_metric_uniqueness raised -- the second crash that fired the moment
# the class map was fixed.
#
# The fix ranks the DENOMINATOR, not the whole unit string, which gives a TOTAL order over every
# observed yield unit at once: BU|LB|CWT|TONS / ACRE -> 0, ... / NET PLANTED ACRE -> 1,
# ... / PLANTED ACRE -> 2, anything unobserved -> last. "/ ACRE" stays the winner exactly as before
# (it is the standard published yield, per harvested acre), so no existing partition changes value.
_YIELD_DENOMINATOR_PREFERENCE = (
    "ACRE",
    "NET PLANTED ACRE",
    "PLANTED ACRE",
)
_UNRANKED_YIELD_DENOMINATOR = len(_YIELD_DENOMINATOR_PREFERENCE)


def _yield_denominator(unit: str) -> str:
    """The part of a NASS yield unit after the slash ('BU / NET PLANTED ACRE' -> 'NET PLANTED ACRE')."""
    _, _, denominator = unit.partition("/")
    return denominator.strip()


def _metric_preference_rank(row: pd.Series) -> int:
    if row["statisticcat_desc_norm"] != "YIELD":
        return 0
    denominator = _yield_denominator(row["unit_desc_norm"])
    try:
        return _YIELD_DENOMINATOR_PREFERENCE.index(denominator)
    except ValueError:
        return _UNRANKED_YIELD_DENOMINATOR


def _prefer_metric_rows(df: pd.DataFrame) -> pd.DataFrame:
    key_cols = ["leviathan_slug", "state", "year", "statisticcat_desc_norm"]
    duplicate_mask = df.duplicated(subset=key_cols, keep=False)
    if not duplicate_mask.any():
        return df

    work = df.copy()
    work["_metric_preference_rank"] = work.apply(_metric_preference_rank, axis=1)
    best_rank = work.groupby(key_cols, dropna=False)["_metric_preference_rank"].transform("min")
    work = work.loc[work["_metric_preference_rank"] == best_rank].copy()
    return work.drop(columns=["_metric_preference_rank"])


def _validate_metric_uniqueness(df: pd.DataFrame) -> pd.DataFrame:
    key_cols = ["leviathan_slug", "state", "year", "statisticcat_desc_norm"]
    duplicate_mask = df.duplicated(subset=key_cols, keep=False)
    if not duplicate_mask.any():
        return df

    duplicates = df.loc[duplicate_mask].copy()
    conflicts: list[tuple[object, ...]] = []
    for key, group in duplicates.groupby(key_cols, dropna=False):
        value_count = group["converted_value"].dropna().nunique()
        cv_count = group["cv_pct"].dropna().nunique()
        if value_count > 1 or cv_count > 1:
            conflicts.append(key)

    if conflicts:
        preview = ", ".join(str(c) for c in conflicts[:5])
        raise ValueError(
            "NASS annual silver found conflicting duplicate metric rows for "
            f"{preview}. Tighten source/class/practice filters before pivoting."
        )

    return df.drop_duplicates(subset=key_cols, keep="last").copy()


def transform_nass_annual_bronze_to_silver(df: pd.DataFrame) -> pd.DataFrame:
    """Convert bronze USDA NASS annual rows into wide silver production features."""
    missing = _REQUIRED_COLS - set(df.columns)
    if missing:
        raise ValueError(
            f"NASS annual bronze DataFrame is missing required columns: {missing}. "
            f"Got: {list(df.columns)}"
        )
    if df.empty:
        return _empty_output()

    work = df.copy()
    work["agg_level_desc_norm"] = work["agg_level_desc"].map(_clean_text)
    work["statisticcat_desc_norm"] = work["statisticcat_desc"].map(_clean_text)
    work["unit_desc_norm"] = work["unit_desc"].map(_clean_text)

    work = work.loc[
        work["agg_level_desc_norm"].isin({"NATIONAL", "STATE"})
        & work["statisticcat_desc_norm"].isin(STAT_TO_VALUE_COL)
    ].copy()
    work = work.loc[~work["unit_desc_norm"].isin(_NON_FEATURE_UNITS)].copy()
    if work.empty:
        return _empty_output()

    work = _filter_primary_rows(work)
    if work.empty:
        return _empty_output()

    class_series = (
        work["class_desc"]
        if "class_desc" in work.columns
        else pd.Series([""] * len(work), index=work.index)
    )
    work["leviathan_slug"] = [
        _canonical_slug(commodity, class_name)
        for commodity, class_name in zip(work["commodity_desc"], class_series)
    ]
    work = work.dropna(subset=["leviathan_slug"]).copy()
    if work.empty:
        return _empty_output()

    work["value"] = pd.to_numeric(
        work["value"].astype(str).str.replace(",", "", regex=False),
        errors="coerce",
    )
    work["cv_pct"] = pd.to_numeric(
        work["cv_pct"].astype(str).str.replace(",", "", regex=False),
        errors="coerce",
    )
    work["year"] = pd.to_numeric(work["year"], errors="coerce")
    work = work.dropna(subset=["year"]).copy()
    work["year"] = work["year"].astype(int)
    work["marketing_year"] = work["year"]
    work["country"] = "united_states"
    work["state"] = work["state_alpha"].where(
        work["agg_level_desc_norm"] != "NATIONAL",
        other="US",
    )
    work["state"] = work["state"].fillna("").astype(str).str.strip().str.upper()
    work = work[work["state"] != ""].copy()
    work["source"] = "usda_nass"

    work["converted_value"] = work.apply(_convert_value, axis=1)
    work = _prefer_metric_rows(work)
    work = _validate_metric_uniqueness(work)

    index_cols = [
        "leviathan_slug",
        "country",
        "state",
        "year",
        "marketing_year",
        "source",
    ]

    values = work.pivot(
        index=index_cols,
        columns="statisticcat_desc_norm",
        values="converted_value",
    ).rename(columns=STAT_TO_VALUE_COL)

    cvs = work.pivot(
        index=index_cols,
        columns="statisticcat_desc_norm",
        values="cv_pct",
    ).rename(columns=STAT_TO_CV_COL)

    silver = pd.concat([values, cvs], axis=1).reset_index()

    # D-LD pre-step D-LD-9a: the derived vintage anchor. Stamped from the CROP YEAR (an int by
    # construction above) BEFORE the OUTPUT_COLUMNS backfill below, so it is never NA-filled --
    # a null here would drop the row from the as-of guard instead of failing loudly.
    silver["release_date"] = [_release_date(y) for y in silver["year"]]

    for col in OUTPUT_COLUMNS:
        if col not in silver.columns:
            silver[col] = pd.NA

    silver = silver[OUTPUT_COLUMNS].sort_values(
        ["leviathan_slug", "state", "year"],
        kind="stable",
    )
    logger.info("NASS annual silver transform produced %d rows", len(silver))
    return silver.reset_index(drop=True)
