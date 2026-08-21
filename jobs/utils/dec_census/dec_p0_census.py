"""DEC-P0 chunk coverage census: chunks side x text layer join. Read-only. ASCII stdout."""
import glob
import hashlib
import json
import os
import re
import statistics as st
import sys
from collections import Counter, defaultdict

SCR = r'C:/Users/User/AppData/Local/Temp/claude/C--Users-User-Desktop-Leviathan/360a169c-9409-4bdb-af00-a02392ed35a2/scratchpad'
CACHE = os.path.join(SCR, "dec_p0_chunks")
sys.path.insert(0, r"C:/Users/User/Desktop/Leviathan/src")

_SRC_RE = re.compile(r"text/source=([^/]+)/")


def source_of(k):
    m = _SRC_RE.search(k or "")
    return m.group(1) if m else "unknown"


# ── 1. load the doc-keyed chunk cache ────────────────────────────────────────────────────
props = []
per_doc_props = {}                       # md5 -> n props
cache_files = sorted(glob.glob(os.path.join(CACHE, "*.jsonl")))
empty_cache_objs = []
for f in cache_files:
    h = os.path.basename(f)[:-6]
    recs = [json.loads(ln) for ln in open(f, encoding="utf-8").read().splitlines() if ln.strip()]
    per_doc_props[h] = len(recs)
    if not recs:
        empty_cache_objs.append(h)
    props.extend(recs)

print(f"cache objects={len(cache_files)}  empty={len(empty_cache_objs)}  props={len(props):,}")

# ── 2. per-source census over the cache prop universe ────────────────────────────────────
by_src = defaultdict(lambda: {"props": 0, "docs": set(), "off_present": 0, "off_absent": 0,
                              "kind": Counter(), "cv": Counter(), "no_cv": 0,
                              "event_date": 0, "no_source_key": 0})
docs_props = Counter()                    # source_key -> n props
all_doc_keys = set()
kind_total = Counter()
cv_total = Counter()
off_present_total = off_absent_total = 0
id_set = set()
dupe_ids = 0
for p in props:
    sk = p.get("source_key")
    src = source_of(sk)
    b = by_src[src]
    b["props"] += 1
    if sk:
        b["docs"].add(sk)
        docs_props[sk] += 1
        all_doc_keys.add(sk)
    else:
        b["no_source_key"] += 1
    cs = p.get("char_start")
    ok = p.get("offset_kind")
    has = cs is not None and (ok is None or str(ok).lower() != "none")
    if has:
        b["off_present"] += 1
        off_present_total += 1
    else:
        b["off_absent"] += 1
        off_absent_total += 1
    b["kind"][str(ok)] += 1
    kind_total[str(ok)] += 1
    cv = p.get("chunk_version")
    if cv:
        b["cv"][cv] += 1
        cv_total[cv] += 1
    else:
        b["no_cv"] += 1
        cv_total["<absent>"] += 1
    if p.get("event_date"):
        b["event_date"] += 1
    pid = p.get("id")
    if pid in id_set:
        dupe_ids += 1
    id_set.add(pid)

print(f"distinct doc_keys referenced by cache props: {len(all_doc_keys):,}")
print(f"offsets present={off_present_total:,} absent={off_absent_total:,}  kinds={dict(kind_total)}")
print(f"chunk_version distribution: {dict(cv_total)}")
print(f"prop ids: distinct={len(id_set):,} collisions={dupe_ids:,}")

# ── 3. text layer: independent LIST already taken ────────────────────────────────────────
tx = json.load(open(os.path.join(SCR, "dec_p0_text_listing.json")))
doc_keys_text = sorted(k for k, _, _ in tx if k.endswith("document.json"))
text_by_src = defaultdict(list)
for k in doc_keys_text:
    text_by_src[source_of(k)].append(k)
print(f"text/ document.json total={len(doc_keys_text):,} sources={len(text_by_src)}")

# non-document.json objects under text/ (the pageindex sidecars etc.)
other_text = Counter()
for k, _, _ in tx:
    if not k.endswith("document.json"):
        other_text[k.rsplit("/", 1)[-1]] += 1
print("non-document.json objects under text/:", dict(other_text))

# ── 4. THE JOIN: which text docs have a chunk-cache object / >=1 chunk ───────────────────
cache_hashes = set(per_doc_props)
md5_of = {k: hashlib.md5(k.encode("utf-8")).hexdigest() for k in doc_keys_text}
hash_to_key = {v: k for k, v in md5_of.items()}
chunked_by_hash = {k for k in doc_keys_text if md5_of[k] in cache_hashes}
chunked_by_ref = {k for k in doc_keys_text if k in docs_props}
chunked = chunked_by_hash | chunked_by_ref
with_ge1 = {k for k in chunked if (docs_props.get(k, 0) > 0 or per_doc_props.get(md5_of[k], 0) > 0)}
never = [k for k in doc_keys_text if k not in with_ge1]

# cache objects whose hash matches NO text doc -> orphan cache entries
orphan_hashes = sorted(cache_hashes - set(hash_to_key))
# doc_keys referenced by props but absent from the text LIST
orphan_refs = sorted(all_doc_keys - set(doc_keys_text))

print(f"docs with >=1 chunk: {len(with_ge1):,}  never-chunked: {len(never):,}")
print(f"orphan cache objects (hash matches no live text doc): {len(orphan_hashes)}")
print(f"prop source_keys absent from the text LIST: {len(orphan_refs)}")

# ── 5. derive slice membership and CHECK against the 2026-08-03 rebuild manifest ─────────
os.environ.pop("EVIDENCE_S3", None)
derive_ok = True
derived = {"commodity": {}, "drivers": {}}
slice_offsets = {"commodity": {}, "drivers": {}}
derive_err = None
try:
    from leviathan.graphrag import evidence as ev
    from leviathan.graphrag import harvest as hv
    from leviathan.graphrag import extract as ex
    nodes = ev.all_nodes()
    matchers = {n: hv.build_matcher(ev.match_forms(n)) for n in nodes}
    dmatch = ev.driver_matchers()
    print(f"derivation: {len(nodes)} commodity nodes, {len(dmatch)} driver specs", flush=True)
    # SPEED: _Matcher.search() runs ex._normalize(text) on EVERY call, so 133 matchers x 262K props is
    # 35M NFKD passes. Normalize each prop's text ONCE and drive the compiled regexes directly -- this is
    # byte-for-byte the same predicate (_Matcher.search == self._rx.search(ex._normalize(text)) is not None),
    # memoized over identical texts (the cache has many repeats across docs).
    norm_memo = {}
    node_rx = [(n, matchers[n]._rx) for n in nodes]
    drv_rx = [(dn, m._rx) for dn, m in dmatch.items()]
    comm = {n: [] for n in nodes}
    dsink = defaultdict(list)
    for i, p in enumerate(props):
        t = p["text"]
        nt = norm_memo.get(t)
        if nt is None:
            nt = norm_memo[t] = ex._normalize(t)
        for n, rx in node_rx:
            if rx is not None and rx.search(nt):
                comm[n].append(p)
        for dn, rx in drv_rx:
            if rx is not None and rx.search(nt):
                dsink[dn].append(p)
        if i % 25000 == 0:
            print(f"   routed {i}/{len(props)}", flush=True)
    for n, recs in comm.items():
        derived["commodity"][n] = len(recs)
        pres = sum(1 for r in recs if r.get("char_start") is not None
                   and str(r.get("offset_kind")).lower() != "none")
        slice_offsets["commodity"][n] = {"n": len(recs), "off_present": pres,
                                         "off_absent": len(recs) - pres,
                                         "docs": len({r.get("source_key") for r in recs})}
    for dn, recs in dsink.items():
        seen, uniq = set(), []
        for r in recs:
            k = (r.get("source_key"), r["text"])
            if k in seen:
                continue
            seen.add(k)
            uniq.append(r)
        cap = ev.slice_cap(dn, 4000)
        capped = uniq[:cap] if (cap is not None and len(uniq) > cap) else uniq
        derived["drivers"][dn] = len(capped)
        pres = sum(1 for r in capped if r.get("char_start") is not None
                   and str(r.get("offset_kind")).lower() != "none")
        slice_offsets["drivers"][dn] = {"n": len(capped), "off_present": pres,
                                        "off_absent": len(capped) - pres,
                                        "docs": len({r.get("source_key") for r in capped}),
                                        "pre_cap": len(uniq), "cap": cap}
except Exception as e:  # noqa: BLE001
    derive_ok = False
    derive_err = f"{type(e).__name__}: {e}"
    print("DERIVATION FAILED:", derive_err)

mf = json.load(open(os.path.join(SCR, "write_manifest_rebuild_20260803T134404Z.json")))
manifest_counts = {layer: {n: r.get("after_n") for n, r in recs.items()}
                   for layer, recs in mf["slices"].items()}
check = {}
if derive_ok:
    for layer in ("commodity", "drivers"):
        mc, dc = manifest_counts[layer], derived[layer]
        names = sorted(set(mc) | set(dc))
        exact = [n for n in names if mc.get(n) == dc.get(n)]
        diff = [(n, mc.get(n), dc.get(n)) for n in names if mc.get(n) != dc.get(n)]
        check[layer] = {"n_slices_manifest": len(mc), "n_slices_derived": len(dc),
                        "exact_match": len(exact), "mismatch": len(diff),
                        "mismatches": diff[:200]}
        print(f"derivation check {layer}: exact {len(exact)}/{len(names)}  mismatch {len(diff)}")
        for d in diff[:12]:
            print("   ", d)

out = {"props": props[:0]}  # placeholder; real artifact assembled by the writer below
json.dump({
    "cache_files": len(cache_files), "empty_cache_objs": empty_cache_objs,
    "props_total": len(props), "distinct_doc_keys": len(all_doc_keys),
    "off_present": off_present_total, "off_absent": off_absent_total,
    "kind_total": dict(kind_total), "cv_total": dict(cv_total),
    "distinct_ids": len(id_set), "dupe_ids": dupe_ids,
    "by_src": {s: {"props": v["props"], "docs": len(v["docs"]), "off_present": v["off_present"],
                   "off_absent": v["off_absent"], "kind": dict(v["kind"]), "cv": dict(v["cv"]),
                   "no_cv": v["no_cv"], "event_date": v["event_date"],
                   "no_source_key": v["no_source_key"]} for s, v in by_src.items()},
    "docs_props": docs_props, "text_docs": len(doc_keys_text),
    "text_by_src": {s: len(v) for s, v in text_by_src.items()},
    "never": never, "with_ge1": len(with_ge1), "orphan_hashes": orphan_hashes,
    "orphan_refs": orphan_refs, "other_text": dict(other_text),
    "derived": derived, "slice_offsets": slice_offsets, "manifest_counts": manifest_counts,
    "check": check, "derive_ok": derive_ok, "derive_err": derive_err,
    "per_doc_props_by_hash": per_doc_props, "md5_of_text_docs": md5_of,
}, open(os.path.join(SCR, "dec_p0_census_raw.json"), "w"), default=list)
print("wrote dec_p0_census_raw.json")
