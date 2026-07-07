"""Submit the evidence->pg mirror loader (jobs/utils/load_pg_evidence.py) as a Fargate Batch job.

Same reuse as submit_batch_load_numbers_pg: the evidence-build job-def bakes src/ + configs/, its execution
role injects EVIDENCE_PG_DSN, and RDS is only reachable in-VPC — so this loader's home is Batch, not the
laptop. The loader reads the flat-file slices and upserts their INLINE bge-m3 vectors into pgvector (never
re-embeds); S3 stays the source of truth.

The two overrides that make this a BLUE-GREEN primitive:
  * `--table evidence_props_shadow` forwards to `load_pg_evidence.py --table` (the W0.3 shadow-table param) so
    a load lands in a shadow table the live serving path doesn't read until the transactional rename swap.
  * `--evidence-s3 <shadow prefix>` overrides EVIDENCE_S3 so the shadow table is filled FROM the shadow S3
    slices — load a shadow prefix INTO a shadow table in one job, verify row counts, then flip.
Omit both and the job loads the live slices into the live table exactly as a laptop run would.

    python jobs/submit/submit_batch_load_pg_evidence.py --all --dry-run
    python jobs/submit/submit_batch_load_pg_evidence.py --nodes corn soybeans
    python jobs/submit/submit_batch_load_pg_evidence.py --all --table evidence_props_shadow \
        --evidence-s3 s3://bkt/graphrag_evidence/shadow_e1b
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

logger = get_logger("submit_load_pg_evidence")


def build_command(*, nodes: list[str] | None, load_all: bool, table: str | None,
                  workers: int | None = None) -> list[str]:
    """The container command (the image ENTRYPOINT is `python`, so this is the arg list to it).

    load_pg_evidence.py is a script path (not a -m module) exactly like load_pg_numbers.py. Exactly one of
    `--nodes`/`--all` selects the slices; `--table` is forwarded only when set (opt-in — omitting it keeps the
    loader's default `evidence_props` target, so default behaviour is byte-identical to a bare laptop run).
    """
    cmd = ["jobs/utils/load_pg_evidence.py"]
    if load_all:
        cmd += ["--all"]
    elif nodes:
        cmd += ["--nodes", *nodes]
    if table:
        cmd += ["--table", table]                            # W0.3 shadow-table param; absent => default evidence_props
    if workers is not None:
        cmd += ["--workers", str(workers)]
    return cmd


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    load_env()

    env = os.environ.get("LEVIATHAN_ENV", "dev")
    project = os.environ.get("LEVIATHAN_PROJECT", "leviathan")
    job_queue = f"{project}-{env}-queue-ondemand"            # don't let Spot reclaim a mid-COPY loader
    job_definition = f"{project}-{env}-evidence-build"       # image + DSN secret + bge-m3 backend on the role

    ap = argparse.ArgumentParser(description="Submit the evidence->pg mirror loader as a Batch job")
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument("--all", action="store_true", dest="load_all",
                     help="load all local slices + S3 driver slices (the S3 store is the production source)")
    grp.add_argument("--nodes", nargs="+", default=None, metavar="NODE",
                     help="specific slice names (e.g. corn soybeans drivers/el_nino)")
    ap.add_argument("--table", default=None,
                    help="target pg table (forwarded to load_pg_evidence --table); e.g. evidence_props_shadow "
                         "for a blue-green load. Omit => the loader's default evidence_props.")
    ap.add_argument("--evidence-s3", default=None, metavar="S3_URI",
                    help="optional EVIDENCE_S3 override — load FROM a shadow prefix (pairs with --table for a "
                         "shadow-prefix->shadow-table load). Omit => the job-def's live prefix.")
    ap.add_argument("--workers", type=int, default=None, help="parallel slice loads (forwarded; loader default 8)")
    ap.add_argument("--vcpu", type=int, default=2)
    ap.add_argument("--memory", type=int, default=8192)
    ap.add_argument("--queue", default=None, help="override the Batch queue (default: on-demand)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if args.queue:
        job_queue = args.queue

    aws_region = get_required_env("AWS_REGION")
    command = build_command(nodes=args.nodes, load_all=args.load_all, table=args.table, workers=args.workers)
    overrides: dict = {
        "command": command,
        "resourceRequirements": [
            {"type": "VCPU", "value": str(args.vcpu)},
            {"type": "MEMORY", "value": str(args.memory)},
        ],
    }
    if args.evidence_s3:                                     # shadow-prefix load: read the slices from elsewhere
        overrides["environment"] = [{"name": "EVIDENCE_S3", "value": args.evidence_s3}]

    scope = "all" if args.load_all else (args.nodes[0].replace("/", "-").replace("_", "-")[:40] if args.nodes else "none")
    job_name = "evidence-pg-load-" + scope + (f"-{args.table.replace('_', '-')[:40]}" if args.table else "")

    logger.info("queue=%s  job_def=%s  table=%s", job_queue, job_definition, args.table or "evidence_props")
    logger.info("command: python %s", " ".join(command))
    if args.evidence_s3:
        logger.info("env override: EVIDENCE_S3=%s", args.evidence_s3)
    if args.dry_run:
        logger.info("[DRY RUN] would submit job_name=%s (nothing submitted).", job_name)
        return

    client = boto3.client("batch", region_name=aws_region)
    resp = client.submit_job(jobName=job_name, jobQueue=job_queue, jobDefinition=job_definition,
                             containerOverrides=overrides)
    logger.info("Submitted  job_name=%s  job_id=%s", job_name, resp["jobId"])

    run_id = utc_now_iso().replace(":", "-")
    write_run_record(Path("data/batch_runs") / f"evidence_pg_load_{run_id}.json",
                     {"run_id": run_id, "job_name": job_name, "job_id": resp["jobId"],
                      "nodes": args.nodes, "all": args.load_all, "table": args.table,
                      "evidence_s3": args.evidence_s3})


if __name__ == "__main__":
    main()
