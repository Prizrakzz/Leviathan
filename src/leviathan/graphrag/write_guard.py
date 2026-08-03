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
#   legitimate path is --allow-churn with a declared magnitude.
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


# ── the guard verdict ────────────────────────────────────────────────────────────────────────────────────
def evaluate(prior: dict, after: dict, *, layer: str, allow_churn: float | None = None,
             already_written=()) -> dict:
    """Straddle one wholesale write pass. `prior` is resolve_prior's map; `after` is {name: span_tuple} for
    every slice the pass is about to write (span_tuple carries the exact new n). Returns
    {refusals, warns, layer_before_n, layer_after_n, layer_drop, prior_only, prior_only_n, unmeasured} --
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
    driven synthetically by test_write_guard.test_empty_over_nonempty_refuses."""
    refusals: list[str] = []
    warns: list[str] = []
    unmeasured: list[str] = []
    for name in sorted(after):
        p = prior.get(name) or {"bytes": 0, "n": 0, "exact": True, "span": None, "source": "absent"}
        a = after[name]
        bn, an = p.get("n"), a["n"]
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
                    refusals.append(line + f" -- at/over the {SLICE_DROP_REFUSE * 100:.0f}% refuse line"
                                    + ("" if not allow_churn
                                       else f" and over the declared --allow-churn {allow_churn * 100:.0f}%"))
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
                refusals.append(line)
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
            "prior_only": prior_only, "prior_only_n": prior_only_n, "unmeasured": unmeasured}


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
        self.warnings: list[str] = []
        self.guard: dict[str, dict] = {}                       # layer -> evaluate() verdict

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
        for key in ("refusals", "warns", "unmeasured", "prior_only"):
            merged[key] = list(prev.get(key) or []) + [x for x in (verdict.get(key) or [])
                                                       if x not in (prev.get(key) or [])]
        merged["n_plans"] = int(prev.get("n_plans") or 1) + 1
        self.guard[layer] = merged

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
            "slices": self.slices,
            # F9: store-only slices this pass never wrote. Their files persist unchanged; on a FULL pass that
            # means their terms no longer route and the stale object is nobody's to rewrite.
            "unwritten": self.unwritten,
            "guard": self.guard,
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
    verdict = evaluate(prior, after, layer=layer, allow_churn=allow_churn, already_written=done)
    for line in verdict["warns"]:
        print(f"  WARN write-guard {_ascii(line)}")
        if manifest is not None:
            manifest.warnings.append(f"WARN write-guard {line}")
        if warnings is not None:
            warnings.append(f"WARN write-guard {_ascii(line)}")
    if manifest is not None:
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
        f"first byte moved. Re-run with --allow-churn <pct> naming the drop you EXPECT "
        f"(e.g. --allow-churn 25) if this population change is intended."])


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
