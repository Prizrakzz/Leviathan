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


def s3_driver_nodes() -> list[str]:
    """List drivers/<name> slices under EVIDENCE_S3 (they are not mirrored locally)."""
    uri = ev._evid_s3()
    if not uri:
        return []
    import boto3
    b, prefix = ev._parse_s3(uri.rstrip("/") + "/drivers/")
    out = []
    for page in boto3.client("s3").get_paginator("list_objects_v2").paginate(Bucket=b, Prefix=prefix):
        for o in page.get("Contents") or []:
            key = o["Key"]
            if key.endswith(".jsonl"):
                out.append("drivers/" + key.rsplit("/", 1)[-1][:-len(".jsonl")])
    return sorted(out)


def main() -> int:
    ap = argparse.ArgumentParser(description="Backfill pgvector from the flat-file evidence slices (no re-embed).")
    ap.add_argument("--nodes", nargs="*", default=None, help="slice names (e.g. corn drivers/el_nino)")
    ap.add_argument("--all", action="store_true", help="all local slices + S3 driver slices")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    nodes = args.nodes or []
    if args.all:
        nodes = local_nodes() + s3_driver_nodes()
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
    for node in nodes:
        try:
            recs = ev.load_index(node)
        except Exception as e:  # noqa: BLE001 — a missing slice must not kill the backfill
            print(f"  SKIP {node}: {str(e)[:120]}")
            continue
        n = pgstore.upsert(node, recs)
        total += n
        print(f"  {node}: {n} props")
    print(f"loaded {total} props across {len(nodes)} slices")
    return 0


if __name__ == "__main__":
    sys.exit(main())
