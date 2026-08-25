"""C-2 NASS value-axis census -- the MEASURING TOOL behind data/dec_p0/nass_statcat_census.json.

Measure only, ASCII stdout. Streams the raw QuickStats crops object the estate already owns
(qs.crops.txt.gz, ~1.1 GB gz) and tallies statisticcat_desc x agg_level_desc x commodity_desc,
split by the ANNUAL lane's two admission gates. This is the census that sized the
``_RECORDED_STAT_CAT_EXCLUSIONS`` / ``_RECORDED_COMMODITY_EXCLUSIONS`` registries in
``src/leviathan/transforms/raw_to_bronze/usda_nass.py`` -- committed BECAUSE those registries pin
290 literals against its output, and an in-source provenance pointer that resolves to no tool in
the repo is the "4 text producers in NO git ref" defect class (Lane-6 review, major 3).

THE GATES ARE IMPORTED, NEVER MIRRORED: the 2026-08-25 execution ran with hand-mirrored copies of
``_ANNUAL_STAT_CATS`` / ``_ANNUAL_COMMODITY_MAP`` (verified equal at the time); a committed tool
that mirrors a frozenset it can import is a string-identity drift waiting to be measured wrong.
If the transform's gates move, this census MEANS something different -- which is exactly what the
import makes visible.

The banked artifact (data/dec_p0/nass_statcat_census.json) is this raw census plus derived
registry-shaped sections (full_tallies / answers / verdicts_vs_plan) assembled in the same 08-25
session; its every count reconciled against the registries to the row by the Lane-6 adversarial
review. A re-measure re-runs this tool against a NEWER snapshot key and re-derives; it never edits
the banked artifact in place.

    python jobs/utils/nass_value_axis_census.py                       # default 2026-08-18 snapshot
    python jobs/utils/nass_value_axis_census.py --key raw/production/source=usda_nass/...
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
from collections import Counter

import boto3
from boto3.s3.transfer import TransferConfig

from leviathan.transforms.bronze_to_silver.usda_nass_annual import _ANNUAL_COMMODITY_MAP
from leviathan.transforms.raw_to_bronze.usda_nass import _ANNUAL_STAT_CATS

_DEFAULT_BUCKET = os.environ.get("LEVIATHAN_BUCKET", "leviathan-dev-shahem-001")
_DEFAULT_KEY = "raw/production/source=usda_nass/sector=crops/download_date=2026-08-18/qs.crops.txt.gz"
_ADMITTED_AGG = frozenset({"NATIONAL", "STATE"})   # the silver annual lane's agg narrowing


def log(m: str) -> None:
    print(m, flush=True)


def fetch(bucket: str, key: str, local: str) -> dict:
    s3 = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    head = s3.head_object(Bucket=bucket, Key=key)
    meta = {
        "bucket": bucket,
        "key": key,
        "content_length_bytes": head["ContentLength"],
        "last_modified_utc": head["LastModified"].isoformat(),
        "etag": head["ETag"].strip('"'),
        "storage_class": head.get("StorageClass", "STANDARD"),
    }
    log("HEAD bytes=%d last_modified=%s" % (meta["content_length_bytes"], meta["last_modified_utc"]))
    if os.path.exists(local) and os.path.getsize(local) == meta["content_length_bytes"]:
        log("local copy already complete, skipping download")
        return meta
    cfg = TransferConfig(multipart_threshold=64 * 1024 * 1024,
                         multipart_chunksize=64 * 1024 * 1024,
                         max_concurrency=8)
    state = {"n": 0}

    def cb(n: int) -> None:
        state["n"] += n
        if state["n"] % (200 * 1024 * 1024) < n:
            log("downloaded %d MB" % (state["n"] // (1024 * 1024)))

    s3.download_file(bucket, key, local, Config=cfg, Callback=cb)
    log("download complete size=%d" % os.path.getsize(local))
    return meta


def census(local: str) -> dict:
    mapped_keys = frozenset(_ANNUAL_COMMODITY_MAP)
    total = 0
    malformed = 0
    stat_agg: Counter = Counter()          # (stat, agg) -> rows
    stat_total: Counter = Counter()        # stat -> rows
    agg_total: Counter = Counter()         # agg -> rows
    sector_total: Counter = Counter()      # sector -> rows
    adm_ns_commodity: Counter = Counter()  # admitted stat cats, NATIONAL/STATE -> commodity rows
    adm_all_commodity: Counter = Counter() # admitted stat cats, ANY agg -> commodity rows
    resid_ns_commodity: Counter = Counter()
    # residual stat cats restricted to the mapped commodities (what a value-axis widening alone
    # would unlock, holding the commodity axis fixed -- the "2.8x prize" cell)
    resid_mapped_ns_stat: Counter = Counter()
    header = None
    idx: dict[str, int] = {}

    with gzip.open(local, "rt", encoding="latin-1", newline="") as fh:
        for line in fh:
            if header is None:
                header = [c.strip().lower().replace(" ", "_").replace("%", "pct")
                          for c in line.rstrip("\r\n").split("\t")]
                for name in ("statisticcat_desc", "agg_level_desc", "commodity_desc", "sector_desc"):
                    if name not in header:
                        raise SystemExit("MISSING COLUMN %s ; header=%r" % (name, header))
                    idx[name] = header.index(name)
                log("header cols=%d" % len(header))
                continue
            f = line.rstrip("\r\n").split("\t")
            if len(f) != len(header):
                malformed += 1
                if malformed <= 3:
                    log("MALFORMED nfields=%d at row %d" % (len(f), total))
                if len(f) <= max(idx.values()):
                    continue
            total += 1
            stat = f[idx["statisticcat_desc"]].strip().upper()
            agg = f[idx["agg_level_desc"]].strip().upper()
            comm = f[idx["commodity_desc"]].strip().upper()
            sec = f[idx["sector_desc"]].strip().upper()
            stat_agg[(stat, agg)] += 1
            stat_total[stat] += 1
            agg_total[agg] += 1
            sector_total[sec] += 1
            if stat in _ANNUAL_STAT_CATS:
                adm_all_commodity[comm] += 1
                if agg in _ADMITTED_AGG:
                    adm_ns_commodity[comm] += 1
            elif agg in _ADMITTED_AGG:
                resid_ns_commodity[comm] += 1
                if comm in mapped_keys:
                    resid_mapped_ns_stat[stat] += 1
            if total % 5_000_000 == 0:
                log("rows %d" % total)

    log("TOTAL ROWS %d malformed_lines %d" % (total, malformed))
    return {
        "total_rows": total,
        "malformed_lines": malformed,
        "header": header,
        "gates": {"admitted_stat_cats": sorted(_ANNUAL_STAT_CATS),
                  "admitted_agg": sorted(_ADMITTED_AGG),
                  "annual_commodity_map_keys": sorted(mapped_keys)},
        "stat_total": dict(stat_total),
        "agg_total": dict(agg_total),
        "sector_total": dict(sector_total),
        "stat_agg": {"%s||%s" % k: v for k, v in stat_agg.items()},
        "admitted_ns_commodity": dict(adm_ns_commodity),
        "admitted_allagg_commodity": dict(adm_all_commodity),
        "residual_ns_commodity": dict(resid_ns_commodity),
        "residual_mapped_ns_stat": dict(resid_mapped_ns_stat),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="NASS value-axis census (measure only)")
    ap.add_argument("--bucket", default=_DEFAULT_BUCKET)
    ap.add_argument("--key", default=_DEFAULT_KEY)
    ap.add_argument("--local", default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                    "qs.crops.txt.gz"))
    ap.add_argument("--out", default="data/dec_p0/nass_statcat_census_raw.json")
    args = ap.parse_args()
    meta = fetch(args.bucket, args.key, args.local)
    payload = census(args.local)
    payload["s3_object"] = meta
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1, sort_keys=True)
    log("WROTE %s" % args.out)


if __name__ == "__main__":
    main()
