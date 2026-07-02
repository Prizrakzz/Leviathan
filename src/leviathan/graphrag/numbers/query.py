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
    period: Optional[str] = None                     # marketing_year / year value (per the table's period format)
    period_start: Optional[str] = None               # date-grained window start (weather / exports)
    period_end: Optional[str] = None                 # date-grained window end
    agg: Literal["latest", "series", "sum", "mean", "max", "min"] = "latest"
    limit: int = 5000


def _q(v) -> str:                                    # single-quote-safe SQL literal
    return "'" + str(v).replace("'", "''") + "'"


def _value_expr(spec: NumberQuery, ts: TableSpec) -> str:
    return spec.metric if ts.shape == "wide" else (ts.value_col or "value")


def _filters(spec: NumberQuery, ts: TableSpec) -> list[str]:
    """The identity/scope predicates (NOT the as-of guard)."""
    w: list[str] = []
    if spec.commodity and ts.commodity_col:
        w.append(f"{ts.commodity_col} = {_q(spec.commodity)}")
    if spec.country and ts.country_col:
        w.append(f"{ts.country_col} = {_q(spec.country)}")
    if ts.shape == "tall" and ts.metric_col:
        w.append(f"{ts.metric_col} = {_q(spec.metric)}")
    if spec.period and ts.period_col:
        w.append(f"{ts.period_col} = "
                 + (str(int(str(spec.period)[:4])) if ts.period_sql_type == "int" else _q(spec.period)))
    if ts.date_col and spec.period_start:
        w.append(f"{ts.date_col} >= {_q(spec.period_start)}")
    if ts.date_col and spec.period_end:
        w.append(f"{ts.date_col} <= {_q(spec.period_end)}")
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
    return f"{col} <= {_q(spec.asof)}"


def _order_col(ts: TableSpec) -> Optional[str]:
    """The chronological ordering expression (date, else year*100+month)."""
    if ts.date_col:
        return ts.date_col
    if ts.year_col and ts.month_col:
        return f"({ts.year_col} * 100 + {ts.month_col})"
    return None


def _extras(ts: TableSpec) -> list[tuple[str, str]]:
    """(expr, alias) provenance columns surfaced alongside the value."""
    out: list[tuple[str, str]] = []
    if ts.knowledge_date_col:
        out.append((ts.knowledge_date_col, "knowledge_date"))
    if ts.date_col and ts.date_col != ts.knowledge_date_col:
        out.append((ts.date_col, "data_date"))
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
        if ts.knowledge_semantics == "year_month":                       # the leakage guard (year_month)
            return int(r.get(ts.year_col)) * 100 + int(r.get(ts.month_col)) <= ym
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
