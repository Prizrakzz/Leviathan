"""Submit the numbers->pg mirror loader (and/or the parity gate) as a Fargate Batch job.

Runs jobs/utils/load_pg_numbers.py (or jobs/utils/numbers_parity.py with --parity) on the evidence-build
job definition — the same reuse as submit_eval: that jobdef's image bakes src/ + configs/, its execution
role injects EVIDENCE_PG_DSN, and its task role now carries Athena (codified Stage-1). RDS is only
reachable in-VPC, so this is the loader's home.

    python jobs/submit/submit_batch_load_numbers_pg.py --dry-run
    python jobs/submit/submit_batch_load_numbers_pg.py                       # load the P1 set
    python jobs/submit/submit_batch_load_numbers_pg.py --tables silver_fred_fx,silver_noaa_oni
    python jobs/submit/submit_batch_load_numbers_pg.py --parity              # the blocking parity gate
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

logger = get_logger("submit_load_numbers_pg")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    load_env()
    env = os.environ.get("LEVIATHAN_ENV", "dev")
    project = os.environ.get("LEVIATHAN_PROJECT", "leviathan")
    job_queue = f"{project}-{env}-queue-ondemand"                # don't let Spot reclaim a mid-COPY loader
    default_jobdef = f"{project}-{env}-evidence-build"           # image + DSN secret + Athena on the role

    ap = argparse.ArgumentParser(description="Submit the numbers->pg mirror loader as a Batch job")
    ap.add_argument("--tables", default=None, help="comma-separated registry ids (default: loader's P1 set)")
    ap.add_argument("--parity", action="store_true", help="run the pg-vs-Athena parity gate instead")
    # 2026-09-22 (census B1/P1): the SCHEDULED nightly load runs on the purpose-built
    # `leviathan-dev-pg-numbers-loader` jobdef, which carries the real command, the batch job role,
    # 4 vCPU / 16 GB and a pre-start-only retry rule. This flag exists so that jobdef can be SMOKED
    # through the same script the two real loads went through, instead of a bespoke hand command --
    # the pre-arm smoke law. The DEFAULT IS UNCHANGED: evidence-build, which is where the
    # 2026-09-10 full load (16,964,478 rows) and the 2026-09-17 MPOB reload actually ran.
    ap.add_argument("--job-definition", default=None,
                    help=f"Batch job definition (default: {default_jobdef}). Pass "
                         f"{project}-{env}-pg-numbers-loader to smoke the scheduled jobdef.")
    # SENTINEL DEFAULTS, deliberately. These used to be 2 / 8192 unconditionally, which is right for
    # evidence-build (a 16 vCPU / 120 GB jobdef sized for rebuild-slices, not for this) and WRONG for
    # a jobdef that was sized for this job: an unasked-for override would silently shrink the
    # purpose-built loader back to the placeholder revision's 2 vCPU. So an explicit --vcpu/--memory
    # still overrides anything, an unspecified pair keeps 2/8192 on the DEFAULT jobdef byte for byte,
    # and an unspecified pair on ANY OTHER jobdef sends no resourceRequirements at all.
    ap.add_argument("--vcpu", type=int, default=None)
    ap.add_argument("--memory", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    job_definition = args.job_definition or default_jobdef
    aws_region = get_required_env("AWS_REGION")
    script = "jobs/utils/numbers_parity.py" if args.parity else "jobs/utils/load_pg_numbers.py"
    command = [script] + (["--tables", args.tables] if args.tables else [])
    overrides = {"command": command}
    if args.vcpu or args.memory or job_definition == default_jobdef:
        vcpu = args.vcpu or 2
        memory = args.memory or 8192
        overrides["resourceRequirements"] = [{"type": "VCPU", "value": str(vcpu)},
                                             {"type": "MEMORY", "value": str(memory)}]
    job_name = ("numbers-pg-parity" if args.parity else "numbers-pg-load") + (
        f"-{args.tables.replace(',', '-').replace('_', '-')[:40]}" if args.tables else "")

    logger.info("queue=%s job_def=%s command: python %s", job_queue, job_definition, " ".join(command))
    if args.dry_run:
        logger.info("[DRY RUN] would submit job_name=%s", job_name)
        return
    client = boto3.client("batch", region_name=aws_region)
    resp = client.submit_job(jobName=job_name, jobQueue=job_queue, jobDefinition=job_definition,
                             containerOverrides=overrides)
    logger.info("Submitted job_name=%s job_id=%s", job_name, resp["jobId"])
    run_id = utc_now_iso().replace(":", "-")
    write_run_record(Path("data/batch_runs") / f"numbers_pg_{run_id}.json",
                     {"run_id": run_id, "job_name": job_name, "job_id": resp["jobId"],
                      "tables": args.tables, "parity": args.parity})


if __name__ == "__main__":
    main()
