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
    """The nine per-mode board constants of sec 7, in the design's OWN declared order.

    ``(loud_k, fan_k, analog_k, analog_dims, board_admit_k, wave1, wave2, receipt_cap, path_render_k)``
    -- the order is the design's and is not re-sorted here, because the same nine ride the ``Mode``
    table as ONE appended tuple field when S6 lands it (`k_by_depth`'s precedent, reasoning_modes.py:145
    "a TUPLE so the dataclass stays hashable and the table stays immutable").

    WHY A NamedTuple AND NOT A DICT: a dict of nine keys is nine chances to typo a knob name at a call
    site and get ``None`` back silently; an attribute access on a wrong name raises. The board's caps
    are the one thing in this design that must never fail open.
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


def wave2_shape(k: BoardKnobs, *, legb_cells: int = 0, legb_on: bool = False) -> dict:
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
    (58 -> 31 on Cascade) and moves no other column, which is what "with leg B dark" means."""
    bench = max(0, int(k.analog_dims) * int(k.analog_k))
    receipts = min(bench, max(0, int(k.receipt_cap)))
    declared_legb = max(0, int(legb_cells)) * READS_PER_CELL
    # FLOORED AT ZERO so an over-committed knob table cannot mint a NEGATIVE slice at the pricer (which
    # Python would read as "all but the last thirty", i.e. a cap that silently becomes a different cap).
    # An over-commitment is a LINT ERROR (`check_knobs`), and the pricer's own trim order of sec 3.8 is
    # what handles it at runtime -- floored here, trimmed there, flagged in both places.
    far = max(0, int(k.wave2) - bench - receipts - declared_legb)
    legb = declared_legb if legb_on else 0
    return {"far": far, "analog_benchmark": bench, "analog_receipts": receipts, "legb": legb,
            "legb_declared": declared_legb,
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
BOARD_REASONS: tuple[str, ...] = ("pg_not_live", "anchor_none", "turn_spend_unknown", "lane_off")

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
REASONS_WITH_DETAIL: frozenset = frozenset({
    "scope_unresolved", "thin_history", "history_truncated", "changes_thin", "percentile_thin",
    "lane_off",
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
    "named",              # the user NAMED this market: never truncated by MAX_CONTRACTS (Amendment 2)
    "planner_inferred",   # the planner's own enumeration: MAX_CONTRACTS still bounds THESE
    "board_loudest",      # COLD START: no market named (V1.1 by D26; built here, default OFF)
)


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
    evidence_borrows: int = 0           # `BoardEvidenceBorrows` -- the counted analog receipt reads
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
        return sum(w.reads_used for w in self.waves.values()) + self.tape_reads

    @property
    def reads_cap(self) -> int:
        return sum(w.reads_cap for w in self.waves.values()) + self.tape_cap

    def closed(self) -> bool:
        return all(w.closed for w in self.waves.values())

    def to_dict(self) -> dict:
        return {"waves": {k: v.to_dict() for k, v in sorted(self.waves.items())},
                "evidence_borrows": self.evidence_borrows,
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
        """The driver being EXPLAINED, when the anchor is a driver (Amendment 1). '' otherwise."""
        for a in self.anchors:
            if a.source == "focus_driver" and a.driver_id:
                return a.driver_id
        return ""

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
        two stages beside ``timing_ms.fill / rest / numbers``."""
        return {"legs": dict(self.legs), "stage_ms": dict(self.stage_ms),
                "anchors": self.anchor_slugs, "anchor_source": self.anchor_source,
                "mode": self.mode, "asof": self.asof, "horizon_months": self.horizon_months,
                "rank_rule": self.rank_rule,
                "ledger": self.ledger.to_dict(), "net_reads": self.net_reads(),
                "cap": self.declared_cap(), "rectangle": self.rectangle(),
                "rows": len(self.rows), "series": len(self.series), "notes": list(self.notes)}


def board_knobs_of(mode: str) -> Optional[BoardKnobs]:
    """The mode's board knobs, or ``None`` where the tier declares none (``standard`` and every preset
    that has not been armed). ``None`` is the passthrough: no knobs, no board.

    The TABLE lives on ``reasoning_modes`` beside every other per-mode constant -- one producer for the
    tier arithmetic -- and this is the accessor that turns its tuple into the NamedTuple so no consumer
    indexes by position (sec 7)."""
    from leviathan.graphrag import reasoning_modes as rm
    t = rm.board_preset(mode)
    return None if t is None else BoardKnobs(*t)
