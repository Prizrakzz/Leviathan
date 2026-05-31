"""AWS Batch task: USDA FGIS Export Inspections bronze → silver Parquet.

Reads per-CY bronze Parquets from S3, aggregates per-shipment rows into
weekly volumes with cumulative season-to-date (CTD), and writes partitions
under ``silver/fgis/``.

Marketing year / calendar year boundary
-----------------------------------------
A single marketing year spans **two** calendar year (CY) bronze files:

    corn / soybeans  (Sep-start):  MY2024 = CY2024 (Sep–Dec) + CY2025 (Jan–Aug)
    wheat classes    (Jun-start):  MY2024 = CY2024 (Jun–Dec) + CY2025 (Jan–May)

For a requested set of marketing years Y, this task loads bronze CY files
for years Y and Y+1 (i.e. the union of all CYs needed).  The transform then
filters by ``marketing_year`` column — which was already computed during
bronze creation — so no date arithmetic is needed here.

Usage
-----
    # Dry-run: show which partitions would be written
    python jobs/batch/fgis_silver_task.py --bucket leviathan-dev-shahem-001 \\
        --aws-region us-east-1 --dry-run

    # Smoke test: corn + soy MY2024 only
    python jobs/batch/fgis_silver_task.py --marketing-years 2024 --slugs corn_cbot,soybeans_cbot

    # Full backfill
    python jobs/batch/fgis_silver_task.py

    # Force overwrite
    python jobs/batch/fgis_silver_task.py --force-overwrite true
"""
from __future__ import annotations

import argparse
import io
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import pandas as pd

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.paths import bronze_fgis_key, parse_hive_key, silver_fgis_key
from leviathan.storage.s3 import (
    get_thread_local_s3_client,
    list_s3_keys,
    s3_download_with_retry,
)
from leviathan.transforms.bronze_to_silver.usda_fgis import (
    OUTPUT_COLUMNS,
    _SLUG_MY_START_MONTH,
    transform_fgis_bronze_to_silver,
)

logger = get_logger("fgis_silver_task")

_BRONZE_PREFIX = "bronze/production/source=usda_fgis_export_inspections/"
_FGIS_MIN_CY = 1983


# ---------------------------------------------------------------------------
# Arg parsing
# ---------------------------------------------------------------------------

def _parse_bool(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    return value.strip().lower() in {"1", "true", "yes", "y"}


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return parsed


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="USDA FGIS bronze -> silver")
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    parser.add_argument(
        "--force-overwrite",
        default="false",
        help="Re-write silver partitions even if they already exist.",
    )
    parser.add_argument(
        "--workers",
        type=_positive_int,
        default=8,
        help="Concurrent S3 write workers (default: 8).",
    )
    parser.add_argument(
        "--marketing-years",
        default="all",
        dest="marketing_years",
        help="Comma-separated marketing years or 'all' (default: all).",
    )
    parser.add_argument(
        "--slugs",
        default="all",
        help="Comma-separated leviathan slugs or 'all' (default: all).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Log what would be written without actually writing.",
    )
    args = parser.parse_args()
    args.force_overwrite = _parse_bool(args.force_overwrite)
    return args


# ---------------------------------------------------------------------------
# CY selection
# ---------------------------------------------------------------------------

def _cy_years_for_marketing_years(
    marketing_years: list[int],
) -> list[int]:
    """Return the sorted list of calendar years needed to cover *marketing_years*.

    For every requested marketing year Y, we need CY Y (data starts mid-year)
    and CY Y+1 (data continues into the next calendar year).
    """
    cy_set: set[int] = set()
    for my in marketing_years:
        cy_set.add(my)
        cy_set.add(my + 1)
    return sorted(cy_set)


def _available_cy_years(bucket: str, aws_region: str) -> list[int]:
    """List all CY years for which a bronze Parquet exists in S3."""
    keys = list_s3_keys(bucket, _BRONZE_PREFIX, suffix=".parquet", aws_region=aws_region)
    years: list[int] = []
    for key in keys:
        year_str = parse_hive_key(key, "year")
        if year_str.isdigit():
            years.append(int(year_str))
    return sorted(set(years))


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------

def _load_cy_bronze(bucket: str, year: int, aws_region: str) -> pd.DataFrame:
    """Download and deserialise one CY bronze Parquet."""
    s3 = get_thread_local_s3_client(aws_region)
    key = bronze_fgis_key(year)
    raw_bytes = s3_download_with_retry(bucket, key, s3)
    df = pd.read_parquet(io.BytesIO(raw_bytes))
    logger.info("loaded bronze CY=%d key=%s rows=%d", year, key, len(df))
    return df


def _load_bronze_union(
    bucket: str,
    cy_years: list[int],
    aws_region: str,
    workers: int,
) -> pd.DataFrame:
    """Load and concatenate multiple CY bronze Parquets in parallel."""
    frames: list[pd.DataFrame] = []
    errors = 0

    with ThreadPoolExecutor(max_workers=min(workers, len(cy_years))) as executor:
        future_to_year = {
            executor.submit(_load_cy_bronze, bucket, cy, aws_region): cy
            for cy in cy_years
        }
        for future in as_completed(future_to_year):
            cy = future_to_year[future]
            try:
                frames.append(future.result())
            except Exception as exc:  # noqa: BLE001
                logger.error("failed to load CY=%d: %s", cy, exc)
                errors += 1

    if errors:
        raise RuntimeError(f"{errors} CY bronze file(s) failed to load — aborting.")

    if not frames:
        return pd.DataFrame()

    return pd.concat(frames, ignore_index=True)


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

def _target_exists(s3_client, bucket: str, key: str) -> bool:
    try:
        s3_client.head_object(Bucket=bucket, Key=key)
        return True
    except s3_client.exceptions.ClientError as exc:
        if exc.response["Error"]["Code"] == "404":
            return False
        raise


def _write_partition(
    bucket: str,
    aws_region: str,
    slug: str,
    marketing_year: int,
    df: pd.DataFrame,
    force_overwrite: bool,
    dry_run: bool,
) -> str:
    key = silver_fgis_key(slug, marketing_year)

    if dry_run:
        logger.info("[DRY RUN] Would write: %s rows=%d", key, len(df))
        return "dry_run"

    s3_client = get_thread_local_s3_client(aws_region)
    if not force_overwrite and _target_exists(s3_client, bucket, key):
        logger.info("skipping existing silver partition: %s", key)
        return "skipped"

    buf = io.BytesIO()
    df.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
    s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=buf.getvalue(),
        ContentType="application/octet-stream",
    )
    logger.info("wrote silver partition: %s rows=%d", key, len(df))
    return "written"


def _write_partitions(
    silver: pd.DataFrame,
    bucket: str,
    aws_region: str,
    force_overwrite: bool,
    dry_run: bool,
    workers: int,
    slug_filter: set[str] | None,
    my_filter: set[int] | None,
) -> tuple[int, int, int]:
    """Write one silver Parquet per (slug, marketing_year) partition.

    Returns:
        (written, skipped, dry_run_count) counts.
    """
    groups: list[tuple[str, int, pd.DataFrame]] = []
    for (slug, marketing_year), group in silver.groupby(
        ["leviathan_slug", "marketing_year"]
    ):
        slug = str(slug)
        marketing_year = int(marketing_year)
        if slug_filter is not None and slug not in slug_filter:
            continue
        if my_filter is not None and marketing_year not in my_filter:
            continue
        groups.append((slug, marketing_year, group[OUTPUT_COLUMNS].reset_index(drop=True)))

    if not groups:
        logger.warning("No silver partitions to write after slug/MY filtering.")
        return 0, 0, 0

    written = skipped = dry_run_count = errors = completed = 0

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_partition = {
            executor.submit(
                _write_partition,
                bucket,
                aws_region,
                slug,
                marketing_year,
                group,
                force_overwrite,
                dry_run,
            ): (slug, marketing_year)
            for slug, marketing_year, group in groups
        }
        for future in as_completed(future_to_partition):
            slug, marketing_year = future_to_partition[future]
            completed += 1
            try:
                status = future.result()
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "failed to write slug=%s marketing_year=%d: %s",
                    slug,
                    marketing_year,
                    exc,
                )
                errors += 1
                continue

            if status == "written":
                written += 1
            elif status == "skipped":
                skipped += 1
            else:
                dry_run_count += 1

            logger.info(
                "write progress=%d/%d slug=%s marketing_year=%d status=%s",
                completed,
                len(groups),
                slug,
                marketing_year,
                status,
            )

    if errors:
        raise SystemExit(1)

    return written, skipped, dry_run_count


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

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

    # --- Resolve filters ---
    slug_filter: set[str] | None = None
    if args.slugs.strip().lower() != "all":
        slug_filter = {s.strip() for s in args.slugs.split(",") if s.strip()}

    # --- Determine marketing years ---
    available_cys = _available_cy_years(bucket, aws_region)
    if not available_cys:
        raise FileNotFoundError(
            f"No FGIS bronze Parquets found under {_BRONZE_PREFIX}"
        )

    # Infer available marketing years from available CYs.
    # A CY provides data for MY(CY-1) (Jan–Aug tail) and MY(CY) (Sep–Dec head).
    all_possible_mys: set[int] = set()
    for cy in available_cys:
        all_possible_mys.add(cy - 1)  # tail end
        all_possible_mys.add(cy)      # head

    if args.marketing_years.strip().lower() == "all":
        requested_mys = sorted(all_possible_mys)
    else:
        requested_mys = sorted(
            int(y.strip())
            for y in args.marketing_years.split(",")
            if y.strip()
        )

    my_filter: set[int] | None = set(requested_mys)

    # --- Determine which CY files to load ---
    needed_cys = [
        cy for cy in _cy_years_for_marketing_years(requested_mys)
        if cy in set(available_cys)
    ]

    if not needed_cys:
        raise FileNotFoundError(
            f"None of the required CY files are available for "
            f"marketing years {requested_mys}"
        )

    logger.info(
        "FGIS silver task  bucket=%s  marketing_years=%s  cys=%s  "
        "slugs=%s  force=%s  dry_run=%s  workers=%d",
        bucket,
        requested_mys,
        needed_cys,
        args.slugs,
        args.force_overwrite,
        args.dry_run,
        args.workers,
    )

    start = datetime.now(timezone.utc)

    # --- Load bronze ---
    bronze = _load_bronze_union(bucket, needed_cys, aws_region, args.workers)
    if bronze.empty:
        logger.warning("No bronze rows loaded — nothing to transform.")
        return

    logger.info("Loaded %d bronze rows from %d CY files", len(bronze), len(needed_cys))

    # --- Transform ---
    silver = transform_fgis_bronze_to_silver(bronze)
    if silver.empty:
        logger.warning("Transform produced empty silver DataFrame — nothing to write.")
        return

    # --- Write partitions ---
    written, skipped, dry_run_count = _write_partitions(
        silver,
        bucket,
        aws_region,
        args.force_overwrite,
        args.dry_run,
        args.workers,
        slug_filter,
        my_filter,
    )

    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    logger.info(
        "Done FGIS silver  written=%d skipped=%d dry_run=%d rows=%d elapsed=%.1fs",
        written,
        skipped,
        dry_run_count,
        len(silver),
        elapsed,
    )


if __name__ == "__main__":
    main()
