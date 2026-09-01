"""D-XT G1 -- THE PROMPT SOAK (spec section c1). `plan_turn` ONLY: no walk, no synthesis, no judge.

WHAT THIS BUYS. Owner directive 1 (2026-08-29) moves cross-commodity detection for the OPEN class out
of `intent.py`'s regex and into the DISPATCH PLANNER's system prompt. That makes the prompt the whole
detector for this class -- measured, `intent.is_cross_commodity_explicit` returns (False, None) on
14/14 frozen contagion rows -- and it makes THREE ratified never-volunteer pins defended by PROSE. G1
is the only measurement of that prose, and it is bought BEFORE anything else in the wave.

THE SEAT IS PINNED ON BOTH PROMPTS: model=claude-sonnet-4-6, temperature=0 (dispatch._temp_kw; the
4-6 seat still accepts the pin), max_contracts=6 -- the ARM's own ceiling. Round 3's baseline was
measured at the shipped default ceiling of 2 and is therefore NOT this arm's baseline; G1-0 corrects
that for ~$0.14. `today` comes from each row's own `asof` where the deck carries one.

THE CELLS
  g1-0  the 14 contagion rows, TODAY's prompt (xc_open=False), 3 draws   -- the true baseline (P14)
  g1-a  the 14 contagion rows, AMENDED prompt, 3 draws                   -- open recall + no invention
  g1-c  the 24 boundary rows, amended, 1 draw + 3 re-draws on any fire    -- the negative boundary
  g1-d  the 6 typo rows, amended, 3 draws, row passes at >=2/3 (P15)      -- the robustness CLAIM
  g1-e  the 5 v4_cascade rv2 rows, amended, 3 draws                       -- the ratified fence (P2)
  g1-f  ROUTING DRIFT: g1-0 majority vs g1-a majority, per row            -- FREE, no calls
  g1-g  the 84 xc_fence_deck_v1 rows, BOTH prompts, 1 draw each           -- the shipped deck's floor

THE BARS, PRE-REGISTERED (spec c1). Every one is a PASS/STOP, and the verdict vocabulary for the wave
is {LAND-DARK, STOP} -- this script cannot flip anything, by design.
  G1-a  >= 9 of 14 rows fire with an OPEN target (null or collective) on >= 2 of 3 draws
  G1-b  0 of 14 rows return a NAMED, non-collective target naming a commodity the turn does not name
  G1-c  24/24 xc_explicit=false; ANY row firing on ANY of 4 draws is a STOP (a boundary that flickers
        is not a boundary)
  G1-d  >= 5 of 6 typo rows pass; 3-4 = PARTIAL ("the robustness claim is half-earned"); <= 2 = STOP
  G1-e  the three rv2_neg_* rows stay xc_explicit=false on EVERY draw, and the two positive rows stay
        true on EVERY draw (P2 -- a fence cell that only counts negatives cannot see a recall collapse)
  G1-f  <= 2 of 14 rows differ in `steps` or `contracts` between the two prompts. The treatment IS a
        prompt, so it can perturb routing on rows where nothing fires; a moving denominator makes the
        paired judged comparison unreadable (the D-DV-1 lesson). Drift rows are NAMED and excluded
        from any paired headline whatever the count; > 2 REFUSES the judged arm regardless of G1-a.
  G1-g  no INCREASE in the xc_explicit=true count on the shipped 84-row fence deck vs today's prompt

COST. ~$0.01 per dispatch call [M, the round-3 probe's own per-call anchor]. The spec's booked package
is G1-0/a/c/d/e = 101-113 calls = $1.15; g1-g adds 168 calls (~$1.68) and g1-f is free. `--dry-run`
prints the exact call plan and the estimate BEFORE anything is spent -- run it first, every time.

USAGE (owner shell is Windows PowerShell 5.1: chain with `;`, never `&&`)
  $env:PYTHONPATH="src"; python scripts/xc_planner_soak.py --dry-run
  $env:PYTHONPATH="src"; python scripts/xc_planner_soak.py --cells g1-0,g1-a
  $env:PYTHONPATH="src"; python scripts/xc_planner_soak.py            # every cell

ANTHROPIC_API_KEY is read from the environment and NEVER printed, logged or written to the artifact.
Exit codes: 0 = ran, every evaluated bar PASS; 1 = a bar STOPped; 2 = refused before spending.
"""
from __future__ import annotations

import argparse
import collections
import datetime as _dt
import importlib.util
import json
import os
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO / "src") not in sys.path:                    # direct `python scripts/xc_planner_soak.py`
    sys.path.insert(0, str(_REPO / "src"))

import yaml  # noqa: E402
from leviathan.graphrag import dispatch as dp  # noqa: E402
from leviathan.graphrag import orchestrator as orch  # noqa: E402

# ── the pinned seat (a7/M5) ──────────────────────────────────────────────────────────────────────
# sonnet-4-6 routed 6/6 unanimous vs sonnet5_fixed's 2/6 split, and a routing flip to bare `numbers`
# kills the fork outright (the XC gate runs only on reasoning/hybrid) -- un-attributable noise sitting
# on the treatment's own mechanism. It matters MORE in round 4 than in round 3: the treatment now IS a
# prompt, so the seat and the prompt would otherwise move together.
SEAT = "claude-sonnet-4-6"
MAX_CONTRACTS = 6
PER_CALL_USD = 0.01
DEFAULT_TODAY = "2026-08-29"                              # decks that carry no asof of their own

CFG = _REPO / "configs" / "graphrag"
CONTAGION = CFG / "eval_queries_q0_contagion_v1.yaml"
BOUNDARY = CFG / "xc_planner_boundary_deck_v1.yaml"
TYPO = CFG / "xc_open_typo_deck_v1.yaml"
V4 = CFG / "eval_queries_v4_cascade.yaml"
FENCE = CFG / "xc_fence_deck_v1.yaml"
OUT = _REPO / "data" / "batch_runs" / "xc_gate" / "g1_soak.json"

# G1-e's five rows, BY ID. Three never-volunteer negatives + two positives -- P2: a fence cell that
# only counts negatives cannot see a recall collapse, so both halves are barred.
RV2_NEG = ("rv2_neg_single_commodity_palm", "rv2_neg_context_mention_palm",
           "rv2_neg_single_commodity_soyoil")
RV2_POS = ("rv2_decline_untracked_sibling", "rv2_pos_explicit_palm_to_soyoil")
RV2_IDS = RV2_NEG + RV2_POS

CELLS = ("g1-0", "g1-a", "g1-c", "g1-d", "g1-e", "g1-f", "g1-g")
PAID = {"g1-0": 14 * 3, "g1-a": 14 * 3, "g1-c": 24, "g1-d": 6 * 3, "g1-e": 5 * 3,
        "g1-f": 0, "g1-g": 84 * 2}


def _ascii(s) -> str:
    """The owner's console is cp1252: stdout stays ASCII-only (UTF-8 files are fine)."""
    return str(s).encode("ascii", "replace").decode()


# ── deck loading (no API, no network) ────────────────────────────────────────────────────────────
def _yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _rows(path: Path, key: str = "rows") -> list:
    doc = _yaml(path)
    return list(doc.get(key) or [])


def contagion_rows() -> list:
    rows = _rows(CONTAGION, "queries")
    if len(rows) != 14:
        raise SystemExit(f"REFUSED: contagion deck holds {len(rows)} rows, not the frozen 14 -- every "
                         f"pre-registered bar in this wave is stated over those 14.")
    return rows


def v4_rv2_rows() -> list:
    by_id = {r.get("id"): r for r in _rows(V4, "queries")}
    missing = [i for i in RV2_IDS if i not in by_id]
    if missing:
        raise SystemExit(f"REFUSED: v4_cascade is missing the rv2 fence rows {missing} -- G1-e is the "
                         f"single most load-bearing cell in the wave and cannot be scored without them.")
    return [by_id[i] for i in RV2_IDS]


# ── scoring (PURE: reads recorded draws, never the network) ──────────────────────────────────────
def is_open_target(target) -> bool:
    """An OPEN target: null, or a COLLECTIVE phrase. `is_collective_span` is the ONE producer -- the
    same symbol `xc_detect_two_tier`'s llm lane consumes, never a reimplementation."""
    return target is None or bool(orch.is_collective_span(target))


def row_verdict(expect: str, draws: list) -> dict:
    """One row's verdict over its draws. `draws` are recorded plan fields; a draw carrying `errored` is
    UNSCORED (an unscored negative is not a passed negative -- the xc_fence S2-3 rule).

      expect == 'nofire'     PASS iff NO scored draw returned xc_explicit=true, and >=1 draw scored.
      expect == 'fire_open'  a draw HITS iff xc_explicit is true AND the target is open (null or
                             collective); PASS at >= 2 of 3 (P15 -- a robustness verdict must not rest
                             on single samples). `invented` counts draws that fired with a NAMED,
                             non-collective target: the prompt forbids that in terms, so it is a
                             reportable defect on its own axis (G1-b).
    """
    ok = [d for d in draws if not d.get("errored")]
    errs = len(draws) - len(ok)
    fires = sum(1 for d in ok if d.get("xc_explicit") is True)
    hits = sum(1 for d in ok if d.get("xc_explicit") is True and is_open_target(d.get("xc_target")))
    invented = sum(1 for d in ok if d.get("xc_explicit") is True
                   and not is_open_target(d.get("xc_target")))
    out = {"draws": len(draws), "scored": len(ok), "errored": errs, "fires": fires,
           "open_hits": hits, "invented": invented}
    if expect == "nofire":
        out["pass"] = bool(ok) and fires == 0
    else:
        out["pass"] = bool(ok) and hits * 3 >= 2 * len(ok)
    return out


def majority_route(draws: list):
    """The MAJORITY (steps, contracts) signature over a row's draws -- the routing shape G1-f compares
    across the two prompts. Ties break on first-seen, which is deterministic given the draw order."""
    sigs = [(tuple(d.get("steps") or []), tuple(d.get("contracts") or []))
            for d in draws if not d.get("errored")]
    if not sigs:
        return None
    return collections.Counter(sigs).most_common(1)[0][0]


def named_but_unnamed_in_question(question: str, draws: list) -> list:
    """G1-b's strict form: a NAMED, non-collective target whose surface text does not appear in the
    turn. Naming one would be SELECTING the market, and selection is not the planner's job."""
    q = (question or "").lower()
    return sorted({str(d.get("xc_target")) for d in draws
                   if d.get("xc_explicit") is True and not is_open_target(d.get("xc_target"))
                   and str(d.get("xc_target") or "").lower() not in q})


# ── the run half ─────────────────────────────────────────────────────────────────────────────────
def _load_fence_helpers():
    """`scripts/xc_fence.py` by file location (scripts is not a package). ONE producer for the serving
    graph load, the non-toy refusal, the enum hash and the temperature-recording call wrapper."""
    spec = importlib.util.spec_from_file_location("xc_fence_helpers", _REPO / "scripts" / "xc_fence.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def draw(row: dict, *, graph, inner_call, xc_open: bool, today: str, helpers) -> dict:
    """ONE plan_turn draw. Records the RAW plan fields the artifact must carry to be re-auditable
    offline: xc_explicit, xc_target, steps and contracts. A raise, a silent fallback or a degraded
    model marks the draw UNSCORED rather than letting it read as a clean no-fire."""
    rec: dict = {}
    plan = dp.plan_turn(row.get("question") or "", graph=graph,
                        state_block=row.get("state_block"), today=today,
                        state_contracts=row.get("state_contracts"),
                        call=helpers.make_call(inner_call, rec), model=SEAT,
                        max_contracts=MAX_CONTRACTS, xc_open=xc_open)
    if rec.get("error"):
        return {"errored": rec["error"], "temperature": rec.get("temperature")}
    if plan.fallback:
        return {"errored": "planner_fallback (no raise)", "temperature": rec.get("temperature")}
    if plan.degraded:
        return {"errored": "degraded_model (Sonnet->Haiku)", "temperature": rec.get("temperature")}
    return {"xc_explicit": plan.xc_explicit is True, "xc_target": plan.xc_target,
            "steps": list(plan.steps), "contracts": list(plan.contracts),
            "temperature": rec.get("temperature")}


def run_rows(rows, *, graph, inner_call, xc_open, draws, today_of, helpers) -> list:
    out = []
    for row in rows:
        today = today_of(row)
        reps = [draw(row, graph=graph, inner_call=inner_call, xc_open=xc_open, today=today,
                     helpers=helpers) for _ in range(draws)]
        out.append({"id": row.get("id"), "question": row.get("question"), "today": today,
                    "expect": row.get("expect"), "draws": reps})
        fired = sum(1 for d in reps if d.get("xc_explicit"))
        print(f"    {_ascii(row.get('id')):<44} fires={fired}/{len(reps)}")
    return out


def _today_of(default: str):
    return lambda row: str(row.get("asof") or default)


# ── the cells ────────────────────────────────────────────────────────────────────────────────────
def cell_contagion(name, xc_open, *, graph, inner_call, helpers, draws=3) -> dict:
    rows = contagion_rows()
    return {"cell": name, "xc_open": xc_open, "draws_per_row": draws,
            "rows": run_rows(rows, graph=graph, inner_call=inner_call, xc_open=xc_open,
                             draws=draws, today_of=_today_of(DEFAULT_TODAY), helpers=helpers)}


def cell_boundary(*, graph, inner_call, helpers) -> dict:
    """1 draw per row; ANY row returning xc_explicit=true is re-drawn THREE more times. 1-4 of 4 firing
    is a STOP either way -- the re-draws exist to CHARACTERISE a failure, never to rescue it."""
    rows = _rows(BOUNDARY)
    scored = run_rows(rows, graph=graph, inner_call=inner_call, xc_open=True, draws=1,
                      today_of=_today_of(DEFAULT_TODAY), helpers=helpers)
    by_id = {r["id"]: r for r in rows}
    for rec in scored:
        if any(d.get("xc_explicit") for d in rec["draws"]):
            print(f"    RE-DRAW (fired once): {_ascii(rec['id'])}")
            extra = run_rows([by_id[rec["id"]]], graph=graph, inner_call=inner_call, xc_open=True,
                             draws=3, today_of=_today_of(DEFAULT_TODAY), helpers=helpers)
            rec["draws"].extend(extra[0]["draws"])
    return {"cell": "g1-c", "xc_open": True, "draws_per_row": "1 (+3 on any fire)", "rows": scored}


def cell_typo(*, graph, inner_call, helpers) -> dict:
    return {"cell": "g1-d", "xc_open": True, "draws_per_row": 3,
            "rows": run_rows(_rows(TYPO), graph=graph, inner_call=inner_call, xc_open=True, draws=3,
                             today_of=_today_of(DEFAULT_TODAY), helpers=helpers)}


def cell_fence_rows(*, graph, inner_call, helpers) -> dict:
    return {"cell": "g1-e", "xc_open": True, "draws_per_row": 3,
            "rows": run_rows(v4_rv2_rows(), graph=graph, inner_call=inner_call, xc_open=True, draws=3,
                             today_of=_today_of(DEFAULT_TODAY), helpers=helpers)}


def cell_fence_deck(*, graph, inner_call, helpers) -> dict:
    """The SHIPPED 84-row fence deck through BOTH prompts, 1 draw each. The deterministic detector is
    untouched by this wave, so its regex verdicts cannot move -- but the PLANNER's xc_explicit can, and
    that is what the amended prose could regress. Measured, not assumed."""
    doc = _yaml(FENCE)
    rows = list(doc.get("rows") or [])
    today = _today_of(str(doc.get("today") or DEFAULT_TODAY))
    print("  [g1-g] today's prompt")
    off = run_rows(rows, graph=graph, inner_call=inner_call, xc_open=False, draws=1,
                   today_of=today, helpers=helpers)
    print("  [g1-g] amended prompt")
    on = run_rows(rows, graph=graph, inner_call=inner_call, xc_open=True, draws=1,
                  today_of=today, helpers=helpers)
    return {"cell": "g1-g", "xc_open": "both", "draws_per_row": 1, "rows_off": off, "rows_on": on}


# ── the bars ─────────────────────────────────────────────────────────────────────────────────────
def _verdict(ok: bool) -> str:
    return "PASS" if ok else "STOP"


def score_bars(cells: dict) -> list:
    """Every evaluated bar, as {bar, verdict, detail}. A cell that was not run yields no bar -- a bar
    that was never measured is never reported as passed."""
    bars = []
    a = cells.get("g1-a")
    if a:
        rows = [(r, row_verdict("fire_open", r["draws"])) for r in a["rows"]]
        passed = [r["id"] for r, v in rows if v["pass"]]
        bars.append({"bar": "G1-a OPEN RECALL (>= 9 of 14)", "verdict": _verdict(len(passed) >= 9),
                     "detail": f"{len(passed)}/14 rows fired with an open target on >=2/3 draws",
                     "rows_passed": passed,
                     "rows_failed": [r["id"] for r, v in rows if not v["pass"]]})
        invented = {r["id"]: named_but_unnamed_in_question(r["question"], r["draws"])
                    for r in a["rows"]}
        invented = {k: v for k, v in invented.items() if v}
        bars.append({"bar": "G1-b NO INVENTION (0 of 14)", "verdict": _verdict(not invented),
                     "detail": f"{len(invented)} rows named a market the turn does not name",
                     "rows": invented})
    c = cells.get("g1-c")
    if c:
        rows = [(r, row_verdict("nofire", r["draws"])) for r in c["rows"]]
        failed = [r["id"] for r, v in rows if not v["pass"]]
        bars.append({"bar": "G1-c BOUNDARY (24/24 false)", "verdict": _verdict(not failed),
                     "detail": f"{len(rows) - len(failed)}/{len(rows)} rows held on every draw",
                     "rows_failed": failed})
    d = cells.get("g1-d")
    if d:
        rows = [(r, row_verdict("fire_open", r["draws"])) for r in d["rows"]]
        passed = [r["id"] for r, v in rows if v["pass"]]
        n = len(passed)
        note = ("" if n >= 5 else ("  PARTIAL: the robustness claim is half-earned" if n >= 3
                                   else "  the amendment failed its stated purpose"))
        bars.append({"bar": "G1-d TYPO (>= 5 of 6)", "verdict": _verdict(n >= 5),
                     "detail": f"{n}/6 rows passed at >=2/3 draws{note}",
                     "partial": bool(3 <= n < 5),
                     "rows_failed": [r["id"] for r, v in rows if not v["pass"]]})
    e = cells.get("g1-e")
    if e:
        by_id = {r["id"]: r for r in e["rows"]}
        neg_bad = [i for i in RV2_NEG
                   if any(x.get("xc_explicit") for x in by_id[i]["draws"] if not x.get("errored"))]
        pos_bad = [i for i in RV2_POS
                   if not all(x.get("xc_explicit") for x in by_id[i]["draws"] if not x.get("errored"))]
        bars.append({"bar": "G1-e FENCE (3 negatives false, 2 positives true, EVERY draw)",
                     "verdict": _verdict(not neg_bad and not pos_bad),
                     "detail": f"negatives fired: {neg_bad or 'none'}; positives lost: {pos_bad or 'none'}",
                     "negatives_fired": neg_bad, "positives_lost": pos_bad})
    f = cells.get("g1-f")
    if f:
        bars.append({"bar": "G1-f ROUTING DRIFT (<= 2 of 14)", "verdict": _verdict(len(f["drifted"]) <= 2),
                     "detail": f"{len(f['drifted'])}/14 rows changed steps or contracts",
                     "rows": f["drifted"]})
    g = cells.get("g1-g")
    if g:
        off = sum(1 for r in g["rows_off"] for x in r["draws"] if x.get("xc_explicit"))
        on = sum(1 for r in g["rows_on"] for x in r["draws"] if x.get("xc_explicit"))
        bars.append({"bar": "G1-g FENCE DECK (no increase vs today's prompt)",
                     "verdict": _verdict(on <= off),
                     "detail": f"xc_explicit=true: today {off} -> amended {on}",
                     "off": off, "on": on})
    return bars


def drift_cell(base: dict, treat: dict) -> dict:
    """G1-f, FREE. The treatment changes the dispatch system prompt, so it can perturb `steps` or
    `contracts` on rows where nothing fires. Drift rows are NAMED and excluded from any paired judged
    headline whatever the count -- the D-DV-1 moving-denominator lesson."""
    b = {r["id"]: majority_route(r["draws"]) for r in base["rows"]}
    t = {r["id"]: majority_route(r["draws"]) for r in treat["rows"]}
    drifted = []
    for rid in b:
        if b[rid] != t.get(rid):
            drifted.append({"id": rid,
                            "today": {"steps": list(b[rid][0]), "contracts": list(b[rid][1])}
                            if b[rid] else None,
                            "amended": {"steps": list(t[rid][0]), "contracts": list(t[rid][1])}
                            if t.get(rid) else None})
    return {"cell": "g1-f", "calls": 0, "drifted": drifted,
            "majority_today": {k: [list(v[0]), list(v[1])] if v else None for k, v in b.items()},
            "majority_amended": {k: [list(v[0]), list(v[1])] if v else None for k, v in t.items()}}


# ── plan / dry run ───────────────────────────────────────────────────────────────────────────────
def print_plan(chosen) -> float:
    lo = sum(PAID[c] for c in chosen)
    hi = lo + (12 * 3 if "g1-c" in chosen else 0)             # <=12 boundary rows could each re-draw x3
    print("CALL PLAN")
    print(f"  seat={SEAT}  temperature=0  max_contracts={MAX_CONTRACTS}")
    for c in CELLS:
        mark = "RUN " if c in chosen else "skip"
        print(f"  {mark} {c:<5} {PAID[c]:>4} calls" + ("   (derived from g1-0 x g1-a)" if c == "g1-f" else ""))
    print(f"  total: {lo}-{hi} calls  ~${lo * PER_CALL_USD:.2f}-${hi * PER_CALL_USD:.2f} "
          f"at ${PER_CALL_USD:.2f}/call")
    core = [c for c in chosen if c != "g1-g"]
    clo = sum(PAID[c] for c in core)
    chi = clo + (36 if "g1-c" in core else 0)
    print(f"  of which the c1 core (g1-0/a/c/d/e + the free g1-f) = {clo}-{chi} calls "
          f"~${clo * PER_CALL_USD:.2f}-${chi * PER_CALL_USD:.2f}"
          + (f", and g1-g = {PAID['g1-g']} calls ~${PAID['g1-g'] * PER_CALL_USD:.2f}"
             if "g1-g" in chosen else ""))
    print(f"  EXPOSURE, said before not after: the spec booked $1.15 for the c1 core at ONE draw on "
          f"g1-0; P14 gives g1-0 3 draws (+28 calls, +$0.28) and P15 gives the typo rows 3 draws "
          f"(+12 calls, +$0.12). The ceiling above is the budget number.")
    return hi * PER_CALL_USD


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="D-XT G1 planner soak (plan_turn only; no walk, no judge)")
    ap.add_argument("--cells", default=",".join(CELLS),
                    help=f"comma-separated subset of {','.join(CELLS)} (default: all)")
    ap.add_argument("--dry-run", action="store_true", help="print the call plan + cost, spend nothing")
    ap.add_argument("--out", default=str(OUT), help="artifact path (UTF-8 JSON)")
    args = ap.parse_args(argv)

    chosen = [c.strip().lower() for c in args.cells.split(",") if c.strip()]
    unknown = [c for c in chosen if c not in CELLS]
    if unknown:
        print(f"REFUSED: unknown cell(s) {unknown}; known cells are {list(CELLS)}")
        return 2
    if "g1-f" in chosen and not {"g1-0", "g1-a"} <= set(chosen):
        print("REFUSED: g1-f is DERIVED from g1-0 x g1-a -- run both, or drop g1-f.")
        return 2
    chosen = [c for c in CELLS if c in chosen]                 # canonical order

    missing = [str(p) for p in (CONTAGION, BOUNDARY, TYPO, V4, FENCE) if not p.exists()]
    if missing:
        print(f"REFUSED: deck(s) absent (private configs layer): {missing}")
        return 2
    print_plan(chosen)
    if args.dry_run:
        print("DRY RUN: no API call made, nothing spent.")
        return 0
    if os.environ.get("GRAPHRAG_DISPATCH", "llm") == "rules":
        print("REFUSED: GRAPHRAG_DISPATCH=rules -- every row would silently fall back (vacuous soak).")
        return 2
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("REFUSED: ANTHROPIC_API_KEY is not set in this environment.")
        return 2

    helpers = _load_fence_helpers()
    graph = helpers.load_serving_graph()                       # REAL serving enum; toy enums refused
    from leviathan.graphrag import answer as an
    inner_call = an._call_opus
    kw = dict(graph=graph, inner_call=inner_call, helpers=helpers)

    cells: dict = {}
    for name in chosen:
        print(f"[{name}]")
        if name == "g1-0":
            cells[name] = cell_contagion("g1-0", False, **kw)
        elif name == "g1-a":
            cells[name] = cell_contagion("g1-a", True, **kw)
        elif name == "g1-c":
            cells[name] = cell_boundary(**kw)
        elif name == "g1-d":
            cells[name] = cell_typo(**kw)
        elif name == "g1-e":
            cells[name] = cell_fence_rows(**kw)
        elif name == "g1-g":
            cells[name] = cell_fence_deck(**kw)
        elif name == "g1-f":
            cells[name] = drift_cell(cells["g1-0"], cells["g1-a"])

    bars = score_bars(cells)
    doc = {"generated_utc": _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
           "wave": "D-XT round 4", "gate": "G1", "seat": SEAT, "temperature": 0,
           "max_contracts": MAX_CONTRACTS, "cells_run": chosen,
           "graph_version": getattr(graph, "version", None),
           "enum_hash": helpers.enum_hash(graph.contracts), "n_contracts": len(graph.contracts),
           "decks": {"contagion": str(CONTAGION.name), "boundary": str(BOUNDARY.name),
                     "typo": str(TYPO.name), "v4_cascade": str(V4.name), "fence": str(FENCE.name)},
           "heldout_hashes": {"boundary": helpers.heldout_hash(_yaml(BOUNDARY)),
                              "typo": helpers.heldout_hash(_yaml(TYPO))},
           "cells": cells, "bars": bars}
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")

    print("")
    print("PRE-REGISTERED BARS")
    for b in bars:
        print(f"  {b['verdict']:<4} {_ascii(b['bar']):<52} {_ascii(b['detail'])}")
    print(f"artifact: {path}")
    stopped = [b["bar"] for b in bars if b["verdict"] == "STOP"]
    print(f"VERDICT: {'STOP -- ' + _ascii(stopped[0]) if stopped else 'all evaluated bars PASS'}")
    return 1 if stopped else 0


if __name__ == "__main__":
    sys.exit(main())
