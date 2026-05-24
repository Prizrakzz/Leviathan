"""Fetch MPOC market intelligence pages (HTML) to raw S3.

Four report series are downloaded:

  trade_statistics   — "Monthly Palm Oil Trade Statistics {year}"
                       One HTML page per calendar year; Malaysian palm oil
                       exports/imports, top destination countries, production,
                       closing stocks, and monthly CPO prices.
                       Available years: 2009–2023 (15 pages).
                       mpoc.org.my/monthly-palm-oil-trade-statistics-{YYYY}/

  stock_comparison   — "Stock Comparison"
                       Single live page with oils & fats ending stock data
                       (Palm, Soy, Sunflower, Rapeseed) for China, India,
                       Pakistan, Bangladesh, and USA, plus analyst narrative
                       paragraphs per country.
                       mpoc.org.my/market-insight/stock-comparison/

  competitive_prices — "Daily Palm Oil Prices"
                       Single live page with a monthly CPO BMD+3 vs SBO ARG
                       FOB vs SFO Black Sea FOB price comparison and spread
                       table showing price premiums of substitute oils over CPO.
                       mpoc.org.my/market-insight/daily-palm-oil-prices/

  market_highlights  — Individual market analysis articles.
                       Each slug maps to one HTML page spidered from:
                       mpoc.org.my/market-insight/market-highlights/

Discovery strategy
------------------
All report URLs are stored in a static manifest produced by the probe scripts:
  configs/sources/mpoc_archive.yaml

MPOC (mpoc.org.my) is a WordPress site with no WAF; standard ``requests``
with a Chrome User-Agent works without fingerprint bypass.

S3 key structure
----------------
  trade_statistics:
    raw/production/source=mpoc/release_type=trade_statistics/
        year={YYYY}/mpoc_trade_stats_{YYYY}.html

  stock_comparison:
    raw/production/source=mpoc/release_type=stock_comparison/
        mpoc_stock_comparison.html

  competitive_prices:
    raw/production/source=mpoc/release_type=competitive_prices/
        mpoc_competitive_prices.html

  market_highlights:
    raw/production/source=mpoc/release_type=market_highlights/
        slug={slug}/mpoc_article_{slug}.html

Idempotency
-----------
Pass ``--skip-existing-s3`` to skip pages already uploaded.  Re-running with
this flag is safe and fast.  Use ``--limit 1`` for a quick smoke-test.

Note: stock_comparison and competitive_prices are live snapshots — do NOT pass
``--skip-existing-s3`` when refreshing those pages with current data.
"""
from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

import requests
import yaml

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.paths import (
    raw_mpoc_article_key,
    raw_mpoc_competitive_prices_key,
    raw_mpoc_stock_comparison_key,
    raw_mpoc_trade_stats_key,
)
from leviathan.storage.raw_metadata import check_min_file_size, write_raw_s3_metadata
from leviathan.storage.s3 import s3_object_exists, upload_bytes_to_s3

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Validation markers per release type
_MARKER_TRADE_STATS = "EXPORTS TO MAJOR COUNTRIES"
_MARKER_STOCK_COMPARISON = "OILS AND FATS ENDING STOCKS"
_MARKER_COMPETITIVE_PRICES_A = "CPO"
_MARKER_COMPETITIVE_PRICES_B = "SBO"

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

_MANIFEST_PATH = (
    Path(__file__).parent.parent.parent / "configs" / "sources" / "mpoc_archive.yaml"
)


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------

def _download_html(url: str, session: requests.Session, timeout: int = 30) -> str:
    resp = session.get(url, timeout=timeout, allow_redirects=True)
    resp.raise_for_status()
    return resp.text


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    parser = argparse.ArgumentParser(
        description=(
            "Download MPOC market intelligence HTML pages to raw S3. "
            "Reads URLs from configs/sources/mpoc_archive.yaml."
        )
    )
    parser.add_argument(
        "--skip-existing-s3",
        action="store_true",
        help=(
            "Skip pages whose S3 key already exists. "
            "Do NOT use this flag for stock_comparison or competitive_prices "
            "when refreshing with current data."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print all S3 keys and source URLs without downloading anything.",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=1.0,
        help="Polite delay between HTTP requests in seconds (default: 1.0).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Process at most N entries — use 1 for a quick smoke test.",
    )
    parser.add_argument(
        "--year",
        type=int,
        default=None,
        metavar="YYYY",
        help="Process only trade_statistics entries for this calendar year.",
    )
    parser.add_argument(
        "--release-type",
        choices=[
            "trade_statistics",
            "stock_comparison",
            "competitive_prices",
            "market_highlights",
        ],
        default=None,
        help="Process only this release type (default: all).",
    )
    args = parser.parse_args()

    # -----------------------------------------------------------------------
    # Load manifest
    # -----------------------------------------------------------------------
    manifest_data = yaml.safe_load(_MANIFEST_PATH.read_text(encoding="utf-8"))
    releases: list[dict] = manifest_data["releases"]
    logger.info("Loaded %d entries from manifest %s", len(releases), _MANIFEST_PATH.name)

    # -----------------------------------------------------------------------
    # Apply filters
    # -----------------------------------------------------------------------
    if args.year is not None:
        releases = [r for r in releases if r.get("year") == args.year]
    if args.release_type is not None:
        releases = [r for r in releases if r["release_type"] == args.release_type]
    if args.limit:
        releases = releases[: args.limit]

    # -----------------------------------------------------------------------
    # Dry run
    # -----------------------------------------------------------------------
    if args.dry_run:
        print(
            f"Manifest: {_MANIFEST_PATH.name}  "
            f"({len(releases)} entries after filters)"
        )
        for entry in releases:
            rt = entry["release_type"]
            url = entry["stat_url"]
            if rt == "trade_statistics":
                s3_key = raw_mpoc_trade_stats_key(entry["year"])
            elif rt == "stock_comparison":
                s3_key = raw_mpoc_stock_comparison_key()
            elif rt == "competitive_prices":
                s3_key = raw_mpoc_competitive_prices_key()
            else:
                s3_key = raw_mpoc_article_key(entry["slug"])
            print(f"  {rt:<22}  →  {s3_key}")
            print(f"    {url}")
        return

    # -----------------------------------------------------------------------
    # Download & upload
    # -----------------------------------------------------------------------
    load_env()
    bucket = get_required_env("LEVIATHAN_BUCKET")
    region = get_required_env("AWS_REGION")

    uploaded = skipped = errors = 0

    session = requests.Session()
    session.headers.update({"User-Agent": _UA})

    for entry in releases:
        rt = entry["release_type"]
        url = entry["stat_url"]

        # Build S3 key and human-readable label
        if rt == "trade_statistics":
            year = entry["year"]
            s3_key = raw_mpoc_trade_stats_key(year)
            label = f"trade_statistics/{year}"
        elif rt == "stock_comparison":
            s3_key = raw_mpoc_stock_comparison_key()
            label = "stock_comparison"
        elif rt == "competitive_prices":
            s3_key = raw_mpoc_competitive_prices_key()
            label = "competitive_prices"
        else:
            slug = entry["slug"]
            s3_key = raw_mpoc_article_key(slug)
            label = f"market_highlights/{slug}"

        try:
            if args.skip_existing_s3 and s3_object_exists(bucket, s3_key, region):
                logger.info("Skipping — already in S3: %s", s3_key)
                skipped += 1
                continue

            logger.info("Downloading %s  %s …", label, url)

            html_text = _download_html(url, session)
            html_upper = html_text.upper()

            # Validate content
            if rt == "trade_statistics":
                if _MARKER_TRADE_STATS not in html_upper:
                    raise RuntimeError(
                        f"Validation failed: '{_MARKER_TRADE_STATS}' not found in {url}"
                    )
                check_min_file_size(html_text.encode("utf-8"), "mpoc_trade_stats", context=url)

            elif rt == "stock_comparison":
                if _MARKER_STOCK_COMPARISON not in html_upper:
                    raise RuntimeError(
                        f"Validation failed: '{_MARKER_STOCK_COMPARISON}' not found in {url}"
                    )
                check_min_file_size(html_text.encode("utf-8"), "mpoc_stock_comparison", context=url)

            elif rt == "competitive_prices":
                if _MARKER_COMPETITIVE_PRICES_A not in html_upper or _MARKER_COMPETITIVE_PRICES_B not in html_upper:
                    raise RuntimeError(
                        f"Validation failed: 'CPO' or 'SBO' not found in {url}"
                    )
                check_min_file_size(html_text.encode("utf-8"), "mpoc_competitive_prices", context=url)

            else:  # market_highlights
                check_min_file_size(html_text.encode("utf-8"), "mpoc_article", context=url)

            payload = html_text.encode("utf-8")
            content_type = "text/html; charset=utf-8"

            upload_bytes_to_s3(payload, bucket, s3_key, region)
            write_raw_s3_metadata(
                bucket,
                s3_key,
                payload,
                url,
                content_type,
                region,
            )

            logger.info(
                "Uploaded %s  (%.1f KB) → s3://%s/%s",
                label,
                len(payload) / 1_024,
                bucket,
                s3_key,
            )
            uploaded += 1

        except Exception as exc:  # noqa: BLE001
            logger.error("Failed %s (%s): %s", label, url, exc)
            errors += 1

        time.sleep(args.sleep_seconds)

    session.close()

    logger.info(
        "Done. uploaded=%d  skipped=%d  errors=%d", uploaded, skipped, errors
    )

    if errors:
        raise SystemExit(f"{errors} report(s) failed — see logs above.")


if __name__ == "__main__":
    main()
