"""One-off: seed the S3 HuggingFace model cache (Stage 5.3 R1).

Optional — the serving task self-seeds on first startup via hf_cache.ensure(). Run this only to pre-seed S3
BEFORE a deploy so even the first task syncs (~30 s) instead of paying the one-time ~327 s HF download.

Runs on the embedder image (has sentence-transformers + boto3); the serving/Batch task role has S3 RW to the
data-lake bucket. In-region, ~minutes, cents. Idempotent — re-run to refresh after a model bump.

  # As a standalone ECS task (reuses the serving image + task role), command override:
  #   ["jobs/utils/populate_hf_s3_cache.py", "--uri", "s3://leviathan-dev-shahem-001/models/hf"]
  # Or locally with AWS creds + the [embed] extra:
  python jobs/utils/populate_hf_s3_cache.py --uri s3://leviathan-dev-shahem-001/models/hf
"""
from __future__ import annotations

import argparse

from leviathan.graphrag import hf_cache


def main() -> None:
    ap = argparse.ArgumentParser(description="Seed the S3 HF model cache (bge-m3 + bge-reranker-v2-m3).")
    ap.add_argument("--uri", default="s3://leviathan-dev-shahem-001/models/hf",
                    help="s3://<bucket>/<prefix> to upload the HF_HOME tree into.")
    args = ap.parse_args()
    print(f"[hf-cache] populating {args.uri} from HuggingFace ...", flush=True)
    res = hf_cache.populate(args.uri)
    print(f"[hf-cache] done: uploaded={res['uploaded']} home={res['home']}", flush=True)


if __name__ == "__main__":
    main()
