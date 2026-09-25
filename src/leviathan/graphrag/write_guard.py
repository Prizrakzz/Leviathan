"""Write-path guards + the per-pass run manifest for the evidence layer (EVIDENCE_INTEGRITY_WAVE_PLAN G1).

The evidence layer has FIVE wholesale-write seams and, before this module, no run record at all. Revision 1
of the wave plan named three; the adversarial review of the landed code found two more (F2, F3), and both are
now guarded here rather than left as the two holes a reader would have mistaken for coverage:

    C1  a driver_slices.yaml term edit re-routes populations          (guarded by the G2 manifest lint)
    C2  write_driver_slices (evidence.py) overwrites every driver slice with no read, no delta, no empty guard
    C3  _write_doc_cache (evidence_batch.py) overwrites chunks/<md5>.jsonl wholesale -- and because
        rebuild_slices re-derives EVERY slice from the whole cache, overwriting ONE document silently re-rolls
        every driver slice that document feeds.
    C4  _route_and_write's `_raw/<node>` archive (evidence_batch.py) -- 24 objects / 79,974,491 B, written
        inside the node loop AHEAD of every other guard, and the derivation source `--reroute` reads. Its
        overwrite is structurally C3 one layer up: change one _raw object and every future reroute derives
        from new inputs. Now a guarded layer of its own ("_raw", subprefix "_raw/").
    C5  evidence.build_index's final `_evid_write(node, ...)` -- the LIVE cloud commodity write
        (jobs/batch/build_evidence_task.py -> jobdef leviathan-dev-evidence-build), writing the same 24
        top-level slices _commodity_guarded_write protects, and carrying its own order-nondeterministic
        `records[:max_props]` truncation. Now routed through this module with the G5a treatment.

C3 is what the 2026-07-19T22:00Z re-chunk was: 614 documents rewritten, 24,439 driver rows moved, 48 slice
span endpoints moved, net -633 props, and NOTHING on disk anywhere that recorded it happened. The attribution
was only possible at all because somebody had hand-copied drivers/ to _backup_pre_ndw_20260720/ the next day.

This module turns "undetectable by design" into "detectable by default":

    * prior population is resolved ONCE per pass (resolve_prior) from the cheapest sound source available;
    * every slice write is straddled by a before/after census diff (evaluate);
    * a population DROP past a named threshold REFUSES the pass before a single byte is written;
    * the refusal is atomic across ALL of a pass's layers, not just within one -- plan_write() evaluates and
      commit_write() writes, and a caller that plans every layer before committing any cannot land the
      2026-07-20 shape (commodity fine, drivers collapse, 11.1 GB already rewritten, "refused", exit 2);
    * every pass emits a RunManifest beside the other eval artifacts, so the next lane-2-style attribution
      takes minutes instead of a two-sided 2.7 GB stream.

WHAT THIS GUARD CANNOT SEE, stated so its absence is never mistaken for a green. G1b's first leg asks for the
ROW-LEVEL churn ratio (|lost| + |gained|), not the net -- because at the 2026-07-20 promote 5,809 of the
16,000 rows in the four capped slices were swapped for a different 5,809 with the counts frozen at exactly
4000 on both sides. No counts-based or bytes-based comparison can see that, and the only exact source is the
prior row set itself (101 GETs / 1.361 GB with a full json.loads of vector-bearing lines). So this module
evaluates the NET population line, records `layer_row_churn: null` with `layer_row_churn_reason` in every
manifest, and the swap class is closed by determinism (G5a) instead -- not by this guard. Do not read a clean
manifest as "no rows moved".

DECLARED CHURN -- THE PER-SLICE, DATED, REVIEWED WAY TO SAY "THIS DROP IS INTENDED" (2026-09-25). The
2026-09-23 fold (corpus-fold-h13c) refused before its first byte on ONE slice,
drivers/russia_export_tax_quota 583 -> 133 (77.2%), while every other slice moved 0.1-0.9%. The drop was
DECLARED in the routing config a month earlier -- driver_slices.yaml:859, the 2026-08-27 co_terms narrowing
(commit d9af78ce) -- and the guard judged the declared post-narrowing population against the stale
pre-narrowing slice. The only way out it offered was --allow-churn PCT, which is LAYER-WIDE: an 80% allowance
lets EVERY slice drop 80% silently, the exact class this module exists to refuse.
configs/graphrag/declared_churn.json is the structural route: one entry per slice carrying the reason (the
routing change and its commit), the PRE-CHANGE slice the declaration was measured against (prior_population:
the live object's population, plus the fold's census baseline when that baseline is older than the object),
the expected post-change POPULATION, optionally the post-change SPAN ENDPOINTS, and an expiry. The guard
admits exactly that slice, only on the pass that moves it FROM a pre-change reading TO a population that no
longer reads pre-change, and only at the declared population -- every comparison is the UNCHANGED
SLICE_DROP_REFUSE line, so there is no new threshold -- plus a span endpoint only as far inward as the declared
endpoint on that same pass, each as a WARN naming the declaration. Once the store has moved off the pre-change
readings the entry is SPENT, whatever the slice grows to afterwards, and the plain 10% line judges every later
drop. (The first cut tested "pending" as "the prior sits 10% above the declared population" -- a population
proxy that post-landing GROWTH re-armed: 160 -> 121 admitted, the 2026-09-25 verifier's MAJOR-1.) Every other
slice keeps the 10% line; an expired, not-yet-in-force or malformed declaration admits nothing; the empty guard
and the layer line never consult a declaration. See load_declared_churn, pre_change_reading, _declared_lands,
_declared_admits and _declared_span_admits.
"""
from __future__ import annotations

import json
import os
import sys
import time

# ── D-EI-7 trip lines ────────────────────────────────────────────────────────────────────────────────────
# These are FIRST TRIP LINES, not tuned optima. They are calibrated from the ONE measured event in evidence
# (the 2026-07-20 promote, full two-sided stream of all 101 driver slices) and are meant to be re-tuned from
# the first two manifests this module writes. Each carries its receipt.
#
# SLICE_DROP_REFUSE -- a per-slice population drop at or above this REFUSES the write; any drop below it
#   WARNS (a shrink is never silent). Receipt: 40 of 101 slices shrank at the promote; the largest single
#   loser, `metals`, went -263 props against a 975-prop survivor = -21%, and all five slices the backlog
#   named sit above this line. A slice losing a tenth of its props has no legitimate SILENT path -- the
#   legitimate paths are a per-slice DECLARATION in configs/graphrag/declared_churn.json (judged by this
#   same line re-based onto the declared population and onto the pre-change readings the declaration was
#   measured against), or, layer-wide, --allow-churn with a magnitude.
SLICE_DROP_REFUSE = 0.10
# LAYER_DROP_REFUSE -- the same line applied to the layer's total population. Stated honestly: this would
#   NOT have fired on 2026-07-20 (net -633 over 59,165 props = -1.07%); the per-slice line is what catches
#   that event. The layer line exists for the wholesale class (a config/route collapse taking the whole
#   layer down at once), which the per-slice line would report 101 times and never escalate.
LAYER_DROP_REFUSE = 0.10
# SPAN_CONTRACTION_REFUSES -- a per-slice date-span ENDPOINT that moves inward (start later, end earlier) is
#   a first-class trip, not an advisory. Receipt: 48 span endpoints moved at the promote; `fertilizer` lost
#   28 years of event_date start (1960-01-01 -> 1988-01-01), `potash` 25 years, `mississippi_river_levels`
#   3+ years of end -- while the backlog line recorded "none lost span". An endpoint moving OUTWARD (more
#   history, fresher end) is growth and only WARNS.
SPAN_CONTRACTION_REFUSES = True
# _RANGE_SAMPLE_BYTES -- how much of a prior slice object to read when estimating its prop count from its
#   size. One prop is one json line; reading the first complete line calibrates bytes-per-prop against the
#   ACTUAL store (real 1024-dim vectors in the cloud, tiny ones in a test fixture) instead of against a
#   hardcoded constant. Cost: one ranged GET per slice, ~64 KB each -- the plan priced only "one LIST, zero
#   GETs" (net-blind, needs a magic constant) against "101 full GETs / 1.361 GB"; this is the third option
#   and it is ~6.5 MB for the whole driver layer. The measured live constant, for the record, is
#   23,215-23,360 B/prop over 7 line-counted slices (spread < 0.7%) -- two orders below the 10% trip line,
#   which is why a size-derived count estimate cannot manufacture or mask a trip on its own.
_RANGE_SAMPLE_BYTES = 65536

# G1a -- the doc-cache vintage guard. A chunks/<md5>.jsonl object whose props carry a DIFFERENT chunk_version
# than the pass writing over it is a re-chunk, not a fill, and re-chunking re-rolls every driver slice that
# document feeds. Refuse it unless the caller says --rechunk.
DOC_CACHE_VINTAGE_REFUSES = True

# ── DECLARED CHURN (configs/graphrag/declared_churn.json) ────────────────────────────────────────────────
# WHERE THE FILE LIVES, AND WHY NOT eval/. The guard runs INSIDE the evidence-build container, so its
# declarations must ride the image. configs/graphrag/eval/ does not: .dockerignore names it "never needed
# inside an image", scripts/ops/make_worker_context_tar.OVERLAY_EXCLUDE_PREFIXES drops it from the gitignored
# overlay, and the context tar behind the live embedder image (commit 5d90d2c0, digest 5dbf1e1f) was measured
# on 2026-09-25 to hold ZERO configs/graphrag/eval/ members. A tracked file there would ride the kaniko route
# only by the accident of `git archive` not reading .dockerignore, and would vanish from a plain
# `docker build .`. So the file sits at the TOP of configs/graphrag/, beside priority_manifest.json -- which
# that same tar does carry -- and tests/unit/test_declared_churn.py pins the path against both exclusion
# lists. A declaration the guard cannot read admits nothing: every failure mode of this file FAILS CLOSED.
DECLARED_CHURN_FILE = "declared_churn.json"
DECLARED_CHURN_MANIFEST = "declared_churn"
DECLARED_CHURN_VERSION = 1
_DECL_TOP_KEYS = frozenset({"manifest", "version", "doctrine", "entries"})
# expected_population AND prior_population are REQUIRED: together they are how an entry sees its change LAND
# (a pre-change reading -> a population that no longer reads pre-change) and is SPENT from then on. A
# span-only entry has no such identity -- its slice's population need not move -- so it could never be seen
# to land and would re-admit every outward-then-inward endpoint move until expiry (MAJOR-1 through the span
# leg). The schema refuses one; see validate_declared_churn.
_DECL_REQUIRED = ("slice", "declared_on", "reason", "expires", "expected_population", "prior_population")
_DECL_OPTIONAL = frozenset({"evidence", "expected_span"})
# The PRE-CHANGE READINGS an entry records -- each a population the slice HELD BEFORE THE CHANGE, measured, with
# its receipt in the entry's `evidence`:
#   store            -- REQUIRED. The live object the rebuild overwrites: the write guard's prior (for the
#                       russia slice, 584 = the exact after_n of the 2026-08-21 rebuild manifest, whose
#                       after_bytes 13,632,657 == the live object).
#   census_baseline  -- the fold's census baseline, when that baseline predates the store's last write. The
#                       fold's step 3 diffs against it, not against the store: the frozen 2026-08-02
#                       eval/e1_census.json holds 363 for the russia slice. Without this reading the first fold
#                       passes step 2, REWRITES the store, and fails step 3 on the same slice.
# BOTH gates test their before-side against EVERY reading (pre_change_reading): one rule, so a declaration can
# never be honoured by one gate and refused by the other.
_DECL_PRIOR_READINGS = ("store", "census_baseline")


class WriteRefused(RuntimeError):
    """A wholesale write was refused by a G1 guard. Carries the per-slice refusal lines."""

    def __init__(self, lines: list[str]):
        self.lines = list(lines)
        super().__init__("; ".join(self.lines))


def _ascii(s) -> str:
    """cp1252-safe stdout: every guard line is printed on a Windows console (the ASCII-only print law)."""
    return str(s).encode("ascii", "backslashreplace").decode("ascii")


# ── span tuples ──────────────────────────────────────────────────────────────────────────────────────────
_SPAN_FIELDS = ("date_min", "date_max", "event_date_min", "event_date_max")


def span_tuple(recs: list[dict]) -> dict:
    """The {n, date min/max, event_date min/max} tuple G1b leg 2 trips on. ISO date strings compare
    lexically, so min()/max() need no parsing; None/blank values are skipped (an unset event_date is not a
    span endpoint). All five keys are always present -- an absent endpoint is an explicit None, never a
    missing key, so a diff never has to distinguish "no props" from "no field"."""
    def _ends(field: str):
        vals = sorted({str(r.get(field))[:10] for r in recs
                       if r.get(field) and str(r.get(field)).strip()})
        return (vals[0], vals[-1]) if vals else (None, None)

    d_lo, d_hi = _ends("date")
    e_lo, e_hi = _ends("event_date")
    return {"n": len(recs), "date_min": d_lo, "date_max": d_hi,
            "event_date_min": e_lo, "event_date_max": e_hi}


def _span_moves(before: dict | None, after: dict) -> tuple[list[str], list[str]]:
    """(contractions, expansions) between two span tuples, as human lines. A start moving LATER or an end
    moving EARLIER is a contraction (history was lost); the reverse is growth."""
    if not before:
        return [], []
    contracted, expanded = [], []
    for field in _SPAN_FIELDS:
        b, a = before.get(field), after.get(field)
        if b is None or a is None or b == a:
            continue
        inward = (a > b) if field.endswith("_min") else (a < b)
        (contracted if inward else expanded).append(f"{field} {b} -> {a}")
    return contracted, expanded


# ── prior-population resolution ──────────────────────────────────────────────────────────────────────────
def _s3_client():
    import boto3
    return boto3.client("s3")


def list_slice_bytes(subprefix: str) -> dict:
    """{slice_name: bytes} for the objects one level under <EVIDENCE_S3>/<subprefix> (or the local store).

    ONE list_objects_v2 in S3 mode -- never a per-key HEAD (the July LIST-storm discipline); the exact idiom
    e1_census._slice_names_on_disk already uses, plus `Delimiter="/"`. The delimiter matters for the
    commodity layer: its `subprefix` is "" (the 24 slices are top-level `*.jsonl` under the evidence root),
    and an undelimited LIST there enumerates all 6,346 objects under graphrag_evidence/ -- including the
    2,940-object shadow_ndw/ and the 2,815-object chunks/ -- to find 24 keys. With the delimiter S3 rolls
    every subdirectory into CommonPrefixes and returns one page. Nested keys are excluded either way.
    Missing store -> {} (a first-ever write has no prior, which is not a drop)."""
    from leviathan.graphrag import evidence as ev
    base = ev._evid_s3()
    sub = subprefix.strip("/")
    if base:
        bkt, prefix = ev._parse_s3(base.rstrip("/") + "/" + (sub + "/" if sub else ""))
        out: dict[str, int] = {}
        for page in _s3_client().get_paginator("list_objects_v2").paginate(Bucket=bkt, Prefix=prefix,
                                                                          Delimiter="/"):
            for o in page.get("Contents") or []:
                rel = o["Key"][len(prefix):]
                if rel.endswith(".jsonl") and "/" not in rel:
                    out[rel[:-6]] = int(o["Size"])
        return out
    d = ev._EVID_DIR / sub if sub else ev._EVID_DIR
    if not d.exists():
        return {}
    return {p.stem: p.stat().st_size for p in d.glob("*.jsonl")}


def _first_line_bytes(node: str) -> int | None:
    """Byte length (incl. the newline) of the FIRST json line of a stored slice -- one ranged GET in S3 mode,
    a bounded local read otherwise. This is bytes-per-prop calibrated against the actual store. None when the
    object is absent/empty or holds no complete line inside the sampled window."""
    from leviathan.graphrag import evidence as ev
    base = ev._evid_s3()
    try:
        if base:
            bkt, key = ev._parse_s3(base.rstrip("/") + f"/{node}.jsonl")
            body = _s3_client().get_object(Bucket=bkt, Key=key,
                                           Range=f"bytes=0-{_RANGE_SAMPLE_BYTES - 1}")["Body"].read()
            head = body.decode("utf-8", "ignore")
        else:
            p = ev._EVID_DIR / f"{node}.jsonl"
            if not p.exists():
                return None
            with open(p, "rb") as fh:
                head = fh.read(_RANGE_SAMPLE_BYTES).decode("utf-8", "ignore")
    except Exception:                                          # noqa: BLE001 -- absent/unreadable prior
        return None
    nl = head.find("\n")
    if nl < 0:                                                 # one single line (or a line longer than the window)
        return len(head.encode("utf-8")) or None
    return len(head[:nl].encode("utf-8")) + 1


def _manifest_stamp(key: str) -> str:
    """The UTC stamp out of a `write_manifest_{label}_{stamp}.json` key -- the ONLY chronological field in
    the name.

    F7: the previous selector was `sorted(...)[-1]` / `max(keys)`, whose comment asserted "zero-padded UTC
    stamp: lexical == chronological". It is not: the LABEL sorts first. Over
    `retrieve_...T120000Z`, `rebuild_...T130000Z`, `run_20260701T010000Z` both selectors returned the
    `run_...` one -- six months stale -- so any `--retrieve` followed by a `--rebuild` baselined the next
    pass off the retrieve. The after_bytes fence at resolve_prior:1 then degrades that to "silently lose the
    exact baseline and the span guard", which is F4 re-opened forever. Sort on the stamp instead. A name
    with no parseable stamp sorts last-resort-first (empty string), never ahead of a real one."""
    name = key.rsplit("/", 1)[-1]
    if name.endswith(".json"):
        name = name[:-len(".json")]
    stamp = name.rsplit("_", 1)[-1]
    return stamp if stamp.endswith("Z") else ""


def newest_run_manifest() -> tuple[dict | None, str]:
    """The newest write_manifest_*.json under <EVIDENCE_S3>/eval/ (one LIST + one GET) or the local eval dir.

    "Newest" is by the UTC STAMP in the filename (_manifest_stamp), never by the whole name -- see F7 there.

    This is the ONLY source of an EXACT prior population and of prior span endpoints, and it exists only
    because a previous guarded pass wrote it -- or because `--seed-manifest` bootstrapped one read-only over
    the existing store (seed_manifest below; without it the span leg is silent on the FIRST guarded pass,
    which is exactly the Wave-R rebuild the whole wave is built around). Returns (manifest_dict | None,
    label)."""
    from leviathan.graphrag import evidence as ev
    from leviathan.graphrag import extract as ex
    local = ex._CFG / "eval"
    if local.exists():
        cands = sorted(local.glob("write_manifest_*.json"), key=lambda p: (_manifest_stamp(p.name), p.name))
        if cands:
            try:
                return json.loads(cands[-1].read_text(encoding="utf-8")), str(cands[-1])
            except Exception:                                  # noqa: BLE001 -- a corrupt manifest is no baseline
                pass
    base = ev._evid_s3()
    if not base:
        return None, "no prior run manifest (local eval/ empty, no EVIDENCE_S3)"
    bkt, prefix = ev._parse_s3(base.rstrip("/") + "/eval/")
    keys: list[str] = []
    try:
        for page in _s3_client().get_paginator("list_objects_v2").paginate(Bucket=bkt, Prefix=prefix):
            for o in page.get("Contents") or []:
                rel = o["Key"][len(prefix):]
                if rel.startswith("write_manifest_") and rel.endswith(".json") and "/" not in rel:
                    keys.append(o["Key"])
        if not keys:
            return None, f"no prior run manifest under s3://{bkt}/{prefix}"
        newest = max(keys, key=lambda k: (_manifest_stamp(k), k))
        doc = json.loads(_s3_client().get_object(Bucket=bkt, Key=newest)["Body"].read().decode("utf-8"))
        return doc, f"s3://{bkt}/{newest}"
    except Exception as exc:                                   # noqa: BLE001
        return None, f"prior run manifest unreadable ({_ascii(exc)})"


def resolve_prior(subprefix: str, names, *, layer: str | None = None) -> dict:
    """Prior population per slice, from the cheapest sound source, with the source RECORDED per slice.

    Resolution order, per slice:
      1. the newest run manifest's recorded after_n / after_span, IF its recorded after_bytes still equals
         what the store holds today. The equality test is the stale-mirror fence: a manifest that a later
         UNGUARDED write invalidated must not be trusted as a baseline (the pattern-records lesson -- a
         mirror nobody re-loaded made a guard fail open on every run since it landed).
      2. otherwise the LIST byte size divided by this slice's own first-line byte length -> an ESTIMATED
         count, no spans.
      3. a slice with no object at all -> n = 0, bytes = 0, "absent" (a first write is never a drop).

    Returns {name: {bytes, n, exact: bool, span: dict|None, source: str}} over the union of `names` and every
    slice already in the store, so a slice the pass DOESN'T write is still censused (that is how the plan's
    "a slice whose terms are deleted is never rewritten and its stale file persists" case becomes visible)."""
    sizes = list_slice_bytes(subprefix)
    manifest, mlabel = newest_run_manifest()
    prior_slices = ((manifest or {}).get("slices") or {}) if isinstance(manifest, dict) else {}
    key = layer or (subprefix.strip("/") or "_top")
    prior_sub = prior_slices.get(key, {}) if isinstance(prior_slices, dict) else {}
    out: dict[str, dict] = {}
    for name in sorted(set(names) | set(sizes)):
        nbytes = int(sizes.get(name, 0))
        if nbytes <= 0:
            out[name] = {"bytes": 0, "n": 0, "exact": True, "span": None, "source": "absent"}
            continue
        rec = prior_sub.get(name) if isinstance(prior_sub, dict) else None
        if isinstance(rec, dict) and rec.get("after_bytes") == nbytes and rec.get("after_n") is not None:
            out[name] = {"bytes": nbytes, "n": int(rec["after_n"]), "exact": True,
                         "span": rec.get("after_span"), "source": f"run manifest ({mlabel})"}
            continue
        node = f"{subprefix.strip('/')}/{name}" if subprefix.strip("/") else name
        bpp = _first_line_bytes(node)
        if not bpp:
            out[name] = {"bytes": nbytes, "n": None, "exact": False, "span": None,
                         "source": "bytes only (no readable first line)"}
            continue
        stale = " -- prior manifest STALE (bytes moved since)" if isinstance(rec, dict) else ""
        out[name] = {"bytes": nbytes, "n": max(1, round(nbytes / bpp)), "exact": False, "span": None,
                     "source": f"size/first-line estimate ({bpp} B/prop){stale}"}
    return out


# ── declared churn: the loader, the schema, the admission rule ───────────────────────────────────────────
def declared_churn_path():
    """<configs/graphrag>/declared_churn.json, resolved through extract._CFG at CALL time: a hermetic test that
    points _CFG at a tmp dir sees no declarations, and the container reads /app/configs/graphrag/ (the image
    runs `pip install -e`, so the package -- and therefore _CFG -- is the image's own /app tree)."""
    from leviathan.graphrag import extract as ex
    return ex._CFG / DECLARED_CHURN_FILE


def _iso_date(value):
    """A strict YYYY-MM-DD date, or None. No datetimes, no partial dates: an expiry is a calendar day."""
    from datetime import date
    if not isinstance(value, str) or len(value) != 10:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def validate_declared_churn(doc) -> list[str]:
    """Schema errors for a declared-churn document; [] means valid. STRICT on purpose -- an unknown key is an
    error, not a comment -- because this file is the ONLY thing that lets a refusable drop through, and a
    misspelt `expected_populaton` must not silently mean "no bound".

    WHAT AN ENTRY STATES -- every quantity ABSOLUTE and MEASURED:
      `prior_population` ({store: int >= 1, census_baseline?: int >= 1}) -- REQUIRED. The PRE-CHANGE slice
        the declaration was measured against (see _DECL_PRIOR_READINGS). Every reading must sit at least
        SLICE_DROP_REFUSE above expected_population: a reading within the line of the declared population
        could never be told apart from the post-change store, so its entry could never be seen to land;
      `expected_population` (an int >= 1) -- REQUIRED. The post-change population: the population leg (see
        _declared_admits), and the other half of how an entry sees its change land (_declared_lands);
      `expected_span` (optional; {date_min|date_max|event_date_min|event_date_max: YYYY-MM-DD}) -- the
        post-change span endpoints, the span leg (see _declared_span_admits). An endpoint that is not declared
        is not admitted.
    `expected_drop_pct` is REFUSED by name, and the reason is structural, not taste: a relative declaration is
    re-applied to EVERY future prior until the entry expires, so once the declared change has landed it would
    admit the SAME drop again from the new, smaller population -- the --allow-churn defect scoped down to one
    slice. The same defect reached the first cut a second way (the 2026-09-25 verifier's MAJOR-1): "pending"
    was read off the declared population alone, so post-landing GROWTH re-armed it. An entry is now bound to
    the pre-change store it names and is spent once the store has moved off it."""
    if not isinstance(doc, dict):
        return ["the document is not a JSON object"]
    errs: list[str] = []
    extra = sorted(set(doc) - _DECL_TOP_KEYS)
    if extra:
        errs.append(f"unknown top-level key(s) {extra}; allowed: {sorted(_DECL_TOP_KEYS)}")
    if doc.get("manifest") != DECLARED_CHURN_MANIFEST:
        errs.append(f"'manifest' must be {DECLARED_CHURN_MANIFEST!r}, got {doc.get('manifest')!r}")
    if doc.get("version") != DECLARED_CHURN_VERSION:
        errs.append(f"'version' must be {DECLARED_CHURN_VERSION}, got {doc.get('version')!r}")
    entries = doc.get("entries")
    if not isinstance(entries, list):
        return errs + ["'entries' must be a list"]
    seen: set[str] = set()
    for i, e in enumerate(entries):
        where = f"entries[{i}]"
        if not isinstance(e, dict):
            errs.append(f"{where}: not an object")
            continue
        if "expected_drop_pct" in e:
            errs.append(f"{where}: expected_drop_pct is refused -- a RELATIVE declaration re-applies to every "
                        f"future prior until expiry, so after the declared change lands it admits the same drop "
                        f"AGAIN. Declare the absolute expected_population.")
        unknown = sorted(set(e) - set(_DECL_REQUIRED) - _DECL_OPTIONAL - {"expected_drop_pct"})
        if unknown:
            errs.append(f"{where}: unknown key(s) {unknown}")
        missing = [k for k in _DECL_REQUIRED if k not in e]
        if missing:
            errs.append(f"{where}: missing required key(s) {missing}")
        if "expected_population" not in e and "expected_span" in e:
            errs.append(f"{where}: a span-only declaration is refused -- expected_population is required, "
                        f"because the population move (a prior_population reading -> the declared population) "
                        f"is how an entry sees its change land and goes spent; a span-only entry would re-admit "
                        f"every outward-then-inward endpoint move until it expires")
        sl = e.get("slice")
        if isinstance(sl, str) and sl.count("/") == 1 and all(sl.split("/")):
            layer = sl.split("/")[0]
            if layer not in SEED_LAYERS:
                errs.append(f"{where}: slice {sl!r} names layer {layer!r}; known layers: {sorted(SEED_LAYERS)}")
            if sl in seen:
                errs.append(f"{where}: slice {sl!r} is declared twice")
            seen.add(sl)
        elif "slice" in e:
            errs.append(f"{where}: slice must be '<layer>/<name>' (e.g. 'drivers/russia_export_tax_quota'), "
                        f"got {sl!r}")
        d_on, d_exp = _iso_date(e.get("declared_on")), _iso_date(e.get("expires"))
        if "declared_on" in e and d_on is None:
            errs.append(f"{where}: declared_on must be a YYYY-MM-DD date, got {e.get('declared_on')!r}")
        if "expires" in e and d_exp is None:
            errs.append(f"{where}: expires must be a YYYY-MM-DD date, got {e.get('expires')!r}")
        if d_on and d_exp and d_exp < d_on:
            errs.append(f"{where}: expires {d_exp} is before declared_on {d_on}")
        if "reason" in e and not (isinstance(e["reason"], str) and e["reason"].strip()):
            errs.append(f"{where}: reason must be a non-empty string naming the routing change")
        pop = e.get("expected_population")
        pop_ok = isinstance(pop, int) and not isinstance(pop, bool) and pop >= 1
        if "expected_population" in e and not pop_ok:
            errs.append(f"{where}: expected_population must be an int >= 1 (a declared EMPTY slice is never "
                        f"admitted -- the empty guard is unconditional), got {pop!r}")
        prior = e.get("prior_population")
        if "prior_population" in e:
            if not (isinstance(prior, dict) and "store" in prior and set(prior) <= set(_DECL_PRIOR_READINGS)):
                errs.append(f"{where}: prior_population must be an object over {list(_DECL_PRIOR_READINGS)} "
                            f"holding at least 'store' (the live object's pre-change population), got {prior!r}")
            else:
                for label in _DECL_PRIOR_READINGS:
                    if label not in prior:
                        continue
                    r = prior[label]
                    if not (isinstance(r, int) and not isinstance(r, bool) and r >= 1):
                        errs.append(f"{where}: prior_population {label} must be an int >= 1, got {r!r}")
                    elif pop_ok and (r - pop) / r < SLICE_DROP_REFUSE:
                        errs.append(f"{where}: prior_population {label} {r} is not at least "
                                    f"{SLICE_DROP_REFUSE * 100:.0f}% above expected_population {pop} -- the "
                                    f"declared change is no refusable drop from that reading, and a store at the "
                                    f"declared population would still read as pre-change, so the entry could "
                                    f"never be seen to land")
        span = e.get("expected_span")
        if "expected_span" in e:
            if not (isinstance(span, dict) and span and set(span) <= set(_SPAN_FIELDS)):
                errs.append(f"{where}: expected_span must be a non-empty object over {list(_SPAN_FIELDS)}, "
                            f"got {span!r}")
            else:
                bad = sorted(k for k, v in span.items() if _iso_date(v) is None)
                if bad:
                    errs.append(f"{where}: expected_span {bad} must be YYYY-MM-DD dates")
                for lo, hi in (("date_min", "date_max"), ("event_date_min", "event_date_max")):
                    if (lo in span and hi in span and not bad and span[lo] > span[hi]):
                        errs.append(f"{where}: expected_span {lo} {span[lo]} is after {hi} {span[hi]}")
        evid = e.get("evidence")
        if "evidence" in e and not (isinstance(evid, dict) and all(
                isinstance(k, str) and isinstance(v, (str, int, float)) and not isinstance(v, bool)
                for k, v in evid.items())):
            errs.append(f"{where}: evidence must be an object of string keys to string/number values")
    return errs


class DeclaredChurn:
    """The declarations in force for ONE pass, exactly as the guard read them.

    `state` is "absent" (no file -- the normal state), "valid", or "invalid" (unreadable or schema-failing:
    EVERY entry is ignored, fail closed). `active` maps '<layer>/<slice>' to the entry in force today;
    `inactive` maps an entry that exists but is NOT in force (expired, or not yet declared) to the reason, so a
    refusal on that slice can say why the declaration did not apply instead of reading as undeclared."""

    __slots__ = ("path", "sha256", "state", "errors", "today", "active", "inactive")

    def __init__(self, *, path: str, state: str = "absent", sha256: str | None = None, errors=(),
                 today: str | None = None, active: dict | None = None, inactive: dict | None = None):
        self.path, self.state, self.sha256 = path, state, sha256
        self.errors, self.today = list(errors), today
        self.active, self.inactive = dict(active or {}), dict(inactive or {})

    def entry_for(self, key: str) -> dict | None:
        return self.active.get(key)

    def record(self) -> dict:
        """What the run manifest carries: enough to re-read the exact declarations a pass was judged by."""
        return {"path": self.path, "state": self.state, "sha256": self.sha256, "today": self.today,
                "errors": [_ascii(x) for x in self.errors], "active": sorted(self.active),
                "inactive": {k: _ascii(v) for k, v in sorted(self.inactive.items())}}


def load_declared_churn(path=None, *, today=None) -> DeclaredChurn:
    """Read configs/graphrag/declared_churn.json (or `path`) and split its entries into in-force / not.

    An entry is IN FORCE on declared_on <= today <= expires (UTC calendar days, `expires` inclusive: it is the
    last day the entry counts). Past its expiry it is ignored and the refusal it would have admitted STANDS.
    Never raises: an absent file is no declarations; an unreadable or schema-failing file is state "invalid"
    with its errors recorded and NOTHING in force."""
    import hashlib
    from datetime import datetime, timezone
    from pathlib import Path
    p = Path(path) if path is not None else declared_churn_path()
    day = today or datetime.now(timezone.utc).date()
    stamp = day.isoformat()
    try:
        if not p.exists():
            return DeclaredChurn(path=str(p), state="absent", today=stamp)
        raw = p.read_bytes()
        doc = json.loads(raw.decode("utf-8"))
    except Exception as exc:                                   # noqa: BLE001 -- unreadable = no declarations
        return DeclaredChurn(path=str(p), state="invalid", errors=[f"unreadable: {_ascii(exc)}"], today=stamp)
    sha = hashlib.sha256(raw).hexdigest()
    errs = validate_declared_churn(doc)
    if errs:
        return DeclaredChurn(path=str(p), state="invalid", sha256=sha, errors=errs, today=stamp)
    active: dict[str, dict] = {}
    inactive: dict[str, str] = {}
    for e in doc["entries"]:
        d_on, d_exp = _iso_date(e["declared_on"]), _iso_date(e["expires"])
        if day > d_exp:
            inactive[e["slice"]] = f"EXPIRED on {e['expires']} (today {stamp}) and was ignored"
        elif day < d_on:
            inactive[e["slice"]] = f"NOT YET IN FORCE (declared_on {e['declared_on']}, today {stamp})"
        else:
            active[e["slice"]] = dict(e)
    return DeclaredChurn(path=str(p), state="valid", sha256=sha, today=stamp, active=active, inactive=inactive)


def pre_change_reading(entry: dict | None, n) -> tuple[str, int] | None:
    """The pre-change reading `n` still reads as -- (label, population) -- or None when it reads as none.

    "Reads as" is the guard's OWN line: |n - r| / r < SLICE_DROP_REFUSE, the comparison the unchanged guard
    would make between that reading and n. A population that matches a reading is a slice the declared change
    has NOT reached; one that matches none has moved off the pre-change store -- by the declared change or by
    anything else -- and the entry has nothing left to say about it.

    THIS is what binds an entry to the store it was MEASURED against rather than to its declared population
    (the verifier's MAJOR-1). The russia entry's readings are store 584 and census_baseline 363; a slice that
    lands at 133 and then grows to 160 is 72.6% off the one and 55.9% off the other, so 160 -> 121 is a NEW
    drop the plain line refuses (the first cut read 160 as "still pending" because 160 >= 133 / 0.9 = 148).
    The residual, stated rather than implied: to read pending again a landed slice must RE-GROW into a
    pre-change window (here 327-399 or 526-642 props) -- regrow the very population the change removed --
    before the entry expires, and the expiry is the backstop."""
    if not entry or n is None:
        return None
    readings = entry.get("prior_population")
    if not isinstance(readings, dict):
        return None
    for label in _DECL_PRIOR_READINGS:
        r = readings.get(label)
        if isinstance(r, int) and not isinstance(r, bool) and r >= 1 and abs(n - r) / r < SLICE_DROP_REFUSE:
            return label, r
    return None


def _declared_lands(entry: dict | None, bn, an) -> bool:
    """THE PASS LANDS THE DECLARED CHANGE: its before-side still reads as a pre-change reading AND its
    after-side reads as none of them. BOTH legs gate on this, so an entry admits only on a pass that moves the
    slice OFF the pre-change store, and it is SPENT on the pass after -- by construction, not by hope: an
    admitted after-side matches no pre-change reading, so the next pass's before-side (that population, plus
    whatever it grew) starts outside every window. A pass whose after-side still reads pre-change (583 -> 380
    against the census reading 363, say) is not the declared change and is refused, so no landing can leave the
    entry armed."""
    return (bool(entry) and an is not None and pre_change_reading(entry, bn) is not None
            and pre_change_reading(entry, an) is None)


def _declared_admits(entry: dict | None, bn, an) -> bool:
    """THE POPULATION ADMISSION RULE -- two conditions, and every tolerance is the guard's OWN line.

    (a) THE PASS LANDS THE DECLARED CHANGE (_declared_lands): the prior still reads as the pre-change slice the
        declaration was measured against (prior_population), and the new population no longer does. The
        2026-09-23 fold's 583 -> 133: 583 reads as the store's 584 (0.2% off), 133 reads as neither 584 nor
        363. After that pass the store holds ~133, which reads as no pre-change reading, so the entry is SPENT:
        140 -> 125, and equally 160 -> 121 or 300 -> 120 after post-landing growth, are NEW drops the plain
        10% line judges. (The first cut's "(bn - P) / bn >= SLICE_DROP_REFUSE" re-armed on any growth past
        P / 0.9 = 148 -- the verifier's MAJOR-1.)
    (b) THE NEW POPULATION IS THE DECLARED ONE: it sits within SLICE_DROP_REFUSE of the DECLARED population,
        (P - an) / P < SLICE_DROP_REFUSE -- exactly the comparison the unchanged guard makes against a prior,
        re-based onto the declaration. For P = 133 that admits 120 and refuses 119. Above P is admitted: it is
        less loss than was declared (a corpus that grows between declaration and fold lands there) -- as long
        as it no longer reads pre-change, per (a)."""
    if not entry or not bn or "expected_population" not in entry:
        return False
    pop = int(entry["expected_population"])
    return _declared_lands(entry, bn, an) and (pop - an) / pop < SLICE_DROP_REFUSE


def admitted_declaration(declared: "DeclaredChurn | None", key: str, before, after) -> dict | None:
    """The in-force entry that admits a `before -> after` POPULATION drop on `key` ('<layer>/<slice>'), else
    None. The ONE rule both gates apply -- evaluate() here and e1_census.diff_census's population_drops leg --
    so a declaration can never be honoured by one gate and refused by the other. Measured, not hypothetical:
    replayed offline, the 2026-09-23 fold with the declaration read by the write guard ONLY passes step 2 and
    then fails its own census gate on the same slice (2026-08-02 baseline 363 -> 133), AFTER the rebuild has
    rewritten the store -- and because the chain never rolls its baseline on red, every later fold fails too.
    The two gates' before-sides are DIFFERENT readings of the same pre-change slice (the write guard reads the
    live object, 583-584; the census reads its frozen 2026-08-02 baseline, 363), which is why the entry records
    both and pre_change_reading tests every before-side against every reading."""
    entry = declared.entry_for(key) if declared is not None else None
    return entry if _declared_admits(entry, before, after) else None


def _declared_span_admits(entry: dict | None, field: str, new_value) -> bool:
    """THE SPAN ADMISSION RULE: a contracted endpoint is admitted only when the entry declares THAT endpoint
    and the new value has not moved PAST it (a *_min no later than the declared date, a *_max no earlier) --
    AND, checked by evaluate on the same pass, when the pass LANDS the declared change (_declared_lands, the
    population leg's own test).

    That gate is what retires the span leg. The first cut relied on "a contraction to the declared endpoint
    implies the prior lay outside it", which post-landing growth broke: a store that gained a 2026-11-15 prop
    after landing and then lost it again fell back to the declared 2025-03-19 and was ADMITTED (the verifier's
    P5). Once the store has moved off the pre-change readings every inward move is judged by the plain span
    line. The tolerance is zero days on purpose: routing is deterministic (G5a) and new documents can only
    move an endpoint OUTWARD, so the measured post-change endpoint is the declaration, not an estimate of
    it."""
    declared = ((entry or {}).get("expected_span") or {}).get(field)
    if declared is None or new_value is None:
        return False
    return new_value <= declared if field.endswith("_min") else new_value >= declared


def _declared_note(entry: dict, bn, an) -> str:
    pop = int(entry["expected_population"])
    label, r = pre_change_reading(entry, bn) or ("-", "-")
    return (f" -- ADMITTED by declared churn [{DECLARED_CHURN_FILE}: declared_on {entry['declared_on']}, "
            f"expires {entry['expires']}]: the prior reads as the pre-change {label} {r} and the pass lands the "
            f"declared change -- expected population {pop}, and {an} is within the "
            f"{SLICE_DROP_REFUSE * 100:.0f}% refuse line of it. Reason: {entry['reason'][:240]}")


def _declared_off_store(entry: dict, bn, an) -> str:
    """Why an in-force entry did not see THIS pass land its change -- the two ways _declared_lands fails."""
    readings = ", ".join(f"{k} {v}" for k, v in sorted((entry.get("prior_population") or {}).items()))
    if pre_change_reading(entry, bn) is None:
        return (f" -- the declaration for this slice is SPENT: the prior {bn} no longer reads as the pre-change "
                f"slice it was measured against ({readings}; each within the {SLICE_DROP_REFUSE * 100:.0f}% "
                f"line), so the declared change has landed and this move is NEW and undeclared")
    hit = pre_change_reading(entry, an)
    if hit is None:
        return " -- the declaration for this slice cannot judge a pass with no after-side population"
    return (f" -- the new population {an} still reads as the pre-change {hit[0]} {hit[1]}: this pass does NOT "
            f"land the declared change (expected population {entry.get('expected_population')}), so the move "
            f"is undeclared")


def _declared_miss(declared: "DeclaredChurn | None", key: str, entry: dict | None, bn, an) -> str:
    """Why a declaration did NOT admit this refused slice -- so a refusal on a declared slice never reads as
    an undeclared one, and an invalid file is named at the refusal it failed to prevent."""
    if declared is None:
        return ""
    if entry is None:
        if key in declared.inactive:
            return f" -- a declaration for this slice is {declared.inactive[key]}"
        if declared.state == "invalid":
            return (f" -- the declared-churn manifest {declared.path} is INVALID, so no declaration was read "
                    f"(fail closed)")
        return ""
    if "expected_population" not in entry:
        return " -- the declaration for this slice declares no expected_population (the schema refuses that)"
    pop = int(entry["expected_population"])
    if not _declared_lands(entry, bn, an):
        return _declared_off_store(entry, bn, an)
    return (f" -- BELOW the declared population {pop} by {(pop - an) / pop * 100:.1f}% (at/over the "
            f"{SLICE_DROP_REFUSE * 100:.0f}% line applied to the declaration; declared {entry['declared_on']})")


# ── the guard verdict ────────────────────────────────────────────────────────────────────────────────────
def evaluate(prior: dict, after: dict, *, layer: str, allow_churn: float | None = None,
             already_written=(), declared: "DeclaredChurn | None" = None) -> dict:
    """Straddle one wholesale write pass. `prior` is resolve_prior's map; `after` is {name: span_tuple} for
    every slice the pass is about to write (span_tuple carries the exact new n). Returns
    {refusals, warns, layer_before_n, layer_after_n, layer_drop, prior_only, prior_only_n, unmeasured,
    declared_admitted} --
    it never writes and never raises; the caller decides (plan_write + raise_if_refused do, across every
    layer of the pass, before any byte moves).

    `allow_churn` is the --allow-churn escape hatch and it REQUIRES an expected magnitude (a fraction in
    [0,1]): a declared 0.30 permits drops up to 30% and downgrades them plus every span contraction to a
    warn. It is deliberately not a boolean -- "I expect churn" is not a statement anyone can be wrong about,
    "I expect up to 30%" is. A declared ZERO is not a declaration of churn at all (F15): `--allow-churn 0`
    used to leave the drop line armed while silently downgrading EVERY span contraction to a warn, the exact
    opposite of what "I expect no churn" means. Both legs now gate on a nonzero magnitude.

    THE EMPTY GUARD (leg 1) IS A FLOOR, NOT COVERAGE (F8). It is currently UNREACHABLE from the four
    in-tree callers, and this is stated rather than implied so nobody reads it as the G1b leg-3 case being
    exercised in production: `write_driver_slices` builds `records` from `driver_sink`, whose keys only exist
    via `setdefault(dn, []).append(...)`, so every list has >=1 record and the (source_key, text) dedup cannot
    empty one; and `_commodity_guarded_write`, `_plan_raw_write` and `build_index` all filter empty nodes out
    BEFORE the guard on purpose (an empty node must keep its prior file -- refusing a whole pass over one
    empty node would be a regression, not a guard). It is retained as a floor for future callers and is
    driven synthetically by test_write_guard.test_empty_over_nonempty_refuses.

    `declared` (a DeclaredChurn; plan_write loads it) is the PER-SLICE route: a refusable drop on a slice with
    a declaration IN FORCE is admitted -- as a WARN carrying the declaration, also listed in
    `declared_admitted` -- when _declared_admits says the pass LANDS the declared change (the prior still reads
    as a pre-change reading, the new population reads as none) and the new population is the declared one. A
    span contraction is admitted endpoint by endpoint on such a pass only (_declared_lands), and only as far
    inward as the entry's `expected_span` declares (_declared_span_admits). Nothing else consults it: the empty
    guard (1), the layer line (4) and every undeclared slice are judged exactly as before. `allow_churn` keeps
    its layer-wide meaning and is checked first."""
    refusals: list[str] = []
    warns: list[str] = []
    unmeasured: list[str] = []
    admitted: list[str] = []
    for name in sorted(after):
        p = prior.get(name) or {"bytes": 0, "n": 0, "exact": True, "span": None, "source": "absent"}
        a = after[name]
        bn, an = p.get("n"), a["n"]
        key = f"{layer}/{name}"
        entry = declared.entry_for(key) if declared is not None else None
        declared_ok = _declared_admits(entry, bn, an)
        # (1) empty guard -- exact, needs no count estimate. Mirrors evidence_batch.py:433's commodity guard,
        #     which write_driver_slices never had.
        if an == 0 and p["bytes"] > 0:
            refusals.append(f"{layer}/{name}: refusing to write an EMPTY slice over an existing "
                            f"{p['bytes']} B object ({p['source']})")
            continue
        # (2) population drop -- the D-EI-7 line.
        if bn:
            drop = (bn - an) / bn
            if drop > 0:
                qual = "" if p["exact"] else " [estimated prior]"
                line = (f"{layer}/{name}: population {bn} -> {an} ({drop * 100:.1f}% drop){qual} "
                        f"[prior: {p['source']}]")
                if drop >= SLICE_DROP_REFUSE and (not allow_churn or drop > allow_churn):
                    if declared_ok:
                        warns.append(line + _declared_note(entry, bn, an))
                        admitted.append(warns[-1])
                    else:
                        refusals.append(line + f" -- at/over the {SLICE_DROP_REFUSE * 100:.0f}% refuse line"
                                        + ("" if not allow_churn
                                           else f" and over the declared --allow-churn {allow_churn * 100:.0f}%")
                                        + _declared_miss(declared, key, entry, bn, an))
                else:
                    warns.append(line)
        elif bn is None and p.get("bytes"):
            # (2b) F16 -- an UNREADABLE prior (a throttled ranged GET, a truncated object) disarms the drop
            #      check for this slice AND is excluded from before_total below. "not checked" must never
            #      read as "checked and clean", so it is named here and carried into the manifest.
            unmeasured.append(f"{layer}/{name}: prior population NOT MEASURED ({p['bytes']} B object, "
                              f"{p['source']}) -- the drop check is DISARMED for this slice and its prior "
                              f"props are excluded from the layer line")
            warns.append(unmeasured[-1])
        # (3) span endpoints -- only evaluable against an EXACT prior (a run manifest); silence here means
        #     "no baseline", and the manifest says so per slice rather than implying "no move".
        contracted, expanded = _span_moves(p.get("span"), a)
        for mv in contracted:
            line = f"{layer}/{name}: span CONTRACTED {mv} [prior: {p['source']}]"
            if SPAN_CONTRACTION_REFUSES and not allow_churn:
                field = mv.split(" ", 1)[0]                    # _span_moves lines are "<field> <b> -> <a>"
                lands = _declared_lands(entry, bn, an)          # the population leg's own test gates the span
                if lands and _declared_span_admits(entry, field, a.get(field)):
                    warns.append(line + f" -- ADMITTED by declared churn [{DECLARED_CHURN_FILE}: declared_on "
                                        f"{entry['declared_on']}, expires {entry['expires']}]: the pass lands the "
                                        f"declared change and expected_span {field} "
                                        f"{entry['expected_span'][field]} is not passed")
                    admitted.append(warns[-1])
                elif entry is not None:
                    d = (entry.get("expected_span") or {}).get(field)
                    refusals.append(line + (_declared_off_store(entry, bn, an) if not lands else
                                            f" -- PAST the declared expected_span {field} {d}" if d else
                                            f" -- the declaration for this slice does not declare {field}"))
                else:
                    refusals.append(line + _declared_miss(declared, key, None, bn, an))
            else:
                warns.append(line)
        for mv in expanded:
            warns.append(f"{layer}/{name}: span grew {mv}")
    before_total = sum(int(p["n"]) for p in prior.values() if p.get("n"))
    after_total = sum(a["n"] for a in after.values())
    # slices present before but NOT written by this pass keep their props -- count them on both sides so the
    # layer line measures the pass, not the pass's coverage.
    untouched = sum(int(p["n"]) for name, p in prior.items() if name not in after and p.get("n"))
    after_total_layer = after_total + untouched
    # (4) F9 -- a slice in the STORE that this pass did not write. Two very different causes share one shape:
    #     a legitimately partial pass (--nodes corn) and "its terms were deleted, so it never entered the
    #     sink, so it is never rewritten and its stale file persists on S3 indefinitely". resolve_prior's
    #     docstring claimed this case was VISIBLE; it was not -- evaluate iterates `after`, so a prior-only
    #     slice got no line, no warn and no manifest entry, and the coffee_rust_crop 505->gone class was
    #     silent where the 505->20 class trips. It is named now, per layer, with the full list in the
    #     manifest. It is still CREDITED to after_total_layer above: this guard cannot tell coverage from
    #     deletion, and un-crediting would refuse every partial pass. See the OPEN item in the fix round.
    #     `already_written` is how a pass that plans the same layer MORE THAN ONCE (build_index runs per
    #     node against the shared commodity layer) keeps this honest: a slice an earlier call in THIS pass
    #     already wrote is not "unwritten by the pass", and plan_write feeds the manifest's own record in.
    done = set(already_written)
    prior_only = sorted(name for name, p in prior.items()
                        if name not in after and name not in done and (p.get("n") or 0) > 0)
    prior_only_n = sum(int(prior[name]["n"]) for name in prior_only)
    if prior_only:
        shown = ", ".join(prior_only[:10]) + (f", ... (+{len(prior_only) - 10})" if len(prior_only) > 10
                                              else "")
        warns.append(f"{layer}: {len(prior_only)} slice(s) present in the store but NOT written by this "
                     f"pass, holding {prior_only_n} props -- their files persist unchanged. Expected for a "
                     f"partial pass; for a FULL pass it means the terms no longer route (a stale file "
                     f"nobody rewrites). [{shown}]")
    layer_drop = ((before_total - after_total_layer) / before_total) if before_total else 0.0
    if layer_drop >= LAYER_DROP_REFUSE and (not allow_churn or layer_drop > allow_churn):
        refusals.append(f"{layer}: LAYER population {before_total} -> {after_total_layer} "
                        f"({layer_drop * 100:.1f}% drop) -- at/over the "
                        f"{LAYER_DROP_REFUSE * 100:.0f}% refuse line")
    return {"refusals": refusals, "warns": warns, "layer_before_n": before_total,
            "layer_after_n": after_total_layer, "layer_drop": round(layer_drop, 6),
            "prior_only": prior_only, "prior_only_n": prior_only_n, "unmeasured": unmeasured,
            "declared_admitted": admitted}


# ── G1c: the run manifest ────────────────────────────────────────────────────────────────────────────────
class RunManifest:
    """One manifest per write pass -- the artifact whose absence made 2026-07-19 unattributable.

    Carries: pass label, UTC stamp, the container command verbatim, the chunk_version in play, docs written /
    OVERWRITTEN with their vintage transitions, per-slice {before_bytes, after_bytes, before_n, after_n,
    truncated_n, span before/after, prior source}, and the caller's `warnings` collector. Written beside the
    other eval artifacts (local configs/graphrag/eval/ + <EVIDENCE_S3>/eval/), where --dark-tally already
    writes, with a UTC-stamped filename so a rerun never overwrites the prior record."""

    def __init__(self, label: str, *, chunk_version: str | None = None, allow_churn: float | None = None):
        self.label = label
        self.started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.chunk_version = chunk_version
        self.allow_churn = allow_churn
        self.slices: dict[str, dict] = {}                      # layer -> {slice -> record}
        self.unwritten: dict[str, dict] = {}                   # layer -> {slice -> prior-only record} (F9)
        self.docs: dict = {"written": 0, "overwritten": 0, "vintage_transitions": {}, "per_doc_delta": {}}
        self.extraction: dict = {}                             # X2: per-pass window / doc-read / dedup counters
        self.warnings: list[str] = []
        self.guard: dict[str, dict] = {}                       # layer -> evaluate() verdict
        self.declared_churn: dict | None = None                # the declarations this pass was judged by

    # -- slices -------------------------------------------------------------------------------------------
    def record_slice(self, layer: str, name: str, *, prior: dict, after_span: dict,
                     after_bytes: int | None = None, truncated_n: int = 0) -> None:
        self.slices.setdefault(layer, {})[name] = {
            "before_bytes": prior.get("bytes", 0), "after_bytes": after_bytes,
            "before_n": prior.get("n"), "after_n": after_span["n"],
            "before_n_exact": bool(prior.get("exact")), "prior_source": prior.get("source"),
            "before_span": prior.get("span"), "after_span": after_span,
            "truncated_n": int(truncated_n),
        }

    def set_after_bytes(self, layer: str, name: str, nbytes: int) -> None:
        rec = self.slices.get(layer, {}).get(name)
        if rec is not None:
            rec["after_bytes"] = int(nbytes)

    def record_guard(self, layer: str, verdict: dict) -> None:
        """Record one layer's verdict. A layer planned MORE THAN ONCE in a pass (build_index is called per
        node against the shared commodity layer) ACCUMULATES rather than overwrites -- the last node's
        verdict silently replacing the previous 23 would make the manifest's guard section a record of one
        node while reading as a record of the pass."""
        prev = self.guard.get(layer)
        if prev is None:
            self.guard[layer] = {k: v for k, v in verdict.items()} | {"n_plans": 1}
            return
        merged = {k: v for k, v in verdict.items()}
        for key in ("refusals", "warns", "unmeasured", "prior_only", "declared_admitted"):
            merged[key] = list(prev.get(key) or []) + [x for x in (verdict.get(key) or [])
                                                       if x not in (prev.get(key) or [])]
        merged["n_plans"] = int(prev.get("n_plans") or 1) + 1
        self.guard[layer] = merged

    def record_declared(self, declared: "DeclaredChurn") -> None:
        """The declared-churn file this pass read (path, sha256, state, what was in force). Recorded ONCE per
        pass -- every plan_write reads the same file -- so a later reader can tell exactly which declaration
        admitted which slice, and a pass judged with NO declarations says so rather than omitting the key."""
        if self.declared_churn is None:
            self.declared_churn = declared.record()

    def record_unwritten(self, layer: str, prior: dict, names) -> None:
        """F9 -- slices the store holds that this pass did NOT write, with their prior population and the
        source that population came from. Deliberately NOT folded into `slices`: those records are what
        resolve_prior trusts as an exact baseline, and a prior-only slice's `n` is usually a size ESTIMATE.
        Recording an estimate where the next pass reads an exact count is how a mirror lies."""
        if not names:
            return
        rec = self.unwritten.setdefault(layer, {})
        for n in sorted(names):
            rec[n] = {"prior_n": (prior.get(n) or {}).get("n"),
                      "prior_bytes": (prior.get(n) or {}).get("bytes"),
                      "prior_source": (prior.get(n) or {}).get("source")}
        # A later call in the same pass may WRITE a slice an earlier call listed as unwritten (build_index
        # runs per node against the shared commodity layer): drop anything now recorded as written, so the
        # manifest's "unwritten" section is the state at flush, not a stale intermediate.
        for n in [k for k in rec if k in (self.slices.get(layer) or {})]:
            rec.pop(n)

    # -- docs (G1a) ---------------------------------------------------------------------------------------
    def record_docs(self, *, written: int, overwritten: int, vintage_transitions: dict,
                    per_doc_delta: dict) -> None:
        self.docs = {"written": int(written), "overwritten": int(overwritten),
                     "vintage_transitions": {str(k): int(v) for k, v in vintage_transitions.items()},
                     "per_doc_delta": {str(k): int(v) for k, v in per_doc_delta.items()}}

    # -- extraction (X2) ----------------------------------------------------------------------------------
    def record_extraction(self, counters: dict) -> None:
        """Merge one pass-stage's extraction counters into the manifest: window states (`windows`), document
        reads (`doc_reads`), the dedup gate (`dedup`). A MERGE rather than a set, because `run` is submit
        THEN retrieve and each stage records its own half of the same pass. These are the numbers that make
        "the batch produced fewer props than the census predicted" answerable without a re-measurement."""
        self.extraction.update({str(k): v for k, v in (counters or {}).items()})

    # -- payload / flush ----------------------------------------------------------------------------------
    def payload(self) -> dict:
        return {
            "manifest": "evidence_write", "version": 1, "label": self.label,
            "started_utc": self.started,
            "finished_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "command": [_ascii(a) for a in sys.argv],
            "evidence_s3": os.environ.get("EVIDENCE_S3"),
            "chunk_version": self.chunk_version,
            "allow_churn": self.allow_churn,
            "thresholds": {"slice_drop_refuse": SLICE_DROP_REFUSE, "layer_drop_refuse": LAYER_DROP_REFUSE,
                           "span_contraction_refuses": SPAN_CONTRACTION_REFUSES},
            "docs": self.docs,
            "extraction": self.extraction,
            "slices": self.slices,
            # F9: store-only slices this pass never wrote. Their files persist unchanged; on a FULL pass that
            # means their terms no longer route and the stale object is nobody's to rewrite.
            "unwritten": self.unwritten,
            "guard": self.guard,
            "declared_churn": self.declared_churn,
            "warnings": [_ascii(w) for w in self.warnings],
            # Stated, not implied: the row-level churn ratio G1b leg 1 asks for is NOT computable from any
            # source this guard reads. See the module docstring.
            "layer_row_churn": None,
            "layer_row_churn_reason": ("row-level |lost|+|gained| needs the prior row SET (101 GETs / "
                                       "1.361 GB with a full json.loads of vector-bearing lines); this "
                                       "manifest carries NET population only. A frozen count does NOT mean "
                                       "no rows moved -- see G5a."),
        }

    def flush(self) -> str:
        """Write the manifest local + (when EVIDENCE_S3 is set) remote; print an ASCII summary. Returns the
        local path. Never raises on the remote leg -- losing the S3 copy must not fail a completed pass."""
        from pathlib import Path

        from leviathan.graphrag import evidence as ev
        from leviathan.graphrag import extract as ex
        doc = self.payload()
        name = f"write_manifest_{self.label}_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.json"
        out = ex._CFG / "eval" / name
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(json.dumps(doc, indent=2), encoding="utf-8")
        base = ev._evid_s3()
        if base:
            try:
                b, k = ev._parse_s3(base.rstrip("/") + f"/eval/{name}")
                _s3_client().put_object(Bucket=b, Key=k, Body=json.dumps(doc).encode("utf-8"))
            except Exception as exc:                           # noqa: BLE001
                print(f"  WARN run-manifest: local copy written but the S3 copy failed ({_ascii(exc)})")
        for layer, recs in sorted(self.slices.items()):
            trunc = sum(r["truncated_n"] for r in recs.values())
            g = self.guard.get(layer) or {}
            print(f"  run-manifest [{self.label}/{layer}]: {len(recs)} slices, "
                  f"{g.get('layer_before_n')} -> {g.get('layer_after_n')} props, "
                  f"truncated={trunc}, warns={len(g.get('warns') or [])}")
        print(f"  run-manifest -> {out}")
        return str(out)


# ── the atomic wrapper every wholesale slice write goes through ──────────────────────────────────────────
class WritePlan:
    """One layer, EVALUATED but not yet written. The unit F1 exists to create.

    Before this split, `guarded_write` evaluated and wrote in one call, and a pass with more than one layer
    therefore refused only AFTER every earlier layer had already landed: `_route_and_write` completed all 24
    commodity writes (11,119,127,224 bytes) and only then let `write_driver_slices` raise. The module
    docstring promised "a refusal leaves the store byte-identical instead of half-rewritten"; that held
    WITHIN a layer and nowhere else, and the 2026-07-20 shape (commodity fine, drivers collapse) lands
    precisely in the gap.

    A plan carries everything needed to commit and nothing that commits: the verdict, the resolved prior, the
    per-slice after-spans and the lazy payload closures (so a refused pass still pays no embed). The caller
    plans EVERY layer, calls raise_if_refused over all of them, and only then commits."""

    __slots__ = ("layer", "subprefix", "prior", "after", "verdict", "payloads", "records", "write_fn",
                 "node_of", "manifest", "truncated")

    def __init__(self, *, layer: str, subprefix: str, prior: dict, after: dict, verdict: dict,
                 payloads: dict, records: dict, write_fn, node_of, manifest: "RunManifest | None",
                 truncated: dict | None):
        self.layer, self.subprefix = layer, subprefix
        self.prior, self.after, self.verdict = prior, after, verdict
        self.payloads, self.records = payloads, records
        self.write_fn, self.node_of = write_fn, node_of
        self.manifest, self.truncated = manifest, truncated or {}

    @property
    def refusals(self) -> list[str]:
        return list(self.verdict["refusals"])

    def __repr__(self) -> str:                                 # pragma: no cover -- debugging aid
        return (f"WritePlan({self.layer}, {len(self.records)} slices, "
                f"{len(self.verdict['refusals'])} refusals)")


def plan_write(layer: str, subprefix: str, payloads: dict, *, records: dict,
               manifest: RunManifest | None, allow_churn: float | None, write_fn, node_of,
               truncated: dict | None = None, warnings: list | None = None) -> WritePlan:
    """Evaluate one layer's wholesale write and return the plan. WRITES NOTHING and RAISES NOTHING.

    `layer`    the manifest key ("drivers" / "commodity" / "_raw"); `subprefix` the store prefix it lives
               under ("drivers/" / "" / "_raw/") -- kept separate so the manifest key survives a prefix change;
    `records`  {slice -> the exact record list about to be written} (spans + counts come from here, free);
    `payloads` {slice -> the serialized body} -- may be a lazy callable per slice to keep 1.3 GB of bodies
               out of memory at once, and so that a refused pass pays no embed;
    `write_fn(node, body)` performs the single wholesale write; `node_of(name)` maps a slice name to its
    store node ("drivers/x" or "x"). A write_fn marked with `bytes_writer` is handed the ALREADY-ENCODED
    utf-8 bytes instead of the str -- see commit_write, and BYTES_WRITER_ATTR for why the marker exists.

    Warns are printed and recorded HERE (at plan time), because a warn is information about the pass whether
    or not the pass proceeds -- a refused pass's warns are the diagnosis."""
    prior = resolve_prior(subprefix, list(records), layer=layer)
    after = {name: span_tuple(recs) for name, recs in records.items()}
    done = set((manifest.slices.get(layer) or {})) if manifest is not None else set()
    declared = load_declared_churn()                           # read from the image's configs; never raises
    verdict = evaluate(prior, after, layer=layer, allow_churn=allow_churn, already_written=done,
                       declared=declared)
    if declared.state == "invalid":
        verdict["warns"].insert(0, f"declared-churn manifest INVALID at {declared.path} -- EVERY declaration "
                                   f"ignored, fail closed (the {SLICE_DROP_REFUSE * 100:.0f}% line applies to "
                                   f"every slice): {'; '.join(declared.errors)[:600]}")
    for line in verdict["warns"]:
        print(f"  WARN write-guard {_ascii(line)}")
        if manifest is not None:
            manifest.warnings.append(f"WARN write-guard {line}")
        if warnings is not None:
            warnings.append(f"WARN write-guard {_ascii(line)}")
    if manifest is not None:
        manifest.record_declared(declared)
        manifest.record_guard(layer, verdict)
        manifest.record_unwritten(layer, prior, verdict.get("prior_only") or [])
        for name, span in after.items():
            manifest.record_slice(layer, name, prior=prior.get(name) or {}, after_span=span,
                                  truncated_n=(truncated or {}).get(name, 0))
    return WritePlan(layer=layer, subprefix=subprefix, prior=prior, after=after, verdict=verdict,
                     payloads=payloads, records=records, write_fn=write_fn, node_of=node_of,
                     manifest=manifest, truncated=truncated)


def raise_if_refused(*plans: WritePlan) -> None:
    """UNION the refusals across every planned layer and raise ONCE, before any of them commits.

    This is the whole of F1's fix in one function: the caller cannot write layer A and then discover layer B
    refuses, because the refusals of A and B are pooled here while both are still unwritten. Called with one
    plan it is exactly the old behaviour; called with three it is the atomicity the docstring always
    claimed."""
    lines: list[str] = []
    for p in plans:
        lines.extend(p.verdict["refusals"])
    if not lines:
        return
    for line in lines:
        print(f"  REFUSE write-guard {_ascii(line)}")
    layers = ", ".join(sorted({p.layer for p in plans}))
    raise WriteRefused(lines + [
        f"nothing was written in ANY layer ({layers}) -- every layer of this pass was evaluated before the "
        f"first byte moved. If a refused population change is INTENDED, DECLARE it for that one slice in "
        f"configs/graphrag/{DECLARED_CHURN_FILE} (slice, declared_on, reason naming the routing change and "
        f"its commit, prior_population = the measured pre-change slice, expected_population, optionally "
        f"expected_span, expires) -- the guard then admits exactly that slice at exactly that population / "
        f"those endpoints, on the one pass that moves it off the pre-change slice, and nothing else. "
        f"--allow-churn <pct> (e.g. "
        f"--allow-churn 25) is LAYER-WIDE: every slice in the pass may then drop that much."])


# ── the bytes contract for write_fn (the 2026-08-02 OOM) ─────────────────────────────────────────────────
# A write_fn is CALLER-SUPPLIED, so commit_write cannot simply assume it takes bytes: a test double or a
# future caller may only handle str, and handing it bytes would break it -- or, worse, a try-bytes/retry-str
# fallback would re-run a write_fn that may already have put half its object before raising. So the bytes
# path is OPT-IN and explicit: a write_fn that carries this attribute is handed the pre-encoded utf-8 bytes;
# anything else is handed the str exactly as before. The four shipped callers all pass evidence._evid_write,
# which sets the marker, so production takes the zero-copy path and nothing else changes behaviour.
#
# The marker is a plain attribute, so ANY wrapper that does not copy it -- a functools.partial, a lambda, a
# decorator, a monkeypatch -- silently lands on the str branch. That branch must therefore be no worse than
# the pre-fix loop, which is why commit_write DROPS its own bytes (`blob = None`) before calling a str-only
# write_fn: otherwise our bytes would still be live while write_fn encodes its own, i.e. 3.00x the body at
# the sink -- WORSE than the 2.00x that OOM-killed the pass, and in exactly the configuration that dies
# (measured on a 256 MB body: 3.00x without the drop, 2.00x with it, which is today's peak). Degradation is
# then strictly "slower, never wrong": one extra encode, never an extra live copy.
BYTES_WRITER_ATTR = "accepts_bytes"


def bytes_writer(fn):
    """Mark a `write_fn(node, body)` as accepting BYTES as well as str. Returns fn (usable as a decorator)."""
    setattr(fn, BYTES_WRITER_ATTR, True)
    return fn


def _accepts_bytes(fn) -> bool:
    return bool(getattr(fn, BYTES_WRITER_ATTR, False))


def commit_write(plan: WritePlan) -> int:
    """Run one planned layer's write loop. Call ONLY after raise_if_refused over every plan in the pass.
    Returns the number of records written.

    ONE ENCODE PER SLICE, and the str released before the write. The 2026-08-02 Wave-R routing pass was
    OOM-killed (exit 137, 8 vCPU / 16 GB) mid commit_all on graphrag_evidence/soybeans.jsonl -- the largest
    object in the store at 1.03 GB -- after landing 19 of 24 commodity slices and zero driver slices, leaving
    the store TORN. This loop paid for that body THREE times: the materialized str; the bytes `_evid_write`
    encoded from it, which put 2.00x the body live at the moment of the PUT, i.e. exactly where boto3 then
    layers its own request buffers (tracemalloc, 40 MB stand-in); and then, after the write, a SECOND full
    encode of the same str whose only purpose was `len(...)` for the manifest, taking it back to 2.00x. Now
    the payload is encoded exactly once here, the str is released BEFORE the write (measured: 1.00x live at
    the PUT), the SAME bytes object is both written and measured, and both are dropped before the next slice
    materializes -- so a 24-slice commit_all never carries one slice's body into the next slice's.

    WHAT THIS DOES AND DOES NOT LOWER (measured, 256 MB body). Copies alive AT THE SINK: 2 -> 1, which is the
    point -- that window is the whole 1.03 GB S3 PUT, where boto3 layers its own request buffers on top, and
    it is where exit 137 landed. Full-size 2.00x windows per slice: 2 -> 1 (the post-write len() encode is
    gone). The absolute in-process PEAK is UNCHANGED at 2.00x: str and bytes necessarily coexist during the
    encode itself, and no rearrangement of this loop can avoid that without streaming the serialization. So
    the 2.00x moment MOVED -- from a network-bound PUT to a ~0.2s memcpy with no other allocator active --
    it did not halve. Do not describe this as "peak memory dropped"; it dropped AT THE SINK.

    INVARIANT (a): `set_after_bytes` still records the TRUE utf-8 byte length of the body that was written --
    it is now `len()` of the very bytes handed to write_fn rather than a second encode of the same str, which
    is the same number by construction. resolve_prior compares it for EQUALITY against the stored object size
    as its stale-mirror fence, so a wrong value here silently downgrades every slice to a size estimate and
    blanks its span."""
    total = 0
    wants_bytes = _accepts_bytes(plan.write_fn)
    for name in sorted(plan.records):
        body = plan.payloads[name]
        body = body() if callable(body) else body              # materialize (up to 1.03 GB)
        blob = body if isinstance(body, (bytes, bytearray)) else body.encode("utf-8")   # the ONLY encode
        nbytes = len(blob)
        if wants_bytes:
            target = blob                                      # zero-copy: the SAME object is written+measured
        else:
            target, blob = body, None                          # str-only write_fn: drop OUR bytes first, or it
                                                               # re-encodes a THIRD copy alongside them (3.00x)
        del body                                               # release the str before the write ...
        plan.write_fn(plan.node_of(name), target)
        total += len(plan.records[name])
        if plan.manifest is not None:
            plan.manifest.set_after_bytes(plan.layer, name, nbytes)
        del target, blob                                       # ... and before the next slice materializes
    return total


def commit_all(*plans: WritePlan) -> dict:
    """Commit several planned layers in order; {layer: records written}. The caller has already established
    that none of them refuses."""
    return {p.layer: commit_write(p) for p in plans}


def guarded_write(layer: str, subprefix: str, payloads: dict, *, records: dict,
                  manifest: RunManifest | None, allow_churn: float | None, write_fn, node_of,
                  truncated: dict | None = None, warnings: list | None = None) -> int:
    """Plan + raise + commit for a SINGLE-layer pass -- the original one-call entry point, unchanged in
    behaviour and signature.

    Multi-layer callers must NOT use this: two guarded_write calls in sequence are exactly the F1 defect.
    Use plan_write for every layer, then raise_if_refused(*plans), then commit_write."""
    plan = plan_write(layer, subprefix, payloads, records=records, manifest=manifest,
                      allow_churn=allow_churn, write_fn=write_fn, node_of=node_of,
                      truncated=truncated, warnings=warnings)
    raise_if_refused(plan)
    return commit_write(plan)


# ── F4: the read-only baseline bootstrap ─────────────────────────────────────────────────────────────────
# {layer key -> store subprefix}. The layer key is what resolve_prior looks up inside a manifest's `slices`,
# so these strings MUST match the ones plan_write is called with.
SEED_LAYERS = {"commodity": "", "drivers": "drivers/", "_raw": "_raw/"}


def _stream_slice_lines(node: str):
    """Yield the json lines of a stored slice WITHOUT materializing the whole object.

    A commodity slice runs to hundreds of MB; `_evid_read` returns one str. This streams: a local file line
    by line, an S3 object through the StreamingBody's own line iterator (one GET, no range juggling)."""
    from leviathan.graphrag import evidence as ev
    base = ev._evid_s3()
    if base:
        bkt, key = ev._parse_s3(base.rstrip("/") + f"/{node}.jsonl")
        body = _s3_client().get_object(Bucket=bkt, Key=key)["Body"]
        for raw in body.iter_lines():
            yield raw.decode("utf-8", "ignore") if isinstance(raw, bytes) else raw
        return
    p = ev._EVID_DIR / f"{node}.jsonl"
    if not p.exists():
        return
    with open(p, "r", encoding="utf-8") as fh:
        for line in fh:
            yield line


def seed_manifest(layers=("drivers",), *, label: str = "seed") -> str:
    """READ-ONLY bootstrap of the run manifest the span guard needs, streamed off the CURRENT store.

    WHY THIS EXISTS (F4). `resolve_prior` sets `"span": None` on both the estimate branch and the absent
    branch; only the run-manifest branch carries a real span, and `_span_moves(None, after)` returns
    ([], []). `newest_run_manifest()` returns None on a store that has never had a guarded pass -- which is
    every store today. So G1b leg 2, "the leg that would have caught `potash` -25y and
    `mississippi_river_levels` -3y immediately", CANNOT FIRE on the first guarded pass, and the first guarded
    pass IS the Wave-R rebuild the whole wave is built around. The guard is sound; its baseline does not
    exist. This makes it exist.

    WHAT IT DOES. For each requested layer: one LIST for the sizes, then one full streamed read per slice to
    count props and derive the exact {date,event_date} span tuple. Emits
    `write_manifest_seed_<UTC>.json` into configs/graphrag/eval/ (+ <EVIDENCE_S3>/eval/ when set), with
    `after_n` / `after_span` measured and `after_bytes` taken from the LIST -- the store's own byte count, so
    resolve_prior's stale-mirror fence (`rec["after_bytes"] == nbytes`) matches on the very next pass instead
    of falling through to the size estimate.

    READ-ONLY, and that is a property of the code, not a promise: it opens no write path to any slice. The
    ONLY object it writes is its own manifest under eval/. IDEMPOTENT: re-running it re-derives the same
    numbers from the same store and emits a second, byte-equivalent-modulo-timestamp manifest; nothing in the
    slice layer moves, and newest_run_manifest simply reads the newer one.

    COST. Drivers is ~1.361 GB / 101 objects; commodity is ~11.1 GB / 24 objects; `_raw` ~80 MB / 24. Default
    is drivers-only because that is where every measured span move happened. Pass layers=("drivers",
    "commodity", "_raw") for the full baseline.

    Returns the local manifest path."""
    unknown = [x for x in layers if x not in SEED_LAYERS]
    if unknown:
        raise ValueError(f"unknown seed layer(s) {unknown}; known: {sorted(SEED_LAYERS)}")
    mf = RunManifest(label)
    mf.warnings.append("SEED manifest: derived read-only from the CURRENT store by --seed-manifest. It "
                       "records what the store HOLDS, not what any pass wrote -- there is no before/after "
                       "here and no guard verdict was taken.")
    for layer in layers:
        sub = SEED_LAYERS[layer]
        sizes = list_slice_bytes(sub)
        total = 0
        for name in sorted(sizes):
            node = f"{sub.strip('/')}/{name}" if sub.strip("/") else name
            recs = []
            for line in _stream_slice_lines(node):
                if not line.strip():
                    continue
                try:
                    r = json.loads(line)
                except Exception:                              # noqa: BLE001 -- one bad line is not a baseline
                    continue
                recs.append({"date": r.get("date"), "event_date": r.get("event_date")})
            span = span_tuple(recs)
            total += span["n"]
            mf.record_slice(layer, name, prior={"bytes": int(sizes[name]), "n": None, "exact": False,
                                                "span": None, "source": "seed (no prior pass)"},
                            after_span=span)
            mf.set_after_bytes(layer, name, int(sizes[name]))   # the STORE's bytes, so the fence matches
            print(f"  seed [{layer}/{name}]: {span['n']} props, {sizes[name]} B, "
                  f"date {span['date_min']}..{span['date_max']} event {span['event_date_min']}.."
                  f"{span['event_date_max']}")
        mf.record_guard(layer, {"refusals": [], "warns": [], "layer_before_n": None,
                                "layer_after_n": total, "layer_drop": 0.0, "prior_only": [],
                                "prior_only_n": 0, "unmeasured": [],
                                "seed": True})
    return mf.flush()
