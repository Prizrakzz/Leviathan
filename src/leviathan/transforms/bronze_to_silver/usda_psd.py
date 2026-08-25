"""Silver transform for USDA PSD (Production, Supply and Distribution) data.

Converts a list of bronze PSD DataFrames (one per release date) into a single
silver DataFrame suitable for Tier 2 S/D balance-sheet feature engineering.

Design notes
------------
* **Wide format** — one row per (leviathan_slug, country, market_year,
  wasde_release_month, release_date).  The eight core attributes (6 S/D + area
  + yield) are pivoted to columns so that su_ratio, revision diffs, and
  area-based ratios can be computed without extra joins.

* **Contract slug fan-out** — each PSD commodity_code maps to a list of
  Leviathan contract slugs (e.g. wheat → 4 slugs covering KCBT, CBOT, MGEX,
  MATIF).  The global PSD S/D row is duplicated once per slug so that
  ``leviathan_slug`` is a universal join key consistent with ESR, FGIS, and
  other silver tables.  Downstream consumers filter to the slug(s) relevant to
  their model.

* **MT units** — all mass columns are converted to metric tonnes (MT).  Unit
  conversion happens before the pivot.  ``area_harvested_1000ha`` keeps the
  USDA native "1000 HA" unit (column name is explicit).  ``yield_mt_ha`` is
  the per-hectare yield in MT/HA; USDA reports some commodities in KG/HA which
  is divided by 1 000 before storage.

* **Consumption attribute normalisation** — sugar uses "Total Disappearance"
  (attr 126), cotton uses "Domestic Use" (attr 142) and the fresh-citrus sheets
  use "Fresh Dom. Consumption" instead of the standard "Domestic Consumption"
  (attr 125).  All three are remapped before the pivot so ``consumption_mt`` is
  uniformly named across all commodities.

* **su_ratio** — ending_stocks_mt / consumption_mt.  Zero consumption → NaN.

* **su_ratio_yoy_delta** — within each (leviathan_slug, country, release_date),
  year-over-year diff of su_ratio across market_year.  Available from the first
  release because the PSD snapshot spans ~65 marketing years.

* **revision columns** — month-on-month change within (leviathan_slug, country,
  market_year), ordered by wasde_release_month ascending:
  revision[M] = estimate[M] - estimate[M-1].  The earliest month in a marketing
  year has no prior estimate, so its revision is NaN.

* **month_code = 0** — pre-WASDE-tracking historical estimates (MY ~1960–2004
  for older series).  Passed through as wasde_release_month = 0.

* **calendar_year / country_code** — dropped.  calendar_year is a batch-import
  artefact; country_code is 100% NULL in the PSD bulk CSV.

* **The projection is DELIBERATE, and its residue is enumerated** — see
  :data:`_PSD_COMMODITY_TO_SLUGS` and :data:`_PSD_UNMAPPED_CODES` below.  Every
  one of the 63 commodity codes the bulk ZIP carries is dispositioned there:
  mapped to a slug, or refused with the reason.  (Superseded note, kept so the
  history reads straight: sorghum used to be listed here as "excluded — no
  Leviathan contract YAML exists".  D-EC XC-1 gave it a home — ``sorghum`` is a
  declared context commodity — so it is mapped now.)

* **Palm marketing year = Oct** — ``_PSD_COMMODITY_TO_MYS[4243000] = 10``.  USDA
  GAIN PSD tables print "Market Year Begins Oct" for both dominant producers
  (Indonesia, Malaysia); the prior value 11 (Nov) drove ``release_date`` one
  month later than USDA's own calendar.  The direction was PIT-conservative
  (data appeared later than truth, so no leakage) but the dates were wrong; a
  silver rebuild shifts every palm ``release_date`` one month earlier.

No S3 or AWS dependencies — pure data transformation.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from leviathan.common.logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Commodity fan-out: PSD 6-digit code → list of Leviathan silver slugs
# ---------------------------------------------------------------------------
# Each global S/D row is emitted once per slug in this list.
#
# D-EC XC-1 (2026-08-20) -- THE PROJECTION WIDENING.  Until this change the map
# carried 13 of the 63 commodity codes the bulk ZIP publishes, so 1,098,150 rows
# (52.5% of the file, MEASURED on the 2026-08-13 raw object) were dropped on the
# floor at silver every single day.  The census that found it
# (data/dec_p0/desk_ontology_diff.md, XC-1) named the cause exactly: the map's
# rule was "a row is worth keeping iff it maps to a TRADEABLE CONTRACT slug",
# and that rule is what makes the demand-side and co-product concepts
# unrepresentable no matter how much data we already hold.  So the rule changes:
# a row is worth keeping iff its subject has a HOME -- a contract slug, a
# declared context commodity, or a forward-declared publication-grain slug.
#
# THE THREE RULES THIS MAP OBEYS.  Each of them is a measured property of the
# transform below, not a style preference; each is pinned by a test.
#
#  R1. EVERY MAPPED CODE MUST ALSO HAVE A _PSD_COMMODITY_TO_MYS ENTRY.  Step 4b
#      does ``.map(_PSD_COMMODITY_TO_MYS).astype(int)``, so a code present here
#      and absent there raises "cannot convert float NaN to integer" for the
#      WHOLE frame, not for its own rows.  The two dicts have identical key sets
#      and a test asserts it.
#
#  R2. NO SLUG MAY APPEAR UNDER TWO CODES.  The pivot index is
#      (leviathan_slug, country, market_year, wasde_release_month, release_date)
#      and step 10 drops duplicates on that key + attribute_desc, keeping FIRST.
#      Two codes sharing one slug therefore produce identical keys for the same
#      country-year and one commodity's balance sheet is SILENTLY DISCARDED.
#      This is the single sharpest edge in the widening and it is what decides
#      several dispositions below (four citrus codes, five dairy codes, three
#      soy "Local" codes) -- collapsing a family onto one key would be a lie the
#      dedup tells quietly.  Fan-out ONE code to MANY slugs stays legal and is
#      how the 13 original codes work; it is the reverse that is banned.
#
#  R3. THE SLUG IS THE PSD PUBLICATION GRAIN.  A D15 context-commodity id is
#      used as the slug only where the node and the PSD code are 1:1 (the family
#      HEAD -- the oilseed for a crush complex).  Where one node spans several
#      codes, each code keeps its own publication-grain slug, because USDA
#      publishes those balance sheets separately and R2 forbids merging them.
#      Those extra ids are FORWARD DECLARATIONS: they are numbers keys today and
#      graph nodes only if and when the post-X2 edge half declares them.  They
#      are listed in _PSD_FORWARD_DECLARED_SLUGS below so the set is auditable
#      rather than scattered through the map.
#
# The context-commodity ids used verbatim (barley, sorghum, sunflower,
# sunflower_oil, fish_meal + the D15 wave-1c thirteen) are spelled exactly as
# configs/graphrag/commodity_hierarchy.yaml declares them.  They are NOT renamed
# here and this file never invents a variant spelling of one.

# Marketing-year start month per PSD commodity code (1=Jan … 12=Dec).
# Used to convert (market_year, month_code) → the actual WASDE calendar date,
# replacing the ingest timestamp that bronze stores as release_date.
#
# WHERE THESE NUMBERS COME FROM, and what was MEASURED rather than assumed
# (D-EC XC-1, probe of the 2026-08-13 raw ZIP):
#   * The bulk CSV's ``Calendar_Year`` column CANNOT be used to derive a start
#     month.  It equals ``Market_Year`` for essentially every row; the handful
#     of offsets are noise.  (The module docstring already calls it a
#     batch-import artefact; this is the measurement behind that sentence.)
#   * The bulk CSV's ``Month`` column IS the CALENDAR month of the release, not
#     an MY-relative index.  Measured against USDA's own publication calendars
#     on the newest market year in the file: dairy 2026 carries {7} (Dairy WM&T
#     is July + December), livestock/meat 2026 carries {4} (April + October),
#     sugar 2026 carries {5} (May + November), citrus carries {1,7} (January +
#     July), and the monthly WASDE families carry {8} -- August 2026, the latest
#     release at probe time.  Under an MY-relative reading none of those five
#     independent matches could happen.
#   * CONSEQUENCE, recorded and DELIBERATELY NOT ACTED ON HERE: the formula in
#     _compute_psd_release_dates treats month_code as MY-relative and rotates it
#     by MYS, so the release_date it computes is NOT the true publication month
#     for any code with MYS != 1.  That is pre-existing, shipped behaviour for
#     all 13 original codes and re-dating it would move every row of
#     silver_psd -- a re-baseline, not an enum widening.  What this change does
#     instead is keep the new codes on the SAME convention (MYS = the USDA
#     marketing-year start month) so one table never carries two date
#     conventions.  The finding is reported for a follow-up task; it is not
#     smuggled in under a widening.
# Each new value below is labelled INHERITED (taken exactly from an already
# pinned sibling in the same USDA sheet family), PUBLISHED (the USDA marketing
# year for that commodity) or LATE (genuinely uncertain, resolved to the later
# candidate because a later MYS moves release_date LATER, which is the
# PIT-conservative direction -- the same direction the palm correction note
# above records).
_PSD_COMMODITY_TO_MYS: dict[int, int] = {
    # ---- the original 13 (UNCHANGED) --------------------------------------
    410000:  6,   # wheat (all classes): Jun 1
    440000:  9,   # corn / maize: Sep 1
    422110:  8,   # milled rice: Aug 1
    2222000: 9,   # soybeans: Sep 1
    813100:  10,  # soybean meal: Oct 1
    4232000: 10,  # soybean oil: Oct 1
    2226000: 8,   # canola / rapeseed: Aug 1
    4239100: 10,  # rapeseed oil: Oct 1
    813600:  10,  # rapeseed meal: Oct 1
    4243000: 10,  # palm oil: Oct 1 (USDA GAIN prints "Market Year Begins Oct" for BOTH
                  #                  Indonesia and Malaysia; was 11=Nov, which stamped every
                  #                  palm release_date one month LATE -- PIT-conservative but
                  #                  wrong; corrected 2026-07-18 per the reroute-v2 World probe)
    612000:  10,  # raw sugar / white sugar: Oct 1
    711100:  10,  # coffee (arabica + robusta): Oct 1
    2631000: 8,   # cotton: Aug 1
    # ---- D-EC XC-1: the coarse + small grains -----------------------------
    430000:  6,   # barley: Jun 1        PUBLISHED (US small-grains June cycle, = wheat)
    451000:  6,   # rye: Jun 1           PUBLISHED (same small-grains cycle)
    452000:  6,   # oats: Jun 1          PUBLISHED (same small-grains cycle)
    459900:  6,   # mixed grain: Jun 1   INHERITED (it aggregates the June small grains)
    459200:  9,   # sorghum: Sep 1       PUBLISHED (US sorghum runs the corn cycle)
    459100:  9,   # millet: Sep 1        LATE (a summer coarse grain in the same USDA sheet
                  #                      family as sorghum; the US proso June cycle is the
                  #                      earlier candidate and is deliberately not taken)
    # ---- D-EC XC-1: the oilseeds ------------------------------------------
    2221000: 8,   # peanut / groundnut: Aug 1   PUBLISHED
    2223000: 8,   # cottonseed: Aug 1           INHERITED from cotton 2631000 -- the gin
                  #                             produces lint and seed in one pass, so a
                  #                             second calendar for the same harvest would be
                  #                             a fabricated distinction
    2224000: 9,   # sunflowerseed: Sep 1        PUBLISHED
    2232000: 10,  # palm kernel: Oct 1          INHERITED from palm oil 4243000 (same fruit)
    2231000: 10,  # copra: Oct 1                LATE (a tropical perennial with no crop year;
                  #                             resolved onto the Oct lauric/vegoil cycle the
                  #                             palm entry already pins)
    # ---- D-EC XC-1: the crush products ------------------------------------
    # Every meal and oil sheet runs the Oct oil-year, exactly as the two shipped
    # crush products (813100 soybean meal, 4239100 rapeseed oil) already pin.
    813200:  10,  # peanut meal            INHERITED
    813300:  10,  # cottonseed meal        INHERITED
    813500:  10,  # sunflowerseed meal     INHERITED
    813700:  10,  # copra meal             INHERITED
    813800:  10,  # palm kernel meal       INHERITED
    814200:  10,  # fish meal              INHERITED
    4233000: 10,  # cottonseed oil         INHERITED
    4234000: 10,  # peanut oil             INHERITED
    4235000: 10,  # olive oil              PUBLISHED (the Mediterranean olive year begins Oct 1)
    4236000: 10,  # sunflowerseed oil      INHERITED
    4242000: 10,  # coconut oil            INHERITED
    4244000: 10,  # palm kernel oil        INHERITED
    # ---- D-EC XC-7: citrus + orange juice ---------------------------------
    571120:  10,  # oranges, fresh: Oct 1  PUBLISHED (USDA citrus MY, Northern Hemisphere)
    585100:  10,  # orange juice: Oct 1    PUBLISHED (rides the citrus year; Brazil's Jul year
                  #                        is the minority leg and the LATER candidate is taken)
    # ---- D-EC XC-1: the livestock + dairy demand layer --------------------
    # PSD publishes these on a CALENDAR year, so MYS = 1 is both the published
    # marketing year AND the value that makes the computed month equal the
    # release month exactly -- the only family in this file where the shipped
    # formula and the measured semantics agree.
    111000:  1,   # meat, beef and veal    PUBLISHED (calendar year)
    113000:  1,   # meat, swine            PUBLISHED
    114200:  1,   # poultry meat, broiler  PUBLISHED
    115000:  1,   # meat, chicken          PUBLISHED
    223000:  1,   # dairy, milk, fluid     PUBLISHED
    224200:  1,   # dairy, nonfat dry milk PUBLISHED
    224400:  1,   # dairy, whole milk powder PUBLISHED
    230000:  1,   # dairy, butter          PUBLISHED
    240000:  1,   # dairy, cheese          PUBLISHED
}

# Slugs this map mints that are NOT yet nodes anywhere in the ontology.  They
# are numbers keys, nothing more: silver rows land under them so the data stops
# being discarded, and whether any of them becomes a graph node is the post-X2
# EDGE decision that configs/graphrag/commodity_hierarchy.yaml's D15 block
# explicitly defers ("the seed/oil/meal split is an EDGE decision and the edge
# half is post-X2").  Declaring them here rather than discovering them later is
# the point: a reader can diff this set against the hierarchy and see exactly
# which silver keys have no home yet.
#
# The four livestock/dairy FAMILY names the D-EC plan uses are
# broilers_poultry / cattle_beef / hogs / dairy.  Three of them are slugs below
# verbatim; `dairy` is NOT, because PSD publishes five separate dairy balance
# sheets and R2 forbids collapsing them onto one key -- so `dairy` survives as
# the family GLOSS over the five product slugs, and the product grain is what
# the table stores.
_PSD_FORWARD_DECLARED_SLUGS: frozenset[str] = frozenset({
    # crush co-products, one per USDA sheet (R3)
    "cottonseed_meal", "cottonseed_oil",
    "peanut_meal", "peanut_oil",
    "sunflower_meal",
    "copra_meal", "coconut_oil",
    "palm_kernel_meal", "palm_kernel_oil",
    # the minor cereals, one per USDA sheet (the D15 `minor_cereals` node is a
    # retrieval term-bag over the family; the numbers stay per grain)
    "rye", "oats", "millet", "mixed_grain",
    # the livestock + dairy demand layer
    "cattle_beef", "hogs", "broilers_poultry", "chicken_meat",
    "milk_fluid", "milk_powder_nonfat", "milk_powder_whole", "butter", "cheese",
})

_PSD_COMMODITY_TO_SLUGS: dict[int, list[str]] = {
    # =======================================================================
    # THE ORIGINAL 13 -- unchanged, byte for byte.  These are the fan-out
    # codes: one global S/D sheet serving several tradeable contracts.
    # =======================================================================
    410000: [                              # all-class wheat aggregate
        "hard_red_winter_wheat_kcbt",
        "soft_red_winter_wheat_cbot",
        "hard_red_spring_wheat_mgex",
        "french_wheat_matif",
    ],
    440000: [                              # corn / maize aggregate
        "corn_cbot",
        "campinas_corn_reference_bmf",
        "french_maize_matif",
        "south_african_white_maize_jse",   # SA maize shares global corn S/D
        "south_african_yellow_maize_jse",
    ],
    422110: ["rough_rice_cbot"],           # milled rice
    2222000: [                             # soybeans aggregate
        "soybeans_cbot",
        "soybeans_no_1_dce",
        "soybeans_no_2_dce",
    ],
    813100:  ["soybean_meal_cbot", "soybean_meal_dce"],
    4232000: ["soybean_oil_cbot", "soybean_oil_dce"],
    2226000: ["canola_ice", "french_rapeseed_matif"],
    4239100: ["rapeseed_oil_zce"],
    813600:  ["rapeseed_meal_zce"],
    4243000: ["palm_olein_dce", "malaysian_crude_palm_oil_cme"],
    612000:  ["raw_sugar", "white_sugar"],
    711100:  [                             # coffee aggregate (all origins)
        "arabica_coffee",
        "brazilian_arabica_coffee",        # same global coffee S/D as arabica/robusta
        "robusta_coffee",
    ],
    2631000: ["cotton"],

    # =======================================================================
    # D-EC XC-7 -- THE FCOJ BINDING.  frozen_orange_juice is a LIVE ICE
    # contract that had zero PSD supply/demand backing while its own data sat
    # in the raw layer being discarded daily.  Two codes, two different
    # subjects, and they are deliberately NOT both hung on the contract:
    #   * 585100 Orange Juice     -> the CONTRACT slug.  This is the FCOJ
    #                                balance sheet; it is what the contract
    #                                trades and it belongs to the contract.
    #   * 571120 Oranges, Fresh   -> the CONTEXT node `fresh_citrus`.  That is
    #                                the whole point of D15: the fruit is a
    #                                different subject from the juice, and the
    #                                census measured 3,348 of fresh_citrus's
    #                                dark propositions arriving from the juice
    #                                node's OWN source -- exactly the confusion
    #                                a separate key stops.
    # `fresh_citrus` carries the ORANGE leg only.  Tangerines, lemons/limes and
    # grapefruit are refused below under R2, not forgotten.
    # =======================================================================
    585100:  ["frozen_orange_juice"],
    571120:  ["fresh_citrus"],

    # =======================================================================
    # D-EC XC-1 -- COARSE AND SMALL GRAINS (237,195 raw rows, the largest
    # single discard group).  barley and sorghum are DECLARED context
    # commodities and take their ids verbatim; the other four are the
    # publication grains under the D15 `minor_cereals` node (R3).
    # =======================================================================
    430000:  ["barley"],
    459200:  ["sorghum"],
    451000:  ["rye"],
    452000:  ["oats"],
    459100:  ["millet"],
    459900:  ["mixed_grain"],

    # =======================================================================
    # D-EC XC-1 -- THE CRUSH COMPLEXES.  Each family's OILSEED code takes the
    # context-commodity id (the node and the sheet are 1:1); the meal and oil
    # sheets take their own publication-grain slugs (R2 forbids sharing).
    # sunflower/sunflower_oil/fish_meal were already declared context
    # commodities before D15 and are used verbatim here too.
    # =======================================================================
    2223000: ["cottonseed"],           # D15 tier 1
    813300:  ["cottonseed_meal"],
    4233000: ["cottonseed_oil"],
    2221000: ["peanut"],               # D15 tier 1
    813200:  ["peanut_meal"],
    4234000: ["peanut_oil"],
    2231000: ["coconut"],              # D15 tier 1 -- copra IS the coconut complex head
    813700:  ["copra_meal"],
    4242000: ["coconut_oil"],
    2232000: ["palm_kernel"],          # D15 tier 1 -- the lauric co-product node
    813800:  ["palm_kernel_meal"],
    4244000: ["palm_kernel_oil"],
    2224000: ["sunflower"],            # pre-D15 context commodity
    813500:  ["sunflower_meal"],
    4236000: ["sunflower_oil"],        # pre-D15 context commodity
    814200:  ["fish_meal"],            # pre-D15 context commodity
    4235000: ["olive_oil"],            # D15 tier 2 -- one node, one sheet, exact 1:1

    # =======================================================================
    # D-EC XC-1 -- THE LIVESTOCK AND DAIRY DEMAND LAYER (148,237 + 80,874 raw
    # rows).  This is the layer the owner found by reading a market commentary
    # and that every prior census missed, because every prior census keyed on
    # the configs and the configs only ever admitted contracts.
    #
    # The two ANIMAL-NUMBERS codes are refused below: they are head counts, and
    # this table's columns are all metric tonnes.
    # =======================================================================
    111000:  ["cattle_beef"],
    113000:  ["hogs"],
    114200:  ["broilers_poultry"],
    115000:  ["chicken_meat"],         # BROADER than broiler and it OVERLAPS it --
                                       # never sum 114200 and 115000, see the note on
                                       # _PSD_FORWARD_DECLARED_SLUGS
    223000:  ["milk_fluid"],
    224200:  ["milk_powder_nonfat"],
    224400:  ["milk_powder_whole"],
    230000:  ["butter"],
    240000:  ["cheese"],
}

# ---------------------------------------------------------------------------
# The residue, enumerated.  D-EC XC-1 asked for a deliberate widening, not a
# blind one, so the codes that stay out are listed WITH the reason rather than
# left as an absence a reader has to reconstruct.  Row counts are MEASURED on
# the 2026-08-13 raw object (2,092,687 rows, 63 codes).  After this widening the
# discard falls from 1,098,150 rows (52.5%) to 193,384 (9.2%).
#
# This dict is documentation with a test behind it: a test asserts that its keys
# plus _PSD_COMMODITY_TO_SLUGS's keys are exactly the 63 codes the file carries,
# so a new USDA commodity code cannot appear and be silently ignored -- it will
# fail the census pin instead.
# ---------------------------------------------------------------------------
_PSD_UNMAPPED_CODES: dict[int, str] = {
    # -- UNIT: a head count has no home in an all-tonnes schema ---------------
    11000: (
        "Animal Numbers, Cattle (34,515 rows). Every target-attribute row is "
        "(1000 HEAD). Mapping it would push a head count through the same "
        "unit-factor path as a mass and land it in production_mt -- a units lie "
        "that no downstream consumer could detect. Reopen by giving the schema a "
        "head-count column pair, not by adding a factor."
    ),
    13000: (
        "Animal Numbers, Swine (23,991 rows). Same reason as 11000: (1000 HEAD)."
    ),
    # -- R2: the slug is already taken by the family head ---------------------
    571220: (
        "Tangerines/Mandarins, Fresh (9,128 rows). fresh_citrus is 1:1 with the "
        "ORANGE sheet (XC-7); a second code on the same slug collides on the "
        "pivot key and one of the two balance sheets is silently dropped. D15 "
        "authored fresh_citrus as ONE node on purpose, so minting three more "
        "ids would overturn that decision from the wrong end of the system."
    ),
    572120: "Lemons/Limes, Fresh (7,994 rows). Same reason as 571220.",
    572220: "Grapefruit, Fresh (6,972 rows). Same reason as 571220.",
    # -- R2 + a missing axis: the soy 'Local' marketing-year duplicates -------
    813101: (
        "Meal, Soybean (Local) (1,764 rows). PSD re-prints the soybean-meal "
        "balance sheet on a LOCAL marketing year for the countries whose local "
        "year differs from the international one. The silver schema has no "
        "marketing-year-CONVENTION axis, so these rows collide with the "
        "international-year rows on (slug, country, market_year, month) and the "
        "vintage dedup would drop one of the two conventions at random. Reopen "
        "by adding an my_convention column -- a schema change, not a map entry."
    ),
    2222001: "Oilseed, Soybean (Local) (1,638 rows). Same reason as 813101.",
    4232001: "Oil, Soybean (Local) (1,638 rows). Same reason as 813101.",
    # -- NO HOME: no contract, no context commodity, no planned demand node ---
    # 105,744 rows across eight codes. These are the ONLY group refused purely
    # on ontology grounds, and the refusal is the point of the D-EC wave: minting
    # silver keys with no node and no card is exactly the orphan-slice class the
    # dark census was opened to close.
    574000: "Apples, Fresh (31,545 rows). No node anywhere in the ontology; not a contract, not a context commodity, not in the demand layer the plan names.",
    575100: "Grapes, Fresh Table (11,862 rows). Same reason as 574000.",
    577400: "Almonds, Shelled Basis (11,352 rows). Same reason as 574000.",
    577901: "Walnuts, Inshell Basis (8,600 rows). Same reason as 574000.",
    577907: "Pistachios, Inshell Basis (6,520 rows). Same reason as 574000.",
    579220: "Pears, Fresh (15,570 rows). Same reason as 574000.",
    579305: "Cherries (Sweet&Sour), Fresh (9,243 rows). Same reason as 574000.",
    579309: "Peaches & Nectarines, Fresh (11,052 rows). Same reason as 574000.",
}

# The one contract slug that STILL has no PSD binding after this widening, and
# why: USDA PSD publishes no cocoa sheet at all -- cocoa is not among the 63
# codes.  Stated here so "cocoa is unbound" reads as a measured fact about the
# source rather than an oversight in this map.  (Before this change
# frozen_orange_juice was the second member of this set; XC-7 closed it.)
_PSD_UNBINDABLE_CONTRACT_SLUGS: frozenset[str] = frozenset({"cocoa"})

# ---------------------------------------------------------------------------
# Unit conversion: native PSD unit_desc → factor applied to raw value
# ---------------------------------------------------------------------------
# Result is MT for mass columns, 1000 HA for area, MT/HA for yield.

_UNIT_FACTOR: dict[str, float] = {
    "(1000 MT)":          1_000.0,    # grains, oilseeds, oils, sugar, meat, dairy
    "(MT)":               1.0,        # orange juice + the fruit/nut sheets
    "1000 480 lb. Bales": 217.724,    # cotton: 1 bale = 480 lb; 1000 bales → MT
    "(1000 60 KG BAGS)":  60.0,       # coffee: 1000 bags × 60 kg → MT
    "(1000 HA)":          1.0,        # area harvested (keep 1000 HA, col name says so)
    "(MT/HA)":            1.0,        # yield already in MT/HA
    "(KG/HA)":            0.001,      # yield in KG/HA → divide by 1000 → MT/HA
    # D-EC XC-1: the ONLY new unit the widening admits.  CWE = carcass-weight
    # equivalent, USDA's standard basis for red meat; it is a BASIS note on a
    # real mass, not a different dimension, so the factor is the plain
    # thousand-tonne one.  It is spelled as its own key rather than folded into
    # "(1000 MT)" because the basis is load-bearing for a reader: beef and pork
    # tonnages here are carcass weight and are NOT comparable to the retail or
    # boneless weights a trade table may quote.  Only 111000 (beef and veal) and
    # 113000 (swine) use it; broiler and chicken publish plain (1000 MT).
    "(1000 MT CWE)":      1_000.0,
    # DELIBERATELY ABSENT: "(1000 HEAD)".  It is the unit of the two
    # animal-numbers codes, which _PSD_UNMAPPED_CODES refuses precisely because
    # a head count is not a mass.  Adding a factor here would be the mechanism
    # by which that refusal quietly stops holding, so the absence is the fence.
    # "(PERCENT)" and "(RATIO)" are also absent and always have been: they only
    # ever ride NON-target attributes (extraction rates, stocks-to-use) and the
    # step-6 attribute filter removes them before step 7 ever sees them.
}

# ---------------------------------------------------------------------------
# Attribute normalisation
# ---------------------------------------------------------------------------

# The eight attributes we pivot to columns.
_TARGET_ATTRS: frozenset[str] = frozenset({
    "Beginning Stocks",
    "Production",
    "Imports",
    "Exports",
    "Ending Stocks",
    "Domestic Consumption",
    "Area Harvested",
    "Yield",
})

# Silver column names for each attribute_desc after pivot.
_ATTR_TO_COL: dict[str, str] = {
    "Beginning Stocks":   "beginning_stocks_mt",
    "Production":         "production_mt",
    "Imports":            "imports_mt",
    "Exports":            "exports_mt",
    "Ending Stocks":      "ending_stocks_mt",
    "Domestic Consumption": "consumption_mt",
    "Area Harvested":     "area_harvested_1000ha",
    "Yield":              "yield_mt_ha",
}

# Consumption attribute_desc in bronze for slugs that deviate from the default.
_SUGAR_CONSUMPTION_ATTR  = "Total Disappearance"   # attr_id 126
_COTTON_CONSUMPTION_ATTR = "Domestic Use"           # attr_id 142
# D-EC XC-7: the fresh-fruit sheets label consumption "Fresh Dom. Consumption".
# Without this third remap `fresh_citrus` would land with consumption_mt NULL on
# every row while the source publishes the number -- the same silent hole the
# sugar and cotton remaps above exist to close.  The remap is keyed on the SLUG
# (as the two existing ones are), so it can never reach a sheet that publishes a
# plain "Domestic Consumption".
_FRESH_CONSUMPTION_ATTR  = "Fresh Dom. Consumption"

_SUGAR_SLUGS:  frozenset[str] = frozenset({"raw_sugar", "white_sugar"})
_COTTON_SLUGS: frozenset[str] = frozenset({"cotton"})
_FRESH_SLUGS:  frozenset[str] = frozenset({"fresh_citrus"})

# ---------------------------------------------------------------------------
# Required columns in bronze DataFrames
# ---------------------------------------------------------------------------

_REQUIRED_COLS: frozenset[str] = frozenset({
    "commodity_code",
    "commodity_desc",
    "country_name",
    "market_year",
    "month_code",
    "attribute_desc",
    "unit_desc",
    "value",
    "release_date",
})

# ---------------------------------------------------------------------------
# Final column order for silver output (18 columns)
# ---------------------------------------------------------------------------

_SILVER_COLS: list[str] = [
    "leviathan_slug",
    "country",
    "market_year",
    "wasde_release_month",
    "release_date",
    "beginning_stocks_mt",
    "production_mt",
    "imports_mt",
    "exports_mt",
    "ending_stocks_mt",
    "consumption_mt",
    "area_harvested_1000ha",
    "yield_mt_ha",
    "su_ratio",
    "su_ratio_yoy_delta",
    "production_mt_revision",
    "ending_stocks_mt_revision",
    "consumption_mt_revision",
]

# ---------------------------------------------------------------------------
# Public transform
# ---------------------------------------------------------------------------


def _compute_psd_release_dates(df: pd.DataFrame) -> pd.Series:
    """Replace bronze's ingest-timestamp release_date with the WASDE calendar date.

    month_code (WASDE release number, 1–12 within the marketing year):
      release_calendar_month = (MYS + month_code - 2) % 12 + 1
      release_year           = market_year + (MYS + month_code - 2) // 12

    month_code == 0 (pre-WASDE-tracking estimates, ~1960–2004): mapped to
    Jan 1 of market_year — always visible to any historical crop-year cutoff.
    """
    mys = df["commodity_code"].map(_PSD_COMMODITY_TO_MYS).astype(int)
    mc  = pd.to_numeric(df["month_code"], errors="coerce").fillna(0).astype(int)
    my  = pd.to_numeric(df["market_year"], errors="coerce").fillna(0).astype(int)

    total     = mys + mc - 2
    cal_month = (total % 12 + 1).astype(int)
    cal_year  = (my + total // 12).astype(int)

    dates = cal_year.astype(str) + "-" + cal_month.astype(str).str.zfill(2) + "-10"

    # Pre-tracking rows have no WASDE month; anchor them to Jan 1 so they are
    # always visible to visible_slice("prior_marketing_year").
    dates[mc == 0] = my[mc == 0].astype(str) + "-01-01"

    return dates


def prepare_psd_combined_frame(
    dfs: list[pd.DataFrame],
    *,
    extra_required: frozenset[str] = frozenset(),
) -> pd.DataFrame:
    """Run steps 1-5 of the PSD pipeline and return the frame at the BRANCH POINT.

    D-EC L2-2 (2026-08-25) -- THE SHARED PREFIX.  ``silver_psd`` (wide, 8 pivoted
    attributes, MT-converted) and ``silver_psd_attributes`` (long, every attribute,
    native units) are the SAME table up to this point: same commodity filter, same
    slug fan-out, same WASDE-calendar release_date, same consumption remaps.  The
    two producers therefore share one prefix rather than each keeping a copy of it
    -- a duplicated prefix is a pair of tables that drift apart silently, which is
    the exact failure class R2 exists to stop one level down.

    The returned frame is post-explode (one row per leviathan_slug) and post-remap,
    and it carries TWO attribute-label columns:

      * ``attribute_desc``        -- the NORMALISED label the wide pivot keys on
                                    ("Total Disappearance"/"Domestic Use"/"Fresh
                                    Dom. Consumption" already folded into
                                    "Domestic Consumption").
      * ``attribute_desc_native`` -- USDA's own label, snapshotted BEFORE the
                                    remaps.  The long companion emits this one so
                                    that (attribute, attribute_id) stays 1:1 across
                                    the whole table; the wide pivot ignores it.

    MEASURED (2026-08-13 bulk object): the three remaps are 1:1 RENAMES, not
    merges -- codes 612000 / 2631000 / 571120 publish NO attribute_id 125 of their
    own, so folding 126 / 142 / 135 onto "Domestic Consumption" can never collide
    with a genuine 125 row.  Either label choice is therefore grain-safe; the long
    table takes the native one for fidelity, not to dodge a collision.

    Args:
        dfs: List of bronze DataFrames.  Must be non-empty.
        extra_required: Column names required IN ADDITION to :data:`_REQUIRED_COLS`
            (the long producer adds ``attribute_id``).

    Returns:
        The combined frame at the branch point, or an EMPTY frame when no row
        survives the commodity filter.  Callers own their own empty schema.

    Raises:
        ValueError: If *dfs* is empty or required columns are missing.
    """
    if not dfs:
        raise ValueError("dfs must contain at least one DataFrame")

    # -----------------------------------------------------------------------
    # 1. Validate required columns
    # -----------------------------------------------------------------------
    required = _REQUIRED_COLS | frozenset(extra_required)
    for i, df in enumerate(dfs):
        missing = required - set(df.columns)
        if missing:
            raise ValueError(
                f"PSD bronze DataFrame[{i}] missing required columns: {missing}. "
                f"Got: {list(df.columns)}"
            )

    # -----------------------------------------------------------------------
    # 2. Concatenate all release snapshots
    # -----------------------------------------------------------------------
    combined = pd.concat(dfs, ignore_index=True)

    # -----------------------------------------------------------------------
    # 3. Filter to in-scope commodity codes
    # -----------------------------------------------------------------------
    in_scope_mask = combined["commodity_code"].isin(_PSD_COMMODITY_TO_SLUGS)
    n_dropped = int((~in_scope_mask).sum())
    if n_dropped:
        logger.info("PSD transform: dropping %d out-of-scope rows", n_dropped)
    combined = combined[in_scope_mask].copy()

    if combined.empty:
        logger.warning("PSD transform: no in-scope rows remain after commodity filter")
        return combined

    # -----------------------------------------------------------------------
    # 4. Fan-out: explode each commodity row to one row per contract slug
    # -----------------------------------------------------------------------
    combined["leviathan_slug"] = combined["commodity_code"].map(_PSD_COMMODITY_TO_SLUGS)
    combined = combined.explode("leviathan_slug").reset_index(drop=True)

    # -----------------------------------------------------------------------
    # 4b. Replace ingest-timestamp release_date with true WASDE calendar date
    # -----------------------------------------------------------------------
    # Bronze stamps every row with the download date (e.g. '2026-05-20').
    # visible_slice("prior_marketing_year") filters release_date <= crop_year_start,
    # so all historical rows would fail that filter without this correction.
    #
    # F2 clamp: the WASDE-calendar formula treats month_code as an MY-relative
    # sequential index, which projects current-crop rows to FUTURE calendar dates
    # (up to ~2027 for the 2026-05-20 snapshot).  A release_date can never
    # post-date the snapshot that observed it, so clamp each computed date to an
    # upper bound of that row's bronze ingest date: min(computed, ingest).  Only
    # rows the formula pushed past ingest are affected; historical backdating is
    # untouched.  Both series are ISO-8601 'YYYY-MM-DD' strings, which sort
    # lexicographically == chronologically, so the element-wise min is exact and
    # preserves release_date's existing object/string dtype.
    ingest_date = pd.to_datetime(combined["release_date"]).dt.strftime("%Y-%m-%d")
    computed_date = _compute_psd_release_dates(combined)
    combined["release_date"] = computed_date.where(
        computed_date <= ingest_date, ingest_date
    )
    # Keep the bronze ingest date the line above overwrites.  It is the ONLY
    # surviving witness to WHICH SNAPSHOT a row came from, and the computed WASDE
    # date is not a substitute: for any row the F2 clamp does not bind (i.e. every
    # historical row) two different bronze snapshots produce the SAME computed
    # release_date, so "which of these two re-prints is newer" is unanswerable
    # without it.  The long companion uses it as the vintage tiebreak; nothing in
    # the wide path reads it.
    combined["bronze_ingest_date"] = ingest_date

    # -----------------------------------------------------------------------
    # 5. Remap non-standard consumption attribute labels -> "Domestic Consumption"
    # -----------------------------------------------------------------------
    # Snapshot USDA's own label FIRST.  The long companion keys on it; nothing in
    # the wide path reads it (pivot_table takes index/columns/values explicitly).
    combined["attribute_desc_native"] = combined["attribute_desc"]

    sugar_mask = (
        combined["leviathan_slug"].isin(_SUGAR_SLUGS)
        & (combined["attribute_desc"] == _SUGAR_CONSUMPTION_ATTR)
    )
    combined.loc[sugar_mask, "attribute_desc"] = "Domestic Consumption"

    cotton_mask = (
        combined["leviathan_slug"].isin(_COTTON_SLUGS)
        & (combined["attribute_desc"] == _COTTON_CONSUMPTION_ATTR)
    )
    combined.loc[cotton_mask, "attribute_desc"] = "Domestic Consumption"

    fresh_mask = (
        combined["leviathan_slug"].isin(_FRESH_SLUGS)
        & (combined["attribute_desc"] == _FRESH_CONSUMPTION_ATTR)
    )
    combined.loc[fresh_mask, "attribute_desc"] = "Domestic Consumption"

    return combined


def transform_psd_bronze_to_silver(
    dfs: list[pd.DataFrame],
) -> pd.DataFrame:
    """Convert one or more bronze PSD DataFrames into a single silver DataFrame.

    Each element of *dfs* is one ``release_date`` partition read from S3
    (``bronze/production/source=usda_psd/release_date=.../part-000.parquet``).
    Passing multiple DataFrames enables revision-diff computation across
    sequential WASDE releases.

    Args:
        dfs: List of bronze DataFrames.  Must be non-empty.

    Returns:
        Wide-format silver DataFrame with :data:`_SILVER_COLS` columns.

    Raises:
        ValueError: If *dfs* is empty, required columns are missing, or an
                    unrecognised ``unit_desc`` appears for an in-scope row.
    """
    # Steps 1-5 are shared with the long companion producer; see
    # prepare_psd_combined_frame for why they live in one place.
    combined = prepare_psd_combined_frame(dfs)
    if combined.empty:
        return _empty_silver()

    # -----------------------------------------------------------------------
    # 6. Filter to the eight target attributes
    # -----------------------------------------------------------------------
    combined = combined[combined["attribute_desc"].isin(_TARGET_ATTRS)].copy()

    if combined.empty:
        logger.warning("PSD transform: no rows remain after attribute filter")
        return _empty_silver()

    # -----------------------------------------------------------------------
    # 7. Validate unit_desc (only in-scope rows, so limited to known units)
    # -----------------------------------------------------------------------
    unknown_units = set(combined["unit_desc"].unique()) - set(_UNIT_FACTOR)
    if unknown_units:
        raise ValueError(
            f"PSD bronze contains unrecognised unit_desc for in-scope rows: "
            f"{unknown_units}. Update _UNIT_FACTOR to avoid wrong conversions."
        )

    # -----------------------------------------------------------------------
    # 8. Convert values using unit_desc factor
    # -----------------------------------------------------------------------
    factor_series = combined["unit_desc"].map(_UNIT_FACTOR)
    combined["value_mt"] = combined["value"] * factor_series

    # -----------------------------------------------------------------------
    # 9. Rename index columns
    # -----------------------------------------------------------------------
    combined = combined.rename(columns={
        "country_name": "country",
        "month_code":   "wasde_release_month",
    })

    # -----------------------------------------------------------------------
    # 10. Dedup before pivot (keep first occurrence per key)
    # -----------------------------------------------------------------------
    pivot_index = [
        "leviathan_slug",
        "country",
        "market_year",
        "wasde_release_month",
        "release_date",
    ]
    dedup_key = pivot_index + ["attribute_desc"]
    n_dupes = int(combined.duplicated(subset=dedup_key).sum())
    if n_dupes:
        # VINTAGE DIRECTION FIX (owner word 2026-08-25; found by the Lane-3 grain test): for every
        # historical row the F2 clamp does not bind, so two bronze snapshots of the same vintage carry
        # the IDENTICAL release_date -- a blind keep-first here resolved the tie to whichever snapshot
        # the caller listed FIRST (oldest, in the natural order), contradicting the card's
        # vintage_retention: latest-only and silently starving step 11.5 of the re-print it exists to
        # resolve. bronze_ingest_date is the only surviving witness to WHICH snapshot a row came from;
        # ordering on it makes the dedup latest-wins on both axes and caller-order-independent (the
        # long companion shipped this rule first; the wide table now matches).
        logger.warning(
            "PSD transform: %d duplicate (index + attribute_desc) rows; keeping newest snapshot",
            n_dupes,
        )
        combined = (combined.sort_values(dedup_key + ["bronze_ingest_date"])
                            .drop_duplicates(subset=dedup_key, keep="last"))

    # -----------------------------------------------------------------------
    # 11. Pivot attribute_desc → wide columns
    # -----------------------------------------------------------------------
    wide = combined.pivot_table(
        index=pivot_index,
        columns="attribute_desc",
        values="value_mt",
        aggfunc="first",
    ).reset_index()
    wide.columns.name = None

    # Rename attribute columns to silver names
    wide = wide.rename(columns=_ATTR_TO_COL)

    # Guarantee all eight pivot columns exist even if absent in this snapshot
    for col in _ATTR_TO_COL.values():
        if col not in wide.columns:
            wide[col] = np.nan

    # -----------------------------------------------------------------------
    # 11.5 Latest-only vintage dedup ACROSS source releases
    # Semi-annual sheets (coffee 711100, sugar 612000) re-print the SAME
    # (market_year, month_code) row in consecutive monthly bulk snapshots, so
    # once bronze holds two overlapping releases the pivot emits TWO rows for
    # one logical vintage slot (first observed 2026-07-18: the 2026-07-17
    # snapshot re-printed the 2026-05-20 coffee/sugar rows -- 381 duplicate
    # keys). The registry contract is vintage_retention: latest-only, and the
    # step-13/14 groupby-diff comments assume (MY, month) -> ONE release_date;
    # keep the newest release per key (it may carry revisions) BEFORE any
    # derived metric is computed.
    # -----------------------------------------------------------------------
    vintage_key = ["leviathan_slug", "country", "market_year", "wasde_release_month"]
    n_reprints = int(wide.duplicated(subset=vintage_key).sum())
    if n_reprints:
        logger.warning(
            "PSD transform: %d re-printed vintage rows across source releases; keeping latest release_date",
            n_reprints,
        )
        wide = (wide.sort_values(vintage_key + ["release_date"])
                    .drop_duplicates(subset=vintage_key, keep="last"))

    # -----------------------------------------------------------------------
    # 12. Compute su_ratio
    # -----------------------------------------------------------------------
    with np.errstate(divide="ignore", invalid="ignore"):
        wide["su_ratio"] = wide["ending_stocks_mt"] / wide["consumption_mt"]
    wide["su_ratio"] = wide["su_ratio"].replace([np.inf, -np.inf], np.nan)

    # -----------------------------------------------------------------------
    # 13. Compute su_ratio_yoy_delta
    # Within each (leviathan_slug, country, wasde_release_month), diff su_ratio
    # by market_year ascending.  Each market_year × month_code pair maps to a
    # unique release_date so grouping by release_date would produce singleton
    # groups (all NaN).  Grouping by wasde_release_month instead captures "at
    # the same point in the marketing calendar, how did the S/D balance shift
    # year-over-year?" — the economically meaningful comparison.
    # -----------------------------------------------------------------------
    wide = wide.sort_values(
        ["leviathan_slug", "country", "wasde_release_month", "market_year"]
    ).copy()
    wide["su_ratio_yoy_delta"] = wide.groupby(
        ["leviathan_slug", "country", "wasde_release_month"]
    )["su_ratio"].diff(1)

    # -----------------------------------------------------------------------
    # 14. Compute revision columns
    # Within each (leviathan_slug, country, market_year), diff across
    # wasde_release_month ascending: revision[M] = estimate[M] - estimate[M-1].
    # release_date is deterministic from (market_year, wasde_release_month) so
    # grouping by release_date inside the group would produce singletons (all NaN).
    # -----------------------------------------------------------------------
    wide = wide.sort_values(
        ["leviathan_slug", "country", "market_year", "wasde_release_month"]
    ).copy()
    revision_group_key = ["leviathan_slug", "country", "market_year"]
    for col in ("production_mt", "ending_stocks_mt", "consumption_mt"):
        wide[f"{col}_revision"] = wide.groupby(revision_group_key)[col].diff(1)

    # -----------------------------------------------------------------------
    # 15. Cast types
    # -----------------------------------------------------------------------
    wide["market_year"] = wide["market_year"].astype("Int16")
    wide["wasde_release_month"] = wide["wasde_release_month"].astype("Int8")

    # -----------------------------------------------------------------------
    # 16. Final column order
    # -----------------------------------------------------------------------
    wide = wide[_SILVER_COLS]

    logger.info(
        "PSD silver transform complete: rows=%d slugs=%d releases=%d",
        len(wide),
        wide["leviathan_slug"].nunique(),
        wide["release_date"].nunique(),
    )

    return wide


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _empty_silver() -> pd.DataFrame:
    """Return an empty DataFrame matching the silver schema."""
    schema: dict[str, pd.Series] = {
        "leviathan_slug":            pd.Series([], dtype="object"),
        "country":                   pd.Series([], dtype="object"),
        "market_year":               pd.Series([], dtype="Int16"),
        "wasde_release_month":       pd.Series([], dtype="Int8"),
        "release_date":              pd.Series([], dtype="object"),
        "beginning_stocks_mt":       pd.Series([], dtype="float64"),
        "production_mt":             pd.Series([], dtype="float64"),
        "imports_mt":                pd.Series([], dtype="float64"),
        "exports_mt":                pd.Series([], dtype="float64"),
        "ending_stocks_mt":          pd.Series([], dtype="float64"),
        "consumption_mt":            pd.Series([], dtype="float64"),
        "area_harvested_1000ha":     pd.Series([], dtype="float64"),
        "yield_mt_ha":               pd.Series([], dtype="float64"),
        "su_ratio":                  pd.Series([], dtype="float64"),
        "su_ratio_yoy_delta":        pd.Series([], dtype="float64"),
        "production_mt_revision":    pd.Series([], dtype="float64"),
        "ending_stocks_mt_revision": pd.Series([], dtype="float64"),
        "consumption_mt_revision":   pd.Series([], dtype="float64"),
    }
    return pd.DataFrame(schema)
