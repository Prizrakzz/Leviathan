#!/usr/bin/env python
"""Re-register a Batch job definition onto a NEW image digest, copying the live revision VERBATIM.

    python scripts/ops/repin_jobdef_digest.py --job-definition leviathan-dev-esr-bronze-to-silver \
        --image-digest sha256:<the digest kaniko printed> --expect-vcpu 2 --expect-memory 12288
    ... then re-run with --apply once the printed diff shows ONLY the image line.

WHY THIS EXISTS (C-M2 / C-NEW-F2).  ``leviathan-dev-esr-bronze-to-silver`` and
``leviathan-dev-silver-publisher-runner`` are NOT terraform-managed: they are hand-registered.  The
estate's hand-registration scripts (``jobs/utils/register_*_jobdef.py``, ``jobs/submit/
submit_batch_b2s_esr.py``) build the descriptor from HARDCODED constants -- and
``submit_batch_b2s_esr.py`` hardcodes ``MEMORY: "4096"`` for exactly the jobdef that was bumped to
12,288 MiB on 2026-09-03 after it OOM'd at 4 GB on the all-vintage concat.  A re-registration built
from a stale constant silently reverts the envelope and the job dies on its next run, with a clean
console and a green-looking plan.  MEASURED LIVE 2026-09-04:

    leviathan-dev-esr-bronze-to-silver     rev 8   2 vCPU / 12,288 MiB
    leviathan-dev-silver-publisher-runner  rev 36  2 vCPU / 12,288 MiB
    leviathan-dev-usda-esr-bronze          rev 20  2 vCPU /  4,096 MiB
    leviathan-dev-silver-gate              rev 34  2 vCPU /  8,192 MiB

So this tool never AUTHORS a descriptor.  It reads the highest ACTIVE revision, copies it, swaps
ONE field -- ``containerProperties.image``, and only its digest, never its repository -- and
refuses if anything else moved.  ``--expect-vcpu`` / ``--expect-memory`` let the runbook state the
envelope as an assertion rather than as a hope.

DRY RUN BY DEFAULT.  Without ``--apply`` nothing is registered; the diff is printed and the exit
code is 0.  With ``--apply`` the new revision is registered and then RE-DESCRIBED, and the tool
asserts the live post-registration resourceRequirements equal the ones it copied -- because in this
estate a digest-pinned jobdef makes a push a no-op, and the only proof a repin landed is a NEW
REVISION NUMBER read back from AWS.

ASCII-only output.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import sys

# Fields ``describe_job_definitions`` returns that ``register_job_definition`` will not accept.
READ_ONLY_FIELDS = ("jobDefinitionArn", "revision", "status", "containerOrchestrationType")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class RepinRefusal(RuntimeError):
    """A refusal: the descriptor moved in a way this tool will not sign for."""


def _split_image(image: str) -> tuple[str, str]:
    """``repo@sha256:...`` or ``repo:tag`` -> ``(repo, reference)``."""
    if "@" in image:
        repo, _, ref = image.partition("@")
        return repo, ref
    repo, _, tag = image.rpartition(":")
    if not repo or "/" in tag:
        return image, ""
    return repo, tag


def resource_map(descriptor: dict) -> dict:
    container = descriptor.get("containerProperties") or {}
    return {r["type"]: str(r["value"]) for r in container.get("resourceRequirements", [])}


def sanitize(descriptor: dict) -> dict:
    """The live descriptor minus the fields register_job_definition rejects. Nothing else moves."""
    payload = copy.deepcopy(descriptor)
    for field in READ_ONLY_FIELDS:
        payload.pop(field, None)
    return payload


def plan_repin(live: dict, new_digest: str) -> tuple[dict, list[str]]:
    """Return ``(register payload, the list of changed json paths)``.

    Raises :class:`RepinRefusal` if the digest is malformed or the descriptor carries no image.
    """
    if not DIGEST_RE.match(new_digest):
        raise RepinRefusal(
            f"--image-digest must be sha256:<64 hex>, got {new_digest!r}. Read the digest off the "
            "kaniko log or `aws ecr describe-images`; never infer it from a tag."
        )
    payload = sanitize(live)
    container = payload.get("containerProperties")
    if not container or not container.get("image"):
        raise RepinRefusal(
            f"{live.get('jobDefinitionName')!r} rev {live.get('revision')} has no "
            "containerProperties.image -- this tool only repins container jobdefs."
        )
    repo, old_ref = _split_image(container["image"])
    container["image"] = f"{repo}@{new_digest}"

    changed = _diff_paths(sanitize(live), payload)
    if changed != ["containerProperties.image"]:
        raise RepinRefusal(
            "REFUSING: the repin would change more than the image: " + ", ".join(changed)
        )
    return payload, [f"containerProperties.image: {old_ref} -> {new_digest}"]


def _diff_paths(a, b, prefix: str = "") -> list[str]:
    """Every json path at which *a* and *b* differ (sorted, deterministic)."""
    if isinstance(a, dict) and isinstance(b, dict):
        out: list[str] = []
        for key in sorted(set(a) | set(b)):
            child = f"{prefix}.{key}" if prefix else str(key)
            if key not in a or key not in b:
                out.append(child)
            else:
                out.extend(_diff_paths(a[key], b[key], child))
        return out
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return [prefix or "<root>"]
        out = []
        for i, (x, y) in enumerate(zip(a, b)):
            out.extend(_diff_paths(x, y, f"{prefix}[{i}]"))
        return out
    return [] if a == b else [prefix or "<root>"]


def assert_envelope(descriptor: dict, expect_vcpu: str | None, expect_memory: str | None) -> None:
    """The runbook's envelope, stated as an assertion. Refuses on any mismatch."""
    resources = resource_map(descriptor)
    for label, expected in (("VCPU", expect_vcpu), ("MEMORY", expect_memory)):
        if expected is None:
            continue
        actual = resources.get(label)
        if actual != str(expected):
            raise RepinRefusal(
                f"REFUSING: {label} is {actual!r} on "
                f"{descriptor.get('jobDefinitionName')!r} rev {descriptor.get('revision')}, "
                f"expected {str(expected)!r}. A re-registration must PRESERVE the live envelope; "
                "the 12,288 MiB on the two ESR silver jobdefs is the post-OOM bump of 2026-09-03."
            )


def latest_active(batch, name: str) -> dict:
    revisions = batch.describe_job_definitions(
        jobDefinitionName=name, status="ACTIVE")["jobDefinitions"]
    if not revisions:
        raise RepinRefusal(f"REFUSING: no ACTIVE revision of {name!r} to copy.")
    return sorted(revisions, key=lambda d: d["revision"])[-1]


def repin(batch, name: str, new_digest: str, *, expect_vcpu=None, expect_memory=None,
          apply: bool = False) -> dict:
    live = latest_active(batch, name)
    assert_envelope(live, expect_vcpu, expect_memory)
    before = resource_map(live)
    payload, changes = plan_repin(live, new_digest)

    print(f"{name}")
    print(f"  live revision      : {live['revision']}")
    print(f"  live image         : {live['containerProperties']['image']}")
    print(f"  live resources     : VCPU={before.get('VCPU')} MEMORY={before.get('MEMORY')}")
    for line in changes:
        print(f"  change             : {line}")
    print(f"  fields changed     : 1 (containerProperties.image) -- everything else copied verbatim")

    if not apply:
        print("  DRY RUN            : nothing registered. Re-run with --apply.")
        return {"job_definition": name, "live_revision": live["revision"], "applied": False,
                "resources": before}

    registered = batch.register_job_definition(**payload)
    new_revision = registered["revision"]
    fresh = latest_active(batch, name)
    after = resource_map(fresh)
    if after != before:
        raise RepinRefusal(
            f"REFUSING TO CONFIRM: {name} rev {new_revision} registered with resources {after} "
            f"but the copied revision had {before}. Deregister it and investigate."
        )
    if fresh["revision"] != new_revision:
        raise RepinRefusal(
            f"REFUSING TO CONFIRM: registered rev {new_revision} but the highest ACTIVE revision "
            f"reads {fresh['revision']} -- something else is registering this jobdef."
        )
    print(f"  NEW REVISION       : {new_revision}  (was {live['revision']})")
    print(f"  new image          : {fresh['containerProperties']['image']}")
    print(f"  resources preserved: VCPU={after.get('VCPU')} MEMORY={after.get('MEMORY')}")
    return {"job_definition": name, "live_revision": live["revision"],
            "new_revision": new_revision, "applied": True, "resources": after}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--job-definition", action="append", required=True, dest="job_definitions",
                    help="jobdef name (repeatable)")
    ap.add_argument("--image-digest", required=True, dest="image_digest",
                    help="sha256:<64 hex>, read off the kaniko log or ecr describe-images")
    ap.add_argument("--aws-region", default="us-east-1", dest="aws_region")
    ap.add_argument("--expect-vcpu", default=None, dest="expect_vcpu",
                    help="assert the live revision's VCPU before copying it")
    ap.add_argument("--expect-memory", default=None, dest="expect_memory",
                    help="assert the live revision's MEMORY (MiB) before copying it")
    ap.add_argument("--apply", action="store_true", help="register (default: dry run)")
    args = ap.parse_args(argv)

    import boto3
    batch = boto3.client("batch", region_name=args.aws_region)
    results = []
    for name in args.job_definitions:
        try:
            results.append(repin(batch, name, args.image_digest,
                                 expect_vcpu=args.expect_vcpu, expect_memory=args.expect_memory,
                                 apply=args.apply))
        except RepinRefusal as exc:
            print(f"{name}\n  {exc}", file=sys.stderr)
            return 2
    print(json.dumps(results, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
