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
    leaking a future value.)"""
    return f"CAST({col} AS varchar)"


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


def _partition_filters(spec: NumberQuery, ts: TableSpec) -> list[str]:
    """Static equalities for EVERY injected-projection partition (Athena CONSTRAINT_VIOLATION otherwise).
    region defaults to the commodity's primary station; country derives from the region's geography block
    (values are snake_case there — 'united_states'); commodity must be given."""
    geo = _geo(spec.commodity) if spec.commodity else {}
    w: list[str] = []
    region = spec.region or (geo.get("_primary") or (None, None))[1]
    for col in ts.partition_cols:
        if col == ts.commodity_col:
            if not spec.commodity:
                raise ValueError(f"table {ts.id} requires commodity (partition column)")
            continue                                          # emitted by the regular commodity filter
        if col == ts.country_col:
            val = _snake(spec.country) if spec.country else geo.get(region)
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
    if spec.commodity and ts.commodity_col:
        w.append(f"{ts.commodity_col} = {_q(spec.commodity)}")
    if spec.country and ts.country_col and ts.country_col not in ts.partition_cols:
        w.append(f"{ts.country_col} = {_q(spec.country)}")
    if ts.shape == "tall" and ts.metric_col:
        w.append(f"{ts.metric_col} = {_q(spec.metric)}")
    if spec.period and ts.period_col:
        w.append(f"{ts.period_col} = "
                 + (str(int(str(spec.period)[:4])) if ts.period_sql_type == "int" else _q(spec.period)))
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

    if ts.knowledge_semantics == "vintage":
        # as-known: rank vintages within the identity group, keep the newest published on/before asof
        part = ", ".join(ts.group_cols()) or "1"
        inner = (f"SELECT {sel}, ROW_NUMBER() OVER (PARTITION BY {part} "
                 f"ORDER BY {ts.knowledge_date_col} DESC) AS _rn "
                 f"FROM {db}.{spec.table} WHERE {where}")
        outcols = "value" + "".join(f", {a}" for _, a in extras)
        base = f"SELECT {outcols} FROM ({inner}) WHERE _rn = 1"
        if spec.agg in ("sum", "mean", "max", "min"):
            base = _agg(base)
        return base + f" LIMIT {int(spec.limit)}"

    # non-vintage (ingest / data_date / year_month)
    base = f"SELECT {sel} FROM {db}.{spec.table} WHERE {where}"
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
                if int(str(rv)[:4] or 0) != int(pv[:4]):
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
    import boto3
    from leviathan.common import config
    config.load_env()
    client = boto3.client("athena", region_name="us-east-1")
    return _athena(client, sql, db)


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


def _athena(client, sql: str, db: str) -> list[dict]:
    import os
    import time
    bucket = os.environ.get("LEVIATHAN_BUCKET", "leviathan-dev-shahem-001")
    qid = _retry(lambda: client.start_query_execution(
        QueryString=sql, QueryExecutionContext={"Database": db},
        ResultConfiguration={"OutputLocation": f"s3://{bucket}/athena-results/"}))["QueryExecutionId"]
    while True:
        st = _retry(lambda: client.get_query_execution(QueryExecutionId=qid))["QueryExecution"]["Status"]
        if st["State"] == "SUCCEEDED":
            break
        if st["State"] in ("FAILED", "CANCELLED"):
            raise RuntimeError(f"Athena {st['State']}: {st.get('StateChangeReason','')}\nSQL: {sql[:400]}")
        time.sleep(2)
    res = _retry(lambda: client.get_query_results(QueryExecutionId=qid, MaxResults=1000))
    hdr = [c["Name"] for c in res["ResultSet"]["ResultSetMetadata"]["ColumnInfo"]]
    return [{hdr[i]: c.get("VarCharValue", "") for i, c in enumerate(row["Data"])}
            for row in res["ResultSet"]["Rows"][1:]]
