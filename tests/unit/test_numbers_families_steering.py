"""B1 -- thread `data_families` into the numbers agent, and give hybrid the handoff numbers_only had.

Two independent halves, one kill-switch (GRAPHRAG_NUMBERS_FAMILIES, default OFF, fail-closed):

  1. STEERING. The dispatch planner has been emitting `data_families` and the family-facet promotion has been
     reading it, stamping it on the decision, and THROWING THE LIST AWAY. It now rides the agent's user turn
     as a routing hint, resolved back to the TABLE IDS the agent's own tool enum accepts.
  2. HANDOFF PARITY. run_numbers_only has always built a coreference-enriched question ("And exports?" ->
     "...(conversation context: this refers to corn_cbot, BRAZIL)"); the hybrid lane passed the bare query.
     The same words reached the agent with a different amount of context purely because of a routing outcome.

B1 is a fix for GRAPH-BLINDNESS, not for the positioning defect: GRAPHRAG_FAMILY_FACET was already on in all
four measured arms and the promotion fired 118 times while the agent declined anyway. Steering moves a
probability. These tests pin the PLUMBING (a cot lookup is reachable and steered), never a model outcome.

No LLM spend: the agent client and the dispatch planner are injected fakes.
"""
from __future__ import annotations

import types

import pytest
from leviathan.causal import schema as cs
from leviathan.graphrag import dispatch as dp
from leviathan.graphrag import graph as g
from leviathan.graphrag import orchestrator as orch
from leviathan.graphrag.numbers import agent as na
from leviathan.graphrag.numbers import registry as nreg

CORN = "corn_cbot"


# -- the kill-switch: default OFF, fail-closed, copies the _family_facet_on idiom exactly -------------
@pytest.mark.parametrize("val,want", [
    ("on", True), ("ON", True),
    (" on ", False), ("off", False), ("0", False), ("1", False), ("true", False), ("yes", False),
    ("garbage", False), ("", False),
])
def test_numbers_families_flag_fail_closed(monkeypatch, val, want):
    monkeypatch.setenv("GRAPHRAG_NUMBERS_FAMILIES", val)
    assert orch._numbers_families_on() is want


def test_numbers_families_flag_default_off(monkeypatch):
    monkeypatch.delenv("GRAPHRAG_NUMBERS_FAMILIES", raising=False)
    assert orch._numbers_families_on() is False


# -- half 1: the steering line ------------------------------------------------------------------------
def _reg():
    return nreg.load_registry()


def test_family_prefix_mirrors_the_planner_enum_derivation():
    """The family enum is DERIVED by stripping this prefix off every registered table id, so resolving a
    family back to its table is undoing exactly that substitution. Pinned equal rather than imported, so the
    agent keeps no dependency on the planner module -- and so the two can never silently diverge."""
    assert na._FAMILY_PREFIX.pattern == dp._FAMILY_PREFIX.pattern


def test_families_line_names_the_table_id_not_the_family_stem():
    """A hint naming 'cot' is unusable: `lookup_number.table` is an enum over the registry, so the hint has
    to name what the model can actually pass."""
    line = na._families_line(_reg(), ["cot"])
    assert "silver_cot" in line and "ROUTING HINT" in line


def test_families_line_resolves_every_registered_family():
    """Registry-derived on both sides: every planner-emittable family resolves to a real table, so this
    generalizes past COT with nothing hardcoded."""
    fams = dp.family_names()
    reg = _reg()
    assert fams                                                  # the enum loaded
    for f in fams:
        line = na._families_line(reg, [f])
        if line:                                                 # flag-hidden cards resolve to "" (see below)
            assert f"silver_{f}" in line or f"gold_{f}" in line or f"bronze_{f}" in line


def test_families_line_empty_for_no_families():
    assert na._families_line(_reg(), None) == ""
    assert na._families_line(_reg(), []) == ""


def test_families_line_drops_an_unknown_family(monkeypatch):
    """Fail-soft: a family that resolves to no visible table disappears rather than steering the model at a
    table it does not have. A mis-plumbed enum degrades to today's turn, never to a lie."""
    assert na._families_line(_reg(), ["totally_made_up"]) == ""
    line = na._families_line(_reg(), ["totally_made_up", "cot"])
    assert "silver_cot" in line and "totally_made_up" not in line


def test_families_line_respects_the_pattern_records_kill_switch(monkeypatch):
    """Resolved against _visible_tables, not reg.tables -- the same kill-switch parity system_prompt keeps."""
    from leviathan.graphrag.numbers import pattern_records as PR
    fam = na._FAMILY_PREFIX.sub("", PR.PR_TABLE)
    monkeypatch.setenv("GRAPHRAG_PATTERN_RECORDS", "off")
    assert na._families_line(_reg(), [fam]) == ""                # the card is hidden -> so is the hint
    monkeypatch.setenv("GRAPHRAG_PATTERN_RECORDS", "on")
    assert PR.PR_TABLE in na._families_line(_reg(), [fam])


def test_families_line_refuses_to_promise_a_row():
    """The failure mode of steering is a fabricated row: 'implicated' can read as 'a value must exist'."""
    line = na._families_line(_reg(), ["cot"])
    assert "no_rows" in line and "not_known" in line and "never invent" in line


# -- half 1, wired: the hint reaches the model's user turn (and only when passed) ---------------------
def _ns(**kw):
    return types.SimpleNamespace(**kw)


class _Msgs:
    def __init__(self, outer):
        self.outer = outer

    def create(self, **kw):
        self.outer.seen.append(kw)
        return self.outer.q.pop(0)


class FakeAnthropic:
    def __init__(self, q):
        self.q = list(q)
        self.seen: list[dict] = []
        self.messages = _Msgs(self)


def _decline_client():
    """One turn, no tool use -- the plumbing is what is under test, never a model outcome."""
    return FakeAnthropic([_ns(content=[_ns(type="text", text="Nothing to look up.")], stop_reason="end_turn")])


def test_agent_user_turn_carries_the_hint_when_families_passed():
    c = _decline_client()
    na.answer_numbers("are funds crowded in corn?", "2026-06-01", client=c, families=["cot"])
    content = c.seen[0]["messages"][0]["content"]
    assert "As-of date (fixed): 2026-06-01" in content
    assert "silver_cot" in content
    assert content.rstrip().endswith("Question: are funds crowded in corn?")   # QUESTION keeps the last slot


def test_agent_user_turn_is_byte_identical_without_families():
    """Default None -> the pre-B1 string exactly, so every existing caller and fixture is untouched."""
    c = _decline_client()
    na.answer_numbers("are funds crowded in corn?", "2026-06-01", client=c)
    assert c.seen[0]["messages"][0]["content"] == \
        "As-of date (fixed): 2026-06-01\n\nQuestion: are funds crowded in corn?"


def test_agent_system_block_is_unchanged_by_families():
    """The hint rides the USER turn on purpose: `system` carries cache_control ephemeral and is byte-stable
    per (registry, flags), so a per-turn families line there would invalidate the prompt cache every turn."""
    a, b = _decline_client(), _decline_client()
    na.answer_numbers("q", "2026-06-01", client=a)
    na.answer_numbers("q", "2026-06-01", client=b, families=["cot"])
    assert a.seen[0]["system"] == b.seen[0]["system"]


def test_agent_reads_no_environment_for_families(monkeypatch):
    """The engine is gated by the ARGUMENT: flipping the kill-switch cannot steer a turn the orchestrator
    did not steer."""
    monkeypatch.setenv("GRAPHRAG_NUMBERS_FAMILIES", "on")
    c = _decline_client()
    na.answer_numbers("q", "2026-06-01", client=c)
    assert "ROUTING HINT" not in c.seen[0]["messages"][0]["content"]


# -- the orchestrator threading: both lanes, both halves, one flag ------------------------------------
def _graph() -> g.CausalGraph:
    corn = cs.CausalContract(contract=CORN, aliases=["corn", "maize"],
                             drivers=[cs.Driver(id="fund_flow", type="positioning", sign="+", mechanism="mm")])
    return g.CausalGraph({CORN: corn}, silver=set())


def _spy(monkeypatch, kind):
    """Record the kwargs the branch function was called with, without running an engine."""
    seen: dict = {}

    def run(*a, **k):
        seen["args"], seen["kw"] = a, k
        return {"answer": "stub", "intent": kind, "structured": None, "evidence": [], "citations": [],
                "number_calls": [], "contract": None, "contracts": []}

    monkeypatch.setattr(orch, f"run_{kind}", run)
    return seen


def _planner_call(families, steps, country=None):
    def call(system, user, *, model, tool, **kw):
        if tool["name"] == "set_plan":
            out = {"steps": list(steps), "contracts": [CORN], "data_families": list(families)}
            if country:
                out["country"] = country
            return out
        return {"tldr": "t", "mechanism": "m", "diagram_mermaid": "", "sources": []}
    return call


def _respond(monkeypatch, query, *, families, steps, flag, country=None):
    if flag is None:
        monkeypatch.delenv("GRAPHRAG_NUMBERS_FAMILIES", raising=False)
    else:
        monkeypatch.setenv("GRAPHRAG_NUMBERS_FAMILIES", flag)
    kind = "numbers_only" if steps == ("numbers",) else "hybrid"
    seen = _spy(monkeypatch, kind)
    orch.respond(query, graph=_graph(), asof="2026-06-01",
                 call=_planner_call(families, steps, country))
    return seen


def test_numbers_only_receives_the_planner_families(monkeypatch):
    seen = _respond(monkeypatch, "where does managed money net length in corn stand?",
                    families=["cot"], steps=("numbers",), flag="on")
    assert seen["kw"]["families"] == ["cot"]


def test_hybrid_receives_the_planner_families(monkeypatch):
    seen = _respond(monkeypatch, "given fund positioning is corn stretched?",
                    families=["cot"], steps=("numbers", "reasoning"), flag="on")
    assert seen["kw"]["families"] == ["cot"]


def test_hybrid_receives_the_enriched_numbers_query(monkeypatch):
    """Handoff parity: the numbers leg gets the coreference-enriched question numbers_only always built."""
    seen = _respond(monkeypatch, "and positioning?", families=["cot"],
                    steps=("numbers", "reasoning"), flag="on", country="BRAZIL")
    nq = seen["kw"]["numbers_query"]
    assert nq.startswith("and positioning?")
    assert "conversation context: this refers to" in nq and CORN in nq and "BRAZIL" in nq


def test_hybrid_walk_still_routes_on_the_raw_query(monkeypatch):
    """The enrichment reaches the NUMBERS leg only. route_fn's short-follow-up coreference gate keys on
    len(query), and an enriched string is past that bound -- handing it to the walk would silently disable
    the coreference route this same enrichment exists to preserve."""
    seen = _respond(monkeypatch, "and positioning?", families=["cot"],
                    steps=("numbers", "reasoning"), flag="on")
    assert seen["args"][0] == "and positioning?"                 # positional `query` -> raw, unchanged
    assert seen["kw"]["numbers_query"] != seen["args"][0]


def test_flag_off_passes_neither_half(monkeypatch):
    """Fail-closed: OFF -> families None and numbers_query None -> the hybrid call is byte-identical."""
    seen = _respond(monkeypatch, "and positioning?", families=["cot"],
                    steps=("numbers", "reasoning"), flag="off")
    assert seen["kw"]["families"] is None and seen["kw"]["numbers_query"] is None


def test_flag_absent_passes_neither_half(monkeypatch):
    seen = _respond(monkeypatch, "and positioning?", families=["cot"],
                    steps=("numbers", "reasoning"), flag=None)
    assert seen["kw"]["families"] is None and seen["kw"]["numbers_query"] is None


def test_numbers_only_question_unchanged_by_the_flag(monkeypatch):
    """The nq enrichment on numbers_only is PRE-EXISTING behavior and is NOT newly flag-gated -- only the
    families hint is. A flag that silently removed the enrichment would be a regression dressed as a rollback."""
    off = _respond(monkeypatch, "and exports?", families=["esr"], steps=("numbers",), flag="off")
    on = _respond(monkeypatch, "and exports?", families=["esr"], steps=("numbers",), flag="on")
    assert off["args"][0] == on["args"][0]
    assert "conversation context: this refers to" in off["args"][0]
    assert off["kw"]["families"] is None and on["kw"]["families"] == ["esr"]


def test_no_families_from_the_planner_passes_none(monkeypatch):
    """An empty list is passed as None, not [] -- absent means absent, and the agent's hint builder never
    has to distinguish 'no families' from 'families we dropped'."""
    seen = _respond(monkeypatch, "why is corn convex here?", families=[],
                    steps=("numbers", "reasoning"), flag="on")
    assert seen["kw"]["families"] is None


def test_unknown_family_never_reaches_the_agent(monkeypatch):
    """The planner's _validate drops a minted family, so the model cannot inject a steering target."""
    seen = _respond(monkeypatch, "where does corn positioning stand?", families=["totally_made_up"],
                    steps=("numbers",), flag="on")
    assert seen["kw"]["families"] is None


def test_run_hybrid_defaults_keep_the_agent_call_unchanged(monkeypatch):
    """Backward compatibility at the function boundary: an existing caller that passes neither kwarg gets
    the pre-B1 answer_numbers call exactly."""
    seen: dict = {}

    def fake_answer_numbers(q, asof, **kw):
        seen["q"], seen["kw"] = q, kw
        return {"calls": [], "answer": "x"}

    monkeypatch.setattr(na, "answer_numbers", fake_answer_numbers)
    monkeypatch.setattr(orch.an, "answer",
                        lambda q, **kw: (kw["extra_resolver"](), {"answer": "a", "trace": {}})[1])
    orch.run_hybrid("bare query", "2026-06-01", graph=_graph())
    assert seen["q"] == "bare query" and seen["kw"]["families"] is None
