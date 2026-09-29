"""FIX SITTING 2 (09-26), LANE H -- citations.py (the numbers ledger, the label corrections, the known stamp),
state/rows.py (the population field and words, the figure token's value path, the change unit) and verify.py
(the year-vs-quantity rule). CONTRACT Y8 / Y9 / Y22 / Y23 / Y24 / Y25; THREAT_MODEL sec 2 lane H.

Every expected string below is either HEAD's own byte (a pin that the flag-off path did not move) or the
contract's declared correction; the fixture board case replays the REAL fixture board's calls (the state harness,
no network) through the ledger rather than a case list written for the ledger."""
from __future__ import annotations

import copy
import types

import pytest
from leviathan.graphrag import citations as C
from leviathan.graphrag import verify as V
from leviathan.graphrag.state import rows as R


# ═══════════════════════════════════════ H-1 THE NUMBERS LEDGER (Y22) ═══════════════════════════════════════
def _oni(route: str, value=0.98, unit="degC", stat="level", kd="2026-08-31", **row):
    r = {"value": value, "unit": unit, "knowledge_date": kd, "stat": stat, "routing": route,
         "series_short": "the tropical Pacific sea-surface temperature anomaly", "commodity_words": ""}
    r.update(row)
    return {"query": {"table": "silver_noaa_oni", "metric": "oni_anom", "commodity": "_global", "country": None,
                      "period": "2026-08-31", "asof": "2026-09-07"},
            "rows": [r], "status": "ok", "_sb": True,
            "_row_id": f"corn_cbot|{route.replace(' ', '_')}|oni_climate|_global|", "shown": [value]}


def test_H1_one_series_read_for_two_drivers_takes_ONE_handle_and_keeps_both_routes():
    L = C.NumbersLedger(n_start=9)
    h1, r1 = L.address(_oni("El Nino"))
    h2, r2 = L.address(_oni("La Nina"))
    assert (h1, r1, h2, r2) == (9, False, 9, True)
    assert L.row_ids_for(9) == ("corn_cbot|El_Nino|oni_climate|_global|", "corn_cbot|La_Nina|oni_climate|_global|")
    assert L.stamp() == {"issued": 1, "reused": 1, "identity_value_conflict": 0}
    # the next NEW identity takes the next handle: the reused mint did not advance the count
    assert L.address(_oni("El Nino", value=1.2, unit="sigma", stat="sigma")) == (10, False)


@pytest.mark.parametrize("change", [
    {"window": {"from": "2016-08-31", "to": "2026-08-31"}},          # a percentile over another population
    {"offset_months": 6},                                              # a same-series offset reading
    {"_fold": {"axis": "destination", "rule": "sum", "n": 40}},        # a destination fold vs one buyer
    {"knowledge_date": "2026-09-05"},                                  # another vintage / knowledge stamp
    {"unit": "sigma"},                                                 # another unit
    {"stat": "window_peak_percentile"},                                # another statistic
    {"z_window": 120},                                                 # a z over another window
])
def test_H1a_two_rows_that_only_LOOK_identical_are_never_merged(change):
    L = C.NumbersLedger(n_start=1)
    a = _oni("El Nino")
    b = _oni("La Nina")
    b["rows"][0].update(change)
    assert L.address(a) == (1, False)
    assert L.address(b) == (2, False)
    assert L.stamp()["reused"] == 0


def test_H1b_H4b_a_restated_value_under_the_same_identity_is_a_counted_conflict_never_a_merge():
    L = C.NumbersLedger(n_start=1)
    assert L.address(_oni("El Nino", value=-0.668)) == (1, False)
    assert L.address(_oni("La Nina", value=1.526)) == (2, False)      # same identity, restated value
    assert L.address(_oni("El Nino", value=1.526)) == (2, True)       # the restated value's own handle, reused
    assert L.stamp() == {"issued": 2, "reused": 1, "identity_value_conflict": 1}


def test_H1_an_empty_or_blank_read_has_no_identity_and_always_takes_a_new_handle():
    L = C.NumbersLedger(n_start=1)
    empty = {"query": {"table": "silver_esr", "metric": "weekly_exports_1000mt"}, "rows": [], "status": "error"}
    blank = {"query": {"table": "silver_esr", "metric": "weekly_exports_1000mt"}, "rows": [{"value": None}],
             "status": "ok"}
    assert [L.address(c)[0] for c in (empty, empty, blank, blank)] == [1, 2, 3, 4]
    assert L.stamp()["reused"] == 0


def test_H1_the_seed_holds_the_seat_numbering_and_the_board_starts_after_it():
    seat = [{"query": {"table": "silver_icco_cocoa", "metric": "su_ratio", "commodity": None, "country": None,
                       "period": None, "asof": "2026-09-26"},
             "rows": [{"period": "2024/25", "value": "0.2852", "knowledge_date": "2026-05-29"}], "status": "ok"},
            {"query": {"table": "silver_esr", "metric": "weekly_exports_1000mt"}, "rows": [], "status": "error"}]
    L = C.NumbersLedger(seat, n_start=1)
    assert L.address(_oni("El Nino")) == (3, False)
    # the seat's own call shape, served again, is the seat's handle -- the value compared as a number
    again = copy.deepcopy(seat[0])
    again["rows"][0]["value"] = 0.2852
    assert L.address(again) == (1, True)


def test_H1_a_global_series_asked_for_by_two_anchors_is_one_identity():
    a = {"query": {"table": "silver_noaa_oni", "metric": "oni_anom", "commodity": "soybeans_cbot",
                   "country": "United States", "period": "2025-09-26..2026-09-26", "asof": "2026-09-26"},
         "rows": [{"value": 1.8, "unit": "degC", "year": 2026, "month": 7}], "status": "ok"}
    b = copy.deepcopy(a)
    b["query"].update(commodity="rough_rice_cbot", country="United States")
    L = C.NumbersLedger(n_start=1)
    assert L.identity(a) == L.identity(b)
    # ...while a series with a commodity axis keeps its commodity in its identity
    esr = {"query": {"table": "silver_esr", "metric": "weekly_exports_1000mt", "commodity": "corn_cbot",
                     "country": None, "period": None, "asof": "2026-09-26"},
           "rows": [{"value": 1900.047, "unit": "1000 MT"}], "status": "ok"}
    esr2 = copy.deepcopy(esr)
    esr2["query"]["commodity"] = "soybeans_cbot"
    assert L.identity(esr) != L.identity(esr2)


def test_H1_the_REAL_fixture_board_every_shared_handle_differs_only_in_its_route():
    """The drive, in the deck: the fixture palm board's own calls (the state harness, no network) replayed
    through a fresh ledger in mint order. Every group of calls the ledger puts under one handle differs ONLY in
    the declared route keys -- never in a period, a window, a stat, a unit, a stamp or a value -- and every call
    that takes a new handle differs from every earlier one in at least one of them (or in its value)."""
    from leviathan.graphrag import graph as G
    from leviathan.graphrag.state import __main__ as M
    from leviathan.graphrag.state import seam as S
    g = G.CausalGraph(G.load_contracts(), silver=set(), version="harness")
    slug = "malaysian_crude_palm_oil_cme"
    sg = types.SimpleNamespace(seeds=[slug], nodes=[], trace={})
    bd = S.fill_stage1(graph=g, sg=sg, asof=M.ASOF, mode="quick", query="where does palm oil stand now?",
                       state_fn=M.fixture_state_fn(M.ASOF), named=(slug,))
    S.fill_stage2(bd, graph=g, sg=sg, state_fn=M.fixture_state_fn(M.ASOF), state_chain=False)
    calls = list(bd.calls)
    assert calls
    L = C.NumbersLedger(n_start=1)
    by_handle: dict = {}
    for c in calls:
        h, _reused = L.address(c)
        by_handle.setdefault(h, []).append(c)

    def strip_route(c):
        c = copy.deepcopy(c)
        for k in C.NUMBERS_LEDGER_ROUTE_CALL_KEYS:
            c.pop(k, None)
        for r in c.get("rows") or []:
            for k in C.NUMBERS_LEDGER_ROUTE_ROW_KEYS:
                r.pop(k, None)
        return c

    for h, group in by_handle.items():
        base = strip_route(group[0])
        for other in group[1:]:
            assert strip_route(other) == base, h
    firsts = [strip_route(grp[0]) for grp in by_handle.values()]
    for i, a in enumerate(firsts):
        for b in firsts[i + 1:]:
            assert a != b
    st = L.stamp()
    assert st["issued"] == len(by_handle) and st["issued"] + st["reused"] == len(calls)


# ═════════════════════════════ H-2 THE FIGURE TOKEN'S SEPARATORS AND THE CHANGE UNIT (Y23) ═════════════════════
def test_H2_the_value_path_formats_the_figure_with_its_separator_and_nothing_else():
    assert R.figure_token("", value=241501, unit="contracts") == "241,501 contracts"
    assert R.figure_token("", value=5519.0, decimals=2, unit="USD/metric ton") == "5,519 USD/metric ton"
    assert R.figure_token("", value=1317.5, decimals=2, unit="US cents/bushel") == "1,317.5 US cents/bushel"
    # H2-a: periods, years and handles ride their own slots and are NEVER grouped
    tok = R.figure_token("", value=1900.047, unit="1000 MT", figure_basis="shipped in the week",
                         period_words="week to 17 September 2026")
    assert tok == "1,900 1000 MT shipped in the week, week to 17 September 2026"
    assert R.figure_token("", value=325, unit="Million Bushels", period_words="2025/26",
                          period_kind="marketing_year") == R.figure_token("325 Million Bushels", period_words="2025/26",
                                                                          period_kind="marketing_year")
    # a sub-thousand figure and a two-sided line guard are the one precision producer's, unchanged
    assert R.figure_token("", value=0.46, lines=(0.5,), two_sided=True, unit="degC") == "+0.46 degC"


def test_H2c_value_None_is_HEADs_token_byte_for_byte():
    for kw in ({}, {"unit": "%", "figure_basis": "of domestic use", "period_words": "2026/27",
                    "period_kind": "marketing_year"}, {"period_role": "the ICCO release of 29 May 2026"}):
        assert R.figure_token("10.72", **kw) == R.figure_token("10.72", value=None, **kw)


def test_H2b_the_verifier_reads_the_grouped_token_as_the_same_magnitude():
    spans = V._claim_number_spans("net long 241,501 contracts; December settled 5,519 USD/metric ton, -1,049 over "
                                  "sixty-three sessions")
    assert [v for _a, _b, v in spans] == [241501.0, 5519.0, 1049.0]
    # a grouped figure in the year range is a magnitude, never a year (rule (a) needs a bare 4-digit run)
    assert [v for _a, _b, v in V._claim_number_spans("shipments of 1,950 1000 MT")] == [1950.0]


def test_H2d_a_change_row_carries_its_level_units_and_a_rank_change_is_in_points():
    assert R.change_unit("USD/metric ton") == "USD/metric ton"
    assert R.change_unit("US cents/bushel") == "US cents/bushel"
    assert R.change_unit("percentile") == "points"
    assert R.change_unit("") == ""


# ═════════════════════════════════════ H-3 THE POPULATION (Y8) ═════════════════════════════════════════════════
BOOK = {"whole": "of its own record since {month}",
        "window": "of the window read since {month}",
        "contract_life": "of the {n_words} sessions this delivery has traded since {day}"}


def test_H3_the_words_name_the_population_the_rank_was_taken_over():
    tape = {"first": "2026-02-12", "last": "2026-09-23", "n": 158, "whole": False, "basis": "contract_life"}
    assert R.population_words(tape, book=BOOK) == ("of the one hundred fifty-eight sessions this delivery has "
                                                   "traded since 12 February 2026")
    oni = {"first": "2015-08-01", "last": "2026-07-01", "n": 131, "whole": False, "basis": "window"}
    assert R.population_words(oni, book=BOOK) == "of the window read since August 2015"
    whole = {"first": "1950-01-01", "last": "2026-07-01", "n": 919, "whole": True, "basis": "series"}
    assert R.population_words(whole, book=BOOK) == "of its own record since January 1950"


def test_H3_a_period_the_row_names_in_its_own_label_is_never_read_as_a_month():
    # a marketing-year token ("2008/09") is NOT an ISO date: month_words would read it as September 2008
    my = {"first": "2008/09", "last": "2024/25", "n": 15, "whole": False, "basis": "window"}
    assert R.population_words(my, book=BOOK) == "of the window read since 2008/09"
    # a contract's first SESSION must be a day; a month-precision first observation prints nothing
    assert R.population_words({"first": "2026-02", "basis": "contract_life", "n": 3}, book=BOOK) == ""


def test_H3_no_population_no_book_or_a_missing_fact_prints_nothing():
    assert R.population_words({}, book=BOOK) == ""
    assert R.population_words({"first": "2026-02-12", "basis": "contract_life"}, book={}) == ""
    # a template naming a fact the population does not carry prints NOTHING, never a hole
    assert R.population_words({"basis": "contract_life"}, book=BOOK) == ""


def test_H3_the_row_field_is_omitted_from_the_trace_when_empty():
    row = R.StateRow(key=R.SeriesKey(ref="oni_climate", commodity="_global"))
    assert "population" not in row.to_dict()
    row.population = {"first": "2015-08-01", "n": 131, "whole": False, "basis": "window"}
    assert row.to_dict()["population"]["n"] == 131


# ═══════════════════════════════ H-4 THE EPISODE WINDOW'S LABEL (the label half) ═══════════════════════════════
def test_H4a_an_episode_outcome_label_names_its_own_window_and_no_likeness():
    call = {"query": {"table": "silver_futures_eod", "metric": "settle_change_pct", "commodity": "soybeans_cbot",
                      "country": None, "period": "2021-10..2021-12", "asof": "2026-09-26",
                      "contract_month": "2022-01"},
            "rows": [{"value": 3.0297, "unit": "%", "knowledge_date": "2021-12-20", "contract_month": "2022-01",
                      "settle_kind": "exchange settlement", "currency": "USD"}], "status": "ok"}
    for c in (call, dict(call, display="analyst")):
        lab = C.from_number(c, 188).label
        assert "2021-10" in lab and "2021-12" in lab
        low = lab.lower()
        assert "like this" not in low and "episode" not in low
        # the stamp is the row's own session through the card's ONE derivation (data date + its lag): the
        # served tariff page's "[known 2021-12-21]" for the window ending on the 20 December session
        assert C.from_number(c, 188).date == "2021-12-21"


# ════════════════════════════════════ H-5 THE CONTROL'S LABEL DEFECTS (Y24) ════════════════════════════════════
ONI_CASCADE = {"query": {"table": "silver_noaa_oni", "metric": "oni_anom", "commodity": "soybeans_cbot",
                         "country": "United States", "period": "2025-09-26..2026-09-26", "asof": "2026-09-26"},
               "rows": [{"value": 1.8, "unit": "degC", "year": 2026, "month": 7}], "status": "ok"}


def test_PC8_a_global_series_carries_no_anchor_scope_in_its_label_or_identity():
    lab = C.from_number(ONI_CASCADE, 19).label
    assert lab == "NOAA ONI ONI anomaly 2025-09-26..2026-09-26 = 1.8 degC"
    brent = {"query": {"table": "silver_pink_sheet", "metric": "brent_crude_usd_bbl_zscore_5yr",
                       "commodity": "rough_rice_cbot", "country": None, "period": "2025-09-26..2026-09-26",
                       "asof": "2026-09-26"},
             "rows": [{"value": 0.5072943423080404, "unit": "z", "knowledge_date": "2026-08-01"}], "status": "ok"}
    assert C.from_number(brent, 21).label == ("World Bank Pink Sheet brent crude price 5-year z-score "
                                              "2025-09-26..2026-09-26 = 0.507294 z")
    ident = C.call_identity(ONI_CASCADE)
    assert ident["scope_words"] == "" and ident["commodity_words"] == "" and ident["short"] == "ONI anomaly"


def test_PC8_the_boards_own_global_token_and_a_card_with_a_country_axis_keep_HEADs_words():
    board = {"query": {"table": "silver_noaa_oni", "metric": "oni_anom", "commodity": "_global", "country": None,
                       "period": "2026-07", "asof": "2026-09-26"},
             "rows": [{"value": 1.8, "unit": "degC", "knowledge_date": "2026-09-05", "stat": "level"}],
             "status": "ok", "_sb": True}
    assert C.from_number(board, 9).label == "NOAA ONI ONI anomaly  global 2026-07 = 1.8 degC"
    psd = {"query": {"table": "silver_psd", "metric": "exports_mt", "commodity": "soybeans_cbot",
                     "country": "United States", "period": "2026", "asof": "2026-09-26"},
           "rows": [{"value": 45.0, "period": "2026", "knowledge_date": "2026-09-11"}], "status": "ok"}
    lab = C.from_number(psd, 3).label
    assert "CBOT soybeans" in lab and "United States" in lab


PACE = {"query": {"table": "silver_esr", "metric": "weekly_exports_1000mt_pace_change", "commodity": "soybeans_cbot",
                  "country": None, "period": "2026-07-18..2026-09-26", "asof": "2026-09-26"},
        "rows": [{"value": 164.219, "unit": "1000 MT", "knowledge_date": "20260924"}], "status": "ok"}


def test_PC7_no_declared_derivation_is_HEADs_label_byte_for_byte():
    assert C.from_number(PACE, 3).label == ("USDA FAS Export Sales (ESR) weekly_exports_1000mt_pace_change CBOT "
                                            "soybeans 2026-07-18..2026-09-26 = 164.219 1000 MT")


def test_PC7_a_declared_pace_row_is_named_by_its_derivation_never_its_slug_or_fetch_window():
    c = copy.deepcopy(PACE)
    c["query"]["derived"] = {"kind": "pace_change", "of": "weekly_exports_1000mt", "grain": "week"}
    for call in (c, dict(c, display="analyst")):
        lab = C.from_number(call, 3).label
        assert "pace_change" not in lab and "2026-07-18" not in lab
        assert lab.startswith("USDA FAS Export Sales (ESR) weekly exports CBOT soybeans change from the prior week")
    streak = {"query": {"table": "silver_noaa_oni", "metric": "oni_anom_pace_streak", "commodity": "soybeans_cbot",
                        "country": "United States", "period": "2026-02-18..2026-09-26", "asof": "2026-09-26",
                        "derived": {"kind": "pace_streak", "of": "oni_anom", "grain": "month"}},
              "rows": [{"value": 5, "unit": "months", "year": 2026, "month": 7}], "status": "ok"}
    assert C.from_number(streak, 22).label == ("NOAA ONI ONI anomaly consecutive months moving the same way, "
                                               "July 2026 = 5 months")
    assert C.call_identity(streak)["short"] == "ONI anomaly"
    assert C.call_identity(streak)["period_words"] == "July 2026"


def test_PC7_a_folded_national_row_names_the_fold_in_the_boards_words_and_its_own_week():
    fold = {"query": {"table": "silver_esr", "metric": "weekly_exports_1000mt", "commodity": "corn_cbot",
                      "country": None, "period": "2025", "asof": "2026-09-26"},
            "rows": [{"value": 775.39, "unit": "1000 MT", "week_ending_date": "2026-09-17",
                      "knowledge_date": "20260924", "_fold": {"axis": "destination", "rule": "sum", "n": 41}}],
            "status": "ok"}
    lab = C.from_number(fold, 16).label
    assert "summed over every destination" in lab and "2026-09-17" in lab
    unfolded = copy.deepcopy(fold)
    unfolded["rows"][0].pop("_fold")
    assert "summed over" not in C.from_number(unfolded, 16).label


def test_Y9_the_year_month_stamp_is_derived_under_the_analyst_stamp_and_HEADs_off_it():
    off = C.from_number(ONI_CASCADE, 19)
    on = C.from_number(dict(ONI_CASCADE, display="analyst"), 19)
    assert off.date == "2026-07"                               # HEAD's (PC-9 proposed, not confirmed)
    assert on.date == "2026-09-05"                             # month-end + the card's 36-day lag
    then = {"query": {"table": "silver_noaa_oni", "metric": "oni_anom", "commodity": "_global", "country": None,
                      "period": "2011-01-01..2011-04-01", "asof": "2026-09-26"},
            "rows": [{"value": -0.99, "year": 2011, "month": 1}, {"value": -0.68, "unit": "degC", "year": 2011,
                                                                  "month": 4}], "status": "ok"}
    t = C.from_number(dict(then, display="analyst"), 172)
    assert t.date == "2011-06-05" and "latest available" not in t.label   # never a new staleness claim


# ═══════════════════════════════════ H-6 THE YEAR-VS-QUANTITY RULE (Y25) ═══════════════════════════════════════
ESR_ROW = {"query": {"table": "silver_esr", "metric": "weekly_exports_1000mt", "commodity": "corn_cbot",
                     "country": None, "period": None, "asof": "2026-09-26"},
           "rows": [{"value": 1900.0469999999998, "unit": "1000 MT", "knowledge_date": "20260924",
                     "week_ending_date": "2026-09-17"}], "status": "ok"}


@pytest.mark.parametrize("fig,charged", [("1900", False), ("1950", True), ("2150", True)])
def test_H6_a_quantity_written_in_its_rows_declared_unit_words_is_checked(fig, charged):
    st = {"tldr": "", "mechanism": f"Weekly export shipments of {fig} thousand MT in the week to 17 September "
                                   f"2026 [N1].", "sources": []}
    rep = V.verify_citations(st, [], [copy.deepcopy(ESR_ROW)])
    assert bool((rep.get("by_rule") or {}).get("number_mismatch")) is charged


def test_H6a_a_true_year_beside_a_quantity_row_stays_a_year():
    g = V._unit_grammar((), ("contracts",))
    assert V._claim_number_spans("in 2021 lots of funds were long", units=g) == []
    g2 = V._unit_grammar((), ("1000 MT",))
    assert V._claim_number_spans("the 2021 harvest shipped early", units=g2) == []
    assert V._row_unit_spellings("MT") == [] and V._row_unit_spellings("1000 60-kg bags") == []
    assert ("thousand", "mt") in V._row_unit_spellings("1000 MT")


def test_H1c_the_verifier_reads_the_handles_identity_so_a_second_route_under_a_shared_handle_is_backed():
    """H1-c's verify.py reader: under one handle the calls list holds the FIRST route's call; the second route's
    line printed the same identity at the same value (the ledger's value fence), so every figure it printed is
    backed by the call at the handle -- and a figure the row does not carry is still charged."""
    call = _oni("El Nino")
    call["display"] = "analyst"
    scal = [{"value": 0.98, "unit": "degC", "kind": "level", "row_id": call["_row_id"], "handle": 1, "text": "0.98"},
            {"value": 0.98, "unit": "degC", "kind": "level", "row_id": "corn_cbot|La_Nina|oni_climate|_global|",
             "handle": 1, "text": "0.98"}]
    for sent, charged in (("The cool-phase reading sits at 0.98 degC [N1].", False),
                          ("The warm-phase reading sits at 0.98 degC [N1].", False),
                          ("The cool-phase reading sits at 1.5 degC [N1].", True)):
        st = {"tldr": "", "mechanism": sent, "sources": []}
        rep = V.verify_citations(st, [], [copy.deepcopy(call)], served_scalars=copy.deepcopy(scal))
        assert bool((rep.get("by_rule") or {}).get("number_mismatch")) is charged, sent
