"""Dispatch planner v1 — enum-locked routing plan + orchestrator wiring (all mocked; no LLM spend).

Pins: validation (steps/contracts/asof/near enum + clip rules), every fallback path (env, exception,
empty plan), the step->branch mapping, the executor-side live kill-switch, near passthrough, the
planner-resolved coreference reaching route_fn, and the numbers context hint. The exact convo_e failure
("I meant the Kansas one." after wheat) is the e2e case — it is the measured defect this module fixes.
"""
from __future__ import annotations

from leviathan.causal import schema as cs
from leviathan.graphrag import dispatch as dp
from leviathan.graphrag import graph as g
from leviathan.graphrag import orchestrator as orch
from leviathan.graphrag import session as ss


def _graph() -> g.CausalGraph:
    mk = lambda cid, drv: cs.CausalContract(contract=cid, aliases=[], drivers=[     # noqa: E731
        cs.Driver(id=drv, type="hazard", sign="+", mechanism="m")])
    return g.CausalGraph({"soft_red_winter_wheat_cbot": mk("soft_red_winter_wheat_cbot", "drought"),
                          "hard_red_winter_wheat_kcbt": mk("hard_red_winter_wheat_kcbt", "drought"),
                          "corn": mk("corn", "drought")}, silver=set())


IDS = {"soft_red_winter_wheat_cbot", "hard_red_winter_wheat_kcbt", "corn"}


# ── validation ─────────────────────────────────────────────────────────────────────────────────────
def test_validate_drops_unknowns_dedupes_and_clips():
    p = dp._validate({"steps": ["reasoning", "sql_injection", "reasoning", "numbers", "live"],
                      "contracts": ["corn", "unicorn_futures", "hard_red_winter_wheat_kcbt",
                                    "soft_red_winter_wheat_cbot"],
                      "asof": "not-a-date", "near": "circa 2010"}, IDS)
    assert p.steps == ["reasoning", "numbers", "live"][:dp.MAX_STEPS]
    assert p.contracts == ["corn", "hard_red_winter_wheat_kcbt"]        # unknown dropped, clipped to 2
    assert p.asof is None and p.near is None and not p.fallback


def test_validate_empty_steps_is_fallback_and_good_fields_survive():
    assert dp._validate({"steps": [], "contracts": ["corn"]}, IDS).fallback
    p = dp._validate({"steps": ["reasoning"], "contracts": [], "asof": "2013-03-15", "near": "2010-08"}, IDS)
    assert (p.asof, p.near, p.fallback) == ("2013-03-15", "2010-08", False)


def test_kind_maps_step_patterns_to_branches():
    K = lambda steps: dp.Plan(steps=steps, contracts=[]).kind()         # noqa: E731
    assert K(["numbers"]) == "numbers_only"
    assert K(["reasoning"]) == "reasoning"
    assert K(["numbers", "reasoning"]) == "hybrid"
    assert K(["reasoning", "numbers"]) == "hybrid"                      # order tolerated, numbers feed reasoner
    assert K(["live", "reasoning"]) == "live"


# ── plan_turn ──────────────────────────────────────────────────────────────────────────────────────
def test_plan_turn_env_kill_and_exception_fall_back(monkeypatch):
    monkeypatch.setenv("GRAPHRAG_DISPATCH", "rules")
    assert dp.plan_turn("q", graph=_graph(), call=lambda *a, **k: {"steps": ["reasoning"]}).fallback
    monkeypatch.delenv("GRAPHRAG_DISPATCH")

    def boom(*a, **k):
        raise RuntimeError("api down")
    assert dp.plan_turn("q", graph=_graph(), call=boom).fallback        # routing never breaks an answer


def test_plan_turn_prompt_carries_state_and_enum_orders_carried_first():
    seen = {}

    def call(system, user, *, model, tool):
        seen.update(system=system, user=user, tool=tool)
        return {"steps": ["reasoning"], "contracts": ["hard_red_winter_wheat_kcbt"]}

    p = dp.plan_turn("I meant the Kansas one.", graph=_graph(), state_block="- discussing contracts: wheat",
                     today="2026-07-03", state_contracts=["hard_red_winter_wheat_kcbt"], call=call)
    assert p.contracts == ["hard_red_winter_wheat_kcbt"] and p.kind() == "reasoning"
    assert "NEVER answer the question" in seen["system"]                # the constitution, cached-stable
    assert "are REASONING even when phrased as a count" in seen["system"]   # P1.3 regime/timing routing rule
    assert "discussing contracts: wheat" in seen["user"] and "TODAY: 2026-07-03" in seen["user"]
    enum = seen["tool"]["input_schema"]["properties"]["contracts"]["items"]["enum"]
    assert enum[0] == "hard_red_winter_wheat_kcbt"                      # carried contract leads the enum


# ── orchestrator wiring (fake planner via `call` tool-name dispatch) ───────────────────────────────
def _call_factory(plan_out, log=None):
    def call(system, user, *, model, tool):
        if tool["name"] == "set_plan":
            return dict(plan_out)
        if log is not None:
            log.append(tool["name"])
        return {"tldr": "t", "mechanism": "m", "diagram_mermaid": "", "sources": []}
    return call


def _retrieve(q, node, *, k, asof=None, near=None):
    _retrieve.near = near
    return [{"date": "2024-01-01", "source": "usda_wasde", "source_key": f"s3://{node}", "text": "note"}]


def test_respond_planner_resolves_pronoun_to_carried_contract_and_reasoning():
    """The convo_e defect end-to-end: short follow-up after wheat routes REASONING on the Kansas contract."""
    store = ss.InMemoryStore()
    store.append_turn("s1", ss.TurnRecord(turn=0, query="Thoughts on wheat right now?", answer_tldr="t",
                                          contracts=["hard_red_winter_wheat_kcbt"], asof="2026-07-01",
                                          intent="reasoning", ts=0.0))
    store.put_state("s1", ss.SessionState(contracts=["hard_red_winter_wheat_kcbt"], asof_latest="2026-07-01",
                                          turn_count=1))
    call = _call_factory({"steps": ["reasoning"], "contracts": ["hard_red_winter_wheat_kcbt"], "near": "2010-08"})
    out = orch.respond("How did the 2010 Russia export ban play out for it?", graph=_graph(),
                       call=call, retrieve=_retrieve, session_id="s1", session_store=store)
    assert out["intent"] == "reasoning"
    assert out["contract"] == "hard_red_winter_wheat_kcbt"              # planner coreference reached route_fn
    assert _retrieve.near == "2010-08"                                  # era hint reached retrieval
    assert out["intent_decision"]["planner"] == "llm"
    assert out["asof"] == "2026-07-01"                                  # carried; the plan set no asof


def test_respond_plan_asof_fills_explicit_slot_but_never_beats_caller_arg():
    call = _call_factory({"steps": ["reasoning"], "contracts": ["corn"], "asof": "2013-03-15"})
    out = orch.respond("same but as of March 2013", graph=_graph(), call=call, retrieve=_retrieve)
    assert out["asof"] == "2013-03-15"                                  # turn-stated cutoff honored
    out2 = orch.respond("same but as of March 2013", graph=_graph(), call=call, retrieve=_retrieve,
                        asof="2024-06-01")
    assert out2["asof"] == "2024-06-01"                                 # the caller's arg is law


def test_respond_live_step_demoted_to_reasoning_by_past_asof_killswitch():
    call = _call_factory({"steps": ["live", "reasoning"], "contracts": ["corn"]})
    out = orch.respond("any news on corn?", graph=_graph(), call=call, retrieve=_retrieve, asof="2020-01-01")
    assert out["intent"] == "reasoning"                                 # the plan is advice, the guard is law
    assert "live_events" not in out


def test_respond_numbers_step_gets_contract_context_hint(monkeypatch):
    seen = {}

    def fake_numbers(query, asof, **kw):
        seen["q"] = query
        return {"answer": "42", "intent": "numbers_only", "citations": [], "number_calls": [],
                "evidence": [], "asof": asof, "structured": None, "contract": None}
    monkeypatch.setattr(orch, "run_numbers_only", fake_numbers)
    call = _call_factory({"steps": ["numbers"], "contracts": ["hard_red_winter_wheat_kcbt"]})
    orch.respond("And exports?", graph=_graph(), call=call)
    assert "conversation context" in seen["q"] and "hard_red_winter_wheat_kcbt" in seen["q"]


def test_respond_fallback_plan_uses_legacy_classifier(monkeypatch):
    monkeypatch.setenv("GRAPHRAG_DISPATCH", "rules")
    called = {}

    def classify_spy(q, call=None):
        called["legacy"] = True
        return {"intent": "reasoning", "needs_numbers": False, "needs_reasoning": True}
    monkeypatch.setattr(orch.it, "classify_intent", classify_spy)
    out = orch.respond("why is corn bullish", graph=_graph(),
                       call=_call_factory({}), retrieve=_retrieve)
    assert called.get("legacy") and out["intent"] == "reasoning"
    monkeypatch.delenv("GRAPHRAG_DISPATCH")


def test_plan_country_validated_and_reaches_numbers_hint(monkeypatch):
    p = dp._validate({"steps": ["numbers"], "contracts": [], "country": "  Brazil  "}, IDS)
    assert p.country == "Brazil" and p.trace()["country"] == "Brazil"

    seen = {}

    def fake_numbers(query, asof, **kw):
        seen["q"] = query
        return {"answer": "42", "intent": "numbers_only", "citations": [], "number_calls": [],
                "evidence": [], "asof": asof, "structured": None, "contract": None}
    monkeypatch.setattr(orch, "run_numbers_only", fake_numbers)
    call = _call_factory({"steps": ["numbers"], "contracts": ["corn"], "country": "Brazil"})
    orch.respond("And exports?", graph=_graph(), call=call)
    assert "corn, Brazil" in seen["q"]                               # geography rides the context hint
