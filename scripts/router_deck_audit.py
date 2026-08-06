"""D-AM-20 router-deck audit -- offline, deterministic scorer for the tier-1 contract selector.

Scores configs/graphrag/eval_queries_router_v2.yaml against the REAL serving surface by IMPORTING
intent.select_response_contract / select_response_contract_all (never a reimplementation -- a copied
regex would drift the same day) plus the classify-free lexical intent heuristic
(intent.classify_intent with call=None, i.e. the pure _NUM/_REASON path with no LLM adjudicator, and
intent.is_news_explicit / is_live for the live lane).

ZERO SPEND, ZERO I/O: pure regex over a yaml file. No LLM, no Athena, no evidence store, no AWS.

WHAT IT REPORTS
  * deck census (source / expected_intent / rc_expected strata, ambiguous count);
  * selector accuracy over ALL rows and over ELIGIBLE rows (expected_intent in reasoning|hybrid) --
    the second is the serving-relevant number, because orchestrator.py runs the selector only for
    kind in (reasoning, hybrid); numbers_only and live are tier-0 exempt lanes;
  * per-stratum accuracy with a Wilson score 95% LOWER bound (binomial; the honest floor at n=10-18
    per stratum, where a raw ratio reads far more precisely than the sample supports);
  * CONTESTED rows -- where select_response_contract_all returns more than one match, i.e. exactly
    the rows a priority re-order or a cue widening would silently re-shape (the also_matched stamp);
  * every MISS, split into wrong-contract / missed (fell through to default) / false-positive.

READ THE DECK HEADER BEFORE ACTING ON A MISS. This is a MEASUREMENT deck: the misses are the
product. Widening a cue until this scoreboard reads 100% measures the fitting, not the router.

Usage (repo root):
    python scripts/router_deck_audit.py
    python scripts/router_deck_audit.py --deck <path> --show-all
Exit codes: 0 = audit ran, 2 = deck missing/unreadable. NEVER non-zero on a low score -- this is a
measurement, not a gate.
"""
from __future__ import annotations

import argparse
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO / "src") not in sys.path:                    # direct `python scripts/router_deck_audit.py`
    sys.path.insert(0, str(_REPO / "src"))

import yaml  # noqa: E402
from leviathan.graphrag import intent as it  # noqa: E402
from leviathan.graphrag import response_contracts as rc  # noqa: E402

DECK_PATH = _REPO / "configs" / "graphrag" / "eval_queries_router_v2.yaml"
DEFAULT_LABEL = "default"                                 # the null rc_expected bucket, for display
ELIGIBLE_INTENTS = ("reasoning", "hybrid")                # the lanes where the selector actually runs
Z95 = 1.959964                                            # two-sided 95% -> the one-sided lower bound


def _a(s) -> str:
    """ASCII-only rendering (the console is cp1252; the deck carries Arabic and Portuguese rows)."""
    return str(s).encode("ascii", "replace").decode()


def wilson_lb(k: int, n: int, z: float = Z95) -> float:
    """Wilson score interval LOWER bound for a binomial proportion. Chosen over the normal
    approximation because the per-stratum n here is 10-18: the normal interval is badly wrong (and
    degenerate at k==n), Wilson stays sane at the boundaries."""
    if n <= 0:
        return 0.0
    p = k / n
    denom = 1.0 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1.0 - p) / n + z * z / (4.0 * n * n))
    return max(0.0, (centre - margin) / denom)


def _pct(x: float) -> str:
    return f"{100.0 * x:5.1f}%"


def _rate(k: int, n: int) -> str:
    if n <= 0:
        return "   n/a  (n=0)"
    return f"{_pct(k / n)} ({k}/{n})  lb95 {_pct(wilson_lb(k, n))}"


def load_deck(path: Path) -> list:
    if not path.exists():
        print(f"REFUSED: deck not found: {_a(path)}")
        raise SystemExit(2)
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    rows = doc.get("rows") or []
    if not rows:
        print(f"REFUSED: deck has no rows: {_a(path)}")
        raise SystemExit(2)
    return rows


def score_row(row: dict) -> dict:
    """Pure per-row scoring -- no state, no ordering effects."""
    q = row.get("question") or ""
    matches = it.select_response_contract_all(q)
    got = it.select_response_contract(q)
    want = row.get("rc_expected")
    exp_intent = row.get("expected_intent")
    lex = it.classify_intent(q)                           # call=None -> the free lexical path ONLY
    if exp_intent == "live":
        intent_ok = bool(it.is_news_explicit(q) or it.is_live(q))
    else:
        intent_ok = lex["intent"] == exp_intent
    lane_want = exp_intent in ("numbers_only", "hybrid")
    return {
        "id": row.get("id"), "question": q, "source": row.get("source"),
        "want": want, "got": got, "matches": list(matches),
        "also_matched": list(matches[1:]),
        "ok": got == want,
        "stratum": want or DEFAULT_LABEL,
        "expected_intent": exp_intent, "lex_intent": lex["intent"],
        "intent_ok": intent_ok,
        "lane_ok": bool(lex["needs_numbers"]) == lane_want and exp_intent != "live",
        "eligible": exp_intent in ELIGIBLE_INTENTS,
        "ambiguous": bool(row.get("ambiguous")),
        "kind": ("hit" if got == want else
                 "false_positive" if want is None else
                 "missed" if got is None else "wrong_contract"),
    }


def _census(rows: list, scored: list) -> None:
    print("== DECK CENSUS ==")
    print(f"  rows: {len(rows)}")
    for label, key in (("source", "source"), ("expected_intent", "expected_intent"),
                       ("rc_expected", "stratum")):
        c = Counter(s[key] for s in scored)
        body = ", ".join(f"{_a(k)}={v}" for k, v in sorted(c.items(), key=lambda kv: (-kv[1], str(kv[0]))))
        print(f"  by {label:<15}: {body}")
    print(f"  ambiguous flagged  : {sum(1 for s in scored if s['ambiguous'])}")
    dup_ids = [i for i, n in Counter(s["id"] for s in scored).items() if n > 1]
    if dup_ids:
        print(f"  !! DUPLICATE IDS   : {_a(dup_ids)}")
    bad = sorted({str(s["want"]) for s in scored if s["want"] is not None} - set(rc.valid_names()))
    if bad:
        print(f"  !! rc_expected NOT IN response_contracts.valid_names(): {_a(bad)}")
    print()


def _accuracy(scored: list) -> None:
    print("== SELECTOR ACCURACY (intent.select_response_contract) ==")
    print("   [lb95 = Wilson score 95% binomial LOWER bound -- the honest floor at these sample sizes]")
    ok_all = sum(1 for s in scored if s["ok"])
    elig = [s for s in scored if s["eligible"]]
    ok_el = sum(1 for s in elig if s["ok"])
    print(f"  ALL rows                 : {_rate(ok_all, len(scored))}")
    print(f"  ELIGIBLE (reasoning|hybrid): {_rate(ok_el, len(elig))}   <- the serving-relevant number")
    exempt = [s for s in scored if not s["eligible"]]
    shadow_fp = sum(1 for s in exempt if s["got"] is not None)
    print(f"  EXEMPT lanes (numbers_only|live): {len(exempt)} rows, {shadow_fp} would have selected a "
          f"contract (shadow-only; the selector never runs on those lanes)")
    strict = [s for s in scored if not s["ambiguous"]]
    print(f"  UNAMBIGUOUS rows only    : {_rate(sum(1 for s in strict if s['ok']), len(strict))}")
    for src in ("store", "synthetic"):
        sub = [s for s in scored if s["source"] == src]
        print(f"  source={src:<10}       : {_rate(sum(1 for s in sub if s['ok']), len(sub))}")
    print()
    print("== PER-STRATUM (stratum = rc_expected; 'default' = the null/fail-open bucket) ==")
    by = defaultdict(list)
    for s in scored:
        by[s["stratum"]].append(s)
    for name in sorted(by, key=lambda n: (n == DEFAULT_LABEL, n)):
        sub = by[name]
        k = sum(1 for s in sub if s["ok"])
        amb = sum(1 for s in sub if s["ambiguous"])
        print(f"  {name:<15}: {_rate(k, len(sub))}   ambiguous={amb}")
    print()


def _intent_checks(scored: list) -> None:
    print("== CLASSIFY-FREE LEXICAL INTENT CHECK (no LLM: intent.classify_intent(call=None)) ==")
    print("   Observational. In serving the cheap Haiku classifier adjudicates the ambiguous cases,")
    print("   so a miss here is a statement about the FREE heuristic, not about the shipped router.")
    k = sum(1 for s in scored if s["intent_ok"])
    print(f"  exact intent match       : {_rate(k, len(scored))}")
    lanes = [s for s in scored if s["expected_intent"] != "live"]
    print(f"  needs_numbers lane agree : {_rate(sum(1 for s in lanes if s['lane_ok']), len(lanes))}")
    live = [s for s in scored if s["expected_intent"] == "live"]
    print(f"  live rows detected       : {_rate(sum(1 for s in live if s['intent_ok']), len(live))}")
    by = defaultdict(list)
    for s in scored:
        by[s["expected_intent"]].append(s)
    for name in sorted(by):
        sub = by[name]
        print(f"  {name:<15}: {_rate(sum(1 for s in sub if s['intent_ok']), len(sub))}")
    print()


def _contested(scored: list) -> None:
    con = [s for s in scored if s["also_matched"]]
    print("== CONTESTED ROWS (also_matched non-empty -- where priority order decides the shape) ==")
    print(f"  {len(con)} of {len(scored)} rows match more than one tier-1 pattern.")
    pair = Counter()
    for s in con:
        for other in s["also_matched"]:
            pair[(s["got"], other)] += 1
    for (winner, loser), n in pair.most_common():
        print(f"    {_a(winner):<15} beats {_a(loser):<15} x{n}")
    for s in con:
        print(f"    {_a(s['id']):<24} {_a(s['got']):<14} also={_a(s['also_matched'])}")
    print()


def _misses(scored: list, show_all: bool) -> None:
    misses = [s for s in scored if not s["ok"]]
    print("== MISSES ==")
    print(f"  {len(misses)} of {len(scored)} rows. kind counts: "
          f"{_a(dict(Counter(s['kind'] for s in misses)))}")
    print("  wrong_contract = picked a different contract | missed = fell through to default "
          "(FAIL-OPEN, costs shaping only) | false_positive = picked a contract where default was right")
    for kind in ("wrong_contract", "false_positive", "missed"):
        sub = [s for s in misses if s["kind"] == kind]
        if not sub:
            continue
        print(f"  -- {kind} ({len(sub)}) --")
        for s in sub:
            flag = " [AMBIGUOUS]" if s["ambiguous"] else ""
            exm = "" if s["eligible"] else " [tier-0 exempt lane]"
            print(f"    {_a(s['id']):<24} want={_a(s['want']):<14} got={_a(s['got']):<14}{flag}{exm}")
            print(f"      {_a(s['question'])[:150]}")
    if show_all:
        print("  -- HITS --")
        for s in scored:
            if s["ok"]:
                print(f"    {_a(s['id']):<24} {_a(s['want'])}")
    print()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="D-AM-20 router measurement deck audit (offline).")
    ap.add_argument("--deck", default=str(DECK_PATH))
    ap.add_argument("--show-all", action="store_true", help="also list the hits")
    args = ap.parse_args(argv)

    path = Path(args.deck)
    rows = load_deck(path)
    scored = [score_row(r) for r in rows]

    print("=" * 100)
    print("D-AM-20 ROUTER MEASUREMENT DECK AUDIT -- offline, deterministic, zero spend")
    print(f"deck: {_a(path)}")
    print("MEASUREMENT deck: do NOT tune _RC_PATTERNS row-by-row against this scoreboard.")
    print("=" * 100)
    _census(rows, scored)
    _accuracy(scored)
    _intent_checks(scored)
    _contested(scored)
    _misses(scored, args.show_all)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
