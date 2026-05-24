"""Fetch USDA FAS Export Sales Reporting (ESR) data to raw S3.

Source
------
USDA FAS Export Sales Reporting (ESR) — weekly forward export commitments
    https://apps.fas.usda.gov/esrqs/#/home
    API: https://api.fas.usda.gov

Requires a free API key from https://api.data.gov/signup.
Set the key as environment variable FAS_API_KEY (never embed in URLs or code).

Rate limits
-----------
api.data.gov default: 1,000 requests/hour per API key (sliding window).
Full backfill (~360 requests) completes in ~6 min at 1.0s sleep — well under
the limit.  Do NOT use a thread pool for this endpoint.  It is a government
server, not a CDN; concurrency does not improve throughput and risks 429s.

Two modes
---------
backfill
    Fetch historical all-countries JSON for every (commodity_code, market_year)
    pair from start_year to end_year.  Historical years are static once closed.
    One file per (commodity_code, market_year).

    Default range: all target commodity codes, 1990 to current_year.

weekly
    Snapshot the current and next-crop marketing year for all target commodity
    codes.  ESR publishes new-crop forward sales before the season opens, so
    both years are relevant every Thursday.

    Partitioned by as_of date so each Thursday produces a new immutable object,
    preserving point-in-time correctness for backtested ML features.

S3 key structure
----------------
    backfill:
        raw/production/source=usda_esr/commodity_code={code}/market_year={year}/all_countries.json
    weekly:
        raw/production/source=usda_esr/commodity_code={code}/market_year={year}/as_of={YYYYMMDD}/all_countries.json

Update schedule
---------------
Run --mode weekly every Thursday after ESR publishes (~08:00 ET / 13:00 UTC).
The Airflow DAG ``esr_weekly_ingest`` handles this automatically at 14:00 UTC.

Idempotency
-----------
Pass ``--skip-existing-s3`` to skip keys already present in S3 (safe for re-runs).
Pass ``--dry-run`` to print S3 keys without making any API calls.
"""
from __future__ import annotations

import argparse
import logging
import datetime
import json
import time

import requests

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.paths import raw_esr_backfill_key, raw_esr_weekly_key
from leviathan.storage.raw_metadata import check_min_file_size, write_raw_s3_metadata
from leviathan.storage.s3 import s3_object_exists, upload_bytes_to_s3

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_API_BASE = "https://api.fas.usda.gov"
_API_KEY_ENV = "FAS_API_KEY"

# Government server — NOT a CDN.  Sequential requests only.
# 1.0s sleep keeps rate well under the api.data.gov 1,000 req/hour limit.
_BACKFILL_SLEEP = 1.0

_DOWNLOAD_TIMEOUT = 30  # seconds per request

# Minimum plausible JSON size.  ESR returns small arrays for sparse early years;
# 500 B catches HTML error pages returned by api.data.gov on auth failure.
_MIN_SIZE_BYTES = 500

# Commodity codes covered in scope for Leviathan.  Cotton and rice codes are
# reserved pending confirmation from /api/esr/commodities once an API key is
# in hand.
_TARGET_COMMODITY_CODES: list[int] = [101, 102, 103, 104, 107, 401, 701, 801, 901, 902]

# Marketing year start month per commodity group.  Wheat: Jun 1; Cotton/Rice:
# Aug 1; everything else (corn, soy, sorghum): Sep 1.
_WHEAT_CODES = frozenset({101, 102, 103, 104, 105, 106, 107, 201})
_COTTON_RICE_CODES = frozenset({1201, 1202, 1203, 1301, 1302, 3202})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _marketing_year_start_month(commodity_code: int) -> int:
    """Return the month (1-12) that opens the marketing year for this code."""
    if commodity_code in _WHEAT_CODES:
        return 6  # Jun 1
    if commodity_code in _COTTON_RICE_CODES:
        return 8  # Aug 1
    return 9  # Sep 1  (corn, soybeans, sorghum, oilseeds)


def _current_marketing_year(commodity_code: int, reference_date: datetime.date) -> int:
    """Return the marketing year that contains *reference_date* for this commodity.

    The marketing year is identified by its start year.  For example, if corn's
    marketing year starts Sep 1 and reference_date is May 2026, the current
    marketing year is 2025 (Sep 2025 – Aug 2026).

    Args:
        commodity_code: ESR commodity code.
        reference_date: The date to resolve against.
    """
    start_month = _marketing_year_start_month(commodity_code)
    if reference_date.month >= start_month:
        return reference_date.year
    return reference_date.year - 1


def _build_url(commodity_code: int, market_year: int) -> str:
    return (
        f"{_API_BASE}/api/esr/exports"
        f"/commodityCode/{commodity_code}"
        f"/allCountries"
        f"/marketYear/{market_year}"
    )


def _validate_json(data: bytes, url: str) -> None:
    """Raise RuntimeError if *data* is not a non-empty JSON array."""
    try:
        parsed = json.loads(data)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"ESR response from {url} is not valid JSON: {data[:200]!r}"
        ) from exc
    if not isinstance(parsed, list):
        raise RuntimeError(
            f"ESR response from {url} is not a JSON array: {type(parsed).__name__}"
        )
    if len(parsed) == 0:
        raise RuntimeError(
            f"ESR response from {url} returned an empty array — "
            "no data for this commodity/year combination."
        )


def _fetch_one(
    session: requests.Session,
    commodity_code: int,
    market_year: int,
    api_key: str,
) -> bytes | None:
    """Fetch all-countries ESR data for one (commodity_code, market_year).

    Returns raw JSON bytes on success.  Returns ``None`` if the API responds
    with 404 or an empty array (data not available for this year — expected
    for very early historical years).  Raises for all other errors.

    Args:
        session:        Shared requests Session.
        commodity_code: ESR commodity code.
        market_year:    Marketing year start year.
        api_key:        FAS API key (passed as X-Api-Key header, never in URL).
    """
    url = _build_url(commodity_code, market_year)
    logger.info("  GET %s", url)

    resp = session.get(url, timeout=_DOWNLOAD_TIMEOUT, headers={"X-Api-Key": api_key})

    if resp.status_code == 404:
        logger.info(
            "  [skip] 404 — no ESR data for commodity_code=%d market_year=%d",
            commodity_code, market_year,
        )
        return None

    if resp.status_code == 429:
        raise RuntimeError(
            f"ESR API rate limit hit (429) on commodity_code={commodity_code} "
            f"market_year={market_year}.  Increase _BACKFILL_SLEEP or request "
            "a higher rate limit at https://api.data.gov/contact/."
        )

    resp.raise_for_status()
    data = resp.content
    logger.info("    %.1f KB received", len(data) / 1024)

    try:
        _validate_json(data, url)
    except RuntimeError as exc:
        # Empty array means no data for this year — not a pipeline error.
        if "empty array" in str(exc):
            logger.info("  [skip] empty response — %s", exc)
            return None
        raise

    check_min_file_size(data, "usda_esr", context=url)
    return data


# ---------------------------------------------------------------------------
# Backfill
# ---------------------------------------------------------------------------

def run_backfill(
    commodity_codes: list[int],
    start_year: int,
    end_year: int,
    bucket: str,
    region: str,
    api_key: str,
    skip_existing: bool,
    dry_run: bool,
) -> None:
    """Fetch historical ESR JSON for all (commodity_code, market_year) pairs.

    Args:
        commodity_codes: List of ESR commodity codes to fetch.
        start_year:      First marketing year to fetch.
        end_year:        Last marketing year to fetch (inclusive).
        bucket:          S3 bucket name.
        region:          AWS region.
        api_key:         FAS API key.
        skip_existing:   Skip if the S3 key already exists.
        dry_run:         Print keys without fetching.
    """
    years = list(range(start_year, end_year + 1))
    total = len(commodity_codes) * len(years)
    logger.info(
        "Backfill: %d commodity codes × %d years = %d API calls",
        len(commodity_codes), len(years), total,
    )

    if dry_run:
        for code in commodity_codes:
            for year in years:
                print(f"[dry-run] s3://{bucket}/{raw_esr_backfill_key(code, year)}")
        return

    session = requests.Session()

    uploaded = skipped = failed = 0
    call_count = 0

    for code in commodity_codes:
        for i, year in enumerate(years):
            s3_key = raw_esr_backfill_key(code, year)

            if skip_existing and s3_object_exists(bucket, s3_key, region):
                logger.info("  [skip] already in S3: %s", s3_key)
                skipped += 1
                continue

            try:
                data = _fetch_one(session, code, year, api_key)
                if data is None:
                    skipped += 1
                else:
                    url = _build_url(code, year)
                    upload_bytes_to_s3(data, bucket, s3_key, region)
                    write_raw_s3_metadata(
                        bucket, s3_key, data, url, "application/json", region
                    )
                    logger.info("  → s3://%s/%s", bucket, s3_key)
                    uploaded += 1
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "  FAILED commodity_code=%d market_year=%d — %s", code, year, exc
                )
                failed += 1

            call_count += 1
            # Sleep between every API call — government server, not a CDN.
            if call_count < total:
                time.sleep(_BACKFILL_SLEEP)

    logger.info(
        "Backfill complete. uploaded=%d  skipped=%d  failed=%d",
        uploaded, skipped, failed,
    )
    if failed:
        raise SystemExit(f"{failed} request(s) failed — see log above.")


# ---------------------------------------------------------------------------
# Weekly snapshot
# ---------------------------------------------------------------------------

def run_weekly(
    commodity_codes: list[int],
    as_of_date: str,
    bucket: str,
    region: str,
    api_key: str,
    skip_existing: bool,
    dry_run: bool,
) -> None:
    """Snapshot current and new-crop marketing year ESR data for all codes.

    Both the current and next marketing year are fetched because ESR publishes
    new-crop forward sales before the season officially opens.  These early
    new-crop outstanding_sales are the esr_new_crop_sales_z signal.

    Args:
        commodity_codes: List of ESR commodity codes to fetch.
        as_of_date:      Snapshot date in YYYYMMDD format (typically today).
        bucket:          S3 bucket name.
        region:          AWS region.
        api_key:         FAS API key.
        skip_existing:   Skip if the S3 key already exists.
        dry_run:         Print keys without fetching.
    """
    reference = datetime.date(
        int(as_of_date[:4]), int(as_of_date[4:6]), int(as_of_date[6:8])
    )

    # Build (code, market_year) pairs — current + new-crop for each code.
    pairs: list[tuple[int, int]] = []
    for code in commodity_codes:
        current_year = _current_marketing_year(code, reference)
        pairs.append((code, current_year))
        pairs.append((code, current_year + 1))  # new-crop forward sales

    if dry_run:
        for code, year in pairs:
            print(f"[dry-run] s3://{bucket}/{raw_esr_weekly_key(code, year, as_of_date)}")
        return

    session = requests.Session()

    uploaded = skipped = failed = 0

    for i, (code, year) in enumerate(pairs):
        s3_key = raw_esr_weekly_key(code, year, as_of_date)

        if skip_existing and s3_object_exists(bucket, s3_key, region):
            logger.info("  [skip] already in S3: %s", s3_key)
            skipped += 1
            continue

        try:
            data = _fetch_one(session, code, year, api_key)
            if data is None:
                skipped += 1
            else:
                url = _build_url(code, year)
                upload_bytes_to_s3(data, bucket, s3_key, region)
                write_raw_s3_metadata(
                    bucket, s3_key, data, url, "application/json", region
                )
                logger.info("  → s3://%s/%s", bucket, s3_key)
                uploaded += 1
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "  FAILED commodity_code=%d market_year=%d — %s", code, year, exc
            )
            failed += 1

        if i < len(pairs) - 1:
            time.sleep(_BACKFILL_SLEEP)

    logger.info(
        "Weekly snapshot complete. uploaded=%d  skipped=%d  failed=%d",
        uploaded, skipped, failed,
    )
    if failed:
        raise SystemExit(f"{failed} request(s) failed — see log above.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    today = datetime.date.today()
    default_as_of = today.strftime("%Y%m%d")
    default_end_year = today.year  # current calendar year covers open marketing years

    parser = argparse.ArgumentParser(
        description=(
            "Download USDA FAS ESR JSON data to raw S3. "
            "Requires FAS_API_KEY environment variable (free from api.data.gov)."
        )
    )
    parser.add_argument(
        "--mode",
        choices=["backfill", "weekly"],
        required=True,
        help=(
            "backfill: download historical annual JSON for all target "
            "commodity codes and marketing years. "
            "weekly: snapshot current and new-crop year for all codes."
        ),
    )
    parser.add_argument(
        "--commodity-codes",
        nargs="+",
        type=int,
        default=_TARGET_COMMODITY_CODES,
        metavar="CODE",
        help=(
            f"ESR commodity codes to fetch (default: {_TARGET_COMMODITY_CODES}). "
            "Example: --commodity-codes 401 801"
        ),
    )
    parser.add_argument(
        "--start-year",
        type=int,
        default=1990,
        metavar="YYYY",
        help="First marketing year to fetch in backfill mode (default: 1990).",
    )
    parser.add_argument(
        "--end-year",
        type=int,
        default=default_end_year,
        metavar="YYYY",
        help=f"Last marketing year to fetch in backfill mode (default: {default_end_year}).",
    )
    parser.add_argument(
        "--as-of",
        default=default_as_of,
        metavar="YYYYMMDD",
        help=(
            f"Snapshot date for weekly mode (default: today = {default_as_of}). "
            "Used as the as_of partition key."
        ),
    )
    parser.add_argument(
        "--skip-existing-s3",
        action="store_true",
        help="Skip download if the S3 key already exists (safe for re-runs).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print S3 keys without making any API calls.",
    )
    args = parser.parse_args()

    if not args.dry_run:
        load_env()
    bucket = get_required_env("LEVIATHAN_BUCKET") if not args.dry_run else "BUCKET"
    region = get_required_env("AWS_REGION") if not args.dry_run else "us-east-1"
    api_key = get_required_env(_API_KEY_ENV) if not args.dry_run else "DRY_RUN_KEY"

    if args.mode == "backfill":
        run_backfill(
            commodity_codes=args.commodity_codes,
            start_year=args.start_year,
            end_year=args.end_year,
            bucket=bucket,
            region=region,
            api_key=api_key,
            skip_existing=args.skip_existing_s3,
            dry_run=args.dry_run,
        )
    else:
        run_weekly(
            commodity_codes=args.commodity_codes,
            as_of_date=args.as_of,
            bucket=bucket,
            region=region,
            api_key=api_key,
            skip_existing=args.skip_existing_s3,
            dry_run=args.dry_run,
        )


if __name__ == "__main__":
    main()
