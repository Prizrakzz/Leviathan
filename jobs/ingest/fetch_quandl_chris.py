"""Fetch Quandl CHRIS continuous futures and write raw JSON + bronze to S3.

Downloads 36 series (12 slugs × C1/C2/C3 tenors) from the Nasdaq Data Link
(formerly Quandl) CHRIS dataset and writes:

    raw/production/source=quandl_chris/{slug}/tenor={n}/part-000.json
    bronze/production/source=quandl_chris/{slug}/tenor={n}/part-000.parquet

Prerequisites
-------------
A **free** Nasdaq Data Link API key is required.
  1. Register at https://data.nasdaq.com/sign-up (email only, no payment)
  2. Copy your API key from your account dashboard
  3. Add to .env or environment: ``NASDAQ_API_KEY=your_key_here``

The CHRIS dataset is permanently free.  The 403 encountered without a key
is Cloudflare blocking anonymous HTTP, not a paywall.

API endpoint
------------
    https://data.nasdaq.com/api/v3/datasets/{dataset_id}.json
        ?api_key={key}&start_date={YYYY-MM-DD}&order=asc

CHRIS dataset IDs (verified against Quandl documentation):
    corn_cbot              CHRIS/CME_C{n}
    soybeans_cbot          CHRIS/CME_S{n}
    soybean_oil_cbot       CHRIS/CME_BO{n}
    soybean_meal_cbot      CHRIS/CME_SM{n}
    soft_red_winter_wheat  CHRIS/CME_W{n}
    hard_red_winter_wheat  CHRIS/CME_KW{n}
    arabica_coffee         CHRIS/ICE_KC{n}
    cocoa                  CHRIS/ICE_CC{n}
    cotton                 CHRIS/ICE_CT{n}
    raw_sugar              CHRIS/ICE_SB{n}
    rough_rice_cbot        CHRIS/CME_RR{n}  (may end Oct 2021 — CBOT delisted)
    frozen_orange_juice    CHRIS/ICE_OJ{n}

Rate limits (free tier): 300 calls/10s, 2000 calls/10min.
With 1s polite delay: 36 calls ≈ 36 seconds total.

Usage
-----
    python jobs/ingest/fetch_quandl_chris.py
    python jobs/ingest/fetch_quandl_chris.py --dry-run
    python jobs/ingest/fetch_quandl_chris.py --slugs corn_cbot soybeans_cbot
    python jobs/ingest/fetch_quandl_chris.py --tenors 1 3   (C1 and C3 only)
    python jobs/ingest/fetch_quandl_chris.py --start-date 2000-01-01
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
from leviathan.storage.paths import bronze_chris_key, raw_chris_key
from leviathan.storage.s3 import get_thread_local_s3_client, upload_bytes_to_s3
from leviathan.transforms.raw_to_bronze.quandl_chris import extract_chris_bronze

logger = get_logger("fetch_quandl_chris")

_API_BASE     = "https://data.nasdaq.com/api/v3/datasets"
_TIMEOUT      = 30
_POLITE_DELAY = 1.0   # seconds between requests (free tier allows 300/10s)
_DEFAULT_START = "1990-01-01"   # ~35 years of history

# CHRIS dataset ID prefix per slug (append tenor number to get full ID)
CHRIS_MAP: dict[str, str] = {
    "corn_cbot":                    "CHRIS/CME_C",
    "soybeans_cbot":                "CHRIS/CME_S",
    "soybean_oil_cbot":             "CHRIS/CME_BO",
    "soybean_meal_cbot":            "CHRIS/CME_SM",
    "soft_red_winter_wheat_cbot":   "CHRIS/CME_W",
    "hard_red_winter_wheat_kcbt":   "CHRIS/CME_KW",
    "arabica_coffee":               "CHRIS/ICE_KC",
    "cocoa":                        "CHRIS/ICE_CC",
    "cotton":                       "CHRIS/ICE_CT",
    "raw_sugar":                    "CHRIS/ICE_SB",
    "rough_rice_cbot":              "CHRIS/CME_RR",
    "frozen_orange_juice":          "CHRIS/ICE_OJ",
}


def _fetch_one(
    slug: str,
    tenor: int,
    api_key: str,
    start_date: str,
    bucket: str,
    aws_region: str,
    s3_client,
    dry_run: bool,
    force: bool,
) -> bool:
    """Fetch one (slug, tenor) series. Returns True on success."""
    prefix  = CHRIS_MAP[slug]
    ds_id   = f"{prefix}{tenor}"
    url     = f"{_API_BASE}/{ds_id}.json"
    r_key   = raw_chris_key(slug, tenor)
    b_key   = bronze_chris_key(slug, tenor)

    if not force and not dry_run:
        try:
            s3_client.head_object(Bucket=bucket, Key=b_key)
            logger.debug("skip (bronze exists) %s C%d", slug, tenor)
            return True
        except Exception:
            pass

    params = {"api_key": api_key, "start_date": start_date, "order": "asc"}
    try:
        resp = requests.get(url, params=params, timeout=_TIMEOUT)
        resp.raise_for_status()
        raw_bytes = resp.content
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            logger.warning("CHRIS %s C%d: 404 (dataset may not exist)", slug, tenor)
        else:
            logger.exception("HTTP error fetching %s C%d", slug, tenor)
        return False
    except requests.RequestException:
        logger.exception("Request failed: %s C%d", slug, tenor)
        return False

    # Quick validation
    try:
        payload = json.loads(raw_bytes)
        rows = payload.get("dataset", {}).get("data", [])
        logger.info("CHRIS %s C%d: %d data rows", slug, tenor, len(rows))
        if not rows:
            logger.warning("CHRIS %s C%d: no data rows", slug, tenor)
    except Exception:
        logger.exception("Invalid JSON for %s C%d", slug, tenor)
        return False

    if dry_run:
        logger.info("dry-run  %s C%d: would write %s", slug, tenor, r_key)
        return True

    # Write raw JSON
    upload_bytes_to_s3(raw_bytes, bucket, r_key, aws_region)
    logger.info("Raw written → %s", r_key)

    # Bronze transform
    try:
        df = extract_chris_bronze(raw_bytes, slug, tenor, ds_id)
    except ValueError:
        logger.exception("Bronze transform failed: %s C%d", slug, tenor)
        return False

    if df.empty:
        logger.warning("CHRIS %s C%d: empty bronze — skipping write", slug, tenor)
        return True

    buf = io.BytesIO()
    df.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
    s3_client.put_object(
        Bucket=bucket, Key=b_key, Body=buf.getvalue(),
        ContentType="application/octet-stream",
    )
    logger.info("Bronze written → %s  rows=%d", b_key, len(df))
    return True


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        stream=sys.stderr,
    )
    load_env()

    parser = argparse.ArgumentParser(
        description="Fetch Quandl CHRIS continuous futures → raw JSON + bronze Parquet"
    )
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    parser.add_argument("--api-key", default=None, dest="api_key",
                        help="Nasdaq Data Link API key (or set NASDAQ_API_KEY env var)")
    parser.add_argument("--slugs", nargs="+", default=list(CHRIS_MAP.keys()), metavar="SLUG")
    parser.add_argument("--tenors", nargs="+", type=int, default=[1, 2, 3], metavar="N")
    parser.add_argument("--start-date", default=_DEFAULT_START, dest="start_date",
                        metavar="YYYY-MM-DD")
    parser.add_argument("--force-overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    bucket     = args.bucket     or get_required_env("LEVIATHAN_BUCKET")
    aws_region = args.aws_region or get_required_env("AWS_REGION")
    api_key    = (
        args.api_key
        or __import__("os").environ.get("NASDAQ_API_KEY")
        or __import__("os").environ.get("QUANDL_API_KEY")
    )

    if not api_key:
        logger.error(
            "No API key found.  Register free at https://data.nasdaq.com/sign-up "
            "then set NASDAQ_API_KEY in your environment or .env file."
        )
        sys.exit(1)

    unknown = set(args.slugs) - set(CHRIS_MAP)
    if unknown:
        logger.error("Unknown slugs: %s", sorted(unknown))
        sys.exit(1)

    s3 = get_thread_local_s3_client(aws_region)
    total   = len(args.slugs) * len(args.tenors)
    errors  = 0
    counter = 0

    logger.info(
        "CHRIS ingest  slugs=%d  tenors=%s  start=%s  dry_run=%s",
        len(args.slugs), args.tenors, args.start_date, args.dry_run,
    )

    for slug in args.slugs:
        for tenor in args.tenors:
            ok = _fetch_one(
                slug, tenor, api_key, args.start_date,
                bucket, aws_region, s3, args.dry_run, args.force_overwrite,
            )
            if not ok:
                errors += 1
            counter += 1
            if counter < total:
                time.sleep(_POLITE_DELAY)

    label = "dry-run" if args.dry_run else "written"
    logger.info("Done — %s=%d  errors=%d / %d", label, total - errors, errors, total)
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
