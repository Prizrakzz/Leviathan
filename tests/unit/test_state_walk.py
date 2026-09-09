"""THE WALK -- STATE ENGINE DESIGN sec 3 whole, plus 1.3, 1.5, 6.7 and sec 7. Sitting S2.

THE BARS THIS FILE OWNS (sec 10.2, the S2 row of sec 11): B1 the rectangle, B3 the budget and its
atomicity, B7 the shared driver, B8 upstream, B13 the tags, B16 ordering-not-verdict, B17 the two
stamped stages -- plus the anchor grammar of sec 16's two amendments and the priced cold-start read set.

EVERYTHING RUNS OFFLINE. The state producer, the key resolver and the executor are INJECTED, so no test
here opens a pg mirror, reaches Athena, spends a cent or reads an environment variable. Where a bar is
about a fact of the SHIPPED graph (B7's `-`/`+` split on El_Nino, B8's crude_oil path) the test loads
the REAL 36 curated DAGs, because a bar pinned against a synthetic graph would pin the fixture.
"""
import pytest
from leviathan.causal import schema as cs
from leviathan.graphrag import graph as G
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
    assert sum(1 for p in scan.paths if p["rendered"]) == 2
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
        assert set(win) == {"near", "state_date", "knowledge_date", "analog_dates"}


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
