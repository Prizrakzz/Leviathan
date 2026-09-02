"""V2-2 BALANCE-SHEET OUTCOMES -- step 1, the $0 in-VPC substrate probe (charter V2 HORIZON, recon
2026-09-02: build V2-2 on silver_psd's card-served revision metrics, NOT on WASDE).

THE QUESTION. For every (board, firing window) cell the walk can select (the r2 fence artifact's
selection-A cells + the sitting-3 arm's fired soy cell), does silver_psd serve -- THROUGH THE REAL
CARD PATH, vintage-correct at asof = the window's END -- a revision row (production / ending stocks
/ consumption, MT) whose release_date falls INSIDE the window? That is the sentence V2-2 would mint:
"over that firing the sheet's ending-stocks estimate for MY<x> was revised by <v> MT [N]". A revision
is ONE source-stamped row, so the derived lane's one-knowledge-date law never engages.

Runs IN-VPC on the evidence jobdef (the laptop cannot reach the RDS; the cw_probe bootstrap
precedent). Writes the artifact to EVIDENCE_S3 probes/v22_psd_probe_<asof>.json and prints each
cell as it lands (a late crash must never eat the early answers).

    python jobs/utils/v22_psd_probe.py --asof 2026-09-02
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

sys.path.insert(0, "src")

REV_METRICS = ("ending_stocks_mt_revision", "production_mt_revision", "consumption_mt_revision")
COUNTRY = "United States"        # the silver_psd country vocabulary (rv_regional_probe precedent)

# the walk's board slug -> the PSD leviathan_slug it should read (identity first; the probe ALSO
# tries the bare commodity so an alias miss is measured rather than assumed)
BOARD_TO_PSD = {
    "corn_cbot": ("corn_cbot", "corn"),
    "hard_red_winter_wheat_kcbt": ("hard_red_winter_wheat_kcbt", "wheat"),
    "soft_red_winter_wheat_cbot": ("soft_red_winter_wheat_cbot", "wheat"),
    "soybeans_cbot": ("soybeans_cbot", "soybeans"),
    "soybean_meal_cbot": ("soybean_meal_cbot", "soybean_meal"),
    "soybean_oil_cbot": ("soybean_oil_cbot", "soybean_oil"),
    "arabica_coffee": ("arabica_coffee", "coffee"),
    "robusta_coffee": ("robusta_coffee", "coffee"),
    "raw_sugar": ("raw_sugar", "sugar"),
    "white_sugar": ("white_sugar", "sugar"),
    "rapeseed_oil_zce": ("rapeseed_oil_zce", "rapeseed_oil"),
    "rapeseed_meal_zce": ("rapeseed_meal_zce", "rapeseed_meal"),
}


def _cells() -> list:
    """(board, t1, t2) from the banked r2 selection-A firings + the arm's fired soy window."""
    cells = set()
    here = os.path.dirname(os.path.abspath(__file__))
    cands = [os.path.join(os.getcwd(), "data", "batch_runs", "cw_probe_fence_r2_20260901.json"),
             os.path.join(here, "..", "..", "data", "batch_runs", "cw_probe_fence_r2_20260901.json")]
    r2 = next((c for c in cands if os.path.exists(c)), cands[0])   # in-VPC the bootstrap lands it in CWD
    try:
        d = json.load(open(r2, encoding="utf-8"))
        for h in d["halves"]["fence_hops"]:
            a, b = h["hop"].split("->")
            for f in h["firings"]:
                if "A" in f.get("selections", []):
                    t1, t2 = f["window"].split("..")
                    cells.add((a, t1, t2))
                    cells.add((b, t1, t2))
    except Exception as exc:  # noqa: BLE001 -- the artifact is local; in-VPC we fall back to the roster
        print(f"[v22] r2 artifact unavailable ({type(exc).__name__}); using the embedded roster")
        for a, t1, t2 in (("corn_cbot", "2025-08-01", "2026-04-20"),
                          ("hard_red_winter_wheat_kcbt", "2025-08-01", "2026-04-20"),
                          ("soft_red_winter_wheat_cbot", "2025-08-01", "2026-04-20"),
                          ("soybean_meal_cbot", "2025-08-01", "2026-04-20"),
                          ("corn_cbot", "2024-10-03", "2025-06-27"),
                          ("soybean_meal_cbot", "2026-01-01", "2026-08-12"),
                          ("soybean_oil_cbot", "2026-01-01", "2026-08-12"),
                          ("soybeans_cbot", "2025-03-31", "2025-06-01"),
                          ("soybean_oil_cbot", "2025-03-31", "2025-06-01"),
                          ("raw_sugar", "2024-09-01", "2025-05-01"),
                          ("white_sugar", "2024-09-01", "2025-05-01"),
                          ("arabica_coffee", "2025-12-31", "2026-05-01"),
                          ("robusta_coffee", "2025-09-04", "2026-05-20"),
                          ("rapeseed_oil_zce", "2022-01-01", "2022-08-01"),
                          ("rapeseed_meal_zce", "2022-01-01", "2022-08-01")):
            cells.add((a, t1, t2))
    # the arm's live fired window (soybeans -> meal -> oil, 2019-12..2020-04, endpoint 2020-04-21)
    for a in ("soybeans_cbot", "soybean_meal_cbot", "soybean_oil_cbot"):
        cells.add((a, "2019-12-01", "2020-04-21"))
    return sorted(cells)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--asof", default="2026-09-02")
    args = ap.parse_args()
    assert os.environ.get("EVIDENCE_PG_DSN"), "v22_psd_probe requires EVIDENCE_PG_DSN (in-VPC)"
    os.environ.setdefault("GRAPHRAG_NUMBERS_BACKEND", "pg")
    from leviathan.graphrag.numbers import pgnumbers
    from leviathan.graphrag.numbers import query as Q
    out: dict = {"probe": "v22_psd_revisions", "asof": args.asof, "cells": [], "summary": {}}

    def read(slug, metric, asof, my_lo, my_hi):
        spec = Q.NumberQuery(table="silver_psd", metric=metric, asof=asof, commodity=slug,
                             country=COUNTRY, agg="series", period_start=str(my_lo),
                             period_end=str(my_hi))
        return Q.run(spec, query_fn=pgnumbers.pg_query) or []

    n_reads = 0
    hits_inside = 0
    served_any = 0
    for board, t1, t2 in _cells():
        end = dt.date.fromisoformat(t2)
        my_hi = end.year
        my_lo = end.year - 1
        cell = {"board": board, "window": f"{t1}..{t2}", "psd_slug": None, "metrics": {}}
        for cand in BOARD_TO_PSD.get(board, (board,)):
            got_any = False
            for m in REV_METRICS:
                try:
                    rows = read(cand, m, t2, my_lo, my_hi)
                    n_reads += 1
                except Exception as exc:  # noqa: BLE001 -- record the failure, keep probing
                    cell["metrics"][m] = {"error": type(exc).__name__, "detail": str(exc)[:160]}
                    continue
                recs = []
                for r in rows:
                    kd = str((r or {}).get("knowledge_date") or (r or {}).get("release_date") or "")[:10]
                    recs.append({"period": (r or {}).get("period"), "release_date": kd,
                                 "value": (r or {}).get("value"), "unit": (r or {}).get("unit"),
                                 "inside_window": bool(kd and t1 <= kd <= t2)})
                if recs:
                    got_any = True
                inside = [x for x in recs if x["inside_window"]]
                cell["metrics"][m] = {"n_rows": len(recs), "n_inside_window": len(inside),
                                      "rows_inside": inside[:6],        # r3: the rows that MATTER
                                      "periods_seen": sorted({str(x["period"]) for x in recs})[-4:],
                                      "newest_release": max((x["release_date"] for x in recs), default=None)}
            if got_any:
                cell["psd_slug"] = cand
                break
            cell["metrics"] = {}
        if cell["psd_slug"]:
            served_any += 1
        if any((v.get("n_inside_window") or 0) > 0 for v in cell["metrics"].values()):
            hits_inside += 1
        out["cells"].append(cell)
        ins = {k: (v.get("n_inside_window") if isinstance(v, dict) else v)
               for k, v in cell["metrics"].items()}
        print(f"[v22] {board} {t1}..{t2} psd_slug={cell['psd_slug']} inside={ins}")
    out["summary"] = {"cells": len(out["cells"]), "served_any_revision": served_any,
                      "cells_with_a_revision_inside_window": hits_inside, "pg_reads": n_reads}
    print("[v22] SUMMARY", json.dumps(out["summary"]))
    base = os.environ.get("EVIDENCE_S3", "")
    if base.startswith("s3://"):
        import boto3
        bucket, _, prefix = base[5:].partition("/")
        key = f"{prefix.rstrip('/')}/probes/v22_psd_probe_r3_{args.asof}.json"
        boto3.client("s3").put_object(Bucket=bucket, Key=key,
                                      Body=json.dumps(out, indent=1, default=str).encode())
        print(f"[v22] banked s3://{bucket}/{key}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
