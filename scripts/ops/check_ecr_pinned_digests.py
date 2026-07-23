"""SILVER-F085 guard: every ECR digest pinned by an ACTIVE Batch jobdef or the serving ECS
taskdef must exist in its repository -- and should not be near the lifecycle count-cap horizon.

Two prod-breaking incidents motivated this (both CannotPullContainerError at scheduled fires):
  - 2026-07-17 (A-W7 Wave-3): a hard cap of 5 evicted tagged digests during an 8-rebuild day
    and broke 8 ACTIVE jobdefs.
  - 2026-07-23 (this guard's namesake): the untagged-after-1-day rule expired latest-only
    pushes whose :latest tag had been stolen by a newer push; 16 jobdef families' TOP
    revisions pinned deleted digests and the 14:00 UTC usda_esr run failed.

Lifecycle policies cannot see external references, so this script is the referee. Run it:
  - BEFORE any ECR lifecycle-policy tightening;
  - after image-push bursts / jobdef re-registrations (a green run = nothing stranded).

Exit codes: 0 = all TOP-revision pins exist; 1 = at least one TOP-revision pin is MISSING
(broken next fire); warnings (non-top pins missing, pins near the cap horizon) never fail.
ASCII-only stdout (cp1252 console).

Usage:
    python scripts/ops/check_ecr_pinned_digests.py [--region us-east-1] [--horizon 25]
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict

import boto3

_SERVING_CLUSTERS = ["leviathan-dev-serving"]


def _pin(image: str) -> tuple[str, str] | None:
    """'...amazonaws.com/repo@sha256:abc' -> (repo, digest); None for tag-referenced images."""
    if "@sha256:" not in image or ".ecr." not in image:
        return None
    repo = image.split("/")[-1].split("@")[0]
    return repo, "sha256:" + image.split("@sha256:")[-1]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--region", default="us-east-1")
    ap.add_argument("--margin", type=int, default=5,
                    help="warn when a pinned digest sits within N positions of its repo's "
                         "actual lifecycle count cap (caps evict oldest-first); repos with "
                         "no lifecycle policy never warn")
    args = ap.parse_args()

    batch = boto3.client("batch", region_name=args.region)
    ecs = boto3.client("ecs", region_name=args.region)
    ecr = boto3.client("ecr", region_name=args.region)

    # (repo, digest) -> list of "jobdef:rev[TOP]" / "service/taskdef:rev" references
    refs: dict[tuple[str, str], list[str]] = defaultdict(list)
    top_rev: dict[str, int] = {}
    for page in batch.get_paginator("describe_job_definitions").paginate(status="ACTIVE"):
        for jd in page["jobDefinitions"]:
            top_rev[jd["jobDefinitionName"]] = max(top_rev.get(jd["jobDefinitionName"], 0),
                                                   jd["revision"])
    for page in batch.get_paginator("describe_job_definitions").paginate(status="ACTIVE"):
        for jd in page["jobDefinitions"]:
            p = _pin(jd.get("containerProperties", {}).get("image", ""))
            if p:
                is_top = jd["revision"] == top_rev[jd["jobDefinitionName"]]
                refs[p].append("%s:%d%s" % (jd["jobDefinitionName"], jd["revision"],
                                            "[TOP]" if is_top else ""))
    for cluster in _SERVING_CLUSTERS:
        try:
            svc_arns = ecs.list_services(cluster=cluster)["serviceArns"]
            for svc in ecs.describe_services(cluster=cluster, services=svc_arns)["services"]:
                td = ecs.describe_task_definition(taskDefinition=svc["taskDefinition"])["taskDefinition"]
                for cd in td["containerDefinitions"]:
                    p = _pin(cd.get("image", ""))
                    if p:
                        refs[p].append("%s/%s[TOP]" % (cluster,
                                                       td["taskDefinitionArn"].split("/")[-1]))
        except Exception as exc:  # noqa: BLE001 -- a missing cluster must not kill the audit
            print("WARN: cluster %s not audited (%s)" % (cluster, type(exc).__name__))

    # newest-first digest order + the repo's REAL lifecycle count cap (None = no policy/no cap)
    import json as _json
    order: dict[str, list[str]] = {}
    cap: dict[str, int | None] = {}
    for repo in sorted({r for r, _ in refs}):
        imgs = []
        for page in ecr.get_paginator("describe_images").paginate(repositoryName=repo):
            imgs += page["imageDetails"]
        imgs.sort(key=lambda i: i["imagePushedAt"], reverse=True)
        order[repo] = [i["imageDigest"] for i in imgs]
        try:
            rules = _json.loads(ecr.get_lifecycle_policy(repositoryName=repo)["lifecyclePolicyText"])["rules"]
            counts = [r["selection"]["countNumber"] for r in rules
                      if r["selection"].get("countType") == "imageCountMoreThan"]
            cap[repo] = min(counts) if counts else None
        except ecr.exceptions.LifecyclePolicyNotFoundException:
            cap[repo] = None

    missing_top, missing_old, near_cap = [], [], []
    for (repo, digest), who in sorted(refs.items()):
        exists = digest in order.get(repo, [])
        if not exists:
            (missing_top if any("[TOP]" in w for w in who) else missing_old).append(
                (repo, digest[:19], who))
        elif (cap.get(repo) and any("[TOP]" in w for w in who)
              and digest not in order[repo][:max(cap[repo] - args.margin, 1)]):
            near_cap.append((repo, digest[:19], order[repo].index(digest) + 1, cap[repo], who))

    print("pinned (repo,digest) pairs audited: %d across %d repos" % (len(refs), len(order)))
    for repo, dig, who in missing_top:
        print("MISSING[TOP] %s %s <- %s" % (repo, dig, ", ".join(who[:4])))
    for repo, dig, who in missing_old:
        print("missing[old-rev] %s %s <- %s" % (repo, dig, ", ".join(who[:2])))
    for repo, dig, pos, c, who in near_cap:
        print("WARN near-cap %s %s at position %d of cap %d (oldest-first eviction) <- %s"
              % (repo, dig, pos, c, ", ".join(who[:3])))
    if not (missing_top or missing_old or near_cap):
        print("OK: every pinned digest exists, none near its repo's lifecycle cap")
    if missing_top:
        print("FAIL: %d TOP-revision pin(s) reference deleted images -- re-register on a live "
              "digest before the next scheduled fire" % len(missing_top))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
