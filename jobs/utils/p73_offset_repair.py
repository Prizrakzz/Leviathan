"""#73 OFFSET RE-REPAIR over the live pg store -- reclassify the `(none)` cohort (GN-2 side item).

THE COHORT AND WHY IT EXISTS. 11.1% of the rebuilt store's 2.74M props carry NO offsets
(`meta.offset_kind` absent or the chunk-time literal 'none'): their chunk-cache records predate the
W2.1 offset machinery ("pre-offset vintages"), and the X2 rebuild faithfully re-loaded that absence.
Phase F's serve-time verify-and-repair (pdfpage._verify_and_repair) recovers the PAGE per click, but
the stored classification -- what the highlight census counts and what the FE's pin-point path reads
-- stays `(none)` until something writes it back. This script is that something.

WHY WHOLE-DOCUMENT LOCATE IS LEGITIMATE HERE (the backfill_prop_dates docstring says offsets are
"chunk-time and NOT backfillable"). That sentence is about the BLOCK-scoped locate: the ~5,000-char
block text lives only in the batch manifests, so the chunk-time cursor discipline cannot be replayed.
This pass does something narrower and self-evidently sound instead: find the prop's verbatim `text`
in the document's OWN full_text (the text layer pdfpage serves highlights from) and accept the span
ONLY when the match is GLOBALLY UNIQUE -- raw find first (`exact`), the _ws_pattern
whitespace-tolerant regex second (`exact_ws`), exactly evidence_batch._locate_span's vocabulary. A
needle that appears twice names neither occurrence (ambiguous -> left absent); a rewritten prop that
appears nowhere stays absent. There is no cursor to get wrong because there is no order claim: each
accepted span is THE unique place its text occurs.

WHAT IT DELIBERATELY DOES NOT TOUCH:
  - rows with ANY existing offset_kind (exact / exact_ws / block): those are chunk-time truth; in
    particular `block` is NOT upgraded here -- block props are propositional rewrites or measured
    ambiguities, and this pass's charter is the absent cohort only.
  - the S3 chunk cache and the slice files. pg is a DISPOSABLE DERIVED INDEX (S3 = truth), so this
    repair is erased by the next full rebuild BY DESIGN -- the same way Phase F's classification
    was. That is the accepted cost of staying off the D-EI-guarded write seams; the rebuild runbook
    carries a one-line "re-run p73_offset_repair --apply after load". Durable promotion into the
    chunk cache is a separate, gated decision.

Idempotent: a second --apply finds the cohort already stamped (offset_kind set) and writes nothing.
Every written row gains `meta.offset_repair = "p73-<UTC date>"` so the repair's provenance is
queryable and a census can tell chunk-time offsets from repaired ones.

    python jobs/utils/p73_offset_repair.py                 # DRY RUN: locate + full report, zero writes
    python jobs/utils/p73_offset_repair.py --apply         # write the located spans back to pg meta
    python jobs/utils/p73_offset_repair.py --limit 5000    # bounded probe (dry-run sampling)

Needs EVIDENCE_PG_DSN (in-VPC) + S3 access; EVIDENCE_PG_TABLE honors the pgstore default/override.
"""
from __future__ import annotations

import argparse
import collections
import datetime as _dt
import json
import sys
from concurrent.futures import ThreadPoolExecutor

from leviathan.common import config

config.load_env()

from leviathan.graphrag import evidence_batch as eb   # noqa: E402  (_ws_pattern -- the ONE ws idiom)
from leviathan.graphrag import pdfpage as pp          # noqa: E402  (_load_document -- the text layer reader)
from leviathan.graphrag import pgstore as pg          # noqa: E402  (_table -- the validated table name)

_BATCH = 500              # UPDATE batch size
_DOC_WORKERS = 8          # S3 document.json fetch concurrency (LRU-cached in pdfpage after fetch)


def _locate_whole_doc(needle: str, full: str):
    """(char_start, char_end, kind) with kind in {exact, exact_ws} ONLY when the match is globally
    unique in `full`; (None, None, reason) otherwise. Vocabulary and ws-regex are _locate_span's."""
    if not needle or not full:
        return None, None, "empty"
    idx = full.find(needle)
    if idx >= 0:
        if full.find(needle, idx + 1) >= 0:
            return None, None, "ambiguous"
        return idx, idx + len(needle), "exact"
    pat = eb._ws_pattern(needle)
    if pat is not None:
        hits = []
        for m in pat.finditer(full):
            hits.append(m)
            if len(hits) > 1:
                return None, None, "ambiguous"
        if len(hits) == 1:
            return hits[0].start(), hits[0].end(), "exact_ws"
    return None, None, "not_found"


def _source_of(key: str) -> str:
    return next((p[len("source="):] for p in str(key).split("/") if p.startswith("source=")), "unknown")


def main() -> int:
    ap = argparse.ArgumentParser(description="#73 offset re-repair over the pg store ((none) cohort)")
    ap.add_argument("--apply", action="store_true", help="write located spans back (default: dry run)")
    ap.add_argument("--limit", type=int, default=None, help="cap the cohort read (probe runs)")
    args = ap.parse_args()

    import psycopg
    dsn = config.get_required_env("EVIDENCE_PG_DSN")
    table = pg.table_name()
    stamp = f"p73-{_dt.datetime.now(_dt.timezone.utc).strftime('%Y%m%d')}"

    where = ("meta IS NULL OR meta->>'offset_kind' IS NULL OR meta->>'offset_kind' = 'none' "
             "OR meta->>'offset_kind' = 'None'")
    lim = f" LIMIT {int(args.limit)}" if args.limit else ""
    rows: list[tuple] = []
    with psycopg.connect(dsn) as conn, conn.cursor(name="p73_cohort") as cur:
        cur.itersize = 20_000
        cur.execute(f"SELECT id, source_key, text FROM {table} WHERE {where}{lim}")
        for r in cur:
            rows.append(r)
    print(f"cohort: {len(rows)} props with absent offsets (table={table})", flush=True)
    if not rows:
        return 0

    by_doc: dict[str, list[tuple]] = collections.defaultdict(list)
    for r in rows:
        by_doc[r[1]].append(r)
    print(f"across {len(by_doc)} documents; fetching text layers ...", flush=True)

    full_text: dict[str, str | None] = {}

    def _fetch(sk: str):
        try:
            doc = pp._load_document(sk)
            full_text[sk] = doc.get("full_text") or ""
        except Exception:                                     # noqa: BLE001 -- a missing doc is a report row
            full_text[sk] = None

    with ThreadPoolExecutor(max_workers=_DOC_WORKERS) as pool:
        list(pool.map(_fetch, by_doc))

    kinds = collections.Counter()
    per_source = collections.defaultdict(collections.Counter)
    updates: list[tuple] = []
    for sk, props in by_doc.items():
        full = full_text.get(sk)
        src = _source_of(sk)
        if full is None:
            kinds["doc_missing"] += len(props)
            per_source[src]["doc_missing"] += len(props)
            continue
        for pid, _sk, text in props:
            s, e, kind = _locate_whole_doc(text or "", full)
            kinds[kind] += 1
            per_source[src][kind] += 1
            if s is not None:
                updates.append((json.dumps({"char_start": s, "char_end": e, "offset_kind": kind,
                                            "offset_repair": stamp}), pid))

    total = len(rows)
    located = kinds["exact"] + kinds["exact_ws"]
    print(f"\nlocated {located}/{total} ({100.0 * located / total:.1f}%): "
          f"exact={kinds['exact']} exact_ws={kinds['exact_ws']} | left absent: "
          f"ambiguous={kinds['ambiguous']} not_found={kinds['not_found']} "
          f"empty={kinds['empty']} doc_missing={kinds['doc_missing']}")
    print("\nper-source (top 20 by cohort size):")
    ranked = sorted(per_source.items(), key=lambda kv: -sum(kv[1].values()))[:20]
    for src, c in ranked:
        n = sum(c.values())
        print(f"  {src:<28} n={n:>7} exact={c['exact']:>6} ws={c['exact_ws']:>6} "
              f"ambig={c['ambiguous']:>5} miss={c['not_found']:>6} nodoc={c['doc_missing']:>5}")

    if not args.apply:
        print("\nDRY RUN -- nothing written. Re-run with --apply to stamp the located spans.")
        return 0

    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        for i in range(0, len(updates), _BATCH):
            cur.executemany(
                f"UPDATE {table} SET meta = coalesce(meta, '{{}}'::jsonb) || %s::jsonb WHERE id = %s",
                updates[i:i + _BATCH])
            conn.commit()
    print(f"\nAPPLIED: {len(updates)} rows stamped ({stamp}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
