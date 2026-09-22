"""Register (a new revision of) the ``leviathan-dev-freshness-poller`` Batch job definition.

A DEDICATED lightweight jobdef for the SILVER-F082 freshness poller (scripts/silver/freshness_poller.py),
mirroring register_notifications_jobdef.py exactly: the DEFAULT command already IS the poller at
0.25 vCPU / 1 GiB, so a scheduler whose ContainerOverrides key is ever dropped/miscased still runs the
right (cheap, read-mostly) task -- never some heavy default like the evidence rebuild.

!! THIS REGISTRAR IS NOT RUNNABLE AS WRITTEN, AND NOTHING RUNS IT. READ THIS BLOCK FIRST. !!
(measured 2026-09-22, pipeline census P7)

  1. `leviathan-dev-freshness-poller` has ZERO revisions in ANY status
     (`aws batch describe-job-definitions --job-definition-name leviathan-dev-freshness-poller`
     -> `jobDefinitions: []`). This file has never been run against the account.
  2. What ACTUALLY runs the poller is the ENABLED EventBridge schedule
     `leviathan-dev-freshness-poller`, which submits to **`leviathan-dev-raw-ingest-runner`**
     (rev 9, WORKER repo, 1 vCPU / 2048 MiB, jobRole `leviathan-dev-batch-job-role`) with
     `ContainerOverrides.Command = ["-m","jobs.observability.freshness_poller_task"]`.
     So the repin that matters is a repin of THAT jobdef, with
     `scripts/ops/repin_jobdef_digest.py`, which copies the live revision verbatim and swaps only
     the image DIGEST -- never the repository.
  3. `_REPO` below names the **EMBEDDER** repository while the module it registers is a WORKER
     module. Under the estate's standing jobdef law ("a jobdef repin KEEPS the repository;
     a worker task on the embedder repo dies at STARTING with CannotPullContainerError") a
     registration from this file would have to be a deliberate EMBEDDER-family decision. The
     embedder Dockerfile does COPY jobs/, src/ and configs/, so it is not absurd -- but it is a
     different image from the one the schedule has been running for weeks, and switching families
     by accident is exactly the failure that law exists to prevent.
  4. `jobRoleArn` names `leviathan-dev-freshness-poller-job-role`, which **DOES NOT EXIST**
     (`aws iam get-role` -> NoSuchEntity). Registering this descriptor today produces a jobdef
     whose jobRole cannot be assumed.
  5. `image` uses the FLOATING `:latest` tag. Every other jobdef in this estate is DIGEST-PINNED,
     which is why "a digest-pinned jobdef makes a push a NO-OP" is a standing law here: a floating
     tag makes the running code unknowable after the fact.

  So: this file is kept as the DESCRIPTOR OF INTENT for a dedicated least-privilege poller jobdef,
  and armed only when (4) is created and (3)/(5) are decided on purpose. Until then the live path
  is raw-ingest-runner + repin_jobdef_digest.py.

Safety posture (the INTENDED posture, once the role exists):
  - jobRoleArn = a DEDICATED freshness-poller job role (freshness_poller.tf.prepared, Track: this lane)
    scoped to s3:ListBucket on the data-lake bucket + cloudwatch:PutMetricData (namespace-conditioned).
    NOT batch-job-role (the internet-facing serving task assumes that; it must not gain PutMetricData
    on the account, and the poller must not gain serving's Bedrock/dynamo grants).
  - !! THAT SCOPE IS NOW ONE PERMISSION SHORT. Since P6 (2026-09-22) the poller ALSO reads the
    DATA axis: for a target whose declared knowledge_date_col is a physical column it opens the
    parquet FOOTER of at most four newest-written canonical objects with RANGED
    `s3:GetObject` calls (measured: ~64 KB per object, 1.6 MB for the whole 53-target estate).
    A ListBucket+PutMetricData-only role returns AccessDenied on every one of those reads, the
    poller counts them all as DataDateUnread{Reason=unreadable}, and the blindness alarm pages --
    fail-closed, but permanently. The dedicated role must carry `s3:GetObject` on
    `arn:aws:s3:::leviathan-dev-shahem-001/silver/*` and `/gold/*` before it is used, or the
    poller must be run with `--no-data-date`. The LIVE path is unaffected:
    `leviathan-dev-batch-job-role` carries `leviathan-dev-s3-data-lake-rw` (verified 2026-09-22).
  - The poller LISTS S3, RANGE-READS parquet footers, and PUTS custom metrics -- no Athena and no
    writes to the data lake. It cannot mutate any table.
  - retryStrategy attempts=2: a Fargate-Spot reclaim retries once; a re-emit of the same lags is
    idempotent (CloudWatch just overwrites the datapoint at that timestamp).

NOTE: the poller is the in-image module jobs/observability/freshness_poller_task.py (D-SG G3-1;
the image copies jobs/ and NOT scripts/, so the old scripts/silver path was never runnable in a
container -- scripts/silver/freshness_poller.py is now a local shim over the same module). The
image must carry that module + src/leviathan/silver/freshness.py + the configs/silver/tables
registry. Register a new revision AFTER that image ships.

    python jobs/utils/register_freshness_poller_jobdef.py            # register (REFUSES today)
    python jobs/utils/register_freshness_poller_jobdef.py --dry-run  # print + list the refusals
"""
from __future__ import annotations

import argparse
import json

import boto3

_ACCOUNT = "668891723125"
_REGION = "us-east-1"
_REPO = "leviathan-dev-leviathan-embedder"   # same image (poller + registry configs baked)
_NAME = "leviathan-dev-freshness-poller"
_BUCKET = "leviathan-dev-shahem-001"

_CONTAINER = {
    "image": f"{_ACCOUNT}.dkr.ecr.{_REGION}.amazonaws.com/{_REPO}:latest",
    "command": ["-m", "jobs.observability.freshness_poller_task"],  # the DEFAULT command IS the poller (in-image module; scripts/ is not baked)
    "jobRoleArn": f"arn:aws:iam::{_ACCOUNT}:role/leviathan-dev-freshness-poller-job-role",  # ListBucket + PutMetricData only
    "executionRoleArn": f"arn:aws:iam::{_ACCOUNT}:role/leviathan-dev-batch-execution-role",
    "resourceRequirements": [
        {"type": "VCPU", "value": "0.25"},        # a few list_objects_v2 pages + put_metric_data
        {"type": "MEMORY", "value": "1024"},
    ],
    "networkConfiguration": {"assignPublicIp": "ENABLED"},
    "fargatePlatformConfiguration": {"platformVersion": "LATEST"},
    "environment": [
        {"name": "AWS_REGION", "value": _REGION},
        {"name": "LEVIATHAN_BUCKET", "value": _BUCKET},
        {"name": "LEVIATHAN_ENV", "value": "dev"},
        {"name": "PYTHONIOENCODING", "value": "utf-8"},
    ],
}


def preflight(container: dict, *, iam=None, allow_floating_tag: bool = False) -> list[str]:
    """Every reason this descriptor must NOT be registered, as a list. Empty list == go.

    PURE ENOUGH TO TEST: ``iam`` is injected, and with ``iam=None`` only the offline checks run.

    WHY A FENCE AND NOT A PARAGRAPH. The docstring above has recorded since 2026-09-22 that this
    file's job role does not exist and its image is a floating tag. A note that the next operator
    must remember to read is not a fix; it is the shape of every silent drift in this estate's
    history. A registrar that would produce a jobdef which cannot pull its image or assume its role
    should REFUSE, at the moment of the call, with the reason printed -- and it should refuse on
    HEAD today, which is what makes the check a pin rather than a decoration."""
    problems: list[str] = []
    image = container.get("image", "")
    if "@sha256:" not in image and not allow_floating_tag:
        problems.append(
            f"image {image!r} is not DIGEST-PINNED. Every jobdef in this estate is pinned to a "
            "digest -- 'a digest-pinned jobdef makes a push a NO-OP' is a standing law here, and a "
            "floating tag makes the code that actually ran unknowable after the fact. Pass "
            "--image-digest sha256:<64 hex> (read it from `aws ecr describe-images`, never "
            "inferred from a tag), or --allow-floating-tag to sign for it deliberately.")
    role = container.get("jobRoleArn", "")
    role_name = role.rsplit("/", 1)[-1]
    if iam is not None and role_name:
        try:
            iam.get_role(RoleName=role_name)
        except Exception as e:  # noqa: BLE001 -- NoSuchEntity is the case this exists for
            problems.append(
                f"jobRoleArn names {role_name!r}, which this account does not have "
                f"({type(e).__name__}). A jobdef whose job role cannot be assumed fails at RUNTIME, "
                f"in a scheduled fire, with no plan-time signal. Create the role (it needs "
                f"s3:ListBucket AND s3:GetObject on the data-lake bucket plus "
                f"cloudwatch:PutMetricData -- see the GetObject note in this module's docstring), "
                f"or pass --job-role with one that exists.")
    return problems


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Register the leviathan-dev-freshness-poller job definition.")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--job-role", default=None, help="override the job role ARN (default: the dedicated role)")
    ap.add_argument("--image-digest", default=None,
                    help="sha256:<64 hex> -- pin the image to this digest instead of the :latest tag")
    ap.add_argument("--allow-floating-tag", action="store_true",
                    help="sign for an unpinned :latest image deliberately (refused by default)")
    args = ap.parse_args(argv)

    container = dict(_CONTAINER)
    if args.job_role:
        container["jobRoleArn"] = args.job_role
    if args.image_digest:
        repo = container["image"].split("@")[0].rsplit(":", 1)[0]
        container["image"] = f"{repo}@{args.image_digest}"

    payload = dict(
        jobDefinitionName=_NAME,
        type="container",
        platformCapabilities=["FARGATE"],
        containerProperties=container,
        retryStrategy={"attempts": 2},            # Spot-reclaim resilience; re-emit is idempotent
    )

    if args.dry_run:
        print(json.dumps(payload, indent=2))
        for problem in preflight(container, iam=None,
                                 allow_floating_tag=args.allow_floating_tag):
            print(f"[preflight] REFUSE: {problem}")
        return 0

    problems = preflight(container, iam=boto3.client("iam"),
                         allow_floating_tag=args.allow_floating_tag)
    if problems:
        print(f"REFUSED: {_NAME} was NOT registered -- {len(problems)} precondition(s) unmet:")
        for problem in problems:
            print(f"  - {problem}")
        return 2

    batch = boto3.client("batch", region_name=_REGION)
    resp = batch.register_job_definition(**payload)
    print(f"registered {resp['jobDefinitionName']} revision {resp['revision']} "
          f"({resp['jobDefinitionArn']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
