"""Window-level candidate probe, thin_slice_fill method, over the WHOLE 7,065-doc text layer.

For every candidate surface form:
  n_win   = prop-scale windows containing it
  dark    = of those, windows that NO driver-slice term and NO commodity match_form claims
  srcs    = top sources of the dark windows
plus 2 verbatim dark samples so over-fire is judged on text.

Usage: python window_probe.py <candidates.txt> [--samples N]
ASCII stdout only.
"""
import collections
import io
import json
import os
import re
import sys
import unicodedata

import yaml

BASE = r"C:\Users\User\Desktop\Leviathan\configs\graphrag"
SCR = (r"C:\Users\User\AppData\Local\Temp\claude\C--Users-User-Desktop-Leviathan"
       r"\360a169c-9409-4bdb-af00-a02392ed35a2\scratchpad")
DOCS = os.path.join(SCR, "docs.jsonl")
CACHE = os.path.join(SCR, "windows.tsv")

_PARA = re.compile(r"\n\s*\n")
_SENT = re.compile(r'(?<=[.!?;])\s+(?=[A-Z0-9"(\u201c])')
CAP = 150000


def normalize(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[\s_\-]+", " ", s).strip().lower()


def windows(full):
    out = []
    for para in _PARA.split(full[:CAP]):
        if not para.strip():
            continue
        if len(para) <= 400:
            out.append(para.strip())
            continue
        for sent in _SENT.split(para):
            if not sent.strip():
                continue
            if len(sent) <= 400:
                out.append(sent.strip())
            else:
                out.extend(sent[j:j + 250].strip() for j in range(0, len(sent), 250))
    return [w for w in out if w]


def union_rx(forms):
    idx = {}
    for f in forms:
        nf = normalize(str(f))
        if nf and len(nf) > 1:
            idx.setdefault(nf, 1)
    keys = sorted(idx, key=len, reverse=True)
    return re.compile(r"\b(" + "|".join(re.escape(k) for k in keys) + r")\b") if keys else None


def load_cfg(name):
    with io.open(os.path.join(BASE, name), "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


sl = load_cfg("driver_slices.yaml")
voc = load_cfg("entity_vocabulary.yaml")
win = load_cfg("evidence_windows.yaml")

driver_terms = []
for _n, spec in (sl.get("drivers") or {}).items():
    driver_terms.extend([str(t) for t in (spec.get("terms") or [])])

NODES = ["corn", "wheat", "hrw_wheat", "hrs_wheat", "srw_wheat", "french_wheat", "rice",
         "white_maize", "yellow_maize", "soybeans", "soybean_meal", "soybean_oil", "rapeseed",
         "canola", "rapeseed_oil", "rapeseed_meal", "palm_oil", "palm_olein", "arabica_coffee",
         "robusta_coffee", "cocoa", "raw_sugar", "white_sugar", "cotton", "orange_juice"]
extra = win.get("extra_terms") or {}
alias = voc.get("aliases") or {}
node_forms = []
for n in NODES:
    node_forms += [n, n.replace("_", " ")] + [str(x) for x in (alias.get(n) or [])] \
                  + [str(x) for x in (extra.get(n) or [])]

DRX = union_rx(driver_terms)
NRX = union_rx(node_forms)

if not os.path.exists(CACHE):
    nw = 0
    with io.open(CACHE, "w", encoding="utf-8", newline="\n") as out:
        with io.open(DOCS, "r", encoding="utf-8") as fh:
            for line in fh:
                d = json.loads(line)
                t = d.get("t") or ""
                if not t:
                    continue
                for w in windows(t):
                    nwin = normalize(w)
                    flag = ("D" if DRX.search(nwin) else "-") + ("N" if NRX.search(nwin) else "-")
                    out.write("%s\t%s\t%s\t%s\n" % (d["s"], flag, nwin.replace("\t", " "),
                                                   w.replace("\t", " ").replace("\n", " ")[:300]))
                    nw += 1
    sys.stdout.write("windows built: %d\n" % nw)

SRC = []
FLAG = []
NW = []
RAW = []
with io.open(CACHE, "r", encoding="utf-8") as fh:
    for line in fh:
        p = line.rstrip("\n").split("\t")
        if len(p) < 4:
            continue
        SRC.append(p[0])
        FLAG.append(p[1])
        NW.append(p[2])
        RAW.append(p[3])

ndark = sum(1 for f in FLAG if f == "--")
sys.stdout.write("windows=%d dark(neither)=%d (%.1f%%)\n\n" % (len(NW), ndark, 100.0 * ndark / len(NW)))

cands = [ln.strip() for ln in io.open(sys.argv[1], "r", encoding="utf-8") if ln.strip()
         and not ln.startswith("#")]
nsamp = 2
for c in cands:
    nf = normalize(c)
    rx = re.compile(r"\b" + re.escape(nf) + r"\b")
    hit = 0
    dk = 0
    srcs = collections.Counter()
    samples = []
    for i, w in enumerate(NW):
        if nf not in w:
            continue
        if rx.search(w):
            hit += 1
            if FLAG[i] == "--":
                dk += 1
                srcs[SRC[i]] += 1
                if len(samples) < nsamp:
                    samples.append(RAW[i])
    sys.stdout.write("%-34s n=%-6d dark=%-6d top=%s\n"
                     % (c, hit, dk, ",".join("%s:%d" % (s, k) for s, k in srcs.most_common(3))))
    for s in samples:
        sys.stdout.write("     > %s\n" % s.encode("ascii", "ignore").decode()[:200])
