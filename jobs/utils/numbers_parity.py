"""The pg-mirror parity gate (BLOCKING for GRAPHRAG_NUMBERS_BACKEND=pg).

Runs a grid of registry (table, metric) x sample (commodity, asof) NumberQuery specs through BOTH backends
— the SAME build_sql() string executed on Athena and on the pg mirror — and diffs the rows (values +
knowledge/vintage dates). The flip to pg is allowed only on a clean report. ASCII-only stdout (cp1252
console rule); the full report also lands in data/graphrag/ + S3 when EVIDENCE_S3 is set.

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
                    "silver_psd_attributes": "soybeans_cbot"}
# 2026 asof included because ingest-semantics tables (silver_production) were ingested in 2026 — earlier
# asofs legitimately see 0 rows (honest PIT), which would leave that panel vacuous.
ASOFS = ["2021-08-15", "2024-06-01", "2026-07-01"]
AGGS = ["latest", "series"]

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

    total = match = 0
    mismatches: list[str] = []
    nonempty: dict[str, int] = {}                     # per-table compared queries with actual rows
    compared: dict[str, int] = {}
    lines = [f"# numbers pg-parity report ({date.today().isoformat()})", ""]
    def _cmp(spec, tid, metric, asof, agg):
        """One spec -> compare Athena vs the pg mirror (the SAME build_sql string on both) and tally into
        the enclosing report state. Reused verbatim by the (table,metric,asof,agg) grid AND the ESR
        destination leg (ESR_DESTINATION_PLAN 5.2), so both run identical compare logic."""
        nonlocal total, match
        try:
            sql = Q.build_sql(spec)
        except Exception as e:  # noqa: BLE001 — spec not valid for this table (e.g. region rules)
            lines.append(f"- SKIP {tid}.{metric} asof={asof} agg={agg}: spec invalid ({e})")
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
        # Lift the [:4] sampling cap for TALL tables (Attack 3 #4): a tall table's metrics are ROW values
        # (gold_weather_z has 5, silver_wasde 6) and the cap would skip metrics past the 4th, letting a
        # broken/missing tail metric slip through parity. Wide tables (metrics == columns, cheap) keep the
        # cap -- their panel is representative at 4.
        metric_list = list(ts.metrics) if ts.shape == "tall" else list(ts.metrics)[:4]
        for metric in metric_list:
            for asof in ASOFS:
                for agg in AGGS:
                    _cmp(Q.NumberQuery(table=tid, metric=metric, asof=asof, commodity=commodity,
                                       agg=agg, limit=50), tid, metric, asof, agg)

    # ESR_DESTINATION_PLAN 5.2: destination-scoped parity leg -- the concrete cross-backend proof that the
    # smallint (Athena) / TEXT (pg) country_code compares IDENTICALLY under CAST(country_code AS varchar)
    # IN (...). corn_cbot + country='China' (FAS 5700), agg=sum (MY total) and agg=latest (freshest week).
    # Empty-on-both is a match (not a mismatch); only a genuine athena!=pg divergence flags -- exactly the
    # smallint/TEXT trap needing runtime proof (the offline unit test only proves the SQL STRING is emitted).
    if "silver_esr" in tables:
        for asof in ASOFS:
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
    # A panel where EVERY compared query returned 0 rows on BOTH backends proves nothing (wrong sample
    # commodity, empty mirror table, ...) — vacuous panels BLOCK the flip like a mismatch does.
    for tid, n in compared.items():
        if n > 0 and nonempty.get(tid, 0) == 0:
            mismatches.append(f"EMPTY-PANEL {tid}: all {n} compared queries returned 0 rows on both "
                              "backends - vacuous, check SAMPLE_COMMODITY / mirror load")
    lines += ["", f"## verdict: {match}/{total} exact-match",
              "PASS - flip GRAPHRAG_NUMBERS_BACKEND=pg" if not mismatches and match == total and total > 0
              else "FAIL - do NOT flip; mismatches below", ""]
    lines += [f"- {m}" for m in mismatches]
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
