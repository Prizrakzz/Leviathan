"""dec_p0 era scan, RANGED edition -- same measurement, restart-tolerant transport.

Why this exists: v1 held one open GET per object for its whole body. On the ~0.6-1.0 GB commodity
slices over a home link that stream stalls and restarts from byte 0, so the link stays busy while
nothing ever finishes (measured: 5.2 MB/s flowing, 2 of 24 slices done after 66 minutes).

Here each object is pulled in bounded RANGE requests (default 32 MB) with per-range retries, so a
hiccup costs one range, never the whole object. Records straddling a range edge carry over in `buf`.
Parsing, era bucketing and the output record are byte-identical to v1.

Appends to the SAME dec_p0_era_scan.jsonl and skips slices already present (resume).
ASCII stdout only (cp1252 console).
"""
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import boto3
from botocore.config import Config

SCRATCH = r'C:/Users/User/AppData/Local/Temp/claude/C--Users-User-Desktop-Leviathan/360a169c-9409-4bdb-af00-a02392ed35a2/scratchpad'
BKT = 'leviathan-dev-shahem-001'
PFX = 'graphrag_evidence/'
OUT = os.path.join(SCRATCH, 'dec_p0_era_scan.jsonl')
RANGE = 32 << 20                                        # 32 MB per request

ERAS = ("pre1990", "1990s", "2000s", "2010_17", "2018_26", "undated")
RX_EV = re.compile(rb'"event_date"\s*:\s*(?:"([^"]*)"|null)')
RX_DT = re.compile(rb'"date"\s*:\s*(?:"([^"]*)"|null)')

_cfg = Config(max_pool_connections=32, retries={'max_attempts': 3, 'mode': 'standard'},
              read_timeout=90, connect_timeout=20)
_lock = threading.Lock()
_done = {'n': 0}


def era_of(raw):
    try:
        year = int(raw[:4])
    except (TypeError, ValueError):
        return "undated"
    if year < 1990:
        return "pre1990"
    if year <= 1999:
        return "1990s"
    if year <= 2009:
        return "2000s"
    if year <= 2017:
        return "2010_17"
    if year <= 2026:
        return "2018_26"
    return "undated"


class Acc:
    """Per-slice accounting, shared by the streaming loop and the final-record branch."""

    def __init__(self):
        self.hist = {e: 0 for e in ERAS}
        self.n = 0
        self.no_event = 0
        self.ymin = None
        self.ymax = None

    def add(self, ln):
        self.n += 1
        mev = RX_EV.search(ln)
        raw = mev.group(1) if (mev and mev.group(1)) else None
        if raw is None:
            self.no_event += 1
            mdt = RX_DT.search(ln)
            raw = mdt.group(1) if (mdt and mdt.group(1)) else None
        self.hist[era_of(raw)] += 1
        if raw:
            try:
                y = int(raw[:4])
                self.ymin = y if self.ymin is None else min(self.ymin, y)
                self.ymax = y if self.ymax is None else max(self.ymax, y)
            except ValueError:
                pass


def _get_range(s3, key, start, end, tries=5):
    last = None
    for i in range(tries):
        try:
            return s3.get_object(Bucket=BKT, Key=key,
                                 Range="bytes=%d-%d" % (start, end))['Body'].read()
        except Exception as e:                           # noqa: BLE001 -- transport flake, retry the RANGE
            last = e
            time.sleep(min(2 ** i, 15))
    raise RuntimeError("range %d-%d of %s failed after %d tries: %s" % (start, end, key, tries, last))


def scan(key, name, group, size):
    s3 = boto3.client('s3', config=_cfg)
    acc = Acc()
    t0 = time.time()
    buf = b''
    pos = 0
    while pos < size:
        end = min(pos + RANGE, size) - 1
        chunk = _get_range(s3, key, pos, end)
        pos = end + 1
        buf += chunk
        lines = buf.split(b'\n')
        buf = lines.pop()                                # may be a partial record; carries to next range
        for ln in lines:
            if ln.strip():
                acc.add(ln)
    if buf.strip():                                      # writer uses "\n".join -> no trailing newline
        acc.add(buf)
    rec = {"slice": name, "group": group, "key": key, "bytes": size, "n_props": acc.n,
           "era_hist": acc.hist, "n_no_event_date": acc.no_event, "n_multi_event_field": 0,
           "year_min": acc.ymin, "year_max": acc.ymax, "scan_seconds": round(time.time() - t0, 1),
           "transport": "ranged"}
    with _lock:
        with open(OUT, 'a', encoding='utf-8') as f:
            f.write(json.dumps(rec) + "\n")
        _done['n'] += 1
        print("  [%2d] %-22s %-9s n=%-7d %7.1f MB %5.0fs" % (
            _done['n'], name, group, acc.n, size / 1e6, rec['scan_seconds']), flush=True)
    return rec


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else 'all'
    workers = int(sys.argv[2]) if len(sys.argv) > 2 else 8
    s3 = boto3.client('s3', config=_cfg)
    jobs = []
    for page in s3.get_paginator('list_objects_v2').paginate(Bucket=BKT, Prefix=PFX, Delimiter='/'):
        for o in page.get('Contents') or []:
            rel = o['Key'][len(PFX):]
            if rel.endswith('.jsonl') and not rel.startswith('_'):
                jobs.append((o['Key'], rel[:-6], 'commodity', o['Size']))
    for page in s3.get_paginator('list_objects_v2').paginate(Bucket=BKT, Prefix=PFX + 'drivers/'):
        for o in page.get('Contents') or []:
            rel = o['Key'][len(PFX + 'drivers/'):]
            if rel.endswith('.jsonl') and '/' not in rel:
                jobs.append((o['Key'], rel[:-6], 'driver', o['Size']))
    if only in ('drivers', 'commodity'):
        want = 'driver' if only == 'drivers' else 'commodity'
        jobs = [j for j in jobs if j[2] == want]
    already = set()
    if os.path.exists(OUT):
        for ln in open(OUT, encoding='utf-8'):
            if ln.strip():
                already.add(json.loads(ln)['slice'])
    jobs = [j for j in jobs if j[1] not in already]
    jobs.sort(key=lambda j: j[3])                        # SMALLEST first: steady completions, visible progress
    print("ranged scan: %d slices, %.2f GB, workers=%d, range=%d MB (resume: %d already done)" % (
        len(jobs), sum(j[3] for j in jobs) / 1e9, workers, RANGE >> 20, len(already)), flush=True)
    t0 = time.time()
    fails = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(scan, *j): j for j in jobs}
        for f in as_completed(futs):
            try:
                f.result()
            except Exception as e:                       # noqa: BLE001
                fails.append(futs[f][1])
                print("  FAIL %s: %s" % (futs[f][1], str(e)[:200]), flush=True)
    print("done: %d ok, %d failed, %.0fs" % (_done['n'], len(fails), time.time() - t0), flush=True)
    if fails:
        print("failed slices: %s" % ", ".join(fails), flush=True)
    return 1 if fails else 0


if __name__ == '__main__':
    raise SystemExit(main())
