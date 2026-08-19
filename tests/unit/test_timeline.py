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


# ── D-EC P0 / task #67: THE RECEIPT AXIS ───────────────────────────────────────────────────────────
# The measured defect: cluster() builds the window from COALESCE(event_date, date) while episodes_for()
# matched a receipt on h["date"], the publication date. 583 of 1,118 scored episodes (52.1%) therefore
# had ZERO contributing prop whose PUBLICATION date landed inside their own window -- unreceiptable no
# matter how good retrieval got. These pin the reconstruction, both directions, and the PIT floor.
def _one_window(tmp_path, monkeypatch, dates=("1979-06-01", "1979-09-01", "1980-02-01")):
    """One artifact holding a single event-dated window for `drivers/frost`, kill-switch ON."""
    art = tmp_path / "episodes.json"
    art.write_text(json.dumps({"drivers/frost": [
        {"start": dates[0], "end": dates[-1], "dates": list(dates)}]}), encoding="utf-8")
    monkeypatch.setenv("GRAPHRAG_TIMELINE_PATH", str(art))
    monkeypatch.setenv("GRAPHRAG_TIMELINE", "on")
    tl.reset_cache()


def test_receipt_matches_on_the_window_axis_not_the_publication_axis(tmp_path, monkeypatch):
    _one_window(tmp_path, monkeypatch)
    # THE DEFECT, RECONSTRUCTED: a 2020 retrospective narrating 1979. Its publication date is 40 years
    # outside the window; its event date -- the axis the window was clustered on -- is inside it. Before
    # the fix this episode rendered _NO_RECEIPT with the citable item sitting in the same prompt.
    ev = [{"date": "2020-01-15", "event_date": "1979-07-04",
           "text": "The 1979 harvest was cut by a July freeze across the belt."}]
    eps = tl.episodes_for("drivers/frost", "2026-01-01", evidence=ev)
    r = eps[0]["receipt"]
    assert r is not None                                             # WAS None on the publication axis
    # THE CONTRACT SHAPE IS UNMOVED: `date` is still the PUBLICATION date, because answer._receipt_item
    # joins the receipt back to this turn's evidence on it and an unmatched receipt declines the whole
    # D-DT-1 scaffold. The in-window date rides BESIDE it, only because the two disagree.
    assert r["date"] == "2020-01-15" and r["event_date"] == "1979-07-04"
    assert "July freeze" in r["text"]
    line = tl.render_line("frost", eps)
    assert 'e.g. 1979-07-04 (reported 2020-01-15): "The 1979 harvest' in line
    assert tl._NO_RECEIPT not in line
    monkeypatch.delenv("GRAPHRAG_TIMELINE")
    monkeypatch.delenv("GRAPHRAG_TIMELINE_PATH")
    tl.reset_cache()


def test_receipt_axis_still_refuses_the_prop_that_is_in_NEITHER(tmp_path, monkeypatch):
    _one_window(tmp_path, monkeypatch)
    # Neither axis lands inside 1979-06..1980-02, so the window stays honestly receipt-less. The axis fix
    # is not a widening: absence stated is still the answer when the corpus holds nothing for the window.
    ev = [{"date": "2020-01-15", "event_date": "2014-03-02", "text": "A 2014 frost, narrated in 2020."},
          {"date": "1990-05-05", "text": "A 1990 report with no event date at all."}]
    eps = tl.episodes_for("drivers/frost", "2026-01-01", evidence=ev)
    assert eps[0]["receipt"] is None
    assert tl._NO_RECEIPT in tl.render_line("frost", eps)
    monkeypatch.delenv("GRAPHRAG_TIMELINE")
    monkeypatch.delenv("GRAPHRAG_TIMELINE_PATH")
    tl.reset_cache()


def test_receipt_axis_drops_the_publication_date_coincidence(tmp_path, monkeypatch):
    _one_window(tmp_path, monkeypatch)
    # THE INVERSE, and the reason this is a correction rather than a widening. A document PUBLISHED
    # inside the window that is about something else entirely used to receipt it -- the old axis could
    # not tell "published during" from "about". It no longer can be quoted as backing for this window.
    ev = [{"date": "1979-08-01", "event_date": "2011-05-05", "text": "About a 2011 event, published 1979."}]
    eps = tl.episodes_for("drivers/frost", "2026-01-01", evidence=ev)
    assert eps[0]["receipt"] is None
    monkeypatch.delenv("GRAPHRAG_TIMELINE")
    monkeypatch.delenv("GRAPHRAG_TIMELINE_PATH")
    tl.reset_cache()


def test_receipt_axis_is_pit_safe_on_both_axes(tmp_path, monkeypatch):
    _one_window(tmp_path, monkeypatch, dates=("2021-06-01", "2021-07-10", "2025-08-20"))
    # PIT: `vis` clamps the window to prop dates <= asof, so `end <= asof` ALWAYS -- and a prop can only
    # receipt a window it is INSIDE. An item dated after the as-of on either axis is therefore
    # unreachable at any axis, which is the whole leakage argument: matching on event_date changes WHICH
    # admitted row is pointed at, never WHETHER a row is admitted (retrieval filters date <= asof
    # upstream and is untouched here).
    ev = [{"date": "2025-08-20", "event_date": "2025-08-19", "text": "post-asof on both axes"},
          {"date": "2021-07-01", "event_date": "2025-08-15", "text": "published pre-asof, EVENT post-asof"}]
    eps = tl.episodes_for("drivers/frost", "2021-08-01", evidence=ev)
    assert eps[0]["end"] == "2021-07-10"                             # the 2025 prop date is not yet known
    assert eps[0]["receipt"] is None                                 # neither item can reach the window
    monkeypatch.delenv("GRAPHRAG_TIMELINE")
    monkeypatch.delenv("GRAPHRAG_TIMELINE_PATH")
    tl.reset_cache()


def test_axis_date_coalesces_on_presence_exactly_like_derive():
    # COALESCE takes event_date whenever it is NON-NULL and cluster() then drops whatever does not parse,
    # so a present-but-unparseable event_date leaves the prop with NO position on the axis -- it built no
    # window, so it may receipt none. Absent/blank falls through to the publication date.
    assert tl.axis_date({"date": "2020-01-15", "event_date": "1979-07-04"}) == "1979-07-04"
    assert tl.axis_date({"date": "2020-01-15"}) == "2020-01-15"
    assert tl.axis_date({"date": "2020-01-15", "event_date": None}) == "2020-01-15"
    assert tl.axis_date({"date": "2020-01-15", "event_date": ""}) == "2020-01-15"
    assert tl.axis_date({"date": "2020-01-15", "event_date": "1979-06"}) == ""      # month grain: no position
    assert tl.axis_date({"date": "2020-01-15", "event_date": "circa 1979"}) == ""
    assert tl.axis_date({"date": None}) == "" and tl.axis_date(None) == ""


def test_receipt_render_is_byte_identical_when_the_axes_agree():
    # A corpus with no recovered event dates renders exactly the pre-fix line: one date, no parenthetical.
    eps = [{"start": "2021-06-01", "end": "2021-07-10", "n": 2,
            "receipt": {"date": "2021-07-10", "text": "A damaging frost hit southern Minas Gerais."}}]
    assert '; e.g. 2021-07-10: "A damaging frost' in tl.render_line("frost", eps)
    assert "(reported" not in tl.render_line("frost", eps)


def test_event_dated_receipt_still_resolves_through_the_scaffold_join(tmp_path, monkeypatch):
    # THE DOWNSTREAM PIN. answer._receipt_item recovers the turn's OWN evidence row from the receipt by
    # (date, text prefix) and a MISS declines the entire D-DT-1 episode scaffold -- so re-pointing
    # receipt["date"] at the event axis would have traded a 52% unreceiptable rate for a 100% decline.
    from leviathan.graphrag import answer as ans
    _one_window(tmp_path, monkeypatch)
    ev = [{"date": "2020-01-15", "event_date": "1979-07-04", "source": "wb_cmo_outlook",
           "source_key": "s3://text/wb_cmo_outlook/2020-01-15/document.json",
           "text": "The 1979 harvest was cut by a July freeze across the belt."}]
    eps = tl.episodes_for("drivers/frost", "2026-01-01", evidence=ev)
    item = ans._receipt_item(eps[0]["receipt"], ev)
    assert item is not None and item["source_key"].endswith("document.json")
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
    # D-DV-1b: episodes are stamped AFTER _dedup_and_cap, so this fixture must give each node its OWN
    # prop. It used to hand every node the same source_key, which the cross-node dedup attributed to the
    # shallowest (contract) node -- leaving `frost` with zero evidence and episodes anyway. That state IS
    # the orphaned-receipt bug (an episode line quoting receipts absent from the verifier's evidence
    # list), and this test was pinning it. The attachment assertion below is unchanged in kind.
    def _ev_for(node):
        return [{"date": "2021-06-05", "source": "gain", "source_key": f"s3://{node}",
                 "text": f"frost report for {node}"}]
    pl.ground(sg, "frost coffee", graph, retrieve=lambda q, node, *, k, asof=None, near=None: _ev_for(node),
              asof="2021-07-01", driver_slices={"frost"})
    frost = next(n for n in sg.nodes if n.id == "frost")
    assert frost.evidence                                        # kept its OWN prop through the cap
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
