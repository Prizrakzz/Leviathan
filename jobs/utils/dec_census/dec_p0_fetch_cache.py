"""DEC-P0: (a) verify the 2026-08-03 rebuild manifest still describes the LIVE slice objects,
(b) download the whole chunks/ doc cache (2,815 objects, ~155 MB) to scratch."""
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import boto3

SCR = r'C:/Users/User/AppData/Local/Temp/claude/C--Users-User-Desktop-Leviathan/360a169c-9409-4bdb-af00-a02392ed35a2/scratchpad'
CACHE_DIR = os.path.join(SCR, "dec_p0_chunks")
BUCKET = "leviathan-dev-shahem-001"
P = "graphrag_evidence/"

ev_list = json.load(open(os.path.join(SCR, "dec_p0_ev_listing.json")))
sizes = {k[len(P):]: s for k, s, _ in ev_list}
mf = json.load(open(os.path.join(SCR, "write_manifest_rebuild_20260803T134404Z.json")))

# ---- (a) manifest vs live bytes ------------------------------------------------------------
print("== manifest after_bytes vs live LIST sizes ==")
report = {}
for layer, recs in mf["slices"].items():
    sub = "" if layer == "commodity" else "drivers/"
    ok = bad = miss = 0
    mism = []
    for name, r in recs.items():
        rel = f"{sub}{name}.jsonl"
        live = sizes.get(rel)
        if live is None:
            miss += 1
            mism.append((name, "MISSING", r.get("after_bytes")))
        elif live == r.get("after_bytes"):
            ok += 1
        else:
            bad += 1
            mism.append((name, live, r.get("after_bytes")))
    print(f"  {layer}: exact-byte match {ok}/{len(recs)}  mismatch={bad} missing={miss}")
    for m in mism[:10]:
        print("    MISMATCH", m)
    report[layer] = {"match": ok, "mismatch": bad, "missing": miss, "examples": mism[:20]}
json.dump(report, open(os.path.join(SCR, "dec_p0_manifest_bytes_check.json"), "w"))

# ---- (b) download chunks/ ------------------------------------------------------------------
os.makedirs(CACHE_DIR, exist_ok=True)
keys = [k for k, _, _ in ev_list if k[len(P):].startswith("chunks/") and k.endswith(".jsonl")]
print(f"\n== downloading {len(keys)} chunks/ objects ==")
tl = threading.local()
lock = threading.Lock()
state = {"n": 0, "bytes": 0, "err": 0}
t0 = time.time()


def _cli():
    c = getattr(tl, "c", None)
    if c is None:
        c = tl.c = boto3.client("s3", region_name="us-east-1")
    return c


def one(key):
    name = key.rsplit("/", 1)[-1]
    dst = os.path.join(CACHE_DIR, name)
    if os.path.exists(dst) and os.path.getsize(dst) > 0:
        with lock:
            state["n"] += 1
        return
    try:
        b = _cli().get_object(Bucket=BUCKET, Key=key)["Body"].read()
        with open(dst, "wb") as fh:
            fh.write(b)
        with lock:
            state["n"] += 1
            state["bytes"] += len(b)
            if state["n"] % 400 == 0:
                print(f"   {state['n']}/{len(keys)}  {state['bytes']/1e6:.0f} MB  "
                      f"{time.time()-t0:.0f}s", flush=True)
    except Exception as e:  # noqa: BLE001
        with lock:
            state["err"] += 1
            if state["err"] < 5:
                print("   ERR", name, type(e).__name__, str(e)[:120], flush=True)


with ThreadPoolExecutor(max_workers=24) as pool:
    list(pool.map(one, keys))
print(f"done: {state['n']} objects, {state['bytes']/1e6:.1f} MB new, errors={state['err']}, "
      f"{time.time()-t0:.0f}s")
sys.stdout.flush()
