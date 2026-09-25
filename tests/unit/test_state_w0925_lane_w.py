"""THE 09-25 RE-SMOKE FIX ROUND, LANE W (walk / board) -- the pins for items W-1..W-4.

Every pin names the 09-25 artefact it was written against (the served page or trace under
resmoke_0925/answers/) and the lexical form the fix rejected. W-5 (N8, the reach term) is an owner docket
and moves no score here.

  W-1 (N2)  a question slot seats the BEST-RANKED chain that answers it; the diversity fold orders only
            within a rank tie (the Thai TRQ horizon seat on the deep / max soybean turns).
  W-2 (N4)  a pattern condition counts only in the tail its card declares for it (the cocoa FATAL).
  W-3 (N7)  one quantity served under two series keys is ONE link (the 2024 meal consumption /
            feed-and-waste identity, 34.18 MMT into 34.18 MMT).
  W-4 (N12) trace hygiene: a chain the sign swap drops gives up its seat word; a cross variant carries its
            base's refused report pair.
"""
from __future__ import annotations

import pytest
from leviathan.causal import schema as cs
from leviathan.graphrag import graph as G
from leviathan.graphrag.state import board as B
from leviathan.graphrag.state import walk as W
from leviathan.graphrag.state.feeders import KeyPlan
from leviathan.graphrag.state.lagbands import parse_lag
from leviathan.graphrag.state.rows import SeriesKey, StateRow


@pytest.fixture(scope="module")
def real():
    return G.CausalGraph(G.load_contracts(), silver=set(), version="test")


def _st(ref, *, commodity="", country="", table="t", metric="", z=None, pct=None, level=1.0,
        level_date="2026-08", narrate_unit="z", unit="z"):
    return StateRow(key=SeriesKey(ref=ref, commodity=commodity, country=country), status="ok",
                    coverage_tier="series", table=table, metric=metric or ref, cadence="monthly",
                    unit=unit, narrate_unit=narrate_unit, level=level, level_date=level_date,
                    z=None if z is None else {"value": z, "window_n": 120},
                    percentile=None if pct is None else {"value": pct, "n": 120})


def _row(graph, contract, driver_id, st=None, *, loud=True):
    d = next(x for x in graph.contracts[contract].drivers if x.id == driver_id)
    row = W._node_row(graph, contract, d)
    if st is not None:
        row.state = st
        row.series_key = st.key.label()
    row.legs["loud"] = loud
    return row


def _conv(graph, contract, rows, *, sides=True):
    ids = {r.driver_id for r in rows if r.legs.get("loud") and not r.context_only}
    read = {r.driver_id for r in rows if r.legs.get("loud") and r.state is not None}
    kw = {"sides": {r.driver_id: W.row_side(r) for r in rows if r.driver_id in read}} if sides else {}
    return {c["name"]: c for c in W.convergence_rows(graph, contract, ids, loud_k=12, band_ids=set(),
                                                     measured_ids=read, **kw)}


# ── W-2 (N4): THE PATTERN QUORUM IS TAIL-AWARE ──────────────────────────────────────────────────────
@pytest.mark.parametrize("pct,z,orient,side", [
    (96.6, 2.67, 0, 1),        # the palm-belt dry run: upper tail
    (3.4, -1.49, 0, -1),       # the cocoa dry-day run on 09-25: lower tail (WET)
    (6.4, -1.23, 0, -1),       # the cocoa max-temperature anomaly on 09-25: lower tail (COOL)
    (36.0, 1.33, 0, 1),        # GBP: the z is the louder component, so its side is the reading's
    (75.0, -1.25, 0, 0),       # the two components tie with opposite signs: no tail
    (50.0, None, 0, 0),        # the middle of the record: no tail
    (None, None, 0, 0),        # no standing: no tail
    (92.7, 2.43, 1, 1),        # an oriented reading: the upper tail in the driver's own sense
    (92.7, 2.43, -1, -1),      # ... and the lower, read the other way round
])
def test_W0925_W2_the_reading_side_is_the_loud_components_own_sign(pct, z, orient, side):
    """ONE MEASURE, THE CHAIN'S: the side is the sign of the component `_hop_tail` takes the magnitude of
    -- the one that makes the reading loud -- read in the driver's own sense for a declared pole."""
    assert W.reading_side(pct, z, orient=orient) == side


def test_W0925_W2_the_COCOA_squeeze_counts_ONE_condition_not_THREE(real):
    """THE 09-25 COCOA FATAL (deep_state_cocoa_2026_09): the page said "three of its six conditions are
    counted on this page against a threshold of three" for the West African deficit squeeze and the
    TL;DR put supply "toward higher prices" -- on a WET dry-day run (footer [N14] -0.92 z, [N16] 3rd
    percentile) and a COOL max-temperature anomaly ([N20] -0.67 z, [N22] 6th percentile), both drivers
    declared `+` in a `+` pattern. The rows below are the trace's own `row_states`. The quorum now counts
    the one condition it can (the unread export-pace lag, HEAD's text-tier reading) and states the two
    readings in the opposite tail as AGAINST the pattern. The rejected lexical form: pattern-name or
    driver-name keyword rules."""
    rows = [_row(real, "cocoa", "harmattan",
                 _st("stage_tmax_anomaly", commodity="cocoa", country="West Africa", table="gold_weather_z",
                     metric="tmax_anomaly", level=-0.6681553372294483, z=-1.23, pct=6.4)),
            _row(real, "cocoa", "drought",
                 _st("drought_z", commodity="cocoa", country="West Africa", table="gold_weather_z",
                     level=-0.9183083940048905, z=-1.49, pct=3.4)),
            _row(real, "cocoa", "export_pace_lag")]            # loud, no series read (scope_unresolved)
    head = _conv(real, "cocoa", rows, sides=False)["west_africa_deficit_squeeze"]
    assert head["n_matched"] == 3 and head["threshold"] == 3, "HEAD's count (the page's three of three)"
    assert "against" not in head and "unsided" not in head, "no `sides` -> HEAD's row, byte for byte"
    got = _conv(real, "cocoa", rows)["west_africa_deficit_squeeze"]
    assert got["matched"] == ("export_pace_lag",) and got["n_matched"] == 1
    assert got["matched_measured"] == () and got["matched_unmeasured"] == ("export_pace_lag",)
    assert got["against"] == ("harmattan", "drought") and got["unsided"] == ()
    assert set(got) == set(head) | {"against", "unsided"}, "the tail verdicts ride at the row's tail"
    # the amplifier keeps HEAD's rank claim and names which of its members sit on the other side
    amp = next(i for i in got["interactions"] if set(i["when"]) == {"harmattan", "drought"})
    assert amp["rendered"] is True and amp["against"] == ("harmattan", "drought")


def test_W0925_W2_a_POLE_member_and_a_POLICY_EVENT_keep_HEADs_reading(real):
    """TWO DECLARED CAUSES OF "NO READING'S TAIL" (`row_side` -> None), each read off the graph, never a name:

    * a member of a declared phase pair: its condition is the PHASE, and the render's quorum fold already
      judges it off the one phase producer -- a member in the opposite phase is stated by name and left out
      of the count (MAJOR 10). Moving it out of `matched` would silence that sentence (the b40 supply-squeeze
      row's "El Nino names the phase opposite the one in force on that reading, so it is not counted here").
      So ONI +1.8 leaves El Nino and La Nina where HEAD put them, and the render's fold decides the count;
    * a `policy_event` node: its state is its dated action (`hop_event`'s regime ladder); the trade-flow
      series bound to it measures the policy's effect under a polarity the graph does not declare -- the
      palm export ban reads the Indonesian EXPORT level, where HIGH exports are NO ban."""
    oni = dict(commodity="_global", table="silver_noaa_oni", metric="oni_anom", level=1.8, z=2.43,
               pct=92.7, narrate_unit="degC", unit="degC", level_date="2026-07")
    el, la = (_row(real, "malaysian_crude_palm_oil_cme", d, _st("oni_climate", **oni))
              for d in ("El_Nino", "La_Nina"))
    assert W.row_side(el) is None and W.row_side(la) is None
    sig = next(s for s in real.contracts["malaysian_crude_palm_oil_cme"].convergence
               if "La_Nina" in s.drivers)
    head = _conv(real, "malaysian_crude_palm_oil_cme", [el, la], sides=False)[sig.name]
    got = _conv(real, "malaysian_crude_palm_oil_cme", [el, la])[sig.name]
    assert got["matched"] == head["matched"] and "La_Nina" in got["matched"] and got["against"] == ()
    ban = _row(real, "malaysian_crude_palm_oil_cme", "export_ban",
               _st("export", commodity="malaysian_crude_palm_oil_cme", country="Indonesia", level=20.0, z=-1.9,
                   pct=4.0, narrate_unit="MMT", unit="MT", level_date="2025"))
    assert ban.type == "policy_event" and W.row_side(ban) is None
    pol = next(s for s in real.contracts["malaysian_crude_palm_oil_cme"].convergence
               if "export_ban" in s.drivers)
    assert "export_ban" in _conv(real, "malaysian_crude_palm_oil_cme", [ban])[pol.name]["matched"]
    # and a row with no served reading has no tail either
    assert W.row_side(_row(real, "cocoa", "export_pace_lag")) is None


def test_W0925_W2_a_driver_the_card_declares_ZERO_is_UNSIDED_and_not_counted(real):
    """`eurusd_fx` is declared `0` on MATIF rapeseed (no committed direction) and sits in the `+`
    bullish_fx_macro_input pattern; one loud reading cannot count for a side the card never committed to.
    09-25 palm/rape served it as a condition of that pattern (EUR/USD 0.88, z 2.01, the 31st percentile)."""
    r = _row(real, "french_rapeseed_matif", "eurusd_fx",
             _st("fred_fx_macro", commodity="_global", level=0.87974, z=2.01, pct=30.6, narrate_unit="EUR/USD",
                 unit="EUR/USD", level_date="2026-09-24"))
    assert r.type != "policy_event" and W.row_side(r) == 1
    got = _conv(real, "french_rapeseed_matif", [r])["bullish_fx_macro_input"]
    assert got["unsided"] == ("eurusd_fx",) and "eurusd_fx" not in got["matched"]
    assert got["n_matched"] == 0


def test_W0925_W2_THE_WALK_passes_each_board_its_own_sides():
    """Through `walk()` / stage 2 on a hermetic DAG: the pattern's upper-tail condition counts, the
    lower-tail one is against, and HEAD's keys are all still on the row."""
    d = [cs.Driver(id="hot", type="climate_driver", sign="+", mechanism="m", silver_ref="hot",
                   silver_status="available"),
         cs.Driver(id="wet", type="climate_driver", sign="+", mechanism="m", silver_ref="wet",
                   silver_status="available")]
    sig = cs.ConvergenceSignal(name="squeeze", direction="+", requires_any_n_of=2, drivers=["hot", "wet"])
    g = G.CausalGraph({"c_cbot": cs.CausalContract(contract="c_cbot", drivers=d, convergence=[sig])},
                      silver=set(), version="fixture")

    def _state_fn(ref, node):
        spec = {"hot": (2.0, 97.0), "wet": (-2.0, 3.0)}[ref]
        return _st(ref, z=spec[0], pct=spec[1], level_date="2026-07-31")

    def _key_fn(ref, node, *, turn_kind=""):
        return KeyPlan(key=SeriesKey(ref=ref, commodity=node.contract), status="ok", table="t", metric=ref,
                       cadence="monthly", row={"table": "t"})
    bd = W.walk(graph=g, asof="2026-09-07", mode="deep", anchors=W.resolve_anchors(named=("c_cbot",)),
                state_fn=_state_fn, key_fn=_key_fn, receipts={})
    row = next(r for r in bd.convergence if r["name"] == "squeeze")
    assert row["matched"] == ("hot",) and row["against"] == ("wet",) and row["n_matched"] == 1
    assert {"n_matched", "matched_measured", "matched_unmeasured", "n_with_band"} <= set(row)


# ── W-1 (N2): THE QUESTION SLOT SEATS BY RANK ───────────────────────────────────────────────────────
def _hop(did, *, key, band="0-1 quarters", seat=0):
    return W.ChainHop(contract="soybeans_cbot", driver_id=did, lag_band=parse_lag(band), series_key=key,
                      seat=seat)


def _chain(score, hops, *, terminal="soybeans_cbot", side="for"):
    ch = W.Chain(contract="soybeans_cbot", hops=tuple(hops), depth=len(hops) - 1, terminal=terminal)
    ch.score, ch.side = score, side
    return ch


def _deep_0925_pool():
    """THE 09-25 DEEP SOYBEAN SHAPE (deep_rv_soybeans_state_2026_09_07 trace chains 1, 4, 3): the top chain
    (crude -> crush -> stocks-to-use -> DCE, 78.0) is outside the three-month horizon's band; the BEST
    horizon chain (crude -> crush -> stocks-to-use -> calendar spread -> CBOT soybeans, 68.5) shares its top
    reading (Brent) with it; the Thai TRQ chain (59.1, weakest link LOW) folds cleanly."""
    top = _chain(78.0, [_hop("crude_oil", key="brent", band="2-4 quarters", seat=1),
                        _hop("soybean_crush_margin", key="crush", seat=2)], terminal="soybeans_no_1_dce",
                 side="against")
    best = _chain(68.5, [_hop("crude_oil", key="brent", seat=1), _hop("calendar_spread", key="cal", seat=5)])
    thai = _chain(59.1, [_hop("TRQ_soybeans", key="thai", seat=9), _hop("export_pace_lag", key="esr", seat=7)])
    return top, best, thai


def test_W0925_W1_the_HORIZON_seat_takes_the_best_ranked_chain_not_the_Thai_TRQ_chain():
    """Both 2026 soybean TL;DRs said "the chain from Thai imports answers the horizon" (deep:5, max:5):
    the fold preference (walk.py:3777) skipped the 68.5 crude chain because Brent was already on the page.
    The seat is the rank's; the fold orders only within a rank tie. The rejected lexical forms: excluding
    TRQ ids, a confidence floor keyed on driver names."""
    top, best, thai = _deep_0925_pool()
    got = W.chain_render_set([top, best, thai], k=1, horizon_months=3)
    seat = next(c for c in got["rendered"] if c.slot == "horizon")
    assert seat is best and best.answers_horizon and not thai.rendered, [c.hop_ids for c in got["rendered"]]
    assert got["counts"]["slot_state"]["horizon"] == "seated"


def test_W0925_W1_the_fold_preference_orders_ONLY_within_a_rank_tie():
    top, best, thai = _deep_0925_pool()
    thai.score = best.score                           # a tie on the rank's measured term
    got = W.chain_render_set([top, best, thai], k=1, horizon_months=3)
    assert next(c for c in got["rendered"] if c.slot == "horizon") is thai, "the clean fold wins the tie"
    assert W._slot_pick([best, thai], lambda c: c is thai) is thai
    thai.score = best.score - 0.1
    assert W._slot_pick([best, thai], lambda c: c is thai) is best, "novelty never outranks relevance"


# ── W-3 (N7): ONE QUANTITY IS ONE LINK ─────────────────────────────────────────────────────────────
def _meal_hop(did, ref, *, level, z=1.3435315358894013, pct=97.36842105263158, country="United States"):
    return W.ChainHop(contract="soybean_meal_cbot", driver_id=did, series_key="%s|soybean_meal_cbot|%s"
                      % (ref, country), measured=True, level_shown=level, narrate_unit="MMT", z=z,
                      percentile=pct, level_date="2020", lag_band=parse_lag("0-2 quarters"))


def test_W0925_W3_the_2024_meal_CONSUMPTION_and_FEED_WASTE_rows_are_ONE_quantity():
    """deep_rv_soybeans_state_2024_03_01 chain 2 walked poultry expansion on `consumption|...` (the PSD
    consumption_mt card, native MT) into soybean-meal feed demand on `psd_meal_feed_waste_use|...` (the
    attributes sheet, native 1000 MT): 34.18 MMT for 2020/21 into 34.18 MMT, 97th percentile, z 1.34 --
    and scored the link "aligned". The served levels differ only in float representation
    (34.178999999999995 vs 34.179). One quantity is one link; the fold keeps the first node and names the
    second as its alias. The rejected lexical form: a synonym table of refs."""
    a = _meal_hop("poultry_expansion", "consumption", level=34.178999999999995)
    b = _meal_hop("soybean_meal_feed_demand", "psd_meal_feed_waste_use", level=34.179)
    c = W.ChainHop(contract="soybean_meal_cbot", driver_id="soybean_crush_margin", measured=True,
                   series_key="cbot_board_crush_margin|_global|", level_shown=0.808, narrate_unit="USD/bu",
                   z=-1.45, percentile=11.5, level_date="2024-02-29")
    assert a.fold_key != b.fold_key and a.quantity_key == b.quantity_key != ()
    hops, n = W.fold_series_hops((a, b, c))
    assert [h.driver_id for h in hops] == ["poultry_expansion", "soybean_crush_margin"] and n == 1
    assert hops[0].aliases == ("soybean_meal_feed_demand",)


@pytest.mark.parametrize("change", [
    {"z": 1.2}, {"pct": 90.0}, {"country": "China"}, {"level": 34.2},
])
def test_W0925_W3_a_COINCIDENCE_is_not_an_identity(change):
    """Two quantities that share one print but not their record (z / percentile), their scope, or their
    value do not fold."""
    a = _meal_hop("poultry_expansion", "consumption", level=34.179)
    kw = dict(level=change.get("level", 34.179), z=change.get("z", 1.3435315358894013),
              pct=change.get("pct", 97.36842105263158), country=change.get("country", "United States"))
    b = _meal_hop("soybean_meal_feed_demand", "psd_meal_feed_waste_use", **kw)
    assert a.quantity_key != b.quantity_key
    assert len(W.fold_series_hops((a, b))[0]) == 2


def test_W0925_W3_a_hop_with_NO_standing_has_no_measured_identity():
    h = W.ChainHop(contract="a_cbot", driver_id="x", series_key="x|a_cbot|", measured=True, level_shown=1.0)
    assert h.quantity_key == () and h.reading_keys == frozenset({h.fold_key})
    unmeasured = W.ChainHop(contract="a_cbot", driver_id="y")
    assert unmeasured.quantity_key == ()


def test_W0925_W3_the_DIVERSITY_fold_counts_one_quantity_once():
    """Two chains whose TOP readings are one quantity under two series keys share a reading on the page
    exactly as two chains on one series key do."""
    t1 = _meal_hop("poultry_expansion", "consumption", level=34.179)
    t2 = _meal_hop("soybean_meal_feed_demand", "psd_meal_feed_waste_use", level=34.179)
    oth = W.ChainHop(contract="soybean_meal_cbot", driver_id="crude_oil", measured=True, series_key="brent",
                     level_shown=80.0, narrate_unit="USD/bbl", z=0.5, percentile=68.0, level_date="2024-02")
    mk = lambda score, h: W.Chain(contract="soybean_meal_cbot", hops=(h, W.ChainHop(  # noqa: E731
        contract="soybean_meal_cbot", driver_id="calendar_spread_%d" % int(score))), depth=1,
        terminal="soybean_meal_cbot", score=score, side="for")
    a, b, c = mk(90.0, t1), mk(80.0, t2), mk(70.0, oth)
    got = W.chain_render_set([a, b, c], k=2)
    assert [x.hop_ids[0] for x in got["rendered"]] == ["poultry_expansion", "crude_oil"]
    assert not b.rendered and b.decline == "render_cap"


def test_W0925_W3_THROUGH_chain_rows_the_path_is_composed_at_its_TRUE_depth():
    bd = B.Board(asof="2024-03-01", mode="deep", knobs=B.board_knobs_of("deep"), horizon_months=3,
                 anchors=(B.Anchor(contract="soybean_meal_cbot", source="named"),))
    for did, ref, native, scale, level in (("poultry_expansion", "consumption", "MT", 1e-6, 34179000.0),
                                            ("soybean_meal_feed_demand", "psd_meal_feed_waste_use",
                                             "1000 MT", 0.001, 34179.0)):
        st = StateRow(key=SeriesKey(ref=ref, commodity="soybean_meal_cbot", country="United States"),
                      status="ok", coverage_tier="series", table="t_%s" % ref, metric=ref, unit=native,
                      narrate_unit="MMT", scale=scale, level=level, level_date="2020",
                      z={"value": 1.3435315358894013, "window_n": 60},
                      percentile={"value": 97.36842105263158, "n": 60})
        row = B.NodeRow(contract="soybean_meal_cbot", driver_id=did, sign="+", lag="0-2 quarters",
                        lag_band=parse_lag("0-2 quarters"), confidence="high", mechanism="m",
                        silver_status="available", series_key=st.key.label(), state=st)
        row.legs["loud"] = True
        bd.series[st.key.label()] = st
        bd.rows.append(row)
    st3 = StateRow(key=SeriesKey(ref="cbot_board_crush_margin", commodity="_global"), status="ok",
                   coverage_tier="series", table="t_crush", metric="crush", unit="USD/bu",
                   narrate_unit="USD/bu", level=0.808, level_date="2024-02-29",
                   z={"value": -1.45, "window_n": 120}, percentile={"value": 11.5, "n": 120})
    r3 = B.NodeRow(contract="soybean_meal_cbot", driver_id="soybean_crush_margin", sign="+",
                   lag="0-1 quarters", lag_band=parse_lag("0-1 quarters"), confidence="high", mechanism="m",
                   silver_status="available", series_key=st3.key.label(), state=st3)
    r3.legs["loud"] = True
    bd.series[st3.key.label()] = st3
    bd.rows.append(r3)
    bd.paths.append({"contract": "soybean_meal_cbot", "seeded_by": "poultry_expansion",
                     "ancestor": "poultry_expansion", "bottom": "soybean_crush_margin", "depth": 2,
                     "hops": ("poultry_expansion", "soybean_meal_feed_demand", "soybean_crush_margin"),
                     "lag_band": parse_lag(""), "band_is_the_ancestors_own": True, "confidence": "high",
                     "rank": (), "rendered": False, "decline": None})
    bd.set_order(W.rank_rows(bd.rows))
    got = W.chain_rows(bd, None, knobs=bd.knobs)
    (ch,) = got["pool"]
    assert ch.hop_ids == ("poultry_expansion", "soybean_crush_margin") and ch.depth == 1
    assert ch.hops[0].aliases == ("soybean_meal_feed_demand",)
    assert got["counts"]["series_folded"] == 1


# ── W-4 (N12): TRACE HYGIENE ────────────────────────────────────────────────────────────────────────
def test_W0925_W4_a_chain_the_SIGN_SWAP_drops_gives_up_its_seat_word():
    """2024 chain 4, deep 2026 chain 7 and cocoa chain 5 read `slot "top"` beside `rendered false` on the
    09-25 traces: the swap dropped them with `picked[:] = keep` and never cleared the word."""
    mk = lambda score, key, side: W.Chain(  # noqa: E731
        contract="a_cbot", hops=(W.ChainHop(contract="a_cbot", driver_id=key, series_key=key),
                                 W.ChainHop(contract="a_cbot", driver_id=key + "_b", series_key=key + "_b")),
        depth=1, terminal="a_cbot", score=score, side=side)
    a, b, c = mk(90.0, "a", "against"), mk(80.0, "b", "against"), mk(70.0, "c", "for")
    got = W.chain_render_set([a, b, c], k=2)
    assert {x.hop_ids[0]: x.slot for x in got["rendered"]} == {"a": "top", "c": "sign"}
    assert not b.rendered and b.slot == "", b.slot
    assert all(x.slot == "" for x in (a, b, c) if not x.rendered)


def test_W0925_W4_a_CROSS_VARIANT_carries_its_base_chains_refused_report():
    """max chain 5 (the base: crude -> crush -> stocks-to-use -> calendar spread) carried the refused
    report "crude_oil 2005-09-01" and its cross variants (max chain 2, corn_wheat chain 1) an empty pair:
    the variant copies the receipt words, so its `chain_score` never re-derives the pair."""
    bd = B.Board(asof="2026-09-07", mode="deep", knobs=B.board_knobs_of("deep"),
                 anchors=(B.Anchor(contract="a_cbot", source="named"),))
    old = {"date": "2005-09-01", "text": "an old report on the crush mechanism"}
    h1 = W.ChainHop(contract="a_cbot", driver_id="crude_oil", sign="+", lag_band=parse_lag("0-1 quarters"),
                    series_key="s1", measured=True, percentile=90.0, receipts_top=(old,))
    h2 = W.ChainHop(contract="a_cbot", driver_id="su", sign="-", lag_band=parse_lag("0-1 quarters"),
                    series_key="s2", measured=True, percentile=10.0)
    base = W._compose(bd, (h1, h2), contract="a_cbot", index={}, named={"a_cbot"}, hist_cache={})
    assert base.mechanism_refused_date == "2005-09-01" and base.mechanism_refused_hop is h1
    assert base.receipt_words, "the refused report is NAMED on the base (report_outside)"
    cross = {"anchor": "a_cbot", "other": "z_ice", "direction": "forward", "relation": "competes_with",
             "sign": "+", "lag": "", "far_driver_id": "", "far_series_key": "", "far_level": None,
             "far_unit": "", "far_percentile": None}
    v = W._with_cross(bd, base, cross, index={}, named={"a_cbot"}, hist_cache={})
    assert v.terminal == "z_ice" and v.receipt_words == base.receipt_words
    assert (v.mechanism_refused_date, v.mechanism_refused_hop) == ("2005-09-01", h1)
    assert v.to_dict()["mechanism_refused_hop"] == "crude_oil"
    # and the count line still counts ONE document for the two chains
    assert W.chain_counts([base, v])["mechanism_refused"] == 1
