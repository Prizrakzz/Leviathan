"""E-W2 harness resilience — per-turn watchdog, incremental JSONL persistence, heartbeat (all mocked)."""
from __future__ import annotations

import json
import time

from leviathan.graphrag import eval as gev


def _clean_answer(question, *, graph, model, k, asof=None, near=None):
    return {"answer": "Clean prose.", "contract": "corn", "structured": {}, "evidence": [], "citations": [],
            "trace": {"citation_verifier": {"enabled": True, "checked": 1, "stripped": 0, "claim_count": 2,
                                            "corrected": 0, "by_rule": {}}}}


def _row(rid="q1", degraded=None):
    trace = {"citation_verifier": {"enabled": True, "checked": 3, "stripped": 1, "claim_count": 4,
                                   "corrected": 0, "by_rule": {"fabricated_citation": 1}}}
    if degraded is not None:
        trace["degraded_model"] = degraded
    return {"q": {"id": rid, "contract": "corn", "expected_intent": "reasoning"},
            "out": {"answer": "Clean prose.", "intent": "reasoning", "trace": trace,
                    "structured": {}, "evidence": [], "citations": []},
            "rubric": {"routed_right": True, "intent_ok": True, "cascade_asserts": None},
            "secs": 12.0}


def test_timeout_row_shape():
    q = {"id": "q1", "contract": "corn", "expect": {}}
    tr = gev._timeout_row(q, 4200)
    assert tr["secs"] == 4200                                        # secs == deadline
    assert tr["rubric"]["routed_right"] is False                    # score() runs: contract None != corn
    assert tr["out"]["trace"]["degraded_model"] == "(watchdog_timeout)"   # AV2: counts as RETRY-TRANSIENT
    assert tr["out"]["trace"]["error"] == "watchdog_timeout"        # both causes stay distinguishable
    rec = gev._per_answer_record(tr, "single")
    assert rec["degraded_model"] == "(watchdog_timeout)" and rec["secs"] == 4200


def test_per_answer_record_zero_drift():
    # the partial JSONL builder and _baseline_json MUST agree byte-for-byte on a normal row.
    row = _row("q1")
    rec = gev._per_answer_record(row, "single")
    doc = gev._baseline_json([row], run_kind="single", model="m", judged=False, eval_set="v4",
                             graph_version="g", corpus_fp="c")
    assert doc["per_answer"][0] == rec
    assert "degraded_model" in rec and rec["degraded_model"] is None   # F12 key present, null on a clean turn


def test_watchdog_orphans_slow_turn_and_bounds_wall_clock(capsys):
    def ans(question, *, graph, model, k, asof=None, near=None):
        if "slow" in question:
            time.sleep(2.0)                                         # far past the 0.5s deadline
        return _clean_answer(question, graph=graph, model=model, k=k, asof=asof, near=near)
    queries = [{"id": "fast", "contract": "corn", "question": "quick"},
               {"id": "slow", "contract": "corn", "question": "slow one"}]
    t0 = time.monotonic()
    rows = gev.run(None, queries, answer_fn=ans, workers=2, deadline=0.5, heartbeat_period=0.1)
    elapsed = time.monotonic() - t0
    assert elapsed < 1.5                                            # bounded by the deadline, NOT the 2s sleep
    by = {r["q"]["id"]: r for r in rows}
    assert by["fast"]["out"]["answer"] == "Clean prose."           # the healthy turn completed normally
    assert by["slow"]["out"]["trace"]["degraded_model"] == "(watchdog_timeout)"
    assert by["slow"]["secs"] == 0.5                               # the timeout row records the deadline
    assert "WATCHDOG" in capsys.readouterr().out


def test_run_persists_partial_matching_baseline(tmp_path, monkeypatch):
    monkeypatch.setattr(gev, "_OUT", tmp_path)
    queries = [{"id": "q1", "contract": "corn", "question": "a"},
               {"id": "q2", "contract": "corn", "question": "b"}]
    pw = gev._PartialWriter(gev._partial_path("v4", "anthropic"), "single")
    rows = gev.run(None, queries, answer_fn=_clean_answer, workers=2, persist=pw, deadline=100,
                   heartbeat_period=0.1)
    pw.close()
    lines = [json.loads(l) for l in
             gev._partial_path("v4", "anthropic").read_text(encoding="utf-8").splitlines()]
    doc = gev._baseline_json(rows, run_kind="single", model="m", judged=False, eval_set="v4",
                             graph_version="g", corpus_fp="c")
    by_id = {p["id"]: p for p in doc["per_answer"]}
    assert len(lines) == 2
    for rec in lines:                                              # each persisted line == the baseline row
        assert rec == by_id[rec["id"]]
        assert "degraded_model" in rec


def test_sequential_run_persists_each_turn(tmp_path, monkeypatch):
    monkeypatch.setattr(gev, "_OUT", tmp_path)
    queries = [{"id": "q1", "contract": "corn", "question": "a"}]
    pw = gev._PartialWriter(gev._partial_path("v4", "anthropic"), "single")
    gev.run(None, queries, answer_fn=_clean_answer, workers=1, persist=pw)   # workers<=1 sequential loop
    pw.close()
    lines = gev._partial_path("v4", "anthropic").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["id"] == "q1"


def test_partial_writer_flushes_every_write_without_close(tmp_path, monkeypatch):
    # AV1: file CONTENT must be readable after EACH write with the handle STILL OPEN -> buffering=1 + flush
    # (a block-buffered handle would keep the tail in-process and lose it on kill -9).
    monkeypatch.setattr(gev, "_OUT", tmp_path)
    p = tmp_path / "partial_x.jsonl"
    pw = gev._PartialWriter(p, "single")
    pw(_row("q1"))
    c1 = p.read_text(encoding="utf-8")                            # handle NOT closed
    assert c1.endswith("\n") and c1.count("\n") == 1 and json.loads(c1.splitlines()[0])["id"] == "q1"
    pw(_row("q2"))
    c2 = p.read_text(encoding="utf-8")                            # still open — second record already flushed
    assert c2.count("\n") == 2 and json.loads(c2.splitlines()[1])["id"] == "q2"
    pw.close()


def test_heartbeat_prints_during_run(capsys):
    def slow(question, *, graph, model, k, asof=None, near=None):
        time.sleep(0.35)                                           # long enough for a 0.1s heartbeat to fire
        return _clean_answer(question, graph=graph, model=model, k=k, asof=asof, near=near)
    queries = [{"id": "q1", "contract": "corn", "question": "a"}]
    gev.run(None, queries, answer_fn=slow, workers=2, deadline=100, heartbeat_period=0.1)
    out = capsys.readouterr().out
    assert "heartbeat:" in out and "n_answered=" in out and "in_flight=" in out
