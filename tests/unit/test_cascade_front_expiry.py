"""PRICE_AND_PLAYBOOKS W3.3 item 17 / skeptic F-E -- the `front_expiry` pace-collapse KIND + the
price-table collapse lint (hermetic: no pg/Athena/LLM; hand-built records, the test_cascade_pace_leg
idiom).

THE NAMED GATE (plan :1041) is test_front_expiry_fixes_the_two_expiry_sign_inversion below: an
adversarial multi-expiry fixture -- two dates x three expiries -- where the naive last-minus-prev
delta deltas two EXPIRIES and comes out UP (+5.0) while the whole curve actually fell (-2.0 on the
front month). Without the collapse that inverted number rides a real minted [N] handle that the
all-numbers guard validates as correct; with it, the front expiry is selected by the ONE named
query-time rule (leviathan.silver.futures_roll, front_month_v2) first and the delta is taken across
DATES after.

Nothing here wires silver_futures_eod into PACE_TABLES -- that is W3.3 item 16, gated on the parity
soak. The end-to-end leg test monkeypatches the inventory to prove the post-soak behaviour is safe,
and test_futures_eod_stays_out_of_pace_tables pins the fence itself.
"""
from __future__ import annotations

import pytest

from leviathan.graphrag import config_check as cc
from leviathan.graphrag.numbers import cascade as cq

_MATIF_ROW = {
    "table": "silver_futures_eod", "metric": "settle", "period_type": "date",
    "native_unit": "EUR/t", "narrate_unit": "EUR/t", "scale": 1,
}
_KEY = ("french_wheat_matif", "matif_curve")


def _eod_rec(rows, commodity="french_wheat_matif", key=_KEY):
    """A pace record shaped like a REAL silver_futures_eod read: the card's date_col IS its
    knowledge_date_col (trade_date), so query._extras surfaces `knowledge_date` and nothing else --
    which is precisely why _pace_period_key's ("_row", idx) fallback would give every curve row its
    own 'period'. rows = [(value, trade_date, contract_month, open_interest), ...] in SQL order."""
    return {"query": {"commodity": commodity, "metric": "settle", "asof": "2026-06-02"},
            "rows": [{"value": str(v), "unit": "EUR/t", "knowledge_date": d, "contract_month": cm,
                      **({"open_interest": oi} if oi is not None else {})}
                     for v, d, cm, oi in rows],
            "status": "ok", "node_key": key, "leg": ("pace", None), "era_idx": None, "my": None}


# THE ADVERSARIAL FIXTURE. MATIF milling wheat lists Mar/May/Sep/Dec, so on a 2026-06 session the
# eligible months are 2026-09 (front), 2026-12 and 2027-03. The whole curve fell 2 EUR/t overnight,
# but rows arrive date-ascending then value-ascending (the futures_eod ORDER BY today), so the last
# two ROWS are Dec-2026 and Mar-2027 of the SECOND date: +5.0 -- up, on a curve that fell.
_INVERSION_ROWS = [
    (210.0, "2026-06-01", "2026-09", None),
    (215.0, "2026-06-01", "2026-12", None),
    (220.0, "2026-06-01", "2027-03", None),
    (208.0, "2026-06-02", "2026-09", None),
    (214.0, "2026-06-02", "2026-12", None),
    (219.0, "2026-06-02", "2027-03", None),
]


# -- declarations ----------------------------------------------------------------------------------
def test_front_expiry_is_a_declared_kind_bound_to_an_expiry_column():
    assert "front_expiry" in cq._PACE_COLLAPSE_KINDS
    assert cq._PACE_COLLAPSE["silver_futures_eod"] == "front_expiry"
    assert cq._PACE_EXPIRY_COL["silver_futures_eod"] == "contract_month"
    assert "silver_futures_eod" in cq._PRICE_TABLES


def test_futures_eod_stays_out_of_pace_tables():
    # W3.3 item 16 is GATED on the parity soak (F-E: not until the collapse kind exists -- it does
    # now, but the soak still owns the flip). This test is the fence, not a to-do.
    assert "silver_futures_eod" not in cq.PACE_TABLES
    assert cq._pace_grain({"table": "silver_futures_eod", "period_type": "date"}) is None


# -- THE NAMED GATE: the sign inversion, and the collapse that fixes it -----------------------------
def test_naive_last_minus_prev_on_the_fixture_is_direction_inverted():
    """The defect, demonstrated on the SAME rows: an UNDECLARED per-expiry table keeps the legacy
    one-row-one-period path, and because the rows carry no data_date alias every row becomes its own
    'period' -- so the fail-safe 'multi-row period declines whole' never even fires. The delta is
    Mar-2027 minus Dec-2026 on one session: +5.0, up, on a curve that fell."""
    rec = _eod_rec(_INVERSION_ROWS)
    vals, collapsed = cq._pace_series(rec, "silver_futures_eod_shadow")   # a table nobody declared
    assert vals == [210.0, 215.0, 220.0, 208.0, 214.0, 219.0] and collapsed is None
    assert vals[-1] - vals[-2] == pytest.approx(5.0)                     # UP: two expiries, one date


def test_front_expiry_fixes_the_two_expiry_sign_inversion():
    """THE GATE. Same rows, declared table: select the front expiry (2026-09 -- the nearest LISTED
    MATIF month not yet in delivery) per trade date FIRST, then delta across dates."""
    rec = _eod_rec(_INVERSION_ROWS)
    vals, collapsed = cq._pace_series(rec, "silver_futures_eod")
    assert vals == [210.0, 208.0]                                        # ONE value per DATE, front month
    assert collapsed == "front_expiry"
    assert vals[-1] - vals[-2] == pytest.approx(-2.0)                    # DOWN -- the honest direction
    naive = [float(r["value"]) for r in rec["rows"]]
    assert (naive[-1] - naive[-2]) * (vals[-1] - vals[-2]) < 0           # the signs genuinely oppose


def test_pace_leg_end_to_end_emits_the_front_month_change_row(monkeypatch):
    """The post-soak behaviour (item 16), proven WITHOUT wiring the table into the shipped inventory."""
    monkeypatch.setitem(cq.PACE_TABLES, "silver_futures_eod", "day")
    rec = _eod_rec(_INVERSION_ROWS)
    calls: list = []
    lines, trace = cq._pace_legs([rec], [{"specs": [{"node_key": _KEY}], "row": _MATIF_ROW}], 0, calls)
    assert len(calls) == 1 and len(lines) == 1                           # one move: change row, no streak
    assert calls[0]["rows"][0]["value"] == pytest.approx(-2.0)           # NEVER +5 (Mar-2027 - Dec-2026)
    assert calls[0]["query"]["metric"] == "settle_pace_change"
    assert lines[0] == ("- [N1] change in settlement price from the prior day (daily pace): -2 EUR/t "
                        "[series: french_wheat_matif; table: FUTURES EOD]")
    assert trace[0]["collapse"] == "front_expiry"
    assert trace[0]["n_points"] == 2                                     # TRADE DATES, not curve rows
    assert cq.pace_register_ok(lines[0])


# -- the rule is CALLED, not emulated ---------------------------------------------------------------
def test_front_by_open_interest_beats_the_nearest_month_when_oi_is_present():
    """corn_cbot rolls by OPEN INTEREST (GLBX publishes it). With OI on the rows the selection must
    name Dec -- the OI leader -- not Sep, the nearest month. If this ever returns the nearest-month
    series [420, 418] the module has silently degraded to a different, unnamed rule."""
    rec = _eod_rec([(420.0, "2026-06-01", "2026-09", 1000),
                    (430.0, "2026-06-01", "2026-12", 5000),
                    (418.0, "2026-06-02", "2026-09", 900),
                    (435.0, "2026-06-02", "2026-12", 5200)], commodity="corn_cbot")
    vals, collapsed = cq._pace_series(rec, "silver_futures_eod")
    assert vals == [430.0, 435.0] and collapsed == "front_expiry"


def test_front_by_oi_slug_declines_when_the_rules_own_input_is_absent():
    """The card is settle-ONLY, so a served row carries no open_interest today. front_month would
    fill the missing metric with -1 and fall through to its nearest-month tie-break -- a DIFFERENT
    rule wearing front_month_v2's name. Honest absence instead."""
    rows = [(r[0], r[1], r[2], None) for r in _INVERSION_ROWS]
    vals, collapsed = cq._pace_series(_eod_rec(rows, commodity="corn_cbot"), "silver_futures_eod")
    assert vals == [] and collapsed is None


_PARTIAL_OI_ROWS = [(420.0, "2026-06-01", "2026-09", None), (430.0, "2026-06-01", "2026-12", 5000),
                    (418.0, "2026-06-02", "2026-09", None), (435.0, "2026-06-02", "2026-12", 5200)]


def test_front_by_oi_slug_declines_when_its_input_is_present_on_only_SOME_rows(monkeypatch):
    """THE PARTIAL CASE -- the one a 'decline only when the metric is missing EVERYWHERE' guard waves
    through. OI prints on the Dec row of each session and is absent on Sep, so front_month's -1 fill
    makes Dec win by DEFAULT rather than by open interest: a nearest-print rule wearing front_month_v2's
    name, the same substitution the all-missing case declines on. Unreachable while the card is
    settle-ONLY; live the moment open_interest is surfaced as a selection-only alias.

    The second half shows the defect the guard prevents: with the precondition waved through, the leg
    happily returns the OI-carrying expiry's series and nothing downstream can tell that the winner was
    decided by which row happened to carry a print."""
    rec = _eod_rec(_PARTIAL_OI_ROWS, commodity="corn_cbot")
    assert cq._pace_series(rec, "silver_futures_eod") == ([], None)
    from leviathan.silver import futures_roll as FR
    monkeypatch.setattr(FR, "front_month_inputs_present", lambda df: True)
    assert cq._pace_series(rec, "silver_futures_eod") == ([430.0, 435.0], "front_expiry")


def test_a_blank_metric_string_is_absent_too():
    rec = _eod_rec([(420.0, "2026-06-01", "2026-09", ""), (430.0, "2026-06-01", "2026-12", 5000),
                    (418.0, "2026-06-02", "2026-09", ""), (435.0, "2026-06-02", "2026-12", 5200)],
                   commodity="corn_cbot")
    assert cq._pace_series(rec, "silver_futures_eod") == ([], None)


def test_the_input_precondition_is_DELEGATED_to_the_rule_module(monkeypatch):
    """Which column each method reads is the rule module's contract (METHOD_METRIC_COL), not this
    module's: cascade asks futures_roll and obeys the answer. Flipping the module's verdict flips the
    leg both ways, which no inline copy of the mapping could do."""
    from leviathan.silver import futures_roll as FR
    rec = _eod_rec([(r[0], r[1], r[2], None) for r in _INVERSION_ROWS], commodity="corn_cbot")
    monkeypatch.setattr(FR, "front_month_inputs_present", lambda df: True)
    assert cq._pace_series(rec, "silver_futures_eod")[1] == "front_expiry"
    monkeypatch.setattr(FR, "front_month_inputs_present", lambda df: False)
    assert cq._pace_series(rec, "silver_futures_eod") == ([], None)


def test_cash_index_slug_has_no_front_month_and_declines():
    rec = _eod_rec([(2100.0, "2026-06-01", "2026-09", None), (2050.0, "2026-06-02", "2026-09", None)],
                   commodity="brazilian_arabica_coffee")                 # CEPEA: roll method 'none'
    assert cq._pace_series(rec, "silver_futures_eod") == ([], None)


def test_unmapped_slug_declines_and_never_raises():
    rec = _eod_rec(_INVERSION_ROWS, commodity="not_a_contract")
    assert cq._pace_series(rec, "silver_futures_eod") == ([], None)


# -- fail-closed on every incompleteness ------------------------------------------------------------
def test_expiry_column_and_slug_are_threaded_not_hardcoded():
    """The plumbing itself: the selection reads the alias it is HANDED. Same rows under a different
    delivery-month alias select identically when it is threaded, and decline when it is not."""
    rec = _eod_rec(_INVERSION_ROWS)
    for r in rec["rows"]:
        r["delivery_month"] = r.pop("contract_month")
    assert cq._pace_series(rec, "silver_futures_eod") == ([], None)
    vals, collapsed = cq._pace_series(rec, "silver_futures_eod", expiry_col="delivery_month",
                                      commodity="french_wheat_matif")
    assert vals == [210.0, 208.0] and collapsed == "front_expiry"


def test_missing_expiry_alias_declines_whole():
    """The live pre-W3.1 shape: query._extras does not surface contract_month yet. An unlabeled curve
    row is unattributable, so the leg declines rather than delta-ing whatever arrived."""
    rec = _eod_rec(_INVERSION_ROWS)
    for r in rec["rows"]:
        r.pop("contract_month")
    assert cq._pace_series(rec, "silver_futures_eod") == ([], None)


def test_undated_row_declines_whole():
    rec = _eod_rec(_INVERSION_ROWS)
    rec["rows"][2].pop("knowledge_date")
    assert cq._pace_series(rec, "silver_futures_eod") == ([], None)


def test_no_commodity_on_the_record_declines_whole():
    rec = _eod_rec(_INVERSION_ROWS)
    rec["query"]["commodity"] = None
    assert cq._pace_series(rec, "silver_futures_eod") == ([], None)


def test_a_roll_inside_the_window_declines_rather_than_splicing():
    """The front month rolls between the two sessions (Sep expires, Dec becomes front). Delta-ing
    across that is a SPLICE -- the same contamination levels_only fences on the continuous sibling --
    so the leg declines. Roll/continuous are out of scope for this table by ratified design."""
    rec = _eod_rec([(210.0, "2026-09-01", "2026-09", None), (215.0, "2026-09-01", "2026-12", None),
                    (216.0, "2026-10-01", "2026-12", None), (221.0, "2026-10-01", "2027-03", None)])
    assert cq._pace_series(rec, "silver_futures_eod") == ([], None)


def test_a_missing_print_on_the_front_month_never_substitutes_the_next_expiry():
    """Sep has no numeric settle on the first session. Selecting Dec for that date alone and Sep for
    the next would delta two EXPIRIES again, by a different route -- the single-contract fence catches
    it and the leg declines."""
    rec = _eod_rec(_INVERSION_ROWS)
    rec["rows"][0]["value"] = ""                                         # the true front, no print
    assert cq._pace_series(rec, "silver_futures_eod") == ([], None)


def test_every_expiry_in_delivery_leaves_nothing_to_select():
    # both listed months are BEHIND the trade month -> no eligible contract -> no series, no guess.
    rec = _eod_rec([(210.0, "2026-06-01", "2026-03", None), (211.0, "2026-06-01", "2026-05", None),
                    (208.0, "2026-06-02", "2026-03", None), (209.0, "2026-06-02", "2026-05", None)])
    assert cq._pace_series(rec, "silver_futures_eod") == ([], None)


def test_single_date_is_under_two_points_so_no_pace_claim(monkeypatch):
    monkeypatch.setitem(cq.PACE_TABLES, "silver_futures_eod", "day")
    rec = _eod_rec(_INVERSION_ROWS[:3])                                  # one trade date, three expiries
    calls: list = []
    lines, trace = cq._pace_legs([rec], [{"specs": [{"node_key": _KEY}], "row": _MATIF_ROW}], 0, calls)
    assert lines == [] and trace == [] and calls == []


def test_a_per_expiry_table_declared_any_other_way_declines_whole(monkeypatch):
    """The runtime twin of the lint: even if someone types 'mean' for a per-expiry price table, the
    engine refuses to apply it (fail-closed) rather than minting a plausible unnamed series."""
    for bad in ("mean", "sum"):
        monkeypatch.setitem(cq._PACE_COLLAPSE, "silver_futures_eod", bad)
        assert cq._pace_series(_eod_rec(_INVERSION_ROWS), "silver_futures_eod") == ([], None)
        assert cq._pace_collapse_kind("silver_futures_eod") is None


def test_legacy_collapse_kinds_are_untouched():
    """Byte-identical behaviour for the two shipped kinds (the ESR/weather regression fence)."""
    esr = {"query": {}, "rows": [{"value": "300", "data_date": "2026-06-21"},
                                 {"value": "310", "data_date": "2026-06-21"},
                                 {"value": "280", "data_date": "2026-06-28"},
                                 {"value": "285", "data_date": "2026-06-28"}], "status": "ok"}
    assert cq._pace_series(esr, "silver_esr") == ([610.0, 565.0], "sum")
    wz = {"query": {}, "rows": [{"value": "0.3", "year": "2026", "month": "5"},
                                {"value": "0.5", "year": "2026", "month": "5"},
                                {"value": "0.8", "year": "2026", "month": "6"},
                                {"value": "1.2", "year": "2026", "month": "6"}], "status": "ok"}
    assert cq._pace_series(wz, "gold_weather_z") == ([0.4, 1.0], "mean")
    cot = {"query": {}, "rows": [{"value": "100", "data_date": "2026-06-21"},
                                 {"value": "140", "data_date": "2026-06-28"}], "status": "ok"}
    assert cq._pace_series(cot, "silver_cot") == ([100.0, 140.0], None)


# -- THE F-E LINT ------------------------------------------------------------------------------------
def test_shipped_declarations_lint_clean():
    assert cq.lint_pace_collapse() == []
    assert cc.check_pace_collapse() == []


def test_lint_forbids_sum_and_mean_on_every_price_table(monkeypatch):
    for table in sorted(cq._PRICE_TABLES):
        for bad in ("sum", "mean"):
            monkeypatch.setitem(cq._PACE_COLLAPSE, table, bad)
            errs = cq.lint_pace_collapse()
            assert any(table in e and "FORBIDDEN on a price table" in e for e in errs), (table, bad, errs)
            monkeypatch.undo()
            monkeypatch.setitem(cq._PACE_COLLAPSE, table, bad)          # re-arm for the config_check bind
            assert any(e.startswith("pace_collapse: ") for e in cc.check_pace_collapse())
            monkeypatch.undo()


def test_lint_belt_catches_a_price_table_nobody_declared(monkeypatch):
    """The drift belt: silver_pink_sheet removed from the explicit set is still caught, because its
    registry card reads as a price table (currency-per-quantity units)."""
    monkeypatch.setattr(cq, "_PRICE_TABLES", frozenset({"silver_futures_eod"}))
    monkeypatch.setitem(cq._PACE_COLLAPSE, "silver_pink_sheet", "mean")
    errs = cq.lint_pace_collapse()
    assert any("silver_pink_sheet" in e and "reads as a PRICE table" in e for e in errs), errs


def test_lint_rejects_an_unknown_collapse_kind(monkeypatch):
    monkeypatch.setitem(cq._PACE_COLLAPSE, "silver_esr", "median")
    errs = cq.lint_pace_collapse()
    assert any("unknown collapse kind" in e for e in errs), errs
    assert cq._pace_collapse_kind("silver_esr") is None                  # runtime refuses it too


def test_lint_binds_front_expiry_to_an_expiry_column_both_ways(monkeypatch):
    monkeypatch.delitem(cq._PACE_EXPIRY_COL, "silver_futures_eod")
    assert any("no delivery-month alias" in e for e in cq.lint_pace_collapse())
    monkeypatch.undo()
    monkeypatch.setitem(cq._PACE_COLLAPSE, "silver_futures_eod", "sum")
    errs = cq.lint_pace_collapse()
    assert any("declared per-delivery-month but its _PACE_COLLAPSE kind" in e for e in errs), errs


def test_lint_is_pure_and_returns_ascii_strings():
    for e in cq.lint_pace_collapse() + ["probe"]:
        assert isinstance(e, str) and e.isascii()
