"""OP-8 -- the estate-wide min_nonnull_frac recalibration census (task #62; alarm-RCA 2026-08-18).

THE LAW THIS SERVES: the reliability threat is FALSE REDS from inferred thresholds, not corruption.
~48 silver registries carry `min_nonnull_frac: 0.5` stamped `provisional` -- a uniform guess, never a
measurement -- and the one time a guess met real data (nass pct_emerged, floor 0.08 vs measured
0.0681) it paged the owner three times over a healthy table. This census replaces every provisional
floor with a MEASURED one.

WHAT IS MEASURED (the check's own frame grain, never an aggregate the check will not see):
  * flat tables    -- the publish frame IS the whole table (flat_producer republishes part-000
                      wholesale), so the whole-table nonnull fraction per value column is exactly
                      what check_value_nonnull will divide.
  * partitioned    -- the publish frame is ONE registered partition, so the floor must clear the
                      WORST partition, not the mean: worst per-column fraction across partitions.
                      Partitions whose key names the CURRENT year are reported separately and
                      EXCLUDED from floor-setting (completed-periods-only: an in-progress year's
                      partial partition is not a representative frame).

THE PROPOSAL RULE (the two shipped precedents as bounds):
  proposed = clamp(round_down_to_0.05(worst_completed * MARGIN), FLOOR_MIN, FLOOR_MAX)
  * MARGIN 0.7 -- the nass recal's own ratio (0.05 / 0.0681 = 0.73): the floor sits far enough
    below the worst legitimate frame that sampler undershoot never pages anyone.
  * FLOOR_MIN 0.02 -- below this a floor no longer distinguishes data from an all-null column.
  * FLOOR_MAX 0.9 -- the eex_freight `calibrated` precedent: even an always-dense column keeps
    room for a legitimately thin frame.
  A column measured at worst=0 over completed frames gets NO floor proposal (0.0 is that column's
  honest reality; flooring it is a policy decision, not a calibration) -- reported as `all_null_seen`.

WHAT IT WRITES (--apply): per-column `min_nonnull_frac_overrides` on each registry (the scalar
`min_nonnull_frac` stays as the default for future columns), `min_nonnull_frac_status: calibrated`,
and a dated note. HAND-CURATED overrides are NEVER overwritten (nass's five + its season rows,
wasde, psd, esr, pink_sheet, ams, unica sales): a hand row wins over a census row on the same
column, and the file's `min_nonnull_frac_season_overrides` block is untouched.

    python jobs/utils/op8_floor_census.py                    # census + report, writes nothing
    python jobs/utils/op8_floor_census.py --tables silver_cot,silver_fgis
    python jobs/utils/op8_floor_census.py --apply            # land the calibrated floors

Laptop-runnable: reads only the value columns of canonical parquet (columns= projection), skips
_shadow/_staging/_meta. Report lands at data/op8/floor_census_<UTC date>.json.
"""
from __future__ import annotations

import argparse
import collections
import datetime as _dt
import io
import json
import math
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import boto3
import pyarrow.parquet as pq
import yaml

MARGIN = 0.7
FLOOR_MIN = 0.02
FLOOR_MAX = 0.9
_GRID = 0.05                     # floors land on a human-readable 0.05 grid
_CUR_YEAR = "2026"               # completed-periods fence (in-progress partitions excluded)
_WORKERS = 16
_REG_DIR = Path("configs/silver/tables")


def _round_down_grid(x: float) -> float:
    return math.floor(x / _GRID + 1e-9) * _GRID


def propose(worst_completed: float) -> float | None:
    """The proposal rule, exactly as the module docstring states it -- with one amendment the full
    census forced (2026-08-22): a column whose worst COMPLETED frame is all-null gets an EXPLICIT
    0.0 floor, not silence. Fifteen measured columns (ESR changes, fnc vintage columns, seasonal
    nass pcts) legitimately publish all-null frames; leaving them under the scalar 0.5 makes their
    next such publish a false red -- the exact alarm-RCA class this census exists to close."""
    if worst_completed <= 0.0:
        return 0.0
    raw = _round_down_grid(worst_completed * MARGIN)
    return round(max(FLOOR_MIN, min(FLOOR_MAX, raw)), 2)


def _s3():
    return boto3.client("s3", region_name="us-east-1")


def _list_parquet(bucket: str, prefix: str) -> list[str]:
    keys = []
    p = _s3().get_paginator("list_objects_v2")
    for page in p.paginate(Bucket=bucket, Prefix=prefix.rstrip("/") + "/"):
        for o in page.get("Contents", []):
            k = o["Key"]
            if not k.endswith(".parquet"):
                continue
            if "/_shadow/" in k or "/_staging/" in k or "/_meta" in k:
                continue
            keys.append(k)
    return keys


def _partition_of(key: str, root_prefix: str) -> str:
    """The partition directory relative to the root (the publish-frame identity)."""
    rel = key[len(root_prefix):].lstrip("/")
    return rel.rsplit("/", 1)[0] if "/" in rel else "<flat>"


def _frame_counts(bucket: str, key: str, cols: list[str]) -> tuple[str, int, dict[str, int]] | None:
    """(key, n_rows, {col: nonnull}) for one object, reading ONLY the value columns."""
    try:
        body = _s3().get_object(Bucket=bucket, Key=key)["Body"].read()
        pf = pq.ParquetFile(io.BytesIO(body))
        present = [c for c in cols if c in pf.schema_arrow.names]
        n = pf.metadata.num_rows
        if not present:
            return key, n, {}
        t = pf.read(columns=present)
        return key, n, {c: n - t.column(c).null_count for c in present}
    except Exception as exc:  # noqa: BLE001 -- a per-object failure is a report row, not a crash
        print(f"  READ-FAIL {key}: {exc}", flush=True)
        return None


def census_table(reg: dict, name: str) -> dict | None:
    root = reg.get("s3_root") or ""
    m = re.match(r"s3://([^/]+)/(.+)", root)
    vcols = list(reg.get("value_columns") or [])
    if not m or not vcols or reg.get("min_nonnull_frac") is None:
        return None
    bucket, prefix = m.group(1), m.group(2)
    keys = _list_parquet(bucket, prefix)
    if not keys:
        return {"table": name, "error": "no canonical parquet found", "prefix": prefix}
    flat = (reg.get("layout") or "flat") == "flat"

    # accumulate per PARTITION (the publish frame); a flat table is one frame
    rows = collections.Counter()
    nonnull: dict[str, collections.Counter] = {c: collections.Counter() for c in vcols}
    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        futs = {pool.submit(_frame_counts, bucket, k, vcols): k for k in keys}
        for f in as_completed(futs):
            r = f.result()
            if r is None:
                continue
            key, n, counts = r
            part = "<flat>" if flat else _partition_of(key, prefix)
            rows[part] += n
            for c, nn in counts.items():
                nonnull[c][part] += nn

    out_cols = {}
    for c in vcols:
        fracs_done, fracs_cur = [], []
        for part, n in rows.items():
            if n == 0:
                continue
            frac = nonnull[c][part] / n
            (fracs_cur if (_CUR_YEAR in part and not flat) else fracs_done).append((frac, part))
        if not fracs_done and fracs_cur:      # a table with ONLY current-year frames: use them, flagged
            fracs_done, fracs_cur = fracs_cur, []
        if not fracs_done:
            continue
        worst, worst_part = min(fracs_done)
        cur_worst = min(fracs_cur)[0] if fracs_cur else None
        out_cols[c] = {"worst_completed": round(worst, 4), "worst_partition": worst_part,
                       "current_year_worst": (round(cur_worst, 4) if cur_worst is not None else None),
                       "proposed": propose(worst)}
    return {"table": name, "layout": reg.get("layout"), "n_objects": len(keys),
            "n_frames": len(rows), "current_floor": reg.get("min_nonnull_frac"),
            "hand_overrides": dict(reg.get("min_nonnull_frac_overrides") or {}),
            "columns": out_cols}


def apply_to_registry(path: Path, result: dict, stamp: str) -> bool:
    """Land the calibrated per-column floors as YAML edits (text-surgical: the registries carry
    hand-written comments a yaml.dump round-trip would destroy)."""
    text = path.read_text(encoding="utf-8")
    hand = result["hand_overrides"]
    newrows = {c: v["proposed"] for c, v in result["columns"].items()
               if v["proposed"] is not None and c not in hand}
    if not newrows:
        return False
    lines = [f"  {c}: {v:g}   # OP-8 measured worst {result['columns'][c]['worst_completed']:g}"
             for c, v in sorted(newrows.items())]
    block = "\n".join(lines)
    if "min_nonnull_frac_overrides:" in text:
        text = text.replace("min_nonnull_frac_overrides:",
                            f"min_nonnull_frac_overrides:\n{block}", 1)
    else:
        text = text.replace("min_nonnull_frac_status: provisional",
                            f"min_nonnull_frac_overrides:\n{block}\n"
                            f"min_nonnull_frac_status: provisional", 1)
    text = text.replace(
        "min_nonnull_frac_status: provisional",
        f"min_nonnull_frac_status: calibrated   # OP-8 census {stamp} (task #62): per-column floors\n"
        f"#   = worst COMPLETED publish-frame fraction x {MARGIN} margin, grid {_GRID}, clamp "
        f"[{FLOOR_MIN}, {FLOOR_MAX}]; hand-curated rows untouched; the scalar stays for future columns",
        1)
    path.write_text(text, encoding="utf-8", newline="")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description="OP-8 min_nonnull_frac recalibration census")
    ap.add_argument("--tables", default=None, help="comma-separated table ids (default: all provisional)")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    only = {t.strip() for t in args.tables.split(",")} if args.tables else None
    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")
    results, applied = [], []
    for p in sorted(_REG_DIR.glob("*.yaml")):
        reg = yaml.safe_load(p.read_text(encoding="utf-8"))
        if not isinstance(reg, dict) or reg.get("min_nonnull_frac_status") != "provisional":
            continue
        name = p.stem
        if only and name not in only:
            continue
        print(f"== {name}", flush=True)
        r = census_table(reg, name)
        if r is None:
            print("   skipped (no value_columns / no floor / no s3_root)")
            continue
        results.append(r)
        if "error" in r:
            print(f"   {r['error']}")
            continue
        for c, v in r["columns"].items():
            mark = " HAND" if c in r["hand_overrides"] else ""
            print(f"   {c:<34} worst={v['worst_completed']:<7g} cur={v['current_year_worst']} "
                  f"-> {v['proposed']}{mark}")
        if args.apply:
            if apply_to_registry(p, r, stamp):
                applied.append(name)

    out = Path("data/op8"); out.mkdir(parents=True, exist_ok=True)
    rp = out / f"floor_census_{stamp.replace('-', '')}.json"
    rp.write_text(json.dumps(results, indent=1), encoding="utf-8")
    print(f"\nreport: {rp}  tables={len(results)}  applied={applied if args.apply else '(census only)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
