"""Submit `advance_rolling_census` (A-W3 [Reconcile]) as an in-VPC Batch job -- the MANUAL re-bank lane.

The scheduled path runs this same module as the [Reconcile] step of each family's Step Function
(infra/terraform/modules/step_functions/main.tf). This wrapper is for the other case: re-banking a
family's rolling baseline by hand, out of schedule, after a flip the scheduled path has not seen.

    python jobs/submit/submit_batch_advance_rolling_census.py --dry-run \
        --dest-uri s3://leviathan-dev-shahem-001/cascade_census/rolling/psd_monthly/census.json

TWO WARNINGS, both measured, both the reason this file has a docstring at all.

1. THE OVERWRITE IS UNRECOVERABLE, AND NOTHING GUARDS THE CONTENT. `advance_rolling_census` does one
   `put_object` of the census it just produced -- a FULL REPLACE: it never reads the baseline it is
   about to clobber, never merges, and has NO regression or monotonicity check (12 tests in
   tests/unit/test_advance_rolling_census.py; none covers regression). Bucket versioning on
   leviathan-dev-shahem-001 is SUSPENDED, so the clobbered bytes are gone. This is not theoretical:
   the scheduled `unica` reconcile at 2026-08-26T12:16:21Z -- four hours AFTER the 679-leg /
   428-fire lane3-flip census -- overwrote unica's baseline with a 676/404/272 census and nothing
   said a word. Know what the baseline holds before you submit, and check what it holds after.

2. THE CENSUS IS ONLY AS FRESH AS THE SUBMITTED JOBDEF'S IMAGE. `cascade_census` walks the CONFIGS
   BAKED INTO THE CONTAINER, not the repo on the laptop and not the pg mirror's idea of the map, so
   a re-bank on a stale image banks a stale census with a current timestamp -- which is precisely how
   the incident above happened (`leviathan-dev-silver-gate` was pinned to the previous day's worker
   image). This wrapper therefore targets `leviathan-dev-evidence-build`, whose image tracks the
   embedder `:latest`, and NOT the silver-gate jobdef the scheduled path uses. REBUILD AND PUSH THE
   IMAGE FIRST if the flip you are banking landed after the last push; the run record below stamps
   the jobdef so the vintage question is answerable afterwards.

Content note, so the `--dest-uri` is not over-read: `cascade_census.census()` takes no family or table
filter -- it walks every contract. The rolling baseline is per-family in PATH ONLY, and two families
re-banked in the same hour receive byte-identical objects (proven: psd_monthly and unica both wrote
216,225 bytes on 2026-08-26).
"""
from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

import boto3
from leviathan.common.batch_submit import write_run_record
from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.metadata import utc_now_iso

logger = get_logger("submit_advance_rolling_census")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    load_env()
    env = os.environ.get("LEVIATHAN_ENV", "dev")
    project = os.environ.get("LEVIATHAN_PROJECT", "leviathan")
    job_queue = f"{project}-{env}-queue-ondemand"                # no Spot reclaim mid-census
    job_definition = f"{project}-{env}-evidence-build"           # image + DSN secret + Athena on the role

    ap = argparse.ArgumentParser(
        description="Submit advance_rolling_census (the rolling-baseline re-bank) as an in-VPC Batch job")
    # REQUIRED AND EXPLICIT, never derived from a family name. The descriptor key is the SCHEDULE name,
    # not the SFN `family` field, and they differ: configs/silver/dags/production_faostat.json carries
    # family 'faostat' with path segment 'production_faostat', and psd_monthly.json carries family
    # 'usda_psd' with path segment 'psd_monthly'. A family->URI derivation would write the wrong key --
    # and the wrong key here is an unrecoverable overwrite of some OTHER family's baseline.
    ap.add_argument("--dest-uri", required=True,
                    help="s3://bucket/key of the rolling baseline census.json to OVERWRITE (read it "
                         "straight out of configs/silver/dags/<schedule>.json `gate_baseline_uri`)")
    ap.add_argument("--asof", default=None, help="census as-of (default: today UTC -- see the asof-trap note below)")
    ap.add_argument("--vcpu", type=int, default=2)
    ap.add_argument("--memory", type=int, default=8192)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    aws_region = get_required_env("AWS_REGION")
    # ASOF TRAP (measured 2026-08-21): the old frozen default "2026-02-15" made every manual gate
    # run PIT-read the store seven months back -- after the ESR 44-code widening re-vintaged
    # history past February, that read NINE healthy export-pace legs as "metric-empty" and failed
    # the gate on phantom drift (the scheduled path never sees this because the DAG passes the
    # real scheduled time). A census asof must default to NOW unless the caller pins one.
    # The same trap reaches THIS job through a second door: cascade_census's own --asof defaults to
    # CENSUS_ASOF_DEFAULT = "2026-02-15". advance_rolling_census makes --asof required so it can never
    # inherit that silently, and a wrapper that hardcoded a date would reintroduce it here.
    if not args.asof:
        from datetime import datetime, timezone
        args.asof = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    command = ["jobs/audit/advance_rolling_census.py", "--asof", args.asof, "--dest-uri", args.dest_uri]
    overrides = {"command": command,
                 # cascade_census is pg-mirror-only BY ASSERTION: it raises unless
                 # GRAPHRAG_NUMBERS_BACKEND=pg, EVIDENCE_PG_DSN is set and pgnumbers.enabled(), and it
                 # runs behind a hard Athena tripwire. NEITHER jobdef bakes the backend var (measured
                 # 2026-08-26 on evidence-build:109 and silver-gate:27 -- the sibling gate wrapper's
                 # comment claiming the scheduled jobdef bakes it is FALSE as deployed); the SFN
                 # supplies it as a containerOverride exactly as this line does. EVIDENCE_PG_DSN does
                 # arrive from Secrets Manager on both jobdefs, so the backend var is all that is needed.
                 "environment": [{"name": "GRAPHRAG_NUMBERS_BACKEND", "value": "pg"}],
                 "resourceRequirements": [{"type": "VCPU", "value": str(args.vcpu)},
                                          {"type": "MEMORY", "value": str(args.memory)}]}
    # the family segment of the dest key, for a legible job name (the key is .../rolling/<family>/census.json).
    # SANITIZED to the Batch jobName alphabet (review find, 2026-08-26: a dest key like .../y.json made the
    # raw segment 'y.json', and the API rejects the dot AFTER the operator has already read the overwrite
    # banner -- a name must never be the thing that fails a submission).
    import re
    family = next((p for p in reversed(args.dest_uri.rstrip("/").split("/")) if p and p != "census.json"),
                  "baseline")
    job_name = ("advance-rolling-census-" + re.sub(r"[^A-Za-z0-9-]", "-", family.replace("_", "-")))[:128]

    logger.info("queue=%s job_def=%s command: python %s", job_queue, job_definition, " ".join(command))
    logger.info("OVERWRITE (unrecoverable -- bucket versioning is Suspended): %s", args.dest_uri)
    # THE ONE CONTROL THE TOOL ITSELF LACKS (review find): show the operator WHAT is about to be
    # clobbered -- the baseline's age and verdict counts -- before the irreversible put. Read-only,
    # fail-soft: an unreadable baseline (first bank, permissions) prints as such and never blocks.
    try:
        import json as _json
        m = re.match(r"^s3://([^/]+)/(.+)$", args.dest_uri)
        if m:
            obj = boto3.client("s3", region_name=aws_region).get_object(Bucket=m.group(1), Key=m.group(2))
            doc = _json.loads(obj["Body"].read())
            legs = doc.get("legs") or []
            verdicts = {}
            for leg in legs:
                v = (leg or {}).get("verdict", "?")
                verdicts[v] = verdicts.get(v, 0) + 1
            logger.info("CURRENT baseline: LastModified=%s as_of=%s legs=%d verdicts=%s",
                        obj.get("LastModified"), doc.get("as_of_date"), len(legs),
                        {k: verdicts[k] for k in sorted(verdicts)})
        else:
            logger.info("CURRENT baseline: dest-uri is not s3://bucket/key -- nothing read")
    except Exception as e:  # noqa: BLE001 -- a pre-flight peek must never block the re-bank
        logger.info("CURRENT baseline: unreadable (%s: %s) -- possibly the first bank at this key",
                    type(e).__name__, str(e)[:120])
    if args.dry_run:
        logger.info("[DRY RUN] would submit job_name=%s", job_name)
        return
    client = boto3.client("batch", region_name=aws_region)
    resp = client.submit_job(jobName=job_name, jobQueue=job_queue, jobDefinition=job_definition,
                             containerOverrides=overrides)
    logger.info("Submitted job_name=%s job_id=%s", job_name, resp["jobId"])
    run_id = utc_now_iso().replace(":", "-")
    write_run_record(Path("data/batch_runs") / f"advance_rolling_census_{run_id}.json",
                     {"run_id": run_id, "job_name": job_name, "job_id": resp["jobId"],
                      "dest_uri": args.dest_uri, "asof": args.asof, "job_definition": job_definition})


if __name__ == "__main__":
    main()
