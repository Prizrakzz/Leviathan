"""Session working memory (plan 7.5 Phases 1+2) + prompt caching — all mocked, no AWS/LLM.

What these pin: the PIT firewall (state carries ids and short strings; evidence/rows never cross turns
except via the SQL-keyed cache whose key embeds its own as-of), coreference routing from state, as-of
carry-unless-explicit, degradation (a broken store never breaks an answer), compaction guards, and the
prompt-cache block structure (stable prefix first, question last, breakpoints only on the real path).
"""
from __future__ import annotations

from leviathan.causal import schema as cs
from leviathan.graphrag import answer as an
from leviathan.graphrag import graph as g
from leviathan.graphrag import orchestrator as orch
from leviathan.graphrag import session as ss


def _graph() -> g.CausalGraph:
    arabica = cs.CausalContract(
        contract="arabica_coffee", aliases=["arabica"],
        drivers=[cs.Driver(id="frost", type="hazard", sign="+", mechanism="frost damage")])
    robusta = cs.CausalContract(
        contract="robusta_coffee", aliases=["robusta"],
        drivers=[cs.Driver(id="drought", type="hazard", sign="+", mechanism="drought")])
    return g.CausalGraph({"arabica_coffee": arabica, "robusta_coffee": robusta}, silver=set())


def _reason_call(system, user, *, model, tool):
    u = user if isinstance(user, str) else "\n".join(b["text"] if isinstance(b, dict) else str(b) for b in user)
    _reason_call.users = getattr(_reason_call, "users", []) + [u]
    return {"tldr": "frost squeeze thesis", "mechanism": "cold kills cherries", "diagram_mermaid": "",
            "sources": []}


def _retrieve(q, slice_, *, k, asof=None, near=None):
    return [{"date": "2021-07-20", "source": "GAIN", "source_key": "s3://a",
             "text": "PROPTEXT-9d1c frost damaged cherries"}]


def _respond(query, store, session_id="s1", asof=None, classify_kind="reasoning"):
    return orch.respond(query, graph=_graph(), asof=asof, session_id=session_id, session_store=store,
                        classify=lambda q, call=None: {"intent": classify_kind, "needs_numbers": False,
                                                       "needs_reasoning": True},
                        call=_reason_call, retrieve=_retrieve, planner="onehop")


# ── store round-trip + turn record ────────────────────────────────────────────────────────────────
def test_store_roundtrip_and_writeback():
    store = ss.InMemoryStore()
    out = _respond("how does frost hit arabica?", store, asof="2021-08-01")
    assert out["session"] == {"id": "s1", "turn": 0}
    snap = store.load("s1")
    assert snap.state.contracts == ["arabica_coffee"] and snap.state.asof_latest == "2021-08-01"
    assert snap.turns[-1].answer_tldr.startswith("frost squeeze")
    assert snap.turns[-1].query.startswith("how does frost")


def test_pit_firewall_state_carries_no_evidence():
    store = ss.InMemoryStore()
    _respond("how does frost hit arabica?", store, asof="2021-08-01")
    snap = store.load("s1")
    import json
    from dataclasses import asdict
    blob = json.dumps(asdict(snap.state)) + json.dumps([asdict(t) for t in snap.turns])
    assert "PROPTEXT-9d1c" not in blob                              # the retrieved prop text never enters state
    assert "s3://" not in blob                                      # nor source keys / evidence objects


# ── coreference + as-of carry ─────────────────────────────────────────────────────────────────────
def test_followup_routes_from_state_when_lexical_routing_empty():
    store = ss.InMemoryStore()
    _respond("how does frost hit arabica?", store, asof="2021-08-01")
    out = _respond("does it get worse into winter?", store)         # no commodity named -> lexical routing empty
    assert out["contract"] == "arabica_coffee"                      # resolved from session state
    joined = "\n".join(_reason_call.users)
    assert "PRIOR-CONVERSATION STATE" in joined                     # the state block reached the reasoner
    assert "NOT evidence" in joined


def test_explicit_commodity_beats_state():
    store = ss.InMemoryStore()
    _respond("how does frost hit arabica?", store, asof="2021-08-01")
    out = _respond("and what about robusta?", store)
    assert out["contract"] == "robusta_coffee"                      # lexical routing wins over carried state


def test_asof_carries_unless_specified():
    store = ss.InMemoryStore()
    _respond("how does frost hit arabica?", store, asof="2021-08-01")
    out2 = _respond("does it get worse?", store)                    # no asof -> carried
    assert out2["asof"] == "2021-08-01"
    out3 = _respond("does it get worse?", store, asof="2019-05-01")  # explicit -> wins + updates state
    assert out3["asof"] == "2019-05-01"
    assert store.load("s1").state.asof_latest == "2019-05-01"


# ── degradation + kill switch ─────────────────────────────────────────────────────────────────────
class _BrokenStore:
    def load(self, sid):
        raise RuntimeError("dynamo down")

    def append_turn(self, sid, t):
        raise RuntimeError("dynamo down")

    def put_state(self, sid, s):
        raise RuntimeError("dynamo down")


def test_broken_store_degrades_to_stateless_answer():
    out = _respond("how does frost hit arabica?", _BrokenStore(), asof="2021-08-01")
    assert out["contract"] == "arabica_coffee" and out["answer"]    # answer survives
    assert "session" not in out or out["session"].get("error") or out.get("session") is None


def test_sessions_env_off_never_touches_store(monkeypatch):
    monkeypatch.setenv("GRAPHRAG_SESSIONS", "off")
    touched = {"n": 0}

    class Spy(ss.InMemoryStore):
        def load(self, sid):
            touched["n"] += 1
            return super().load(sid)
    out = _respond("how does frost hit arabica?", Spy(), asof="2021-08-01")
    assert touched["n"] == 0 and out["contract"] == "arabica_coffee"


# ── compaction + numbers cache ────────────────────────────────────────────────────────────────────
def test_roll_summary_validates_entities_and_survives_failure():
    st = ss.SessionState()
    t = ss.TurnRecord(turn=0, query="q", answer_tldr="a", contracts=["arabica_coffee"], asof="2021-08-01")

    def fake_call(system, user, *, model, tool):
        return {"entities": ["arabica_coffee", "made_up_node"], "thesis": "x" * 999, "open_threads": ["t1"]}
    out = ss.roll_summary(st, t, graph=_graph(), call=fake_call)
    assert out.summary["entities"] == ["arabica_coffee"]            # model can't mint nodes into state
    assert len(out.summary["thesis"]) <= 400
    out2 = ss.roll_summary(out, t, graph=_graph(), call=lambda *a, **k: 1 / 0)
    assert out2.summary["entities"] == ["arabica_coffee"]           # failure keeps the previous summary


def test_numbers_cache_keyed_by_exact_sql():
    st = ss.SessionState()
    calls = {"n": 0}

    def inner(sql):
        calls["n"] += 1
        return [{"value": "42"}]
    q = ss.cached_query_fn(st, inner)
    a = "SELECT v WHERE CAST(d AS varchar) <= '2021-08-01'"
    b = "SELECT v WHERE CAST(d AS varchar) <= '2012-08-01'"         # different as-of -> different SQL -> miss
    assert q(a) == [{"value": "42"}] and q(a) == [{"value": "42"}] and calls["n"] == 1   # second hit cached
    q(b)
    assert calls["n"] == 2


# ── prompt caching structure ──────────────────────────────────────────────────────────────────────
def test_prompt_parts_context_first_question_last():
    sp, vp = an._prompt_parts("why frost?", ["arabica_coffee"], ["CTX"], ["EVIDENCE"])
    assert sp.startswith("=== CAUSAL GRAPH") and "CTX" in sp and "why frost?" not in sp
    assert vp.endswith("QUESTION: why frost?") and "EVIDENCE" in vp


def test_pack_tuple_only_on_real_path():
    assert an._pack("S", "V", True) == ("S", "V")                   # real call -> cached blocks
    assert an._pack("S", "V", False) == "S\n\nV"                    # injected fakes keep the string API
