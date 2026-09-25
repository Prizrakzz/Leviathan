"""DECLARED CHURN -- the per-slice, dated declaration the write guard reads (2026-09-25).

THE EVENT. The scheduled evidence fold corpus-fold-h13c (2026-09-23, Batch job b0af76e7, evidence-build:137)
refused before its first byte on ONE slice: drivers/russia_export_tax_quota 583 -> 133 (77.2%), every other
slice moving 0.1-0.9%. The drop was DECLARED in the routing config a month earlier -- driver_slices.yaml:859,
the 2026-08-27 co_terms narrowing (commit d9af78ce) -- and the guard judged the declared post-narrowing
population against the stale pre-narrowing slice (written 2026-08-21). Its only offered way out,
--allow-churn PCT, is LAYER-WIDE: an 80% allowance lets every slice drop 80% silently.

WHAT IS PINNED HERE.
  * the tracked manifest validates, names a live routing key, and rides every image build route;
  * the guard ADMITS the declared slice at 133 (the measured post-narrowing population), and at 120 --
    the guard's own SLICE_DROP_REFUSE line re-based onto the declaration, no new threshold -- and REFUSES
    it at 119 and at 100;
  * it REFUSES an undeclared 77% drop, an expired entry, a not-yet-in-force entry, a declaration that has
    already landed (SPENT), and everything when the file is invalid (fail closed);
  * SPENT MEANS SPENT (the 2026-09-25 verifier's MAJOR-1): "pending" is bound to the PRE-CHANGE slice the
    entry was measured against (prior_population: the store's 584, the fold census baseline's 363), never to
    the declared population -- so after landing, growth then loss (148/160 -> 121, 300 -> 120) and a span
    that grew newer history and fell back to the declared endpoint are NEW and refused, by BOTH gates;
  * a span endpoint is admitted only on the pass that lands the declared change, only as far inward as the
    entry declares, and never past it;
  * the empty guard and the layer line never consult a declaration.

Hermetic: local store + tmp config dir, zero S3, zero spend. The real tracked file is read only where the
test says so, and every date-dependent verdict passes `today` explicitly -- no deck here goes red on a
calendar date.
"""
from __future__ import annotations

import importlib.util
import json
from datetime import date
from pathlib import Path

import pytest
import yaml
from leviathan.graphrag import evidence as ev
from leviathan.graphrag import extract as ex
from leviathan.graphrag import write_guard as wg

_REPO = Path(__file__).resolve().parents[2]
_TRACKED = _REPO / "configs" / "graphrag" / "declared_churn.json"
_REL = "configs/graphrag/declared_churn.json"

TODAY = date(2026, 9, 25)
RUSSIA = "drivers/russia_export_tax_quota"
NAME = "russia_export_tax_quota"
# The 2026-09-23 refused fold, verbatim from eval/write_manifest_rebuild_20260923T170324Z.json.
PRIOR_N_EST, PRIOR_BYTES = 583, 13632657
SPAN_0923 = {"date_min": "2010-09-10", "date_max": "2025-03-19",
             "event_date_min": "2010-01-01", "event_date_max": "2023-02-05"}
# The exact prior that manifest could not see (eval/write_manifest_rebuild_20260821T212319Z.json, after_bytes
# == the live object) -- the span leg's baseline when it is armed.
SPAN_0821 = {"n": 584, "date_min": "1996-05-01", "date_max": "2026-05-20",
             "event_date_min": "1998-01-01", "event_date_max": "2026-04-07"}
_NO_SPAN = {"date_min": None, "date_max": None, "event_date_min": None, "event_date_max": None}
# The PRE-CHANGE slice the declaration was measured against -- the readings each gate's before-side takes:
#   store 584           -- the exact after_n of eval/write_manifest_rebuild_20260821T212319Z.json, whose
#                          after_bytes 13,632,657 == the live object (head-object, 2026-09-25): the WRITE GUARD's prior;
#   census_baseline 363 -- eval/e1_census.json, LastModified 2026-08-02T00:36:09Z (the fold schedule's frozen
#                          --census-baseline, GET 2026-09-25): the CENSUS GATE's before-side on the first fold.
PRIOR_READINGS = {"store": 584, "census_baseline": 363}
# A quiet neighbour: the real driver layer held 295,421 props, so the declared -450 is 0.15% of it. Without a
# neighbour a one-slice fixture layer would trip the LAYER line and hide the per-slice verdict under test.
NEIGHBOUR_N = 100_000


def _entry(**over) -> dict:
    e = {"slice": RUSSIA, "declared_on": "2026-09-25",
         "reason": "the 2026-08-27 co_terms narrowing, driver_slices.yaml:859, commit d9af78ce",
         "prior_population": dict(PRIOR_READINGS),
         "expected_population": 133, "expected_span": dict(SPAN_0923), "expires": "2026-12-31"}
    e.update(over)
    return {k: v for k, v in e.items() if v is not None}


def _doc(*entries) -> dict:
    return {"manifest": "declared_churn", "version": 1, "entries": list(entries)}


def _declared(tmp_path, doc, today=TODAY) -> wg.DeclaredChurn:
    p = tmp_path / "declared_churn.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    return wg.load_declared_churn(p, today=today)


def _prior(n, *, span=None, exact=False, nbytes=PRIOR_BYTES) -> dict:
    return {"bytes": nbytes, "n": n, "exact": exact, "span": span,
            "source": "run manifest (test)" if exact else "size/first-line estimate (23371 B/prop)"}


def _verdict(declared, an, *, prior=None, span=None, name=NAME, layer="drivers"):
    after_span = dict(SPAN_0923) if span is None else span
    return wg.evaluate({name: prior or _prior(PRIOR_N_EST), "export_ban": _prior(NEIGHBOUR_N)},
                       {name: {"n": an, **after_span}, "export_ban": {"n": NEIGHBOUR_N, **_NO_SPAN}},
                       layer=layer, declared=declared)


# ── the tracked manifest ─────────────────────────────────────────────────────────────────────────────
def test_the_tracked_manifest_is_valid_and_declares_the_0827_narrowing():
    raw = _TRACKED.read_bytes()
    raw.decode("ascii")                                         # read on a cp1252 console; ASCII only
    doc = json.loads(raw)
    assert wg.validate_declared_churn(doc) == []
    [entry] = [e for e in doc["entries"] if e["slice"] == RUSSIA]
    assert entry["expected_population"] == 133                 # the 09-23 run manifest's after_n
    assert entry["expected_span"] == SPAN_0923                  # ... and its after_span, endpoint for endpoint
    assert entry["prior_population"] == PRIOR_READINGS          # the pre-change slice, as each gate reads it
    assert "13632657" in entry["evidence"]["prior_store_object"]
    assert "2026-08-02T00:36:09Z" in entry["evidence"]["prior_census_baseline"]
    assert "n_routed_props 363" in entry["evidence"]["prior_census_baseline"]
    assert entry["declared_on"] == "2026-09-25" and entry["expires"] == "2026-12-31"
    assert "driver_slices.yaml:859" in entry["reason"] and "d9af78ce" in entry["reason"]


def test_the_guards_default_path_IS_the_tracked_file():
    """The guard reads configs/graphrag/declared_churn.json through extract._CFG -- the same root every other
    graphrag config resolves through -- so the file the deck validates is the file the rebuild reads."""
    assert wg.declared_churn_path().resolve() == _TRACKED.resolve()


def test_every_declared_drivers_slice_is_a_live_routing_key_carrying_its_declared_cause():
    """A declaration for a slice the routing config no longer has is stale by construction. And the russia
    entry's stated cause -- the co_terms gate -- must actually be on that slice in the tracked config."""
    specs = (yaml.safe_load((_REPO / "configs" / "graphrag" / "driver_slices.yaml")
                            .read_text(encoding="utf-8")) or {}).get("drivers") or {}
    doc = json.loads(_TRACKED.read_text(encoding="utf-8"))
    for e in doc["entries"]:
        layer, name = e["slice"].split("/")
        if layer == "drivers":
            assert name in specs, f"{e['slice']} is declared but no longer routed"
    assert {"russia", "russian"} <= set(specs[NAME].get("co_terms") or [])


def test_the_manifest_path_rides_every_image_route():
    """configs/graphrag/eval/ is 'never context' in BOTH exclusion lists, and the context tar behind the live
    embedder image was measured to hold zero eval/ members. The declaration must not live anywhere either
    list drops, or the in-container guard reads nothing and the fold refuses again."""
    spec = importlib.util.spec_from_file_location(
        "_mwct_for_declared_churn", _REPO / "scripts" / "ops" / "make_worker_context_tar.py")
    mwct = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mwct)
    assert _REL.startswith(mwct.OVERLAY_SUBTREE + "/")
    assert not any(_REL.startswith(p) for p in mwct.OVERLAY_EXCLUDE_PREFIXES)
    ignored = [ln.strip() for ln in (_REPO / ".dockerignore").read_text(encoding="utf-8").splitlines()
               if ln.strip() and not ln.strip().startswith("#")]
    assert not any(_REL.startswith(pat.rstrip("*")) for pat in ignored if pat.startswith("configs/"))
    dockerfile = (_REPO / "docker" / "leviathan_embedder" / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY configs/ ./configs/" in dockerfile
    assert _REL == "configs/graphrag/" + wg.DECLARED_CHURN_FILE


def test_the_tracked_declaration_replays_the_0923_refusal_into_an_admission():
    """The measured event, end to end through the REAL file (today pinned, so no calendar time-bomb)."""
    declared = wg.load_declared_churn(_TRACKED, today=TODAY)
    assert declared.state == "valid" and RUSSIA in declared.active
    undeclared = _verdict(None, 133)
    assert len(undeclared["refusals"]) == 1 and "583 -> 133 (77.2% drop)" in undeclared["refusals"][0]
    v = _verdict(declared, 133)
    assert v["refusals"] == [] and len(v["declared_admitted"]) == 1


# ── the population leg ───────────────────────────────────────────────────────────────────────────────
def test_admits_the_declared_slice_at_133(tmp_path):
    v = _verdict(_declared(tmp_path, _doc(_entry())), 133)
    assert v["refusals"] == []
    [line] = v["declared_admitted"]
    assert "583 -> 133" in line and "ADMITTED by declared churn" in line and "expected population 133" in line
    assert line in v["warns"]                                   # admitted is never silent: it is a WARN


def test_the_tolerance_IS_the_guards_own_line_re_based_onto_the_declaration(tmp_path):
    """No new number: the floor is derived from SLICE_DROP_REFUSE, so re-tuning that constant moves both."""
    declared = _declared(tmp_path, _doc(_entry()))
    floor = min(n for n in range(1, 134) if (133 - n) / 133 < wg.SLICE_DROP_REFUSE)
    assert floor == 120
    assert _verdict(declared, floor)["refusals"] == []
    below = _verdict(declared, floor - 1)["refusals"]
    assert len(below) == 1 and "BELOW the declared population 133" in below[0]


def test_refuses_the_declared_slice_at_100(tmp_path):
    v = _verdict(_declared(tmp_path, _doc(_entry())), 100)
    assert len(v["refusals"]) == 1 and v["declared_admitted"] == []
    assert "583 -> 100" in v["refusals"][0] and "BELOW the declared population 133 by 24.8%" in v["refusals"][0]


def test_growth_past_the_declared_population_is_less_loss_and_is_admitted(tmp_path):
    v = _verdict(_declared(tmp_path, _doc(_entry())), 160)      # new Russia docs between declaration and fold
    assert v["refusals"] == [] and len(v["declared_admitted"]) == 1


def test_refuses_an_UNDECLARED_77pct_drop_even_with_a_declaration_in_force(tmp_path):
    declared = _declared(tmp_path, _doc(_entry()))
    other = _verdict(declared, 133, name="export_restrictions_world")
    assert len(other["refusals"]) == 1 and other["declared_admitted"] == []
    assert "export_restrictions_world: population 583 -> 133" in other["refusals"][0]
    # the key is <layer>/<slice>: the same NAME in another layer is a different slice, undeclared
    commodity = _verdict(declared, 133, layer="commodity")
    assert commodity["refusals"] and commodity["declared_admitted"] == []


def test_an_EXPIRED_entry_is_ignored_and_the_refusal_stands(tmp_path):
    doc = _doc(_entry())
    last_day = _verdict(_declared(tmp_path, doc, today=date(2026, 12, 31)), 133)
    assert last_day["refusals"] == []                           # `expires` is the LAST day the entry counts
    expired = _verdict(_declared(tmp_path, doc, today=date(2027, 1, 1)), 133)
    assert len(expired["refusals"]) == 1 and expired["declared_admitted"] == []
    assert "EXPIRED on 2026-12-31" in expired["refusals"][0]


def test_an_entry_not_yet_in_force_admits_nothing(tmp_path):
    v = _verdict(_declared(tmp_path, _doc(_entry()), today=date(2026, 9, 24)), 133)
    assert len(v["refusals"]) == 1 and "NOT YET IN FORCE" in v["refusals"][0]


def test_the_declaration_RETIRES_ITSELF_once_the_store_holds_the_declared_population(tmp_path):
    """After the first committed pass the prior IS ~133 (plus growth). A later drop on that slice is NEW; an
    entry that stayed live until expiry would wave it through -- the --allow-churn defect, one slice wide."""
    declared = _declared(tmp_path, _doc(_entry()))
    v = _verdict(declared, 125, prior=_prior(140, exact=True))  # -10.7% from a post-change prior
    assert len(v["refusals"]) == 1 and v["declared_admitted"] == []
    assert "is SPENT" in v["refusals"][0] and "census_baseline 363, store 584" in v["refusals"][0]


# ── fail closed ──────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("mutate, expect", [
    (lambda d: d["entries"][0].pop("expires"), "missing required key(s) ['expires']"),
    (lambda d: d["entries"][0].update(expected_populaton=133), "unknown key(s) ['expected_populaton']"),
    (lambda d: d["entries"][0].update(expected_drop_pct=77.2), "expected_drop_pct is refused"),
    (lambda d: [d["entries"][0].pop(k) for k in ("expected_population", "expected_span")],
     "missing required key(s) ['expected_population']"),
    (lambda d: d["entries"][0].pop("expected_population"), "a span-only declaration is refused"),
    (lambda d: d["entries"][0].pop("prior_population"), "missing required key(s) ['prior_population']"),
    (lambda d: d["entries"][0].update(prior_population=584), "prior_population must be an object"),
    (lambda d: d["entries"][0].update(prior_population={"census_baseline": 363}), "holding at least 'store'"),
    (lambda d: d["entries"][0].update(prior_population={"store": 584, "shadow": 500}),
     "prior_population must be an object"),
    (lambda d: d["entries"][0].update(prior_population={"store": 584.0}), "prior_population store must be an int"),
    (lambda d: d["entries"][0].update(prior_population={"store": True}), "prior_population store must be an int"),
    (lambda d: d["entries"][0].update(prior_population={"store": 584, "census_baseline": 0}),
     "prior_population census_baseline must be an int >= 1"),
    (lambda d: d["entries"][0].update(prior_population={"store": 147}),       # 133 is within 10% of 147
     "prior_population store 147 is not at least 10% above expected_population 133"),
    (lambda d: d["entries"][0].update(prior_population={"store": 584, "census_baseline": 100}),   # a GROWTH
     "prior_population census_baseline 100 is not at least 10% above expected_population 133"),
    (lambda d: d["entries"][0].update(expires="2026-13-01"), "expires must be a YYYY-MM-DD date"),
    (lambda d: d["entries"][0].update(declared_on="2026-09-25T00:00:00Z"), "declared_on must be a YYYY-MM-DD"),
    (lambda d: d["entries"][0].update(expires="2026-09-01"), "is before declared_on"),
    (lambda d: d["entries"][0].update(expected_population=0), "expected_population must be an int >= 1"),
    (lambda d: d["entries"][0].update(expected_population=True), "expected_population must be an int >= 1"),
    (lambda d: d["entries"][0].update(expected_population=133.0), "expected_population must be an int >= 1"),
    (lambda d: d["entries"][0].update(slice=NAME), "slice must be '<layer>/<name>'"),
    (lambda d: d["entries"][0].update(slice="pilot/" + NAME), "names layer 'pilot'"),
    (lambda d: d["entries"][0].update(expected_span={"start": "2010-01-01"}), "expected_span must be"),
    (lambda d: d["entries"][0].update(expected_span={"date_min": "2010"}), "must be YYYY-MM-DD dates"),
    (lambda d: d["entries"][0].update(expected_span={"date_min": "2025-01-01", "date_max": "2020-01-01"}),
     "is after date_max"),
    (lambda d: d["entries"][0].update(reason="  "), "reason must be a non-empty string"),
    (lambda d: d["entries"][0].update(evidence={"ok": True}), "evidence must be an object"),
    (lambda d: d["entries"].append(dict(d["entries"][0])), "is declared twice"),
    (lambda d: d.update(version=2), "'version' must be 1"),
    (lambda d: d.update(manifest="churn"), "'manifest' must be 'declared_churn'"),
    (lambda d: d.update(notes="x"), "unknown top-level key(s) ['notes']"),
    (lambda d: d.update(entries={}), "'entries' must be a list"),
])
def test_the_schema_is_strict(mutate, expect):
    doc = _doc(_entry())
    assert wg.validate_declared_churn(doc) == []
    mutate(doc)
    errs = wg.validate_declared_churn(doc)
    assert any(expect in e for e in errs), errs


def test_an_INVALID_manifest_admits_nothing_and_says_so_at_the_refusal(tmp_path):
    """One bad entry voids the WHOLE file: a partially-read declaration set is how a guard fails open."""
    doc = _doc(_entry(), _entry(slice="drivers/export_ban", expected_drop_pct=50))
    declared = _declared(tmp_path, doc)
    assert declared.state == "invalid" and declared.active == {} and declared.errors
    v = _verdict(declared, 133)
    assert len(v["refusals"]) == 1 and "is INVALID" in v["refusals"][0]


def test_an_UNREADABLE_manifest_is_invalid_and_never_raises(tmp_path):
    p = tmp_path / "declared_churn.json"
    p.write_text("{ not json", encoding="utf-8")
    declared = wg.load_declared_churn(p, today=TODAY)
    assert declared.state == "invalid" and declared.active == {} and "unreadable" in declared.errors[0]


def test_an_ABSENT_manifest_is_no_declarations_and_the_line_is_unchanged(tmp_path):
    declared = wg.load_declared_churn(tmp_path / "nope.json", today=TODAY)
    assert declared.state == "absent" and declared.active == {}
    v = _verdict(declared, 133)
    assert len(v["refusals"]) == 1 and v["refusals"][0].endswith("at/over the 10% refuse line")


# ── the span leg ─────────────────────────────────────────────────────────────────────────────────────
def test_span_endpoints_are_admitted_only_as_far_as_declared(tmp_path):
    """Measured: against the EXACT 08-21 prior, all four russia endpoints moved inward. Declared, all four are
    admitted; one day past a declared endpoint is refused; an entry that declares no span admits none."""
    exact = _prior(584, span=SPAN_0821, exact=True)
    declared = _declared(tmp_path, _doc(_entry()))
    v = _verdict(declared, 133, prior=exact)
    assert v["refusals"] == [] and len(v["declared_admitted"]) == 5          # 1 population + 4 endpoints

    past = _verdict(declared, 133, prior=exact, span={**SPAN_0923, "date_min": "2010-09-11"})
    assert len(past["refusals"]) == 1
    assert "PAST the declared expected_span date_min 2010-09-10" in past["refusals"][0]

    no_span = _verdict(_declared(tmp_path, _doc(_entry(expected_span=None))), 133, prior=exact)
    assert len(no_span["refusals"]) == 4                                      # population admitted, span not
    assert all("does not declare" in r for r in no_span["refusals"])


def test_a_SPAN_ONLY_declaration_is_refused_because_it_could_never_be_seen_to_land(tmp_path):
    """The first cut accepted a span-only entry (the argentina_export_policy shape: population grew,
    event_date_min moved because the same narrowing removed a Thai sugar prop). Its population need not move,
    so nothing could ever show its change had LANDED: every outward-then-inward endpoint move would be
    re-admitted until expiry -- MAJOR-1 through the span leg. The schema refuses it, the WHOLE file goes
    invalid (fail closed), and the span contraction it meant to admit refuses."""
    span_only = _declared(tmp_path, _doc(_entry(expected_population=None)))
    assert span_only.state == "invalid" and span_only.active == {}
    assert any("a span-only declaration is refused" in x for x in span_only.errors)
    v = _verdict(span_only, 133, prior=_prior(584, span=SPAN_0821, exact=True))
    assert v["declared_admitted"] == [] and len(v["refusals"]) == 5      # 1 population + 4 endpoints


def test_an_undeclared_span_contraction_still_refuses(tmp_path):
    declared = _declared(tmp_path, _doc(_entry()))
    before = {"n": 10, "date_min": "1960-01-01", "date_max": "2026-01-01",
              "event_date_min": "1960-01-01", "event_date_max": "2026-01-01"}
    v = wg.evaluate({"fertilizer": _prior(10, span=before, exact=True)},
                    {"fertilizer": {**before, "event_date_min": "1988-01-01"}},
                    layer="drivers", declared=declared)
    assert len(v["refusals"]) == 1 and "fertilizer: span CONTRACTED event_date_min" in v["refusals"][0]


# ── what a declaration never touches ─────────────────────────────────────────────────────────────────
def test_the_LAYER_line_never_consults_a_declaration(tmp_path):
    declared = _declared(tmp_path, _doc(_entry()))
    v = wg.evaluate({NAME: _prior(PRIOR_N_EST)}, {NAME: {"n": 133, **SPAN_0923}}, layer="drivers",
                    declared=declared)
    assert len(v["declared_admitted"]) == 1                     # the slice is admitted ...
    assert v["refusals"] == ["drivers: LAYER population 583 -> 133 (77.2% drop) -- at/over the 10% refuse line"]


def test_the_EMPTY_guard_never_consults_a_declaration(tmp_path):
    v = _verdict(_declared(tmp_path, _doc(_entry())), 0, span=dict(_NO_SPAN))
    assert any("EMPTY slice" in r for r in v["refusals"]) and v["declared_admitted"] == []


def test_allow_churn_keeps_its_layer_wide_meaning_and_is_checked_first(tmp_path):
    declared = _declared(tmp_path, _doc(_entry()))
    v = wg.evaluate({NAME: _prior(PRIOR_N_EST), "export_ban": _prior(NEIGHBOUR_N)},
                    {NAME: {"n": 133, **SPAN_0923}, "export_ban": {"n": NEIGHBOUR_N, **_NO_SPAN}},
                    layer="drivers", allow_churn=0.80, declared=declared)
    assert v["refusals"] == [] and v["declared_admitted"] == []  # the flag admitted it, not the declaration


# ── through plan_write: the file the rebuild reads, and the record it leaves ─────────────────────────
def _rec(i):
    # fixed-width fields: every line has the same byte length, so the size/first-line prior is exactly n
    return {"id": f"i{i:06d}", "date": "2020-01-01", "source": "WB", "source_key": f"k{i:06d}",
            "text": "t" * 40, "event_date": None}


def _seed(tmp_path, name, n):
    d = tmp_path / "drivers"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.jsonl").write_text("\n".join(json.dumps(_rec(i)) for i in range(n)) + "\n",
                                     encoding="utf-8")


def _plan(tmp_path, monkeypatch, n_after, *, doc):
    monkeypatch.setattr(ev, "_EVID_DIR", tmp_path)
    cfg = tmp_path / "cfg"
    cfg.mkdir(exist_ok=True)
    monkeypatch.setattr(ex, "_CFG", cfg)
    monkeypatch.delenv("EVIDENCE_S3", raising=False)
    if doc is not None:
        (cfg / wg.DECLARED_CHURN_FILE).write_text(json.dumps(doc), encoding="utf-8")
    _seed(tmp_path, NAME, PRIOR_N_EST)
    _seed(tmp_path, "export_ban", 5000)
    mf = wg.RunManifest("unit")
    records = {NAME: [_rec(i) for i in range(n_after)], "export_ban": [_rec(i) for i in range(5000)]}
    written = []
    plan = wg.plan_write("drivers", "drivers/", {n: (lambda: "x") for n in records}, records=records,
                         manifest=mf, allow_churn=None, write_fn=lambda node, body: written.append(node),
                         node_of=lambda n: f"drivers/{n}")
    return plan, mf, written


# Dates chosen so the entry is in force on ANY day this deck runs: plan_write reads the real clock.
_TIMELESS = _doc(_entry(declared_on="2026-01-01", expires="2099-12-31", expected_span=None))


def test_plan_write_reads_the_declaration_from_configs_and_records_it(tmp_path, monkeypatch, capsys):
    plan, mf, written = _plan(tmp_path, monkeypatch, 133, doc=_TIMELESS)
    assert plan.refusals == [] and written == []
    out = capsys.readouterr().out
    assert "WARN write-guard drivers/russia_export_tax_quota: population 583 -> 133" in out
    assert "ADMITTED by declared churn" in out
    rec = mf.payload()["declared_churn"]
    assert rec["state"] == "valid" and rec["active"] == [RUSSIA] and len(rec["sha256"]) == 64
    assert rec["path"].endswith(wg.DECLARED_CHURN_FILE)
    assert len(mf.guard["drivers"]["declared_admitted"]) == 1


def test_plan_write_still_refuses_outside_the_declaration(tmp_path, monkeypatch):
    plan, mf, _ = _plan(tmp_path, monkeypatch, 100, doc=_TIMELESS)
    assert len(plan.refusals) == 1 and "BELOW the declared population 133" in plan.refusals[0]
    with pytest.raises(wg.WriteRefused):
        wg.raise_if_refused(plan)


def test_plan_write_with_no_file_is_exactly_the_old_guard(tmp_path, monkeypatch):
    plan, mf, _ = _plan(tmp_path, monkeypatch, 133, doc=None)
    assert len(plan.refusals) == 1 and plan.refusals[0].endswith("at/over the 10% refuse line")
    assert mf.payload()["declared_churn"]["state"] == "absent"


def test_plan_write_names_an_INVALID_file_in_its_warnings(tmp_path, monkeypatch, capsys):
    plan, mf, _ = _plan(tmp_path, monkeypatch, 133, doc={"manifest": "declared_churn"})
    assert len(plan.refusals) == 1 and "is INVALID" in plan.refusals[0]
    assert "declared-churn manifest INVALID" in capsys.readouterr().out
    assert mf.payload()["declared_churn"]["state"] == "invalid"


def test_the_refusal_message_leads_with_the_per_slice_route(tmp_path, monkeypatch):
    plan, _, _ = _plan(tmp_path, monkeypatch, 133, doc=None)
    with pytest.raises(wg.WriteRefused) as exc:
        wg.raise_if_refused(plan)
    tail = exc.value.lines[-1]
    assert "declared_churn.json" in tail and "LAYER-WIDE" in tail and "--allow-churn" in tail
    assert tail.index("declared_churn.json") < tail.index("--allow-churn")


# ── the fold's SECOND gate: e1_census --diff reads the SAME declaration by the SAME rule ────────────────
# Replayed offline ($0: current configs, the 09-23 rebuild's populations substituted for the slice GETs), the
# re-run fold with the declaration honoured by the write guard ONLY would pass step 2, REWRITE the store, then
# fail step 3 on this one slice -- 2026-08-02 baseline 363 -> 133 -- and never roll its baseline again.
def _census(n_russia: int, n_other: int = 1000) -> dict:
    slices = [{"slice": NAME, "n_dag_ids": 1, "n_routed_props": n_russia, "consumed": n_russia > 0,
               "orphan_kind": None},
              {"slice": "export_ban", "n_dag_ids": 1, "n_routed_props": n_other, "consumed": True,
               "orphan_kind": None}]
    return {"census": "E1_darkness", "id_totals": {"n_dark": 10, "by_reason": {"exact": 5}},
            "slice_totals": {"n_consumed": 2, "orphan_by_kind": {"retire": 1}}, "slices": slices}


def test_the_census_gate_admits_the_declared_drop_and_says_so(tmp_path):
    from leviathan.graphrag import e1_census as ec
    base, cur = _census(363), _census(133)
    assert ec.diff_census(base, cur)["regressed"] is True                  # the bare gate: unchanged
    declared = _declared(tmp_path, _doc(_entry()))
    d = ec.diff_census(base, cur, declared=declared)
    assert d["regressed"] is False and d["population_drops"] == []
    [adm] = d["population_drops_declared"]
    assert (adm["slice"], adm["before"], adm["after"], adm["expected_population"]) == (NAME, 363, 133, 133)
    code, lines = ec.run_diff(cur, base, declared=declared)
    assert code == 0 and any(ln.startswith("ADMITTED population russia_export_tax_quota: 363 -> 133")
                             and "pre-change census_baseline 363 -> expected population 133" in ln
                             for ln in lines)
    "\n".join(lines).encode("ascii")


def test_the_census_gate_still_refuses_what_the_declaration_does_not_cover(tmp_path):
    from leviathan.graphrag import e1_census as ec
    declared = _declared(tmp_path, _doc(_entry()))
    assert ec.diff_census(_census(363), _census(100), declared=declared)["regressed"] is True   # below 120
    other = ec.diff_census(_census(363, n_other=1000), _census(133, n_other=500), declared=declared)
    assert other["regressed"] is True and [x["slice"] for x in other["population_drops"]] == ["export_ban"]
    expired = _declared(tmp_path, _doc(_entry()), today=date(2027, 1, 1))
    assert ec.diff_census(_census(363), _census(133), declared=expired)["regressed"] is True
    invalid = _declared(tmp_path, {"manifest": "declared_churn"})
    code, lines = ec.run_diff(_census(133), _census(363), declared=invalid)
    assert code == 1 and any("DECLARED-CHURN manifest INVALID" in ln for ln in lines)


def test_run_diff_reads_the_file_the_write_guard_reads(tmp_path, monkeypatch):
    """The fold's step 3 is the e1_census CLI, whose only seam is run_diff(current, baseline): by default it
    loads configs/graphrag/declared_churn.json through the write guard's own loader."""
    from leviathan.graphrag import e1_census as ec
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    monkeypatch.setattr(ex, "_CFG", cfg)
    assert ec.run_diff(_census(133), _census(363))[0] == 1                 # no file: the bare gate
    (cfg / wg.DECLARED_CHURN_FILE).write_text(json.dumps(_TIMELESS), encoding="utf-8")
    assert ec.run_diff(_census(133), _census(363))[0] == 0


# every reading's window edge (store 584: 526..642; census_baseline 363: 327..399), the MAJOR-1 priors, and
# the post-landing band
@pytest.mark.parametrize("before", [363, 583, 584, 140, 133, 148, 160, 300, 380,
                                    525, 526, 642, 643, 326, 327, 399, 400])
def test_the_two_gates_agree_on_every_population(tmp_path, before):
    """One rule, two callers: for every after-population the census's verdict is the write guard's."""
    from leviathan.graphrag import e1_census as ec
    declared = _declared(tmp_path, _doc(_entry(expected_span=None)))
    for after in range(0, before + 1):
        guard = _verdict(declared, after, prior=_prior(before, exact=True), span=dict(_NO_SPAN))
        guard_refuses = any(r.startswith(f"drivers/{NAME}: population") for r in guard["refusals"])
        census_refuses = bool(ec.diff_census(_census(before), _census(after),
                                             declared=declared)["population_drops"])
        lost = before - after
        if 0 < after and lost >= ec.POP_DROP_MIN_ABS:                      # where both gates can speak
            assert guard_refuses == census_refuses, (before, after)


# ── MAJOR-1 (the 2026-09-25 verifier): SPENT MEANS SPENT -- "pending" is the PRE-CHANGE slice, never a proxy ──
# The first cut tested "pending" as (prior - P) / prior >= SLICE_DROP_REFUSE. After landing (store ~133) any
# growth past P / 0.9 = 148 re-armed it until expiry: 160 -> 121 (a 24.4% drop the plain guard refuses) and
# 300 -> 120 were ADMITTED, by the census gate too, and a span that grew newer history fell back to the
# declared endpoint and was admitted. Now the entry is bound to the slice it was MEASURED against.
@pytest.mark.parametrize("prior_n, after_n", [(148, 121), (160, 121), (300, 120), (147, 121), (200, 133)])
def test_growth_then_loss_after_landing_is_NEW_and_refused_by_the_write_guard(tmp_path, prior_n, after_n):
    declared = wg.load_declared_churn(_TRACKED, today=TODAY)          # the REAL tracked entry
    v = _verdict(declared, after_n, prior=_prior(prior_n, exact=True), span=dict(_NO_SPAN))
    assert v["declared_admitted"] == [] and len(v["refusals"]) == 1
    assert f"population {prior_n} -> {after_n}" in v["refusals"][0] and "is SPENT" in v["refusals"][0]


@pytest.mark.parametrize("before, after", [(148, 121), (160, 121), (300, 120), (140, 125)])
def test_growth_then_loss_after_landing_is_REGRESSED_by_the_census_gate(before, after):
    from leviathan.graphrag import e1_census as ec
    declared = wg.load_declared_churn(_TRACKED, today=TODAY)
    d = ec.diff_census(_census(before), _census(after), declared=declared)
    assert d["regressed"] is True and d["population_drops_declared"] == []
    assert [x["slice"] for x in d["population_drops"]] == [NAME]


def test_the_span_fallback_after_newer_history_is_refused(tmp_path):
    """The verifier's P5: after landing, the store grew newer history (date_max 2026-11-15) and later fell
    back to the declared 2025-03-19. With no population drop at all, only the span leg speaks -- and it is
    gated on the pass LANDING the change, which a post-landing store (160) cannot do."""
    declared = wg.load_declared_churn(_TRACKED, today=TODAY)
    grown = {"n": 160, **SPAN_0923, "date_max": "2026-11-15", "event_date_max": "2026-11-01"}
    v = _verdict(declared, 160, prior=_prior(160, span=grown, exact=True))
    assert v["declared_admitted"] == [] and len(v["refusals"]) == 2
    assert all("span CONTRACTED" in r and "is SPENT" in r for r in v["refusals"])


def test_the_no_growth_retire_case_is_kept(tmp_path):
    declared = wg.load_declared_churn(_TRACKED, today=TODAY)
    for prior_n, after_n in ((133, 119), (140, 125), (135, 100)):
        v = _verdict(declared, after_n, prior=_prior(prior_n, exact=True), span=dict(_NO_SPAN))
        assert v["declared_admitted"] == [] and "is SPENT" in v["refusals"][0], (prior_n, after_n)


def test_the_FIRST_admission_still_lands_through_BOTH_gates():
    """The re-run fold, through the real file: step 2 judges the live object (583 estimated, 584 exact) and
    step 3 judges the frozen 2026-08-02 census baseline (363). Both read as a pre-change reading; 133 reads as
    none; both admit."""
    from leviathan.graphrag import e1_census as ec
    declared = wg.load_declared_churn(_TRACKED, today=TODAY)
    for prior in (_prior(PRIOR_N_EST), _prior(584, span=SPAN_0821, exact=True)):
        v = _verdict(declared, 133, prior=prior)
        assert v["refusals"] == [] and v["declared_admitted"], prior
        assert "the prior reads as the pre-change store 584" in v["declared_admitted"][0]
    d = ec.diff_census(_census(363), _census(133), declared=declared)
    assert d["regressed"] is False and [x["prior_reading"] for x in d["population_drops_declared"]] == [
        "census_baseline 363"]


def test_without_the_census_baseline_reading_step_3_would_refuse_what_step_2_admitted(tmp_path):
    """Why the entry records the census baseline at all: the census's before-side on the first fold is NOT the
    store (363 vs 584, 37.8% apart). Bound to the store alone, the fold would pass step 2, REWRITE the store,
    and fail step 3 on the same slice -- the split-gate failure the shared rule exists to prevent."""
    from leviathan.graphrag import e1_census as ec
    store_only = _declared(tmp_path, _doc(_entry(prior_population={"store": 584})))
    assert _verdict(store_only, 133)["refusals"] == []                          # step 2 admits
    assert ec.diff_census(_census(363), _census(133), declared=store_only)["regressed"] is True  # step 3 refuses


def test_a_pass_that_does_not_move_the_slice_off_the_pre_change_readings_is_not_the_declared_change(tmp_path):
    """583 -> 380 is above the declared floor but still reads as the census baseline 363: admitting it would
    leave the entry ARMED for a later 380 -> 125. Refused, by both gates, as not the declared change."""
    from leviathan.graphrag import e1_census as ec
    declared = _declared(tmp_path, _doc(_entry()))
    v = _verdict(declared, 380)
    assert v["declared_admitted"] == [] and "still reads as the pre-change census_baseline 363" in v["refusals"][0]
    assert ec.diff_census(_census(584), _census(380), declared=declared)["regressed"] is True


def test_every_admission_leaves_the_entry_SPENT_by_construction(tmp_path):
    """The property MAJOR-1 lacked, checked exhaustively over every before/after pair up to 700: whatever a pass
    admits, the population it lands reads as NO pre-change reading, so the next pass starts outside every
    window -- and the only way back in is to RE-GROW into one (327-399 or 526-642 here) before expiry."""
    entry = _entry()
    admitted = 0
    for bn in range(1, 701):
        for an in range(0, bn + 1):
            if wg._declared_admits(entry, bn, an):
                admitted += 1
                assert wg.pre_change_reading(entry, an) is None, (bn, an)
                assert wg.pre_change_reading(entry, bn) is not None, (bn, an)
    assert admitted > 0
    windows = {n for n in range(1, 1000) if wg.pre_change_reading(entry, n)}
    assert min(windows) == 327 and max(windows) == 642
    assert windows == set(range(327, 400)) | set(range(526, 643))


def test_the_pending_windows_ARE_the_guards_own_line_around_each_reading():
    """No new number: re-tuning SLICE_DROP_REFUSE moves every window with it."""
    entry = _entry()
    for label, r in PRIOR_READINGS.items():
        inside = [n for n in range(1, 2 * r) if (wg.pre_change_reading(entry, n) or (None,))[0] == label]
        assert all(abs(n - r) / r < wg.SLICE_DROP_REFUSE for n in inside)
        assert abs(min(inside) - 1 - r) / r >= wg.SLICE_DROP_REFUSE
        assert abs(max(inside) + 1 - r) / r >= wg.SLICE_DROP_REFUSE
