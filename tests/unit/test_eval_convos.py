"""Multi-turn conversation eval harness — all mocked (no LLM/S3/Dynamo).

Pins: turns run SEQUENTIALLY per conversation while conversations parallelize without state bleed
(distinct session ids), the deterministic mechanics checks (carry/override/trap/vague-resolution),
the judge's conversation-history assembly, and the report's cache/speed panels.
"""
from __future__ import annotations

import threading

from leviathan.graphrag import eval as gev
from leviathan.graphrag import session as ss

CONVOS = [
    {"id": "c1", "turns": [
        {"q": "how does frost hit arabica?", "asof": "2021-08-01", "expected_intent": "reasoning",
         "contracts_any_of": ["arabica_coffee"]},
        {"q": "and the convexity?", "expected_intent": "reasoning", "carries_contracts": True,
         "carries_asof": True, "uses_state": True},
        {"q": "same but as of 2019", "asof": "2019-06-01", "overrides_asof": True},
    ]},
    {"id": "c2", "turns": [
        {"q": "brazil soy production?", "asof": "2024-02-15", "expected_intent": "numbers_only"},
        {"q": "what does the May 2024 WASDE say?", "carries_asof": True, "not_known": True},
    ]},
]


def _fake_respond_factory(log):
    lock = threading.Lock()

    def respond(q, *, graph, asof=None, model=None, numbers_client=None, call=None,
                session_id=None, session_store=None):
        with lock:
            log.append((session_id, q))
        prev_asof = getattr(respond, "asof_by_sid", {}).get(session_id)
        respond.asof_by_sid = getattr(respond, "asof_by_sid", {})
        eff_asof = asof or prev_asof or "2026-07-03"
        respond.asof_by_sid[session_id] = eff_asof
        nk = "was not published at the as-of date" if "May 2024" in q else ""
        return {"answer": f"ans: {q} {nk}".strip(), "intent": ("numbers_only" if "production" in q or "WASDE" in q
                                                               else "reasoning"),
                "contract": "arabica_coffee" if "c1" in (session_id or "") else "soybeans",
                "contracts": ["arabica_coffee"] if "c1" in (session_id or "") else ["soybeans"],
                "asof": eff_asof, "structured": {"tldr": f"tldr for {q[:30]}"}, "evidence": [],
                "number_calls": [], "trace": {}}
    return respond


def test_turns_sequential_per_convo_and_no_state_bleed():
    log = []
    rows = gev.run_conversations(None, CONVOS, workers=2, respond_fn=_fake_respond_factory(log),
                                 store=ss.InMemoryStore())
    assert len(rows) == 5
    # per convo, turn order is strictly the scripted order (state dependency respected)
    for cid in ("c1", "c2"):
        qs = [q for sid, q in log if cid in sid]
        assert qs == [t["q"] for c in CONVOS if c["id"] == cid for t in c["turns"]]
    # distinct session ids per convo -> no cross-convo state bleed
    sids = {sid for sid, _ in log}
    assert len(sids) == 2 and all(("c1" in s) ^ ("c2" in s) for s in sids)


def test_mechanics_carry_override_trap_and_resolution():
    log = []
    rows = gev.run_conversations(None, CONVOS, workers=2, respond_fn=_fake_respond_factory(log),
                                 store=ss.InMemoryStore())
    by = {(r["convo"], r["turn"]): r["mech"] for r in rows}
    assert by[("c1", 0)]["intent_ok"] and by[("c1", 0)]["contract_ok"]
    assert by[("c1", 1)]["carry_contracts_ok"] and by[("c1", 1)]["carry_asof_ok"] and by[("c1", 1)]["resolved_ok"]
    assert by[("c1", 2)]["override_asof_ok"]                     # explicit 2019 as-of won
    assert by[("c2", 1)]["not_known_ok"]                         # the mid-convo PIT trap phrasing detected


def test_convo_history_only_prior_turns_of_same_convo():
    log = []
    rows = gev.run_conversations(None, CONVOS, workers=1, respond_fn=_fake_respond_factory(log),
                                 store=ss.InMemoryStore())
    r_c1t2 = next(r for r in rows if r["convo"] == "c1" and r["turn"] == 2)
    hist = gev._convo_history(rows, r_c1t2)
    assert "how does frost hit arabica?" in hist and "and the convexity?" in hist
    assert "brazil soy" not in hist                              # other convo never leaks into history
    assert "same but as of 2019" not in hist                     # current turn not in its own history


def test_convo_report_renders_mechanics_cache_and_judge():
    log = []
    rows = gev.run_conversations(None, CONVOS, workers=1, respond_fn=_fake_respond_factory(log),
                                 store=ss.InMemoryStore())
    rows[1]["usage"] = {"read": 2000, "write": 0, "input": 500, "output": 100}   # simulate a cache hit
    rows[1]["judge"] = {"usefulness": 4, "convexity": 4, "point_in_time": 5, "grounding": 4,
                        "continuity": 5, "hallucinations": [], "gaps": [], "verdict": "solid follow-up"}
    md = gev.convo_report(rows, model="claude-sonnet-4-6")
    assert "Session mechanics" in md and "carry_asof_ok" in md
    assert "prompt-cache HIT: **1/" in md
    assert "continuity 5" in md.replace("**", "")
    assert "## c1" in md and "## c2" in md


def test_judge_tool_continuity_field_gated():
    assert "continuity" not in gev._judge_tool()["input_schema"]["properties"]
    t = gev._judge_tool(continuity=True)
    assert "continuity" in t["input_schema"]["properties"] and "continuity" in t["input_schema"]["required"]
