"""DEC-P0/P1 step B: co-mention counting over the vector-free chunk corpus.

Matcher semantics are COPIED from production (leviathan.graphrag.harvest._Matcher +
extract._normalize): NFKD -> ascii, collapse [\\s_-]+ -> ' ', lower, word-boundary
alternation, longest-first. Nothing invented.

Corpus = graphrag_evidence/chunks/*.jsonl ONLY (the full per-document chunk store), deduped
by (id, source_key).

_x2 run (2026-08-21, graph-completion wave stage 2), three mandatory changes vs DEC-P0:
  (a) CHUNKS points at a FRESH cache dir. jobs/utils/x2_tail_resplit.py:357 rewrote 569
      existing chunk objects on 2026-08-21 09h, so the pre-X2 dec_p0_chunks/ copy mixes
      pre-merge and post-merge props and its counts are unattributable.
  (b) THE _raw/ LEG IS DROPPED ENTIRELY. data/dec_p0/critique.md:59-63,120-122,199-200 ruled
      on this: ~50,800 of edge_evidence's chunks (12.8%) are not in the live universe, _raw/
      is frozen at the 2026-07-01 vintage (re-LISTed 2026-08-21: still 24 objects / 80 MB),
      and recommendation 6 is "Re-scope edge_evidence's corpus to the live store".
      thin_slice_fill.md:255 already refused to quote these counts for that reason.
  (c) Outputs are dec_p1_* so the pre-X2 baseline survives.

Two co-mention granularities are counted:
  PROP  -- both entities named in the same chunk (a sentence-scale prop). Strict.
  DOC   -- both entities named somewhere in the same source document (source_key). Loose.
An edge that is dark at BOTH levels is the real review candidate.

Usage: dec_p0_comention.py [--workers N]   (N>1 shards by FILE across processes; the merge is
exact because chunks/ objects are per-document and (id, source_key) uniqueness is asserted).
"""
import argparse
import collections
import glob
import json
import os
import re
import sys
import time
import unicodedata
from concurrent.futures import ProcessPoolExecutor

SCRATCH = r'C:/Users/User/AppData/Local/Temp/claude/C--Users-User-Desktop-Leviathan/360a169c-9409-4bdb-af00-a02392ed35a2/scratchpad'
CHUNKS = os.path.join(SCRATCH, 'dec_p1_chunks')
MAX_ENT_PER_CHUNK = 30

# forms whose normalized token is an ordinary English word. Kept out so a stray "us"/"real"
# does not manufacture co-mentions. Every other config surface form is used as written.
BLOCK_FORMS = {'us', 'eu', 'mg', 'real', 'don', 'sap', 'mot', 'minas'}

_RX = None
_FORM_TO_ENTS = None


def _normalize(s):
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode()
    return re.sub(r'[\s_\-]+', ' ', s).strip().lower()


def _build_matcher():
    """Compile the longest-first union regex over every config surface form."""
    model = json.load(open(os.path.join(SCRATCH, 'dec_p1_model.json'), encoding='utf-8'))
    form_to_ents = collections.defaultdict(set)
    for eid, meta in model['entities'].items():
        for s in meta['surfaces']:
            nf = _normalize(s)
            if not nf or len(nf) <= 1 or nf in BLOCK_FORMS:
                continue
            form_to_ents[nf].add(eid)
    keys = sorted(form_to_ents, key=len, reverse=True)
    rx = re.compile(r'\b(' + '|'.join(re.escape(k) for k in keys) + r')\b')
    return rx, form_to_ents, keys


def _init():
    global _RX, _FORM_TO_ENTS
    if _RX is None:
        _RX, _FORM_TO_ENTS, _ = _build_matcher()


def scan(paths):
    """Scan a shard of chunk files. Returns plain dicts (picklable)."""
    _init()
    solo = collections.Counter()
    pair = collections.Counter()
    form_hits = collections.Counter()
    per_slice = collections.Counter()
    per_source = collections.Counter()
    doc_ents = collections.defaultdict(set)
    ent_hist = collections.Counter()
    seen = set()
    n_scanned = n_used = n_capped = 0
    text_chars = 0
    for p in paths:
        for line in open(p, 'rb'):
            line = line.strip()
            if not line:
                continue
            n_scanned += 1
            try:
                r = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            skey = r.get('source_key')
            key = (r.get('id'), skey)
            if key in seen:
                continue
            seen.add(key)
            n_used += 1
            text = r.get('text') or ''
            text_chars += len(text)
            hits = _RX.findall(_normalize(text))
            if not hits:
                ent_hist[0] += 1
                continue
            ents = set()
            for h in hits:
                form_hits[h] += 1
                ents |= _FORM_TO_ENTS[h]
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
    return {
        'solo': dict(solo),
        'pair': {f'{a}|{b}': c for (a, b), c in pair.items()},
        'form_hits': dict(form_hits), 'per_slice': dict(per_slice),
        'per_source': dict(per_source),
        'ent_hist': {str(k): v for k, v in ent_hist.items()},
        'doc_ents': {k: sorted(v) for k, v in doc_ents.items()},
        'n_scanned': n_scanned, 'n_used': n_used, 'n_capped': n_capped,
        'text_chars': text_chars, 'n_keys': len(seen),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--workers', type=int, default=1)
    args = ap.parse_args()

    _, _, keys = _build_matcher()
    print('surface forms compiled:', len(keys), flush=True)

    files = sorted(glob.glob(os.path.join(CHUNKS, '*.jsonl')))
    print('input files:', len(files), '(chunks/ only -- _raw/ leg dropped)', flush=True)
    if not files:
        sys.exit(f'no chunk files under {CHUNKS}')

    t0 = time.time()
    if args.workers > 1:
        shards = [files[i::args.workers] for i in range(args.workers)]
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            parts = list(ex.map(scan, shards))
    else:
        parts = [scan(files)]
    print(f'scan done in {time.time()-t0:.0f}s over {len(parts)} shard(s)', flush=True)

    solo = collections.Counter()
    pair = collections.Counter()
    form_hits = collections.Counter()
    per_slice = collections.Counter()
    per_source = collections.Counter()
    ent_hist = collections.Counter()
    doc_ents = collections.defaultdict(set)
    n_scanned = n_used = n_capped = text_chars = shard_keys = 0
    for pt in parts:
        solo.update(pt['solo'])
        pair.update(pt['pair'])
        form_hits.update(pt['form_hits'])
        per_slice.update(pt['per_slice'])
        per_source.update(pt['per_source'])
        ent_hist.update(pt['ent_hist'])
        for k, v in pt['doc_ents'].items():
            doc_ents[k] |= set(v)
        n_scanned += pt['n_scanned']
        n_used += pt['n_used']
        n_capped += pt['n_capped']
        text_chars += pt['text_chars']
        shard_keys += pt['n_keys']

    # Sharding is exact only if (id, source_key) never repeats ACROSS files. chunks/ objects are
    # per-document so it should not; assert it rather than assume it.
    dedup_note = ('single process' if args.workers <= 1 else
                  f'sharded x{args.workers}; per-shard unique keys sum={shard_keys} == n_used')
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
        'corpus_dir': CHUNKS, 'n_input_files': len(files), 'raw_leg_dropped': True,
        'workers': args.workers, 'dedup_note': dedup_note,
        'scan_seconds': round(time.time() - t0, 1),
        # `pair` is ALREADY string-keyed ("a|b") -- shards emit it that way so the merge is a
        # plain Counter.update. `doc_pair` is tuple-keyed (built here, post-merge).
        'solo': dict(solo), 'pair': dict(pair),
        'doc_solo': dict(doc_solo), 'doc_pair': {f'{a}|{b}': c for (a, b), c in doc_pair.items()},
        'form_hits': dict(form_hits), 'per_slice': dict(per_slice),
        'per_source': dict(per_source), 'ent_per_chunk_hist': dict(ent_hist),
    }
    json.dump(out, open(os.path.join(SCRATCH, 'dec_p1_comention.json'), 'w', encoding='utf-8'))
    print('prop pairs', len(pair), 'doc pairs', len(doc_pair),
          'mean chunk chars', out['mean_chunk_chars'])


if __name__ == '__main__':
    main()
