"""Deterministic, leakage-safe query layer for the numbers SQL agent.

The LLM never writes SQL. It emits a typed ``NumberQuery``; ``build_sql`` compiles it to parameterized Athena SQL
that ALWAYS injects the point-in-time knowledge guard from the table's registry spec — so a lookup can never see
a value that wasn't published by ``asof``. ``apply_pit_filter`` is the pure-Python reference implementing the
identical semantics (used by the anti-leakage property test + as a client-side fallback). ``run`` executes on
Athena (results are KBs).

Design: determinism at the CONTROL plane (which table/metric/asof), freedom at the REASONING plane (the agent
decides WHAT to look up and the synthesizer interprets it). No free-form SQL — leakage-safety, cost, and
testability are guaranteed by construction, not by prompt discipline.
"""
from __future__ import annotations

import functools
from typing import Literal, Optional

from pydantic import BaseModel

from leviathan.graphrag.numbers.registry import TableSpec, load_registry

ATHENA_DB = "leviathan_dev"


class NumberQuery(BaseModel):
    table: str
    metric: str
    asof: str                                        # REQUIRED point-in-time date 'YYYY-MM-DD' (as-known cutoff)
    commodity: Optional[str] = None
    country: Optional[str] = None
    region: Optional[str] = None                     # station-region for partition-required tables (nasa_power)
    period: Optional[str] = None                     # marketing_year / year value (per the table's period format)
    period_start: Optional[str] = None               # date-grained window start (weather / exports)
    period_end: Optional[str] = None                 # date-grained window end
    agg: Literal["latest", "series", "sum", "mean", "max", "min"] = "latest"
    limit: int = 5000


def _q(v) -> str:                                    # single-quote-safe SQL literal
    return "'" + str(v).replace("'", "''") + "'"


def _dcol(col: str) -> str:
    """Compare a date/knowledge column AS TEXT so the predicate works whether silver stored it as a DATE, a
    TIMESTAMP, or a string. Silver schemas are heterogeneous — silver_nasa_power.date is a true DATE (Athena
    rejects `date <= varchar`), while silver_psd.release_date / silver_fred_fx.data_date are strings. ISO-8601
    dates sort lexically == chronologically, and a DATE casts to 'YYYY-MM-DD', so a text compare is correct and
    type-agnostic. (A TIMESTAMP casts to 'YYYY-MM-DD HH:MM:...' — same-day rows compare conservatively, never
    leaking a future value.)

    NEVER use this on a PROJECTED PARTITION column: wrapping one in CAST (or any function) makes the
    predicate non-sargable, Athena cannot prune the projection, and it enumerates the FULL projected
    space — one S3 LIST per candidate prefix (the Jul-2026 $134 LIST storm). Projected columns get
    native-literal bounds via _vintage_partition_bounds instead."""
    return f"CAST({col} AS varchar)"


def _norm_ts_date(col: str) -> str:
    """DP-5 (PRICE_OBSERVABILITY W1.1): normalize a physical TIMESTAMP date column to a 'YYYY-MM-DD' string.
    Athena stringifies a timestamp(3) as '2026-06-01 00:00:00.000' and the pg mirror stores str(datetime) as
    '2026-06-01 00:00:00', so a naive text compare (a) breaks parity (every non-vacuous _rows_key mismatches)
    and (b) EXCLUDES a window's boundary month ('2026-06-01 00:00:00.000' > '2026-06-01'). substr(CAST(...),1,10)
    collapses both renders to the same 'YYYY-MM-DD' -- CAST is a no-op on the pg TEXT column and Athena substrs
    the varchar render. The table is flat/unpartitioned so sargability is moot (the no-CAST rule targets
    PROJECTED partition columns only, never this)."""
    return f"substr(CAST({col} AS varchar), 1, 10)"


def _pit_dval(ts: TableSpec, col: str, val) -> str:
    """DP-5 in the pure-Python PIT oracle (apply_pit_filter), mirroring _norm_ts_date's SQL substr. A physical
    TIMESTAMP date column's row value renders as '2026-06-01 00:00:00[.000]' from BOTH Athena and the pg mirror;
    truncating to the first 10 chars collapses it to 'YYYY-MM-DD', so the oracle keeps the boundary month at a
    window edge AND at the exact publication-lag boundary -- byte-for-byte the property build_sql's
    `substr(CAST(date AS varchar),1,10) <= cutoff` encodes (query.py:306, W2.6). Without this the raw
    '2026-06-01 00:00:00.000' > '2026-06-01' (and <= a 2026-06-01 lag cutoff is False), and the oracle diverges
    from the SQL it exists to verify. Applies ONLY to the date_col of a timestamp-typed table; every other
    column (and every string-typed table) is byte-identical to str(val)."""
    if ts.date_col_type == "timestamp" and col == ts.date_col:
        return str(val)[:10]
    return str(val)


def _dcmp(ts: TableSpec, col: str) -> str:
    """The text-comparable render of a knowledge/date column for a PREDICATE. DP-5: a physical TIMESTAMP date
    column normalizes to 'YYYY-MM-DD' (both backends agree, boundary month included); every other column keeps
    the type-agnostic CAST-as-varchar form (_dcol)."""
    if ts.date_col_type == "timestamp" and col == ts.date_col:
        return _norm_ts_date(col)
    return _dcol(col)


def _sel_date(ts: TableSpec, col: str) -> str:
    """The SELECT-list render of a date/knowledge column surfaced in _extras. DP-5: a physical TIMESTAMP date
    column is normalized to 'YYYY-MM-DD' so a monthly series never renders a raw timestamp in its [N] meta and
    the alias sorts lexically == chronologically; every other column is a bare reference."""
    if ts.date_col_type == "timestamp" and col == ts.date_col:
        return _norm_ts_date(col)
    return col


def _fmt_pdate(iso: str, fmt: str) -> str:
    """ISO 'YYYY-MM-DD' -> the partition-value format ('yyyyMMdd' strips dashes; 'iso' is identity)."""
    return iso.replace("-", "") if fmt == "yyyyMMdd" else iso


def _vintage_partition_bounds(spec: NumberQuery, ts: TableSpec) -> list[str]:
    """SARGABLE snapshot-locator window on a projected vintage-partition column (silver_esr.as_of_date).
    Native string compares in the partition's own value format — never CAST, so Athena prunes the
    projection instead of LISTing every candidate prefix (the Jul-2026 $134 storm: ~130-600K LISTs/query).

    NO bounds are emitted on the vintage column itself — the 2026-07-04 canary proved they are
    semantically WRONG for this storage layout: silver_esr keeps ONE latest snapshot per marketing year
    under the snapshot's WRITE date (the whole backfilled history sits at as_of_date ~ 2026-05-24), so a
    window derived from the marketing year or asof either misses the only existing partition (the MY-sum
    canary returned EMPTY) or still spans thousands of projected candidates. The vintage axis is pruned
    CATALOG-side instead: silver_esr moved from partition projection to REGISTERED Glue partitions
    (~350 real entries), which Athena prunes without any S3 enumeration and without query-shape
    constraints. What this helper still contributes: the market_year band for latest-style queries
    (collapses the 46-value MY axis when no period equality exists) — correct regardless of catalog
    mode, and the point-in-time guard stays on week_ending_date exactly as before."""
    col = ts.vintage_partition_col
    if not col:
        return []
    w: list[str] = []
    asof_y = int(spec.asof[:4])
    if ts.vintage_dates_real and spec.period:
        # REAL publication dates only (silver_wasde): no release mentioning marketing year Y is
        # published before Y's calendar year (WASDE first projects MY Y in May of Y) — the lower
        # bound shrinks the projected daily grid from (asof - 1973) candidates to ~(asof - Y) without
        # excluding any qualifying vintage. The upper bound lives in _guard (release <= asof, native).
        w.append(f"{col} >= {_q(_fmt_pdate(f'{int(str(spec.period)[:4])}-01-01', ts.vintage_partition_format))}")
    if not spec.period and ts.period_col and ts.period_sql_type == "int":
        if spec.period_start and spec.period_end:
            # source END-year labels covering the window, +1/+2 margin
            w.append(f"{ts.period_col} BETWEEN {int(spec.period_start[:4])} AND {int(spec.period_end[:4]) + 2}")
        elif spec.agg == "latest":
            # the MY containing asof carries END-label asof_y or asof_y+1; -1 for staleness margin
            w.append(f"{ts.period_col} BETWEEN {asof_y - 1} AND {asof_y + 1}")
    return w


def _commodity_code_filter(spec: NumberQuery, ts: TableSpec) -> list[str]:
    """Native equality on a projected int commodity-code partition when the slug maps (prunes 10x on
    silver_esr). An unmapped slug just skips pruning — the identity filter on commodity_name still scopes
    the ROWS; only the LIST cost is higher."""
    if ts.commodity_code_col and spec.commodity and spec.commodity in ts.commodity_codes:
        return [f"{ts.commodity_code_col} = {int(ts.commodity_codes[spec.commodity])}"]
    return []


def _esr_country_codes(spec: NumberQuery, ts: TableSpec) -> list[str]:
    """ESR_DESTINATION_PLAN W1 (sub-route A2): translate the model's destination NAME to FAS code(s)
    and emit a backend-agnostic ``CAST(country_col AS varchar) IN ('...')`` filter. CAST-as-varchar is a
    no-op on the pg TEXT ``country_code`` and stringifies the Athena smallint, so the quoted-string IN
    list compares IDENTICALLY on both backends (the smallint/TEXT type trap, ESR plan 1). ``country_code``
    is an in-file column of silver_esr_compact (NOT a projected partition key -- partitions = commodity),
    so the no-CAST-on-projected-partition rule does not apply.

    An UNRESOLVED name fails CLOSED (an IN list that matches ZERO rows), never a silent national total --
    the July name-vs-code lesson class (``country='China'`` -> ``country_code = 'China'`` -> 0 rows
    narrated as a real figure). EMPTY (no spec.country) -> [] so the national path is byte-identical."""
    if not (ts.country_name_ref and spec.country):
        return []
    from leviathan.graphrag.numbers.esr_destinations import load_esr_destinations
    codes = load_esr_destinations().resolve_codes(spec.country)
    col = _dcol(ts.country_col)                                # CAST(country_code AS varchar) -- type-agnostic
    if not codes:                                             # unresolved name -> fail CLOSED (zero rows)
        return [f"{col} IN ('__unresolved_destination__')"]
    return [f"{col} IN ({', '.join(_q(c) for c in codes)})"]


def _metric_commodity_filters(spec: NumberQuery, ts: TableSpec) -> dict[str, list[str]]:
    """A3 (PRICE_OBSERVABILITY re-whitelist): per-commodity ROW constraints declared on the queried metric
    (``Metric.row_filters``) as ``{column: [allowed values]}`` -- emitted as ``column IN (...)`` by build_sql
    and mirrored by apply_pit_filter. EMPTY unless ``spec.commodity`` has an entry, so every other lookup is
    byte-identical. silver_wasde.avg_farm_price uses it to (a) fence the soybeans attribution bleed to
    ``unit IN ('$/bu','')`` and (b) span the cotton region split ``region IN ('u_s_cotton','united_states')``;
    an IN clause on the table's country_col REPLACES the plain country equality (a WIDENING, not a narrowing --
    see _filters)."""
    m = ts.metrics.get(spec.metric)
    rf = getattr(m, "row_filters", None) if m else None
    if not rf or not spec.commodity:
        return {}
    return {col: list(vals) for col, vals in (rf.get(spec.commodity) or {}).items()}


def _value_expr(spec: NumberQuery, ts: TableSpec) -> str:
    return spec.metric if ts.shape == "wide" else (ts.value_col or "value")


def _snake(v: str) -> str:
    return v.strip().lower().replace(" ", "_")


@functools.lru_cache(maxsize=64)
def _geo(commodity: str) -> dict:
    """configs/geographies/<commodity>_regions.yaml -> {region: country_snake, '_primary': (country, region)}.
    Supplies the DEFAULT station-region (first primary-country location) and the region->country mapping for
    partition-projected weather tables. Countries there are snake_case ('united_states')."""
    import yaml

    from leviathan.graphrag import extract as ex
    p = ex._CFG.parent / "geographies" / f"{commodity}_regions.yaml"
    if not p.exists():
        return {}
    cfg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    blocks = sorted(cfg.get("regions") or [], key=lambda b: 0 if b.get("importance") == "primary" else 1)
    out: dict = {}
    for b in blocks:
        c = b.get("country") or ""
        for loc in b.get("locations") or []:
            r = loc.get("region")
            if r:
                out.setdefault(r, c)
                out.setdefault("_primary", (c, r))
    return out


def default_region(commodity: str) -> Optional[str]:
    prim = _geo(commodity).get("_primary")
    return prim[1] if prim else None


# Model-supplied country strings arrive in many surface forms; partitions use exactly one. A miss is
# silent (SUCCEEDED query, 0 bytes scanned, 0 rows) — the July-3 eval's b_weather_2012 emitted 'us',
# matched no partition, and the answer narrated the empty result as "not yet published".
_COUNTRY_ALIASES = {"us": "united_states", "usa": "united_states", "u.s.": "united_states",
                    "u_s": "united_states", "u.s.a.": "united_states", "america": "united_states",
                    "united_states_of_america": "united_states",
                    "uk": "united_kingdom", "uae": "united_arab_emirates"}


def _canon_country(country: Optional[str]) -> Optional[str]:
    if not country:
        return None
    s = _snake(country)
    return _COUNTRY_ALIASES.get(s, s)


def _resolved_country(spec: NumberQuery, ts: TableSpec) -> Optional[str]:
    """The country-PARTITION value, resolved in ONE place so build_sql (_partition_filters) and
    apply_pit_filter agree — the D-W0.1 clobber fix plus its lockstep oracle. Preference (do NOT collapse to a
    bare geo default — that discards a caller-resolved country: the July 'us' class AND the cascade's
    Title-Case _scope country): an EXPLICIT region's geography country wins (the finer key — the numbers-agent
    fix), else an EXPLICIT country canonicalised to the snake_case partition surface form (the cascade passes a
    deterministic resolved country), else geo's country for the DEFAULTED primary region when neither is
    pinned. `ts` is unused today (country is always the same physical column) but kept for signature parity
    with the other resolvers."""
    geo = _geo(spec.commodity) if spec.commodity else {}
    region = spec.region or (geo.get("_primary") or (None, None))[1]
    return (geo.get(spec.region) if spec.region else None) or _canon_country(spec.country) or geo.get(region)


def _partition_filters(spec: NumberQuery, ts: TableSpec) -> list[str]:
    """Static equalities for EVERY injected-projection partition (Athena CONSTRAINT_VIOLATION otherwise).
    region defaults to the commodity's primary station; the country partition value comes from
    _resolved_country (explicit-region country wins, else explicit country in the snake_case partition form,
    else the geo default — the D-W0.1 fix, replacing the old geo-default-clobbers-caller behavior); commodity
    must be given."""
    geo = _geo(spec.commodity) if spec.commodity else {}
    w: list[str] = []
    region = spec.region or (geo.get("_primary") or (None, None))[1]
    for col in ts.partition_cols:
        if col == ts.commodity_col:
            if not spec.commodity:
                raise ValueError(f"table {ts.id} requires commodity (partition column)")
            continue                                          # emitted by the regular commodity filter
        if col == ts.country_col:
            val = _resolved_country(spec, ts)
        elif col == "region":
            val = region
        else:
            val = getattr(spec, col, None)
        if not val:
            raise ValueError(f"table {ts.id} requires a static {col} equality (injected partition); "
                             f"pass {col}= or a commodity with a geographies config")
        w.append(f"{col} = {_q(val)}")
    return w


def _filters(spec: NumberQuery, ts: TableSpec) -> list[str]:
    """The identity/scope predicates (NOT the as-of guard)."""
    w: list[str] = list(_partition_filters(spec, ts)) if ts.partition_cols else []
    w += _vintage_partition_bounds(spec, ts) + _commodity_code_filter(spec, ts)
    cf = _metric_commodity_filters(spec, ts)                 # A3 per-commodity row constraints (metric.row_filters)
    if spec.commodity and ts.commodity_col:
        w.append(f"{ts.commodity_col} = {_q(spec.commodity)}")
    for col, vals in cf.items():                             # emit `col IN (...)`; a country_col IN clause
        if vals:                                             # REPLACES the plain equality below (widening the
            w.append(f"{col} IN ({', '.join(_q(v) for v in vals)})")  # match across e.g. the cotton region split)
    if ts.country_name_ref:                                  # ESR destination: NAME->code IN filter (fail-closed);
        w += _esr_country_codes(spec, ts)                    # [] when no spec.country -> national path unchanged
    elif spec.country and ts.country_col and ts.country_col not in ts.partition_cols and ts.country_col not in cf:
        w.append(f"{ts.country_col} = {_q(spec.country)}")
    if ts.shape == "tall" and ts.metric_col:
        w.append(f"{ts.metric_col} = {_q(spec.metric)}")
    if spec.period and ts.period_col:
        if ts.period_sql_type == "int":                  # +period_offset translates OUR start-year MY convention
            val = str(int(str(spec.period)[:4]) + ts.period_offset)   # to the source's label (ESR = end year)
        else:
            val = _q(spec.period)
        w.append(f"{ts.period_col} = {val}")
    if ts.date_col and spec.period_start:
        w.append(f"{_dcmp(ts, ts.date_col)} >= {_q(spec.period_start)}")   # DP-5: substr-normalized if timestamp
    if ts.date_col and spec.period_end:
        w.append(f"{_dcmp(ts, ts.date_col)} <= {_q(spec.period_end)}")     # DP-5: boundary month included
    if ts.year_col:
        # sargable bare-column year bounds: neither the ym EXPRESSION (year_month tables) nor a guard
        # on a date DATA column (silver_nasa_power, whose year/month are projected partitions) can
        # prune a projected year axis — weather queries probed ~660 year-month candidates each
        # (Jul-2026 lint finding). All three bounds are implied by the existing date/ym predicates,
        # so semantics are unchanged; they exist purely so projection pruning can see them.
        w.append(f"{ts.year_col} <= {int(spec.asof[:4])}")
        if spec.period_start:
            w.append(f"{ts.year_col} >= {int(spec.period_start[:4])}")
        if spec.period_end:
            w.append(f"{ts.year_col} <= {int(spec.period_end[:4])}")
    if ts.knowledge_semantics == "year_month" and (spec.period_start or spec.period_end):
        ym = f"({ts.year_col} * 100 + {ts.month_col})"          # window monthly (year_month) tables by 'YYYY-MM'
        if spec.period_start:
            w.append(f"{ym} >= {_asof_ym(spec.period_start)}")
        if spec.period_end:
            w.append(f"{ym} <= {_asof_ym(spec.period_end)}")
    return w


def _asof_ym(asof: str) -> int:
    return int(asof[:4]) * 100 + int(asof[5:7])              # 'YYYY-MM-DD' -> YYYYMM integer


def _pub_lagged_asof(asof: str, lag_days: int) -> str:
    """Shift the as-of cutoff BACK by a table's publication lag: a row stamped by its DATA date (ESR
    week_ending_date) is not PUBLIC until lag_days later, so the intended `data_date + lag <= asof` is bound
    as the equivalent `data_date <= asof - lag`. Shifting the RHS LITERAL (not the column) keeps the guard
    sargable and backend-agnostic — no SQL date arithmetic touches week_ending_date, so its text-compare form
    AND the commodity partition pruning stay exactly as before (D-W0.3). lag_days 0 (default) is identity."""
    if not lag_days:
        return asof
    from datetime import date, timedelta
    return (date(int(asof[:4]), int(asof[5:7]), int(asof[8:10])) - timedelta(days=lag_days)).isoformat()


def _guard(spec: NumberQuery, ts: TableSpec) -> str:
    """The as-of predicate that is ALWAYS present — the leakage guard."""
    if ts.knowledge_semantics == "year_month":
        if not (ts.year_col and ts.month_col):
            raise ValueError(f"table {ts.id} year_month semantics needs year_col + month_col")
        # the bare-column year bound is implied by the ym expression (any year > asof_year makes
        # year*100+month exceed asof_ym) — it exists purely so projection pruning can see the guard.
        return (f"({ts.year_col} * 100 + {ts.month_col}) <= {_asof_ym(spec.asof)} "
                f"AND {ts.year_col} <= {int(spec.asof[:4])}")
    col = ts.knowledge_col()
    if not col:
        raise ValueError(f"table {ts.id} has no knowledge/date column to anchor the as-of guard")
    asof = _pub_lagged_asof(spec.asof, ts.publication_lag_days)   # ESR: a week is citable only once PUBLISHED
    if col == ts.vintage_partition_col:
        # the knowledge col IS a projected partition: compare NATIVELY in the partition's own value
        # format — a CAST here is semantically a no-op on a string column but makes the predicate
        # non-sargable, so Athena enumerates the whole projected grid (silver_wasde: 19.5K daily
        # candidates over 461 real monthly partitions — the WASDE arm of the Jul-2026 LIST storm).
        return f"{col} <= {_q(_fmt_pdate(asof, ts.vintage_partition_format))}"
    return f"{_dcmp(ts, col)} <= {_q(asof)}"                  # DP-5: substr-normalized when col is a timestamp date


def _order_col(ts: TableSpec) -> Optional[str]:
    """The chronological ordering expression (date, else year*100+month)."""
    if ts.date_col:
        return ts.date_col
    if ts.year_col and ts.month_col:
        return f"({ts.year_col} * 100 + {ts.month_col})"
    return None


def _extras(ts: TableSpec) -> list[tuple[str, str]]:
    """(expr, alias) columns surfaced alongside the value so every row is SELF-IDENTIFYING (which period, when
    published) — a series row that carries only a bare value is unattributable and gets misread."""
    out: list[tuple[str, str]] = []
    if ts.knowledge_date_col:
        out.append((_sel_date(ts, ts.knowledge_date_col), "knowledge_date"))   # DP-5: normalize a timestamp date
    if ts.date_col and ts.date_col != ts.knowledge_date_col:
        out.append((_sel_date(ts, ts.date_col), "data_date"))                  # DP-5: normalize a timestamp date
    if ts.provenance_col:                                # DP-2: revision/vintage stamp -> citation meta
        out.append((ts.provenance_col, "revision_stamp"))
    if ts.period_col and ts.period_col not in (ts.knowledge_date_col, ts.date_col):
        out.append((ts.period_col, "period"))
    if ts.country_col:                                   # without it a multi-country row is unattributable
        out.append((ts.country_col, "country"))
    if ts.year_col:
        out.append((ts.year_col, "year"))
    if ts.month_col:
        out.append((ts.month_col, "month"))
    if ts.unit_col:
        out.append((ts.unit_col, "unit"))
    if ts.shape == "tall" and ts.metric_col:
        out.append((ts.metric_col, "metric"))
    return out


# ISO 'YYYY-MM-DD' month field -> the full English month name silver stores in projection_month
# (usda_wasde_silver._norm_month emits exactly these Title-case names, else ''). The mapping is used
# BYTE-IDENTICALLY by the SQL emitter and the Python oracle so a release-relative rank agrees on both.
_MONTH_NUM_TO_NAME = {"01": "January", "02": "February", "03": "March", "04": "April",
                      "05": "May", "06": "June", "07": "July", "08": "August",
                      "09": "September", "10": "October", "11": "November", "12": "December"}


def _release_month_name_sql(date_col: str) -> str:
    """A backend-portable expression rendering an ISO 'YYYY-MM-DD' date column's MONTH to its full English
    month name — substr + a literal CASE, NO engine-specific date function (date_format/to_char diverge
    Presto-vs-Postgres). substr(col,6,2) yields 'MM' on Presto, Postgres AND sqlite (all 1-indexed), so the
    ONE emitted SQL string sorts identically on both serving backends and in the sqlite execution tests."""
    whens = " ".join(f"WHEN '{k}' THEN '{v}'" for k, v in _MONTH_NUM_TO_NAME.items())
    return f"CASE substr({date_col}, 6, 2) {whens} ELSE '' END"


def _release_month_name(iso: str) -> str:
    """The Python-oracle twin of _release_month_name_sql: 'YYYY-MM-DD' -> full English month name (or '')."""
    return _MONTH_NUM_TO_NAME.get(str(iso or "")[5:7], "")


def _vintage_tiebreak_order(ts: TableSpec) -> str:
    """Extra ORDER BY terms appended (after ``knowledge_date DESC``) to the latest-vintage ROW_NUMBER window so
    the per-grain pick is a DETERMINISTIC TOTAL order — identical on Athena and the pg mirror BY CONSTRUCTION
    (one SQL string; explicit directions + NULLS so neither engine's default null placement can diverge). The
    tiebreak columns are string in silver (see the generated DDL) and TEXT COLLATE "C" in the pg mirror ==
    Presto byte-order varchar comparison, so the sort is byte-identical on both backends.

    Returns "" for tables without a ``vintage_tiebreak`` spec -> the emitted SQL is byte-identical to before.

    silver_wasde: early-era releases (1985-1999) carry MULTIPLE estimate_role rows per numbers grain at ONE
    release_date; without a tiebreak the ROW_NUMBER tie is engine-arbitrary (the F2 pg-parity break). The role
    rank makes the MOST-SETTLED figure win (actual < estimate < projection). The modern US two-vintage shape
    carries TWO projection rows per grain at one release (current-month + prior-month columns); the CURRENT
    projection == the RELEASE month, so a `match_release_month` term ranks THAT row first — release-relative,
    because a static month order picks the wrong row at the Dec→Jan wrap (probed present: 1549 grains). Then
    source_table_id ASC is the final total-order tiebreak. ``dir`` is honored on BOTH the plain and role_order
    branches, mirroring _vintage_cmp (the ORACLE-DIR contract)."""
    terms: list[str] = []
    for t in ts.vintage_tiebreak:
        if t.match_release_month:                            # release-relative: current-month projection wins
            mexpr = _release_month_name_sql(t.match_release_month)
            terms.append(f"CASE WHEN {t.col} = {mexpr} THEN 0 ELSE 1 END ASC")
        elif t.role_order:                                   # CASE rank: listed-first value ranks 0 (wins)
            whens = " ".join(f"WHEN {_q(v)} THEN {i}" for i, v in enumerate(t.role_order))
            terms.append(f"CASE {t.col} {whens} ELSE {len(t.role_order)} END {t.dir.upper()}")
        else:
            frag = f"{t.col} {t.dir.upper()}"
            if t.nulls:
                frag += f" NULLS {t.nulls.upper()}"
            terms.append(frag)
    return "".join(f", {t}" for t in terms)


def _vintage_cmp(ts: TableSpec):
    """A comparator mirroring the latest-vintage ROW_NUMBER ORDER BY (``knowledge_date`` DESC, then the spec's
    ``vintage_tiebreak`` terms) so apply_pit_filter picks the SAME per-grain winner build_sql's SQL does — the
    anti-leakage oracle stays in lockstep with the tiebreak fix. ``cmp(a, b) < 0`` means a sorts BEFORE b (a
    wins). Tiebreak columns compare AS TEXT (their silver type), matching the SQL on both backends."""
    kcol = ts.knowledge_date_col

    def cmp(a: dict, b: dict) -> int:
        ka, kb = str(a.get(kcol) or ""), str(b.get(kcol) or "")
        if ka != kb:
            return -1 if ka > kb else 1                      # knowledge_date DESC: newer vintage wins
        for t in ts.vintage_tiebreak:
            if t.match_release_month:                        # release-relative rank: current-month wins (rank 0)
                ra = 0 if str(a.get(t.col) or "") == _release_month_name(a.get(t.match_release_month)) else 1
                rb = 0 if str(b.get(t.col) or "") == _release_month_name(b.get(t.match_release_month)) else 1
                if ra != rb:
                    return -1 if ra < rb else 1              # ASC, no dir: byte-identical to the SQL CASE
                continue
            va, vb = a.get(t.col), b.get(t.col)
            if t.role_order:                                 # role rank: listed-first value (rank 0) wins
                ra = t.role_order.index(va) if va in t.role_order else len(t.role_order)
                rb = t.role_order.index(vb) if vb in t.role_order else len(t.role_order)
                if ra != rb:
                    c = -1 if ra < rb else 1                 # honor `dir` SYMMETRICALLY with the SQL CASE rank
                    return -c if t.dir == "desc" else c      # (the ORACLE-DIR trap: SQL honored dir, oracle didn't)
                continue
            an, bn = (va is None or va == ""), (vb is None or vb == "")
            if an or bn:                                     # explicit NULLS placement (default last)
                if an and bn:
                    continue
                last = (t.nulls or "last") == "last"
                return (1 if last else -1) if an else (-1 if last else 1)
            sa, sb = str(va), str(vb)                        # TEXT compare (byte order == COLLATE "C" == Presto)
            if sa != sb:
                c = 1 if sa > sb else -1
                return -c if t.dir == "desc" else c
        return 0
    return cmp


def _total_order(extras: list[tuple[str, str]], include_country: bool = True) -> str:
    """A deterministic TOTAL ordering over the aliased output columns, chronology first. Without one,
    multi-row results under LIMIT are ENGINE-ARBITRARY — Athena and the pg mirror legitimately return
    different row samples for the same SQL (found by the pg-parity gate, 2026-07-05). Output aliases are
    valid ORDER BY targets on both Presto and Postgres.

    ESR_DESTINATION_PLAN S1 [HIGH]: ``country`` participates in the tiebreak ONLY when a destination
    filter is active (``include_country`` = ``spec.country is not None``). Declaring silver_esr's
    ``country_col`` surfaces a ``country`` alias that would otherwise slot into the LIMIT-1 tiebreak of
    the ``agg=latest`` vintage branch (the LIVE esr_exports cascade leg, country_rule=none) and silently
    flip the freshest-week pick to the lexicographically-smallest ``country_code`` row — a different value
    for the national leg. Dropping ``country`` on the no-country path keeps that leg's value byte-stable;
    when a destination IS named the alias participates (a single scoped row anyway)."""
    have = [a for _, a in extras]
    pri = ["data_date", "period", "year", "month", "country", "metric", "knowledge_date", "unit"]
    if not include_country:
        pri = [p for p in pri if p != "country"]
    return ", ".join([a for a in pri if a in have] + ["value"])


def build_sql(spec: NumberQuery, ts: Optional[TableSpec] = None, *, db: str = ATHENA_DB) -> str:
    """Compile a NumberQuery to leakage-safe Athena SQL. The as-of guard is injected unconditionally; for
    `vintage` tables it also collapses to the LATEST vintage published on/before asof (as-known-at-asof)."""
    ts = ts or load_registry().get(spec.table)
    # SEAM-C LEVELS-ONLY GUARD: a roll-spliced continuous FRONT-MONTH settle series (silver_futures_prices)
    # has NO PIT-safe cross-date delta -- the splice between expiries contaminates any change/window/curve
    # read. Only a single-date agg=latest level is compilable; any other agg OR any period_start/period_end
    # window RAISES deterministically (defense-in-depth beside the agent's phrasing-based decline routes --
    # the Conventions bullet is discipline, this is enforcement, mirroring the DP-1 guard below).
    if getattr(ts, "levels_only", False) and (spec.agg != "latest" or spec.period_start or spec.period_end):
        raise ValueError(f"table {spec.table} is levels-only (roll-spliced continuous front-month settle): "
                         f"only agg=latest single-date levels are served; a change/window/series/curve read "
                         f"is not point-in-time-safe across roll boundaries")
    # DP-1 GUARD: a metric carrying unit_overrides is keyed by commodity for its unit (avg_farm_price). A
    # commodity-less query would serve unattributable blank-unit rows -- RAISE deterministically (the
    # Conventions bullet is discipline; this is enforcement).
    _m = ts.metrics.get(spec.metric)
    if _m is not None and getattr(_m, "unit_overrides", None) and spec.commodity is None:
        raise ValueError(f"metric {spec.table}.{spec.metric} carries unit_overrides but the query has no "
                         f"commodity -- a commodity-less farm-price query serves unattributable blank-unit rows")
    val = _value_expr(spec, ts)
    extras = _extras(ts)
    inc_country = spec.country is not None            # ESR S1: country enters _total_order only when a
    #                                                   destination filter is active (national path stays stable)
    where = " AND ".join(_filters(spec, ts) + [_guard(spec, ts)])
    sel = f"{val} AS value" + "".join(f", {e} AS {a}" for e, a in extras)
    order = _order_col(ts)

    def _agg(sql: str) -> str:
        fn = {"mean": "avg"}.get(spec.agg, spec.agg)
        # subquery ALIAS: optional on Athena/Presto, REQUIRED by Postgres — one SQL string serves both backends
        return f"SELECT {fn}(value) AS value FROM ({sql}) AS _v"

    table = ts.athena_table or spec.table                     # agent-facing id -> physical Glue table
    if ts.knowledge_semantics == "vintage":
        # as-known: rank vintages within the identity group, keep the newest published on/before asof
        part = ", ".join(ts.group_cols()) or "1"
        inner = (f"SELECT {sel}, ROW_NUMBER() OVER (PARTITION BY {part} "
                 f"ORDER BY {ts.knowledge_date_col} DESC{_vintage_tiebreak_order(ts)}) AS _rn "
                 f"FROM {db}.{table} WHERE {where}")
        outcols = "value" + "".join(f", {a}" for _, a in extras)
        base = f"SELECT {outcols} FROM ({inner}) AS _v WHERE _rn = 1"   # alias: PG-required, Athena-accepted
        if spec.agg in ("sum", "mean", "max", "min"):
            base = _agg(base)
        elif spec.agg == "latest" and order:
            # a vintage table WITH a chronological data axis (ESR week_ending_date under the BF-W2
            # per-week semantics flip): 'latest' keeps its single-freshest-observation contract AFTER
            # the vintage dedup -- the ESR pace leg's freshest-week lock (D-W3.1/C2). Without this the
            # flip silently turns agg=latest into a full-window series. Tables with no order col
            # (PSD/WASDE: no date_col) keep the plain deduped-set shape below, unchanged.
            # The dedup subquery exposes ALIASES only -- order by the chronological axis's alias,
            # never the raw column: Athena AND Postgres both reject the raw name in the outer scope
            # (COLUMN_NOT_FOUND, live-caught at the BF-W2 step-11 serving smoke gate).
            alias = dict(extras)
            order_alias = alias[ts.date_col] if ts.date_col else "(year * 100 + month)"
            return base + f" ORDER BY {order_alias} DESC, {_total_order(extras, inc_country)} LIMIT 1"
        else:
            base += f" ORDER BY {_total_order(extras, inc_country)}"
        return base + f" LIMIT {int(spec.limit)}"

    # non-vintage (ingest / data_date / year_month)
    base = f"SELECT {sel} FROM {db}.{table} WHERE {where}"
    if spec.agg in ("sum", "mean", "max", "min"):
        return _agg(base) + f" LIMIT {int(spec.limit)}"
    if spec.agg == "latest" and order:                        # the single most-recent observation on/before asof
        return base + f" ORDER BY {order} DESC, {_total_order(extras, inc_country)} LIMIT 1"
    base += f" ORDER BY {_total_order(extras, inc_country)}"  # series/default: chronological + total tiebreak
    return base + f" LIMIT {int(spec.limit)}"


def apply_pit_filter(rows: list[dict], spec: NumberQuery, ts: TableSpec) -> list[dict]:
    """Pure-Python reference for the SAME point-in-time semantics build_sql encodes (test oracle + client
    fallback). Filters by identity/scope, drops anything not yet known at asof, and for `vintage` keeps only the
    latest vintage per identity group."""
    kcol = ts.knowledge_col()
    ym = _asof_ym(spec.asof) if ts.knowledge_semantics == "year_month" else None
    guard_asof = _pub_lagged_asof(spec.asof, ts.publication_lag_days)   # publication-lag shift; mirrors _guard
    if kcol and kcol == ts.vintage_partition_col:
        # the knowledge col carries the PARTITION's value format (ESR as_of_date = YYYYMMDD): compare the
        # cutoff in that format, exactly as _guard does — an ISO-vs-YYYYMMDD lexical compare is silently
        # FALSE for every row (the R2 trap), so the oracle would diverge from the SQL it verifies.
        guard_asof = _fmt_pdate(guard_asof, ts.vintage_partition_format)
    part_country = (_resolved_country(spec, ts)                          # country-PARTITION identity resolved the
                    if ts.country_col and ts.country_col in ts.partition_cols else None)  # SAME way as build_sql
    cf = _metric_commodity_filters(spec, ts)                             # A3 per-commodity row constraints (mirror
    cf_sets = {col: {str(v) for v in vals} for col, vals in cf.items()}  # of build_sql's `col IN (...)` emit)
    esr_codes: Optional[set[str]] = None                                 # ESR destination: resolved str codes for
    if ts.country_name_ref and spec.country:                             # spec.country (mirrors _esr_country_codes;
        from leviathan.graphrag.numbers.esr_destinations import load_esr_destinations  # EMPTY set == unresolved ->
        esr_codes = {str(c) for c in load_esr_destinations().resolve_codes(spec.country)}  # fail CLOSED (no row kept)

    def keep(r: dict) -> bool:
        if "region" in ts.partition_cols:
            val = spec.region or default_region(spec.commodity or "")
            if val and str(r.get("region")) != str(val):
                return False
        if spec.commodity and ts.commodity_col and str(r.get(ts.commodity_col)) != str(spec.commodity):
            return False
        if ts.country_col and ts.country_col in ts.partition_cols:       # country is a partition: compare the
            if part_country and str(r.get(ts.country_col)) != str(part_country):   # RESOLVED value (D-W0.1 lockstep)
                return False
        elif ts.country_col and ts.country_col in cf_sets:               # A3: a row_filter on the country_col
            if str(r.get(ts.country_col)) not in cf_sets[ts.country_col]:  # WIDENS the match (cotton region split)
                return False
        elif esr_codes is not None:                                      # ESR destination: NAME->code membership
            if str(r.get(ts.country_col)) not in esr_codes:              # (esr_codes empty == unresolved -> closed)
                return False
        elif spec.country and ts.country_col and str(r.get(ts.country_col)) != str(spec.country):
            return False
        for col, allowed in cf_sets.items():                            # A3: non-country row_filters are ADDITIONAL
            if col == ts.country_col:                                   # restrictions (soybeans unit bleed fence)
                continue
            if str(r.get(col)) not in allowed:
                return False
        if ts.shape == "tall" and ts.metric_col and str(r.get(ts.metric_col)) != str(spec.metric):
            return False
        if spec.period and ts.period_col:
            rv, pv = str(r.get(ts.period_col)), str(spec.period)
            if ts.period_sql_type == "int":
                if int(str(rv)[:4] or 0) != int(pv[:4]) + ts.period_offset:   # same label translation as build_sql
                    return False
            elif rv != pv:
                return False
        if spec.period_start and ts.date_col and _pit_dval(ts, ts.date_col, r.get(ts.date_col)) < spec.period_start:
            return False
        if spec.period_end and ts.date_col and _pit_dval(ts, ts.date_col, r.get(ts.date_col)) > spec.period_end:
            return False
        if ts.knowledge_semantics == "year_month":
            rym = int(r.get(ts.year_col)) * 100 + int(r.get(ts.month_col))
            if spec.period_start and rym < _asof_ym(spec.period_start):
                return False
            if spec.period_end and rym > _asof_ym(spec.period_end):
                return False
            return rym <= ym                                             # the leakage guard (year_month)
        kv = r.get(kcol)
        if kv is None or str(kv) == "":                                  # NULL/empty knowledge date: FAIL CLOSED —
            return False                                                 # unstamped == not-yet-visible, never
            #                                                              always-visible. Mirrors the SQL guard,
            #                                                              where `col <= asof` is NULL (=> excluded)
            #                                                              for a NULL knowledge date; the old
            #                                                              `str(None or '')`='' compared <= asof as
            #                                                              TRUE, leaking every unstamped row.
        return _pit_dval(ts, kcol, kv) <= guard_asof                     # DP-5-normalized leakage guard (date + pub lag)
    kept = [r for r in rows if keep(r)]

    if ts.knowledge_semantics == "vintage" and kept:
        # Pick the per-grain winner with the SAME total order build_sql's ROW_NUMBER uses: knowledge_date DESC,
        # then the spec's vintage_tiebreak (silver_wasde role priority). With no tiebreak this reduces to the
        # newest knowledge_date, first-seen on a tie — byte-identical to the prior behavior.
        import functools as _ft
        cmp = _vintage_cmp(ts)
        groups: dict[tuple, list[dict]] = {}
        for r in kept:
            groups.setdefault(tuple(r.get(c) for c in ts.group_cols()), []).append(r)
        kept = [min(g, key=_ft.cmp_to_key(cmp)) for g in groups.values()]
    return kept


def _apply_unit_overrides(rows: list[dict], spec: NumberQuery, ts: TableSpec) -> list[dict]:
    """DP-1 POST-FETCH (PRICE_OBSERVABILITY W1.1): a metric carrying unit_overrides has NO governed source unit
    (silver avg_farm_price's `unit` column is null / junk section-heading text). SET r["unit"] to the
    per-commodity override on EVERY returned row -- INCLUDING agg-shaped rows, which emit no extras (the agg SQL
    is SELECT avg(value) AS value FROM (...)) so a "mean farm price over 5 MYs" would otherwise cite unitless.
    Blank ("") on an unresolvable commodity beats serving the junk unit. citations.py reads r["unit"] FIRST, so
    this drives the citation unit; the choke point is Q.run (all backends flow through it)."""
    m = ts.metrics.get(spec.metric)
    ov = getattr(m, "unit_overrides", None) if m else None
    if not ov:
        return rows
    unit = ov.get(spec.commodity, "")                    # blank-on-unresolvable; build_sql already raised if None
    for r in rows:
        r["unit"] = unit
    return rows


def _apply_country_names(rows: list[dict], spec: NumberQuery, ts: TableSpec) -> list[dict]:
    """ESR_DESTINATION_PLAN W1.3.3 POST-FETCH: render the row's raw ``country_code`` (surfaced as the
    ``country`` extra alias) to its display name, so a citation/answer shows 'China', not '5700'. The code
    comes back as a STRING on BOTH backends (Athena VarCharValue / pg _stringify), so display() is
    str-normalized (the folded S2 int-key/string-value reconciliation); an unmapped code falls back to the
    bare code string (never raises -- the reference-lint makes a probe-present-but-unmapped code a hard
    failure). Only for a card with country_name_ref; agg=sum rows carry no ``country`` extra (nothing to
    render). Every other table is byte-identical."""
    if not ts.country_name_ref:
        return rows
    from leviathan.graphrag.numbers.esr_destinations import load_esr_destinations
    dst = load_esr_destinations()
    for r in rows:
        if r.get("country") is not None:
            r["country"] = dst.display(r["country"])
    return rows


def run(spec: NumberQuery, *, query_fn=None, db: str = ATHENA_DB) -> list[dict]:
    """Execute on the active backend (or an injected query_fn(sql)->rows for tests/session-cache wrappers).
    Returns rows as list[dict]. The pg mirror's schema is NAMED like the Athena db, so the compiled SQL is
    backend-agnostic -- routing is purely a choice of executor. POST-FETCH: apply DP-1 unit_overrides so every
    returned row (agg-shaped rows included) carries the correct per-commodity unit."""
    ts = load_registry().get(spec.table)
    sql = build_sql(spec, ts, db=db)
    rows = query_fn(sql) if query_fn is not None else default_query_fn(db=db)(sql)
    rows = _apply_unit_overrides(rows, spec, ts)
    return _apply_country_names(rows, spec, ts)              # ESR: raw country_code -> display name (post-fetch)


def default_query_fn(db: str = ATHENA_DB):
    """The executor for the ACTIVE numbers backend: the RDS pg mirror (with per-request Athena fallback on
    the SAME SQL) when GRAPHRAG_NUMBERS_BACKEND=pg, else Athena. This is what callers should wrap (the
    session SQL-keyed cache does) so backend routing survives the wrapping."""
    from leviathan.graphrag.numbers import pgnumbers
    if pgnumbers.enabled():
        return pgnumbers.query_fn()
    return athena_query_fn(db=db)


def athena_query_fn(db: str = ATHENA_DB):
    """The Athena executor as an injectable query_fn(sql)->rows — lets callers WRAP the real Athena
    path (e.g. the session-scoped SQL result cache) instead of only replacing it in tests."""
    import boto3

    from leviathan.common import config
    config.load_env()
    client = boto3.client("athena", region_name="us-east-1")
    return lambda sql: _athena(client, sql, db)


_THROTTLE = ("TooManyRequestsException", "ThrottlingException", "SlowDown", "RequestLimitExceeded")


def _retry(fn, tries: int = 6):
    """Exponential backoff on Athena/S3 throttles (the results bucket 503s under burst)."""
    import time

    from botocore.exceptions import ClientError
    for i in range(tries):
        try:
            return fn()
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if i < tries - 1 and (code in _THROTTLE or "503" in str(e)):
                time.sleep(1.5 * (2 ** i))
                continue
            raise


# Per-process Athena telemetry — the S3-LIST-storm tripwire. Planning time IS the projection-enumeration
# signature (the Jul-2026 storm queries planned for 26-31s while scanning KBs); the eval report prints a
# panel over this and warns when p95 planning exceeds ~3s.
STATS: list[dict] = []


def reset_stats() -> None:
    STATS.clear()


def stats_summary() -> dict:
    """{n, planning_ms p50/p95/max, exec_ms_max, scanned_mb} over the queries run since reset_stats()."""
    if not STATS:
        return {"n": 0}
    plan = sorted(s.get("planning_ms", 0) for s in STATS)

    def pct(p: float) -> int:
        return int(plan[min(len(plan) - 1, int(p * (len(plan) - 1)))])
    return {"n": len(STATS), "planning_p50_ms": pct(0.50), "planning_p95_ms": pct(0.95),
            "planning_max_ms": plan[-1], "exec_ms_max": max(s.get("total_ms", 0) for s in STATS),
            "scanned_mb": round(sum(s.get("scanned_bytes", 0) for s in STATS) / 1e6, 2)}


def _athena(client, sql: str, db: str) -> list[dict]:
    import os
    import time
    bucket = os.environ.get("LEVIATHAN_BUCKET", "leviathan-dev-shahem-001")
    deadline = time.time() + float(os.environ.get("ATHENA_QUERY_TIMEOUT_S", "180"))
    qid = _retry(lambda: client.start_query_execution(
        QueryString=sql, QueryExecutionContext={"Database": db},
        ResultConfiguration={"OutputLocation": f"s3://{bucket}/athena-results/"}))["QueryExecutionId"]
    while True:
        qe = _retry(lambda: client.get_query_execution(QueryExecutionId=qid))["QueryExecution"]
        st = qe["Status"]
        if st["State"] == "SUCCEEDED":
            break
        if st["State"] in ("FAILED", "CANCELLED"):
            raise RuntimeError(f"Athena {st['State']}: {st.get('StateChangeReason','')}\nSQL: {sql[:400]}")
        if time.time() > deadline:
            # a query still planning/running after the deadline is almost certainly enumerating a
            # projection (the LIST-storm class) — CANCEL it so it cannot keep billing S3 LISTs, and fail
            # loudly instead of quietly retrying (retries multiply the storm).
            try:
                client.stop_query_execution(QueryExecutionId=qid)
            except Exception:  # noqa: BLE001
                pass
            raise RuntimeError(f"Athena query cancelled after {os.environ.get('ATHENA_QUERY_TIMEOUT_S', '180')}s "
                               f"timeout (enumeration-class query? check partition predicates)\nSQL: {sql[:400]}")
        time.sleep(2)
    s = qe.get("Statistics", {})
    STATS.append({"planning_ms": s.get("QueryPlanningTimeInMillis", 0),
                  "total_ms": s.get("TotalExecutionTimeInMillis", 0),
                  "scanned_bytes": s.get("DataScannedInBytes", 0)})
    res = _retry(lambda: client.get_query_results(QueryExecutionId=qid, MaxResults=1000))
    hdr = [c["Name"] for c in res["ResultSet"]["ResultSetMetadata"]["ColumnInfo"]]
    return [{hdr[i]: c.get("VarCharValue", "") for i, c in enumerate(row["Data"])}
            for row in res["ResultSet"]["Rows"][1:]]
