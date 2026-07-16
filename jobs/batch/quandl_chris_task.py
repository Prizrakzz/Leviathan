"""AWS Batch entrypoint: Quandl CHRIS continuous futures -> raw + bronze + silver (shadow-first).

Downloads 36 series (12 slugs x C1/C2/C3 tenors) from Nasdaq Data Link,
computes bronze (settlement prices) and silver (calendar spreads), and
publishes the flat table:

    silver/calendar_spreads/part-000.parquet

Publish contract (A-W4 CLASS-B retrofit)
----------------------------------------
The silver write is routed through the SILVER-F015 shadow-first controlled
publisher (:class:`leviathan.silver.publisher.ShadowPublisher`, FLAT strategy).
``--publish-mode`` (default ``dry-run``) resolves through the publish guard:

  * dry-run   : nothing is written anywhere.
  * shadow    : the silver object is staged ONLY under ``silver/calendar_spreads/_shadow/``;
                canonical is untouched. Raw + bronze are NOT written (gated on
                ``may_mutate_canonical``).
  * canonical : raw + bronze + shadow-stage -> validate -> promote, ONLY with a
                verified signed approval.

STRUCTURAL NOTE (A-W4): ``silver_calendar_spreads`` has NO F010 registry contract
(no ``configs/silver/tables/silver_calendar_spreads.yaml``), so this task cannot use
the contract-driven ``flat_producer.build_flat_publish`` path the other CLASS-B
retrofits use. It routes through the SAME publisher machinery (ShadowPublisher /
StagedObject) directly, encoding the parquet with the task's own writer (no pinned
INV-2 schema, since none is declared). Shadow-first + INV-6 protection are identical;
only the INV-2 registry-schema pin is absent. Adding the registry contract is the
follow-up that would let this task adopt ``build_flat_publish`` verbatim.

The legacy ``--dry-run`` flag is retained as an alias for ``--publish-mode dry-run``.

Prerequisites
-------------
Set NASDAQ_API_KEY in environment or .env.  Register free at https://data.nasdaq.com/sign-up

Usage
-----
    python -m jobs.batch.quandl_chris_task                         # dry-run (writes nothing)
    python -m jobs.batch.quandl_chris_task --publish-mode shadow
    python -m jobs.batch.quandl_chris_task --publish-mode canonical --force-overwrite
    python -m jobs.batch.quandl_chris_task --dry-run
    python -m jobs.batch.quandl_chris_task --slugs corn_cbot soybeans_cbot
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
from leviathan.common.publish_guard import PublishMode, PublishTarget, authorize_publish
from leviathan.silver.publisher import (
    ManifestState,
    PublishStrategy,
    ShadowPublisher,
    StagedObject,
    ValidationHooks,
)
from leviathan.storage.paths import (
    bronze_chris_key,
    raw_chris_key,
    silver_calendar_spreads_key,
)
from leviathan.storage.s3 import (
    get_thread_local_s3_client,
    upload_bytes_to_s3,
)
from leviathan.transforms.bronze_to_silver.quandl_chris import build_calendar_spreads_silver
from leviathan.transforms.raw_to_bronze.quandl_chris import extract_chris_bronze
from jobs.ingest.fetch_quandl_chris import CHRIS_MAP  # reuse dataset ID map

logger = get_logger("quandl_chris_task")

_API_BASE     = "https://data.nasdaq.com/api/v3/datasets"
_TIMEOUT      = 30
_POLITE_DELAY = 1.0
_DEFAULT_START = "1990-01-01"

# silver_calendar_spreads has no registry contract; these identities are the publisher's target.
_TABLE = "silver_calendar_spreads"
_JOB = "quandl_chris_silver"
_DATABASE = "leviathan_dev"
_CANONICAL_ROOT = "silver/calendar_spreads"


def _exists(s3_client, bucket: str, key: str) -> bool:
    try:
        s3_client.head_object(Bucket=bucket, Key=key)
        return True
    except Exception:
        return False


def _write_bronze(s3_client, bucket: str, key: str, df: pd.DataFrame) -> None:
    buf = io.BytesIO()
    df.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
    s3_client.put_object(Bucket=bucket, Key=key, Body=buf.getvalue(),
                         ContentType="application/octet-stream")


def _caller_identity(aws_region: str) -> tuple[str, str]:
    """Best-effort STS identity for the canonical publish target (empty on failure)."""
    try:
        import boto3
        ident = boto3.client("sts", region_name=aws_region).get_caller_identity()
        return ident.get("Account", ""), ident.get("Arn", "")
    except Exception as exc:  # noqa: BLE001 -- dry-run / shadow must not require live credentials
        logger.info("STS identity unavailable (%s); using empty target (dry-run/shadow only)", exc)
        return "", ""


def _fetch_bronze(
    slugs: list[str],
    tenors: list[int],
    start_date: str,
    api_key: str,
    bucket: str,
    aws_region: str,
    s3_client,
    write_canonical: bool,
) -> tuple[dict[str, dict[int, pd.DataFrame]], int]:
    """Fetch raw + extract bronze per (slug, tenor); raw + bronze reach the canonical surface only
    when ``write_canonical``. Returns (non_empty_bronze_by_slug, error_count)."""
    bronze_by_slug: dict[str, dict[int, pd.DataFrame]] = {}
    errors = 0
    total  = len(slugs) * len(tenors)
    count  = 0

    for slug in slugs:
        bronze_by_slug[slug] = {}
        for tenor in tenors:
            ds_id  = f"{CHRIS_MAP[slug]}{tenor}"
            r_key  = raw_chris_key(slug, tenor)
            b_key  = bronze_chris_key(slug, tenor)
            url    = f"{_API_BASE}/{ds_id}.json"
            params = {"api_key": api_key, "start_date": start_date, "order": "asc"}

            count += 1
            logger.info("[%d/%d] Fetching %s C%d (%s) ...", count, total, slug, tenor, ds_id)

            try:
                resp = requests.get(url, params=params, timeout=_TIMEOUT)
                resp.raise_for_status()
                raw_bytes = resp.content
            except requests.HTTPError as e:
                code = e.response.status_code if e.response is not None else "?"
                logger.warning("HTTP %s for %s C%d -- skipping", code, slug, tenor)
                errors += 1
                if count < total:
                    time.sleep(_POLITE_DELAY)
                continue
            except requests.RequestException:
                logger.exception("Request failed: %s C%d", slug, tenor)
                errors += 1
                if count < total:
                    time.sleep(_POLITE_DELAY)
                continue

            n_rows = len(json.loads(raw_bytes).get("dataset", {}).get("data", []))
            logger.info("  %d data rows", n_rows)

            if write_canonical:
                upload_bytes_to_s3(raw_bytes, bucket, r_key, aws_region)
                logger.info("  Raw -> %s", r_key)

            try:
                df_bronze = extract_chris_bronze(raw_bytes, slug, tenor, ds_id)
            except ValueError:
                logger.exception("Bronze parse failed: %s C%d", slug, tenor)
                errors += 1
                if count < total:
                    time.sleep(_POLITE_DELAY)
                continue

            if write_canonical and not df_bronze.empty:
                _write_bronze(s3_client, bucket, b_key, df_bronze)
                logger.info("  Bronze -> %s  rows=%d", b_key, len(df_bronze))

            if not df_bronze.empty:
                bronze_by_slug[slug][tenor] = df_bronze

            if count < total:
                time.sleep(_POLITE_DELAY)

    return {s: t for s, t in bronze_by_slug.items() if t}, errors


def _publish_calendar_spreads(
    df: pd.DataFrame,
    auth,
    s3_client,
    bucket: str,
    *,
    force_overwrite: bool,
) -> ManifestState | None:
    """Publish the flat calendar-spreads silver object through the shadow-first publisher.

    No F010 registry contract exists for ``silver_calendar_spreads`` (see the module docstring),
    so this routes through ShadowPublisher directly with the task's own parquet writer rather than
    the contract-driven ``build_flat_publish``. Shadow-first + INV-6 protection are identical."""
    canonical_key = silver_calendar_spreads_key()
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

    buf = io.BytesIO()
    df.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
    staged = StagedObject(canonical_key=canonical_key, body=buf.getvalue(), row_count=len(df))
    # dry-run (no client) needs a no-op manifest sink; shadow/canonical persist via the default S3 store.
    manifest_store = None if s3_client is not None else (lambda _k, _b: None)
    publisher = ShadowPublisher(
        job=_JOB,
        table=_TABLE,
        database=_DATABASE,
        bucket=bucket,
        canonical_root=_CANONICAL_ROOT,
        auth=auth,
        s3_client=s3_client,
        strategy=PublishStrategy.FLAT,
        validation=ValidationHooks(min_rows=1),
        manifest_store=manifest_store,
    )
    manifest = publisher.run([staged])
    logger.info(
        "calendar_spreads silver publish mode=%s state=%s rows=%d key=%s",
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

    parser = argparse.ArgumentParser(description="Quandl CHRIS -> raw + bronze + silver")
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    parser.add_argument("--api-key", default=None, dest="api_key")
    parser.add_argument("--slugs", nargs="+", default=list(CHRIS_MAP.keys()), metavar="SLUG")
    parser.add_argument("--tenors", nargs="+", type=int, default=[1, 2, 3], metavar="N")
    parser.add_argument("--start-date", default=_DEFAULT_START, dest="start_date")
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
    api_key    = (
        args.api_key
        or os.environ.get("NASDAQ_API_KEY")
        or os.environ.get("QUANDL_API_KEY")
    )
    if not api_key:
        logger.error(
            "NASDAQ_API_KEY not set.  Register free at https://data.nasdaq.com/sign-up"
        )
        sys.exit(1)

    account_id, role_arn = args.account_id, args.role_arn
    if publish_mode == "canonical" and not account_id and not role_arn:
        account_id, role_arn = _caller_identity(aws_region)
    target = PublishTarget(
        account_id=account_id,
        bucket=bucket,
        database=_DATABASE,
        prefix=_CANONICAL_ROOT.rstrip("/") + "/",
        role_arn=role_arn,
        table=_TABLE,
    )
    auth = authorize_publish(target, mode=PublishMode(publish_mode), env=os.environ)
    logger.info("publish authorized: mode=%s may_canonical=%s", auth.mode.value, auth.may_mutate_canonical)

    s3 = get_thread_local_s3_client(aws_region)
    publish_client = None if publish_mode == "dry-run" else s3

    non_empty, errors = _fetch_bronze(
        args.slugs, args.tenors, args.start_date, api_key, bucket, aws_region, s3,
        write_canonical=auth.may_mutate_canonical,
    )
    if not non_empty:
        logger.error("No bronze data produced -- all series failed")
        sys.exit(1)

    df_silver = build_calendar_spreads_silver(non_empty)
    df_silver["date"] = pd.to_datetime(df_silver["date"])

    # Validation diagnostics: corn 2012 backwardation (>0) vs 2016 contango (<0).
    for slug_v, year_v, expected_sign, label in [
        ("corn_cbot", 2012, "positive", "backwardation during drought"),
        ("corn_cbot", 2016, "negative", "contango during surplus"),
    ]:
        rows = df_silver[
            (df_silver["leviathan_slug"] == slug_v)
            & (df_silver["date"].dt.year == year_v)
            & df_silver["spread_c1c3"].notna()
        ]["spread_c1c3"]
        if not rows.empty:
            median_spread = float(rows.median())
            ok = (expected_sign == "positive" and median_spread > 0) or \
                 (expected_sign == "negative" and median_spread < 0)
            logger.info(
                "Validation %s: %s %d median_spread=%.2f (%s)",
                "OK" if ok else "WARN", slug_v, year_v, median_spread, label,
            )

    if publish_mode == "dry-run":
        logger.info(
            "dry-run -- would publish %s rows=%d slugs=%d",
            silver_calendar_spreads_key(), len(df_silver), df_silver["leviathan_slug"].nunique(),
        )
        sample = df_silver[
            (df_silver["leviathan_slug"] == "corn_cbot")
            & (df_silver["date"] >= "2012-06-01")
            & (df_silver["date"] <= "2012-10-01")
        ][["date", "settle_c1", "settle_c3", "spread_c1c3", "spread_c1c3_z_3yr"]].head(8)
        if not sample.empty:
            print(sample.to_string(index=False))

    _publish_calendar_spreads(df_silver, auth, publish_client, bucket,
                              force_overwrite=args.force_overwrite)

    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
