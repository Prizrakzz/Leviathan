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
import json
import sys
from collections import defaultdict
from pathlib import Path

_SERVING_CLUSTERS = ["leviathan-dev-serving"]

_REPO_ROOT = Path(__file__).resolve().parents[2]
DAG_SCHEDULES = _REPO_ROOT / "infra" / "terraform" / "envs" / "dev" / "dag_schedules.auto.tfvars.json"
SIDECAR_BUCKET = "leviathan-dev-shahem-001"


def _pin(image: str) -> tuple[str, str] | None:
    """'...amazonaws.com/repo@sha256:abc' -> (repo, digest); None for tag-referenced images."""
    if "@sha256:" not in image or ".ecr." not in image:
        return None
    repo = image.split("/")[-1].split("@")[0]
    return repo, "sha256:" + image.split("@sha256:")[-1]


# ===========================================================================
# --config-drift: the FENCE for incident I-1, at FLEET scope.
#
# The in-container preflight (leviathan.common.image_stamp, wired into
# jobs/audit/silver_rebuild_gate.py) can only speak once a job has already
# fired -- and only from images built AFTER the fence existed. This pass
# catches the same class BEFORE the fire, from the outside, for every
# digest-pinned jobdef: it compares what each TOP revision's image BAKED
# (published as an S3 manifest sidecar at push time) against what the
# scheduler ASKS that jobdef to gate (dag_schedules.auto.tfvars.json --
# terraform-applied, therefore always current).
#
# Run today and it goes RED on leviathan-dev-silver-gate the moment
# configs/silver/tables/silver_futures_eod.yaml lands, i.e. 2026-07-28 --
# four days before anyone read a gate log.
#
# SCOPING IS THE WHOLE DESIGN. RED is reserved for the SEMANTIC mismatch
# ("a table this jobdef is asked to gate is not in its baked set") and for
# UNKNOWN PROVENANCE (no sidecar => cannot prove it is current => treat as
# stale). Plain fingerprint drift is YELLOW, never RED: a blanket
# "fingerprint != HEAD" rule fires on all ~33 digest-pinned jobdefs on every
# config commit, and a fence that always fires gets muted.
# ===========================================================================
def parse_dag_asks(path=None) -> dict[str, set[str]]:
    """jobdef name -> the set of silver table configs that jobdef must have BAKED.

    Reads the same authority the scheduler itself uses: each family's ``input_json`` is a JSON
    string whose ``Input`` is another JSON string carrying ``gate`` (with ``jobdef`` + the argv
    containing ``--tables``), ``gate_tables``, ``phases`` and ``promote``.

    TWO kinds of exposure, both counted:
      * the GATE jobdef -- classifies the table against its baked F010 registry. This is the exact
        surface that produced incident I-1.
      * the family's PHASE/PROMOTE jobdefs (fetch/bronze/silver/promote tasks) -- the transform
        tasks read the same ``configs/silver/tables/<table>.yaml`` contract to write the table.
        Omitting them would have left ``leviathan-dev-b3-flat-silver`` unaudited, and that jobdef
        is pinned to sha256:3590b188 -- the very digest that caused I-1.

    Derived, never hand-maintained: a new gated family is covered the moment its tfvars entry is
    applied.
    """
    p = Path(path) if path is not None else DAG_SCHEDULES
    asks: dict[str, set[str]] = defaultdict(set)
    try:
        families = json.loads(p.read_text(encoding="utf-8"))["dag_schedules"]
    except Exception as exc:  # noqa: BLE001
        print("WARN: could not read %s (%s) -- no asks derived" % (p, type(exc).__name__))
        return {}
    for fam in families.values():
        try:
            payload = json.loads(json.loads(fam["input_json"])["Input"])
        except Exception:  # noqa: BLE001 -- a family without a parseable input contributes nothing
            continue
        gate = payload.get("gate") or {}
        family_tables: set[str] = set(payload.get("gate_tables") or [])
        argv = list(gate.get("command") or [])
        for i, tok in enumerate(argv):
            if tok == "--tables" and i + 1 < len(argv):
                family_tables.update(t.strip() for t in argv[i + 1].split(",") if t.strip())
        if not family_tables:
            continue
        worker_jobdefs = {gate.get("jobdef")}
        for phase in (payload.get("phases") or {}).values():
            for task in (phase or {}).get("tasks") or []:
                worker_jobdefs.add(task.get("jobdef"))
        for task in (payload.get("promote") or {}).get("tasks") or []:
            worker_jobdefs.add(task.get("jobdef"))
        for jd in worker_jobdefs:
            if jd:
                asks[jd].update(family_tables)
    return dict(asks)


def run_config_drift(asks: dict[str, set[str]], pins: dict[str, object],
                     sidecar_fetch, head_tables: set[str], head_fp: str) -> int:
    """Compare each jobdef's ASK against what its pinned image BAKED. Returns the exit code.

    ``pins``  : jobdef -> ("digest", repo, digest) | ("tag", image) | None
    ``sidecar_fetch(repo, digest)`` -> manifest dict, or None when no sidecar exists.

    RED (exit 1): an asked table absent from the baked set, or a digest with no sidecar at all.
    YELLOW (exit 0): baked table SET matches but the content fingerprint differs from HEAD.
    """
    red_stale: list[str] = []    # PROVEN: the image bakes a set that is missing an asked table
    red_unproven: list[str] = []  # UNPROVEN: no sidecar, so staleness cannot be ruled out
    yellow: list[str] = []
    print("--config-drift: %d jobdef(s) read silver table configs; repo HEAD has %d configs "
          "(fp %s)" % (len(asks), len(head_tables), head_fp))
    for jobdef in sorted(asks):
        ask = asks[jobdef]
        pin = pins.get(jobdef)
        if pin is None:
            print("  skip %s: no ACTIVE jobdef found" % jobdef)
            continue
        if pin[0] == "tag":
            print("  TAG-PINNED %s -> %s (never stale, but moves without a jobdef change -- not "
                  "auditable by digest)" % (jobdef, pin[1]))
            continue
        _, repo, digest = pin
        manifest = None
        try:
            manifest = sidecar_fetch(repo, digest)
        except Exception as exc:  # noqa: BLE001
            print("  WARN sidecar fetch failed for %s %s (%s)" % (repo, digest[:19],
                                                                  type(exc).__name__))
        if not manifest:
            sample = sorted(ask)
            red_unproven.append(
                "UNKNOWN-PROVENANCE %s -> %s %s has NO manifest sidecar, so it cannot PROVE it "
                "bakes the %d configs it reads (%s%s). Unproven is treated as stale."
                % (jobdef, repo, digest[:19], len(ask), ", ".join(sample[:6]),
                   ", ..." if len(sample) > 6 else ""))
            continue
        baked = set(manifest.get("silver_tables") or [])
        missing = sorted(ask - baked)
        if missing:
            red_stale.append("IMAGE-PREDATES-CONFIG %s -> %s %s (commit %s, built %s) bakes %d "
                             "silver table configs; %s NOT among them. The CONFIG IS FINE -- THE "
                             "IMAGE IS STALE: rebuild + repin this jobdef."
                             % (jobdef, repo, digest[:19], str(manifest.get("git_commit"))[:8],
                                manifest.get("build_time_utc"), len(baked), ", ".join(missing)))
        elif manifest.get("silver_tables_fp") != head_fp:
            yellow.append("CONTENT-DRIFT %s -> %s %s: baked table SET matches HEAD but content "
                          "fp %s != HEAD %s (an existing config was edited after this build)"
                          % (jobdef, repo, digest[:19], manifest.get("silver_tables_fp"), head_fp))
    for line in red_stale:
        print("RED  " + line)
    for line in red_unproven:
        print("RED  " + line)
    for line in yellow:
        print("YELLOW " + line)
    if red_stale or red_unproven:
        # The two classes are reported SEPARATELY on purpose. A wall of identical UNKNOWN-
        # PROVENANCE lines is the expected BOOTSTRAP state -- no image in ECR carries a sidecar
        # until it is rebuilt through the fenced build script -- and it clears itself as images
        # are rebuilt. red_stale is the real incident signature and must never be lost inside it.
        print("FAIL --config-drift: %d jobdef(s) PROVABLY pinned to an image missing a config "
              "they read; %d more cannot be proved either way (no sidecar yet -- rebuild through "
              "scripts/build_push_worker.ps1 to publish one)."
              % (len(red_stale), len(red_unproven)))
        return 1
    print("OK --config-drift: every digest-pinned jobdef bakes every silver config it reads")
    return 0


def _head_silver_tables() -> tuple[set[str], str]:
    sys.path.insert(0, str(_REPO_ROOT / "src"))
    from leviathan.common.image_stamp import baked_silver_tables
    stems, fp = baked_silver_tables()
    return set(stems), fp


def _sidecar_fetcher(s3):
    def fetch(repo: str, digest: str):
        key = "image_manifests/%s/%s.json" % (repo, digest.replace(":", "_"))
        try:
            body = s3.get_object(Bucket=SIDECAR_BUCKET, Key=key)["Body"].read()
        except Exception:  # noqa: BLE001 -- absent sidecar == unknown provenance (handled as RED)
            return None
        try:
            return json.loads(body.decode("utf-8"))
        except Exception:  # noqa: BLE001
            return None
    return fetch


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--region", default="us-east-1")
    ap.add_argument("--margin", type=int, default=5,
                    help="warn when a pinned digest sits within N positions of its repo's "
                         "actual lifecycle count cap (caps evict oldest-first); repos with "
                         "no lifecycle policy never warn")
    ap.add_argument("--config-drift", action="store_true",
                    help="FENCE (incident I-1): also verify that every jobdef the scheduler asks "
                         "to gate a silver table is pinned to an image that actually BAKES that "
                         "table's config. RED on a missing table or a digest with no manifest "
                         "sidecar; YELLOW on content-only drift.")
    args = ap.parse_args()

    import boto3  # lazy: importing this module for its pure helpers must not need boto3

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
    top_pin: dict[str, object] = {}
    for page in batch.get_paginator("describe_job_definitions").paginate(status="ACTIVE"):
        for jd in page["jobDefinitions"]:
            image = jd.get("containerProperties", {}).get("image", "")
            p = _pin(image)
            is_top = jd["revision"] == top_rev[jd["jobDefinitionName"]]
            if is_top:
                top_pin[jd["jobDefinitionName"]] = (("digest",) + p) if p else ("tag", image)
            if p:
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
    rc = 0
    if missing_top:
        print("FAIL: %d TOP-revision pin(s) reference deleted images -- re-register on a live "
              "digest before the next scheduled fire" % len(missing_top))
        rc = 1

    if args.config_drift:
        print("")
        s3 = boto3.client("s3", region_name=args.region)
        head_tables, head_fp = _head_silver_tables()
        rc = max(rc, run_config_drift(parse_dag_asks(), top_pin, _sidecar_fetcher(s3),
                                      head_tables, head_fp))
    return rc


if __name__ == "__main__":
    sys.exit(main())
