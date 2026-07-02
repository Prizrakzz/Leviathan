"""graphdev eval harness — mocked (no model calls)."""
from __future__ import annotations

from leviathan.causal import schema as cs
from leviathan.graphrag import coverage as cov
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
    queries = [{"id": "q1", "category": "convergence", "contract": "arabica_coffee", "question": "what caused the spike",
                "expect": {"drivers": ["frost"], "regime": "bullish_supply_squeeze", "needs_evidence": True}}]

    def fake_answer(question, *, graph, model, k, asof=None, near=None):
        return {"answer": "Frost drove the bullish supply squeeze.", "contract": "arabica_coffee",
                "structured": {"sources": [{"ref": 1}]}, "evidence": [{"source": "GAIN", "date": "2021-07-20"}],
                "model": model, "trace": {}}

    rows = gev.run(_graph(), queries, model="claude-sonnet-4-6", answer_fn=fake_answer)
    assert rows[0]["rubric"]["routed_right"]
    rep = gev.report(rows, model="claude-sonnet-4-6")
    assert "GAIN" in rep and "routed correctly: **1/1**" in rep


def test_judge_quant_persona_and_grounding_report():
    q = {"id": "q1", "category": "convergence", "contract": "arabica_coffee", "question": "what caused the spike",
         "expect": {"drivers": ["frost"], "needs_evidence": True}}
    out = {"answer": "Frost ...", "contract": "arabica_coffee", "structured": {"sources": [{"ref": 1}]},
           "evidence": [{"source": "GAIN", "date": "2021-07-20", "text": "frost hit"}]}
    scores = {"usefulness": 4, "convexity": 3, "point_in_time": 5, "grounding": 5, "hallucinations": [],
              "gaps": ["no threshold given"], "improvements": ["name the tipping buffer"], "verdict": "sound mechanism"}

    def fake_call(client, system, user, *, model, max_tokens, tool):    # mimic ex.call_opus -> (input, usage)
        assert tool["name"] == "score_answer" and "QUANTITATIVE RESEARCHER" in system and "frost hit" in user
        assert "OBSERVED NUMBERS" in user and "not a trading system" in system.lower()  # numbers ctx + no-sizing framing
        return scores, None

    j = gev.judge(q, out, client=None, model="claude-opus-4-8", call=fake_call)
    assert j["usefulness"] == 4 and j["gaps"] == ["no threshold given"]
    rep = gev.report([{"q": q, "out": out, "rubric": gev.score(q, out), "judge": j}], model="claude-sonnet-4-6")
    assert "usefulness 4.0" in rep and "convexity 3.0" in rep and "point_in_time 5.0" in rep   # v3 header
    assert "Per-commodity grounding depth" in rep and "no threshold given" in rep              # grounding table + gaps


def test_source_diversity_metrics_and_panel():
    q = {"id": "q1", "category": "cross", "contract": "corn"}
    out = {"contract": "corn", "answer": "T1 and T4 sources disagree on the number.",
           "structured": {"sources": [{"ref": 1, "source": "usda_wasde"}, {"ref": 2, "source": "usda_gain_corn"},
                                      {"ref": 3, "source": "wb_cmo_outlook"}]},           # cited T1->T2->T4
           "evidence": [{"source": "usda_wasde", "date": "2020"}, {"source": "usda_gain_corn", "date": "2020"},
                        {"source": "wb_cmo_outlook", "date": "2020"}]}
    row = {"q": q, "out": out, "rubric": {"routed_right": True}}
    m = gev._metrics(row)
    assert m["ev_sources"] == 3 and m["ev_tiers"] == 3 and m["multi_tier"] is True
    assert m["trust_ordered"] is True                       # T1,T2,T4 ascending = most-trusted first
    assert m["disagreement"] is True                        # 'disagree' flagged in the answer
    panel = "\n".join(gev.source_report([row]))
    assert "multi-tier answers" in panel and "trust-ordered" in panel and "1/1" in panel


def test_judge_scores_source_diversity():
    props = gev._judge_tool()["input_schema"]
    assert "source_diversity" in props["properties"] and "source_diversity" in props["required"]
    assert "source_diversity" in gev._JUDGE_SYS


def test_coverage_report_flags_thin_and_missing_tiers():
    comm = {"corn": {"usda_wasde": [10, {"d1", "d2"}], "wb_cmo_outlook": [3, {"d3"}]},   # T1+T4, 3 docs
            "raw_sugar": {"usda_gain_sugar": [4, {"d4"}]}}                                # single-source, T2 only, no T1
    props, docs, tiers = cov._totals(comm["corn"])
    assert props == 13 and docs == 3 and tiers == [1, 4]
    rep = cov.report(comm, {"drought": {"usda_wasde": [5, {"d1"}]}}, ndocs=100)
    assert "| corn |" in rep and "| raw_sugar |" in rep
    assert "NO T1" in rep and "raw_sugar" in rep.split("NO T1")[1]                        # raw_sugar flagged: no T1
    assert "single-source" in rep and "raw_sugar" in rep.split("single-source")[1]        # and single-source


def test_estimate_cost_includes_judge():
    sonnet = gev.estimate_cost([{}] * 10, model="claude-sonnet-4-6")
    withjudge = gev.estimate_cost([{}] * 10, model="claude-sonnet-4-6", judge_model="claude-opus-4-8")
    assert sonnet["queries"] == 10 and withjudge["total_usd"] > sonnet["answer_usd"]   # judge adds cost


def test_v3_orchestrator_intent_routing_and_leakage(monkeypatch):
    from leviathan.graphrag import orchestrator as orch

    def fake_respond(question, *, graph, asof=None, model=None, numbers_client=None, call=None):
        if "argentina" in question.lower():                       # the leakage trap: the lookup returned nothing
            return {"answer": "That figure was not known at the as-of date.", "intent": "numbers_only",
                    "contract": None, "evidence": [], "citations": [],
                    "number_calls": [{"query": {"table": "silver_psd", "metric": "ending_stocks_mt"}, "rows": []}]}
        return {"answer": "The response turns convex once the buffer is thin [1].", "intent": "hybrid",
                "contract": "corn", "evidence": [{"source": "usda_wasde", "date": "2024", "text": "x"}], "citations": [],
                "number_calls": [{"query": {"table": "silver_psd", "metric": "su_ratio"}, "rows": [{"value": "0.09"}]}]}
    monkeypatch.setattr(orch, "respond", fake_respond)
    qs = [{"id": "trap", "contract": "corn", "expected_intent": "numbers_only", "asof": "2023-07-01",
           "question": "Argentina corn 2023/24 ending stocks?", "expect": {"not_known": True}},
          {"id": "hyb", "contract": "corn", "expected_intent": "hybrid", "asof": "2024-01-15",
           "question": "is the corn response convex given tight stocks?", "expect": {"needs_evidence": True}}]
    rows = gev.run(None, qs, via_orchestrator=True)
    assert rows[0]["rubric"]["intent_ok"] and rows[0]["rubric"]["leakage_ok"]       # trap: right intent + said "not known"
    assert rows[1]["rubric"]["intent_ok"] and rows[1]["out"]["number_calls"]        # hybrid: right intent + a lookup ran
    rr = "\n".join(gev.routing_report(rows))
    assert "**intent routed correctly**: **2/2**" in rr and "leakage-trap handled" in rr and "1/1" in rr
    assert "numbers looked up: silver_psd" in gev.report(rows, model="claude-sonnet-4-6")  # provenance surfaced


def test_planner_panel_reports_l2_structure():
    from leviathan.graphrag import eval as E
    rows = [{"q": {"contract": "arabica_coffee", "id": "q1"},
             "out": {"answer": "x", "evidence": [], "structured": {},
                     "trace": {"planner": "l2",
                               "kept": [["contract", "arabica_coffee", "arabica_coffee"],
                                        ["driver", "arabica_coffee", "frost"],
                                        ["contract", "robusta_coffee", "robusta_coffee"]],
                               "active": [["driver", "arabica_coffee", "frost"]],
                               "fired_regimes": [{"contract": "arabica_coffee", "name": "squeeze"}]}},
             "rubric": {"routed_right": True}}]
    m = E._metrics(rows[0])
    assert m["is_l2"] and m["n_kept"] == 3 and m["n_contracts"] == 2 and m["n_regimes"] == 1 and m["leg_grounded"] == 1.0
    panel = "\n".join(E.planner_report(rows))
    assert "L2 planner" in panel and "cross-commodity" in panel
