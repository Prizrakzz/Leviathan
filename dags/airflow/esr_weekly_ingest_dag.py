"""ESR weekly ingest DAG — snapshot USDA FAS Export Sales Reporting data.

Runs every Thursday at 14:00 UTC, after ESR publishes (~08:00 ET / 13:00 UTC).

Pipeline
--------
fetch_all_snapshots  →  transform_all_to_bronze  →  log_completion

Design notes
------------
- Both ingest and bronze transform run inline in the Airflow worker.
  A Glue Python Shell job for 20 files taking ~5s of work would spend
  60–90s in cold-start billing overhead — 12–18× cost inflation.
  Inline is the correct choice for this data volume.

- No threading in fetch_all_snapshots.  The FAS API is a government server
  (api.fas.usda.gov via api.data.gov), not a CDN.  Sequential requests with
  a 1.0s sleep prevent 429s.  20 API calls complete in ~20s — fast enough.

- Both the current and next-crop marketing year are fetched per commodity.
  ESR publishes new-crop forward sales before the marketing year opens.
  The new-crop outstanding_sales values are the esr_new_crop_sales_z signal.

- Prior-year backfill is handled by the CLI script
  jobs/ingest/fetch_usda_esr.py --mode backfill
  and the Glue job jobs/glue/raw_to_bronze_usda_esr.py --mode backfill.
"""
from __future__ import annotations

import datetime
import io
import json
import os

import boto3
import requests
from airflow.decorators import dag, task
from airflow.utils.dates import days_ago

from leviathan.common.logging import get_logger
from leviathan.storage.paths import bronze_esr_key, raw_esr_weekly_key, silver_esr_key
from leviathan.transforms.raw_to_bronze.usda_esr import transform_esr_json_to_bronze
from leviathan.transforms.bronze_to_silver.usda_esr import transform_esr_bronze_to_silver

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

AWS_REGION    = os.environ.get("AWS_REGION", "us-east-1")
LEVIATHAN_ENV = os.environ.get("LEVIATHAN_ENV", "dev")
PROJECT       = os.environ.get("LEVIATHAN_PROJECT", "leviathan")
BUCKET        = os.environ.get("LEVIATHAN_BUCKET", f"{PROJECT}-{LEVIATHAN_ENV}-shahem-001")
FAS_API_KEY   = os.environ.get("FAS_API_KEY", "")

_API_BASE = "https://api.fas.usda.gov"
_DOWNLOAD_TIMEOUT = 30     # seconds per API call
_REQUEST_SLEEP    = 1.0    # seconds between requests — government server, not CDN
_MIN_SIZE_BYTES   = 500

# Commodity codes to snapshot every Thursday.
TARGET_COMMODITY_CODES = [101, 102, 103, 104, 107, 401, 701, 801, 901, 902]

_WHEAT_CODES       = frozenset({101, 102, 103, 104, 105, 106, 107, 201})
_COTTON_RICE_CODES = frozenset({1201, 1202, 1203, 1301, 1302, 3202})

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _marketing_year_start_month(commodity_code: int) -> int:
    if commodity_code in _WHEAT_CODES:
        return 6
    if commodity_code in _COTTON_RICE_CODES:
        return 8
    return 9


def _current_marketing_year(commodity_code: int, reference: datetime.date) -> int:
    start_month = _marketing_year_start_month(commodity_code)
    if reference.month >= start_month:
        return reference.year
    return reference.year - 1


def _build_url(commodity_code: int, market_year: int) -> str:
    return (
        f"{_API_BASE}/api/esr/exports"
        f"/commodityCode/{commodity_code}"
        f"/allCountries"
        f"/marketYear/{market_year}"
    )


# ---------------------------------------------------------------------------
# DAG definition
# ---------------------------------------------------------------------------

@dag(
    dag_id="esr_weekly_ingest",
    description=(
        "Weekly snapshot of USDA FAS ESR export commitment data. "
        "Fetches current and new-crop marketing year for all target commodity codes. "
        "Stores immutable as_of-partitioned JSON (raw) and Parquet (bronze) in S3."
    ),
    schedule="0 14 * * 4",  # Every Thursday at 14:00 UTC
    start_date=days_ago(1),
    catchup=False,
    tags=["leviathan", "esr", "usda", "fas"],
)
def esr_weekly_ingest_dag() -> None:

    @task()
    def fetch_all_snapshots() -> list[dict]:
        """Fetch ESR JSON for all commodity codes × [current, new-crop] years.

        Returns a list of metadata dicts describing each uploaded raw file,
        passed to the bronze transform task.
        """
        if not FAS_API_KEY:
            raise RuntimeError(
                "FAS_API_KEY environment variable is not set. "
                "Obtain a free key at https://api.data.gov/signup and add it "
                "to the Airflow environment / Secrets Manager."
            )

        today = datetime.date.today()
        as_of = today.strftime("%Y%m%d")

        # Build (code, market_year) pairs — current + new-crop for each code.
        pairs: list[tuple[int, int]] = []
        for code in TARGET_COMMODITY_CODES:
            cur = _current_marketing_year(code, today)
            pairs.append((code, cur))
            pairs.append((code, cur + 1))

        s3 = boto3.client("s3", region_name=AWS_REGION)
        session = requests.Session()

        uploaded: list[dict] = []
        skipped  = 0
        failed   = 0

        for i, (code, year) in enumerate(pairs):
            s3_key = raw_esr_weekly_key(code, year, as_of)
            url    = _build_url(code, year)

            logger.info("GET commodity_code=%d market_year=%d as_of=%s", code, year, as_of)

            try:
                resp = session.get(
                    url,
                    timeout=_DOWNLOAD_TIMEOUT,
                    headers={"X-Api-Key": FAS_API_KEY},
                )

                if resp.status_code == 404:
                    logger.info("  [skip] 404 — no data for code=%d year=%d", code, year)
                    skipped += 1
                    continue

                if resp.status_code == 429:
                    raise RuntimeError(
                        f"ESR API rate limit hit (429) on code={code} year={year}. "
                        "Increase _REQUEST_SLEEP or request a higher quota from api.data.gov."
                    )

                resp.raise_for_status()
                data = resp.content

                if len(data) < _MIN_SIZE_BYTES:
                    logger.warning(
                        "  [skip] response too small (%d B) for code=%d year=%d — "
                        "possible error page",
                        len(data), code, year,
                    )
                    skipped += 1
                    continue

                # Validate it's a non-empty JSON array
                parsed = json.loads(data)
                if not isinstance(parsed, list) or len(parsed) == 0:
                    logger.info("  [skip] empty/invalid JSON array for code=%d year=%d", code, year)
                    skipped += 1
                    continue

                s3.put_object(
                    Bucket=BUCKET,
                    Key=s3_key,
                    Body=data,
                    ContentType="application/json",
                )
                logger.info(
                    "  Uploaded %.1f KB → s3://%s/%s",
                    len(data) / 1024, BUCKET, s3_key,
                )
                uploaded.append({
                    "commodity_code": code,
                    "market_year":    year,
                    "as_of":          as_of,
                    "s3_key":         s3_key,
                    "size_bytes":     len(data),
                })

            except Exception as exc:  # noqa: BLE001
                logger.error("  FAILED code=%d year=%d — %s", code, year, exc)
                failed += 1

            # Sleep between requests — government server, sequential only.
            if i < len(pairs) - 1:
                import time
                time.sleep(_REQUEST_SLEEP)

        logger.info(
            "fetch_all_snapshots complete. uploaded=%d  skipped=%d  failed=%d",
            len(uploaded), skipped, failed,
        )

        if failed:
            raise RuntimeError(
                f"{failed} ESR fetch(es) failed — see task log. "
                "DAG will not proceed to bronze transform."
            )

        return uploaded

    @task()
    def transform_all_to_bronze(uploaded: list[dict]) -> int:
        """Transform all fetched raw JSON files to bronze Parquet in-place.

        Downloads each raw JSON from S3, runs transform_esr_json_to_bronze,
        writes Parquet, and uploads to the bronze S3 key.  Runs inline —
        no Glue cold-start overhead for what is ~5s of actual work.

        Returns the number of bronze files written.
        """
        import pyarrow as pa  # noqa: F401 — verify pyarrow is available before looping
        today_iso = datetime.date.today().isoformat()

        s3 = boto3.client("s3", region_name=AWS_REGION)
        success = 0
        failed  = 0

        for item in uploaded:
            code     = item["commodity_code"]
            year     = item["market_year"]
            as_of    = item["as_of"]
            raw_key  = item["s3_key"]

            try:
                response  = s3.get_object(Bucket=BUCKET, Key=raw_key)
                raw_bytes = response["Body"].read()

                df = transform_esr_json_to_bronze(
                    raw_bytes=raw_bytes,
                    commodity_code=code,
                    market_year=year,
                    as_of_date=as_of,
                    ingest_date=today_iso,
                )

                b_key = bronze_esr_key(code, year, as_of)

                buf = io.BytesIO()
                df.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
                buf.seek(0)

                s3.put_object(
                    Bucket=BUCKET,
                    Key=b_key,
                    Body=buf.read(),
                    ContentType="application/octet-stream",
                )
                logger.info(
                    "  Bronze → s3://%s/%s  rows=%d",
                    BUCKET, b_key, len(df),
                )
                success += 1

            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "  FAILED bronze for code=%d year=%d — %s", code, year, exc
                )
                failed += 1

        logger.info(
            "transform_all_to_bronze complete. success=%d  failed=%d",
            success, failed,
        )

        if failed:
            raise RuntimeError(
                f"{failed} bronze transform(s) failed — see task log."
            )

        return success

    @task()
    def transform_all_to_silver(uploaded: list[dict]) -> int:
        """Transform all bronze Parquet files to silver in-place.

        Downloads each bronze Parquet from S3, runs transform_esr_bronze_to_silver,
        writes silver Parquet, and uploads to the silver S3 key.  Runs inline —
        same as the bronze task.

        Returns the number of silver files written.
        """
        import pandas as pd  # noqa: F401 — local import keeps top-level clean

        s3 = boto3.client("s3", region_name=AWS_REGION)
        success = 0
        failed  = 0

        for item in uploaded:
            code  = item["commodity_code"]
            year  = item["market_year"]
            as_of = item["as_of"]

            b_key = bronze_esr_key(code, year, as_of)
            s_key = silver_esr_key(code, year, as_of)

            try:
                bronze_bytes = s3.get_object(Bucket=BUCKET, Key=b_key)["Body"].read()
                df_bronze = pd.read_parquet(io.BytesIO(bronze_bytes))

                df_silver = transform_esr_bronze_to_silver(df_bronze, market_year=year)

                buf = io.BytesIO()
                df_silver.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
                buf.seek(0)

                s3.put_object(
                    Bucket=BUCKET,
                    Key=s_key,
                    Body=buf.read(),
                    ContentType="application/octet-stream",
                )
                logger.info(
                    "  Silver → s3://%s/%s  rows=%d",
                    BUCKET, s_key, len(df_silver),
                )
                success += 1

            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "  FAILED silver for code=%d year=%d — %s", code, year, exc
                )
                failed += 1

        logger.info(
            "transform_all_to_silver complete. success=%d  failed=%d",
            success, failed,
        )

        if failed:
            raise RuntimeError(
                f"{failed} silver transform(s) failed — see task log."
            )

        return success

    @task()
    def log_completion(bronze_count: int, silver_count: int) -> None:
        logger.info(
            "ESR weekly pipeline complete. "
            "bronze_files_written=%d  silver_files_written=%d  bucket=%s",
            bronze_count, silver_count, BUCKET,
        )

    uploaded     = fetch_all_snapshots()
    bronze_count = transform_all_to_bronze(uploaded)
    silver_count = transform_all_to_silver(uploaded)
    log_completion(bronze_count, silver_count)


esr_weekly_ingest_dag()
