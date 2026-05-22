"""World Bank Pink Sheet monthly ingest DAG.

Downloads the current monthly release of the World Bank Commodity Markets
("Pink Sheet") XLSX and uploads it to raw S3.

Schedule
--------
Runs at 14:00 UTC on the first Tuesday of each month (cron: ``0 14 1-7 * 2``).
The World Bank typically publishes around the first Tuesday of the month,
so this schedule runs ~2 business days after the usual release window,
giving the WB time to post before the DAG fires.

Pipeline
--------
discover_and_download  →  log_completion

Design notes
------------
- No Batch: the XLSX is ~2–3 MB.  Inline execution is appropriate.
- Pure boto3 S3 upload (no Airflow Amazon provider dependency).
- ``--skip-existing-s3`` semantics are replicated via a pre-upload existence
  check so the DAG is safe to trigger manually mid-month without double-storing.
- URL discovery scrapes the WB commodity-markets entry page each run because
  the document ID in the download URL is opaque and changes every month.
- The full history back to January 1960 is included in every release.
  Storing one file per release month captures retroactive WB revisions.

Historical backfill
-------------------
The initial backfill (any prior months not yet in S3) is handled by running
the CLI script manually:
    python jobs/ingest/fetch_world_bank_pink_sheet.py
Only the current month's release is available on the entry page, so earlier
releases require locating the archived URL manually (Wayback Machine or WB
archives page) and passing ``--release-month`` with the ingest script.
"""
from __future__ import annotations

import datetime
import io
import os
import re
import zipfile

import boto3
import requests
from airflow.decorators import dag, task
from airflow.utils.dates import days_ago
from bs4 import BeautifulSoup

from leviathan.common.logging import get_logger
from leviathan.storage.paths import raw_pink_sheet_key
from leviathan.storage.raw_metadata import check_min_file_size, write_raw_s3_metadata

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

AWS_REGION    = os.environ.get("AWS_REGION", "us-east-1")
LEVIATHAN_ENV = os.environ.get("LEVIATHAN_ENV", "dev")
PROJECT       = os.environ.get("LEVIATHAN_PROJECT", "leviathan")
BUCKET        = os.environ.get("LEVIATHAN_BUCKET", f"{PROJECT}-{LEVIATHAN_ENV}-shahem-001")

_ENTRY_URL = "https://www.worldbank.org/en/research/commodity-markets"
_XLS_RE = re.compile(r"CMO-Historical-Data-Monthly\.xlsx", re.IGNORECASE)
_XLS_FALLBACK_RE = re.compile(r"thedocs\.worldbank\.org.*\.xlsx", re.IGNORECASE)
_PDF_DATE_RE = re.compile(r"CMO-Pink-Sheet-([A-Za-z]+)-(\d{4})\.pdf", re.IGNORECASE)
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_PAGE_TIMEOUT    = 30
_DOWNLOAD_TIMEOUT = 120

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# DAG definition
# ---------------------------------------------------------------------------

@dag(
    dag_id="pink_sheet_monthly_ingest",
    description=(
        "Monthly download of the World Bank Commodity Markets Pink Sheet XLSX. "
        "Stores one versioned raw snapshot per release month for point-in-time "
        "reconstruction of fertilizer and energy input cost series."
    ),
    schedule="0 14 1-7 * 2",  # First Tuesday of each month at 14:00 UTC
    start_date=days_ago(1),
    catchup=False,
    tags=["leviathan", "world_bank", "pink_sheet"],
)
def pink_sheet_monthly_ingest_dag() -> None:

    @task()
    def discover_and_download() -> str:
        """Scrape WB page, download XLSX, validate, upload to S3.

        Returns the S3 key of the uploaded object.
        """
        session = requests.Session()
        session.headers.update({"User-Agent": _UA})

        # ----------------------------------------------------------------
        # Step 1: Discover the current XLS download URL
        # ----------------------------------------------------------------
        logger.info("Fetching WB commodity-markets entry page: %s", _ENTRY_URL)
        resp = session.get(_ENTRY_URL, timeout=_PAGE_TIMEOUT)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")
        all_hrefs = [tag["href"] for tag in soup.find_all("a", href=True)]
        xls_url = None
        filename = "CMO-Historical-Data-Monthly.xlsx"

        for href in all_hrefs:
            if _XLS_RE.search(href):
                xls_url = href if href.startswith("http") else f"https://www.worldbank.org{href}"
                break

        if xls_url is None:
            for href in all_hrefs:
                if _XLS_FALLBACK_RE.search(href):
                    xls_url = href
                    filename = href.rstrip("/").split("/")[-1].split("?")[0]
                    break

        if xls_url is None:
            raise RuntimeError(
                f"Could not locate Pink Sheet XLSX href on {_ENTRY_URL}. "
                "The WB page structure may have changed. Check manually and update the DAG."
            )

        logger.info("Discovered Pink Sheet URL: %s", xls_url)

        # ----------------------------------------------------------------
        # Step 2: Extract release month from the accompanying PDF href
        # ----------------------------------------------------------------
        page_html = resp.text
        m2 = _PDF_DATE_RE.search(page_html)
        if m2:
            month_name, year_str = m2.group(1), m2.group(2)
            month_num = datetime.datetime.strptime(month_name, "%B").month
            release_ym = f"{year_str}M{month_num:02d}"
        else:
            today = datetime.date.today()
            release_ym = f"{today.year}M{today.month:02d}"
            logger.warning(
                "Could not extract release month from PDF href; defaulting to %s",
                release_ym,
            )
        logger.info("Release: %s", release_ym)

        # ----------------------------------------------------------------
        # Step 3: Build S3 key + skip if already present
        # ----------------------------------------------------------------
        s3_key = raw_pink_sheet_key(release_ym, filename)
        s3_client = boto3.client("s3", region_name=AWS_REGION)

        try:
            s3_client.head_object(Bucket=BUCKET, Key=s3_key)
            logger.info("Already in S3, skipping: s3://%s/%s", BUCKET, s3_key)
            return s3_key
        except s3_client.exceptions.ClientError as exc:
            if exc.response["Error"]["Code"] != "404":
                raise

        # ----------------------------------------------------------------
        # Step 4: Download
        # ----------------------------------------------------------------
        logger.info("Downloading Pink Sheet XLSX from %s …", xls_url)
        dl = session.get(xls_url, timeout=_DOWNLOAD_TIMEOUT, stream=False)
        dl.raise_for_status()
        data = dl.content
        logger.info("Downloaded %.2f MB", len(data) / 1_048_576)

        # ----------------------------------------------------------------
        # Step 5: Validate (magic bytes + structural integrity + min size)
        # ----------------------------------------------------------------
        if len(data) < 4 or data[:2] != b"PK":
            raise RuntimeError(
                f"Validation failed: response from {xls_url} does not have XLSX/ZIP "
                f"magic bytes. Got: {data[:8]!r}. Possible HTML error page."
            )
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                names = zf.namelist()
        except zipfile.BadZipFile as exc:
            raise RuntimeError(
                f"Validation failed: not a valid ZIP/XLSX from {xls_url}: {exc}"
            ) from exc

        if not any(n.startswith("xl/") for n in names):
            raise RuntimeError(
                f"Validation failed: ZIP from {xls_url} has no xl/ entries. "
                f"Partial contents: {names[:10]}"
            )

        check_min_file_size(data, "world_bank_pink_sheet", context=xls_url)
        logger.info("Validation passed — %d bytes, well-formed XLSX", len(data))

        # ----------------------------------------------------------------
        # Step 6: Upload to S3
        # ----------------------------------------------------------------
        s3_client.put_object(
            Bucket=BUCKET,
            Key=s3_key,
            Body=data,
            ContentType=(
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ),
        )
        logger.info("Uploaded → s3://%s/%s", BUCKET, s3_key)

        # ----------------------------------------------------------------
        # Step 7: Write companion metadata
        # ----------------------------------------------------------------
        write_raw_s3_metadata(
            BUCKET,
            s3_key,
            data,
            xls_url,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            AWS_REGION,
        )
        logger.info("Metadata written → raw_meta/%s_meta.json", s3_key)

        return s3_key

    @task()
    def log_completion(s3_key: str) -> None:
        """Log the completed snapshot key for observability."""
        logger.info("Pink Sheet monthly snapshot complete: s3://%s/%s", BUCKET, s3_key)

    s3_key = discover_and_download()
    log_completion(s3_key)


pink_sheet_monthly_ingest_dag()
