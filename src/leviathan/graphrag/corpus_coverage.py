"""Phase G, sitting 1 -- the ALIAS-AWARE corpus coverage census, the two freshness lags, and the
two ingestion gates (G1 ledger-bounded fetch, G2 key-layout) as PURE, TESTABLE cores.

NAME, AND WHY IT IS NOT `coverage.py`. TEXT_INGESTION_LANE_DESIGN.md (rev 2, S 13) lists
`src/leviathan/graphrag/coverage.py` under "files this lane creates". THAT FILE ALREADY EXISTS AT
HEAD and is live code: it is the WS-MS5 per-node x per-source evidence coverage report
(`python -m leviathan.graphrag.coverage` -> configs/graphrag/eval/coverage_node_source.md), imported
by `e3_sizing.py:290` and pinned by `tests/unit/test_eval.py:5`. Creating the lane's census there
would have deleted a live module and reddened two consumers. The design was written without checking
the tree; the collision is reported rather than papered over, and the lane's census lands here.

WHY THIS MODULE EXISTS, MEASURED, NOT ARGUED.

(1) THE md5-JOIN ARTEFACT THAT FOOLED TWO SEATS ON 2026-09-07. The obvious coverage metric joins the
    text layer to `graphrag_evidence/chunks/<md5(text_key)>.jsonl` and calls anything that misses
    "never chunked". That metric read `usda_gain_soybeans` at 58/127 = 45.7% and sent a brief to
    "chunk the 69 stragglers". The 69 are byte-identical CO-FILINGS of one GAIN Oilseeds-and-Products
    Annual filed by FAS under several commodity prefixes; the estate chunked each ONCE under a
    sibling prefix and recorded the fold in `_index/doc_aliases.jsonl` (146 rows, every one
    `layer: store_path`). `DedupGate` (evidence_batch.py:597-760) exists for exactly this and
    `_build_requests_from_docs` (:1609-1648) would have refused the run at
    SystemExit("all requested docs already in the chunk cache") (:1687). Forcing it would have
    re-paid Haiku for 69 byte-identical documents (~$1.0) and minted a SECOND set of props for one
    text under a second `source_key` -- a direct violation of chunk-once, whose price is on the
    record: billing ROWS instead of PATHS cost $61.92 against $53.52 on the X2 work set.
    So: a document is COVERED when it is chunked, OR its path twin is chunked, OR the persisted
    alias index says it was folded into a chunked canonical. Naive 84.0% -> alias-aware 87.8%
    corpus-wide, and `usda_gain_soybeans` 45.7% -> 100.0%.

(2) THE 110-DAY GAIN FETCH LAG. The recency ceiling is the FETCH, not the chunker: raw GAIN was last
    written 2026-05-21/22 and seventeen `usda_gain_*` prefixes carry no EventBridge schedule of any
    kind. That is why the ledger carries `newest_raw_pub` and `fetch_lag_days` per source and why
    `CorpusFetchLagDaysMax` is one of the four metrics -- a census that only measured chunk coverage
    would have read GREEN through the whole 110-day stall.

(3) THE Jan-1 FLOOR AT evidence.py:318-324. `doc_date_detail` falls through a NAMED refusal to
    `y = bx._year_of(key); return date(int(y), 1, 1), "year_floor"`, and then to `epoch_floor`
    1970-01-01. A floored date is always on or BEFORE the true release, i.e. leakage-PERMISSIVE in
    exactly the field the as-of filter compares (`evidence.py:639`,
    `recs = [r for r in all_records if r["date"] <= asof]`). The D-EC P0c census measured 2,036 of
    7,056 documents (28.9%) on that fallback; the seven key rules closed that class and the standing
    residue is 62 documents (conab 55 + mpob 7). G2 keeps it at 62 by refusing the WRITE rather than
    letting a new document floor.

WHAT THIS MODULE DELIBERATELY DOES NOT COVER.

* It never writes S3, never calls CloudWatch and never fetches anything. It returns payloads; the
  caller writes them. Sitting 1 runs read-only.
* `layer_row_churn` is `null` in every run manifest -- row-level |lost|+|gained| needs the prior row
  SET (101 GETs / 1.361 GB) -- so a frozen slice COUNT here does not prove no rows moved. The served
  lag below reads span ENDPOINTS, not row identity.
* The content-hash dedupe layer (sha1(full_text)) is NOT reproduced here: `chunks/` holds no
  full_text, so a content twin is only recoverable from the persisted `_index/content_hashes.jsonl`
  plus a GET per document. This census is 3 LISTs + 1 GET by construction, so it scores the two PATH
  layers and the persisted alias rows and nothing else. A content twin that was never written to the
  alias index therefore reads as a GAP here -- the conservative direction: it over-counts work to do,
  it never under-counts it.
* Reachability, WAF and in-VPC network facts are not this module's subject.
"""
from __future__ import annotations

import collections
import hashlib
import json
import re
import threading
from datetime import date

# -- identity constants ----------------------------------------------------------------------------
BUCKET = "leviathan-dev-shahem-001"
TEXT_PREFIX = "text/"
RAW_PREFIX = "raw/production/"
DOCUMENT_NAME = "document.json"

# The lane's own artifacts. `graphrag_evidence/coverage/` does not exist today (LIST verified, 0
# objects); this lane creates it and nothing else.
LEDGER_SUFFIX = "coverage/ledger.json"
HEARTBEAT_SUFFIX = "coverage/last_run.json"
ALIAS_INDEX_SUFFIX = "_index/doc_aliases.jsonl"
CHUNKS_SUFFIX = "chunks/"

FAMILY = "graphrag_evidence"

# -- THE FLAG. Both gates are DARK behind it and the flag-off path is byte-identical. ---------------
# The design (revision 2) names no flag, so the lane mints one. `on`/`1`/`true`/`yes` arms it; ANY
# other value -- including unset, empty and "off" -- leaves both gates inert. `raw_to_text.writer`
# imports this module LAZILY and only when the flag is on, so a flag-off text producer does not even
# pay the import (this module reaches `evidence.py` -> `extract.py` -> yaml + pydantic; the
# b3-flat-silver image carries them, but a dark path must cost NOTHING, not merely little).
GATE_FLAG = "CORPUS_LANE_GATES"
_TRUTHY = frozenset({"1", "true", "on", "yes"})


def gates_enabled(env=None) -> bool:
    """True when the lane's gates are ARMED. `env` is injectable so a deck never has to mutate the
    session's os.environ."""
    import os
    src = os.environ if env is None else env
    return str(src.get(GATE_FLAG) or "").strip().lower() in _TRUTHY


# -- the two sources STRUCK from this lane's write path (design S 4, clause 3) -----------------------
# A NAMED refusal still floors (evidence.py:318-324), so every new conab/mpob document would land on
# `year_floor` BY CONSTRUCTION and the lane's own acceptance ("zero new documents on year_floor or
# epoch_floor") would be self-contradictory. Each carries a NAMED PREREQUISITE; a source re-enters
# the lane the day its layout rule exists, which is why the gate below keys on the LAYOUT (a parsed
# date passes) and not on a hard-coded source list. This mapping is documentation for the ledger and
# the census, never a second gate.
STRUCK_SOURCES = {
    "conab": ("conab_survey_is_not_a_month",
              "needs a crop_year=YYYY_YY/survey=NN -> month calendar rule: NN maps to two different "
              "months across an era boundary the key does not state (pre-2013 OlalaCMS vs modern)"),
    "mpob": ("year_only",
             "needs a year=YYYY -> release month rule: the overview PDFs are one file per calendar "
             "year with no finer stamp anywhere in the key"),
}

# -- caps and prices (design S 3; every constant cited to its line) ---------------------------------
MAX_DOCS_DEFAULT = 200               # per-run document cap; a fire that wants more is a backfill
MAX_USD_DEFAULT = 5.0                # per-run Haiku cap
POLL_BUDGET_SECONDS_DEFAULT = 5400   # 90 min wall clock. evidence-build rev135 is `timeout: None`
#                                      and `retrieve` blocks on a 20 s poll
#                                      (evidence_batch.py:1369-1371); the Anthropic Batch SLA is
#                                      24 h = $28.35 for ONE fire at the baked 16 vCPU / 122,880 MB
#                                      ($1.1812/h). This is the fence that bounds the fire.

# The TIGHT per-request estimator, evidence_batch.py:1907 -- 1,500 input + 1,537 output tokens at
# Haiku-4.5 Batch $0.50/$2.50 per M. It belongs to the NODE-sampling dry-run.
TIGHT_USD_PER_REQUEST = 1500 * 0.5 / 1e6 + 1537 * 2.5 / 1e6      # == 0.0045925
# The FILL dry-run's own printed band, evidence_batch.py:1886-1887 -- a 3.5x spread. Printed BESIDE
# the tight number, never instead of it, so the two are never confused again.
FILL_BAND = (0.002, 0.007)

# -- the lane's declared freshness contract (design S 2 G4 / A6) ------------------------------------
# These are the ARMED-STATE contract, not a measurement. Today's census reads most of them RED by
# construction: the weekly fire is not armed, the optional 686-document backlog is not bought, and
# the GAIN fetch is gated on the owner's curl_cffi ruling. Arming the alarms therefore queues behind
# those, and this module says so rather than shipping a pager that is red on day one.
CHUNK_LAG_CEILING_DAYS = 7.0
SERVED_LAG_CEILING_DAYS = 35.0
FETCH_LAG_CEILING_DAYS = 7.0
COVERAGE_FLOOR = 1.0                 # A1's acceptance bar: alias-aware coverage 87.8% -> 100.0%

# -- the FOUR family-rolled metrics (design S 5; the 85-metric shape is PRICED AND REJECTED) --------
# CloudWatch bills each distinct dimension VALUE as its own custom metric and `Leviathan/Silver`
# already carries 189 unique streams today, so 28 sources x 3 + 1 = 85 metrics x $0.30 =
# $25.50/month -- more than the entire lane ($14.7/month). Four family-rolled metrics + four alarms
# = $1.60/month. The per-source detail is NOT lost: it lives in coverage/ledger.json on S3, which is
# free and is the artifact an operator actually reads. CloudWatch is the pager; S3 is the record.
# DO NOT add a per-source dimension here. The deck pins the cardinality.
METRIC_NAMESPACE = "Leviathan/Silver"
METRIC_COVERAGE_MIN = "CorpusChunkCoverageMin"
METRIC_CHUNK_LAG_MAX = "CorpusChunkLagDaysMax"
METRIC_FETCH_LAG_MAX = "CorpusFetchLagDaysMax"
METRIC_BREACH_COUNT = "CorpusCoverageBreachCount"
FAMILY_METRIC_NAMES = (METRIC_COVERAGE_MIN, METRIC_CHUNK_LAG_MAX,
                       METRIC_FETCH_LAG_MAX, METRIC_BREACH_COUNT)
# The SERVED lag is deliberately NOT a metric. A6 wants it alarmed; S 5's priced FOUR do not include
# it; a fifth metric plus its alarm is +$0.40/month. It rides the LEDGER (free) under
# `served_lag_days` until the owner rules. Stated so the omission is a decision, not a miss.

_SOURCE_RE = re.compile(r"(?:^|/)(?:text|raw/production)/source=([^/]+)/")
_SOURCE_SEG = re.compile(r"/source=[^/]+/")


def source_of(key: str) -> str:
    """The `source=<s>` segment of a text/ or raw/production/ key, or 'unknown'."""
    m = _SOURCE_RE.search(key)
    return m.group(1) if m else "unknown"


def path_fingerprint(key: str) -> str:
    """A document's identity ACROSS sources: its key with the `source=<src>/` segment removed.

    This is `evidence_batch._path_fingerprint` (:457-463, `_SOURCE_SEG` at :454) reproduced as a
    LEAF so the census costs no import of the chunker. It is pinned byte-for-byte against the
    original by the deck: if the chunker's identity rule ever moves, the census must move with it or
    it starts scoring aliases as gaps again -- which is the whole defect this module exists for."""
    return _SOURCE_SEG.sub("/", key, count=1)


def doc_cache_name(text_key: str) -> str:
    """The `chunks/<name>.jsonl` object name for a text key -- md5 of the key, exactly as
    `evidence_batch._doc_cache_node` (:252-254) mints it. Pinned against it by the deck."""
    return hashlib.md5(text_key.encode("utf-8")).hexdigest()


def _pub_date(key: str):
    """(date|None, layout) from the key alone. NO document.json in this corpus carries a date field
    (raw_to_text/schema.py:15-26), and `extracted_at` is a FETCH timestamp that is never the PIT
    date. Imported lazily so this module stays cheap for the writer seam."""
    from leviathan.graphrag import evidence as ev
    return ev.pub_date_layout(key)


# ===================================================================================================
# G2 -- THE KEY-LAYOUT GATE (before write_document)
# ===================================================================================================

class KeyLayoutRefused(Exception):
    """A text key whose publication date cannot be PARSED from the key. Raised by the G2 gate in
    place of a silent Jan-1 floor. Carries the key, the layout that refused, and a reason code."""

    def __init__(self, key: str, reason: str, layout: str):
        self.key, self.reason, self.layout = key, reason, layout
        super().__init__(f"G2 REFUSED {reason} layout={layout!r} key={key}")


REASON_OK = "ok"
REASON_UNKNOWN_LAYOUT = "unknown_key_layout"
REASON_NAMED_REFUSAL = "named_refusal"

_refusals: "collections.Counter[str]" = collections.Counter()
_refusal_lock = threading.Lock()


def refusal_counts() -> dict:
    """The gate's running tally, `{label: n}`. Every refusal is COUNTED, never silent -- the text
    producers run a 30-thread pool (gain_text_task._WORKERS), hence the lock."""
    with _refusal_lock:
        return dict(_refusals)


def reset_refusals() -> None:
    with _refusal_lock:
        _refusals.clear()


_summary_registered = False


def _register_refusal_summary() -> None:
    """Print the tally ONCE at process exit, so 'refuses loudly AND COUNTS' holds in production.

    THE MEASURED GAP (fix pass): `refusal_counts()` had exactly one reader in the tree -- the deck.
    No producer and neither wrapper printed it, and each text producer is its own Fargate process, so
    an armed gate's Counter died with the task and the count reached nobody. Registering here rather
    than in each producer keeps the seam at ONE file: the gate is the only thing the producers import
    and the only thing that knows a refusal happened. Registered lazily on the FIRST count, so a
    flag-off producer pays nothing (it never imports this module at all -- writer.py's import is
    inside `if _gate_armed()`).

    ASCII only (Windows console is cp1252) and it can never raise: an atexit handler that throws
    would turn a clean task into a nonzero exit at teardown."""
    global _summary_registered
    if _summary_registered:
        return
    _summary_registered = True
    import atexit

    def _emit() -> None:
        try:
            counts = refusal_counts()
            if not counts:
                return
            print("G2 KEY-LAYOUT GATE tally (%s armed): %s"
                  % (GATE_FLAG, ", ".join("%s=%d" % kv for kv in sorted(counts.items()))))
        except Exception:                                      # noqa: BLE001
            pass

    atexit.register(_emit)


def _count(*labels: str) -> None:
    _register_refusal_summary()
    with _refusal_lock:
        for label in labels:
            _refusals[label] += 1


def key_layout_verdict(text_key: str) -> tuple[bool, str, str]:
    """(accept, reason, layout) for one text key. PURE: no S3, no clock, no env.

    ACCEPT iff `pub_date_layout` parses a real date. That single predicate implements BOTH halves of
    the design's G2:

      * `layout == "unknown"` -- a key shape no rule recognises. `pub_date_layout`'s own docstring
        says this "should be read as *add a rule*, not as *this document has no date*", and today
        NOTHING enforces that: the key silently floors to Jan-1 of its year.
      * a NAMED refusal (`conab_survey_is_not_a_month`, `year_only`) -- the clause the draft was
        missing. A named refusal STILL FLOORS at evidence.py:318-324, so refusing only `unknown`
        would have let conab and mpob write documents that land on `year_floor` by construction.

    Keying on the LAYOUT rather than on a source list is deliberate: the day a conab survey-calendar
    rule lands, conab parses and re-enters the lane with no code change here."""
    d, layout = _pub_date(text_key)
    if d is not None:
        return True, REASON_OK, layout
    if layout == "unknown":
        return False, REASON_UNKNOWN_LAYOUT, layout
    return False, REASON_NAMED_REFUSAL, layout


def assert_key_layout(text_key: str) -> None:
    """Raise `KeyLayoutRefused` (counted) when `text_key` would floor. The only caller is
    `raw_to_text.writer.write_document`, and only when the flag is on."""
    ok, reason, layout = key_layout_verdict(text_key)
    if ok:
        _count("accepted")
        return
    _count("refused", "refused:" + reason, "refused_layout:" + layout)
    raise KeyLayoutRefused(text_key, reason, layout)


# ===================================================================================================
# G1 -- LEDGER-BOUNDED FETCH
# ===================================================================================================

REASON_NO_PUB_DATE = "no_publication_date_in_the_source_listing"
REASON_FUTURE_DATED = "publication_date_after_the_run_date"
REASON_NOT_NEWER = "not_newer_than_the_ledger"


def bound_listing(entries, *, newest_raw_pub, today: date) -> dict:
    """Apply the lane's two G1 rules to ONE source's own release listing.

    `entries` is an iterable of mappings carrying at least `id` and `pub_date`, where `pub_date` is a
    `datetime.date` READ FROM THE SOURCE'S OWN LISTING or report metadata -- or None when the source
    did not state one. `newest_raw_pub` is that source's ledger entry (None on a first fire).

    RULE 1, LEDGER-BOUNDED. Ask the source only for releases published AFTER `newest_raw_pub`, so a
    fire's cost is proportional to what actually published rather than to the archive's size. Every
    existing fetcher already carries the idempotency half (`s3_object_exists`, `--skip-existing-s3`
    on gain_backfill_task.py); the ledger is the cheap half that stops the LIST-and-compare.

    RULE 2, REFUSE AN UNDATED OBJECT. If the publication date cannot be read from the source's own
    listing, the object is NOT written to raw/. THERE IS NO `datetime.now()` FALLBACK ANYWHERE IN
    THIS LANE -- which is why `today` is a REQUIRED keyword with no default: this function cannot
    read a clock even by accident. A FUTURE-dated listing entry is refused on the same principle: a
    date after the run date is the wrong-early class the whole lane exists to make impossible (the
    D-EC P0c census measured `_pub_date` wrong-early on 28.9% of the corpus).

    Returns {accepted, refused, skipped, counts} -- every entry lands in exactly one bucket and the
    counts sum to the input length. Nothing is silent, and nothing is dropped without a reason."""
    accepted, refused, skipped = [], [], []
    for e in entries:
        ident = e.get("id")
        d = e.get("pub_date")
        if d is None or not isinstance(d, date):
            refused.append({"id": ident, "reason": REASON_NO_PUB_DATE})
            continue
        if d > today:
            refused.append({"id": ident, "reason": REASON_FUTURE_DATED, "pub_date": str(d)})
            continue
        if newest_raw_pub is not None and d <= newest_raw_pub:
            skipped.append({"id": ident, "reason": REASON_NOT_NEWER, "pub_date": str(d)})
            continue
        accepted.append({"id": ident, "pub_date": str(d)})
    return {"accepted": accepted, "refused": refused, "skipped": skipped,
            "counts": {"accepted": len(accepted), "refused": len(refused), "skipped": len(skipped),
                       "bound": None if newest_raw_pub is None else str(newest_raw_pub)}}


# ===================================================================================================
# THE CENSUS -- 3 free LISTs + 1 GET
# ===================================================================================================

def build_census(text_keys, chunk_names, alias_rows, raw_keys, *, today: date) -> dict:
    """The alias-aware per-source census. PURE -- every input is a plain collection, so the deck runs
    it on a fixture and the wrapper runs it on three LISTs and one GET.

    `text_keys`   every `text/source=*/.../document.json` key
    `chunk_names` the md5 object names under `<EVIDENCE_S3>/chunks/` (no `.jsonl` suffix)
    `alias_rows`  the parsed rows of `_index/doc_aliases.jsonl` ({source_key, canonical_key, layer})
    `raw_keys`    every `raw/production/source=*/...` key (for `newest_raw_pub`)

    COVERED = chunked OR path-twin-of-a-chunked-document OR carries an alias row into a chunked
    canonical. The UNION is the whole point (see the module header): the md5 join alone reads
    `usda_gain_soybeans` at 45.7% when the store itself has folded every one of its 69 stragglers."""
    text_keys = [k for k in text_keys if k.endswith(DOCUMENT_NAME)]
    chunked_set = set(chunk_names)
    alias_by_key = {r["source_key"]: r for r in alias_rows
                    if isinstance(r, dict) and r.get("source_key")}

    is_chunked = {k: doc_cache_name(k) in chunked_set for k in text_keys}
    # the STORE-PATH layer: fingerprints of documents that ARE in chunks/, across EVERY source
    chunked_fps = {path_fingerprint(k) for k, c in is_chunked.items() if c}

    def covered(k: str) -> tuple[bool, str]:
        if is_chunked[k]:
            return True, "chunked"
        if path_fingerprint(k) in chunked_fps:
            return True, "aliased_path_twin"
        row = alias_by_key.get(k)
        if row and is_chunked.get(row.get("canonical_key")) is True:
            return True, "aliased_index_row"
        # An alias row whose canonical is NOT in chunks/ is an UNBACKED promise -- DedupGate's own
        # liveness law counts that case rather than promising it (evidence_batch.py:685-700). We
        # score it as a GAP, the conservative direction.
        return False, "gap"

    # MEASURED 2026-09-07, and the design assumed otherwise: `pub_date_layout`'s seven rules were
    # written for TEXT keys, and FOUR sources' RAW keys carry no segment any of them can read --
    # `raw/production/source=sagis_cec/CEC_2026-08-26.pdf` (bare slug), `.../source=mpoc/
    # release_type=.../slug=.../x.html`, `.../source=fnc/bulk/Exportaciones-2026-2.xlsx` and
    # `.../source=icco_ewg_stocks/season=2020-21/...` (a season is not a date). So `newest_raw_pub`
    # and `fetch_lag_days` are UNAVAILABLE for those four, and `raw_date_derivable` says so per
    # source rather than letting a `None` read as "fresh". The fail-safe consequence for G1 is the
    # right one: with no ledger bound, `bound_listing` treats the source as a FIRST FIRE and skips
    # nothing.
    raw_seen: dict[str, int] = {}
    raw_newest: dict[str, date] = {}
    for rk in raw_keys:
        src = source_of(rk)
        raw_seen[src] = raw_seen.get(src, 0) + 1
        d, _lay = _pub_date(rk)
        if d and (src not in raw_newest or d > raw_newest[src]):
            raw_newest[src] = d

    per: dict[str, dict] = {}
    for k in text_keys:
        src = source_of(k)
        rec = per.setdefault(src, {"docs": 0, "chunked": 0, "aliased": 0, "gap": 0,
                                   "newest_pub": None, "newest_covered_pub": None,
                                   "layouts": collections.Counter(),
                                   "refusals": collections.Counter()})
        rec["docs"] += 1
        d, layout = _pub_date(k)
        rec["layouts"][layout] += 1
        if d is None:
            rec["refusals"][layout] += 1
        ok, how = covered(k)
        if how == "chunked":
            rec["chunked"] += 1
        elif ok:
            rec["aliased"] += 1
        else:
            rec["gap"] += 1
        if d is not None:
            if rec["newest_pub"] is None or d > rec["newest_pub"]:
                rec["newest_pub"] = d
            if ok and (rec["newest_covered_pub"] is None or d > rec["newest_covered_pub"]):
                rec["newest_covered_pub"] = d

    sources: dict[str, dict] = {}
    for src, rec in sorted(per.items()):
        docs = rec["docs"]
        cov_n = rec["chunked"] + rec["aliased"]
        newest_raw = raw_newest.get(src)
        layout = rec["layouts"].most_common(1)[0][0] if rec["layouts"] else "unknown"
        struck = src in STRUCK_SOURCES
        sources[src] = {
            "docs": docs,
            "chunked": rec["chunked"],
            "aliased": rec["aliased"],
            "gap": rec["gap"],
            "coverage_naive": round(rec["chunked"] / docs, 4) if docs else None,
            "coverage": round(cov_n / docs, 4) if docs else None,
            "newest_pub": str(rec["newest_pub"]) if rec["newest_pub"] else None,
            "newest_covered_pub": (str(rec["newest_covered_pub"])
                                   if rec["newest_covered_pub"] else None),
            "newest_raw_pub": str(newest_raw) if newest_raw else None,
            "n_raw_objects": raw_seen.get(src, 0),
            # True only when the source's RAW keys are dateable at all; False means "we listed raw
            # objects and NONE carried a readable date", which is a MISSING RULE, never a fresh read.
            "raw_date_derivable": bool(newest_raw) or raw_seen.get(src, 0) == 0,
            "chunk_lag_days": ((today - rec["newest_covered_pub"]).days
                               if rec["newest_covered_pub"] else None),
            "fetch_lag_days": (today - newest_raw).days if newest_raw else None,
            "layout": layout,
            "n_date_refusals": sum(rec["refusals"].values()),
            "date_refusals": dict(rec["refusals"]),
            # STRUCK sources have no derivable date at all, so they can carry no lag and cannot
            # breach; excluding them is what makes the lags FINITE instead of permanently None.
            "struck_from_write_path": struck,
            "struck_prerequisite": STRUCK_SOURCES[src][1] if struck else None,
        }

    totals = {
        "docs": sum(s["docs"] for s in sources.values()),
        "chunked": sum(s["chunked"] for s in sources.values()),
        "aliased": sum(s["aliased"] for s in sources.values()),
        "gap": sum(s["gap"] for s in sources.values()),
        "n_sources": len(sources),
        "n_date_refusals": sum(s["n_date_refusals"] for s in sources.values()),
        "n_alias_rows": len(alias_by_key),
        "n_chunk_objects": len(chunked_set),
        "sources_without_a_derivable_raw_date": sorted(
            s for s, r in sources.items() if not r["raw_date_derivable"]),
    }
    totals["coverage_naive"] = (round(totals["chunked"] / totals["docs"], 4)
                                if totals["docs"] else None)
    totals["coverage"] = (round((totals["chunked"] + totals["aliased"]) / totals["docs"], 4)
                          if totals["docs"] else None)
    return {"generated_for": str(today), "sources": sources, "totals": totals}


def scored_sources(census: dict) -> dict:
    """The sources a lag or a breach may be computed over: everything except the two STRUCK ones,
    whose named refusals mean they can never carry a derivable publication date."""
    return {s: r for s, r in census["sources"].items() if not r["struck_from_write_path"]}


def chunk_lag_days_max(census: dict):
    """today - newest publication date COVERED in chunks/, worst source. None when nothing scores."""
    vals = [r["chunk_lag_days"] for r in scored_sources(census).values()
            if r["chunk_lag_days"] is not None]
    return max(vals) if vals else None


def fetch_lag_days_max(census: dict):
    """today - newest publication date present in raw/, worst source. The 110-day GAIN stall is the
    number this exists to make visible."""
    vals = [r["fetch_lag_days"] for r in scored_sources(census).values()
            if r["fetch_lag_days"] is not None]
    return max(vals) if vals else None


def coverage_min(census: dict):
    vals = [r["coverage"] for r in scored_sources(census).values() if r["coverage"] is not None]
    return min(vals) if vals else None


def breaching_sources(census: dict, *, coverage_floor: float = COVERAGE_FLOOR,
                      chunk_lag_ceiling: float = CHUNK_LAG_CEILING_DAYS) -> list[str]:
    """Sources past the lane's declared contract. See the constants above: today this reads red for
    most of the estate BY CONSTRUCTION (the weekly fire is unarmed, the 686-document backlog is
    unbought, the GAIN fetch is gated on the owner's ruling), which is exactly why the ALARMS are a
    later sitting and not this one."""
    out = []
    for src, r in sorted(scored_sources(census).items()):
        cov, lag = r["coverage"], r["chunk_lag_days"]
        if ((cov is not None and cov < coverage_floor - 1e-9)
                or (lag is not None and lag > chunk_lag_ceiling)):
            out.append(src)
    return out


def served_lag_days(run_manifest: dict | None, *, today: date):
    """today - the newest publication date in the SERVED slices, read from the newest run manifest's
    per-slice `after_span.date_max` (write_guard.RunManifest.record_slice, write_guard.py:430-437).

    One LIST + one GET (write_guard.newest_run_manifest), no slice body. This is the SECOND of the
    design's two lags and it is the one the MONTHLY fold sets; conflating it with the chunk lag is
    what let the draft claim a single "recency" number that hid the fold. Returns None when no
    manifest carries a span -- which is itself a finding, never a zero."""
    if not isinstance(run_manifest, dict):
        return None
    best = None
    for _layer, slices in (run_manifest.get("slices") or {}).items():
        if not isinstance(slices, dict):
            continue
        for _name, rec in slices.items():
            span = (rec or {}).get("after_span") or {}
            dm = span.get("date_max")
            if not dm:
                continue
            try:
                d = date.fromisoformat(str(dm)[:10])
            except ValueError:
                continue
            if best is None or d > best:
                best = d
    return None if best is None else (today - best).days


def metric_payloads(census: dict, *, timestamp=None) -> list[dict]:
    """The FOUR family-rolled CloudWatch datums. At most four, exactly one dimension each, and that
    dimension's value is CONSTANT (`Family=graphrag_evidence`) -- so this emits FOUR metric streams
    forever, never 3 x 28. The deck pins that cardinality; see the header note on the $25.50/month
    per-source shape that was priced and rejected."""
    dim = [{"Name": "Family", "Value": FAMILY}]
    out = []
    for name, value, unit in (
        (METRIC_COVERAGE_MIN, coverage_min(census), "None"),
        (METRIC_CHUNK_LAG_MAX, chunk_lag_days_max(census), "Count"),
        (METRIC_FETCH_LAG_MAX, fetch_lag_days_max(census), "Count"),
        (METRIC_BREACH_COUNT, float(len(breaching_sources(census))), "Count"),
    ):
        if value is None:
            # A metric with no measurable value emits NO datapoint -- freshness.py's own empty-prefix
            # convention, where the alarm's treat_missing_data="breaching" owns the silence.
            continue
        datum = {"MetricName": name, "Dimensions": list(dim), "Value": float(value), "Unit": unit}
        if timestamp is not None:
            datum["Timestamp"] = timestamp
        out.append(datum)
    return out


def ledger_document(census: dict, *, generated_at: str, served_lag: int | None = None,
                    outstanding_batch_id: str | None = None,
                    fulltext_cap: int | None = None) -> dict:
    """The `coverage/ledger.json` body: the per-source record CloudWatch deliberately does not carry,
    plus the two lags, plus the outstanding batch id the NEXT weekly fire retrieves BEFORE it submits
    a new one (`_save_manifest`, evidence_batch.py:837-845, already persists that batch's block
    manifest to `<EVIDENCE_S3>/_batches/<bid>.json` precisely so a DIFFERENT Fargate job can
    retrieve it -- which is what makes the two-phase fire possible at all)."""
    return {
        "generated_at": generated_at,
        "fulltext_cap": fulltext_cap,
        "chunk_lag_days_max": chunk_lag_days_max(census),
        "fetch_lag_days_max": fetch_lag_days_max(census),
        "coverage_min": coverage_min(census),
        "served_lag_days": served_lag,          # ledger-only on purpose: no 5th metric (S 5)
        "breaching_sources": breaching_sources(census),
        "struck_from_write_path": {s: {"layout": lay, "prerequisite": why}
                                   for s, (lay, why) in sorted(STRUCK_SOURCES.items())},
        "outstanding_batch_id": outstanding_batch_id,
        "totals": census["totals"],
        "sources": census["sources"],
    }


# ===================================================================================================
# CAPS
# ===================================================================================================

def price_blocks(n_blocks: int) -> dict:
    """The tight estimate AND the fill estimator's band, together, always. The wrapper prints both so
    an operator never reads the 3.5x band as a fence."""
    lo, hi = FILL_BAND
    return {"n_blocks": n_blocks,
            "tight_usd": round(n_blocks * TIGHT_USD_PER_REQUEST, 4),
            "band_lo_usd": round(n_blocks * lo, 2),
            "band_hi_usd": round(n_blocks * hi, 2)}


def check_caps(*, n_docs: int, n_blocks: int, max_docs: int = MAX_DOCS_DEFAULT,
               max_usd: float = MAX_USD_DEFAULT) -> list[str]:
    """The refusal lines for a fire that wants more than its caps allow -- an EMPTY list means pass.

    THE CAPS BOUND HAIKU TOKENS ONLY. They do NOT bound the fire's dominant cost, which is Fargate
    wall-clock on a jobdef measured live with `timeout: None`; that is bounded separately and
    explicitly by `--poll-budget-seconds` (default 5400 = 90 min = $1.77 at the baked
    16 vCPU / 122,880 MB). Saying so here is the whole point: the earlier draft's caps were read as a
    ceiling on the fire and they never were."""
    p = price_blocks(n_blocks)
    lines = []
    if n_docs > max_docs:
        lines.append("REFUSED: %d NEW documents exceeds --max-docs %d. A fire that wants more is a "
                     "BACKFILL and takes an operator (design S 3)." % (n_docs, max_docs))
    if p["tight_usd"] > max_usd:
        lines.append(
            "REFUSED: %d blocks price at $%.2f (tight estimator $%.7f/request, "
            "evidence_batch.py:1907) which exceeds --max-usd %.2f. The FILL dry-run's own band for "
            "the same run reads ~$%.0f-%.0f (evidence_batch.py:1886-1887) -- printed beside the "
            "tight number, never instead of it."
            % (n_blocks, p["tight_usd"], TIGHT_USD_PER_REQUEST, max_usd,
               p["band_lo_usd"], p["band_hi_usd"]))
    return lines


# ===================================================================================================
# S3 READERS -- the only impure part, and it is LIST-only plus one GET
# ===================================================================================================

def _s3(region: str = "us-east-1"):
    import boto3
    return boto3.client("s3", region_name=region)


def _list_keys(s3, bucket: str, prefix: str, *, suffix: str = "") -> list[str]:
    out: list[str] = []
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        for o in page.get("Contents") or []:
            k = o["Key"]
            if not suffix or k.endswith(suffix):
                out.append(k)
    return out


def evidence_prefix(default: str | None = None) -> str:
    """`EVIDENCE_S3` or the default live prefix. The wrappers always pass it explicitly."""
    import os
    return (os.environ.get("EVIDENCE_S3") or default
            or "s3://%s/graphrag_evidence" % BUCKET).rstrip("/")


EVIDENCE_ENV_VAR = "EVIDENCE_S3"


def bind_evidence_prefix(explicit: str | None, *, env=None, require: bool = False,
                         echo=print) -> str:
    """Make `--evidence-s3` REAL by writing it into the ONE channel the evidence machinery reads.

    THE MEASURED DEFECT THIS CLOSES (fix pass, 2026-09-07). `evidence_batch` exposes NO
    `--evidence-s3` flag anywhere: `_cached_hashes` (evidence_batch.py:257-268),
    `store_path_index`, `DedupGate`'s content/alias indexes, `_build_requests_from_docs`,
    `submit_docs` (:1673), `retrieve`, `_save_manifest` (:837-845) and `evidence._evid_write`
    (evidence.py:60-64) ALL resolve `evidence._evid_s3()`, which is nothing but
    `os.environ.get("EVIDENCE_S3")` (evidence.py:42-43). So a wrapper that took the prefix as a CLI
    argument and never touched the environment produced two divergent stores in one process:

      * FLAG AT SHADOW, ENV AT LIVE -- measured: `corpus_fold_task`'s GUARD 1 validated the shadow
        prefix, printed `GUARD live-prefix: PASS`, planned a backup of the shadow's 199 objects, and
        then launched `evidence_batch --rebuild-slices` in a child that inherited the jobdef's baked
        `EVIDENCE_S3=s3://leviathan-dev-shahem-001/graphrag_evidence` and rewrote all 196 LIVE slice
        objects -- with the only backup taken of the wrong prefix. The submitter sets this variable
        as a container override (submit_batch_evidence_maintenance.py:228); a DESCRIPTOR fire never
        runs the submitter, so the descriptor path had no override at all.
      * FLAG SET, ENV UNSET -- measured: `_cached_hashes()` returns an EMPTY set, which kills the
        idempotency skip, the store_path layer and the alias index at once.
        `--stage chunk --all-gap --sources usda_gain_soybeans` read 127 candidates / 1,352 blocks /
        $6.21 with the variable unset against 69 candidates / 69 ALIASED / 0 blocks with it bound:
        the chunk-once law broken, and a source small enough to clear --max-docs 200 / --max-usd 5
        would have submitted a real batch re-chunking already-chunked documents.

    THE RULE. The explicit flag WINS and is bound into the environment for this process AND every
    child. A DISAGREEING ambient value is REBOUND LOUDLY rather than refused, and that is deliberate:
    the jobdef bakes the LIVE prefix, so refusing on disagreement would refuse every shadow rehearsal
    fired from a descriptor -- i.e. it would refuse R2, the only safe way to exercise the fold.
    What IS refused (`require=True`, used by the billed chunk leg and by the fold) is a prefix that
    is neither declared nor inherited: a silent fall-through to the hardcoded live default is exactly
    the empty-`_cached_hashes` case above.

    NOT COVERED: this binds a prefix, it does not validate that the prefix exists or is writable, and
    it says nothing about whether the prefix is the live store -- that is `assert_not_live_rebuild`'s
    job and it reads the JOBDEF, not this variable.
    """
    import os
    env = os.environ if env is None else env
    ambient = (env.get(EVIDENCE_ENV_VAR) or "").strip() or None
    declared = (explicit or "").strip() or None
    chosen = declared or ambient
    if chosen is None:
        if require:
            raise SystemExit(
                "REFUSED: no evidence prefix. Neither --evidence-s3 nor the %s environment variable "
                "is set, and this leg will not fall through to a hardcoded default. With %s unset "
                "`evidence_batch._cached_hashes()` (evidence_batch.py:257-268) returns an EMPTY set, "
                "so the idempotency skip, the store_path layer and the alias index are all dead -- "
                "measured on usda_gain_soybeans: 127 candidates / 1,352 blocks / $6.21 unset against "
                "69 candidates / 0 blocks bound, i.e. a re-chunk of documents already in chunks/. "
                "Pass --evidence-s3, or run where the jobdef bakes %s."
                % (EVIDENCE_ENV_VAR, EVIDENCE_ENV_VAR, EVIDENCE_ENV_VAR))
        chosen = evidence_prefix()
        echo("  NOTE %s was neither declared nor inherited; this READ-ONLY stage falls back to %s "
             "and binds it so every reader in this process agrees." % (EVIDENCE_ENV_VAR, chosen))
    chosen = chosen.rstrip("/")
    if declared and ambient and declared.rstrip("/") != ambient.rstrip("/"):
        echo("  %s REBOUND: %s -> %s. The flag wins and is exported to this process and every child; "
             "without this the guards read the flag while evidence_batch read the environment."
             % (EVIDENCE_ENV_VAR, ambient.rstrip("/"), chosen))
    env[EVIDENCE_ENV_VAR] = chosen
    return chosen


def _split_s3(uri: str) -> tuple[str, str]:
    rest = uri[len("s3://"):] if uri.startswith("s3://") else uri
    bkt, _, key = rest.partition("/")
    return bkt, key


def read_inputs(*, bucket: str = BUCKET, evidence_s3: str | None = None,
                region: str = "us-east-1") -> dict:
    """Free LISTs of `text/`, `<EVIDENCE_S3>/chunks/` and the raw prefixes of the TEXT-PRODUCING
    sources, plus ONE GET (`_index/doc_aliases.jsonl`). Measured runtime of exactly this join today:
    ~90 s, $0. No slice body, no document body, no Athena, no pg, and nothing is written.

    THE RAW LEG IS SCOPED, deliberately. `raw/production/` holds 52 `source=` prefixes -- the whole
    data lake, including every silver family (fgis, nass, esr, weather, cftc_cot ...) -- while only
    28 of them produce `text/`. Listing the lot to answer a corpus question would page through
    hundreds of thousands of objects for nothing, so the raw leg lists ONLY the sources the text
    layer actually names. A source that has raw objects and no text at all is therefore invisible
    here; that is the raw->text SEAM question, and `--stage text` answers it separately."""
    s3 = _s3(region)
    ev_uri = (evidence_s3 or evidence_prefix()).rstrip("/")
    ev_bkt, ev_key = _split_s3(ev_uri)
    text_keys = _list_keys(s3, bucket, TEXT_PREFIX, suffix=DOCUMENT_NAME)
    chunk_keys = _list_keys(s3, ev_bkt, "%s/%s" % (ev_key, CHUNKS_SUFFIX), suffix=".jsonl")
    chunk_names = [k.rsplit("/", 1)[-1][:-len(".jsonl")] for k in chunk_keys]
    raw_keys: list[str] = []
    for src in sorted({source_of(k) for k in text_keys} - {"unknown"}):
        raw_keys += _list_keys(s3, bucket, "%ssource=%s/" % (RAW_PREFIX, src))
    try:
        body = s3.get_object(Bucket=ev_bkt, Key="%s/%s" % (ev_key, ALIAS_INDEX_SUFFIX))["Body"].read()
        alias_rows = [json.loads(ln) for ln in body.decode("utf-8").splitlines() if ln.strip()]
    except Exception as exc:                                   # noqa: BLE001
        # An ABSENT alias index is legal (a fresh shadow prefix has none) and is NOT silent: the
        # census reports n_alias_rows = 0 and this line prints. It is never a zero that reads like a
        # measurement.
        alias_rows = []
        print("  NOTE: alias index unreadable at %s/%s (%s) -- alias rows scored as 0; path twins "
              "still count" % (ev_uri, ALIAS_INDEX_SUFFIX, type(exc).__name__))
    return {"text_keys": text_keys, "chunk_names": chunk_names,
            "alias_rows": alias_rows, "raw_keys": raw_keys, "evidence_s3": ev_uri}


def read_ledger(*, evidence_s3: str | None = None, region: str = "us-east-1") -> dict:
    """The lane's ledger, or {} when it does not exist yet -- and it does NOT exist today
    (`graphrag_evidence/coverage/` LIST-verified at 0 objects). An absent ledger is a first fire,
    never an error."""
    ev_uri = (evidence_s3 or evidence_prefix()).rstrip("/")
    bkt, key = _split_s3(ev_uri)
    try:
        body = _s3(region).get_object(Bucket=bkt, Key="%s/%s" % (key, LEDGER_SUFFIX))["Body"].read()
        return json.loads(body.decode("utf-8"))
    except Exception:                                          # noqa: BLE001
        return {}


def render_table(census: dict, *, limit: int | None = None) -> str:
    """The per-source table an operator reads, worst gap first. ASCII only (Windows console cp1252).
    This is the artifact the four family metrics deliberately do not carry."""
    rows = sorted(census["sources"].items(), key=lambda kv: (-kv[1]["gap"], kv[0]))
    if limit:
        rows = rows[:limit]
    head = ("%-28s%6s%7s%7s%6s%8s%13s%13s%13s%11s%11s  %s"
            % ("source", "docs", "chunk", "alias", "gap", "naive", "alias-aware",
               "newest_pub", "covered", "chunk_lag", "fetch_lag", "layout"))
    lines = [head, "-" * len(head)]
    for src, r in rows:
        nav = "-" if r["coverage_naive"] is None else "%.1f%%" % (r["coverage_naive"] * 100)
        aa = "-" if r["coverage"] is None else "%.1f%%" % (r["coverage"] * 100)
        lines.append("%-28s%6d%7d%7d%6d%8s%13s%13s%13s%11s%11s  %s%s"
                     % (src, r["docs"], r["chunked"], r["aliased"], r["gap"], nav, aa,
                        str(r["newest_pub"] or "-"), str(r["newest_covered_pub"] or "-"),
                        str(r["chunk_lag_days"] if r["chunk_lag_days"] is not None else "-"),
                        str(r["fetch_lag_days"] if r["fetch_lag_days"] is not None else "-"),
                        r["layout"], "   [STRUCK]" if r["struck_from_write_path"] else ""))
    t = census["totals"]
    lines.append("-" * len(head))
    lines.append("%-28s%6d%7d%7d%6d%7.1f%%%12.1f%%"
                 % ("TOTAL", t["docs"], t["chunked"], t["aliased"], t["gap"],
                    (t["coverage_naive"] or 0) * 100, (t["coverage"] or 0) * 100))
    return "\n".join(lines)
