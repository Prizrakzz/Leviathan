"""The one-command minagro pipeline: capture -> bronze -> silver, idempotent at every layer.

Run WEEKLY from a RESIDENTIAL vantage (measured 2026-08-20: Cloudflare passes local headless
Chromium cleanly and refuses Fargate outright, so this pipeline is deliberately local -- the one
laptop-side scheduled command in the estate). The page publishes ~Friday 09:05 Kyiv (== Amman
time); run any time Friday afternoon. A re-run is free: the fetch skips an existing capture,
bronze skips parsed captures, and silver is a byte-stable whole-table rewrite.

    python jobs/ingest/run_minagro_pipeline.py

``--skip-fetch`` runs the bronze+silver FOLD ONLY, over whatever raw captures already exist. That
is the mode ``jobs/ingest/backfill_minagro_wayback.py`` hands off to: the backfill lands archived
captures itself, and re-running the live browser leg to fold them would be a pointless hit on a
Cloudflare-fronted origin (and impossible from a vantage that has no browser at all). It is also
the repair mode for a raw capture that landed but never folded.

    python jobs/ingest/run_minagro_pipeline.py --skip-fetch

Exit codes: 0 = pipeline green (including nothing-new); 6/7 propagate the fetcher's refusal
codes (6 = the venue served a non-table, 7 = the Cloudflare challenge did not clear); 1 = a
real failure in bronze/silver.
"""
from __future__ import annotations

import argparse
import io
import subprocess
import sys
from pathlib import Path

import boto3
import pandas as pd
import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from leviathan.common.logging import get_logger  # noqa: E402
from leviathan.silver import flat_producer  # noqa: E402
from leviathan.transforms.bronze_to_silver.minagro_grain_exports import (  # noqa: E402
    build_silver,
)
from leviathan.transforms.raw_to_bronze.minagro_grain_exports import (  # noqa: E402
    build_bronze,
)

logger = get_logger("run_minagro_pipeline")
# The estate's get_logger emits nothing until a handler exists; the fetcher configures one in its
# own __main__, but this driver is the entry point here -- without this line the whole pipeline
# runs MUTE (bronze+silver written with zero output, observed on first run 2026-08-20).
import logging  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")

BUCKET = "leviathan-dev-shahem-001"
RAW_PREFIX = "raw/production/source=minagro_grain_exports/"
BRONZE_PREFIX = "bronze/production/source=minagro_grain_exports/"
SILVER_KEY = "silver/minagro_grain_exports/part-000.parquet"
CONTRACT = REPO / "configs" / "silver" / "tables" / "silver_minagro_grain_exports.yaml"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="minagro capture -> bronze -> silver, idempotent")
    ap.add_argument("--skip-fetch", action="store_true",
                    help="fold the raw captures already in S3 into bronze+silver without running "
                         "the live browser leg (the backfill hand-off; also the re-fold repair)")
    args = ap.parse_args(argv)

    if args.skip_fetch:
        logger.info("--skip-fetch: the live capture leg is NOT run; folding the raw captures "
                    "already present under %s", RAW_PREFIX)
    else:
        fetch = subprocess.run(
            [sys.executable, str(REPO / "jobs" / "ingest" / "fetch_minagro_grain_exports.py")],
            cwd=str(REPO),
        )
        if fetch.returncode not in (0,):
            logger.error("fetch exited %d -- bronze/silver NOT run (refusals never land bytes)",
                         fetch.returncode)
            return fetch.returncode

    s3 = boto3.client("s3", region_name="us-east-1")
    pages = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=BUCKET, Prefix=RAW_PREFIX):
        for obj in page.get("Contents", []):
            if obj["Key"].endswith("/page.html"):
                pages.append(obj["Key"])
    if not pages:
        logger.error("no raw captures under %s -- nothing to build", RAW_PREFIX)
        return 1
    logger.info("raw captures: %d", len(pages))

    frames = []
    built = skipped = 0
    for raw_key in sorted(pages):
        as_of = raw_key.split("as_of=")[1].split("/")[0]
        bronze_key = f"{BRONZE_PREFIX}as_of={as_of}/part-000.parquet"
        try:
            s3.head_object(Bucket=BUCKET, Key=bronze_key)
            frames.append(pd.read_parquet(
                io.BytesIO(s3.get_object(Bucket=BUCKET, Key=bronze_key)["Body"].read())))
            skipped += 1
            continue
        except s3.exceptions.ClientError:
            pass
        payload = s3.get_object(Bucket=BUCKET, Key=raw_key)["Body"].read().decode("utf-8")
        df, stats = build_bronze(payload, as_of_date=f"{as_of[:4]}-{as_of[4:6]}-{as_of[6:]}")
        buf = io.BytesIO()
        df.to_parquet(buf, index=False)
        s3.put_object(Bucket=BUCKET, Key=bronze_key, Body=buf.getvalue())
        logger.info("bronze written -> s3://%s/%s (%d rows)", BUCKET, bronze_key, len(df))
        frames.append(df)
        built += 1
    logger.info("bronze: %d built, %d already present", built, skipped)

    silver = build_silver(frames)
    contract = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    body = flat_producer.encode_parquet(silver, contract)
    s3.put_object(Bucket=BUCKET, Key=SILVER_KEY, Body=body)
    logger.info("silver written -> s3://%s/%s (%d rows, %d captures, %d bytes)",
                BUCKET, SILVER_KEY, len(silver), silver["as_of_date"].nunique(), len(body))
    return 0


if __name__ == "__main__":
    sys.exit(main())
