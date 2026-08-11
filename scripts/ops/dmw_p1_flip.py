"""D-MW P1 LAYER C -- the one-shot flip: serving's rerank lane, Bedrock -> native Cohere.

    python scripts/ops/dmw_p1_flip.py            # DRY RUN: prints the diff, mutates NOTHING
    python scripts/ops/dmw_p1_flip.py --run      # registers + deploys

--run IS MANDATORY for any mutation, and any other argument is rejected outright. This file
mutates production, so an accidental invocation -- a tab-completion, a `--help` that a script
ignoring argv would have swallowed, a stray shell history entry -- must be inert by
construction. (Written after exactly that: this script was invoked with `--help` during a
compile check and, argv being ignored at the time, began registering a revision. A truncated
pipe stopped it before the API call. Design, not luck, is what should stop it.)

Does exactly two prod mutations, in the plan's hard order, and verifies between them:
  1. register a new leviathan-dev-serving revision FROM THE DEPLOYED one (never the family's
     latest-ACTIVE -- that is the poisoning trap D-MW-4 records), with GRAPHRAG_RERANK_BACKEND
     flipped to "cohere" and the COHERE_API_KEY secret mounted. This delegates to
     scripts/ops/register_serving_taskdef.py so the shipped, diff-reviewed patch logic is the
     only thing that ever builds a taskdef.
  2. update-service --force-new-deployment onto that exact revision ARN.

Between them it re-reads the registered revision and ASSERTS the flip is actually in it, so a
partial or mis-patched registration can never reach update-service. Nothing here retries, and
nothing here accepts a rollout -- acceptance is the ECS-ROLLOUT-STATE-LIES check the caller runs
afterwards (new task ARN + fresh boot log), which this script prints as its last word.

Rollback is one env value: re-run register_serving_taskdef.py with
--set-env GRAPHRAG_RERANK_BACKEND=bedrock and deploy that revision.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import boto3

CLUSTER = "leviathan-dev-serving"
SERVICE = "leviathan-dev-serving"
FAMILY = "leviathan-dev-serving"
CONTAINER = "serving"
REGION = "us-east-1"
SECRET_ARN = "arn:aws:secretsmanager:us-east-1:668891723125:secret:leviathan-dev-cohere-api-key"
# THE IMAGE IS HALF THE FLIP. The env value GRAPHRAG_RERANK_BACKEND=cohere is only meaningful to
# code that has a cohere branch; the shipped-before-P1 image has none, and its dispatcher falls
# through EVERY unrecognised backend to the CPU cross-encoder -- so old image + new env is a
# silent ~100 s/walk regression, not a flip. Rev 92 was registered without this and is the reason
# the constant exists. Digest of the P1 image (tag 20260811T113923, commit 06b8ebd1).
IMAGE_DIGEST = "sha256:440ad45c72c04a8a09b37741cc5f5db48d4be731ef7920a762d027da3fb6751c"
IMAGE_COMMIT = "06b8ebd1"

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "scripts" / "ops" / "register_serving_taskdef.py"


def main(argv: list[str]) -> int:
    # Interactive-terminal output through a pipe is block-buffered; a truncating reader (head)
    # then interleaves this script's lines behind the subprocess's. Line buffering keeps the
    # printed order the same as the executed order, which is what makes the log readable as a
    # record of what happened.
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:  # noqa: BLE001
        pass

    run = argv == ["--run"]
    if argv and not run:
        print("REFUSING: unrecognised argument(s) %s. This script takes --run, or nothing "
              "(dry run)." % " ".join(argv))
        return 2

    ecs = boto3.client("ecs", region_name=REGION)

    svc = ecs.describe_services(cluster=CLUSTER, services=[SERVICE])["services"][0]
    before = next((d for d in svc["deployments"] if d.get("status") == "PRIMARY"), svc)
    before_rev = before["taskDefinition"].split("/")[-1]
    print("=" * 78)
    print("STEP 0  deployed now: %s  (running %s / desired %s)"
          % (before_rev, before.get("runningCount"), before.get("desiredCount")))
    print("=" * 78)

    # ---- STEP 1: register -------------------------------------------------------------
    print("\nSTEP 1  %s the cohere revision from the DEPLOYED one...\n"
          % ("registering" if run else "DRY RUN of registering"))
    cmd = [sys.executable, str(HELPER),
           "--set-env", "GRAPHRAG_RERANK_BACKEND=cohere",
           "--add-secret", "COHERE_API_KEY=%s" % SECRET_ARN,
           "--image", IMAGE_DIGEST]
    if run:
        cmd.append("--yes")
    rc = subprocess.call(cmd, cwd=str(ROOT))
    if rc != 0:
        print("\nREGISTER FAILED (exit %d). Nothing was deployed; serving is untouched." % rc)
        return rc
    if not run:
        print("\n" + "=" * 78)
        print("DRY RUN COMPLETE -- nothing was registered and nothing was deployed.")
        print("Re-run with --run to register the revision above and force the deployment.")
        print("=" * 78)
        return 0

    # ---- STEP 2: verify what actually got registered ----------------------------------
    td = ecs.describe_task_definition(taskDefinition=FAMILY)["taskDefinition"]
    new_arn, new_rev = td["taskDefinitionArn"], td["revision"]
    con = next(c for c in td["containerDefinitions"] if c["name"] == CONTAINER)
    env = {e["name"]: e["value"] for e in con.get("environment", [])}
    secrets = {s["name"] for s in con.get("secrets", [])}

    image = con.get("image", "")
    print("\nSTEP 2  verifying revision %d before deploying it" % new_rev)
    print("        GRAPHRAG_RERANK_BACKEND = %s" % env.get("GRAPHRAG_RERANK_BACKEND"))
    print("        COHERE_API_KEY mounted  = %s" % ("COHERE_API_KEY" in secrets))
    print("        image                   = %s" % image.split("@")[-1])
    print("        env keys carried        = %d   secrets = %d" % (len(env), len(secrets)))
    if env.get("GRAPHRAG_RERANK_BACKEND") != "cohere" or "COHERE_API_KEY" not in secrets:
        print("\nREFUSING TO DEPLOY: revision %d does not carry the flip. Serving is untouched."
              % new_rev)
        return 1
    # The env value and the code that reads it must ship TOGETHER. Rev 92 proved the failure mode:
    # backend=cohere on an image with no cohere branch falls through to the CPU cross-encoder.
    if IMAGE_DIGEST not in image:
        print("\nREFUSING TO DEPLOY: revision %d runs %s, not the P1 image %s (commit %s). The "
              "backend value would be read by code that has no cohere branch and would fall "
              "through to the CPU cross-encoder. Serving is untouched."
              % (new_rev, image.split("@")[-1], IMAGE_DIGEST, IMAGE_COMMIT))
        return 1
    if int(new_rev) <= int(before_rev.split(":")[-1]):
        print("\nREFUSING TO DEPLOY: revision %d is not newer than the deployed %s."
              % (new_rev, before_rev))
        return 1

    # ---- STEP 3: deploy ---------------------------------------------------------------
    print("\nSTEP 3  update-service --force-new-deployment onto %s:%d\n" % (FAMILY, new_rev))
    out = ecs.update_service(cluster=CLUSTER, service=SERVICE,
                             taskDefinition=new_arn, forceNewDeployment=True)["service"]
    dep = next((d for d in out["deployments"] if d.get("status") == "PRIMARY"), {})
    print("        deployment id : %s" % dep.get("id"))
    print("        taskDefinition: %s" % dep.get("taskDefinition", "").split("/")[-1])
    print("        rolloutState  : %s" % dep.get("rolloutState"))

    print("\n" + "=" * 78)
    print("DEPLOY REQUESTED. This is NOT acceptance.")
    print("ECS ROLLOUT STATE LIES: rolloutState=COMPLETED, a reported taskDefinition and a")
    print("reported image digest are ALL compatible with nothing having changed. Accept only on")
    print("  (a) a NEW task ARN, and (b) a FRESH boot log in that task's own stream.")
    print("Tell Claude 'done' -- it runs that verification, the prod smoke, and a live turn's")
    print("rerank_lane check (expects backends ['cohere'], fallbacks 0).")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
