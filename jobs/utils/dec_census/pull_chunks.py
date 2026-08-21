"""Pull the whole graphrag_evidence/chunks/ prop cache to one local jsonl (text + source_key only).

Read-only: 1 LIST + N GETs. No writes to S3. Output ~50 MB. Resumable: skips keys already in the
progress file.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import boto3
from botocore.config import Config

BUCKET = "leviathan-dev-shahem-001"
PREFIX = "graphrag_evidence/chunks/"
OUT = sys.argv[1] if len(sys.argv) > 1 else "chunk_cache_props.jsonl"
DONE = OUT + ".done"

_cfg = Config(max_pool_connections=64, retries={"max_attempts": 10, "mode": "adaptive"},
              connect_timeout=15, read_timeout=60)
s3 = boto3.client("s3", config=_cfg)

keys = [o["Key"] for page in s3.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=PREFIX)
        for o in page.get("Contents", []) if o["Key"].endswith(".jsonl")]
done = set()
if os.path.exists(DONE):
    done = {ln.strip() for ln in open(DONE, encoding="utf-8") if ln.strip()}
todo = [k for k in keys if k not in done]
print(f"objects={len(keys)} done={len(done)} todo={len(todo)}")

lock = threading.Lock()
fh = open(OUT, "a", encoding="utf-8")
dh = open(DONE, "a", encoding="utf-8")
n = [0]


def _get(k: str):
    for attempt in range(6):
        try:
            body = s3.get_object(Bucket=BUCKET, Key=k)["Body"].read().decode("utf-8")
            break
        except Exception as exc:  # noqa: BLE001
            if attempt == 5:
                print(f"  GIVE UP {k}: {exc}")
                return
            time.sleep(1.5 * (attempt + 1))
    out = []
    for line in body.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        out.append({"t": r.get("text") or "", "s": r.get("source_key") or "",
                    "d": r.get("date") or "", "src": r.get("source") or ""})
    with lock:
        for r in out:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        dh.write(k + "\n")
        n[0] += len(out)
        if len(n) and n[0] % 20000 < len(out):
            print(f"  ~{n[0]} props")


with ThreadPoolExecutor(max_workers=24) as ex:
    list(ex.map(_get, todo))
fh.close()
dh.close()
print(f"DONE new_props={n[0]} -> {OUT}")
