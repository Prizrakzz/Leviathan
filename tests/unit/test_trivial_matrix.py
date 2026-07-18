"""Trivial/ambiguous ROUTER MATRIX (F1 Wave-6 gate #3) — the pre-ship correctness table.

>=16 rows spanning every class the router must get right: greetings, thanks/smalltalk, meta, off-topic-but-
real, greeting+real-question, terse ambiguous, empty/whitespace, PLUS the REQUIRED escaping-vocabulary rows
(verifier F3: a greeting token + short + fires NEITHER _NUM nor _REASON, so only the full-string anchor carries
them). Each trivial row asserts short-circuit + correct class + register-clean reply + session state untouched;
each fall-through row asserts dispatch IS reached. Mirrors configs/graphrag/eval_trivial_matrix_v1.yaml.
"""
from __future__ import annotations

import pathlib

import pytest
import yaml

from leviathan.causal import schema as cs
from leviathan.graphrag import graph as g
from leviathan.graphrag import intent as it
from leviathan.graphrag import orchestrator as orch
from leviathan.graphrag import register as reg
from leviathan.graphrag import session as ss


def _graph() -> g.CausalGraph:
    coffee = cs.CausalContract(contract="arabica_coffee", aliases=["arabica"],
                               drivers=[cs.Driver(id="frost", type="hazard", sign="+", mechanism="frost")])
    corn = cs.CausalContract(contract="corn", aliases=["maize"],
                             drivers=[cs.Driver(id="drought", type="hazard", sign="+", mechanism="dry")])
    return g.CausalGraph({"arabica_coffee": coffee, "corn": corn}, silver=set())


class _Reached(Exception):
    """Sentinel: raised by the classifier -> the turn FELL THROUGH to the planner (not short-circuited)."""


def _reached(query, call=None):
    raise _Reached(query)


class _SpyStore(ss.InMemoryStore):
    def __init__(self):
        super().__init__()
        self.loads = self.appends = 0

    def load(self, session_id):
        self.loads += 1
        return super().load(session_id)

    def append_turn(self, session_id, turn):
        self.appends += 1
        super().append_turn(session_id, turn)


# (query, expected_class | None) — None => must FALL THROUGH (reach dispatch).
TRIVIAL_ROWS = [
    ("hi", "greeting"),
    ("hello there", "greeting"),
    ("good morning", "greeting"),
    ("hey team", "greeting"),
    ("thanks", "smalltalk"),
    ("thank you so much", "smalltalk"),
    ("cheers", "smalltalk"),
    ("who are you", "meta"),
    ("what can you do", "meta"),
    ("what do you cover", "meta"),
]

FALLTHROUGH_ROWS = [
    ("hi, what were corn exports?", "greeting+real (data cue)"),
    ("hi, also what is wheat doing", "greeting+real (headline)"),
    ("why is coffee bullish", "real reasoning"),
    ("what's the weather like?", "off-topic-but-real"),
    ("who won the game", "off-topic-but-real"),
    ("morning", "terse ambiguous"),
    ("", "empty"),
    ("   ", "whitespace"),
    ("hey what's driving cocoa", "escaping-vocab"),
    ("morning, is corn moving", "escaping-vocab"),
    ("yo cocoa update", "escaping-vocab"),
    ("hi hows sugar looking", "escaping-vocab"),
]


def test_matrix_is_big_enough():
    assert len(TRIVIAL_ROWS) + len(FALLTHROUGH_ROWS) >= 16
    # the four required escaping-vocabulary rows must be present (verifier F3).
    esc = [q for q, why in FALLTHROUGH_ROWS if why == "escaping-vocab"]
    assert len(esc) == 4


@pytest.mark.parametrize("query,klass", TRIVIAL_ROWS)
def test_trivial_rows_short_circuit(query, klass, monkeypatch):
    monkeypatch.setenv("GRAPHRAG_TRIVIAL_ROUTER", "on")
    store = _SpyStore()
    sid = "m1"
    store.put_state(sid, ss.SessionState(contracts=["corn"], asof_latest="2024-01-01", turn_count=2))

    out = orch.respond(query, graph=_graph(), session_id=sid, session_store=store, classify=_reached)
    # short-circuit + correct class
    assert out["intent"] == "social" and out["model"] == "(canned)"
    assert out["trace"]["trivial"]["class"] == klass
    assert out["trace"]["trivial"]["starters"] is True             # FE hint for the live suggester chips
    # register-clean reply (mentor voice; no mood/slug leak)
    assert reg.register_leaks(out["answer"]) == [] and reg._MOOD.findall(out["answer"]) == []
    # session state untouched (greeting returns above session load AND writeback)
    assert store.loads == 0 and store.appends == 0
    assert store._state[sid].contracts == ["corn"] and store._state[sid].turn_count == 2


@pytest.mark.parametrize("query,why", FALLTHROUGH_ROWS)
def test_fallthrough_rows_reach_dispatch(query, why, monkeypatch):
    monkeypatch.setenv("GRAPHRAG_TRIVIAL_ROUTER", "on")
    with pytest.raises(_Reached):                                  # the classifier ran => NOT short-circuited
        orch.respond(query, graph=_graph(), asof="2024-06-01", classify=_reached)


def test_no_real_eval_query_matches_is_trivial():
    # Wave-6 gate #2 guarantee-BY-CONSTRUCTION: the strip eval's real questions must NEVER match is_trivial,
    # so flipping GRAPHRAG_TRIVIAL_ROUTER=on cannot alter the fall-through population (strip rate is unchanged
    # not by luck but because no real query is ever short-circuited). The private eval yamls are gitignored
    # (they ride in the image); skip cleanly if a fresh checkout lacks them.
    cfg = pathlib.Path(__file__).resolve().parents[2] / "configs" / "graphrag"
    checked, hits = 0, []
    for name in ("eval_queries.yaml", "eval_queries_v2.yaml", "eval_queries_v3.yaml",
                 "eval_queries_v34_combined.yaml", "eval_queries_v4_cascade.yaml"):
        p = cfg / name
        if not p.exists():
            continue
        for q in (yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("queries") or []:
            checked += 1
            if it.is_trivial(q.get("question") or "") is not None:
                hits.append((name, q.get("id")))
    convo = cfg / "eval_convos_v1.yaml"
    if convo.exists():
        for c in (yaml.safe_load(convo.read_text(encoding="utf-8")) or {}).get("conversations") or []:
            for t in (c.get("turns") or []):
                checked += 1
                if it.is_trivial(t.get("q") or "") is not None:
                    hits.append((c.get("id"), t.get("q")))
    if checked == 0:
        pytest.skip("private eval sets not present in this checkout")
    assert hits == [], hits
