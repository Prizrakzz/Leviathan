"""AWS Batch Fargate task: silver_futures_eod -> gold_futures_spreads (flat, daily, LONG shape).

Reads exactly the registry pairs' leg prefixes DIRECTLY from S3 (the gold_board_crush no-Athena
pattern -- listing the other slugs to throw them away is the LIST-storm class), applies the ONE
front-month roll rule per leg, computes each same-unit spread, and writes a single flat parquet to
``gold/futures_spreads/part-000.parquet``.

The compute core is ``leviathan.transforms.gold.futures_spreads`` (pure, unit-tested); this file is
only the S3 I/O + orchestration shell. DDL: sql/athena/ddl/gold_futures_spreads.sql (flat,
non-projected); the pg mirror rides load_pg_numbers.

PARTIAL-PAIR POSTURE (deliberately DIFFERENT from the crush's fail-closed): the crush is ONE
three-leg object -- a missing leg means no table. This table is N independent pairs; a pair whose
venue is dark emits nothing FOR THAT PAIR (its ledger says so, loudly) while the others publish.
The zero-row fence still refuses to overwrite the published table with an empty frame.

Usage:
    python jobs/batch/gold_futures_spreads_task.py
    python jobs/batch/gold_futures_spreads_task.py --dry-run true
"""
from __future__ import annotations

import argparse
import io
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import pyarrow.parquet as pq

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.transforms.gold.futures_spreads import (
    INPUT_COLUMNS,
    PHYSICAL_COLUMNS,
    REFUSED_DATES,
    SPREAD_RULE_VERSION,
    SPREADS,
    compute_futures_spreads,
)

logger = get_logger("gold_futures_spreads")

_SILVER_EOD = "silver/futures_eod"
_GOLD_KEY = "gold/futures_spreads/part-000.parquet"
_WORKERS = 16


def _read_leg(bucket: str, slug: str, region: str) -> pd.DataFrame:
    from leviathan.storage.s3 import (
        get_thread_local_s3_client,
        list_s3_keys,
        s3_download_with_retry,
    )

    prefix = f"{_SILVER_EOD}/leviathan_slug={slug}/"
    keys = list_s3_keys(bucket, prefix, suffix=".parquet", aws_region=region)
    if not keys:
        logger.warning("gold_futures_spreads: no objects under %s", prefix)
        return pd.DataFrame(columns=INPUT_COLUMNS)
    frames: list[pd.DataFrame] = []
    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        futs = {pool.submit(s3_download_with_retry, bucket, k,
                            get_thread_local_s3_client(region)): k for k in keys}
        for fut in as_completed(futs):
            k = futs[fut]
            try:
                body = fut.result()
            except Exception as exc:  # noqa: BLE001 -- one unreadable object must not lose the leg
                logger.error("gold_futures_spreads: failed to read %s (%s)", k, exc)
                continue
            df = pq.read_table(io.BytesIO(body)).to_pandas()
            df["leviathan_slug"] = slug          # Hive partition key: in the path, never the file
            frames.append(df)
    if not frames:
        return pd.DataFrame(columns=INPUT_COLUMNS)
    out = pd.concat(frames, ignore_index=True)
    logger.info("gold_futures_spreads: leg %s -> %d rows from %d objects", slug, len(out), len(keys))
    return out


def main(argv: list[str] | None = None) -> int:
    import logging
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s - %(message)s", stream=sys.stderr)
    ap = argparse.ArgumentParser(
        description="Compute gold_futures_spreads from the registry pairs of silver_futures_eod.")
    ap.add_argument("--dry-run", default="false", help="compute and log the shape, write nothing")
    args = ap.parse_args(argv)
    dry = str(args.dry_run).lower() in ("1", "true", "yes")

    load_env()
    bucket = get_required_env("S3_BUCKET")
    region = get_required_env("AWS_REGION")

    slugs = sorted({s for pair in SPREADS.values() for s in pair})
    legs = [_read_leg(bucket, slug, region) for slug in slugs]
    eod = pd.concat([f for f in legs if len(f)], ignore_index=True) if any(
        len(f) for f in legs) else pd.DataFrame(columns=INPUT_COLUMNS)

    gold = compute_futures_spreads(eod)

    for sid, ledger in sorted((gold.attrs.get(REFUSED_DATES) or {}).items()):
        logger.info("gold_futures_spreads: %s", ledger.render())

    if gold.empty:
        logger.error("gold_futures_spreads: computed ZERO rows from %d input rows -- refusing to "
                     "overwrite the published table with an empty one", len(eod))
        return 3

    per = gold.groupby("spread_id")["trade_date"].agg(["count", "min", "max"])
    for sid, r in per.iterrows():
        logger.info("gold_futures_spreads: %s rows=%d %s .. %s rule=%s",
                    sid, r["count"], r["min"], r["max"], SPREAD_RULE_VERSION)

    if dry:
        logger.info("gold_futures_spreads: --dry-run, nothing written")
        return 0

    from leviathan.storage.s3 import get_thread_local_s3_client

    body = gold[PHYSICAL_COLUMNS].copy()
    body.attrs = {}                              # the ledger is a RUN RECORD, never file metadata
    buf = io.BytesIO()
    body.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
    get_thread_local_s3_client(region).put_object(Bucket=bucket, Key=_GOLD_KEY, Body=buf.getvalue())
    logger.info("gold_futures_spreads: wrote %d rows to s3://%s/%s", len(body), bucket, _GOLD_KEY)
    return 0


if __name__ == "__main__":
    sys.exit(main())
