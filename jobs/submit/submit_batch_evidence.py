"""Submit build_evidence Batch tasks (GraphRAG v2 WS-MS2 / WS-MS4).

Splits the target nodes into balanced groups (default 6 per job) and submits one Fargate job per group to the
shared queue — so the 24 nodes build across a few parallel tasks instead of one long serial run, while still
amortizing the bge-m3 model load + image pull over several nodes per task. The node list is resolved LOCALLY
(reads the gitignored commodity_hierarchy + evidence_windows), but each Batch task re-resolves its own group.

Usage
-----
    # Dry run — show the groups + jobs that would be submitted (free)
    python jobs/submit/submit_batch_evidence.py --nodes all --dry-run

    # One node, smoke test (pair with `register_evidence_jobdef` first)
    python jobs/submit/submit_batch_evidence.py --nodes raw_sugar

    # Full multi-source rebuild of every node (gated: Bedrock-Haiku billed)
    python jobs/submit/submit_batch_evidence.py --nodes all

    # Only the uncovered nodes
    python jobs/submit/submit_batch_evidence.py --nodes new
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
from leviathan.graphrag import evidence as ev
from leviathan.storage.metadata import utc_now_iso

logger = get_logger("submit_batch_evidence")


def _resolve(sel: str) -> list[str]:
    if sel == "all":
        return ev.all_nodes()
    if sel == "new":
        return ev.new_nodes()
    return list(dict.fromkeys(ev.node_for(n) for n in sel.split(",")))   # contract ids -> nodes, deduped


def _groups(nodes: list[str], size: int) -> list[list[str]]:
    return [nodes[i:i + size] for i in range(0, len(nodes), size)]


def submit_groups(groups: list[list[str]], *, job_queue: str, job_definition: str, aws_region: str,
                  n_docs: int, workers: int, dry_run: bool) -> list[dict]:
    client = boto3.client("batch", region_name=aws_region)
    submitted: list[dict] = []
    for grp in groups:
        job_name = f"evidence-{grp[0].replace('_', '-')}-{len(grp)}"
        parameters = {"nodes": ",".join(grp), "n_docs": str(n_docs), "workers": str(workers)}
        if dry_run:
            logger.info("[DRY RUN] Would submit: %s  nodes=%s", job_name, parameters["nodes"])
            submitted.append({"job_name": job_name, "job_id": None, "nodes": grp})
            continue
        resp = client.submit_job(jobName=job_name, jobQueue=job_queue,
                                 jobDefinition=job_definition, parameters=parameters)
        logger.info("Submitted  job_name=%s  job_id=%s  nodes=%s", job_name, resp["jobId"], parameters["nodes"])
        submitted.append({"job_name": job_name, "job_id": resp["jobId"], "nodes": grp})
    return submitted


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    load_env()

    env = os.environ.get("LEVIATHAN_ENV", "dev")
    project = os.environ.get("LEVIATHAN_PROJECT", "leviathan")
    job_queue = f"{project}-{env}-queue"
    job_definition = f"{project}-{env}-evidence-build"

    ap = argparse.ArgumentParser(description="Submit build_evidence Batch Fargate tasks")
    ap.add_argument("--nodes", default="all", help="'all' | 'new' | comma-separated node/contract ids")
    ap.add_argument("--n-docs", type=int, default=90)
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--group-size", type=int, default=6, help="nodes per Batch job (parallelism vs startup cost)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    aws_region = get_required_env("AWS_REGION")
    nodes = _resolve(args.nodes)
    if not nodes:
        logger.warning("No nodes to build for --nodes=%s (all covered?).", args.nodes)
        return
    groups = _groups(nodes, args.group_size)

    logger.info("Submitting %d node(s) in %d job(s)  queue=%s  job_def=%s  n_docs=%d  workers=%d",
                len(nodes), len(groups), job_queue, job_definition, args.n_docs, args.workers)

    submitted = submit_groups(groups, job_queue=job_queue, job_definition=job_definition, aws_region=aws_region,
                              n_docs=args.n_docs, workers=args.workers, dry_run=args.dry_run)

    if not args.dry_run:
        run_id = utc_now_iso().replace(":", "-")
        write_run_record(Path("data/batch_runs") / f"build_evidence_{run_id}.json",
                         {"run_id": run_id, "job_count": len(submitted), "jobs": submitted})
        logger.info("All %d job(s) submitted.", len(submitted))
    else:
        logger.info("[DRY RUN] %d job(s) over %d node(s) would be submitted.", len(groups), len(nodes))


if __name__ == "__main__":
    main()
