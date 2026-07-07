"""E0/E3 sparsity-attribution harness (P7-P0.2) — hermetic units: no boto3, no S3, no model calls.

Pins the Scan pagination, the intent gate (numbers_only is never 'sparse'), the evidence-kind source
counting, the dominant-first bucket assignment (dark > unchunked > absence), the dark-reason
sub-condition split, the graph_version honesty flag, and the planner `driver_legs` instrumentation.
"""
from __future__ import annotations

import json

from leviathan.causal import schema as cs
from leviathan.graphrag import e0_harness as e0
from leviathan.graphrag import graph as g


def _graph():
    c = cs.CausalContract(
        contract="corn_cbot",
        drivers=[cs.Driver(id="drought", type="hazard", sign="+", mechanism="m"),
                 cs.Driver(id="excess_rain", type="hazard", sign="-", mechanism="m"),
                 cs.Driver(id="ghost_leg", type="hazard", sign="+", mechanism="m")])
    return g.CausalGraph({"corn_cbot": c}, silver=set(), version="gv123456789a")


BACKED = {"drought", "ghost_leg"}                       # excess_rain unbacked; ghost_leg backed but no slice


def _slice_for(did):
    return {"drought": "drought"}.get(did)              # only drought resolves to a slice file


def _turn(intent="reasoning", sources=None, contract="corn_cbot", gv="gv123456789a"):
    return {"question": "q", "intent": intent, "contract": contract, "asof": "2026-06-01",
            "sources": sources if sources is not None else [], "graph_version": gv, "ts": "t"}


# ── enumeration: raw Scan with pagination ────────────────────────────────────────────────────────────
class _FakeDb:
    def __init__(self):
        t1 = {"pk": {"S": "user#u1"}, "sk": {"S": "turn#th#1"},
              "body": {"S": json.dumps(_turn())}}
        t2 = {"pk": {"S": "user#u2"}, "sk": {"S": "turn#th#2"},
              "body": {"S": json.dumps(_turn(intent="numbers_only"))}}
        bad = {"pk": {"S": "user#u3"}, "sk": {"S": "turn#th#3"}, "body": {"S": "{not json"}}
        self.pages = [{"Items": [t1, bad], "LastEvaluatedKey": {"pk": {"S": "x"}}},
                      {"Items": [t2]}]
        self.calls = []

    def scan(self, **kw):
        self.calls.append(kw)
        return self.pages[len(self.calls) - 1]


def test_enumerate_turns_paginates_and_skips_malformed():
    db = _FakeDb()
    turns = e0.enumerate_turns(db, "tbl")
    assert len(turns) == 2                                        # bad-json item skipped, both pages read
    assert db.calls[1].get("ExclusiveStartKey")                   # pagination token carried
    assert turns[0]["_user"] == "u1" and turns[0]["_sk"] == "turn#th#1"


# ── the gates ────────────────────────────────────────────────────────────────────────────────────────
def test_keep_excludes_numbers_only_and_refused():
    assert e0.keep(_turn("reasoning")) and e0.keep(_turn("hybrid")) and e0.keep(_turn("live"))
    assert not e0.keep(_turn("numbers_only")) and not e0.keep(_turn("refused")) and not e0.keep(_turn(None))


def test_sparse_counts_evidence_kind_only():
    n = [{"kind": "number", "ref": "N1"}]
    ev1 = [{"kind": "evidence", "ref": "1"}]
    legacy = [{"ref": "1"}]                                       # pre-kind records count as evidence
    assert e0.is_sparse(_turn(sources=[])) and e0.is_sparse(_turn(sources=n))
    assert not e0.is_sparse(_turn(sources=ev1)) and not e0.is_sparse(_turn(sources=legacy))


# ── classification: dominant-first buckets + sub-conditions ─────────────────────────────────────────
def test_dark_legs_split_subconditions():
    legs = e0.dark_legs("corn_cbot", _graph(), backed=BACKED, slice_for=_slice_for)
    assert {(x["id"], x["reason"]) for x in legs} == {("excess_rain", "unbacked_id"), ("ghost_leg", "no_slice")}


def test_classify_dark_beats_unchunked_beats_absence():
    gr = _graph()
    dark = e0.classify(_turn(), gr, backed=BACKED, slice_for=_slice_for, uncached_count_fn=lambda c: 9,
                       current_graph_version="gv123456789a")
    assert dark["klass"] == "dark_routing" and len(dark["dark_driver_legs"]) == 2
    all_backed = {"drought", "excess_rain", "ghost_leg"}
    unchunk = e0.classify(_turn(), gr, backed=all_backed, slice_for=lambda d: d,
                          uncached_count_fn=lambda c: 9)
    assert unchunk["klass"] == "unchunked_doc" and unchunk["n_uncached_docs"] == 9
    absence = e0.classify(_turn(), gr, backed=all_backed, slice_for=lambda d: d,
                          uncached_count_fn=lambda c: 0)
    assert absence["klass"] == "genuine_absence"
    unknown = e0.classify(_turn(), gr, backed=all_backed, slice_for=lambda d: d)   # no corpus listing
    assert unknown["klass"] == "coverage_unknown"                 # never silently 'absence'
    assert e0.classify(_turn(contract=None), gr, backed=BACKED, slice_for=_slice_for)["klass"] == "unroutable"


def test_snapshot_buckets_and_graph_version_honesty():
    turns = [_turn(),                                              # sparse reasoning -> dark_routing
             _turn(sources=[{"kind": "evidence", "ref": "1"}]),    # cited -> not sparse
             _turn(intent="numbers_only"),                         # excluded by the intent gate
             _turn(gv="OLDGRAPH")]                                 # sparse + drifted graph -> flagged
    snap = e0.snapshot(turns, _graph(), backed=BACKED, slice_for=_slice_for,
                       uncached_count_fn=lambda c: 0, corpus_fingerprint="cf", label="E0")
    assert snap["n_turns_scanned"] == 4 and snap["n_kept"] == 3 and snap["n_sparse"] == 2
    assert snap["attribution"] == {"dark_routing": 2}
    assert snap["n_graph_version_mismatch"] == 1                  # the OLDGRAPH turn, flagged not mixed
    assert snap["basis"] == "as_of_current_config" and snap["corpus_fingerprint"] == "cf"


# ── planner instrumentation: trace.driver_legs is additive + reason-split ────────────────────────────
def test_ground_trace_reports_driver_legs():
    from leviathan.graphrag import planner as pl
    gr = _graph()
    sg = pl.grounded_subgraph("corn drought outlook", gr, embed=lambda ts: [[1.0, 0.0] for _ in ts],
                              route_fn=lambda q, g_: ["corn_cbot"])
    def fake_retrieve(query, node, k=5, asof=None, near=None):
        return [{"date": "2020-01-01", "source": "s", "text": "drought evidence"}] if "drought" in str(node) else []
    pl.ground(sg, "corn drought outlook", gr, retrieve=fake_retrieve,
              driver_slices=["drought", "ghost_leg"])             # hermetic: ids ARE the slice paths
    legs = {x["key"][2]: x for x in sg.trace["driver_legs"]}
    assert legs, "driver_legs missing from trace"
    if "excess_rain" in legs:                                     # unbacked -> dark with the right reason
        assert legs["excess_rain"]["dark"] and legs["excess_rain"]["dark_reason"] == "unbacked_id"
    assert not legs["drought"]["dark"] and legs["drought"]["n_evidence"] >= 1
