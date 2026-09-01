"""D-DA STEP-0 census probes P0-P5 (derived-arithmetic lane, round-2 design v2) -- pg-only, $0.

Runs IN-VPC on the evidence jobdef (the rv_regional_probe precedent: the laptop cannot reach the
RDS). Reads silver_wasde and silver_futures_eod through the pg mirror (schema = pgnumbers.SCHEMA).
Writes the artifact JSON to EVIDENCE_S3 (`probes/dda_probe_<asof>.json`) and prints it to the log.

Probes (design v2 STEP 0, amended by refute-v2 F2 + M2):
  P0  silver_wasde pg columns + the DISTINCT commodity vocabulary for the roster legs.
  P1  total_use census: which attributes exist per (commodity, united_states), MY counts each --
      decides the official-line-vs-ladder basis (v2 ROW 2).
  P2  THE F2 KILL: table_type multiplicity -- at the latest release_date per (commodity, region,
      attribute, marketing_year), how many DISTINCT table_type rows survive? A multi-valued series
      kills lane 1 as designed (no serving-side fence exists for the axis).
  P3  vintage survival (KD0): share of MYs whose latest-vintage components share ONE release_date.
  P4  magnitude census (refute M2): MIN/MAX/latest per component -- the in-band [0.5, 150] count
      per leg decides whether DV_INBAND_CAP is a budget fence or a unit-scale filter.
  P5  EOD-leg roster (owner-ratified native-unit fresh levels): which reading-roster slugs serve
      silver_futures_eod at all + one front_expiry row-shape sample (the real-row-shape law).
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

SCHEMA = pgnumbers.SCHEMA
US = "united_states"
# the candidate _DV_WASDE_LEGS roster: the XC material pairs' US-WASDE-covered legs
LEGS = ("corn", "wheat", "soybeans", "soybean_oil", "soybean_meal", "sorghum")
COMPONENTS = ("ending_stocks", "production", "domestic_total", "exports", "total_use")
EOD_ROSTER = ("corn_cbot", "soft_red_winter_wheat_cbot", "hard_red_winter_wheat_kcbt",
              "soybeans_cbot", "soybean_oil_cbot", "soybean_meal_cbot",
              "malaysian_crude_palm_oil_cme", "canola_ice", "french_wheat_matif")
INBAND = (0.5, 150.0)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--asof", default="2026-09-01")
    args = ap.parse_args()
    assert os.environ.get("EVIDENCE_PG_DSN"), "dda_probe requires EVIDENCE_PG_DSN"
    conn = psycopg.connect(pgstore.dsn(), autocommit=True)
    out: dict = {"asof": args.asof, "probes": {}}

    def q(sql, params=()):
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()

    def emit(name, payload):
        """Print each probe AS IT LANDS -- a late crash must never eat the early answers."""
        out["probes"][name] = payload
        print(f"[probe] {name}: {json.dumps(payload, default=str)[:1200]}")

    # P0 -- the real columns, and the commodity vocabulary
    cols = [r[0] for r in q(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema=%s AND table_name='silver_wasde' ORDER BY ordinal_position", (SCHEMA,))]
    out["probes"]["P0_columns"] = cols
    print(f"[probe] P0_columns: {cols}")
    val_col = next((c for c in ("estimate", "value", "amount", "figure", "val", "quantity")
                    if c in cols), None)
    print(f"[probe] P0_value_col: {val_col}")
    out["probes"]["P0_value_col"] = val_col
    like = " OR ".join("commodity ILIKE %s" for _ in LEGS)
    vocab = q(f"SELECT DISTINCT commodity FROM {SCHEMA}.silver_wasde WHERE {like} ORDER BY 1",
              tuple(f"%{leg.split('_')[0]}%" for leg in LEGS))
    emit("P0_commodity_vocab", [r[0] for r in vocab])

    has_tt = "table_type" in cols
    has_role = "estimate_role" in cols
    rel_col = "release_date" if "release_date" in cols else (
        "knowledge_date" if "knowledge_date" in cols else None)
    emit("P0_keys", {"table_type": has_tt, "estimate_role": has_role, "release_col": rel_col})
    if rel_col is None or val_col is None:
        print(json.dumps(out, indent=1, default=str))
        return 1

    # P1 -- attribute existence + MY counts per leg
    p1 = {}
    for leg in LEGS:
        rows = q(f"SELECT attribute, COUNT(DISTINCT marketing_year) FROM {SCHEMA}.silver_wasde "
                 f"WHERE commodity ILIKE %s AND region=%s AND attribute = ANY(%s) "
                 f"GROUP BY attribute", (f"%{leg.split('_')[0]}%", US, list(COMPONENTS)))
        p1[leg] = {r[0]: int(r[1]) for r in rows}
    emit("P1_total_use_census", p1)

    # P2 -- THE F2 KILL: table_type multiplicity at the latest vintage
    p2 = {}
    if has_tt:
        for leg in LEGS:
            rows = q(
                f"WITH latest AS (SELECT commodity, region, attribute, marketing_year, table_type, "
                f"  ROW_NUMBER() OVER (PARTITION BY commodity, region, attribute, marketing_year, "
                f"    table_type ORDER BY {rel_col} DESC) rn "
                f"  FROM {SCHEMA}.silver_wasde WHERE commodity ILIKE %s AND region=%s "
                f"  AND attribute = ANY(%s)) "
                f"SELECT attribute, COUNT(*) AS my_rows, "
                f"  COUNT(DISTINCT marketing_year) AS mys, "
                f"  SUM(CASE WHEN cnt > 1 THEN 1 ELSE 0 END) AS multi_mys "
                f"FROM (SELECT attribute, marketing_year, COUNT(DISTINCT table_type) cnt "
                f"      FROM latest WHERE rn=1 GROUP BY attribute, marketing_year) g "
                f"GROUP BY attribute",
                (f"%{leg.split('_')[0]}%", US, list(COMPONENTS)))
            p2[leg] = [{"attribute": r[0], "my_rows": int(r[1]), "mys": int(r[2]),
                        "multi_table_type_mys": int(r[3])} for r in rows]
        tts = q(f"SELECT commodity, table_type, COUNT(*) FROM {SCHEMA}.silver_wasde "
                f"WHERE region=%s GROUP BY 1, 2 ORDER BY 1, 3 DESC LIMIT 40", (US,))
        p2["_table_type_values"] = [[r[0], r[1], int(r[2])] for r in tts]
    emit("P2_table_type_kill", p2 if has_tt else "NO table_type COLUMN IN PG MIRROR")

    # P2b -- THE DECISIVE HALF: do the duplicate table_types AGREE on the value at the latest
    # vintage? Agreement = harmless duplication (dedup by value); disagreement = lane 1 blocked
    # without a serving-side table_type surface.
    p2b = {}
    if has_tt:
        for leg in LEGS:
            rows = q(
                f"WITH latest AS (SELECT attribute, marketing_year, table_type, {val_col} AS v, "
                f"  ROW_NUMBER() OVER (PARTITION BY commodity, region, attribute, marketing_year, "
                f"    table_type ORDER BY {rel_col} DESC) rn "
                f"  FROM {SCHEMA}.silver_wasde WHERE commodity ILIKE %s AND region=%s "
                f"  AND attribute = ANY(%s)) "
                f"SELECT attribute, COUNT(*) AS multi_mys, "
                f"  SUM(CASE WHEN vals > 1 THEN 1 ELSE 0 END) AS disagree_mys "
                f"FROM (SELECT attribute, marketing_year, COUNT(DISTINCT table_type) tts, "
                f"      COUNT(DISTINCT v) vals FROM latest WHERE rn=1 "
                f"      GROUP BY attribute, marketing_year HAVING COUNT(DISTINCT table_type) > 1) g "
                f"GROUP BY attribute",
                (f"%{leg.split('_')[0]}%", US, list(COMPONENTS)))
            p2b[leg] = [{"attribute": r[0], "multi_mys": int(r[1]), "disagree_mys": int(r[2])}
                        for r in rows]
        # sample disagreements verbatim for the corn flagship, if any
        rows = q(
            f"WITH latest AS (SELECT attribute, marketing_year, table_type, {val_col} AS v, unit, "
            f"  ROW_NUMBER() OVER (PARTITION BY commodity, region, attribute, marketing_year, "
            f"    table_type ORDER BY {rel_col} DESC) rn "
            f"  FROM {SCHEMA}.silver_wasde WHERE commodity='corn' AND region=%s "
            f"  AND attribute='ending_stocks') "
            f"SELECT marketing_year, table_type, v, unit FROM latest WHERE rn=1 "
            f"AND marketing_year IN (SELECT marketing_year FROM latest WHERE rn=1 "
            f"  GROUP BY marketing_year HAVING COUNT(DISTINCT v) > 1) "
            f"ORDER BY marketing_year DESC, table_type LIMIT 16", (US,))
        p2b["_corn_disagreement_sample"] = [[str(r[0]), r[1], str(r[2]), r[3]] for r in rows]
    emit("P2b_value_agreement", p2b)

    # P3 -- vintage survival: latest-vintage components sharing one release date per MY
    p3 = {}
    for leg in LEGS:
        rows = q(
            f"WITH latest AS (SELECT attribute, marketing_year, {rel_col} AS rel, "
            f"  ROW_NUMBER() OVER (PARTITION BY attribute, marketing_year ORDER BY {rel_col} DESC) rn "
            f"  FROM {SCHEMA}.silver_wasde WHERE commodity ILIKE %s AND region=%s "
            f"  AND attribute = ANY(%s)) "
            f"SELECT marketing_year, COUNT(DISTINCT attribute) attrs, COUNT(DISTINCT rel) rels "
            f"FROM latest WHERE rn=1 GROUP BY marketing_year ORDER BY marketing_year",
            (f"%{leg.split('_')[0]}%", US, ["ending_stocks", "production", "domestic_total", "exports"]))
        mys = [{"my": str(r[0]), "attrs": int(r[1]), "rels": int(r[2])} for r in rows]
        n = len(mys)
        ok = sum(1 for m in mys if m["attrs"] >= 3 and m["rels"] == 1)
        p3[leg] = {"mys": n, "single_vintage_full": ok,
                   "share": round(ok / n, 3) if n else None, "tail": mys[-6:]}
    emit("P3_vintage_survival", p3)

    # P4 -- magnitude census (M2): in-band [0.5, 150] exposure per leg
    p4 = {}
    for leg in LEGS:
        rows = q(f"SELECT attribute, unit, MIN({val_col}), MAX({val_col}) "
                 f"FROM {SCHEMA}.silver_wasde "
                 f"WHERE commodity ILIKE %s AND region=%s AND attribute = ANY(%s) "
                 f"GROUP BY attribute, unit", (f"%{leg.split('_')[0]}%", US, list(COMPONENTS)))
        ent = []
        for r in rows:
            try:
                lo, hi = float(r[2]), float(r[3])
            except (TypeError, ValueError):
                ent.append({"attribute": r[0], "unit": r[1], "min": str(r[2]), "max": str(r[3]),
                            "inband": "NON-NUMERIC"})
                continue
            ent.append({"attribute": r[0], "unit": r[1], "min": lo, "max": hi,
                        "inband": not (hi < INBAND[0] or lo > INBAND[1])})
        p4[leg] = ent
    emit("P4_magnitude_census", p4)

    # P5 -- EOD-leg roster + one real front-expiry-shaped row sample
    eod = q(f"SELECT DISTINCT leviathan_slug FROM {SCHEMA}.silver_futures_eod "
            f"WHERE leviathan_slug = ANY(%s) ORDER BY 1", (list(EOD_ROSTER),))
    served = [r[0] for r in eod]
    emit("P5_eod_roster", {"served": served,
                           "missing": [s for s in EOD_ROSTER if s not in served]})
    if served:
        cols_eod = [r[0] for r in q(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema=%s AND table_name='silver_futures_eod' ORDER BY ordinal_position",
            (SCHEMA,))]
        ocol = next((c for c in ("data_date", "trade_date", "date", "knowledge_date", "asof_date")
                     if c in cols_eod), cols_eod[0])
        sample = q(f"SELECT * FROM {SCHEMA}.silver_futures_eod WHERE leviathan_slug=%s "
                   f"ORDER BY {ocol} DESC LIMIT 1", (served[0],))
        emit("P5_row_shape", {"columns": cols_eod, "order_col": ocol,
                              "sample": [str(v) for v in sample[0]] if sample else None})

    # P6 -- the SERVED row shape through the REAL query path (the fixture contract for lane 1):
    # keys as the producer will see them, the table_type duplication AS SERVED, unit presence.
    os.environ["GRAPHRAG_NUMBERS_BACKEND"] = "pg"
    from leviathan.graphrag.numbers import query as Q
    spec = Q.NumberQuery(table="silver_wasde", metric="ending_stocks", asof=args.asof,
                         commodity="corn", country=None, agg="series", period=None)
    srows = Q.run(spec, query_fn=pgnumbers.pg_query)
    per_my: dict = {}
    for r in (srows or []):
        my = str(r.get("period") or r.get("marketing_year"))
        per_my[my] = per_my.get(my, 0) + 1
    dup = {k: v for k, v in per_my.items() if v > 1}
    emit("P6_card_shape", {
        "rows": len(srows or []),
        "keys": sorted(srows[0].keys()) if srows else [],
        "first": srows[0] if srows else None,
        "last": srows[-1] if srows else None,
        "mys": len(per_my), "dup_mys": len(dup),
        "dup_sample": dict(list(dup.items())[:4]),
        "units_seen": sorted({str(r.get("unit")) for r in (srows or [])})[:8],
    })

    body = json.dumps(out, indent=1, default=str)
    print(body)
    s3uri = os.environ.get("EVIDENCE_S3", "")
    if s3uri.startswith("s3://"):
        import boto3
        b, _, k = s3uri[5:].partition("/")
        key = f"{k}/probes/dda_probe_{args.asof.replace('-', '')}.json".lstrip("/")
        boto3.client("s3").put_object(Bucket=b, Key=key, Body=body.encode("utf-8"))
        print(f"[artifact] s3://{b}/{key}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
