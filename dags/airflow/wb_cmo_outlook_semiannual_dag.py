"""Airflow DAG: World Bank CMO Outlook semi-annual PDF ingest.

Fires on the first Tuesday of April and October at 14:00 UTC — shortly after
the World Bank typically publishes the new semi-annual issue.

This DAG does NOT use the manifest file at runtime.  It independently scrapes
the archive page, detects the latest issue (highest release_date not yet in
S3), downloads it, and uploads to raw S3.  This keeps the DAG self-contained
and idempotent — re-running after a partial failure is safe.

For the historical backfill (~85 reports, 1994–present), run the standalone
ingest script:
    python jobs/ingest/fetch_wb_cmo_outlook.py --discover
    python jobs/ingest/fetch_wb_cmo_outlook.py --backfill --skip-existing-s3
"""
from __future__ import annotations

import datetime
import re

import boto3
import requests
from airflow.decorators import dag, task
from bs4 import BeautifulSoup

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.paths import raw_cmo_outlook_key
from leviathan.storage.raw_metadata import check_min_file_size, write_raw_s3_metadata
from leviathan.storage.s3 import upload_bytes_to_s3

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ARCHIVE_URL = (
    "https://www.worldbank.org/en/research/commodity-markets/report-archive"
)
_OPENKNOWLEDGE_BASE = "https://openknowledge.worldbank.org"

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_PDF_MAGIC = b"%PDF"
_REQUEST_TIMEOUT_S = 60

# Semi-annual issues always land in April (H1) or October (H2)
_SEMI_ANNUAL_MONTHS = {4, 10}

# Pattern for bitstream download links
_BITSTREAM_RE = re.compile(
    r"openknowledge\.worldbank\.org/bitstreams/[^\"'\s]+/download",
    re.IGNORECASE,
)

_NUM_TO_MONTH_NAME: dict[int, str] = {
    1: "January", 2: "February", 3: "March", 4: "April",
    5: "May", 6: "June", 7: "July", 8: "August",
    9: "September", 10: "October", 11: "November", 12: "December",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_latest_semi_annual(html: str) -> tuple[str, str, str] | None:
    """Scan the archive page for the most recent semi-annual PDF href.

    Returns (release_ym, filename, url) or None if not found.
    The most recent entry is always at the top of the table.
    """
    soup = BeautifulSoup(html, "html.parser")

    year_re = re.compile(r"\b(20[0-9]{2})\b")
    month_map = {
        "april": 4, "apr": 4,
        "october": 10, "oct": 10,
    }

    for table in soup.find_all("table"):
        for row in table.find_all("tr")[1:]:  # skip header
            cells = row.find_all(["td", "th"])
            if len(cells) < 2:
                continue

            issue_text = cells[0].get_text(separator=" ", strip=True).lower()
            year_m = year_re.search(issue_text)
            if not year_m:
                continue
            year = int(year_m.group(1))

            # Only care about April / October issues (semi-annual era)
            month = None
            for label, m in month_map.items():
                if label in issue_text:
                    month = m
                    break
            if month is None:
                continue

            # Find the PDF link
            report_cell = cells[1]
            for a in report_cell.find_all("a", href=True):
                href = a["href"]
                link_text = a.get_text(strip=True).lower()
                if link_text == "pdf" or "bitstreams" in href:
                    url = (
                        href
                        if href.startswith("http")
                        else f"{_OPENKNOWLEDGE_BASE}{href}"
                    )
                    release_ym = f"{year}-{month:02d}"
                    month_name = _NUM_TO_MONTH_NAME[month]
                    filename = f"CMO-Outlook-{year}-{month_name}.pdf"
                    return release_ym, filename, url

    return None


def _resolve_landing_page(url: str, session: requests.Session) -> str | None:
    """If url is an openknowledge landing page, follow it to the bitstream."""
    if "bitstreams" in url and "/download" in url:
        return url  # already a direct download
    try:
        resp = session.get(url, timeout=_REQUEST_TIMEOUT_S)
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Landing page fetch failed for %s: %s", url, exc)
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    for a in soup.find_all("a", href=True):
        candidate = a["href"]
        if "bitstreams" in candidate and "/download" in candidate:
            return (
                candidate
                if candidate.startswith("http")
                else f"{_OPENKNOWLEDGE_BASE}{candidate}"
            )
    m = _BITSTREAM_RE.search(resp.text)
    if m:
        return "https://" + m.group(0)
    return None


# ---------------------------------------------------------------------------
# DAG
# ---------------------------------------------------------------------------

@dag(
    dag_id="wb_cmo_outlook_semiannual_ingest",
    schedule="0 14 1-7 4,10 2",   # first Tuesday of April and October at 14:00 UTC
    start_date=datetime.datetime(2026, 4, 1),
    catchup=False,
    tags=["world-bank", "cmo-outlook", "raw-ingest", "semi-annual"],
    doc_md=__doc__,
)
def wb_cmo_outlook_semiannual_ingest_dag():

    @task
    def discover_and_download() -> dict:
        """Scrape archive page, detect new semi-annual issue, upload to S3."""
        load_env()
        bucket = get_required_env("LEVIATHAN_RAW_BUCKET")
        region = get_required_env("AWS_DEFAULT_REGION")

        session = requests.Session()
        session.headers.update({"User-Agent": _UA})

        # ----------------------------------------------------------------
        # Step 1: Scrape archive page to find latest semi-annual release
        # ----------------------------------------------------------------
        logger.info("Fetching archive page: %s", _ARCHIVE_URL)
        resp = session.get(_ARCHIVE_URL, timeout=_REQUEST_TIMEOUT_S)
        resp.raise_for_status()

        result = _find_latest_semi_annual(resp.text)
        if result is None:
            raise RuntimeError(
                f"Could not locate a semi-annual PDF href on {_ARCHIVE_URL}. "
                "The WB page structure may have changed. Check the archive page "
                "manually and update _find_latest_semi_annual() in this DAG."
            )

        release_ym, filename, raw_url = result
        logger.info("Latest semi-annual issue: %s  %s", release_ym, filename)

        # ----------------------------------------------------------------
        # Step 2: Resolve to a direct bitstream download URL if needed
        # ----------------------------------------------------------------
        download_url = _resolve_landing_page(raw_url, session)
        if download_url is None:
            raise RuntimeError(
                f"Could not resolve PDF download URL from {raw_url}. "
                "The openknowledge.worldbank.org page structure may have changed."
            )
        logger.info("Resolved download URL: %s", download_url)

        # ----------------------------------------------------------------
        # Step 3: Skip if already in S3
        # ----------------------------------------------------------------
        s3_key = raw_cmo_outlook_key(release_ym, filename)
        s3_client = boto3.client("s3", region_name=region)
        try:
            s3_client.head_object(Bucket=bucket, Key=s3_key)
            logger.info("Already in S3 — skipping: %s", s3_key)
            return {"status": "skipped", "s3_key": s3_key, "release_ym": release_ym}
        except s3_client.exceptions.ClientError as exc:
            if exc.response["Error"]["Code"] != "404":
                raise

        # ----------------------------------------------------------------
        # Step 4: Download
        # ----------------------------------------------------------------
        logger.info("Downloading %s …", download_url)
        dl_resp = session.get(download_url, timeout=_REQUEST_TIMEOUT_S, allow_redirects=True)
        dl_resp.raise_for_status()
        data = dl_resp.content

        if data[:4] != _PDF_MAGIC:
            raise RuntimeError(
                f"Response from {download_url} is not a valid PDF "
                f"(got {data[:4]!r}). Possible error page."
            )
        check_min_file_size(data, "wb_cmo_outlook", context=download_url)
        logger.info("Downloaded %.1f KB, validation passed", len(data) / 1024)

        # ----------------------------------------------------------------
        # Step 5: Upload to S3
        # ----------------------------------------------------------------
        upload_bytes_to_s3(data, bucket, s3_key, region)
        write_raw_s3_metadata(
            bucket, s3_key, data, download_url, "application/pdf", region
        )
        logger.info("Uploaded → s3://%s/%s", bucket, s3_key)

        return {
            "status": "uploaded",
            "s3_key": s3_key,
            "release_ym": release_ym,
            "filename": filename,
            "size_bytes": len(data),
        }

    @task
    def log_completion(result: dict) -> None:
        status = result.get("status")
        release_ym = result.get("release_ym")
        s3_key = result.get("s3_key")
        if status == "uploaded":
            size_kb = result.get("size_bytes", 0) / 1024
            logger.info(
                "CMO Outlook ingest complete: release=%s  size=%.1f KB  key=%s",
                release_ym,
                size_kb,
                s3_key,
            )
        else:
            logger.info(
                "CMO Outlook ingest: release=%s already in S3 — nothing to do.",
                release_ym,
            )

    result = discover_and_download()
    log_completion(result)


wb_cmo_outlook_semiannual_ingest_dag()
