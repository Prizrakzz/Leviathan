"""Submit an evidence-slice MAINTENANCE pass (`--rebuild-slices` / `--reroute`) as a Fargate Batch job.

`reroute()` and `rebuild_slices()` are free (no Anthropic call) laptop-only CLI modes of
`leviathan.graphrag.evidence_batch.main()` today — there is NO cloud entrypoint (`build_evidence_task.py`
does full per-node BUILDS only). This wrapper adds one, reusing the same evidence-build job-def as
submit_eval/submit_batch_load_numbers_pg: its image bakes src/ + configs/, its role carries Bedrock + S3,
and its env supplies the bge-m3 backend. The ONE override that matters is `EVIDENCE_S3` — a shadow rebuild
must read/write a shadow prefix so it never touches the live commodity slices.

    python jobs/submit/submit_batch_evidence_maintenance.py --reroute --evidence-s3 s3://bkt/graphrag_evidence --dry-run
    python jobs/submit/submit_batch_evidence_maintenance.py --reroute --nodes corn,soybeans \
        --evidence-s3 s3://bkt/graphrag_evidence/shadow_e1b
    python jobs/submit/submit_batch_evidence_maintenance.py --rebuild-slices \
        --evidence-s3 s3://bkt/graphrag_evidence/shadow_e1b     # on-demand queue: Spot killed a prior embed (exit 137)

WHY the live-prefix refusal (the load-bearing safety): `rebuild_slices()` re-derives ALL slices from the
whole chunks/ doc-cache and CLOBBERS every non-empty commodity slice (evidence_batch.py:263-268) with a
~3-4h re-embed of ~107K vectors. Pointed at the live prefix it would nuke all 24 commodity slices in one
job. So `--rebuild-slices` REFUSES when `--evidence-s3` resolves to the live prefix baked into the
evidence-build job-def (read here via describe_job_definitions), unless you pass `--i-know-this-is-live`.
`--reroute` re-derives from the per-node `_raw/` archive and only rewrites the routed nodes, so it is not
gated the same way — but it still takes the required `--evidence-s3` so a shadow reroute is one flag away.
"""
from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

import boto3

from leviathan.common.batch_submit import write_run_record
from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.metadata import utc_now_iso

logger = get_logger("submit_evidence_maintenance")


def build_command(*, mode: str, nodes: str | None = None) -> list[str]:
    """The container command (the image ENTRYPOINT is `python`, so this is the arg list to it).

    `mode` is EXACTLY one of the two free evidence_batch maintenance modes — `rebuild-slices` (no args) or
    `reroute` (honours `--nodes n1,n2`; evidence_batch defaults that to "all" when omitted). We deliberately
    surface only these two: the billed modes (--submit/--run/--fill) have their own gated wrapper
    (submit_batch_evidence) and must not be reachable through a "maintenance" verb.
    """
    if mode not in ("rebuild-slices", "reroute"):
        raise ValueError(f"unknown maintenance mode: {mode!r} (expected 'rebuild-slices' or 'reroute')")
    cmd = ["-m", "leviathan.graphrag.evidence_batch", f"--{mode}"]
    if mode == "reroute" and nodes:                          # rebuild-slices takes no --nodes (whole-cache route)
        cmd += ["--nodes", nodes]
    return cmd


def _normalize_prefix(uri: str) -> str:
    """Canonicalize an s3:// evidence prefix for equality: drop a trailing slash so a shadow that only differs
    by a `/` (or its absence) isn't mistaken for a distinct prefix, and vice-versa."""
    return uri.rstrip("/")


def live_prefix_from_jobdef(job_definition: str, aws_region: str) -> str | None:
    """Read the `EVIDENCE_S3` env baked into the evidence-build job-def (the LIVE store) via
    describe_job_definitions. Returns the normalized prefix, or None if the job-def / env isn't found — a
    missing live value must NOT silently disable the refusal, so callers treat None as "couldn't verify".
    """
    client = boto3.client("batch", region_name=aws_region)
    resp = client.describe_job_definitions(jobDefinitionName=job_definition, status="ACTIVE")
    defs = resp.get("jobDefinitions") or []
    if not defs:
        return None
    # ACTIVE revisions come back newest-first; the current live prefix is whatever the latest one bakes.
    latest = max(defs, key=lambda d: d.get("revision", 0))
    for pair in (latest.get("containerProperties") or {}).get("environment") or []:
        if pair.get("name") == "EVIDENCE_S3" and pair.get("value"):
            return _normalize_prefix(pair["value"])
    return None


def assert_not_live_rebuild(*, evidence_s3: str, job_definition: str, aws_region: str,
                            override: bool) -> None:
    """Refuse a `--rebuild-slices` submission whose `--evidence-s3` IS the live prefix — it would clobber every
    commodity slice. The escape hatch (`--i-know-this-is-live`) skips both the describe call and the check, so
    an intentional live rebuild (or an env where describe isn't reachable) is still possible on purpose."""
    if override:
        logger.warning("--i-know-this-is-live set: SKIPPING the live-prefix guard for %s", evidence_s3)
        return
    live = live_prefix_from_jobdef(job_definition, aws_region)
    if live is None:
        raise SystemExit(
            f"could not read the live EVIDENCE_S3 from job-def {job_definition!r} to verify "
            f"--evidence-s3={evidence_s3} is a SHADOW prefix. Refusing --rebuild-slices (it clobbers every "
            f"commodity slice). Pass --i-know-this-is-live only if you truly mean the live store.")
    if _normalize_prefix(evidence_s3) == live:
        raise SystemExit(
            f"REFUSING --rebuild-slices against the LIVE prefix {live} — it re-embeds ~107K vectors and "
            f"clobbers all 24 commodity slices. Point --evidence-s3 at a shadow prefix (e.g. {live}/shadow_e1b) "
            f"or pass --i-know-this-is-live if you truly mean to rebuild the live store.")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    load_env()

    env = os.environ.get("LEVIATHAN_ENV", "dev")
    project = os.environ.get("LEVIATHAN_PROJECT", "leviathan")
    job_definition = f"{project}-{env}-evidence-build"        # reuse: image + EVIDENCE_S3 env + bge-m3 backend
    ondemand_queue = f"{project}-{env}-queue-ondemand"        # rebuild default: Spot reclaimed a prior ~3-4h embed

    ap = argparse.ArgumentParser(description="Submit an evidence-slice reroute/rebuild maintenance Batch job")
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument("--rebuild-slices", action="store_true",
                     help="re-derive ALL slices from the whole chunks/ doc-cache (~3-4h re-embed; clobbers "
                          "every commodity slice — SHADOW prefix only)")
    grp.add_argument("--reroute", action="store_true",
                     help="re-derive slices from the persisted _raw archive (fast; only rewrites --nodes)")
    ap.add_argument("--nodes", default=None,
                    help="reroute only: comma-separated node/contract ids (evidence_batch defaults to 'all')")
    ap.add_argument("--evidence-s3", required=True, metavar="S3_URI",
                    help="REQUIRED EVIDENCE_S3 override (read+write prefix) — use a SHADOW prefix for a rebuild "
                         "so the live commodity slices are never touched")
    ap.add_argument("--i-know-this-is-live", action="store_true",
                    help="escape hatch: allow --rebuild-slices against the live prefix (or when the job-def's "
                         "live EVIDENCE_S3 can't be read to verify)")
    ap.add_argument("--vcpu", type=int, default=8)           # matches the jobdef default (16 threads + bge-m3)
    ap.add_argument("--memory", type=int, default=16384, help="MiB (bge-m3 weights ~2.5 GB + working set)")
    ap.add_argument("--queue", default=None,
                    help="override the Batch queue (default: on-demand for --rebuild-slices, shared for --reroute)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    mode = "rebuild-slices" if args.rebuild_slices else "reroute"
    if mode == "reroute" and args.i_know_this_is_live:
        ap.error("--i-know-this-is-live only applies to --rebuild-slices")

    aws_region = get_required_env("AWS_REGION")
    # Default queue: on-demand for the long rebuild (Spot killed a prior embed, exit 137); shared for reroute.
    job_queue = args.queue or (ondemand_queue if mode == "rebuild-slices" else f"{project}-{env}-queue")

    if mode == "rebuild-slices":                             # the load-bearing safety — do it BEFORE any submit
        assert_not_live_rebuild(evidence_s3=args.evidence_s3, job_definition=job_definition,
                                aws_region=aws_region, override=args.i_know_this_is_live)

    command = build_command(mode=mode, nodes=args.nodes)
    overrides: dict = {
        "command": command,
        "environment": [{"name": "EVIDENCE_S3", "value": args.evidence_s3}],
        "resourceRequirements": [
            {"type": "VCPU", "value": str(args.vcpu)},
            {"type": "MEMORY", "value": str(args.memory)},
        ],
    }
    node_tag = ("-" + args.nodes.replace(",", "-").replace("_", "-")[:40]) if (mode == "reroute" and args.nodes) else ""
    job_name = f"evidence-{mode}{node_tag}"

    logger.info("queue=%s  job_def=%s  EVIDENCE_S3=%s", job_queue, job_definition, args.evidence_s3)
    logger.info("command: python %s", " ".join(command))
    if args.dry_run:
        logger.info("[DRY RUN] would submit job_name=%s (nothing submitted).", job_name)
        return

    client = boto3.client("batch", region_name=aws_region)
    resp = client.submit_job(jobName=job_name, jobQueue=job_queue, jobDefinition=job_definition,
                             containerOverrides=overrides)
    logger.info("Submitted  job_name=%s  job_id=%s", job_name, resp["jobId"])

    run_id = utc_now_iso().replace(":", "-")
    write_run_record(Path("data/batch_runs") / f"evidence_maintenance_{run_id}.json",
                     {"run_id": run_id, "job_name": job_name, "job_id": resp["jobId"],
                      "mode": mode, "nodes": args.nodes, "evidence_s3": args.evidence_s3})


if __name__ == "__main__":
    main()
