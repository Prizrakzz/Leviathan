#!/usr/bin/env python
"""Phase G -- THE WEEKLY CORPUS-INGEST WRAPPER (fetch -> text -> chunk -> census).

WHY A WRAPPER EXISTS AT ALL, measured at HEAD, not argued.

(1) THE DESCRIPTOR LINT REJECTS THE COMMANDS THE LANE WOULD OTHERWISE WRITE.
    `scripts/silver/gen_sfn_inputs.py:311-323` accepts exactly two Batch shapes: module-form must
    carry `-m` at command[0] AND a name starting with `jobs.` at command[1]; script-form must end
    command[0] in `.py`. So `python -m leviathan.graphrag.evidence_batch --fill ...` is REJECTED
    ("must name a jobs.* module at command[1]"), and
    `submit_batch_evidence_maintenance.build_gated_command` returns `["-c", script]`, which the
    invocation_form check rejects outright. This file is the script-form entry point that makes the
    schedule legal. Its frozen, lint-legal command is:

        ["jobs/batch/corpus_ingest_task.py", "--stage", "chunk",
         "--max-docs", "200", "--max-usd", "5", "--poll-budget-seconds", "5400"]

(2) A SCHEDULE'S INPUT IS FROZEN AT APPLY TIME. EventBridge stores the StartExecution Input verbatim
    and the SFN passes `$.task.command` through unchanged, so a runtime gap list, a run id or an
    outstanding batch id are simply NOT EXPRESSIBLE there. Everything runtime-valued therefore moves
    INSIDE this file.

(3) `--fill --run` WAS NOT AVAILABLE. `--run` already exists (evidence_batch.py:1742) and dispatches
    the node-sampling submit+retrieve+ROUTE path (:1922) which WRITES commodity and driver slices;
    `--fill` short-circuits before it (:1868). An operator who dropped `--fill` by mistake would get
    a guarded slice-writing pass instead of a no-op. So this wrapper adds NO new flag to
    evidence_batch: it imports it and calls `submit_docs(...)` / `retrieve(...)` as LIBRARY
    FUNCTIONS. Chunking itself is never re-implemented here -- `chunking.chunk_document`, the three
    `DedupGate` layers and the 150,000-char `_FULLTEXT_CAP` are used exactly as they are.

(4) THE POLL IS UNBOUNDED AND THE JOBDEF HAS NO TIMEOUT. `retrieve` blocks in
    `while ... != "ended": sleep(20)` (evidence_batch.py:1369-1371), the Anthropic Batch SLA is 24 h,
    and `leviathan-dev-evidence-build` rev135 was measured live with `timeout: None` at the BAKED
    16 vCPU / 122,880 MB ($1.1812/h) -- so a naive submit-and-poll fire is a $28.35 bill and holds
    the SFN's submitJob.sync Map open the whole time. Hence `--poll-budget-seconds` (default 5400 =
    90 min = $1.77 hard ceiling) and a TWO-PHASE fire: on budget expiry the batch id goes into
    `coverage/ledger.json` and the NEXT weekly fire retrieves it before submitting anything new.
    That works because `_save_manifest` (evidence_batch.py:837-845) already persists the block
    manifest to `<EVIDENCE_S3>/_batches/<bid>.json` precisely so a DIFFERENT Fargate job can retrieve
    it.

(5) THE 110-DAY GAIN FETCH LAG IS THE RECENCY CEILING, not the chunker. Raw GAIN was last written
    2026-05-21/22 and seventeen `usda_gain_*` prefixes carry no EventBridge schedule of any kind.
    The census stage measures that lag explicitly (`CorpusFetchLagDaysMax`) so a fire cannot read
    green while the source stands still.

(6) `--evidence-s3` IS AN ENVIRONMENT BINDING, NOT AN ARGUMENT -- the defect the fix pass closed.
    `evidence_batch` has NO `--evidence-s3` flag: `select_docs`/`_cached_hashes`,
    `store_path_index`, `DedupGate`, `_build_requests_from_docs`, `submit_docs`, `retrieve` and
    `_save_manifest` all resolve `evidence._evid_s3()` = `os.environ["EVIDENCE_S3"]`
    (evidence.py:42-43). The first draft honoured the flag in the census, the caps and the ledger
    while every billed call read the environment, so the flag pointed at a shadow while the chunks
    landed live; and with the variable UNSET `_cached_hashes()` returned an empty set, which read
    `usda_gain_soybeans --all-gap` at 127 candidates / 1,352 blocks / $6.21 instead of 69 candidates
    / 69 ALIASED / 0 blocks -- the chunk-once law broken. `main` now binds the flag into the
    environment before any stage runs, `stage_chunk` re-reads `evidence._evid_s3()` and refuses on
    any disagreement, and the billed leg refuses outright when neither is set. EVERY FIGURE IN A
    DRY-RUN REPORT IS THEREFORE REPRODUCIBLE FROM THE COMMAND ALONE.

WHAT THIS FILE DELIBERATELY DOES NOT DO.

* It NEVER routes. A doc-list `retrieve` does not route by construction (evidence_batch.py:1428-1432)
  -- it only grows `chunks/`. So the chunk stage touches `chunks/` and `_batches/` and no guarded
  layer, which is what makes it (and only it) legal on the S3-staged override seam. THE FOLD IS
  NEVER STAGED; it is `jobs/batch/corpus_fold_task.py`.
* It never writes a slice, never touches pg, never calls CloudWatch, and never passes `--allow-churn`
  to anything.
* `--stage fetch` does NOT fetch. Sitting 1 ships the G1 RULE (ledger-bounded, refuse-an-undated-
  object) as a pure gate in `corpus_coverage.bound_listing` and REPORTS the bound each source's
  ledger entry would impose. Wiring it into `jobs/ingest/fetch_*.py` is a later sitting and is gated
  on the owner's `curl_cffi` ruling for `fas.usda.gov` (design risk 4); the producers are UNCHANGED
  here by design ("Existing producers, unchanged" -- design S 2, G1).
* `--stage text` does NOT extract. It runs the free raw-vs-text seam census (LIST only) and reports
  what the G2 key-layout gate WOULD refuse on those candidates. Three of the five text producers the
  lane needs do not exist at HEAD (`sagis_cec_text_task.py`, an mpoc producer, a recovered fnc
  producer) and writing them is a later sitting.

ASCII-only stdout (Windows console is cp1252).

    python jobs/batch/corpus_ingest_task.py --stage census --dry-run
    python jobs/batch/corpus_ingest_task.py --stage chunk --dry-run --sources usda_gain_soybeans
    python jobs/batch/corpus_ingest_task.py --stage chunk --max-docs 200 --max-usd 5 \
        --poll-budget-seconds 5400
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO / "src") not in sys.path:                 # a repo checkout with no editable install
    sys.path.insert(0, str(_REPO / "src"))

from leviathan.graphrag import corpus_coverage as cc  # noqa: E402

STAGES = ("fetch", "text", "chunk", "census")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _run_date(explicit: str | None) -> date:
    """The run date. THE ONE CLOCK READ IN THIS LANE, and it happens here so every pure core below
    takes `today` as an explicit argument and can never reach for `datetime.now()` on its own -- the
    fence against the Jan-1 / wrong-early class the whole design exists to close. `--asof` makes it
    injectable for a rehearsal."""
    if explicit:
        return date.fromisoformat(explicit[:10])
    return datetime.now(timezone.utc).date()


# ---------------------------------------------------------------------------------------------------
# stage: census
# ---------------------------------------------------------------------------------------------------

def stage_census(args, today: date) -> int:
    """3 free LISTs + 1 GET -> the alias-aware per-source table, the two lags, the four family
    metrics. `--dry-run` prints and writes NOTHING (sitting 1 runs read-only)."""
    print("stage=census  evidence_s3=%s  asof=%s  dry_run=%s"
          % (args.evidence_s3 or cc.evidence_prefix(), today, args.dry_run))
    t0 = time.time()
    raw = cc.read_inputs(bucket=args.bucket, evidence_s3=args.evidence_s3, region=args.aws_region)
    census = cc.build_census(raw["text_keys"], raw["chunk_names"], raw["alias_rows"],
                             raw["raw_keys"], today=today)
    print("  listed %d text docs, %d chunk objects, %d raw objects, %d alias rows in %.1fs"
          % (len(raw["text_keys"]), len(raw["chunk_names"]), len(raw["raw_keys"]),
             len(raw["alias_rows"]), time.time() - t0))
    print()
    print(cc.render_table(census))
    print()

    served = None
    try:
        from leviathan.graphrag import write_guard as wg
        manifest, label = wg.newest_run_manifest()
        served = cc.served_lag_days(manifest, today=today)
        n_spans = sum(1 for _l, sl in ((manifest or {}).get("slices") or {}).items()
                      if isinstance(sl, dict) for _n, r in sl.items()
                      if ((r or {}).get("after_span") or {}).get("date_max"))
        print("  served-slice manifest: %s (%d slice span(s))" % (label, n_spans))
        if served is None:
            print("    served lag is None because THAT manifest carries no per-slice after_span. "
                  "MEASURED FINDING: `newest_run_manifest` prefers the LOCAL configs/graphrag/eval/ "
                  "archive over S3 and picks by stamp, so on a laptop the newest LOCAL manifest can "
                  "be a non-rebuild one (x2_tail) with no spans. In-container that archive does not "
                  "exist (.dockerignore), so the S3 rebuild manifest is read instead. None is a "
                  "FINDING, never a fresh reading.")
    except Exception as exc:                                   # noqa: BLE001
        print("  served lag UNAVAILABLE (%s) -- reported as None, never as 0" % type(exc).__name__)

    print("  THE TWO LAGS (design S 2, G4 -- one number cannot describe a two-cadence lane):")
    print("    CorpusChunkLagDays  max = %s  (bound <= %.0f, set by the WEEKLY fire)"
          % (cc.chunk_lag_days_max(census), cc.CHUNK_LAG_CEILING_DAYS))
    print("    CorpusServedLagDays     = %s  (bound <= %.0f, set by the MONTHLY fold; LEDGER-ONLY, "
          "no 5th metric)" % (served, cc.SERVED_LAG_CEILING_DAYS))
    print("    CorpusFetchLagDays  max = %s  (the 110-day GAIN stall is what this exists to show)"
          % cc.fetch_lag_days_max(census))
    breaches = cc.breaching_sources(census)
    print("  breaching sources (%d): %s" % (len(breaches), ", ".join(breaches) or "none"))
    print("  date refusals: %d documents (design's standing residue is 62 = conab 55 + mpob 7); "
          "STRUCK from the write path: %s"
          % (census["totals"]["n_date_refusals"], ", ".join(sorted(cc.STRUCK_SOURCES))))
    nodate = census["totals"]["sources_without_a_derivable_raw_date"]
    # n_raw is printed BESIDE each name because `raw_date_derivable` is True both for "the keys are
    # dateable" AND for "there are no raw objects at all" (corpus_coverage.py:419,
    # `bool(newest_raw) or raw_seen.get(src, 0) == 0`). Without the count this list cannot be read as
    # complete: a source with 0 raw objects never appears here and is not thereby dateable.
    print("  sources whose RAW keys carry NO derivable date (%d): %s"
          % (len(nodate), ", ".join("%s(n_raw=%d)" % (s, (census["sources"].get(s) or {})
                                                      .get("n_raw_objects", 0)) for s in nodate)
             or "none"))
    if nodate:
        print("    -> their fetch_lag is UNAVAILABLE, not fresh. pub_date_layout's seven rules were "
              "written for TEXT keys; these sources' raw keys are bare slugs/seasons "
              "(e.g. raw/production/source=sagis_cec/CEC_2026-08-26.pdf). G1 then treats each as a "
              "FIRST FIRE and skips nothing -- the fail-safe direction. A raw-key layout rule per "
              "source is a NAMED prerequisite for the fetch-lag alarm.")
    print()
    print("  the FOUR family-rolled metrics (S 5; the 85-metric per-source shape is $25.50/mo and "
          "was priced and REJECTED):")
    for d in cc.metric_payloads(census):
        print("    %s{%s=%s} = %s [%s]"
              % (d["MetricName"], d["Dimensions"][0]["Name"], d["Dimensions"][0]["Value"],
                 d["Value"], d["Unit"]))

    ledger = cc.ledger_document(census, generated_at=_utc_now_iso(), served_lag=served,
                                outstanding_batch_id=cc.read_ledger(
                                    evidence_s3=args.evidence_s3,
                                    region=args.aws_region).get("outstanding_batch_id"),
                                fulltext_cap=_fulltext_cap())
    if args.dry_run:
        print()
        print("  DRY RUN: nothing written. The ledger this fire WOULD write is %d bytes to "
              "%s/%s" % (len(json.dumps(ledger)), ledger_prefix(args), cc.LEDGER_SUFFIX))
        if args.ledger_out:
            Path(args.ledger_out).write_text(json.dumps(ledger, indent=2), encoding="utf-8")
            print("  ledger preview -> %s" % args.ledger_out)
        return 0
    _write_ledger(args, ledger)
    return 0


def ledger_prefix(args) -> str:
    return (args.evidence_s3 or cc.evidence_prefix()).rstrip("/")


def _fulltext_cap():
    """Read the cap off the CONSTANT, never off a field name -- `novelty.py:125-126` warns that
    `partial_60k_flag` is a misnomer kept for compatibility, and `pdfpage`'s "an offset at or past
    the cap can never have been minted" refusal is a statement ABOUT this number. All three mirrors
    read 150000 today (evidence_batch.py:32, novelty.py:31, pdfpage.py:44)."""
    try:
        from leviathan.graphrag import evidence_batch as eb
        return eb._FULLTEXT_CAP
    except Exception:                                          # noqa: BLE001
        return None


def _write_ledger(args, ledger: dict, *, heartbeat: bool = True,
                  outcome: str = "CORPUS_INGEST_OK") -> None:
    """The ledger and the heartbeat are written LAST, after every other write has committed, so a
    half-finished fire never advertises itself as complete (design G5)."""
    import boto3
    bkt, key = cc._split_s3(ledger_prefix(args))
    s3 = boto3.client("s3", region_name=args.aws_region)
    s3.put_object(Bucket=bkt, Key="%s/%s" % (key, cc.LEDGER_SUFFIX),
                  Body=json.dumps(ledger).encode("utf-8"), ContentType="application/json")
    print("  ledger -> s3://%s/%s/%s" % (bkt, key, cc.LEDGER_SUFFIX))
    if heartbeat:
        hb = {"generated_at": ledger["generated_at"], "outcome": outcome,
              "chunk_lag_days_max": ledger["chunk_lag_days_max"],
              "fetch_lag_days_max": ledger["fetch_lag_days_max"],
              "coverage_min": ledger["coverage_min"]}
        s3.put_object(Bucket=bkt, Key="%s/%s" % (key, cc.HEARTBEAT_SUFFIX),
                      Body=json.dumps(hb).encode("utf-8"), ContentType="application/json")
        print("  heartbeat -> s3://%s/%s/%s" % (bkt, key, cc.HEARTBEAT_SUFFIX))


def _close_quiet(args, census: dict, *, outcome: str) -> None:
    """A scheduled fire that did NOT bill still leaves its trace (verify seat, 2026-09-07: seven early
    returns in stage_chunk skipped the ledger and the heartbeat, so the weekly no-op path -- today the
    ONLY path, since the gap is 861 documents against a 200-document cap -- left nothing on S3 and the
    freshness poller could not tell 'fired and found nothing' from 'never fired'). The census in hand
    already describes the store (nothing was written), so it is the ledger; the heartbeat carries the
    outcome word. A DRY RUN writes nothing, by contract."""
    if args.dry_run:
        print("  DRY RUN: no ledger, no heartbeat (%s)." % outcome)
        return
    _write_ledger(args, cc.ledger_document(census, generated_at=_utc_now_iso(),
                                           outstanding_batch_id=None,
                                           fulltext_cap=_fulltext_cap()),
                  outcome=outcome)


def _set_outstanding(args, bid: str | None) -> None:
    """Record (or clear) the outstanding batch id on its OWN, immediately after the submit -- not at
    the end of the fire. THE DESIGN SAYS 'on poll-budget expiry write the bid'; that leaves a window
    where a crash between `create` and the ledger write orphans a BILLED batch with nothing on S3
    naming it. Writing it straight after the submit closes that window and costs one PUT."""
    cur = cc.read_ledger(evidence_s3=args.evidence_s3, region=args.aws_region)
    cur["outstanding_batch_id"] = bid
    cur.setdefault("generated_at", _utc_now_iso())
    import boto3
    bkt, key = cc._split_s3(ledger_prefix(args))
    boto3.client("s3", region_name=args.aws_region).put_object(
        Bucket=bkt, Key="%s/%s" % (key, cc.LEDGER_SUFFIX),
        Body=json.dumps(cur).encode("utf-8"), ContentType="application/json")
    print("  ledger outstanding_batch_id := %s" % bid)


# ---------------------------------------------------------------------------------------------------
# stage: fetch  (the G1 RULE, reported -- the producers are unchanged)
# ---------------------------------------------------------------------------------------------------

def stage_fetch(args, today: date) -> int:
    """Report the LEDGER BOUND each source's fetch leg would be given, and prove the G1 gate on this
    fire's own inputs. NOTHING IS FETCHED HERE (design S 2 G1: "Existing producers, unchanged").

    The two rules, both in `corpus_coverage.bound_listing`:
      1. a source asks only for releases published AFTER its ledger `newest_raw_pub`, so a fire's
         cost is proportional to what published rather than to the archive's size;
      2. an object whose publication date cannot be read FROM THE SOURCE'S OWN LISTING is REFUSED and
         counted. There is no `datetime.now()` fallback anywhere in this lane -- `bound_listing`
         takes `today` as a required keyword precisely so it cannot read a clock."""
    raw = cc.read_inputs(bucket=args.bucket, evidence_s3=args.evidence_s3, region=args.aws_region)
    census = cc.build_census(raw["text_keys"], raw["chunk_names"], raw["alias_rows"],
                             raw["raw_keys"], today=today)
    print("stage=fetch  (REPORT ONLY -- no producer is invoked, no object is written)")
    print("%-28s%14s%12s  %s" % ("source", "newest_raw_pub", "fetch_lag", "the bound G1 would impose"))
    print("-" * 96)
    for src, r in sorted(census["sources"].items()):
        bound = r["newest_raw_pub"]
        note = ("ask only for releases published after %s" % bound) if bound else \
               "FIRST FIRE: no ledger entry -- every DATED release is in scope"
        if r["struck_from_write_path"]:
            note = "STRUCK from the write path: %s" % cc.STRUCK_SOURCES[src][0]
        print("%-28s%14s%12s  %s"
              % (src, bound or "-", r["fetch_lag_days"] if r["fetch_lag_days"] is not None else "-",
                 note))
    print()
    print("  G1 is DARK behind %s (armed=%s). Wiring it into jobs/ingest/fetch_*.py is a LATER "
          "sitting and the GAIN half is gated on the owner's curl_cffi ruling (design risk 4)."
          % (cc.GATE_FLAG, cc.gates_enabled()))
    return 0


# ---------------------------------------------------------------------------------------------------
# stage: text  (the raw-vs-text seam census + what G2 would refuse)
# ---------------------------------------------------------------------------------------------------

def stage_text(args, today: date) -> int:
    """The free (LIST-only) raw-vs-text seam census, plus the G2 verdict over every text key. The
    design measured 87 unconverted document-shaped raw objects (sagis 46, mpoc 24, mpob 13, GAIN 3,
    conab 1) and 3 orphan `usda_wap` text documents whose raw object is gone; this reproduces the
    shape without a single GET. NO EXTRACTION HAPPENS HERE."""
    raw = cc.read_inputs(bucket=args.bucket, evidence_s3=args.evidence_s3, region=args.aws_region)
    doc_shaped = (".pdf", ".doc", ".docx", ".html", ".htm", ".txt")
    per: dict[str, dict] = {}
    text_by_src: dict[str, int] = {}
    for k in raw["text_keys"]:
        text_by_src[cc.source_of(k)] = text_by_src.get(cc.source_of(k), 0) + 1
    for k in raw["raw_keys"]:
        src = cc.source_of(k)
        rec = per.setdefault(src, {"raw": 0, "doc_shaped": 0})
        rec["raw"] += 1
        if k.lower().endswith(doc_shaped):
            rec["doc_shaped"] += 1
    print("stage=text  (SEAM CENSUS ONLY -- no producer is invoked, no document is written)")
    print("%-28s%10s%14s%10s%12s" % ("source", "raw", "doc-shaped", "text", "unconverted"))
    print("-" * 76)
    tot_unconv = 0
    for src in sorted(set(per) | set(text_by_src)):
        rec = per.get(src, {"raw": 0, "doc_shaped": 0})
        n_text = text_by_src.get(src, 0)
        unconv = rec["doc_shaped"] - n_text
        tot_unconv += max(0, unconv)
        print("%-28s%10d%14d%10d%12d" % (src, rec["raw"], rec["doc_shaped"], n_text, unconv))
    print("-" * 76)
    print("  unconverted (doc-shaped raw with no document.json), summed over positives: %d"
          % tot_unconv)
    print("  NOTE a NEGATIVE unconverted count is an ORPHAN text document whose raw object is gone "
          "(the design measured 3 for usda_wap). Counted, never hidden.")
    verdicts: dict[str, int] = {}
    for k in raw["text_keys"]:
        _ok, reason, layout = cc.key_layout_verdict(k)
        label = reason if reason == cc.REASON_OK else "%s:%s" % (reason, layout)
        verdicts[label] = verdicts.get(label, 0) + 1
    print("  G2 verdict over the %d EXISTING text keys (armed=%s):"
          % (len(raw["text_keys"]), cc.gates_enabled()))
    for label, n in sorted(verdicts.items(), key=lambda kv: -kv[1]):
        print("    %-48s %d" % (label, n))
    return 0


# ---------------------------------------------------------------------------------------------------
# stage: chunk  (the billed one -- and the only one with caps)
# ---------------------------------------------------------------------------------------------------

def _gap_doc_keys(args, census: dict, sources: list[str]) -> list[str]:
    """The documents this fire would chunk.

    DEFAULT (`--since-ledger`, on): only documents published AFTER that source's
    `newest_covered_pub` -- the chunk-stage half of the ledger bound. THE DESIGN DOES NOT STATE THIS
    AND IT MUST: the historical gap is 861 documents and the per-run cap is 200, so a fire that
    always took the whole gap would REFUSE forever and the weekly lane would never move. The
    backlog is an OPTIONAL, PRICED, operator-run item (design S 3 / S 10.1, ~$19.6 over 686 non-soy
    documents), and `--all-gap` is how an operator asks for it -- at which point the cap refuses and
    names the number, which is the correct outcome, not an obstacle.

    WHAT `--since-ledger` IS BLIND TO, and it must be said: a BACK-DATED release. The filter below
    accepts only `d > newest_covered_pub`, so a source that later files a document dated BEFORE its
    current covered edge is invisible to every weekly fire, forever -- only an operator `--all-gap`
    can see it, and the caps then refuse and price it. That is a real hole in the lane's own 100%
    coverage target, it is accepted here because the alternative (re-scanning the whole 861-document
    gap weekly against a 200 cap) refuses every week and moves nothing, and the ledger's per-source
    `docs` vs `chunked + aliased` columns are where it shows up. Closing it properly is a
    ledger-of-seen-keys, which is a later sitting.

    `select_docs` (evidence_batch.py:1582-1598) already drops anything already in `chunks/` via
    `_cached_hashes`; the ALIAS layers are applied later, inside `submit_docs`' `DedupGate`, which is
    why a `--sources usda_gain_soybeans` fire reports 0 NEW docs rather than 69. Both depend on
    EVIDENCE_S3 being bound (main() does it): with it unset `_cached_hashes()` is EMPTY and this
    function returns the whole corpus as "new"."""
    from leviathan.graphrag import evidence_batch as eb
    keys = eb.select_docs(sources)                             # md5-cached filter, free-ish
    if args.all_gap:
        return sorted(keys)
    out = []
    for k in keys:
        src = cc.source_of(k)
        rec = census["sources"].get(src) or {}
        edge = rec.get("newest_covered_pub")
        d, _lay = cc._pub_date(k)
        if d is None:
            continue                                           # G2's population: never chunked here
        if edge is None or d > date.fromisoformat(edge):
            out.append(k)
    return sorted(out)


def stage_chunk(args, today: date) -> int:
    import boto3
    from leviathan.graphrag import evidence_batch as eb

    # THE ONE-STORE ASSERTION, read through the EXACT function every billed call resolves
    # (`evidence._evid_s3`, evidence.py:42-43) rather than through a copy of the same idea. main()
    # binds it; this refuses if anything between here and there moved it. A billed leg whose census
    # describes one prefix and whose writes land in another is the defect this lane exists to avoid.
    effective = (eb.ev._evid_s3() or "").rstrip("/")
    if effective != (args.evidence_s3 or "").rstrip("/"):
        raise SystemExit("REFUSED: evidence_batch would read %r while this fire priced and capped "
                         "%r. The chunks, the batch manifest and the alias index all follow "
                         "evidence._evid_s3(), so they would land in a store this run never "
                         "measured." % (effective, args.evidence_s3))
    s3 = boto3.client("s3", region_name=args.aws_region)
    ledger = cc.read_ledger(evidence_s3=args.evidence_s3, region=args.aws_region)
    outstanding = ledger.get("outstanding_batch_id")
    print("stage=chunk  evidence_s3=%s  asof=%s  dry_run=%s  max_docs=%d  max_usd=%.2f  "
          "poll_budget=%ds" % (ledger_prefix(args), today, args.dry_run, args.max_docs,
                               args.max_usd, args.poll_budget_seconds))
    print("  fulltext_cap = %s (evidence_batch.py:32; mirrors novelty.py:31 and pdfpage.py:44 -- "
          "NEVER hardcode 60,000)" % _fulltext_cap())

    # PHASE 1 -- retrieve any OUTSTANDING batch BEFORE submitting anything new.
    if outstanding:
        print("  OUTSTANDING batch %s from a prior fire -- retrieving it FIRST" % outstanding)
        if args.dry_run:
            print("  DRY RUN: would poll %s (budget %ds) then call evidence_batch.retrieve(); a "
                  "doc-list retrieve does NOT route (evidence_batch.py:1428-1432)."
                  % (outstanding, args.poll_budget_seconds))
        else:
            rc = _drain_batch(args, s3, outstanding)
            if rc != 0:
                return rc

    # PHASE 2 -- select, price, cap, submit.
    raw = cc.read_inputs(bucket=args.bucket, evidence_s3=args.evidence_s3, region=args.aws_region)
    census = cc.build_census(raw["text_keys"], raw["chunk_names"], raw["alias_rows"],
                             raw["raw_keys"], today=today)
    if args.sources:
        sources = [s for s in args.sources.split(",") if s]
    else:
        sources = [s for s, r in sorted(census["sources"].items())
                   if r["gap"] > 0 and not r["struck_from_write_path"]]
    struck = [s for s in sources if s in cc.STRUCK_SOURCES]
    if struck:
        print("  REFUSING the struck source(s) %s -- a NAMED date refusal still floors to Jan-1 "
              "(evidence.py:318-324), so every new document from them would land on year_floor BY "
              "CONSTRUCTION. Named prerequisite per source is in the ledger." % ", ".join(struck))
        sources = [s for s in sources if s not in cc.STRUCK_SOURCES]
    print("  sources (%d): %s" % (len(sources), ",".join(sources) or "none"))
    if not sources:
        print("  nothing to do.")
        _close_quiet(args, census, outcome="CORPUS_INGEST_NOTHING_TO_DO")
        return 0

    keys = _gap_doc_keys(args, census, sources)
    print("  candidate documents: %d  (mode=%s)"
          % (len(keys), "ALL-GAP (a backfill)" if args.all_gap else "since-ledger (the weekly bound)"))
    if not keys:
        print("  0 candidates -- nothing to chunk. (For usda_gain_soybeans this is the CORRECT "
              "answer: all 69 'stragglers' are byte-identical co-filings already ALIASED in "
              "_index/doc_aliases.jsonl; forcing them would re-pay Haiku for 69 identical documents "
              "and mint a SECOND set of props under a second source_key.)")
        _close_quiet(args, census, outcome="CORPUS_INGEST_NO_CANDIDATES")
        return 0

    # THE FREE LOCAL SPLIT -- the exact block count, before a single request is billed. This is
    # `evidence_batch`'s own fill dry-run path: DedupGate seeded with store_path_index (2 LISTs,
    # 0 GETs), which is the layer that already aliased all 69 soybean annuals.
    reads = eb.DocReadTally(label="corpus_ingest_split")
    dedup = eb.DedupGate(store_paths=eb.store_path_index(s3))
    tally = eb.DarkTally(label="corpus_ingest")
    reqs, manifest = eb._build_requests_from_docs(s3, keys, tally=tally, reads=reads, dedup=dedup)
    # `reads.report()` and NOT `reads.raise_if_over()`: this pre-split is a PRICE QUOTE, and a quote
    # must be allowed to show a bad drop rate rather than die before printing it. The fence is not
    # skipped -- `submit_docs` builds its own DedupGate, re-reads the bodies and calls
    # `raise_if_over` itself, so the drop-rate refusal still fires before any batch is created. The
    # cost of that correctness is that every candidate body is GET twice on a real fire.
    reads.report()
    dedup.report()
    if args.all_gap:
        print("  BACKLOG RIDER (PIT): a full-gap pass is NOT purely additive. `DedupGate.flush()`"
              " re-points existing alias canonicals at later-dated byte-identical twins -- the"
              " 2026-09-07 backlog dry run printed `dedup PIT: 671 canonical(s) DEPOSED by a"
              " later-dated byte-identical twin`. That is evidence_batch's ratified keeper rule, not"
              " this lane's, but it CHANGES WHICH DOCUMENT'S PUBLICATION DATE SURVIVES for 671"
              " texts and belongs in the backlog's price tag beside the dollars.")
    ndocs = len({m["source_key"] for m in manifest.values()})
    price = cc.price_blocks(len(reqs))
    print("  SPLIT: %d blocks over %d NEW docs" % (len(reqs), ndocs))
    print("    tight estimate  $%.2f  (%.7f/request, evidence_batch.py:1907)"
          % (price["tight_usd"], cc.TIGHT_USD_PER_REQUEST))
    print("    fill band       ~$%.0f-%.0f  (evidence_batch.py:1886-1887, a 3.5x spread) -- printed "
          "BESIDE the tight number, never instead of it"
          % (price["band_lo_usd"], price["band_hi_usd"]))
    print("    truncated at the %s cap: %d doc(s)"
          % (_fulltext_cap(), len(getattr(tally, "truncated_docs", ()) or ())))

    refusals = cc.check_caps(n_docs=ndocs, n_blocks=len(reqs),
                             max_docs=args.max_docs, max_usd=args.max_usd)
    if refusals:
        for line in refusals:
            print("  " + line)
        print("  NOTE the caps bound HAIKU TOKENS ONLY. The fire's dominant cost is Fargate "
              "wall-clock on a jobdef measured live with timeout: None, and THAT is bounded by "
              "--poll-budget-seconds %d (90 min = $1.77 at the baked 16 vCPU / 122,880 MB)."
              % args.poll_budget_seconds)
        _close_quiet(args, census, outcome="CORPUS_INGEST_REFUSED_CAP")
        return 2                                               # refuse LOUDLY, bill nothing
    if not reqs:
        print("  0 blocks -- every candidate was already cached or aliased. Nothing submitted.")
        _close_quiet(args, census, outcome="CORPUS_INGEST_ALL_CACHED")
        return 0

    if args.dry_run:
        print("  DRY RUN: nothing submitted, nothing written, $0 billed.")
        return 0

    import anthropic
    from leviathan.graphrag import batch_extract as bx
    client = anthropic.Anthropic(api_key=bx._api_key())
    bid = eb.submit_docs(s3, client, keys)                      # library call: NO new evidence_batch flag
    _set_outstanding(args, bid)                                # ...recorded before we start polling
    rc = _drain_batch(args, s3, bid, client=client)
    if rc != 0:
        return rc
    # THE LEDGER AND THE HEARTBEAT GO LAST, after chunks/ and _batches/ have committed, so a
    # half-finished fire never advertises itself as complete (design G5). The census is re-taken
    # here on purpose: it must describe the store AFTER this fire, not before it.
    after = cc.read_inputs(bucket=args.bucket, evidence_s3=args.evidence_s3, region=args.aws_region)
    census2 = cc.build_census(after["text_keys"], after["chunk_names"], after["alias_rows"],
                              after["raw_keys"], today=today)
    _write_ledger(args, cc.ledger_document(census2, generated_at=_utc_now_iso(),
                                           outstanding_batch_id=None,
                                           fulltext_cap=_fulltext_cap()))
    return 0


def _drain_batch(args, s3, bid: str, client=None) -> int:
    """Poll ONE batch inside the wall-clock budget, then hand it to `evidence_batch.retrieve`.

    The budget is the fence: `retrieve` polls forever on its own (evidence_batch.py:1369-1371) and
    the jobdef has `timeout: None`, so the poll happens HERE and `retrieve` is only entered once the
    batch already reads `ended` -- at which point its own while-loop falls straight through. On
    expiry the bid stays in the ledger and the NEXT fire drains it; that is the two-phase fire, and
    it works because `_save_manifest` already put the block manifest on S3."""
    import anthropic
    from leviathan.graphrag import batch_extract as bx
    from leviathan.graphrag import evidence_batch as eb
    client = client or anthropic.Anthropic(api_key=bx._api_key())
    deadline = time.time() + args.poll_budget_seconds
    while True:
        status = client.messages.batches.retrieve(bid).processing_status
        if status == "ended":
            break
        if time.time() >= deadline:
            print("  POLL BUDGET EXPIRED (%ds) with batch %s still %r. The bid stays in the ledger "
                  "and the NEXT fire retrieves it before submitting anything new; its block "
                  "manifest is already on S3 at _batches/%s.json. Exiting 0 -- this is the designed "
                  "outcome, not a failure." % (args.poll_budget_seconds, bid, status, bid))
            _set_outstanding(args, bid)
            return 0
        print("  batch %s: %s (%.0fs of budget left)" % (bid, status, deadline - time.time()))
        time.sleep(args.poll_seconds)
    from leviathan.graphrag import write_guard as wg
    mf = wg.RunManifest("corpus_ingest", chunk_version=eb._chunk_version())
    try:
        eb.retrieve(s3, client, bid, manifest=mf)               # doc-list: grows chunks/, does NOT route
    except wg.WriteRefused as exc:
        print("REFUSED: the write guard stopped this pass before anything was written.")
        for line in exc.lines:
            print("  - " + line)
        mf.warnings.append("REFUSED: " + " | ".join(exc.lines))
        mf.flush()
        return 2
    mf.flush()
    _set_outstanding(args, None)
    return 0


# ---------------------------------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Phase G weekly corpus-ingest wrapper (fetch/text/chunk/census)")
    ap.add_argument("--stage", required=True, choices=STAGES,
                    help="fetch (report the G1 bound), text (seam census + G2 verdict), "
                         "chunk (the billed leg), census (the alias-aware ledger)")
    ap.add_argument("--sources", default="",
                    help="comma-separated source names; default = the census's own gap list")
    ap.add_argument("--max-docs", type=int, default=cc.MAX_DOCS_DEFAULT,
                    help="per-run NEW-document cap; over it the fire REFUSES and names the number")
    ap.add_argument("--max-usd", type=float, default=cc.MAX_USD_DEFAULT,
                    help="per-run Haiku cap, checked against the TIGHT estimator before any submit")
    ap.add_argument("--poll-budget-seconds", type=int, default=cc.POLL_BUDGET_SECONDS_DEFAULT,
                    help="hard wall-clock ceiling on the batch poll; on expiry the bid goes in the "
                         "ledger and the next fire retrieves it")
    ap.add_argument("--poll-seconds", type=int, default=20, help="poll interval inside the budget")
    ap.add_argument("--all-gap", action="store_true",
                    help="take the WHOLE historical gap instead of only what is newer than the "
                         "ledger edge -- an operator BACKFILL, which the per-run cap will refuse "
                         "and price")
    ap.add_argument("--asof", default=None,
                    help="run date (ISO); the ONE clock read in this lane, injectable for rehearsal")
    ap.add_argument("--evidence-s3", default=None,
                    help="the read+write prefix. It is EXPORTED as EVIDENCE_S3 before any stage "
                         "runs, because that variable -- not any flag -- is the only channel "
                         "evidence_batch reads (evidence.py:42-43). The billed chunk leg REFUSES "
                         "when neither this flag nor the variable is set")
    ap.add_argument("--bucket", default=cc.BUCKET)
    ap.add_argument("--aws-region", default="us-east-1", dest="aws_region")
    ap.add_argument("--ledger-out", default=None,
                    help="dry-run only: write the ledger PREVIEW to this local path")
    ap.add_argument("--dry-run", action="store_true")
    return ap


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(line_buffering=True)             # container stdout is a PIPE to awslogs
    except (AttributeError, ValueError):
        pass
    args = build_parser().parse_args(argv)
    try:
        from leviathan.common import config
        config.load_env()
    except Exception as exc:                                    # noqa: BLE001
        print("  NOTE: config.load_env() unavailable (%s) -- relying on the ambient environment"
              % type(exc).__name__)
    # BIND THE PREFIX BEFORE ANY STAGE RUNS, and before `evidence_batch` is imported anywhere in this
    # process. `--evidence-s3` was documented as an "EVIDENCE_S3 override" but was INERT on the only
    # billed leg: `select_docs`/`_cached_hashes`, `store_path_index`, `DedupGate`,
    # `_build_requests_from_docs`, `submit_docs`, `retrieve` and `_save_manifest` all read
    # `evidence._evid_s3()` = os.environ["EVIDENCE_S3"] (evidence.py:42-43) and evidence_batch has no
    # flag of its own. Measured with the flag at a shadow prefix and the variable at live: the census,
    # the caps and the ledger described the SHADOW while the chunks, the batch manifest and the alias
    # index would have landed LIVE. Measured with the flag set and the variable unset:
    # `_cached_hashes()` empty -> usda_gain_soybeans read 127 candidates / 1,352 blocks / $6.21
    # instead of 69 candidates / 69 ALIASED / 0 blocks. `require` is the billed leg's fence: the
    # read-only stages may fall back to the default live prefix (that is what the census has always
    # done), the chunk stage may not. The FROZEN schedule command carries no --evidence-s3 and does
    # not need one: `leviathan-dev-evidence-build` bakes EVIDENCE_S3 (VERIFIED -- the fold's
    # live-prefix guard reads exactly that env off the jobdef via describe_job_definitions and
    # printed `s3://leviathan-dev-shahem-001/graphrag_evidence` on the 2026-09-07 dry run). If a
    # future jobdef revision ever drops it, this refuses instead of re-chunking the corpus.
    # It runs AFTER config.load_env() on purpose, so a .env value counts as ambient.
    args.evidence_s3 = cc.bind_evidence_prefix(args.evidence_s3, require=(args.stage == "chunk"))
    today = _run_date(args.asof)
    if args.stage == "census":
        return stage_census(args, today)
    if args.stage == "fetch":
        return stage_fetch(args, today)
    if args.stage == "text":
        return stage_text(args, today)
    return stage_chunk(args, today)


if __name__ == "__main__":
    raise SystemExit(main())
