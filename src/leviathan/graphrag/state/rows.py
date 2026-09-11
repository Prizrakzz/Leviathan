"""The board's ROW SCHEMA -- STATE ENGINE DESIGN sec 1.1 (the unit of state), 1.2 (the row schema),
1.3 (coverage tiers) and 1.4 (point-in-time / the derived knowledge date). Sitting S1.

TWO KEYED LAYERS, ONE JOIN, and this module owns the first of them:

  * :class:`StateRow` -- ONE per ``series_key = (silver_ref, resolved scope)`` per as-of. UNSIGNED: it
    carries a level, its changes, its z, its percentile, its run and its receipts, and NEVER a sign, a
    direction or a verdict. The sign lives on the EDGE and is read at traversal (sec 1.5, ruling 3):
    one ONI state serves 35 node rows whose boards disagree about what it means, and reconciling them
    HERE would be the curation error the design refuses.
  * the NODE ROW, keyed by ``(contract, driver_id)``, which points AT a StateRow and carries the DAG's
    own fourteen fields -- it lands with the walk (S2), not here. The join is ``series_key``.

WHAT A StateRow IS NOT. It is not a citation, not a rendered line and not a decision. Every figure it
holds is a number computed by ``stats.py`` over rows fetched under ``query._guard``; the render (sec 6)
mints the ``[N]`` handles and the walk (sec 3) decides the ORDER. A row that could not be measured is
still a row -- ``status`` says which closed word applies and ``coverage_tier`` says what kind of thing
the reader is looking at. **Unmeasured is a row, never an absence** (sec 1.3, open question 5).

PURE: dataclasses, one closed enum per field that has one, and no I/O. The producer is
``state/feeders.py``.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional

# ---------------------------------------------------------------------------------------------------
# THE CLOSED WORD SETS (sec 1.3). Every one of these is rendered to a reader, so each is declared once
# here and lint-pinned rather than typed at a call site.
# ---------------------------------------------------------------------------------------------------

#: The five coverage tiers. A tier says WHAT KIND OF THING the row is, and it is stable across turns.
COVERAGE_TIERS: tuple[str, ...] = (
    "series",                        # a served series whose state clears the stats floors
    "series_thin",                   # a served series with too little history for a standing
    "declared_available_unserved",   # the DAG declares `available`; no served series carries the ref
    "planned_text_only",             # the DAG declares `planned` -- the series backlog
    "none_text_only",                # the DAG declares `none`
)

#: The per-turn status word. A status says WHAT HAPPENED THIS TURN, and it can differ turn to turn on
#: the same row (a budget cut, a pool wait, a scope that did not resolve at this anchor).
#: ``ok`` is the only word that means "the state below is measured"; every other word is an ABSENCE the
#: render states in plain language (sec 1.3's SB-X line), never a silence.
STATUS_WORDS: tuple[str, ...] = (
    "ok",
    "unmapped_ref",                  # + ':<why>' -- neither accessor knows the ref, or no registry card
    "scope_unresolved",              # + ':<skip_reason>' -- the RESOLVER's own seven reasons
    "read_empty",                    # + ':<reason>' -- the read returned no rows (citations.is_empty_read)
    "read_error",                    # the read RAISED; the exception rides `recency['read_error']`
    "thin_history",                  # + ':<n>' -- rows returned, floors refuse
    "zero_variance",                 # a std of zero: a z would be a division by nothing
    "history_truncated",             # + ':<limit>' -- len(rows) == limit, the truncation detector
    "budget_cap",                    # the wave's cap bit; the dropped keys are NAMED
    "pool_exhausted",                # the board's OWN pg decline, by name -- never an Athena fallback
    "pg_timeout",
    "outlook_lane",                  # positioning's series half on an OUTLOOK turn (R9's shipped drop)
)
"""THE CLOSED PER-TURN WORD SET, and it is the DESIGN's own (sec 1.3's roster plus ``read_error`` from
sec 6.7's `series:` line). It is closed for a consumer that does not live in this package: EVERY word
here is rendered to a reader as an SB-X absence line the S3 render must carry a sentence for, so a word
added here is work assigned to a later sitting, and adding one silently is the failure this docstring
exists to prevent.

TWO WORDS THE FIRST S1 CUT ADDED AND THIS ONE REMOVED, both folded onto a design word plus a detail:

  * ``undeclared_cross_section`` -> ``read_empty:undeclared_cross_section``. It is what the design
    actually says (sec 2.6 step 5: "returns ``([], None)`` -> ``status: read_empty`` with reason
    ``undeclared_cross_section``"): the word is ``read_empty`` and the cross-section is its REASON. The
    render needs one sentence for an empty read, not two.
  * ``no_card`` -> ``unmapped_ref:no_registry_card``. It occurs NOWHERE in the design. A map row naming
    a table ``load_registry`` does not serve is, to the board, a ref that resolves to nothing readable
    -- ``unmapped_ref``'s own sentence -- and the detail says which of the two ways it got there."""

#: The parametrised statuses: the word is followed by ``:<detail>``. Declared so a consumer can split on
#: the colon without guessing which words carry a tail.
STATUS_WITH_DETAIL: frozenset[str] = frozenset(
    {"scope_unresolved", "thin_history", "history_truncated", "budget_cap", "read_empty",
     "unmapped_ref"})

#: The board's TAPE row's own closed words (sec 6.7's `tape:` line, D19). A SEPARATE set from the series
#: words above because SB-T is a different row class with a different render sentence per word: a board
#: with no tape slug is not a series that came back empty.
TAPE_STATUS_WORDS: tuple[str, ...] = (
    "ok",
    "no_tape_slug",                  # the TEN boards absent from PRICE_COVERAGE_START (6.2)
    "pre_coverage",                  # the as-of precedes the slug's own coverage floor
    "front_decline",                 # select_front_expiry returned [] -- its own reasoned absence
    "changes_thin",                  # + ':<n>' -- the same-contract series is shorter than the window
    "percentile_thin",               # + ':<n>' -- fewer points than stats.percentile's own floor
    # the three below are NOT on sec 6.7's `tape:` line and are recorded as drift in the S1 report: they
    # are the SERIES set's own words for events a tape read has too (it borrows the same pool and the
    # same executor), and inventing new spellings for them would give the render two words per event.
    "pool_exhausted",
    "pg_timeout",
    "read_error",
)

#: Same rule as :data:`STATUS_WITH_DETAIL`, for the tape words.
TAPE_STATUS_WITH_DETAIL: frozenset[str] = frozenset({"changes_thin", "percentile_thin"})

#: The TEXT half's own three words (sec 2.2) -- a THIRD closed set, and a separate one for the same
#: reason the tape's is separate: "this node's receipts were never fetched" and "this node has no
#: receipts" are two different sentences the S3 render owes a reader, and neither is a series decline.
#: DECLARED AS A CONSTANT AT S2, and the trigger is measured rather than tidy: when ``series_key_for``
#: was lifted out of ``series_state``, the status fence in ``tests/unit/test_state_feeders.py`` was
#: widened to read ``status=`` KEYWORDS as well as ``.status =`` assignments -- and the first thing the
#: wider scanner found was that ``text_state`` writes a vocabulary closed only in a DOCSTRING, i.e. one
#: no test graded. A set that is closed in prose is not closed.
TEXT_STATUS_WORDS: tuple[str, ...] = (
    "ok",
    "no_receipt_fetched",            # the caller passed no receipts -- V1 phase 1b retrieves none itself
    "no_receipts",                   # receipts were passed and the node carries none: a ROW that says so
)

#: The cadences a card may declare (``TableSpec.cadence``), plus the board's own DESTINATION-GRAIN split
#: of ``weekly`` -- a per-destination weekly card (silver_esr, silver_fgis) is read over 52 weeks at the
#: destination grain and SUMMED per week, so its z is a 52-week z and prints as such (sec 2.1).
CADENCES: tuple[str, ...] = ("daily", "weekly", "weekly_destination", "biweekly", "monthly",
                             "annual", "release")

#: The three-entry SIGN map (sec 1.5). It lives here beside the row it never touches, so that the one
#: place a sign becomes a WORD is a table and not a glyph: ``Sign = Literal["+", "-", "0"]``
#: (causal/schema.py:26), ``0`` = ambiguous, and ``None``/``""`` is ``sign_undeclared`` -- a different
#: fact from an ambiguous declaration and never folded into it.
SIGN_WORDS: dict[str, str] = {
    "+": "in the same direction",
    "-": "in the opposite direction",
    "0": "with no committed direction",
}


def status_word(status: str) -> str:
    """The bare closed word of a possibly-parametrised status (``thin_history:3`` -> ``thin_history``)."""
    return (status or "").split(":", 1)[0]


def is_measured(status: str) -> bool:
    """True only for ``ok``. Every other word is an absence the render must NARRATE."""
    return status_word(status) == "ok"


def shown_value(value, scale) -> Optional[float]:
    """**THE ONE PLACE A CARD'S ``scale`` IS APPLIED IN THE STATE LANE** (S7 polish (b)) -- ``value *
    scale``, the magnitude that belongs under the card's ``narrate_unit`` word.

    THE DEFECT IT CLOSES, MEASURED on the banked S4 blocks: 13 of the 36 SB-1 rows on the four banked
    quick boards (36%) and 109 rows across all 16 banked blocks printed the NATIVE magnitude under the
    ANALYST unit word -- ``118000000 MMT`` where the card declares ``scale: 0.000001``, ``35852 M ha``
    on a ``scale: 0.001`` area card, ``87157400 million head``, and -- the sharpest -- a stocks-to-use
    ratio printed as ``0.13 %`` where the ``scale: 100`` card's own comment in ``cascade_map.yaml``
    (:188) reads "THE ratio trap; pre-scale is MANDATORY". That last is a 100x error on the most
    desk-legible number a grain board prints. 25 of the 49 declared cards carry ``scale != 1``.

    IT IS ONE FUNCTION BECAUSE A PAGE MUST NEVER CARRY ONE SERIES AT TWO SCALES. Two classes render a
    figure OF a card's series: the SB-1 state row (through :attr:`StateRow.level_shown`) and the SB-O
    analog outcome, whose change is read off the SAME array by ``analogs.outcome_over_band`` and printed
    under the SAME unit word (``render.sb_analog_outcome``). A change scales exactly as a level does --
    ``(a - b) * s == a*s - b*s`` -- so one multiplication serves both, and a second implementation would
    be a second chance for the two halves of one page to disagree.

    ``None`` in, ``None`` out, and an unparseable pair declines the same way: a row that read no level
    has no shown level either, and the render's own "no level was read" clause is the sentence for it.
    A missing or zero-ish ``scale`` is read as 1 -- an undeclared scale is not a scale of nothing."""
    if value is None:
        return None
    try:
        return float(value) * float(scale or 1.0)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------------------------------
# THE SERIES KEY (sec 1.1) -- silverleg's memo key generalised.
# ---------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class SeriesKey:
    """``(silver_ref, resolved scope)`` -- the unit of STATE, and the unit of the READ.

    The scope is the RESOLVED READ SCOPE the map row produces, NORMALISED BY THE CARD'S AXES and not by
    ``cascade._scope_ex``'s tuple: a card with neither a commodity column nor a country column is
    ``('_global', '')`` however the resolver labelled it. That normalisation is the whole reason one ONI
    read serves 35 rows in CODE as it does in prose -- ``_scope_ex`` hands back the contract slug and the
    primary title for ``oni_climate``, which has no country rule at all, so keying on its tuple would
    mint a separate ENSO state per board and pay 35 reads for one number.

    ``same_series_as`` collapses a declared ALIAS ref onto its base ref's key at ZERO extra reads
    (``oni_lag_climate`` -> ``oni_climate``, read at the six-month offset the served column carries).
    The OFFSET is not part of the key: it is applied to the shared array by the row that declares it.

    ``metric`` IS THE SCOPE ON A CARD THAT KEEPS ITS GEOGRAPHY IN THE METRIC NAME, and it is here
    because the collapse above would otherwise be WRONG on exactly one shipped card. MEASURED at this
    landing: ``silver_fred_fx`` is a WIDE card with ``commodity_col: null`` and ``country_col: null`` and
    FOURTEEN currency metrics (``brl_usd``, ``cny_usd``, ``ars_usd``, ``myr_usd``, ...); the map row
    declares ``brl_usd`` and ``cascade._region_row`` SWAPS the metric to the resolved region's currency.
    Normalising by the card's axes alone would key every board's FX read as ``('_global', '')`` and serve
    a Brazilian real z to a DCE board reading the yuan -- one shared entry, silently, and IMMORTALLY on a
    historical as-of. So the key carries the RESOLVED metric whenever it differs from the map row's
    declared one: the design's own sec 1.1 sentence for this ref is ``('fx', currency)``, and this is
    that sentence in code. It stays EMPTY on every other row (the 46 other refs each declare one metric),
    so no other key moves."""

    ref: str
    commodity: str = ""
    country: str = ""
    metric: str = ""

    @property
    def is_global(self) -> bool:
        return self.commodity == "_global"

    def label(self) -> str:
        """ASCII, stable, and the thing a memo key and a trace line both print."""
        base = f"{self.ref}|{self.commodity}|{self.country}"
        return f"{base}|{self.metric}" if self.metric else base


# ---------------------------------------------------------------------------------------------------
# THE ROW (sec 1.2)
# ---------------------------------------------------------------------------------------------------
@dataclass
class StateRow:
    """ONE series state at ONE as-of. See the module docstring for what it deliberately does not carry.

    THE FIELDS THAT ARE NOT MAGNITUDES, and why each one is on the row rather than derived downstream:

    * ``knowledge_date`` is DERIVED PER CARD CLASS and printed as such (sec 1.4, D21): a ``data_date``
      card's own date plus its ``publication_lag_days``; a ``vintage`` card's SERVED knowledge_date; a
      ``year_month`` card's month-end plus its ``ym_publication_lag_days`` ("data month YYYY-MM, knowable
      from {ISO}"). The store serves a ``knowledge_date`` alias only where the card declares
      ``knowledge_date_col``, so on the rest of the estate this field is the only honest answer to "when
      could anyone have known this".
    * ``vintage_note`` is the REPLAY LABEL (sec 1.4, D17), and it exists because the alternative --
      declining a latest-only revised-in-place card at a historical as-of -- is a fence that DELETES where
      a label already suffices, which this house grades FATAL. The row is SERVED with status ``ok`` and
      the note says: read from a table revised in place; the value as known at {asof} is not recoverable.
    * ``context_only`` is positioning's one rule (sec 2.4, D18): the row is READ and RENDERED, and is
      never a fan-out source, a convergence member, an analog dimension or a projection anchor. One flag,
      one rule -- revision 1 of the design said three incompatible things about positioning.
    * ``derivation`` is the V1 shape of the V2 DERIVATION RECORD: ``[{transform, params, n, inputs}]``,
      re-executable from the same fetched rows (``state/transforms.py``), which is what makes a rendered
      figure reproducible rather than merely cited.
    * ``reads`` is what this row actually SPENT. A budget rectangle that cannot be closed reads as a zero,
      and a zero is indistinguishable from a row nobody asked for."""

    key: SeriesKey
    status: str = "ok"
    coverage_tier: str = "series"

    # -- the card's own facts (pre-scaled at the producer: the K9-3 law) ------------------------------
    table: str = ""
    metric: str = ""
    cadence: str = ""
    unit: str = ""
    narrate_unit: str = ""
    scale: float = 1.0
    role: Optional[str] = None                 # the card's provenance_col value where declared (K9-4)

    # -- the observation ------------------------------------------------------------------------------
    level: Optional[float] = None
    level_date: Optional[str] = None
    knowledge_date: Optional[str] = None
    knowledge_basis: str = ""                  # WHICH derivation produced knowledge_date, in words
    vintage_note: Optional[str] = None
    context_only: bool = False
    offset_months: int = 0                     # a declared same-series offset; 0 = none
    alias_ref: str = ""                        # the ref ASKED FOR where `same_series_as` folded it onto
    #                                            `key.ref` -- 'oni_lag_climate' on a row keyed
    #                                            'oni_climate'. Without it the fold would erase the only
    #                                            fact the render needs to say WHOSE reading this is.
    offset_note: str = ""                      # the offset in WORDS, and it is on the row rather than
    #                                            derived at render because whether the shift was APPLIED
    #                                            depends on how the alias resolved (see feeders' fence):
    #                                            a render that assumed it always applies would print six
    #                                            months on a row that shifted nothing.

    # -- the measures. Each is a stats.py result dict or a decline dict; never a bare float ------------
    coverage: dict = field(default_factory=dict)     # {first_obs, n_obs, history_start, history_end,
    #                                                  truncated}. `first_obs` is the CARD's own declared
    #                                                  oldest observation and `history_start` is what THIS
    #                                                  read fetched -- two different facts, and the gap
    #                                                  between them is the window the row did not rank
    #                                                  against (silver_fred_fx: first_obs 2004-12-31, a
    #                                                  five-year fetched window).
    changes: list = field(default_factory=list)      # [{window, n_periods, from_date, to_date, delta, pct}]
    z: Optional[dict] = None
    percentile: Optional[dict] = None
    run: Optional[dict] = None
    flag_state: Optional[dict] = None                # *_flag refs only; z / percentile decline by name.
    #                                                  {last_event_date, events_in_window, periods_since,
    #                                                  window_periods}. The design's sec 1.2 sketch spells
    #                                                  the third field `months_since`; a *_flag ref is not
    #                                                  necessarily monthly (`frost_event_flag` rides a
    #                                                  weather card), so the row counts in the CADENCE's
    #                                                  own periods and says which. DECLARED drift, not a
    #                                                  silent rename.
    convention: Optional[dict] = None                # {label, band, source} -- ORDERING ONLY
    recency: dict = field(default_factory=dict)      # {age_days, age_periods, publication_lag_days,
    #                                                  ym_publication_lag_days, next_release}. `age_periods`
    #                                                  is age_days in the CADENCE's own periods -- "three
    #                                                  months stale" is the sentence a monthly card's
    #                                                  reader needs, and 92 days is not it.
    derivation: list = field(default_factory=list)
    inputs: dict = field(default_factory=dict)       # the derivation bundle: {key: {values, dates, unit}}
    #                                                  -- the arrays every record above re-executes
    #                                                  against. It is ON THE ROW because a derivation
    #                                                  record references its inputs BY KEY and a
    #                                                  re-execution that had to re-fetch them would be
    #                                                  verifying the store, not the arithmetic. The
    #                                                  design's sec 1.1 already states that the board's
    #                                                  cache holds whole ARRAYS rather than silverleg's
    #                                                  scalar verdicts, and that is why the memo is LRU-
    #                                                  BOUNDED at 512 entries rather than unbounded.

    # -- the ledger -----------------------------------------------------------------------------------
    reads: int = 0
    collapse: Optional[str] = None             # the cross-section collapse USED ('sum'|'mean'|'front_expiry')
    window_note: str = ""                      # the window each measure names, in the cadence's own noun
    asof: str = ""

    @property
    def level_shown(self) -> Optional[float]:
        """THE LEVEL IN ANALYST UNITS -- ``level * scale`` -- and it exists because until S7 the card's
        own ``scale`` had NO CONSUMER anywhere in this package (S7 polish (b)).

        THE DEFECT IT CLOSES, MEASURED on the banked S4 blocks: 13 of the 36 SB-1 rows on the four
        banked quick boards (36%), 109 rows across all 16 banked blocks, printed the NATIVE magnitude
        under the ANALYST unit word -- ``118000000 MMT`` where the card declares
        ``scale: 0.000001  # 2,462,000 MT -> 2.46 MMT``, ``35852 M ha`` on a ``scale: 0.001`` area card,
        ``87157400 million head``, and -- the sharpest -- ``ending stocks su ratio ... 0.13 %`` on the
        ``scale: 100`` card whose own comment in ``cascade_map.yaml`` (:188) reads "THE ratio trap;
        pre-scale is MANDATORY". That last one is a 100x error on the most desk-legible number a grain
        board prints. 25 of the 49 declared cards carry ``scale != 1``.

        IT IS A SECOND FIELD AND NOT A MUTATION OF ``level``, and that is the whole design. ``level``
        stays NATIVE because three other legs read it in native units and are correct there: the
        convention comparison (``feeders._convention_label`` -> ``watch.convention_distance``), the
        derivation bundle (``inputs``, which must stay re-executable against the fetched rows), and the
        change windows. ``z`` and ``percentile`` are dimensionless and are scale-invariant either way.
        The RENDER reads this one; nothing else changes.

        THE ONE PLACE THE TWO COULD DISAGREE IS THE KIND-2 WATCH ROW, and the estate is measured clean
        on it: ``watch.DISTANCE_UNITS`` falls back to ``narrate_unit`` for ``abs_bands`` conventions
        ONLY, and the intersection of "card with ``scale != 1``" and "declared convention" is exactly
        two refs -- ``mpob_ending_stocks`` and ``psd_ending_stock_su_ratio`` -- and BOTH are
        ``percentile_bands``, which measures its distance in percentile points. ``state/lint.py``'s
        clause 4 now asserts that intersection stays empty, so the day an ``abs_bands`` convention is
        declared on a scaled card the lint reds instead of a block printing one series in two units.

        ``None`` in, ``None`` out: a row that read no level has no shown level either, and the render's
        own "no level was read" clause is the sentence for it.

        THE ARITHMETIC ITSELF LIVES IN :func:`shown_value`, ONE FUNCTION, because the SB-1 row is not
        the only place a figure of this series reaches a page: the analog OUTCOME rows (SB-O) read the
        same card's array through ``analogs.outcome_over_band`` and print their change under the same
        analyst unit word. Two multiplications would be two chances to disagree, and a page carrying one
        series at two scales is the defect this whole item exists to close."""
        return shown_value(self.level, self.scale)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["key"] = self.key.label()
        # A PROPERTY IS NOT A FIELD, so ``asdict`` cannot see it -- and the trace is what a census, a
        # replay and an arm report read. The NATIVE value stays under its own name beside it.
        d["level_shown"] = self.level_shown
        return d

    def declined_windows(self) -> list:
        """The change windows the fetched history could not fill, by NAME. The row prints them as words:
        a window that could not be measured is stated, never dropped (sec 2.1)."""
        return [c["window"] for c in self.changes if c.get("declined")]


@dataclass
class TapeState:
    """THE ANCHOR'S OWN PRICE PATH -- one SB-T row per anchor board (sec 6.2, D19). ONE mirror read.

    IT IS NOT A StateRow, and the separation is the design's: a StateRow is keyed by
    ``(silver_ref, resolved scope)`` and every one of them is a DRIVER's state, while this row is the
    ANCHOR's own tape. ``cascade_map.yaml``'s self-reference refusal (:1760-1767) binds DRIVER refs
    precisely so a board never reads its own price as a driver of itself; SB-T is the anchor's tape and
    is never a driver row, a fan source, a convergence member or a ranked candidate (D25 admits the
    PERCENTILE below as an analog DIMENSION on Analysis / Cascade, which is a different thing).

    WHAT IT CARRIES, and each figure is one ``[N]`` handle in the SB-T line:
      * ``level`` / ``level_date`` / ``contract_month`` -- the front settle, named by
        ``query.select_front_expiry`` (``futures_roll.front_month``, ``ROLL_RULE_VERSION``), never by a
        nearest-expiry guess restated here;
      * ``changes`` -- the SAME-CONTRACT change over 1 / 5 / 21 / 63 sessions. Same-contract is the whole
        point: a delta spanning a roll is a SPLICE, which is what ``levels_only`` fences on the
        continuous sibling table;
      * ``percentile`` -- the level's rank inside its FETCHED window, and ``window_note`` prints that
        window in sessions and dates so the rank can never claim a span it did not measure.

    The standings that NAME THEIR POPULATIONS and realised vol are reserved for
    ``numbers/price_standing.py`` (D19 / C-F7) and the answer says so in words."""

    slug: str = ""
    status: str = "ok"                         # TAPE_STATUS_WORDS
    asof: str = ""
    level: Optional[float] = None
    level_date: Optional[str] = None
    contract_month: str = ""
    unit: str = ""
    currency: str = ""
    settle_kind: str = ""
    roll_method: str = ""
    roll_rule_version: str = ""
    changes: list = field(default_factory=list)      # [{window, n_periods, from_date, to_date, delta, pct}]
    percentile: Optional[dict] = None
    coverage: dict = field(default_factory=dict)     # {n_obs, history_start, history_end, truncated}
    window_note: str = ""
    coverage_start: Optional[str] = None       # the slug's PRICE_COVERAGE_START floor, printed on a decline
    derivation: list = field(default_factory=list)
    inputs: dict = field(default_factory=dict)
    reads: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    def declined_windows(self) -> list:
        return [c["window"] for c in self.changes if c.get("declined")]


@dataclass
class Receipt:
    """One dated text receipt on a node, with the rank that ordered it (sec 2.2)."""
    date: str
    source: str = ""
    text: str = ""
    specificity: float = 0.0
    recency: float = 0.0
    rank: float = 0.0
    named: bool = False                        # the node's id (or a slice term) appears in the receipt


@dataclass
class TextState:
    """The TEXT half of a node's state: dated receipts ranked by recency and specificity, plus the
    summary a row carries when the receipts themselves do not ride (sec 2.2).

    WHAT THE RANK NEVER DOES: decide whether a node is on the board (every node is), or gate a mechanism
    on a receipt COUNT. One mechanism-narrating receipt is enough -- frequency floors deny the tail. A
    node with zero receipts is a row that SAYS SO, which is why ``n == 0`` is a valid, rendered state and
    not a decline."""
    node_id: str = ""
    n: int = 0
    newest_date: Optional[str] = None
    oldest_date: Optional[str] = None
    top: list = field(default_factory=list)    # [Receipt] -- at most three
    status: str = "ok"                         # 'ok' | 'no_receipt_fetched' | 'no_receipts'

    def summary(self) -> dict:
        """The ``receipts`` field of a NodeRow: ``{n, newest_date, oldest_date, top[3]}`` (sec 1.2)."""
        return {"n": self.n, "newest_date": self.newest_date, "oldest_date": self.oldest_date,
                "top": [asdict(r) for r in self.top], "status": self.status}


# ---------------------------------------------------------------------------------------------------
# THE COVERAGE TIER (sec 1.3) -- derived, never declared.
# ---------------------------------------------------------------------------------------------------
def coverage_tier(*, map_row: Optional[dict], silver_status: str, status: str,
                  n_obs: int = 0, min_n: int = 8) -> str:
    """The five-way tier, from ``cascade.map_row``/the board's accessor PLUS the read's outcome PLUS the
    DAG's own declared ``silver_status`` word -- and NEVER from ``graph.silver_status()['live']``.

    THAT EXCLUSION IS THE WHOLE POINT, and it is measured: the predicate is ``silver_ref in self._silver``
    with ``_silver = validate.available_silver()`` = features.yaml FAMILIES + node_silver_map metrics +
    live map refs, so it returns True for the 125 available-but-UNMAPPED instances (``stage_precip_z``,
    ``crush_margin_z``, ``nass_crop_progress_ge_z`` are features.yaml families). It is a DISPLAY fact
    about what the feature layer knows about, not a claim that a served series carries the ref. Reading
    a tier off it would put "measured" on 125 rows nothing measures.

    THE SPLIT, in order:
      * NO map row at all -> the row is TEXT-ONLY, and WHICH text-only tier is the DAG's own declaration:
        ``available`` -> ``declared_available_unserved`` (the honest sentence is "declared available; no
        served series carries it"), ``planned`` -> ``planned_text_only`` (a backlog item), ``none`` ->
        ``none_text_only``. The DAG's word is a curator's DECLARATION about the world, which is a
        different kind of thing from the live predicate above, and it is the only thing that can tell
        those three apart.
      * a map row and a measured read -> ``series``, unless the history is too thin for a standing, which
        is ``series_thin``: level + recency, and "eight points are needed for a standing; the series
        holds N" in words.
      * a map row and a read that did not produce a series -> ``series_thin`` as well when rows came back
        but the floors refused; otherwise the row keeps a SERIES tier and its ``status`` carries the
        reason. A per-turn decline (a budget cut, a pool wait, a scope that did not resolve) does NOT
        change what KIND of thing the row is -- that is why status and tier are two fields."""
    if map_row is None:
        return {"available": "declared_available_unserved",
                "planned": "planned_text_only"}.get((silver_status or "none").strip(), "none_text_only")
    w = status_word(status)
    if w == "ok":
        return "series" if n_obs >= min_n else "series_thin"
    if w in ("thin_history", "zero_variance", "read_empty", "read_error"):
        return "series_thin" if n_obs else "series"
    return "series"
