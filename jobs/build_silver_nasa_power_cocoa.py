from __future__ import annotations

import argparse
from pathlib import Path

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.paths import silver_weather_key
from leviathan.storage.s3 import upload_file_to_s3
from leviathan.transforms.bronze_to_silver.nasa_power_weather import (
    transform_nasa_power_weather_to_silver,
)


logger = get_logger("build_silver_nasa_power_cocoa")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--bronze-root",
        default="data/bronze/weather/nasa_power/cocoa",
    )
    parser.add_argument(
        "--output-root",
        default="data/silver/weather/nasa_power/cocoa",
    )
    parser.add_argument("--upload", action="store_true")
    args = parser.parse_args()

    load_env()

    bucket = get_required_env("LEVIATHAN_BUCKET")
    aws_region = get_required_env("AWS_REGION")

    written_files = transform_nasa_power_weather_to_silver(
        bronze_root=args.bronze_root,
        output_root=args.output_root,
    )

    if not args.upload:
        logger.info("Upload disabled. Silver NASA POWER files written locally only.")
        return

    for file_path in written_files:
        country_part = next(part for part in file_path.parts if part.startswith("country="))
        region_part = next(part for part in file_path.parts if part.startswith("region="))
        year_part = next(part for part in file_path.parts if part.startswith("year="))
        month_part = next(part for part in file_path.parts if part.startswith("month="))

        country = country_part.split("=")[1]
        region = region_part.split("=")[1]
        year = int(year_part.split("=")[1])
        month = int(month_part.split("=")[1])

        s3_key = silver_weather_key(
            source="nasa_power",
            commodity="cocoa",
            country=country,
            region=region,
            year=year,
            month=month,
            filename=file_path.name,
        )

        upload_file_to_s3(
            local_path=file_path,
            bucket=bucket,
            key=s3_key,
            aws_region=aws_region,
        )

        logger.info("Uploaded silver weather to s3://%s/%s", bucket, s3_key)


if __name__ == "__main__":
    main()