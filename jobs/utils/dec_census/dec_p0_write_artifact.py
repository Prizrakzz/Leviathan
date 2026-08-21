"""DEC-P0: assemble data/dec_p0/chunk_coverage.{json,md} from the census raw dump."""
import json
import os
import statistics as st
from collections import Counter

SCR = r'C:/Users/User/AppData/Local/Temp/claude/C--Users-User-Desktop-Leviathan/360a169c-9409-4bdb-af00-a02392ed35a2/scratchpad'
OUT = r'C:/Users/User/Desktop/Leviathan/data/dec_p0'
R = json.load(open(os.path.join(SCR, "dec_p0_census_raw.json"), encoding="utf-8"))
EVL = json.load(open(os.path.join(SCR, "dec_p0_ev_listing.json"), encoding="utf-8"))
BCHK = json.load(open(os.path.join(SCR, "dec_p0_manifest_bytes_check.json"), encoding="utf-8"))
ADD = json.load(open(os.path.join(SCR, "dec_p0_addendum.json"), encoding="utf-8"))
MF = json.load(open(os.path.join(SCR, "write_manifest_rebuild_20260803T134404Z.json"), encoding="utf-8"))

P = "graphrag_evidence/"
sizes = {k[len(P):]: s for k, s, _ in EVL}
lastmod = {k[len(P):]: m for k, s, m in EVL}

docs_props = R["docs_props"]                      # source_key -> n props
by_src = R["by_src"]
text_by_src = R["text_by_src"]
never = R["never"]

# never-chunked grouped by source
import re
_SRC = re.compile(r"text/source=([^/]+)/")


def src_of(k):
    m = _SRC.search(k or "")
    return m.group(1) if m else "unknown"


never_by_src = Counter(src_of(k) for k in never)

# per-source chunks-per-doc distribution
dist = {}
for s in sorted(set(list(text_by_src) + list(by_src))):
    vals = sorted(v for k, v in docs_props.items() if src_of(k) == s)
    d = {
        "text_docs_total": text_by_src.get(s, 0),
        "docs_with_ge1_chunk": len(vals),
        "docs_never_chunked": text_by_src.get(s, 0) - len(vals),
        "coverage_pct": round(100.0 * len(vals) / text_by_src[s], 2) if text_by_src.get(s) else None,
        "chunks_total": by_src.get(s, {}).get("props", 0),
        "chunks_per_doc": None,
    }
    if vals:
        d["chunks_per_doc"] = {
            "min": vals[0], "p25": vals[int(0.25 * (len(vals) - 1))],
            "median": int(st.median(vals)), "mean": round(sum(vals) / len(vals), 2),
            "p75": vals[int(0.75 * (len(vals) - 1))], "p90": vals[int(0.90 * (len(vals) - 1))],
            "max": vals[-1],
        }
    b = by_src.get(s)
    if b:
        d["offsets"] = {"present": b["off_present"], "absent": b["off_absent"],
                        "pct_present": round(100.0 * b["off_present"] / b["props"], 2) if b["props"] else None,
                        "offset_kind": b["kind"]}
        d["chunk_version"] = b["cv"]
        d["chunk_version_absent"] = b["no_cv"]
        d["props_with_event_date"] = b["event_date"]
    dist[s] = d

# slice tables
comm_mf = MF["slices"]["commodity"]
drv_mf = MF["slices"]["drivers"]
so = R["slice_offsets"]
slices = {}
for layer, mfl, sub in (("commodity", comm_mf, ""), ("drivers", drv_mf, "drivers/")):
    rows = {}
    for name, rec in mfl.items():
        d = {
            "rows_live": rec.get("after_n"),
            "rows_prior": rec.get("before_n"),
            "bytes_live": sizes.get(f"{sub}{name}.jsonl"),
            "bytes_manifest": rec.get("after_bytes"),
            "bytes_match": sizes.get(f"{sub}{name}.jsonl") == rec.get("after_bytes"),
            "last_modified": lastmod.get(f"{sub}{name}.jsonl"),
            "span": rec.get("after_span"),
            "date_min": (rec.get("after_span") or {}).get("date_min"),
            "date_max": (rec.get("after_span") or {}).get("date_max"),
            "truncated_n": rec.get("truncated_n"),
            "before_n_exact": rec.get("before_n_exact"),
        }
        od = (so.get(layer) or {}).get(name)
        if od:
            d["derived_rows"] = od["n"]
            d["derived_matches_manifest"] = od["n"] == rec.get("after_n")
            d["derived_off_present"] = od["off_present"]
            d["derived_off_absent"] = od["off_absent"]
            d["derived_distinct_doc_keys"] = od["docs"]
            if "pre_cap" in od:
                d["derived_pre_cap"] = od["pre_cap"]
                d["cap"] = od["cap"]
        rows[name] = d
    slices[layer] = rows

art = {
    "artifact": "chunk_coverage",
    "generated_utc": __import__("time").strftime("%Y-%m-%dT%H:%M:%SZ", __import__("time").gmtime()),
    "method": {
        "backend_used": "flat S3 jsonl (pg mirror UNREACHABLE from the laptop: RDS is in-VPC, "
                        "psycopg connect timeout at 20s)",
        "authority_for_slice_row_counts": "graphrag_evidence/eval/write_manifest_rebuild_20260803T134404Z.json "
                                          "(label=rebuild, command '--rebuild-slices --dark-tally "
                                          "--allow-churn 25', chunk_version 7adc57fac2d2-20260803); its "
                                          "per-slice after_bytes was verified against a fresh LIST and "
                                          "matches all 125 live objects EXACTLY, so the manifest describes "
                                          "the live store",
        "authority_for_the_prop_universe": "graphrag_evidence/chunks/ -- the doc-keyed chunk cache "
                                           "(2,815 objects, 155.1 MB), downloaded in full. rebuild_slices() "
                                           "derives EVERY slice from this cache, so the cache is the chunk "
                                           "universe and the slices are deterministic filters of it",
        "text_layer_list": "independent paginated LIST of s3://leviathan-dev-shahem-001/text/ taken by this "
                           "agent (7,307 objects, 7,056 document.json)",
        "join_key": "chunks/<md5(source_key)>.jsonl -- the doc cache filename IS md5 of the document.json S3 "
                    "key (evidence_batch._doc_cache_node), so the text-layer join needs ZERO extra GETs",
        "s3_select": "REFUSED by the bucket (MethodNotAllowed) -- server-side projection over the 12.5 GB of "
                     "vector-bearing slices is not available",
        "gets_spent": 2815 + 2,
        "gets_breakdown": "2,815 chunks/ objects + 2 run manifests. ZERO GETs against the 12.5 GB slice "
                          "layer, zero against text/ document.json bodies, zero per-object HEADs. Two "
                          "paginated LISTs (graphrag_evidence/ = 9,840 objects; text/ = 7,307 objects).",
    },
    "record_shape": {
        "cache_prop": ["id", "date", "source", "source_key", "text", "event_date",
                       "event_date_precision", "char_start", "char_end", "offset_kind", "chunk_version"],
        "commodity_slice_row": "cache prop + contract + vector + backend",
        "driver_slice_row": "cache prop + driver + vector + backend",
        "doc_key_backpointer": "source_key -> the text/ document.json S3 key",
        "offset_semantics": "offset_kind exact|block|none (evidence_batch._locate_span). 'none' == no block "
                            "text was available, char_start/char_end are null. 'block' == the prop was "
                            "rewritten and floors to its whole source block's span.",
        "legacy_path_note": "evidence.build_index()/_prop_record() (the INLINE build path) writes NO "
                            "char_start/char_end/offset_kind at all -- only evidence_batch.retrieve() mints "
                            "them. The live store carries zero such records (see offsets census).",
    },
    "totals": {
        "cache_objects": R["cache_files"],
        "cache_objects_empty": len(R["empty_cache_objs"]),
        "props_in_cache": R["props_total"],
        "distinct_prop_ids": R["distinct_ids"],
        "prop_id_collisions": R["dupe_ids"],
        "distinct_doc_keys_referenced": R["distinct_doc_keys"],
        "slice_rows_commodity": sum(v.get("after_n") or 0 for v in comm_mf.values()),
        "slice_rows_drivers": sum(v.get("after_n") or 0 for v in drv_mf.values()),
        "slice_rows_total": (sum(v.get("after_n") or 0 for v in comm_mf.values())
                             + sum(v.get("after_n") or 0 for v in drv_mf.values())),
        "commodity_slices": len(comm_mf), "driver_slices": len(drv_mf),
        "bytes_commodity_layer": sum(sizes.get(f"{n}.jsonl", 0) for n in comm_mf),
        "bytes_driver_layer": sum(sizes.get(f"drivers/{n}.jsonl", 0) for n in drv_mf),
        "bytes_chunk_cache": sum(s for k, s, _ in EVL if k[len(P):].startswith("chunks/")),
        "text_docs_total": R["text_docs"],
        "text_docs_with_ge1_chunk": R["with_ge1"],
        "text_docs_never_chunked": len(never),
        "never_chunked_pct": round(100.0 * len(never) / R["text_docs"], 2),
    },
    "offsets_X1": {
        "population": "every prop in the chunks/ doc cache (the store's chunk universe)",
        "present": R["off_present"], "absent": R["off_absent"],
        "pct_present": round(100.0 * R["off_present"] / R["props_total"], 4),
        "offset_kind_totals": R["kind_total"],
        "by_source": {s: dist[s].get("offsets") for s in dist if dist[s].get("offsets")},
        "the_gap_is_DOC_level_not_prop_level": {
            "docs_every_prop_has_offsets": ADD["docs_all_props_have_offsets"],
            "docs_NO_prop_has_offsets": ADD["docs_no_props_have_offsets"],
            "docs_MIXED": ADD["docs_MIXED_vintage"],
            "reading": "ZERO mixed docs. offset-absence is a per-DOCUMENT chunking vintage, not a per-prop "
                       "failure -- and it lines up exactly with chunk_version absence (158,567 == 158,567). "
                       "Re-chunking exactly the "
                       f"{ADD['docs_no_props_have_offsets']} offset-less documents closes the whole X1 "
                       "population; nothing else needs touching.",
        },
        "click_to_page_darkness": {
            "pages_json_backed_docs_total": ADD["pages_json_backed_docs_total"],
            "pages_json_backed_docs_chunked": ADD["pages_json_backed_docs_in_cache"],
            "props_offsets_present": ADD["props_on_sidecar_docs_offsets_present"],
            "props_offsets_absent": ADD["props_on_sidecar_docs_offsets_ABSENT"],
            "pct_dark": round(100.0 * ADD["props_on_sidecar_docs_offsets_ABSENT"]
                              / (ADD["props_on_sidecar_docs_offsets_ABSENT"]
                                 + ADD["props_on_sidecar_docs_offsets_present"]), 2),
            "reading": "pdfpage._resolve_page prefers the deterministic offsets-first path; on the only "
                       "docs that HAVE a per-page sidecar, that path is available for a minority of props.",
        },
    },
    "chunk_version_totals": R["cv_total"],
    "manifest_provenance": {
        "key": "graphrag_evidence/eval/write_manifest_rebuild_20260803T134404Z.json",
        "label": MF.get("label"), "chunk_version": MF.get("chunk_version"),
        "command": MF.get("command"), "finished_utc": MF.get("finished_utc"),
        "guard": MF.get("guard"), "warnings": MF.get("warnings"),
        "before_n_caveat": "commodity before_n came from a size/first-line ESTIMATE (~23.2 KB/prop); "
                           "after_n is exact (len(records) at write time)",
    },
    "manifest_byte_check": BCHK,
    "derivation_check": R["check"],
    "derivation_ok": R["derive_ok"],
    "derivation_error": R["derive_err"],
    "per_source": dist,
    "slices": slices,
    "never_chunked_by_source": dict(never_by_src.most_common()),
    "never_chunked_doc_keys": never,
    "orphan_cache_objects_hash": R["orphan_hashes"],
    "prop_source_keys_absent_from_text_list": R["orphan_refs"],
    "text_layer_non_document_objects": R["other_text"],
    "pageindex_sidecars": {
        "convention": "raw_to_text/pageindex.sidecar_key -> pages.json written NEXT TO document.json; "
                      "{page_count, pages:[{page,text}]} from Textract LINE blocks. Only scanned/Textract "
                      "docs get one; graphrag.pdfpage maps a stored char_start into a 1-indexed PDF page "
                      "via this sidecar (_char_to_page), so click-to-page needs BOTH a sidecar AND offsets.",
        "total": 251, "by_source": {"usda_wasde": 251},
        "all_have_sibling_document_json": True,
        "usda_wasde_docs_total": 616,
        "usda_wasde_sidecar_coverage_pct": round(100.0 * 251 / 616, 2),
    },
    "gaps": [
        "pg mirror (evidence_props) NOT measured: RDS is in-VPC and psycopg timed out from the laptop. "
        "Everything here is the S3 store; the pg row count and its meta->>'char_start' population are "
        "unverified against it. Re-run this census from inside the VPC (a Batch/Fargate one-shot) to "
        "confirm the mirror agrees.",
        "Per-slice row counts are the store's own run-manifest after_n, NOT a line count taken from the "
        "objects themselves. They are trustworthy because every one of the 125 after_bytes matches the live "
        "object byte-for-byte, but the 12.5 GB of vector-bearing slices was never downloaded and S3 Select "
        "is disabled on this bucket.",
        "Commodity-layer before_n in the manifest is a size/first-line ESTIMATE, so the prior-population "
        "column is approximate; after_n is exact.",
        "The chunk cache prop `id` (`<custom_id>#<i>`) is batch-scoped and NOT globally unique: "
        f"{R['props_total']:,} props carry only {R['distinct_ids']:,} distinct ids "
        f"({R['dupe_ids']:,} collisions). pgstore.prop_id() re-derives its own md5 over "
        "(node, source_key, text) so the mirror is unaffected, but nothing in the flat store can be keyed "
        "on `id` alone.",
        "Never-chunked is measured against the doc-cache universe. A document chunked before the cache "
        "existed and never re-chunked would look never-chunked here -- but 0 of 2,815 cache objects are "
        "orphans and 0 prop source_keys are missing from the text LIST, so the two sides are consistent.",
        "Doc-level text length / page count was not read (that would be 7,056 document.json GETs); "
        "chunks-per-doc is therefore not normalised by document size.",
    ],
}
json.dump(art, open(os.path.join(OUT, "chunk_coverage.json"), "w", encoding="utf-8"), indent=1)
print("wrote json", os.path.getsize(os.path.join(OUT, "chunk_coverage.json")))
