"""GraphRAG Phase-1 vocab/pattern harvest — raise the deterministic-capture ceiling. $0 LLM, CPU only.

Three sources → classify → hit-count (TWO-LEVEL prune) → stage candidates + report:
  A) mine_extractions — surface forms + **unmapped tails** + `(marker,relation)` from prior runs (pilot
     reports). The unmapped tail = terms the model saw but the vocab couldn't map (highest-value gaps).
  B) mine_corpus      — regex capitalised-phrase + causal-marker-proximity verb mining over a 2020–26 sample.
  C) research_seed.yaml — curated domain terms (diseases/pests/climate drivers/policy/verbs/markers).

**Prune rule (two-level):** a *concept* (canonical node member) is KEPT even at 0 corpus hits — absence in
a 5-year slice ≠ invalidity (may appear in deltas). Only a *redundant surface form* (alias/verb-variant) is
parked: 0 hits AND its concept already has ≥1 hitting form (the corpus phrased it another way). A 0-hit
surface form whose concept has NO hitting form is kept (the only handle on a real-but-absent concept).

    python -m leviathan.graphrag.harvest --sample 300
"""
from __future__ import annotations

import argparse
import collections
import json
import random
import re

import boto3
import yaml

from leviathan.graphrag import batch_extract as bx
from leviathan.graphrag import extract as ex
from leviathan.graphrag.corpus_recon import BUCKET, TEXT_PREFIX, _CAP_PHRASE, _STOP, _source_of

_CFG = ex._CFG
_OUT = bx._OUT
_SEED = _CFG / "research_seed.yaml"
_CANDIDATES = _CFG / "vocab_candidates.yaml"

# heuristic type-guess for a mined candidate (research_seed terms come pre-typed)
_TYPE_PATTERNS = [
    (re.compile(r"(?i)(rust|blight|mildew|smut|\bwilt\b|\brot\b|borer|worm|weevil|aphid|locust|midge|"
                r"nematode|virus|\bscab\b|blast|lodging|shatter|\bhail\b|drought|frost|flood|heat stress|"
                r"sprouting|waterlog|planthopper|stink bug|armyworm)"), "hazard"),
    (re.compile(r"(?i)(el ?ni\w+|la ?ni\w+|oscillation|monsoon|vortex|dipole|\benso\b|teleconnection|"
                r"blocking high|heat dome)"), "climate_driver"),
    (re.compile(r"(?i)(tariff|\bquota\b|export ban|export tax|mandate|subsidy|\bduty\b|\bMEP\b|\bTRQ\b|"
                r"\bEUDR\b|\bRFS\b|\bRIN\b|phytosanitary|licens|safeguard|\bMSP\b|\blevy\b|moratorium|"
                r"stock limit)"), "policy_event"),
    (re.compile(r"(?i)(spread|\bmargin\b|premium|\bbasis\b|\bcarry\b|crush|parity|oil share)"), "instrument"),
    (re.compile(r"(?i)(flowering|grain fill|pod fill|tillering|anthesis|maturity|emergence|ratoon|"
                r"dormancy|silking|boll set|germination)"), "state_marker"),
]


def _guess_type(term: str) -> str:
    for rx, t in _TYPE_PATTERNS:
        if rx.search(term):
            return t
    return "unknown"


def _seed() -> dict:
    return yaml.safe_load(_SEED.read_text(encoding="utf-8")) if _SEED.exists() else {}


# ── Source A — mine prior extractions (pilot reports; local, fast) ─────────────────
def mine_extractions() -> dict:
    """unmapped tail (highest-value gap) + mapped surface forms from the local pilot artifacts."""
    out = {"unmapped": collections.Counter(), "surface": collections.Counter()}
    for fn in ("friction_report.md", "decider_report.md"):
        p = _OUT / fn
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            m = re.match(r"-\s*(\d+)x\s*`(.+?)`", line.strip())        # "- 7x `term (type)`"
            if m:
                out["unmapped"][re.sub(r"\s*\(.*?\)\s*$", "", m.group(2)).strip()] += int(m.group(1))
    for fn in ("candidate_gold.jsonl", "extraction.candidates.jsonl"):
        p = _OUT / fn
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except (json.JSONDecodeError, TypeError):
                continue
            for e in rec.get("entities", []):
                out["surface"][str(e.get("id", ""))] += 1
            for edge in rec.get("edges", []):
                out["surface"][str(edge.get("src", ""))] += 1
                out["surface"][str(edge.get("dst", ""))] += 1
    return out


# ── Source B — mine the corpus (regex; spaCy deferred to the Exp-2 filter) ─────────
_VERB_NEAR = re.compile(r"\b([a-z]{4,12}(?:s|ed|ing)?)\b\s+(?:the\s+)?(?:\w+\s+){0,3}"
                        r"(?:price|production|yield|output|supply|demand|exports?|stocks?|area)", re.I)


def mine_corpus(s3, sample: int) -> dict:
    """Capitalised candidate phrases (entities) + verbs adjacent to S/D nouns (cascade-verb candidates)."""
    keys = [o["Key"] for page in s3.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=TEXT_PREFIX)
            for o in page.get("Contents", []) if o["Key"].endswith("document.json")
            and bx._year_of(o["Key"]) != "unknown" and int(bx._year_of(o["Key"])) >= 2020]
    keys = random.Random(0).sample(keys, min(sample, len(keys)))
    phrases, verbs = collections.Counter(), collections.Counter()
    for k in keys:
        try:
            txt = (json.loads(s3.get_object(Bucket=BUCKET, Key=k)["Body"].read()).get("full_text") or "")
        except Exception:  # noqa: BLE001
            continue
        for ph in _CAP_PHRASE.findall(txt[:40000]):
            if ph not in _STOP and len(ph) > 3:
                phrases[ph] += 1
        for v in _VERB_NEAR.findall(txt[:40000]):
            verbs[v.lower()] += 1
    return {"phrases": phrases, "verbs": verbs, "n_docs": len(keys)}


# ── matcher + two-level hit-count prune ────────────────────────────────────────────
def build_matcher(forms: list[str]):
    """Word-boundary regex over all surface forms → counts hits per form. (Exp-2 swaps in spaCy PhraseMatcher.)"""
    forms = sorted({f for f in forms if f and len(f) > 1}, key=len, reverse=True)
    idx = {f.lower(): f for f in forms}
    rx = re.compile(r"\b(" + "|".join(re.escape(f) for f in forms) + r")\b", re.I) if forms else None
    return rx, idx


def hit_count(s3, forms: list[str], sample: int) -> collections.Counter:
    rx, idx = build_matcher(forms)
    hits = collections.Counter({f: 0 for f in forms})
    if rx is None:
        return hits
    keys = [o["Key"] for page in s3.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=TEXT_PREFIX)
            for o in page.get("Contents", []) if o["Key"].endswith("document.json")
            and bx._year_of(o["Key"]) != "unknown" and int(bx._year_of(o["Key"])) >= 2020]
    for k in random.Random(1).sample(keys, min(sample, len(keys))):
        try:
            txt = (json.loads(s3.get_object(Bucket=BUCKET, Key=k)["Body"].read()).get("full_text") or "")
        except Exception:  # noqa: BLE001
            continue
        for m in rx.findall(txt):
            hits[idx.get(m.lower(), m)] += 1
    return hits


def prune_two_level(concepts: dict, hits: collections.Counter) -> dict:
    """concepts: {concept: {type, forms:[...]}}.  Returns per-concept verdict + per-form accept/park."""
    out = {}
    for concept, meta in concepts.items():
        forms = meta["forms"]
        any_hit = any(hits.get(f, 0) > 0 for f in forms)
        form_status = {}
        for f in forms:
            if hits.get(f, 0) > 0:
                form_status[f] = "accept"
            elif any_hit:
                form_status[f] = "park"            # redundant: 0 hits, concept already covered
            else:
                form_status[f] = "accept"          # lone handle on a real-but-absent concept → keep
        out[concept] = {"type": meta["type"], "concept_hits": sum(hits.get(f, 0) for f in forms),
                        "covered": any_hit, "forms": form_status}
    return out


# ── orchestration + report ──────────────────────────────────────────────────────────
def _live_vocab_terms() -> set:
    v = ex._vocab()
    terms = {m for ms in v.get("nodes", {}).values() if ms for m in ms}
    for al in (v.get("aliases") or {}).values():
        terms.update(al)
    return {ex._normalize(t) for t in terms}


def harvest(s3, *, sample: int) -> None:
    seed = _seed()
    live = _live_vocab_terms()
    # concepts from research_seed (pre-typed). dict node_type sections → {concept: [forms]}
    concepts = {}
    for ntype in ("hazard", "climate_driver", "state_marker", "policy_event", "instrument"):
        for concept, forms in (seed.get(ntype) or {}).items():
            concepts[concept] = {"type": ntype, "forms": [concept.replace("_", " ")] + list(forms)}
    # all surface forms to hit-count
    all_forms = sorted({f for c in concepts.values() for f in c["forms"]})
    hits = hit_count(s3, all_forms, sample)
    verdict = prune_two_level(concepts, hits)

    _write_active_seed(verdict, seed)                       # the pruned seed ex._vocab() merges live

    data = mine_extractions()
    corp = mine_corpus(s3, sample)
    # candidate NEW terms from mining = not already in live vocab + not already a seed concept
    seed_norm = {ex._normalize(c) for c in concepts} | {ex._normalize(f) for c in concepts.values() for f in c["forms"]}
    def _novel(counter):
        return [(t, n) for t, n in counter.most_common(120)
                if ex._normalize(t) not in live and ex._normalize(t) not in seed_norm and len(t) > 3]
    mined_unmapped = _novel(data["unmapped"])
    mined_phrases = _novel(corp["phrases"])
    mined_verbs = [(v, n) for v, n in corp["verbs"].most_common(40) if v not in ex._vocab().get("causal_markers", [])]

    _write(verdict, hits, mined_unmapped, mined_phrases, mined_verbs, seed, sample, corp["n_docs"])


def _write_active_seed(verdict, seed) -> None:
    """research_seed.active.yaml = the seed with PARKED redundant forms dropped; concepts always kept.
    ex._vocab() merges this live (additive node members + aliases + verbs + markers)."""
    active = {"version": (seed.get("version", "0") + "-active"), "_note": "auto-pruned by harvest; edit research_seed.yaml"}
    for ntype in ("hazard", "climate_driver", "state_marker", "policy_event", "instrument"):
        sec = {}
        for concept, forms in (seed.get(ntype) or {}).items():
            parked = {f for f, s in verdict.get(concept, {}).get("forms", {}).items() if s == "park"}
            sec[concept] = [f for f in (forms or []) if f not in parked]   # concept itself always kept
        active[ntype] = sec
    active["verb_normalization"] = seed.get("verb_normalization", {})
    active["causal_markers"] = seed.get("causal_markers", [])
    (_CFG / "research_seed.active.yaml").write_text(
        yaml.safe_dump(active, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _write(verdict, hits, mined_unmapped, mined_phrases, mined_verbs, seed, sample, n_docs) -> None:
    _OUT.mkdir(parents=True, exist_ok=True)
    # staged candidates (data/corpus-mined — need review before folding)
    cand = {"research_seed_verdict": {c: {"type": v["type"], "concept_hits": v["concept_hits"],
                                          "parked_forms": [f for f, s in v["forms"].items() if s == "park"]}
                                      for c, v in verdict.items()},
            "mined_unmapped_tail": [{"term": t, "n": n, "type_guess": _guess_type(t)} for t, n in mined_unmapped],
            "mined_corpus_phrases": [{"term": t, "n": n, "type_guess": _guess_type(t)} for t, n in mined_phrases],
            "mined_corpus_verbs": [{"verb": v, "n": n} for v, n in mined_verbs]}
    _CANDIDATES.write_text(yaml.safe_dump(cand, sort_keys=False, allow_unicode=True), encoding="utf-8")

    n_concepts = len(verdict)
    zero_hit_concepts = [c for c, v in verdict.items() if not v["covered"]]
    parked = [(c, f) for c, v in verdict.items() for f, s in v["forms"].items() if s == "park"]
    by_type = collections.Counter(v["type"] for v in verdict.values())
    parked_lines = [f"    - `{f}` (→ {c})" for c, f in parked[:40]]
    top_concepts = [f"- {v['concept_hits']:>4}x  {c} ({v['type']})"
                    for c, v in sorted(verdict.items(), key=lambda kv: -kv[1]['concept_hits'])[:30]]
    unmapped_lines = [f"- {n:>3}x `{t}`  -> guess: {_guess_type(t)}" for t, n in mined_unmapped[:40]] or ["- none"]
    phrase_lines = [f"- {n:>3}x `{t}`  -> guess: {_guess_type(t)}" for t, n in mined_phrases[:40]] or ["- none"]
    verb_lines = [f"- {n:>3}x `{v}`" for v, n in mined_verbs[:25]] or ["- none"]
    L = [f"# Phase-1 harvest report ({n_docs} docs sampled, 2020-26)",
         f"\n**{n_concepts} research-seed concepts** across {dict(by_type)}.",
         f"- **0-hit concepts KEPT (flagged for review, never removed):** {len(zero_hit_concepts)} -- "
         f"{', '.join(zero_hit_concepts[:30])}{' ...' if len(zero_hit_concepts) > 30 else ''}",
         f"- **redundant surface forms PARKED** (0 hits, concept covered): {len(parked)}",
         *parked_lines,
         "\n## Top seed concepts by corpus hits", *top_concepts,
         f"\n## Mined unmapped tail (prior runs -- new vocab gaps, {len(mined_unmapped)})", *unmapped_lines,
         f"\n## Mined corpus phrases (candidate entities, {len(mined_phrases)})", *phrase_lines,
         "\n## Mined corpus cascade-verbs (candidate markers)", *verb_lines,
         "\n**Fold rule:** fold all seed concepts + their accepted forms into entity_vocabulary.yaml; drop the",
         "parked forms; review the mined tail/phrases before folding (noisier). Concepts are never removed for",
         "0 hits -- absence in 2020-26 != invalidity (deltas may surface them)."]
    (_OUT / "harvest_report.md").write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L[:8]), flush=True)
    print(f"\nwrote {_CANDIDATES}\nwrote {_OUT / 'harvest_report.md'}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser(description="GraphRAG Phase-1 vocab/pattern harvest (free, no LLM).")
    ap.add_argument("--sample", type=int, default=300, help="2020–26 docs sampled for hit-counting/mining")
    ap.add_argument("--region", default="us-east-1")
    args = ap.parse_args()
    s3 = boto3.client("s3", region_name=args.region)
    harvest(s3, sample=args.sample)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
