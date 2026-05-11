from __future__ import annotations

import argparse 

from pathlib import Path

from leviathan.ingestion.weather.nasa_power import fetch_nasa_power_daily, save_raw_json
from leviathan.common.logging import get_logger
from leviathan.common.config import get_required_env, load_env, load_yaml
from leviathan.storage.paths import raw_weather_key
from leviathan.storage.s3 import upload_file_to_s3

logger = get_logger("ingest_nasa_power_cocoa")

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-date", required = True, help = "YYYYMMDD")
    parser.add_argument("--end-date", required=True, help="YYYYMMDD")
    parser.add_argument("--year", required=True, type=int)
    parser.add_argument("--month", required=True, type=int)
    parser.add_argument("--upload", action="store_true")
    args = parser.parse_args()

    load_env()

    bucket = get_required_env("LEVIATHAN_BUCKET")
    aws_region = get_required_env("AWS_REGION")

    source_config = load_yaml("configs/sources/nasa_power.yaml")
    geography_config = load_yaml("configs/geographies/cocoa_regions.yaml")

    base_url = source_config["base_url"]
    parameters = source_config["parameters"]
    community = source_config["community"]
    output_format = source_config["format"]

    for country_block in geography_config["regions"]:
        country = country_block["country"]

        for location in country_block["locations"]:
            region = location["region"]
            latitude = location["latitude"]
            longitude = location["longitude"]

            payload = fetch_nasa_power_daily(
                base_url=base_url,
                latitude=latitude,
                longitude=longitude,
                start_date=args.start_date,
                end_date=args.end_date,
                parameters=parameters,
                community=community,
                output_format=output_format,
            )

            filename = (
                f"nasa_power_cocoa_{country}_{region}_"
                f"{args.start_date}_{args.end_date}.json"
            )

            local_path = Path("data/raw/weather/nasa_power/cocoa") / country / region / filename
            save_raw_json(payload, local_path)

            s3_key = raw_weather_key(
                source="nasa_power",
                commodity="cocoa",
                country=country,
                region=region,
                year=args.year,
                month=args.month,
                filename=filename,
            )

            if args.upload:
                upload_file_to_s3(
                    local_path=local_path,
                    bucket=bucket,
                    key=s3_key,
                    aws_region=aws_region,
                )
                logger.info("Uploaded to s3://%s/%s", bucket, s3_key)


if __name__ == "__main__":
    main()