"""Retrieval telemetry (Phase 7 P3 / W1.4) — hermetic, synthetic, zero-spend, PIT-safe.

The module is a COUNT-ONLY runtime signal: record() folds a turn's driver legs into an in-memory per-slice
counter of plain ints, flush() emits those ints to S3 (+ a local mirror), and triage() joins them with an
e1_census doc into {unreachable | reachable-never-asked | used}. These tests pin the counting arithmetic,
the PIT firewall (NO text ever reaches the counter or the flushed JSON, even when a leg dict carries it),
the flush/no-op contract (mock S3 + local tmp), the reporter buckets, and — the wiring test that matters —
that the planner.ground() hook calls record() WITHOUT perturbing the trace and never breaks the walk.

All fixtures are synthetic: tiny hand-built leg dicts + a two-driver causal graph with a fake keyword
embedder. No real DAG/slice IP, no S3, no Athena, no LLM. The in-memory counter is reset in try/finally in
every test that touches it, so a synthetic count never leaks into another test.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from leviathan.causal import schema as cs
from leviathan.graphrag import evidence as ev
from leviathan.graphrag import graph as g
from leviathan.graphrag import planner as pl
from leviathan.graphrag import retrieval_telemetry as rt

_FIXED = datetime(2026, 7, 7, 14, 30, 15, tzinfo=timezone.utc)   # -> 20260707T143015Z filename stamp


# ── record: counting arithmetic ───────────────────────────────────────────────────────────────────────
def test_record_counts_slices_and_strips_prefix():
    rt.reset()
    try:
        # frost: backed, has evidence -> retrieved; rain: dark -> dark; frost seen twice (two turns' legs)
        rt.record([{"slice": "drivers/frost", "n_evidence": 3, "dark": False},
                   {"slice": "drivers/rain", "n_evidence": 0, "dark": True}])
        rt.record([{"slice": "drivers/frost", "n_evidence": 1, "dark": False}])
        snap = rt.snapshot()
        assert set(snap) == {"frost", "rain"}                 # the drivers/ prefix is stripped to census-canonical
        assert snap["frost"] == {"legs": 2, "retrieved": 2, "dark": 0}
        assert snap["rain"] == {"legs": 1, "retrieved": 0, "dark": 1}
    finally:
        rt.reset()


def test_record_skips_sliceless_legs_and_empty_input():
    rt.reset()
    try:
        rt.record([])                                         # empty -> no-op, no keys
        rt.record(None)                                       # defensive: None -> no-op
        # an unbacked/no-slice serving leg (slice is None) has no per-slice key -> skipped, no crash
        rt.record([{"slice": None, "n_evidence": 0, "dark": True},
                   {"slice": "drivers/heat", "n_evidence": 2, "dark": False}])
        snap = rt.snapshot()
        assert set(snap) == {"heat"}                          # only the routed leg produced a key
        assert snap["heat"] == {"legs": 1, "retrieved": 1, "dark": 0}
    finally:
        rt.reset()


def test_record_dark_leg_with_slice_counts_dark_not_retrieved():
    # hermetic-test / dark-with-slice shape: the id IS its slice path but the leg is dark -> legs + dark,
    # never retrieved (dark legs never fetch, so n_evidence is 0 and the two counters stay disjoint).
    rt.reset()
    try:
        rt.record([{"slice": "drivers/lonely", "n_evidence": 0, "dark": True}])
        assert rt.snapshot()["lonely"] == {"legs": 1, "retrieved": 0, "dark": 1}
    finally:
        rt.reset()


# ── PIT firewall: no text ever enters the counter or the flush ────────────────────────────────────────
def test_pit_counter_holds_only_int_counts_no_text():
    rt.reset()
    try:
        # legs that CARRY evidence text/source (as a real trace leg might) — record must read only the
        # three scalar fields and drop everything else. This is the firewall assertion.
        rt.record([{"key": ["driver", "arabica", "frost"], "slice": "drivers/frost", "n_evidence": 2,
                    "dark": False, "text": "SECRET PROP TEXT frost -8%", "source": "GAIN",
                    "source_key": "s3://secret", "date": "2021-07-20"},
                   {"slice": "drivers/rain", "n_evidence": 0, "dark": True, "text": "ANOTHER SECRET"}])
        snap = rt.snapshot()
        # structure: only str slice keys -> dicts of the three int fields, nothing else
        for key, val in snap.items():
            assert isinstance(key, str)
            assert set(val) == {"legs", "retrieved", "dark"}
            assert all(isinstance(x, int) for x in val.values())
        # content: no leaked text/source anywhere in the serialized counter
        blob = json.dumps(snap)
        for leak in ("SECRET", "GAIN", "s3://secret", "2021-07-20", "text", "source"):
            assert leak not in blob
    finally:
        rt.reset()


# ── flush: count-only durable emission (mock S3 + local mirror) ───────────────────────────────────────
class _CapS3:
    """A fake boto3 s3 client that captures put_object bodies (no network)."""

    def __init__(self):
        self.puts = []

    def put_object(self, *, Bucket, Key, Body):
        self.puts.append({"Bucket": Bucket, "Key": Key, "Body": Body})


def test_flush_writes_count_only_json_local_and_s3(tmp_path, monkeypatch):
    cap = _CapS3()
    monkeypatch.setattr(rt, "_OUT", tmp_path / "eval")
    monkeypatch.setattr(ev, "_evid_s3", lambda: "s3://bkt/graphrag/evidence/")
    monkeypatch.setattr("boto3.client", lambda svc, *a, **k: cap, raising=False)
    rt.reset()
    try:
        rt.record([{"slice": "drivers/frost", "n_evidence": 2, "dark": False, "text": "SECRET"},
                   {"slice": "drivers/rain", "n_evidence": 0, "dark": True}])
        path = rt.flush(now=_FIXED)

        # local mirror written at the UTC-stamped path
        assert path is not None and path.exists()
        assert path.name == "20260707T143015Z.json"
        assert path.parent.name == "retrieval_counts"
        body = path.read_text(encoding="utf-8")

        # S3 got the SAME bytes at eval/retrieval_counts/<stamp>.json
        assert len(cap.puts) == 1
        put = cap.puts[0]
        assert put["Bucket"] == "bkt"
        assert put["Key"] == "graphrag/evidence/eval/retrieval_counts/20260707T143015Z.json"
        assert put["Body"] == body.encode("utf-8")

        # count-only doc: totals roll the ints, per-slice ints present, NO text leaked
        doc = json.loads(body)
        assert doc["kind"] == "retrieval_counts" and doc["generated_utc"] == _FIXED.isoformat()
        assert doc["n_slices"] == 2
        assert doc["totals"] == {"legs": 2, "retrieved": 1, "dark": 1}
        assert doc["counts"]["frost"] == {"legs": 1, "retrieved": 1, "dark": 0}
        assert "SECRET" not in body and "text" not in body

        # counter reset after a successful flush -> windows are independent
        assert rt.snapshot() == {}
    finally:
        rt.reset()


def test_flush_noop_when_evidence_s3_unset(tmp_path, monkeypatch):
    cap = _CapS3()
    monkeypatch.setattr(rt, "_OUT", tmp_path / "eval")
    monkeypatch.setattr(ev, "_evid_s3", lambda: None)         # no sink configured
    monkeypatch.setattr("boto3.client", lambda svc, *a, **k: cap, raising=False)
    rt.reset()
    try:
        rt.record([{"slice": "drivers/frost", "n_evidence": 1, "dark": False}])
        assert rt.flush(now=_FIXED) is None                   # no-op return
        assert cap.puts == []                                 # never touched S3
        assert not (tmp_path / "eval" / "retrieval_counts").exists()   # no local trail
        assert rt.snapshot() == {"frost": {"legs": 1, "retrieved": 1, "dark": 0}}   # counter preserved
    finally:
        rt.reset()


def test_flush_noop_on_empty_counter(tmp_path, monkeypatch):
    cap = _CapS3()
    monkeypatch.setattr(rt, "_OUT", tmp_path / "eval")
    monkeypatch.setattr(ev, "_evid_s3", lambda: "s3://bkt/pfx/")
    monkeypatch.setattr("boto3.client", lambda svc, *a, **k: cap, raising=False)
    rt.reset()
    try:
        assert rt.flush(now=_FIXED) is None                   # nothing recorded -> no empty artifact
        assert cap.puts == []
    finally:
        rt.reset()


def test_flush_print_line_is_ascii(tmp_path, monkeypatch, capsys):
    # the flush stdout line must be cp1252-safe (Windows console) -> ASCII-only.
    monkeypatch.setattr(rt, "_OUT", tmp_path / "eval")
    monkeypatch.setattr(ev, "_evid_s3", lambda: "s3://bkt/pfx/")
    monkeypatch.setattr("boto3.client", lambda svc, *a, **k: _CapS3(), raising=False)
    rt.reset()
    try:
        rt.record([{"slice": "drivers/frost", "n_evidence": 1, "dark": False}])
        rt.flush(now=_FIXED)
        capsys.readouterr().out.encode("ascii")               # raises if any non-ASCII reached stdout
    finally:
        rt.reset()


# ── triage: census x counts join ──────────────────────────────────────────────────────────────────────
def _census(slices):
    return {"census": "E1_darkness", "slices": slices}


def test_triage_buckets_slices_by_reachability_and_use():
    census = _census([
        {"slice": "frost", "n_dag_ids": 1, "n_routed_props": 100, "consumed": True, "orphan_kind": None},
        {"slice": "el_nino", "n_dag_ids": 1, "n_routed_props": 0, "consumed": False, "orphan_kind": "keep"},
        {"slice": "thin", "n_dag_ids": 2, "n_routed_props": 3, "consumed": True, "orphan_kind": None},
        {"slice": "dead", "n_dag_ids": 0, "n_routed_props": 5, "consumed": False, "orphan_kind": "retire"},
    ])
    counts = {"frost": {"legs": 3, "retrieved": 2, "dark": 0},     # retrieved -> used
              "thin": {"legs": 1, "retrieved": 0, "dark": 1},      # reachable, asked, but 0 evidence -> never-asked
              "mystery": {"legs": 1, "retrieved": 1, "dark": 0}}   # in counts, not in census -> used via union
    rep = rt.triage(counts, census)
    by = {s["slice"]: s for s in rep["slices"]}

    assert by["frost"]["state"] == rt.STATE_USED
    assert by["el_nino"]["state"] == rt.STATE_NEVER            # routed (keep orphan) but never surfaced evidence
    assert by["thin"]["state"] == rt.STATE_NEVER              # thin CONSUMED slice asked but empty -> E4 target
    assert by["dead"]["state"] == rt.STATE_UNREACHABLE        # retire orphan: nothing routes here
    assert by["mystery"]["state"] == rt.STATE_USED
    # census fields flow through for the sizing report; counter fields default to 0 for census-only slices
    assert by["el_nino"]["n_dag_ids"] == 1 and by["el_nino"]["legs"] == 0
    assert by["frost"]["n_routed_props"] == 100 and by["frost"]["retrieved"] == 2
    assert rep["by_state"] == {rt.STATE_USED: 2, rt.STATE_NEVER: 2, rt.STATE_UNREACHABLE: 1}


def test_triage_counts_only_key_absent_from_census_is_unreachable_when_unused():
    # a counter key the census never heard of, with no retrievals, falls to unreachable (not dropped).
    rep = rt.triage({"ghost": {"legs": 2, "retrieved": 0, "dark": 2}}, _census([]))
    assert rep["slices"][0]["state"] == rt.STATE_UNREACHABLE
    assert rep["by_state"] == {rt.STATE_UNREACHABLE: 1}


# ── planner hook: calls record() without perturbing the trace, never breaks the walk ──────────────────
_KW = ["frost", "rain"]


def _embed(texts):
    return [[1.0 if kw in t.lower() else 0.0 for kw in _KW] for t in texts]


def _d(id_, mech, **o):
    return cs.Driver(id=id_, type=o.pop("type", "hazard"), sign=o.pop("sign", "+"), mechanism=mech, **o)


def _graph():
    arabica = cs.CausalContract(
        contract="arabica", aliases=["arabica"],
        drivers=[_d("frost", "frost damage"),
                 _d("rain", "rain only", sign="-", type="climate_driver")])
    return g.CausalGraph({"arabica": arabica}, silver=set())


def _retrieve(query, slice_, *, k, asof=None, near=None):
    if slice_ == "drivers/frost":
        return [{"date": "2021-07-20", "source": "GAIN", "source_key": "s3://f", "text": "frost hit"}][:k]
    return []


def _walk():
    gr = _graph()
    sg = pl.grounded_subgraph("frost", gr, embed=_embed, route_fn=lambda q, graph: ["arabica"],
                              tau=0.0, depth=1, node_budget=10)
    return gr, sg


def test_planner_hook_records_real_legs_end_to_end():
    # drive the real ground() path (real record, real counter): frost is backed w/ evidence -> retrieved,
    # rain is unbacked (not in driver_slices) but its hermetic slice path exists -> a dark leg.
    gr, sg = _walk()
    rt.reset()
    try:
        pl.ground(sg, "frost", gr, retrieve=_retrieve, silver_lookup=None, driver_slices={"frost"})
        snap = rt.snapshot()
        assert snap["frost"] == {"legs": 1, "retrieved": 1, "dark": 0}
        assert snap["rain"] == {"legs": 1, "retrieved": 0, "dark": 1}
    finally:
        rt.reset()


def test_planner_hook_passes_trace_legs_and_does_not_mutate_them(monkeypatch):
    gr, sg = _walk()
    seen = {}

    def spy(driver_legs):
        seen["arg"] = driver_legs                             # capture the exact object handed to record()

    monkeypatch.setattr(rt, "record", spy)
    pl.ground(sg, "frost", gr, retrieve=_retrieve, silver_lookup=None, driver_slices={"frost"})
    legs = sg.trace["driver_legs"]
    assert seen.get("arg") is legs                            # record got the trace's own list, by identity
    # the trace shape is exactly what the pre-telemetry planner produced (hook is read-only)
    by = {tuple(leg["key"]): leg for leg in legs}
    assert by[("driver", "arabica", "frost")]["n_evidence"] == 1
    assert by[("driver", "arabica", "frost")]["dark"] is False
    assert by[("driver", "arabica", "rain")]["dark"] is True


def test_planner_hook_never_breaks_the_walk(monkeypatch):
    # a telemetry bug must be swallowed by the guard: ground() completes and the trace is intact.
    gr, sg = _walk()

    def boom(_legs):
        raise RuntimeError("telemetry exploded")

    monkeypatch.setattr(rt, "record", boom)
    out = pl.ground(sg, "frost", gr, retrieve=_retrieve, silver_lookup=None, driver_slices={"frost"})
    assert out is sg                                          # ground still returned the subgraph
    assert "driver_legs" in sg.trace and isinstance(sg.fired_regimes, list)   # walk finished past the hook
