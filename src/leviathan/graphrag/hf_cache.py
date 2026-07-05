"""S3-backed HuggingFace model cache — cold-start hardening (Stage 5.3 R1 + follow-up).

The serving/embedder image ships model-less (docker/leviathan_embedder/Dockerfile): bge-m3 (the query hot-path
embedder) + bge-reranker-v2-m3 (the bedrock-rerank fallback) download from HuggingFace into HF_HOME (/opt/hf)
on first use. This module mirrors that cache to/from S3 so a replacement task syncs the models in-region
instead of pulling them from HuggingFace. It is SELF-SEEDING via `ensure()`: the first task after the cache is
enabled downloads from HF once (behind the still-serving old task) and uploads to S3; every task after syncs.

Two levers keep the sync fast (the initial 5.3 cache was 13.7 GB / ~100 s because HF ships every weight format):
  * PRUNE — `_download_models` uses `snapshot_download(..., ignore_patterns=...)` to fetch ONLY the safetensors
    format sentence-transformers loads (drops pytorch_model.bin / onnx / openvino), ~4.5 GB.
  * PARALLEL — up/download run over a ThreadPoolExecutor (`GRAPHRAG_HF_S3_WORKERS`, default 16).
Callers should set HF_HUB_OFFLINE=1 after a successful ensure() so the model LOAD is cache-only and never
re-fetches the pruned formats from HF (server.py does this).

  ensure(uri):   startup entry point — sync from S3 if seeded, else seed S3 from HF. Leaves HF_HOME ready.
  sync(uri):     mirror s3://bucket/prefix/ -> HF_HOME (skips when the local cache already looks populated).
  populate(uri): download the (pruned) models then upload the HF_HOME tree to s3://bucket/prefix/.

Every S3 op is best-effort at the call site (the server startup try-guards this); a cache miss degrades to the
image's existing HF-download path, never to a broken task.
"""
from __future__ import annotations

import os
from pathlib import Path

# The models the serving path can load. bge-m3 is always on the query hot-path; the reranker is only the
# bedrock-rerank fallback, but it is cached too so a Cohere outage can't trigger a mid-incident download.
MODELS = ("BAAI/bge-m3", "BAAI/bge-reranker-v2-m3")

# Weight formats HF ships that sentence-transformers/CrossEncoder never load with the torch backend — excluded
# from the cache so it stays ~4.5 GB (both models keep model.safetensors + all config/tokenizer files).
_IGNORE_PATTERNS = ["*.onnx", "onnx/*", "*.onnx_data", "openvino/*", "openvino_model*",
                    "pytorch_model.bin", "tf_model.h5", "*.ckpt", "flax_model.msgpack", "*.pth"]


def _hf_home() -> Path:
    return Path(os.environ.get("HF_HOME") or os.environ.get("SENTENCE_TRANSFORMERS_HOME") or "/opt/hf")


def _s3():
    import boto3
    return boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-east-1"))


def _parse(uri: str) -> tuple[str, str]:
    """s3://bucket/prefix -> (bucket, prefix); prefix has no leading/trailing slash."""
    body = uri[5:] if uri.startswith("s3://") else uri
    bucket, _, prefix = body.partition("/")
    return bucket, prefix.strip("/")


def _workers() -> int:
    try:
        return max(1, int(os.environ.get("GRAPHRAG_HF_S3_WORKERS", "16")))
    except ValueError:
        return 16


def _run_parallel(fn, items) -> int:
    """Apply fn to each item over a bounded thread pool (S3 up/download is I/O-bound; a shared boto3 client is
    thread-safe). Falls back to serial for <=1 worker or a single item. Returns the count processed."""
    items = list(items)
    if not items:
        return 0
    n = min(_workers(), len(items))
    if n <= 1:
        for it in items:
            fn(it)
        return len(items)
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=n) as ex:
        list(ex.map(fn, items))
    return len(items)


def is_populated(uri: str, *, s3=None) -> bool:
    """True when s3://bucket/prefix/ already holds at least one object (the cache has been seeded)."""
    bucket, prefix = _parse(uri)
    s3 = s3 or _s3()
    resp = s3.list_objects_v2(Bucket=bucket, Prefix=f"{prefix}/", MaxKeys=1)
    return int(resp.get("KeyCount", 0)) > 0


def _local_looks_populated() -> bool:
    """Heuristic: HF_HOME already holds a hub snapshot dir for each model (avoids a redundant re-download)."""
    home = _hf_home()
    for m in MODELS:
        tag = "models--" + m.replace("/", "--")
        if not (home / "hub" / tag).exists() and not (home / tag).exists():
            return False
    return True


def _download_models() -> None:
    """Fetch ONLY the safetensors format each model loads into HF_HOME (the image is ONLINE). snapshot_download
    populates the same hub snapshot path SentenceTransformer/CrossEncoder read, so the later load is a cache hit."""
    from huggingface_hub import snapshot_download
    for repo in MODELS:
        snapshot_download(repo_id=repo, ignore_patterns=_IGNORE_PATTERNS)


def populate(uri: str, *, s3=None) -> dict:
    """Download the (pruned) models (HF -> HF_HOME) then upload the whole HF_HOME tree to s3://bucket/prefix/,
    in parallel. Idempotent — re-run to refresh after a model bump. upload_file auto-multiparts the shards."""
    bucket, prefix = _parse(uri)
    s3 = s3 or _s3()
    _download_models()
    home = _hf_home()
    files = [p for p in home.rglob("*") if p.is_file()]

    def _up(path: Path) -> None:
        rel = path.relative_to(home).as_posix()
        s3.upload_file(str(path), bucket, f"{prefix}/{rel}")

    uploaded = _run_parallel(_up, files)
    return {"action": "populate", "uploaded": uploaded, "home": str(home), "uri": uri}


def sync(uri: str, *, force: bool = False, s3=None) -> dict:
    """Mirror s3://bucket/prefix/ -> HF_HOME in parallel. Skips (no-op) when the local cache already looks
    populated, unless force=True."""
    bucket, prefix = _parse(uri)
    home = _hf_home()
    home.mkdir(parents=True, exist_ok=True)
    if not force and _local_looks_populated():
        return {"action": "sync", "downloaded": 0, "skipped": True, "home": str(home)}
    s3 = s3 or _s3()
    keys: list[tuple[str, str]] = []
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=f"{prefix}/"):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            rel = key[len(prefix) + 1:]                        # strip "prefix/"
            if rel:
                keys.append((key, rel))

    def _dl(item: tuple[str, str]) -> None:
        key, rel = item
        dest = home / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        s3.download_file(bucket, key, str(dest))

    downloaded = _run_parallel(_dl, keys)
    return {"action": "sync", "downloaded": downloaded, "skipped": False, "home": str(home), "uri": uri}


def ensure(uri: str, *, s3=None) -> dict:
    """Startup entry point: leave HF_HOME populated with the least work. If S3 is already seeded, sync from it
    (in-region, parallel); otherwise seed S3 from HuggingFace once (paid behind the still-serving old task on
    the first deploy of a new cache prefix)."""
    s3 = s3 or _s3()
    if is_populated(uri, s3=s3):
        return sync(uri, s3=s3)
    out = populate(uri, s3=s3)
    out["seeded"] = True
    return out
