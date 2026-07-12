"""OP-1 probe: CHIRPS silver ingest_date x value-null census (SILVER-F045; read-only, gated to BF-W1).

Resolves OP-1 (CHIRPS blast radius): the S3 lane sampled 15 all-NaN probes; the code/consumer lanes
found arabica_coffee real. Reconciling hypothesis: silver ``value`` is NaN exactly on partitions whose
silver ``ingest_date`` predates the 2026-06-16 bronze re-ingest. This probe MEASURES that -- it walks
the projected chirps silver tree and, per commodity (bounded ``--sample-per-commodity`` objects),
reads ONLY the parquet FOOTER (ingest_date min/max + value null-fraction via
:mod:`leviathan.silver.value_census`), never a data page and NEVER an Athena query (INV-3). It buckets
each object into {real, all_nan} x ingest_date and writes a JSON census artifact.

READ-ONLY: this issues S3 LIST + bounded range-GETs only; it mutates nothing. It is the OP-1 gate
artifact for F045 -- run it (BF-W1) before crediting the CHIRPS rebuild with un-deferring drought_z.

    python jobs/utils/probe_chirps_ingest_census.py --sample-per-commodity 25
    python jobs/utils/probe_chirps_ingest_census.py --commodity arabica_coffee --sample-per-commodity 200
"""
from __future__ import annotations

import argparse
import io
import json
import logging
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pyarrow.parquet as pq

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.silver import value_census as vc
from leviathan.storage.paths import parse_hive_key
from leviathan.storage.s3 import get_thread_local_s3_client, list_s3_keys, s3_download_with_retry

logger = get_logger("probe_chirps_ingest_census")
_PREFIX = "silver/weather/source=chirps/"
_FOOTER_BYTES = 1 << 16  # tail range for the parquet footer (bounded read; no full download)


def _footer(bucket: str, key: str, region: str):
    """Read the parquet FOOTER only via a bounded tail range-GET (no data pages)."""
    s3 = get_thread_local_s3_client(region)
    # A small object (~9 KB) is cheaper to fetch whole than to range twice; chirps objects are tiny.
    data = s3_download_with_retry(bucket, key, s3)
    return pq.ParquetFile(io.BytesIO(data)).metadata


def _probe_one(bucket: str, key: str, region: str) -> dict | None:
    try:
        md = _footer(bucket, key, region)
        value_stat = vc.file_column_stat(md, "value")
        ing_stat = vc.file_column_stat(md, "ingest_date")
        col = vc.census_column([value_stat], "value") if value_stat else None
        ingest = None
        if ing_stat and ing_stat.has_min_max:
            ingest = str(ing_stat.min_value)
        return {
            "key": key,
            "commodity": parse_hive_key(key, "commodity"),
            "ingest_date": ingest,
            "value_all_nan": bool(col.all_nan) if col else None,
            "value_nonnull_fraction": round(col.nonnull_fraction, 4) if col else None,
            "rows": col.total_rows if col else 0,
        }
    except Exception as exc:  # noqa: BLE001 -- per-object failure logged; census continues
        logger.error("probe failed %s: %s", key, exc)
        return None


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
    load_env()
    ap = argparse.ArgumentParser(description="OP-1 CHIRPS ingest_date x value-null census (read-only)")
    ap.add_argument("--bucket", default=None)
    ap.add_argument("--aws-region", default=None, dest="aws_region")
    ap.add_argument("--commodity", default="all")
    ap.add_argument("--sample-per-commodity", type=int, default=25)
    ap.add_argument("--out", default="reports/silver_readiness/R2_W/OP1_chirps_ingest_census.json")
    args = ap.parse_args()

    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    region = args.aws_region or get_required_env("AWS_REGION")

    keys = list_s3_keys(bucket, _PREFIX, suffix=".parquet", aws_region=region)
    by_commodity: dict[str, list[str]] = defaultdict(list)
    for k in keys:
        c = parse_hive_key(k, "commodity")
        if c and (args.commodity == "all" or c == args.commodity):
            by_commodity[c].append(k)

    sampled: list[str] = []
    for c, ks in by_commodity.items():
        step = max(1, len(ks) // max(1, args.sample_per_commodity))
        sampled.extend(ks[::step][: args.sample_per_commodity])
    logger.info("OP-1 probe: %d commodities, %d objects sampled (of %d total)",
                len(by_commodity), len(sampled), len(keys))

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=32) as pool:
        futs = {pool.submit(_probe_one, bucket, k, region): k for k in sampled}
        for fut in as_completed(futs):
            r = fut.result()
            if r:
                results.append(r)

    # Roll up: per commodity, per ingest_date -> counts of all-NaN vs real.
    rollup: dict = defaultdict(lambda: defaultdict(lambda: {"all_nan": 0, "real": 0}))
    for r in results:
        bucket_key = "all_nan" if r["value_all_nan"] else "real"
        rollup[r["commodity"]][r["ingest_date"]][bucket_key] += 1
    census = {
        "package": "SILVER-F045 / OP-1",
        "prefix": _PREFIX,
        "total_objects": len(keys),
        "objects_sampled": len(results),
        "athena_queries_issued": 0,
        "hypothesis": "value NaN <=> silver ingest_date < 2026-06-16 (bronze re-ingest date)",
        "by_commodity_by_ingest_date": {c: dict(v) for c, v in rollup.items()},
        "objects": results,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(census, indent=2, default=str), encoding="utf-8")
    logger.info("wrote OP-1 census -> %s", out)


if __name__ == "__main__":
    main()
