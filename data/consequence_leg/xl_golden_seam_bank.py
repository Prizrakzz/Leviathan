"""D-XL FLAG-OFF SEAM GOLDEN -- the THIRD byte-identity baseline, banked BEFORE the extreme-locator
build lands (phase 1, no product edits).

WHY A THIRD GOLDEN. The estate already holds two, and NEITHER one can see this build.

  G1  (v25_golden_bank.py -> v25_golden_head_v2.json, sha e0dc1e5d) holds ONE law: with the deep flag
      off the cascade-walk LEG is byte-identical to rev-126 serving.
  G1d (v23_golden_deep_bank.py -> v23_golden_deep_on.json) holds the same leg still INSIDE the deep
      regime.

Both wrap `_cascade_walk_leg_or_nothing`. D-XL does not touch that function. It edits the PLANNER
CONSTITUTION (dispatch.planner_sys, _plan_tool, Plan, _validate, plan_turn), the ANSWER SEAM
(answer._answer_l2's kwarg-assembly block, answer.answer, answer._system), the ORCHESTRATOR THREAD
(run_reasoning / run_hybrid) and `quantify`'s own signature -- nineteen edits (E1-E19, E32) whose
FIRST law is that with GRAPHRAG_EXTREME_LOCATOR absent every one of those surfaces renders exactly
the bytes it renders today. Nothing in the estate would notice if one of them moved.

WHAT IT MEASURES, AND WHY IT WRAPS NOTHING AT RUNTIME.

THIS IS THE FINDING THAT SHAPED THE PRODUCER, and it is a measurement, not a preference: `cq.quantify`
CANNOT BE INSTRUMENTED. A pure identity no-op rewrap --

    _ORIG = cq.quantify
    @functools.wraps(_ORIG)
    def _w(*a, **kw): return _ORIG(*a, **kw)
    cq.quantify = _w

-- with no recording of any kind, reds 10 tests across the live-path deck (measured 2026-09-04:
test_f7_stage_events.py floors its reasoning turn, losing every stage event, so
`names.index("walk")` raises ValueError; the same rewrap costs 10 reds over the seven live-path
suites, which are 329/329 GREEN without it). Deferring the import and the patch to the first
`pytest_runtest_setup` reproduces the same 10 reds, so it is the REBINDING, not the import order and
not the recording. A golden producer whose own instrument reds the deck is not a gate -- that is
G1d's own law ("the native pass MUST be green -- that is gated") -- so this producer takes the other
road: it OBSERVES the seam statically and PURELY, and perturbs nothing.

That is not a weaker measurement for THIS build. Every D-XL seam edit is an ADDITION to a signature,
a prompt render, a schema dict or a kwarg-assembly block, and all four are exactly what static and
pure observation sees byte-for-byte:

  SECTION A -- THE PLANNER SURFACE (E1, E2, E3, E4, E5, E6).
    `planner_sys()` rendered across its WHOLE argument space (max_contracts 1..6 x xc_open
    False/True = 12 renders), each hashed, plus the default render's own sha and the
    `PLANNER_SYS is planner_sys()` text identity the module constant promises. E1 inserts the XL
    block producer immediately before this function and E2 gives it a THIRD keyword: with the roster
    empty every one of these 12 renders must come back byte-identical.
    `_plan_tool(...)` serialized canonically over three roster states. E3 adds five properties "only
    when it is non-empty (the `if fams:` idiom verbatim, so an empty roster leaves the schema JSON
    byte-identical)" -- this is the assertion that sentence has to answer to.
    `Plan`'s fields as an ORDERED tuple of (name, type, default). E4 appends FIVE fields "at the
    TAIL, before `fallback`"; a field that landed anywhere else moves this tuple.

  SECTION B -- THE ANSWER SEAM AND THE THREAD (E11, E12, E16, E18, E32).
    The ORDERED parameter list of every signature the build widens: `plan_turn`, `_validate`,
    `run_reasoning`, `run_hybrid`, `answer`, `_answer_l2`, `_system`, `cq.quantify`. Each is recorded
    as (name, kind, default-repr) IN ORDER, so "appended at the TAIL so no existing keyword moves"
    (E12, E32) is checkable rather than promised.
    The kwarg-assembly BLOCK's source bytes. E16 inserts the XL kwarg "inside the same try, so the
    kwarg is built where every sibling kwarg is" -- i.e. straight into this block. The block is
    located by its two ANCHOR LINES rather than by line number (line numbers move under every edit
    above it, which would make the bank a re-banking chore instead of a gate) and hashed.
    `_system` RENDERED over a deck of kwarg shapes: the all-off shape, each existing boolean alone,
    and the prod-serving combination. E18 adds two keyword-only booleans "DEFAULT FALSE so every
    existing caller is byte-identical"; these renders are what that means.

  SECTION C -- THE OFF-STATE ITSELF.
    Every seam flag helper's value with GRAPHRAG_* stripped, and the RESOLVED kwarg key set the seam
    hands `quantify` in that state -- computed from the same helpers the seam calls, in the seam's
    own order. Plus NEGATIVE pins: the names D-XL MINTS (`_extreme_locator_on`,
    `_extreme_locator_block_on`, `_record_from`, `EXTREME_ROW_AGGS`, `extreme_locator`,
    `XL_BOARD_LABEL`, `quantify_extreme_locator`, `check_extreme_locator`) MUST NOT EXIST YET. A
    negative pin that never had a moment of being true is not a pin; this is that moment.

THE ENV IS STRIPPED IN A CHILD PROCESS, NOT IN THIS ONE. "GRAPHRAG_EXTREME_LOCATOR absent" is the
whole point of the bank, and a runner that happened to export a GRAPHRAG_* flag would otherwise bank
its own shell. The collector runs in a subprocess with every GRAPHRAG_* name popped -- the same law
the two sibling producers apply to their pytest subprocesses, for the same reason.

A BARE RE-RUN NEVER OVERWRITES THE BANK (the V2-5 producer's law, kept): `BANK` is the baseline every
later run is judged against, and re-banking it is a deliberate act taken with a measurement in hand.
Point `XL_GOLDEN_OUT` anywhere to write a comparison run.

HOW THE GATE USES IT. After the D-XL build, re-run this script with GRAPHRAG_EXTREME_LOCATOR unset.
Every section must reproduce EXACTLY, with two NAMED exceptions the build itself creates and which
the pin therefore checks rather than forbids: the `signatures` section gains its appended tail
parameters, and `negative_pins` flips to "minted". Everything else -- all 12 planner renders, all
three schema serializations, the Plan tuple, the seam block sha, every `_system` render, every flag
value and the resolved kwarg key set -- is UNCHANGED or the flag leaked. The pin is
tests/unit/test_cascade_walk.py::test_g1x_the_locator_flag_off_seam_reproduces_the_banked_head_golden.

RECURSION IS CLOSED BY THE V2-5 SENTINEL, reused verbatim (V2-3 law L10, "the V25_GOLDEN_INNER
sentinel idiom"): the pin lives in test_cascade_walk.py beside its two siblings, and BOTH sibling
producers run that whole suite in a subprocess -- so without the sentinel this pin would fire three
extra times inside their inner runs and measure nothing. It skips under it.

COST: one clean-env python import, ~5 seconds, $0, offline, no model calls, no AWS.
Re-runnable: `python data/consequence_leg/xl_golden_seam_bank.py`.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BANK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "xl_golden_seam_off.json")
# The V2-5 recursion sentinel, REUSED. One name for one fact -- "this process is a golden producer's
# own subprocess" -- read by all three pins.
INNER_ENV = "V25_GOLDEN_INNER"

# The kwarg-assembly block inside `_answer_l2` is located by ANCHOR LINES, never by line number: E1-E15
# all insert above it, so a line-numbered slice would drift on every edit and turn this gate into a
# re-banking chore. Both anchors are asserted present-and-unique by the collector.
BLOCK_START = "_pace_kw = {\"pace\": True} if _pace_leg_on() else {}"
BLOCK_END = "**_dv_kw, **_cw_kw)"
# ...AND THE ONE ANCHOR THE BUILD ITSELF LANDS ON. E16 inserts the XL kwarg INTO this block, and its
# `**_xl_kw` expansion lands on the END ANCHOR's own line -- so after the build `BLOCK_END` no longer
# occurs and a producer that only knew that string would EXIT NON-ZERO and take the whole gate with it.
# The producer accepts either, records WHICH matched, and additionally computes `sans_xl_sha256`: the
# block with the D-XL insertion CUT OUT and the expansion undone. That is the sha the pin joins against
# the BANK, so "the seam block is byte-identical apart from exactly this insertion" is a MEASUREMENT
# rather than a re-banking. Re-anchored on a named fact, never loosened.
BLOCK_END_POST = "**_eod_kw)"
# THE CUT IS A LINE SET, NOT A RANGE (review minor 6). The first version deleted everything from the
# D-XL comment through the `_eod_kw = ...` line as ONE span -- so anything inserted ANYWHERE INSIDE that
# span escaped the `sans_xl_sha256` join, and "E16 inserted a kwarg and moved nothing else" was measured
# only at the range's two edges. Each of the two insertions is now cut INDIVIDUALLY, from its own leading
# comment through its own final assignment, so a third insertion BETWEEN them survives into `sans` and
# REDS the pin. The two cuts are contiguous in the shipped source, so `sans` is byte-identical to what
# the range cut produced and the bank is unmoved -- this is a tightening, not a re-banking.
XL_INSERTS = (
    ("# D-XL: the seam CONSUMES the request the orchestrator already resolved",
     "_xl_kw = {\"extreme_locator\": _xl_req}"),
    ("# THE EXTREMA-CLOCK REPAIR, BUILT DARK",
     "_eod_kw = {\"extrema_own_date\": True} if _extrema_own_date_on() else {}"),
)

# The names D-XL MINTS. None may exist at HEAD; all must exist after the build.
NEGATIVE_PINS = [
    ("leviathan.graphrag.answer", "_extreme_locator_on"),
    ("leviathan.graphrag.answer", "_extreme_locator_block_on"),
    ("leviathan.graphrag.answer", "_record_from"),
    ("leviathan.graphrag.numbers.query", "EXTREME_ROW_AGGS"),
    ("leviathan.graphrag.numbers.stats", "extreme_locator"),
    ("leviathan.graphrag.numbers.stats", "EXTREME_TIE_RULE"),
    ("leviathan.graphrag.numbers.cascade", "XL_BOARD_LABEL"),
    ("leviathan.graphrag.numbers.cascade", "XL_CAP"),
    ("leviathan.graphrag.config_check", "check_extreme_locator"),
    ("leviathan.graphrag.dispatch", "_xl_block"),
    ("leviathan.graphrag.orchestrator", "_extreme_locator_decision"),
]

# `_system`'s deck: the all-off shape, each existing boolean ALONE, and the prod-serving combination
# (walk + deep, which is what rev 127 serves). Rendered by the real function, which is pure.
SYSTEM_DECK = [
    ("all_off", {}),
    ("outlook", {"outlook": True}),
    ("episodes_true", {"episodes": True}),
    ("episodes_false", {"episodes": False}),
    ("recency", {"recency": True}),
    ("provenance", {"provenance": True}),
    ("handles", {"handles": True}),
    ("cascade_walk", {"cascade_walk": True}),
    ("cascade_context", {"cascade_context": True}),
    ("cascade_deep", {"cascade_deep": True}),
    ("cascade_xccy", {"cascade_xccy": True}),
    ("response_contract", {"response_contract": "mentor"}),
    ("budget", {"budget": "tight"}),
    ("prod_rev127", {"cascade_walk": True, "cascade_deep": True}),
]

# The collector. Runs in a CLEAN-ENV subprocess (every GRAPHRAG_* popped) and prints one JSON blob.
COLLECTOR = r'''
import dataclasses, hashlib, inspect, importlib, json, sys

def sha(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

from leviathan.graphrag import dispatch as dp
from leviathan.graphrag import answer as an
from leviathan.graphrag import orchestrator as orc
from leviathan.graphrag.numbers import cascade as cq

BLOCK_START = json.loads(sys.argv[1])
BLOCK_END = json.loads(sys.argv[2])
NEGATIVE_PINS = json.loads(sys.argv[3])
SYSTEM_DECK = json.loads(sys.argv[4])
BLOCK_END_POST = json.loads(sys.argv[5])
XL_INSERTS = json.loads(sys.argv[6])

out = {}

# -- SECTION A: the planner surface -------------------------------------------------------------
renders = {}
for mc in range(1, 7):
    for xo in (False, True):
        txt = dp.planner_sys(mc, xc_open=xo)
        renders["mc%d_xc%d" % (mc, int(xo))] = {"sha256": sha(txt), "len": len(txt)}
default_txt = dp.planner_sys()
out["planner_sys"] = {
    "renders": renders,
    "default_sha256": sha(default_txt),
    "default_len": len(default_txt),
    # PLANNER_SYS promises to be "the same producer's rendering, never a second copy"
    "PLANNER_SYS_equals_default": dp.PLANNER_SYS == default_txt,
    "PLANNER_SYS_sha256": sha(dp.PLANNER_SYS),
}

schemas = {}
for label, ids, mc in (("two_ids_mc2", ["corn_cbot", "wheat_srw"], 2),
                       ("empty_mc2", [], 2),
                       ("six_ids_mc6", ["corn_cbot", "wheat_srw", "soybeans_cbot",
                                        "soybean_oil", "soybean_meal", "cotton_ice"], 6)):
    body = json.dumps(dp._plan_tool(ids, mc), ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))
    schemas[label] = {"sha256": sha(body), "len": len(body)}
out["plan_tool"] = schemas

out["plan_fields"] = [[f.name, str(f.type),
                       ("__MISSING__" if f.default is dataclasses.MISSING else repr(f.default))]
                      for f in dataclasses.fields(dp.Plan)]

# -- SECTION B: signatures, the seam block, and _system ------------------------------------------
def sig_of(fn):
    ps = []
    for p in inspect.signature(fn).parameters.values():
        ps.append([p.name, str(p.kind),
                   ("__EMPTY__" if p.default is inspect.Parameter.empty else repr(p.default))])
    return ps

out["signatures"] = {
    "dispatch.planner_sys": sig_of(dp.planner_sys),
    "dispatch._plan_tool": sig_of(dp._plan_tool),
    "dispatch.plan_turn": sig_of(dp.plan_turn),
    "dispatch._validate": sig_of(dp._validate),
    "orchestrator.run_reasoning": sig_of(orc.run_reasoning),
    "orchestrator.run_hybrid": sig_of(orc.run_hybrid),
    "answer.answer": sig_of(an.answer),
    "answer._answer_l2": sig_of(an._answer_l2),
    "answer._system": sig_of(an._system),
    "cascade.quantify": sig_of(cq.quantify),
}

# THE SEAM BLOCK, located by anchors and asserted UNIQUE -- a duplicated anchor would silently bank
# the wrong slice, which is the one way this measurement could lie.
src = inspect.getsource(an._answer_l2)
end_anchor = BLOCK_END if src.count(BLOCK_END) == 1 else BLOCK_END_POST
i, j = src.find(BLOCK_START), src.find(end_anchor)
assert i != -1 and j != -1, "seam anchors not found -- re-anchor the producer, never loosen it"
assert src.count(BLOCK_START) == 1, "BLOCK_START is not unique in _answer_l2"
assert src.count(end_anchor) == 1, "the end anchor is not unique in _answer_l2"
assert i < j, "seam anchors are inverted"
block = src[i:j + len(end_anchor)]
# THE D-XL INSERTIONS, CUT OUT ONE NAMED LINE SET AT A TIME so the PRE-BUILD block is recoverable from
# the POST-BUILD source, plus the `, **_xl_kw` the expansion added on the end-anchor line. What remains
# must be BYTE-IDENTICAL to the banked HEAD block -- the claim "E16 inserted a kwarg and moved nothing
# else", made checkable instead of promised.
#
# EACH INSERTION IS ITS OWN CUT, from its own leading comment through its own final assignment. A single
# cut spanning both would swallow ANYTHING inserted between them, so the measurement would hold only at
# the span's two edges; cut separately, a third insertion landing between the two survives into `sans`
# and reds the pin. Each anchor is asserted UNIQUE, and the ORDER is asserted too -- a cut whose end
# anchor precedes its start would delete the wrong bytes silently.
sans = block
n_cuts = 0
for _start, _end in XL_INSERTS:
    if _start not in sans or _end not in sans:
        continue
    assert sans.count(_start) == 1, "XL insert start anchor is not unique: %r" % _start
    assert sans.count(_end) == 1, "XL insert end anchor is not unique: %r" % _end
    assert sans.index(_start) < sans.index(_end), "XL insert anchors are inverted: %r" % _start
    a = sans.rfind("\n", 0, sans.index(_start)) + 1
    b = sans.index(_end) + len(_end)
    b = sans.find("\n", b) + 1
    sans = sans[:a] + sans[b:]
    n_cuts += 1
import re as _re
sans = _re.sub(r",\s*\*\*_eod_kw\)", ")", sans)
sans = sans.replace(", **_xl_kw", "")
out["seam_block"] = {"sha256": sha(block), "len": len(block),
                     "n_lines": block.count("\n") + 1,
                     "start_anchor": BLOCK_START, "end_anchor": end_anchor,
                     # THE RE-ANCHOR: this is what the pin joins against the BANK's own `sha256`.
                     "sans_xl_sha256": sha(sans), "sans_xl_len": len(sans),
                     "xl_insert_cuts": n_cuts,
                     "xl_insert_present": sans != block}

sysd = {}
for label, kw in SYSTEM_DECK:
    txt = an._system(**kw)
    sysd[label] = {"sha256": sha(txt), "len": len(txt)}
out["system_deck"] = sysd

# -- SECTION C: the off state itself --------------------------------------------------------------
flags = {}
for n in sorted(dir(an)):
    if not (n.startswith("_") and n.endswith("_on")):
        continue
    f = getattr(an, n)
    if not callable(f):
        continue
    try:
        if len(inspect.signature(f).parameters) == 0:
            flags[n] = f()
    except (TypeError, ValueError):
        pass
flags["_series_newest_first_on"] = an._series_newest_first_on()
flags["_futures_newest_first_on"] = an._futures_newest_first_on()
out["flags_off"] = flags

# THE RESOLVED KWARG KEY SET, in the seam's OWN order, from the seam's OWN helpers. This is what
# `quantify` is handed on a flag-off turn; E16 must not add a key to it.
seam_keys = []
if an._pace_leg_on():
    seam_keys.append("pace")
if an._chain_on():
    seam_keys.append("chain")
if an._transmission_on():
    seam_keys.append("transmission")
if an._headline_on():
    seam_keys.append("headline")
if an._outlook_on():
    seam_keys.append("outlook")
if an._episode_outcomes_on():
    seam_keys.append("episode_outcomes")
if an._cot_outcomes_on():
    seam_keys.append("cot_outcomes")
if an._newest_first_scope(an._futures_newest_first_on(), an._series_newest_first_on()):
    seam_keys.append("futures_newest_first")
if an._rv_reading_on():
    seam_keys.append("rv_reading")
if an._rv_regional_on():
    seam_keys.append("rv_regional")
if an._derived_arith_on():
    seam_keys.append("derived_arith")
if an._cascade_walk_on():
    seam_keys.append("cascade_walk")
# price_replay rides the turn's asof, never an env flag, so it is NOT part of the off-state key set;
# it is named here so the omission is a measurement rather than a gap.
out["seam_kwarg_keys_off"] = {"keys": seam_keys,
                              "always_passed": ["qfn", "asof", "near", "extra_number_calls",
                                                "xc_request", "comove", "price_request"],
                              "asof_dependent_not_env": ["price_replay"]}

neg = {}
for mod, name in NEGATIVE_PINS:
    # AN UNIMPORTABLE MODULE IS A BROKEN PIN, NEVER A PASSING ONE. The first cut of this producer
    # spelled two of these `leviathan.graphrag.query` / `.stats` -- they live under `.numbers.` --
    # and a swallowed ModuleNotFoundError banked "absent" for a name it had never actually looked
    # for. A negative pin that cannot fail is not a pin, so this raises instead.
    m = importlib.import_module(mod)
    neg["%s.%s" % (mod, name)] = hasattr(m, name)
out["negative_pins"] = neg

sys.stdout.write(json.dumps(out, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
'''


def main() -> int:
    out_path = (os.environ.get("XL_GOLDEN_OUT")
                or os.path.join(os.path.dirname(BANK), "xl_golden_seam_rerun.json"))
    env = dict(os.environ, PYTHONPATH=os.path.join(REPO, "src"))
    for k in list(env):
        if k.startswith("GRAPHRAG_"):
            env.pop(k)          # THE POINT OF THE BANK: the locator flag, and every sibling flag,
            #                     absent. A runner's shell must never ride into a golden.
    env[INNER_ENV] = "1"        # all three golden pins skip inside a producer's own subprocess
    proc = subprocess.run(
        [sys.executable, "-c", COLLECTOR,
         json.dumps(BLOCK_START), json.dumps(BLOCK_END),
         json.dumps(NEGATIVE_PINS), json.dumps(SYSTEM_DECK),
         json.dumps(BLOCK_END_POST), json.dumps([list(p) for p in XL_INSERTS])],
        cwd=REPO, env=env, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.stderr.write((proc.stdout or "")[-3000:] + (proc.stderr or "")[-4000:])
        return 1
    payload = json.loads(proc.stdout)
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    sha = hashlib.sha256(body.encode("utf-8")).hexdigest()
    doc = {
        "what": ("D-XL FLAG-OFF SEAM GOLDEN -- the planner surface, the answer-seam signatures and "
                 "kwarg-assembly block, the _system deck and the resolved off-state, measured with "
                 "every GRAPHRAG_* name absent. Wraps nothing: cq.quantify cannot be rewrapped "
                 "without flooring the live-path deck (10 reds on a pure no-op, measured)."),
        "basis": "HEAD 9f928623 (product surface identical to 6679c154: HEAD touches only "
                 "infra/terraform/envs/dev/variables.tf)",
        "collector": "one clean-env python subprocess, no pytest, no wrapping",
        "bank_sha256": sha,
        "sections": sorted(payload),
        "how_the_gate_uses_it": (
            "re-run with GRAPHRAG_EXTREME_LOCATOR unset after the build; every section must "
            "reproduce EXACTLY except the two the build itself creates and which the pin checks "
            "rather than forbids: `signatures` gains its appended TAIL parameters, and "
            "`negative_pins` flips to minted"),
        "bank": payload,
    }
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1, sort_keys=False)
    print("wrote %s  sha256=%s" % (out_path, sha))
    print("  planner renders=%d  plan_tool=%d  plan_fields=%d  signatures=%d  system_deck=%d"
          % (len(payload["planner_sys"]["renders"]), len(payload["plan_tool"]),
             len(payload["plan_fields"]), len(payload["signatures"]),
             len(payload["system_deck"])))
    print("  seam_block sha=%s len=%d  off_kwarg_keys=%r"
          % (payload["seam_block"]["sha256"][:12], payload["seam_block"]["len"],
             payload["seam_kwarg_keys_off"]["keys"]))
    print("  negative_pins minted_at_head=%r"
          % sorted(k for k, v in payload["negative_pins"].items() if v is True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
