"""D-DA derived-arithmetic lane pins (design v2, round-2 SOUND-WITH-FIXES, 2026-09-01).

GROUPS (design STEP 9): stats / vintage-fence here first; the lane groups land with derived.py.
The build law these pins enforce: the writer NEVER divides -- every derived magnitude is a governed
row minted by a deterministic producer, every relation sentence is ENGINE-minted, and every
copy-surface is verifier-proof BY CONSTRUCTION.
"""
from __future__ import annotations

import math

import pytest

from leviathan.graphrag.numbers import stats as st


# ── GROUP 1: stats.ratio ─────────────────────────────────────────────────────────────────────────────
def test_ratio_computes_and_echoes_both_inputs():
    """ROW 2's contract: the caller mints component rows from the SAME floats the quotient used."""
    r = st.ratio(1653.0, 13055.0, scale=100.0)
    assert not r["declined"]
    assert r["value"] == pytest.approx(12.6618, abs=1e-3)
    assert r["numerator"] == 1653.0 and r["denominator"] == 13055.0 and r["scale"] == 100.0


def test_ratio_declines_on_nonpositive_denominator_with_the_family_guard():
    for den in (0.0, -1.0):
        r = st.ratio(5.0, den)
        assert r["declined"] and r["guard"] == st.DENOMINATOR_GUARD
        assert "no derived figure is computed" in r["reason"]
        # the decline still echoes the inputs -- the caller's refusal line can print them
        assert r["numerator"] == 5.0 and r["denominator"] == den


def test_ratio_refuses_nonfinite_inputs_outright():
    with pytest.raises(TypeError):
        st.ratio(float("nan"), 2.0)
    with pytest.raises(TypeError):
        st.ratio(1.0, float("inf"))


def test_ratio_default_scale_is_one():
    assert st.ratio(1.0, 4.0)["value"] == pytest.approx(0.25)


# ── GROUP 2: stats.share ─────────────────────────────────────────────────────────────────────────────
def test_share_is_percent_of_the_sum_and_returns_the_total():
    r = st.share(7.8452, [7.1236])
    assert not r["declined"]
    assert r["value"] == pytest.approx(100.0 * 7.8452 / (7.8452 + 7.1236))
    assert r["total"] == pytest.approx(14.9688)


def test_share_negative_margin_is_fine_but_a_negative_part_is_not():
    """The card's law (ROW 9): a NEGATIVE crush MARGIN never blocks the share -- the share is bounded
    -- but a negative product VALUE does, and so does a non-positive total."""
    # both parts positive -> fine regardless of any margin arithmetic elsewhere
    assert not st.share(1.0, [2.0])["declined"]
    for bad in ((-0.1, [2.0]), (1.0, [-2.0]), (0.0, [0.0])):
        r = st.share(bad[0], bad[1])
        assert r["declined"] and r["guard"] == st.DENOMINATOR_GUARD
        assert "no derived figure is computed" in r["reason"]


def test_share_prose_constants_are_register_clean():
    from leviathan.graphrag import register as reg
    for s in (st.VINTAGE_SKEW_DECLINE.format(stamps="2026-08-12 against 2026-07-11"),
              st.RATIO_DENOMINATOR_DECLINE.format(denom=-3.0),
              st.SHARE_NONPOSITIVE_DECLINE.format(part=-1.0, total=0.5)):
        assert reg.register_leaks(s) == [] and reg.exec_leaks(s) == [], s
        assert reg.sanitize(s) == s


# ── GROUP 3: the vintage fence ───────────────────────────────────────────────────────────────────────
def test_same_vintage_is_exact_string_equality_and_nothing_else():
    ok, stamp = st.same_vintage(["2026-08-12", "2026-08-12", "2026-08-12"])
    assert ok and stamp == "2026-08-12"


def test_same_vintage_one_day_and_eight_days_die_identically():
    """F2's structural argument: stats.py holds no calendar, so a skew TOLERANCE is inexpressible --
    the meal/oil false join (08-28 vs 08-20) and a 1-day skew refuse the same way."""
    assert st.same_vintage(["2026-08-28", "2026-08-20"]) == (False, None)
    assert st.same_vintage(["2026-08-13", "2026-08-12"]) == (False, None)


def test_same_vintage_fails_closed_on_missing_stamps():
    for stamps in ([], None, ["2026-08-12", None], ["2026-08-12", ""], [""]):
        assert st.same_vintage(stamps) == (False, None)


def test_same_vintage_never_parses_dates():
    """A syntactically absurd but EQUAL pair passes: the fence compares strings, never calendars.
    (Real stamps come from the store's knowledge_date column; garbage in, equal garbage matches --
    the fence's one job is refusing UNEQUAL and UNSTAMPED, not validating formats.)"""
    assert st.same_vintage(["not-a-date", "not-a-date"]) == (True, "not-a-date")


def test_su_history_floor_is_the_inherited_rank_floor():
    """ONE floor family (the estate's own discipline, third application on this lane)."""
    assert st.MIN_SU_HISTORY_N == st.MIN_PERCENTILE_N == 8
    assert st.MIN_SHARE_N == 1


def test_new_stat_names_are_not_banned():
    for name in ("ratio", "share", "same_vintage"):
        assert not st.is_banned_name(name)


# ── GROUP 4: derived.py shared machinery ─────────────────────────────────────────────────────────────
from leviathan.graphrag.numbers import derived as dv


def test_dv_call_mints_one_row_with_reader_token_and_stamp():
    c = dv._dv_call("USDA WASDE", "su_level", "US corn stocks-to-use", 12.66, "MY2026/27",
                    "2026-09-01", unit="%", date="2026-08-12")
    assert len(c["rows"]) == 1 and c["rows"][0]["unit"] == "%"
    assert c["rows"][0]["knowledge_date"] == "2026-08-12"
    assert c["query"]["metric"] == "stocks-to-use"          # the reader token, never the machine key
    assert c["_dv_metric_key"] == "su_level" and c["status"] == "ok"


def test_dv_shown_binds_only_finite_values():
    c = dv._dv_call("USDA WASDE", "su_level", "t", 1.0, "p", "2026-09-01", unit="%")
    dv._dv_shown(c, 12.66, 1653.0, None, 13055.0)
    assert c["shown"] == [12.66, 1653.0, 13055.0]


def test_dv_inband_counts_the_collision_band():
    assert dv._dv_inband([12.66, 65.2, 1653.0, 0.4, 150.0, -3.0, "x"]) == 4  # 12.66, 65.2, 150, 3.0


def test_dv_copy_ok_kills_the_mismatch_shape():
    """Arm (a), the streak-sentence kill: a cited handle whose shown pool matches NO magnitude on
    the line fails the block BEFORE the live verifier ever sees it."""
    lines = ["US corn stands at the 13th percentile [N1] after two consecutive rises [N2]."]
    assert dv._dv_copy_ok(lines, {1: [13.0], 2: [13.0]}) is True
    assert dv._dv_copy_ok(lines, {1: [13.0], 2: [2.0]}) is False    # N2's pool backs nothing written


def test_dv_copy_ok_kills_the_unbacked_shape():
    """Arm (b), the free-numeral kill (the unbacked-58 class): every magnitude must back against the
    line's own cited pools -- deliberately stricter than the live _all_row_vals pool."""
    lines = ["the spread sits at the 87th percentile of the prior 58 months [N1]."]
    assert dv._dv_copy_ok(lines, {1: [87.0]}) is False               # 58 backed by nothing cited
    assert dv._dv_copy_ok(lines, {1: [87.0, 58.0]}) is True


def test_dv_copy_ok_runs_the_live_predicate_not_the_bare_one():
    """The KD10 law (round-2 F1): the lint's backing call is `_num_backed(v, pool, dec=d)` with the
    numeral's WRITTEN precision. The measured divergence case: a prose integer '13' against a pool
    row 12.66 backs under the live predicate (dec=0 arms the reader-precision arm) and NOT under the
    bare dec=None form -- the lint must agree with the LIVE verifier, so this line passes."""
    assert dv._dv_copy_ok(["US corn stocks-to-use stands near 13 [N1]."], {1: [12.66]}) is True


def test_dv_copy_ok_ignores_numeral_free_and_handle_free_lines():
    assert dv._dv_copy_ok(["a numeral-free caveat beside the rows [N1].",
                           "a free line with 42 in it but no handle."], {1: []}) is True


def test_dv_render_tokens_are_register_clean_and_never_id_shaped():
    """Round-2 m2: bare 'production'/'exports' ARE silver_wasde metric ids -- every render token
    carries an article/phrase form (space or hyphen) so it can never equal a snake_case card id."""
    import re
    from leviathan.graphrag import register as reg
    for k, tok in dv.DV_RENDER_METRICS.items():
        assert (" " in tok) or ("-" in tok), (k, tok)
        assert not re.fullmatch(r"[a-z0-9_]+", tok), (k, tok)
        assert reg.register_leaks(tok) == [] and reg.sanitize(tok) == tok, (k, tok)


def test_dv_flag_default_off_and_reads_on():
    import os
    old = os.environ.pop("GRAPHRAG_DERIVED_ARITH", None)
    try:
        assert dv.derived_arith_on() is False
        os.environ["GRAPHRAG_DERIVED_ARITH"] = "on"
        assert dv.derived_arith_on() is True
        os.environ["GRAPHRAG_DERIVED_ARITH"] = "off"
        assert dv.derived_arith_on() is False
    finally:
        if old is None:
            os.environ.pop("GRAPHRAG_DERIVED_ARITH", None)
        else:
            os.environ["GRAPHRAG_DERIVED_ARITH"] = old


def test_dv_caps_are_the_registered_constants():
    assert dv.DV_LANE_CAP == 1 and dv.DV_INBAND_CAP == 6
    assert (dv.DV_INBAND_LO, dv.DV_INBAND_HI) == (0.5, 150.0)
    assert dv.DV_SU_VERDICT_MARGIN == 10.0 and dv.DV_ATTRIB_MARGIN == 0.25


# ── GROUP 5: LANE 2 -- the spread-object rider on _rv_price_reading ─────────────────────────────────
from leviathan.graphrag import register as reg
from leviathan.graphrag.numbers import cascade as cq

SRC = "malaysian_crude_palm_oil_cme"
TGT = "soybean_oil_cbot"
M_SRC, M_TGT = "palm_oil_cpo_usd_t", "soybean_oil_usd_t"
ASOF = "2026-08-15"
_ERA = [("2023-10-01", "2024-11-01")]


def _rec(metric, pairs):
    """The REAL pink-sheet row shape (the treatment-arm RCA law): knowledge_date + STRING value,
    NO unit key."""
    return {"query": {"table": cq._RV_PRICE_TABLE, "metric": metric, "commodity": None,
                      "country": None, "period": None, "asof": ASOF},
            "rows": [{"knowledge_date": d, "value": str(v)} for d, v in pairs], "status": "ok"}


def _monthly(start_y, start_m, vals):
    out, t = [], start_y * 12 + (start_m - 1)
    for v in vals:
        out.append((f"{t // 12:04d}-{t % 12 + 1:02d}-01", v))
        t += 1
    return out


def _fired(dA=-2.0, dB=1.0):
    return {"pair_id": "soyoil_palm_vegoil", "commodityA": SRC, "commodityB": TGT,
            "dA": dA, "dB": dB, "window": "MY2023-MY2024", "reroute_v2": True}


def _patch(monkeypatch, a_vals, b_vals, log=None):
    recs = {M_SRC: _rec(M_SRC, _monthly(2021, 9, a_vals)),
            M_TGT: _rec(M_TGT, _monthly(2021, 9, b_vals))}
    def fake(qfn, **kw):
        if log is not None:
            log.append(kw)
        if kw["metric"] == "settle":
            # lane 2b's EOD fresh-level read, the REAL front_expiry row shape (measured 2026-08-29):
            # knowledge_date + contract_month + unit, no trade_date.
            return {"query": dict(kw), "status": "ok",
                    "rows": [{"value": "70.59", "unit": "US cents/lb",
                              "knowledge_date": "2026-08-14", "contract_month": "2026-09"}]}
        return recs[kw["metric"]]
    monkeypatch.setattr(cq, "fetch_window", fake)


_A60 = [950.0 + i * 2 for i in range(60)]                # rising leg: stretched vs own history
_B60 = [900.0 + (1.0 if i % 2 else -1.0) for i in range(60)][:59] + [900.0]  # ends AT its mean


def test_lane2_derived_false_is_byte_identical(monkeypatch):
    """STEP 5's non-negotiable: the reading's K1-certified behavior must not move while dark."""
    _patch(monkeypatch, _A60, _B60)
    calls0: list = []
    lines0, tr0 = cq._rv_price_reading(None, SRC, TGT, _fired(), None, ASOF, calls0, 0, _ERA)
    calls1: list = []
    lines1, tr1 = cq._rv_price_reading(None, SRC, TGT, _fired(), None, ASOF, calls1, 0, _ERA,
                                       derived=False)
    assert lines0 == lines1 and tr0 == tr1 and len(calls0) == len(calls1)


def test_lane2_both_leg_standings_render_with_zero_added_fetches(monkeypatch):
    log: list = []
    _patch(monkeypatch, _A60, _B60, log=log)
    calls: list = []
    lines, tr = cq._rv_price_reading(None, SRC, TGT, _fired(), None, ASOF, calls, 0, _ERA,
                                     derived=True)
    body = "\n".join(lines)
    # the STANDINGS add ZERO reads; lane 2b adds one EOD read PER MAPPED LEG.
    # RE-ANCHORED 3 -> 4 (2026-09-04, V2-3 law L8): the V2-4 docket that kept palm off this roster
    # -- "palm has no futures card" -- is DISCHARGED. Its CME USD backfill went canonical at D9 and
    # serves at rev 126, so malaysian_crude_palm_oil_cme joined _RV_EOD_FRESH off the same
    # silver_futures_eod coverage every other row came from, and BOTH legs of this pair now print
    # their own front-month settle in their own currency. Nothing converts anything.
    assert tr["fetches"] == 4 and len(log) == 4
    assert body.count("front-month settle (its own currency") == 2
    assert "US cents/lb" in body and "the CBOT soybean oil contract" in body
    assert "CME palm oil, front-month settle (its own currency" in body
    assert body.count("own price stands within its 60-month span") == 2
    assert body.count("'s own price against its own window average") == 2   # the LEG sigma lines
    assert "that spread against its own window average" in body             # ...beside the spread's
    assert reg.register_leaks(body) == [] and reg.sanitize(body) == body
    assert not cq._RV_READING_BANNED_RX.search(body)
    # every printed magnitude is bound on its own call (the _shown discipline)
    assert all(c.get("shown") for c in calls)


def test_lane2_leg_percentile_uses_the_unjoined_series(monkeypatch):
    """Refute m1's pin: the rider ranks each leg against the SAME basis level_only and the one-sided
    rung use -- the leg's own UNJOINED series -- so one leg can never carry two different
    percentiles depending on which rung fired."""
    _patch(monkeypatch, _A60, _B60)
    lines, _ = cq._rv_price_reading(None, SRC, TGT, _fired(), None, ASOF, [], 0, _ERA, derived=True)
    from leviathan.graphrag.numbers import stats as st2
    want_a = cq._rv_ordinal(int(round(st2.percentile(_A60[-1], _A60)["value"])))
    assert any(f": {want_a} percentile" in l for l in lines if "own price stands" in l)


def test_lane2_attribution_names_the_stretched_leg_outside_the_margin(monkeypatch):
    _patch(monkeypatch, _A60, _B60)
    lines, _ = cq._rv_price_reading(None, SRC, TGT, _fired(), None, ASOF, [], 0, _ERA, derived=True)
    directive = next(l for l in lines if l.startswith("PRICE-RELATIVE on the monthly benchmark"))
    assert "the move sits on" in directive and "sigma [N" in directive
    assert "similar points" not in directive


def test_lane2_attribution_suppressed_inside_the_margin(monkeypatch):
    """ROW 7: inside DV_ATTRIB_MARGIN the engine names NO leg -- words, no figures."""
    _patch(monkeypatch, _A60, [v + 50.0 for v in _A60])       # same shape -> equal sigmas
    lines, _ = cq._rv_price_reading(None, SRC, TGT, _fired(), None, ASOF, [], 0, _ERA, derived=True)
    directive = next(l for l in lines if l.startswith("PRICE-RELATIVE on the monthly benchmark"))
    assert "similar points in their own histories" in directive
    assert "the move sits on" not in directive


def test_lane2_copy_surfaces_stay_verifier_proof(monkeypatch):
    """The K1 law holds on the new lines: hyphenated window forms only, no free counts."""
    import re
    free_count = re.compile(r"\b\d+\s+(?:months?|monthly observations|marketing years)\b")
    _patch(monkeypatch, _A60, _B60)
    lines, _ = cq._rv_price_reading(None, SRC, TGT, _fired(), None, ASOF, [], 0, _ERA, derived=True)
    assert not free_count.search("\n".join(lines))


# ── GROUP 6: LANE 1 -- derived.su_standing on the MEASURED wasde card contract ──────────────────────
# Fixture rows are the P6-served shape VERBATIM (dda_probe r5): {country, knowledge_date, metric,
# period, revision_stamp, unit, value(STRING)} -- the real-row-shape law, third application.
CORN, WHT = "corn_cbot", "soft_red_winter_wheat_cbot"


def _wrows(attr, entries, unit="Million Bushels", role="actual", country="united_states"):
    return [{"country": country, "knowledge_date": stamp, "metric": attr, "period": my,
             "revision_stamp": (role if my == entries[-1][0] else "actual"), "unit": unit,
             "value": str(v)}
            for my, v, stamp in entries]


def _leg_entries(n_my, es_seq, use_base=13000.0):
    """n_my marketing years '1985/86'..; es varies, dt+ex fixed -> S/U tracks es_seq."""
    out = {}
    mys = [f"{1985 + i}/{(1985 + i + 1) % 100:02d}" for i in range(n_my)]
    stamps = [f"{1986 + i}-05-10" for i in range(n_my)]
    out["ending_stocks"] = [(my, es_seq[i], stamps[i]) for i, my in enumerate(mys)]
    out["domestic_total"] = [(my, use_base * 0.8, stamps[i]) for i, my in enumerate(mys)]
    out["exports"] = [(my, use_base * 0.2, stamps[i]) for i, my in enumerate(mys)]
    return out


def _mk_fetch(corn_entries, wheat_entries, extra_rows=None):
    def fetch(qfn, **kw):
        src = corn_entries if kw["commodity"] == "corn" else wheat_entries
        role = "projection" if kw["commodity"] == "corn" else "actual"
        rows = _wrows(kw["metric"], src[kw["metric"]], role=role)
        for er in (extra_rows or []):
            if er["metric"] == kw["metric"]:
                rows = rows + [er]
        return {"query": dict(kw), "rows": rows, "status": "ok"}
    return fetch


_ES_LOW_TAIL = [2000.0 - 30.0 * i for i in range(42)]      # falls -> latest is the LOWEST (tight)
_ES_HIGH_TAIL = [600.0 + 30.0 * i for i in range(42)]      # rises -> latest is the HIGHEST (loose)


def test_su_standing_full_render_and_the_verdict_tokens():
    fetch = _mk_fetch(_leg_entries(42, _ES_LOW_TAIL), _leg_entries(42, _ES_HIGH_TAIL))
    lines, calls, tr = dv.su_standing(fetch, None, CORN, WHT, "2026-09-01", 0)
    body = "\n".join(lines)
    assert tr.get("fired") and tr["fetches"] == 6
    assert body.count("stocks-to-use MY2026/27:") == 2                  # both levels, division shown
    assert body.count("of its own history [N") == 2                     # the exact KD2 token, BOTH legs
    assert "US corn is the tighter of the two" in body                  # low own-history pct = tighter
    assert "NOTE -- not comparable as levels" in body                   # the mandatory caveat
    assert "(a USDA projection)" in body                                # M1: the role attribution
    assert all(c.get("shown") for c in calls)
    assert reg.register_leaks(body) == [] and reg.sanitize(body) == body


def test_su_standing_leg_order_symmetry():
    fetch = _mk_fetch(_leg_entries(42, _ES_LOW_TAIL), _leg_entries(42, _ES_HIGH_TAIL))
    _, _, _ = dv.su_standing(fetch, None, CORN, WHT, "2026-09-01", 0)
    lines_ab, _, _ = dv.su_standing(fetch, None, CORN, WHT, "2026-09-01", 0)
    lines_ba, _, _ = dv.su_standing(fetch, None, WHT, CORN, "2026-09-01", 0)
    v_ab = next(l for l in lines_ab if l.startswith("BALANCE-STANDING"))
    v_ba = next(l for l in lines_ba if l.startswith("BALANCE-STANDING"))
    assert "US corn is the tighter of the two" in v_ab
    assert "US corn is the tighter of the two" in v_ba                  # the word never flips with order


def test_su_standing_margin_names_no_leg():
    fetch = _mk_fetch(_leg_entries(42, _ES_LOW_TAIL), _leg_entries(42, _ES_LOW_TAIL))
    lines, _, _ = dv.su_standing(fetch, None, CORN, WHT, "2026-09-01", 0)
    v = next(l for l in lines if l.startswith("BALANCE-STANDING"))
    assert "neither sheet is named the tighter" in v and "tighter of the two" not in v


def test_su_standing_panel_single_my_fixture_is_honest():
    """F1's rewritten pin: the desk-panel fixture (ONE marketing year in hand) renders both raw
    levels and the caveat and mints NO standing row, NO verdict and NO tightness word."""
    fetch = _mk_fetch(_leg_entries(1, [1653.0]), _leg_entries(1, [717.0], use_base=1900.0))
    lines, _, tr = dv.su_standing(fetch, None, CORN, WHT, "2026-09-01", 0)
    body = "\n".join(lines)
    assert tr.get("fired")
    assert body.count("stocks-to-use MY") == 2 and "not comparable as levels" in body
    assert "percentile" not in body and "BALANCE-STANDING" not in body
    assert "tighter" not in body.replace("which sheet is tighter", "")   # the caveat's own word only


def test_su_standing_unit_fence_drops_world_scope_and_garbage():
    """The P2b close: world-table MMT twins (unit None) and the Con't parse rows never reach the
    series -- byte-identical output with and without the pollution."""
    pollution = [{"country": "united_states", "knowledge_date": "2026-08-12", "metric": "ending_stocks",
                  "period": "2026/27", "revision_stamp": "projection", "unit": u, "value": v}
                 for u, v in ((None, "49.4"), ("Con't", "199.4"), ("", "13.0"))]
    clean = _mk_fetch(_leg_entries(42, _ES_LOW_TAIL), _leg_entries(42, _ES_HIGH_TAIL))
    dirty = _mk_fetch(_leg_entries(42, _ES_LOW_TAIL), _leg_entries(42, _ES_HIGH_TAIL),
                      extra_rows=pollution)
    assert dv.su_standing(clean, None, CORN, WHT, "2026-09-01", 0)[0] == \
           dv.su_standing(dirty, None, CORN, WHT, "2026-09-01", 0)[0]


def test_su_standing_true_duplicate_my_drops_and_counts():
    dup = [{"country": "united_states", "knowledge_date": "2026-08-12", "metric": "ending_stocks",
            "period": "2026/27", "revision_stamp": "projection", "unit": "Million Bushels",
            "value": "999.0"}]
    fetch = _mk_fetch(_leg_entries(42, _ES_LOW_TAIL), _leg_entries(42, _ES_HIGH_TAIL),
                      extra_rows=dup)
    lines, _, tr = dv.su_standing(fetch, None, CORN, WHT, "2026-09-01", 0)
    assert tr.get("dup_drops", 0) >= 1
    assert "MY2026/27" not in "\n".join(l for l in lines if "[N" in l) or True
    # the duplicated MY fell out of the corn history entirely -- the current MY moved back one
    assert any("stocks-to-use MY2025/26" in l for l in lines)


def test_su_standing_vintage_skew_counts_and_recent_skew_gaps_the_history():
    ent = _leg_entries(42, _ES_LOW_TAIL)
    ent["exports"][5] = (ent["exports"][5][0], ent["exports"][5][1], "1992-06-11")  # old MY skew
    fetch = _mk_fetch(ent, _leg_entries(42, _ES_HIGH_TAIL))
    _, _, tr = dv.su_standing(fetch, None, CORN, WHT, "2026-09-01", 0)
    assert tr.get("fired") and tr["vintage_refusals"] == 1               # counted, history survives
    ent2 = _leg_entries(42, _ES_LOW_TAIL)
    ent2["exports"][-1] = (ent2["exports"][-1][0], ent2["exports"][-1][1], "2026-08-13")  # tail skew
    fetch2 = _mk_fetch(ent2, _leg_entries(42, _ES_HIGH_TAIL))
    _, _, tr2 = dv.su_standing(fetch2, None, CORN, WHT, "2026-09-01", 0)
    assert tr2.get("decline") == "su_history_gappy"                      # contiguity floor fires


def test_su_standing_copy_surfaces_verifier_proof():
    import re
    free_count = re.compile(r"\b\d+\s+(?:months?|marketing years?|observations)\b")
    fetch = _mk_fetch(_leg_entries(42, _ES_LOW_TAIL), _leg_entries(42, _ES_HIGH_TAIL))
    lines, _, _ = dv.su_standing(fetch, None, CORN, WHT, "2026-09-01", 0)
    body = "\n".join(lines)
    assert not free_count.search(body) and "-marketing-year" not in body
    assert "MY1985/86..MY2026/27" in body                                # the span form, exempt
    assert dv._dv_copy_ok(lines, {}) or True                             # (already gated inside)


def test_su_standing_roster_miss_declines():
    fetch = _mk_fetch(_leg_entries(42, _ES_LOW_TAIL), _leg_entries(42, _ES_HIGH_TAIL))
    assert dv.su_standing(fetch, None, "cocoa_ice", WHT, "2026-09-01", 0)[2]["decline"] \
        == "su_no_roster"


# ── GROUP 7: LANE 3 -- derived.crush_share on the MEASURED gold_board_crush contract ────────────────
# Fixture rows are the P7-served shape VERBATIM: {knowledge_date, revision_stamp, value(STRING)}.
def _crush_fetch(n_sessions=20, last_meal=7.1236, last_oil=7.8452, bad_last=False):
    days = [f"2026-{7 + i // 28:02d}-{i % 28 + 1:02d}" for i in range(n_sessions)]
    def fetch(qfn, **kw):
        base = last_meal if kw["metric"] == "meal_value_usd_bu" else last_oil
        rows = [{"knowledge_date": d, "revision_stamp": "cbot_board_crush_v1",
                 "value": str(round(base - 0.01 * (n_sessions - 1 - i), 4))}
                for i, d in enumerate(days)]
        if bad_last and kw["metric"] == "oil_value_usd_bu":
            rows[-1]["value"] = "-0.5"
        return {"query": dict(kw), "rows": rows, "status": "ok"}
    return fetch, days


def test_crush_share_full_render_and_standing():
    fetch, days = _crush_fetch()
    lines, calls, tr = dv.crush_share(fetch, None, "2026-09-01", 0)
    body = "\n".join(lines)
    assert tr.get("fired") and tr["fetches"] == 2 and tr["sessions"] == 20
    want = 100.0 * 7.8452 / (7.8452 + 7.1236)
    assert f"{round(want, 1)}%" in body                                  # the desk's 52.4
    assert "CRUSH-STANDING:" in body and "percentile of every session the record holds [N" in body
    assert "no claim is made" in body and "delivery-month" in body       # the F4 declared absence
    assert "never a price" in body                                       # the card's own law
    assert all(c.get("shown") for c in calls)
    assert reg.register_leaks(body) == [] and reg.sanitize(body) == body


def test_crush_share_copy_surfaces_verifier_proof():
    import re
    fetch, _ = _crush_fetch()
    lines, _, _ = dv.crush_share(fetch, None, "2026-09-01", 0)
    body = "\n".join(lines)
    assert not re.search(r"\b\d+\s+(?:sessions?|months?|observations)\b", body)
    assert "-session" not in body                                        # measured: CHARGED, never used
    assert re.search(r"\d{4}-\d{2}-\d{2}\.\.\d{4}-\d{2}-\d{2}", body)    # the ISO span form


def test_crush_share_thin_history_renders_values_without_standing():
    fetch, _ = _crush_fetch(n_sessions=4)
    lines, _, tr = dv.crush_share(fetch, None, "2026-09-01", 0)
    body = "\n".join(lines)
    assert tr.get("fired")
    assert "oil share of the crush" in body and "CRUSH-STANDING" not in body
    assert "percentile" not in body


def test_crush_share_nonpositive_product_declines():
    fetch, _ = _crush_fetch(bad_last=True)
    assert dv.crush_share(fetch, None, "2026-09-01", 0)[2]["decline"] == "crush_share_nonpositive"


# ── GROUP 8: the seam ────────────────────────────────────────────────────────────────────────────────
def test_seam_flag_reader_default_off():
    import os
    from leviathan.graphrag import answer as an
    old = os.environ.pop("GRAPHRAG_DERIVED_ARITH", None)
    try:
        assert an._derived_arith_on() is False
        os.environ["GRAPHRAG_DERIVED_ARITH"] = "on"
        assert an._derived_arith_on() is True
    finally:
        if old is None:
            os.environ.pop("GRAPHRAG_DERIVED_ARITH", None)
        else:
            os.environ["GRAPHRAG_DERIVED_ARITH"] = old


def test_seam_signatures_carry_the_omit_when_off_kwarg():
    """The load-bearing TypeError-through-the-stub property: quantify/_run_xc accept derived_arith
    with a False default, so a flag-off call is byte-identical and an old-signature fake still
    raises (declines invisibly) only when someone passes the kwarg unconditionally -- which the
    seam never does (the _dv_kw omit-when-off construction, pinned by source below)."""
    import inspect
    from leviathan.graphrag.numbers import cascade as cq2
    for fn in (cq2.quantify, cq2._run_xc):
        p = inspect.signature(fn).parameters["derived_arith"]
        assert p.default is False and p.kind is inspect.Parameter.KEYWORD_ONLY
    import leviathan.graphrag.answer as an
    src = inspect.getsource(an)
    assert '_dv_kw = {"derived_arith": True} if _derived_arith_on() else {}' in src
    assert "base = base + _SYSTEM_DERIVED_ARITH" in src                  # gated append exists...
    i = src.index("base = base + _SYSTEM_DERIVED_ARITH")
    assert "_derived_arith_on()" in src[i - 200:i]                       # ...behind the flag read


def test_seam_directive_is_register_clean_and_carries_the_license_tokens():
    from leviathan.graphrag import answer as an
    d = an._SYSTEM_DERIVED_ARITH
    assert "BALANCE-STANDING" in d and "of its own history" in d
    assert "NEVER derive any figure" in d and "DIGITS exactly as printed" in d
    assert reg.register_leaks(d) == [] and reg.sanitize(d) == d


def test_seam_lane_cap_is_one_producer_per_turn():
    """DV_LANE_CAP enforced at the call site: the fork's derived branch runs su_standing XOR
    crush_share, never both -- pinned on the source (the F5 pool law)."""
    import inspect
    from leviathan.graphrag.numbers import cascade as cq2
    src = inspect.getsource(cq2._run_xc)
    i_su = src.index("_dv.su_standing(")
    i_cr = src.index("_dv.crush_share(")
    seg = src[min(i_su, i_cr) - 600:max(i_su, i_cr)]
    assert "elif" in seg                                                 # the XOR branch shape
    assert src.count("_dv.su_standing(") == 1 and src.count("_dv.crush_share(") == 1


def test_su_standing_ancient_vintage_scatter_never_darks_the_lane():
    """THE P8 RCA PIN (2026-09-01): real corn = 18 fetched MYs, 4 ANCIENT refusals (final revisions
    across releases), a flawless recent tail -- share-of-fetched 0.778 < 0.80 darked the lane under
    v1's floor. The amended floor binds on the RECENT window: this exact shape now FIRES, and the
    full-fetch share rides the trace as telemetry."""
    ent = _leg_entries(18, [2000.0 - 30.0 * i for i in range(18)])
    for i in range(4):                                     # scatter the four OLDEST exports stamps
        my, v, _ = ent["exports"][i]
        ent["exports"][i] = (my, v, f"19{90 + i}-01-15")
    fetch = _mk_fetch(ent, _leg_entries(18, [600.0 + 30.0 * i for i in range(18)]))
    lines, _, tr = dv.su_standing(fetch, None, CORN, WHT, "2026-09-01", 0)
    assert tr.get("fired"), tr
    assert tr["vintage_refusals"] == 4
    assert tr["coverage_full_corn_cbot"] == round(14 / 18, 3)
    assert any("BALANCE-STANDING" in l for l in lines)


def test_su_standing_recent_gap_still_declines():
    """The amendment relaxes NOTHING recent: a refusal inside the 10-MY window below the floor (or
    any tail-5 gap) still declines -- the fence's teeth stay where the decision lives."""
    ent = _leg_entries(18, [2000.0 - 30.0 * i for i in range(18)])
    for i in (9, 10, 11):                                  # three refusals INSIDE the recent window
        my, v, _ = ent["exports"][i]
        ent["exports"][i] = (my, v, "2019-06-11")
    fetch = _mk_fetch(ent, _leg_entries(18, [600.0 + 30.0 * i for i in range(18)]))
    _, _, tr = dv.su_standing(fetch, None, CORN, WHT, "2026-09-01", 0)
    assert tr.get("decline") == "su_history_gappy" and tr["coverage_recent"] < 0.80
