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


def build_command(*, queries: str | None, convos: str | None, model: str, judge: bool,
                  judge_model: str, k: int) -> list[str]:
    """The container command (the image ENTRYPOINT is `python`, so this is the arg list to it)."""
    cmd = ["-m", "leviathan.graphrag.eval", "--run", "--model", model, "--k", str(k)]
    if convos:
        cmd += ["--convos", convos]
    else:
        cmd += ["--queries", queries]
    if judge:
        cmd += ["--judge", "--judge-model", judge_model]
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
    ap.add_argument("--convos", default=None,
                    help="conversations yaml (multi-turn session eval) — overrides --queries when set")
    ap.add_argument("--model", default="claude-sonnet-4-6", help="serving model (validated ~= Opus at ~1/5 cost)")
    ap.add_argument("--judge", action="store_true", help="add the independent Opus judge (usefulness/grounding)")
    ap.add_argument("--judge-model", default="claude-opus-4-8")
    ap.add_argument("--k", type=int, default=5)
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
                            judge=args.judge, judge_model=args.judge_model, k=args.k)
    overrides: dict = {
        "command": command,
        "resourceRequirements": [
            {"type": "VCPU", "value": str(args.vcpu)},
            {"type": "MEMORY", "value": str(args.memory)},
        ],
    }
    env_pairs = [p.split("=", 1) for p in args.env_overrides if "=" in p]
    if env_pairs:
        overrides["environment"] = [{"name": k, "value": v} for k, v in env_pairs]
    stem = Path(args.convos or args.queries).stem
    job_name = f"eval-{stem.replace('_', '-')}-{args.model.replace('.', '-')}"
    for k, v in env_pairs:
        job_name += f"-{v.lower()[:12]}" if k == "GRAPHRAG_PROVIDER" else ""

    logger.info("queue=%s  job_def=%s  mem=%dMiB vcpu=%d", job_queue, job_definition, args.memory, args.vcpu)
    logger.info("command: python %s", " ".join(command))
    if env_pairs:
        logger.info("env overrides: %s", ", ".join(f"{k}={v}" for k, v in env_pairs))
    logger.info("report will persist to  s3://.../graphrag_evidence/eval/report_%s_%s.md", args.model, stem)

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
                      "env_overrides": dict(env_pairs)})


if __name__ == "__main__":
    main()
