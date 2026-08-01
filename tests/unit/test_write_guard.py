"""G1 write-path guards + the per-pass run manifest — hermetic, local-store only, zero S3, zero spend.

Every case here is calibrated against the ONE measured event the wave plan has: the 2026-07-20 promote, where
12,536 driver prop rows went out and 11,903 came in (net -633) across a layer nobody could attribute for two
weeks, because all three wholesale-write seams were unguarded and no run record existed anywhere.

The guard's contract, and what each test pins:
  * a population DROP >= write_guard.SLICE_DROP_REFUSE refuses the pass; below it, it warns (never silent)
  * an EMPTY slice over a non-empty one refuses unconditionally (the evidence_batch.py:433 mirror)
  * a date-span endpoint moving INWARD refuses; outward only warns (the `potash` -25y class)
  * --allow-churn takes a MAGNITUDE, and only that magnitude
  * refusal is ATOMIC and happens BEFORE any write and BEFORE any embed
"""
from __future__ import annotations

import json

import pytest
from leviathan.graphrag import evidence as ev
from leviathan.graphrag import extract as ex
from leviathan.graphrag import write_guard as wg


def _rec(date, key="k", rid="i", event_date=None):
    return {"id": rid, "date": date, "source": "WB", "source_key": key, "text": "t" * 40,
            "event_date": event_date}


def _prior(n=None, nbytes=1000, span=None, exact=True, source="test"):
    return {"bytes": nbytes, "n": n, "exact": exact, "span": span, "source": source}


# ── span tuples ───────────────────────────────────────────────────────────────────────────────────────
def test_span_tuple_reports_all_five_keys_and_skips_unset_event_dates():
    recs = [_rec("2020-01-01"), _rec("2024-06-30", event_date="2019-03-02"), _rec("2022-02-02")]
    assert wg.span_tuple(recs) == {"n": 3, "date_min": "2020-01-01", "date_max": "2024-06-30",
                                   "event_date_min": "2019-03-02", "event_date_max": "2019-03-02"}
    # an absent endpoint is an explicit None, never a missing key -- a diff must never have to tell
    # "no props" apart from "no field".
    assert wg.span_tuple([]) == {"n": 0, "date_min": None, "date_max": None,
                                 "event_date_min": None, "event_date_max": None}


# ── the verdict ───────────────────────────────────────────────────────────────────────────────────────
def test_empty_over_nonempty_refuses():
    v = wg.evaluate({"metals": _prior(n=975)}, {"metals": wg.span_tuple([])}, layer="drivers")
    assert any("EMPTY slice" in r and "drivers/metals" in r for r in v["refusals"])
    assert any("LAYER population 975 -> 0" in r for r in v["refusals"])   # and the layer line escalates it


def test_ten_percent_drop_refuses_and_smaller_drop_only_warns():
    # `metals` at the promote: -263 props against a 975-prop survivor = -21%. Over the line.
    big = wg.evaluate({"metals": _prior(n=1238)}, {"metals": wg.span_tuple([_rec("2020-01-01")] * 975)},
                      layer="drivers")
    assert big["refusals"] and "21.2% drop" in big["refusals"][0]
    small = wg.evaluate({"x": _prior(n=100)}, {"x": wg.span_tuple([_rec("2020-01-01")] * 95)},
                        layer="drivers")
    assert small["refusals"] == [] and len(small["warns"]) == 1 and "5.0% drop" in small["warns"][0]


def test_growth_is_never_a_trip():
    v = wg.evaluate({"x": _prior(n=100)}, {"x": wg.span_tuple([_rec("2020-01-01")] * 200)}, layer="drivers")
    assert v["refusals"] == [] and v["warns"] == []


def test_allow_churn_takes_a_magnitude_and_only_that_magnitude():
    prior, after = {"x": _prior(n=1000)}, {"x": wg.span_tuple([_rec("2020-01-01")] * 700)}   # -30%
    assert wg.evaluate(prior, after, layer="drivers")["refusals"]                      # no declaration: refuse
    assert wg.evaluate(prior, after, layer="drivers", allow_churn=0.35)["refusals"] == []   # declared 35%: ok
    assert wg.evaluate(prior, after, layer="drivers", allow_churn=0.25)["refusals"]         # declared 25%: no
    # the permitted drop is still RECORDED -- "expected" never means "invisible"
    assert any("30.0% drop" in w for w in wg.evaluate(prior, after, layer="drivers",
                                                      allow_churn=0.35)["warns"])


def test_span_contraction_refuses_and_expansion_warns():
    before = {"n": 10, "date_min": "1960-01-01", "date_max": "2026-01-01",
              "event_date_min": "1960-01-01", "event_date_max": "2026-01-01"}
    # `fertilizer` lost 28 years of event_date start at the promote while the backlog said "none lost span".
    contracted = wg.evaluate({"fertilizer": _prior(n=10, span=before)},
                             {"fertilizer": {"n": 10, "date_min": "1960-01-01", "date_max": "2026-01-01",
                                             "event_date_min": "1988-01-01",
                                             "event_date_max": "2026-01-01"}}, layer="drivers")
    assert len(contracted["refusals"]) == 1 and "event_date_min 1960-01-01 -> 1988-01-01" in contracted["refusals"][0]
    expanded = wg.evaluate({"x": _prior(n=10, span=before)},
                           {"x": {"n": 10, "date_min": "1950-01-01", "date_max": "2026-01-01",
                                  "event_date_min": "1960-01-01", "event_date_max": "2026-01-01"}},
                           layer="drivers")
    assert expanded["refusals"] == [] and any("span grew" in w for w in expanded["warns"])


def test_no_span_baseline_means_no_span_verdict_not_a_pass():
    # prior["span"] is None when the only baseline is a byte LIST. The guard must stay SILENT rather than
    # imply "no endpoint moved" -- that silence is what the manifest's prior_source field explains.
    v = wg.evaluate({"x": _prior(n=10, span=None, exact=False)},
                    {"x": wg.span_tuple([_rec("2020-01-01")] * 10)}, layer="drivers")
    assert v["refusals"] == [] and v["warns"] == []


def test_layer_line_counts_untouched_slices_on_both_sides():
    # A pass that rewrites ONE slice must not read as a layer-wide collapse just because it did not touch
    # the other 100.
    prior = {"a": _prior(n=100), "b": _prior(n=900)}
    v = wg.evaluate(prior, {"a": wg.span_tuple([_rec("2020-01-01")] * 100)}, layer="drivers")
    assert v["layer_before_n"] == 1000 and v["layer_after_n"] == 1000 and v["refusals"] == []


# ── prior resolution ──────────────────────────────────────────────────────────────────────────────────
def _seed_slice(tmp_path, name, recs):
    d = tmp_path / "drivers"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.jsonl").write_text("\n".join(json.dumps(r) for r in recs), encoding="utf-8")


def test_resolve_prior_estimates_the_count_from_size_and_the_first_line(tmp_path, monkeypatch):
    monkeypatch.setattr(ev, "_EVID_DIR", tmp_path)
    monkeypatch.setattr(ex, "_CFG", tmp_path / "cfg")
    _seed_slice(tmp_path, "freight", [_rec("2020-01-01", rid=f"i{i}") for i in range(20)])
    prior = wg.resolve_prior("drivers/", ["freight"])["freight"]
    assert prior["exact"] is False and prior["n"] == 20 and "first-line estimate" in prior["source"]


def test_resolve_prior_prefers_an_exact_run_manifest_and_distrusts_a_stale_one(tmp_path, monkeypatch):
    monkeypatch.setattr(ev, "_EVID_DIR", tmp_path)
    cfg = tmp_path / "cfg"
    monkeypatch.setattr(ex, "_CFG", cfg)
    _seed_slice(tmp_path, "freight", [_rec("2020-01-01", rid=f"i{i}") for i in range(20)])
    nbytes = (tmp_path / "drivers" / "freight.jsonl").stat().st_size
    (cfg / "eval").mkdir(parents=True)
    span = {"n": 7, "date_min": "1999-01-01", "date_max": "2020-01-01",
            "event_date_min": None, "event_date_max": None}

    def _manifest(after_bytes):
        (cfg / "eval" / "write_manifest_x_20260801T000000Z.json").write_text(json.dumps(
            {"slices": {"drivers": {"freight": {"after_bytes": after_bytes, "after_n": 7,
                                                "after_span": span}}}}), encoding="utf-8")

    _manifest(nbytes)                                          # manifest agrees with the store -> EXACT
    fresh = wg.resolve_prior("drivers/", ["freight"], layer="drivers")["freight"]
    assert fresh["exact"] is True and fresh["n"] == 7 and fresh["span"] == span

    _manifest(nbytes + 1)   # a later UNGUARDED write moved the bytes: the mirror is no longer a baseline
    stale = wg.resolve_prior("drivers/", ["freight"], layer="drivers")["freight"]
    assert stale["exact"] is False and stale["n"] == 20 and "STALE" in stale["source"]


def test_absent_slice_is_never_a_drop(tmp_path, monkeypatch):
    monkeypatch.setattr(ev, "_EVID_DIR", tmp_path)
    monkeypatch.setattr(ex, "_CFG", tmp_path / "cfg")
    prior = wg.resolve_prior("drivers/", ["brand_new"])["brand_new"]
    assert prior == {"bytes": 0, "n": 0, "exact": True, "span": None, "source": "absent"}


# ── atomicity + the manifest ──────────────────────────────────────────────────────────────────────────
def test_guarded_write_refuses_before_any_write_or_any_embed(tmp_path, monkeypatch):
    monkeypatch.setattr(ev, "_EVID_DIR", tmp_path)
    monkeypatch.setattr(ex, "_CFG", tmp_path / "cfg")
    _seed_slice(tmp_path, "big", [_rec("2020-01-01", rid=f"i{i}") for i in range(100)])
    _seed_slice(tmp_path, "ok", [_rec("2020-01-01", rid=f"j{i}") for i in range(10)])
    before = {p.name: p.read_bytes() for p in (tmp_path / "drivers").glob("*.jsonl")}
    embedded, written = [], []

    def _payload(name):
        def _mk():
            embedded.append(name)                              # embedding is the expensive half: never paid
            return "x"
        return _mk

    records = {"big": [_rec("2020-01-01")] * 50, "ok": [_rec("2020-01-01")] * 12}
    with pytest.raises(wg.WriteRefused) as exc:
        wg.guarded_write("drivers", "drivers/", {n: _payload(n) for n in records}, records=records,
                         manifest=None, allow_churn=None,
                         write_fn=lambda node, body: written.append(node),
                         node_of=lambda n: f"drivers/{n}")
    assert embedded == [] and written == []                    # atomic: not one slice, not one embed
    assert {p.name: p.read_bytes() for p in (tmp_path / "drivers").glob("*.jsonl")} == before
    assert any("--allow-churn" in line for line in exc.value.lines)      # the message names the way out


def test_run_manifest_records_the_pass_and_states_what_it_cannot_see(tmp_path, monkeypatch):
    monkeypatch.setattr(ev, "_EVID_DIR", tmp_path)
    monkeypatch.setattr(ex, "_CFG", tmp_path / "cfg")
    monkeypatch.delenv("EVIDENCE_S3", raising=False)
    _seed_slice(tmp_path, "freight", [_rec("2020-01-01", rid=f"i{i}") for i in range(10)])
    mf = wg.RunManifest("unit", chunk_version="abc-20260801", allow_churn=None)
    records = {"freight": [_rec("2021-01-01", rid="a"), _rec("2020-06-06", rid="b")] * 6}
    n = wg.guarded_write("drivers", "drivers/", {"freight": lambda: "line"}, records=records, manifest=mf,
                         allow_churn=0.99, write_fn=lambda node, body: None,
                         node_of=lambda n: f"drivers/{n}", truncated={"freight": 3})
    mf.record_docs(written=2, overwritten=1, vintage_transitions={"None -> abc-20260801": 1},
                   per_doc_delta={"s3://k": -4})
    path = mf.flush()
    doc = json.loads(open(path, encoding="utf-8").read())
    assert n == 12
    rec = doc["slices"]["drivers"]["freight"]
    assert rec["after_n"] == 12 and rec["truncated_n"] == 3 and rec["before_n"] == 10
    assert rec["after_span"]["date_min"] == "2020-06-06" and rec["after_span"]["date_max"] == "2021-01-01"
    assert rec["after_bytes"] == 4 and rec["prior_source"].startswith("size/first-line estimate")
    assert doc["chunk_version"] == "abc-20260801" and doc["docs"]["overwritten"] == 1
    assert doc["thresholds"]["slice_drop_refuse"] == wg.SLICE_DROP_REFUSE
    # The one thing this manifest must never let a reader infer: it is NET, not row-level churn. A frozen
    # count does not mean no rows moved (5,809 swapped behind four frozen 4000s at the promote).
    assert doc["layer_row_churn"] is None and "row SET" in doc["layer_row_churn_reason"]


# ── F1: plan/commit -- atomicity ACROSS layers, not just within one ────────────────────────────────────
def test_plan_write_evaluates_and_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(ev, "_EVID_DIR", tmp_path)
    monkeypatch.setattr(ex, "_CFG", tmp_path / "cfg")
    _seed_slice(tmp_path, "big", [_rec("2020-01-01", rid=f"i{i}") for i in range(100)])
    written = []
    plan = wg.plan_write("drivers", "drivers/", {"big": lambda: "x"},
                         records={"big": [_rec("2020-01-01")] * 50}, manifest=None, allow_churn=None,
                         write_fn=lambda node, body: written.append(node),
                         node_of=lambda n: f"drivers/{n}")
    assert written == []                                       # planning is not writing
    assert plan.refusals and "drop) [estimated prior]" in plan.refusals[0]   # the verdict is already known


def test_a_refusal_in_ANY_planned_layer_leaves_EVERY_layer_unwritten(tmp_path, monkeypatch):
    """F1 -- the finding. `_commodity_guarded_write` completed all 24 commodity writes (11,119,127,224 bytes)
    and only THEN did write_driver_slices evaluate its own guard and raise, so the module's "a refusal leaves
    the store byte-identical" held within a layer and nowhere else. The 2026-07-20 shape -- commodity fine,
    drivers collapse -- lands exactly there. Planning both first makes the promise true."""
    monkeypatch.setattr(ev, "_EVID_DIR", tmp_path)
    monkeypatch.setattr(ex, "_CFG", tmp_path / "cfg")
    (tmp_path / "corn.jsonl").write_bytes(b"prior-commodity")
    _seed_slice(tmp_path, "metals", [_rec("2020-01-01", rid=f"i{i}") for i in range(100)])
    before = {p.name: p.read_bytes() for p in tmp_path.rglob("*.jsonl")}
    written, embedded = [], []

    def _payload(name):
        def _mk():
            embedded.append(name)
            return "body"
        return _mk

    # commodity is HEALTHY (growth); drivers COLLAPSE. The old shape wrote commodity, then raised.
    commodity = wg.plan_write("commodity", "", {"corn": _payload("corn")},
                              records={"corn": [_rec("2020-01-01")] * 40}, manifest=None, allow_churn=None,
                              write_fn=lambda n, b: written.append(n), node_of=lambda n: n)
    drivers = wg.plan_write("drivers", "drivers/", {"metals": _payload("metals")},
                            records={"metals": [_rec("2020-01-01")] * 10}, manifest=None, allow_churn=None,
                            write_fn=lambda n, b: written.append(n), node_of=lambda n: f"drivers/{n}")
    assert commodity.refusals == [] and drivers.refusals                   # only ONE layer objects ...
    with pytest.raises(wg.WriteRefused) as exc:
        wg.raise_if_refused(commodity, drivers)                            # ... and BOTH are stopped
    assert written == [] and embedded == []
    assert {p.name: p.read_bytes() for p in tmp_path.rglob("*.jsonl")} == before
    assert any("nothing was written in ANY layer" in line for line in exc.value.lines)
    assert any("commodity" in line and "drivers" in line for line in exc.value.lines)


# ── F7: the newest manifest is the newest STAMP, not the highest LABEL ─────────────────────────────────
def test_newest_run_manifest_sorts_on_the_stamp_not_the_label(tmp_path, monkeypatch):
    """`sorted(...)[-1]` / `max(keys)` sort the LABEL first, so over retrieve_...T120000Z,
    rebuild_...T130000Z and run_20260701T010000Z both returned the `run_` one -- six months stale. Any
    --retrieve followed by a --rebuild baselined the next pass off the retrieve."""
    monkeypatch.setattr(ev, "_EVID_DIR", tmp_path)
    cfg = tmp_path / "cfg"
    monkeypatch.setattr(ex, "_CFG", cfg)
    (cfg / "eval").mkdir(parents=True)
    for name, tag in (("write_manifest_run_20260701T010000Z.json", "old"),
                      ("write_manifest_retrieve_20261231T120000Z.json", "mid"),
                      ("write_manifest_rebuild_20261231T130000Z.json", "newest")):
        (cfg / "eval" / name).write_text(json.dumps({"label": tag}), encoding="utf-8")
    doc, label = wg.newest_run_manifest()
    assert doc["label"] == "newest" and "rebuild" in label
    assert wg._manifest_stamp("write_manifest_retrieve_20261231T120000Z.json") == "20261231T120000Z"


# ── F15: --allow-churn 0 is not a churn declaration ────────────────────────────────────────────────────
def test_allow_churn_zero_does_not_disarm_the_span_guard():
    before = {"n": 10, "date_min": "1960-01-01", "date_max": "2026-01-01",
              "event_date_min": "1960-01-01", "event_date_max": "2026-01-01"}
    after = {"n": 10, "date_min": "1960-01-01", "date_max": "2026-01-01",
             "event_date_min": "1988-01-01", "event_date_max": "2026-01-01"}
    v = wg.evaluate({"fertilizer": _prior(n=10, span=before)}, {"fertilizer": after},
                    layer="drivers", allow_churn=0.0)
    assert any("span CONTRACTED" in r for r in v["refusals"])   # 0 declares NO churn, so it still refuses
    assert wg.evaluate({"fertilizer": _prior(n=10, span=before)}, {"fertilizer": after},
                       layer="drivers", allow_churn=0.5)["refusals"] == []      # a real magnitude downgrades


# ── F9: a slice in the store that the pass never wrote is NAMED ────────────────────────────────────────
def test_a_prior_only_slice_is_named_and_recorded(tmp_path, monkeypatch):
    """resolve_prior's docstring claimed the "terms deleted -> slice never rewritten -> stale file persists"
    case was VISIBLE. evaluate iterated `after`, so it produced no line, no warn and no manifest entry: the
    coffee_rust_crop 505->20 class tripped and the 505->gone class was silent."""
    monkeypatch.setattr(ev, "_EVID_DIR", tmp_path)
    monkeypatch.setattr(ex, "_CFG", tmp_path / "cfg")
    monkeypatch.delenv("EVIDENCE_S3", raising=False)
    _seed_slice(tmp_path, "deleted_terms_slice", [_rec("2020-01-01", rid=f"i{i}") for i in range(30)])
    _seed_slice(tmp_path, "freight", [_rec("2020-01-01", rid=f"j{i}") for i in range(10)])
    mf = wg.RunManifest("unit")
    wg.guarded_write("drivers", "drivers/", {"freight": lambda: "x"},
                     records={"freight": [_rec("2021-01-01")] * 12}, manifest=mf, allow_churn=None,
                     write_fn=lambda n, b: None, node_of=lambda n: f"drivers/{n}")
    assert mf.guard["drivers"]["prior_only"] == ["deleted_terms_slice"]
    assert any("NOT written by this pass" in w and "deleted_terms_slice" in w for w in mf.warnings)
    assert mf.unwritten["drivers"]["deleted_terms_slice"]["prior_n"] == 30
    # ... and it is NOT promoted into `slices`, which is what the next pass trusts as an EXACT baseline.
    assert "deleted_terms_slice" not in mf.slices["drivers"]


# ── F16: an unreadable prior is "not checked", never "checked and clean" ───────────────────────────────
def test_an_unmeasured_prior_is_reported_not_silently_skipped():
    v = wg.evaluate({"x": {"bytes": 900000, "n": None, "exact": False, "span": None,
                           "source": "bytes only (no readable first line)"}},
                    {"x": wg.span_tuple([_rec("2020-01-01")] * 3)}, layer="drivers")
    assert v["refusals"] == []                                  # it cannot refuse: there is no number
    assert len(v["unmeasured"]) == 1 and "NOT MEASURED" in v["unmeasured"][0]
    assert any("DISARMED" in w for w in v["warns"])


# ── F4: the read-only seed that ARMS the span guard on the first guarded pass ──────────────────────────
def test_seed_manifest_is_read_only_idempotent_and_arms_the_span_leg(tmp_path, monkeypatch):
    """F4 -- resolve_prior sets span=None on BOTH the estimate and the absent branches; only the run-manifest
    branch carries a span, and newest_run_manifest() returns None on a store no guarded pass has ever
    touched. So G1b leg 2 -- "the leg that would have caught potash -25y immediately" -- could not fire on
    the FIRST guarded pass, which is the Wave-R rebuild. The seed is that missing baseline."""
    monkeypatch.setattr(ev, "_EVID_DIR", tmp_path)
    monkeypatch.setattr(ex, "_CFG", tmp_path / "cfg")
    monkeypatch.delenv("EVIDENCE_S3", raising=False)
    recs = [_rec("2020-01-01", rid="a", event_date="1960-01-01"),
            _rec("2024-06-30", rid="b", event_date="2024-06-30")]
    _seed_slice(tmp_path, "potash", recs)
    before = (tmp_path / "drivers" / "potash.jsonl").read_bytes()

    path = wg.seed_manifest(("drivers",))
    assert (tmp_path / "drivers" / "potash.jsonl").read_bytes() == before    # READ-ONLY on the slices
    doc = json.loads(open(path, encoding="utf-8").read())
    rec = doc["slices"]["drivers"]["potash"]
    assert rec["after_n"] == 2 and rec["after_span"]["event_date_min"] == "1960-01-01"
    assert rec["after_bytes"] == len(before)                    # the STORE's bytes: the stale fence matches

    prior = wg.resolve_prior("drivers/", ["potash"], layer="drivers")["potash"]
    assert prior["exact"] is True and prior["n"] == 2 and prior["span"]["event_date_min"] == "1960-01-01"

    # ... and NOW the span leg can actually fire: -64y of event_date start at a FROZEN count.
    contracted = wg.evaluate({"potash": prior},
                             {"potash": wg.span_tuple([_rec("2020-01-01", rid="a", event_date="2024-01-01"),
                                                       _rec("2024-06-30", rid="b",
                                                            event_date="2024-06-30")])}, layer="drivers")
    assert any("span CONTRACTED event_date_min 1960-01-01" in r for r in contracted["refusals"])

    second = wg.seed_manifest(("drivers",))                     # idempotent on the store and on the numbers
    assert (tmp_path / "drivers" / "potash.jsonl").read_bytes() == before
    assert json.loads(open(second, encoding="utf-8").read())["slices"] == doc["slices"]
