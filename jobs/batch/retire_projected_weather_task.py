"""Retire the projected month-grain weather objects after F047 compaction (BF-W1).

The compaction writes coarse ``commodity=<c>/year=<y>/part-000.parquet`` objects NEXT TO the old
month-grain tree (``commodity=<c>/country=<x>/region=<r>/year=<y>/month=<m>/...``) and the
ShadowPublisher never deletes. That leaves BOTH layouts under the extractor's prefix, and
``extractors._paths_with_year_partitions`` filters only on ``year=`` in the key -- every weather row
would be read twice (silently corrupting dedup/count semantics in the feature layer). This job moves
the month-grain tree to the ``silver_old/weather_projected_bfw1/`` backup prefix -- which is ALSO the
F047 rollback artifact (bucket versioning is Suspended, so the backup prefix IS the rollback).

FAIL-CLOSED, per commodity, before any mutation:
  * every year present in the month-grain tree must have its compacted
    ``commodity=<c>/year=<y>/part-000.parquet`` object present and non-empty, else REFUSE;
  * the move itself is copy-then-delete, idempotent (a destination that already exists is not
    re-copied; a rerun resumes where it stopped);
  * deleting canonical objects requires ``--publish-mode canonical`` with a signed approval
    (publish_guard), the same per-table approval the compaction pass used. ``dry-run`` (default)
    prints the plan; there is no ``shadow`` mode for a retire (refused with a message).

Run AFTER ``deproject_glue_table.py --flip`` and BEFORE any feature extraction / gold rebuild:
post-flip the registered table reads only ``commodity/year=`` locations, so Athena never sees the
month tree either way; the extractor is the only double-reader.

Usage:
    python jobs/batch/retire_projected_weather_task.py --source chirps                  # plan only
    python jobs/batch/retire_projected_weather_task.py --source chirps --publish-mode canonical
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.common.publish_guard import PublishTarget, authorize_publish
from leviathan.storage.paths import parse_hive_key
from leviathan.storage.s3 import get_thread_local_s3_client, list_s3_keys

logger = get_logger("retire_projected_weather")

_SILVER_WEATHER = "silver/weather"
_BACKUP_PREFIX = "silver_old/weather_projected_bfw1"
_WORKERS = 32
_SOURCE_TO_TABLE = {
    "nasa_power": "silver_nasa_power",
    "chirps": "silver_chirps",
    "cpc_soil": "silver_cpc_soil",
}


def month_grain_keys(bucket: str, source: str, commodity: str, aws_region: str) -> list[str]:
    """Every projected month-grain object for (source, commodity).

    The ``country=`` segment right after ``commodity=`` is what separates the projected layout
    from the compacted ``commodity=<c>/year=<y>/`` layout, so this prefix cannot select a
    compacted object."""
    prefix = f"{_SILVER_WEATHER}/source={source}/commodity={commodity}/country="
    return list_s3_keys(bucket, prefix, suffix=".parquet", aws_region=aws_region)


def compacted_key(source: str, commodity: str, year: int) -> str:
    return f"{_SILVER_WEATHER}/source={source}/commodity={commodity}/year={year}/part-000.parquet"


def verify_compacted_coverage(
    bucket: str, source: str, commodity: str, keys: list[str], aws_region: str
) -> tuple[dict[int, list[str]], list[int]]:
    """Bucket month keys by year and verify each year's compacted object exists non-empty.

    Returns ``(by_year, missing_years)``; any missing year means REFUSE for this commodity."""
    s3 = get_thread_local_s3_client(aws_region)
    by_year: dict[int, list[str]] = defaultdict(list)
    for k in keys:
        try:
            raw = parse_hive_key(k, "year")
            year = int(raw) if raw is not None else None
        except (TypeError, ValueError):
            year = None
        if year is None:
            logger.warning("skipping un-yeared key (left in place): %s", k)
            continue
        by_year[year].append(k)
    missing: list[int] = []
    for year in sorted(by_year):
        try:
            head = s3.head_object(Bucket=bucket, Key=compacted_key(source, commodity, year))
            if int(head.get("ContentLength", 0)) <= 0:
                missing.append(year)
        except Exception:  # noqa: BLE001 -- any HEAD failure means "not proven present"
            missing.append(year)
    return dict(by_year), missing


def _move_one(bucket: str, key: str, aws_region: str) -> str:
    """Copy ``key`` to the backup prefix (skip if already there), then delete the original."""
    s3 = get_thread_local_s3_client(aws_region)
    dest = f"{_BACKUP_PREFIX}/{key}"
    try:
        s3.head_object(Bucket=bucket, Key=dest)
    except Exception:  # noqa: BLE001 -- absent (or unprovable): copy it
        s3.copy_object(Bucket=bucket, Key=dest, CopySource={"Bucket": bucket, "Key": key})
    s3.delete_object(Bucket=bucket, Key=key)
    return key


def retire_commodity(bucket: str, source: str, commodity: str, aws_region: str, auth) -> dict:
    keys = month_grain_keys(bucket, source, commodity, aws_region)
    if not keys:
        return {"commodity": commodity, "state": "empty", "moved": 0}
    by_year, missing = verify_compacted_coverage(bucket, source, commodity, keys, aws_region)
    if missing:
        logger.error(
            "REFUSED source=%s commodity=%s: %d year(s) lack a compacted object: %s",
            source, commodity, len(missing), missing[:10],
        )
        return {"commodity": commodity, "state": "refused_missing_compacted",
                "missing_years": missing, "moved": 0}
    if not auth.may_mutate_canonical:
        return {"commodity": commodity, "state": "planned",
                "would_move": len(keys), "years": len(by_year)}
    moved = 0
    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        futs = [pool.submit(_move_one, bucket, k, aws_region) for k in keys]
        for fut in as_completed(futs):
            fut.result()  # re-raise per-object failures: a partial move must be LOUD
            moved += 1
    logger.info("source=%s commodity=%s: moved %d month objects -> %s/",
                source, commodity, moved, _BACKUP_PREFIX)
    return {"commodity": commodity, "state": "retired", "moved": moved, "years": len(by_year)}


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s - %(message)s", stream=sys.stderr)
    load_env()
    parser = argparse.ArgumentParser(
        description="retire projected month-grain weather objects to the backup prefix")
    parser.add_argument("--source", required=True, choices=sorted(_SOURCE_TO_TABLE))
    parser.add_argument("--commodity", default="all")
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    parser.add_argument("--publish-mode", default="dry-run")
    args = parser.parse_args()

    if args.publish_mode == "shadow":
        raise SystemExit("retire has no shadow mode: use dry-run to plan, canonical to execute")

    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    aws_region = args.aws_region or get_required_env("AWS_REGION")
    table = _SOURCE_TO_TABLE[args.source]

    import boto3
    sts = boto3.client("sts", region_name=aws_region)
    ident = sts.get_caller_identity()
    auth = authorize_publish(
        PublishTarget(account_id=ident["Account"], bucket=bucket, database="leviathan_dev",
                      prefix=f"{_SILVER_WEATHER}/source={args.source}/", role_arn=ident["Arn"],
                      table=table),
        argv=sys.argv,
    )

    if args.commodity.strip().lower() == "all":
        keys = list_s3_keys(bucket, f"{_SILVER_WEATHER}/source={args.source}/",
                            suffix=".parquet", aws_region=aws_region)
        commodities = sorted({s for s in (parse_hive_key(k, "commodity") for k in keys) if s})
    else:
        commodities = [c.strip() for c in args.commodity.split(",") if c.strip()]

    results = [retire_commodity(bucket, args.source, c, aws_region, auth) for c in commodities]
    refused = [r for r in results if r["state"] == "refused_missing_compacted"]
    summary = {"source": args.source, "mode": auth.mode.value, "results": results}
    print(json.dumps(summary, indent=1))
    if refused:
        logger.error("DONE WITH REFUSALS: %d/%d commodities refused", len(refused), len(commodities))
        raise SystemExit(2)
    logger.info("DONE source=%s: %d commodities, mode=%s", args.source, len(commodities),
                auth.mode.value)


if __name__ == "__main__":
    main()
