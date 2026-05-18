"""Fetch USDA FAS Coffee: World Markets and Trade (WMT) circular PDFs to raw S3.

Discovery strategy
------------------
The FAS browse page at fas.usda.gov/data/search (filtered to commodity=Coffee,
report_type=World Production, Markets, and Trade Report) is paginated HTML.
This job paginates through those pages to collect each report's detail-page URL,
then visits each detail page to extract the direct PDF download link and publication
date.  Both steps use Python's stdlib ``html.parser`` — no external HTML library
required.

Download strategy
-----------------
Sequential with a polite inter-request sleep (default 1 s).  The remote server
(apps.fas.usda.gov / www.fas.usda.gov) is a USDA government server, not a CDN.
With only ~47 historical PDFs and 2 new ones per year there is no justification
for parallelism — threading would only risk rate-limiting without any throughput
benefit.

Idempotency
-----------
Pass ``--skip-existing-s3`` to skip reports already uploaded.  Re-running the
full historical backfill with this flag is safe and fast.
"""
from __future__ import annotations

import argparse
import re
import time
from datetime import datetime

import requests

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.paths import raw_wmt_key
from leviathan.storage.raw_metadata import check_min_file_size, write_raw_s3_metadata
from leviathan.storage.s3 import s3_object_exists, upload_bytes_to_s3

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PDF_MAGIC = b"%PDF"

# FAS search URL: Coffee commodity (609) + WMT report type (10259), one page at a time.
_BROWSE_URL = (
    "https://www.fas.usda.gov/data/search"
    "?reports%5B0%5D=report_commodities%3A609"
    "&reports%5B1%5D=report_type%3A10259"
    "&page={page}"
)

# Matches WMT report detail-page URLs embedded in browse-page HTML.
_DETAIL_HREF_RE = re.compile(
    r'href="(https://www\.fas\.usda\.gov/data/coffee-world-markets-and-trade-[^"]+)"'
)

# Matches any .pdf href that lives on a fas.usda.gov or apps.fas.usda.gov host.
_PDF_HREF_RE = re.compile(r'href="([^"]*(?:fas|apps\.fas)\.usda\.gov[^"]*\.pdf)"')

# Publication date text on a report detail page, e.g. "December 18, 2025  |"
_PUB_DATE_RE = re.compile(r"(\w+ \d+, \d{4})\s*\|")

_HEADERS = {
    "User-Agent": "Leviathan-Data-Pipeline/1.0 (research data ingestion)",
    "Accept": "text/html,application/xhtml+xml,application/pdf,*/*",
}


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _get(url: str, session: requests.Session, timeout: int = 30) -> requests.Response:
    resp = session.get(url, headers=_HEADERS, timeout=timeout, allow_redirects=True)
    resp.raise_for_status()
    return resp


# ---------------------------------------------------------------------------
# Discovery helpers
# ---------------------------------------------------------------------------

def _discover_report_pages(session: requests.Session, sleep_seconds: float) -> list[str]:
    """Paginate through FAS browse pages and return all WMT detail-page URLs."""
    seen: set[str] = set()
    page = 0

    while True:
        url = _BROWSE_URL.format(page=page)
        logger.info("Fetching browse page %d …", page)
        html = _get(url, session).text

        found = _DETAIL_HREF_RE.findall(html)
        new_urls = [u for u in found if u not in seen]

        if not new_urls:
            # No new results on this page — we have reached the end.
            break

        seen.update(new_urls)
        page += 1
        time.sleep(sleep_seconds)

    urls = sorted(seen)
    logger.info("Discovered %d WMT report pages.", len(urls))
    return urls


def _parse_detail_page(html: str, detail_url: str) -> tuple[str, str]:
    """Return ``(publication_date_yyyymmdd, pdf_url)`` from a report detail page.

    Raises:
        RuntimeError: If the publication date or PDF link cannot be found.
    """
    # --- Publication date ---
    date_match = _PUB_DATE_RE.search(html)
    if not date_match:
        raise RuntimeError(
            f"Could not find publication date on detail page: {detail_url}"
        )
    try:
        pub_dt = datetime.strptime(date_match.group(1), "%B %d, %Y")
    except ValueError as exc:
        raise RuntimeError(
            f"Unparseable date '{date_match.group(1)}' on {detail_url}"
        ) from exc

    pub_date_str = pub_dt.strftime("%Y%m%d")

    # --- PDF URL ---
    pdf_matches = _PDF_HREF_RE.findall(html)
    if not pdf_matches:
        raise RuntimeError(f"Could not find a FAS PDF link on detail page: {detail_url}")

    return pub_date_str, pdf_matches[0]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Download USDA FAS Coffee WMT circular PDFs to raw S3. "
            "Runs sequentially with a polite delay — do not add threading."
        )
    )
    parser.add_argument(
        "--skip-existing-s3",
        action="store_true",
        help="Skip reports whose S3 key already exists (safe for re-runs).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Discover and print all report URLs without downloading anything.",
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
        help="Process at most N reports — use 1 for a smoke test.",
    )
    args = parser.parse_args()

    load_env()
    bucket = get_required_env("LEVIATHAN_BUCKET")
    region = get_required_env("AWS_REGION")

    session = requests.Session()

    # -----------------------------------------------------------------------
    # Phase A — Discovery
    # -----------------------------------------------------------------------
    logger.info("Phase A: discovering WMT report detail pages …")
    detail_urls = _discover_report_pages(session, args.sleep_seconds)

    if args.dry_run:
        print(f"Discovered {len(detail_urls)} WMT report pages:")
        for url in detail_urls:
            print(f"  {url}")
        return

    # -----------------------------------------------------------------------
    # Phase B — Download and upload
    # -----------------------------------------------------------------------
    if args.limit:
        detail_urls = detail_urls[: args.limit]

    uploaded = skipped = errors = 0

    for detail_url in detail_urls:
        try:
            time.sleep(args.sleep_seconds)
            html = _get(detail_url, session).text
            pub_date_str, pdf_url = _parse_detail_page(html, detail_url)
            s3_key = raw_wmt_key(pub_date_str)

            if args.skip_existing_s3 and s3_object_exists(bucket, s3_key, region):
                logger.info("Skipping — already in S3: %s", s3_key)
                skipped += 1
                continue

            time.sleep(args.sleep_seconds)
            logger.info("Downloading %s  (%s) …", pub_date_str, pdf_url)
            pdf_bytes = _get(pdf_url, session, timeout=60).content

            # --- Validate ---
            if not pdf_bytes.startswith(_PDF_MAGIC):
                raise RuntimeError(
                    f"Response is not a valid PDF (missing %%PDF header): {pdf_url}"
                )
            check_min_file_size(pdf_bytes, "usda_fas_coffee_wmt", context=pdf_url)

            # --- Upload ---
            upload_bytes_to_s3(pdf_bytes, bucket, s3_key, region)
            write_raw_s3_metadata(
                bucket, s3_key, pdf_bytes, pdf_url, "application/pdf", region
            )

            logger.info(
                "Uploaded %s (%.1f MB) → s3://%s/%s",
                pub_date_str,
                len(pdf_bytes) / 1_048_576,
                bucket,
                s3_key,
            )
            uploaded += 1

        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to process %s: %s", detail_url, exc)
            errors += 1

    logger.info(
        "Done. uploaded=%d  skipped=%d  errors=%d", uploaded, skipped, errors
    )

    if errors:
        raise SystemExit(f"{errors} report(s) failed — see logs above.")


if __name__ == "__main__":
    main()
