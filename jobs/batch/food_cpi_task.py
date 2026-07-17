"""AWS Batch entrypoint: World Bank food CPI -> raw + bronze + silver (shadow-first).

Fetches CPI data for IND, RUS, IDN, UKR from the World Bank DataBank API,
writes raw JSON + bronze Parquet per country, then publishes the silver table:

    silver/food_cpi/part-000.parquet

Publish contract (A-W4 CLASS-B retrofit)
----------------------------------------
The silver write is routed through the SILVER-F015 shadow-first controlled
publisher via ``leviathan.silver.flat_producer.build_flat_publish`` with the
EXPLICIT INV-2 arrow schema from the F010 ``silver_food_cpi`` contract.
``--publish-mode`` (default ``dry-run``) resolves through the publish guard:

  * dry-run   : nothing is written anywhere.
  * shadow    : the silver object is staged ONLY under ``silver/food_cpi/_shadow/``;
                canonical is untouched. Raw + bronze are NOT written (they are the
                canonical surface too, gated on ``may_mutate_canonical``).
  * canonical : raw + bronze + shadow-stage -> validate -> promote, ONLY with a
                verified signed approval.

Like the guarded ``noaa_iod`` task, raw + bronze touch the canonical surface ONLY
under a fully-authorized canonical publish; a dry-run / shadow run writes nothing
canonical. The legacy ``--dry-run`` flag is retained as an alias for
``--publish-mode dry-run``.

Usage
-----
    python jobs/batch/food_cpi_task.py                         # dry-run (writes nothing)
    python jobs/batch/food_cpi_task.py --publish-mode shadow
    python jobs/batch/food_cpi_task.py --publish-mode canonical --force-overwrite
    python jobs/batch/food_cpi_task.py --dry-run
    python jobs/batch/food_cpi_task.py --countries IND RUS
"""
from __future__ import annotations

import argparse
import io
import json
import logging
import os
import sys
import time

import requests
import pandas as pd

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.silver.flat_producer import authorize_for_contract, build_flat_publish
from leviathan.silver.publisher import ManifestState
from leviathan.silver.registry import load_registry
from leviathan.storage.paths import (
    bronze_food_cpi_key,
    raw_food_cpi_key,
    silver_food_cpi_key,
)
from leviathan.storage.s3 import (
    get_thread_local_s3_client,
    upload_bytes_to_s3,
)
from leviathan.transforms.bronze_to_silver.world_bank_food_cpi import build_food_cpi_silver
from leviathan.transforms.raw_to_bronze.world_bank_food_cpi import extract_food_cpi_bronze

logger = get_logger("food_cpi_task")

_TABLE = "silver_food_cpi"
_JOB = "food_cpi_silver"
_WB_URL_TEMPLATE = (
    "https://api.worldbank.org/v2/country/{iso}/indicator/FP.CPI.TOTL.ZG"
    "?format=json&date=1960:2025&per_page=200"
)
_TIMEOUT      = 30
_POLITE_DELAY = 1.0
_DEFAULT_COUNTRIES = ["IND", "RUS", "IDN", "UKR"]


def _exists(s3_client, bucket: str, key: str) -> bool:
    try:
        s3_client.head_object(Bucket=bucket, Key=key)
        return True
    except Exception:
        return False


def _caller_identity(aws_region: str) -> tuple[str, str]:
    """Best-effort STS identity for the canonical publish target (empty on failure).

    Thin wrapper over the shared resolver ``leviathan.common.aws_identity.resolve_caller_identity``
    (the one idiom the batch-task family shares). Kept as a module-level seam so tests can
    monkeypatch it and readiness/unit runs stay AWS-free; an empty identity still makes the publish
    guard fail closed on the canonical path exactly as before."""
    from leviathan.common.aws_identity import resolve_caller_identity

    return resolve_caller_identity(aws_region)


def _fetch_bronze(
    countries: list[str],
    bucket: str,
    aws_region: str,
    s3_client,
    write_canonical: bool,
) -> tuple[list[pd.DataFrame], int]:
    """Fetch raw CPI per country, extract bronze, and (only when ``write_canonical``) write raw +
    bronze to the canonical surface. Returns (bronze_dfs, error_count). Fetch always happens so the
    silver can be built + shadow-validated even in dry-run / shadow."""
    bronze_dfs: list[pd.DataFrame] = []
    errors = 0

    for i, iso in enumerate(countries):
        url   = _WB_URL_TEMPLATE.format(iso=iso)
        r_key = raw_food_cpi_key(iso)
        b_key = bronze_food_cpi_key(iso)

        logger.info("Fetching %s ...", iso)
        try:
            resp = requests.get(url, timeout=_TIMEOUT)
            resp.raise_for_status()
            raw_bytes = resp.content
        except requests.RequestException:
            logger.exception("HTTP fetch failed for %s", iso)
            errors += 1
            if i < len(countries) - 1:
                time.sleep(_POLITE_DELAY)
            continue

        # Validate response structure
        try:
            payload = json.loads(raw_bytes)
            pages   = payload[0].get("pages", "?")
            if int(pages) > 1:
                logger.warning(
                    "%s: API returned %s pages -- pagination needed; only page 1 ingested",
                    iso, pages,
                )
        except Exception:
            logger.exception("Response for %s is not valid WB JSON", iso)
            errors += 1
            if i < len(countries) - 1:
                time.sleep(_POLITE_DELAY)
            continue

        if write_canonical:
            upload_bytes_to_s3(raw_bytes, bucket, r_key, aws_region)
            logger.info("Raw written -> %s", r_key)

        try:
            df_bronze = extract_food_cpi_bronze(raw_bytes, iso)
        except ValueError:
            logger.exception("Bronze transform failed for %s", iso)
            errors += 1
            if i < len(countries) - 1:
                time.sleep(_POLITE_DELAY)
            continue

        if write_canonical:
            buf = io.BytesIO()
            df_bronze.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
            s3_client.put_object(Bucket=bucket, Key=b_key, Body=buf.getvalue(),
                                 ContentType="application/octet-stream")
            logger.info("Bronze written -> %s  rows=%d", b_key, len(df_bronze))

        bronze_dfs.append(df_bronze)

        if i < len(countries) - 1:
            time.sleep(_POLITE_DELAY)

    return bronze_dfs, errors


def _publish_food_cpi(
    df: pd.DataFrame,
    contract: dict,
    auth,
    s3_client,
    bucket: str,
    *,
    force_overwrite: bool,
) -> ManifestState | None:
    """Publish the flat food-CPI silver object through the shadow-first publisher."""
    canonical_key = silver_food_cpi_key()
    if (
        not force_overwrite
        and auth.may_mutate_canonical
        and s3_client is not None
        and _exists(s3_client, bucket, canonical_key)
    ):
        logger.info(
            "silver exists -- use --publish-mode canonical --force-overwrite to re-run: %s",
            canonical_key,
        )
        return None
    plan = build_flat_publish(
        df=df, contract=contract, canonical_key=canonical_key,
        auth=auth, s3_client=s3_client, job=_JOB,
    )
    manifest = plan.run()
    logger.info(
        "food_cpi silver publish mode=%s state=%s rows=%d key=%s",
        auth.mode.value, manifest.state.value, len(df), canonical_key,
    )
    return manifest.state


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
        stream=sys.stderr,
    )
    load_env()

    parser = argparse.ArgumentParser(description="World Bank food CPI -> raw + bronze + silver")
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    parser.add_argument("--countries", nargs="+", default=_DEFAULT_COUNTRIES, metavar="ISO3")
    parser.add_argument("--force-overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true",
                        help="Alias for --publish-mode dry-run (writes nothing).")
    parser.add_argument("--publish-mode", default="dry-run",
                        choices=["dry-run", "shadow", "canonical"], dest="publish_mode",
                        help="dry-run|shadow|canonical (default dry-run; canonical needs a signed approval)")
    parser.add_argument("--role-arn", default="", dest="role_arn")
    parser.add_argument("--account-id", default="", dest="account_id")
    args = parser.parse_args()

    publish_mode = "dry-run" if args.dry_run else args.publish_mode
    bucket     = args.bucket     or get_required_env("LEVIATHAN_BUCKET")
    aws_region = args.aws_region or get_required_env("AWS_REGION")
    contract = load_registry().table(_TABLE)

    account_id, role_arn = args.account_id, args.role_arn
    if publish_mode == "canonical" and not account_id and not role_arn:
        account_id, role_arn = _caller_identity(aws_region)
    auth = authorize_for_contract(
        contract, publish_mode=publish_mode,
        role_arn=role_arn, account_id=account_id, env=os.environ,
    )
    logger.info("publish authorized: mode=%s may_canonical=%s", auth.mode.value, auth.may_mutate_canonical)

    s3 = get_thread_local_s3_client(aws_region)
    publish_client = None if publish_mode == "dry-run" else s3

    # Fetch raw + bronze per country. Raw + bronze reach the canonical surface only under an
    # authorized canonical publish (may_mutate_canonical); dry-run / shadow write nothing canonical.
    bronze_dfs, errors = _fetch_bronze(
        args.countries, bucket, aws_region, s3, write_canonical=auth.may_mutate_canonical,
    )

    if not bronze_dfs:
        logger.error("No bronze DataFrames produced -- all countries failed")
        sys.exit(1)
    if errors:
        logger.warning("%d country/countries failed ingest", errors)

    df_silver = build_food_cpi_silver(bronze_dfs)

    # Validation diagnostics (Russia 2015 ruble collapse, Ukraine 2022 war inflation).
    for check_iso, check_year, min_z in [("RUS", 2015, 1.5), ("UKR", 2022, 1.5)]:
        row = df_silver[
            (df_silver["country_iso"] == check_iso) &
            (df_silver["year"] == check_year)
        ]
        if not row.empty:
            z = float(row["cpi_yoy_z_5yr"].iloc[0])
            ok = z > min_z if not pd.isna(z) else False
            logger.info(
                "Validation %s %s %d: cpi_yoy_z_5yr=%.2f (expected >%.1f)",
                "OK" if ok else "WARN", check_iso, check_year, z, min_z,
            )

    if publish_mode == "dry-run":
        logger.info("dry-run -- would publish %s rows=%d", silver_food_cpi_key(), len(df_silver))
        print(df_silver.to_string(index=False))

    _publish_food_cpi(df_silver, contract, auth, publish_client, bucket,
                      force_overwrite=args.force_overwrite)

    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
