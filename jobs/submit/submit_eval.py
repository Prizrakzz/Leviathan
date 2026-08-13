"""Submit the GraphRAG v2 eval as a single Fargate Batch job (WS — cloud eval).

Runs the SAME `leviathan.graphrag.eval --run [--judge]` we run locally, but on the evidence-build image/queue
so the laptop stays off (the no-local-compute rule). The image bakes the causal DAGs + `eval_queries*.yaml`;
the report auto-persists to `s3://.../graphrag_evidence/eval/report_<model>_<stem>.md` (eval.main writes it there
when EVIDENCE_S3 is set), so it survives the container being reclaimed. The job reuses the evidence job-def's
`EVIDENCE_S3` env + the Anthropic secret (serving + judge models).

The eval holds every queried slice resident (`CACHE_INDEX=True`) PLUS the bge-m3 embedder and the
bge-reranker-v2-m3 cross-encoder, so we override the job-def's 16 GB up to 32 GB (a legal Fargate value for
8 vCPU; 30 GB is not) to avoid an OOM mid-run.

    # Free: print the exact submission (command + resource overrides), submit nothing
    python jobs/submit/submit_eval.py --dry-run

    # Gated: submit the v2 eval (Sonnet serving + Opus judge) — billed (~$2 of Anthropic API)
    python jobs/submit/submit_eval.py --queries configs/graphrag/eval_queries_v2.yaml --judge

    # Gated: the Bedrock-serving parity arm (convo eval; serving tokens bill to AWS, judge to Anthropic)
    python jobs/submit/submit_eval.py --convos configs/graphrag/eval_convos_v1.yaml --judge \
        --env GRAPHRAG_PROVIDER=bedrock
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

logger = get_logger("submit_eval")

# Serving flags the eval MUST inherit or its measurement of that dimension is silently VACUOUS. The
# evidence-build job-def (reused as the eval image) does NOT bake these, but prod serving does, so we
# default them ON here. GRAPHRAG_REROUTE_V2: the judged-30 submit omitted it, making the rv2 (cross-
# commodity RV) eval dimension a no-op while prod (serving rev-50 taskdef) has it ON. A user --env
# override for the same key WINS (so an explicit A/B arm can still turn it off).
DEFAULT_JOB_ENV = {"GRAPHRAG_REROUTE_V2": "on"}

SERVING_FAMILY = "leviathan-dev-serving"


def _is_flag_on(value: str | None) -> bool:
    """A GRAPHRAG_* env value that reads as ENABLED (on/1/true/yes; anything else is off/unknown)."""
    return (value or "").strip().lower() in ("on", "1", "true", "yes")


def _graphrag_env_from_taskdef(taskdef: dict) -> dict[str, str]:
    """Pull the GRAPHRAG_* container env out of an ecs describe_task_definition response's taskDefinition."""
    out: dict[str, str] = {}
    for cd in taskdef.get("containerDefinitions", []) or []:
        for kv in cd.get("environment", []) or []:
            name = kv.get("name", "")
            if name.startswith("GRAPHRAG_"):
                out[name] = kv.get("value", "")
    return out


def parity_warnings(serving_env: dict[str, str], job_env: dict[str, str]) -> list[str]:
    """serving-ON GRAPHRAG_* flags that are ABSENT from the job env being submitted (sorted).

    Pure/testable: no AWS. A serving flag set to an on-value but not present at all in the eval job
    env means the eval measures that dimension as if OFF -> the report comparison against prod is
    vacuous for it. We only flag ABSENT keys (not value mismatches): some divergence is legitimate
    (e.g. session-table / provider env), so the caller WARNs, never hard-fails.
    """
    return sorted(
        k for k, v in serving_env.items()
        if k.startswith("GRAPHRAG_") and _is_flag_on(v) and k not in job_env
    )


def _fetch_serving_graphrag_env(region: str, family: str = SERVING_FAMILY) -> dict[str, str]:
    """Latest ACTIVE task definition's GRAPHRAG_* env for `family`. Best-effort: any AWS error -> {}
    (the parity guard is advisory, so a describe failure must never block a submission)."""
    try:
        ecs = boto3.client("ecs", region_name=region)
        td = ecs.describe_task_definition(taskDefinition=family)["taskDefinition"]
        return _graphrag_env_from_taskdef(td)
    except Exception as exc:  # noqa: BLE001 - advisory guard, degrade gracefully
        logger.warning("serving-parity check skipped: could not describe task def %s (%s)", family, exc)
        return {}


def _emit_parity_warning(region: str, job_env: dict[str, str]) -> None:
    """Fetch the live serving taskdef and print an ASCII WARNING for any serving-ON GRAPHRAG_* flag
    absent from the eval job env. Advisory only (never raises, never hard-fails)."""
    serving_env = _fetch_serving_graphrag_env(region)
    if not serving_env:
        return
    missing = parity_warnings(serving_env, job_env)
    if missing:
        logger.warning("SERVING-PARITY WARNING: serving-ON GRAPHRAG_* flags ABSENT from this eval job env: %s",
                       "; ".join(f"{k}={serving_env[k]}" for k in missing))
        logger.warning("  -> the eval measures these dimensions as if OFF; add --env <FLAG>=<val> if the "
                       "comparison against prod should hold. (Some divergence is legitimate.)")


def build_command(*, queries: str | None, convos: str | None, model: str, judge: bool,
                  judge_model: str, k: int, workers: int | None = None,
                  via_orchestrator: bool = False, mode: str | None = None,
                  planner: str | None = None, only_ids: str | None = None) -> list[str]:
    """The container command (the image ENTRYPOINT is `python`, so this is the arg list to it)."""
    cmd = ["-m", "leviathan.graphrag.eval", "--run", "--model", model, "--k", str(k)]
    if convos:
        if only_ids:
            # --only-ids names ROWS of a queries deck; a convo deck has none. The eval CLI refuses the
            # same pairing -- refuse HERE too, before a job is submitted with a flag the container will
            # reject after it has already been billed for the container start.
            raise ValueError("--only-ids has no meaning with --convos")
        cmd += ["--convos", convos]
    else:
        cmd += ["--queries", queries]
        if only_ids:
            # D-HP B2 / plan E.6: a pre-registered NAMED SUBSET of a deck (G1's frozen 7-row hungry split)
            # runs through this flag. Forwarded verbatim; the container hard-errors on an unknown id, so a
            # typo fails the submission's job rather than quietly shrinking the population.
            cmd += ["--only-ids", only_ids]
    if via_orchestrator:
        # The intent-branch serving path (numbers_only/reasoning/hybrid) — REQUIRED for any run whose
        # intent accuracy is compared to the 22/30 baseline; plain answer() never sets out.intent
        # (P7-P0.1: the A1 baseline arm silently measured the one-hop path without this).
        cmd += ["--via-orchestrator"]
    if judge:
        cmd += ["--judge", "--judge-model", judge_model]
    if workers is not None:
        # e.g. --workers 1 for Bedrock-rerank arms: the Cohere Rerank quota is 3 req/min and each TURN is one
        # coalesced request, so concurrent turns (default 4 workers) would throttle -> silent bge contamination.
        cmd += ["--workers", str(workers)]
    if mode:
        # D-MW-16: the tier/preset arm lever, forwarded to eval --mode. Until this existed, a mode arm in
        # the cloud needed a HAND-REGISTERED job definition carrying the flag in its baked command, so an
        # arm's identity lived outside the submit record -- the gate could not prove which preset it ran.
        # The serving-side GRAPHRAG_MODES allowlist still decides whether the mode is HONORED (pass it via
        # --env GRAPHRAG_MODES=max,max_c0); the request is recorded either way, per row, in mode_decision.
        cmd += ["--mode", mode]
    if planner:
        cmd += ["--planner", planner]
    return cmd


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    load_env()

    env = os.environ.get("LEVIATHAN_ENV", "dev")
    project = os.environ.get("LEVIATHAN_PROJECT", "leviathan")
    job_queue = f"{project}-{env}-queue"
    job_definition = f"{project}-{env}-evidence-build"        # reuse: same image + EVIDENCE_S3 env + Anthropic secret

    ap = argparse.ArgumentParser(description="Submit the GraphRAG v2 eval as a Fargate Batch job")
    ap.add_argument("--queries", default="configs/graphrag/eval_queries_v2.yaml",
                    help="queries yaml (path INSIDE the image; baked from configs/graphrag/)")
    ap.add_argument("--only-ids", default=None,
                    help="comma-separated row ids: run ONLY those rows of --queries, in deck order "
                         "(forwarded to eval --only-ids). The mechanism a PRE-REGISTERED NAMED SUBSET "
                         "executes through -- e.g. D-HP G1's frozen 7-row hungry split of "
                         "eval_queries_shape_esc_v1.yaml. An id absent from the deck hard-errors inside "
                         "the container before any spend; the artifact keeps the deck's stem as eval_set "
                         "and records the ids that ran in its top-level row_filter key")
    ap.add_argument("--convos", default=None,
                    help="conversations yaml (multi-turn session eval) — overrides --queries when set")
    ap.add_argument("--model", default="claude-sonnet-4-6", help="serving model (validated ~= Opus at ~1/5 cost)")
    ap.add_argument("--judge", action="store_true", help="add the independent Opus judge (usefulness/grounding)")
    ap.add_argument("--judge-model", default="claude-opus-4-8")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--via-orchestrator", action="store_true",
                    help="route queries through the full intent branch (orchestrator.respond) — the "
                         "serving path; required for intent-accuracy baselines (22/30 lives here)")
    ap.add_argument("--workers", type=int, default=None,
                    help="eval concurrency inside the container (forwarded to eval --workers). FAST-EVAL "
                         "RECIPE: pair --workers 4 with --env GRAPHRAG_PROVIDER=bedrock so LLM calls use the "
                         "Bedrock quota lane (the Anthropic API throttles a serial eval into 40-50min "
                         "single-turn stalls, worse now serving also runs on Anthropic). Eval rerank defaults "
                         "to LOCAL bge (rankers._rerank_backend), so workers is NOT capped by the Cohere "
                         "3-req/min quota — that cap ONLY bites if you also pass GRAPHRAG_RERANK_BACKEND=bedrock, "
                         "in which case drop to --workers 1.")
    ap.add_argument("--mode", default=None,
                    help="reasoning mode REQUESTED on every turn (quick|standard|deep|max|max_c0), "
                         "forwarded to eval --mode. Requires --via-orchestrator. Pair with "
                         "--env GRAPHRAG_MODES=<allowlist> or the mode is requested but never honored")
    ap.add_argument("--planner", default=None, choices=["l2", "onehop"],
                    help="forwarded to eval --planner: 'onehop' forces the single-contract baseline arm")
    ap.add_argument("--memory", type=int, default=32768, help="MiB; legal Fargate value for 8 vCPU (16/20/24/28/32 GB)")
    ap.add_argument("--vcpu", type=int, default=8)
    ap.add_argument("--queue", default=None,
                    help="override the Batch queue (e.g. leviathan-dev-queue-ondemand to dodge Spot interrupts)")
    ap.add_argument("--env", action="append", default=[], metavar="KEY=VAL", dest="env_overrides",
                    help="extra container env var (repeatable) — e.g. GRAPHRAG_PROVIDER=bedrock for the "
                         "Bedrock-serving arm, GRAPHRAG_TIMELINE=on for a timeline arm")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if args.queue:
        job_queue = args.queue                               # e.g. on-demand so a long eval isn't Spot-reclaimed

    aws_region = get_required_env("AWS_REGION")
    command = build_command(queries=args.queries, convos=args.convos, model=args.model,
                            judge=args.judge, judge_model=args.judge_model, k=args.k, workers=args.workers,
                            via_orchestrator=args.via_orchestrator, mode=args.mode, planner=args.planner,
                            only_ids=args.only_ids)
    overrides: dict = {
        "command": command,
        "resourceRequirements": [
            {"type": "VCPU", "value": str(args.vcpu)},
            {"type": "MEMORY", "value": str(args.memory)},
        ],
    }
    env_pairs = [p.split("=", 1) for p in args.env_overrides if "=" in p]
    # Job env = the DEFAULT serving-parity flags, then the user --env overrides on top (user wins).
    job_env: dict[str, str] = dict(DEFAULT_JOB_ENV)
    job_env.update({k: v for k, v in env_pairs})
    overrides["environment"] = [{"name": k, "value": v} for k, v in job_env.items()]
    stem = Path(args.convos or args.queries).stem
    job_name = f"eval-{stem.replace('_', '-')}-{args.model.replace('.', '-')}"
    if args.mode:
        # the two P3 arms are the SAME deck at the SAME model and differ only by mode -- without this the
        # two submissions are indistinguishable in the Batch console
        job_name += f"-{args.mode.replace('_', '-')}"
    if args.only_ids:
        # same argument as --mode above: a NAMED-SUBSET arm and a whole-deck arm are the same deck, model
        # and mode, so without this they are indistinguishable in the Batch console. The COUNT is the
        # distinguishing token (the ids themselves are in the run record and in the artifact's row_filter).
        job_name += f"-rows{len([t for t in args.only_ids.split(',') if t.strip()])}"
    for k, v in env_pairs:
        job_name += f"-{v.lower()[:12]}" if k == "GRAPHRAG_PROVIDER" else ""

    logger.info("queue=%s  job_def=%s  mem=%dMiB vcpu=%d", job_queue, job_definition, args.memory, args.vcpu)
    logger.info("command: python %s", " ".join(command))
    if env_pairs:
        logger.info("env overrides: %s", ", ".join(f"{k}={v}" for k, v in env_pairs))
    logger.info("report will persist to  s3://.../graphrag_evidence/eval/report_%s_%s.md", args.model, stem)

    # Serving-parity guard: WARN (never fail) if any serving-ON GRAPHRAG_* flag is missing from this
    # job env, so an eval dimension isn't silently measured as OFF vs prod. Runs on dry-run too.
    _emit_parity_warning(aws_region, job_env)

    if args.dry_run:
        logger.info("[DRY RUN] would submit job_name=%s (nothing submitted).", job_name)
        return

    client = boto3.client("batch", region_name=aws_region)
    resp = client.submit_job(jobName=job_name, jobQueue=job_queue, jobDefinition=job_definition,
                             containerOverrides=overrides)
    logger.info("Submitted  job_name=%s  job_id=%s", job_name, resp["jobId"])

    run_id = utc_now_iso().replace(":", "-")
    write_run_record(Path("data/batch_runs") / f"eval_{run_id}.json",
                     {"run_id": run_id, "job_name": job_name, "job_id": resp["jobId"],
                      "queries": args.convos or args.queries, "model": args.model, "judge": args.judge,
                      "mode": args.mode, "planner": args.planner, "only_ids": args.only_ids,
                      "env_overrides": dict(env_pairs)})


if __name__ == "__main__":
    main()
