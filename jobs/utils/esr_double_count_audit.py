"""ESR double-count audit (ESR_DESTINATION_PLAN W2.2) — READ-ONLY, S3-direct, no Athena.

The v1 national ESR total is ``agg=sum`` across ALL ``country_code``. If the FAS allCountries data
carried a bloc AGGREGATE code (EU-27, Former Soviet Union) *alongside* its member-state codes with the
aggregate value == the sum of those members, that national sum would already DOUBLE-COUNT today —
independent of destination filtering. This audit answers the question against the DATA, not the
reference: do bloc/aggregate pseudo-codes coexist with their member codes inside one
``(commodity, market_year, week_ending_date)``, and is the aggregate additively equal to the members?

Method (mirrors ``load_pg_numbers._probe_body_columns``: single-URI pyarrow reads of the registered
``silver_esr_compact`` parquet fragments straight from S3 — never Athena on a projected table):
  * for each commodity's latest full-history vintage: DISTINCT ``country_code``;
  * flag each present code against ``esr_destinations.yaml`` (kind bloc / region_nec / unknown);
  * for every bloc code, per ``(my, week)`` cell where it appears, compare its value to the SUM of the
    same-region member codes present in that cell (additive within tolerance == a rollup == double count).

Verdict outcomes (ESR_DESTINATION_PLAN 4.2):
  * no additive coexistence -> national ``agg=sum`` is correct; ``national_exclusion_required = []``.
  * additive coexistence    -> the national sum MUST exclude the offending aggregate code(s); the audit
    returns that exclusion list (W2.4, conditional).

  python jobs/utils/esr_double_count_audit.py                        # human-readable verdict
  python jobs/utils/esr_double_count_audit.py --json audit.json      # machine summary (feeds the builder)
"""
from __future__ import annotations

import argparse
import collections
import json
import os

_BUCKET = os.environ.get("LEVIATHAN_BUCKET", "leviathan-dev-shahem-001")
_REGION = os.environ.get("AWS_REGION", "us-east-1")
_ROOT = "silver/esr"
_VALUE_COLS = ("weekly_exports_1000mt", "outstanding_sales_1000mt", "gross_new_sales_1000mt")
_ADDITIVE_TOL = 0.02                    # |agg - sum(members)| / sum(members) below this == a rollup


def _s3():
    import boto3
    return boto3.client("s3", region_name=_REGION)


def _list_commodities(s3) -> list[str]:
    r = s3.list_objects_v2(Bucket=_BUCKET, Prefix=f"{_ROOT}/", Delimiter="/")
    return sorted(p["Prefix"].split("commodity=")[1].rstrip("/")
                  for p in r.get("CommonPrefixes", []) if "commodity=" in p["Prefix"])


def _latest_vintage(s3, commodity: str) -> str | None:
    r = s3.list_objects_v2(Bucket=_BUCKET, Prefix=f"{_ROOT}/commodity={commodity}/", Delimiter="/")
    asofs = sorted(p["Prefix"].split("as_of=")[1].rstrip("/") for p in r.get("CommonPrefixes", []) if "as_of=" in p["Prefix"])
    return asofs[-1] if asofs else None


def _read_table(commodity: str, asof: str):
    import pyarrow.dataset as pads
    uri = f"s3://{_BUCKET}/{_ROOT}/commodity={commodity}/as_of={asof}/part-000.parquet"
    cols = ["country_code", "market_year", "week_ending_date", *_VALUE_COLS]
    return pads.dataset(uri, format="parquet").to_table(columns=cols)


def _region_members(ref_rows: list[dict]) -> dict[int, set[int]]:
    out: dict[int, set[int]] = collections.defaultdict(set)
    for r in ref_rows:
        out[r["regionId"]].add(r["countryCode"])
    return out


def audit(commodities: list[str] | None = None, raw_ref_path: str | None = None) -> dict:
    from leviathan.graphrag.numbers.esr_destinations import load_esr_destinations, missing_codes
    dst = load_esr_destinations()
    # region map from the raw FAS reference (regionId lives in the raw JSON, not the curated YAML)
    ref_rows = None
    if raw_ref_path:
        ref_rows = json.load(open(raw_ref_path, encoding="utf-8"))
    reg_members = _region_members(ref_rows) if ref_rows else {}
    code_region = {r["countryCode"]: r["regionId"] for r in ref_rows} if ref_rows else {}

    s3 = _s3()
    commodities = commodities or _list_commodities(s3)
    bloc_codes = {int(c) for c in dst.bloc_watch_codes}

    all_codes: set[int] = set()
    coexist: dict[int, dict] = {int(c): {"cells": 0, "member_overlap_cells": 0, "additive_cells": 0,
                                         "example": None} for c in bloc_codes}
    per_commodity: dict[str, dict] = {}

    for comm in commodities:
        asof = _latest_vintage(s3, comm)
        if not asof:
            continue
        t = _read_table(comm, asof)
        cc = t.column("country_code").to_pylist()
        my = t.column("market_year").to_pylist()
        wk = [str(x) for x in t.column("week_ending_date").to_pylist()]
        vals = {vc: t.column(vc).to_pylist() for vc in _VALUE_COLS}
        all_codes |= set(cc)
        per_commodity[comm] = {"vintage": asof, "rows": t.num_rows, "distinct_codes": len(set(cc))}

        # per-cell code -> value-tuple, for the additivity test
        cell: dict[tuple, dict[int, tuple]] = collections.defaultdict(dict)
        for i in range(len(cc)):
            cell[(my[i], wk[i])][cc[i]] = tuple((vals[vc][i] or 0.0) for vc in _VALUE_COLS)
        for bloc in bloc_codes:
            region = code_region.get(bloc)
            members = (reg_members.get(region, set()) - {bloc}) if region is not None else set()
            for key, codes in cell.items():
                if bloc not in codes:
                    continue
                coexist[bloc]["cells"] += 1
                present_members = [c for c in codes if c in members]
                if not present_members:
                    continue
                coexist[bloc]["member_overlap_cells"] += 1
                # additive test on outstanding_sales (index 1) -- the level a rollup would sum
                agg = codes[bloc][1]
                msum = sum(codes[c][1] for c in present_members)
                if msum > 0 and abs(agg - msum) / msum < _ADDITIVE_TOL:
                    coexist[bloc]["additive_cells"] += 1
                    if coexist[bloc]["example"] is None:
                        coexist[bloc]["example"] = {"commodity": comm, "my": key[0], "week": key[1],
                                                    "agg_outstanding": round(agg, 3),
                                                    "member_sum": round(msum, 3),
                                                    "members_present": sorted(present_members)}

    exclusion = sorted(b for b, s in coexist.items() if s["additive_cells"] > 0)
    verdict = "double_count" if exclusion else "none"
    missing = missing_codes(all_codes)

    return {
        "probed_table": "silver_esr_compact",
        "probed_source": f"s3://{_BUCKET}/{_ROOT} (S3-direct parquet, no Athena)",
        "commodities": per_commodity,
        "distinct_codes_in_data": len(all_codes),
        "data_codes_all_covered": not missing,
        "unmapped_codes": missing,
        "bloc_watch_codes": sorted(bloc_codes),
        "bloc_coexistence": {str(b): s for b, s in coexist.items()},
        "double_count_verdict": verdict,
        "national_exclusion_required": exclusion,
    }


def main() -> None:
    import logging
    logging.basicConfig(level=logging.WARNING)
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--commodities", nargs="+", default=None, help="subset (default: all under silver/esr)")
    ap.add_argument("--raw-ref", default=None,
                    help="FAS /api/esr/countries raw JSON (for regionId member grouping; recommended)")
    ap.add_argument("--json", default=None, help="write the machine summary here")
    args = ap.parse_args()

    res = audit(args.commodities, args.raw_ref)
    # ASCII-only stdout (cp1252 console)
    print("=== ESR double-count audit (W2.2) ===")
    print(f"probed: {res['probed_source']}")
    print(f"commodities: {len(res['commodities'])}  distinct country_code in data: {res['distinct_codes_in_data']}")
    print(f"coverage: all data codes mapped in reference = {res['data_codes_all_covered']} "
          f"(unmapped: {res['unmapped_codes'] or 'none'})")
    print(f"bloc watch codes: {res['bloc_watch_codes']}")
    for b, s in res["bloc_coexistence"].items():
        print(f"  bloc {b}: cells={s['cells']} member-overlap={s['member_overlap_cells']} "
              f"ADDITIVE(rollup)={s['additive_cells']}")
        if s["example"]:
            print(f"    additive example: {s['example']}")
    print(f"VERDICT: double_count = {res['double_count_verdict']}")
    print(f"national agg=sum exclusion required: {res['national_exclusion_required'] or 'NONE (v1 total correct)'}")
    if args.json:
        json.dump(res, open(args.json, "w"), indent=2)
        print(f"wrote {args.json}")


if __name__ == "__main__":
    main()
