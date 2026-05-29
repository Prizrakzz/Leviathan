"""FNC Colombia Excel raw → bronze Batch task.

Reads the two FNC bulk Excel files from S3 raw/ and writes one bronze
Parquet per extracted series.

FNC publishes updated Excel files annually.  Each run re-extracts from
the most recently downloaded file in raw/.

S3 key structure
----------------
  Raw:    raw/production/source=fnc/bulk/{filename}.xlsx
  Bronze: bronze/production/source=fnc_excel/series={name}/part-000.parquet

Series written
--------------
  produccion_mensual         — monthly production (1000s 60kg bags)
  precio_ex_dock_mensual     — external price (USD cents/lb)
  precio_interno_mensual     — internal price (COP/125kg)
  area_departamento          — area by department (1000s ha)
  exportaciones_total_volumen — monthly export volume
  exportaciones_total_valor   — monthly export value
  exportaciones_puerto_tipo   — volume+value by port and type

Usage
-----
    python jobs/batch/fnc_excel_task.py [--bucket B] [--aws-region R] [--force-overwrite]
"""
from __future__ import annotations

import argparse
import io
import logging
import sys
from datetime import datetime, timezone

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.paths import bronze_fnc_key
from leviathan.storage.s3 import (
    get_thread_local_s3_client,
    list_s3_keys,
    s3_download_with_retry,
)
from leviathan.transforms.raw_to_bronze.fnc_excel import extract_fnc_excel

logger = get_logger("fnc_excel_task")

_RAW_PREFIX = "raw/production/source=fnc/bulk/"


def _bronze_exists(s3_client, bucket: str, key: str) -> bool:
    try:
        s3_client.head_object(Bucket=bucket, Key=key)
        return True
    except Exception:  # noqa: BLE001
        return False


def _process_file(
    raw_key: str,
    bucket: str,
    aws_region: str,
    force_overwrite: bool,
    ingest_date: str,
) -> tuple[int, int, int]:
    """Download one FNC Excel file, extract all series, write Parquets.

    Returns:
        ``(written, skipped, errors)``
    """
    s3 = get_thread_local_s3_client(aws_region)
    filename = raw_key.rsplit("/", 1)[-1]

    try:
        raw_bytes = s3_download_with_retry(bucket, raw_key, s3)
    except Exception as exc:  # noqa: BLE001
        logger.error("S3 download failed  key=%s: %s", raw_key, exc)
        return 0, 0, 1

    try:
        series_map = extract_fnc_excel(raw_bytes, filename, ingest_date)
    except Exception as exc:  # noqa: BLE001
        logger.error("FNC Excel transform failed  key=%s: %s", raw_key, exc, exc_info=True)
        return 0, 0, 1

    written = skipped = errors = 0
    for series_name, df in series_map.items():
        b_key = bronze_fnc_key(series_name)

        if not force_overwrite and _bronze_exists(s3, bucket, b_key):
            skipped += 1
            continue

        try:
            buf = io.BytesIO()
            df.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
            s3.put_object(
                Bucket=bucket,
                Key=b_key,
                Body=buf.getvalue(),
                ContentType="application/octet-stream",
            )
            logger.info("bronze written  %s  rows=%d", b_key, len(df))
            written += 1
        except Exception as exc:  # noqa: BLE001
            logger.error("Parquet write failed  series=%s: %s", series_name, exc)
            errors += 1

    return written, skipped, errors


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        stream=sys.stderr,
    )

    load_env()

    parser = argparse.ArgumentParser(description="FNC Colombia Excel raw → bronze")
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    parser.add_argument("--force-overwrite", action="store_true")
    args = parser.parse_args()

    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    aws_region = args.aws_region or get_required_env("AWS_REGION")

    raw_keys = list_s3_keys(bucket, _RAW_PREFIX, aws_region=aws_region)
    raw_keys = [k for k in raw_keys if k.lower().endswith(".xlsx")]
    raw_keys.sort()

    logger.info(
        "FNC Excel task  bucket=%s  raw_keys=%d  force=%s",
        bucket, len(raw_keys), args.force_overwrite,
    )

    if not raw_keys:
        logger.warning("No FNC Excel files found under %s", _RAW_PREFIX)
        sys.exit(0)

    ingest_date = datetime.now(timezone.utc).date().isoformat()
    start = datetime.now(timezone.utc)
    total_written = total_skipped = total_errors = 0

    for key in raw_keys:
        w, s, e = _process_file(key, bucket, aws_region, args.force_overwrite, ingest_date)
        total_written += w
        total_skipped += s
        total_errors += e

    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    logger.info(
        "Done  written=%d  skipped=%d  errors=%d  elapsed=%.1fs",
        total_written, total_skipped, total_errors, elapsed,
    )

    if total_errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
