"""FIX SITTING 4 (2026-09-29), LANE A -- answer.py + state/narration.py (CONTRACT C4-4 / C4-8 / C4-9 / C4-13 / C4-16 /
C4-17; THREAT_MODEL sec 4 LANE A).

Every item states the FACT the writer now sees and the CHECK that guards it; none hands the writer a sentence:
  * A4-1 THE STALE-DATE CLAUSE -- a row's SUPERSESSION (the release calendar's next print of its series on or before
    the as-of, or the board's `period_behind`) is the fact the charge reads; the clause sits right after that row's
    own handle, once per row, never a handle list, never a bare handle;
  * A4-2 THE ABSENCE APPEND -- the block's served absences are referents (a name the block serves as an absence names
    nothing, E11), and a served reading binds only by identity WITH scope;
  * A4-3 THE PUBLICATION NOTE -- `scheduled_prints` is a RULE, composed after the absence fact it scopes;
  * A4-4 THE MINORS -- `_fact_told` reads a figure whole; the call clause names each ASKED SIDES line's own label;
    the panel leg ships the book sentence's declaration, the ask being `facts_owed`'s;
  * A4-5 THE LEDGER on the board request;
  * V4-2 (A half) THE HANDLE'S CLAUSE read on both sides before a value splice; V4-6 built and UNWIRED;
  * R4-1 (A half) THE ROUTING LICENCE reads every name the page prints for the row.
The witnesses are the 63 banked pages' own sentences (fix_sitting_4_0929/verify/stale/witness_census.out); the
negative-corpus drives live in fix_sitting_4_0929/a_work/ (B23-S4, B48-S4, B64, B-R)."""
from __future__ import annotations

import datetime as _dt
import inspect
import types

from leviathan.graphrag import answer as an
from leviathan.graphrag.state import narration as N
from leviathan.graphrag.state import render as R

#: an injected release calendar (`calendar.next_release(..., doc=)`, the module's own injection discipline): the
#: WASDE window (9th-12th), MPOB's 10th, a Thursday weekly, a daily session card, and one uncalendared table
CAL = {"sources": {"usda": {"tables": ["silver_psd", "silver_wasde"],
                            "rule": {"kind": "monthly_window", "day_min": 9, "day_max": 12}},
                   "mpob": {"tables": ["silver_mpob"], "rule": {"kind": "monthly_window", "day_min": 10, "day_max": 10}},
                   "esr": {"tables": ["silver_esr"], "rule": {"kind": "weekly_dow", "dow": "THU"}},
                   "fut": {"tables": ["gold_board_crush"], "rule": {"kind": "daily_sessions"}}},
       "uncalendared": {"gold_weather_z": "a derived table"}}
D = _dt.date.fromisoformat


def _call(table, metric, commodity, country, period, value, unit, known, asof="2026-09-29"):
    return {"query": {"table": table, "metric": metric, "commodity": commodity, "country": country,
                      "period": period, "asof": asof},
            "rows": [{"value": value, "unit": unit, "knowledge_date": known}], "status": "ok"}


# ═══ A4-1 -- SUPERSESSION, NOT AGE; THE CLAUSE AFTER ITS OWN HANDLE ═════════════════════════════════════════════
def test_A41_the_charge_reads_the_rows_supersession_off_the_release_calendar():
    """The newest WASDE on the page (known 2026-09-11, the October print not out on 2026-09-29) is CURRENT -- the
    annual clock's "past zero" charged it at HEAD; the August print is superseded by September's. MPOB read on the
    13th is current until 10 October; one read on 1 August was superseded on 10 August. A daily session card read a
    month back is superseded; an uncalendared table is unknown (no charge)."""
    a = D("2026-09-29")
    assert an._seam_superseded({"table": "silver_psd", "known": "2026-09-11"}, a, calendar_doc=CAL) is False
    assert an._seam_superseded({"table": "silver_psd", "known": "2026-08-12"}, a, calendar_doc=CAL) is True
    assert an._seam_superseded({"table": "silver_mpob", "known": "2026-09-13"}, a, calendar_doc=CAL) is False
    assert an._seam_superseded({"table": "silver_mpob", "known": "2026-08-01"}, D("2026-09-23"), calendar_doc=CAL)
    assert an._seam_superseded({"table": "silver_esr", "known": "2026-09-24"}, a, calendar_doc=CAL) is False
    assert an._seam_superseded({"table": "silver_esr", "known": "2026-09-17"}, a, calendar_doc=CAL) is True
    assert an._seam_superseded({"table": "gold_board_crush", "known": "2026-08-21"}, a, calendar_doc=CAL) is True
    assert an._seam_superseded({"table": "gold_weather_z", "known": "2026-07-25"}, a, calendar_doc=CAL) is None
    assert an._seam_superseded({"table": "silver_nope", "known": "2026-07-25"}, a, calendar_doc=CAL) is None
    # the board's own `period_behind` stamp (a newer period held) is supersession without the calendar
    assert an._seam_superseded({"table": "gold_weather_z", "known": "2026-09-11"}, a, calendar_doc=CAL,
                               period_behind=True) is True


def test_A41_the_newest_print_is_never_dated_and_a_superseded_one_is_dated_after_its_own_handle():
    """The smoke corn/wheat sentence (witness A4-1): "(N14, N16 read 2026-09-11)" dated the newest WASDE area row
    with its handles named bare. Now: no clause for the current row; a superseded row's clause sits right after
    ITS handle, once per row (the level and the percentile of one series share the row), never a bare handle."""
    calls = [None] * 16
    calls[13] = _call("silver_psd", "area harvested", "srw wheat", "United States", "MY2026", 12.97, "M ha", "2026-09-11")
    calls[15] = _call("silver_psd", "area harvested", "srw wheat", "United States", "MY2026", 1, "percentile",
                      "2026-09-11")
    rows = an._seam_row_index(calls)
    s = ("Wheat's own sheet is loose on stocks but its area reading is the largest move on this board: 12.97 M ha "
         "[N14], 1st percentile [N16], falling two years.")
    d = {"tldr": "", "mechanism": s}
    cen = an._seam_stale_figures(d, rows, "2026-09-29", calendar_doc=CAL)
    assert d["mechanism"] == s and cen["stale_rows_dated"] == 0, cen
    # the SAME sentence on a row superseded by September's print
    for i in (13, 15):
        calls[i]["rows"][0]["knowledge_date"] = "2026-08-12"
    rows = an._seam_row_index(calls)
    d2 = {"tldr": "", "mechanism": s}
    cen2 = an._seam_stale_figures(d2, rows, "2026-09-29", calendar_doc=CAL)
    assert cen2["stale_rows_dated"] == 1 and cen2["stale_rows_superseded"] == 1, cen2   # one row, one clause
    assert "12.97 M ha [N14] (read 2026-08-12), 1st percentile [N16], falling two years." in d2["mechanism"]
    assert "(N14" not in d2["mechanism"] and ", N16" not in d2["mechanism"]


def test_A41_a_grouped_token_takes_one_clause_only_where_every_member_carries_it():
    calls = [None] * 3
    calls[0] = _call("silver_psd", "production", "palm oil", "Indonesia", "MY2026", 50, "MMT", "2026-08-12")
    calls[1] = _call("silver_psd", "production", "palm oil", "Malaysia", "MY2026", 20, "MMT", "2026-08-12")
    calls[2] = _call("silver_psd", "production", "palm oil", "Thailand", "MY2026", 3, "MMT", "2026-09-11")
    rows = an._seam_row_index(calls)
    d = {"tldr": "", "mechanism": "Output [N1, N2] is rising."}
    an._seam_stale_figures(d, rows, "2026-09-29", calendar_doc=CAL)
    assert d["mechanism"] == "Output [N1, N2] (read 2026-08-12) is rising."
    d2 = {"tldr": "", "mechanism": "Output [N1, N3] is rising."}          # N3 is current: the group is not dated
    c2 = an._seam_stale_figures(d2, rows, "2026-09-29", calendar_doc=CAL)
    assert d2["mechanism"] == "Output [N1, N3] is rising." and c2.get("stale_rows_grouped_withheld") == 1


def test_A41_the_seam_is_wired_with_the_rows_identity_and_the_board():
    src = inspect.getsource(an._writer_seam_lints)
    assert "_seam_stale_figures(structured, rows, asof, number_calls=number_calls, board=board)" in src


# ═══ A4-2 -- THE SERVED ABSENCES ARE REFERENTS; A SERVED READING BINDS WITH ITS SCOPE ══════════════════════════════
def _board_call(table, metric, commodity, country, value, unit, known, routing, row_id):
    c = _call(table, metric, commodity, country, "2026-08", value, unit, known)
    c["_row_id"], c["_sb"], c["routing"] = row_id, True, routing
    c["rows"] = [dict(c["rows"][0], routing=routing)]
    return c


def test_A42_the_smoke_max_claim_restates_the_patterns_own_unread_conditions():
    """Witness A4-2 (smoke run 1, max): "... with drought and heat stress carrying no series read on this turn" took
    "(a served reading bears on this: [N130] = 0.11 z ...)" -- ZCE meal's CANADA heat-stress row, bound by its
    routing phrase alone. The pattern's own unread conditions are served absences: TRUE, nothing appended."""
    hs = _board_call("gold_weather_z", "heat_stress_z", "rapeseed_meal_zce", "Canada", 0.11, "z", "2026-09-05",
                     "heat stress", "rapeseed_meal_zce|heat_stress|heat_stress_z|rapeseed_meal_zce|Canada")
    calls = [None] * 129 + [hs]
    rows = an._seam_row_index(calls)
    sent = ("the South American weather squeeze names five and one is counted here (the tight stocks-to-use "
            "ratio), with drought and heat stress carrying no series read on this turn.")
    conv = [{"contract": "soybeans_cbot", "name": "south_american_weather_squeeze",
             "matched_unmeasured": ("drought", "heat_stress")}]
    bd = types.SimpleNamespace(rows=[], chains=[], rendered_rows=(), convergence=conv, anchor_slugs=("soybeans_cbot",))
    d = {"tldr": "", "mechanism": sent}
    cen = an._seam_absence_claims(d, rows, number_calls=calls, board=bd, seat=True)
    assert d["mechanism"] == sent and cen.get("absence_rows_appended") == 0, cen
    assert cen.get("absence_claims_restating_served_absence") == 1, cen


def test_A42_a_served_reading_binds_only_with_its_scope_and_the_true_correction_keeps_its_append():
    """"The world ending-stocks read produced no rows" is never answered with Brazil's stocks (resmoke 0924, 2024;
    the replay's HEAD append); ROUND2 #10's own case -- "Argentine selling incentives ... have no series" beside the
    Argentina exports row the board ROUTED to that driver -- keeps its append (threat A42b-a)."""
    # the resmoke 0924 board, rebuilt from its own row state: Brazil's arabica-coffee stock row (the `stock` card,
    # read for "tenderable collapse") names "ending stocks" through its row identity -- HEAD appended it
    from leviathan.graphrag.state import feeders as F
    from leviathan.graphrag.state import rows as ROWS
    mrow = F.board_map().get("stock") or {}
    st = ROWS.StateRow(key=ROWS.SeriesKey(ref="stock", commodity="brazilian_arabica_coffee", country="Brazil",
                                          metric=""),
                       table=str(mrow.get("table") or ""), metric=str(mrow.get("metric") or ""), level_date="2022",
                       knowledge_date="2023-12-31", unit="MT")
    row = types.SimpleNamespace(contract="brazilian_arabica_coffee", driver_id="tenderable_collapse",
                                series_key="stock|brazilian_arabica_coffee|Brazil", state=st)
    bd0 = types.SimpleNamespace(rows=[row], chains=[], rendered_rows=(), convergence=[],
                                anchor_slugs=("soybeans_cbot",), row=lambda c, d: row)
    br = {"query": {"table": "silver_psd", "metric": "ending_stocks_mt", "commodity": "brazilian_arabica_coffee",
                    "country": "Brazil", "period": "2022", "asof": "2024-03-01"},
          "rows": [{"value": 0.2772, "unit": "MMT", "knowledge_date": "2023-12-31", "routing": "tenderable collapse"}],
          "status": "ok", "_row_id": "brazilian_arabica_coffee|tenderable_collapse|stock|brazilian_arabica_coffee|Brazil",
          "_sb": True, "routing": "tenderable collapse"}
    calls = [None] * 137 + [br]
    rows = an._seam_row_index(calls)
    s = "The world ending-stocks read produced no rows at all at this as-of."
    d = {"tldr": "", "mechanism": s}
    c0 = an._seam_absence_claims(d, rows, number_calls=calls, board=bd0, seat=True)
    assert d["mechanism"] == s and c0["absence_rows_appended"] == 0, c0
    # the same claim off the writer seam (seat=False: every other caller) keeps HEAD's binding byte for byte
    d0 = {"tldr": "", "mechanism": s}
    assert an._seam_absence_claims(d0, rows, number_calls=calls, board=bd0)["absence_rows_appended"] == 1
    bd = types.SimpleNamespace(rows=[], chains=[], rendered_rows=(), convergence=[], anchor_slugs=("soybeans_cbot",))
    ex = _board_call("silver_psd", "exports", "soybeans_cbot", "Argentina", 6.45, "MMT", "2026-09-11",
                     "Argentine selling incentives",
                     "soybeans_cbot|Argentine_selling_incentives|psd_exports|soybeans_cbot|AR")
    calls2 = [None] * 47 + [ex]
    rows2 = an._seam_row_index(calls2)
    sent = ("The model's price-pressuring supply-glut pattern needs three of its five drivers, and two of its legs "
            "(Argentine selling incentives, the dollar) have no series this page could read.")
    d2 = {"tldr": "", "mechanism": sent}
    c2 = an._seam_absence_claims(d2, rows2, number_calls=calls2, board=bd, seat=True)
    assert c2["absence_rows_appended"] == 1, c2
    assert "(a served reading bears on this: [N48]" in d2["mechanism"]
    # the tariff smoke page's shape (witness A4-2, run 2): "No series is served at the tariff link" took [N94],
    # Argentina's production -- whatever word bound it, the claim names neither Argentina nor that row's own routing
    # phrase, so no append (the worst case: a row routed by the one word "tariff")
    ar = _board_call("silver_psd", "production_mt", "soybeans_cbot", "Argentina", 0.5, "sigma", "2026-09-11",
                     "tariff", "soybeans_cbot|tariff|psd_production|soybeans_cbot|AR")
    calls3 = [None] * 93 + [ar]
    s3 = "No series is served at the tariff link, and the export book carries the rest."
    d3 = {"tldr": "", "mechanism": s3}
    c3 = an._seam_absence_claims(d3, an._seam_row_index(calls3), number_calls=calls3, board=bd, seat=True)
    assert d3["mechanism"] == s3 and c3["absence_rows_appended"] == 0, c3


# ═══ A4-3 -- THE PUBLICATION NOTE IS A RULE ═══════════════════════════════════════════════════════════════════
SCHEDULED_WORDS = ("The scheduled prints are not watch items here: {record} names them once, in its own dated note, "
                   "and they stay there.")


def test_A43_scheduled_prints_is_a_rule_its_words_unchanged():
    facts = {k for k, _h, _c in N.MANDATE_FACTS}
    rules = {k: c for k, _h, c in N.MANDATE_RULES}
    assert "scheduled_prints" not in facts and rules["scheduled_prints"] == SCHEDULED_WORDS
    assert N.MANDATE_RULES[-1][0] == "scheduled_prints"                   # appended, never sorted


def test_A43_the_rule_is_composed_after_the_absence_fact_it_scopes_never_under_close_with():
    m = N.state_board_mandate(nonobvious=True)
    rule = SCHEDULED_WORDS.format(record=N.MANDATE_BLOCK_SELF_NAME)
    assert m.count(rule) == 1 and N._CLAUSE["absence_reason"] + " " + rule in m
    assert rule not in N.MANDATE_WATCH_NONOBVIOUS
    for chain in (False, True):
        for desk in (False, True):
            mm = N.state_board_mandate(nonobvious=True, chain=chain, desk=desk)
            rec = N.MANDATE_BLOCK_READER_NAME if desk else N.MANDATE_BLOCK_SELF_NAME
            assert mm.count(SCHEDULED_WORDS.format(record=rec)) == 1
            assert "scheduled_prints" in N.mandate_asks({"m": mm})["rules"]
            assert "scheduled_prints" not in N.mandate_asks({"m": mm})["facts"]
    # the watch flag OFF: HEAD's literal, the rule nowhere (the ban it protects exists only on the lit draw)
    assert N.state_board_mandate() is N.SYSTEM_STATE_BOARD_MANDATE and rule not in N.SYSTEM_STATE_BOARD_MANDATE
    assert N.check_literals() == []


# ═══ A4-4 -- THE MINORS ═════════════════════════════════════════════════════════════════════════════════════
def test_A44_fact_told_reads_a_figure_whole():
    """Sitting 3's minor: "250 1000 MT" was told by "1,250 1000 MT" and "2.6 USD/bu" by "-2.6 USD/bu"."""
    assert not an._fact_told("weekly sales rose 1,250 1000 MT", names=("250 1000 MT",))
    assert an._fact_told("weekly sales rose 1,250 1000 MT", names=("1,250 1000 MT",))
    assert not an._fact_told("the margin fell to -2.6 USD/bu", names=("2.6 USD/bu",))
    assert an._fact_told("the margin fell to -2.6 USD/bu", names=("-2.6 USD/bu",))
    assert an._fact_told("the margin is +2.6 USD/bu", names=("2.6 USD/bu",))
    assert an._fact_told("a 2024-2.6 USD/bu range", names=("2.6 USD/bu",))          # a range dash is no sign
    assert an._fact_told("stocks at 0.117 S/U ratio in May", names=("0.117 S/U ratio",))
    assert not an._fact_told("stocks at 0.1175 S/U ratio in May", names=("0.117 S/U ratio",))
    # a name that opens on no figure keeps the matcher's reading (N-L1's hyphen joint)
    assert an._fact_told("through rubber area substitution", names=("Rubber-Area Substitution",))


def _sides_block(pairs):
    lines, pool = [], []
    for i, (f, a) in enumerate(pairs):
        b = R.Block(start=20 + 10 * i)
        clause = R.sb_ask_sides({"for": f, "against": a, "unsettled": 0}, {"front": True}, block=b)
        lines.append("- [N%d] CBOT market %d, the nearest listed delivery, November 2026, settle on 2026-09-16: 1,021 "
                     "US cents/bushel; %s" % (20 + 10 * i, i, clause))
        pool += [dict(sc, cls="SB-T") for sc in b._pending]
    return "\n".join(lines), pool


def test_A44_each_asked_sides_line_is_named_under_its_own_label():
    """A two-market board whose lines disagree (one leans 3-1, one is level 1-1) -- measured on 4 of 4 multi-market
    fixture boards (a_work/b50s4_netting.out): the lean clause over the leaning line, the balanced clause over the
    level one, each with the parts ITS line printed; one label -> HEAD's single clause byte for byte."""
    block, pool = _sides_block([(3, 1), (1, 1)])
    recs = an._ask_sides_line_records(block, pool, {})
    assert [(h, b) for h, b, _n in recs] == [(("[N20]",), False), (("[N30]",), True)]
    clause = N.ask_call_mandate(("[N20]", "[N30]"), balanced=False, lines=recs)
    assert clause == (N.ask_call_mandate(("[N20]",)) + " " + N.ask_call_mandate(("[N30]",), balanced=True))
    one, pool1 = _sides_block([(3, 1), (4, 1)])
    assert an._ask_sides_line_records(one, pool1, {}) == ()
    assert N.ask_call_mandate(("[N20]",), lines=()) == N.ask_call_mandate(("[N20]",))
    net = {"opposing": ("[N5]", "[N44]")}
    recs2 = ((("[N21]", "[N5]"), False, {"opposing": ("[N5]",)}), (("[N40]", "[N44]"), True, {"opposing": ("[N44]",)}))
    got = N.ask_call_mandate(("[N21]", "[N5]", "[N40]", "[N44]"), netting=net, lines=recs2)
    assert "the reading set against that lean ([N5])" in got and "the reading leading each side ([N44])" in got
    # threaded through `_system` on its own TAIL kwarg; absent -> HEAD's bytes
    p = list(inspect.signature(an._system).parameters)
    assert p[-2:] == ["ask_netting", "ask_sides_lines"]
    assert an._system(state_board=True, ask_sides=("[N20]",), ask_sides_lines=()) == \
        an._system(state_board=True, ask_sides=("[N20]",))
    assert clause in an._system(state_board=True, ask_sides=("[N20]", "[N30]"), ask_sides_balanced=False,
                                ask_sides_lines=recs)


def test_A44_the_panel_leg_is_the_books_declaration_and_the_ask_is_facts_owed():
    book = str(R.book_words("panel_words", "mandate") or "")
    leg = N.panel_mandate()
    if ": " in book:
        assert leg == book.split(": ", 1)[0].rstrip(" ,;") + "."
        assert "or say in one clause why one is not used" not in leg
    else:
        assert leg == book
    legs = dict(an._mandate_parts(state_board=True))
    assert legs.get("panel", "").strip() == leg
    assert N._CLAUSE["facts_owed"] in legs["state_board_mandate"]
    assert an._mandate_census(list(legs.items()))["undeclared_words"] == 0


# ═══ A4-5 -- THE NUMBERS LEDGER RIDES THE BOARD REQUEST ═════════════════════════════════════════════════════════
def test_A45_the_ledger_rides_the_board_request_outside_the_g1x_block():
    src = inspect.getsource(an._answer_l2)
    i = src.index("_board_req = dict(_board_req, display=_DISPLAY_ANALYST)")
    j = src.index("_board_req = dict(_board_req, numbers_ledger=_nledger)")
    assert i < j < src.index("_sb_kw = {\"board\": _board_req} if _board_req else {}")
    assert "if _nledger is not None:" in src[i:j]
    q = src.index("_cblock, _quant_trace, _reroute_trace = cq.quantify(")
    assert "numbers_ledger" not in src[q:src.index("sg.trace[\"ms_quantify\"]", q)]


# ═══ V4-2 (the A half) -- THE HANDLE'S CLAUSE, BOTH SIDES; V4-6 UNWIRED ═════════════════════════════════════════
def _pct(v):
    return _call("gold_board_crush", "crush_margin_usd_bu_pct", "soybeans_cbot", None, None, v, "percentile",
                 "2024-02-29", asof="2024-03-01")


V42 = ("- **Crush** [N31] 0.81 USD/bu on 29 February 2024, [N33] 11th percentile since March 2019, after bottoming at "
       "[N34] the 3rd percentile in February 2024 -- weak, but turning up over the last session.")
V42B = ("- **The chains.** From the crush margin to ICE canola: margin at [N33] the 11th percentile, into the "
        "stocks-to-use ratio at [N92] the 31st, into the fund position at [N24] the 0th;")


def test_V42_a_figure_the_clause_already_states_on_either_side_is_never_spliced_again():
    """Witness V4-2 (smoke run 1, 2024): "after bottoming at 3 percentile [N34] the 3rd percentile" -- four such
    splices on the page ([N34] [N33] [N92] [N24]); B64: exactly those four withheld on the 63, 0 other change."""
    calls = [None] * 92
    calls[30] = _call("gold_board_crush", "crush_margin_usd_bu", "soybeans_cbot", None, None, 0.81, "USD/bu",
                      "2024-02-29", asof="2024-03-01")
    for i, v in ((33, 11), (34, 3), (92, 31), (24, 0)):
        calls[i - 1] = _pct(v)
    for text in (V42, V42B):
        d = {"tldr": "", "mechanism": text}
        cen = an._resolve_number_handles(d, calls, clause_figures=True)
        assert d["mechanism"] == text, d["mechanism"]
        assert cen["clause_figure_stated"] >= 1 and cen["substituted"] == 0
        # flag-off: HEAD's splice, byte for byte (the kwarg is absent off the board)
        d0 = {"tldr": "", "mechanism": text}
        c0 = an._resolve_number_handles(d0, calls)
        assert c0["substituted"] >= 1 and "clause_figure_stated" not in c0
    # ANOTHER row's figure in the clause never counts (threat A42-a): [N34] at 3 beside a different row's 11
    d = {"tldr": "", "mechanism": "after bottoming at [N34] beside the 11th percentile of the crush."}
    an._resolve_number_handles(d, calls, clause_figures=True)
    assert "at 3 percentile [N34]" in d["mechanism"]


def test_V46_the_figureless_splice_is_built_and_unwired():
    """The contract's V4-6 rule fired 393 times on 50 of the 53 board pages of the 63 (a_work/b64_compare_r1.out),
    most of them false -- so it is UNWIRED (`figureless_splice`, passed by no call site); its producer stands and
    prints a change row WITH its measure words exactly as the block line printed them."""
    src = inspect.getsource(an._answer_l2)
    assert '_cf_kw = {"clause_figures": True} if _wseam_on else {}' in src
    assert '"figureless_splice"' not in src and "figureless_splice=" not in src          # no call site passes it
    tape = _call("silver_futures_eod", "settle change over 63 sessions", "soft_red_winter_wheat_cbot", None, None,
                 83.0, "US cents/bushel", "2026-09-25")
    calls = [None] * 72 + [tape]
    pool = [{"kind": "window_change", "handle": 73, "text": "+83", "unit": "US cents/bushel", "row_id": "w"},
            {"kind": "window_length", "handle": None, "text": "sixty-three", "unit": "sessions", "row_id": "w"}]
    block = "- [N72] CBOT srw wheat settle: 707 US cents/bushel; [N73] +83 US cents/bushel over sixty-three sessions on the same contract"
    s = "wheat's leans two up, seven down beside [N73] and a collapsed harvested area."
    d = {"tldr": "", "mechanism": s}
    an._resolve_number_handles(d, calls, clause_figures=True, served_scalars=pool, block=block)
    assert d["mechanism"] == s                                            # unwired: nothing spliced
    d2 = {"tldr": "", "mechanism": s}
    c2 = an._resolve_number_handles(d2, calls, clause_figures=True, figureless_splice=True, served_scalars=pool,
                                    block=block)
    assert "beside +83 US cents/bushel over sixty-three sessions [N73]" in d2["mechanism"], d2["mechanism"]
    assert c2["handle_no_figure_spliced"] == 1
    # a change row with no registered measure is LEFT and counted, never printed as a level (threat A46-a)
    d3 = {"tldr": "", "mechanism": s}
    c3 = an._resolve_number_handles(d3, calls, clause_figures=True, figureless_splice=True, served_scalars=pool[:1],
                                    block=block)
    assert d3["mechanism"] == s and c3["handle_no_figure_kept"] == 1


# ═══ R4-1 (the A half) -- THE ROUTING LICENCE READS EVERY PRINTED NAME ═══════════════════════════════════════════
def test_R41_a_routing_word_the_footer_prints_for_the_row_names_the_row():
    """"the high-confidence drought reading [N24]" was "corrected" to the block's long name in apposition while the
    footer prints the row as "GOLD WEATHER Z drought z-score ...": the routing word is a word the page prints for the
    row, so it is never replaced. "India export ban" over "exports for India" is still corrected (AR-a)."""
    call = _call("gold_weather_z", "drought_z", "malaysian_crude_palm_oil_cme", "SE Asia Palm Belt", "2026-08", 1.25,
                 "z", "2026-09-25")
    idn = {"short": "the longest dry-day run in the month, as a z-score", "name": "the longest dry-day run in the month",
           "routing_words": "drought"}
    assert "drought z-score" in an._nbl_printed_names(idn, call)
    sent = "the high-confidence drought reading [N24] points the other way."
    assert not [e for e in an._nbl_name_edits(sent, (0, 36), idn, call) if e[3] == "routing_corrected"]
    ex = _call("silver_psd", "exports", "rice", "India", "MY2026", 22.5, "MMT", "2026-09-11")
    idn2 = {"short": "exports for India", "name": "exports for India", "routing_words": "India export ban"}
    s2 = "The India export ban reading sits at 22.5 MMT [N70]."
    got = [e for e in an._nbl_name_edits(s2, (0, 32), idn2, ex) if e[3] == "routing_corrected"]
    assert got and got[0][2] == "exports for India", got
