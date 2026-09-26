"""THE 09-26 FIX SITTING, LANE W (state/walk.py, state/feeders.py, state/board.py) -- the pins.

W-1 the point-in-time ACTION LEDGER per regime node (D1, the tariff turn); W-2 the RECEIPT IDENTITY (D2,
the cocoa coffee report); W-3 the SUBJECT and the SEAT need the question's own hop or a SIGNED terminal
(D4); W-4 STALE PERIODS out of TAIL and the agreements (D12); W-5 a fenced GLOBAL scope resolves to the
anchor's declared HOME and says so (D14); W-6 the ONE C8 window producer carries its ANCHOR (D11); and
P13's ``answered_by_row``.

EVERYTHING HERE IS HAND-BUILT AND OFFLINE: fake store readers stand in for the pooled pg statements, no
environment is read, nothing is spent. Every fact a pin asserts is a fact of the arm-A pages named in its
docstring; the drives on the twenty pages themselves are in lane W's evidence file (BUILD_W.md)."""
from __future__ import annotations

from leviathan.causal import schema as cs
from leviathan.graphrag import graph as G
from leviathan.graphrag.state import board as B
from leviathan.graphrag.state import feeders as F
from leviathan.graphrag.state import walk as W
from leviathan.graphrag.state.lagbands import parse_lag
from leviathan.graphrag.state.rows import SeriesKey, StateRow


# ── helpers (hand-built, the walk deck's own shapes) ─────────────────────────────────────────────────
def _st(ref, *, pct=None, z=None, level_date="2026-08-31", table="t", metric=None, cadence="monthly",
        run=None, status="ok", commodity="", country="", recency=None, **kw):
    st = StateRow(key=SeriesKey(ref=ref, commodity=commodity, country=country), status=status,
                  coverage_tier="series", table=table, metric=metric or ref, cadence=cadence, unit="t",
                  narrate_unit="t", level=1.0, level_date=level_date, knowledge_date="2026-09-01",
                  z=None if z is None else {"value": z, "window_n": 120},
                  percentile=None if pct is None else {"value": pct, "n": 120},
                  run=run, changes=[{"window": "1m", "delta": 1.0, "pct": 1.0}])
    if recency is not None:
        st.recency = dict(recency)
    for k, v in kw.items():
        setattr(st, k, v)
    return st


def _row(bd, contract, driver_id, *, st=None, sign="+", lag="0-1 quarters", typ="climate_driver",
         receipts=None, loud=True):
    lbl = st.key.label() if st is not None else ""
    row = B.NodeRow(contract=contract, driver_id=driver_id, sign=sign, lag=lag, lag_band=parse_lag(lag),
                    confidence="high", mechanism="m", silver_status="available", series_key=lbl, state=st,
                    type=typ)
    row.legs["loud"] = loud
    if st is not None:
        bd.series[lbl] = st
    if receipts:
        row.receipts = {"n": len(receipts), "top": list(receipts), "status": "ok"}
    bd.rows.append(row)
    return row


def _board(*, asof="2026-09-26", anchors=("a_cbot",), horizon=None):
    return B.Board(asof=asof, mode="deep", knobs=B.board_knobs_of("deep"), horizon_months=horizon,
                   anchors=tuple(B.Anchor(contract=s, source="named") for s in anchors))


def _path(bd, contract, hops):
    bd.paths.append({"contract": contract, "seeded_by": hops[0], "ancestor": hops[0], "bottom": hops[-1],
                     "depth": len(hops) - 1, "hops": tuple(hops), "lag_band": parse_lag(""),
                     "band_is_the_ancestors_own": True, "confidence": "high", "rank": (),
                     "rendered": False, "decline": None})


def _finish(bd):
    bd.set_order(W.rank_rows(bd.rows))


def _doc(date, event, prec, text, *, source="usda_gain_oilseeds", skey=None, kind=None):
    d = {"date": date, "source": source, "source_key": skey or "text/source=%s/d=%s/doc.json" % (source, date),
         "text": text, "event_date": event, "event_date_precision": prec}
    if kind is not None:
        d["date_kind"] = kind
    return d


# ═════════════════════════════════════════════════════════════════════════════════════════════════════
# W-1 THE POINT-IN-TIME ACTION LEDGER
# ═════════════════════════════════════════════════════════════════════════════════════════════════════
def test_W1_the_ledger_keeps_only_REALISED_POINT_IN_TIME_actions_newest_EVENT_first_and_stamps_its_cost():
    """ARM A, THE TARIFF TURN (D1): the treatment page held a February-2025 duty "in force" while the store
    held the Busan easing of 2025-10-30. The ledger reads the node's slice at the as-of, independent of the
    question: a realised action is kept (its event closed on or before its own document), a forecast is not
    (W1-b), a month-floored document whose month straddles the as-of is not knowable (W1-a), an event whose
    interval closes after the as-of is not knowable, and the order is by the EVENT, never by publication
    (W1-d: a 2026 retrospective of a 2018 duty sorts at 2018)."""
    rows = {"drivers/tariff": [
        _doc("2025-11-03", "2025-10-30", "day", "The Busan deal eased tariff pressures."),
        _doc("2026-02-10", "2026-06-01", "month", "Tariffs are expected to be cut further in June."),
        _doc("2025-03-19", "2025-02-01", "month", "Beijing placed retaliatory tariffs on U.S. soybeans."),
        _doc("2026-09-01", "2026-09-01", "day", "A same-month release floored to its month.", kind="key_month"),
        _doc("2026-05-01", "2018-07-06", "day", "Looking back: the 2018 duty cut US shipments."),
        _doc("2025-11-03", "2025-10-30", "day", "The Busan deal eased tariff pressures."),   # a duplicate
    ]}
    calls = []

    def reader(pairs, *, asof, limit):
        calls.append((tuple(pairs), asof, limit))
        return {pr: rows.get(pr[0], []) for pr in pairs}

    got, stamp = F.action_ledger({("soybeans_cbot", "China_import_tariff"): ("drivers/tariff",)},
                                 asof="2026-09-26", reader=reader)
    # ONE statement per turn, and the pair carries the CONTRACT's own slice: the identity is read inside it
    assert calls == [((("drivers/tariff", "soybeans", None),), "2026-09-26", F.ACTION_LEDGER_LIMIT)], calls
    # ANCHORED on the draw's reporting country, the pair carries it and the statement binds the actor; a node
    # with no anchor is not read at all
    calls.clear()
    F.action_ledger({("soybeans_cbot", "China_import_tariff"): ("drivers/tariff",), ("corn_cbot", "x"): ("s",)},
                    asof="2026-09-26", reader=reader, anchors={("soybeans_cbot", "China_import_tariff"): "CN"})
    assert calls[0][0] == (("drivers/tariff", "soybeans", "CN"),), calls
    recs = got[("soybeans_cbot", "China_import_tariff")]
    assert [r["event_date"] for r in recs] == ["2025-10-30", "2025-02-01", "2018-07-06"], recs
    assert all(r["origin"] == F.ACTION_LEDGER_ORIGIN for r in recs)
    assert set(stamp) == {"read", "nodes", "rows", "ms", "why"} and stamp["read"] is True
    assert stamp["nodes"] == 1 and stamp["rows"] == 3 and stamp["why"] == ""


def test_W1_the_ledger_is_POINT_IN_TIME_at_a_2024_as_of_and_declines_BY_NAME_when_it_cannot_read():
    """B14 extended to ledger rows (the 2024-03-01 re-walk): nothing whose document date, floor end or event
    end is past the as-of. And a ledger that cannot read never raises and never guesses (W1-j)."""
    rows = {"s": [_doc("2024-02-15", "2024-02-10", "day", "an action in February"),
                  _doc("2024-03-01", "2024-02-20", "day", "reported on the as-of day"),
                  _doc("2024-03-01", "2024-02-01", "month", "a March release floored", kind="key_month"),
                  _doc("2024-02-29", "2024-02-01", "month", "a February action at month precision"),
                  _doc("2024-02-28", "2024-02-01", "month", "a February straddle, not yet whole"),
                  _doc("2024-03-05", "2024-02-01", "day", "published after the as-of")]}
    got, _ = F.action_ledger({("c", "d"): ("s",)}, asof="2024-03-01",
                             reader=lambda pairs, **k: {pr: rows.get(pr[0], []) for pr in pairs})
    kept = got[("c", "d")]
    assert all(r["date"] <= "2024-03-01" for r in kept)
    assert {r["text"] for r in kept} == {"an action in February", "reported on the as-of day",
                                         "a February action at month precision"}, kept
    for reader, why in ((lambda s, **k: None, "no_pool"), (lambda s, **k: 1 / 0, "read_error")):
        got, st = F.action_ledger({("c", "d"): ("s",)}, asof="2024-03-01", reader=reader)
        assert got == {} and st["read"] is False and st["why"] == why
    assert F.action_ledger({}, asof="2024-03-01")[1]["why"] == "no_nodes"
    assert F.action_ledger({("c", "d"): ("s",)}, asof="")[1]["why"] == "no_asof"


def test_W1_the_default_reader_declines_no_pool_offline_and_never_touches_the_network(monkeypatch):
    """The harness has no mirror: the pooled statement returns ``None`` before any connection is made."""
    from leviathan.graphrag import pgstore
    monkeypatch.delenv("EVIDENCE_PG_DSN", raising=False)
    monkeypatch.setattr(pgstore, "_acquire", lambda: (_ for _ in ()).throw(AssertionError("no borrow")))
    got, st = F.action_ledger({("c", "d"): ("s",)}, asof="2026-09-26")
    assert got == {} and st["why"] == "no_pool"
    got, st = F.routed_propositions([F.routed_prop_id("soybeans", {"source_key": "k", "text": "t"})])
    assert got == frozenset() and st["why"] == "no_pool"


def test_W1_merge_keeps_the_DRAW_FIRST_AND_VERBATIM_and_retrieval_never_subtracts():
    """W1-g: the draw's own objects ride through, in order; a ledger row the draw already holds is held
    once; the new ledger rows follow."""
    a = _doc("2025-03-19", "2025-02-01", "month", "Beijing placed retaliatory tariffs.")
    b = {"date": "2025-04-04", "source": "x", "text": "a report", "source_key": "k2"}
    led = [dict(a, origin=F.ACTION_LEDGER_ORIGIN), _doc("2025-11-03", "2025-10-30", "day", "Busan eased.")]
    m = W.merge_receipts([a, b], led)
    assert m[0] is a and m[1] is b and len(m) == 3 and m[2]["text"] == "Busan eased."
    assert W.merge_receipts([], []) == [] and W.merge_receipts([a], None) == [a]


def _tariff_graph():
    return G.CausalGraph({"soybeans_cbot": cs.CausalContract(contract="soybeans_cbot", drivers=[
        cs.Driver(id="China_import_tariff", type="policy_event", sign="-", mechanism="m",
                  lag="0-1 quarters"),
        cs.Driver(id="export_pace_lag", type="market_driver", sign="-", mechanism="m",
                  parents=["China_import_tariff"], lag="0-1 quarters"),
        cs.Driver(id="ending_stocks", type="market_driver", sign="-", mechanism="m",
                  parents=["export_pace_lag"], lag="0-1 quarters")])}, silver=set(), version="fx")


def _tariff_board(monkeypatch, *, ledger_rows, routed=None, state_chain=True):
    """The tariff board, hand-built: the regime node's DRAW is the treatment page's February-2025 receipt
    ([E7] "Beijing has placed retaliatory tariffs on U.S. soybeans.", reported 2025-03-19, event 2025-02 at
    month precision -- citation_resolved / sources_ledger ref 7 of the treatment trace)."""
    monkeypatch.setattr(W, "_driver_slice", lambda did: "drivers/%s" % did)
    monkeypatch.setattr(W, "_contract_slice", lambda c: "soybeans")
    g = _tariff_graph()

    def _key_fn(ref, node, *, turn_kind=""):
        from leviathan.graphrag.state.feeders import KeyPlan
        return KeyPlan(key=SeriesKey(ref=ref or node.driver.id, commodity="soybeans_cbot"), status="ok",
                       table="t", metric="m", cadence="monthly", row={"table": "t"})

    def _state_fn(ref, node):
        return (_st(ref, pct=90, z=1.5), 1)

    drawn = [_doc("2025-03-19", "2025-02-01", "month",
                  "Beijing has placed retaliatory tariffs on U.S. soybeans.",
                  skey="text/source=usda_gain_oilseeds/country=CN/d=2025-03-19/doc.json")]
    receipts = {("soybeans_cbot", "China_import_tariff"): drawn}
    calls = {"ledger": 0, "routed": 0}

    def ledger_reader(slices, *, asof, limit):
        calls["ledger"] += 1
        return {pr: list(ledger_rows) for pr in slices}

    def routed_reader(ids):
        calls["routed"] += 1
        return set(routed(ids)) if routed is not None else set(ids)

    bd = W.walk(graph=g, asof="2026-09-26", mode="deep",
                anchors=W.resolve_anchors(named=("soybeans_cbot",)), question="q",
                state_fn=_state_fn, key_fn=_key_fn, receipts=receipts, knobs=B.board_knobs_of("deep"),
                width=2, stage2=False)
    W.stage2(bd, g, state_fn=_state_fn, key_fn=_key_fn, receipts=receipts, state_chain=state_chain,
             ledger_reader=ledger_reader, routed_reader=routed_reader)
    return bd, calls, drawn


BUSAN = _doc("2025-11-03", "2025-10-30", "day", "The Busan deal eased tariff pressures on US soybeans.",
             skey="text/source=usda_gain_oilseeds/country=CN/d=2025-11-03/doc.json")
CORN_CUT = _doc("2025-11-12", "2025-11-10", "day", "China cut its additional tariff on US corn to 10 percent.",
                source="usda_gain_grain", skey="text/source=usda_gain_grain/country=CN/d=2025-11-12/doc.json")


def test_W1_the_TARIFF_regime_is_the_NEWEST_realised_action_the_STORE_holds_not_the_draws(monkeypatch):
    """THE DRIVE'S SHAPE, AS A PIN (B25 (i)): the draw holds February 2025; the ledger holds the Busan easing
    and the 2025-11-10 corn cut. The soybean tariff hop's regime is the Busan easing -- the newest realised
    action ON THIS LINK -- and the corn cut is REFUSED by the receipt identity (its document is routed to the
    corn slice, not the soybean one: W1-c). The draw is never subtracted; the ledger is read ONCE."""
    corn_on_soy = F.routed_prop_id("soybeans", CORN_CUT)

    def routed(ids):
        return {i for i in ids if i != corn_on_soy}
    bd, calls, drawn = _tariff_board(monkeypatch, ledger_rows=[BUSAN, CORN_CUT], routed=routed)
    # ONE ledger statement; the routing: one contract-slice read, and one read of the refusal candidates over
    # the router's own node universe (the corn cut is named to other markets -- never "names no market")
    assert calls == {"ledger": 1, "routed": 2}
    hop = next(h for c in bd.chains for h in c.hops if h.driver_id == "China_import_tariff")
    assert hop.event_date == "2025-10-30" and hop.event_kind in ("regime_in_force", "action_open"), hop
    assert hop.event_receipt["origin"] == F.ACTION_LEDGER_ORIGIN
    assert ("2025-11-12", CORN_CUT["source_key"]) in hop.identity_refused
    row = next(r for r in bd.rows if r.driver_id == "China_import_tariff")
    assert row.event_date == "2025-10-30", "the SB-E row and the chain read ONE merged list"
    assert row.receipts["top"][0]["text"] == drawn[0]["text"], "the draw stays first and verbatim"
    tr = bd.trace()
    assert tr["action_ledger"]["read"] is True and tr["action_ledger"]["nodes"] == 1
    assert tr["chain_counts"]["action_ledger_unread"] == 0
    assert tr["chain_counts"]["mechanism_refused"] >= 1, "a refusal is COUNTED"


THAI = _doc("2026-04-16", "2026-01-27", "day",
            "On January 27, 2026, the Thai government approved a 3-year tariff exemption for soybean imports.",
            source="usda_gain_soybean_oil",
            skey="text/source=usda_gain_soybean_oil/country=TH/publication_date=20260416/doc.json")


def test_W1_the_ledger_never_introduces_an_ACTOR_the_draw_did_not_hold(monkeypatch):
    """MEASURED ON THE STORE (the S3 ``drivers/tariff`` slice, 12,133 propositions, read-only): the slice is
    shared by every tariff actor its matchers catch, and the contract's own routing admits a Thai soybean
    tariff exemption on the soybean hop as readily as China's own duty (each sentence names soybeans). The
    node's identity (China_import_tariff) is not a store fact; the regime its DRAW already holds is -- its
    receipt's declared region, the reporting post (``country=CN`` on the treatment's [E7]). A ledger row of
    another declared region is REFUSED and counted; the draw's own actor's newer action supersedes."""
    bd, calls, drawn = _tariff_board(monkeypatch, ledger_rows=[THAI, BUSAN])
    hop = next(h for c in bd.chains for h in c.hops if h.driver_id == "China_import_tariff")
    assert hop.event_date == "2025-10-30", "the Thai action (newer, TH) never becomes China's regime"
    assert ("2026-04-16", THAI["source_key"]) in hop.identity_refused


def test_W1_a_node_whose_DRAW_holds_no_realised_action_is_NOT_extended_and_is_counted(monkeypatch):
    monkeypatch.setattr(W, "_driver_slice", lambda did: "drivers/%s" % did)
    monkeypatch.setattr(W, "_contract_slice", lambda c: "soybeans")
    bd = _board(anchors=("soybeans_cbot",))
    _row(bd, "soybeans_cbot", "China_import_tariff", st=_st("tariff", pct=90), typ="policy_event")
    report = _doc("2026-02-15", "2026-02-01", "month", "a report inside its own month")    # not realised
    merged, routed = W._ledger_and_routing(
        bd, {("soybeans_cbot", "China_import_tariff"): [report]},
        ledger_reader=lambda pairs, **k: {pr: [BUSAN] for pr in pairs}, routed_reader=lambda ids: set(ids))
    assert merged[("soybeans_cbot", "China_import_tariff")] == [report], "the draw stands, nothing added"
    assert bd.action_ledger["unanchored"] == 1


def test_W1_the_ledger_regime_WORDS_name_the_record_never_this_turns_retrieval(monkeypatch):
    """W1-f: a regime the ledger READ is never "the newest ... this turn retrieved". The words are lane R's
    ``render.REGIME_LEDGER_WORDS`` (declared once); a drawn regime keeps HEAD's words; where R's constant has
    not landed the walk keeps HEAD's words and says nothing new."""
    from leviathan.graphrag.state import render as R
    monkeypatch.setattr(R, "REGIME_LEDGER_WORDS",
                        "the newest dated policy action this record holds on this link is dated %s", raising=False)
    bd, _calls, _ = _tariff_board(monkeypatch, ledger_rows=[BUSAN])
    ch = next(c for c in bd.chains if c.event_kind == "regime_in_force")
    assert ch.receipt_words.startswith("the newest dated policy action this record holds"), ch.receipt_words
    assert "this turn retrieved" not in ch.receipt_words
    monkeypatch.setattr(R, "REGIME_LEDGER_WORDS", "", raising=False)
    assert W.regime_ledger_words() == ""
    bd, _calls, _ = _tariff_board(monkeypatch, ledger_rows=[])
    ch = next(c for c in bd.chains if c.event_kind == "regime_in_force")
    assert "this turn retrieved" in ch.receipt_words, "a DRAWN regime keeps HEAD's words"


def test_W1_a_CHAIN_OFF_turn_reads_NO_ledger_and_its_trace_carries_no_key(monkeypatch):
    """W1-i: the read and the merge ride ``state_chain`` only; B4 (board on, chain off) moves nothing."""
    bd, calls, _ = _tariff_board(monkeypatch, ledger_rows=[BUSAN], state_chain=False)
    assert calls == {"ledger": 0, "routed": 0}
    assert "action_ledger" not in bd.trace() and bd.chains == []
    row = next(r for r in bd.rows if r.driver_id == "China_import_tariff")
    assert row.event_date == "2025-02-01", "the draw's own winner, HEAD's"


def test_W1_an_UNREADABLE_ledger_is_counted_and_the_draw_stands(monkeypatch):
    monkeypatch.setattr(W, "_driver_slice", lambda did: "drivers/%s" % did)
    monkeypatch.setattr(W, "_contract_slice", lambda c: "soybeans")
    bd = _board(anchors=("soybeans_cbot",))
    _row(bd, "soybeans_cbot", "China_import_tariff", st=_st("tariff", pct=90), typ="policy_event")
    draw = {("soybeans_cbot", "China_import_tariff"): [BUSAN]}
    merged, routed = W._ledger_and_routing(bd, draw, ledger_reader=lambda s, **k: None,
                                           routed_reader=lambda t: None)
    assert merged == draw and routed["read"] is False
    assert bd.action_ledger["why"] == "no_pool" and bd.action_ledger["nodes"] == 1


# ═════════════════════════════════════════════════════════════════════════════════════════════════════
# W-2 THE RECEIPT IDENTITY
# ═════════════════════════════════════════════════════════════════════════════════════════════════════
COFFEE_GAIN = {"date": "2026-05-20", "source": "usda_gain_coffee",
               "source_key": ("text/source=usda_gain_coffee/country=VN/publication_date=20260520/"
                              "document=coffee_annual_ho_chi_minh_city_vietnam_vm2026-0016/document.json"),
               "text": ("El Nino typically brings warmer and drier conditions to parts of Southeast Asia, "
                        "which could reduce coffee productivity and production.")}


def test_W2_cocoas_COFFEE_GAIN_sentence_is_REFUSED_where_the_ROUTER_did_not_put_it_on_the_cocoa_slice():
    """ARM A, COCOA (D2): [E19] -- citation_resolved.E19 of the cocoa treatment trace, verbatim -- a USDA GAIN
    COFFEE report on Vietnam. MEASURED on the S3 slices (read-only): its DOCUMENT sits on the cocoa slice (one
    sentence names the "Vietnam Coffee and Cocoa Association") but THIS SENTENCE does not -- so the fact read
    is the proposition's own routing (``pgstore.prop_id``). Routing read and the sentence not on the cocoa
    slice: REFUSED. On it: admitted. Routing unread: its source's declaration (coffee contracts) cannot admit
    it on cocoa and is never a reason to refuse -- ``unread``, HEAD's admission, counted. On a robusta hop
    with the routing unread, the declaration admits it."""
    sk = "oni_climate|_global|"
    hop = W.ChainHop(contract="cocoa", driver_id="El_Nino", series_key=sk)
    read_off = W.ChainHop(contract="cocoa", driver_id="El_Nino", series_key=sk, routed_read=True,
                          routed_on=frozenset())
    read_on = W.ChainHop(contract="cocoa", driver_id="El_Nino", series_key=sk, routed_read=True,
                         routed_on=frozenset({(COFFEE_GAIN["source_key"], COFFEE_GAIN["text"])}))
    assert W.receipt_identity(COFFEE_GAIN, read_off) == ""
    assert W.receipt_identity(COFFEE_GAIN, read_on) == "contract"
    assert W.receipt_identity(COFFEE_GAIN, hop) == "unread"
    robusta = W.ChainHop(contract="robusta_coffee", driver_id="El_Nino")
    assert W.receipt_identity(COFFEE_GAIN, robusta) == "contract"


def test_W2_the_STORE_routing_admits_what_it_routes_and_a_proven_miss_is_refused():
    """``contract`` where the store's router put the SENTENCE on the hop's own contract slice; refused where
    the routing WAS read and does not place it; ``unread`` -- HEAD's admission, counted -- where the routing
    could not be read (W2-a: never a refusal on a guess). A source that declares the contract (WASDE
    declares every contract) admits by declaration ONLY where the routing could not be read."""
    doc = {"date": "2025-11-03", "source": "some_undeclared_source", "source_key": "k1", "text": "t"}
    on = W.ChainHop(contract="soybeans_cbot", driver_id="x", routed_read=True,
                    routed_on=frozenset({("k1", "t")}))
    off = W.ChainHop(contract="soybeans_cbot", driver_id="x", routed_read=True, routed_on=frozenset())
    unread = W.ChainHop(contract="soybeans_cbot", driver_id="x")
    assert W.receipt_identity(doc, on) == "contract"
    assert W.receipt_identity(doc, off) == ""
    assert W.receipt_identity(doc, unread) == "unread"
    wasde = {"date": "2024-04-11", "source": "usda_wasde", "source_key": "k2", "text": "t"}
    assert W.receipt_identity(wasde, unread) == "contract", "a declaration ADMITS where routing is unread"
    assert W.receipt_identity(wasde, off) == "", "the router's own fact decides where it was read"


E36 = {"date": "2026-04-03", "source": "usda_gain_cotton",
       "source_key": ("text/source=usda_gain_cotton/country=IN/publication_date=20260403/"
                      "document=cotton_and_products_annual_new_delhi_india_in2026-0020/document.json"),
       "text": ("If El Nino conditions emerge during 2026, they could weaken the Indian southwest monsoon, "
                "potentially resulting in below-normal rainfall.")}


def test_W2_a_sentence_naming_NO_market_joins_the_market_its_SOURCE_declares_and_no_other():
    """MEASURED ON THE STORE: the cotton page's [E36] -- an India COTTON GAIN sentence on El Nino and the
    monsoon -- is on NO commodity slice (it names no market), and its source declares cotton; refusing it on
    the cotton hop would refuse a TRUE receipt (threat W2-a). The router's own universe
    (``evidence.all_nodes()``) decides "names no market" (``ChainHop.routed_marketless``); the source's
    declaration decides WHICH market -- so the same sentence joins the cotton hop and not the cocoa hop, and
    the Vietnam coffee sentence (named to coffee, off the marketless set) still does not join cocoa."""
    pk = (E36["source_key"], E36["text"])
    cotton = W.ChainHop(contract="cotton", driver_id="El_Nino", routed_read=True,
                        routed_marketless=frozenset({pk}))
    cocoa = W.ChainHop(contract="cocoa", driver_id="El_Nino", routed_read=True,
                       routed_marketless=frozenset({pk}))
    assert W.receipt_identity(E36, cotton) == "contract"
    assert W.receipt_identity(E36, cocoa) == ""
    not_free = W.ChainHop(contract="cotton", driver_id="El_Nino", routed_read=True)
    assert W.receipt_identity(E36, not_free) == "", "a sentence the router NAMED to another market stays refused"


def test_W2_the_step5_read_finds_the_marketless_set_over_the_routers_own_node_universe(monkeypatch):
    monkeypatch.setattr(W, "_contract_slice", lambda c: "cotton")
    monkeypatch.setattr(W, "_commodity_nodes", lambda: ("cotton", "arabica_coffee", "cocoa"))
    bd = _board(anchors=("cotton",))
    _row(bd, "cotton", "El_Nino", st=_st("oni", pct=93))
    coffee = dict(COFFEE_GAIN)
    rmap = {("cotton", "El_Nino"): [E36, coffee]}
    coffee_on_arabica = F.routed_prop_id("arabica_coffee", coffee)
    merged, routed = W._ledger_and_routing(bd, rmap, ledger_reader=lambda p, **k: {},
                                           routed_reader=lambda ids: {i for i in ids if i == coffee_on_arabica})
    assert routed["read"] is True
    assert (E36["source_key"], E36["text"]) in routed["marketless"]
    assert (coffee["source_key"], coffee["text"]) not in routed["marketless"]
    hop = W.chain_hop(bd, bd.rows[0], receipts=merged, routed=routed)
    assert hop.identity_refused == (("2026-05-20", COFFEE_GAIN["source_key"]),), hop.identity_refused
    kept = [r for r in merged[("cotton", "El_Nino")]
            if W._identity_of(r, contract="cotton", cell="", routed_read=True, routed_on=frozenset(),
                              marketless=routed["marketless"])]
    assert [r["source"] for r in kept] == ["usda_gain_cotton"]


def test_W2_REGION_is_read_off_the_stores_partition_key_never_parsed_out_of_an_id():
    """``region``: a partition key the source_key declares (``country=`` / ``region=``) equal to the row's
    cell; the source id itself is looked up WHOLE and never split into words (W2-b)."""
    doc = {"date": "2026-01-01", "source": "x_y_z", "source_key": "text/source=x_y_z/country=West_Africa/d.json",
           "text": "t"}
    assert W.receipt_identity(doc, W.ChainHop(contract="cocoa", driver_id="drought",
                                              series_key="drought_z|cocoa|West Africa")) == "region"
    hop = W.ChainHop(contract="cocoa", driver_id="drought", series_key="drought_z|cocoa|West Africa",
                     routed_read=True)
    assert W.receipt_identity(doc, hop) == "region"
    assert F.source_target_contracts("usda_gain_coffee") == frozenset(
        {"arabica_coffee", "robusta_coffee", "brazilian_arabica_coffee"})
    assert F.source_target_contracts("../usda_wasde") is None and F.source_target_contracts("") is None


def test_W2_the_chain_hop_drops_a_refused_document_FROM_THAT_HOP_ONLY_and_the_count_line_counts_it():
    """W2-c: a refused receipt is recorded on the hop and folded into ``mechanism_refused`` (documents, the
    existing one population); the chain then reads "no dated document" rather than a coffee report."""
    bd = _board(anchors=("cocoa",))
    st = _st("oni", pct=93, z=2.4, commodity="_global")
    _row(bd, "cocoa", "El_Nino", st=st, receipts=[COFFEE_GAIN], lag="1-3 quarters")
    _row(bd, "cocoa", "drought", st=_st("drought", pct=3, commodity="cocoa", country="West Africa"),
         lag="1-3 quarters")
    _path(bd, "cocoa", ["El_Nino", "drought"])
    _finish(bd)
    head = W.chain_rows(bd, None, knobs=bd.knobs)
    assert any(c.receipt_kind == "mechanism" for c in head["pool"]), "HEAD took the coffee report"
    got = W.chain_rows(bd, None, knobs=bd.knobs, routed={"read": True, "on": {}})
    c = got["pool"][0]
    assert c.receipt_kind == "none" and c.receipt is None, (c.receipt_kind, c.receipt)
    assert c.hops[0].identity_refused == (("2026-05-20", COFFEE_GAIN["source_key"]),)
    assert got["counts"]["mechanism_refused"] == 1
    assert c.hops[0].to_dict()["identity_refused"] == [["2026-05-20", COFFEE_GAIN["source_key"]]]


# ═════════════════════════════════════════════════════════════════════════════════════════════════════
# W-3 THE SUBJECT AND THE SEAT
# ═════════════════════════════════════════════════════════════════════════════════════════════════════
def _chain(contract, terminal, *, score, signs=("+", "0"), ids=("a", "b"), side="unsettled"):
    hops = tuple(W.ChainHop(contract=contract, driver_id=i, series_key="%s|%s" % (contract, i),
                            measured=True, tail=0.5) for i in ids)
    c = W.Chain(contract=contract, hops=hops, terminal=terminal, depth=len(hops) - 1, score=score,
                edge_signs=tuple(signs), terms={"tail": 1.0, "reach": 10})
    c.side = side
    return c


def test_W3_an_OFF_QUESTION_chain_seats_only_through_a_SIGNED_last_link_and_keeps_its_score():
    """ARM A, RICE / COTTON (D4): CORN's stocks-to-use chain (terminal rice via ``competes_with``, cross sign
    "0") seated on the rice page. A chain whose own contract is off the question seats only where
    ``edge_signs[-1]`` is "+" or "-"; one whose own contract is on the question seats whatever its terminal
    sign. SEATING ONLY: score, terms and pool membership are untouched (W3-a), HEAD's ``off_question`` count
    is unchanged and the new refusals are their own count."""
    q = frozenset({"rough_rice_cbot"})
    rice = _chain("rough_rice_cbot", "rough_rice_cbot", score=50.0, ids=("r1", "r2"))
    corn0 = _chain("corn_cbot", "rough_rice_cbot", score=90.0, signs=("+", "0"), ids=("c1", "c2"))
    cornp = _chain("corn_cbot", "rough_rice_cbot", score=80.0, signs=("+", "-"), ids=("c3", "c4"))
    before = [(c.score, dict(c.terms)) for c in (rice, corn0, cornp)]
    out = W.chain_render_set([rice, corn0, cornp], k=3, question_markets=q)
    assert corn0 not in out["rendered"] and cornp in out["rendered"] and rice in out["rendered"]
    assert [(c.score, dict(c.terms)) for c in (rice, corn0, cornp)] == before
    assert out["counts"]["off_question"] == 0 and out["counts"]["unsigned_terminal"] == 1
    assert "unsigned_terminal" not in W.chain_render_set([rice, cornp], k=3, question_markets=q)["counts"]
    # no reach computed -> HEAD
    assert corn0 in W.chain_render_set([rice, corn0, cornp], k=3)["rendered"]


def test_W3_the_SUBJECT_needs_the_hop_that_CARRIES_it_on_a_question_market():
    """The subject test keys on the carrier hop's own contract (distance 0); a chain that merely ENDS on a
    question market no longer answers the subject (rice's "US balance sheet" answered by corn's S/U)."""
    corn = _chain("corn_cbot", "rough_rice_cbot", score=90.0, signs=("+", "-"), ids=("ending_stocks", "x"))
    ids = {"corn_cbot": frozenset({"ending_stocks"})}
    assert W._slot_subject(corn, ids, frozenset({"rough_rice_cbot"})) is False
    assert W._slot_subject(corn, ids, frozenset({"corn_cbot"})) is True
    assert W._slot_subject(corn, ids) is True, "no reach -> HEAD"


def test_P13_a_subject_whose_OWN_row_answers_it_seats_NO_group_cousins_chain():
    """ARM A, SOYOIL / PALM (D13): the pick ``soyoil_palm_premium`` heads only single-link paths; the subject
    slot seated the DCE palm-olein chain through its group cousin ``soyoil_olein_premium``. With the pick's
    OWN row served on a question market, the slot reads ``answered_by_row`` and no cousin is seated."""
    cousin = _chain("m_cbot", "m_cbot", score=30.0, signs=("+", "+"), ids=("cousin", "z"))
    top = _chain("m_cbot", "m_cbot", score=90.0, signs=("+", "+"), ids=("t1", "t2"))
    ids = {"m_cbot": frozenset({"pick", "cousin"})}
    q = frozenset({"m_cbot"})
    head = W.chain_render_set([top, cousin], k=1, subject_ids=ids, question_markets=q)
    assert head["counts"]["slot_state"]["subject"] == "seated" and cousin in head["rendered"]
    rows = {"rows": frozenset({("m_cbot", "pick")}), "own": {"m_cbot": frozenset({"pick"})}}
    got = W.chain_render_set([top, cousin], k=1, subject_ids=ids, question_markets=q, subject_rows=rows)
    assert got["counts"]["slot_state"]["subject"] == "answered_by_row" and cousin not in got["rendered"]
    # a candidate carrying the pick's OWN id still seats (P13 never refuses the pick's own chain)
    own = _chain("m_cbot", "m_cbot", score=30.0, signs=("+", "+"), ids=("pick", "z2"))
    got = W.chain_render_set([top, own], k=1, subject_ids=ids, question_markets=q, subject_rows=rows)
    assert got["counts"]["slot_state"]["subject"] == "seated" and own in got["rendered"]
    assert W.SLOT_STATES[-1] == "answered_by_row" and W.SLOT_STATES[:5] == (
        "not_asked", "resolver_off", "answered_by_rank", "seated", "no_candidate")


def test_P13_the_builder_finds_the_picks_OWN_single_link_row_on_a_question_market():
    bd = _board(anchors=("m_cbot",))
    bd.question_reach = (("m_cbot", 0),)
    bd.subject = {"picked": ["pick"], "groups": {"pick": ["pick", "cousin"]}, "hints": {}}
    _row(bd, "m_cbot", "pick", st=_st("pick", pct=50))
    _row(bd, "m_cbot", "cousin", st=_st("cousin", pct=60))
    _row(bd, "m_cbot", "z", st=_st("z", pct=70))
    _path(bd, "m_cbot", ["pick"])
    _path(bd, "m_cbot", ["cousin", "z"])
    _finish(bd)
    rows = W._subject_rows(bd, [], {"m_cbot": frozenset({"pick", "cousin"})}, frozenset({"m_cbot"}),
                           {("m_cbot", "pick")}, {r.key: r for r in bd.rows})
    assert rows == {"rows": frozenset({("m_cbot", "pick")}), "own": {"m_cbot": frozenset({"pick"})}}
    assert W._subject_rows(bd, [], {"m_cbot": frozenset({"pick"})}, None, set(), {}) is None


# ═════════════════════════════════════════════════════════════════════════════════════════════════════
# W-4 STALE PERIODS
# ═════════════════════════════════════════════════════════════════════════════════════════════════════
def test_W4_the_2024_TRQ_and_US_SU_periods_are_STALE_and_a_one_period_lag_never_is():
    """ARM A, 2024-03-01 (D12): Thai imports MY2021/22 (level_date "2021") and the US stocks-to-use MY2020/21
    ("2020", with the store's newer 2023/24 on WASDE) read as the March-2024 state. Stale = more than ONE
    full period behind what the card should hold at the as-of: the store's own newer period where held,
    else the card's declared first print (silver_psd: the label's first day + six months). A monthly print
    one release late and an annual row one year behind are never stale (W4-a); a daily label never is."""
    trq = _st("import", table="silver_psd", metric="import_mt", cadence="annual", level_date="2021",
              commodity="soybeans_cbot", country="Thailand")
    su = _st("psd_ending_stock_su_ratio", table="silver_psd", metric="su_ratio", cadence="annual",
             level_date="2020", period_behind={"held": "2020/21", "newer_on": "USDA WASDE", "newer": "2023/24"})
    now = _st("x", table="silver_psd", metric="import_mt", cadence="annual", level_date="2025")
    assert W.hop_period_stale(trq, "2024-03-01") == {"served": "2021", "expected": "2023", "gap_periods": 2,
                                                      "basis": "card"}
    assert W.hop_period_stale(su, "2024-03-01")["basis"] == "store"
    assert W.hop_period_stale(su, "2024-03-01")["gap_periods"] == 3
    assert W.hop_period_stale(now, "2026-09-26") == {}, "one year behind is never stale"
    oni = _st("oni", level_date="2026-06", recency={"ym_publication_lag_days": 36})
    assert W.hop_period_stale(oni, "2026-09-26") == {}, "one print late is not stale"
    oni_old = _st("oni", level_date="2026-04", recency={"ym_publication_lag_days": 36})
    assert W.hop_period_stale(oni_old, "2026-09-26")["gap_periods"] == 3
    assert W.hop_period_stale(_st("crush", level_date="2026-01-02"), "2026-09-26") == {}
    assert W.hop_period_stale(_st("undeclared", level_date="2019", cadence="annual"), "2026-09-26") == {}


def test_W4_a_stale_hop_scores_NO_TAIL_joins_NO_agreement_and_REACH_is_untouched():
    """W-4's rule on the chain: the stale hop's reading is not today's -- TAIL reads it as 0, the ASYMMETRY
    term skips it, its link reads ``undetermined``, its run declares no direction -- and REACH (W4-b) is
    byte-equal. The chain stays in the pool with its score."""
    def board(stale):
        bd = _board(asof="2024-03-01", anchors=("soybeans_cbot",))
        trq = _st("import", pct=96, z=0.5, table="silver_psd", metric="import_mt", cadence="annual",
                  level_date=("2021" if stale else "2023"), commodity="soybeans_cbot", country="Thailand",
                  run={"direction": "down", "length": 1, "since_date": "2021"})
        _row(bd, "soybeans_cbot", "TRQ_soybeans", st=trq, sign="-")
        _row(bd, "soybeans_cbot", "export_pace_lag", st=_st("pace", pct=50), sign="-")
        _path(bd, "soybeans_cbot", ["TRQ_soybeans", "export_pace_lag"])
        _finish(bd)
        return W.chain_rows(bd, None, knobs=bd.knobs)["pool"][0]
    fresh, stale = board(False), board(True)
    assert stale.hops[0].period_stale["served"] == "2021"
    assert stale.terms["tail"] < fresh.terms["tail"] and stale.terms["reach"] == fresh.terms["reach"]
    assert stale.agreements[0] == "undetermined" and stale.direction == "unsettled"
    assert "2021" in (W.chain_explain(stale).notes.get("tail") or "") or stale.receipt_index != 0
    assert stale.hops[0].to_dict()["period_stale"]["gap_periods"] == 2
    assert "period_stale" not in fresh.hops[0].to_dict()


# ═════════════════════════════════════════════════════════════════════════════════════════════════════
# W-5 A FENCED GLOBAL SCOPE RESOLVES TO THE ANCHOR'S DECLARED HOME
# ═════════════════════════════════════════════════════════════════════════════════════════════════════
class _Node:
    def __init__(self, contract, did, region, anchor_row=True):
        self.contract, self.id, self.prior, self.kind = contract, did, {"region": region}, "driver"
        self.anchor_row = anchor_row


def test_W5_cotton_SU_and_SRW_ending_stocks_resolve_to_their_DECLARED_HOME_and_the_row_says_so():
    """ARM A (D14): cotton ``ending_stocks_su_ratio`` and SRW ``ending_stocks`` sat dark
    (``scope_unresolved:global-token-fenced``) while the same page served the US S/U. The home is the
    contract's OWN two declarations (commodity_hierarchy ``origin`` met by a ``country`` entry of its own
    geography); MATIF's ``EU`` origin is no country its geography declares, so it stays fenced (HEAD), and
    a context commodity with no hierarchy entry stays fenced too. No token table (W5-b)."""
    p = F.series_key_for("psd_ending_stock_su_ratio", _Node("cotton", "ending_stocks_su_ratio", "global"))
    assert p.status == "ok" and p.key.label() == "psd_ending_stock_su_ratio|cotton|United States"
    assert p.scope_resolution == F.SCOPE_HOME_FOR_GLOBAL == "home_for_global"
    p = F.series_key_for("psd_ending_stock_su_ratio",
                         _Node("soft_red_winter_wheat_cbot", "ending_stocks", "Global"))
    assert p.key.label() == "psd_ending_stock_su_ratio|soft_red_winter_wheat_cbot|United States"
    for c in ("french_wheat_matif", "barley", "sunflower_oil"):
        p = F.series_key_for("psd_ending_stock_su_ratio", _Node(c, "ending_stocks", "Global"))
        assert p.key is None and p.status == "scope_unresolved:global-token-fenced", c
        assert p.scope_resolution == ""
    assert F.home_scope_for("cocoa") == "" and F.home_scope_for("raw_sugar") == ""
    # a non-global node's plan is HEAD's
    p = F.series_key_for("psd_ending_stock_su_ratio", _Node("cotton", "ending_stocks_su_ratio", ""))
    assert p.scope_resolution == ""
    # ...and a FAR / fan node (not a row of the turn's own anchor boards) keeps HEAD's fence: MEASURED on the
    # palm fixture, a resolved far row read US wheat S/U as the fan of palm's own `ending_stocks`
    p = F.series_key_for("psd_ending_stock_su_ratio",
                         _Node("hard_red_spring_wheat_mgex", "ending_stocks", "Global", anchor_row=False))
    assert p.key is None and p.status == "scope_unresolved:global-token-fenced"
    assert W._WalkNode("c", cs.Driver(id="x", type="market_driver", sign="+", mechanism="m")).anchor_row is False


def test_W5_the_served_row_carries_its_scope_resolution_and_every_other_row_keeps_HEADs_shape():
    rows = []

    def qfn(*a, **k):
        rows.append(1)
        return []
    st = F.series_state("psd_ending_stock_su_ratio", _Node("cotton", "ending_stocks_su_ratio", "global"),
                        "2026-09-26", qfn=qfn)
    assert getattr(st, "scope_resolution", "") == "home_for_global"
    st2 = F.series_state("psd_ending_stock_su_ratio", _Node("french_wheat_matif", "ending_stocks", "Global"),
                         "2026-09-26", qfn=qfn)
    assert getattr(st2, "scope_resolution", "") == ""


# ═════════════════════════════════════════════════════════════════════════════════════════════════════
# W-6 THE ONE C8 PRODUCER CARRIES ITS ANCHOR
# ═════════════════════════════════════════════════════════════════════════════════════════════════════
def test_W6_the_one_producer_names_its_ANCHOR_DATE_run_or_reading_and_moves_no_other_value():
    """ARM A, MAX / RICE (D11): "opens around February 2026" (SB-J, counted from the run's start) against
    "opens 2026-10-31" (the watch, counted from the reading) -- one reading, two windows, no anchor on
    either. ``effect_window`` is the ONE producer both read; it now says which date opened ``opens``."""
    band = parse_lag("1-2 quarters")
    run = W.effect_window(band, newest="2026-07-31", run_start="2025-11-30")
    rd = W.effect_window(band, newest="2026-07-31")
    assert (run["anchor"], run["anchor_date"]) == ("run", "2025-11-30")
    assert (rd["anchor"], rd["anchor_date"]) == ("reading", "2026-07-31")
    assert rd["opens"] == "2026-10-31" and rd["closes"] == "2027-01-31"
    assert run["closes"] == rd["closes"], "the close is counted from the newest print on both anchors"


def test_W6_the_chain_hop_carries_the_windows_opening_and_anchor_off_the_SAME_call():
    bd = _board()
    st = _st("oni", pct=93, level_date="2026-07-31",
             run={"direction": "up", "length": 8, "since_date": "2025-11-30"})
    row = _row(bd, "a_cbot", "El_Nino", st=st, lag="1-3 quarters")
    hop = W.chain_hop(bd, row)
    ew = W.effect_window(row.lag_band, newest="2026-07-31", run_start="2025-11-30")
    assert (hop.effect_opens, hop.effect_anchor, hop.effect_anchor_date) == (
        ew["opens"], "run", "2025-11-30")
    assert hop.effect_closes == ew["closes"]
    d = hop.to_dict()
    assert d["effect_anchor"] == "run" and list(d)[-3:] == ["effect_opens", "effect_anchor",
                                                             "effect_anchor_date"]
    bare = W.ChainHop(contract="a_cbot", driver_id="x").to_dict()
    assert "effect_anchor" not in bare and "identity_refused" not in bare and "period_stale" not in bare


def test_the_BOARD_trace_omits_the_ledger_stamp_on_every_turn_the_chain_leg_did_not_read_it():
    bd = _board()
    assert "action_ledger" not in bd.trace()
    bd.action_ledger = {"read": False, "nodes": 1, "rows": 0, "ms": 0.0, "why": "no_pool"}
    assert bd.trace()["action_ledger"]["why"] == "no_pool" and list(bd.trace())[-1] == "action_ledger"
