"""FIX SITTING 3 (plan 09-27), LANE W -- walk.py / feeders.py (CONTRACT Z10, Z12, Z13 feeder half, Z22).

Every test runs OFFLINE: canned rows through ``feeders.fixture_query_fn`` (the REAL compiler first), hand-built
board rows and a stub graph for the quorum. Each item's FACT and CHECK are named in BUILD_W.md; the pins here
guard the facts the walk now serves:

* Z10 (U-2 + M-4): a READ quorum member of a regime type is read by the walk's own regime reading of its dated
  action, never by its trade-flow series' tail; a member held only as last revised is no reading of the
  present. Both are NAMED with their reason and never counted; ``None`` kwargs are HEAD byte for byte.
* Z12 (U-11): each past time is priced on the contract the shipped roll rule names front at the close of its
  own band, over that band, never across a roll, point-in-time, with every decline named and every read counted.
* Z13 (U-8, feeder half): one FX row per non-USD currency, dated on or before the spread's session and the
  as-of, a stale or missing series named -- never converted here.
* Z22 (ORCH-P2): the then-current WASDE line of a held row as its own StateRow, zero reads.
"""
import datetime as _dt
import types

import pytest
from leviathan.graphrag.numbers import registry as REG
from leviathan.graphrag.state import board as B
from leviathan.graphrag.state import feeders as F
from leviathan.graphrag.state import walk as W
from leviathan.graphrag.state.lagbands import parse_lag
from leviathan.graphrag.state.rows import SeriesKey, StateRow


# ---------------------------------------------------------------------------------------------------------------
# Z10 -- THE QUORUM MEMBER BY ITS OWN CONDITION
# ---------------------------------------------------------------------------------------------------------------
def _graph(direction="+", signs=None, requires=2):
    signs = dict(signs or {"ban": "+", "stocks": "-", "flow": "+"})
    drivers = [types.SimpleNamespace(id=d, sign=s) for d, s in signs.items()]
    sig = types.SimpleNamespace(name="export_restriction", direction=direction, drivers=tuple(signs),
                                requires_any_n_of=requires, interactions=())
    return types.SimpleNamespace(contracts={"rice": types.SimpleNamespace(drivers=drivers, convergence=[sig])})


def _row(**kw):
    return W.convergence_rows(_graph(), "rice", {"ban", "stocks", "flow"}, loud_k=16,
                              measured_ids={"ban", "stocks", "flow"}, sides={"stocks": -1, "flow": +1}, **kw)[0]


def test_Z10_default_kwargs_are_HEAD_byte_for_byte_and_add_no_key():
    head = W.convergence_rows(_graph(), "rice", {"ban", "stocks", "flow"}, loud_k=16,
                              measured_ids={"ban", "stocks", "flow"}, sides={"stocks": -1, "flow": +1})
    assert head == W.convergence_rows(_graph(), "rice", {"ban", "stocks", "flow"}, loud_k=16,
                                      measured_ids={"ban", "stocks", "flow"}, sides={"stocks": -1, "flow": +1},
                                      regime=None, held=None)
    assert "unread_reason" not in head[0]
    assert head[0]["matched_measured"] == ("ban", "stocks", "flow"), "HEAD: a sideless regime member is counted"


def test_Z10_a_regime_member_with_no_action_in_force_is_NAMED_with_its_reason_and_never_counted():
    """U-2, the arm-A rice FATAL: India exports at the 99th percentile were counted as the India export ban
    while the walk's own chain hop on that node read no dated action."""
    r = _row(regime={"ban": {"in_force": None, "action": None, "why": "none"}})
    assert "ban" in r["matched"], "the ORDERING count keeps HEAD's loud intersection"
    assert "ban" not in r["matched_measured"] and "ban" in r["matched_unmeasured"]
    assert r["unread_reason"] == {"ban": "regime_action_unread"}
    assert r["unread_reason"]["ban"] in W.QUORUM_UNREAD_REASONS
    # a report / forecast on the node (False) is not an action in force either
    r2 = _row(regime={"ban": {"in_force": False, "action": None, "why": "report_in_reach"}})
    assert r2["unread_reason"] == {"ban": "regime_action_unread"}


def test_Z10_a_regime_action_IN_FORCE_reads_the_node_present_through_the_cards_own_tail_rule():
    r = _row(regime={"ban": {"in_force": True, "action": {}, "why": "regime_in_force"}})
    assert "ban" in r["matched_measured"] and "unread_reason" not in r
    # the SAME action on a pattern whose card asks the node's absence (a bearish pattern, node declared '+')
    bear = W.convergence_rows(_graph(direction="-"), "rice", {"ban"}, loud_k=16, measured_ids={"ban"},
                              sides={}, regime={"ban": {"in_force": True}})[0]
    assert bear["against"] == ("ban",) and "ban" not in bear["matched"]
    # a node declared with no committed direction is unsided, never counted
    flat = W.convergence_rows(_graph(signs={"ban": "0"}), "rice", {"ban"}, loud_k=16, measured_ids={"ban"},
                              sides={}, regime={"ban": {"in_force": True}})[0]
    assert flat["unsided"] == ("ban",)


def test_Z10_a_member_held_only_as_last_revised_is_named_not_counted_whatever_its_tail():
    """M-4: a served marketing-year level the store holds only as last revised is no reading of the present --
    neither a condition showing nor one counted against (``flow`` sits in the asked tail, ``stocks`` in the
    asked tail of a '-' driver; both leave the count)."""
    r = _row(held={"flow", "stocks"})
    assert r["unread_reason"] == {"stocks": "held_as_last_revised", "flow": "held_as_last_revised"}
    assert set(r["matched_unmeasured"]) == {"stocks", "flow"}
    assert r["matched_measured"] == ("ban",), "the sideless regime member without a regime fact keeps HEAD"
    # an UNREAD member (no series) is never touched by either fact
    un = W.convergence_rows(_graph(), "rice", {"ban", "flow"}, loud_k=16, measured_ids={"flow"},
                            sides={"flow": 1}, regime={"ban": {"in_force": None}}, held=set())[0]
    assert "unread_reason" not in un and un["matched_unmeasured"] == ("ban",)


def test_Z10_the_four_populations_partition_the_loud_members_on_every_combination():
    for reg in (None, {"ban": {"in_force": None}}, {"ban": {"in_force": True}}):
        for held in (None, {"flow"}, {"stocks", "flow"}):
            r = _row(regime=reg, held=held)
            loud = {"ban", "stocks", "flow"}
            m, a, u = set(r["matched"]), set(r.get("against") or ()), set(r.get("unsided") or ())
            assert m | a | u == loud and not (m & a) and not (m & u)
            assert set(r["matched_measured"]) | set(r["matched_unmeasured"]) == m
            assert not (set(r["matched_measured"]) & set(r["matched_unmeasured"]))
            assert set(r.get("unread_reason") or {}) <= set(r["matched_unmeasured"])


def _regime_row(**kw):
    kw.setdefault("lag", "0-1 quarters")
    return B.NodeRow(contract="rough_rice_cbot", driver_id="India_export_ban", type="policy_event", sign="+",
                     lag_band=parse_lag(kw["lag"]), **kw)


def test_Z10_regime_state_is_the_chain_hops_own_reading_of_the_dated_action():
    bd = types.SimpleNamespace(asof="2026-09-24")
    row = _regime_row()
    rec = {"date": "2026-03-10", "event_date": "2026-03-01", "event_date_precision": "day",
           "text": "India banned non-basmati white rice exports", "source": "fixture"}
    got = W.regime_state(bd, row, receipts={row.key: [rec]})
    assert got["in_force"] is True and got["why"] in W.REGIME_IN_FORCE_KINDS
    assert got["action"]["event_date"] == "2026-03-01" and got["action"]["origin"] == "draw"
    assert W.regime_state(bd, row, receipts={})["in_force"] is None
    assert W.regime_state(bd, row, receipts={})["why"] == "none"
    # a statement about its own future (guidance: dated before the as-of, written before the event) is not an
    # action in force
    fut = dict(rec, date="2026-03-10", event_date="2026-09-01")
    assert W.regime_state(bd, row, receipts={row.key: [fut]})["in_force"] is False
    # a non-regime row is not read here at all
    plain = B.NodeRow(contract="rough_rice_cbot", driver_id="drought", type="weather_state", sign="+")
    assert W.regime_state(bd, plain) == {"in_force": None, "action": None, "why": "not_regime"}


def test_Z10_quorum_member_facts_reads_only_READ_rows_and_the_measured_retention_stamp():
    bd = types.SimpleNamespace(asof="2026-09-24")
    held_st = StateRow(key=SeriesKey(ref="psd_ending_stock_su_ratio", commodity="soybeans_cbot"),
                       recency={F.RETENTION_KEY: {"state": "held_as_last_revised"}})
    fresh_st = StateRow(key=SeriesKey(ref="area", commodity="soybeans_cbot"))
    rows = [_regime_row(), B.NodeRow(contract="c", driver_id="su", type="balance_state", state=held_st),
            B.NodeRow(contract="c", driver_id="area", type="supply_state", state=fresh_st),
            B.NodeRow(contract="c", driver_id="pos", type="positioning", state=held_st, context_only=True)]
    regime, held = W.quorum_member_facts(bd, rows, {"India_export_ban", "su", "area", "pos"})
    assert set(regime) == {"India_export_ban"} and held == {"su"}
    regime2, held2 = W.quorum_member_facts(bd, rows, {"area"})
    assert regime2 == {} and held2 == set(), "an unread row is never a member fact"


# ---------------------------------------------------------------------------------------------------------------
# Z12 -- THE FRONT PRICE AT EACH PAST TIME
# ---------------------------------------------------------------------------------------------------------------
_CYCLE = (1, 3, 5, 7, 8, 9, 11)


def _curve(start, end, *, first_listed=None):
    """A silver_futures_eod SERIES read's shape over a soybean-like cycle: one row per (session, listed expiry);
    each expiry's settle is its own ramp (base by expiry index + 0.5 per session), so a move that wandered onto
    a neighbouring month could not reproduce the one-contract figures; open interest falls with distance so the
    nearest listed month after the session's own month is the front. ``first_listed`` delays one expiry's
    listing (``{expiry: first session}``)."""
    exps = ["%04d-%02d" % (y, m) for y in range(2018, 2023) for m in _CYCLE]
    d, d1, i, out = _dt.date.fromisoformat(start), _dt.date.fromisoformat(end), 0, []
    while d <= d1:
        if d.weekday() < 5:
            s = d.isoformat()
            live = [e for e in exps if s[:7] < e <= "%04d-%02d" % (d.year + 1, d.month)
                    and s >= (first_listed or {}).get(e, "")]
            for rank, e in enumerate(live):
                out.append({"value": str(900.0 + 10.0 * exps.index(e) + 0.5 * i), "knowledge_date": s,
                            "contract_month": e, "settle_kind": "official", "currency": "USD",
                            "unit": "US cents/bushel", "open_interest": 100000 - 5000 * rank,
                            "volume": 40000 - 2000 * rank})
            i += 1
        d += _dt.timedelta(days=1)
    return out


_ROWS = _curve("2018-12-01", "2020-01-31")
_BAND = parse_lag("0-2 quarters")


def test_Z12_each_past_time_is_priced_on_the_contract_front_at_the_close_of_its_own_band_never_spliced():
    qfn = F.fixture_query_fn({"silver_futures_eod": _ROWS})
    fm = F.front_moves("soybeans_cbot", [{"date": "2019-03-01"}], _BAND, "2019-12-31", qfn=qfn)
    e = fm["per_firing"]["2019-03-01"]
    assert e["contract_month"] == "2019-09" and e["status"] == "ok"
    assert e["named_at"] <= "2019-09-01" and e["dates"][-1] <= "2019-09-01"
    assert e["dates"][0] <= "2019-03-01", "the contract traded at the band's opening"
    # ONE contract: every price is that expiry's own ramp (0.5 per session) -- no step at any date
    steps = {round(b - a, 6) for a, b in zip(e["values"], e["values"][1:])}
    assert steps == {0.5}, steps
    assert fm["reads"] == 2 and not fm["declined"], "one front read at the close, one contract read"
    assert set(F.FRONT_MOVE_DECLINES) >= {"pre_coverage", "front_decline", "contract_expired_in_band",
                                          "in_flight", "read_error"}


def test_Z12_in_flight_and_pre_coverage_decline_BY_NAME_at_ZERO_reads():
    def _never(sql):
        raise AssertionError("a past time the store cannot price must not spend a read")
    fm = F.front_moves("soybeans_cbot", [{"date": "2019-11-01"}, {"date": "2008-05-01"}], _BAND,
                       "2019-12-31", qfn=_never)
    assert fm["declined"] == {"2019-11-01": "in_flight", "2008-05-01": "pre_coverage"}
    assert fm["reads"] == 0 and fm["per_firing"] == {}
    tapeless = F.front_moves("soybeans", [{"date": "2019-03-01"}], _BAND, "2019-12-31", qfn=_never)
    assert tapeless["declined"] == {"2019-03-01": "front_decline"} and tapeless["reads"] == 0
    # a CASH REFERENCE (the roll rule's own declared method 'none') is never asked "which contract was front"
    cash = F.front_moves("campinas_corn_reference_bmf", [{"date": "2019-03-01"}], _BAND, "2019-12-31",
                         qfn=_never)
    assert cash["declined"] == {"2019-03-01": "front_decline"} and cash["reads"] == 0


def test_Z12_a_contract_not_trading_at_the_bands_opening_declines_and_a_failed_read_never_raises():
    rows = _curve("2018-12-01", "2020-01-31", first_listed={"2019-09": "2019-04-15"})
    fm = F.front_moves("soybeans_cbot", [{"date": "2019-03-01"}], _BAND, "2019-12-31",
                       qfn=F.fixture_query_fn({"silver_futures_eod": rows}))
    assert fm["declined"] == {"2019-03-01": "contract_not_live_at_open"}

    def _boom(sql):
        raise RuntimeError("mirror down")
    bad = F.front_moves("soybeans_cbot", [{"date": "2019-03-01"}], _BAND, "2019-12-31", qfn=_boom)
    assert bad["declined"] == {"2019-03-01": "read_error"} and bad["reads"] == 1


def test_Z12_every_priced_session_is_on_or_before_the_as_of_B14():
    rows = _curve("2018-12-01", "2020-06-30")
    fm = F.front_moves("soybeans_cbot", [{"date": "2019-03-01"}, {"date": "2019-06-03"}], _BAND,
                       "2019-12-20", qfn=F.fixture_query_fn({"silver_futures_eod": rows}))
    assert fm["per_firing"], fm
    assert all(d <= "2019-12-20" for e in fm["per_firing"].values() for d in e["dates"])


def test_Z12_chain_outcome_per_firing_names_its_basis_and_None_is_HEAD():
    firings = [{"date": "2019-03-01"}, {"date": "2019-06-03"}, {"date": "2019-11-01"}]
    fm = F.front_moves("soybeans_cbot", firings, _BAND, "2019-12-31",
                       qfn=F.fixture_query_fn({"silver_futures_eod": _ROWS}))
    o = W.chain_outcome((), (), unit="", firings=firings, band=_BAND, declared_sign="+", per_firing=fm)
    assert o["basis"] == W.OUTCOME_CONTRACT_CYCLE and o["n"] == 2 and o["n_in"] == 3
    assert o["in_flight"] == 1 and o["pre_coverage"] == 0 and o["reads"] == fm["reads"]
    assert set(o["contracts"]) == {e["contract_month"] for e in fm["per_firing"].values()}
    assert o["window_from"] == "2019-03-01" and o["share_declared_way"] == 2
    assert all(m > 0 for m in o["moves"]), "each one-contract ramp rose over its band"
    head = W.chain_outcome([1.0, 2.0], ["2019-01-01", "2019-06-01"], unit="c", firings=[], band=_BAND)
    assert "basis" not in head and set(head) == {"n", "n_in", "median_move", "low", "high",
                                                 "share_declared_way", "unit", "scope", "window_from",
                                                 "window_to", "words", "moves"}


def _chain(firings):
    hop = W.ChainHop(contract="soybeans_cbot", driver_id="crude_oil", lag_band=_BAND)
    return types.SimpleNamespace(history={"firings": tuple(firings)}, hops=(hop,), receipt_index=0,
                                 contract="soybeans_cbot", declared_sign="+")


def test_Z12_outcome_for_reads_front_fn_when_passed_and_HEADs_tape_otherwise():
    bd = types.SimpleNamespace(tape={}, asof="2019-12-31")
    ch = _chain([{"date": "2019-03-01"}])
    head = W._outcome_for(bd, ch)
    assert head == W._outcome_for(bd, ch, front_fn=None) and "basis" not in head
    seen = []

    def _fn(slug, firings, band):
        seen.append((slug, tuple(f["date"] for f in firings), band))
        return F.front_moves(slug, firings, band, "2019-12-31",
                             qfn=F.fixture_query_fn({"silver_futures_eod": _ROWS}))
    got = W._outcome_for(bd, ch, front_fn=_fn)
    assert seen == [("soybeans_cbot", ("2019-03-01",), _BAND)]
    assert got["basis"] == W.OUTCOME_CONTRACT_CYCLE and got["n"] == 1

    def _raises(*a, **k):
        raise RuntimeError("seam failure")
    assert W._outcome_for(bd, ch, front_fn=_raises) == head, "a failing seam reads HEAD's tape"
    assert W._outcome_for(bd, _chain([]), front_fn=_fn) == W._outcome_for(bd, _chain([]))


# ---------------------------------------------------------------------------------------------------------------
# Z13 -- THE FX JOIN (feeder half)
# ---------------------------------------------------------------------------------------------------------------
def _fx_rows(dates, value=0.92):
    return [{"data_date": d, "date": d, "value": str(value + i * 0.001), "unit": "EUR per USD (ECB via Frankfurter)"}
            for i, d in enumerate(dates)]


@pytest.fixture
def _fx_producer(monkeypatch):
    monkeypatch.setattr(REG, "fx_metric_for", lambda c: {"EUR": "eur_usd", "MYR": "myr_usd"}.get(c),
                        raising=False)


def test_Z13_one_fx_row_per_non_usd_currency_the_newest_on_or_before_the_session_and_the_asof(_fx_producer):
    qfn = F.fixture_query_fn({"silver_fred_fx": _fx_rows(["2026-09-21", "2026-09-22", "2026-09-23",
                                                          "2026-09-25"])})
    got = F.fx_rows(["EUR", "USD", "eur"], "2026-09-24", qfn=qfn, on_or_before="2026-09-23")
    assert set(got) == {"EUR"}, "USD needs no row; one row per currency"
    e = got["EUR"]
    assert e["status"] == "ok" and e["date"] == "2026-09-23" and e["metric"] == "eur_usd"
    assert e["rate"] == pytest.approx(0.922) and e["unit"].startswith("EUR per USD") and e["card"] == F.FX_TABLE
    assert len(qfn.calls) == 1
    # the spread's session AFTER the as-of never reads past the as-of (B14)
    late = F.fx_rows(["EUR"], "2026-09-24", qfn=qfn, on_or_before="2026-09-30")["EUR"]
    assert late["date"] == "2026-09-23" and late["on_or_before"] == "2026-09-24"


def test_Z13_a_stale_rate_and_a_missing_series_are_NAMED_never_used(_fx_producer):
    qfn = F.fixture_query_fn({"silver_fred_fx": _fx_rows(["2026-09-17", "2026-09-18"])})
    got = F.fx_rows(["EUR", "BRL"], "2026-09-24", qfn=qfn, on_or_before="2026-09-23")
    assert got["EUR"]["status"] == "fx_stale" and got["EUR"]["date"] == "2026-09-18"
    assert got["BRL"]["status"] == "no_fx_series" and got["BRL"]["metric"] == ""
    # a Monday spread takes the Friday rate: one session of a weekday card
    mon = F.fx_rows(["EUR"], "2026-09-30", qfn=F.fixture_query_fn({"silver_fred_fx": _fx_rows(["2026-09-25"])}),
                    on_or_before="2026-09-28")["EUR"]
    assert mon["status"] == "ok" and mon["date"] == "2026-09-25"


def test_Z13_Z12_no_executor_handed_in_reads_through_the_BOARDS_executor_never_query_runs_default(
        _fx_producer, monkeypatch):
    """``query.run``'s default executor carries the per-request fallback ``board_query_fn`` exists to refuse; a
    caller that hands no executor gets the board's own, for the FX join and the past-time front reads alike."""
    from leviathan.graphrag.numbers import query as Q

    def _forbidden(*a, **k):
        raise AssertionError("the default executor was reached")
    monkeypatch.setattr(Q, "default_query_fn", _forbidden)
    seen = []

    def _board():
        def _run(sql):
            seen.append(sql)
            return []
        return _run
    monkeypatch.setattr(F, "board_query_fn", _board)
    F.fx_rows(["EUR"], "2026-09-24", qfn=None, on_or_before="2026-09-23")
    F.front_moves("soybeans_cbot", [{"date": "2019-03-01"}], _BAND, "2019-12-31", qfn=None)
    assert len(seen) == 2 and "silver_fred_fx" in seen[0] and "silver_futures_eod" in seen[1]


def test_Z13_a_registry_without_the_producer_reads_nothing_and_says_read_error(monkeypatch):
    monkeypatch.delattr(REG, "fx_metric_for", raising=False)

    def _never(sql):
        raise AssertionError("no metric producer, no read")
    got = F.fx_rows(["EUR"], "2026-09-24", qfn=_never, on_or_before="2026-09-23")
    assert got["EUR"]["status"] == "read_error" and got["EUR"]["rate"] is None
    assert set(F.FX_ROW_STATUS) == {"ok", "no_fx_series", "fx_stale", "read_error"}


# ---------------------------------------------------------------------------------------------------------------
# Z22 -- THE WASDE THEN-CURRENT LINE AS ITS OWN ROW
# ---------------------------------------------------------------------------------------------------------------
def _held(tc, state="held_as_last_revised"):
    return StateRow(key=SeriesKey(ref="psd_ending_stock_su_ratio", commodity="soybeans_cbot", country="United States"),
                    table="silver_psd", level=0.13, level_date="2020", asof="2024-03-01",
                    recency={F.RETENTION_KEY: {"state": state, "then_current": tc}})


_TC = {"read": True, "table": "silver_wasde", "metric": "ending_stocks", "commodity": "soybeans",
       "country": "United States", "period": "2023/24", "ordinal": 2023, "value": "315", "unit": "Million Bushels",
       "knowledge_date": "2024-02-08", "role": "projection", "newer": "2023/24", "newer_on": "USDA WASDE"}


def test_Z22_the_then_current_line_is_its_own_row_with_its_own_identity_figure_release_and_role():
    st = F.then_current_state(_held(dict(_TC)))
    assert st is not None and st.status == "ok" and st.reads == 0
    assert (st.key.ref, st.key.commodity, st.key.country, st.key.metric) == (
        "silver_wasde", "soybeans", "United States", "ending_stocks")
    assert st.table == "silver_wasde" and st.level == 315.0 and st.unit == "Million Bushels"
    assert st.level_date == "2023/24" and st.knowledge_date == "2024-02-08" and st.role == "projection"
    assert st.asof == "2024-03-01"


def test_Z22_no_row_where_the_source_is_not_held_or_the_line_is_unreadable():
    assert F.then_current_state(_held(dict(_TC), state="vintaged")) is None
    assert F.then_current_state(_held({"read": True, "why": "stale_line", "period": "2011/12"})) is None
    assert F.then_current_state(_held({"read": False, "why": "no_pool"})) is None
    assert F.then_current_state(_held(dict(_TC, value="NA"))) is None
    assert F.then_current_state(StateRow(key=SeriesKey(ref="x"))) is None
