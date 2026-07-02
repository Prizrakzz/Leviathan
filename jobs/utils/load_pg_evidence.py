"""Backfill the pgvector evidence store from the flat-file slices (S3 or local) — REUSING inline vectors.

One-time / re-runnable (idempotent upserts on the content id). Never re-chunks, never re-embeds: the slices
already carry their bge-m3 vectors. S3 stays the source of truth; the pg table is a disposable derived index.

    python jobs/utils/load_pg_evidence.py --nodes corn soybeans          # specific slices
    python jobs/utils/load_pg_evidence.py --all                          # every local slice + S3 driver slices
    (EVIDENCE_PG_DSN must point at the target Postgres; EVIDENCE_S3 enables the drivers/ listing + S3 reads)
"""
from __future__ import annotations

import argparse
import sys

from leviathan.common import config

config.load_env()

from leviathan.graphrag import evidence as ev  # noqa: E402
from leviathan.graphrag import extract as ex  # noqa: E402
from leviathan.graphrag import pgstore  # noqa: E402


def local_nodes() -> list[str]:
    d = ex._CFG / "evidence"
    return sorted(p.stem for p in d.glob("*.jsonl")) if d.exists() else []


def s3_nodes() -> list[str]:
    """List ALL slices under EVIDENCE_S3: top-level commodity slices + drivers/<name>. (In the Fargate image
    configs/graphrag/evidence/ is dockerignored, so the S3 listing — the production store — is the real source.)"""
    uri = ev._evid_s3()
    if not uri:
        return []
    import boto3
    b, prefix = ev._parse_s3(uri.rstrip("/") + "/")
    out = []
    for page in boto3.client("s3").get_paginator("list_objects_v2").paginate(Bucket=b, Prefix=prefix):
        for o in page.get("Contents") or []:
            key = o["Key"][len(prefix):]
            if not key.endswith(".jsonl"):
                continue
            if key.startswith("_") or "/" in key.replace("drivers/", ""):     # skip _batches/ + other artifacts
                continue
            out.append(key[:-len(".jsonl")])
    return sorted(out)


def _load_one(node: str) -> tuple[str, int, str]:
    """Worker: read one slice (S3/local) + upsert on its OWN connection (psycopg conns aren't shared across
    threads). Returns (node, rows, err)."""
    import psycopg
    try:
        recs = ev.load_index(node)
        with psycopg.connect(pgstore.dsn(), autocommit=True) as conn:
            n = pgstore.upsert(node, recs, conn=conn)
        return node, n, ""
    except Exception as e:  # noqa: BLE001 — a missing slice must not kill the backfill
        return node, 0, str(e)[:120]


def main() -> int:
    ap = argparse.ArgumentParser(description="Backfill pgvector from the flat-file evidence slices (no re-embed).")
    ap.add_argument("--nodes", nargs="*", default=None, help="slice names (e.g. corn drivers/el_nino)")
    ap.add_argument("--all", action="store_true", help="all local slices + S3 driver slices")
    ap.add_argument("--workers", type=int, default=8, help="parallel slice loads (S3 read + upsert per worker)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    nodes = args.nodes or []
    if args.all:
        nodes = sorted(set(s3_nodes() or local_nodes()))       # S3 = the production store; local = dev fallback
    if not nodes:
        print("nothing to load (pass --nodes or --all)")
        return 1
    if args.dry_run:
        print(f"would load {len(nodes)} slices: {nodes[:8]}{' ...' if len(nodes) > 8 else ''}")
        return 0
    if not pgstore.dsn():
        print("EVIDENCE_PG_DSN not set")
        return 1

    pgstore.init_schema()
    total = 0
    from concurrent.futures import ThreadPoolExecutor, as_completed
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futs = [pool.submit(_load_one, n) for n in nodes]
        for f in as_completed(futs):
            node, n, err = f.result()
            if err:
                print(f"  SKIP {node}: {err}")
            else:
                total += n
                print(f"  {node}: {n} props")
    print(f"loaded {total} props across {len(nodes)} slices")
    return 0


if __name__ == "__main__":
    sys.exit(main())
