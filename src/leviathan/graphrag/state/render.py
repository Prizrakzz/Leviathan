"""THE ROW CLASSES -- STATE ENGINE DESIGN sec 6.1 (one block, one marker, closed vocabularies), 6.2
(the eighteen row classes as the acceptance spec), 6.3 (every figure is an ``[N]`` the verifier can
bind), 6.6 (fences CORRECT or COMPUTE, never delete) and 6.7 (the closed absence vocabulary rendered as
a sentence per word). Sitting S3.

WHAT THIS MODULE IS. The board's ONE renderer: a builder per row class, each returning
``(line, calls)``; a compiled regex per class that the lint asserts is pairwise disjoint; the ONE
marker the S6 seam gate keys on; and :func:`render_board`, which assembles the block in a declared
section order and applies the SB-X REPLACEMENT FENCE line by line. It decides no order (that is
``walk.py``), computes no state (``feeders.py``) and selects no analog (``analogs.py``).

THREE PROPERTIES THIS MODULE EXISTS TO MAKE STRUCTURAL:

  1. **ONE HANDLE PER MAGNITUDE** (sec 6.3, K9-6). Every figure the board prints mints its own call
     record in ``_cw_call``'s shape (cascade.py:7465) carrying ``shown=[that one magnitude]``, so
     ``citations.unify`` numbers it, ``from_number`` labels it and ``verify._check_number_handle``
     value-checks the writer's copy against ``_mismatch_pool``. A line and its calls are committed
     TOGETHER or not at all (see the fence below), because a handle pointing at a call that was
     dropped is worse than either.
  2. **WORDS ARE FREE, DIGITS ARE NOT.** The letters-only classes (SB-E / SB-J / SB-F / SB-A / SB-P /
     SB-C / SB-X) carry no ``[N]`` and no charged digit, which is what lets sign words, band words and
     the conditional projection ride prose without a fence. Counts, run lengths and window lengths
     render through :func:`words_for_int`; ISO dates and 4-digit years ride as themselves because
     ``verify._claim_number_spans`` rules (a), (b) and (d) exempt exactly those (verify.py:314 / :327 /
     :606-614).
  3. **A TRIPPED TEMPLATE IS CORRECTED, NEVER DELETED** (sec 6.6). The templates here are CLOSED and
     linted at BUILD against all four register detectors, so a serve-time trip is a build defect -- and
     if one fires anyway the offending LINE is replaced by its own SB-X absence
     (``template_register_trip``), every other row survives, and the trip is stamped. Drafts C and D's
     drop-whole ``_board_register_fence`` is not here: suppression instead of correction is fatal in
     review.

ASCII-ONLY on everything this module prints; the file itself is UTF-8.
"""
from __future__ import annotations

import re
from typing import Optional

from leviathan.graphrag.state.lagbands import LagBand
from leviathan.graphrag.state.rows import SIGN_WORDS, status_word

# ---------------------------------------------------------------------------------------------------
# THE MARKER (sec 6.1) -- minted ONCE here and imported by the seam gate at S6
# ---------------------------------------------------------------------------------------------------
#: The block's own marker PREFIX. The S6 gate tests the PREFIX exactly as ``CW_MARKER_PREFIX in vp``
#: does (cascade.py:7768; answer.py's `_cascade_walk_block_on` shape), never a marker carrying the
#: as-of -- a marker that carried the date would make the gate a date comparison and would stop
#: matching the moment the block's header changed a character after it.
SB_MARKER_PREFIX = "STATE OF THE WORLD at "


def block_marker_present(volatile_prompt: Optional[str]) -> bool:
    """``SB_MARKER_PREFIX in vp`` -- the predicate S6's ``_state_board_block_on`` calls, minted beside
    the marker so the gate and the producer can never drift apart (the CW_MARKER_PREFIX law)."""
    return SB_MARKER_PREFIX in (volatile_prompt or "")


# ---------------------------------------------------------------------------------------------------
# NUMERALS AS WORDS -- the one place a count becomes text
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
    """``2026-08-31`` -> ``August 2026``. The 4-digit year rides as a numeral because
    ``_claim_number_spans`` rule (a) exempts a bare calendar year 1900-2099 (verify.py:606-609), which
    is what lets a PROJECTION line name two calendar months without carrying a charged digit."""
    s = str(iso or "")
    if len(s) < 7:
        return ""
    try:
        m = int(s[5:7])
    except ValueError:
        return ""
    if not 1 <= m <= 12:
        return ""
    return f"{MONTH_NAMES[m - 1]} {s[0:4]}"


#: The ordinal suffix by the numeral's own last two digits -- eleven, twelve and thirteen take "th" and
#: everything else follows its last digit. `derived._dv_ordinal` is the estate's own twin; this one is
#: here because a percentile is the board's most common figure and "82th percentile" was what the first
#: cut of :func:`sb_state` printed on the scenario-1 harness.
def ordinal(n) -> str:
    try:
        n = int(n)
    except (TypeError, ValueError):
        return str(n)
    if 10 <= (abs(n) % 100) <= 20:
        return f"{n}th"
    return f"{n}" + {1: "st", 2: "nd", 3: "rd"}.get(abs(n) % 10, "th")


def _fmt(v, places: int = 2) -> str:
    """A magnitude as the reader sees it: no exponent, no trailing zeros, no thousands comma (a comma
    would make ``_claim_number_spans`` read ``2,021`` as a magnitude with punctuation and would put the
    board's own figures on a different footing from the agent's)."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return ""
    s = f"{f:.{places}f}".rstrip("0").rstrip(".")
    return s if s not in ("", "-") else "0"


# ---------------------------------------------------------------------------------------------------
# THE CLOSED WORD MAPS (sec 6.2: "every literal, sign word, run word and convention word comes from a
# closed map")
# ---------------------------------------------------------------------------------------------------
CONFIDENCE_WORDS: dict = {"high": "high", "medium": "medium", "low": "low"}

#: A run's direction as a word. ``streak`` returns ``up``/``down``; the board never says "improving".
RUN_DIRECTION_WORDS: dict = {"up": "rising", "down": "falling"}

#: The cadence's own period noun, singular and plural -- ``feeders._period_noun``'s table restated as a
#: RENDER map (the producer's copy is used to LABEL a change window; this one is used in prose).
PERIOD_NOUNS: dict = {"daily": "session", "weekly": "week", "weekly_destination": "week",
                      "biweekly": "fortnight", "monthly": "month", "annual": "marketing year",
                      "release": "release"}


def period_noun(cadence: str, n: int = 2) -> str:
    noun = PERIOD_NOUNS.get(cadence or "", "period")
    return noun if n == 1 else noun + "s"


def band_words(band: Optional[LagBand]) -> str:
    """A lag band as WORDS, never a point and never a sum (sec 2.3, D3).

    ``structural`` prints the design's own phrase for an open horizon; an unparsed spelling says the
    table does not carry it rather than reading as contemporaneous, which is the whole reason
    :class:`LagBand` keeps ``min_q is None`` distinct from ``min_q == 0``."""
    if band is None or band.min_q is None:
        return "a lag the table does not carry"
    if band.max_q is None:
        return "beyond two years"
    if band.min_q == band.max_q:
        return ("within the same quarter" if band.min_q == 0
                else f"{words_for_int(band.min_q)} {_quarters(band.min_q)}")
    return (f"{words_for_int(band.min_q)} to {words_for_int(band.max_q)} "
            f"{_quarters(band.max_q)}")


def _quarters(n: int) -> str:
    return "quarter" if int(n) == 1 else "quarters"


def sign_words(sign: Optional[str]) -> str:
    """The three-entry map of sec 1.5. An UNDECLARED sign is a different fact from an ambiguous one and
    says so; folding them would lose the distinction ``sign_undeclared`` exists to keep."""
    w = SIGN_WORDS.get(str(sign or ""))
    return w or "in a direction the graph does not declare"


#: Every closed absence word of sec 6.7 as ONE plain sentence -- ``_CW_ABSENCE_WHY``'s shape
#: (cascade.py:7528). THE MAP IS THE CONTRACT: a word added to a closed enum in ``board.py`` or
#: ``rows.py`` and not given a sentence here renders as the fallback, and ``state/lint.py`` fails on it.
#: A reader never meets a code word.
ABSENCE_WHY: dict = {
    # series (rows.STATUS_WORDS + board.SERIES_REASONS)
    "unmapped_ref": "the graph names a series no served card carries, so there is nothing to read",
    "scope_unresolved": "the region this row declares does not resolve to a single scope the store can "
                        "be asked about",
    "series_planned": "the series is declared as planned work and is not served yet",
    "series_none": "the graph declares no series for this driver at all",
    "read_empty": "the read returned no rows for this scope at this as-of",
    "read_error": "the read did not complete, so this row has no state this turn",
    "thin_history": "the series holds too few points for a standing against its own history",
    "zero_variance": "the series does not vary over its own window, so a standing would divide by "
                     "nothing",
    "history_truncated": "the read came back at its own row cap, so the history behind it is partial "
                         "and no standing is claimed",
    "budget_cap": "this turn's read budget was spent before these keys, which are named here",
    "outlook_lane": "positioning is not read as a series on this kind of turn",
    "pool_exhausted": "no reader slot came free for this series inside this turn",
    "pg_timeout": "the read for this series did not return inside its own time",
    # edge
    "sign_undeclared": "the graph declares no direction on this link",
    "lag_unparsed": "the graph declares a lag the table does not carry",
    "far_series_other_table": "that board reads this driver from a different card, which is a different "
                              "series and not this one",
    "lag_undeclared_between_nodes": "the graph declares no lag between these two nodes, only each "
                                    "node's own lag onto the price",
    # fan / path / convergence
    "fan_cap": "the far boards past this tier's fan are named here; their own states were not read",
    "board_unlabeled": "that board carries this driver with no series label",
    "child_uncovered": "that board does not carry this driver",
    "render_cap": "the rows past this tier's render cut are named here",
    "edge_hop_cap": "this tier walks the links in one direction only",
    "when_not_all_loud": "the drivers this amplifier names do not all sit among this board's loudest "
                         "rows",
    # tape
    "no_tape_slug": "no per-contract tape is served for this board",
    "pre_coverage": "the as-of sits before this board's own tape coverage begins",
    "front_decline": "the front delivery month could not be named by the roll rule on this session",
    "changes_thin": "the same-contract series is shorter than the changes this row would print",
    "percentile_thin": "there are too few sessions on this contract for a standing",
    # analog
    "no_like_state": "no past state on this series is like this one under the likeness rule",
    "horizon_open": "the band from that date has not closed yet, so its outcome is not readable",
    "span_out_of_band": "the window the outcome needs is outside the span the tape read certifies",
    "no_tape_rows": "the series carries no observation over that window",
    "read_truncated": "the read for that window came back at its own cap",
    "no_receipt": "no documents exist for it",
    "no_numeric_event_history": "no numeric event history exists for this driver; prior steps are "
                                "receipts, not analogs",
    "near_unreachable": "the date named in the question has a band that has not closed",
    # watch
    "no_calendar_rule": "no release rule is declared for this series",
    "rule_unverified": "the publisher states its next date rather than following a rule this board can "
                       "compute",
    "no_convention": "no desk line is declared for this series",
    "no_open_window": "no declared lag window is open on this row",
    "no_policy_date": "the record holds no forward date for this driver",
    # render / board
    "template_register_trip": "a line this board composed did not pass its own register check and was "
                              "replaced by this note",
    "pg_not_live": "the reader this board uses is not available on this turn",
    "anchor_none": "the question named no market this estate tracks",
    "turn_spend_unknown": "this turn's own read count is not available to the board",
    "lane_off": "this turn does not run the board",
}

#: The fallback. It is deliberately a SENTENCE and not the raw word: a reader must never be shown a
#: code token, and ``state/lint.py`` fails when a closed word has no entry above, so this string is
#: what a lint failure looks like at serve time rather than what a normal turn prints.
ABSENCE_FALLBACK = "the record does not carry a measurable read here"


def absence_why(reason: str) -> str:
    """The plain sentence for a possibly-parametrised closed word (``thin_history:3`` -> its sentence).
    The DETAIL is deliberately dropped: it is a count, and a count in a letters-only class is a digit."""
    return ABSENCE_WHY.get(status_word(reason or ""), ABSENCE_FALLBACK)


#: The transliterations the estate's own curated text actually contains. It is a MAP and not a codec
#: call because a reader must meet "El Nino", not "El Ni?o" and not "El Nin\\u0303o": the fold is a
#: display decision, and the two characters below are the ones MEASURED in the shipped DAGs (the palm
#: board's `bullish_supply_squeeze` interaction note carries U+00F1).
_ASCII_FOLD: dict = {
    "\u00e0": "a", "\u00e1": "a", "\u00e2": "a", "\u00e3": "a", "\u00e4": "a", "\u00e5": "a",
    "\u00e7": "c", "\u00e8": "e", "\u00e9": "e", "\u00ea": "e", "\u00eb": "e",
    "\u00ec": "i", "\u00ed": "i", "\u00ee": "i", "\u00ef": "i", "\u00f1": "n",
    "\u00f2": "o", "\u00f3": "o", "\u00f4": "o", "\u00f5": "o", "\u00f6": "o",
    "\u00f9": "u", "\u00fa": "u", "\u00fb": "u", "\u00fc": "u", "\u00fd": "y",
    "\u2013": "-", "\u2014": "--", "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
    "\u2026": "...", "\u00b0": " degrees", "\u00a0": " ",
}


def ascii_text(s: str) -> str:
    """FREE TEXT FROM THE GRAPH OR THE CORPUS, folded to ASCII (sec 6.1's ASCII law).

    Every literal this module OWNS is ASCII by construction; the strings it INTERPOLATES are not --
    an interaction's ``note``, a receipt's ``text``, a source name. MEASURED at this landing: the palm
    board's ``bullish_supply_squeeze`` note carries "El Ni\u00f1o" and the rendered block was therefore
    not ASCII, which the harness's own stdout wrapper hid by backslash-escaping it on the way out. The
    BLOCK is what reaches a writer, so the fold belongs here and not at the printer."""
    out = []
    for ch in str(s or ""):
        if ord(ch) < 128:
            out.append(ch)
            continue
        out.append(_ASCII_FOLD.get(ch, " "))
    return "".join(out)


def humanise(node_id: str) -> str:
    """A driver id as reader words, through the estate's ONE display vocabulary
    (``display.node_label``): a curated override wins, otherwise the id de-underscores PRESERVING token
    case so BRL, USD and ENSO read right.

    THIS IS NOT A CONVENIENCE. ``register.internal_leaks`` (:836) is NEVER RELAXABLE and it greps reader
    prose for raw contract slugs, raw regime ids and labelled metric slugs; a board that printed
    ``soybeans_cbot`` would trip it on EVERY line, which is exactly what the first cut of this module
    did -- 281 of 337 rendered lines were replaced by their own SB-X correction, MEASURED on the
    scenario-1 harness before these three functions existed. One vocabulary, one producer."""
    from leviathan.graphrag import display as _display
    return ascii_text(_display.node_label(str(node_id or "")))


def board_label(slug: str) -> str:
    """A CONTRACT slug as reader words -- ``display.node_label(slug, kind='contract')``, which is
    ``'{EXCH} {node}'`` off the hierarchy (``soybeans_cbot`` -> ``CBOT soybeans``). It is the same
    vocabulary ``cascade._CW_BOARD_LABEL`` (:7035) carries for the walk's own rows, read from the
    hierarchy rather than re-typed as a second table."""
    from leviathan.graphrag import display as _display
    return ascii_text(_display.node_label(str(slug or ""), kind="contract"))


def table_words(table: str) -> str:
    """A card as its SOURCE label (``silver_noaa_oni`` -> ``NOAA ONI``). An unmapped table strips
    ``silver_`` and upper-cases, so this function cannot return a raw slug -- which is why the reader
    half of an SB-1 line names the SOURCE while the call record keeps the machine ``metric``
    (``_cw_call``'s own review D9: a display label in the query poisons the citations locator)."""
    from leviathan.graphrag import display as _display
    return ascii_text(_display.table_label(str(table or "")))


def pattern_label(name: str) -> str:
    """A convergence pattern id as reader words (``display.regime_label``), which also appends the
    declared direction in words. A raw regime id in prose is an ``internal_leaks`` hit by construction."""
    from leviathan.graphrag import display as _display
    return ascii_text(_display.regime_label(str(name or "")))


# ---------------------------------------------------------------------------------------------------
# THE CALL RECORD (sec 6.3) -- `_cw_call`'s shape, one handle per magnitude
# ---------------------------------------------------------------------------------------------------
def sb_call(*, table: str, metric: str, commodity: Optional[str], country: Optional[str],
            period: str, asof: str, value, unit: str = "", knowledge_date: Optional[str] = None,
            z_window=None, z_series: Optional[str] = None, role: Optional[str] = None) -> dict:
    """ONE synthetic call record for ONE magnitude -- ``_cw_call`` / ``_dv_call``'s own shape
    (cascade.py:7465, derived.py:73), so ``citations.unify`` numbers it in call order and
    ``from_number`` labels it from the same record. One producer, one row, one ``shown``.

    ``country`` IS THE RESOLVED SCOPE AND IS NEVER ABSENT ON A MULTI-GEO CARD (K9-2): the board's own
    key resolution produced it, so ``citations._unscoped_multi_geo`` can never fire on a board row.
    ``z_window`` / ``z_series`` ride the ROW (citations.py:1432-1434 reads them there, not off the
    query), which is what renders "vs {n} points of {series}" on a z handle without a second producer."""
    row: dict = {"value": value}
    if unit:
        row["unit"] = unit
    if knowledge_date:
        row["knowledge_date"] = knowledge_date
    if z_window is not None:
        row["z_window"] = z_window
    if z_series:
        row["z_series"] = z_series
    if role:
        row["provenance"] = role
    call = {"query": {"table": table, "metric": metric, "commodity": commodity, "country": country,
                      "period": period, "asof": asof},
            "rows": [row], "status": "ok", "_sb": True}
    try:
        call["shown"] = [float(value)]
    except (TypeError, ValueError):                 # a magnitude that is not a float is not `shown`
        pass
    return call


def series_tag(*, commodity: Optional[str], country: Optional[str], table: str) -> str:
    """The SCOPE suffix an SB-1 line ends with -- ``cascade._series_tag``'s reader-facing shape
    (:2562), restated rather than imported because that file is the K9 lane's and this package edits
    and imports nothing there beyond the pinned surface of ``feeders.CASCADE_IMPORTS``.

    IT IS ALSO THIS CLASS'S DISCRIMINATOR: SB-1 is the ONLY class that carries the tag, which is what
    makes :data:`ROW_CLASSES`' regexes pairwise disjoint without inventing a class token the design's
    templates do not have."""
    segs = [("series", commodity), ("country", country), ("table", table)]
    body = "; ".join(f"{k}: {v}" for k, v in segs if v)
    return f" [{body}]" if body else ""


# ---------------------------------------------------------------------------------------------------
# THE ROW CLASSES (sec 6.2) -- one compiled regex each, asserted pairwise disjoint by state/lint.py
# ---------------------------------------------------------------------------------------------------
_ISO = r"\d{4}-\d{2}-\d{2}"
_YM = r"\d{4}-\d{2}"

ROW_CLASSES: dict = {
    "SB-H": re.compile(r"^STATE OF THE WORLD at "),
    "SB-1": re.compile(r"^- \[N\d+\] .*\[(?:series|country|table): [^\]]*\]$"),
    # SB-V IS THE KIND-2 WATCH ROW, and the class token is the WATCH word plus a HANDLE. Sec 6.2's
    # own table gives SB-W "ISO dates + kind-2 figure", and sec 5.1 mints that one figure under its own
    # handle -- so the reader meets ONE watch vocabulary and the lint keeps TWO classes: a handled watch
    # line (this one, figure-bearing) and an unhandled one (SB-W, letters and ISO dates). The first cut
    # rendered kind 2 with no WATCH word at all, which cost the writer the row: the mandate's fourth
    # movement tells it to close with the WATCH rows, and a bare distance line is not one of them.
    "SB-V": re.compile(r"^- \[N\d+\] WATCH the level a convention names "),
    "SB-T": re.compile(r"^- \[N\d+\] .+ front " + _YM + r" settle on " + _ISO + r": "),
    "SB-O": re.compile(r"^- \[N\d+\] .+ over the band the graph declares from that state, "),
    "SB-W": re.compile(r"^- WATCH "),
    "SB-R": re.compile(r"^- \[E\d+\]\[T\d+\] "),
    "SB-E": re.compile(r"^- .+ is declared to move .+ with a lag the graph states as "),
    "SB-J": re.compile(r"^- conditional on the lag the graph states, counted from "),
    "SB-D": re.compile(r"^- .+ dated " + _ISO + r" by \[E\d+\] \(published " + _ISO + r"\): "),
    "SB-F": re.compile(r"^- the same reading is declared on "),
    "SB-C": re.compile(r"^- .+ on .+: .+ of its .+ declared drivers sits? among "),
    "SB-M": re.compile(r"^  amplifier on "),
    "SB-P": re.compile(r"^UPSTREAM "),
    "SB-A": re.compile(r"^LIKE STATE "),
    "SB-L": re.compile(r"^RECENCY "),
    "SB-X": re.compile(r"^BOARD ABSENCE "),
}

#: The classes that may carry a charged digit. Every OTHER class is letters-plus-dates only, and
#: ``state/lint.py`` charges any digit in one of them that is not part of an ISO date or a 4-digit year.
FIGURE_CLASSES: frozenset = frozenset({"SB-1", "SB-V", "SB-T", "SB-O"})

#: The classes whose only digits are ISO dates (sec 6.2's "ISO dates only" column).
DATE_ONLY_CLASSES: frozenset = frozenset({"SB-H", "SB-D", "SB-L", "SB-R"})


def classify(line: str) -> tuple:
    """Every class whose regex matches ``line``. The lint asserts exactly one on every rendered line --
    that IS the disjointness bar, measured on real output rather than argued about between regexes."""
    return tuple(name for name, rx in ROW_CLASSES.items() if rx.search(line or ""))


# ---------------------------------------------------------------------------------------------------
# THE BUILDERS -- each returns (line, calls)
# ---------------------------------------------------------------------------------------------------
def sb_header(bd, *, anchor_label: str = "", n_series: Optional[int] = None,
              n_receipts: Optional[int] = None) -> str:
    """SB-H (sec 6.1). The counts are in WORDS and the ordering rule is a LITERAL, because a header that
    read as a ranking of one series against another would misdescribe the one thing the rank does: each
    z is against its OWN window.

    THE SENTENCE IS THE TUPLE THAT RAN. ``walk.rank_rule_words`` reads the board's own ``rank_rule``, so
    an alternative-tuple arm (P1) prints the alternative's rule and a reader -- or a census row -- can
    never be told an ordering the page did not use."""
    from leviathan.graphrag.state.walk import rank_rule_words
    rule_words = rank_rule_words(getattr(bd, "rank_rule", "d2"))
    label = anchor_label or ", ".join(board_label(s) for s in bd.anchor_slugs) or "no named market"
    if n_series is None:
        n_series = sum(1 for r in bd.rows
                       if r.state is not None and status_word(r.state.status) == "ok")
    if n_receipts is None:
        n_receipts = sum(1 for r in bd.rows if (r.receipts or {}).get("n"))
    return (f"{SB_MARKER_PREFIX}{bd.asof} for {label}: {words_for_int(n_series)} drivers read on "
            f"their own series, {words_for_int(n_receipts)} carried as dated receipts; "
            f"{rule_words}.")


def sb_state(n: int, row, *, asof: str, age_clause: str = "") -> tuple:
    """SB-1 (sec 6.2): the STATE row, ONE HANDLE PER MAGNITUDE.

    Three handles at most -- the level, the z, the percentile -- each with its own call carrying its
    own single ``shown`` value. A measure that DECLINED mints no handle and says so in words instead:
    ``derived.py:322-331`` is the precedent for minting the percentile under its own handle, and
    ``_cw_cell_line`` (:7449) is the precedent for one magnitude per handle.

    A FLAG ROW (``*_flag`` refs) carries ``flag_state`` where a z and a percentile would be, because a
    sigma over a 0/1 column is a base rate wearing a sigma's clothes (``stats.flag_events``). Its ONE
    magnitude is the event count, and the rest of the sentence is dates and words."""
    st = row.state
    calls: list = []
    if st is None:
        return "", calls
    unit = st.narrate_unit or st.unit or ""
    period = str(st.level_date or "")
    if st.role:
        period = f"{period} {st.role}".strip()
    label = humanise(row.driver_id)
    reader = table_words(st.table or st.key.ref)
    q = {"table": st.table or st.key.ref, "metric": st.metric or st.key.ref,
         "commodity": st.key.commodity or row.contract, "country": st.key.country or None,
         "period": period, "asof": asof}

    parts: list = []
    h = n
    if st.flag_state:
        fs = st.flag_state
        calls.append(sb_call(value=fs.get("events_in_window"), unit="events",
                             knowledge_date=st.knowledge_date, role=st.role, **q))
        noun = period_noun(st.cadence, int(fs.get("window_periods") or 2))
        parts.append(f"- [N{h}] {label} on {board_label(row.contract)}, {reader} for {period}: "
                     f"{_fmt(fs.get('events_in_window'), 0)} events in its last "
                     f"{words_for_int(fs.get('window_periods'))} {noun}")
        last = fs.get("last_event_date")
        parts.append(f"the last was dated {last}" if last
                     else "the series carries no event at all")
    else:
        lvl = _level_words(st)
        calls.append(sb_call(value=st.level, unit=unit, knowledge_date=st.knowledge_date,
                             role=st.role, **q))
        parts.append(f"- [N{h}] {label} on {board_label(row.contract)}, {reader} for {period}: {lvl}")
        if _ok(st.z):
            h += 1
            win = st.z.get("window_n") or st.z.get("window") or st.z.get("n")
            calls.append(sb_call(value=round(float(st.z["value"]), 1), unit="sigma",
                                 knowledge_date=st.knowledge_date, z_window=win,
                                 z_series=f"{q['table']}.{q['metric']}", **q))
            parts.append(f"[N{h}] {float(st.z['value']):+.1f} sigma on its trailing window of "
                         f"{words_for_int(win)} {period_noun(st.cadence, int(win or 2))}")
        else:
            parts.append("its own history carries no standing this turn: "
                         + absence_why((st.z or {}).get("reason") or "thin_history"))
        if _ok(st.percentile):
            h += 1
            pv = int(round(float(st.percentile["value"])))
            calls.append(sb_call(value=pv, unit="percentile", knowledge_date=st.knowledge_date, **q))
            parts.append(f"[N{h}] {ordinal(pv)} percentile of its own record")
        else:
            # A MEASURE THAT DECLINED IS A CLAUSE, NEVER A SILENCE. The z arm already said so; without
            # this one a row whose z computed and whose percentile did not would print two handles and
            # no word about the third, and a reader would not know a rank had been attempted at all.
            parts.append("its own record carries no rank for this reading: "
                         + absence_why((st.percentile or {}).get("reason") or "thin_history"))
    if st.run and not st.run.get("declined"):
        d = RUN_DIRECTION_WORDS.get(str(st.run.get("direction") or ""), "moving one way")
        ln = int(st.run.get("length") or 0)
        parts.append(f"{d} over the last {period_noun(st.cadence, 1)}" if ln == 1 else
                     f"{d} in each of the last {words_for_int(ln)} {period_noun(st.cadence, ln)}")
    if st.convention and st.convention.get("matched") and st.convention.get("label"):
        parts.append(f"past the line the desk convention calls {st.convention['label']}")
    if row.context_only:
        # D18's ONE rule, on the row that carries it: a positioning row is READ and RENDERED and is
        # never a fan source, a convergence member, an analog dimension or a projection anchor. The
        # clause is PAST TENSE and says what the row is for, because the R9 guard's measured failure was
        # positioning narrated as a CAUSE of the anchor's price.
        parts.append("historical context only: this row is what the reporting funds held, never a "
                     "cause the graph declares")
    if age_clause:
        parts.append(age_clause)
    if st.vintage_note:
        parts.append(st.vintage_note)
    if st.offset_note:
        parts.append(offset_words(st))
    line = "; ".join(parts) + series_tag(commodity=board_label(row.contract), country=q["country"],
                                         table=table_words(q["table"]))
    return line, calls


def offset_words(st) -> str:
    """The declared same-series offset note WITH ITS REF TOKENS FOLDED TO THE SERIES' DISPLAY LABEL
    (sec 2.6 item 1).

    The literal is the producer's (``feeders``), and it is the ONE place an internal id survived every
    other display fold on this page: "the same series as oni_climate, read at a declared 6-month
    offset" reaches a writer with a raw ref in it. ``register.internal_leaks`` (:836) is never relaxable
    and the estate's own display vocabulary is one call away, so the fold happens where the note meets a
    reader rather than where it is composed -- which leaves the producer's note re-readable in a trace
    and its rendered half in reader words.

    **AND THE PARENT IS A SERIES, SO IT WEARS THE SERIES' LABEL.** The first fold ran the base REF
    through ``humanise`` -- the DRIVER vocabulary -- and printed "the same series as oni climate": a
    de-underscored id wearing reader spacing, on the one clause whose subject is a source rather than a
    node. A ``same_series_as`` fold reads the BASE's own table and metric (that is what makes the alias
    free), so the row's own source label IS the parent series' label, and the clause now reads "the same
    series as NOAA ONI" -- the same words the line's own ``[table: ...]`` tag carries, which is what
    lets a reader see that the two are one series."""
    note = str(getattr(st, "offset_note", "") or "")
    if not note:
        return ""
    label = table_words(str(getattr(st, "table", "") or "")) or humanise(
        str(getattr(st.key, "ref", "") or ""))
    for tok in (str(getattr(st, "alias_ref", "") or ""), str(getattr(st.key, "ref", "") or "")):
        if tok and tok in note:
            note = note.replace(tok, label)
    return ascii_text(note)


def _level_words(st) -> str:
    """The level in ANALYST UNITS, pre-scaled at the producer (the K9-3 law; ``cascade._prescaled``
    :1871 is the shape). The design writes ``{level:+g}``; the SIGN is narrowed to the series that
    actually have one -- a two-sided reading (an anomaly graded against absolute bands) or a negative
    value. ``+117.4 MMT`` of ending stocks would be a sign the series does not carry."""
    unit = st.narrate_unit or st.unit or ""
    two_sided = bool(st.convention and st.convention.get("kind") == "abs_bands")
    try:
        v = float(st.level)
    except (TypeError, ValueError):
        return "no level was read"
    body = f"{v:+.2f}".rstrip("0").rstrip(".") if (two_sided or v < 0) else _fmt(v)
    return f"{body} {unit}".strip()


def _ok(measure) -> bool:
    return bool(measure) and not measure.get("declined") and measure.get("value") is not None


def sb_convention(n: int, row, *, distance, band, label: str, unit_words: str, direction: str,
                  asof: str, band_words: str = "", kind_words: str = "the level a convention names",
                  row_label: str = "", dates: str = "") -> tuple:
    """SB-V (sec 6.2, 5.1 kind 2): the WATCH row that carries a figure -- the distance to a declared
    desk line, minted as its OWN ``[N]`` through the ``_dv_call`` idiom (derived.py:73) so it is a
    computed figure with a handle rather than a subtraction the reader must trust.

    IT WEARS THE WATCH WORD (sec 6.2's SB-W shape, "- [N n] WATCH {kind words} {label}: {what} -- {ISO}")
    and keeps its own CLASS, which is the reading that satisfies both halves of sec 5.1: the magnitude is
    minted ONCE under one handle -- rendering a second, digit-free SB-W row beside it would give a
    verifier two rows to bind one copied figure to, which is K9-6 from the other direction -- and the
    reader meets one watch vocabulary. The class stays separate so ``state/lint.py``'s digit bar keeps
    holding every OTHER watch row to letters and ISO dates."""
    st = row.state
    q = {"table": (st.table if st is not None else "") or "desk convention",
         "metric": f"distance to the {label} line",
         "commodity": (st.key.commodity if st is not None else row.contract) or row.contract,
         "country": (st.key.country if st is not None else None) or None,
         "period": str((st.level_date if st is not None else "") or ""), "asof": asof}
    call = sb_call(value=round(float(distance), 4), unit=unit_words or "", **q)
    at = band_words or (f"{_fmt(band)} {unit_words}".strip())
    who = row_label or f"{humanise(row.driver_id)} on {board_label(row.contract)}"
    tail = f" -- {dates}" if dates else ""
    line = (f"- [N{n}] WATCH {kind_words} {who}: {_fmt(distance)} {unit_words} {direction} the "
            f"{label} line at {at}{tail}")
    return re.sub(r"\s+", " ", line), [call]


def sb_edge(row, *, far: Optional[dict] = None) -> str:
    """SB-E (sec 6.2): the declared edge in words -- NO handle, NO digit. This is the class that makes
    ruling 3 renderable: two boards, two lines, never reconciled."""
    if far is None:
        driver, board = humanise(row.driver_id), board_label(row.contract)
        sign, band, conf = row.sign, row.lag_band, row.confidence
        tail = ""
    else:
        driver, board = humanise(far["driver_id"]), board_label(far["contract"])
        sign, band, conf = far["sign"], far["lag_band"], far["confidence"]
        tail = (" -- the same reading this board carries, read on that graph's own edge"
                if far.get("free") else "")
    return (f"- {driver} is declared to move {board} {sign_words(sign)} with a lag the graph states "
            f"as {band_words(band)}, at {CONFIDENCE_WORDS.get(conf, 'medium')} confidence{tail}")


def sb_projection(*, board: str, anchor_words: str, window: dict, horizon_months=None,
                  horizon_sits: Optional[str] = None, asof: str = "") -> str:
    """SB-J (sec 6.2, B10): the projection, CONDITIONAL, as two calendar months counted from the row's
    OWN printed anchor date -- never from the as-of (Judge 2: a lag runs from the state to the effect).

    The horizon clause is BOARD ARITHMETIC (``walk.horizon_sits``), computed off the same two months the
    line prints, so a reader can check it against the line above it.

    **A WINDOW THAT CLOSED BEFORE THE AS-OF GETS THE DATE, NOT THE HORIZON CLAUSE.** The horizon runs
    forward from the as-of and the window is counted from the STATE's date, so on a row whose window has
    already closed the clause said "the horizon asked about, three months, sits past that window" --
    true arithmetic, and a sentence that invites the reader to place a future question inside a window
    that is over. What the reader needs there is the closing date, so the row says the window closed on
    that ISO day (an ISO date rides letters-only classes; ``verify._claim_number_spans`` rule (a)) and
    the horizon clause stands down. SB-D already draws this distinction on the EVENT row ("the window
    has been closed since ..."); the projection row now draws it too."""
    if window.get("declined") or not window.get("opens"):
        return (f"- conditional on the lag the graph states, counted from {anchor_words}, no effect "
                f"window on {board} can be placed: {absence_why(window.get('declined') or 'lag_unparsed')}")
    if window.get("open_ended"):
        body = (f"the effect window on {board} opens around {month_words(window['opens'])} and the "
                f"graph declares no close")
    else:
        body = (f"the effect window on {board} opens around {month_words(window['opens'])} and closes "
                f"around {month_words(window['closes'])}")
    closed = bool(window.get("closes") and asof and str(window["closes"]) < str(asof)[:10])
    tail = ""
    if closed:
        tail = f"; that window closed on {window['closes']}"
    elif horizon_months and horizon_sits:
        tail = (f"; the horizon asked about, {words_for_int(horizon_months)} months, sits "
                f"{horizon_sits} that window")
    return (f"- conditional on the lag the graph states, counted from {anchor_words}, {body}{tail}")


def sb_event(row, *, receipt_handle: int, published: str, board: str, window: dict,
             asof: str) -> str:
    """SB-D (sec 6.2, 3.7, B18): a dated EVENT, anchored at the EVENT date and never at a later
    analysis piece's publication date. ISO dates only."""
    if window.get("declined") or not window.get("opens"):
        state = "the graph declares no lag from it, so no window is placed"
    elif window.get("open_ended"):
        state = f"the window opened around {month_words(window['opens'])} and the graph declares no close"
    elif window.get("closes") >= str(asof)[:10]:
        state = f"the window is open until about {month_words(window['closes'])}"
    else:
        state = f"the window has been closed since about {month_words(window['closes'])}"
    return (f"- {humanise(row.driver_id)} dated {row.event_date} by [E{receipt_handle}] "
            f"(published {published}): the {board} graph records it {sign_words(row.sign)} with a lag "
            f"of {band_words(row.lag_band)}; {state}")


def sb_path(path: dict, *, anchor: str, handles=()) -> str:
    """SB-P (sec 6.2, 3.4, B8): an UPSTREAM path named by the node at its top, carrying THAT node's OWN
    declared band onto the anchor price -- never a sum along the hops (doctrine M-4)."""
    chain = " -> ".join(humanise(h) for h in path["hops"])
    hs = "".join(f"[N{h}]" for h in handles)
    tail = f"; the measured rows on it are {hs}" if hs else "; no row on it carries a measured state"
    lbl = board_label(anchor)
    hops_word = "hop" if int(path["depth"]) == 1 else "hops"
    return (f"UPSTREAM {chain} -> {lbl}: the graph places {humanise(path['hops'][0])} "
            f"{words_for_int(path['depth'])} {hops_word} upstream of the {lbl} price and declares its "
            f"own "
            f"lag onto that price as {band_words(path['lag_band'])}{tail}")


def sb_fan(entry: dict) -> str:
    """SB-F (sec 6.2, 3.6): the fan-out, COUNTS IN WORDS. The names are never cut -- only far STATES are
    priced -- so this line is the one that makes "the graph decides relevance" visible."""
    far = entry["far"]
    by_sign: dict = {}
    for f in far:
        by_sign.setdefault(f["sign"] or "", []).append(board_label(f["contract"]))
    if not by_sign:
        return ""
    head_sign = sorted(by_sign, key=lambda s: (-len(by_sign[s]), s))[0]
    head = sorted(by_sign[head_sign])
    rest = sorted(c for s, cs in by_sign.items() if s != head_sign for c in cs)
    body = (f"{sign_words(head_sign)} on {words_for_int(len(head))} ({', '.join(head)})")
    if rest:
        other_sign = sorted(s for s in by_sign if s != head_sign)[0]
        body += f" and {sign_words(other_sign)} on the rest ({', '.join(rest)})"
    n = len(far)
    return (f"- the same reading is declared on {words_for_int(n)} other "
            f"{'board' if n == 1 else 'boards'}: {body}")


def sb_convergence(row: dict) -> str:
    """SB-C (sec 6.2, 3.5, B16): PROXIMITY IN WORDS, counts in words, and never "met", "fires" or "the
    regime is". Firing stays with ``firing.fire_contract`` over declared bands; this row says how close
    a declared pattern sits on THIS board at THIS as-of, which is a different question.

    **THE NAMES ARE SPLIT BY WHETHER THE ROW WAS READ, and that is a MEASURED correction.** Sec 6.2's
    template promises "({names}, each with its own [N] z)" -- and the loud set admits rows with NO state
    by construction (a crossed band, an open event, doctrine M-3), so the first cut printed "four of its
    four declared drivers sit among this board's twenty-four loudest rows (China import tariff,
    section301 tariffs, export pace lag, China state reserves)" on scenario 1, where three of the four
    appear as BOARD ABSENCE rows lower in the same block. The COUNT was true and the promise was not: a
    writer told that four of four demand drivers are loud will narrate a measured demand collapse
    standing on nothing. Nothing is deleted -- the count stands, every name still reaches the reader --
    and the row now says which names carry a figure and which carry no series to read."""
    measured = [humanise(d) for d in (row.get("matched_measured") or row["matched"])]
    unread = [humanise(d) for d in (row.get("matched_unmeasured") or ())]
    named = (f"({', '.join(measured)}, "
             f"{'with its own [N] z' if len(measured) == 1 else 'each with its own [N] z'})"
             if measured else "(none of those rows carries a state read on this board)")
    unread_clause = ""
    if unread:
        unread_clause = (f"; {words_for_int(len(unread))} of them "
                         f"{'carries' if len(unread) == 1 else 'carry'} no series this board could "
                         f"read ({', '.join(unread)})")
    return (f"- {pattern_label(row['name'])} on {board_label(row['contract'])}: "
            f"{words_for_int(row['n_matched'])} of its "
            f"{words_for_int(row['n_declared'])} declared drivers "
            f"{'sits' if row['n_matched'] == 1 else 'sit'} among this board's "
            f"{words_for_int(row['loud_k'])} loudest rows {named}{unread_clause}; the pattern's own "
            f"threshold is {words_for_int(row['threshold'])}; "
            + ("none of them carries a declared desk band" if not row["n_with_band"] else
               f"{words_for_int(row['n_with_band'])} "
               f"{'carries' if row['n_with_band'] == 1 else 'carry'} a declared desk band"))


def sb_amplifier(contract: str, inter: dict) -> str:
    """The AMPLIFIER sub-line (sec 3.5, D24): the graph's only amplifier semantics, rendered as an
    ordering fact under its pattern's row. Digit-free, and indented so its class is its own."""
    ids = ", ".join(humanise(i) for i in inter["when"])
    note = f" -- {ascii_text(inter['note'])}" if inter.get("note") else ""
    # THE SUB-LINE SAYS WHICH OF ITS OWN IDS WERE READ, for the same reason SB-C does: an Interaction
    # whose `when` ids are all LOUD may still name a driver with no series at all (`biodiesel_mandate`
    # is an open EVENT row and enters the loud set by construction), and "all sit among this board's
    # loudest rows" invites a reader to hear a measured co-occurrence.
    unread = [humanise(i) for i in (inter.get("unmeasured") or ())]
    tail = (f"; {', '.join(unread)} {'carries' if len(unread) == 1 else 'carry'} no series this "
            f"board could read") if unread else ""
    return (f"  amplifier on {board_label(contract)}: {ids} all sit among this board's loudest rows; "
            f"the graph "
            f"records the effect as {inter['effect']}{tail}{note}")


def sb_tape(n: int, tape, *, asof: str) -> tuple:
    """SB-T (sec 6.2, D19, B19): the ANCHOR's own tape -- the dated front settle, the four SAME-CONTRACT
    session changes and the level's percentile over the window this read fetched. ONE handle per
    magnitude; the standings that name their populations and realised vol are RESERVED and the line
    says so in words."""
    calls: list = []
    q = {"table": "silver_futures_eod", "metric": "settle", "commodity": tape.slug, "country": None,
         "period": tape.contract_month, "asof": asof}
    h = n
    calls.append(sb_call(value=tape.level, unit=tape.unit, knowledge_date=tape.level_date, **q))
    parts = [f"- [N{h}] {board_label(tape.slug)} front {tape.contract_month} settle on "
             f"{tape.level_date}: "
             f"{_fmt(tape.level)} {tape.unit}".rstrip()]
    for ch in tape.changes:
        if ch.get("declined"):
            parts.append(f"over {words_for_int(ch['n_periods'])} "
                         f"{period_noun('daily', ch['n_periods'])} the same contract carries no change "
                         f"to print")
            continue
        h += 1
        calls.append(sb_call(value=round(float(ch["delta"]), 4), unit=tape.unit,
                             knowledge_date=ch.get("to_date"),
                             **{**q, "metric": f"settle change over {ch['window']}"}))
        parts.append(f"[N{h}] {_fmt(ch['delta'])} over {words_for_int(ch['n_periods'])} "
                     f"{period_noun('daily', ch['n_periods'])} on the same contract")
    if _ok(tape.percentile):
        h += 1
        pv = int(round(float(tape.percentile["value"])))
        calls.append(sb_call(value=pv, unit="percentile", knowledge_date=tape.level_date,
                             **{**q, "metric": "settle percentile"}))
        parts.append(f"[N{h}] the level at the {ordinal(pv)} percentile of the window this read "
                     f"fetched "
                     f"({tape.window_note})")
    parts.append("the standings that name their own populations and realised volatility are not "
                 "served yet and are not claimed here")
    return "; ".join(parts), calls


def attach_tape(bd, tape_by_slug: dict, *, reads_each: int = 1) -> None:
    """Put the anchor boards' SB-T rows on the board AND DECLARE THEIR SEAT ON THE LEDGER (D19).

    ``Ledger.tape_cap`` is a SEPARATE field from the two wave caps because the tape is not a wave: D19
    declares one mirror read per ANCHOR BOARD, outside both rectangles. ``board.py`` left it at zero and
    said in so many words that "the S3/S4 sitting that mints an SB-T read declares it here in the same
    edit" -- this is that edit. Without it ``net_reads()`` would count a tape read that ``reads_cap``
    had no room for, and the S6 ceiling of D12 would break by the anchor count, silently, in the
    direction that UNDER-counts.

    ``reads_each`` is 0 for a tape assembled from arrays already in hand (the offline harness) and 1 for
    a mirror read, so the ledger states what was actually spent rather than what the shape implies."""
    bd.tape.update(tape_by_slug or {})
    n = len(tape_by_slug or {})
    bd.ledger.tape_cap = max(int(bd.ledger.tape_cap), n)
    bd.ledger.tape_reads += n * max(0, int(reads_each))


def sb_analog_header(a: dict) -> str:
    """SB-A (sec 6.2, 4.2): the LIKE STATE header. Counts in words; the coverage floor PRINTED, so a
    loud set that cannot see 2003 says so; the vintage sentence on every stanza.

    **THE HEADER DECLARES NO BAND, AND THAT IS THE CORRECTION A MEASURED FALSE NOTE FORCED.** It used to
    print "the moves below are read over the declared lag band of {seed's band}" -- one band for a whole
    stanza whose rows are read over SEVERAL. MEASURED on scenario 1: "read over the declared lag band of
    one to two quarters" was immediately followed by the PALM benchmark's move, whose window
    (2024-08-31..2025-02-28) is palm's own TWO-TO-FOUR-quarter band, and every figure was handle-bound,
    so ``verify._check_number_handle`` value-checked the magnitude and nothing checked the band. A writer
    copying "over the declared one-to-two-quarter band the palm benchmark moved 161.56 to 181.52 USD/t"
    would have stated a falsehood that passed every K9 check. Sec 4.3's rule is that the OUTCOME ROW says
    whose band it used, and :func:`sb_analog_outcome` now does -- so the header states the RULE and each
    row states its own band.

    **THE CO-LOUD STANZA IS THE SAME CLASS AND A DIFFERENT SENTENCE** (sec 16 Amendment 1). A
    driver-as-subject board's like state is a CO-OCCURRENCE -- the dates when several of the boards
    carrying that driver sat in the top decile of their own history at once -- and printing "the series
    sat like this" over it would name a selector that did not run, which is the false note the paragraph
    above corrects rather than repeats. SB-A is a CLASS and not a template, so the co-loud header wears
    it: same opening token, same letters-plus-year discipline, no new entry in 6.2's vocabulary and no
    second regex for the disjointness lint to reconcile. ``analogs.co_loud_stanzas`` stamps the flag."""
    if a.get("co_loud"):
        n_boards = int(a.get("n_contracts") or 0)
        n_dates = int(a['n_candidates'])
        return (f"LIKE STATE {humanise(a['driver_id'])} across the boards that carry it: "
                f"{words_for_int(n_boards)} of them sat in the top decile of their own history at once "
                f"in {month_words(a['date'])}; the record carries {words_for_int(n_dates)} such "
                f"{'date' if n_dates == 1 else 'dates'} since {str(a['floor_year'])}; each move below "
                f"is read over the band the graph declares for the board it names, and the row prints "
                f"that band; measured on the record as revised through {month_words(a['asof'])}")
    n = int(a['n_candidates'])
    return (f"LIKE STATE {humanise(a['driver_id'])} on {board_label(a['contract'])}: the series sat "
            f"like this in "
            f"{month_words(a['date'])}; the record carries {words_for_int(n)} such "
            f"{'crossing' if n == 1 else 'crossings'} since {str(a['floor_year'])}; each move below is "
            f"read over the band the graph declares for the leg it names, and the row prints that "
            f"band; measured on the record as revised through {month_words(a['asof'])}")


def sb_analog_outcome(n: int, o: dict, *, asof: str) -> tuple:
    """SB-O (sec 6.2, 4.3): the outcome over the band, read at BOTH ENDS. Two handles per outcome, so
    "moved X at the near end and Y at the far end" is two bound figures rather than a range.

    **THE ROW CARRIES ITS OWN BAND** (sec 4.3: "the row says so ... a far board uses ITS edge's band for
    the same parent"). One like state yields SEVERAL horizons -- the bean window over one to two quarters
    and the palm window over two to four -- and until the band rode the row the stanza header spoke for
    all of them with the seed's. A band is not a magnitude, so it renders in WORDS and carries no handle;
    the two figures keep theirs.

    **AND THE FIGURE IS A CHANGE, SO IT TAKES A VERB.** "161.56 USD/t at the near end" reads as a LEVEL,
    and against a palm benchmark that sits around 760 USD/t that is exactly the misreading available. The
    design's own scenario prose says "moved {N} to {N} across the band"; ``window_change`` returns a
    change, and the row now says the word."""
    if o.get("declined"):
        return "", []
    q = {"table": o.get("table") or "", "metric": o.get("metric") or "", "commodity": o.get("commodity"),
         "country": o.get("country"), "period": f"{o['near_date']}..{o['far_date']}", "asof": asof}
    calls = [sb_call(value=round(float(o["near_value"]), 4), unit=o.get("unit") or "",
                     knowledge_date=o.get("near_date"), **q),
             sb_call(value=round(float(o["far_value"]), 4), unit=o.get("unit") or "",
                     knowledge_date=o.get("far_date"), **q)]
    line = (f"- [N{n}] {o['label']} over the band the graph declares from that state, "
            f"{band_words(o.get('band'))}: moved {_fmt(o['near_value'])} "
            f"{o.get('unit') or ''} by the near end; [N{n + 1}] moved {_fmt(o['far_value'])} "
            f"{o.get('unit') or ''} by the far end")
    return re.sub(r"\s+", " ", line).replace(" ;", ";"), calls


def sb_receipt(e_handle: int, t_tier: int, r: dict, *, driver_id: str) -> str:
    """SB-R (sec 6.2): the D-HP-1 menu row in ``_ev_block``'s own shape (answer.py:3380) so
    ``cit.unify`` numbers it and the persona's ``[T1]-[T4]`` trust contract is preserved."""
    src = ascii_text(r.get("source") or "the record")
    ev = r.get("event_date")
    ev_part = f"; event {ev}" if ev else ""
    return (f"- [E{e_handle}][T{t_tier}] ({src}, reported {r.get('date')}{ev_part}) "
            f"{{driver: {humanise(driver_id)}}} {ascii_text(r.get('text') or '')}".rstrip())


def sb_watch(w: dict) -> str:
    """SB-W (sec 6.2, 5.1): the UNHANDLED watch row -- letters and ISO dates and nothing else. Every row
    names a table, a level, a date or a document; nothing here produces "watch the weather".

    KIND 2 IS THE ONE WATCH ROW THAT CARRIES A FIGURE and it renders through :func:`sb_convention`
    instead, under its own class, so this builder can never take a handle: an unhandled magnitude on a
    watch row is exactly the digit ``verify._claim_number_spans`` charges."""
    dates = w.get("dates") or ""
    tail = f" -- {dates}" if dates else ""
    return f"- WATCH {w['kind_words']} {w['label']}: {w['what']}{tail}"


def sb_recency(layer: str, text: str) -> str:
    """SB-L (sec 6.2, 6.5): one line per LAYER, each a fact about the layer it names. None of them
    dates another, and no rendered line contains "not a current-state read" (B12)."""
    return f"RECENCY {layer}: {text}"


def sb_absence(label: str, reason: str) -> str:
    """SB-X (sec 6.2, 6.7): ``_cw_absence``'s shape (cascade.py:7528) with the reason as a SENTENCE from
    the closed map. An absence is a ROW; the reader is never shown a silence."""
    return f"BOARD ABSENCE {label}: {absence_why(reason)}."


# ---------------------------------------------------------------------------------------------------
# THE REPLACEMENT FENCE (sec 6.6) -- CORRECT, never delete
# ---------------------------------------------------------------------------------------------------
def register_hits(text: str) -> list:
    """All four register detectors over ONE line. Empty == clean. Imported lazily because
    ``register.py`` is a serving module and this package is imported by lint and by decks that never
    render a word."""
    try:
        from leviathan.graphrag import register as reg
    except Exception as exc:                            # noqa: BLE001 -- re-raised named, never swallowed
        # A SYNTHETIC HIT WOULD REPLACE EVERY LINE OF THE BLOCK with its SB-X absence and the board
        # would serve an empty page under a correction word, which is the loudest possible failure
        # disguised as the quietest. The detector is a BUILD dependency of this module: if it cannot be
        # imported the render is broken, and a broken render says so.
        raise RuntimeError("state/render.py cannot import leviathan.graphrag.register, so no line can "
                           "be register-checked: %s" % (exc,)) from exc
    hits: list = []
    if reg.count_flow_words(text):
        hits.append("count_flow_words")
    if reg.count_valuation_words(text):
        hits.append("count_valuation_words")
    if reg.register_leaks(text):
        hits.append("register_leaks")
    if reg._LANE_B_ADJ.search(text):
        hits.append("lane_b_adjective")
    return hits


class Block:
    """The rendered block, its calls, and every trip the fence corrected.

    LINES AND CALLS ARE COMMITTED TOGETHER. :meth:`add` builds a candidate line with its candidate
    calls, runs the fence, and either commits BOTH or replaces the line with its SB-X absence and
    commits NEITHER -- because a handle whose call was dropped is a citation pointing at nothing, which
    is a worse failure than the register trip it was trying to correct."""

    def __init__(self, *, start: int = 1, e_start: int = 1):
        self.lines: list = []
        self.calls: list = []
        self.trips: list = []
        self.classes: list = []
        self._next = int(start)
        self._next_e = int(e_start)

    def take_e(self) -> int:
        """The next ``[E]`` handle, MINTED ONCE FOR THE WHOLE BLOCK.

        The first cut restarted at ``[E1]`` inside every receipt loop and hardcoded ``[E1]`` on the
        event row, so a board carrying receipts on several rows minted the same handle three times
        before ``cit.unify`` renumbered them -- and until it did, the block a writer reads pointed three
        different documents at one label. One counter, one block."""
        e = self._next_e
        self._next_e += 1
        return e

    @property
    def next_e_handle(self) -> int:
        return self._next_e

    @property
    def next_handle(self) -> int:
        """The handle the NEXT minted magnitude takes. The board's own numbering starts at ``start`` and
        S6 appends the board's calls BEFORE the base wave so the cascade's own mints continue the count
        (sec 3.9 item 3)."""
        return self._next

    def add(self, line: str, calls=(), *, label: str = "", allow_empty: bool = False):
        """Commit ONE row. Returns the line actually committed (possibly the SB-X correction)."""
        if not line and not allow_empty:
            return ""
        hits = register_hits(line)
        if hits:
            self.trips.append({"label": label or line[:40], "hits": tuple(hits), "line": line})
            line = sb_absence(label or "a composed line", "template_register_trip")
            calls = ()
        self.lines.append(line)
        self.classes.append(classify(line))
        for c in calls:
            self.calls.append(c)
            self._next += 1
        return line

    def text(self) -> str:
        return "\n".join(self.lines)


# ---------------------------------------------------------------------------------------------------
# THE BLOCK (sec 6.1) -- one declared section order and one render cap per section
# ---------------------------------------------------------------------------------------------------
#: The order the sections render in. It is a CONSTANT rather than a call order so that two boards with
#: the same rows render the same block, and so the acceptance fixtures of sec 0.3 can be read against it
#: line by line.
BLOCK_ORDER: tuple = ("header", "states", "events", "paths", "fan", "convergence", "tape", "analogs",
                      "receipts", "watch", "recency", "absences")

#: THE RENDER CAPS, per base mode, and they are sec 7's OWN line counts read as caps rather than as
#: predictions. Sec 7 sizes Cascade at "~24 SB-1 + 16 + 6 + 2 stanzas (~12) + 8 SB-W + SB-P paths ~=
#: 66-80 lines"; the first cut of this module had NO cap below the state rows and MEASURED 337 lines on
#: the scenario-1 harness -- 95 SB-E, 70 SB-O and 94 SB-X -- four times the design's own upper bound and
#: about fourteen thousand estimated tokens of volatile, uncached input on every Cascade turn.
#:
#: EVERY CAP NAMES WHAT IT CUT. A capped section ends with one SB-X carrying the closed word for that
#: cut (``fan_cap`` / ``render_cap``), which is the same law the walk's own caps keep: a cut that reads
#: as a zero is indistinguishable from a row nobody asked for.
RENDER_CAPS: dict = {
    "quick": {"spillover": 4, "convergence": 2, "analog": 0, "analog_outcomes": 0, "receipts": 0},
    "deep": {"spillover": 8, "convergence": 4, "analog": 1, "analog_outcomes": 4, "receipts": 3},
    "max": {"spillover": 16, "convergence": 6, "analog": 2, "analog_outcomes": 4, "receipts": 5},
}


def render_caps(mode: str) -> dict:
    from leviathan.graphrag import reasoning_modes as rm
    return dict(RENDER_CAPS.get(rm.base_mode(mode), RENDER_CAPS["deep"]))


def render_board(bd, *, analogs=(), watch=(), receipts_by_row=None, recency=None, start: int = 1,
                 anchor_label: str = "", loud_only: bool = True, age_clauses=None,
                 caps: Optional[dict] = None) -> Block:
    """THE WHOLE BLOCK. Deterministic, ASCII, every figure bound to its own call, every cut NAMED.

    ``loud_only`` renders the STATE rows of the loud set (the ``loud_k`` knob is the cut) while every
    OTHER row still reaches the reader: an unmeasured or unread row joins a GROUPED SB-X absence at the
    foot, which is the design's "an unmeasured driver is a ROW that says so", not a filter.

    THE ABSENCES ARE GROUPED BY REASON WORD and every name is listed inside the group. One line per
    unmeasured row was the first cut and it MEASURED 94 SB-X lines on a 47-row board -- more absence
    than board. Sec 0.3's own scenario-1 SB-X list is five lines, and grouping is how thirty-five named
    rows fit in five: the NAMES are never cut (the fan's law, applied here), only the sentences are
    shared."""
    b = Block(start=start)
    cap = dict(caps or render_caps(bd.mode))
    ages = dict(age_clauses or {})
    b.add(sb_header(bd, anchor_label=anchor_label), label="header")

    order = {k: i for i, k in enumerate(bd.order)}
    loud = sorted((r for r in bd.rows if r.legs.get("loud")),
                  key=lambda r: order.get(r.key, len(order)))
    rendered = loud if loud_only else sorted(bd.rows, key=lambda r: order.get(r.key, len(order)))

    from leviathan.graphrag.state.walk import horizon_sits, projection_window

    # -- STATES, each with its edge and its projection ------------------------------------------------
    handles_by_row: dict = {}
    for row in rendered:
        st = row.state
        if st is None or status_word(st.status) != "ok":
            continue
        h = b.next_handle
        line, calls = sb_state(h, row, asof=bd.asof, age_clause=ages.get(row.key, ""))
        if line:
            b.add(line, calls, label=f"{row.contract}/{row.driver_id}")
            handles_by_row[row.key] = h
        b.add(sb_edge(row), label=f"edge {row.driver_id}")
        win = bd.windows.get(row.key) or {}
        anchor_date = win.get("near") or st.level_date
        # D18's fourth clause: a `context_only` row is NEVER A PROJECTION ANCHOR. Its STATE row renders
        # (it is read and it is context), and it carries the past-tense clause that says what it is;
        # projecting a window forward from it would be the R9 guard's measured failure written by the
        # board instead of by the writer.
        if anchor_date and not row.context_only:
            w = projection_window(anchor_date, row.lag_band)
            b.add(sb_projection(board=board_label(row.contract),
                                anchor_words=_anchor_words(st, anchor_date), window=w,
                                horizon_months=bd.horizon_months,
                                # THE AS-OF, not the state date: "three months from now" is counted
                                # from now, while the window is counted from the state (see
                                # `walk.horizon_sits`). It rides twice: once as the horizon's own
                                # counted-from date, and once so the row can tell a window that has
                                # already CLOSED from one the horizon can still sit inside.
                                horizon_sits=horizon_sits(bd.horizon_months, w, bd.asof),
                                asof=bd.asof),
                  label=f"projection {row.driver_id}")

    # -- EVENTS ---------------------------------------------------------------------------------------
    for row in rendered:
        if not row.event_date:
            continue
        # THE PUBLISHED DATE AND THE [E] HANDLE BELONG TO THE RECEIPT THAT DATED THE EVENT, and the
        # first cut took `receipts['top'][0]` -- the caller's first receipt in INSERTION order -- with a
        # hardcoded `[E1]`. On the harness that printed "published 2026-05-02" only because the fixture
        # happens to list the event document first; on the real path receipts arrive ranked by recency
        # and specificity (sec 2.2), which puts the 2026-08-20 levy document first and would have
        # rendered "biodiesel mandate dated 2026-05-01 by [E1] (published 2026-08-20)" -- a false
        # attribution under a handle pointing at the wrong document. `walk.event_receipt_for` carries
        # the WINNER out of the same rule that chose the date, and the receipt renders under that handle
        # so the citation resolves to the document the row names.
        rc = dict(row.event_receipt or ((row.receipts or {}).get("top") or [{}])[0] or {})
        e = b.take_e()
        b.add(sb_event(row, receipt_handle=e, published=rc.get("date") or row.event_date,
                       board=board_label(row.contract),
                       window=projection_window(row.event_date, row.lag_band), asof=bd.asof),
              label=f"event {row.driver_id}")
        if rc.get("date"):
            b.add(sb_receipt(e, int(rc.get("tier") or 3), rc, driver_id=row.driver_id),
                  label=f"event receipt {row.driver_id}")

    # -- PATHS (capped by the walk's own `path_render_k`, which stamped `rendered` per path) ----------
    for p in bd.paths:
        if not p.get("rendered"):
            continue
        hs = [handles_by_row[(p["contract"], h)] for h in p["hops"]
              if (p["contract"], h) in handles_by_row]
        b.add(sb_path(p, anchor=p["contract"], handles=hs), label=f"path {p['ancestor']}")

    # -- FAN and its far edges, ONE combined section under sec 7's spillover count --------------------
    # THE ENTRIES ARE WALKED IN RANK ORDER AND EACH GETS ITS OWN SHARE. The first cut walked
    # ``bd.fan`` in ROW APPEND order and let one entry spend the whole cap: on the scenario-1 harness
    # ``La_Nina`` (the DAG's first driver) took all sixteen spillover lines and ``El_Nino`` -- the
    # anchor's loudest shared driver and the whole point of scenario 2 -- rendered no far edge at all.
    #
    # AND THE SPLIT RENDERS FIRST inside an entry: a far board whose declared SIGN differs from this
    # board's, then one whose BAND differs, then the graph's own far order. Rendering the split IS the
    # value (sec 3.6), and it is an ORDERING, never an exclusion -- the SB-F line above names every far
    # board either way, loud or quiet, read or not.
    spill, cut_boards = 0, []
    fan_entries = sorted((e for e in bd.fan if e.get("loud") or not loud_only),
                         key=lambda e: order.get((e["contract"], e["driver_id"]), len(order)))
    far_per_entry = max(1, int(cap["spillover"]) // max(1, min(len(fan_entries), 8)))
    for e in fan_entries:
        seed = bd.row(e["contract"], e["driver_id"])
        far_named = [f for f in e["far"] if f.get("state_read") or f.get("free")]
        far_named.sort(key=lambda f: (0 if (seed is not None and f["sign"] != seed.sign) else 1,
                                      0 if (seed is not None and seed.lag_band is not None
                                            and f["lag_band"].raw != seed.lag_band.raw) else 1,
                                      f["contract"]))
        if spill >= int(cap["spillover"]):
            cut_boards.extend(f["contract"] for f in far_named)
            continue
        b.add(sb_fan(e), label=f"fan {e['driver_id']}")
        spill += 1
        for f in far_named[:far_per_entry]:
            if spill >= int(cap["spillover"]):
                cut_boards.append(f["contract"])
                continue
            b.add(sb_edge(seed, far=f), label=f"far {f['contract']}/{f['driver_id']}")
            spill += 1
        cut_boards.extend(f["contract"] for f in far_named[far_per_entry:])
    if cut_boards:
        b.add(sb_absence("the far boards past this tier's spillover cut ("
                         + ", ".join(sorted({board_label(c) for c in cut_boards})) + ")", "fan_cap"),
              label="fan render cap")

    # -- CONVERGENCE ----------------------------------------------------------------------------------
    # THE CAP COUNTS PATTERNS, AND A RENDERED PATTERN KEEPS ITS AMPLIFIER SUB-LINES. Counting both
    # against one budget was the first cut, and it MEASURED wrong on scenario 3: three amplifiers under
    # the earlier patterns exhausted the cap and `biodiesel_energy_floor`'s own
    # `(crude_oil_price, biodiesel_mandate) amplifies` line -- the scenario's whole convexity material,
    # and bar B16's fixture -- was the row that fell off. An amplifier is a SUB-LINE of a row already
    # admitted, digit-free, and bounded by the pattern count it hangs under.
    conv = 0
    for c in bd.convergence:
        if conv >= int(cap["convergence"]):
            break
        b.add(sb_convergence(c), label=f"pattern {c['name']}")
        conv += 1
        for it in c["interactions"]:
            if it.get("rendered"):
                b.add(sb_amplifier(c["contract"], it), label=f"amplifier {c['name']}")

    # -- TAPE -----------------------------------------------------------------------------------------
    for slug in bd.anchor_slugs:
        tp = bd.tape.get(slug)
        if tp is None:
            continue
        if status_word(tp.status) != "ok":
            b.add(sb_absence(f"{board_label(slug)} price path", tp.status), label=f"tape {slug}")
            continue
        line, calls = sb_tape(b.next_handle, tp, asof=bd.asof)
        b.add(line, calls, label=f"tape {slug}")

    # -- ANALOGS: the most LIKE stanzas first, capped at sec 7's own stanza count ---------------------
    fired = [a for a in analogs if not a.get("declined")]
    # THE SEED'S OWN RANK ORDERS THE STANZAS, distance breaks the tie. Ordering by DISTANCE alone was
    # the first cut and it MEASURED wrong: a daily crush-margin series has a near-identical crossing
    # three months back, so its distance beat every monthly driver and the two rendered stanzas on the
    # scenario-1 board were both crush margin -- the loudest driver on the page, El Nino, had no stanza
    # at all. Loudness orders everything else on this board; it orders this too.
    fired.sort(key=lambda a: (int(a.get("seat", 1 << 20)),
                              round(float(a.get("distance") or 0.0), 9), a["driver_id"]))
    shown_analogs = fired[: int(cap["analog"])]
    for a in shown_analogs:
        b.add(sb_analog_header(a), label=f"analog {a['driver_id']}")
        outs = [o for o in (a.get("outcomes") or ()) if not o.get("declined")]
        # THE ANCHOR BOARD'S OWN CONSEQUENCE LEADS. Sorting on the label alone put "the palm monthly
        # benchmark" above "the soybean monthly benchmark" -- alphabetically -- so the most prominent
        # analog figure on a soybean board was a palm move. The band now rides every row, so this is an
        # ordering rather than a correction; it is still the ordering the reader expects.
        outs.sort(key=lambda o: (0 if str(o.get("commodity") or "") == a["contract"] else 1,
                                 0 if "benchmark" in str(o.get("label") or "") else 1,
                                 str(o.get("label") or "")))
        shown_outs = outs[: int(cap["analog_outcomes"])]
        for o in shown_outs:
            line, calls = sb_analog_outcome(b.next_handle, o, asof=bd.asof)
            b.add(line, calls, label="analog outcome")
        # EVERY CUT NAMES WHAT IT CUT, and this one did not. MEASURED at the S3 re-fix on the b40_event
        # board: `analog_outcomes` is FOUR on Cascade and the stanza carried more, so outcomes over
        # declared bands were dropped with no absence row, no name list and no sentence -- the reader
        # met a stanza that looked complete and the writer met a consequence set that silently was not.
        # The four swept cuts (fan, paths, budget, stanzas) all say what they dropped and why; this one
        # now takes the same shape rather than being the fifth exception. A DROPPED outcome is not a
        # DECLINED one and keeps its own sentence: the group below says the band could not be read, and
        # this line says the band was read and the tier had no room to print it.
        if len(outs) > len(shown_outs):
            dropped = sorted({str(o.get("label") or "an outcome over that band")
                              for o in outs[len(shown_outs):]})
            b.add(sb_absence("the outcomes of this like state past this tier's outcome cut ("
                             + ", ".join(dropped) + ")", "render_cap"),
                  label="analog outcome render cap")
        held = [o for o in (a.get("outcomes") or ()) if o.get("declined")]
        for word in sorted({str(o["declined"]) for o in held}):
            b.add(sb_absence("an outcome over that band", word), label="analog outcome absence")
        for rc in (a.get("receipts") or ())[: int(cap["receipts"])]:
            b.add(sb_receipt(b.take_e(), rc.get("t", 3), rc, driver_id=a["driver_id"]),
                  label="analog receipt")
        if not (a.get("receipts") or ()):
            # THE CO-LOUD STANZA SPANS BOARDS, so its absence may not name ONE of them: the ordinary
            # line's "on {board}" would attribute the whole stanza to its leading anchor, and the rows
            # above it are several boards' own records.
            where = ("across the boards that carry it" if a.get("co_loud")
                     else f"on {board_label(a['contract'])}")
            stands = ("the boards' own records alone" if a.get("co_loud") else "the series alone")
            b.add(f"LIKE STATE {humanise(a['driver_id'])} {where}: the corpus "
                  f"holds no dated document for this window; the figures above stand on {stands}",
                  label="analog receipt absence")
    if len(fired) > len(shown_analogs):
        b.add(sb_absence("the like states past this tier's stanza cut ("
                         + ", ".join(_named_rows(
                             (a["contract"], a["driver_id"]) for a in fired[len(shown_analogs):]))
                         + ")", "render_cap"),
              label="analog render cap")
    for word in sorted({str(a["declined"]) for a in analogs if a.get("declined")}):
        b.add(sb_absence("a like state on this board", word), label="analog absence")

    # -- RECEIPTS on the loud rows ---------------------------------------------------------------------
    for key, rs in sorted((receipts_by_row or {}).items()):
        for r in rs[: int(cap["receipts"])]:
            b.add(sb_receipt(b.take_e(), r.get("tier", 3), r, driver_id=key[1]), label="receipt")

    # -- WATCH -----------------------------------------------------------------------------------------
    #    EVERY KIND WEARS THE WATCH WORD; kind 2 alone carries a handle and a figure, under its own
    #    class (SB-V). That is sec 5.1's parenthesis read with sec 6.2's SB-W row in front of it -- "on
    #    kind 2 only, ONE minted distance figure under its own handle" -- and the alternative, an SB-V
    #    row beside a digit-free SB-W row for the same kind, would mint the SAME magnitude under two
    #    handles, which is the K9-6 defect from the other direction: a verifier value-checking a
    #    writer's copy would find two rows to bind it to. The first cut kept the handle and DROPPED the
    #    WATCH word, which cost the writer the row: the mandate's fourth movement tells it to close with
    #    the WATCH rows, and a bare distance line is not one of them.
    for w in watch:
        if w.get("call") is not None and w.get("row_obj") is not None:
            line, calls = sb_convention(b.next_handle, w["row_obj"], distance=w["distance"],
                                        band=w["band"], label=w["conv_label"],
                                        unit_words=w["unit_words"], direction=w["direction"],
                                        asof=bd.asof, band_words=w.get("band_words") or "",
                                        kind_words=w["kind_words"], row_label=w["label"],
                                        dates=w.get("dates") or "")
            b.add(line, calls, label=f"watch {w['kind']}")
            continue
        b.add(sb_watch(w), label=f"watch {w['kind']}")

    # -- RECENCY ---------------------------------------------------------------------------------------
    for layer, text in (recency or {}).items():
        b.add(sb_recency(layer, text), label=f"recency {layer}")

    # -- ABSENCES, GROUPED BY REASON WORD, every name listed --------------------------------------------
    groups: dict = {}
    for row in bd.rows:
        st = row.state
        if st is not None and status_word(st.status) == "ok":
            continue
        reason = (status_word(st.status) if st is not None
                  else {"declared_available_unserved": "unmapped_ref",
                        "planned_text_only": "series_planned"}.get(row.coverage_tier, "series_none"))
        groups.setdefault(reason, []).append(f"{humanise(row.driver_id)} on "
                                             f"{board_label(row.contract)}")
    for reason in sorted(groups):
        b.add(sb_absence(", ".join(sorted(groups[reason])), reason), label=f"absence {reason}")
    # EVERY CUT NAMES WHAT IT CUT, and until this edit four of them said "named above" while naming
    # the rows NOWHERE -- against sec 3.8's own law ("the tail it cannot afford is NAMED") and B3's
    # "NAMED deferrals equal in count to declared - read". The fan render cap always did it right; these
    # follow it, and the closed sentences behind them now say "named here" because that is where the
    # names are.
    for note in bd.notes:
        if note.get("kind") == "budget_cap":
            named = _named_rows(note.get("pairs") or ())
            b.add(sb_absence("the keys this turn's budget did not reach"
                             + (" (" + ", ".join(named) + ")" if named else ""), "budget_cap"),
                  label="budget cap")
        elif note.get("kind") == "path_render_cap":
            named = sorted({humanise(x) for x in (note.get("names") or ())})
            b.add(sb_absence("the upstream paths past this tier's render cut"
                             + (" (" + ", ".join(named) + ")" if named else ""), "render_cap"),
                  label="path render cap")
        elif note.get("kind") == "fan_states_unread":
            named = _named_rows(note.get("names") or ())
            b.add(sb_absence("the far states of the rows past this tier's cut"
                             + (" (" + ", ".join(named) + ")" if named else ""), "fan_cap"),
                  label="fan states unread")
        elif note.get("kind") == "edge_hop_cap":
            b.add(sb_absence("the link direction this tier does not walk", "edge_hop_cap"),
                  label="edge hop cap")
    return b


def _named_rows(pairs) -> list:
    """``(contract, driver_id)`` pairs as sorted reader words. ONE producer for every cut line's name
    list, so a named tail can never reach a reader as a raw id (``register.internal_leaks``, :836)."""
    out = set()
    for p in pairs or ():
        try:
            c, d = p
        except (TypeError, ValueError):
            continue
        out.add(f"{humanise(d)} on {board_label(c)}")
    return sorted(out)



def _anchor_words(st, anchor_date: str) -> str:
    """WHAT THE PROJECTION IS COUNTED FROM, in words -- and the row prints WHICH anchor it used (sec
    3.7). A run's start and a level's date are two different claims about the same series."""
    since = (st.run or {}).get("since_date") if (st.run and not st.run.get("declined")) else None
    if since and str(since)[:10] == str(anchor_date)[:10]:
        return f"the run's start in {month_words(anchor_date)}"
    return f"this reading's own date in {month_words(anchor_date)}"
