"""FIX SITTING 4 (launched 09-29), LANE W -- walk.py / feeders.py (CONTRACT C4-1, C4-2, C4-12, C4-18).

Every test runs OFFLINE: canned rows through ``feeders.fixture_query_fn`` (the REAL compiler first), hand-built quorum
members over a stub graph, and a stub resolver for the anchor call. Each item's FACT and CHECK are named in BUILD_W.md;
the pins guard the facts the board now serves:

* C4-1 (F4-1): a session is a PRICE only when its settle is one (``feeders.session_price``, the ingest law read at the
  tape). A change whose base session carries no price DECLINES by name (``base_not_a_price`` + ``base_date``) and is
  never minted from a zero (the as-of probe served ``settle change over 63 sessions = $3,630.00`` = the level); the
  percentile ranks priced sessions only; a past-time band whose opening or closing session is not a price declines.
  A NULL settle is absent, as it always was (a GLBX holiday row is no session).
* C4-2 (F4-2): the tail rider's month guard at as-of 2026-04-15 reads 202603 with GRAPHRAG_YM_PUBLICATION_LAG on and
  202604 off -- the documented leak and its existing closure.
* C4-12 (R4-4 a, W4-1, W4-2): nothing dated read and read-but-none-in-force are two reasons; an in-force action is read
  by its record's declared polarity, else named unread; a regime member counted by its action carries ``counted_by``;
  a state_marker read on a series whose binding declares no orientation is named unread, never counted.
* C4-18 (S4 call site): every anchor seat goes through ``board.priced_anchor`` once; a priced slug is HEAD's anchor
  byte for byte; the question's product class rides only the seats the question named.
"""
import dataclasses
import datetime as _dt
import types

from leviathan.graphrag.state import board as B
from leviathan.graphrag.state import feeders as F
from leviathan.graphrag.state import walk as W
from leviathan.graphrag.state.lagbands import parse_lag

# ---------------------------------------------------------------------------------------------------------------
# C4-1 (F4-1) -- A SESSION IS A PRICE ONLY WHEN ITS SETTLE IS ONE
# ---------------------------------------------------------------------------------------------------------------
CYCLE_SLUG = "french_wheat_matif"      # delivery_cycle: the rule reads no activity metric (test_state_tape's own)


def _sessions(n, last="2026-09-04"):
    end = _dt.date.fromisoformat(last)
    return [(end - _dt.timedelta(days=k)).isoformat() for k in range(n)][::-1]


def _tape_rows(sessions, expiries, base=250.0, zero=(), null=()):
    """test_state_tape's own ramp (0.5 per session, 2.0 per expiry); ``zero`` / ``null`` put a settle of 0.0 / None
    on the FRONT expiry (``expiries[0]``) at those sessions -- the ICE bar path's zero close and a NULL row."""
    out = []
    for i, d in enumerate(sessions):
        for j, cm in enumerate(expiries):
            v = str(round(base + i * 0.5 + j * 2.0, 2))
            if j == 0 and d in zero:
                v = "0.0"
            if j == 0 and d in null:
                v = None
            out.append({"value": v, "knowledge_date": d, "contract_month": cm, "settle_kind": "official",
                        "currency": "EUR", "unit": "EUR/t"})
    return out


def _tape(rows, asof="2026-09-08"):
    return F.tape_state(CYCLE_SLUG, asof, qfn=F.fixture_query_fn({"silver_futures_eod": rows}))


def test_C41_session_price_is_the_ingest_law_read_at_the_tape_and_a_NULL_stays_absent():
    assert F.session_price({"value": "3,630.00"}) == 3630.0
    assert F.session_price({"value": 1328.25}) == 1328.25
    for v in ("0.0", 0, "-1.5", "nan", "inf", None, "", "n/a"):
        assert F.session_price({"value": v}) is None, v
    # the AXIS test is HEAD's parse: a number (zero included) is a session; a NULL is absent
    assert F._settle_number({"value": "0.0"}) == 0.0 and F._settle_number({"value": None}) is None
    assert F.TAPE_CHANGE_DECLINES == ("base_not_a_price",)
    assert F.FRONT_MOVE_DECLINES[:6] == ("pre_coverage", "front_decline", "contract_expired_in_band", "in_flight",
                                         "read_error", "contract_not_live_at_open"), "APPEND-NEVER-SORT"
    assert F.FRONT_MOVE_DECLINES[6:] == ("base_not_a_price",)


def test_C41_a_change_whose_BASE_is_a_zero_close_DECLINES_by_name_and_is_never_the_level():
    """THE AS-OF PROBE'S [N55]: the 64th session back carried settle 0.0 and HEAD printed the 63-session change as the
    level itself (end - 0). The window is never re-based on an older session: it declines, naming the session."""
    ss = _sessions(120)
    t = _tape(_tape_rows(ss, ["2026-12", "2027-03"], zero={ss[-64]}))
    ch = {c["window"]: c for c in t.changes}
    c63 = ch["63 sessions"]
    assert c63["declined"] is True and c63["reason"] == "base_not_a_price"
    assert c63["base_date"] == ss[-64] and c63["from_date"] == ss[-64] and c63["delta"] is None
    assert c63["delta"] != t.level
    # the windows whose base is priced are HEAD's own figures (the ramp: 0.5 per session)
    assert [ch[w]["delta"] for w in ("1 session", "5 sessions", "21 sessions")] == [0.5, 2.5, 10.5]
    assert t.level == 250.0 + 119 * 0.5 and t.level_date == ss[-1]
    # the percentile ranks the PRICED sessions; the unpriced one is counted, never ranked
    assert t.percentile["n"] == 119 and t.coverage["n_obs"] == 119 and t.coverage["unpriced_sessions"] == 1
    assert t.status == "ok", "a base that is not a price is not a THIN tape"
    assert F.TR.re_execute_all(t.derivation, t.inputs) == [], "every served figure reproduces from its rows"
    assert all(c.get("knowledge_date") for c in t.changes if not c["declined"])


def test_C41_a_zero_INSIDE_a_window_is_no_value_and_moves_no_priced_window():
    ss = _sessions(120)
    head = _tape(_tape_rows(ss, ["2026-12"]))
    t = _tape(_tape_rows(ss, ["2026-12"], zero={ss[-30]}))
    assert [c["delta"] for c in t.changes] == [c["delta"] for c in head.changes] == [0.5, 2.5, 10.5, 31.5]
    assert [c["from_date"] for c in t.changes] == [c["from_date"] for c in head.changes]
    assert t.percentile["n"] == head.percentile["n"] - 1 and t.coverage["unpriced_sessions"] == 1


def test_C41_a_zero_on_the_NEWEST_session_is_never_the_level():
    ss = _sessions(120)
    t = _tape(_tape_rows(ss, ["2026-12"], zero={ss[-1]}))
    assert t.level == 250.0 + 118 * 0.5 and t.level_date == ss[-2], "the level is the newest PRICED session"
    assert all(c["to_date"] == ss[-2] for c in t.changes), "every change ends at the printed settle"
    assert [c["delta"] for c in t.changes] == [0.5, 2.5, 10.5, 31.5]
    assert t.coverage["unpriced_sessions"] == 1


def test_C41_a_NULL_settle_is_ABSENT_as_it_always_was_and_a_tape_with_no_unpriced_session_is_HEADs():
    """A GLBX holiday row (NULL settle, no volume) is no session: counting it would shorten every window across it
    (MEASURED on CME palm 2026-06-19 / 07-03 / 09-07). HEAD dropped it; so does the fix, and adds no key."""
    ss = _sessions(120)
    clean = _tape(_tape_rows(ss, ["2026-12"]))
    assert "unpriced_sessions" not in clean.coverage
    holed = _tape(_tape_rows(ss, ["2026-12"], null={ss[-10]}))
    assert "unpriced_sessions" not in holed.coverage
    assert holed.changes[2]["from_date"] == ss[-23], "the NULL session is skipped exactly as HEAD skipped it"


# the past-time front moves (sitting 3's Z12 curve: weekday sessions, each expiry its own ramp)
_CYCLE = (1, 3, 5, 7, 8, 9, 11)


def _curve(start, end, *, zero=None):
    """``zero`` = ``{(session, expiry)}`` carrying settle 0.0."""
    exps = ["%04d-%02d" % (y, m) for y in range(2018, 2023) for m in _CYCLE]
    d, d1, i, out = _dt.date.fromisoformat(start), _dt.date.fromisoformat(end), 0, []
    while d <= d1:
        if d.weekday() < 5:
            s = d.isoformat()
            live = [e for e in exps if s[:7] < e <= "%04d-%02d" % (d.year + 1, d.month)]
            for rank, e in enumerate(live):
                v = "0.0" if (s, e) in (zero or set()) else str(900.0 + 10.0 * exps.index(e) + 0.5 * i)
                out.append({"value": v, "knowledge_date": s, "contract_month": e, "settle_kind": "official",
                            "currency": "USD", "unit": "US cents/bushel", "open_interest": 100000 - 5000 * rank,
                            "volume": 40000 - 2000 * rank})
            i += 1
        d += _dt.timedelta(days=1)
    return out


_BAND = parse_lag("0-2 quarters")


def _fm(zero=None):
    rows = _curve("2018-12-01", "2020-01-31", zero=zero)
    return F.front_moves("soybeans_cbot", [{"date": "2019-03-01"}], _BAND, "2019-12-31",
                         qfn=F.fixture_query_fn({"silver_futures_eod": rows}))


def test_C41_a_past_time_band_whose_OPENING_or_CLOSING_session_is_a_zero_close_declines_by_name():
    head = _fm()
    e = head["per_firing"]["2019-03-01"]
    cm, first, last = e["contract_month"], "2019-03-01", e["dates"][-1]
    opened = _fm(zero={(first, cm)})
    assert opened["declined"] == {"2019-03-01": "base_not_a_price"} and not opened["per_firing"]
    closed = _fm(zero={(last, cm)})
    assert closed["declined"] == {"2019-03-01": "base_not_a_price"}, "a zero close would be a phantom -100%"
    assert opened["reads"] == closed["reads"] == head["reads"] == 2


def test_C41_a_zero_INSIDE_a_band_is_never_a_value_and_the_bands_move_is_unchanged():
    head = _fm()
    e = head["per_firing"]["2019-03-01"]
    mid = e["dates"][40]
    got = _fm(zero={(mid, e["contract_month"])})["per_firing"]["2019-03-01"]
    assert mid not in got["dates"] and 0.0 not in got["values"]
    assert (got["dates"][0], got["values"][0], got["dates"][-1], got["values"][-1]) == \
        (e["dates"][0], e["values"][0], e["dates"][-1], e["values"][-1])
    o_h = W.chain_outcome((), (), unit="", firings=[{"date": "2019-03-01"}], band=_BAND, declared_sign="+",
                          per_firing=head)
    o_t = W.chain_outcome((), (), unit="", firings=[{"date": "2019-03-01"}], band=_BAND, declared_sign="+",
                          per_firing=_fm(zero={(mid, e["contract_month"])}))
    assert o_h["moves"] == o_t["moves"]


# ---------------------------------------------------------------------------------------------------------------
# C4-2 (F4-2) -- THE TAIL RIDER'S MONTH GUARD, FLAG ON AND OFF
# ---------------------------------------------------------------------------------------------------------------
def _tail_sql(monkeypatch, on: bool) -> str:
    from leviathan.graphrag.numbers import cascade as C
    if on:
        monkeypatch.setenv("GRAPHRAG_YM_PUBLICATION_LAG", "on")
    else:
        monkeypatch.delenv("GRAPHRAG_YM_PUBLICATION_LAG", raising=False)
    got = []
    rec = C.fetch_window(lambda sql: got.append(sql) or [], table=C._WEATHER_Z_TABLE,
                         metric="tmax_anomaly" + C._TAIL_SUFFIX, commodity="cocoa", country="West Africa",
                         t1="2025-04-15", t2="2026-04-15", asof="2026-04-15", agg="latest", period_type="date")
    assert rec["status"] != "error", rec
    assert len(got) == 1
    return got[0]


def test_C42_the_tail_riders_month_guard_is_the_lagged_month_with_the_flag_and_the_as_of_month_without(
        monkeypatch):
    """F4-2 (the as-of probe's [N76], a basin tail share of APRIL 2026 served at as-of 2026-04-15, known 2026-05-05):
    flag off the guard admits the as-of's own month from its first day (202604 -- the documented leak, O-S3-2); flag
    on it is the newest month whose declared lag (5 days after month-end) has passed (202603)."""
    import re
    off, on = _tail_sql(monkeypatch, False), _tail_sql(monkeypatch, True)
    bound = lambda sql: min(int(x) for x in re.findall(r"\(year \* 100 \+ month\) <= (\d{6})", sql))  # noqa: E731
    assert bound(off) == 202604, "flag off: the as-of's own month from its first day (the documented leak)"
    assert bound(on) == 202603, "flag on: the newest month whose declared lag has passed"


# ---------------------------------------------------------------------------------------------------------------
# C4-12 -- THE QUORUM MEMBER'S REASON (R4-4 a, W4-1, W4-2)
# ---------------------------------------------------------------------------------------------------------------
def _graph(direction="+", drivers=None, requires=2):
    drivers = drivers or {"ban": ("+", "policy_event"), "stocks": ("-", "supply_state"),
                          "collapse": ("+", "state_marker")}
    ds = [types.SimpleNamespace(id=d, sign=s, type=t) for d, (s, t) in drivers.items()]
    sig = types.SimpleNamespace(name="squeeze", direction=direction, drivers=tuple(drivers),
                                requires_any_n_of=requires, interactions=())
    return types.SimpleNamespace(contracts={"rice": types.SimpleNamespace(drivers=ds, convergence=[sig])})


def _row(graph=None, *, sides=None, measured=None, **kw):
    g = graph or _graph()
    ids = {d for d in g.contracts["rice"].convergence[0].drivers}
    return W.convergence_rows(g, "rice", ids, loud_k=16, measured_ids=measured if measured is not None else ids,
                              sides=sides if sides is not None else {"stocks": -1, "collapse": +1}, **kw)[0]


_UNDECLARED = ("marker_orientation_undeclared", "regime_action_polarity_undeclared")


def _partition(r):
    """THE FOUR POPULATIONS: ``matched`` (the ORDERING count), ``against``, ``unsided`` and the members the walk cannot
    orient (an undeclared orientation / polarity) -- disjoint; the last are NAMED in ``matched_unmeasured`` and are in
    no verdict list and not in the ordering count."""
    m, a, u = set(r["matched"]), set(r.get("against") or ()), set(r.get("unsided") or ())
    und = {d for d, w in (r.get("unread_reason") or {}).items() if w in _UNDECLARED}
    assert not (m & a) and not (m & u) and not (a & u) and not (und & (m | a | u))
    assert set(r["matched_measured"]) | set(r["matched_unmeasured"]) == m | und
    assert not (set(r["matched_measured"]) & set(r["matched_unmeasured"]))
    assert set(r.get("unread_reason") or {}) <= set(r["matched_unmeasured"])
    assert set(r.get("counted_by") or {}) <= set(r["matched_measured"])
    assert r["n_matched"] == len(r["matched"]), "matched and n_matched agree (review round 2, MAJOR 5)"


def test_C412_R44a_nothing_dated_read_and_read_but_none_in_force_are_TWO_reasons():
    none_read = _row(regime={"ban": {"in_force": None, "action": None, "why": "none"}})
    assert none_read["unread_reason"]["ban"] == "regime_action_none_read"
    read_none = _row(regime={"ban": {"in_force": False, "action": None, "why": "report_in_reach"}})
    assert read_none["unread_reason"]["ban"] == "regime_action_unread"
    for r in (none_read, read_none):
        assert "ban" in r["matched_unmeasured"] and "ban" not in r["matched_measured"]
        _partition(r)
    assert W.QUORUM_UNREAD_REASONS[:2] == ("regime_action_unread", "held_as_last_revised"), "APPEND-NEVER-SORT"
    assert W.QUORUM_UNREAD_REASONS[2:] == ("regime_action_none_read", "marker_orientation_undeclared",
                                           "regime_action_polarity_undeclared")


def test_C412_W42_an_action_IN_FORCE_with_no_declared_polarity_is_NAMED_never_counted():
    """S4-E, the probe palm page: an in-force import-tariff action counted as the node present, listed with the z of
    its EFFECT series -- a cut and a hike read alike. No record declares a direction today, so it is named."""
    r = _row(regime={"ban": {"in_force": True, "action": {"event_date": "2026-01-01"}, "why": "regime_in_force",
                             "polarity": None}})
    assert r["unread_reason"]["ban"] == "regime_action_polarity_undeclared"
    assert "ban" not in r["matched_measured"] and "counted_by" not in r
    assert "ban" in r["matched_unmeasured"] and "ban" not in r["matched"], "named, and no weight in the order"
    _partition(r)
    # a regime dict with no polarity key at all (HEAD's shape) reads the same: undeclared
    r2 = _row(regime={"ban": {"in_force": True, "action": {}, "why": "regime_in_force"}})
    assert r2["unread_reason"]["ban"] == "regime_action_polarity_undeclared"


def test_C412_W42_a_DECLARED_polarity_reads_the_node_present_or_absent_and_the_count_names_its_action():
    act = {"event_date": "2026-01-01", "kind": "regime_in_force"}
    up = _row(regime={"ban": {"in_force": True, "action": act, "why": "regime_in_force", "polarity": "+"}})
    assert "ban" in up["matched_measured"] and "ban" not in (up.get("unread_reason") or {})
    assert up["counted_by"] == {"ban": {"action_date": "2026-01-01", "e_handle": None, "polarity": "+"}}
    _partition(up)
    lifted = _row(regime={"ban": {"in_force": True, "action": act, "why": "regime_in_force", "polarity": "-"}})
    assert lifted["against"] == ("ban",) and "counted_by" not in lifted, "a lifting is not the policy in force"
    flat = _row(regime={"ban": {"in_force": True, "action": act, "why": "regime_in_force", "polarity": "0"}})
    assert flat["unsided"] == ("ban",)


def test_C412_W42_regime_state_reports_the_records_declared_polarity_and_None_where_it_declares_none(
        monkeypatch):
    bd = types.SimpleNamespace(asof="2026-09-24")
    row = B.NodeRow(contract="rough_rice_cbot", driver_id="India_export_ban", type="policy_event", sign="+",
                    lag="0-1 quarters", lag_band=parse_lag("0-1 quarters"))
    rec = {"date": "2026-03-10", "event_date": "2026-03-01", "event_date_precision": "day",
           "text": "the ministry lifted the ban", "source": "fixture", "direction_sign": "-"}
    got = W.regime_state(bd, row, receipts={row.key: [rec]})
    assert got["in_force"] is True and got["polarity"] is None, "no record field is declared: nothing is read"
    assert W.REGIME_ACTION_POLARITY_FIELD is None
    monkeypatch.setattr(W, "REGIME_ACTION_POLARITY_FIELD", "direction_sign")
    assert W.regime_state(bd, row, receipts={row.key: [rec]})["polarity"] == "-"
    # the text is never read: a declared field with no value is undeclared whatever the sentence says
    assert W.regime_state(bd, row, receipts={row.key: [dict(rec, direction_sign="")]})["polarity"] is None
    plain = B.NodeRow(contract="rough_rice_cbot", driver_id="drought", type="weather_state", sign="+")
    assert W.regime_state(bd, plain) == {"in_force": None, "action": None, "why": "not_regime"}


def test_C412_W41_a_READ_marker_whose_binding_declares_no_orientation_is_NAMED_never_counted_against_or_unsided():
    """Rice counted "tenderable collapse" off US ending stocks at the 75th percentile (ample stocks) while the
    channel was "NOT in its tail". The graph binds markers to series of their INVERSE quantity and declares no
    orientation, so the series' tail is no reading of the condition."""
    for side in (+1, -1, 0):
        r = _row(sides={"stocks": -1, "collapse": side})
        assert r["unread_reason"]["collapse"] == "marker_orientation_undeclared"
        assert "collapse" in r["matched_unmeasured"]
        assert "collapse" not in r["matched"] + r.get("against", ()) + r.get("unsided", ())
        _partition(r)
    # every other member is decided exactly as before (stocks: '-' in a '+' pattern, read low -> counted)
    assert "stocks" in _row()["matched_measured"]
    # a marker with NO tail to read (not in sides) and an UNREAD marker keep HEAD's path
    no_tail = _row(sides={"stocks": -1})
    assert "collapse" in no_tail["matched_measured"] and "collapse" not in (no_tail.get("unread_reason") or {})
    unread = _row(measured={"stocks"})
    assert "collapse" in unread["matched_unmeasured"] and "collapse" not in (unread.get("unread_reason") or {})


def test_C412_an_UNDECLARED_member_adds_no_weight_to_its_patterns_ORDERING_count():
    """MEASURED on the first cut (it put the undeclared member in ``matched``, as Z10 does for a regime member with no
    action): a marker HEAD read AGAINST joined the ordering count, 22 of 774 quorum rows on the 53 banked boards
    crossed their threshold on names the page does not count, and the watch's admission floor drew 11 rows as "a
    declared pattern at its own threshold". The ordering count never rises by a member the walk cannot orient."""
    for side in (+1, -1, 0):
        base = _row(sides={"stocks": -1, "collapse": side}, measured={"stocks", "ban"})   # collapse unread: HEAD
        got = _row(sides={"stocks": -1, "collapse": side})
        assert got["n_matched"] <= base["n_matched"] + 0, (side, got["n_matched"], base["n_matched"])
        assert "collapse" not in got["matched"]


def test_C412_W41_a_DECLARED_orientation_reads_the_series_tail_in_the_markers_own_direction(monkeypatch):
    monkeypatch.setattr(W, "MARKER_ORIENTATION_FIELD", "orientation")
    g = _graph(drivers={"stocks": ("-", "supply_state"), "collapse": ("+", "state_marker")})
    g.contracts["rice"].drivers[1].orientation = "-"          # the series measures the INVERSE quantity
    low = _row(g, sides={"stocks": -1, "collapse": -1})      # stocks LOW = collapse present
    assert "collapse" in low["matched_measured"]
    high = _row(g, sides={"stocks": -1, "collapse": +1})     # stocks HIGH = no collapse
    assert high["against"] == ("collapse",)
    g.contracts["rice"].drivers[1].orientation = "+"
    assert "collapse" in _row(g, sides={"stocks": -1, "collapse": +1})["matched_measured"]
    g.contracts["rice"].drivers[1].orientation = "0"          # orients nothing -> undeclared
    assert _row(g)["unread_reason"]["collapse"] == "marker_orientation_undeclared"


def test_C412_HEAD_byte_for_byte_where_no_marker_is_read_and_no_regime_or_held_fact_is_passed():
    g = _graph(drivers={"stocks": ("-", "supply_state"), "flow": ("+", "trade_flow")})
    ids = {"stocks", "flow"}
    r = W.convergence_rows(g, "rice", ids, loud_k=16, measured_ids=ids, sides={"stocks": -1, "flow": 1})[0]
    assert "unread_reason" not in r and "counted_by" not in r
    assert set(r["matched_measured"]) == ids


# ---------------------------------------------------------------------------------------------------------------
# C4-18 -- THE ANCHOR SEAT GOES THROUGH THE PRICED-ANCHOR RESOLVER
# ---------------------------------------------------------------------------------------------------------------
def _resolver(calls):
    def _pa(slug, *, graph=None, question_class=None):
        calls.append((slug, question_class))
        if slug == "soybeans":
            return {"contract": "soybeans_cbot", "reason": "one_priced_contract",
                    "note": "the priced contract of soybeans", "candidates": ("soybeans_cbot",)}
        if slug == "french_rapeseed_matif" and question_class == "vegetable_oils":
            return {"contract": "rapeseed_oil_zce", "reason": "class_named", "note": "the oil the question names",
                    "candidates": ("rapeseed_oil_zce",)}
        if slug == "rapeseed":
            return {"contract": "rapeseed", "reason": "several_priced", "note": "two priced contracts",
                    "candidates": ("french_rapeseed_matif", "canola_ice")}
        return {"contract": slug, "reason": "priced", "note": "", "candidates": ()}
    return _pa


def test_C418_no_resolver_is_HEADs_anchor_set_and_a_priced_slug_is_HEADs_anchor_byte_for_byte(monkeypatch):
    kw = dict(named=("soybeans_cbot",), contracts=("corn_cbot", "soybeans"), max_contracts=2)
    monkeypatch.delattr(B, "priced_anchor", raising=False)
    head = W.resolve_anchors(**kw)
    assert [a.contract for a in head] == ["soybeans_cbot", "corn_cbot", "soybeans"] or         {a.contract for a in head} == {"soybeans_cbot", "corn_cbot", "soybeans"}, "HEAD seats a seed as given"
    monkeypatch.setattr(B, "priced_anchor", _resolver([]), raising=False)
    got = W.resolve_anchors(named=("soybeans_cbot",), contracts=("corn_cbot",), max_contracts=2)
    monkeypatch.delattr(B, "priced_anchor", raising=False)
    assert got == W.resolve_anchors(named=("soybeans_cbot",), contracts=("corn_cbot",), max_contracts=2),         "every priced seat is HEAD's anchor, field for field"


def test_C418_a_generic_slug_seats_its_priced_contract_with_the_resolvers_note_and_collapses(monkeypatch):
    calls = []
    monkeypatch.setattr(B, "priced_anchor", _resolver(calls), raising=False)
    got = W.resolve_anchors(named=("soybeans",), contracts=("soybeans_cbot", "corn_cbot"), max_contracts=1)
    by = {a.contract: a for a in got}
    assert "soybeans" not in by and by["soybeans_cbot"].source == "named" and by["soybeans_cbot"].named
    assert by["soybeans_cbot"].note == "the priced contract of soybeans"
    assert "corn_cbot" in by, "the inferred seat is not spent on a seed that resolves to a named anchor"
    kept = W.resolve_anchors(named=("rapeseed",))
    assert [a.contract for a in kept] == ["rapeseed"] and kept[0].note == "two priced contracts"


def test_C418_the_questions_product_class_rides_ONLY_the_seats_the_question_named(monkeypatch):
    calls = []
    monkeypatch.setattr(B, "priced_anchor", _resolver(calls), raising=False)
    got = W.resolve_anchors(contracts=("malaysian_crude_palm_oil_cme", "french_rapeseed_matif"),
                            attached_event="french_rapeseed_matif", question_class="vegetable_oils")
    by = {a.contract: a for a in got}
    assert by["french_rapeseed_matif"].source == "attached_event", "an FE gesture is resolved with no class"
    assert ("french_rapeseed_matif", None) in calls
    got2 = W.resolve_anchors(contracts=("malaysian_crude_palm_oil_cme", "french_rapeseed_matif"),
                             question_class="vegetable_oils")
    assert {a.contract for a in got2} == {"malaysian_crude_palm_oil_cme", "rapeseed_oil_zce"}
    assert ("french_rapeseed_matif", "vegetable_oils") in calls


def test_C418_a_resolver_that_raises_keeps_HEADs_seat(monkeypatch):
    def _boom(slug, **kw):
        raise RuntimeError("registry unreadable")
    monkeypatch.setattr(B, "priced_anchor", _boom, raising=False)
    assert [a.contract for a in W.resolve_anchors(named=("soybeans",))] == ["soybeans"]


def test_C418_the_resolution_rides_the_anchor_where_lane_Ss_Anchor_declares_the_traces_names(monkeypatch):
    @dataclasses.dataclass(frozen=True)
    class _A(B.Anchor):
        seed: str = ""
        reason: str = ""
    monkeypatch.setattr(B, "Anchor", _A)
    monkeypatch.setattr(B, "priced_anchor", _resolver([]), raising=False)
    got = W.resolve_anchors(named=("soybeans", "corn_cbot"))
    by = {a.contract: a for a in got}
    assert (by["soybeans_cbot"].seed, by["soybeans_cbot"].reason) == ("soybeans", "one_priced_contract")
    assert (by["corn_cbot"].seed, by["corn_cbot"].reason) == ("", ""), "a priced seat is HEAD's anchor"


def test_every_new_reason_word_is_a_closed_ascii_snake_word():
    for w in W.QUORUM_UNREAD_REASONS + F.TAPE_CHANGE_DECLINES + F.FRONT_MOVE_DECLINES:
        assert w == w.lower() and w.replace("_", "").isalpha(), w
    assert len(set(W.QUORUM_UNREAD_REASONS)) == len(W.QUORUM_UNREAD_REASONS)
    assert len(set(F.FRONT_MOVE_DECLINES)) == len(F.FRONT_MOVE_DECLINES)
