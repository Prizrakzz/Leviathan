"""D-XT (2026-08-29) -- THE OPEN-ASK / SOURCE-FROM-WALK UNIT PINS, hermetic (no LLM, no pg, no AWS).

The wave moves cross-commodity DETECTION for the OPEN class out of `intent.py`'s regex and into the
DISPATCH PLANNER's system prompt (owner directive 1: "no regex cat-and-mouse"), and moves the OPEN
lane's SOURCE binding off `an.route`'s lexical head onto the WALK's own focus seed (owner directive 2;
measured, the lexical head yields a curated material candidate on 1 of 14 desk rows). Both halves sit
behind ONE default-dark flag, `GRAPHRAG_XC_OPEN`, read at ONE seam and threaded downstream as an
ARGUMENT -- never a second env read.

Pin groups, in spec order (dxt_final_spec section d):
  A  the flag grammar, including the STRUCK `regex` leg name
  B  `intent.py` is FROZEN -- byte digest, no `open_v2` kwarg, and the measured 0-of-14 regex floor
  C  the planner prompt render: OFF byte-identical, ON differs, the cache key separates the flag
  D  the two-tier detector composite: the `llm_open` lane and everything it must NOT demote
  E  the gate (`_xc_request`): flag-off byte-identity, the DEFERRED request that names no market,
     and `_route_probe`, N4's real instrument
  F  `route` is `route_scored`'s projection (ONE producer)
  G  `cascade.resolve_xc_open` -- the deferred bind, hermetic fakes, no pg and no map file
  H  the answer.py quantify seam (M7/P21), driven through the REAL `an.answer` -> `_answer_l2` path
  I  the F2 frame guard + the a5.4 chain-vs-pair precedence decision
  J  registration: tracekeys + the N3 decision-record merge, through the real `orchestrator.respond`
  L  preflight tripwires, frozen as tests (zero API)

Fake shapes and the monkeypatch/delenv discipline mirror `tests/unit/test_reroute_v2_gate.py` (`_Pair`,
`_Map`, `_graph`, `_gate`, `_mkplan`) and `tests/unit/test_transmission_chain.py` (`_sg`, `_pair_row`).
"""
from __future__ import annotations

import hashlib
import inspect
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from leviathan.graphrag import answer as an
from leviathan.graphrag import complex_map as cm
from leviathan.graphrag import dispatch as dp
from leviathan.graphrag import intent as it
from leviathan.graphrag import orchestrator as orch
from leviathan.graphrag import tracekeys as tk
from leviathan.graphrag.numbers import cascade as cq

_REPO = Path(__file__).resolve().parents[2]

# canonical loaded-contract slugs (verbatim, as the curated pair table writes them)
PALM = "malaysian_crude_palm_oil_cme"
SOY = "soybean_oil_cbot"
RAPE = "rapeseed_oil_zce"
CORN = "corn_cbot"
WHEAT = "soft_red_winter_wheat_cbot"
MEAL = "soybean_meal_cbot"
BEANS = "soybeans_cbot"

CONTAGION_DECK = _REPO / "configs" / "graphrag" / "eval_queries_q0_contagion_v1.yaml"
CENSUS = _REPO / "data" / "cascade_census" / "cascade_census_20260826_lane3flip.json"


@pytest.fixture(autouse=True)
def _dark_by_default(monkeypatch):
    """EVERY pin in this file starts from the SHIPPED state: both D-XT-relevant flags absent. A pin that
    needs a flag sets it explicitly -- an unpinned default is not a pin (F3/M5)."""
    monkeypatch.delenv("GRAPHRAG_XC_OPEN", raising=False)
    monkeypatch.delenv("GRAPHRAG_XC_LLM_DETECT", raising=False)


# ── shared fakes (the test_reroute_v2_gate shapes) ───────────────────────────────────────────────────
class _Pair:
    """A curated complex_map row: `.id`, `.pair` (2 slugs), `.relation`, `.complex_name`, tier."""

    def __init__(self, pid, a, b, *, relation="substitutes_for", complex_name="vegoil_substitution",
                 tier="material"):
        self.id = pid
        self.pair = (a, b)
        self.relation = relation
        self.complex_name = complex_name
        self.shared_event = "soyoil_palm_premium"
        self.side_a = {"contract": a, "ref": "psd_ending_stock_su_ratio", "country_rule": "world"}
        self.side_b = {"contract": b, "ref": "psd_ending_stock_su_ratio", "country_rule": "world"}
        self.direction = "opposing"
        self.focus_rule = "query"
        self.materiality_tier = tier


class _Map:
    def __init__(self, pairs):
        self.pairs = pairs


def _graph(*slugs):
    return SimpleNamespace(contracts={s: None for s in slugs}, version="test")


def _gate(query, *, graph, state=None, detect, route, pairs, resolve=None, realizable=None,
          route_scored=None, legs=frozenset()):
    """The gate producer with fully-injected lane-A/lane-D stubs (test_reroute_v2_gate._gate + legs)."""
    return orch._xc_request(
        query, graph=graph, state=state, detect=detect,
        route=(route if callable(route) else (lambda q, g: list(route))),
        resolve_bare=resolve, load_map=lambda: _Map(pairs),
        realizable=(realizable if realizable is not None else (lambda pid: True)),
        route_scored=route_scored, legs=legs)


def _mkplan(target="palm", explicit=True, degraded=False):
    return dp.Plan(steps=["reasoning"], contracts=[], xc_explicit=explicit, xc_target=target,
                   degraded=degraded)


def _node(cid, *, relevance=0.0, via_edge=None):
    return SimpleNamespace(kind="contract", id=cid, relevance=relevance, via_edge=via_edge)


def _sg(seeds=(), nodes=(), trace=None):
    return SimpleNamespace(seeds=list(seeds), nodes=list(nodes),
                           trace={} if trace is None else trace, fired_regimes=[])


_XC_MISS_Q = "how does a palm export ban affect soybean oil?"     # a genuine tier-1 miss (S2-1 shape)


# ════════════════════════════════════════════════════════════════════════════════════════════════════
# A -- THE FLAG GRAMMAR (a1). Copied verbatim from `_modes_enabled`: fail-closed, allowlist-intersected.
# ════════════════════════════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("val,want", [
    (None, frozenset()), ("", frozenset()), ("   ", frozenset()),
    ("off", frozenset()), ("OFF", frozenset()), (" Off ", frozenset()),
    ("on", frozenset({"llm", "graph"})), ("ON", frozenset({"llm", "graph"})),
    ("1", frozenset({"llm", "graph"})), ("true", frozenset({"llm", "graph"})),
    ("TRUE", frozenset({"llm", "graph"})), (" on ", frozenset({"llm", "graph"})),
    ("llm", frozenset({"llm"})), ("LLM", frozenset({"llm"})),
    ("graph", frozenset({"graph"})),
    ("llm,graph", frozenset({"llm", "graph"})), ("graph, llm", frozenset({"llm", "graph"})),
    ("llm,bogus", frozenset({"llm"})),
    # the DIRECTIVE-1 pin: `regex` was STRUCK from the design. The struck leg name is not a leg, so a
    # stale runbook value intersects to DARK rather than half-arming a lane that no longer exists.
    ("regex", frozenset()), ("regex,llm", frozenset({"llm"})),
    # fail-closed on every near-miss the `_modes_enabled` grammar deliberately refuses
    ("yes", frozenset()), ("enabled", frozenset()), ("on extra", frozenset()), ("garbage", frozenset()),
])
def test_xc_open_legs_grammar(monkeypatch, val, want):
    if val is None:
        monkeypatch.delenv("GRAPHRAG_XC_OPEN", raising=False)
    else:
        monkeypatch.setenv("GRAPHRAG_XC_OPEN", val)
    assert orch._xc_open_legs() == want


def test_xc_open_legs_default_is_dark_and_the_leg_enum_is_two():
    assert orch._xc_open_legs() == frozenset()                      # autouse fixture: env absent
    assert orch._XC_OPEN_LEGS == frozenset({"llm", "graph"})        # no third leg was minted


# ════════════════════════════════════════════════════════════════════════════════════════════════════
# B -- intent.py IS FROZEN (directive 1). The landing gate is `git diff --stat` on the file; this is the
# same gate expressed as a test, so a later wave cannot edit it quietly.
# ════════════════════════════════════════════════════════════════════════════════════════════════════
# sha256 of `src/leviathan/graphrag/intent.py` as it stands at the D-XT round-4 landing. If this reds,
# EITHER intent.py was edited (directive-1 violation -> STOP) or the working tree's line endings were
# rewritten (a checkout artifact, not an edit) -- diff the file before touching this constant.
_INTENT_SHA256 = "23bd745712d3997a95d7af5399028b98b4efce134be5d0a332f33fde021e7576"


def test_intent_module_is_byte_identical_to_head():
    assert hashlib.sha256(Path(it.__file__).read_bytes()).hexdigest() == _INTENT_SHA256


def test_intent_has_no_open_v2_kwarg():
    """`open_v2=` was STRUCK, not written: the detector still takes exactly ONE argument, which is what
    `xc_detect_two_tier`'s tier 1 calls it with."""
    params = inspect.signature(it.is_cross_commodity_explicit).parameters
    assert "open_v2" not in params
    assert [p for p in params] == ["query"]


@pytest.mark.skipif(not CONTAGION_DECK.exists(),
                    reason="gitignored contagion deck absent (private configs layer)")
def test_intent_regex_floor_is_zero_of_fourteen():
    """[M] The deterministic floor contributes NOTHING on this class and never will: all 14 frozen
    contagion rows return (False, None). It is the premise the whole prompt-as-detector design rests on,
    so it is pinned rather than remembered."""
    rows = yaml.safe_load(CONTAGION_DECK.read_text(encoding="utf-8"))["queries"]
    assert len(rows) == 14
    fires = [r["id"] for r in rows if it.is_cross_commodity_explicit(r["question"]) != (False, None)]
    assert fires == []


# ════════════════════════════════════════════════════════════════════════════════════════════════════
# C -- THE PROMPT RENDER (a2). OFF must be byte-identical; the memo key must separate the flag.
# ════════════════════════════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("n", [1, 2, 3, 4, 5, 6])
def test_planner_sys_off_is_byte_identical(n):
    """`_xc_open_block(False) == ""` -- the PA-11 `coverage_block` idiom. Same OBJECT, not merely equal:
    that is what keeps the serving prompt-cache prefix untouched on every unflagged turn."""
    assert dp.planner_sys(n) is dp.planner_sys(n, xc_open=False)
    assert dp.planner_sys(n) == dp.planner_sys(n, xc_open=False)
    assert dp._xc_open_block(False) == ""


def test_planner_sys_on_differs_and_contains_the_open_bullets():
    off, on = dp.planner_sys(6), dp.planner_sys(6, xc_open=True)
    assert on != off and len(on) > len(off)
    assert off in on.replace(dp._xc_open_block(True), "")           # a pure INSERTION, nothing rewritten
    for phrase in ("An OPEN cross-commodity ask counts too",
                   "MISSPELLINGS AND TYPOS COUNT",
                   "NEVER invent or substitute a commodity to fill xc_target",
                   "THE NEGATIVE BOUNDARY IS THE SAME FOR THE OPEN SHAPE",
                   "REPORTED --", "NEGATED --", "DEPRECATED --", "When uncertain, false."):
        assert phrase in on, phrase
        if phrase not in ("When uncertain, false.",):              # the shipped section says this too
            assert phrase not in off, phrase


def test_sys_renders_cache_key_separates_the_flag():
    """Same ceiling, both flag values -> TWO distinct memo entries, each stable across calls. A shared
    key would serve the amended prompt to an unflagged turn (or the reverse) off the first render."""
    a1, a2 = dp.planner_sys(4), dp.planner_sys(4)
    b1, b2 = dp.planner_sys(4, xc_open=True), dp.planner_sys(4, xc_open=True)
    assert a1 is a2 and b1 is b2 and a1 is not b1
    keys = [k for k in dp._SYS_RENDERS if k[0] == 4]
    # D-XL RE-ANCHOR (2026-09-04), by exactly ONE and never loosened: the key gains a FIFTH
    # component, `tuple(sorted((xl_boards or {}).items()))`, whose EMPTY value is `()` -- so the
    # xc_open component keeps its position and every flag-off key is `(n, tail, cov, xc_open, ())`.
    # The new component is asserted EMPTY on these renders, which is what makes the append safe.
    assert {k[3] for k in keys} == {False, True} and len(keys[0]) == 5
    assert {k[4] for k in keys} == {()}


def test_planner_sys_default_constant_is_unmoved():
    assert dp.PLANNER_SYS is dp.planner_sys()                       # xc_open defaults False, key unchanged


def test_plan_turn_omits_xc_open_when_off_and_threads_it_when_on(monkeypatch):
    seen = []
    monkeypatch.setattr(dp, "planner_sys", lambda n, *, xc_open=False: seen.append((n, xc_open)) or "SYS")

    def call(system, user, *, model, tool, **kw):
        return {"steps": ["reasoning"], "contracts": []}

    g = _graph(PALM, SOY)
    dp.plan_turn("q", graph=g, call=call)
    dp.plan_turn("q", graph=g, call=call, xc_open=True)
    dp.plan_turn("q", graph=g, call=call, xc_open=False)
    assert seen == [(2, False), (2, True), (2, False)]


def test_plan_tool_and_validate_untouched():
    """a2.4, VERIFIED not edited: the schema already documents the open shape and `_validate` already
    produces it. `Plan(xc_explicit=True, xc_target=None)` is a legal, reachable validated shape at HEAD --
    only the PROSE forbade it, which is exactly the asymmetry the amendment closes."""
    tool = dp._plan_tool([PALM, SOY], 6)
    assert "null for an open ask" in tool["input_schema"]["properties"]["xc_target"]["description"]
    plan = dp._validate({"steps": ["reasoning"], "contracts": [], "xc_explicit": True, "xc_target": None},
                        {PALM, SOY}, 6)
    assert plan.xc_explicit is True and plan.xc_target is None and plan.fallback is False


# ════════════════════════════════════════════════════════════════════════════════════════════════════
# D -- THE DETECTOR COMPOSITE (a3.1/a3.2). One leg only; D2 / S1-F2 / D11 sit ABOVE it, unmoved.
# ════════════════════════════════════════════════════════════════════════════════════════════════════
def test_llm_open_lane_dark_by_default(monkeypatch):
    """D19 re-asserted: with GRAPHRAG_XC_OPEN unset a null target is consulted-and-declined, exactly as
    `test_reroute_v2_gate.py::test_composite_open_span_not_consumed` pins it (that test sets only
    GRAPHRAG_XC_LLM_DETECT and stays green unedited)."""
    monkeypatch.setenv("GRAPHRAG_XC_LLM_DETECT", "on")
    det = orch.xc_detect_two_tier(_mkplan(target=None))
    assert det(_XC_MISS_Q) == (False, None)
    assert det.tier == "none" and det.llm_consulted is True


@pytest.mark.parametrize("span", ["other oilseed complexes", "corn / feed book",
                                  "the rest of the feed book", "the wider vegoil complex",
                                  "other markets", "edible-oil complex"])
def test_llm_collective_target_demotes_to_open(monkeypatch, span):
    monkeypatch.setenv("GRAPHRAG_XC_LLM_DETECT", "on")
    monkeypatch.setenv("GRAPHRAG_XC_OPEN", "llm")
    det = orch.xc_detect_two_tier(_mkplan(target=span))
    assert det(_XC_MISS_Q) == (True, None)                          # the SPAN is dropped: no market named
    assert det.tier == "llm_open" and det.llm_consulted is True


def test_llm_named_target_unchanged_under_flag(monkeypatch):
    monkeypatch.setenv("GRAPHRAG_XC_LLM_DETECT", "on")
    monkeypatch.setenv("GRAPHRAG_XC_OPEN", "on")                    # BOTH legs armed
    det = orch.xc_detect_two_tier(_mkplan(target="soybean oil"))
    assert det(_XC_MISS_Q) == (True, "soybean oil")                 # byte-identical to D19
    assert det.tier == "llm" and det.llm_consulted is True


def test_llm_unresolvable_single_commodity_is_not_demoted(monkeypatch):
    """'sunflower oil' stays a NAMED detection that the gate then declines at resolve_bare -- that is
    what keeps `rv2_decline_untracked_sibling` green. Demoting it would turn an untracked sibling ask
    into a fork on some OTHER market: the fence violation this wave exists under."""
    monkeypatch.setenv("GRAPHRAG_XC_LLM_DETECT", "on")
    monkeypatch.setenv("GRAPHRAG_XC_OPEN", "on")
    det = orch.xc_detect_two_tier(_mkplan(target="sunflower oil"))
    assert det(_XC_MISS_Q) == (True, "sunflower oil")
    assert det.tier == "llm"


def test_llm_open_lane_fires_on_null_target_under_flag(monkeypatch):
    monkeypatch.setenv("GRAPHRAG_XC_LLM_DETECT", "on")
    monkeypatch.setenv("GRAPHRAG_XC_OPEN", "llm")
    det = orch.xc_detect_two_tier(_mkplan(target=None))
    assert det(_XC_MISS_Q) == (True, None)
    assert det.tier == "llm_open" and det.llm_consulted is True


def test_degraded_plan_still_floor_only_under_flag(monkeypatch):
    monkeypatch.setenv("GRAPHRAG_XC_LLM_DETECT", "on")
    monkeypatch.setenv("GRAPHRAG_XC_OPEN", "on")
    det = orch.xc_detect_two_tier(_mkplan(target=None, degraded=True))
    assert det(_XC_MISS_Q) == (False, None)                         # S1-F2 sits ABOVE the new branch
    assert det.tier == "none" and det.llm_consulted is False


def test_plan_none_still_floor_only_under_flag(monkeypatch):
    monkeypatch.setenv("GRAPHRAG_XC_LLM_DETECT", "on")
    monkeypatch.setenv("GRAPHRAG_XC_OPEN", "on")
    det = orch.xc_detect_two_tier(None)                             # D11 dispatch fallback
    assert det(_XC_MISS_Q) == (False, None)
    assert det.tier == "none" and det.llm_consulted is False


def test_llm_detect_off_keeps_the_open_lane_unreachable(monkeypatch):
    """The open lane sits BEHIND the explicit-ask detector, never beside it: GRAPHRAG_XC_OPEN alone
    arms nothing."""
    monkeypatch.setenv("GRAPHRAG_XC_OPEN", "on")
    det = orch.xc_detect_two_tier(_mkplan(target=None))
    assert det(_XC_MISS_Q) == (False, None)
    assert det.tier == "none" and det.llm_consulted is False


def test_regex_hit_still_wins_under_flag(monkeypatch):
    monkeypatch.setenv("GRAPHRAG_XC_LLM_DETECT", "on")
    monkeypatch.setenv("GRAPHRAG_XC_OPEN", "on")
    det = orch.xc_detect_two_tier(_mkplan(target="other oilseed complexes"))
    assert det("palm ban -- what does that do to soyoil?") == (True, "soyoil")
    assert det.tier == "regex" and det.llm_consulted is False       # D2: tier 1 returns before tier 2


@pytest.mark.parametrize("span", [
    "other oilseed complexes", "corn / feed book", "the rest of the complex",
    "the wider vegoil complex", "other markets", "edible-oil complex",
    "the rest of the feed book", "the whole complex", "remaining markets", "other balance sheets",
])
def test_is_collective_span_true(span):
    assert orch.is_collective_span(span) is True


@pytest.mark.parametrize("span", [
    "sunflower oil", "soybean meal", "soybean meal balance sheets", "corn", "palm's board",
    "soybean oil", "rapeseed oil", "", None,
])
def test_is_collective_span_false(span):
    """m2's anchor: a trailing collective noun counts ONLY when nothing that could be a commodity
    precedes it -- 'soybean meal balance sheets' and \"palm's board\" name ONE market, not a group."""
    assert orch.is_collective_span(span) is False


# ════════════════════════════════════════════════════════════════════════════════════════════════════
# E -- THE GATE (a3.3/a3.4). Flag-off request dicts must be BYTE-IDENTICAL to today.
# ════════════════════════════════════════════════════════════════════════════════════════════════════
def _resolve_vegoil(s):
    t = (s or "").strip().lower()
    return PALM if "palm" in t else (SOY if "soy" in t else None)


def test_open_request_is_shipped_shape_when_flag_off():
    """The shipped D7 OPEN-target branch: SOURCE = the lexical route head, PAIR_CAP=1 in id order. No
    `route_probe`, no `defer`, no `rank` -- the dict is byte-identical to its pre-D-XT self."""
    out = _gate("what else does this affect?", graph=_graph(PALM, SOY),
                detect=lambda q: (True, None), route=[PALM],
                pairs=[_Pair("soyoil_palm_vegoil", SOY, PALM)], legs=frozenset())
    assert out == {"pair_id": "soyoil_palm_vegoil", "source_slug": PALM, "target_slug": SOY}
    assert "route_probe" not in out and "defer" not in out


def test_named_request_is_shipped_shape_when_flag_off():
    out = _gate(_XC_MISS_Q, graph=_graph(PALM, SOY), detect=lambda q: (True, "soybean oil"),
                route=[PALM], resolve=_resolve_vegoil,
                pairs=[_Pair("soyoil_palm_vegoil", SOY, PALM)], legs=frozenset())
    assert set(out) == {"pair_id", "source_slug", "target_slug"}    # NO route_probe key at all


def test_probe_count_unchanged_when_flag_off():
    """The census probe is a LIVE pg call. Flag off, the shipped first-True loop must still stop at the
    first realizable candidate, and must still probe every candidate when none fire."""
    calls = []
    pairs = [_Pair("aaa_pair", PALM, SOY), _Pair("bbb_pair", PALM, RAPE),
             _Pair("ccc_pair", PALM, CORN)]
    out = _gate("what else does this affect?", graph=_graph(PALM, SOY, RAPE, CORN),
                detect=lambda q: (True, None), route=[PALM], pairs=pairs,
                realizable=lambda pid: calls.append(pid) or True, legs=frozenset())
    assert out["pair_id"] == "aaa_pair" and calls == ["aaa_pair"]   # first-True: exactly ONE probe
    calls.clear()
    out = _gate("what else does this affect?", graph=_graph(PALM, SOY, RAPE, CORN),
                detect=lambda q: (True, None), route=[PALM], pairs=pairs,
                realizable=lambda pid: calls.append(pid) or False, legs=frozenset())
    assert out is None and calls == ["aaa_pair", "bbb_pair", "ccc_pair"]


def test_deferred_request_carries_no_market():
    """F3, structurally: an unresolved request is INCAPABLE of naming a market. No source_slug key at
    all, pair_id and target_slug explicitly None, and the census is never probed (zero pg cost)."""
    probes = []
    out = _gate("where else does this reach?", graph=_graph(PALM, SOY),
                detect=lambda q: (True, None), route=[PALM],
                pairs=[_Pair("soyoil_palm_vegoil", SOY, PALM)],
                realizable=lambda pid: probes.append(pid) or True,
                route_scored=lambda q, g: [(1, PALM)], legs=frozenset({"llm"}))
    assert "source_slug" not in out
    assert out["pair_id"] is None and out["target_slug"] is None and out["defer"] == "walk"
    assert probes == []
    assert set(out) == {"pair_id", "target_slug", "defer", "rank", "route_probe"}


@pytest.mark.parametrize("legs,rank", [
    (frozenset({"llm"}), "idorder"),
    (frozenset({"llm", "graph"}), "graph"),
    (frozenset({"graph"}), "graph"),
])
def test_deferred_request_carries_the_rank_policy_not_the_env(monkeypatch, legs, rank):
    """The RANK rides as an ARGUMENT. The env is set to the OPPOSITE value to prove the gate reads the
    injected `legs` and never the environment (D8: one seam, one read)."""
    monkeypatch.setenv("GRAPHRAG_XC_OPEN", "llm" if rank == "graph" else "on")
    out = _gate("where else does this reach?", graph=_graph(PALM, SOY),
                detect=lambda q: (True, None), route=[PALM],
                pairs=[_Pair("soyoil_palm_vegoil", SOY, PALM)],
                route_scored=lambda q, g: [(1, PALM)], legs=legs)
    assert out["rank"] == rank


def test_regex_open_hit_also_defers_under_the_flag():
    """The deliberate behaviour change on the six shipped `_XC_OPEN` regex patterns: a tier-1 OPEN hit
    (matched with a NULL span) takes the SAME deferral. The lane is chosen by the SHAPE of the
    detection, never by which tier produced it."""
    det = orch.xc_detect_two_tier(None)
    assert it.is_cross_commodity_explicit("what else does this affect?") == (True, None)
    out = _gate("what else does this affect?", graph=_graph(PALM, SOY), detect=det, route=[PALM],
                pairs=[_Pair("soyoil_palm_vegoil", SOY, PALM)],
                route_scored=lambda q, g: [(1, PALM)], legs=frozenset({"llm"}))
    assert out["defer"] == "walk" and out["detect_tier"] == "regex"
    assert "source_slug" not in out


def test_named_ask_is_never_deferred():
    """The NAMED branch does not move: it still binds SOURCE target-aware and returns a resolved pair.
    Only the (omitted-when-off) `route_probe` telemetry key joins it under the flag."""
    out = _gate(_XC_MISS_Q, graph=_graph(PALM, SOY), detect=lambda q: (True, "soybean oil"),
                route=[PALM], resolve=_resolve_vegoil,
                pairs=[_Pair("soyoil_palm_vegoil", SOY, PALM)],
                route_scored=lambda q, g: [(2, PALM), (1, SOY)], legs=frozenset({"llm"}))
    assert "defer" not in out and "rank" not in out
    assert out["pair_id"] == "soyoil_palm_vegoil" and out["source_slug"] == PALM
    assert out["target_slug"] == SOY and isinstance(out["route_probe"], dict)


def test_route_probe_records_the_scored_tie_count():
    """N4: `an.route` DISCARDS the hit counts, so any tie instrument built on it is structurally 1. The
    probe consumes `route_scored` instead, and a 3-way tie at the top count reads ties: 3."""
    scored = [(3, PALM), (3, SOY), (3, RAPE), (1, CORN)]
    out = _gate("where else does this reach?", graph=_graph(PALM, SOY, RAPE, CORN),
                detect=lambda q: (True, None), route=[PALM, SOY, RAPE, CORN],
                pairs=[_Pair("soyoil_palm_vegoil", SOY, PALM)],
                route_scored=lambda q, g: list(scored), legs=frozenset({"llm"}))
    rp = out["route_probe"]
    assert rp == {"n_hits": 4, "head": PALM, "top_n": 3, "ties": 3, "head_in_material": True}


def test_route_probe_head_in_material_is_false_on_a_non_pair_head():
    out = _gate("where else does this reach?", graph=_graph(PALM, SOY, CORN),
                detect=lambda q: (True, None), route=[CORN],
                pairs=[_Pair("soyoil_palm_vegoil", SOY, PALM)],
                route_scored=lambda q, g: [(2, CORN)], legs=frozenset({"llm"}))
    assert out["route_probe"]["head"] == CORN
    assert out["route_probe"]["head_in_material"] is False          # binding SOURCE here could never fork


def test_route_probe_is_belted_and_never_declines_the_turn():
    """P9: telemetry must never decline the turn it measures. A raising `route_scored` yields an EMPTY
    probe dict and the deferral still stands."""
    def boom(q, g):
        raise RuntimeError("scored producer down")

    out = _gate("where else does this reach?", graph=_graph(PALM, SOY),
                detect=lambda q: (True, None), route=[PALM],
                pairs=[_Pair("soyoil_palm_vegoil", SOY, PALM)],
                route_scored=boom, legs=frozenset({"llm"}))
    assert out["defer"] == "walk" and out["route_probe"] == {}


def test_gate_declines_are_unchanged_under_the_flag():
    """A no-detection turn returns None with the flag ON exactly as it does with the flag OFF: the
    fork is never volunteered, and the flag only re-scopes an ask the detector already licensed."""
    for legs in (frozenset(), frozenset({"llm", "graph"})):
        assert _gate("why did palm rally?", graph=_graph(PALM, SOY),
                     detect=lambda q: (False, None), route=[PALM],
                     pairs=[_Pair("soyoil_palm_vegoil", SOY, PALM)],
                     route_scored=lambda q, g: [(1, PALM)], legs=legs) is None


# ════════════════════════════════════════════════════════════════════════════════════════════════════
# F -- `route` IS `route_scored`'s PROJECTION (a4.1). ONE producer, so the two can never disagree.
# ════════════════════════════════════════════════════════════════════════════════════════════════════
def _routing_graph():
    """A tiny REAL-shaped contract enum (id + aliases) -- `route_scored` reads nothing else."""
    return SimpleNamespace(contracts={
        PALM: SimpleNamespace(aliases=["palm", "palm oil", "cpo"]),
        SOY: SimpleNamespace(aliases=["soyoil", "soybean oil"]),
        CORN: SimpleNamespace(aliases=["corn", "maize"]),
        WHEAT: SimpleNamespace(aliases=["wheat", "srw"]),
    }, version="test")


@pytest.mark.parametrize("q", [
    "palm export ban -- what does that do to soybean oil?",
    "corn corn corn and a little wheat",
    "soyoil vs palm oil, which tightens? palm palm",
    "where else does this reach?",                                  # zero hits
    "maize and srw wheat and cpo",
    "",
])
def test_route_is_route_scored_projection(q):
    g = _routing_graph()
    scored = an.route_scored(q, g)
    assert an.route(q, g) == [cid for _, cid in scored]
    assert scored == sorted(scored, reverse=True)                   # most-hits-first, unchanged ordering
    assert all(n > 0 for n, _ in scored)                            # zero-hit contracts never enter


def test_route_scored_counts_are_real_hit_counts():
    g = _routing_graph()
    scored = dict((c, n) for n, c in an.route_scored("corn corn maize and palm", g))
    assert scored[CORN] == 3 and scored[PALM] == 1 and SOY not in scored


# ════════════════════════════════════════════════════════════════════════════════════════════════════
# G -- THE RESOLVER (a5.1/a5.2). Hermetic: no pg, no complex_map file, no walk.
# ════════════════════════════════════════════════════════════════════════════════════════════════════
def _wire_resolver(monkeypatch, pairs, *, realizable=True, probes=None):
    """Inject the lane-A map and the lane-D census probe at the module seams `resolve_xc_open` reads."""
    monkeypatch.setattr(cm, "load_complex_map", lambda: _Map(list(pairs)))

    def _rz(pid):
        if probes is not None:
            probes.append(pid)
        return realizable(pid) if callable(realizable) else bool(realizable)
    monkeypatch.setattr(cq, "_xmit_pair_realizable", _rz)


def _deferred(rank="idorder", **extra):
    return {"pair_id": None, "target_slug": None, "defer": "walk", "rank": rank, **extra}


def test_non_deferred_request_passes_through_identical(monkeypatch):
    """The `is` object: every NAMED ask, every legacy 3-key request and every flag-off turn bypasses
    this function untouched, so the resolver cannot perturb a lane it was never asked about."""
    _wire_resolver(monkeypatch, [])
    for req in ({"pair_id": "p", "source_slug": PALM, "target_slug": SOY},
                {"pair_id": "p", "source_slug": PALM, "target_slug": SOY, "detect_tier": "llm"},
                {}):
        out, dec = cq.resolve_xc_open(req, _sg(seeds=[PALM]), _graph(PALM))
        assert out is req and dec is None
    out, dec = cq.resolve_xc_open(None, _sg(), _graph())
    assert out is None and dec is None


def test_focus_is_the_first_graph_contract_seed(monkeypatch):
    _wire_resolver(monkeypatch, [_Pair("soyoil_palm_vegoil", SOY, PALM)])
    out, dec = cq.resolve_xc_open(_deferred(), _sg(seeds=[PALM, SOY]), _graph(PALM, SOY))
    assert dec is None and out["source_slug"] == PALM and out["target_slug"] == SOY


def test_focus_skips_a_seed_absent_from_graph_contracts(monkeypatch):
    _wire_resolver(monkeypatch, [_Pair("soyoil_palm_vegoil", SOY, PALM)])
    out, _ = cq.resolve_xc_open(_deferred(), _sg(seeds=["ghost_contract", PALM]), _graph(PALM, SOY))
    assert out["source_slug"] == PALM
    assert out["xc_open_rank"]["n_seeds"] == 1                      # the ghost is not a seed for this rule


def test_no_focus_declines_with_a_reason(monkeypatch):
    _wire_resolver(monkeypatch, [_Pair("soyoil_palm_vegoil", SOY, PALM)])
    out, dec = cq.resolve_xc_open(_deferred(), _sg(seeds=[]), _graph(PALM, SOY))
    assert out is None and dec == {"reason": "no_focus", "n_seeds": 0}
    out, dec = cq.resolve_xc_open(_deferred(), _sg(seeds=["ghost"]), _graph(PALM, SOY))
    assert out is None and dec["reason"] == "no_focus"


def test_generic_contract_focus_declines_focus_not_paired_and_records_first_paired_seed(monkeypatch):
    """THE ROSTER INSTRUMENT (P7). The walk's head can be a GENERIC contract id ('corn', 'soybeans' --
    distinct ids from corn_cbot/soybeans_cbot and legs of ZERO curated pairs). Those turns decline, and
    `first_paired_seed` records for FREE exactly what a 'first PAIRED seed' rule would have bought --
    so the owner can price that discretion rather than inherit it."""
    _wire_resolver(monkeypatch, [_Pair("corn_wheat_feed", CORN, WHEAT, complex_name="feed_grain")])
    sg = _sg(seeds=["corn", CORN, WHEAT])
    out, dec = cq.resolve_xc_open(_deferred(), sg, _graph("corn", CORN, WHEAT))
    assert out is None
    assert dec == {"reason": "focus_not_paired", "focus": "corn", "n_seeds": 3,
                   "focus_paired": False, "first_paired_seed": CORN, "n_pairs": 0}


def test_idorder_binds_the_first_realizable_candidate(monkeypatch):
    """The SHIPPED PAIR_CAP=1 rule, applied to a source the GRAPH chose rather than one the alphabet
    chose. The first candidate is not realizable, so the bind falls to the second in curated-id order."""
    pairs = [_Pair("aaa_pair", PALM, SOY), _Pair("bbb_pair", PALM, RAPE), _Pair("ccc_pair", PALM, CORN)]
    _wire_resolver(monkeypatch, pairs, realizable=lambda pid: pid != "aaa_pair")
    out, dec = cq.resolve_xc_open(_deferred(), _sg(seeds=[PALM]), _graph(PALM, SOY, RAPE, CORN))
    assert dec is None
    assert out["pair_id"] == "bbb_pair" and out["target_slug"] == RAPE
    assert out["xc_open_rank"]["rank"] == "idorder"
    assert out["xc_open_rank"]["n_pairs"] == 3 and out["xc_open_rank"]["n_realizable"] == 2


def test_unrealizable_candidates_decline_no_realizable(monkeypatch):
    pairs = [_Pair("aaa_pair", PALM, SOY), _Pair("bbb_pair", PALM, RAPE)]
    _wire_resolver(monkeypatch, pairs, realizable=False)
    out, dec = cq.resolve_xc_open(_deferred(), _sg(seeds=[PALM]), _graph(PALM, SOY, RAPE))
    assert out is None and dec["reason"] == "no_realizable"
    assert dec["n_pairs"] == 2 and dec["n_realizable"] == 0 and dec["capped"] is False


def test_probe_cap_bounds_realizable_calls(monkeypatch):
    """N11: `pair_realizable` is a LIVE pg probe behind an lru_cache -- NOT pure and NOT free. The cap is
    measured-inert today (the largest curated candidate set is 4); it exists so ROSTER GROWTH cannot
    silently uncap the probe count, which is exactly what this fixture simulates."""
    probes = []
    pairs = [_Pair(f"pair_{i:02d}", PALM, f"partner_{i:02d}") for i in range(10)]
    _wire_resolver(monkeypatch, pairs, probes=probes)
    out, dec = cq.resolve_xc_open(_deferred(), _sg(seeds=[PALM]),
                                  _graph(PALM, *[f"partner_{i:02d}" for i in range(10)]))
    assert dec is None
    assert len(probes) == cq.XC_OPEN_PROBE_CAP == 4
    assert out["xc_open_rank"]["probes"] == 4 and out["xc_open_rank"]["capped"] is True
    assert out["pair_id"] == "pair_00"


def test_probe_cap_capped_flag_is_false_when_the_set_fits(monkeypatch):
    pairs = [_Pair("aaa_pair", PALM, SOY), _Pair("bbb_pair", PALM, RAPE)]
    _wire_resolver(monkeypatch, pairs)
    out, _ = cq.resolve_xc_open(_deferred(), _sg(seeds=[PALM]), _graph(PALM, SOY, RAPE))
    assert out["xc_open_rank"]["capped"] is False and out["xc_open_rank"]["probes"] == 2


def test_traversed_relation_beats_id_order(monkeypatch):
    """THE GRAPH-LEG ALPHABET PIN. `bbb_pair` loses on id order and WINS because the walk actually
    traversed ITS OWN relation out of SOURCE to reach that partner."""
    pairs = [_Pair("aaa_pair", PALM, SOY, relation="substitutes_for"),
             _Pair("bbb_pair", PALM, RAPE, relation="competes_with")]
    _wire_resolver(monkeypatch, pairs)
    sg = _sg(seeds=[PALM],
             nodes=[_node(PALM, relevance=1.0),
                    _node(RAPE, relevance=0.7,
                          via_edge={"_from": PALM, "relation": "competes_with", "tracked": True}),
                    _node(SOY, relevance=0.9)])                     # lit, but by no edge OUT of source
    out, dec = cq.resolve_xc_open(_deferred(rank="graph"), sg, _graph(PALM, SOY, RAPE))
    assert dec is None and out["pair_id"] == "bbb_pair" and out["target_slug"] == RAPE
    assert out["trigger"] == "open_walk_graph"
    assert out["xc_open_rank"]["rank"] == "graph" and out["xc_open_rank"]["traversed"] == 1
    # ...and the SAME fixture on the shipped `idorder` policy takes the alphabet's answer, unchanged.
    out2, _ = cq.resolve_xc_open(_deferred(rank="idorder"), sg, _graph(PALM, SOY, RAPE))
    assert out2["pair_id"] == "aaa_pair" and out2["trigger"] == "open_walk_idorder"


def test_relation_mismatch_is_not_a_traversal(monkeypatch):
    """M2: the per-pair match is EXPLICIT -- an edge with a DIFFERENT relation is not this pair's edge.
    With nothing lit, the graph leg falls back to id order and STAMPS the fallback (never a decline)."""
    pairs = [_Pair("aaa_pair", PALM, SOY, relation="substitutes_for"),
             _Pair("bbb_pair", PALM, RAPE, relation="competes_with")]
    _wire_resolver(monkeypatch, pairs)
    sg = _sg(seeds=[PALM],
             nodes=[_node(RAPE, relevance=0.9,
                          via_edge={"_from": PALM, "relation": "substitutes_for"})])
    out, dec = cq.resolve_xc_open(_deferred(rank="graph"), sg, _graph(PALM, SOY, RAPE))
    assert dec is None and out["pair_id"] == "aaa_pair"
    assert out["xc_open_rank"]["fallback"] == "id_order" and out["xc_open_rank"]["rank"] == "graph"


def test_cascade_slot_via_edge_does_not_traverse(monkeypatch):
    """N5, ADOPTED AS AN EXCLUSION. A D-MW-28 cascade slot stamps `_from`, `relation` AND `tracked: True`
    -- so the round-3 claim that its relation set is empty was FALSE. Worse, that edge is traversed in
    REVERSE (the foreign contract declared the seed as ITS driver), so counting it would score
    `traversed` on the opposite direction from the one this key measures."""
    from leviathan.graphrag.planner import REASON_DOWNSTREAM_CONTRACT
    pairs = [_Pair("aaa_pair", PALM, SOY, relation="substitutes_for"),
             _Pair("bbb_pair", PALM, RAPE, relation="competes_with")]
    _wire_resolver(monkeypatch, pairs)
    slot = {"_from": PALM, "relation": "competes_with", "tracked": True,
            "reason": REASON_DOWNSTREAM_CONTRACT}
    sg = _sg(seeds=[PALM], nodes=[_node(RAPE, relevance=0.95, via_edge=slot)])
    # the walk index records the node but contributes NO relation for it...
    idx = cq._xc_walk_index(sg, PALM)
    assert idx[RAPE]["relations"] == set() and idx[RAPE]["tracked"] is True
    # ...so the graph leg lights nothing and falls back to id order rather than promoting bbb_pair.
    out, dec = cq.resolve_xc_open(_deferred(rank="graph"), sg, _graph(PALM, SOY, RAPE))
    assert dec is None and out["pair_id"] == "aaa_pair"
    assert out["xc_open_rank"]["fallback"] == "id_order"


def test_walk_index_unions_relations_with_no_string_compare(monkeypatch):
    """M2: a node reached by TWO relations keeps BOTH (mcpo -> soybean_oil carries substitutes_for AND
    competes_with). A `max()` over relation strings would pick one LEXICALLY -- an alphabet tiebreak
    inside the fix whose whole purpose is 'the graph, not the alphabet'."""
    sg = _sg(nodes=[_node(SOY, relevance=0.4, via_edge={"_from": PALM, "relation": "substitutes_for"}),
                    _node(SOY, relevance=0.8, via_edge={"_from": PALM, "relation": "competes_with"}),
                    SimpleNamespace(kind="driver", id="not_a_contract", relevance=1.0, via_edge=None)])
    idx = cq._xc_walk_index(sg, PALM)
    assert idx[SOY]["relations"] == {"substitutes_for", "competes_with"}
    assert idx[SOY]["relevance"] == 0.8                             # max, not last-writer
    assert "not_a_contract" not in idx                              # contract nodes only


def test_crush_only_is_computed_over_the_candidate_set(monkeypatch):
    """M1. A `crushed_into` candidate whose crush edge was not traversed is DROPPED (a crush relation is
    an accounting identity, true without dated evidence). But `crush_only` is computed over the WHOLE
    candidate set BEFORE the loop, so a MIXED set the walk did not light falls to the id-order fallback
    -- never to a `continue`-driven decline masquerading as a reorder."""
    pairs = [_Pair("aaa_crush", BEANS, MEAL, relation="crushed_into", complex_name="soy_crush"),
             _Pair("bbb_subs", BEANS, SOY, relation="substitutes_for")]
    _wire_resolver(monkeypatch, pairs)
    sg = _sg(seeds=[BEANS], nodes=[_node(MEAL, relevance=0.5), _node(SOY, relevance=0.5)])
    out, dec = cq.resolve_xc_open(_deferred(rank="graph"), sg, _graph(BEANS, MEAL, SOY))
    assert dec is None and out["pair_id"] == "aaa_crush"            # the id-order list, whole
    assert out["xc_open_rank"]["fallback"] == "id_order"


def test_all_crush_candidates_unlit_decline_crush_not_traversed(monkeypatch):
    """The one path on which the graph leg genuinely declines: EVERY candidate is a crush identity and
    the walk lit none of them. `crush_not_traversed` is a declared decline reason, not a silent absence."""
    pairs = [_Pair("aaa_crush", BEANS, MEAL, relation="crushed_into", complex_name="soy_crush"),
             _Pair("bbb_crush", BEANS, SOY, relation="crushed_into", complex_name="soy_crush")]
    _wire_resolver(monkeypatch, pairs)
    out, dec = cq.resolve_xc_open(_deferred(rank="graph"), _sg(seeds=[BEANS]),
                                  _graph(BEANS, MEAL, SOY))
    assert out is None and dec["reason"] == "crush_not_traversed"
    assert dec["reason"] in cq.XC_OPEN_DECLINES


def test_idorder_can_never_reach_crush_not_traversed(monkeypatch):
    """The SHIPPED leg, structurally: `idorder` is never empty when `ids` is non-empty, so M1's defect
    class is unreachable on the lane that actually ships."""
    pairs = [_Pair("aaa_crush", BEANS, MEAL, relation="crushed_into", complex_name="soy_crush"),
             _Pair("bbb_crush", BEANS, SOY, relation="crushed_into", complex_name="soy_crush")]
    _wire_resolver(monkeypatch, pairs)
    out, dec = cq.resolve_xc_open(_deferred(rank="idorder"), _sg(seeds=[BEANS]),
                                  _graph(BEANS, MEAL, SOY))
    assert dec is None and out["pair_id"] == "aaa_crush"


def test_resolved_request_stamps_source_target_and_trigger(monkeypatch):
    """THE POSITIVE BIND (P3). A resolver that only ever declines proves nothing: this pins the whole
    resolved shape -- the pair, both markets, the trigger the frame guard and the precedence guard read,
    the rank record the trace lifts -- and pins that `defer`/`rank` are STRIPPED while every other
    carried key (the detection tier) rides through untouched."""
    _wire_resolver(monkeypatch, [_Pair("soyoil_palm_vegoil", SOY, PALM)])
    req = _deferred(detect_tier="llm_open", route_probe={"n_hits": 2, "head": PALM})
    out, dec = cq.resolve_xc_open(req, _sg(seeds=[PALM, SOY]), _graph(PALM, SOY))
    assert dec is None
    assert out["pair_id"] == "soyoil_palm_vegoil"
    assert out["source_slug"] == PALM and out["target_slug"] == SOY
    assert out["trigger"] == "open_walk_idorder" and out["trigger"] in cq._OPEN_TRIGGERS
    assert out["detect_tier"] == "llm_open" and out["route_probe"] == {"n_hits": 2, "head": PALM}
    assert "defer" not in out and "rank" not in out
    rank = out["xc_open_rank"]
    assert rank["focus"] == PALM and rank["pair_id"] == "soyoil_palm_vegoil" and rank["target"] == SOY
    assert rank["focus_paired"] is True and rank["n_seeds"] == 2 and rank["n_realizable"] == 1
    assert rank["rank"] == "idorder" and isinstance(rank["probe_ms"], int)
    assert req["defer"] == "walk"                                   # the caller's dict is never mutated


def test_resolver_never_raises(monkeypatch):
    """A resolver failure degrades to NO FORK -- never a 500, never a guess. Every limb is exercised:
    a raising walk, a raising map load, and a raising census probe."""
    class _Boom:
        @property
        def seeds(self):
            raise RuntimeError("walk exploded")

    _wire_resolver(monkeypatch, [_Pair("soyoil_palm_vegoil", SOY, PALM)])
    out, dec = cq.resolve_xc_open(_deferred(), _Boom(), _graph(PALM, SOY))
    assert out is None and dec == {"reason": "error"} and dec["reason"] in cq.XC_OPEN_DECLINES

    def _raise_map():
        raise RuntimeError("cold-cache glob failed")
    monkeypatch.setattr(cm, "load_complex_map", _raise_map)
    out, dec = cq.resolve_xc_open(_deferred(), _sg(seeds=[PALM]), _graph(PALM, SOY))
    assert out is None and dec["reason"] == "focus_not_paired"      # a map failure is a DECLINE, not a raise

    def _raise_probe(pid):
        raise RuntimeError("pg down")
    _wire_resolver(monkeypatch, [_Pair("soyoil_palm_vegoil", SOY, PALM)])
    monkeypatch.setattr(cq, "_xmit_pair_realizable", _raise_probe)
    out, dec = cq.resolve_xc_open(_deferred(), _sg(seeds=[PALM]), _graph(PALM, SOY))
    assert out is None and dec["reason"] == "error"


def test_deferred_request_is_inert_in_xmit_focus():
    """N2, WITH SEEDS PRESENT -- the round-3 pin passed vacuously without them. `_xmit_focus` falls back
    to the walk's focus seed, which is PRECISELY the contract a deferred request is waiting to be bound
    to, so omitting `source_slug` alone would have routed the deferral straight down trigger 2 with the
    composer's file-order selection."""
    sg, g = _sg(seeds=[PALM, SOY]), _graph(PALM, SOY)
    assert cq._xmit_focus(sg, g, {}) == PALM                        # the pin is NOT vacuous: seeds bind
    assert cq._xmit_focus(sg, g, {"source_slug": SOY}) == SOY
    assert cq._xmit_focus(sg, g, _deferred()) is None               # ...and a deferral is inert
    assert cq._xmit_focus(sg, g, _deferred(rank="graph")) is None


def test_walk_focus_agrees_with_the_price_leg_expression():
    """a5.1: D-XT deliberately REUSES the F2 price leg's focus expression rather than authoring a second
    notion of 'the market this turn is about' -- two focus rules that could disagree is the defect, not
    the fix. The price leg keeps its inline expression (a behaviour-neutral refactor on a live lane is
    not free), so drift is CAUGHT here rather than prevented: the exact source line is pinned, and the
    two are compared behaviourally on shared fixtures."""
    src = Path(an.__file__).read_text(encoding="utf-8")
    assert ('next((c for c in (getattr(sg, "seeds", None) or []) if c in graph.contracts), None)') in src
    for seeds, slugs in (([PALM, SOY], (PALM, SOY)), ([SOY], (PALM, SOY)), ([], (PALM,)),
                         (["ghost", CORN], (PALM, CORN)), (["ghost"], (PALM,))):
        sg, g = _sg(seeds=seeds), _graph(*slugs)
        price_focus = next((c for c in (getattr(sg, "seeds", None) or []) if c in g.contracts), None)
        assert cq._xc_walk_focus(sg, g) == price_focus


# ════════════════════════════════════════════════════════════════════════════════════════════════════
# H -- THE ANSWER SEAM (a4.2 / M7 / P21), driven through the REAL an.answer -> _answer_l2 path with a
# recording `cq.quantify` (the test_cascade_pace_live_path idiom: genuine walk, hermetic I/O).
# ════════════════════════════════════════════════════════════════════════════════════════════════════
def _seam_graph():
    from leviathan.causal import schema as cs
    from leviathan.graphrag import graph as g
    corn = cs.CausalContract(
        contract=CORN, aliases=["corn"],
        drivers=[cs.Driver(id="export_ban", type="policy_event", sign="+", region="US",
                           silver_ref="export", silver_status="available",
                           mechanism="Export restrictions elsewhere shift world demand to US supply.")])
    return g.CausalGraph({CORN: corn}, silver=set())


def _wire_seam(monkeypatch, quantify_rec):
    from leviathan.graphrag import evidence as ev
    monkeypatch.setattr(ev, "embed", lambda texts, **kw: [[1.0, 0.0] for _ in texts])
    monkeypatch.setattr(ev, "backed_dag_ids", lambda: {"export_ban"})
    monkeypatch.setattr(ev, "slice_for_driver", lambda did: did)
    monkeypatch.setattr(an, "_pgnumbers_live", lambda: True)
    monkeypatch.setattr(cq, "quantify", quantify_rec)


def _run_seam(xc_request):
    def retrieve(q, node, *, k=5, asof=None, near=None):
        return [{"date": "2025-10-05", "source": "usda_gain", "source_key": f"s3://{node}/1",
                 "text": f"{node} note"}]

    def call(system, user, *, model, tool, **kw):
        return {"tldr": "t", "mechanism": "m", "diagram_mermaid": "", "sources": []}

    return an.answer("what else does this reach?", graph=_seam_graph(), planner="l2",
                     asof="2026-02-15", retrieve=retrieve, call=call,
                     numbers_lookup=lambda sql: [], route_fn=lambda q, gr: [CORN],
                     xc_request=xc_request)


class _QuantifyRec:
    def __init__(self):
        self.seen = []

    def __call__(self, sg, graph, **kw):
        self.seen.append(kw)
        return ([], None, None)


def test_seam_omits_resolver_when_no_defer(monkeypatch):
    """The seam is gated by the ARGUMENT (`defer`), exactly like `price_request` -- answer.py reads NO
    env for it. A NAMED request never reaches the resolver and rides into quantify as the SAME object."""
    rec = _QuantifyRec()
    _wire_seam(monkeypatch, rec)
    called = []
    monkeypatch.setattr(cq, "resolve_xc_open", lambda *a: called.append(a) or (None, None))
    req = {"pair_id": "p", "source_slug": PALM, "target_slug": SOY}
    out = _run_seam(req)
    assert called == [] and rec.seen[0]["xc_request"] is req
    assert "xc_open_pair" not in out["trace"] and "xc_open_decline" not in out["trace"]


def test_seam_resolves_a_deferred_request_and_traces_the_rank(monkeypatch):
    rec = _QuantifyRec()
    _wire_seam(monkeypatch, rec)
    resolved = {"pair_id": "soyoil_palm_vegoil", "source_slug": PALM, "target_slug": SOY,
                "trigger": "open_walk_idorder", "xc_open_rank": {"focus": PALM, "rank": "idorder"}}
    monkeypatch.setattr(cq, "resolve_xc_open", lambda req, sg, graph: (resolved, None))
    out = _run_seam(_deferred())
    assert rec.seen[0]["xc_request"] is resolved
    assert out["trace"]["xc_open_pair"] == {"focus": PALM, "rank": "idorder"}
    assert "xc_open_decline" not in out["trace"]
    assert "quantify_error" not in out["trace"]


def test_decline_rebinds_xc_request_to_none(monkeypatch):
    """A DECLINE makes quantify see exactly what a no-ask turn sees: no fork, no transmission attempt,
    zero cost -- and the decline itself is TRACED, so an attempted-and-declined turn stays
    distinguishable from a no-match turn in the census."""
    rec = _QuantifyRec()
    _wire_seam(monkeypatch, rec)
    dec = {"reason": "focus_not_paired", "focus": "corn", "first_paired_seed": None}
    monkeypatch.setattr(cq, "resolve_xc_open", lambda req, sg, graph: (None, dec))
    out = _run_seam(_deferred())
    assert rec.seen[0]["xc_request"] is None
    assert out["trace"]["xc_open_decline"] == dec and "xc_open_pair" not in out["trace"]


def test_seam_block_is_inside_the_quantify_try_and_a_raising_resolver_degrades(monkeypatch):
    """M7 + P21. A raising resolver must kill the FORK and nothing else: the qualitative answer still
    renders, quantify still runs (`quantify_error` absent), and the failure is recorded as a decline."""
    rec = _QuantifyRec()
    _wire_seam(monkeypatch, rec)

    def boom(req, sg, graph):
        raise RuntimeError("resolver exploded")
    monkeypatch.setattr(cq, "resolve_xc_open", boom)
    out = _run_seam(_deferred())
    assert out["answer"] and rec.seen and rec.seen[0]["xc_request"] is None
    assert out["trace"]["xc_open_decline"] == {"reason": "error"}
    assert "quantify_error" not in out["trace"]                     # the quantify block SURVIVED the raise


def test_seam_source_shape_is_belted_at_every_write():
    """NARROWED PIN, declared. `test_seam_survives_a_traceless_sg` cannot be driven end-to-end: on the
    real `_answer_l2` path `sg` is the planner's own Subgraph and its `trace` is a plain dict, so a
    traceless sg is not constructible from outside without replacing the walk. The belt is therefore
    pinned STRUCTURALLY, on the landed source (the `test_transmission_chain.py` source-inspection
    idiom): the D-XT block sits INSIDE the quantify `try`, carries its own inner try (P21), and each of
    the two trace writes is individually belted."""
    src = Path(an.__file__).read_text(encoding="utf-8")
    seam = src[src.index("OPEN-TARGET RESOLUTION (D-XT"):]
    seam = seam[:seam.index("_pace_kw =")]
    # the block is reached only through the `defer` argument, and the resolver call has its own belt
    assert 'xc_request.get("defer") == "walk"' in seam
    assert seam.count("try:") == 3 and seam.count("except Exception:") == 3
    assert 'sg.trace["xc_open_pair"]' in seam and 'sg.trace["xc_open_decline"]' in seam
    # ...and the whole block sits between the quantify stage timer and the quantify call, i.e. INSIDE
    # the `try:` whose purpose is to degrade a quantify-path failure to the qualitative answer.
    head = src[:src.index("OPEN-TARGET RESOLUTION (D-XT")]
    assert head.rstrip().endswith("# ──"), head.rstrip()[-40:]
    assert "_t_quant = time.perf_counter()" in head[-600:]
    assert "try:" in head[-800:]


# ════════════════════════════════════════════════════════════════════════════════════════════════════
# I -- THE FRAME GUARD (F2) + CHAIN-VS-PAIR PRECEDENCE (a5.4/a5.6)
# ════════════════════════════════════════════════════════════════════════════════════════════════════
_SOY_CRUSH_SHIPPED = ("the crush shifted toward one product on DEMAND (meal and oil are JOINT products "
                      "co-produced on the supply side, so a co-move is not a relative-value story; only "
                      "a demand divergence opposes)")
_SOY_CRUSH_OPEN = ("the shock reached the second leg of the crush; meal and oil are JOINT products "
                   "co-produced on the supply side, and the record here does not say which side moved")


def test_soy_crush_frame_bytes_unchanged_without_open_ask():
    row = _Pair("soymeal_soyoil_crush", MEAL, SOY, relation="competes_with", complex_name="soy_crush")
    assert cq._xc_frame(row, _sg()) == _SOY_CRUSH_SHIPPED
    assert cq._xc_frame(row, _sg(), open_ask=False) == _SOY_CRUSH_SHIPPED


@pytest.mark.parametrize("shared", [True, False])
def test_soy_crush_open_ask_drops_the_demand_claim_unconditionally(monkeypatch, shared):
    """F2, and it is NOT gated on `_shared_event_matched`: MEASURED INERT -- on the banked cc1_r1
    admissions that matcher returns True for board_crush 14/14 and soybean_crush_margin 14/14. A 14/14
    matcher is not a gate. The user asked 'what else is affected', not 'did demand shift the crush';
    asserting a demand shift onto an acreage/supply question is the sign-identity class."""
    monkeypatch.setattr(cq, "_shared_event_matched", lambda sg, ev: shared)
    row = _Pair("soymeal_soyoil_crush", MEAL, SOY, relation="competes_with", complex_name="soy_crush")
    assert cq._xc_frame(row, _sg(), open_ask=True) == _SOY_CRUSH_OPEN
    assert "DEMAND" not in cq._xc_frame(row, _sg(), open_ask=True)


def test_non_soy_crush_frames_are_untouched_by_open_ask(monkeypatch):
    monkeypatch.setattr(cq, "_shared_event_matched", lambda sg, ev: False)
    for cname in ("vegoil_substitution", "feed_grain"):
        row = _Pair("p", PALM, SOY, complex_name=cname)
        assert cq._xc_frame(row, _sg(), open_ask=True) == cq._xc_frame(row, _sg())


def test_run_xc_omits_open_ask_kwarg_when_not_open(monkeypatch):
    """N12, and it is LOAD-BEARING, not cosmetic. The gate-test stub replaces `_reroute_xc` with a
    POSITIONAL-ONLY `lambda *a:`; passing `open_ask` unconditionally would raise TypeError, which
    `_run_xc`'s belt swallows into a silent ([], None) -- an open-ask turn would decline INVISIBLY.
    This pin exercises exactly that stub."""
    monkeypatch.setattr(cq, "_load_pair_row", lambda pid: object())
    monkeypatch.setattr(cq, "_xc_focus_windows", lambda *a: ["w"])
    monkeypatch.setattr(cq, "_reroute_xc", lambda *a: (["line"], {"pair_id": "p"}))
    named = {"pair_id": "p", "source_slug": PALM, "target_slug": SOY, "detect_tier": "llm"}
    block, fired = cq._run_xc(named, None, None, [], None, "2026-02-15", None, [])
    assert block == ["line"] and fired["detect_tier"] == "llm" and "trigger" not in fired
    # the SAME positional-only stub, now handed an OPEN request: the kwarg IS passed, the stub raises,
    # and the belt swallows it -- which is why the omit-when-off idiom must stay.
    open_req = dict(named, trigger="open_walk_idorder")
    assert cq._run_xc(open_req, None, None, [], None, "2026-02-15", None, []) == ([], None)


def test_run_xc_passes_open_ask_and_stamps_the_trigger(monkeypatch):
    seen = {}

    def stub(*a, **kw):
        seen.update(kw)
        return (["line"], {"pair_id": "p"})
    monkeypatch.setattr(cq, "_load_pair_row", lambda pid: object())
    monkeypatch.setattr(cq, "_xc_focus_windows", lambda *a: ["w"])
    monkeypatch.setattr(cq, "_reroute_xc", stub)
    req = {"pair_id": "p", "source_slug": PALM, "target_slug": SOY,
           "detect_tier": "llm_open", "trigger": "open_walk_idorder"}
    block, fired = cq._run_xc(req, None, None, [], None, "2026-02-15", None, [])
    assert seen == {"open_ask": True}
    assert fired["trigger"] == "open_walk_idorder" and fired["detect_tier"] == "llm_open"


def test_transmission_declines_on_an_open_ask_with_a_traced_reason(monkeypatch):
    """a5.4, DECIDED: on an open ask the PAIR wins and the composer is suppressed BEFORE selection --
    `_xmit_select` picks by FILE ORDER (the alphabet defect in another costume) and `_xmit_focus` carries
    zero information about an open ask. N10: `chain_id` is present as None deliberately -- no chain was
    selected, but the T2b ledger reads a UNIFORM decline shape."""
    called = []
    monkeypatch.setattr(cq, "load_transmission_map", lambda: called.append("map") or [])
    req = {"pair_id": "p", "source_slug": PALM, "target_slug": SOY, "trigger": "open_walk_idorder"}
    lines, fired, decline = cq._transmission_legs(
        _sg(seeds=[PALM]), _graph(PALM, SOY), [{"commodity": PALM, "eras": []}], req,
        lambda sql: [], "2026-02-15", None, [], comove=False, chain_fired=False)
    assert lines == [] and fired is None
    # 9af92649 A2 RE-PIN: every PRE-FETCH transmission decline now stamps net_reads 0 (cascade.py
    # _transmission_legs, the open-ask guard literal) -- declined before any fetch, so the spend is exactly 0.
    assert decline == {"chain_id": None, "reason": "open_ask_pair_precedence",
                       "trigger": "open_walk_idorder", "net_reads": 0}
    assert "chain_id" in decline and decline["chain_id"] is None
    assert called == []                                             # suppressed ABOVE the selector


def test_transmission_is_untouched_on_a_named_ask(monkeypatch):
    """The guard is scoped to the OPEN triggers alone: a NAMED request still reaches the map loader."""
    called = []
    monkeypatch.setattr(cq, "load_transmission_map", lambda: called.append("map") or [])
    req = {"pair_id": "p", "source_slug": PALM, "target_slug": SOY, "detect_tier": "llm"}
    lines, fired, decline = cq._transmission_legs(
        _sg(seeds=[PALM]), _graph(PALM, SOY), [{"commodity": PALM, "eras": []}], req,
        lambda sql: [], "2026-02-15", None, [], comove=False, chain_fired=False)
    assert called == ["map"] and decline is None and lines == [] and fired is None


def test_open_ask_precedence_reason_is_declared():
    """P1, a round-4 finding neither prior round caught: the new reason must join the shared enum, which
    reds `test_transmission_chain.py::test_decline_reasons_are_the_shared_enum_plus_one` (amended in the
    same sitting -- the ONLY edit to a shipped test in this wave, declared, not silent)."""
    assert "open_ask_pair_precedence" in cq._XMIT_DECLINE_REASONS
    assert cq._XMIT_DECLINE_REASONS - cq._CHAIN_DECLINE_REASONS == {"link_comove",
                                                                    "open_ask_pair_precedence"}


def test_transmission_link_threads_open_ask_belt_and_braces():
    """NARROWED PIN, declared. a5.3's `**_oa` at the `_transmission_legs` link call is BELT AND BRACES:
    a5.4's precedence guard makes an open ask structurally unreachable there, so no behavioural fixture
    can exercise it (reaching the link call would require defeating the guard this wave just landed).
    Pinned on the landed source instead, beside the guard that makes it dead code -- both must move
    together if a later wave relaxes the precedence decision."""
    src = Path(cq.__file__).read_text(encoding="utf-8")
    xmit = src[src.index("def _transmission_legs"):]
    assert xmit.count('_oa = {"open_ask": True} if (xc_request or {}).get("trigger") in _OPEN_TRIGGERS') == 1
    assert "comove,\n                                     **_oa)" in xmit
    assert cq._OPEN_TRIGGERS == ("open_walk_graph", "open_walk_idorder")


# ════════════════════════════════════════════════════════════════════════════════════════════════════
# J -- REGISTRATION (a3.5 / a6). The keys AND the merge that makes them reachable.
# ════════════════════════════════════════════════════════════════════════════════════════════════════
def test_xc_detect_is_a_decision_record_key():
    """The WHOLE dict rides (the `response_contract` precedent). The orchestrator has stamped it on
    every reasoning/hybrid turn since RV2 W2 while eval.py hand-lifted ONLY `.tier` -- so everything
    else reached NO artifact, silently: the exact class this registry exists to kill."""
    assert ("xc_detect", "xc_detect_decision") in tk.DECISION_RECORD_KEYS
    # D-XL RE-ANCHOR (2026-09-04), by exactly ONE and never loosened: the locator appends its whole
    # decision dict at the tail, so the xc_detect pin moves in by one and the new tail is NAMED here
    # rather than left as "whatever is last" -- an unnamed tail pin cannot tell an append from a sort.
    assert tk.DECISION_RECORD_KEYS[-2] == ("xc_detect", "xc_detect_decision")   # append-never-sort
    assert tk.DECISION_RECORD_KEYS[-1] == ("extreme_locator", "extreme_locator_decision")


def test_new_trace_keys_are_registered():
    """Registering BOTH is what separates the FOUR census outcomes: NO MATCH (both absent), ATTEMPTED-
    AND-DECLINED, FIRED, and DEFERRED-BUT-NEVER-RESOLVED (open_defer set, both keys absent) -- the
    seam-never-ran tripwire, pre-registered at 0."""
    assert "xc_open_pair" in tk.TRACE_RECORD_KEYS
    assert "xc_open_decline" in tk.TRACE_RECORD_KEYS


def test_detection_tier_column_is_unmoved():
    """No column shift at eval.py:1480 -- every banked artifact stays comparable."""
    src = (Path(orch.__file__).parent / "eval.py").read_text(encoding="utf-8")
    assert ('"detection_tier": ((out.get("intent_decision") or {}).get("xc_detect") or {}).get("tier")'
            in src)


def _respond_graph():
    from leviathan.causal import schema as cs
    from leviathan.graphrag import graph as g
    palm = cs.CausalContract(contract=PALM, aliases=["palm", "palm oil"],
                             drivers=[cs.Driver(id="export_ban", type="policy", sign="+",
                                                mechanism="ban")])
    soy = cs.CausalContract(contract=SOY, aliases=["soyoil", "soybean oil"],
                            drivers=[cs.Driver(id="crush", type="demand", sign="+", mechanism="crush")])
    return g.CausalGraph({PALM: palm, SOY: soy}, silver=set())


def _force(kind):
    return lambda q, call=None: {"intent": kind, "needs_numbers": kind in ("numbers_only", "hybrid"),
                                 "needs_reasoning": kind in ("reasoning", "hybrid")}


class _Recorder:
    def __init__(self):
        self.kwargs = None

    def __call__(self, query, **kw):
        self.kwargs = kw
        return {"answer": "stub", "structured": None, "evidence": [], "citations": []}


def test_open_probe_reaches_the_decision_record(monkeypatch):
    """N3: `decided["xc_detect"]` is built BEFORE the request exists and `_run_xc` copies no request keys
    into the fired trace -- so anything the request learned reached NO artifact. The merge closes it."""
    rec = _Recorder()
    monkeypatch.setattr(orch.an, "answer", rec)
    monkeypatch.setenv("GRAPHRAG_REROUTE_V2", "on")
    probe = {"n_hits": 2, "head": PALM, "top_n": 3, "ties": 1, "head_in_material": True}
    monkeypatch.setattr(orch, "_xc_request", lambda *a, **k: {
        "pair_id": None, "target_slug": None, "defer": "walk", "rank": "idorder",
        "route_probe": probe, "detect_tier": "llm_open"})
    out = orch.respond("where else does this reach?", graph=_respond_graph(), asof="2026-06-01",
                       classify=_force("reasoning"))
    xd = out["intent_decision"]["xc_detect"]
    assert xd["route_probe"] == probe
    assert xd["open_defer"] == "walk" and xd["open_rank"] == "idorder"
    assert xd["tier"] == "none" and "llm_consulted" in xd and "target_span" in xd


def test_decision_record_is_byte_identical_on_a_flag_off_turn(monkeypatch):
    """The merge is keyed on keys a flag-off request cannot carry, so an unflagged turn's decision dict
    is byte-identical to its pre-D-XT self."""
    rec = _Recorder()
    monkeypatch.setattr(orch.an, "answer", rec)
    monkeypatch.setenv("GRAPHRAG_REROUTE_V2", "on")
    monkeypatch.setattr(orch, "_xc_request", lambda *a, **k: {
        "pair_id": "soyoil_palm_vegoil", "source_slug": PALM, "target_slug": SOY})
    out = orch.respond("palm ban -- what does that do to soyoil?", graph=_respond_graph(),
                       asof="2026-06-01", classify=_force("reasoning"))
    assert out["intent_decision"]["xc_detect"] == {"tier": "regex", "llm_consulted": False,
                                                   "target_span": "soyoil"}


# ════════════════════════════════════════════════════════════════════════════════════════════════════
# L -- PREFLIGHT TRIPWIRES, frozen as tests (ZERO API, zero pg)
# ════════════════════════════════════════════════════════════════════════════════════════════════════
@pytest.mark.skipif(not CENSUS.exists(), reason="banked cascade census absent")
def test_preflight_all_seven_material_pairs_are_census_fires():
    """[M] candidate-bearing == fireable: all SEVEN curated material pairs read FIRES in the latest
    banked census, so realizability is not a filter on this lane and the G2 fire floor is decided by
    CANDIDATE-BEARING alone. A roster edit or a census regression reds this before an arm is bought."""
    pairs = json.loads(CENSUS.read_text(encoding="utf-8"))["pairs"]
    assert len(pairs) == 7
    assert [p["pair_id"] for p in pairs if p["verdict"] != "FIRES"] == []
    ids = {p["pair_id"] for p in pairs}
    assert ids == {"soyoil_palm_vegoil", "soyoil_rapeoil_vegoil", "palm_rapeoil_vegoil",
                   "soymeal_soyoil_crush", "soybeans_soymeal_crush", "soybeans_soyoil_crush",
                   "corn_wheat_feed"}


@pytest.mark.skipif(not CENSUS.exists() or not (_REPO / "configs" / "graphrag" / "numbers"
                                                / "complex_map.yaml").exists(),
                    reason="banked census or gitignored complex_map absent")
def test_preflight_the_census_roster_covers_the_curated_roster():
    """The ROSTER is the binding constraint on this wave, not the trigger (c7.1). Every curated
    material pair must have BOTH legs realizability-proven -- by the banked pair census (the RV-W0
    seven) or by the RV roster sitting's per-slug probe (2026-08-29: the probe is per-slug because
    _pair_verdict is per-leg, so slug-FIRES x2 == pair-FIRES). A material pair proven by NEITHER
    is a roster edit that skipped its census -- the exact drift this pin exists to red."""
    curated = cm.load_complex_map().pairs
    banked = {p["pair_id"] for p in json.loads(CENSUS.read_text(encoding="utf-8"))["pairs"]}
    probe_path = _REPO / "data" / "batch_runs" / "rv_slug_probe_20260829.json"
    probed = set()
    if probe_path.exists():
        pj = json.loads(probe_path.read_text(encoding="utf-8"))["slugs"]
        probed = {s for s, v in pj.items()
                  if v.get("world_nonempty") is True and v.get("era_disjoint") is True}
    banked_slugs = {s for p in curated if p.id in banked for s in p.pair}
    unproven = [p.id for p in curated
                if p.id not in banked and not all(s in probed | banked_slugs for s in p.pair)]
    assert not unproven, f"material pairs with an unproven leg: {unproven}"


@pytest.mark.skipif(not CENSUS.exists() or not (_REPO / "configs" / "graphrag" / "numbers"
                                                / "complex_map.yaml").exists(),
                    reason="banked census or gitignored complex_map absent")
def test_preflight_generic_contract_ids_are_legs_of_no_curated_pair():
    """c7.1, pinned so the cost stays visible: the GENERIC contract ids the planner often names first
    ('corn', 'soybeans') are distinct from corn_cbot/soybeans_cbot and are legs of ZERO curated pairs.
    Those turns decline `focus_not_paired` -- a ROSTER finding, and it goes to the owner as one."""
    legs = {s for p in cm.load_complex_map().pairs for s in cm.pair_slugs(p)}
    assert "corn" not in legs and "soybeans" not in legs
    assert CORN in legs and BEANS in legs


def test_pair_leg_helpers_have_one_producer():
    """P10: the gate and the resolver read the SAME leg logic -- a second pair-leg producer minted in
    cascade was the duplicate-and-drift class round 3 named (m3) and round 4 re-caught."""
    p = _Pair("soyoil_palm_vegoil", SOY, PALM)
    assert cm.pair_slugs(p) == (SOY, PALM)
    assert cm.pair_other(p, SOY) == PALM and cm.pair_other(p, PALM) == SOY
    assert cm.pair_other(p, RAPE) is None
    assert orch._xc_pair_slugs(p) == cm.pair_slugs(p)               # the orchestrator alias is thin
    assert orch._xc_other(p, SOY) == cm.pair_other(p, SOY)
    side_only = SimpleNamespace(pair=None, side_a={"contract": SOY}, side_b={"contract": PALM})
    assert cm.pair_slugs(side_only) == (SOY, PALM)                  # the defensive fallback survived


def test_open_decline_vocabulary_is_declared():
    """Every decline the resolver can emit is enumerated, so the census can read the four outcomes
    apart without guessing at a string."""
    assert set(cq.XC_OPEN_DECLINES) == {"no_focus", "focus_not_paired", "no_realizable",
                                        "crush_not_traversed", "error"}
    assert re.match(r"^open_walk_", cq._OPEN_TRIGGERS[0])
