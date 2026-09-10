"""STATE ENGINE S7 -- THE COVERAGE INSTRUMENT, THE SPILLOVER HOME, THE JOINED XC ROW, THE RECENCY
MOVEMENT AND THE JUDGE'S "state use" DIMENSION.

WHAT THIS DECK GRADES, and why each pin is here rather than somewhere else:

  1. `state.render.board_coverage` counts what a draft did with the rendered board, on the THREE
     acceptance fixtures, against a SYNTHETIC draft that cites some rows by handle and prints others'
     figures without a handle -- so both arms of the handle surface are exercised, and the tight read
     (`*_cited`) is asserted to be a strict subset of the loose one (`*_referenced`).
  2. The `CROSS-COMMODITY` licence line is minted IFF the block rendered at least one far row across a
     cross edge -- pinned positively on all three fixtures and negatively on a board whose fan is
     empty.
  3. The world-balance leg's THREE rows are ONE joined row: the head carries all three magnitudes,
     the two siblings declare the head, the [N] stride stays 3 and the rendered line is byte-identical
     to the shipped literal.
  4. The mandate names the RECENCY rows inside its EVIDENCE movement, and `check_literals()` is empty.
  5. `eval._judge_tool` gains `state_use` ONLY when the record carried a board, and the panel is ""
     otherwise -- so a deck with no board is byte-identical in schema and in prompt.

EVERYTHING HERE IS OFFLINE AND $0: the fixture harness (`state.__main__.build_scenario`), no pg, no
Athena, no S3, no clock, no LLM. Every figure quoted in a docstring is a FIXTURE value.
"""
from __future__ import annotations

import pytest
from leviathan.graphrag import eval as E
from leviathan.graphrag import verify as vf
from leviathan.graphrag.numbers import cascade as cq
from leviathan.graphrag.state import __main__ as H
from leviathan.graphrag.state import narration as N
from leviathan.graphrag.state import render as R

# ═══ THE OWED config_check CLAUSE ═══════════════════════════════════════════════════════════════════
# `config_check.py` IS ANOTHER LANE'S FILE THIS SITTING, so the clause this build owes it is written
# out here verbatim and asserted below in the only half this deck can own -- the behaviour. Whoever
# next opens `config_check.check_state_seam` should paste it in as clause (xii) and delete this note.
#
#   (xii)  THE SPILLOVER LICENCE IS A DECLARED MINT, NOT A SILENT ONE. Clause (iv) compares
#          `SB_MARKER_PREFIX` against the five INJECTED-ONLY marker LINES the persona keys reserved
#          headings on (CROSS-COMMODITY / CO-MOVE / CROSS-BOARD / DIVERGENCE / REROUTE) and its own
#          note said "the board mints none of them today, verified on all three acceptance fixtures".
#          THAT NOTE IS NOW FALSE BY DESIGN: `render.sb_cross_commodity` mints a CROSS-COMMODITY line
#          so the SPILLOVERS movement has the heading `narration.MANDATE_MOVEMENTS` already names for
#          it. The clause therefore becomes an ALLOWLIST OF ONE rather than a ban:
#            (a) `render.SB_CROSS_COMMODITY_PREFIX` is the ONE constant the board may mint from the
#                five, it is minted by exactly one producer (`sb_cross_commodity`, one call site in
#                `render_board`), and no OTHER of the five reserved words begins any rendered line --
#                assert it on the three acceptance fixtures' rendered blocks, as clause (iv)'s note
#                already claimed to;
#            (b) the mint is CONDITIONAL on the block having rendered at least one far row across a
#                cross edge, so a licence can never demand a section the block carries no rows for
#                (the +10-hallucination class the walk's own marker gate exists to refuse);
#            (c) `narration.SYSTEM_STATE_BOARD_MANDATE` carries the sentence that scopes that line, so
#                the FOUR MOVEMENTS keep ONE producer (the G5 law) and the persona paragraph at
#                answer.py:550-577 is not touched -- which is what keeps a flag-off turn
#                byte-identical. The scoping sentence must answer ALL FOUR readers of the bare word,
#                not one: `_SYSTEM_CASCADE_A` (:550-577, the su_ratio rule), `_SYSTEM_CASCADE_B`
#                (:709, "no CROSS-COMMODITY line -> do not invent a fork"), `_SYSTEM_TRANSMISSION`
#                (:783, "a CROSS-COMMODITY link is a relative-value divergence") and the world-balance
#                leg in `numbers/cascade.py`, which mints a SECOND line under the same word on a turn
#                that runs both legs. Assert the four clauses are present: no stocks-to-use rows, no
#                handle of its own, not a chain link, opens no fork heading;
#            (d) the EVAL-SIDE half of the same collision is closed and must stay closed:
#                `eval._cascade_asserts`' `reroute_v2_expected` NEGATIVE branch reds on the HEADING,
#                which the board now licenses with `reroute_v2_pairs == 0` -- nine live deck rows carry
#                that pin. The exemption is gated on this turn's own `state_board` trace reporting
#                `coverage.spillover_licensed`, so flag-off and no-far-row boards are unchanged.
OWED_CONFIG_CHECK_CLAUSE = "check_state_seam clause (xii) -- see the module note above"

# ═══ THE OWED EMF COUNTERS ══════════════════════════════════════════════════════════════════════════
# `state/seam.py` IS ALSO ANOTHER LANE'S FILE THIS SITTING, and `seam.counters()` is where the board's
# EMF block is minted. G3 on the design lane's reading is that all twenty-odd counters there measure
# what the board COST and not one measures what it BOUGHT -- `BoardBlockChars` counts what was SHOWN.
# The coverage dict now holds the numbers; these are the counter names phase B should publish from it,
# absent-when-inapplicable exactly like every other key that function emits (never a fake zero):
#
#     BoardRowsLoud / BoardRowsLoudReferenced / BoardRowsLoudCited
#     BoardEventsOpen / BoardEventsReferenced
#     BoardRecencyRows / BoardRecencyReferenced
#     BoardWatchRows / BoardWatchReferenced
#     BoardSpilloverRows / BoardSpilloverReferenced / BoardSpilloverLicensed
#
# NONE OF THEM IS WRITTEN HERE, deliberately: an EMF counter is a serving-side emission and this
# sitting ships an instrument, not a dashboard. `Board.coverage` and `Board.trace()['coverage']` carry
# every input those twelve need.
OWED_EMF_COUNTERS = ("BoardRowsLoudReferenced", "BoardEventsReferenced", "BoardRecencyReferenced",
                     "BoardWatchReferenced", "BoardSpilloverReferenced")

_RESERVED_MARKER_WORDS = ("CO-MOVE", "CROSS-BOARD", "DIVERGENCE", "REROUTE")


@pytest.fixture(scope="module")
def boards():
    """The three acceptance fixtures, built once. `bd.calls` is the SEAM's write in production; the
    harness holds the `Block`, so the block's own list is handed to `board_coverage` instead of
    mutating a board to satisfy an instrument (the `calls=` kwarg exists for exactly this caller)."""
    return {name: H.build_scenario(name) for name in H.SCENARIOS}


def _entries(bd, role="state") -> list:
    """One representative row per COVERAGE DENOMINATOR ENTRY of `role`, in block order.

    A DENOMINATOR ENTRY IS A ROW EXCEPT WHERE THE BLOCK SAYS TWO ROWS ARE ONE READING. `render_board`
    stamps `join` on the members of every phase pair (El Nino / La Nina on one ONI reading, the three
    Indonesian palm policy names on one PSD reading), and `board_coverage` folds them -- so a deck that
    picked "the first three state rows" would be picking two halves of one entry and asserting a
    denominator the instrument does not have."""
    out, seen = [], set()
    for m in bd.rendered_rows:
        if m.get("role") != role or not m.get("handles"):
            continue
        key = str(m.get("join") or "") or ("#%d" % id(m))
        if key in seen:
            continue
        seen.add(key)
        out.append(m)
    return out


def _draft_citing(bd, blk, *, roles=("state",), take=2, figures=()) -> str:
    """A SYNTHETIC draft: it cites the first `take` DENOMINATOR ENTRIES of each named role BY HANDLE,
    and prints each value in `figures` as a bare magnitude with no handle at all.

    THE TWO HALVES ARE THE TWO ARMS OF THE HANDLE SURFACE. A cited handle is the TIGHT read; a bare
    magnitude that matches a row's own LEVEL `shown` value through `verify._num_matches`, in a sentence
    carrying no other board handle, is the LOOSE one -- and the deck asserts they are counted
    separately rather than blended."""
    parts = []
    for role in roles:
        for m in _entries(bd, role)[:take]:
            parts.append(f"The board carries this reading [N{m['handles'][0]}].")
    for v in figures:
        parts.append(f"That series measures {v} on its own scale.")
    return " ".join(parts)


# ═══ 1. THE COVERAGE INSTRUMENT ═════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("name", list(H.SCENARIOS))
def test_coverage_counts_the_handle_surface_on_both_arms(boards, name):
    """A draft that cites two state rows and PRINTS a third's figure is credited with three rows --
    two on the tight read and three on the loose one."""
    ctx = boards[name]
    bd, blk = ctx["board"], ctx["block"]
    ents = _entries(bd, "state")
    assert len(ents) >= 3, name
    third = R._row_figures(ents[2]["handles"][:1], blk.calls, 1)
    assert third, "a rendered state row always mints at least one magnitude"
    draft = _draft_citing(bd, blk, take=2, figures=(f"{third[0]:g}",))
    cov = R.board_coverage(bd, draft, n_start=1, calls=blk.calls)
    assert cov["loud_cited"] == 2, (name, cov)
    assert cov["loud_referenced"] >= 3, (name, cov)
    assert cov["loud_figure_only"] >= 1, (name, cov)
    assert cov["loud_cited"] + cov["loud_figure_only"] == cov["loud_referenced"], (name, cov)
    assert cov["loud_rows"] == len(ents), (name, cov)
    # THE MISS LIST NAMES ROWS THAT HAVE NO HANDLE TOO -- four fifths of this block has none, and a
    # miss list that could only name the fifth that does would be a list about the wrong problem.
    assert len(cov["missed"]["loud"]) == cov["loud_rows"] - cov["loud_referenced"], (name, cov)


@pytest.mark.parametrize("name", list(H.SCENARIOS))
def test_coverage_is_zero_on_an_empty_draft_and_never_raises(boards, name):
    """AN EMPTY DRAFT IS A REAL DRAFT. Every denominator stands and every numerator is zero -- the
    instrument must not read "nothing said" as "nothing to measure"."""
    ctx = boards[name]
    cov = R.board_coverage(ctx["board"], "", n_start=1, calls=ctx["block"].calls)
    for hit, tot in (("loud_referenced", "loud_rows"), ("events_referenced", "events_open"),
                     ("recency_referenced", "recency_rows"), ("watch_referenced", "watch_rows"),
                     ("spillover_referenced", "spillover_rows")):
        assert cov[hit] == 0, (name, hit, cov)
        assert cov[tot] >= 0
    assert cov["loud_rows"] > 0 and cov["watch_rows"] > 0 and cov["spillover_rows"] > 0, (name, cov)


def test_coverage_leaves_an_untestable_recency_row_out_of_the_denominator(boards):
    """ABSENT IS NEVER ZERO. `soybeans_now` carries three RECENCY layers and the TEXT layer holds no
    document at all ("not carried on this page"), so the row has no date to test and is UNTESTABLE --
    it leaves the denominator rather than being charged as a miss."""
    ctx = boards["soybeans_now"]
    bd = ctx["board"]
    rec = [m for m in bd.rendered_rows if m.get("role") == "recency"]
    assert len(rec) == 3, [m["line"] for m in rec]
    assert sum(1 for m in rec if not m["tokens"]) == 1, [m["line"] for m in rec]
    cov = R.board_coverage(bd, "", n_start=1, calls=ctx["block"].calls)
    assert cov["recency_rows"] == 2, cov


def test_recency_row_needs_its_own_edge_words_not_just_a_date(boards):
    """THE LAYER FACT AND THE ROW FACT ARE TWO DIFFERENT CLAIMS, and the instrument must not confuse
    them. The EVIDENCE movement already tells the writer to date each row it leans on BY THAT ROW'S own
    knowledge date, so a sentence doing that correctly must not score the LAYER row as used."""
    ctx = boards["soybeans_now"]
    bd, blk = ctx["board"], ctx["block"]
    row_fact = "Note its knowledge date is 2025-12-31 and its declared effect window closed."
    layer_fact = ("The newest knowledge date on a number row behind this page is 2026-09-04, "
                  "and the oldest is 2025-12-31.")
    assert R.board_coverage(bd, row_fact, n_start=1, calls=blk.calls)["recency_referenced"] == 0
    assert R.board_coverage(bd, layer_fact, n_start=1, calls=blk.calls)["recency_referenced"] == 1


def test_coverage_reads_a_grouped_handle_token(boards):
    """`[N4,5]` IS A CITATION OF TWO ROWS. `eval._cascade_stats` tests `f"[{id}]" in prose`, which sees
    neither; the instrument routes through `verify._handle_members`, the shipped parser for the shape,
    so a writer that grouped its board handles is credited rather than charged."""
    ctx = boards["el_nino_fanout"]
    bd, blk = ctx["board"], ctx["block"]
    ents = _entries(bd, "state")
    a, b = ents[0]["handles"][0], ents[1]["handles"][0]
    cov = R.board_coverage(bd, f"Both readings sit far from their own history [N{a},{b}].",
                           n_start=1, calls=blk.calls)
    assert cov["loud_cited"] == 2, cov


def test_coverage_never_fences(boards):
    """A COUNTER, NEVER A FENCE. The instrument returns plain ints and tuples and touches nothing: no
    line of the block, no call record, no leg stamp, no trip.

    AND THE COUNTERS IT FEEDS ARE DECLARED, NOT WRITTEN. `seam.counters()` is another lane's file this
    sitting, so the twelve EMF names phase B should publish are named in :data:`OWED_EMF_COUNTERS` and
    the module note above it -- every one of them computable from the dict this returns."""
    ctx = boards["b40_event"]
    bd, blk = ctx["board"], ctx["block"]
    before = (list(blk.lines), list(blk.trips), [dict(c) for c in blk.calls], dict(bd.legs))
    cov = R.board_coverage(bd, "anything at all [N1]", n_start=1, calls=blk.calls)
    assert (list(blk.lines), list(blk.trips), [dict(c) for c in blk.calls], dict(bd.legs)) == before
    assert all(isinstance(v, (int, bool)) for k, v in cov.items() if k != "missed")
    assert OWED_EMF_COUNTERS and all(n.startswith("Board") for n in OWED_EMF_COUNTERS)


# ═══ 1b. THE THREE FALSE POSITIVES THE FIRST CUT SHIPPED ════════════════════════════════════════════
# The first cut ran `verify.figure_referenced` over EVERY sentence of the whole answer against the pool
# of ALL THREE handles a state row mints, and scored 38 of 38 loud rows REFERENCED on three banked
# prod-seat draws whose own human read found fourteen loud rows never used. Each pin below is one of the
# three reproduced defects, written from the fixture that produced it.
def test_a_join_twin_is_one_denominator_entry_not_two(boards):
    """(a) EL NINO AND LA NINA ARE ONE ONI READING UNDER TWO NAMES -- the block says so in its own JOIN
    row and the mandate tells the writer to give one side and never two. The first cut counted them as
    two loud rows, so the twin the writer correctly folded was scored REFERENCED by the sentence about
    its partner (they share one series and therefore one `shown` pool) -- a guaranteed false positive on
    every group, and twelve of the fourteen apparently-ignored loud rows on the banked draws.

    ONE ENTRY, ONE VERDICT, TAKEN FROM THE BEST MEMBER."""
    ctx = boards["el_nino_fanout"]
    bd, blk = ctx["board"], ctx["block"]
    joined = [m for m in bd.rendered_rows if m.get("role") == "state" and m.get("join")]
    assert len(joined) >= 2, [m["line"][:60] for m in joined]
    groups = {m["join"] for m in joined}
    pair = sorted((m for m in joined if m["join"] == sorted(groups)[0]),
                  key=lambda m: m["handles"][0])
    assert len(pair) == 2, [m["line"][:80] for m in pair]
    # CITING ONE MEMBER COVERS THE ENTRY, and the twin is neither a hit nor a miss of its own.
    cov = R.board_coverage(bd, f"The phase reads warm [N{pair[0]['handles'][0]}].",
                           n_start=1, calls=blk.calls)
    assert cov["loud_cited"] == 1, cov
    assert f"N{pair[1]['handles'][0]}" not in cov["missed"]["loud"], cov["missed"]
    # AND THE DENOMINATOR IS ENTRIES, NOT ROWS: every join group costs its members minus one.
    states = [m for m in bd.rendered_rows if m.get("role") == "state" and m.get("handles")]
    assert cov["loud_rows"] == len(_entries(bd, "state")) < len(states), (cov, len(states))


def test_the_loose_read_pools_the_level_handle_and_never_the_sigma(boards):
    """(b) SIGMA AND PERCENTILE ARE DIMENSIONLESS AND COLLIDE ACROSS EVERY ROW. `_num_matches` is
    sign-insensitive and scale-bridging, so one row's `-0.9 sigma` was matched by another's `+0.9
    sigma`: on the banked `soybeans_now` draw the Argentina AND Brazil export-tax rows were both scored
    REFERENCED by one fragment about the CRUSH row.

    NOTHING IS DELETED -- both siblings are still served, still handled, still bound by
    `_check_number_handle`. They are simply not EVIDENCE OF USE of the row they hang on."""
    ctx = boards["soybeans_now"]
    bd, blk = ctx["board"], ctx["block"]
    row = next(m for m in _entries(bd, "state") if len(m["handles"]) >= 3)
    lvl, sig = (R._row_figures(row["handles"][:1], blk.calls, 1)[0],
                R._row_figures(row["handles"][1:2], blk.calls, 1)[0])
    assert lvl != sig
    on_level = R.board_coverage(bd, f"It measures {lvl:g} on its own scale.", n_start=1,
                                calls=blk.calls)
    on_sigma = R.board_coverage(bd, f"It measures {sig:g} sigma on its own window.", n_start=1,
                                calls=blk.calls)
    assert on_level["loud_referenced"] >= 1, on_level
    assert on_sigma["loud_referenced"] == 0, (sig, on_sigma)


def test_a_value_match_needs_a_sentence_bound_to_the_row(boards):
    """(c) A SENTENCE THAT CITES ANOTHER BOARD ROW IS THAT ROW'S TESTIMONY. On the banked
    `el_nino_fanout` draw the flash-drought row -- SMOKE's "nearest thing to a defect in the three
    turns" -- was scored REFERENCED by a sentence about reporting-fund length carrying `[N26]` and
    `[N27]`. `verify` charges per SENTENCE and per CITED HANDLE; the first cut ran the same predicate
    with no handle binding at all.

    A value match counts in a sentence carrying THIS row's own handle, or carrying no board handle."""
    ctx = boards["el_nino_fanout"]
    bd, blk = ctx["board"], ctx["block"]
    ents = _entries(bd, "state")
    subject, other = ents[1], ents[0]
    val = R._row_figures(subject["handles"][:1], blk.calls, 1)[0]
    free = R.board_coverage(bd, f"Some reading measures {val:g} on its scale.", n_start=1,
                            calls=blk.calls)
    bound = R.board_coverage(bd, f"Some reading measures {val:g} [N{other['handles'][0]}].",
                             n_start=1, calls=blk.calls)
    assert f"N{subject['handles'][0]}" not in free["missed"]["loud"], free["missed"]
    assert f"N{subject['handles'][0]}" in bound["missed"]["loud"], bound["missed"]


def test_a_register_corrected_loud_row_is_a_miss_and_never_invisible(boards):
    """THE FENCE CORRECTS, AND THE DENOMINATOR KEEPS THE ROW. `Block.add`'s own docstring promises "a
    row the fence corrected keeps its role and loses its handles ... so the row is still in the
    denominator and can never be referenced" -- and the first cut let it fall out of BOTH numerator and
    denominator, because a handle-role row with no handles and no tokens read as UNTESTABLE. A block
    that corrected every loud row would have read `0 of 0`, and the bias was UPWARD: the one direction
    an instrument must never take. Reachable in prod -- S6's own note records a measured shape shipping
    `trips=3, register_leaks=3` at deep and max."""
    ctx = boards["soybeans_now"]
    blk = R.Block(start=1)
    ok = blk.add("- [N1] a clean loud reading: 1.5 degC", [R.sb_call(
        table="silver_noaa_oni", metric="oni", commodity=None, country="global", period="2026-08",
        asof="2026-09-07", value=1.5, unit="degC")], role="state")
    tripped = blk.add("this is a buy signal", [R.sb_call(
        table="silver_noaa_oni", metric="oni", commodity=None, country="global", period="2026-08",
        asof="2026-09-07", value=2.5, unit="degC")], role="state",
        display="the state row for a tripped driver")
    assert ok and blk.trips, blk.trips
    assert tripped.startswith("BOARD ABSENCE"), tripped
    corrected = blk.rows_meta[-1]
    assert corrected["role"] == "state" and corrected["handles"] == () and corrected["tokens"] == ()

    class _B:
        rendered_rows = tuple(dict(m) for m in blk.rows_meta)
        calls = list(blk.calls)
        knobs = ctx["board"].knobs
    cov = R.board_coverage(_B(), "The board carries this reading [N1].", n_start=1, calls=blk.calls)
    assert cov["loud_rows"] == 2, cov                 # the corrected row is STILL in the denominator
    assert cov["loud_cited"] == 1 and cov["loud_referenced"] == 1, cov
    assert len(cov["missed"]["loud"]) == 1, cov       # and it is a MISS, never an absent measurement


def test_an_empty_board_measures_nothing_rather_than_zero(boards):
    """ABSENT IS NEVER ZERO, ON THE FUNCTION WRITTEN TO HONOUR IT. A board that rendered no row returns
    `{}` -- so `Board.trace()` omits the key (its own docstring's promise) and the judge is never asked
    to score `state_use` against a board that put nothing on the page. THE PATH IS LIVE:
    `seam.fill_stage2`'s SUBJECT RESOLVER ambiguity branch ships a one-line block WITHOUT calling
    `render_board`, so the seam's `block` is truthy and `rendered_rows` is still empty."""
    bd = boards["b40_event"]["board"]
    saved = bd.rendered_rows
    try:
        bd.rendered_rows = ()
        assert R.board_coverage(bd, "anything at all", n_start=1, calls=[]) == {}
        bd.coverage = R.board_coverage(bd, "anything at all", n_start=1, calls=[])
        assert "coverage" not in bd.trace()
        assert E._judge_state_panel({"trace": {"state_board": {"coverage": {}}}}) == ""
        assert E._judge_state_panel({"trace": {"state_board": {"coverage": {"declined": "KeyError"}}}}) == ""
    finally:
        bd.rendered_rows, bd.coverage = saved, {}


def test_a_kind_two_watch_row_keeps_its_letters_surface(boards):
    """A HANDLED ROW MAY STILL BE NARRATED IN WORDS. The kind-2 WATCH row is on BOTH surfaces -- its
    distance figure is bound to its own [N] and `_watch_tokens` mints a name-and-date group for it --
    and the first cut short-circuited on the handle surface, so a writer that named the row and its date
    without restating the distance scored MISSED with a passing token group in hand."""
    ctx = boards["b40_event"]
    bd, blk = ctx["board"], ctx["block"]
    kind2 = [m for m in bd.rendered_rows if m.get("role") == "watch" and m.get("handles")
             and m.get("tokens")]
    if not kind2:
        pytest.skip("no kind-2 watch row on this fixture")
    m = kind2[0]
    sentence = " ".join([m["tokens"][0][0]] + [g[0] for g in m["tokens"][1:]])
    cov = R.board_coverage(bd, f"Watch this one: {sentence}.", n_start=1, calls=blk.calls)
    assert f"N{m['handles'][0]}" not in cov["missed"]["watch"], (sentence, cov["missed"])
    assert cov["watch_referenced"] >= 1 and cov["watch_cited"] == 0, cov


def test_coverage_rides_the_board_trace_and_is_omitted_when_empty(boards):
    """`Board.trace()` CARRIES IT AND OMITS IT -- the `subject` idiom, and the reason is the same: one
    registered `state_board` key, zero `tracekeys` churn, zero tail-pin re-anchoring."""
    ctx = boards["el_nino_fanout"]
    bd = ctx["board"]
    assert "coverage" not in bd.trace()
    bd.coverage = R.board_coverage(bd, "", n_start=1, calls=ctx["block"].calls)
    tr = bd.trace()
    assert "coverage" in tr and tr["coverage"]["loud_rows"] > 0
    bd.coverage = {}


# ═══ 2. THE SPILLOVER HOME ══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("name", list(H.SCENARIOS))
def test_the_cross_commodity_licence_is_minted_on_every_acceptance_fixture(boards, name):
    """ALL THREE MINT IT, and `el_nino_fanout` is the one the design demands it on -- the question
    never names palm and the fan is the whole point. `soybeans_now` mints it TOO, because the board
    renders ten far rows across cross edges (CBOT soybean meal / soybean oil, CME palm oil, ICE cocoa /
    raw sugar / robusta coffee, JSE white and yellow maize, MATIF french wheat, MGEX hrs wheat) -- and
    that turn is exactly the one whose prod-seat draw dropped SPILLOVERS entirely."""
    ctx = boards[name]
    lic = [ln for ln in ctx["block"].lines if ln.startswith(R.SB_CROSS_COMMODITY_PREFIX)]
    assert len(lic) == 1, (name, lic)
    assert R.classify(lic[0]) == ("SB-F",), (name, R.classify(lic[0]))
    assert R.register_hits(lic[0]) == [], (name, R.register_hits(lic[0]))
    assert not any(ch.isdigit() for ch in lic[0]), (name, lic[0])   # letters-only class
    far = {m["line"] for m in ctx["board"].rendered_rows if m.get("role") == "far"}
    assert far, name
    cov = R.board_coverage(ctx["board"], "", n_start=1, calls=ctx["block"].calls)
    assert cov["spillover_licensed"] is True and cov["spillover_rows"] == len(far), (name, cov)


def test_the_licence_names_only_boards_whose_far_rows_rendered(boards):
    """A LICENCE NAMES ROWS THE READER HAS. Every market on the line is a far board with its own
    rendered row above it -- so the section the writer is licensed to open has the sign words and lag
    words it will need, and the +10-hallucination class stays closed."""
    ctx = boards["el_nino_fanout"]
    lic = next(ln for ln in ctx["block"].lines if ln.startswith(R.SB_CROSS_COMMODITY_PREFIX))
    rendered_far = [m["line"] for m in ctx["board"].rendered_rows if m.get("role") == "far"]
    for m in ctx["board"].rendered_rows:
        if m.get("role") != "far":
            continue
        assert any(t in lic for t in m["tokens"][0]), (m["line"], lic)
    assert len(rendered_far) == 4, rendered_far


def test_no_far_row_mints_no_licence_and_changes_nothing():
    """THE NEGATIVE HALF, and it is the one that makes the mint a gate rather than a habit. A board
    whose fan is emptied renders no far row, so no licence line is minted and the SPILLOVERS movement
    falls back exactly where `MANDATE_MOVEMENTS` has always sent it."""
    ctx = H.build_scenario("el_nino_fanout")
    bd = ctx["board"]
    bd.fan = []
    blk = R.render_board(bd, analogs=ctx["analogs"], watch=ctx["watch"], recency=ctx["recency"],
                         anchor_label="CBOT soybeans")
    assert not [ln for ln in blk.lines if ln.startswith(R.SB_CROSS_COMMODITY_PREFIX)]
    cov = R.board_coverage(bd, "", n_start=1, calls=blk.calls)
    assert cov["spillover_licensed"] is False and cov["spillover_rows"] == 0, cov


@pytest.mark.parametrize("name", list(H.SCENARIOS))
def test_no_other_reserved_marker_word_opens_a_board_line(boards, name):
    """THE OTHER FOUR RESERVED HEADINGS STAY UNLICENSED. This is the behaviour half of the owed
    `config_check` clause (xii)(a): CROSS-COMMODITY is an allowlist of ONE, and CO-MOVE, CROSS-BOARD,
    DIVERGENCE and REROUTE must still begin no rendered line."""
    for ln in boards[name]["block"].lines:
        for word in _RESERVED_MARKER_WORDS:
            assert not ln.startswith(word), (name, word, ln[:80])


def test_a_same_board_far_row_is_not_a_spillover_and_mints_no_licence():
    """ONE POPULATION UNDER ONE WORD. The licence names only far rows across a CROSS edge
    (`f['contract'] != e['contract']`) while the first cut stamped role `far` on EVERY far row, so
    `spillover_referenced 4 / 8` could count a denominator the licence deliberately excludes. A
    same-board fan far row now carries `far_same_board` and is counted BESIDE the spillovers, never
    inside them.

    UNEXERCISED ON THE THREE FIXTURES (every far row there is cross), which is exactly why it had to be
    closed by construction: this rewrites the fan's far boards to the seed's own contract to reach it."""
    ctx = H.build_scenario("el_nino_fanout")
    bd = ctx["board"]
    for e in bd.fan:
        for f in e["far"]:
            f["contract"] = e["contract"]
    blk = R.render_board(bd, analogs=ctx["analogs"], watch=ctx["watch"], recency=ctx["recency"],
                         anchor_label="CBOT soybeans")
    assert not [ln for ln in blk.lines if ln.startswith(R.SB_CROSS_COMMODITY_PREFIX)]
    cov = R.board_coverage(bd, "", n_start=1, calls=blk.calls)
    assert cov["spillover_licensed"] is False, cov
    assert cov["spillover_rows"] == 0, cov
    assert cov["spillover_same_board_rows"] > 0, cov


def test_the_licence_exempts_the_reroute_v2_negative_pin_only_on_a_board_turn():
    """THE LICENCE FALSE-REDS A SHIPPED GATE THE MOMENT THE FLAG IS ON, AND THE EXEMPTION IS AS NARROW
    AS THE FACT. `eval._cascade_asserts`' `reroute_v2_expected` negative branch fails on
    `(not fired_v2) and heading` -- and the board now mints the marker that licenses that heading, on
    turns where `reroute_v2_pairs` is 0 by construction. Nine live deck rows carry
    `reroute_v2_expected: false`.

    The pin is about the RV-v2 LEG, so a heading the BOARD licensed is outside its subject -- but ONLY
    when this turn's own `state_board` trace says the block minted the licence. Flag-off is unchanged,
    and a board with no far row is unchanged."""
    q = {"expect": {"reroute_v2_expected": False}}

    def _out(heading: bool, lic=None):
        mech = ("## Cross-commodity\n- CBOT soybean oil moves the same way"
                if heading else "## Mechanism\nplain prose")
        tr = {"quantify": []}
        if lic is not None:
            tr["state_board"] = {"coverage": {"spillover_licensed": lic, "loud_rows": 4}}
        return {"trace": tr, "structured": {"tldr": "", "mechanism": mech}, "citations": [],
                "intent_decision": {"planner": "llm"}}

    # HEAD's behaviour, unchanged where no board licensed the heading
    assert E._cascade_asserts(q, _out(heading=False))["reroute_v2_expected"] is True
    assert E._cascade_asserts(q, _out(heading=True))["reroute_v2_expected"] is False
    assert E._cascade_asserts(q, _out(heading=True, lic=False))["reroute_v2_expected"] is False
    # the board licensed it -> the heading is not this pin's business
    assert E._cascade_asserts(q, _out(heading=True, lic=True))["reroute_v2_expected"] is True
    # and the HARD half of the gate is untouched: a fired v2 on a negative pin still FAILS
    hard = _out(heading=True, lic=True)
    hard["trace"]["quantify_reroute_v2"] = [{"pair_id": "veg_oil_soy_palm"}]
    assert E._cascade_asserts(q, hard)["reroute_v2_expected"] is False


def test_the_mandate_scopes_the_licence_line_and_keeps_one_producer():
    """THE FOUR MOVEMENTS HAVE ONE PRODUCER (the G5 law). The sentence that tells the writer what the
    board's own CROSS-COMMODITY line carries lives in the MANDATE, inside the SPILLOVERS movement --
    not in a second directive appended after it, and not in the persona paragraph at answer.py:550-577,
    which is untouched so a flag-off turn stays byte-identical."""
    m = N.SYSTEM_STATE_BOARD_MANDATE
    assert R.SB_CROSS_COMMODITY_PREFIX in m
    i_sp, i_watch = m.index("(3) SPILLOVERS"), m.index("(4) WATCH")
    assert i_sp < m.index(R.SB_CROSS_COMMODITY_PREFIX) < i_watch
    assert ("SPILLOVERS", "## Cross-commodity", "## Mechanism") in N.MANDATE_MOVEMENTS


def test_the_mandate_answers_all_four_readers_of_the_bare_marker_word():
    """FOUR CONSUMERS KEY ON THE BARE WORD AND THE SCOPING SENTENCE ANSWERS ALL FOUR AT ONCE.
    `_SYSTEM_CASCADE_A` (answer.py:550-577) reads it as two commodities' stocks-to-use rows;
    `_SYSTEM_CASCADE_B` (:709) reads its ABSENCE as "do not invent a fork"; `_SYSTEM_TRANSMISSION`
    (:783) reads it as a relative-value divergence, i.e. a chain LINK; and `numbers/cascade.py` mints a
    second line under the same word on a turn that runs the world-balance leg.

    THE SCOPE IS STATED IN THE MANDATE AND IN NO PERSONA PARAGRAPH, and that is the byte-identity
    argument, not a preference: all three persona paragraphs are UNCONDITIONAL module constants, so a
    sentence added to any of them would change the system prompt on every flag-off turn. The mandate
    ships only when the block does."""
    m = N.SYSTEM_STATE_BOARD_MANDATE
    body = m[m.index("(3) SPILLOVERS"):m.index("(4) WATCH")]
    assert "carries no stocks-to-use rows and no handle of its own" in body
    assert "not a link in a transmission chain" in body
    assert "opens no fork heading" in body
    assert "is a different line under its own rule" in body
    # the three persona paragraphs are NOT touched -- they carry no board sentence
    from leviathan.graphrag import answer as A
    for para in (A._SYSTEM_CASCADE_A, A._SYSTEM_CASCADE_B, A._SYSTEM_TRANSMISSION):
        assert "STATE OF THE WORLD" not in para
        assert "board" not in para.lower().replace("world basis", "")
    # and the RV-v2 rule that reads the same word is still the su_ratio one, verbatim
    assert ("two DIFFERENT commodities' stocks-to-use ratios are being compared on a world basis"
            in A._SYSTEM_CASCADE_A)


# ═══ 3. ONE HANDLE PER JOINED SENTENCE (the world-balance leg) ══════════════════════════════════════
_XC_A = {"a": (2000, 12.2662, "2000-01-01"), "b": (2001, 11.7287, "2001-01-01"), "d": -0.537525}
_XC_B = {"a": (2000, 8.0, "2000-01-01"), "b": (2001, 9.5, "2001-01-01"), "d": 1.5}


def _xc():
    calls: list = []
    lines, _ends, legs = cq._xc_leg_lines("soybean oil", "soybean_oil", _XC_A,
                                          "palm oil", "palm_oil", _XC_B,
                                          calls, 40, "2026-09-07")
    return lines, calls, legs


def test_the_world_balance_leg_is_one_joined_row_per_leg():
    """THE BANKED SHAPE, REPRODUCED. `deep rv_soyoil_palm` rendered ONE sentence carrying three
    magnitudes -- 11.7287% in MY2001, 12.2662% in MY2000, -0.537525pp over the window -- under
    `[N41]`, while `[N42]` and `[N43]` were served, spent and never cited. Every one of the 22 tightest
    used-without-citing rows in the utilisation census is this shape.

    ONE LINE, ONE HEAD HANDLE, THREE MAGNITUDES ON IT. The two siblings now DECLARE the row they
    belong to, so a menu reader counts one joined offer where the sentence has one."""
    lines, calls, legs = _xc()
    assert len(lines) == 2, lines                       # one joined row per leg, never three
    (hA, hi, lo, d), (hB, _b1, _b0, _bd) = legs
    assert (hA, hB) == (41, 44)
    assert lines[0].startswith("- [N41] soybean oil stocks-to-use MY2001: 11.7287% "
                               "(vs MY2000 12.2662%, -0.537525pp over the window)")
    head = calls[0]
    assert head["shown"] == [11.7287, 12.2662, -0.537525], head["shown"]
    assert cq.xc_join_head(head) == 41 and cq.xc_join_is_member(head) is False
    for off, role in ((1, "baseline"), (2, "delta")):
        sib = calls[off]
        assert cq.xc_join_head(sib) == 41, (off, sib.get(cq.XC_JOIN_KEY))
        assert cq.xc_join_is_member(sib) is True
        assert sib[cq.XC_JOIN_KEY]["role"] == role
        assert sib[cq.XC_JOIN_KEY]["members"] == (41, 42, 43)
    assert (hi, lo, d) == (11.7287, 12.2662, -0.5375)


def test_the_joined_row_deletes_nothing_and_moves_no_handle():
    """FENCES CORRECT OR COMPUTE, NEVER DELETE. All six call records still exist, all three values per
    leg are still served, and the [N] STRIDE STAYS 3 -- so every later handle keeps its position and
    the rendered prose is byte-identical to HEAD."""
    _lines, calls, _legs = _xc()
    assert len(calls) == 6
    # THE HEAD'S POOL IS ITS `shown` (all three magnitudes, RAW); the two siblings carry ONE row each
    # and `_xc_call` rounds a row value to four places -- which is why the delta's own row reads
    # -0.5375 while the head's testimony to the verifier keeps -0.537525. Both are pinned, because a
    # writer may copy either token off the line and both must bind.
    assert vf.row_pool(calls[0]) == [11.7287, 12.2662, -0.537525]
    assert [vf.row_pool(c)[0] for c in calls] == [11.7287, 12.2662, -0.5375, 9.5, 8.0, 1.5]
    heads = [cq.xc_join_head(c) for c in calls]
    assert heads == [41, 41, 41, 44, 44, 44]            # stride 3, both legs


def test_the_join_key_reaches_no_rendered_or_banked_surface():
    """THE FLAG-OFF BYTE-IDENTITY CLAIM FOR THE ONE CHANGE THAT IS NOT BOARD-GATED, MEASURED RATHER
    THAN ASSERTED -- AND, READ THE OTHER WAY, THE PROOF THAT ITEM (3) IS AN ADDRESS AND NOT YET THE FIX.
    Nothing in `src/`, `jobs/` or `scripts/` reads `XC_JOIN_KEY` outside its own producer, so the writer
    is still offered N41/N42/N43 as three separate menu rows for the one joined sentence and every
    counter in the estate still counts three where the sentence has one: the 22 used-without-citing
    `xc` rows the utilisation census measured would re-score IDENTICALLY today. The two surfaces that
    would close it -- `citations.render` folding members under their head, and a joined-row denominator
    in the eval census -- are outside this sitting's allowlist and are carried, not claimed.

    The join stamp rides the CALL RECORD, and every surface a call record reaches is compared here
    against the same records with the key stripped:

      * `citations.unify` + `citations.render` -- the `## Sources` footer and the [N] menu;
      * `verify.verify_citations` -- the strips, the ledger and the prose it rewrites;
      * `eval._served_rows` -- the banked artifact, which projects a CLOSED key set per row and never
        the raw call dict.

    So the leg's prose, its footer, its strip count and its artifact are all byte-identical to HEAD."""
    import copy
    import json as _json

    from leviathan.graphrag import citations as cit
    lines, calls, _legs = _xc()
    stripped = [{k: v for k, v in c.items() if k != cq.XC_JOIN_KEY}
                for c in copy.deepcopy(calls)]
    a, b = cit.unify([], calls), cit.unify([], stripped)
    assert _json.dumps(a, sort_keys=True, default=str) == _json.dumps(b, sort_keys=True, default=str)
    assert cit.render(a) == cit.render(b)
    claim = ("World soybean oil stocks-to-use was 11.7287% in MY2001, versus 12.2662% in MY2000, "
             "-0.537525pp over the window [N41].")
    s1, s2 = {"tldr": claim, "mechanism": ""}, {"tldr": claim, "mechanism": ""}
    r1 = vf.verify_citations(s1, [], [{}] * 40 + calls)
    r2 = vf.verify_citations(s2, [], [{}] * 40 + stripped)
    assert s1["tldr"] == s2["tldr"] == claim          # the joined sentence survives, unrewritten
    assert int(r1.get("stripped") or 0) == int(r2.get("stripped") or 0) == 0
    assert E._served_rows({"number_calls_full": calls}) == E._served_rows(
        {"number_calls_full": stripped})
    assert lines[0].endswith("[series: soybean_oil; country: World; table: USDA PSD]")


def test_the_join_key_is_invisible_to_a_call_with_no_join():
    """ONE READER FOR THE KEY, and it answers None for every other row in the estate -- a board row, an
    agent lookup, a cascade era leg. Nothing outside this leg acquires a join by accident."""
    assert cq.xc_join_head({"query": {}, "rows": []}) is None
    assert cq.xc_join_is_member({"query": {}, "rows": []}) is False
    assert cq.xc_join_head(R.sb_call(table="silver_noaa_oni", metric="oni", commodity=None,
                                     country="global", period="2026-08", asof="2026-09-07",
                                     value=0.98, unit="degC")) is None


# ═══ 4. THE RECENCY MOVEMENT ════════════════════════════════════════════════════════════════════════
def test_the_mandate_names_the_recency_rows_inside_its_evidence_movement():
    """THE SB-L ROWS ARE EVIDENCE THE READER IS OWED, and the sentence saying so sits INSIDE movement
    (2) -- not in the mandate's tail, where the standing "state each RECENCY row as a fact about the
    layer it names" rule already lived and where a prod-seat draw narrated 0 of 9 such rows."""
    m = N.SYSTEM_STATE_BOARD_MANDATE
    i_ev, i_sp = m.index("(2) EVIDENCE"), m.index("(3) SPILLOVERS")
    body = m[i_ev:i_sp]
    assert "RECENCY rows belong to this movement" in body
    for phrase in ("newest knowledge date", "newest dated document", "board price tape"):
        assert phrase in body, phrase
    # the standing tail rule is NOT replaced -- both sentences ship
    assert "State each RECENCY row as a fact about the layer it names" in m[i_sp:]


def test_the_mandate_is_register_clean_at_build():
    """A SERVE-TIME REGISTER TRIP ON A SHIPPED LITERAL IS A BUILD DEFECT (bar B15). Both new sentences
    ride the same four detectors plus `pace_register_ok` and the banned recency phrase."""
    assert N.check_literals() == []
    assert R.register_hits(N.SYSTEM_STATE_BOARD_MANDATE) == []
    assert cq.pace_register_ok(N.SYSTEM_STATE_BOARD_MANDATE) is True
    N.SYSTEM_STATE_BOARD_MANDATE.encode("ascii")


# ═══ 5. THE JUDGE ═══════════════════════════════════════════════════════════════════════════════════
def test_the_state_use_dimension_is_absent_when_the_record_carried_no_board():
    """ABSENT, NOT ZERO, AND THE PANEL DECK'S SHAPE IS UNCHANGED. A turn with no board has no state use
    to score, so neither the schema property nor the rubric text exists on it -- and `required` is
    byte-identical either way, which is what stops every existing deck's baseline moving."""
    base = E._judge_tool()
    assert "state_use" not in base["input_schema"]["properties"]
    assert E._judge_state_panel({}) == ""
    assert E._judge_state_panel({"trace": {}}) == ""
    assert E._judge_state_panel({"trace": {"state_board": {"legs": {}}}}) == ""
    armed = E._judge_tool(state_use=True)
    assert "state_use" in armed["input_schema"]["properties"]
    assert armed["input_schema"]["required"] == base["input_schema"]["required"]
    assert "state_use" not in armed["input_schema"]["required"]
    # THE SHARED SYSTEM CONSTANT IS UNTOUCHED: it is cache-controlled and every deck in the estate
    # pays for it, so the bullet rides the per-turn user block instead.
    assert "state_use" not in E._JUDGE_SYS


def test_the_state_panel_shows_the_counts_and_the_misses(boards):
    """SCORED FROM THE COVERAGE DICT AND THE DRAFT. The panel is built from a REAL board's coverage,
    and it must carry every denominator, the licence fact and the missed ids -- a judge shown only
    numerators could not tell an unused board from a small one."""
    ctx = boards["b40_event"]
    bd, blk = ctx["board"], ctx["block"]
    cov = R.board_coverage(bd, "", n_start=1, calls=blk.calls)
    panel = E._judge_state_panel({"trace": {"state_board": {"coverage": cov}}})
    # THE TIGHT READ LEADS. `*_cited` is what the writer NAMED; the loose arm added ZERO rows on all
    # three banked prod-seat draws while a control corpus carrying no board magnitude at any scale
    # still scored 2-5 of 8-9 through `_num_matches`' five-scale bridging -- so a panel that led with
    # the loose number would lead with the noisier one.
    assert panel.splitlines()[0].startswith("- loud state rows CITED by handle: 0 of %d"
                                            % cov["loud_rows"]), panel.splitlines()[0]
    assert "loud state rows referenced: 0 of %d" % cov["loud_rows"] in panel
    assert "OPEN dated-event rows referenced: 0 of 1" in panel
    assert "per-layer RECENCY rows stated as layer facts" in panel
    assert "the block minted the cross-commodity licence line" in panel
    assert "never referenced" in panel
    assert "COVERAGE" in E._JUDGE_STATE_USE or "COVERAGE, not correctness" in E._JUDGE_STATE_USE
    assert "coverage" in E._JUDGE_STATE_USE.lower()


def test_the_judge_metrics_row_carries_state_use_as_none_without_a_board():
    """THE `dir_trace` IDIOM: the axis is a key whose value is None on every row that has no board, so
    a mixed deck aggregates over the rows that HAVE it rather than over a fabricated zero."""
    row = {"q": {"contract": "soybeans"}, "out": {"answer": "", "structured": {}, "trace": {}},
           "rubric": {"routed_right": True}, "judge": {}}
    assert E._metrics(row)["state_use"] is None
    row["judge"] = {"state_use": 4}
    assert E._metrics(row)["state_use"] == 4
