"""graphdev eval harness — mocked (no model calls)."""
from __future__ import annotations

from leviathan.causal import schema as cs
from leviathan.graphrag import eval as gev
from leviathan.graphrag import graph as g


def _graph() -> g.CausalGraph:
    coffee = cs.CausalContract(
        contract="arabica_coffee", aliases=["arabica"],
        drivers=[cs.Driver(id="frost", type="hazard", sign="+", mechanism="m")],
        convergence=[cs.ConvergenceSignal(name="bullish_supply_squeeze", direction="+",
                                          requires_any_n_of=1, drivers=["frost"])])
    return g.CausalGraph({"arabica_coffee": coffee}, silver=set())


def test_score_rubric():
    q = {"contract": "arabica_coffee",
         "expect": {"drivers": ["frost", "drought"], "regime": "bullish_supply_squeeze", "needs_evidence": True}}
    out = {"contract": "arabica_coffee", "answer": "Frost drove the bullish supply squeeze.", "evidence": [{"x": 1}]}
    rb = gev.score(q, out)
    assert rb["routed_right"] is True
    assert rb["drivers_hit"] == "1/2" and rb["drivers_missed"] == ["drought"]   # frost found, drought not
    assert rb["regime_named"] is True and rb["evidence_cited"] is True


def test_run_and_report():
    queries = [{"id": "q1", "type": "convergence", "contract": "arabica_coffee", "question": "what caused the spike",
                "expect": {"drivers": ["frost"], "regime": "bullish_supply_squeeze", "needs_evidence": True}}]

    def fake_answer(question, *, graph, model, k, asof=None, near=None):
        return {"answer": "Frost drove the bullish supply squeeze.", "contract": "arabica_coffee",
                "evidence": [{"source": "GAIN", "date": "2021-07-20"}], "model": model, "trace": {}}

    rows = gev.run(_graph(), queries, model="claude-sonnet-4-6", answer_fn=fake_answer)
    assert rows[0]["rubric"]["routed_right"] and rows[0]["rubric"]["regime_named"]
    rep = gev.report(rows, model="claude-sonnet-4-6")
    assert "bullish supply squeeze" in rep and "GAIN" in rep and "routed correctly: **1/1**" in rep


def test_judge_scores_and_report():
    q = {"id": "q1", "type": "convergence", "contract": "arabica_coffee", "question": "what caused the spike",
         "expect": {"drivers": ["frost"], "regime": "bullish_supply_squeeze", "needs_evidence": True}}
    out = {"answer": "Frost ...", "contract": "arabica_coffee", "evidence": [{"source": "GAIN", "date": "2021-07-20"}]}
    scores = {"groundedness": 5, "driver_coverage": 5, "evidence_use": 4, "overall": 5,
              "regime_correct": True, "hallucination": False, "rationale": "well grounded"}

    def fake_call(client, system, user, *, model, max_tokens, tool):    # mimic ex.call_opus -> (input, usage)
        assert tool["name"] == "score_answer" and "frost" in user.lower()
        return scores, None

    j = gev.judge(q, out, client=None, model="claude-opus-4-8", call=fake_call)
    assert j["overall"] == 5 and j["hallucination"] is False
    rep = gev.report([{"q": q, "out": out, "rubric": gev.score(q, out), "judge": j}], model="claude-sonnet-4-6")
    assert "LLM-judge overall: **5.0/5**" in rep and "well grounded" in rep


def test_estimate_cost_scales_with_model():
    sonnet = gev.estimate_cost([{}] * 10, model="claude-sonnet-4-6")
    opus = gev.estimate_cost([{}] * 10, model="claude-opus-4-8")
    assert sonnet["queries"] == 10 and 0 < sonnet["est_usd"] < opus["est_usd"]   # opus pricier
