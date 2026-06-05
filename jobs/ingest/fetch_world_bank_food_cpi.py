"""Fetch World Bank DataBank food CPI data and write raw + bronze to S3.

Source
------
World Bank DataBank API — indicator FP.CPI.TOTL.ZG
    (Inflation, consumer prices, annual %)

    https://api.worldbank.org/v2/country/{ISO3}/indicator/FP.CPI.TOTL.ZG
        ?format=json&date=1960:2025&per_page=200

No API key required.  Free public API.  One request per country.
Response: two-element JSON array — [metadata, records].  Single page
(pages=1 confirmed for all four countries with per_page=200).

Countries
---------
    IND — India       (food CPI driver: wheat, rice export bans)
    RUS — Russia      (food CPI driver: wheat export quotas)
    IDN — Indonesia   (food CPI driver: CPO/palm oil export bans)
    UKR — Ukraine     (food CPI driver: wheat/corn export risk)

S3 layout
---------
    Raw:    raw/production/source=wb_food_cpi/country={ISO}/part-000.json
    Bronze: bronze/production/source=wb_food_cpi/country={ISO}/part-000.parquet

One raw JSON and one bronze Parquet per country.

Usage
-----
    python jobs/ingest/fetch_world_bank_food_cpi.py
    python jobs/ingest/fetch_world_bank_food_cpi.py --dry-run
    python jobs/ingest/fetch_world_bank_food_cpi.py --force-overwrite
    python jobs/ingest/fetch_world_bank_food_cpi.py --countries IND RUS
"""
from __future__ import annotations

import argparse
import io
import json
import logging
import sys
import time

import requests

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.paths import bronze_food_cpi_key, raw_food_cpi_key
from leviathan.storage.s3 import upload_bytes_to_s3
from leviathan.transforms.raw_to_bronze.world_bank_food_cpi import extract_food_cpi_bronze

logger = get_logger("fetch_world_bank_food_cpi")

_WB_URL_TEMPLATE = (
    "https://api.worldbank.org/v2/country/{iso}/indicator/FP.CPI.TOTL.ZG"
    "?format=json&date=1960:2025&per_page=200"
)
_TIMEOUT       = 30
_POLITE_DELAY  = 1.0   # seconds between requests — be a good citizen

# Countries to ingest (ordered by data richness)
_DEFAULT_COUNTRIES = ["IND", "RUS", "IDN", "UKR"]


def _write_parquet(data: bytes, bucket: str, key: str, aws_region: str) -> None:
    import boto3
    from leviathan.storage.s3 import _BOTO_RETRY_CONFIG
    s3 = boto3.client("s3", region_name=aws_region, config=_BOTO_RETRY_CONFIG)
    s3.put_object(Bucket=bucket, Key=key, Body=data,
                  ContentType="application/octet-stream")


def fetch_one(iso: str, bucket: str, aws_region: str, dry_run: bool,
              force: bool) -> bool:
    """Fetch and ingest one country.  Returns True on success, False on error."""
    url   = _WB_URL_TEMPLATE.format(iso=iso)
    r_key = raw_food_cpi_key(iso)
    b_key = bronze_food_cpi_key(iso)

    logger.info("Fetching %s …  url=%s", iso, url)

    try:
        resp = requests.get(url, timeout=_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException:
        logger.exception("HTTP fetch failed for %s", iso)
        return False

    raw_bytes = resp.content

    # Validate: response must be a 2-element JSON array
    try:
        payload = json.loads(raw_bytes)
        if not isinstance(payload, list) or len(payload) < 2:
            raise ValueError(f"unexpected structure: {type(payload)}")
        pages = payload[0].get("pages", "?")
        total = payload[0].get("total", "?")
        logger.info("%s: pages=%s  total_records=%s", iso, pages, total)
        if int(pages) > 1:
            logger.warning(
                "%s: API returned %s pages — only page 1 ingested. "
                "Increase per_page or add pagination loop.",
                iso, pages,
            )
    except (json.JSONDecodeError, ValueError, TypeError):
        logger.exception("Response from %s does not look like valid WB JSON", iso)
        return False

    if dry_run:
        non_null = sum(1 for r in payload[1] if r.get("value") is not None)
        logger.info("dry-run  %s: would write %s  non-null=%d", iso, r_key, non_null)
        return True

    # Write raw JSON
    upload_bytes_to_s3(raw_bytes, bucket, r_key, aws_region)
    logger.info("Raw written → s3://%s/%s", bucket, r_key)

    # Bronze transform
    try:
        df = extract_food_cpi_bronze(raw_bytes, iso)
    except ValueError:
        logger.exception("Bronze transform failed for %s", iso)
        return False

    buf = io.BytesIO()
    df.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
    _write_parquet(buf.getvalue(), bucket, b_key, aws_region)
    logger.info(
        "Bronze written → s3://%s/%s  rows=%d  years=%d–%d",
        bucket, b_key, len(df), int(df["year"].min()), int(df["year"].max()),
    )
    return True


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        stream=sys.stderr,
    )
    load_env()

    parser = argparse.ArgumentParser(
        description="Fetch World Bank food CPI → raw S3 + bronze Parquet"
    )
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    parser.add_argument(
        "--countries", nargs="+", default=_DEFAULT_COUNTRIES,
        metavar="ISO3",
        help=f"Countries to ingest (default: {' '.join(_DEFAULT_COUNTRIES)})",
    )
    parser.add_argument("--force-overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    bucket     = args.bucket     or get_required_env("LEVIATHAN_BUCKET")
    aws_region = args.aws_region or get_required_env("AWS_REGION")

    logger.info(
        "Food CPI ingest  countries=%s  dry_run=%s  force=%s",
        args.countries, args.dry_run, args.force_overwrite,
    )

    errors = 0
    for i, iso in enumerate(args.countries):
        ok = fetch_one(iso, bucket, aws_region, args.dry_run, args.force_overwrite)
        if not ok:
            errors += 1
        if i < len(args.countries) - 1:
            time.sleep(_POLITE_DELAY)

    logger.info(
        "Done — %d/%d countries OK  errors=%d",
        len(args.countries) - errors, len(args.countries), errors,
    )
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
