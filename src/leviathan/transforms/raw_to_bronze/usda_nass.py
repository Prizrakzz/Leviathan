"""Bronze transform for USDA NASS QuickStats bulk crops download.

Reads the tab-delimited, gzip-compressed QuickStats CROPS sector file and
produces two bronze series:

``annual``
    Standard annual crop statistics (Area Planted, Area Harvested, Yield,
    Production) at the national and state level.  Filtered to the leviathan
    commodity universe.

``crop_progress``
    Weekly Crop Progress percentages (Good/Excellent % is the primary
    feature; all PROGRESS and CONDITION rows are retained).  Filtered to
    grains + oilseeds only.

Memory note
-----------
The full .gz file is ~1 GB uncompressed.  This transform streams it in
chunks of 100,000 rows to stay within Fargate container memory limits.
The Batch submission script should allocate ≥4 GB of container memory.

Commodity mapping
-----------------
NASS uses its own ``commodity_desc`` values (e.g. "CORN", "SOYBEANS").
The mappings are ``_ANNUAL_COMMODITY_MAP`` and ``_PROGRESS_COMMODITY_MAP``
below (there is no ``_NASS_SLUG_MAP``; that name was stale documentation).
Only rows whose ``commodity_desc`` appears in the relevant map are retained.

A map VALUE is the bronze PARTITION BUCKET, not the silver slug: several
source commodities deliberately share one bucket (the coarse-grain and
oilseed proxies), and the bronze partition ``soft_red_winter_wheat_cbot``
holds every wheat class. The silver transforms re-canonicalise from
``commodity_desc`` + ``class_desc``, so a bucket name is never a claim
about what the rows are.

What the ANNUAL lane's gates DROP is written down, with its measured row
count, in ``_RECORDED_STAT_CAT_EXCLUSIONS`` (the value axis, complete over
all 136 census cats) and ``_RECORDED_COMMODITY_EXCLUSIONS`` (the commodity
axis at NATIONAL/STATE scope ONLY -- the registry's own header states the
larger physical bronze drop it does not enumerate, and
``_PROGRESS_COMMODITY_MAP`` has no exclusions registry at all yet) --
documentation with a test, never control flow. The registries are a FLOOR
on what is written down, never a claim that every dropped row is.
"""
from __future__ import annotations

import io

import pandas as pd

from leviathan.common.logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Commodity mapping: NASS commodity_desc → leviathan slug
# ---------------------------------------------------------------------------

# Annual crops: area / yield / production
_ANNUAL_COMMODITY_MAP: dict[str, str] = {
    "CORN":           "corn_cbot",
    "SOYBEANS":       "soybean_meal_cbot",   # proxy — NASS has no meal-only series
    # D-EC P0: NASS carries EVERY wheat class under commodity_desc='WHEAT' (4,150,930 measured rows)
    # with the class on class_desc, so this ONE key admits winter, spring, durum and the nine
    # sub-classes. The former "WHEAT, WINTER" / "WHEAT, SPRING" / "WHEAT, DURUM" keys matched
    # NOTHING in the source's 278-value commodity_desc census and are deleted rather than left to
    # read as coverage they never provided.
    "WHEAT":          "soft_red_winter_wheat_cbot",
    "COTTON":         "cotton",
    "RICE":           "rough_rice_cbot",
    "SORGHUM":        "corn_cbot",   # sorghum aggregated with coarse grains
    "OATS":           "corn_cbot",   # coarse grains
    "BARLEY":         "corn_cbot",   # coarse grains
    "SUGARCANE":      "raw_sugar",
    "SUGARBEETS":     "raw_sugar",   # source spelling; "SUGAR BEETS" matched none of 278 values
    "SUNFLOWER":      "soybean_meal_cbot",  # oilseeds proxy
    "CANOLA":         "canola_ice",
}

# Weekly crop progress: Good/Excellent % and related condition/progress rows
_PROGRESS_COMMODITY_MAP: dict[str, str] = {
    "CORN":       "corn_cbot",
    "SOYBEANS":   "soybean_meal_cbot",
    "WHEAT":      "soft_red_winter_wheat_cbot",
    "COTTON":     "cotton",
    "SORGHUM":    "corn_cbot",
    "RICE":       "rough_rice_cbot",
    "OATS":       "corn_cbot",
    "BARLEY":     "corn_cbot",
}

# Columns to keep in annual series
_ANNUAL_KEEP_COLS = [
    "source_desc", "sector_desc", "group_desc", "commodity_desc",
    "class_desc", "prodn_practice_desc", "util_practice_desc",
    "domain_desc", "domaincat_desc", "short_desc", "freq_desc",
    "reference_period_desc",
    "statisticcat_desc", "unit_desc",
    "agg_level_desc", "state_alpha", "state_name",
    "county_code", "county_name",
    "year", "value",
    "CV_%",
]

# Columns to keep in crop progress series
_PROGRESS_KEEP_COLS = [
    "source_desc", "commodity_desc", "class_desc",
    "prodn_practice_desc", "util_practice_desc",
    "domain_desc", "domaincat_desc", "short_desc",
    "statisticcat_desc", "unit_desc",
    "agg_level_desc", "state_alpha", "state_name",
    "year", "week_ending", "value",
]

_ANNUAL_STAT_CATS = frozenset({
    "AREA PLANTED", "AREA HARVESTED", "YIELD", "PRODUCTION",
})

_PROGRESS_STAT_CATS = frozenset({
    "PROGRESS", "CONDITION",
})

# ---------------------------------------------------------------------------
# THE MEASURED REFUSALS -- what the gates above drop, written down (C-2, 2026-08-25).
# ---------------------------------------------------------------------------
# MEASURED, NOT INFERRED. One stream of the raw object the estate already owns --
# s3://leviathan-dev-shahem-001/raw/production/source=usda_nass/sector=crops/
# download_date=2026-08-18/qs.crops.txt.gz, 1,128,974,735 B, ETag
# 1cc6f2250173d2154d69b0e83cd32fd0, 23,866,721 rows, 0 malformed lines -- tallied
# statisticcat_desc x agg_level_desc x commodity_desc. No Athena, no re-fetch. Every literal below
# is a cell of the artifact named in _VALUE_AXIS_CENSUS_ARTIFACT, and the pinning test names it too.
#
# DOCUMENTATION WITH A TEST, NEVER CONTROL FLOW -- the pattern proven on
# ``_RECORDED_CLASS_EXCLUSIONS`` (bronze_to_silver/usda_nass_annual.py:242). ``extract_usda_nass``
# does not read either dict below and returns byte-identical frames with both of them emptied; the
# unit suite asserts that first, then asserts that the admitted axes and these registries PARTITION
# the measured census. THE DRIFT DIRECTION THAT MATTERS: admitting a member into a gate above
# WITHOUT deleting its line here is a test failure, so a widened gate can never leave a stale
# refusal standing behind it.
#
# There is no ``_ANY_CLASS``-style sentinel on these two axes: a statisticcat_desc and a
# commodity_desc are single flat strings with no sub-axis under them, so plain membership is the
# whole query and the sibling's ``_is_recorded_exclusion`` has no analogue here.
#
# WHAT THIS IS NOT: a plan to light the rows. C-2 PRICES row-lighting (a Glue additive migration,
# new card metrics, a producer wave on the F063 pattern) and deliberately does not execute it. A
# reason string says why a row is outside TODAY'S contract, never that the row is worthless.
_VALUE_AXIS_CENSUS_ARTIFACT = "data/dec_p0/nass_statcat_census.json"   # measured 2026-08-25

# The census cells the registries below are pinned against. They move only when the census is
# re-measured, and the population they describe must move in the same change.
_CENSUS_SOURCE_ROWS = 23_866_721
_CENSUS_ADMITTED_STAT_CAT_ROWS = 14_064_160
# STAT-CAT rows, not lane-kept rows (renamed from _CENSUS_PROGRESS_LANE_ROWS -- the Lane-6 review):
# this is the census tally of the two _PROGRESS_STAT_CATS strings across ALL commodities, but the
# crop-progress lane ANDs that gate with the 8-key _PROGRESS_COMMODITY_MAP (extract_usda_nass), so
# most of these rows die there anyway -- PASTURELAND's weekly CONDITION (417,400 residual NAT/STATE
# rows), HAY's cutting PROGRESS (333,534) and PEANUTS (115,795) among them, plus the 2,746
# REGION:SUB-STATE rows the silver lane's NATIONAL/STATE narrowing drops. The mapped-vs-unmapped
# split of this 1,348,989 is the ONE cell the census did not measure -- it rides as an open
# measurement item on the next census cut, and until then 8,453,572 below is a FLOOR on the
# never-enumerated mass, not the truth.
_CENSUS_PROGRESS_STAT_CAT_ROWS = 1_348_989
_CENSUS_ADMITTED_CAT_NATIONAL_STATE_ROWS = 1_946_206
_CENSUS_MAPPED_COMMODITY_ROWS = 842_068

# ---- THE VALUE AXIS (statisticcat_desc) ----------------------------------------------------
# 136 distinct statisticcat_desc in the source. ``_ANNUAL_STAT_CATS`` admits 4 of them
# (14,064,160 rows, 58.93%), leaving 9,802,561 rows (41.07%) on the 132 registered below.
# ``_PROGRESS_STAT_CATS`` admits 2 of those 132 BY STAT CAT (1,348,989 rows), so the honest
# NEVER-ENUMERATED figure is AT LEAST 8,453,572 rows on 130 cats (35.42%) -- a FLOOR, because the
# progress lane's commodity gate (_PROGRESS_COMMODITY_MAP, 8 keys) kills an unmeasured share of
# those 1,348,989 too; see _CENSUS_PROGRESS_STAT_CAT_ROWS above. C-2's plan text read the whole
# 41.07% as never enumerated; the correction is recorded here, in the file it is about, and the two
# crop-progress cats carry _TAKEN_BY_THE_PROGRESS_LANE rather than a refusal so the distinction
# cannot be lost.
#
# THE PRIZE, holding the commodity axis fixed (artifact, value_axis_prize_holding_commodity_fixed):
# on the 12 mapped commodities at NATIONAL/STATE, the cats below hold 2,386,755 rows against the
# 842,068 the annual lane keeps -- 2.8x, or 1.8x counting only cats no lane admits. The VALUE axis
# is the larger of the two gaps and the plan text scoped only the commodity one.
_TAKEN_BY_THE_PROGRESS_LANE = (
    "PARTIALLY taken, never 'NOT dark': _PROGRESS_STAT_CATS admits this cat by exact string, but "
    "the crop-progress lane ANDs it with the 8-key _PROGRESS_COMMODITY_MAP, so only the mapped "
    "grains' rows survive -- PASTURELAND condition, HAY cutting progress, PEANUTS and every other "
    "unmapped commodity's rows on this cat die at that same line, unrecorded (their split is the "
    "census's one unmeasured cell). Registered because it is outside the ANNUAL lane, and because "
    "the plan text counted the whole cat as never-enumerated"
)
_SALES_NOTE = (
    "the largest residual cat by a wide margin. SALES is a MARKETING measure -- quantity or value "
    "sold -- and is not the production it is routinely mistaken for; the two differ by on-farm "
    "use, seed and stock change, and a production row is PRODUCTION"
)
_PRICE_RECEIVED_NOTE = (
    "named by C-2 by construction. The farm-gate price axis: real, wanted, and refused HERE "
    "because this producer emits physical-balance columns only. Lighting it is a value column, a "
    "card metric and a producer -- priced by C-2, not executed by it"
)
_STOCKS_NOTE = (
    "named by C-2 by construction. A LEVEL, not a flow: stocks are dated by the quarterly stocks "
    "survey, not by the crop year this table keys on, so admitting them needs their own knowledge "
    "date as well as their own column -- the annual-summary release_date stamp would be wrong for "
    "every one of these rows"
)
_AREA_PLANTED_NET_NOTE = (
    "the one residual area cat that is a genuine ALTERNATE BASIS for an admitted column rather "
    "than a different measurement -- net planted area excludes failed and abandoned acres. It "
    "cannot share area_planted_ha: two values on one (slug, state, year, stat) key is exactly "
    "what the silver _validate_metric_uniqueness rejects. A column decision, not a map key"
)
_YIELD_MEDIAN_NOTE = (
    "median rather than mean yield -- a second YIELD value for the same key, which the silver "
    "uniqueness validator rejects. Its own column or nothing"
)
_GINNED_BALES_NOTE = (
    "cotton ginnings: a production measure on a DIFFERENT basis (running bales at the gin against "
    "PRODUCTION's 480 lb statistical bales) and on a different calendar. Two production numbers "
    "under one column is a collision, not coverage"
)
_ALT_AREA_BASIS = (
    "alternate area basis, neither AREA PLANTED nor AREA HARVESTED; filing it as either would put "
    "two values on one (slug, state, year, stat) key, which the silver uniqueness validator "
    "rejects"
)
_PRICE_AXIS = (
    "price axis -- a farm-gate price, index, parity or price-reaction cat. This producer carries "
    "physical balance only; the estate's price numbers come from the exchange and cash lanes"
)
_IN_SEASON_FIELD = (
    "in-season weekly field observation. The crop-progress lane is the home for this axis and it "
    "admits PROGRESS and CONDITION BY EXACT STRING, so every ', PREVIOUS YEAR' and ', 5 YEAR AVG' "
    "variant here is dark -- which is where the bulk of this family's rows sit"
)
_CROP_QUALITY = (
    "a quality, damage or grade measurement, not a balance-sheet quantity"
)
_DISPOSITION_AXIS = (
    "disposition or utilisation of a crop already produced (sold, fed, seeded, milled, crushed) -- "
    "a second balance-sheet axis this production-feature table does not carry"
)
_STOCKS_AXIS = (
    "a stocks or supplies LEVEL, on the same footing as STOCKS above and with the same "
    "survey-dated knowledge problem"
)
_INFRASTRUCTURE = (
    "processing or handling infrastructure -- capacity, gins, warehouses, operations, taps -- not "
    "a crop measure"
)

# Ordered by measured rows, descending: the mass reads first. Row counts are ALL AGG LEVELS, which
# is the level the bronze stat-cat gate acts at.
_RECORDED_STAT_CAT_EXCLUSIONS: dict[str, tuple[int, str]] = {
    "SALES": (2_969_384, _SALES_NOTE),
    "CONDITION": (949_032, _TAKEN_BY_THE_PROGRESS_LANE),
    "AREA BEARING & NON-BEARING": (609_299, _ALT_AREA_BASIS),
    "AREA IN PRODUCTION": (600_879, _ALT_AREA_BASIS),
    "PRICE RECEIVED": (599_327, _PRICE_RECEIVED_NOTE),
    "CONDITION, PREVIOUS YEAR": (514_079, _IN_SEASON_FIELD),
    "CONDITION, 5 YEAR AVG": (423_291, _IN_SEASON_FIELD),
    "PROGRESS": (399_957, _TAKEN_BY_THE_PROGRESS_LANE),
    "MOISTURE": (373_985, _IN_SEASON_FIELD),
    "PROGRESS, 5 YEAR AVG": (344_588, _IN_SEASON_FIELD),
    "AREA BEARING": (298_383, _ALT_AREA_BASIS),
    "STOCKS": (253_924, _STOCKS_NOTE),
    "AREA NON-BEARING": (252_546, _ALT_AREA_BASIS),
    "PROGRESS, PREVIOUS YEAR": (214_508, _IN_SEASON_FIELD),
    "MOISTURE, PREVIOUS YEAR": (172_396, _IN_SEASON_FIELD),
    "AREA PLANTED, NET": (171_964, _AREA_PLANTED_NET_NOTE),
    "AREA GROWN": (159_502, _ALT_AREA_BASIS),
    "CAPACITY": (79_540, _INFRASTRUCTURE),
    "GINNED BALES": (64_444, _GINNED_BALES_NOTE),
    "DAYS SUITABLE": (50_078, _IN_SEASON_FIELD),
    "SALES IN ORGANIC MARKETS": (32_419, _DISPOSITION_AXIS),
    "INVENTORY": (31_260, _STOCKS_AXIS),
    "WATER APPLIED": (26_837, _INFRASTRUCTURE),
    "DAYS SUITABLE, PREVIOUS YEAR": (21_351, _IN_SEASON_FIELD),
    "PRICE RECEIVED, PARITY": (19_551, _PRICE_AXIS),
    "AREA NOT HARVESTED": (18_378, _ALT_AREA_BASIS),
    "TAPS": (17_247, _INFRASTRUCTURE),
    "INDEX FOR PRICE RECEIVED, 1910 - 1914": (12_053, _PRICE_AXIS),
    "USAGE": (11_663, _DISPOSITION_AXIS),
    "SUCROSE": (9_983, _CROP_QUALITY),
    "SALES IN CONVENTIONAL MARKETS": (8_015, _DISPOSITION_AXIS),
    "OPERATIONS": (6_770, _INFRASTRUCTURE),
    "ACTIVE GINS": (6_674, _INFRASTRUCTURE),
    "INDEX FOR PRICE RECEIVED, 1990 - 1992": (5_023, _PRICE_AXIS),
    "FARM USE": (4_758, _DISPOSITION_AXIS),
    "DAMAGE": (4_693, _CROP_QUALITY),
    "INDEX FOR PRICE RECEIVED, 2011": (4_448, _PRICE_AXIS),
    "DAMAGE, PREVIOUS YEAR": (3_768, _CROP_QUALITY),
    "PRICE REACTION": (3_074, _PRICE_AXIS),
    "SAMPLES": (2_997, _CROP_QUALITY),
    "ACTIVITY": (2_730, _IN_SEASON_FIELD),
    "PRICE RECEIVED AFTER REPORT": (2_696, _PRICE_AXIS),
    "ACTIVITY, PREVIOUS YEAR": (2_452, _IN_SEASON_FIELD),
    "DAMAGE, 5 YEAR AVG": (2_440, _CROP_QUALITY),
    "AREA": (2_256, _ALT_AREA_BASIS),
    "REMOVAL FOR PROCESSING": (2_171, _DISPOSITION_AXIS),
    "DISAPPEARANCE": (1_827, _DISPOSITION_AXIS),
    "FACILITIES": (1_629, _INFRASTRUCTURE),
    "CRUSHED": (1_579, _DISPOSITION_AXIS),
    "PRICE RECEIVED, ADJUSTED BASE": (1_566, _PRICE_AXIS),
    "ACTIVITY, 5 YEAR AVG": (1_452, _IN_SEASON_FIELD),
    "POD COUNT": (1_389, _IN_SEASON_FIELD),
    "PLANT POPULATION": (1_366, _IN_SEASON_FIELD),
    "PRICE RECEIVED PRIOR TO CLOSING": (1_348, _PRICE_AXIS),
    "EAR COUNT": (1_328, _IN_SEASON_FIELD),
    "LOSS": (1_319, _CROP_QUALITY),
    "MILLING CAPACITY": (1_114, _INFRASTRUCTURE),
    "MILLED": (1_096, _DISPOSITION_AXIS),
    "HEIGHT, AVG": (968, _IN_SEASON_FIELD),
    "SHRINK": (818, _CROP_QUALITY),
    "DISTRIBUTION": (816, _STOCKS_AXIS),
    "WAREHOUSES": (782, _INFRASTRUCTURE),
    "PRICE REACTION, DECREASE": (752, _PRICE_AXIS),
    "PRICE REACTION, INCREASE": (752, _PRICE_AXIS),
    "SUPPLIES": (740, _STOCKS_AXIS),
    "NUT SET": (720, _IN_SEASON_FIELD),
    "HEIGHT, AVG, PREVIOUS YEAR": (695, _IN_SEASON_FIELD),
    "SUPPLIES, PREVIOUS YEAR": (638, _STOCKS_AXIS),
    "PRICE REACTION, NO CHANGE": (626, _PRICE_AXIS),
    "NUT SET, PREVIOUS YEAR": (593, _IN_SEASON_FIELD),
    "ROW WIDTH": (544, _IN_SEASON_FIELD),
    "HEAD COUNT": (528, _IN_SEASON_FIELD),
    "REMOVAL FOR PROCESSING, INEDIBLE USE": (483, _DISPOSITION_AXIS),
    "ACCESSIBILITY": (453, _IN_SEASON_FIELD),
    "PRICE RECEIVED, 10 YEAR AVG": (419, _PRICE_AXIS),
    "BOLL COUNT": (399, _IN_SEASON_FIELD),
    "SUPPLIES, 5 YEAR AVG": (387, _STOCKS_AXIS),
    "PRICE RECEIVED, 10 YEAR AVG FOR PARITY PURPOSES": (336, _PRICE_AXIS),
    "PRICE RECEIVED, MEDIAN": (332, _PRICE_AXIS),
    "NUT SET, 5 YEAR AVG": (321, _IN_SEASON_FIELD),
    "ACCESSIBILITY, PREVIOUS YEAR": (294, _IN_SEASON_FIELD),
    "AREA FILLED": (292, _ALT_AREA_BASIS),
    "REMOVAL FOR PROCESSING, EDIBLE USE": (275, _DISPOSITION_AXIS),
    "YIELD, MEDIAN": (268, _YIELD_MEDIAN_NOTE),
    "MOISTURE, 5 YEAR AVG": (266, _IN_SEASON_FIELD),
    "HEIGHT, AVG, 5 YEAR AVG": (220, _IN_SEASON_FIELD),
    "OTHER SALE": (216, _DISPOSITION_AXIS),
    "SEED FOR PLANTING": (216, _DISPOSITION_AXIS),
    "COVER": (215, _IN_SEASON_FIELD),
    "ACCESSIBILITY, 5 YEAR AVG": (204, _IN_SEASON_FIELD),
    "MILL SALE": (186, _DISPOSITION_AXIS),
    "AREA CERTIFIED": (171, _ALT_AREA_BASIS),
    "CAPTURED": (151, _DISPOSITION_AXIS),
    "END DATE, MAX": (151, _IN_SEASON_FIELD),
    "START DATE, MIN": (151, _IN_SEASON_FIELD),
    "END DATE, AVG": (141, _IN_SEASON_FIELD),
    "NET WEIGHT": (138, _CROP_QUALITY),
    "START DATE, AVG": (131, _IN_SEASON_FIELD),
    "RATIO": (130, _CROP_QUALITY),
    "PRICE RECEIVED, 3 YEAR AVG": (126, _PRICE_AXIS),
    "AREA GRAZED": (124, _ALT_AREA_BASIS),
    "AVAILABILITY": (120, _IN_SEASON_FIELD),
    "AVAILABILITY, 5 YEAR AVG": (114, _IN_SEASON_FIELD),
    "AVAILABILITY, PREVIOUS YEAR": (114, _IN_SEASON_FIELD),
    "PROCESSED IN LAB": (108, _CROP_QUALITY),
    "LENGTH OF SEASON, AVG": (107, _IN_SEASON_FIELD),
    "INFESTATION": (104, _IN_SEASON_FIELD),
    "MOVEMENT": (104, _IN_SEASON_FIELD),
    "MOVEMENT, PREVIOUS YEAR": (84, _IN_SEASON_FIELD),
    "MOVEMENT, 5 YEAR AVG": (76, _IN_SEASON_FIELD),
    "STOCKS, CURRENT YEAR": (73, _STOCKS_AXIS),
    "INFESTATION, PREVIOUS YEAR": (68, _IN_SEASON_FIELD),
    "HARVEST LOSS": (64, _CROP_QUALITY),
    "START DATE": (56, _IN_SEASON_FIELD),
    "COVER, PREVIOUS YEAR": (55, _IN_SEASON_FIELD),
    "STOCKS, PREVIOUS YEAR": (55, _STOCKS_AXIS),
    "AVERAGE PRICE": (52, _PRICE_AXIS),
    "RELATIVE WEIGHT": (45, _CROP_QUALITY),
    "START DATE, PREVIOUS YEAR": (41, _IN_SEASON_FIELD),
    "PRODUCTION NOT SOLD": (39, _DISPOSITION_AXIS),
    "AREA REMAINING TO BE PLANTED": (26, _ALT_AREA_BASIS),
    "START DATE, 5 YEAR AVG": (19, _IN_SEASON_FIELD),
    "AREA REMAINING TO BE HARVESTED": (12, _ALT_AREA_BASIS),
    "GROUP ITEM WEIGHT, MONTHLY": (6, _CROP_QUALITY),
    "TOTAL AREA": (6, _ALT_AREA_BASIS),
    "DEPTH, AVG": (5, _IN_SEASON_FIELD),
    "BLOOM DATE": (4, _IN_SEASON_FIELD),
    "AREA FLOODED": (3, _ALT_AREA_BASIS),
    "FRUIT SIZE": (3, _CROP_QUALITY),
    "DEPTH, AVG, PREVIOUS YEAR": (2, _IN_SEASON_FIELD),
    "FRUIT SIZE, 5 YEAR AVG": (1, _CROP_QUALITY),
    "FRUIT SIZE, PREVIOUS YEAR": (1, _CROP_QUALITY),
}

# ---- THE COMMODITY AXIS (commodity_desc) ---------------------------------------------------
# Measured INSIDE the admitted stat cats and at the NATIONAL/STATE levels the silver lane keeps
# (bronze_to_silver/usda_nass_annual.py:536 applies that narrowing; BRONZE applies no agg-level
# filter at all, so the physical bronze drop is LARGER THAN THIS REGISTRY BY 4.6x and its all-agg
# tally lives in the artifact: 14,064,160 admitted-cat rows split mapped 9,003,825 / unmapped
# 5,060,335 across every agg level, so the registry below documents 1,104,138 of a 5,060,335-row
# physical gate drop -- 21.8%. The remainder is county/district/zip/watershed mass this estate has
# never served and does not enumerate here; FORTY commodities (4,466 rows: YAMS 542, CASSAVA 541,
# TANIERS 259, DASHEENS 183, BITTERMELON 174, LEMONS & LIMES 168, COCONUTS 150, MANGOES 148, ...)
# carry admitted-cat rows at those sub-state levels ONLY and therefore have NO entry below at all
# -- named in the artifact's admitted_all_agg_by_commodity, absent here BY SCOPE, not by oversight.
# The NATIONAL/STATE count is the one enumerated because it is the only mass this estate
# could ever have served. Of 1,946,206 such rows the 12 ``_ANNUAL_COMMODITY_MAP`` keys ADMIT 842,068
# at this gate (43.27%; an UPPER BOUND on what the annual lane finally keeps -- silver drops further
# on _NON_FEATURE_UNITS and _filter_primary_rows, so the 2.8x value-axis prize ratio computed
# against it is itself a lower bound) and the 153 commodities below lose 1,104,138 (56.73%).
#
# TWO PLAN FIGURES ARE CORRECTED BY THE MEASUREMENT, which is the reason this registry is
# ENUMERATED rather than summarised:
#   * 1,123,488 dropped rows -> 1,104,138. The delta is EXACTLY SUGARBEETS, 19,350 rows: the plan
#     figure was inferred against the pre-fix map key "SUGAR BEETS" (with a space), which matched
#     nothing in the source. The source spelling has been the map key since the D-EC P0 class-lane
#     repair, so those rows are KEPT today and SUGARBEETS is deliberately absent below.
#   * 194 unmapped commodities -> 153. The plan computed 205 - 11 against the ALL-AGG-LEVEL
#     commodity count and applied the answer to a NATIONAL/STATE question. Measured: 205 distinct
#     commodities carry admitted-cat rows at some agg level, only 165 carry them at NATIONAL/STATE,
#     and all 12 map keys hit -- so 153 unmapped, and no map key is dead.
_FORAGE = (
    "forage and roughage -- consumed on the farm that grows it and never delivered against a "
    "contract. The feed layer the graph models is grain and meal (the coarse_grains and "
    "compound_feed context nodes), not hay"
)
_HORTICULTURE = (
    "fruit, vegetable or tree-nut horticulture: no futures contract and no context node anywhere "
    "in commodity_hierarchy.yaml, so a lit row would have nothing downstream to attach to"
)
_NASS_ROLLUP = (
    "a NASS ROLL-UP, not a commodity -- its rows are the sum of members counted elsewhere in this "
    "registry, so admitting it alongside them would double-count"
)
_PULSES_NODE = (
    "the `pulses` context node is the graph's home for this family and it has no numeric lane "
    "anywhere in the estate; a map key here would be the first one"
)
_MINOR_CEREAL_NODE = (
    "the `minor_cereals` context node is the graph's home for this family (declared as rye / oats "
    "/ millet / triticale / buckwheat) and it has no numeric lane anywhere in the estate"
)
_MINOR_OILSEED_NODE = (
    "the `minor_oilseeds` context node is the graph's home for this family and it has no numeric "
    "lane anywhere in the estate"
)
_CRUSH_PRODUCT = (
    "a PROCESSED product on the commodity axis, not a crop: the estate's meal, oil and mill "
    "numbers come from the crush and product contracts, and a QuickStats crop row would be a "
    "second unreconciled basis for them"
)
_CITRUS_LANE = (
    "citrus reaches the estate through the nass_citrus Florida forecast PDFs -- a DIFFERENT raw "
    "object with its own producer and its own silver table. Admitting the QuickStats rows here "
    "would open a second, unreconciled lane for the same node"
)
_NO_CONTRACT_NODE = (
    "no futures contract and no context node on this commodity; nothing downstream could address "
    "the rows"
)
_PEANUT_NODE = (
    "`peanut` is a DECLARED tier-1 context node (commodity_hierarchy.yaml context_commodities) "
    "carrying 7,975 dark propositions and NO numeric lane anywhere in the estate -- the largest "
    "single row-lighting candidate on this axis, priced by C-2 and not executed here"
)
_RAPESEED_NODE = (
    "`rapeseed` IS a contract node (french_rapeseed_matif), but US QuickStats rapeseed is 390 rows "
    "beside CANOLA's mapped 3,552 on the same crush chain, and NASS publishes them as two "
    "commodity_desc values -- one key cannot serve both without conflating Canadian canola with "
    "EU rapeseed"
)
_COFFEE_NODE = (
    "arabica_coffee and robusta_coffee are contract nodes, but the US is not a price-setting "
    "origin for either; the estate's coffee numbers come from the PSD and origin lanes "
    "(conab_coffee, fnc_colombia), and this domestic sliver would add a basis nothing cites"
)

# Ordered by measured rows, descending. Counts are admitted-stat-cat rows at NATIONAL + STATE.
_RECORDED_COMMODITY_EXCLUSIONS: dict[str, tuple[int, str]] = {
    "HAY": (217_825, _FORAGE),
    "POTATOES": (101_994, _HORTICULTURE),
    "BEANS": (96_915, _PULSES_NODE),
    "HAY & HAYLAGE": (88_265, _FORAGE),
    "TOBACCO": (65_499, _NO_CONTRACT_NODE),
    "SWEET CORN": (38_392, _HORTICULTURE),
    "TOMATOES": (34_444, _HORTICULTURE),
    "HAYLAGE": (30_810, _FORAGE),
    "PEAS": (30_131, _PULSES_NODE),
    "SWEET POTATOES": (28_042, _HORTICULTURE),
    "PEANUTS": (27_304, _PEANUT_NODE),
    "VEGETABLE TOTALS": (19_969, _NASS_ROLLUP),
    "RYE": (19_545, _MINOR_CEREAL_NODE),
    "MELONS": (13_917, _HORTICULTURE),
    "ONIONS": (12_808, _HORTICULTURE),
    "GRASSES & LEGUMES TOTALS": (12_534, _NASS_ROLLUP),
    "LETTUCE": (11_449, _HORTICULTURE),
    "CABBAGE": (9_898, _HORTICULTURE),
    "APPLES": (9_782, _HORTICULTURE),
    "PEPPERS": (9_244, _HORTICULTURE),
    "CUCUMBERS": (8_838, _HORTICULTURE),
    "SQUASH": (8_510, _HORTICULTURE),
    "ORANGES": (8_451, _CITRUS_LANE),
    "HOPS": (7_819, _NO_CONTRACT_NODE),
    "HEMP": (6_907, _NO_CONTRACT_NODE),
    "CARROTS": (6_572, _HORTICULTURE),
    "FIELD CROP TOTALS": (6_469, _NASS_ROLLUP),
    "FLAXSEED": (6_049, _MINOR_OILSEED_NODE),
    "CHICKPEAS": (5_208, _PULSES_NODE),
    "BLUEBERRIES": (4_933, _HORTICULTURE),
    "SPINACH": (4_882, _HORTICULTURE),
    "STRAWBERRIES": (4_828, _HORTICULTURE),
    "GREENS": (4_770, _HORTICULTURE),
    "PUMPKINS": (4_672, _HORTICULTURE),
    "HERBS": (4_309, _HORTICULTURE),
    "PEACHES": (4_250, _HORTICULTURE),
    "BROCCOLI": (4_247, _HORTICULTURE),
    "GRASSES": (4_217, _FORAGE),
    "MINT": (4_066, _NO_CONTRACT_NODE),
    "GRAPES": (3_925, _HORTICULTURE),
    "CAULIFLOWER": (3_881, _HORTICULTURE),
    "GRAPEFRUIT": (3_811, _CITRUS_LANE),
    "CHERRIES": (3_739, _HORTICULTURE),
    "ASPARAGUS": (3_702, _HORTICULTURE),
    "CUT CHRISTMAS TREES": (3_628, _NO_CONTRACT_NODE),
    "GARLIC": (3_482, _HORTICULTURE),
    "VEGETABLES, OTHER": (3_404, _NASS_ROLLUP),
    "LEGUMES": (3_030, _FORAGE),
    "CELERY": (2_790, _HORTICULTURE),
    "RASPBERRIES": (2_779, _HORTICULTURE),
    "POPCORN": (2_741, _NO_CONTRACT_NODE),
    "PEARS": (2_726, _HORTICULTURE),
    "MAPLE SYRUP": (2_711, _NO_CONTRACT_NODE),
    "SOD": (2_673, _FORAGE),
    "TANGERINES": (2_079, _CITRUS_LANE),
    "MILLET": (2_014, _MINOR_CEREAL_NODE),
    "LEMONS": (1_966, _CITRUS_LANE),
    "PECANS": (1_940, _HORTICULTURE),
    "SAFFLOWER": (1_937, _MINOR_OILSEED_NODE),
    "BLACKBERRIES": (1_892, _HORTICULTURE),
    "LENTILS": (1_744, _PULSES_NODE),
    "CROPS, OTHER": (1_730, _NASS_ROLLUP),
    "FIELD CROPS, OTHER": (1_697, _NASS_ROLLUP),
    "BERRY TOTALS": (1_552, _NASS_ROLLUP),
    "BEETS": (1_544, _HORTICULTURE),
    "OIL": (1_513, _CRUSH_PRODUCT),
    "ALCOHOL COPRODUCTS": (1_510, _CRUSH_PRODUCT),
    "EGGPLANT": (1_446, _HORTICULTURE),
    "CRANBERRIES": (1_445, _HORTICULTURE),
    "RADISHES": (1_260, _HORTICULTURE),
    "ARTICHOKES": (1_244, _HORTICULTURE),
    "SHORT TERM WOODY TREES": (1_211, _NO_CONTRACT_NODE),
    "TURNIPS": (1_184, _HORTICULTURE),
    "OKRA": (1_116, _HORTICULTURE),
    "SMALL GRAINS": (1_116, _NASS_ROLLUP),
    "BERRIES, OTHER": (1_055, _NASS_ROLLUP),
    "BUCKWHEAT": (1_045, _MINOR_CEREAL_NODE),
    "RHUBARB": (998, _HORTICULTURE),
    "BRUSSELS SPROUTS": (975, _HORTICULTURE),
    "TRITICALE": (968, _MINOR_CEREAL_NODE),
    "CROP TOTALS": (961, _NASS_ROLLUP),
    "PARSLEY": (958, _HORTICULTURE),
    "FRUIT TOTALS": (922, _NASS_ROLLUP),
    "FRUIT & TREE NUT TOTALS": (903, _NASS_ROLLUP),
    "COFFEE": (895, _COFFEE_NODE),
    "GINGER ROOT": (892, _HORTICULTURE),
    "AVOCADOS": (846, _HORTICULTURE),
    "GRASSES & LEGUMES, OTHER": (833, _NASS_ROLLUP),
    "PLUMS & PRUNES": (829, _HORTICULTURE),
    "APRICOTS": (815, _HORTICULTURE),
    "FRUIT, OTHER": (780, _NASS_ROLLUP),
    "CAKE & MEAL": (716, _CRUSH_PRODUCT),
    "HORSERADISH": (678, _HORTICULTURE),
    "ESCAROLE & ENDIVE": (649, _HORTICULTURE),
    "FIGS": (633, _HORTICULTURE),
    "DAIKON": (616, _HORTICULTURE),
    "TARO": (592, _HORTICULTURE),
    "DATES": (560, _HORTICULTURE),
    "MUSTARD": (544, _MINOR_OILSEED_NODE),
    "EMMER & SPELT": (540, _MINOR_CEREAL_NODE),
    "GINSENG": (503, _NO_CONTRACT_NODE),
    "NECTARINES": (492, _HORTICULTURE),
    "TREE NUTS, OTHER": (486, _NASS_ROLLUP),
    "OLIVES": (472, _HORTICULTURE),
    "CHICORY": (470, _HORTICULTURE),
    "PLUMS": (461, _HORTICULTURE),
    "ALMONDS": (454, _HORTICULTURE),
    "WATERCRESS": (450, _HORTICULTURE),
    "TREE NUT TOTALS": (445, _NASS_ROLLUP),
    "CITRUS TOTALS": (435, _NASS_ROLLUP),
    "FLOUR": (413, _CRUSH_PRODUCT),
    "WALNUTS": (413, _HORTICULTURE),
    "TANGELOS": (400, _CITRUS_LANE),
    "RAPESEED": (390, _RAPESEED_NODE),
    "FOOD CROP TOTALS": (388, _NASS_ROLLUP),
    "MUSHROOMS": (378, _HORTICULTURE),
    "PRUNES": (372, _HORTICULTURE),
    "HAZELNUTS": (357, _HORTICULTURE),
    "KIWIFRUIT": (356, _HORTICULTURE),
    "MILLFEED": (352, _CRUSH_PRODUCT),
    "PAPAYAS": (352, _HORTICULTURE),
    "BOYSENBERRIES": (308, _HORTICULTURE),
    "NON-CITRUS FRUIT & TREE NUTS TOTALS": (308, _NASS_ROLLUP),
    "FOOD CROP, OTHER": (292, _NASS_ROLLUP),
    "GOURDS": (264, _HORTICULTURE),
    "PISTACHIOS": (244, _HORTICULTURE),
    "WILD RICE": (204, _MINOR_CEREAL_NODE),
    "BANANAS": (202, _HORTICULTURE),
    "PARSNIPS": (200, _HORTICULTURE),
    "VEGETABLES, MIXED": (196, _NASS_ROLLUP),
    "MACADAMIAS": (168, _HORTICULTURE),
    "PEAS & LENTILS": (168, _PULSES_NODE),
    "SESAME": (148, _MINOR_OILSEED_NODE),
    "PINEAPPLES": (135, _HORTICULTURE),
    "CURRANTS": (128, _HORTICULTURE),
    "DILL": (128, _HORTICULTURE),
    "SWITCHGRASS": (127, _NO_CONTRACT_NODE),
    "GUAVAS": (112, _HORTICULTURE),
    "NON-CITRUS TOTALS": (112, _NASS_ROLLUP),
    "CAMELINA": (102, _MINOR_OILSEED_NODE),
    "LOGANBERRIES": (98, _HORTICULTURE),
    "JOJOBA": (90, _MINOR_OILSEED_NODE),
    "MISCANTHUS": (82, _NO_CONTRACT_NODE),
    "GRAIN": (81, _NASS_ROLLUP),
    "GUAR": (76, _MINOR_OILSEED_NODE),
    "MICROGREENS": (65, _HORTICULTURE),
    "CITRUS, OTHER": (51, _NASS_ROLLUP),
    "AMARANTH": (21, _MINOR_CEREAL_NODE),
    "LOTUS ROOT": (20, _HORTICULTURE),
    "PIMIENTOS": (18, _HORTICULTURE),
    "SWEET RICE": (10, _MINOR_CEREAL_NODE),
    "CRAMBE": (9, _MINOR_OILSEED_NODE),
    "CANEBERRIES": (3, _HORTICULTURE),
}

_CHUNKSIZE = 100_000


def _normalize_col(c: str) -> str:
    return c.strip().lower().replace(" ", "_").replace("%", "pct")


def extract_usda_nass(
    raw_source: "bytes | IO[bytes]",
    download_date: str,
) -> dict[str, pd.DataFrame]:
    """Stream-parse the NASS QuickStats .gz and return two series DataFrames.

    Args:
        raw_source:    Either raw bytes of the .gz file, or a file-like object
                       (e.g. a boto3 StreamingBody or an ``io.BytesIO``).
                       Passing a file-like avoids an in-memory copy of the
                       compressed file.
        download_date: Download date in ``YYYY-MM-DD`` format (metadata column).

    Returns:
        Dict with keys ``"annual"`` and ``"crop_progress"``, each mapping to
        a DataFrame.  Either value may be an empty DataFrame if no matching
        rows were found (unlikely with a valid NASS bulk file).
    """
    annual_frames: list[pd.DataFrame] = []
    progress_frames: list[pd.DataFrame] = []

    source: "bytes | IO[bytes]" = (
        io.BytesIO(raw_source) if isinstance(raw_source, bytes) else raw_source
    )

    reader = pd.read_csv(
        source,
        sep="\t",
        compression="gzip",
        low_memory=False,
        chunksize=_CHUNKSIZE,
        encoding="latin-1",
    )

    for chunk in reader:
        # Normalize column names
        chunk.columns = [_normalize_col(c) for c in chunk.columns]

        if "commodity_desc" not in chunk.columns or "statisticcat_desc" not in chunk.columns:
            logger.warning("NASS chunk missing expected columns — skipping")
            continue

        comm = chunk["commodity_desc"].astype(str).str.strip().str.upper()
        stat = chunk["statisticcat_desc"].astype(str).str.strip().str.upper()

        # Annual slice
        annual_mask = (
            comm.isin(_ANNUAL_COMMODITY_MAP)
            & stat.isin(_ANNUAL_STAT_CATS)
        )
        if annual_mask.any():
            sub = chunk.loc[annual_mask].copy()
            sub["leviathan_slug"] = comm[annual_mask].map(_ANNUAL_COMMODITY_MAP)
            keep = [_normalize_col(c) for c in _ANNUAL_KEEP_COLS if _normalize_col(c) in sub.columns]
            keep = ["leviathan_slug"] + [c for c in keep if c not in ("leviathan_slug",)]
            annual_frames.append(sub[keep])

        # Crop progress slice
        progress_mask = (
            comm.isin(_PROGRESS_COMMODITY_MAP)
            & stat.isin(_PROGRESS_STAT_CATS)
        )
        if progress_mask.any():
            sub = chunk.loc[progress_mask].copy()
            sub["leviathan_slug"] = comm[progress_mask].map(_PROGRESS_COMMODITY_MAP)
            keep = [_normalize_col(c) for c in _PROGRESS_KEEP_COLS if _normalize_col(c) in sub.columns]
            keep = ["leviathan_slug"] + [c for c in keep if c not in ("leviathan_slug",)]
            progress_frames.append(sub[keep])

    def _concat(frames: list[pd.DataFrame]) -> pd.DataFrame:
        if not frames:
            return pd.DataFrame()
        df = pd.concat(frames, ignore_index=True)
        if "value" in df.columns:
            df["value"] = pd.to_numeric(
                df["value"].astype(str).str.replace(",", "", regex=False),
                errors="coerce",
            )
        if "year" in df.columns:
            df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")
        if "county_code" in df.columns:
            # Chunked read_csv infers float64 for all-blank county chunks and
            # object for county-level chunks.  After concat the column holds
            # Python float NaN mixed with str values (e.g. '033').  Normalise
            # so PyArrow infers utf8 with nulls instead of trying DOUBLE.
            notna_mask = df["county_code"].notna()
            df["county_code"] = df["county_code"].astype(str).where(notna_mask, None)
        df["download_date"] = download_date
        df["source"] = "usda_nass"
        return df

    annual_df = _concat(annual_frames)
    progress_df = _concat(progress_frames)

    logger.info(
        "NASS extract complete  download=%s  annual_rows=%d  progress_rows=%d",
        download_date,
        len(annual_df),
        len(progress_df),
    )
    return {"annual": annual_df, "crop_progress": progress_df}
