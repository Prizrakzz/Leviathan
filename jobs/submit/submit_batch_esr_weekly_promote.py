"""SILVER-F031 option-b: the raw -> bronze WEEKLY PROMOTION path for the already-landing ESR
weekly snapshots (e.g. the ``as_of=20260712`` raw weeks the DISABLED weekly EventBridge Scheduler /
the manual ``submit_batch_usda_esr_fetch.py`` land under ``raw/production/source=usda_esr/.../
as_of=<date>/all_countries.json``).

The weekly fetch lands raw with NO bronze promotion (D-W1 scaffold). This script DEFINES + BUILDS
the promotion: it lists the raw weekly objects for a target ``--as-of`` (read-only S3 LIST) and
prints the exact raw->bronze plan the ``leviathan-dev-esr-bronze`` job would run
(``jobs/batch/esr_task.py``, weekly keys promote to ``bronze/.../as_of=<date>/part-000.parquet``,
idempotent via head_object skip-existing).

GATED: the default is a DRY-RUN PLAN -- it submits NOTHING. Real promotion is BF-W2: pass BOTH
``--submit`` and ``--i-understand-bf-w2`` to fire the Batch job. This is the raw->bronze half; the
bronze->silver option-b (per-week compact) half is ``submit_batch_b2s_esr.py --vintage-mode all
--publish-mode canonical`` (also BF-W2 gated).

Usage:
    python jobs/submit/submit_batch_esr_weekly_promote.py --as-of 20260712            # dry-run plan
    python jobs/submit/submit_batch_esr_weekly_promote.py --as-of 20260712 --submit --i-understand-bf-w2
"""
from __future__ import annotations

import argparse
import logging
import sys

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.paths import parse_hive_key
from leviathan.storage.s3 import list_s3_keys

logger = get_logger("submit_batch_esr_weekly_promote")

_RAW_PREFIX = "raw/production/source=usda_esr/"
_JOB_DEF_NAME = "leviathan-dev-esr-bronze"          # raw->bronze Batch job (jobs/batch/esr_task.py)
_JOB_QUEUE = "leviathan-dev-queue"
_REGION = "us-east-1"


def build_promotion_plan(raw_keys: list[str], as_of: str) -> list[dict]:
    """Pure: the (commodity_code, market_year, as_of) promotions for the weekly raw objects that
    carry ``as_of=<as_of>``. Idempotent + bounded; no AWS."""
    plan: list[dict] = []
    for key in sorted(raw_keys):
        if f"as_of={as_of}" not in key:
            continue
        code = parse_hive_key(key, "commodity_code")
        year = parse_hive_key(key, "market_year")
        if not (code and year):
            continue
        plan.append({
            "raw_key": key,
            "commodity_code": int(code),
            "market_year": int(year),
            "as_of": as_of,
            "bronze_key": (f"bronze/production/source=usda_esr/commodity_code={code}"
                           f"/market_year={year}/as_of={as_of}/part-000.parquet"),
        })
    return plan


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s - %(message)s", stream=sys.stderr)
    load_env()
    parser = argparse.ArgumentParser(description="ESR raw->bronze weekly promotion (SILVER-F031, gated)")
    parser.add_argument("--as-of", required=True, dest="as_of", help="YYYYMMDD weekly snapshot date")
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=_REGION, dest="aws_region")
    parser.add_argument("--submit", action="store_true", help="actually submit (BF-W2 only)")
    parser.add_argument("--i-understand-bf-w2", action="store_true", dest="ack",
                        help="required acknowledgement that promotion is a BF-W2-gated execution")
    args = parser.parse_args()

    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    raw_keys = list_s3_keys(bucket, _RAW_PREFIX, suffix=".json", aws_region=args.aws_region)
    plan = build_promotion_plan(raw_keys, args.as_of)

    logger.info("ESR weekly promotion plan for as_of=%s: %d raw object(s) -> bronze", args.as_of, len(plan))
    for p in plan:
        logger.info("  code=%d year=%d  %s -> %s",
                    p["commodity_code"], p["market_year"], p["raw_key"], p["bronze_key"])

    if not plan:
        logger.warning("no raw ESR objects carry as_of=%s under %s -- nothing to promote.",
                       args.as_of, _RAW_PREFIX)
        return

    if not (args.submit and args.ack):
        logger.info("[dry-run] plan only -- NOT submitting. Promotion is BF-W2-gated: re-run with "
                    "--submit --i-understand-bf-w2 to fire %s (jobs/batch/esr_task.py, weekly keys, "
                    "skip-existing).", _JOB_DEF_NAME)
        logger.info("[dry-run] BF-W2 follow-on (bronze->silver per-week): "
                    "submit_batch_b2s_esr.py --vintage-mode all --publish-mode canonical")
        return

    # BF-W2 execution path (explicitly acknowledged).
    import boto3
    batch = boto3.client("batch", region_name=args.aws_region)
    resp = batch.submit_job(
        jobName=f"esr-weekly-promote-{args.as_of}",
        jobQueue=_JOB_QUEUE,
        jobDefinition=_JOB_DEF_NAME,
        parameters={"bucket": bucket, "aws_region": args.aws_region},
    )
    logger.info("Submitted raw->bronze promotion: jobId=%s (as_of=%s)", resp["jobId"], args.as_of)


if __name__ == "__main__":
    main()
