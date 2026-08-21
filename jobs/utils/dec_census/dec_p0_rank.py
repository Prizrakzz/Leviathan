"""DEC-P0 step C: rank NEW-edge candidates + UNSUPPORTED existing edges, write artifacts."""
import collections
import datetime
import json
import math
import os
import re
import unicodedata

SCRATCH = r'C:/Users/User/AppData/Local/Temp/claude/C--Users-User-Desktop-Leviathan/360a169c-9409-4bdb-af00-a02392ed35a2/scratchpad'
OUT = r'C:/Users/User/Desktop/Leviathan/data/dec_p0'
os.makedirs(OUT, exist_ok=True)

model = json.load(open(os.path.join(SCRATCH, 'dec_p0_model.json'), encoding='utf-8'))
cm = json.load(open(os.path.join(SCRATCH, 'dec_p0_comention.json'), encoding='utf-8'))
ENT, EDGES = model['entities'], model['edges']
solo = collections.Counter(cm['solo'])
dsolo = collections.Counter(cm['doc_solo'])
pair = collections.Counter({tuple(k.split('|')): v for k, v in cm['pair'].items()})
dpair = collections.Counter({tuple(k.split('|')): v for k, v in cm['doc_pair'].items()})
N, ND = cm['n_unique_chunks'], cm['n_documents']

CONTEXT_KINDS = {'country_origin', 'region', 'organization'}
COMMODITY_KINDS = {'commodity', 'commodity_group'}
MEASURABLE_FLOOR = 100
ZERO_BAND = 2


def _normalize(s):
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode()
    return re.sub(r'[\s_\-]+', ' ', s).strip().lower()


BLOCK = set(cm['blocked_forms'])
nf = {e: {f for f in (_normalize(s) for s in ENT[e]['surfaces'])
          if f and len(f) > 1 and f not in BLOCK} for e in ENT}


def kind(e):
    return ENT[e]['kind'] if e in ENT else '?'


def cls(e):
    k = kind(e)
    return 'context' if k in CONTEXT_KINDS else ('commodity' if k in COMMODITY_KINDS else 'driver')


def pkey(a, b):
    return (a, b) if a <= b else (b, a)


existing = {}
for e in EDGES:
    if e['src'] and e['dst'] and e['src'] != e['dst']:
        existing.setdefault(pkey(e['src'], e['dst']), []).append(e)

# a "co-mention" between two entities that share a surface form is one string firing twice
degenerate = {p for p in set(list(existing) + list(pair))
              if p[0] in nf and p[1] in nf and (nf[p[0]] & nf[p[1]])}
# ... and one whose form is a token-substring of the other's is partly circular: flag, don't drop
nested = set()
for p in set(list(existing) + list(pair)):
    if p in degenerate or p[0] not in nf or p[1] not in nf:
        continue
    if any(f' {x} ' in f' {y} ' or f' {y} ' in f' {x} ' for x in nf[p[0]] for y in nf[p[1]]):
        nested.add(p)


def npmi(a, b, c):
    if not solo[a] or not solo[b] or not c:
        return None
    pxy = c / N
    return round(math.log(pxy / ((solo[a] / N) * (solo[b] / N))) / (-math.log(pxy)), 3)


def row(a, b):
    a, b = pkey(a, b)
    c = pair.get((a, b), 0)
    dc = dpair.get((a, b), 0)
    exp = solo[a] * solo[b] / N if N else 0
    return {
        'a': a, 'a_kind': kind(a), 'b': b, 'b_kind': kind(b),
        'shape': '-'.join(sorted([cls(a), cls(b)])),
        'co_mentions_prop': c, 'co_mentions_doc': dc,
        'a_mentions': solo[a], 'b_mentions': solo[b],
        'a_docs': dsolo[a], 'b_docs': dsolo[b],
        'expected_prop_if_independent': round(exp, 1),
        'lift': round(c / exp, 2) if exp else None,
        'npmi': npmi(a, b, c),
        'cond_support': round(c / min(solo[a], solo[b]), 4) if min(solo[a], solo[b]) else None,
        'shared_surface_form': (a, b) in degenerate,
        'nested_surface_form': (a, b) in nested,
    }


# ------------------------------------------------- (a) NEW-edge candidates
cands = [row(a, b) for (a, b) in pair if pkey(a, b) not in existing and pkey(a, b) not in degenerate]
by_shape = collections.defaultdict(list)
for r in cands:
    by_shape[r['shape']].append(r)
for v in by_shape.values():
    v.sort(key=lambda r: -r['co_mentions_prop'])
dag_c = sorted([r for r in cands if 'context' not in r['shape']],
               key=lambda r: -r['co_mentions_prop'])
by_npmi = sorted([r for r in dag_c if r['co_mentions_prop'] >= 60], key=lambda r: -(r['npmi'] or -9))

# ------------------------------------------------- (b) UNSUPPORTED existing edges
dark_both, dark_prop, unmeasurable, supported = [], [], [], []
for p, rows in existing.items():
    r = row(*p)
    r['edge_types'] = sorted({x['edge_type'] for x in rows if x['edge_type']})
    r['edge_kinds'] = sorted({x['kind'] for x in rows})
    r['dag_contracts'] = sorted({x['contract'] for x in rows})
    r['n_dag_rows'] = len(rows)
    r['dag_names'] = sorted({f"{x['src_raw']} -> {x['dst_raw']}" for x in rows})[:8]
    r['silver_status'] = sorted({x['silver_status'] for x in rows if x['silver_status']})
    r['confidence'] = sorted({x['confidence'] for x in rows if x['confidence']})
    r['authored_mechanism'] = max((x.get('mechanism') or '' for x in rows), key=len)[:300]
    r['p_zero_if_independent'] = (f"{math.exp(-r['expected_prop_if_independent']):.2e}"
                                  if r['co_mentions_prop'] == 0 else None)
    if solo[r['a']] < MEASURABLE_FLOOR or solo[r['b']] < MEASURABLE_FLOOR:
        r['verdict'] = 'unmeasurable'
        r['why'] = 'endpoint below the ' + str(MEASURABLE_FLOOR) + '-mention measurable floor: ' + \
                   ', '.join(f'{e}={solo[e]}' for e in (r['a'], r['b']) if solo[e] < MEASURABLE_FLOOR)
        unmeasurable.append(r)
    elif r['co_mentions_prop'] <= ZERO_BAND and r['co_mentions_doc'] == 0:
        r['verdict'] = 'dark_at_both_levels'
        dark_both.append(r)
    elif r['co_mentions_prop'] <= ZERO_BAND:
        r['verdict'] = 'dark_in_prop_text_only'
        dark_prop.append(r)
    else:
        r['verdict'] = 'supported'
        supported.append(r)

for lst in (dark_both, dark_prop):
    lst.sort(key=lambda r: -r['expected_prop_if_independent'])
unmeasurable.sort(key=lambda r: -r['n_dag_rows'])
supported.sort(key=lambda r: -r['co_mentions_prop'])

never = sorted({e for p in existing for e in p if solo.get(e, 0) == 0})

# ------------------------------------------------- (c) structural findings
degree = collections.Counter()
for a_, b_ in existing:
    degree[a_] += 1
    degree[b_] += 1
orphans = sorted(({'entity': e, 'kind': kind(e), 'dag_degree': 0, 'corpus_mentions': solo[e],
                   'corpus_documents': dsolo[e],
                   'top_corpus_partner': max(((pair.get(pkey(e, o), 0), o) for o in ENT if o != e),
                                             default=(0, None))[1],
                   'top_corpus_partner_comentions': max(
                       (pair.get(pkey(e, o), 0) for o in ENT if o != e), default=0)}
                  for e in ENT
                  if kind(e) not in CONTEXT_KINDS and degree.get(e, 0) == 0 and solo[e] >= 100),
                 key=lambda r: -r['corpus_mentions'])
deg_vs_mentions = sorted(
    ({'entity': e, 'kind': kind(e), 'dag_degree': degree.get(e, 0), 'corpus_mentions': solo[e]}
     for e in ENT if kind(e) in COMMODITY_KINDS), key=lambda r: -r['corpus_mentions'])
thin_block = collections.Counter()
for r in unmeasurable:
    for e, mn in ((r['a'], r['a_mentions']), (r['b'], r['b_mentions'])):
        if mn < MEASURABLE_FLOOR:
            thin_block[e] += 1
thin_rows = [{'entity': e, 'kind': kind(e), 'corpus_mentions': solo[e],
              'dag_pairs_it_makes_unmeasurable': n,
              'has_surface_forms': bool(nf.get(e))} for e, n in thin_block.most_common(30)]
no_surface = sorted(e for e in ENT if not nf.get(e))
unmapped, waivers = model['unmapped_endpoints'], model['waivers']

art = {
    'artifact': 'edge_evidence',
    'generated_utc': datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
    'question': 'which causal-DAG edges the corpus text supports, and which node pairs the '
                'corpus co-mentions that have no edge at all',
    'method': {
        'matcher': 'production semantics copied verbatim from leviathan.graphrag.harvest._Matcher '
                   '+ extract._normalize (NFKD->ascii, [\\s_-]+ -> " ", lower, \\b word boundary, '
                   'longest-first alternation so a short form cannot shadow a longer one)',
        'surface_forms_compiled': cm['n_forms'],
        'surface_form_sources': 'entity_vocabulary.yaml nodes + aliases; driver_slices.yaml per-slice '
                                'term lists. Slice NAMES were deliberately NOT added as surface forms '
                                '(the config keeps terms specific on purpose: "heat wave" not "heat").',
        'blocked_forms': cm['blocked_forms'],
        'blocked_reason': 'these config aliases normalize to ordinary English words and would '
                          'manufacture co-mentions on every page',
        'corpus': 'graphrag_evidence/_raw/*.jsonl (24 commodity slices, 190,898 recs, vector-free) '
                  'UNION graphrag_evidence/chunks/*.jsonl (2,815 per-document chunk files, 345,870 '
                  'recs), deduped on (id, source_key)',
        'sampling': 'NO sampling was needed. The vector-free corpus is 235 MB total, so all 396,693 '
                    'unique chunks were matched -- strictly dominating the ~50k stratified sample the '
                    'task budgeted for. Per-slice coverage is reported under corpus.per_commodity_slice.',
        'pg_mirror': 'pg (evidence_props) was PREFERRED per the brief but is VPC-internal and '
                     'unreachable from this host (TCP 172.31.11.0:5432 refused); fell back to the '
                     'flat S3 slices, which are the same props.',
        'two_granularities': 'PROP co-mention = both entities in the SAME chunk (mean 102.9 chars, '
                             'i.e. one sentence) -- a strict test. DOC co-mention = both entities '
                             'somewhere in the same source document. An edge dark at BOTH levels is '
                             'the real review candidate; dark at prop level only usually just means '
                             'the mechanism is never stated in a single sentence.',
        'existing_edge_derivation': '33 configs/graphrag/causal/*.yaml -- drivers[].id -> contract '
                                    '(1,152 rows), drivers[].parents -> driver (1,088), '
                                    'inter_commodity[].driver_commodity -> contract (117), '
                                    'convergence[].interactions[].when pairs (277). Contract resolved '
                                    'to its node via commodity_hierarchy.yaml; DAG driver ids resolved '
                                    'to entities via entity_vocabulary aliases then driver_slices.dag_alias.',
        'edges_are_undirected_here': 'co-mention is symmetric, so the 2,634 directed DAG rows collapse '
                                     'to 979 distinct unordered endpoint pairs',
        'measurable_floor': MEASURABLE_FLOOR,
        'zero_band': ZERO_BAND,
        'degenerate_pairs_excluded_from_new_candidates': len(degenerate),
    },
    'corpus': {
        'chunks_scanned': cm['n_scanned'], 'unique_chunks_matched': N,
        'documents': ND, 'mean_chunk_chars': cm['mean_chunk_chars'],
        'chunks_with_no_vocab_hit': cm['ent_per_chunk_hist'].get('0', 0),
        'per_commodity_slice': cm['per_slice'],
        'top_sources': dict(collections.Counter(cm['per_source']).most_common(20)),
    },
    'headline': {
        'entities': len(ENT), 'entities_with_surface_forms': sum(1 for e in ENT if nf[e]),
        'dag_edge_rows': len(EDGES), 'distinct_undirected_pairs': len(existing),
        'unmapped_dag_endpoint_names': len(unmapped),
        'unmapped_all_waivered': all(k in waivers for k in unmapped),
        'pairs_with_any_prop_comention': len(pair),
        'pairs_with_any_doc_comention': len(dpair),
        'existing_supported': len(supported),
        'existing_dark_at_both_levels': len(dark_both),
        'existing_dark_prop_only': len(dark_prop),
        'existing_unmeasurable': len(unmeasurable),
        'new_candidates_non_context': len(dag_c),
        'new_candidates_total': len(cands),
    },
    'a_new_edge_candidates': {
        'top_by_prop_comention': dag_c[:60],
        'top_by_npmi_min60': by_npmi[:40],
        'driver_commodity': by_shape.get('commodity-driver', [])[:40],
        'commodity_commodity': by_shape.get('commodity-commodity', [])[:30],
        'driver_driver': by_shape.get('driver-driver', [])[:30],
        'context_endpoints_out_of_dag_scope': sorted(
            [r for r in cands if 'context' in r['shape']],
            key=lambda r: -r['co_mentions_prop'])[:25],
    },
    'b_unsupported_existing_edges': {
        'note': 'RANKED BY SURPRISE: expected_prop_if_independent is how many same-chunk '
                'co-mentions the two endpoints would produce by chance alone given their solo '
                'frequencies. A zero against a large expectation is the real signal. '
                'REVIEW, NOT DELETE -- several of the top rows are deliberately-authored '
                'two-hop mechanisms (see authored_mechanism), which is exactly the kind of '
                'edge a corpus never states in one sentence.',
        'all_prop_dark_ranked': sorted(dark_both + dark_prop,
                                       key=lambda r: -r['expected_prop_if_independent']),
        'dark_at_both_levels': dark_both,
        'unmeasurable': unmeasurable,
    },
    'c_structural_findings': {
        'note': 'these fall out of the same measurement and are the most actionable part of it',
        'edge_orphaned_entities': orphans,
        'commodity_dag_degree_vs_corpus_mentions': deg_vs_mentions,
        'thin_endpoints_blocking_measurement': thin_rows,
    },
    'best_supported_existing_edges': supported[:40],
    'endpoints_never_mentioned_in_corpus': never,
    'entities_without_surface_forms': no_surface,
    'unmapped_dag_endpoints': {k: {'n_edge_rows': v, 'waiver': waivers.get(k, {})}
                               for k, v in sorted(unmapped.items(), key=lambda kv: -kv[1])},
    'degenerate_alias_pairs': sorted(f'{a} | {b}' for a, b in degenerate),
}
json.dump(art, open(os.path.join(OUT, 'edge_evidence.json'), 'w', encoding='utf-8'),
          indent=1, ensure_ascii=True)

print('unique chunks', N, 'docs', ND)
print('existing pairs', len(existing), '| supported', len(supported),
      '| dark_both', len(dark_both), '| dark_prop_only', len(dark_prop),
      '| unmeasurable', len(unmeasurable))
print('new candidates', len(cands), 'non-context', len(dag_c), 'degenerate excluded', len(degenerate))
print('\n--- shapes of new candidates ---')
for k, v in sorted(by_shape.items(), key=lambda kv: -len(kv[1])):
    print(f'  {k:26s} {len(v)}')
print('\n--- DARK AT BOTH LEVELS (top 25) ---')
for r in dark_both[:25]:
    print(f"{r['a']:26s} {r['b']:24s} prop={r['co_mentions_prop']} doc={r['co_mentions_doc']} "
          f"exp={r['expected_prop_if_independent']:7.1f} rows={r['n_dag_rows']:2d} "
          f"{','.join(r['edge_types'])[:30]}")
print('\n--- NEW: driver x commodity (top 20) ---')
for r in by_shape.get('commodity-driver', [])[:20]:
    print(f"{r['a']:26s} {r['b']:24s} prop={r['co_mentions_prop']:5d} doc={r['co_mentions_doc']:5d} "
          f"npmi={r['npmi']} lift={r['lift']}")
print('\n--- NEW: commodity x commodity (top 12) ---')
for r in by_shape.get('commodity-commodity', [])[:12]:
    print(f"{r['a']:26s} {r['b']:24s} prop={r['co_mentions_prop']:5d} npmi={r['npmi']} lift={r['lift']}")
print('\n--- NEW: driver x driver (top 12) ---')
for r in by_shape.get('driver-driver', [])[:12]:
    print(f"{r['a']:26s} {r['b']:24s} prop={r['co_mentions_prop']:5d} npmi={r['npmi']} lift={r['lift']}")
print('\nnever-mentioned endpoints', len(never), never)
