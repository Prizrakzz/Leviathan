"""DEC-P0 TEXT-layer census: per-source doc counts, per-year, bytes, pageindex,
extraction methods, and bytes->tokens calibration from a stratified GET sample.

LIST is free (already dumped to p0_text_listing.jsonl).  GETs are hard-capped.
"""
from __future__ import annotations

import collections
import concurrent.futures as cf
import json
import os
import re
import sys

import boto3

HERE = os.path.dirname(os.path.abspath(__file__))
LISTING = os.path.join(HERE, "p0_text_listing.jsonl")
OUT_DIR = "C:/Users/User/Desktop/Leviathan/data/dec_p0"
BUCKET = "leviathan-dev-shahem-001"

MAX_PER_SOURCE = 5
HARD_GET_CAP = 150
CHARS_PER_TOKEN = 4.0

ERA_BANDS = [
    ("pre_1990", None, 1989),
    ("1990_2005", 1990, 2005),
    ("2006_2015", 2006, 2015),
    ("2016_2020", 2016, 2020),
    ("2021_plus", 2021, None),
]

# key= names in the partition path that carry a date/year, in priority order.
_DATE_KEYS = (
    "publication_date", "release_date", "release_month", "release",
    "date", "crop_year", "year",
)
_YEAR_RE = re.compile(r"(19|20)\d{2}")


def year_of(key: str):
    """Extract a 4-digit publication/release year from a text-layer key."""
    segs = key.split("/")
    kv = {}
    for s in segs:
        if "=" in s:
            k, _, v = s.partition("=")
            kv.setdefault(k, v)
    for dk in _DATE_KEYS:
        if dk in kv:
            m = _YEAR_RE.match(kv[dk])
            if m:
                y = int(m.group(0))
                if 1900 <= y <= 2100:
                    return y
    # last resort: any 4-digit year anywhere in a partition value
    for s in segs:
        if "=" in s:
            m = _YEAR_RE.search(s.partition("=")[2])
            if m:
                y = int(m.group(0))
                if 1900 <= y <= 2100:
                    return y
    return None


def era_of(y):
    if y is None:
        return "unknown"
    for name, lo, hi in ERA_BANDS:
        if (lo is None or y >= lo) and (hi is None or y <= hi):
            return name
    return "unknown"


# ---------------------------------------------------------------- LIST pass
rows = [json.loads(l) for l in open(LISTING, encoding="utf-8")]

per_source = {}
other_basenames = collections.Counter()

for r in rows:
    key, size = r["k"], r["s"]
    parts = key.split("/")
    if len(parts) < 2 or not parts[1].startswith("source="):
        other_basenames["NON_SOURCE:" + key] += 1
        continue
    src = parts[1][len("source="):]
    base = parts[-1]
    d = per_source.setdefault(src, {
        "doc_count": 0, "bytes": 0, "pageindex_count": 0, "pageindex_bytes": 0,
        "per_year": collections.Counter(), "bytes_per_year": collections.Counter(),
        "other": collections.Counter(), "keys": [],
    })
    if base == "document.json":
        d["doc_count"] += 1
        d["bytes"] += size
        y = year_of(key)
        d["per_year"][str(y) if y else "unknown"] += 1
        d["bytes_per_year"][str(y) if y else "unknown"] += size
        d["keys"].append((y if y else 0, key, size))
    elif base == "pages.json":
        d["pageindex_count"] += 1
        d["pageindex_bytes"] += size
    else:
        d["other"][base] += 1
        other_basenames[base] += 1

total_docs = sum(d["doc_count"] for d in per_source.values())
total_bytes = sum(d["bytes"] for d in per_source.values())
total_pi = sum(d["pageindex_count"] for d in per_source.values())
print("sources=%d docs=%d bytes=%d (%.1f MB) pageindex=%d"
      % (len(per_source), total_docs, total_bytes, total_bytes / 1e6, total_pi))

# ------------------------------------------------------------ sample select
def pick(keys, n):
    """Stratified pick: oldest .. newest, evenly spread over the sorted list."""
    keys = sorted(keys)
    if len(keys) <= n:
        return keys
    idx = [round(i * (len(keys) - 1) / (n - 1)) for i in range(n)]
    seen, out = set(), []
    for i in idx:
        if i not in seen:
            seen.add(i)
            out.append(keys[i])
    return out


plan = []
for src in sorted(per_source):
    for _, key, size in pick(per_source[src]["keys"], MAX_PER_SOURCE):
        plan.append((src, key, size))
assert len(plan) <= HARD_GET_CAP, "GET plan %d exceeds cap %d" % (len(plan), HARD_GET_CAP)
print("stratified GET plan: %d objects across %d sources" % (len(plan), len(per_source)))

s3 = boto3.client("s3", region_name="us-east-1")


def fetch(item):
    src, key, size = item
    try:
        body = s3.get_object(Bucket=BUCKET, Key=key)["Body"].read()
        doc = json.loads(body.decode("utf-8"))
        ft = doc.get("full_text") or ""
        secs = doc.get("sections") or []
        sec_chars = sum(len(s.get("text") or "") for s in secs if isinstance(s, dict))
        return {
            "src": src, "key": key, "obj_bytes": size, "body_bytes": len(body),
            "full_text_chars": len(ft),
            "extraction_method": doc.get("extraction_method") or "MISSING",
            "n_sections": len(secs), "section_chars": sec_chars,
            "raw_key": doc.get("raw_key") or "", "top_keys": sorted(doc.keys()),
            "ok": True,
        }
    except Exception as exc:  # noqa: BLE001
        return {"src": src, "key": key, "obj_bytes": size, "ok": False,
                "error": "%s: %s" % (type(exc).__name__, exc)}


with cf.ThreadPoolExecutor(max_workers=12) as ex:
    samples = list(ex.map(fetch, plan))

n_ok = sum(1 for s in samples if s["ok"])
print("GETs done: %d ok / %d attempted" % (n_ok, len(samples)))

# ------------------------------------------------------- calibrate + assemble
by_src_samples = collections.defaultdict(list)
for s in samples:
    by_src_samples[s["src"]].append(s)

glob_ft = sum(s["full_text_chars"] for s in samples if s["ok"])
glob_ob = sum(s["obj_bytes"] for s in samples if s["ok"])
GLOBAL_RATIO = (glob_ft / glob_ob) if glob_ob else 1.0
print("GLOBAL chars-per-object-byte ratio = %.4f  (sampled %.1f MB)"
      % (GLOBAL_RATIO, glob_ob / 1e6))

out_sources = {}
era_totals = collections.Counter()
era_docs = collections.Counter()

for src in sorted(per_source):
    d = per_source[src]
    ss = [s for s in by_src_samples.get(src, []) if s["ok"]]
    ft = sum(s["full_text_chars"] for s in ss)
    ob = sum(s["obj_bytes"] for s in ss)
    if ob > 0:
        ratio = ft / ob
        basis = "sampled"
    else:
        ratio = GLOBAL_RATIO
        basis = "global_fallback"
    est_tokens = d["bytes"] * ratio / CHARS_PER_TOKEN

    methods = collections.Counter(s["extraction_method"] for s in ss)

    per_era_tok, per_era_docs = collections.Counter(), collections.Counter()
    for ystr, b in d["bytes_per_year"].items():
        e = era_of(int(ystr)) if ystr != "unknown" else "unknown"
        per_era_tok[e] += b * ratio / CHARS_PER_TOKEN
        per_era_docs[e] += d["per_year"][ystr]
    for e, v in per_era_tok.items():
        era_totals[e] += v
    for e, v in per_era_docs.items():
        era_docs[e] += v

    yrs = [int(y) for y in d["per_year"] if y != "unknown"]
    out_sources[src] = {
        "doc_count": d["doc_count"],
        "per_year": {y: c for y, c in sorted(d["per_year"].items())},
        "bytes": d["bytes"],
        "bytes_per_year": {y: c for y, c in sorted(d["bytes_per_year"].items())},
        "est_tokens": int(round(est_tokens)),
        "pageindex_count": d["pageindex_count"],
        "pageindex_bytes": d["pageindex_bytes"],
        "extraction_methods": dict(methods),
        "sample_keys": [s["key"] for s in by_src_samples.get(src, [])],
        "year_min": min(yrs) if yrs else None,
        "year_max": max(yrs) if yrs else None,
        "unknown_year_docs": d["per_year"].get("unknown", 0),
        "mean_doc_bytes": int(round(d["bytes"] / d["doc_count"])) if d["doc_count"] else 0,
        "mean_full_text_chars_sampled": int(round(ft / len(ss))) if ss else None,
        "chars_per_object_byte": round(ratio, 5),
        "calibration_basis": basis,
        "samples_ok": len(ss),
        "samples_attempted": len(by_src_samples.get(src, [])),
        "est_tokens_per_era": {e: int(round(v)) for e, v in sorted(per_era_tok.items())},
        "docs_per_era": {e: int(v) for e, v in sorted(per_era_docs.items())},
        "other_basenames": dict(d["other"]),
    }

total_tokens = sum(v["est_tokens"] for v in out_sources.values())

artifact = {
    "artifact": "doc_census",
    "generated_at_utc": __import__("datetime").datetime.utcnow().isoformat() + "Z",
    "bucket": BUCKET,
    "prefix": "text/",
    "method": {
        "list": "paginated list_objects_v2 over text/ (complete, 1 pass)",
        "get_sample": "stratified oldest->newest, max %d/source, hard cap %d"
                      % (MAX_PER_SOURCE, HARD_GET_CAP),
        "tokens": "est_tokens = source_bytes * chars_per_object_byte / %.1f  "
                  "(chars_per_object_byte = sum(len(full_text)) / sum(S3 object bytes) "
                  "over that source's sample -- this IS the JSON-overhead correction, "
                  "since document.json carries sections[] duplicating full_text plus "
                  "JSON escaping and UTF-8 multibyte)" % CHARS_PER_TOKEN,
        "era_bands": [b[0] for b in ERA_BANDS],
    },
    "totals": {
        "objects_listed": len(rows),
        "sources": len(per_source),
        "doc_count": total_docs,
        "bytes": total_bytes,
        "pageindex_count": total_pi,
        "pageindex_bytes": sum(d["pageindex_bytes"] for d in per_source.values()),
        "est_tokens": total_tokens,
        "gets_used": len(samples),
        "gets_ok": n_ok,
        "global_chars_per_object_byte": round(GLOBAL_RATIO, 5),
        "est_tokens_per_era": {e: int(round(v)) for e, v in sorted(era_totals.items())},
        "docs_per_era": {e: int(v) for e, v in sorted(era_docs.items())},
    },
    "key_structure": {
        "root": "text/source=<source>/...",
        "layouts": {},
    },
    "per_source": out_sources,
    "sample_detail": samples,
    "unattributed_objects": {k: v for k, v in other_basenames.items()
                             if k.startswith("NON_SOURCE:")},
}

# record the observed sub-layout per source (partition key names after source=)
for src in sorted(per_source):
    ex_key = sorted(k for _, k, _ in per_source[src]["keys"])[0] if per_source[src]["keys"] else ""
    segs = ex_key.split("/")[2:-1]
    artifact["key_structure"]["layouts"][src] = "/".join(
        (s.partition("=")[0] + "=<v>") if "=" in s else s for s in segs
    ) or "(flat)"

os.makedirs(OUT_DIR, exist_ok=True)
with open(os.path.join(OUT_DIR, "doc_census.json"), "w", encoding="utf-8") as fh:
    json.dump(artifact, fh, indent=2, ensure_ascii=False)

print("TOTAL est_tokens = %d (%.2f M)" % (total_tokens, total_tokens / 1e6))
print("wrote %s" % os.path.join(OUT_DIR, "doc_census.json"))
