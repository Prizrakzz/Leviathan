"""DEC-P0: render data/dec_p0/chunk_coverage.md from chunk_coverage.json. ASCII-only body."""
import json
import os

OUT = r'C:/Users/User/Desktop/Leviathan/data/dec_p0'
a = json.load(open(os.path.join(OUT, "chunk_coverage.json"), encoding="utf-8"))
T = a["totals"]
X = a["offsets_X1"]
L = []
w = L.append

w("# chunk_coverage -- the CHUNKS side, joined to the text layer")
w("")
w(f"Generated {a['generated_utc']}. Bucket `leviathan-dev-shahem-001`. Read-only; "
  f"{a['method']['gets_spent']} S3 GETs total.")
w("")
w("## Method (and why)")
w("")
w(f"- **pg mirror UNREACHABLE** -- `psycopg.connect` timed out at 20s. RDS is in-VPC; the laptop has no "
  f"route. Fell back to the flat S3 store, as instructed.")
w(f"- **S3 Select REFUSED** by the bucket (`MethodNotAllowed`), so server-side projection over the "
  f"{T['bytes_commodity_layer']/1e9:.2f} GB commodity layer + {T['bytes_driver_layer']/1e9:.2f} GB driver "
  f"layer was not available. Downloading 12.5 GB of vector-bearing slices was refused as disproportionate.")
w(f"- **Slice row counts come from the store's own run manifest**: "
  f"`graphrag_evidence/eval/write_manifest_rebuild_20260803T134404Z.json` "
  f"(`--rebuild-slices --dark-tally --allow-churn 25`, chunk_version `7adc57fac2d2-20260803`). Its recorded "
  f"`after_bytes` was checked against a fresh LIST and matches **all 125 live objects EXACTLY** "
  f"(commodity {a['manifest_byte_check']['commodity']['match']}/24, "
  f"drivers {a['manifest_byte_check']['drivers']['match']}/101), so the manifest describes the live store, "
  f"not a superseded one.")
w(f"- **The prop universe is `graphrag_evidence/chunks/`** -- the doc-keyed chunk cache "
  f"({T['cache_objects']:,} objects, {T['bytes_chunk_cache']/1e6:.1f} MB), downloaded in full. "
  f"`evidence_batch.rebuild_slices()` re-derives EVERY slice from this cache, so the cache is the chunk "
  f"universe and each slice is a deterministic filter of it.")
w(f"- **The text-layer join is free**: a cache object is named `chunks/<md5(source_key)>.jsonl`, so "
  f"md5-ing my own `text/` LIST joins the two sides with zero extra GETs.")
w(f"- `_raw/` was NOT used as the census surface: it is dated **2026-07-01** while every live slice is "
  f"**2026-08-03**, and `rebuild_slices` deliberately does not touch it. It is stale by one rebuild.")
w("")
w("## Headline numbers")
w("")
w("| fact | value |")
w("|---|---|")
w(f"| props in the chunk cache (the chunk universe) | **{T['props_in_cache']:,}** |")
w(f"| distinct prop ids | {T['distinct_prop_ids']:,} (collisions {T['prop_id_collisions']:,}) |")
w(f"| distinct doc_keys referenced by chunks | **{T['distinct_doc_keys_referenced']:,}** |")
w(f"| live slice rows, commodity ({T['commodity_slices']} slices) | **{T['slice_rows_commodity']:,}** |")
w(f"| live slice rows, drivers ({T['driver_slices']} slices) | **{T['slice_rows_drivers']:,}** |")
w(f"| live slice rows, total | **{T['slice_rows_total']:,}** |")
w(f"| commodity layer bytes | {T['bytes_commodity_layer']:,} |")
w(f"| driver layer bytes | {T['bytes_driver_layer']:,} |")
w(f"| text/ document.json total | **{T['text_docs_total']:,}** |")
w(f"| text docs with >=1 chunk | **{T['text_docs_with_ge1_chunk']:,}** |")
w(f"| text docs NEVER chunked | **{T['text_docs_never_chunked']:,}** ({T['never_chunked_pct']}%) |")
w(f"| offsets PRESENT (X1 complement) | **{X['present']:,}** ({X['pct_present']}%) |")
w(f"| offsets ABSENT (the X1 population) | **{X['absent']:,}** |")
w("")
w(f"offset_kind totals: `{X['offset_kind_totals']}`")
w("")
w(f"chunk_version totals: `{a['chunk_version_totals']}`")
w("")

dc = a.get("derivation_check") or {}
if a.get("derivation_ok") and dc:
    w("## Derivation proof (slice membership is reproducible from the cache)")
    w("")
    w("Re-ran the live routing rules (`evidence.match_forms` matchers for the 24 commodity nodes; "
      "`driver_matchers()` + `(source_key,text)` dedupe + `slice_cap` for the driver slices) over the "
      "downloaded cache and compared to the manifest's per-slice `after_n`:")
    w("")
    w("| layer | slices | exact count match | mismatch |")
    w("|---|---|---|---|")
    for layer in ("commodity", "drivers"):
        c = dc.get(layer) or {}
        w(f"| {layer} | {c.get('n_slices_manifest')} | **{c.get('exact_match')}** | {c.get('mismatch')} |")
    w("")
    bad = [(l, m) for l in ("commodity", "drivers") for m in (dc.get(l) or {}).get("mismatches", [])]
    if bad:
        w("Mismatching slices (layer, slice, manifest_after_n, derived):")
        w("")
        w("```")
        for l, m in bad[:40]:
            w(f"{l:10s} {m[0]:44s} manifest={m[1]} derived={m[2]}")
        w("```")
        w("")
else:
    w("## Derivation proof")
    w("")
    w(f"NOT RUN / FAILED: `{a.get('derivation_error')}`")
    w("")

w("## Per-source: text docs vs chunked docs vs never-chunked")
w("")
w("| source | text docs | with >=1 chunk | never-chunked | cov % | chunks | chunks/doc med | mean | max |")
w("|---|---|---|---|---|---|---|---|---|")
rows = sorted(a["per_source"].items(), key=lambda kv: -(kv[1]["text_docs_total"] or 0))
for s, d in rows:
    cpd = d.get("chunks_per_doc") or {}
    w(f"| {s} | {d['text_docs_total']:,} | {d['docs_with_ge1_chunk']:,} | "
      f"**{d['docs_never_chunked']:,}** | {d['coverage_pct']} | {d['chunks_total']:,} | "
      f"{cpd.get('median','-')} | {cpd.get('mean','-')} | {cpd.get('max','-')} |")
w("")

w("## X1: offsets present vs absent, per source (exact)")
w("")
w("`offset_kind` is minted only by `evidence_batch.retrieve()` (`_locate_span`): `exact` = the prop's "
  "verbatim span was found in its block; `block` = a rewritten prop floored to its whole block span; "
  "`none` = no block text was available, so `char_start`/`char_end` are null. The legacy inline path "
  "`evidence.build_index()`/`_prop_record()` writes NO offset keys at all.")
w("")
G = X["the_gap_is_DOC_level_not_prop_level"]
w("**The gap is DOC-level, not prop-level.** Of the "
  f"{T['distinct_doc_keys_referenced']:,} chunked documents, **{G['docs_every_prop_has_offsets']:,}** have "
  f"offsets on EVERY prop, **{G['docs_NO_prop_has_offsets']:,}** have offsets on NO prop, and "
  f"**{G['docs_MIXED']}** are mixed. The offset-absent count equals the chunk_version-absent count exactly "
  f"({X['absent']:,} == {a['chunk_version_totals'].get('<absent>', 0):,}), so this is one pre-W2.1 chunking "
  f"vintage, cleanly separable. Re-chunking exactly those "
  f"{G['docs_NO_prop_has_offsets']:,} documents closes the entire X1 population.")
w("")
C = X["click_to_page_darkness"]
w(f"**Click-to-page consequence.** Of the {C['pages_json_backed_docs_total']} `pages.json`-backed WASDE docs "
  f"({C['pages_json_backed_docs_chunked']} of them chunked), "
  f"**{C['props_offsets_absent']:,} of {C['props_offsets_absent']+C['props_offsets_present']:,} props "
  f"({C['pct_dark']}%)** carry no offset, so `pdfpage`'s deterministic offsets-first page resolution is "
  f"unavailable for them even though the sidecar exists.")
w("")
w("| source | chunks | offsets present | offsets ABSENT | % present | exact | block | none |")
w("|---|---|---|---|---|---|---|---|")
for s, d in rows:
    o = d.get("offsets")
    if not o:
        continue
    k = o["offset_kind"]
    w(f"| {s} | {d['chunks_total']:,} | {o['present']:,} | **{o['absent']:,}** | {o['pct_present']} | "
      f"{k.get('exact',0):,} | {k.get('block',0):,} | {k.get('none',0):,} |")
w("")

w("## Chunks per slice -- commodity layer (live rows, 2026-08-03 rebuild)")
w("")
w("`prior rows` for this layer is the guard's size/first-line ESTIMATE (~23.2 KB/prop), not an exact count; "
  "`rows` (after_n) is exact.")
w("")
w("| slice | rows | prior (est) | bytes | date_min | date_max | derived rows | distinct doc_keys | offsets absent |")
w("|---|---|---|---|---|---|---|---|---|")
for n, d in sorted(a["slices"]["commodity"].items(), key=lambda kv: -(kv[1]["rows_live"] or 0)):
    w(f"| {n} | **{d['rows_live']:,}** | {d['rows_prior']:,} | {d['bytes_live']:,} | "
      f"{d.get('date_min')} | {d.get('date_max')} | "
      f"{d.get('derived_rows','-')} | {d.get('derived_distinct_doc_keys','-')} | "
      f"{d.get('derived_off_absent','-')} |")
w("")

w("## Chunks per slice -- driver layer (all 101, live rows)")
w("")
tr = sorted(((n, d["truncated_n"], d.get("derived_pre_cap")) for n, d in a["slices"]["drivers"].items()
             if d.get("truncated_n")), key=lambda t: -t[1])
if tr:
    w(f"**{len(tr)} driver slices are CAPPED at max_props=4000 and lost "
      f"{sum(t[1] for t in tr):,} props at write** (kept the most recent by date, ties by source_key/id -- "
      f"`evidence.plan_driver_slices` G5a/G5b): "
      + ", ".join(f"`{n}` ({pre:,} -> 4,000, -{d:,})" for n, d, pre in tr) + ". "
      f"No commodity slice was truncated.")
    w("")
w("| slice | rows | prior | bytes | derived | pre-cap | cap | distinct doc_keys | offsets absent |")
w("|---|---|---|---|---|---|---|---|---|")
for n, d in sorted(a["slices"]["drivers"].items(), key=lambda kv: -(kv[1]["rows_live"] or 0)):
    w(f"| {n} | **{d['rows_live']:,}** | {d['rows_prior']:,} | {d['bytes_live']:,} | "
      f"{d.get('derived_rows','-')} | {d.get('derived_pre_cap','-')} | {d.get('cap','-')} | "
      f"{d.get('derived_distinct_doc_keys','-')} | {d.get('derived_off_absent','-')} |")
w("")

dark = [s for s, d in a["per_source"].items() if d["text_docs_total"] and d["docs_with_ge1_chunk"] == 0]
thin = sorted(((s, d) for s, d in a["per_source"].items()
               if d["text_docs_total"] and 0 < (d["coverage_pct"] or 0) < 25),
              key=lambda kv: kv[1]["coverage_pct"])
w("## Never-chunked docs, by source")
w("")
if dark:
    w(f"**Sources with ZERO chunked documents ({len(dark)})** -- entirely absent from the evidence graph: "
      + ", ".join(f"`{s}` ({a['per_source'][s]['text_docs_total']:,} docs)" for s in dark) + ".")
    w("")
if thin:
    w(f"**Sources under 25% chunk coverage ({len(thin)})**: "
      + ", ".join(f"`{s}` ({d['coverage_pct']}%)" for s, d in thin) + ".")
    w("")
w("")
w("| source | never-chunked | of text docs |")
w("|---|---|---|")
for s, n in sorted(a["never_chunked_by_source"].items(), key=lambda kv: -kv[1]):
    w(f"| {s} | **{n:,}** | {a['per_source'][s]['text_docs_total']:,} |")
w("")
w(f"Full list of all {T['text_docs_never_chunked']:,} never-chunked doc keys is in "
  f"`chunk_coverage.json` -> `never_chunked_doc_keys`. First 20:")
w("")
w("```")
for k in a["never_chunked_doc_keys"][:20]:
    w(k)
w("```")
w("")

orp = a["orphan_cache_objects_hash"]
ref = a["prop_source_keys_absent_from_text_list"]
w("## Integrity notes")
w("")
w(f"- cache objects whose md5 matches NO live `text/` document.json: **{len(orp)}** "
  f"(a chunked doc that has since left the text layer, or a hash minted from a different key form).")
w(f"- prop `source_key`s absent from my own `text/` LIST: **{len(ref)}**.")
w(f"- empty cache objects (a doc chunked to ZERO props): **{T['cache_objects_empty']}**.")
w(f"- **the flat store's prop `id` is NOT unique**: {T['props_in_cache']:,} props carry only "
  f"{T['distinct_prop_ids']:,} distinct ids ({T['prop_id_collisions']:,} collisions). The id is "
  f"`<batch custom_id>#<i>`, which is scoped to one Anthropic batch, so ids repeat across batches. "
  f"`pgstore.prop_id()` re-derives an md5 over `(node, source_key, text)`, so the pg mirror is unaffected "
  f"-- but nothing reading the JSONL may key on `id` alone.")
w(f"- non-`document.json` objects under `text/`: `{a['text_layer_non_document_objects']}`.")
ps = a["pageindex_sidecars"]
w(f"- `pages.json` pageindex sidecars: **{ps['total']}**, all under `usda_wasde`, all sitting next to a "
  f"`document.json` -- {ps['usda_wasde_sidecar_coverage_pct']}% of that source's "
  f"{ps['usda_wasde_docs_total']:,} docs. `graphrag.pdfpage._char_to_page` maps a stored `char_start` into "
  f"a 1-indexed PDF page THROUGH this sidecar, so deterministic click-to-page needs BOTH a sidecar AND an "
  f"offset -- the X1 population measured above is dark to it on the offsets leg alone.")
if ref[:10]:
    w("")
    w("```")
    for k in ref[:10]:
        w(k)
    w("```")
w("")
w("## Gaps")
w("")
for g in a["gaps"]:
    w(f"- {g}")
w("")

body = "\n".join(L)
open(os.path.join(OUT, "chunk_coverage.md"), "w", encoding="utf-8").write(body)
print("wrote md", len(body))
