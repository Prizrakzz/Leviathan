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
    assert "graph:" not in rep                                  # omitted when no version passed
    rep2 = gev.report(rows, model="claude-sonnet-4-6", graph_version="deadbeef1234")
    assert "graph: `deadbeef1234`" in rep2                      # audit stamp in the header when passed


def test_judge_quant_persona_and_grounding_report():
    q = {"id": "q1", "category": "convergence", "contract": "arabica_coffee", "question": "what caused the spike",
         "expect": {"drivers": ["frost"], "needs_evidence": True}}
    out = {"answer": "Frost ...", "contract": "arabica_coffee", "structured": {"sources": [{"ref": 1}]},
           "evidence": [{"source": "GAIN", "date": "2021-07-20", "text": "frost hit"}]}
    scores = {"usefulness": 4, "convexity": 3, "point_in_time": 5, "grounding": 5, "hallucinations": [],
              "gaps": ["no threshold given"], "improvements": ["name the tipping buffer"], "verdict": "sound mechanism"}

    def fake_call(client, system, user, *, model, max_tokens, tool):    # mimic ex.call_opus -> (input, usage)
        sys_text = system if isinstance(system, str) else system[0]["text"]   # judge system = cached block list
        assert tool["name"] == "score_answer" and "QUANTITATIVE RESEARCHER" in sys_text and "frost hit" in user
        assert "OBSERVED NUMBERS" in user and "not a trading system" in sys_text.lower()  # numbers ctx + no-sizing
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


# ── P7-P0.1: strip-RATE rollup + baseline artifact + corpus fingerprint ──────────────────────────────
def _mk_row(rid, strips, claims, checked, answer="Clean prose.", intent="reasoning", intent_ok=True):
    return {"q": {"id": rid, "contract": "corn", "expected_intent": intent},
            "out": {"answer": answer, "intent": intent,
                    "trace": {"citation_verifier": {"enabled": True, "checked": checked, "stripped": strips,
                                                    "claim_count": claims, "corrected": 0,
                                                    "by_rule": {"fabricated_citation": strips} if strips else {}}}},
            "rubric": {"routed_right": True, "intent_ok": intent_ok}}


def test_verifier_panel_reports_strip_rate():
    traces = [r["out"]["trace"]["citation_verifier"] for r in
              [_mk_row("a", 1, 4, 3), _mk_row("b", 0, 6, 2)]]
    panel = "\n".join(gev.verifier_panel(traces))
    assert "strip RATE: 0.1000" in panel                    # 1 strip / 10 sentence-claims
    assert "10 sentence-claims" in panel


def test_baseline_json_schema_and_rates():
    rows = [_mk_row("a", 1, 4, 3), _mk_row("b", 0, 6, 2, intent_ok=False)]
    doc = gev._baseline_json(rows, run_kind="single", model="m", judged=False, eval_set="v3",
                             graph_version="g12", corpus_fp="c34")
    assert doc["kind"] == "baseline_single" and doc["eval_set"] == "v3"
    assert doc["graph_version"] == "g12" and doc["corpus_fingerprint"] == "c34"
    assert doc["total_strips"] == 1 and doc["total_claims"] == 10
    assert doc["strip_rate"] == 0.1 and doc["handle_strip_rate"] == 0.2
    assert doc["intent_ok"] == 1 and doc["intent_n"] == 2
    assert doc["via_orchestrator"] is False                 # self-describing arm: one-hop unless stated
    assert doc["n_answers"] == 2 and doc["per_answer"][0]["id"] == "a"
    assert doc["per_answer"][0]["register_leaks"] == 0      # residual, post-sanitize


def test_baseline_json_convo_rows_compose_ids():
    rows = [{"convo": "wheat_thread", "turn": 2,
             "out": {"answer": "x", "intent": "hybrid",
                     "trace": {"citation_verifier": {"enabled": True, "checked": 1, "stripped": 0,
                                                     "claim_count": 2, "corrected": 0, "by_rule": {}}}},
             "mech": {"intent_ok": True}, "spec": {"q": "?"}}]
    doc = gev._baseline_json(rows, run_kind="convos", model="m", judged=True, eval_set="convos_v1",
                             graph_version=None, corpus_fp="c", via_orchestrator=True)
    assert doc["per_answer"][0]["id"] == "wheat_thread/2" and doc["kind"] == "baseline_convos"
    assert doc["via_orchestrator"] is True


def test_is_slice_key_accepts_slices_rejects_everything_else():
    # P7-P2.0: only retrieval slices belong in the fingerprint — root <node>.jsonl + drivers/*.jsonl.
    for ok in ("corn.jsonl", "arabica_coffee.jsonl", "drivers/el_nino.jsonl"):
        assert gev._is_slice_key(ok), ok
    for bad in ("chunks/ab12cd.jsonl", "_raw/corn.jsonl", "eval/baseline_x.json",
                "eval/report.md", "live_events/2026.jsonl", "drivers/nested/x.jsonl", "corn.parquet"):
        assert not gev._is_slice_key(bad), bad


def test_corpus_fingerprint_s3_hashes_only_slice_keys(monkeypatch):
    # P7-P2.0 regression: the old code listed a non-existent evidence/ subprefix and hashed ZERO slice
    # keys in S3 mode — a slice-content rebuild never flipped the fingerprint. Now: slice keys drive the
    # hash; chunks/_raw/eval keys are inert.
    from leviathan.graphrag import evidence as _ev

    class _Pag:
        def __init__(self, contents):
            self._c = contents
        def paginate(self, Bucket, Prefix):
            yield {"Contents": [{"Key": Prefix + k, "ETag": e} for k, e in self._c]}

    class _Client:
        def __init__(self, contents):
            self._p = _Pag(contents)
        def get_paginator(self, _name):
            return self._p

    import boto3
    base = [("corn.jsonl", "e1"), ("drivers/el_nino.jsonl", "e2"), ("chunks/aa.jsonl", "e3"),
            ("eval/report.md", "e4"), ("_raw/corn.jsonl", "e5")]
    monkeypatch.setattr(_ev, "_evid_s3", lambda: "s3://bkt/graphrag_evidence")
    monkeypatch.setattr(_ev, "_DRIVER_PATH", type("P", (), {"exists": lambda self: False})())
    monkeypatch.setattr(boto3, "client", lambda _svc: _Client(base))
    a = gev.corpus_fingerprint()
    assert a != "unknown"
    # a slice ETag change flips it
    changed = [("corn.jsonl", "e1-NEW")] + base[1:]
    monkeypatch.setattr(boto3, "client", lambda _svc: _Client(changed))
    assert gev.corpus_fingerprint() != a
    # a chunks/-cache add or a new eval report does NOT flip it
    noise = base + [("chunks/bb.jsonl", "e6"), ("eval/baseline_new.json", "e7")]
    monkeypatch.setattr(boto3, "client", lambda _svc: _Client(noise))
    assert gev.corpus_fingerprint() == a


def test_corpus_fingerprint_local_excludes_cache_dirs(tmp_path, monkeypatch):
    # local mode mirrors the S3 filter: chunks/ and _raw/ files never move the fingerprint.
    from leviathan.graphrag import evidence as _ev
    evdir = tmp_path / "evidence"
    (evdir / "chunks").mkdir(parents=True)
    (evdir / "corn.jsonl").write_text('{"t": 1}\n', encoding="utf-8")
    drv = tmp_path / "driver_slices.yaml"
    drv.write_text("drivers: {}\n", encoding="utf-8")
    monkeypatch.delenv("EVIDENCE_S3", raising=False)
    monkeypatch.setattr(_ev, "_EVID_DIR", evdir)
    monkeypatch.setattr(_ev, "_DRIVER_PATH", drv)
    a = gev.corpus_fingerprint()
    (evdir / "chunks" / "aa.jsonl").write_text('{"t": 9}\n', encoding="utf-8")
    assert gev.corpus_fingerprint() == a                    # doc-cache add is inert


def test_corpus_fingerprint_local_deterministic_and_sensitive(tmp_path, monkeypatch):
    # local mode: filenames+sizes + driver_slices.yaml bytes; deterministic; flips on any corpus change.
    evdir = tmp_path / "evidence"
    evdir.mkdir()
    (evdir / "corn.jsonl").write_text('{"t": 1}\n', encoding="utf-8")
    drv = tmp_path / "driver_slices.yaml"
    drv.write_text("drivers: {}\n", encoding="utf-8")
    from leviathan.graphrag import evidence as _ev
    monkeypatch.delenv("EVIDENCE_S3", raising=False)
    monkeypatch.setattr(_ev, "_EVID_DIR", evdir)
    monkeypatch.setattr(_ev, "_DRIVER_PATH", drv)
    a = gev.corpus_fingerprint()
    b = gev.corpus_fingerprint()
    assert a == b and len(a) == 12 and a != "unknown"       # deterministic 12-hex
    (evdir / "corn.jsonl").write_text('{"t": 1}\n{"t": 2}\n', encoding="utf-8")
    assert gev.corpus_fingerprint() != a                    # slice change flips it
    c = gev.corpus_fingerprint()
    drv.write_text("drivers: {new_slice: {category: x, terms: [y]}}\n", encoding="utf-8")
    assert gev.corpus_fingerprint() != c                    # alias/term edit flips it (E1 visibility)


# ── P9-A: mentor-voice gates (banned mood words, scaffold, mechanism_voice judge axis) ───────────────
def test_metrics_reads_banned_mood_words_from_trace():
    r = {"q": {"contract": "x"}, "rubric": {"routed_right": True},
         "out": {"trace": {"banned_mood_words": 2}, "answer": "", "evidence": [], "structured": {}}}
    assert gev._metrics(r)["banned_mood_words"] == 2
    r["out"]["trace"] = {}
    assert gev._metrics(r)["banned_mood_words"] == 0                  # no trace field -> 0, never KeyError


def test_judge_scores_mechanism_voice():
    schema = gev._judge_tool()["input_schema"]
    assert "mechanism_voice" in schema["properties"]
    assert "mechanism_voice" in schema["required"]
    assert "mechanism_voice" in gev._JUDGE_SYS                        # the rubric bullet exists


def test_scaffold_ok_gate():
    ok = {"structured": {"mechanism": "## Mechanism\nx\n## The record\ny\n## What to watch\nz"}}
    assert gev._scaffold_ok(ok) is True
    assert gev._scaffold_ok({"structured": {"mechanism": ""}}) is True          # numbers-only: vacuous pass
    assert gev._scaffold_ok({"structured": {"mechanism": "no headings at all"}}) is False
    out_of_order = {"structured": {"mechanism": "## The record\ny\n## Mechanism\nx"}}
    assert gev._scaffold_ok(out_of_order) is False                    # must OPEN with '## Mechanism'


def test_baseline_json_carries_mood_and_scaffold():
    rows = [_mk_row("a", 1, 4, 3), _mk_row("b", 0, 6, 2)]
    rows[0]["out"]["trace"]["banned_mood_words"] = 2                  # one offender
    rows[0]["out"]["structured"] = {"mechanism": "## The record\nwrong order\n## Mechanism\nx"}
    doc = gev._baseline_json(rows, run_kind="single", model="m", judged=False, eval_set="v3",
                             graph_version="g", corpus_fp="c")
    assert doc["banned_mood_words_total"] == 2
    assert doc["scaffold_violations"] == 1
    assert doc["per_answer"][0]["banned_mood_words"] == 2
    assert doc["per_answer"][0]["mechanism_scaffold_ok"] is False
    assert doc["per_answer"][1]["mechanism_scaffold_ok"] is True
