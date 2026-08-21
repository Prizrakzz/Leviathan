"""dec_p0/p1: the CONFIG-side census -- declared universe, DAG-id routing, orphan kinds.

Pure function of configs/graphrag/* (no S3, no pg, no model): reuses leviathan.graphrag.evidence
(driver_specs / driver_alias / slice_for_driver) and display.all_driver_ids() exactly as
e1_census.census() does, but WITHOUT e1_census's per-slice S3 GET (the counts come from the era scan).
ASCII stdout only.
"""
import json
import os

import yaml

from leviathan.common import config

config.load_env()

from leviathan.graphrag import display as dp  # noqa: E402
from leviathan.graphrag import e1_census as ec  # noqa: E402
from leviathan.graphrag import evidence as ev  # noqa: E402
from leviathan.graphrag import extract as ex  # noqa: E402

SCRATCH = r'C:/Users/User/AppData/Local/Temp/claude/C--Users-User-Desktop-Leviathan/360a169c-9409-4bdb-af00-a02392ed35a2/scratchpad'

alias_map = ev.driver_alias()                      # {dag_id -> slice_name}: identity + dag_alias + accent-fold
backed = set(alias_map.keys())
all_ids = sorted(dp.all_driver_ids())
specs = ev.driver_specs()
raw = ev._driver_raw()

ids = ec.id_census(all_ids, backed, ev.slice_for_driver)
id_tot = ec.id_totals(ids)

real = set(all_ids)
inv = {}
for dag_id, slice_name in alias_map.items():
    if dag_id in real:
        inv.setdefault(slice_name, []).append(dag_id)

# declared driver universe: driver_slices.yaml `drivers:` + the tracked manifest mirror
man = yaml.safe_load(open(os.path.join(ex._CFG, 'driver_slices_manifest.yaml'), encoding='utf-8'))
man_slices = sorted(man.get('slices') or {})

# declared commodity universe: the causal DAG contracts -> node_for(contract)
hier = yaml.safe_load(open(os.path.join(ex._CFG, 'commodity_hierarchy.yaml'), encoding='utf-8'))
contracts = sorted((hier.get('contracts') or {}))
nodes_declared = sorted({ev.node_for(c) for c in contracts})
all_nodes = sorted(ev.all_nodes())

doc = {
    "id_totals": id_tot,
    "ids": ids,
    "spec_names": sorted(specs),
    "manifest_names": man_slices,
    "manifest_counts": man.get('counts'),
    "manifest_file_sha256": man.get('file_sha256'),
    "spec_meta": {n: {"category": (specs[n] or {}).get("category"),
                      "priority": (specs[n] or {}).get("priority"),
                      "n_terms": len((specs[n] or {}).get("terms") or []),
                      "max_props": (specs[n] or {}).get("max_props")}
                  for n in sorted(specs)},
    "dag_alias_block": {k: sorted(v) for k, v in sorted((raw.get('dag_alias') or {}).items())},
    "waivers": sorted(raw.get('waivers') or []) if isinstance(raw.get('waivers'), list) else raw.get('waivers'),
    "routed_ids_by_slice": {k: sorted(v) for k, v in sorted(inv.items())},
    "commodity_contracts": contracts,
    "commodity_nodes_declared": nodes_declared,
    "commodity_all_nodes": all_nodes,
    "n_causal_dags": len(list((ex._CFG / 'causal').glob('*.yaml'))),
}
out = os.path.join(SCRATCH, 'dec_p1_config_side.json')
json.dump(doc, open(out, 'w', encoding='utf-8'), indent=1)
print("dag ids %d | backed %d | dark %d | reasons %s | fold-recoverable %d" % (
    id_tot['n_ids'], id_tot['n_backed'], id_tot['n_dark'], id_tot['by_reason'],
    id_tot['n_fold_recoverable']))
print("driver specs declared: %d | manifest mirror: %d | agree: %s" % (
    len(specs), len(man_slices), sorted(specs) == man_slices))
print("manifest counts:", man.get('counts'))
print("commodity contracts: %d | declared nodes: %d | all_nodes(): %d" % (
    len(contracts), len(nodes_declared), len(all_nodes)))
print("causal DAG yamls:", doc['n_causal_dags'])
print("slices with >=1 routed real dag id:", len(inv))
print("wrote", out)
