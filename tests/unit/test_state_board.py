"""THE BOARD CONTAINER -- STATE ENGINE DESIGN sec 1.2, 3.1, 3.8, 3.9, 6.7 and sec 7's knob table.
Sitting S2.

Every test here is OFFLINE and has no clock beyond the as-of it is handed. The bars this file owns:
B1 (the rectangle), the B3 half that is a LEDGER property, B13 (the closed decline vocabulary) and the
sec 7 / sec 3.8 knob arithmetic the report states per mode.
"""
import dataclasses

import pytest
from leviathan.graphrag import reasoning_modes as rm
from leviathan.graphrag.state import board as B


# ═══ THE ONE CROSS-DECK CLAIM S7's QUICK CAPS MAKE ══════════════════════════════════════════════════
# `render_absence` -- the absence GROUP cap -- is the knob S6 minted and left at 0 = UNCAPPED on every
# tier, with its own docstring saying in as many words that "S7 decides which of them moves". It moved:
# SB-X is 23.2% of the quick block and the single largest class on it, so Scan now takes THREE groups
# and the two PAID tiers keep 0 (the owner's 09-10 ruling -- deep and max run UNCAPPED into arm A).
#
# THAT CHANGE IS READ BY A PIN IN ANOTHER LANE'S DECK, `test_state_seam.py`'s
# `test_the_render_caps_are_knobs_at_the_shipped_values_and_S7_decides`, which used to assert the
# literal `absence=0` on all three tiers. VERIFIED AT THIS LANDING: the seam lane has already corrected
# it to read `absence=kn.render_absence` and to assert the ratified SHAPE (quick > 0, deep and max == 0)
# as its own claim, and that deck is green. Nothing is owed.
#
# WHAT IS ASSERTED BELOW is the shape BOTH decks now rest on, from this side. S7's three new cap keys
# (`fan_names`, `projection`, `edge`) ride the `RENDER_CAPS` TABLE rather than being knob-only reads,
# precisely so `dict(R.RENDER_CAPS[mode], ...)` picks them up on its own and that pin's shape keeps
# matching without a second edit.
def test_the_ratified_S7_shape_is_SCAN_ONLY_and_both_decks_rest_on_it():
    """THE CROSS-DECK CLAIM IS AN ASSERTION, not a comment. If a later sitting caps deep or max, this
    reds HERE as well as in the seam deck -- which is the point: a cap that crept onto a paid tier
    would change the prompt of the very cell arm A is measuring, the one thing sec 10.3 forbids."""
    assert B.board_knobs_of("quick").render_absence == 3
    assert B.board_knobs_of("deep").render_absence == 0
    assert B.board_knobs_of("max").render_absence == 0
    # ...and the same claim for the three knobs S7 appended, INCLUDING the fan enumeration. Round 2
    # took deep's 24 back to 0: a bound on a name list inside one line is still a bound, and the paid
    # tiers are arm A's control cells.
    for mode in ("deep", "max"):
        kn = B.board_knobs_of(mode)
        assert (kn.render_fan_names, kn.render_projection, kn.render_edge) == (0, 0, 0)


# ── sec 7 + sec 3.8: the knob table IS the design's table ───────────────────────────────────────────
def test_the_nine_knobs_are_the_designs_own_nine_in_the_designs_own_order():
    """`(loud_k, fan_k, analog_k, analog_dims, board_admit_k, wave1, wave2, receipt_cap,
    path_render_k)` -- sec 7's declared order, which is also the order the `Mode` tuple takes at S6.
    A NamedTuple rather than a dict so a mistyped knob raises instead of returning None."""
    # S6 RE-ANCHOR, on its ONE named cause and WITHOUT loosening the join: the sitting appended
    # SEVEN RENDER CAPS after the design's nine, each with a default equal to the shipped render
    # table, so `BoardKnobs(*t)` over a nine-entry tuple still resolves. What sec 7 claims -- THESE
    # nine, in THIS order, FIRST -- is asserted exactly as before, one rung in.
    _NINE = ("loud_k", "fan_k", "analog_k", "analog_dims", "board_admit_k",
             "wave1", "wave2", "receipt_cap", "path_render_k")
    _S6_RENDER = ("render_spillover", "render_convergence", "render_analog",
                  "render_analog_outcomes", "render_receipts", "render_watch", "render_absence")
    # THE TWO BOUNDS THE S6 REVIEW APPENDED AFTER THE SEVEN. They are a different KIND of knob and
    # keep their own name here for that reason: every render cap above bounds a ROW CLASS, and both of
    # these bound a dimension no per-class cap can see -- the ANCHOR COUNT (measured 35 from one
    # `focus_driver` gesture, cap 106 against the design's 71) and the NAMES inside one absence line
    # (measured 23,871 characters).
    _S6R_BOUNDS = ("max_anchors", "render_absence_names")
    # S7 APPENDS THREE MORE, LAST, each with a default -- the three classes sec 7's Scan row never
    # budgeted and that a cap can reach: the fan index's ENUMERATION, the projection row, and the
    # seed's own edge line (minted dark, 0 on every tier, the number is S8's).
    _S7_CAPS = ("render_fan_names", "render_projection", "render_edge")
    assert B.BoardKnobs._fields[:9] == _NINE
    assert B.BoardKnobs._fields in (_NINE, _NINE + _S6_RENDER, _NINE + _S6_RENDER + _S6R_BOUNDS,
                                    _NINE + _S6_RENDER + _S6R_BOUNDS + _S7_CAPS)
    # every appended field carries a DEFAULT, which is what keeps a nine-tuple caller valid
    assert set(B.BoardKnobs._field_defaults) == set(B.BoardKnobs._fields[9:])


@pytest.mark.parametrize("mode,expect,render,bounds,s7", [
    ("quick", (8, 4, 0, 0, 4, 24, 0, 0, 1), (4, 1, 0, 0, 0, 3, 3), (4, 6), (8, 4, 0)),
    ("deep", (16, 8, 1, 3, 8, 32, 18, 3, 4), (8, 4, 1, 4, 3, 6, 0), (6, 24), (0, 0, 0)),
    ("max", (24, 16, 2, 5, 12, 40, 58, 5, 8), (16, 6, 2, 4, 5, 8, 0), (8, 32), (0, 0, 0)),
])
def test_every_shipped_tiers_knobs_are_the_values_sec_7_declares(mode, expect, render, bounds, s7):
    """S6 RE-ANCHOR: the NINE are asserted as a whole tuple; the SEVEN render caps appended after them
    are asserted separately AND against the tables `render.RENDER_CAPS` ships, so the claim "the
    defaults are the design's planned sizes, not a new opinion" is MEASURED rather than described.

    **S7 MOVES FIVE QUICK NUMBERS AND APPENDS THREE KNOBS**, on the owner's ratified rule of 09-10
    ("Scan (quick) gets render CAPS at S7; deep and max run UNCAPPED into arm A"). On QUICK:
    `path_render_k` 2 -> 1, `render_convergence` 2 -> 1, `render_absence` 0 -> 3,
    `render_absence_names` 16 -> 6, and `render_fan_names` 8 / `render_projection` 4 /
    `render_edge` 0 land. **DEEP AND MAX MOVE NOTHING AT ALL** (scoped in round 2): their render row is
    byte-identical to S6's and all three new knobs are 0/0/0 on both. The first cut gave deep a
    `render_fan_names` of 24 -- a bound on the ENUMERATION inside one line rather than on a row -- and
    that is still a cap the ratified rule did not grant a control cell. A cap arm A did not intend is a
    second flag in a one-flag experiment.

    THE MEASURED BASIS, so the numbers are not an opinion: the S4 board census put the QUICK block at
    53 lines / 13,648.5 chars / ~3,412.5 est tokens at the median of 36 boards, against sec 7's Scan
    sizing of ~17-20 lines / ~1,100 tokens -- 3.10x by tokens -- in front of a 105-154-word Scan writer
    budget. Deep measured 2.17x and max 1.72x."""
    kn = B.board_knobs_of(mode)
    assert tuple(kn)[:9] == expect
    assert tuple(kn)[9:] in ((), render, render + bounds, render + bounds + s7)
    assert (kn.render_fan_names, kn.render_projection, kn.render_edge) == s7
    # THE EDGE KNOB SHIPS DARK ON EVERY TIER. The mechanism lands at S7 and the NUMBER is S8's: an
    # SB-E line is what makes ruling 3 renderable, so cutting it decides what the reader is TOLD.
    assert kn.render_edge == 0
    if len(tuple(kn)) > 16:
        # THE ANCHOR CEILING IS A TIER NUMBER, and that is the whole point: without it the DECLARED
        # read cap, the serial tape column, the [N] address space and the block's own length all
        # scaled with a user gesture rather than with the tier the user bought.
        assert (kn.max_anchors, kn.render_absence_names) == bounds
        assert kn.max_anchors >= 1
    if len(tuple(kn)) > 9:
        from leviathan.graphrag.state import render as R
        from leviathan.graphrag.state import watch as WA
        shipped = R.RENDER_CAPS[mode]
        assert (kn.render_spillover, kn.render_convergence, kn.render_analog,
                kn.render_analog_outcomes, kn.render_receipts) == (
            shipped["spillover"], shipped["convergence"], shipped["analog"],
            shipped["analog_outcomes"], shipped["receipts"])
        assert kn.render_watch == WA.WATCH_RENDER_K[mode]
        # S7: `render_absence` is 0 = UNCAPPED on the two PAID tiers and THREE on Scan. The design
        # plans no absence number at all (sec 7 sizes states, spillovers, patterns, stanzas and watch
        # rows and stops), which is why this bound is a knob rather than a table row -- and why it is
        # asserted DERIVED here rather than as the literal 0 it used to be.
        assert kn.render_absence == (3 if mode == "quick" else 0)
        # ...and the knob is what the RENDER actually reads, so the two tables cannot drift
        assert R.render_caps(mode, kn) == dict(shipped, absence=kn.render_absence,
                                               absence_names=kn.render_absence_names)
        # EVERY TIER DECLARES EVERY KEY AND THE VALUE CARRIES THE ANSWER (round 2): on the paid tiers
        # all three S7 caps read 0, which this table declares as UNCAPPED. A missing key and a cap of
        # zero must not be two different things.
        if mode != "quick":
            assert (shipped["fan_names"], shipped["projection"], shipped["edge"]) == (0, 0, 0)
            assert shipped["rank_cuts"] == 0
        assert WA.render_k(mode, kn) == WA.WATCH_RENDER_K[mode]


def test_the_wave_2_columns_DERIVE_from_the_nine_knobs_and_reproduce_sec_3_8s_table():
    """Sec 3.8's table, re-derived rather than re-typed. `far` is the RESIDUAL against the DECLARED
    leg-B column, which is what makes the columns and the total incapable of disagreeing."""
    deep = B.wave2_shape(B.board_knobs_of("deep"), legb_cells=0, legb_on=False)
    assert (deep["far"], deep["analog_benchmark"], deep["analog_receipts"], deep["legb"]) == (12, 3, 3, 0)
    assert deep["total"] == 18                                     # 32 + 18 = 50
    hot = B.wave2_shape(B.board_knobs_of("max"), legb_cells=9, legb_on=True)
    assert (hot["far"], hot["analog_benchmark"], hot["analog_receipts"], hot["legb"]) == (16, 10, 5, 27)
    assert hot["total"] == 58                                      # 40 + 58 = 98


def test_darkening_leg_B_lowers_the_TOTAL_and_moves_no_other_column():
    """THE DEFECT THIS PINS WAS MEASURED, not imagined: the first cut of `wave2_shape` took only the
    cells, so a dark leg B made its column zero and the RESIDUAL handed those 27 reads to the far
    column -- Cascade priced 43 far keys against a design that says 16, i.e. a wave-2 budget 27 reads
    larger than its own "71 with leg B dark" line, arrived at silently. The declared cells set the
    residual; the rider sets whether the column is spent."""
    kn = B.board_knobs_of("max")
    dark = B.wave2_shape(kn, legb_cells=9, legb_on=False)
    assert dark["far"] == 16 and dark["legb"] == 0 and dark["legb_declared"] == 27
    assert dark["total"] == 31                                     # 40 + 31 = 71, sec 3.8's own figure
    assert dark["analog_benchmark"] == 10 and dark["analog_receipts"] == 5


def test_check_knobs_is_green_on_every_shipped_tier_and_red_on_an_overcommitted_one():
    for mode in ("quick", "deep", "max"):
        assert B.check_knobs(B.board_knobs_of(mode), legb_cells=B.legb_cells_of(mode)) == []
    over = B.BoardKnobs(16, 8, 2, 5, 8, 32, 4, 5, 4)               # wave2 4 < its own columns
    errs = B.check_knobs(over)
    assert errs and "over-committed" in errs[0]


def test_the_tier_table_is_keyed_on_the_BASE_preset_so_an_hp_twin_reads_its_own_tiers_board():
    """`deep_hp` is an ANALYSIS turn and must read the Analysis board. A table keyed by literal name
    would hand every `_hp` twin a None -- i.e. no board at all on exactly the turns an arm measures
    (the `is_metered` join, same reason, same function)."""
    for hp, base in rm.HANDLE_PROSE_PRESETS.items():
        assert rm.board_preset(hp) == rm.board_preset(base), hp
    assert rm.board_preset("deep_hp") == rm.board_preset("deep")


def test_a_dark_ARM_preset_whose_base_is_ITSELF_declares_no_board_and_that_is_NAMED():
    """MEASURED AND RECORDED rather than papered over. `base_mode` maps the four `_hp` twins and
    nothing else, so `quick_r0` / `quick_s` / `quick_n3` / `deep_v2` / `max_cc1` are their own bases and
    read NO board. That is harmless today -- arm A (S7) runs the board flag on `deep`, whose base is
    `deep` -- and it is a live hazard the day an arm runs a dark twin: such a preset must join
    `BOARD_PRESETS` in the same commit that mints it, the F8 leak fence's own shape. Inventing a
    tier-family join here instead would put a second, disagreeing base-preset resolver in the estate."""
    for name in (rm.QUICK_R0, rm.QUICK_S, rm.QUICK_N3, rm.DEEP_V2):
        assert rm.base_mode(name) == name
        assert rm.board_preset(name) is None, name


def test_standard_and_an_unknown_name_declare_NO_board():
    for name in (rm.STANDARD, None, "", "not_a_mode"):
        assert rm.board_preset(name) is None
        assert B.board_knobs_of(name) is None


# ── the DARKNESS fence: the knobs move nothing that ships ───────────────────────────────────────────
def test_the_board_knobs_move_NO_shipped_preset_and_NO_knob_dict():
    """DARK BY CONSTRUCTION, two ways. (1) The table is a module constant nothing on the serve path
    consults -- `state/` is imported by no serving module until the `board=` kwarg lands at S6.
    (2) `knobs()` is untouched, so no existing knob dict, trace stamp or eval `mode_knobs` column
    gains a key and `standard` stays the all-None passthrough."""
    assert rm.knobs(rm.STANDARD) == {}
    for name in rm.MODES:
        assert "board" not in rm.knobs(name), name
    assert all(getattr(rm.MODES[rm.STANDARD], f) is None for f in rm.KNOB_FIELDS)


def test_KNOB_FIELDS_gained_the_boards_field_AT_THE_TAIL_and_clause_iv_moved_with_it():
    """THE APPENDED-LAST LAW, and this sitting's deliberate non-application of it.

    Sec 7 asks for ONE appended `Mode` field `board: tuple | None` after `numbers_roster`. Appending it
    moves `KNOB_FIELDS[-1]`, and `config_check.check_scan_roster` clause (iv) asserts that literal BY
    NAME (`if _rm.KNOB_FIELDS[-1] != "numbers_roster"`), with its own docstring saying "THIS is the
    clause that owns the literal tail order". `config_check.py` is held for S6, which already edits it.
    So the knobs land as a module table now and the field appends at S6, in the same commit as clause
    (iv) and the two test tail pins -- whoever lands last owns the shift, and that is S6. THIS TEST IS
    THE MARKER: it fails the day the field lands without the clause moving with it."""
    # S6 LANDED IT. The pin keeps its whole subject -- the field is APPENDED, `numbers_roster` is
    # still named at a named position, and clause (iv) still owns the literal -- and it now asserts
    # the state the sitting produced instead of the state that preceded it.
    assert rm.KNOB_FIELDS[-1] == "board"
    assert rm.KNOB_FIELDS[-2] == "numbers_roster"
    from leviathan.graphrag import config_check as cc
    assert cc.check_scan_roster() == [] and cc.check_scan_tier() == []
    # ...and clause (iv) is the one that MOVED: it names the two-name tail by literal now, so a
    # third append that forgets it still reds rather than passing on a looser rule.
    import inspect
    assert '_KF_TAIL = ("numbers_roster", "board")' in inspect.getsource(cc.check_scan_roster)


# ── sec 6.7: the closed decline vocabulary ──────────────────────────────────────────────────────────
def test_every_leg_of_sec_6_7_has_its_own_closed_enum_and_no_two_share_a_list():
    assert set(B.LEG_REASONS) == {"series", "edge", "fan", "path", "interaction", "tape", "analog",
                                  "watch", "render", "board"}
    for leg, vocab in B.LEG_REASONS.items():
        assert vocab and len(set(vocab)) == len(vocab), leg
    assert B.OUTCOMES == ("fired", "declined", "not_reached")


def test_the_two_revision_1_series_reasons_are_STRUCK():
    """`replay` became a LABEL (D17) and `positioning_context_only` became one rule on the row (2.4).
    A decline where a label already exists is the suppress-not-correct shape the house grades FATAL."""
    assert "replay" not in B.SERIES_REASONS
    assert "positioning_context_only" not in B.SERIES_REASONS
    assert "depth_cap" not in B.PATH_REASONS          # rev 3: no depth is cut (D27)
    assert "0" not in B.EDGE_REASONS and B.EDGE_REASONS[0] == "sign_undeclared"


def test_a_stamp_outside_a_legs_own_enum_RAISES_at_the_stamp():
    bd = B.Board(asof="2026-09-07", mode="deep")
    bd.stamp("series", "declined", reason="thin_history:5")
    bd.stamp("path", "declined", reason="render_cap")
    with pytest.raises(ValueError):
        bd.stamp("series", "declined", reason="render_cap")        # another leg's word
    with pytest.raises(ValueError):
        bd.stamp("series", "declined", reason="invented_word")
    with pytest.raises(ValueError):
        bd.stamp("series", "skipped")                              # not one of the three outcomes
    with pytest.raises(ValueError):
        bd.stamp("path", "declined", reason="render_cap:2")        # a tail nobody declared


def test_not_reached_is_stamped_by_the_ORCHESTRATING_walk_and_never_overwrites_a_verdict():
    """A leg cannot stamp its own absence (sec 6.7) -- that is the hole the reading's 4.8 measured
    (`rv_reading_decline` None on 12 of 12 because the leg was never REACHED on 10)."""
    bd = B.Board()
    bd.stamp("series", "fired", reads=9)
    bd.stamp_not_reached("series", "analog", "watch")
    assert bd.legs["series"]["outcome"] == "fired"
    assert bd.legs["analog"] == {"outcome": "not_reached", "reason": None, "reads": 0}


def test_the_eval_fork_gate_reads_FIRED_only_and_a_candidate_still_rides_the_trace():
    """`_reroute`'s objection, answered (sec 6.7): the board separates TRACE from PROMPT. Every
    candidate's tag rides the trace; the prompt renders fired rows and NAMED absences only."""
    bd = B.Board()
    bd.stamp("fan", "declined", reason="fan_cap", reads=0)
    fired = [k for k, v in bd.trace()["legs"].items() if v["outcome"] == "fired"]
    assert fired == []
    assert bd.trace()["legs"]["fan"]["reason"] == "fan_cap"


# ── sec 1.2 / 3.8: the ledger, its rectangle and its ordering ───────────────────────────────────────
def test_B1_the_rectangle_closes_and_says_so_when_it_does_not():
    w = B.WaveLedger(1, reads_cap=24)
    w.plan_written(["a", "b"], declared=5, deferred=["c", "d", "e"])
    w.read = 2
    assert w.closed
    w.declined = 1
    assert not w.closed


def test_B3_the_plan_is_written_BEFORE_the_first_fetch_and_a_wave_that_never_fetched_is_clean():
    w = B.WaveLedger(2, reads_cap=18)
    assert w.priced_before_fetch                       # vacuously: nothing was fetched
    w.plan_written(["k"], declared=1)
    w.note_fetch()
    assert w.priced_before_fetch
    bad = B.WaveLedger(2)
    bad.note_fetch()
    bad.plan_written(["k"], declared=1)                # the plan arrived AFTER the read
    assert not bad.priced_before_fetch


def test_free_keys_count_as_READ_and_never_as_a_deferral():
    """A key the memo already holds costs nothing and cannot be the reason another key was dropped;
    calling it deferred would NAME a row the reader can plainly see (sec 3.8)."""
    w = B.WaveLedger(2, reads_cap=18)
    w.plan_written(["paid"], declared=3, deferred=(), free=["free1", "free2"])
    w.read = 3
    assert w.closed and w.deferred == 0 and len(w.free_keys) == 2


def test_the_board_rectangle_names_every_complaint_it_finds():
    bd = B.Board(mode="deep", knobs=B.board_knobs_of("deep"))
    bd.ledger.waves[1].reads_cap = 32
    bd.ledger.waves[1].plan_written(["a"], declared=2)
    bd.ledger.waves[1].read = 1                        # 2 != 1 + 0 + 0
    bd.ledger.waves[1].reads_used = 99                 # and over the cap
    problems = " ".join(bd.rectangle())
    assert "declared 2" in problems and "exceeds reads_cap" in problems


# ── sec 3.1: the anchor record ──────────────────────────────────────────────────────────────────────
def test_an_anchor_source_outside_the_closed_set_RAISES():
    B.Anchor(contract="soybeans_cbot", source="named")
    with pytest.raises(ValueError):
        B.Anchor(contract="soybeans_cbot", source="because_i_said_so")


def test_the_anchor_sources_are_in_PRECEDENCE_order_strongest_first():
    """An explicit gesture outranks the board (3.1); a driver anchor outranks a market the planner
    merely inferred; cold start is last because it is what happens when nothing else did.

    `subject` IS THE SUBJECT RESOLVER'S ONE WORD (D6, 2026-09-09), and its seat is the decision the
    pin exists to hold: BELOW `focus_driver`, because an FE attachment is a CLICK and a resolved
    subject is an INFERENCE about a typed phrase; ABOVE `named`, because a market the question names is
    context for the CAUSE it asks about. `Anchor.__post_init__` raises on any word not in this tuple,
    so the vocabulary edit is enforced at construction."""
    assert B.ANCHOR_SOURCES == ("attached_event", "focus_driver", "subject", "named",
                                "planner_inferred", "board_loudest")


def test_an_empty_anchor_set_reports_anchor_none():
    assert B.Board().anchor_source == "anchor_none"


# ── sec 3.9: what quantify is handed ────────────────────────────────────────────────────────────────
def test_the_board_request_carries_the_four_keys_sec_3_9_names_and_nothing_it_does_not():
    bd = B.Board(asof="2026-09-07", mode="max", knobs=B.board_knobs_of("max"),
                 anchors=(B.Anchor(contract="soybeans_cbot", source="named"),))
    req = bd.request()
    assert {"order", "windows", "calls", "budget"} <= set(req)
    assert set(req["budget"]) == {"spent", "cap", "ledger"}
    assert req["anchor_source"] == "named"


def test_net_reads_and_declared_cap_are_two_different_facts():
    """D12: the walk's ceiling gains the board's declared CAP when the payload is present, and
    `_cw_turn_spent` gains the board's SPEND as one enumerated term. ABSENT IS NEVER ZERO."""
    bd = B.Board(mode="deep", knobs=B.board_knobs_of("deep"))
    bd.ledger.waves[1].reads_cap, bd.ledger.waves[2].reads_cap = 32, 18
    bd.ledger.waves[1].reads_used = 11
    bd.ledger.tape_reads = 1
    assert bd.net_reads() == 12 and bd.declared_cap() == 50


def test_the_TAPE_read_has_a_declared_SEAT_so_the_S6_ceiling_can_never_UNDER_count():
    """MEASURED AT THE S2 REVIEW as an arithmetic hole waiting for D19: `reads_used` already counted
    `tape_reads` while `reads_cap` had no room for them, so the day the one-mirror-read-per-anchor-board
    lands, `net_reads()` exceeds `declared_cap()` by the anchor count -- silently, and in the direction
    that under-counts the D12 ceiling. `tape_cap` is that seat; it is 0 at this sitting because S2 reads
    no tape, and the sitting that mints an SB-T read declares it in the same edit."""
    bd = B.Board(mode="max", knobs=B.board_knobs_of("max"))
    bd.ledger.waves[1].reads_cap, bd.ledger.waves[2].reads_cap = 40, 31
    assert bd.declared_cap() == 71, "sec 3.8's own '71 with leg B dark', unmoved by the new seat"
    bd.ledger.tape_cap = 2                              # two anchor boards, one mirror read each (D19)
    bd.ledger.tape_reads = 2
    assert bd.declared_cap() == 73 and bd.net_reads() == 2 <= bd.declared_cap()


def test_read_empty_is_a_BARE_word_and_the_detail_set_is_only_what_sec_6_7_parametrises():
    """Sec 6.7 prints `thin_history:<n>`, `history_truncated:<limit>`, `scope_unresolved:<7 reasons>`,
    `changes_thin:<n>`, `percentile_thin:<n>` and `lane_off:<lane>` -- and `read_empty` BARE. The S2
    landing admitted `read_empty` to the detail set, which is the class this module exists to prevent:
    a word in the detail set is a word the S3 render owes a SECOND sentence, and nothing here ever
    stamped one. (`rows.STATUS_WITH_DETAIL` is a DIFFERENT set -- the feeder's STATUS vocabulary, where
    `read_empty:all_blank` is real -- and it is untouched.)"""
    assert "read_empty" in B.SERIES_REASONS and "read_empty" not in B.REASONS_WITH_DETAIL
    assert B.check_reason("series", "read_empty") is None
    assert B.check_reason("series", "read_empty:all_blank") is not None
    # `subject_ambiguous` IS THE SEVENTH (SUBJECT RESOLVER D5, 2026-09-09) and the FIRST whose detail
    # is not a count or a lane name: it carries two driver IDS, and `render.sb_subject_ambiguous` is
    # the SECOND SENTENCE this set's own rule demands -- it names both drivers in reader words and asks
    # the reader which they mean. Admitted with its render, which is the bar `read_empty` failed.
    assert B.REASONS_WITH_DETAIL == frozenset({
        "scope_unresolved", "thin_history", "history_truncated", "changes_thin", "percentile_thin",
        "lane_off", "subject_ambiguous"})
    assert B.check_reason("board", "subject_ambiguous:El_Nino|La_Nina") is None
    from leviathan.graphrag.state.rows import STATUS_WITH_DETAIL
    assert "read_empty" in STATUS_WITH_DETAIL, "the FEEDER's status set is a different set, unmoved"


def test_the_ordered_node_list_is_a_STORED_field_this_module_never_derives():
    """Sec 3.9 item 1. `board.py` "decides no order" (its own docstring), so `order` is written by
    `walk.board_order` and read back verbatim -- a container that also ranked would be the second
    ranker this package exists to not have. Before this field, `request()` filtered `rows` on a
    `rank` tuple that is truthy for EVERY row, so the payload was the DAG's insertion order."""
    bd = B.Board()
    assert bd.request()["order"] == (), "no walk, no order -- never a guess"
    bd.rows = [B.NodeRow(contract="c", driver_id=x) for x in ("a", "b", "c")]
    for r in bd.rows:
        r.rank = (0, -1.0, 0.0, 0.0, 0.0, 0.0, r.driver_id)
    assert bd.request()["order"] == (), "a truthy rank tuple is NOT an order"
    bd.set_order([bd.rows[2], bd.rows[0], bd.rows[1]])
    assert bd.request()["order"] == (("c", "c"), ("c", "a"), ("c", "b"))


def test_every_dataclass_here_is_a_dataclass_and_the_board_serialises():
    assert dataclasses.is_dataclass(B.NodeRow) and dataclasses.is_dataclass(B.Board)
    from leviathan.graphrag.state.lagbands import parse_lag
    row = B.NodeRow(contract="soybeans_cbot", driver_id="El_Nino", sign="-", lag="1-2 quarters",
                    lag_band=parse_lag("1-2 quarters"))
    d = row.to_dict()
    assert d["lag_band"]["min_q"] == 1 and d["lag_band"]["max_q"] == 2 and d["state"] is None
