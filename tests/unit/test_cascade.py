"""P9-B quantified cascade — hermetic unit tests (no pg/Athena/LLM; stub query_fn(sql)->rows).
Covers: per-leg PIT pinning (era asof=window_end, current=session asof), the R3 forward-guidance clamp,
graceful degradation (error status, never raises), the marketing-year boundary helper (P8), the ratio
pre-scale normalizer + string-value float-cast (R9), the cross-era fork engine (R2), whole-node capping
(P7/F5), in-place [N] injection with continued count, the deferred-row loader, the map lint, and the
cross-country reroute (RF-3 pairing/beneficiary + pair-atomic cap, RF-4 firing/decline, probe-shaped)."""
from __future__ import annotations

from types import SimpleNamespace

from leviathan.graphrag.numbers import cascade as cq


def _node(contract="wheat", ref="export", dates=None, event_dates=None, region="US", nid=None):
    ev = []
    for i, d in enumerate(dates or []):
        ev.append({"date": d, "source": "usda_gain", "source_key": f"k{i}", "text": "t",
                   "event_date": (event_dates or {}).get(i)})
    # id-based, like the REAL planner.GroundedNode (RF-1). The old stub fabricated node=/driver= attrs the
    # production object never had -- the masking class that let F0 ship (every prod node keyed (contract,None)).
    return SimpleNamespace(contract=contract, id=nid or ref, prior={"silver_ref": ref, "region": region},
                           evidence=ev)


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


# ── F2: cross-era endpoint difference (the citable 'gain above the MY<yy> baseline') ─────────────────
def test_cross_era_diff_two_eras_endpoint_difference():
    row = {"scale": 1, "narrate_unit": "MMT", "metric": "exports_mt"}
    eras = {0: [_ok(10, 2020), _ok(14, 2021)],                       # era0 endpoint = MY2021 level 14
            1: [_ok(20, 2024), _ok(16, 2025)]}                        # era1 endpoint = MY2025 level 16
    diff, label, later = cq._cross_era_diff({0: +4.0, 1: -4.0}, eras, None, row)
    assert abs(diff - 2.0) < 1e-9                                     # 16 - 14 (later minus baseline)
    assert label == "MY2021->MY2025"                                 # chronological, earlier -> later
    assert later["my"] == 2025                                       # the later endpoint stamps provenance/asof


def test_cross_era_diff_scales_to_narrate_unit():
    row = {"scale": 0.000001, "narrate_unit": "MMT", "metric": "exports_mt"}
    eras = {0: [_ok(14000000, 2021)], 1: [_ok(16758000, 2025)]}      # 1 endpoint each is enough for the diff
    diff, label, _ = cq._cross_era_diff({0: +1.0, 1: -1.0}, eras, None, row)
    assert abs(diff - 2.758) < 1e-9 and label == "MY2021->MY2025"    # pre-scaled MMT, the RCA magnitude


def test_cross_era_diff_era_vs_current_equals_divergence_b():
    row = {"scale": 1, "narrate_unit": "MMT", "metric": "exports_mt"}
    eras = {0: [_ok(10, 2020), _ok(14, 2021)]}                       # era rose to MY2021 level 14
    cur = _ok(9, 2022)                                               # current below the era end (-5)
    diff, label, later = cq._cross_era_diff({0: +4.0}, eras, cur, row)
    assert abs(diff - (-5.0)) < 1e-9                                 # == _divergence's b (cur - era end)
    assert label == "MY2021->MY2022" and later is cur


def test_cross_era_diff_none_when_endpoint_missing():
    row = {"scale": 1, "narrate_unit": "MMT", "metric": "exports_mt"}
    eras = {0: [], 1: [_ok(20, 2024), _ok(16, 2025)]}                # era0 has no ok endpoint
    assert cq._cross_era_diff({0: +4.0, 1: -4.0}, eras, None, row) is None


def test_delta_call_period_override_stamps_era_diff_row():
    rec = {"query": {"commodity": "wheat", "country": "Russia", "period": "MY2025",
                     "metric": "exports_mt", "asof": "2025-06-01"},
           "rows": [{"value": "16", "release_date": "2025-05-01"}]}
    row = {"metric": "exports_mt", "narrate_unit": "MMT", "scale": 1}
    call = cq._delta_call(rec, row, 2.758, 9, kind="era_diff", period="MY2021->MY2025")
    assert call["query"]["metric"] == "exports_mt_era_diff"          # not the plain _delta suffix
    assert call["query"]["period"] == "MY2021->MY2025"               # span label overrides the leg period
    assert call["rows"][0]["value"] == 2.758 and call["rows"][0]["unit"] == "MMT"
    assert call["rows"][0]["_provenance"]["release_date"] == "2025-05-01"   # later endpoint provenance (R10)
    # no override -> the inherited leg period is untouched (existing delta/pct rows unchanged)
    plain = cq._delta_call(rec, row, 2.0, 3, kind="delta")
    assert plain["query"]["period"] == "MY2025" and plain["query"]["metric"] == "exports_mt_delta"


def _erec(value, my, era_idx, key=("wheat", "export")):
    return {"query": {"commodity": "wheat", "country": "Russia", "period": f"MY{my}",
                      "metric": "exports_mt", "asof": f"{my}-06-01"},
            "rows": [{"value": str(value)}], "status": "ok",
            "node_key": key, "leg": ("era", era_idx), "era_idx": era_idx, "my": my}


def _kept_wheat(key=("wheat", "export")):
    row = {"table": "silver_psd", "metric": "exports_mt", "scale": 1, "narrate_unit": "MMT",
           "period_type": "marketing_year"}
    return [{"specs": [{"node_key": key}], "row": row}]


def _divergence_line(lines):
    return next((ln for ln in lines if ln.startswith("DIVERGENCE on")), None)


def test_assemble_injects_era_diff_row_with_handle_on_cross_era_line_only():
    # era0 rose (+4), era1 fell (-4): opposite signs -> divergence fires cross-era; the endpoint diff
    # (MY2021 level 14 -> MY2025 level 16 = +2) must be injected as a citable [N] row whose handle rides
    # ONLY the cross-era line stating that value. Review fold (major #3): the DIVERGENCE line's visible
    # numbers are the within-era deltas a/b -- a handle there would prime 'a vs b [Nx]' narrations that
    # mismatch the endpoint-diff row and strip, reintroducing the exact strip F2 prevents.
    records = [_erec(10, 2020, 0), _erec(14, 2021, 0), _erec(20, 2024, 1), _erec(16, 2025, 1)]
    calls: list = []
    lines, trace, _dk = cq._assemble(records, _kept_wheat(), 0, calls)
    injected = [c for c in calls if (c.get("query") or {}).get("metric") == "exports_mt_era_diff"]
    assert len(injected) == 1                                        # exactly ONE cross-era row
    ic = injected[0]
    assert ic["query"]["period"] == "MY2021->MY2025" and ic["rows"][0]["value"] == 2.0
    n = calls.index(ic) + 1                                          # base=0 -> [N] is 1-indexed position
    xline = next(ln for ln in lines if "cross-era change in exports_mt (MY2021->MY2025)" in ln)
    assert f"[N{n}]" in xline and "+2 MMT" in xline
    dline = _divergence_line(lines)
    assert dline is not None and f"[N{n}]" not in dline              # NO handle on the a/b prose line
    assert any(t.get("divergence") for t in trace)


def test_assemble_no_era_diff_row_when_no_divergence():
    # both eras rose (same sign): NO divergence -> NO cross-era row injected (no row bloat) and no line.
    records = [_erec(10, 2020, 0), _erec(14, 2021, 0), _erec(20, 2024, 1), _erec(26, 2025, 1)]
    calls: list = []
    lines, _trace, _dk = cq._assemble(records, _kept_wheat(), 0, calls)
    assert not any((c.get("query") or {}).get("metric") == "exports_mt_era_diff" for c in calls)
    assert _divergence_line(lines) is None
    assert not any("cross-era change" in ln for ln in lines)


# ── Clause B' (thin-turn honesty fix): human era label, no bare era0/era1 integer in any rendered line ─
def test_era_label_maps_index_to_human_words():
    assert cq._era_label(0) == "earlier era"
    assert cq._era_label(1) == "later era"
    assert cq._era_label("current") == "current"
    assert cq._era_label(0, {"period": "MY2016->MY2017"}) == "MY2016->MY2017"   # MY span when the row carries one
    assert cq._era_label(2) == "later era"                                       # higher indices collapse (no bare 2)


def test_three_formatters_never_emit_bare_era_index():
    # the Row-3 false-strip: 'era0'/'within-era0' is mirrored into prose and stripped as an uncited magnitude;
    # all THREE render sites (_fmt_line :717, _fmt_delta :723, _fmt_pct :727) must emit human labels instead.
    row = {"metric": "exports_mt", "narrate_unit": "MMT", "scale": 1}
    rec = {"query": {"commodity": "wheat", "period": "MY2010", "metric": "exports_mt", "asof": "2010-06-01"},
           "rows": [{"value": "3.9"}]}
    line = cq._fmt_line(rec, row, 4, era=0)
    dline = cq._fmt_delta(row, -5.058, 5, era=0)
    pline = cq._fmt_pct(row, -3.36, 6, era=1)
    cur = cq._fmt_line({**rec, "query": {**rec["query"], "period": "MY2025"}}, row, 7, era="current")
    for s in (line, dline, pline, cur):
        assert "era0" not in s and "era1" not in s and "within-era" not in s
    assert "earlier era" in line and "earlier era" in dline and "later era" in pline
    assert "(current," in cur                                                    # the current leg keeps its label


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
    block, trace, _rt = cq.quantify(_sg(nodes), None, qfn=qfn, asof="2011-06-01", near="2010",
                                    extra_number_calls=extra)
    assert block and block.startswith("OBSERVED CASCADE NUMBERS")
    assert len(extra) > 1                                            # appended IN PLACE
    assert "[N2]" in block and "[N1]" not in block                   # N-count CONTINUES past the base call
    kept_nodes = {tuple(t["node_key"]) for t in trace}
    assert len(kept_nodes) == 2                                      # third node dropped WHOLE (cap)


def test_quantify_unmapped_ref_stays_qualitative():
    n = _node(ref="no_such_ref", dates=["2010-08-05"])
    block, trace, rtrace = cq.quantify(_sg([n]), None, qfn=lambda s: [], asof="2011-06-01", near=None,
                                       extra_number_calls=[])
    assert block is None and trace == [] and rtrace == []


def test_quantify_never_raises_on_hostile_inputs():
    bad = SimpleNamespace(contract=None, id=None, prior=None, evidence=None)
    block, trace, _rt = cq.quantify(_sg([bad]), None, qfn=lambda s: [], asof="2020-01-01", near=None,
                                    extra_number_calls=[])
    assert block is None


# ── RF-1: node identity on the REAL production object (the F0 regression) ───────────────────────────
def test_production_topology_seed_plus_two_drivers_all_survive(monkeypatch):
    """rrv1 1d MANDATORY shape: REAL planner.GroundedNode objects -- one unmapped depth-0 contract SEED plus
    TWO mapped export drivers on ONE contract. Pre-RF-1 every prod node keyed (contract, None): the seed
    claimed the slot first and evicted EVERY driver, so quantify returned (None, []) on every real serving
    turn (the cascade was entirely dark, not under-covering)."""
    from leviathan.graphrag import planner as pl

    def _driver(did, region):
        n = pl.GroundedNode(kind="driver", id=did, contract="wheat", depth=1, relevance=0.9,
                            prior={"silver_ref": "export", "region": region})
        n.evidence = [{"date": d, "source": "usda_gain", "source_key": f"{did}{i}", "text": "t"}
                      for i, d in enumerate(["2010-08-05", "2010-09-10"])]
        return n

    seed = pl.GroundedNode(kind="contract", id="wheat", contract="wheat", depth=0, relevance=1.0,
                           prior={"target_metrics": ["price"], "via_edge": None})
    d1, d2 = _driver("russia_export_tax", "Russia"), _driver("export_pace_lag", "US")
    sg = pl.Subgraph(seeds=["wheat"], nodes=[seed, d1, d2])

    sel = cq._select_nodes(sg, None)
    assert len(sel) == 3                                             # the seed no longer evicts the drivers
    assert len({(n.contract, n.id) for n in sel}) == 3               # three DISTINCT node keys

    seen = []

    def qfn(sql):
        seen.append(sql)
        return [{"value": "10", "market_year": 2009}]

    block, trace, _rt = cq.quantify(sg, None, qfn=qfn, asof="2011-06-01", near="2010",
                                    extra_number_calls=[])
    node_ids = {t["node_key"][1] for t in trace}
    assert node_ids == {"russia_export_tax", "export_pace_lag"}      # specs for BOTH drivers, none for the seed
    assert block and block.startswith("OBSERVED CASCADE NUMBERS")
    # RF-2 rides the same topology: each driver leg queries ITS OWN region's country, not the primary
    assert any("Russia" in s for s in seen) and any("United States" in s for s in seen)


# ── RF-2: region -> country resolution matrix ────────────────────────────────────────────────────────
def test_scope_region_rule_resolves_clean_tokens():
    row = {"table": "silver_psd", "country_rule": "region"}
    assert cq._scope(_node(ref="export", region="Russia"), row) == ("wheat", "Russia")
    assert cq._scope(_node(ref="export", region="US"), row) == ("wheat", "United States")


def test_scope_region_rule_compound_and_missing_skip():
    # compounds/prose NEVER resolve and NEVER fall back to primary (rrv1 2c: primary-fallback stamps the
    # wrong country's numbers with country=<primary> in the [N] citation); missing region = the same skip.
    row = {"table": "silver_psd", "country_rule": "region"}
    for region in ("Russia_Ukraine", "Global", None):
        _c, country = cq._scope(_node(ref="export", region=region), row)
        assert country is cq.SKIP_NODE


def test_quantify_skips_unresolved_region_node_entirely():
    n = _node(ref="export", dates=["2010-08-05", "2010-09-10"], region="Russia_Ukraine")

    def qfn(sql):  # noqa: ARG001
        raise AssertionError("no SQL may fire for an unresolved region leg")

    block, trace, rtrace = cq.quantify(_sg([n]), None, qfn=qfn, asof="2011-06-01", near=None,
                                       extra_number_calls=[])
    assert block is None and trace == [] and rtrace == []            # qualitative, never mixed/mislabeled


def test_scope_primary_and_none_rules_unchanged(monkeypatch):
    from leviathan.graphrag import silverleg as slv
    monkeypatch.setattr(slv, "_primary_country", lambda c: "united_states")
    n = _node(ref="production", region="Australia")                  # region present but the rule is primary
    assert cq._scope(n, {"table": "silver_psd"}) == ("wheat", "United States")
    assert cq._scope(n, {"table": "silver_psd", "country_rule": "none"}) == ("wheat", None)


def test_region_row_fx_currency_pick():
    # the ars_usd/brl_usd fold-forward fix: the region's currency picks the metric; country stays None
    # (silver_fred_fx has no country column); a resolved region with NO fx column (Canada) skips honestly.
    row = cq.load_map()["fred_fx_macro"]
    ars = _node(contract="soybeans", ref="fred_fx_macro", region="Argentina")
    assert cq._region_row(ars, row)["metric"] == "ars_usd"
    assert cq._scope(ars, row) == ("soybeans_cbot", None)
    brl = _node(contract="soybeans", ref="fred_fx_macro", region="Brazil")
    assert cq._region_row(brl, row)["metric"] == "brl_usd"
    _c, country = cq._scope(_node(contract="soybeans", ref="fred_fx_macro", region="Canada"), row)
    assert country is cq.SKIP_NODE


# ── RF-3/RF-4: the cross-country reroute (probe-shaped fixtures; RF-0 verdicts pinned 2026-07-11) ────
def _psd_qfn(values):
    """silver_psd stub keyed on the generated SQL's own predicates (country = '<c>', market_year = <my>).
    An unmatched (metric, country, MY) returns [] -> vintage not_known: the honest-absence path the
    reroute must respect (the probe-pinned foreign vintage lag)."""
    def qfn(sql):
        for (metric, country, my), v in values.items():
            if metric in sql and f"country = '{country}'" in sql and f"market_year = {my}" in sql:
                return [{"value": str(v), "market_year": my}]
        return []
    return qfn


_WHEAT_2010 = {  # RF-0 P2 pinned: Russia collapse vs US pick-up over [MY2009, MY2010] -- OPPOSITE signs
    ("exports_mt", "Russia", 2009): 18556000, ("exports_mt", "Russia", 2010): 3983000,
    ("exports_mt", "United States", 2009): 23931000, ("exports_mt", "United States", 2010): 35147000,
}

_SOY_2018 = {  # RF-0 P2 pinned: US/Brazil exports AND China imports all FELL over [MY2017, MY2018]
    ("exports_mt", "United States", 2017): 57950000, ("exports_mt", "United States", 2018): 47600000,
    ("exports_mt", "Brazil", 2017): 76200000, ("exports_mt", "Brazil", 2018): 74951000,
    ("imports_mt", "China", 2017): 94100000, ("imports_mt", "China", 2018): 82544000,
}


def _primary_us(monkeypatch):
    from leviathan.graphrag import silverleg as slv
    monkeypatch.setattr(slv, "_primary_country", lambda c: "united_states")


def test_reroute_wheat_shaped_pair_fires(monkeypatch):
    """Foreign shock (Russia export collapse) + the SYNTHESIZED US beneficiary leg: opposite signs over
    the shared MY2009-MY2010 anchor window -> the exact REROUTE line, a pair-level trace entry, and BOTH
    countries' delta rows injected (value-checkable). The beneficiary node_key encodes the country (rrv1
    3c) so the two legs' deltas stay pure per-country, never interleaved."""
    _primary_us(monkeypatch)
    n = _node(contract="wheat", ref="export", region="Russia", dates=["2010-08-05", "2010-09-10"])
    extra = []
    block, trace, rtrace = cq.quantify(_sg([n]), None, qfn=_psd_qfn(_WHEAT_2010), asof="2011-06-01",
                                       near="2010", extra_number_calls=extra)
    assert ("REROUTE on exports_mt: Russia -14.573 vs United States +11.216 (MMT) over MY2009-MY2010 "
            "-- render '## Where the record disagrees' and show BOTH legs BY COUNTRY; "
            "the flow rerouted, do not blend.") in block
    assert len(rtrace) == 1
    t = rtrace[0]
    assert set(t) == {"contract", "metric", "countryA", "dA", "countryB", "dB", "window", "reroute"}
    assert t["contract"] == "wheat" and t["metric"] == "exports_mt" and t["reroute"] is True
    assert t["countryA"] == "Russia" and t["countryB"] == "United States"
    assert t["window"] == "MY2009-MY2010"
    assert abs(t["dA"] - (-14.573)) < 1e-9 and abs(t["dB"] - 11.216) < 1e-9   # pure per-country deltas
    keys = {tuple(t["node_key"]) for t in trace}                     # shock 2-tuple + country-encoded 3-tuple
    assert keys == {("wheat", "export"), ("wheat", "export", "United States")}
    deltas = {((c.get("query") or {}).get("country"), c["rows"][0]["value"]) for c in extra
              if (c.get("query") or {}).get("metric") == "exports_mt_delta"}
    assert {("Russia", -14.573), ("United States", 11.216)} <= deltas   # both magnitudes value-check


def test_reroute_soy_shaped_same_sign_does_not_fire(monkeypatch):
    """The ENGINE-HONESTY case (probe-pinned): US exports, Brazil exports AND China imports all fell over
    the shared window -- every candidate pair (export/export + export/import) declines, and same-sign
    pairs record NOTHING (a recorded candidate would legitimize a hallucinated fork heading)."""
    _primary_us(monkeypatch)
    dates = ["2018-07-06", "2018-09-10"]
    us = _node(contract="soybeans", ref="export", region="US", dates=dates, nid="export_pace_lag")
    br = _node(contract="soybeans", ref="export", region="Brazil", dates=dates, nid="brazil_export")
    cn = _node(contract="soybeans", ref="import", region="China", dates=dates, nid="china_soybean_import")
    block, trace, rtrace = cq.quantify(_sg([us, br, cn]), None, qfn=_psd_qfn(_SOY_2018),
                                       asof="2019-06-01", near="2018", extra_number_calls=[])
    assert rtrace == [] and "REROUTE" not in block
    assert all(len(t["node_key"]) == 2 for t in trace)               # natural pairs: NO synthesized leg
    assert "-10.35" in block and "-1.249" in block and "-11.556" in block   # probe magnitudes still narrate


def test_reroute_not_known_foreign_leg_declines(monkeypatch):
    """The probe-pinned FOREIGN VINTAGE LAG: at a tight asof the Russia event-MY row is not yet published
    (not_known) -> one ok row -> no within-era delta on the shock leg -> the reroute DECLINES and records
    NOTHING, even though the US beneficiary leg resolved a signed delta."""
    _primary_us(monkeypatch)
    vals = dict(_WHEAT_2010)
    del vals[("exports_mt", "Russia", 2010)]                         # unknown until the ~2011-06 release
    n = _node(contract="wheat", ref="export", region="Russia", dates=["2010-08-05", "2010-09-10"])
    block, trace, rtrace = cq.quantify(_sg([n]), None, qfn=_psd_qfn(vals), asof="2011-06-01",
                                       near="2010", extra_number_calls=[])
    assert rtrace == [] and "REROUTE" not in (block or "")
    shock = next(t for t in trace if tuple(t["node_key"]) == ("wheat", "export"))
    assert "not_known" in shock["era_statuses"][0]                   # the absence is carried, not papered over


def test_reroute_pair_atomic_cap_drops_shock_and_beneficiary_together(monkeypatch):
    """Pair-atomic cap: a budget that fits the shock (3 specs) but not shock+beneficiary (5) drops BOTH --
    a shock kept without its beneficiary can never fire and would spend its lookups for nothing."""
    _primary_us(monkeypatch)
    monkeypatch.setattr(cq, "CASCADE_CAP", 6)                        # corn 3 + shock 3 fits; +ben 2 does not
    corn = _node(contract="corn", ref="export", region="US", dates=["2010-08-05", "2010-09-10"])
    shock = _node(contract="wheat", ref="export", region="Russia", dates=["2010-08-05", "2010-09-10"])
    block, trace, rtrace = cq.quantify(_sg([corn, shock]), None, qfn=_psd_qfn(_WHEAT_2010),
                                       asof="2011-06-01", near="2010", extra_number_calls=[])
    keys = {tuple(t["node_key"]) for t in trace}
    assert keys == {("corn_cbot", "export")}                         # wheat pair dropped WHOLE, corn kept
    assert rtrace == [] and "REROUTE" not in (block or "")


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


def test_cascade_map_lint_flags_unknown_region_token(tmp_path, monkeypatch):
    # RF-2 census: a region-ruled driver whose token is in NEITHER resolve nor unresolved fails the build
    # (the E4 alias/waiver precedent -- an unmapped token must never silently mislabel a country at serve time)
    from leviathan.causal import blurb as bl
    causal = tmp_path / "causal"
    causal.mkdir()
    (causal / "fixture.yaml").write_text(
        "contract: test_contract\n"
        "drivers:\n"
        "- {id: atlantis_export_ban, type: policy_event, sign: '+', mechanism: m, "
        "silver_ref: export, region: Atlantis}\n", encoding="utf-8")
    monkeypatch.setattr(bl, "_CAUSAL_DIR", causal)
    from leviathan.graphrag.config_check import check_cascade_map
    errs = check_cascade_map()
    assert any("region_map census" in e and "Atlantis" in e for e in errs)


def test_cascade_map_lint_flags_phantom_fx_currency(tmp_path, monkeypatch):
    # a resolve currency must be a REAL silver_fred_fx column: 'eur' -> eur_usd does not exist
    from leviathan.causal import blurb as bl
    causal = tmp_path / "causal"
    causal.mkdir()                                                   # empty causal dir: census part inert
    monkeypatch.setattr(bl, "_CAUSAL_DIR", causal)
    monkeypatch.setattr(cq, "load_region_map",
                        lambda: {"resolve": {"EU": {"country": "European Union", "currency": "eur"}},
                                 "unresolved": []})
    from leviathan.graphrag.config_check import check_cascade_map
    errs = check_cascade_map()
    assert any("eur_usd" in e for e in errs)


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
    rpair = {"contract": "wheat", "metric": "exports_mt", "countryA": "Russia", "dA": -14.573,
             "countryB": "United States", "dB": 11.216, "window": "MY2009-MY2010", "reroute": True}

    def stub(sg, graph, *, qfn, asof, near, extra_number_calls):
        extra_number_calls.append({"query": {"metric": "exports_mt"}, "rows": [{"value": 2.46}], "status": "ok"})
        return "OBSERVED CASCADE NUMBERS (test):\n- [N1] wheat exports 2.46 MMT", [{"divergence": False}], [rpair]

    out, captured = _seam_harness(monkeypatch, stub)
    assert "OBSERVED CASCADE NUMBERS" in captured["user"]            # the block reached the volatile tail
    assert out["trace"].get("quantify") == [{"divergence": False}]
    assert out["trace"].get("quantify_reroute") == [rpair]           # RF-4: stashed exactly like quantify


def test_seam_empty_reroute_trace_not_stashed(monkeypatch):
    def stub(sg, graph, *, qfn, asof, near, extra_number_calls):
        return "OBSERVED CASCADE NUMBERS (test):\n- x", [{"divergence": False}], []

    out, _captured = _seam_harness(monkeypatch, stub)
    assert "quantify_reroute" not in out["trace"]                    # mirror of the quantify merge: falsy skips


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


def test_scope_aliases_reference_contracts_and_titles_country(monkeypatch):
    # W0-caught: silver_psd keys by EXCHANGE slug and stores 'United States' — the un-aliased contract
    # slug + snake country made EVERY PSD leg read not_known (silently, by the degrade design).
    from leviathan.graphrag import silverleg as slv
    monkeypatch.setattr(slv, "_primary_country", lambda c: "united_states")
    commodity, country = cq._scope(SimpleNamespace(contract="corn"), {"table": "silver_psd"})
    assert commodity == "corn_cbot" and country == "United States"
    commodity, country = cq._scope(SimpleNamespace(contract="soft_red_winter_wheat_cbot"),
                                     {"table": "silver_psd"})
    assert commodity == "soft_red_winter_wheat_cbot" and country == "United States"
    commodity, country = cq._scope(SimpleNamespace(contract="soybeans"), {"country_rule": "none"})
    assert commodity == "soybeans_cbot" and country is None


def test_primary_title_folds_eu_members(monkeypatch):
    # Stage-1 RCA q11: PSD aggregates EU members under 'European Union'; the matif contracts' geo
    # primary is France -> 0 PSD rows -> the reroute beneficiary leg died not_known and the pair
    # silently declined.
    from leviathan.graphrag import silverleg as slv
    monkeypatch.setattr(slv, "_primary_country", lambda c: "france")
    assert cq._primary_title("french_wheat_matif") == "European Union"
    monkeypatch.setattr(slv, "_primary_country", lambda c: "united_states")
    assert cq._primary_title("corn_cbot") == "United States"
    # census-caught sibling (2026-07-11): the geo primary loses the apostrophe in title-casing while
    # PSD spells it "Cote d'Ivoire" (live DISTINCT-title probe) -- same class as France->EU.
    monkeypatch.setattr(slv, "_primary_country", lambda c: "cote_divoire")
    assert cq._primary_title("cocoa") == "Cote d'Ivoire"
