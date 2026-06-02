"""AWS Batch task: FNC Colombia bronze Parquet to silver Parquet."""
from __future__ import annotations

import argparse
import io
import logging
import sys
from datetime import datetime, timezone

import pandas as pd

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.paths import (
    bronze_fnc_key,
    silver_fnc_colombia_area_department_key,
    silver_fnc_colombia_exports_port_type_key,
    silver_fnc_colombia_monthly_key,
)
from leviathan.storage.s3 import get_thread_local_s3_client, s3_download_with_retry
from leviathan.transforms.bronze_to_silver.fnc_colombia import (
    AREA_OUTPUT_COLUMNS,
    EXPORTS_PORT_TYPE_OUTPUT_COLUMNS,
    MONTHLY_OUTPUT_COLUMNS,
    transform_fnc_colombia_bronze_to_silver,
)

logger = get_logger("fnc_colombia_silver_task")

_BRONZE_SERIES = [
    "produccion_mensual",
    "precio_ex_dock_mensual",
    "precio_interno_mensual",
    "area_departamento",
    "exportaciones_total_volumen",
    "exportaciones_total_valor",
    "exportaciones_puerto_tipo",
]


def _parse_bool(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    return value.strip().lower() in {"1", "true", "yes", "y"}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="FNC Colombia bronze -> silver")
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    parser.add_argument("--force-overwrite", default="false")
    parser.add_argument(
        "--years",
        default="all",
        help="Comma-separated years or 'all'. Useful for smoke tests.",
    )
    args = parser.parse_args()
    args.force_overwrite = _parse_bool(args.force_overwrite)
    return args


def _selected_years(value: str) -> set[int] | None:
    if value.strip().lower() == "all":
        return None
    return {int(item.strip()) for item in value.split(",") if item.strip()}


def _target_exists(s3_client, bucket: str, key: str) -> bool:
    try:
        s3_client.head_object(Bucket=bucket, Key=key)
        return True
    except s3_client.exceptions.ClientError as exc:
        if exc.response["Error"]["Code"] == "404":
            return False
        raise


def _read_bronze_series(bucket: str, aws_region: str) -> dict[str, pd.DataFrame]:
    s3 = get_thread_local_s3_client(aws_region)
    series: dict[str, pd.DataFrame] = {}
    for series_name in _BRONZE_SERIES:
        key = bronze_fnc_key(series_name)
        raw_bytes = s3_download_with_retry(bucket, key, s3)
        df = pd.read_parquet(io.BytesIO(raw_bytes))
        series[series_name] = df
        logger.info("read FNC bronze series=%s rows=%d key=%s", series_name, len(df), key)
    return series


def _write_parquet(
    bucket: str,
    aws_region: str,
    key: str,
    df: pd.DataFrame,
    force_overwrite: bool,
) -> str:
    s3 = get_thread_local_s3_client(aws_region)
    if not force_overwrite and _target_exists(s3, bucket, key):
        logger.info("skipping existing silver partition: %s", key)
        return "skipped"
    buf = io.BytesIO()
    df.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=buf.getvalue(),
        ContentType="application/octet-stream",
    )
    logger.info("wrote silver partition: %s rows=%d", key, len(df))
    return "written"


def _filter_years(df: pd.DataFrame, years: set[int] | None) -> pd.DataFrame:
    if years is None or df.empty:
        return df
    return df.loc[df["year"].isin(years)].copy()


def _write_grouped(
    df: pd.DataFrame,
    output_columns: list[str],
    bucket: str,
    aws_region: str,
    force_overwrite: bool,
    key_fn,
) -> tuple[int, int]:
    written = skipped = 0
    if df.empty:
        return written, skipped
    for year, group in df.groupby("year"):
        key = key_fn(int(year))
        status = _write_parquet(
            bucket,
            aws_region,
            key,
            group[output_columns].reset_index(drop=True),
            force_overwrite,
        )
        if status == "written":
            written += 1
        else:
            skipped += 1
    return written, skipped


def _validate_uniqueness(monthly: pd.DataFrame, area: pd.DataFrame, exports: pd.DataFrame) -> None:
    checks = [
        ("monthly", monthly, ["leviathan_slug", "year", "month", "date"]),
        ("area_department", area, ["leviathan_slug", "department", "year"]),
        (
            "exports_port_type",
            exports,
            ["leviathan_slug", "year", "month", "port", "coffee_type"],
        ),
    ]
    for label, df, key_cols in checks:
        if df.empty:
            continue
        duplicate_mask = df.duplicated(subset=key_cols, keep=False)
        if duplicate_mask.any():
            preview = df.loc[duplicate_mask, key_cols].drop_duplicates().head(5).to_dict("records")
            raise ValueError(f"FNC Colombia {label} has duplicate output rows: {preview}")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
        stream=sys.stderr,
    )
    load_env()
    args = _parse_args()

    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    aws_region = args.aws_region or get_required_env("AWS_REGION")
    years = _selected_years(args.years)

    start = datetime.now(timezone.utc)
    bronze = _read_bronze_series(bucket, aws_region)
    silver = transform_fnc_colombia_bronze_to_silver(bronze)
    monthly = _filter_years(silver.monthly, years)
    area = _filter_years(silver.area_department, years)
    exports = _filter_years(silver.exports_port_type, years)
    _validate_uniqueness(monthly, area, exports)

    written = skipped = 0
    w, s = _write_grouped(
        monthly,
        MONTHLY_OUTPUT_COLUMNS,
        bucket,
        aws_region,
        args.force_overwrite,
        silver_fnc_colombia_monthly_key,
    )
    written += w
    skipped += s
    w, s = _write_grouped(
        area,
        AREA_OUTPUT_COLUMNS,
        bucket,
        aws_region,
        args.force_overwrite,
        silver_fnc_colombia_area_department_key,
    )
    written += w
    skipped += s
    w, s = _write_grouped(
        exports,
        EXPORTS_PORT_TYPE_OUTPUT_COLUMNS,
        bucket,
        aws_region,
        args.force_overwrite,
        silver_fnc_colombia_exports_port_type_key,
    )
    written += w
    skipped += s

    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    logger.info(
        "Done FNC Colombia silver written=%d skipped=%d rows=%d elapsed=%.1fs",
        written,
        skipped,
        len(monthly) + len(area) + len(exports),
        elapsed,
    )


if __name__ == "__main__":
    main()
