"""D-MW P2 deploy: serving picks up the P2 image (caller-boundary packing + parallel cohere
dispatch + the budget-true knob clamp). IMAGE-ONLY -- rev 93's env and secrets carry verbatim.

    python scripts/ops/dmw_p2_deploy.py            # DRY RUN: prints the diff, mutates NOTHING
    python scripts/ops/dmw_p2_deploy.py --run      # registers + deploys

Same skeleton and same fences as dmw_p1_flip.py (register -> VERIFY -> deploy; --run mandatory;
refuses any other argument): P1's three live-caught tooling defects are why every one of these
exists. The verify step asserts BOTH halves of the P1 flip law in the new revision -- the P2
image digest AND that GRAPHRAG_RERANK_BACKEND=cohere carried over -- because an image-only
change has the MIRROR failure of P1's env-only change: new code under a lost flag is the same
split of one change into two.

At today's width this deploy is provably behavior-neutral (one query x <= 960 docs = one group,
one leaf call -- pinned per lane); the new paths execute only where P3's width creates them.
Rollback: deploy rev 93 (P1 image) or rev 91 (bedrock).
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
# The P2 image (tag 20260811T140350, commit 5b870c5e).
IMAGE_DIGEST = "sha256:0bf8fe570ba12b4b854ff8a4daade3232cd553e735435c6073ddf8bbe53fb16b"
IMAGE_COMMIT = "5b870c5e"

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "scripts" / "ops" / "register_serving_taskdef.py"


def main(argv: list[str]) -> int:
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

    print("\nSTEP 1  %s the P2-image revision from the DEPLOYED one...\n"
          % ("registering" if run else "DRY RUN of registering"))
    cmd = [sys.executable, str(HELPER), "--image", IMAGE_DIGEST]
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

    td = ecs.describe_task_definition(taskDefinition=FAMILY)["taskDefinition"]
    new_arn, new_rev = td["taskDefinitionArn"], td["revision"]
    con = next(c for c in td["containerDefinitions"] if c["name"] == CONTAINER)
    env = {e["name"]: e["value"] for e in con.get("environment", [])}
    secrets = {s["name"] for s in con.get("secrets", [])}
    image = con.get("image", "")

    print("\nSTEP 2  verifying revision %d before deploying it" % new_rev)
    print("        image                   = %s" % image.split("@")[-1])
    print("        GRAPHRAG_RERANK_BACKEND = %s" % env.get("GRAPHRAG_RERANK_BACKEND"))
    print("        COHERE_API_KEY mounted  = %s" % ("COHERE_API_KEY" in secrets))
    print("        env keys carried        = %d   secrets = %d" % (len(env), len(secrets)))
    if IMAGE_DIGEST not in image:
        print("\nREFUSING TO DEPLOY: revision %d does not run the P2 image %s (commit %s). "
              "Serving is untouched." % (new_rev, IMAGE_DIGEST, IMAGE_COMMIT))
        return 1
    if env.get("GRAPHRAG_RERANK_BACKEND") != "cohere" or "COHERE_API_KEY" not in secrets:
        print("\nREFUSING TO DEPLOY: revision %d lost the P1 flip (backend=%s, secret=%s) -- the "
              "mirror of the rev-92 defect. Serving is untouched."
              % (new_rev, env.get("GRAPHRAG_RERANK_BACKEND"), "COHERE_API_KEY" in secrets))
        return 1
    if int(new_rev) <= int(before_rev.split(":")[-1]):
        print("\nREFUSING TO DEPLOY: revision %d is not newer than the deployed %s."
              % (new_rev, before_rev))
        return 1

    print("\nSTEP 3  update-service --force-new-deployment onto %s:%d\n" % (FAMILY, new_rev))
    out = ecs.update_service(cluster=CLUSTER, service=SERVICE,
                             taskDefinition=new_arn, forceNewDeployment=True)["service"]
    dep = next((d for d in out["deployments"] if d.get("status") == "PRIMARY"), {})
    print("        deployment id : %s" % dep.get("id"))
    print("        taskDefinition: %s" % dep.get("taskDefinition", "").split("/")[-1])
    print("\n" + "=" * 78)
    print("DEPLOY REQUESTED -- not acceptance. Tell Claude 'done': it verifies the NEW task ARN")
    print("+ fresh boot log, then reads the live RerankRequests/latency for the P2 no-regression")
    print("gate (expected: byte-identical behavior at today's width).")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
