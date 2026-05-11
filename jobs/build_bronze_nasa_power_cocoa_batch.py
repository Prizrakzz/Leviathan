from __future__ import annotations

import argparse
from pathlib import Path

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.paths import bronze_weather_key
from leviathan.storage.s3 import upload_file_to_s3
from leviathan.transforms.raw_to_bronze.nasa_power import transform_nasa_power_json_to_bronze


logger = get_logger("build_bronze_nasa_power_cocoa_batch")


def infer_country_region_from_path(path: Path) -> tuple[str, str]:
    """
    Expected raw path:
    data/raw/weather/nasa_power/cocoa/<country>/<region>/<file>.json
    """
    parts = path.parts

    try:
        cocoa_index = parts.index("cocoa")
    except ValueError as exc:
        raise ValueError(
            f"Could not infer country/region from path: {path}. "
            "Expected path containing /cocoa/<country>/<region>/"
        ) from exc

    try:
        country = parts[cocoa_index + 1]
        region = parts[cocoa_index + 2]
    except IndexError as exc:
        raise ValueError(
            f"Could not infer country/region from path: {path}. "
            "Expected path containing /cocoa/<country>/<region>/"
        ) from exc

    return country, region


def upload_bronze_file(
    bronze_file: Path,
    bucket: str,
    aws_region: str,
    country: str,
    region: str,
) -> None:
    year_part = next(part for part in bronze_file.parts if part.startswith("year="))
    month_part = next(part for part in bronze_file.parts if part.startswith("month="))

    year = int(year_part.split("=")[1])
    month = int(month_part.split("=")[1])

    s3_key = bronze_weather_key(
        source="nasa_power",
        commodity="cocoa",
        country=country,
        region=region,
        year=year,
        month=month,
        filename=bronze_file.name,
    )

    upload_file_to_s3(
        local_path=bronze_file,
        bucket=bucket,
        key=s3_key,
        aws_region=aws_region,
    )

    logger.info("Uploaded bronze weather file to s3://%s/%s", bucket, s3_key)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--raw-dir",
        default="data/raw/weather/nasa_power/cocoa",
        help="Root directory containing raw NASA POWER cocoa JSON files",
    )
    parser.add_argument(
        "--ingest-date",
        required=True,
        help="Raw ingest date, format YYYY-MM-DD",
    )
    parser.add_argument(
        "--upload",
        action="store_true",
        help="Upload bronze Parquet files to S3",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional max number of raw JSON files to process for testing",
    )

    args = parser.parse_args()

    load_env()

    bucket = get_required_env("LEVIATHAN_BUCKET")
    aws_region = get_required_env("AWS_REGION")

    raw_dir = Path(args.raw_dir)

    if not raw_dir.exists():
        raise FileNotFoundError(f"Raw NASA POWER directory not found: {raw_dir}")

    raw_json_files = sorted(raw_dir.rglob("*.json"))

    if args.limit is not None:
        raw_json_files = raw_json_files[: args.limit]

    if not raw_json_files:
        raise FileNotFoundError(f"No raw JSON files found under: {raw_dir}")

    logger.info("Found %s raw NASA POWER JSON files", len(raw_json_files))

    output_base_dir = Path("data/bronze/weather/nasa_power/cocoa")

    success_count = 0
    failure_count = 0

    for raw_json_path in raw_json_files:
        try:
            country, region = infer_country_region_from_path(raw_json_path)

            logger.info(
                "Processing raw NASA POWER JSON country=%s region=%s file=%s",
                country,
                region,
                raw_json_path,
            )

            bronze_file = transform_nasa_power_json_to_bronze(
                raw_json_path=raw_json_path,
                output_base_dir=output_base_dir,
                commodity="cocoa",
                country=country,
                region=region,
                ingest_date=args.ingest_date,
            )

            if args.upload:
                upload_bronze_file(
                    bronze_file=bronze_file,
                    bucket=bucket,
                    aws_region=aws_region,
                    country=country,
                    region=region,
                )

            success_count += 1

        except Exception:
            failure_count += 1
            logger.exception("Failed processing raw JSON: %s", raw_json_path)

    logger.info(
        "Batch bronze build complete. success=%s failure=%s total=%s",
        success_count,
        failure_count,
        len(raw_json_files),
    )

    if failure_count > 0:
        raise RuntimeError(f"{failure_count} files failed during batch bronze build.")


if __name__ == "__main__":
    main()