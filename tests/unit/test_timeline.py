"""Event timeline + RCA-561 harness hardening — all mocked (no pg, no S3, no LLM).

Pins: episode clustering (gap split, junk dates), the PIT recount from per-episode prop dates
(a future prop can never inflate a shown count), the kill switch, ground() attachment, judge
parse-time coercion (the 561 mechanism made structurally impossible), judged-coverage lines,
and the numbers-answer verifier (the 0.107-vs-0.3636 fabrication class).
"""
from __future__ import annotations

import json

from leviathan.graphrag import timeline as tl


def test_cluster_splits_on_gap_and_skips_junk():
    eps = tl.cluster(["2021-06-01", "2021-07-15", "garbage", None, "1994-06-10", "1994-08-01"], gap_days=90)
    assert [(e["start"], e["end"]) for e in eps] == [("1994-06-10", "1994-08-01"), ("2021-06-01", "2021-07-15")]
    assert eps[1]["dates"] == ["2021-06-01", "2021-07-15"]


def test_episodes_for_recounts_pit_and_drops_future(tmp_path, monkeypatch):
    art = tmp_path / "episodes.json"
    art.write_text(json.dumps({"drivers/frost": [
        {"start": "1994-06-10", "end": "1994-08-01", "dates": ["1994-06-10", "1994-08-01"]},
        {"start": "2021-06-01", "end": "2021-08-20", "dates": ["2021-06-01", "2021-07-10", "2021-08-20"]},
    ]}), encoding="utf-8")
    monkeypatch.setenv("GRAPHRAG_TIMELINE_PATH", str(art))
    monkeypatch.setenv("GRAPHRAG_TIMELINE", "on")               # DEFAULT is now OFF — opt in to exercise
    tl.reset_cache()
    eps = tl.episodes_for("drivers/frost", "2021-07-15")
    by_start = {e["start"]: e for e in eps}
    assert by_start["2021-06-01"]["n"] == 2                      # the 2021-08-20 prop is NOT YET KNOWN
    assert by_start["2021-06-01"]["end"] == "2021-07-10"         # span recomputed from visible dates
    assert by_start["1994-06-10"]["n"] == 2
    assert tl.episodes_for("drivers/frost", "1990-01-01") == []  # nothing knowable yet
    assert tl.episodes_for("drivers/frost", None) == []          # no as-of -> no timeline
    monkeypatch.delenv("GRAPHRAG_TIMELINE")
    assert tl.episodes_for("drivers/frost", "2022-01-01") == []  # DEFAULT OFF: unset env -> no episodes
    monkeypatch.delenv("GRAPHRAG_TIMELINE_PATH")
    tl.reset_cache()


def test_receipt_attaches_in_window_prop_and_renders(monkeypatch, tmp_path):
    art = tmp_path / "episodes.json"
    art.write_text(json.dumps({"drivers/frost": [
        {"start": "2021-06-01", "end": "2021-08-20", "dates": ["2021-06-01", "2021-07-10", "2021-08-20"]}]}),
        encoding="utf-8")
    monkeypatch.setenv("GRAPHRAG_TIMELINE_PATH", str(art))
    monkeypatch.setenv("GRAPHRAG_TIMELINE", "on")
    tl.reset_cache()
    ev = [{"date": "2021-07-10", "text": "A damaging frost hit southern Minas Gerais coffee."},
          {"date": "2025-01-01", "text": "out of window, must not be picked"}]
    eps = tl.episodes_for("drivers/frost", "2021-08-01", evidence=ev)
    r = eps[0]["receipt"]
    assert r and r["date"] == "2021-07-10" and "Minas Gerais" in r["text"]   # in-window prop is the receipt
    line = tl.render_line("frost", eps)
    assert "report TIMESTAMPS, not descriptions" in line and '2021-07-10: "A damaging frost' in line
    # F-I: no evidence -> the episode is KEPT (its n is a PIT recount, not a retrieval result) and the
    # missing receipt is STATED. A bare "(2 reports)" with no marker was the confabulation invitation.
    bare = tl.episodes_for("drivers/frost", "2021-08-01", evidence=[])
    assert bare[0]["receipt"] is None and bare[0]["n"] == 2
    bare_line = tl.render_line("frost", bare)
    assert tl._NO_RECEIPT in bare_line and "do not narrate" in bare_line
    assert "(2 reports)" not in bare_line                            # never a naked count
    monkeypatch.delenv("GRAPHRAG_TIMELINE")
    monkeypatch.delenv("GRAPHRAG_TIMELINE_PATH")
    tl.reset_cache()


def test_derive_with_fake_query_fn_and_render():
    eps = tl.derive(query_fn=lambda sql: [
        {"node": "drivers/frost", "d": "2021-06-01"}, {"node": "drivers/frost", "d": "2021-07-01"},
        {"node": "arabica_coffee", "d": "1994-06-10"}])
    assert set(eps) == {"drivers/frost", "arabica_coffee"} and len(eps["drivers/frost"]) == 1
    line = tl.render_line("frost", [{"start": "2021-06-01", "end": "2021-07-01", "n": 2, "receipt": None}])
    # R3.1: the noun is "report dates", not "reports" -- `n` counts DISTINCT PROP DATES (cluster() builds
    # each episode from a set of dates), and the corroboration floor is a threshold on this very number,
    # so a wrong noun has the prompt and the threshold disagreeing about what was counted.
    assert "DATED EPISODES for frost" in line and "2021-06..2021-07 (2 report dates; " in line
    assert tl._NO_RECEIPT in line                                    # F-I marker, never a naked count


def test_ground_attaches_pit_episodes(tmp_path, monkeypatch):
    from leviathan.causal import schema as cs
    from leviathan.graphrag import graph as g
    from leviathan.graphrag import planner as pl
    art = tmp_path / "episodes.json"
    # THREE dates, two of them pre-asof. R3 (2026-08-01) added the corroboration floor
    # (serving.timeline.min_props, default 2), so the old two-date fixture recounted to n=1 at this
    # as-of and was suppressed -- which tested the floor, not the attachment this test is about. The
    # PIT assertion is unchanged in kind: the 2021-08-20 prop is still invisible at asof 2021-07-01.
    art.write_text(json.dumps({"drivers/frost": [
        {"start": "2021-06-01", "end": "2021-08-20",
         "dates": ["2021-06-01", "2021-06-20", "2021-08-20"]}]}), encoding="utf-8")
    monkeypatch.setenv("GRAPHRAG_TIMELINE_PATH", str(art))
    monkeypatch.setenv("GRAPHRAG_TIMELINE", "on")
    tl.reset_cache()
    c = cs.CausalContract(contract="arabica_coffee", aliases=[], drivers=[
        cs.Driver(id="frost", type="hazard", sign="+", mechanism="frost kills trees")])
    graph = g.CausalGraph({"arabica_coffee": c}, silver=set())
    sg = pl.grounded_subgraph("frost coffee", graph, embed=lambda xs: [[1.0, 0.0] for _ in xs],
                              route_fn=lambda q, gr: ["arabica_coffee"])
    ev = [{"date": "2021-06-05", "source": "gain", "source_key": "s3://x", "text": "frost report"}]
    pl.ground(sg, "frost coffee", graph, retrieve=lambda q, node, *, k, asof=None, near=None: list(ev),
              asof="2021-07-01", driver_slices={"frost"})
    frost = next(n for n in sg.nodes if n.id == "frost")
    assert frost.episodes and frost.episodes[0]["n"] == 2        # only the pre-asof props count
    assert frost.episodes[0]["end"] == "2021-06-20"              # span recomputed from visible dates
    # GATE: a node with NO evidence gets NO episode line even though the artifact has episodes
    sg2 = pl.grounded_subgraph("frost coffee", graph, embed=lambda xs: [[1.0, 0.0] for _ in xs],
                               route_fn=lambda q, gr: ["arabica_coffee"])
    pl.ground(sg2, "frost coffee", graph, retrieve=lambda q, node, *, k, asof=None, near=None: [],
              asof="2021-07-01", driver_slices={"frost"})
    assert not next(n for n in sg2.nodes if n.id == "frost").episodes
    monkeypatch.delenv("GRAPHRAG_TIMELINE")
    monkeypatch.delenv("GRAPHRAG_TIMELINE_PATH")
    tl.reset_cache()


# ── RCA-561 hardening ──────────────────────────────────────────────────────────────────────────────
def test_judge_coerces_string_hallucinations_to_one_item():
    from leviathan.graphrag import eval as gev

    def fake_call(client, sys_blocks, user, *, model, max_tokens, tool):
        return {"usefulness": 4, "hallucinations": "one long prose string pretending to be a list",
                "gaps": ["a", "b"] + [f"g{i}" for i in range(20)], "verdict": "v"}, None
    j = gev.judge({"question": "q"}, {"answer": "a", "evidence": [], "number_calls": []}, call=fake_call)
    assert j["hallucinations"] == ["one long prose string pretending to be a list"]   # 1 item, NOT 46 chars
    assert len(j["gaps"]) == 16                                   # clipped


def test_convo_report_prints_judged_coverage():
    from leviathan.graphrag import eval as gev
    rows = [{"convo": "c1", "turn": i, "spec": {"q": f"q{i}"}, "mech": {},
             "out": {"intent": "reasoning", "contracts": ["x"], "asof": "2024-01-01", "trace": {}},
             "usage": {"read": 0, "input": 1, "output": 1}, "secs": 1.0,
             "judge": ({"usefulness": 4, "continuity": 4, "point_in_time": 4, "grounding": 4,
                        "convexity": 4, "hallucinations": [], "gaps": [], "verdict": "v"} if i == 0 else None)}
            for i in range(3)]
    md = gev.convo_report(rows, model="m")
    assert "judged 1/3 turns" in md and "FAILED" in md


def test_numbers_answer_verifier_flags_the_citv2b_fabrication():
    from leviathan.graphrag import orchestrator as orch
    calls = [{"query": {}, "rows": [{"value": "0.3636"}]}]
    bad = orch._verify_numbers_answer("The current stocks-to-use is 0.107.", calls)
    assert bad["mismatched"] == 1 and bad["mismatch_values"] == [0.107]
    ok = orch._verify_numbers_answer("Stocks-to-use is 0.3636 (36.4% of use).", calls)
    assert ok["mismatched"] == 0                                  # exact + percent-scale both match
    yrs = orch._verify_numbers_answer("The 2012 figure was 0.3636.", calls)
    assert yrs["mismatched"] == 0                                 # bare years are not 'stated values'
