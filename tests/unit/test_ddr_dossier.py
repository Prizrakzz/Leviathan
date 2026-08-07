"""D-DR-1/2 -- the deep-research dossier orchestration leg (hermetic: no API, no AWS, no evidence store).

WHAT THESE PIN, in the order the plan states them:
  * the PLAN is deterministic playbook-first -- the same question yields the same six standing rows with
    or without a planner, and a dead planner degrades rather than failing the dossier;
  * the sub-query loop is SEQUENTIAL, shares ONE as-of, and turns a failure into a declared GAP
    (honest-partial) rather than an exception;
  * the ENGINE SPLIT from the D-CC-3 amended red branch: quick sub-queries run census-OFF (forced,
    because R1 measured the mandates harmful at quick width), deep run census-ON, and the override is
    thread-scoped so a concurrent turn is untouched;
  * the SPINE LAW: notes carry (claim, handle, prop_id, as_of) verbatim off the turn's OWN citation
    list, the synthesis prompt is built from NOTES (never raw evidence, never the assembled body), and
    every handle the document may write resolves to a carried pair;
  * the artifact body carries the visible plan, the disagreement + cannot-answer mandates and the
    sub-query trace, and lands through the SAME freeze `server._freeze_artifact` uses;
  * quota arithmetic: UTC ISO-week bucket, decrement at acceptance, refund on FAILED (not PARTIAL),
    bypass for the eval lane and named admins.
"""
from __future__ import annotations

import datetime as _dt
import threading

import pytest

from leviathan.graphrag import answer as an
from leviathan.graphrag import dossier as dsr
from leviathan.graphrag import response_contracts as rc
from leviathan.graphrag import store as st


class _FakeGraph:
    contracts = {"corn": object(), "arabica_coffee": object(), "soybean_oil_cbot": object()}
    version = "gddr01aabbcc"


IDENT = {"sub": "u-alice"}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in ("GRAPHRAG_DOSSIER", "GRAPHRAG_DOSSIER_ADMINS", "GRAPHRAG_AUTH",
              "GRAPHRAG_COMPOSITION_CENSUS", "GRAPHRAG_DISPATCH", "GRAPHRAG_DISPATCH_MODEL"):
        monkeypatch.delenv(k, raising=False)


def _store() -> st.InMemoryStore:
    return st.InMemoryStore()


# ── a sub-answer shaped exactly like a real respond() result ────────────────────────────────────────
def _result(i: int, *, contracts=("corn",), windows=0) -> dict:
    """One sub-answer. The keys used here are the ones respond() really returns: structured (tldr /
    mechanism / sources), citations (the machine Citation dicts), evidence rows, number_calls, trace."""
    return {
        "answer": "**TL;DR.** assembled body that these tests must never be read from [E1]\n\n## Sources\n[E1] x",
        "structured": {
            "tldr": f"Finding {i} rests on the dated row [E1].",
            "mechanism": (f"## Mechanism\nStocks are tight [E1] and the pace is behind [N1].\n"
                          f"## The record\nThe {i}th vintage prints lower [E1].\n"
                          f"## What to watch\nThe next release [N1]."),
            "sources": [{"ref": 1, "source": "usda_wasde", "date": "2024-05-10", "note": "stocks"}],
        },
        "citations": [
            {"id": "E1", "kind": "evidence", "label": f"usda_wasde (2024-05-10): chunk {i}",
             "source": "usda_wasde", "date": "2024-05-10",
             "payload": {"source_key": f"sk-{i}", "text": f"full prop text for sub-answer {i}"}},
            {"id": "N1", "kind": "number", "label": f"PSD stocks corn MY2024 = {100 + i} kt",
             "source": "PSD", "date": "2024-05-01",
             "payload": {"query": {"table": "silver_psd", "metric": "ending_stocks", "period": str(2024 + i)},
                         "rows": [{"value": 100 + i}]}},
        ],
        "evidence": [{"source_key": f"sk-{i}", "source": "usda_wasde", "date": "2024-05-10",
                      "text": f"full prop text for sub-answer {i}"}],
        "number_calls": [{"query": {"table": "silver_psd", "metric": "ending_stocks",
                                    "period": str(2024 + i)},
                          "rows": [{"value": 100 + i}, {"value": 99}, {"value": 98}, {"value": 97}],
                          "status": "ok"}],
        "asof": "2026-08-01", "contracts": list(contracts),
        "intent_decision": {"mode": {"honored": "quick"}},
        "trace": {"citation_verifier": {"checked": 4, "stripped": 0},
                  "episodes_injected": [{"spans": [{}] * windows}] if windows else [],
                  "synth_usage": {"model": "claude-sonnet-4-6", "in": 100, "out": 50}},
    }


# ══ 1. THE PLAN ══════════════════════════════════════════════════════════════════════════════════════
def test_plan_is_playbook_first_and_deterministic_without_any_model_call():
    """No planner at all (GRAPHRAG_DISPATCH=rules is the estate's planner kill-switch): the six standing
    rows still exist, in order, numbered, and two identical calls are byte-identical."""
    a = dsr.plan("what happens to corn if the crop fails?", asof="2026-08-01", graph=_FakeGraph(),
                 call=_boom)
    b = dsr.plan("what happens to corn if the crop fails?", asof="2026-08-01", graph=_FakeGraph(),
                 call=_boom)
    assert a == b
    assert [r["shape"] for r in a["subqueries"]] == [s.id for s in dsr.PLAYBOOK]
    assert a["planner"] == "playbook" and a["n"] == len(dsr.PLAYBOOK) >= dsr.MIN_SUBQUERIES
    assert [r["i"] for r in a["subqueries"]] == list(range(1, a["n"] + 1))
    assert {r["n"] for r in a["subqueries"]} == {a["n"]}


def _boom(*a, **kw):
    raise RuntimeError("planner is down")


def test_a_dead_planner_never_breaks_the_dossier():
    p = dsr.plan("corn balance", asof=None, graph=_FakeGraph(), call=_boom)
    assert p["planner"] == "playbook" and len(p["subqueries"]) == len(dsr.PLAYBOOK)
    assert p["title"] == "corn balance"                    # deterministic fallback title, never blank


def _exiter(*a, **kw):
    raise SystemExit("ANTHROPIC_API not found in environment or .env")


def test_a_provider_systemexit_is_survived_everywhere(monkeypatch):
    """providers.make_client() -> batch_extract._api_key() raises SystemExit, not Exception. A bare
    `except Exception` anywhere on this path kills the job thread and leaves the dossier stuck RUNNING
    forever -- the one failure mode the module is built to make impossible."""
    p = dsr.plan("corn", asof=None, graph=_FakeGraph(), call=_exiter)
    assert p["planner"] == "playbook"
    job, _ = _run(monkeypatch, _exiter)
    assert job.status == dsr.FAILED and "SystemExit" in job.subqueries[0]["error"]
    assert job.events[-1]["type"] == dsr.FAILED           # it LANDED; it did not vanish


def test_planner_titles_and_fills_gaps_within_the_cap():
    seen = {}

    def call(system, user, *, model, tool, **kw):
        seen.update(system=system, user=user, tool=tool)
        return {"title": "Corn balance under a failed crop",
                "subqueries": [{"title": "Ethanol grind", "question": "What is the ethanol grind doing?",
                                "width_hungry": False, "rationale": "demand leg"},
                               {"title": "Export rank", "question": "Rank the exporters at risk.",
                                "width_hungry": True, "rationale": "roster"}]}

    p = dsr.plan("corn crop failure", asof="2026-08-01", graph=_FakeGraph(), call=call)
    assert p["title"] == "Corn balance under a failed crop" and p["planner"] == "llm"
    assert len(p["subqueries"]) == len(dsr.PLAYBOOK) + 2
    extra = p["subqueries"][len(dsr.PLAYBOOK):]
    assert [r["source"] for r in extra] == ["planner", "planner"]
    assert [r["config"] for r in extra] == ["quick", "deep"]         # width_hungry -> deep
    # The planner is told what already exists, so it fills gaps rather than repeating the checklist.
    assert "STANDING SUB-QUESTIONS ALREADY PLANNED" in seen["user"]
    assert seen["tool"]["name"] == "set_dossier_plan"


def test_plan_never_exceeds_the_cap_even_with_a_greedy_planner():
    def call(*a, **kw):
        return {"title": "t", "subqueries": [{"title": f"x{i}", "question": f"q{i}?"} for i in range(50)]}

    p = dsr.plan("corn", asof=None, graph=_FakeGraph(), call=call)
    assert len(p["subqueries"]) == dsr.MAX_SUBQUERIES
    assert {r["n"] for r in p["subqueries"]} == {dsr.MAX_SUBQUERIES}


def test_width_hungry_shapes_are_the_deep_ones_and_only_those():
    """The D-CC-3 amended branch in one assertion: enumeration + cross-chain get the width engine, the
    focused single-market lookups do not."""
    deep = {s.id for s in dsr.PLAYBOOK if s.config == "deep"}
    assert deep == {"episodes", "comove"}
    assert all(s.config in ("quick", "deep") for s in dsr.PLAYBOOK)


def test_subject_resolution_is_deterministic_and_falls_back_to_the_question():
    g = _FakeGraph()
    assert dsr.subject("what is happening in corn stocks?", g) == "corn"
    assert dsr.subject("soybean oil vs palm", g) == "soybean oil"
    # No tracked contract named -> the question's own clause, so the sub-question still stands alone.
    assert dsr.subject("is the freight market tight?", g) == "is the freight market tight"


# ══ 2. THE SUB-QUERY LOOP ════════════════════════════════════════════════════════════════════════════
def _run(monkeypatch, respond, *, question="corn crop failure", asof="2026-08-01", synth=None,
         store=None, **kw):
    store = store or _store()
    job = dsr.Job("d-1", IDENT["sub"], question, asof, quota_period="dossier#2026-W32")
    dsr.register(job)

    def _plan(q, **k):
        rows = [dsr._entry(1, "One", "q1?", "quick", "r", shape="balance", source="playbook"),
                dsr._entry(2, "Two", "q2?", "deep", "r", shape="episodes", source="playbook")]
        for r in rows:
            r["n"] = len(rows)
        return {"title": "T", "asof": asof, "subject": "corn", "n": len(rows),
                "planner": "playbook", "subqueries": rows}

    monkeypatch.setattr(dsr, "plan", _plan)
    monkeypatch.setattr(dsr, "synthesize", synth or _fake_synth)
    try:
        dsr.execute(job, graph=_FakeGraph(), store=store, respond=respond, **kw)
    finally:
        dsr.forget(job.id)
    return job, store


def _fake_synth(question, asof, plan_data, notes, union, **kw):
    return {"structured": {"tldr": "doc", "mechanism": "## Mechanism\nbody [E1]", "sources": []},
            "verifier": {"enabled": True, "checked": 1, "stripped": 0}, "body": "BODY",
            "usage": {"model": "claude-sonnet-4-6", "in": 10, "out": 5}, "census": {"n_entities": 1}}


def test_subqueries_run_sequentially_and_share_one_asof(monkeypatch):
    order, concurrent = [], []
    gate = threading.Lock()
    seen_asof, seen_modes = set(), []

    def respond(q, *, graph, asof=None, mode=None, on_stage=None, **kw):
        if not gate.acquire(blocking=False):
            concurrent.append(q)                                 # would only fire under parallelism
        order.append(q)
        seen_asof.add(asof)
        seen_modes.append(mode)
        gate.release()
        return _result(len(order))

    job, _ = _run(monkeypatch, respond)
    assert order == ["q1?", "q2?"] and concurrent == []          # Cohere 3/min: never co-scheduled
    assert seen_asof == {"2026-08-01"}                            # ONE as-of stamped at submission
    assert seen_modes == ["quick", "deep"]
    assert job.status == dsr.DONE


def test_one_failed_subquery_yields_a_partial_dossier_with_the_gap_declared(monkeypatch):
    def respond(q, *, graph, asof=None, **kw):
        if q == "q1?":
            raise RuntimeError("evidence store is down")
        return _result(2)

    job, store = _run(monkeypatch, respond)
    assert job.status == dsr.PARTIAL                              # honest-partial, never a silent drop
    assert [r["status"] for r in job.subqueries] == [dsr.SQ_FAILED, dsr.SQ_OK]
    assert "evidence store is down" in job.subqueries[0]["error"]
    assert job.artifact_id                                        # a partial dossier still LANDS
    trace = _artifact(store, job)["payload"]["subquery_trace"]
    assert trace[0]["status"] == dsr.SQ_FAILED and trace[0]["error"]


def test_every_subquery_failing_lands_failed_and_refunds_the_slot(monkeypatch):
    store = _store()
    store.incr_turn_quota(IDENT["sub"], "dossier#2026-W32", dsr.QUOTA_LIMIT)
    job, store = _run(monkeypatch, _boom_respond, store=store)
    assert job.status == dsr.FAILED and job.error
    assert store.read_quota(IDENT["sub"], "dossier#2026-W32") == 0      # FAILED -> refunded


def _boom_respond(q, **kw):
    raise RuntimeError("dead")


def test_partial_does_not_refund(monkeypatch):
    store = _store()
    store.incr_turn_quota(IDENT["sub"], "dossier#2026-W32", dsr.QUOTA_LIMIT)

    def respond(q, *, graph, asof=None, **kw):
        if q == "q1?":
            raise RuntimeError("gap")
        return _result(2)

    job, store = _run(monkeypatch, respond, store=store)
    assert job.status == dsr.PARTIAL
    assert store.read_quota(IDENT["sub"], "dossier#2026-W32") == 1      # spent: a document was delivered


def test_wall_clock_cap_skips_the_rest_and_still_composes(monkeypatch):
    def respond(q, *, graph, asof=None, **kw):
        return _result(1)

    job, _ = _run(monkeypatch, respond, wall_clock_s=-1)
    # Deadline already blown: nothing runs, nothing to compose -> FAILED, declared, not hung.
    assert job.status == dsr.FAILED
    assert [r["status"] for r in job.subqueries] == [dsr.SQ_SKIPPED, dsr.SQ_SKIPPED]
    assert "wall-clock" in job.subqueries[0]["error"]


def test_a_hung_subcall_costs_one_subquestion_not_the_job(monkeypatch):
    def respond(q, *, graph, asof=None, **kw):
        if q == "q1?":
            threading.Event().wait(30)                            # never returns within the timeout
        return _result(2)

    job, _ = _run(monkeypatch, respond, subcall_timeout_s=0.2)
    assert job.status == dsr.PARTIAL
    assert job.subqueries[0]["status"] == dsr.SQ_FAILED and "TimeoutError" in job.subqueries[0]["error"]
    assert job.subqueries[1]["status"] == dsr.SQ_OK


# ══ 3. THE ENGINE SPLIT (the D-CC-3 amended red branch) ══════════════════════════════════════════════
def test_quick_forces_the_census_off_and_deep_forces_it_on(monkeypatch):
    """R1 measured the composition mandates ACTIVELY HARMFUL at quick width. So quick is not merely
    'left to the flag' -- it is forced OFF even when the serving env has the flag on."""
    monkeypatch.setenv("GRAPHRAG_COMPOSITION_CENSUS", "on")
    seen = []

    def respond(q, *, graph, asof=None, mode=None, **kw):
        seen.append((mode, an._composition_census_on()))
        return _result(1)

    _run(monkeypatch, respond)
    assert seen == [("quick", False), ("deep", True)]


def test_the_override_does_not_leak_to_the_thread_or_to_other_threads():
    """The whole reason it is a ContextVar and not an os.environ flip."""
    assert an._composition_census_on() is False
    other = {}

    def peek():
        other["v"] = an._composition_census_on()

    with an.composition_census_override(True):
        assert an._composition_census_on() is True
        t = threading.Thread(target=peek)
        t.start()
        t.join()
    assert other["v"] is False                       # a concurrent desk turn is untouched
    assert an._composition_census_on() is False      # and the block restores on exit


def test_the_override_restores_even_when_the_block_raises():
    with pytest.raises(ValueError):
        with an.composition_census_override(True):
            raise ValueError("boom")
    assert an._composition_census_on() is False


def test_env_flag_still_decides_when_no_override_is_set(monkeypatch):
    monkeypatch.setenv("GRAPHRAG_COMPOSITION_CENSUS", "on")
    assert an._composition_census_on() is True
    with an.composition_census_override(None):
        assert an._composition_census_on() is True   # None = "no override", not "off"


# ══ 4. NOTES + THE SPINE LAW ═════════════════════════════════════════════════════════════════════════
def test_notes_carry_the_citation_pairs_verbatim_off_the_turns_own_list():
    res = _result(3)
    note = dsr.notes_from_result(res, {"i": 1, "title": "One", "question": "q?", "config": "quick",
                                       "shape": "balance"})
    pairs = {p["handle"]: p for p in note["pairs"]}
    assert set(pairs) == {"E1", "N1"}
    assert pairs["E1"]["prop_id"] == "sk-3"                       # the prop identity, carried
    assert pairs["E1"]["as_of"] == "2024-05-10"                   # when it was KNOWN
    assert pairs["E1"]["prop_text"] == "full prop text for sub-answer 3"
    assert pairs["N1"]["label"].endswith("103 kt")                # the figure the doc may restate
    assert note["asof"] == "2026-08-01" and note["strips"] == 0
    assert note["used"] == ["E1", "N1"]                           # what a carried claim stood behind


def test_notes_are_built_from_the_structured_field_never_the_assembled_body():
    """D-DT item-2: the assembled body carries the rendered sources footer, and all four discovery
    rules leaked the last time anything read it. The note must be reconstructible from `structured`
    alone -- proven by deleting the body and getting the identical note."""
    res = _result(4)
    with_body = dsr.notes_from_result(res, {"i": 1, "title": "t", "question": "q", "config": "quick"})
    res.pop("answer")
    assert dsr.notes_from_result(res, {"i": 1, "title": "t", "question": "q", "config": "quick"}) == with_body
    assert [s["heading"] for s in with_body["sections"]] == ["Mechanism", "The record", "What to watch"]
    assert with_body["sections"][0]["handles"] == ["E1", "N1"]


def test_a_handle_with_no_carried_pair_is_dropped_not_guessed():
    res = _result(5)
    res["structured"]["mechanism"] = "## Mechanism\nBacked [E1] and invented [E9]."
    note = dsr.notes_from_result(res, {"i": 1, "title": "t", "question": "q", "config": "quick"})
    assert note["sections"][0]["handles"] == ["E1"]               # E9 has no pair -> never recorded
    union = dsr.build_union([note], [res])
    assert dsr.remap_body("Backed [E1] and invented [E9].", union["remap"][1]) == "Backed [E1] and invented ."


def test_the_union_dedups_by_prop_and_renumbers_deterministically():
    a = _result(1)
    b = _result(1)                                               # SAME prop (sk-1) cited by both
    c = _result(2)
    notes = [dsr.notes_from_result(r, {"i": i, "title": "t", "question": "q", "config": "quick"})
             for i, r in enumerate((a, b, c), 1)]
    u = dsr.build_union(notes, [a, b, c])
    assert [p["handle"] for p in u["pairs"]] == ["E1", "N1", "E2", "N2"]
    assert u["remap"][1] == u["remap"][2] == {"E1": "E1", "N1": "N1"}    # same prop -> same global handle
    assert u["remap"][3] == {"E1": "E2", "N1": "N2"}
    assert [e["source_key"] for e in u["evidence"]] == ["sk-1", "sk-2"]
    # A retrieved-but-uncited prop is NOT admitted: a turn's citation list is its whole retrieved set,
    # and the dossier's citable pool is "what a carried claim stood behind", never the raw retrieval.
    c["citations"].append({"id": "E2", "kind": "evidence", "label": "unused", "source": "usda_fas",
                           "date": "2024-01-01", "payload": {"source_key": "sk-unused", "text": "x"}})
    notes2 = [dsr.notes_from_result(r, {"i": i, "title": "t", "question": "q", "config": "quick"})
              for i, r in enumerate((a, b, c), 1)]
    assert "sk-unused" not in {p["prop_id"] for p in dsr.build_union(notes2, [a, b, c])["pairs"]}
    # The FULL number-call record is carried, not the citation payload's 3-row truncation -- otherwise
    # the final verifier would charge number_mismatch against figures that are in fact backed.
    assert len(u["number_calls"][0]["rows"]) == 4


# ══ 5. SYNTHESIS ═════════════════════════════════════════════════════════════════════════════════════
def _notes_and_union(n=2, windows=0):
    results = [_result(i, windows=windows) for i in range(1, n + 1)]
    notes = [dsr.notes_from_result(r, {"i": i, "title": f"S{i}", "question": f"q{i}?",
                                       "config": "quick", "shape": "balance"})
             for i, r in enumerate(results, 1)]
    return notes, dsr.build_union(notes, results), results


def test_synthesis_prompt_carries_notes_and_never_raw_evidence():
    notes, union, results = _notes_and_union()
    plan_data = {"subqueries": [{"i": i, "n": 2, "title": f"S{i}", "question": f"q{i}?",
                                 "config": "quick", "status": dsr.SQ_OK} for i in (1, 2)]}
    block = dsr.notes_block("corn?", "2026-08-01", plan_data, notes, union)
    assert "NOTES FROM THE SUB-ANSWERS" in block and "PLAN (this ran" in block
    # Each note's claim arrives with ITS OWN handles remapped into the one global namespace: sub-answer
    # 1's [E1] stays E1, sub-answer 2's [E1] (a different prop) becomes E2.
    assert "Stocks are tight [E1] and the pace is behind [N1]." in block
    assert "Stocks are tight [E2] and the pace is behind [N2]." in block
    # Raw evidence never appears as an evidence BLOCK; props reach the model only as pair receipts.
    assert "=== EVIDENCE" not in block and "GROUNDING LEDGER" not in block
    assert "CITATION PAIRS" in block
    # And the assembled sub-answer bodies are not in the prompt either (spine law).
    assert "assembled body that these tests must never be read from" not in block


def test_synthesis_runs_the_document_contract_with_the_union_census():
    notes, union, results = _notes_and_union(windows=3)
    seen = {}

    def call(system, user, *, model, tool):
        seen.update(system=system, user=user, tool=tool)
        return {"tldr": "d", "mechanism": "## Mechanism\nx [E1]", "sources": []}

    out = dsr.synthesize("corn?", "2026-08-01", {"subqueries": []}, notes, union, call=call)
    for heading in rc.DOSSIER_SECTIONS:
        assert heading in seen["system"]
    assert rc.CANNOT in seen["system"] and rc.DISAGREES in seen["system"]
    assert "DOSSIER COMPOSITION" in seen["system"]
    assert "EPISODE-COVERAGE: 6 dated episode window(s)" in seen["system"]   # union: 3 + 3
    assert "THRESHOLD-LOCATE" in seen["system"]                              # document-scale mandate
    assert seen["tool"]["name"] == "emit_answer"          # the verifier's own schema, reused not re-declared
    assert out["census"]["n_evidence"] == len(union["evidence"])


def test_synthesis_verifies_the_final_body_against_the_union_evidence(monkeypatch):
    notes, union, results = _notes_and_union()
    seen = {}
    from leviathan.graphrag import verify as vf
    real = vf.verify_citations

    def spy(structured, evidence, number_calls=None, **kw):
        seen.update(evidence=evidence, number_calls=number_calls)
        return real(structured, evidence, number_calls, **kw)

    monkeypatch.setattr(vf, "verify_citations", spy)
    dsr.synthesize("corn?", "2026-08-01", {"subqueries": []}, notes, union,
                   call=lambda s, u, **k: {"tldr": "d", "mechanism": "## Mechanism\nx [E1]",
                                           "sources": [{"ref": 1, "source": "usda_wasde",
                                                        "date": "2024-05-10", "note": "n"}]})
    assert seen["evidence"] == union["evidence"] and seen["number_calls"] == union["number_calls"]


def test_the_rendered_sources_block_comes_from_carried_pairs_only():
    notes, union, results = _notes_and_union()
    structured = {"tldr": "d", "mechanism": "## Mechanism\nfact [E1]", "sources": []}
    block = dsr._sources_block(structured, union)
    assert "[E1] usda_wasde (2024-05-10)" in block
    assert "[E2]" not in block                                    # uncited pairs are not listed


# ══ 6. THE ARTIFACT ══════════════════════════════════════════════════════════════════════════════════
def _artifact(store, job) -> dict:
    return store.get_item(job.user, dsr.ARTIFACT_KIND, job.artifact_id)["snapshot"]


def test_artifact_body_carries_the_visible_plan_sections_and_trace(monkeypatch):
    def respond(q, *, graph, asof=None, **kw):
        return _result(1 if q == "q1?" else 2)

    job, store = _run(monkeypatch, respond)
    snap = _artifact(store, job)
    p = snap["payload"]
    assert p["kind"] == "dossier" and p["dossier_id"] == job.id
    assert [r["question"] for r in p["plan"]["subqueries"]] == ["q1?", "q2?"]   # the PLAN is visible
    assert [r["config"] for r in p["subquery_trace"]] == ["quick", "deep"]
    assert p["citations"] and all({"handle", "prop_id", "as_of"} <= set(c) for c in p["citations"])
    assert "sections" in p and "citation_verifier" in p and "usage" in p
    assert snap["question"] == "corn crop failure" and snap["asof"] == "2026-08-01"
    assert snap["graph_version"] == _FakeGraph.version     # pinned like every other frozen turn


def test_the_dossier_artifact_body_matches_the_existing_artifact_freeze_shape(monkeypatch):
    """The result lands through the D-AM-15 seam, not beside it: same store kind, same body keys, so it
    opens in the artifact tab with no new collection and no new privacy story."""
    from leviathan.graphrag import server as sv

    def respond(q, **kw):
        return _result(1)

    job, store = _run(monkeypatch, respond)
    mine = store.get_item(job.user, dsr.ARTIFACT_KIND, job.artifact_id)
    theirs = sv._freeze_artifact({"name": "n", "question": "q", "asof": "2026-08-01", "payload": {}})
    assert set(mine) - {"id", "kind"} == set(theirs)
    assert set(mine["snapshot"]) == {"id", "question", "asof", "graph_version", "created_at", "payload"}


def test_every_rendered_handle_resolves_to_a_carried_pair(monkeypatch):
    """The deterministic spine gate D-DR-4 will check: zero spine violations."""
    def respond(q, **kw):
        return _result(1 if q == "q1?" else 2)

    def synth(question, asof, plan_data, notes, union, **kw):
        out = _fake_synth(question, asof, plan_data, notes, union)
        out["structured"]["mechanism"] = "## Mechanism\na [E1] b [E2] c [N1]"
        return out

    job, store = _run(monkeypatch, respond, synth=synth)
    p = _artifact(store, job)["payload"]
    carried = {c["handle"] for c in p["citations"]}
    used = {h for s in p["sections"] for h in [x["handle"] for x in s["sources"]]}
    assert used and used <= carried


# ══ 7. QUOTA (D-DR-2) ════════════════════════════════════════════════════════════════════════════════
def _mon(y, m, d, h=0):
    return _dt.datetime(y, m, d, h, tzinfo=_dt.timezone.utc)


def test_week_bucket_and_reset_agree_on_the_same_monday_boundary():
    sun = _mon(2026, 8, 9, 23)                 # Sunday 23:00Z
    mon = _mon(2026, 8, 10, 0)                 # Monday 00:00Z -- the next bucket
    assert dsr.week_key(sun) != dsr.week_key(mon)
    assert dsr.week_reset_at(sun) == "2026-08-10T00:00:00Z"
    assert dsr.week_reset_at(mon) == "2026-08-17T00:00:00Z"
    assert dsr.week_key(_mon(2026, 8, 10, 0)) == dsr.week_key(_mon(2026, 8, 16, 23))   # one whole week


def test_quota_decrements_at_acceptance_and_refuses_the_fourth(monkeypatch):
    monkeypatch.setenv("GRAPHRAG_AUTH", "on")
    s = _store()
    now = _mon(2026, 8, 6)
    for i in range(dsr.QUOTA_LIMIT):
        assert dsr.consume_quota(s, IDENT, now=now) == dsr.quota_period(now)
        assert dsr.quota_state(s, IDENT, now=now)["remaining"] == dsr.QUOTA_LIMIT - (i + 1)
    with pytest.raises(st.QuotaExceeded):
        dsr.consume_quota(s, IDENT, now=now)
    assert dsr.quota_state(s, IDENT, now=now) == {"remaining": 0, "limit": 3,
                                                  "reset_at": dsr.week_reset_at(now)}


def test_the_next_utc_week_is_a_fresh_bucket(monkeypatch):
    monkeypatch.setenv("GRAPHRAG_AUTH", "on")
    s = _store()
    for _ in range(dsr.QUOTA_LIMIT):
        dsr.consume_quota(s, IDENT, now=_mon(2026, 8, 6))
    assert dsr.quota_state(s, IDENT, now=_mon(2026, 8, 6))["remaining"] == 0
    assert dsr.quota_state(s, IDENT, now=_mon(2026, 8, 13))["remaining"] == dsr.QUOTA_LIMIT


def test_refund_never_mints_a_negative_counter(monkeypatch):
    monkeypatch.setenv("GRAPHRAG_AUTH", "on")
    s = _store()
    p = dsr.consume_quota(s, IDENT, now=_mon(2026, 8, 6))
    dsr.refund_quota(s, IDENT["sub"], p)
    dsr.refund_quota(s, IDENT["sub"], p)                          # double refund
    assert s.read_quota(IDENT["sub"], p) == 0


def test_eval_lane_and_admins_bypass_quota(monkeypatch):
    s = _store()
    assert dsr.quota_bypass(IDENT) is True                        # auth OFF = eval/dev lane
    assert dsr.consume_quota(s, IDENT) is None and s.read_quota(IDENT["sub"], dsr.quota_period()) == 0
    assert dsr.quota_state(s, IDENT)["bypass"] is True
    monkeypatch.setenv("GRAPHRAG_AUTH", "on")
    assert dsr.quota_bypass(IDENT) is False
    monkeypatch.setenv("GRAPHRAG_DOSSIER_ADMINS", "u-alice,u-bob")
    assert dsr.quota_bypass(IDENT) is True
    assert dsr.quota_bypass({"sub": "u-carol"}) is False
    assert dsr.quota_bypass({"sub": "u-carol", "groups": ["internal"]}) is True


def test_quota_read_fails_open(monkeypatch):
    monkeypatch.setenv("GRAPHRAG_AUTH", "on")

    class _Dead:
        def read_quota(self, *a, **k):
            raise RuntimeError("dynamo is sulking")

    assert dsr.quota_state(_Dead(), IDENT)["remaining"] == dsr.QUOTA_LIMIT


# ══ 8. FLAG + RESTART SEMANTICS ══════════════════════════════════════════════════════════════════════
def test_flag_grammar_dark_wildcard_and_allowlist(monkeypatch):
    assert dsr.enabled() is False and dsr.allowed("u-alice") is False
    monkeypatch.setenv("GRAPHRAG_DOSSIER", "off")
    assert dsr.enabled() is False and dsr.allowed("u-alice") is False
    monkeypatch.setenv("GRAPHRAG_DOSSIER", "on")
    assert dsr.enabled() is True and dsr.allowed("anyone") is True
    monkeypatch.setenv("GRAPHRAG_DOSSIER", "u-alice, u-bob")
    assert dsr.allowed("u-alice") is True and dsr.allowed("u-carol") is False


def test_an_orphaned_job_lands_failed_and_refunds_on_the_next_read(monkeypatch):
    s = _store()
    s.incr_turn_quota(IDENT["sub"], "dossier#2026-W32", dsr.QUOTA_LIMIT)
    rec = {"dossier_id": "gone", "status": dsr.RUNNING, "stage": "subquery 2/6",
           "quota_period": "dossier#2026-W32", "subqueries": [], "events": []}
    s.put_item(IDENT["sub"], dsr.KIND, "gone", rec)
    out = dsr.reap_orphan(s, IDENT["sub"], rec)
    assert out["status"] == dsr.FAILED and "restarted" in out["error"]
    assert s.read_quota(IDENT["sub"], "dossier#2026-W32") == 0
    assert s.get_item(IDENT["sub"], dsr.KIND, "gone")["status"] == dsr.FAILED
    # Idempotent: a second read must not refund twice.
    dsr.reap_orphan(s, IDENT["sub"], s.get_item(IDENT["sub"], dsr.KIND, "gone"))
    assert s.read_quota(IDENT["sub"], "dossier#2026-W32") == 0


def test_a_live_job_is_never_reaped(monkeypatch):
    job = dsr.Job("live-1", IDENT["sub"], "q", "2026-08-01")
    dsr.register(job)
    try:
        rec = job.record()
        assert dsr.reap_orphan(_store(), IDENT["sub"], rec)["status"] == dsr.PLANNING
    finally:
        dsr.forget("live-1")


# ══ 9. EVENTS ════════════════════════════════════════════════════════════════════════════════════════
def test_event_order_is_plan_then_subqueries_then_synthesis_then_terminal(monkeypatch):
    def respond(q, **kw):
        return _result(1)

    job, _ = _run(monkeypatch, respond)
    kinds = [e["type"] for e in job.events]
    assert kinds[0] == "stage"
    assert kinds.index("plan") < kinds.index("subquery") < kinds.index("synthesis") < kinds.index(dsr.DONE)
    assert kinds[-1] == dsr.DONE and job.events[-1]["artifact_id"] == job.artifact_id
    assert sum(1 for k in kinds if k == "subquery") == 4          # running + terminal, per sub-question


def test_a_late_subscriber_replays_then_tails():
    job = dsr.Job("ev-1", IDENT["sub"], "q", "2026-08-01")
    job.emit("plan", n=2)
    replay, q = job.subscribe()
    assert [e["type"] for e in replay] == ["plan"]
    job.emit(dsr.DONE, artifact_id="a1")
    assert q.get_nowait()["type"] == dsr.DONE
    job.unsubscribe(q)
    job.emit("stage", stage="ignored")
    assert q.empty()


# ══ 10. THE DOSSIER CONTRACT IN THE LEAF (D-DR-1 x D-CC-1) ═══════════════════════════════════════════
def test_the_dossier_contract_is_not_on_the_turn_menu():
    """LOAD-BEARING. `valid_names()` IS the turn-path allowlist (answer._response_contracts_enabled()
    returns exactly it under the wildcard flag), so a `dossier` entry in CONTRACTS would become
    selectable on an ordinary desk turn and would be swept live by GRAPHRAG_RESPONSE_CONTRACT=on."""
    assert "dossier" not in rc.CONTRACTS and "dossier" not in rc.valid_names()
    assert an._response_contracts_enabled() == frozenset()          # flag off in this suite
    assert rc.DOSSIER.name == "dossier"


def test_the_new_cannot_heading_stays_out_of_the_turn_vocabulary():
    """D-RC-3's nine reserved literals are the TURN vocabulary; adding CANNOT to SECTIONS would move
    eval._FIXED_SCAFFOLD's neighbourhood and answer._SECTION_KINDS."""
    assert rc.CANNOT not in rc.SECTIONS
    assert rc.CANNOT in rc.DOSSIER_SECTIONS and rc.DISAGREES in rc.DOSSIER_SECTIONS
    assert rc.DOSSIER_SECTIONS[0] == rc.MECHANISM and rc.WATCH == rc.DOSSIER_SECTIONS[-1]
    assert rc.DOSSIER.conditional == ()                             # every section mandated


def test_the_dossier_directive_reuses_the_three_mandate_producers():
    census = {"entities": ("Brazil", "Russia", "Ukraine", "corn"), "n_entities": 4,
              "n_episode_windows": 5, "n_evidence": 40}
    d = rc.dossier_directive(census)
    assert d.startswith(rc.DOSSIER.directive)
    assert rc.rank_complete_clause(census["entities"], 4) in d
    assert rc.threshold_locate_clause(40) in d
    assert rc.episode_coverage_clause(5) in d
    # Every mandate keeps its "or say the record can't" ending -- the refusal-honest law.
    for escape in ("no dated row at the as-of", "does not locate a switch point",
                   "no citable item inside that window"):
        assert escape in d


def test_the_dossier_directive_and_budget_fail_open_without_a_census():
    assert rc.dossier_directive(None) == rc.DOSSIER.directive
    assert rc.dossier_budget(None) == rc.DOSSIER.budget
    assert rc.dossier_budget({"n_entities": 1}) == rc.DOSSIER.budget          # below MIN_RANK_ENTITIES
    assert rc.dossier_budget({"n_entities": 8}) != rc.DOSSIER.budget          # the mandate is paid for


def test_the_dossier_system_prompt_carries_the_plan_budget_and_mandates():
    sysm = dsr.system_prompt({"entities": ("Brazil", "Russia"), "n_entities": 2,
                              "n_episode_windows": 0, "n_evidence": 12})
    assert rc.dossier_structure_clause() in sysm
    assert f"target {rc.dossier_budget({'n_entities': 2})} words" in sysm
    assert "RANK-COMPLETE" in sysm and "THRESHOLD-LOCATE" in sysm
    assert "EPISODE-COVERAGE" not in sysm                            # no windows -> no mandate
    assert "never invent" in sysm or "Never invent" in sysm          # handle discipline is stated


# ══ 11. THE QUOTA SATELLITE (store) ══════════════════════════════════════════════════════════════════
def test_read_and_refund_quota_are_on_the_store_protocol():
    for name in ("read_quota", "refund_quota"):
        assert hasattr(st.Store, name) and hasattr(st.InMemoryStore, name)
        assert hasattr(st.DynamoStore, name)


def test_in_memory_quota_satellite_round_trips():
    s = _store()
    assert s.read_quota("u", "dossier#2026-W32") == 0
    s.incr_turn_quota("u", "dossier#2026-W32", 3)
    s.incr_turn_quota("u", "dossier#2026-W32", 3)
    assert s.read_quota("u", "dossier#2026-W32") == 2
    s.refund_quota("u", "dossier#2026-W32")
    assert s.read_quota("u", "dossier#2026-W32") == 1
    assert s.read_quota("u", "dossier#2026-W33") == 0                # buckets are independent


def test_the_dossier_counter_never_touches_the_daily_turn_counter():
    s = _store()
    for _ in range(3):
        s.incr_turn_quota("u", dsr.quota_period(), dsr.QUOTA_LIMIT)
    s.incr_turn_quota("u", "2026-08-06", 50)                         # the daily turn counter
    assert s.read_quota("u", "2026-08-06") == 1 and s.read_quota("u", dsr.quota_period()) == 3
