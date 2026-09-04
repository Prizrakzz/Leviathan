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

* **su_ratio_yoy_delta** — within each (leviathan_slug, country,
  wasde_release_month), the year-over-year diff of su_ratio across market_year,
  taken over the LATEST-VINTAGE reduction of each marketing year (see step 13).
  Available from the first release because the PSD snapshot spans ~65 marketing
  years.

* **revision columns** — month-on-month change within (leviathan_slug, country,
  market_year), ordered by RELEASE DATE ascending:
  revision[k] = estimate[release k] - estimate[release k-1].  The earliest
  release in a marketing year has no prior estimate, so its revision is NaN.
  Ordering on wasde_release_month (the shipped sort) was correct only while the
  rotation made month order equal chronological order; under the honest clock a
  marketing year's releases WRAP the calendar for any MYS != 1 commodity, so the
  diff would be taken in the wrong direction for 38 of the 47 mapped codes.

* **month_code = 0** — pre-WASDE-tracking historical estimates (MY ~1960–2004
  for older series).  Passed through as wasde_release_month = 0.

* **calendar_year IS THE CLOCK** (2026-09-04, the E re-baseline).  It used to be
  dropped here as "a batch-import artefact".  That sentence was false and it is
  what let the marketing-year rotation survive a year: measured on three banked
  bronze snapshots, ``Calendar_Year`` and ``Month`` together ARE the release
  stamp, and the rotation they replaced was exact on 3,276 of 1,653,988 stamped
  rows (0.20%).  ``calendar_year`` is now a REQUIRED bronze column and the input
  to :mod:`leviathan.transforms.bronze_to_silver.psd_clock`.  ``country_code`` is
  still dropped: it is 100% NULL in the PSD bulk CSV.

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
from leviathan.transforms.bronze_to_silver.psd_clock import (
    DISPOSITION_CLAMPED_CROSS_MONTH_DECLINED,
    DISPOSITION_CLAMPED_TO_INGEST,
    DISPOSITION_CLAMPED_TO_WASDE_DAY,
    DISPOSITION_MONTH_END_FALLBACK,
    psd_release_dates,
)

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
#  R1. EVERY MAPPED CODE MUST ALSO HAVE A _PSD_COMMODITY_TO_MYS ENTRY.  The two
#      dicts have identical key sets and a test asserts it.
#      THE MECHANISM CHANGED ON 2026-09-04 AND THE RULE DID NOT.  Until the
#      honest-clock re-baseline this rule enforced ITSELF by accident: step 4b did
#      ``.map(_PSD_COMMODITY_TO_MYS).astype(int)`` to rotate month_code, so a code
#      present here and absent there raised "cannot convert float NaN to integer"
#      for the WHOLE frame.  Deleting the rotation deleted that read, and with it
#      the blast radius -- the roster could have drifted in silence from the day
#      the clock landed.  So the fence is now EXPLICIT and NAMED
#      (``_assert_every_in_scope_code_has_a_marketing_year``, step 3b below): same
#      rule, same fail-closed behaviour, stated on purpose instead of inherited
#      from a cast.  An invariant that survives only as a side effect of code that
#      is about to be deleted is an invariant about to be lost.
#
#  R2. NO SLUG MAY APPEAR UNDER TWO CODES.  The pivot index is
#      (leviathan_slug, country, market_year, wasde_release_month, release_date)
#      and step 10 drops duplicates on
#      (leviathan_slug, country, market_year, release_date, attribute_desc),
#      ordered by bronze_ingest_date and keeping LAST.
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
# IT IS A ROSTER DECLARATION, NOT A CLOCK.  It USED to convert
# (market_year, month_code) → a WASDE calendar date, replacing the ingest
# timestamp bronze stores as release_date; that rotation was DELETED on
# 2026-09-04 (see the E re-baseline paragraph below).  Nothing reads these
# VALUES to compute a date any more.  What the dict still does is carry rule R1,
# and the fence that enforces R1 is now the explicit, named assertion
# _assert_every_in_scope_code_has_a_marketing_year at step 3b -- not a cast.
#
# WHERE THESE NUMBERS COME FROM, and what was MEASURED rather than assumed
# (D-EC XC-1, probe of the 2026-08-13 raw ZIP):
#   * The bulk CSV's ``Calendar_Year`` column CANNOT be used to derive a start
#     month.  It equals ``Market_Year`` for essentially every row; the handful
#     of offsets are noise.  (The module docstring already calls it a
#     batch-import artefact; this is the measurement behind that sentence.)
#     RE-MEASURED AND CORRECTED 2026-09-04 (the E re-baseline).  The claim above
#     is quoted as it read, and it is the sentence that let the rotation live.
#     Two things are wrong with it.  (a) It is a claim about the mc == 0 mass
#     only, and even there the equality is not "essentially every row": over
#     245,315 in-scope month_code-0 rows, Calendar_Year - Market_Year is 0 on
#     179,807 (73.3%), -1 on 59,544 (24.3%) and +1 on 5,964 (2.4%), concentrated
#     in dairy (fluid milk 17,496; cheese 12,609; butter 12,591; NFDM 12,240;
#     WMP 4,608) and citrus (oranges 3,836; OJ 2,128).  That is why mc == 0 stays
#     anchored to MARKET_YEAR-01-01: re-anchoring it on Calendar_Year would move
#     59,544 rows EARLIER, the leakage direction.  (b) The paragraph was read as
#     licence to ignore Calendar_Year for the STAMPED rows too, and there it is
#     simply the release's calendar year.  ZERO of the 47 MAPPED codes agree with
#     the source at 100% under the rotation -- the MYS = 1 families included,
#     because the formula's year base is market_year while the true stamp year is
#     Calendar_Year.
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
#   * IT HAS NOW BEEN ACTED ON (2026-09-04, lane E).  The follow-up the paragraph
#     above deferred is this change.  The rotation is DELETED:
#     _compute_psd_release_dates now delegates to psd_clock.psd_release_dates,
#     which dates a row from its OWN (Calendar_Year, Month) stamp.  The
#     re-baseline the paragraph feared is what shipped, measured end to end on
#     three banked bronze snapshots: 247,036 wide rows -> 247,294 (+258 older
#     vintages the shipped step-11.5 key was deleting), 809 distinct release_date
#     values -> 287 under a uniform WASDE day (439 with the eight World Markets
#     and Trade sheets on month-end), and the eight pivoted value columns
#     BYTE-IDENTICAL on all 247,036 joined keys.  E is a re-dating and a vintage
#     recovery, not a value change.
#   * SO _PSD_COMMODITY_TO_MYS IS NO LONGER A CLOCK.  It is a ROSTER FENCE and
#     nothing else: rule R1 below still requires every mapped code to carry an
#     entry, and the MECHANISM that enforces R1 changed with the rotation.  It
#     used to be enforced BY ACCIDENT -- step 4b's .map(...).astype(int) raised
#     "cannot convert float NaN to integer" for the WHOLE frame on a missing
#     entry -- and that cast is DELETED.  The fence is now
#     _assert_every_in_scope_code_has_a_marketing_year, called at step 3b right
#     after the commodity filter, and tests/unit/test_psd_slug_map_widening.py
#     holds it as the commodity-map completeness pin.  NOTHING reads its VALUES
#     to compute a date any more.  Do not delete it; do not resurrect it as a
#     date source.
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
    # E1 (2026-09-04): calendar_year is the CLOCK, so it is REQUIRED and the build
    # fails closed without it.  It already lands in bronze -- raw_to_bronze/
    # usda_psd.py:37-53 renames eleven known headers and :91-95 snake-cases every
    # remaining one; verified on all three banked bronze parquets (14 columns,
    # calendar_year int64, 0 nulls).  NO re-fetch and NO raw-lane change was
    # needed.  A missing stamp must stop the build, not silently fall back to a
    # convention: that is exactly how the rotation stayed invisible.
    "calendar_year",
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
# The clock counters the GATE reads
# ---------------------------------------------------------------------------
# E12: every one of these is emitted as a machine-readable field by the batch
# task's structured log, because a counter that lives only in a log SENTENCE is
# not a gate reading.  The prefix keys are minted by prepare_psd_combined_frame
# (shared with the long companion); the rest by the wide transform.
_CLOCK_COUNTER_KEYS: tuple[str, ...] = (
    "n_stamp_constancy_violations",      # expected 0, per INPUT snapshot
    "n_month_end_fallback",              # BRONZE-grain rows on the month-end convention
    "n_month_end_fallback_wide",         # ...and the SERVING-grain count, which is the
                                         #    one both cards and the gate quote
    "month_end_fallback_months",         # and WHICH stamp months they were
    "day_dispositions",                  # the day conventions rows SHIPPED with, counted:
                                         #    the clock's four, PLUS the three clamp names
                                         #    if and only if the clamp fired
    "n_clamped",                         # expected 0 under the honest clock
    "n_clamped_to_wasde_day",            # ...and how the firings were disposed of
    "n_clamped_to_ingest",
    "n_clamped_cross_month_declined",    # ...including the substitution REFUSED to keep
                                         #    release_date inside its own stamp month
    "n_step10_collapsed",                # identical-vintage re-prints removed
    "n_reprints_under_shipped_key",      # G1's identity: the rows the OLD key deleted
    "n_step13_declined_absent_comparator",   # su_ratio rows with no prior marketing year
    "n_distinct_release_dates",
    "n_calendar_months",
    "max_calendar_month",
)


# ---------------------------------------------------------------------------
# Public transform
# ---------------------------------------------------------------------------


_STAMP_CONSTANCY_KEY: list[str] = ["commodity_code", "country_name", "market_year"]


def _assert_every_in_scope_code_has_a_marketing_year(df: pd.DataFrame) -> None:
    """Rule R1's fence, explicit since the rotation that used to enforce it went away.

    _PSD_COMMODITY_TO_MYS is a ROSTER declaration now, not a clock: nothing reads
    its VALUES to compute a date.  The rule that the two maps carry identical key
    sets still stands -- a code with a slug and no declared marketing year is an
    undeclared commodity -- and it fails the build rather than the reader.
    """
    codes = set(pd.unique(df["commodity_code"]))
    missing = sorted(int(c) for c in codes if int(c) not in _PSD_COMMODITY_TO_MYS)
    if missing:
        raise ValueError(
            "PSD transform: in-scope commodity code(s) %s are mapped to slugs but carry no "
            "_PSD_COMMODITY_TO_MYS entry. The two maps are ONE universe (rule R1); a code with "
            "a home in one and not the other is an undeclared commodity." % missing
        )


def _assert_stamp_constant_per_snapshot(df: pd.DataFrame, i: int) -> int:
    """One bronze snapshot must carry ONE (Calendar_Year, Month) stamp per sheet-cell.

    THE PRECONDITION THE WIDE PIVOT RESTS ON.  A sheet-cell is
    (commodity_code, country_name, market_year); USDA prints it once per release,
    with one stamp.  If a single release ever published two stamps for one cell,
    pivot_index would shatter and the table would silently GAIN rows.  That must
    fail the build, not the reader.

    IT IS ASSERTED PER INPUT FRAME AND NEVER ON THE CONCAT, and the difference is
    the whole point.  MEASURED: 0 violations of 141,771 / 141,922 / 142,015
    in-scope sheet-cells per banked snapshot, but 2,607 (1.84%) across two
    concatenated snapshots and 3,290 of 142,015 (2.32%) across three -- because a
    cell's stamp legitimately ADVANCES between monthly releases.  The monthly task
    feeds every distinct-ETag partition from a bucket that holds nine, so an
    assertion moved after ``pd.concat`` at step 2 is guaranteed to raise on its
    first real fire.  It would kill the build, not the data.

    IT IS ALSO SCOPED TO THE MAPPED CODES, INSIDE THIS HELPER.  The call site is
    step 1, which runs BEFORE the step-3 commodity filter, so the raw frame it is
    handed carries all 63 codes the bulk ZIP publishes -- 162,544 / 162,695 /
    162,788 sheet-cells across the three banked snapshots, of which 20,773 belong
    to the 16 codes this transform REFUSES (see _PSD_UNMAPPED_CODES).  Unfiltered,
    a stamp anomaly in a code the table never serves would hard-abort psd_monthly
    for a fact no reader can reach, and the figures above -- which are the
    in-scope population -- would not be the ones the assertion measures.  The
    filter therefore lives HERE rather than at the call site, because the
    per-INPUT-SNAPSHOT placement is load-bearing and must not move to after the
    concat to buy the scoping.  Its R1 sibling
    (_assert_every_in_scope_code_has_a_marketing_year) is placed after the filter
    for the same reason, stated the other way round.

    Returns:
        The number of violating sheet-cells (always 0 on a healthy snapshot).
    """
    cols = _STAMP_CONSTANCY_KEY + ["calendar_year", "month_code"]
    if any(c not in df.columns for c in cols):
        return 0
    sub = df.loc[df["commodity_code"].isin(_PSD_COMMODITY_TO_SLUGS), cols]
    if sub.empty:
        return 0
    n_stamps = sub.groupby(_STAMP_CONSTANCY_KEY, dropna=False, sort=False)[
        ["calendar_year", "month_code"]
    ].nunique()
    bad = n_stamps[(n_stamps["calendar_year"] > 1) | (n_stamps["month_code"] > 1)]
    n_bad = int(len(bad))
    if n_bad:
        raise ValueError(
            "PSD bronze DataFrame[%d] carries %d IN-SCOPE sheet-cell(s) with MORE THAN ONE "
            "(calendar_year, month_code) stamp inside ONE release. The wide pivot's index "
            "assumes one stamp per (commodity_code, country_name, market_year) per release; "
            "two would shatter it and silently add rows. First offenders: %s"
            % (i, n_bad, [tuple(k) for k in bad.index[:5]])
        )
    return n_bad


def _compute_psd_release_dates(
    df: pd.DataFrame,
    *,
    calendar: dict[str, int],
) -> pd.Series:
    """Date every row from its OWN (Calendar_Year, Month) stamp.

    The MARKETING-YEAR ROTATION IS GONE.  It used to read month_code as an
    MY-relative index and rotate it by _PSD_COMMODITY_TO_MYS; measured on three
    banked bronze snapshots it was exact on 0.20% of stamped rows, EARLY on 97.4%
    and LATE on 2.4%, and ZERO of the 47 mapped codes agreed at 100%.

    The rule now lives in ONE place --
    :func:`leviathan.transforms.bronze_to_silver.psd_clock.psd_release_dates` --
    which the long companion and (when it lands) the archive backfill call too.
    A per-lane copy is a kill condition.

    Args:
        df: The post-explode combined frame.  Needs commodity_code, market_year,
            calendar_year and month_code.
        calendar: ``{'YYYY-MM': day}`` from the REGISTERED silver_wasde
            partitions.  Keyword-only with NO DEFAULT -- a default is a silent
            fallback to a stale or empty calendar, which is the defect this
            change exists to close wearing a different hat.

    Returns:
        The release_date Series.  ``month_code == 0`` still maps to
        ``market_year-01-01`` exactly as the shipped line did; that pin is what
        keeps 30,715 wide rows byte-identical across E.
    """
    dates, _ = psd_release_dates(
        df["commodity_code"], df["market_year"], df["calendar_year"], df["month_code"],
        calendar=calendar,
    )
    return dates


def prepare_psd_combined_frame(
    dfs: list[pd.DataFrame],
    *,
    calendar: dict[str, int],
    extra_required: frozenset[str] = frozenset(),
    counters: dict | None = None,
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

    It also carries ``day_disposition`` -- the day convention each row SHIPPED
    with, POST-CLAMP, as a categorical.  Neither table emits it; the wide producer
    counts its serving-grain fallback rows off it (step 11.5) instead of guessing
    the convention back from release_date's month.

    MEASURED (2026-08-13 bulk object): the three remaps are 1:1 RENAMES, not
    merges -- codes 612000 / 2631000 / 571120 publish NO attribute_id 125 of their
    own, so folding 126 / 142 / 135 onto "Domestic Consumption" can never collide
    with a genuine 125 row.  Either label choice is therefore grain-safe; the long
    table takes the native one for fidelity, not to dodge a collision.

    Args:
        dfs: List of bronze DataFrames.  Must be non-empty.
        calendar: ``{'YYYY-MM': day}`` built from the REGISTERED silver_wasde
            partitions, read at RUN TIME by the batch task and passed straight
            through to the clock.  Keyword-only with NO DEFAULT.
        extra_required: Column names required IN ADDITION to :data:`_REQUIRED_COLS`
            (the long producer adds ``attribute_id``).
        counters: Optional dict the transform fills with machine-readable run
            counters (see :data:`_CLOCK_COUNTER_KEYS`).  The batch task passes one
            and logs it, because a counter that lives only in a log SENTENCE is
            not a gate reading.

    Returns:
        The combined frame at the branch point, or an EMPTY frame when no row
        survives the commodity filter.  Callers own their own empty schema.

    Raises:
        ValueError: If *dfs* is empty, required columns are missing, or one input
            snapshot carries two stamps for one sheet-cell.
        psd_clock.PsdClockError: If a stamp month is newer than the calendar's.
    """
    if not dfs:
        raise ValueError("dfs must contain at least one DataFrame")
    counters = {} if counters is None else counters

    # -----------------------------------------------------------------------
    # 1. Validate required columns, and assert the stamp is CONSTANT per snapshot
    # -----------------------------------------------------------------------
    required = _REQUIRED_COLS | frozenset(extra_required)
    n_constancy_violations = 0
    for i, df in enumerate(dfs):
        missing = required - set(df.columns)
        if missing:
            raise ValueError(
                f"PSD bronze DataFrame[{i}] missing required columns: {missing}. "
                f"Got: {list(df.columns)}"
            )
        # PER FRAME, INSIDE THIS LOOP -- never after the concat at step 2.  See
        # _assert_stamp_constant_per_snapshot for the 0-per-snapshot / 3,290-on-three
        # measurement that makes the placement load-bearing.  The helper scopes
        # ITSELF to the mapped codes, which is why this call can stay here, ahead
        # of the step-3 filter: the two properties (per-snapshot, in-scope) are
        # both required and neither may be bought with the other.
        n_constancy_violations += _assert_stamp_constant_per_snapshot(df, i)
    counters["n_stamp_constancy_violations"] = n_constancy_violations

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
    # 3b. Rule R1, made EXPLICIT (2026-09-04)
    # -----------------------------------------------------------------------
    # See the R1 paragraph in this module's header.  This assertion replaces the
    # accidental enforcement the retired marketing-year rotation provided, and it
    # is deliberately placed AFTER the commodity filter so it speaks only about
    # codes this transform actually serves.
    _assert_every_in_scope_code_has_a_marketing_year(combined)

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
    # F2 clamp, RE-AUTHORED FOR THE HONEST CLOCK.  A release_date can never
    # post-date the snapshot that observed it, so every computed date is bounded
    # above by that row's bronze ingest date.  Under the retired rotation the
    # clamp fired on 78,738 exploded rows, because the MY-relative formula
    # projected current-crop rows into 2027.  Under the honest clock it is
    # STRUCTURALLY INERT: 0 firings on all three banked snapshots, under BOTH day
    # rules, with the eight-code month-end set.  An inert fence that fires is a
    # clock-regression alarm, so it is KEPT and COUNTED rather than deleted.
    #
    # WHAT IT DOES WHEN IT FIRES, and why it never raises here.  The only way a
    # date can exceed ingest on the monthly path is a World Markets and Trade
    # sheet whose stamp month is the SNAPSHOT's own month: month-end then sits
    # after a day-8-13 fetch.  Measured headroom for that case today is 13 days
    # over 333,744 stamped WM&T rows -- real, currently unfired, and NOT a reason
    # to hard-fail the monthly job in a month the three banked snapshots (May,
    # July, August) cannot observe.  So the clamp DISPOSES of the row by name:
    #
    #   clamped_to_wasde_day  the WM&T row's stamp month HAS a registered WASDE
    #                         day AND that day is itself on or before the ingest
    #                         date, so take it -- a published date rather than a
    #                         download date, and it precedes month-end by
    #                         construction.
    #   clamped_to_ingest     no registered day exists for that month, or the
    #                         registered day is ALSO after the snapshot, so fall
    #                         back to the ingest date -- the shipped behaviour and
    #                         the only bound left. The second half of that
    #                         condition matters: a circular stamped in the
    #                         snapshot's own month can sit after a day-8 fetch on
    #                         BOTH candidate days, and substituting a date that is
    #                         still in the future would leave the per-row bound
    #                         violated for the task's own fail-closed guard to
    #                         find as a hard abort. Naming it here keeps it a
    #                         counted disposition instead.
    #                         THE INGEST DATE IS ONLY TAKEN INSIDE THE STAMP
    #                         MONTH -- see the next disposition for why.
    #   clamped_cross_month_declined
    #                         the ingest date lies OUTSIDE the stamp month, so the
    #                         substitution is DECLINED BY NAME rather than made.
    #                         P21 -- release_date determines wasde_release_month --
    #                         is what step 10's dedup key and the numbers card's
    #                         refusal to declare a vintage_tiebreak both rest on,
    #                         and a cross-month clamp breaks it: a row stamped
    #                         2026-08 in a partition ingested 2026-07-30 would land
    #                         release_date '2026-07-30' against
    #                         wasde_release_month 8, and step 10 would then key two
    #                         genuinely different vintages onto one date. So the
    #                         row keeps a date INSIDE its own stamp month: the
    #                         registered WASDE day if the month has one, else the
    #                         month's FIRST day -- the earliest date the month can
    #                         offer, which is the closest the stamp month can come
    #                         to honouring the ingest bound without lying about
    #                         which month published it. The row is COUNTED under
    #                         its own name so a reader sees a declined clamp rather
    #                         than an honoured one, and the task's fail-closed
    #                         guard still sees the residual future date and aborts
    #                         -- which is the correct outcome, because a stamp
    #                         month that post-dates the whole snapshot means the
    #                         clock and the source have diverged.
    #
    # All three are COUNTED and surfaced to the gate; all three are expected 0.
    # THE CLAMP REWRITES `disposition` TOO, not just the date.  day_dispositions is
    # a gate reading, and a clamped row whose disposition still reads
    # 'month_end_wmt' tells the gate the pre-clamp convention while n_clamped_*
    # tells it the post-clamp one -- two counters describing the same row and
    # disagreeing.  After this block, day_dispositions reports POST-CLAMP.
    #
    # The RAISE is reserved for the case that genuinely means our clock is behind
    # the source: a stamp month NEWER than the live calendar's newest month, which
    # psd_clock raises on before any of this runs.
    #
    # Both series are ISO-8601 'YYYY-MM-DD' strings, which sort lexicographically
    # == chronologically, so every comparison here is exact and release_date keeps
    # its object/string dtype.
    ingest_date = pd.to_datetime(combined["release_date"]).dt.strftime("%Y-%m-%d")
    computed_date, disposition = psd_release_dates(
        combined["commodity_code"], combined["market_year"],
        combined["calendar_year"], combined["month_code"],
        calendar=calendar,
    )
    too_late = computed_date > ingest_date
    n_clamped = int(too_late.sum())
    counters["n_clamped"] = n_clamped
    counters["n_clamped_to_wasde_day"] = 0
    counters["n_clamped_to_ingest"] = 0
    counters["n_clamped_cross_month_declined"] = 0
    if n_clamped:
        stamp_month = computed_date.str.slice(0, 7)
        registered = stamp_month.map(calendar)
        wasde_day_date = (stamp_month + "-"
                          + registered.fillna(0).astype(int).astype(str).str.zfill(2))
        month_first_date = stamp_month + "-01"
        # The ingest substitution is legal only INSIDE the stamp month; outside it
        # the clamp would rewrite which month published the row (P21).
        ingest_in_stamp_month = ingest_date.str.slice(0, 7) == stamp_month
        to_wasde_day = too_late & registered.notna() & (wasde_day_date <= ingest_date)
        remainder = too_late & ~to_wasde_day
        to_ingest = remainder & ingest_in_stamp_month
        cross_month = remainder & ~ingest_in_stamp_month
        cross_month_to_wasde = cross_month & registered.notna()
        cross_month_to_first = cross_month & registered.isna()
        counters["n_clamped_to_wasde_day"] = int(to_wasde_day.sum())
        counters["n_clamped_to_ingest"] = int(to_ingest.sum())
        counters["n_clamped_cross_month_declined"] = int(cross_month.sum())
        computed_date = computed_date.mask(to_wasde_day, wasde_day_date)
        computed_date = computed_date.mask(to_ingest, ingest_date)
        computed_date = computed_date.mask(cross_month_to_wasde, wasde_day_date)
        computed_date = computed_date.mask(cross_month_to_first, month_first_date)
        disposition = disposition.mask(to_wasde_day, DISPOSITION_CLAMPED_TO_WASDE_DAY)
        disposition = disposition.mask(to_ingest, DISPOSITION_CLAMPED_TO_INGEST)
        disposition = disposition.mask(
            cross_month, DISPOSITION_CLAMPED_CROSS_MONTH_DECLINED
        )
        logger.warning(
            "PSD transform: release-date clamp fired on %d row(s) -- %d took the registered "
            "WASDE day of their stamp month, %d took the bronze ingest date, %d DECLINED the "
            "substitution because the ingest date falls outside the stamp month and taking it "
            "would break release_date -> wasde_release_month. The clamp is expected to be INERT "
            "under the honest clock; a firing is a clock-regression alarm.",
            n_clamped, counters["n_clamped_to_wasde_day"], counters["n_clamped_to_ingest"],
            counters["n_clamped_cross_month_declined"],
        )
    # THE COUNTERS ARE MINTED AFTER THE CLAMP, so every one of them reports the
    # convention the row actually SHIPS with.  n_month_end_fallback and
    # month_end_fallback_months therefore exclude a fallback row the clamp moved,
    # and day_dispositions carries the three clamp names when (and only when) the
    # clamp fired.
    counters["n_month_end_fallback"] = int(
        (disposition == DISPOSITION_MONTH_END_FALLBACK).sum()
    )
    counters["month_end_fallback_months"] = sorted(
        {d[:7] for d in computed_date[disposition == DISPOSITION_MONTH_END_FALLBACK]}
    )
    counters["day_dispositions"] = {
        str(k): int(v) for k, v in disposition.value_counts().items()
    }
    combined["release_date"] = computed_date
    # The day convention this row SHIPPED with, carried to the branch point so the
    # wide producer can count its fallback rows at the SERVING grain BY DISPOSITION
    # rather than by month membership.  The long companion ignores it (it selects
    # _SILVER_PSD_ATTR_COLS at the end), and the wide pivot drops it: it is a
    # measurement channel, not a silver column.  CATEGORICAL on purpose -- at most
    # seven distinct values over an exploded frame that reaches ~30M rows on nine
    # bronze partitions, and this task's peak RSS is a read the runbook takes.
    combined["day_disposition"] = disposition.astype("category")
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
    *,
    calendar: dict[str, int],
    counters: dict | None = None,
) -> pd.DataFrame:
    """Convert one or more bronze PSD DataFrames into a single silver DataFrame.

    Each element of *dfs* is one ``release_date`` partition read from S3
    (``bronze/production/source=usda_psd/release_date=.../part-000.parquet``).
    Passing multiple DataFrames enables revision-diff computation across
    sequential WASDE releases.

    Args:
        dfs: List of bronze DataFrames.  Must be non-empty.
        calendar: ``{'YYYY-MM': day}`` from the REGISTERED silver_wasde
            partitions.  Keyword-only, NO DEFAULT.
        counters: Optional dict filled with the :data:`_CLOCK_COUNTER_KEYS` run
            counters for the batch task's structured log and the gate.

    Returns:
        Wide-format silver DataFrame with :data:`_SILVER_COLS` columns.

    Raises:
        ValueError: If *dfs* is empty, required columns are missing, an
                    unrecognised ``unit_desc`` appears for an in-scope row, one
                    snapshot carries two stamps for one sheet-cell, or the
                    post-pivot vintage key is not unique.
    """
    counters = {} if counters is None else counters
    # Steps 1-5 are shared with the long companion producer; see
    # prepare_psd_combined_frame for why they live in one place.
    combined = prepare_psd_combined_frame(dfs, calendar=calendar, counters=counters)
    counters["n_calendar_months"] = len(calendar)
    counters["max_calendar_month"] = max(calendar) if calendar else None
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
    # THE DEDUP KEY IS THE VINTAGE KEY, AND IT SHEDS wasde_release_month (E6).
    # It used to read `dedup_key = pivot_index + ["attribute_desc"]`.  That
    # identity is no longer true, and leaving it in place would leave a FALSE
    # sentence in a load-bearing comment.  The new relation, stated explicitly:
    #
    #   dedup_key == pivot_index MINUS wasde_release_month PLUS attribute_desc
    #
    # and it discriminates IDENTICALLY, because under the honest clock
    # release_date DETERMINES wasde_release_month -- release_date[5:7] IS the
    # stamp month for every stamped row, and every mc == 0 row carries
    # market_year-01-01, a value no real stamp can produce (real days are 8..14,
    # the declared 2008-10-28 exception, or month-end).  That invariant is
    # PINNED by a test rather than left implicit, because two other rulings lean
    # on it silently: this key, and the numbers card's refusal to declare a
    # vintage_tiebreak.
    #
    # THE UNSTATED PREMISE, NOW STATED: the mc == 0 anchor is distinguishable from
    # a real stamp only because NO REGISTERED WASDE MONTH RESOLVES TO A DAY-1
    # JANUARY.  Measured on the 472 registered partitions: exactly one month lands
    # on day 1 at all -- 2000-04 -- and no January does, in any year, including the
    # pre-2006 span where the days run 1..16 and the 8..14 fence does not apply.
    # If a January-day-1 release were ever registered, a stamped January row would
    # collide with that marketing year's mc == 0 anchor on this key and step 10
    # would drop one of them by bronze_ingest_date, silently.  It is a property of
    # the calendar we read, not of the clock, so it is pinned in
    # tests/unit/test_psd_clock.py over the banked calendar rather than asserted
    # here -- a producer-side raise would red a correct run for a real USDA
    # scheduling change, and this key is not where that decision belongs.
    #
    # WHY IT MATTERS ANYWAY.  wasde_release_month is now a CALENDAR month, so two
    # releases twelve months apart share it.  Keying anything that DELETES rows on
    # it would delete the older vintage; this key names release_date instead, so
    # only byte-identical RE-PRINTS of one release collapse (0 value disagreements
    # among 1,848,919 same-stamp rows, measured across two snapshots 85 days
    # apart).  Every distinct release survives.
    dedup_key = [
        "leviathan_slug",
        "country",
        "market_year",
        "release_date",
        "attribute_desc",
    ]
    n_dupes = int(combined.duplicated(subset=dedup_key).sum())
    counters["n_step10_collapsed"] = n_dupes
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
    # 11.5 THE VINTAGE KEY BECOMES AN ASSERTION -- and it MINTS G1's counter FIRST
    #
    # It used to be a latest-only drop_duplicates on
    # (slug, country, market_year, wasde_release_month), keeping the newest
    # release_date.  Under the marketing-year rotation that key was safe, because
    # release_date was a FUNCTION of (market_year, month_code) and one marketing
    # year could not reach the same month twice.  Under the honest clock
    # wasde_release_month is a CALENDAR month, so two genuinely different
    # releases twelve months apart collide on it and the newest-wins reduction
    # DELETES the older one.  MEASURED on three banked bronze snapshots: 258 rows.
    # Under a 238-file archive backfill the same key would cap every sheet-cell at
    # twelve vintages FOREVER.  Shipping the clock without this re-key is worse
    # than not shipping the clock.
    #
    # THE COUNTER IS MINTED BEFORE THE ASSERTION AND IT IS NOT DECORATION.  Gate
    # G1's whole identity is
    #
    #   row_count_after == row_count_before + n_reprints_under_shipped_key
    #
    # and a post-E run has NOWHERE ELSE to get that number: the rotation that
    # produced the 247,036 baseline is deleted, and step 10's collapse count is
    # three orders of magnitude away (3,291,515 against 258).  One duplicated()
    # call is what makes G1 non-vacuous.
    # -----------------------------------------------------------------------
    shipped_vintage_key = ["leviathan_slug", "country", "market_year", "wasde_release_month"]
    n_reprints_under_shipped_key = int(wide.duplicated(subset=shipped_vintage_key).sum())
    counters["n_reprints_under_shipped_key"] = n_reprints_under_shipped_key
    if n_reprints_under_shipped_key:
        logger.info(
            "PSD transform: %d row(s) share a (slug, country, market_year, calendar-month) key "
            "under DIFFERENT release_dates -- older vintages the retired latest-only key would "
            "have deleted. They are KEPT; this count is gate G1's row-delta identity.",
            n_reprints_under_shipped_key,
        )

    # THE SERVING-GRAIN FALLBACK COUNT, KEYED ON THE DISPOSITION THE ROW SHIPPED
    # WITH.  It used to be computed at step 16 by testing release_date's MONTH
    # against month_end_fallback_months, which is a different number wearing the
    # same name: a World Markets and Trade sheet stamped inside one of those
    # months takes month_end_wmt, not the fallback, and was counted anyway.
    # MEASURED on the three banked snapshots: 39 wide rows, so the month-keyed
    # figure read 51,454 where the disposition-keyed one reads 51,415.  Both cards
    # and gate G6 quote this counter, so it has to measure the thing it is named
    # after.  The join is on the pivot index because that IS the wide grain, and
    # the disposition is constant within it (rule R2 gives each slug exactly one
    # commodity code, and the clock's answer is a function of that code and the
    # stamp).  It is computed HERE, before step 15's Int16/Int8 casts, so the key
    # dtypes on both sides still match.
    _fallback_wide = int(
        wide.loc[:, pivot_index]
            .merge(combined.loc[:, pivot_index + ["day_disposition"]]
                           .drop_duplicates(subset=pivot_index),
                   on=pivot_index, how="left")["day_disposition"]
            .eq(DISPOSITION_MONTH_END_FALLBACK).sum()
    )

    vintage_key = ["leviathan_slug", "country", "market_year", "release_date"]
    n_true_dupes = int(wide.duplicated(subset=vintage_key).sum())
    if n_true_dupes:
        offenders = (wide.loc[wide.duplicated(subset=vintage_key, keep=False), vintage_key]
                         .drop_duplicates().head(5).to_dict("records"))
        raise ValueError(
            "PSD transform: %d post-pivot row(s) duplicate the vintage key %s. One release of "
            "one sheet-cell must produce exactly ONE row; a duplicate here means step 10's "
            "collapse did not hold or the pivot index shattered. First offenders: %s"
            % (n_true_dupes, vintage_key, offenders)
        )

    # -----------------------------------------------------------------------
    # 12. Compute su_ratio
    # -----------------------------------------------------------------------
    with np.errstate(divide="ignore", invalid="ignore"):
        wide["su_ratio"] = wide["ending_stocks_mt"] / wide["consumption_mt"]
    wide["su_ratio"] = wide["su_ratio"].replace([np.inf, -np.inf], np.nan)

    # -----------------------------------------------------------------------
    # 13. Compute su_ratio_yoy_delta -- THE LATEST-VINTAGE REDUCTION
    #
    # Within each (leviathan_slug, country, wasde_release_month), diff su_ratio by
    # market_year ascending: "at the same point in the release calendar, how did
    # the S/D balance shift year-over-year?"
    #
    # WHAT CHANGED AND WHY.  The shipped code diffed the group's rows directly.
    # That was safe only while (market_year, month_code) mapped to ONE
    # release_date; step 11.5 now KEEPS the older vintage instead of deleting it,
    # so a group can hold two rows for one marketing year and a bare .diff(1)
    # would emit a WITHIN-marketing-year difference wearing a year-over-year
    # label, and shift its neighbour's.  MEASURED on three banked snapshots: 258
    # such groups, 514 of their 516 rows carrying a live su_ratio and 216 of them
    # carrying DIFFERING su_ratios -- i.e. the false delta would be non-zero, not
    # cosmetic.
    #
    # THE RULE: reduce each (slug, country, wasde_release_month, market_year) to
    # its LATEST release_date, diff across adjacent marketing years there, and
    # attach the result to that latest-vintage row.  A NON-LATEST vintage carries
    # NULL by construction -- it is not the year's current estimate.  A marketing
    # year with no predecessor in its group DECLINES BY NAME and is counted.
    #
    # MEASURED AGAINST THE LIVE CANONICAL: this rule reproduces today's column
    # BYTE-IDENTICALLY -- 0 differing of 247,036 joined keys, non-null count
    # unchanged at 211,890 -- so su_ratio_yoy_delta stays inside the flip's
    # byte-identity pin and stays above its 0.6 min_nonnull_frac floor (85.7% of
    # 247,294 rows), which is the floor jobs/audit/silver_rebuild_gate.py's
    # value-census stage measures on every gate run.
    #
    # WHAT THIS IS NOT.  The card's phrase "the SAME release month of the estimate
    # cycle" was true by CONSTRUCTION under the rotation, because MY(n) month m sat
    # exactly one year after MY(n-1) month m.  Under the honest clock the two
    # compared vintages can be several calendar years apart, and the card text is
    # re-authored to say so.  The genuinely same-CYCLE comparator (MY(n) at
    # calendar year cy against MY(n-1) at cy-1) is servable only where every
    # release is its own partition: on this BULK-UNION table it finds a partner for
    # 14.2% of live-su rows and would take the column's coverage from 211,890 to
    # 33,583 non-null rows (-84.2%), below the contract floor.  It belongs to the
    # per-release vintage table, not here.
    # -----------------------------------------------------------------------
    yoy_group_key = ["leviathan_slug", "country", "wasde_release_month"]
    latest = (wide.sort_values(yoy_group_key + ["market_year", "release_date"],
                               kind="stable")
                  .drop_duplicates(subset=yoy_group_key + ["market_year"], keep="last")
                  .sort_values(yoy_group_key + ["market_year"], kind="stable")
                  .copy())
    latest["su_ratio_yoy_delta"] = latest.groupby(
        yoy_group_key, dropna=False
    )["su_ratio"].diff(1)
    counters["n_step13_declined_absent_comparator"] = int(
        (latest["su_ratio"].notna() & latest["su_ratio_yoy_delta"].isna()).sum()
    )
    wide = wide.merge(
        latest[yoy_group_key + ["market_year", "release_date", "su_ratio_yoy_delta"]],
        on=yoy_group_key + ["market_year", "release_date"],
        how="left",
    )

    # -----------------------------------------------------------------------
    # 14. Compute revision columns -- ORDERED BY RELEASE DATE
    # Within each (leviathan_slug, country, market_year), diff across RELEASE
    # DATE ascending: revision[k] = estimate[release k] - estimate[release k-1].
    #
    # THE SORT KEY MOVED, AND IT HAD TO.  The shipped sort was on
    # wasde_release_month, which equalled chronological order only because the
    # retired rotation made it so.  Under the honest clock a marketing year's
    # releases WRAP the calendar for every MYS != 1 commodity -- corn MY2024 runs
    # calendar months 5..12 of 2024 and then 1..4 of 2025 -- so a month-ordered
    # sort puts January 2025 BEFORE May 2024 and every one of the three revision
    # columns becomes a difference taken in the WRONG DIRECTION for 38 of the 47
    # mapped codes.  It would not surface for a long time: these columns are ~2.5%
    # non-null today (the contract's own min_nonnull_frac_overrides say 0.025), so
    # the sign error only becomes visible once an archive backfill makes them
    # dense.
    #
    # WHAT THE COLUMNS MEAN AFTER THE RE-BASELINE: still a diff WITHIN ONE BULK
    # SNAPSHOT's set of surviving vintages, now correctly ordered.  A true
    # cross-vintage revision series needs one partition per release and is a
    # property of the per-release vintage table, not of this one.
    # -----------------------------------------------------------------------
    wide = wide.sort_values(
        ["leviathan_slug", "country", "market_year", "release_date"]
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

    counters["n_distinct_release_dates"] = int(wide["release_date"].nunique())
    # The SERVING-grain fallback count, computed at step 11.5 -- see there for the
    # disposition-keyed rule and why the month-keyed one it replaced was 39 rows
    # high.  WHY BOTH GRAINS ARE COUNTED: the prefix counts month-end fallback rows
    # at the exploded BRONZE grain, over EVERY attribute label rather than the
    # eight the wide pivot keeps, and that number is ~45x larger -- 2,312,799
    # against 51,415 on the three banked snapshots, inside full-frame
    # day_dispositions of 5,541,672 registered_wasde_day / 2,312,799
    # month_end_fallback / 1,278,861 mc_zero_anchor / 863,887 month_end_wmt.  It is
    # not the number the cards or the gate quote; one row in five of the SERVED
    # table is the sentence a reader has to be given, in figures.
    counters["n_month_end_fallback_wide"] = _fallback_wide

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
