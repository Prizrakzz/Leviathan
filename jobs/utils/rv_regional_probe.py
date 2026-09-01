"""RV-REGIONAL census probes P1-P9 (regional-RV sitting, design v2 section D) -- pg-only, $0.

Runs IN-VPC on the evidence jobdef (the laptop cannot reach the RDS: not publicly accessible, no
SSM tunnel target since the MLflow EC2 retired -- measured 2026-08-29). Reads silver_psd and
silver_futures_eod through the pg mirror (schema = pgnumbers.SCHEMA), never Athena. Writes the
artifact JSON to EVIDENCE_S3 (`probes/rv_regional_probe_<asof>.json`) and prints it to the log --
the banked artifact becomes the census pin (the rv_slug_probe precedent).

    # in-VPC (Batch containerOverrides command):
    jobs/utils/rv_regional_probe.py --asof 2026-08-29

Probes (design v2 sec D): P1 su_ratio MY sets both scopes; P2 EU aggregate titles per era;
P2b France; P3 NULL density; P4 (BLOCKING) the native su_ratio column's SCALE; P5 the series-read
shape through the REAL query path; P6 exports_mt; P7 the directional back-test; P8 MATIF EOD first
obs; P9 the literal US title.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import psycopg

sys.path.insert(0, "src")
from leviathan.graphrag import pgstore  # noqa: E402
from leviathan.graphrag.numbers import pgnumbers  # noqa: E402

KC, MATIF = "hard_red_winter_wheat_kcbt", "french_wheat_matif"
US, EU = "United States", "European Union"
SCHEMA = pgnumbers.SCHEMA


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--asof", default="2026-08-29")
    args = ap.parse_args()
    assert os.environ.get("EVIDENCE_PG_DSN"), "rv_regional_probe requires EVIDENCE_PG_DSN"
    conn = psycopg.connect(pgstore.dsn(), autocommit=True)
    out: dict = {"asof": args.asof, "probes": {}}

    def q(sql, params=()):
        with conn.cursor() as cur:
            cur.execute(sql.replace("silver_psd", f"{SCHEMA}.silver_psd")
                           .replace("silver_futures_eod", f"{SCHEMA}.silver_futures_eod"), params)
            return cur.fetchall()

    def year_set(slug, country, col):
        rows = q("SELECT DISTINCT market_year FROM silver_psd WHERE leviathan_slug=%s AND "
                 f"country=%s AND {col} IS NOT NULL ORDER BY market_year", (slug, country))
        return sorted(int(r[0]) for r in rows)

    # P1
    p1 = {f"{s}@{c}": year_set(s, c, "su_ratio") for s, c in ((KC, US), (MATIF, EU))}
    sa, sb = set(p1[f"{KC}@{US}"]), set(p1[f"{MATIF}@{EU}"])
    out["probes"]["P1"] = {"sets": {k: v for k, v in p1.items()}, "shared": sorted(sa & sb)}

    # P2
    rows = q("SELECT country, MIN(market_year), MAX(market_year), COUNT(*) FROM silver_psd "
             "WHERE leviathan_slug=%s AND country = ANY(%s) GROUP BY country ORDER BY country",
             (MATIF, ["European Union", "EU-15", "EU-27", "EU-28"]))
    out["probes"]["P2"] = [[r[0], int(r[1]), int(r[2]), int(r[3])] for r in rows]

    # P2b
    fr = year_set(MATIF, "France", "su_ratio")
    out["probes"]["P2b"] = {"france_years": fr}

    # P3
    p3 = {}
    for s, c in ((KC, US), (MATIF, EU)):
        rows = q("SELECT COUNT(*), COUNT(su_ratio), COUNT(ending_stocks_mt), COUNT(consumption_mt) "
                 "FROM silver_psd WHERE leviathan_slug=%s AND country=%s", (s, c))
        n, nsu, nes, ncon = [int(x) for x in rows[0]]
        p3[f"{s}@{c}"] = {"rows": n, "su_ratio": nsu, "ending_stocks": nes, "consumption": ncon}
    out["probes"]["P3"] = p3

    # P4 (BLOCKING): the native column's scale
    rows = q("SELECT country, market_year, su_ratio, ending_stocks_mt, consumption_mt "
             "FROM silver_psd WHERE leviathan_slug=%s AND country IN (%s,%s) "
             "AND su_ratio IS NOT NULL AND ending_stocks_mt IS NOT NULL AND "
             "consumption_mt IS NOT NULL ORDER BY market_year DESC LIMIT 6", (KC, US, EU))
    cells = []
    for c, my, su, es, con in rows:
        ratio = float(es) / float(con) if float(con) else None
        cells.append({"country": c, "my": int(my), "su_ratio": float(su),
                      "es_over_con": round(ratio, 6) if ratio else None,
                      "implied_scale": round(float(su) / ratio, 3) if ratio else None})
    out["probes"]["P4"] = cells

    # P5: the series-read shape through the REAL path
    os.environ["GRAPHRAG_NUMBERS_BACKEND"] = "pg"
    from leviathan.graphrag.numbers import query as Q
    spec = Q.NumberQuery(table="silver_psd", metric="su_ratio", asof=args.asof,
                         commodity=KC, country=US, agg="series", period=None)
    srows = Q.run(spec, query_fn=pgnumbers.pg_query)
    out["probes"]["P5"] = {"rows": len(srows), "first": srows[0] if srows else None,
                           "last": srows[-1] if srows else None,
                           "keys": sorted(srows[0].keys()) if srows else []}

    # P6
    p6 = {f"{s}@{c}": year_set(s, c, "exports_mt") for s, c in ((KC, US), (MATIF, EU))}
    ea, eb = set(p6[f"{KC}@{US}"]), set(p6[f"{MATIF}@{EU}"])
    out["probes"]["P6"] = {"sets": {k: v for k, v in p6.items()}, "shared": sorted(ea & eb)}

    # P7: directional back-test over the last 10 shared MY windows
    shared = sorted(sa & sb)[-11:]
    vals: dict = {}
    for s, c in ((KC, US), (MATIF, EU)):
        rows = q("SELECT market_year, su_ratio FROM silver_psd WHERE leviathan_slug=%s AND "
                 "country=%s AND su_ratio IS NOT NULL AND market_year = ANY(%s) "
                 "ORDER BY market_year", (s, c, shared))
        vals[s] = {int(r[0]): float(r[1]) for r in rows}
    opp = same = 0
    for y0, y1 in zip(shared, shared[1:]):
        da = vals[KC].get(y1, 0) - vals[KC].get(y0, 0)
        db = vals[MATIF].get(y1, 0) - vals[MATIF].get(y0, 0)
        if da * db < 0:
            opp += 1
        elif da * db > 0:
            same += 1
    out["probes"]["P7"] = {"windows": len(shared) - 1, "opposite": opp, "same": same}

    # P8
    rows = q("SELECT MIN(trade_date), MAX(trade_date), COUNT(*) FROM silver_futures_eod "
             "WHERE leviathan_slug=%s", (MATIF,))
    out["probes"]["P8"] = {"matif_eod": [str(rows[0][0]), str(rows[0][1]), int(rows[0][2])]}

    # P9
    rows = q("SELECT DISTINCT country FROM silver_psd WHERE leviathan_slug=%s ORDER BY country",
             (KC,))
    out["probes"]["P9"] = [r[0] for r in rows]

    body = json.dumps(out, indent=1)
    print(body)
    s3uri = os.environ.get("EVIDENCE_S3")
    if s3uri:
        import boto3
        from leviathan.graphrag import evidence as ev
        b, k = ev._parse_s3(s3uri.rstrip("/") + f"/probes/rv_regional_probe_{args.asof}.json")
        boto3.client("s3").put_object(Bucket=b, Key=k, Body=body.encode("utf-8"))
        print(f"ARTIFACT s3://{b}/{k}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
