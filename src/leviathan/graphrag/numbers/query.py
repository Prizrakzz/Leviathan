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


def _partition_filters(spec: NumberQuery, ts: TableSpec) -> list[str]:
    """Static equalities for EVERY injected-projection partition (Athena CONSTRAINT_VIOLATION otherwise).
    region defaults to the commodity's primary station; country derives from the region's geography block
    (values are snake_case there — 'united_states'); commodity must be given. When the region IS in the
    geographies map, the map's country is AUTHORITATIVE over the model-supplied one (the region is the
    finer key, and the model's surface form may not be a real partition value)."""
    geo = _geo(spec.commodity) if spec.commodity else {}
    w: list[str] = []
    region = spec.region or (geo.get("_primary") or (None, None))[1]
    for col in ts.partition_cols:
        if col == ts.commodity_col:
            if not spec.commodity:
                raise ValueError(f"table {ts.id} requires commodity (partition column)")
            continue                                          # emitted by the regular commodity filter
        if col == ts.country_col:
            val = geo.get(region) or _canon_country(spec.country)
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
    if spec.commodity and ts.commodity_col:
        w.append(f"{ts.commodity_col} = {_q(spec.commodity)}")
    if spec.country and ts.country_col and ts.country_col not in ts.partition_cols:
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
        w.append(f"{_dcol(ts.date_col)} >= {_q(spec.period_start)}")
    if ts.date_col and spec.period_end:
        w.append(f"{_dcol(ts.date_col)} <= {_q(spec.period_end)}")
    if ts.knowledge_semantics == "year_month" and (spec.period_start or spec.period_end):
        ym = f"({ts.year_col} * 100 + {ts.month_col})"          # window monthly (year_month) tables by 'YYYY-MM'
        if spec.period_start:
            w.append(f"{ym} >= {_asof_ym(spec.period_start)}")
        if spec.period_end:
            w.append(f"{ym} <= {_asof_ym(spec.period_end)}")
    return w


def _asof_ym(asof: str) -> int:
    return int(asof[:4]) * 100 + int(asof[5:7])              # 'YYYY-MM-DD' -> YYYYMM integer


def _guard(spec: NumberQuery, ts: TableSpec) -> str:
    """The as-of predicate that is ALWAYS present — the leakage guard."""
    if ts.knowledge_semantics == "year_month":
        if not (ts.year_col and ts.month_col):
            raise ValueError(f"table {ts.id} year_month semantics needs year_col + month_col")
        return f"({ts.year_col} * 100 + {ts.month_col}) <= {_asof_ym(spec.asof)}"
    col = ts.knowledge_col()
    if not col:
        raise ValueError(f"table {ts.id} has no knowledge/date column to anchor the as-of guard")
    return f"{_dcol(col)} <= {_q(spec.asof)}"


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
        out.append((ts.knowledge_date_col, "knowledge_date"))
    if ts.date_col and ts.date_col != ts.knowledge_date_col:
        out.append((ts.date_col, "data_date"))
    if ts.period_col and ts.period_col not in (ts.knowledge_date_col, ts.date_col):
        out.append((ts.period_col, "period"))
    if ts.year_col:
        out.append((ts.year_col, "year"))
    if ts.month_col:
        out.append((ts.month_col, "month"))
    if ts.unit_col:
        out.append((ts.unit_col, "unit"))
    if ts.shape == "tall" and ts.metric_col:
        out.append((ts.metric_col, "metric"))
    return out


def build_sql(spec: NumberQuery, ts: Optional[TableSpec] = None, *, db: str = ATHENA_DB) -> str:
    """Compile a NumberQuery to leakage-safe Athena SQL. The as-of guard is injected unconditionally; for
    `vintage` tables it also collapses to the LATEST vintage published on/before asof (as-known-at-asof)."""
    ts = ts or load_registry().get(spec.table)
    val = _value_expr(spec, ts)
    extras = _extras(ts)
    where = " AND ".join(_filters(spec, ts) + [_guard(spec, ts)])
    sel = f"{val} AS value" + "".join(f", {e} AS {a}" for e, a in extras)
    order = _order_col(ts)

    def _agg(sql: str) -> str:
        fn = {"mean": "avg"}.get(spec.agg, spec.agg)
        return f"SELECT {fn}(value) AS value FROM ({sql})"

    table = ts.athena_table or spec.table                     # agent-facing id -> physical Glue table
    if ts.knowledge_semantics == "vintage":
        # as-known: rank vintages within the identity group, keep the newest published on/before asof
        part = ", ".join(ts.group_cols()) or "1"
        inner = (f"SELECT {sel}, ROW_NUMBER() OVER (PARTITION BY {part} "
                 f"ORDER BY {ts.knowledge_date_col} DESC) AS _rn "
                 f"FROM {db}.{table} WHERE {where}")
        outcols = "value" + "".join(f", {a}" for _, a in extras)
        base = f"SELECT {outcols} FROM ({inner}) WHERE _rn = 1"
        if spec.agg in ("sum", "mean", "max", "min"):
            base = _agg(base)
        return base + f" LIMIT {int(spec.limit)}"

    # non-vintage (ingest / data_date / year_month)
    base = f"SELECT {sel} FROM {db}.{table} WHERE {where}"
    if spec.agg in ("sum", "mean", "max", "min"):
        return _agg(base) + f" LIMIT {int(spec.limit)}"
    if spec.agg == "latest" and order:                        # the single most-recent observation on/before asof
        return base + f" ORDER BY {order} DESC LIMIT 1"
    if order:                                                 # series/default: chronological
        base += f" ORDER BY {order}"
    return base + f" LIMIT {int(spec.limit)}"


def apply_pit_filter(rows: list[dict], spec: NumberQuery, ts: TableSpec) -> list[dict]:
    """Pure-Python reference for the SAME point-in-time semantics build_sql encodes (test oracle + client
    fallback). Filters by identity/scope, drops anything not yet known at asof, and for `vintage` keeps only the
    latest vintage per identity group."""
    kcol = ts.knowledge_col()
    ym = _asof_ym(spec.asof) if ts.knowledge_semantics == "year_month" else None

    def keep(r: dict) -> bool:
        if "region" in ts.partition_cols:
            val = spec.region or default_region(spec.commodity or "")
            if val and str(r.get("region")) != str(val):
                return False
        if spec.commodity and ts.commodity_col and str(r.get(ts.commodity_col)) != str(spec.commodity):
            return False
        if spec.country and ts.country_col and str(r.get(ts.country_col)) != str(spec.country):
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
        if spec.period_start and ts.date_col and str(r.get(ts.date_col)) < spec.period_start:
            return False
        if spec.period_end and ts.date_col and str(r.get(ts.date_col)) > spec.period_end:
            return False
        if ts.knowledge_semantics == "year_month":
            rym = int(r.get(ts.year_col)) * 100 + int(r.get(ts.month_col))
            if spec.period_start and rym < _asof_ym(spec.period_start):
                return False
            if spec.period_end and rym > _asof_ym(spec.period_end):
                return False
            return rym <= ym                                             # the leakage guard (year_month)
        return str(r.get(kcol) or "") <= spec.asof                       # the leakage guard (date)
    kept = [r for r in rows if keep(r)]

    if ts.knowledge_semantics == "vintage" and kept:
        best: dict[tuple, dict] = {}
        for r in kept:
            key = tuple(r.get(c) for c in ts.group_cols())
            cur = best.get(key)
            if cur is None or str(r.get(ts.knowledge_date_col)) > str(cur.get(ts.knowledge_date_col)):
                best[key] = r
        kept = list(best.values())
    return kept


def run(spec: NumberQuery, *, query_fn=None, db: str = ATHENA_DB) -> list[dict]:
    """Execute on Athena (or an injected query_fn(sql)->rows for tests). Returns rows as list[dict]."""
    sql = build_sql(spec, db=db)
    if query_fn is not None:
        return query_fn(sql)
    return athena_query_fn(db=db)(sql)


def athena_query_fn(db: str = ATHENA_DB):
    """The default executor as an injectable query_fn(sql)->rows — lets callers WRAP the real Athena
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
