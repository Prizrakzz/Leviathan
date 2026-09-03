"""$0 recon: does Databento GLBX.MDP3 carry the CME USD Malaysian Crude Palm Oil Calendar futures
(Globex root CPO), and what would its daily settlement history cost?

V2-4 (cascade-walk V2 horizon, charter docs/private/CASCADE_WALK_V4_CHARTER.md): the MYR/BMD
FCPO venue is blocked; CME's CPO is the USD instrument (monthly contracts for 60 consecutive
months, financially settled to the contract month's cumulative average of the BMD third-forward
FCPO settlement converted at the KL USD/MYR fixing). cmegroup.com serves ONE trade date of
settlements; the only history routes are CME DataMine (purchase) or Databento GLBX.MDP3 -- IF the
product is in the feed. CME's own footnote: settlements on instruments without open interest or
volume are web-only and never reach the Market Data Platform, so the statistics schema may be
sparse for the back months. This probe measures, for FREE (symbology.resolve + metadata.get_cost
are unbilled; no timeseries pull):

  per year 2010..asof-year on GLBX.MDP3:
    - CPO.FUT parent -> instrument ids -> raw symbols (the shipped two-step resolve)
    - the outright set under the shipped GLBX filter (partition_symbols)
    - metadata.get_cost for ohlcv-1d and statistics on exactly that symbol set / window

The shipped fetch job pins --root to ROOT_MAP's 15 roots, so this probe is standalone; it reuses
the fetch module's helpers verbatim (make_client, call_with_backoff, dataset_available_end,
_resolve_chunk_salvaging) so the call shapes are the ones that already bought the W2 backfill.

Runs in-VPC on the leviathan-dev-databento-fetch jobdef (DATABENTO_API_KEY injected from Secrets
Manager). Banks probes/cpo_databento_probe_<asof>.json under LEVIATHAN_BUCKET. ASCII-only output.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone

for _p in ("/app", os.getcwd(),
           os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))):
    if _p not in sys.path:
        sys.path.insert(0, _p)

ROOT = "CPO"
DATASET = "GLBX.MDP3"
OHLCV = "ohlcv-1d"
STATS = "statistics"


def _log(msg: str) -> None:
    print(msg.encode("ascii", "replace").decode("ascii"), flush=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--asof", required=True)
    ap.add_argument("--first-year", type=int, default=2010)
    ap.add_argument("--bucket", default=os.environ.get("LEVIATHAN_BUCKET"))
    ap.add_argument("--suffix", default="", help="artifact name suffix (partial re-runs)")
    # V2-4 sitting (2026-09-02): the FREE record-count instrument. metadata.get_record_count is
    # unbilled (verified in databento 0.82.0: dataset/start/end/symbols/schema/stype_in), so the
    # per-year statistics + ohlcv-1d record counts and, for --density-years, the PER-OUTRIGHT
    # statistics counts (does every listed month carry records?) are measured at $0.
    ap.add_argument("--record-counts", action="store_true",
                    help="also bank metadata.get_record_count per year for both schemas (free)")
    ap.add_argument("--density-years", default="",
                    help="comma-separated years whose PER-OUTRIGHT statistics record counts are "
                         "banked (free; one metadata call per outright)")
    args = ap.parse_args(argv)
    density_years = {int(y) for y in args.density_years.split(",") if y.strip()}

    from jobs.ingest.fetch_databento_eod import (  # noqa: E402
        _resolve_chunk_salvaging, RESOLVE_CHUNK, call_with_backoff, dataset_available_end,
        make_client,
    )
    from leviathan.transforms.raw_to_bronze.databento_eod import _GLBX_FIRST, partition_symbols  # noqa: E402

    key = os.environ.get("DATABENTO_API_KEY")
    if not key:
        _log("FATAL: DATABENTO_API_KEY absent (run on the databento-fetch jobdef)")
        return 2
    client = make_client(key)
    asof = datetime.strptime(args.asof[:10], "%Y-%m-%d").date()
    avail_end = dataset_available_end(client, DATASET)
    _log(f"dataset {DATASET} available_end={avail_end} asof={asof}")
    first = datetime.strptime(_GLBX_FIRST, "%Y-%m-%d").date()

    out = {"probe": "cpo_databento_probe", "asof": str(asof), "dataset": DATASET, "root": ROOT,
           "available_end": str(avail_end), "glbx_first": _GLBX_FIRST,
           "generated_at": datetime.now(timezone.utc).isoformat(), "years": [], "errors": []}
    total_ohlcv = total_stats = 0.0
    for year in range(max(args.first_year, first.year), asof.year + 1):
        start = max(first, date(year, 1, 1))
        # END IS EXCLUSIVE and clamped to metadata.get_dataset_range's end exactly as the shipped
        # lane's incremental_window does: end = avail_end (exclusive). The +1-day form 422s
        # (dataset_unavailable_range) on the current year -- measured 2026-09-02.
        end_excl = min(date(year + 1, 1, 1), min(asof, avail_end))
        if end_excl <= start:
            continue
        s, e = start.isoformat(), end_excl.isoformat()
        row = {"year": year, "window": {"start": s, "end_exclusive": e}}
        try:
            r1 = call_with_backoff(client.symbology.resolve, dataset=DATASET, symbols=f"{ROOT}.FUT",
                                   stype_in="parent", stype_out="instrument_id",
                                   start_date=s, end_date=e)
            ids = sorted({x["s"] for entries in (r1.get("result") or {}).values()
                          for x in entries if x.get("s")}, key=int)
            row["instrument_ids"] = len(ids)
            syms: set[str] = set()
            unresolvable: list[str] = []
            for i in range(0, len(ids), RESOLVE_CHUNK):
                chunk = ids[i:i + RESOLVE_CHUNK]
                r2 = _resolve_chunk_salvaging(client, DATASET, chunk, s, e, unresolvable)
                for entries in (r2.get("result") or {}).values():
                    for x in entries:
                        if x.get("s"):
                            syms.add(x["s"])
                time.sleep(0.5)
            keep, drop = partition_symbols(syms, ROOT, DATASET)
            row["raw_symbols"] = sorted(syms)
            row["outrights"] = keep
            row["dropped"] = drop
            row["unresolvable"] = unresolvable
            if keep:
                c_o = float(call_with_backoff(client.metadata.get_cost, dataset=DATASET, symbols=keep,
                                              schema=OHLCV, stype_in="raw_symbol", start=s, end=e))
                c_s = float(call_with_backoff(client.metadata.get_cost, dataset=DATASET, symbols=keep,
                                              schema=STATS, stype_in="raw_symbol", start=s, end=e))
            else:
                c_o = c_s = 0.0
            row["cost_usd"] = {OHLCV: round(c_o, 4), STATS: round(c_s, 4)}
            total_ohlcv += c_o
            total_stats += c_s
            if args.record_counts and keep:
                counts = {}
                for schema in (STATS, OHLCV):
                    counts[schema] = int(call_with_backoff(
                        client.metadata.get_record_count, dataset=DATASET, symbols=keep,
                        schema=schema, stype_in="raw_symbol", start=s, end=e))
                row["record_count"] = counts
                _log(f"{year}: record_count statistics={counts[STATS]} ohlcv-1d={counts[OHLCV]}")
            if year in density_years and keep:
                per = {}
                for sym in keep:
                    per[sym] = int(call_with_backoff(
                        client.metadata.get_record_count, dataset=DATASET, symbols=[sym],
                        schema=STATS, stype_in="raw_symbol", start=s, end=e))
                    time.sleep(0.2)
                row["statistics_records_per_outright"] = per
                zero = sorted(k for k, v in per.items() if v == 0)
                _log(f"{year}: per-outright statistics records: {len(per)} outrights, "
                     f"{len(zero)} with ZERO records {zero[:10]}")
            _log(f"{year}: ids={len(ids)} outrights={len(keep)} dropped={len(drop)} "
                 f"ohlcv=${c_o:.4f} statistics=${c_s:.4f} first={keep[:3]}")
        except Exception as exc:  # noqa: BLE001
            row["error"] = f"{type(exc).__name__}: {exc}"[:400]
            out["errors"].append({"year": year, "error": row["error"]})
            _log(f"{year}: ERROR {row['error']}")
        out["years"].append(row)
        time.sleep(0.5)

    out["totals_usd"] = {OHLCV: round(total_ohlcv, 4), STATS: round(total_stats, 4),
                         "both": round(total_ohlcv + total_stats, 4)}
    all_outrights = sorted({x for r in out["years"] for x in r.get("outrights", [])})
    out["outright_count_total"] = len(all_outrights)
    out["first_outright_year"] = next((r["year"] for r in out["years"] if r.get("outrights")), None)
    _log(f"TOTAL ohlcv=${total_ohlcv:.4f} statistics=${total_stats:.4f} "
         f"outrights_total={len(all_outrights)} first_year={out['first_outright_year']}")

    body = json.dumps(out, indent=1, default=str)
    local = f"/tmp/cpo_databento_probe_{asof.strftime('%Y%m%d')}{args.suffix}.json"
    with open(local, "w", encoding="utf-8") as fh:
        fh.write(body)
    if args.bucket:
        import boto3  # noqa: E402
        k = f"probes/cpo_databento_probe_{asof.strftime('%Y%m%d')}{args.suffix}.json"
        boto3.client("s3").put_object(Bucket=args.bucket, Key=k, Body=body.encode("utf-8"),
                                      ContentType="application/json")
        _log(f"banked s3://{args.bucket}/{k}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
