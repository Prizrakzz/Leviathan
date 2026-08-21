"""DEC-P0/P1: LIST the evidence store + the text layer. Paginated LISTs only, zero GETs.

_x2 run (2026-08-21, graph-completion wave stage 2): outputs re-pointed to dec_p1_* so the
pre-X2 dec_p0_*_listing.json baselines survive. Also emits a chunks/ LIST SNAPSHOT
(count, bytes, newest LastModified) that every stage-2 artifact's method block must carry --
the re-census universe has to stay identifiable after the fact.
"""
import json
import os
import re
from collections import defaultdict

import boto3

BUCKET = "leviathan-dev-shahem-001"
EV = "graphrag_evidence/"
TEXT = "text/"
OUT = r'C:/Users/User/AppData/Local/Temp/claude/C--Users-User-Desktop-Leviathan/360a169c-9409-4bdb-af00-a02392ed35a2/scratchpad'

s3 = boto3.client("s3", region_name="us-east-1")
pg = s3.get_paginator("list_objects_v2")


def listing(prefix):
    out = []
    for p in pg.paginate(Bucket=BUCKET, Prefix=prefix):
        for o in p.get("Contents", []):
            out.append((o["Key"], o["Size"], o["LastModified"].isoformat()))
    return out


ev = listing(EV)
print("evidence objects:", len(ev), "total bytes:", sum(s for _, s, _ in ev))
buckets = defaultdict(lambda: [0, 0])
for k, s, _ in ev:
    rel = k[len(EV):]
    grp = rel.split("/")[0] if "/" in rel else "TOPLEVEL"
    buckets[grp][0] += 1
    buckets[grp][1] += s
for g, (n, b) in sorted(buckets.items(), key=lambda x: -x[1][1]):
    print(f"  {g:16s} n={n:6d} bytes={b:,}")

print()
print("TOP-LEVEL commodity slices:")
for k, s, _ in sorted([e for e in ev if "/" not in e[0][len(EV):]], key=lambda x: -x[1]):
    print(f"  {k[len(EV):]:40s} {s:,}")

with open(os.path.join(OUT, "dec_p1_ev_listing.json"), "w", encoding="utf-8") as fh:
    json.dump(ev, fh)

# ---- chunks/ LIST snapshot (the sequencing-trap rider: pin the universe being judged) -------
CH = EV + "chunks/"
ch = [e for e in ev if e[0].startswith(CH) and e[0].endswith(".jsonl")]
snap = {
    "prefix": CH,
    "n_objects": len(ch),
    "total_bytes": sum(s for _, s, _ in ch),
    "newest_last_modified": max((m for _, _, m in ch), default=None),
    "oldest_last_modified": min((m for _, _, m in ch), default=None),
    "listed_at_utc": __import__("datetime").datetime.now(
        __import__("datetime").timezone.utc).isoformat(),
}
by_day = defaultdict(lambda: [0, 0])
for _, s, m in ch:
    by_day[m[:10]][0] += 1
    by_day[m[:10]][1] += s
snap["last_modified_by_day"] = {d: {"n": n, "bytes": b} for d, (n, b) in sorted(by_day.items())}
with open(os.path.join(OUT, "dec_p1_chunks_snapshot.json"), "w", encoding="utf-8") as fh:
    json.dump(snap, fh, indent=1)
print()
print(f"CHUNKS SNAPSHOT n={snap['n_objects']} bytes={snap['total_bytes']:,} "
      f"newest={snap['newest_last_modified']}")
for d, v in snap["last_modified_by_day"].items():
    print(f"   {d}  n={v['n']:5d}  bytes={v['bytes']:,}")

tx = listing(TEXT)
print()
print("text objects:", len(tx))
docs = [e for e in tx if e[0].endswith("document.json")]
print("document.json:", len(docs))
src = defaultdict(int)
for k, s, _ in docs:
    m = re.search(r"text/source=([^/]+)/", k)
    src[m.group(1) if m else "unknown"] += 1
for k in sorted(src, key=lambda x: -src[x]):
    print(f"  {k:40s} {src[k]}")
with open(os.path.join(OUT, "dec_p1_text_listing.json"), "w", encoding="utf-8") as fh:
    json.dump(tx, fh)
print("DONE")
