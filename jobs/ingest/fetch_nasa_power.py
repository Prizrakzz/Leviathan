from __future__ import annotations

import argparse
import datetime
import hashlib
import time
from pathlib import Path
from time import sleep

from leviathan.common.config import get_required_env, load_env, load_yaml
from leviathan.common.dates import month_windows
from leviathan.common.logging import get_logger
from leviathan.ingestion.weather.nasa_power import fetch_nasa_power_daily, save_raw_json
from leviathan.storage.metadata import utc_now_iso, write_json_metadata
from leviathan.storage.paths import raw_weather_key
from leviathan.storage.raw_metadata import check_min_file_size, write_raw_s3_metadata
from leviathan.storage.s3 import s3_object_exists, upload_file_to_s3


logger = get_logger("backfill_raw_nasa_power")


def build_raw_filename(
    commodity: str,
    country: str,
    region: str,
    start_date: str,
    end_date: str,
) -> str:
    return f"nasa_power_{commodity}_{country}_{region}_{start_date}_{end_date}.json"


def build_local_raw_path(
    commodity: str,
    country: str,
    region: str,
    filename: str,
) -> Path:
    return Path(f"data/raw/weather/nasa_power/{commodity}") / country / region / filename


def build_metadata_key(commodity: str, run_id: str, filename: str) -> str:
    return f"metadata/runs/source=nasa_power/commodity={commodity}/run_id={run_id}/{filename}"


def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument("--commodity", required=True)
    parser.add_argument("--start-year", required=True, type=int)
    parser.add_argument("--end-year", required=True, type=int)

    parser.add_argument("--country", default=None)
    parser.add_argument("--region", default=None)

    parser.add_argument("--upload", action="store_true")
    parser.add_argument("--skip-existing-s3", action="store_true")
    parser.add_argument("--sleep-seconds", type=float, default=0.5)
    parser.add_argument("--limit", type=int, default=None)

    args = parser.parse_args()

    # Do not ingest beyond this year without an explicit ML overlap window review.
    MAX_INGEST_YEAR: int = datetime.date.today().year
    if args.end_year > MAX_INGEST_YEAR:
        raise SystemExit(
            f"ERROR: --end-year {args.end_year} exceeds MAX_INGEST_YEAR={MAX_INGEST_YEAR}. "
            "Update MAX_INGEST_YEAR only after an explicit ML overlap window review."
        )

    load_env()

    bucket = get_required_env("LEVIATHAN_BUCKET")
    aws_region = get_required_env("AWS_REGION")

    source_config = load_yaml("configs/sources/nasa_power.yaml")
    geography_config = load_yaml(f"configs/geographies/{args.commodity}_regions.yaml")

    base_url = source_config["base_url"]
    parameters = source_config["parameters"]
    community = source_config["community"]
    output_format = source_config["format"]

    run_id = utc_now_iso().replace(":", "-")
    run_started_at = utc_now_iso()

    run_records: list[dict] = []

    api_call_count = 0
    skipped_count = 0
    success_count = 0
    failure_count = 0

    logger.info("Starting NASA POWER %s backfill run_id=%s", args.commodity, run_id)

    for window in month_windows(args.start_year, args.end_year):
        for country_block in geography_config["regions"]:
            country = country_block["country"]

            if args.country and country != args.country:
                continue

            for location in country_block["locations"]:
                region = location["region"]

                if args.region and region != args.region:
                    continue

                filename = build_raw_filename(
                    commodity=args.commodity,
                    country=country,
                    region=region,
                    start_date=window.start_yyyymmdd,
                    end_date=window.end_yyyymmdd,
                )

                local_path = build_local_raw_path(
                    commodity=args.commodity,
                    country=country,
                    region=region,
                    filename=filename,
                )

                s3_key = raw_weather_key(
                    source="nasa_power",
                    commodity=args.commodity,
                    country=country,
                    region=region,
                    year=window.year,
                    month=window.month,
                    filename=filename,
                )

                task_started = time.time()

                record = {
                    "run_id": run_id,
                    "source": "nasa_power",
                    "commodity": args.commodity,
                    "country": country,
                    "region": region,
                    "year": window.year,
                    "month": window.month,
                    "start_date": window.start_yyyymmdd,
                    "end_date": window.end_yyyymmdd,
                    "local_path": str(local_path),
                    "s3_bucket": bucket if args.upload else None,
                    "s3_key": s3_key if args.upload else None,
                    "status": None,
                    "error": None,
                    "started_at": utc_now_iso(),
                    "finished_at": None,
                    "duration_seconds": None,
                }

                try:
                    if local_path.exists():
                        logger.info("Skipping existing local file: %s", local_path)
                        skipped_count += 1
                        record["status"] = "skipped_local_exists"

                        if args.upload:
                            upload_file_to_s3(
                                local_path=local_path,
                                bucket=bucket,
                                key=s3_key,
                                aws_region=aws_region,
                            )
                            record["status"] = "uploaded_existing_local"

                        continue

                    if args.skip_existing_s3 and args.upload:
                        if s3_object_exists(bucket=bucket, key=s3_key, aws_region=aws_region):
                            logger.warning(
                                "Skipping duplicate S3 object (already exists): s3://%s/%s",
                                bucket, s3_key,
                            )
                            skipped_count += 1
                            record["status"] = "skipped_s3_exists"
                            continue

                    if args.limit is not None and api_call_count >= args.limit:
                        logger.info("Limit reached: %s API calls", args.limit)
                        break

                    logger.info(
                        "Fetching NASA POWER country=%s region=%s year=%s month=%s",
                        country,
                        region,
                        window.year,
                        window.month,
                    )

                    payload = fetch_nasa_power_daily(
                        base_url=base_url,
                        latitude=location["latitude"],
                        longitude=location["longitude"],
                        start_date=window.start_yyyymmdd,
                        end_date=window.end_yyyymmdd,
                        parameters=parameters,
                        community=community,
                        output_format=output_format,
                    )

                    save_raw_json(payload=payload, output_path=local_path)

                    if args.upload:
                        upload_file_to_s3(
                            local_path=local_path,
                            bucket=bucket,
                            key=s3_key,
                            aws_region=aws_region,
                        )

                        raw_bytes = local_path.read_bytes()
                        check_min_file_size(raw_bytes, "nasa_power", context=s3_key)
                        record["file_size_bytes"] = len(raw_bytes)
                        record["sha256"] = hashlib.sha256(raw_bytes).hexdigest()
                        write_raw_s3_metadata(
                            bucket, s3_key, raw_bytes, base_url, "application/json", aws_region
                        )

                    api_call_count += 1
                    success_count += 1
                    record["status"] = "success"

                    if args.sleep_seconds > 0:
                        sleep(args.sleep_seconds)

                except Exception as exc:  # noqa: BLE001 — any download or upload error is logged; loop continues to the next station
                    failure_count += 1
                    record["status"] = "failed"
                    record["error"] = str(exc)
                    logger.exception(
                        "Failed country=%s region=%s year=%s month=%s",
                        country,
                        region,
                        window.year,
                        window.month,
                    )

                finally:
                    record["finished_at"] = utc_now_iso()
                    record["duration_seconds"] = round(time.time() - task_started, 3)
                    run_records.append(record)

            if args.limit is not None and api_call_count >= args.limit:
                break

        if args.limit is not None and api_call_count >= args.limit:
            break

    run_summary = {
        "run_id": run_id,
        "source": "nasa_power",
        "commodity": args.commodity,
        "stage": "raw_backfill",
        "start_year": args.start_year,
        "end_year": args.end_year,
        "country_filter": args.country,
        "region_filter": args.region,
        "upload": args.upload,
        "skip_existing_s3": args.skip_existing_s3,
        "started_at": run_started_at,
        "finished_at": utc_now_iso(),
        "success_count": success_count,
        "skipped_count": skipped_count,
        "failure_count": failure_count,
        "api_call_count": api_call_count,
        "records": run_records,
    }

    metadata_path = write_json_metadata(
        run_summary,
        Path(f"data/metadata/runs/nasa_power/{args.commodity}") / f"run_{run_id}.json",
    )

    logger.info("Wrote run metadata: %s", metadata_path)

    if args.upload:
        metadata_key = build_metadata_key(
            commodity=args.commodity,
            run_id=run_id,
            filename=metadata_path.name,
        )
        upload_file_to_s3(
            local_path=metadata_path,
            bucket=bucket,
            key=metadata_key,
            aws_region=aws_region,
        )
        logger.info("Uploaded run metadata to s3://%s/%s", bucket, metadata_key)

    logger.info(
        "Backfill complete. success=%s skipped=%s failures=%s api_calls=%s",
        success_count,
        skipped_count,
        failure_count,
        api_call_count,
    )

    if failure_count > 0:
        raise RuntimeError(f"{failure_count} NASA POWER backfill tasks failed.")


if __name__ == "__main__":
    main()
