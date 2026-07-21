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


class VintageTiebreakTerm(BaseModel):
    """One ORDER BY term appended (AFTER knowledge_date DESC) to the latest-vintage ROW_NUMBER window so the
    per-grain pick is a DETERMINISTIC TOTAL order — identical on Athena and the pg mirror by construction.

    A term with a non-empty ``role_order`` emits a CASE rank (the value listed FIRST ranks 0 == wins the tie —
    e.g. actual < estimate < projection makes the most-settled figure win); otherwise it is a plain
    ``col dir [NULLS first|last]`` term. Directions AND null placement are emitted EXPLICITLY because Presto
    (Athena) and Postgres disagree on the DEFAULT null placement for DESC — a bare DESC on a nullable column
    would order differently on the two engines and reopen the parity break."""
    model_config = ConfigDict(extra="forbid")
    col: str
    dir: Literal["asc", "desc"] = "asc"
    nulls: Optional[Literal["first", "last"]] = None
    role_order: list[str] = []                               # non-empty -> emit a CASE rank (priority order)


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
    period_col: Optional[str] = None
    period_type: Literal["marketing_year", "year", "date", "none"] = "none"
    period_sql_type: Literal["int", "string"] = "string"     # how the period column compares in SQL
    period_offset: int = 0                                   # source-label translation: OUR convention is MY=START
    #                                                          year; ESR labels by END year -> offset +1 at compile
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


@functools.lru_cache(maxsize=4)
def load_registry(path: Optional[str] = None) -> NumbersRegistry:
    p = Path(path) if path else (ex._CFG / "numbers" / "tables.yaml")
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    tables = {tid: TableSpec(id=tid, **spec) for tid, spec in (raw.get("tables") or {}).items()}
    disabled = _disabled_tables()
    if disabled:
        tables = {tid: ts for tid, ts in tables.items() if tid not in disabled}
    return NumbersRegistry(tables=tables)
