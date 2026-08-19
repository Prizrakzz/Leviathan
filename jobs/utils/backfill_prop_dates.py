"""Re-derive every stored prop's `date` from the FIXED key deriver (DEC-P0c S1) -- the chunk cache first,
the pg mirror second. Dry-run by default; it writes nothing until you say --apply.

WHY THIS IS A LEAK REPAIR AND NOT A TIDY-UP. `date` is exactly the field `evidence.retrieve()`'s leakage
filter compares against `asof` (evidence.py:523) and the pg WHERE repeats. Before the deriver fix,
`evidence._pub_date` matched only three key shapes, so 2,036 of 7,056 documents (28.9%) fell through to
`year -> Jan-1` -- including 100% of `usda_wasde` (616), `usda_wap` (450), `sagis_cec` (463), `mpoc` (335),
`fnc` (56), `conab` (55), `icco_*` (54) and `mpob` (7). Every one of those errors is BACKWARDS IN TIME: a
document published 2020-06-25 stamped 2020-01-01 is citable five months before it existed. The store holds
~345,870 cached props over 2,815 documents, so the wrong-early dates are live, not hypothetical.

    python jobs/utils/backfill_prop_dates.py                             # DRY RUN over the whole cache
    python jobs/utils/backfill_prop_dates.py --sources usda_wasde,fnc    # DRY RUN, two sources
    python jobs/utils/backfill_prop_dates.py --apply                     # rewrite chunks/ + the pg rows
    python jobs/utils/backfill_prop_dates.py --apply --skip-pg           # cache only (pg reloads from S3 anyway)
    (EVIDENCE_S3 selects the S3 store over the local one; EVIDENCE_PG_DSN enables the pg leg.)

IDEMPOTENT BY CONSTRUCTION. The new date is a pure function of the record's own `source_key`, so a second
run computes the same value, finds `before == after` on every record, and writes nothing at all -- the
`--apply` leg only touches a cache object when at least one of its records actually moves. Run it twice; the
second run's report is the proof.

WHAT IT DELIBERATELY DOES NOT TOUCH:
  - `text`, `char_start`/`char_end`, `offset_kind`, `chunk_version`, `id`. Offsets are chunk-time and are
    NOT backfillable (the block text lives only in the batch manifests) -- that is why the whitespace-tolerant
    locate had to ship BEFORE the X2 pass and why this script does not pretend to repair it.
  - the commodity/driver slices under `<EVIDENCE_S3>/*.jsonl` and `drivers/*.jsonl`. Those are DERIVED from
    the cache: re-run `evidence_batch --rebuild-slices` after this, under its own write guard, rather than
    editing 125 guarded objects from here. `evidence.restamp(node)` remains the per-slice tool.
  - a document whose date is ALREADY correct: it is reported and left byte-identical rather than
    rewritten to add the new `date_kind`/`date_layout` flags. Those flags are minted at chunk time for new
    props; adding them to 2,815 untouched objects would be 2,815 PUTs to record something the layout table
    already derives from the key on demand.
  - a date the deriver still REFUSES (`conab`'s survey numbers are not a calendar; `mpob`'s overview PDFs
    carry only `year=`). Those 62 documents keep their year floor and are reported under `refused_docs`,
    never silently "fixed" to a guess.
"""
from __future__ import annotations

import argparse
import collections
import json
import sys

from leviathan.common import config

config.load_env()

from leviathan.graphrag import evidence as ev  # noqa: E402
from leviathan.graphrag import evidence_batch as eb  # noqa: E402


def _source_of(key: str) -> str:
    return next((p[len("source="):] for p in str(key).split("/") if p.startswith("source=")), "unknown")


def _new_date(source_key: str) -> tuple[str | None, str]:
    """(the ISO date the fixed deriver produces, the layout that produced it) or (None, layout) when the key
    carries no date at all. Deliberately `pub_date_layout` and NOT `doc_date_detail`: the document body is
    not in hand here, and no corpus document.json carries a date field anyway, so re-reading 2,815 bodies to
    consult a field that is never present would be 2,815 GETs for nothing."""
    d, layout = ev.pub_date_layout(source_key)
    return (str(d) if d else None), layout


class Report:
    """Per-source before/after histograms. `moved` counts records whose date CHANGED, and it is split into
    `later` and `earlier` because the direction IS the finding: every Jan-1 floor was too EARLY, so a repair
    that moves a stamp LATER is closing a leak, and a stamp moving EARLIER would mean the deriver disagrees
    with a date something else already got right -- a thing to look at before applying, not after."""

    def __init__(self):
        self.docs = collections.Counter()
        self.props = collections.Counter()
        self.moved = collections.Counter()
        self.refused = collections.Counter()
        self.layouts = collections.Counter()
        self.later = collections.Counter()
        self.earlier = collections.Counter()
        self.before = collections.defaultdict(collections.Counter)
        self.after = collections.defaultdict(collections.Counter)
        self.examples: dict[str, tuple] = {}

    def note_doc(self, src: str, source_key: str, old: str | None, new: str | None, layout: str,
                 n_props: int) -> None:
        self.docs[src] += 1
        self.props[src] += n_props
        self.layouts[f"{src}/{layout}"] += 1
        # MONTH buckets, not year: the whole error class is intra-year (Jan-1 vs the real release month), so
        # a year histogram would show the repair as a no-op on exactly the documents it repairs.
        self.before[src][(old or "")[:7]] += 1
        self.after[src][(new or old or "")[:7]] += 1
        if new is None:
            self.refused[src] += 1
            return
        if new == old:
            return
        self.moved[src] += n_props
        if old and new > old:
            self.later[src] += n_props
        elif old:
            self.earlier[src] += n_props
        self.examples.setdefault(src, (source_key, old, new, layout))

    def render(self) -> str:
        out = ["", "per-source backfill report (docs / props / props MOVED / of which LATER / EARLIER / refused)"]
        for src in sorted(self.docs):
            out.append(f"  {src:<28} docs={self.docs[src]:>5} props={self.props[src]:>7} "
                       f"moved={self.moved[src]:>7} later={self.later[src]:>7} "
                       f"earlier={self.earlier[src]:>7} refused_docs={self.refused[src]:>4}")
            ex = self.examples.get(src)
            if ex:
                out.append(f"      e.g. {ex[1]} -> {ex[2]}  via {ex[3]}   {ex[0]}")
        out.append("")
        out.append("month histogram, before -> after (documents per stamped YYYY-MM)")
        for src in sorted(self.docs):
            b = ",".join(f"{y}:{n}" for y, n in sorted(self.before[src].items()))
            a = ",".join(f"{y}:{n}" for y, n in sorted(self.after[src].items()))
            out.append(f"  {src:<28} BEFORE {b}")
            out.append(f"  {'':<28} AFTER  {a}")
        return "\n".join(out)

    def payload(self) -> dict:
        return {"report": "backfill_prop_dates",
                "per_source": {src: {"docs": self.docs[src], "props": self.props[src],
                                     "props_moved": self.moved[src], "props_later": self.later[src],
                                     "props_earlier": self.earlier[src], "refused_docs": self.refused[src],
                                     "before_month_hist": dict(self.before[src]),
                                     "after_month_hist": dict(self.after[src])}
                               for src in sorted(self.docs)},
                "layouts": dict(self.layouts),
                "totals": {"docs": sum(self.docs.values()), "props": sum(self.props.values()),
                           "props_moved": sum(self.moved.values()),
                           "props_later": sum(self.later.values()),
                           "props_earlier": sum(self.earlier.values()),
                           "refused_docs": sum(self.refused.values())}}


def backfill_cache(*, sources: set[str] | None, apply: bool, report: Report, limit: int | None = None) -> int:
    """Walk chunks/<md5>.jsonl, re-derive each record's date from its own source_key, and (with --apply)
    rewrite ONLY the objects that actually moved. Returns the number of objects rewritten (0 on a dry run).

    One LIST of chunks/ and one GET per cached document -- the same read shape `_build_novelty_gate` already
    pays -- and one PUT per MOVED document. An unchanged document is not rewritten, which is what keeps a
    second run free and keeps the doc-cache's own write guard (evidence_batch._write_doc_cache) out of the
    picture: this is a field-level repair of existing records, not a re-chunk, and it must not look like one."""
    written = 0
    hashes = sorted(eb._cached_hashes())
    for i, h in enumerate(hashes):
        if limit is not None and i >= limit:
            break
        recs = ev.load_index(f"chunks/{h}")
        if not recs:
            continue
        source_key = recs[0].get("source_key") or ""
        src = _source_of(source_key)
        if sources and src not in sources:
            continue
        old = recs[0].get("date")
        new, layout = _new_date(source_key)
        report.note_doc(src, source_key, old, new, layout, len(recs))
        if new is None or all(r.get("date") == new for r in recs):
            continue                                        # refused, or already correct: nothing to write
        for r in recs:
            r["date"] = new
            r["date_kind"] = "key_month" if ev._KEY_DATE_PRECISION.get(layout) == "month" else "key"
            r["date_layout"] = layout
        if apply:
            ev._evid_write(f"chunks/{h}", "\n".join(json.dumps(r) for r in recs))
        written += 1
    return written


def backfill_pg(*, sources: set[str] | None, apply: bool, report: Report) -> int:
    """Re-stamp the pg mirror the same way, keyed on source_key. Returns rows that moved (a dry run counts
    without updating). pg is a DISPOSABLE derived index -- S3 is truth -- so this leg exists only to spare a
    full reload; `--skip-pg` plus a `load_pg_evidence.py` re-run is an equally correct route."""
    from leviathan.graphrag import pgstore
    conn = pgstore.connect()
    t = pgstore.table_name()
    moved = 0
    with conn.cursor() as cur:
        cur.execute(f"SELECT DISTINCT source_key, date FROM {t}")
        rows = cur.fetchall()
        for source_key, old in rows:
            src = _source_of(source_key or "")
            if sources and src not in sources:
                continue
            new, _layout = _new_date(source_key or "")
            if new is None or new == old:
                continue
            if apply:
                cur.execute(f"UPDATE {t} SET date=%s WHERE source_key=%s AND date=%s", (new, source_key, old))
                moved += cur.rowcount
            else:
                cur.execute(f"SELECT count(*) FROM {t} WHERE source_key=%s AND date=%s", (source_key, old))
                moved += cur.fetchone()[0]
    return moved


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true",
                    help="actually write. WITHOUT it this is a pure read: the report is produced and not one "
                         "object or row is touched. Dry-run first is not a suggestion -- the store's "
                         "versioning is Suspended.")
    ap.add_argument("--sources", default="", help="comma-separated source names to limit the pass to")
    ap.add_argument("--skip-pg", action="store_true", help="cache only (pg reloads from S3 with load_pg_evidence)")
    ap.add_argument("--limit", type=int, default=None, help="stop after N cached documents (a smoke pass)")
    ap.add_argument("--out", default=None, help="write the machine-readable report to this path as well")
    args = ap.parse_args()
    sources = {s for s in args.sources.split(",") if s} or None

    report = Report()
    print(f"{'APPLY' if args.apply else 'DRY-RUN'}: re-deriving prop dates from the fixed key deriver"
          f"{' for ' + ','.join(sorted(sources)) if sources else ' over the whole chunk cache'}")
    written = backfill_cache(sources=sources, apply=args.apply, report=report, limit=args.limit)
    print(report.render())
    payload = report.payload()
    payload["cache_objects_rewritten" if args.apply else "cache_objects_that_would_move"] = written
    print(f"\nchunk cache: {written} document object(s) "
          f"{'REWRITTEN' if args.apply else 'would move'} of {payload['totals']['docs']} inspected")
    if payload["totals"]["docs"] == 0:
        # FAIL-CLOSED (2026-08-19): a mis-pointed store (EVIDENCE_S3 unset, wrong prefix) makes an
        # empty run indistinguishable from a healthy no-op -- the first real dry-run did exactly
        # this and reported '0 of 0' with exit 0. An inspected-zero run is a configuration error,
        # never a verdict about the data.
        print("REFUSED: 0 documents inspected -- the store is mis-pointed (set EVIDENCE_S3, e.g. "
              "s3://leviathan-dev-shahem-001/graphrag_evidence) or the cache prefix is empty.")
        raise SystemExit(2)
    if not args.skip_pg:
        try:
            n = backfill_pg(sources=sources, apply=args.apply, report=report)
            payload["pg_rows_moved"] = n
            print(f"pg mirror: {n} row(s) {'UPDATED' if args.apply else 'would move'}")
        except Exception as exc:                            # noqa: BLE001 -- no DSN / no driver: report, don't fail
            payload["pg_error"] = str(exc)[:300]
            print(f"pg mirror: SKIPPED ({str(exc)[:200]}) -- re-run with EVIDENCE_PG_DSN set, or reload "
                  f"the table from S3 with jobs/utils/load_pg_evidence.py")
    if args.out:
        from pathlib import Path
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"report -> {args.out}")
    if not args.apply:
        print("\nnothing was written. Re-run with --apply once the per-source histogram above is what you "
              "expect, then re-derive the slices with `evidence_batch --rebuild-slices` so the 24 commodity "
              "and 101 driver objects pick the repaired dates up under their own write guard.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
