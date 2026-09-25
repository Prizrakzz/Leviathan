"""THE CITATION LABEL READS THE CARD AND THE ROW (09-23 fix round, lane C; CONTRACT C3 / C5 / C10 / C11).

Every test here is a label the 2026-09-23 re-smoke served FALSE (grades/fact/*.md), rebuilt as a fixture
call off the banked served row, and the corrected label. The card fields lane T declares (C10) are
injected through `citations._card_fields` -- the ONE accessor this module reads them by -- so the deck
pins the rule both before and after T lands; the fallbacks (the registry's own `period_type`, the
knowledge semantics, `destination_coded()`) are pinned with NOTHING injected.
"""
from __future__ import annotations

import pytest

from leviathan.graphrag import citations as cit

_ASOF = "2026-09-23"


def _call(table, metric, rows, *, commodity=None, country=None, period=None, sb=False, asof=_ASOF, **extra):
    c = {"query": {"table": table, "metric": metric, "commodity": commodity, "country": country,
                   "period": period, "asof": asof}, "rows": rows, "status": "ok"}
    if sb:
        c["_sb"] = True
    c.update(extra)
    return c


def _head(label: str) -> str:
    """`answer._seam_row_index`'s join key: the label minus its value clause."""
    return label.rpartition(" = ")[0].strip()


@pytest.fixture
def cards(monkeypatch):
    """Inject C10 fields: ``cards({table: {...}, (table, metric): {...}})``."""
    def _set(spec: dict):
        def _cf(t, m):
            out = dict(spec.get(str(t), {}))
            out.update(spec.get((str(t), str(m)), {}))
            return out
        monkeypatch.setattr(cit, "_card_fields", _cf)
    return _set


# ── DEFECT 4: THE MY PREFIX ONLY ON A MARKETING YEAR ───────────────────────────────────────────────────
@pytest.mark.parametrize("table,metric,period,sb,want", [
    ("silver_noaa_oni", "oni_anom", "2026-07", True, " 2026-07 = "),             # a month (board)
    ("silver_cot", "mm_net", "2026-09-15", True, " 2026-09-15 = "),              # a report week (board)
    ("silver_esr", "weekly_exports_1000mt", "2026-09-10", True, " 2026-09-10 = "),  # an ESR week (board)
    ("silver_mpob", "closing_stocks_palm_oil_mt", "2026-08-01", True, " 2026-08-01 = "),
    ("silver_pink_sheet", "brent_crude_usd_bbl_zscore_5yr", "2026-08-01", True, " 2026-08-01 = "),
    ("gold_board_crush", "crush_margin_usd_bu", "2026-08-20", True, " 2026-08-20 = "),
    ("gold_weather_z", "drought_z", "2026-07", True, " 2026-07 = "),
    ("silver_futures_eod", "settle", "2026-12", False, " 2026-12 = "),           # a delivery month (seat)
    ("silver_psd", "su_ratio", "2026", True, " MY2026 = "),                      # a marketing year (board)
    ("silver_wasde", "ending_stocks", "2025/26", True, " MY2025/26 = "),
    ("silver_psd", "production_mt", "2026", False, " MY2026 = "),                # a marketing year (seat)
    ("silver_esr", "outstanding_sales_1000mt", "2025", False, " MY2025 = "),     # the ESR marketing year
])
@pytest.mark.parametrize("declared", ["live_registry", "nothing_declared"])
def test_the_MY_prefix_rides_ONLY_a_marketing_year(table, metric, period, sb, want, declared, cards):
    """Every 09-23 page printed "MY2026-07" / "MY2026-09-15" / "MY2026-12". The prefix is now the card's
    claim: a marketing-year PERIOD COLUMN keeps it; a date, a week, a month, a delivery month never gets
    it. Pinned twice: on the live registry (lane T's `period_words`) and with NOTHING declared, where the
    fallback is the registry's own period_type and the axis the board reads -- the two must agree."""
    if declared == "nothing_declared":
        cards({})
    c = cit.from_number(_call(table, metric, [{"value": "1.5", "knowledge_date": "2026-09-11"}],
                              commodity="soybeans_cbot", period=period, sb=sb), 1)
    assert want in c.label, c.label
    assert "MYMY" not in c.label


def test_a_prelabelled_or_windowed_period_is_untouched_and_an_unknown_card_keeps_HEADs_rule():
    for per in ("MY2011", "2010-06-01..2010-09-01"):
        c = cit.from_number(_call("silver_psd", "su_ratio", [{"value": "0.1"}], period=per), 1)
        assert f" {per} = " in c.label
    c = cit.from_number(_call("silver_not_a_card", "x", [{"value": "1"}], period="2026-07"), 1)
    assert " MY2026-07 = " in c.label, "a card this module cannot resolve is HEAD's rule, byte for byte"
    assert cit._period_label("2026-07") == "MY2026-07" == cit._period_label("2026-07", None)


def test_the_ICCO_SEASON_is_named_when_the_query_names_no_period(cards):
    """cocoa F1: the headline ICCO row (2024/25, read 2026-05-29) was served with NO period at all. The
    headline row's own period now rides the label, as the season the card declares it to be."""
    row = {"value": "0.28522", "knowledge_date": "2026-05-29", "period": "2024/25"}
    cards({})
    base = cit.from_number(_call("silver_icco_cocoa", "su_ratio", [row], commodity="cocoa"), 1)
    assert " MY2024/25 = " in base.label, "before lane T: the registry's own marketing-year period type"
    cards({"silver_icco_cocoa": {"period_words": "crop_season"}})
    c = cit.from_number(_call("silver_icco_cocoa", "su_ratio", [row], commodity="cocoa"), 1)
    assert " 2024/25 season = " in c.label, c.label


# ── DEFECT 5: THE KNOWN DATE OF A DATA-DATE CARD ───────────────────────────────────────────────────────
@pytest.mark.parametrize("table,metric,observed,known", [
    ("silver_mpob", "closing_stocks_palm_oil_mt", "2026-08-01", "2026-09-13"),   # 43-day lag
    ("silver_pink_sheet", "soybeans_usd_mt", "2026-08-01", "2026-09-10"),        # 40-day lag
    ("silver_cot", "mm_net", "2026-09-15", "2026-09-21"),                        # 6-day lag
])
def test_a_DATA_DATE_cards_known_stamp_is_the_boards_one_derivation(table, metric, observed, known):
    """palm_rapeoil F2 / soyoil_palm L3: "known 2026-08-01" for August MPOB stocks, which MPOB prints
    around 10 September. The stamp is `feeders.derive_knowledge_date` -- the SAME derivation the board's
    own row prints -- and the observation's date rides the label as its period instead."""
    c = cit.from_number(_call(table, metric, [{"value": "2824488.0", "knowledge_date": observed}],
                              commodity="malaysian_crude_palm_oil_cme"), 1)
    assert c.date == known, (c.date, c.label)
    assert f" {observed} = " in c.label, c.label
    assert "latest available" not in c.label


def test_a_BOARD_call_vintage_and_year_month_stamps_are_untouched():
    """The board's call already carries the derived date (no second lag); a vintage card's stamp is the
    served vintage; a year_month card keeps its month identity (CYCLE-5 VINTAGE-1)."""
    sb = cit.from_number(_call("silver_mpob", "closing_stocks_palm_oil_mt",
                               [{"value": "1", "knowledge_date": "2026-09-13"}], period="2026-08-01", sb=True), 1)
    assert sb.date == "2026-09-13"
    v = cit.from_number(_call("silver_psd", "su_ratio", [{"value": "0.1", "knowledge_date": "2026-09-11"}],
                              period="2026"), 1)
    assert v.date == "2026-09-11"
    ym = cit.from_number(_call("silver_noaa_oni", "oni_anom", [{"value": "1.8", "year": 2026, "month": 7}]), 1)
    assert ym.date == "2026-07"


# ── DEFECT 3: BASIS / AXIS / OFFSET / STAT ─────────────────────────────────────────────────────────────
def test_the_BASIS_rides_every_stat_of_the_row_with_ONE_head(cards):
    """Six pages printed "stocks-to-use 10.72 %" with no word that the denominator is DOMESTIC use. The
    card's basis rides the metric name on the level AND the percentile alike, so the head the writer
    seam pairs them on (C-6) stays one spelling."""
    cards({("silver_psd", "su_ratio"): {"basis_words": "ending stocks as a share of domestic use"}})
    q = dict(commodity="soybeans_cbot", country="United States", period="2026", sb=True)
    lvl = cit.from_number(_call("silver_psd", "su_ratio", [{"value": 10.72, "unit": "%"}], **q), 36)
    pct = cit.from_number(_call("silver_psd", "su_ratio", [{"value": 23, "unit": "percentile"}], **q), 38)
    assert "stocks-to-use ratio (ending stocks as a share of domestic use)" in lvl.label
    assert _head(lvl.label) == _head(pct.label)
    # the board's own C3 `basis` wins over the card, and a seat call without either is HEAD's name
    own = cit.from_number(_call("silver_psd", "su_ratio", [{"value": 10.72, "unit": "%", "basis": "B"}], **q), 1)
    assert "stocks-to-use ratio (B)" in own.label


def test_a_DESTINATION_row_says_to_whom(cards):
    """deep26 F3: {"period": "2026", "value": "0.0", "country": "Nicaragua"} under an unscoped ESR read
    was footered "outstanding sales CBOT soybeans MY2025 = 0 1000 MT" -- one destination served as the
    national figure. The row IS one destination's; the label says so, in the flow's direction."""
    row = {"value": "0.0", "knowledge_date": "20260917", "period": "2026", "country": "Nicaragua"}
    c = cit.from_number(_call("silver_esr", "outstanding_sales_1000mt", [row], commodity="soybeans_cbot",
                              period="2025"), 14)
    assert " to Nicaragua MY2025 = " in c.label, c.label
    scoped = cit.from_number(_call("silver_esr", "outstanding_sales_1000mt", [row], commodity="soybeans_cbot",
                                   country="China", period="2025"), 14)
    assert "to Nicaragua" not in scoped.label and " China MY2025 = " in scoped.label
    national = dict(row)
    national.pop("country")
    assert " to " not in cit.from_number(_call("silver_esr", "outstanding_sales_1000mt", [national],
                                               commodity="soybeans_cbot", period="2025"), 1).label


def test_a_destination_word_never_rides_a_WITHHELD_multi_scope_line(monkeypatch):
    monkeypatch.setenv("GRAPHRAG_SCOPE_WITHHOLD", "on")
    rows = [{"value": "1", "country": "Mexico", "period": "2026"}, {"value": "2", "country": "China", "period": "2026"}]
    c = cit.from_number(_call("silver_esr", "outstanding_sales_1000mt", rows, commodity="soybeans_cbot",
                              period="2025"), 1)
    assert cit._SCOPE_WITHHOLD_MARK in c.label and " to " not in _head(c.label)


def test_a_REGION_CELL_cross_section_is_labelled_one_regional_reading_not_the_country(cards):
    """deep26 F1 (FATAL): gold_weather_z drought reads of "United States" served 10 rows per month (ten
    growing-region surfaces) and footered ONE of them as "United States". The card declares a region axis
    with NO national row; a read whose rows share the headline's month is a CROSS-SECTION, and the label
    says the figure is one of several regional readings. A lone row per period (a basin / member-country
    aggregate is one row too -- the cocoa tail-share row) and an aggregate read are left as they are."""
    rows = [{"value": str(v), "year": y, "month": m, "unit": "z"}
            for (y, m) in ((2026, 6), (2026, 7)) for v in (2.24909, 1.1, -0.4, -1.7)]
    cards({})
    head_before = cit.from_number(_call("gold_weather_z", "drought_z", rows, commodity="soybeans_cbot",
                                        country="United States", period="2025-09-23..2026-09-23"), 76).label
    cards({"gold_weather_z": {"country_axis": "region_cell", "axis_national": "none"}})
    c = cit.from_number(_call("gold_weather_z", "drought_z", rows, commodity="soybeans_cbot",
                              country="United States", period="2025-09-23..2026-09-23"), 76)
    assert " United States, one of several regional readings 2025-09-23..2026-09-23 = " in c.label, c.label
    assert "regional readings" not in head_before
    # 09-23 FIX ROUND (review VC M4): a LONE row of this card is still ONE REGION'S reading -- the card
    # declares no national row -- so deep26's N13 (a LIMIT-1 read over ten cells) is never "United States"
    # alone; and a metric the card declares AGGREGATE-grain (`row_grain: aggregate`, the basin / member
    # tail shares) keeps its surface's name with no regional words, because its row IS the surface
    cards({"gold_weather_z": {"country_axis": "region_cell", "axis_national": "none"},
           ("gold_weather_z", "tmax_anomaly_tail_share"): {"row_grain": "aggregate"}})
    one = cit.from_number(_call("gold_weather_z", "drought_z", [{"value": "-1.19263", "unit": "z"}],
                                commodity="soybeans_cbot", country="United States"), 13)
    assert " United States, one regional reading = " in one.label, one.label
    lone = cit.from_number(_call("gold_weather_z", "tmax_anomaly_tail_share",
                                 [{"value": "0", "year": 2026, "month": 8}], commodity="cocoa",
                                 country="West Africa"), 60)
    assert "regional" not in lone.label, "an aggregate-grain metric's row is its surface: no cell words"
    agg = _call("gold_weather_z", "drought_z", rows, commodity="soybeans_cbot", country="United States")
    agg["query"]["agg"] = "mean"
    assert "regional" not in cit.from_number(agg, 1).label


def test_the_board_calls_own_AXIS_SCOPE_wins():
    rows = [{"value": -1.19, "unit": "z", "axis_scope": "one United States growing cell"}]
    c = cit.from_number(_call("gold_weather_z", "drought_z", rows, commodity="soybeans_cbot",
                              country="United States", period="2026-07", sb=True), 1)
    assert " one United States growing cell 2026-07 = " in c.label, c.label


def test_an_OFFSET_row_names_its_lag_and_never_says_latest_available():
    """soyoil_palm L2: "NOAA ONI ... MY2026-01 = -0.39 degC (latest available 2026-03-08; as-of 2026-09-23)"
    -- a six-month DECLARED EFFECT LAG sold as data latency. Every stat of the row carries the words."""
    q = dict(commodity="_global", period="2026-01", sb=True)
    lvl = cit.from_number(_call("silver_noaa_oni", "oni_anom",
                                [{"value": -0.39, "unit": "degC", "knowledge_date": "2026-03-08",
                                  "offset_months": 6}], **q), 54)
    pct = cit.from_number(_call("silver_noaa_oni", "oni_anom",
                                [{"value": 35, "unit": "percentile", "knowledge_date": "2026-03-08",
                                  "offset_months": 6}], **q), 56)
    assert "read 6 months back by this market's declared lag" in lvl.label
    assert "latest available" not in lvl.label and "latest available" not in pct.label
    assert _head(lvl.label) == _head(pct.label)
    plain = cit.from_number(_call("silver_noaa_oni", "oni_anom",
                                  [{"value": -0.39, "unit": "degC", "knowledge_date": "2026-03-08"}], **q), 1)
    assert "latest available 2026-03-08" in plain.label, "an unapplied offset prints no offset words (C-10)"


@pytest.mark.parametrize("value,side", [(99, "highest"), (3, "lowest")])
def test_a_WINDOW_PEAK_percentile_is_its_own_statistic(value, side):
    """C3 `stat: window_peak_percentile`: the peak inside the lag window is a different figure from the
    row's current rank, so it carries its window and does NOT share the current percentile's head."""
    q = dict(commodity="soybeans_cbot", country="United States", period="2026-07", sb=True)
    peak = cit.from_number(_call("gold_weather_z", "drought_z",
                                 [{"value": value, "unit": "percentile", "stat": "window_peak_percentile",
                                   "window": {"from": "2026-01", "to": "2026-07"}}], **q), 1)
    cur = cit.from_number(_call("gold_weather_z", "drought_z", [{"value": 72, "unit": "percentile"}], **q), 2)
    assert f"{side} reading inside 2026-01..2026-07" in peak.label
    assert _head(peak.label) != _head(cur.label)


# ── DEFECT 7: ANALYST PRECISION RIDES THE DISPLAY STAMP ONLY ───────────────────────────────────────────
def test_ANALYST_precision_only_on_a_display_stamped_call_and_off_is_HEAD():
    """D2: "0.583039", "2.35294", "0.0604982" in the reader's footer. With lane A's `display: analyst`
    stamp (board flag on) the headline figure prints through `render.shown_figure`; without it the label
    is `_fmt`'s, byte for byte (OWNER DECISION 10)."""
    from leviathan.graphrag.state import render as R
    if getattr(R, "shown_figure", None) is None:
        pytest.skip("lane R's render.shown_figure (CONTRACT C5) not landed on this tree")
    rows = [{"value": "0.583039", "knowledge_date": "2026-09-11", "unit": "ratio"}]
    base = _call("silver_psd", "su_ratio", rows, commodity="malaysian_crude_palm_oil_cme",
                 country="Malaysia", period="2025")
    off = cit.from_number(base, 7)
    on = cit.from_number(dict(base, display="analyst"), 7)
    assert " = 0.583039 ratio" in off.label
    # RE-BANKED 09-24 (fix round 2, CONTRACT K7, OWNER DECISION O-1 (b) -- a declared DM1 move, the analyst
    # stamp exists only under GRAPHRAG_STATE_BOARD): a LEVEL in the card's native unit is re-stated in the
    # card's DISPLAY spec (x100, "%", 2 decimals), so this row can no longer print "0.58 ratio" beside the
    # board's "58.3 %" for the same series; the K2 token carries the period at the card's precision.
    assert " = 58.3 %" in on.label and " ratio" not in on.label.split(" = ", 1)[1], on.label
    assert on.value == off.value == "0.583039", "the value the verifier reads never moves"
    assert on.unit == off.unit == "ratio", "nor the unit a stand-in splice reads (value and unit stay a pair)"
    assert _head(on.label) == _head(off.label)
    big = _call("silver_mpob", "closing_stocks_palm_oil_mt", [{"value": "2824488.0", "knowledge_date": "2026-08-01"}])
    assert " = 2,824,488 " in cit.from_number(dict(big, display="analyst"), 1).label


def test_analyst_precision_REFUSES_a_figure_its_row_cannot_back(monkeypatch):
    """C-9, RE-BANKED 09-24 (fix round 2, CONTRACT K7 / THREAT C-5): the backing guard now holds the text to
    the row's value TIMES THE SCALE THE CARD DECLARES. A producer that returns the card's own re-statement
    (0.1072 x 100 = "10.72") is ACCEPTED -- that is K7 -- and one that returns ANY other figure (a wrong
    scale, a re-signed value) is refused and the label keeps HEAD's figure in the row's own unit."""
    from leviathan.graphrag.state import render as R
    mk = lambda: _call("silver_psd", "su_ratio", [{"value": "0.1072", "unit": "ratio"}], period="2026",
                       display="analyst")
    monkeypatch.setattr(R, "shown_figure", lambda v, **k: "10.72", raising=False)
    assert " = 10.72 %" in cit.from_number(mk(), 1).label
    for wrong in ("1.072", "107.2", "-10.72", "0.11"):
        monkeypatch.setattr(R, "shown_figure", lambda v, _w=wrong, **k: _w, raising=False)
        c = cit.from_number(mk(), 1)
        assert " = 0.1072 ratio" in c.label, (wrong, c.label)


# ── C-1 / C-2: NO ROLE OR STAMP WORD IS INVENTED OR LOST BY THE LABEL ──────────────────────────────────
def test_the_label_adds_no_role_word_off_flag_and_the_roster_is_the_board_roster():
    """GRAPHRAG_VINTAGE_ROLE semantics are untouched (DECISION 6): off-flag, no role word is added; the
    board admits roles through `_role_display`, the roster pinned equal to `rows.VINTAGE_ROLES` in the
    feeder deck."""
    row = {"value": "12.65", "knowledge_date": "2024-02-08", "period": "2023/24", "revision_stamp": "projection"}
    c = cit.from_number(_call("silver_wasde", "avg_farm_price", [row], commodity="soybeans", country="united_states",
                              period="2023/24", asof="2024-03-01"), 63)
    assert "USDA projection" not in c.label
    assert cit._role_display({"revision_stamp": "2026M09"}) == ""


def test_analyst_precision_never_lends_the_LEVELS_card_to_another_statistic():
    """FOUND BY THE BOARD DRIVE, not by a case written for it: on the palm ONI row the card's degC El Nino
    lines and two-sided sign were handed to the PERCENTILE call and printed "+78 percentile". The card's
    display spec describes the card metric's level in its own display unit; a z, a percentile, or the level
    in another unit is asked without the card."""
    from leviathan.graphrag.state import render as R
    if getattr(R, "shown_figure", None) is None:
        pytest.skip("lane R's render.shown_figure (CONTRACT C5) not landed on this tree")
    q = dict(commodity="_global", period="2026-07", sb=True, display="analyst")
    pct = cit.from_number(_call("silver_noaa_oni", "oni_anom", [{"value": 78, "unit": "percentile"}], **q), 1)
    sig = cit.from_number(_call("silver_noaa_oni", "oni_anom", [{"value": 0.9, "unit": "sigma"}], **q), 2)
    assert " = 78 percentile" in pct.label and "+78" not in pct.label, pct.label
    assert " = 0.9 sigma" in sig.label, sig.label


def test_a_BOARD_call_never_borrows_cell_words_the_board_did_not_mint(cards):
    """REFUTED ON THE ARTEFACT, not on a case written for it: the as-of-2024 page's [N38] is a BOARD drought
    row, and the board collapses a region-cell card by MEAN across its cells -- "one region cell" there
    would be the R-2 failure ("one cell" on a mean). A board call's scope words are its identity's
    (`axis_scope`) or nothing."""
    cards({"gold_weather_z": {"country_axis": "region_cell", "axis_national": "none"}})
    rows = [{"value": -0.673533, "unit": "z", "knowledge_date": "2024-02-25"}]
    c = cit.from_number(_call("gold_weather_z", "drought_z", rows, commodity="soybeans_cbot",
                              country="United States", period="2024-01", sb=True, asof="2024-03-01"), 38)
    assert "region" not in c.label and " United States 2024-01 = " in c.label, c.label


def test_a_row_that_CARRIES_its_region_is_named_by_it(cards):
    """The brief's own words: "the row's own axis value when the card's country_axis is destination /
    region_cell and the row carries one". The read does not surface the region column today (a lane-T
    request); the day it does, the surface is named -- never guessed before."""
    cards({"gold_weather_z": {"country_axis": "region_cell", "axis_national": "none"}})
    c = cit.from_number(_call("gold_weather_z", "drought_z",
                              [{"value": "-1.2", "year": 2026, "month": 7, "region": "Corn Belt"}],
                              commodity="soybeans_cbot", country="United States"), 13)
    assert " United States, Corn Belt 2026-07 = " in c.label, c.label


def test_fix_0923_M3b_a_card_less_pair_level_row_reads_its_period_kind_off_its_two_legs_cards():
    """09-23 FIX ROUND, review WT M-3 (b): the minted pair-spread LEVEL has no card of its own, and HEAD's
    rule labelled its Pink Sheet month "MY2026-08-01" -- a marketing year it is not. The row's period is
    an observation date on its two legs' cards (`leg_a` / `leg_b`); both read it as a MONTH, so the label
    prints the month's own token and the writer seam's month clock keys on it. Built by the REAL minting
    producer (`agent.rv_pair_spread_legs`, the level-only rung)."""
    from leviathan.graphrag.numbers import agent as A
    palm = [1050.0, 1062.0, 1071.0, 1088.0, 1094.0, 1101.0, 1110.0, 1117.0]
    soy = [1480.0, 1502.0, 1533.0, 1561.0, 1580.0, 1601.0, 1620.0, 1638.0]

    def _leg(metric, vals):
        dates = [f"2026-{m:02d}-01" for m in range(1, len(vals) + 1)]
        return {"query": {"table": "silver_pink_sheet", "metric": metric}, "status": "ok",
                "rows": [{"value": v, "unit": "USD/mt", "data_date": d, "knowledge_date": d}
                         for v, d in zip(vals, dates)]}
    lvl, why = A.rv_pair_spread_legs(("soybean_oil_cbot", "malaysian_crude_palm_oil_cme"),
                                     [_leg("palm_oil_cpo_usd_t", palm), _leg("soybean_oil_usd_t", soy)],
                                     level_only=True)
    assert why is None and len(lvl) == 1
    assert cit.printed_period(lvl[0]) == ("2026-08-01", "month")
    label = cit.from_number(lvl[0], 1).label
    assert " 2026-08-01 = 521 USD/mt" in label and "MY2026" not in label, label


# ── 09-24 (fix round FINAL_2; the orchestrator's ruling 6, Option 2, on R-2) ────────────────────────────
@pytest.mark.parametrize("period", ["2026-08-27", "MY2026-08-27", "20260827", "2026-W35-4"])
@pytest.mark.parametrize("declared", ["live_registry", "nothing_declared"])
def test_fix_0924_R2_a_DATE_in_a_marketing_year_column_is_a_date_and_never_prints_MY(period, declared, cards):
    """R-2: `silver_esr` declares its period COLUMN a marketing year, and a NON-board call whose period
    value IS a calendar date -- an ISO date, the source's undashed stamp or an ISO week date, bare or
    carrying HEAD's printed "MY" -- is dated AS A DATE: the value's TYPE (the date type's own parser) is
    read before the column's kind. Its kind is the card's declared observation grain ("week"; "day"
    where the card declares none), the label prints the date and never "MY2026-08-27", and the writer
    seam dates the twelve-day-old week on the 21-day clock, never the annual one (window zero)."""
    if declared == "nothing_declared":
        cards({})
    c = _call("silver_esr", "weekly_exports_1000mt",
              [{"value": "311.846", "unit": "1000 MT", "knowledge_date": "20260904"}],
              commodity="soybeans_cbot", period=period)
    assert cit.printed_period(c) == (period, "week" if declared == "live_registry" else "day")
    label = cit.from_number(c, 1).label
    assert f" {period.removeprefix('MY')} = " in label and "MY20" not in label, label
    from leviathan.graphrag import answer as an
    d = {"tldr": "", "mechanism": "Shipments [N1] falling on the week"}
    assert an._seam_stale_figures(d, an._seam_row_index([c]), "2026-09-16")["stale_rows_dated"] == 0


def test_fix_0924_R2_a_YEAR_LABEL_in_the_same_column_keeps_its_marketing_year_and_HEADs_rule_stands():
    """The other side of R-2: the type read can only ever move a value that IS a date. A year label in
    the same marketing-year column keeps its kind and its prefix, a card this module cannot resolve keeps
    HEAD's rule byte for byte even for a date, and no year label ever parses as a date."""
    for per, want in (("2027", " MY2027 = "), ("MY2026", " MY2026 = "), ("2026/27", " MY2026/27 = ")):
        c = _call("silver_esr", "outstanding_sales_1000mt", [{"value": "45", "knowledge_date": "2026-09-11"}],
                  commodity="soybeans_cbot", period=per)
        assert cit.printed_period(c) == (per, "marketing_year")
        assert want in cit.from_number(c, 1).label
    c = cit.from_number(_call("silver_not_a_card", "x", [{"value": "1"}], period="2026-08-27"), 1)
    assert " MY2026-08-27 = " in c.label, "a card this module cannot resolve is HEAD's rule, byte for byte"
    for tok in ("2026", "MY2026", "2026/27", "MY2024/25", "2026-07", "MY2026-07", "", None):
        assert cit._date_value(tok) is None, tok


# ── 09-24 (VERIFY_FINAL MAJOR-1): THE ROW'S OWN PERIOD -- a knowledge stamp is never a period, and a date whose
# kind nothing resolves is a date, never a marketing year ───────────────────────────────────────────────────
@pytest.mark.parametrize("table,metric,kd,sb", [
    ("compute_stat", "window_change", "2026-09-22", False),      # no card: a stat of a stat / a leg handle
    ("compute_stat", "window_change", "20260917", False),        # ...the source's undashed stamp
    ("silver_not_a_card", "x", "2026-09-22", False),             # a card this module cannot resolve
    ("silver_psd", "production_mt", "2026-09-11", False),        # VINTAGE: the alias is the release date
    ("silver_production", "production", "2026-08-26", False),    # INGEST: the alias is the ingest date
    ("silver_mpob", "closing_stocks_palm_oil_mt", "2026-09-13", True),   # a BOARD row: the DERIVED known date
])
def test_fix_0924_MAJOR1_a_KNOWLEDGE_STAMP_on_the_row_prints_no_period(table, metric, kd, sb):
    """MAJOR-1: when the query names no period the label prints the HEADLINE ROW's own (`feeders.row_period`),
    and a row whose only date is its KNOWLEDGE alias handed that stamp over as the period -- "computed
    statistic change over the window MY2026-09-22" through the real numbers agent, flag-off, both cells. The
    alias is a period only where the CARD says it carries the observation (`knowledge_semantics: data_date`,
    `citations._observation_card`); everywhere else -- no card, an unresolvable card, a vintage or ingest
    card, a board row's derived stamp -- it is a knowledge stamp: NO period (HEAD's bytes), and the stamp
    still rides the [known ...] slot."""
    c = _call(table, metric, [{"value": "3", "knowledge_date": kd}], sb=sb)
    assert cit.printed_period(c) == ("", None)
    label = cit.from_number(c, 1).label
    assert kd not in label and "MY" not in label, label
    assert "  = 3" in label, label                                 # the empty period slot, as HEAD printed it
    assert cit.from_number(c, 1).date == kd


@pytest.mark.parametrize("table,metric,kd,want,kind,known", [
    ("silver_mpob", "closing_stocks_palm_oil_mt", "2026-08-01", " 2026-08-01 = ", "month", "2026-09-13"),
    ("silver_cot", "mm_net", "2026-09-15", " 2026-09-15 = ", "week", "2026-09-21"),
])
def test_fix_0924_MAJOR1_a_DATA_DATE_cards_knowledge_alias_IS_its_observation_and_keeps_its_period(
        table, metric, kd, want, kind, known):
    """The other side: on a data-date card the knowledge alias IS the date column (`knowledge_date_col ==
    date_col` on every such card), so the D3 row-own period stands -- the MPOB month, the COT report week --
    and [known ...] is the board's one derivation (data date + the card's publication lag)."""
    c = _call(table, metric, [{"value": "3", "knowledge_date": kd}])
    assert cit.printed_period(c) == (kd, kind)
    x = cit.from_number(c, 1)
    assert want in x.label and "MY" not in x.label, x.label
    assert x.date == known


@pytest.mark.parametrize("table,row,tok,kind", [
    ("compute_stat", {"period": "2026-09-17"}, "2026-09-17", "day"),
    ("compute_stat", {"period": "20260917"}, "20260917", "day"),
    ("compute_stat", {"data_date": "2026-09-17"}, "2026-09-17", "day"),
    ("compute_stat", {"year": 2026, "month": 7}, "2026-07", "month"),
    ("silver_not_a_card", {"period": "2026-08-27"}, "2026-08-27", "day"),
])
def test_fix_0924_MAJOR1_a_DATE_typed_row_token_whose_kind_nothing_resolves_is_a_date_never_MY(table, row, tok,
                                                                                              kind):
    """Ruling R-2's date rule on EVERY row-own token whose kind no card resolves, card or no card: the token's
    SOURCE FAMILY names its kind by itself (`citations._kind_of_source` with no card) -- a date-typed value
    (the date type's own parser) is a day, a year+month pair a month -- so "MY" can never precede a date on
    this branch. (The QUERY's period on an unresolvable card keeps HEAD's rule, pinned above: that is a token
    HEAD printed; this branch prints tokens HEAD never did.)"""
    c = _call(table, "x", [dict(row, value="3")])
    assert cit.printed_period(c) == (tok, kind)
    label = cit.from_number(c, 1).label
    assert f" {tok} = 3" in label and "MY" not in label, label
    # ...and the rule can only move a DATE: a year label whose kind nothing resolves keeps HEAD's prefix
    assert cit._kind_of_source("period", None, {}, "2026") is None
    assert cit._kind_of_source("period", None, {}, "2026/27") is None
