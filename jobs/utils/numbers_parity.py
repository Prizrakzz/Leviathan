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
from datetime import date

from leviathan.common.config import load_env
from leviathan.common.logging import get_logger

logger = get_logger("numbers_parity")

# Small representative grid: per table one liquid commodity + a historical and a recent as-of.
# COMMODITY VALUES MUST MATCH THE SILVER DATA (verified 2026-07-05 against S3/Athena): psd/production/esr
# store CONTRACT slugs (corn_cbot); wasde stores BASE names (corn). A wrong value makes that table's panel
# VACUOUS — 0 rows == 0 rows passes without proving anything.
SAMPLE_COMMODITY = {"silver_psd": "corn_cbot", "silver_wasde": "corn", "silver_production": "corn_cbot",
                    "silver_esr": "corn_cbot", "silver_fred_fx": None, "silver_noaa_oni": None,
                    # gold_weather_z is a TALL z-table keyed by CONTRACT slug: the gold task's 'all'
                    # mode discovers commodities from silver/weather canonical partitions, which are the 31
                    # contract slugs (verified 2026-07-17: gold/weather_z/corn_cbot.parquet, commodity column
                    # == 'corn_cbot', 44,954 rows 1981-2026). The earlier 'corn' base-name sample made the
                    # panel vacuous the FIRST time the weather gate ran it live (weather-R3 red).
                    "gold_weather_z": "corn_cbot"}
# 2026 asof included because ingest-semantics tables (silver_production) were ingested in 2026 — earlier
# asofs legitimately see 0 rows (honest PIT), which would leave that panel vacuous.
ASOFS = ["2021-08-15", "2024-06-01", "2026-07-01"]
AGGS = ["latest", "series"]


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
    for tid in tables:
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
                    spec = Q.NumberQuery(table=tid, metric=metric, asof=asof, commodity=commodity,
                                         agg=agg, limit=50)
                    try:
                        sql = Q.build_sql(spec)
                    except Exception as e:  # noqa: BLE001 — spec not valid for this table (e.g. region rules)
                        lines.append(f"- SKIP {tid}.{metric} asof={asof} agg={agg}: spec invalid ({e})")
                        continue
                    total += 1
                    try:
                        a = _rows_key(athena(sql))
                    except Exception as e:  # noqa: BLE001
                        lines.append(f"- ATHENA-ERR {tid}.{metric} asof={asof} agg={agg}: {str(e)[:120]}")
                        continue
                    try:
                        p = _rows_key(pgnumbers.pg_query(sql))
                    except Exception as e:  # noqa: BLE001
                        mismatches.append(f"PG-ERR {tid}.{metric} asof={asof} agg={agg}: {str(e)[:120]}")
                        continue
                    compared[tid] = compared.get(tid, 0) + 1
                    if a or p:
                        nonempty[tid] = nonempty.get(tid, 0) + 1
                    if a == p:
                        match += 1
                    else:
                        mismatches.append(f"DIFF {tid}.{metric} asof={asof} agg={agg}: athena={a} pg={p}")
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
            from leviathan.graphrag import evidence as ev
            import boto3
            b, k = ev._parse_s3(s3uri.rstrip("/") + "/eval/numbers_pg_parity.md")
            boto3.client("s3").put_object(Bucket=b, Key=k, Body=report.encode("utf-8"))
            logger.info("report persisted to s3://%s/%s", b, k)
        except Exception as e:  # noqa: BLE001
            logger.warning("s3 persist failed: %s", e)
    return 0 if not mismatches else 1


if __name__ == "__main__":
    raise SystemExit(main())
