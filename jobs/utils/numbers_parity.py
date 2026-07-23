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
                    # holds CONTRACT slugs via _MARKET_TO_SLUG (raw_to_bronze/cftc_cot.py:55-56) -- corn_cbot,
                    # NOT bare 'corn' (which matches zero rows = the gold_weather_z vacuous-panel trap; the
                    # EMPTY-PANEL guard would catch it loudly, but the RIGHT sample is corn_cbot).
                    "silver_cot": "corn_cbot",
                    # WIRING WAVE-1 (2026-07-23): silver_noaa_iod has NO commodity axis (global IOD state) ->
                    # None, like noaa_oni/fred_fx/pink_sheet; the wide sampler takes its 2 served metrics.
                    # silver_conab_coffee's commodity_col is `commodity` = arabica_coffee|robusta_coffee (NOT
                    # a contract slug); arabica_coffee is the headline variety (a wrong sample -> vacuous
                    # panel, caught loudly by EMPTY-PANEL). safra 2023+ only, so the 2021 asof legitimately
                    # sees 0 rows -- non-empty at the 2024/2026 asofs. silver_sagis_weekly_exports is NOT in
                    # the grid this wave (Card C BLOCKED, not wired into the registry).
                    "silver_noaa_iod": None,
                    "silver_conab_coffee": "arabica_coffee",
                    # SEAM C (futures v1.5-lite, whitelisted 2026-07-23): commodity_col is leviathan_slug
                    # holding continuous front-month CONTRACT slugs -- corn_cbot is the liquid probe. The card
                    # is levels-only, so the `series` grid legs SKIP (build_sql rejects non-latest) and the
                    # `latest` legs at each asof carry the panel; bare 'corn' would match zero rows.
                    "silver_futures_prices": "corn_cbot"}
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
