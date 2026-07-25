"""Submit the T2B pattern-records ledger sweep (daily) / backfill grid as an AWS Batch Fargate task.

The jobdef is TERRAFORM-MANAGED (infra/terraform/modules/batch/main.tf
``aws_batch_job_definition.pattern_records_sweep``, wired in envs/dev/main.tf and count-gated on the
pinned image digest), so this wrapper NEVER registers a revision of its own -- two owners of one
jobdef means the next ``terraform apply`` silently reverts whatever the wrapper registered, and the
sweep then runs on an image nobody content-checked. It RESOLVES the live jobdef instead and REFUSES
to submit unless the active revision matches the pin below (the mirror image of the BF-W1 lesson:
there the danger was reusing a stale revision, here it is submitting onto one).

Runs on a DEDICATED scoped jobdef + role (the P3 morning-brief pattern, plan sec 7 step 5): the
EventBridge schedule ships DISABLED, ONE manual day-0 run happens through THIS wrapper, and the
schedule is ENABLED only after that run is reviewed. The sweep is an ENGINE REPLAY over the pg
mirror, so the jobdef carries the full serving pg env (GRAPHRAG_NUMBERS_BACKEND=pg + EVIDENCE_PG_DSN
from Secrets Manager); without it the quantify seam is DEAD and every fired verdict is an ARTIFACT
(the 2026-07-23 phantom-regression lesson). The task asserts pg-only at startup and refuses to run
otherwise -- and ``check_jobdef_contract`` below fails BEFORE submit for the same reason, because a
pg-dead sweep would not just fail, it would write wrong verdicts into a ledger that is never
recomputed (plan non-goal 6).

Two modes, ONE jobdef:
  * DAILY sweep -- asof = today UTC. --asof is deliberately OMITTED from the command (the task
    defaults to today and REFUSES a non-backfill sweep at a past asof; a pinned date would rot).
  * BACKFILL GRID -- the ONE-TIME bounded weekly grid (plan sec 3.4 / D6, rollout step 4). Runs at a
    past-asof grid with provenance=backfill_grid. Eligibility is NOT a flag: the task records a
    backfill verdict only for surfaces whose EVERY leg reads a RELEASE-DATE-VINTAGED table
    (esr_compact / wasde / psd). Legs on the period LATEST-ONLY tables (silver_noaa_oni,
    gold_weather_z) are EXCLUDED because a past-asof read returns TODAY's restated value wearing a
    past period label (plan sec 3.1 / F2) -- so --kinds cannot be used to sneak them in.

Usage:
    python jobs/submit/submit_batch_pattern_records_sweep.py --dry-run              # daily, plan only
    python jobs/submit/submit_batch_pattern_records_sweep.py --backfill --dry-run   # the weekly grid
    python jobs/submit/submit_batch_pattern_records_sweep.py --publish-mode shadow  # day-0 rehearsal
    python jobs/submit/submit_batch_pattern_records_sweep.py --publish-mode canonical --i-understand-canonical
"""
from __future__ import annotations

import argparse
import logging
import sys
from typing import Optional

import boto3

from leviathan.common.config import load_env
from leviathan.common.logging import get_logger

logger = get_logger("submit_batch_pattern_records_sweep")

# Terraform-managed jobdef NAME (modules/batch: "${project}-${environment}-pattern-records-sweep").
# A wrong name dies at submit time with ClientException -- AFTER any approval ceremony -- so it is
# pinned here and pinned again in the unit test (the BF-W2 D1 lesson).
_JOB_DEF_NAME = "leviathan-dev-pattern-records-sweep"
_JOB_QUEUE = "leviathan-dev-queue"
_TASK_PATH = "jobs/batch/pattern_records_sweep_task.py"

# Pinned by DIGEST -- CONTENT-CHECK the sweep entrypoint before pinning (docker run + inspect.getsource
# markers for pattern_records_sweep_task.sweep / apply_write_guard), and read the digest from
# `aws ecr describe-images`, never a build log and never :latest (the d9b2e10e stale-:latest lesson).
# This value MUST equal terraform var.pattern_records_image_digest -- the wrapper refuses to submit
# onto a jobdef whose active revision carries a different image, so a half-applied re-pin is caught
# before the job runs rather than after it has written verdicts.
# STATUS: PLACEHOLDER -- filled at rollout step 3, together with the terraform variable.
_IMAGE_DIGEST_PLACEHOLDER = "sha256:REPLACE_WITH_CONTENT_CHECKED_DIGEST"
_ECR_IMAGE = (
    "668891723125.dkr.ecr.us-east-1.amazonaws.com/leviathan-dev-leviathan-embedder"
    f"@{_IMAGE_DIGEST_PLACEHOLDER}"
)

_REGION = "us-east-1"
# Per-attempt ceilings. The daily sweep matches the jobdef default (3 h, ~600 pg probes); the
# one-time grid replays ~52 asofs per year of depth, so it gets its own wider ceiling at SUBMIT time
# rather than inflating the daily jobdef's timeout.
_DAILY_TIMEOUT_S = 10800
_BACKFILL_TIMEOUT_S = 86400


def build_command(
    *,
    asof: Optional[str] = None,
    backfill: bool = False,
    backfill_years: Optional[float] = None,
    kinds: Optional[str] = None,
    publish_mode: str = "dry-run",
    shadow_prefix: Optional[str] = None,
    build_only: bool = False,
) -> list:
    """Pure: the containerOverrides command for a sweep submission. No AWS, no env.

    --asof is emitted ONLY when the caller pins one. A daily sweep leaves it out so the task stamps
    asof = today UTC at run time; a pinned past date on a non-backfill run is refused by the task
    itself (a daily_sweep row must be written at its OWN asof, plan sec 3.1 / F4)."""
    cmd = [_TASK_PATH]
    if asof:
        cmd += ["--asof", asof]
    cmd += ["--publish-mode", publish_mode]
    if kinds:
        cmd += ["--kinds", kinds]
    if shadow_prefix:
        cmd += ["--shadow-prefix", shadow_prefix]
    if backfill:
        cmd.append("--backfill")
        if backfill_years is not None:
            cmd += ["--backfill-years", str(backfill_years)]
    if build_only:
        cmd.append("--dry-run")  # the TASK's build-records-and-stop flag (writes nothing at all)
    return cmd


def check_jobdef_contract(container_properties: dict) -> list:
    """Pure: the pre-submit contract on the live jobdef. Returns a list of problems (empty = OK).

    Every item is a way the sweep could run and produce a WRONG-but-plausible ledger rather than an
    honest failure:
      * a different image  -> code nobody content-checked wrote the verdicts;
      * no pg backend / no DSN -> the quantify seam is dead, every verdict is fired=false (the
        phantom-regression class), and the ledger records that lie permanently;
      * no engine_version stamp -> the write-guard's CODE axis collapses to "unknown", so a re-run
        under bumped code silently overwrites a past verdict instead of being refused (plan F1);
      * the shared batch-job-role -> the serving-reused identity would gain ledger writes."""
    problems = []
    image = container_properties.get("image")
    if image != _ECR_IMAGE:
        problems.append(f"image {image!r} != pinned digest {_ECR_IMAGE!r}")
    env = {e.get("name"): e.get("value") for e in container_properties.get("environment", [])}
    if env.get("GRAPHRAG_NUMBERS_BACKEND") != "pg":
        problems.append("GRAPHRAG_NUMBERS_BACKEND != 'pg' (the quantify seam would be DEAD)")
    if not env.get("GRAPHRAG_ENGINE_VERSION"):
        problems.append("GRAPHRAG_ENGINE_VERSION unset (the write-guard code axis would be 'unknown')")
    secrets = {s.get("name") for s in container_properties.get("secrets", [])}
    if "EVIDENCE_PG_DSN" not in secrets:
        problems.append("EVIDENCE_PG_DSN secret not mounted (pg-only sweep cannot run)")
    role = container_properties.get("jobRoleArn") or ""
    if role.endswith("/leviathan-dev-batch-job-role"):
        problems.append("jobRoleArn is the SHARED batch-job-role (serving reuses it); expected the "
                        "dedicated leviathan-dev-pattern-records-job-role")
    return problems


def resolve_job_definition(batch) -> str:
    """Resolve the terraform-managed jobdef and verify the pre-submit contract. Never registers."""
    resp = batch.describe_job_definitions(jobDefinitionName=_JOB_DEF_NAME, status="ACTIVE")
    active = sorted(resp.get("jobDefinitions", []), key=lambda d: d["revision"])
    if not active:
        raise SystemExit(
            f"job definition {_JOB_DEF_NAME} is not registered. It is terraform-managed: pin "
            "var.pattern_records_image_digest and apply "
            "-target=module.batch.aws_batch_job_definition.pattern_records_sweep. "
            "This wrapper deliberately does NOT register jobdefs.")
    live = active[-1]
    problems = check_jobdef_contract(live.get("containerProperties", {}))
    if problems:
        raise SystemExit(f"{_JOB_DEF_NAME} revision {live['revision']} fails the pre-submit contract: "
                         + "; ".join(problems))
    logger.info("Using terraform-managed job definition: %s", live["jobDefinitionArn"])
    return live["jobDefinitionArn"]


def main() -> None:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                        format="%(asctime)s %(levelname)s %(name)s -- %(message)s")
    load_env()
    parser = argparse.ArgumentParser(description="Submit the pattern-records sweep Batch job")
    parser.add_argument("--aws-region", default=_REGION, dest="aws_region")
    parser.add_argument("--asof", default=None,
                        help="pin the sweep as-of / the backfill grid END (YYYY-MM-DD). Omit for a "
                             "daily sweep: the task stamps today UTC and refuses a past-asof daily run.")
    parser.add_argument("--backfill", action="store_true",
                        help="run the ONE-TIME bounded weekly grid (provenance=backfill_grid; only "
                             "surfaces whose every leg reads a release-date-vintaged table)")
    parser.add_argument("--backfill-years", type=float, default=None, dest="backfill_years",
                        help="grid depth in years (~3-5; the task default is 3)")
    parser.add_argument("--kinds", default=None,
                        help="comma list of record kinds (v1: cascade,pace,chain). Does NOT widen "
                             "backfill eligibility -- that fence is per-surface, not per-kind.")
    parser.add_argument("--publish-mode", default="dry-run", dest="publish_mode",
                        choices=["dry-run", "shadow", "canonical"],
                        help="dry-run (default) | shadow | canonical (needs --i-understand-canonical)")
    parser.add_argument("--shadow-prefix", default=None, dest="shadow_prefix")
    parser.add_argument("--build-only", action="store_true",
                        help="pass the TASK's --dry-run: build the records, print counts, write nothing")
    parser.add_argument("--timeout-seconds", type=int, default=None, dest="timeout_seconds",
                        help="per-attempt ceiling override (default 3 h daily / 24 h backfill)")
    parser.add_argument("--i-understand-canonical", action="store_true", dest="ack_canonical",
                        help="required for --publish-mode canonical: a ledger row is a PERMANENT "
                             "record of the engine's verdict at T and is never recomputed")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the submission and exit; submits NOTHING (wrapper-level)")
    args = parser.parse_args()

    if args.publish_mode == "canonical" and not args.ack_canonical:
        raise SystemExit("--publish-mode canonical requires --i-understand-canonical: it appends "
                         "immutable rows to gold_pattern_records (the write-guard then REFUSES any "
                         "later re-run under a different engine_version). Rehearse with "
                         "--publish-mode shadow first.")

    command = build_command(asof=args.asof, backfill=args.backfill, backfill_years=args.backfill_years,
                            kinds=args.kinds, publish_mode=args.publish_mode,
                            shadow_prefix=args.shadow_prefix, build_only=args.build_only)
    timeout_s = args.timeout_seconds or (_BACKFILL_TIMEOUT_S if args.backfill else _DAILY_TIMEOUT_S)
    job_name = f"pattern-records-{'backfill' if args.backfill else 'daily'}-{args.asof or 'today'}"

    if args.dry_run:
        logger.info("[dry-run] would submit %s jobName=%s command=%s timeout=%ds",
                    _JOB_DEF_NAME, job_name, command, timeout_s)
        return

    if _IMAGE_DIGEST_PLACEHOLDER in _ECR_IMAGE:
        raise SystemExit("_ECR_IMAGE is still the placeholder digest: content-check the image "
                         "(rollout step 3) and pin the same digest here AND in "
                         "var.pattern_records_image_digest before submitting.")

    batch = boto3.client("batch", region_name=args.aws_region)
    job_def_arn = resolve_job_definition(batch)
    resp = batch.submit_job(
        jobName=job_name,
        jobQueue=_JOB_QUEUE,
        jobDefinition=job_def_arn,
        containerOverrides={"command": command},
        timeout={"attemptDurationSeconds": timeout_s},
    )
    logger.info("Submitted: jobId=%s command=%s", resp["jobId"], command)
    logger.info("Monitor: aws batch describe-jobs --jobs %s --region %s", resp["jobId"], args.aws_region)


if __name__ == "__main__":
    main()
