# dec_census — the D-EC census producers, rescued into git (2026-08-21)

These scripts produced every `data/dec_p0/` census artifact (edge_evidence, zero_route_clusters,
slice_census, graph_walk, doc_census, chunk_coverage, thin_slice_fill, projection_census
assembly) during the D-EC wave. They were authored as one-off agent scripts and survived ONLY in
a session temp scratchpad — a temp sweep away from destroying the graph-completion wave's step-1
instruments (the re-census scout's headline risk). Rescued verbatim, mirroring the
jobs/utils/dhp_census/ precedent.

---

## The `_x2` run (graph-completion wave, STAGE 2 — executed 2026-08-21)

The re-census on the doubled corpus. **Outputs go to `data/dec_p1/`. Nothing writes to
`data/dec_p0/`** — that is the sole pre-X2 baseline every "the corpus doubling fed it" claim is
measured against, and these writers use fixed filenames, so one careless re-run would destroy the
denominator. The path re-points below are committed as the run's evolution; `git log` recovers the
dec_p0 originals.

### What changed, and why each change was forced

| file | change | why |
|---|---|---|
| `dec_p0_list.py` | outputs → `dec_p1_*`; emits `dec_p1_chunks_snapshot.json` | the sequencing-trap rider: every artifact's method block carries the chunks/ LIST (count, bytes, newest LastModified) so the judged universe stays identifiable after stage 1 or a re-fire moves it |
| `dec_p0_fetch_cache.py` | `CACHE_DIR` → a FRESH `dec_p1_chunks/`; prior manifest → `write_manifest_rebuild_20260820T180701Z.json` (auto-downloaded) | `x2_tail_resplit.py:357` rewrote 569 existing chunk objects on 2026-08-21 09h (374 MB of 663 MB) and this fetcher skips any local file with size>0 — a resumed pull silently mixes pre- and post-merge props |
| `dec_p0_build_model.py` | output → `dec_p1_model.json` | preserve the pre-X2 model (causal hash `482c0e2554e6`); the config moved under it to `031ce56fec3d` |
| `dec_p0_comention.py` | fresh CHUNKS dir; **`_raw/` leg DROPPED**; `--workers N` | `data/dec_p0/critique.md:59-63,199-200`: ~50,800 of edge_evidence's chunks (12.8%) are not in the live universe and `_raw/` is frozen at the 2026-07-01 vintage. Re-running with it reproduces a known defect at 2x scale |
| `dec_p0_rank.py` | `OUT` → `data/dec_p1/`; corpus string, denominators, causal hash and edge-kind counts all made live | the run book's mandatory edit (c) — record the new denominators verbatim rather than inheriting DEC-P0 prose |
| `dec_p0_md.py`, `dec_p0_examples.py` | → `data/dec_p1/`; samples drawn from `dec_p1_chunks` only | a verbatim sample from outside the judged universe is a receipt for a measurement that did not happen |
| `graph_walk.py` | `OUT` → `data/dec_p1/`; **`ALL_NODES` widened to `ev.all_nodes()`**; **forward-traversability reported under BOTH rules** | (i) the 19 context commodities all have S3 slices now, so the contract-only node set fired 19 phantom `evidence_files_no_node` alarms — both lists are empty after the fix; (ii) the raw-string-equality rule returns 52 and is pre-fix-#68, production resolves 94 via `graph.py:102 _CANONICAL_SEED` |
| `dec_p0_submit_cloud_scan.py` | output key → `dec_p1_era_scan_<STAMP>.json` | keep the dec_p0 scan artifacts; 8 vCPU / 32,768 MB kept deliberately (largest object french_wheat 1.68 GB, queue maxvCpus 32) |
| `dec_p0_merge_scan.py` | looks for a `dec_p1` local twin (there is none) | the laptop-side era scan was NOT re-run at 29.76 GB, so the independent-second-measurement check is legitimately empty rather than silently comparing two vintages |
| `dec_p0_config_side.py` | output → `dec_p1_config_side.json` | — |
| `dec_p0_assemble.py` | `OUTDIR` → `data/dec_p1/`; **both hardcoded priors re-pointed** | the manifest was 2026-08-03 and the prior census was `configs/graphrag/eval/e1_census.json` (2026-08-02, TWO config vintages back). Left alone, every `vs_prior` number would mix config drift with corpus growth |

### New instruments authored for this stage

- **`dark_driver_fillability.py`** (RUN 3) — no prior producer existed. For each of the 123 dark
  DAG driver ids: is the honest move to author terms, bind a silver table, or waive? Terms are
  derived from each driver's OWN `evidence_query`/`blurb`/`mechanism`/`region`, **never from its
  id** (the scout measured id-as-term: 84/123 score zero and the top scorers are generic
  over-fires). Four guards, and **each of the last three exists because the previous version's
  own samples exposed a defect** — this instrument was re-tuned three times against what it
  printed, which is the whole reason G3's samples are mandatory:
  - **G1** multi-token only (the config's "heat wave not heat" rule) — kills the single-word class.
  - **G2** a genericity ceiling **measured**, not chosen: the p90 *independent reach* of the 495
    multi-token terms `driver_slices.yaml` already accepts (median 4 props, max 99,863 → ceiling
    **306**). v1 used a flat 1%-of-corpus ceiling (13,876), dropped 8 terms, and let
    `IOD_negative` score on "Sugar production for Australia".
  - **Reach, not raw hits.** Phase A compiles one longest-first alternation, so a longer term
    shadows a shorter one; Phase B runs a smaller regex where those competitors are gone. That
    mismatch let `hard red` measure 112 props (under the ceiling) and then carry 53% of
    `us_export_pace`'s mass. Genericity is now scored as a term's own hits **plus the hits of
    every term containing it** — `hard red` reaches 2,549 and is refused.
  - **G4** token distinctiveness across the dark set: a term needs ≥1 token rare among the 123
    dark drivers' own authored text. Kills `winter wheat`, `meal price`, `south africa`,
    `crop yield` — phrases the n-gram window manufactures by joining unrelated keywords.
  - **G3** a 60% single-term concentration cap plus 3 mandatory verbatim samples per id. An id
    whose mass rides one term is flagged `concentration_risk` and withheld from FILLABLE.
  - **G5** anchoring: the 100-prop floor is applied to props reached by a term that *names this
    driver* — one carrying a token at most 2 of the 123 dark drivers use anywhere (`conab`,
    `funcafe`, `cecafe`, `heilongjiang`). 120 of 123 ids have one. A driver whose mass rides
    shared phrasing has corpus text about its **topic**, not evidence for itself, and a slice
    authored off that routes other drivers' props into it. Samples are drawn from the anchored
    mass for the same reason — a sample must be evidence for the count it sits under.

  The FILLABLE count moved **109 → 63 → 35 → 38 → 14** across those guard generations, every step
  forced by what the previous version's samples showed. 14 is a deliberate lower bound: residual
  n-gram noise is visible in each row's `anchored_terms` and samples, so the curation stage can
  still reject rows (`flowering` anchors on `during april`, `replanting_cycle` on `area
  reduction`). Phase A is cached per (term set × corpus snapshot), so re-tuning costs only Phase B.
- **`edge_adjudication.py`** — joins graph_walk's 130 structural candidates (the QUESTION) to the
  co-mention census (the ANSWER), adds every edge the plan's F-A itemization names, and applies
  one rule fixed before the numbers were read. Also attributes every delta vs DEC-P0 as `corpus`
  or `vocabulary`: 29 entities entered the vocabulary since DEC-P0, so a DEC-P0 zero on those
  means the entity had no surface forms, NOT that the text was silent.
- **`dec_p1_prepare_assemble_inputs.py`** — builds the assembler's side-inputs with the priors
  re-pointed (see the table above).

### ⚠ Four writers still point at `data/dec_p0/` — re-point before running them

Stage 2 ran RUNs 1–4 plus the adjudication. It did **not** re-run the chunk-coverage,
zero-route-cluster or doc-census producers, so these four still carry hardcoded `data/dec_p0/`
output paths and fixed filenames:

- `dec_p0_write_artifact.py` → `chunk_coverage.json`
- `dec_p0_write_md.py` → `chunk_coverage.md`
- `laneA_build_report.py` → `zero_route_clusters.{json,md}`
- `p0_census.py` → `doc_census.{json,md}`

Running any of them as-is **destroys part of the pre-X2 baseline**. Re-point `OUT` first.
Verified after stage 2: no file under `data/dec_p0/` was modified.

### Re-running it

```
python dec_p0_list.py                       # LISTs only; writes the chunks/ snapshot
python dec_p0_fetch_cache.py                # fresh cache (5,936 objects / 663 MB, ~80 s)
python dec_p0_build_model.py
python dec_p0_comention.py --workers 8      # 1,387,697 props, ~130 s
python dec_p0_rank.py ; python dec_p0_md.py ; python dec_p0_examples.py
python graph_walk.py
python dark_driver_fillability.py --workers 8
python dec_p0_submit_cloud_scan.py          # Batch, ~$0.05; then:
python dec_p0_merge_scan.py graphrag_evidence/eval/dec_p1_era_scan_<STAMP>.json
python dec_p1_prepare_assemble_inputs.py
python dec_p0_config_side.py
python dec_p0_assemble.py
python edge_adjudication.py
```

`SCRATCH` is hardcoded to the authoring session's temp dir in every script; re-point it before
re-running elsewhere. `e1_census.py` is deliberately NOT in this chain — `slice_census():233` GETs
and `json.loads`es all 120 vector-bearing driver slices (3.76 GB), the exact transport that failed
at DEC-P0 over the home link. The cloud byte-scan is its substitute.
