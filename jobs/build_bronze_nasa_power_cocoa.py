from __future__ import annotations

import argparse
from pathlib import Path

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.paths import bronze_weather_key
from leviathan.storage.s3 import upload_file_to_s3
from leviathan.transforms.raw_to_bronze.nasa_power import transform_nasa_power_json_to_bronze


logger = get_logger("build_bronze_nasa_power_cocoa")


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
            "Could not infer country/region. Expected path containing /cocoa/<country>/<region>/"
        ) from exc

    country = parts[cocoa_index + 1]
    region = parts[cocoa_index + 2]

    return country, region


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--raw-json",
        required=True,
        help="Local path to raw NASA POWER JSON file",
    )
    parser.add_argument(
        "--ingest-date",
        required=True,
        help="Raw ingest date, format YYYY-MM-DD",
    )
    parser.add_argument(
        "--upload",
        action="store_true",
        help="Upload bronze Parquet file to S3",
    )

    args = parser.parse_args()

    load_env()

    bucket = get_required_env("LEVIATHAN_BUCKET")
    aws_region = get_required_env("AWS_REGION")

    raw_json_path = Path(args.raw_json)
    country, region = infer_country_region_from_path(raw_json_path)

    output_base_dir = Path("data/bronze/weather/nasa_power/cocoa")

    bronze_file = transform_nasa_power_json_to_bronze(
        raw_json_path=raw_json_path,
        output_base_dir=output_base_dir,
        commodity="cocoa",
        country=country,
        region=region,
        ingest_date=args.ingest_date,
    )

    if not args.upload:
        logger.info("Upload disabled. Bronze weather file written locally only.")
        return

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


if __name__ == "__main__":
    main()