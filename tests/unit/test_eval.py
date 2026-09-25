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

    def fake_respond(question, *, graph, asof=None, model=None, numbers_client=None, call=None, query_fn=None):
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


# ── P9-AB: the v4 per-query cascade assertion engine + qfn wiring + judge merge ──────────────────────
def _num_cit(i, metric="exports_mt", period="MY2010", asof="2010-09-01", value="3.9",
             commodity="soft_red_winter_wheat_cbot", release="2010-08-15", country="Russia"):
    return {"id": f"N{i}", "kind": "number", "value": value, "unit": "MMT",
            "locator": {"kind": "number", "table": "silver_psd", "metric": metric, "commodity": commodity,
                        "country": country, "period": period, "asof": asof},
            "payload": {"query": {}, "rows": [{"value": value, "_provenance": {"release_date": release}}]}}


def _out_with(cits, mech="## Mechanism\nExports fell [N1] with the era delta [N2]."):
    return {"answer": mech + "\n\n## Sources\n[N1] x\n[N2] y\n[N3] z",  # the footer re-lists EVERYTHING
            "intent": "reasoning", "structured": {"tldr": "", "mechanism": mech},
            "citations": cits, "evidence": [],
            "trace": {"quantify": [{"node_key": ["wheat", "export_ban"], "metric": "exports_mt",
                                    "era_statuses": {0: ["ok", "ok"]}, "current_status": "ok",
                                    "divergence": False}]}}


def test_cascade_stats_scans_structured_prose_not_the_sources_footer():
    # the primary-gate trap: strips REMOVE the handle from structured prose but the Sources footer keeps
    # re-rendering every ledgered [N] line -- a naive out['answer'] scan would false-pass on fabrications.
    out = _out_with([_num_cit(1), _num_cit(2, metric="exports_mt_delta", value="-2.1")],
                    mech="## Mechanism\nOnly one handle survives in prose [N1].")
    cs = gev._cascade_stats(out)
    assert cs["fired"] and cs["n_rows"] == 2
    assert cs["n_cited"] == 1 and cs["cited_ids"] == ["N1"]         # N2 lives only in the footer


def test_cascade_asserts_matrix_pass():
    q = {"contract": "soft_red_winter_wheat_cbot", "asof": "2026-06-15",
         "expect": {"cascade_fired": True, "min_cascade_cited": 2, "delta_row": True, "fork": False,
                    "pit_clean": True, "ok_era_leg": True}}
    res = gev._cascade_asserts(q, _out_with([_num_cit(1), _num_cit(2, metric="exports_mt_delta")]))
    assert res == {"cascade_fired": True, "min_cascade_cited": True, "delta_row": True, "fork": True,
                   "pit_clean": True, "ok_era_leg": True}


def test_cascade_fork_heading_without_trace_fork_fails():
    # one-directional text rule: a rendered fork heading with NO trace divergence is always a FAIL.
    q = {"contract": "c", "asof": "2026-06-15", "expect": {"fork": False}}
    out = _out_with([_num_cit(1)], mech="## Mechanism\nx [N1]\n## Where the record disagrees\ninvented")
    assert gev._cascade_asserts(q, out) == {"fork": False}


def test_cascade_asserts_absent_for_v3_queries():
    assert gev.score({"contract": "corn"}, {"answer": "x"})["cascade_asserts"] is None


def test_pit_clean_my_label_uses_covering_my_not_window_end():
    asof = "2011-06-01"                                             # wheat MY starts Jun: covering MY = 2011
    ok = _out_with([_num_cit(1, period="MY2011", asof="2011-06-01", release="2011-05-10")])
    assert gev._pit_clean(ok, asof)                                 # MY window past asof is LEGAL for MY labels
    my_leak = _out_with([_num_cit(1, period="MY2012", asof="2011-06-01")])
    assert not gev._pit_clean(my_leak, asof)                        # beyond the covering MY = leak
    leg_leak = _out_with([_num_cit(1, period="MY2011", asof="2011-07-01")])
    assert not gev._pit_clean(leg_leak, asof)                       # leg asof past session asof
    win_leak = _out_with([_num_cit(1, period="2011-01-01..2011-08-01", asof="2011-06-01")])
    assert not gev._pit_clean(win_leak, asof)                       # date-window end rule still applies
    prov_leak = _out_with([_num_cit(1, period="MY2011", asof="2011-06-01", release="2011-06-15")])
    assert not gev._pit_clean(prov_leak, asof)                      # published after the leg's own asof


def test_pit_clean_reads_every_guard_column_stamp_not_release_date_alone():
    """D-OJ-7(b). Only the VINTAGE tables carry `release_date`, so a check that read that key alone was
    a no-op on every data_date card -- including both OUTCOMES_JOIN legs, which stamp `_provenance`
    under the `date` key precisely so the pinned-asof backtest has a day-grained value to read instead
    of the bare `year` a futures row carries. The comment at `cascade._episode_outcome_call` claimed
    this was already happening; it was not (adversarial finding 4)."""
    asof = "2011-06-01"

    def _stamped(**prov):
        cit = _num_cit(1, period="MY2011", asof="2011-06-01")
        cit["payload"]["rows"] = [{"value": "3.9", "_provenance": prov}]
        return _out_with([cit])

    for key in ("release_date", "knowledge_date", "data_date", "week_ending_date", "date"):
        assert not gev._pit_clean(_stamped(**{key: "2011-06-15"}), asof), key   # past the leg's asof
        assert gev._pit_clean(_stamped(**{key: "2011-05-15"}), asof), key
    assert gev._pit_clean(_stamped(year="2011"), asof)          # a bare year is not a day-grain stamp
    # the ORDER is the guard-column order: the more specific publication axis wins where both are there
    assert not gev._pit_clean(_stamped(release_date="2011-06-15", date="2011-05-01"), asof)


def _reroute_pair(**kw):
    base = {"contract": "soft_red_winter_wheat_cbot", "metric": "exports_mt", "countryA": "Russia",
            "dA": -14.573, "countryB": "United States", "dB": 11.216, "window": "MY2009-MY2010",
            "reroute": True}
    base.update(kw)
    return base


def test_cascade_stats_counts_reroute_pairs():
    out = _out_with([])
    assert gev._cascade_stats(out)["reroute_pairs"] == 0             # absent key -> 0, never a KeyError
    out["trace"]["quantify_reroute"] = [_reroute_pair()]
    assert gev._cascade_stats(out)["reroute_pairs"] == 1


def test_cascade_asserts_reroute_matrix_and_fork_guard_widening():
    # RF-5: heading rendered + a FIRED reroute pair + divergence_nodes == 0 -- the WIDENED fork guard must
    # PASS (pre-widening this exact shape scored as a hallucinated fork: rr_r3 3c).
    q = {"contract": "soft_red_winter_wheat_cbot", "asof": "2026-06-15",
         "expect": {"reroute_fired": True, "opposite_country_legs": True, "two_countries_cited": 2,
                    "fork": True}}
    cits = [_num_cit(1, metric="exports_mt_delta", value="-14.573", country="Russia"),
            _num_cit(2, metric="exports_mt_delta", value="11.216", country="United States")]
    mech = "## Mechanism\nx [N1][N2]\n## Where the record disagrees\nRussia fell; the US picked it up"
    out = _out_with(cits, mech=mech)                                 # quantify trace: divergence stays False
    out["trace"]["quantify_reroute"] = [_reroute_pair()]
    res = gev._cascade_asserts(q, out)
    assert res == {"reroute_fired": True, "opposite_country_legs": True, "two_countries_cited": True,
                   "fork": True}


def test_cascade_asserts_reroute_same_sign_negative_cases():
    # a same-sign pair records NOTHING -> reroute_fired False passes; both-negative legs are NOT
    # opposite; a single-country citation set fails the two_countries_cited canary.
    q = {"contract": "soybeans_cbot", "asof": "2026-06-15",
         "expect": {"reroute_fired": False, "opposite_country_legs": False, "two_countries_cited": 2,
                    "fork": False}}
    cits = [_num_cit(1, metric="exports_mt_delta", value="-10.35", country="United States"),
            _num_cit(2, metric="exports_mt_delta", value="-1.249", country="United States")]
    res = gev._cascade_asserts(q, _out_with(cits))
    assert res == {"reroute_fired": True, "opposite_country_legs": True, "two_countries_cited": False,
                   "fork": True}


def test_opposite_country_legs_requires_two_distinct_countries_on_delta_rows():
    q = {"contract": "c", "asof": "2026-06-15", "expect": {"opposite_country_legs": True}}
    cits = [_num_cit(1, metric="exports_mt_delta", value="4.0", country="Russia"),
            _num_cit(2, metric="exports_mt_delta", value="-2.0", country="Russia")]
    assert gev._cascade_asserts(q, _out_with(cits)) == {"opposite_country_legs": False}   # one country
    cits = [_num_cit(1, metric="exports_mt", value="4.0", country="Russia"),
            _num_cit(2, metric="exports_mt", value="-2.0", country="United States")]
    assert gev._cascade_asserts(q, _out_with(cits)) == {"opposite_country_legs": False}   # levels, not deltas


def test_fork_heading_with_reroute_but_want_false_fails():
    # the widened guard is still two-sided: a query pinned fork:false FAILS when a reroute fires.
    q = {"contract": "c", "asof": "2026-06-15", "expect": {"fork": False}}
    out = _out_with([_num_cit(1)])
    out["trace"]["quantify_reroute"] = [_reroute_pair()]
    assert gev._cascade_asserts(q, out) == {"fork": False}


# ── F-W2: no_unbacked_fork -- the PREMISE-CORRECTION alignment guard (deterministic teeth) ────────────
def test_no_unbacked_fork_three_cases():
    # the retrieval-ROBUST half of the `fork` rule as a standalone premise-correction key: a rendered
    # '## Where the record disagrees' heading with NO trace fork is a MODEL-manufactured contradiction (FAIL);
    # heading absent -> PASS; heading WITH a genuine data-true fork (divergence node OR reroute pair) -> PASS.
    q = {"contract": "french_wheat_matif", "asof": "2026-02-15", "expect": {"no_unbacked_fork": True}}
    # (a) heading ABSENT -> True (the confirm-plainly path renders no disagreement heading)
    absent = _out_with([_num_cit(1)], mech="## Mechanism\nThe record confirms it: exports fell [N1].")
    assert gev._cascade_asserts(q, absent) == {"no_unbacked_fork": True}
    # (b) heading present WITH a fired reroute pair -> True (a genuine data-true fork legitimately renders)
    reroute = _out_with([_num_cit(1)],
                        mech="## Mechanism\nx [N1]\n## Where the record disagrees\nRussia fell; EU rose")
    reroute["trace"]["quantify_reroute"] = [_reroute_pair()]
    assert gev._cascade_asserts(q, reroute) == {"no_unbacked_fork": True}
    # (b') heading present WITH a divergence node -> True
    diverg = _out_with([_num_cit(1)],
                       mech="## Mechanism\nx [N1]\n## Where the record disagrees\nthe eras split")
    diverg["trace"]["quantify"][0]["divergence"] = True
    assert gev._cascade_asserts(q, diverg) == {"no_unbacked_fork": True}
    # (c) heading present WITHOUT any trace fork -> False (manufactured contradiction)
    invented = _out_with([_num_cit(1)],
                         mech="## Mechanism\nx [N1]\n## Where the record disagrees\ninvented gotcha")
    assert gev._cascade_asserts(q, invented) == {"no_unbacked_fork": False}


def test_no_unbacked_fork_one_directional_safe_when_not_wanted():
    # one-directional-SAFE: a query that does NOT want the guard is never failed by it, even a bare heading.
    q = {"contract": "c", "asof": "2026-02-15", "expect": {"no_unbacked_fork": False}}
    out = _out_with([_num_cit(1)], mech="## Mechanism\nx [N1]\n## Where the record disagrees\ninvented")
    assert gev._cascade_asserts(q, out) == {"no_unbacked_fork": True}


def test_su_prescaled_levels_only():
    q = {"contract": "corn", "asof": "2026-06-15", "expect": {"su_prescaled": True}}
    cits = [_num_cit(1, metric="su_ratio", value="36.0"),
            _num_cit(2, metric="su_ratio_delta", value="-8.0")]     # signed delta must NOT fail the assert
    assert gev._cascade_asserts(q, _out_with(cits))["su_prescaled"] is True
    bad = [_num_cit(1, metric="su_ratio", value="0.36")]            # unscaled ratio leaked through
    assert gev._cascade_asserts(q, _out_with(bad))["su_prescaled"] is False


# ── W3.6 price-observability expect keys (each exercised judge-free on a synthetic out) ──────────────────
def _price_cit(i, table="silver_pink_sheet", metric="palm_oil_cpo_usd_t", unit="USD/mt", value="920.0"):
    return {"id": f"N{i}", "kind": "number", "value": value, "unit": unit,
            "locator": {"kind": "number", "table": table, "metric": metric, "commodity": "palm_oil",
                        "period": "2026-06", "asof": "2026-07-21"},
            "payload": {"query": {}, "rows": [{"value": value}]}}


def test_price_cited_and_unit_present_filter_price_tables():
    q = {"contract": "malaysian_crude_palm_oil_cme", "asof": "2026-07-21",
         "expect": {"price_cited": True, "unit_present": True}}
    res = gev._cascade_asserts(q, _out_with([_price_cit(1)]))
    assert res == {"price_cited": True, "unit_present": True}
    # a NON-price-table number citation does not satisfy price_cited, and unit_present has nothing to affirm
    res_none = gev._cascade_asserts(q, _out_with([_num_cit(1)]))          # silver_psd, not a price table
    assert res_none == {"price_cited": False, "unit_present": False}
    # a price citation missing its unit fails unit_present but still satisfies price_cited
    res_nounit = gev._cascade_asserts(q, _out_with([_price_cit(1, unit=None)]))
    assert res_nounit == {"price_cited": True, "unit_present": False}


def test_price_decline_guard_matches_trace_scope_slug():
    q = {"contract": "arabica_coffee", "asof": "2026-07-21", "expect": {"price_decline_guard": "robusta"}}
    out = _out_with([])
    out["trace"]["price_decline_guard"] = "robusta"
    assert gev._cascade_asserts(q, out) == {"price_decline_guard": True}
    out["trace"]["price_decline_guard"] = "jse_white_maize"                # wrong scope -> fail
    assert gev._cascade_asserts(q, out) == {"price_decline_guard": False}
    absent = _out_with([])                                                 # guard never fired -> fail (not None)
    assert gev._cascade_asserts(q, absent) == {"price_decline_guard": False}


def test_banned_valuation_and_flow_read_raw_trace_counters():
    q = {"contract": "malaysian_crude_palm_oil_cme", "asof": "2026-07-21",
         "expect": {"banned_valuation": 0, "banned_flow": 0}}
    clean = _out_with([])                                                  # absent counters -> 0 -> pass
    assert gev._cascade_asserts(q, clean) == {"banned_valuation": True, "banned_flow": True}
    dirty = _out_with([])
    dirty["trace"]["banned_valuation_words"] = 2
    dirty["trace"]["banned_flow_words"] = 1
    assert gev._cascade_asserts(q, dirty) == {"banned_valuation": False, "banned_flow": False}


def test_numbers_mismatched_reads_numbers_verifier_tally():
    q = {"contract": "corn", "asof": "2026-07-21", "expect": {"numbers_mismatched": 0}}
    ok = _out_with([])
    ok["trace"]["numbers_verifier"] = {"mismatched": 0}
    assert gev._cascade_asserts(q, ok) == {"numbers_mismatched": True}
    bad = _out_with([])
    bad["trace"]["numbers_verifier"] = {"mismatched": 3}
    assert gev._cascade_asserts(q, bad) == {"numbers_mismatched": False}


def test_baseline_json_carries_cascade_fields_and_arm_flags(monkeypatch):
    monkeypatch.setenv("GRAPHRAG_MENTOR_VOICE", "off")              # C2: arm identity must be in the artifact
    monkeypatch.setenv("GRAPHRAG_CASCADE_QUANT", "off")
    rows = [_mk_row("a", 0, 4, 2)]
    rows[0]["secs"] = 12.5
    rows[0]["rubric"]["cascade_asserts"] = {"cascade_fired": True}
    doc = gev._baseline_json(rows, run_kind="single", model="m", judged=False, eval_set="v4",
                             graph_version="g", corpus_fp="c")
    assert doc["mentor_voice"] == "off" and doc["cascade_quant"] == "off"
    pa = doc["per_answer"][0]
    assert pa["secs"] == 12.5 and pa["cascade_fired"] is False and pa["n_cascade_rows"] == 0
    assert pa["cascade_asserts"] == {"cascade_fired": True}


def test_baseline_json_carries_n_sections_and_answer_v2_arm(monkeypatch):
    monkeypatch.setenv("GRAPHRAG_ANSWER_V2", "on")                  # P9-C arm identity + derived-view count
    rows = [_mk_row("a", 0, 4, 2), _mk_row("b", 0, 6, 2)]
    rows[0]["out"]["structured"] = {"mechanism": "## Mechanism\nx",
                                    "sections": [{"kind": "mechanism", "heading": "Mechanism", "body": "x"}]}
    doc = gev._baseline_json(rows, run_kind="single", model="m", judged=False, eval_set="v4",
                             graph_version="g", corpus_fp="c")
    assert doc["answer_v2"] == "on"
    assert doc["per_answer"][0]["n_sections"] == 1
    assert doc["per_answer"][1]["n_sections"] == 0                  # no structured/sections -> 0, never KeyError
    monkeypatch.delenv("GRAPHRAG_ANSWER_V2")
    doc2 = gev._baseline_json(rows, run_kind="single", model="m", judged=False, eval_set="v4",
                              graph_version="g", corpus_fp="c")
    assert doc2["answer_v2"] == "off"                               # the default self-describes the control arm


def test_judge_numtext_merges_cascade_citations():
    captured = {}

    def fake_call(client, sys_blocks, user, model=None, max_tokens=None, tool=None):
        captured["user"] = user
        return ({"usefulness": 5, "convexity": 5, "point_in_time": 5, "grounding": 5,
                 "source_diversity": 5, "mechanism_voice": 5, "gaps": [], "verdict": "ok"}, None)

    agent_call = {"query": {"table": "silver_psd", "metric": "su_ratio", "period": "2024", "asof": "2024-01-15"},
                  "rows": [{"value": "0.09"}]}
    out = {"answer": "x", "intent": "reasoning", "evidence": [],
           "number_calls": [agent_call],
           "citations": [{"id": "N1", "kind": "number", "value": "0.09", "unit": "",
                          "locator": {"table": "silver_psd", "metric": "su_ratio",
                                      "period": "2024", "asof": "2024-01-15"}},
                         _num_cit(2, metric="exports_mt", period="MY2010", asof="2010-09-01")]}
    gev.judge({"question": "q", "asof": "2024-01-15"}, out, call=fake_call)
    user = captured["user"]
    assert "[N2] silver_psd.exports_mt" in user                     # G3: cascade row surfaced to the judge
    assert user.count("silver_psd.su_ratio") == 1                   # agent row NOT duplicated


def test_qfn_threads_to_respond_when_via_orchestrator(monkeypatch):
    from leviathan.graphrag import orchestrator as orch
    from leviathan.graphrag.numbers import query as Q

    def sentinel(sql):
        return []

    monkeypatch.setattr(Q, "default_query_fn", lambda db=None: sentinel)
    seen = {}

    def fake_respond(question, *, graph, asof=None, model=None, numbers_client=None, call=None, query_fn=None):
        seen["query_fn"] = query_fn
        return {"answer": "x", "intent": "reasoning", "contract": None, "evidence": [], "citations": [],
                "number_calls": [], "structured": None, "trace": {}}

    monkeypatch.setattr(orch, "respond", fake_respond)
    gev.run(None, [{"id": "q", "contract": "corn", "question": "?"}], via_orchestrator=True)
    assert seen["query_fn"] is sentinel                             # the G1 fix: the seam can fire in eval


def test_from_number_period_label_no_double_prefix():
    from leviathan.graphrag import citations as cit
    base = {"rows": [{"value": 3.9}]}
    agent = cit.from_number({**base, "query": {"table": "silver_psd", "metric": "exports_mt",
                                               "commodity": "wheat", "period": "2011",
                                               "asof": "2011-06-01"}}, 1)
    assert "MY2011" in agent.label and "MYMY" not in agent.label    # bare agent year still gets the prefix
    casc = cit.from_number({**base, "query": {"table": "silver_psd", "metric": "exports_mt",
                                              "commodity": "wheat", "period": "MY2011",
                                              "asof": "2011-06-01"}}, 2)
    assert "MY2011" in casc.label and "MYMY" not in casc.label      # pre-labeled cascade period untouched
    win = cit.from_number({**base, "query": {"table": "silver_fred_fx", "metric": "brl_usd",
                                             "commodity": None, "period": "2010-01-01..2010-03-01",
                                             "asof": "2010-03-01"}}, 3)
    assert "2010-01-01..2010-03-01" in win.label and "MY2010-01-01" not in win.label


# -- LANE C: every persisted baseline names the CODE that produced it -----------------------------------
# The artifact already pins the DATA (corpus_fingerprint, graph_version) and the ARM (model, provider,
# mentor_voice/cascade_quant/answer_v2). It pinned nothing about the source, so two baselines straddling a
# prompt change -- the c160bece episodes-omission shape exactly -- were distinguishable only by wall clock.
def _baseline_doc(**over):
    doc = {"kind": "baseline_single", "ts": "2026-08-04T09:00:00Z", "eval_set": "v4", "provider": "anthropic",
           "strip_rate": 0.0, "total_claims": 3, "register_leaks_total": 0, "banned_mood_words_total": 0,
           "scaffold_violations": 0, "intent_ok": 1, "intent_n": 1, "per_answer": []}
    doc.update(over)
    return doc


def _written(tmp_path):
    import json
    files = list(tmp_path.glob("baseline_*.json"))
    assert len(files) == 1, files
    return json.loads(files[0].read_text(encoding="utf-8"))


def test_write_baseline_stamps_the_git_commit(tmp_path, monkeypatch):
    from leviathan.graphrag import evidence as ev
    monkeypatch.setattr(gev, "_OUT", tmp_path)
    monkeypatch.setattr(ev, "_evid_s3", lambda: None)          # local twin only, no S3 in a unit test
    gev._write_baseline(_baseline_doc())
    commit = _written(tmp_path)["git_commit"]
    assert commit == "unknown" or (1 <= len(commit) <= 40 and all(c in "0123456789abcdef" for c in commit))


def test_baseline_git_commit_prefers_the_baked_image_manifest(monkeypatch):
    """In a container there is no .git (docker/ copies src/, not the repo), so image_stamp's baked manifest
    is the ONLY honest source -- and it must win over any git that happens to be on PATH."""
    from leviathan.common import image_stamp
    monkeypatch.setattr(image_stamp, "load_manifest", lambda *a, **k: {"git_commit": "abc123def456"})
    assert gev._baseline_git_commit() == "abc123def456"


def test_baseline_git_commit_falls_back_to_rev_parse_then_to_unknown(monkeypatch):
    import subprocess
    import types
    from leviathan.common import image_stamp
    monkeypatch.setattr(image_stamp, "load_manifest", lambda *a, **k: None)   # no baked manifest
    calls = {}

    def fake_run(cmd, **kw):
        calls["cmd"] = list(cmd)
        return types.SimpleNamespace(returncode=0, stdout="deadbeefcafe1234\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert gev._baseline_git_commit() == "deadbeefcafe1234"
    assert calls["cmd"] == ["git", "rev-parse", "HEAD"]

    def boom(*a, **k):                                          # no git binary / no .git / timeout
        raise OSError("git not found")

    monkeypatch.setattr(subprocess, "run", boom)
    assert gev._baseline_git_commit() == "unknown"              # graceful, never a raise, never a lost run


def test_write_baseline_honours_a_commit_the_caller_already_set(tmp_path, monkeypatch):
    from leviathan.graphrag import evidence as ev
    monkeypatch.setattr(gev, "_OUT", tmp_path)
    monkeypatch.setattr(ev, "_evid_s3", lambda: None)
    monkeypatch.setattr(gev, "_baseline_git_commit", lambda: "should-not-be-used")
    gev._write_baseline(_baseline_doc(git_commit="1234abcd"))
    assert _written(tmp_path)["git_commit"] == "1234abcd"


# --- PRE-ARM D5 (2026-09-16, coherence audit JP-N): THE BOARD'S LIKE-STATE STANZA ------------------
# `_judge_episodes_panel` reads `trace['episodes_injected']`, written SOLELY by the timeline leg, so on
# a board turn it renders "(none ...)" while the block handed the writer dated LIKE-STATE windows --
# and `_JUDGE_SYS` says "A dated window in NONE of the four sources IS a hallucination". The analog
# OUTCOME rows escape (their [N] locator carries `period="{near}..{far}"`); the stanza HEADER, minted
# by `render.sb_analog_header` with NO calls and dated IN WORDS, reaches no panel in any spelling.
# That is W4-N1 re-minted: a feature that RAISES the hallucination count mechanically, on arm A's own
# acceptance metric.

def _board_out(answer="## Mechanism\nx [N1]\n", coverage=None, desk=None):
    """A judged record with (or without) a board. `coverage=None` means NO board at all."""
    tr = {"planner": "l2", "kept": [], "active": []}
    if coverage is not None:
        tr["state_board"] = {"coverage": coverage, "anchors": ["corn_cbot"], "mode": "deep"}
    if desk is not None:
        tr["desk_register"] = desk
    return {"answer": answer, "intent": "reasoning", "evidence": [], "citations": [],
            "number_calls": [], "trace": tr,
            "structured": {"tldr": "", "mechanism": answer, "sources": []}}


_COV = {"loud_k": 3, "loud_rows": 5, "loud_cited": 4, "loud_referenced": 4, "loud_figure_only": 0,
        "events_open": 2, "events_referenced": 1, "events_closed": 1, "events_unplaced": 0,
        "recency_rows": 3, "recency_referenced": 2,
        "watch_rows": 9, "watch_referenced": 5, "watch_cited": 3, "watch_figure_only": 1,
        "spillover_rows": 4, "spillover_referenced": 2, "spillover_same_board_rows": 1,
        "spillover_licensed": True,
        "missed": {"loud": (), "events": (), "recency": (), "watch": (), "spillover": ()}}


def _judged_prompt(out):
    cap = {}

    def fake_call(client, sys_blocks, user, model=None, max_tokens=None, tool=None):
        cap["user"] = user
        return ({"usefulness": 4, "convexity": 4, "point_in_time": 4, "grounding": 4,
                 "source_diversity": 4, "mechanism_voice": 4, "gaps": [], "verdict": "ok"}, None)

    gev.judge({"question": "q", "asof": "2026-09-08"}, out, call=fake_call)
    return cap["user"]


def test_a_board_turn_tells_the_judge_the_like_state_stanza_is_shown_ground_truth():
    """THE CLAUSE IS THE FIX, AND IT NAMES THE CONSTRUCTION FACT. The stanza header carries no [N] and
    names its date in WORDS, so it appears in none of the four panels by construction -- not because
    the answer invented it. The clause says so, and says what is STILL a hallucination."""
    user = _judged_prompt(_board_out(coverage=dict(_COV)))
    assert "LIKE-STATE stanzas are a FIFTH source" in user
    assert "IN WORDS, with no [N] handle" in user
    assert "do NOT list them under hallucinations" in user
    # IT DOES NOT WIDEN THE STANDARD -- both halves of the old rule are restated inside the clause.
    assert "IS still a hallucination" in user
    assert "NARRATED over a window the record shows only as a" in user
    # it sits with the other state rubric and NEVER inside _JUDGE_SYS, the one shared cache-controlled
    # prefix every judged row of every deck in the estate pays for
    assert gev._JUDGE_STATE_ANALOG not in gev._JUDGE_SYS
    assert user.index("STATE BOARD USE ON THIS TURN") < user.index("LIKE-STATE stanzas are a FIFTH")


def test_a_turn_with_no_board_is_byte_identical_and_never_sees_the_like_state_clause():
    """DARK BY THE SAME CONDITION `_JUDGE_STATE_USE` USES. No board -> no `sb_text` -> the whole
    segment is omitted, so every flag-off row of every deck in the estate is unmoved."""
    user = _judged_prompt(_board_out(coverage=None))
    assert "LIKE-STATE stanzas" not in user
    assert "STATE BOARD USE ON THIS TURN" not in user
    assert gev._judge_state_panel(_board_out(coverage=None)) == ""
    # a DECLINED coverage dict renders no COVERAGE panel either -- the instrument stamps its own
    # failure, and a judge asked to score `state_use` off a broken instrument would be scoring a
    # fabricated zero. That is about the COUNTS; the clause is about the stanzas, and rides separately.
    assert gev._judge_state_panel(_board_out(coverage={"declined": "pg_not_live"})) == ""


def test_a_declined_board_still_gets_the_like_state_clause_and_still_scores_no_state_use():
    """ROUND-2 RULING R5. `_judge_state_panel` returns "" for TWO different turns and round 1 keyed the
    clause on that emptiness. A DECLINED board RENDERED -- the writer saw the block, like-state stanzas
    included -- and only the counter broke, so it is exactly the turn whose stanza month-and-year a
    judge would otherwise charge as a hallucination. The clause ships there; the counts and the
    `state_use` score do not, because there is nothing to count."""
    out = _board_out(coverage={"declined": "pg_not_live"})
    user = _judged_prompt(out)
    assert gev._JUDGE_STATE_ANALOG in user
    assert "coverage instrument DECLINED" in user
    # NO counts, NO `state_use` rubric, and no register/watch clause: those are the panel's, not the board's
    assert "STATE BOARD USE ON THIS TURN" not in user
    assert gev._JUDGE_STATE_USE not in user
    assert gev._JUDGE_STATE_WATCH not in user and gev._JUDGE_STATE_REGISTER not in user
    # and the tool schema still omits `state_use`, which is keyed on the panel and not on the board
    assert "state_use" not in str(gev._judge_tool(state_use=False))
    # THE NO-BOARD TURN IS STILL BYTE-IDENTICAL: there is no board to have shown a stanza
    assert gev._JUDGE_STATE_ANALOG not in _judged_prompt(_board_out(coverage=None))
    assert "coverage instrument DECLINED" not in _judged_prompt(_board_out(coverage=None))


def test_the_like_state_clause_ships_beside_the_watch_and_register_clauses_not_instead_of_them():
    """THREE CONSTANTS, THREE CONDITIONS. The watch and register clauses ride their own panel LINES
    (their instruments carry their own flags); this one rides the BOARD, because the stanza is part of
    the board itself and has no flag of its own."""
    cov = dict(_COV)
    cov.update({"watch_candidates": 10, "watch_candidates_used": 4, "watch_candidates_cited": 3,
                "watch_bullets": 5, "watch_writer_added": 1, "watch_admitted_zero": False,
                "register_lingo_hits": 2, "register_lingo_rewritten": 1,
                "register_adjectives_licensed": 3, "register_adjectives_corrected": 1,
                "register_adjectives_struck": 0, "register_adjectives_unbacked": 1})
    user = _judged_prompt(_board_out(coverage=cov))
    for clause in (gev._JUDGE_STATE_USE, gev._JUDGE_STATE_ANALOG,
                   gev._JUDGE_STATE_WATCH, gev._JUDGE_STATE_REGISTER):
        assert clause in user
    # the analog clause is unconditional-on-board; the other two are not
    plain = _judged_prompt(_board_out(coverage=dict(_COV)))
    assert gev._JUDGE_STATE_ANALOG in plain
    assert gev._JUDGE_STATE_WATCH not in plain and gev._JUDGE_STATE_REGISTER not in plain


# --- PRE-ARM E7 (2026-09-16, coherence audit JP-G): THE REPORT SURFACE FOR S7 AND S7b --------------
# `_metrics` carried `state_use` and NOTHING read it; `desk_register` / `count_desk_register` appeared
# ZERO times in eval.py, so the S7b headline -- the SAME PURE LINT reading 51 hits on the no-mandate
# prompt arm (S6B) and 5 on the mandate-lit one (R4), over three real-seat answers of the same length
# -- had no aggregation surface and the arm could not report what it was run to measure.
#
# ROUND-2 RULING R1: THE MANDATE'S NUMBER IS A CROSS-CELL DIFFERENCE AND THE ROWS BELOW FEED IT AS ONE.
# Round 1 pinned a SYNTHETIC census (`{hits_before: 51, hits_after: 5}`) and asserted the panel rendered
# "51 -> 5" -- a rendering no real trace can produce, because the lint runs only under the same flag
# that appends the mandate, so `hits_before` is never a no-mandate count. These rows feed two CELLS'
# ANSWER TEXTS through the pure lint instead, which is the measurement the smoke actually made.

#: A real mandate-DARK body: nine desk-register hits, measured (`register.count_desk_register`).
_LINT_CONTROL_BODY = ("The board is loud on corn: three rows have spent their knowledge date and the "
                      "node fired late. The walk into soybeans is the loudest receipt on the board.")
#: The same content written to the mandate: one hit, measured.
_LINT_TREATMENT_BODY = ("Corn is the largest move on the market, read through 2026-09-05. Two series "
                        "are read through older dates, and one row of the record still lags.")


def _srow(out, judge=None):
    return {"q": {"id": "q1", "contract": "corn_cbot", "question": "x"}, "out": out,
            "rubric": {"routed_right": True, "needs_evidence": False}, "judge": judge or {}}


def test_state_report_is_absent_on_a_deck_with_no_board_and_no_lint_census():
    """ABSENT-WHEN-INAPPLICABLE, like every instrument it aggregates. A panel of zeros would invite a
    reader to compare a dimension that did not exist."""
    assert gev.state_report([]) == []
    assert gev.state_report([_srow(_board_out(coverage=None))]) == []
    # and the report() assembly adds nothing at all -- not even the blank line
    body = gev.report([_srow(_board_out(coverage=None))], model="claude-opus-5")
    assert "## State board use" not in body


def test_state_report_aggregates_the_coverage_read_and_the_desk_register_census():
    """THE THREE THINGS S7b BUILT, in one panel: the per-BULLET watch counter, the licence's unbacked
    count, and the lint's before -> after."""
    cov = dict(_COV)
    cov.update({"watch_candidates": 10, "watch_candidates_used": 4, "watch_candidates_cited": 3,
                "watch_bullets": 5, "watch_writer_added": 1, "watch_admitted_zero": True,
                "register_lingo_hits": 2, "register_lingo_rewritten": 1,
                "register_adjectives_licensed": 3, "register_adjectives_corrected": 1,
                "register_adjectives_struck": 0, "register_adjectives_unbacked": 4})
    desk = {"hits_before": 7, "hits_after": 1, "sentences": 9, "offered": 6, "rewritten": 4,
            "outcome": "rewritten", "usd": 0.0123, "refused": {"edit_outside_table": 2}}
    L = gev.state_report([_srow(_board_out(answer=_LINT_TREATMENT_BODY, coverage=cov, desk=desk),
                                judge={"state_use": 4})])
    body = "\n".join(L)
    assert body.startswith("## State board use")
    assert "state_use avg 4.0/5" in body
    assert "CITED by handle 4/5" in body
    assert "WATCH bullets shipped: 5" in body and "nominations used 4/10" in body
    assert "bullets resting on NO nomination: 1" in body
    assert "valuation adjectives shipped with NO figure beside them: 4" in body
    # THE REWRITE'S DELTA IS ITS OWN LINE, WITH ITS OWN LABEL AND ITS OWN POPULATION (R1)
    assert "the bounded REWRITE: hits before -> after on the treatment turns that fired it: 7 -> 1" in body
    assert "accepted 4" in body and "edit_outside_table" in body
    assert "$0.0123" in body
    # THE TWO POPULATIONS ARE NAMED WHERE THEY DIFFER -- the census is tldr+mechanism, not the page
    assert "`tldr` + `mechanism`" in body
    # NO BAR IS PUT ON ANY NUMBER: the panel says what the counters are, never what they should be
    assert "it does not judge them" in body


def test_the_mandate_line_is_a_cross_cell_read_of_the_pure_lint_over_two_cells_answers():
    """RULING R1. The mandate number is the PURE lint (no model call, no flag) over each cell's OWN
    banked body, split by whether that turn carried the mandate -- never the rewrite's before -> after,
    which is a delta INSIDE the treatment cell and cannot see the control at all."""
    ctl = _srow(_board_out(answer=_LINT_CONTROL_BODY, coverage=dict(_COV)))
    trt = _srow(_board_out(answer=_LINT_TREATMENT_BODY, coverage=dict(_COV),
                           desk={"hits_before": 3, "hits_after": 1, "sentences": 2, "offered": 2,
                                 "rewritten": 2, "outcome": "rewritten", "usd": 0.002}))
    body = "\n".join(gev.state_report([ctl, trt]))
    # 9 hits on the mandate-dark body, 1 on the mandate-lit one -- both measured by the real lint
    assert "shipped lint hits per answer: control **9.0** -> treatment **1.0** (1 / 1 answer(s))" in body
    # the two lines are never the same sentence, and the rewrite's line says whose delta it is
    assert "the bounded REWRITE: hits before -> after on the treatment turns that fired it: 3 -> 1" in body
    # THE SMOKE'S NUMBER IS RE-STATED AS WHAT IT WAS: two prompt arms, one census, no rewrite
    assert "51 with the mandate ABSENT (arm S6B)" in body and "5 with it LIT (arm R4)" in body
    assert "NOT a before -> after inside one cell" in body
    # and it is never rendered as an X -> Y beside a same-census delta
    assert "51 -> 5" not in body


def test_a_single_cell_deck_says_the_difference_is_not_in_this_panel():
    """ABSENT IS NEVER ZERO, applied to a DIFFERENCE. One cell's rows cannot produce a cross-cell
    number, so the panel prints the side it has and says where the other one lives -- it never
    borrows the rewrite's delta to fill the gap."""
    trt = _srow(_board_out(answer=_LINT_TREATMENT_BODY, coverage=dict(_COV),
                           desk={"hits_before": 3, "hits_after": 1, "outcome": "rewritten"}))
    body = "\n".join(gev.state_report([trt]))
    assert "treatment **1.0** over 1 answer(s)" in body
    assert "NO mandate-dark answer in these rows" in body
    assert "THE DIFFERENCE IS NOT IN THIS PANEL" in body
    # a CONTROL-ONLY read carries no desk census on any row and is therefore indistinguishable from a
    # board-only deck: the panel prints NO mandate line at all (absent is never zero; the control side
    # appears only in a merged two-cell read -- round-2 verify minor).
    ctl = _srow(_board_out(answer=_LINT_CONTROL_BODY, coverage=dict(_COV)))
    cbody = "\n".join(gev.state_report([ctl]))
    assert "control **9.0**" not in cbody and "mandate" not in cbody.lower()
    # ...and the merged read prints both sides
    mbody = "\n".join(gev.state_report([ctl, trt]))
    assert "control **9.0** -> treatment **1.0** (1 / 1 answer(s))" in mbody


def test_state_report_never_raises_on_a_non_dict_state_board_and_names_the_shape():
    """R5 MINOR. `report()` runs ONCE per deck after a paid arm, so an AttributeError here loses the
    whole artifact rather than one row. `answer.py:5178` guards the same key with `isinstance`; this
    panel counts the malformed shape and names it rather than swallowing it."""
    bad = _srow(_board_out(answer=_LINT_TREATMENT_BODY, coverage=dict(_COV)))
    bad["out"]["trace"]["state_board"] = "pg_not_live"            # truthy, not a mapping
    L = gev.state_report([bad, _srow(_board_out(coverage=dict(_COV)))])
    body = "\n".join(L)
    assert "`state_board` trace is not a mapping: 1" in body
    assert "board turns: **1/2**" in body                          # the malformed row is not a board


def test_a_census_only_deck_gets_no_board_line_and_no_board_titled_header():
    """R5 MINOR, the other end of 'absent is never zero': a deck carrying ONLY a desk-register census
    has no board, so a `0/N` board line under a board-titled header invents the dimension it denies."""
    out = _board_out(answer=_LINT_TREATMENT_BODY, coverage=None,
                     desk={"hits_before": 4, "hits_after": 2, "outcome": "rewritten"})
    body = "\n".join(gev.state_report([_srow(out)]))
    assert body.startswith("## Desk register (S7b")
    assert "## State board use" not in body
    assert "board turns:" not in body
    assert "treatment **1.0** over 1 answer(s)" in body


def test_state_report_never_sums_the_retired_watch_counter_with_the_shipped_one():
    """`watch_bullets` is the per-BULLET read (S7b round 4); `watch_referenced` is the RETIRED
    per-SENTENCE one that scored 5 of 37 on pages a hand read scored 13 of 13. A turn has exactly one
    of them, and the panel names which counter produced its number."""
    off = gev.state_report([_srow(_board_out(coverage=dict(_COV)))])          # flag off: retired read
    assert any("RETIRED per-SENTENCE read" in ln for ln in off)
    assert not any("WATCH bullets shipped" in ln for ln in off)
    on_cov = dict(_COV)
    on_cov.update({"watch_candidates": 8, "watch_candidates_used": 3, "watch_bullets": 3,
                   "watch_writer_added": 0, "watch_admitted_zero": False})
    on = gev.state_report([_srow(_board_out(coverage=on_cov))])
    assert any("WATCH bullets shipped" in ln for ln in on)
    assert not any("RETIRED per-SENTENCE read" in ln for ln in on)


def test_state_report_counts_a_declined_board_and_never_scores_it():
    """A declined coverage dict is a board that FAILED, not a board that scored 0. It is counted and
    named, and it contributes to no numerator and no denominator."""
    L = gev.state_report([_srow(_board_out(coverage={"declined": "pg_not_live"})),
                          _srow(_board_out(coverage=dict(_COV)))])
    body = "\n".join(L)
    assert "boards that DECLINED: 1" in body and "pg_not_live" in body
    assert "board turns: **2/2**" in body and "1 rendered rows" in body
    assert "CITED by handle 4/5" in body                     # the declined row is not in the ratio


def test_report_renders_the_state_panel_on_a_board_deck():
    """The panel reaches the report a human reads, and only when there is something in it."""
    body = gev.report([_srow(_board_out(coverage=dict(_COV)), judge={"state_use": 5})],
                      model="claude-opus-5", judge_requested=True)
    assert "## State board use" in body
    assert "state_use avg 5.0/5" in body


def test_register_report_no_longer_claims_to_be_the_whole_complement():
    """It reads the pre-S7b leak list and nothing else; `desk_register` is a different population with
    a different remedy on a different trace key. The docstring says so now, and names its partner."""
    doc = gev.register_report.__doc__ or ""
    assert "the deterministic complement to the judge\'s register read" not in doc
    assert "state_report" in doc and "desk_register" in doc


def test_state_report_prints_no_desk_register_lines_on_a_board_only_deck():
    """A deck whose rows carry a board and no desk census has no register dimension: no mandate line, no
    rewrite line, no smoke sentence (round-2 verify minor -- absent is never zero)."""
    cov = dict(_COV)
    cov.update({"watch_candidates": 10, "watch_candidates_used": 4, "watch_candidates_cited": 3,
                "watch_bullets": 5, "watch_writer_added": 1, "watch_admitted_zero": True})
    L = gev.state_report([_srow(_board_out(answer=_LINT_TREATMENT_BODY, coverage=cov), judge={"state_use": 4})])
    body = "\n".join(L)
    assert body.startswith("## State board use")
    assert "shipped lint hits" not in body and "mandate" not in body.lower() and "51" not in body


# ── LANE tracekeys ROUND 2 (2026-09-23): THE CHAIN PANEL'S TWO FIGURES, AGAINST THEIR PRODUCERS ────
# Round 1 shipped this panel with a figure that counted `trace["planner"] == "onehop"` -- a value with
# NO producer anywhere in the estate. `answer.py` carries exactly ONE `"planner"` literal and it is the
# CONSTANT `"planner": "l2"` inside `_answer_l2`, so the count could never leave 0 on any deck: the
# review's own 10-row deck, nine of whose rows were the one-hop body's trace taken from the shipped
# stamp, printed "0 of 10". A printed figure whose population no row can join is a backing failure,
# and these two pins are what make it one the build cannot re-ship.
_CHAIN_CENSUS = {"outcome": "ok", "sentences": 3, "corrected": 2, "chain_hops_unfigured": 1,
                 "chain_hops_skipped": 4, "chain_unranked_narrated": 1, "chain_hops_ambiguous": 2,
                 "chain_fence_closed": 3}
#: An L2 row: the planner constant the ONE producer writes, plus a census, so the block renders.
_L2_CHAIN_ROW = {"out": {"trace": {"planner": "l2", "chain_lints": dict(_CHAIN_CENSUS)}}}


def _onehop_row(monkeypatch, lit: bool) -> dict:
    """The one-hop body's own trace, from the SHIPPED producer at the flag state asked for.

    `answer.answer`'s single return splices `_state_board_lane_stamp("lane_off:onehop", mode)` and
    `"regimes": regimes` into ONE dict literal, so a real one-hop row carries both -- and with
    GRAPHRAG_STATE_BOARD dark the stamp is `{}` and `regimes` is all there is."""
    from leviathan.graphrag import answer as gan
    if lit:
        monkeypatch.setenv("GRAPHRAG_STATE_BOARD", "on")
    else:
        monkeypatch.delenv("GRAPHRAG_STATE_BOARD", raising=False)
    return {"out": {"trace": {**gan._state_board_lane_stamp("lane_off:onehop", "deep"),
                              "regimes": []}}}


def _onehop_line(rows: list[dict]) -> str:
    L = [x for x in gev.state_report(rows) if "one-hop rollback in this deck" in x]
    assert len(L) == 1, L
    return L[0]


def test_the_one_hop_figure_is_counted_off_keys_the_one_hop_body_actually_writes(monkeypatch):
    """ROUND-2 RULING B5. THE FIGURE READS THE DISCRIMINATOR THAT EXISTS, IN BOTH FLAG STATES.

    THE DEFECT, REPRODUCED ON THE SHIPPED PRODUCER: `trace["planner"]` has one producer in
    `answer.py` and it is the constant `"l2"`, so `== "onehop"` was structurally dead and this deck's
    ten rows printed "0 of 10" while nine of them were one-hop rows taken from the stamp itself.

    THE OPPOSITE ERROR IS PINNED IN THE SAME TEST, because the obvious repair is worse than the
    defect: `trace["planner"] != "l2"` counts `answer()`'s empty-route `anchor_none` return, which is
    taken BEFORE the planner branch and therefore by an L2 turn just as readily -- 2 of 4 on a deck
    whose truth is 1 of 4. What the panel counts instead are the two keys the one-hop body's OWN
    single return writes: the `lane_off:onehop` lane stamp (exact, one producer, but present only
    while GRAPHRAG_STATE_BOARD is lit) and its `regimes` trace key (which `_answer_l2` never writes --
    it writes `fired_regimes` -- and which survives a dark board). BOTH flag states are exercised
    because either key alone leaves a real deck unreadable."""
    import pathlib as _pl

    from leviathan.graphrag import answer as gan
    for lit in (True, False):
        rows = [_L2_CHAIN_ROW] + [_onehop_row(monkeypatch, lit) for _ in range(9)]
        line = _onehop_line(rows)
        assert "one-hop rollback in this deck: 9 of 10" in line, (lit, line)
        # ...and the sentence that framed the dead figure is gone with it
        assert "only `trace['planner']` separates" not in line
    # THE OPPOSITE ERROR: an `anchor_none` row is NOT a one-hop row, on either planner or either flag.
    for lit in (True, False):
        if lit:
            monkeypatch.setenv("GRAPHRAG_STATE_BOARD", "on")
        else:
            monkeypatch.delenv("GRAPHRAG_STATE_BOARD", raising=False)
        anchor = {"out": {"trace": {"routed": [],
                                    **gan._state_board_lane_stamp("anchor_none", "deep")}}}
        rows = [_L2_CHAIN_ROW, _L2_CHAIN_ROW, anchor, _onehop_row(monkeypatch, lit)]
        line = _onehop_line(rows)
        assert "one-hop rollback in this deck: 1 of 4" in line, (lit, line)
        assert "in this deck: 2 of 4" not in line                 # what `!= "l2"` would have printed
    # AND THE BACKING IS THE PRODUCER CENSUS, not this deck's own fixtures: nothing in `answer.py`
    # writes "onehop" into that key, so a row that carried one would be a row no seat can mint.
    _asrc = _pl.Path(gan.__file__).read_text(encoding="utf-8")
    assert _asrc.count('"planner"') == 1 and '"planner": "l2"' in _asrc
    assert '"planner": "onehop"' not in _asrc
    fabricated = [_L2_CHAIN_ROW, {"out": {"trace": {"planner": "onehop"}}}]
    assert "one-hop rollback in this deck: 0 of 2" in _onehop_line(fabricated)
    # A MALFORMED BOARD STILL CANNOT RAISE HERE -- `report()` runs once per deck after a paid arm.
    bent = [_L2_CHAIN_ROW, {"out": {"trace": {"state_board": {"legs": "not a dict"}}}},
            {"out": {"trace": {"state_board": "pg_not_live"}}}]
    assert "one-hop rollback in this deck: 0 of 3" in _onehop_line(bent)


def test_the_chain_counter_gloss_is_built_from_the_roster_and_cannot_outlive_a_rename(monkeypatch):
    """ROUND-2 RULING B6. THE GLOSS IS THE ROSTER'S TOO, AND THE DECK SPELLS WHAT THE REPORT MAY NOT.

    Round 1's line said the five counters were "read off the roster and never spelled here" and then
    spelled three of them in its next clause -- measured, 3 of 5 as literals in `eval.py`. The FIGURES
    were roster-read; the GLOSS was not, so a rename printed the NEW name in the figure and the OLD
    name in the gloss on one line, which is precisely the failure the comment above it calls
    impossible. Reproduced here by monkeypatching the shipped tuple.

    THE ALIGNMENT IS WHAT A DECK MUST HOLD. The gloss text rides a tuple zipped against
    `CHAIN_LINT_COUNTERS`, so a REORDERED roster would attach each sentence to the wrong counter and
    no source rule in `eval.py` could see it. This test pins each gloss to its counter BY NAME -- the
    one place the names may be spelled -- so a reorder goes red here."""
    from leviathan.graphrag.state import lint as LINT
    line = [x for x in gev.state_report([{"out": {"trace": {"chain_lints": dict(_CHAIN_CENSUS)}}}])
            if ("`%s`" % LINT.CHAIN_LINT_COUNTERS[0]) in x]
    assert len(line) == 1
    body = line[0]
    for name, tot in (("chain_hops_unfigured", 1), ("chain_hops_skipped", 4),
                      ("chain_unranked_narrated", 1), ("chain_hops_ambiguous", 2),
                      ("chain_fence_closed", 3)):
        assert ("`%s` %d" % (name, tot)) in body, (name, body)
    # EACH GLOSS AGAINST THE COUNTER IT BELONGS TO -- the reorder tripwire
    assert "`chain_hops_unfigured` is NOT a defect" in body
    assert "`chain_hops_ambiguous` counts figures REFUSED" in body
    assert "`chain_fence_closed` counts corrections WITHHELD" in body
    # NO ORPHAN NAME: every counter-shaped token on the line is an element of the shipped roster
    import re as _re
    toks = set(_re.findall(r"`(chain_[a-z_]+)`", body))
    assert toks and toks <= set(LINT.CHAIN_LINT_COUNTERS), toks
    # ...and the claim the line used to make about itself, which was false, is not made any more
    assert "never spelled here" not in body

    # THE RENAME, ON THE SHIPPED TUPLE: the gloss follows the name and the retired one is GONE.
    monkeypatch.setattr(LINT, "CHAIN_LINT_COUNTERS",
                        ("chain_hops_renamed",) + tuple(LINT.CHAIN_LINT_COUNTERS[1:]))
    renamed = [x for x in gev.state_report(
        [{"out": {"trace": {"chain_lints": {**_CHAIN_CENSUS, "chain_hops_renamed": 7}}}}])
        if "chain_hops_renamed" in x]
    assert len(renamed) == 1
    assert "`chain_hops_renamed` 7" in renamed[0]                 # the FIGURE moved with the roster
    assert "`chain_hops_renamed` is NOT a defect" in renamed[0]   # ...and so did its GLOSS
    assert "chain_hops_unfigured" not in renamed[0]               # the retired name is not printed
    # A SIXTH COUNTER ARRIVES UNGLOSSED RATHER THAN MIS-GLOSSED, and its FIGURE still prints.
    monkeypatch.setattr(LINT, "CHAIN_LINT_COUNTERS",
                        tuple(LINT.CHAIN_LINT_COUNTERS) + ("chain_sixth_counter",))
    sixth = [x for x in gev.state_report(
        [{"out": {"trace": {"chain_lints": {**_CHAIN_CENSUS, "chain_hops_renamed": 7,
                                            "chain_sixth_counter": 5}}}}])
        if "chain_sixth_counter" in x]
    assert len(sixth) == 1 and "`chain_sixth_counter` 5" in sixth[0]
    assert "`chain_sixth_counter` is NOT" not in sixth[0]
    # the COUNT is read, never spelled -- 09-25 FIX ROUND 3 (lane RT): the shipped roster holds six since lane A's
    # `chain_hops_off_question` was rostered, so the "sixth" appended here is the seventh; the pin reads the length
    assert ("the %d `state.lint.CHAIN_LINT_COUNTERS`" % len(LINT.CHAIN_LINT_COUNTERS)) in sixth[0]


# ── LANE F (2026-09-17): THE COST CENSUS AND THE SPEND PANEL ──────────────────────────────────────
# THE DEFECT, MEASURED (COST_LATENCY.md sec 0, the 2026-09-16 in-VPC pre-arm smoke): `turn_cost_usd`
# is the estate's ONE money column and it prices ONE of six Anthropic seats -- the WRITER. Five smoke
# turns priced $2.5643 in it against a PROVEN floor of $3.9251 and a modelled $5.6656, so every budget
# built by scaling it under-counts a hybrid turn by 35-55%. The seats it never saw are the NUMBERS
# AGENT (claude-sonnet-5, $8.84 of a $35 arm, the long pole at 46-73% of wall clock), the DISPATCH
# PLANNER (stamped nowhere at all) and the DESK REWRITE (already priced, reaching the report only).
_SU = {"model": "claude-opus-5", "in": 25486, "out": 3333, "cache_read": 0, "cache_write": 50897}


def test_turn_cost_total_equals_turn_cost_usd_when_only_the_writer_is_stamped():
    """THE BYTE-IDENTITY PIN FOR THE MONEY COLUMN. `_turn_cost_usd` is UNTOUCHED -- name, arithmetic
    and scope -- because it sits in banked baselines across the estate and redefining it would silently
    re-scale every prior arm's $/turn. On a writer-only row (every flag-off row, every banked replay,
    every non-orchestrator row) the new column agrees with it EXACTLY: same seat, same function. The
    banked value below is the max smoke turn's own: 25,486*5 + 50,897*5*1.25 + 3,333*25 = $0.52886125."""
    total, seats = gev._turn_cost_total_usd({"synth_usage": _SU})
    assert seats == {"writer": gev._turn_cost_usd(_SU)}
    assert abs(total - gev._turn_cost_usd(_SU)) < 1e-12
    assert abs(total - 0.52886125) < 1e-9


def test_the_census_never_fabricates_a_zero_and_omits_an_unpriced_seat():
    """THE CostUsd 0-SEMANTICS IDIOM, twice. A turn with NOTHING stamped returns (None, None) -- not
    ($0.00, {}) -- because "nobody measured" and "it was free" are different facts. And a seat whose
    model is absent from `providers.SERVING_PRICES` is OMITTED FROM THE MAP rather than counted as
    free, so a total can never silently under-report by pricing an unknown model at zero. The row
    count in the map IS the disclosure of how many seats the number covers."""
    assert gev._turn_cost_total_usd({}) == (None, None)
    assert gev._turn_cost_total_usd(None) == (None, None)
    t, s = gev._turn_cost_total_usd({"synth_usage": _SU,
                                     "plan_usage": {"model": "some-model-nobody-priced",
                                                    "in": 9999, "out": 9999}})
    assert set(s) == {"writer"} and "dispatch_planner" not in s
    assert abs(t - gev._turn_cost_usd(_SU)) < 1e-12


def test_the_numbers_seat_is_a_list_of_rounds_and_is_summed_as_one_seat():
    """The agent's bill is dominated by ONE ~99 k-token cached prefix re-read once per round, so the
    artifact keeps a PER-ROUND shape (a cold write is `cache_read == 0` on round 1, $0.3720 a time,
    and it is the cheapest lever measured on arm A). The MONEY, though, is one seat's money."""
    rounds = [{"model": "claude-sonnet-5", "in": 21, "out": 1383, "cache_read": 86668, "cache_write": 0},
              {"model": "claude-sonnet-5", "in": 105, "out": 4312, "cache_read": 424002, "cache_write": 0}]
    _t, s = gev._turn_cost_total_usd({"synth_usage": _SU, "numbers_usage": rounds})
    assert set(s) == {"writer", "numbers"}
    assert abs(s["numbers"] - sum(gev._seat_cost_usd(r) for r in rounds)) < 1e-12
    # an EMPTY list is not a seat: the agent ran no round, which is not "the numbers cost $0"
    _t2, s2 = gev._turn_cost_total_usd({"synth_usage": _SU, "numbers_usage": []})
    assert set(s2) == {"writer"}


def test_the_desk_rewrite_is_taken_verbatim_and_never_re_priced_from_tokens_it_lacks():
    """`answer._desk_register_lint` already prices itself with THIS SAME `providers.serving_cost_usd`
    and the census carries no tokens for it, so re-deriving here would be a second spelling of one
    bill. A non-numeric `usd` (or the `over_ceiling` bool beside it) is not a price.

    RE-BANKED, ROUND-2 REVIEW M2, AND THE CAUSE IS THE POINT: every trace here now carries a
    CENSUS-ONLY seat beside the desk register, because `desk_register` is stamped by a TREATMENT flag
    (`GRAPHRAG_DESK_REGISTER`) and a treatment flag must not change a flag-off artifact. Without a
    census seat on the row the desk rewrite is no longer counted at all -- that is the fix, and
    `test_a_treatment_flags_seat_alone_grows_no_column_and_renders_no_panel` below is its own pin. What
    this test still owns is the VERBATIM rule: when the census DID run, the already-priced dollar is
    taken as it stands and never re-derived."""
    _pu = {"model": "claude-sonnet-4-6", "in": 80, "out": 600, "cache_read": 8800, "cache_write": 0}
    _t, s = gev._turn_cost_total_usd({"synth_usage": _SU, "plan_usage": _pu,
                                      "desk_register": {"usd": 0.0098, "over_ceiling": False}})
    assert s["desk_rewrite"] == 0.0098
    for bad in ({"usd": None}, {"usd": "0.01"}, {"usd": True}, {"outcome": "no_caller"}):
        _t2, s2 = gev._turn_cost_total_usd({"synth_usage": _SU, "plan_usage": _pu,
                                            "desk_register": bad})
        assert "desk_rewrite" not in s2, bad


def test_the_two_new_columns_are_absent_when_the_writer_is_the_only_stamped_seat():
    """THE FLAG-OFF BYTE PIN ON THE RECORD. On a writer-only row the two columns would say exactly what
    `turn_cost_usd` already says, so emitting them would move every flag-off artifact off HEAD's byte
    for no information. Their PRESENCE is itself the fact that a second seat was stamped."""
    off = gev._per_answer_record({"q": {"id": "q1"}, "out": {"trace": {"synth_usage": _SU}}}, "single")
    assert "turn_cost_total_usd" not in off and "turn_cost_by_seat_usd" not in off
    assert abs(off["turn_cost_usd"] - 0.52886125) < 1e-9
    on = gev._per_answer_record(
        {"q": {"id": "q1"},
         "out": {"trace": {"synth_usage": _SU,
                           "plan_usage": {"model": "claude-sonnet-4-6", "in": 80, "out": 600,
                                          "cache_read": 8800, "cache_write": 0}}}}, "single")
    assert on["turn_cost_usd"] == off["turn_cost_usd"]             # UNTOUCHED, both rows
    assert set(on["turn_cost_by_seat_usd"]) == {"writer", "dispatch_planner"}
    assert on["turn_cost_total_usd"] > on["turn_cost_usd"]
    # the judge's usage is a MEASUREMENT cost, rides its own column, never folded into turn_cost_usd
    jrow = gev._per_answer_record(
        {"q": {"id": "q1"}, "out": {"trace": {"synth_usage": _SU}},
         "judge": {"usefulness": 4, "_usage": {"model": "claude-opus-4-8", "in": 15342, "out": 700,
                                               "cache_read": 0, "cache_write": 6269}}}, "single")
    assert jrow["judge_usage"]["model"] == "claude-opus-4-8"
    assert jrow["judge"] == {"usefulness": 4}                # the AXIS whitelist: _usage cannot leak
    assert jrow["turn_cost_usd"] == off["turn_cost_usd"]
    assert "judge" in jrow["turn_cost_by_seat_usd"]


def _spend_row(trace, tier="deep"):
    return {"q": {"id": "q1", "contract": "arabica_coffee", "question": "x"},
            "out": {"answer": "x", "intent": "reasoning", "evidence": [], "number_calls": [],
                    "structured": {"tldr": "", "mechanism": "x", "sources": []},
                    "trace": trace, "intent_decision": {"mode": {"honored": tier}}},
            "rubric": {"routed_right": True, "needs_evidence": False}}


def test_the_spend_panel_is_absent_when_the_census_is_dark_and_names_every_seat_when_lit():
    """ABSENT-WHEN-DARK, so every banked report of every flag-off deck is byte-identical: a one-seat
    total wearing the word "spend" is exactly the misreading this panel exists to end."""
    assert gev.spend_report([]) == []
    assert gev.spend_report([_spend_row({"synth_usage": _SU})]) == []
    body = gev.report([_spend_row({"synth_usage": _SU})], model="claude-opus-5")
    assert "## Spend" not in body
    lit = [_spend_row({"synth_usage": _SU,
                       "numbers_usage": [{"model": "claude-sonnet-5", "in": 100, "out": 2000,
                                          "cache_read": 0, "cache_write": 99207},
                                         {"model": "claude-sonnet-5", "in": 100, "out": 2000,
                                          "cache_read": 99207, "cache_write": 0}],
                       "desk_register": {"usd": 0.0098}}, tier="max")]
    L = gev.spend_report(lit)
    t = "\n".join(L)
    assert t.startswith("## Spend")
    for seat in ("writer", "numbers", "desk_rewrite"):
        assert ("- %s:" % seat) in t, seat
    assert "tier `max`" in t
    assert "COLD prefix writes (cache_read == 0 on a round that wrote): 1" in t
    assert "Cohere rerank" in t                                    # what the number does NOT cover
    assert "## Spend" in gev.report(lit, model="claude-opus-5")


def test_the_judge_binds_its_own_usage_only_under_the_census_flag(monkeypatch):
    """`eval.py`'s judge line was `scores, _ = call(...)` -- `ex.call_opus` returns `(tool_input,
    usage)` and the second element was discarded on EVERY judged row the estate has ever run, so the
    judge's own ~$2.90 of a 34-turn arm was recorded nowhere. THE JUDGED PROMPT DOES NOT MOVE A BYTE:
    the same system blocks, user block, tool and max_tokens; only the discarded value is kept."""
    import types

    seen = {}

    def fake_call(client, sys_blocks, user, model=None, max_tokens=None, tool=None):
        seen["user"] = user
        seen["max_tokens"] = max_tokens
        seen["sys_blocks"] = sys_blocks                            # round-2 review m6: all four, not two
        seen["tool"] = tool
        seen["model"] = model
        return ({"usefulness": 4, "convexity": 3, "point_in_time": 4, "grounding": 4,
                 "source_diversity": 3, "mechanism_voice": 4, "hallucinations": []},
                types.SimpleNamespace(input_tokens=15342, output_tokens=700,
                                      cache_read=0, cache_creation=6269))

    out = {"answer": "x", "intent": "reasoning", "evidence": [], "number_calls": [],
           "structured": {"tldr": "", "mechanism": "x", "sources": []}, "trace": {}}
    q = {"question": "why", "asof": "2026-09-16", "contract": "arabica_coffee"}
    monkeypatch.delenv("GRAPHRAG_COST_CENSUS", raising=False)
    dark = gev.judge(q, out, graph=_graph(), client=None, call=fake_call)
    dark_call = (seen["user"], seen["sys_blocks"], seen["tool"], seen["max_tokens"], seen["model"])
    assert "_usage" not in dark                                    # HEAD's scores dict exactly
    monkeypatch.setenv("GRAPHRAG_COST_CENSUS", "on")
    lit = gev.judge(q, out, graph=_graph(), client=None, call=fake_call)
    # ROUND-2 REVIEW m6: the CLAIM was "same sys_blocks, same user, same tool, same max_tokens"; the
    # pin captured `user` and `max_tokens` and asserted only `user`. All five arguments of the call are
    # asserted now, so the claim and the pin are the same statement.
    assert (seen["user"], seen["sys_blocks"], seen["tool"], seen["max_tokens"], seen["model"]) == \
           dark_call                                               # THE PROMPT DID NOT MOVE
    assert lit["_usage"] == {"model": "claude-opus-4-8", "in": 15342, "out": 700,
                             "cache_read": 0, "cache_write": 6269}
    assert gev._seat_cost_usd(lit["_usage"]) > 0


def test_a_treatment_flags_seat_alone_grows_no_column_and_renders_no_panel():
    """ROUND-2 REVIEW M2 -- THE CENSUS's KILL-SWITCH GATES THE CENSUS's OUTPUT. PROVEN BOTH WAYS.

    `desk_register` is stamped under `GRAPHRAG_DESK_REGISTER`, an `arm_flags` TREATMENT flag with NO
    relation to this census. BEFORE THE FIX, a row carrying only `synth_usage` + `desk_register` --
    reachable on ANY S7b deck with `GRAPHRAG_COST_CENSUS` UNSET ENTIRELY -- grew both new columns and
    rendered an eight-line Spend panel. Measured then: `turn_cost_total_usd` 0.53866125, seats
    `{'writer': 0.5289, 'desk_rewrite': 0.0098}`, 8 panel lines, census flag off.

    A TREATMENT FLAG MUST NOT CHANGE A FLAG-OFF ARTIFACT, and turning the census off must put the
    artifact back on HEAD's shape or it is not a rollback. THE GATE IS A PROPERTY OF THE ROW, never an
    environment read at report time: a `--from-baseline` replay of a run that DID stamp the census must
    keep every column that run produced, and the second half of this test is that case."""
    tr = {"synth_usage": _SU, "desk_register": {"usd": 0.0098, "over_ceiling": False}}
    total, seats = gev._turn_cost_total_usd(tr)
    assert seats == {"writer": gev._turn_cost_usd(_SU)}            # the TREATMENT seat is not counted
    assert abs(total - 0.52886125) < 1e-9                          # ...so the total is the writer's
    row = gev._per_answer_record({"q": {"id": "q1"}, "out": {"trace": tr}}, "single")
    assert "turn_cost_total_usd" not in row and "turn_cost_by_seat_usd" not in row
    assert row["desk_register"] == {"usd": 0.0098, "over_ceiling": False}   # the KEY still lifts
    assert row["turn_cost_usd"] == gev._turn_cost_usd(_SU)         # ...and HEAD's money column is HEAD's
    assert gev.spend_report([_spend_row(tr)]) == []
    assert "## Spend" not in gev.report([_spend_row(tr)], model="claude-opus-5")
    # ...AND THE MOMENT A CENSUS-ONLY SEAT RIDES BESIDE IT, the desk rewrite is counted again: the row
    # itself is the receipt that the census ran, so a banked replay loses nothing.
    lit = dict(tr)
    lit["plan_usage"] = {"model": "claude-sonnet-4-6", "in": 80, "out": 600,
                         "cache_read": 8800, "cache_write": 0}
    _t2, s2 = gev._turn_cost_total_usd(lit)
    assert set(s2) == {"writer", "dispatch_planner", "desk_rewrite"}
    assert "desk_rewrite" in gev._per_answer_record(
        {"q": {"id": "q1"}, "out": {"trace": lit}}, "single")["turn_cost_by_seat_usd"]


def test_the_spend_panels_two_denominators_are_counted_and_named_separately():
    """ROUND-2 REVIEW M3 -- THE MIXED DECK. PROVEN BEFORE AND AFTER.

    The loop SKIPS writer-only rows and the headline then reported over `len(rows)` -- ALL of them.
    MEASURED BEFORE THE FIX on 2 census rows beside 6 writer-only rows carrying the same banked
    `synth_usage`:

        - **total $1.5357** over 8 row(s); `turn_cost_usd` (the WRITER alone ...) is $1.0577 of it -- 69%

    while that deck's OWN `turn_cost_usd` column summed to $4.2309. A panel built to stop a money
    column UNDER-reporting printed a census total BELOW the column it corrects, over a row count that
    did not produce it, and a reader taking "69%" as "the writer is 69% of the bill" was wrong twice.
    Both denominators are counted now, both are named in the line that uses them, and the panel says in
    words that the two are different populations rather than a delta."""
    pu = {"model": "claude-sonnet-4-6", "in": 80, "out": 600, "cache_read": 8800, "cache_write": 0}
    rows = ([_spend_row({"synth_usage": _SU, "plan_usage": pu}) for _ in range(2)]
            + [_spend_row({"synth_usage": _SU}) for _ in range(6)])
    t = "\n".join(gev.spend_report(rows))
    assert "over the 2 of 8 row(s) that stamped a seat BEYOND the writer" in t
    col = 8 * gev._turn_cost_usd(_SU)
    assert ("sums to $%.4f over all 8 row(s)" % col) in t
    assert "DIFFERENT DENOMINATOR" in t and "is not\na saving" not in t
    # THE HEADLINE IS THE CENSUS ROWS' MONEY, never the eight-row column wearing the census's name
    census = 2 * (gev._turn_cost_usd(_SU) + gev._seat_cost_usd(pu))
    assert ("**total $%.4f**" % census) in t
    assert ("**total $%.4f**" % col) not in t
    assert census < col                                            # the exact misreading, with the sign
    # ...and the writer's share is taken over the census total it is part of, not over the column
    assert ("the writer is $%.4f of that" % (2 * gev._turn_cost_usd(_SU))) in t
    # ROUND-2 REVIEW m2: the judge is not part of the turn, so the tier line says which it prices
    assert "(every stamped seat, turn + judge)" in t


def test_a_seat_map_that_sums_to_zero_prints_no_share_instead_of_losing_the_report():
    """ROUND-2 REVIEW m1 -- `if not seats` guards an EMPTY map, NOT one that sums to exactly $0.00.

    MEASURED: a row whose writer model is unpriced (correctly OMITTED from the map, the CostUsd
    0-semantics idiom) beside one all-zero-token numbers round gives `{'numbers': 0.0}`, and the
    writer-share division raised `ZeroDivisionError`. `report()` runs ONCE per deck AFTER a paid arm,
    so a raise there loses the whole ARTIFACT rather than a row -- exactly the class `state_report`'s
    own guard was written for. A share of nothing is not printed; it is omitted."""
    tr = {"synth_usage": {"model": "(unavailable)", "in": 9, "out": 9, "cache_read": 0, "cache_write": 0},
          "numbers_usage": [{"model": "claude-sonnet-5", "in": 0, "out": 0,
                             "cache_read": 0, "cache_write": 0}]}
    assert gev._turn_cost_usd(tr["synth_usage"]) is None           # unpriced -> omitted, never zeroed
    _t, s = gev._turn_cost_total_usd(tr)
    assert s == {"numbers": 0.0}
    L = gev.spend_report([_spend_row(tr)])                         # NO RAISE
    assert L and L[0].startswith("## Spend")
    assert "the writer is" not in "\n".join(L)                     # a share of nothing is not printed
    assert "## Spend" in gev.report([_spend_row(tr)], model="claude-opus-5")


def test_the_writer_seam_panel_reports_a_correction_as_a_defect_and_names_the_two_watch_counters():
    """LANE E's key, read by this lane. A correction count is a DEFECT count: `superlatives_corrected`
    means the writer made claims its OWN cited rows denied. And `writer_seam.watch_bullets` is NOT
    `state_board.coverage.watch_bullets` -- two counters over one object, measured 19 vs 16 on the
    2026-09-16 smoke -- so the panel names which is which rather than letting a reader sum them."""
    ws = {"outcome": "ok", "prose_words": 1833, "prose_ceiling": 900, "prose_over_budget": 933,
          "superlatives_seen": 4, "superlatives_corrected": 2, "classes_corrected": 1,
          "stale_sentences": 3, "stale_rows_dated": 2, "lag_windows_checked": 5,
          "lag_windows_corrected": 1, "decline_words_corrected": 0, "watch_bullets": 4,
          "watch_no_figure": 3, "watch_figures_added": 2, "watch_no_window": 2,
          "watch_no_falsifier": 1, "watch_over_ceiling": 1}
    L = gev.state_report([_srow({"answer": "x", "trace": {"writer_seam": ws},
                                 "structured": {"tldr": "", "mechanism": "x"}})])
    t = "\n".join(L)
    assert t.startswith("## Writer seam")                          # a header that promises no board
    assert "over budget by 933" in t and "THE CONTROL WAS NEVER TOLD A CEILING" in t
    assert "a DEFECT count" in t and "superlatives 2/4" in t
    assert "NOT the same population" in t and "NEVER SUMMED" in t
    assert "over the tier's own 3/5/7 ceiling: 1" in t
    # absent is never zero: a deck that ran no seam prints no seam line
    assert not any("WRITER SEAM" in x for x in gev.state_report([_srow(_board_out(coverage=dict(_COV)))]))


# == THE 09-23 FIX ROUND, O-2 -- OWNER DECISION 8 (a): THE v1 REGISTER COUNT BESIDE THE EXTENDED ONE ====
# The desk table grew eleven rows this round (firing, hop, declared way, ...), so the extended count moves on
# BOTH cells for a reason that is not the treatment (threat R-10). The report prints the v1 (HEAD's eleven
# tokens) count beside it, per cell, on the same rows -- measured by the REAL lint, never typed here.
_V1_BODY = "Five of eight past firings moved the declared way on this hop, and the board is loud on corn."


def test_fix_0923_O2_the_v1_register_count_rides_beside_the_extended_one_in_both_cells():
    from leviathan.graphrag import register as reg
    ext, v1 = reg.count_desk_register(_V1_BODY), reg.count_desk_register(_V1_BODY, reg.DESK_REGISTER_V1_NAMES)
    assert ext > v1 > 0                                   # the two tables disagree on this body, by design
    ctl = _srow(_board_out(answer=_V1_BODY, coverage=dict(_COV)))
    cov = dict(_COV, register_lingo_hits=3, register_lingo_rewritten=1, register_lingo_hits_v1=1)
    trt = _srow(_board_out(answer=_V1_BODY, coverage=cov,
                           desk={"hits_before": 5, "hits_after": 3, "hits_before_v1": 2, "hits_after_v1": 1,
                                 "offered_v1": 2, "rewritten_v1": 1, "outcome": "rewritten"}))
    body = "\n".join(gev.state_report([ctl, trt]))
    # the extended line is HEAD's words, untouched; the v1 line sits beside it on the same two cells
    assert f"shipped lint hits per answer: control **{ext:.1f}** -> treatment **{ext:.1f}**" in body
    assert f"the SAME pure lint on the v1 table** (`register.DESK_REGISTER_V1_NAMES`" in body
    assert f"control **{v1:.1f}** -> treatment **{v1:.1f}**, same rows" in body
    # the treatment's coverage and rewrite, each with its own v1 twin
    assert "the same count on the v1 table" in body and "): 1 over 1 turn(s)" in body
    assert "the same REWRITE on the v1 table: 2 -> 1 over 1 answer(s)" in body


def test_fix_0923_O2_a_census_from_before_the_v1_stamp_is_named_never_read_as_zero():
    stamped = _srow(_board_out(answer=_V1_BODY, coverage=dict(_COV),
                               desk={"hits_before": 5, "hits_after": 3, "hits_before_v1": 2,
                                     "hits_after_v1": 1, "outcome": "rewritten"}))
    clean = _srow(_board_out(answer="Corn stocks are tight.", coverage=dict(_COV),
                             desk={"hits_before": 0, "hits_after": 0, "outcome": "clean"}))   # v1 = 0 by inclusion
    banked = _srow(_board_out(answer=_V1_BODY, coverage=dict(_COV),
                              desk={"hits_before": 4, "hits_after": 2, "outcome": "rewritten"}))
    body = "\n".join(gev.state_report([stamped, clean, banked]))
    assert "the same REWRITE on the v1 table: 2 -> 1 over 2 answer(s) (1 census(es) from before the v1 " \
           "stamp left out, not read as zero)" in body
    # a deck of pre-round censuses only prints no v1 rewrite line at all, and no v1 coverage line
    old = "\n".join(gev.state_report([banked]))
    assert "the same REWRITE on the v1 table" not in old and "the same count on the v1 table" not in old


# ── 09-24 (fix round FINAL_2, INTEGRATION O-2): THE SPLAT REGISTRY's REPORT ────────────────────────
def _splat_row(**trace):
    out = _board_out(coverage=None)
    out["trace"].update(trace)
    return _srow(out)


def test_fix_0924_O2_a_REFUSED_pair_is_a_COUNTED_refusal_and_the_panel_is_absent_when_off():
    """INTEGRATION O-2 / THREAT T-3 "refuse and count": a turn whose RV pair leg ran carries EXACTLY ONE
    of `rv_pair_spread` (minted) and `rv_pair_uncomputed` (refused, in the calculator's own sentence);
    the report counts both over the leg's own denominator and prints each refusal's reason verbatim.
    The spine de-dup's census rides the same panel. A deck carrying none of the keys prints nothing --
    absent is never zero -- and a malformed record is counted, never raised."""
    reason = ("the two series are quoted in different currencies (EUR against USD), and this lookup never "
              "converts between them")
    minted = _splat_row(rv_pair_spread={"legs": 1, "markets": ["malaysian_crude_palm_oil_cme",
                                                               "soybean_oil_cbot"]})
    refused = _splat_row(rv_pair_uncomputed={"markets": ["malaysian_crude_palm_oil_cme", "rapeseed_oil_zce"],
                                             "reason": reason})
    spine = _splat_row(tldr_spine_deduped={"sections": 4, "sentences_removed": 45, "sentences_moved": 1})
    plain = _splat_row()
    body = "\n".join(gev.splat_census_report([minted, refused, spine, plain]))
    assert "RV PAIR LEG: ran on 2 of 4 turn(s) -- MINTED 1, REFUSED 1" in body
    assert "minted: 1 row(s) over the pairs {'malaysian_crude_palm_oil_cme / soybean_oil_cbot': 1}" in body
    assert ("{'%s': 1}; pairs {'malaysian_crude_palm_oil_cme / rapeseed_oil_zce': 1}" % reason) in body
    assert "de-duplicated on 1 of 4 turn(s)** -- 4 TL;DR section(s)" in body
    assert "45 sentence(s) removed from the TL;DR" in body and "1 moved into the mechanism" in body
    # ABSENT IS NEVER ZERO -- and the report() assembly adds nothing, not even the blank line
    assert gev.splat_census_report([plain]) == [] and gev.splat_census_report([]) == []
    assert "Per-turn records" not in gev.report([plain], model="claude-opus-5")
    assert "REFUSED 1" in gev.report([refused], model="claude-opus-5")
    # a truthy non-dict is COUNTED and named, never raised
    bad = "\n".join(gev.splat_census_report([_splat_row(rv_pair_uncomputed="refused")]))
    assert "rows whose record is not a mapping: {'rv_pair_uncomputed': 1}" in bad
    # ...and the per-answer record lifts the refusal verbatim, absent on the row that carries none
    rec = gev._per_answer_record(refused, "single")
    assert rec["rv_pair_uncomputed"]["reason"] == reason and "rv_pair_spread" not in rec
    assert "rv_pair_uncomputed" not in gev._per_answer_record(plain, "single")
