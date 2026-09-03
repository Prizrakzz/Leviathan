"""RV-READING pins (2026-08-29) -- the directional price leg on a fired cross-commodity pair.

Groups:
  A  `stats.pair_spread` -- the deterministic constructor (pins 1-5 of the design's list)
  B  the reading composer `cascade._rv_price_reading` -- hermetic fakes at the `fetch_window` seam
     (no pg, no registry SQL): rungs, sign-identity BOTH orders (the cardinal pin), narration
     register-cleanliness, the C20 not-the-same-aggregate sentences, the fetch budget, PIT specs
  C  the seams -- `_run_xc(reading=, replay=)`, quantify threading, `answer._rv_reading_on`
  D  governance -- STAT_REGISTRY untouched, the R4c synthesized-leg lint (green AND fail-closed),
     the outcomes rider dark, the R4 fences un-weakened

The design + verifier record: workflow journal wf_4162176a-173 (results 3 and 5); the D1-D10 fixes and
the owner E4 ruling (board spreads ride futures_eod dailies elsewhere; THIS leg rides the Pink Sheet)
are folded here. The flag (GRAPHRAG_RV_READING) is DARK; every pin runs flag-off semantics through the
threaded kwargs, never an env read below the answer seam.
"""
from __future__ import annotations

import pytest

from leviathan.graphrag import register as reg
from leviathan.graphrag.numbers import cascade as cq
from leviathan.graphrag.numbers import stats as st

SRC = "malaysian_crude_palm_oil_cme"
TGT = "soybean_oil_cbot"
M_SRC, M_TGT = "palm_oil_cpo_usd_t", "soybean_oil_usd_t"


# ════════════════════════════════════════════════════════════════════════════════════════════════════
# A -- stats.pair_spread
# ════════════════════════════════════════════════════════════════════════════════════════════════════
def _axes(vals, start_y=2024, start_m=1):
    dates = []
    t = start_y * 12 + (start_m - 1)
    for _ in vals:
        dates.append(f"{t // 12:04d}-{t % 12 + 1:02d}-01")
        t += 1
    return list(vals), dates


def test_pair_spread_unit_refusal():
    a, da = _axes([10.0] * 10)
    b, db = _axes([5.0] * 10)
    # same currency (None-None), different units -> RATIO, unit None
    r = st.pair_spread(a, da, "USD/mt", b, db, "US cents/lb", label_a="A", label_b="B")
    assert not r["declined"] and r["form"] == "ratio" and r["unit"] is None
    # different currencies -> CURRENCY_GUARD, value None (fixture-only branch, held for a future source)
    r = st.pair_spread(a, da, "x/t", b, db, "y/t", currency_a="MYR", currency_b="CNY",
                       label_a="A", label_b="B")
    assert r["declined"] and r["guard"] == st.CURRENCY_GUARD and r["value"] is None
    # one unit blank -> UNIT_GUARD with UNIT_UNKNOWN_DECLINE verbatim
    r = st.pair_spread(a, da, "USD/mt", b, db, None, label_a="A", label_b="B")
    assert r["declined"] and r["guard"] == st.UNIT_GUARD
    assert r["reason"] == st.UNIT_UNKNOWN_DECLINE.format(known="USD/mt")
    # neither unit -> refusal, NOT a silent difference (stricter than unit_compatible, on purpose)
    r = st.pair_spread(a, da, None, b, db, "", label_a="A", label_b="B")
    assert r["declined"] and r["guard"] == st.UNIT_GUARD
    assert r["reason"] == st.BOTH_UNITS_REQUIRED_DECLINE


def test_pair_spread_ratio_fallback_and_zero_crossing_law():
    a, da = _axes([100.0, 110.0, 120.0, 130.0, 140.0, 150.0, 160.0, 170.0])
    b, db = _axes([90.0, 95.0, 100.0, 105.0, 110.0, 115.0, 120.0, 125.0])
    r = st.pair_spread(a, da, "USD/mt", b, db, "USD/mt", label_a="A", label_b="B")
    assert r["form"] == "difference" and r["unit"] == "USD/mt" and r["pct_change_allowed"] is False
    assert r["value"] == 45.0 and r["n"] == 8 and r["a_latest"] == 170.0 and r["b_latest"] == 125.0
    assert r["series"][0] == 10.0                                  # oldest -> newest, A minus B
    r = st.pair_spread(a, da, "USD/mt", b, db, "US cents/lb", label_a="A", label_b="B")
    assert r["form"] == "ratio" and r["pct_change_allowed"] is True and r["unit"] is None
    assert r["value"] == pytest.approx(170.0 / 125.0)


def test_pair_spread_denominator_whole_stat_refusal():
    a, da = _axes([10.0, 10.0, 10.0, 10.0])
    b, db = _axes([5.0, 0.0, -1.0, 5.0])
    r = st.pair_spread(a, da, "USD/mt", b, db, "US cents/lb", label_a="A", label_b="B")
    assert r["declined"] and r["guard"] == st.DENOMINATOR_GUARD
    assert "2 of the 4" in r["reason"] and da[1] in r["reason"]    # count + FIRST offending date, no filter
    b2, db2 = _axes([5.0, 4.0, 3.0, 5.0])
    assert not st.pair_spread(a, da, "USD/mt", b2, db2, "US cents/lb",
                              label_a="A", label_b="B")["declined"]


def test_pair_spread_join_dupes_and_floor():
    a, da = _axes([1.0, 2.0, 3.0])
    b, db = _axes([1.0, 1.0], start_m=2)                           # overlaps months 2-3 only
    r = st.pair_spread(a, da, "USD/mt", b, db, "USD/mt", label_a="A", label_b="B")
    assert not r["declined"] and r["n"] == 2 and r["dates"] == da[1:]   # a's order preserved
    dup_b, dup_db = [1.0, 1.0], [da[0], da[0]]
    r = st.pair_spread(a, da, "USD/mt", dup_b, dup_db, "USD/mt", label_a="A", label_b="B")
    assert r["declined"] and "more than one row" in r["reason"]
    # zero overlap declines with n == overlap (0), THIN_GUARD -- the floor is MIN_PAIR_SPREAD_N (=2,
    # review m4: at ONE joined observation extrema places a number against itself; 2 = MIN_SPREAD_N's
    # own two-endpoint logic, inherited -- and still below the rank floor so ordinal-thin lives)
    c, dc = _axes([1.0, 2.0], start_y=1999)
    r = st.pair_spread(a, da, "USD/mt", c, dc, "USD/mt", label_a="A", label_b="B")
    assert r["declined"] and r["guard"] == st.THIN_GUARD and r["n"] == 0
    one, done = _axes([9.0], start_m=1)                            # overlap exactly 1 -> THIN too (m4)
    r = st.pair_spread(a, da, "USD/mt", one, done, "USD/mt", label_a="A", label_b="B")
    assert r["declined"] and r["guard"] == st.THIN_GUARD and r["n"] == 1
    assert st.MIN_PAIR_SPREAD_N == st.MIN_SPREAD_N == 2
    # same-series refusal
    r = st.pair_spread(a, da, "USD/mt", a, da, "USD/mt", label_a="A", label_b="A")
    assert r["declined"] and "same series" in r["reason"]


def test_pair_spread_empty_outranks_units():
    a, da = _axes([1.0, 2.0])
    r = st.pair_spread([], [], None, a, da, "USD/mt", label_a="A", label_b="B")
    assert r["declined"] and r["guard"] == st.EMPTY_GUARD          # never narrated as a unit mismatch
    r = st.pair_spread(a, da, "USD/mt", [], [], None, label_a="A", label_b="B")
    assert r["declined"] and r["guard"] == st.EMPTY_GUARD


# ════════════════════════════════════════════════════════════════════════════════════════════════════
# B -- the reading composer, hermetic at the fetch_window seam
# ════════════════════════════════════════════════════════════════════════════════════════════════════
ASOF = "2026-08-15"


def _rec(metric, pairs, unit=None):
    """THE REAL ROW SHAPE (measured 2026-08-29, the treatment-arm RCA): a pink-sheet series row
    carries `knowledge_date` + a STRING `value` and NO unit key -- the unit comes off the card via
    the _rv_axes fallback. The first fixtures invented `date` + `unit` keys and the suite stayed
    green while every cloud row declined empty_series. `unit` stays overridable for the
    fixture-only unit-arm tests."""
    row = lambda d, v: ({"knowledge_date": d, "value": str(v), "unit": unit} if unit is not None
                        else {"knowledge_date": d, "value": str(v)})
    return {"query": {"table": cq._RV_PRICE_TABLE, "metric": metric, "commodity": None,
                      "country": None, "period": None, "asof": ASOF},
            "rows": [row(d, v) for d, v in pairs], "status": "ok"}


def _monthly(start_y, start_m, vals):
    out = []
    t = start_y * 12 + (start_m - 1)
    for v in vals:
        out.append((f"{t // 12:04d}-{t % 12 + 1:02d}-01", v))
        t += 1
    return out


def _patch_fetch(monkeypatch, by_metric, log=None):
    def fake(qfn, **kw):
        if log is not None:
            log.append(kw)
        return by_metric[kw["metric"]]
    monkeypatch.setattr(cq, "fetch_window", fake)


def _fired(dA=-2.0, dB=1.0, window="MY2023-MY2024", **kw):
    return {"pair_id": "soyoil_palm_vegoil", "commodityA": SRC, "commodityB": TGT,
            "dA": dA, "dB": dB, "window": window, "reroute_v2": True, **kw}


def _series_for(source, window="MY2023-MY2024", rising=True, months=60):
    """A palm/soyoil fixture whose A-minus-B spread RISES (or falls) monotonically, spanning the MY
    window so the verdict clip holds >=2 observations whatever _my_start(source) is."""
    base = [900.0 + i for i in range(months)]
    step = 1.0 if rising else -1.0
    spread = [50.0 + step * i for i in range(months)]
    a = [b + s for b, s in zip(base, spread)]
    return (_monthly(2021, 9, a), _monthly(2021, 9, base))


def test_rv_reading_full_rung_renders_and_is_register_clean(monkeypatch):
    pa, pb = _series_for(SRC)
    _patch_fetch(monkeypatch, {M_SRC: _rec(M_SRC, pa), M_TGT: _rec(M_TGT, pb)})
    calls: list = []
    lines, tr = cq._rv_price_reading(None, SRC, TGT, _fired(), None, ASOF, calls, 0, _ERA)
    assert lines and tr["form"] == "difference" and tr["rung"] == "full"
    assert tr["fetches"] == 2 and tr["n"] == 60
    assert tr["alignment"] in ("aligned", "at_odds")               # windows given -> the verdict renders
    body = "\n".join(lines)
    assert "Set against the balance sheets above" in body          # ... and its sentence is register-run
    # figures AND words; every magnitude a bound [N] row; the directive literals pin #9 demands
    assert "not exchange settles" in body and "PRICE-RELATIVE on the monthly benchmark spread" in body
    assert "no statement is made about where the spread goes next" in body
    assert "'## Cross-commodity'" in body
    assert len(calls) <= 6 and all((c.get("rows") or [{}])[0].get("unit") for c in calls)   # D5
    assert all(c.get("shown") for c in calls)                       # every printed magnitude is bound
    # register cleanliness, all three belts
    assert reg.register_leaks(body) == [] and reg.exec_leaks(body) == []
    assert not cq._RV_READING_BANNED_RX.search(body)
    assert reg.sanitize(body) == body


_ERA = [("2023-10-01", "2024-11-01")]                              # palm/soyoil both _my_start 10 -> span
#                                                                    [2023, 2024] == _fired()'s window


def test_rv_reading_sign_identity_both_orders(monkeypatch):
    """THE CARDINAL PIN. dA=-2.0 (A tightened), dB=+1.0, spread RISING over the fired era -> aligned;
    spread FALLING -> at_odds; and the IDENTICAL fixture with (source, target) reversed -- legs,
    metrics and deltas all swapped, exactly as _reroute_xc would stamp them -- yields the SAME verdict
    word. The verdict clips the ERA'S OWN CALENDAR DATES (F1), so `windows` rides in."""
    pa, pb = _series_for(SRC, rising=True)
    _patch_fetch(monkeypatch, {M_SRC: _rec(M_SRC, pa), M_TGT: _rec(M_TGT, pb)})
    _, tr = cq._rv_price_reading(None, SRC, TGT, _fired(dA=-2.0, dB=1.0), None, ASOF, [], 0, _ERA)
    assert tr["alignment"] == "aligned"
    pa2, pb2 = _series_for(SRC, rising=False)
    _patch_fetch(monkeypatch, {M_SRC: _rec(M_SRC, pa2), M_TGT: _rec(M_TGT, pb2)})
    _, tr = cq._rv_price_reading(None, SRC, TGT, _fired(dA=-2.0, dB=1.0), None, ASOF, [], 0, _ERA)
    assert tr["alignment"] == "at_odds"
    # REVERSED ORDER: A is now soyoil; B-minus-A of the rising fixture FALLS, and the deltas swap.
    pa3, pb3 = _series_for(SRC, rising=True)
    _patch_fetch(monkeypatch, {M_SRC: _rec(M_SRC, pa3), M_TGT: _rec(M_TGT, pb3)})
    _, tr = cq._rv_price_reading(None, TGT, SRC, _fired(dA=1.0, dB=-2.0), None, ASOF, [], 0, _ERA)
    assert tr["alignment"] == "aligned"                             # SAME word, orientation-invariant


def test_rv_reading_sign_identity_across_differing_my_calendars(monkeypatch):
    """THE F1 CLASS (review round 1, CONFIRMED-fatal in the first cut): corn (_my_start 9) vs SRW
    (_my_start 6). The fired MY STRING differs per orientation -- corn-focus mints MY2022-MY2023 for
    the era ('2023-10-01','2024-06-01') while wheat-focus mints MY2023-MY2024 -- but the verdict clips
    the era's own calendar dates, which are ONE span, so the SAME facts give the SAME verdict word
    from both orientations. The first cut rebuilt the clip from _my_start(source) and inverted."""
    era = [("2023-10-01", "2024-06-01")]
    corn_span = cq._my_span(era[0], "corn_cbot")
    srw_span = cq._my_span(era[0], "soft_red_winter_wheat_cbot")
    assert corn_span != srw_span                                    # the class exists or the pin is vacuous
    w_corn = f"MY{corn_span[0]}-MY{corn_span[-1]}"
    w_srw = f"MY{srw_span[0]}-MY{srw_span[-1]}"
    pa, pb = _series_for("corn_cbot", rising=True)
    # corn focus: A = corn, spread = corn - wheat RISES; corn tightened (dA<0) -> rel_tight>0 -> aligned
    _patch_fetch(monkeypatch, {"maize_usd_t": _rec("maize_usd_t", pa),
                               "wheat_us_srw_usd_t": _rec("wheat_us_srw_usd_t", pb)})
    f1 = {"pair_id": "corn_wheat_feed", "commodityA": "corn_cbot",
          "commodityB": "soft_red_winter_wheat_cbot", "dA": -2.0, "dB": 1.0,
          "window": w_corn, "reroute_v2": True}
    _, tr1 = cq._rv_price_reading(None, "corn_cbot", "soft_red_winter_wheat_cbot",
                                  f1, None, ASOF, [], 0, era)
    # wheat focus: SAME world -- legs, series and deltas swapped; the fired window is WHEAT's MY string
    _patch_fetch(monkeypatch, {"maize_usd_t": _rec("maize_usd_t", pa),
                               "wheat_us_srw_usd_t": _rec("wheat_us_srw_usd_t", pb)})
    f2 = {"pair_id": "corn_wheat_feed", "commodityA": "soft_red_winter_wheat_cbot",
          "commodityB": "corn_cbot", "dA": 1.0, "dB": -2.0,
          "window": w_srw, "reroute_v2": True}
    _, tr2 = cq._rv_price_reading(None, "soft_red_winter_wheat_cbot", "corn_cbot",
                                  f2, None, ASOF, [], 0, era)
    assert tr1["alignment"] == tr2["alignment"] == "aligned"        # one world, ONE verdict


def test_rv_reading_verdict_coverage_floor(monkeypatch):
    """M3: an era older than the price history's own envelope gets NO direction claim -- the verdict
    stays undetermined rather than describing months the series never held."""
    era = [("2018-10-01", "2019-11-01")]                            # span [2018, 2019] for palm
    pa, pb = _series_for(SRC, rising=True)                          # history starts 2021-09
    _patch_fetch(monkeypatch, {M_SRC: _rec(M_SRC, pa), M_TGT: _rec(M_TGT, pb)})
    _, tr = cq._rv_price_reading(None, SRC, TGT, _fired(window="MY2018-MY2019"), None, ASOF,
                                 [], 0, era)
    assert tr["alignment"] == "undetermined"


def test_rv_reading_citation_labels_are_reader_clean(monkeypatch):
    """THE REVIEW'S CHARGE-6 PIN (M1+M2): every call the composer appends must render a
    citations.from_number label with NO internal id (*_usd_t) and NO MY-prefixed calendar month --
    the two defects lived entirely on the citation axis the engine-block pins never crossed."""
    from leviathan.graphrag import citations as ct
    pa, pb = _series_for(SRC)
    _patch_fetch(monkeypatch, {M_SRC: _rec(M_SRC, pa), M_TGT: _rec(M_TGT, pb)})
    calls: list = []
    lines, _ = cq._rv_price_reading(None, SRC, TGT, _fired(), None, ASOF, calls, 0, _ERA)
    assert lines and calls
    for i, c in enumerate(calls, start=1):
        label = ct.from_number(c, i).label
        assert reg.internal_leaks(label) == [], label
        assert "MY2" not in label, label                            # the MYMY class on a date table


def test_rv_reading_ordinal_thin_rung(monkeypatch):
    pa, pb = _series_for(SRC, months=5)
    _patch_fetch(monkeypatch, {M_SRC: _rec(M_SRC, pa), M_TGT: _rec(M_TGT, pb)})
    calls: list = []
    lines, tr = cq._rv_price_reading(None, SRC, TGT, _fired(window="MYnope"), None, ASOF, calls, 0)
    assert tr["rung"] == "ordinal_thin" and tr["n"] == 5
    body = "\n".join(lines)
    assert "placed ORDINALLY" in body and "no percentile and no z-score is computed" in body
    assert "the highest" in body and "the lowest" in body
    assert tr["alignment"] == "undetermined"                        # the window parse missed, honestly
    assert reg.register_leaks(body) == [] and reg.sanitize(body) == body


def test_rv_reading_no_sigma_rung(monkeypatch):
    flat = [(d, 100.0) for d, _ in _monthly(2021, 9, [0] * 12)]
    flat_b = [(d, 40.0) for d, _ in _monthly(2021, 9, [0] * 12)]
    _patch_fetch(monkeypatch, {M_SRC: _rec(M_SRC, flat), M_TGT: _rec(M_TGT, flat_b)})
    lines, tr = cq._rv_price_reading(None, SRC, TGT, _fired(), None, ASOF, [], 0)
    assert tr["rung"] == "no_sigma"
    body = "\n".join(lines)
    assert "no sigma is computed" in body and "sigma against" not in body
    assert reg.register_leaks(body) == [] and reg.sanitize(body) == body


def test_rv_reading_level_only_rung_is_fixture_only_but_honest(monkeypatch):
    """FIXTURE-ONLY by construction (D1): the real card R1-lints a unit onto every metric and _rv_axes
    falls back to it, so reaching the unit arm needs the registry seam faked unit-less -- exactly what
    'fixture-only under Pink-Sheet plumbing' means."""
    from types import SimpleNamespace
    card = SimpleNamespace(metrics={M_SRC: SimpleNamespace(unit="USD/mt"),
                                    M_TGT: SimpleNamespace(unit=None)})
    monkeypatch.setattr(cq, "_registry", lambda: SimpleNamespace(get=lambda t: card))
    pa, pb = _series_for(SRC, months=12)
    _patch_fetch(monkeypatch, {M_SRC: _rec(M_SRC, pa, unit="USD/mt"),
                               M_TGT: _rec(M_TGT, pb, unit="")})
    ca: list = []
    lines, tr = cq._rv_price_reading(None, SRC, TGT, _fired(), None, ASOF, ca, 0)
    assert tr["rung"] == "level_only" and tr["decline_guard"] == st.UNIT_GUARD
    body = "\n".join(lines)
    assert "read one at a time" in body and "no spread between them is computed" in body
    assert "PRICE-RELATIVE declined" in body and "not exchange settles" in body
    assert reg.register_leaks(body) == [] and reg.sanitize(body) == body


def test_rv_reading_never_a_level_outside_its_own_row(monkeypatch):
    """Pin #9: each leg's own price magnitude appears EXACTLY once (its own [N] level row); the
    directive paragraph carries the spread magnitude only."""
    pa, pb = _series_for(SRC)
    _patch_fetch(monkeypatch, {M_SRC: _rec(M_SRC, pa), M_TGT: _rec(M_TGT, pb)})
    lines, _ = cq._rv_price_reading(None, SRC, TGT, _fired(), None, ASOF, [], 0)
    body = "\n".join(lines)
    a_latest, b_latest = pa[-1][1], pb[-1][1]
    assert body.count(f"{a_latest:.2f}") == 1 and body.count(f"{b_latest:.2f}") == 1


def test_rv_reading_c20_labels(monkeypatch):
    """D6: srw/corn (the corn_wheat_feed shape) -- the price row names the SPECIFIC benchmark while the
    balance row is _xc_label's aggregate, and the directive says so for BOTH legs."""
    pa, pb = _series_for("corn_cbot")
    _patch_fetch(monkeypatch, {"maize_usd_t": _rec("maize_usd_t", pa),
                               "wheat_us_srw_usd_t": _rec("wheat_us_srw_usd_t", pb)})
    f = {"pair_id": "corn_wheat_feed", "commodityA": "corn_cbot",
         "commodityB": "soft_red_winter_wheat_cbot", "dA": -1.0, "dB": 0.5,
         "window": "MY2023-MY2024", "reroute_v2": True}
    lines, _ = cq._rv_price_reading(None, "corn_cbot", "soft_red_winter_wheat_cbot",
                                    f, None, ASOF, [], 0)
    body = "\n".join(lines)
    assert cq._xc_label("soft_red_winter_wheat_cbot") == "world wheat (all classes)"
    assert "US soft red winter wheat" in body and "US Gulf" in body
    assert "not the same aggregate" in body
    assert "soft red winter benchmark specifically" in body and "maize benchmark specifically" in body


def test_rv_reading_fetch_specs_are_pit_clipped(monkeypatch):
    """Pin #6 (spec half): both fetches carry the SESSION asof, t2 == asof, the 60-month t1, the date
    grain and the series agg -- and there are exactly TWO."""
    log: list = []
    pa, pb = _series_for(SRC)
    _patch_fetch(monkeypatch, {M_SRC: _rec(M_SRC, pa), M_TGT: _rec(M_TGT, pb)}, log=log)
    cq._rv_price_reading(None, SRC, TGT, _fired(), None, ASOF, [], 0)
    assert len(log) == 2
    for kw in log:
        assert kw["table"] == "silver_pink_sheet" and kw["asof"] == ASOF and kw["t2"] == ASOF
        assert kw["t1"] == cq._months_back(ASOF, cq._RV_PRICE_MONTHS)
        assert kw["agg"] == "series" and kw["period_type"] == "date"
        assert kw["commodity"] is None and kw["country"] is None


def test_rv_reading_declines_are_tagged_not_silent(monkeypatch):
    # no metric map (palm_olein_dce is ABSENT ON PURPOSE)
    lines, tr = cq._rv_price_reading(None, "palm_olein_dce", TGT, _fired(), None, ASOF, [], 0)
    assert lines == [] and tr == {"decline": "no_metric_map"}
    # empty read
    _patch_fetch(monkeypatch, {M_SRC: {"query": {}, "rows": [], "status": "record_silent"},
                               M_TGT: _rec(M_TGT, _series_for(SRC)[1])})
    lines, tr = cq._rv_price_reading(None, SRC, TGT, _fired(), None, ASOF, [], 0)
    assert lines == [] and tr == {"decline": "empty_series"}


def test_rv_reading_fence_drops_whole_block_and_orphans_no_rows(monkeypatch):
    pa, pb = _series_for(SRC)
    _patch_fetch(monkeypatch, {M_SRC: _rec(M_SRC, pa), M_TGT: _rec(M_TGT, pb)})
    monkeypatch.setattr(cq, "_RV_READING_BANNED_RX", __import__("re").compile(r"PRICE-RELATIVE"))
    calls: list = []
    lines, tr = cq._rv_price_reading(None, SRC, TGT, _fired(), None, ASOF, calls, 0)
    assert lines == [] and tr == {"decline": "fenced"} and calls == []   # no orphan [N] rows


def test_months_back_is_pure_string_arithmetic():
    assert cq._months_back("2026-08-15", 60) == "2021-08-01"
    assert cq._months_back("2026-01-31", 1) == "2025-12-01"
    assert cq._months_back("2024-12-01", 12) == "2023-12-01"


# ════════════════════════════════════════════════════════════════════════════════════════════════════
# C -- the seams
# ════════════════════════════════════════════════════════════════════════════════════════════════════
def _stub_reroute(monkeypatch, fired):
    monkeypatch.setattr(cq, "_load_pair_row", lambda pid: object())
    monkeypatch.setattr(cq, "_xc_focus_windows", lambda *a: [("2023-01-01", "2024-06-01")])
    monkeypatch.setattr(cq, "_reroute_xc", lambda *a, **k: (["- [N1] leg"], dict(fired)))


class _SG:
    def __init__(self):
        self.trace: dict = {}
        self.seeds: list = []
        self.nodes: list = []


REQ = {"pair_id": "p", "source_slug": SRC, "target_slug": TGT}


def test_run_xc_reading_off_is_byte_identical(monkeypatch):
    _stub_reroute(monkeypatch, _fired())
    calls: list = []
    block, fired = cq._run_xc(REQ, _SG(), None, [], None, ASOF, None, calls)
    assert "price_reading" not in fired and "price_reading_decline" not in fired
    assert calls == [] and block == ["- [N1] leg"]


def test_run_xc_replay_belt_drops_the_leg_whole(monkeypatch):
    _stub_reroute(monkeypatch, _fired())
    seen: list = []
    monkeypatch.setattr(cq, "_rv_price_reading", lambda *a: seen.append(a) or (["x"], {}))
    _, fired = cq._run_xc(REQ, _SG(), None, [], None, ASOF, None, [], reading=True, replay=True)
    assert fired["price_reading_decline"] == "replay" and seen == []   # NO fetch on a replay turn


def test_run_xc_threads_reading_and_stamps_trace(monkeypatch):
    _stub_reroute(monkeypatch, _fired())
    monkeypatch.setattr(cq, "_rv_price_reading", lambda *a, **k: (["- [N2] read"], {"rung": "full"}))
    block, fired = cq._run_xc(REQ, _SG(), None, [], None, ASOF, None, [], reading=True)
    assert block == ["- [N1] leg", "- [N2] read"] and fired["price_reading"] == {"rung": "full"}


def test_run_xc_fence_decline_writes_the_trace_key(monkeypatch):
    _stub_reroute(monkeypatch, _fired())
    monkeypatch.setattr(cq, "_rv_price_reading", lambda *a, **k: ([], {"decline": "fenced"}))
    sg = _SG()
    _, fired = cq._run_xc(REQ, sg, None, [], None, ASOF, None, [], reading=True)
    assert fired["price_reading_decline"] == "fenced"
    assert sg.trace.get("quantify_rv_reading_fenced") is True


def test_run_xc_comove_declines_the_reading(monkeypatch):
    """M4 (review round 1, supersedes the own-marker plan): the co-move block's directive is
    'su_ratio percentages only' -- a price-relative verdict under that marker is two contradicting
    directives in one block, so the reading DECLINES outright on a co-move fire. No fetch is spent."""
    seen: list = []
    monkeypatch.setattr(cq, "_rv_price_series", lambda *a: seen.append(a) or {"status": "error"})
    f = _fired(comove=True)
    f.pop("reroute_v2")
    lines, tr = cq._rv_price_reading(None, SRC, TGT, f, None, ASOF, [], 0, _ERA)
    assert lines == [] and tr == {"decline": "comove"} and seen == []


def test_rv_reading_same_label_pair_declines_as_shape(monkeypatch):
    """m2: soybean_oil_cbot vs soybean_oil_dce share ONE reader label ('world soybean oil') and ONE
    metric -- a same-series pair. The structural refusal maps to the 'shape' tag, never 'error'."""
    pa, _ = _series_for(SRC)
    _patch_fetch(monkeypatch, {"soybean_oil_usd_t": _rec("soybean_oil_usd_t", pa)})
    lines, tr = cq._rv_price_reading(None, "soybean_oil_cbot", "soybean_oil_dce",
                                     _fired(), None, ASOF, [], 0, _ERA)
    assert lines == [] and tr == {"decline": "shape"}


class _Node:
    """One mapped-ref node so quantify builds a group and reaches the xc seam (the test_comove
    _seam_groups harness, verbatim in shape)."""
    def __init__(self):
        self.contract = SRC
        self.prior = {}
        self.evidence = [{"event_date": "2020-05-01"}, {"event_date": "2020-06-01"}]


def _seam_groups(monkeypatch):
    monkeypatch.setattr(cq, "_silver_ref", lambda n: "psd_export")
    monkeypatch.setattr(cq, "map_row", lambda ref: {"table": "silver_psd", "metric": "exports_mt",
                                                    "period_type": "marketing_year", "agg": "latest",
                                                    "country_rule": "none"})


def test_quantify_threads_rv_reading_and_replay(monkeypatch):
    seen: dict = {}
    _seam_groups(monkeypatch)
    monkeypatch.setattr(cq, "_run_xc", lambda *a, **k: seen.update(k) or ([], None))
    sg = _SG()
    sg.nodes = [_Node()]
    cq.quantify(sg, None, qfn=lambda sql: [], asof=ASOF, near=None, extra_number_calls=[],
                xc_request=REQ, rv_reading=True, price_replay=True)
    assert seen.get("reading") is True and seen.get("replay") is True
    seen.clear()
    sg2 = _SG()
    sg2.nodes = [_Node()]
    cq.quantify(sg2, None, qfn=lambda sql: [], asof=ASOF, near=None, extra_number_calls=[],
                xc_request=REQ)
    assert seen.get("reading") is False and seen.get("replay") is False


@pytest.mark.parametrize("val,want", [("on", True), ("1", True), ("TRUE", True), ("", False),
                                      ("off", False), ("yes", False)])
def test_answer_rv_reading_flag_grammar(monkeypatch, val, want):
    from leviathan.graphrag import answer as ans
    monkeypatch.setenv("GRAPHRAG_RV_READING", val)
    assert ans._rv_reading_on() is want


def test_answer_rv_reading_default_dark(monkeypatch):
    from leviathan.graphrag import answer as ans
    monkeypatch.delenv("GRAPHRAG_RV_READING", raising=False)
    assert ans._rv_reading_on() is False


# ════════════════════════════════════════════════════════════════════════════════════════════════════
# D -- governance
# ════════════════════════════════════════════════════════════════════════════════════════════════════
def test_pair_spread_not_in_stat_registry():
    """Pin #10: the agent tool enum never widens as a side effect (the `quantiles` discipline)."""
    assert "pair_spread" not in st.STAT_REGISTRY
    assert st.is_banned_name("pair_spread") is False


def test_rv_metrics_declared_on_the_card_two_way():
    """Pin #11 + R4c coherence: every reachable metric is declared on the loaded card AND inside the
    ratified allow-list; the written-down absences are genuinely absent (drift belt, both ways)."""
    from leviathan.graphrag.config_check import SYNTHESIZED_PRICE_LEG_ALLOW, _check_synthesized_price_legs
    from leviathan.graphrag.numbers.registry import load_registry
    card = load_registry().tables.get(cq._RV_PRICE_TABLE)
    assert card is not None
    reachable = {m for m, _l in cq._RV_PRICE_SERIES.values()}
    assert reachable <= set(card.metrics)
    assert reachable <= SYNTHESIZED_PRICE_LEG_ALLOW[cq._RV_PRICE_TABLE]
    for absent in ("palm_olein_usd_t", "white_sugar_usd_t", "rapeseed_meal_usd_t", "canola_usd_t",
                   "rapeseed_usd_t"):
        assert absent not in card.metrics, absent
    assert _check_synthesized_price_legs() == []


def test_r4c_catches_a_stray_synthesized_metric(monkeypatch):
    """R4c fail-closed proof: a metric added to the code without a register sitting reds the build."""
    from leviathan.graphrag import config_check as cc
    stray = dict(cq._RV_PRICE_SERIES)
    # re-anchored 2026-09-02: beef_usd_t is now RATIFIED (the V2-1 context cell registered it), so the
    # stray is copper_usd_mt -- declared on the card, on no synthesized surface, NOT ratified.
    stray["cocoa_smuggled"] = ("copper_usd_mt", "world copper")
    monkeypatch.setattr(cq, "_RV_PRICE_SERIES", stray)
    errs = cc._check_synthesized_price_legs()
    assert any("copper_usd_mt" in e and "outside the ratified allow-list" in e for e in errs)


def test_r4_fences_untouched():
    """Pin #14: the reading adds NO map row -- both R4 halves stay green, and the name-ban error string
    is not weakened by one byte."""
    from leviathan.graphrag import config_check as cc
    assert cc._check_price_context_lane() == []
    import inspect
    src = inspect.getsource(cc._check_price_context_lane)
    assert "is a price " in src and "never a relative-value leg" in src


def test_outcomes_rider_is_dark():
    """Pin #12: the outcomes-join analogue has NO code behind it -- the sub-flag token appears nowhere
    in cascade.py, and a rendered full-rung reading emits no conditional-history line."""
    import inspect
    src = inspect.getsource(cq)
    assert "RV_READING_OUTCOMES" not in src
    assert "stood at or beyond" not in src


def test_prose_constants_are_register_clean():
    for s in (st.CURRENCY_MISMATCH_DECLINE.format(a="MYR", b="CNY"),
              st.BOTH_UNITS_REQUIRED_DECLINE,
              st.NONPOSITIVE_DENOMINATOR_DECLINE.format(k=2, n=60, when="2024-01-01")):
        assert reg.register_leaks(s) == [] and reg.exec_leaks(s) == [], s
        assert reg.sanitize(s) == s


def test_rv_reading_copy_surface_is_verifier_proof(monkeypatch):
    """K1 RCA pin (2026-09-01, audited pair 101703Z/103129Z): the verifier's P9-B all-numbers guard
    strips any writer sentence carrying a FREE window-length numeral ("of the prior 58 months"), and
    the per-handle check strips a streak whose count the writer respelled in words. Every copy-surface
    the reading hands the writer must therefore print counts as digits and window lengths ONLY in the
    hyphenated duration-modifier form the extractor exempts ("60-month" -- measured surviving in the
    same corpus), and the directive must order the writer to transcribe digits verbatim."""
    import re as _re
    free_count = _re.compile(r"\b\d+\s+(?:months?|monthly observations|marketing years)\b")
    pa, pb = _series_for(SRC)
    _patch_fetch(monkeypatch, {M_SRC: _rec(M_SRC, pa), M_TGT: _rec(M_TGT, pb)})
    lines, tr = cq._rv_price_reading(None, SRC, TGT, _fired(), None, ASOF, [], 0, _ERA)
    body = "\n".join(lines)
    assert tr["rung"] == "full"
    assert "60-month" in body and not free_count.search(body)
    assert "copy every figure in this block as DIGITS" in body      # the TRANSCRIPTION directive
    # ordinal-thin branch: the same discipline on the thin-history copy-surface
    pa5, pb5 = _series_for(SRC, months=5)
    _patch_fetch(monkeypatch, {M_SRC: _rec(M_SRC, pa5), M_TGT: _rec(M_TGT, pb5)})
    lines5, tr5 = cq._rv_price_reading(None, SRC, TGT, _fired(), None, ASOF, [], 0, _ERA)
    body5 = "\n".join(lines5)
    assert tr5["rung"] == "ordinal_thin"
    assert "5-month" in body5 and "-month floor" in body5 and not free_count.search(body5)


def test_rv_reading_payoff_sentence_never_carries_the_streak_handle(monkeypatch):
    """K1 pair #2 pin (2026-09-01, 113447Z): the writer respells small counts as words even under the
    TRANSCRIPTION directive, and a streak handle inside the payoff sentence then deletes percentile,
    sigma and level with it. The streak is a block row only -- the PRICE-RELATIVE directive sentence
    must cite the level/percentile/sigma rows and NEVER the streak row."""
    pa, pb = _series_for(SRC)
    _patch_fetch(monkeypatch, {M_SRC: _rec(M_SRC, pa), M_TGT: _rec(M_TGT, pb)})
    lines, tr = cq._rv_price_reading(None, SRC, TGT, _fired(), None, ASOF, [], 0, _ERA)
    assert tr["rung"] == "full"
    directive = next(l for l in lines if l.startswith("PRICE-RELATIVE on the monthly benchmark"))
    streak_rows = [l for l in lines if l.startswith("- [N") and "consecutive monthly" in l]
    assert streak_rows, "fixture must exercise the streak row"
    handle = streak_rows[0].split("]")[0] + "]"                     # e.g. "- [N4]" -> "- [N4]"
    n_handle = handle.split("[")[1].rstrip("]")                     # "N4"
    assert f"[{n_handle}]" not in directive
    assert "consecutive monthly" not in directive
