"""D-W3 ESR pace-leg unit tests (hermetic: no pg/Athena/LLM; stub query_fn(sql)->rows).

Covers the two _node_specs code changes (D-W3.2: the `leg_mode: current` era-guard + agg-threading), the
freshest-week query shape (D-W3.1 `agg: latest`, the C2 stale-week lock), unit honesty (1000 MT flow, never
MMT, no ESR<->PSD delta), non-pairability (no reroute fork, D-W3.4), the coverage guard (driver_fireable /
census pg probe, D-W3.3), and silent-week absence (DECLINES-HONESTLY). D-W3.5 items 1,2,3,4,5,7.

Item 6 (the PIT publication-lag boundary, D-W0.3) is owned by the D-W0 agent and lives in that agent's
test file -- not re-implemented here.

The cascade_map `esr_exports` row is intentionally `deferred: true` (the flip is D-W5, user-gated), so
load_map() drops it. These tests therefore inject the D-W3.1 row directly as `_ESR_ROW` -- exactly the shape
the un-defer will activate -- and drive `_node_specs`/`_assemble`/`_pair_units` with it, matching the
existing cascade test convention of passing map rows as plain dicts."""
from __future__ import annotations

from types import SimpleNamespace

from leviathan.graphrag.numbers import cascade as cq

# The D-W3.1 ESR pace row (see configs/graphrag/numbers/cascade_map.yaml:esr_exports, minus `deferred`).
_ESR_ROW = {
    "table": "silver_esr",
    "metric": "weekly_exports_1000mt",
    "agg": "latest",
    "period_type": "date",
    "leg_mode": "current",
    "country_rule": "none",
    "native_unit": "1000 MT",
    "narrate_unit": "1000 MT",
    "scale": 1,
    "coverage_start": 1990,
}

# A PSD export LEVEL row (the era/level backbone the pace leg complements), for the regression + honesty legs.
_PSD_EXPORT_ROW = {
    "table": "silver_psd",
    "metric": "exports_mt",
    "agg": "latest",
    "period_type": "marketing_year",
    "narrate_unit": "MMT",
    "scale": 0.000001,
}

_ERAS = [("2012-06-01", "2012-11-01"), ("2020-03-01", "2020-08-01")]


def _node(contract="corn_cbot", ref="esr_exports", nid="us_export_pace", dates=None):
    ev = [{"date": d, "source": "usda_fas", "source_key": f"k{i}", "text": "t"}
          for i, d in enumerate(dates or [])]
    return SimpleNamespace(contract=contract, id=nid, prior={"silver_ref": ref, "region": "US"},
                           evidence=ev)


# ── D-W3.5.1: `leg_mode: current` emits a current-only leg; PSD still emits era + current ──────────────
def test_leg_mode_current_emits_current_only():
    specs = cq._node_specs(_node(), _ESR_ROW, "corn_cbot", None, _ERAS, asof="2026-07-01")
    assert [s["leg"] for s in specs] == [("current", None)]           # exactly ONE current spec
    assert all(s["leg"][0] != "era" for s in specs)                   # ZERO era specs (era-legs-stay-PSD)
    assert specs[0]["era_idx"] is None
    assert specs[0]["agg"] == "latest"                                # D-W3.2 agg-threading honored


def test_psd_node_still_emits_era_and_current_regression():
    specs = cq._node_specs(_node(contract="corn_cbot", ref="export", nid="export"),
                           _PSD_EXPORT_ROW, "corn_cbot", "United States", _ERAS, asof="2026-07-01")
    legs = [s["leg"][0] for s in specs]
    assert "era" in legs                                             # PSD keeps its era/level backbone
    assert any(s["leg"] == ("current", None) for s in specs)         # ... plus the current rhyme leg


def test_guard_keys_on_leg_mode_not_period_type():
    # the era-guard fires ONLY on leg_mode==current, never on period_type==date: a date row WITHOUT leg_mode
    # (fred_fx) still emits era legs, and its current leg keeps agg='series' (the D-W3.2 default preserves
    # today's PSD/fx date-leg behavior exactly).
    fx_row = {"table": "silver_fred_fx", "metric": "brl_usd", "period_type": "date", "scale": 1,
              "narrate_unit": "local currency per USD"}
    specs = cq._node_specs(_node(contract="soybeans_cbot", ref="fred_fx_macro", nid="BRL_FX"),
                           fx_row, "soybeans_cbot", None, _ERAS, asof="2026-07-01")
    assert any(s["leg"][0] == "era" for s in specs)                  # era legs still emitted (no leg_mode)
    cur = next(s for s in specs if s["leg"] == ("current", None))
    assert cur["agg"] == "series"                                    # default preserved (row has no agg)


# ── D-W3.5.7: the current pace is the FRESHEST week <= asof (agg: latest); C2 stale-week lock ──────────
def test_current_pace_is_freshest_week_agg_latest():
    asof = "2026-07-01"
    cur = cq._node_specs(_node(), _ESR_ROW, "corn_cbot", None, _ERAS, asof=asof)[0]
    assert cur["agg"] == "latest" and cur["leg"] == ("current", None)

    weeks = [
        {"value": "410.2", "week_ending_date": "2025-08-16"},   # ~1yr old: rows[0] of an ASC series window
        {"value": "588.9", "week_ending_date": "2026-05-31"},
        {"value": "742.5", "week_ending_date": "2026-06-28"},   # the freshest week on/before asof
        {"value": "999.9", "week_ending_date": "2026-07-19"},   # AFTER asof -> the data-date guard excludes it
    ]
    seen = {}

    def qfn(sql):
        seen["sql"] = sql
        known = [w for w in weeks if w["week_ending_date"] <= asof]      # the as-of data-date guard
        if "DESC" in sql and "LIMIT 1" in sql:                          # the agg=latest freshest-first shape
            return [max(known, key=lambda w: w["week_ending_date"])]
        return sorted(known, key=lambda w: w["week_ending_date"])       # what an ASC series leg surfaces

    rec = cq._run_one(qfn, cur)
    assert rec["status"] == "ok"
    assert cq._float_val(rec) == 742.5                              # the FRESHEST week, NOT the ~1yr-old 410.2
    # the freshest-week semantics live in query.py's agg=latest branch: ORDER BY <date> DESC ... LIMIT 1,
    # under the CAST-as-text as-of guard on week_ending_date (a data column, storm-safe -- not projected).
    assert "ORDER BY week_ending_date DESC" in seen["sql"] and "LIMIT 1" in seen["sql"]
    assert "CAST(week_ending_date AS varchar) <= '2026-07-01'" in seen["sql"]


# ── D-W3.5.2: unit honesty -- 1000 MT flow, never MMT, and no delta path crosses ESR<->PSD ────────────
def _psd_erec(value, my, key):
    return {"query": {"commodity": "corn_cbot", "country": "United States", "period": f"MY{my}",
                      "metric": "exports_mt", "asof": f"{my}-06-01"},
            "rows": [{"value": str(value)}], "status": "ok",
            "node_key": key, "leg": ("era", 0), "era_idx": 0, "my": my}


def test_esr_unit_honesty_and_no_cross_node_delta():
    esr_key = ("corn_cbot", "us_export_pace")
    psd_key = ("corn_cbot", "export")
    esr_rec = {"query": {"commodity": "corn_cbot", "metric": "weekly_exports_1000mt",
                         "period": "2025-07-01..2026-07-01", "asof": "2026-07-01"},
               "rows": [{"value": "742.5", "unit": "1000 MT", "week_ending_date": "2026-06-28"}],
               "status": "ok", "node_key": esr_key, "leg": ("current", None), "era_idx": None, "my": None}
    psd = [_psd_erec(35147000, 2024, psd_key), _psd_erec(40000000, 2025, psd_key)]
    kept = [{"specs": [{"node_key": esr_key}], "row": _ESR_ROW},
            {"specs": [{"node_key": psd_key}], "row": _PSD_EXPORT_ROW}]
    calls: list = []
    lines, _trace, _dk = cq._assemble([esr_rec] + psd, kept, 0, calls)

    def _m(c):
        return (c.get("query") or {}).get("metric") or ""

    def _u(c):
        return (c["rows"][0] or {}).get("unit")

    esr_calls = [c for c in calls if _m(c) == "weekly_exports_1000mt"]
    assert len(esr_calls) == 1                                       # exactly one ESR pace [N]
    assert esr_calls[0]["rows"][0]["value"] == 742.5                 # scale 1: 742.5 stays 742.5 (no MMT ratio)
    assert _u(esr_calls[0]) == "1000 MT"
    # NO ESR delta/era_diff/pct row -- leg_mode:current means no era legs, so no within-ESR delta exists.
    assert not any(_m(c).startswith("weekly_exports_1000mt_") for c in calls)
    # unit is never conflated across the two nodes: every ESR row is 1000 MT; no PSD row wears 1000 MT.
    for c in calls:
        if _m(c).startswith("weekly_exports_1000mt"):
            assert _u(c) == "1000 MT"
        if _m(c).startswith("exports_mt"):
            assert _u(c) != "1000 MT"                                # PSD level/delta is MMT (or % for pct)
    # the PSD node DID exercise its delta path (proving ESR abstains structurally, not by empty data).
    assert any(_m(c) == "exports_mt_delta" for c in calls)
    # no DIVERGENCE/REROUTE line ever cites the ESR flow metric.
    assert not any("weekly_exports_1000mt" in ln and ("DIVERGENCE" in ln or "REROUTE" in ln) for ln in lines)


# ── D-W3.5.3: the ESR pace leg is NOT pairable (never seeds a cross-country reroute) ──────────────────
def _esr_group(country=None):
    return {"node": _node(), "row": _ESR_ROW, "country": country, "commodity": "corn_cbot",
            "specs": [{"node_key": ("corn_cbot", "us_export_pace")}], "eras": _ERAS,
            "key": ("corn_cbot", "us_export_pace"), "contract": "corn_cbot"}


def test_esr_leg_not_pairable_no_beneficiary():
    g = _esr_group()
    assert cq._pairable(g) is False                                  # weekly_exports_1000mt not in _TRADE_METRICS
    # the metric gate alone blocks pairing -- even a (hypothetical) resolved country cannot make it pairable.
    assert cq._pairable({**g, "country": "United States"}) is False
    units, pairs = cq._pair_units([g])
    assert units == [[g]]                                            # a lone CAP unit, no synthesized beneficiary
    assert pairs == []                                              # never a reroute candidate pair


# ── D-W3.5.4: coverage guard -- fireable on a covered contract, not on a non-ESR one ──────────────────
def _mock_candidate_config(monkeypatch, cc, index):
    """Simulate the D-W5 un-deferred candidate: map_row returns the active ESR row; a mocked contract
    index carries the proposed drivers. driver_fireable/census read map_row + _scope, both patched here."""
    monkeypatch.setattr(cq, "map_row", lambda ref: _ESR_ROW if ref == "esr_exports" else None)
    monkeypatch.setattr(cc, "_contract_index", lambda: index)


def test_driver_fireable_covered_vs_noncovered(monkeypatch):
    from leviathan.graphrag.numbers import cascade_census as cc
    corn = SimpleNamespace(contract="corn_cbot", drivers=[
        SimpleNamespace(id="us_export_pace", silver_ref="esr_exports", region="US")])
    cocoa = SimpleNamespace(contract="cocoa", drivers=[            # not in the ESR coverage set: no pace driver
        SimpleNamespace(id="grind_demand", silver_ref="consumption", region="US")])
    _mock_candidate_config(monkeypatch, cc, {"corn_cbot": corn, "cocoa": cocoa})
    assert cc.driver_fireable("corn_cbot", "us_export_pace") is True   # covered: ESR slug + country_rule none
    assert cc.driver_fireable("cocoa", "us_export_pace") is False      # not assigned there (coverage-set guard)


def test_census_esr_probe_fires_covered_darks_mis_assigned(monkeypatch):
    # mock the pg probe: the covered corn_cbot leg finds rows -> FIRES; a wrongly-assigned non-ESR slug
    # (cotton) finds ZERO rows -> DARK, never a firing leg. This is the D-W3.3 coverage guard at the pg layer
    # (in the true candidate config -- silver_esr removed from UNCERTIFIED_TABLES -- the dark REASON refines to
    # commodity-slug-miss; the VERDICT is DARK either way).
    from leviathan.graphrag.numbers import cascade_census as cc
    corn = SimpleNamespace(contract="corn_cbot", drivers=[
        SimpleNamespace(id="us_export_pace", silver_ref="esr_exports", region="US")])
    cotton = SimpleNamespace(contract="cotton", drivers=[
        SimpleNamespace(id="US_export_pace", silver_ref="esr_exports", region="US")])
    _mock_candidate_config(monkeypatch, cc, {"corn_cbot": corn, "cotton": cotton})

    def qfn(sql):
        return [{"value": "742.5", "week_ending_date": "2026-01-30"}] if "'corn_cbot'" in sql else []

    art = cc.census(asof="2026-02-15", query_fn=qfn)
    verdicts = {(leg["contract"], leg["node_id"]): leg["verdict"] for leg in art["legs"]}
    assert verdicts[("corn_cbot", "us_export_pace")] == cc.FIRES
    assert verdicts[("cotton", "US_export_pace")] == cc.DARK


# ── D-W3.5.5: a silent week narrates as ABSENCE (DECLINES-HONESTLY), never a fabricated pace.
#    BF-W2 vintage flip: silver_esr is now knowledge_semantics=vintage, so the empty-window status is
#    the vintage-honest 'not_known' ("vintage not yet published") instead of 'record_silent' -- same
#    invariant (no fabricated [N] row), vintage-correct phrasing. ─────────────────────────────────────
def test_esr_silent_week_narrates_absence_no_fabricated_pace():
    cur = cq._node_specs(_node(), _ESR_ROW, "corn_cbot", None, _ERAS, asof="2026-07-01")[0]
    rec = cq._run_one(lambda sql: [], cur)                          # no ESR rows in the current window
    assert rec["status"] == "not_known" and rec["rows"] == []
    kept = [{"specs": [{"node_key": cur["node_key"]}], "row": _ESR_ROW}]
    calls: list = []
    lines, trace, _dk = cq._assemble([rec], kept, 0, calls)
    assert calls == []                                              # NOTHING injected -- no fabricated [N] row
    absence = [ln for ln in lines if "vintage not yet published" in ln]
    assert len(absence) == 1 and "[N" not in absence[0]            # absence line, no citation handle
    assert trace and trace[0]["current_status"] == "not_known"
