"""P9-B quantified cascade — hermetic unit tests (no pg/Athena/LLM; stub query_fn(sql)->rows).
Covers: per-leg PIT pinning (era asof=window_end, current=session asof), the R3 forward-guidance clamp,
graceful degradation (error status, never raises), the marketing-year boundary helper (P8), the ratio
pre-scale normalizer + string-value float-cast (R9), the cross-era fork engine (R2), whole-node capping
(P7/F5), in-place [N] injection with continued count, the deferred-row loader, and the map lint."""
from __future__ import annotations

from types import SimpleNamespace

from leviathan.graphrag.numbers import cascade as cq


def _node(contract="wheat", ref="export", dates=None, event_dates=None):
    ev = []
    for i, d in enumerate(dates or []):
        ev.append({"date": d, "source": "usda_gain", "source_key": f"k{i}", "text": "t",
                   "event_date": (event_dates or {}).get(i)})
    return SimpleNamespace(contract=contract, node=f"drivers/{ref}", driver=ref,
                          prior={"silver_ref": ref}, evidence=ev)


def _sg(nodes):
    return SimpleNamespace(nodes=nodes, trace={}, fired_regimes=[])


# ── marketing-year boundaries (P8) ───────────────────────────────────────────────────────────────────
def test_covering_my_per_commodity():
    assert cq._covering_my("2010-08-05", "kc_wheat_kcbt") == 2010   # Jun-May year: Aug-2010 -> MY2010
    assert cq._covering_my("2010-03-01", "kc_wheat_kcbt") == 2009   # Mar-2010 -> MY2009 (started Jun-2009)
    assert cq._covering_my("2010-08-05", "corn") == 2009            # Sep-Aug year: Aug-2010 -> MY2009
    assert cq._covering_my("2010-10-01", "corn") == 2010
    assert cq._covering_my("garbage", "corn") is None


def test_my_span_widens_single_year():
    assert cq._my_span(("2010-08-05", "2011-02-01"), "wheat") == [2009, 2010]   # crosses no boundary? widened
    span = cq._my_span(("2010-07-01", "2010-08-01"), "wheat")
    assert len(span) >= 2                                            # single-MY episode widens backward (R2)


# ── fetch_window: PIT pinning + clamp + graceful degradation ─────────────────────────────────────────
def test_fetch_window_pins_era_asof_to_window_end():
    seen = {}

    def qfn(sql):
        seen["sql"] = sql
        return []

    cq.fetch_window(qfn, table="silver_psd", metric="exports_mt", commodity="wheat",
                    country="Russia", t1=None, t2=None, asof="2011-02-01", agg="latest",
                    period=2010, period_type="marketing_year")
    assert "2011-02-01" in seen["sql"]                               # the era leg's own asof, not today
    assert "market_year" in seen["sql"] and "2010" in seen["sql"]


def test_fetch_window_clamp_future_unpublished():
    def qfn(sql):  # noqa: ARG001
        raise AssertionError("no SQL may fire on a clamped-empty window")

    rec = cq.fetch_window(qfn, table="silver_fred_fx", metric="brl_usd", commodity=None, country=None,
                          t1="2026-09-01", t2="2026-12-01", asof="2026-07-10", period_type="date")
    assert rec["status"] == "future_unpublished" and rec["rows"] == []


def test_fetch_window_error_never_raises():
    def qfn(sql):  # noqa: ARG001
        raise RuntimeError("pg down")

    rec = cq.fetch_window(qfn, table="silver_psd", metric="exports_mt", commodity="wheat",
                          country="Russia", t1=None, t2=None, asof="2011-02-01",
                          period=2010, period_type="marketing_year")
    assert rec["status"] == "error" and rec["rows"] == [] and "pg down" in rec.get("error", "")


def test_fetch_window_bad_spec_is_error_not_raise():
    rec = cq.fetch_window(lambda sql: [], table="no_such_table", metric="x", commodity=None, country=None,
                          t1=None, t2=None, asof="2020-01-01", period=2019, period_type="marketing_year")
    assert rec["status"] == "error"


# ── window derivation: the R3 primary clamp ──────────────────────────────────────────────────────────
def test_derive_windows_clamps_forward_guidance():
    n = _node(dates=["2010-08-05", "2010-09-10"], event_dates={0: "2026-12-31"})   # guidance dated PAST asof
    wins = cq._derive_windows(n, None, "2010-12-01")
    assert wins and all(w[1] <= "2010-12-01" for w in wins)          # every end clamped to the session asof


def test_derive_windows_drops_fully_future_episode():
    n = _node(dates=["2026-09-01", "2026-10-01"])                    # entirely after asof
    assert cq._derive_windows(n, None, "2020-01-01") == []


def test_derive_windows_empty_evidence():
    assert cq._derive_windows(_node(dates=[]), None, "2020-01-01") == []


# ── normalizer + float-cast (R9) + provenance (R10) ─────────────────────────────────────────────────
def test_prescaled_floatcasts_string_and_scales_ratio():
    rec = {"query": {"metric": "su_ratio"}, "rows": [{"value": "0.36", "unit": "ratio",
                                                      "release_date": "2010-11-09"}], "status": "ok"}
    row = {"metric": "su_ratio", "scale": 100, "narrate_unit": "%"}
    out = cq._prescaled(rec, row, 1)
    assert out["rows"][0]["value"] == 36.0 and out["rows"][0]["unit"] == "%"
    assert out["rows"][0]["_provenance"]["release_date"] == "2010-11-09"   # PIT guard column carried (R10)
    assert rec["rows"][0]["value"] == "0.36"                         # source record untouched (deep copy)


def test_prescaled_comma_string():
    rec = {"query": {}, "rows": [{"value": "2,462,000"}], "status": "ok"}
    out = cq._prescaled(rec, {"scale": 0.000001, "narrate_unit": "MMT", "metric": "exports_mt"}, 1)
    assert abs(out["rows"][0]["value"] - 2.462) < 1e-9


# ── fork engine (R2) ─────────────────────────────────────────────────────────────────────────────────
def _ok(val, my=None):
    return {"query": {}, "rows": [{"value": str(val)}], "status": "ok", "my": my}


def test_era_delta_needs_two_rows():
    row = {"scale": 1, "narrate_unit": "MMT", "metric": "exports_mt"}
    assert cq._era_delta([_ok(10)], row) is None                     # 1 row -> no within-era delta -> no fork
    assert cq._era_delta([_ok(10), _ok(14)], row) == 4.0


def test_pct_change():
    row = {"scale": 1, "narrate_unit": "MMT", "metric": "exports_mt"}
    assert cq._pct_change([_ok(10), _ok(11.8)], row) == 18.0
    assert cq._pct_change([_ok(0), _ok(5)], row) is None             # zero base -> no percent claim


def test_divergence_two_eras_opposite_signs():
    row = {"scale": 1, "narrate_unit": "MMT", "metric": "exports_mt"}
    div, a, b = cq._divergence({0: +4.0, 1: -2.0}, {0: [], 1: []}, None, row)
    assert div and a == 4.0 and b == -2.0
    div, _, _ = cq._divergence({0: +4.0, 1: +1.0}, {0: [], 1: []}, None, row)
    assert not div                                                   # same sign -> no fork claimed


def test_divergence_era_vs_current():
    row = {"scale": 1, "narrate_unit": "MMT", "metric": "exports_mt"}
    eras = {0: [_ok(10), _ok(14)]}                                   # era rose (+4)
    cur = _ok(9)                                                     # current below era end (-5)
    div, a, b = cq._divergence({0: +4.0}, eras, cur, row)
    assert div and a == 4.0 and b == -5.0


def test_divergence_never_without_two_signals():
    row = {"scale": 1, "narrate_unit": "MMT", "metric": "exports_mt"}
    assert cq._divergence({}, {}, None, row) == (False, 0.0, 0.0)


# ── quantify: cap on whole nodes + in-place injection + N continuation ───────────────────────────────
def test_quantify_caps_whole_nodes_and_injects_in_place(monkeypatch):
    # 3 mapped nodes x 5 specs each (2 eras x 2 MYs + current); cap 10 -> 2 WHOLE nodes kept, never split
    monkeypatch.setattr(cq, "CASCADE_CAP", 10)
    calls_fired = []

    def qfn(sql):
        calls_fired.append(sql)
        return [{"value": "10", "market_year": 2009}]

    nodes = [_node(contract=c, ref="export", dates=["2010-08-05", "2010-11-20"])
             for c in ("wheat", "corn", "soybeans")]
    extra = [{"query": {"metric": "pre"}, "rows": [{"value": "1"}]}]  # pre-existing hybrid call
    block, trace = cq.quantify(_sg(nodes), None, qfn=qfn, asof="2011-06-01", near="2010",
                               extra_number_calls=extra)
    assert block and block.startswith("OBSERVED CASCADE NUMBERS")
    assert len(extra) > 1                                            # appended IN PLACE
    assert "[N2]" in block and "[N1]" not in block                   # N-count CONTINUES past the base call
    kept_nodes = {tuple(t["node_key"]) for t in trace}
    assert len(kept_nodes) == 2                                      # third node dropped WHOLE (cap)


def test_quantify_unmapped_ref_stays_qualitative():
    n = _node(ref="no_such_ref", dates=["2010-08-05"])
    block, trace = cq.quantify(_sg([n]), None, qfn=lambda s: [], asof="2011-06-01", near=None,
                               extra_number_calls=[])
    assert block is None and trace == []


def test_quantify_never_raises_on_hostile_inputs():
    bad = SimpleNamespace(contract=None, node=None, driver=None, prior=None, evidence=None)
    block, trace = cq.quantify(_sg([bad]), None, qfn=lambda s: [], asof="2020-01-01", near=None,
                               extra_number_calls=[])
    assert block is None


# ── map loader + deferred rows ───────────────────────────────────────────────────────────────────────
def test_load_map_drops_deferred_rows():
    m = cq.load_map()
    assert "export" in m and m["export"]["table"] == "silver_psd"
    assert "esr_exports" not in m and "weather_z" not in m           # deferred -> inert
    assert cq.map_row("esr_exports") is None and cq.map_row(None) is None


def test_cascade_map_lint_clean():
    from leviathan.graphrag.config_check import check_cascade_map
    assert check_cascade_map() == []


def test_cascade_map_lint_catches_uncertified_active(monkeypatch):
    monkeypatch.setattr(cq, "load_map",
                        lambda: {"bad": {"table": "silver_esr", "metric": "weekly_exports_mt",
                                         "period_type": "date", "scale": 1}})
    cq.load_map.cache_clear if hasattr(cq.load_map, "cache_clear") else None
    from leviathan.graphrag.config_check import check_cascade_map
    errs = check_cascade_map()
    assert errs and any("uncertified" in e for e in errs)


# ── the answer.py seam (flag + breaker + wiring; quantify itself is covered above) ───────────────────
def _seam_harness(monkeypatch, quantify_stub):
    from leviathan.graphrag import answer as an
    from leviathan.graphrag import evidence as ev
    from leviathan.graphrag.numbers import cascade as cq_mod

    import tests.unit.test_answer as ta
    gr = ta._graph()
    monkeypatch.setattr(ev, "embed", lambda texts, **k: [[1.0 if "frost" in t.lower() else 0.0] for t in texts])
    monkeypatch.setattr(an, "_pgnumbers_live", lambda: True)
    monkeypatch.setattr(cq_mod, "quantify", quantify_stub)
    captured = {}

    def fake_call(system, user, *, model, tool):
        captured["user"] = user
        return {"tldr": "frost tightens [1]", "mechanism": "## Mechanism\nfrost cuts output [1]",
                "diagram_mermaid": "", "sources": [{"ref": 1, "source": "GAIN", "date": "2021-07-20",
                                                    "note": "frost"}]}

    def fake_retrieve(q, node, *, k, asof=None, near=None):
        return [{"date": "2021-07-20", "source": "GAIN", "source_key": f"s3://{node}", "text": "July frost hit"}]

    out = an.answer("trace how a coffee frost spikes price", graph=gr, planner="l2", asof="2021-08-01",
                    retrieve=fake_retrieve, call=fake_call, route_fn=lambda q, g: ["arabica_coffee"],
                    numbers_lookup=lambda sql: [])
    return out, captured


def test_seam_injects_block_and_trace(monkeypatch):
    def stub(sg, graph, *, qfn, asof, near, extra_number_calls):
        extra_number_calls.append({"query": {"metric": "exports_mt"}, "rows": [{"value": 2.46}], "status": "ok"})
        return "OBSERVED CASCADE NUMBERS (test):\n- [N1] wheat exports 2.46 MMT", [{"divergence": False}]

    out, captured = _seam_harness(monkeypatch, stub)
    assert "OBSERVED CASCADE NUMBERS" in captured["user"]            # the block reached the volatile tail
    assert out["trace"].get("quantify") == [{"divergence": False}]


def test_seam_flag_off_skips_quantify(monkeypatch):
    def stub(*a, **k):
        raise AssertionError("quantify must not run with the flag off")

    monkeypatch.setenv("GRAPHRAG_CASCADE_QUANT", "off")
    out, captured = _seam_harness(monkeypatch, stub)
    assert "OBSERVED CASCADE NUMBERS" not in captured["user"]
    assert "quantify" not in out["trace"]


def test_seam_quantify_crash_degrades_qualitative(monkeypatch):
    def stub(*a, **k):
        raise RuntimeError("boom")

    out, captured = _seam_harness(monkeypatch, stub)
    assert out["answer"]                                             # the turn survived (no floor, no raise)
    assert out["trace"].get("quantify_error") == "RuntimeError"
