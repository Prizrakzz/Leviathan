"""Register (a new revision of) the ``leviathan-dev-pg-numbers-loader`` Batch job definition.

THE JOB DEFINITION THAT HAS NEVER LOADED ANYTHING, MADE REAL.

WHAT WAS MEASURED (2026-09-22 refuter, read-only, and it is the reason this file exists). The
estate has one jobdef named for the pg mirror load, ``leviathan-dev-pg-numbers-loader``, and it has
NEVER PERFORMED ONE. Both its ACTIVE revisions carry the placeholder command
``['-c', "print('override me')"]``; its job role is ``leviathan-dev-silver-publisher`` while every
real load ran under ``leviathan-dev-batch-job-role``; it is 2 vCPU / 8 GB; and its only two
CloudWatch streams are dated 2026-07-31. Every real load in the estate's history went through
``leviathan-dev-evidence-build`` instead, submitted by ``jobs/submit/submit_batch_load_numbers_pg.py``
with a container override -- the 2026-09-10 full load (``DONE: 16964478 rows``, 13:22:02..13:27:57,
under six minutes) and the 2026-09-17 single-table MPOB reload (``DONE: 117 rows``) are both on that
stream.

WHY THAT MATTERS RIGHT NOW. Census blocker B1: nothing in the account SCHEDULES the mirror load (30
schedules, not one names it), so the serve path is as fresh as the last time somebody remembered --
and ``leviathan-dev-serving:133`` runs ``GRAPHRAG_NUMBERS_BACKEND=pg``. The permanent fix (P1) is a
daily EventBridge Scheduler fire, and a schedule needs a job definition that carries its own real
command: a schedule that passes a ContainerOverrides command is a second place the command lives,
which is the drift class the freshness poller's inline-python block cost this estate twice. So the
jobdef gets the command, and ``infra/terraform/envs/dev/schedule_pg_numbers_load.tf`` names NO
override at all.

    python jobs/utils/register_pg_numbers_loader_jobdef.py --dry-run   # print, don't register
    python jobs/utils/register_pg_numbers_loader_jobdef.py             # register a new revision

Registering is the ORCHESTRATOR's step; applying the terraform is the OWNER's hand.
"""
from __future__ import annotations

import argparse
import json

import boto3

_ACCOUNT = "668891723125"
_REGION = "us-east-1"
_NAME = "leviathan-dev-pg-numbers-loader"
_BUCKET = "leviathan-dev-shahem-001"

# ---------------------------------------------------------------------------------------------
# THE IMAGE FAMILY, AND THE LAW THAT DECIDES IT.
#
# "A jobdef REPIN keeps the repository" -- measured 2026-09-09: a WORKER digest registered against a
# jobdef whose family is the EMBEDDER repo dies at STARTING with CannotPullContainerError, and the
# reverse is just as fatal. This jobdef's family is the WORKER repo: revisions 1 and 2 are both
# ``leviathan-dev-leviathan-worker@sha256:...`` (read 2026-09-22; rev 2 is 46f55987, the current
# 20260916-seams worker).
#
# THAT IS NOT THE SAME REPO ``leviathan-dev-evidence-build`` USES, and the difference is deliberate
# rather than an oversight. evidence-build is on ``leviathan-dev-leviathan-embedder`` (torch +
# bge-m3, ~2.5 GB) because it EMBEDS; the mirror load does not embed anything. What it needs is
# pyarrow, psycopg and src/ + jobs/ + configs/, and the worker image has all of them: its Dockerfile
# installs ``.[batch,biweekly,pg]`` and COPYs src/, jobs/, configs/ and sql/. The proof it RUNS there
# is not an argument but an existing production path -- ``jobs/audit/silver_rebuild_gate.py``'s
# Branch-A ``stage_pg_reload`` calls ``load_pg_numbers.load_table`` IN PROCESS on every gate run, and
# the silver gate runs on a worker-family image.
#
# So the family is WORKER, and ``_assert_repository_family`` below refuses to register if the live
# revision says otherwise -- because the day someone repins this from the wrong digest file, the
# failure is a job stuck at STARTING with no log stream, which is the most expensive shape of error
# this estate has.
# ---------------------------------------------------------------------------------------------
_REPO = "leviathan-dev-leviathan-worker"

# THE REAL COMMAND. No ``--tables``, which IS the P1 set (load_pg_numbers' argparse default is
# ``",".join(P1_TABLES)``) -- all 39 mirrored tables, the same thing the 2026-09-10 full load ran.
# Spelled as a bare script path because the worker image's ENTRYPOINT is ``["python"]`` (the live
# placeholder ``['-c', ...]`` is itself the proof) and WORKDIR is /app, where jobs/ is COPYed.
#
# NOT A ``Ref::`` PARAMETER. The evidence-build jobdef parameterises its command because a dozen
# different submissions drive it; this one has exactly one caller -- a daily schedule -- and a
# parameter with a default is a second place the truth lives. A caller that needs a subset still has
# ``jobs/submit/submit_batch_load_numbers_pg.py --tables``, which overrides the command wholesale.
_COMMAND = ["jobs/utils/load_pg_numbers.py"]

# THE ROLE THE REAL LOADS ACTUALLY RAN UNDER, and not the one this jobdef has been carrying.
# ``leviathan-dev-batch-job-role`` is what ``describe_jobs`` returns for both 2026 loads; it already
# holds the glue:GetTable + s3:GetObject/ListBucket the loader needs (it reads the Glue catalog for
# schema/location and the canonical parquet straight from S3 -- no Athena on this path).
# ``leviathan-dev-silver-publisher``, the role on revisions 1-2, is the PUBLISHER role: a load has no
# business holding publish authority, and the refuter found it there only because nothing had ever
# exercised it.
_JOB_ROLE = "leviathan-dev-batch-job-role"
_EXECUTION_ROLE = "leviathan-dev-batch-execution-role"

# The DSN the loader exits 1 without ("EVIDENCE_PG_DSN not set (run in-VPC via the Batch submit)").
# Resolved by NAME at registration so the secret's random suffix stays out of this (public) repo.
_PG_DSN_SECRET_NAME = "leviathan/dev/evidence-pg-dsn"

# 4 vCPU / 16 GB. The 2026-09-10 full load -- 16,964,478 rows across all 39 tables -- finished in
# 5m55s on evidence-build's 16 vCPU / 120 GB, and the loader is not CPU-parallel: it scans one
# pyarrow dataset at a time and COPYs row by row, so the binding resource is the per-table batch
# buffer, not cores. 2 vCPU / 8 GB (the placeholder revision's size) is the shape that has never been
# exercised on a real load and is NOT the one to arm a schedule on; 16/120 is evidence-build's
# envelope sized for rebuild-slices holding a full prop routing in memory, which this job never does.
# 4/16 is the measured middle, and Fargate only admits 16384 MB at 4 vCPU in the 8-30 GB band.
_VCPU = "4"
_MEMORY = "16384"

# 7,200 s. The real full load takes about six minutes, so this is a 60x margin -- deliberately, because
# the number this timeout must survive is not the happy path but a cold RDS, a retried table and a
# mirror that has grown. An attemptDurationSeconds that is merely "generous against today" is how a
# load starts failing the week a table doubles. (The live placeholder revision already carries 7200;
# keeping it means the schedule's first fire changes exactly one thing at a time.)
_TIMEOUT_SECONDS = 7200

# ---------------------------------------------------------------------------------------------
# RETRY: THE PRE-START CLASS ONLY, AND THE LAST RULE IS A TERMINAL EXIT.
#
# The failure this exists for was measured on 2026-09-21 on the futures_eod chain: a Batch job with
# ``StatusReason: "Rate limit exceeded while preparing network interface to be attached to instance"``
# and ``ExitCode: None`` -- the container NEVER RAN. The state machine's own ClassifyBatchCauseGate
# routes a missing ExitCode to an infra-failure notification precisely because that class is not the
# job's fault and is safe to repeat.
#
# WHY IT MUST STAY THIS NARROW. This job DROPs and re-CREATEs every mirrored table. A retry of a job
# that actually STARTED would re-run that write path, and the T2b doctrine excludes publisher-shaped
# jobs from blanket retries for exactly that reason. The three RETRY rules all match statusReasons a
# container that never started produces; the fourth rule -- ``onStatusReason "*" -> EXIT`` -- makes
# EVERY other failure, including every non-zero exit code, terminal on the FIRST attempt. Batch
# evaluates evaluateOnExit rules in order and takes the first match, so the terminal rule must stay
# LAST, and nothing may be inserted after it.
#
# (The pg side is safe under a repeat in any case: load_table does DROP+CREATE+COPY inside ONE
# transaction and pg DDL is transactional, so a killed attempt leaves readers on the old rows. The
# narrowness is not about corruption, it is about not normalising a retry on a write path.)
# ---------------------------------------------------------------------------------------------
_RETRY_STRATEGY = {
    "attempts": 2,
    "evaluateOnExit": [
        {"onStatusReason": "CannotPullContainer*", "action": "RETRY"},
        {"onStatusReason": "ResourceInitializationError*", "action": "RETRY"},
        {"onStatusReason": "Rate limit exceeded*", "action": "RETRY"},
        {"onStatusReason": "*", "action": "EXIT"},
    ],
}

_CONTAINER = {
    # Replaced at registration -- see _resolve_image. NEVER left as a mutable tag: a tag re-resolves
    # at every pull and defeats provenance.
    "image": f"{_ACCOUNT}.dkr.ecr.{_REGION}.amazonaws.com/{_REPO}:latest",
    "command": _COMMAND,
    "jobRoleArn": f"arn:aws:iam::{_ACCOUNT}:role/{_JOB_ROLE}",
    "executionRoleArn": f"arn:aws:iam::{_ACCOUNT}:role/{_EXECUTION_ROLE}",
    "resourceRequirements": [
        {"type": "VCPU", "value": _VCPU},
        {"type": "MEMORY", "value": _MEMORY},
    ],
    "networkConfiguration": {"assignPublicIp": "ENABLED"},
    "fargatePlatformConfiguration": {"platformVersion": "LATEST"},
    "environment": [
        {"name": "AWS_REGION", "value": _REGION},
        {"name": "LEVIATHAN_BUCKET", "value": _BUCKET},
        {"name": "LEVIATHAN_ENV", "value": "dev"},
        # 2026-09-22 review MAJOR-1: leviathan-dev-batch-failed-scheduled -- the ONLY failure metric filter
        # whose alarm carries an SNS action -- matches MANAGED_BY_AWS in the container environment (or a
        # three-name jobName allowlist this job is not on). Without this marker a nightly load that fails
        # every night restores the census B1 state with nobody told. The estate applies the same marker
        # to every scheduled Batch job (infra/terraform/envs/dev/main.tf, the MANAGED_BY_AWS convention).
        {"name": "MANAGED_BY_AWS", "value": "scheduler"},
        # The serving backend this mirror EXISTS for. Carried on the live revision too, so this is a
        # preserved fact rather than a new one.
        {"name": "GRAPHRAG_NUMBERS_BACKEND", "value": "pg"},
        {"name": "PYTHONPATH", "value": "/app/src"},
        # Unbuffered so the per-table "loaded N rows in Xs" lines reach awslogs LIVE rather than at
        # exit -- the mute-rebuild class. A load whose progress is invisible until it ends cannot be
        # watched end to end, and the first scheduled fire must be (threat model T4).
        {"name": "PYTHONUNBUFFERED", "value": "1"},
        # cp1252 console rule: the estate's logs are read on a Windows terminal.
        {"name": "PYTHONIOENCODING", "value": "utf-8"},
    ],
}


def _assert_repository_family(batch) -> str | None:
    """Refuse to register if the LIVE revision's image is not in the repository this file pins.

    THE FAILURE THIS PREVENTS, measured 2026-09-09: a jobdef repinned to a digest from the WRONG ECR
    repository dies at STARTING with CannotPullContainerError -- no log stream, no exit code, nothing
    to read. ``graphrag-eval`` is the EMBEDDER family and the silver six are the WORKER family, and
    the only way to know which is to read the live revision before choosing the digest file.

    Returns the live image string (for the dry-run print), or None when the jobdef has no ACTIVE
    revision yet -- a first registration is legal and defines the family."""
    resp = batch.describe_job_definitions(jobDefinitionName=_NAME, status="ACTIVE")
    revisions = sorted(resp.get("jobDefinitions", []), key=lambda d: d.get("revision", 0))
    if not revisions:
        return None
    live = revisions[-1]["containerProperties"].get("image", "")
    repo = live.split("/")[-1].split("@")[0].split(":")[0]
    if repo != _REPO:
        raise SystemExit(
            f"REFUSING to register: {_NAME} revision {revisions[-1].get('revision')} is on "
            f"repository {repo!r} but this registrar pins {_REPO!r}. A jobdef repin KEEPS its "
            f"repository -- a cross-family digest dies at STARTING with CannotPullContainerError "
            f"and no log stream. Read the live image and fix _REPO (or the digest file) first.")
    return live


def _newest_pushed(ecr) -> tuple[str, list[str], str]:
    """(digest, tags, pushed_at) of the most recently pushed image in the repository."""
    newest = None
    for page in ecr.get_paginator("describe_images").paginate(repositoryName=_REPO):
        for d in page.get("imageDetails", []):
            if newest is None or d["imagePushedAt"] > newest["imagePushedAt"]:
                newest = d
    if newest is None:
        raise SystemExit(f"repository {_REPO} holds no images")
    return newest["imageDigest"], newest.get("imageTags", []), str(newest["imagePushedAt"])


def _resolve_image(ecr, live_image: str | None, image_tag: str | None) -> tuple[str, list[str]]:
    """Which digest this revision pins, and the warnings the caller must read before registering.

    THE DEFAULT IS "DO NOT MOVE THE IMAGE", AND THAT IS NOT CONSERVATISM, IT IS A MEASUREMENT.
    ``register_evidence_jobdef.py`` resolves ``:latest`` at registration, and copying that idiom here
    would have been a silent ROLLBACK: read read-only on 2026-09-22, ``leviathan-dev-leviathan-worker``'s
    ``latest`` tag points at sha256:91104375 pushed 2026-08-27 (also tagged 20260827T144148), while
    the repository's newest image is sha256:46f55987 / 20260916-seams pushed 2026-09-16 -- the digest
    the live revision of THIS jobdef already carries and the one thirteen verified repins put across
    the estate. A registrar that took ``:latest`` would have quietly pinned a 26-day-old, five-builds-
    behind worker and called it a repin.

    So: by default this registrar reuses the digest the LIVE revision already carries, and moves
    exactly the things this change is about -- the command, the job role, the size, the timeout and
    the retry rules. Moving the image is a SEPARATE decision that needs ``--image-tag <tag>`` spelled
    out, and whatever is chosen, the caller is told how it compares to the newest pushed image."""
    warnings: list[str] = []
    newest_digest, newest_tags, newest_pushed = _newest_pushed(ecr)
    if image_tag:
        digest = ecr.describe_images(
            repositoryName=_REPO, imageIds=[{"imageTag": image_tag}]
        )["imageDetails"][0]["imageDigest"]
        source = f"--image-tag {image_tag}"
    elif live_image and "@" in live_image:
        digest = live_image.split("@", 1)[1]
        source = f"the live revision of {_NAME} (image UNCHANGED by this registration)"
    else:
        digest = newest_digest
        source = f"the newest pushed image {newest_tags} (no digest-pinned live revision to preserve)"
    warnings.append(f"image digest {digest} from {source}")
    if digest != newest_digest:
        warnings.append(
            f"NOTE: this is NOT the repository's newest image. Newest is {newest_digest} "
            f"{newest_tags} pushed {newest_pushed}. That is legal (a deliberate pin or rollback) but "
            f"it must be a CHOICE -- re-run with --image-tag to move it.")
    return digest, warnings


def main() -> None:
    ap = argparse.ArgumentParser(
        description=f"Register the {_NAME} job definition with its REAL load command.")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--image-tag", default=None,
                    help="move the image to this ECR tag (default: keep the live revision's digest). "
                         "NEVER pass 'latest' without reading _resolve_image's measurement first.")
    args = ap.parse_args()

    batch = boto3.client("batch", region_name=_REGION)
    live_image = _assert_repository_family(batch)

    container = dict(_CONTAINER)
    ecr = boto3.client("ecr", region_name=_REGION)
    digest, image_notes = _resolve_image(ecr, live_image, args.image_tag)
    for note in image_notes:
        print(f"# {note}")
    container["image"] = f"{_ACCOUNT}.dkr.ecr.{_REGION}.amazonaws.com/{_REPO}@{digest}"

    sm = boto3.client("secretsmanager", region_name=_REGION)
    container["secrets"] = [
        {"name": "EVIDENCE_PG_DSN", "valueFrom": sm.describe_secret(SecretId=_PG_DSN_SECRET_NAME)["ARN"]},
    ]

    payload = dict(
        jobDefinitionName=_NAME,
        type="container",
        platformCapabilities=["FARGATE"],
        containerProperties=container,
        timeout={"attemptDurationSeconds": _TIMEOUT_SECONDS},
        retryStrategy=_RETRY_STRATEGY,
    )

    if args.dry_run:
        masked = [{"name": s["name"], "valueFrom": "[resolved by name]"} for s in container["secrets"]]
        print(f"# live image: {live_image or '(no ACTIVE revision yet -- first registration)'}")
        print(json.dumps({**payload, "containerProperties": {**container, "secrets": masked}}, indent=2))
        return

    resp = batch.register_job_definition(**payload)
    print(f"registered {resp['jobDefinitionName']} revision {resp['revision']} "
          f"({resp['jobDefinitionArn']})")
    print(f"image pinned to {container['image']}")


if __name__ == "__main__":
    main()
