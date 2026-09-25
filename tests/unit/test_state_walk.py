"""THE WALK -- STATE ENGINE DESIGN sec 3 whole, plus 1.3, 1.5, 6.7 and sec 7. Sitting S2.

THE BARS THIS FILE OWNS (sec 10.2, the S2 row of sec 11): B1 the rectangle, B3 the budget and its
atomicity, B7 the shared driver, B8 upstream, B13 the tags, B16 ordering-not-verdict, B17 the two
stamped stages -- plus the anchor grammar of sec 16's two amendments and the priced cold-start read set.

EVERYTHING RUNS OFFLINE. The state producer, the key resolver and the executor are INJECTED, so no test
here opens a pg mirror, reaches Athena, spends a cent or reads an environment variable. Where a bar is
about a fact of the SHIPPED graph (B7's `-`/`+` split on El_Nino, B8's crude_oil path) the test loads
the REAL 36 curated DAGs, because a bar pinned against a synthetic graph would pin the fixture.
"""
import json

import pytest
from leviathan.causal import schema as cs
from leviathan.graphrag import graph as G
from leviathan.graphrag import register as REG
from leviathan.graphrag.state import board as B
from leviathan.graphrag.state import walk as W
from leviathan.graphrag.state.feeders import KeyPlan
from leviathan.graphrag.state.lagbands import parse_lag
from leviathan.graphrag.state.rows import SeriesKey, StateRow


# ── fixtures ─────────────────────────────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def real():
    """The 36 curated DAGs as shipped. `silver=set()` keeps `silver_status()['live']` a DISPLAY fact
    that no tier is read off (sec 1.3)."""
    return G.CausalGraph(G.load_contracts(), silver=set(), version="test")


def _driver(did, **kw):
    kw.setdefault("type", "climate_driver")
    kw.setdefault("sign", "+")
    kw.setdefault("mechanism", "m")
    return cs.Driver(id=did, **kw)


def _graph(**boards):
    """A hermetic CausalGraph from `{slug: CausalContract}` -- the real class, so every accessor the
    walk uses is the shipped one and no test-only traversal exists."""
    return G.CausalGraph(boards, silver=set(), version="fixture")


def _state(ref, *, z=None, pct=None, run=None, conv=None, tier="series", status="ok", reads=1):
    return StateRow(key=SeriesKey(ref=ref), status=status, coverage_tier=tier, table="t", metric=ref,
                    cadence="monthly", level=1.0, level_date="2026-07-31",
                    knowledge_date="2026-08-05",
                    z=None if z is None else {"value": z, "window_n": 120},
                    percentile=None if pct is None else {"value": pct, "n": 120},
                    run=None if run is None else {"direction": "up", "length": run,
                                                  "since_date": "2026-04-30"},
                    convention=conv, reads=reads)


def _key_fn(global_refs=("oni_climate", "oni_lag_climate", "iod_climate")):
    """A zero-read key resolver in the shape of `feeders.series_key_for`: the ONI alias folds onto the
    base key exactly as `same_series_as` makes it fold, which is what makes a far ONI state FREE.

    `iod_climate` IS IN THE GLOBAL SET because the shipped config says so (`global_state: true` on
    `oni_climate`, `iod_climate` and `oni_lag_climate`, sec 3.6) -- it was absent from the first cut of
    this fixture, which made the cold-start pricer's own "two reads serve 89 rows on 51 boards" line
    untestable against a resolver that gave IOD one key per board."""
    def _fn(ref, node, *, turn_kind=""):
        if ref in global_refs:
            base = "iod_climate" if ref == "iod_climate" else "oni_climate"
            return KeyPlan(key=SeriesKey(ref=base, commodity="_global"), status="ok",
                           table="silver_noaa_oni", metric="oni_anom", cadence="monthly",
                           row={"table": "silver_noaa_oni"})
        return KeyPlan(key=SeriesKey(ref=ref, commodity=node.contract), status="ok", table="t",
                       metric=ref, cadence="monthly", row={"table": "t"})
    return _fn


def _flat_state_fn(**by_ref):
    """`(ref, node) -> StateRow`, with per-ref overrides and a quiet default. One read per call."""
    def _fn(ref, node):
        spec = by_ref.get(ref, {"z": 0.1, "pct": 51.0})
        return _state(ref, **spec)
    return _fn


# ── 3.1 THE ASKED HORIZON: parsed by ONE closed regex, and it anchors nothing ────────────────────────
@pytest.mark.parametrize("q,months", [
    ("what does El Nino do to soybeans over the next six months?", 6),
    ("the three month view", 3),
    ("two quarters out", 6),
    ("one year from now", 12),
    ("18 months", 18),
    ("what is the balance sheet doing", None),
    ("zero months", None),
])
def test_the_horizon_is_PARSED_never_guessed(q, months):
    assert W.parse_horizon(q) == months


def test_the_FIRST_horizon_wins_so_a_comparison_window_never_becomes_the_question():
    """A question with two horizons has ONE asked horizon and one comparison window; a board that
    silently took the larger would print a projection clause about a span nobody asked for."""
    assert W.parse_horizon("over three months, versus the last two years") == 3


def test_the_horizon_clause_is_BOARD_arithmetic_and_names_where_it_sits():
    band = parse_lag("2-4 quarters")
    win = W.projection_window("2026-04-30", band)
    assert win["opens"] == "2026-10-30" and win["closes"] == "2027-04-30"
    assert W.horizon_sits(3, win, "2026-04-30") == "before"
    assert W.horizon_sits(9, win, "2026-04-30") == "inside"
    assert W.horizon_sits(24, win, "2026-04-30") == "past"
    assert W.horizon_sits(None, win, "2026-04-30") is None


def test_a_structural_band_opens_and_never_closes():
    win = W.projection_window("2026-04-30", parse_lag("structural"))
    assert win["open_ended"] and win["closes"] is None and win["opens"] == "2028-04-30"


# ── 3.2 THE RANK ─────────────────────────────────────────────────────────────────────────────────────
def _row(did, **kw):
    st = kw.pop("state", None)
    r = B.NodeRow(contract="c", driver_id=did, confidence=kw.pop("confidence", "medium"),
                  coverage_tier=kw.pop("tier", "series"), state=st, **kw)
    return r


def test_the_D2_tuple_leads_with_abs_z_and_the_convention_is_a_TIE_BREAK():
    """Among rows with a z the order IS |z|; percentile and run break exact ties only; a declared band
    is a tie-break BEHIND all three (Judges 2 and 3; Draft B's tuple corrected). A weight would be a
    threshold with a smooth edge -- which is the curation ruling 1 forbids."""
    hit = {"label": "strong", "band": 1.5, "matched": True}
    quiet_but_banded = _row("a", state=_state("r", z=0.2, pct=52.0, conv=hit))
    loud_unbanded = _row("b", state=_state("r", z=2.4, pct=99.0))
    assert W.rank_key(loud_unbanded) < W.rank_key(quiet_but_banded)
    assert W.alt_rank_key(quiet_but_banded) < W.alt_rank_key(loud_unbanded)   # the BANKED alternative


def test_the_coverage_band_leads_the_tuple_and_an_unmeasured_row_is_still_ranked():
    served = _row("a", state=_state("r", z=0.0))
    planned = _row("z", tier="planned_text_only")
    assert W.coverage_band(served) == 0 and W.coverage_band(planned) == 4
    assert W.rank_key(served) < W.rank_key(planned)
    zero_var = _row("b", state=_state("r", z=None, pct=97.0))
    assert W.coverage_band(zero_var) == 1                      # a percentile with a declined z
    assert W.coverage_band(_row("c", state=_state("r"))) == 2   # neither: a level and no standing


def test_no_row_is_dropped_for_being_quiet_and_a_normal_reading_is_a_ROW():
    rows = [_row("a", state=_state("r", z=0.01)), _row("b", state=_state("r", z=3.0))]
    assert len(W.rank_rows(rows)) == 2
    assert W.rank_rows(rows)[0].driver_id == "b"


def test_the_loud_set_is_a_RANK_CUT_union_band_crossers_union_OPEN_EVENTS():
    """The two unions are INCLUSIONS and never exclusions (sec 3.2). Without the event union,
    `biodiesel_mandate` on palm -- coverage band 4, `planned` -- could reach Cascade's top-24 only
    through the alphabetical `driver_id` tail and would never reach Scan or Analysis at all."""
    rows = [_row(f"d{i:02d}", state=_state("r", z=3.0 - i * 0.1)) for i in range(10)]
    quiet_banded = _row("zz_banded", state=_state("r", z=0.01))
    quiet_banded.band_crossed = True
    open_event = _row("zz_event", tier="planned_text_only")
    open_event.event_open = True
    everything = rows + [quiet_banded, open_event]
    loud = W.loud_set(everything, loud_k=3)
    ids = {r.driver_id for r in loud}
    assert {"d00", "d01", "d02", "zz_banded", "zz_event"} == ids


def test_the_rank_rule_is_PRINTED_in_words_and_never_claims_a_cross_series_comparison():
    assert "its own history on its own window" in W.RANK_RULE_WORDS
    assert "sigma" not in W.RANK_RULE_WORDS
    # THE ALTERNATIVE HAS ITS OWN SENTENCE, and it leads with the convention because the tuple does.
    assert "crossed a level its desk convention names" in W.ALT_RANK_RULE_WORDS
    assert "sigma" not in W.ALT_RANK_RULE_WORDS
    assert W.rank_rule_words(True) == W.ALT_RANK_RULE_WORDS
    assert W.rank_rule_words(False) == W.RANK_RULE_WORDS


def _alt_arm_graph():
    """ONE board, three drivers, and the two tuples DISAGREE about which row leads it.

    `crossed` sits quiet (|z| 0.2) but past a declared desk band; `loudest` is the biggest |z| on the
    board and crosses nothing. Under D2 the order is loudest -> ... -> crossed; under the alternative
    (`-convention_hit` ahead of `-abs_z`) it is crossed -> loudest. That is P1's whole question, and it
    is the fixture the switch is pinned on."""
    ds = [_driver("crossed", silver_ref="crossed", silver_status="available"),
          _driver("loudest", silver_ref="loudest", silver_status="available"),
          _driver("middling", silver_ref="middling", silver_status="available")]
    return _graph(c=cs.CausalContract(contract="c", drivers=ds))


def _alt_arm_state_fn():
    hit = {"label": "strong", "band": 1.5, "matched": True}
    spec = {"crossed": {"z": 0.2, "pct": 52.0, "conv": hit},
            "loudest": {"z": 2.4, "pct": 99.0},
            "middling": {"z": 1.0, "pct": 70.0}}

    def _fn(ref, node):
        return _state(ref, **spec[ref])
    return _fn


def _alt_arm_walk(**kw):
    return W.walk(graph=_alt_arm_graph(), asof="2026-09-07", mode="max",
                  anchors=(B.Anchor(contract="c", source="named"),),
                  state_fn=_alt_arm_state_fn(), key_fn=_key_fn(), receipts={}, **kw)


def test_P1s_ALTERNATIVE_tuple_is_ONE_switch_and_it_moves_EVERY_place_the_rank_is_consulted():
    """THE S2 LANDING'S DEFECT, MEASURED AND CLOSED. `alternative_rank=True` was threaded to `_stage1`
    and handed to ONE call (`loud_set`), so the alternative decided loud-set MEMBERSHIP and nothing
    else: `row.rank` was stamped with the D2 tuple, `board_order` sorted every row by that stamp, stage
    2 re-took the loud set from it, and the header printed the SHIPPED rule's sentence. The arm that
    exists to measure the alternative ranked by the tuple it was measuring against.

    ONE SWITCH NOW: the board carries `rank_rule`, and the stamp, the cut, both order writes, the
    anchor ranking and the header sentence all read it. The bar is the ORDER, on the same fixture."""
    d2 = _alt_arm_walk()
    alt = _alt_arm_walk(alternative_rank=True)

    assert (d2.rank_rule, alt.rank_rule) == ("d2", "alternative")
    # 1. the STAMP is the tuple that ran -- not the shipped one wearing the alternative's name
    assert d2.row("c", "crossed").rank == W.rank_key(d2.row("c", "crossed"))
    assert alt.row("c", "crossed").rank == W.alt_rank_key(alt.row("c", "crossed"))
    assert alt.row("c", "crossed").rank != W.rank_key(alt.row("c", "crossed"))
    # 2. the ORDER moves: the two tuples lead the same board with DIFFERENT rows
    assert d2.order[0] == ("c", "loudest") and alt.order[0] == ("c", "crossed")
    assert d2.order != alt.order
    # 3. the RANK CUT moves with it, and NEITHER TUPLE EXCLUDES: at loud_k=1 the D2 cut is the loudest
    #    row and the band-crosser joins by the UNION rule; under the alternative the crosser IS the
    #    cut, so the union adds nothing and `loudest` sits below it -- on the board, rendered when the
    #    budget allows, and named when it is not. One row, two positions, no exclusion either way.
    d2_cut = [r.driver_id for r in W.loud_set(d2.rows, loud_k=1)]
    alt_cut = [r.driver_id for r in W.loud_set(alt.rows, loud_k=1, alternative=True)]
    assert d2_cut == ["loudest", "crossed"] and alt_cut == ["crossed"]
    assert {"crossed", "loudest"} <= {r.driver_id for r in d2.rows}
    assert {"crossed", "loudest"} <= {r.driver_id for r in alt.rows}
    # 4. the TRACE names which tuple ran, so no census row is ever attributed to the other one
    assert d2.trace()["rank_rule"] == "d2" and alt.trace()["rank_rule"] == "alternative"
    # 5. the HEADER prints the rule the board actually used
    from leviathan.graphrag.state import render as R
    assert W.RANK_RULE_WORDS in R.sb_header(d2) and W.ALT_RANK_RULE_WORDS not in R.sb_header(d2)
    assert W.ALT_RANK_RULE_WORDS in R.sb_header(alt) and W.RANK_RULE_WORDS not in R.sb_header(alt)


def test_the_alternative_arm_stays_ONE_ordering_across_the_two_stamped_stages():
    """B17 under the alternative: stage 2 appends and never re-ranks, so the numeric head of the order
    written at the end of stage 1 survives the stage-2 write. The S2 landing could not hold this bar in
    the alternative arm at all -- stage 2's `loud_set` did not know which tuple had run."""
    stage1_only = _alt_arm_walk(alternative_rank=True, stage2=False)
    both = _alt_arm_walk(alternative_rank=True)
    assert stage1_only.order == both.order
    assert [r.driver_id for r in both.rows if r.legs.get("loud")] == ["crossed", "loudest", "middling"]


# ── 3.1 / sec 16 THE ANCHOR GRAMMAR ──────────────────────────────────────────────────────────────────
def test_AMENDMENT_2_named_markets_are_ALL_anchors_and_the_ceiling_bounds_only_inferred_seeds(real):
    """`MAX_CONTRACTS` exists to bound the PLANNER's own enumeration against the composition ceiling.
    Under the board it keeps that job for INFERRED seeds and stops truncating what the user NAMED: a
    question naming wheat, corn, soybeans and palm anchors all four ON EVERY TIER."""
    named = ["soft_red_winter_wheat_cbot", "corn_cbot", "soybeans_cbot",
             "malaysian_crude_palm_oil_cme"]
    anchors = W.resolve_anchors(named=named, contracts=["cocoa", "cotton", "raw_sugar"],
                                graph=real, max_contracts=2)
    assert {a.contract for a in anchors if a.source == "named"} == set(named)
    assert len([a for a in anchors if a.source == "planner_inferred"]) == 2   # the ceiling still binds
    assert anchors[0].source == "named"                                       # named outranks inferred


def test_an_ATTACHED_EVENT_outranks_the_board(real):
    anchors = W.resolve_anchors(named=["corn_cbot"], attached_event="soybeans_cbot", graph=real)
    assert anchors[0].contract == "soybeans_cbot" and anchors[0].source == "attached_event"


def test_a_market_that_is_both_NAMED_and_INFERRED_collapses_to_its_STRONGEST_source(real):
    anchors = W.resolve_anchors(named=["corn_cbot"], contracts=["corn_cbot"], graph=real,
                                max_contracts=2)
    assert len(anchors) == 1 and anchors[0].source == "named"


def test_AMENDMENT_1_a_focus_driver_anchors_EVERY_contract_carrying_it(real):
    """DRIVER-AS-SUBJECT: the two-contract planner ceiling does not apply, because these contracts are
    not planned -- they are read off the graph."""
    anchors = W.resolve_anchors(focus_driver="El_Nino", graph=real, max_contracts=2)
    assert len(anchors) == 35                                   # every board carrying the id
    assert {a.source for a in anchors} == {"focus_driver"}
    assert all(a.driver_id == "El_Nino" for a in anchors)


def test_AMENDMENT_1_positioning_as_SUBJECT_is_the_exception_to_context_only(real):
    """The R9 guard's MEASURED reason is positioning narrated as a CAUSE of the anchor's price; it does
    not apply when positioning IS the thing being explained. `subject` rides the anchor AND the row, so
    every consumer reads one field instead of re-deriving the exception."""
    anchors = W.resolve_anchors(focus_driver="cot_mm_positioning", graph=real,
                                positioning_ids=("cot_mm_positioning",))
    assert anchors and all(a.subject for a in anchors)
    bd = W.walk(graph=real, asof="2026-09-07", mode="deep", anchors=anchors[:2],
                state_fn=_flat_state_fn(), key_fn=_key_fn(), receipts={},
                turn_kind="outlook", positioning_ids=("cot_mm_positioning",))
    assert bd.subject_driver == "cot_mm_positioning"
    subj = [r for r in bd.rows if r.driver_id == "cot_mm_positioning"]
    assert subj and all(r.subject and not r.context_only for r in subj)


def test_a_focus_driver_anchor_set_is_RE_RANKED_by_that_drivers_own_state_after_wave_1(real):
    """Amendment 1's ranking runs in STAGE 1 and not at anchor time, because the state does not exist
    at anchor time and a ranking asserted before its input is a ranking of the alphabet.

    The driver here is SCOPE-KEYED (`drought`, one state per board) rather than global, because a
    globally-keyed driver has exactly one state by construction -- see the pin below."""
    anchors = W.resolve_anchors(focus_driver="drought", graph=real)[:4]
    loudest = anchors[-1].contract                                # the LAST by the graph's own order

    def state_fn(ref, node):
        return _state(ref, z=3.0 if node.contract == loudest else 0.1, pct=99.0)

    def only_drought(ref, node, *, turn_kind=""):
        """ONLY the subject driver carries a key here, and that is the realistic shape rather than a
        convenience: wave 1 ranks "anchor board first", so on a four-anchor turn a fixture that gave
        EVERY driver a live ref would spend the whole 32-key cap on the first board and leave the other
        three with no state to be ranked by. The estate's own supply is the same shape -- the newest
        census measures 12-13 DISTINCT series keys on the soybeans board, not one per driver."""
        if ref != "drought_z":
            return KeyPlan(key=None, status="unmapped_ref")
        return KeyPlan(key=SeriesKey(ref=ref, commodity=node.contract), status="ok", row={"t": 1})

    bd = W.walk(graph=real, asof="2026-09-07", mode="deep", anchors=anchors,
                state_fn=state_fn, key_fn=only_drought, receipts={})
    assert bd.anchors[0].contract == loudest


def test_a_GLOBALLY_keyed_focus_driver_cannot_be_re_ranked_and_keeps_the_GRAPHS_declared_order(real):
    """ONE unsigned state per `(silver_ref, resolved scope)` means every board carrying `El_Nino` points
    at the SAME StateRow, so "ranked by that driver's own state" is degenerate for a global ref: the
    states are identical by construction. The tie-break is the order `_driver_anchor_order` computed off
    the graph -- confidence, then the driver's own lag band, then slug. WITHOUT that term the set would
    fall back to alphabetical and DISCARD the graph's declared order, which is a curation nobody asked
    for arriving through a sort key."""
    anchors = W.resolve_anchors(focus_driver="El_Nino", graph=real)[:5]
    before = [a.contract for a in anchors]
    bd = W.walk(graph=real, asof="2026-09-07", mode="deep", anchors=anchors,
                state_fn=_flat_state_fn(), key_fn=_key_fn(), receipts={})
    assert [a.contract for a in bd.anchors] == before
    keys = {bd.row(a.contract, "El_Nino").series_key for a in anchors}
    assert keys == {"oni_climate|_global|"}, "one ONI read, one state, every board"


def test_COLD_START_is_OFF_in_V1_and_stamps_anchor_none_reading_NOTHING(real):
    """D26: `answer()` returns "No tracked contract matched this question." before `_answer_l2` on an
    empty route, so a zero-anchor turn never reaches the board and V1 keeps that return."""
    assert W.resolve_anchors(graph=real) == ()
    bd = W.walk(graph=real, asof="2026-09-07", mode="deep", anchors=(),
                state_fn=_flat_state_fn(), key_fn=_key_fn())
    assert bd.legs["board"] == {"outcome": "declined", "reason": "anchor_none", "reads": 0}
    assert bd.net_reads() == 0 and bd.rectangle() == [] and bd.rows == []


def test_COLD_START_is_BUILT_and_PRICED_IN_KEYS_so_the_deferral_is_a_decision(real):
    """Revision 2's "the board's loudest rows across ALL contracts anchor" priced no read set, which is
    why it was refused. This is the price: the GLOBAL-keyed KEYS first, then the top SCOPE-keyed KEYS by
    fan-out weight, cut at the mode's WAVE-1 cap, with the rest NAMED on the SB-X line.

    **KEYS, NOT REFS, and the S2 review MEASURED why that distinction is the whole mechanism.** The
    first build ranked the seven-row REF table and returned n = 9 against caps of 24 / 32 / 40 -- so the
    cut NEVER BOUND, `named` was ALWAYS empty, and sec 3.1's SB-X line ("no market was named; {n} of the
    estate's {m} series keys were read") could not print a number about anything. Priced in keys the cap
    binds on every tier and the leftovers are a real list."""
    for mode, cap in (("quick", 24), ("deep", 32), ("max", 40)):
        rs = W.cold_start_keys(B.board_knobs_of(mode), graph=real, key_fn=_key_fn())
        assert rs["cap"] == cap and rs["n"] == cap, "the cap BINDS -- it is a cut, not a formality"
        assert rs["global"][:2] == ["oni_climate|_global|", "iod_climate|_global|"], \
            "two reads buy 89 rows on 51 boards; nothing else in the estate is that cheap"
        assert rs["named"], "every key past the cut is NAMED -- the SB-X line's own {m} - {n}"
        assert rs["estate_keys"] > rs["n"], "the {m} the line is measured against"
        assert all(k not in rs["named"] for k in rs["keys"])
    tiny = W.cold_start_keys(B.BoardKnobs(8, 4, 0, 0, 4, 3, 0, 0, 2), graph=real, key_fn=_key_fn())
    assert tiny["n"] == 3 and len(tiny["named"]) > 100


def test_cold_start_anchors_only_when_it_is_THREADED_on(real):
    anchors = W.resolve_anchors(graph=real, cold_start=True)
    assert anchors and {a.source for a in anchors} == {"board_loudest"}


def test_COLD_START_anchors_the_boards_the_PRICED_KEYS_sit_on_and_READS_that_set(real):
    """MAJOR-3, closed. `board_loudest` must read the estate's loudest drivers; at the S2 landing it
    read the ALPHABETICALLY FIRST BOARD. `cold_start_keys` was called by nothing in `walk()`, so wave 1
    declared 927 keys over 36 anchor DAGs and the `anchor board first` term handed the whole cap to
    `arabica_coffee`'s own DAG -- 8 of 23 read refs were in the priced set and the rest were an
    accident of slug order. The pricer now runs FIRST, its positions ride the `anchor_order` term, and
    the plan IS the priced set, in the priced order, with every unadmitted key deferred BY NAME."""
    priced = W.cold_start_keys(B.board_knobs_of("deep"), graph=real, key_fn=_key_fn())
    bd = W.walk(graph=real, asof="2026-09-07", mode="deep", anchors=(), cold_start=True,
                state_fn=_flat_state_fn(), key_fn=_key_fn(), receipts={})
    # COLD START IS EXEMPT FROM THE ANCHOR CEILING THE S6 REVIEW ADDED, and this pin is why: the
    # pricer runs FIRST and wave 1's plan IS the priced set, so cutting the BOARDS would leave the plan
    # naming keys on boards the board no longer carries. The read budget here is bounded by the
    # pricer's own cap; the tape column and the render are the residual, on a lane that ships dark.
    assert bd.anchor_source == "board_loudest" and len(bd.anchors) == len(priced["boards"])
    assert set(bd.anchor_slugs) == set(priced["boards"])
    assert not [n for n in bd.notes if n.get("kind") == "anchor_cap"]
    w1 = bd.ledger.waves[1]
    assert [k.label for k in w1.plan] == priced["keys"], "the plan IS the priced set, in its order"
    assert w1.reads_used == priced["n"] == w1.reads_cap
    assert w1.deferred and w1.deferred_keys, "everything past the cut is DEFERRED, and it is NAMED"
    named = [n for n in bd.notes if n.get("kind") == "budget_cap" and n.get("wave") == 1]
    assert named and len(named[0]["names"]) == w1.deferred
    assert bd.rectangle() == [] and len(bd.rows) > 1000, "every node of every anchor DAG is still a ROW"


def test_COLD_STARTs_own_SB_X_line_has_a_PRODUCER(real):
    """Sec 3.1 specifies the line verbatim -- "no market was named; {n words} of the estate's {m words}
    series keys were read for the loudest drivers". At the S2 landing NO note of any kind was minted for
    cold start, so the sentence had no numbers. Every other cut on this board mints one."""
    bd = W.walk(graph=real, asof="2026-09-07", mode="quick", anchors=(), cold_start=True,
                state_fn=_flat_state_fn(), key_fn=_key_fn(), receipts={})
    note = [n for n in bd.notes if n["kind"] == "cold_start"][0]
    assert note["read"] == 24 == note["cap"] and note["estate_keys"] > note["read"]
    assert note["unread"] == len(note["names"]) > 0 and note["boards"] == len(bd.anchors)


def test_cold_start_stays_OFF_unless_it_is_THREADED_into_the_walk(real):
    """D26 in one assertion: the flag defaults OFF, and with it off a zero-anchor turn stamps
    `anchor_none` and reads nothing -- which is V1's shipped behaviour, not a gap."""
    off = W.walk(graph=real, asof="2026-09-07", mode="deep", anchors=(),
                 state_fn=_flat_state_fn(), key_fn=_key_fn())
    assert off.legs["board"]["reason"] == "anchor_none" and off.net_reads() == 0 and off.rows == []


# ── 3.6 THE SHARED-DRIVER FAN-OUT -- B7 ──────────────────────────────────────────────────────────────
def test_B7_the_owners_case_as_a_gate(real):
    """On a `soybeans_cbot` anchor the board carries a far row `(malaysian_crude_palm_oil_cme,
    El_Nino)` with `far_sign == '+'`, `far_lag == (2, 4)`, `far_ref == 'oni_lag_climate'`, resolving
    through `same_series_as` to the SAME series key as the anchor's own El_Nino row -- and
    `robusta_coffee`, `rough_rice_cbot` and `south_african_white_maize_jse` say "same direction" beside
    soy's "opposite direction", on separate lines, never reconciled (ruling 3)."""
    anchors = W.resolve_anchors(named=["soybeans_cbot"], graph=real)
    bd = W.walk(graph=real, asof="2026-09-07", mode="max", anchors=anchors,
                state_fn=_flat_state_fn(oni_climate={"z": 2.2, "pct": 98.0, "run": 4}),
                key_fn=_key_fn(), receipts={})
    soy = bd.row("soybeans_cbot", "El_Nino")
    assert soy.sign == "-" and soy.lag_band.min_q == 1 and soy.lag_band.max_q == 2
    fan = [e for e in bd.fan if e["driver_id"] == "El_Nino"][0]
    far = {f["contract"]: f for f in fan["far"]}
    palm = far["malaysian_crude_palm_oil_cme"]
    assert palm["sign"] == "+" and (palm["lag_band"].min_q, palm["lag_band"].max_q) == (2, 4)
    assert palm["ref"] == "oni_lag_climate"
    assert palm["series_key"] == soy.series_key, "the fold must land on ONE series key"
    assert palm["free"] is True, "a far state already on the board costs ZERO (the memo)"
    assert palm["sign_words"] == "in the same direction"
    for slug in ("robusta_coffee", "rough_rice_cbot", "south_african_white_maize_jse"):
        assert far[slug]["sign_words"] == "in the same direction", slug
    assert W.SIGN_WORDS[soy.sign] == "in the opposite direction"


def test_the_fan_INDEX_is_FREE_and_is_never_cut_while_far_STATES_are_priced(real):
    """EVERY row with a shared id -- loud or not -- fans as NAMED far boards at ZERO reads; only
    scope-keyed far STATE reads are priced. So a shared driver at rank 9 on Scan with a real anomaly is
    never silently unwalked: its far boards are named, and the SB-X line says which states were unread."""
    idx = W.fan_index(real)
    assert len(idx["El_Nino"]) == 35                       # the design's own measured figure
    assert sum(1 for v in idx.values() if len(v) >= 2) == 173
    anchors = W.resolve_anchors(named=["soybeans_cbot"], graph=real)
    scan = W.walk(graph=real, asof="2026-09-07", mode="quick", anchors=anchors,
                  state_fn=_flat_state_fn(), key_fn=_key_fn(), receipts={})
    named_far = sum(len(e["far"]) for e in scan.fan)
    assert named_far > 100, "the names are never cut"
    assert scan.ledger.waves[2].reads_used == 0, "Scan reads no far states at all (sec 7)"
    capped = [f for e in scan.fan for f in e["far"] if f["decline"] == "fan_cap"]
    assert capped, "far boards past `fan_k` decline BY NAME rather than vanishing"


def test_the_sign_is_read_off_the_FAR_edge_and_the_two_readings_are_never_reconciled(real):
    idx = W.fan_index(real)
    rows = W.far_rows(idx, "soybeans_cbot", "El_Nino")
    signs = {f["sign"] for f in rows}
    assert signs == {"-", "+"}, "16 ids disagree on non-zero sign across DAGs; none is curated"
    assert all(f["sign_words"] in W.SIGN_WORDS.values() for f in rows)


def test_the_far_order_is_GRAPH_declared_and_never_the_query(real):
    """`(far confidence rank, far lag_min_q, board slug)` -- sec 3.6. High confidence first."""
    rows = W.far_rows(W.fan_index(real), "soybeans_cbot", "El_Nino")
    assert rows[0]["confidence"] == "high"
    assert [r["contract"] for r in rows] == sorted(
        [r["contract"] for r in rows], key=lambda s: W._far_order(
            next(x for x in rows if x["contract"] == s)))


# ── 3.4 UPSTREAM -- B8 ───────────────────────────────────────────────────────────────────────────────
def test_B8_a_loud_grandparent_surfaces_with_its_OWN_band_and_no_driver_named_in_the_query(real):
    """The fixture path is `crude_oil -> soybean_crush_margin -> board_crush` on the shipped soybean
    DAG. crude_oil is LOUD; its child and grandchild are quiet; the SB-P row carries crude_oil's OWN
    declared band (0-2 quarters), NEVER a sum along the hops -- 0-2 plus 0-1 plus 0-1 would be 0-4, a
    horizon the graph never declared (doctrine M-4)."""
    anchors = W.resolve_anchors(named=["soybeans_cbot"], graph=real)

    def state_fn(ref, node):
        return _state(ref, z=3.4 if node.id == "crude_oil" else 0.05, pct=99.0 if
                      node.id == "crude_oil" else 50.5)

    bd = W.walk(graph=real, asof="2026-09-07", mode="max", anchors=anchors,
                state_fn=state_fn, key_fn=_key_fn(), receipts={})
    crude = [p for p in bd.paths if p["ancestor"] == "crude_oil" and p["bottom"] == "board_crush"]
    assert crude, "a loud grandparent must render an SB-P row"
    p = crude[0]
    assert p["hops"] == ("crude_oil", "soybean_crush_margin", "board_crush")
    assert (p["lag_band"].min_q, p["lag_band"].max_q) == (0, 2)      # crude_oil's OWN declared band
    assert p["depth"] == 2, "the design's own sentence: 'two hops upstream of the bean price'"
    assert p["band_is_the_ancestors_own"]
    assert bd.row("soybeans_cbot", "board_crush").state.z["value"] == 0.05      # grandchild: quiet
    assert bd.row("soybeans_cbot", "soybean_crush_margin").state.z["value"] == 0.05   # child: quiet
    ranked = W.rank_rows(bd.rows_for("soybeans_cbot"))
    assert ranked[0].driver_id == "crude_oil", "the loud grandparent leads its own board"
    assert "crude" not in "what does el nino do to soybeans".lower()   # no driver named in the query


def test_a_paths_band_can_never_be_SUMMED_even_by_accident():
    with pytest.raises(TypeError):
        parse_lag("0-2 quarters") + parse_lag("0-1 quarters")


def test_the_FULL_closure_is_walked_on_every_tier_and_only_the_RENDER_is_capped(real):
    """D27. Revision 2 borrowed `CW_DEEP_MAX_ORDER` 3 -- the shipped graph's TERMINAL depth on the
    walk's INTER-COMMODITY rev-links -- to cut a DIFFERENT graph whose own closure measures median 2,
    mean 3.58, max 26. The closure is walked whole; the mode caps only how many SB-P rows RENDER, and
    the paths past the cut are NAMED with `path: render_cap`."""
    anchors = W.resolve_anchors(named=["soybeans_cbot"], graph=real)
    kw = dict(graph=real, asof="2026-09-07", anchors=anchors, state_fn=_flat_state_fn(),
              key_fn=_key_fn(), receipts={})
    scan, casc = W.walk(mode="quick", **kw), W.walk(mode="max", **kw)
    shared = ({r.driver_id for r in scan.rows if r.legs.get("loud")}
              & {r.driver_id for r in casc.rows if r.legs.get("loud")})
    assert shared, "the tiers overlap on at least one loud driver"
    for did in sorted(shared):
        # THE PRODUCER's output, not the board's list: the walk deduplicates a path by `(top, bottom)`
        # across loud seeds, so a wider tier can attribute one row to a different seed. The CLOSURE is
        # what must not shrink, and this is where it is computed.
        a = {(p["ancestor"], p["bottom"], p["depth"])
             for p in W.ancestor_paths(real, scan, "soybeans_cbot", did)}
        b = {(p["ancestor"], p["bottom"], p["depth"])
             for p in W.ancestor_paths(real, casc, "soybeans_cbot", did)}
        assert a == b, f"{did}: the closure must not shrink with the tier"
    # S7 (2026-09-11): Scan's path_render_k moved 2 -> 1 -- the ratified quick RENDER cap (SB-P was 3.7%
    # of the quick block; the walk's own path rank is the cut). The CLOSURE above is what must not shrink;
    # the render count is the tier's knob, read from BOARD_PRESETS['quick'], and it is 1 on Scan now.
    assert sum(1 for p in scan.paths if p["rendered"]) == 1
    assert sum(1 for p in casc.paths if p["rendered"]) == 8
    assert all(p["decline"] == "render_cap" for p in casc.paths if not p["rendered"])
    assert any(n["kind"] == "path_render_cap" and n["names"] for n in casc.notes)
    assert max(p["depth"] for p in scan.paths) >= 3, \
        "a third-hop cause is walked on SCAN -- CW_DEEP_MAX_ORDER is not the board's constant"


# ── 3.5 CONVERGENCE -- B16 ───────────────────────────────────────────────────────────────────────────
def test_B16_a_convergence_row_is_ORDERING_information_and_never_a_verdict(real):
    """No rendered field may say "met", "fires" or "the regime is". Revision 1 handed `graph.regimes`
    the mode-sized rank cut, which made "met" a function of LIST LENGTH and MODE: on Cascade every
    mapped soybean driver inside the cut of 24 was "active" regardless of any z, so `bearish_glut`
    (3 of 5) read met on Cascade and not on Scan at ONE as-of."""
    anchors = W.resolve_anchors(named=["malaysian_crude_palm_oil_cme"], graph=real)
    bd = W.walk(graph=real, asof="2026-09-07", mode="max", anchors=anchors,
                state_fn=_flat_state_fn(), key_fn=_key_fn(), receipts={})
    assert bd.convergence
    blob = " ".join(str(v) for r in bd.convergence for k, v in r.items()
                    if k in ("name", "direction")).lower()
    for banned in W.CONVERGENCE_BANNED_WORDS:
        assert banned not in blob
    for r in bd.convergence:
        assert set(r) >= {"n_matched", "n_declared", "threshold", "matched", "loud_k"}
        assert "fired" not in r and "met" not in r


def test_B16_EVERY_declared_pattern_gets_a_row_not_only_the_ones_that_would_FIRE(real):
    """A pattern at one of three is a row that SAYS one of three. `graph.regimes` answers the FIRING
    question and belongs to `firing.fire_contract` over DECLARED bands; the board asks a different
    question and must not borrow that answer."""
    palm = real.contracts["malaysian_crude_palm_oil_cme"]
    rows = W.convergence_rows(real, "malaysian_crude_palm_oil_cme", {"El_Nino"}, loud_k=24)
    assert len(rows) == len(palm.convergence)
    low = [r for r in rows if r["n_matched"] < r["threshold"]]
    assert low, "a pattern below its own threshold is still a row"


def test_B16_the_palm_amplifier_renders_when_both_when_ids_are_loud_and_declines_when_they_are_not(real):
    """Scenario 3's own `(crude_oil_price, biodiesel_mandate) amplifies` line on palm's
    `biodiesel_energy_floor` -- the 277 `Interaction` rows are the graph's ONLY amplifier semantics
    (D24) and they are not thrown away and not fired."""
    both = W.convergence_rows(real, "malaysian_crude_palm_oil_cme",
                              {"crude_oil_price", "biodiesel_mandate"}, loud_k=24)
    floor = [r for r in both if r["name"] == "biodiesel_energy_floor"][0]
    amp = [i for i in floor["interactions"] if set(i["when"]) == {"crude_oil_price",
                                                                 "biodiesel_mandate"}][0]
    assert amp["rendered"] and amp["effect"] == "amplifies" and amp["decline"] is None
    one = W.convergence_rows(real, "malaysian_crude_palm_oil_cme", {"crude_oil_price"}, loud_k=24)
    floor1 = [r for r in one if r["name"] == "biodiesel_energy_floor"][0]
    amp1 = [i for i in floor1["interactions"] if set(i["when"]) == {"crude_oil_price",
                                                                    "biodiesel_mandate"}][0]
    assert not amp1["rendered"] and amp1["decline"] == "when_not_all_loud"
    assert floor1["n_matched"] == 1, "the PATTERN row still renders when its amplifier does not"


def test_the_convergence_row_carries_NO_ungoverned_signal_note(real):
    """MINOR (b) OF THE S6 SECOND VERIFY. `ConvergenceSignal.note` was copied onto every convergence
    row and READ BY NOTHING -- `render.sb_convergence` has no such key -- so the board carried a second
    ungoverned config-prose string, out of the same gitignored DAG files as `Interaction.note`, one
    edit away from a template that would splice it into a rendered line with no fence in front of it.

    THE COPY IS DROPPED RATHER THAN GOVERNED, which is the cheaper of the two doctrinal moves and the
    one that leaves no surface: a row that wants the note later takes it from the signal and renders it
    through `render.governed_note` and the assembled-row fence beside it, which is where the grading
    lives. The INTERACTION note stays on its row, because a row does render it.

    THE SIGNALS STILL CARRY THEIR NOTES -- nothing was deleted from the graph, and the assertion below
    is that at least one shipped signal has prose the row no longer copies, so this pin fails if the
    copy comes back rather than merely passing on an empty estate."""
    rows = W.convergence_rows(real, "malaysian_crude_palm_oil_cme",
                              {"crude_oil_price", "biodiesel_mandate"}, loud_k=24)
    assert rows
    for r in rows:
        assert "note" not in r, r["name"]
        for it in r["interactions"]:
            assert "note" in it              # the interaction's own note is RENDERED and stays
    with_prose = [s for c in real.contracts.values()
                  for s in (getattr(c, "convergence", ()) or ()) if str(getattr(s, "note", "") or "")]
    assert with_prose, "no shipped ConvergenceSignal carries a note -- this pin no longer proves it"


def test_a_two_of_three_pattern_reports_two_of_three_and_its_own_threshold():
    d = [_driver("a"), _driver("b"), _driver("c")]
    sig = cs.ConvergenceSignal(name="p", direction="+", requires_any_n_of=3, drivers=["a", "b", "c"])
    g = _graph(c=cs.CausalContract(contract="c", drivers=d, convergence=[sig]))
    row = W.convergence_rows(g, "c", {"a", "b"}, loud_k=8)[0]
    assert (row["n_matched"], row["n_declared"], row["threshold"]) == (2, 3, 3)


# ── 3.7 DATED EVENTS -- the date is a RULE, not "the newest receipt" ─────────────────────────────────
def test_the_event_date_is_max_event_date_broken_by_PRECISION_then_the_EARLIER_publication():
    """Critic G17's rule. An analysis piece published a month after the event carries the event's own
    `event_date` when the extractor stamped one, and otherwise contributes no date at all."""
    rs = [{"date": "2026-03-02", "event_date": "2026-03-01", "event_date_precision": "day"},
          {"date": "2026-04-01", "event_date": "2026-03", "event_date_precision": "month"},
          {"date": "2026-04-15", "event_date": None}]
    assert W.event_date_for(rs, "2026-09-07") == ("2026-03-01", "day")
    tie = [{"date": "2026-05-01", "event_date": "2026-03-01", "event_date_precision": "month"},
           {"date": "2026-04-01", "event_date": "2026-03-01", "event_date_precision": "day"}]
    assert W.event_date_for(tie, "2026-09-07") == ("2026-03-01", "day")


def test_a_receipt_dated_after_the_asof_NEVER_anchors_an_event_row():
    rs = [{"date": "2026-09-01", "event_date": "2027-01-01", "event_date_precision": "day"}]
    assert W.event_date_for(rs, "2026-09-07") == (None, "")


def test_an_event_stays_on_the_board_and_projects_forward_until_its_band_EXPIRES():
    band = parse_lag("0-2 quarters")
    assert W.event_is_open("2026-06-01", band, "2026-09-07")        # inside the six-month window
    assert not W.event_is_open("2025-01-01", band, "2026-09-07")    # expired: history with an age clause
    assert W.event_is_open("2020-01-01", parse_lag("structural"), "2026-09-07")
    assert not W.event_is_open("2026-06-01", parse_lag("not a lag string"), "2026-09-07")


# ── 3.8 THE BUDGET -- B3 and its atomicity ───────────────────────────────────────────────────────────
def _wide(n_drivers=60, slug="c"):
    ds = [_driver(f"d{i:02d}", silver_ref=f"ref{i:02d}", silver_status="available")
          for i in range(n_drivers)]
    return _graph(**{slug: cs.CausalContract(contract=slug, drivers=ds)})


def test_B3_each_wave_is_priced_BEFORE_its_first_fetch_and_never_exceeds_its_cap():
    g = _wide()
    anchors = (B.Anchor(contract="c", source="named"),)
    for mode in ("quick", "deep", "max"):
        bd = W.walk(graph=g, asof="2026-09-07", mode=mode, anchors=anchors,
                    state_fn=_flat_state_fn(), key_fn=_key_fn(), receipts={})
        for n, w in bd.ledger.waves.items():
            assert w.priced_before_fetch, (mode, n)
            assert w.reads_used <= w.reads_cap, (mode, n, w.reads_used, w.reads_cap)
        assert bd.rectangle() == [], mode


def test_B3_a_price_over_the_cap_yields_NAMED_deferrals_equal_to_declared_minus_read():
    g = _wide(n_drivers=60)
    bd = W.walk(graph=g, asof="2026-09-07", mode="quick",
                anchors=(B.Anchor(contract="c", source="named"),),
                state_fn=_flat_state_fn(), key_fn=_key_fn(), receipts={})
    w1 = bd.ledger.waves[1]
    assert w1.series_declared == 60 and w1.reads_used == 24        # Scan's wave-1 cap
    assert w1.deferred == 36 and len(w1.deferred_keys) == 36
    assert w1.series_declared - w1.read - w1.declined == w1.deferred
    named = [n for n in bd.notes if n.get("kind") == "budget_cap" and n.get("wave") == 1]
    assert named and len(named[0]["names"]) == 36, "every dropped key is NAMED"
    assert bd.ledger.budget_capped == 36
    dropped = [r for r in bd.rows if r.state is not None and r.state.status == "budget_cap"]
    assert len(dropped) == 36, "a budget cut is a ROW that says so, never a silence"


def test_B1_the_rectangle_closes_at_EVERY_early_return():
    g = _wide(n_drivers=5)
    a = (B.Anchor(contract="c", source="named"),)
    assert W.walk(graph=g, asof="2026-09-07", mode="deep", anchors=a, lane="numbers_only",
                  state_fn=_flat_state_fn(), key_fn=_key_fn()).rectangle() == []
    assert W.walk(graph=g, asof="2026-09-07", mode="deep", anchors=(),
                  state_fn=_flat_state_fn(), key_fn=_key_fn()).rectangle() == []
    assert W.walk(graph=g, asof="2026-09-07", mode="deep", anchors=a, stage2=False,
                  state_fn=_flat_state_fn(), key_fn=_key_fn()).rectangle() == []
    assert W.walk(graph=g, asof="2026-09-07", mode="deep", anchors=a,
                  state_fn=_flat_state_fn(), key_fn=_key_fn(), receipts={}).rectangle() == []


def test_B3_the_pool_never_exceeds_width_2(real):
    anchors = W.resolve_anchors(named=["soybeans_cbot"], graph=real)
    bd = W.walk(graph=real, asof="2026-09-07", mode="max", anchors=anchors,
                state_fn=_flat_state_fn(), key_fn=_key_fn(), receipts={}, width=2)
    assert bd.recency["width_peak"] <= 2


def test_B3_a_read_that_declines_by_name_is_counted_and_never_falls_back_to_athena():
    """The board's reads go through `pgnumbers.pg_query` under its OWN counter and decline
    `pool_exhausted` / `pg_timeout` BY NAME -- never `query_fn`'s per-request Athena fallback, whose
    planning floor is ~2-3 s per query (D20). `BoardPoolDeclined` is arm A's bar and its bar is 0."""
    g = _wide(n_drivers=4)

    def state_fn(ref, node):
        return _state(ref, status="pool_exhausted", tier="series", reads=1)

    bd = W.walk(graph=g, asof="2026-09-07", mode="deep",
                anchors=(B.Anchor(contract="c", source="named"),),
                state_fn=state_fn, key_fn=_key_fn(), receipts={})
    assert bd.ledger.pool_declined == 4
    assert bd.ledger.waves[1].declined == 4 and bd.rectangle() == []


def test_the_ANCHOR_BOARD_FIRST_term_makes_wave_1_a_FIRST_BOARD_budget_and_NAMES_the_rest(real):
    """A MEASURED CONSEQUENCE OF THE DESIGN'S OWN WAVE-1 ORDER, pinned here so it cannot move quietly.

    Sec 3.8 ranks wave-1 keys by "(anchor board first; then the number of node rows sharing the key;
    then confidence rank; then ref)". On a FOUR-NAMED-MARKET question -- the case sec 16's Amendment 2
    creates by making every named market an anchor -- the first term dominates: board one fills the cap
    and the later boards are served only by keys the first board already bought. MEASURED at this
    landing on wheat / corn / soybeans / palm (185 rows, 128 distinct wave-1 keys), rows carrying a
    MEASURED state per board:

        Scan     (cap 24)   wheat 34 | corn 2 | soybeans 2 | palm 2
        Analysis (cap 32)   wheat 42 | corn 2 | soybeans 2 | palm 2
        Cascade  (cap 40)   wheat 44 | corn 21 | soybeans 2 | palm 2

    The two rows the later boards do carry are the SHARED ones -- the global ONI key the first board
    already paid for, serving every board that declares El Nino at zero extra cost, which is the fan-out
    weighting doing exactly its job. Against the shipped map's thinner supply the split is much less
    extreme (Scan: 26 | 21 | 2 | 4), because fewer refs are live and more keys are shared.

    NOTHING IS SILENT. Every dropped key is NAMED on the `budget_cap` SB-X row, every named board is
    WHOLE on the board with all its rows, and the rectangle closes on both waves.

    THIS TEST DOES NOT DECIDE THE QUESTION. The design's sentence is explicit, so the walk implements it
    literally. Whether wave 1 should instead round-robin the cap across anchor boards, or reserve a
    per-anchor floor, is a DESIGN change for S4's census to price and the owner to take -- Amendment 2's
    own promise is that a named market is never DROPPED, and it is not: it is un-READ, which is a
    different fact and one the board says out loud. The pin exists so the answer is a decision rather
    than a discovery."""
    named = ["soft_red_winter_wheat_cbot", "corn_cbot", "soybeans_cbot",
             "malaysian_crude_palm_oil_cme"]
    anchors = W.resolve_anchors(named=named, graph=real)
    bd = W.walk(graph=real, asof="2026-09-07", mode="deep", anchors=anchors,
                state_fn=_flat_state_fn(), key_fn=_key_fn(), receipts={})
    measured = {}
    for r in bd.rows:
        if r.state is not None and r.state.status == "ok" and r.series_key:
            measured[r.contract] = measured.get(r.contract, 0) + 1
    first = anchors[0].contract
    assert measured[first] > 10 * max(measured.get(a.contract, 0) for a in anchors[1:])
    assert all(measured.get(a.contract, 0) > 0 for a in anchors[1:]), \
        "the SHARED global key still reaches every board at zero extra cost"
    shared = {bd.row(a.contract, "El_Nino").series_key for a in anchors
              if bd.row(a.contract, "El_Nino") is not None}
    assert shared == {"oni_climate|_global|"}, "one ONI read, every board that declares El Nino"
    named_keys = [n for n in bd.notes if n.get("kind") == "budget_cap" and n.get("wave") == 1]
    assert named_keys and named_keys[0]["names"], "every starved key is NAMED, never silent"
    assert bd.rectangle() == []
    assert len(bd.rows) == sum(len(real.contracts[c].drivers) for c in named), \
        "every named board is still WHOLE on the board -- only its STATE was not read"


def test_one_SHARED_key_is_priced_ONCE_however_many_boards_carry_it(real):
    """Sec 1.1: "the read count of a turn is the DISTINCT series-key count". MEASURED at this landing as
    a real defect in the first cut of the pricer: wave-1 keys were deduplicated by
    `(label, contract, driver_id)`, so the soybean board's `El_Nino` and the palm board's
    `oni_lag_climate` -- which fold onto ONE `(oni_climate, _global)` key through `same_series_as` --
    were priced as TWO reads. The fold that exists to make 35 boards share one reading was costing a
    read instead of saving one, and the cap shrank by every fold on the board."""
    anchors = W.resolve_anchors(named=["soybeans_cbot", "malaysian_crude_palm_oil_cme"], graph=real)
    bd = W.walk(graph=real, asof="2026-09-07", mode="max", anchors=anchors,
                state_fn=_flat_state_fn(), key_fn=_key_fn(), receipts={})
    plan_labels = [k.label for k in bd.ledger.waves[1].plan]
    assert len(plan_labels) == len(set(plan_labels)), "a key appears in the plan at most once"
    assert plan_labels.count("oni_climate|_global|") <= 1
    soy = bd.row("soybeans_cbot", "El_Nino")
    palm = bd.row("malaysian_crude_palm_oil_cme", "El_Nino")
    assert soy.series_key == palm.series_key == "oni_climate|_global|"
    assert soy.state is palm.state, "two rows, two signs, ONE unsigned state (ruling 3)"
    assert soy.sign == "-" and palm.sign == "+"


def test_the_wave_1_order_puts_the_anchor_board_first_then_the_key_that_serves_the_most_rows():
    keys = [W.PricedKey("k_rare", "r", "c", "d1", 0, 1, 1),
            W.PricedKey("k_shared", "s", "c", "d2", 0, 11, 1),
            W.PricedKey("k_far", "f", "x", "d3", 1, 99, 2)]
    plan = W.price_wave1(keys, cap=2)["plan"]
    assert [k.label for k in plan] == ["k_shared", "k_rare"]


def test_a_FREE_key_is_never_counted_against_the_cap_nor_deferred():
    keys = [W.PricedKey(f"paid{i}", "r", "c", f"d{i}", 0, 1, 1) for i in range(3)]
    keys += [W.PricedKey("global", "oni_climate", "c", "d9", 0, 40, 1, free=True)]
    cut = W.price_wave1(keys, cap=2)
    assert len(cut["plan"]) == 2 and len(cut["deferred"]) == 1 and len(cut["free"]) == 1
    assert cut["declared"] == 4


def test_the_wave_2_trim_order_is_legB_then_receipts_then_far_keys_then_benchmarks():
    """Analog benchmarks trim LAST because a leg-A outcome with no benchmark is an outcome nobody can
    place (sec 3.8)."""
    kn = B.BoardKnobs(24, 16, 2, 5, 12, 40, 12, 5, 8)          # a deliberately OVER-COMMITTED wave 2
    assert B.check_knobs(kn, legb_cells=9), "an over-committed table is a LINT error, not a surprise"
    far = [W.PricedKey(f"f{i}", "r", "x", f"d{i}", 1, 1, 1) for i in range(20)]
    p = W.price_wave2(far_keys=far, analog_benchmarks=["b"] * 10, analog_receipts=["r"] * 5,
                      legb_cells=9, legb_on=True, knobs=kn)
    assert p["n_planned"] <= 12
    assert p["columns"]["legb"] == (), "leg-B cells trim FIRST"
    assert len(p["columns"]["analog_receipts"]) < 5, "analog receipts trim SECOND"
    assert len(p["columns"]["analog_benchmark"]) == 10, "benchmarks trim LAST and were never reached"
    assert p["deferred"]["legb"] and p["deferred"]["analog_receipts"]


def test_under_the_DERIVED_shape_the_columns_always_sum_to_the_total_so_the_trim_never_fires():
    """A property worth writing down rather than discovering later: because every wave-2 column derives
    from the nine knobs and `far` is the residual, a SHIPPED tier's columns sum to its total exactly and
    the trim order of sec 3.8 is unreachable there. It stays implemented because the design declares it
    and because a future knob table can over-commit -- and when one does, `check_knobs` says so first."""
    for mode in ("quick", "deep", "max"):
        kn = B.board_knobs_of(mode)
        for on in (False, True):
            sh = B.wave2_shape(kn, legb_cells=B.legb_cells_of(mode), legb_on=on)
            assert (sh["far"] + sh["analog_benchmark"] + sh["analog_receipts"] + sh["legb"]
                    == sh["total"]), (mode, on)


def test_wave_2s_rectangle_covers_what_THIS_sitting_EXECUTES_and_RESERVES_the_analog_seats(real):
    """The analog columns of sec 3.8's wave-2 table are PRICED here and SPENT by S3's analog leg. They
    are reserved against the wave-2 cap -- which is what stops a later leg from over-spending it -- and
    they are NOT counted as read, because a rectangle that reported a reserved seat as a read would tell
    the same lie a budget cut reading as a zero tells, from the other direction."""
    anchors = W.resolve_anchors(named=["soybeans_cbot"], graph=real)
    bd = W.walk(graph=real, asof="2026-09-07", mode="max", anchors=anchors,
                state_fn=_flat_state_fn(), key_fn=_key_fn(), receipts={})
    reserved = [n for n in bd.notes if n["kind"] == "wave2_reserved"][0]["columns"]
    assert reserved == {"analog_benchmark": 10, "analog_receipts": 5, "legb": 0}
    w2 = bd.ledger.waves[2]
    assert w2.closed and w2.reads_used <= w2.reads_cap
    assert bd.legs["analog"]["outcome"] == "not_reached", "the seats are reserved, the leg is S3's"
    # THE SEATS ARE A CAP AND ARE RECORDED AS ONE. `evidence_borrows` used to be assigned this number
    # and `state.seam.counters` published it as `BoardEvidenceBorrows` -- whose 10.5 definition is
    # "analog receipt reads on the evidence pool" -- so it read 5 on every fired Cascade board while
    # `analogs._receipts_for` returned [] at zero reads: arm A's evidence-pool pressure taken from a
    # number no read produced (S6 review, major 6). A BORROW IS COUNTED WHERE A BORROW HAPPENS.
    assert bd.ledger.evidence_cap == 5, "the RESERVED analog receipt seats"
    assert bd.ledger.benchmark_cap == 10, "the RESERVED analog benchmark seats"
    assert bd.ledger.evidence_borrows == 0, "no receipt_fn is wired, so no borrow happened"
    assert bd.ledger.benchmark_reads == 0, "no benchmark_fn is wired, so no read happened"
    # AND AN UNWIRED ANALOG LEG RESERVES NEITHER COLUMN (major 7): reserving 15 reads no producer can
    # spend put them on the WALK's own runaway ceiling through `cascade._board_declared_cap`.
    dark = W.walk(graph=real, asof="2026-09-07", mode="max", anchors=anchors,
                  state_fn=_flat_state_fn(), key_fn=_key_fn(), receipts={}, analog_reads=False)
    dcols = [n for n in dark.notes if n["kind"] == "wave2_reserved"][0]["columns"]
    assert dcols == {"analog_benchmark": 0, "analog_receipts": 0, "legb": 0}
    assert dark.ledger.waves[2].reads_cap == w2.reads_cap - 15
    assert dark.ledger.waves[2].closed and dark.rectangle() == []


def test_a_FAR_read_that_declines_by_name_is_counted_in_wave_2s_own_rectangle():
    """`BoardPoolDeclined` is arm A's bar and its bar is 0, so a wave-2 decline the ledger never saw
    would make the bar unmeasurable. MEASURED as a gap in the first cut: wave 1 counted its pool
    declines and wave 2 counted none, so a far state that never came back was reported as READ."""
    a = _driver("shared", silver_ref="shared_ref", silver_status="available")
    g = _graph(c1=cs.CausalContract(contract="c1", drivers=[a]),
               c2=cs.CausalContract(contract="c2", drivers=[a]))

    def key_fn(ref, node, *, turn_kind=""):
        return KeyPlan(key=SeriesKey(ref=ref, commodity=node.contract), status="ok", row={"t": 1})

    def state_fn(ref, node):
        if node.contract == "c2":
            return _state(ref, status="pg_timeout")
        return _state(ref, z=3.0, pct=99.0)

    bd = W.walk(graph=g, asof="2026-09-07", mode="max",
                anchors=(B.Anchor(contract="c1", source="named"),),
                state_fn=state_fn, key_fn=key_fn, receipts={})
    w2 = bd.ledger.waves[2]
    assert w2.series_declared == 1 and w2.declined == 1 and w2.read == 0
    assert bd.ledger.pool_declined == 1 and w2.closed


# ── 3.3 / D11 THE TWO STAMPED STAGES -- B17 ──────────────────────────────────────────────────────────
def test_B17_stage_1_stamps_before_stage_2_and_stage_2_NEVER_re_ranks_stage_1(real):
    """Stage 1 (numeric state, the rank, wave 1) runs AFTER `pl.grounded_subgraph` and BEFORE
    `pl.ground`; stage 2 (receipts, EVENT rows, the text-tier rank, wave 2) runs AFTER `ground`. `n.
    evidence` does not exist before `ground()`, which is exactly why there are two."""
    anchors = W.resolve_anchors(named=["soybeans_cbot"], graph=real)
    kw = dict(graph=real, asof="2026-09-07", mode="deep", anchors=anchors,
              state_fn=_flat_state_fn(), key_fn=_key_fn())
    one = W.walk(stage2=False, **kw)
    assert one.stage_done == {1: True, 2: False} and one.stage_ms[2] == 0.0
    assert one.ledger.waves[2].reads_used == 0
    both = W.walk(receipts={}, **kw)
    assert both.stage_done == {1: True, 2: True}
    assert both.trace()["stage_ms"][1] > 0 and both.trace()["stage_ms"][2] > 0
    before = {r.key: r.rank for r in one.rows}
    after = {r.key: r.rank for r in both.rows}
    assert before == after, "stage 2 APPENDS; it never re-ranks stage 1's rows"


def test_stage_2_may_still_ADD_an_open_event_row_to_the_loud_set_without_re_ranking(real):
    """An OPEN EVENT row is loud BY CONSTRUCTION and cannot be known before receipts exist (sec 3.2 /
    3.3 step 5). Joining the loud set is an INCLUSION; the rank tuple it was given in stage 1 stands."""
    anchors = W.resolve_anchors(named=["malaysian_crude_palm_oil_cme"], graph=real)
    rs = {"biodiesel_mandate": [{"date": "2026-06-05", "event_date": "2026-06-01",
                                 "event_date_precision": "day"}]}
    bd = W.walk(graph=real, asof="2026-09-07", mode="quick", anchors=anchors,
                state_fn=_flat_state_fn(), key_fn=_key_fn(), receipts=rs)
    row = bd.row("malaysian_crude_palm_oil_cme", "biodiesel_mandate")
    assert row.event_date == "2026-06-01" and row.event_open
    assert row.legs["loud"] is True
    assert row.rank == W.rank_key(row)


# ── 6.7 THE TAGS -- B13 ──────────────────────────────────────────────────────────────────────────────
def test_B13_every_leg_carries_a_closed_outcome_and_a_closed_reason(real):
    anchors = W.resolve_anchors(named=["soybeans_cbot"], graph=real)
    bd = W.walk(graph=real, asof="2026-09-07", mode="deep", anchors=anchors,
                state_fn=_flat_state_fn(), key_fn=_key_fn(), receipts={})
    assert set(bd.legs) == set(W.ALL_LEGS)
    for leg, rec in bd.legs.items():
        assert rec["outcome"] in B.OUTCOMES, leg
        if rec["outcome"] == "declined":
            assert B.check_reason(leg, rec["reason"]) is None, (leg, rec)
        else:
            assert rec["reason"] is None, (leg, rec)


def test_B13_a_leg_the_walk_did_not_enter_is_stamped_not_reached_BY_THE_WALK(real):
    anchors = W.resolve_anchors(named=["soybeans_cbot"], graph=real)
    bd = W.walk(graph=real, asof="2026-09-07", mode="deep", anchors=anchors,
                state_fn=_flat_state_fn(), key_fn=_key_fn(), receipts={})
    for leg in ("analog", "watch", "render", "tape"):
        assert bd.legs[leg]["outcome"] == "not_reached", leg


@pytest.mark.parametrize("lane", list(B.OFF_LANES))
def test_the_four_off_lanes_each_stamp_their_own_word_and_read_NOTHING(lane):
    """Sec 7's lane gate, so `BoardFired` is absent-when-inapplicable rather than silently zero:
    `numbers_only` never reaches `_answer_l2` at all, the `onehop` rollback body has no
    `grounded_subgraph`, the trivial router returns above dispatch, and `_guardrail_check` refuses."""
    g = _wide(n_drivers=4)
    bd = W.walk(graph=g, asof="2026-09-07", mode="deep",
                anchors=(B.Anchor(contract="c", source="named"),), lane=lane,
                state_fn=_flat_state_fn(), key_fn=_key_fn())
    assert bd.legs["board"] == {"outcome": "declined", "reason": f"lane_off:{lane}", "reads": 0}
    assert bd.net_reads() == 0 and bd.rows == [] and bd.rectangle() == []


# ── 1.3 EVERY TIER IS A ROW ──────────────────────────────────────────────────────────────────────────
def test_an_unmeasured_driver_is_a_ROW_that_says_so_and_the_walk_traverses_every_tier():
    ds = [_driver("measured", silver_ref="r", silver_status="available"),
          _driver("planned_one", silver_status="planned"),
          _driver("none_one", silver_status="none"),
          _driver("declared_unserved", silver_ref="ghost", silver_status="available")]
    g = _graph(c=cs.CausalContract(contract="c", drivers=ds))

    def key_fn(ref, node, *, turn_kind=""):
        if ref == "ghost":
            return KeyPlan(key=None, status="unmapped_ref")
        return KeyPlan(key=SeriesKey(ref=ref, commodity=node.contract), status="ok", row={"t": 1})

    bd = W.walk(graph=g, asof="2026-09-07", mode="deep",
                anchors=(B.Anchor(contract="c", source="named"),),
                state_fn=_flat_state_fn(), key_fn=key_fn, receipts={})
    tiers = {r.driver_id: r.coverage_tier for r in bd.rows}
    assert tiers == {"measured": "series", "planned_one": "planned_text_only",
                     "none_one": "none_text_only",
                     "declared_unserved": "declared_available_unserved"}
    assert len(bd.rows) == 4, "no filter anywhere removes a node from the board"
    assert bd.row("c", "declared_unserved").state.status == "unmapped_ref"


def test_positioning_is_context_only_UNLESS_it_is_the_subject():
    ds = [_driver("cot_mm_positioning", silver_ref="pos", silver_status="available")]
    g = _graph(c=cs.CausalContract(contract="c", drivers=ds))

    def key_fn(ref, node, *, turn_kind=""):
        return KeyPlan(key=SeriesKey(ref=ref, commodity=node.contract), status="ok",
                       context_only=True, row={"t": 1})

    plain = W.walk(graph=g, asof="2026-09-07", mode="deep",
                   anchors=(B.Anchor(contract="c", source="named"),),
                   state_fn=_flat_state_fn(), key_fn=key_fn, receipts={})
    assert plain.row("c", "cot_mm_positioning").context_only is True
    subj = W.walk(graph=g, asof="2026-09-07", mode="deep",
                  anchors=(B.Anchor(contract="c", source="focus_driver",
                                    driver_id="cot_mm_positioning", subject=True),),
                  state_fn=_flat_state_fn(), key_fn=key_fn, receipts={})
    assert subj.row("c", "cot_mm_positioning").context_only is False


# ── 3.9 WHAT quantify IS HANDED ──────────────────────────────────────────────────────────────────────
def test_the_walk_produces_the_board_request_shape_S6_will_thread(real):
    anchors = W.resolve_anchors(named=["soybeans_cbot"], graph=real)
    bd = W.walk(graph=real, asof="2026-09-07", mode="deep", anchors=anchors,
                question="what happens over the next two quarters?",
                state_fn=_flat_state_fn(), key_fn=_key_fn(), receipts={})
    req = bd.request()
    assert req["horizon_months"] == 6
    assert req["order"] and all(isinstance(k, tuple) and len(k) == 2 for k in req["order"])
    assert req["budget"]["spent"] == bd.net_reads() <= req["budget"]["cap"]
    assert req["windows"], "the state-chosen anchor windows `_derive_windows` will take as its `near`"
    for key, win in req["windows"].items():
        # `reading` IS THE S7b R6 ADDITION AND `near` IS THE PIN THAT MATTERS. The window a WATCH row
        # counts from is the READING's own date; the window SB-J counts from is the RUN's start, and
        # `projection_window`'s own docstring declares that ("a lag runs from the state to the effect",
        # Judge 2). MEASURED on the 09-11 non-obvious prototype: 10 of its 60 rows rendered a
        # 1997-12..1998-06 window for a 2026 reading because the watch row took the run start. The two
        # questions get two fields; `near` is asserted UNMOVED below, which is the tripwire -- if `near`
        # ever changes, every SB-J line on every board-on turn changes with it.
        assert set(win) == {"near", "reading", "state_date", "knowledge_date", "analog_dates"}
        st = bd.row(*key).state
        near_want = ((st.run or {}).get("since_date")
                     if st.run and not st.run.get("declined") else None) or st.level_date
        assert win["near"] == near_want, "SB-J's anchor moved; the whole projection class moves with it"
        assert win["reading"] == st.level_date


def test_board_ORDER_is_the_RANK_order_and_never_the_DAGs_insertion_order(real):
    """MAJOR-1, closed, and it is the ONE payload key S6 threads (sec 3.9 item 1): `_select_nodes`
    (cascade.py:306) returns `board.order` filtered to `sg.nodes`, so S22 retires only if that tuple is
    RANKED.

    MEASURED AT THE S2 REVIEW: `request()` emitted `tuple(r.key for r in self.rows if r.rank)`, and
    because `rank_key` always returns a 7-tuple the `if r.rank` filter admitted EVERY row -- the payload
    was the DAG's insertion order byte-for-byte on 47 of 47 rows, and the loudness this whole engine
    computes would have reordered nothing at quantify. The old deck asserted only that the entries were
    2-tuples, which is why it passed."""
    anchors = W.resolve_anchors(named=["soybeans_cbot"], graph=real)
    bd = W.walk(graph=real, asof="2026-09-07", mode="deep", anchors=anchors,
                state_fn=_flat_state_fn(oni_climate={"z": 4.4, "pct": 99.0, "run": 6}),
                key_fn=_key_fn(), receipts={})
    order = bd.request()["order"]
    ranked = [r.key for r in W.rank_rows(bd.rows)]
    assert list(order) == ranked, "the payload IS the rank order"
    assert order != tuple(r.key for r in bd.rows), "and it is NOT the DAG's insertion order"
    assert order[0] == ("soybeans_cbot", "El_Nino"), "the loudest reading leads the list S6 threads"
    assert len(order) == len(bd.rows) and set(order) == {r.key for r in bd.rows}, \
        "every row is ordered -- a hole would read as 'the board did not rank it'"


def test_the_board_order_is_ONE_ordering_and_stage_2_moves_only_the_TEXT_tail(real):
    """`rank_key`'s sixth term is `-receipt_specificity`, which is 0 for every row in stage 1 and
    non-zero in stage 2. A stage-2 caller that RECOMPUTED the tuple would hold a second ordering, in a
    sitting whose law is one -- so `rank_rows` reads the tuple stage 1 STAMPED (`stored_rank`). Sec 3.2
    licenses exactly one stage-2 reorder, the text-only tier's own `(open_event, newest receipt date,
    specificity)`, and that tier has its own key."""
    ds = [_driver("numeric", silver_ref="r", silver_status="available"),
          _driver("text_a", lag="0-2 quarters"), _driver("text_b", lag="0-2 quarters")]
    g = _graph(c=cs.CausalContract(contract="c", drivers=ds))
    kw = dict(graph=g, asof="2026-09-07", mode="deep",
              anchors=(B.Anchor(contract="c", source="named"),),
              state_fn=_flat_state_fn(), key_fn=_key_fn())
    one = W.walk(stage2=False, **kw)
    assert one.order[0] == ("c", "numeric"), "stage 1 alone already hands S6 an ORDER"
    both = W.walk(receipts={("c", "text_b"): [{"date": "2026-06-05", "event_date": "2026-06-01",
                                               "event_date_precision": "day", "rank": 0.9}]}, **kw)
    numeric_1 = [k for k in one.order if W.coverage_band(one.row(*k)) <= 2]
    numeric_2 = [k for k in both.order if W.coverage_band(both.row(*k)) <= 2]
    assert numeric_1 == numeric_2 == [("c", "numeric")], "stage 2 APPENDS; the numeric head does not move"
    assert one.order[1:] == (("c", "text_a"), ("c", "text_b")), "no receipts: the deterministic tail"
    assert both.order[1:] == (("c", "text_b"), ("c", "text_a")), \
        "the OPEN EVENT leads the text-only tail, which is the one thing stage 2 may reorder"
    assert both.row("c", "text_b").rank == one.row("c", "text_b").rank, "the stamped tuple is untouched"


def test_the_board_refuses_an_order_that_does_not_cover_its_own_rows():
    bd = B.Board()
    bd.rows = [B.NodeRow(contract="c", driver_id="a"), B.NodeRow(contract="c", driver_id="b")]
    with pytest.raises(ValueError):
        bd.set_order(bd.rows[:1])
    assert bd.set_order(list(reversed(bd.rows))) == (("c", "b"), ("c", "a"))


# ── 3.8 WAVE 2 IS PRICED FROM THE WAVE-1 RANK ───────────────────────────────────────────────────────
def _fan_fixture():
    """One anchor board with a VERY loud row and a VERY quiet row, each shared with four far boards.
    The QUIET row's far edges declare `high` confidence and the loud row's declare `medium`, which is
    the configuration that separates "ordered by the far graph's confidence" from "ordered by the
    wave-1 rank"."""
    def _d(did, ref, conf="medium"):
        return cs.Driver(id=did, type="climate_driver", sign="+", mechanism="m", silver_ref=ref,
                         silver_status="available", confidence=conf)
    boards = {"anchor": cs.CausalContract(contract="anchor",
                                          drivers=[_d("loud", "loud_ref"), _d("quiet", "quiet_ref")])}
    for i in range(4):
        boards[f"far_loud_{i}"] = cs.CausalContract(
            contract=f"far_loud_{i}", drivers=[_d("loud", "loud_ref", "medium")])
        boards[f"far_quiet_{i}"] = cs.CausalContract(
            contract=f"far_quiet_{i}", drivers=[_d("quiet", "quiet_ref", "high")])
    return _graph(**boards)


def test_MAJOR_2_wave_2_is_priced_from_the_WAVE_1_RANK_not_the_far_graphs_confidence():
    """Sec 3.3 step 9: far keys are "priced from the wave-1 rank"; sec 3.6: bounded "by the rank cut and
    the mode's `fan_k`".

    MEASURED AT THE S2 REVIEW as the exact inverse of this test. Every far `PricedKey` was minted with
    `anchor_order=1, share=1`, so `wave1_order` collapsed to `(1, -1, -confidence, ref, label)` and the
    seeding row's rank was DISCARDED: on this fixture with a far cap of 4 the anchor's z = 5.0 row had
    all four of its far boards DEFERRED while the z = 0.02 row's four took the whole far column, purely
    because the quiet row's far edges declare `high`. The far half of the wave was ordered by the far
    graph's confidence and by nothing about how loud the anchor row was."""
    g = _fan_fixture()

    def key_fn(ref, node, *, turn_kind=""):
        return KeyPlan(key=SeriesKey(ref=ref, commodity=node.contract), status="ok", row={"t": 1})

    def state_fn(ref, node):
        return _state(ref, z=5.0 if ref == "loud_ref" else 0.02)

    kn = B.BoardKnobs(8, 4, 0, 0, 4, 24, 4, 0, 2)      # far cap 4 -- room for ONE row's fan, not two
    bd = W.walk(graph=g, asof="2026-09-07", mode="deep", knobs=kn,
                anchors=(B.Anchor(contract="anchor", source="named"),),
                state_fn=state_fn, key_fn=key_fn, receipts={})
    w2 = bd.ledger.waves[2]
    assert [k.label for k in w2.plan] == [f"loud_ref|far_loud_{i}|" for i in range(4)]
    assert {k.label for k in w2.deferred_keys} == {f"quiet_ref|far_quiet_{i}|" for i in range(4)}
    assert bd.order[0] == ("anchor", "loud") and w2.closed and bd.rectangle() == []


def test_the_wave_2_SHARE_term_is_measured_and_not_a_constant_1():
    """Sec 3.8's fan-out weighting is written for BOTH waves; at the S2 landing `share` was a literal 1
    on every far key, so the term that makes a key several loud rows all want cheaper than one row's
    key was absent from the wave it was written for."""
    def _d(did, ref):
        return cs.Driver(id=did, type="climate_driver", sign="+", mechanism="m", silver_ref=ref,
                         silver_status="available")
    boards = {"anchor": cs.CausalContract(contract="anchor",
                                          drivers=[_d("a", "shared_ref"), _d("b", "shared_ref")]),
              "far": cs.CausalContract(contract="far",
                                       drivers=[_d("a", "shared_ref"), _d("b", "shared_ref")])}
    g = _graph(**boards)

    def key_fn(ref, node, *, turn_kind=""):
        return KeyPlan(key=SeriesKey(ref=ref, commodity=node.contract), status="ok", row={"t": 1})

    bd = W.walk(graph=g, asof="2026-09-07", mode="max",
                anchors=(B.Anchor(contract="anchor", source="named"),),
                state_fn=_flat_state_fn(), key_fn=key_fn, receipts={})
    w2 = bd.ledger.waves[2]
    assert len(w2.plan) == 1, "two loud rows want ONE far key; it is bought once"
    assert w2.plan[0].share == 2, "and the share term SAYS two rows wanted it"


# ── 6.7 A CUT THAT NEVER HAPPENED IS NEVER NAMED ────────────────────────────────────────────────────
def test_MAJOR_4_a_wave_that_declined_BY_NAME_never_stamps_budget_cap():
    """MEASURED AT THE S2 REVIEW: with four drivers whose reads all returned `pool_exhausted`, the
    series leg stamped `declined:budget_cap` while `ledger.budget_capped == 0` and no `budget_cap` note
    existed -- a budget cut with an empty list of dropped keys, and the S3 render owes that word a
    sentence naming them. The honest word was already on the ledger and on every row; only the stamp was
    lying. This is the SAME error the zero-declared branch was written to avoid, left standing one
    branch over."""
    g = _wide(n_drivers=4)

    def state_fn(ref, node):
        return _state(ref, status="pool_exhausted", tier="series", reads=1)

    bd = W.walk(graph=g, asof="2026-09-07", mode="deep",
                anchors=(B.Anchor(contract="c", source="named"),),
                state_fn=state_fn, key_fn=_key_fn(), receipts={})
    assert bd.legs["series"] == {"outcome": "declined", "reason": "pool_exhausted", "reads": 4}
    assert bd.ledger.budget_capped == 0 and bd.ledger.waves[1].deferred == 0
    assert not [n for n in bd.notes if n.get("kind") == "budget_cap"]
    assert bd.rectangle() == []


def test_a_wave_that_ACTUALLY_hit_the_cap_still_says_budget_cap():
    """The other half of the same rule: when keys WERE deferred, `budget_cap` is the true word even if
    some reads also declined, because the SB-X row it owes has real names to print."""
    g = _wide(n_drivers=60)

    def state_fn(ref, node):
        return _state(ref, status="pg_timeout", tier="series", reads=1)

    bd = W.walk(graph=g, asof="2026-09-07", mode="quick",
                anchors=(B.Anchor(contract="c", source="named"),),
                state_fn=state_fn, key_fn=_key_fn(), receipts={})
    assert bd.legs["series"]["reason"] == "budget_cap"
    assert [n for n in bd.notes if n.get("kind") == "budget_cap"][0]["names"]


def test_B1_read_is_COUNTED_from_the_returns_so_the_rectangle_can_actually_FAIL():
    """The first build wrote `read = max(0, declared - deferred - declined)`, which made
    `WaveLedger.closed` an IDENTITY: a bar the module docstring calls "unbreakable" could only fail by
    over-subtraction, i.e. it graded nothing. Counted from what came back, the rectangle is a real
    assertion -- and it still closes on a wave where half the reads declined."""
    g = _wide(n_drivers=6)

    def state_fn(ref, node):
        return _state(ref, status="pool_exhausted" if ref.endswith(("0", "1", "2")) else "ok")

    bd = W.walk(graph=g, asof="2026-09-07", mode="deep",
                anchors=(B.Anchor(contract="c", source="named"),),
                state_fn=state_fn, key_fn=_key_fn(), receipts={})
    w1 = bd.ledger.waves[1]
    assert w1.series_declared == 6 and w1.declined == 3 and w1.read == 3 and w1.deferred == 0
    assert bd.rectangle() == []
    w1.read += 1                                       # a read nobody made
    assert not w1.closed and bd.rectangle(), "the assertion DOES work now"


# ── sec 7: no knobs, no board ───────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("mode", ["deep_v2", "max_cc1", "quick_r0", "quick_s", "standard"])
def test_a_preset_with_NO_declared_board_runs_NO_board_and_SAYS_so(mode, real):
    """`board_knobs_of`'s own docstring: "None is the passthrough: no knobs, no board". The first build
    fell back to a hard-coded Scan tuple, so a dark twin whose base is ITSELF silently ran a SCAN-depth
    board -- on an arm that is a parity error nothing stamps, because the control and the treatment
    would then differ by a board neither declared."""
    assert B.board_knobs_of(mode) is None
    anchors = W.resolve_anchors(named=["soybeans_cbot"], graph=real)
    bd = W.walk(graph=real, asof="2026-09-07", mode=mode, anchors=anchors,
                state_fn=_flat_state_fn(), key_fn=_key_fn(), receipts={})
    assert bd.legs["board"] == {"outcome": "declined", "reason": f"lane_off:{mode}", "reads": 0}
    assert bd.net_reads() == 0 and bd.rows == [] and bd.rectangle() == []


# ── 6.7: the closed words the walk had made unreachable ─────────────────────────────────────────────
def test_a_far_board_whose_graph_declares_NO_sign_stamps_the_edge_word_for_it(real):
    """Sec 6.7's `edge:` enum opens with `sign_undeclared`, and at the S2 landing the only site that
    stamped it was the INTER-COMMODITY edge -- far rows set `sign_declared=False` and stamped nothing,
    so the word was unreachable from the half of the walk that produces the most rows. `edge_decline` is
    a SECOND field beside `decline` because a far board named-but-unread and a far board whose graph
    declared no sign are two different facts."""
    index = {"d": (("a", "+", "1-2 quarters", "high", "r"),
                   ("b", "", "1-2 quarters", "high", "r"),
                   ("c", "-", "whenever", "low", "r"))}
    rows = {f["contract"]: f for f in W.far_rows(index, "z", "d")}
    assert rows["a"]["edge_decline"] is None and rows["a"]["sign_words"]
    assert rows["b"]["edge_decline"] == "sign_undeclared" and rows["b"]["decline"] is None
    assert rows["c"]["edge_decline"] == "lag_unparsed"
    for f in rows.values():
        assert B.check_reason("edge", f["edge_decline"] or "sign_undeclared") is None


def test_the_two_receipt_absences_are_DIFFERENT_facts_and_the_row_says_which(real):
    """`rows.TEXT_STATUS_WORDS` declares three words this sitting; the walk wrote `no_receipts` whenever
    the list was empty, which collapsed "the caller fetched none" into "this node has none" and made the
    third word of a closed set unreachable from the walk."""
    anchors = W.resolve_anchors(named=["soybeans_cbot"], graph=real)
    bd = W.walk(graph=real, asof="2026-09-07", mode="quick", anchors=anchors,
                state_fn=_flat_state_fn(), key_fn=_key_fn(),
                receipts={("soybeans_cbot", "El_Nino"): []})
    assert bd.row("soybeans_cbot", "El_Nino").receipts["status"] == "no_receipts"
    other = [r for r in bd.rows if r.driver_id != "El_Nino"][0]
    assert other.receipts["status"] == "no_receipt_fetched"


def test_a_band_crossed_on_ONE_board_is_never_counted_toward_ANOTHER_boards_pattern():
    """`convergence_rows` was handed a board-WIDE `band_ids` set, so on a multi-anchor turn a band
    crossed on board A counted toward board B's `n_with_band` -- two boards can declare the same driver
    id, which is the whole point of the fan-out."""
    conv = cs.ConvergenceSignal(name="p", direction="+", requires_any_n_of=1, drivers=["d"])
    d = _driver("d", silver_ref="r", silver_status="available")
    g = _graph(a=cs.CausalContract(contract="a", drivers=[d], convergence=[conv]),
               b=cs.CausalContract(contract="b", drivers=[d], convergence=[conv]))

    def key_fn(ref, node, *, turn_kind=""):
        return KeyPlan(key=SeriesKey(ref=ref, commodity=node.contract), status="ok", row={"t": 1})

    def state_fn(ref, node):
        hit = node.contract == "a"
        return _state(ref, z=2.0, conv={"matched": hit, "declined": None} if hit else
                      {"matched": False, "declined": None})

    bd = W.walk(graph=g, asof="2026-09-07", mode="deep",
                anchors=(B.Anchor(contract="a", source="named"),
                         B.Anchor(contract="b", source="named", rank=1)),
                state_fn=state_fn, key_fn=key_fn, receipts={})
    by_board = {r["contract"]: r for r in bd.convergence}
    assert by_board["a"]["n_with_band"] == 1 and by_board["b"]["n_with_band"] == 0


def test_a_chains_LOUD_hops_are_LOUD_and_not_merely_ON_THE_BOARD():
    """Sec 3.5 orders declared chains "by the number of loud hops"; the first build counted hops that
    were merely present on the board, so a chain no loud row touched out-ranked one with a real loud
    hop."""
    chains = [{"name": "present_only", "hops": ("x", "y")},
              {"name": "one_loud", "hops": ("p", "q")}]
    out = W.chain_paths(chains, on_board={"x", "y", "p", "q"}, loud_boards={"p"})
    assert [c["name"] for c in out] == ["one_loud", "present_only"]
    assert out[0]["loud_hops"] == 1 and out[0]["hops_on_board"] == 2
    assert out[1]["loud_hops"] == 0 and out[1]["hops_on_board"] == 2


def test_the_complexes_and_chains_notes_are_EXERCISED_through_the_walk_and_not_only_declared(real):
    """Both notes defaulted to empty tuples in every test and every call at the S2 landing, so two legs
    sec 3.5 declares were built and never run. The maps are the S6 caller's to thread (`complex_map` 35
    pairs, `chain_map` 10 + `transmission_map` 2); this pins that threading them works."""
    anchors = W.resolve_anchors(named=["soybeans_cbot", "malaysian_crude_palm_oil_cme"], graph=real)
    bd = W.walk(graph=real, asof="2026-09-07", mode="max", anchors=anchors,
                state_fn=_flat_state_fn(), key_fn=_key_fn(), receipts={},
                complexes=[("soybeans_cbot", "malaysian_crude_palm_oil_cme"),
                           ("soybeans_cbot", "not_a_board")],
                chains=[{"name": "vegoil", "hops": ["malaysian_crude_palm_oil_cme", "soybeans_cbot"]},
                        {"name": "absent", "hops": ["not_a_board"]}])
    cx = dict([(p, r) for p, r in [n for n in bd.notes if n["kind"] == "complexes"][0]["rows"]])
    assert cx[("soybeans_cbot", "malaysian_crude_palm_oil_cme")] is True
    assert cx[("soybeans_cbot", "not_a_board")] is False
    chains = {name: (rendered, loud) for name, rendered, loud
              in [n for n in bd.notes if n["kind"] == "chains"][0]["rows"]}
    assert chains["vegoil"][0] is True and chains["vegoil"][1] == 2, "both hops are LOUD boards"
    assert chains["absent"] == (False, 0)


def test_the_rows_past_the_cut_whose_far_STATES_went_unread_are_NAMED(real):
    """Sec 3.2's own SB-X line, which had no producer at the S2 landing. Every other cut on this board
    mints a note (`budget_cap`, `path_render_cap`, `edge_hop_cap`); the fan's did not, so the ONE
    SB-X line the design specifies per mode had nothing to read. The far NAMES are never cut -- the note
    is about STATES only (sec 3.6)."""
    anchors = W.resolve_anchors(named=["soybeans_cbot"], graph=real)
    scan = W.walk(graph=real, asof="2026-09-07", mode="quick", anchors=anchors,
                  state_fn=_flat_state_fn(), key_fn=_key_fn(), receipts={})
    note = [n for n in scan.notes if n["kind"] == "fan_states_unread"][0]
    assert note["loud_k"] == 8 and note["rows"] == len(note["names"]) > 0
    quiet_keys = {r.key for r in scan.rows if not r.legs.get("loud")}
    assert set(note["names"]) <= quiet_keys, "only rows past the cut"
    named_anyway = {f["contract"] for e in scan.fan for f in e["far"]}
    assert named_anyway, "and their far boards are still NAMED -- the index is free and never cut"


def test_the_declared_cap_is_the_EFFECTIVE_one_so_the_S6_ceiling_is_derived_from_what_can_be_spent(real):
    """D12: `cw_ceiling = (CW_DEEP_TURN_CEILING if deep_on else CW_TURN_CEILING) +
    (STATE_BOARD_CAP[mode] if board_fired else 0)`. With leg B dark, Cascade's cap is sec 3.8's own
    "71 with leg B dark" -- 40 + 31 -- and not the 98 the armed table prints."""
    anchors = W.resolve_anchors(named=["soybeans_cbot"], graph=real)
    kw = dict(graph=real, asof="2026-09-07", mode="max", anchors=anchors,
              state_fn=_flat_state_fn(), key_fn=_key_fn(), receipts={})
    assert W.walk(**kw).declared_cap() == 71
    assert W.walk(legb_on=True, **kw).declared_cap() == 98

# ═════════════════════════════════════════════════════════════════════════════════════════════════════
# S8 LANE W -- THE COMPOSED CHAIN (DESIGN B.0-B.3, owner doctrine 2026-09-17)
#
# THE BARS THIS BLOCK OWNS. E9 the history stat is a weight and never a gate; E10 the earned-cross
# rule; E11 the (contract, driver_id) join, built from HAND-MADE rows because the fixture serves one
# array per ref and CANNOT fail it; the orchestrator's print-line ruling (a pool is never rendered
# empty); the SIGN-DIVERSITY rule (owner: disagreement must be structural); the diversity fold on the
# SERIES key; the curated prior; and the shape adapter that lets the estate's ten curated chains reach
# a turn for the first time.
#
# EVERYTHING HERE IS HAND-BUILT AND OFFLINE. No graph is loaded except where a bar is about the shipped
# graph, no state producer runs, no environment is read and nothing is spent.
# ═════════════════════════════════════════════════════════════════════════════════════════════════════
def _cs(ref, *, pct=None, z=None, values=None, dates=None, unit="t", run=None,
        level=1.0, status="ok", changes=None, conv=None):
    """ONE StateRow carrying its own INPUT BUNDLE, which is what the history stat reads at zero reads."""
    key = SeriesKey(ref=ref)
    st = StateRow(key=key, status=status, coverage_tier="series", table="t", metric=ref,
                  cadence="monthly", unit=unit, narrate_unit=unit, level=level,
                  level_date="2026-08-31", knowledge_date="2026-09-01",
                  z=None if z is None else {"value": z, "window_n": 120},
                  percentile=None if pct is None else {"value": pct, "n": 120},
                  run=run, convention=conv,
                  changes=list(changes or [{"window": "1m", "delta": 1.0, "pct": 1.0}]))
    if values is not None:
        st.inputs = {key.label(): {"values": list(values), "dates": list(dates or ()), "unit": unit}}
    return st


def _crow(bd, contract, driver_id, *, sign="+", lag="0-1 quarters", conf="high", st=None,
          series_key=None, loud=True, event=None, event_open=False, receipts=None):
    """ONE NodeRow on ``bd``, with its state registered under its OWN series key (E11's whole point)."""
    lbl = series_key if series_key is not None else (st.key.label() if st is not None else "")
    row = B.NodeRow(contract=contract, driver_id=driver_id, sign=sign, lag=lag,
                    lag_band=parse_lag(lag), confidence=conf, mechanism="m",
                    silver_status="available", series_key=lbl, state=st)
    row.legs["loud"] = loud
    if st is not None:
        bd.series[lbl] = st
    if event:
        row.event_date, row.event_precision = event, "day"
        row.event_receipt = {"date": event, "source": "src", "text": "an action", "event_date": event}
        row.event_open = bool(event_open)
    if receipts:
        row.receipts = {"n": len(receipts), "top": list(receipts), "status": "ok"}
    bd.rows.append(row)
    return row


def _cboard(*, asof="2026-09-07", mode="deep", anchors=("a_cbot",), horizon=3):
    bd = B.Board(asof=asof, mode=mode, knobs=B.board_knobs_of(mode), horizon_months=horizon,
                 anchors=tuple(B.Anchor(contract=s, source="named") for s in anchors))
    return bd


def _cpath(bd, contract, hops):
    bd.paths.append({"contract": contract, "seeded_by": hops[0], "ancestor": hops[0],
                     "bottom": hops[-1], "depth": len(hops) - 1, "hops": tuple(hops),
                     "lag_band": parse_lag(""), "band_is_the_ancestors_own": True,
                     "confidence": "high", "rank": (), "rendered": False, "decline": None})


def _cfinish(bd):
    bd.set_order(W.rank_rows(bd.rows))


# ── the flag, and the byte-identical set it protects ────────────────────────────────────────────────
def test_the_chain_flag_off_builds_nothing_stamps_nothing_and_moves_no_knob(real):
    """DESIGN B.7: board ON and chain OFF must be byte-identical to the 2026-09-16 smoke, or arm A
    cannot attribute a character. This is that property at the WALK's own seam: with the kwarg absent,
    `Board.chains` is empty, `chain_counts` is empty, the trace omits both keys AND the row payload,
    the `path` leg carries the stamp step 6 gave it, and the render caps are the TIER's own -- the A.8
    cuts ride the flag through `board.with_chain_caps` and never the mode table."""
    g = _graph(a_cbot=cs.CausalContract(
        contract="a_cbot",
        drivers=[_driver("top", lag="0-1 quarters"), _driver("mid", parents=["top"]),
                 _driver("bot", parents=["mid"])]))
    bd = W.walk(graph=g, asof="2026-09-07", mode="deep", anchors=W.resolve_anchors(named=("a_cbot",)),
                question="q", state_fn=lambda ref, node: (_state(ref, z=1.0, pct=90), 1),
                key_fn=_key_fn(), receipts={}, knobs=B.board_knobs_of("deep"), width=2, stage2=False)
    W.stage2(bd, g, state_fn=lambda ref, node: (_state(ref, z=1.0, pct=90), 1), key_fn=_key_fn(),
             receipts={})
    assert bd.chains == [] and bd.chain_counts == {}
    tr = bd.trace()
    assert "chains" not in tr and "chain_counts" not in tr and "row_states" not in tr
    assert isinstance(tr["rows"], int), "`rows` is the COUNT and must stay an integer"
    assert bd.knobs == B.board_knobs_of("deep"), "no cap moved with the flag off"
    assert bd.legs["path"]["outcome"] in ("fired", "declined", "not_reached")


def test_the_chain_flag_on_cuts_exactly_the_four_A8_enumerations_and_nothing_else():
    """DESIGN A.8 / threat E1: the enumeration cuts land in the same commit as the chain rows, and
    they ride the CHAIN FLAG rather than `BOARD_PRESETS` so the control cell cannot move with the
    treatment. Exactly four knobs move, and every budget knob is untouched by construction."""
    for mode in ("quick", "deep", "max"):
        k = B.board_knobs_of(mode)
        c = B.with_chain_caps(k, mode)
        moved = {n for n in B.BoardKnobs._fields if getattr(k, n) != getattr(c, n)}
        assert moved <= {"render_absence", "render_absence_names", "render_fan_names",
                         "render_projection"}, moved
        for n in ("loud_k", "fan_k", "wave1", "wave2", "analog_k", "analog_dims", "receipt_cap",
                  "board_admit_k", "max_anchors", "path_render_k"):
            assert getattr(k, n) == getattr(c, n), n
        assert B.check_knobs(c, legb_cells=B.legb_cells_of(mode)) == []
    # QUICK GETS NOTHING FROM THE TABLE AND THE DESIGN SAYS SO: `BOARD_PRESETS[QUICK]` already ships
    # A.8's quick row byte for byte, which is why the free tier absorbs its one chain as a net add.
    assert B.with_chain_caps(B.board_knobs_of("quick"), "quick") == B.board_knobs_of("quick")
    assert B.with_chain_caps(None, "deep") is None


# ── E9: THE STATS GRADE, THEY NEVER GATE ────────────────────────────────────────────────────────────
def test_E9_a_chain_with_ONE_firing_and_a_first_percentile_hop_RANKS_AND_RENDERS():
    """THE NEGATIVE TEST DESIGN E9 ASKS FOR BY NAME, and it exists because this is the estate's own
    repeated failure -- the analog rule, the K9 floors, the register fence and S7's STOP were all a
    weight that became a gate. A chain whose record is ONE firing and whose receipt hop sits at the
    FIRST percentile of its own record must rank and render, with "history thin" printed beside it.
    Frequency floors deny the tail."""
    bd = _cboard()
    st_top = _cs("top", pct=1, z=-2.6, values=[5, 4, 5, 4, 3, 2, 1], unit="pct",
                 dates=["2026-0%d-28" % i for i in range(1, 8)])
    _crow(bd, "a_cbot", "top", st=st_top)
    _crow(bd, "a_cbot", "bot", st=_cs("bot", pct=50, values=[1, 2], dates=["2026-01-31", "2026-07-31"]))
    _cpath(bd, "a_cbot", ["top", "bot"])
    _cfinish(bd)
    got = W.chain_rows(bd, None, knobs=bd.knobs)
    assert got["pool"], "the chain must exist"
    ch = got["pool"][0]
    # 25 * max(|1-50|/50, min(|-2.6|/2.5, 1)) = 25 * max(0.98, 1.0) = 25.0 -- THE SIGMA LEG CLAMPS
    # AT ONE, so a reading past 2.5 sigma is a full tail and not a bigger one.
    assert ch.terms["tail"] == 25.0, ch.terms
    assert ch.history["n_firings"] <= 2 and ch.history["thin"] is True
    assert ch.terms["history"] == W.CHAIN_HISTORY_NEUTRAL, "a thin record is NEUTRAL, never low"
    assert ch.rendered is True, "a thin record removed a chain -- the weight became a gate"
    # 09-24 FIX ROUND (item 28c, DECLARED): the trace twin of the page's record line speaks the desk's
    # words -- "the record is thin" -- and names the reading and its next link (K11's twin).
    assert "the record is thin" in ch.notes["history"], ch.notes["history"]
    assert "top" in ch.notes["history"] and "bot" in ch.notes["history"], ch.notes["history"]


def test_the_history_term_is_a_fraction_of_a_real_record_and_prints_its_sample_size():
    """DESIGN B.2's HISTORY arithmetic, executed: `15 * aligned_fraction` at six or more firings,
    discounted by 0.7 between three and six, NEUTRAL below three -- and the words carry the COUNT so a
    reader weighs it (figures AND words together, never either extreme)."""
    # a parent that rises, falls, rises ... and a child that follows it one month later
    vals = [1, 2, 1, 2, 1, 2, 1, 2, 1, 2, 1, 2, 1, 2, 1, 2, 1, 2]
    dates = ["2024-%02d-28" % ((i % 12) + 1) if i < 12 else "2025-%02d-28" % ((i % 12) + 1)
             for i in range(len(vals))]
    a = _cs("a", pct=95, values=vals, dates=dates, run={"direction": "up", "length": 1})
    b = _cs("b", pct=60, values=[v * 2 for v in vals], dates=dates)
    h = W.chain_history(a, b, edge_sign="+", band=parse_lag("0-1 quarters"), asof="2026-09-07",
                        direction=1)
    assert h["n_firings"] >= 3, h
    assert 0.0 <= h["fraction"] <= 1.0
    assert str(h["n_firings"]) not in h["words"], "the sample size is spelled in WORDS, not digits"
    # 09-24 FIX ROUND (item 28c, DECLARED): the population is the record line's own desk noun
    assert "past times this reading sat this far out" in h["words"], h["words"]
    assert "firing" not in h["words"], h["words"]
    # and it never removes anything: a declined record is a NEUTRAL score, not an absent chain
    assert W.chain_history(None, None, edge_sign="+", band=parse_lag("0-1 quarters"),
                           asof="2026-09-07")["n_firings"] == 0


def test_the_history_stat_drops_a_firing_whose_declared_window_has_NOT_closed_at_the_asof():
    """THE ONLY HARD FILTERS IN THIS DESIGN ARE POINT-IN-TIME AND EXISTENCE (ruling R2). A firing
    whose declared band closes after the as-of is not a record -- it is the present -- so it is
    dropped, and the CURRENT run's own start needs no second clause because its window closes after
    the as-of by construction."""
    vals = [1, 2, 1, 2, 1, 2]
    dates = ["2026-04-30", "2026-05-31", "2026-06-30", "2026-07-31", "2026-08-31", "2026-09-30"]
    early = W.chain_firings(vals, dates, direction=1, min_separation=1, asof="2026-09-07",
                            close_months=3)
    late = W.chain_firings(vals, dates, direction=1, min_separation=1, asof="2027-09-07",
                           close_months=3)
    assert len(early) < len(late), (early, late)
    assert all(f["date"] <= "2026-06-07" for f in early), early


# ── E10: THE EARNED-CROSS RULE ──────────────────────────────────────────────────────────────────────
def test_E10_a_cross_hop_to_an_UNPRICED_far_board_earns_no_reach_and_renders_no_cross_line():
    """DESIGN B.0 / E10: an unpriced far market is a NAME, and a name buys no rank -- the direct fix
    for the PM's reading of "declared on twenty-three other markets" as scoring machinery. AND IT
    REMOVES NO CHAIN: it removes the chain's cross EXTENSION, and the intra-DAG chain stays in the
    pool with its own score, which is the half of the rule that is easy to get wrong."""
    bd = _cboard()
    _crow(bd, "a_cbot", "top", st=_cs("top", pct=95))
    _crow(bd, "a_cbot", "bot", st=_cs("bot", pct=50))
    _cpath(bd, "a_cbot", ["top", "bot"])
    bd.edges.append({"anchor": "a_cbot", "direction": "forward", "other": "z_cbot",
                     "relation": "substitute", "sign": "+", "lag": "0-1 quarters",
                     "lag_band": parse_lag("0-1 quarters"), "mechanism": "m", "tracked": True})
    bd.fan.append({"contract": "a_cbot", "driver_id": "top", "loud": True,
                   "far": [{"contract": "z_cbot", "driver_id": "top", "state_read": False,
                            "series_key": "", "sign": "+", "confidence": "high", "ref": "r"}]})
    _cfinish(bd)
    got = W.chain_rows(bd, None, knobs=bd.knobs)
    assert got["counts"]["cross_unpriced"] == 1
    assert all(c.cross is None for c in got["pool"]), "an unpriced far board was carried"
    assert len(got["pool"]) == 1, "the intra-DAG chain was removed with its extension"
    assert got["pool"][0].terms["reach"] < 15


def test_a_cross_hop_to_a_PRICED_far_board_is_earned_and_carries_the_far_reading():
    """The other half: `bd.edges` is MARKET to MARKET and knows the relation, the sign, the lag and
    the mechanism; `bd.fan[*].far[*]` is the SAME DRIVER on another board and is the only one that
    knows whether anything was PRICED. The composition takes the edge from the first and EARNS it
    against the second (S8 recon, surprise S5)."""
    bd = _cboard()
    _crow(bd, "a_cbot", "top", st=_cs("top", pct=95))
    _crow(bd, "a_cbot", "bot", st=_cs("bot", pct=50))
    _cpath(bd, "a_cbot", ["top", "bot"])
    far_st = _cs("zfar", pct=99)
    bd.series["zfar"] = far_st
    bd.edges.append({"anchor": "a_cbot", "direction": "forward", "other": "z_cbot",
                     "relation": "substitute", "sign": "+", "lag": "0-1 quarters",
                     "lag_band": parse_lag("0-1 quarters"), "mechanism": "m", "tracked": True})
    bd.fan.append({"contract": "a_cbot", "driver_id": "top", "loud": True,
                   "far": [{"contract": "z_cbot", "driver_id": "top", "state_read": True,
                            "series_key": "zfar", "sign": "+", "confidence": "high", "ref": "r"}]})
    _cfinish(bd)
    got = W.chain_rows(bd, None, knobs=bd.knobs)
    crossed = [c for c in got["pool"] if c.cross]
    assert len(crossed) == 1 and crossed[0].terminal == "z_cbot"
    assert crossed[0].terminal_percentile == 99
    assert crossed[0].terms["reach"] > got["pool"][0].terms["reach"]
    assert crossed[0].unnamed_terminal is True, "the question named a_cbot and not z_cbot"


# ── E11: THE JOIN ───────────────────────────────────────────────────────────────────────────────────
def test_E11_the_chain_state_join_keys_on_contract_AND_driver_id_and_on_the_series_key():
    """`area` IS A DRIVER OF `corn_cbot` AND OF `soft_red_winter_wheat_cbot` AND THE TWO READ THE 98TH
    AND THE 1ST PERCENTILE ON THE SAME TURN. `render.series_by_driver` keys on the bare id with
    `setdefault` and returns ONE reading per id for the whole board, so a chain built off it prints one
    board's tail on the other board's chain.

    THE FIXTURE CANNOT FAIL THIS -- it serves one array per ref regardless of scope, so both boards
    print the same percentile and the defect is invisible (measured in the S8 recon, surprise S4). So
    the rows here are HAND-MADE, which is exactly what the standing memory about string-identity joins
    asks for."""
    bd = _cboard(anchors=("corn_cbot", "soft_red_winter_wheat_cbot"))
    _crow(bd, "corn_cbot", "top", st=_cs("ctop", pct=55), series_key="ctop")
    _crow(bd, "corn_cbot", "area", st=_cs("area_corn", pct=98), series_key="area_corn")
    _crow(bd, "soft_red_winter_wheat_cbot", "top", st=_cs("wtop", pct=55), series_key="wtop")
    _crow(bd, "soft_red_winter_wheat_cbot", "area", st=_cs("area_wheat", pct=1), series_key="area_wheat")
    _cpath(bd, "corn_cbot", ["top", "area"])
    _cpath(bd, "soft_red_winter_wheat_cbot", ["top", "area"])
    _cfinish(bd)
    got = W.chain_rows(bd, None, knobs=bd.knobs)
    by_board = {c.contract: c for c in got["pool"]}
    assert by_board["corn_cbot"].hops[1].percentile == 98
    assert by_board["soft_red_winter_wheat_cbot"].hops[1].percentile == 1
    assert by_board["corn_cbot"].hops[1].series_key != by_board["soft_red_winter_wheat_cbot"].hops[1].series_key
    # and the two `area` hops are NOT one reading for the diversity fold either
    assert by_board["corn_cbot"].hops[1].fold_key != \
        by_board["soft_red_winter_wheat_cbot"].hops[1].fold_key


# ── the render decision ─────────────────────────────────────────────────────────────────────────────
def test_the_TOP_chain_always_renders_even_below_the_print_line_IN_FULL():
    """THE ORCHESTRATOR'S RULING OF 2026-09-17 AND OWNER RULING 6(a) TOGETHER: when any candidate chain
    exists the top-ranked one renders, and it renders IN FULL whatever it scored (review MA-1) -- so no
    turn is chain-less while the graph carried one, and a data-poor anchor's best chain is not served
    in a reduced form for having scarce data. The chain below the line keeps its score, its rank and
    its trace row, and the count line says it sat below the line only where it did NOT render."""
    bd = _cboard()
    _crow(bd, "a_cbot", "top", st=_cs("top", pct=50), conf="low")
    _crow(bd, "a_cbot", "bot", st=_cs("bot", pct=50), conf="low")
    _cpath(bd, "a_cbot", ["top", "bot"])
    _cfinish(bd)
    got = W.chain_rows(bd, None, knobs=bd.knobs)
    ch = got["pool"][0]
    assert ch.score < bd.knobs.chain_print_line, ch.score
    assert ch.rendered is True and ch.full is True, "a pool was rendered empty or reduced"
    assert ch.decline is None and ch.slot == "top"
    assert got["counts"]["below_print_line"] == 0, "it RENDERED, so it is not counted below the line"
    # and the line still has exactly one reader: the count, never the selection
    assert W.chain_render_set([ch], k=1, print_line=0.0)["rendered"][0].full is True


def test_no_chain_is_ever_removed_from_the_pool_and_every_cut_carries_a_declared_word():
    """Ruling R2 in one assertion. `chain_render_set` is a RENDER rule the object exposes, never a
    filter: the pool it returns is the pool it was given, and every chain that did not render carries
    a word from `board.CHAIN_REASONS` -- the vocabulary the render owes a sentence."""
    bd = _cboard(mode="quick")
    for i in range(6):
        _crow(bd, "a_cbot", "t%d" % i, st=_cs("t%d" % i, pct=90 + i))
        _crow(bd, "a_cbot", "b%d" % i, st=_cs("b%d" % i, pct=50))
        _cpath(bd, "a_cbot", ["t%d" % i, "b%d" % i])
    _cfinish(bd)
    got = W.chain_rows(bd, None, knobs=bd.knobs)
    assert len(got["pool"]) == 6
    assert got["counts"]["total"] == 6
    for c in got["pool"]:
        assert c.rendered or c.decline in B.CHAIN_REASONS, (c.rendered, c.decline)
    assert sum(1 for c in got["pool"] if c.rendered) == bd.knobs.chain_render_k


def test_the_diversity_rule_folds_on_the_SERIES_key_so_one_reading_is_never_two_chains():
    """DESIGN B.2's diversity rule with the fix lane's own fold. Two drivers served by ONE series --
    `El_Nino` and `La_Nina` off one ONI print, the estate's own example -- are ONE reading, and
    rendering both would be the defect `_series_fold` / `group_keep` / `fold_relation` closed on four
    other surfaces in the pre-arm fix."""
    bd = _cboard(mode="max")
    oni = _cs("oni", pct=93, z=2.4)
    _crow(bd, "a_cbot", "El_Nino", st=oni, series_key="oni")
    _crow(bd, "a_cbot", "La_Nina", st=oni, series_key="oni")
    _crow(bd, "a_cbot", "b1", st=_cs("b1", pct=50), series_key="b1")
    _crow(bd, "a_cbot", "b2", st=_cs("b2", pct=50), series_key="b2")
    _cpath(bd, "a_cbot", ["El_Nino", "b1"])
    _cpath(bd, "a_cbot", ["La_Nina", "b2"])
    _cfinish(bd)
    got = W.chain_rows(bd, None, knobs=bd.knobs)
    rendered = [c for c in got["pool"] if c.rendered]
    assert len(rendered) == 1, [c.hop_ids for c in rendered]
    assert got["pool"][0].hops[0].fold_key == ("series", "oni")


def test_the_SIGN_DIVERSITY_rule_carries_both_sides_and_says_so_when_only_one_exists():
    """OWNER, 2026-09-17: disagreement is where convexity lives and it must be STRUCTURAL, never left
    to the writer to notice. Where both sides of the anchor carry a chain above the line the render
    carries the best FOR and the best AGAINST; where only one side exists, the block SAYS SO."""
    bd = _cboard(mode="max")
    up = {"direction": "up", "length": 3, "since_date": "2026-06-30"}
    # a '+' driver rising -> higher;  a '-' driver rising -> lower
    _crow(bd, "a_cbot", "bull", sign="+", st=_cs("bull", pct=97, run=up), series_key="bull")
    _crow(bd, "a_cbot", "bear", sign="-", st=_cs("bear", pct=96, run=up), series_key="bear")
    _crow(bd, "a_cbot", "bull2", sign="+", st=_cs("bull2", pct=95, run=up), series_key="bull2")
    # THE BOTTOM HOP SHARES ITS TOP'S DECLARED SIGN so the relative sign is '+' and the two readings
    # AGREE. With opposite signs the chain runs against itself and is UNSETTLED -- which is the rule
    # working rather than a fixture detail, and the test below pins that case on its own.
    for t, sg in (("bull", "+"), ("bear", "-"), ("bull2", "+")):
        _crow(bd, "a_cbot", "x_" + t, sign=sg, st=_cs("x_" + t, pct=50), series_key="x_" + t)
        _cpath(bd, "a_cbot", [t, "x_" + t])
    _cfinish(bd)
    got = W.chain_rows(bd, None, knobs=bd.knobs)
    rendered = [c for c in got["pool"] if c.rendered]
    assert {c.side for c in rendered} >= {"for", "against"}, [(c.hop_ids, c.side) for c in rendered]
    assert "opposite ways" in got["disagreement"]
    # ONE SIDE ONLY -> the block says so rather than staying silent about the absence
    one = W.chain_render_set([c for c in got["pool"] if c.side == "for"], k=3, print_line=0.0)
    assert "no chain above the line points the other way" in one["disagreement"] or \
        "none points the other way" in one["disagreement"]


def test_a_chain_is_never_ranked_down_for_disagreeing_and_the_hop_that_runs_against_is_NAMED():
    """Disagreement is INFORMATION, not noise: the per-hop verdict is a FIELD and the print line is a
    FIELD, never a filter. A chain whose middle hop runs against its declared direction scores exactly
    what the same chain scores with the hop agreeing, and the block names the hop."""
    def _one(child_delta):
        bd = _cboard()
        _crow(bd, "a_cbot", "top", sign="+", st=_cs("top", pct=95,
                                                    changes=[{"window": "1m", "delta": 1.0}]))
        _crow(bd, "a_cbot", "bot", sign="+", st=_cs("bot", pct=50,
                                                    changes=[{"window": "1m", "delta": child_delta}]))
        _cpath(bd, "a_cbot", ["top", "bot"])
        _cfinish(bd)
        return W.chain_rows(bd, None, knobs=bd.knobs)["pool"][0]
    agree, against = _one(1.0), _one(-1.0)
    assert agree.agreements[0] == "aligned" and against.agreements[0] == "at_odds"
    assert agree.score == against.score, "a chain was ranked down for disagreeing"
    assert against.against_hops == ("top",)
    assert against.side == "unsettled"
    # THE SENTENCE NAMES THE HOP, AND IT SPENDS NO CHARGED TOKEN DOING IT (review round 2 M1): the
    # first cut said "the direction THE GRAPH declares for it", which `register.desk_register_hits`
    # charges on every rendered chain of every tier.
    words = W.chain_disagreement_words([against])
    assert "runs against the direction declared for it" in words
    # THE TRACE'S SENTENCE, GRADED BY THE ELEVEN-NAME TABLE IT WAS WRITTEN UNDER (see the M1 pin below):
    # the page's own sides row is the render's (`render.sb_chain_sides`), graded by the extended table.
    _v1 = set(getattr(REG, "DESK_REGISTER_V1_NAMES", ()) or ())
    assert "the graph" not in words
    assert [h for h in REG.desk_register_hits(words) if not _v1 or h[0] in _v1] == []


# ── the declared sign, and the composition the shipped schema licenses ───────────────────────────────
def test_the_relative_sign_between_two_hops_is_the_PRODUCT_of_their_own_declared_signs():
    """`Driver.sign` is "the driver's effect on the contract's target_metric" (causal/schema.py:8-10),
    NOT its sign onto its child, so the only composition the schema licenses is the product -- a '+'
    parent of a '-' child pushes it DOWN. `'0'` is a DECLARED word and is not a sign (sec 1.5), so the
    pair has no relative sign and the verdict is `undetermined`: stated, never guessed."""
    assert W.hop_edge_sign("+", "+") == "+"
    assert W.hop_edge_sign("-", "-") == "+"
    assert W.hop_edge_sign("+", "-") == "-"
    assert W.hop_edge_sign("0", "+") == ""
    assert W.hop_edge_sign("", "+") == ""


def test_the_chains_declared_direction_telescopes_onto_the_TOP_hops_own_sign():
    """The product of the relative signs along a chain composed with the bottom hop's own sign onto
    the price is `s0 * s1^2 * ... = s0` -- so a chain's declared direction onto the anchor IS its top
    hop's own declared sign, which is what `ancestor_paths` already says of the BAND ("the band on the
    row is the TOP node's own, never a sum"), arrived at from the other end. An EARNED cross hop then
    carries it onto the far board through the EDGE's own sign."""
    hops = (W.ChainHop(contract="a", driver_id="t", sign="-"),
            W.ChainHop(contract="a", driver_id="m", sign="+"),
            W.ChainHop(contract="a", driver_id="b", sign="-"))
    assert W.chain_declared_sign(hops) == "-"
    assert W.chain_declared_sign(hops, cross_sign="-") == "+"
    assert W.chain_declared_sign(hops, cross_sign="0") == ""
    assert W.chain_declared_sign(()) == ""


# ── the receipt ─────────────────────────────────────────────────────────────────────────────────────
def test_the_receipt_takes_an_OPEN_action_first_a_closed_one_next_and_a_mechanism_sentence_last():
    """DESIGN B.4's order of choice, and the EVENT ladder that prices it. An enacted action inside the
    hop's own window is worth the most a receipt can be worth; a closed one is read AS HISTORY and
    says so in its own words (threat E4: the correction, not the deletion); a dated report sentence
    about the mechanism is worth a third of it; and none says so rather than going quiet (E6)."""
    def _one(**kw):
        bd = _cboard()
        _crow(bd, "a_cbot", "top", st=_cs("top", pct=95), **kw)
        _crow(bd, "a_cbot", "bot", st=_cs("bot", pct=50))
        _cpath(bd, "a_cbot", ["top", "bot"])
        _cfinish(bd)
        return W.chain_rows(bd, None, knobs=bd.knobs)["pool"][0]
    op = _one(event="2026-08-01", event_open=True)
    cl = _one(event="2026-07-01", event_open=False)
    # **THE MECHANISM SENTENCE IS READ AGAINST THE HOP'S OWN WINDOW TOO** (round-5, census 5).
    # Choice (3) now takes the SAME recency bound choice (2) does, so THIS fixture's report is
    # dated INSIDE the 0-1 quarter band it is read against. Round 4 dated it 2026-05-02 -- four
    # months before the as-of, on a hop whose own declared window reaches three -- and scored it
    # 6 of 20, which is the reading the bound refuses. THE LADDER IS UNMOVED: the document this
    # tier is graded on is now one the chain can claim, and the refused one is graded below it.
    me = _one(receipts=[{"date": "2026-08-02", "source": "s", "text": "a report sentence"}])
    no = _one()
    assert (op.receipt_kind, op.terms["event"]) == ("open", 20)
    assert (cl.receipt_kind, cl.terms["event"]) == ("closed", 12)
    assert "history" in cl.receipt_words and "closed" in cl.receipt_words
    assert (me.receipt_kind, me.terms["event"]) == ("mechanism", 6)
    assert (no.receipt_kind, no.terms["event"]) == ("none", 0)
    # ...and a report sentence OLDER than the hop's own declared window is NOT this chain's
    # receipt under choice (3) either -- the same 2026-05-02 date round 4 scored six for.
    old_me = _one(receipts=[{"date": "2026-05-02", "source": "s",
                             "text": "a report sentence"}])
    assert (old_me.receipt_kind, old_me.terms["event"]) == ("none", 0), old_me.receipt_words
    # E6: the absence names WHICH DRAW RAN, never "none exists" -- and owner ruling 6 splits that
    # absence in two, because "nothing in THIS HOP'S WINDOW" and "nothing about this MARKET reached
    # the turn at all" are different facts about a term that scored the same.
    assert "no dated document about this market reached this turn" in no.notes["event"]
    bd = _cboard()
    _crow(bd, "a_cbot", "top", st=_cs("top", pct=95))
    _crow(bd, "a_cbot", "bot", st=_cs("bot", pct=50))
    _crow(bd, "a_cbot", "elsewhere", st=_cs("elsewhere", pct=50),
          receipts=[{"date": "2026-05-02", "source": "s", "text": "a report sentence"}])
    _cpath(bd, "a_cbot", ["top", "bot"])
    _cfinish(bd)
    some = W.chain_rows(bd, None, knobs=bd.knobs)["pool"][0]
    assert some.receipt_kind == "none"
    assert "among the documents this turn retrieved" in some.notes["event"]


def test_B4_a_CLOSED_receipt_older_than_ONE_BAND_LENGTH_is_AGED_OUT_of_the_choice_and_the_term():
    """DESIGN B.4's own clause, which the first cut did not implement (review round 2 M7).
    `NodeRow.event_date` is `max(event_date <= asof)` and is never aged out, so a 2019 action could be
    a 2026 chain's printed receipt AND score the EVENT term 12 of 20. The WORDS were honest ("read as
    history: the window closed"), so this is not the E4 lie -- it is a rank term inflated by a document
    no desk would call a receipt for today's chain, and a stale document put on the page beside it.
    ONE BAND-LENGTH is the hop's OWN declared maximum lag, so the bound is the graph's."""
    def _one(event, lag="0-1 quarters"):
        bd = _cboard(asof="2026-09-07")
        _crow(bd, "a_cbot", "top", lag=lag, st=_cs("top", pct=95), event=event, event_open=False)
        _crow(bd, "a_cbot", "bot", lag=lag, st=_cs("bot", pct=50))
        _cpath(bd, "a_cbot", ["top", "bot"])
        _cfinish(bd)
        return W.chain_rows(bd, None, knobs=bd.knobs)["pool"][0]
    near, old = _one("2026-07-01"), _one("2024-01-01")
    assert (near.receipt_kind, near.terms["event"]) == ("closed", 12)
    assert (old.receipt_kind, old.terms["event"]) == ("none", 0), old.receipt_words
    # A WIDER DECLARED BAND REACHES FURTHER BACK, because the bound is the BAND and not a constant:
    # the same 2024 action sits inside one band-length of a hop that declares twelve quarters.
    wide = _one("2024-01-01", lag="4-12 quarters")
    assert wide.receipt_kind == "closed", wide.receipt_words
    # and the OPEN branch is untouched: an open window is by definition still running
    bd = _cboard(asof="2026-09-07")
    _crow(bd, "a_cbot", "top", st=_cs("top", pct=95), event="2019-01-01", event_open=True)
    _crow(bd, "a_cbot", "bot", st=_cs("bot", pct=50))
    _cpath(bd, "a_cbot", ["top", "bot"])
    _cfinish(bd)
    assert W.chain_rows(bd, None, knobs=bd.knobs)["pool"][0].receipt_kind == "open"


# ── the outcome line ────────────────────────────────────────────────────────────────────────────────
def test_the_outcome_line_is_PAST_TENSE_with_its_sample_size_and_names_the_window_it_had():
    """OWNER ASK, 2026-09-17: the base rate a PM pays for. And the S8 recon's hard measurement beside
    it -- the anchor's front-month tape is ~320 sessions by DECLARATION, `bd.tape` is keyed by anchor
    slug only, and `board_map` declares NO level price series -- so an outcome older than about
    eighteen months is not constructible at zero reads. Both honest forms are pinned: the window the
    array actually covers, named in the sentence, and "no price history over these firings"."""
    dates = ["2024-%02d-15" % m for m in range(1, 13)] + ["2025-%02d-15" % m for m in range(1, 13)]
    vals = [100 - i for i in range(len(dates))]
    firings = [{"index": i, "date": dates[i]} for i in range(0, 12)]
    got = W.chain_outcome(vals, dates, unit="USc/bu", firings=firings,
                          band=parse_lag("0-1 quarters"), declared_sign="-",
                          scope="the front price's own 2024-01-15 to 2025-12-15 window")
    assert got["n"] >= 8 and got["median_move"] is not None
    assert "moved a middle" in got["words"] and "2024-01-15" in got["words"]
    assert "the declared way" in got["words"] and got["share_declared_way"] == got["n"]
    # ONE CALCULATOR, AND IT REFUSES BELOW ITS OWN FLOOR. `stats.quantiles` declines under
    # MIN_QUANTILE_N, so a handful of firings prints the COUNT and the SHARE and says the sample is
    # thin -- a count is not a distribution and must never be dressed as one.
    thin = W.chain_outcome(vals, dates, unit="USc/bu", firings=firings[:2],
                           band=parse_lag("0-1 quarters"), declared_sign="-")
    assert thin["n"] == 2 and thin["median_move"] is None
    assert "too thin for a middle figure" in thin["words"]
    empty = W.chain_outcome([], [], unit="", firings=firings, band=parse_lag("0-1 quarters"))
    # 09-24 FIX ROUND (item 28c, DECLARED): the record line's own noun, never "firings"
    assert (empty["words"] == "no price history over the past times this reading sat this far out"
            and empty["n"] == 0), empty["words"]
    assert "firing" not in got["words"] and "firing" not in thin["words"], (got["words"], thin["words"])


# ── the curated prior, and the adapter that lets it reach a turn ────────────────────────────────────
def test_the_curated_chains_are_a_PRIOR_and_never_a_second_engine():
    """DESIGN B.0 / F5: `notes[kind=chains].rows == ()` on 5 of 5 banked payloads because the seam
    passes `chains=()` and `chain_paths` would raise on the first curated row anyway. A curated row
    MINTS NO CHAIN and REMOVES NONE -- it is worth the CONFIDENCE term at its maximum and the curated
    name on the page, and the composed chain would have existed without it."""
    curated = [{"id": "corn_lanina_safrinha_su", "contracts": ["a_cbot"],
                "hops": [{"node": "top", "ref": "r"}, {"node": "bot", "ref": "r2"}]}]
    idx = W.curated_chain_index(curated)
    assert idx["nodes"]["a_cbot"] == [("corn_lanina_safrinha_su", ("top", "bot"))]
    bd = _cboard()
    _crow(bd, "a_cbot", "top", st=_cs("top", pct=95), conf="low")
    _crow(bd, "a_cbot", "bot", st=_cs("bot", pct=50), conf="low")
    _cpath(bd, "a_cbot", ["top", "bot"])
    _cfinish(bd)
    plain = W.chain_rows(bd, None, knobs=bd.knobs)["pool"][0]
    with_prior = W.chain_rows(bd, None, knobs=bd.knobs, chains=curated)["pool"][0]
    assert plain.curated == "" and with_prior.curated == "corn_lanina_safrinha_su"
    assert with_prior.terms["confidence"] == W.CHAIN_TERM_MAX["confidence"] > plain.terms["confidence"]
    assert len(W.chain_rows(bd, None, knobs=bd.knobs, chains=curated)["pool"]) == 1


def test_chain_paths_reads_BOTH_shipped_maps_instead_of_raising_on_the_first_row(real):
    """THE DEFECT REFUTED #3 NAMES, CLOSED. `cascade.load_chain_map()` rows carry `id` and `hops` of
    DICTS; `chain_paths` read `ch['name']` and then `h in loud` with `h` a dict -- `TypeError:
    unhashable type: 'dict'` on the FIRST row. And its one caller passed BOARD SLUGS while those hops
    are DRIVER NODES, so even without the raise the join would have counted nothing. The axis is now
    DECLARED per row."""
    from leviathan.graphrag.numbers import cascade as CAS
    rows = list(CAS.load_chain_map())
    assert rows and any(isinstance(h, dict) for h in rows[0]["hops"]), "the shipped shape moved"
    nodes = {("corn_cbot", h["node"]) for ch in rows for h in ch["hops"]}
    got = W.chain_paths(rows, ["corn_cbot"], loud_boards={"corn_cbot"},
                        on_nodes=nodes, loud_nodes=nodes)
    assert got and any(c["loud_hops"] for c in got), got[:2]
    assert all(c["axis"] == "node" for c in got)
    # a node-axis row whose own contracts are not on THIS board counts nothing (the string-identity
    # join this estate has a standing memory about, arrived at through a config)
    off = W.chain_paths(rows, ["malaysian_crude_palm_oil_cme"], on_nodes=nodes, loud_nodes=nodes)
    assert all(c["loud_hops"] == 0 for c in off if "corn" in c["name"])
    # and the transmission map's MARKET axis reads as markets
    tm = list(CAS.load_transmission_map())
    if tm:
        assert W.chain_row_shape(tm[0])[0] == "market"
    assert W.chain_paths((), ["corn_cbot"]) == []


def test_E11_a_curated_chains_hops_are_counted_on_ITS_OWN_CONTRACTS_rows_and_never_another_boards():
    """E11 ON THE ORDERING SURFACE F5 JUST OPENED (review round 2 M3). `chain_paths` took a FLAT set of
    driver ids over a board that spans contracts, so on the corn+wheat turn -- one of the five smoke
    payloads -- a curated chain whose hops are `area` and `ending_stocks` counted TWO LOUD HOPS and
    rendered off the OTHER board's two rows, because both DAGs declare both ids. A string-identity join
    on a driver id alone is this estate's standing failure; the join is `(contract, driver_id)`."""
    row = [{"id": "corn_area_su", "contracts": ["corn_cbot"],
            "hops": [{"node": "area"}, {"node": "ending_stocks"}]}]
    board = ["corn_cbot", "soft_red_winter_wheat_cbot"]
    wheat = {("soft_red_winter_wheat_cbot", "area"),
             ("soft_red_winter_wheat_cbot", "ending_stocks")}
    off = W.chain_paths(row, board, loud_boards={"soft_red_winter_wheat_cbot"},
                        on_nodes=wheat, loud_nodes=wheat)[0]
    assert (off["loud_hops"], off["hops_on_board"], off["rendered"]) == (0, 0, False), off
    # the SAME board, once CORN's own rows are on it: the curated corn chain lights, and it lights on
    # its own readings.
    both = wheat | {("corn_cbot", "area"), ("corn_cbot", "ending_stocks")}
    on = W.chain_paths(row, board, loud_boards={"corn_cbot", "soft_red_winter_wheat_cbot"},
                       on_nodes=both, loud_nodes=both)[0]
    assert (on["loud_hops"], on["hops_on_board"], on["rendered"]) == (2, 2, True), on
    # and the SHIPPED wheat row behaves the same way against a corn-only reading set
    from leviathan.graphrag.numbers import cascade as CAS
    shipped = [r for r in CAS.load_chain_map() if r.get("id") == "wheat_area_su"]
    assert shipped, "the shipped curated row moved"
    corn = {("corn_cbot", "area"), ("corn_cbot", "ending_stocks")}
    got = W.chain_paths(shipped, board, loud_boards={"corn_cbot"}, on_nodes=corn, loud_nodes=corn)[0]
    assert (got["loud_hops"], got["rendered"]) == (0, False), got


# ── the trace ───────────────────────────────────────────────────────────────────────────────────────
def test_the_chain_trace_is_BOUNDED_and_carries_what_rendered_plus_what_beat_the_rest():
    """A max board composes 1,848 candidate chains (MEASURED on the fixture) and a `state_board`
    record carrying two thousand chain rows is an instrument nobody can open. The COUNTS carry the
    whole pool; the ROWS carry what rendered and what it was beaten by, rendered first, and no arrays
    ride either (DESIGN A.7's "NO ARRAYS")."""
    bd = _cboard(mode="max")
    for i in range(20):
        _crow(bd, "a_cbot", "t%d" % i, st=_cs("t%d" % i, pct=90 + (i % 10)))
        _crow(bd, "a_cbot", "b%d" % i, st=_cs("b%d" % i, pct=50))
        _cpath(bd, "a_cbot", ["t%d" % i, "b%d" % i])
    _cfinish(bd)
    got = W.chain_rows(bd, None, knobs=bd.knobs)
    bd.chains, bd.chain_counts = got["pool"], got["counts"]
    bd.trace_rows = True
    tr = bd.trace()
    assert len(tr["chains"]) == W.CHAIN_TRACE_K < len(bd.chains)
    assert tr["chain_counts"]["total"] == len(bd.chains)
    assert all(c["rendered"] for c in tr["chains"][:got["counts"]["rendered"]])
    blob = json.dumps(tr["chains"])
    assert "values" not in blob and "dates" not in blob, "an array reached the payload"
    assert isinstance(tr["rows"], int) and isinstance(tr["row_states"], list)
    assert {"contract", "driver_id", "percentile", "loud"} <= set(tr["row_states"][0])


def test_chain_explain_fills_the_seven_sentences_and_moves_no_score():
    """The arithmetic line is what makes the selection falsifiable on the page (DESIGN B.2), so it is
    not optional -- only DEFERRED to the chains a reader meets. MEASURED: building seven sentences for
    every candidate cost 2.5 seconds on a board whose whole stage 2 is 108 ms."""
    bd = _cboard()
    _crow(bd, "a_cbot", "top", st=_cs("top", pct=95))
    _crow(bd, "a_cbot", "bot", st=_cs("bot", pct=50))
    _cpath(bd, "a_cbot", ["top", "bot"])
    _cfinish(bd)
    ch = W.chain_rows(bd, None, knobs=bd.knobs)["pool"][0]
    before = ch.score
    W.chain_explain(ch, named_markets=("a_cbot",), horizon_months=3)
    assert ch.score == before
    assert set(ch.notes) == set(W.CHAIN_TERMS)
    for t, words in ch.notes.items():
        assert words and words == words.encode("ascii", "ignore").decode("ascii"), t


def test_the_rank_is_100_points_and_the_receipt_hop_rule_has_ONE_reader():
    """DESIGN B.2's ceiling, and the ONE rule that decides where the action is looked for, which record
    is read and which reading the diversity fold keys on. `chain_score` re-derives the same index from
    the same tuple that `_compose` chose it with -- two readers of one rule, pinned."""
    assert sum(W.CHAIN_TERM_MAX.values()) == 100.0
    assert set(W.CHAIN_TERM_MAX) == set(W.CHAIN_TERMS)
    hops = (W.ChainHop(contract="a", driver_id="quiet", tail=0.1, seat=0),
            W.ChainHop(contract="a", driver_id="loud", tail=0.9, seat=5))
    assert W.chain_receipt_index(hops) == 1
    ch = W.Chain(contract="a", hops=hops, depth=1, terminal="a")
    ch.edge_signs, ch.agreements = ("", ""), ("undetermined", "undetermined")
    W.chain_score(ch, named_markets=("a",), horizon_months=None, history={})
    assert ch.receipt_index == 1
    assert 0.0 <= ch.score <= 100.0
    # TIES ON THE TAIL BREAK ON THE BOARD'S OWN SEAT, never the alphabet
    tied = (W.ChainHop(contract="a", driver_id="zeta", tail=0.5, seat=1),
            W.ChainHop(contract="a", driver_id="alpha", tail=0.5, seat=9))
    assert W.chain_receipt_index(tied) == 0


# ═════════════════════════════════════════════════════════════════════════════════════════════════════
# S8 LANE W, ROUND 2 -- THE FIX ROUND'S OWN PINS
#
# Six review MAJORs and four owner rulings, each with the measurement that found it. Everything here is
# offline: two pins build the SHIPPED fixture board through the walk (zero reads, the state producer is
# the harness's own), the rest are hand-made rows.
# ═════════════════════════════════════════════════════════════════════════════════════════════════════
@pytest.fixture(scope="module")
def chain_tiers(real):
    """The fixture soybeans board at all three tiers with the chain leg ARMED -- the same path
    `seam.fill_stage2` drives, at zero reads."""
    from leviathan.graphrag.numbers import cascade as CAS
    from leviathan.graphrag.state import __main__ as H
    from leviathan.graphrag.state import render as R
    curated = list(CAS.load_chain_map()) + list(CAS.load_transmission_map())
    out = {}
    for mode in ("quick", "deep", "max"):
        anchors = W.resolve_anchors(named=("soybeans_cbot",))
        bd = W.walk(graph=real, asof=H.ASOF, mode=mode, anchors=anchors,
                    question="what is the situation on soybeans now? and 3 months from now?",
                    state_fn=H.fixture_state_fn(H.ASOF), key_fn=None, receipts={},
                    knobs=B.board_knobs_of(mode), width=2, legb_on=False, stage2=False)
        R.attach_tape(bd, {s: H.fixture_tape(s, H.ASOF) for s in bd.anchor_slugs}, reads_each=0)
        W.stage2(bd, real, state_fn=H.fixture_state_fn(H.ASOF), receipts={}, width=2,
                 legb_on=False, chains=curated, state_chain=True)
        out[mode] = bd
    return out


def _chain_prose(bd):
    """EVERY SENTENCE THE CHAIN MOVEMENT PRODUCES for the chains a reader or the arm meets."""
    out = []
    for c in bd.chains:
        if not c.rendered:
            continue
        out.extend((("notes." + k), v) for k, v in sorted(c.notes.items()))
        out.append(("receipt", c.receipt_words))
        out.append(("history", (c.history or {}).get("words") or ""))
        out.append(("outcome", (c.outcome or {}).get("words") or ""))
    out.append(("disagreement", (bd.chain_counts or {}).get("disagreement") or ""))
    return [(k, str(v)) for k, v in out if str(v).strip()]


def test_M1_every_rendered_chains_OWN_PROSE_is_register_clean_at_ALL_THREE_TIERS(chain_tiers):
    """REVIEW ROUND 2, M1. `chain_score` built `notes['reach']` as "depth 2, reaching corn_cbot, a
    market this question did not name" -- a RAW CONTRACT SLUG -- and `notes['tail']` / `['asymmetry']`
    printed raw driver ids, beside `chain_disagreement_words`' charged `the graph`. MEASURED before the
    fix: of the 60 sentences the rendered chains carried across the three tiers SIX tripped the block's
    own fence (`register.internal_leaks`), one per rendered chain on every tier, and `Block.add`
    answers a tripping line by REPLACING it and dropping its citations. The producers already existed
    -- `render.humanise` for a node, `render.board_label` for a market, which is what `sb_path` uses on
    the very class this one replaces.

    NO PIN IN THIS LANE GRADED THE CHAIN'S OWN PROSE, which is exactly how six tripping sentences
    reached a build report claiming the block's bytes were measured. This is that pin."""
    from leviathan.graphrag.state import render as R
    # **THESE ARE THE TRACE'S SENTENCES, GRADED BY THE TABLE THEY WERE WRITTEN UNDER** (the 09-23 fix
    # round). The desk table grows by the owner-named instrument words (CONTRACT C13: "hop", "firing",
    # "declared way", ...) to grade the PAGE's migrated row classes -- lane R's row-class lint, over the
    # render's own templates, and the page's history line is the render's twin
    # (`render.chain_record_words`). The walk's prose rides the trace and the arm report; it is graded
    # here by the ELEVEN-name table it has always met (`register.DESK_REGISTER_V1_NAMES` where the
    # frozen roster is published, the whole table where it is not), so the extension neither reds a
    # trace sentence nor lets one drift under the table it was written for.
    _v1 = set(getattr(REG, "DESK_REGISTER_V1_NAMES", ()) or ())
    for mode, bd in chain_tiers.items():
        prose = _chain_prose(bd)
        assert prose, mode
        assert sum(1 for c in bd.chains if c.rendered) == bd.knobs.chain_render_k, mode
        for kind, s in prose:
            assert R.register_hits(s) == [], (mode, kind, s)
            assert REG.internal_leaks(s) == [], (mode, kind, s)
            v1_hits = [h for h in REG.desk_register_hits(s) if not _v1 or h[0] in _v1]
            assert v1_hits == [], (mode, kind, s)
            assert s == s.encode("ascii", "ignore").decode("ascii"), (mode, kind, s)


def test_M1_the_notes_name_a_market_and_a_driver_through_the_estates_ONE_display_vocabulary():
    """The same defect at the unit, so the pin above cannot pass by an accident of the fixture."""
    from leviathan.graphrag.state import render as R
    bd = _cboard()
    _crow(bd, "a_cbot", "psd_ending_stock_su_ratio", st=_cs("su", pct=3))
    _crow(bd, "a_cbot", "bot", st=_cs("bot", pct=50))
    _cpath(bd, "a_cbot", ["psd_ending_stock_su_ratio", "bot"])
    _cfinish(bd)
    ch = W.chain_explain(W.chain_rows(bd, None, knobs=bd.knobs)["pool"][0],
                         named_markets=("a_cbot",))
    assert "psd_ending_stock_su_ratio" not in ch.notes["tail"]
    assert R.humanise("psd_ending_stock_su_ratio") in ch.notes["tail"]
    assert "a_cbot" not in ch.notes["reach"] and R.board_label("a_cbot") in ch.notes["reach"]


def test_M2_the_array_memo_key_carries_the_ASOF_the_OFFSET_and_the_MIRROR_EPOCH():
    """REVIEW ROUND 2, M2 -- a POINT-IN-TIME breach, and the immortal kind. `hop_arrays` memoised on
    `st.key.label()` alone, in a module global with a process lifetime, so the SECOND turn's history
    stat was computed on the FIRST turn's array. MEASURED before the fix: a second reader of
    `oni_climate|_global|` got [1.0, 2.0, 3.0] where its own array is [1.0 .. 5.0], and
    `feeders.cache_clear()` left the entry in place."""
    from leviathan.graphrag.state import feeders as F
    W.cache_clear()
    a = _cs("oni_climate", values=[1.0, 2.0, 3.0], dates=["2024-01-31", "2024-02-29", "2024-03-31"])
    a.asof = "2024-04-01"
    b = _cs("oni_climate", values=[1.0, 2.0, 3.0, 4.0, 5.0],
            dates=["2024-01-31", "2024-02-29", "2024-03-31", "2024-04-30", "2024-05-31"])
    b.asof = "2026-09-07"
    assert a.key.label() == b.key.label(), "the two rows must share a label for this to mean anything"
    assert W.hop_arrays(a)[0] == (1.0, 2.0, 3.0)
    assert W.hop_arrays(b)[0] == (1.0, 2.0, 3.0, 4.0, 5.0), "one label, two as-ofs, one entry"
    assert W.array_memo_key(a, a.key.label()) != W.array_memo_key(b, b.key.label())
    # THE DECLARED SAME-SERIES OFFSET IS ON THE KEY for the reason `feeders.state_cache_key`'s own
    # docstring gives: the same array, shifted, is a different STATE.
    c = _cs("oni_climate", values=[9.0, 9.0, 9.0], dates=["2024-01-31", "2024-02-29", "2024-03-31"])
    c.asof, c.offset_months = a.asof, 6
    assert W.array_memo_key(c, c.key.label()) != W.array_memo_key(a, a.key.label())
    assert W.array_memo_key(a, a.key.label())[-1] == F.mirror_epoch()
    # AND THE ESTATE'S ONE CLEAR SEAM REACHES IT (the board census calls it between boards)
    assert W._ARRAY_MEMO
    F.cache_clear()
    assert not W._ARRAY_MEMO and not W._DATE_KEY_MEMO


def test_M4_sign_diversity_tests_the_REPLACEMENT_before_it_drops_and_never_renders_K_minus_1():
    """REVIEW ROUND 2, M4. Clause (4) removed the worst chain on the crowded side and only THEN called
    `_take(other)`, which can refuse on the diversity fold -- so the reviewer's 90 / 80 / 70 case (k=2,
    two FOR and one AGAINST that shares the survivor's receipt reading) rendered ONE chain where three
    existed. Fewer than K is right when fewer EXIST, never when more did."""
    def _ch(score, side, top, rcpt):
        hops = (W.ChainHop(contract="a", driver_id=top, series_key=top, tail=0.9, seat=0),
                W.ChainHop(contract="a", driver_id=rcpt, series_key=rcpt, tail=0.95, seat=1))
        c = W.Chain(contract="a", hops=hops, depth=1, terminal="a")
        c.score, c.side, c.receipt_index = score, side, 1
        return c
    a = _ch(90.0, "for", "t1", "shared")
    b = _ch(80.0, "for", "t2", "own")
    d = _ch(70.0, "against", "t3", "shared")        # shares the SURVIVOR's receipt reading
    got = W.chain_render_set([a, b, d], k=2, print_line=40.0)
    assert len(got["rendered"]) == 2, [c.hop_ids for c in got["rendered"]]
    assert {c.score for c in got["rendered"]} == {90.0, 80.0}
    # AND WHERE THE SWAP DOES CLOSE IT STILL HAPPENS: an AGAINST chain that folds cleanly takes the
    # weaker FOR chain's seat, which is the clause doing its own job.
    e = _ch(70.0, "against", "t4", "free")
    got2 = W.chain_render_set([a, b, e], k=2, print_line=40.0)
    assert {c.side for c in got2["rendered"]} == {"for", "against"}
    assert {c.score for c in got2["rendered"]} == {90.0, 70.0}


def test_M5_the_firing_separation_is_the_ARRAYS_OWN_PERIODS_and_never_a_month_count():
    """REVIEW ROUND 2, M5. `chain_history` passed the band's MONTHS as `min_separation`, which
    `chain_firings` compares against ARRAY INDEXES. MEASURED: a DAILY parent over a 1-2 quarter band
    kept 83 firings where a true six-month separation keeps 3, and an ANNUAL parent under the same call
    skipped SIX YEARS between firings. `n_firings` is a PRINTED figure with its sample size, so the
    number the reader was handed moved with the card's cadence and nothing declared it."""
    daily = _cs("d", values=[1.0], dates=["2026-01-01"])
    daily.cadence = "daily"
    annual = _cs("a", values=[1.0], dates=["2026-01-01"])
    annual.cadence = "annual"
    assert W.separation_periods(6, daily) == 126, "six months of a daily card is ~126 sessions"
    assert W.separation_periods(6, annual) == 1, "six months of an ANNUAL card is one period"
    assert W.separation_periods(6, _cs("m", values=[], dates=[])) == 6, "the monthly card is itself"
    import datetime as _d
    dd = [(_d.date(2023, 1, 2) + _d.timedelta(days=i)).isoformat() for i in range(1000)]
    dv = [float((i % 20) if (i // 20) % 2 == 0 else (20 - (i % 20))) for i in range(1000)]
    shipped = W.chain_firings(dv, dd, direction=1, min_separation=6, asof="2026-09-07",
                              close_months=6)
    fixed = W.chain_firings(dv, dd, direction=1, min_separation=W.separation_periods(6, daily),
                            asof="2026-09-07", close_months=6)
    assert len(fixed) < len(shipped) and len(fixed) <= 8, (len(shipped), len(fixed))
    ad = ["%d-12-31" % y for y in range(1995, 2025)]
    av = [float(y % 3) for y in range(1995, 2025)]
    a_shipped = W.chain_firings(av, ad, direction=1, min_separation=6, asof="2026-09-07",
                                close_months=6)
    a_fixed = W.chain_firings(av, ad, direction=1, min_separation=W.separation_periods(6, annual),
                              asof="2026-09-07", close_months=6)
    assert len(a_fixed) > len(a_shipped), (len(a_shipped), len(a_fixed))
    # AND A CARD THAT DECLARES NO CADENCE IS ANSWERED BY ITS OWN ARRAY, never by a guess.
    weekly = [(_d.date(2026, 1, 5) + _d.timedelta(days=7 * i)).isoformat() for i in range(40)]
    assert W.separation_periods(6, None, weekly) >= 20


def test_RULING_5_the_TAIL_term_reads_the_hops_DECLARED_LAG_WINDOW_and_prints_peak_AND_latest():
    """OWNER RULING 5, 2026-09-18. A shock is IN TRANSIT for the length of its declared lag: a reading
    that peaked at the 97th percentile three months ago and eased to the 80th is still acting on the
    next hop while the window runs. The TAIL term reads the LOUDEST knowable reading inside
    [as-of - max_lag, as-of]; the LATEST reading alone stays the SB-1 figure, and the chain prints
    BOTH."""
    vals = [50.0] * 20 + [99.0, 60.0, 60.0]
    dates = (["2024-%02d-28" % (1 + i) for i in range(12)]
             + ["2025-%02d-28" % (1 + i) for i in range(8)]
             + ["2026-03-31", "2026-06-30", "2026-08-31"])
    bd = _cboard(asof="2026-09-07")
    _crow(bd, "a_cbot", "peaky", lag="0-2 quarters", st=_cs("peaky", pct=57, values=vals,
                                                            dates=dates))
    _crow(bd, "a_cbot", "bot", lag="0-2 quarters", st=_cs("bot", pct=50))
    _cpath(bd, "a_cbot", ["peaky", "bot"])
    _cfinish(bd)
    ch = W.chain_explain(W.chain_rows(bd, None, knobs=bd.knobs)["pool"][0],
                         named_markets=("a_cbot",))
    hop = ch.hops[0]
    assert hop.percentile == 57 and hop.tail < 0.2, "the LATEST reading is mid-record"
    assert hop.tail_peak > 0.9 and hop.tail_peak_date == "2026-03-31", (hop.tail_peak,
                                                                       hop.tail_peak_date)
    assert hop.chain_tail == hop.tail_peak, "the chain's measure is the window's peak"
    assert ch.terms["tail"] > 20.0, ch.terms
    assert "peaked at the" in ch.notes["tail"] and "reads the 57th now" in ch.notes["tail"]
    assert "the declared lag runs to" in ch.notes["tail"]
    # THE WINDOW IS THE HOP'S OWN DECLARED LAG AND NOT A CONSTANT: a hop whose band ends before that
    # peak cannot see it.
    bd2 = _cboard(asof="2026-09-07")
    _crow(bd2, "a_cbot", "peaky", lag="0-1 quarters",
          st=_cs("peaky", pct=57, values=vals, dates=dates))
    _crow(bd2, "a_cbot", "bot", lag="0-1 quarters", st=_cs("bot", pct=50))
    _cpath(bd2, "a_cbot", ["peaky", "bot"])
    _cfinish(bd2)
    narrow = W.chain_rows(bd2, None, knobs=bd2.knobs)["pool"][0]
    assert narrow.hops[0].tail_peak < 0.9, narrow.hops[0].tail_peak


def test_RULING_1_POSITIONING_crowded_the_chains_own_way_is_ASYMMETRY_and_it_is_PRINTED():
    """OWNER RULING 1, 2026-09-18 ("how does it know how convex the market is?"). The ASYMMETRY term
    read BUFFER rows and never POSITIONING, and the smoke's own PM read flagged twice that a
    100th-percentile managed-money long into a bullish call is the risk that kills the position. A COT
    row at or past the 90th / 10th percentile of its own record, crowded the way the chain argues,
    gains five points INSIDE the ten and says so; crowded the other way it is printed as the cushion it
    is and scores nothing. It is a RANK TERM and never a filter."""
    def _one(cot_pct, sign):
        up = {"direction": "up", "length": 3, "since_date": "2026-06-30"}
        bd = _cboard(mode="max", asof="2026-09-07")
        _crow(bd, "a_cbot", "top", sign=sign, st=_cs("top", pct=60, run=up))
        _crow(bd, "a_cbot", "bot", sign=sign, st=_cs("bot", pct=55))
        r = _crow(bd, "a_cbot", "cot_mm_positioning", st=_cs("cot", pct=cot_pct))
        r.silver_ref = "cot_mm_positioning"
        _cpath(bd, "a_cbot", ["top", "bot"])
        _cfinish(bd)
        return W.chain_explain(W.chain_rows(bd, None, knobs=bd.knobs)["pool"][0],
                               named_markets=("a_cbot",), anchor=W.anchor_facts(bd, "a_cbot"))
    same, other, quiet = _one(99, "+"), _one(1, "+"), _one(50, "+")
    assert same.direction == "higher" and other.direction == "higher"
    assert same.terms["asymmetry"] == quiet.terms["asymmetry"] + 5.0, (same.terms, quiet.terms)
    assert "crowded the same way" in same.notes["asymmetry"]
    assert "makes the reversal abrupt" in same.notes["asymmetry"]
    assert other.terms["asymmetry"] == quiet.terms["asymmetry"]
    assert "crowded the other way" in other.notes["asymmetry"]
    assert same.terms["asymmetry"] <= W.CHAIN_TERM_MAX["asymmetry"], "capped inside the ten"


def test_RULING_2_the_anchors_PRICE_row_feeds_TAIL_when_the_chain_terminates_on_the_price():
    """OWNER RULING 2, 2026-09-18 ("by the futures price?"). The TAIL term read every HOP's percentile
    and never the terminal's. Where no cross is earned the chain lands on the anchor's own front price,
    so a chain terminating on a price at the 97th percentile of its own record scores tail on the
    terminal too -- and the sentence says the richer standing (the front spread, the curve, realised
    volatility) is not served on this page."""
    from leviathan.graphrag.state.rows import TapeState
    bd = _cboard(asof="2026-09-07")
    _crow(bd, "a_cbot", "top", st=_cs("top", pct=52))
    _crow(bd, "a_cbot", "bot", st=_cs("bot", pct=48))
    _cpath(bd, "a_cbot", ["top", "bot"])
    _cfinish(bd)
    quiet = W.chain_explain(W.chain_rows(bd, None, knobs=bd.knobs)["pool"][0],
                            named_markets=("a_cbot",), anchor=W.anchor_facts(bd, "a_cbot"))
    bd.tape["a_cbot"] = TapeState(slug="a_cbot", status="ok", level=1200.0,
                                  percentile={"value": 97.0, "n": 250},
                                  window_note="250 sessions")
    loud = W.chain_explain(W.chain_rows(bd, None, knobs=bd.knobs)["pool"][0],
                           named_markets=("a_cbot",), anchor=W.anchor_facts(bd, "a_cbot"))
    assert loud.terms["tail"] > quiet.terms["tail"], (loud.terms, quiet.terms)
    assert "97th percentile" in loud.notes["tail"]
    assert "not served on this page" in loud.notes["tail"]
    assert loud.scope["price_read"] is True and quiet.scope["price_read"] is False


def test_RULING_6_the_PRINT_LINE_never_renders_fewer_than_K_and_the_SCOPE_says_what_the_page_had():
    """OWNER RULING 6, 2026-09-18: each anchor is judged on the data it has. The rank is RELATIVE
    WITHIN ONE BOARD, so the top K render ALWAYS and a low score reads as SCARCE DATA -- which is only
    honest because the chain carries its own data scope.

    **AND THEY RENDER IN FULL** (review MA-1, closed round 3). The first cut kept the line as the FULL
    versus ONE-LINE decision and that is the rule the parenthetical of ruling 6(a) NAMES -- "drop the
    absolute print line (score >= 40 to render in full): the top K render in full ALWAYS". ONE FIELD
    was carrying two readings: this very pool rendered THREE chains, `full=False` on all three, while
    `below_print_line` said four of four sat below a line three of them were printed above. Now
    `Chain.full` means "rendered in full" and the count is computed from the SCORE over the chains
    that did NOT render."""
    bd = _cboard(mode="max")                    # k = 3
    for i in range(5):
        _crow(bd, "a_cbot", "t%d" % i, conf="low", st=_cs("t%d" % i, pct=50))
        _crow(bd, "a_cbot", "b%d" % i, conf="low", st=_cs("b%d" % i, pct=50))
        _cpath(bd, "a_cbot", ["t%d" % i, "b%d" % i])
    _cfinish(bd)
    got = W.chain_rows(bd, None, knobs=bd.knobs)
    rendered = [c for c in got["pool"] if c.rendered]
    assert all(c.score < bd.knobs.chain_print_line for c in got["pool"]), "the fixture must be poor"
    assert len(rendered) == bd.knobs.chain_render_k, [c.score for c in rendered]
    assert all(c.full is True for c in rendered), "the top K render IN FULL, always"
    assert got["counts"]["below_print_line"] == len(got["pool"]) - len(rendered), got["counts"]
    assert got["counts"]["rendered_one_line"] == 0
    assert not any(c.decline == "below_print_line" for c in got["pool"]), \
        "the line is a COUNT and no longer a cut, so no chain declines for it"
    sc = rendered[0].scope
    assert sc["terms_total"] == 7 and 0 <= sc["terms_scored"] <= 7
    assert sc["hops"] == 2 and sc["hops_no_series"] == 0


def test_MA1_a_data_poor_pool_renders_THREE_FULL_chains_and_counts_ONE_below_the_line():
    """**THE REVIEWER'S OWN UNIT, MOVED WITH THE BEHAVIOUR** (review MA-1 / census blocker 5). The
    measurement that found it: a pool of four chains at 30 / 22 / 15 / 9 with k=3 rendered three, ALL
    THREE as one-liners, and `below_print_line` read 4 of a pool of 4 while three of those four were
    ON THE PAGE. The reading now: three chains rendered IN FULL, and the ONE chain below the line that
    is counted is the one that did not render."""
    pool = []
    for i, sc in enumerate((30.0, 22.0, 15.0, 9.0)):
        ch = W.Chain(contract="a_cbot", terminal="a_cbot", depth=1,
                     hops=(W.ChainHop(contract="a_cbot", driver_id="t%d" % i, seat=i),
                           W.ChainHop(contract="a_cbot", driver_id="b%d" % i, seat=i + 10)))
        ch.score = sc
        pool.append(ch)
    got = W.chain_render_set(pool, k=3, print_line=40.0)
    rendered = got["rendered"]
    assert [c.score for c in rendered] == [30.0, 22.0, 15.0]
    assert all(c.full is True for c in rendered), "the top K render in full, ALWAYS"
    assert all(c.slot == "top" for c in rendered)
    assert got["counts"]["below_print_line"] == 1, got["counts"]
    assert got["counts"]["rendered_one_line"] == 0
    # and the one NOT rendered is the one the count names
    assert [c.score for c in pool if not c.rendered] == [9.0]


def test_RULING_6b_the_BUFFER_family_is_resolved_PER_ANCHOR_and_its_absence_is_PRINTED():
    """OWNER RULING 6b, 2026-09-18. The ASYMMETRY term's buffer family is whatever THAT MARKET's cards
    declare -- the desk-convention registry's own percentile-band and pace series plus
    `verify.BAR_FAMILY_REFS` -- never the design's literal token list. A market with no buffer series
    scores zero on that clause and the sentence SAYS SO, so the absence reads as scarce data and never
    as a chain that failed a test."""
    fam = W.registry_buffer_refs()
    assert "psd_ending_stock_su_ratio" in fam and "mpob_ending_stocks" in fam
    assert "cot_mm_positioning" not in fam, "positioning is its own family and its own term"
    bd = _cboard()
    r = _crow(bd, "a_cbot", "su", st=_cs("su", pct=2))
    r.silver_ref = "psd_ending_stock_su_ratio"
    _crow(bd, "a_cbot", "bot", st=_cs("bot", pct=50))
    _cpath(bd, "a_cbot", ["su", "bot"])
    _cfinish(bd)
    af = W.anchor_facts(bd, "a_cbot")
    assert af.buffer_served and af.buffer_ids == frozenset({"su"})
    ch = W.chain_explain(W.chain_rows(bd, None, knobs=bd.knobs)["pool"][0],
                         named_markets=("a_cbot",), anchor=af)
    assert ch.terms["asymmetry"] == 10.0, ch.terms
    # and a market that serves NONE says so, in its own sentence
    bd2 = _cboard()
    _crow(bd2, "a_cbot", "weather", st=_cs("weather", pct=50))
    _crow(bd2, "a_cbot", "bot", st=_cs("bot2", pct=50))
    _cpath(bd2, "a_cbot", ["weather", "bot"])
    _cfinish(bd2)
    af2 = W.anchor_facts(bd2, "a_cbot")
    assert not af2.buffer_served
    ch2 = W.chain_explain(W.chain_rows(bd2, None, knobs=bd2.knobs)["pool"][0],
                          named_markets=("a_cbot",), anchor=af2)
    assert "no buffer series is served for this market" in ch2.notes["asymmetry"]
    assert ch2.scope["buffer_series"] is False


# ═════════════════════════════════════════════════════════════════════════════════════════════════════
# S8 LANE W, ROUND 3 -- THE SEAM, THE COUNTS THAT STOPPED CONTRADICTING THE PAGE, AND THE RENDER SLOTS
#
# LAW (a) FROM ROUND 2: A CROSS-LANE PIN ASSERTS AGAINST THE SHIPPED TYPE. Four owner-ordered surfaces
# rendered NOTHING while every pin on both sides was green, because every pin asserted against a
# `types.SimpleNamespace` stand-in carrying whatever name its author hoped for. Everything below
# resolves against a REAL `walk.Chain` / `walk.ChainHop` / `walk.chain_counts`.
# ═════════════════════════════════════════════════════════════════════════════════════════════════════
def _seam_targets(chain_tiers):
    """The three SHIPPED objects the seam names live on, taken off the deep fixture board."""
    bd = chain_tiers["deep"]
    ch = next(c for c in bd.chains if c.rendered)
    return bd, ch, ch.receipt_hop


def test_R3_CHAIN_SEAM_FIELDS_RESOLVES_ON_THE_SHIPPED_TYPES_BUILT_FROM_THE_FIXTURE(chain_tiers):
    """**THE W -> R SEAM IN ONE SPELLING, PINNED AGAINST THE PRODUCER'S OWN OBJECTS** (round-3 item 1).

    THE MEASUREMENT THAT MADE THIS NECESSARY (round-2 census, blocker 2): `render.chain_state_words`
    read `tail_peak_month` and `lag_window_end`; `render.chain_arithmetic_words` read
    `Chain.data_scope`; `render.sb_chain_count` read `chain_counts["cross_event"]`. The walk carries
    `tail_peak_date`, `tail_lag_to`, `Chain.scope` and `chain_counts["cross_market_event"]`. On the
    page, across all three tiers: "peaked" 0 times, against 6 of 6 rendered chains whose TAIL term was
    SCORED on a window peak -- including a hop printed at the 28th percentile and scored at the 94th.

    So the names live in ONE place and this test resolves EVERY one of them -- flat attributes, the
    three dicts a chain carries, and the count line's keys -- on the shipped types."""
    bd, ch, hop = _seam_targets(chain_tiers)
    assert W.CHAIN_SEAM_FIELDS == tuple(dict.fromkeys(W.CHAIN_SEAM_FIELDS)), "one spelling, once"
    counts = dict(bd.chain_counts or {})
    assert counts, "the fixture must have run the chain leg"
    missing = []
    for name in W.CHAIN_SEAM_FIELDS:
        parts = name.split(".")
        if parts[0] == "ChainHop":
            if not hasattr(hop, parts[1]):
                missing.append(name)
        elif parts[0] == "chain_counts":
            if parts[1] not in counts:
                missing.append(name)
        elif parts[0] == "Chain" and len(parts) == 2:
            if not hasattr(ch, parts[1]):
                missing.append(name)
        elif parts[0] == "Chain" and len(parts) == 3:
            holder = getattr(ch, parts[1], None)
            # `positioning` is EMPTY unless the clause fires; its keys have their own pin below.
            if parts[1] != "positioning" and parts[2] not in (holder or {}):
                missing.append(name)
        else:
            missing.append("UNPARSEABLE " + name)
    assert missing == [], missing
    # ...AND THE FOUR NAMES THE CENSUS CAUGHT ARE NOT THIS MODULE'S SPELLING, on the shipped type.
    for wrong in ("tail_peak_month", "lag_window_end", "tail_peak_value"):
        assert not hasattr(hop, wrong), wrong
    assert not hasattr(ch, "data_scope")
    assert "cross_event" not in counts and "cross_market_event" in counts
    # every seam name is reachable from `to_dict`'s payload too, for the keys the arm report reads
    row = ch.to_dict()
    for k in ("scope", "positioning", "slot", "receipts_aged_out", "full", "rendered"):
        assert k in row, k


def test_R3_the_POSITIONING_dict_carries_the_pages_own_three_keys_and_is_EMPTY_otherwise():
    """`Chain.positioning` (lane R's handoff W-R2): the fact the page's positioning row prints, under
    the PAIR the standing is cited at (E11 -- `cot_mm_positioning` is a row of every futures board this
    turn carries). It is EMPTY where the clause does not fire, so the row is absent rather than a zero
    wearing a claim."""
    bd = _cboard()
    r = _crow(bd, "a_cbot", "cot_mm_positioning", st=_cs("cot_mm_positioning", pct=99))
    r.silver_ref = "cot_mm_positioning"
    _crow(bd, "a_cbot", "top", st=_cs("top", pct=95))
    _crow(bd, "a_cbot", "bot", st=_cs("bot", pct=50))
    _cpath(bd, "a_cbot", ["top", "bot"])
    _cfinish(bd)
    af = W.anchor_facts(bd, "a_cbot")
    assert af.positioning_id == "cot_mm_positioning" and af.positioning_percentile == 99
    ch = W.chain_rows(bd, None, knobs=bd.knobs)["pool"][0]
    assert ch.direction in ("higher", "lower"), ch.direction
    assert set(ch.positioning) == {"percentile", "against", "key"}, ch.positioning
    assert ch.positioning["key"] == ("a_cbot", "cot_mm_positioning")
    assert ch.positioning["percentile"] == 99
    assert isinstance(ch.positioning["against"], bool)
    # a board with NO positioning row declares nothing at all -- never a zero
    bd2 = _cboard()
    _crow(bd2, "a_cbot", "top", st=_cs("t2", pct=95))
    _crow(bd2, "a_cbot", "bot", st=_cs("b2", pct=50))
    _cpath(bd2, "a_cbot", ["top", "bot"])
    _cfinish(bd2)
    assert W.chain_rows(bd2, None, knobs=bd2.knobs)["pool"][0].positioning == {}


def test_MA3_terms_scored_counts_a_term_ONLY_WHERE_IT_READ_SOMETHING(chain_tiers):
    """**REVIEW MA-3.** `Chain.scope['terms_scored']` counted every term scoring above zero, and TWO of
    the seven carry a NEUTRAL: HISTORY scores 7.5 exactly when there is NO record and LAG scores 1 when
    no horizon was asked. MEASURED on the deep fixture's first rendered chain before this landed:

        terms  {'tail': 23.9, 'reach': 25, 'event': 0, 'history': 7.5, 'asymmetry': 10.0,
                'confidence': 3.0, 'lag': 2}      history n_firings = 0, unmeasured = 14
        scope  terms_scored 6 of 7

    -- "six of seven terms scored" printed one line above "history thin: the next hop publishes no
    second reading inside the declared window, on any of the fourteen past firings". The instrument
    ruling 6(a) added so a low score would read as SCARCE DATA was counting the scarcity as a reading.
    SIX -> FIVE, and it is the same arithmetic read off facts already on the object."""
    bd = chain_tiers["deep"]
    thin = next(c for c in bd.chains
                if c.rendered and int((c.history or {}).get("n_firings") or 0) == 0)
    assert thin.terms["history"] == W.CHAIN_HISTORY_NEUTRAL and thin.receipt_kind == "none"
    assert thin.scope["terms_read"] == 5, (thin.scope, thin.terms)
    assert thin.scope["terms_total"] == 7
    # ...and `terms_scored` is what the PAGE prints beside it (round-4 ruling, R3-W1):
    # one word, one number, and the neutral is visible under its own name.
    assert thin.scope["terms_scored"] == 6, thin.scope
    # ...and a chain that DID read a record counts it. 09-24 FIX ROUND (CONTRACT K13, DECLARED): the
    # rendered chain that carried a record at HEAD was topped by La Nina on the fixture's WARM ONI (the
    # 81.7th percentile, above the convention's first band) -- a premise not in force, which now takes no
    # seat -- so the record-carrying chain is read off the POOL, best-ranked first.
    rich = next((c for c in sorted(bd.chains, key=lambda c: c.rank)
                 if int((c.history or {}).get("n_firings") or 0) > 0), None)
    assert rich is not None, "the deep board carries both cases"
    assert W._term_was_read("history", rich.terms, n_firings=int(rich.history["n_firings"]),
                            kind=rich.receipt_kind, horizon_months=3, band=None) is True
    assert rich.scope["terms_read"] == rich.scope["terms_scored"], rich.scope
    # **THE LA NINA CHAIN: ITS ASYMMETRY READ NOTHING AT ROUND 1 (W-7) AND ITS PREMISE IS NOW OFF (K13).**
    # HEAD scored ten ASYMMETRY points on "La Nina sits on a declared desk line" -- the El Nino band's own
    # label; round 1 read that on La Nina's own pole (nothing); round 2 reads the premise: the chain's
    # first link is the pole not in force, so it declares no direction and takes no seat.
    lanina_chains = [c for c in bd.chains if c.hops and c.hops[0].driver_id == "La_Nina"]
    assert lanina_chains, "the fixture carries La Nina-topped chains"
    for c in lanina_chains:
        top = c.hops[0]
        assert top.phase_reoriented and top.phase_in_force_driver == "El_Nino"
        assert c.premise_off is True and c.terms["asymmetry"] == 0.0, (c.hop_ids, c.terms)
        assert (c.direction, c.side) == ("unsettled", "unsettled") and not c.rendered, c.hop_ids
    # the rule at the unit, both neutrals and the EVENT word
    band = parse_lag("0-1 quarters")
    terms = {"tail": 20.0, "reach": 25, "event": 0, "history": W.CHAIN_HISTORY_NEUTRAL,
             "asymmetry": 0.0, "confidence": 3.0, "lag": 1}
    assert W._term_was_read("history", terms, n_firings=0, kind="none", horizon_months=3,
                            band=band) is False
    assert W._term_was_read("history", terms, n_firings=1, kind="none", horizon_months=3,
                            band=band) is True
    assert W._term_was_read("lag", terms, n_firings=0, kind="none", horizon_months=None,
                            band=band) is False
    assert W._term_was_read("lag", terms, n_firings=0, kind="none", horizon_months=3,
                            band=None) is False
    assert W._term_was_read("lag", terms, n_firings=0, kind="none", horizon_months=3,
                            band=band) is True
    assert W._term_was_read("event", terms, n_firings=0, kind="none", horizon_months=3,
                            band=band) is False
    assert W._term_was_read("event", terms, n_firings=0, kind="closed", horizon_months=3,
                            band=band) is True
    assert W._term_was_read("asymmetry", terms, n_firings=0, kind="none", horizon_months=3,
                            band=band) is False


def test_MA4_an_AGED_OUT_closed_receipt_is_COUNTED_and_never_silently_dropped():
    """**REVIEW MA-4.** M7's recency bound landed and its COUNTING did not: as-of 2026-09-07, a 0-1
    quarter hop carrying a dated action of 2024-01-01 read `receipt_kind "none"` / `receipt_words ""`
    / EVENT 0 of 20 with NOTHING recording that the document existed -- indistinguishable, on the trace
    and in the count line, from a chain that never had one. Fences CORRECT or COMPUTE, never delete,
    and that applies to a document the turn actually retrieved."""
    bd = _cboard()
    _crow(bd, "a_cbot", "top", st=_cs("top", pct=95), event="2024-01-01")
    _crow(bd, "a_cbot", "bot", st=_cs("bot", pct=50))
    _cpath(bd, "a_cbot", ["top", "bot"])
    _cfinish(bd)
    got = W.chain_rows(bd, None, knobs=bd.knobs)
    ch = got["pool"][0]
    assert ch.receipt_kind == "none" and ch.terms["event"] == 0, "the bound still holds"
    assert ch.receipts_aged_out == 1, "the estate HAD the document; the window had closed on it"
    assert got["counts"]["receipts_aged_out"] == 1, got["counts"]
    assert ch.to_dict()["receipts_aged_out"] == 1
    # and a receipt INSIDE one band-length is the chain's receipt and ages nothing out
    bd2 = _cboard()
    _crow(bd2, "a_cbot", "top", st=_cs("t2", pct=95), event="2026-08-01")
    _crow(bd2, "a_cbot", "bot", st=_cs("b2", pct=50))
    _cpath(bd2, "a_cbot", ["top", "bot"])
    _cfinish(bd2)
    got2 = W.chain_rows(bd2, None, knobs=bd2.knobs)
    assert got2["pool"][0].receipt_kind == "closed"
    assert got2["pool"][0].receipts_aged_out == 0
    assert got2["counts"]["receipts_aged_out"] == 0


def test_MA5_ONE_noun_for_past_firings_and_the_outcome_line_names_ITS_OWN_SUBSET(chain_tiers):
    """**REVIEW MA-5.** `chain_history_words` prints "in eleven of FOURTEEN past firings of this
    reading ..." and `chain_outcome_words` printed "after FIVE past firings of this reading the front
    price ..." -- one population, two counts, one noun, and nothing saying the five were a SUBSET of
    the fourteen. MEASURED on the deep fixture's rendered chain: history `n_firings` 14, outcome `n` 5.
    The page was saved there only because five sits under `stats.quantiles`' own floor.

    ONE COUNT WITH ITS EXPLAINED SUBSET: the record line keeps the firings, the outcome line names how
    many of THOSE the front price reaches, and `n_in` carries the denominator on the dict."""
    from leviathan.graphrag.state.render import words_for_int
    bd = chain_tiers["deep"]
    # 09-24 FIX ROUND (CONTRACT K13, DECLARED): the rendered chain that priced its record at HEAD was La
    # Nina-topped on a warm ONI and takes no seat now, so the outcome is read -- through the SAME producer
    # the rendered chains use -- for the best-ranked record-carrying chain of the pool.
    ch = next((c for c in sorted(bd.chains, key=lambda c: c.rank)
               if int((W._outcome_for(bd, c) or {}).get("n") or 0) > 0), None)
    assert ch is not None, "the deep fixture must price at least one chain's firings"
    o, h = W._outcome_for(bd, ch), ch.history
    n, n_in = int(o["n"]), int(o["n_in"])
    assert n <= n_in, (n, n_in)
    assert n_in == int(h["n_firings"]), "the denominator IS the record line's own count"
    assert words_for_int(n) in o["words"] and words_for_int(n_in) in o["words"]
    assert words_for_int(int(h["n_firings"])) in h["words"]
    # LANE R's HANDOFF W-R7: the "over" clause is said ONCE
    assert "over the declared window over" not in o["words"], o["words"]
    # the two window dates are FIELDS and no longer only prose (handoff W-R5)
    assert o["window_from"] and o["window_to"] and o["window_from"] <= o["window_to"]
    assert o["window_from"] in o["scope"] and o["window_to"] in o["scope"]


def test_CENSUS3_the_anchors_PRICE_ROW_scores_TAIL_on_the_TERMINAL_when_the_TAPE_IS_ATTACHED_FIRST(
        chain_tiers):
    """**THE ROUND-2 CENSUS'S BLOCKER 3, the producer half.** Owner ruling 2's price-row TAIL term was
    BUILT, PINNED and UNREACHABLE: `walk.anchor_facts` reads `bd.tape`, and the census measured
    `bd.tape` EMPTY at stage-2 time in its own harness AND in `seam.fill_stage2` (`:374` then `:380`),
    so `Chain.scope['price_read']` was False on all 3,308 chains of all three tiers while the same
    board's front price sat at the 83rd percentile of its own record.

    WITH THE TAPE ATTACHED BEFORE THE CHAIN COMPOSES -- which is the order this fixture drives and the
    order lane R moves `_attach_tape` to -- the term fires and stamps the fact."""
    for mode, bd in chain_tiers.items():
        af = W.anchor_facts(bd, "soybeans_cbot")
        assert round(float(af.price_percentile or 0.0), 2) == 83.28, (mode, af.price_percentile)
        assert round(af.price_tail, 4) == 0.6656, (mode, af.price_tail)
        priced = [c for c in bd.chains if (c.scope or {}).get("price_read")]
        assert priced, "%s: the anchor price must score TAIL on some terminal" % mode
        for c in priced:
            assert not c.cross, "the price is the terminal only where NO cross was earned"
            assert c.terms["tail"] == round(W.CHAIN_TERM_MAX["tail"] * af.price_tail, 1)
            assert c.scope["price_standing"] == "level and its own window percentile"
    # THE NEGATIVE, AND IT IS THE ORDERING HAZARD ITSELF: no tape, no reading, and the fact says so.
    bd2 = _cboard()
    _crow(bd2, "a_cbot", "top", st=_cs("top", pct=50))
    _crow(bd2, "a_cbot", "bot", st=_cs("bot", pct=50))
    _cpath(bd2, "a_cbot", ["top", "bot"])
    _cfinish(bd2)
    assert bd2.tape == {}
    ch2 = W.chain_rows(bd2, None, knobs=bd2.knobs)["pool"][0]
    assert ch2.scope["price_read"] is False and ch2.scope["price_standing"] == ""


# ── THE RENDER SLOTS (owner ruling 2026-09-22) ──────────────────────────────────────────────────────
def _slot_board(*, anchors, horizon=3, n=6):
    """A pool of `n` two-hop chains on one anchor, ranked by the receipt hop's own percentile."""
    bd = B.Board(asof="2026-09-07", mode="max", knobs=B.board_knobs_of("max"),
                 horizon_months=horizon, anchors=tuple(anchors))
    for i in range(n):
        _crow(bd, "a_cbot", "t%d" % i, st=_cs("t%d" % i, pct=90 - i))
        _crow(bd, "a_cbot", "b%d" % i, st=_cs("b%d" % i, pct=50))
        _cpath(bd, "a_cbot", ["t%d" % i, "b%d" % i])
    return bd


def test_SLOT_a_SUBJECT_chain_ranked_BELOW_the_top_K_takes_its_own_seat():
    """**OWNER RULING 2026-09-22, ratified.** After the top K and the sign swap, the QUESTION's own
    seats: a chain carrying the driver this turn is ANCHORED on renders, labelled, even where the rank
    left it under the cap. THE RANK IS NEVER MOVED -- the graph decides relevance and the question only
    anchors -- so the subject chain is APPENDED and the picked set stays in rank order."""
    sub = B.Anchor(contract="a_cbot", source="subject", driver_id="t5", subject=True)
    bd = _slot_board(anchors=(sub,))
    _cfinish(bd)
    got = W.chain_rows(bd, None, knobs=bd.knobs)
    rendered = got["rendered"]
    k = bd.knobs.chain_render_k
    assert len(rendered) == k + 1, [c.hop_ids for c in rendered]
    seat = next(c for c in rendered if c.slot == "subject")
    assert "t5" in seat.hop_ids, seat.hop_ids
    assert [c.rank for c in rendered] == sorted(c.rank for c in rendered), "the rank never moved"
    assert got["counts"]["slot_subject"] == 1 and got["counts"]["slot_top"] == k
    assert sum(1 for c in rendered if c.slot == "top") == k


def test_SLOT_a_COINCIDING_chain_adds_NO_ROW():
    """A slot RESERVES a seat; it does not duplicate one. Where the top K already carries a chain that
    satisfies the slot, the slot adds nothing at all -- so the page never grows for a fact it already
    printed."""
    sub = B.Anchor(contract="a_cbot", source="subject", driver_id="t0", subject=True)
    bd = _slot_board(anchors=(sub,))
    _cfinish(bd)
    got = W.chain_rows(bd, None, knobs=bd.knobs)
    assert len(got["rendered"]) == bd.knobs.chain_render_k
    assert got["counts"]["slot_subject"] == 0
    assert any("t0" in c.hop_ids for c in got["rendered"])


def test_SLOT_with_NO_subject_ONE_named_market_and_NO_horizon_the_set_is_the_PRE_SLOT_SET():
    """THE NEGATIVE HALF, and it is the one that protects every turn the ruling did not aim at: a board
    the question anchors nothing on renders EXACTLY the top K by rank, every seat labelled `top` or
    `sign`, byte for byte what the selection chose before the slots existed."""
    bd = _slot_board(anchors=(B.Anchor(contract="a_cbot", source="named", named=True),),
                     horizon=None)
    _cfinish(bd)
    got = W.chain_rows(bd, None, knobs=bd.knobs)
    pre = W.chain_render_set(list(got["pool"]), k=bd.knobs.chain_render_k,
                             print_line=float(bd.knobs.chain_print_line))
    assert [c.hop_ids for c in got["rendered"]] == [c.hop_ids for c in pre["rendered"]]
    assert all(c.slot in ("top", "sign") for c in got["rendered"])
    for key in ("slot_subject", "slot_pair", "slot_horizon", "rendered_one_line"):
        assert got["counts"][key] == 0, (key, got["counts"])


def _slot_chain(i, score, hop_ids, terminal, *, band="0-1 quarters", contract="a_cbot"):
    """ONE hand-made chain with a declared score, so the slot rules are read at the unit and the
    board's own ranker is not the thing under test."""
    hops = tuple(W.ChainHop(contract=contract, driver_id=h, seat=j + i * 10,
                            lag_band=parse_lag(band), series_key="s_%s_%d" % (h, i))
                 for j, h in enumerate(hop_ids))
    ch = W.Chain(contract=contract, hops=hops, depth=len(hops) - 1, terminal=terminal)
    ch.score = score
    return ch


def test_SLOT_the_K_PLUS_TWO_FULL_BOUND_HOLDS_WITH_ALL_THREE_SLOTS_LIVE():
    """THE BOUND: at most `K + 2` chains render IN FULL, and a slot chain past it renders as ONE LINE
    -- never dropped, and COUNTED. Three slots can seat three extra chains and the block's own budget
    cannot absorb three extra full chain rows.

    AND THE SAME POOL AT A WIDER K SHOWS THE OTHER HALF: where the top K already carries the subject,
    that slot adds no row at all, and nothing is reduced because nothing is past the bound."""
    pool = [_slot_chain(0, 90.0, ("t0", "b0"), "a_cbot"),
            _slot_chain(1, 80.0, ("t1", "b1"), "a_cbot"),
            _slot_chain(2, 70.0, ("sub", "b2"), "a_cbot"),                   # the SUBJECT
            _slot_chain(3, 60.0, ("t3", "b3"), "z_cbot"),                    # the PAIR call
            _slot_chain(4, 50.0, ("t4", "b4"), "a_cbot", band="2-4 quarters")]  # the HORIZON
    kw = {"subject_ids": {"a_cbot": frozenset({"sub"})},
          "named_contracts": ("a_cbot", "z_cbot"), "horizon_months": 9}
    got = W.chain_render_set(pool, k=1, print_line=40.0, **kw)
    rendered = got["rendered"]
    assert [(c.slot, c.full) for c in rendered] == [("top", True), ("subject", True),
                                                    ("pair", True), ("horizon", False)], \
        [(c.hop_ids, c.slot, c.full) for c in rendered]
    assert len([c for c in rendered if c.full]) == 1 + W.CHAIN_SLOT_FULL_OVER_K
    assert got["counts"]["rendered_one_line"] == 1
    assert got["counts"]["rendered"] == 4, "the chain past the bound is REDUCED, never dropped"
    assert all(c.rendered for c in rendered)
    assert sum(got["counts"]["slot_" + w] for w in W.CHAIN_SLOTS) == len(rendered)
    # THE RANK IS NEVER MOVED BY A SLOT
    assert [c.score for c in rendered] == sorted((c.score for c in rendered), reverse=True)
    # ...and at K=3 the subject is already carried, so that slot adds NOTHING
    wide = W.chain_render_set(pool, k=3, print_line=40.0, **kw)
    assert [(c.slot, c.full) for c in wide["rendered"]] == [
        ("top", True), ("top", True), ("top", True), ("pair", True), ("horizon", True)]
    assert wide["counts"]["slot_subject"] == 0 and wide["counts"]["rendered_one_line"] == 0


def test_SLOT_the_ROUTING_FIELDS_SELECT_NOTHING():
    """"The graph decides relevance, the question only anchors." A slot is anchored by the SUBJECT, the
    NAMED markets and the HORIZON -- facts about the question -- and never by how the turn was routed.
    This is the negative pin the ruling asks for, read off the selection's own source."""
    import ast
    import inspect
    import textwrap
    code: list = []
    for fn in (W.chain_render_set, W._slot_subject, W._slot_pair, W._slot_horizon, W.chain_counts):
        tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
        # THE DOCSTRINGS ARE STRIPPED AND THE COMMENTS NEVER PARSE: this pin grades what the selection
        # READS, not what its prose NAMES -- the docstring above names these five fields precisely in
        # order to say that none of them selects anything.
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Module, ast.ClassDef)):
                if node.body and isinstance(node.body[0], ast.Expr) \
                        and isinstance(node.body[0].value, ast.Constant) \
                        and isinstance(node.body[0].value.value, str):
                    node.body = node.body[1:] or [ast.Pass()]
        ast.fix_missing_locations(tree)
        code.append(ast.unparse(tree))
    src = "\n".join(code)
    for routing in ("steps", "fallback", "subject_hints_n", "degraded", "planner_mode", "mode"):
        assert routing not in src, routing
    assert set(W.CHAIN_SLOTS) == {"top", "sign", "subject", "pair", "horizon"}


# -- ROUND 4: the closing round's own pins ----------------------------------------------------------
def _keyed_chain(score, drivers, keys, terminal, *, band="0-1 quarters", contract="a_cbot"):
    """ONE hand-made chain with its FOLD KEYS declared, so a slot candidate can be a FOLD DUPLICATE of
    a top-K pick -- the shape that makes clause (5) seat a chain the diversity fold refused."""
    hops = tuple(W.ChainHop(contract=contract, driver_id=d, seat=j, lag_band=parse_lag(band),
                            series_key=k)
                 for j, (d, k) in enumerate(zip(drivers, keys)))
    ch = W.Chain(contract=contract, hops=hops, depth=len(hops) - 1, terminal=terminal)
    ch.score = score
    return ch


def _demote_pool():
    """THE REVIEWER'S OWN POOL (round-3 review MA-R3-1, reproduced by the census at 8b.1): k=3, print
    line 40.0, a top K of 99 / 70 / 40 and three FOLD-DUPLICATE slot chains at 98 / 97 / 96.

    All three duplicates carry the TOP chain's own two fold keys, so `_fits` refuses every one of them
    and the top K is 99 / 70 / 40 by rank -- and each one then answers a slot the top K does not: the
    SUBJECT driver, a terminal in the second named market, a band containing the horizon."""
    return [_keyed_chain(99.0, ("t1", "r1"), ("s1", "s1r"), "a_cbot"),
            _keyed_chain(70.0, ("t2", "r2"), ("s2", "s2r"), "a_cbot"),
            _keyed_chain(40.0, ("t3", "r3"), ("s3", "s3r"), "a_cbot"),
            # the three slot candidates, each carrying the TOP chain's own two fold keys
            _keyed_chain(98.0, ("sub", "r1"), ("s1", "s1r"), "a_cbot"),
            _keyed_chain(97.0, ("t1", "pair"), ("s1", "s1r"), "z_cbot"),
            _keyed_chain(96.0, ("t1", "hzn"), ("s1", "s1r"), "a_cbot", band="2-4 quarters")]


def test_MA_R3_1_the_FULL_bound_is_stamped_in_SEAT_order_so_a_TOP_K_chain_is_NEVER_reduced():
    """**ROUND-3 REVIEW MA-R3-1, ORCHESTRATOR RULING 2026-09-22.** The bound belongs to the order the
    SEATS were taken -- the top K, then the sign swap, then the slots -- and the sort is for DISPLAY.

    MEASURED BEFORE, on this pool: the chains rendered 99 / 98 / 97 / 96 / 70 / 40 and `c.full = i <
    k + 2` on the POST-SORT position reduced the SIXTH -- the 40.0 chain, a TOP-K pick -- so the page
    printed "CHAIN sixth of six, under this page's own selection line: t3, then r3, reaching a cbot"
    while `below_print_line` said ZERO chains sat below a line that chain scored exactly (round 5 renamed
    that seat's sentence to "carried in one line, past the page's full-render bound"). One field,
    two readings, and the count line reading the wrong one: MA-1's own class, one round after it
    closed, and against both ruling 6(a) ("the top K render in full ALWAYS") and this function's own
    docstring. The chains that can outrank a top-K pick are exactly the slot candidates, because
    clause (5) bypasses the diversity fold as a veto.

    AFTER: the reduced chain is the LAST-SEATED slot chain (the horizon seat, taken sixth of six), the
    40.0 top-K chain renders IN FULL, and the count line agrees with the page word for word."""
    from leviathan.graphrag.state import render as R
    pool = _demote_pool()
    got = W.chain_render_set(pool, k=3, print_line=40.0,
                             subject_ids={"a_cbot": frozenset({"sub"})},
                             named_contracts=("a_cbot", "z_cbot"), horizon_months=9)
    rendered = got["rendered"]
    assert [(c.score, c.slot, c.full) for c in rendered] == [
        (99.0, "top", True), (98.0, "subject", True), (97.0, "pair", True),
        (96.0, "horizon", False), (70.0, "top", True), (40.0, "top", True)], \
        [(c.score, c.slot, c.full, c.hop_ids) for c in rendered]
    assert all(c.full for c in rendered if c.slot == "top"), "ruling 6(a): the top K render in FULL"
    assert len([c for c in rendered if c.full]) == 3 + W.CHAIN_SLOT_FULL_OVER_K
    assert got["counts"]["rendered_one_line"] == 1
    assert got["counts"]["below_print_line"] == 0, "nothing in this pool is below the line"
    # THE WORDS ON THE PAGE. `render.render_board` switches on `Chain.full` and nothing else (the
    # `if not _c.full:` branch that calls `sb_chain_one_line`), so this is the row a reader meets.
    n = len(rendered)
    rows = [(R.sb_chain_head(c, i=i, n=n) if c.full else R.sb_chain_one_line(c, i=i, n=n))
            for i, c in enumerate(rendered, start=1)]
    reduced = [(c, row) for c, row in zip(rendered, rows) if "it is here for" in row]
    assert len(reduced) == 1, rows
    assert reduced[0][0].slot == "horizon" and "hzn" in reduced[0][1], reduced
    forty = next(row for c, row in zip(rendered, rows) if c.score == 40.0)
    assert "t3" in forty and "it is here for" not in forty and "selection line" not in forty, forty


def test_MINOR2_a_render_cap_of_ZERO_renders_NOTHING_the_slots_INCLUDED():
    """**ROUND-3 REVIEW, MINOR 2.** `chain_rows` reads `int(getattr(knobs, "chain_render_k", 0) or 0)`,
    so a knobs object WITHOUT the column arrives at k=0 -- and clause (5) still seated three chains,
    TWO of them in full, because the bound is `0 + 2`. MEASURED before: the five-chain pool with all
    three slots live rendered THREE at k=0 (subject, pair, horizon). A slot is a seat BESIDE the top K
    and never instead of it, so a page that asked for no chains gets none -- and every chain still
    carries a declared decline word, because nothing is dropped without a reason."""
    pool = [_slot_chain(0, 90.0, ("t0", "b0"), "a_cbot"),
            _slot_chain(1, 80.0, ("t1", "b1"), "a_cbot"),
            _slot_chain(2, 70.0, ("sub", "b2"), "a_cbot"),
            _slot_chain(3, 60.0, ("t3", "b3"), "z_cbot"),
            _slot_chain(4, 50.0, ("t4", "b4"), "a_cbot", band="2-4 quarters")]
    kw = {"subject_ids": {"a_cbot": frozenset({"sub"})},
          "named_contracts": ("a_cbot", "z_cbot"), "horizon_months": 9}
    got = W.chain_render_set(pool, k=0, print_line=40.0, **kw)
    assert got["rendered"] == []
    assert got["counts"]["rendered"] == 0 and got["counts"]["rendered_one_line"] == 0
    assert all(not c.rendered and not c.full and c.slot == "" for c in pool)
    assert all(c.decline for c in pool), [c.decline for c in pool]
    for word in W.CHAIN_SLOTS:
        assert got["counts"]["slot_" + word] == 0, word
    # ...and the same pool at k=1 still renders, so the guard is a CAP and not a new fence
    assert len(W.chain_render_set(pool, k=1, print_line=40.0, **kw)["rendered"]) == 4


def test_MA_R3_2_receipts_aged_out_is_ONE_population_DOCUMENTS_wherever_the_name_appears():
    """**ROUND-3 REVIEW MA-R3-2, ORCHESTRATOR RULING 2026-09-22.** `Chain.receipts_aged_out` counts
    the aged-out DOCUMENTS on one chain; `chain_counts["receipts_aged_out"]` counted the CHAINS that
    had at least one. MEASURED through the shipped producer on a board with TWO aged hops: the chain
    said 2 and the count line said 1, under ONE name, and both reach `Board.trace()`, the census
    record and the arm's report. It is the law MA-5 closed for the firings noun -- one series, counted
    ONCE, in ONE spelling -- so the count line SUMS the documents."""
    bd = _cboard()
    _crow(bd, "a_cbot", "h0", st=_cs("h0", pct=95), event="2024-01-01")
    _crow(bd, "a_cbot", "h1", st=_cs("h1", pct=94), event="2023-05-05")
    _crow(bd, "a_cbot", "bot", st=_cs("bot", pct=50))
    _cpath(bd, "a_cbot", ["h0", "h1", "bot"])
    _cfinish(bd)
    got = W.chain_rows(bd, None, knobs=bd.knobs)
    ch = got["pool"][0]
    assert ch.receipt_kind == "none" and ch.terms["event"] == 0, "the recency bound still holds"
    assert ch.receipts_aged_out == 2, "TWO documents the window had closed on"
    assert got["counts"]["receipts_aged_out"] == 2, got["counts"]
    assert got["counts"]["receipts_aged_out"] == sum(int(c.receipts_aged_out or 0)
                                                     for c in got["pool"])
    assert ch.to_dict()["receipts_aged_out"] == 2
    assert "chain_counts.receipts_aged_out" in W.CHAIN_SEAM_FIELDS


def test_R3W1_the_scope_count_IS_the_number_the_page_prints_and_the_READ_count_has_its_OWN_name(
        chain_tiers):
    """**LANE R's HANDOFF R3-W1, ORCHESTRATOR RULING 2026-09-22.** `render.chain_arithmetic_words`
    counts the PAIRS it enumerates -- every term with points above zero -- and `Chain.scope` published
    `_term_was_read`'s SEMANTIC count under the same word, so the sentence "six of seven terms scored"
    and the trace's own number were two claims about one chain. MEASURED before, over the six rendered
    chains of the three fixture tiers: FIVE disagreed, always LOW (5 against 6, 5 against 6, 5 against
    6, 5 against 6, 4 against 5), and the arm report and the judge read the one the reader never saw.

    ONE NAME, ONE NUMBER: `terms_scored` is computed by the page's own rule, after every term
    including HISTORY is set. MA-3's fact is NOT deleted -- it is published as `terms_read`, which is
    what a low score reading as SCARCE DATA actually needs (ruling 6a), and the thin chains keep it."""
    from leviathan.graphrag.state.render import chain_arithmetic_words, words_for_int
    bad, seen = [], 0
    for mode in ("quick", "deep", "max"):
        for ch in chain_tiers[mode].chains:
            if not ch.rendered:
                continue
            seen += 1
            printed = sum(1 for t in W.CHAIN_TERMS if W._term_points(ch.terms, t) > 0.0)
            if int(ch.scope["terms_scored"]) != printed:
                bad.append((mode, ch.hop_ids, ch.scope["terms_scored"], printed))
            # the SENTENCE the reader meets carries that same count in the estate's own cardinals
            assert ("%s of seven terms scored" % words_for_int(printed)) in chain_arithmetic_words(ch)
    assert seen >= 6 and bad == [], bad
    # ...and the READ count survives under its own name, one short exactly where a NEUTRAL is scored
    thin = next(c for c in chain_tiers["deep"].chains
                if c.rendered and int((c.history or {}).get("n_firings") or 0) == 0)
    assert thin.terms["history"] == W.CHAIN_HISTORY_NEUTRAL
    assert thin.scope["terms_read"] == 5 and thin.scope["terms_scored"] == 6, thin.scope
    # a chain carrying no NEUTRAL reads exactly what it scores. 09-24 FIX ROUND (CONTRACT K13, DECLARED):
    # HEAD's rendered record-carrying chain was La Nina-topped on a warm ONI -- a premise not in force,
    # no seat -- so the chain is read off the POOL, best-ranked first (the MA-3 pin carries the rest).
    rich = next(c for c in sorted(chain_tiers["deep"].chains, key=lambda c: c.rank)
                if int((c.history or {}).get("n_firings") or 0) > 0)
    assert rich.scope["terms_read"] == rich.scope["terms_scored"], rich.scope
    for name in ("Chain.scope.terms_scored", "Chain.scope.terms_read"):
        assert name in W.CHAIN_SEAM_FIELDS, name


def test_CENSUS7_a_firing_the_PARSE_cannot_read_is_COUNTED_and_never_silently_dropped(monkeypatch):
    """**ROUND-2 CENSUS BLOCKER 7, CARRIED.** `chain_history`'s parent-move parse answered a
    TypeError / ValueError / IndexError with a bare `continue`, so the firing left BOTH counters and
    the denominator a reader meets ("on any of the fourteen past firings of this reading") was smaller
    than the record the arrays held. The two window drops beside it already counted; a fence CORRECTS
    or COMPUTES, and a dropped item is COUNTED.

    THE BRANCH IS NOT REACHABLE THROUGH `hop_arrays` ON THE SERVED PATH and this pin says so out loud:
    `transforms.num_or_none` makes every array numeric by construction, which is why the branch went
    four rounds uncounted. So the pin hands the SHIPPED producer an array the cleaner would have
    dropped -- seven cells that all COMPARE (they are strings, so `chain_firings` finds its runs) of
    which one does not PARSE -- and asserts on the real ledger it returns: every firing
    `chain_firings` found is in `n_firings` or in `unmeasured`, and neither is a stand-in."""
    vals = ("5", "4", "zz", "2", "1", "3", "6")                      # the run into "zz" FIRES
    dates = ("2015-01-01", "2015-02-01", "2015-03-01", "2015-04-01", "2015-05-01",
             "2015-06-01", "2015-07-01")
    child = (1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0)
    a, b = _cs("A", pct=90), _cs("B", pct=50)
    a.metric, b.metric = "A", "B"
    monkeypatch.setattr(W, "hop_arrays", lambda st: (
        ((), (), "") if st is None else
        ((vals, dates, "t") if getattr(st, "metric", "") == "A" else (child, dates, "t"))))
    band = parse_lag("0-1 quarters")
    h = W.chain_history(a, b, edge_sign="+", band=band, asof="2026-09-07", direction=1)
    fired = W.chain_firings(vals, dates, direction=1,
                            min_separation=W.separation_periods(band.months()[1], a, dates),
                            asof="2026-09-07", close_months=band.months()[1])
    assert len(fired) == 2, fired
    assert int(h["n_firings"]) == 1 and int(h["unmeasured"]) == 1, h
    assert int(h["n_firings"]) + int(h["unmeasured"]) == len(fired), h
    assert "Chain.history.unmeasured" in W.CHAIN_SEAM_FIELDS


def test_CENSUS7_every_firing_on_a_REAL_board_lands_in_exactly_one_counter(chain_tiers):
    """The same ledger on the three fixture tiers, through the boards the seam actually drives: the
    three VERDICTS sum to `n_firings` on every chain that carries a record (3,308 of them), so a
    firing is aligned, at odds, undetermined or UNMEASURED and never nothing at all."""
    bad, seen = [], 0
    for mode in ("quick", "deep", "max"):
        for c in chain_tiers[mode].chains:
            h = c.history or {}
            if not h:
                continue
            seen += 1
            got = (int(h.get("aligned") or 0) + int(h.get("at_odds") or 0)
                   + int(h.get("undetermined") or 0))
            if got != int(h.get("n_firings") or 0):
                bad.append((mode, c.hop_ids, got, h.get("n_firings")))
    assert seen > 100 and bad == [], bad[:3]


def test_CENSUS7_a_SINGLE_HOP_path_is_COUNTED_in_the_count_line_and_never_silently_skipped():
    """**ROUND-2 CENSUS BLOCKER 7, CARRIED.** A path of ONE hop is not a chain and never becomes one
    -- `chain_rows` skips it, correctly -- but it was on the board and the skip recorded nothing, so
    the count line's own `total` (the POOL) could not be reconciled with the paths the walk carried.
    It rides the count line under its own name, beside `cross_unpriced`: the two facts the BUILDER
    knows and the selection cannot."""
    bd = _cboard()
    _crow(bd, "a_cbot", "solo", st=_cs("solo", pct=95))
    _crow(bd, "a_cbot", "top", st=_cs("top", pct=90))
    _crow(bd, "a_cbot", "bot", st=_cs("bot", pct=50))
    _cpath(bd, "a_cbot", ["solo"])
    _cpath(bd, "a_cbot", ["top", "bot"])
    _cfinish(bd)
    got = W.chain_rows(bd, None, knobs=bd.knobs)
    assert len(bd.paths) == 2 and got["counts"]["total"] == 1
    assert got["counts"]["single_hop_paths"] == 1, got["counts"]
    assert "chain_counts.single_hop_paths" in W.CHAIN_SEAM_FIELDS


def test_SEAM_every_key_the_count_dict_carries_at_RUNTIME_has_a_DECLARED_spelling(chain_tiers):
    """**ROUND-3 CENSUS, SECTION 9.** Three keys existed on the served dict with no published
    spelling: `cross_unpriced` and `single_hop_paths`, stamped by the BUILDER after the selection
    returns, and `disagreement`, stamped by `stage2` -- and all three reach `Board.trace()` and the
    census record, because `chain_counts` is dumped wholesale. A key with no declared name is how
    `counts["cross_event"]` rendered silence for a whole round. The roster is the seam in ONE
    spelling, so it is graded in BOTH directions here: nothing runtime that is undeclared, and
    nothing declared that the real dict does not carry."""
    counts = dict(chain_tiers["deep"].chain_counts or {})
    declared = {n.split(".", 1)[1] for n in W.CHAIN_SEAM_FIELDS if n.startswith("chain_counts.")}
    assert counts, "the fixture must have run the chain leg"
    assert sorted(set(counts) - declared) == [], sorted(set(counts) - declared)
    assert sorted(declared - set(counts)) == [], sorted(declared - set(counts))
    for name in ("chain_counts.cross_unpriced", "chain_counts.single_hop_paths",
                 "chain_counts.disagreement"):
        assert name in W.CHAIN_SEAM_FIELDS, name
    assert W.CHAIN_SEAM_FIELDS == tuple(dict.fromkeys(W.CHAIN_SEAM_FIELDS)), "one spelling, once"


# ── ROUND 5: the aged document, its hop, its label and the record line's own denominator ────────────
def test_C3_the_count_line_counts_DISTINCT_DOCUMENTS_over_the_pool_and_never_chains_x_documents():
    """**ROUND-4 CENSUS BLOCKER 3.** `ChainHop` is memoised per `(contract, driver_id)`, so ONE dated
    action on ONE row rides EVERY pool chain that walks that row -- and the count line summed the
    PER-CHAIN field over the pool. MEASURED with EXACTLY ONE dated action in the whole estate, the
    page printed "fifty-five / two hundred twenty / two hundred sixty-four dated actions aged out of
    their windows" at quick / deep / max. Chains times documents is not a document count, and the
    noun the page prints it under says documents.

    THE KEY IS THE DOCUMENT'S OWN ADDRESS -- `(contract, driver_id, event_date)`, E11's PAIR and never
    the bare id, because one driver id is a row of many markets. `Chain.receipts_aged_out` STAYS the
    per-chain count: two arithmetics over ONE population, each under its own owner's name, and
    `CHAIN_SEAM_FIELDS` says which name carries which."""
    bd = _cboard()
    _crow(bd, "a_cbot", "doc", st=_cs("doc", pct=95), event="2019-01-01")
    for b in ("b1", "b2", "b3"):
        _crow(bd, "a_cbot", b, st=_cs(b, pct=50))
        _cpath(bd, "a_cbot", ["doc", b])
    _cfinish(bd)
    got = W.chain_rows(bd, None, knobs=bd.knobs)
    pool = got["pool"]
    assert len(pool) == 3, "three chains walk the ONE row the document sits on"
    assert [c.receipts_aged_out for c in pool] == [1, 1, 1], "each chain HAD the one document"
    assert sum(int(c.receipts_aged_out or 0) for c in pool) == 3, "round 4's own arithmetic"
    assert got["counts"]["receipts_aged_out"] == 1, got["counts"]
    assert W._aged_receipt_keys(pool[0]) == {("a_cbot", "doc", "2019-01-01")}
    assert len({k for c in pool for k in W._aged_receipt_keys(c)}) == 1
    # ...and TWO aged rows on ONE chain are still TWO documents (MA-R3-2, unmoved)
    bd2 = _cboard()
    _crow(bd2, "a_cbot", "h0", st=_cs("h0", pct=95), event="2024-01-01")
    _crow(bd2, "a_cbot", "h1", st=_cs("h1", pct=94), event="2023-05-05")
    _crow(bd2, "a_cbot", "bot", st=_cs("bot", pct=50))
    _cpath(bd2, "a_cbot", ["h0", "h1", "bot"])
    _cfinish(bd2)
    got2 = W.chain_rows(bd2, None, knobs=bd2.knobs)
    assert got2["pool"][0].receipts_aged_out == 2
    assert got2["counts"]["receipts_aged_out"] == 2, got2["counts"]


def test_C4_C5_the_AGED_document_names_ITS_OWN_HOP_and_never_returns_under_the_MECHANISM_label():
    """**ROUND-4 CENSUS BLOCKERS 4 AND 5, the producer half.**

    (4) THE AGED DATE IS A `max` OVER WHICHEVER HOPS AGED OUT, and the only hop a consumer could name
    beside it was the chain's RECEIPT hop -- so a page whose document sits on `La_Nina` printed "at
    cot mm positioning, a dated action on 2019-01-01, aged out of the window declared for it": a dated
    fact under a relation the producer never declared it against, which is round-3 MAJOR 1's own
    class. The producer knows which hop it was; now it says so, beside the date.

    (5) A DATED ACTION USUALLY CARRIES A PUBLICATION DATE TOO, so the document choice (2) had just
    aged out came straight back as choice (3) and scored SIX of twenty: one page read "reach
    twenty-five, ACTION SIX, record six and a half" beside its OWN document row saying that document
    aged out, with `receipt_kind = mechanism` on the same chain. Two producers, one document, one
    page. Choice (3) now reads the SAME bound choice (2) does, on the candidate's own date."""
    from leviathan.graphrag.state.render import CHAIN_RECEIPT_AGED
    bd = _cboard(asof="2026-09-07")
    # the document sits on the QUIETER hop, so the chain's receipt hop is a DIFFERENT row -- the
    # census's own shape (the action on `La_Nina`, the receipt hop `cot_mm_positioning`)
    _crow(bd, "a_cbot", "doc_row", st=_cs("doc_row", pct=60), event="2019-01-01",
          receipts=[{"date": "2019-01-05", "source": "s", "text": "an action, reported"}])
    _crow(bd, "a_cbot", "loudest", st=_cs("loudest", pct=99))
    _cpath(bd, "a_cbot", ["doc_row", "loudest"])
    _cfinish(bd)
    ch = W.chain_rows(bd, None, knobs=bd.knobs)["pool"][0]
    # (5) THE MECHANISM LABEL NO LONGER BUYS THE AGED DOCUMENT SIX POINTS -- and the candidate that
    # bought them is still on the hop, so this is a REFUSAL and not an absence
    assert (ch.receipt_kind, ch.terms["event"]) == ("none", 0), ch.receipt_words
    assert any(str(r.get("date") or "")[:10] == "2019-01-05"
               for r in (ch.aged_receipt_hop.receipts_top or ())), "the candidate is still there"
    assert ch.receipts_aged_out == 1
    # ...and the WORDS state the aged action instead of the empty string a reader met as "this turn
    # retrieved nothing", in the render's own ONE spelling of that sentence
    assert ch.receipt_words == CHAIN_RECEIPT_AGED % "2019-01-01", ch.receipt_words
    # (4) THE HOP THE DOCUMENT SITS ON, BESIDE ITS DATE -- and it is NOT the chain's receipt hop
    assert ch.receipt_hop is not None and ch.receipt_hop.driver_id == "loudest"
    assert ch.aged_receipt_hop is not None and ch.aged_receipt_hop.driver_id == "doc_row"
    assert ch.aged_receipt_hop is not ch.receipt_hop, "the row the round-4 page named"
    assert ch.aged_receipt_date == "2019-01-01"
    row = ch.to_dict()
    assert row["aged_receipt_hop"] == "doc_row" and row["aged_receipt_date"] == "2019-01-01"
    for name in ("Chain.aged_receipt_hop", "Chain.aged_receipt_date"):
        assert name in W.CHAIN_SEAM_FIELDS, name
    # a chain with NOTHING aged carries neither name's claim, and the ladder above it is untouched
    bd2 = _cboard(asof="2026-09-07")
    _crow(bd2, "a_cbot", "t", st=_cs("t", pct=95), event="2026-08-01")
    _crow(bd2, "a_cbot", "b", st=_cs("b", pct=50))
    _cpath(bd2, "a_cbot", ["t", "b"])
    _cfinish(bd2)
    fine = W.chain_rows(bd2, None, knobs=bd2.knobs)["pool"][0]
    assert (fine.receipt_kind, fine.terms["event"]) == ("closed", 12)
    assert fine.receipts_aged_out == 0
    assert fine.aged_receipt_hop is None and fine.aged_receipt_date == ""


def test_C8_the_record_line_names_ONE_population_and_the_reader_meets_the_TRACE_ROWS_numbers():
    """**ROUND-4 CENSUS BLOCKER 8 / this lane's own MA-R4-1.** Both branches of
    `chain_history_words` spelled the denominator "past firings of this reading" and meant two
    different counts: the thin branch's is `unmeasured` (every firing the producer found) and the
    n>0 branch's was `n_firings` -- THE MEASURED SUBSET ALONE. MEASURED through the shipped producer,
    `China_import_tariff -> export_pace_lag` carries `n_firings` 5 and `unmeasured` 9, so the producer
    found FOURTEEN firings and the line read "in one of FIVE past firings of this reading ..." while
    the chain's own trace row carried 5 and 9. A printed figure its own trace contradicts is a backing
    failure, and it is the law MA-5 closed for this very noun one round ago."""
    from leviathan.graphrag.state import render as R
    h = {"n_firings": 5, "aligned": 1, "unmeasured": 9}
    line = W.chain_history_words(h)
    # 09-24 FIX ROUND (item 28c, DECLARED): the trace twin of the page's record line, in the desk's
    # words -- one population ("the past times this reading sat this far out"), its two numbers (the
    # MEASURED five and the nine with no reading of the next link inside the lag) -- never "firings".
    assert "of the past times this reading sat this far out, five had a reading of" in line, line
    assert "moved the way the model expects in one" in line, line
    assert "nine more times no reading of the next link was published" in line, line
    assert R.words_for_int(5) in line and R.words_for_int(9) in line, line
    assert "firing" not in line, line
    # AND ON THE PAGE, through the row producer that prints it. THE PAGE'S WORDS ARE LANE R's (the
    # 09-23 fix round: `render.chain_record_words`, the history line's page twin in desk English); what
    # this lane owns there is the POPULATION -- the reader meets the trace row's own two numbers.
    ch = W.Chain(contract="a_cbot", hops=(W.ChainHop(contract="a_cbot", driver_id="d"),))
    ch.history = dict(h)
    row = R.sb_chain_record(ch)
    assert R.words_for_int(5) in row and R.words_for_int(9) in row, row
    # the THIN branch's own denominator is untouched -- it always named every time found
    assert "sat this far out fourteen times before" in W.chain_history_words(
        {"n_firings": 0, "aligned": 0, "unmeasured": 14})
    # ...and a record with nothing unmeasured says nothing about it
    clean = W.chain_history_words({"n_firings": 14, "aligned": 11, "unmeasured": 0})
    assert "fourteen had a reading of the next link to measure" in clean, clean
    assert "was published inside the lag" not in clean, clean
    # ...and NAMED, the reading and its next link are the chain's own (K11's trace twin)
    named = W.chain_history_words(h, reading="Brent crude oil", next="the board crush margin")
    assert named.startswith("of the past times Brent crude oil sat this far out, five had a reading of "
                            "the board crush margin to measure"), named


def test_R5_a_REPORT_SENTENCE_the_mechanism_bound_refuses_is_RECORDED_and_COUNTED_under_its_own_noun():
    """**ROUND-5 CENSUS BLOCKERS 1 AND 4.** Choice (3) refuses a report sentence outside the hop's declared
    window (EVENT 0) -- and before this it recorded NOTHING, so the render could print the sentence as the
    chain's receipt and the count line could not say how often the bound fired. The refused date and its
    hop ride ``Chain.mechanism_refused_date`` / ``_hop``, the trace row, and ``chain_counts.mechanism_refused``
    -- their OWN key and noun, never folded into ``receipts_aged_out`` (dated ACTIONS)."""
    bd = _cboard()
    _crow(bd, "a_cbot", "top", st=_cs("top", pct=95),
          receipts=[{"date": "2019-01-05", "source": "src", "tier": 2,
                     "text": "the cold phase tightened the planting window that season"}])
    _crow(bd, "a_cbot", "bot", st=_cs("bot", pct=50))
    _cpath(bd, "a_cbot", ["top", "bot"])
    _cfinish(bd)
    got = W.chain_rows(bd, None, knobs=bd.knobs)
    ch = got["pool"][0]
    assert ch.receipt_kind == "none" and ch.terms["event"] == 0, "the bound holds"
    assert ch.mechanism_refused_date == "2019-01-05", ch.mechanism_refused_date
    assert ch.mechanism_refused_hop is not None and ch.mechanism_refused_hop.driver_id == "top"
    from leviathan.graphrag.state import render as R
    # THE SENTENCE IS THE RENDER'S OWN SPELLING (`CHAIN_RECEIPT_REPORT_OUTSIDE`, lane R's words), read by
    # the walk and never re-typed -- so the pin reads the constant, and the noun stays "dated report".
    assert ch.receipt_words == R.CHAIN_RECEIPT_REPORT_OUTSIDE % "2019-01-05", ch.receipt_words
    assert "dated report" in ch.receipt_words and "dated action" not in ch.receipt_words
    assert ch.event_kind == "report_outside", ch.event_kind
    assert ch.receipts_aged_out == 0, "a report sentence is NOT a dated action"
    assert got["counts"]["mechanism_refused"] == 1 and got["counts"]["receipts_aged_out"] == 0, got["counts"]
    assert ch.to_dict()["mechanism_refused_date"] == "2019-01-05"
    assert ch.to_dict()["mechanism_refused_hop"] == "top"
    # a report sentence INSIDE one band-length is the chain's mechanism receipt and refuses nothing
    bd2 = _cboard()
    _crow(bd2, "a_cbot", "top", st=_cs("t2", pct=95),
          receipts=[{"date": "2026-08-20", "source": "src", "tier": 2,
                     "text": "the cold phase tightened the planting window this month"}])
    _crow(bd2, "a_cbot", "bot", st=_cs("b2", pct=50))
    _cpath(bd2, "a_cbot", ["top", "bot"])
    _cfinish(bd2)
    got2 = W.chain_rows(bd2, None, knobs=bd2.knobs)
    assert got2["pool"][0].receipt_kind == "mechanism" and got2["pool"][0].terms["event"] == 6
    assert got2["pool"][0].mechanism_refused_date == "" and got2["counts"]["mechanism_refused"] == 0
    # blocker 6 (round-4 review MINOR 5): the thin record line agrees with itself at ONE firing.
    # 09-24 FIX ROUND (item 28c, DECLARED): the same agreement at one and at two, in the desk's words.
    one = W.chain_history_words({"n_firings": 1, "unmeasured": 0, "fraction": 1.0, "aligned": 1})
    assert "only one of the past times this reading sat this far out has a reading" in one, one
    two = W.chain_history_words({"n_firings": 2, "unmeasured": 0, "fraction": 1.0, "aligned": 2})
    assert "only two of the past times this reading sat this far out have a reading" in two, two


# ═════════════════════════════════════════════════════════════════════════════════════════════════════
# THE 09-23 FIX ROUND, LANE W (CONTRACT C7 / C8 / C11; THREAT_MODEL W-1..W-12). Every pin below is the
# drive its threat row names, at the unit, offline and at zero cost: the SLOT STATE over the three payload
# shapes and a seeded pool fuzz (W-1, W-2); the EVENT KIND over the precision x (event <, =, > document)
# table and the two node types (W-3, W-4, W-5); the PHASE-AWARE tail at ONI +1.99 / -1.2 / +0.3 (W-7);
# the mechanism-refused FOLD (W-11); the bounded payload's DISTINCT fill (W-10); the EFFECT WINDOW's
# bounds (W-9); the PERIOD-GAP demotion (W-12); and the chain-scoped event reading never touching the
# rows the loud set reads (W-6).
# ═════════════════════════════════════════════════════════════════════════════════════════════════════
import random as _random


def _oni_st(level, pct, z, *, values=None, dates=None, conv=None):
    """ONE ONI StateRow on the DECLARED card (`silver_noaa_oni.oni_anom`), so `render.phase_for_state`
    reads the shipped phase pair and the shipped band -- nothing about the phase is typed here."""
    key = SeriesKey(ref="oni_climate")
    st = StateRow(key=key, status="ok", coverage_tier="series", table="silver_noaa_oni",
                  metric="oni_anom", cadence="monthly", unit="degC", narrate_unit="degC",
                  level=level, level_date="2026-08", knowledge_date="2026-09-05",
                  z={"value": z, "window_n": 120}, percentile={"value": pct, "n": 120},
                  run={"direction": "up", "length": 6, "since_date": "2026-03"}, convention=conv,
                  changes=[{"window": "1m", "delta": 0.1, "pct": 1.0}])
    if values is not None:
        st.inputs = {key.label(): {"values": list(values), "dates": list(dates), "unit": "degC"}}
    return st


#: A 48-month ONI-shaped record ending August 2026, and the six months the 1-2 quarter window reads.
_ONI_DATES = ["%04d-%02d-28" % (2022 + (i // 12), (i % 12) + 1) for i in range(56)]


def _oni_values(last6):
    base = [(-1.4 + 2.8 * ((i * 7) % 50) / 49.0) for i in range(50)]
    return base + list(last6)


def _phase_hops(level, pct, z, last6, *, asof="2026-09-07"):
    # THE ARRAY MEMO IS KEYED ON (label, as-of, offset, mirror epoch) -- a hand-built StateRow carries no
    # as-of, so the three parametrised readings would share one cached array. Cleared here, per board.
    W.cache_clear()
    bd = _cboard(asof=asof)
    st = _oni_st(level, pct, z, values=_oni_values(last6), dates=_ONI_DATES)
    for did in ("El_Nino", "La_Nina"):
        _crow(bd, "a_cbot", did, lag="1-2 quarters", st=st, series_key=st.key.label())
    return bd, {d: W.chain_hop(bd, bd.row("a_cbot", d)) for d in ("El_Nino", "La_Nina")}


@pytest.mark.parametrize("level,pct,z,last6,in_force,zeroed", [
    (1.99, 95.0, 2.03, (0.8, 1.1, 1.3, 1.6, 1.8, 1.99), "El_Nino", "La_Nina"),
    (-1.2, 5.0, -1.6, (-0.6, -0.8, -0.9, -1.0, -1.1, -1.2), "La_Nina", "El_Nino"),
    (0.3, 60.0, 0.4, (0.1, 0.2, 0.25, 0.2, 0.3, 0.3), "", None)])
def test_W7_a_PHASE_hop_scores_its_TAIL_on_its_OWN_pole_and_ONLY_when_the_OTHER_pole_is_in_force(
        level, pct, z, last6, in_force, zeroed):
    """**THE 2024-03-01 AS-OF TURN RANKED A LA NINA CHAIN FIRST ON ONI +1.99 degC** -- "La Nina sits at
    the 95th percentile of its own record", scored 22.5 of 25 on the WARM tail. `chain_score`'s TAIL read
    the hop's UNSIGNED distance from the middle on a series two poles share, and the estate's own phase
    producer (`render.phase_for_state`) was never consulted.

    THE RULE, read off the DECLARED pair and never an id list: a hop naming one pole scores its tail on
    that pole's side ONLY where the OTHER pole is in force. ONI +1.99: La Nina ~0, El Nino unchanged;
    ONI -1.2: the mirror; ONI +0.3 -- inside the line, neither pole in force -- both unchanged (W-7)."""
    bd, hops = _phase_hops(level, pct, z, last6)
    head = W._hop_tail(pct, z)                       # HEAD's unsigned measure, the untouched reading
    for did, h in hops.items():
        assert h.phase_driver == did, (did, h.phase_driver)
        assert h.phase_in_force_driver == in_force, (did, h.phase_in_force_driver)
        assert h.phase_orient == (1 if did == "El_Nino" else -1)
        if did == zeroed:
            assert h.phase_reoriented and h.phase_in_force is False
            assert h.tail == 0.0 and h.tail_peak == 0.0 and h.chain_tail == 0.0, h
            assert h.tail_peak_percentile is None and h.tail_lag_to == "", "no peak on its own side"
        else:
            assert not h.phase_reoriented
            assert h.tail == head, (did, h.tail, head)
            assert h.phase_in_force is (bool(in_force) and in_force == did)
    # AND A HOP OF NO DECLARED PAIR IS NEVER TOUCHED: its phase fields are empty and its tail is HEAD's.
    st = _cs("drought", pct=95, z=2.03)
    row = _crow(bd, "a_cbot", "drought", st=st)
    dh = W.chain_hop(bd, row)
    assert (dh.phase_driver, dh.phase_in_force, dh.phase_orient) == ("", None, 0)
    assert dh.tail == W._hop_tail(95, 2.03) and not dh.phase_reoriented


def test_W7_a_cool_reading_STILL_IN_TRANSIT_keeps_the_La_Nina_hops_own_peak():
    """THE IN-TRANSIT DOCTRINE (owner ruling 5) SURVIVES THE PHASE RULE. A La Nina reading inside the
    hop's declared window is still acting on the next hop after the warm pole took over, so the oriented
    peak is the window's MINIMUM -- the cool reading, dated -- and the chain prints "peaked ... now" with
    the lag counted from THAT reading. Only the other pole's readings are refused, never the hop's own."""
    _bd, hops = _phase_hops(1.99, 95.0, 2.03, (-0.8, -0.3, 0.4, 1.0, 1.6, 1.99))
    ln = hops["La_Nina"]
    assert ln.phase_reoriented and ln.tail == 0.0
    assert ln.tail_peak > 0.0 and ln.tail_peak_date == "2026-03-28", (ln.tail_peak, ln.tail_peak_date)
    assert ln.tail_peak_percentile is not None and ln.tail_peak_percentile < 50.0
    assert ln.tail_lag_to == W._add_months("2026-03-28", 6), ln.tail_lag_to
    assert ln.chain_tail == ln.tail_peak > 0.0


def test_W7_ASYMMETRY_reads_a_re_oriented_hop_on_its_own_pole_and_never_the_other_poles_desk_line():
    """The ASYMMETRY term had the same blind spot twice: a La Nina hop at the 95th percentile of ONI
    passed the 90 / 10 cut on the WARM side, and "sits on a declared desk line" read the El Nino band's
    own label as La Nina's. On the hop's own pole neither is its fact."""
    def _chain(top):
        W.cache_clear()
        bd = _cboard()
        st = _oni_st(1.99, 95.0, 2.03, values=_oni_values((0.8, 1.1, 1.3, 1.6, 1.8, 1.99)),
                     dates=_ONI_DATES, conv={"matched": True, "label": "a strong warm phase"})
        _crow(bd, "a_cbot", top, lag="1-2 quarters", st=st, series_key=st.key.label())
        _crow(bd, "a_cbot", "bot", st=_cs("bot", pct=50))
        _cpath(bd, "a_cbot", [top, "bot"])
        _cfinish(bd)
        return W.chain_rows(bd, None, knobs=bd.knobs)["pool"][0]
    warm, cool = _chain("El_Nino"), _chain("La_Nina")
    assert warm.terms["asymmetry"] > 0.0 and warm.terms["tail"] > 20.0, warm.terms
    assert cool.terms["asymmetry"] == 0.0 and cool.terms["tail"] == 0.0, cool.terms
    assert warm.score > cool.score


def _rc(event_date, precision, doc, text="an action", source="src"):
    return {"event_date": event_date, "event_date_precision": precision, "date": doc,
            "text": text, "source": source, "tier": 1}


@pytest.mark.parametrize("ed,prec,doc,node_type,kind", [
    # DAY precision: before, EQUAL TO (W-5) and after its document date
    ("2026-08-01", "day", "2026-08-05", "hazard", "action_open"),
    ("2026-08-05", "day", "2026-08-05", "hazard", "action_open"),
    ("2026-09-20", "day", "2026-08-05", "hazard", "guidance"),
    # MONTH: 09-23 FIX ROUND (review WT F-1) -- a document written INSIDE the month it is about is a
    # dated REPORT (the interval straddles its date: "La Nina switched to neutral in March 2023",
    # published 30 March 2023), never a forecast; a document before the month is a forecast; after it,
    # a recap
    ("2026-06-01", "month", "2026-06-10", "hazard", "report_in_reach"),
    ("2026-06-01", "month", "2026-05-20", "hazard", "guidance"),
    ("2026-06-01", "month", "2026-07-01", "hazard", "action_open"),
    # QUARTER
    ("2026-04-01", "quarter", "2026-05-15", "hazard", "report_in_reach"),
    ("2026-04-01", "quarter", "2026-03-15", "hazard", "guidance"),
    ("2026-04-01", "quarter", "2026-07-02", "hazard", "action_open"),
    # YEAR -- cotton's E48 exactly: "during 2026", published 2026-04-03, on the El Nino (climate) hop: a
    # report inside its own year -- the mechanism tier, never an open action and never worded a forecast
    ("2026-01-01", "year", "2026-04-03", "climate_driver", "report_in_reach"),
    ("2025-01-01", "year", "2026-01-15", "hazard", "action_aged"),
    # the realised report of WT F-1 read at an as-of long after its period: a SPENT report, never an action
    ("2019-03-01", "month", "2019-03-21", "hazard", "report_outside"),
    # 09-24 FIX ROUND (CONTRACT K6 rule 1, RE-BANKED): an UNDECLARED precision has no interval to
    # compare, so it is NEVER an action -- a dated report on the recency bound, read at its DOCUMENT date
    # (HEAD read it at face value: guidance / action_open). The 09-24 tariff hop carried "2025-02-01" with
    # no precision and printed it as the day China announced its tariff.
    ("2026-08-01", "", "2026-07-01", "hazard", "report_in_reach"),
    ("2026-08-01", "", "2026-08-01", "hazard", "report_in_reach"),
    ("2026-08-01", "", "2025-06-01", "hazard", "report_outside"),
    ("2026-08-01", "", "2026-08-01", "policy_event", "report_in_reach"),
    # a forecast whose WHOLE interval closed long before the as-of is a spent report
    ("2019-01-01", "year", "2019-03-01", "hazard", "report_outside"),
    # OWNER DECISION O-6 (a), RE-BANKED (it REVISES round 1's W-4, quoted: "a scheduled policy action,
    # effective after its document date, is an ACTION"): a scheduled or conditional statement is GUIDANCE
    # until a later document reports it done -- on a regime node too. The 2024-03-01 page promoted MPOC's
    # "If the mandated biodiesel blend rate ... is raised to 15% from 10% beginning in April 2023"
    # (documented 2023-03-28) into a policy regime in force, EVENT 12.
    ("2026-09-01", "day", "2026-08-01", "policy_event", "guidance"),
    ("2023-04-01", "month", "2023-03-28", "policy_event", "report_outside"),
    # ...and the SAME action documented AFTER it happened is realised: the regime in force (W-3's case --
    # the 2025-03-10 imposition documented 2025-03-19), or open while its own window runs
    ("2025-03-10", "day", "2025-03-19", "policy_event", "regime_in_force"),
    ("2026-08-01", "day", "2026-08-05", "policy_event", "action_open"),
    # a month-precision action reported AFTER its month is realised (Feb 2025 documented 19 Mar 2025)
    ("2025-02-01", "month", "2025-03-19", "policy_event", "regime_in_force"),
    # ...and one reported INSIDE its own month is a straddle: a dated report, never an action
    ("2025-03-01", "month", "2025-03-19", "policy_event", "report_outside"),
    # ...and a statement dated to a period its own document sits inside ("the upcoming 2026 USMCA
    # review", published 2026-04-23) is not a dated action at all (review WT M-1 (b))
    ("2026-01-01", "year", "2026-04-23", "policy_event", "report_in_reach"),
])
def test_W4_W5_the_event_kind_reads_the_date_AT_ITS_PRECISION_against_its_OWN_document_date(
        ed, prec, doc, node_type, kind):
    """**COTTON SCORED A CONDITIONAL FORECAST 20 OF 20 AS AN OPEN ACTION.** "If El Nino conditions emerge
    during 2026 ..." (USDA GAIN, 2026-04-03) was stored as event 2026-01-01 and read as a dated action
    whose window was still open. ``contracts.py`` already declares the semantics -- ``event_date >
    document_date marks forward guidance`` -- and the precision the extractor stamped makes the date an
    INTERVAL: a year is its whole year, which runs past its document. The table is the precision x
    (event before / equal / after its document) grid and the two node types; the band is 1-3 quarters
    except for the regime rows, which carry the tariff's own 0-2."""
    band = parse_lag("0-2 quarters" if node_type == "policy_event" else "1-3 quarters")
    ev = W.hop_event([_rc(ed, prec, doc)], asof="2026-09-23", band=band, node_type=node_type)
    assert ev["kind"] == kind, (ed, prec, doc, node_type, ev)
    assert ev["kind"] in W.EVENT_KINDS
    iv = ev["interval"]
    if not prec:
        # K6 rule 1: an unplaced date carries NO interval -- nobody may print the stored first-of-period
        assert iv == (), iv
        assert W.realised(_rc(ed, prec, doc)) is False
        return
    assert iv == W.event_interval(ed, prec) and iv[0] <= iv[1], iv
    if prec == "year":
        assert iv == (ed[:4] + "-01-01", ed[:4] + "-12-31")
    if prec == "day":
        assert iv == (ed, ed), "a day is itself -- the rounding case W-5 guards"
    # THE ACTION KINDS ARE EXACTLY THE REALISED CANDIDATES (K6): the interval ends on or before its
    # document's own date
    assert (kind in ("action_open", "action_closed", "action_aged", "regime_in_force")) == W.realised(
        _rc(ed, prec, doc)), (ed, prec, doc, kind)


def test_W4_the_event_after_the_asof_never_anchors_and_an_empty_list_is_none():
    band = parse_lag("1-3 quarters")
    assert W.hop_event([_rc("2026-11-15", "day", "2026-08-20")], asof="2026-09-23",
                       band=band)["kind"] == "none"
    assert W.hop_event([], asof="2026-09-23", band=band)["kind"] == "none"
    # A FORECAST NEVER DISPLACES AN ACTION on the same hop: DESIGN B.4's ladder chooses the action.
    got = W.hop_event([_rc("2026-06-01", "month", "2026-06-10", text="a forecast"),
                       _rc("2026-05-20", "day", "2026-05-21", text="an enacted step")],
                      asof="2026-09-23", band=band)
    assert got["kind"] == "action_open" and got["receipt"]["text"] == "an enacted step", got


def _regime_board(receipts, *, node_type="policy_event", asof="2026-09-23"):
    bd = _cboard(asof=asof)
    top = _crow(bd, "a_cbot", "tariff", lag="0-2 quarters", st=_cs("tariff_flow", pct=95))
    top.type = node_type
    _crow(bd, "a_cbot", "bot", st=_cs("bot", pct=50))
    _cpath(bd, "a_cbot", ["tariff", "bot"])
    _cfinish(bd)
    return W.chain_rows(bd, None, knobs=bd.knobs, receipts={("a_cbot", "tariff"): list(receipts)})


def test_W3_a_REGIME_is_the_NEWEST_dated_action_on_its_node_and_a_later_one_SUPERSEDES_it():
    """**THE TARIFF TURN SCORED A STANDING TARIFF 0 OF 20** (receipts_aged_out 2): China's March 2025
    imposition, not reversed, aged on a shock's 0-2 quarter lag band as a SPENT impulse. Owner decision 3
    (build default): a node the graph TYPES ``policy_event`` reads its NEWEST dated action as a regime,
    in force until a later dated action on the same node, scored at the CLOSED weight (12) because the
    evidence carries no polarity -- and the words name the action and the rule, never "the tariff is in
    force"."""
    band = parse_lag("0-2 quarters")
    imp18 = _rc("2018-07-06", "day", "2018-07-12", text="China imposed a 25 percent tariff on US soybeans")
    exc20 = _rc("2020-02-18", "day", "2020-04-09", text="China announced a new round of tariff exclusions")
    ev = W.hop_event([imp18, exc20], asof="2026-09-23", band=band, node_type="policy_event")
    assert ev["kind"] == "regime_in_force" and ev["event_date"] == "2020-02-18", ev
    assert ev["receipt"]["text"] == exc20["text"], "the LATER action is the regime; the 2018 one is not"
    # the tariff turn's own document, alone: in force, never aged
    imp25 = _rc("2025-03-10", "day", "2025-03-19", text="China imposed an additional 10 percent tariff")
    got = _regime_board([imp25])
    ch = got["pool"][0]
    assert (ch.receipt_kind, ch.event_kind, ch.terms["event"]) == ("closed", "regime_in_force", 12)
    assert ch.receipts_aged_out == 0 and got["counts"]["receipts_aged_out"] == 0, got["counts"]
    assert got["counts"]["with_event"] >= 1, got["counts"]
    assert "2025-03-10" in ch.receipt_words and "in force until a later dated action" in ch.receipt_words
    assert "tariff" not in ch.receipt_words, "the words name the action's DATE and the rule, not a claim"
    assert REG.desk_register_hits(ch.receipt_words) == [] and REG.internal_leaks(ch.receipt_words) == []
    # HEAD's reading of the SAME document on a node the graph does not type as a regime: aged, counted
    twin = _regime_board([imp25], node_type="hazard")
    tc = twin["pool"][0]
    assert (tc.receipt_kind, tc.event_kind, tc.terms["event"]) == ("none", "action_aged", 0)
    assert twin["counts"]["receipts_aged_out"] == 1


def test_W3_REFUTED_a_later_EXCLUSION_supersedes_the_tariff_and_the_imposition_NEVER_reads_in_force():
    """THE BRIEF'S OWN REFUTATION: the tariff chain with a later "exclusion" receipt added must NOT read
    the imposition in force. The regime is the newest dated action on the node -- the exclusion -- and
    the chain's receipt IS that document: its date, its text, nothing of the imposition."""
    imp25 = _rc("2025-03-10", "day", "2025-03-19", text="China imposed an additional 10 percent tariff")
    exc25 = _rc("2025-11-10", "day", "2025-11-12",
                text="China suspended the additional tariff on US soybeans")
    got = _regime_board([imp25, exc25])
    ch = got["pool"][0]
    assert ch.event_kind == "regime_in_force", ch.event_kind
    assert ch.receipt["text"] == exc25["text"], ch.receipt
    assert "2025-11-10" in ch.receipt_words and "2025-03-10" not in ch.receipt_words, ch.receipt_words
    hop = ch.hops[0]
    assert hop.event_date == "2025-11-10" and hop.event_receipt["text"] == exc25["text"]
    assert hop.event_open is False
    # ...and in the reverse listing order the answer is the same document: the rule is the DATE.
    rev = _regime_board([exc25, imp25])["pool"][0]
    assert rev.receipt["text"] == exc25["text"]


def test_W4_cottons_E48_forecast_is_GUIDANCE_on_the_chain_and_the_ROW_keeps_HEADs_reading():
    """The cotton chain's El Nino hop, through the real builder: the conditional scores at the MECHANISM
    tier (6), prints its interval at its precision ("during 2026"), and the ROW -- which the loud set
    reads -- keeps HEAD's event date and open flag untouched (W-6). 09-23 FIX ROUND (review WT F-1): the
    note is dated INSIDE the year it is about, so it is a dated REPORT (`report_in_reach`) at the same
    mechanism weight -- never an open action, and never worded a forecast (the realised / conditional split
    is an extraction fact, docketed)."""
    e48 = _rc("2026-01-01", "year", "2026-04-03", source="usda_gain_cotton",
              text="If El Nino conditions emerge during 2026, they could weaken the monsoon")
    bd = _cboard(asof="2026-09-23")
    top = _crow(bd, "a_cbot", "El_Nino", lag="1-3 quarters", st=_cs("elnino", pct=93))
    top.type = "climate_driver"
    # step 5's own reading of HEAD's winner, exactly as `_stage2` stamps it
    top.event_date, top.event_precision = "2026-01-01", "year"
    top.event_receipt, top.event_open = dict(e48), W.event_is_open("2026-01-01", top.lag_band,
                                                                    "2026-09-23")
    assert top.event_open is True, "HEAD read the forecast as an OPEN action"
    _crow(bd, "a_cbot", "bot", st=_cs("bot", pct=50))
    _cpath(bd, "a_cbot", ["El_Nino", "bot"])
    _cfinish(bd)
    got = W.chain_rows(bd, None, knobs=bd.knobs, receipts={("a_cbot", "El_Nino"): [e48]})
    ch = got["pool"][0]
    assert (ch.receipt_kind, ch.event_kind, ch.terms["event"]) == ("mechanism", "report_in_reach", 6)
    assert "during 2026" in ch.receipt_words and "2026-04-03" in ch.receipt_words, ch.receipt_words
    assert "forecast" not in ch.receipt_words and "not as an action" not in ch.receipt_words
    assert "2026-01-01" not in ch.receipt_words, "the normalised first day is not a date anyone wrote"
    assert ch.hops[0].event_interval == ("2026-01-01", "2026-12-31")
    assert ch.hops[0].event_open is False and ch.hops[0].event_kind == "report_in_reach"
    assert got["counts"]["with_event"] == 0 and got["counts"]["cross_market_event"] == 0
    # THE ROW IS NEVER WRITTEN BY THE CHAIN LEG
    assert (top.event_date, top.event_open, top.event_precision) == ("2026-01-01", True, "year")
    assert REG.desk_register_hits(ch.receipt_words) == [] and REG.internal_leaks(ch.receipt_words) == []


def test_W6_the_chain_leg_never_moves_a_ROW_event_field_or_the_LOUD_set(real):
    """W-6: `row.event_open` feeds the loud set's re-take (step 5), so the event semantics must stay on
    the CHAIN. The B40 scenario (an open policy action plus a forecast dated after the as-of) walked with
    the chain leg OFF and ON: every row's event date, precision, receipt and open flag, the loud set, the
    board order and the ledger are identical."""
    from leviathan.graphrag.state import __main__ as H

    def _walk(chain):
        anchors = W.resolve_anchors(attached_event="malaysian_crude_palm_oil_cme")
        rs = {("malaysian_crude_palm_oil_cme", "biodiesel_mandate"): list(H.B40_RECEIPTS)}
        bd = W.walk(graph=real, asof=H.ASOF, mode="max", anchors=anchors,
                    question="Indonesia raised the biodiesel mandate to B40", receipts=rs,
                    state_fn=H.fixture_state_fn(H.ASOF), key_fn=None, knobs=B.board_knobs_of("max"),
                    width=2, legb_on=False, state_chain=chain)
        return bd, {r.key: (r.event_date, r.event_precision, json.dumps(r.event_receipt, sort_keys=True),
                            r.event_open, bool(r.legs.get("loud"))) for r in bd.rows}
    off, rows_off = _walk(False)
    on, rows_on = _walk(True)
    assert rows_off == rows_on

    def _ledger(bd):                                  # every ledger fact but the wall-clock milliseconds
        d = bd.ledger.to_dict()
        d["waves"] = {n: {k: v for k, v in w.items() if k != "ms"} for n, w in d["waves"].items()}
        return d
    assert off.order == on.order and _ledger(off) == _ledger(on)
    assert off.windows == on.windows
    assert on.chains and not off.chains


# ── W-1 / W-2: THE SLOT STATE ──────────────────────────────────────────────────────────────────────────
def test_W1_the_SUBJECT_slot_state_is_read_off_the_BOARD_across_the_three_payload_shapes():
    """**D9: `slot_subject 0` ON TEN OF TEN TURNS READ AS "NEVER LIT".** The subject resolver never ran
    (GRAPHRAG_SUBJECT_RESOLVER dark), so the slot was skipped before the pool was read -- and the count
    printed the same zero a turn that answered its subject by the rank prints. The state is read off
    `Board.subject`, which the seam writes ONLY when the resolver payload is on: payload OFF ->
    `resolver_off`; ON and nothing picked -> `not_asked`; ON with a pick the board carries -> the
    selection's own word (`seated` / `answered_by_rank`)."""
    named = B.Anchor(contract="a_cbot", source="named", named=True)
    bd = _slot_board(anchors=(named,), horizon=None)
    _cfinish(bd)
    assert W.chain_rows(bd, None, knobs=bd.knobs)["counts"]["slot_state"]["subject"] == "resolver_off"
    bd = _slot_board(anchors=(named,), horizon=None)
    bd.subject = {"hints": {}, "picked": [], "groups": {}, "source": "named", "vs_focus": ""}
    _cfinish(bd)
    assert W.chain_rows(bd, None, knobs=bd.knobs)["counts"]["slot_state"]["subject"] == "not_asked"
    # a pick no anchor board of this turn carries: ASKED, and nothing here can answer it
    bd = _slot_board(anchors=(named,), horizon=None)
    bd.subject = {"hints": {}, "picked": ["x_id"], "groups": {}, "source": "named", "vs_focus": ""}
    _cfinish(bd)
    assert W.chain_rows(bd, None, knobs=bd.knobs)["counts"]["slot_state"]["subject"] == "no_candidate"
    for did, want in (("t5", "seated"), ("t0", "answered_by_rank")):
        sub = B.Anchor(contract="a_cbot", source="subject", driver_id=did, subject=True)
        bd = _slot_board(anchors=(sub,), horizon=None)
        bd.subject = {"hints": {}, "picked": [did], "groups": {}, "source": "subject", "vs_focus": ""}
        _cfinish(bd)
        got = W.chain_rows(bd, None, knobs=bd.knobs)
        ss = got["counts"]["slot_state"]
        assert ss["subject"] == want, (did, ss)
        assert got["counts"]["slot_subject"] == (1 if want == "seated" else 0)
        assert ss["pair"] == "not_asked" and ss["horizon"] == "not_asked"
    # a FOCUS DRIVER anchors the slot without the resolver: the slot is LIVE, not resolver_off
    fd = B.Anchor(contract="a_cbot", source="focus_driver", driver_id="t5")
    bd = _slot_board(anchors=(fd,), horizon=None)
    _cfinish(bd)
    assert W.chain_rows(bd, None, knobs=bd.knobs)["counts"]["slot_state"]["subject"] == "seated"


def test_W1_the_PAIR_and_HORIZON_slot_states_name_what_happened():
    """PAIR: `no_candidate` where two markets are named and no chain reaches the other one (the palm /
    rapeseed turn) -- the one state the render prints; HORIZON: `answered_by_rank` where the top K's own
    band holds the horizon (deep / max / 2024 on the re-smoke), `not_asked` where none was asked."""
    pool = [_slot_chain(0, 90.0, ("t0", "b0"), "a_cbot"),
            _slot_chain(1, 80.0, ("t1", "b1"), "a_cbot"),
            _slot_chain(2, 70.0, ("t2", "b2"), "a_cbot", band="4-8 quarters")]
    got = W.chain_render_set(pool, k=1, named_contracts=("a_cbot", "z_cbot"), horizon_months=3)
    assert got["counts"]["slot_state"] == {"subject": "not_asked", "pair": "no_candidate",
                                           "horizon": "answered_by_rank"}, got["counts"]["slot_state"]
    got = W.chain_render_set(pool, k=1, named_contracts=("a_cbot",), horizon_months=None)
    assert got["counts"]["slot_state"] == {"subject": "not_asked", "pair": "not_asked",
                                           "horizon": "not_asked"}
    # the horizon only the lower chain's band holds: SEATED
    got = W.chain_render_set(pool, k=1, horizon_months=18)
    assert got["counts"]["slot_state"]["horizon"] == "seated"
    assert next(c for c in got["rendered"] if c.slot == "horizon").hop_ids == ("t2", "b2")
    # A CAP OF ZERO ASKS FOR NO SEAT: no slot runs, every slot keeps its question-side word
    got = W.chain_render_set(pool, k=0, horizon_months=18, subject_off="resolver_off")
    assert got["counts"]["slot_state"] == {"subject": "resolver_off", "pair": "not_asked",
                                           "horizon": "not_asked"}


def test_W2_POOL_FUZZ_every_slot_state_agrees_with_the_seat_the_selection_ACTUALLY_took():
    """W-2: a slot state is stamped inside the SAME branch that decides the seat, so it can never
    disagree with the render set. Seeded fuzz over the reviewer's pool shape (k = 1..3, fold-duplicate
    chains, random terminals and bands, all three slots randomly live): `seated` iff a rendered chain
    carries `slot == word`; `answered_by_rank` iff a chain already on the page when the slot is asked
    (the top K, the sign swap, an earlier slot's seat) passes the slot's own test;
    `no_candidate` iff the slot is live and NO chain in the pool passes it; `not_asked` iff it is not
    live -- and the five seat counts are exactly the seats."""
    rng = _random.Random(20260923)
    tests = {"subject": lambda c, kw: W._slot_subject(c, kw["subject_ids"]),
             "pair": lambda c, kw: W._slot_pair(c, kw["named_contracts"]),
             "horizon": lambda c, kw: W._slot_horizon(c, kw["horizon_months"])}
    seen = {s: set() for s in W.QUESTION_SLOTS}
    for trial in range(400):
        n = rng.randint(1, 9)
        pool = []
        for i in range(n):
            top = rng.choice(("t0", "t1", "t2", "sub", "t3"))
            pool.append(_slot_chain(i, float(rng.randint(10, 99)), (top, "b%d" % rng.randint(0, 3)),
                                    rng.choice(("a_cbot", "z_cbot", "q_cbot")),
                                    band=rng.choice(("0-1 quarters", "2-4 quarters", "4-8 quarters"))))
        kw = {"subject_ids": ({"a_cbot": frozenset({"sub"})} if rng.random() < 0.6 else {}),
              "named_contracts": (("a_cbot", "z_cbot") if rng.random() < 0.6 else ("a_cbot",)),
              "horizon_months": rng.choice((None, 3, 9, 18))}
        k = rng.randint(0, 3)
        got = W.chain_render_set(pool, k=k, **kw)
        ss, rendered = got["counts"]["slot_state"], got["rendered"]
        for word in W.QUESTION_SLOTS:
            st = ss[word]
            seen[word].add(st)
            assert st in W.SLOT_STATES, st
            live = {"subject": bool(kw["subject_ids"]), "pair": len(set(kw["named_contracts"])) >= 2,
                    "horizon": kw["horizon_months"] is not None}[word] and k > 0
            fits = [c for c in pool if tests[word](c, kw)]
            # the chains ALREADY ON THE PAGE when this slot is asked: the top K, the sign swap and every
            # EARLIER question slot's seat -- the population `chain_render_set`'s own test reads
            earlier = ("top", "sign") + W.QUESTION_SLOTS[:W.QUESTION_SLOTS.index(word)]
            base = [c for c in rendered if c.slot in earlier]
            assert (st == "seated") == any(c.slot == word for c in rendered), (trial, word, st)
            assert got["counts"]["slot_" + word] == (1 if st == "seated" else 0), (trial, word)
            if not live:
                assert st in ("not_asked", "resolver_off"), (trial, word, st)
                assert all(word not in c.slot_fits for c in pool)
                continue
            assert (st == "answered_by_rank") == any(tests[word](c, kw) for c in base), (trial, word)
            assert (st == "no_candidate") == (not fits), (trial, word, st)
            assert {id(c) for c in pool if word in c.slot_fits} == {id(c) for c in fits}
    # the fuzz reached every state the three slots can take
    assert {"seated", "answered_by_rank", "no_candidate", "not_asked"} <= set().union(*seen.values())


def test_W2_the_fixture_boards_carry_ONE_slot_state_per_slot_from_the_published_vocabulary(chain_tiers):
    for mode, bd in chain_tiers.items():
        ss = bd.chain_counts["slot_state"]
        assert set(ss) == set(W.QUESTION_SLOTS) and set(ss.values()) <= set(W.SLOT_STATES), (mode, ss)
        # the fixture turn names one market, no resolver ran, and asks "3 months from now"
        assert ss["subject"] == "resolver_off" and ss["pair"] == "not_asked", (mode, ss)
        assert ss["horizon"] in ("answered_by_rank", "seated"), (mode, ss)
        assert (ss["horizon"] == "seated") == (bd.chain_counts["slot_horizon"] == 1)
        # and it rides the trace inside the already-registered payload
        assert bd.trace()["chain_counts"]["slot_state"] == ss


# ── W-11: the mechanism-refused FOLD ────────────────────────────────────────────────────────────────
def test_W11_mechanism_refused_counts_DOCUMENTS_and_the_per_chain_field_and_the_ranks_are_unchanged():
    """**COCOA PRINTED 42 OF 57** -- one refused report sentence rides every pool chain that walks its
    memoised hop, and the pool carried THREE documents. The count line folds on the document's own
    address (contract, driver_id, date), exactly as `receipts_aged_out` does; each chain still carries
    its own `mechanism_refused_*` and no rank moves (the fold reads the pool, never a term)."""
    bd = _cboard()
    old = [{"date": "2019-01-05", "source": "src", "tier": 2, "text": "a report on the mechanism"}]
    _crow(bd, "a_cbot", "top", st=_cs("top", pct=95), receipts=old)
    for i in range(6):
        _crow(bd, "a_cbot", "b%d" % i, st=_cs("b%d" % i, pct=40 + i))
        _cpath(bd, "a_cbot", ["top", "b%d" % i])
    _crow(bd, "a_cbot", "other", st=_cs("other", pct=92),
          receipts=[{"date": "2018-06-01", "source": "src", "tier": 2, "text": "another report"}])
    _crow(bd, "a_cbot", "ob", st=_cs("ob", pct=50))
    _cpath(bd, "a_cbot", ["other", "ob"])
    _cfinish(bd)
    got = W.chain_rows(bd, None, knobs=bd.knobs)
    pool = got["pool"]
    per_chain = [c for c in pool if c.mechanism_refused_date]
    assert len(per_chain) == 7, "every chain keeps its own field"
    assert got["counts"]["mechanism_refused"] == 2, got["counts"]["mechanism_refused"]
    assert {W._refused_report_key(c) for c in per_chain} == {
        ("a_cbot", "top", "2019-01-05"), ("a_cbot", "other", "2018-06-01")}
    assert [c.rank for c in sorted(pool, key=lambda c: c.rank)] == sorted(c.rank for c in pool)
    assert all(c.terms["event"] == 0 for c in per_chain)


# ── W-10: the bounded payload ─────────────────────────────────────────────────────────────────────────
def test_W10_the_trace_payload_carries_what_RENDERED_each_live_slots_best_and_then_DISTINCT_sequences():
    """**THE TARIFF PAYLOAD WAS TWO RENDERED CHAINS AND TEN CROSS-VARIANTS OF ONE SEQUENCE.** Rendered
    first, whatever they share; then the best-ranked chain of each LIVE question slot not already carried;
    then the rest by rank with ONE chain per (contract, hop sequence). Raising the cap was the rejected
    fix, and the cap holds."""
    pool = [_slot_chain(0, 95.0, ("t0", "b0"), "a_cbot")]
    # ten cross-variants of ONE sequence, each outranking every distinct chain below
    for i, far in enumerate(("x%d_cbot" % j for j in range(10))):
        ch = _slot_chain(1, 90.0 - i * 0.1, ("t1", "b1"), far)
        pool.append(ch)
    pool += [_slot_chain(20 + i, 60.0 - i, ("d%d" % i, "e%d" % i), "a_cbot") for i in range(6)]
    pool.append(_slot_chain(40, 50.0, ("sub", "b9"), "a_cbot"))          # the subject's own chain
    pool.append(_slot_chain(41, 49.0, ("sub", "b8"), "a_cbot"))          # ...and its runner-up
    got = W.chain_render_set(pool, k=2, subject_ids={"a_cbot": frozenset({"sub"})})
    tr = W.chain_trace_set(pool, k=6)
    rendered = [c for c in pool if c.rendered]
    assert tr[:len(rendered)] == sorted(rendered, key=lambda c: c.rank)
    assert got["counts"]["slot_state"]["subject"] == "seated"
    seqs = [(c.contract, c.hop_ids) for c in tr]
    assert len(set(seqs)) == len(seqs), seqs
    # the variants of the rendered sequence never refill the payload
    assert sum(1 for s in seqs if s[1] == ("t1", "b1")) == 1
    # the subject slot's runner-up rides the payload right after what rendered, with its decline word
    runner = next(c for c in tr if c.hop_ids == ("sub", "b8"))
    assert tr.index(runner) == len(rendered) and runner.decline in ("render_cap", "no_measured_hop")
    assert "subject" in runner.slot_fits
    assert len(tr) == 6
    # THE BOARD TRACE CARRIES THE SAME SET
    bd = _cboard()
    bd.chains, bd.chain_counts = pool, got["counts"]
    carried = [(c["contract"], tuple(h["driver_id"] for h in c["hops"]), c["terminal"])
               for c in bd.trace()["chains"]]
    assert carried[:W.CHAIN_TRACE_K] == [(c.contract, c.hop_ids, c.terminal)
                                         for c in W.chain_trace_set(pool)]


# ── W-9: the effect window ──────────────────────────────────────────────────────────────────────────
def test_W9_the_EFFECT_WINDOW_closes_at_the_NEWEST_print_plus_the_max_lag_and_the_run_start_only_opens():
    """**CORN/WHEAT F4: "closed around August 2026" FOR AN ONI STILL RISING AT +1.8 degC**, while the
    chain on the same page carried the lag to April 2027 -- SB-J counted the whole window from the run's
    START. One rule (CONTRACT C8): the run start OPENS the window; the effect CLOSES at the newest print
    plus the declared maximum lag; the peak's own window is the peak plus the maximum. Bounded (W-9): a
    run that began in 1997 still closes at newest + max."""
    band = parse_lag("1-3 quarters")
    ew = W.effect_window(band, newest="2026-07", run_start="2025-11", peak="2026-07")
    assert ew == {"opens": "2026-02-28", "closes": "2027-04-30", "peak_closes": "2027-04-30",
                  "anchor": "run"}, ew
    old = W.effect_window(band, newest="2026-07", run_start="1997-01")
    assert old["closes"] == "2027-04-30" and old["opens"] == "1997-04-30", old
    assert W.effect_window(band, newest="2026-07")["anchor"] == "reading"
    # a STRUCTURAL band opens and never closes -- no invented date
    st = W.effect_window(parse_lag("structural"), newest="2026-07", peak="2026-05")
    assert st["closes"] is None and st["peak_closes"] is None and st["opens"] is not None, st
    # a ZERO band keeps the one-month floor the peak was measured over (HEAD's `peak + 1 month`)
    pt = W.effect_window(parse_lag("0 quarters"), newest="2026-07", peak="2026-06-30")
    assert pt["closes"] == "2026-08-31" and pt["peak_closes"] == "2026-07-30", pt
    none = W.effect_window(parse_lag("not a band"), newest="2026-07")
    assert none == {"opens": None, "closes": None, "peak_closes": None, "anchor": "reading"}


def test_W9_on_the_fixture_every_hops_lag_to_is_HEADs_and_its_effect_closes_is_BOUNDED(chain_tiers):
    """The chain's `tail_lag_to` now reads `effect_window`'s `peak_closes`: byte for byte HEAD's
    `peak + max lag` on every bounded band; `effect_closes` is newest + max on 100% of hops (W-9)."""
    n = 0
    for mode, bd in chain_tiers.items():
        for c in bd.chains:
            for h in c.hops:
                band = h.lag_band
                if band is None or band.min_q is None or band.max_q is None:
                    continue
                hi = max(1, band.months()[1])
                if h.tail_peak_date:
                    assert h.tail_lag_to == W._add_months(h.tail_peak_date, hi), (mode, h)
                if h.level_date:
                    assert h.effect_closes == W._add_months(h.level_date, hi), (mode, h)
                    n += 1
    assert n > 0


# ── W-12: the period-gap demotion ─────────────────────────────────────────────────────────────────────
def test_W12_a_PERIOD_GAP_is_ONE_BAND_LOWER_inside_the_numeric_tier_and_the_row_is_never_removed():
    """**THE 2024-03-01 AS-OF TURN RANKED MARKETING YEAR 2020/21 BESIDE READINGS OF THE PRESENT.** Lane C
    stamps `StateRow.period_gap` from the STORE (`feeders.stamp_period_gaps`: a sibling series of the same
    slug held a newer period as known at the as-of -- the 09-23 verifier's F1; the card's calendar pair no
    longer decides it); the rank reads a
    non-empty gap as one band lower, so a three-year-old level is never ordered as "now" -- and the row
    keeps its state, its rank and its render (W-12). The demotion stays in the numeric tier: a gapped
    level is still a reading and is never sorted by the text tier's receipt rule."""
    def _r(did, st):
        return B.NodeRow(contract="c", driver_id=did, coverage_tier="series", state=st,
                         lag_band=parse_lag("0-1 quarters"))
    a = _r("area", _state("area", z=2.4, pct=97))
    b = _r("crush", _state("crush", z=0.3, pct=60))
    assert W.coverage_band(a) == 0 and W.coverage_band(b) == 0
    a.state.period_gap = {"expected": "2023/24", "served": "2020/21", "gap_periods": 3}
    assert W.coverage_band(a) == 1
    ranked = W.rank_rows([a, b])
    assert [r.driver_id for r in ranked] == ["crush", "area"], "a gapped level sits below the present"
    one = _r("one", _state("one", pct=95))
    one.state.period_gap = {"expected": "2023/24", "served": "2022/23", "gap_periods": 1}
    assert W.coverage_band(one) == 2
    lvl = _r("lvl", _state("lvl"))
    lvl.state.period_gap = {"expected": "2023/24", "served": "2020/21", "gap_periods": 3}
    assert W.coverage_band(lvl) == 2, "the numeric floor: never pushed into the text tier"
    # an EMPTY gap (every live card, every undeclared card) moves nothing
    b.state.period_gap = {}
    assert W.coverage_band(b) == 0
    # the row is still in the loud set when the cut reaches it -- demoted, never removed
    assert {r.driver_id for r in W.loud_set([a, b], loud_k=2)} == {"area", "crush"}


def test_F1_the_WALK_stamps_the_gap_from_its_OWN_served_rows_before_the_rank_and_never_from_a_calendar(
        monkeypatch):
    """THE 09-23 VERIFIER'S F1, END TO END THROUGH `walk`: the gap the rank demotes on is stamped in stage 1
    from the states wave 1 SERVED, and only where a sibling series of the SAME slug on the SAME card came
    back holding a NEWER period as known at the as-of. The soybeans board: US area held MY2020 while the
    Thailand imports series held MY2021 -> area is gapped and sits below the present. The FCOJ board
    today: every PSD series holds MY2025 and no MY2026 was printed -> NO gap, whatever the card's calendar
    pair says, and the loud area row leads."""
    from leviathan.graphrag import citations as _cit
    monkeypatch.setattr(_cit, "_card_fields", lambda t, m: (
        {"period_first_known": {"anchor": "period_start", "offset_months": 6}} if t == "silver_psd" else {}))

    def _psd(ref, slug, year, kd, z):
        return StateRow(key=SeriesKey(ref=ref, commodity=slug), status="ok", coverage_tier="series",
                        table="silver_psd", metric=ref, cadence="annual", level=1.0, level_date=year,
                        knowledge_date=kd, z={"value": z, "window_n": 20}, reads=1)

    def _board(slug, years, asof):
        ds = [_driver("area", silver_ref="area", silver_status="available"),
              _driver("imports", silver_ref="imports", silver_status="available"),
              _driver("crush", silver_ref="crush", silver_status="available")]
        spec = {"area": _psd("area", slug, years[0], "2024-01-12", 2.4),
                "imports": _psd("imports", slug, years[1], "2023-09-12", 0.1),
                "crush": _state("crush", z=0.3, pct=60.0)}
        return W.walk(graph=_graph(**{slug: cs.CausalContract(contract=slug, drivers=ds)}), asof=asof,
                      mode="max", anchors=(B.Anchor(contract=slug, source="named"),),
                      state_fn=lambda ref, node: spec[ref], key_fn=_key_fn(), receipts={}, stage2=False)

    bd = _board("soybeans_cbot", ("2020", "2021"), "2024-03-01")
    area = bd.row("soybeans_cbot", "area")
    assert area.state.period_gap == {"expected": "2021", "served": "2020", "gap_periods": 1}
    assert bd.row("soybeans_cbot", "imports").state.period_gap == {}
    assert W.coverage_band(area) == 1
    assert [k[1] for k in bd.order].index("crush") < [k[1] for k in bd.order].index("area")
    oj = _board("frozen_orange_juice", ("2025", "2025"), "2026-09-24")
    assert oj.row("frozen_orange_juice", "area").state.period_gap == {}
    assert W.coverage_band(oj.row("frozen_orange_juice", "area")) == 0
    assert [k[1] for k in oj.order][0] == "area", "no gap on the late printer: the loud row leads"


def test_W7_a_top_hop_whose_POLE_IS_ABSENT_declares_NO_DIRECTION_and_the_sign_swap_cannot_seat_it():
    """**THE MAX TURN's "COOL-PHASE SIDE" CHAIN** took the SIGN seat on a warm ONI: the chain's side was
    read off the series' run (ONI rising), which is the WARM pole's move, and the sign-diversity swap
    seats a chain by its SIDE whatever it scored -- so the tail rule alone lowers its score and leaves the
    seat. A pole that is not in force and carries no reading on its own side has no move: its chain is
    UNSETTLED, as an unmeasured top is, and its agreements with its neighbours are undetermined. A pole
    whose own reading is still inside its window (in transit) keeps HEAD's reading."""
    def _chain(top, last6):
        W.cache_clear()
        bd = _cboard()
        st = _oni_st(1.99, 95.0, 2.03, values=_oni_values(last6), dates=_ONI_DATES)
        _crow(bd, "a_cbot", top, lag="1-2 quarters", st=st, series_key=st.key.label())
        _crow(bd, "a_cbot", "bot", st=_cs("bot", pct=50))
        _cpath(bd, "a_cbot", [top, "bot"])
        _cfinish(bd)
        return W.chain_rows(bd, None, knobs=bd.knobs)["pool"][0]
    warm6 = (0.8, 1.1, 1.3, 1.6, 1.8, 1.99)
    cool = _chain("La_Nina", warm6)
    assert W._pole_absent(cool.hops[0]) and (cool.direction, cool.side) == ("unsettled", "unsettled")
    assert cool.agreements[0] == "undetermined", cool.agreements
    warm = _chain("El_Nino", warm6)
    assert not W._pole_absent(warm.hops[0]) and warm.side in ("for", "against"), warm.side
    transit = _chain("La_Nina", (-0.8, -0.3, 0.4, 1.0, 1.6, 1.99))
    assert transit.hops[0].phase_reoriented and not W._pole_absent(transit.hops[0])
    # 09-24 FIX ROUND (CONTRACT K13, RE-BANKED): a pole in transit keeps its OWN-POLE READING -- its tail
    # is scored on the window's cool extreme (round 1's W-7, unchanged) -- but the CHAIN whose first link
    # is the phase not in force carries a premise that is off: no direction, no asymmetry credit, no
    # seat. MEASURED on 09-24: max chain 3 (corn / La_Nina, a cool reading at the 33rd percentile still
    # inside its window at ONI +1.8) took a top seat at 71.6 on a positioning tail.
    assert transit.hops[0].chain_tail > 0.0, "the pole's own reading in its window is still scored"
    assert transit.premise_off is True and transit.side == "unsettled", (transit.premise_off,
                                                                         transit.side)
    assert transit.terms["asymmetry"] == 0.0, transit.terms
    assert warm.premise_off is False and cool.premise_off is True


def test_fix_0923_RA_M1_the_hop_carries_its_reads_own_collapse_from_the_SB1_row():
    """09-23 FIX ROUND, review RA M1: the chain line names the cell exactly as the SB-1 row does, so the
    walk stamps the READ'S OWN collapse (`StateRow.collapse`) on the hop at zero reads -- "" (one cell),
    "mean" (a mean over cells) -- and a row with no served state stamps None (no cell words, never a
    guess)."""
    W.cache_clear()
    bd = _cboard(asof="2026-09-07")
    for collapse in ("", "mean"):
        st = _cs("drought_" + (collapse or "one"), pct=95, z=2.03)
        st.collapse = collapse
        row = _crow(bd, "a_cbot", "drought_" + (collapse or "one"), st=st)
        assert W.chain_hop(bd, row).collapse == collapse
    bare = _crow(bd, "a_cbot", "no_series", st=None)
    assert W.chain_hop(bd, bare).collapse is None


# ═════════════════════════════════════════════════════════════════════════════════════════════════════
# THE 09-24 FIX ROUND, LANE W (CONTRACT K6 / K9 / K10 / K12 / K13 / K21 / K23 / K26; THREAT_MODEL W-1..W-9).
# Every pin is the drive its threat row names, offline and at zero cost. The real graph is read only
# where the bar is ABOUT the shipped graph (the question's reach); everything else is hand-built.
# ═════════════════════════════════════════════════════════════════════════════════════════════════════
def _ev(ed, prec, doc, text="an action"):
    return {"event_date": ed, "event_date_precision": prec, "date": doc, "text": text,
            "source": "src", "tier": 1}


@pytest.mark.parametrize("ed,prec,doc,want", [
    # W-1's table: precision x (the event's interval END <, =, > its document's date)
    ("2025-03-10", "day", "2025-03-19", True),       # a day before its document: realised
    ("2025-03-19", "day", "2025-03-19", True),       # the SAME day: realised (never a strict inequality)
    ("2025-03-20", "day", "2025-03-19", False),      # after its document: scheduled -- guidance
    ("2025-02-01", "month", "2025-03-19", True),     # Feb 2025 documented 19 Mar 2025: realised
    ("2025-03-01", "month", "2025-03-19", False),    # Mar 2025 documented 19 Mar: a straddle, not whole
    ("2025-01-01", "quarter", "2025-04-02", True),
    ("2025-01-01", "quarter", "2025-03-30", False),
    ("2025-01-01", "year", "2026-01-15", True),
    ("2026-01-01", "year", "2026-04-03", False),     # cotton E48: "during 2026", documented April 2026
    ("2025-02-01", "", "2025-03-19", False),         # NO PRECISION: no interval, never an action (K25's belt)
    ("2025-02-01", "month", "", False),              # NO DOCUMENT DATE: nothing to compare it to
])
def test_W0924_K6_REALISED_is_the_whole_interval_ending_on_or_before_its_document(ed, prec, doc, want):
    """CONTRACT K6 / OWNER DECISION O-6 (a): an action is a document reporting something that HAS
    HAPPENED -- the event's whole interval, at its declared precision, ends on or before the document's
    own date. It reads DATES AND THEIR PRECISION ONLY, never a word of the text (the hedge-word regex is
    the rejected lexical fix); both spellings of the three facts are read the same way."""
    assert W.realised(_ev(ed, prec, doc)) is want, (ed, prec, doc)
    cand = {"event_date": ed, "precision": prec, "document_date": doc}
    assert W.realised(cand) is want


def test_W0924_K6_a_SCHEDULED_or_CONDITIONAL_action_is_GUIDANCE_until_a_LATER_document_reports_it_done():
    """**O-6 REVISES ROUND 1's W-4** ("a scheduled policy action, effective after its document date, is an
    ACTION" -- the 2024-03-01 page served MPOC's "If the mandated biodiesel blend rate ... is raised to 15%
    from 10% beginning in April 2023", documented 2023-03-28, as a policy regime in force, EVENT 12). On a
    regime node the regime is the newest REALISED action; the scheduled statement is guidance, and it
    becomes the regime only when a later document reports it done."""
    band = parse_lag("0-2 quarters")
    sched = _ev("2025-03-10", "day", "2025-03-04", text="China will impose an additional tariff from 10 March")
    done = _ev("2025-03-10", "day", "2025-03-19", text="China imposed an additional 10 percent tariff")
    old = _ev("2018-07-06", "day", "2018-07-12", text="China imposed a 25 percent tariff")
    # (an event dated after the as-of is never a receipt at all -- the point-in-time rule -- so the as-of
    # here sits after the scheduled date and before any document reported it done)
    got = W.hop_event([sched], asof="2025-03-12", band=band, node_type="policy_event")
    assert got["kind"] == "guidance", got
    assert W.hop_event([sched], asof="2025-03-06", band=band, node_type="policy_event")["kind"] == "none"
    # the older REALISED action stays the regime while the new one is only scheduled
    got = W.hop_event([old, sched], asof="2025-03-12", band=band, node_type="policy_event")
    assert got["kind"] == "regime_in_force" and got["event_date"] == "2018-07-06", got
    # ...and the later document that REPORTS it done makes it the regime (W-3's own tariff document)
    got = W.hop_event([old, sched, done], asof="2026-09-23", band=band, node_type="policy_event")
    assert got["kind"] == "regime_in_force" and got["receipt"]["text"] == done["text"], got
    # THE MPOC CONDITIONAL on the 2024-03-01 board, through the real builder: never a regime
    mpoc = _ev("2023-04-01", "month", "2023-03-28",
               text="If the mandated biodiesel blend rate ... is raised to 15% from 10% beginning in April 2023")
    bd = _cboard(asof="2024-03-01")
    top = _crow(bd, "a_cbot", "biodiesel_mandate", lag="1-3 quarters", st=_cs("bm", pct=60))
    top.type = "policy_event"
    _crow(bd, "a_cbot", "bot", st=_cs("bot", pct=50))
    _cpath(bd, "a_cbot", ["biodiesel_mandate", "bot"])
    _cfinish(bd)
    ch = W.chain_rows(bd, None, knobs=bd.knobs,
                      receipts={("a_cbot", "biodiesel_mandate"): [mpoc]})["pool"][0]
    assert ch.event_kind != "regime_in_force" and ch.terms["event"] < 12, (ch.event_kind, ch.terms)
    # ...and with NO precision (the 09-24 served state: 393 of 393 hops) it is a dated report, never a regime
    bd2 = _cboard(asof="2024-03-01")
    top2 = _crow(bd2, "a_cbot", "biodiesel_mandate", lag="1-3 quarters", st=_cs("bm2", pct=60))
    top2.type = "policy_event"
    _crow(bd2, "a_cbot", "bot", st=_cs("bot2", pct=50))
    _cpath(bd2, "a_cbot", ["biodiesel_mandate", "bot"])
    _cfinish(bd2)
    ch2 = W.chain_rows(bd2, None, knobs=bd2.knobs,
                       receipts={("a_cbot", "biodiesel_mandate"): [dict(mpoc, event_date_precision="")]}
                       )["pool"][0]
    assert ch2.event_kind in ("report_in_reach", "report_outside", "none"), ch2.event_kind
    assert ch2.hops[0].event_interval == (), ch2.hops[0].event_interval


def test_W0924_K6_the_TARIFF_hop_prints_its_DOCUMENT_date_unplaced_and_its_MONTH_when_placed():
    """THE 09-24 TARIFF TURN: "2025-02-01" with NO precision (the US order's date, a Saturday) printed as the
    DAY China announced its tariff, regime_in_force, EVENT 12. Rule 1 of `hop_event`: an unplaced date is a
    dated report read at its DOCUMENT date, and the trace words carry that date alone. With K25's
    precision restored (month) and a document of 19 March 2025 the action is realised and IS the regime,
    worded at its precision -- never as a day the document did not write."""
    def _board(prec):
        bd = _cboard(asof="2026-09-24")
        top = _crow(bd, "a_cbot", "China_import_tariff", lag="0-2 quarters", st=_cs("tf_" + prec, pct=60))
        top.type = "policy_event"
        _crow(bd, "a_cbot", "bot", st=_cs("bot_" + prec, pct=50))
        _cpath(bd, "a_cbot", ["China_import_tariff", "bot"])
        _cfinish(bd)
        rc = _ev("2025-02-01", prec, "2025-03-19", text="an additional 10 percent tariff on soybeans")
        return W.chain_rows(bd, None, knobs=bd.knobs,
                            receipts={("a_cbot", "China_import_tariff"): [rc]})["pool"][0]
    unplaced = _board("")
    # the hop reads a dated REPORT (outside the 0-2 quarter window at this as-of), so the chain carries
    # no realised action from this draw -- the page's CHAIN_NO_RECEIPT, the draw law K6 keeps
    assert unplaced.hops[0].event_kind in ("report_in_reach", "report_outside"), unplaced.hops[0].event_kind
    assert unplaced.event_kind != "regime_in_force" and unplaced.terms["event"] < 12, unplaced.event_kind
    assert unplaced.hops[0].event_interval == ()
    assert "2025-02-01" not in unplaced.receipt_words, unplaced.receipt_words
    placed = _board("month")
    assert placed.event_kind == "regime_in_force" and placed.terms["event"] == 12, placed.event_kind
    assert "February 2025" in placed.receipt_words and "2025-02-01" not in placed.receipt_words, \
        placed.receipt_words
    assert placed.hops[0].event_interval == ("2025-02-01", "2025-02-28")


# ── K9: THE QUESTION'S REACH ─────────────────────────────────────────────────────────────────────────
#: THE TEN 09-24 PAYLOAD QUESTIONS: the markets each named (== the planner's seeds on all ten) and the
#: subject picks the resolver's planner made, read off `state_board.subject.picked` of each served trace
#: (resmoke_0924/answers/*.trace.json). Data from the served turns, never a rule.
_PAYLOAD_QUESTIONS = {
    "tariff": (("soybeans_cbot",), ("China_import_tariff", "us_export_pace", "import_arrivals")),
    "asof_2024": (("soybeans_cbot",), ("conab_production_revision", "export_pace_lag", "Brazil_export_tax")),
    "deep_2026": (("soybeans_cbot",), ("brazil_soybean_supply", "crop_condition")),
    "max_2026": (("soybeans_cbot",), ("brazil_soybean_supply", "crop_condition")),
    "cocoa": (("cocoa",), ("psd_ending_stock_su_ratio", "grind_demand")),
    "cotton": (("cotton",), ("ending_stocks_su_ratio", "us_export_pace")),
    "rice": (("rough_rice_cbot",), ("ending_stocks_su_ratio", "US_acreage_shift", "export_pace_lag")),
    "corn_wheat": (("corn_cbot", "soft_red_winter_wheat_cbot"), ("ending_stocks_su_ratio", "wheat_corn_spread")),
    "palm_rape": (("french_rapeseed_matif", "malaysian_crude_palm_oil_cme"),
                  ("ending_stocks_su_ratio", "soyoil_palm_premium")),
    "soyoil_palm": (("malaysian_crude_palm_oil_cme", "soybean_oil_cbot"), ("soyoil_palm_premium",)),
}
#: The boards the 09-24 turns anchored that NO turn's question reaches (CONTRACT K9's measurement).
_FOREIGN = ("arabica_coffee", "brazilian_arabica_coffee", "campinas_corn_reference_bmf")


def test_W0924_K9_the_REACH_is_the_question_markets_and_the_boards_that_DRIVE_them(real):
    """CONTRACT K9's measured table, re-derived from the shipped graph: distance 0 is the named and
    planned markets, distance 1 every loaded board a declared cross edge makes a DRIVER of one of them
    (`graph.cross_links`), NEVER a board a question market cascades INTO (`graph.rev_cross_links`)."""
    reach = dict(W.question_reach(real, named=("cocoa",)))
    assert reach == {"cocoa": 0}, reach
    soy = dict(W.question_reach(real, named=("soybeans_cbot",)))
    assert soy == {"soybeans_cbot": 0, "corn_cbot": 1, "malaysian_crude_palm_oil_cme": 1,
                   "rapeseed_meal_zce": 1, "rapeseed_oil_zce": 1, "soybean_meal_cbot": 1,
                   "soybean_oil_cbot": 1, "sunflower_oil": 1}, soy
    # the board soybeans cascades INTO is not in its reach -- reverse edges only
    rev = {str(e.get("contract")) for e in real.rev_cross_links("soybeans_cbot")}
    assert "campinas_corn_reference_bmf" in rev and "campinas_corn_reference_bmf" not in soy
    cw = dict(W.question_reach(real, named=("corn_cbot", "soft_red_winter_wheat_cbot")))
    assert cw["corn_cbot"] == cw["soft_red_winter_wheat_cbot"] == 0
    assert cw.get("barley") == 1 and cw.get("sorghum") == 1, cw        # declared corn drivers
    for name, (named, _picks) in _PAYLOAD_QUESTIONS.items():
        r = dict(W.question_reach(real, named=named, planned=named))
        assert not (set(r) & set(_FOREIGN)), (name, sorted(set(r) & set(_FOREIGN)))
        assert all(r[n] == 0 for n in named), (name, r)
    # zero reads, deterministic, and an unknown market keeps its seat alone
    assert W.question_reach(real, named=("soybeans_cbot",)) == W.question_reach(real, named=("soybeans_cbot",))
    assert W.question_reach(real, named=("no_such_board",)) == (("no_such_board", 0),)


@pytest.mark.parametrize("name", sorted(_PAYLOAD_QUESTIONS))
def test_W0924_K9_the_ten_payload_questions_anchor_ONLY_inside_their_reach(real, name):
    """**THE LIT RESOLVER ANCHORED THE ALPHABET** (09-24, item 15): cocoa, cotton and rice anchored
    arabica_coffee, brazilian_arabica_coffee, barley, campinas_corn_reference_bmf and canola_ice; the top
    chain on cocoa and rice was Brazilian arabica into robusta; the soybean subject seat was a safrinha
    corn chain. Re-planned with the served picks: every anchor sits in the question's reach, the named
    market leads and is never cut, and no foreign board is an anchor on any turn (THREAT W-3 / B17)."""
    named, picks = _PAYLOAD_QUESTIONS[name]
    reach = dict(W.question_reach(real, named=named, planned=named))
    anchors = W.resolve_anchors(graph=real, contracts=list(named), named=named, subject=picks,
                                max_contracts=2)
    slugs = [a.contract for a in anchors]
    assert set(slugs) <= set(reach), (name, sorted(set(slugs) - set(reach)))
    assert not (set(slugs) & set(_FOREIGN)), (name, slugs)
    assert set(named) <= set(slugs) and all(a.named for a in anchors if a.contract in named), slugs
    assert all(a.distance == reach[a.contract] for a in anchors), [(a.contract, a.distance) for a in anchors]
    # the question's own markets LEAD the anchor order
    assert slugs[:len(named)] == [s for s in slugs if s in named], slugs
    if name == "cocoa":
        assert slugs == ["cocoa"], slugs
    # with NO subject the anchor set is S6's own and carries no distance (B4)
    bare = W.resolve_anchors(graph=real, contracts=list(named), named=named, max_contracts=2)
    assert all(a.distance is None for a in bare) and all(not a.group for a in bare)


def test_W0924_K9_the_board_carries_its_REACH_and_the_trace_names_it_only_when_the_resolver_ran(real):
    """`Board.question_reach` is re-derived by the walk from its own anchors' distance-0 set, and only
    where `resolve_anchors` stamped one; the trace's `subject` payload carries it (and the subject's
    standing) only where the resolver ran -- a flag-off board's trace is byte for byte HEAD's."""
    from leviathan.graphrag.state import __main__ as H
    named, picks = _PAYLOAD_QUESTIONS["cocoa"]
    on = W.resolve_anchors(graph=real, contracts=list(named), named=named, subject=picks)
    bd = W.walk(graph=real, asof=H.ASOF, mode="quick", anchors=on, question="how tight is cocoa",
                state_fn=_flat_state_fn(), key_fn=_key_fn(), receipts={}, stage2=False)
    assert bd.question_reach == (("cocoa", 0),), bd.question_reach
    bd.subject = {"hints": {"exact": [], "alias": [], "candidates": []}, "picked": list(picks),
                  "groups": {}, "source": "subject", "vs_focus": ""}
    W.stage2(bd, real, state_fn=_flat_state_fn(), key_fn=_key_fn(), receipts={})
    tr = bd.trace()["subject"]
    assert tr["reach"] == [["cocoa", 0]], tr
    assert tr["tiers"] == {"psd_ending_stock_su_ratio": "semantic", "grind_demand": "semantic"}, tr
    assert tr["single_market"] is True
    off = W.walk(graph=real, asof=H.ASOF, mode="quick",
                 anchors=W.resolve_anchors(graph=real, contracts=list(named), named=named),
                 question="how tight is cocoa", state_fn=_flat_state_fn(), key_fn=_key_fn(),
                 receipts={})
    assert off.question_reach == () and off.subject_reach == {} and "subject" not in off.trace()


class _PickGraph:
    """The two accessors `subject_standing` reads -- `contracts` and `driver(contract, id)` -- over a
    `{slug: (driver ids)}` table. Hand-built, offline."""

    def __init__(self, boards):
        self._b = {k: set(v) for k, v in boards.items()}
        self.contracts = {k: None for k in boards}

    def driver(self, contract, did):
        if did in self._b.get(contract, ()):
            return object()
        raise KeyError((contract, did))


def _subject_board(*, anchors, reach, picked, hints, groups=None, n=6):
    bd = _slot_board(anchors=anchors, horizon=None, n=n)
    bd.question_reach = tuple(reach)
    bd.subject = {"hints": dict(hints), "picked": list(picked), "groups": dict(groups or {}),
                  "source": "subject", "vs_focus": ""}
    return bd


def test_W0924_O5_a_SEMANTIC_pick_does_NOT_seat_on_a_SINGLE_market_question_and_seats_LABELLED_otherwise():
    """OWNER DECISION O-5 (the 2024-03-01 PM read, M2: a cosine-only pick for a question that names no
    driver seated a subject chain): on a single-market question a pick the question's own words did not
    name -- exact [] and alias [] across its group -- does not seat (the slot reads `not_asked`); a
    lexical pick seats as before; on a multi-market question a semantic pick seats and its chain carries
    `subject_tier == "semantic"`, which the seat label reads ("the driver this question was resolved
    to")."""
    g = _PickGraph({"a_cbot": ["t5"]})
    sub = B.Anchor(contract="a_cbot", source="subject", driver_id="t5", subject=True, named=True,
                   group=("t5",), distance=0)
    # single market, semantic pick -> not seated, not_asked
    bd = _subject_board(anchors=(sub,), reach=(("a_cbot", 0),), picked=["t5"],
                        hints={"exact": [], "alias": [], "candidates": [["t5", 0.6, "id"]]})
    bd.subject_reach = W.subject_standing(bd, g)
    assert bd.subject_reach["tiers"] == {"t5": "semantic"} and bd.subject_reach["single_market"]
    _cfinish(bd)
    got = W.chain_rows(bd, g, knobs=bd.knobs)
    assert got["counts"]["slot_state"]["subject"] == "not_asked", got["counts"]["slot_state"]
    assert got["counts"]["slot_subject"] == 0
    # single market, ALIAS pick -> seated, labelled lexical
    bd = _subject_board(anchors=(sub,), reach=(("a_cbot", 0),), picked=["t5"],
                        hints={"exact": [], "alias": ["t5"], "candidates": []})
    bd.subject_reach = W.subject_standing(bd, g)
    _cfinish(bd)
    got = W.chain_rows(bd, g, knobs=bd.knobs)
    assert got["counts"]["slot_state"]["subject"] == "seated", got["counts"]["slot_state"]
    seat = next(c for c in got["rendered"] if c.slot == "subject")
    assert seat.subject_tier == "alias"
    # TWO markets, semantic pick -> seated, labelled semantic
    bd = _subject_board(anchors=(sub, B.Anchor(contract="z_cbot", source="named", named=True, distance=0)),
                        reach=(("a_cbot", 0), ("z_cbot", 0)), picked=["t5"],
                        hints={"exact": [], "alias": [], "candidates": [["t5", 0.6, "id"]]})
    bd.subject_reach = W.subject_standing(bd, g)
    assert bd.subject_reach["single_market"] is False
    _cfinish(bd)
    got = W.chain_rows(bd, g, knobs=bd.knobs)
    seat = next(c for c in got["rendered"] if c.slot == "subject")
    assert seat.subject_tier == "semantic" and seat.to_dict()["subject_tier"] == "semantic"


def test_W0924_K9_a_pick_with_NO_carrier_in_reach_DECLINES_visibly_and_a_subject_chain_needs_a_question_market():
    """W-4: the resolver never goes dark SILENTLY. A pick whose group no reach board carries is declined
    `not_on_question_markets` (trace) and the slot reads `no_candidate`. And a chain carrying the subject
    on a distance-1 board that neither sits on nor runs into a question market answers no subject seat."""
    g = _PickGraph({"a_cbot": ["t0", "t1", "t2", "t3", "t4", "t5"], "far_cbot": ["x_id"]})
    named = B.Anchor(contract="a_cbot", source="named", named=True, distance=0)
    bd = _subject_board(anchors=(named,), reach=(("a_cbot", 0),), picked=["x_id"],
                        hints={"exact": ["x_id"], "alias": [], "candidates": []})
    bd.subject_reach = W.subject_standing(bd, g)
    assert bd.subject_reach["declined_picks"] == ["x_id"]
    assert bd.subject_reach["declined"] == "not_on_question_markets"
    _cfinish(bd)
    got = W.chain_rows(bd, g, knobs=bd.knobs)
    assert got["counts"]["slot_state"]["subject"] == "no_candidate"
    assert bd.trace()["subject"]["declined"] == "not_on_question_markets"
    # ...and a SEMANTIC pick declined on a single-market question is O-5's "not asked" on the slot, the
    # decline still on the trace
    bd = _subject_board(anchors=(named,), reach=(("a_cbot", 0),), picked=["x_id"],
                        hints={"exact": [], "alias": [], "candidates": [["x_id", 0.6, "id"]]})
    bd.subject_reach = W.subject_standing(bd, g)
    _cfinish(bd)
    assert W.chain_rows(bd, g, knobs=bd.knobs)["counts"]["slot_state"]["subject"] == "not_asked"
    assert bd.trace()["subject"]["declined"] == "not_on_question_markets"
    # THE DISTANCE-0 TEST, at the unit: a subject chain on a distance-1 board with no cross into a
    # question market does not answer the subject; the same chain onto one does
    c = W.Chain(contract="d1_cbot", hops=(W.ChainHop(contract="d1_cbot", driver_id="s"),
                                           W.ChainHop(contract="d1_cbot", driver_id="b")),
                terminal="d1_cbot")
    ids = {"d1_cbot": frozenset({"s"})}
    assert W._slot_subject(c, ids) is True                     # HEAD's test: no reach, no bound
    assert W._slot_subject(c, ids, frozenset({"q_cbot"})) is False
    c.terminal = "q_cbot"
    assert W._slot_subject(c, ids, frozenset({"q_cbot"})) is True


# ── K10: THE LAST LINK'S VERDICT ─────────────────────────────────────────────────────────────────────
def _cross_board(*, bot_sign="+", cross_sign="+", tape_delta=None, far_row=None, earned_delta=-5.0,
                 far_is_bot_series=False):
    """a_cbot: top -> bot, one EARNED cross onto b_cbot. The cross is earned by an UNRELATED shared
    driver (`shared`, read on b_cbot and moving against), which is exactly the reading HEAD signed the
    last link against. `far_row` = (sign, delta) of the far board's row of the SAME driver as the last
    hop; `tape_delta` = the far contract's own tape move."""
    from leviathan.graphrag.state.rows import TapeState
    bd = _cboard(asof="2026-09-07")
    _crow(bd, "a_cbot", "top", st=_cs("top", pct=95))
    bot = _crow(bd, "a_cbot", "bot", sign=bot_sign, st=_cs("bot", pct=50))
    _crow(bd, "a_cbot", "shared", st=_cs("shared", pct=60))
    _cpath(bd, "a_cbot", ["top", "bot"])
    shared_far = _cs("shared_far", pct=90, changes=[{"window": "1m", "delta": earned_delta}])
    bd.series[shared_far.key.label()] = shared_far
    fan = [{"contract": "a_cbot", "driver_id": "shared", "loud": True,
            "far": [{"contract": "b_cbot", "driver_id": "shared", "sign": "+", "state_read": True,
                     "series_key": shared_far.key.label(), "free": False, "ref": "shared_far"}]}]
    if far_row is not None:
        fsign, fdelta = far_row
        if far_is_bot_series:
            fkey = bot.series_key
        else:
            fst = _cs("bot_far", pct=40, changes=[{"window": "1m", "delta": fdelta}])
            bd.series[fst.key.label()] = fst
            fkey = fst.key.label()
        fan.append({"contract": "a_cbot", "driver_id": "bot", "loud": True,
                    "far": [{"contract": "b_cbot", "driver_id": "bot", "sign": fsign, "state_read": True,
                             "series_key": fkey, "free": False, "ref": "bot_far"}]})
    bd.fan = fan
    bd.edges = [{"anchor": "a_cbot", "direction": "reverse", "other": "b_cbot", "sign": cross_sign,
                 "relation": "substitutes_for", "lag": "0-2 quarters", "lag_band": parse_lag("0-2 quarters")}]
    if tape_delta is not None:
        bd.tape["b_cbot"] = TapeState(slug="b_cbot", status="ok", level=100.0,
                                      changes=[{"window": "1d", "delta": tape_delta}])
    _cfinish(bd)
    pool = W.chain_rows(bd, None, knobs=bd.knobs)["pool"]
    return next(c for c in pool if c.cross), next(c for c in pool if not c.cross)


def test_W0924_K10_the_last_link_reads_the_FAR_TAPE_then_the_SAME_DRIVER_then_NOTHING():
    """**17 OF 25 RENDERED CHAINS SIGNED THE LAST LINK AGAINST AN UNRELATED FAR READING** (09-24, item 16)
    -- the far board's best-seated shared driver that earned the cross (China's beginning stocks under a
    US stocks-to-use hop; the ONI under a fertilizer hop). The earned cross's reading moves AGAINST in
    every case below and decides nothing: the verdict reads the far contract's own tape, else the far
    board's row of the SAME driver as the last hop, else settles nothing (THREAT W-5)."""
    tape, _ = _cross_board(tape_delta=+2.0, far_row=("-", -3.0))
    assert tape.terminal_reading["source"] == "tape", tape.terminal_reading
    assert tape.agreements[-1] == "aligned", tape.agreements        # bot +1, tape +2, sign (+)(+)
    same, _ = _cross_board(far_row=("-", -3.0))
    assert same.terminal_reading["source"] == "same_driver", same.terminal_reading
    # the relation to a far SAME-DRIVER row composes the far board's own declared sign: (+)(+)(-) = -;
    # bot +1 against a far move of -3 under "-" is aligned
    assert same.terminal_reading["sign"] == "-" and same.agreements[-1] == "aligned", same.agreements
    none, _ = _cross_board()
    assert none.terminal_reading["source"] == "undetermined" and none.agreements[-1] == "undetermined"
    # the far row reading the last hop's OWN series is the series against itself: no verdict
    ident, _ = _cross_board(far_row=("+", 1.0), far_is_bot_series=True)
    assert ident.terminal_reading["source"] == "undetermined", ident.terminal_reading
    assert ident.agreements[-1] == "undetermined"
    # the earned cross stays a REACH fact on the chain, never a verdict input
    assert none.cross["far_series_key"] == "shared_far||" and none.cross["far_driver_id"] == "shared"
    for c in (tape, same, none, ident):
        assert c.to_dict()["terminal_reading"] == dict(c.terminal_reading)


def test_W0924_K10_the_last_links_DECLARED_relation_is_the_COMPOSED_sign():
    """The cross edge says how the ANCHOR moves the far market; the last hop moves the anchor by its own
    sign; the relation the page prints between the last hop and the far market is the PRODUCT (the same
    telescoping `chain_declared_sign` states). HEAD stored the cross sign alone: the 09-24 tariff page
    read "the stocks-to-use link is expected to move the Dalian contract in the opposite direction" where
    the model's two declarations compose to the SAME direction. A declared "no committed direction"
    anywhere keeps its own word."""
    neg, _ = _cross_board(bot_sign="-", cross_sign="-", tape_delta=1.0)
    assert neg.edge_signs[-1] == "+", neg.edge_signs
    pos, _ = _cross_board(bot_sign="-", cross_sign="+", tape_delta=1.0)
    assert pos.edge_signs[-1] == "-", pos.edge_signs
    zero, _ = _cross_board(bot_sign="-", cross_sign="0", tape_delta=1.0)
    assert zero.edge_signs[-1] == "0" and zero.agreements[-1] == "undetermined"
    assert W.composed_sign("-", "-") == "+" and W.composed_sign("+", "0") == "0"
    assert W.composed_sign("+", "") == "" and W.composed_sign("-", "+", "-") == "+"
    # the no-cross terminal keeps HEAD's reading: the hop's own sign, undetermined
    _, base = _cross_board(bot_sign="-", tape_delta=1.0)
    assert base.edge_signs[-1] == "-" and base.agreements[-1] == "undetermined"
    assert base.terminal_reading == {}


# ── K12: ONE SERIES, ONE LINK ────────────────────────────────────────────────────────────────────────
def test_W0924_K12_a_chain_NEVER_walks_one_series_twice():
    """**MAX CHAINS 1-2 WALKED `soybean_crush_margin -> board_crush`** -- two driver ids on ONE series
    (`cbot_board_crush_margin|_global|`, level 2.6038, the 91.58th percentile both), the link between them
    "aligned" by construction and counted as an agreeing hop. Consecutive hops on one series are one
    link: the second id rides `ChainHop.aliases`, no agreement is computed between a series and itself,
    the depth is the real link count, a path that folds to one link is no chain, and every fold is
    counted (THREAT W-6: distinct series never fold)."""
    bd = _cboard(asof="2026-09-07")
    crush = _cs("cbot_board_crush_margin", pct=92)
    _crow(bd, "a_cbot", "crude_oil", st=_cs("brent", pct=68))
    _crow(bd, "a_cbot", "soybean_crush_margin", st=crush, series_key=crush.key.label())
    _crow(bd, "a_cbot", "board_crush", conf="medium", st=crush, series_key=crush.key.label())
    _crow(bd, "a_cbot", "su", st=_cs("su", pct=23))
    _cpath(bd, "a_cbot", ["crude_oil", "soybean_crush_margin", "board_crush"])
    _cpath(bd, "a_cbot", ["soybean_crush_margin", "board_crush"])
    _cpath(bd, "a_cbot", ["crude_oil", "soybean_crush_margin", "su"])
    _cfinish(bd)
    got = W.chain_rows(bd, None, knobs=bd.knobs)
    pool = got["pool"]
    folded = next(c for c in pool if c.hop_ids == ("crude_oil", "soybean_crush_margin"))
    assert folded.hops[1].aliases == ("board_crush",), folded.hops[1].aliases
    assert folded.depth == 1 and len(folded.agreements) == 2, (folded.depth, folded.agreements)
    assert folded.hops[0].series_key != folded.hops[1].series_key, "no link joins a series to itself"
    assert folded.to_dict()["hops"][1]["aliases"] == ["board_crush"]
    # the distinct-series path is untouched (W-6), and a one-series path is not a chain
    plain = next(c for c in pool if c.hop_ids == ("crude_oil", "soybean_crush_margin", "su"))
    assert all(not h.aliases for h in plain.hops) and plain.depth == 2
    assert not any(c.hop_ids == ("soybean_crush_margin",) for c in pool)
    assert got["counts"]["series_folded"] == 2 and got["counts"]["single_hop_paths"] == 1, got["counts"]
    # the fold at the unit: keyed on the SERIES; a hop with no series never folds into its neighbour
    a, b = W.ChainHop(contract="c", driver_id="a"), W.ChainHop(contract="c", driver_id="b")
    assert W.fold_series_hops((a, b)) == ((a, b), 0)


# ── K13: A PREMISE NOT IN FORCE NEVER TAKES A SEAT ───────────────────────────────────────────────────
@pytest.mark.parametrize("level,pct,z,last6,off", [
    (1.99, 95.0, 2.03, (0.8, 1.1, 1.3, 1.6, 1.8, 1.99), {"La_Nina"}),
    (-1.2, 5.0, -1.6, (-0.6, -0.8, -0.9, -1.0, -1.1, -1.2), {"El_Nino"}),
    # INSIDE THE LINE neither pole is in force, so a chain rooted on EITHER pole argues a phase that is not
    # happening: both premises are off (the brief's own proof -- soyoil's IOD_positive subject seat at IOD
    # -0.11 degC, inside its 0.4 band). The TAIL there is scored unsigned exactly as round 1 left it.
    (0.3, 60.0, 0.4, (0.1, 0.2, 0.25, 0.2, 0.3, 0.3), {"El_Nino", "La_Nina"})])
def test_W0924_K13_a_chain_ROOTED_on_the_pole_NOT_in_force_is_premise_off_and_takes_NO_seat(
        level, pct, z, last6, off):
    """**MAX CHAIN 3** (corn / La_Nina at ONI +1.8, `phase_in_force` False) took a TOP seat at 71.6 on a
    positioning tail, and soyoil's subject seat was IOD_positive, not in force. The round-1 phase fix
    reached the phase hop's own tail and words only. A chain whose FIRST hop is a declared pole NOT in
    force (`phase_in_force is False`: the other pole in force, or neither inside the line): `premise_off`,
    direction unsettled, no asymmetry credit, no seat of any kind, counted. A non-pole root never is
    (THREAT W-7). Read off the declared pair, never an id."""
    W.cache_clear()
    bd = _cboard(asof="2026-09-07", horizon=3)
    st = _oni_st(level, pct, z, values=_oni_values(last6), dates=_ONI_DATES)
    for did in ("El_Nino", "La_Nina"):
        _crow(bd, "a_cbot", did, lag="1-2 quarters", st=st, series_key=st.key.label())
    _crow(bd, "a_cbot", "pos", st=_cs("pos", pct=99.7, z=2.35))
    _crow(bd, "a_cbot", "plain", st=_cs("plain", pct=80))
    _cpath(bd, "a_cbot", ["La_Nina", "pos"])
    _cpath(bd, "a_cbot", ["El_Nino", "pos"])
    _cpath(bd, "a_cbot", ["plain", "pos"])
    _cfinish(bd)
    got = W.chain_rows(bd, None, knobs=bd.knobs)
    by_top = {c.hops[0].driver_id: c for c in got["pool"]}
    assert {d for d, c in by_top.items() if c.premise_off} == off, {d: c.premise_off for d, c in by_top.items()}
    for d in off:
        c = by_top[d]
        assert (c.direction, c.side) == ("unsettled", "unsettled")
        assert c.terms["asymmetry"] == 0.0 and not c.rendered and c.slot == "", (c.terms, c.slot)
        assert "subject" not in c.slot_fits and "horizon" not in c.slot_fits
    assert not by_top["plain"].premise_off                     # a non-pole root never is
    assert got["counts"]["premise_off"] == len(off)
    assert all(not c.premise_off for c in got["rendered"])


# ── K26: "THE SAME READING" IS ONE SERIES ────────────────────────────────────────────────────────────
def test_W0924_K26_every_far_row_says_whether_it_is_the_SAME_SERIES_and_a_phase_row_names_the_pole_in_force():
    """**"DECLARED ON THIRTEEN OTHER MARKETS, THE NEAREST BEING BARLEY"** (palm/rape) counted every card's
    OWN stocks-to-use ratio as "the same reading", and the deep turn's "thirty-four ... opposite on
    twenty-eight" read a La_Nina-keyed row's edges at ONI +1.8 (the ENSO sign inverted for palm). Each far
    row carries its zero-read series identity and `same_series`; a row naming the pole NOT in force names
    the pole that IS, so the reader is handed that pole's edges (THREAT W-9)."""
    W.cache_clear()
    bd = _cboard(asof="2026-09-07")
    st = _oni_st(1.8, 93.0, 2.4, values=_oni_values((0.8, 1.1, 1.3, 1.6, 1.8, 1.8)), dates=_ONI_DATES)
    ln = _crow(bd, "a_cbot", "La_Nina", st=st, series_key="oni_climate|_global|")
    su = _crow(bd, "a_cbot", "su", st=_cs("psd_su", pct=20), series_key="psd_su|a_cbot|")
    bd.fan = [{"contract": "a_cbot", "driver_id": "La_Nina", "loud": True,
               "far": [{"contract": "b_cbot", "driver_id": "La_Nina", "ref": "oni_climate", "series_key": ""},
                       {"contract": "c_cbot", "driver_id": "La_Nina", "ref": "", "series_key": ""}]},
              {"contract": "a_cbot", "driver_id": "su", "loud": True,
               "far": [{"contract": "b_cbot", "driver_id": "su", "ref": "psd_su", "series_key": ""}]}]
    g = _graph(b_cbot=cs.CausalContract(contract="b_cbot",
                                        drivers=[_driver("La_Nina", silver_ref="oni_climate"),
                                                 _driver("su", silver_ref="psd_su")]))
    W.fan_identity(bd, g, key_fn=_key_fn(), turn_kind="")
    oni_far, blank_far = bd.fan[0]["far"]
    assert oni_far["far_key"] == "oni_climate|_global|" and oni_far["same_series"] is True
    assert blank_far["far_key"] == "" and blank_far["same_series"] is False
    su_far = bd.fan[1]["far"][0]
    assert su_far["far_key"] == "psd_su|b_cbot|" and su_far["same_series"] is False, su_far
    assert bd.fan[0]["pole_in_force"] == "El_Nino" and bd.fan[1]["pole_in_force"] == ""
    # the PRICED key keeps its HEAD meaning: nothing here marks a far row read or priced
    assert all(not f.get("state_read") and not f["series_key"] for e in bd.fan for f in e["far"])
    assert ln.series_key and su.series_key


# ── K21: THE HORIZON ROW'S INPUT ─────────────────────────────────────────────────────────────────────
def test_W0924_K21_exactly_ONE_rendered_chain_answers_the_asked_horizon(chain_tiers):
    """The head's horizon row prints the OUTCOME of the chain answering the asked horizon (deep / max /
    2024 answered by direction only, while `chains[i].outcome.words` said "too thin for a middle figure").
    The producer names that chain -- the seated one, else the best-ranked rendered chain the slot's own
    test passes -- and its rank index among the rendered chains; no new statistic."""
    for mode in ("quick", "deep", "max"):
        bd = chain_tiers[mode]
        cc = bd.chain_counts
        ans = [c for c in bd.chains if c.answers_horizon]
        if cc["slot_state"]["horizon"] in ("seated", "answered_by_rank"):
            assert len(ans) == 1 and ans[0].rendered and ans[0].outcome, (mode, len(ans))
            ranked = sorted((c for c in bd.chains if c.rendered), key=lambda c: c.rank)
            assert ranked[cc["horizon_chain"]] is ans[0]
            assert W._slot_horizon(ans[0], bd.horizon_months)
        else:
            assert not ans and cc["horizon_chain"] == -1


# ── K23: THE STORE-PERIOD STAMP DEMOTES ONE BAND ─────────────────────────────────────────────────────
def test_W0924_K23_a_PERIOD_BEHIND_is_one_band_lower_exactly_as_a_period_gap_and_never_stacks():
    """The 2024-03-01 turn read the PSD MY2020 stocks-to-use as the March-2024 buffer while WASDE's
    2023/24 sat on the same page. Lane C stamps `StateRow.period_behind`; the rank demotes it one band --
    once, whether one stamp or both is present -- inside the numeric tier, never removing the row."""
    st = _cs("su", pct=5, z=-2.0)
    row = B.NodeRow(contract="a_cbot", driver_id="su", coverage_tier="series", state=st)
    assert W.coverage_band(row) == 0
    st.period_behind = {"held": "2020/21", "newer_on": "USDA WASDE", "newer": "2023/24"}
    assert W.coverage_band(row) == 1
    st.period_gap = {"held": "2020/21"}
    assert W.coverage_band(row) == 1, "the two stamps never stack"
    thin = _cs("su2", pct=None, z=None)
    thin.period_behind = {"held": "2020/21"}
    assert W.coverage_band(B.NodeRow(contract="a_cbot", driver_id="su2", coverage_tier="series",
                                     state=thin)) == 2


# ── 28c: THE TRACE'S TAIL WORDS TAKE THE EXTREME'S OWN VERB ──────────────────────────────────────────
def test_W0924_28c_a_TROUGH_bottomed_and_the_reading_is_the_hops_own_name():
    """The tariff trace read "export pace lag peaked at the 3rd percentile" for a TROUGH. The verb comes
    from `render.extreme_verb` -- the page's producer -- and the reading is named by
    `render.chain_hop_name`, the ONE printed hop name. Trace-only bytes."""
    from leviathan.graphrag.state import render as R
    trough = W.ChainHop(contract="a_cbot", driver_id="export_pace_lag", measured=True, percentile=43.0,
                        tail=0.14, tail_peak=0.95, tail_peak_percentile=2.6, tail_peak_date="2026-08-06")
    words = W._tail_words(trough)
    assert "bottomed at the 3rd percentile" in words and "peaked" not in words, words
    assert words.startswith(R.chain_hop_name(trough)), words
    peak = W.ChainHop(contract="a_cbot", driver_id="crude_oil", measured=True, percentile=68.0,
                      tail=0.36, tail_peak=0.96, tail_peak_percentile=98.1, tail_peak_date="2026-04-01")
    assert "peaked at the 98th percentile" in W._tail_words(peak)


def test_W0924_the_chain_trace_prose_stays_register_clean_at_ALL_THREE_TIERS(chain_tiers):
    """Every sentence the rendered chains carry on the trace after the 09-24 words (the record's names,
    the desk nouns, the extreme's verb) is clean on the round-1 trace table and leaks no raw id."""
    for mode in ("quick", "deep", "max"):
        for key, text in _chain_prose(chain_tiers[mode]):
            assert REG.internal_leaks(text) == [], (mode, key, text)
            if key in ("history", "outcome", "notes.history", "notes.tail"):
                assert "firing" not in text, (mode, key, text)
