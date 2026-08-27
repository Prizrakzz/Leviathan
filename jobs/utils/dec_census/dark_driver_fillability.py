"""DARK-DRIVER FILLABILITY CENSUS -- a NEW instrument (D-EC graph-completion wave, stage 2, RUN 3).

THE QUESTION. 123 declared DAG driver ids have no evidence slice behind them (`dark`). For each
one, is the honest next move to (a) author terms / a slice because the corpus already carries the
text, (b) bind it to a silver table because the NUMBER exists, or (c) keep the waiver and write
down why? This measures all three axes instead of guessing.

WHY IT HAD TO BE AUTHORED. No committed or scratchpad producer existed. The nearest precedents are
laneA_route.py (the production matcher pair) and window_probe.py.

THE DESIGN FACT THAT SHAPES IT -- ID-AS-TERM IS THE WRONG INSTRUMENT. The scout previewed the
naive version against the pre-X2 345,870-prop cache: 84 of 123 dark ids scored ZERO on forms
derived from their own id, only 6 cleared 100 props, and the leaders were generic-token over-fires
(area 21,753 / consumption 20,662 / stock 1,181 / flowering 371 / phytosanitary 331) -- exactly the
over-firing driver_slices.yaml's own comment forbids ("heat wave" not bare "heat"). A census built
that way is half empty and half poison. So terms here are derived from each dark driver's OWN
authored retrieval text -- `evidence_query` first (it IS the query the DAG author wrote), then
`blurb`, `mechanism`, `region` -- and never from the id, behind five guards. G2, G4 and G5 each
exist because the PREVIOUS version's own samples exposed a defect; the FILLABLE count moved
109 -> 63 -> 35 -> 38 -> 14 across those generations. That history is the argument for why
G3's verbatim samples are mandatory rather than decorative:

  G1  MULTI-TOKEN ONLY. A candidate term must be >= 2 tokens. This is the config's own rule and it
      alone kills the entire single-word poison class the preview surfaced.
  G2  EMPIRICAL GENERICITY CEILING, CALIBRATED ON THE CONFIG'S OWN ACCEPTED TERMS. A first pass at
      this used a flat 1%-of-corpus ceiling and it was FAR too loose: it dropped only 8 terms and
      passed `coffee production`, `sugar production`, `palm oil`, `price sensitive`, which then
      dominated the counts. The samples caught it -- `IOD_negative` was scoring on "Sugar
      production for Australia", `labor_shortage` on "palm oil ... in Australia". So the ceiling
      is no longer a guessed constant: the corpus frequency of all ~711 terms driver_slices.yaml
      ALREADY ACCEPTS is measured in the same pass, and a candidate is refused if it is more
      generic than the config's own CEILING_PCTL-th percentile term. The rule reads: a new term
      may not be vaguer than the vaguest term the product already lives with.
  G3  CONCENTRATION CHECK + SAMPLE VETTING. Per id, the share of its mass carried by its single
      most-firing term is reported. A driver whose "evidence" is one broad term is flagged
      `concentration_risk`, and its verdict is withheld from FILLABLE. Every id also carries 3
      verbatim props so a human can see what actually fired -- a count with no sample is not
      evidence, and this instrument only exists because its first version proved that.
  G4  TOKEN DISTINCTIVENESS ACROSS THE DARK SET. G2 bounds how common a term is in the CORPUS; it
      does not catch a term that is merely generic AMONG DRIVERS. The n-gram sweep runs a sliding
      window over authored text, so it manufactures phrases by joining adjacent-but-unrelated
      keywords -- `China rapeseed oil demand hotpot food biofuel` yields `food biofuel`, and the
      wheat drivers all yield `hard red`. Samples caught this too: `us_export_pace` was scoring on
      "hard red winter wheat", `conab_production_revision` on "soybean meal price". So a term is
      refused unless at least ONE of its tokens is rare across the dark drivers' own authored text
      (document frequency <= MAX_TOKEN_DRIVER_DF of them). `conab brazil` survives on `conab`;
      `crop yield`, `meal price`, `winter wheat` and `south africa` do not. G4 is NOT sufficient
      on its own -- `hard red` passes it (only 6 dark drivers use those tokens) and is killed by
      G2's reach correction instead. The two guards cover different failure modes and both are
      needed.

THE MEASUREMENT. Two passes over the FRESH chunks/ cache (dec_p1_chunks, 1,387,697 props):
  Phase A -- per-TERM corpus frequency, to apply G2.
  Phase B -- per-ID prop counts over surviving terms, split by whether the prop is DRIVER-DARK
             today (no production driver matcher fires: ev.driver_matchers(), the exact pair
             evidence_batch.rebuild_slices uses), plus top sources and the 3 samples.
  A prop matching several terms of one id counts ONCE for that id.

  G5  ANCHORING -- the sharper question the curation stage actually needs answered. G2/G4 decide
      whether a term is too vague to use at all. G5 asks whether the driver has any term that
      NAMES IT: one carrying a token at most ANCHOR_MAX_DF dark drivers use anywhere in their
      authored text (`conab`, `hessian`, `vernalization`, `cecafe`). 120 of the 123 do. A driver
      whose mass rides only shared phrasing has corpus text about its TOPIC, not evidence for
      ITSELF, and a slice authored off that would route other drivers' props into it. So the
      100-prop floor is applied to ANCHORED props, not to total matched props.

THE VERDICT (the run book's rule, applied verbatim, written down before firing):
  FILLABLE-BY-TERM  >= MEASURABLE_FLOOR (100) ANCHORED DRIVER-DARK props on sample-vetted terms.
                    The text is already in the store and nothing routes it -- author terms /
                    a slice.
  BINDABLE          at least one declared instance carries silver_status: available. The NUMBER
                    exists; this is the GN-1 shortlist and costs no corpus at all.
  HONEST-WAIVE      neither. Keep the waiver row and record the reason.
The two axes are ORTHOGONAL and are both reported per id; `verdict` is the primary label under the
precedence FILLABLE > BINDABLE > WAIVE, and `verdict_matrix` gives the honest cross-tab.

Output: data/dec_p1/dark_driver_fillability.{json,md}. Read-only; no S3 writes, no model calls.
"""
from __future__ import annotations

import argparse
import collections
import glob
import hashlib
import json
import os
import re
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import yaml

REPO = Path("C:/Users/User/Desktop/Leviathan")
CFG = REPO / "configs" / "graphrag"
OUT = REPO / "data" / "dec_p1"
OUT.mkdir(parents=True, exist_ok=True)
SCRATCH = Path(r"C:/Users/User/AppData/Local/Temp/claude/"
               r"C--Users-User-Desktop-Leviathan/360a169c-9409-4bdb-af00-a02392ed35a2/scratchpad")
CHUNKS = SCRATCH / "dec_p1_chunks"

sys.path.insert(0, str(REPO / "src"))
from leviathan.graphrag import display as dp     # noqa: E402
from leviathan.graphrag import evidence as ev    # noqa: E402
from leviathan.graphrag import extract as ex     # noqa: E402

MEASURABLE_FLOOR = 100          # dec_p0_rank.py:25 -- the standing floor, reused verbatim
CEILING_PCTL = 90               # G2: calibrated on driver_slices.yaml's OWN accepted terms
MIN_TERM_TOKENS = 2             # G1: the config's own "heat wave not heat" rule
MAX_TOKEN_DRIVER_DF = 0.08      # G4: a term needs >=1 token rare across the dark drivers themselves
MAX_CONCENTRATION = 0.60        # G3: >60% of an id's mass on ONE term = not evidence, an artefact
ANCHOR_MAX_DF = 2               # G5: a token naming <=2 dark drivers ANCHORS a term to this one
MAX_TERMS_PER_ID = 40
N_SAMPLES = 3

STOP = {
    'a', 'an', 'and', 'are', 'as', 'at', 'be', 'been', 'but', 'by', 'can', 'cause', 'causes',
    'for', 'from', 'has', 'have', 'in', 'into', 'is', 'it', 'its', 'may', 'more', 'most', 'no',
    'not', 'of', 'on', 'or', 'other', 'over', 'that', 'the', 'their', 'then', 'this', 'through',
    'to', 'up', 'via', 'when', 'which', 'while', 'with', 'within', 'would', 'less', 'higher',
    'lower', 'high', 'low', 'large', 'small', 'new', 'old', 'both', 'than', 'also', 'any',
}

_RX = None
_TERM_IDS = None
_DRV_RX = None
_ANCHORED = {}


# ─────────────────────────────────────────────────────────────────────────────
# 1. THE DARK UNIVERSE + EVERY DECLARED INSTANCE
# ─────────────────────────────────────────────────────────────────────────────
def dark_universe():
    """sorted(set(display.all_driver_ids()) - set(evidence.driver_alias())).

    Derived IN-PROCESS rather than via `e1_census --local-only`: e1_census.slice_census():233 does
    one full ev.load_index() per slice -- a GET plus a json.loads of vector-bearing lines -- across
    120 driver slices / 3.76 GB. That is the exact transport that failed at DEC-P0 over the home
    link. This route reads config only.
    """
    all_ids = sorted(dp.all_driver_ids())
    backed = set(ev.driver_alias())
    return all_ids, backed, sorted(set(all_ids) - backed)


def declared_instances():
    """{driver id: [instance rows]} across all 33 causal DAGs, carrying the authored text."""
    inst = collections.defaultdict(list)
    for p in sorted(glob.glob(str(CFG / "causal" / "*.yaml"))):
        dag = yaml.safe_load(open(p, encoding="utf-8")) or {}
        contract = dag.get("contract")
        for d in (dag.get("drivers") or []):
            inst[d["id"]].append({
                "contract": contract, "type": d.get("type"), "sign": d.get("sign"),
                "edge_type": d.get("edge_type"), "confidence": d.get("confidence"),
                "silver_ref": d.get("silver_ref"), "silver_status": d.get("silver_status"),
                "evidence_query": d.get("evidence_query") or "",
                "blurb": d.get("blurb") or "", "mechanism": d.get("mechanism") or "",
                "region": d.get("region") or "", "target_metric": d.get("target_metric"),
                "parents": list(d.get("parents") or []),
            })
    return inst


# ─────────────────────────────────────────────────────────────────────────────
# 2. TERM DERIVATION -- from the driver's OWN authored text, never from its id
# ─────────────────────────────────────────────────────────────────────────────
def _ngrams(text, nmin=2, nmax=3):
    toks = re.findall(r"[a-z0-9]+", ex._normalize(text or ""))
    for n in range(nmin, nmax + 1):
        for i in range(len(toks) - n + 1):
            g = toks[i:i + n]
            if g[0] in STOP or g[-1] in STOP:
                continue
            if all(t in STOP for t in g):
                continue
            if any(len(t) <= 2 for t in g):
                continue
            yield " ".join(g)


def derive_terms(rows):
    """Candidate terms for one dark id, priority-ordered by which authored field produced them.

    evidence_query is FIRST on purpose: it is literally the retrieval query the DAG author wrote
    for this driver, so it is the highest-signal statement of what text would evidence it.
    """
    ranked = collections.OrderedDict()
    for field, prio in (("evidence_query", 0), ("blurb", 1), ("mechanism", 2), ("region", 3)):
        for r in rows:
            for g in _ngrams(r.get(field) or ""):
                if g not in ranked:
                    ranked[g] = {"term": g, "source_field": field, "priority": prio}
    return list(ranked.values())[:MAX_TERMS_PER_ID]


def _union_rx(terms):
    keys = sorted(set(terms), key=len, reverse=True)
    return re.compile(r"\b(" + "|".join(re.escape(k) for k in keys) + r")\b") if keys else None


def _prod_driver_rx():
    """The PRODUCTION driver matcher set, union-compiled.

    Exact pair from evidence_batch.rebuild_slices: ev.driver_matchers(). The union-regex form is
    the same optimization laneA_route.py verified equivalent against the full per-matcher loop on
    a 20,000-prop sample (0 mismatches): _Matcher.search(t) == m._rx.search(ex._normalize(t)), and
    an alternation answers "any hit" identically.
    """
    keys = set()
    for m, _co in ev.driver_matchers().values():   # (terms, co) pairs since the co_terms sitting; the
        keys.update(m._idx.keys())                 # any-hit union stays TERMS-only -- a co_term alone
        #                                            cannot route a prop, so including it would over-claim
    keys = sorted(keys, key=len, reverse=True)
    return re.compile(r"\b(" + "|".join(re.escape(k) for k in keys) + r")\b") if keys else None


# ─────────────────────────────────────────────────────────────────────────────
# 3. THE TWO CORPUS PASSES
# ─────────────────────────────────────────────────────────────────────────────
def _init(term_ids):
    global _RX, _TERM_IDS, _DRV_RX
    if _RX is None:
        _TERM_IDS = term_ids
        _RX = _union_rx(list(term_ids))
        _DRV_RX = _prod_driver_rx()


def phase_a(args):
    """Per-TERM corpus frequency. Feeds the G2 over-fire ceiling."""
    paths, term_ids = args
    _init(term_ids)
    hits = collections.Counter()
    n = 0
    for p in paths:
        for line in open(p, "rb"):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            n += 1
            if _RX is None:
                continue
            for h in set(_RX.findall(ex._normalize(r.get("text") or ""))):
                hits[h] += 1
    return {"hits": dict(hits), "n": n}


def phase_b(args):
    """Per-ID prop counts, split by driver-dark, + per-term mass, sources, verbatim samples."""
    paths, term_ids, anchored_map = args
    global _RX, _TERM_IDS, _DRV_RX, _ANCHORED
    _RX, _TERM_IDS, _DRV_RX = None, None, None
    _ANCHORED = {k: set(v) for k, v in anchored_map.items()}
    _init(term_ids)
    total = collections.Counter()
    dark = collections.Counter()
    per_term_dark = collections.Counter()      # (id, term) -> dark props, for G3 concentration
    anchored = collections.Counter()           # G5: dark props reached by an ANCHORED term
    src = collections.defaultdict(collections.Counter)
    samples = collections.defaultdict(list)
    n = n_dark = 0
    for p in paths:
        for line in open(p, "rb"):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            n += 1
            text = r.get("text") or ""
            nf = ex._normalize(text)
            is_dark = not (_DRV_RX and _DRV_RX.search(nf))
            if is_dark:
                n_dark += 1
            if _RX is None:
                continue
            hits = set(_RX.findall(nf))
            if not hits:
                continue
            ids = set()
            for h in hits:
                ids |= _TERM_IDS[h]
            for did in ids:                     # a prop counts ONCE per id
                total[did] += 1
                src[did][r.get("source") or "?"] += 1
                if is_dark:
                    dark[did] += 1
                    mine = sorted(h for h in hits if did in _TERM_IDS[h])
                    for t in mine:
                        per_term_dark[f"{did}\t{t}"] += 1
                    anc_hits = [t for t in mine if t in _ANCHORED.get(did, ())]
                    if anc_hits:
                        anchored[did] += 1
                        # SAMPLES COME FROM THE ANCHORED MASS ONLY. The samples ARE the vetting
                        # mechanism (G3) and the verdict is scored on anchored props, so drawing
                        # them from any-term matches showed the curator text that did not back
                        # the number -- `us_export_pace` illustrated by "Nigeria imports hard red
                        # winter wheat". A sample must be evidence for the count it sits under.
                        if len(samples[did]) < N_SAMPLES:
                            samples[did].append({
                                "text": text[:320], "source": r.get("source"),
                                "date": r.get("date"), "source_key": r.get("source_key"),
                                "matched_anchored_terms": anc_hits[:5],
                                "matched_terms": mine[:5],
                            })
    return {"total": dict(total), "dark": dict(dark), "n": n, "n_dark": n_dark,
            "per_term_dark": dict(per_term_dark), "anchored": dict(anchored),
            "src": {k: dict(v) for k, v in src.items()},
            "samples": {k: v for k, v in samples.items()}}


def run_pass(fn, files, term_ids, workers, extra=None):
    def _arg(chunk):
        return (chunk, term_ids) if extra is None else (chunk, term_ids, extra)
    if workers > 1:
        shards = [_arg(files[i::workers]) for i in range(workers)]
        with ProcessPoolExecutor(max_workers=workers) as pool:
            return list(pool.map(fn, shards))
    return [fn(_arg(files))]


# ─────────────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    all_ids, backed, dark_ids = dark_universe()
    inst = declared_instances()
    waivers = (yaml.safe_load((CFG / "driver_slices.yaml").read_text(encoding="utf-8"))
               or {}).get("waivers") or {}
    snap = json.loads((SCRATCH / "dec_p1_chunks_snapshot.json").read_text(encoding="utf-8"))

    print(f"driver ids {len(all_ids)} | backed {len(backed)} | DARK {len(dark_ids)}", flush=True)
    declared_dark = [d for d in dark_ids if d in inst]
    print(f"dark ids that are declared driver rows: {len(declared_dark)}", flush=True)

    # ---- terms + bindability -------------------------------------------------------------
    terms_by_id = {}
    bindable = {}
    for did in dark_ids:
        rows = inst.get(did, [])
        terms_by_id[did] = derive_terms(rows)
        avail = sorted({r["silver_ref"] for r in rows
                        if r.get("silver_status") == "available" and r.get("silver_ref")})
        bindable[did] = {
            "is_bindable": any(r.get("silver_status") == "available" for r in rows),
            "silver_refs_available": avail,
            "silver_statuses": sorted({r.get("silver_status") for r in rows
                                       if r.get("silver_status")}),
        }
    n_bindable = sum(1 for v in bindable.values() if v["is_bindable"])
    print(f"bindable (>=1 instance silver_status=available): {n_bindable}", flush=True)

    # ---- G4: token distinctiveness across the dark drivers' OWN authored text ---------------
    tok_df = collections.Counter()
    for did in dark_ids:
        toks = set()
        for r in inst.get(did, []):
            for f in ("evidence_query", "blurb", "mechanism", "region"):
                toks.update(re.findall(r"[a-z0-9]+", ex._normalize(r.get(f) or "")))
        for t in toks:
            tok_df[t] += 1
    df_cut = max(1, int(MAX_TOKEN_DRIVER_DF * len(dark_ids)))

    def distinctive(term):
        return any(tok_df.get(t, 0) <= df_cut for t in term.split())

    n_pre_g4 = sum(len(v) for v in terms_by_id.values())
    g4_dropped = collections.Counter()
    for did in list(terms_by_id):
        keep = []
        for t in terms_by_id[did]:
            if distinctive(t["term"]):
                keep.append(t)
            else:
                g4_dropped[t["term"]] += 1
        terms_by_id[did] = keep
    print(f"G4 token-distinctiveness: df_cut={df_cut} of {len(dark_ids)} dark drivers; "
          f"terms {n_pre_g4} -> {sum(len(v) for v in terms_by_id.values())} "
          f"({len(g4_dropped)} distinct terms refused as generic-among-drivers)", flush=True)
    for t, c in g4_dropped.most_common(12):
        print(f"   G4 DROP {t!r} (claimed by {c} drivers)")

    term_ids_all = collections.defaultdict(set)
    for did, ts in terms_by_id.items():
        for t in ts:
            term_ids_all[t["term"]].add(did)
    term_ids_all = {k: set(v) for k, v in term_ids_all.items()}
    print(f"candidate terms (post-G4, pre-G2): {len(term_ids_all)}", flush=True)

    # G2 CALIBRATION SET: every term driver_slices.yaml already accepts. Measured in the SAME
    # corpus pass as the candidates so the two frequencies are directly comparable. Filed under a
    # sentinel id so the phase-A counter picks them up without polluting any driver's mass.
    CAL = "\x00CALIBRATION"
    prod_terms = set()
    for m in ev.driver_matchers().values():
        prod_terms.update(m._idx.keys())
    prod_terms = {t for t in prod_terms if len(t.split()) >= MIN_TERM_TOKENS}
    probe = dict(term_ids_all)
    for t in prod_terms:
        probe.setdefault(t, set()).add(CAL)
    print(f"calibration terms (accepted, multi-token): {len(prod_terms)}", flush=True)

    files = sorted(glob.glob(str(CHUNKS / "*.jsonl")))
    if not files:
        sys.exit(f"no chunk files under {CHUNKS}")

    # ---- PHASE A: term frequency (candidates AND the calibration set) ---------------------
    # Cached: phase A is a pure function of (term set, corpus) and the corpus is pinned by the
    # snapshot. Guards get tuned by iteration -- and this instrument WAS re-tuned twice on what
    # its own samples showed -- so re-scanning 1.39M props for frequencies already measured is
    # pure waste. The cache keys on the exact term set and the corpus snapshot.
    cache_key = hashlib.sha256(
        (json.dumps(sorted(probe), ensure_ascii=False) + "|"
         + snap["newest_last_modified"] + "|" + str(snap["n_objects"])).encode("utf-8")
    ).hexdigest()[:16]
    cache_f = SCRATCH / f"dec_p1_dark_phaseA_{cache_key}.json"
    t0 = time.time()
    if cache_f.exists():
        _c = json.loads(cache_f.read_text(encoding="utf-8"))
        term_hits = collections.Counter(_c["hits"])
        n_props = _c["n"]
        print(f"phase A: REUSED cache {cache_f.name} ({n_props:,} props)", flush=True)
    else:
        parts = run_pass(phase_a, files, probe, args.workers)
        term_hits = collections.Counter()
        n_props = 0
        for p in parts:
            term_hits.update(p["hits"])
            n_props += p["n"]
        cache_f.write_text(json.dumps({"hits": dict(term_hits), "n": n_props}), encoding="utf-8")
        print(f"phase A: {n_props:,} props in {time.time()-t0:.0f}s", flush=True)

    # SUBSTRING CORRECTION -- without this the guard measures the wrong thing.
    # Phase A compiles ONE longest-first alternation over candidates + calibration terms, so at
    # any given position a longer term shadows a shorter one: `hard red winter` consumes the span
    # and `hard red` is never counted there. But Phase B runs a SMALLER regex (only surviving
    # terms), where those longer competitors may be gone and the short term then matches
    # everywhere. That mismatch let `hard red` look rare to G2 (under the 306 ceiling) and then
    # carry 53% of `us_export_pace`'s mass in the verdict pass -- a guard measuring one thing and
    # a verdict measuring another.
    # The fix is to score genericity by a term's INDEPENDENT reach: its own hits plus the hits of
    # every term that contains it. That is an upper bound on how often it could fire once its
    # competitors are removed, it is order-independent, and it errs toward calling a term generic
    # -- the safe direction for a guard. Computed offline from the same counts, no re-scan.
    _by_tok = collections.defaultdict(list)
    for t in term_hits:
        for tk in set(t.split()):
            _by_tok[tk].append(t)

    def _reach(t):
        pad = f" {t} "
        total = term_hits.get(t, 0)
        seen = set()
        for cand in _by_tok.get(t.split()[0], ()):
            if cand in seen or cand == t:
                continue
            seen.add(cand)
            if pad in f" {cand} ":
                total += term_hits.get(cand, 0)
        return total

    reach = {t: _reach(t) for t in set(term_hits) | set(probe)}

    # THE CEILING IS MEASURED, NOT CHOSEN: the CEILING_PCTL-th percentile of the independent reach
    # of terms the config ALREADY accepts. A candidate may not be vaguer than that.
    cal_freqs = sorted(reach.get(t, 0) for t in prod_terms)
    idx = max(0, min(len(cal_freqs) - 1, int(round(CEILING_PCTL / 100.0 * (len(cal_freqs) - 1)))))
    ceiling = cal_freqs[idx] if cal_freqs else 0
    cal_stats = {
        "n_calibration_terms": len(cal_freqs),
        "percentile": CEILING_PCTL,
        "ceiling_props": ceiling,
        "ceiling_share_of_corpus": round(ceiling / max(n_props, 1), 5),
        "calibration_median": cal_freqs[len(cal_freqs) // 2] if cal_freqs else 0,
        "calibration_max": cal_freqs[-1] if cal_freqs else 0,
        "scored_by": "independent reach (own hits + hits of every term containing it)",
        "most_generic_accepted_terms": [
            {"term": t, "corpus_reach": reach.get(t, 0)}
            for t in sorted(prod_terms, key=lambda x: -reach.get(x, 0))[:10]],
    }
    over_fire = sorted(((t, c) for t, c in ((t, reach.get(t, 0)) for t in term_ids_all)
                        if c > ceiling), key=lambda kv: -kv[1])
    kept = {t: ids for t, ids in term_ids_all.items() if reach.get(t, 0) <= ceiling}
    print(f"G2 ceiling = {ceiling:,} props (p{CEILING_PCTL} of {len(cal_freqs)} ACCEPTED terms; "
          f"median {cal_stats['calibration_median']:,}, max {cal_stats['calibration_max']:,})",
          flush=True)
    print(f"over-fire candidate terms dropped: {len(over_fire)} of {len(term_ids_all)}", flush=True)
    for t, c in over_fire[:15]:
        print(f"   DROP {t!r} {c:,}")

    # ---- G5 ANCHORING: which surviving terms are unmistakably THIS driver's ----------------
    # G2 and G4 decide whether a term is too vague to use. G5 asks the sharper question the
    # curation stage actually needs answered: does this driver have any term that NAMES IT --
    # one carrying a token that at most ANCHOR_MAX_DF dark drivers use at all (`conab`, `hessian`,
    # `vernalization`, `cecafe`)? A driver whose entire mass rides shared phrasing has corpus
    # text about its TOPIC, not evidence for itself, and authoring a slice off that would route
    # other drivers' props into it. FILLABLE therefore requires MEASURABLE_FLOOR props reached by
    # an anchored term, not merely by any surviving term.
    anchored_terms = {}
    for did in dark_ids:
        ks = [t["term"] for t in terms_by_id[did] if t["term"] in kept]
        anchored_terms[did] = sorted(
            t for t in ks if any(tok_df.get(tk, 99) <= ANCHOR_MAX_DF for tk in t.split()))
    n_with_anchor = sum(1 for v in anchored_terms.values() if v)
    print(f"G5 anchoring: {n_with_anchor} of {len(dark_ids)} dark ids have >=1 anchored term "
          f"(token used by <= {ANCHOR_MAX_DF} dark drivers)", flush=True)

    # ---- PHASE B: per-id counts over surviving terms --------------------------------------
    t0 = time.time()
    parts = run_pass(phase_b, files, kept, args.workers, extra=anchored_terms)
    total = collections.Counter()
    darkc = collections.Counter()
    per_term = collections.Counter()
    anchoredc = collections.Counter()
    src = collections.defaultdict(collections.Counter)
    samples = collections.defaultdict(list)
    n2 = n_dark_props = 0
    for p in parts:
        total.update(p["total"])
        darkc.update(p["dark"])
        per_term.update(p["per_term_dark"])
        anchoredc.update(p["anchored"])
        n2 += p["n"]
        n_dark_props += p["n_dark"]
        for k, v in p["src"].items():
            src[k].update(v)
        for k, v in p["samples"].items():
            for s in v:
                if len(samples[k]) < N_SAMPLES:
                    samples[k].append(s)
    print(f"phase B: {n2:,} props in {time.time()-t0:.0f}s | driver-dark props "
          f"{n_dark_props:,} ({100.0*n_dark_props/max(n2,1):.1f}%)", flush=True)

    # per-id term mass, for the G3 concentration check
    by_id_terms = collections.defaultdict(collections.Counter)
    for k, v in per_term.items():
        did, t = k.split("\t", 1)
        by_id_terms[did][t] = v

    # ---- VERDICTS -------------------------------------------------------------------------
    rows = []
    for did in dark_ids:
        kept_terms = [t for t in terms_by_id[did] if t["term"] in kept]
        dropped = [t["term"] for t in terms_by_id[did] if t["term"] not in kept]
        dk = darkc.get(did, 0)
        tm = by_id_terms.get(did, collections.Counter())
        top_term, top_n = (tm.most_common(1)[0] if tm else (None, 0))
        conc = round(top_n / dk, 3) if dk else 0.0
        # G3: mass carried by ONE term is an artefact of that term, not evidence for the driver.
        anc = anchoredc.get(did, 0)
        concentrated = bool(dk >= MEASURABLE_FLOOR and conc > MAX_CONCENTRATION)
        # G5: the floor is applied to ANCHORED mass, not total mass.
        fillable = anc >= MEASURABLE_FLOOR and not concentrated
        b = bindable[did]
        verdict = ("FILLABLE-BY-TERM" if fillable else
                   "BINDABLE" if b["is_bindable"] else "HONEST-WAIVE")
        why = ("%d driver-dark props reached by %d ANCHORED terms (%s) out of %d total dark props "
               "across %d vetted terms; top term `%s` carries %.0f%%, under the %.0f%% limit"
               % (anc, len(anchored_terms[did]),
                  ", ".join("`%s`" % t for t in anchored_terms[did][:4]), dk,
                  len(kept_terms), top_term, 100 * conc, 100 * MAX_CONCENTRATION)) if fillable else (
              ("%d driver-dark props but %.0f%% of them come from the single term `%s` -- that is "
               "evidence about the term, not about this driver; %s"
               % (dk, 100 * conc, top_term,
                  ("bind it instead (silver_status: available on %s)"
                   % (",".join(b["silver_refs_available"]) or "an unnamed ref"))
                  if b["is_bindable"] else "re-derive terms before authoring anything")
               ) if concentrated else
              ("silver_status: available on %s -- the NUMBER exists; only %d of its %d driver-dark "
               "props are reached by a term that NAMES this driver (%d anchored terms), below the "
               "%d floor, so text alone will not back it"
               % (",".join(b["silver_refs_available"]) or "an unnamed ref", anc, dk,
                  len(anchored_terms[did]), MEASURABLE_FLOOR))
              if b["is_bindable"] else
              ("neither axis: %d anchored driver-dark props of %d total (floor %d, %d anchored "
               "terms) and no instance carries silver_status: available (statuses: %s). "
               "Keep the waiver."
               % (anc, dk, MEASURABLE_FLOOR, len(anchored_terms[did]),
                  ",".join(b["silver_statuses"]) or "none declared")))
        rows.append({
            "driver_id": did,
            "verdict": verdict,
            "why": why,
            "fillable_by_term": fillable,
            "bindable_now": b["is_bindable"],
            "concentration_risk": concentrated,
            "props_driver_dark_anchored": anc,
            "anchored_terms": anchored_terms[did],
            "n_anchored_terms": len(anchored_terms[did]),
            "top_term": top_term,
            "top_term_dark_props": top_n,
            "top_term_share_of_dark": conc,
            "dark_props_by_term": dict(tm.most_common(12)),
            "props_matching_terms": total.get(did, 0),
            "props_driver_dark": dk,
            "n_declared_instances": len(inst.get(did, [])),
            "contracts": sorted({r["contract"] for r in inst.get(did, [])}),
            "silver_refs_available": b["silver_refs_available"],
            "silver_statuses": b["silver_statuses"],
            "n_terms_kept": len(kept_terms),
            "terms_kept": [t["term"] for t in kept_terms],
            "terms_by_source_field": collections.Counter(
                t["source_field"] for t in kept_terms),
            "terms_dropped_as_overfire": dropped,
            "top_sources": dict(collections.Counter(src.get(did, {})).most_common(5)),
            "waiver": waivers.get(did) if isinstance(waivers, dict) else None,
            "verbatim_samples": samples.get(did, []),
        })
    rows.sort(key=lambda r: (-r["props_driver_dark_anchored"], -r["props_driver_dark"],
                             r["driver_id"]))
    for r in rows:
        r["terms_by_source_field"] = dict(r["terms_by_source_field"])

    vc = collections.Counter(r["verdict"] for r in rows)
    matrix = collections.Counter(
        (r["fillable_by_term"], r["bindable_now"]) for r in rows)

    doc = {
        "artifact": "dark_driver_fillability",
        "run": "dec_p1_x2",
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "question": "for each dark DAG driver id: author terms, bind a silver table, or waive "
                    "honestly -- decided by measurement on all three axes",
        "method": {
            "universe": "sorted(set(display.all_driver_ids()) - set(evidence.driver_alias())), "
                        "derived in-process; e1_census --local-only was REFUSED as the route "
                        "because e1_census.slice_census():233 GETs + json.loads every one of the "
                        "120 vector-bearing driver slices (3.76 GB) and that transport already "
                        "failed at DEC-P0 over this link",
            "term_derivation": "per dark id, 2-3-token n-grams from its OWN authored fields in "
                               "priority order evidence_query > blurb > mechanism > region. THE "
                               "ID IS NEVER A TERM: the scout measured id-as-term over the pre-X2 "
                               "cache and 84/123 scored zero while the top scorers were generic "
                               "over-fires (area 21,753 / consumption 20,662 / stock 1,181 / "
                               "flowering 371 / phytosanitary 331)",
            "guards": {
                "G1_multi_token_only": MIN_TERM_TOKENS,
                "G2_ceiling_calibration": cal_stats,
                "G2_note": ("the ceiling is MEASURED from driver_slices.yaml's own accepted terms, "
                            "not chosen. A first version used a flat 1%-of-corpus ceiling; it "
                            "dropped only 8 terms and let `coffee production` / `sugar production` "
                            "/ `palm oil` / `price sensitive` through, which then carried most of "
                            "the mass -- IOD_negative was scoring on 'Sugar production for "
                            "Australia'. The G3 samples caught it, which is the whole reason "
                            "samples are mandatory."),
                "G4_max_token_driver_df": MAX_TOKEN_DRIVER_DF,
                "G4_df_cut_drivers": df_cut,
                "G4_terms_refused_as_generic_among_drivers": len(g4_dropped),
                "G4_top_refusals": [{"term": t, "claimed_by_n_drivers": c}
                                    for t, c in g4_dropped.most_common(25)],
                "G5_anchor_max_driver_df": ANCHOR_MAX_DF,
                "G5_ids_with_an_anchored_term": n_with_anchor,
                "G5_note": ("FILLABLE is scored on ANCHORED dark props -- props reached by a term "
                            "carrying a token at most %d dark drivers use at all. A driver whose "
                            "mass rides only shared phrasing has corpus text about its TOPIC, not "
                            "evidence for ITSELF, and a slice authored off that would route other "
                            "drivers' props into it." % ANCHOR_MAX_DF),
                "G3_max_single_term_share": MAX_CONCENTRATION,
                "G3_verbatim_samples_per_id": N_SAMPLES,
            },
            "driver_dark_test": "a prop is DRIVER-DARK when no production driver matcher fires: "
                                "ev.driver_matchers(), the exact pair evidence_batch."
                                "rebuild_slices uses, union-compiled (laneA_route.py verified the "
                                "union equivalent to the full per-matcher loop, 0/20,000 mismatches)",
            "dedup": "a prop matching several terms of one id counts ONCE for that id",
            "measurable_floor": MEASURABLE_FLOOR,
            "corpus": f"graphrag_evidence/chunks/*.jsonl only -- {snap['n_objects']:,} objects, "
                      f"{snap['total_bytes']:,} bytes, {n2:,} props",
            "corpus_snapshot": snap,
        },
        "headline": {
            "driver_ids_total": len(all_ids),
            "driver_ids_backed": len(backed),
            "driver_ids_dark": len(dark_ids),
            "dark_ids_declared_as_driver_rows": len(declared_dark),
            "props_scanned": n2,
            "props_driver_dark": n_dark_props,
            "props_driver_dark_pct": round(100.0 * n_dark_props / max(n2, 1), 2),
            "candidate_terms_pre_g4": n_pre_g4,
            "candidate_terms_pre_guard": len(term_ids_all),
            "candidate_terms_kept": len(kept),
            "overfire_terms_dropped": len(over_fire),
            "ids_flagged_concentration_risk": sum(1 for r in rows if r["concentration_risk"]),
            "verdicts": dict(vc),
            "verdict_matrix_fillable_x_bindable": {
                f"fillable={k[0]},bindable={k[1]}": v for k, v in sorted(matrix.items())},
        },
        "overfire_terms_dropped_detail": [{"term": t, "corpus_props": c} for t, c in over_fire],
        "ids": rows,
    }
    (OUT / "dark_driver_fillability.json").write_text(
        json.dumps(doc, indent=1, ensure_ascii=True), encoding="utf-8")

    # ---- md -------------------------------------------------------------------------------
    L = []
    A = L.append
    A("# Dark-driver fillability census (dec_p1, X2 corpus) -- %s" % doc["generated_utc"])
    A("")
    A("Artifact: `data/dec_p1/dark_driver_fillability.json`. Corpus: "
      "%s chunk objects / %s props, driver-dark %s (%.1f%%)."
      % (f"{snap['n_objects']:,}", f"{n2:,}", f"{n_dark_props:,}",
         100.0 * n_dark_props / max(n2, 1)))
    A("")
    A("**The question.** %s" % doc["question"])
    A("")
    A("**Terms are NOT ids.** Derived from each driver's own `evidence_query` / `blurb` / "
      "`mechanism` / `region`, >=%d tokens. The genericity ceiling is MEASURED, not chosen: it is "
      "the p%d corpus frequency of the %d multi-token terms `driver_slices.yaml` ALREADY accepts "
      "(median %s props, max %s), i.e. **%s props** -- a new term may not be vaguer than the "
      "vaguest term the product already lives with. %d of %d candidate terms were dropped that "
      "way. A further %d ids are flagged `concentration_risk` (>%.0f%% of their mass on one term) "
      "and are withheld from FILLABLE."
      % (MIN_TERM_TOKENS, CEILING_PCTL, cal_stats["n_calibration_terms"],
         f"{cal_stats['calibration_median']:,}", f"{cal_stats['calibration_max']:,}",
         f"{ceiling:,}", len(over_fire), len(term_ids_all),
         sum(1 for r in rows if r["concentration_risk"]), MAX_CONCENTRATION * 100))
    A("")
    A("| verdict | n |")
    A("|---|---:|")
    for k, v in vc.most_common():
        A("| %s | %d |" % (k, v))
    A("")
    A("The two axes are orthogonal -- cross-tab:")
    A("")
    A("| fillable_by_term | bindable_now | n |")
    A("|---|---|---:|")
    for (f, b), v in sorted(matrix.items()):
        A("| %s | %s | %d |" % (f, b, v))
    A("")
    A("## Every dark id, ranked by driver-dark prop mass")
    A("")
    A("| driver_id | verdict | anchored props | all dark props | anchored terms | top term | share | silver refs |")
    A("|---|---|---:|---:|---:|---|---:|---|")
    for r in rows:
        A("| `%s` | %s | %d | %d | %d | %s | %.0f%% | %s |" % (
            r["driver_id"], r["verdict"], r["props_driver_dark_anchored"],
            r["props_driver_dark"], r["n_anchored_terms"],
            ("`%s`" % r["top_term"]) if r["top_term"] else "-",
            100 * r["top_term_share_of_dark"],
            ", ".join(r["silver_refs_available"][:2]) or "-"))
    A("")
    A("## FILLABLE-BY-TERM, with the verbatim text that says so")
    A("")
    for r in rows:
        if r["verdict"] != "FILLABLE-BY-TERM":
            continue
        A("### `%s` -- %d ANCHORED driver-dark props (of %d total)"
          % (r["driver_id"], r["props_driver_dark_anchored"], r["props_driver_dark"]))
        A("")
        A("- **anchored terms (%d)**: %s" % (r["n_anchored_terms"],
                                             ", ".join("`%s`" % t for t in r["anchored_terms"])))
        A("- all terms kept (%d): %s" % (r["n_terms_kept"],
                                         ", ".join("`%s`" % t for t in r["terms_kept"][:12])))
        A("- dark props by term: %s" % json.dumps(r["dark_props_by_term"]))
        A("- top sources: %s" % json.dumps(r["top_sources"]))
        if r["terms_dropped_as_overfire"]:
            A("- dropped as over-fire: %s"
              % ", ".join("`%s`" % t for t in r["terms_dropped_as_overfire"][:8]))
        A("")
        for s in r["verbatim_samples"]:
            A("  > %s _(%s, %s; matched %s)_" % (
                s["text"].replace("\n", " ")[:300], s["source"], s["date"],
                ", ".join("`%s`" % t for t in s["matched_terms"])))
            A("")
    A("## Flagged `concentration_risk` -- a count that is about a term, not a driver")
    A("")
    A("These cleared the %d-prop floor but more than %.0f%% of the mass sits on ONE term. That is "
      "the failure mode this instrument was rebuilt to catch; they are NOT authorable as they "
      "stand." % (MEASURABLE_FLOOR, MAX_CONCENTRATION * 100))
    A("")
    A("| driver_id | dark props | top term | share | verdict |")
    A("|---|---:|---|---:|---|")
    for r in rows:
        if r["concentration_risk"]:
            A("| `%s` | %d | `%s` | %.0f%% | %s |" % (r["driver_id"], r["props_driver_dark"],
                                                      r["top_term"],
                                                      100 * r["top_term_share_of_dark"],
                                                      r["verdict"]))
    A("")
    A("## HONEST-WAIVE -- neither axis carries them")
    A("")
    A("| driver_id | dark props | silver statuses | why |")
    A("|---|---:|---|---|")
    for r in rows:
        if r["verdict"] == "HONEST-WAIVE":
            A("| `%s` | %d | %s | %s |" % (r["driver_id"], r["props_driver_dark"],
                                           ", ".join(r["silver_statuses"]) or "none", r["why"]))
    (OUT / "dark_driver_fillability.md").write_text("\n".join(L) + "\n", encoding="utf-8")

    print()
    print("VERDICTS", dict(vc))
    print("MATRIX  ", {f"fillable={k[0]},bindable={k[1]}": v for k, v in sorted(matrix.items())})
    print("wrote", OUT / "dark_driver_fillability.json")


if __name__ == "__main__":
    main()
