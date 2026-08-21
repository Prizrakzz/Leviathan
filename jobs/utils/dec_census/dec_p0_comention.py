"""DEC-P0 step B: co-mention counting over the vector-free chunk corpus.

Matcher semantics are COPIED from production (leviathan.graphrag.harvest._Matcher +
extract._normalize): NFKD -> ascii, collapse [\\s_-]+ -> ' ', lower, word-boundary
alternation, longest-first. Nothing invented.

Corpus = graphrag_evidence/_raw/*.jsonl (24 commodity slices, slice-labelled) UNION
graphrag_evidence/chunks/*.jsonl (the full per-document chunk store), deduped by chunk id.

Two co-mention granularities are counted:
  PROP  -- both entities named in the same chunk (a sentence-scale prop). Strict.
  DOC   -- both entities named somewhere in the same source document (source_key). Loose.
An edge that is dark at BOTH levels is the real review candidate.
"""
import collections
import glob
import json
import os
import re
import unicodedata

SCRATCH = r'C:/Users/User/AppData/Local/Temp/claude/C--Users-User-Desktop-Leviathan/360a169c-9409-4bdb-af00-a02392ed35a2/scratchpad'
RAW = os.path.join(SCRATCH, 'dec_p0_raw')
CHUNKS = os.path.join(SCRATCH, 'dec_p0_chunks')
MAX_ENT_PER_CHUNK = 30

# forms whose normalized token is an ordinary English word. Kept out so a stray "us"/"real"
# does not manufacture co-mentions. Every other config surface form is used as written.
BLOCK_FORMS = {'us', 'eu', 'mg', 'real', 'don', 'sap', 'mot', 'minas'}


def _normalize(s):
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode()
    return re.sub(r'[\s_\-]+', ' ', s).strip().lower()


model = json.load(open(os.path.join(SCRATCH, 'dec_p0_model.json'), encoding='utf-8'))
ENT = model['entities']

form_to_ents = collections.defaultdict(set)
for eid, meta in ENT.items():
    for s in meta['surfaces']:
        nf = _normalize(s)
        if not nf or len(nf) <= 1 or nf in BLOCK_FORMS:
            continue
        form_to_ents[nf].add(eid)

keys = sorted(form_to_ents, key=len, reverse=True)
RX = re.compile(r'\b(' + '|'.join(re.escape(k) for k in keys) + r')\b')
print('surface forms compiled:', len(keys), flush=True)

solo = collections.Counter()
pair = collections.Counter()
form_hits = collections.Counter()
per_slice = collections.Counter()
per_source = collections.Counter()
doc_ents = collections.defaultdict(set)
seen = set()
n_scanned = n_used = n_capped = 0
text_chars = 0
ent_hist = collections.Counter()

files = [(p, 'raw') for p in sorted(glob.glob(os.path.join(RAW, '*.jsonl')))] + \
        [(p, 'chunk') for p in sorted(glob.glob(os.path.join(CHUNKS, '*.jsonl')))]
print('input files:', len(files), flush=True)
for fi, (p, kind) in enumerate(files):
    for line in open(p, 'rb'):
        line = line.strip()
        if not line:
            continue
        n_scanned += 1
        try:
            r = json.loads(line)
        except Exception:
            continue
        skey = r.get('source_key')
        key = (r.get('id'), skey)
        if key in seen:
            continue
        seen.add(key)
        n_used += 1
        text = r.get('text') or ''
        text_chars += len(text)
        hits = RX.findall(_normalize(text))
        if not hits:
            ent_hist[0] += 1
            continue
        ents = set()
        for h in hits:
            form_hits[h] += 1
            ents |= form_to_ents[h]
        ent_hist[len(ents)] += 1
        if skey:
            doc_ents[skey] |= ents
        if len(ents) > MAX_ENT_PER_CHUNK:
            n_capped += 1
            continue
        es = sorted(ents)
        for e in es:
            solo[e] += 1
        for i in range(len(es)):
            for j in range(i + 1, len(es)):
                pair[(es[i], es[j])] += 1
        if r.get('contract'):
            per_slice[r['contract']] += 1
        per_source[r.get('source') or '?'] += 1
    if fi % 600 == 0:
        print(f'  {fi}/{len(files)} scanned={n_scanned} unique={n_used}', flush=True)

print('scanned', n_scanned, 'unique', n_used, 'docs', len(doc_ents), flush=True)

doc_solo = collections.Counter()
doc_pair = collections.Counter()
for skey, ents in doc_ents.items():
    es = sorted(ents)
    for e in es:
        doc_solo[e] += 1
    for i in range(len(es)):
        for j in range(i + 1, len(es)):
            doc_pair[(es[i], es[j])] += 1

out = {
    'n_scanned': n_scanned, 'n_unique_chunks': n_used, 'n_capped': n_capped,
    'n_documents': len(doc_ents), 'mean_chunk_chars': round(text_chars / max(n_used, 1), 1),
    'n_forms': len(keys), 'blocked_forms': sorted(BLOCK_FORMS),
    'solo': dict(solo), 'pair': {f'{a}|{b}': c for (a, b), c in pair.items()},
    'doc_solo': dict(doc_solo), 'doc_pair': {f'{a}|{b}': c for (a, b), c in doc_pair.items()},
    'form_hits': dict(form_hits), 'per_slice': dict(per_slice),
    'per_source': dict(per_source), 'ent_per_chunk_hist': {str(k): v for k, v in ent_hist.items()},
}
json.dump(out, open(os.path.join(SCRATCH, 'dec_p0_comention.json'), 'w', encoding='utf-8'))
print('prop pairs', len(pair), 'doc pairs', len(doc_pair), 'mean chunk chars', out['mean_chunk_chars'])
