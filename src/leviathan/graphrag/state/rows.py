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

from collections.abc import Mapping
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
# NUMERALS AND MONTHS AS WORDS -- the ONE producer of each, LIVING IN THE LEAF (09-23 fix round, lane R).
#
# THEY MOVED HERE FROM ``render.py`` UNCHANGED, and ``render`` re-exports both names, so every caller
# (``walk.chain_history_words``, the decks, the render itself) reads the same function object it read
# before. They moved because :meth:`RowIdentity.words` -- a method of a LEAF dataclass -- has to spell a
# period ("July 2026") and an offset ("six months back") and this module imports nothing from the
# estate: a second cardinal table here would be the second producer the estate's own law forbids.
# ---------------------------------------------------------------------------------------------------
_ONES = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
         "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen",
         "nineteen")
_TENS = ("", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety")

#: A count the board would never write as a word. Above it the phrase says so rather than printing a
#: numeral into a letters-only class -- a digit there is the one thing the class exists to exclude.
_WORDS_CEILING = 999999


def words_for_int(n) -> str:
    """A non-negative count as ENGLISH WORDS. The board's counts (runs, crossings, drivers, boards,
    window lengths) are POSITION and POPULATION facts, never magnitudes, and a digit outside a
    figure-bearing class trips the fence (sec 6.2). So they render here.

    IT COVERS THE WINDOW LENGTHS TOO, and that is a MEASURED correction to sec 6.2's literal. The design
    writes the trailing window as the hyphen compound ``250-session window`` on the strength of
    ``verify._claim_number_spans`` rule (f) -- but rule (f)'s duration nouns are
    ``year|yr|month|week|wk|day|quarter|qtr|season`` (verify.py:389) and the board's own cadence nouns
    include ``session``, ``fortnight`` and ``marketing year`` (feeders.py:1178). On a DAILY row the
    compound therefore earns no exemption: a writer copying ``2.4 sigma on its trailing 250-session
    window`` would have the 250 charged as ``number_unbacked`` and lose the whole sentence. The window
    length is a WINDOW SLOT, which is exactly the thing this function renders, so it renders here too
    and the compound never appears."""
    try:
        n = int(n)
    except (TypeError, ValueError):
        return "an undeclared number of"
    if n < 0:
        return "minus " + words_for_int(-n)
    if n < 20:
        return _ONES[n]
    if n < 100:
        t, r = divmod(n, 10)
        return _TENS[t] + ("-" + _ONES[r] if r else "")
    if n < 1000:
        h, r = divmod(n, 100)
        return _ONES[h] + " hundred" + (" " + words_for_int(r) if r else "")
    if n <= _WORDS_CEILING:
        th, r = divmod(n, 1000)
        return words_for_int(th) + " thousand" + (" " + words_for_int(r) if r else "")
    return "more than nine hundred ninety-nine thousand"


MONTH_NAMES = ("January", "February", "March", "April", "May", "June", "July", "August", "September",
               "October", "November", "December")


def month_words(iso: Optional[str]) -> str:
    """``2026-08-31`` -> ``August 2026``; ``2026-08`` -> ``August 2026``; ``2026`` -> ``2026``. The
    4-digit year rides as a numeral because ``_claim_number_spans`` rule (a) exempts a bare calendar
    year 1900-2099 (verify.py:606-609), which is what lets a PROJECTION line name two calendar months
    without carrying a charged digit.

    **THE BARE YEAR IS A REAL FORM AND THIS FUNCTION USED TO DROP IT** (S7 polish (a)). A marketing-year
    card writes its period as a bare ``YYYY`` (``feeders._period_dates``; ten annual tables on the
    mirror), and the first cut's ``len(s) < 7`` guard returned ``""`` for it -- so ``_anchor_words``
    interpolated an empty string and the board printed ``counted from the run's start in , the effect
    window ... opens around December 2024``. MEASURED: 13 of the 33 SB-J lines on the four banked quick
    boards, 95 lines across all 16 banked census blocks (quick 13, deep 26, max 56). The WINDOW was
    placed correctly the whole time, because ``walk._add_months`` had ALREADY been taught the bare-year
    form through ``analogs.axis_date`` at the 09-10 mirror run: one function in the tree knew the form
    and the other did not, which is the same-producer law's own failure mode.

    A bare year renders AS ITS YEAR rather than as a month it does not have -- the card dates the
    reading to a marketing year and inventing January would be a figure the source never carried."""
    s = str(iso or "").strip()
    if len(s) == 4 and s.isdigit() and 1900 <= int(s) <= 2099:
        return s
    if len(s) < 7:
        return ""
    try:
        m = int(s[5:7])
    except ValueError:
        return ""
    if not 1 <= m <= 12:
        return ""
    return f"{MONTH_NAMES[m - 1]} {s[0:4]}"


def day_words(iso: Optional[str]) -> str:
    """``2026-09-10`` -> ``10 September 2026`` -- a DAY at its own precision, ``""`` for anything that is
    not a full ISO date. The ordinary-language day form :func:`render._date_forms` already accepts as
    one spelling of that date, so a writer copying it is copying a form the estate reads."""
    s = str(iso or "").strip()[:10]
    mw = month_words(s)
    if len(s) != 10 or not mw or " " not in mw:
        return ""
    try:
        d = int(s[8:10])
    except ValueError:
        return ""
    return f"{d} {mw}" if 1 <= d <= 31 else ""


# ---------------------------------------------------------------------------------------------------
# THE 09-23 CONTRACT'S CLOSED VOCABULARIES (CONTRACT.md C1, C3, C4) -- one spelling each, read by
# render (lane R), citations (lane C), the verifier (lane V) and assembly (lane A).
# ---------------------------------------------------------------------------------------------------
#: THE ONE CLOSED VINTAGE-ROLE ROSTER (K9-4). A card's provenance column carries release stamps
#: (``2026M09``) and rule versions as well as roles; ONLY these three words are a role, and a token
#: outside them is never spliced into a period or written as a call's ``provenance``.
VINTAGE_ROLES: tuple = ("actual", "estimate", "projection")

#: WHAT A CARD'S COUNTRY AXIS IS (``TableSpec.country_axis``, lane T). The identity's scope words are
#: derived from it, never typed per driver.
AXIS_KINDS: tuple = ("national", "reporter", "destination", "region_cell", "global")

#: WHAT A ROW'S PERIOD IS (``TableSpec.period_words``, lane T) -- the label a reader is shown.
PERIOD_KINDS: tuple = ("marketing_year", "crop_season", "month", "week", "day", "delivery_month",
                       "window")

#: THE KINDS ONE OBSERVATION'S PERIOD CAN BE, LONGEST GRAIN FIRST (fixer pass, REVIEW_RA lexical 1-2): the
#: order IS the calendar's (a marketing year and a season are annual, then a month, a week, a day), so a
#: reader asking "is the written period longer than the row's?" compares two positions here -- never a
#: typed day count. A delivery month and a window are SCOPES of a row, never its period, and are absent.
OBSERVATION_PERIOD_KINDS: tuple = ("marketing_year", "crop_season", "month", "week", "day")

#: WHICH MAGNITUDE OF A ROW ONE BOARD CALL IS (C3 ``row["stat"]``). ``window_change`` (09-24 fix round,
#: CONTRACT K5) is a CHANGE of the series between two of its own observations -- the analog outcome's two
#: ends -- and it is never the level's name; ``pair_level_spread`` (K8) is the ONE tape spread the board
#: mints, whose identity carries both legs and their order. Appended at the TAIL: every reader of the
#: first five keeps its index.
STAT_KINDS: tuple = ("level", "sigma", "percentile", "window_peak_percentile", "current_level",
                     "window_change", "pair_level_spread")

#: THE STAT KINDS WHOSE MAGNITUDE IS THE SERIES' OWN LEVEL (fixer pass, REVIEW_VC F2 / lexical 2478): a row
#: with one of these (or no ``stat`` at all) is a reading of the series in the card's quantity; every other
#: kind is ANOTHER quantity of the same row (a sigma, a percentile, a change, a spread), which never takes
#: the card's level words (its ``figure_basis``). Read by lane C's label; one vocabulary, never re-typed.
LEVEL_STAT_KINDS: tuple = ("level", "current_level")

#: THE STAT KINDS WHOSE MAGNITUDE IS A DIFFERENCE and therefore prints its sign (fixer pass, REVIEW_RA lexical
#: 8): a change of the series between two of its observations and the one tape spread. One vocabulary, read by
#: the ask head, never a word searched for in a display string.
CHANGE_STAT_KINDS: tuple = ("window_change", "pair_level_spread")

#: THE SERVED-SCALARS POOL'S KINDS (C4). A scalar carrying a ``row_id`` is ROW-BEARING (it backs a numeral
#: only in a clause bound to a handle of the same row); a handled scalar with no row backs only through its
#: own handle; a scalar with neither backs a numeral only under its own derived unit. THE 09-24 TAIL (K8,
#: item 30): ``window_change`` -- a tape's same-contract change, row-bearing through the tape's own row;
#: ``pair_level_spread`` -- the tape spread's figure, backed through its own handle; ``ask_row`` -- a
#: numbers-seat calculator row the ask head printed, backed only through the seat call's own handle.
SCALAR_KINDS: tuple = ("level", "sigma", "percentile", "window_peak_percentile", "current_level",
                       "window_length", "run_length", "lag_band_quarters", "firings_count",
                       "firings_aligned", "card_threshold", "outcome_move", "window_change",
                       "pair_level_spread", "ask_row",
                       # 09-26 (CONTRACT P5, S-4): one SB-F fan's counts -- the total and each signed arm, each
                       # with the sign words the line printed beside it and the fan's identity; no row, no handle.
                       "fan_count")

#: WHAT ONE SERVED ROW'S LEVEL IS OVER A CELL AXIS (CONTRACT K3), in derivation order -- and the empty word
#: is a real answer: a read whose grain the served rows do not prove prints its scope alone, never a
#: guessed cell. ``single_cell`` stays in the vocabulary for a caller that KNOWS it holds one cell's row;
#: no derivation here mints it from the axis enum (the round-1 inversion that labelled cocoa's West Africa
#: BASIN MEAN "one West Africa growing cell").
CELL_RULES: tuple = ("single_cell", "mean_of_cells", "one_of_cells", "sum", "")

#: The reader noun of each PERIOD kind, for the one sentence that must name a kind of period rather
#: than a period (the period-gap clause, C11).
PERIOD_KIND_NOUNS: dict = {"marketing_year": "marketing year", "crop_season": "season",
                           "month": "month", "week": "week", "day": "day",
                           "delivery_month": "delivery month", "window": "window"}


# ---------------------------------------------------------------------------------------------------
# THE PRECISION PRODUCER (CONTRACT.md C5) -- ONE rule for every figure the board prints in digits
# ---------------------------------------------------------------------------------------------------
#: The most decimals any rule here will print. A figure that needs more to be honest about its side of a
#: line is printed at this many and no more.
FIGURE_MAX_DECIMALS: int = 6

#: The decile lines a PERCENTILE is never rounded onto or across (``percentile_int``). They are the
#: tail cuts the board's own record-tail rule reads (``watch.TAIL_DECILE`` = 10, its mirror 90).
PERCENTILE_DECILE_LINES: tuple = (10.0, 90.0)


def _default_decimals(v: float) -> int:
    """SB-1's own rule, extended (C5): two decimals between 0.1 and 1000, none at 1000 and over, and
    below 0.1 the FEWEST decimals that still show TWO significant figures -- so a small magnitude is
    never printed as ``0`` and backs a false zero (R-7)."""
    a = abs(float(v))
    if a == 0.0:
        return 0
    if a >= 1000.0:
        return 0
    if a >= 0.1:
        return 2
    import math
    return max(0, min(FIGURE_MAX_DECIMALS, -int(math.floor(math.log10(a))) + 1))


def _side(x: float, line: float) -> int:
    """-1 below the line, 0 on it, +1 above it -- compared at a precision finer than any figure prints."""
    d = round(float(x) - float(line), 9)
    return 0 if d == 0 else (1 if d > 0 else -1)


def _guarded_decimals(v: float, d: int, lines, two_sided: bool) -> int:
    """THE LINE GUARD (C5): add one decimal at a time until the SHOWN value sits on the same side of
    every declared line the RAW value sits on. A two-sided series' lines are magnitudes, so both are
    compared by their absolute value."""
    raw = abs(v) if two_sided else v
    for _ in range(FIGURE_MAX_DECIMALS + 1):
        shown = round(v, d)
        cmp = abs(shown) if two_sided else shown
        if all(_side(cmp, ln) == _side(raw, ln) for ln in (lines or ())):
            return d
        if d >= FIGURE_MAX_DECIMALS:
            return d
        d += 1
    return d


def figure_text(value, *, unit: str = "", decimals: Optional[int] = None, lines: tuple = (),
                two_sided: bool = False, grouping: bool = False) -> str:
    """ONE magnitude as a reader sees it -- THE precision producer every board figure prints through.

    The rule (CONTRACT.md C5): ``decimals`` when the card declares them, else :func:`_default_decimals`;
    trailing zeros stripped; the LINE GUARD (:func:`_guarded_decimals`) so rounding never puts a figure
    on or across a declared line the raw value is not on (ONI 0.46 is never printed "0.5", the El Nino
    line); a sign only on a two-sided series or a negative value; never ``-0``. ``grouping`` keeps the
    citation label's ``,.0f`` shape for a caller that prints one; the board's own rows pass False (a
    comma would make ``_claim_number_spans`` read ``2,021`` as punctuation). ``""`` for a value that is
    not a number, so a caller's "no level was read" clause is the sentence for it."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return ""
    if v != v:                                      # NaN is not a figure
        return ""
    d = _default_decimals(v) if decimals is None else max(0, min(FIGURE_MAX_DECIMALS, int(decimals)))
    d = _guarded_decimals(v, d, tuple(float(x) for x in (lines or ())), bool(two_sided))
    shown = round(v, d)
    if shown == 0.0:
        body = "0"
    else:
        body = (f"{abs(shown):,.{d}f}" if grouping else f"{abs(shown):.{d}f}")
        if "." in body:
            body = body.rstrip("0").rstrip(".")
        if shown < 0:
            body = "-" + body
        elif two_sided:
            body = "+" + body
    return f"{body} {unit}".strip() if unit else body


#: HOW A PERIOD JOINS THE FIGURE IT DATES, PER PERIOD KIND (09-25 fix round, RT-4). A marketing year or a
#: crop season prints as a bare label ("2025/26") -- digits and a slash with no word of its own -- and set
#: after a COMMA it is an appositive a writer drops: the deep soybean page printed "ending stocks at 325
#: Million Bushels [N3]" beside "10.72% of domestic use for 2026/27" and lost the fact that the sheet was
#: 2025/26, off a token that read "325 Million Bushels, 2025/26". Joined by the kind's own preposition the
#: period is the figure's complement ("325 Million Bushels for 2025/26"), one noun phrase a writer copies
#: whole. The other kinds' words are already phrases ("week to 3 September 2026", "July 2026") and keep
#: the comma. A caller that names no kind keeps HEAD's comma join byte for byte.
#: THE JOIN IS THE WORDS BETWEEN THE FIGURE AND THE KIND'S OWN LABEL (09-25 N8 restore, VERIFY MINOR-B / lane
#: CC's residual): a marketing year's label is a bare "2026/27" and takes the preposition alone ("for
#: 2026/27"); a crop season's label (:func:`period_label_for`) is a NOUN, "2024/25 season", and a count noun
#: takes its article -- the cocoa N1 token read "28.52 % of grindings for 2024/25 season", true and not
#: English. The entry carries the article, so the kind's label is never re-spelt: "for the 2024/25 season".
class _BookJoins(Mapping):
    """THE PERIOD JOINS, READ OFF THE ONE BOOK (09-26 fix sitting, R-5): ``state_conventions.period_joins`` --
    ``{<period kind>: <preposition>}``, declared ONCE there and graded by ``state/lint.py`` clause 18. This
    module stays import-pure (no I/O at import): the book is read through the conventions' own cached loader
    on first use. A missing book is an empty map -- the token then prints its period with the plain comma,
    never a guessed preposition."""

    def _data(self) -> dict:
        try:
            from leviathan.graphrag.state import lint as _lint
            v = (_lint.load_conventions() or {}).get("period_joins")
            return {str(k): str(w) for k, w in dict(v).items()} if isinstance(v, dict) else {}
        except Exception:                               # noqa: BLE001 -- no book, no join
            return {}

    def __getitem__(self, key):
        return self._data()[key]

    def __iter__(self):
        return iter(self._data())

    def __len__(self):
        return len(self._data())

    def __repr__(self):
        return repr(self._data())


PERIOD_TOKEN_JOINS: Mapping = _BookJoins()


def figure_token(shown: str, *, unit: str = "", figure_basis: str = "", period_words: str = "",
                 period_role: str = "", period_kind: str = "", grain_words: str = "") -> str:
    """THE FIGURE TOKEN (CONTRACT K2): ``"<shown> <unit> <figure_basis>, <period_words>[, <period_role>]"``
    -- every part omitted when empty -- the ONE string a writer copies when it copies a figure.

    THE DEFECT IT CLOSES (items 2, 13, 27b, the 09-24 re-smoke): the row identity reached the footer and
    never the SENTENCE. The writer copies the value slot, and the value slot printed the magnitude and its
    unit alone -- "10.72 %" with its basis a clause away, "0 thousand MT" with its period elsewhere on the
    line -- so six pages printed a stocks-to-use figure with no basis and the tariff page read one week's
    figure as two. The token puts the card's own basis and the row's own period ON the figure, so the words
    that make the number true travel with it.

    ``shown`` IS ALWAYS THE ONE PRECISION PRODUCER'S TEXT (round-1 C5: :func:`figure_text` /
    ``render.shown_figure``) and may already carry its unit, in which case ``unit`` is passed empty.
    ``figure_basis`` is a CARD field (lane T, digit-free by config_check); ``period_words`` is the row's
    period at the card's own precision (``RowIdentity.period_label``); ``period_role`` is the store-period
    or closed-year words (K23 / K24). Nothing is invented here: an empty part prints nothing, so a card
    that declares no basis and a row with no period print HEAD's bare figure.

    **09-25 (RT-4 / RT-2), TWO KEYWORDS, BOTH EMPTY ON EVERY HEAD CALL:** ``period_kind`` joins the period by
    its kind's own preposition (:data:`PERIOD_TOKEN_JOINS`: "325 Million Bushels for 2025/26"), and
    ``grain_words`` puts a CELL row's grain on the figure itself ("0.9 z for one United States growing cell
    (the driest of ten)", :meth:`RowIdentity.grain_words`) -- so the words that make a regional cell's figure
    true travel with it into the sentence, exactly as the basis does."""
    head = " ".join(p for p in (str(shown or "").strip(), str(unit or "").strip(),
                                str(figure_basis or "").strip(), str(grain_words or "").strip()) if p)
    if not head:
        return ""
    pw, pr = str(period_words or "").strip(), str(period_role or "").strip()
    join = PERIOD_TOKEN_JOINS.get(str(period_kind or ""))
    if pw and join:
        return ", ".join([head + " " + join + " " + pw] + ([pr] if pr else []))
    tail = [p for p in (pw, pr) if p]
    return ", ".join([head] + tail)


def cell_rule_for(*, axis: str = "", collapse: str = "", scope: str = "", basin_surfaces=(),
                  rows_at_period: int = 0) -> tuple:
    """``(cell_rule, cell_n)`` -- WHAT ONE SERVED ROW'S LEVEL IS OVER A CELL AXIS, from the SERVED ROW'S
    GRAIN and never from the axis enum (CONTRACT K3, item 6).

    THE DERIVATION, IN ORDER: (1) the read's own collapse -- ``mean`` is the mean over the cells, ``sum``
    the sum over the destinations; (2) a scope that IS one of the producer's own aggregate surfaces
    (``basin_surfaces``: the caller hands in the producer's declared surface names -- the gold weather
    producer writes the BASIN MEAN over its member cells at exactly those scopes) is the mean over the
    cells; (3) a read that served MORE THAN ONE row at its headline period for one scope is ONE of that
    many cells (``one_of_cells``, ``cell_n`` = that count); (4) otherwise ``""`` -- FAIL CLOSED: the scope
    alone, no cell words, because a single row per period at a scope nobody declared is a grain the rows do
    not prove (the round-1 default of ``single_cell`` printed cocoa's West Africa basin mean as "one West
    Africa growing cell" four times in one footer).

    Only a CELL axis takes cell words at steps (2)-(3); a destination axis keeps its own ``sum`` and a
    national or global axis has no cells. PURE: the caller supplies every fact."""
    c = str(collapse or "")
    if c == "mean":
        return "mean_of_cells", 0
    if c == "sum":
        return "sum", 0
    if str(axis or "") != "region_cell":
        return "", 0
    sc = str(scope or "").strip()
    if sc and sc in {str(s) for s in (basin_surfaces or ())}:
        return "mean_of_cells", 0
    try:
        n = int(rows_at_period or 0)
    except (TypeError, ValueError):
        n = 0
    if n > 1:
        return "one_of_cells", n
    return "", 0


def cell_standing(values_at_period, headline) -> tuple:
    """``(rank_high, rank_low, n)`` -- WHERE ONE CELL'S HEADLINE READING STANDS AMONG THE CELLS SERVED AT ITS
    OWN PERIOD (09-25 fix round, RT-2 / D11): ``rank_high`` counts from the highest reading (1 = the highest
    of the ``n``), ``rank_low`` from the lowest. Ties share the better rank. ``(0, 0, 0)`` for a headline
    that is not a number or a cross-section of fewer than two readings -- one row is no standing.

    THE DEFECT IT CLOSES: the deep soybean page printed "US dryness at 0.90036 z then [N164] and 0.918692 z
    now [N165]" -- each the headline of a ten-cell block, sorted descending, so the DRIEST of ten cells, while
    the ten-cell mean sat at -1.02 z and the board's own US row at -0.69 z. The label said "one of several
    regional readings"; it never said WHICH one. The rank is the served rows' own order statistic, never a
    guess about which cell a region alias names (that stays the D11 data docket). PURE: the caller hands in
    the values the read served at the headline's period."""
    try:
        h = float(headline)
    except (TypeError, ValueError):
        return (0, 0, 0)
    if h != h:
        return (0, 0, 0)
    vals: list = []
    for v in (values_at_period or ()):
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if f == f:
            vals.append(f)
    if len(vals) < 2:
        return (0, 0, 0)
    return (1 + sum(1 for v in vals if v > h), 1 + sum(1 for v in vals if v < h), len(vals))


def cell_standing_words(rank: int, n: int, extreme: str) -> str:
    """"the driest of ten" / "the third driest of ten" -- one cell's standing among the ``n`` cells served at
    its period, counted from the side ``extreme`` names (the card's DECLARED superlative for that side,
    ``state_conventions.tail_words``). ``""`` when any part is missing: no standing is printed without the
    series' own word for its extreme."""
    try:
        r, k = int(rank or 0), int(n or 0)
    except (TypeError, ValueError):
        return ""
    ex = str(extreme or "").strip()
    if r < 1 or k < 2 or r > k or not ex:
        return ""
    if r == 1:
        return "the %s of %s" % (ex, words_for_int(k))
    return "the %s %s of %s" % (ordinal_words(r), ex, words_for_int(k))


_ORDINAL_WORDS = ("", "first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth",
                  "tenth", "eleventh", "twelfth")


def ordinal_words(n: int) -> str:
    """An ordinal in WORDS for the small counts a cross-section carries ("third"); a larger one in the
    numeral-free cardinal form the page's own counts use ("number twenty-one")."""
    try:
        k = int(n)
    except (TypeError, ValueError):
        return ""
    if 0 < k < len(_ORDINAL_WORDS):
        return _ORDINAL_WORDS[k]
    return "number %s" % words_for_int(k) if k > 0 else ""


def release_words(publisher: str, known_date: str) -> str:
    """WHOSE RELEASE A VINTAGE ROW IS (09-25 fix round, RT-7): "the ICCO release of 29 May 2026" -- the card's
    declared publisher (``registry.publisher_words``) and the row's own knowledge date, which on a vintage
    card IS the release it was taken from. A document of the same publisher dated EARLIER is therefore an
    earlier release of this series -- a vintage -- and the words let a writer say so instead of calling the
    gap a "trust tier". ``""`` when either part is missing (fail closed: no release is named that the card
    and the row do not both carry)."""
    pub = str(publisher or "").strip()
    day = day_words(str(known_date or "")[:10]) if str(known_date or "").strip() else ""
    if not pub or not day:
        return ""
    return "%s release of %s" % (pub, day)


def period_behind_words(pb: Optional[dict], *, asof_words: str = "") -> str:
    """THE STORE-PERIOD CLAUSE (CONTRACT K23) in words: the period this row holds is the newest the SERIES
    holds as known at the as-of, while a sibling card of the same commodity and scope already held a newer
    one -- "the newest this series holds as known on 1 March 2024; USDA WASDE held 2023/24 by then".

    A FACT ABOUT THE STORE, NEVER A CALENDAR CONSTANT (round-1 ruling F1): every word comes off the stamp
    lane C writes (``StateRow.period_behind`` = ``{"held", "newer_on", "newer"}``) and the as-of the caller
    names; nothing later than the as-of is printed (C11 -- ``newer`` is a period the store held AS KNOWN at
    the as-of). ``""`` for an empty stamp: a row with no newer sibling period prints nothing."""
    d = dict(pb or {})
    if not (d.get("held") or d.get("newer")):
        return ""
    out = "the newest this series holds as known on %s" % (asof_words or "the as-of")
    if d.get("newer"):
        src = str(d.get("newer_on") or "").strip()
        out += "; %s held %s by then" % (src or "the same source", str(d["newer"]))
    return out


def _ordinal_suffix(n: int) -> str:
    return "th" if 10 <= (abs(n) % 100) <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(abs(n) % 10, "th")


def percentile_value(p, *, lines: tuple = PERCENTILE_DECILE_LINES) -> Optional[float]:
    """THE NUMBER :func:`percentile_int` PRINTS, as a number -- the value a percentile call carries so the
    call and the printed words are the SAME magnitude (the two halves of one handle, render.py's own
    law). Half-to-even to an integer, EXCEPT where that integer sits on or across a decile line the raw
    value does not: then one decimal (89.6 stays 89.6, never 90 -- the top decile it is not in)."""
    try:
        v = float(p)
    except (TypeError, ValueError):
        return None
    if v != v:
        return None
    return round(v, _percentile_decimals(v, lines))


def _percentile_decimals(v: float, lines) -> int:
    """0 (half-to-even to an integer) unless that lands on or across a line the raw value is not on;
    then the fewest decimals that keep every line's side -- 89.6 -> one, 89.96 -> two."""
    for d in range(0, FIGURE_MAX_DECIMALS + 1):
        shown = float(round(v)) if d == 0 else round(v, d)       # round() is half-to-even at 0 dp
        if all(_side(shown, ln) == _side(v, ln) for ln in (lines or ())):
            return d
    return FIGURE_MAX_DECIMALS


def percentile_int(p, *, lines: tuple = PERCENTILE_DECILE_LINES) -> str:
    """A percentile as a reader's ordinal -- ``89th``, ``10.4th`` -- NEVER rounded onto a decile line
    (C5). ``""`` for a value that is not a number."""
    try:
        v = float(p)
    except (TypeError, ValueError):
        return ""
    if v != v:
        return ""
    d = _percentile_decimals(v, lines)
    if d == 0:
        n = int(round(v))
        return f"{n}{_ordinal_suffix(n)}"
    return f"{round(v, d):.{d}f}th"


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
    # -- the 09-23 contract's two PERIOD / PROVENANCE facts (CONTRACT.md C11; lane C writes them) ------
    #: A card whose provenance column is a RELEASE STAMP (the Pink Sheet's ``2026M09``) writes it HERE
    #: and never onto ``role``: a stamp is not a vintage role, and a stamp later than the as-of is
    #: rendered NOWHERE (the 2024 as-of turn's ``2026M09`` leak).
    release_stamp: Optional[str] = None
    #: ``{"expected": "2023/24", "served": "2020/21", "gap_periods": 3}`` where the store HOLDS, as known
    #: at the as-of, a NEWER period of the same slug on the same card than the newest period this row
    #: holds (``feeders.stamp_period_gaps`` over the board's own served rows; ``expected`` is that newest
    #: held period). The card's ``period_first_known`` only OPTS the card in -- its numbers document the
    #: measured first-print lag and stamp nothing. EMPTY on every row that carries no such gap -- the
    #: render prints nothing for it.
    period_gap: dict = field(default_factory=dict)
    #: THE STORE-PERIOD STAMP (09-24 fix round, CONTRACT K23; lane C writes it, lane W demotes on it, lane
    #: R prints it): ``{"held": "2020/21", "newer_on": "USDA WASDE", "newer": "2023/24"}`` where the store
    #: holds, as known at the as-of, a NEWER period for the SAME commodity and scope on ANY served
    #: marketing-year card than the newest this series holds (the 2024 turn read PSD US stocks-to-use for
    #: MY2020 beside WASDE US 2023/24 and printed the 2020 figure as the March-2024 buffer). EMPTY on every
    #: row with no such sibling -- the render prints nothing for it.
    period_behind: dict = field(default_factory=dict)
    #: 09-26 (CONTRACT P14, W-5): how the row's SCOPE was resolved where it is not the scope the driver declares
    #: -- ``"home_for_global"``: a driver declared for the world whose world series is fenced, read on the
    #: anchor contract's own declared home scope (lane W's feeder sets it; the render prints the declared
    #: clause). EMPTY on every other row, and then absent from :meth:`to_dict` (HEAD's shape).
    scope_resolution: str = ""

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
        if not d.get("scope_resolution"):
            d.pop("scope_resolution", None)             # 09-26: omitted when empty -- HEAD's shape
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
    live map refs, so it returns True for the 122 available-but-UNMAPPED instances (``stage_precip_z``,
    ``crush_margin_z``, ``nass_crop_progress_ge_z`` are features.yaml families). It is a DISPLAY fact
    about what the feature layer knows about, not a claim that a served series carries the ref. Reading
    a tier off it would put "measured" on 122 rows nothing measures.

    THE NUMBER IS THROUGH ``state.feeders.board_map_row``, WHICH IS THE ACCESSOR THIS CODE USES
    (coherence audit 2026-09-16, GM-A13: it read 125, which is the count through the RAW
    ``numbers.cascade.load_map()`` -- the wrong producer for the code this docstring documents).
    RE-MEASURED today over ``graph.CausalGraph.load()`` and its own ``_silver``: **126** instances are
    unmapped through ``cascade.load_map()`` and **122** through ``feeders.board_map_row``. The whole
    difference is ONE ref, ``oni_lag_climate`` -- ``board_map()`` carries it (``deferred: true`` PLUS
    ``board_read: true``) and the raw map filters it by construction -- on FOUR driver rows: ``El_Nino``
    and ``La_Nina`` on ``malaysian_crude_palm_oil_cme`` and on ``palm_olein_dce``. Reproduce by walking
    ``load_contracts()``' drivers, keeping ``silver_ref in available_silver()``, and counting the rows
    each of the two accessors returns ``None`` for.

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



# ---------------------------------------------------------------------------------------------------
# THE ROW IDENTITY (CONTRACT.md C1) -- a served row is named by its SERIES, never by the driver that
# routes to it. Lane R mints it; lanes R, A, V and C read it.
# ---------------------------------------------------------------------------------------------------
def _fold_words(s: str) -> str:
    """Two phrases compared as WORDS: lower-case, every run of non-alphanumerics one space."""
    out, prev = [], " "
    for ch in str(s or "").lower():
        c = ch if ch.isalnum() else " "
        if not (c == " " and prev == " "):
            out.append(c)
        prev = c
    return "".join(out).strip()


def _is_bare_year(s: str) -> bool:
    """A bare calendar year -- the form a marketing-year card writes its period in."""
    return len(s) == 4 and s.isdigit()


def _is_iso_day(s: str) -> bool:
    return len(s) >= 10 and s[4] == "-" and s[7] == "-" and s[:4].isdigit()


def _is_year_month(s: str) -> bool:
    return len(s) == 7 and s[4] == "-" and s[:4].isdigit() and s[5:7].isdigit()


#: The PERIOD KIND a row's own ISO date implies under its card's CADENCE, for a card that declares no
#: ``period_words``. It is the card's own declaration read with the row's own date -- a daily card's ISO
#: date IS a session, a weekly card's IS a week ending -- and never a guess about a card that says
#: neither: a shape this cannot place returns ``""`` and the label keeps the row's date as served.
_CADENCE_DAY_KIND: dict = {"daily": "day", "weekly": "week", "weekly_destination": "week",
                           "monthly": "month"}


def period_kind_for(data_date: str, *, period_words: str = "", period_type: str = "",
                    cadence: str = "") -> str:
    """The row's PERIOD KIND: the card's declared ``period_words`` wins; otherwise the shape of the row's
    own date read with the card's own ``period_type`` and ``cadence`` (:data:`_CADENCE_DAY_KIND`)."""
    if str(period_words or "") in PERIOD_KINDS:
        return str(period_words)
    s = str(data_date or "").strip()
    if ".." in s:
        return "window"
    if _is_bare_year(s):
        return "marketing_year" if str(period_type or "") == "marketing_year" else ""
    if _is_year_month(s):
        return "month"
    if _is_iso_day(s):
        kind = _CADENCE_DAY_KIND.get(str(cadence or ""), "")
        if not kind and str(cadence or "") == "annual" and str(period_type or "") == "marketing_year":
            return "marketing_year"
        return kind
    return ""


def period_label_for(kind: str, data_date: str) -> str:
    """The period a reader is shown, at the row's own precision: ``2026/27``, ``2024/25 season``,
    ``July 2026``, ``week to 10 September 2026``, ``10 September 2026``, ``November 2026`` (a delivery
    month), ``2025-01-24 to 2025-04-01`` (a window). A kind this producer cannot spell -- or a date it
    cannot place under that kind -- returns the row's own date EXACTLY as it was served, which is what
    the line printed before the identity existed: nothing is invented and nothing is dropped."""
    s = str(data_date or "").strip()
    if not s:
        return ""
    if kind in ("marketing_year", "crop_season") and s[:4].isdigit():
        y = int(s[:4])
        lab = "%d/%02d" % (y, (y + 1) % 100)
        return lab + (" season" if kind == "crop_season" else "")
    if kind in ("month", "delivery_month"):
        return month_words(s) or s
    if kind == "week":
        dw = day_words(s)
        return ("week to " + dw) if dw else s
    if kind == "day":
        return day_words(s) or s
    if kind == "window" and ".." in s:
        a, b = s.split("..", 1)
        return "%s to %s" % (a.strip(), b.strip())
    return s


def _with_commodity(name: str, cw: str) -> str:
    """THE SERIES' COMMODITY NAMES WHAT THE SERIES IS OF (K3): "production of sunflower oil", "the stocks-to-use
    ratio of rapeseed", "the head count of live animals of cattle beef" -- ONE composition, after the name,
    so no test of a name's first word decides where the commodity goes (FIXER PASS, REVIEW_RA lexical 9: the
    first cut opened "the " names by string and prefixed the rest; a declared name's article is the card's
    own words and is never parsed here). A name that already carries the commodity's words is left as it
    is (compared as words, `_fold_words`)."""
    if not cw or not name:
        return name or cw
    fn, fc = " %s " % _fold_words(name), " %s " % _fold_words(cw)
    if fc.strip() and fc in fn:
        return name
    return "%s of %s" % (name, cw)


@dataclass(frozen=True)
class RowIdentity:
    """THE ONE IDENTITY OF ONE SERVED BOARD ROW (CONTRACT.md C1). The driver id is ROUTING ONLY and is
    printed as "read here for <driver>", never as the row's name.

    THE DEFECT CLASS IT CLOSES, MEASURED ON THE 09-23 RE-SMOKE: a drought z-score served as "flash
    drought" (max F1), PSD all-class milled ending stocks as "deliverable" stocks (rice F1), PSD FSI use as
    "the ethanol grind" (corn_wheat F1), national carry-in as a "reserve" (rice F3, cotton FA-2) -- one
    series printed under a name its card never gave it. Every one was the SB-1 head printing
    ``humanise(row.driver_id)`` -- the DRIVER that routes to a series -- where the SERIES belonged. The
    name here is the card's own declared reader words (``state_conventions.reading_words``) and every
    other word is a card declaration or a served-row fact, so no rename table exists anywhere."""

    row_id: str
    contract: str
    driver_id: str
    series_key: str
    table: str
    metric: str
    name: str
    basis: str = ""
    axis: str = "national"
    scope: str = ""
    cell_rule: str = ""
    period_kind: str = ""
    period_label: str = ""
    data_date: str = ""
    known_date: str = ""
    offset_months: int = 0
    vintage_role: str = ""
    #: THE CARD'S OWN NOUN FOR ONE ROW OF A CELL AXIS, singular and plural (tables.yaml ``cell_noun``,
    #: 09-23 fix round: a DECLARATION on the card, never a word keyed on the axis enum); ``()`` = the card
    #: declares none and no cell words are printed.
    cell_noun: tuple = ()
    # ── THE 09-24 TAIL (CONTRACT K3 / K5 / K2), every field defaulted so a caller that sets none of them
    # builds HEAD's identity byte for byte ──────────────────────────────────────────────────────────────
    #: THE SERIES' COMMODITY in reader words where it DIFFERS from the reading board's own commodity --
    #: "sunflower oil" on a palm or soybean-oil board (the 09-24 soyoil page read "Russian sunflower
    #: production" off a sunflower OIL row whose identity named no commodity at all). ``""`` otherwise.
    commodity_words: str = ""
    #: How many cells stood behind the headline period where the read served one row per cell
    #: (``one_of_cells``); 0 otherwise.
    cell_n: int = 0
    #: ``""`` = the series' LEVEL; ``"window_change"`` = a CHANGE between two of its observations (K5).
    stat_kind: str = ""
    #: THE PERIOD'S ROLE (K2 ``period_role``): the store-period words (K23) where a sibling card of the
    #: same commodity and scope already held a newer period as known at the as-of. ``""`` otherwise.
    period_role: str = ""
    #: THE PUBLISHED FAMILY'S CLASS WORDS (FIXER PASS, REVIEW_WT lexical: the per-slug
    #: ``@rough_rice_cbot`` reading-words line RETIRED): "all classes[, <basis>]" where the card's family
    #: rule (``registry.class_scope``, lane T's ``commodity_families``) says the served row is USDA's
    #: all-class aggregate -- rice's "all classes, milled basis", a wheat class slug's "all classes".
    #: ``""`` otherwise. The render reads the rule; this module imports nothing.
    class_words: str = ""
    # -- THE 09-25 TAIL (RT-2 / D11), defaulted so every HEAD caller builds HEAD's identity ---------------
    #: WHERE THIS CELL'S HEADLINE STANDS AMONG THE ``cell_n`` CELLS SERVED AT ITS PERIOD (``cell_standing``,
    #: counted from the side ``cell_extreme`` names) -- 1 = the extreme itself; 0 = unranked.
    cell_rank: int = 0
    #: THE CARD'S OWN SUPERLATIVE FOR THAT SIDE ("driest", ``state_conventions.tail_words``); ``""`` = none.
    cell_extreme: str = ""

    def cell_standing_words(self) -> str:
        """"the driest of ten" where a ranked cell row carries its standing, else ``""``."""
        if self.cell_rule != "one_of_cells":
            return ""
        return cell_standing_words(int(self.cell_rank or 0), int(self.cell_n or 0),
                                   str(self.cell_extreme or ""))

    def grain_words(self) -> str:
        """THE GRAIN A CELL ROW'S FIGURE MUST CARRY (09-25, RT-2): "for one United States growing cell (the
        driest of ten)" where the row is one ranked cell of a cross-section, else ``""`` -- a national, a
        basin-mean or an unranked row puts nothing on its figure, and its head keeps its scope words."""
        sw = self.cell_standing_words()
        nouns = tuple(self.cell_noun or ()) if len(tuple(self.cell_noun or ())) == 2 else None
        if not sw or not nouns:
            return ""
        scope = str(self.scope or "").strip()
        return "for one %s%s (%s)" % ((scope + " ") if scope else "", nouns[0], sw)

    def scope_words(self) -> str:
        """The `` for <scope + cell words>`` clause, derived from the card's axis and the read's own
        collapse -- ``""`` where the axis says nothing a reader needs (a global series), and never a
        guessed cell: a cell axis whose cell rule is unknown prints the scope alone."""
        scope = str(self.scope or "").strip()
        axis = str(self.axis or "")
        nouns = tuple(self.cell_noun or ()) if len(tuple(self.cell_noun or ())) == 2 else None
        if axis == "global":
            return ""
        if nouns and self.cell_rule == "single_cell":
            return " for one %s%s" % ((scope + " ") if scope else "", nouns[0])
        if nouns and self.cell_rule == "mean_of_cells":
            return " for the mean over the %s%s" % ((scope + " ") if scope else "", nouns[1])
        if nouns and self.cell_rule == "one_of_cells" and self.cell_standing_words():
            # 09-25 (RT-2): A RANKED CELL SAYS WHICH ONE -- by its standing among the cells served at its
            # period, in the card's own superlative ("for one United States growing cell (the driest of
            # ten)"); the region alias of that cell stays the D11 data docket.
            return " " + self.grain_words()
        if nouns and self.cell_rule == "one_of_cells" and int(self.cell_n or 0) > 1:
            # ONE OF N CELLS, and N is the served rows' own count at the headline period (K3): the label
            # says only what the rows prove -- WHICH cell it is (the region alias) is docket D11.
            return " for one of the %s %s%s" % (words_for_int(int(self.cell_n)),
                                               (scope + " ") if scope else "", nouns[1])
        if axis == "destination":
            if scope:
                return " for %s as the destination" % scope
            return " summed over every destination" if self.cell_rule == "sum" else ""
        return (" for %s" % scope) if scope else ""

    def series_words(self) -> str:
        """WHAT THE SERIES IS, without WHEN: name [", " basis] [", for " scope + cell words] -- the head of
        :meth:`words` and, alone, the chain hop's name (C9, review RA M1: one row reads ONE thing on its
        SB-1 line and on every chain line that cites it -- the basis and the cell rule included).
        A BASIS THAT RESTATES THE NAME IS THE NAME, QUALIFIED (see :meth:`words`)."""
        name = str(self.name or "")
        basis = str(self.basis or "")
        cw = str(self.commodity_words or "").strip()
        # THE SERIES' OWN COMMODITY NAMES WHAT IT IS OF WHERE IT IS NOT THE BOARD'S (K3): "production of
        # sunflower oil, for Russia" -- never "production, for Russia" on a soybean-oil board. It joins the
        # NAME (fixer pass), so the basis clause after it still qualifies the whole series.
        if basis and name and _fold_words(basis).startswith(_fold_words(name)):
            out = _with_commodity(basis, cw)
        else:
            out = _with_commodity(name, cw) + ((", " + basis) if basis else "")
        if self.class_words:
            out += ", " + str(self.class_words)
        sw = self.scope_words()
        return out + (("," + sw) if sw else "")

    def short_words(self) -> str:
        """THE INLINE NOUN (K3): ``"[commodity_words ]name[ for scope]"`` -- the words lane A's name lint
        writes in place of a routing name. No basis, no period, no cell grain: the short name a sentence
        carries beside a figure whose token (K2) already states the rest."""
        name = _with_commodity(str(self.name or ""), str(self.commodity_words or "").strip())
        scope = str(self.scope or "").strip()
        if scope and str(self.axis or "") != "global":
            name += " for " + scope
        return name

    def head_words(self) -> str:
        """THE SB-1 HEAD (K2): :meth:`words` WITHOUT the period and the vintage role, which ride the FIGURE
        TOKEN instead -- the value slot is what a writer copies, so the period sits on the figure and the
        head names the series once. The declared offset clause stays here: it says WHICH reading of the
        series the row is, which is a fact about the series and not about the figure."""
        out = self.series_words()
        n = int(self.offset_months or 0)
        if n > 0:
            out += (", read %s %s back -- the reading whose declared lag lands now"
                    % (words_for_int(n), "month" if n == 1 else "months"))
        return out

    def token_period_words(self) -> str:
        """The period the figure token carries (K2 ``period_words``): the period label at the card's own
        precision plus the vintage role where it is one -- "2026/27 (projection)"."""
        out = str(self.period_label or "")
        if out and self.vintage_role:
            out += " (%s)" % self.vintage_role
        return out

    def words(self) -> str:
        """THE ONE PRINTED IDENTITY PHRASE, in the contract's FIXED order: name [", " basis]
        [", for " scope + cell words] [", " period_label] [" (" vintage_role ")"] [", read <n> months
        back -- the reading whose declared lag lands now" where a declared offset was applied]. The scope
        takes a comma, as the contract's own example does ("..., for one United States growing cell,
        July 2026"), so it can never read as the tail of a basis clause.

        A BASIS THAT RESTATES THE NAME IS THE NAME, QUALIFIED: where the card's declared basis opens with
        the declared series name (the FSI card names "food, seed and industrial use" and qualifies it
        "food, seed and industrial use -- ethanol is inside it"), the basis is printed ONCE, in place of
        the name -- one phrase, never the same words twice. Compared as words, never as bytes."""
        out = self.series_words()
        if self.period_label:
            out += ", " + self.period_label
        if self.vintage_role:
            out += " (%s)" % self.vintage_role
        if self.period_role:
            out += " -- " + self.period_role
        n = int(self.offset_months or 0)
        if n > 0:
            out += (", read %s %s back -- the reading whose declared lag lands now"
                    % (words_for_int(n), "month" if n == 1 else "months"))
        return out


def row_identity(*, contract: str, driver_id: str, st, card: dict, reading_words: str,
                 offset_applied: Optional[bool] = None, basin_surfaces=(), rows_at_period: int = 0,
                 commodity_words: str = "", stat_kind: str = "",
                 period_role: str = "", class_words: str = "", cell_rank: int = 0,
                 cell_extreme: str = "") -> RowIdentity:
    """THE PRODUCER of :class:`RowIdentity` -- pure, over the served row ``st`` (a :class:`StateRow`)
    and its card's declared fields ``card`` (``render.card_fields`` plus the card facts the render reads
    beside them). ``reading_words`` is the declared series name; the render is the only caller that
    fetches it.

    EVERY FIELD IS DERIVED: ``axis`` from the card's ``country_axis`` (else its declared
    ``country_axis_is_destination``, else the series key's own global normalisation, else national);
    ``cell_rule`` from the read's own collapse (``mean`` over cells, ``sum`` over destinations) and, on a
    card that declares its rows are cells, one row per period IS one cell; the period from the card's
    ``period_words`` (else the date's own shape and the card's cadence, :func:`period_kind_for`); the
    vintage role ONLY when the row's role is a member of :data:`VINTAGE_ROLES`; the offset ONLY when the
    producer says it was applied (``offset_applied``, else ``recency['offset_applied']``).

    **09-24 (CONTRACT K3): THE CELL RULE IS THE SERVED ROW'S GRAIN** (:func:`cell_rule_for`), fed by the
    caller's two facts -- the producer's own aggregate surfaces (``basin_surfaces``) and the served rows'
    count at the headline period (``rows_at_period``) -- and never the axis enum. ``commodity_words``,
    ``stat_kind`` and ``period_role`` are the caller's (the render resolves the series' commodity through
    the one display producer; this module imports nothing)."""
    card = dict(card or {})
    key = getattr(st, "key", None)
    table = str(getattr(st, "table", "") or getattr(key, "ref", "") or "")
    metric = str(getattr(st, "metric", "") or getattr(key, "ref", "") or "")
    try:
        skey = key.label() if key is not None else ""
    except Exception:                                   # noqa: BLE001 -- an unlabelled key names nothing
        skey = ""
    is_global = bool(getattr(key, "is_global", False))
    axis = str(card.get("country_axis") or "")
    if axis not in AXIS_KINDS:
        if card.get("country_axis_is_destination"):
            axis = "destination"
        elif is_global:
            axis = "global"
        else:
            axis = "national"
    scope = "" if (is_global or axis == "global") else str(getattr(key, "country", "") or "")
    collapse = str(getattr(st, "collapse", "") or "")
    cell_rule, cell_n = cell_rule_for(axis=axis, collapse=collapse, scope=scope,
                                      basin_surfaces=basin_surfaces, rows_at_period=rows_at_period)
    data_date = str(getattr(st, "level_date", "") or "")
    kind = period_kind_for(data_date, period_words=str(card.get("period_words") or ""),
                           period_type=str(card.get("period_type") or ""),
                           cadence=str(getattr(st, "cadence", "") or card.get("cadence") or ""))
    role = str(getattr(st, "role", "") or "").strip().lower()
    if offset_applied is None:
        rec = getattr(st, "recency", None) or {}
        offset_applied = (bool(rec["offset_applied"]) if "offset_applied" in rec
                          else bool(getattr(st, "offset_months", 0)))
    off = int(getattr(st, "offset_months", 0) or 0) if offset_applied else 0
    return RowIdentity(
        row_id="%s|%s|%s" % (contract, driver_id, skey), contract=str(contract or ""),
        driver_id=str(driver_id or ""), series_key=skey, table=table, metric=metric,
        name=str(reading_words or card.get("label") or ""),
        basis=str(card.get("basis_words") or ""), axis=axis, scope=scope, cell_rule=cell_rule,
        period_kind=kind, period_label=period_label_for(kind, data_date), data_date=data_date,
        known_date=str(getattr(st, "knowledge_date", "") or ""), offset_months=off,
        vintage_role=role if role in VINTAGE_ROLES else "",
        cell_noun=tuple(str(x) for x in (card.get("cell_noun") or ()))[:2],
        commodity_words=str(commodity_words or ""), cell_n=int(cell_n or 0),
        stat_kind=str(stat_kind or ""), period_role=str(period_role or ""),
        class_words=str(class_words or ""),
        cell_rank=(int(cell_rank or 0) if cell_rule == "one_of_cells" else 0),
        cell_extreme=(str(cell_extreme or "") if cell_rule == "one_of_cells" else ""))
