"""Submit the USDA PSD LONG attributes table (silver_psd_attributes) as an AWS Batch job.

    python jobs/submit/submit_batch_psd_attributes_silver.py --dry-run
    python jobs/submit/submit_batch_psd_attributes_silver.py --publish-mode shadow
    python jobs/submit/submit_batch_psd_attributes_silver.py --publish-mode canonical --force-overwrite

TWO THINGS ``--dry-run`` COULD MEAN, AND IT MEANS THE FIRST. On this wrapper ``--dry-run`` means
"do not call SubmitJob" (the submit-script idiom across jobs/submit/); the TASK's own writes-nothing
mode is ``--publish-mode dry-run``, which this wrapper forwards. ``--dry-run`` alone therefore
prints the command it would have submitted and exits without touching Batch.

``--force-overwrite`` IS ``store_true`` AND DEFAULTS TO FALSE. Forwarded as-is: without it a
``--publish-mode canonical`` run finds the existing canonical object, skips the publish and exits
0, so the Batch job goes SUCCEEDED with the table untouched. Pass it on every rebuild.

WHY IT REUSES THE psd-silver JOB DEFINITION. The long producer concatenates the SAME bronze
release snapshots as ``jobs/batch/psd_silver_task.py`` -- the 8-9 GiB peak that jobdef's 2 vCPU /
16384 MB exists for lives in the shared load, not in the table-specific tail (module.batch's
psd_silver header carries the measurement). It also SELF-PROMOTES, and kms:Sign lives only on
module.iam.silver_publisher_role, which that jobdef carries and the shared b3-flat-silver jobdef
does not; submitting canonical onto a jobdef without it fails closed at the approval gate.
The command is overridden per submit, so the jobdef's baked wide-table command never runs here.

THE LONG TAIL IS BIGGER THAN THE WIDE ONE and this has not been measured against live bronze: the
long table keeps ~69 attribute labels where the wide one keeps 8, so the post-fan-out frame it
holds alongside the shared concat is larger. If the job exits 137, raise the ceiling explicitly
with ``--vcpu 4 --memory 30720`` (16384 is the Fargate maximum at 2 vCPU) rather than retrying.
No resource override is sent by default -- the jobdef's own sizing is the honest starting point.

The queue is the ON-DEMAND queue: ``leviathan-dev-queue`` is Spot, and a reclaimed publisher is a
half-run write path.
"""
from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

import boto3
from leviathan.common.batch_submit import sanitize_batch_job_name, write_run_record
from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.metadata import utc_now_iso

logger = get_logger("submit_batch_psd_attributes_silver")

_MODULE = "jobs.batch.psd_attributes_silver_task"


def build_command(
    *,
    publish_mode: str,
    force_overwrite: bool,
    on_uncovered: str = "drop",
) -> list[str]:
    """Build the container command for one long-table run.

    Module form ([-m]) is mandatory, not stylistic: the task imports ``jobs.batch.psd_silver_task``
    for the shared bronze load and F2 guard, and only ``-m`` from the image's /app working
    directory puts the repository root on ``sys.path``.

    ``--on-uncovered drop`` is the transform's own default and is emitted only when overridden, so
    the submitted command stays byte-comparable with the job definition's baked one.
    """
    command = ["-m", _MODULE, "--publish-mode", publish_mode]
    if force_overwrite:
        command.append("--force-overwrite")
    if on_uncovered != "drop":
        command += ["--on-uncovered", on_uncovered]
    return command


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    load_env()

    env = os.environ.get("LEVIATHAN_ENV", "dev")
    project = os.environ.get("LEVIATHAN_PROJECT", "leviathan")
    default_queue = f"{project}-{env}-queue-ondemand"     # never Spot: a reclaimed publisher half-writes
    default_jobdef = f"{project}-{env}-psd-silver"        # memory + the publisher role (see header)

    ap = argparse.ArgumentParser(
        description="Submit the USDA PSD long attributes silver producer as a Batch job"
    )
    ap.add_argument("--publish-mode", default="shadow", choices=["dry-run", "shadow", "canonical"],
                    dest="publish_mode",
                    help="forwarded to the task (default shadow: never touches canonical)")
    ap.add_argument("--on-uncovered", default="drop", choices=["drop", "raise"],
                    dest="on_uncovered",
                    help="forwarded to the task's R4 uncovered-pair policy (default drop)")
    ap.add_argument("--force-overwrite", action="store_true",
                    help="forwarded to the task; without it a canonical run over an existing "
                         "object skips and the job still succeeds")
    ap.add_argument("--queue", default=None, help=f"override the Batch queue (default: {default_queue})")
    ap.add_argument("--job-definition", default=None, dest="job_definition",
                    help=f"override the Batch job definition (default: {default_jobdef})")
    ap.add_argument("--vcpu", type=int, default=None,
                    help="override the job definition's vCPU (default: the job definition's own)")
    ap.add_argument("--memory", type=int, default=None,
                    help="override the job definition's memory in MiB (default: the job definition's own)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the submission and exit WITHOUT calling Batch")
    args = ap.parse_args()

    if (args.vcpu is None) != (args.memory is None):
        # Fargate validates the pair, not each half: a lone --memory 30720 against the baked 2 vCPU
        # is rejected at submit with an unhelpful message.
        ap.error("--vcpu and --memory must be given together")

    aws_region = get_required_env("AWS_REGION")
    job_queue = args.queue or default_queue
    job_definition = args.job_definition or default_jobdef

    command = build_command(publish_mode=args.publish_mode, force_overwrite=args.force_overwrite,
                            on_uncovered=args.on_uncovered)
    overrides: dict[str, object] = {"command": command}
    if args.vcpu is not None:
        overrides["resourceRequirements"] = [
            {"type": "VCPU", "value": str(args.vcpu)},
            {"type": "MEMORY", "value": str(args.memory)},
        ]
    job_name = sanitize_batch_job_name(f"psd-attributes-silver-{args.publish_mode}")

    logger.info("queue=%s job_def=%s command: python %s", job_queue, job_definition, " ".join(command))
    if args.dry_run:
        logger.info("[DRY RUN] would submit job_name=%s overrides=%s", job_name, overrides)
        return

    client = boto3.client("batch", region_name=aws_region)
    resp = client.submit_job(jobName=job_name, jobQueue=job_queue, jobDefinition=job_definition,
                             containerOverrides=overrides)
    logger.info("Submitted job_name=%s job_id=%s", job_name, resp["jobId"])

    run_id = utc_now_iso().replace(":", "-")
    write_run_record(
        Path("data/batch_runs") / f"psd_attributes_silver_{run_id}.json",
        {
            "run_id": run_id,
            "source": "usda_psd",
            "stage": "bronze_to_silver",
            "table": "silver_psd_attributes",
            "job_name": job_name,
            "job_id": resp["jobId"],
            "job_queue": job_queue,
            "job_definition": job_definition,
            "command": command,
            "publish_mode": args.publish_mode,
            "force_overwrite": args.force_overwrite,
        },
    )


if __name__ == "__main__":
    main()
