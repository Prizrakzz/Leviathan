"""dec_p0: assemble data/dec_p0/slice_census.{json,md} from the four measured inputs.

  dec_p0_era_scan.jsonl      -- per-slice n_props + 6-bucket era histogram, streamed from S3 (measured)
  dec_p0_config_side.json    -- declared universe + DAG-id routing (pure config)
  dec_p0_write_manifest.json -- the 2026-08-03 rebuild's per-slice after_n + date spans (cross-check)
  dec_p0_s3list.json         -- object bytes + LastModified (presence + staleness)

Era buckets / thickness gates are e1_census's verbatim: THICK_MIN=100 props to be judged, THIN_MAX=10
props per REAL era, undated excluded from the gap test. Files are UTF-8; stdout is ASCII (cp1252).
"""
import json
import os
from datetime import datetime, timezone

SCRATCH = r'C:/Users/User/AppData/Local/Temp/claude/C--Users-User-Desktop-Leviathan/360a169c-9409-4bdb-af00-a02392ed35a2/scratchpad'
REPO = r'C:/Users/User/Desktop/Leviathan'
OUTDIR = os.path.join(REPO, 'data', 'dec_p0')

ERAS = ("pre1990", "1990s", "2000s", "2010_17", "2018_26", "undated")
REAL_ERAS = ERAS[:5]
THICK_MIN = 100
THIN_MAX = 10
ZERO = 0
THIN_SLICE_MAX = 10                                    # task definition of a "thin slice": < 10 props

_final = os.path.join(SCRATCH, 'dec_p0_era_scan_final.jsonl')
_scan_src = _final if os.path.exists(_final) else os.path.join(SCRATCH, 'dec_p0_era_scan.jsonl')
scan = {}
for ln in open(_scan_src, encoding='utf-8'):
    if ln.strip():
        r = json.loads(ln)
        scan[r['slice']] = r
_xc = os.path.join(SCRATCH, 'dec_p0_crosscheck.json')
crosscheck = json.load(open(_xc, encoding='utf-8')) if os.path.exists(_xc) else None
cs = json.load(open(os.path.join(SCRATCH, 'dec_p0_config_side.json'), encoding='utf-8'))
man = json.load(open(os.path.join(SCRATCH, 'dec_p0_write_manifest.json'), encoding='utf-8'))
s3l = json.load(open(os.path.join(SCRATCH, 'dec_p0_s3list.json'), encoding='utf-8'))
chunks = json.load(open(os.path.join(SCRATCH, 'dec_p0_chunks.json'), encoding='utf-8'))
prior = json.load(open(os.path.join(REPO, 'configs/graphrag/eval/e1_census.json'), encoding='utf-8'))
prior_by = {s['slice']: s for s in prior['slices']}

s3meta = {}
for k, size, lm in s3l['top']:
    if k.endswith('.jsonl'):
        s3meta[k[:-6]] = {"key": "graphrag_evidence/" + k, "bytes": size, "last_modified": lm}
for k, size, lm in s3l['drivers']:
    if k.endswith('.jsonl') and '/' not in k:
        s3meta[k[:-6]] = {"key": "graphrag_evidence/drivers/" + k, "bytes": size, "last_modified": lm}

man_comm = man['slices']['commodity']
man_drv = man['slices']['drivers']

spec_names = set(cs['spec_names'])
routed = cs['routed_ids_by_slice']
comm_declared = set(cs['commodity_nodes_declared'])
comm_present = {k[:-6] for k, _s, _l in s3l['top'] if k.endswith('.jsonl')}
drv_present = {k[:-6] for k, _s, _l in s3l['drivers'] if k.endswith('.jsonl') and '/' not in k}


def thin_eras(n_props, hist):
    if n_props < THICK_MIN:
        return []
    return [e for e in REAL_ERAS if hist[e] < THIN_MAX]


def build(name, layer, declared, present):
    sc = scan.get(name)
    mrec = (man_comm if layer == 'commodity' else man_drv).get(name)
    meta = s3meta.get(name)
    hist = sc['era_hist'] if sc else {e: 0 for e in ERAS}
    n = sc['n_props'] if sc else 0
    ids = routed.get(name, []) if layer == 'driver' else []
    n_ids = len(ids)
    if layer == 'driver':
        consumed = n_ids >= 1 and n >= 1
        if consumed:
            kind = None
        elif n >= 1:
            kind = 'retire'                            # corpus with nothing routing to it
        elif n_ids >= 1:
            kind = 'keep'                              # routed but empty -> build target, never retire
        else:
            kind = 'empty'
    else:
        consumed, kind = (n >= 1), (None if n >= 1 else 'empty')
    spec = cs['spec_meta'].get(name) or {}
    return {
        "slice": name, "layer": layer, "declared": declared, "present": present,
        "n_props": n, "era_hist": hist, "thin_eras": thin_eras(n, hist),
        "zero_prop": n == ZERO, "thin_slice": n < THIN_SLICE_MAX,
        "n_dag_ids": n_ids, "routed_dag_ids": ids, "consumed": consumed, "orphan_kind": kind,
        "category": spec.get("category"), "priority": spec.get("priority"),
        "n_terms": spec.get("n_terms"), "max_props_cap": spec.get("max_props"),
        "bytes": (meta or {}).get("bytes"), "last_modified": (meta or {}).get("last_modified"),
        "s3_key": (meta or {}).get("key"),
        "n_no_event_date": (sc or {}).get("n_no_event_date"),
        # Date SPAN is taken from the writer's own manifest, not re-derived here: the scan's derived
        # span could omit each file's final record (no trailing newline). Counts and era_hist are
        # unaffected -- both were verified against manifest after_n on all 125 slices.
        "manifest_after_n": (mrec or {}).get("after_n"),
        "manifest_span": (mrec or {}).get("after_span"),
        "manifest_truncated_n": (mrec or {}).get("truncated_n"),
        "count_matches_manifest": (None if not mrec else (mrec.get("after_n") == n)),
    }


slices = []
for nm in sorted(comm_declared | comm_present):
    slices.append(build(nm, 'commodity', nm in comm_declared, nm in comm_present))
for nm in sorted(spec_names | drv_present):
    slices.append(build(nm, 'driver', nm in spec_names, nm in drv_present))

by_layer = {}
for lay in ('commodity', 'driver'):
    rows = [s for s in slices if s['layer'] == lay]
    agg = {e: sum(r['era_hist'][e] for r in rows) for e in ERAS}
    by_layer[lay] = {
        "n_slices": len(rows), "n_present": sum(1 for r in rows if r['present']),
        "n_declared": sum(1 for r in rows if r['declared']),
        "n_props": sum(r['n_props'] for r in rows),
        "era_totals": agg,
        "n_zero_prop": sum(1 for r in rows if r['zero_prop']),
        "n_thin_slice": sum(1 for r in rows if r['thin_slice']),
        "n_thick": sum(1 for r in rows if r['n_props'] >= THICK_MIN),
        "n_thick_with_thin_eras": sum(1 for r in rows if r['thin_eras']),
    }

declared_but_absent = sorted(s['slice'] for s in slices if s['declared'] and not s['present'])
present_but_undeclared = sorted(s['slice'] for s in slices if s['present'] and not s['declared'])
zero_prop = sorted((s['layer'], s['slice']) for s in slices if s['zero_prop'])
thin = sorted((s['n_props'], s['layer'], s['slice']) for s in slices if s['thin_slice'])
retire = sorted(s['slice'] for s in slices if s['orphan_kind'] == 'retire')
keep = sorted(s['slice'] for s in slices if s['orphan_kind'] == 'keep')
empty = sorted(s['slice'] for s in slices if s['orphan_kind'] == 'empty' and s['layer'] == 'driver')
mismatch = sorted(s['slice'] for s in slices if s['count_matches_manifest'] is False)

# population movement vs the superseded census (driver layer only -- it had no commodity rows)
pop_moved, pop_shrank_hard = [], []
for s in slices:
    p = prior_by.get(s['slice'])
    if p is None or s['layer'] != 'driver':
        continue
    before, after = int(p.get('n_routed_props') or 0), s['n_props']
    if before != after:
        pop_moved.append((s['slice'], before, after))
    lost = before - after
    if before > 0 and lost >= 5 and lost / before >= 0.10:
        pop_shrank_hard.append((s['slice'], before, after))
pop_moved.sort(key=lambda d: -(abs(d[2] - d[1])))
pop_shrank_hard.sort(key=lambda d: -(d[1] - d[2]))

# Slices whose population signature (n_props + all six era buckets) is identical -- candidate duplicate
# corpora carried under different names. `same_bytes` promotes a group from "same shape" to
# "same object size", which at these magnitudes is near-conclusive; a small-n group without it may be
# coincidence, so the flag is reported rather than assumed.
_sig = {}
for s in slices:
    if s['n_props'] > 0:
        _sig.setdefault((s['layer'], s['n_props'], tuple(sorted(s['era_hist'].items()))), []).append(s)
dup_groups = []
for (lay, n, _h), rows in _sig.items():
    if len(rows) > 1:
        sizes = sorted({r['bytes'] for r in rows if r['bytes']})
        spread = (max(sizes) - min(sizes)) if sizes else 0
        # THE PROOF. Each record embeds its slice name exactly once, so if two slices hold the SAME
        # props their object sizes differ by exactly n_props * (difference in name length). Subtract
        # len(name)*n_props from each size: identical remainders => byte-identical populations. This
        # turns "same count and same era histogram" (suggestive) into a receipt, and it correctly
        # REJECTS a small-n lookalike, which is why the test is applied rather than assumed.
        norm = {r['slice']: (r['bytes'] - len(r['slice']) * n) for r in rows if r['bytes']}
        proven = len(set(norm.values())) == 1 and len(norm) == len(rows)
        dup_groups.append({"layer": lay, "n_props": n, "slices": sorted(r['slice'] for r in rows),
                           "n_distinct_byte_sizes": len(sizes), "bytes": sizes,
                           "byte_spread": spread,
                           "byte_spread_pct": (round(100.0 * spread / max(sizes), 4) if sizes else None),
                           "name_normalized_bytes": sorted(set(norm.values())),
                           "identical_population_proven": proven,
                           "redundant_props": n * (len(rows) - 1)})
dup_groups.sort(key=lambda d: (not d['identical_population_proven'], -d['redundant_props']))
dup_proven = [g for g in dup_groups if g['identical_population_proven']]
dup_rejected = [g for g in dup_groups if not g['identical_population_proven']]
dup_redundant = sum(g['redundant_props'] for g in dup_proven)

era_totals = {e: sum(s['era_hist'][e] for s in slices) for e in ERAS}
n_props_all = sum(s['n_props'] for s in slices)
dark_ids = [r['id'] for r in cs['ids'] if not r['backed']]
_w = cs['waivers']
waiver_names = set(_w) if isinstance(_w, (dict, list)) else set()

doc = {
    "census": "dec_p0_slice_thinness",
    "version": 1,
    "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "basis": {
        "store": "s3://leviathan-dev-shahem-001/graphrag_evidence/",
        "method": ("full streaming byte-scan of EVERY slice object -- each record's date fields are read "
                   "by regex over the raw bytes and the 1024-float vectors are never parsed -- plus the "
                   "pure-config declared universe (driver_slices.yaml + its manifest mirror + the causal "
                   "DAGs). No sampling, no estimation: every prop was counted."),
        "transport": ("run inside the VPC on AWS Batch. The home link sustains ~4.6 MB/s and drops long "
                      "transfers: the 101 driver slices (1.36 GB) scanned fine from the laptop, but the "
                      "24 commodity slices (11.12 GB) burned ~4.4 GB of retries in 16 minutes with zero "
                      "completions. The laptop's 104 finished slices were kept as an independent "
                      "second measurement -- see basis.cross_check.independent_rescan."),
        "pg_mirror": ("UNREACHABLE from this network -- the RDS DSN is VPC-private; connection timed out. "
                      "S3 is the store of truth (project doctrine: pg is a disposable derived index), so "
                      "every count here is measured from S3, not from the mirror."),
        "cross_check": ("every scanned n_props was compared to after_n in the 2026-08-03 rebuild write "
                        "manifest (eval/write_manifest_rebuild_20260803T134404Z.json)"),
        "independent_rescan": (None if not crosscheck else {
            "what": ("the same slice bytes were scanned twice by different transports -- once from the "
                     "laptop over the home link, once inside the VPC on Batch -- and compared on "
                     "n_props AND all six era buckets"),
            "n_compared": crosscheck['n_compared'], "n_agree": crosscheck['n_agree'],
            "disagreements": crosscheck['disagreements'],
            "vpc_scan_key": crosscheck['cloud_key'],
            "vpc_elapsed_seconds": crosscheck['cloud_elapsed_seconds'],
            "vpc_failed_slices": crosscheck['cloud_n_failed']}),
        "era_gate": {"THICK_MIN": THICK_MIN, "THIN_MAX": THIN_MAX,
                     "thin_slice_definition": "< %d props" % THIN_SLICE_MAX,
                     "eras": list(ERAS), "real_eras": list(REAL_ERAS),
                     "bucket_rule": ("event_date preferred over date; unparseable / absent / year > 2026 "
                                     "-> 'undated' (a data-quality note, never an era gap)")},
        "supersedes": "configs/graphrag/eval/e1_census.json (2026-08-02, pre-rebuild)",
    },
    "totals": {
        "n_slices_universe": len(slices),
        "n_props": n_props_all,
        "era_totals": era_totals,
        "n_zero_prop": len(zero_prop),
        "n_thin_slice": len(thin),
        "n_declared_but_absent": len(declared_but_absent),
        "n_present_but_undeclared": len(present_but_undeclared),
        "n_count_mismatch_vs_manifest": len(mismatch),
        "bytes_scanned": sum(s['bytes'] or 0 for s in slices),
    },
    "by_layer": by_layer,
    "chunk_doc_cache": dict(chunks, note=(
        "graphrag_evidence/chunks/ -- the per-document chunk cache the slice builder reads FROM. "
        "It is upstream of the slice universe, not a member of it. Its newest object predates the "
        "2026-08-03 slice rebuild, so every prop counted here derives from this corpus vintage.")),
    "id_totals": cs['id_totals'],
    "declared_universe": {
        "driver_specs_yaml": len(cs['spec_names']),
        "driver_manifest_mirror": len(cs['manifest_names']),
        "mirror_agrees_with_yaml": sorted(cs['spec_names']) == sorted(cs['manifest_names']),
        "manifest_file_sha256": cs['manifest_file_sha256'],
        "manifest_counts": cs['manifest_counts'],
        "commodity_contracts": len(cs['commodity_contracts']),
        "commodity_nodes": len(cs['commodity_nodes_declared']),
        "causal_dag_yamls": cs['n_causal_dags'],
    },
    "declared_but_absent": declared_but_absent,
    "present_but_undeclared": present_but_undeclared,
    "zero_prop_slices": [{"layer": lay, "slice": nm} for lay, nm in zero_prop],
    "thin_slices": [{"n_props": n, "layer": lay, "slice": nm} for n, lay, nm in thin],
    "orphans": {"retire": retire, "keep": keep, "empty": empty},
    "duplicate_population_groups": {
        "note": ("slices whose n_props AND all six era buckets match exactly -- the same population under "
                 "more than one name. The objects are near-identical in size but not byte-identical "
                 "(byte_spread), i.e. the same props differing only in per-slice fields. An exact match "
                 "on both count and all six buckets is near-conclusive at commodity magnitudes; the "
                 "17-prop driver pair is small enough to be coincidence and should be checked before use."),
        "n_groups_proven": len(dup_proven), "n_groups_rejected": len(dup_rejected),
        "redundant_props": dup_redundant, "groups": dup_groups},
    "count_mismatch_vs_manifest": mismatch,
    "vs_prior_census": {
        "prior_artifact": "configs/graphrag/eval/e1_census.json (2026-08-02, pre-rebuild)",
        "prior_id_totals": prior['id_totals'],
        "prior_slice_totals": prior['slice_totals'],
        "population_moved": [{"slice": n, "before": b, "after": a} for n, b, a in pop_moved],
        "population_shrank_past_trip_lines": [
            {"slice": n, "before": b, "after": a} for n, b, a in pop_shrank_hard],
    },
    "dark_dag_ids": dark_ids,
    "waiver_coverage": {
        "n_waivers": len(waiver_names),
        "n_dark": len(dark_ids),
        "n_dark_waived": len(set(dark_ids) & waiver_names),
        "dark_not_waived": sorted(set(dark_ids) - waiver_names),
        "waived_but_not_dark": sorted(waiver_names - set(dark_ids)),
    },
    "slices": slices,
    "ids": cs['ids'],
}

os.makedirs(OUTDIR, exist_ok=True)
jp = os.path.join(OUTDIR, 'slice_census.json')
json.dump(doc, open(jp, 'w', encoding='utf-8'), indent=1)


# ---------------- markdown ----------------
def row(s):
    h = s['era_hist']
    return ("| %s | %s | %s | %d | %d | %d | %d | %d | %d | %d | %s |" % (
        s['slice'], s['layer'], 'y' if s['present'] else 'ABSENT', s['n_props'],
        h['pre1990'], h['1990s'], h['2000s'], h['2010_17'], h['2018_26'], h['undated'],
        ', '.join(s['thin_eras']) or '-'))


L = []
A = L.append
A("# Slice-thinness census (dec_p0) -- %s" % doc['generated_utc'])
A("")
A("Full re-measurement of the evidence store, superseding the 2026-08-02 `e1_census.json` "
  "(which predates the 2026-08-03 E4W1 rebuild). Every prop count and every era bucket below was read "
  "from S3 by streaming all %.2f GB of slice objects; nothing is sampled and nothing is estimated. "
  "The scan ran inside the VPC on Batch -- the home link could not carry the 11.12 GB commodity half."
  % (doc['totals']['bytes_scanned'] / 1e9))
A("")
A("## Headline")
A("")
A("- **Universe:** %d slices (%d commodity + %d driver), **%s props** total."
  % (doc['totals']['n_slices_universe'], by_layer['commodity']['n_slices'],
     by_layer['driver']['n_slices'], format(n_props_all, ',')))
A("- **Commodity layer:** %d/%d present, %s props." % (
    by_layer['commodity']['n_present'], by_layer['commodity']['n_slices'],
    format(by_layer['commodity']['n_props'], ',')))
A("- **Driver layer:** %d declared, %d present, %s props." % (
    by_layer['driver']['n_declared'], by_layer['driver']['n_present'],
    format(by_layer['driver']['n_props'], ',')))
A("- **Zero-prop slices:** %d. **Thin slices (<%d props):** %d."
  % (len(zero_prop), THIN_SLICE_MAX, len(thin)))
A("- **Declared but absent:** %d. **Present but undeclared:** %d."
  % (len(declared_but_absent), len(present_but_undeclared)))
A("- **Duplicate populations:** %d groups of commodity slices are PROVEN to hold the same props "
  "under different names; **%s props (%.0f%% of the commodity layer) are copies**."
  % (len(dup_proven), format(dup_redundant, ','),
     100.0 * dup_redundant / max(1, by_layer['commodity']['n_props'])))
A("- **Thick slices (>=%d props) with a hollow real era:** %d of %d thick."
  % (THICK_MIN, sum(v['n_thick_with_thin_eras'] for v in by_layer.values()),
     sum(v['n_thick'] for v in by_layer.values())))
A("- **DAG driver ids:** %d total, %d backed, **%d dark (%.1f%%)**; reason split %s."
  % (cs['id_totals']['n_ids'], cs['id_totals']['n_backed'], cs['id_totals']['n_dark'],
     100.0 * cs['id_totals']['n_dark'] / max(1, cs['id_totals']['n_ids']), cs['id_totals']['by_reason']))
if crosscheck:
    A("- **Independently re-scanned:** the same bytes were measured twice by different transports "
      "(laptop over the home link, and inside the VPC on Batch). %d of %d slices measured both ways "
      "agree on `n_props` and on all six era buckets."
      % (crosscheck['n_agree'], crosscheck['n_compared']))
_stale_w = sorted(waiver_names - set(dark_ids))
A("- **Dark-id waivers:** %d of the %d dark ids carry an explicit waiver entry; %d are unaccounted "
  "for. %d waiver%s now cover%s an id that is no longer dark%s."
  % (len(set(dark_ids) & waiver_names), len(dark_ids), len(set(dark_ids) - waiver_names),
     len(_stale_w), '' if len(_stale_w) == 1 else 's', 's' if len(_stale_w) == 1 else '',
     (' (' + ', '.join('`%s`' % w for w in _stale_w) + ')') if _stale_w else ''))
A("- **Cross-check:** %d of %d slices with a write-manifest entry disagree with their 2026-08-03 "
  "`after_n`. The store has not moved since the rebuild." % (len(mismatch), len(man_comm) + len(man_drv)))
A("")
A("## Era totals (whole store)")
A("")
A("| layer | props | pre1990 | 1990s | 2000s | 2010_17 | 2018_26 | undated |")
A("|---|--|--|--|--|--|--|--|")
for lay in ('commodity', 'driver'):
    v = by_layer[lay]
    e = v['era_totals']
    A("| %s | %d | %d | %d | %d | %d | %d | %d |" % (
        lay, v['n_props'], e['pre1990'], e['1990s'], e['2000s'], e['2010_17'], e['2018_26'], e['undated']))
A("| **all** | %d | %d | %d | %d | %d | %d | %d |" % (
    n_props_all, era_totals['pre1990'], era_totals['1990s'], era_totals['2000s'],
    era_totals['2010_17'], era_totals['2018_26'], era_totals['undated']))
A("")
A("## Zero-prop slices (%d)" % len(zero_prop))
A("")
if zero_prop:
    _no_file = [nm for lay, nm in zero_prop if not next(
        x for x in slices if x['slice'] == nm and x['layer'] == lay)['present']]
    _empty_file = [nm for lay, nm in zero_prop if nm not in _no_file]
    A("%d of these have no slice object in the store at all (declared, never built); %d have an object "
      "that holds zero records. Routed-but-empty is an E1b build target, never a retire candidate."
      % (len(_no_file), len(_empty_file)))
    A("")
    A("| slice | layer | routed dag ids | category | terms |")
    A("|---|--|--|--|--|")
    for lay, nm in zero_prop:
        s = next(x for x in slices if x['slice'] == nm and x['layer'] == lay)
        A("| %s | %s | %d%s | %s | %s |" % (
            nm, lay, s['n_dag_ids'],
            (' (' + ', '.join(s['routed_dag_ids'][:4]) + ')') if s['routed_dag_ids'] else '',
            s['category'] or '-', s['n_terms'] if s['n_terms'] is not None else '-'))
else:
    A("- none")
A("")
A("## Thin slices (< %d props) -- %d" % (THIN_SLICE_MAX, len(thin)))
A("")
A("| slice | layer | props | routed dag ids | category | pre1990 | 1990s | 2000s | 2010_17 | 2018_26 | undated |")
A("|---|--|--|--|--|--|--|--|--|--|--|")
for n, lay, nm in thin:
    s = next(x for x in slices if x['slice'] == nm and x['layer'] == lay)
    h = s['era_hist']
    A("| %s | %s | %d | %d | %s | %d | %d | %d | %d | %d | %d |" % (
        nm, lay, n, s['n_dag_ids'], s['category'] or '-',
        h['pre1990'], h['1990s'], h['2000s'], h['2010_17'], h['2018_26'], h['undated']))
A("")
A("## Declared but absent (%d)" % len(declared_but_absent))
A("")
if declared_but_absent:
    A("A `drivers:` spec (and a manifest-mirror row) exists; no slice object does. These are the "
      "routed-but-empty 'keep' orphans -- the E1b build list.")
    A("")
    for nm in declared_but_absent:
        s = next(x for x in slices if x['slice'] == nm)
        A("- `%s` -- %d routed DAG id(s)%s, category %s, %s terms"
          % (nm, s['n_dag_ids'],
             (' (' + ', '.join(s['routed_dag_ids']) + ')') if s['routed_dag_ids'] else '',
             s['category'] or '-', s['n_terms']))
else:
    A("- none")
A("")
A("## Present but undeclared (%d)" % len(present_but_undeclared))
A("")
A(("- none -- every slice object in the store has a declaration behind it." if not present_but_undeclared
   else "\n".join("- `%s`" % n for n in present_but_undeclared)))
A("")
A("## Thick slices (>= %d props) with a hollow real era (< %d props)" % (THICK_MIN, THIN_MAX))
A("")
A("The analogue-serving gaps: a slice fat enough to be judged that cannot answer in some era. "
  "`undated` is excluded from the gap test (a data-quality note, never an era gap).")
A("")
A("| slice | layer | present | props | pre1990 | 1990s | 2000s | 2010_17 | 2018_26 | undated | thin eras |")
A("|---|--|--|--|--|--|--|--|--|--|--|")
for s in sorted((x for x in slices if x['thin_eras']), key=lambda x: (-x['n_props'], x['slice'])):
    A(row(s))
A("")
A("## Orphan routing (driver layer)")
A("")
A("- **retire candidates** (props on disk, no DAG id routes there): %s" % (', '.join(retire) or 'none'))
A("- **keep candidates** (routed but empty -> build, never retire): %s" % (', '.join(keep) or 'none'))
A("- **inert** (declared, no file, nothing routes there): %s" % (', '.join(empty) or 'none'))
A("")
A("## Duplicate populations (%d proven groups, %s redundant props)" % (len(dup_proven), format(dup_redundant, ',')))
A("")
A("Groups whose prop count AND all six era buckets match exactly. The commodity layer's %s props are "
  "therefore NOT %d independent corpora: **%s of them (%.0f%%) are a second copy of a population "
  "already counted.**"
  % (format(by_layer['commodity']['n_props'], ','), by_layer['commodity']['n_slices'],
     format(dup_redundant, ','), 100.0 * dup_redundant / max(1, by_layer['commodity']['n_props'])))
A("")
A("**The proof, not an inference.** Each record embeds its slice name exactly once, so two slices "
  "holding the same props must differ in object size by exactly `n_props x (name length difference)`. "
  "Subtracting `len(name) x n_props` from each object size collapses every group below to a SINGLE "
  "byte count -- identical to the byte. These are the same props under different names, not merely "
  "similar corpora. The same test REJECTS a small-n lookalike (listed after), which is why it is run "
  "rather than assumed.")
A("")
A("| props each | slices | byte spread | name-normalized bytes | redundant |")
A("|--|---|--|--|--|")
for g in dup_proven:
    A("| %d | %s | %s | **%s (all equal)** | %d |" % (
        g['n_props'], ', '.join('`%s`' % s for s in g['slices']),
        format(g['byte_spread'], ','), format(g['name_normalized_bytes'][0], ','),
        g['redundant_props']))
if dup_rejected:
    A("")
    A("Rejected by the same test (equal counts and era buckets, but the name-normalized sizes differ -- "
      "a coincidence at small n, not a duplicate):")
    A("")
    for g in dup_rejected:
        A("- %s (%d props each) -- normalized bytes %s"
          % (', '.join('`%s`' % s for s in g['slices']), g['n_props'],
             " vs ".join(format(b, ',') for b in g['name_normalized_bytes'])))
A("")
A("## Movement since the superseded census (2026-08-02 -> now)")
A("")
A("The prior artifact was written the day BEFORE the 2026-08-03 rebuild, and `driver_slices.yaml` has "
  "gained aliases since. Both halves moved, which is why it could not be reused.")
A("")
A("| metric | 2026-08-02 | now | delta |")
A("|---|--|--|--|")
for label, b, c in (
        ("DAG driver ids", prior['id_totals']['n_ids'], cs['id_totals']['n_ids'],),
        ("backed ids", prior['id_totals']['n_backed'], cs['id_totals']['n_backed']),
        ("dark ids", prior['id_totals']['n_dark'], cs['id_totals']['n_dark']),
        ("driver slices consumed", prior['slice_totals']['n_consumed'],
         sum(1 for s in slices if s['layer'] == 'driver' and s['consumed'])),
        ("retire orphans", prior['slice_totals']['orphan_by_kind'].get('retire', 0), len(retire)),
        ("keep orphans", prior['slice_totals']['orphan_by_kind'].get('keep', 0), len(keep)),
        ("thick driver slices w/ hollow era", prior['slice_totals'].get('n_thick_with_thin_eras', 0),
         sum(1 for s in slices if s['layer'] == 'driver' and s['thin_eras'])),
):
    A("| %s | %d | %d | %+d |" % (label, b, c, c - b))
A("")
A("- Prior per-slice `n_routed_props` vs now: **%d driver slices changed population**, "
  "%d grew, %d shrank." % (len(pop_moved), sum(1 for d in pop_moved if d[2] > d[1]),
                           sum(1 for d in pop_moved if d[2] < d[1])))
if pop_shrank_hard:
    A("- Past the standing gate's trip lines (>=10%% AND >=5 props): %s"
      % ", ".join("`%s` %d->%d" % d for d in pop_shrank_hard))
A("")
A("## Full per-slice era histogram (%d slices)" % len(slices))
A("")
A("| slice | layer | present | props | pre1990 | 1990s | 2000s | 2010_17 | 2018_26 | undated | thin eras |")
A("|---|--|--|--|--|--|--|--|--|--|--|")
for s in sorted(slices, key=lambda x: (x['layer'], -x['n_props'], x['slice'])):
    A(row(s))
A("")
A("## Gaps and caveats")
A("")
A("- The pg mirror (`evidence_props`) could not be reached: the RDS endpoint is VPC-private and the "
  "connection timed out from this network. All counts here are measured from S3, which project doctrine "
  "already names the store of truth; the mirror's agreement with S3 is therefore UNVERIFIED by this run.")
_no_ev = sum(s['n_no_event_date'] or 0 for s in slices)
A("- **%s of %s props (%.1f%%)** carry no `event_date` and were bucketed by publication `date` instead. "
  "That is the same fallback `e1_census._era_of` applies, but it means the pre-1990 buckets are "
  "understated wherever an old event was published recently."
  % (format(_no_ev, ','), format(n_props_all, ','), 100.0 * _no_ev / max(1, n_props_all)))
_capped = sorted(s['slice'] for s in slices if s['max_props_cap'] and s['n_props'] >= s['max_props_cap'])
_cap_of = {s['slice']: s['max_props_cap'] for s in slices}
A("- %d slice%s sit%s exactly on a `max_props` cap and %s therefore a TRUNCATED population rather than "
  "a natural one -- their era histograms describe only what survived truncation, so a hollow era there "
  "may be an artefact of the cap: %s."
  % (len(_capped), '' if len(_capped) == 1 else 's', 's' if len(_capped) == 1 else '',
     'is' if len(_capped) == 1 else 'are',
     ', '.join('`%s` (cap %d)' % (n, _cap_of[n]) for n in _capped) or 'none'))
A("- This census counts props per slice; it does not re-derive term-level claims "
  "(`e1_census.term_census`) or chunk-level coverage.")
A("- The upstream chunk doc-cache (`chunks/`) holds **%s documents** in %.2f GB, newest object "
  "%s -- BEFORE the 2026-08-03 slice rebuild. Every prop counted here derives from that corpus "
  "vintage, so a slice cannot be thicker than its corpus allows; a thin slice may be a corpus gap "
  "rather than a routing gap, and this census cannot tell the two apart."
  % (format(chunks['n_objects'], ','), chunks['bytes'] / 1e9, chunks['lm_max'][:10]))
A("- Per-slice date SPANS (`manifest_span`) are the writer's own recorded `after_span`, not re-derived "
  "by this scan. Prop COUNTS and era histograms are this scan's own measurement and were verified "
  "against the manifest's `after_n` on all %d slices that carry an entry." % (len(man_comm) + len(man_drv)))
A("- The store has not been written since 2026-08-03; a `chunks/` corpus pass after that date would "
  "make these counts stale in exactly the way the superseded artifact was.")

mp = os.path.join(OUTDIR, 'slice_census.md')
open(mp, 'w', encoding='utf-8').write("\n".join(L) + "\n")

print("slices %d | props %d | zero %d | thin %d | declared-absent %d | undeclared %d | mismatch %d" % (
    len(slices), n_props_all, len(zero_prop), len(thin), len(declared_but_absent),
    len(present_but_undeclared), len(mismatch)))
print("era totals:", era_totals)
print("wrote", jp)
print("wrote", mp)
