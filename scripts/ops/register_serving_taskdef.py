"""Register a NEW leviathan-dev-serving task definition FROM THE CURRENTLY DEPLOYED ONE.

D-MW-4 tooling. This wave hand-registers serving taskdefs at least three times (the P1 Cohere
flip, its rollback, the P3 preset work) and the `flip_*` scripts the terraform module comment
references DO NOT EXIST. Every hand-built revision so far has been assembled by copying a JSON
blob and editing it, which is exactly how an env key gets dropped -- the serving container carries
~40 env keys, MOST OF WHICH EXIST ONLY ON THE LIVE REVISION (the config-of-record in
envs/dev/main.tf is known-incomplete; the recorded "13 missing keys" figure is itself stale).
Losing one is a silent behavior change that no gate reads.

THE SOURCE REVISION IS THE ONE THE SERVICE IS RUNNING, NEVER THE FAMILY'S LATEST ACTIVE.
`describe-task-definition --task-definition leviathan-dev-serving` resolves to the highest ACTIVE
revision, which is NOT necessarily deployed: a terraform apply through module.serving mints a
revision from terraform's stale config WITHOUT deploying it (D-MW-4 names this the latest-ACTIVE
poisoning hazard, risk #6). Building the next revision off that one would silently ship the stale
config. So the source is resolved through `describe-services -> services[0].taskDefinition`, and
when the family's latest ACTIVE differs from the deployed one this script says so, loudly, on
every run.

WHAT IT DOES
  1. describe-services -> the DEPLOYED taskdef ARN (the source of truth).
  2. describe-task-definition --include TAGS on that ARN.
  3. strips the fields register_task_definition rejects (taskDefinitionArn, revision, status,
     requiresAttributes, compatibilities, registeredAt, registeredBy, deregisteredAt).
  4. applies --set-env / --unset-env / --add-secret to ONE named container (default `serving`).
  5. prints an ASCII DIFF of env keys + secret names vs the source revision.
  6. registers ONLY with --yes; otherwise it is a dry run that prints the would-be registration.

Secret VALUES never pass through this script (a taskdef carries only `valueFrom` ARNs), and the
random suffix of every secret ARN is masked in output -- this repo is PUBLIC and the estate's
convention (register_evidence_jobdef.py) is that suffixes stay out of it.

Exit codes: 0 = done (registered, or dry run printed); 1 = could not proceed (service/container
not found, malformed patch, nothing to change without --allow-noop).

ASCII-only stdout (cp1252 console).

Usage:
    python scripts/ops/register_serving_taskdef.py \
        --set-env GRAPHRAG_RERANK_BACKEND=cohere \
        --add-secret COHERE_API_KEY=arn:aws:secretsmanager:us-east-1:668891723125:secret:leviathan-dev-cohere-api-key-XXXXXX
    python scripts/ops/register_serving_taskdef.py ... --yes        # actually register
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import sys

_CLUSTER = "leviathan-dev-serving"
_SERVICE = "leviathan-dev-serving"
_CONTAINER = "serving"

# register_task_definition rejects these describe-side fields outright (they are server-assigned).
# Kept as an explicit frozenset rather than a whitelist of what to KEEP: a whitelist silently drops
# any field AWS adds later (ephemeralStorage, runtimePlatform, proxyConfiguration have all appeared
# on this family), and dropping an unknown field is the exact env-loss class this script exists to
# kill.
# Diff-review catch: the blacklist has the MIRRORED failure -- botocore grows TaskDefinition members
# that the register request never accepts (deleteRequestedAt appeared exactly this way and would have
# been a hard ParamValidationError AT THE FLIP MOMENT). So the set is DERIVED from the installed SDK's
# own shapes when possible -- the future-proofing the paragraph above argues for -- with the last
# known-good frozenset as the fallback.
_REJECTED_FALLBACK = frozenset({
    "taskDefinitionArn", "revision", "status", "requiresAttributes", "compatibilities",
    "registeredAt", "registeredBy", "deregisteredAt", "deleteRequestedAt",
})


def _rejected_fields(ecs_client) -> frozenset:
    try:
        sm = ecs_client.meta.service_model
        td = set(sm.shape_for("TaskDefinition").members)
        req = set(sm.shape_for("RegisterTaskDefinitionRequest").members)
        derived = frozenset(td - req)
        return derived if derived else _REJECTED_FALLBACK
    except Exception:  # noqa: BLE001 -- an SDK shape rename must not break the flip tool
        return _REJECTED_FALLBACK

# The law this script's last line quotes, recorded 2026-07 after a rollout reported COMPLETED with
# a new taskdef ARN on a task that had not changed (28h-old log stream).
_ROLLOUT_LAW = (
    "ECS ROLLOUT STATE LIES. `update-service` alone may not replace the task: run\n"
    "      aws ecs update-service --cluster %s --service %s --task-definition %s "
    "--force-new-deployment\n"
    "  and accept the deploy ONLY on (a) a NEW task ARN and (b) a FRESH boot log in that task's\n"
    "  own stream. rolloutState=COMPLETED, a reported taskDefinition, and a reported image digest\n"
    "  are ALL compatible with nothing having changed. startedAt older than the image build is\n"
    "  the tell."
)

_ARN_SUFFIX = re.compile(r"-([A-Za-z0-9]{6})$")


def mask_arn(arn: str) -> str:
    """Mask a Secrets Manager ARN's random 6-char suffix. Not a security control -- an ARN is not a
    credential -- but this repo is public and pasted script output ends up in it, so the estate
    keeps suffixes out of the record (register_evidence_jobdef.py resolves them by NAME for the
    same reason). Non-secret ARNs (SSM parameters, no suffix) pass through unchanged."""
    return _ARN_SUFFIX.sub(lambda m: "-" + "*" * len(m.group(1)), arn or "")


def parse_pairs(items, *, flag: str) -> dict:
    """['K=V', ...] -> {K: V}. Splits on the FIRST '=' only: env values legitimately contain '='
    (base64, DSNs, JSON), and a naive split would truncate them into a silently wrong taskdef."""
    out: dict[str, str] = {}
    for raw in items or []:
        if "=" not in raw:
            raise SystemExit("%s expects KEY=VALUE, got %r" % (flag, raw))
        k, v = raw.split("=", 1)
        k = k.strip()
        if not k:
            raise SystemExit("%s expects a non-empty KEY, got %r" % (flag, raw))
        if k in out:
            raise SystemExit("%s names %s twice -- refusing to guess which wins" % (flag, k))
        out[k] = v
    return out


def strip_for_register(taskdef: dict, rejected: frozenset = _REJECTED_FALLBACK) -> dict:
    """describe_task_definition's taskDefinition -> a register_task_definition payload.
    `rejected` comes from _rejected_fields(ecs) at the call site (SDK-derived); the fallback default
    keeps the function usable in tests without a client."""
    return {k: v for k, v in taskdef.items() if k not in rejected}


def pick_container(payload: dict, name: str) -> dict:
    """The one containerDefinition to patch. A missing name is fatal, and the error NAMES what the
    taskdef actually contains -- a patch silently applied to nothing is worse than no patch."""
    defs = payload.get("containerDefinitions") or []
    for c in defs:
        if c.get("name") == name:
            return c
    raise SystemExit("container %r not in this taskdef; it defines: %s"
                     % (name, ", ".join(sorted(str(c.get("name")) for c in defs)) or "(none)"))


def apply_patch(container: dict, *, set_env: dict, unset_env, add_secret: dict) -> None:
    """Mutate ONE container definition in place. Order within `environment` is preserved for keys
    that already exist (so the diff of a re-registration is empty, not a reshuffle); new keys append
    in the order they were given on the command line."""
    env = list(container.get("environment") or [])
    unset = set(unset_env or ())
    env = [e for e in env if e.get("name") not in unset]
    seen = {e.get("name"): e for e in env}
    for k, v in set_env.items():
        if k in seen:
            seen[k]["value"] = v
        else:
            env.append({"name": k, "value": v})
    container["environment"] = env

    if add_secret:
        secrets = list(container.get("secrets") or [])
        by_name = {s.get("name"): s for s in secrets}
        for name, arn in add_secret.items():
            if name in by_name:
                by_name[name]["valueFrom"] = arn
            else:
                secrets.append({"name": name, "valueFrom": arn})
        container["secrets"] = secrets


def _env_map(container: dict) -> dict:
    return {e.get("name"): e.get("value") for e in (container.get("environment") or [])}


def _secret_map(container: dict) -> dict:
    return {s.get("name"): s.get("valueFrom") for s in (container.get("secrets") or [])}


def _elide(value, width: int = 46) -> str:
    s = "" if value is None else str(value)
    return s if len(s) <= width else s[:width - 3] + "..."


def _short_arn(arn: str) -> str:
    """Render a secret ARN for the DIFF TABLE: everything from ':secret:' on.

    Elision must never eat the identifying part. A head-truncated ARN
    ('arn:aws:secretsmanager:us-east-1:6688917231...') tells the operator nothing about WHICH
    secret is being mounted, which is the one thing this row exists to show; the account/region
    prefix is identical on every row anyway. The full (suffix-masked) ARN is still printed by
    --print-json."""
    marker = ":secret:"
    i = (arn or "").find(marker)
    return ("..." + arn[i:]) if i >= 0 else _elide(arn)


def diff_lines(before: dict, after: dict, *, kind: str, mask=False) -> list[str]:
    """ASCII table of what changes, and ONLY what changes, plus an unchanged COUNT.

    Printing all ~40 unchanged env rows would bury the two that matter; printing nothing at all
    would hide the thing this script exists to prove -- that the carry-over happened. So the
    unchanged keys are counted, not listed, and the count is what an operator checks against the
    source revision."""
    show = (lambda v: _short_arn(mask_arn(v))) if mask else _elide
    keys = sorted(set(before) | set(after))
    rows = []
    unchanged = 0
    for k in keys:
        b, a = before.get(k), after.get(k)
        if k in before and k not in after:
            rows.append(("REMOVE", k, show(b), "-"))
        elif k not in before and k in after:
            rows.append(("ADD", k, "-", show(a)))
        elif b != a:
            rows.append(("CHANGE", k, show(b), show(a)))
        else:
            unchanged += 1
    out = ["%s DIFF vs the source revision (%d unchanged %s carried over verbatim):"
           % (kind.upper(), unchanged, kind)]
    if not rows:
        out.append("  (no %s change)" % kind)
        return out
    width = max(len(r[1]) for r in rows)
    out.append("  %-6s %-*s  %-46s  %s" % ("op", width, "key", "from", "to"))
    out.append("  %s" % ("-" * (6 + 1 + width + 2 + 46 + 2 + 20)))
    for op, k, b, a in rows:
        out.append("  %-6s %-*s  %-46s  %s" % (op, width, k, b, a))
    return out


def resolve_source(ecs, *, cluster: str, service: str) -> tuple[str, str, int | None]:
    """-> (deployed taskdef ARN, family, latest ACTIVE revision or None).

    The deployed ARN is read from the SERVICE, never from the family name (see the module
    docstring). The latest-ACTIVE revision is fetched only so the run can SAY when the two differ;
    it is never used as a source."""
    resp = ecs.describe_services(cluster=cluster, services=[service])
    services = resp.get("services") or []
    if not services:
        fails = "; ".join("%s: %s" % (f.get("arn"), f.get("reason"))
                          for f in (resp.get("failures") or [])) or "no reason given"
        raise SystemExit("service %s not found in cluster %s (%s)" % (service, cluster, fails))
    arn = services[0].get("taskDefinition")
    if not arn:
        raise SystemExit("service %s reports no taskDefinition" % service)
    family = arn.split("/")[-1].rsplit(":", 1)[0]
    latest = None
    try:
        arns = ecs.list_task_definitions(familyPrefix=family, status="ACTIVE", sort="DESC",
                                         maxResults=1).get("taskDefinitionArns") or []
        if arns:
            tail = arns[0].rsplit(":", 1)[-1]
            latest = int(tail) if tail.isdigit() else None
    except Exception as exc:  # noqa: BLE001 -- an unreadable listing must not block the register
        print("WARN: could not list ACTIVE revisions for %s (%s) -- the latest-ACTIVE drift check "
              "is SKIPPED, not passed" % (family, type(exc).__name__))
    return arn, family, latest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cluster", default=_CLUSTER)
    ap.add_argument("--service", default=_SERVICE)
    ap.add_argument("--container", default=_CONTAINER,
                    help="containerDefinitions entry to patch (default: %s)" % _CONTAINER)
    ap.add_argument("--set-env", action="append", metavar="KEY=VAL", default=[],
                    help="set or overwrite one env key (repeatable)")
    ap.add_argument("--unset-env", action="append", metavar="KEY", default=[],
                    help="remove one env key (repeatable)")
    ap.add_argument("--add-secret", action="append", metavar="NAME=ARN", default=[],
                    help="mount one Secrets Manager entry as NAME (repeatable). Removal is "
                         "deliberately NOT offered: the wave's rollback ladder is an env flip, and "
                         "un-mounting a secret by hand is how a container stops booting.")
    ap.add_argument("--region", default="us-east-1")
    ap.add_argument("--allow-noop", action="store_true",
                    help="permit registering a byte-identical copy of the source revision. Off by "
                         "default: a pointless revision is what poisons latest-ACTIVE consumers.")
    ap.add_argument("--print-json", action="store_true",
                    help="dry run also prints the full would-be registration payload")
    ap.add_argument("--yes", action="store_true", help="actually register (default is a dry run)")
    args = ap.parse_args(argv)

    set_env = parse_pairs(args.set_env, flag="--set-env")
    add_secret = parse_pairs(args.add_secret, flag="--add-secret")
    unset_env = [k.strip() for k in (args.unset_env or []) if k.strip()]
    overlap = sorted(set(set_env) & set(unset_env))
    if overlap:
        raise SystemExit("--set-env and --unset-env both name: %s" % ", ".join(overlap))

    import boto3  # lazy: importing this module for its pure helpers must not need boto3

    ecs = boto3.client("ecs", region_name=args.region)
    source_arn, family, latest = resolve_source(ecs, cluster=args.cluster, service=args.service)
    described = ecs.describe_task_definition(taskDefinition=source_arn, include=["TAGS"])
    source_td = described["taskDefinition"]
    tags = described.get("tags") or []
    source_rev = source_td.get("revision")

    print("source: %s (the revision the service is RUNNING)" % source_arn)
    if latest is not None and source_rev is not None and latest != source_rev:
        # This is the D-MW-4 hazard, printed rather than silently handled: someone applied
        # terraform (or hand-registered) without deploying, so the family's default now points at a
        # revision nobody has ever run.
        print("NOTE: the family's latest ACTIVE revision is %s:%d, NOT the deployed %s:%d. This "
              "script deliberately builds from the DEPLOYED one. Anything that resolves this "
              "family BY NAME (submit_eval parity, the promote runbook) is currently reading "
              "revision %d." % (family, latest, family, source_rev, latest))
    print("tags carried over: %d" % len(tags))

    # STRIP FIRST, THEN DEEP-COPY, AND COPY WITH copy.deepcopy -- NOT a json round-trip. Caught by
    # the first live dry run against rev 91: `registeredAt` is a datetime, so json.dumps(source_td)
    # raises before anything is stripped. deepcopy is type-agnostic, which is the right property
    # here anyway: this script must survive whatever boto3 hands back.
    payload = copy.deepcopy(strip_for_register(source_td, _rejected_fields(ecs)))
    container = pick_container(payload, args.container)
    before_env, before_secrets = _env_map(container), _secret_map(container)
    apply_patch(container, set_env=set_env, unset_env=unset_env, add_secret=add_secret)
    after_env, after_secrets = _env_map(container), _secret_map(container)

    print("")
    for line in diff_lines(before_env, after_env, kind="env"):
        print(line)
    print("")
    for line in diff_lines(before_secrets, after_secrets, kind="secret", mask=True):
        print(line)

    changed = (before_env != after_env) or (before_secrets != after_secrets)
    if not changed and not args.allow_noop:
        print("")
        print("REFUSING: the patch changes nothing, so registering would mint a revision that "
              "differs from %s:%s in nothing but its number -- and a new latest-ACTIVE revision is "
              "read by name elsewhere. Pass --allow-noop if a pure re-register is genuinely what "
              "you want." % (family, source_rev))
        return 1

    if args.print_json:
        masked = copy.deepcopy(payload)
        for c in masked.get("containerDefinitions") or []:
            for s in c.get("secrets") or []:
                s["valueFrom"] = mask_arn(s.get("valueFrom", ""))
        print("")
        print("would register (secret ARNs masked):")
        # default=str: any exotic type boto3 hands back renders rather than killing the dry run.
        print(json.dumps({"payload": masked, "tags": tags}, indent=2, sort_keys=True, default=str))

    if not args.yes:
        print("")
        print("DRY RUN -- nothing registered. Re-run with --yes to register a new revision of %s."
              % family)
        return 0

    resp = ecs.register_task_definition(**payload, tags=tags)
    new = resp["taskDefinition"]
    new_ref = "%s:%d" % (new["family"], new["revision"])
    print("")
    print("registered %s (%s)" % (new_ref, new["taskDefinitionArn"]))
    print("")
    print("  " + _ROLLOUT_LAW % (args.cluster, args.service, new_ref))
    return 0


if __name__ == "__main__":
    sys.exit(main())
