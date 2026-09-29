"""LANE AN -- FIX SITTING 3 (plan 09-27, CONTRACT Z11 / Z14 / Z17 / Z18 / Z19 / Z24): the watch nominator.

  U-6 / Z11  the nominator ranks by the CALL's own legs (``watch.call_legs``: the lead readings and question-seat
             chain links, plus the loudest reading on each settled side of an asked market, plus the netting
             facts' rows) and by the HORIZON's own clock (``watch.turns_inside`` / ``_row_clock``: the card's
             period against the horizon, and its next scheduled print); a STANDING row (its period longer than
             the horizon) never takes a ceiling slot; a CARRIED market's item is drawn only as a call leg and is
             counted (``carried_not_call``); the ruling's rank itself is untouched;
  M-1 / Z14  a declared phase pair's one-series item is minted on the pole IN FORCE (``watch.pole_row``) -- NEW5
             in test_state_board_producers turns green with its assertion unchanged;
  M-4 / Z17  a row held only as last revised backs no forward item (the current-state predicate) and is counted;
  V-3 / Z18  every nomination carries the counts its template FORMATTED (``formatted_counts``), read off the
             template's own slots;
  OI-8 / Z19 a release rule that is a window keeps both ends (``next_print_opens`` / ``next_print_closes``);
  OI-2 / Z24 the selection licence no longer teaches "nominated" / "cleared the bar".

THE FACTS these pins guard are the stamps and rows the writer reads; nothing here hands the writer a sentence (the
2N draw stays, the writer chooses and words the list). The harness boards are the estate's own offline scenarios
(``state/__main__.SCENARIOS``, the full walk); the constructed rows exist only where the banked corpus carries no
instance (a held-as-last-revised row, a carried market below the lead) and each says so.
"""
import copy

import pytest
from leviathan.graphrag.state import __main__ as H
from leviathan.graphrag.state import board as B
from leviathan.graphrag.state import feeders as F
from leviathan.graphrag.state import render as R
from leviathan.graphrag.state import watch as WA
from leviathan.graphrag.state.feeders import state_from_arrays
from leviathan.graphrag.state.lagbands import parse_lag

ASOF = "2026-09-07"
_MEMO: dict = {}


def _scenario(name):
    if name not in _MEMO:
        _MEMO[name] = H.build_scenario(name)
    return _MEMO[name]


def _months(n, start_year=2010, start_month=1):
    out, y, m = [], start_year, start_month
    for _ in range(n):
        last = [31, 29 if (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)) else 28,
                31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
        out.append(f"{y:04d}-{m:02d}-{last:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _decile_row(ref, *, table="silver_psd", driver_id="export_pace", contract="soybeans_cbot", cadence="monthly"):
    """A loud row whose reading sits in its own record's top decile, with NO convention (the floor's record_tail)."""
    vals = [float(i) for i in range(60)] + [500.0]
    st = state_from_arrays(ref, vals, _months(len(vals)), cadence=cadence, asof=ASOF, unit="1000 MT",
                           narrate_unit="1000 MT", windows={"monthly": 60, "annual": 60, "weekly": 60},
                           convention=None, table=table, metric="value")
    r = B.NodeRow(contract=contract, driver_id=driver_id, lag_band=parse_lag("1-2 quarters"), state=st,
                  receipts={"n": 0, "newest_date": None, "oldest_date": None, "top": []})
    r.legs["loud"] = True
    return r


def _board(rows, *, mode="deep", anchors=None, horizon=None):
    bd = B.Board(asof=ASOF, mode=mode, knobs=B.board_knobs_of(mode),
                 anchors=tuple(anchors or (B.Anchor(contract=rows[0].contract, source="named", named=True),)))
    bd.rows = list(rows)
    bd.order = tuple(r.key for r in rows)
    bd.horizon_months = horizon
    for r in rows:
        st = r.state
        bd.windows[r.key] = {"near": st.level_date, "reading": st.level_date, "state_date": st.level_date,
                             "knowledge_date": st.knowledge_date, "analog_dates": ()}
        bd.series[st.key.label()] = st
    return bd


def _drawn(rows):
    return [w for w in rows if w.get("slot") in ("ceiling", "nomination")]


# ═══ M-1 / Z14: the pole in force ═══════════════════════════════════════════════════════════════════════════
def test_M1_pole_row_rekeys_the_pole_NOT_in_force_onto_the_pole_in_force():
    """b40: ONI reads La Nina in force and IOD reads its positive pole in force (lane W's ``pole_in_force`` stamp on
    the fan entries); a row on the other pole of each pair is minted on the pole in force; every other row keeps
    its own key."""
    bd = _scenario("b40_event")["board"]
    palm = "malaysian_crude_palm_oil_cme"
    stamp = {e["driver_id"]: e.get("pole_in_force") for e in bd.fan if e["contract"] == palm}
    assert stamp.get("El_Nino") == "La_Nina" and stamp.get("IOD_negative") == "IOD_positive"
    assert WA.pole_row(bd, bd.row(palm, "El_Nino")) == (palm, "La_Nina")
    assert WA.pole_row(bd, bd.row(palm, "IOD_negative")) == (palm, "IOD_positive")
    for d in ("La_Nina", "IOD_positive", "ending_stocks", "drought"):
        assert WA.pole_row(bd, bd.row(palm, d)) == (palm, d)


def test_M1_the_re_key_needs_the_pole_row_LOUD_and_on_the_SAME_series():
    """The guards are facts: the in-force pole must be a rendered (loud) row, and on the same series and offset --
    two poles on two readings are two readings, and a pole with no line prints no handle to cite."""
    bd = copy.deepcopy(_scenario("b40_event")["board"])
    palm = "malaysian_crude_palm_oil_cme"
    el = bd.row(palm, "El_Nino")
    ln = bd.row(palm, "La_Nina")
    ln.legs["loud"] = False
    assert WA.pole_row(bd, el) == (palm, "El_Nino")
    ln.legs["loud"] = True
    assert ln.state is el.state                          # the harness reads both poles off ONE state object
    ln.state = copy.copy(el.state)
    ln.state.offset_months = int(getattr(el.state, "offset_months", 0) or 0) + 3
    assert WA._dedupe_key(ln) != WA._dedupe_key(el)
    assert WA.pole_row(bd, el) == (palm, "El_Nino")


def test_M1_no_drawn_phase_pole_item_sits_on_the_pole_not_in_force():
    """The pole census (sitting 2's ``pole_census.py``) over the three scenario boards: 0 wrong-pole items. On HEAD
    b40's ONI reach was drawn on the El Nino row under La Nina (1 of 7)."""
    wrong, seen = [], 0
    for name in H.SCENARIOS:
        ctx = _scenario(name)
        bd = ctx["board"]
        for w in WA.nonobvious_rows(bd, analogs=ctx["analogs"]):
            row = tuple(w.get("row") or ())
            if len(row) != 2:
                continue
            pf = R.phase_for_state(getattr(bd.row(*row), "state", None)) or {}
            if not pf.get("in_force") or row[1] not in (pf.get("driver"), pf.get("other_driver")):
                continue
            seen += 1
            if row[1] != pf.get("driver"):
                wrong.append((name, w.get("kind"), row))
    assert seen >= 5 and wrong == [], (seen, wrong)


def test_M1_the_reached_row_keeps_its_membership_refusal_and_its_rank_term():
    """NEW-5's ruling is untouched: the El Nino row's pattern MEMBERSHIP is refused and the rank term every pattern
    naming it earns is kept -- and the reach it produces is minted on La Nina's row, carrying that rank term."""
    ctx = _scenario("b40_event")
    bd = ctx["board"]
    palm = "malaysian_crude_palm_oil_cme"
    el = bd.row(palm, "El_Nino")
    pat = WA._pattern_facts(bd, el, list(bd.convergence), R.series_by_driver(bd))
    assert pat["member"] is False and pat["rank"] < WA.AMPLIFIER_LEVELS["neutral"]
    reach = [c for c in WA.nonobvious_candidates(bd, analogs=ctx["analogs"]) if c["kind"] == "spillover_reach"
             and c["row"] in ((palm, "El_Nino"), (palm, "La_Nina"))]
    assert reach and all(c["row"] == (palm, "La_Nina") for c in reach)
    assert pat["rank"] in {c["pattern"] for c in reach}
    assert all(c["label"].startswith("La Nina") for c in reach)


# ═══ U-6 / Z11: the call's legs and the horizon's clock ════════════════════════════════════════════════════
def test_Z11_call_legs_is_a_superset_of_call_rows_with_AT_MOST_ONE_row_per_settled_side():
    for name in H.SCENARIOS:
        bd = _scenario(name)["board"]
        rows, legs = WA.call_rows(bd), WA.call_legs(bd)
        assert rows <= legs, name
        extra = legs - rows
        for slug in bd.anchor_slugs:
            sides = [R.board_side(bd, bd.row(*k)) for k in extra if k[0] == slug and bd.row(*k) is not None]
            assert sides.count("for") <= 1 and sides.count("against") <= 1, (name, slug, sides)
            assert "unsettled" not in sides


def test_Z11_the_side_leg_is_the_LOUDEST_current_reading_of_that_side():
    bd = _scenario("soybeans_now")["board"]
    extra = WA.call_legs(bd) - WA.call_rows(bd)
    order = {k: i for i, k in enumerate(bd.order)}
    for k in extra:
        side = R.board_side(bd, bd.row(*k))
        earlier = [r for r in bd.rows if r.contract == k[0] and r.legs.get("loud") and WA._current(r.state)
                   and order.get(r.key, 1 << 20) < order[k] and R.board_side(bd, r) == side]
        assert earlier == [], (k, side, [r.key for r in earlier])


def test_Z11_every_candidate_is_stamped_BEFORE_the_draw_with_its_three_facts():
    ctx = _scenario("soybeans_now")
    bd = ctx["board"]
    legs = WA.call_legs(bd)
    for w in _drawn(WA.nonobvious_rows(bd, analogs=ctx["analogs"])):
        assert isinstance(w["call_leg"], bool) and isinstance(w["standing"], bool)
        assert w["turns_inside"] in (None, True, False)
        assert w["call_leg"] == (tuple(w["row"]) in legs)
        clk = WA._row_clock(bd, bd.row(*w["row"]).state)
        assert (w["turns_inside"], w["standing"]) == (clk["turns_inside"], clk["standing"])


def test_Z11_a_STANDING_row_never_takes_a_ceiling_slot_and_rides_the_tail_with_its_own_mark():
    """soybeans_now at a three-month horizon: HEAD seated an ANNUAL-period upstream item as core six of six (its
    cadence mark was stamped after the draw). It now sits in the tail, stamped standing, marked cadence."""
    ctx = _scenario("soybeans_now")
    bd = ctx["board"]
    assert bd.horizon_months == 3
    drawn = _drawn(WA.nonobvious_rows(bd, analogs=ctx["analogs"]))
    assert not [w for w in drawn if w["slot"] == "ceiling" and w["standing"]]
    tail_standing = [w for w in drawn if w["slot"] == "nomination" and w["standing"]]
    assert tail_standing and all(w["horizon_miss"] == "cadence" for w in tail_standing)
    assert ("upstream_convergence", ("soybeans_cbot", "psd_ending_stock_su_ratio")) in {
        (w["kind"], tuple(w["row"])) for w in tail_standing}


def test_Z11_the_CALL_pass_seats_call_legs_first_and_the_rank_fills_the_rest():
    for name in H.SCENARIOS:
        ctx = _scenario(name)
        core = [w for w in WA.nonobvious_rows(ctx["board"], analogs=ctx["analogs"]) if w.get("slot") == "ceiling"]
        flags = [bool(w.get("call_row")) for w in core]
        assert flags == sorted(flags, reverse=True), (name, flags)      # every call-pass row precedes the rest
        assert any(flags), name
        assert all(w["call_leg"] for w in core if w.get("call_row"))
        assert all(w["turns_inside"] is not False and not w["standing"] for w in core if w.get("call_row"))


def test_Z11_turns_inside_reads_the_PERIOD_and_the_PRINT_and_is_None_where_either_is_unknown():
    annual = _decile_row("psd_ending_stock_su_ratio", table="silver_psd", driver_id="ending_stocks", cadence="annual")
    weekly = _decile_row("esr_exports", table="silver_esr", driver_id="export_pace", cadence="weekly")
    daily = _decile_row("cbot_board_crush_margin", table="gold_board_crush", driver_id="board_crush", cadence="daily")
    oni = _decile_row("oni_climate", table="silver_noaa_oni", driver_id="El_Nino", cadence="monthly")
    nocal = _decile_row("mystery", table="silver_no_such_card", driver_id="mystery", cadence="monthly")
    bd = _board([annual, weekly, daily, oni, nocal], horizon=3)
    assert WA.turns_inside(bd, annual) is False                   # the period outruns the horizon
    assert WA._row_clock(bd, annual.state)["standing"] is True
    assert WA.turns_inside(bd, weekly) is True                    # a weekly print lands inside three months
    assert WA.turns_inside(bd, daily) is True                     # daily sessions print on the next session
    assert WA.turns_inside(bd, oni) is True                       # the monthly window opens inside it
    assert WA.turns_inside(bd, nocal) is None                     # no declared rule: unknown, never False
    bd.horizon_months = None
    for r in (annual, weekly, daily, oni, nocal):
        assert WA.turns_inside(bd, r) is None                     # no horizon asked: nothing to turn inside
        assert WA._row_clock(bd, r.state)["standing"] is False


def test_Z11_ONE_producer_the_post_draw_marks_agree_with_the_pre_draw_stamps():
    for name in H.SCENARIOS:
        ctx = _scenario(name)
        for w in _drawn(WA.nonobvious_rows(ctx["board"], analogs=ctx["analogs"])):
            assert (w.get("horizon_miss") == "cadence") == bool(w["standing"]), (name, w["kind"], w["row"])
            if w.get("horizon_miss") == "print":
                assert w["turns_inside"] is False
            if w["turns_inside"] is True:
                assert not w.get("horizon_miss")


def _carried_board(corn_first: bool):
    """CONSTRUCTED (the banked boards carry no carried market BELOW the lead on a harness board): four soybean
    decile readings and one corn reading, the corn board a subject-carried anchor the question did not name."""
    soy = [_decile_row(f"soy_ref_{i}", driver_id=f"soy_driver_{i}") for i in range(4)]
    corn = _decile_row("corn_ref", driver_id="corn_driver", contract="corn_cbot")
    rows = ([corn] + soy) if corn_first else (soy + [corn])
    anchors = (B.Anchor(contract="soybeans_cbot", source="named", named=True, distance=0),
               B.Anchor(contract="corn_cbot", source="subject", named=False, distance=1))
    return _board(rows, mode="max", anchors=anchors)


def test_Z11_a_CARRIED_market_item_is_drawn_only_as_a_call_leg_and_is_COUNTED():
    bd = _carried_board(corn_first=False)
    assert WA._carried_markets(bd) == frozenset({"corn_cbot"})
    rows = WA.nonobvious_rows(bd, analogs=())
    assert not [w for w in _drawn(rows) if w["row"][0] == "corn_cbot"]
    census = next(w["draw_census"] for w in rows if w.get("draw_census"))
    assert census == {"carried_not_call": 1}
    stamp = WA.watch_leg(bd, rows)
    assert stamp["outcome"] == "fired" and stamp["carried_not_call"] == 1
    # the same corn reading LEADING the page is one of the call's legs, and is drawn
    bd2 = _carried_board(corn_first=True)
    rows2 = WA.nonobvious_rows(bd2, analogs=())
    corn = [w for w in _drawn(rows2) if w["row"][0] == "corn_cbot"]
    assert corn and all(w["call_leg"] for w in corn)
    assert not any(w.get("draw_census") for w in rows2)


def test_Z11_a_named_or_distance_zero_market_is_never_carried():
    rows = [_decile_row("a_ref", driver_id="a", contract="soybeans_cbot")]
    for a in (B.Anchor(contract="soybeans_cbot", source="subject", named=True, distance=1),
              B.Anchor(contract="soybeans_cbot", source="subject", named=False, distance=0),
              B.Anchor(contract="soybeans_cbot", source="named", named=True, distance=None),
              B.Anchor(contract="soybeans_cbot", source="planner_inferred", named=False, distance=None)):
        assert WA._carried_markets(_board(rows, anchors=(a,))) == frozenset(), a


def test_Z11_the_partial_note_is_said_only_where_it_is_TRUE():
    """The caps' note says the alternates were held back by the caps; a standing alternate was held back by its
    period, and says so on its own line. soybeans_now's tail carries one, so neither note is added there; a
    board whose tail is all cap-held keeps the caps' note (test_state_watch's own pin) and an exhausted list keeps
    the exhausted note."""
    ctx = _scenario("soybeans_now")
    rows = WA.nonobvious_rows(ctx["board"], analogs=ctx["analogs"])
    assert any(w.get("standing") for w in rows if w.get("slot") == "nomination")
    assert not [w for w in rows if w.get("kind") in ("watch_core_capped", "watch_nothing_further")]


# ═══ M-4 / Z17: a row held only as last revised ════════════════════════════════════════════════════════════
def test_Z17_a_row_HELD_as_last_revised_backs_no_item_and_is_counted_on_the_leg():
    """CONSTRUCTED (no banked trace carries a retention stamp: the probe post-dates the fifty): the Y5 stamp
    ``recency['retention'] = {'state': 'held_as_last_revised'}`` on one of two decile readings."""
    held = _decile_row("held_ref", driver_id="held_driver")
    live = _decile_row("live_ref", driver_id="live_driver")
    held.state.recency = dict(held.state.recency or {}, **{F.RETENTION_KEY: {"state": "held_as_last_revised"}})
    assert F.held_as_last_revised(held.state) and not WA._current(held.state) and WA._current(live.state)
    bd = _board([held, live])
    assert not [c for c in WA.nonobvious_candidates(bd, analogs=()) if c["row"] == held.key]
    rows = WA.nonobvious_rows(bd, analogs=())
    assert [w["row"] for w in _drawn(rows)] == [live.key]
    assert WA.watch_leg(bd, rows)["held_as_last_revised"] == 1
    assert held.key not in WA.call_legs(bd) - WA.call_rows(bd)


# ═══ V-3 / Z18: the counts the template formatted ═════════════════════════════════════════════════════════
def test_Z18_every_formatted_count_is_PRINTED_on_its_line_beside_its_noun():
    n = 0
    for name in H.SCENARIOS:
        ctx = _scenario(name)
        for w in _drawn(WA.nonobvious_rows(ctx["board"], analogs=ctx["analogs"])):
            line = R.sb_watch(w).lower()
            for v, noun in w.get("formatted_counts") or ():
                n += 1
                assert R.words_for_int(int(v)) in line and noun.lower() in line, (name, w["kind"], v, noun)
    assert n >= 20


def test_Z18_a_slot_the_template_does_not_carry_is_never_declared_formatted():
    got = WA._slot_counts(WA.NONOBVIOUS_BODIES["convergence_amplified_alone"],
                          {"n_matched": (1, "drivers"), "n_declared": (3, "drivers"), "threshold": (2, "drivers")})
    assert got == ((3, "drivers"), (2, "drivers"))
    got = WA._slot_counts(WA.NONOBVIOUS_BODIES["spillover_reach_unplaced"],
                          {"n_far": (5, "other markets"), "n_same": (2, "markets"), "n_directed": (3, "markets")})
    assert got == ((5, "other markets"), (3, "markets"))


def test_Z18_HEADs_five_kinds_carry_no_formatted_counts():
    bd = _scenario("soybeans_now")["board"]
    for w in WA.watch_rows(bd, analogs=(), loud_k=16):
        assert "formatted_counts" not in w and "draw_census" not in w


# ═══ OI-8 / Z19: the next print as a window ═══════════════════════════════════════════════════════════════
def test_Z19_a_WINDOW_rule_keeps_both_ends_and_the_line_says_between():
    oni = _decile_row("oni_climate", table="silver_noaa_oni", driver_id="El_Nino")
    esr = _decile_row("esr_exports", table="silver_esr", driver_id="export_pace", cadence="weekly")
    bd = _board([oni, esr])
    cands = [{"row": oni.key, "kind": "tail_reading", "kind_words": "x", "label": "ONI", "what": "w", "dates": ""},
             {"row": esr.key, "kind": "tail_reading", "kind_words": "x", "label": "ESR", "what": "w", "dates": ""}]
    WA.stamp_release_clock(bd, cands)
    a, b = cands
    assert a["next_print"] == a["next_print_opens"] and a["next_print_closes"] > a["next_print_opens"]
    assert "; next print between %s and %s" % (a["next_print_opens"], a["next_print_closes"]) in R.sb_watch(a)
    assert b.get("next_print") and "next_print_opens" not in b and "next_print_closes" not in b


# ═══ OI-2 / Z24: the licence in the reader's words ════════════════════════════════════════════════════════
def test_Z24_the_selection_licence_no_longer_teaches_nominated_or_cleared_the_bar():
    from leviathan.graphrag import register as reg
    for form in (WA.WATCH_SELECTION_CLAUSE,) + tuple(WA.selection_clause(m) for m in WA.WATCH_NONOBVIOUS_K):
        low = form.lower()
        assert "nominat" not in low and "cleared the bar" not in low and "this page" not in low
        assert "core item" in low and "alternate" in low and "at most" in low
        assert "weighed and left and why" in low
        assert form.isascii() and reg.register_leaks(form) == [] and reg.desk_register_hits(form) == []


def test_the_new_trace_facts_never_reach_HEADs_flag_off_leg():
    bd = _scenario("el_nino_fanout")["board"]
    rows = WA.watch_rows(bd, analogs=(), loud_k=16)
    stamp = WA.watch_leg(bd, rows)
    assert set(stamp) == {"outcome", "reason", "reads"}


if __name__ == "__main__":                                  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
