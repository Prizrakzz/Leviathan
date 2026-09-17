"""THE COST CENSUS SEAMS (lane F, 2026-09-17) -- the two producers outside `eval.py`.

THE DEFECT, MEASURED ON THE 2026-09-16 IN-VPC PRE-ARM SMOKE (`prearm_smoke_0916/COST_LATENCY.md`):
`eval._turn_cost_usd` is the estate's ONE money column and it prices the WRITER and nothing else --
its own docstring says so. Five real turns read **$2.5643** in it against a **PROVEN floor of
$3.9251** and a modelled **$5.6656**, so every budget built by scaling that column under-counts a
hybrid turn by 35-55%. The owner read "~$4 on the console" against a report that said $2.56 and the
report was not lying, it was answering a narrower question than the one being asked of it.

Of the six Anthropic seats on a hybrid turn, exactly one was stamped. This deck pins the two seams
that stop the other two IN-TURN seats being thrown away:

  DISPATCH PLANNER   `an._call_opus` TAGS `_usage` on the reply and
                     `dispatch._validate` normalises it away, so one sonnet-4-6 call per turn -- 4.0
                     to 4.9 s of EVERY turn's wall clock, dead flat across tiers -- was recorded
                     NOWHERE in the estate. `plan_turn` now keeps it.
  NUMBERS AGENT      the LARGEST unstamped seat ($8.84 of a $35 arm, 46-73% of wall clock). The agent
                     stamps per-round usage under the flag; `orchestrator` carries it in the SAME
                     GUARDED IDIOM as `ms_numbers` and `numbers_budget`, never in the unguarded `_sk`
                     copy tuple -- a key placed there would land on EVERY hybrid turn with the flags
                     off, which is the exact defect `numbers_budget`'s own note records.

THE FLAG. `GRAPHRAG_COST_CENSUS`, default OFF, strict `on|1|true`. It exists because the stamps would
otherwise reach EVERY turn including serving's, breaking the estate's "flag off => byte-identical
trace" law. It is declared in `arm_env_base.yaml` under `arm_only`, CONSTANT ACROSS BOTH CELLS of arm
A, so it cannot touch a judged delta, and it changes no request, no prompt byte and no rendered byte.

NO NETWORK, NO AWS, NO LLM, NO pg.
"""
from __future__ import annotations

import pathlib

import pytest
from leviathan.causal import schema as cs
from leviathan.graphrag import dispatch as dp
from leviathan.graphrag import graph as g
from leviathan.graphrag import orchestrator as orch
from leviathan.graphrag import tracekeys as tk
from leviathan.graphrag.numbers import agent as ag

_ORCH_SRC = pathlib.Path(orch.__file__).read_text(encoding="utf-8")


def _graph() -> g.CausalGraph:
    return g.CausalGraph({"corn": cs.CausalContract(
        contract="corn", aliases=[],
        drivers=[cs.Driver(id="drought", type="hazard", sign="+", mechanism="m")])}, silver=set())


_USAGE = {"model": "claude-sonnet-4-6", "in": 80, "out": 600, "cache_read": 8800, "cache_write": 0}


def _call(seen: list):
    """A planner `call` in `an._call_opus`'s own shape: the plan dict WITH the `_usage` pop-tag on it."""
    def _c(*_a, **_k):
        out = {"steps": ["reasoning"], "contracts": ["corn"], "_usage": dict(_USAGE)}
        seen.append(out)
        return out
    return _c


# ── the flag itself ───────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("val,on", [("on", True), ("1", True), ("true", True), ("TRUE", True),
                                    (" on ", True), ("yes", False), ("off", False), ("", False),
                                    ("0", False), ("no", False)])
def test_the_census_flag_takes_the_strict_grammar_and_defaults_off(monkeypatch, val, on):
    """THE STRICT `on|1|true` GRAMMAR, NOT `_stats_tool_on`'s FAIL-SAFE-ON ONE. This ships OFF and a
    typo must never silently arm a trace-key change on the serving lane. `arm_env_base.yaml` already
    records what a spelling mismatch costs: `--env GRAPHRAG_STATE_BOARD=yes` ran a CONTROL turn at
    treatment price, named and logged as a full treatment, and only a post-spend precondition caught
    it -- which is why `yes` is FALSE here rather than quietly accepted.

    ROUND-2 REVIEW M1: the grammar now lives ONCE, in `tracekeys.cost_census_on` -- the leaf module
    that already declares the three keys this flag gates -- and `dispatch._cost_census_on` is a
    delegation with no grammar of its own. Both are asserted here; the cross-reader pin below asserts
    the numbers agent's reader against the same canonical answer."""
    monkeypatch.setenv("GRAPHRAG_COST_CENSUS", val)
    assert tk.cost_census_on() is on                           # THE canonical reader
    assert dp._cost_census_on() is on                          # ...and the delegation agrees
    monkeypatch.delenv("GRAPHRAG_COST_CENSUS")
    assert tk.cost_census_on() is False                        # DEFAULT OFF, no env at all
    assert dp._cost_census_on() is False


@pytest.mark.parametrize("val", ["on", "1", "true", "TRUE", " on ", "yes", "YES", "y", "enabled",
                                 "off", "", "0", "no"])
def test_every_reader_of_the_one_flag_agrees_on_every_spelling(monkeypatch, val):
    """ROUND-2 REVIEW M1 -- ONE FLAG, ONE GRAMMAR, AND THE TEST IMPORTS EVERY READER OF IT.

    ROUND 1 SHIPPED TWO GRAMMARS FOR ONE FLAG AND I MEASURED THE CONSEQUENCE IN ONE PROCESS:

        'on'   dispatch=True   numbers_agent=True
        'yes'  dispatch=False  numbers_agent=True     <- HALF-ARMED
        'YES'  dispatch=False  numbers_agent=True

    `GRAPHRAG_COST_CENSUS=yes` therefore stamped the numbers agent -- the LARGEST seat, $8.84 of a $35
    arm -- while this planner's pop and the judge's usage stayed dark, and the Spend panel then printed
    a "total" that looked complete while silently omitting two seats. Nothing caught it:
    `submit_eval.arm_value_refusal` inspects `arm_flags` only, and the census is DELIBERATELY not a
    treatment flag. This is the same defect class the pre-arm seams commit (17fed3e4) exists to close.

    THE FIX IS STRUCTURAL -- one grammar in the leaf registry, imported -- and THIS PIN IS WHAT KEEPS
    IT ONE: a reader that re-spells the grammar anywhere in `src/` fails here rather than half-arming
    a paid arm. It imports every reader in the estate by name, so a new one must be added here too."""
    monkeypatch.setenv("GRAPHRAG_COST_CENSUS", val)
    canonical = tk.cost_census_on()
    assert dp._cost_census_on() is canonical, val
    assert ag._cost_census_on() is canonical, val


# ── the dispatch planner's seat ───────────────────────────────────────────────────────────────────
def test_plan_turn_keeps_the_planner_usage_only_under_the_flag(monkeypatch):
    """WITH THE FLAG ON the usage is popped off the reply and hung on the validated plan. WITH IT OFF
    NOT ONE BYTE MOVES: `_usage` is NOT popped, so `_validate` receives HEAD's exact dict, and no
    attribute is set, so `Plan` is HEAD's dataclass with HEAD's fields."""
    monkeypatch.delenv("GRAPHRAG_DISPATCH", raising=False)
    seen: list = []
    monkeypatch.delenv("GRAPHRAG_COST_CENSUS", raising=False)
    p = dp.plan_turn("why corn", graph=_graph(), call=_call(seen))
    assert not p.fallback and p.contracts == ["corn"]
    assert getattr(p, "plan_usage", None) is None
    assert seen[0]["_usage"] == _USAGE                        # NOT popped: `_validate` saw HEAD's dict

    seen2: list = []
    monkeypatch.setenv("GRAPHRAG_COST_CENSUS", "on")
    q = dp.plan_turn("why corn", graph=_graph(), call=_call(seen2))
    assert q.plan_usage == _USAGE
    assert "_usage" not in seen2[0]                           # popped BEFORE `_validate` normalised it
    # THE PLAN ITSELF IS OTHERWISE IDENTICAL -- the seam records, it never routes
    assert (q.steps, q.contracts, q.asof, q.near, q.fallback) == \
           (p.steps, p.contracts, p.asof, p.near, p.fallback)


def test_the_shared_fallback_singleton_is_never_stamped(monkeypatch):
    """`_FALLBACK` IS A MODULE-LEVEL SINGLETON and `_validate` returns IT, not a copy, on every bad
    plan. Stamping it would leak ONE turn's usage onto EVERY later fallback plan in the process -- the
    class of defect a shared mutable default argument is. Pinned because the guard is one `is not`."""
    monkeypatch.setenv("GRAPHRAG_COST_CENSUS", "on")
    monkeypatch.delenv("GRAPHRAG_DISPATCH", raising=False)

    def _bad(*_a, **_k):
        return {"steps": [], "contracts": [], "_usage": dict(_USAGE)}     # empty steps -> _FALLBACK

    p = dp.plan_turn("why corn", graph=_graph(), call=_bad)
    assert p is dp._FALLBACK and p.fallback
    assert getattr(dp._FALLBACK, "plan_usage", None) is None
    # ...and a GOOD plan right after it is still stamped, so the guard fenced the singleton and
    # nothing else
    assert dp.plan_turn("why corn", graph=_graph(), call=_call([])).plan_usage == _USAGE
    assert getattr(dp._FALLBACK, "plan_usage", None) is None


def test_a_planner_exception_still_falls_back_and_stamps_nothing(monkeypatch):
    """ROUTING MUST NEVER BREAK AN ANSWER -- the module's own law, unchanged. The pop sits INSIDE the
    same `try`, so a reply of a shape the pop cannot read takes the identical fallback path."""
    monkeypatch.setenv("GRAPHRAG_COST_CENSUS", "on")
    monkeypatch.delenv("GRAPHRAG_DISPATCH", raising=False)

    def boom(*_a, **_k):
        raise RuntimeError("provider down")

    assert dp.plan_turn("q", graph=_graph(), call=boom) is dp._FALLBACK
    assert getattr(dp._FALLBACK, "plan_usage", None) is None


# ── the numbers agent's seat, at the orchestrator's two copy seams ────────────────────────────────
def test_numbers_usage_rides_its_own_guarded_line_and_never_the_unguarded_copy_tuple():
    """THE STRUCTURAL PIN, and it is the one that matters. `orchestrator._resolve` carries a FIXED
    tuple of keys with a BARE, UNGUARDED `holder[_sk] = nums.get(_sk)`. A key placed in that tuple
    lands on EVERY hybrid turn -- as an explicit None -- and, through the caller's guarded tuple,
    stamps the trace on every turn with the flags off. That is exactly what `numbers_budget`'s own
    note in this file records, and it is why BOTH of the cost census's orchestrator lines are
    standalone `is not None` guards instead.

    Asserted against the SOURCE because the defect is a line's PLACEMENT, not its value: a functional
    test of `_resolve` would pass with the key in the wrong tuple on any turn that stamps it."""
    # the UNGUARDED copy tuples, read verbatim -- neither may name the census key
    assert _ORCH_SRC.count("numbers_usage") >= 4
    for chunk in _ORCH_SRC.split("for _sk in ("):
        head = chunk.split("):")[0]
        if "fork_basis" in head:
            assert "numbers_usage" not in head, "the census key must NEVER join the unguarded tuple"
    # ...and both carries are present, both guarded, in the `ms_numbers` idiom
    assert '_nu = nums.get("numbers_usage")' in _ORCH_SRC
    assert "if _nu is not None:" in _ORCH_SRC
    assert 'holder["numbers_usage"] = _nu' in _ORCH_SRC
    assert 'if holder.get("numbers_usage") is not None:' in _ORCH_SRC
    assert 'out.setdefault("trace", {})["numbers_usage"] = holder["numbers_usage"]' in _ORCH_SRC


def test_the_plan_usage_carry_is_guarded_and_reads_the_plan_by_getattr():
    """The orchestrator stamp site is the ONE seam holding both the Plan and the trace --
    `_session_writeback`, which carries `ms_dispatch`, never sees the Plan object. With the flag off
    the attribute does not exist at all, so `getattr(..., None)` is the whole carry and the trace is
    HEAD's byte for byte; the `isinstance` guard means a fallback turn (attribute absent) stamps
    nothing rather than stamping None."""
    assert '_plan_usage = getattr(plan, "plan_usage", None)' in _ORCH_SRC
    assert "if isinstance(_plan_usage, dict):" in _ORCH_SRC
    assert 'res.setdefault("trace", {})["plan_usage"] = _plan_usage' in _ORCH_SRC
    # it is stamped BEFORE the intent decision is attached, i.e. inside `_respond_walk` (NOT `_respond`,
    # which is a different body and never plans -- round-2 review m8), beside rerank_lane
    assert _ORCH_SRC.index('res.setdefault("trace", {})["plan_usage"]') < \
           _ORCH_SRC.index('res["intent_decision"] = decided')
    assert _ORCH_SRC.index('["rerank_lane"] = _lane.snapshot()') < \
           _ORCH_SRC.index('res.setdefault("trace", {})["plan_usage"]')


def test_both_orchestrator_seams_live_inside_the_bodies_that_run_every_turn():
    """ROUND-2 REVIEW m4, THE HALF A DECK CAN CLOSE. The two pins above read `orchestrator.py`'s WHOLE
    SOURCE, so both would still pass if either seam had been moved into a function nothing calls --
    the reviewer's words. `inspect.getsource` of the two live entry points closes that half for
    nothing: the numbers carry must sit inside `run_hybrid` (which owns the hybrid lane's numbers leg
    AND the `holder` -> trace mirror) and the plan carry inside `_respond_walk`, which is the ONE seam
    holding both the Plan object and the trace. `_respond` at the same module level is a DIFFERENT body
    that never plans, and it must not carry the key -- round-2 review m8 caught the build report naming
    it, so it is asserted here rather than remembered.

    WHAT THIS STILL DOES NOT PROVE, stated rather than glossed: that a REAL turn lands either key on
    `out["trace"]`. That needs ONE in-VPC turn with `GRAPHRAG_COST_CENSUS=on` (~$1), which is the
    owner's pre-arm smoke law and is carried in the handoff, not something a deck can buy."""
    import inspect
    hyb = inspect.getsource(orch.run_hybrid)
    assert '_nu = nums.get("numbers_usage")' in hyb and "if _nu is not None:" in hyb
    assert 'holder["numbers_usage"] = _nu' in hyb
    assert 'if holder.get("numbers_usage") is not None:' in hyb
    assert 'out.setdefault("trace", {})["numbers_usage"] = holder["numbers_usage"]' in hyb
    walk = inspect.getsource(orch._respond_walk)
    assert '_plan_usage = getattr(plan, "plan_usage", None)' in walk
    assert "if isinstance(_plan_usage, dict):" in walk
    assert 'res.setdefault("trace", {})["plan_usage"] = _plan_usage' in walk
    assert "plan_usage" not in inspect.getsource(orch._respond)      # the body that never plans
