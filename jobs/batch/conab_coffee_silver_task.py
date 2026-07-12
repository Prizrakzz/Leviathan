"""AWS Batch task: CONAB coffee XLS bronze Parquet -> silver Parquet (SILVER-F024).

Every silver object is published through the SILVER-F015 shadow-first publisher with the INV-2 arrow
writer schema from the F010 registry contract (22-column ``silver_conab_coffee``). ``--publish-mode``
defaults to ``dry-run`` (nothing written; the run manifest is a plan) -- a bare run can never touch
the canonical surface (the F004 kill-switch contract).
"""
from __future__ import annotations

import argparse
import io
import logging
import sys
from datetime import datetime, timezone

import pandas as pd

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.silver.flat_producer import authorize_for_contract, build_flat_publish
from leviathan.silver.publisher import ManifestState
from leviathan.silver.registry import load_registry
from leviathan.storage.paths import parse_hive_key, silver_conab_coffee_key
from leviathan.storage.s3 import get_thread_local_s3_client, list_s3_keys, s3_download_with_retry
from leviathan.transforms.bronze_to_silver.conab_coffee import (
    OUTPUT_COLUMNS,
    transform_conab_coffee_bronze_to_silver,
)

logger = get_logger("conab_coffee_silver_task")

_BRONZE_PREFIX = "bronze/production/source=conab_xls/"
_TABLE = "silver_conab_coffee"
_JOB = "conab_coffee_silver"


def _parse_bool(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    return value.strip().lower() in {"1", "true", "yes", "y"}


def _selected_years(value: str) -> set[int] | None:
    if value.strip().lower() == "all":
        return None
    return {int(item.strip()) for item in value.split(",") if item.strip()}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="CONAB coffee bronze -> silver")
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    parser.add_argument("--force-overwrite", default="false")
    parser.add_argument("--years", default="all", help="Comma-separated safra years or 'all'.")
    parser.add_argument("--publish-mode", default="dry-run",
                        choices=["dry-run", "shadow", "canonical"], dest="publish_mode")
    parser.add_argument("--role-arn", default="", dest="role_arn")
    parser.add_argument("--account-id", default="", dest="account_id")
    args = parser.parse_args()
    args.force_overwrite = _parse_bool(args.force_overwrite)
    return args


def _contract() -> dict:
    return load_registry().table(_TABLE)


def _target_exists(s3_client, bucket: str, key: str) -> bool:
    try:
        s3_client.head_object(Bucket=bucket, Key=key)
        return True
    except s3_client.exceptions.ClientError as exc:
        if exc.response["Error"]["Code"] == "404":
            return False
        raise


def _list_bronze_keys(bucket: str, aws_region: str, years: set[int] | None) -> list[str]:
    keys = [
        key
        for key in list_s3_keys(bucket, _BRONZE_PREFIX, aws_region=aws_region)
        if key.endswith(".parquet")
    ]
    if years is not None:
        keys = [
            key
            for key in keys
            if (year := parse_hive_key(key, "safra_year")) and int(year) in years
        ]
    return sorted(keys)


def _read_bronze(bucket: str, aws_region: str, years: set[int] | None) -> pd.DataFrame:
    s3 = get_thread_local_s3_client(aws_region)
    keys = _list_bronze_keys(bucket, aws_region, years)
    if not keys:
        return pd.DataFrame()

    frames = []
    for key in keys:
        raw_bytes = s3_download_with_retry(bucket, key, s3)
        df = pd.read_parquet(io.BytesIO(raw_bytes))
        frames.append(df)
        logger.info("read CONAB bronze rows=%d key=%s", len(df), key)
    return pd.concat(frames, ignore_index=True)


def _validate_uniqueness(df: pd.DataFrame) -> None:
    if df.empty:
        return
    key_cols = ["commodity", "safra_year", "survey_number", "region"]
    duplicate_mask = df.duplicated(subset=key_cols, keep=False)
    if duplicate_mask.any():
        preview = df.loc[duplicate_mask, key_cols].drop_duplicates().head(5).to_dict("records")
        raise ValueError(f"CONAB coffee silver has duplicate output rows: {preview}")


def _publish_grouped(
    df: pd.DataFrame,
    contract: dict,
    auth,
    s3_client,
    bucket: str,
    force_overwrite: bool,
) -> tuple[int, int]:
    """Publish one shadow-first object per (commodity, safra_year) group. Returns (published, skipped).

    dry-run: the manifest reaches VALIDATED and NOTHING is written (published counts the planned
    objects); shadow/canonical: the publisher stages/promotes per its guard verdict."""
    published = skipped = 0
    if df.empty:
        return published, skipped

    for (commodity, safra_year), group in df.groupby(["commodity", "safra_year"], sort=True):
        key = silver_conab_coffee_key(int(safra_year), str(commodity))
        if (
            not force_overwrite
            and auth.may_mutate_canonical
            and s3_client is not None
            and _target_exists(s3_client, bucket, key)
        ):
            logger.info("skipping existing silver partition: %s", key)
            skipped += 1
            continue
        plan = build_flat_publish(
            df=group[OUTPUT_COLUMNS].reset_index(drop=True),
            contract=contract,
            canonical_key=key,
            auth=auth,
            s3_client=s3_client,
            job=_JOB,
        )
        manifest = plan.run()
        if manifest.state in (ManifestState.VALIDATED, ManifestState.CERTIFIED):
            published += 1
        else:
            logger.error("publish did not validate for %s: state=%s", key, manifest.state.value)
    return published, skipped


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
    contract = _contract()
    auth = authorize_for_contract(
        contract, publish_mode=args.publish_mode,
        role_arn=args.role_arn, account_id=args.account_id,
    )
    # dry-run stages nothing (no client needed); shadow + canonical both write to S3.
    s3_client = None if args.publish_mode == "dry-run" else get_thread_local_s3_client(aws_region)

    start = datetime.now(timezone.utc)
    bronze = _read_bronze(bucket, aws_region, years)
    silver = transform_conab_coffee_bronze_to_silver(bronze)
    _validate_uniqueness(silver)
    published, skipped = _publish_grouped(
        silver, contract, auth, s3_client, bucket, args.force_overwrite
    )

    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    logger.info(
        "Done CONAB coffee silver mode=%s published=%d skipped=%d rows=%d elapsed=%.1fs",
        args.publish_mode, published, skipped, len(silver), elapsed,
    )


if __name__ == "__main__":
    main()
