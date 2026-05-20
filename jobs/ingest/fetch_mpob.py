"""Fetch MPOB BEPI palm oil reports (HTML tables and PDFs) to raw S3.

Three report series are downloaded:

  annual_summary   — "Summary Of The Malaysian Palm Oil Industry {year}"
                     One HTML page per calendar year; national CPO production,
                     closing stocks, exports, imports, FFB price (all months).
                     bepi.mpob.gov.my/stat/web_report1.php?val={YYYY}84

  monthly_release  — "{Month} {year}"
                     One HTML page per calendar month; same variables plus
                     regional breakdown (Peninsular Malaysia / Sabah / Sarawak).
                     bepi.mpob.gov.my/stat/web_report1.php?val={YYYY}75&val1={MM}

  overview_pdf     — "Overview of Industry {year}"
                     Annual PDF report covering production, trade, prices and
                     area statistics.  Primary source for pre-2017 data.
                     bepi.mpob.gov.my/images/overview/Overview_of_Industry_{year}.pdf

Discovery strategy
------------------
All report URLs are stored in a static manifest produced by the probe script:
  configs/sources/mpob_archive.yaml

MPOB BEPI (bepi.mpob.gov.my) is a Joomla CMS site with no WAF; standard
``requests`` with a Chrome User-Agent works without fingerprint bypass.

S3 key structure
----------------
  annual_summary:
    raw/production/source=mpob/release_type=annual_summary/
        year={YYYY}/mpob_annual_summary_{YYYY}.html

  monthly_release:
    raw/production/source=mpob/release_type=monthly_release/
        year={YYYY}/month={MM}/mpob_monthly_{YYYY}_{MM}.html

Idempotency
-----------
Pass ``--skip-existing-s3`` to skip pages already uploaded.  Re-running with
this flag is safe and fast.  Use ``--limit 1`` for a quick smoke-test.
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import requests
import yaml

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.paths import (
    raw_mpob_annual_key,
    raw_mpob_monthly_key,
    raw_mpob_overview_pdf_key,
)
from leviathan.storage.raw_metadata import check_min_file_size, write_raw_s3_metadata
from leviathan.storage.s3 import s3_object_exists, upload_bytes_to_s3

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Validation marker — every MPOB BEPI palm oil table page contains this string
_TABLE_MARKER = "CRUDE PALM OIL"

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

_MANIFEST_PATH = (
    Path(__file__).parent.parent.parent / "configs" / "sources" / "mpob_archive.yaml"
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
    parser = argparse.ArgumentParser(
        description=(
            "Download MPOB BEPI palm oil HTML table pages to raw S3. "
            "Reads URLs from configs/sources/mpob_archive.yaml."
        )
    )
    parser.add_argument(
        "--skip-existing-s3",
        action="store_true",
        help="Skip pages whose S3 key already exists (safe for re-runs).",
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
        help="Process at most N entries — use 1 for a smoke test.",
    )
    parser.add_argument(
        "--year",
        type=int,
        default=None,
        metavar="YYYY",
        help="Process only entries for this calendar year.",
    )
    parser.add_argument(
        "--release-type",
        choices=["annual_summary", "monthly_release", "overview_pdf"],
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
        releases = [r for r in releases if r["year"] == args.year]
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
            year = entry["year"]
            month = entry.get("month")
            if rt == "annual_summary":
                s3_key = raw_mpob_annual_key(year)
            elif rt == "monthly_release":
                s3_key = raw_mpob_monthly_key(year, month)
            else:
                s3_key = raw_mpob_overview_pdf_key(year)
            print(f"  {rt:<20}  {year}/{month or '--':>2}  →  {s3_key}")
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
        year = entry["year"]
        month = entry.get("month")
        url = entry["stat_url"]

        if rt == "annual_summary":
            s3_key = raw_mpob_annual_key(year)
            label = f"annual_summary/{year}"
        elif rt == "monthly_release":
            s3_key = raw_mpob_monthly_key(year, month)
            label = f"monthly_release/{year}/{month:02d}"
        else:
            s3_key = raw_mpob_overview_pdf_key(year)
            label = f"overview_pdf/{year}"

        try:
            if args.skip_existing_s3 and s3_object_exists(bucket, s3_key, region):
                logger.info("Skipping — already in S3: %s", s3_key)
                skipped += 1
                continue

            logger.info("Downloading %s  %s …", label, url)

            if rt == "overview_pdf":
                resp = session.get(url, timeout=60, allow_redirects=True)
                resp.raise_for_status()
                payload = resp.content
                if not payload.startswith(b"%PDF"):
                    raise RuntimeError(
                        f"Validation failed: response is not a PDF (magic bytes missing) from {url}"
                    )
                check_min_file_size(payload, "mpob_overview_pdf", context=url)
                content_type = "application/pdf"
            else:
                html_text = _download_html(url, session)
                if _TABLE_MARKER not in html_text.upper():
                    raise RuntimeError(
                        f"Validation failed: '{_TABLE_MARKER}' not found in response from {url}"
                    )
                payload = html_text.encode("utf-8")
                check_min_file_size(payload, "mpob", context=url)
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
