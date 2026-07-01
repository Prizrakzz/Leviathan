"""build_evidence Batch task (GraphRAG v2 WS-MS2) — cloud, multi-source, bge-m3 embeddings.

Per commodity NODE: sample the corpus SOURCE-AGNOSTICALLY (evidence.sample_keys) -> Bedrock-Haiku propositional
chunking (concurrent, ThreadPool) -> keep on-topic props -> bge-m3 embed (self-hosted in the leviathan_embedder
image, NOT Bedrock — there is no bge-m3 on Bedrock) -> write evidence/<node>.jsonl to S3 (EVIDENCE_S3). Mirrors
text_to_graphrag_task: argparse, Fargate, thread-local S3 clients. The LLM chunking is on-demand Bedrock Haiku
(AWS-native, IAM role only — no Anthropic key/secret, unlike the laptop evidence_batch path).

    python jobs/batch/build_evidence_task.py --nodes raw_sugar --n-docs 90        # one node
    python jobs/batch/build_evidence_task.py --nodes raw_sugar,cotton             # several (comma-sep)
    python jobs/batch/build_evidence_task.py --nodes all --n-docs 90              # every node
    python jobs/batch/build_evidence_task.py --nodes new                           # uncovered nodes only

AWS Batch invokes it with Ref:: parameter overrides (nodes / n_docs / workers). EVIDENCE_S3 + the bge-m3 cache
come from the job-def environment + the baked image. Exits non-zero on any node failure.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timezone

import boto3

from leviathan.common.config import load_env
from leviathan.graphrag import evidence as ev

logger = logging.getLogger("build_evidence_task")

_WORKERS = int(os.environ.get("EVIDENCE_WORKERS", "16"))


def _resolve(sel: str) -> list[str]:
    if sel == "all":
        return ev.all_nodes()
    if sel == "new":
        return ev.new_nodes()
    return list(dict.fromkeys(ev.node_for(n) for n in sel.split(",")))   # contract ids -> nodes, deduped


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s",
                        stream=sys.stderr)
    ap = argparse.ArgumentParser(description="Cloud evidence build (Bedrock-Haiku chunk + bge-m3 embed -> S3).")
    ap.add_argument("--nodes", default="all", help="contract/node id(s) comma-sep, 'all', or 'new'")
    ap.add_argument("--n-docs", type=int, default=90)
    ap.add_argument("--workers", type=int, default=_WORKERS)
    ap.add_argument("--backend", default=ev.DEFAULT_BACKEND)
    ap.add_argument("--aws-region", default=os.environ.get("AWS_REGION", "us-east-1"))
    ap.add_argument("--skip-existing", default="false",   # "true"/"false" so it threads through Batch Ref::
                    help="skip nodes already present in EVIDENCE_S3 — for resuming a partially-failed run "
                         "without re-billing Haiku (default false = full overwrite)")
    ap.add_argument("--drivers", default="true",          # WS-MS6: capture cross-cutting driver/cascade props
                    help="'true' routes driver/cascade props (B40, freight, FX, El Nino) into driver slices "
                         "FREE from the same pass; 'false' = commodity slices only")
    ap.add_argument("--chunk-provider", default="bedrock",   # 'anthropic' bills Haiku to the Anthropic account
                    help="'bedrock' (task IAM role) or 'anthropic' (Anthropic API, ANTHROPIC_API_KEY from secret)")
    args = ap.parse_args()

    load_env()
    if not ev._evid_s3():                                 # never write the IP slices to a container-local disk
        raise SystemExit("EVIDENCE_S3 not set — refusing to write evidence locally inside a Batch job.")

    nodes = _resolve(args.nodes)
    if str(args.skip_existing).lower() == "true":         # resume mode: don't re-pay for nodes already in S3
        covered = ev.covered_nodes()
        skip = [n for n in nodes if n in covered]
        nodes = [n for n in nodes if n not in covered]
        if skip:
            logger.info("skip-existing: %d node(s) already in EVIDENCE_S3, skipping: %s", len(skip), skip)
    logger.info("build_evidence  nodes=%s  n_docs=%d  workers=%d  backend=%s  out=%s",
                nodes, args.n_docs, args.workers, args.backend, ev._evid_s3())
    if not nodes:
        logger.info("nothing to build (all requested nodes already covered).")
        return

    s3 = boto3.client("s3", region_name=args.aws_region)
    provider = str(args.chunk_provider).lower()
    bedrock = ev._bedrock() if provider == "bedrock" else None   # shared bedrock-runtime client (thread-safe)
    anthropic_client = None
    if provider == "anthropic":                          # Haiku billed to the Anthropic account (prepaid credit)
        import anthropic
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise SystemExit("--chunk-provider anthropic but ANTHROPIC_API_KEY not set (Secrets Manager injection).")
        anthropic_client = anthropic.Anthropic(api_key=key, max_retries=8)   # SDK backoff for rate limits
    capture_drivers = str(args.drivers).lower() == "true"
    driver_sink: dict = {} if capture_drivers else None   # accumulated ACROSS nodes -> run drivers in ONE job
    logger.info("chunk provider=%s", provider)
    start = datetime.now(timezone.utc)
    total, errors = 0, 0
    for node in nodes:
        try:
            n = ev.build_index(s3, node=node, aliases=ev._aliases(node), year_windows=ev.windows_for(node),
                               n_docs=ev.n_docs_for(node, args.n_docs), backend=args.backend, bedrock=bedrock,
                               max_props=None, workers=args.workers, aws_region=args.aws_region,
                               driver_sink=driver_sink, provider=provider, anthropic_client=anthropic_client)
            logger.info("  %s: %d dated props -> evidence/%s.jsonl", node, n, node)
            total += n
        except Exception as exc:                          # one bad node shouldn't abandon the rest of the group
            logger.exception("  %s FAILED: %s", node, exc)
            errors += 1

    dtotal = 0
    if capture_drivers and driver_sink:                   # embed + write the cross-cutting driver slices once
        dtotal = ev.write_driver_slices(driver_sink, backend=args.backend, bedrock=bedrock)
        logger.info("  drivers: %d props across %d slices -> evidence/drivers/*.jsonl", dtotal, len(driver_sink))

    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    logger.info("Done  nodes=%d  commodity_props=%d  driver_props=%d  errors=%d  elapsed=%.1fs",
                len(nodes), total, dtotal, errors, elapsed)
    if errors:
        raise RuntimeError(f"build_evidence finished with {errors} failed node(s). Check CloudWatch logs.")


if __name__ == "__main__":
    main()
