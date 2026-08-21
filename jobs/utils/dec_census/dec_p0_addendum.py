"""DEC-P0 addendum: click-to-page darkness = props on a pages.json-backed doc that carry no offsets,
plus the doc-level offset-vintage split. Re-reads the local cache only (no S3)."""
import glob
import hashlib
import json
import os
import re
from collections import Counter, defaultdict

SCR = r'C:/Users/User/AppData/Local/Temp/claude/C--Users-User-Desktop-Leviathan/360a169c-9409-4bdb-af00-a02392ed35a2/scratchpad'
CACHE = os.path.join(SCR, "dec_p0_chunks")
tx = json.load(open(os.path.join(SCR, "dec_p0_text_listing.json")))
side = {k[:-len("pages.json")] + "document.json" for k, _, _ in tx if k.endswith("pages.json")}

doc_state = {}          # source_key -> Counter(offset_kind)
side_present = side_absent = 0
by_doc_kinds = defaultdict(Counter)
for f in glob.glob(os.path.join(CACHE, "*.jsonl")):
    for ln in open(f, encoding="utf-8"):
        if not ln.strip():
            continue
        p = json.loads(ln)
        sk = p.get("source_key")
        ok = str(p.get("offset_kind"))
        has = p.get("char_start") is not None and ok.lower() != "none"
        by_doc_kinds[sk][ok] += 1
        if sk in side:
            if has:
                side_present += 1
            else:
                side_absent += 1

# doc-level vintage: a doc is MIXED if it holds both offset-bearing and offset-less props
allp = alla = mixed = 0
for sk, c in by_doc_kinds.items():
    n_none = c.get("None", 0)
    tot = sum(c.values())
    if n_none == 0:
        allp += 1
    elif n_none == tot:
        alla += 1
    else:
        mixed += 1

sidedocs = {sk for sk in by_doc_kinds if sk in side}
out = {
    "pages_json_backed_docs_in_cache": len(sidedocs),
    "pages_json_backed_docs_total": len(side),
    "props_on_sidecar_docs_offsets_present": side_present,
    "props_on_sidecar_docs_offsets_ABSENT": side_absent,
    "docs_all_props_have_offsets": allp,
    "docs_no_props_have_offsets": alla,
    "docs_MIXED_vintage": mixed,
}
print(json.dumps(out, indent=1))
json.dump(out, open(os.path.join(SCR, "dec_p0_addendum.json"), "w"))
