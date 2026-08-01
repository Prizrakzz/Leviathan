"""SEAM B -- F2 price-response leg (Alternative B): hermetic unit tests (no pg/Athena/LLM; stub
query_fn(sql)->rows). Covers the focus-contract->WASDE map + cotton era split, the string-MY slash format
(silver_wasde period_sql_type=string), the unit inheritance from _apply_unit_overrides ([SKEPTIC F6], leg-
local -- _fmt_line/_delta_call untouched), pair-atomicity, the PIT pin (session asof -> settled actual vs
window-end asof -> then-current projection), the flag-off byte-identity of existing cascade rows, the
'## The record' PRICE-RESPONSE clause, the eval price_leg_fired boolean, and the register surface (past-tense
dated price factual passes 0 fences; the 'gap'-futurity landmine fails)."""
from __future__ import annotations

import re
from types import SimpleNamespace

from leviathan.graphrag import answer as an
from leviathan.graphrag import citations as ci
from leviathan.graphrag import eval as ev
from leviathan.graphrag import register as reg
from leviathan.graphrag.numbers import cascade as cq


# ── fixtures ──────────────────────────────────────────────────────────────────────────────────────────
def _node(contract, dates, ref="price", region="US"):
    evd = [{"date": d, "source": "s", "source_key": f"k{i}", "text": "t"} for i, d in enumerate(dates)]
    return SimpleNamespace(contract=contract, id=ref, prior={"silver_ref": ref, "region": region}, evidence=evd)


def _sg(nodes):
    return SimpleNamespace(nodes=nodes, trace={}, fired_regimes=[])


def _my_of(sql):
    m = re.search(r"marketing_year = '([^']*)'", sql)
    return m.group(1) if m else None


def _asof_of(sql):
    m = re.search(r"release_date <= '([^']*)'", sql)
    return m.group(1) if m else None


def _wasde_qfn(values):
    """qfn(sql)->rows keyed by the marketing_year literal in the compiled SQL. Rows carry NO 'unit' -- the
    fetched unit MUST arrive from Q.run's _apply_unit_overrides (the design's whole point)."""
    def qfn(sql):
        my = _my_of(sql)
        return [{"value": str(values[my])}] if my in values else []
    return qfn


def _combined_qfn(wasde):
    """Serves BOTH the silver_wasde price pair (marketing_year slash literals) AND a silver_psd export leg
    (market_year int) so a MAPPED cascade node populates `groups` -- quantify early-returns on empty groups, so
    the price leg (like the xc fork) rides ALONGSIDE a real cascade, never on a bare unmapped focus."""
    def qfn(sql):
        my = _my_of(sql)
        if my in wasde:
            return [{"value": str(wasde[my])}]
        if re.search(r"market_year = \d", sql):                  # silver_psd int MY -> a real export leg
            return [{"value": "100", "market_year": 2011}]
        return []
    return qfn


# ── helpers: the map, region split, slash format, price token ───────────────────────────────────────────
def test_my_slash_format():
    assert cq._my_slash(2011) == "2011/12"
    assert cq._my_slash(2012) == "2012/13"
    assert cq._my_slash(1999) == "1999/00"
    assert cq._my_slash(2009) == "2009/10"


def test_farm_wasde_map_coverage():
    # US farm-gate grains/rice/cotton -> a bare WASDE commodity
    assert cq._farm_wasde("corn_cbot") == "corn"
    assert cq._farm_wasde("soybeans_cbot") == "soybeans"
    assert cq._farm_wasde("soft_red_winter_wheat_cbot") == "wheat"      # all-class
    assert cq._farm_wasde("hard_red_winter_wheat_kcbt") == "wheat"
    assert cq._farm_wasde("hard_red_spring_wheat_mgex") == "wheat"
    assert cq._farm_wasde("rough_rice_cbot") == "rice"
    assert cq._farm_wasde("cotton") == "cotton"
    # NO LEG: Decatur market prices, and everything non-US / non-farm-gate
    for slug in ("soybean_oil_cbot", "soybean_meal_cbot", "soybean_meal_dce", "arabica_coffee",
                 "cocoa", "raw_sugar", "robusta_coffee", "french_wheat_matif", "malaysian_crude_palm_oil_cme"):
        assert cq._farm_wasde(slug) is None, slug


def test_farm_region_cotton_split():
    # the REAL 2011-09 break: pre-2011 the US cotton farm price lives under 'u_s_cotton', 2011+ 'united_states'
    assert cq._farm_region("cotton", 2010) == "u_s_cotton"
    assert cq._farm_region("cotton", 2011) == "united_states"
    assert cq._farm_region("cotton", 2015) == "united_states"
    # every other commodity is always united_states
    assert cq._farm_region("corn", 2005) == "united_states"
    assert cq._farm_region("wheat", 1998) == "united_states"


def test_fmt_price_units():
    assert cq._fmt_price(3.6, "$/bu") == "$3.60/bu"
    assert cq._fmt_price(14.4, "$/cwt") == "$14.40/cwt"
    assert cq._fmt_price(68.09, "c/lb") == "68.09c/lb"
    assert cq._fmt_price(5.0, "") == "5.00"


# ── core render: the 2-MY pair + [N] handles + value-check ───────────────────────────────────────────────
def test_price_pair_renders_two_my_pair_with_handles():
    n = _node("corn_cbot", ["2012-06-15", "2012-08-01"])
    calls: list = []
    lines, fired = cq._price_pair({"focus_contract": "corn_cbot"}, _sg([n]), None, [], _wasde_qfn(
        {"2011/12": "3.60", "2012/13": "6.89"}), "2013-06-01", "2012", calls, len(calls))
    assert fired and fired["price_leg"] is True and fired["commodity"] == "corn"
    # two reader lines + one PRICE-RESPONSE marker line; W4: each row line ends with its SERIES scope.
    # A3 (2026-08-01): the handle itself now states WHAT the level is -- the judged gap on 7 row-runs was
    # that the pair read as an undisclosed stand-in for the CBOT level the question asked about, and the
    # only place the discipline lived was the model-facing PRICE-RESPONSE tail.
    assert lines[0] == ("- [N1] US corn USDA season-average farm price, marketing-year "
                        "(survey actual; not a futures settle) MY2011/12: $3.60/bu "
                        "[series: corn; country: united_states; table: USDA WASDE]")
    assert lines[1] == ("- [N2] US corn USDA season-average farm price, marketing-year "
                        "(survey actual; not a futures settle) MY2012/13: $6.89/bu "
                        "[series: corn; country: united_states; table: USDA WASDE]")
    assert any(ln.startswith("PRICE-RESPONSE on avg_farm_price:") for ln in lines)
    body = "\n".join(lines)
    assert "$3.60/bu" in body and "$6.89/bu" in body
    # both magnitudes are backed by an injected row (the all-numbers strip guard)
    assert len(calls) == 2
    row_vals = [c["rows"][0]["value"] for c in calls]
    assert row_vals == [3.6, 6.89]
    # W4 A/B RCA (2026-08-01): each price call records the level its OWN line printed, so a citation is
    # checked against the displayed figure. _fmt_price renders 2 dp over the 4-dp store; the verifier's
    # 1pct tolerance covers that, so `shown` carries the unrounded float the f-string formatted.
    assert [c["shown"] for c in calls] == [[3.6], [6.89]]
    # the marker cites BOTH handles, direction is prose ('rose')
    marker = [ln for ln in lines if ln.startswith("PRICE-RESPONSE")][0]
    assert "[N1]" in marker and "[N2]" in marker and "rose from" in marker


def test_price_label_keeps_the_all_classes_qualifier_on_wheat():
    """A3: the wheat branch carries BOTH disciplines -- the WASDE US wheat farm price is an all-class
    average, and it is a survey actual rather than a futures settle. Neither may drop when the other lands.
    Asserted on the label expression itself so the pin does not need a second full-render fixture."""
    n = _node("soft_red_winter_wheat_cbot", ["2012-06-15", "2012-08-01"])
    calls: list = []
    lines, fired = cq._price_pair({"focus_contract": "soft_red_winter_wheat_cbot"}, _sg([n]), None, [],
                                  _wasde_qfn({"2011/12": "7.24", "2012/13": "7.77"}),
                                  "2013-06-01", "2012", calls, len(calls))
    assert fired and fired["commodity"] == "wheat"
    assert lines[0].startswith("- [N1] US wheat USDA season-average farm price (all classes), "
                               "marketing-year (survey actual; not a futures settle) MY2011/12: ")


def test_price_pair_direction_falls_when_price_declines():
    n = _node("corn_cbot", ["2012-06-15", "2012-08-01"])
    calls: list = []
    lines, _ = cq._price_pair({"focus_contract": "corn_cbot"}, _sg([n]), None, [], _wasde_qfn(
        {"2011/12": "6.89", "2012/13": "3.60"}), "2013-06-01", "2012", calls, len(calls))
    assert any("fell from" in ln for ln in lines)


# ── [SKEPTIC F6] unit inheritance is leg-local (fetched override), narrate_unit UNSET ────────────────────
def test_price_pair_unit_inherited_from_fetched_override_bu():
    n = _node("corn_cbot", ["2012-06-15", "2012-08-01"])
    calls: list = []
    lines, fired = cq._price_pair({"focus_contract": "corn_cbot"}, _sg([n]), None, [], _wasde_qfn(
        {"2011/12": "3.60", "2012/13": "6.89"}), "2013-06-01", "2012", calls, 0)
    # the line + the call-record BOTH carry $/bu, sourced from rows[0]['unit'] (Q.run _apply_unit_overrides)
    assert "/bu" in lines[0] and calls[0]["rows"][0]["unit"] == "$/bu"
    # narrate_unit is NEVER set on the price synthesis (scale=1, no ratio trap)
    assert "narrate_unit" not in calls[0]["rows"][0] and "narrate_unit" not in calls[0].get("query", {})
    assert fired["unit"] == "$/bu"


def test_price_pair_unit_cotton_is_c_per_lb():
    n = _node("cotton", ["2010-09-15", "2010-11-01"])
    calls: list = []
    lines, _ = cq._price_pair({"focus_contract": "cotton"}, _sg([n]), None, [], _wasde_qfn(
        {"2009/10": "62.80", "2010/11": "81.50"}), "2012-06-01", "2010", calls, 0)
    assert "c/lb" in lines[0] and calls[0]["rows"][0]["unit"] == "c/lb"


def test_f6_regression_global_formatters_stay_unitless_no_fallback():
    """[SKEPTIC F6] the unit fallback is CONFINED to the two price-leg call sites -- _fmt_line/_delta_call were
    NOT globally edited to inherit the fetched unit. A narrate_unit-UNSET map row still renders UNITLESS there
    (the pre-seam behavior), so existing mapped refs are byte-unchanged."""
    rec = {"query": {"metric": "x"}, "rows": [{"value": "5.0", "unit": "$/bu"}]}   # fetched unit present
    row = {"metric": "x"}                                                          # narrate_unit UNSET
    dc = cq._delta_call(rec, row, 5.0, 3, kind="delta")
    assert dc["rows"][0]["unit"] == ""            # NO fallback to rec's fetched '$/bu' -- global fn untouched
    line = cq._fmt_line(rec, row, 3, era=0)
    assert "$/bu" not in line                     # the global renderer never inherits the fetched unit


# ── map coverage: NO leg -> honest decline ───────────────────────────────────────────────────────────────
def test_price_pair_no_map_declines_market_price_and_non_us():
    for slug in ("soybean_meal_cbot", "soybean_oil_cbot", "arabica_coffee", "cocoa", "french_wheat_matif"):
        n = _node(slug, ["2012-06-15", "2012-08-01"])
        lines, fired = cq._price_pair({"focus_contract": slug}, _sg([n]), None, [],
                                      _wasde_qfn({"2011/12": "1", "2012/13": "1"}), "2013-06-01", "2012", [], 0)
        assert lines == [] and fired is None, slug


def test_price_pair_no_focus_window_declines():
    # a focus with NO dated evidence yields no derived window -> honest decline
    n = _node("corn_cbot", [])
    lines, fired = cq._price_pair({"focus_contract": "corn_cbot"}, _sg([n]), None, [],
                                  _wasde_qfn({}), "2013-06-01", "2012", [], 0)
    assert lines == [] and fired is None


# ── pair-atomic: either endpoint not ok -> whole pair declines, no partial [N] minted ────────────────────
def test_price_pair_atomic_one_endpoint_missing_declines():
    n = _node("corn_cbot", ["2012-06-15", "2012-08-01"])
    calls: list = []
    lines, fired = cq._price_pair({"focus_contract": "corn_cbot"}, _sg([n]), None, [], _wasde_qfn(
        {"2011/12": "3.60"}), "2013-06-01", "2012", calls, 0)      # 2012/13 absent -> not ok
    assert lines == [] and fired is None
    assert calls == []                                            # no half-minted handle left behind


# ── PIT pin (load-bearing): SESSION asof -> settled ACTUAL; window-end asof -> then-current PROJECTION ────
def test_pit_price_leg_uses_session_asof_settled_actual():
    """One MY (corn 2012/13) with a late-release ACTUAL (~6.89) and an early-release PROJECTION (~5.40). The
    price leg MUST render the realized consequence (session asof -> actual), NOT the era-leg's window-end
    projection."""
    ACTUAL_RELEASE = "2013-02-01"

    def qfn(sql):
        my = _my_of(sql)
        if my not in ("2011/12", "2012/13"):
            return []
        asof = _asof_of(sql) or ""
        settled = asof >= ACTUAL_RELEASE                          # emulate the vintage collapse's role tiebreak
        if my == "2012/13":
            return [{"value": "6.89" if settled else "5.40"}]
        return [{"value": "6.22"}]

    n = _node("corn_cbot", ["2012-06-15", "2012-08-01"])
    # the leg runs at the SESSION asof -> settled 6.89
    calls: list = []
    lines, fired = cq._price_pair({"focus_contract": "corn_cbot"}, _sg([n]), None, [], qfn,
                                  "2013-06-01", "2012", calls, 0)
    assert fired["p_hi"] == 6.89 and any("$6.89/bu" in ln for ln in lines)
    # a window-end asof (the era-leg style) would have returned the then-current PROJECTION 5.40 -- proving the
    # session-asof choice is what surfaces the realized actual
    proj = cq.fetch_window(qfn, table="silver_wasde", metric="avg_farm_price", commodity="corn",
                           country="united_states", t1=None, t2=None, asof="2012-09-01", agg="latest",
                           period="2012/13", period_type="marketing_year")
    assert cq._float_val(proj) == 5.40


# ── quantify seam: flag-off byte-identity of existing rows + flag-on trace/block ─────────────────────────
def _mapped_corn():
    # a MAPPED corn export driver so quantify's `if not groups` early-return is not hit; the price focus rides
    # its _xc_focus_windows on the same grounded topology (Invariant-4 shared window).
    return _node("corn_cbot", ["2012-06-15", "2012-08-01"], ref="export")


def test_quantify_price_leg_off_leaves_existing_rows_byte_identical():
    """[byte-identity] flag OFF (price_request None) -> the EXISTING cascade rows (PSD legs + trace) are
    byte-identical; ON only APPENDS the price block + rows, never mutates a prior row."""
    qfn = _combined_qfn({"2011/12": "3.60", "2012/13": "6.89"})
    e_off: list = []
    b_off, t_off, r_off = cq.quantify(_sg([_mapped_corn()]), None, qfn=qfn, asof="2013-06-01", near="2012",
                                      extra_number_calls=e_off, price_request=None)
    e_on: list = []
    b_on, t_on, r_on = cq.quantify(_sg([_mapped_corn()]), None, qfn=qfn, asof="2013-06-01", near="2012",
                                   extra_number_calls=e_on, price_request={"focus_contract": "corn_cbot"})
    assert b_off and "PRICE-RESPONSE" not in b_off                # the pre-seam block has no price content
    assert t_off == t_on and r_off == r_on                        # existing cascade trace UNCHANGED
    assert e_on[: len(e_off)] == e_off                            # existing [N] rows unchanged, price APPENDED
    assert b_on.startswith(b_off) and "PRICE-RESPONSE" in b_on    # existing block is an unchanged prefix


def test_quantify_price_leg_on_writes_trace_and_block():
    qfn = _combined_qfn({"2011/12": "3.60", "2012/13": "6.89"})
    sg = _sg([_mapped_corn()])
    extra: list = []
    block, _t, _r = cq.quantify(sg, None, qfn=qfn, asof="2013-06-01", near="2012",
                                extra_number_calls=extra, price_request={"focus_contract": "corn_cbot"})
    assert block and "PRICE-RESPONSE on avg_farm_price:" in block
    assert sg.trace.get("quantify_price_leg", {}).get("price_leg") is True
    # the [N] rows were injected in place, continuing the count
    assert any(c["query"].get("table") == "silver_wasde" for c in extra)


def test_quantify_price_leg_non_farm_focus_writes_no_price_key():
    """A non-farm focus (coffee) declines at the map -> NO quantify_price_leg key, and the cascade itself is
    unaffected (the corn export block still renders)."""
    qfn = _combined_qfn({})
    sg = _sg([_mapped_corn()])
    block, _t, _r = cq.quantify(sg, None, qfn=qfn, asof="2013-06-01", near="2012",
                                extra_number_calls=[], price_request={"focus_contract": "arabica_coffee"})
    assert "quantify_price_leg" not in sg.trace and block and "PRICE-RESPONSE" not in block


# ── citation locator: table=silver_wasde + unit present (eval price_cited / unit_present filter) ──────────
def test_price_call_citation_carries_wasde_table_and_unit():
    call = cq._price_call("corn", "united_states", 6.89, "2012/13", "2013-06-01", unit="$/bu")
    c = ci.from_number(call, 4)
    assert c.locator.get("table") == "silver_wasde" and c.locator.get("metric") == "avg_farm_price"
    assert (c.unit or "").strip() == "$/bu"


# ── register surface (mirror test_reroute_v2_surface): past-tense dated factual passes; 'gap' landmine fails
def test_register_price_factual_passes_zero_fences():
    factual = ("US corn farm price rose from $3.60/bu [N1] to $6.89/bu [N2] through the 2012/13 drought; the "
               "settled season-average print confirmed the move.")
    assert reg.register_leaks(factual) == []


def test_register_gap_futurity_landmine_fails():
    landmine = "The old-crop/new-crop price gap should narrow into 2013 as the record catches up."
    hits = reg.register_leaks(landmine)
    assert hits and any("convergence" in tok for tok, _ctx in hits)   # (token, context) -- the LABEL is the token


def test_price_leg_leg_local_marker_is_not_a_fork_marker():
    n = _node("corn_cbot", ["2012-06-15", "2012-08-01"])
    calls: list = []
    lines, _ = cq._price_pair({"focus_contract": "corn_cbot"}, _sg([n]), None, [], _wasde_qfn(
        {"2011/12": "3.60", "2012/13": "6.89"}), "2013-06-01", "2012", calls, 0)
    body = "\n".join(lines)
    # the price leg is NOT a divergence / reroute / cross-commodity / co-move fork
    assert "DIVERGENCE" not in body and "REROUTE" not in body
    assert "CROSS-COMMODITY" not in body and "CO-MOVE" not in body


# ── flag helper + prompt clause + eval stat ──────────────────────────────────────────────────────────────
def test_price_leg_flag_helper_default_off_and_on(monkeypatch):
    monkeypatch.delenv("GRAPHRAG_CASCADE_PRICE_LEG", raising=False)
    assert an._price_leg_on() is False
    for v in ("on", "1", "TRUE", "True"):
        monkeypatch.setenv("GRAPHRAG_CASCADE_PRICE_LEG", v)
        assert an._price_leg_on() is True
    for v in ("off", "", "yes", "no"):
        monkeypatch.setenv("GRAPHRAG_CASCADE_PRICE_LEG", v)
        assert an._price_leg_on() is False


def test_system_cascade_price_response_clause_is_record_scoped(monkeypatch):
    s = an._SYSTEM_CASCADE
    assert "PRICE-RESPONSE" in s
    # rendered under '## The record', NOT any fork heading
    assert "put BOTH price LEVELS under '## The record'" in s
    # the hoisted price-level blessing now lives in the record section
    assert "observed price LEVELS arrive as [N] rows" in s
    assert "NEVER mint an uncited price figure" in s
    # render-gate + the no-fork backstop enumerates the price line
    assert "ONLY when a 'PRICE-RESPONSE' line is present" in s
    assert "NO PRICE-RESPONSE line" in s
    # still appended only under the quant flag
    monkeypatch.setenv("GRAPHRAG_MENTOR_VOICE", "on")
    monkeypatch.setenv("GRAPHRAG_CASCADE_QUANT", "on")
    assert "PRICE-RESPONSE" in an._system()
    monkeypatch.setenv("GRAPHRAG_CASCADE_QUANT", "off")
    assert "PRICE-RESPONSE" not in an._system()


def test_cascade_stats_price_leg_fired_boolean():
    base = {"trace": {"quantify": []}, "structured": {"tldr": "", "mechanism": ""}, "citations": []}
    assert ev._cascade_stats(base)["price_leg_fired"] is False
    fired = {**base, "trace": {"quantify": [], "quantify_price_leg": {"price_leg": True, "commodity": "corn"}}}
    assert ev._cascade_stats(fired)["price_leg_fired"] is True
    # never pollutes the rv2 / comove keys
    assert ev._cascade_stats(fired)["reroute_v2_pairs"] == 0 and ev._cascade_stats(fired)["comove_fired"] is False
