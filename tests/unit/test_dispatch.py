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


def test_temp_kw_seat_gates_the_5_family_and_keeps_legacy_byte_identical():
    """2026-08-29 probe RCA: sonnet-5 400s on a bare `temperature` kwarg ('deprecated for this
    model'), and plan_turn's fail-closed wrapper turned that into a SILENT 14/14 fallback. The pin
    must drop for the 5-family seats and stay byte-identical everywhere else (model=None = every
    legacy caller; sonnet-4-6 = today's prod dispatch)."""
    def accepts_temp(system, user, *, model, tool, temperature=None):
        return {}

    assert dp._temp_kw(accepts_temp) == {"temperature": 0}                       # legacy: unchanged
    assert dp._temp_kw(accepts_temp, "claude-sonnet-4-6") == {"temperature": 0}  # prod seat: unchanged
    assert dp._temp_kw(accepts_temp, "claude-haiku-4-5") == {"temperature": 0}
    assert dp._temp_kw(accepts_temp, "claude-sonnet-5") == {}                    # the measured 400 seat
    assert dp._temp_kw(accepts_temp, "claude-opus-5") == {}
    assert dp._temp_kw(accepts_temp, "claude-fable-5") == {}


def test_plan_turn_threads_the_model_into_the_temp_gate(monkeypatch):
    """plan_turn must pass its RESOLVED model to _temp_kw — a 5-family dispatch seat that still
    received temperature=0 would silently fall back on every turn (the probe's exact signature)."""
    seen = {}

    def fake_call(system, user, *, model, tool, **kw):
        seen.update(kw)
        return {"steps": [], "contracts": []}

    class _G:
        contracts: dict = {}

    monkeypatch.setenv("GRAPHRAG_DISPATCH_MODEL", "claude-sonnet-5")
    dp.plan_turn("q", graph=_G(), call=fake_call)
    assert "temperature" not in seen
    monkeypatch.setenv("GRAPHRAG_DISPATCH_MODEL", "claude-sonnet-4-6")
    dp.plan_turn("q", graph=_G(), call=fake_call)
    assert seen.get("temperature") == 0


# -- STATE ENGINE Amendment 2 + the S6 re-fix's major 3: `named`, `dedup`, FLAG-OFF IDENTITY --------
#: HEAD's own pick expression, re-typed here so the pin is a SECOND WRITING of the rule rather than a
#: second reading of the code. `_validate`'s docstring quotes these two lines as the flag-off path
#: ("HEAD's own list comprehension and HEAD's own slice, character for character"); if the branch ever
#: stops taking them, this deck says so without needing a git checkout to compare against.
def _head_pick(plan: dict, ids: set, cap: int) -> list:
    return [c for c in (plan.get("contracts") or []) if c in ids][:max(1, int(cap))]


#: The two plans the S6 verifier named. A planner emits a LIST and nothing stops it emitting one slug
#: twice; the de-dup that collapses it MOVES the ceiling's arithmetic, which is why it is flag-gated.
_DUP = {"steps": ["reasoning", "numbers"],
        "contracts": ["corn", "corn", "hard_red_winter_wheat_kcbt", "soft_red_winter_wheat_cbot"]}
_QUAD = {"steps": ["reasoning"],
         "contracts": ["corn", "corn", "corn", "corn", "hard_red_winter_wheat_kcbt"]}


def test_validate_FLAG_OFF_is_HEADs_own_pick_on_duplicate_and_quadruple_plans():
    """S6 RE-FIX, MAJOR 3 -- THE PIN THE FIRST BUILD DID NOT HAVE.

    The routed-slug de-dup ran UNCONDITIONALLY, outside the `if named:` branch, so with
    GRAPHRAG_STATE_BOARD off the ceiling was applied to a DE-DUPLICATED list where HEAD applied it to
    the raw one: a plan naming one contract twice kept that contract plus TWO others where HEAD kept it
    plus ONE. A flag-off behaviour change, with no flag and no pin, under a docstring one line above
    that promised the opposite.

    MEASURED HERE ON BOTH SHAPES AND EVERY CEILING THE ESTATE SHIPS. The expectation is HEAD's own
    expression (`_head_pick`), and the literals below are what HEAD's module returned when this deck
    was written -- so a future edit fails on the RULE and on the VALUE, not on one of them."""
    for plan in (_DUP, _QUAD):
        for cap in (1, 2, 3, 4, 6):
            assert dp._validate(dict(plan), IDS, cap).contracts == _head_pick(plan, IDS, cap), (plan, cap)
    # ...and the same, written out, because a re-typed rule can be re-typed wrong twice
    assert dp._validate(dict(_DUP), IDS, 2).contracts == ["corn", "corn"]
    assert dp._validate(dict(_DUP), IDS, 3).contracts == ["corn", "corn", "hard_red_winter_wheat_kcbt"]
    assert dp._validate(dict(_QUAD), IDS, 3).contracts == ["corn", "corn", "corn"]
    assert dp._validate(dict(_QUAD), IDS, 4).contracts == ["corn"] * 4


def test_validate_flag_off_matches_HEADs_OWN_MODULE_when_git_can_hand_it_over():
    """THE THIRD PROOF OF FLAG-OFF IDENTITY: HEAD's `dispatch.py` loaded as its own module and its
    `_validate` run beside the tree's on the same plans.

    IT IS THE WEAKEST OF THE THREE AND IS WRITTEN THAT WAY DELIBERATELY. It compares against whatever
    HEAD happens to be, so once this work commits it compares the branch with itself and stops being a
    regression bar -- `test_validate_FLAG_OFF_is_HEADs_own_pick_...` above is the durable one. What it
    adds is the proof AT THE MOMENT OF THE FIX, reproducible by anyone who checks the tree out against
    the commit before it. It SKIPS rather than fails wherever git or the blob is not there (an
    installed wheel, a source tarball, a shallow worker image)."""
    import importlib.util
    import pathlib
    import subprocess
    import sys
    import tempfile

    import pytest
    root = pathlib.Path(__file__).resolve().parents[2]
    try:
        # `encoding="utf-8"` IS LOAD-BEARING ON THE OWNER'S BOX (S6 second verify, minor (d)).
        # `text=True` alone decodes with `locale.getpreferredencoding(False)`, which is cp1252 on
        # Windows -- so a non-ASCII byte anywhere in HEAD's `dispatch.py` would either raise
        # UnicodeDecodeError or, worse, mojibake silently and make this test compare the module
        # against a corrupted copy of itself. The blob is UTF-8; say so.
        blob = subprocess.run(["git", "-C", str(root), "show",
                               "HEAD:src/leviathan/graphrag/dispatch.py"],
                              capture_output=True, text=True, encoding="utf-8", timeout=60)
    except Exception:                                   # noqa: BLE001 -- no git on this box
        pytest.skip("git unavailable")
    if blob.returncode != 0 or not blob.stdout:
        pytest.skip("HEAD blob unavailable")
    with tempfile.TemporaryDirectory() as td:
        path = pathlib.Path(td) / "_head_dispatch.py"
        path.write_text(blob.stdout, encoding="utf-8", newline="")
        spec = importlib.util.spec_from_file_location("_head_dispatch", path)
        head = importlib.util.module_from_spec(spec)
        # REGISTERED BEFORE EXEC: `dataclasses` resolves a frozen class's own module out of
        # `sys.modules`, so a module that is not there yet raises inside the decorator.
        sys.modules["_head_dispatch"] = head
        try:
            spec.loader.exec_module(head)
            for plan in (_DUP, _QUAD):
                for cap in (1, 2, 3, 4, 6):
                    assert (head._validate(dict(plan), IDS, cap).contracts
                            == dp._validate(dict(plan), IDS, cap).contracts), (plan, cap)
        finally:
            sys.modules.pop("_head_dispatch", None)


def test_the_dedup_is_FLAG_GATED_and_collapses_first_occurrence_wins():
    """THE SWITCH ITSELF, ON. It is its OWN kwarg and not a rider on `named`'s truthiness, because a
    board turn that names NO market still anchors, still prices a tape column and still renders -- and
    those are not turns where a duplicate is harmless."""
    assert dp._validate(dict(_DUP), IDS, 2, dedup=True).contracts == [
        "corn", "hard_red_winter_wheat_kcbt"]                      # HEAD kept ["corn", "corn"]
    assert dp._validate(dict(_DUP), IDS, 3, dedup=True).contracts == [
        "corn", "hard_red_winter_wheat_kcbt", "soft_red_winter_wheat_cbot"]
    assert dp._validate(dict(_QUAD), IDS, 3, dedup=True).contracts == [
        "corn", "hard_red_winter_wheat_kcbt"]                      # four copies collapse to one
    # THE PLANNER'S OWN CENTRALITY ORDER IS UNTOUCHED: first occurrence wins, nothing is re-ranked.
    p = {"steps": ["reasoning"],
         "contracts": ["hard_red_winter_wheat_kcbt", "corn", "hard_red_winter_wheat_kcbt"]}
    assert dp._validate(dict(p), IDS, 3, dedup=True).contracts == ["hard_red_winter_wheat_kcbt", "corn"]
    # ...and an unknown slug is still dropped on BOTH paths, which is the fence the de-dup rides inside
    q = {"steps": ["reasoning"], "contracts": ["nope", "corn", "corn", "nope"]}
    assert dp._validate(dict(q), IDS, 3, dedup=True).contracts == ["corn"]
    assert dp._validate(dict(q), IDS, 3).contracts == ["corn", "corn"]


def test_named_markets_are_all_anchors_and_the_EXEMPTION_IS_BOUNDED():
    """AMENDMENT 2 AND ITS CEILING. Named markets escape `max_contracts`; the escape itself is bounded
    at `NAMED_ANCHOR_CAP`, in the PLAN's order, so the total is `NAMED_ANCHOR_CAP + max_contracts` and
    never the router's whole ranking."""
    ids = {"c%d" % i for i in range(12)}
    plan = {"steps": ["reasoning"], "contracts": ["c%d" % i for i in range(12)]}
    assert dp._validate(dict(plan), ids, 2).contracts == ["c0", "c1"]            # off: the ceiling
    # four named markets survive a quick turn's ceiling of two, and quick still infers two beyond them
    four = dp._validate(dict(plan), ids, 2, named=("c0", "c1", "c2", "c3")).contracts
    assert four == ["c0", "c1", "c2", "c3", "c4", "c5"]
    # EIGHT named on the same turn is bounded by NAMED_ANCHOR_CAP: six exempt, then the ordinary two
    eight = dp._validate(dict(plan), ids, 2, named=tuple("c%d" % i for i in range(8))).contracts
    assert len(eight) == dp.NAMED_ANCHOR_CAP + 2 == 8
    assert eight == ["c%d" % i for i in range(8)]
    # the residual is NAMED rather than hidden: past the cap a typed market keeps the ordinary ceiling
    twelve = dp._validate(dict(plan), ids, 2, named=tuple("c%d" % i for i in range(12))).contracts
    assert len(twelve) == dp.NAMED_ANCHOR_CAP + 2
    # the two switches compose without either reading the other
    dupe = {"steps": ["reasoning"], "contracts": ["c0", "c0", "c1", "c2", "c3"]}
    assert dp._validate(dict(dupe), ids, 2, named=("c0", "c1")).contracts == [
        "c0", "c0", "c1", "c2", "c3"]                       # named, no dedup: the duplicate survives
    assert dp._validate(dict(dupe), ids, 2, named=("c0", "c1"), dedup=True).contracts == [
        "c0", "c1", "c2", "c3"]


def test_named_markets_is_BOUNDED_by_its_own_declared_number_and_never_raises():
    """THE REVIEW'S CHEAP MINOR ON `named_markets`: the docstring claimed a bound and the function
    returned the router's whole ranking, so an estate law -- the exposure is bounded BEFORE the work --
    rested on a sentence. MEASURED on the shipped roster (2026-09-09): 36 contracts, seventeen matches
    for the four-market question, twenty-two for a six-market one, a widest single-token fan-out of six
    ("palm oil"). `NAMED_ROUTE_CAP` sits above that worst case and below the roster, so it bounds the
    return without binding on anything a question can legitimately name."""
    from leviathan.graphrag import answer as an
    from leviathan.graphrag import graph as G
    real = G.CausalGraph(G.load_contracts(), silver=set(), version="deck")
    assert dp.NAMED_ROUTE_CAP == 24 and dp.NAMED_ANCHOR_CAP == 6
    q4 = "How do wheat, corn, soybeans and palm oil compare right now?"
    q6 = "How do wheat, corn, soybeans, palm oil, sugar and coffee compare right now?"
    assert len(an.route(q4, real)) == 17 and len(an.route(q6, real)) == 22
    assert 22 < dp.NAMED_ROUTE_CAP < len(real.contracts)
    for q in (q4, q6):
        got = dp.named_markets(q, real)
        assert len(got) <= dp.NAMED_ROUTE_CAP
        assert list(got) == list(an.route(q, real))[:dp.NAMED_ROUTE_CAP]   # ONE matcher, never a copy
    # THE ORDER-SENSITIVE BOUND BELONGS IN `_validate` AND NOT HERE, measured: a flat cut of the
    # router's hits-then-alphabetical ranking drops two of the four markets the user actually typed.
    flat = list(an.route(q4, real))[:dp.NAMED_ANCHOR_CAP]
    assert "corn_cbot" not in flat and "soft_red_winter_wheat_cbot" not in flat
    assert "sunflower_oil" in flat
    # a naming census must never break a turn
    assert dp.named_markets("", None) == () and dp.named_markets(None, real) == ()
    assert dp.named_markets("wheat", object()) == ()


def test_plan_turn_is_OMIT_WHEN_OFF_at_all_three_cap_sites(monkeypatch):
    """With neither kwarg the PROMPT phrase, the SCHEMA `maxItems` and the VALIDATOR call are HEAD's --
    which is what makes an injected `_validate` written against the older signature still valid, the
    property every planner fixture in this suite rests on. With them, all three widen together."""
    seen: dict = {}

    def _cap_sys(n, **kw):
        seen["sys_n"] = n
        return "SYS"

    def _cap_tool(ids, n, *a):
        seen["tool_n"] = n
        return {"name": "plan", "input_schema": {"type": "object", "properties": {}}}

    def _cap_validate(out, ids, n, *a, **kw):
        seen["validate_n"] = n
        seen["kw"] = dict(kw)
        return dp.Plan(steps=["reasoning"], contracts=[])

    class _G:
        contracts: dict = {"corn": None}

    monkeypatch.setattr(dp, "planner_sys", _cap_sys)
    monkeypatch.setattr(dp, "_plan_tool", _cap_tool)
    monkeypatch.setattr(dp, "_validate", _cap_validate)
    monkeypatch.delenv("GRAPHRAG_DISPATCH", raising=False)
    monkeypatch.delenv("GRAPHRAG_DISPATCH_MODEL", raising=False)

    def call(s, u, **k):
        return {"steps": ["reasoning"], "contracts": []}

    dp.plan_turn("q", graph=_G(), call=call, max_contracts=2)
    assert seen == {"sys_n": 2, "tool_n": 2, "validate_n": 2, "kw": {}}    # ABSENT, not None-valued
    seen.clear()
    dp.plan_turn("q", graph=_G(), call=call, max_contracts=2,
                 named=("a", "b", "c", "d"), dedup=True)
    assert seen["sys_n"] == seen["tool_n"] == 4        # the prompt and the schema widen too...
    assert seen["validate_n"] == 2                     # ...while the ceiling stays the tier's
    assert seen["kw"] == {"named": ("a", "b", "c", "d"), "dedup": True}
    seen.clear()
    # the named set NEVER NARROWS the tier: a one-market question on a deep turn keeps its ceiling
    dp.plan_turn("q", graph=_G(), call=call, max_contracts=6, named=("a",))
    assert seen["sys_n"] == seen["tool_n"] == 6
