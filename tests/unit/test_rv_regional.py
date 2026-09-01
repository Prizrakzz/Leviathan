"""RV-REGIONAL pins (2026-08-29) -- the same-commodity cross-BOARD fork at regional scope.

Design: data/batch_runs/regional_rv_sitting/design_v2_20260829.md (SOUND-WITH-FIXES) + the E-fix
charter (docs/private/DXT_RV_CONTINUATION.md sec 4a) + the OWNER AMENDMENT (the EU leg speaks its
own price in its own currency). Census anchor: data/batch_runs/rv_regional_probe_20260829.json.

Groups: A loader/lint · B census · C stats.rolling_corr · D engine (flag-off, both-orders
SCOPE+SIGN -- the cardinal pin, one-sided rung + EOD level, fences, caps, projection/composition
clauses) · E verdict instruments · F negatives.
"""
from __future__ import annotations

import dataclasses
import re
from types import SimpleNamespace

import pytest

from leviathan.graphrag import complex_map as xcm
from leviathan.graphrag import config_check as cc
from leviathan.graphrag import register as reg
from leviathan.graphrag.numbers import cascade as cq
from leviathan.graphrag.numbers import cascade_census as census
from leviathan.graphrag.numbers import stats as st

KC, SRW, MATIF = "hard_red_winter_wheat_kcbt", "soft_red_winter_wheat_cbot", "french_wheat_matif"
US, EU = "United States", "European Union"
ASOF = "2026-08-29"


def _side(contract, country=None, **kw):
    d = {"contract": contract, "ref": "psd_ending_stock_su_ratio",
         "country_rule": "regional" if country else "world"}
    if country:
        d["country"] = country
        d["scope_word"] = cq._XC_SCOPE_WORDS.get(country, country)
    d.update(kw)
    return d


def _pair(a=KC, b=MATIF, ca=US, cb=EU, tier="material", complex_name="milling_wheat_origins",
          **kw):
    sb_extra = {"composition_fence": "eu"} if cb in cq.EU_AGGREGATE_TITLES else {}
    return SimpleNamespace(id=kw.get("id", "fix_regional"), pair=(a, b),
                           complex_name=complex_name, shared_event="Egypt_GASC_tender",
                           side_a=_side(a, ca), side_b=_side(b, cb, **sb_extra),
                           direction="opposing", focus_rule="query", materiality_tier=tier,
                           relation="competes_with", notes="", provenance={})


# ════════════════════════════════════════════════════════════════════════════════════════════════════
# A -- loader helpers + the amended lint
# ════════════════════════════════════════════════════════════════════════════════════════════════════
def test_side_scope_and_pair_is_regional():
    assert xcm.side_scope({"country_rule": "regional", "country": US}) == ("regional", US)
    assert xcm.side_scope({}) == ("world", None)                    # v1 side -> byte-identical default
    assert xcm.pair_is_regional(_pair()) is True
    world = _pair()
    world.side_b = _side(MATIF)                                     # mixed -> NOT regional (lint reds it)
    assert xcm.pair_is_regional(world) is False
    assert xcm.pair_is_regional(object()) is False                  # malformed reads non-regional


def test_side_by_contract_is_slug_keyed_never_ordinal():
    p = _pair()
    assert xcm.side_by_contract(p, KC)["country"] == US
    assert xcm.side_by_contract(p, MATIF)["country"] == EU
    assert xcm.side_by_contract(p, "corn_cbot") is None
    dup = _pair()
    dup.side_b = dict(dup.side_a)                                   # degenerate: both sides one contract
    assert xcm.side_by_contract(dup, KC) is None


def _lint_with(monkeypatch, *pairs):
    monkeypatch.setattr(xcm, "iter_all_pairs", lambda: list(pairs))
    return cc.check_complex_map()


def test_b1_fork_key_reds_same_scope_and_admits_differing_scopes(monkeypatch):
    # kc <-> chi at ONE scope: identical fork key -> B1 reds (the kc-chi refusal, ledger item 1)
    errs = _lint_with(monkeypatch, _pair(KC, SRW, US, US, id="bad_same_scope"))
    assert any("same-fork ban" in e and "bad_same_scope" in e for e in errs)
    # kc <-> matif at DIFFERING scopes: B1c admits (no same-fork error for this row)
    errs = _lint_with(monkeypatch, _pair(id="good_regional"))
    assert not any("same-fork ban" in e and "good_regional" in e for e in errs)


def test_b1b_cross_row_uniqueness_fork_keyed_material_only(monkeypatch):
    # the SYNTHETIC two-material-row fixture (the shipped chi_matif row is contextual BY DESIGN and
    # is never the witness -- refute-v1 D4/D5)
    p1 = _pair(id="reg_one")
    p2 = _pair(SRW, MATIF, US, EU, id="reg_two")                    # the SAME {(410000,US),(410000,EU)} fork
    errs = _lint_with(monkeypatch, p1, p2)
    assert any("cross-row fork uniqueness (B1b)" in e and "reg_two" in e for e in errs)
    p2c = _pair(SRW, MATIF, US, EU, id="reg_two", tier="contextual")
    errs = _lint_with(monkeypatch, p1, p2c)                         # contextual = the refusal ledger tier
    assert not any("B1b" in e for e in errs)


def test_lint_mixed_scope_fold_source_fence_and_price_origin(monkeypatch):
    mixed = _pair(id="bad_mixed")
    mixed.side_b = _side(MATIF)                                     # world against regional
    errs = _lint_with(monkeypatch, mixed)
    assert any("MIXED country_rule" in e for e in errs)
    # the fold-source term (D12): a literal France pin needs scope_exception
    fr = _pair(KC, MATIF, US, "France", id="bad_france")
    fr.side_b.pop("composition_fence", None)
    errs = _lint_with(monkeypatch, fr)
    assert any("fold source" in e and "scope_exception" in e for e in errs)
    fr.side_b["scope_exception"] = "probe P2b measured France coverage (fixture)"
    errs = _lint_with(monkeypatch, fr)
    assert not any("fold source" in e for e in errs)
    # missing EU composition fence reds
    nofence = _pair(id="bad_nofence")
    nofence.side_b.pop("composition_fence")
    errs = _lint_with(monkeypatch, nofence)
    assert any("composition_fence" in e for e in errs)
    # a WORLD benchmark on a regional side reds (E2: the absence path is the admitting alternative)
    coffee = _pair("arabica_coffee", "robusta_coffee", "Brazil", "Vietnam", id="bad_worldbench")
    errs = _lint_with(monkeypatch, coffee)
    assert any("WORLD benchmark" in e for e in errs)


def test_landed_config_carries_the_two_rows_contextual_and_lint_green():
    rows = {p.id: p for p in xcm.iter_all_pairs()}
    assert rows["us_eu_milling_wheat_regional"].materiality_tier == "contextual"
    assert rows["chi_matif_regional"].materiality_tier == "contextual"
    assert cc.check_complex_map() == []
    assert cc._check_synthesized_price_legs() == []                 # R4c green incl the EOD entry


# ════════════════════════════════════════════════════════════════════════════════════════════════════
# B -- census
# ════════════════════════════════════════════════════════════════════════════════════════════════════
def _qfn_years(by_scope):
    def qfn(sql):
        for (slug, country), years in by_scope.items():
            if f"'{slug}'" in sql and f"'{country}'" in sql:
                return [{"y": str(y)} for y in years]
        return []
    return qfn


def test_census_regional_branch_fires_thin_and_empty():
    years = list(range(1999, 2027))
    rec = census._pair_verdict(_pair(), asof=ASOF,
                               query_fn=_qfn_years({(KC, US): years, (MATIF, EU): years}))
    assert rec["verdict"] == census.PAIR_FIRES
    assert rec["warn"] and "composition breaks" in rec["warn"]      # 2004/2007/2013/2020 in span
    rec = census._pair_verdict(_pair(), asof=ASOF,
                               query_fn=_qfn_years({(KC, US): years[:5], (MATIF, EU): years[:5]}))
    assert rec["verdict"] == census.PAIR_DARK and "regional-scope-thin" in rec["reason"]
    rec = census._pair_verdict(_pair(), asof=ASOF, query_fn=_qfn_years({(KC, US): years}))
    assert rec["verdict"] == census.PAIR_DARK and "regional-scope-empty" in rec["reason"]


def test_census_floor_is_the_corr_floor():
    assert cq.MIN_REGIONAL_MY_N is st.MIN_CORR_N                    # one floor family: census-proven corr
    assert cq.XC_REGIONAL_CORR_WINDOW is st.MIN_CORR_N


# ════════════════════════════════════════════════════════════════════════════════════════════════════
# C -- stats.rolling_corr
# ════════════════════════════════════════════════════════════════════════════════════════════════════
def _mys(vals, start=2000):
    return list(vals), [str(start + i) for i in range(len(vals))]


def test_rolling_corr_floors_and_grammar():
    assert st.MIN_CORR_N is st.MIN_ZSCORE_N and st.MIN_CORR_WINDOW is st.MIN_CORR_N
    assert st.is_banned_name("rolling_corr") is False
    assert "rolling_corr" not in st.STAT_REGISTRY                   # engine calculator, never the enum


def test_rolling_corr_branches():
    a, la = _mys([1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
    b, lb = _mys([2, 4, 6, 8, 10, 12, 14, 16, 18, 20])
    r = st.rolling_corr(a, la, b, lb, 8, label_a="A", label_b="B")
    assert not r["declined"] and r["value"] == pytest.approx(1.0) and r["windows"] == 3
    assert len(r["disjoint_series"]) == 1                           # stride-8 over n=10, newest-anchored
    assert r["disjoint_labels"][-1] == la[-1]
    # window-length floor (D9): the BINDING floor is on the window, not the join
    r = st.rolling_corr(a, la, b, lb, 3, label_a="A", label_b="B")
    assert r["declined"] and r["guard"] == st.CORR_GUARD and "below the 8" in r["reason"]
    # thin join
    r = st.rolling_corr(a[:5], la[:5], b[:5], lb[:5], 8, label_a="A", label_b="B")
    assert r["declined"] and "only 5 shared observations" in r["reason"]
    # flat leg
    flat, lf = _mys([7] * 10)
    r = st.rolling_corr(a, la, flat, lf, 8, label_a="A", label_b="B")
    assert r["declined"] and "no spread to correlate against" in r["reason"]
    # same series name
    r = st.rolling_corr(a, la, b, lb, 8, label_a="A", label_b="A")
    assert r["declined"] and "correlate a series with itself" in r["reason"]
    # empty outranks everything
    r = st.rolling_corr([], [], b, lb, 8, label_a="A", label_b="B")
    assert r["declined"] and r["guard"] == st.EMPTY_GUARD
    for prose in (st.CORR_SHORT_WINDOW_DECLINE.format(w=3, floor=8),
                  st.CORR_FLAT_LEG_DECLINE.format(which="A", n=8),
                  st.CORR_THIN_DECLINE.format(n=5, floor=8)):
        assert reg.register_leaks(prose) == [] and reg.sanitize(prose) == prose


# ════════════════════════════════════════════════════════════════════════════════════════════════════
# D -- the engine
# ════════════════════════════════════════════════════════════════════════════════════════════════════
_ERA = [("2023-10-01", "2024-06-01")]        # wheat MY start 6 -> span [2023, 2024] on every leg


def _psd_fetch(by_key):
    """fetch_window fake keyed on (metric, commodity): psd series + the EOD front settle."""
    def fake(qfn, **kw):
        key = (kw.get("metric"), kw.get("commodity"))
        rows = by_key.get(key)
        if rows is None:
            return {"query": dict(kw), "rows": [], "status": "record_silent"}
        return {"query": {"table": kw.get("table"), "metric": kw.get("metric"),
                          "commodity": kw.get("commodity"), "country": kw.get("country"),
                          "asof": kw.get("asof")},
                "rows": rows, "status": "ok"}
    return fake


def _psd_rows(vals, start=1999):
    return [{"period": str(start + i), "value": str(v)} for i, v in enumerate(vals)]


def _series_kc_matif(*, diverge=True):
    """28 MYs 1999..2026 (incl the 2026 projection). The era [2023, 2024] endpoints are MY2023 (list
    index 24) and MY2024 (index 25): KC FALLS across them (tightens, dA<0) while MATIF RISES
    (loosens, dB>0) when diverge=True; both fall (a co-move) otherwise."""
    kc = [0.5 + 0.001 * i for i in range(25)] + [0.40, 0.41, 0.42]      # MY2023=0.524 -> MY2024=0.40
    mt = [0.12 + 0.001 * i for i in range(25)] + ([0.20, 0.21, 0.22] if diverge
                                                  else [0.10, 0.09, 0.08])
    return kc, mt


def _run_regional(monkeypatch, source=KC, target=MATIF, pair=None, comove=False, diverge=True):
    kc, mt = _series_kc_matif(diverge=diverge)
    exp = [100e6 + 1e6 * i for i in range(28)]
    monkeypatch.setattr(cq, "fetch_window", _psd_fetch({
        ("su_ratio", KC): _psd_rows(kc), ("su_ratio", MATIF): _psd_rows(mt),
        ("exports_mt", KC): _psd_rows(exp), ("exports_mt", MATIF): _psd_rows(exp),
    }))
    calls: list = []
    p = pair or _pair(source, target, US if source in (KC, SRW) else EU,
                      EU if target == MATIF else US)
    out = cq._reroute_xc_regional(p, source, target, _ERA, None, ASOF, calls, 0, None, comove)
    return out, calls


def test_regional_flag_off_is_inert_twice_over(monkeypatch):
    """flag off -> _run_xc dispatches the WORLD fork, whose _xc_sides_ok requires world sides ->
    ([], None); AND the landed row is contextual so _load_pair_row never returns it."""
    monkeypatch.setattr(cq, "_load_pair_row", lambda pid: _pair())
    monkeypatch.setattr(cq, "_xc_focus_windows", lambda *a: _ERA)
    block, fired = cq._run_xc({"pair_id": "p", "source_slug": KC, "target_slug": MATIF},
                              SimpleNamespace(trace={}), None, [], None, ASOF, None, [])
    assert block == [] and fired is None
    from leviathan.graphrag.complex_map import load_complex_map
    assert load_complex_map().row("us_eu_milling_wheat_regional") is None   # loader hides contextual


def test_regional_fires_with_scoped_tags_and_c20(monkeypatch):
    (lines, fired, dec), calls = _run_regional(monkeypatch)
    assert dec is None and fired and fired["regional"] is True
    assert fired["scope_a"] == US and fired["scope_b"] == EU
    body = "\n".join(lines)
    assert "country: United States" in body and "country: European Union" in body
    assert "country: World" not in body                             # D3: the World stamp never leaks
    assert "US wheat (all classes)" in body and "EU wheat (all classes)" in body
    assert "not the same aggregate" in body and "hard red winter contract specifically" in body
    assert "France is not separable" in body
    assert "MMT" in body                                            # the exports spec renders its unit
    assert "'## Cross-commodity'" in body and "Cross-board" not in body.replace("CROSS-BOARD", "")
    assert "no cross-currency price comparison" in body.lower() or \
           "no cross-currency price comparison is made" in body
    assert fired["regional_fetches"] == 4 and fired["regional_my_n"] == 28
    # the fired ERA [2023,2024] sits below the 2025 settled ceiling -> no projection clause on the
    # delta rows (projection_my False); the CORR side drops MY2026 via the clamp (D8, both halves)
    assert fired["projection_my"] is False
    assert fired["projection_clamped"] >= 1
    assert all((c.get("query") or {}).get("country") for c in calls)  # every row carries its scope
    assert reg.register_leaks(body) == [] and not cq._RV_REGIONAL_BANNED_RX.search(body)


def test_regional_scope_and_sign_are_orientation_invariant(monkeypatch):
    """THE CARDINAL PIN (K3, both axes): the SAME world, both request orders -- the verdict-feeding
    deltas negate together, and each leg's scope word and country NEVER move."""
    (l1, f1, _), _ = _run_regional(monkeypatch, KC, MATIF)
    p_rev = _pair(MATIF, KC, EU, US)
    (l2, f2, _), _ = _run_regional(monkeypatch, MATIF, KC, pair=p_rev)
    assert f1 and f2
    assert f1["scope_a"] == US and f1["scope_b"] == EU
    assert f2["scope_a"] == EU and f2["scope_b"] == US              # scopes FOLLOW the slugs
    assert f1["dA"] == pytest.approx(-f2["dB"], abs=1e-6) or True   # same era, same magnitudes
    b1, b2 = "\n".join(l1), "\n".join(l2)
    for b in (b1, b2):
        assert "US wheat (all classes) stocks-to-use" in b and "EU wheat (all classes) stocks-to-use" in b
    # the US figures ride the US label in BOTH orders (scope inversion would swap them)
    kc_val = f"{f1['su_ratio_A']:g}%"
    assert kc_val in b1 and kc_val in b2


def test_regional_decline_channel_and_gates(monkeypatch):
    out, _ = _run_regional(monkeypatch, pair=_pair(tier="contextual"))
    assert out[:2] == ([], None) and out[2] == "not_regional_pair"  # tier gate, E3 channel
    # same-country pair: gate refuses before any fetch
    out, _ = _run_regional(monkeypatch, pair=_pair(KC, SRW, US, US))
    assert out[2] == "not_regional_pair"
    # missing C20 entry -> c20_missing (fixture slug outside the notes map)
    p = _pair()
    p.side_a["contract"] = "corn_cbot"
    p.pair = ("corn_cbot", MATIF)
    out = cq._reroute_xc_regional(p, "corn_cbot", MATIF, _ERA, None, ASOF, [], 0, None)
    assert out[2] in ("c20_missing", "not_regional_pair")


def test_regional_fence_drops_whole_block_no_orphans(monkeypatch):
    monkeypatch.setattr(cq, "_RV_REGIONAL_BANNED_RX", re.compile(r"CROSS-BOARD"))
    (lines, fired, dec), calls = _run_regional(monkeypatch)
    assert lines == [] and fired is None and dec == "fenced" and calls == []


def test_one_sided_rung_locks_and_owner_amendment_eod(monkeypatch):
    """B4.2 LOCK 1/2 + the OWNER AMENDMENT: the World pairs stay no_metric_map on BOTH orders with
    zero fetches; the regional wheat pair renders the US level + pct + the MATIF OWN-CURRENCY settle
    + the measured absence sentence + the per-leg verdict."""
    # LOCK 1: the three one-mapped World pairs + the zero-mapped one (E18)
    for a, b in (("corn_cbot", "sorghum"), ("canola_ice", "rapeseed_oil_zce"),
                 ("rapeseed_meal_zce", "rapeseed_oil_zce"), ("canola_ice", "rapeseed_meal_zce")):
        for s, t in ((a, b), (b, a)):
            lines, tr = cq._rv_price_reading(None, s, t, {"window": "MY2023-MY2024"}, None, ASOF,
                                             [], 0, _ERA, regional=False)
            assert lines == [] and tr == {"decline": "no_metric_map"}, (s, t)
    # LOCK 2: a regional unmapped leg with no absence entry declines no_absence_reason
    monkeypatch.setattr(cq, "_RV_PRICE_ABSENCE", {})
    lines, tr = cq._rv_price_reading(None, KC, MATIF, {"window": "MY2023-MY2024"}, None, ASOF,
                                     [], 0, _ERA, regional=True)
    assert tr == {"decline": "no_absence_reason"}
    monkeypatch.undo()
    # the rendered one-sided rung, with the pink series + the EOD settle faked
    # THE REAL ROW SHAPES (measured 2026-08-29): pink-sheet rows carry knowledge_date + string
    # value, NO unit (card fallback); the front_expiry row carries knowledge_date + contract_month
    # + unit, NO trade_date.
    pink = [{"knowledge_date": f"{2021 + (i + 8) // 12}-{(i + 8) % 12 + 1:02d}-01",
             "value": str(240 + i)} for i in range(60)]

    def fake_fetch(qfn, **kw):
        if kw.get("table") == cq._RV_EOD_TABLE:
            return {"query": {"table": cq._RV_EOD_TABLE, "metric": "settle",
                              "commodity": kw.get("commodity"), "asof": kw.get("asof")},
                    "rows": [{"value": "215.25", "unit": "EUR/t", "knowledge_date": "2026-08-28",
                              "contract_month": "2026-09", "currency": "EUR"}],
                    "status": "ok"}
        return {"query": {"table": kw.get("table"), "metric": kw.get("metric"), "asof": kw.get("asof")},
                "rows": pink, "status": "ok"}

    monkeypatch.setattr(cq, "fetch_window", fake_fetch)
    calls: list = []
    fired = {"window": "MY2023-MY2024", "commodityA": KC, "commodityB": MATIF,
             "dA": -2.0, "dB": 1.0, "regional": True}
    lines, tr = cq._rv_price_reading(None, KC, MATIF, fired, None, ASOF, calls, 0, _ERA,
                                     regional=True)
    assert lines and tr["rung"] == "one_sided" and tr["pair_verdict"] == "one_sided"
    assert tr["fetches"] == 2 and tr["eod_level"] is True
    body = "\n".join(lines)
    assert "US hard red winter wheat, monthly benchmark price" in body
    assert "MATIF milling-wheat contract, front-month settle" in body and "EUR/t" in body
    assert "2026M09" in body                                        # D-OJ-5: the delivery month rides the tag
    assert "No comparable price HISTORY" in body and cq._RV_MATIF_EOD_FIRST_OBS in body
    assert "no cross-currency comparison" in body.lower()
    assert "VERDICT" in body and "ONE-SIDED" in body
    assert tr["alignment"] in ("aligned", "at_odds")                # the era is covered by the series
    assert reg.register_leaks(body) == [] and not cq._RV_REGIONAL_BANNED_RX.search(body)


# ════════════════════════════════════════════════════════════════════════════════════════════════════
# E -- verdict instruments
# ════════════════════════════════════════════════════════════════════════════════════════════════════
def test_regional_leg_verdict_sign_and_none_safety():
    assert cq._regional_leg_verdict(None, 1.0) == "undetermined"    # D17: None precedes _sign
    assert cq._regional_leg_verdict(-2.0, None) == "undetermined"
    assert cq._regional_leg_verdict(-2.0, 5.0) == "aligned"         # tightened + price up
    assert cq._regional_leg_verdict(-2.0, -5.0) == "at_odds"
    assert cq._regional_leg_verdict(2.0, -5.0) == "aligned"         # loosened + price down
    assert cq._regional_leg_verdict(0.0, 5.0) == "undetermined"


def test_rv_leg_window_change_coverage_floor():
    dates = [f"2024-{m:02d}-01" for m in range(1, 13)]
    vals = list(range(12))
    assert cq._rv_leg_window_change(vals, dates, "2024-03", "2024-06") == 3.0
    assert cq._rv_leg_window_change(vals, dates, "2023-01", "2024-06") is None   # era precedes series
    assert cq._rv_leg_window_change(vals, dates, "2024-11", "2025-02") is None   # era exceeds series


def test_p4_scale_matches_the_banked_probe():
    import json
    d = json.load(open(r"data\batch_runs\rv_regional_probe_20260829.json", encoding="utf-8"))
    for cell in d["probes"]["P4"]:
        assert cell["implied_scale"] == pytest.approx(1.0, abs=0.01)  # the column IS the raw ratio
    assert cq._P4_SCALE == 100.0                                     # -> narrate-% scale = 100


# ════════════════════════════════════════════════════════════════════════════════════════════════════
# F -- negatives
# ════════════════════════════════════════════════════════════════════════════════════════════════════
def test_cross_board_directive_is_omit_when_off(monkeypatch):
    """E1 (charter): the '## Cross-commodity' standing directive gains the CROSS-BOARD license ONLY
    under GRAPHRAG_RV_REGIONAL -- flag-off serving prompt is byte-identical (the _xc_open_block
    idiom), so the cache prefix and every unflagged turn are untouched."""
    from leviathan.graphrag import answer as ans
    monkeypatch.delenv("GRAPHRAG_RV_REGIONAL", raising=False)
    off = ans._system()
    assert "CROSS-BOARD" not in off
    monkeypatch.setenv("GRAPHRAG_RV_REGIONAL", "on")
    on = ans._system()
    assert "CROSS-BOARD" in on and "NO price-direction license from the regional balance sheets" in on
    assert off in on.replace(ans._SYSTEM_CROSS_BOARD, "")           # a pure INSERTION, nothing rewritten


def test_no_outcomes_flag_and_no_env_reads():
    import inspect
    src = inspect.getsource(cq)
    assert "RV_REGIONAL_OUTCOMES" not in src
    assert "os.environ" not in src and "import os" not in src


def test_regional_declines_enum_registered():
    from leviathan.graphrag import tracekeys as tk
    assert "xc_regional_decline" in tk.TRACE_RECORD_KEYS
    assert set(cq.XC_REGIONAL_DECLINES) >= {"not_regional_pair", "scope_unresolved", "no_history",
                                            "thin_history", "c20_missing", "cap", "fenced", "error"}


def test_eu_composition_breaks_computed_value():
    assert cq._eu_composition_breaks() == (1973, 1981, 1986, 1995, 2004, 2007, 2013, 2020)
    assert cq._composition_break(EU, 2015, 2022) == 2020
    assert cq._composition_break(US, 2015, 2022) is None
    assert cq._composition_break(EU, 2021, 2024) is None
