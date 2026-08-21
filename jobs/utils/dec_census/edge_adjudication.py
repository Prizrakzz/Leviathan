"""EDGE ADJUDICATION -- the wave's decision record (D-EC graph-completion, stage 2).

THE TWO HALVES. `data/dec_p1/graph_walk.json` asks the QUESTION -- 130 node pairs that are
structurally adjacent (shared hierarchy group/complex, shared neighbours, shared driver slices)
but carry no edge. It is a PURE FUNCTION OF THE CONFIG and does not move when the corpus doubles.
`data/dec_p1/edge_evidence.json` (this run's co-mention pass over 1,387,697 props) ANSWERS it from
text. This instrument joins them, adds every edge the plan's F-A itemization names by hand
(docs/private/EVIDENCE_CORPUS_RECON_PLAN.md:488-600), and applies ONE written rule to all of them.

THE RULE IS WRITTEN DOWN BEFORE FIRING so the wave cannot rationalize after the fact. Verdicts, in
strict precedence order:

  WAIVE-UNMEASURABLE   either endpoint is below MEASURABLE_FLOOR (100) corpus mentions -- or is not
                       in the vocabulary at all. This is a verdict about THE INSTRUMENT, never
                       about the edge. The honest fix is vocabulary, not an edge.
  REFUSE               measurable and co-mentioned, but the endpoints appear together LESS than
                       chance (npmi <= 0 AND lift < 1.0). barley~wheat is the caution row: 903 prop
                       co-mentions at DEC-P0 but lift 0.72 / npmi -0.054. That is an argument about
                       what the edge would MEAN, not a licence to author it.
  AUTHOR               co_mentions_prop >= AUTHOR_FLOOR (60) AND (npmi > 0 OR lift > 1.5) AND NOT
                       shared_surface_form. The 60 floor is dec_p0_rank.py:105's own npmi floor.
                       shared_surface_form is excluded because it is one string firing twice.
  AUTHOR-ON-STRUCTURE  corpus-silent or thin, but the pair is a PHYSICAL IDENTITY or a declared
                       complex member whose slice fingerprints nearly coincide. palm_oil~palm_olein
                       is exactly this: co-occurrence 0, Jaccard 0.741, and graph_walk.md calls it
                       "the only complex whose relationship is a physical identity" (olein is the
                       liquid fraction of CPO). A zero co-mention MUST NOT veto it -- but the
                       reason goes in the edge's mechanism text, not in a silence.
  REFUSE-INSUFFICIENT  measurable, below the author floor, and with no structural claim to stand on.

Thresholds are the STANDING ones, reused verbatim so the delta is a delta: MEASURABLE_FLOOR=100
and ZERO_BAND=2 (dec_p0_rank.py:25-26), the >=60 co-mention floor before npmi ranking (:105).

Output: data/dec_p1/edge_adjudication.{md,json}. Reads only; decides nothing on its own authority.
"""
from __future__ import annotations

import collections
import json
import math
import re
import time
import unicodedata
from pathlib import Path

REPO = Path("C:/Users/User/Desktop/Leviathan")
OUT = REPO / "data" / "dec_p1"
SCRATCH = Path(r"C:/Users/User/AppData/Local/Temp/claude/"
               r"C--Users-User-Desktop-Leviathan/360a169c-9409-4bdb-af00-a02392ed35a2/scratchpad")

MEASURABLE_FLOOR = 100          # dec_p0_rank.py:25
ZERO_BAND = 2                   # dec_p0_rank.py:26
AUTHOR_FLOOR = 60               # dec_p0_rank.py:105 -- the co-mention floor before npmi ranking
LIFT_AUTHOR = 1.5
STRUCT_JACCARD = 0.50           # slice-fingerprint overlap that makes a corpus silence forgivable

# ── The plan's F-A itemization, transcribed. (item, label, [(a, b), ...]) ────────────────────
F_A = [
    ("A", "livestock demand layer", [
        ("cattle_cycle_herd_size", "cattle_beef"), ("cattle_beef", "broilers_poultry"),
        ("broilers_poultry", "livestock_feed_demand"),
        ("livestock_feed_demand", "soybean_meal"), ("livestock_feed_demand", "corn"),
        ("livestock_feed_demand", "ddgs"), ("dairy", "livestock_feed_demand")]),
    ("B", "lauric complex", [
        ("coconut", "palm_kernel"), ("palm_kernel", "palm_oil"),
        ("coconut_oil", "palm_kernel_oil")]),
    ("C", "cotton crush", [
        ("cotton", "cottonseed"), ("cottonseed_meal", "soybean_meal"),
        ("cottonseed_oil", "soybean_oil")]),
    ("D", "peanut complex", [
        ("peanut", "soybeans"), ("peanut", "cotton"), ("peanut_oil", "soybean_oil")]),
    ("E", "rapeseed crush chain", [
        ("rapeseed", "rapeseed_oil"), ("rapeseed", "rapeseed_meal"), ("canola", "rapeseed"),
        ("rapeseed_meal", "soybean_meal"), ("rapeseed_oil", "soybean_oil")]),
    ("F", "wheat class spreads", [
        ("french_wheat", "hrw_wheat"), ("french_wheat", "hrs_wheat"),
        ("hrw_wheat", "hrs_wheat"), ("hrw_wheat", "srw_wheat"), ("hrs_wheat", "srw_wheat")]),
    ("G", "ethanol edges", [
        ("corn", "ethanol"), ("ethanol", "ddgs")]),
    ("H", "RD feedstock stack", [
        ("used_cooking_oil", "soybean_oil"), ("tallow", "soybean_oil"),
        ("used_cooking_oil", "tallow")]),
    ("I", "HFCS bridge", [
        ("hfcs", "corn"), ("hfcs", "raw_sugar"), ("hfcs", "white_sugar")]),
    ("J", "fresh citrus diversion", [
        ("fresh_citrus", "orange_juice")]),
    ("K", "MARA meal basket", [
        ("rapeseed_meal", "soybean_meal"), ("cottonseed_meal", "soybean_meal"),
        ("peanut_meal", "soybean_meal"), ("sunflower_meal", "soybean_meal"),
        ("palm_kernel_meal", "soybean_meal"), ("ddgs", "soybean_meal"),
        ("flaxseed_meal", "soybean_meal"), ("sesame_meal", "soybean_meal")]),
    ("L", "class DAG blockers", [
        ("barley", "wheat"), ("sorghum", "corn"), ("barley", "corn"),
        ("sunflower_oil", "soybean_oil"), ("sunflower_oil", "palm_oil")]),
]


def norm(s):
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower().replace("'", "")
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


# ── inputs ───────────────────────────────────────────────────────────────────────────────────
model = json.loads((SCRATCH / "dec_p1_model.json").read_text(encoding="utf-8"))
cm = json.loads((SCRATCH / "dec_p1_comention.json").read_text(encoding="utf-8"))
# THE PRE-X2 BASELINE, raw. dec_p0/edge_evidence.json only serialized top-N tables, so absence
# from it is truncation, NOT a zero -- the raw counter file is the only honest comparison.
p0 = json.loads((SCRATCH / "dec_p0_comention.json").read_text(encoding="utf-8"))
p0_model = json.loads((SCRATCH / "dec_p0_model.json").read_text(encoding="utf-8"))
P0_ENT = set(p0_model["entities"])
P0_SOLO = collections.Counter(p0["solo"])
P0_PAIR = collections.Counter({tuple(k.split("|")): v for k, v in p0["pair"].items()})
P0_N = p0["n_unique_chunks"]
gw = json.loads((OUT / "graph_walk.json").read_text(encoding="utf-8"))
ee = json.loads((OUT / "edge_evidence.json").read_text(encoding="utf-8"))

ENT, EDGES = model["entities"], model["edges"]
solo = collections.Counter(cm["solo"])
dsolo = collections.Counter(cm["doc_solo"])
pair = collections.Counter({tuple(k.split("|")): v for k, v in cm["pair"].items()})
dpair = collections.Counter({tuple(k.split("|")): v for k, v in cm["doc_pair"].items()})
N = cm["n_unique_chunks"]
BLOCK = set(cm["blocked_forms"])

nf = {e: {f for f in (re.sub(r"[\s_\-]+", " ",
                             unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
                             ).strip().lower() for s in ENT[e]["surfaces"])
          if f and len(f) > 1 and f not in BLOCK} for e in ENT}

existing = set()
for e in EDGES:
    if e["src"] and e["dst"] and e["src"] != e["dst"]:
        existing.add(tuple(sorted((e["src"], e["dst"]))))

# structural context per node pair, straight from graph_walk's own candidate rows
struct = {}
for r in gw["missing_edge_candidates"]:
    struct[tuple(sorted((norm(r["a"]), norm(r["b"]))))] = r


def resolve(name):
    """(entity_id, how). `how` matters: a name that resolves only through a SURFACE FOLD is not
    the same thing as the name asked for -- e.g. `sunflower_meal` has no entity of its own and
    folds into the `protein_meal_substitution` slice, so a row labelled sunflower_meal would
    silently be measuring a different, broader entity. Recorded rather than hidden."""
    n = norm(name)
    if n in ENT:
        return n, "exact"
    for eid, meta in ENT.items():          # try a surface-form match
        if n in {norm(s) for s in meta["surfaces"]}:
            return eid, "surface_fold"
    return None, "unresolved"


def npmi(a, b, c):
    if not solo[a] or not solo[b] or not c:
        return None
    pxy = c / N
    return round(math.log(pxy / ((solo[a] / N) * (solo[b] / N))) / (-math.log(pxy)), 3)


def p0_delta(a, b):
    """The pre-X2 read of the same pair, WITH the reason any movement happened.

    This is the run book's risk #5 made explicit. 29 entities entered the vocabulary between
    DEC-P0 and now (coconut, palm_kernel, hfcs, fresh_citrus, ddgs, tallow, used_cooking_oil,
    cottonseed, peanut, the fx family ...). For those, a DEC-P0 count of 0 means THE ENTITY HAD
    NO SURFACE FORMS -- not that the text was silent. Reporting such a pair as "0 -> 469, the
    corpus doubling fed it" would be measuring two config vintages and calling it a corpus result.
    So every delta is attributed:
      vocabulary  at least one endpoint did not exist / had no forms at DEC-P0 -> the move is a
                  CONFIG delta and says nothing about X2
      corpus      both endpoints were measurable at DEC-P0 -> the move IS the corpus
    Note also that DEC-P0's N (396,693) included the stale _raw/ leg this run drops, so raw counts
    are not subtractable; lift and npmi are the comparable quantities.
    """
    known = (a in P0_ENT and P0_SOLO[a] > 0, b in P0_ENT and P0_SOLO[b] > 0)
    c0 = P0_PAIR.get((a, b) if a <= b else (b, a), 0)
    e0 = P0_SOLO[a] * P0_SOLO[b] / P0_N if P0_N else 0
    return {
        "p0_co_mentions_prop": c0,
        "p0_a_mentions": P0_SOLO[a], "p0_b_mentions": P0_SOLO[b],
        "p0_expected_prop_if_independent": round(e0, 1),
        "p0_lift": round(c0 / e0, 2) if e0 else None,
        "delta_attribution": "corpus" if all(known) else "vocabulary",
        "endpoints_new_since_dec_p0": [x for x, k in ((a, known[0]), (b, known[1])) if not k],
    }


def measure(a_raw, b_raw):
    (a, how_a), (b, how_b) = resolve(a_raw), resolve(b_raw)
    if a is None or b is None:
        return {"a_raw": a_raw, "b_raw": b_raw, "a": a, "b": b, "resolved": False,
                "missing_endpoints": [x for x, r in ((a_raw, a), (b_raw, b)) if r is None]}
    if a > b:
        a, b, how_a, how_b = b, a, how_b, how_a
    c = pair.get((a, b), 0)
    dc = dpair.get((a, b), 0)
    exp = solo[a] * solo[b] / N if N else 0
    shared = bool(nf.get(a) and nf.get(b) and (nf[a] & nf[b]))
    nested = (not shared and nf.get(a) and nf.get(b)
              and any(f" {x} " in f" {y} " or f" {y} " in f" {x} "
                      for x in nf[a] for y in nf[b]))
    st = struct.get((a, b)) or struct.get(tuple(sorted((norm(a_raw), norm(b_raw))))) or {}
    out = {
        "a_raw": a_raw, "b_raw": b_raw, "a": a, "b": b, "resolved": True,
        "resolved_via": {"a": how_a, "b": how_b},
        "resolution_is_a_fold": (how_a == "surface_fold" or how_b == "surface_fold"),
        "already_edged": (a, b) in existing,
        "co_mentions_prop": c, "co_mentions_doc": dc,
        "a_mentions": solo[a], "b_mentions": solo[b],
        "a_docs": dsolo[a], "b_docs": dsolo[b],
        "expected_prop_if_independent": round(exp, 1),
        "lift": round(c / exp, 2) if exp else None,
        "npmi": npmi(a, b, c),
        "cond_support": round(c / min(solo[a], solo[b]), 4) if min(solo[a], solo[b]) else None,
        "shared_surface_form": shared, "nested_surface_form": bool(nested),
        "struct_score": st.get("score"), "shared_groups": st.get("shared_groups") or [],
        "common_neighbors": st.get("common_neighbors"),
        "shared_driver_slices": st.get("shared_driver_slices"),
        "slice_jaccard": st.get("slice_jaccard"),
    }
    out.update(p0_delta(a, b))
    return out


def adjudicate(r):
    """THE RULE. Precedence order is the docstring's, top to bottom."""
    if not r["resolved"]:
        return ("WAIVE-UNMEASURABLE",
                "endpoint not in the vocabulary at all (%s) -- the node must be authored before "
                "any edge on it can be measured; this is a verdict about the instrument"
                % ", ".join(r["missing_endpoints"]))
    lo = min(r["a_mentions"], r["b_mentions"])
    if lo < MEASURABLE_FLOOR:
        thin = [f"{e}={solo[e]}" for e in (r["a"], r["b"]) if solo[e] < MEASURABLE_FLOOR]
        return ("WAIVE-UNMEASURABLE",
                "endpoint below the %d-mention measurable floor (%s). We cannot measure this; the "
                "honest fix is vocabulary, not an edge." % (MEASURABLE_FLOOR, ", ".join(thin)))
    c, lift, np_ = r["co_mentions_prop"], r["lift"], r["npmi"]
    groups = r["shared_groups"]
    jac = r["slice_jaccard"] or 0.0
    is_complex = any(str(g).startswith("complex:") for g in groups)
    if c >= AUTHOR_FLOOR and (np_ is not None and np_ <= 0) and (lift is not None and lift < 1.0):
        return ("REFUSE",
                "co-mentioned %d times but lift %.2f / npmi %.3f -- the two appear together LESS "
                "than chance. That is an argument about what the edge would mean, not a licence."
                % (c, lift, np_))
    if c >= AUTHOR_FLOOR and ((np_ is not None and np_ > 0) or (lift is not None and lift > LIFT_AUTHOR)) \
            and not r["shared_surface_form"]:
        return ("AUTHOR",
                "%d prop co-mentions (%d doc), lift %s, npmi %s -- clears the >=%d floor with "
                "positive association and no shared surface form."
                % (c, r["co_mentions_doc"], lift, np_, AUTHOR_FLOOR))
    if is_complex and jac >= STRUCT_JACCARD:
        return ("AUTHOR-ON-STRUCTURE",
                "corpus reads %d prop co-mentions, but the pair is a declared complex member "
                "(%s) with slice Jaccard %.3f -- a physical-identity / same-complex relationship "
                "the text never states in one sentence. The zero must not veto it; the reason "
                "belongs in the edge's mechanism text."
                % (c, ", ".join(groups), jac))
    if r["shared_surface_form"]:
        return ("REFUSE-INSUFFICIENT",
                "%d co-mentions but shared_surface_form: the two entities share a normalized form, "
                "so this is ONE string firing twice, not evidence of a relationship." % c)
    return ("REFUSE-INSUFFICIENT",
            "measurable (min endpoint %d mentions) but only %d prop co-mentions -- below the >=%d "
            "author floor, and no complex/identity claim to stand on (Jaccard %.3f)."
            % (lo, c, AUTHOR_FLOOR, jac))


# ── (1) the F-A named edges ──────────────────────────────────────────────────────────────────
fa_rows = []
for item, label, pairs in F_A:
    for a, b in pairs:
        r = measure(a, b)
        v, why = adjudicate(r)
        r.update({"fa_item": item, "fa_label": label, "verdict": v, "why": why})
        fa_rows.append(r)

# ── (2) the 130 structural candidates ────────────────────────────────────────────────────────
st_rows = []
for cand in gw["missing_edge_candidates"]:
    r = measure(cand["a"], cand["b"])
    r["struct_score"] = cand["score"]
    r["shared_groups"] = cand["shared_groups"]
    r["common_neighbors"] = cand["common_neighbors"]
    r["shared_driver_slices"] = cand["shared_driver_slices"]
    r["slice_jaccard"] = cand["slice_jaccard"]
    r["dag_neighborhood_cooccurrence"] = cand["dag_neighborhood_cooccurrence"]
    v, why = adjudicate(r)
    r.update({"verdict": v, "why": why})
    st_rows.append(r)

fa_v = collections.Counter(r["verdict"] for r in fa_rows)
st_v = collections.Counter(r["verdict"] for r in st_rows)
all_v = fa_v + st_v

# ── (3) NEAR MISSES -- disclosure, NOT a rule change ─────────────────────────────────────────
# The >=60 floor is the INSTRUMENT's, not a fact about these pairs. Rows that sit just under it
# while being strongly positively associated are exactly where a curator should look first, and
# burying them inside a REFUSE-INSUFFICIENT bucket would be the kind of silence this wave exists
# to stop. The rule above is untouched; these rows keep their verdict and are merely surfaced.
NEAR_MIN, NEAR_LIFT = 20, 2.0


def _dedupe(rows):
    """A pair can be BOTH an F-A named edge and a structural candidate. These cross-cut tables
    describe pairs, not list memberships, so a pair appears once (the F-A row wins -- it carries
    the item label)."""
    seen, out = set(), []
    for r in rows:
        k = (r.get("a"), r.get("b"))
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out


near = sorted(_dedupe(
    [r for r in (fa_rows + st_rows)
     if r.get("resolved") and r["verdict"] == "REFUSE-INSUFFICIENT"
     and NEAR_MIN <= r["co_mentions_prop"] < AUTHOR_FLOOR
     and (r["lift"] or 0) > NEAR_LIFT and not r["shared_surface_form"]]),
    key=lambda r: -(r["lift"] or 0))

# ── (4) WHAT X2 ACTUALLY FED -- only pairs whose delta is attributable to the corpus ─────────
corpus_fed = sorted(_dedupe(
    [r for r in (fa_rows + st_rows)
     if r.get("resolved") and r["delta_attribution"] == "corpus"
     and r["co_mentions_prop"] > r["p0_co_mentions_prop"]]),
    key=lambda r: -(r["co_mentions_prop"] - r["p0_co_mentions_prop"]))
vocab_fed = sorted(_dedupe(
    [r for r in (fa_rows + st_rows)
     if r.get("resolved") and r["delta_attribution"] == "vocabulary"
     and r["co_mentions_prop"] >= AUTHOR_FLOOR]),
    key=lambda r: -r["co_mentions_prop"])
folds = _dedupe([r for r in (fa_rows + st_rows) if r.get("resolution_is_a_fold")])

# ── (5) THE ONE CLEAN X2 NUMBER: verdict migration on the pairs BOTH vintages share ──────────
# Every other delta in this wave is confounded by the 29 new vocabulary entities. This one is not:
# it re-classifies the SAME 979 endpoint pairs under the SAME rule against the two corpora, so the
# only thing that moved is the text. (It moved DOWNWARD in corpus size for the _raw leg, which
# this run drops -- so the improvement is a lower bound.)
_RANK = {"unmeasurable": 0, "dark_at_both_levels": 1, "dark_in_prop_text_only": 2, "supported": 3}


def _verdict_against(counter, a, b):
    s, P, DP = counter["solo"], counter["pair"], counter["doc_pair"]
    if s.get(a, 0) < MEASURABLE_FLOOR or s.get(b, 0) < MEASURABLE_FLOOR:
        return "unmeasurable"
    k = "|".join(sorted((a, b)))
    p, d = P.get(k, 0), DP.get(k, 0)
    if p <= ZERO_BAND and d == 0:
        return "dark_at_both_levels"
    if p <= ZERO_BAND:
        return "dark_in_prop_text_only"
    return "supported"


p0_pairs = set()
for e in p0_model["edges"]:
    if e["src"] and e["dst"] and e["src"] != e["dst"]:
        p0_pairs.add(tuple(sorted((e["src"], e["dst"]))))
shared = sorted(p0_pairs & existing)
mig = collections.Counter()
moved = {"improved": [], "regressed": []}
for a, b in shared:
    v0, v1 = _verdict_against(p0, a, b), _verdict_against(cm, a, b)
    mig[f"{v0} -> {v1}"] += 1
    if _RANK[v1] > _RANK[v0]:
        moved["improved"].append({"a": a, "b": b, "from": v0, "to": v1,
                                  "p0_prop": P0_PAIR.get((a, b), 0),
                                  "p1_prop": pair.get((a, b), 0)})
    elif _RANK[v1] < _RANK[v0]:
        moved["regressed"].append({"a": a, "b": b, "from": v0, "to": v1,
                                   "p0_prop": P0_PAIR.get((a, b), 0),
                                   "p1_prop": pair.get((a, b), 0)})
migration = {
    "note": ("THE ONE UNCONFOUNDED X2 MEASUREMENT. The same endpoint pairs, the same rule, two "
             "corpora. Every other delta in this wave is contaminated by the 29 entities that "
             "entered the vocabulary since DEC-P0; this one is not, because the pair set is held "
             "fixed to what BOTH vintages declare. It is also a LOWER BOUND: the pre-X2 side "
             "still includes the stale _raw/ leg that this run drops."),
    "pairs_compared": len(shared),
    "pairs_dec_p0": len(p0_pairs), "pairs_now": len(existing),
    "n_improved": len(moved["improved"]), "n_regressed": len(moved["regressed"]),
    "n_unchanged": len(shared) - len(moved["improved"]) - len(moved["regressed"]),
    "transitions": dict(mig.most_common()),
    "improved": sorted(moved["improved"],
                       key=lambda r: -(r["p1_prop"] - r["p0_prop"]))[:60],
    "regressed": moved["regressed"],
}

doc = {
    "artifact": "edge_adjudication",
    "run": "dec_p1_x2",
    "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "question": "for every edge the plan's F-A itemization names and every one of graph_walk's "
                "130 structural candidates: AUTHOR, AUTHOR-ON-STRUCTURE, REFUSE, or "
                "WAIVE-UNMEASURABLE -- by one rule written down before the numbers were read",
    "rule": {
        "precedence": ["WAIVE-UNMEASURABLE", "REFUSE", "AUTHOR", "AUTHOR-ON-STRUCTURE",
                       "REFUSE-INSUFFICIENT"],
        "measurable_floor": MEASURABLE_FLOOR, "zero_band": ZERO_BAND,
        "author_floor_co_mentions": AUTHOR_FLOOR, "author_lift": LIFT_AUTHOR,
        "structure_jaccard": STRUCT_JACCARD,
        "thresholds_source": "dec_p0_rank.py:25-26 (floor, zero band) and :105 (the >=60 "
                             "co-mention floor before npmi ranking) -- reused verbatim so the "
                             "post-X2 read is a DELTA and not a new instrument",
    },
    "corpus": ee["method"]["corpus_snapshot"],
    "corpus_string": ee["method"]["corpus"],
    "headline": {
        "fa_named_edges": len(fa_rows), "structural_candidates": len(st_rows),
        "verdicts_all": dict(all_v), "verdicts_fa": dict(fa_v),
        "verdicts_structural": dict(st_v),
        "near_misses": len(near),
        "corpus_fed_pairs": len(corpus_fed),
        "vocabulary_fed_pairs_above_author_floor": len(vocab_fed),
        "rows_resolved_through_a_surface_fold": len(folds),
        "x2_pairs_improved": migration["n_improved"],
        "x2_pairs_regressed": migration["n_regressed"],
        "x2_pairs_compared": migration["pairs_compared"],
    },
    "delta_attribution_note": (
        "29 entities entered the vocabulary between DEC-P0 and this run (coconut, palm_kernel, "
        "hfcs, fresh_citrus, ddgs, tallow, used_cooking_oil, cottonseed, peanut, the fx family, "
        "...). A DEC-P0 count of 0 on any of them means THE ENTITY HAD NO SURFACE FORMS, not that "
        "the text was silent. Those deltas are labelled `vocabulary` and say nothing about the "
        "corpus doubling; only `corpus`-labelled rows are evidence about X2. DEC-P0's N (396,693) "
        "also included the stale _raw/ leg this run drops, so raw counts are not subtractable -- "
        "lift and npmi are the comparable quantities."),
    "x2_verdict_migration": migration,
    "near_misses": near,
    "corpus_fed": corpus_fed[:40],
    "vocabulary_fed": vocab_fed[:40],
    "rows_resolved_through_a_surface_fold": [
        {"asked_for": [r["a_raw"], r["b_raw"]], "measured": [r["a"], r["b"]],
         "resolved_via": r["resolved_via"]} for r in folds],
    "fa_named_edges": fa_rows,
    "structural_candidates": sorted(st_rows, key=lambda r: -(r.get("struct_score") or 0)),
}
(OUT / "edge_adjudication.json").write_text(json.dumps(doc, indent=1, ensure_ascii=True),
                                            encoding="utf-8")

# ── md ───────────────────────────────────────────────────────────────────────────────────────
L = []
A = L.append
snap = doc["corpus"]
A("# Edge adjudication (dec_p1, post-X2 corpus) -- %s" % doc["generated_utc"])
A("")
A("Artifact: `data/dec_p1/edge_adjudication.json`. Corpus judged: %s chunk objects / %s bytes, "
  "newest object %s; %s unique props." % (f"{snap['n_objects']:,}", f"{snap['total_bytes']:,}",
                                          snap["newest_last_modified"], f"{N:,}"))
A("")
A("**The question.** %s" % doc["question"])
A("")
A("**The rule, fixed before the numbers were read.** Precedence: "
  "`WAIVE-UNMEASURABLE` (either endpoint < %d mentions, or not in the vocabulary -- a verdict "
  "about the instrument) -> `REFUSE` (>=%d co-mentions but lift < 1.0 AND npmi <= 0, i.e. together "
  "LESS than chance) -> `AUTHOR` (>=%d co-mentions, npmi > 0 or lift > %.1f, no shared surface "
  "form) -> `AUTHOR-ON-STRUCTURE` (corpus-silent but a declared complex member with slice Jaccard "
  ">= %.2f -- the physical-identity class a zero must not veto) -> `REFUSE-INSUFFICIENT`."
  % (MEASURABLE_FLOOR, AUTHOR_FLOOR, AUTHOR_FLOOR, LIFT_AUTHOR, STRUCT_JACCARD))
A("")
A("| verdict | F-A named | structural | total |")
A("|---|---:|---:|---:|")
for k in ("AUTHOR", "AUTHOR-ON-STRUCTURE", "REFUSE", "REFUSE-INSUFFICIENT", "WAIVE-UNMEASURABLE"):
    A("| %s | %d | %d | %d |" % (k, fa_v.get(k, 0), st_v.get(k, 0), all_v.get(k, 0)))
A("")
A("## The one unconfounded X2 measurement")
A("")
A("%s" % migration["note"])
A("")
A("Re-classifying the **%d endpoint pairs both config vintages declare** under the same rule "
  "(floor %d, zero band %d) against the pre-X2 and post-X2 corpora: **%d improved, %d regressed, "
  "%d unchanged.**" % (migration["pairs_compared"], MEASURABLE_FLOOR, ZERO_BAND,
                       migration["n_improved"], migration["n_regressed"],
                       migration["n_unchanged"]))
A("")
A("| transition | n |")
A("|---|---:|")
for k, v in migration["transitions"].items():
    A("| `%s` | %d |" % (k, v))
A("")
if migration["regressed"]:
    A("Regressions (all of them):")
    A("")
    for r in migration["regressed"]:
        A("- `%s ~ %s` %s -> %s (%d -> %d props)"
          % (r["a"], r["b"], r["from"], r["to"], r["p0_prop"], r["p1_prop"]))
    A("")
A("## What the corpus doubling actually fed")
A("")
A("%s" % doc["delta_attribution_note"])
A("")
A("**Corpus-attributable movement** (both endpoints were measurable at DEC-P0, so the delta is "
  "the corpus and nothing else) -- top %d by absolute gain:" % min(15, len(corpus_fed)))
A("")
A("| pair | DEC-P0 prop | now | DEC-P0 lift | now lift | verdict |")
A("|---|---:|---:|---:|---:|---|")
for r in corpus_fed[:15]:
    A("| `%s ~ %s` | %d | %d | %s | %s | %s |" % (
        r["a"], r["b"], r["p0_co_mentions_prop"], r["co_mentions_prop"],
        r["p0_lift"], r["lift"], r["verdict"]))
A("")
A("**Vocabulary-attributable** (the entity did not exist at DEC-P0 -- these are NOT X2 results, "
  "they are the 29 new vocabulary entities becoming measurable at all):")
A("")
A("| pair | now prop | now lift | new endpoint(s) | verdict |")
A("|---|---:|---:|---|---|")
for r in vocab_fed[:15]:
    A("| `%s ~ %s` | %d | %s | %s | %s |" % (
        r["a"], r["b"], r["co_mentions_prop"], r["lift"],
        ", ".join(r["endpoints_new_since_dec_p0"]), r["verdict"]))
A("")
if folds:
    A("**Rows measured through a surface fold** -- the name asked for has no entity of its own, so "
      "the row measures a broader entity. Read these with that in mind:")
    A("")
    for r in folds:
        A("- asked `%s ~ %s`, measured `%s ~ %s` (%s)"
          % (r["a_raw"], r["b_raw"], r["a"], r["b"], json.dumps(r["resolved_via"])))
    A("")
A("## Near misses -- below the floor, strongly associated")
A("")
A("Disclosure, not a rule change: the >=%d floor is the INSTRUMENT's, not a fact about these "
  "pairs. Each keeps its `REFUSE-INSUFFICIENT` verdict; they are surfaced because they are where "
  "a curator should look first." % AUTHOR_FLOOR)
A("")
A("| pair | prop | expected | lift | npmi | doc | verdict |")
A("|---|---:|---:|---:|---:|---:|---|")
for r in near:
    A("| `%s ~ %s` | %d | %s | %s | %s | %d | %s |" % (
        r["a"], r["b"], r["co_mentions_prop"], r["expected_prop_if_independent"],
        r["lift"], r["npmi"], r["co_mentions_doc"], r["verdict"]))
A("")
A("## Part 1 -- the F-A named edges")
A("")
A("| item | edge | verdict | prop | doc | lift | npmi | a_mentions | b_mentions | Jaccard |")
A("|---|---|---|---:|---:|---:|---:|---:|---:|---:|")
for r in fa_rows:
    if not r["resolved"]:
        A("| %s | `%s ~ %s` | %s | - | - | - | - | - | - | - |"
          % (r["fa_item"], r["a_raw"], r["b_raw"], r["verdict"]))
        continue
    A("| %s | `%s ~ %s` | %s | %d | %d | %s | %s | %d | %d | %s |" % (
        r["fa_item"], r["a"], r["b"], r["verdict"], r["co_mentions_prop"], r["co_mentions_doc"],
        r["lift"], r["npmi"], r["a_mentions"], r["b_mentions"], r["slice_jaccard"]))
A("")
for item, label, _ in F_A:
    rows = [r for r in fa_rows if r["fa_item"] == item]
    if not rows:
        continue
    A("### %s. %s" % (item, label))
    A("")
    for r in rows:
        nm = "%s ~ %s" % (r["a"] or r["a_raw"], r["b"] or r["b_raw"])
        A("- **`%s`** -- %s. %s%s" % (
            nm, r["verdict"], r["why"],
            "  _(already edged in the DAGs)_" if r.get("already_edged") else ""))
    A("")
A("## Part 2 -- the 130 structural candidates, ranked by structural score")
A("")
A("| # | pair | score | Jaccard | groups | verdict | prop | lift | npmi |")
A("|---:|---|---:|---:|---|---|---:|---:|---:|")
for i, r in enumerate(doc["structural_candidates"], 1):
    A("| %d | `%s ~ %s` | %s | %s | %s | %s | %s | %s | %s |" % (
        i, r["a"] or r["a_raw"], r["b"] or r["b_raw"], r["struct_score"], r["slice_jaccard"],
        ", ".join(str(g) for g in r["shared_groups"][:2]) or "-", r["verdict"],
        r.get("co_mentions_prop", "-"), r.get("lift", "-"), r.get("npmi", "-")))
A("")
A("### Structural candidates the corpus AUTHORISES")
A("")
for r in doc["structural_candidates"]:
    if r["verdict"] in ("AUTHOR", "AUTHOR-ON-STRUCTURE"):
        A("- **`%s ~ %s`** (%s) -- %s" % (r["a"] or r["a_raw"], r["b"] or r["b_raw"],
                                          r["verdict"], r["why"]))
A("")
A("### Structural candidates the corpus REFUSES")
A("")
for r in doc["structural_candidates"]:
    if r["verdict"] == "REFUSE":
        A("- **`%s ~ %s`** -- %s" % (r["a"] or r["a_raw"], r["b"] or r["b_raw"], r["why"]))
(OUT / "edge_adjudication.md").write_text("\n".join(L) + "\n", encoding="utf-8")

print("F-A named edges:", len(fa_rows), dict(fa_v))
print("structural      :", len(st_rows), dict(st_v))
print("ALL             :", dict(all_v))
print("near misses     :", len(near))
print("corpus-fed      :", len(corpus_fed), "| vocabulary-fed >=floor:", len(vocab_fed))
print("surface folds   :", len(folds), [r["a_raw"] + "~" + r["b_raw"] for r in folds])
print("wrote", OUT / "edge_adjudication.md")
