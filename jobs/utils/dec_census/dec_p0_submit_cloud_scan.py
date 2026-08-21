"""dec_p0: run the era scan IN THE VPC on Batch instead of over the home Wi-Fi.

The laptop link sustains ~4.6 MB/s and drops long transfers: the 101 driver slices (1.36 GB) scanned
fine, but the 24 commodity slices (11.12 GB) burned ~4.4 GB of retries in 16 minutes with zero
completions. Inside the VPC the same read is minutes. READ-ONLY over the slice objects; the only write
is one small JSON under eval/.

Reuses leviathan-dev-evidence-build (image ENTRYPOINT is `python`, so the command override is
["-c", SRC] -- the same `python -c` idiom submit_batch_evidence_maintenance.build_gated_command uses).
Scans ALL slices, so the driver half is an independent re-measurement of the local numbers.

_x2 run (2026-08-21, graph-completion wave stage 2): the estate is now 163 slices / 29.76 GB
(43 commodity + 120 driver, was 125 / 12.48 GB). The scan discovers slices by LIST so no code
change is needed; 8 vCPU / 32,768 MB is KEPT deliberately -- the largest single object is
french_wheat at 1.68 GB and is streamed in 4 MB reads, and the queue's maxvCpus is 32.
Output key is dec_p1_era_scan_<STAMP>.json so the dec_p0 scan artifacts stay intact.
"""
import json
import time

import boto3

REGION = "us-east-1"
QUEUE = "leviathan-dev-queue-ondemand"          # not the SPOT queue: a reclaim would waste the whole read
JOBDEF = "leviathan-dev-evidence-build"
BUCKET = "leviathan-dev-shahem-001"
STAMP = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
OUTKEY = f"graphrag_evidence/eval/dec_p1_era_scan_{STAMP}.json"

SRC = r'''
import boto3, json, re, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from botocore.config import Config

B = "leviathan-dev-shahem-001"; P = "graphrag_evidence/"
OUTKEY = "%OUTKEY%"
RXE = re.compile(rb'"event_date"\s*:\s*(?:"([^"]*)"|null)')
RXD = re.compile(rb'"date"\s*:\s*(?:"([^"]*)"|null)')
ERAS = ("pre1990", "1990s", "2000s", "2010_17", "2018_26", "undated")
CFG = Config(max_pool_connections=64, retries={"max_attempts": 5, "mode": "standard"})

def era(raw):
    try:
        y = int(raw[:4])
    except (TypeError, ValueError):
        return "undated"
    if y < 1990: return "pre1990"
    if y <= 1999: return "1990s"
    if y <= 2009: return "2000s"
    if y <= 2017: return "2010_17"
    if y <= 2026: return "2018_26"
    return "undated"

def scan(job):
    key, name, grp, size = job
    s3 = boto3.client("s3", config=CFG)
    h = {e: 0 for e in ERAS}; n = 0; ne = 0; ymin = None; ymax = None
    t0 = time.time()
    def add(ln):
        nonlocal n, ne, ymin, ymax
        n += 1
        m = RXE.search(ln)
        raw = m.group(1) if (m and m.group(1)) else None
        if raw is None:
            ne += 1
            m2 = RXD.search(ln)
            raw = m2.group(1) if (m2 and m2.group(1)) else None
        h[era(raw)] += 1
        if raw:
            try:
                y = int(raw[:4])
                ymin = y if ymin is None else min(ymin, y)
                ymax = y if ymax is None else max(ymax, y)
            except ValueError:
                pass
    body = s3.get_object(Bucket=B, Key=key)["Body"]
    buf = b""
    while True:
        c = body.read(1 << 22)
        if not c: break
        buf += c
        ls = buf.split(b"\n"); buf = ls.pop()
        for ln in ls:
            if ln.strip(): add(ln)
    if buf.strip(): add(buf)          # writer uses "\n".join -> no trailing newline
    print("  %-24s %-9s n=%-7d %7.1f MB %4.0fs" % (name, grp, n, size/1e6, time.time()-t0), flush=True)
    return {"slice": name, "group": grp, "key": key, "bytes": size, "n_props": n,
            "era_hist": h, "n_no_event_date": ne, "year_min": ymin, "year_max": ymax,
            "scan_seconds": round(time.time()-t0, 1), "transport": "vpc"}

s3 = boto3.client("s3", config=CFG)
jobs = []
for pg in s3.get_paginator("list_objects_v2").paginate(Bucket=B, Prefix=P, Delimiter="/"):
    for o in pg.get("Contents") or []:
        rel = o["Key"][len(P):]
        if rel.endswith(".jsonl") and not rel.startswith("_"):
            jobs.append((o["Key"], rel[:-6], "commodity", o["Size"]))
for pg in s3.get_paginator("list_objects_v2").paginate(Bucket=B, Prefix=P + "drivers/"):
    for o in pg.get("Contents") or []:
        rel = o["Key"][len(P + "drivers/"):]
        if rel.endswith(".jsonl") and "/" not in rel:
            jobs.append((o["Key"], rel[:-6], "driver", o["Size"]))
print("dec_p1 era scan: %d slices, %.2f GB" % (len(jobs), sum(j[3] for j in jobs)/1e9), flush=True)
t0 = time.time()
out = []; fails = []
with ThreadPoolExecutor(max_workers=32) as pool:
    futs = {pool.submit(scan, j): j for j in jobs}
    for f in as_completed(futs):
        try:
            out.append(f.result())
        except Exception as e:
            fails.append({"slice": futs[f][1], "error": str(e)[:300]})
            print("  FAIL %s: %s" % (futs[f][1], str(e)[:200]), flush=True)
doc = {"census": "dec_p1_era_scan", "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
       "n_slices": len(out), "n_failed": len(fails), "failures": fails,
       "elapsed_seconds": round(time.time()-t0, 1),
       "slices": sorted(out, key=lambda r: (r["group"], r["slice"]))}
s3.put_object(Bucket=B, Key=OUTKEY, Body=json.dumps(doc, indent=1).encode("utf-8"))
print("wrote s3://%s/%s  (%d ok, %d failed, %.0fs)" % (B, OUTKEY, len(out), len(fails), doc["elapsed_seconds"]), flush=True)
if fails:
    raise SystemExit(1)
'''.replace('%OUTKEY%', OUTKEY)

overrides = {
    "command": ["-c", SRC],
    "resourceRequirements": [                       # read+regex only; the 16/120 GB default is for rebuilds
        {"type": "VCPU", "value": "8"},
        {"type": "MEMORY", "value": "32768"},
    ],
}
batch = boto3.client("batch", region_name=REGION)
resp = batch.submit_job(jobName=f"dec-p1-era-scan-{STAMP}", jobQueue=QUEUE,
                        jobDefinition=JOBDEF, containerOverrides=overrides)
print("submitted job_id=%s" % resp["jobId"])
print("out_key=%s" % OUTKEY)
print(json.dumps({"job_id": resp["jobId"], "out_key": OUTKEY, "stamp": STAMP}))
