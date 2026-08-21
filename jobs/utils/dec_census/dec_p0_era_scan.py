"""dec_p0: stream every evidence slice from S3 and build the per-slice ERA histogram.

Reads bytes only (never json.loads the 1024-float vectors): each JSONL record carries exactly one
"date": and one "event_date": field, and '"date":' cannot match inside '"event_date":' (the char before
`date` there is '_', not '"'), so two regexes per line are exact and ~100x cheaper than a JSON parse.

Era buckets are e1_census._era_of verbatim (event_date preferred over date; unparseable / year > 2026
-> "undated"). Results append to dec_p0_era_scan.jsonl so a partial run survives.
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

ERAS = ("pre1990", "1990s", "2000s", "2010_17", "2018_26", "undated")
RX_EV = re.compile(rb'"event_date"\s*:\s*(?:"([^"]*)"|null)')
RX_DT = re.compile(rb'"date"\s*:\s*(?:"([^"]*)"|null)')

_cfg = Config(max_pool_connections=64, retries={'max_attempts': 5, 'mode': 'standard'},
              read_timeout=120, connect_timeout=20)
_lock = threading.Lock()
_done = {'n': 0, 'bytes': 0}


def era_of(raw):
    """e1_census._era_of, on bytes. raw is a bytes year-prefix or None."""
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


def scan(key, name, group, size):
    s3 = boto3.client('s3', config=_cfg)
    hist = {e: 0 for e in ERAS}
    n = 0
    n_no_event = 0
    n_multi_field = 0
    ymin, ymax = None, None
    t0 = time.time()
    body = s3.get_object(Bucket=BKT, Key=key)['Body']
    buf = b''
    nbytes = 0
    while True:
        chunk = body.read(1 << 21)
        if not chunk:
            break
        nbytes += len(chunk)
        buf += chunk
        lines = buf.split(b'\n')
        buf = lines.pop()
        for ln in lines:
            if not ln.strip():
                continue
            n += 1
            mev = RX_EV.search(ln)
            mdt = RX_DT.search(ln)
            if mev is not None and len(RX_EV.findall(ln)) > 1:
                n_multi_field += 1
            raw = mev.group(1) if (mev and mev.group(1)) else None
            if raw is None:
                n_no_event += 1
                raw = mdt.group(1) if (mdt and mdt.group(1)) else None
            e = era_of(raw)
            hist[e] += 1
            if raw:
                try:
                    y = int(raw[:4])
                    ymin = y if ymin is None else min(ymin, y)
                    ymax = y if ymax is None else max(ymax, y)
                except ValueError:
                    pass
    if buf.strip():
        # The slice writer emits "\n".join(...) -- no trailing newline -- so EVERY file ends with a
        # record in this branch. It must run the identical accounting as the loop above, year span
        # included (an earlier revision omitted the span here and silently dropped each file's last
        # record from year_min/year_max; caught by cross-checking china_crush_demand against the
        # write manifest's after_span).
        n += 1
        mev = RX_EV.search(buf)
        mdt = RX_DT.search(buf)
        raw = mev.group(1) if (mev and mev.group(1)) else None
        if raw is None:
            n_no_event += 1
            raw = mdt.group(1) if (mdt and mdt.group(1)) else None
        hist[era_of(raw)] += 1
        if raw:
            try:
                y = int(raw[:4])
                ymin = y if ymin is None else min(ymin, y)
                ymax = y if ymax is None else max(ymax, y)
            except ValueError:
                pass
    rec = {"slice": name, "group": group, "key": key, "bytes": size, "n_props": n,
           "era_hist": hist, "n_no_event_date": n_no_event, "n_multi_event_field": n_multi_field,
           "year_min": ymin, "year_max": ymax, "scan_seconds": round(time.time() - t0, 1)}
    with _lock:
        with open(OUT, 'a', encoding='utf-8') as f:
            f.write(json.dumps(rec) + "\n")
        _done['n'] += 1
        _done['bytes'] += nbytes
        print("  [%3d] %-28s %-9s n=%-7d %7.1f MB %5.0fs" % (
            _done['n'], name, group, n, size / 1e6, rec['scan_seconds']), flush=True)
    return rec


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else 'all'
    workers = int(sys.argv[2]) if len(sys.argv) > 2 else 24
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
    if only == 'drivers':
        jobs = [j for j in jobs if j[2] == 'driver']
    elif only == 'commodity':
        jobs = [j for j in jobs if j[2] == 'commodity']
    already = set()
    if os.path.exists(OUT):
        for ln in open(OUT, encoding='utf-8'):
            if ln.strip():
                already.add(json.loads(ln)['slice'])
    jobs = [j for j in jobs if j[1] not in already]
    jobs.sort(key=lambda j: -j[3])                       # biggest first: best tail latency
    total = sum(j[3] for j in jobs)
    print("scanning %d slices, %.2f GB, workers=%d (already done: %d)" % (
        len(jobs), total / 1e9, workers, len(already)), flush=True)
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(scan, *j): j for j in jobs}
        for f in as_completed(futs):
            try:
                f.result()
            except Exception as e:                        # noqa: BLE001
                print("  FAIL %s: %s" % (futs[f][1], str(e)[:160]), flush=True)
    dt = time.time() - t0
    print("done: %d slices in %.0fs (%.1f MB/s aggregate)" % (
        _done['n'], dt, _done['bytes'] / max(dt, 1) / 1e6), flush=True)


if __name__ == '__main__':
    main()
