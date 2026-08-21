"""DEC-P0 step D: pull verbatim example chunks for the top new-edge candidates, so every
ranked pair can be checked against real text rather than trusted."""
import collections
import glob
import json
import os
import re
import unicodedata

SCRATCH = r'C:/Users/User/AppData/Local/Temp/claude/C--Users-User-Desktop-Leviathan/360a169c-9409-4bdb-af00-a02392ed35a2/scratchpad'
OUT = r'C:/Users/User/Desktop/Leviathan/data/dec_p0/edge_evidence.json'


def _normalize(s):
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode()
    return re.sub(r'[\s_\-]+', ' ', s).strip().lower()


model = json.load(open(os.path.join(SCRATCH, 'dec_p0_model.json'), encoding='utf-8'))
cm = json.load(open(os.path.join(SCRATCH, 'dec_p0_comention.json'), encoding='utf-8'))
art = json.load(open(OUT, encoding='utf-8'))
ENT = model['entities']
BLOCK = set(cm['blocked_forms'])

form_to_ents = collections.defaultdict(set)
for eid, meta in ENT.items():
    for s in meta['surfaces']:
        f = _normalize(s)
        if f and len(f) > 1 and f not in BLOCK:
            form_to_ents[f].add(eid)
RX = re.compile(r'\b(' + '|'.join(re.escape(k) for k in
                                  sorted(form_to_ents, key=len, reverse=True)) + r')\b')

want = []
nc = art['a_new_edge_candidates']
for key in ('driver_commodity', 'commodity_commodity', 'driver_driver'):
    for r in nc[key][:12]:
        want.append((r['a'], r['b']))
want = list(dict.fromkeys(tuple(sorted(p)) for p in want))
wantset = set(want)
ex = collections.defaultdict(list)

files = sorted(glob.glob(os.path.join(SCRATCH, 'dec_p0_raw', '*.jsonl'))) + \
        sorted(glob.glob(os.path.join(SCRATCH, 'dec_p0_chunks', '*.jsonl')))
seen = set()
for p in files:
    if all(len(ex[k]) >= 3 for k in wantset):
        break
    for line in open(p, 'rb'):
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        k = (r.get('id'), r.get('source_key'))
        if k in seen:
            continue
        seen.add(k)
        t = r.get('text') or ''
        es = set()
        for hgh in RX.findall(_normalize(t)):
            es |= form_to_ents[hgh]
        if len(es) < 2:
            continue
        for i, a in enumerate(sorted(es)):
            for b in sorted(es)[i + 1:]:
                if (a, b) in wantset and len(ex[(a, b)]) < 3:
                    ex[(a, b)].append({'text': t[:320], 'source': r.get('source'),
                                       'date': r.get('date'), 'source_key': r.get('source_key')})

art['a_new_edge_candidates']['verbatim_examples'] = {
    f'{a} | {b}': v for (a, b), v in sorted(ex.items()) if v}
json.dump(art, open(OUT, 'w', encoding='utf-8'), indent=1, ensure_ascii=True)
print('pairs with examples:', sum(1 for v in ex.values() if v), 'of', len(want))
for k in list(sorted(ex))[:8]:
    print('\n==', k)
    for e in ex[k][:2]:
        print('   ', e['date'], e['source'], '|', e['text'][:190])
