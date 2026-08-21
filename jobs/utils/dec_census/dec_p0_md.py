"""DEC-P0/P1: render data/dec_p1/edge_evidence.md from the JSON artifact. ASCII only."""
import json
import os

P = r'C:/Users/User/Desktop/Leviathan/data/dec_p1/edge_evidence.json'
a = json.load(open(P, encoding='utf-8'))
h, c, m = a['headline'], a['corpus'], a['method']
L = []
w = L.append

w('# Edge evidence audit -- what the CORPUS says about the causal DAG edges')
w('')
w(f"Generated {a['generated_utc']} | artifact: `data/dec_p1/edge_evidence.json`")
w('')
w('## Headline')
w('')
w(f"- **{h['dag_edge_rows']:,} DAG edge rows** across 33 `configs/graphrag/causal/*.yaml` collapse to "
  f"**{h['distinct_undirected_pairs']} distinct unordered endpoint pairs** (co-mention is symmetric).")
w(f"- Corpus: **{c['unique_chunks_matched']:,} unique chunks** over **{c['documents']:,} source documents**; "
  f"mean chunk length **{c['mean_chunk_chars']} chars** -- these are sentence-scale props, so a "
  f"same-chunk co-mention is a SAME-SENTENCE test.")
w(f"- **{h['existing_supported']} of {h['distinct_undirected_pairs']} pairs ({h['existing_supported']*100//h['distinct_undirected_pairs']}%) are corpus-supported** "
  f"(>{m['zero_band']} same-chunk co-mentions).")
w(f"- **{h['existing_dark_prop_only']+h['existing_dark_at_both_levels']} pairs are prop-dark** "
  f"(<= {m['zero_band']} same-chunk co-mentions with both endpoints above the "
  f"{m['measurable_floor']}-mention floor); of those **{h['existing_dark_at_both_levels']} are dark at the "
  f"DOCUMENT level too** -- the two endpoints never share a source document at all.")
w(f"- **{h['existing_unmeasurable']} pairs are unmeasurable**: at least one endpoint is mentioned "
  f"fewer than {m['measurable_floor']} times in the whole corpus. A zero there means nothing.")
w(f"- **{h['unmapped_dag_endpoint_names']} DAG driver ids have no surface form at all** and could not be "
  f"tested. Every one of them is already declared in `driver_slices.yaml` waivers "
  f"(`unmapped_all_waivered = {h['unmapped_all_waivered']}`) -- so this is a known, recorded gap, not a new one.")
w(f"- The corpus co-mentions **{h['pairs_with_any_prop_comention']:,} distinct entity pairs** in the same "
  f"chunk and **{h['pairs_with_any_doc_comention']:,}** in the same document. "
  f"**{h['new_candidates_non_context']:,} co-mentioned pairs have no DAG edge** once country/region/"
  f"organization endpoints are set aside ({h['new_candidates_total']:,} including them).")
# _x2 run: these three lines quoted DEC-P0's numbers as literals and would have re-published
# them verbatim against a 3.5x corpus. Everything here is read from the artifact now.
_orph = a['c_structural_findings']['edge_orphaned_entities']
_top3 = ', '.join(f"`{r['entity']}` ({r['corpus_mentions']:,} mentions)" for r in _orph[:3])
w(f"- **{len(_orph)} entities carry ZERO DAG edges** despite real corpus presence -- the largest "
  f"being {_top3}.")
w(f"- **{len(a['endpoints_never_mentioned_in_corpus'])} existing edge endpoints are never mentioned "
  f"once** in {c['unique_chunks_matched']:,} chunks: "
  + ', '.join(f'`{x}`' for x in a['endpoints_never_mentioned_in_corpus']) + '.')
w('')

w('## Method (and what it is NOT)')
w('')
w(f"- Matcher semantics **copied from production** (`leviathan.graphrag.harvest._Matcher` + "
  f"`extract._normalize`): NFKD->ascii, `[\\s_-]+` -> space, lowercase, `\\b` word boundaries, "
  f"longest-first alternation. **{m['surface_forms_compiled']} surface forms** over "
  f"**{h['entities_with_surface_forms']} of {h['entities']} entities**.")
w(f"- Surface forms come from `entity_vocabulary.yaml` (nodes + aliases) and the `driver_slices.yaml` "
  f"per-slice term lists. Slice NAMES were deliberately not added as surface forms -- the config keeps "
  f"terms specific on purpose (\"heat wave\", not bare \"heat\").")
w(f"- {len(m['blocked_forms'])} config aliases blocked because they normalize to ordinary English words: "
  + ', '.join(f'`{x}`' for x in m['blocked_forms']) + '.')
w(f"- {m['degenerate_pairs_excluded_from_new_candidates']} pairs share a surface form outright "
  f"(e.g. `protein_meal_substitution` lists \"rapeseed meal\"); their \"co-mentions\" are one string "
  f"firing twice, so they are excluded from the new-edge list and flagged everywhere else.")
w(f"- **pg was preferred and is unreachable.** {m['pg_mirror']}")
w(f"- **No sampling.** {m['sampling']}")
w('- Co-mention is **association, not causation**. This audit ranks review candidates; it does not '
  'mint or retire edges.')
w('')

w('## (a) NEW-edge candidates -- co-mentioned, no edge')
w('')
w('Ranked within the shapes the DAGs actually encode. `lift` = observed / expected-if-independent; '
  '`npmi` normalizes it to [-1, 1].')
w('')


def table(rows, cols, hdr):
    w('| ' + ' | '.join(hdr) + ' |')
    w('|' + '|'.join(['---'] * len(hdr)) + '|')
    for r in rows:
        w('| ' + ' | '.join(str(r[k]) if not isinstance(r[k], float) else f'{r[k]:g}'
                            for k in cols) + ' |')
    w('')


NC = ['a', 'b', 'co_mentions_prop', 'co_mentions_doc', 'a_mentions', 'b_mentions', 'lift', 'npmi']
NH = ['node A', 'node B', 'same-chunk', 'same-doc', 'A seen', 'B seen', 'lift', 'npmi']

w('### Driver x commodity (the `driver -> contract` shape) -- top 20 by same-chunk co-mention')
w('')
table(a['a_new_edge_candidates']['driver_commodity'][:20], NC, NH)

w('### Commodity x commodity (the `inter_commodity` shape) -- top 15')
w('')
table(a['a_new_edge_candidates']['commodity_commodity'][:15], NC, NH)

w('### Driver x driver (the `parents` / convergence shape) -- top 15')
w('')
table(a['a_new_edge_candidates']['driver_driver'][:15], NC, NH)

w('### Strongest association regardless of shape -- top 20 by npmi (min 60 same-chunk co-mentions)')
w('')
w('This is the list to read if you want *mechanism* candidates rather than *frequency*: high npmi '
  'means the two names appear together far more than their solo rates predict.')
w('')
table(a['a_new_edge_candidates']['top_by_npmi_min60'][:20], NC, NH)

w('### Out of DAG scope (country / region / organization endpoints)')
w('')
w(f"{len([r for r in a['a_new_edge_candidates']['context_endpoints_out_of_dag_scope']])} shown of "
  f"{h['new_candidates_total'] - h['new_candidates_non_context']:,}. These are origin anchors and "
  f"attribution sources, not causal-DAG nodes -- listed for completeness, not as edge proposals.")
w('')
table(a['a_new_edge_candidates']['context_endpoints_out_of_dag_scope'][:10], NC, NH)

w('### Verbatim corpus evidence (integrity check)')
w('')
w(f"Every pair in the three shape tables above has up to 3 real chunks recorded in the JSON under "
  f"`a_new_edge_candidates.verbatim_examples` "
  f"({len(a['a_new_edge_candidates'].get('verbatim_examples', {}))} pairs). A sample, so the ranking "
  f"can be checked rather than trusted:")
w('')
_EX = a['a_new_edge_candidates'].get('verbatim_examples', {})
for k in ('corn | ethanol', 'biodiesel | palm_oil', 'canola | rapeseed',
          'inr_fx | msp', 'aluminium | copper', 'egypt_gasc_tenders | wheat'):
    if k in _EX and _EX[k]:
        e = _EX[k][0]
        w(f"- **{k}** -- `{e['source']}` {e['date']}: \"{e['text'][:200]}\"")
w('')

w('## (b) UNSUPPORTED existing edges -- edge exists, ~zero co-mention')
w('')
w('**Candidates for REVIEW, not deletion.** Ranked by surprise: `expected` is how many same-chunk '
  'co-mentions the two endpoints would produce by chance alone at their observed solo frequencies. '
  'A zero against a large expectation is the signal; a zero against `expected = 0.4` is nothing. '
  '`same-doc` is the mitigator -- if it is large, the pair does co-occur in documents and only the '
  'single-sentence statement is missing.')
w('')
allx = a['b_unsupported_existing_edges']['all_prop_dark_ranked']
w(f"Full ranked list: **{len(allx)} pairs** in the JSON. Top 25 here.")
w('')
UC = ['a', 'b', 'co_mentions_prop', 'co_mentions_doc', 'expected_prop_if_independent',
      'n_dag_rows', 'edge_types_s', 'dag_contracts_s']
UH = ['node A', 'node B', 'same-chunk', 'same-doc', 'expected', 'DAG rows', 'edge type', 'in DAGs']
for r in allx:
    r['edge_types_s'] = ', '.join(r['edge_types'])[:34]
    r['dag_contracts_s'] = (', '.join(r['dag_contracts'])[:40] +
                            ('...' if len(', '.join(r['dag_contracts'])) > 40 else ''))
table(allx[:25], UC, UH)

w('### Why the top rows are dark (authored mechanism, verbatim from the DAG)')
w('')
for r in allx[:6]:
    if r['authored_mechanism']:
        w(f"- **{r['a']} <-> {r['b']}** (`{', '.join(r['edge_types'])}`, expected "
          f"{r['expected_prop_if_independent']}, observed {r['co_mentions_prop']}): "
          f"\"{r['authored_mechanism'][:210]}...\"")
w('')
w('The pattern is consistent: the highest-surprise dark edges are **deliberately-authored two-hop '
  'mechanisms** (palm -> soyoil -> oil share of crush -> meal; corn ethanol -> cane freed for sugar). '
  'A single-sentence corpus will never state those. That is a limitation of the TEST, and it is the '
  'reason this list is a review queue rather than a delete list.')
w('')

w(f"### Dark at BOTH levels ({h['existing_dark_at_both_levels']} pairs) -- endpoints never share a document")
w('')
w('The stronger claim. Note every one has a small `expected`, so none of these is statistically '
  'surprising on its own -- they are thin-endpoint edges (JSE maize, orange juice, HRS wheat) more '
  'than wrong ones.')
w('')
table([dict(r, edge_types_s=', '.join(r['edge_types'])[:30],
            dag_contracts_s=', '.join(r['dag_contracts'])[:38])
       for r in a['b_unsupported_existing_edges']['dark_at_both_levels'][:15]], UC, UH)

w(f"### Unmeasurable ({h['existing_unmeasurable']} pairs)")
w('')
w(f"At least one endpoint falls below the {m['measurable_floor']}-mention floor. This is the single "
  f"largest bucket -- **{h['existing_unmeasurable']*100//h['distinct_undirected_pairs']}% of all DAG pairs "
  f"cannot be judged by this corpus at all.** Top 10 by how many DAG rows ride on them:")
w('')
table([dict(r, edge_types_s=', '.join(r['edge_types'])[:30],
            dag_contracts_s=str(len(r['dag_contracts'])) + ' DAGs')
       for r in a['b_unsupported_existing_edges']['unmeasurable'][:10]], UC, UH)

S = a['c_structural_findings']
w('## (c) Structural findings that fall out of the same measurement')
w('')
w(f"### {len(S['edge_orphaned_entities'])} entities carry ZERO DAG edges despite real corpus presence")
w('')
w('These are not "weak edges" -- they have no edge at all, in any of the 33 DAGs, in either '
  'direction. Sorted by corpus mentions.')
w('')
w('| entity | kind | corpus mentions | in docs | strongest corpus partner | co-mentions |')
w('|---|---|---|---|---|---|')
for r in S['edge_orphaned_entities']:
    w(f"| {r['entity']} | {r['kind']} | {r['corpus_mentions']:,} | {r['corpus_documents']:,} | "
      f"{r['top_corpus_partner']} | {r['top_corpus_partner_comentions']:,} |")
w('')
# _x2 run: this was four hand-written bullets carrying DEC-P0's literals (biodiesel 1,288,
# sunflower 6,550, canola~rapeseed 185, corn~ethanol 401). Re-publishing those against a 3.5x
# corpus would have been the census contradicting its own headline. Generated from the artifact.
w('The ones that matter most, ranked by the corpus mass sitting behind a node with no edge at all:')
w('')
for r in S['edge_orphaned_entities'][:6]:
    w(f"- **`{r['entity']}`** ({r['kind']}) -- {r['corpus_mentions']:,} mentions across "
      f"{r['corpus_documents']:,} documents, DAG degree 0. Its strongest corpus partner is "
      f"`{r['top_corpus_partner']}` at {r['top_corpus_partner_comentions']:,} same-chunk "
      f"co-mentions.")
w('')
w('See `data/dec_p1/edge_adjudication.md` for the verdict on each named edge -- this table is the '
  'evidence, not the decision.')
w('')
w('### The corpus names the parent concept; the DAGs hang edges off the class nodes')
w('')
w('| commodity node | DAG degree | corpus mentions |')
w('|---|---|---|')
for r in S['commodity_dag_degree_vs_corpus_mentions'][:16]:
    w(f"| {r['entity']} | {r['dag_degree']} | {r['corpus_mentions']:,} |")
w('')
# _x2 run: the wheat-class illustration was hardcoded to DEC-P0's counts. Recomputed.
_deg = {r['entity']: r for r in S['commodity_dag_degree_vs_corpus_mentions']}
_wc = [_deg[n] for n in ('wheat', 'srw_wheat', 'hrw_wheat', 'hrs_wheat') if n in _deg]
if _wc:
    w('`wheat` carries %d DAG pairs on %s mentions, while its class members carry %s. This is by '
      'DESIGN -- `commodity_hierarchy.yaml` makes `wheat` the un-expanded concept and expands it to '
      'class members -- but it is also the single biggest reason this audit cannot measure the '
      'wheat complex: the text says "wheat", the edges say "srw_wheat".'
      % (_wc[0]['dag_degree'], format(_wc[0]['corpus_mentions'], ','),
         '; '.join('`%s` %d pairs on %s mentions'
                   % (r['entity'], r['dag_degree'], format(r['corpus_mentions'], ','))
                   for r in _wc[1:])))
w('')
w('### Thin endpoints that block measurement')
w('')
w(f"These entities are each below the {m['measurable_floor']}-mention floor and between them make "
  f"{h['existing_unmeasurable']} DAG pairs unjudgeable. Top 15:")
w('')
w('| entity | kind | corpus mentions | DAG pairs made unmeasurable | has surface forms |')
w('|---|---|---|---|---|')
for r in S['thin_endpoints_blocking_measurement'][:15]:
    w(f"| {r['entity']} | {r['kind']} | {r['corpus_mentions']:,} | "
      f"{r['dag_pairs_it_makes_unmeasurable']} | {r['has_surface_forms']} |")
w('')
w('This independently confirms the CONTENT DEBT note already written into `driver_slices.yaml`: '
  '`managed_money_positioning` (0 corpus mentions, blocks 14 pairs) and `cftc_positioning` '
  '(blocks 22) are named there as slices reachable from 11 and 20 contracts while holding zero and '
  'one props respectively. The state_marker family -- `export_pace_lag` (31 pairs), '
  '`tenderable_collapse` (23), `withheld_supply` (17), `flowering_stress` (17), `replanting_cycle` '
  '(10) -- is the other half: these are minted concepts with no corpus surface form at all.')
w('')

w('## Best-supported existing edges (positive control)')
w('')
w('The audit is not systematically blind: the top-supported edges are the ones a desk would name first.')
w('')
table([dict(r, edge_types_s=', '.join(r['edge_types'])[:30],
            dag_contracts_s=str(len(r['dag_contracts'])) + ' DAGs')
       for r in a['best_supported_existing_edges'][:15]], UC, UH)

w('## Corpus coverage by commodity slice')
w('')
w('| slice | chunks with >=1 vocab hit |')
w('|---|---|')
for k, v in sorted(c['per_commodity_slice'].items(), key=lambda kv: -kv[1]):
    w(f'| {k} | {v:,} |')
w('')

w('## Gaps and caveats')
w('')
w('1. **pg was unreachable** (VPC-internal); the flat S3 slices carry the same props, so this is a '
   'route change, not a data change.')
w(f"2. **Sentence-scale co-mention.** Mean chunk is {c['mean_chunk_chars']} chars. Any mechanism that "
   'spans two sentences is invisible at prop level; the document level is reported alongside for exactly '
   'this reason.')
w(f"3. **{h['existing_unmeasurable']} of {h['distinct_undirected_pairs']} pairs are unmeasurable** and "
   f"**{h['unmapped_dag_endpoint_names']} DAG driver ids have no surface form**, all already waivered. "
   'Roughly half the DAG cannot be audited from text until those endpoints get surface forms.')
w('4. **Co-mention is not causation.** A high-lift pair (import_tariff x quota) can just be two words '
   'that live in the same policy sentence.')
w(f"5. **{m['degenerate_pairs_excluded_from_new_candidates']} degenerate pairs** share a surface form; "
   'excluded from new candidates, flagged elsewhere. Nested forms (e.g. "feed wheat" inside a '
   'wheat_corn_spread term list) are flagged, not dropped.')
w('6. **Directionality and sign were not tested.** Co-mention is symmetric; nothing here says which way '
   'an edge points or whether the authored sign is right.')

open(os.path.splitext(P)[0] + '.md', 'w', encoding='utf-8').write('\n'.join(L) + '\n')
print('wrote', os.path.splitext(P)[0] + '.md', len('\n'.join(L)), 'chars')
