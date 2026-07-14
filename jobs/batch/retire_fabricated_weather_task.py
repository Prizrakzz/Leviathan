"""Retire FABRICATED (all-NaN) weather partitions -- silver + bronze twins (BF-W1).

The post-rebuild census proved three fabrication classes in chirps: 27 regions outside the
CHIRPS 50S-50N coverage band (all 46 years), pre-minted FUTURE months, and any residue the
2017 refill cannot recover. Their silver rows and bronze twins are 100%-NaN presence that
misrepresents "no data" as "data with missing values". The honest representation is NO
partition (the ingest write-gate now enforces that at birth); this job retires the legacy
fabrications into the ``silver_old/weather_fabricated_bfw1/`` backup prefix.

FAIL-CLOSED, before any mutation, per key:
  * the SILVER footer must prove ``value`` is all-NaN -- any real value REFUSES the run;
  * the BRONZE twin must be all-NaN or absent -- REAL bronze REFUSES the run (that
    partition needs a rebuild, not a retirement);
  * mutation = copy-to-backup then delete (idempotent resume: existing backup not re-copied);
  * deletions require ``--publish-mode canonical`` with the signed per-table approval
    (LEVIATHAN_APPROVAL_JSON seam); ``dry-run`` (default) verifies + plans only.

The retire set comes from an explicit S3 manifest (JSON list of silver keys) built from the
census -- this job never chooses its own victims.

Usage:
    python jobs/batch/retire_fabricated_weather_task.py --source chirps \
        --manifest-key admin/bfw1/fabricated_chirps_manifest.json [--publish-mode canonical]
"""
from __future__ import annotations

import argparse
import io
import json
import logging
import sys
from concurrent.futures import ThreadPoolExecutor

import pyarrow.parquet as pq

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.common.publish_guard import PublishTarget, authorize_publish
from leviathan.silver.value_census import census_column, file_column_stat
from leviathan.storage.s3 import get_thread_local_s3_client, s3_download_with_retry

logger = get_logger("retire_fabricated_weather")

_BACKUP_PREFIX = "silver_old/weather_fabricated_bfw1"
_WORKERS = 24
_SOURCE_TO_TABLE = {
    "nasa_power": "silver_nasa_power",
    "chirps": "silver_chirps",
    "cpc_soil": "silver_cpc_soil",
}
_SILVER_VALUE_COL = "value"
_BRONZE_VALUE_COL = {"chirps": "precipitation_mm", "cpc_soil": "value", "nasa_power": None}


def bronze_twin_keys(silver_key: str, source: str) -> list[str]:
    """The bronze partition objects mirroring a silver month key (parquet + _meta sidecar)."""
    part = silver_key.split(f"source={source}/", 1)[1].rsplit("/", 1)[0]
    base = f"bronze/weather/source={source}/{part}"
    return [f"{base}/part-000.parquet", f"{base}/_meta.json"]


def _footer_all_nan(bucket: str, key: str, column: str, aws_region: str) -> bool | None:
    """True/False for a readable parquet footer; None when the object is absent."""
    s3 = get_thread_local_s3_client(aws_region)
    try:
        data = s3_download_with_retry(bucket, key, s3)
    except Exception:  # noqa: BLE001 -- absent object
        return None
    st = file_column_stat(pq.ParquetFile(io.BytesIO(data)).metadata, column)
    if st is None:
        return None
    return bool(census_column([st], column).all_nan)


def verify_key(bucket: str, silver_key: str, source: str, aws_region: str) -> tuple[str, str]:
    """Return (silver_key, verdict): 'ok' | 'refuse_silver_real' | 'refuse_bronze_real'."""
    silver_nan = _footer_all_nan(bucket, silver_key, _SILVER_VALUE_COL, aws_region)
    if silver_nan is None:
        return silver_key, "already_gone"
    if silver_nan is False:
        return silver_key, "refuse_silver_real"
    bcol = _BRONZE_VALUE_COL.get(source)
    if bcol:
        bronze_parquet = bronze_twin_keys(silver_key, source)[0]
        bronze_nan = _footer_all_nan(bucket, bronze_parquet, bcol, aws_region)
        if bronze_nan is False:
            return silver_key, "refuse_bronze_real"
    return silver_key, "ok"


def _move_one(bucket: str, key: str, aws_region: str) -> bool:
    """Copy to backup (skip if there), delete original. True when the original existed."""
    s3 = get_thread_local_s3_client(aws_region)
    try:
        s3.head_object(Bucket=bucket, Key=key)
    except Exception:  # noqa: BLE001 -- source gone (resumed run / absent sidecar)
        return False
    dest = f"{_BACKUP_PREFIX}/{key}"
    try:
        s3.head_object(Bucket=bucket, Key=dest)
    except Exception:  # noqa: BLE001 -- backup absent: copy
        s3.copy_object(Bucket=bucket, Key=dest, CopySource={"Bucket": bucket, "Key": key})
    s3.delete_object(Bucket=bucket, Key=key)
    return True


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s - %(message)s", stream=sys.stderr)
    load_env()
    ap = argparse.ArgumentParser(description="retire fabricated all-NaN weather partitions")
    ap.add_argument("--source", required=True, choices=sorted(_SOURCE_TO_TABLE))
    ap.add_argument("--manifest-key", required=True, dest="manifest_key")
    ap.add_argument("--bucket", default=None)
    ap.add_argument("--aws-region", default=None, dest="aws_region")
    ap.add_argument("--publish-mode", default="dry-run")
    args = ap.parse_args()

    if args.publish_mode == "shadow":
        raise SystemExit("retire has no shadow mode: dry-run to verify+plan, canonical to execute")

    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    aws_region = args.aws_region or get_required_env("AWS_REGION")
    table = _SOURCE_TO_TABLE[args.source]

    import boto3
    sts = boto3.client("sts", region_name=aws_region)
    ident = sts.get_caller_identity()
    auth = authorize_publish(
        PublishTarget(account_id=ident["Account"], bucket=bucket, database="leviathan_dev",
                      prefix=f"silver/weather/source={args.source}/", role_arn=ident["Arn"],
                      table=table),
        argv=sys.argv,
    )

    s3 = get_thread_local_s3_client(aws_region)
    manifest = json.loads(s3_download_with_retry(bucket, args.manifest_key, s3))
    silver_keys = manifest["silver_keys"] if isinstance(manifest, dict) else list(manifest)
    expected_prefix = f"silver/weather/source={args.source}/"
    stray = [k for k in silver_keys if not k.startswith(expected_prefix) or "/_" in k]
    if stray:
        raise SystemExit(f"REFUSED: {len(stray)} manifest keys outside {expected_prefix}: {stray[:3]}")
    logger.info("manifest %s: %d silver keys", args.manifest_key, len(silver_keys))

    # 1. VERIFY EVERY KEY before any mutation (fail closed on a single real value).
    verdicts: dict[str, list[str]] = {}
    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        for key, verdict in pool.map(
                lambda k: verify_key(bucket, k, args.source, aws_region), silver_keys):
            verdicts.setdefault(verdict, []).append(key)
    refusals = {v: ks for v, ks in verdicts.items() if v.startswith("refuse")}
    logger.info("verify: %s", {v: len(ks) for v, ks in verdicts.items()})
    if refusals:
        for v, ks in refusals.items():
            logger.error("REFUSED %s: %d keys, e.g. %s", v, len(ks), ks[:3])
        raise SystemExit(2)

    to_retire = verdicts.get("ok", [])
    if not auth.may_mutate_canonical:
        print(json.dumps({"mode": auth.mode.value, "would_retire": len(to_retire),
                          "already_gone": len(verdicts.get("already_gone", []))}))
        return

    # 2. MOVE silver + bronze twins to the backup prefix.
    all_keys: list[str] = []
    for sk in to_retire:
        all_keys.append(sk)
        all_keys.extend(bronze_twin_keys(sk, args.source))
    moved = 0
    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        for existed in pool.map(lambda k: _move_one(bucket, k, aws_region), all_keys):
            moved += 1 if existed else 0
    print(json.dumps({"mode": "canonical", "silver_retired": len(to_retire),
                      "objects_moved": moved, "backup_prefix": _BACKUP_PREFIX}))
    logger.info("DONE: retired %d silver partitions (%d objects incl. bronze twins) -> %s/",
                len(to_retire), moved, _BACKUP_PREFIX)


if __name__ == "__main__":
    main()
