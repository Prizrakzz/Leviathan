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


def build_command(*, mode: str, nodes: str | None = None, allow_churn: float | None = None) -> list[str]:
    """The container command (the image ENTRYPOINT is `python`, so this is the arg list to it).

    `mode` is EXACTLY one of the two free evidence_batch maintenance modes — `rebuild-slices` (no args) or
    `reroute` (honours `--nodes n1,n2`; evidence_batch defaults that to "all" when omitted). We deliberately
    surface only these two: the billed modes (--submit/--run/--fill) have their own gated wrapper
    (submit_batch_evidence) and must not be reachable through a "maintenance" verb.

    `allow_churn` (G1b) threads the write-guard escape hatch into the cloud path, because that is where the
    writes actually happen: without it a legitimate large re-route would be REFUSED in-job with no way to
    declare the drop it expects. It is a MAGNITUDE, never a boolean.
    """
    if mode not in ("rebuild-slices", "reroute"):
        raise ValueError(f"unknown maintenance mode: {mode!r} (expected 'rebuild-slices' or 'reroute')")
    cmd = ["-m", "leviathan.graphrag.evidence_batch", f"--{mode}"]
    if mode == "reroute" and nodes:                          # rebuild-slices takes no --nodes (whole-cache route)
        cmd += ["--nodes", nodes]
    if allow_churn is not None:
        cmd += ["--allow-churn", str(allow_churn)]
    return cmd


# The E1 darkness census --diff invocation the census-gate chains AFTER the maintenance module in-job.
# FLAG-NAME NOTE (the wave plan's own correction): this leg invokes `e1_census`, whose argparse exposes
# `--baseline`. `--census-baseline` is load_pg_evidence's OWN flag for the POST-PG-LOAD gate. Two distinct
# gates, two distinct baseline flags — passing the wrong one here fails the job on an unrecognized argument.
_CENSUS_GATE_CMD = ["-m", "leviathan.graphrag.e1_census", "--diff"]

# G2 / D-EI-1 — the driver-slice manifest-mirror lint. Chained AHEAD of the maintenance module, because it is
# the only guard in the wave that fires BEFORE any compute is spent: a term edit that never reached the
# tracked mirror re-routes the whole driver layer, and catching it after a ~3-4h re-embed is catching it too
# late. config_check is a manual CLI today and there is no CI and no pre-commit, so this chain IS its runner.
_MANIFEST_LINT_CMD = ["-m", "leviathan.graphrag.driver_slices_manifest", "--check"]


def build_gated_command(base_cmd: list[str], *, census_gate: bool = True,
                        manifest_lint: bool = True, census_baseline: str | None = None) -> list[str]:
    """Wrap a maintenance command (from `build_command`) into ONE python invocation that runs, in order:

        1. the driver-slice manifest lint (G2)          -- BEFORE the pass; a config drift costs nothing here
        2. the maintenance module itself                -- the rebuild/reroute
        3. the E1 census --diff standing gate (W1.3)    -- AFTER the pass

    Each step runs only if every earlier step exited 0, and the chain exits with the FIRST nonzero code, so a
    failed rebuild is never masked by a clean census nor vice-versa. The image ENTRYPOINT is `python`, so a
    container command is exactly one python invocation — hence the `python -c` chain.

    Both wrappers are individually switchable. `manifest_lint` defaults ON: the lint is pure config
    arithmetic (milliseconds, no S3, no network) and turning it off is the thing that needs a flag, not
    turning it on. `census_gate` stays caller-driven (--census-gate).

    `census_baseline` threads an EXPLICIT baseline into step 3 — the fix for the gate being inert on the flow
    it was built for: `configs/graphrag/eval/` is in `.dockerignore` so there is no local archive in-image,
    and a shadow rebuild's `<EVIDENCE_S3>/eval/` prefix does not exist, so both fallbacks resolve to None and
    the gate prints "skipping the gate" and exits 0. It accepts an `s3://` URI pointing at the LIVE census."""
    steps: list[list[str]] = []
    if manifest_lint:
        steps.append(list(_MANIFEST_LINT_CMD))
    steps.append(list(base_cmd))
    if census_gate:
        steps.append(list(_CENSUS_GATE_CMD) + (["--baseline", census_baseline] if census_baseline else []))
    if len(steps) == 1:
        return steps[0]
    script = (
        "import subprocess, sys; rc = 0\n"
        f"for step in {steps!r}:\n"
        "    rc = subprocess.call([sys.executable, *step])\n"
        "    if rc:\n"
        "        break\n"
        "sys.exit(rc)"
    )
    return ["-c", script]


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
    ap.add_argument("--census-gate", action="store_true",
                    help="opt-in W1.3 standing gate: after the rebuild/reroute, run the E1 darkness census "
                         "--diff in the SAME job and FAIL it (nonzero exit) on a consumed->orphan transition, "
                         "retire-count growth, or a per-slice population drop past the trip lines (G3b).")
    ap.add_argument("--census-baseline", default=None, metavar="PATH_OR_S3URI",
                    help="--census-gate only: the EXPLICIT prior e1_census.json the in-job gate diffs "
                         "against, as a container path or an s3:// URI. Without it the gate resolves NO "
                         "baseline on the shadow-rebuild flow (no local archive in-image, no eval/ prefix "
                         "under a shadow) and passes silently. Note this becomes `--baseline` on the "
                         "e1_census leg; --census-baseline is load_pg_evidence's own flag for a different "
                         "gate.")
    ap.add_argument("--allow-churn", type=float, default=None, metavar="PCT",
                    help="G1b: permit a per-slice population DROP of up to PCT percent in-job. Without it "
                         "the write guard REFUSES any drop >= 10%% with nothing written. Requires a "
                         "magnitude -- state the churn you expect.")
    ap.add_argument("--no-manifest-lint", dest="manifest_lint", action="store_false", default=True,
                    help="skip the G2 driver-slice manifest-mirror lint that otherwise runs BEFORE the pass "
                         "(escape hatch for a tree that deliberately has no mirror)")
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

    command = build_command(mode=mode, nodes=args.nodes, allow_churn=args.allow_churn)
    if args.census_gate or args.manifest_lint:               # G2 lint (default on) + opt-in W1.3 census gate
        command = build_gated_command(command, census_gate=args.census_gate,
                                      manifest_lint=args.manifest_lint,
                                      census_baseline=args.census_baseline)
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
