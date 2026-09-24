"""THE HEADLINE ROW OF A CITATION -- `citations._row_order_key`, `_headline`, `headline_row` (pure; no AWS).

`_row_order_key`'s own docstring names this file as the place its behaviour change is PINNED rather than
described (T1-5 / X3): on a curve read -- one session, several delivery months -- the key sorts the
expiries ascending and `max()` headlines THE FURTHEST-DATED one, deterministically. That property stays
pinned here, because the key is still the order every non-curve read and the extras path rank by.

THE 09-23 CHANGE (lane C, CONTRACT C12) sits ABOVE the key, not inside it: the 2026-09-23 re-smoke served
the November 2026 soybean settle at 1,328 inside N2 and headlined March 2027 at 1,352 ("the furthest
expiry by design"), and the page then told the reader "no front-month level can be named this session"
(deep26 F4, max F2). A CURVE read now headlines the nearest ELIGIBLE delivery through lane T's ONE
producer, `numbers.query.curve_headline_index` -- the roll rule's own eligibility, never a reversed sort
key -- and every non-curve read keeps `_row_order_key`'s headline byte for byte.
"""
from __future__ import annotations

import pytest

from leviathan.graphrag import citations as cit


def _curve(months_values, session="2026-09-21", slug="soybeans_cbot", asof="2026-09-23"):
    rows = [{"value": str(v), "unit": "US cents/bushel", "knowledge_date": session, "contract_month": cm,
             "settle_kind": "settlement", "currency": "USD"} for cm, v in months_values]
    return {"query": {"table": "silver_futures_eod", "metric": "settle", "commodity": slug, "country": None,
                      "period": None, "asof": asof}, "rows": rows, "status": "ok"}


#: The deep26 N2 serve, reconstructed: three expiries of ONE session, ascending (the banked trace keeps
#: value + session; the months are the CBOT soybean cycle the fact grade read them as).
_DEEP26_N2 = [("2026-11", 1328.0), ("2027-01", 1344.0), ("2027-03", 1351.75)]
#: The max N2 serve: the same three plus May 2027 (4 rows served, "delivery 2027-05 = 1,358").
_MAX_N2 = _DEEP26_N2 + [("2027-05", 1358.0)]


def _has_producer() -> bool:
    from leviathan.graphrag.numbers import query as Q
    return callable(getattr(Q, "curve_headline_index", None))


def test_the_KEY_still_orders_a_curve_ascending_and_its_max_is_the_furthest_expiry():
    """X3's pinned contract, unchanged: the key's LAST term is the delivery month, so on one session the
    key's max is the furthest expiry. The key is not what moved."""
    call = _curve(_DEEP26_N2)
    assert max(call["rows"], key=cit._row_order_key)["contract_month"] == "2027-03"
    assert [r["contract_month"] for r in sorted(call["rows"], key=cit._row_order_key)] == [
        "2026-11", "2027-01", "2027-03"]


@pytest.mark.parametrize("serve,value", [(_DEEP26_N2, "1,328"), (_MAX_N2, "1,328")])
def test_a_CURVE_read_headlines_the_nearest_eligible_delivery(serve, value):
    if not _has_producer():
        pytest.skip("lane T's query.curve_headline_index (CONTRACT C12) not landed on this tree")
    c = cit.from_number(_curve(serve), 2)
    assert f"= {value} US cents/bushel" in c.label, c.label
    assert "nearest listed delivery 2026-11" in c.label and "2027-" not in c.label.split(" = ")[0]
    assert "nearest eligible delivery shown]" in c.label and "newest shown" not in c.label
    assert c.value == "1328.0" and c.locator["contract_month"] == "2026-11"
    assert cit.headline_row(_curve(serve))["contract_month"] == "2026-11", "ONE selector, two readers"


def test_a_SINGLE_ROW_futures_read_is_byte_identical_to_HEAD():
    """The tariff N29 (November 2026, one row) and the cocoa December tape rows: no curve, no change in
    the headline or the delivery words."""
    one = _curve([("2026-11", 1328.0)])
    c = cit.from_number(one, 29)
    assert "delivery 2026-11 = 1,328 US cents/bushel" in c.label and "nearest" not in c.label
    assert cit.headline_row(one)["contract_month"] == "2026-11"


def test_a_MULTI_SESSION_series_keeps_the_newest_observation_headline():
    """A read spanning several sessions is not a curve: the freshest observation headlines, as always."""
    rows = [{"value": str(v), "knowledge_date": d, "contract_month": "2026-11"}
            for d, v in (("2026-09-17", 1300), ("2026-09-18", 1310), ("2026-09-21", 1328))]
    call = {"query": {"table": "silver_futures_eod", "metric": "settle", "commodity": "soybeans_cbot",
                      "asof": "2026-09-23"}, "rows": rows, "status": "ok"}
    assert cit.headline_row(call)["knowledge_date"] == "2026-09-21"
    assert "newest shown]" in cit.from_number(call, 1).label


@pytest.mark.parametrize("method,words", [("open_interest", "delivery 2026-11"), ("volume", "delivery 2026-11"),
                                          ("cycle_nearest_eligible", "nearest listed delivery 2026-11"),
                                          ("delivery_cycle", "nearest listed delivery 2026-11")])
def test_FRONT_MONTH_is_the_named_OI_or_volume_rules_word_alone(method, words):
    """OWNER DECISION 5: a front read whose row declares a roll method OUTSIDE `ROLL_METHODS_FRONT` (the
    cycle fallback on expiry week, a delivery-cycle board) is labelled the nearest listed delivery -- so
    the writer is never handed a "front month" that the named rule did not pick."""
    from leviathan.graphrag.numbers import query as Q
    if getattr(Q, "ROLL_METHODS_FRONT", None) is None:
        pytest.skip("lane T's query.ROLL_METHODS_FRONT (CONTRACT C12) not landed on this tree")
    call = _curve([("2026-11", 1328.0)])
    call["rows"][0]["roll_method"] = method
    lab = cit.from_number(call, 1).label
    assert f" {words} = " in lab, lab
    if method in Q.ROLL_METHODS_FRONT:
        assert "nearest" not in lab
