"""Numbers registry — the per-table contract for the observed-value SQL agent.

Each entry declares a table's SQL SHAPE (wide=metric-is-a-column | tall=metric-is-a-row-value), how
commodity/country/period are identified, and — the field that makes lookups trustworthy — its KNOWLEDGE-DATE
SEMANTICS: the anchor for point-in-time correctness so a query can never see a value that wasn't yet published
at `asof`.

  - vintage   : the table carries an explicit publication/vintage date (PSD.release_date, WASDE.release_date,
                ESR.as_of_date). As-of a date = the LATEST vintage whose publish date <= asof.
  - ingest    : observational, non-revising data stamped only with an ingest date (weather, production). As-of
                = rows whose ingest_date <= asof.
  - data_date : known same-day, no separate publication (prices, indices). As-of = rows whose data date <= asof.

Loaded once (cached). Doubles as the agent's cached system-prompt context AND the query builder's schema source.
"""
from __future__ import annotations

import functools
from pathlib import Path
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, ConfigDict

from leviathan.graphrag import extract as ex  # ex._CFG -> configs/graphrag


class Metric(BaseModel):
    # extra="forbid": a typoed key (unit_overides) would otherwise be silently dropped, disarming the
    # unit rewrite, the build_sql commodity raise, AND the R1/R3 lint in one keystroke -- fail at load.
    model_config = ConfigDict(extra="forbid")
    unit: str = ""
    desc: str = ""
    unit_overrides: dict[str, str] = {}                      # DP-1 (PRICE_OBSERVABILITY W1.1): per-commodity unit
    #                                                          for a metric whose SOURCE carries no governed unit
    #                                                          (silver avg_farm_price's `unit` column is null/junk
    #                                                          section-heading text). Q.run POST-FETCH sets
    #                                                          r["unit"] = unit_overrides.get(spec.commodity, "")
    #                                                          on EVERY row (incl. agg-shaped rows, which emit no
    #                                                          extras); build_sql RAISES if it is set and the query
    #                                                          carries no commodity (unattributable blank-unit rows).
    row_filters: dict[str, dict[str, list[str]]] = {}        # A3 (PRICE_OBSERVABILITY re-whitelist): per-commodity
    #                                                          row constraints for a metric whose silver rows carry
    #                                                          ATTRIBUTION BLEED. Shape {commodity: {column: [allowed
    #                                                          values]}} -> build_sql emits `column IN (...)` and
    #                                                          apply_pit_filter mirrors it, only when spec.commodity
    #                                                          has an entry (else byte-identical). If `column` is the
    #                                                          table's country_col the IN clause REPLACES the plain
    #                                                          country equality (widening the match -- silver_wasde
    #                                                          cotton farm price lives under region 'u_s_cotton'
    #                                                          pre-2011 AND 'united_states' 2011-09-12+); otherwise
    #                                                          it is an ADDITIONAL restriction (soybeans farm price
    #                                                          fenced to unit IN ('$/bu','') so the '$/s.t.'/'c/lb'/
    #                                                          'Domestic Measure' bleed rows never reach serving).


class VintageTiebreakTerm(BaseModel):
    """One ORDER BY term appended (AFTER knowledge_date DESC) to the latest-vintage ROW_NUMBER window so the
    per-grain pick is a DETERMINISTIC TOTAL order — identical on Athena and the pg mirror by construction.

    A term with a non-empty ``role_order`` emits a CASE rank (the value listed FIRST ranks 0 == wins the tie —
    e.g. actual < estimate < projection makes the most-settled figure win); a term with ``match_release_month``
    set emits a RELEASE-RELATIVE rank (rank 0 == wins when ``col`` equals the full English month name of that
    date column's month — silver_wasde's current-vs-prior projection-month pair, where the CURRENT projection
    == the RELEASE month and a static month order is WRONG at the Dec→Jan wrap, probed present); otherwise it
    is a plain ``col dir [NULLS first|last]`` term. Directions AND null placement are emitted EXPLICITLY
    because Presto (Athena) and Postgres disagree on the DEFAULT null placement for DESC — a bare DESC on a
    nullable column would order differently on the two engines and reopen the parity break.

    THE ORACLE-DIR CONTRACT: ``dir`` is honored SYMMETRICALLY in the SQL emitter (_vintage_tiebreak_order)
    AND the pure-Python oracle (_vintage_cmp) for BOTH the plain and the role_order branch — a role_order term
    with ``dir: desc`` would otherwise emit a descending CASE rank in SQL while the oracle ranked ascending
    (a silent divergence). The release-relative term carries no ``dir`` at all (default ASC, rank 0 wins), so
    both engines agree by construction."""
    model_config = ConfigDict(extra="forbid")
    col: str
    dir: Literal["asc", "desc"] = "asc"
    nulls: Optional[Literal["first", "last"]] = None
    role_order: list[str] = []                               # non-empty -> emit a CASE rank (priority order)
    match_release_month: Optional[str] = None                # names a release-date column: rank 0 (wins) when
    #                                                          `col` == full-month-name of that column's month.
    #                                                          silver_wasde's chronological current-month pick;
    #                                                          release-relative (correct at the Dec/Jan wrap,
    #                                                          which a static winner-first list gets wrong).
    #                                                          Default ASC, no `dir` -> both engines agree.


class TableSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    description: str
    quarantined: bool = False                                # SILVER-F047 (silver_nasa_power): no engine map may
    #                                                          reference a quarantined table -- enforced build-
    #                                                          failing by config_check.check_quarantine. Direct
    #                                                          agent lookups stay allowed (raw daily weather has
    #                                                          no gold replacement; gold_weather_z = anomalies).
    athena_table: Optional[str] = None                       # physical Glue table when it differs from the id —
    #                                                          e.g. silver_esr serves from silver_esr_compact
    #                                                          (registered partitions; the projected original
    #                                                          cost ~130-600K S3 LISTs/query, Jul-2026 storm)
    grain: str = ""
    shape: Literal["wide", "tall"]
    commodity_col: Optional[str] = None
    country_col: Optional[str] = None
    country_name_ref: Optional[str] = None                   # ESR_DESTINATION_PLAN W1: a numbers-owned static
    #                                                          name<->code reference (configs/graphrag/<ref>.yaml,
    #                                                          e.g. numbers/esr_destinations.yaml) for a card whose
    #                                                          country_col is a RAW code (silver_esr.country_code, an
    #                                                          int FAS destination code with no name). Set ->
    #                                                          build_sql resolves spec.country NAME to code(s) and
    #                                                          emits `CAST(country_col AS varchar) IN (...)` (fail-
    #                                                          CLOSED on an unresolved name), and run() renders the
    #                                                          row's code back to a display name in the `country`
    #                                                          extra. None (every other table) -> byte-identical
    #                                                          (the plain country equality path).
    period_col: Optional[str] = None
    period_type: Literal["marketing_year", "year", "date", "none"] = "none"
    period_sql_type: Literal["int", "string"] = "string"     # how the period column compares in SQL
    period_offset: int = 0                                   # source-label translation: OUR convention is MY=START
    #                                                          year; ESR labels by END year -> offset +1 at compile
    levels_only: bool = False                                # SEAM C (futures v1.5-lite): a roll-spliced
    #                                                          continuous FRONT-MONTH settle series carries NO
    #                                                          true vintage and NO PIT-safe cross-date delta --
    #                                                          the splice between expiries contaminates any
    #                                                          change/window/curve read. build_sql RAISES on any
    #                                                          agg != latest OR any period_start/period_end window
    #                                                          for such a table, so only single-date agg=latest
    #                                                          levels are ever compiled (defense-in-depth beside
    #                                                          the agent's phrasing-based decline routes).
    date_col: Optional[str] = None                           # the DATA date (weather obs date, week ending, ...)
    date_col_type: Literal["string", "timestamp"] = "string"  # DP-5 (PRICE_OBSERVABILITY W1.1): physical type of
    #                                                          the date col. "timestamp" -> the query builder emits
    #                                                          substr(CAST(date_col AS varchar), 1, 10) for that
    #                                                          column in BOTH the _extras aliases AND every guard/
    #                                                          window predicate, so Athena's timestamp(3) render
    #                                                          ('2026-06-01 00:00:00.000') and the pg TEXT mirror
    #                                                          ('2026-06-01 00:00:00') both normalize to
    #                                                          'YYYY-MM-DD' -- else parity breaks and a window's
    #                                                          boundary month is silently excluded. "string"
    #                                                          (default) -> byte-identical to before.
    provenance_col: Optional[str] = None                     # DP-2 (PRICE_OBSERVABILITY W1.1): a revision/vintage-
    #                                                          stamp column surfaced by _extras as alias
    #                                                          `revision_stamp` (wasde estimate_role -> projection
    #                                                          vs actual visible on the row; pink_sheet
    #                                                          latest_release_ym -> "as published, WB release ...").
    year_col: Optional[str] = None                           # year_month semantics: the year column
    month_col: Optional[str] = None                          # year_month semantics: the month column
    knowledge_date_col: Optional[str] = None                 # the vintage/publication/ingest date
    knowledge_semantics: Literal["vintage", "ingest", "data_date", "year_month"] = "data_date"
    publication_lag_days: int = 0                            # PUBLICATION LAG (ESR): rows are stamped by a DATA
    #                                                          date (week_ending_date) but not PUBLIC until this
    #                                                          many days later; the as-of guard shifts its cutoff
    #                                                          back by it (data_date + lag <= asof) so a not-yet-
    #                                                          published week is never citable. 0 = same-day default
    partition_cols: list[str] = []                           # injected-projection partitions: every query MUST carry
    #                                                          a static equality on EACH (silver_nasa_power:
    #                                                          commodity/country/region, mirroring the S3 layout)
    #                                                          ONE EXCEPTION (W3.1, silver_futures_eod's
    #                                                          trade_year): a partition col that is ALSO the
    #                                                          declared year_col is pinned by the SARGABLE YEAR
    #                                                          BOUNDS _filters already emits, not by an equality
    #                                                          -- a date-window read legitimately spans years, so
    #                                                          an equality would silently return ZERO rows, and
    #                                                          `year` is not a NumberQuery field to pass by hand.
    # ── projection-enumeration guards (Jul-2026 S3 LIST storm: silver_esr projects as_of_date over
    #    1990->NOW x market_year x commodity_code ~ 6.1M candidate prefixes; every query WITHOUT sargable
    #    predicates on those columns made Athena LIST ~130-600K S3 prefixes — $134 in two days) ──────────
    vintage_partition_col: Optional[str] = None              # a PROJECTED partition column holding the vintage/
    #                                                          publication date; build_sql bounds it natively
    #                                                          (never CAST — CAST defeats projection pruning)
    vintage_partition_format: Literal["yyyyMMdd", "iso"] = "yyyyMMdd"   # the partition VALUE format
    vintage_dates_real: bool = False                         # True = partition values are REAL publication
    #                                                          dates (silver_wasde) -> date bounds are valid
    #                                                          pruning. False = write-date snapshots
    #                                                          (silver_esr) -> date bounds are WRONG
    #                                                          (canary-proven 2026-07-04); never emit them
    commodity_code_col: Optional[str] = None                 # projected int partition keyed by source code
    commodity_codes: dict[str, int] = {}                     # slug -> source code (prunes the code partition)
    metric_col: Optional[str] = None                         # tall: column holding the metric NAME
    value_col: Optional[str] = None                          # tall: column holding the numeric VALUE
    unit_col: Optional[str] = None
    contract_month_col: Optional[str] = None                 # W3.1 (PRICE_AND_PLAYBOOKS): the DELIVERY-MONTH
    #                                                          column of a per-expiry price table
    #                                                          (silver_futures_eod.contract_month, 'YYYY-MM').
    #                                                          Set -> NumberQuery.contract_month becomes
    #                                                          expressible: build_sql emits an equality for one
    #                                                          expiry and `col IN (...)` for a CURVE read across
    #                                                          expiries, apply_pit_filter mirrors it, and _extras
    #                                                          surfaces the alias `contract_month` -- a curve row
    #                                                          without its expiry label is UNATTRIBUTABLE. None
    #                                                          (every other table) -> byte-identical SQL, and a
    #                                                          contract_month ask RAISES rather than being
    #                                                          silently widened to a continuous/front-month series.
    settle_kind_col: Optional[str] = None                    # W3.1: the PROVENANCE-of-the-number column
    #                                                          (settlement | close | mark_to_market | cash_index)
    #                                                          surfaced by _extras as alias `settle_kind`. An ICE
    #                                                          row is a session CLOSE, never an official
    #                                                          settlement; the label travels ON the row so the
    #                                                          citation cannot round it up to "the settlement".
    currency_col: Optional[str] = None                       # W3.1: the row's ISO-4217 currency, surfaced by
    #                                                          _extras as alias `currency`. Ten currencies live in
    #                                                          one table and NOTHING is FX-converted at ingest or
    #                                                          at serving, so a bare number is unattributable
    #                                                          without it (mirrors unit_col exactly: declare the
    #                                                          column, get the alias, no other behavior).
    roll_input_cols: list[str] = []                          # D-PQ A' (OPTION A-prime, the exchange-settle
    #                                                          anchor): the PHYSICAL columns a per-expiry price
    #                                                          card carries that the ONE query-time front-month
    #                                                          rule (leviathan.silver.futures_roll.front_month,
    #                                                          ROLL_RULE_VERSION front_month_v2) reads as its
    #                                                          ACTIVITY METRIC. Declaring a NON-EMPTY list is
    #                                                          what makes `agg='front_expiry'` expressible on
    #                                                          the card: those columns ride the SELECT of that
    #                                                          ONE branch, are consumed BY THE RULE, and are
    #                                                          STRIPPED off the returned row (they are not
    #                                                          served metrics -- the card's whitelist stays
    #                                                          settle-only, and a provenance column the reader
    #                                                          could quote as a figure is exactly what that
    #                                                          whitelist exists to prevent). The list is BOUND
    #                                                          at the seam to the rule module's own declared
    #                                                          input contract and a drift RAISES there
    #                                                          (query._front_expiry_input_cols) -- never a
    #                                                          second copy of "which method reads which
    #                                                          column", which is the F-L drift class the rule
    #                                                          module exists to prevent. [] (every other card)
    #                                                          -> agg='front_expiry' is not expressible and
    #                                                          build_sql RAISES rather than guessing a front
    #                                                          month from the nearest listed expiry.
    metrics: dict[str, Metric] = {}                          # wide: column->Metric ; tall: metric-value->Metric
    grain_cols: list[str] = []                               # explicit unique-observation identity (else inferred)
    vintage_tiebreak: list[VintageTiebreakTerm] = []         # optional per-grain tiebreak for latest-vintage
    #                                                          selection (vintage tables only). silver_wasde:
    #                                                          early-era releases (1985-1999) carry MULTIPLE
    #                                                          estimate_role rows per numbers grain at ONE
    #                                                          release_date, so the release_date-only ROW_NUMBER
    #                                                          ties and pg-vs-Athena break the tie by engine
    #                                                          order (the F2 silver_rebuild_gate Branch-A break).
    #                                                          These terms are appended after the knowledge_date
    #                                                          DESC to force a deterministic total order. EMPTY
    #                                                          (every other table) -> the generated SQL is
    #                                                          byte-identical to before (zero behavior change).
    partitions: list[str] = []
    notes: str = ""

    def knowledge_col(self) -> Optional[str]:
        """The single column the as-of guard filters on. None for year_month (guarded on year*100+month)."""
        if self.knowledge_semantics == "vintage":
            return self.knowledge_date_col
        if self.knowledge_semantics == "ingest":
            return self.knowledge_date_col or self.date_col
        if self.knowledge_semantics == "year_month":
            return None
        return self.date_col or self.knowledge_date_col      # data_date

    def group_cols(self) -> list[str]:
        """The identity group for latest-vintage selection. Explicit grain_cols win (e.g. ESR keys on the WEEK,
        not the marketing year); else inferred from commodity/country/period(+metric)."""
        if self.grain_cols:
            return list(self.grain_cols)
        cols = [self.commodity_col, self.country_col, self.period_col]
        if self.shape == "tall":
            cols.append(self.metric_col)
        return [c for c in cols if c]


class NumbersRegistry(BaseModel):
    tables: dict[str, TableSpec]

    def get(self, table_id: str) -> TableSpec:
        if table_id not in self.tables:
            raise KeyError(f"unknown table '{table_id}' (known: {sorted(self.tables)})")
        return self.tables[table_id]


# SEAM C (futures v1.5-lite): silver_futures_prices is REGISTERED in tables.yaml + linted
# (config_check.check_futures_lite) and, as of 2026-07-23, WHITELISTED for serving -- the SEAM-C no-judge
# gate AND the yfinance freshness-stall fix BOTH passed (canonical silver/futures_prices/part-000.parquet
# refreshed, freshness alarm green), so the card is REMOVED from this set and load_registry no longer drops
# it: it enters the agent tool enum + system-prompt cards. The runtime kill-switch is now the ordinary
# GRAPHRAG_NUMBERS_DISABLE env idiom (single-table rollback, no redeploy).
#
# PRICE_AND_PLAYBOOKS W1.0 (2026-07-28) -> W3 (2026-07-30): ``silver_futures_eod`` -- the
# per-delivery-month EOD table -- sat in this set for all of W1.0 / W1 / W2, because no producer had
# written a single row yet. The fence was the whole gate for those waves: a whitelist-absent table
# vanishes from the agent's tool enum AND its system-prompt card, and every ``build_sql`` lookup raises
# ``KeyError`` -- fail-CLOSED.
#
# THE FLIP LANDED 2026-07-30 (W3.1 item 7) and the entry is GONE. What made it safe, all in the one
# change (the flip was never a one-line deletion -- deleting the entry makes the card visible to the
# agent's TOOL SCHEMA and system-prompt card):
#   (a) `contract_month` is declared in numbers.agent.tool_schema's input properties. The model can only
#       emit parameters the schema NAMES; the field was already a NumberQuery/TableSpec dimension and
#       _forced_spec honoured it, so the omission would have been silent rather than loud -- a December
#       ask that never emits the parameter is WIDENED to the whole curve, and agg=latest then answers it
#       with the nearest listed expiry. That is exactly the failure build_sql's delivery-month guard
#       exists to prevent, arriving by a different route. tests/unit/test_futures_eod_curve.py holds
#       this as a BUILD FENCE: the test fails the moment the card is served without the parameter.
#   (b) numbers.dispatch ToolSpec.purpose names TERM STRUCTURE / the curve (W3.1 item 8) --
#       family_names() derives the router enum from the registry, so the family arrived automatically.
#   (c) config_check.check_futures_eod clause (c) is INVERTED: it now errors unless the table IS served
#       AND the reachability trio holds (schema parameter + dispatch purpose + the card's declared
#       dimensions), and the ~4 tests that pinned the fence were re-pointed at that invariant.
#   (d) THE COVERAGE GUARD (W3.2, futures_eod_contracts.covers): the served path routes every window
#       against the MEASURED per-contract floor -- serve / legacy level with a provenance sentence /
#       DECLINE a straddle -- so a whitelisted card cannot answer a pre-coverage era by splicing a
#       per-expiry series onto the roll-spliced continuous one.
# The rollback lever is now the ordinary GRAPHRAG_NUMBERS_DISABLE=silver_futures_eod env idiom
# (single-table, config-only, no redeploy).
#
# THE SET STAYS (deliberately empty, not deleted): the next table registered ahead of its producer needs
# exactly this fence, and re-deriving it later loses the (a)-(d) checklist above -- which is the part
# that made the flip an atomic change rather than four separable ones. It also stays DISJOINT from
# _disabled_tables() (env-only) so the env-parse kill-switch tests are byte-identical; the union happens
# once, in load_registry.
#
# AND THE NEXT TABLE IS ON ITS WAY (OUTCOMES_JOIN J1/J2, 2026-08-01): ``gold_futures_outcomes``. Its
# card -- which IS the PIT clamp (D-OJ-13), so it is written with the rule module rather than after it
# -- is STAGED at configs/graphrag/numbers/cards/gold_futures_outcomes.yaml and lands in tables.yaml
# together with its SILVER-F010 contract (the two registries are bound by
# silver/reconcile.NUMBERS_TABLES). Its producer (jobs/batch/gold_futures_outcomes_task.py) has not run
# and no Glue table exists. The fence entry is ARMED AHEAD OF THE PASTE deliberately, so that landing
# the card cannot by itself change serving: whitelist-absent is exactly the state silver_futures_eod
# held through W1/W2 --
# card is dropped at load, so it is absent from the agent tool enum AND the system-prompt card, and
# every build_sql lookup raises KeyError -- fail CLOSED, serving byte-identical. The flip is the
# consumer wave's step and repeats the (a)-(d) checklist above: the first build lands, the card's
# dimensions are reachable from the tool schema + dispatch purpose, and the coverage/PIT lints
# (outcomes.lint_outcome_card, config_check.check_futures_outcomes) are green.
#
# AND THE OTHER TWO IDS OF THE SAME WAVE, ARMED ON THE SAME ARGUMENT (adversarial finding 14):
#   * ``gold_pattern_outcomes`` -- the fence is not merely prudent here, it is REQUIRED, and
#     ``pattern_records.lint_pattern_outcome_card`` says why in its own docstring: the ledger carries a
#     SECOND PIT axis (``ledger_written_at``, the ingest date -- a backfill_grid verdict for a 2023 asof
#     was written in 2026) and ``TableSpec.knowledge_col()`` yields exactly ONE column, so a
#     registry-compiled read of this table CANNOT express it. The engine leg applies both axes by hand.
#     A paste without this entry is therefore a live PIT hole, not a scheduling detail.
#   * ``gold_cot_outcomes`` -- in both ``POSITIONING_TABLES`` constants and in no whitelist until now.
#     Its producer does not exist either, and the J6 leg is fail-closed on an unregistered card.
# THE FLIP REMOVES THE ID, per table, exactly as it does for silver_futures_eod: the (a)-(d) checklist
# above, plus the card's own lint green. NOTE while the entries stand: ``config_check`` reads these
# cards through the RAW registry file rather than ``load_registry()`` precisely so that whitelisting
# them does not also blind their lints -- a fence that disarms the check that guards it is not a fence.
WHITELIST_ABSENT_DEFAULT: frozenset[str] = frozenset({
    "gold_futures_outcomes", "gold_pattern_outcomes", "gold_cot_outcomes",
})


def _disabled_tables() -> frozenset[str]:
    """Kill-switch: table ids to DROP from the loaded registry at load time (env
    ``GRAPHRAG_NUMBERS_DISABLE``, comma-separated). A dropped table vanishes from the agent's tool
    enum (``sorted(reg.tables)``) AND its system-prompt card, and every ``build_sql`` lookup for it
    raises ``KeyError`` (fail-CLOSED for that table) — an instant, config-only rollback for a freshly
    wired table without touching tables.yaml. Read ONCE per registry load (the load is lru_cached).
    Parse junk -> EMPTY set (fail-OPEN: a malformed env var must NEVER silently disable the whole
    numbers stack)."""
    import os
    try:
        raw = os.environ.get("GRAPHRAG_NUMBERS_DISABLE", "") or ""
        return frozenset(t.strip() for t in raw.split(",") if t.strip())
    except Exception:  # noqa: BLE001 — env junk must never break registry load
        return frozenset()


def visible_tables(reg: NumbersRegistry) -> list[str]:
    """THE ONE derivation of "which registered tables are actually exposed this call": ``sorted(reg.tables)``
    MINUS the flag-gated pattern-records card when ``GRAPHRAG_PATTERN_RECORDS`` is OFF. Read PER CALL so the
    kill-switch rollback stays live (never memoize this, and never memoize anything derived from it).

    D-CW-1d (2026-08-07, the DARK CAPABILITY CENSUS enum leak). This used to live only in
    ``numbers.agent._visible_tables``, while ``dispatch.family_names()`` derived the planner's
    ``data_families`` enum from ``load_registry().tables`` -- the UNFILTERED set. With the flag off the
    router could therefore emit ``pattern_records``, a family whose table is absent from the agent's tool
    enum and its system-prompt card: the steering hint resolved to nothing (fail-soft, so it was invisible),
    but the planner was being told a capability existed that the agent could not reach. The two derivations
    are now ONE function, here in the registry module rather than in either consumer, because the numbers
    agent must keep no dependency on the planner and the planner is not the owner of the registry's
    visibility rule. Both callers are thin wrappers over this.

    The pattern-records import is LOCAL: ``pattern_records`` imports the numbers stack, and a module-level
    import here would make the registry -- which every numbers module loads -- the bottom of an import
    cycle. It is a pure-python module with no AWS/IO at import, so the call is cheap."""
    tables = sorted(reg.tables)
    from leviathan.graphrag.numbers import pattern_records as PR
    if PR.PR_TABLE in tables and not PR.pattern_records_on():
        tables = [t for t in tables if t != PR.PR_TABLE]
    return tables


@functools.lru_cache(maxsize=4)
def load_registry(path: Optional[str] = None) -> NumbersRegistry:
    p = Path(path) if path else (ex._CFG / "numbers" / "tables.yaml")
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    tables = {tid: TableSpec(id=tid, **spec) for tid, spec in (raw.get("tables") or {}).items()}
    disabled = _disabled_tables() | WHITELIST_ABSENT_DEFAULT   # env kill-switch + SEAM-C whitelist-absent default
    if disabled:
        tables = {tid: ts for tid, ts in tables.items() if tid not in disabled}
    return NumbersRegistry(tables=tables)
