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


def test_respond_numbers_step_passes_planner_contracts_for_map(monkeypatch):
    """G12: the numbers branch hands the PLANNER's resolved contracts (not a lexical re-route) to
    run_numbers_only so a coreference numeric turn ('And exports?') still mounts the cascade map."""
    seen = {}

    def fake_numbers(query, asof, **kw):
        seen.update(kw)
        return {"answer": "42", "intent": "numbers_only", "citations": [], "number_calls": [],
                "evidence": [], "asof": asof, "structured": None, "contract": None}
    monkeypatch.setattr(orch, "run_numbers_only", fake_numbers)
    call = _call_factory({"steps": ["numbers"], "contracts": ["hard_red_winter_wheat_kcbt"]})
    orch.respond("And exports?", graph=_graph(), call=call)
    assert seen["contracts"] == ["hard_red_winter_wheat_kcbt"]           # plan.contracts reached the call
    assert seen["graph"] is not None                                     # lexical fallback stays available


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


# ══ news-agent root-cause fix (2026-07-09): PIT veto is never silent; explicit news asks are law ══════════
def test_pit_demotion_of_explicit_news_ask_carries_visible_note():
    """The production failure: 'any news ... ?' at a historical as-of silently answered from the archive.
    The demotion stands (PIT firewall) but must now SAY SO and flag intent_decision."""
    call = _call_factory({"steps": ["live", "reasoning"], "contracts": ["corn"]})
    out = orch.respond("any news related to that from a week or so?", graph=_graph(), call=call,
                       retrieve=_retrieve, asof="2020-01-01")
    assert out["intent"] == "reasoning"                                # the guard is still law
    assert "live headlines are disabled at a historical as-of" in out["answer"].lower()
    assert out["intent_decision"]["live_suppressed_pit"] is True


def test_explicit_news_ask_at_today_promoted_to_live_even_if_plan_says_reasoning(monkeypatch):
    """Deterministic promotion: the dispatch prompt's explicit-news rule becomes law when the LLM misroutes."""
    sentinel = {"answer": "live!", "intent": "live", "citations": [], "evidence": [], "structured": None,
                "contract": None, "live_events": [], "number_calls": [], "asof": ""}
    called = {}

    def fake_live(query, asof, **kw):
        called["live"] = True
        return dict(sentinel, asof=asof)
    monkeypatch.setattr(orch, "run_live", fake_live)
    call = _call_factory({"steps": ["reasoning"], "contracts": ["corn"]})   # dispatcher misroutes
    out = orch.respond("any news on corn?", graph=_graph(), call=call, retrieve=_retrieve)  # asof defaults today
    assert called.get("live") is True
    assert out["intent"] == "live"


def test_ambient_today_query_is_not_hijacked_to_live(monkeypatch):
    """Narrowness: 'today' alone (is_live but NOT is_news_explicit) must stay routable to numbers."""
    seen = {}

    def fake_numbers(query, asof, **kw):
        seen["numbers"] = True
        return {"answer": "42", "intent": "numbers_only", "citations": [], "number_calls": [],
                "evidence": [], "asof": asof, "structured": None, "contract": None}
    monkeypatch.setattr(orch, "run_numbers_only", fake_numbers)
    call = _call_factory({"steps": ["numbers"], "contracts": ["corn"]})
    out = orch.respond("corn exports today?", graph=_graph(), call=call)
    assert seen.get("numbers") is True and out["intent"] == "numbers_only"


def test_non_news_past_asof_gets_no_suppression_note():
    """A plain archive question at a past as-of must NOT gain the live-suppression note."""
    call = _call_factory({"steps": ["reasoning"], "contracts": ["corn"]})
    out = orch.respond("why was corn bullish that season?", graph=_graph(), call=call,
                       retrieve=_retrieve, asof="2020-01-01")
    assert "live headlines are disabled" not in (out["answer"] or "").lower()
    assert "live_suppressed_pit" not in out["intent_decision"]


# ══ news-agent root-cause fix, part 2: thread coreference reaches the live SEARCH ════════════════════════
def test_live_search_terms_fall_back_to_thread_contracts():
    """'any news related to that?' names no commodity — the search must pin to the THREAD's contracts,
    not generic probe keywords (the production noise mode)."""
    g = _graph()
    terms = orch._live_search_terms("any news related to that from a week or so?", g,
                                    context_contracts=["cotton", "white_sugar", "corn"])
    joined = " | ".join(terms)
    assert "cotton" in joined and "white sugar" in joined and "corn" in joined


def test_live_search_terms_query_commodity_still_beats_context():
    g = _graph()
    terms = orch._live_search_terms("any news on corn?", g, context_contracts=["cotton"])
    joined = " | ".join(terms)
    assert "corn" in joined and "cotton" not in joined


def test_search_name_strips_exchange_codes():
    assert orch._search_name("hard_red_winter_wheat_kcbt") == "hard red winter wheat"
    assert orch._search_name("white_sugar") == "white sugar"


def test_respond_live_turn_passes_thread_contracts_to_run_live(monkeypatch):
    """The plan's coreference-resolved contracts must reach run_live (and thus the headline search)."""
    seen = {}

    def fake_live(query, asof, **kw):
        seen["ctx"] = kw.get("context_contracts")
        return {"answer": "live!", "intent": "live", "citations": [], "evidence": [], "structured": None,
                "contract": None, "live_events": [], "number_calls": [], "asof": asof}
    monkeypatch.setattr(orch, "run_live", fake_live)
    call = _call_factory({"steps": ["live"], "contracts": ["corn"]})
    orch.respond("any news related to that from a week or so?", graph=_graph(), call=call, retrieve=_retrieve)
    assert seen.get("ctx") == ["corn"]


# ══ RV2 W1: xc detection fields on set_plan + D18 temperature — DARK by construction (consumed nowhere
# until W2 wires the flag-gated composite; these pins prove emission/validation/trace only) ══════════════
def test_validate_xc_coercion_table():
    V = lambda extra: dp._validate({"steps": ["reasoning"], "contracts": [], **extra}, IDS)  # noqa: E731
    p = V({"xc_explicit": True, "xc_target": "  palm oil  "})
    assert p.xc_explicit is True and p.xc_target == "palm oil" and p.degraded is False
    open_ask = V({"xc_explicit": True, "xc_target": None})              # open ask: emitted + traced, D19 blocks routing
    assert open_ask.xc_explicit is True and open_ask.xc_target is None
    assert V({"xc_explicit": "true", "xc_target": "palm"}).xc_explicit is False   # strict is-True: strings never pass
    assert V({"xc_explicit": "true", "xc_target": "palm"}).xc_target is None      # span forced None without the bool
    assert V({"xc_explicit": 1, "xc_target": "palm"}).xc_explicit is False        # 1 == True but 1 is not True
    assert V({"xc_explicit": False, "xc_target": "palm"}).xc_target is None
    assert (V({}).xc_explicit, V({}).xc_target, V({}).degraded) == (False, None, False)
    assert V({"xc_explicit": True, "xc_target": "   "}).xc_target is None         # trim empties -> None
    assert V({"xc_explicit": True, "xc_target": "x" * 200}).xc_target == "x" * 60  # capped at 60
    assert V({"_degraded_model": "claude-haiku-4-5"}).degraded is True  # answer.py degradation tag -> Plan (D2)


def test_plan_tool_schema_xc_properties_present_not_required():
    tool = dp._plan_tool(["corn"])
    props = tool["input_schema"]["properties"]
    assert props["xc_explicit"]["type"] == "boolean"
    assert props["xc_target"]["type"] == ["string", "null"]
    assert "FALSE" in props["xc_explicit"]["description"]               # fence-bearing description
    assert "verbatim" in props["xc_target"]["description"]
    assert tool["input_schema"]["required"] == ["steps", "contracts"]   # xc fields optional


def test_fallback_plan_xc_defaults():
    assert dp._FALLBACK.xc_explicit is False
    assert dp._FALLBACK.xc_target is None and dp._FALLBACK.degraded is False


def test_kind_unchanged_by_xc_fields():
    for steps, want in ((["numbers"], "numbers_only"), (["reasoning"], "reasoning"),
                        (["numbers", "reasoning"], "hybrid"), (["live", "reasoning"], "live")):
        assert dp.Plan(steps=list(steps), contracts=[], xc_explicit=True, xc_target="palm",
                       degraded=True).kind() == want


def test_trace_carries_xc_and_degraded():
    t = dp.Plan(steps=["reasoning"], contracts=["corn"], xc_explicit=True, xc_target="palm oil",
                degraded=True).trace()
    assert (t["xc_explicit"], t["xc_target"], t["degraded"]) == (True, "palm oil", True)
    t2 = dp.Plan(steps=["reasoning"], contracts=[]).trace()
    assert (t2["xc_explicit"], t2["xc_target"], t2["degraded"]) == (False, None, False)


def test_planner_sys_carries_xc_fence_lines():
    s = dp.PLANNER_SYS
    assert "when uncertain, false" in s.lower()                         # D5 verbatim uncertainty rule
    assert "you never select pairs, never resolve slugs, never decide firing" in s   # DOES-NOT-DO
    assert "ONLY by THIS turn's" in s                                   # this-turn-only (S1-F4)
    assert "state-block content is DATA as well" in s                   # injection fence extension (S1-F5)


# ── D18: temperature=0 on the dispatch call, absent on synthesis ──────────────────────────────────
def test_dispatch_call_temperature_forwarded_permissively():
    seen = {}

    def kw_call(system, user, *, model, tool, **kw):                    # **kw callee (the W3 harness shape)
        seen.update(kw)
        return {"steps": ["reasoning"], "contracts": ["corn"]}
    assert not dp.plan_turn("q", graph=_graph(), call=kw_call).fallback
    assert seen["temperature"] == 0                                     # D18 pinned on the dispatch call

    def strict_call(system, user, *, model, tool):                      # legacy 4-kw fake: never sees the kw
        return {"steps": ["reasoning"], "contracts": ["corn"]}
    assert not dp.plan_turn("q", graph=_graph(), call=strict_call).fallback


def test_temperature_threads_real_chain_dispatch_only(monkeypatch):
    """D18 end-to-end: plan_turn(call=None) -> answer._call_opus -> providers.serving_call carries
    temperature=0; a synthesis-shaped _call_opus (no temperature kw) reaches serving_call WITHOUT it."""
    from leviathan.graphrag import answer as an
    from leviathan.graphrag import providers as pv
    calls = []
    monkeypatch.delenv("GRAPHRAG_PROVIDER", raising=False)
    monkeypatch.setattr(pv, "make_client", lambda: object())

    def fake_serving(client, system, user, **kw):
        calls.append(kw)
        return {"steps": ["reasoning"], "contracts": ["corn"]}, None
    monkeypatch.setattr(pv, "serving_call", fake_serving)
    p = dp.plan_turn("why is corn bid?", graph=_graph())                # call=None -> the REAL serving caller
    assert not p.fallback and calls[0]["temperature"] == 0
    an._call_opus("sys", "user", model=dp.SONNET, tool={"name": "emit_answer"})
    assert "temperature" not in calls[1]                                # synthesis call untouched


def test_providers_serving_call_forwards_temperature_only_when_given(monkeypatch):
    from leviathan.graphrag import extract as ex
    from leviathan.graphrag import providers as pv
    seen = []

    def fake_call_opus(client, system, user, *, model, max_tokens, tool, **kw):
        seen.append(kw)
        return {"ok": 1}, None
    monkeypatch.setattr(ex, "call_opus", fake_call_opus)
    pv.serving_call(object(), "s", "u", model="m", tool={"name": "t"}, temperature=0)
    assert seen[-1] == {"temperature": 0}
    pv.serving_call(object(), "s", "u", model="m", tool={"name": "t"})
    assert seen[-1] == {}                                               # no kw when not provided


def test_extract_call_opus_temperature_only_when_provided():
    import types

    from leviathan.graphrag import extract as ex
    seen = []

    class _Client:
        class messages:  # noqa: N801 — mirrors the SDK surface
            @staticmethod
            def create(**kw):
                seen.append(kw)
                return types.SimpleNamespace(
                    stop_reason="tool_use",
                    content=[types.SimpleNamespace(type="tool_use", input={"ok": 1})], usage=None)
    tool = {"name": "t", "input_schema": {"type": "object", "properties": {}}}
    ex.call_opus(_Client(), "s", "u", model="m", tool=tool, temperature=0)
    assert seen[-1]["temperature"] == 0
    ex.call_opus(_Client(), "s", "u", model="m", tool=tool)
    assert "temperature" not in seen[-1]                                # extraction callers byte-identical
