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

# === THE TWO OWED NOTES, NOW LANDED (S7 render lane) ==============================================
# S6 shipped this deck with two OWED notes, because `config_check.py` and `state/seam.py` were other
# lanes' files that sitting and a clause you cannot commit is a clause you write out verbatim. BOTH
# HAVE LANDED, so the notes are deleted and replaced by the ONE thing a deck can own about them --
# assertions that the landed surfaces are the ones that were asked for:
#
#   * `config_check.check_state_seam` clause (xii), THE SPILLOVER LICENCE AS AN ALLOWLIST OF ONE:
#     `render.SB_CROSS_COMMODITY_PREFIX` is the only one of the persona's five reserved marker words
#     the board may mint, it has one producer and one call site, the mint is CONDITIONAL on a rendered
#     far row across a cross edge, and the mandate scopes the word for all four of its readers;
#   * clause (xiii) and `seam.COVERAGE_COUNTERS`, THE TWELVE COUNTERS and their denominators -- the
#     names the S6 note asked phase B to publish, now declared in the seam beside the dict they are
#     computed from.
#
# WHAT IS ASSERTED HERE IS THE JOIN, not the clause bodies: that the twelve counter names exist, that
# every one of them is computable from what `board_coverage` returns, and that the estate's own lint
# is green on the pair. The clause bodies are graded where they live.
COVERAGE_COUNTER_NAMES = ("BoardRowsLoud", "BoardRowsLoudReferenced", "BoardRowsLoudCited",
                          "BoardEventsOpen", "BoardEventsReferenced",
                          "BoardRecencyRows", "BoardRecencyReferenced",
                          "BoardWatchRows", "BoardWatchReferenced",
                          "BoardSpilloverRows", "BoardSpilloverReferenced",
                          "BoardSpilloverLicensed")

#: counter name -> the `board_coverage` key it is computed from. It is written out so the claim "every
#: counter is computable from the instrument's own dict" is an ASSERTION rather than a reading.
COUNTER_SOURCE_KEYS = {
    "BoardRowsLoud": "loud_rows", "BoardRowsLoudReferenced": "loud_referenced",
    "BoardRowsLoudCited": "loud_cited", "BoardEventsOpen": "events_open",
    "BoardEventsReferenced": "events_referenced", "BoardRecencyRows": "recency_rows",
    "BoardRecencyReferenced": "recency_referenced", "BoardWatchRows": "watch_rows",
    "BoardWatchReferenced": "watch_referenced", "BoardSpilloverRows": "spillover_rows",
    "BoardSpilloverReferenced": "spillover_referenced",
    "BoardSpilloverLicensed": "spillover_licensed",
}


def test_the_two_OWED_notes_have_LANDED_and_the_seam_declares_the_twelve_counters(boards):
    """THE HANDOFF IS CLOSED AND THIS IS WHAT CLOSED IT. A deleted OWED note with nothing asserted in
    its place is a note that stopped being true quietly; these three asserts are what make the deletion
    a fact rather than a tidy-up."""
    from leviathan.graphrag import config_check as cc
    from leviathan.graphrag.state import seam as SEAM
    assert tuple(SEAM.COVERAGE_COUNTERS) == COVERAGE_COUNTER_NAMES
    ctx = boards["el_nino_fanout"]
    cov = R.board_coverage(ctx["board"], "nothing in particular", n_start=1,
                           calls=ctx["block"].calls)
    for name, key in sorted(COUNTER_SOURCE_KEYS.items()):
        assert name in SEAM.COVERAGE_COUNTERS, name
        assert key in cov, (name, key)
    assert cc.check_state_seam() == []


#: **S8's ELEVEN, DESIGN B.6's OWN LIST.** They ride the `_nomination_coverage` splat precedent -- a
#: sub-dict returned from `board_coverage` needs no `tracekeys` entry and re-pins nothing -- and they
#: are DECLARED here, beside the twelve above, so the chain's counter roster has ONE home rather than
#: living only in the function that computes it.
CHAIN_COVERAGE_KEYS = ("chain_rendered", "chain_referenced", "chain_hops_rendered",
                       "chain_hops_referenced", "chain_hops_agreeing", "chain_hops_at_odds",
                       "chain_receipts_rendered", "chain_receipts_cited", "chain_events_open",
                       "chain_history_n", "chain_below_print_line")


def test_S8_the_chain_counters_are_ABSENT_on_every_board_whose_chain_leg_did_not_run(boards):
    """**ABSENT IS NEVER ZERO**, the contract this whole return keeps, applied to the eleven new keys.

    The three acceptance fixtures build with `state_chain` unset, so `bd.chains` is empty and NOT ONE
    of these keys may appear: a census must be able to tell "the chain rendered nothing" from "the
    chain was never armed", and an all-zero dict says the first while meaning the second. The positive
    half -- every key present, and the zero-writer floor where the block is scored against its own
    rendered text -- is pinned in `test_state_chain_render.py`, which is the deck that owns a board
    with the leg armed."""
    for name, ctx in boards.items():
        assert list(ctx["board"].chains) == [], name
        cov = R.board_coverage(ctx["board"], ctx["block"].text(), calls=ctx["block"].calls)
        assert [k for k in cov if k.startswith("chain")] == [], (name, cov)
        assert "missed_chains" not in cov, name
    # ...and the eleven are real keys of the producer, not a list nobody joined to it.
    src = R._chain_coverage.__doc__ or ""
    assert "ABSENT IS NEVER ZERO" in src
    import inspect as _i
    body = _i.getsource(R._chain_coverage)
    for key in CHAIN_COVERAGE_KEYS:
        assert '"%s"' % key in body, key


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

    AND THE COUNTERS IT FEEDS ARE DECLARED IN THE SEAM. The twelve EMF names are
    `seam.COVERAGE_COUNTERS`, pinned against this instrument's own keys in
    :data:`COUNTER_SOURCE_KEYS` -- every one of them computable from the dict this returns."""
    ctx = boards["b40_event"]
    bd, blk = ctx["board"], ctx["block"]
    before = (list(blk.lines), list(blk.trips), [dict(c) for c in blk.calls], dict(bd.legs))
    cov = R.board_coverage(bd, "anything at all [N1]", n_start=1, calls=blk.calls)
    assert (list(blk.lines), list(blk.trips), [dict(c) for c in blk.calls], dict(bd.legs)) == before
    assert all(isinstance(v, (int, bool)) for k, v in cov.items() if k != "missed")
    assert COVERAGE_COUNTER_NAMES and all(n.startswith("Board")
                                          for n in COVERAGE_COUNTER_NAMES)


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


# === S7: THE COVERAGE INSTRUMENT'S TOKEN FOLDS =====================================================
# TWO FOLDS SHIPPED AND ONE WAS REFUSED BY ITS OWN FALSIFIER. All three were re-scored on the banked
# prod-seat draws (scratchpad/writer_board_use/smoke_s6b) against the three controls
# `board_coverage`'s docstring records, plus the S6 NEGATIVE control and the HUMAN ceiling.
#
#   A  DATE FORMS (`_date_forms`)  -- SHIPPED. Day-precise forms only.
#   B  RECENCY LAYER WORDS         -- SHIPPED. Superlative-carrying alternatives only.
#   C  TWO-SENTENCE WINDOW         -- REFUSED. See `_TOKEN_WINDOW_SENTS`' own note for the numbers.
#
# MEASURED, POOLED OVER THE THREE S6b DRAWS (HEAD -> S7):
#   recency_referenced   5/7 -> 6/7      (soybeans_now's numbers layer 1/2 -> 2/2, the specified bar)
#   events_referenced    0/1 -> 0/1      (NOT recovered -- see the pin below for why)
#   watch_referenced     7/22 -> 7/22    unmoved
#   loud_referenced     19/26 -> 19/26   unmoved
#   spillover           18/22 -> 18/22   unmoved
# CONTROLS (HEAD -> S7): STRIPPED 11/26, 0/7, 0/22, 18/22 -> IDENTICAL. SOUP 26/26, 0/7, 6/22, 0/22
#   -> IDENTICAL. CROSSED 22/26, 5/7, 5/22, 11/22 -> 22/26, 6/7, 5/22, 11/22: recency +1, and the
#   movement is NAMED rather than explained away in the pin below.
# S6 NEGATIVE CONTROL: recency 0/7 -> 0/7. The S6 answers genuinely never stated a layer fact and the
#   fold did not invent one -- the bar the plan called non-negotiable.
# HUMAN CEILING: the human read of the same three answers found 7 of 22 watch rows used; the
#   instrument reads 7. INSTR <= HUMAN holds.
def test_S7A_the_date_fold_admits_every_DAY_PRECISE_spelling_and_no_coarser_one():
    """The ISO string is what `sb_event` prints; `1 May 2026` and `May 1, 2026` are the two ordinary
    spellings a reader writes. EVERY form names the SAME DAY.

    THE COARSER FORM WAS BUILT AND MEASURED AND REMOVED. The first cut also returned
    `month_words(iso)` (`May 2026`), on the argument that the block prints that form itself. Re-scoring
    the banked draws killed it: the CROSSED control rose from 5 of 22 watch rows to 9 of 22, i.e. the
    control rose by MORE than the real signal (7 -> 9), because the three fixtures share drivers and
    "El Nino" plus "October 2026" in another scenario's answer satisfied a watch row keyed on
    2026-10-01. A fold that lifts a control is not a fold."""
    forms = R._date_forms("2026-05-01")
    assert "2026-05-01" in forms and "1 May 2026" in forms and "May 1, 2026" in forms
    assert "May 2026" not in forms, "a month form is a coarser claim than the row's own date"
    assert not any(f.strip() in ("May", "2026") for f in forms)
    for f in forms:
        assert "2026" in f, f            # no bare month -- it would hit any sentence about spring
        assert any(ch.isdigit() for ch in f.replace("2026", "")) or f == "2026-05-01"
    assert R._date_forms("") == () and R._date_forms("not-a-date") == ("not-a-date",)
    # the group helper folds every date in a text into ONE group, de-duplicated and order-stable
    grp = R._date_group("from 2026-05-01 to 2026-05-01 and 2026-11-15")
    assert grp.count("2026-05-01") == 1 and "15 November 2026" in grp


def test_S7A_the_three_graded_classes_share_ONE_date_helper(boards):
    """One helper, three call sites (events, `_watch_tokens`, `_recency_tokens`), so the three classes
    can never drift apart on what counts as a date. Asserted on the rendered rows rather than on the
    source, because that is the property that matters."""
    seen = set()
    for ctx in boards.values():
        for m in ctx["board"].rendered_rows:
            role = m.get("role")
            if role not in ("event_open", "event_closed", "event", "watch", "recency"):
                continue
            for grp in (m.get("tokens") or ()):
                for tok in grp:
                    if R._ISO_RX.fullmatch(str(tok)):
                        seen.add(role)
                        assert set(R._date_forms(str(tok))) <= set(grp), (role, tok)
    assert {"watch", "recency"} <= seen, sorted(seen)


def test_S7B_every_added_recency_word_carries_a_SUPERLATIVE():
    """THE RULE THAT BOUNDS THE WIDENING, and it is the map's own argument. The EVIDENCE movement tells
    the writer to date every row it leans on by that row's own knowledge date, so a bare
    `knowledge date` was correctly refused -- the SUPERLATIVE is exactly what separates a claim about
    the LAYER from a claim about a ROW. Every alternative added at S7 carries one."""
    sup = ("newest", "oldest", "most recent")
    for layer, words in R._RECENCY_LAYER_WORDS.items():
        for w in words:
            if layer == "tape":
                continue                  # the tape words name the EDGE itself, not a superlative
            assert any(s in w for s in sup), (layer, w)
    assert "knowledge date" not in R._RECENCY_LAYER_WORDS["numbers"]
    assert "newest number row" in R._RECENCY_LAYER_WORDS["numbers"]


def test_S7C_the_token_window_is_ONE_sentence_and_the_refusal_is_recorded():
    """The window fold was SPECIFIED, BUILT, RE-SCORED AND REFUSED. Its own note in `render.py` carries
    the three measurements; this pin is what stops it being widened again without re-running them."""
    assert R._TOKEN_WINDOW_SENTS == 1
    sents = ["The mandate moved on 2026-05-01.", "It is a demand-side diversion."]
    groups = (("2026-05-01",), ("mandate",))
    assert R._tokens_referenced(groups, sents) is True          # both in sentence one
    split = ["The blend changed on 2026-05-01.", "The mandate is a domestic call."]
    assert R._tokens_referenced(groups, split) is False         # one apart -- and it STAYS a miss
    assert R._tokens_referenced(groups, split, window=2) is True


def test_S7_the_b40_EVENT_row_still_misses_and_the_CAUSE_is_the_NAME_not_the_date():
    """THE BAR THE PLAN SET WAS `events_referenced` 0/1 -> 1/1 AND IT IS NOT MET. Stating why is worth
    more than the counter.

    MEASURED on the banked `b40_event` draw: the date group now HITS -- sentence 0 reads "Indonesia's
    move to a forty percent palm blend, dated 1 May 2026, is a demand-side diversion", which the
    ISO-only test missed and the day-precise fold catches. What does not hit is the NAME group: that
    sentence calls the event by its CONTENT ("a forty percent palm blend"), and the nearest sentence
    carrying "mandate" is s2, with the tldr's second half between them. Recovering it would need either
    a three-sentence window (refused, see `_TOKEN_WINDOW_SENTS`) or admitting "B40" and "blend" as name
    tokens -- a vocabulary THE BLOCK DOES NOT PRINT, which is the unbounded charity `_name_words`' own
    bound exists to refuse.

    SO THE RESIDUAL IS NAMED AND THE DIRECTION IS THE SAFE ONE: the instrument UNDER-claims this row."""
    forms = R._date_forms("2026-05-01")
    s0 = ("Indonesia's move to a forty percent palm blend, dated 1 May 2026, is a demand-side "
          "diversion: it burns exportable palm inside the origin.")
    assert any(f.lower() in s0.lower() for f in forms), "the date fold must catch this sentence"
    names = R._name_words("biodiesel mandate")
    assert not any(n.lower() in s0.lower() for n in names), "the NAME is what is absent, not the date"
    assert R._tokens_referenced((forms, names), [s0]) is False

# === S7 ROUND 2 (R5): WHY THE CROSSED CONTROL CANNOT GRADE THE RECENCY CLASS ON THESE FIXTURES =====
def test_S7r2_the_CROSSED_control_is_DEGENERATE_for_recency_because_the_LAYER_FACT_is_shared(boards):
    """THE B FOLD'S +1 SHOWS UP ON THE CONTROL AS WELL AS ON THE SIGNAL, AND THIS IS WHY -- a measured
    property of the fixture set, not a leak in the fold.

    THE CROSSED control scores each board against the OTHER scenarios' answers, and "a fold that lifts
    a control is not a fold, it is a leak" is this instrument's own rule. Re-scored on the banked
    prod-seat draws, `recency_referenced` moved 5/7 -> 6/7 on the real signal AND 5/7 -> 6/7 on CROSSED.
    The rule would condemn the fold -- except that the three acceptance fixtures print the SAME recency
    lines: one as-of, one set of knowledge dates, one tape edge (2026-09-04). A recency row of board A
    satisfied by board B's answer is not cross-row bleed here; it is the same claim about the same day,
    which is what this pin measures.

    THE SHARPEST READING IS AT HEAD, WHERE THE CONTROL BEAT THE SIGNAL: `soybeans_now` scored its OWN
    recency 1 of 2 and its CROSSED recency 2 of 2, because the crossed pool is two answers of prose
    against one. A control that outscores the real read on the class it is grading is measuring the
    prose volume, not the transcription.

    SO THE +1 IS CARRIED AS A NAMED LIMIT INTO ARM A: on this fixture set, CROSSED grades the loud,
    watch and spillover classes and does NOT grade recency. Arm A's deck spans different boards with
    different as-ofs, where the layer facts diverge and the control becomes informative again."""
    lines = {}
    for name in H.SCENARIOS:
        blk = boards[name]["block"]
        lines[name] = {ln.split(":", 1)[0]: ln for ln in blk.lines if ln.startswith("RECENCY ")}
    names = sorted(lines)
    assert len(names) >= 2
    # the NUMBERS and TAPE layer lines are the SAME LINE on every fixture -- byte for byte
    for layer in ("RECENCY numbers", "RECENCY tape"):
        vals = {lines[n].get(layer) for n in names}
        assert len(vals) == 1 and None not in vals, (layer, vals)
    # ...so any answer that transcribes one board's layer fact transcribes all three
    shared = lines[names[0]]["RECENCY numbers"]
    # RE-ANCHORED 2026-09-17 ON THE CONTRACT RATHER THAN ON ONE PHRASING. The pin read the literal
    # "newest knowledge date", which is the exact wording lane A struck at the source ("'number rows'
    # and 'knowledge date' are pipeline vocabulary" -- the PM lens, on two served answers that
    # transcribed it, one of them as the bare integer 20260904). What this test is FOR is that the
    # numbers layer prints ONE shared fact the coverage scorer can see, so it asserts the date and the
    # scorer's own accepted vocabulary -- four of whose seven spellings were already desk-clean.
    assert "2026-09-04" in shared, shared
    assert any(w in shared for w in R._RECENCY_LAYER_WORDS["numbers"]), shared


# === 6. THE NOMINATION READ IS PER BULLET (S7b round 4, orchestrator ruling (7)) ==================
# THE DEFECT THIS SECTION CLOSES, measured: `_nomination_coverage`'s first cut asked `board_coverage`'s
# own `_verdict` -- a ONE-SENTENCE window carrying every one of the row's token groups -- and read 5 of
# 37 nominations used on the three S7b real-seat draws, where a human read of the same three pages
# found every one of the 13 shipped watch bullets resting on a nomination (13 of 13). The rule is now:
# A NOMINATION IS USED when its own [N] handle, or its own series key, appears in a shipped WATCH
# BULLET; A BULLET THAT MATCHES NO NOMINATION IS WRITER-ADDED; per bullet, never per sentence.
NOM_ASOF = "2026-09-07"

#: the EIGHT keys the nomination read adds, and the twenty it may never disturb (the flag-off proof).
NOMINATION_KEYS = ("watch_candidates", "watch_candidates_used", "watch_candidates_cited",
                   "watch_bullets", "watch_writer_added", "watch_admitted_zero",
                   "watch_nomination_groups", "watch_instrument_baseline")


def _nom(kind, driver, handle, *, board="CBOT soybeans", slot="ceiling", i=1, n=3, dates="",
         tokens=None, what="the reading is past the line the desk convention calls behind"):
    """ONE nomination row's MANIFEST, its line minted through THE SHIPPED BUILDER.

    `render.sb_watch` renders the line the reader meets and `_nomination_coverage` keys on that line
    and on nothing else -- the row's `handles` are EMPTY, because the backing citation is PRINTED by
    the builder rather than minted as a call. A deck that hand-typed the string would be grading its
    own typing."""
    from leviathan.graphrag.state import watch as WA
    line = R.sb_watch({"kind_words": WA.NONOBVIOUS_KIND_WORDS[kind],
                       "label": f"{driver} on {board}", "backing_handle": handle, "slot": slot,
                       "slot_size": n, "slot_index": i, "what": what, "dates": dates})
    return {"role": "watch", "line": line, "handles": (),
            "tokens": tokens if tokens is not None else ((driver,),)}


def _nom_cov(rows, page):
    """The producer, called EXACTLY as `board_coverage` calls it: positionally, page by keyword."""
    return R._nomination_coverage(rows, vf.sentences(page), lambda m: False, NOM_ASOF, text=page)


def test_S7b4_a_PARAPHRASED_bullet_that_CITES_its_row_is_USED_where_the_name_test_missed_it():
    """THE HANDLE IS THE IDENTITY THE WRITER ACTUALLY CARRIED. All three draws paraphrased the label --
    "Weekly US export sales" for `export pace lag`, "Brent" for `crude oil`, "The Pacific reading" for
    `El Nino` -- while citing the row's handle in the same breath. The estate already binds every
    printed figure to that handle (`verify._check_number_handle`); this counter now reads the same
    name, and the second assert is the RETIRED read failing on the very same bullet."""
    rows = [_nom("past_the_line", "export pace lag", 7, i=1, n=2),
            _nom("approaching_line", "board crush", 19, i=2, n=2)]
    page = ("## Mechanism\n"
            "- **Crush pull.** The board reads 1.06 USD per bushel [N19].\n"
            "## What to watch\n"
            "- **Weekly US export sales** -- already past the line the desk calls behind [N7].\n"
            "- **Board crush margin** -- running at, not through, the high line [N19].\n")
    cov = _nom_cov(rows, page)
    assert cov["watch_bullets"] == 2, "the Mechanism bullet is not a watch bullet"
    assert cov["watch_candidates"] == 2 and cov["watch_candidates_used"] == 2
    assert cov["watch_candidates_cited"] == 2 and cov["watch_writer_added"] == 0
    # THE RETIRED READ ON THE SAME BULLET: no sentence of it carries the row's own name words
    watch_bullet = R._nom_watch_bullets(page)[0]
    assert not R._tokens_referenced(rows[0]["tokens"], vf.sentences(watch_bullet))


def test_S7b4_the_identity_may_be_spread_across_the_bullet_which_no_SENTENCE_read_can_reach():
    """THE GRANULARITY, ON ITS OWN. The name is in the head of the item and the window in its tail, so
    NO single sentence carries both token groups -- the first assert is that miss, reproduced -- and
    the bullet read finds the row because the handle is somewhere in the item it is scoring."""
    rows = [_nom("approaching_line", "crude oil", 31, dates="2026-08-31 to 2027-02-28",
                 tokens=(("2027-02-28",), ("crude oil",)))]
    page = ("## What to watch\n"
            "- **Crude oil** -- below the elevated line, three months rising, about thirty-nine\n"
            "  percent of the way from zero [N31]. Its window runs to 2027-02-28.\n")
    assert not R._tokens_referenced(rows[0]["tokens"], vf.sentences(page))
    cov = _nom_cov(rows, page)
    assert cov["watch_bullets"] == 1 and cov["watch_candidates_used"] == 1
    assert cov["watch_candidates_cited"] == 1 and cov["watch_writer_added"] == 0


def test_S7b4_the_ZERO_WRITER_read_is_ALL_USED_and_NONE_ADDED_exactly():
    """THE BASELINE THE RULING ASKED FOR. The block handed back VERBATIM is the writer that added
    nothing, dropped nothing and reproduced everything, and on that input the counter reads all-used
    and none-added EXACTLY -- not approximately, which is what the retired per-sentence read could
    only manage (three to seven "added", nought to two "unused" on the nine armed cells). The banked
    constant carries BOTH floors, because the round-2 and round-3 traces were produced by the other
    one and a banked number whose floor has been deleted is a number nobody can read."""
    rows = [_nom(k, d, h, i=i, n=4) for i, (k, d, h) in enumerate(
        (("past_the_line", "export pace lag", 7), ("approaching_line", "board crush", 19),
         ("spillover_reach", "crude oil", 31),
         ("recurrence", "Argentina export registration", 10)), 1)]
    page = "\n".join(m["line"] for m in rows)        # no heading: the block writes none
    cov = _nom_cov(rows, page)
    assert cov["watch_bullets"] == 4 and cov["watch_writer_added"] == 0
    assert cov["watch_candidates"] == 4 == cov["watch_candidates_used"] == cov["watch_candidates_cited"]
    base = R.NOMINATION_ZERO_WRITER_BASELINE
    assert base["bullet_added_at_zero_writer"] == 0
    assert base["bullet_used_short_at_zero_writer"] == 0
    assert base["bullet_exact"] is True
    assert cov["watch_instrument_baseline"] == dict(base)
    # the RETIRED read's four keys are kept, unchanged, and are NOT the shipped read's
    assert base["added_at_zero_writer_max"] == 7 and base["cells"] == 9


def test_S7b4_a_bullet_resting_on_NO_nomination_is_WRITER_ADDED_against_its_own_denominator():
    """THE ONE THING THE SELECTION LICENCE BOUNDS is the writer's OWN item, and "1 added" is a fact
    about a page only beside the number of bullets that page shipped -- which is why `watch_bullets`
    ships beside it and the first cut, which had no denominator at all, could not be read as a rate."""
    rows = [_nom("past_the_line", "export pace lag", 7)]
    page = ("## What to watch\n"
            "- **Weekly US export sales** [N7]: past the line the desk calls behind.\n"
            "- **The Gulf basis**: the writer's own item, on no row this board printed.\n")
    cov = _nom_cov(rows, page)
    assert cov["watch_bullets"] == 2 and cov["watch_writer_added"] == 1
    assert cov["watch_candidates_used"] == 1 and cov["watch_candidates"] == 1


def test_S7b4_the_SERIES_KEY_leg_is_the_LOOSE_half_and_is_reported_APART():
    """`watch_candidates_cited` IS THE TIGHT READ and is <= `watch_candidates_used` by construction.
    The key leg carries `_name_words`' one relaxation -- the last word alone at five characters or
    more -- so "the drought reading" finds `flash drought`; a reader who wants the count that rests on
    a citation alone is given it rather than having to guess which half is which. MEASURED on the three
    real-seat draws the two are EQUAL (25 and 25): every match those pages made was a citation."""
    rows = [_nom("approaching_line", "flash drought", 28)]
    page = "## What to watch\n- The drought reading has not crossed its line.\n"
    cov = _nom_cov(rows, page)
    assert cov["watch_candidates_used"] == 1
    assert cov["watch_candidates_cited"] == 0
    assert cov["watch_writer_added"] == 0
    assert cov["watch_candidates_cited"] <= cov["watch_candidates_used"] <= cov["watch_candidates"]


def test_S7b4_a_CORE_and_its_ALTERNATE_share_one_backing_row_and_ONE_bullet_marks_BOTH_used():
    """THE OVER-CLAIM, DECLARED. The draw hands 2N candidates and the core and the alternate on one
    reading share one backing [N], so one bullet citing that handle marks BOTH used -- MEASURED 25 of
    37 on the three draws against 13 bullets. That is the honest reading of "the writer kept this
    READING"; which KIND it kept is not recoverable from a paraphrased bullet, and a counter that
    guessed would be measuring the guess. The BULLET side stays exact: one bullet, none added."""
    rows = [_nom("past_the_line", "export pace lag", 7, slot="ceiling", i=1, n=1),
            _nom("spillover_reach", "export pace lag", 7, slot="nomination", i=1, n=1)]
    page = "## What to watch\n- **Weekly US export sales** [N7]: past the line.\n"
    cov = _nom_cov(rows, page)
    assert cov["watch_candidates"] == 2 and cov["watch_candidates_used"] == 2
    assert cov["watch_bullets"] == 1 and cov["watch_writer_added"] == 0


def test_S7b4_board_coverage_hands_the_PAGE_to_the_nomination_read_and_not_its_sentences():
    """THE SEAM ITSELF. A bullet is a LIST ITEM and only the un-split text carries one, so
    `board_coverage` threads `text=` and not `sents`. If a later edit reverted that, every counter
    below would read zero on a page whose watch list is plainly there -- which is what this pin
    catches. The key count is the other half: TWENTY-TWO from the board and eight from the nomination
    read -- HEAD's twenty plus ROUND-2 DOCKET item 12's two lead counters (review round 3: this line
    said twenty over an assertion of thirty, and a stale count in a pin is the defect the pin is for)."""
    import types
    rows = [_nom("past_the_line", "export pace lag", 7)]
    bd = types.SimpleNamespace(rendered_rows=rows, asof=NOM_ASOF, knobs=None, calls=())
    page = "## What to watch\n- **Weekly US export sales** [N7]: past the line.\n"
    cov = R.board_coverage(bd, page, n_start=1, calls=())
    # TWENTY-TWO FROM THE BOARD AND EIGHT FROM THE NOMINATION READ (ROUND-2 DOCKET item 12 added
    # `loud_lead_rows` and `loud_lead_referenced`: the three readings the block LEADS with, graded
    # apart from the loud set so 'the top three are named or their omission explained' is a number).
    assert set(NOMINATION_KEYS) <= set(cov) and len(cov) == 30
    assert cov["watch_bullets"] == 1 and cov["watch_candidates_used"] == 1
    assert cov["watch_writer_added"] == 0


def test_S7b4_the_flag_off_coverage_keeps_HEADS_TWENTY_KEYS_on_every_banked_page(boards):
    """FLAG-OFF BYTE IDENTITY, the contract this whole lane ships under. With the non-obvious flag OFF
    the block carries HEAD's five watch kinds, `_nomination_coverage` returns `{}` BEFORE it reads the
    page, and `board_coverage` returns TWENTY-TWO keys -- HEAD's twenty plus ROUND-2 DOCKET item 12's
    two BOARD-SIDE lead counters, which are unconditional and are NOT the eight the flag adds -- on the
    empty page, on a page of prose, and on each of the SIXTEEN banked census blocks handed to each of
    the three acceptance fixtures. A zero-filled block of eight keys would have failed this on every
    turn and would have fabricated a `0 of 0` inside the arm's own new dimension. (Review round 3: the
    name and this sentence both still said TWENTY over an assertion of twenty-two.)"""
    import pathlib as _pl
    banked = (_pl.Path(__file__).resolve().parents[2] / "data" / "board_census" / "2026-09-07"
              / "blocks")
    pages = ["", "nothing in particular"]
    if banked.exists():
        pages += [p.read_text(encoding="utf-8") for p in sorted(banked.glob("*.md"))]
        assert len(pages) == 18, len(pages)
    for name in H.SCENARIOS:
        ctx = boards[name]
        for page in pages:
            cov = R.board_coverage(ctx["board"], page, n_start=1, calls=ctx["block"].calls)
            # 20 -> 22: the two DOCKET-12 lead counters. They are BOARD-side and unconditional, so
            # the non-obvious flag still adds exactly its own eight keys and never a zero-filled
            # block -- which is what this pin exists to catch.
            assert len(cov) == 22, (name, sorted(cov))
            assert {'loud_lead_rows', 'loud_lead_referenced'} <= set(cov)
            assert 'loud_top3' in cov['missed']
            assert not [k for k in NOMINATION_KEYS if k in cov], (name, sorted(cov))


def test_S8R2_the_chain_OUTCOME_rows_carry_a_ROLE_so_no_census_can_count_them_as_NON_CHAIN():
    """**ROUND-2, the review's MINOR 4, and it is an ARITHMETIC defect and not a cosmetic one.**

    ``Block.add`` writes ``role``, ``rank``, ``cls``, ``handles``, ``tokens`` and ``line`` into the
    coverage manifest and writes NO ``label`` -- ``label`` rides ``self.trips``, where it is telemetry.
    Both chain-outcome branches (the SB-O row that mints, and its letters-only absence) passed neither,
    so every instrument that selects chain rows by ``role`` OR ``label`` -- the lane's own census, the
    round-2 census, and the "every chain line" pins -- MISSED them, and their bytes were then counted
    as NON-CHAIN block bytes.

    MEASURED on the receipt-carrying max cell: 85 characters per rendered chain, 255 on the page, which
    is the whole of the round-2 census's reported 83-character A.8 miss and then some -- non-chain max
    reads 25,825 with the rows attributed where they belong against the 26,083 the census reported, so
    the cell PASSES by 175 where it was read as FAILING by 83."""
    import inspect
    import re
    body = inspect.getsource(R.render_board)
    assert body.count('role="chain_outcome"') == 2, \
        "the minting row AND its letters-only absence, one role between them"
    # THE CAUSE, pinned so it cannot come back: the manifest carries no label to fall back on.
    b = R.Block(start=1)
    b.add("  chain price record: the front price here does not reach those firings.",
          label="chain soybeans_cbot a/b outcome absence", display="the price record",
          role="chain_outcome", rank=1)
    assert "label" not in b.rows_meta[0]
    assert b.rows_meta[0]["role"] == "chain_outcome"
    # ...and every chain role this block can stamp begins with the one word a census selects on.
    roles = {m for m in re.findall(r'role="([a-z_]+)"', body) if "chain" in m}
    assert roles and all(m.startswith("chain") for m in roles), roles


def test_S8R3_the_SLOT_LABEL_adds_no_coverage_key_and_moves_no_coverage_DENOMINATOR():
    """**OWNER RULING 2026-09-22 (the render slots), read on the COVERAGE surface.**

    The slot label is a clause on the chain's head row naming the seat the selection held for it. It
    is PROSE, not a new population: the head row's token groups are the chain's first hop and the
    market it reaches, and a label must not join them -- a writer who copied "the other side" would
    otherwise score as having referenced the chain, which would make the label a way to inflate the
    very counter it rides beside.

    So this pin holds two things at once: the chain counter roster is UNCHANGED by the ruling (no
    twelfth key), and the head row's token groups are computed from the hop and the terminal alone."""
    import inspect
    import re as _re

    from leviathan.graphrag.state import render as _R
    from leviathan.graphrag.state import walk as _W
    body = inspect.getsource(_R.render_board)
    emitted = set(_re.findall(r'"(chain[a-z_]*)":', inspect.getsource(_R._chain_coverage)))
    assert emitted == set(CHAIN_COVERAGE_KEYS), sorted(emitted)
    assert '"missed_chains"' in inspect.getsource(_R._chain_coverage),         "the twelfth key is the round-1 debt this roster already names, not the ruling's"
    # THE HEAD ROW'S TOKENS ARE THE HOP AND THE MARKET, and the label is in neither.
    tok = body.split("_tok = (", 1)[1].split(")\n", 1)[0]
    assert "_name_words(humanise(_c.hops[0].driver_id))" in tok
    assert "_market_words(_c.terminal or _c.contract)" in tok
    assert "slot" not in tok, "a label is prose on the row, never a token group the writer is graded on"
    # AND THE LABEL IS REALLY ON THE ROW, on a real `walk.Chain`, in the ruling's own words.
    ch = _W.Chain(contract="soybeans_cbot",
                  hops=(_W.ChainHop(contract="soybeans_cbot", driver_id="export_pace_lag",
                                    measured=True, percentile=13.0),),
                  terminal="corn_cbot")
    ch.rendered = ch.full = True
    plain = _R.sb_chain_head(ch, i=1, n=2)
    for slot, words in _R.CHAIN_SLOT_WORDS.items():
        ch.slot = slot
        got = _R.sb_chain_head(ch, i=1, n=2)
        assert words in got and len(got) == len(plain) + len(words) + 2, slot
    ch.slot = "top"
    assert _R.sb_chain_head(ch, i=1, n=2) == plain


def test_S8R4_the_ROUND_FOUR_clauses_add_no_coverage_key_and_move_no_coverage_DENOMINATOR():
    """**THE FOUR ROUND-4 SURFACES, READ ON THE COVERAGE SURFACE.**

    The aged-out count, the outcome's denominator, the terminal edge's declared lag and the stanza
    mark are all PROSE on rows that already exist. None of them is a new population, none adds a
    counter, and none may join a row's token groups -- a writer who copied "aged out of their
    windows" must not thereby score as having referenced a chain, which would make an honest absence
    clause a way to inflate the very counter it rides beside.

    AND THE CHAIN ORDINAL NOW FOLLOWS THE RANK (round-4 MINOR 2), which is a change of ORDER and not
    of MEMBERSHIP: the same chains render, so the coverage denominator is the same set."""
    import inspect
    import re as _re

    from leviathan.graphrag.state import render as _R
    from leviathan.graphrag.state import walk as _W
    body = inspect.getsource(_R.render_board)
    emitted = set(_re.findall(r'"(chain[a-z_]*)":', inspect.getsource(_R._chain_coverage)))
    assert emitted == set(CHAIN_COVERAGE_KEYS), sorted(emitted)
    # THE HEAD ROW'S TOKENS ARE STILL THE HOP AND THE MARKET, and no round-4 clause is in them.
    tok = body.split("_tok = (", 1)[1].split(")\n", 1)[0]
    for word in ("aged", "slot", "n_in", "first_dim", "declared lag"):
        assert word not in tok, word
    # THE RENDERED SET IS THE SAME SET, ordered by rank rather than by the pool's composition order.
    pool = []
    for i, (driver, score) in enumerate((("export_pace_lag", 20.0), ("La_Nina", 30.0),
                                         ("RFS", 25.0))):
        c = _W.Chain(contract="soybeans_cbot",
                     hops=(_W.ChainHop(contract="soybeans_cbot", driver_id=driver, measured=True,
                                       percentile=13.0 + i, series_key="s%d" % i),),
                     terminal="soybeans_cbot")
        c.score, c.rendered, c.full = score, True, True
        pool.append(c)
    ranked = sorted(pool, key=lambda c: c.rank)
    assert [c.hops[0].driver_id for c in ranked] == ["La_Nina", "RFS", "export_pace_lag"]
    assert sorted(map(id, ranked)) == sorted(map(id, pool)), "an ORDER, never a membership"
    # AND THE COUNT LINE'S AGED CLAUSE IS ABSENT AT ZERO and letters-only when it fires.
    counts = {"distinct_sequences": 9, "total": 12, "state_two_hops": 4, "with_document": 3}
    assert "aged out" not in _R.sb_chain_count(counts, k=2, aged=0)
    fired = _R.sb_chain_count(counts, k=2, aged=3)
    assert "three dated actions aged out of their windows" in fired, fired
    assert _R.classify(fired) == ("SB-P",) and _R.register_hits(fired) == []
