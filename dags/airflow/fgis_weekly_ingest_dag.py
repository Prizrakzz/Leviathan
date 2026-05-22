"""FGIS weekly ingest DAG — snapshot current-year USDA FGIS Export Inspections CSV.

Runs every Thursday at 12:00 UTC, after FGIS publishes Mon–Wed certifications.

Pipeline
--------
fetch_snapshot  →  log_completion

Design notes
------------
- No Batch involvement: one HTTP GET per run, ~1–20 MB.  Runs inline.
- Pure boto3 S3 upload (no Airflow Amazon provider dependency).
- skip_existing_s3: not used by default so each Thursday's snapshot is always
  stored as a new as_of partition (different S3 key each week).
- Prior-year backfill is handled by the CLI script
  ``jobs/ingest/fetch_usda_fgis_export_inspections.py --mode backfill``.
"""
from __future__ import annotations

import datetime
import os

import boto3
import requests
from airflow.decorators import dag, task
from airflow.utils.dates import days_ago

from leviathan.common.logging import get_logger
from leviathan.storage.paths import raw_fgis_weekly_key

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

AWS_REGION    = os.environ.get("AWS_REGION", "us-east-1")
LEVIATHAN_ENV = os.environ.get("LEVIATHAN_ENV", "dev")
PROJECT       = os.environ.get("LEVIATHAN_PROJECT", "leviathan")
BUCKET        = os.environ.get("LEVIATHAN_BUCKET", f"{PROJECT}-{LEVIATHAN_ENV}-shahem-001")

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_DOWNLOAD_TIMEOUT = 120  # seconds — current-year file can be ~20 MB
_MIN_SIZE_BYTES = 10_000

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# DAG definition
# ---------------------------------------------------------------------------

@dag(
    dag_id="fgis_weekly_ingest",
    description=(
        "Weekly snapshot of the current-year USDA FGIS Export Inspections CSV. "
        "Stores an immutable as_of-partitioned object in S3 to preserve "
        "point-in-time correctness for backtested ML features."
    ),
    schedule="0 12 * * 4",  # Every Thursday at noon UTC
    start_date=days_ago(1),
    catchup=False,
    tags=["leviathan", "fgis", "usda"],
)
def fgis_weekly_ingest_dag() -> None:

    @task()
    def fetch_snapshot() -> str:
        """Download the current-year FGIS CSV and upload to S3.

        Returns the S3 key of the uploaded object.
        """
        today = datetime.date.today()
        year = today.year
        as_of = today.strftime("%Y%m%d")
        url = f"https://fgisonline.ams.usda.gov/ExportGrainReport/CY{year}.csv"

        logger.info("Downloading FGIS %d CSV (as_of=%s) from %s …", year, as_of, url)
        resp = requests.get(
            url,
            timeout=_DOWNLOAD_TIMEOUT,
            headers={"User-Agent": _UA},
        )
        resp.raise_for_status()
        data = resp.content

        if len(data) < _MIN_SIZE_BYTES:
            raise RuntimeError(
                f"FGIS CY{year} download too small: {len(data)} bytes (expected ≥{_MIN_SIZE_BYTES}). "
                "Possible error page or outage."
            )

        # Sanity-check CSV header
        first_line = data[:512].decode("utf-8", errors="replace").splitlines()[0].lower()
        if "date" not in first_line:
            raise RuntimeError(
                f"FGIS CY{year} CSV header validation failed. First line: {first_line[:200]!r}"
            )

        s3_key = raw_fgis_weekly_key(year, as_of)
        s3 = boto3.client("s3", region_name=AWS_REGION)
        s3.put_object(
            Bucket=BUCKET,
            Key=s3_key,
            Body=data,
            ContentType="text/csv",
        )
        logger.info(
            "Uploaded %.1f KB → s3://%s/%s",
            len(data) / 1024,
            BUCKET,
            s3_key,
        )
        return s3_key

    @task()
    def log_completion(s3_key: str) -> None:
        """Log the completed snapshot key for observability."""
        logger.info("FGIS weekly snapshot complete: s3://%s/%s", BUCKET, s3_key)

    s3_key = fetch_snapshot()
    log_completion(s3_key)


fgis_weekly_ingest_dag()
