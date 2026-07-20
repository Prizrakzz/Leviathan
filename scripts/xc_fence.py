"""RV2 W3 offline fence harness -- scores the deck against the REAL detection surface (D5/D13).

For each deck row this calls the REAL `dispatch.plan_turn` (the exact prod classifier: forced set_plan
tool, temperature=0 via D18's `_temp_kw` + this harness's **kw call wrapper) on the REAL serving contract
enum (the configs/graphrag/causal artifact CausalGraph.load() serves from -- a toy enum changes what
Sonnet sees, S3-F7), with the row's state_block/state_contracts passed exactly as serving passes session
state. Scoring composes through the IMPORTED `orchestrator.xc_detect_two_tier` symbol (S3-F6, identity-
asserted at startup) so deck attribution can never drift from prod -- this file NEVER reimplements the
composite, never calls classify_intent, never the orchestrator (no Athena/evidence spend).

Scoring semantics (mirrors the deck header):
- nofire rows gate on the PLANNER emission: any repeat with `xc_explicit is True` fails the row (the D20
  would-fire definition -- covers open-target emissions the composite would never route, D19). Composite
  regex hits on nofire rows are informational (the c8 rows regex-match by design; the LAW declines them).
- expect_tier=llm rows count a repeat iff the composite attributes tier=llm; a row passes at >=2/3 of
  scored repeats (D13). expect_tier=regex floor rows must hit on EVERY repeat with zero errors.
- ERRORED repeats: the call wrapper records raises on a per-row cell BEFORE plan_turn swallows them into
  `_FALLBACK` (S2-3 -- without the cell an errored row is byte-indistinguishable from a clean no-fire);
  a no-raise `_FALLBACK` and a degraded Sonnet->Haiku plan (never deck-certified, D2) are ERRORED too.
  Any ERRORED gating negative INVALIDATES the run: an unscored negative is not a passed negative.
- The harness REFUSES to run when GRAPHRAG_DISPATCH=rules (silent all-fallback = vacuous deck) and sets
  GRAPHRAG_XC_LLM_DETECT=on process-locally (restored after) so the composite's tier-2 is REACHABLE for
  attribution -- serving is untouched; the flag only ever gates consumption inside this process.
- D13 gates are evaluated on FULL runs only; --tune-only/--heldout-only are TUNE-iteration aids and mark
  the gates SUBSET. The heldout content hash prints on every run (frozen BEFORE any prompt iteration;
  pending chip rows join the hash when the main loop samples real minted chips).

Cost: a full run is ~600 dispatch-shaped Sonnet calls (~$4.10, eval.py pricing); pre-authorized band with
a HARD user check-in at $5 cumulative W3 spend. `--mock` is the hermetic unit-test lane: canned calls, a
synthetic enum, zero spend, and the report is stamped non-certifying.

Usage (PowerShell, worktree cwd, PYTHONPATH=<worktree>\\src):
    python scripts/xc_fence.py --mock
    python scripts/xc_fence.py --tune-only --repeats 3
    python scripts/xc_fence.py --provider bedrock          # D14 per-lane re-proof (negatives)
Exit codes: 0 = ran (and gates pass where evaluated), 1 = a gate failed, 2 = refused, 3 = run INVALID.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import sys
import types
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO / "src") not in sys.path:                    # direct `python scripts/xc_fence.py` support
    sys.path.insert(0, str(_REPO / "src"))

import yaml  # noqa: E402
from leviathan.graphrag import dispatch as dp  # noqa: E402
from leviathan.graphrag import orchestrator as orch  # noqa: E402

DECK_PATH = _REPO / "configs" / "graphrag" / "xc_fence_deck_v1.yaml"
REPORTS_DIR = _REPO / "reports"
NON_TOY_MIN = 25                                          # serving artifact is 33 contracts; toy = vacuous deck
NEG_REPEATS = 10                                          # D13: 10 repeats per negative row
POS_REPEATS = 3                                           # D13: a positive row passes at >=2/3 repeats
POS_LLM_GATE = 12                                         # D13: >=12/15 LLM-only rows
CHIP_GATE = 8                                             # D13: >=8/10 minted-chip rows (once sampled)
_ROW_HASH_KEYS = ("id", "category", "question", "state_block", "state_contracts", "expect", "expect_tier")

# The ONE scoring symbol (S3-F6): imported, identity-asserted, never reimplemented.
_COMPOSITE = orch.xc_detect_two_tier


def _ascii(s) -> str:
    return str(s).encode("ascii", "replace").decode()


def assert_composite_identity() -> None:
    """S3-F6: the harness must score through the exact orchestrator symbol prod consumes."""
    from leviathan.graphrag import orchestrator as _o
    if _COMPOSITE is not _o.xc_detect_two_tier or _COMPOSITE.__module__ != "leviathan.graphrag.orchestrator":
        raise AssertionError("xc_fence composite is not orchestrator.xc_detect_two_tier -- refusing "
                             "to score through a reimplementation (S3-F6)")


# ── deck load + lint ──────────────────────────────────────────────────────────────────────────────
def lint_deck(deck: dict) -> None:
    """Structural lint (raises ValueError). Premise lints that need the regex live in the unit test."""
    rows = (deck or {}).get("rows")
    if not rows:
        raise ValueError("deck has no rows")
    seen: set[str] = set()
    for r in rows:
        rid = r.get("id")
        if not rid or not isinstance(rid, str):
            raise ValueError(f"row missing id: {r!r}")
        if rid in seen:
            raise ValueError(f"duplicate row id: {rid}")
        seen.add(rid)
        for k in ("category", "expect", "split"):
            if not r.get(k):
                raise ValueError(f"row {rid}: missing required field {k!r}")
        if r["expect"] not in ("fire", "nofire"):
            raise ValueError(f"row {rid}: expect must be fire|nofire, got {r['expect']!r}")
        if r["split"] not in ("tune", "heldout"):
            raise ValueError(f"row {rid}: split must be tune|heldout, got {r['split']!r}")
        if r.get("expect_tier") not in (None, "regex", "llm"):
            raise ValueError(f"row {rid}: expect_tier must be regex|llm, got {r['expect_tier']!r}")
        if "question" not in r:
            raise ValueError(f"row {rid}: missing question")
        if r["split"] == "heldout" and not r.get("pending_sample") and r.get("frozen") is not True:
            raise ValueError(f"row {rid}: heldout rows must carry frozen: true (D13 frozen split)")


def load_deck(path: Path | str = DECK_PATH) -> dict:
    with open(path, encoding="utf-8") as fh:
        deck = yaml.safe_load(fh)
    lint_deck(deck)
    return deck


def heldout_hash(deck: dict) -> str:
    """Content hash of the FROZEN held-out half (sorted by id -- row order never moves it). Pending chip
    placeholders are excluded: they join the hash when the main loop fills in real minted chips."""
    rows = [r for r in deck["rows"] if r.get("split") == "heldout" and not r.get("pending_sample")]
    canon = json.dumps([{k: r.get(k) for k in _ROW_HASH_KEYS} for r in sorted(rows, key=lambda r: r["id"])],
                       sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(canon.encode()).hexdigest()[:16]


def enum_hash(contract_ids) -> str:
    return hashlib.sha256("\n".join(sorted(contract_ids)).encode()).hexdigest()[:12]


# ── graphs + calls ────────────────────────────────────────────────────────────────────────────────
def _assert_non_toy(contracts) -> None:
    if len(contracts) < NON_TOY_MIN:
        raise SystemExit(f"REFUSED: contract enum has {len(contracts)} ids (< {NON_TOY_MIN}) -- a toy "
                         f"enum changes what Sonnet sees and the deck would certify nothing (S3-F7)")


def load_serving_graph():
    """The REAL serving contract enum: the same configs/graphrag/causal artifact CausalGraph.load()
    serves from. Only `.contracts` is needed by plan_turn; silver resolution is deliberately skipped."""
    from leviathan.graphrag import graph as g
    contracts = g.load_contracts()
    _assert_non_toy(contracts)
    return types.SimpleNamespace(contracts=contracts, version=g.causal_graph_version())


_MOCK_ENUM = tuple(f"mock_contract_{i:02d}" for i in range(24)) + (
    "malaysian_crude_palm_oil_cme", "soybean_oil_cbot")   # real slugs: deck state_contracts must survive


def mock_graph():
    return types.SimpleNamespace(contracts={c: None for c in _MOCK_ENUM}, version="mock")


def make_call(inner, rec: dict):
    """Row-call wrapper (S2-3): records raises + the temperature actually passed BEFORE re-raising --
    plan_turn's own catch turns the raise into `_FALLBACK`, so without this cell an errored row would be
    byte-indistinguishable from a clean no-fire. **kw signature on purpose: `_temp_kw` sees VAR_KEYWORD
    and forwards temperature=0 (D18), which `rec` captures as the run's config proof."""
    def call(system, user, *, model, tool, **kw):
        rec["temperature"] = kw.get("temperature", "ABSENT")
        try:
            return inner(system, user, model=model, tool=tool, **kw)
        except Exception as e:  # noqa: BLE001 -- recorded then re-raised; plan_turn maps it to _FALLBACK
            rec["error"] = f"{type(e).__name__}: {e}"
            raise
    return call


def mock_call_factory(row: dict):
    """Canned per-row call for --mock: emits the row's own expectation (harness-logic testing only --
    a mock run exercises arithmetic/plumbing and is stamped non-certifying)."""
    def inner(system, user, *, model, tool, **kw):
        fire = row.get("expect") == "fire" and row.get("expect_tier") != "regex"
        return {"steps": ["reasoning"], "contracts": [],
                "xc_explicit": bool(fire), "xc_target": ("soybean oil" if fire else None)}
    return inner


def real_call_factory(row: dict):
    from leviathan.graphrag import answer as an  # lazy: --mock/--help never import the API stack
    return an._call_opus


# ── run ───────────────────────────────────────────────────────────────────────────────────────────
def run_row(row: dict, *, graph, inner_call, repeats: int, today: str) -> list[dict]:
    reps: list[dict] = []
    for _ in range(repeats):
        rec: dict = {}
        plan = dp.plan_turn(row.get("question") or "", graph=graph,
                            state_block=row.get("state_block"), today=today,
                            state_contracts=row.get("state_contracts"),
                            call=make_call(inner_call, rec))
        if rec.get("error"):
            reps.append({"errored": rec["error"], "temperature": rec.get("temperature")})
            continue
        if plan.fallback:                                 # no raise, still unscored (validation emptied it)
            reps.append({"errored": "planner_fallback (no raise)", "temperature": rec.get("temperature")})
            continue
        if plan.degraded:                                 # D2: the degraded model is never deck-certified
            reps.append({"errored": "degraded_model (Sonnet->Haiku)", "temperature": rec.get("temperature")})
            continue
        det = _COMPOSITE(plan)
        matched, span = det(row.get("question") or "")
        reps.append({"xc_explicit": plan.xc_explicit is True, "xc_target": plan.xc_target,
                     "matched": bool(matched), "span": span, "tier": det.tier,
                     "llm_consulted": bool(det.llm_consulted), "temperature": rec.get("temperature")})
    return reps


def run_deck(deck: dict, *, graph, call_factory, repeats_neg: int = NEG_REPEATS,
             repeats_pos: int = POS_REPEATS, subset: str | None = None,
             today: str | None = None) -> list[dict]:
    if os.environ.get("GRAPHRAG_DISPATCH", "llm") == "rules":
        raise RuntimeError("GRAPHRAG_DISPATCH=rules is set -- every row would silently fall back and "
                           "the deck would certify nothing (S2-3 refusal)")
    rows = [r for r in deck["rows"] if not r.get("pending_sample")]
    if subset:
        rows = [r for r in rows if r.get("split") == subset]
    today = today or deck.get("today") or _dt.date.today().isoformat()
    prev = os.environ.get("GRAPHRAG_XC_LLM_DETECT")
    os.environ["GRAPHRAG_XC_LLM_DETECT"] = "on"           # process-local: tier-2 must be REACHABLE to attribute
    try:
        results = []
        for row in rows:
            n = repeats_pos if row.get("expect") == "fire" else repeats_neg
            reps = run_row(row, graph=graph, inner_call=call_factory(row), repeats=n, today=today)
            results.append({"row": row, "reps": reps})
        return results
    finally:
        if prev is None:
            os.environ.pop("GRAPHRAG_XC_LLM_DETECT", None)
        else:
            os.environ["GRAPHRAG_XC_LLM_DETECT"] = prev


# ── score ─────────────────────────────────────────────────────────────────────────────────────────
def score(results: list[dict], deck: dict, *, subset: str | None = None) -> dict:
    per_row: list[dict] = []
    invalid: list[str] = []
    for item in results:
        row, reps = item["row"], item["reps"]
        errs = [x for x in reps if "errored" in x]
        ok = [x for x in reps if "errored" not in x]
        gating = row.get("gating", True)
        s = {"id": row["id"], "category": row["category"], "expect": row["expect"],
             "expect_tier": row.get("expect_tier"), "split": row["split"], "gating": gating,
             "repeats": len(reps), "errored": len(errs), "errors": [x["errored"] for x in errs][:3]}
        if row["expect"] == "nofire":
            fires = sum(1 for x in ok if x["xc_explicit"])
            s["llm_would_fires"] = fires
            s["regex_hits"] = sum(1 for x in ok if x["matched"] and x["tier"] == "regex")
            s["pass"] = (fires == 0 and not errs) if gating else None
            if gating and errs:
                invalid.append(row["id"])                 # an unscored negative is not a passed negative
        elif row.get("expect_tier") == "regex":
            fires = sum(1 for x in ok if x["matched"] and x["tier"] == "regex")
            s["fires"] = fires
            s["pass"] = (not errs and fires == len(reps)) if gating else None   # floor: EVERY repeat
        else:
            want = "llm" if row.get("expect_tier") == "llm" else None
            fires = sum(1 for x in ok if x["matched"] and (want is None or x["tier"] == want))
            s["fires"] = fires
            s["pass"] = (len(ok) > 0 and fires * 3 >= 2 * len(ok)) if gating else None   # >=2/3 scored
        per_row.append(s)

    neg = [s for s in per_row if s["expect"] == "nofire" and s["gating"]]
    pos_llm = [s for s in per_row if s["category"] == "pos_llm"]
    floor = [s for s in per_row if s["category"] == "pos_regex_floor"]
    chips = [s for s in per_row if s["category"] == "pos_chip"]
    pending_chips = [r["id"] for r in deck["rows"] if r.get("pending_sample")]
    temps = [x.get("temperature") for item in results for x in item["reps"]]
    full = subset is None

    def _gate(ok_: bool) -> str:
        if not full:
            return "SUBSET (not a gate run)"
        return "PASS" if ok_ else "FAIL"

    neg_failed = [s["id"] for s in neg if s["pass"] is False]
    agg = {
        "run_valid": not invalid,
        "invalid_negatives": invalid,
        "subset": subset,
        "neg_rows": len(neg), "neg_failed": neg_failed,
        "neg_gate": _gate(not invalid and not neg_failed),
        "pos_llm_rows": len(pos_llm), "pos_llm_passed": sum(1 for s in pos_llm if s["pass"]),
        "pos_llm_gate": _gate(sum(1 for s in pos_llm if s["pass"]) >= POS_LLM_GATE),
        "floor_rows": len(floor), "floor_passed": sum(1 for s in floor if s["pass"]),
        "floor_gate": _gate(sum(1 for s in floor if s["pass"]) == 4 and len(floor) == 4),
        "chip_rows_sampled": len(chips), "chip_passed": sum(1 for s in chips if s["pass"]),
        "chip_gate": (f"PENDING ({len(pending_chips)} unsampled)" if pending_chips
                      else _gate(sum(1 for s in chips if s["pass"]) >= CHIP_GATE)),
        "temperature_ok": bool(temps) and all(t == 0 for t in temps),
    }
    return {"per_row": per_row, "aggregates": agg}


# ── report ────────────────────────────────────────────────────────────────────────────────────────
def _print_report(doc: dict) -> None:
    agg = doc["scores"]["aggregates"]
    print(f"XC FENCE RUN  deck={doc['deck_path']}  mock={doc['mock']}  subset={agg['subset'] or 'FULL'}")
    print(f"  model={doc['model']}  provider={doc['provider']}  temperature_ok(=0)={agg['temperature_ok']}")
    print(f"  enum_hash={doc['enum_hash']}  n_contracts={doc['n_contracts']}  graph={doc['graph_version']}")
    print(f"  HELDOUT CONTENT HASH (frozen before prompt iteration): {doc['heldout_hash']}")
    print(f"  repeats: neg={doc['repeats_neg']}  pos={doc['repeats_pos']}")
    print("  id                                        expect  tier   fires  err  verdict")
    for s in doc["scores"]["per_row"]:
        fires = s.get("fires", s.get("llm_would_fires"))
        verdict = {True: "pass", False: "FAIL", None: "info"}[s["pass"]]
        extra = f" regex_hits={s['regex_hits']}" if s.get("regex_hits") else ""
        print(f"  {_ascii(s['id']):<41} {s['expect']:<7} {str(s['expect_tier'] or '-'):<6} "
              f"{fires:>5}  {s['errored']:>3}  {verdict}{extra}")
    print(f"  RUN: {'VALID' if agg['run_valid'] else 'INVALID (errored gating negative: ' + ','.join(agg['invalid_negatives']) + ')'}")
    print(f"  NEG gate  (0 would-fires, {agg['neg_rows']} rows) : {agg['neg_gate']}"
          + (f"  failed={','.join(agg['neg_failed'])}" if agg["neg_failed"] else ""))
    print(f"  POS gate  (llm-only >= {POS_LLM_GATE}/{agg['pos_llm_rows']})       : "
          f"{agg['pos_llm_gate']}  passed={agg['pos_llm_passed']}")
    print(f"  FLOOR gate (regex 4/4)              : {agg['floor_gate']}  passed={agg['floor_passed']}")
    print(f"  CHIP gate  (>= {CHIP_GATE}/10 once sampled)    : {agg['chip_gate']}")
    if doc["mock"]:
        print("  NOTE: MOCK RUN -- canned calls, synthetic enum; NOT a certification, never a gate.")


def write_report(doc: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2, ensure_ascii=False)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="RV2 W3 fence deck harness (real plan_turn + shared composite)")
    ap.add_argument("--deck", default=str(DECK_PATH))
    ap.add_argument("--repeats", type=int, default=NEG_REPEATS, help="repeats per NEGATIVE row (D13: 10)")
    ap.add_argument("--pos-repeats", type=int, default=POS_REPEATS, help="repeats per positive row (D13: 3)")
    ap.add_argument("--provider", default=None, help="sets GRAPHRAG_PROVIDER for the run (D14 lane re-proof)")
    grp = ap.add_mutually_exclusive_group()
    grp.add_argument("--tune-only", action="store_true", help="TUNE half only (iteration aid, not a gate)")
    grp.add_argument("--heldout-only", action="store_true", help="HELD-OUT half only (flip-gate scoring)")
    ap.add_argument("--mock", action="store_true", help="canned calls + synthetic enum (unit-test lane)")
    ap.add_argument("--report", default=None, help="UTF-8 JSON report path (default reports/xc_fence_<ts>.json)")
    args = ap.parse_args(argv)

    if os.environ.get("GRAPHRAG_DISPATCH", "llm") == "rules":
        print("REFUSED: GRAPHRAG_DISPATCH=rules -- every row would silently fall back (vacuous deck).")
        return 2
    assert_composite_identity()
    deck = load_deck(args.deck)
    subset = "tune" if args.tune_only else ("heldout" if args.heldout_only else None)

    if args.provider:
        os.environ["GRAPHRAG_PROVIDER"] = args.provider
    if args.mock:
        graph, factory, provider = mock_graph(), mock_call_factory, "mock"
    else:
        graph, factory = load_serving_graph(), real_call_factory
        provider = os.environ.get("GRAPHRAG_PROVIDER") or "anthropic"

    results = run_deck(deck, graph=graph, call_factory=factory, repeats_neg=args.repeats,
                       repeats_pos=args.pos_repeats, subset=subset)
    scores = score(results, deck, subset=subset)
    ts = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    doc = {"generated_utc": ts, "deck_path": str(args.deck), "mock": bool(args.mock),
           "provider": provider, "model": os.environ.get("GRAPHRAG_DISPATCH_MODEL") or dp.SONNET,
           "temperature": 0, "enum_hash": enum_hash(graph.contracts), "n_contracts": len(graph.contracts),
           "graph_version": graph.version, "heldout_hash": heldout_hash(deck),
           "repeats_neg": args.repeats, "repeats_pos": args.pos_repeats,
           "results": [{"id": it["row"]["id"], "reps": it["reps"]} for it in results],
           "scores": scores}
    _print_report(doc)
    rpath = Path(args.report) if args.report else REPORTS_DIR / f"xc_fence_{ts}{'_mock' if args.mock else ''}.json"
    write_report(doc, rpath)
    print(f"report written: {rpath}")
    agg = scores["aggregates"]
    if not agg["run_valid"]:
        return 3
    gates = (agg["neg_gate"], agg["pos_llm_gate"], agg["floor_gate"], agg["chip_gate"])
    return 1 if any(g == "FAIL" for g in gates) else 0


if __name__ == "__main__":
    sys.exit(main())
