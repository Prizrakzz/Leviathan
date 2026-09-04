"""Silver transform for USDA PSD -- the LONG companion table (silver_psd_attributes).

``silver_psd`` (see :mod:`leviathan.transforms.bronze_to_silver.usda_psd`) pivots
EIGHT attributes into MT-denominated columns and drops everything else.  Measured
on the 2026-08-13 bulk object, that is 11 of the 69 attribute labels USDA
publishes; the other 58 -- Crush, the whole demand decomposition, the TY trade
trio, the variety splits, the rates -- are discarded at step 6 every day.

This module is the other half: ONE ROW PER
``(leviathan_slug, country, market_year, wasde_release_month, release_date,
attribute)`` with the value in its NATIVE unit.

Design notes
------------
* **Native units, no conversion, no unit guard.**  The wide producer's step-7
  guard RAISES on any ``unit_desc`` absent from ``_UNIT_FACTOR``, and
  ``(PERCENT)`` / ``(RATIO)`` are DELIBERATELY absent -- they are the fence that
  keeps the ``(1000 HEAD)`` refusal honest.  A long table that converted nothing
  needs no factor at all, so the fence is never approached, let alone widened.
  ``Extr. Rate, 999.9999`` (37,886 in-scope rows), ``Stocks-to-Use`` (7,777) and
  ``Seed to Lint Ratio`` (2,341) ride through with their units intact.
  The same mechanism RETIRES the ``(1000 HEAD)`` problem rather than dodging it:
  ``Cows In Milk`` (attribute 6, 1,917 rows on the MAPPED code 223000) is a head
  count, and a head count in a table with a per-row ``unit`` column is an honest
  row -- it is only a lie in an all-tonnes schema.

* **The branch point.**  Everything up to and including the wide producer's
  step-5 consumption remaps is shared, via
  :func:`~leviathan.transforms.bronze_to_silver.usda_psd.prepare_psd_combined_frame`.
  The branch is BEFORE step 6's ``isin(_TARGET_ATTRS)`` filter, which is what
  makes the 58 unserved labels reachable at all.

* **The emitted label is USDA's OWN.**  The shared prefix normalises three
  consumption labels onto "Domestic Consumption" for the wide pivot; the long
  table emits ``attribute_desc_native`` instead, so sugar keeps "Total
  Disappearance" (126), cotton keeps "Domestic Use" (142) and fresh citrus keeps
  "Fresh Dom. Consumption" (135).  Reason: ``attribute_id`` is in the schema, and
  a table where one label spans four ids is a table whose metric column cannot be
  joined to the source's own key.  The numbers card quotes these spellings
  verbatim, so they must be the spellings the source prints.

* **R4 -- attribute-aware fan-out.**  See :data:`_PSD_ATTR_FANOUT` below.  This is
  the rule that ships WITH the table or the widening degrades it.

No S3 or AWS dependencies -- pure data transformation.
"""
from __future__ import annotations

from typing import Literal

import pandas as pd

from leviathan.common.logging import get_logger
from leviathan.transforms.bronze_to_silver.usda_psd import (
    _PSD_COMMODITY_TO_SLUGS,
    prepare_psd_combined_frame,
)

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# R4 -- ATTRIBUTE-AWARE FAN-OUT
# ---------------------------------------------------------------------------
# R2 (usda_psd.py ~:100-109) makes slug FAN-OUT legal: one commodity code may
# emit its balance sheet under many slugs, and nine codes do.  For the WIDE
# table that is sound, because every one of its eight attributes is a property
# of the whole USDA sheet -- "Production" on the green-coffee sheet is total
# green-coffee production and stamping it on all three coffee slugs says only
# "this contract's underlying commodity has this global balance", which is the
# documented intent of the fan-out.
#
# THE LONG TABLE BREAKS THAT ASSUMPTION, and it does so on MEASURED data, not in
# principle.  Widening from 8 attributes to all 69 admits attributes that are
# specific to a PROPER SUBSET of a code's slug list:
#
#   711100 "Coffee, Green" -> [arabica_coffee, brazilian_arabica_coffee,
#                              robusta_coffee]
#       29  Arabica Production    (4,616 rows/release)  -- arabica only
#       53  Robusta Production    (4,616)               -- robusta only
#       56  Other Production      (4,616)               -- NEITHER (the residual
#                                                        varieties leg; no slug)
#
#   612000 "Sugar, Centrifugal" -> [raw_sugar, white_sugar]
#       64  Raw Imports           (9,501 rows/release)  -- the RAW leg only
#       89  Raw Exports           (9,501)               -- the RAW leg only
#       74  Refined Imp.(Raw Val) (9,501)               -- the REFINED leg only
#       99  Refined Exp.(Raw Val) (9,501)               -- the REFINED leg only
#
# A naive widening writes "Arabica Production" onto ``robusta_coffee`` and "Raw
# Exports" onto ``white_sugar``: 65,700 MANUFACTURED FALSE ROWS per release, on
# LIVE contract slugs (ICE Robusta, ICE #5 white sugar).  That is strictly worse
# than the silent drop R2 guards -- a dropped balance sheet is missing data, a
# manufactured row is wrong data that reads as published.
#
# MEASURED, and this is the finding that sizes R4: exactly TWO of the nine
# multi-slug codes carry a subset-specific attribute.  The other seven fan to
# INTERCHANGEABLE TRADING VENUES for one and the same subject -- wheat's four
# class contracts, corn's five, soybeans' three, and the meal/oil/canola/palm
# pairs -- and USDA publishes NOTHING at class or venue grain for them, so there
# is nothing to mis-fan.  (Wheat classes ARE a real variety distinction; the bulk
# file simply has no class-specific attribute, so the hazard cannot arise there.)
#
# THE POSTURE, and why it is not simply "enumerate the two exceptions":
#
#   * Every multi-slug code MUST be declared in EXACTLY ONE of
#     :data:`_PSD_ATTR_FANOUT` (heterogeneous: adjudicate per attribute) or
#     :data:`_PSD_HOMOGENEOUS_FANOUT_CODES` (venue-only: fan everything).  A code
#     in neither RAISES.  This is the fail-closed half that matters most,
#     because the realistic future edit is not "USDA renames an attribute" but
#     "someone adds a second slug to an existing code" -- and that edit turns a
#     safe single-slug code into an unadjudicated multi-slug one silently.
#
#   * Within a heterogeneous code, EVERY attribute id USDA publishes today is
#     enumerated, including the sheet-level ones that fan to all slugs.  A pair
#     the registry does not cover is UNCOVERED, and the default policy is a
#     NAMED, COUNTED, LOGGED DROP -- better a named drop than a manufactured row.
#     ``on_uncovered="raise"`` is available for a backfill that wants the
#     transform to stop instead.  The default is not "raise" because a new USDA
#     coffee label would then take the WHOLE daily transform down for every
#     commodity -- the same blast radius R1 warns about one module over.
#
#   * The registry keys on ``attribute_id``, NOT on ``attribute_desc``.  A
#     string-identity join loses a source-side rename silently; the id is USDA's
#     stable key.  The label is carried alongside in
#     :data:`_PSD_ATTR_ID_TO_DESC_PIN` as a LOGGED TRIPWIRE: if the source ever
#     re-labels id 29, R4 keeps working and the rename is reported.
#
# R4 takes R2's exact test posture: a static map assertion AND a live proof of
# the failure it prevents (tests/unit/test_psd_attributes_long.py).

# Slug groupings used by the coffee and sugar adjudications.  Spelled from
# _PSD_COMMODITY_TO_SLUGS and asserted equal to it by a test -- never re-typed.
_COFFEE_ARABICA_SLUGS: frozenset[str] = frozenset({
    "arabica_coffee", "brazilian_arabica_coffee",
})
_COFFEE_ROBUSTA_SLUGS: frozenset[str] = frozenset({"robusta_coffee"})
_COFFEE_ALL_SLUGS: frozenset[str] = _COFFEE_ARABICA_SLUGS | _COFFEE_ROBUSTA_SLUGS

_SUGAR_RAW_SLUGS: frozenset[str] = frozenset({"raw_sugar"})
_SUGAR_WHITE_SLUGS: frozenset[str] = frozenset({"white_sugar"})
_SUGAR_ALL_SLUGS: frozenset[str] = _SUGAR_RAW_SLUGS | _SUGAR_WHITE_SLUGS

# An EMPTY frozenset is a first-class value here: "this attribute is true of no
# slug this code fans to".  It is a DECLARED drop, not an omission, and it is
# what separates "we adjudicated and the answer is nobody" from "nobody looked".
_NO_SLUG: frozenset[str] = frozenset()

_PSD_ATTR_FANOUT: dict[int, dict[int, frozenset[str]]] = {
    # =======================================================================
    # 711100 "Coffee, Green" -> arabica_coffee / brazilian_arabica_coffee /
    #                           robusta_coffee
    # All 19 attribute ids the 2026-08-13 object publishes for this code.
    # =======================================================================
    711100: {
        20:  _COFFEE_ALL_SLUGS,      # Beginning Stocks       -- sheet level
        28:  _COFFEE_ALL_SLUGS,      # Production             -- total green coffee
        29:  _COFFEE_ARABICA_SLUGS,  # Arabica Production     -- THE HAZARD
        53:  _COFFEE_ROBUSTA_SLUGS,  # Robusta Production     -- THE HAZARD
        56:  _NO_SLUG,               # Other Production       -- the residual leg:
                                     #   neither arabica nor robusta, and there is
                                     #   no third coffee slug to carry it.  4,616
                                     #   rows/release declined by name.
        57:  _COFFEE_ALL_SLUGS,      # Imports
        58:  _COFFEE_ALL_SLUGS,      # Bean Imports           -- FORM, not variety:
                                     #   bean / roast+ground / soluble split the
                                     #   same sheet by processing stage and every
                                     #   stage exists for both varieties.
        75:  _COFFEE_ALL_SLUGS,      # Roast & Ground Imports
        82:  _COFFEE_ALL_SLUGS,      # Soluble Imports
        86:  _COFFEE_ALL_SLUGS,      # Total Supply
        88:  _COFFEE_ALL_SLUGS,      # Exports
        90:  _COFFEE_ALL_SLUGS,      # Bean Exports
        107: _COFFEE_ALL_SLUGS,      # Roast & Ground Exports
        114: _COFFEE_ALL_SLUGS,      # Soluble Exports
        125: _COFFEE_ALL_SLUGS,      # Domestic Consumption
        141: _COFFEE_ALL_SLUGS,      # Rst,Ground Dom. Consum
        154: _COFFEE_ALL_SLUGS,      # Soluble Dom. Cons.
        176: _COFFEE_ALL_SLUGS,      # Ending Stocks
        178: _COFFEE_ALL_SLUGS,      # Total Distribution
    },
    # =======================================================================
    # 612000 "Sugar, Centrifugal" -> raw_sugar / white_sugar
    # All 16 attribute ids the 2026-08-13 object publishes for this code.
    # =======================================================================
    612000: {
        20:  _SUGAR_ALL_SLUGS,       # Beginning Stocks       -- sheet level
        28:  _SUGAR_ALL_SLUGS,       # Production             -- centrifugal total
        30:  _SUGAR_ALL_SLUGS,       # Beet Sugar Production  -- CROP SOURCE, not
                                     #   refining stage: beet and cane sugar are
                                     #   each produced in raw AND refined form, so
                                     #   this splits the sheet on an axis that is
                                     #   ORTHOGONAL to raw/white.  Fans to both --
                                     #   the one adjudication here that a reader
                                     #   might expect to be a restriction and is
                                     #   deliberately not.
        43:  _SUGAR_ALL_SLUGS,       # Cane Sugar Production  -- same reason as 30
        57:  _SUGAR_ALL_SLUGS,       # Imports
        64:  _SUGAR_RAW_SLUGS,       # Raw Imports            -- THE HAZARD
        74:  _SUGAR_WHITE_SLUGS,     # Refined Imp.(Raw Val)  -- THE HAZARD.  The
                                     #   "(Raw Val)" is an ACCOUNTING BASIS (raw
                                     #   sugar equivalent tonnage), not the
                                     #   subject: what moved is refined sugar.
        86:  _SUGAR_ALL_SLUGS,       # Total Supply
        88:  _SUGAR_ALL_SLUGS,       # Exports
        89:  _SUGAR_RAW_SLUGS,       # Raw Exports            -- THE HAZARD
        99:  _SUGAR_WHITE_SLUGS,     # Refined Exp.(Raw Val)  -- THE HAZARD
        126: _SUGAR_ALL_SLUGS,       # Total Disappearance    (the wide table's
                                     #   consumption_mt source for sugar)
        139: _SUGAR_ALL_SLUGS,       # Human Dom. Consumption
        151: _SUGAR_ALL_SLUGS,       # Other Disappearance
        176: _SUGAR_ALL_SLUGS,       # Ending Stocks
        178: _SUGAR_ALL_SLUGS,       # Total Distribution
    },
}

# The multi-slug codes whose slug list is a set of INTERCHANGEABLE TRADING VENUES
# for one and the same USDA subject.  Every attribute fans to every slug because
# the source publishes nothing at venue or class grain -- there is no fact here
# that belongs to one slug and not another.  Listed explicitly so that "this code
# needs no adjudication" is a DECISION on the page, not the absence of one.
_PSD_HOMOGENEOUS_FANOUT_CODES: frozenset[int] = frozenset({
    410000,   # Wheat            -> HRW KCBT / SRW CBOT / HRS MGEX / French MATIF
              #                     (the classes are real, the bulk file has no
              #                      class-specific attribute -- 15 ids, all sheet
              #                      level.  If USDA ever prints one, this code
              #                      MOVES to _PSD_ATTR_FANOUT.)
    440000,   # Corn             -> CBOT / Campinas BMF / MATIF / JSE white / JSE yellow
    2222000,  # Oilseed, Soybean -> CBOT / DCE no.1 / DCE no.2
    813100,   # Meal, Soybean    -> CBOT / DCE
    4232000,  # Oil, Soybean     -> CBOT / DCE
    2226000,  # Oilseed, Rapeseed-> canola ICE / French rapeseed MATIF
    4243000,  # Oil, Palm        -> palm olein DCE / Malaysian CPO CME
})

# LOGGED TRIPWIRE, not a join key.  The registry keys on attribute_id because a
# string join loses a rename silently (and PSD labels carry punctuation and
# spacing that make them fragile: "Rst,Ground Dom. Consum",
# "Refined Imp.(Raw Val)", "Extr. Rate, 999.9999").  These are the byte-exact
# spellings the 2026-08-13 object prints for the ids R4 adjudicates; a mismatch
# at transform time is WARNED, never fatal, and never changes the fan-out.
_PSD_ATTR_ID_TO_DESC_PIN: dict[int, str] = {
    29:  "Arabica Production",
    53:  "Robusta Production",
    56:  "Other Production",
    64:  "Raw Imports",
    74:  "Refined Imp.(Raw Val)",
    89:  "Raw Exports",
    99:  "Refined Exp.(Raw Val)",
    30:  "Beet Sugar Production",
    43:  "Cane Sugar Production",
}

# ---------------------------------------------------------------------------
# The unit_desc the SOURCE gets wrong -- a hazard the wide table never met
# ---------------------------------------------------------------------------
# The wide producer is protected by an accident: its step-6 attribute filter
# removes these rows before its step-7 unit guard could be fooled.  The long
# table has no attribute filter, so it meets them.
#
# ``Milling Rate (.9999)`` (attribute 182, 7,616 rows/release on code 422110
# "Rice, Milled") is a RATE carrying ``unit_desc = "(1000 MT)"``.  Measured
# values: min 0 / median 6,500 / max 7,561 -- a 1e4-scaled milling rate (~0.65),
# not a tonnage.  Because "(1000 MT)" is a KNOWN unit, nothing anywhere trips: a
# consumer reading the long table's native-unit contract in good faith reads
# 6,500 thousand tonnes of rice and is wrong by ~1e7.
#
# The long table's contract is "value in its NATIVE unit plus unit_desc".  For
# this attribute that contract CANNOT be honoured -- the native unit label is
# false at the source -- so the row is REFUSED BY NAME rather than shipped with a
# unit that lies.  Same doctrine as R4's ``_NO_SLUG``: better a named drop than a
# manufactured row.  Reopen by adding a value-scale column to the schema (which
# would also give ``Extr. Rate, 999.9999`` and ``Seed to Lint Ratio`` a home for
# their own scale oddities), NOT by inventing a unit string here.
_PSD_UNIT_MISLABELLED_ATTR_IDS: dict[int, str] = {
    182: (
        "Milling Rate (.9999) (attribute 182, code 422110, 7,616 rows/release). "
        "A 1e4-scaled RATE published under unit_desc '(1000 MT)'. Measured "
        "min 0 / median 6500 / max 7561 -- a milling rate of ~0.65, not 6.5 MMT. "
        "The native-unit contract cannot be honoured for this attribute, so the "
        "rows are declined by name. Reopen with a value-scale column, never by "
        "rewriting unit_desc."
    ),
}

# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------

_SILVER_PSD_ATTR_COLS: list[str] = [
    "leviathan_slug",
    "country",
    "market_year",
    "wasde_release_month",
    "release_date",
    "attribute",
    "attribute_id",
    "value",
    "unit",
]

# The declared grain.  wasde_release_month IS part of it -- silver_wasde shipped
# without its full grain and the latest-vintage ROW_NUMBER collapsed across
# regions, undetectable for months (see the silver_wasde card's 2026-07-05 note).
# The identical exposure exists here: without wasde_release_month, one arbitrary
# WASDE vintage per (slug, country, market_year, attribute) would win.
#
# release_date JOINED THE GRAIN 2026-09-04 (lane E, the honest-clock re-baseline).
# wasde_release_month is now the CALENDAR month of the release, not an
# MY-relative index, so two releases twelve months apart SHARE it: without
# release_date the declared key is not a key, and the dedup below would delete a
# real vintage rather than a re-print.  The cost is stated rather than assumed --
# strictly more vintages survive, so the served and physical row counts both move
# UP and the pg mirror grows with them on an instance with storage autoscaling
# OFF.  The measurement rides gate G2 with a declared ceiling; it is never a
# projection.
_GRAIN_COLS: list[str] = [
    "leviathan_slug",
    "country",
    "market_year",
    "wasde_release_month",
    "release_date",
    "attribute",
]


# ---------------------------------------------------------------------------
# Public transform
# ---------------------------------------------------------------------------


def transform_psd_attributes_bronze_to_silver(
    dfs: list[pd.DataFrame],
    *,
    calendar: dict[str, int],
    on_uncovered: Literal["drop", "raise"] = "drop",
    counters: dict | None = None,
) -> pd.DataFrame:
    """Convert bronze PSD DataFrames into the LONG attribute companion table.

    Args:
        dfs: List of bronze DataFrames (one per release_date partition).  Must be
            non-empty.  Requires ``attribute_id`` in addition to the wide
            producer's required columns.
        calendar: ``{'YYYY-MM': day}`` from the REGISTERED silver_wasde
            partitions, threaded straight through to the shared prefix and the
            one clock.  Keyword-only with NO DEFAULT -- this is the FOURTH of the
            four signature edits the honest clock needs, and naming it separately
            is what stops the long producer drifting away from the wide one.
        on_uncovered: What to do with a (heterogeneous multi-slug code, attribute)
            pair the R4 registry does not cover.  ``"drop"`` (default) declines
            the rows with a WARNING naming the exact pair; ``"raise"`` stops the
            transform.  Neither option ever fans an unadjudicated attribute.
        counters: Optional dict the shared prefix fills with the clock run
            counters, for the batch task's structured log.

    Returns:
        Long DataFrame with :data:`_SILVER_PSD_ATTR_COLS` columns, unique on
        :data:`_GRAIN_COLS`.

    Raises:
        ValueError: If *dfs* is empty, required columns are missing, a multi-slug
            commodity code is declared in NEITHER R4 register, a surviving row
            has a null/empty ``unit_desc``, or *on_uncovered* is ``"raise"`` and
            an uncovered pair is found.
    """
    _assert_r4_registers_cover_every_multi_slug_code()

    combined = prepare_psd_combined_frame(
        dfs,
        extra_required=frozenset({"attribute_id"}),
        calendar=calendar,
        counters=counters,
    )
    if combined.empty:
        return _empty_psd_attributes()

    n_in = len(combined)
    combined["attribute_id"] = pd.to_numeric(combined["attribute_id"], errors="coerce")

    # -----------------------------------------------------------------------
    # R4. Attribute-aware fan-out
    # -----------------------------------------------------------------------
    combined = _apply_r4(combined, on_uncovered=on_uncovered)
    if combined.empty:
        logger.warning("PSD attributes transform: no rows remain after R4")
        return _empty_psd_attributes()

    # -----------------------------------------------------------------------
    # Refuse the attributes whose SOURCE unit label is false (see the register).
    # -----------------------------------------------------------------------
    mislabelled = combined["attribute_id"].isin(_PSD_UNIT_MISLABELLED_ATTR_IDS)
    n_mislabelled = int(mislabelled.sum())
    if n_mislabelled:
        for attr_id, why in _PSD_UNIT_MISLABELLED_ATTR_IDS.items():
            n = int((combined["attribute_id"] == attr_id).sum())
            if n:
                logger.warning(
                    "PSD attributes transform: declining %d rows of attribute %d -- %s",
                    n, attr_id, why,
                )
        combined = combined[~mislabelled].copy()

    if combined.empty:
        logger.warning("PSD attributes transform: no rows remain after the unit-label refusal")
        return _empty_psd_attributes()

    # -----------------------------------------------------------------------
    # The one assertion a table with no unit conversion still owes its readers:
    # every row must actually CARRY a unit.  There is no _UNIT_FACTOR lookup to
    # fail loudly here, so an empty unit would ship a bare number.
    # -----------------------------------------------------------------------
    unit = combined["unit_desc"]
    bad_unit = unit.isna() | (unit.astype(str).str.strip() == "")
    if bool(bad_unit.any()):
        offenders = sorted(
            set(
                zip(
                    combined.loc[bad_unit, "commodity_code"].tolist(),
                    combined.loc[bad_unit, "attribute_desc_native"].tolist(),
                )
            )
        )[:10]
        raise ValueError(
            f"PSD bronze carries {int(bad_unit.sum())} in-scope rows with a null/empty "
            f"unit_desc; the long table stores values in their NATIVE unit and cannot "
            f"emit a unitless number. First offenders (commodity_code, attribute): "
            f"{offenders}"
        )

    # -----------------------------------------------------------------------
    # Project to the long schema.  attribute = USDA's own label (see module
    # docstring); attribute_id = USDA's own key.
    # -----------------------------------------------------------------------
    out = combined.rename(columns={
        "country_name":          "country",
        "month_code":            "wasde_release_month",
        "attribute_desc_native": "attribute",
        "unit_desc":             "unit",
    })

    _warn_on_attribute_label_drift(out)

    # -----------------------------------------------------------------------
    # Latest-only vintage dedup.  Registry contract is vintage_retention:
    # latest-only, and the semi-annual sheets (coffee 711100, sugar 612000)
    # RE-PRINT the same (market_year, month_code) row in consecutive monthly bulk
    # snapshots -- they are also exactly the two sheets R4 adjudicates, so this is
    # not a hypothetical interaction.
    #
    # THE TIEBREAK IS THE BRONZE INGEST DATE, NOT release_date, and this is the one
    # place the long producer deliberately does NOT mirror the wide one.  The wide
    # producer dedups twice: step 10 on a key that INCLUDES release_date keeping
    # FIRST, then step 11.5 on the vintage key keeping the latest release_date.
    # That works only while the F2 clamp binds -- i.e. for current-crop rows, whose
    # computed WASDE date is clamped to the differing bronze ingest date.  For every
    # HISTORICAL row the computed date is in the past, the clamp does not bind, and
    # two snapshots of the same vintage produce the IDENTICAL release_date; step 10
    # then collapses them keeping FIRST, which is whichever DataFrame the caller
    # happened to pass first.  Pass the snapshots oldest-first (the natural order)
    # and the OLDEST re-print wins -- the opposite of the stated contract, silently.
    # One dedup ordered by (release_date, bronze_ingest_date) is latest-wins on both
    # axes and is independent of the caller's argument order.
    # -----------------------------------------------------------------------
    # release_date JOINED THIS KEY 2026-09-04 with _GRAIN_COLS, for the same
    # reason: wasde_release_month is a CALENDAR month under the honest clock, so
    # keeping "the latest release per (slug, country, MY, month, attribute_id)"
    # would delete a vintage twelve months older rather than a re-print of one
    # release.  With release_date in the key the sort below is latest-wins on a
    # REAL axis and only byte-identical re-prints of ONE release collapse.
    vintage_key = [
        "leviathan_slug", "country", "market_year", "wasde_release_month",
        "release_date", "attribute_id",
    ]
    n_reprints = int(out.duplicated(subset=vintage_key).sum())
    if n_reprints:
        logger.warning(
            "PSD attributes transform: %d re-printed vintage rows; keeping the latest "
            "(release_date, bronze_ingest_date)",
            n_reprints,
        )
        out = (out.sort_values(vintage_key + ["release_date", "bronze_ingest_date"],
                               kind="stable")
                  .drop_duplicates(subset=vintage_key, keep="last"))

    # The declared grain keys on the LABEL, the dedup above keys on the ID.  They
    # coincide while attribute_id -> attribute is 1:1 (69 ids / 69 labels, MEASURED
    # 2026-08-13).  Enforce the declared grain anyway so the table's contract holds
    # even if a future source re-uses a label across two ids -- loudly, because that
    # would be a real source-side event, not noise.
    #
    # THIS FENCE'S KEY WIDENED WITH _GRAIN_COLS (2026-09-04) AND ITS PURPOSE DID
    # NOT.  It reads _GRAIN_COLS by reference, so adding release_date there added
    # release_date here automatically.  That is correct and it must stay correct:
    # the fence exists to catch attribute_id -> attribute going many-to-one INSIDE
    # ONE RELEASE, and it must never become a second vintage collapse.  Had it kept
    # the pre-E key while _GRAIN_COLS widened, keep='first' here would have
    # silently deleted exactly the older vintages the re-key exists to recover --
    # the same defect one layer down.
    n_label_dupes = int(out.duplicated(subset=_GRAIN_COLS).sum())
    if n_label_dupes:
        logger.warning(
            "PSD attributes transform: %d rows share a grain key under DIFFERENT "
            "attribute_ids -- attribute_id -> attribute is no longer 1:1 in the source; "
            "keeping first and reporting",
            n_label_dupes,
        )
        out = out.drop_duplicates(subset=_GRAIN_COLS, keep="first")

    # -----------------------------------------------------------------------
    # Cast + final column order
    # -----------------------------------------------------------------------
    out["market_year"] = out["market_year"].astype("Int16")
    out["wasde_release_month"] = out["wasde_release_month"].astype("Int8")
    out["attribute_id"] = out["attribute_id"].astype("Int16")
    out["value"] = out["value"].astype("float64")
    out["attribute"] = out["attribute"].astype("object")
    out["unit"] = out["unit"].astype("object")

    out = out[_SILVER_PSD_ATTR_COLS].reset_index(drop=True)

    logger.info(
        "PSD attributes (long) transform complete: rows=%d (from %d post-fan-out bronze rows) "
        "slugs=%d attributes=%d releases=%d",
        len(out), n_in, out["leviathan_slug"].nunique(),
        out["attribute"].nunique(), out["release_date"].nunique(),
    )

    return out


# ---------------------------------------------------------------------------
# R4 internals
# ---------------------------------------------------------------------------


def _multi_slug_codes() -> dict[int, list[str]]:
    """The commodity codes whose fan-out emits more than one slug."""
    return {c: s for c, s in _PSD_COMMODITY_TO_SLUGS.items() if len(s) > 1}


def _assert_r4_registers_cover_every_multi_slug_code() -> None:
    """FAIL CLOSED: every multi-slug code is adjudicated or declared homogeneous.

    The realistic future edit is not a USDA rename -- it is a second slug added to
    a code that used to have one.  That edit converts a safe code into an
    unadjudicated fan-out with no diff anywhere near this file, so the check is
    made at transform time and not only in a test.
    """
    multi = _multi_slug_codes()
    undeclared = sorted(
        c for c in multi
        if c not in _PSD_ATTR_FANOUT and c not in _PSD_HOMOGENEOUS_FANOUT_CODES
    )
    if undeclared:
        raise ValueError(
            "R4: commodity code(s) fan out to multiple leviathan_slug values but are "
            f"declared in NEITHER _PSD_ATTR_FANOUT nor _PSD_HOMOGENEOUS_FANOUT_CODES: "
            f"{ {c: multi[c] for c in undeclared} }. Adjudicate the code's attributes, "
            "or declare the slug list interchangeable -- an undeclared fan-out is how a "
            "variety-specific attribute gets stamped onto a sibling-variety slug."
        )

    both = sorted(set(_PSD_ATTR_FANOUT) & _PSD_HOMOGENEOUS_FANOUT_CODES)
    if both:
        raise ValueError(f"R4: code(s) declared in BOTH registers: {both}")

    # A register entry for a code that no longer fans out (or no longer exists) is
    # a stale claim; report it rather than let it rot silently.
    stale = sorted(
        (set(_PSD_ATTR_FANOUT) | _PSD_HOMOGENEOUS_FANOUT_CODES) - set(multi)
    )
    if stale:
        logger.warning(
            "R4: register entries for code(s) %s which no longer fan out to multiple "
            "slugs -- the adjudication is now a no-op and should be retired",
            stale,
        )


def _apply_r4(combined: pd.DataFrame, *, on_uncovered: str) -> pd.DataFrame:
    """Drop the (slug, attribute) pairs the R4 registry does not permit."""
    if on_uncovered not in ("drop", "raise"):
        raise ValueError(f"on_uncovered must be 'drop' or 'raise', got {on_uncovered!r}")

    code = combined["commodity_code"]
    attr = combined["attribute_id"]
    slug = combined["leviathan_slug"]

    keep = pd.Series(True, index=combined.index)
    blocked_report: list[str] = []
    uncovered_report: list[str] = []
    n_blocked = 0

    for c, per_attr in _PSD_ATTR_FANOUT.items():
        code_rows = code == c
        if not bool(code_rows.any()):
            continue

        covered = attr.isin(list(per_attr))
        unc = code_rows & ~covered
        if bool(unc.any()):
            pairs = sorted(
                set(
                    zip(
                        combined.loc[unc, "attribute_id"].tolist(),
                        combined.loc[unc, "attribute_desc_native"].tolist(),
                    )
                )
            )
            uncovered_report.append(f"code {c}: {pairs} ({int(unc.sum())} post-fan-out rows)")
            keep &= ~unc

        for attr_id, allowed in per_attr.items():
            rows = code_rows & (attr == attr_id)
            if not bool(rows.any()):
                continue
            bad = rows & ~slug.isin(allowed)
            n_bad = int(bad.sum())
            if n_bad:
                label = _PSD_ATTR_ID_TO_DESC_PIN.get(attr_id, "")
                blocked_report.append(
                    f"code {c} attribute {attr_id}{(' ' + label) if label else ''} -> "
                    f"{sorted(set(combined.loc[bad, 'leviathan_slug']))} ({n_bad} rows)"
                )
                n_blocked += n_bad
                keep &= ~bad

    if uncovered_report:
        msg = (
            "R4: (multi-slug code, attribute) pair(s) not covered by the fan-out "
            f"registry: {'; '.join(uncovered_report)}"
        )
        if on_uncovered == "raise":
            raise ValueError(msg)
        logger.warning("%s -- DECLINED (fail-closed default)", msg)

    if blocked_report:
        logger.info(
            "R4: blocked %d manufactured (slug, attribute) rows: %s",
            n_blocked, "; ".join(blocked_report),
        )

    return combined[keep].copy()


def _warn_on_attribute_label_drift(out: pd.DataFrame) -> None:
    """Tripwire: report a source-side rename of an attribute R4 adjudicates.

    R4 keys on ``attribute_id`` precisely so a rename cannot break it silently.
    The flip side of that safety is that a rename would otherwise be INVISIBLE,
    so it is reported here -- and only reported: the fan-out never depends on it.
    """
    if "attribute_id" not in out.columns or "attribute" not in out.columns:
        return
    seen = out[["attribute_id", "attribute"]].drop_duplicates()
    for _, row in seen.iterrows():
        pinned = _PSD_ATTR_ID_TO_DESC_PIN.get(row["attribute_id"])
        if pinned is not None and row["attribute"] != pinned:
            logger.warning(
                "PSD attribute label drift: id %s is pinned as %r but the source now "
                "prints %r -- R4 keys on the id and is unaffected; update the pin",
                row["attribute_id"], pinned, row["attribute"],
            )


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _empty_psd_attributes() -> pd.DataFrame:
    """Return an empty DataFrame matching the long silver schema."""
    schema: dict[str, pd.Series] = {
        "leviathan_slug":      pd.Series([], dtype="object"),
        "country":             pd.Series([], dtype="object"),
        "market_year":         pd.Series([], dtype="Int16"),
        "wasde_release_month": pd.Series([], dtype="Int8"),
        "release_date":        pd.Series([], dtype="object"),
        "attribute":           pd.Series([], dtype="object"),
        "attribute_id":        pd.Series([], dtype="Int16"),
        "value":               pd.Series([], dtype="float64"),
        "unit":                pd.Series([], dtype="object"),
    }
    return pd.DataFrame(schema)
