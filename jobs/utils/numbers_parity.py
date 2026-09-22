"""The pg-mirror parity gate (BLOCKING for GRAPHRAG_NUMBERS_BACKEND=pg).

Runs a grid of registry (table, metric) x sample (commodity, asof) NumberQuery specs through BOTH backends
— the SAME build_sql() string executed on Athena and on the pg mirror — and diffs the rows (values +
knowledge/vintage dates). The flip to pg is allowed only on a clean report. ASCII-only stdout (cp1252
console rule); the full report also lands in data/graphrag/ + S3 when EVIDENCE_S3 is set.

SINCE 2026-09-22 IT ASKS TWO QUESTIONS, NOT ONE (pipeline census B1/P2). The grid proves
ARITHMETIC -- do the two backends compute the same answer -- and it asked only FIXED HISTORICAL
as-ofs, which is how it printed ``## verdict: 108/108 exact-match`` and PASSED on a mirror twelve
days stale. It now also proves CURRENCY: a TODAY as-of beside the three pinned ones (``run_asofs``)
and one bounded MAX(knowledge axis) per table, run on BOTH backends and diffed (``tip_sql`` /
``tip_mismatch``). The two verdicts print on SEPARATE lines so a reader can see which question was
answered.

Runs IN-VPC (needs both Athena and RDS): submit via
    python jobs/submit/submit_batch_load_numbers_pg.py --parity
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import date
from pathlib import Path

from leviathan.common.config import load_env
from leviathan.common.logging import get_logger

# Batch invokes this by PATH (`python jobs/utils/numbers_parity.py`), which puts jobs/utils/ -- not
# the repo root -- on sys.path[0], so `import jobs.*` would not resolve. Put the repo root on the
# path first (the silver_rebuild_gate precedent, jobs/audit/silver_rebuild_gate.py:58-61).
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# The pg MIRROR allowlist, imported so the two can never drift (same bind as silver_rebuild_gate).
# A SAMPLE_COMMODITY entry for a table the loader does not mirror has no pg side to compare against:
# `pgnumbers.pg_query` would raise "relation does not exist", `_cmp` records that as a MISMATCH (not
# a skip), and `main` returns 1 -- so ONE deferred table would turn the WHOLE parity gate red for
# every other table. See the SKIP-UNMIRRORED branch in the table loop.
from jobs.utils.load_pg_numbers import P1_TABLES as _PG_MIRROR_LIST  # noqa: E402

PG_MIRROR_TABLES = frozenset(_PG_MIRROR_LIST)

logger = get_logger("numbers_parity")

# Small representative grid: per table one liquid commodity + a historical and a recent as-of.
# COMMODITY VALUES MUST MATCH THE SILVER DATA (verified 2026-07-05 against S3/Athena): psd/production/esr
# store CONTRACT slugs (corn_cbot); wasde stores BASE names (corn). A wrong value makes that table's panel
# VACUOUS — 0 rows == 0 rows passes without proving anything.
SAMPLE_COMMODITY = {"silver_psd": "corn_cbot", "silver_wasde": "corn", "silver_production": "corn_cbot",
                    "silver_esr": "corn_cbot", "silver_fred_fx": None, "silver_noaa_oni": None,
                    # PRICE_OBSERVABILITY W3.3: pink_sheet has NO commodity col (the metric IS the
                    # series); the wide sampler takes the FIRST FOUR declared metrics, which the W2 card
                    # ordered to span price/fertilizer/energy/zscore exactly for this panel.
                    "silver_pink_sheet": None,
                    # gold_weather_z is a TALL z-table keyed by CONTRACT slug: the gold task's 'all'
                    # mode discovers commodities from silver/weather canonical partitions, which are the 31
                    # contract slugs (verified 2026-07-17: gold/weather_z/corn_cbot.parquet, commodity column
                    # == 'corn_cbot', 44,954 rows 1981-2026). The earlier 'corn' base-name sample made the
                    # panel vacuous the FIRST time the weather gate ran it live (weather-R3 red).
                    "gold_weather_z": "corn_cbot",
                    # NUMBERS-DEPTH WAVE (2026-07-19): the three newly-wired tables. ICCO is a
                    # single-commodity WORLD table (no commodity axis) -> None. MPOB carries a
                    # single-valued `commodity` column. SAGIS `commodity_col` is `crop`, a SAGIS crop
                    # code (NOT a contract slug) -- total_maize is the national headline maize crop
                    # (probed on S3); a wrong value makes the panel vacuous (0==0 passes blind).
                    "silver_icco_cocoa": None,
                    "silver_mpob": "malaysian_crude_palm_oil_cme",
                    "silver_sagis_cec": "total_maize",
                    # PRICE_OBSERVABILITY W4.2 (S3.F4): silver_cot's commodity_col is leviathan_slug, which
                    # holds CONTRACT slugs via _CODE_TO_SLUG (raw_to_bronze/cftc_cot.py; code-keyed since 2026-08-21) -- corn_cbot,
                    # NOT bare 'corn' (which matches zero rows = the gold_weather_z vacuous-panel trap; the
                    # EMPTY-PANEL guard would catch it loudly, but the RIGHT sample is corn_cbot).
                    "silver_cot": "corn_cbot",
                    # WIRING WAVE-1 (2026-07-23): silver_noaa_iod has NO commodity axis (global IOD state) ->
                    # None, like noaa_oni/fred_fx/pink_sheet; the wide sampler takes its 2 served metrics.
                    # silver_conab_coffee's commodity_col is `commodity` = arabica_coffee|robusta_coffee (NOT
                    # a contract slug); arabica_coffee is the headline variety (a wrong sample -> vacuous
                    # panel, caught loudly by EMPTY-PANEL). safra 2023+ only, so the 2021 asof legitimately
                    # sees 0 rows -- non-empty at the 2024/2026 asofs.
                    # WIRING WAVE-1 Card C (2026-07-24): silver_sagis_weekly_exports commodity_col is `crop`,
                    # a SAGIS crop LABEL (NOT a contract slug); values are maize | wheat (probed on S3). maize
                    # is the liquid, current subject -- wheat data stops at 2011, so the 2024/2026 asofs would
                    # see a stale row. A wrong sample makes the panel vacuous (caught loudly by EMPTY-PANEL).
                    "silver_noaa_iod": None,
                    "silver_conab_coffee": "arabica_coffee",
                    "silver_sagis_weekly_exports": "maize",
                    # SEAM C (futures v1.5-lite, whitelisted 2026-07-23): commodity_col is leviathan_slug
                    # holding continuous front-month CONTRACT slugs -- corn_cbot is the liquid probe. The card
                    # is levels-only, so the `series` grid legs SKIP (build_sql rejects non-latest) and the
                    # `latest` legs at each asof carry the panel; bare 'corn' would match zero rows.
                    "silver_futures_prices": "corn_cbot",
                    # T2B PATTERN RECORDS (2026-07-24): gold_pattern_records.commodity_col is `contract`
                    # (the focus contract slug). corn_cbot is the backfillable flagship pair (US corn
                    # export pace reads silver_esr_compact, a release-date-vintaged leg, so the bounded
                    # weekly backfill grid populates corn_cbot rows) -- the parity grid's latest/series
                    # legs on the numeric metric columns then compare non-empty on both backends. A wrong
                    # slug (bare 'corn') matches zero rows -> vacuous panel, caught loudly by EMPTY-PANEL.
                    # The grain is the full natural key (grain_cols), so the latest-vintage ROW_NUMBER never
                    # ties across driver/kind and pg==Athena selection is deterministic.
                    "gold_pattern_records": "corn_cbot",
                    # PRICE_AND_PLAYBOOKS W1.0 / D8: silver_futures_eod.commodity_col is leviathan_slug
                    # holding CONTRACT slugs -- corn_cbot is the liquid probe (bare 'corn' matches zero
                    # rows: the documented gold_weather_z vacuous-panel trap). The entry lands NOW, with
                    # the schema, because WITHOUT it the panel is vacuous the first time the gate runs
                    # live (0 == 0 passes blind). It is INERT while the table is whitelist-absent -- the
                    # loop below SKIPs a fenced table loudly instead of crashing -- and goes live the
                    # moment the W3 whitelist flip lands, so nobody has to remember to add it.
                    # NON-VACUITY PRECONDITION to re-check AT the flip: corn_cbot rows only exist after
                    # W2 (Databento GLBX root `ZC`); W1a/W1b produce CZCE rapeseed, JSE maize, CEPEA
                    # arabica/corn, Bursa palm and MIAX HRS -- none of them corn_cbot. The card declares
                    # grain_cols [leviathan_slug, contract_month, trade_date], so the latest-vintage
                    # ROW_NUMBER never ties across delivery months and pg==Athena selection stays
                    # deterministic (the gold_pattern_records lesson directly above).
                    "silver_futures_eod": "corn_cbot",
                    # PROJECTION WAVE Lane 3 / D-8 (2026-08-26, the flip's one open instrument item):
                    # silver_psd_attributes.commodity_col is leviathan_slug, filled from the SAME producer
                    # map silver_psd's `corn_cbot` sample comes from (usda_psd._PSD_COMMODITY_TO_SLUGS) --
                    # a base name ('soybeans') matches zero rows, the gold_weather_z vacuous-panel trap.
                    # WHY soybeans_cbot AND NOT corn_cbot, against the estate's own habit: corn lights
                    # ~2 more of the card's 20 declared metrics (Feed Dom. Consumption / FSI Consumption /
                    # Industrial Dom. Cons. are the grain-sheet lines) but carries NO `Crush` row at all --
                    # corn is not crushed -- and Crush is the attribute this table exists for (the card's
                    # first metric, "the estate's ONLY physical crush VOLUME"; 21 in-scope commodity codes,
                    # MY1960-2026, ONE unit, per the L2-0 census). A corn sample would leave the most
                    # load-bearing new metric of the Lane-3 flip uncompared at the pinned-cell grain below,
                    # and it would put the panel and the cell on two different slugs. soybeans_cbot still
                    # lights Crush, Domestic Consumption, Feed Waste Dom. Cons., Food Use Dom. Cons. and
                    # the TY trio, so the panel is nowhere near thin.
                    # R4: code 2222000 (Oilseed, Soybean) is declared HOMOGENEOUS in the producer's
                    # fan-out registry (_PSD_HOMOGENEOUS_FANOUT_CODES -- CBOT / DCE no.1 / DCE no.2 are
                    # interchangeable venues for one USDA sheet), so no attribute on this slug is an
                    # adjudicated subset and the sample can never sit on a manufactured or declined row.
                    # TALL, so the [:4] cap is lifted and ALL 20 declared metrics run. Most are EMPTY on
                    # any one slug BY CONSTRUCTION (Cows In Milk lives only on milk_fluid; the sugar and
                    # coffee splits only on their own slugs) -- not a defect: vacuity is checked per
                    # TABLE, not per metric.
                    # ORDER DETERMINISM on these country-less grid legs: with spec.country None `country`
                    # drops out of _total_order (the ESR S1 rule), so ~159 destination rows per
                    # (market_year, attribute) tie on every earlier term. That does NOT make the compare
                    # engine-arbitrary: the sort key's remaining terms are (period, metric, knowledge_date,
                    # unit, value) and _rows_key projects (value, knowledge_date), a function of that key
                    # alone -- so the only rows a tie can swap are indistinguishable to the compare. The
                    # strictly-ordered single-row proof is the CELL leg in main().
                    "silver_psd_attributes": "soybeans_cbot",
                    # NASS GATE RCA (2026-09-09) -- the two nass tables have been in
                    # load_pg_numbers.P1_TABLES all along (the mirror loads them), but NEITHER had a
                    # SAMPLE_COMMODITY entry, and both are PROJECTED on `commodity`
                    # (partition_cols [commodity, year]). With commodity None, query.py's
                    # "table {id} requires commodity (partition column)" raises for EVERY leg, _cmp
                    # books each as `- SKIP ... spec invalid` BEFORE the compare counter, so
                    # compared[tid] stays 0, the EMPTY-PANEL guard never sees the table, and the run
                    # returns 0. MEASURED OFFLINE 2026-09-09 through build_sql itself: 24 legs
                    # for nass_annual (4 metrics x 3 asofs x 2 aggs) and 24 for crop_progress -- both
                    # cards are WIDE, so main() caps the metric list at [:4] and crop_progress's fifth
                    # metric, `pct_harvested`, is never compared at all (the RCA's "30" multiplied the
                    # full roster and missed the cap; the uncompared fifth metric is DOCKETED, not
                    # widened here). 48 legs, all green by VACUITY, `## verdict: 0/0 exact-match`.
                    # This is the same class as the 2026-08-18 finding -- a fence whose input was
                    # never measured. PROVED OFFLINE (no Athena): with these samples
                    # build_sql returns real SQL for production_mt / yield_t_ha /
                    # pct_good_excellent at both `latest` and `series`. corn_cbot is the liquid slug
                    # present in BOTH cards' commodity_values (contract slugs, not base names -- the
                    # gold_weather_z weather-R3 trap).
                    "silver_nass_annual": "corn_cbot",
                    "silver_nass_crop_progress": "corn_cbot",
                    # USDA WAP GATE RCA (2026-09-15) -- the NEXT CHAPTER OF THE SAME RCA, and the
                    # first time the SPEC-INVALID-PANEL guard above caught one instead of letting
                    # it pass. silver_wap_table01_revisions is served AND mirrored (P1_TABLES since
                    # D-LD, 2026-08-18) but had no entry, and all THREE of its metrics carry
                    # `unit_overrides` -- value_mmt and prior_value_mmt are MMT for five groups and
                    # 'million 480-lb bales' for cotton, revision_mmt the same in change units --
                    # so query.py's DP-1 guard ("carries unit_overrides but the query has no
                    # commodity") raised on every commodity-less leg. MEASURED 2026-09-15 through
                    # the real build_sql: 18 of 18 raise with commodity=None, 18 of 18 compile with
                    # this sample. The gate FAILED on it three fires running (09-12/09-13/09-14,
                    # 'SPEC-INVALID-PANEL ... all 18 legs unbuildable' -> verdict FAIL), so the WAP
                    # canonical promote never ran and silver sat frozen at release_month 2026-07.
                    # NOT A SLUG CHOICE AT ALL, which is what makes this entry different from every
                    # one above it: commodity_col is `commodity` and it holds WAP AGGREGATE GROUPS,
                    # not contract slugs. The six values in the canonical object are EXACTLY the six
                    # the card declares -- coarse_grains, cotton, oilseeds, rice, total_grains,
                    # wheat (measured on silver/wap_table01_revisions/part-000.parquet, 96,410
                    # rows). There is no corn_cbot here, and a contract slug would match zero rows.
                    # WHEAT IS CHOSEN FOR MEANING, NOT AVAILABILITY. All six groups are non-vacuous
                    # at all three ASOFS, measured at the guard's own cutoffs (asof minus
                    # publication_lag_days 12) on the vintage_type='year' half: wheat 6,070 / 7,150
                    # / 7,978 rows, the thinnest group being cotton at 5,957 / 7,097 / 7,971. World
                    # wheat -- the card's own worked example -- carries 348 / 408 / 454 rows and a
                    # real revision at the newest release of each (2021-08: 763.6 against a prior
                    # 763.5; 2026-06: 844.4 against 843.8), so the panel compares the quantity this
                    # table EXISTS for rather than a group that merely happens to be populated.
                    # PERIOD STAYS FREE, and this is the trap worth naming: the card declares
                    # `period_required: true`, but that is enforced in agent._check_period_required,
                    # never in the compiler, so the grid legitimately compiles period-less SQL. A
                    # builder who "helpfully" pinned a marketing_year would emit
                    # `marketing_year = '2026/27'` under a `<= '2021-08-03'` guard -- two of three
                    # as-ofs returning zero rows, and an EMPTY leg is a MATCH on both backends that
                    # passes while proving nothing (the PSD_ATTR_VINTAGE_CELLS lesson verbatim).
                    # NULLS ARE SAFE HERE: prior_value_mmt and revision_mmt are NULL on 42 of 456
                    # world-wheat year rows and on BOTH marketing years at the 2024-05 release, so
                    # two `latest` legs compare a NULL -- legally, on both backends, because
                    # _total_order is all-ASC and Presto and Postgres both default NULLS LAST on
                    # ASC, and the `latest` arm's only DESC term is knowledge_date, which is never
                    # NULL.
                    # THE DEFERRAL HAS EXPIRED: load_pg_numbers.py's note ("choosing the
                    # commodity/as-of pair is worth doing against the first real mirror") was
                    # written before the mirror existed. It was hand-loaded 2026-09-10 13:29Z, and
                    # stage_pg_reload reloads this very table immediately BEFORE stage_parity on
                    # every Branch-A gate run -- so the futures_eod "sampled but unmirrored reds the
                    # whole gate" hazard is closed twice over here. That note in load_pg_numbers.py
                    # is now stale; it is another lane's file and is left alone, not edited.
                    "silver_wap_table01_revisions": "wheat",
                    # ---------------------------------------------------------------------------
                    # SAMPLER TOTALITY (2026-09-22, pipeline census B4/P4) -- THE REMAINING
                    # SEVENTEEN, LANDED IN ONE CHANGE BECAUSE THE CLASS IS THE DEFECT.
                    #
                    # This is the FOURTH sighting of one bug: silver_nass_annual /
                    # silver_nass_crop_progress (2026-09-09), silver_wap_table01_revisions
                    # (2026-09-15), and today silver_fgis and the three fnc tables -- each found by a
                    # RED GATE that had already blocked a canonical promote, each fixed by adding one
                    # dictionary row, each leaving the next table in the queue. Measured in this
                    # sitting: load_pg_numbers.P1_TABLES has 39 members and this dict had 22, so
                    # SEVENTEEN mirrored tables had no sampler entry and every one of them was one
                    # whitelist flip away from repeating the RCA. The entries below close the roster;
                    # `config_check.check_sampler_totality` (and its unit deck) closes the CLASS, so
                    # the 40th table fails in CI with its own name on it instead of at 12:00Z inside
                    # a gate that blocks a family's writes.
                    #
                    # NONE OF THESE IS A GUESS. Every one was proved NON-VACUOUS before it landed, by
                    # compiling the REAL build_sql and running it READ-ONLY on Athena at the three
                    # pinned as-ofs plus today (probe banked at scratchpad/pipeline_fix_0922/
                    # l1_sampler_probe.py + .json, run 2026-09-22). The per-entry row counts are
                    # quoted below. That discipline is the whole point: an entry matching ZERO rows
                    # does not fail, it PASSES VACUOUSLY -- 0 rows == 0 rows is an exact match -- and
                    # re-creates the gold_weather_z weather-R3 trap the EMPTY-PANEL guard exists to
                    # catch as a BACKSTOP, never as the test.
                    #
                    # THE COMMODITY-LESS ENTRIES ARE `None` AND THAT IS A DECLARATION, NOT A SKIP.
                    # Seven of the seventeen have NO commodity column at all (commodity_col is None on
                    # the card), so `None` is the only correct value -- the silver_pink_sheet /
                    # silver_fred_fx / silver_noaa_oni idiom. They are written out rather than left
                    # absent precisely so the totality lint can tell "declared commodity-less" from
                    # "nobody has looked at this table yet", which is the distinction whose ABSENCE
                    # cost four RCAs.
                    #
                    # gold_board_crush -- NO commodity column (a flat board-margin table; the card's
                    # commodity_values are the SUBJECTS it answers for, not an axis it filters on).
                    # Measured: 8 of 8 legs non-empty (latest=1, series=50 at every as-of including
                    # today). B3's table -- 33 days stale with no producer -- so this panel is also
                    # the instrument that will show the crush leg recovering.
                    "gold_board_crush": None,
                    # gold_futures_spreads -- commodity_col is `spread_id`, NOT a contract slug: the
                    # closed set is {kc_chi, white_yellow} (measured: 2,676 and 14 rows). kc_chi is
                    # the decade-deep leg and the only one with history at the 2021 as-of; a contract
                    # slug here would match zero rows. 8 of 8 legs non-empty.
                    "gold_futures_spreads": "kc_chi",
                    # silver_mpoc_stock_comparison -- commodity_col is `oil_type` and the card
                    # declares NO commodity_values, so the set was read from the data: palm_oil 89
                    # rows, soybean_oil 87, rapeseed_oil 49, sunflower_oil 47. palm_oil is the card's
                    # subject and the widest leg. HONEST PIT, NOT A DEFECT: the series itself begins
                    # after 2024-06, so the 2021 and 2024 as-ofs legitimately return 0 and only the
                    # 2026-07 and today legs carry rows (4 of 8) -- which is exactly why the today
                    # leg added below matters for this table. The same shape as silver_conab_coffee's
                    # documented 2021 miss.
                    "silver_mpoc_stock_comparison": "palm_oil",
                    # silver_fgis -- B4, and the reason this block is not four rows. commodity_col is
                    # `leviathan_slug` holding CONTRACT slugs; corn_cbot is the liquid probe and is in
                    # the card's declared commodity_values. 8 of 8 legs non-empty. The gate FAILED on
                    # 2026-09-17 and the canonical tip has sat at week_ending_date 2026-08-30 since.
                    "silver_fgis": "corn_cbot",
                    # silver_fnc_colombia_monthly -- commodity_col `commodity`, closed set
                    # {arabica_coffee}. 8 of 8 legs non-empty. B6's coffee card.
                    "silver_fnc_colombia_monthly": "arabica_coffee",
                    # silver_fnc_colombia_exports_port_type -- same closed set. 8 of 8 non-empty.
                    "silver_fnc_colombia_exports_port_type": "arabica_coffee",
                    # silver_fnc_colombia_area_department -- same closed set, and the ONE entry in
                    # this block that does NOT reach the "non-empty at 2 of the 3 pinned as-ofs" bar:
                    # 4 of 8 legs, non-empty at 2026-07-01 and today, EMPTY at 2021-08-15 and
                    # 2024-06-01. THAT IS A FINDING ABOUT THE TABLE, NOT ABOUT THE SAMPLE, and no
                    # sample can fix it: this card's knowledge axis is `ingest_date` under
                    # knowledge_semantics=ingest, and ingest_date carries a SINGLE value across the
                    # whole table (2026-06-02, measured by the 2026-09-22 refuter), so every as-of
                    # before that date is invisible to the guard by construction whatever commodity
                    # is asked for. The entry lands because it makes the panel non-vacuous TODAY
                    # (50 rows at both modern as-ofs) instead of leaving it unbuilt; the knowledge-axis
                    # repair (ingest_date -> year, the P12 descriptor half) belongs to whoever owns
                    # configs/graphrag/numbers/tables.yaml and is carried in this lane's still_open.
                    "silver_fnc_colombia_area_department": "arabica_coffee",
                    # silver_nass_citrus -- commodity_col is `crop`, a NASS CROP LABEL and never a
                    # contract slug (the loader's own entry says so in advance). all_orange is the
                    # headline crop. 8 of 8 legs non-empty (49-50 rows per leg).
                    "silver_nass_citrus": "all_orange",
                    # silver_mpoc_trade_stats_monthly -- NO commodity column. The loader's entry
                    # already called this STRUCTURAL rather than a deferral, and the `None` here is
                    # that sentence made machine-readable. 8 of 8 legs non-empty.
                    "silver_mpoc_trade_stats_monthly": None,
                    # silver_sagis_weekly_deliveries -- commodity_col is `crop`, a SAGIS crop LABEL:
                    # wheat 1,079 rows, maize 1,056, sunflower 446, soybeans 446. maize matches the
                    # exports sibling's sample, so the two SAGIS panels compare the same crop. 8 of 8
                    # non-empty. This is the LIVE half of the sagis family (tip 2026-09-11) beside
                    # B9's dead exports leg, so the pair is also the contrast the census needed.
                    "silver_sagis_weekly_deliveries": "maize",
                    # silver_ams_cotton_quality -- commodity_col `commodity`, closed set {cotton}.
                    # 8 of 8 legs non-empty (21/24/26/27 rows -- the row count IS the vintage count,
                    # which is why it rises with the as-of).
                    "silver_ams_cotton_quality": "cotton",
                    # silver_food_cpi -- NO commodity column (the axis is country_iso). 8 of 8
                    # non-empty.
                    "silver_food_cpi": None,
                    # silver_mpoc_exports_by_country -- NO commodity column (the axis is country).
                    # 8 of 8 non-empty.
                    "silver_mpoc_exports_by_country": None,
                    # The three UNICA cards -- NONE has a commodity column (season_history and
                    # monthly_ethanol_sales carry `region`; corn_ethanol carries neither). 8 of 8
                    # legs non-empty on all three. NOTE WHAT THESE PANELS WILL AND WILL NOT SAY: B5
                    # has the family frozen at fortnight_date 2026-02-01 with every weekly fire
                    # green, and a PARITY panel cannot see that -- parity proves Athena == pg, and a
                    # mirror of a frozen table is faithfully frozen. The instrument that CAN see it
                    # is the tip leg added below, and only once the canonical side moves; the fix
                    # itself is P13 and belongs to another lane.
                    "silver_unica_biweekly_season_history": None,
                    "silver_unica_corn_ethanol": None,
                    "silver_unica_monthly_ethanol_sales": None,
                    # silver_minagro_grain_exports -- commodity_col is `crop_slug`, an Argentine
                    # MINAGRO crop label: every slug carries exactly 12 rows (grains_pulses_total,
                    # wheat, barley, rye, corn, the four flour aggregates...), so availability cannot
                    # choose here and MEANING does: `corn` is the Argentine export-pace subject the
                    # card is served for. 6 of 8 legs non-empty -- empty at 2021-08-15 because the
                    # canonical object only carries as_of_date 2026 captures (max 2026-08-14), which
                    # is honest PIT and is also R6's measurement: 39 days against a 14-day ceiling.
                    "silver_minagro_grain_exports": "corn"}

# ---------------------------------------------------------------------------
# SAMPLER EXEMPTIONS -- the ONLY sanctioned way for a mirrored table to have no sampler entry.
#
# EMPTY TODAY, ON PURPOSE. Every one of load_pg_numbers.P1_TABLES's 39 members now has a
# SAMPLE_COMMODITY entry, so nothing is exempt. The mechanism exists anyway because the alternative
# -- a table that is simply ABSENT from both dicts -- is the silent skip that cost four RCAs, and
# `config_check.check_sampler_totality` must be able to tell a DECLARED refusal (with its reason on
# the record, readable by the next person) from an oversight. A future entry here is a sentence, not
# a flag: it names WHY this table cannot be sampled and what would have to change for it to be.
# The lint rejects an empty or whitespace reason, so an exemption can never be a silent one.
# ---------------------------------------------------------------------------
SAMPLER_EXEMPT: dict[str, str] = {
    # ONE entry, and finding it was the totality lint's first catch. gold_pattern_records is
    # MIRRORED, it has carried a SAMPLE_COMMODITY entry ('corn_cbot') since 2026-07-24 -- and its
    # card declares `metrics: {}` ON PURPOSE (configs/graphrag/numbers/tables.yaml:3007, "NO
    # `metrics` (deliberate): this is an AGGREGATION-only card"). So the grid loop below iterates an
    # EMPTY metric list, `compared[tid]` stays 0, neither the EMPTY-PANEL nor the SPEC-INVALID-PANEL
    # guard can see it, and this table's VALUE parity has been unproven for as long as it has been in
    # the mirror -- silently, while its entry read as coverage. It was not caught by the four earlier
    # RCAs because it does not FAIL: it compares nothing and returns 0.
    #
    # It is declared here rather than fixed because the fix is a CARD change (declaring the five
    # numeric metric columns as metrics), and the card's own comment argues against exactly that --
    # declaring them would make the F010 generator derive per-metric machinery this aggregation-only
    # ledger does not want. That is another lane's decision, so this lane RECORDS the hole instead of
    # widening a card to close it.
    #
    # WHAT STILL COVERS THE TABLE: the CURRENCY leg added below. tip_sql reads the card's knowledge
    # axis with no metric at all, so gold_pattern_records gains its FIRST cross-backend parity check
    # in this same change (canonical tip measured 2026-08-17 on Athena, 2026-09-22).
    #
    # AND THE WAIVER CANNOT ROT: config_check.check_sampler_totality clause 3 turns RED the day this
    # card declares metrics and the entry compiles, telling whoever lands that change to delete this
    # line. Nobody has to remember.
    "gold_pattern_records": "the card declares `metrics: {}` on purpose (an AGGREGATION-only ledger "
                            "card); there is no metric to grid, so no sample can make a value panel "
                            "non-vacuous. Retire this exemption when the card declares metrics.",
}

# 2026 asof included because ingest-semantics tables (silver_production) were ingested in 2026 — earlier
# asofs legitimately see 0 rows (honest PIT), which would leave that panel vacuous.
#
# THESE THREE ARE HISTORICAL AND PINNED, AND THEY STAY BYTE-IDENTICAL (threat model T4). Every leg
# this list produces returned exactly what it returns today before the 2026-09-22 currency change;
# the CURRENCY leg is additive and lives in `run_asofs` below, never by editing this list. A test
# pins the three strings for exactly that reason.
ASOFS = ["2021-08-15", "2024-06-01", "2026-07-01"]
AGGS = ["latest", "series"]


# ===========================================================================================
# CURRENCY (2026-09-22, pipeline census B1/P2) -- THE GATE LEARNS TO SEE A STALE MIRROR.
#
# THE DEFECT, MEASURED. At 2026-09-22T09:27Z this gate reported `## verdict: 108/108 exact-match`
# and PASSED, while the pg mirror it certifies had last been fully loaded on 2026-09-10 and was
# missing the ENTIRE September WASDE and PSD release (silver_psd: 247,294 mirrored rows against
# 251,475 canonical, release_date max 2026-09-11). It passed honestly: every leg asks one of three
# FIXED HISTORICAL as-ofs -- 2021-08-15, 2024-06-01, 2026-07-01 -- and a mirror twelve days behind
# answers all three exactly right. The gate proved ARITHMETIC and said nothing about VINTAGE, and
# because GRAPHRAG_NUMBERS_BACKEND=pg is the serving default, "nothing about vintage" is the whole
# question a reader grading the engine on merit is actually asking.
#
# TWO LEGS CLOSE IT, and they close different halves:
#   (a) run_asofs() -- a TODAY as-of beside the three pinned ones. This catches a mirror that is
#       stale in the rows a present-day question reads, on every metric of every card, through the
#       same _cmp path as everything else. It is ADDITIVE: ASOFS above is untouched, so the three
#       historical legs compile the byte-identical SQL and return the byte-identical rows they did
#       before this change (T4's byte-identical set).
#   (b) tip_sql() -- ONE bounded aggregate per table over the card's OWN knowledge axis, run on
#       BOTH backends and diffed. This is the leg that names the defect in one line instead of
#       leaving a reader to infer it from a grid: `TIP-STALE silver_psd: canonical 2026-09-11,
#       mirror 2026-08-12`. A today as-of alone would NOT reliably catch it -- a card whose newest
#       rows are older than its publication lag has an identical answer on both sides at any as-of,
#       and a wide card's [:4] metric cap means most columns are never asked at all.
#
# WHY A SECOND STATEMENT RATHER THAN REUSING THE GATE'S. jobs/audit/silver_rebuild_gate.py already
# builds `_tip_ym_sql` / `_tip_date_sql` over `_mirror_relation` -- but it runs them against the pg
# mirror ALONE, to ask "is the DATA current", and it is DARK (_DATA_FRESHNESS_BLOCKING = False).
# This leg asks the different question "do the TWO BACKENDS carry the same newest knowledge", and
# it cannot import from that module because that module imports THIS one (jobs/audit/
# silver_rebuild_gate.py:652 imports jobs.utils.numbers_parity inside stage_parity) -- a back-import
# would be circular. The shapes are deliberately kept aligned and the divergence is named here
# rather than discovered later.
#
# MEASURED COST, so nobody has to guess at it later (2026-09-22, offline compile + read-only Athena):
#   * the grid goes 657 -> 1,292 COMPILED legs. 39 tables instead of 22 and 4 as-ofs instead of 3;
#     spec-invalid legs go 3 -> 4. At ~3.0 s per Athena leg the FULL standalone run goes from about
#     33 to about 65 minutes, inside the loader jobdef's 7,200 s timeout with room to spare.
#   * the gate does NOT pay that: `stage_parity` pins PARITY_TABLES to ONE table, so a gate run grows
#     only by its own table's share.
#   * the 39 tip statements ran against the real Glue catalog in 117.6 s total, ~3.0 s each, worst
#     PLANNING time 2,430 ms. Planning time is the S3-LIST-storm signature (the Jul-2026 storm
#     planned for 26-31 s while scanning kilobytes), so the projected tables -- silver_esr_compact,
#     silver_fgis, the nass and fnc cards -- were the ones to watch and they are nowhere near it. No
#     bounding is needed; if a future card's tip ever plans slowly, THAT is the signal to bound it.
# ===========================================================================================

def today_asof() -> str:
    """The wall-clock as-of, as its own function so a deck can pin a date without pinning a day.

    The silver gate's `_freshness_clock` records what happens when a currency instrument reads a
    PINNED baseline instead of the clock: with the frozen `--asof 2026-02-15` default it published
    `months_behind = -6` and would have certified a 42-day-stale table as fresh. A currency leg's
    clock is the wall clock, and never a census baseline."""
    return date.today().isoformat()


def run_asofs(today: str | None = None) -> list[str]:
    """The as-ofs THIS RUN compares: the three pinned historical legs, plus today.

    Pure, so the composition is pinnable offline. `ASOFS` itself is never mutated -- a reader (or a
    test) can still see the three historical strings exactly as they have always been, which is the
    property T4's byte-identical set is stated in terms of."""
    return list(ASOFS) + [today or today_asof()]


# The one-day operational override the threat model asks for, and NOT a default.
#
# T4 says the tip leg "is first run in report-only mode for one full day so a wrong threshold cannot
# block a promote before it has been read". That is an OPERATIONAL step for the first run, so it is
# an explicit env opt-out -- `PARITY_TIP_REPORT_ONLY=1` -- and the DEFAULT IS BLOCKING, because a
# fence that defaults to advisory is fail-open and fail-open is the opposite of the doctrine: the
# 108/108 PASS above is exactly what an advisory currency instrument looks like after everyone has
# stopped reading it.
#
# THE BLAST RADIUS OF THE BLOCKING DEFAULT WAS MEASURED, NOT ASSUMED. The gate runs this module
# per-table through `stage_parity` with PARITY_TABLES pinned, and `stage_pg_reload` has ALREADY
# reloaded that table from the same canonical S3 objects Athena reads, immediately before -- so in a
# gate run the two tips are equal by construction and a RED here means the reload did not take,
# which is precisely a red worth having. The standalone full run is the one that goes red today,
# and it SHOULD: that is B1.
_TIP_REPORT_ONLY_ENV = "PARITY_TIP_REPORT_ONLY"


def tip_report_only() -> bool:
    return (os.environ.get(_TIP_REPORT_ONLY_ENV) or "").strip().lower() in {"1", "true", "yes", "on"}


def tip_sql(ts, *, db: str | None = None) -> str | None:
    """ONE bounded aggregate over the card's OWN knowledge axis, in a spelling both backends read.

    Returns None for a card that declares no knowledge axis at all -- which the caller reports as a
    named TIP-SKIP line, never as a silent pass.

    THE THREE THINGS THIS STATEMENT GETS RIGHT, each of them a recorded defect elsewhere:

      * SCHEMA-QUALIFIED. `leviathan_dev.<physical>`, from Q.ATHENA_DB, because the pg mirror does
        not put its tables on the default search_path -- load_pg_numbers creates every one as
        `"leviathan_dev"."<physical>"` and pgnumbers connects with an `options` string that replaces
        whatever the DSN carried. A bare relation raises UndefinedTable on pg only, which reads as a
        one-sided failure of the mirror rather than as a bug in the instrument (silver_rebuild_gate
        `_mirror_relation`, repaired 2026-09-11 for exactly this).

      * NORMALISED THROUGH THE COMPILER'S OWN EXPRESSION. `Q._dcmp` is what build_sql uses for every
        as-of predicate: a physical TIMESTAMP date column becomes `substr(CAST(col AS varchar),1,10)`
        and everything else `CAST(col AS varchar)`. That is not decoration, and it is MEASURED, not
        argued -- run read-only on Athena 2026-09-22, `SELECT MAX(date) FROM
        leviathan_dev.silver_pink_sheet` returns '2026-08-01 00:00:00.000' while the normalised form
        returns '2026-08-01', and the pg mirror stores str(datetime) as '2026-08-01 00:00:00'. A
        naive MAX() would therefore report a FALSE STALE on silver_pink_sheet, silver_futures_prices
        and silver_futures_eod on EVERY run, for ever (DP-5, PRICE_OBSERVABILITY W1.1) -- a fence
        that cries wolf daily is how a real red stops being read. Borrowing the
        compiler's expression rather than re-spelling it means the two can never drift apart; a test
        pins the emitted string so a rename fails in CI rather than at 12:00Z.

      * THE year_month CLASS IS READ, NOT SKIPPED. `knowledge_col()` returns None for a card guarded
        on `year*100+month` (silver_mpoc_stock_comparison, silver_mpoc_trade_stats_monthly), and a
        `if not col: skip` would have silently exempted them -- the same shape as the sampler holes
        this change closes. They get the year-month aggregate instead, which is the same statement
        the gate's own `_tip_ym_sql` builds.
    """
    from leviathan.graphrag.numbers import query as Q
    relation = f"{db or Q.ATHENA_DB}.{ts.athena_table or ts.id}"
    if getattr(ts, "knowledge_semantics", None) == "year_month":
        if not (ts.year_col and ts.month_col):
            return None
        return f"SELECT MAX(({ts.year_col} * 100) + {ts.month_col}) AS tip FROM {relation}"
    col = ts.knowledge_col()
    if not col:
        return None
    return f"SELECT MAX({Q._dcmp(ts, col)}) AS tip FROM {relation}"


def tip_value(rows) -> str:
    """The comparable projection of a tip statement's result: the single cell, normalised.

    `_norm_value` is reused deliberately -- a numeric year-month comes back as the string '202606'
    from Athena and as the int 202606 from psycopg, and the SAME normaliser that already makes the
    grid's values comparable makes these comparable too. A table that is empty on a backend yields
    '' (NULL and no-rows collapse to the same empty tip), so empty-on-both is a match and the grid's
    EMPTY-PANEL guard -- not this leg -- is what calls that out."""
    if not rows:
        return ""
    first = rows[0]
    v = first.get("tip") if isinstance(first, dict) else None
    if v is None and isinstance(first, dict) and first:
        v = next(iter(first.values()))
    return "" if v is None else _norm_value(v)


def tip_mismatch(tid: str, athena_rows, pg_rows) -> str | None:
    """The tip leg's VERDICT, as a pure function of the two backends' rows.

    Returns None when the mirror is at the canonical tip, or the mismatch sentence otherwise.
    Pure and offline on purpose: the decision this instrument makes is the one thing that must be
    pinnable without Athena and without a VPC, because the 2026-09-22 failure was not a wrong
    comparison -- it was a comparison nobody had asked for."""
    a, p = tip_value(athena_rows), tip_value(pg_rows)
    if a == p:
        return None
    return (f"TIP-STALE {tid}: canonical(athena)={a or 'empty'} mirror(pg)={p or 'empty'} - the pg "
            f"mirror is NOT carrying this table's newest knowledge, so a present-day question "
            f"gets an older vintage stamped honestly and the engine reads as stale; reload the "
            f"mirror (jobs/utils/load_pg_numbers.py) and re-run")

# PROJECTION WAVE Lane 3 / D-8: the silver_psd_attributes VINTAGE-FAN cell, as (market_year, asof) pairs.
# Module-level so the shape is pinnable offline (tests/unit/test_numbers_parity_prereq.py); the leg itself
# and the full argument for the cell live in main().
#
# THESE AS-OFS MUST BE RE-DERIVED AGAINST THE POST-CLOCK OBJECT BEFORE THE PROMOTE
# (lane E, 2026-09-04 -- runbook step R7b, and it is BLOCKING). The three pairs below were chosen
# from the RETIRED marketing-year rotation's arithmetic, which is gone: MY2010's vintages are no
# longer "2010-09-10 .. 2011-08-10 by construction", they are whatever releases actually touched
# that cell. MEASURED on the WIDE table over three banked bronze snapshots -- a DIRECTION with a
# named limit, not this leg's verdict, because the leg reads the LONG table -- the honest stamp for
# soybeans_cbot / United States / MY2010 is 2014-11-10, so the mid-fan as-of 2011-01-15 would have
# nothing to select. AN EMPTY LEG IS A MATCH ON BOTH BACKENDS: it PASSES while proving nothing, and
# the table-wide EMPTY-PANEL guard does not see it because these legs share the grid's tid. The
# NON-VACUITY PRECONDITION note in main() names the only real check -- the report's per-leg lines,
# read once. R7b runs the three legs against the SHADOW object, reads those lines, and re-derives
# these pairs so that (a) every leg returns rows and (b) the two modern legs still select DIFFERENT
# vintages; if no such pair of as-ofs exists on the honest axis for this cell, the CELL is re-chosen
# and the reason recorded, because "the vintage fan collapsed" is a finding about the table, not
# about the test.
PSD_ATTR_CELL_COMMODITY = "soybeans_cbot"
PSD_ATTR_CELL_COUNTRY = "United States"
PSD_ATTR_CELL_METRIC = "Crush"                       # byte-exact USDA label (L2-0 census); single unit
# R7b RE-DERIVED ON THE HONEST AXIS (2026-09-04, against the first canonical object; banked in
# tests/fixtures/psd/vintage_cell_20260904.json). The retired pairs read EMPTY on two of three legs --
# MY1998 @2001-06-30 and MY2010 @2011-01-15 both return 0 rows because a bulk-union table carries each
# cell's LATEST print, known 2014-04-09 / 2014-11-10 -- and an empty leg matches vacuously. The honest
# fan for this cell lives in 2026: MY2023's Crush was touched on 2026-04-09 and again on 2026-07-10.
PSD_ATTR_VINTAGE_CELLS = [("1998", "2026-07-01"),    # the month_code-0 era's latest print (known 2014-04-09) -> 1 row
                          ("2023", "2026-05-01"),    # INSIDE MY2023's honest fan -> the 2026-04-09 vintage wins
                          ("2023", "2026-08-01")]    # past the whole fan -> the 2026-07-10 vintage (a DIFFERENT row)


# ---------------------------------------------------------------------------
# The WIDE metric cap (NASS GATE RCA docket, 2026-09-09).
# ---------------------------------------------------------------------------
WIDE_METRIC_CAP = 4        # the representative sample a card too wide to compare in full gets
FULL_METRIC_MAX = 8        # ...and the width at or below which a wide card is compared IN FULL


def metric_plan(shape: str, metrics) -> tuple[list[str], list[str]]:
    """Which of a card's declared metrics this run compares, and which it does NOT. Pure.

    THE DEFECT THIS REPLACES, measured. ``main`` used to write
    ``list(ts.metrics) if ts.shape == "tall" else list(ts.metrics)[:4]``: a TALL card's metrics are
    row VALUES so all of them run, and a WIDE card was sampled at its first four on the argument
    that "metrics == columns, cheap, representative at 4". The cap was SILENT, and it silently
    dropped ``silver_nass_crop_progress``'s fifth metric ``pct_harvested`` -- the D-SG G1-5
    calendar-structural column, the one with its OWN season floor in the registry
    (``min_nonnull_frac_season_overrides``), i.e. the single column on that card whose behaviour
    anyone had bothered to calibrate. It was never compared on either backend, on any as-of, in any
    run. Same 2026-08-18 class as the rest of this RCA: a fence whose input was never measured.

    THE RULE, and why it is not simply "lift the cap". Lifting it ESTATE-WIDE was measured offline
    against the real registry (2026-09-09): the grid goes 582 -> 1,254 legs, +672 (+115%), and 630
    of those 672 come from three sampler-shaped cards -- silver_pink_sheet (76 metrics, +432),
    silver_fred_fx (28, +144) and silver_psd (13, +54). pink_sheet's first four are ORDERED for this
    panel on purpose (the W2 card spans price / fertilizer / energy / zscore), so comparing all 76
    would more than double a blocking in-VPC gate's runtime to re-prove a deliberate design. So the
    rule is by WIDTH: a wide card declaring <= FULL_METRIC_MAX metrics is compared IN FULL, a wider
    one keeps the representative sample. MEASURED COST of that rule: +42 legs (582 -> 624, +7.2%) --
    silver_cot 8 metrics (+24), and silver_noaa_oni / silver_mpob / silver_nass_crop_progress 5 each
    (+6 apiece). At ~10 MB minimum Athena billing that is under a cent and roughly two minutes.

    AND THE CAP STOPS BEING SILENT EITHER WAY: whatever it drops is RETURNED, so ``main`` prints it
    as a report line naming the uncompared metrics. The day a card grows past the width the reader
    sees which metrics stopped being proved, instead of finding out three Tuesdays later."""
    ms = list(metrics)
    if shape == "tall" or len(ms) <= FULL_METRIC_MAX:
        return ms, []
    return ms[:WIDE_METRIC_CAP], ms[WIDE_METRIC_CAP:]


def _norm_value(v) -> str:
    """Rendering-insensitive value key: Athena prints large doubles in Java E-notation ('1.5461095E7'),
    psycopg prints plain decimal ('15461095.0') — the same float. Compare floats as canonical repr;
    non-numeric strings (dates, '', text) compare verbatim."""
    s = str(v)
    try:
        return repr(float(s))
    except (TypeError, ValueError):
        return s


def _rows_key(rows: list[dict], limit: int = 5) -> list[tuple]:
    """Comparable projection: (value, knowledge_date/data_date) of the first rows."""
    out = []
    for r in rows[:limit]:
        out.append((_norm_value(r.get("value")), str(r.get("knowledge_date") or r.get("data_date") or "")))
    return out


_SUM_REL_TOL = 1e-5


def _sum_tolerant_eq(a: list[tuple], p: list[tuple]) -> bool:
    """Float32-accumulation tolerance for ``agg=sum`` legs ONLY (WIRING-W1 parity fold).

    Both backends sum a float32 column (Glue ``float`` -> pg ``real``) in engine-chosen row
    order, so a cross-engine sum can legitimately differ in the ~1e-7-relative range
    (observed 2026-07-23: ESR China corn 69140.06 athena vs 69140.08 pg). Exact equality
    stays the bar for every other leg; a sum leg passes when the date parts are identical
    and each value pair is within ``_SUM_REL_TOL`` relative. Row-set divergence still
    fails: a missing/extra row shifts the sum far beyond tolerance or changes the length.
    """
    if len(a) != len(p):
        return False
    for (av, ad), (pv, pd) in zip(a, p):
        if ad != pd:
            return False
        if av == pv:
            continue
        try:
            fa, fp = float(av), float(pv)
        except (TypeError, ValueError):
            return False
        if abs(fa - fp) > _SUM_REL_TOL * max(1.0, abs(fa), abs(fp)):
            return False
    return True


def vacuity_mismatches(compared: dict[str, int], nonempty: dict[str, int],
                       spec_invalid: dict[str, int]) -> list[str]:
    """The two ways a panel can be GREEN WHILE PROVING NOTHING. Pure + offline so the guards are
    pinnable without Athena or a pg mirror (they are the only thing standing between a broken
    instrument and a passing gate).

    EMPTY-PANEL: every compared query returned 0 rows on BOTH backends (wrong sample commodity,
    empty mirror table). 0 rows == 0 rows is an exact match, so without this the flip passes blind.

    SPEC-INVALID-PANEL (NASS GATE RCA, 2026-09-09) -- the hole BEHIND that guard. A spec-invalid SKIP
    is recorded BEFORE the compare counter increments, so a table whose EVERY leg is unbuildable
    never enters the EMPTY-PANEL loop at all: `mismatches` stays empty, main() returns 0, and the
    report reads `## verdict: 0/0 exact-match`. That is exactly how BOTH usda_nass tables sat green
    for as long as they have been wired -- no SAMPLE_COMMODITY entry, so query.py raised "table
    {id} requires commodity (partition column)" on all 24 + 24 legs. The hole is ESTATE-WIDE, not a
    nass one: any table whose spec cannot be built (a missing sample, a renamed partition column, a
    region rule that no longer admits the grid) passes the same way, which is the 2026-08-18 class
    -- a fence whose input was never measured. A skip that is a PROPERTY OF THE SPEC is a broken
    instrument, so it blocks the flip like a mismatch does.

    It fires ONLY when nothing in that table compared: a table with a few legitimately-unbuildable
    legs beside real compares is untouched, and the SKIP-FENCED / SKIP-UNMIRRORED branches
    (deliberate, loud, and about a table nobody serves) never reach here."""
    out: list[str] = []
    for tid, n in compared.items():
        if n > 0 and nonempty.get(tid, 0) == 0:
            out.append(f"EMPTY-PANEL {tid}: all {n} compared queries returned 0 rows on both "
                       "backends - vacuous, check SAMPLE_COMMODITY / mirror load")
    for tid, n in spec_invalid.items():
        if n > 0 and compared.get(tid, 0) == 0:
            out.append(f"SPEC-INVALID-PANEL {tid}: all {n} legs unbuildable (spec invalid) - "
                       "nothing was compared, so this panel proves nothing; check "
                       "SAMPLE_COMMODITY / the card's partition + region rules")
    return out


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    load_env()
    from leviathan.graphrag.numbers import pgnumbers
    from leviathan.graphrag.numbers import query as Q
    from leviathan.graphrag.numbers.registry import load_registry

    if not os.environ.get("EVIDENCE_PG_DSN"):
        raise SystemExit("EVIDENCE_PG_DSN not set (run in-VPC)")
    athena = Q.athena_query_fn()
    reg = load_registry()
    tables = [t.strip() for t in
              (os.environ.get("PARITY_TABLES") or ",".join(SAMPLE_COMMODITY)).split(",") if t.strip()]

    # ONE clock for the whole run: run_asofs() is called ONCE here, never per table. A run that
    # crosses midnight must compare every table at the SAME today, or two tables' "current" legs
    # silently ask different questions and the report cannot be reproduced from its own header.
    asofs = run_asofs()
    tip_only = tip_report_only()

    total = match = 0
    tip_total = tip_match = 0
    tip_advisories: list[str] = []                    # tip diffs when the one-day override is lit
    mismatches: list[str] = []
    nonempty: dict[str, int] = {}                     # per-table compared queries with actual rows
    compared: dict[str, int] = {}
    spec_invalid: dict[str, int] = {}                 # per-table legs whose spec would not BUILD
    lines = [f"# numbers pg-parity report ({date.today().isoformat()})", "",
             f"as-ofs: {asofs} (the last is the CURRENCY leg; the first three are pinned history)",
             f"tip leg: {'REPORT-ONLY (PARITY_TIP_REPORT_ONLY lit)' if tip_only else 'BLOCKING'}", ""]
    def _cmp(spec, tid, metric, asof, agg):
        """One spec -> compare Athena vs the pg mirror (the SAME build_sql string on both) and tally into
        the enclosing report state. Reused verbatim by the (table,metric,asof,agg) grid AND the ESR
        destination leg (ESR_DESTINATION_PLAN 5.2), so both run identical compare logic."""
        nonlocal total, match
        try:
            sql = Q.build_sql(spec)
        except Exception as e:  # noqa: BLE001 — spec not valid for this table (e.g. region rules)
            lines.append(f"- SKIP {tid}.{metric} asof={asof} agg={agg}: spec invalid ({e})")
            spec_invalid[tid] = spec_invalid.get(tid, 0) + 1
            return
        total += 1
        try:
            a = _rows_key(athena(sql))
        except Exception as e:  # noqa: BLE001
            lines.append(f"- ATHENA-ERR {tid}.{metric} asof={asof} agg={agg}: {str(e)[:120]}")
            return
        try:
            p = _rows_key(pgnumbers.pg_query(sql))
        except Exception as e:  # noqa: BLE001
            mismatches.append(f"PG-ERR {tid}.{metric} asof={asof} agg={agg}: {str(e)[:120]}")
            return
        compared[tid] = compared.get(tid, 0) + 1
        if a or p:
            nonempty[tid] = nonempty.get(tid, 0) + 1
        if a == p:
            match += 1
        elif agg == "sum" and _sum_tolerant_eq(a, p):
            match += 1
            lines.append(f"- TOL {tid}.{metric} asof={asof} agg=sum: float32-accumulation delta "
                         f"within {_SUM_REL_TOL:g} rel (athena={a} pg={p})")
        else:
            mismatches.append(f"DIFF {tid}.{metric} asof={asof} agg={agg}: athena={a} pg={p}")

    def _cmp_tip(ts, tid):
        """The CURRENCY leg: is the mirror carrying the same newest knowledge as canonical?

        Tallied into its OWN counters and NEVER into `compared`/`nonempty`. That separation is
        load-bearing, not tidiness: a non-empty tip would otherwise satisfy the EMPTY-PANEL guard
        for a table whose entire metric grid is vacuous, and this change would have WEAKENED the
        one guard standing between a broken sampler and a passing gate while appearing to add an
        instrument. The tip leg proves vintage; the grid proves values; neither covers for the
        other."""
        nonlocal tip_total, tip_match
        sql = tip_sql(ts)
        if sql is None:
            lines.append(f"- TIP-SKIP {tid}: the card declares no knowledge axis (no knowledge_col "
                         f"and no year/month pair) - currency is unmeasurable for this table, which "
                         f"is a fact about the CARD; it is named here rather than passed silently")
            return
        tip_total += 1
        try:
            a_rows = athena(sql)
        except Exception as e:  # noqa: BLE001
            # 2026-09-22 review MAJOR-3: fail CLOSED, symmetric with the pg side below. An unreadable
            # canonical tip is a MISMATCH the exit code carries, never a line above a PASS verdict.
            mismatches.append(f"TIP-ATHENA-ERR {tid}: {str(e)[:140]}")
            return
        try:
            p_rows = pgnumbers.pg_query(sql)
        except Exception as e:  # noqa: BLE001
            mismatches.append(f"TIP-PG-ERR {tid}: {str(e)[:140]}")
            return
        msg = tip_mismatch(tid, a_rows, p_rows)
        if msg is None:
            tip_match += 1
            lines.append(f"- TIP {tid}: mirror at canonical tip "
                         f"({tip_value(a_rows) or 'empty on both'})")
            return
        if tip_only:
            tip_advisories.append(msg)
            lines.append(f"- TIP-ADVISORY {msg}")
        else:
            mismatches.append(msg)

    for tid in tables:
        # A table can be REGISTERED in tables.yaml yet FENCED out of the loaded registry
        # (registry.WHITELIST_ABSENT_DEFAULT, or the GRAPHRAG_NUMBERS_DISABLE env kill-switch), which
        # is precisely the state a freshly-schema'd table sits in before its producers land
        # (silver_futures_eod, PRICE_AND_PLAYBOOKS W1.0). `reg.get` raises KeyError on those, and this
        # loop is unguarded -- one fenced SAMPLE_COMMODITY entry would crash the WHOLE parity gate for
        # every other table. Skip it LOUDLY (a report line, not a mismatch): a fenced table is not
        # served, so there is nothing to prove parity about, and the entry activates by itself the
        # moment the fence lifts. It is NOT counted as a mismatch -- that would block the pg flip
        # forever on a table nobody is serving.
        if tid not in reg.tables:
            lines.append(f"- SKIP-FENCED {tid}: registered in tables.yaml but absent from the loaded "
                         f"registry (whitelist-absent / GRAPHRAG_NUMBERS_DISABLE) - not served, "
                         f"nothing to compare; this entry goes live at the whitelist flip")
            continue
        # ...and the SEQUENCING guard behind it. Lifting the fence is a ONE-LINE registry edit; adding
        # the table to load_pg_numbers.P1_TABLES is a separate, deliberate decision gated on a measured
        # size check (silver_futures_eod / D7, silver_nasa_power before it). If the fence lifts first,
        # every leg for this table hits a pg relation that was never created, `_cmp` books each miss as
        # a PG-ERR MISMATCH, and main() returns 1 -- the whole gate red because of one unmirrored table.
        # Skip it LOUDLY instead: unmirrored means there is no pg side to be at parity WITH.
        if tid not in PG_MIRROR_TABLES:
            lines.append(f"- SKIP-UNMIRRORED {tid}: served, but absent from load_pg_numbers.P1_TABLES "
                         f"- there is no pg mirror to compare against (the D7-class size-check "
                         f"deferral); add it to P1_TABLES and reload the mirror to activate this entry")
            continue
        ts = reg.get(tid)
        commodity = SAMPLE_COMMODITY.get(tid)
        # Which metrics this run compares, and which the width cap drops -- see metric_plan for the
        # rule, the measured cost of every alternative, and the pct_harvested defect it closes. A
        # dropped metric is NAMED in the report: a cap nobody can see is how the D-SG G1-5 floor
        # column went unproved for as long as this gate has existed.
        metric_list, uncompared = metric_plan(ts.shape, ts.metrics)
        if uncompared:
            lines.append(f"- METRIC-CAP {tid}: comparing {len(metric_list)} of "
                         f"{len(metric_list) + len(uncompared)} declared metrics (wide card past "
                         f"the {FULL_METRIC_MAX}-metric full-compare width); NOT compared: "
                         f"{uncompared}")
        for metric in metric_list:
            for asof in asofs:
                for agg in AGGS:
                    _cmp(Q.NumberQuery(table=tid, metric=metric, asof=asof, commodity=commodity,
                                       agg=agg, limit=50), tid, metric, asof, agg)
        # ...and the currency leg, AFTER the two skip fences above, so a fenced or unmirrored table
        # never reaches a registry that raises or a pg relation that was never created. (The ESR and
        # psd_attributes blocks below sit OUTSIDE this loop and therefore outside those fences --
        # named in their own comments, and the reason the tip leg is placed INSIDE.)
        _cmp_tip(ts, tid)

    # ESR_DESTINATION_PLAN 5.2: destination-scoped parity leg -- the concrete cross-backend proof that the
    # smallint (Athena) / TEXT (pg) country_code compares IDENTICALLY under CAST(country_code AS varchar)
    # IN (...). corn_cbot + country='China' (FAS 5700), agg=sum (MY total) and agg=latest (freshest week).
    # Empty-on-both is a match (not a mismatch); only a genuine athena!=pg divergence flags -- exactly the
    # smallint/TEXT trap needing runtime proof (the offline unit test only proves the SQL STRING is emitted).
    if "silver_esr" in tables:
        for asof in asofs:
            for agg in ("sum", "latest"):
                _cmp(Q.NumberQuery(table="silver_esr", metric="weekly_exports_1000mt", asof=asof,
                                   commodity="corn_cbot", country="China", agg=agg, limit=50),
                     "silver_esr", "weekly_exports_1000mt[China]", asof, agg)
    # PROJECTION WAVE Lane 3 / D-8: the silver_psd_attributes VINTAGE-FAN cell -- the concrete proof that
    # this card's as-of collapse picks the SAME vintage on both backends at BOTH ends of the fan. The card
    # declares NO grain_cols on purpose, so build_sql's latest-vintage ROW_NUMBER partitions by the tall
    # fallback (leviathan_slug, country, market_year, attribute) and orders release_date DESC; that
    # ROW_NUMBER *is* the as-of machinery here, and it is the one piece of this table nothing else proves.
    #
    # WHY THIS CELL IS BYTE-STABLE -- the whole reason a cell leg exists beside the grid:
    #   * SINGLE UNIT. Crush prints '(1000 MT)' and nothing else (L2-0 census, units: ["(1000 MT)"]), so no
    #     row of this cell is a different quantity from its neighbour. `Domestic Consumption` -- the
    #     obvious alternative at 44 codes -- is the ONE multi-unit metric on the card ((1000 MT) /
    #     (1000 MT CWE) / (1000 60 KG BAGS) / (MT)) and is deliberately NOT the cell metric.
    #   * NO R4 AMBIGUITY. 2222000 is a HOMOGENEOUS (venue-only) fan-out, so soybeans_cbot carries the
    #     soybean sheet's Crush unchanged; the two adjudicated codes (coffee 711100, sugar 612000) and
    #     their subset-specific attributes are nowhere near this cell.
    #   * A STRICT TOTAL ORDER, so no row is engine-arbitrary. commodity + country + metric + period are
    #     ALL pinned and _rn = 1 leaves exactly ONE row per market_year, so `ORDER BY period, country,
    #     metric, knowledge_date, unit, value` is already unique on its first term and the LIMIT keeps a
    #     deterministic row on Athena and on pg alike.
    #   * NO TIE INSIDE THE ROW_NUMBER either -- the failure that needed a vintage_tiebreak on
    #     silver_wasde, and this card declares none. RE-AUTHORED 2026-09-04 (lane E): this bullet used
    #     to say release_date is a FUNCTION of (market_year, wasde_release_month) because
    #     usda_psd._compute_psd_release_dates emitted '<cal_year>-<cal_month>-10', injective in
    #     month_code at a fixed market year. That formula is DELETED. release_date is now the row's own
    #     (Calendar_Year, Month) stamp resolved to the registered WASDE day of that calendar month
    #     (month-END for the eight World Markets and Trade sheets, or for a month silver_wasde does not
    #     carry), and '<market_year>-01-01' for month_code 0. The no-tie property SURVIVES and its
    #     reason changed: the twelve monthly releases of one calendar year land on twelve DISTINCT
    #     registered days, and the month_code-0 anchor is 1 January, a day no real stamp can produce
    #     (registered days over 2006+ are 8..14). It is now a property of the CALENDAR, measured
    #     against the banked one in tests/unit/test_numbers_parity_prereq.py, not an identity derived
    #     from arithmetic.
    #   * DEEP SPAN. Crush runs MY1960-2026 (census), so the pre-2005 as-of is a real read.
    #
    # WHY THE PAIRS, and why the grid cannot do this: the grid's ORDER BY is ASC on period, so the five
    # rows _rows_key compares are always the OLDEST marketing years whatever the as-of -- the vintage fan
    # never reaches the compared projection. Pinning `period` collapses each leg to ONE row and puts the
    # fan INSIDE the compare:
    #   (MY1998, 2001-06-30) -- the month_code-0 era. The card measures 389,283 rows at month_code 0,
    #       MY1960-2004, one pass-through print per marketing year at release_date = Jan 1 of that year.
    #       This leg is UNAFFECTED by the clock change: month_code 0 still anchors to 1 January of the
    #       MARKETING year, which is what keeps 30,715 wide rows byte-identical across the re-baseline.
    #   (MY2010, <mid-fan as-of>) -- INSIDE MY2010's fan, so an EARLIER vintage wins.
    #   (MY2010, <settled as-of>)  -- the SETTLED end of the same marketing year, so the LATEST wins.
    #       SAME cell, DIFFERENT vintage, so a backend that collapsed the fan differently cannot pass
    #       both legs, and an as-of machinery that had quietly stopped moving cannot pass either.
    #       THE TWO AS-OFS ARE NO LONGER DERIVABLE FROM A FORMULA (lane E, 2026-09-04). They used to
    #       be: "Soybean MYS = 9, so the monthly vintages run 2010-09-10 (month_code 1) .. 2011-08-10
    #       (month_code 12); this as-of must select 2011-01-10" -- every one of those sentences was the
    #       retired rotation's arithmetic and every one of them is false now. MY2010's vintages are
    #       whichever releases actually touched that cell, so the pair is RE-DERIVED from the shadow
    #       object before the promote (R7b) and the per-leg lines are READ. See the block beside
    #       PSD_ATTR_VINTAGE_CELLS above.
    # Both aggs run although they compile the BYTE-IDENTICAL string today -- this card has no date_col, so
    # `agg=latest` falls past the vintage branch's `and order` into the same series arm. Keeping the pair
    # is the regression detector: the day a date_col is declared here the two arms diverge and the gate
    # exercises both, instead of silently proving only one.
    #
    # NON-VACUITY PRECONDITION to re-check at the first live run (the silver_futures_eod discipline):
    # empty-on-both is a MATCH, so were US soybean Crush absent at MY1998 or MY2010 these six legs would
    # pass while proving nothing, and the table-wide EMPTY-PANEL guard would not see it -- they share the
    # grid's tid. The check is the report's own per-leg lines, read once.
    #
    # FENCE GUARDS REPEATED ON PURPOSE: this block sits OUTSIDE the table loop and therefore outside its
    # SKIP-FENCED / SKIP-UNMIRRORED branches. Re-arm the Lane-3 whitelist entry (or drop the table from
    # P1_TABLES) and the loop would skip it loudly while these legs still fired at a registry that raises
    # KeyError, or at a pg relation that was never created -- each booked as a MISMATCH, the whole gate
    # red for a table nobody is serving. (The ESR leg above carries the same shape and the same latent
    # exposure; silver_esr is served AND mirrored today, so that is named here, not silently rewritten.)
    _PSD_ATTR = "silver_psd_attributes"
    if _PSD_ATTR in tables and _PSD_ATTR in reg.tables and _PSD_ATTR in PG_MIRROR_TABLES:
        for my, asof in PSD_ATTR_VINTAGE_CELLS:
            for agg in ("latest", "series"):
                _cmp(Q.NumberQuery(table=_PSD_ATTR, metric=PSD_ATTR_CELL_METRIC, asof=asof,
                                   commodity=PSD_ATTR_CELL_COMMODITY, country=PSD_ATTR_CELL_COUNTRY,
                                   period=my, agg=agg, limit=50),
                     _PSD_ATTR, f"{PSD_ATTR_CELL_METRIC}[{PSD_ATTR_CELL_COUNTRY} MY{my}]", asof, agg)
    mismatches += vacuity_mismatches(compared, nonempty, spec_invalid)
    lines += ["", f"## verdict: {match}/{total} exact-match",
              # The CURRENCY verdict is its OWN line and never folded into the one above. The
              # 2026-09-22 report read `## verdict: 108/108 exact-match` beside a twelve-day-old
              # mirror; a reader must be able to see, in one line, which of the two questions was
              # answered. Folding the tip legs into the same fraction would have made that
              # unreadable in exactly the way it was already unreadable.
              f"## tip verdict: {tip_match}/{tip_total} tables at the canonical tip"
              + (" (REPORT-ONLY)" if tip_only else ""),
              "PASS - flip GRAPHRAG_NUMBERS_BACKEND=pg" if not mismatches and match == total and total > 0
              else "FAIL - do NOT flip; mismatches below", ""]
    lines += [f"- {m}" for m in mismatches]
    if tip_advisories:
        lines += ["", f"## {len(tip_advisories)} tip advisories NOT blocking this run "
                      f"({_TIP_REPORT_ONLY_ENV} is lit -- this is the ONE-DAY read-first override, "
                      f"not a setting):"]
        lines += [f"- {m}" for m in tip_advisories]
    report = "\n".join(lines)
    print(report)

    out = "data/graphrag/numbers_pg_parity.md"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(report)
    s3uri = os.environ.get("EVIDENCE_S3")
    if s3uri:
        try:
            import boto3
            from leviathan.graphrag import evidence as ev
            b, k = ev._parse_s3(s3uri.rstrip("/") + "/eval/numbers_pg_parity.md")
            boto3.client("s3").put_object(Bucket=b, Key=k, Body=report.encode("utf-8"))
            logger.info("report persisted to s3://%s/%s", b, k)
        except Exception as e:  # noqa: BLE001
            logger.warning("s3 persist failed: %s", e)
    return 0 if not mismatches else 1


if __name__ == "__main__":
    raise SystemExit(main())
