"""DEC-P0 step A: build the matcher entity set + the EXISTING edge list from configs.

Sources (read, never guessed):
  configs/graphrag/entity_vocabulary.yaml   nodes + aliases (surface forms)
  configs/graphrag/driver_slices.yaml       109 slice term lists + dag_alias + waivers
  configs/graphrag/commodity_hierarchy.yaml contract -> node
  configs/graphrag/causal/*.yaml            33 DAGs: drivers[].parents/edge_type, inter_commodity, convergence

Writes scratch/dec_p0_model.json
"""
import glob
import json
import os
import re
import unicodedata

import yaml

CFG = r'C:/Users/User/Desktop/Leviathan/configs/graphrag'
SCRATCH = r'C:/Users/User/AppData/Local/Temp/claude/C--Users-User-Desktop-Leviathan/360a169c-9409-4bdb-af00-a02392ed35a2/scratchpad'


def load(p):
    return yaml.safe_load(open(os.path.join(CFG, p), encoding='utf-8'))


def norm(s):
    """Normalize a name for identity matching: strip accents, lower, non-alnum -> _."""
    s = unicodedata.normalize('NFKD', str(s))
    s = ''.join(c for c in s if not unicodedata.combining(c))
    s = s.lower().replace("'", '')
    s = re.sub(r'[^a-z0-9]+', '_', s).strip('_')
    return s


vocab = load('entity_vocabulary.yaml')
ds = load('driver_slices.yaml')
hier = load('commodity_hierarchy.yaml')

# ---------------------------------------------------------------- entities
# entity id -> {kind, surfaces:set, sources:set}
ent = {}


def add(eid, kind, surfaces):
    e = ent.setdefault(eid, {'kind': kind, 'surfaces': set(), 'kinds': set()})
    e['kinds'].add(kind)
    for s in surfaces:
        s = str(s).strip()
        if s:
            e['surfaces'].add(s)


# vocab nodes: canonical id -> its own name (underscores -> spaces too)
alias_to_canon = {}
for kind, names in vocab['nodes'].items():
    if not names:
        continue
    for n in names:
        eid = norm(n)
        add(eid, kind, [n, str(n).replace('_', ' ')])
        alias_to_canon[norm(n)] = eid

for canon, als in (vocab.get('aliases') or {}).items():
    eid = norm(canon)
    if eid not in ent:
        add(eid, 'alias_only', [canon, str(canon).replace('_', ' ')])
    for a in als:
        add(eid, ent[eid]['kind'], [a, str(a).replace('_', ' ')])
        alias_to_canon[norm(a)] = eid

# driver slices: slice name -> terms. Fold into a vocab canonical when the slice name
# (or one of its dag_alias DAG-driver ids) resolves to one; otherwise it is its own entity.
dag_alias = ds.get('dag_alias') or {}
slice_entity = {}
for sl, spec in ds['drivers'].items():
    terms = spec.get('terms') or []
    target = alias_to_canon.get(norm(sl))
    if target is None:
        for did in dag_alias.get(sl, []):
            t = alias_to_canon.get(norm(did))
            if t is not None:
                target = t
                break
    eid = target or norm(sl)
    slice_entity[sl] = eid
    # ONLY the configured term list is a surface form. The slice NAME is deliberately NOT
    # injected: driver_slices.yaml keeps terms specific on purpose ("heat wave" not bare
    # "heat", "natural gas" not "gas"), and adding the name back would re-create exactly the
    # over-firing the config comment warns about.
    add(eid, spec.get('category') or 'driver_slice', terms)
    ent[eid].setdefault('slices', set())
    ent[eid]['slices'] = set(ent[eid].get('slices', set())) | {sl}

# DAG driver id -> entity resolution
dag_driver_to_ent = {}
for sl, dids in dag_alias.items():
    for did in dids:
        dag_driver_to_ent.setdefault(norm(did), slice_entity.get(sl, norm(sl)))

waivers = ds.get('waivers') or {}

# contract -> node
contract_node = {c: v['node'] for c, v in (hier.get('contracts') or {}).items()}


def resolve_dag_driver(did):
    n = norm(did)
    if n in alias_to_canon:
        return alias_to_canon[n], 'vocab'
    if n in dag_driver_to_ent:
        return dag_driver_to_ent[n], 'dag_alias'
    if n in ent:
        return n, 'self'
    return None, 'unmapped'


def resolve_commodity(name):
    n = norm(name)
    if name in contract_node:
        return norm(contract_node[name]), 'hierarchy'
    if n in alias_to_canon:
        return alias_to_canon[n], 'vocab'
    if n in ent:
        return n, 'self'
    return None, 'unmapped'


# ---------------------------------------------------------------- edges
edges = []          # list of dicts
unmapped_ends = {}

for p in sorted(glob.glob(os.path.join(CFG, 'causal', '*.yaml'))):
    dag = yaml.safe_load(open(p, encoding='utf-8'))
    contract = dag['contract']
    cnode, chow = resolve_commodity(contract)
    if cnode is None:
        cnode = norm(contract)
        add(cnode, 'commodity', [contract, contract.replace('_', ' ')])
    drv = dag.get('drivers') or []
    for d in drv:
        did = d['id']
        dent, dhow = resolve_dag_driver(did)
        if dent is None:
            unmapped_ends[did] = unmapped_ends.get(did, 0) + 1
        edges.append({'src': dent, 'src_raw': did, 'src_how': dhow,
                      'dst': cnode, 'dst_raw': contract, 'kind': 'driver_to_contract',
                      'edge_type': d.get('edge_type'), 'sign': d.get('sign'),
                      'contract': contract, 'confidence': d.get('confidence'),
                      'silver_status': d.get('silver_status'),
                      'mechanism': (d.get('mechanism') or '')[:400]})
        for par in (d.get('parents') or []):
            pent, phow = resolve_dag_driver(par)
            if pent is None:
                unmapped_ends[par] = unmapped_ends.get(par, 0) + 1
            edges.append({'src': pent, 'src_raw': par, 'src_how': phow,
                          'dst': dent, 'dst_raw': did, 'kind': 'parent_to_driver',
                          'edge_type': 'causes', 'sign': d.get('sign'),
                          'contract': contract, 'confidence': d.get('confidence'),
                          'silver_status': None,
                          'mechanism': (d.get('mechanism') or '')[:400]})
    for ic in (dag.get('inter_commodity') or []):
        oc = ic.get('driver_commodity')
        oent, ohow = resolve_commodity(oc)
        if oent is None:
            unmapped_ends[oc] = unmapped_ends.get(oc, 0) + 1
        edges.append({'src': oent, 'src_raw': oc, 'src_how': ohow,
                      'dst': cnode, 'dst_raw': contract, 'kind': 'inter_commodity',
                      'edge_type': ic.get('relation'), 'sign': ic.get('sign'),
                      'contract': contract, 'confidence': None, 'silver_status': None,
                      'mechanism': (ic.get('mechanism') or '')[:400]})
    for cv in (dag.get('convergence') or []):
        for inter in (cv.get('interactions') or []):
            w = inter.get('when') or []
            for i in range(len(w)):
                for j in range(i + 1, len(w)):
                    a, ahow = resolve_dag_driver(w[i])
                    b, bhow = resolve_dag_driver(w[j])
                    edges.append({'src': a, 'src_raw': w[i], 'src_how': ahow,
                                  'dst': b, 'dst_raw': w[j], 'kind': 'convergence_interaction',
                                  'edge_type': inter.get('effect'), 'sign': None,
                                  'contract': contract, 'confidence': None,
                                  'silver_status': None,
                                  'mechanism': (inter.get('note') or '')[:400]})

out = {
    'entities': {k: {'kind': sorted(v['kinds'])[0], 'kinds': sorted(v['kinds']),
                     'n_surfaces': len(v['surfaces']),
                     'surfaces': sorted(v['surfaces']),
                     'slices': sorted(v.get('slices', []))}
                 for k, v in ent.items()},
    'edges': edges,
    'unmapped_endpoints': unmapped_ends,
    'waivers': {k: v for k, v in waivers.items()},
    'contract_node': contract_node,
}
json.dump(out, open(os.path.join(SCRATCH, 'dec_p0_model.json'), 'w', encoding='utf-8'))

pairs = set()
for e in edges:
    if e['src'] and e['dst'] and e['src'] != e['dst']:
        pairs.add(tuple(sorted((e['src'], e['dst']))))
print('entities', len(ent))
print('edges (rows)', len(edges))
print('distinct undirected mapped pairs', len(pairs))
print('unmapped endpoint names', len(unmapped_ends), 'occurrences', sum(unmapped_ends.values()))
print('waivered of those', sum(1 for k in unmapped_ends if k in waivers))
from collections import Counter
print('edge kinds', Counter(e['kind'] for e in edges))
print('src_how', Counter(e['src_how'] for e in edges))
print('surfaces total', sum(len(v['surfaces']) for v in ent.values()))
