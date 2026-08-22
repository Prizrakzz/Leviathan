from __future__ import annotations

import argparse
import datetime
import hashlib
import logging
import time
from pathlib import Path
from time import sleep

from leviathan.common.config import get_required_env, load_env, load_yaml
from leviathan.common.dates import month_windows
from leviathan.common.logging import get_logger
from leviathan.ingestion.weather.nasa_power import fetch_nasa_power_daily
from leviathan.storage.metadata import utc_now_iso, write_json_metadata
from leviathan.storage.paths import raw_weather_key
from leviathan.storage.raw_metadata import check_min_file_size, write_raw_s3_metadata
from leviathan.storage.s3 import list_s3_keys, s3_object_exists, upload_file_to_s3

logger = get_logger("backfill_raw_nasa_power")


def _is_trailing_window(year: int, month: int) -> bool:
    """True for the CURRENT and PREVIOUS calendar months -- the two windows the existence skips
    must never preserve (the partial-month permanence trap, 2026-08-22). By month M-2 a window's
    raw object has been refetched complete at least once and may be treated as immutable again."""
    today = datetime.date.today()
    cur_y, cur_m = today.year, today.month
    prev_y, prev_m = (cur_y, cur_m - 1) if cur_m > 1 else (cur_y - 1, 12)
    return (year, month) in ((cur_y, cur_m), (prev_y, prev_m))



def discover_commodities(bucket: str, aws_region: str) -> list[str]:
    """Commodity slugs from configs/geographies/*_regions.yaml in S3 (thin-contract 'all' sentinel)."""
    keys = list_s3_keys(bucket, "configs/geographies/", suffix="_regions.yaml", aws_region=aws_region)
    return sorted(k.split("/")[-1][: -len("_regions.yaml")] for k in keys)


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


def _process_commodity(
    args: argparse.Namespace, commodity: str, bucket: str, aws_region: str, source_config: dict,
) -> int:
    """Fetch NASA POWER raw for ONE commodity over ``[args.start_year, args.end_year]``.

    Returns the per-commodity failure count; ``main`` aggregates them across commodities. The window
    write-gate (never request a not-yet-started month) and per-station skip-existing are unchanged."""
    geography_config = load_yaml(f"configs/geographies/{commodity}_regions.yaml")

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

    logger.info("Starting NASA POWER %s backfill run_id=%s", commodity, run_id)

    for window in month_windows(args.start_year, args.end_year):
        # WRITE-GATE (BF-W1): never request a month that has not started -- the API answers
        # future windows with an EMPTY parameter payload, and writing that to raw fabricates
        # presence (live-proven: Aug-Dec 2026 raw files with zero daily records failed every
        # raw->bronze run). The current, partial month is legitimate (real days up to the
        # source's ~1-week lag); only strictly-future windows are skipped.
        if window.start_date > datetime.date.today():
            logger.info("SKIP future window %s-%02d (not started; no raw file written)",
                        window.year, window.month)
            continue
        # PARTIAL-MONTH PERMANENCE FIX (2026-08-22): a month first fetched MID-month writes a
        # partial raw object, and the existence skips below then preserve the hole forever --
        # July 2026 sat at 12/31 days across every commodity while daily runs kept "succeeding"
        # (chirps 0/31, cpc 16/31 -- same trap, three fetchers). The CURRENT and PREVIOUS
        # calendar months are therefore ALWAYS refetched regardless of local/S3 existence: two
        # windows per run is cheap, and by M-2 a month's object is immutable-complete again.
        refetch_trailing = _is_trailing_window(window.year, window.month)
        if refetch_trailing:
            logger.info("TRAILING window %s-%02d: existence skips disabled (partial-month fix)",
                        window.year, window.month)
        for country_block in geography_config["regions"]:
            country = country_block["country"]

            if args.country and country != args.country:
                continue

            for location in country_block["locations"]:
                region = location["region"]

                if args.region and region != args.region:
                    continue

                filename = build_raw_filename(
                    commodity=commodity,
                    country=country,
                    region=region,
                    start_date=window.start_yyyymmdd,
                    end_date=window.end_yyyymmdd,
                )

                local_path = build_local_raw_path(
                    commodity=commodity,
                    country=country,
                    region=region,
                    filename=filename,
                )

                s3_key = raw_weather_key(
                    source="nasa_power",
                    commodity=commodity,
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
                    "commodity": commodity,
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
                    if local_path.exists() and not refetch_trailing:
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

                    if args.skip_existing_s3 and args.upload and not refetch_trailing:
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

                    write_json_metadata(payload=payload, output_path=local_path)

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
        "commodity": commodity,
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
        Path(f"data/metadata/runs/nasa_power/{commodity}") / f"run_{run_id}.json",
    )

    logger.info("Wrote run metadata: %s", metadata_path)

    if args.upload:
        metadata_key = build_metadata_key(
            commodity=commodity,
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
        "NASA POWER %s complete. success=%s skipped=%s failures=%s api_calls=%s",
        commodity,
        success_count,
        skipped_count,
        failure_count,
        api_call_count,
    )

    return failure_count


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    parser = argparse.ArgumentParser()

    # A-Wave-3 thin-contract: every arg optional. --commodity 'all' iterates every discovered
    # commodity; --start-year/--end-year self-window to the CURRENT calendar year (with
    # --skip-existing-s3 a daily run is incremental + self-heals within-year gaps). An explicit
    # --commodity/--start-year/--end-year is the preserved backfill invocation.
    parser.add_argument("--commodity", default="all",
                        help="commodity slug, or 'all' to iterate every discovered commodity (default: all)")
    parser.add_argument("--start-year", type=int, default=None, help="default: current year")
    parser.add_argument("--end-year", type=int, default=None, help="default: current year")

    parser.add_argument("--country", default=None)
    parser.add_argument("--region", default=None)

    # Upload defaults ON for the cloud ingestion contract; --no-upload is the local dry-run escape.
    parser.add_argument("--upload", dest="upload", action="store_true", default=True)
    parser.add_argument("--no-upload", dest="upload", action="store_false")
    parser.add_argument("--skip-existing-s3", action="store_true")
    parser.add_argument("--sleep-seconds", type=float, default=0.5)
    parser.add_argument("--limit", type=int, default=None)

    args = parser.parse_args()

    load_env()
    current_year = datetime.date.today().year
    if args.start_year is None:
        args.start_year = current_year
    if args.end_year is None:
        args.end_year = current_year

    # Do not ingest beyond this year without an explicit ML overlap window review.
    if args.end_year > current_year:
        raise SystemExit(
            f"ERROR: --end-year {args.end_year} exceeds MAX_INGEST_YEAR={current_year}. "
            "Update the review gate only after an explicit ML overlap window review."
        )

    bucket = get_required_env("LEVIATHAN_BUCKET")
    aws_region = get_required_env("AWS_REGION")
    source_config = load_yaml("configs/sources/nasa_power.yaml")

    if args.commodity.strip().lower() == "all":
        commodities = discover_commodities(bucket, aws_region)
    else:
        commodities = [args.commodity.strip()]
    logger.info("NASA POWER fetch: %d commodities, years=%d-%d, upload=%s",
                len(commodities), args.start_year, args.end_year, args.upload)

    failed: list[str] = []
    for commodity in commodities:
        try:
            fc = _process_commodity(args, commodity, bucket, aws_region, source_config)
            if fc:
                failed.append(commodity)
        except Exception as exc:  # noqa: BLE001 -- one commodity's failure must not kill the rest
            logger.error("[%s] FAILED: %s: %s", commodity, type(exc).__name__, str(exc)[:300])
            failed.append(commodity)

    if failed:
        raise RuntimeError(f"NASA POWER fetch failed for {len(failed)} commodities: {failed[:10]}")


if __name__ == "__main__":
    main()
