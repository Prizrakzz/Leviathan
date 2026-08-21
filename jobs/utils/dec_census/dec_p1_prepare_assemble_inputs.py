"""Build the dec_p1 side-inputs dec_p0_assemble.py reads, with THE PRIORS RE-POINTED.

The assembler hardcodes two stale priors. Left alone they make the whole `vs_prior_census` block
a TWO-VINTAGE delta -- config drift and corpus growth mixed into one number, which is exactly the
comparison the wave must not make:

  * the write manifest was `write_manifest_rebuild_20260803T134404Z.json`. The X2 routing pass has
    since written `write_manifest_rebuild_20260820T180701Z.json`, and that one matches the live
    objects byte-for-byte (verified: 43/43 commodity + 120/120 driver exact).
  * the prior census was `configs/graphrag/eval/e1_census.json` -- a 2026-08-02 artifact carrying
    361 ids / 142 dark / 109 slices, i.e. TWO config vintages back (causal hash 482c0e2554e6 was
    itself already newer than it). Re-pointed at `data/dec_p0/slice_census.json`, the DEC-P0
    census: the immediately preceding vintage and the sole pre-X2 baseline. The delta is then
    one vintage and means "what the corpus doubling did".

Also mirrors the S3 listing and the chunks/ snapshot into the shapes the assembler expects.
Pure local file shuffling: no S3 calls, no writes outside the scratchpad.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

REPO = Path("C:/Users/User/Desktop/Leviathan")
SCRATCH = Path(r"C:/Users/User/AppData/Local/Temp/claude/"
               r"C--Users-User-Desktop-Leviathan/360a169c-9409-4bdb-af00-a02392ed35a2/scratchpad")
EV = "graphrag_evidence/"
MANIFEST = "write_manifest_rebuild_20260820T180701Z.json"

# ---- 1. s3list: {"top": [[rel, bytes, lm]], "drivers": [[rel, bytes, lm]]} -------------------
ev_list = json.loads((SCRATCH / "dec_p1_ev_listing.json").read_text(encoding="utf-8"))
top, drivers = [], []
for k, size, lm in ev_list:
    rel = k[len(EV):]
    if rel.endswith(".jsonl") and "/" not in rel and not rel.startswith("_"):
        top.append([rel, size, lm])
    elif rel.startswith("drivers/") and rel.endswith(".jsonl") and rel.count("/") == 1:
        drivers.append([rel[len("drivers/"):], size, lm])
top.sort()
drivers.sort()
(SCRATCH / "dec_p1_s3list.json").write_text(
    json.dumps({"top": top, "drivers": drivers}), encoding="utf-8")
print(f"s3list: commodity {len(top)} | drivers {len(drivers)}")

# ---- 2. chunks/ cache summary ---------------------------------------------------------------
snap = json.loads((SCRATCH / "dec_p1_chunks_snapshot.json").read_text(encoding="utf-8"))
(SCRATCH / "dec_p1_chunks.json").write_text(json.dumps({
    "n_objects": snap["n_objects"], "bytes": snap["total_bytes"],
    "lm_min": snap["oldest_last_modified"], "lm_max": snap["newest_last_modified"],
}), encoding="utf-8")
print(f"chunks: {snap['n_objects']:,} objects / {snap['total_bytes']:,} B / "
      f"newest {snap['newest_last_modified']}")

# ---- 3. the write manifest (X2 vintage) -----------------------------------------------------
src = SCRATCH / MANIFEST
if not src.exists():
    raise SystemExit(f"missing {src} -- run dec_p0_fetch_cache.py first (it downloads it)")
(SCRATCH / "dec_p1_write_manifest.json").write_text(
    src.read_text(encoding="utf-8"), encoding="utf-8")
print(f"write manifest: {MANIFEST}")

# ---- 4. THE PRIOR: DEC-P0's own census, adapted to the assembler's expected shape ------------
p0 = json.loads((REPO / "data" / "dec_p0" / "slice_census.json").read_text(encoding="utf-8"))
p0_slices = p0["slices"]
orph = p0.get("orphans") or {}
prior = {
    "prior_artifact": "data/dec_p0/slice_census.json (DEC-P0, 2026-08-19/20, pre-X2)",
    "id_totals": p0["id_totals"],
    "slice_totals": {
        "n_consumed": sum(1 for s in p0_slices
                          if s.get("layer") == "driver" and s.get("consumed")),
        "orphan_by_kind": {k: len(v) for k, v in orph.items()},
        "n_thick_with_thin_eras": sum(1 for s in p0_slices if s.get("thin_eras")),
    },
    # the assembler reads prior rows as `n_routed_props`; DEC-P0 stored the same quantity as
    # `n_props` (the measured population of the slice object).
    "slices": [{"slice": s["slice"], "layer": s.get("layer"),
                "n_routed_props": s.get("n_props"), "n_props": s.get("n_props"),
                "era_hist": s.get("era_hist"), "bytes": s.get("bytes")}
               for s in p0_slices],
}
(SCRATCH / "dec_p1_prior.json").write_text(json.dumps(prior, indent=1), encoding="utf-8")
print("prior: data/dec_p0/slice_census.json -> %d slices | ids %s | slice_totals %s"
      % (len(prior["slices"]), json.dumps(prior["id_totals"]),
         json.dumps(prior["slice_totals"])))
print("wrote dec_p1_{s3list,chunks,write_manifest,prior}.json")
