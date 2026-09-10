"""THE BOARD -- the container the walk fills and the writer is handed. STATE ENGINE DESIGN sec 1.2 (the
row schema and the `Board` block), 1.3 (coverage tiers as rows), 3.1 (the anchor and `anchor.source`),
3.8 (the two-wave budget ledger and its rectangle), 3.9 (what the board hands `quantify`) and 6.7 (the
closed decline vocabulary every leg stamps). Sitting S2.

WHAT THIS MODULE IS. Data and vocabulary: the anchor record, the node row, the two wave ledgers, the
board itself, and the ELEVEN closed reason enums of sec 6.7. It computes no state (that is
``feeders.py``), decides no order (that is ``walk.py``) and renders no line (that is S3's
``render.py``). The split is deliberate -- a container that could also rank would be a second ranker.

THREE PROPERTIES THIS MODULE EXISTS TO MAKE UNBREAKABLE, each of which is a bar in sec 10.2:

  1. **THE RECTANGLE CLOSES AT EVERY RETURN** (B1). ``series_declared == read + deferred + declined`` on
     BOTH waves, checked by :meth:`WaveLedger.closed` and asserted by :meth:`Board.rectangle`. The walk's
     own law (``_cw_board_row_closed``, cascade.py:7385) says why: a budget cut that does not close a
     rectangle is indistinguishable from a row nobody asked for, and a reader cannot tell "we did not
     look" from "there was nothing there".
  2. **THE PLAN IS WRITTEN BEFORE THE FETCH** (B3). :meth:`WaveLedger.plan_written` stamps a monotonic
     sequence number, :meth:`WaveLedger.note_fetch` stamps another, and
     :meth:`WaveLedger.priced_before_fetch` is the predicate. `_transmission_legs` prices `net = 2 *
     len(su_keys)` before any fetch (cascade.py:5880) and that is the shape the board takes; `CASCADE_CAP`
     truncating AFTER the build by walk order (:1515) is the shape it replaces.
  3. **EVERY LEG SAYS WHAT HAPPENED** (B13). ``outcome in {fired, declined, not_reached}`` with a reason
     from that leg's OWN closed enum, and ``not_reached`` stamped by the ORCHESTRATING walk -- a leg
     cannot stamp its own absence, which is the hole the reading's 4.8 measured (`rv_reading_decline`
     None on 12 of 12 because the leg was never REACHED on 10).

NOTHING HERE READS AN ENVIRONMENT AND NOTHING HERE IS WIRED INTO THE SERVE PATH. The board reaches
``quantify`` through ONE omit-when-off ``board=`` kwarg at S6 (sec 3.9, D8); :meth:`Board.request` is
that payload's shape, built here so S6 threads a thing that already exists.

ASCII-ONLY on anything this package prints; the file itself is UTF-8.
"""
from __future__ import annotations

import itertools
from dataclasses import asdict, dataclass, field
from typing import NamedTuple, Optional

from leviathan.graphrag.state.lagbands import LagBand
from leviathan.graphrag.state.rows import StateRow

# ---------------------------------------------------------------------------------------------------
# THE PER-MODE KNOBS (sec 7). The VALUES live on the mode table in `reasoning_modes.BOARD_PRESETS`;
# this NamedTuple is the shape, so no consumer indexes the tuple by position.
# ---------------------------------------------------------------------------------------------------
class BoardKnobs(NamedTuple):
    """The nine per-mode board constants of sec 7, in the design's OWN declared order, plus the SEVEN
    RENDER CAPS S6 appended after them and the TWO BOUNDS its review appended after those.

    ``(loud_k, fan_k, analog_k, analog_dims, board_admit_k, wave1, wave2, receipt_cap, path_render_k)``
    -- the order is the design's and is not re-sorted here, because the same nine ride the ``Mode``
    table as ONE appended tuple field when S6 lands it (`k_by_depth`'s precedent, reasoning_modes.py:145
    "a TUPLE so the dataclass stays hashable and the table stays immutable").

    THE SEVEN RENDER CAPS ARE APPENDED WITH DEFAULTS, and both halves of that sentence are load-bearing.
    APPENDED, because sec 7 declares nine and a nine-tuple from any caller (the S2 fixtures, the census,
    a hand-built preset) must keep working -- ``BoardKnobs(*t)`` over a nine-entry tuple still resolves.
    WITH DEFAULTS DRAWN FROM THE SHIPPED TABLES, because the values already live in three places S3
    wrote them into (``render.RENDER_CAPS``, ``watch.WATCH_RENDER_K``, and ``path_render_k`` here), so a
    knob that defaulted to anything else would be a second opinion about a number the render already
    holds. (Drawn from ANALYSIS's row -- see the closing note; a NamedTuple has one default per field
    and the estate has three tiers.)

    THE DEFAULTS ARE THE DESIGN'S PLANNED SIZES; THE MEASURED SIZES ARE RECORDED BESIDE THEM AND S7
    DECIDES (design sec 7, the S2/S3 overrun). Sec 7 sizes the block at Scan ~17-20 lines / ~1,100
    tokens, Analysis ~40 / ~2,400 and Cascade ~66-80 / ~3,900.

    THE CENSUS, ALL THREE TIERS, measured through `state.seam` (`fill_stage1` + `fill_stage2`, as-of
    2026-09-07, the offline `fixture_state_fn`, zero reads), RE-MEASURED AT THE S6 RE-FIX and now
    carrying the MULTI-ANCHOR shapes beside the single-anchor one -- because every bound this class
    declares is a per-tier number and the block's size is not: it is a per-ANCHOR number, and a table
    that records only the one-anchor turn records the shape a real question least often asks for.

    THE CENSUS NAMES ITS OWN INPUTS, so a row can be re-run rather than believed (S6 second verify,
    minor (c)). It recorded a producer and an as-of but not the QUERY or the FOCUS DRIVER, and the
    focus-driver row cannot be reproduced without both -- the shipped graph carries three widely-shared
    drivers (`El_Nino` 35 boards, `heat_stress` 35, `crude_oil` 24) and they measure 127 / 109 / 142
    rows at Scan, so "a widely-shared driver" names three different tables. Every row below is:

        query          "El Nino is developing: what does it do to soybeans?"
        focus driver   `El_Nino` (the focus-driver row only; the other two pass none)
        seeds          `sg.seeds = ["soybeans_cbot"]`, except the four-market row, which seeds all four
        named          the seeds themselves, except the FOCUS-DRIVER row, which passes `named=()`
        anchors        `max_contracts=6` on the focus-driver row, the default 2 on the other two
        as-of          2026-09-07, `state.__main__.fixture_state_fn`, `qfn=lambda *a, **k: []`

    THE QUERY MOVES NOTHING TODAY and is named anyway. Measured: the one-market Scan block is
    53 rows / 13,206 chars under that question, under `""`, under `"soybeans"` and under a fourth
    phrasing -- byte-identical, because the seam threads the question to `walk(question=...)` and no
    ROW reads it. Naming it is what makes that fact checkable instead of assumed, and what stops the
    next re-measure from silently comparing two different turns.

        shape (anchors)              tier       rows    chars   est tokens  vs plan (rows / tokens)
        one named market (1)         Scan         53   13,206     ~3,302      x2.65 / x3.00
                                     Analysis     77   19,746     ~4,937      x1.93 / x2.06
                                     Cascade      98   25,354     ~6,339      x1.23 / x1.63
        four named markets (4)       Scan         92   23,920     ~5,980      x4.60 / x5.44
                                     Analysis    137   36,941     ~9,235      x3.42 / x3.85
                                     Cascade     180   48,630    ~12,158      x2.25 / x3.12
        `focus_driver` at the        Scan        127   31,538     ~7,885      x6.35 / x7.17
        anchor ceiling (4 / 6 / 8)   Analysis    198   50,476    ~12,619      x4.95 / x5.26
                                     Cascade     259   66,836    ~16,709      x3.24 / x4.28

    RE-MEASURED AT THE S6 SECOND VERIFY on the tree that carries the assembled-row fences
    (`render.sb_amplifier`, `render.sb_receipt`). EVERY ROW COUNT IS UNCHANGED and the character counts
    moved by -50 to +90 -- the fences are byte-identity on all fifteen anchor shapes of the shipped
    graph, so the drift is other S6 edits, not this one. What was re-measured is the three columns
    above; the class-share sentence at the foot of this docstring is the earlier build's measurement and
    was NOT re-run, which is said here rather than left for a reader to assume either way.

    plus the mandate itself, 2,521 chars / ~630 tokens, on every fired turn (it was 2,029 / ~507 before
    the S6 review rewrote it to state an ORDER OF IDEAS under the response contract's own headings --
    see `narration.MANDATE_MOVEMENTS`). THE S6 BUILD RECORDED ONLY THE TWO PAID TIERS and called the
    overrun "~24-88%"; the review measured SCAN at +200% and it is the FREE tier, priced by sec 7 at
    "+~700 uncached input tokens ($0.0035)" against a measured ~3,932 (block + mandate), i.e. 5.6x, on
    a tier with no credit to pay for it. Restated in money, because the arm's covenant is stated in
    money: the block is VOLATILE (post-cache-breakpoint), so at $5/MTok the one-anchor turn is ~$0.020 /
    $0.028 / $0.035 against sec 7's ~$0.0035 / $0.0075 / $0.015 -- and the anchor-ceiling turn is
    ~$0.043 / $0.066 / $0.087, which is the number the anchor bound made FINITE rather than small.
    THE ANCHOR CEILING IS WHAT S6 BOUNDS; THE PER-ANCHOR SIZE IS S7's (declared not-done).

    NOTHING IN THE SEVEN PER-CLASS CAPS IS TIGHTENED HERE, and the reason is that tightening them could
    not have helped: by CHARACTERS, the classes with no cap field at all (SB-1, SB-E, SB-J, SB-T, SB-L,
    SB-H) plus SB-X are 79.5% of the Scan block, 71.5% of Analysis and 62.6% of Cascade, and SB-X alone
    is 30.6 / 22.0 / 18.7% -- the single largest class on all three tiers. A cap change is a
    prompt-content change and arm A must measure ONE instrument, so the seven keep today's values and
    S7 decides which of them moves. WHAT S6'S REVIEW DOES CHANGE is the two bounds that are not per-class
    at all and that no S7 knob could reach: ``max_anchors`` and ``render_absence_names``. Both were
    measured UNBOUNDED and both are bounded by a USER GESTURE rather than by a tier --

      * a `focus_driver` turn (an FE attachment or a weather advisory, `_resolve_attachments`) anchors
        EVERY contract carrying the id by design, MEASURED at 24 anchors for `crude_oil` and 35 for
        `El_Nino` / `heat_stress`. At 35 the declared cap becomes 59 / 85 / 106 against the design's
        24 / 50 / 71 (the tape column is one seat per anchor), so `cw_ceiling` becomes 119 / 165 / 186
        against 60 / 80 / 80 -- the walk's runaway tripwire more than doubled by a gesture. The block
        measured 916 rows / 149,815 chars (~37,450 tokens) at max, and 171,852 chars / ~43,000 tokens
        on the FREE tier;
      * ONE `BOARD ABSENCE` line measured 23,871 characters on that turn, because the absence row names
        every unread row and "the NAMES are never cut". Sec 3.6's "the fan index is free" is about the
        FAN, and a free index is not a free ENUMERATION inside one line.

    ``render_absence`` (GROUPS) stays 0 = UNCAPPED = today's behaviour, exactly as the design plans no
    number for it; ``render_absence_names`` bounds the NAMES within a group and states the remainder as
    a count, which keeps "every cut names what it cut" true while making the line's length a tier fact
    rather than an estate fact.

    WHY A NamedTuple AND NOT A DICT: a dict of nine keys is nine chances to typo a knob name at a call
    site and get ``None`` back silently; an attribute access on a wrong name raises. The board's caps
    are the one thing in this design that must never fail open.

    THE DEFAULTS BELOW ARE ANALYSIS'S ROW, not a fourth table, and that is a property of a NamedTuple
    rather than a decision: there is ONE default per field and there are THREE shipped tiers. Every
    SHIPPED path passes a full row (`board_knobs_of` reads `BOARD_PRESETS`, and `check_state_seam`
    clause (v) pins every row against `check_knobs`), so the defaults are reachable only from a
    hand-built tuple -- an S2 fixture, a census row, an arm's preset -- built with fewer fields than the
    table declares. Such a tuple renders at ANALYSIS caps on quick and on max, silently. The docstring
    used to say the defaults "equal the shipped tables", which is true of no single tier; it says what
    it does now.
    """

    loud_k: int          # the rank cut per anchor board (Scan 8 / Analysis 16 / Cascade 24)
    fan_k: int           # far BOARDS per loud driver whose STATE may be priced (4 / 8 / 16). Names are
    #                      NEVER cut by this or anything else -- the fan index is free (sec 3.6).
    analog_k: int        # analogs selected per analog dimension (0 / 1 / 2)
    analog_dims: int     # the top-N loud rows that may BE analog dimensions (0 / 3 / 5)
    board_admit_k: int   # phase-3's must-admit set for `grounded_subgraph`'s own pot (4 / 8 / 12)
    wave1: int           # the anchor-DAG state-key cap (24 / 32 / 40)
    wave2: int           # the TOTAL wave-2 cap (0 / 18 / 58); its four columns derive -- `wave2_shape`
    receipt_cap: int     # analog receipts on the EVIDENCE pool, counted (0 / 3 / 5)
    path_render_k: int   # SB-P rows RENDERED (2 / 4 / 8). The closure is walked WHOLE on every tier.
    # -- S6: THE RENDER CAPS, appended LAST, defaults = the shipped tables (the design's planned sizes).
    render_spillover: int = 8          # SB-F + far SB-E lines  (4 / 8 / 16)   [measured: the SB-E class
    #                                    is the third-largest on the Cascade board]
    render_convergence: int = 4        # SB-C patterns          (2 / 4 / 6)
    render_analog: int = 1             # LIKE STATE stanzas     (0 / 1 / 2)
    render_analog_outcomes: int = 4    # SB-O rows per stanza   (0 / 4 / 4)
    render_receipts: int = 3           # SB-R rows per loud row (0 / 3 / 5)
    render_watch: int = 6              # SB-W + SB-V rows       (3 / 6 / 8) -- `watch.WATCH_RENDER_K`
    render_absence: int = 0            # SB-X GROUPS; 0 = UNCAPPED, which is today's behaviour and the
    #                                    design's own plan (it names no absence number). MEASURED the
    #                                    LARGEST class on both tiers, which is why it gets a knob now.
    # -- S6 REVIEW: THE TWO BOUNDS THE FIRST BUILD LEFT OPEN. Both are ANCHOR-side or NAME-side, i.e.
    #    they bound the one dimension every per-CLASS cap above is blind to.
    max_anchors: int = 6               # the TOTAL anchor boards a board may carry (4 / 6 / 8). See the
    #                                    note below: this is the term that made the declared cap, the
    #                                    tape column, the render and the pre-writer wall all scale with
    #                                    a user gesture rather than with a tier.
    render_absence_names: int = 24     # NAMES printed inside one SB-X line (16 / 24 / 32); the
    #                                    remainder is stated as a COUNT, so the row still says what it
    #                                    cut. 0 = uncapped.


#: Reads per leg-B tape cell -- ``cascade.CW_READS_PER_CELL`` (:6411), restated rather than imported so
#: this module stays lane-free while the K9 lane holds that file. ``feeders.CASCADE_IMPORTS`` is the
#: place a cascade SYMBOL is pinned; this is a NUMBER, and sec 3.8 states it twice ("9 cells x 3 = 27
#: reads = CW_DEEP_CAP 27"), so the arithmetic below is falsifiable against the design without an import.
READS_PER_CELL = 3

#: The leg-B tape CELLS a tier DECLARES, by base mode (sec 3.8: "9 cells x 3 = 27 reads = `CW_DEEP_CAP`
#: 27"). DECLARED is not ARMED: leg B rides ``GRAPHRAG_STATE_BOARD_ANALOG_TAPE`` behind the P2 span
#: probe (sec 4.3, D6) and ships dark, which is why :func:`wave2_shape` takes the cells and the rider
#: SEPARATELY -- see the note there, which is a defect this sitting measured rather than a nicety.
LEGB_CELLS: dict = {"quick": 0, "deep": 0, "max": 9}


def legb_cells_of(mode: str) -> int:
    """The tier's DECLARED leg-B cells. Keyed on the base preset, like every other tier table."""
    from leviathan.graphrag import reasoning_modes as rm
    return int(LEGB_CELLS.get(rm.base_mode(mode), 0))


def wave2_shape(k: BoardKnobs, *, legb_cells: int = 0, legb_on: bool = False,
                analog_reads: bool = True) -> dict:
    """The FOUR wave-2 columns of sec 3.8's table, DERIVED from the nine knobs. Returns
    ``{far, analog_benchmark, analog_receipts, legb, total}``.

    THE COLUMNS ARE NOT A SECOND TABLE, and proving that was worth the arithmetic: sec 3.8 prints
    Analysis as ``32 | 12 | 3 | 3 | 0 | 50`` and Cascade as ``40 | 16 | 10 | 5 | 27 | 98``, and every one
    of those wave-2 numbers falls out of the knobs --

        analog_benchmark = analog_dims * analog_k          (1 per top-3 -> 3; 2 per top-5 -> 10)
        analog_receipts  = min(analog_dims * analog_k, receipt_cap)   (3 -> 3; 10 candidates cut to 5)
        legb_declared    = legb_cells * READS_PER_CELL     (0; 9 x 3 = 27)
        far              = wave2 - the three above         (18 - 3 - 3 - 0 = 12; 58 - 10 - 5 - 27 = 16)

    -- so the far-key cap is the RESIDUAL against the DECLARED leg-B column, and a knob edit can never
    leave the columns and the total disagreeing. :func:`check_knobs` pins the identity.

    **`legb_cells` AND `legb_on` ARE TWO ARGUMENTS, AND THE FIRST BUILD OF THIS FUNCTION HAD ONLY ONE.**
    That was a real defect, MEASURED on the first walk over the shipped soybean DAG: with leg B dark the
    single-argument form made `legb` zero and the residual handed its 27 reads to the FAR column, so
    Cascade priced 43 far keys against a design that says 16 -- a wave-2 budget 27 reads larger than the
    tier's own "71 with leg B dark" line, arrived at silently, by arithmetic. The declared cells set the
    RESIDUAL; the rider sets whether the column is SPENT. Dark leg B therefore lowers the wave-2 TOTAL
    (58 -> 31 on Cascade) and moves no other column, which is what "with leg B dark" means.

    **`analog_reads` IS THE SAME ARGUMENT SHAPE FOR THE ANALOG COLUMNS, AND IT IS THE S6 REVIEW'S OWN
    DEFECT.** The two analog columns are read by producers the CALLER injects -- `benchmark_fn` and
    `receipt_fn` -- and phase 2's seam wires neither, so `analogs._outcomes_for` and
    `analogs._receipts_for` return at zero reads. Those 3-10 (Analysis) / 5-15 (Cascade) seats were
    still reserved against the cap and therefore entered the WALK's own ceiling through
    `cascade._board_declared_cap`: up to 15 reads a turn that no producer could ever spend, on a
    tripwire whose whole job is to notice a runaway. This flag follows leg B's precedent exactly --
    the DECLARED cells set the residual, the rider sets whether the column is SPENT -- so an unwired
    analog leg lowers the TOTAL and moves no other column. The day the seam wires either producer the
    caller passes True and the tier's declared table is back, unchanged."""
    bench = max(0, int(k.analog_dims) * int(k.analog_k))
    receipts = min(bench, max(0, int(k.receipt_cap)))
    declared_bench, declared_receipts = bench, receipts
    if not analog_reads:
        bench = receipts = 0
    declared_legb = max(0, int(legb_cells)) * READS_PER_CELL
    # FLOORED AT ZERO so an over-committed knob table cannot mint a NEGATIVE slice at the pricer (which
    # Python would read as "all but the last thirty", i.e. a cap that silently becomes a different cap).
    # An over-commitment is a LINT ERROR (`check_knobs`), and the pricer's own trim order of sec 3.8 is
    # what handles it at runtime -- floored here, trimmed there, flagged in both places.
    far = max(0, int(k.wave2) - declared_bench - declared_receipts - declared_legb)
    legb = declared_legb if legb_on else 0
    return {"far": far, "analog_benchmark": bench, "analog_receipts": receipts, "legb": legb,
            "legb_declared": declared_legb, "analog_benchmark_declared": declared_bench,
            "analog_receipts_declared": declared_receipts,
            "total": min(int(k.wave2), far + bench + receipts + legb)}


def check_knobs(k: BoardKnobs, *, legb_cells: int = 0) -> list:
    """Every arithmetic identity sec 7 and sec 3.8 assert about ONE mode's knobs. Empty list = clean.

    This is the lint shape of ``config_check``'s own per-wave checks, kept in-module because the knobs
    are code rather than config. It is what makes the residual far-cap of :func:`wave2_shape` safe: a
    negative residual means the wave-2 total no longer covers its own declared columns, which is a
    silently over-committed budget -- the exact defect revision 1 shipped three ways (sec 3.8)."""
    errs = []
    for name in BoardKnobs._fields:
        v = getattr(k, name)
        if not isinstance(v, int) or isinstance(v, bool) or v < 0:
            errs.append(f"board knob {name}={v!r} is not a non-negative int")
    if errs:
        return errs
    sh = wave2_shape(k, legb_cells=legb_cells, legb_on=True)
    residual = int(k.wave2) - sh["analog_benchmark"] - sh["analog_receipts"] - sh["legb_declared"]
    if residual < 0:
        errs.append(f"board knobs: wave2={k.wave2} is smaller than its own declared columns "
                    f"(benchmark {sh['analog_benchmark']} + receipts {sh['analog_receipts']} + leg-B "
                    f"{sh['legb_declared']}) -- the far-key cap would be {residual}, i.e. the budget "
                    f"is over-committed before a single key is priced")
    if sh["total"] != int(k.wave2):
        errs.append(f"board knobs: the wave-2 columns sum to {sh['total']}, not wave2={k.wave2}")
    dark = wave2_shape(k, legb_cells=legb_cells, legb_on=False)
    if dark["total"] != int(k.wave2) - sh["legb_declared"]:
        errs.append("board knobs: darkening leg B must lower the wave-2 total by exactly its own "
                    "declared column and move no other column")
    adark = wave2_shape(k, legb_cells=legb_cells, legb_on=True, analog_reads=False)
    if adark["total"] != int(k.wave2) - sh["analog_benchmark"] - sh["analog_receipts"]:
        errs.append("board knobs: an unwired analog leg must lower the wave-2 total by exactly its own "
                    "two declared columns and move no other column -- the leg-B identity, one column "
                    "pair over. Freeing those reads INTO the far residual is the measured defect this "
                    "clause exists to catch")
    if adark["far"] != sh["far"]:
        errs.append(f"board knobs: the far residual moved with the analog rider ({sh['far']} -> "
                    f"{adark['far']}); the DECLARED columns set the residual and the rider sets only "
                    f"whether a column is spent")
    if k.max_anchors < 1:
        errs.append("board knobs: max_anchors must admit at least one anchor board")
    if k.receipt_cap > k.analog_dims * k.analog_k and k.analog_k:
        errs.append(f"board knobs: receipt_cap {k.receipt_cap} exceeds the {k.analog_dims * k.analog_k} "
                    f"analog candidates that could carry a receipt -- a cap above its own population "
                    f"reads as a budget the board can never spend")
    if k.wave2 and not k.wave1:
        errs.append("board knobs: wave 2 is priced from the wave-1 rank, so a mode with no wave 1 "
                    "cannot have a wave 2")
    return errs


# ---------------------------------------------------------------------------------------------------
# THE CLOSED DECLINE VOCABULARY (sec 6.7, D10). ONE constant per leg, first-appearance order preserved,
# exactly as `XL_SUPPRESSED_REASONS` (orchestrator.py:1396) is declared and lint-pinned.
# ---------------------------------------------------------------------------------------------------
#: The three-state outcome every leg stamps. ``not_reached`` is stamped BY THE ORCHESTRATING WALK.
OUTCOMES: tuple[str, ...] = ("fired", "declined", "not_reached")

SERIES_REASONS: tuple[str, ...] = (
    "scope_unresolved", "unmapped_ref", "series_planned", "series_none", "thin_history",
    "zero_variance", "history_truncated", "read_empty", "read_error", "budget_cap", "outlook_lane",
    "pool_exhausted", "pg_timeout",
)
EDGE_REASONS: tuple[str, ...] = (
    "sign_undeclared",            # None / empty ONLY -- `0` is a DECLARED word (sec 1.5)
    "lag_unparsed", "far_series_other_table", "lag_undeclared_between_nodes",
)
FAN_REASONS: tuple[str, ...] = ("fan_cap", "board_unlabeled", "child_uncovered")
PATH_REASONS: tuple[str, ...] = ("render_cap", "edge_hop_cap")
CONV_REASONS: tuple[str, ...] = ("when_not_all_loud",)
TAPE_REASONS: tuple[str, ...] = (
    "no_tape_slug", "pre_coverage", "front_decline", "changes_thin", "percentile_thin",
)
ANALOG_REASONS: tuple[str, ...] = (
    "no_like_state", "horizon_open", "span_out_of_band", "pre_coverage", "no_tape_rows",
    "read_truncated", "budget_cap", "no_receipt", "no_numeric_event_history", "near_unreachable",
)
WATCH_REASONS: tuple[str, ...] = (
    "no_calendar_rule", "rule_unverified", "no_convention", "no_open_window", "no_policy_date",
)
RENDER_REASONS: tuple[str, ...] = ("template_register_trip",)
#: ``recency_facts_off`` IS THE S6-REVIEW ADDITION, and it names a COUPLING rather than an outage. The
#: board's SB-L rows and the mandate's closing sentence ("state each RECENCY row as a fact about the
#: layer it names; none of them dates the answer as a whole") contradict `_SYSTEM_RECENCY_EDGE`, the
#: shipped persona clause that dates the whole answer by one layer -- the literal whose own code note
#: records that it made the owner's 2026-09-07 soybean answer date itself by one layer. S5 shipped the
#: replacement behind `GRAPHRAG_RECENCY_FACTS`, dark. With the board on and that flag off the writer is
#: handed BOTH sentences AND three candidate edges to choose the older of, so the board makes the
#: defect worse rather than better. The seam therefore declines with this word rather than shipping the
#: pair, and the census can see exactly how often that state was reached.
#: ``subject_ambiguous`` IS THE SUBJECT RESOLVER'S ADDITION (D5), and it names a CARRY rather than an
#: outage. When the deterministic tiers propose two drivers a typed phrase could mean and the planner
#: declines to pick one, the alternative is to guess -- and a guessed subject anchors every board
#: carrying it, which is the widest wrong answer this board can give. So the board declines with this
#: word, the render names BOTH drivers in reader words and asks the reader to say which, and the
#: census can measure exactly how often a phrase this estate's own vocabulary could not disambiguate
#: reached a turn. It is the ONLY board reason that carries a detail, and the detail is two NAMES.
BOARD_REASONS: tuple[str, ...] = ("pg_not_live", "anchor_none", "turn_spend_unknown", "lane_off",
                                  "recency_facts_off", "subject_ambiguous")

#: leg name -> its own closed enum. THE LEG NAME IS PART OF THE VOCABULARY: sec 6.7's `conv:` line reads
#: "interaction: when_not_all_loud", i.e. the leg is `interaction` and the reason is the word after it.
LEG_REASONS: dict = {
    "series": SERIES_REASONS,
    "edge": EDGE_REASONS,
    "fan": FAN_REASONS,
    "path": PATH_REASONS,
    "interaction": CONV_REASONS,
    "tape": TAPE_REASONS,
    "analog": ANALOG_REASONS,
    "watch": WATCH_REASONS,
    "render": RENDER_REASONS,
    "board": BOARD_REASONS,
}

#: The reasons that carry a ``:detail`` tail. Declared so a consumer splits on the colon rather than
#: guessing, and so a word that grew a tail nobody declared fails the lint instead of the render.
#:
#: ``read_empty`` WAS IN THIS SET AT THE S2 LANDING AND IS STRUCK HERE. Sec 6.7 declares it BARE, and
#: widening a closed vocabulary by one entry is precisely the class this module exists to prevent: a
#: word admitted to the detail set is a word the S3 render owes a SECOND sentence (the detail's), and
#: nothing in this package ever stamped one. The six that remain each carry a detail some caller
#: actually writes -- ``thin_history:3``, ``changes_thin:<n>``, ``lane_off:<lane>``.
#: ``subject_ambiguous`` IS THE SEVENTH, AND IT IS THE FIRST WHOSE DETAIL IS NOT A COUNT OR A LANE
#: NAME. The note above is the reason the set is small: a word admitted here is a word the S3 render
#: OWES A SECOND SENTENCE. This one is admitted precisely because that second sentence is the point --
#: ``render.sb_subject_ambiguous`` renders the two driver DISPLAY names and asks the reader to name
#: one, which ``absence_why`` cannot do (it drops the detail on purpose: every other detail is a digit
#: in a letters-only class). The detail is carried as ``subject_ambiguous:<id>|<id>`` and the ids
#: NEVER reach the EMF dimension -- ``seam.reason_dimension`` cuts at the colon, and two driver ids
#: joined by a pipe is exactly the unbounded CloudWatch cardinality that function exists to refuse.
REASONS_WITH_DETAIL: frozenset = frozenset({
    "scope_unresolved", "thin_history", "history_truncated", "changes_thin", "percentile_thin",
    "lane_off", "subject_ambiguous",
})

#: The four lanes the board does NOT run on (sec 7), each stamped ``board: lane_off:<word>`` so
#: ``BoardFired`` is absent-when-inapplicable rather than silently zero.
OFF_LANES: tuple[str, ...] = ("numbers_only", "onehop", "trivial", "refused")


def reason_word(reason: str) -> str:
    """The bare closed word of a possibly-parametrised reason (``thin_history:3`` -> ``thin_history``)."""
    return (reason or "").split(":", 1)[0]


def check_reason(leg: str, reason: str) -> Optional[str]:
    """``None`` when ``reason`` is in ``leg``'s own closed enum, else the complaint. The lint the walk
    runs on every stamp, so an invented word fails at the stamp and never reaches a reader."""
    vocab = LEG_REASONS.get(leg)
    if vocab is None:
        return f"{leg!r} is not a declared board leg"
    head = reason_word(reason)
    if head not in vocab:
        return f"{leg}: {reason!r} is not a declared reason word"
    if head != reason and head not in REASONS_WITH_DETAIL:
        return f"{leg}: {head!r} carries a ':detail' but is not declared to"
    return None


# ---------------------------------------------------------------------------------------------------
# THE ANCHOR (sec 3.1, sec 16 AMENDMENTS 1 and 2)
# ---------------------------------------------------------------------------------------------------
#: WHERE AN ANCHOR CAME FROM, and it is a closed word because the render says it out loud and because
#: the two ceilings of Amendment 2 apply to exactly one of these. In PRECEDENCE order, strongest first.
ANCHOR_SOURCES: tuple[str, ...] = (
    "attached_event",     # `_resolve_attachments` -- an explicit gesture outranks the board (3.1)
    "focus_driver",       # DRIVER-AS-SUBJECT: the anchor set is every contract carrying the id
    # THE RESOLVED SUBJECT (SUBJECT RESOLVER D6), and its seat in this order is the whole decision:
    # BELOW `focus_driver`, because an FE `focus_driver` attachment is a CLICK and a subject is an
    # INFERENCE about a typed phrase, and this estate's doctrine is that an explicit gesture wins;
    # ABOVE `named`, because a market the question names is context for the cause it asks about, and
    # the subject IS the cause. When both a focus_driver and a differing subject are present BOTH
    # anchor and `Board.trace()` stamps `subject.vs_focus = differ` -- a silent override is the exact
    # class `Anchor.named` was added to close.
    "subject",
    "named",              # the user NAMED this market: never truncated by MAX_CONTRACTS (Amendment 2)
    "planner_inferred",   # the planner's own enumeration: MAX_CONTRACTS still bounds THESE
    "board_loudest",      # COLD START: no market named (V1.1 by D26; built here, default OFF)
)

#: THE ORDER THE ANCHORS SIT IN ON THE BOARD -- a SEPARATE RULE from the precedence above, and the
#: separation is the SUBJECT RESOLVER's D6 amendment stated as code ("the precedence word is a LABEL,
#: the anchor ORDER is a separate rule").
#:
#: :data:`ANCHOR_SOURCES` decides TWO things and neither of them is position: which word wins when one
#: board is reached by two routes (``anchor_source``, the trace and EMF word), and who survives a
#: ``max_anchors`` trim. Reading it as the render order as well collapses three decisions into one
#: tuple, and the collapse has a MEASURED cost: with ``subject`` seated above ``named``, the ask "what
#: does the pacific warming do to corn" opened on ``robusta_coffee`` and put ``corn_cbot`` -- the board
#: the question NAMED -- in the last surviving seat at every tier (quick 3/4, deep 5/6, max 7/8).
#:
#: SO THE ORDER IS: the GESTURES first (an attachment, then an FE ``focus_driver`` click), then the
#: NAMED markets, then the subject's OTHER boards, then the planner's own seeds, then cold start. "A
#: named market always leads its turn": the El Nino question opens on corn's board with the El Nino
#: row inside it, and the other thirty-four El Nino boards are the FAN-OUT, not the lead.
#:
#: IT IS A PERMUTATION OF :data:`ANCHOR_SOURCES` AND NOTHING ELSE -- same words, same length, one
#: transposition -- so a word added to one and forgotten in the other is a build failure
#: (``config_check.check_subject_resolver`` clause (4)) rather than a board that renders in an order
#: nobody declared. With no subject on the turn the two tuples agree on every pair that can co-occur,
#: which is why an unflagged board's anchor order is S6's own, seat for seat.
ANCHOR_ORDER: tuple[str, ...] = (
    "attached_event", "focus_driver", "named", "subject", "planner_inferred", "board_loudest",
)


def anchor_order_index(source: str) -> int:
    """Where ``source`` sits in the RENDER order (:data:`ANCHOR_ORDER`). An unknown word sorts last
    rather than raising: ``Anchor.__post_init__`` is the gate that refuses an undeclared source, and a
    sort is not a place to discover one."""
    try:
        return ANCHOR_ORDER.index(str(source))
    except ValueError:
        return len(ANCHOR_ORDER)


def anchor_order_key(a) -> tuple:
    """THE SORT KEY for an anchor set -- ``(order, rank, contract)`` -- and the ONE producer of it, so
    the anchor pass and the post-wave re-rank cannot order the same board two ways.

    IT READS ``named`` AND NOT ONLY ``source``, and that is the half a source-word-only order misses.
    The precedence COLLAPSES a board reached twice to the stronger word: a market the question named
    which also carries the resolved subject ends up ``source="subject"`` with ``named=True``, because
    ``subject`` outranks ``named`` in :data:`ANCHOR_SOURCES`. Ordering on the word alone therefore
    seated exactly the board D6's amendment says must LEAD -- "what does the pacific warming do to
    corn" opens on corn -- among the subject's thirty-four fan-out boards, alphabetically. ``named``
    is monotonic across that collapse for precisely this reason ("once named, always named"), and the
    ``max_anchors`` trim already reads it the same way.

    A GESTURE STILL OUTRANKS A NAMED MARKET: ``attached_event`` and ``focus_driver`` keep their own
    seats, so a click leads its turn whether or not the same board was typed."""
    src = str(getattr(a, "source", ""))
    named_seat = ANCHOR_ORDER.index("named")
    i = anchor_order_index(src)
    if getattr(a, "named", False) and i > named_seat:
        i = named_seat
    return (i, int(getattr(a, "rank", 0) or 0), str(getattr(a, "contract", "")))


#: The sources whose anchor set is a DRIVER's -- every contract carrying the id, read off the graph
#: rather than planned. Both are exempt from ``max_contracts`` and both are re-ranked by that driver's
#: own state after wave 1; the difference between them is provenance (a click versus an inference),
#: which is what :data:`ANCHOR_SOURCES` records.
DRIVER_ANCHOR_SOURCES: tuple[str, ...] = ("focus_driver", "subject")


@dataclass(frozen=True)
class Anchor:
    """ONE anchor board, with the provenance that decides whether a ceiling may drop it.

    ``rank`` orders the set -- for a ``focus_driver`` anchor set it is the DRIVER'S OWN STATE on that
    contract (Amendment 1: "the anchor set is EVERY contract carrying it, ranked by that driver's own
    state"), and for every other source it is arrival order, which is the planner's.

    ``subject`` is positioning's one exception (Amendment 1): ``context_only`` (2.4 / D18) yields when
    the query names the driver being explained. The R9 guard's MEASURED reason is positioning narrated
    as a CAUSE of the anchor's price; it does not apply when positioning IS the thing being explained,
    and the drivers of each contract's long are the ordinary walk from that contract."""

    contract: str
    source: str
    rank: int = 0
    driver_id: str = ""          # set on a focus_driver anchor: the id that anchored it
    subject: bool = False        # this anchor's driver is the SUBJECT, so context_only yields
    #: THE QUESTION NAMED THIS MARKET, kept BESIDE `source` rather than inside it (S6 review). The
    #: two are not the same fact: `ANCHOR_SOURCES` is a PRECEDENCE and it ranks `focus_driver` ABOVE
    #: `named` (Amendment 1's own order), so a contract that is both -- a market the user typed which
    #: also happens to carry the driver they attached -- collapses to the STRONGER word and loses
    #: every trace of having been typed. The anchor ceiling then cut it while keeping the driver's
    #: twenty-ninth board: Amendment 2 defeated by the fence that bounds Amendment 1. This flag is
    #: what an explicit-gesture reservation reads, and it is monotonic -- once named, always named.
    named: bool = False
    #: WHICH IDS OF THE SUBJECT'S GROUP THIS BOARD ACTUALLY CARRIES (SUBJECT RESOLVER D4). A subject
    #: expands to its GROUP -- the ids that share a curated ``driver_slices`` slice, or a ``silver_ref``
    #: set where no slice covers them -- because the estate carries four fertilizer ids, three crude
    #: ids, three EUDR ids and five positioning ids for four concepts, and the boards union is what the
    #: owner asked for. But the group is a property of the SUBJECT and the ids on this board are a
    #: property of THIS BOARD, and they are not the same tuple: `fertilizer_input_costs` sits on eight
    #: boards and `fertilizer_cost` on five. Recording the intersection here is what lets the render
    #: and the trace say which name this board answered under, instead of naming the group and hoping.
    group: tuple = ()
    note: str = ""

    def __post_init__(self):
        if self.source not in ANCHOR_SOURCES:
            raise ValueError(f"anchor source {self.source!r} is not one of {ANCHOR_SOURCES}")


# ---------------------------------------------------------------------------------------------------
# THE NODE ROW (sec 1.2) -- one per (contract, driver_id). EVERY node of every touched board.
# ---------------------------------------------------------------------------------------------------
@dataclass
class NodeRow:
    """The DAG's own fourteen ``Driver`` fields verbatim plus what the board learned about them.

    A NODE ROW NEVER CARRIES A MAGNITUDE (sec 1.1). It points at a :class:`StateRow` through
    ``series_key``; the state is UNSIGNED and this row's ``sign`` is the EDGE's, read at traversal
    (ruling 3). One ONI reading, 35 rows, two directions, never reconciled.

    ``coverage_tier`` says what KIND of thing the row is and ``state.status`` says what happened this
    turn; they are two fields because a budget cut does not change a row's kind (sec 1.3).

    AN UNMEASURED DRIVER IS A ROW THAT SAYS SO. There is no filter anywhere in this package that removes
    a node from ``Board.rows`` -- ``series_planned`` / ``series_none`` are RENDERED absences with dated
    receipts, and the walk traverses every tier."""

    contract: str
    driver_id: str
    # -- the fourteen Driver fields, verbatim (causal/schema.py:36-53) --------------------------------
    type: str = ""
    sign: str = ""
    mechanism: str = ""
    blurb: Optional[str] = None
    lag: str = ""
    region: Optional[str] = None
    edge_type: str = "causes"
    target_metric: Optional[str] = None
    silver_ref: Optional[str] = None
    silver_status: str = "none"
    parents: tuple = ()
    evidence_query: str = ""
    confidence: str = "medium"
    # -- the board's own ------------------------------------------------------------------------------
    lag_band: Optional[LagBand] = None
    children: tuple = ()
    boards_sharing: tuple = ()          # ((contract, sign, lag, confidence, ref), ...) -- LOAD-TIME, free
    live: bool = False                  # graph.silver_status()['live'] -- a DISPLAY fact only (1.3)
    series_key: str = ""                # the StateRow's label, or '' where the row has no series
    coverage_tier: str = "none_text_only"
    state: Optional[StateRow] = None
    receipts: dict = field(default_factory=dict)     # TextState.summary() -- {n, newest, oldest, top}
    rank: tuple = ()
    context_only: bool = False
    subject: bool = False               # positioning as SUBJECT (Amendment 1)
    event_date: Optional[str] = None    # sec 3.7: max(event_date <= asof), precision then EARLIER pub
    event_precision: str = ""
    event_receipt: Optional[dict] = None  # the receipt that WON that rule -- SB-D's published date and
    #                                       its [E] handle both bind to it, so the citation resolves to
    #                                       the document the row names rather than to whichever receipt
    #                                       the caller happened to list first (sec 3.7, B18)
    event_open: bool = False            # the band has not expired -> LOUD BY CONSTRUCTION (3.2)
    band_crossed: bool = False          # a declared desk band is met -> in the loud set by INCLUSION
    legs: dict = field(default_factory=dict)

    @property
    def key(self) -> tuple:
        return (self.contract, self.driver_id)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["state"] = self.state.to_dict() if self.state is not None else None
        d["lag_band"] = (None if self.lag_band is None else
                         {"raw": self.lag_band.raw, "kind": self.lag_band.kind,
                          "min_q": self.lag_band.min_q, "max_q": self.lag_band.max_q})
        return d


# ---------------------------------------------------------------------------------------------------
# THE BUDGET LEDGER (sec 1.2's `ledger` block, sec 3.8)
# ---------------------------------------------------------------------------------------------------
#: ONE monotonic counter for the whole process, so "the plan was written before the fetch" is an
#: ORDERING fact rather than a wall-clock comparison that a fast machine can make a tie.
_SEQ = itertools.count(1)


@dataclass
class WaveLedger:
    """ONE priced wave, with its own rectangle (sec 3.8, doctrine M-1).

    The wave is ATOMIC in the sense the design means: its plan is written whole, its cap is applied to
    that plan, the deferrals are NAMED, and only then does the first read happen. Nothing is truncated
    after the build by position -- that is `CASCADE_CAP`'s shape (cascade.py:1515) and the one this
    replaces."""

    wave: int
    reads_cap: int = 0
    series_declared: int = 0
    read: int = 0
    deferred: int = 0
    declined: int = 0
    reads_used: int = 0
    ms: float = 0.0
    plan: tuple = ()                    # the keys this wave WILL read, in rank order, post-cut
    deferred_keys: tuple = ()           # NAMED, every one of them (sec 3.8: "every dropped key is NAMED")
    declined_keys: tuple = ()           # priced, attempted, and refused BY NAME (pool / timeout / empty)
    free_keys: tuple = ()               # priced at ZERO because the memo already holds the series
    plan_seq: Optional[int] = None
    first_fetch_seq: Optional[int] = None

    def plan_written(self, plan, *, declared: int, deferred=(), free=()) -> None:
        """Stamp the plan. MUST be called before the first :meth:`note_fetch` of this wave."""
        self.plan = tuple(plan)
        self.series_declared = int(declared)
        self.deferred_keys = tuple(deferred)
        self.deferred = len(self.deferred_keys)
        self.free_keys = tuple(free)
        self.plan_seq = next(_SEQ)

    def note_fetch(self) -> None:
        if self.first_fetch_seq is None:
            self.first_fetch_seq = next(_SEQ)

    @property
    def priced_before_fetch(self) -> bool:
        """B3's own predicate. A wave that never fetched is vacuously priced-first; a wave that fetched
        without a plan is NOT (the ``plan_seq is None`` arm, which is the failure this catches)."""
        if self.first_fetch_seq is None:
            return True
        return self.plan_seq is not None and self.plan_seq < self.first_fetch_seq

    @property
    def closed(self) -> bool:
        """B1: ``series_declared == read + deferred + declined``. The free keys are READ rows served by
        the memo, so they count under ``read`` -- a key served without a fetch is still a key the board
        has, and calling it deferred would name a row the reader can see."""
        return self.series_declared == self.read + self.deferred + self.declined

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("plan_seq", None)
        d.pop("first_fetch_seq", None)
        d["closed"] = self.closed
        d["priced_before_fetch"] = self.priced_before_fetch
        return d


@dataclass
class Ledger:
    """Both waves plus the counters sec 3.8 and 10.5 name by hand."""

    waves: dict = field(default_factory=lambda: {1: WaveLedger(1), 2: WaveLedger(2)})
    #: `BoardEvidenceBorrows` -- the analog receipt reads THE BOARD ACTUALLY MADE, counted by the ONE
    #: producer that makes them (`analogs._receipts_for`, which returns [] at zero reads when no
    #: `receipt_fn` is wired). IT USED TO BE THE RESERVED SEAT COUNT and the S6 review measured the
    #: consequence: 3 on every fired Analysis board and 5 on every fired Cascade board while the
    #: evidence pool was never touched, so arm A's evidence-pool pressure would have been read off a
    #: number no read produced. THE SEATS ARE STILL RECORDED -- as `evidence_cap` below, which is what
    #: a reserved seat is -- because a cap that vanished would be a budget term nobody could audit.
    evidence_borrows: int = 0
    evidence_cap: int = 0               # the analog-receipt SEATS wave 2 reserved (never a read)
    #: The analog BENCHMARK reads. They are made by `analogs._outcomes_for` OUTSIDE both wave rectangles
    #: (it calls `benchmark_fn` after wave 2 has closed), so without a field of their own a real spend
    #: would be invisible to `_cw_turn_spent` -- the exact "a real spend read as zero" failure the
    #: enumeration exists to prevent and the one S5 had to repair for the composer sub-legs. Counted
    #: here, and `net_reads()` adds it, so the day the seam wires a `benchmark_fn` the walk sees it.
    benchmark_reads: int = 0
    benchmark_cap: int = 0              # the benchmark SEATS wave 2 reserved (never a read)
    replay_labelled: int = 0            # `BoardReplayLabelled` -- D17's label, never a decline
    pool_declined: int = 0              # `BoardPoolDeclined` -- arm A's bar is 0
    budget_capped: int = 0              # `BoardBudgetCapped` -- a live counter, never a silent bind
    tape_reads: int = 0                 # the anchor's SB-T mirror read (D19): one per anchor board
    #: THE TAPE'S OWN DECLARED SEAT, and it is a SEPARATE field from the two wave caps because the tape
    #: is not a wave: D19 declares one mirror read per ANCHOR BOARD, outside both rectangles. It is 0 at
    #: this sitting (S2 reads no tape) and the S3/S4 sitting that mints an SB-T read declares it here in
    #: the same edit. WITHOUT IT `reads_used` counted a tape read that `reads_cap` had no room for, so
    #: `net_reads() <= declared_cap()` -- the S6 ceiling of D12 -- would break by the anchor count the
    #: day the tape landed, silently and in the direction that UNDER-counts the ceiling.
    tape_cap: int = 0

    @property
    def reads_used(self) -> int:
        # `benchmark_reads` IS OUTSIDE BOTH RECTANGLES BY CONSTRUCTION (see its field note), so it is
        # summed here rather than inside a wave: a read the walk cannot see is a ceiling the walk
        # cannot honour. It is 0 on every path that wires no `benchmark_fn`, which is every path today.
        return (sum(w.reads_used for w in self.waves.values()) + self.tape_reads
                + self.benchmark_reads)

    @property
    def reads_cap(self) -> int:
        return sum(w.reads_cap for w in self.waves.values()) + self.tape_cap

    def closed(self) -> bool:
        return all(w.closed for w in self.waves.values())

    def to_dict(self) -> dict:
        return {"waves": {k: v.to_dict() for k, v in sorted(self.waves.items())},
                "evidence_borrows": self.evidence_borrows,
                "evidence_cap": self.evidence_cap,
                "benchmark_reads": self.benchmark_reads,
                "benchmark_cap": self.benchmark_cap,
                "replay_labelled": self.replay_labelled,
                "pool_declined": self.pool_declined,
                "budget_capped": self.budget_capped,
                "tape_reads": self.tape_reads, "tape_cap": self.tape_cap,
                "reads_used": self.reads_used, "reads_cap": self.reads_cap}


# ---------------------------------------------------------------------------------------------------
# THE BOARD (sec 1.2's `Board` block)
# ---------------------------------------------------------------------------------------------------
@dataclass
class Board:
    """The whole state of the world at ONE as-of, for ONE turn's anchors.

    ``rows`` is EVERY node of every touched board and is never filtered (sec 1.2). The loud set, the
    render caps and the budget decide what is SAID; nothing decides what EXISTS."""

    asof: str = ""
    mode: str = "standard"
    knobs: Optional[BoardKnobs] = None
    anchors: tuple = ()                 # (Anchor, ...) in precedence then rank order
    graph_version: Optional[str] = None
    turn_kind: str = ""
    horizon_months: Optional[int] = None   # sec 3.1: parsed by ONE closed regex; None = not asked
    #: WHICH RANK TUPLE RAN (sec 3.2, P1) -- ``"d2"`` (owner decision 6, shipped) or ``"alternative"``
    #: (the banked tuple with ``-convention_hit`` ahead of ``-abs_z``). It is a BOARD FIELD rather than
    #: a walk argument because every rank consultation reads it -- the stage-1 stamp, the loud cut, both
    #: ``board_order`` writes, Amendment 1's anchor ranking, the header sentence -- and the S2 landing's
    #: defect was exactly that one caller had the switch and the rest did not. It rides ``trace()`` so a
    #: census row can never be attributed to the tuple that did not produce it.
    rank_rule: str = "d2"

    series: dict = field(default_factory=dict)      # {series_key label: StateRow}
    rows: list = field(default_factory=list)        # [NodeRow]
    #: THE ORDERED NODE LIST (sec 3.9 item 1) -- ``((contract, driver_id), ...)`` in RANK order, written
    #: by the walk through :meth:`set_order` and by nothing else. It is a STORED field rather than a
    #: property over ``rows`` because ``rows`` is APPEND order (anchor, then the DAG's own declaration
    #: order) and this module ranks nothing -- ``walk.rank_rows`` is the one ranker, and a container
    #: that also ranked would be the second one this package exists to not have.
    #:
    #: MEASURED AT THE S2 REVIEW, and it is the defect this field closes: ``request()`` used to emit
    #: ``tuple(r.key for r in self.rows if r.rank)``, and because ``rank_key`` always returns a 7-tuple
    #: the ``if r.rank`` filter admitted every row -- so the ONE key S6 threads into ``_select_nodes``
    #: (cascade.py:306) was the DAG's insertion order, byte-for-byte, on 47 of 47 rows of a real
    #: soybeans board. The whole sitting's loudness would have reached ``quantify`` as alphabetical
    #: soup, and the deck did not catch it because it asserted only that the entries were 2-tuples.
    order: tuple = ()
    tape: dict = field(default_factory=dict)        # {anchor slug: TapeState}
    edges: list = field(default_factory=list)       # inter-commodity, BOTH ways (3.5)
    convergence: list = field(default_factory=list)  # proximity rows + amplifier sub-lines (3.5, D24)
    paths: list = field(default_factory=list)       # the FULL ancestor closure, path-ranked (3.4, D27)
    fan: list = field(default_factory=list)         # the free index: every shared id's far boards (3.6)
    analogs: list = field(default_factory=list)     # S3
    watch: list = field(default_factory=list)       # S3
    calls: list = field(default_factory=list)       # the `[N]` rows -- S3's render mints them
    windows: dict = field(default_factory=dict)     # {node key: the state-chosen anchor window}
    recency: dict = field(default_factory=dict)
    ledger: Ledger = field(default_factory=Ledger)
    legs: dict = field(default_factory=dict)        # {leg: {outcome, reason, reads}} -- sec 6.7
    stage_ms: dict = field(default_factory=lambda: {1: 0.0, 2: 0.0})
    stage_done: dict = field(default_factory=lambda: {1: False, 2: False})
    notes: list = field(default_factory=list)       # SB-X material the walk names (dropped keys, cuts)
    #: THE SUBJECT RESOLUTION (SUBJECT RESOLVER D8), and it rides HERE rather than on a new trace key
    #: for a measured reason: appending one key to `tracekeys.TRACE_RECORD_KEYS` reds SEVEN test files'
    #: negative-index tail pins (the S5 measurement, `tracekeys.py:449`). `Board.trace()` is the ONE
    #: producer of the already-registered `state_board` payload, so a sub-dict inside it costs zero
    #: registry churn and zero re-pins. EMPTY on every turn the resolver did not run, and `trace()`
    #: omits the key entirely then -- so a flag-off board's payload is byte-identical to S6's.
    subject: dict = field(default_factory=dict)
    #: THE COVERAGE MANIFEST (S7 item 1), written by ``render.render_board`` and by nothing else: one
    #: entry per RENDERED row carrying the role the render gave it, the ``[N]`` handles it minted and
    #: the token groups a letters-only row is graded on. It is on the BOARD rather than on the returned
    #: ``Block`` because the seam returns the block as TEXT -- the object is gone by the time there is a
    #: draft to read it against, and the seam is another lane's file this sitting.
    rendered_rows: tuple = ()
    #: WHAT THE WRITER DID WITH THOSE ROWS (``render.board_coverage``), filled at the answer seam AFTER
    #: the verifier returns and never before -- a coverage figure derived from the answer it shaped
    #: would be the circularity ``_composition_census`` is positioned to avoid, read from the other end.
    #:
    #: IT RIDES ``trace()`` FOR THE ``subject`` REASON, restated: appending a key to
    #: ``tracekeys.TRACE_RECORD_KEYS`` reds seven test files' negative-index tail pins, and
    #: :meth:`trace` is the ONE producer of the already-registered ``state_board`` payload -- so a
    #: sub-dict inside it costs zero registry churn and zero re-pins. EMPTY on every turn nothing
    #: measured, and :meth:`trace` omits the key entirely then.
    #:
    #: "NOTHING MEASURED" IS THE INSTRUMENT'S OWN ANSWER AND NOT A GUESS AT THIS END.
    #: ``render.board_coverage`` returns ``{}`` when the block rendered no row at all -- the live case
    #: is ``seam.fill_stage2``'s SUBJECT RESOLVER ambiguity branch, which ships a one-line block WITHOUT
    #: calling ``render_board`` -- and the answer seam stamps ``{"declined": <reason>}`` when the
    #: instrument itself raised. Both are honest absences; neither is a zero. The judge panel renders
    #: nothing on either, so ``state_use`` can never be scored against a board that put no row on the
    #: page.
    coverage: dict = field(default_factory=dict)

    # ── anchors ─────────────────────────────────────────────────────────────────────────────────────
    @property
    def anchor_source(self) -> str:
        """The STRONGEST source in the set -- what the header says the query decided. ``anchor_none``
        when the set is empty, which is V1's own seam word (D26)."""
        for s in ANCHOR_SOURCES:
            if any(a.source == s for a in self.anchors):
                return s
        return "anchor_none"

    @property
    def anchor_slugs(self) -> tuple:
        return tuple(a.contract for a in self.anchors)

    @property
    def subject_driver(self) -> str:
        """The driver being EXPLAINED, when the anchor is a driver (Amendment 1). '' otherwise.

        BOTH DRIVER SOURCES, IN PRECEDENCE ORDER (SUBJECT RESOLVER D6). This property filtered
        ``focus_driver`` alone, and it is one of the TWO readers of that predicate -- the other is
        ``walk._stage1``, which reads THIS -- so a RESOLVED subject reached neither: positioning's D18
        ``context_only`` exception was live on an FE click (measured 6 of 6 rows marked) and dead on
        the resolver's own path (0 of 6, with a row still ``context_only``). An FE click still wins,
        because it is first in :data:`ANCHOR_SOURCES` and this loop takes the sources in that order.

        A GROUP-CARRYING SUBJECT ANCHOR HAS NO SINGLE DRIVER, and this property is single-valued, so it
        answers only for an anchor that carries exactly one id (``Anchor.driver_id``). The plural case
        is :meth:`subject_ids_on`, which is what the row marker and the re-rank actually read."""
        for src in ANCHOR_SOURCES:
            if src not in DRIVER_ANCHOR_SOURCES:
                continue
            for a in self.anchors:
                if a.source == src and a.driver_id:
                    return a.driver_id
        return ""

    def subject_ids_on(self, contract: str) -> tuple:
        """Every driver id THIS BOARD is anchored on as a subject -- the anchor's own ``driver_id``
        plus the members of its :attr:`Anchor.group` that this board carries.

        THE GROUP IS A PROPERTY OF THE SUBJECT AND THE IDS ARE A PROPERTY OF THE BOARD (D4), and this
        is the one producer of the intersection. ``fertilizer_input_costs`` sits on eight boards and
        ``fertilizer_cost`` on five: naming the group and hoping would mark a row on a board that does
        not carry it, and reading ``driver_id`` alone would mark none of them, because a subject anchor
        reached by a group of two or more declares no single id."""
        out: set = set()
        for a in self.anchors:
            if a.contract != contract or a.source not in DRIVER_ANCHOR_SOURCES:
                continue
            if a.driver_id:
                out.add(str(a.driver_id))
            out |= {str(i) for i in (a.group or ()) if str(i or "").strip()}
        return tuple(sorted(out))

    # ── the ledger's laws ───────────────────────────────────────────────────────────────────────────
    def net_reads(self) -> int:
        """What the board actually SPENT -- both waves plus the anchor tape read.

        This is the number that enters ``_cw_turn_spent``'s ONE enumeration at S6 (sec 3.8, D12), and
        ABSENT IS NEVER ZERO: a board that ran without a counter makes the walk decline
        ``turn_spend_unknown`` rather than read a missing term as no spend."""
        return self.ledger.reads_used

    def declared_cap(self) -> int:
        """``STATE_BOARD_CAP[mode]`` -- what the walk's ceiling gains when the board payload is present
        (sec 3.8, D12). The CAP, not the spend: the ceiling must be derived before the reads happen."""
        return self.ledger.reads_cap

    def rectangle(self) -> list:
        """Every rectangle complaint, empty when B1 holds on both waves. Called at EVERY early return."""
        out = []
        for n, w in sorted(self.ledger.waves.items()):
            if not w.closed:
                out.append(f"wave {n}: declared {w.series_declared} != read {w.read} + deferred "
                           f"{w.deferred} + declined {w.declined}")
            if w.reads_used > w.reads_cap:
                out.append(f"wave {n}: reads_used {w.reads_used} exceeds reads_cap {w.reads_cap}")
            if not w.priced_before_fetch:
                out.append(f"wave {n}: a fetch happened before the plan was written")
        return out

    # ── the decline tags (sec 6.7) ──────────────────────────────────────────────────────────────────
    def stamp(self, leg: str, outcome: str, *, reason: str = "", reads: int = 0, **extra) -> dict:
        """Stamp ONE leg. Raises on an outcome or reason outside its closed enum -- an invented word
        fails HERE, at the stamp, and never reaches a reader as a sentence nobody wrote."""
        if outcome not in OUTCOMES:
            raise ValueError(f"outcome {outcome!r} is not one of {OUTCOMES}")
        if outcome == "declined":
            bad = check_reason(leg, reason)
            if bad:
                raise ValueError(bad)
        elif reason:
            raise ValueError(f"{leg}: a {outcome!r} leg must carry NO reason word, but got {reason!r} "
                             f"-- only a 'declined' leg names a reason (sec 6.7)")
        rec = {"outcome": outcome, "reason": reason or None, "reads": int(reads)}
        rec.update(extra)
        self.legs[leg] = rec
        return rec

    def stamp_not_reached(self, *legs) -> None:
        """``not_reached`` for every leg the ORCHESTRATING walk did not enter. A leg cannot stamp its
        own absence (sec 6.7), so this is the walk's job and it is done in one place."""
        for leg in legs:
            self.legs.setdefault(leg, {"outcome": "not_reached", "reason": None, "reads": 0})

    # ── the ordered node list (sec 3.9 item 1) ──────────────────────────────────────────────────────
    def set_order(self, rows) -> tuple:
        """Store the RANKED node list. The walk hands this the output of ``walk.rank_rows``; the board
        keeps it verbatim and never re-derives it.

        IT REFUSES A LIST THAT IS NOT THIS BOARD'S ROWS, because an order over a subset would hand
        ``_select_nodes`` a node list with holes and the hole would read as "the board did not rank
        it" -- which is exactly the absence-vs-silence confusion the rest of this module is built to
        prevent."""
        keys = tuple(r.key for r in rows)
        if len(keys) != len(self.rows) or set(keys) != {r.key for r in self.rows}:
            raise ValueError(f"board order covers {len(keys)} keys, the board has {len(self.rows)} rows")
        self.order = keys
        return self.order

    # ── row access ──────────────────────────────────────────────────────────────────────────────────
    def row(self, contract: str, driver_id: str) -> Optional[NodeRow]:
        for r in self.rows:
            if r.contract == contract and r.driver_id == driver_id:
                return r
        return None

    def rows_for(self, contract: str) -> list:
        return [r for r in self.rows if r.contract == contract]

    def state_of(self, r: NodeRow) -> Optional[StateRow]:
        return self.series.get(r.series_key) if r.series_key else None

    # ── what quantify is handed (sec 3.9, D8) ───────────────────────────────────────────────────────
    def request(self) -> dict:
        """THE ``board=`` PAYLOAD, built here so S6 threads a shape that already exists and is tested.

        FOUR KEYS, and each replaces a DECISION rather than a producer (sec 3.9):
          1. ``order``   -- ``_select_nodes`` (cascade.py:306) returns this filtered to ``sg.nodes``
             plus the board's admitted rows. S22 retires; one branch in one function. IT IS THE RANK
             ORDER (:attr:`order`, written by the walk), never ``rows``' append order -- if S6 threaded
             the append order the loudness this whole engine computes would reorder nothing.
          2. ``windows`` -- ``_derive_windows`` (:327) takes the loud state's date and the analog dates
             as its ``near`` and keeps the 90/90 geometry and the R3 clamp. S26 retires; one branch.
          3. ``calls``   -- the board's `[N]` rows, appended to ``extra_number_calls`` BEFORE the base
             wave so the cascade's own mints continue the count.
          4. ``budget``  -- the priced-and-spent counters ``_cw_turn_spent`` gains as ONE enumerated
             term, with the CAP beside the spend so the ceiling can be re-derived (D12).

        FEED, NEVER REPLACE: all 47 legs stay, each keeps its flag, and each becomes a producer whose
        windows and node order come from the board WHEN THE KWARG IS PRESENT. Flag off -> kwarg absent
        -> cascade.py byte-identical."""
        return {
            "asof": self.asof,
            "mode": self.mode,
            "anchors": self.anchor_slugs,
            "anchor_source": self.anchor_source,
            "order": self.order,
            "windows": dict(self.windows),
            "calls": tuple(self.calls),
            "budget": {"spent": self.net_reads(), "cap": self.declared_cap(),
                       "ledger": self.ledger.to_dict()},
            "horizon_months": self.horizon_months,
            "legs": dict(self.legs),
        }

    def trace(self) -> dict:
        """The ``state_board`` trace key's payload (sec 6.7, D10). ONE registered key, every leg on it.

        ``stage_ms`` rides here because arm A must identify the pole per turn (sec 3.9): the board's own
        two stages beside ``timing_ms.fill / rest / numbers``.

        ``subject`` (SUBJECT RESOLVER D8) is OMITTED when the resolver did not run, so a flag-off
        payload is byte-identical to S6's -- the omit-when-off idiom, applied to a trace as well as to
        a prompt. When present it carries ``{hints, picked, groups, source, vs_focus}``: the tiers'
        own output, what the PLANNER picked from it, what each pick expanded to, which anchor source
        the board ended on, and whether an FE ``focus_driver`` disagreed."""
        out = {"legs": dict(self.legs), "stage_ms": dict(self.stage_ms),
               "anchors": self.anchor_slugs, "anchor_source": self.anchor_source,
               "mode": self.mode, "asof": self.asof, "horizon_months": self.horizon_months,
               "rank_rule": self.rank_rule,
               "ledger": self.ledger.to_dict(), "net_reads": self.net_reads(),
               "cap": self.declared_cap(), "rectangle": self.rectangle(),
               "rows": len(self.rows), "series": len(self.series), "notes": list(self.notes)}
        if self.subject:
            out["subject"] = dict(self.subject)
        # ``coverage`` (S7 item 1) is OMITTED when nothing measured it -- the same omit-when-off idiom,
        # and the same reason: a flag-off (or pre-writer) payload stays byte-identical to S6's.
        if self.coverage:
            out["coverage"] = dict(self.coverage)
        return out


def board_knobs_of(mode: str) -> Optional[BoardKnobs]:
    """The mode's board knobs, or ``None`` where the tier declares none (``standard`` and every preset
    that has not been armed). ``None`` is the passthrough: no knobs, no board.

    The TABLE lives on ``reasoning_modes`` beside every other per-mode constant -- one producer for the
    tier arithmetic -- and this is the accessor that turns its tuple into the NamedTuple so no consumer
    indexes by position (sec 7)."""
    from leviathan.graphrag import reasoning_modes as rm
    t = rm.board_preset(mode)
    return None if t is None else BoardKnobs(*t)
