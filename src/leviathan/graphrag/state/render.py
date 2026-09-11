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
from functools import lru_cache
from typing import Optional

from leviathan.graphrag.state.lagbands import LagBand
from leviathan.graphrag.state.rows import SIGN_WORDS, shown_value, status_word

# ---------------------------------------------------------------------------------------------------
# THE MARKER (sec 6.1) -- minted ONCE here and imported by the seam gate at S6
# ---------------------------------------------------------------------------------------------------
#: The block's own marker PREFIX. The S6 gate tests the PREFIX exactly as ``CW_MARKER_PREFIX in vp``
#: does (cascade.py:7768; answer.py's `_cascade_walk_block_on` shape), never a marker carrying the
#: as-of -- a marker that carried the date would make the gate a date comparison and would stop
#: matching the moment the block's header changed a character after it.
SB_MARKER_PREFIX = "STATE OF THE WORLD at "

#: THE SPILLOVER HOME (S7 item 2). The persona licenses a dedicated ``## Cross-commodity`` heading on
#: any block line beginning with this word (answer.py:550-577, the RV-v2 D5 reserved heading), and
#: ``narration.MANDATE_MOVEMENTS`` sends the SPILLOVERS movement there -- with ``## Mechanism`` as the
#: FALLBACK. MEASURED, the fallback was the only branch that ever fired: no board minted this line, and
#: ``## Mechanism`` carried 1 of 239 first-cited handles across the twelve banked turns, so the movement
#: aimed at the one section the writer keeps number-free. The prod-seat smoke read the consequence
#: directly -- SPILLOVERS dropped entirely on ``soybeans_now``, parked past ``## What to watch`` on
#: ``el_nino_fanout``, and landed correctly only on ``b40_event``, where the anchor board IS the
#: spillover subject.
#:
#: SO THE BOARD MINTS THE LICENCE, AND ONLY WHEN IT HAS ROWS TO PUT UNDER IT: one line, minted iff at
#: least one FAR row across a cross edge actually RENDERED (a fan far row carrying its own sign word and
#: its own board). A licence with no rows behind it is the +10-hallucination class the walk's own marker
#: gate exists to refuse, so "no far row rendered" mints nothing and the fallback stands unchanged.
#:
#: IT IS ONE CONSTANT, HERE, beside the block's other marker -- the CW_MARKER_PREFIX law. config_check's
#: clause (iv) compares ``SB_MARKER_PREFIX`` against the five reserved persona marker words and its own
#: note says the board "mints none of them today"; that note is now false BY DESIGN and the clause it
#: needs is written out in ``tests/unit/test_board_coverage.py`` (see OWED_CONFIG_CHECK_CLAUSE) because
#: ``config_check.py`` is another lane's file this sitting.
SB_CROSS_COMMODITY_PREFIX = "CROSS-COMMODITY"


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
    "recency_facts_off": "the per-layer recency grammar this board's rows are written for is not "
                         "switched on for this turn",
    # SUBJECT RESOLVER D5. THE ONLY ENTRY IN THIS MAP WHOSE WORD OWES A SECOND SENTENCE, and the
    # sentence below is deliberately the HALF that does not name the drivers: `absence_why` drops
    # every detail (each existing one is a count, and a count in a letters-only class is a digit), so a
    # caller that reached this map by the ordinary route still gets a true, complete sentence.
    # `sb_subject_ambiguous` is the row that adds the names.
    "subject_ambiguous": "the question could be about either of two drivers this estate tracks, and "
                         "it does not say which",
}

#: The fallback. It is deliberately a SENTENCE and not the raw word: a reader must never be shown a
#: code token, and ``state/lint.py`` fails when a closed word has no entry above, so this string is
#: what a lint failure looks like at serve time rather than what a normal turn prints.
ABSENCE_FALLBACK = "the record does not carry a measurable read here"


def absence_why(reason: str) -> str:
    """The plain sentence for a possibly-parametrised closed word (``thin_history:3`` -> its sentence).
    The DETAIL is deliberately dropped: it is a count, and a count in a letters-only class is a digit."""
    return ABSENCE_WHY.get(status_word(reason or ""), ABSENCE_FALLBACK)


def _reason_rank(reason: str) -> tuple:
    """A closed reason word's DECLARED position, for the one place a reason list is CUT (S7).

    IT IS THE VOCABULARY'S OWN ORDER AND NOT A SECOND TABLE. ``state/board.LEG_REASONS`` declares each
    leg's enum in the order the design states it, and the legs themselves are declared in that dict in
    order (series, edge, fan, path, interaction, tape, analog, watch, render, board) -- so the
    concatenation IS the ranking, and a word that moves in the design moves here without an edit. A
    word outside every enum ranks last and then alphabetically, so an unknown still renders and still
    renders deterministically.

    WHY IT IS NEEDED AT ALL: the absence groups used to render ``sorted(groups)``, which is harmless
    while every group prints and is a CONTENT decision the moment ``render_absence`` cuts one --
    alphabetically that puts ``budget_cap`` and ``history_truncated`` ahead of ``scope_unresolved``,
    ``unmapped_ref``, ``series_planned`` and ``series_none``, i.e. the incidental reasons ahead of the
    four that say the estate carries no series for the row at all."""
    order = _reason_order()
    word = status_word(reason or "")
    return (order.get(word, len(order)), word)


_REASON_ORDER: dict = {}


def _reason_order() -> dict:
    """``{reason word: declared position}``, built once from ``state/board.LEG_REASONS``.

    THE IMPORT IS LAZY because ``board.py`` is the module that owns the knobs this file's caps come
    from and the two must stay free to import in either order (``board`` imports ``rows`` and
    ``lagbands`` and nothing else at module level today; keeping this lazy means a future edit there
    cannot make a cycle out of a lint constant). A missing or broken enum leaves the map EMPTY, which
    falls back to the alphabetical order this function replaced -- a board must never fail to render
    because a ranking table would not load."""
    global _REASON_ORDER
    if _REASON_ORDER:
        return _REASON_ORDER
    try:
        from leviathan.graphrag.state.board import LEG_REASONS
        seen: dict = {}
        for _leg, words in LEG_REASONS.items():
            for w in words:
                seen.setdefault(str(w), len(seen))
        _REASON_ORDER = seen
    except Exception:                   # noqa: BLE001 -- a ranking table is telemetry, never a fence
        _REASON_ORDER = {}
    return _REASON_ORDER


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


def _market_words(slug: str) -> tuple:
    """The ALTERNATIVE spellings a reader may use for one board, as the coverage instrument's token
    group for a far row (S7 item 1): the full reader label and, when it opens with an exchange code,
    the label without it.

    IT IS DELIBERATELY CHARITABLE AND THE CHARITY IS BOUNDED. ``board_label`` is ``'{EXCH} {node}'``
    and the smoke seat's writer wrote both spellings ("on CME palm oil the El Nino phase is declared"
    and "palm"), so requiring the exchange code would score a market the answer plainly named as a
    MISS. The bound is that only the leading ALL-CAPS token is optional: nothing here matches a
    commodity word the far board does not carry, and the two-token minimum stops "ICE cocoa" collapsing
    to a word short enough to hit by accident."""
    lbl = board_label(slug)
    out = [lbl]
    parts = lbl.split(" ")
    if len(parts) > 2 and parts[0].isupper():
        out.append(" ".join(parts[1:]))
    return tuple(out)


def table_words(table: str) -> str:
    """A card as its SOURCE label (``silver_noaa_oni`` -> ``NOAA ONI``). An unmapped table strips
    ``silver_`` and upper-cases, so this function cannot return a raw slug -- which is why the reader
    half of an SB-1 line names the SOURCE while the call record keeps the machine ``metric``
    (``_cw_call``'s own review D9: a display label in the query poisons the citations locator)."""
    from leviathan.graphrag import display as _display
    return ascii_text(_display.table_label(str(table or "")))


#: ── S8 DOCKET, POLISH (c): A STATE ROW NAMES ITS SOURCE AND NEVER ITS METRIC ─────────────────────
#: MEASURED AND WITHDRAWN AT S7 ROUND 2. The defect is real and is verbatim from the banked S4 blocks:
#: ``soybeans_cbot__quick`` printed ``Brazil export tax on CBOT soybeans, USDA PSD for 2026: ...`` --
#: the DAG node is ``Brazil_export_tax`` (``type: policy_event``, ``silver_ref: export`` ->
#: ``silver_psd.exports_mt``), so the row reads an export VOLUME under a name that says TAX; and
#: ``palm_olein_dce__quick`` printed ``China import pace`` and ``China import tariff`` on one PSD import
#: metric with the same figure and no word saying they were one reading.
#: THE S7 CUT (a ``source_words`` clause folding ``display.metric_label`` into the SB-1 head) WAS
#: REVERTED TO HEAD'S BYTES, on its own measurement: it never fired on the two policy rows it was
#: written for (their metric words fold away against the driver label), and it made 28 of 43 real rows
#: WORSE by appending a storage-column word to a line that already read correctly. The mechanism that
#: would work is a METRIC CARD on the ``cascade_map`` row -- reader words declared beside the ref, not
#: derived from a column name -- and that is a config change, so it is S8's and not this sitting's.
def pattern_label(name: str) -> str:
    """A convergence pattern id as reader words (``display.regime_label``), which also appends the
    declared direction in words. A raw regime id in prose is an ``internal_leaks`` hit by construction."""
    from leviathan.graphrag import display as _display
    return ascii_text(_display.regime_label(str(name or "")))


def row_words(contract: str = "", driver_id: str = "") -> str:
    """A ROW named in READER WORDS -- ``{driver} on {board}`` through the two display producers above.

    It exists so a CORRECTION row can name the row it replaced without the caller reaching for the
    internal label, which is what shipped raw regime ids into the writer prompt (see ``Block.add``).
    One composer, so a new call site cannot invent a second spelling of "which row this was"."""
    d = humanise(driver_id) if driver_id else ""
    c = board_label(contract) if contract else ""
    return f"{d} on {c}" if (d and c) else (d or c)


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
    # SB-F CARRIES TWO SHAPES AND STAYS ONE CLASS (S7 item 2). The fan index line and the
    # CROSS-COMMODITY licence line are the same object to every consumer that matters -- both are the
    # spillover section, both are letters-plus-word-counts, neither mints a handle -- so the licence
    # rides this class's regex as a second alternation rather than becoming a nineteenth key. THAT IS A
    # DECISION ABOUT A FILE THIS SITTING DOES NOT OWN: `state/lint.py`'s clause 10 keys its sample map
    # on `set(ROW_CLASSES)` and reds a class with no sample, and lint.py is outside this sitting's
    # allowlist -- so a new key would have shipped a red `config_check`. The alternation keeps the
    # existing SB-F sample classifying as exactly ("SB-F",) and adds no unsampled key.
    "SB-F": re.compile(r"^(?:- the same reading is declared on |"
                       + SB_CROSS_COMMODITY_PREFIX + r"[ :])"),
    "SB-C": re.compile(r"^- .+ on .+: .+ of its .+ declared drivers sits? among "),
    "SB-M": re.compile(r"^  amplifier on "),
    "SB-P": re.compile(r"^UPSTREAM "),
    "SB-A": re.compile(r"^LIKE STATE "),
    "SB-L": re.compile(r"^RECENCY "),
    "SB-X": re.compile(r"^BOARD ABSENCE "),
    # SB-JOIN IS BEYOND SEC 6.2's TABLE AND THE DIVERGENCE IS DECLARED (S6 review, major 17). Sec 6.2
    # names sixteen classes and none of them can say "these two rows are one reading": every class
    # there describes a row's own content, and this one describes a RELATION BETWEEN rows. It is
    # letters-only (no member of FIGURE_CLASSES, no member of DATE_ONLY_CLASSES), it mints no handle
    # and it asserts no magnitude, so it adds nothing to the [N] address space and nothing the verifier
    # must bind. The alternative -- dropping one member of a phase pair -- is a fence that DELETES,
    # which doctrine forbids: fences correct or compute.
    "SB-JOIN": re.compile(r"^BOARD JOIN "),
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
        # THE CALL AND THE PRINTED WORDS TAKE THE SAME MAGNITUDE, and that is not a nicety: they are the
        # two halves of ONE handle. `verify._check_number_handle` value-checks a writer's copy of the
        # printed figure against this call's `shown` pool, so a line that printed the scaled value over
        # a call carrying the native one would strip every figure the writer correctly transcribed.
        # Figures AND words together (S7 polish (b)).
        lvl = _level_words(st)
        calls.append(sb_call(value=st.level_shown, unit=unit, knowledge_date=st.knowledge_date,
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
    """The level in ANALYST UNITS. The design writes ``{level:+g}``; the SIGN is narrowed to the series
    that actually have one -- a two-sided reading (an anomaly graded against absolute bands) or a
    negative value. ``+117.4 MMT`` of ending stocks would be a sign the series does not carry.

    **THE SCALE IS APPLIED HERE, AND THE DOCSTRING USED TO CLAIM IT WAS APPLIED AT THE PRODUCER.** It
    was not: ``feeders`` reads ``row2['scale']`` onto the row (feeders.py:1011) and nothing in this
    package ever multiplied by it, so the line printed the native magnitude under the analyst unit word
    -- ``118000000 MMT``, ``35852 M ha``, ``87157400 million head``, and a stocks-to-use ratio printed
    as ``0.13 %`` where the card's own ``scale: 100`` says 13 %. See :attr:`rows.StateRow.level_shown`
    for the measurement and for why ``level`` itself stays native. The K9-3 law is honoured by the
    numbers lane one file over (``numbers/cascade._prescaled``, :2255-2269); this is the state lane
    taking the same shape rather than restating the claim."""
    unit = st.narrate_unit or st.unit or ""
    two_sided = bool(st.convention and st.convention.get("kind") == "abs_bands")
    v = st.level_shown
    if v is None:
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


def event_window_open(window: dict, asof: str) -> Optional[bool]:
    """Is this EVENT row's declared window still open at ``asof``? ``None`` when no window was placed.

    ONE PRODUCER, because two consumers now ask it: :func:`sb_event` prints the answer as a sentence and
    the coverage instrument (S7 item 1) counts OPEN event rows as its own denominator. The first cut
    computed the predicate twice -- once here as a rendered clause and once in the counter -- which is
    the shape where a board tells a reader a window is open and tells a census it is closed."""
    if window.get("declined") or not window.get("opens"):
        return None
    if window.get("open_ended"):
        return True
    return bool(str(window.get("closes") or "") >= str(asof)[:10])


def sb_cross_commodity(names, *, anchor: str = "") -> str:
    """THE SPILLOVER LICENCE (S7 item 2) -- one line, minted by :func:`render_board` iff the block
    rendered at least one FAR row across a cross edge.

    IT IS A LICENCE AND NOT A CLAIM. It asserts no magnitude, no sign and no lag of its own: every one
    of those already sits on the far rows above it, each with the sign word and the lag words the graph
    declares for THAT market. What the line does is give the SPILLOVERS movement a heading to land in --
    ``narration.MANDATE_MOVEMENTS`` names ``## Cross-commodity`` first and ``## Mechanism`` as the
    fallback, and until this line existed the fallback was the only branch that ever fired.

    LETTERS AND WORD-COUNTS ONLY, like every other SB-F row: the names come through
    :func:`board_label`, the count through :func:`words_for_int`, and no digit reaches the line."""
    named = sorted({str(n) for n in names if n})
    body = ", ".join(named)
    seat = f"the loud readings on {anchor}" if anchor else "this board's loud readings"
    return (f"{SB_CROSS_COMMODITY_PREFIX}: {seat} are declared on {words_for_int(len(named))} other "
            f"{'market' if len(named) == 1 else 'markets'} -- {body} -- and each of the rows above "
            f"carries that market's own sign words and the lag words the graph states for it.")


def sb_event(row, *, receipt_handle: int, published: str, board: str, window: dict,
             asof: str) -> str:
    """SB-D (sec 6.2, 3.7, B18): a dated EVENT, anchored at the EVENT date and never at a later
    analysis piece's publication date. ISO dates only."""
    _open = event_window_open(window, asof)
    if _open is None:
        state = "the graph declares no lag from it, so no window is placed"
    elif window.get("open_ended"):
        state = f"the window opened around {month_words(window['opens'])} and the graph declares no close"
    elif _open:
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


def sb_fan(entry: dict, *, names_cap: int = 0) -> str:
    """SB-F (sec 6.2, 3.6): the fan-out, COUNTS IN WORDS. The COUNT is never cut -- it is what makes
    "the graph decides relevance" visible, and it is the figure a reader checks the enumeration against.

    **``names_cap`` BOUNDS THE ENUMERATION INSIDE THE LINE, AND SEC 3.6's "THE NAMES ARE NEVER CUT" IS
    ABOUT THE COUNT (S7).** MEASURED on the S4 census: an SB-F index line runs 628-648 characters
    because it enumerates 29-35 board labels through a bare ``', '.join``, and the class is 10.5% of the
    quick block on 3.1 lines. That is the same shape ``name_list`` was written for one class over -- a
    free INDEX is not a free ENUMERATION inside a line (the S6 review's major 12, measured at 23,871
    characters in one SB-X row). The count still says how many boards carry the reading, the remainder
    is stated in words, and NOTHING about which boards are priced changes: this line has never decided
    that (``render_spillover`` does, on the rows below it).

    THE ORDER THE CAP CUTS IN IS THE LINE'S OWN SPLIT -- the majority sign first, then the rest -- which
    is what the line already computed to be worth printing first. 0 = uncapped = the shipped behaviour
    on deep's own table and on max."""
    far = entry["far"]
    by_sign: dict = {}
    for f in far:
        by_sign.setdefault(f["sign"] or "", []).append(board_label(f["contract"]))
    if not by_sign:
        return ""
    cap = max(0, int(names_cap or 0))
    head_sign = sorted(by_sign, key=lambda s: (-len(by_sign[s]), s))[0]
    head = sorted(by_sign[head_sign])
    rest = sorted(c for s, cs in by_sign.items() if s != head_sign for c in cs)
    # THE CAP IS SHARED ACROSS THE TWO ARMS rather than applied twice, because it bounds the LINE. The
    # head arm takes what it needs first (it is the majority sign and the line leads with it) and the
    # rest arm takes what is left, never fewer than one name where it has any -- a "rest" arm that
    # printed a count and no name at all would state a split the reader cannot see.
    head_cap = min(len(head), max(1, cap - 1)) if (cap and rest) else (cap if cap else 0)
    rest_cap = max(0, cap - min(len(head), head_cap)) if cap else 0
    body = (f"{sign_words(head_sign)} on {words_for_int(len(head))} "
            f"({name_list(head, head_cap, noun='boards')})")
    if rest:
        other_sign = sorted(s for s in by_sign if s != head_sign)[0]
        body += (f" and {sign_words(other_sign)} on the rest "
                 f"({name_list(rest, max(1, rest_cap) if cap else 0, noun='boards')})")
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


#: THE CLOSED ORDERING VOCABULARY for an ``Interaction``'s ``effect`` (sec 3.5, D24). The shipped graph
#: declares exactly two words -- MEASURED at 271 ``amplifies`` and 6 ``dampens`` over the thirty-six
#: curated DAGs -- and the first S6 build spliced whichever string it found straight into the rendered
#: line. That is the same class of defect as the note below it, one field over: a curation edit adding a
#: third effect word, or a typo in an existing one, would have reached the writer as prose nobody
#: graded. The map IS the vocabulary; anything outside it renders as the unknown clause and the line
#: still says what it can, which is that the graph declares an interaction it has no word for here.
AMPLIFIER_EFFECT_WORDS: dict = {"amplifies": "amplifies", "dampens": "dampens"}

#: The word for an effect the vocabulary above does not declare. LETTERS ONLY and register-clean, and
#: it CORRECTS rather than deletes: the pair, the loud claim and the read split all still render.
AMPLIFIER_EFFECT_UNKNOWN = ("an interaction this board has no word for")

#: What the row says in place of a curated note that did not pass this block's own register check
#: (sec 6.6; the doctrine's "fences correct or compute, never delete"). THE NOTE IS NOT DROPPED
#: SILENTLY -- the row states, in its own words, that the graph carries a note here and that the note is
#: not in this block's register, so a reader is never shown a silence where prose used to be.
AMPLIFIER_NOTE_REPLACED = (" -- the graph carries its own note on this interaction; it is not in this "
                           "block's register and is replaced by this clause")


def amplifier_effect(effect: str) -> str:
    """An ``Interaction.effect`` as an ORDERING word from :data:`AMPLIFIER_EFFECT_WORDS`."""
    return AMPLIFIER_EFFECT_WORDS.get(str(effect or "").strip(), AMPLIFIER_EFFECT_UNKNOWN)


def governed_note(note: str) -> str:
    """CURATED PROSE FROM THE GRAPH, PASSED THROUGH THIS BLOCK'S OWN REGISTER FENCE (sec 6.6).

    THE DEFECT THIS CLOSES, MEASURED. ``Interaction.note`` is free text in a gitignored DAG config that
    rides the image tar, and :func:`sb_amplifier` spliced it VERBATIM into the rendered line. TWENTY-ONE
    of the shipped 277 notes trip a detector -- seventeen on ``_LANE_B_ADJ`` ("Cheap Black Sea supply
    plus a strong dollar make US SRW uncompetitive on exports, stranding supply and building stocks",
    soft_red_winter_wheat_cbot.yaml:949), three on ``count_flow_words`` + ``register_leaks``, one on
    ``count_valuation_words`` + ``_LANE_B_ADJ`` -- so a four-market question put three tripped lines on
    the board on deep AND max, and the fence's own correction then shipped the raw regime id.

    THE FENCE IS APPLIED TO THE SPLICED FRAGMENT RATHER THAN TO THE ASSEMBLED LINE, which is the whole
    point: ``Block.add`` grades the line and CORRECTS THE WHOLE ROW when it trips, so a dirty note took
    the amplifier's ordering fact -- the pair, the loud claim, the read split, the effect word -- down
    with it. Graded here, the governed half is replaced and every ungoverned half survives.

    THIS GRADING IS THE FIRST OF TWO AND IT IS NOT SUFFICIENT ALONE (S6 second verify, the standing
    major). A fragment can be clean BY ITSELF and still complete a class rule once it is spliced onto
    the row's own words, because the register's class rules read a SENTENCE and the note lands inside a
    sentence the row started. :func:`sb_amplifier` therefore grades the ASSEMBLED row as well and
    replaces the clause -- never the row -- when the completion is the note's. Keeping this fragment
    fence in front of it is deliberate rather than redundant: it is the STRICTER of the two (the
    assembled sentence can carry an ``_EXCLUDED_NOUN`` that suppresses a Lane B hit the fragment
    trips on), so dropping it would relax the measured behaviour above."""
    txt = ascii_text(note or "").strip()
    if not txt:
        return ""
    return f" -- {txt}" if not register_hits(txt) else AMPLIFIER_NOTE_REPLACED


def sb_amplifier(contract: str, inter: dict) -> str:
    """The AMPLIFIER sub-line (sec 3.5, D24): the graph's only amplifier semantics, rendered as an
    ordering fact under its pattern's row. Digit-free, and indented so its class is its own.

    EVERY INTERPOLATED FIELD IS GOVERNED (S6 re-fix). The ids go through ``display.node_label``, the
    board through ``display.node_label(kind='contract')``, the EFFECT through
    :data:`AMPLIFIER_EFFECT_WORDS` and the NOTE through :func:`governed_note`. Before this the effect
    and the note were the two raw config strings on the board, and the note was measured putting three
    fence trips on a four-named-market turn.

    THE NOTE IS GRADED TWICE -- ALONE, AND AS THE ROW WILL BE READ (S6 second verify, the standing
    major). :func:`governed_note` grades the FRAGMENT, and a fragment fence cannot see a class rule the
    SPLICE completes: the register's class rules read a sentence, ``_SENT_ITER`` breaks only on
    ``[.!?;]\\s+``, and this row's own last sentence is whatever follows its final semicolon -- the
    effect word, or the read-split tail. REPRODUCED, offline and byte-exact, on an interaction whose
    read split names a driver labelled with a spread noun:

        note   "expected to narrow from here"           -- `register_hits` == [], clean ALONE
        row    "  amplifier on CBOT soybeans: board crush spread, crude oil price all sit among this
                board's loudest rows; the graph records the effect as amplifies; board crush spread
                carries no series this board could read -- expected to narrow from here"
        hits   ['count_valuation_words', 'register_leaks']   (`forward-convergence`: the tail's SPREAD
               noun, the note's CONVERGE verb, the note's FUTURITY marker, one sentence)

    and the trip reached :meth:`Block.add`, which replaced the WHOLE row with its SB-X absence: the
    pair, the loud claim, the effect word and the read split all deleted to correct a curated clause.
    THE ASSEMBLED ROW IS GRADED HERE and, on a trip, the CLAUSE is replaced and the row is re-rendered
    whole -- which is the doctrine read the only way it can be read: correct the dirty clause, never
    delete the facts around it.

    THE ROW BUILT WITH THE REPLACEMENT CLAUSE IS NOT RE-GRADED, and that is an argument rather than an
    omission. :data:`AMPLIFIER_NOTE_REPLACED` carries no spread noun, no convergence verb, no futurity
    marker, no Lane A phrase, no Lane B adjective and no persistence word, so it can complete no class
    rule and match no phrase: if the row without a note is clean, the row plus that clause is clean.
    Should the row itself be dirty -- ids or effect word, none of them this function's to correct --
    ``Block.add`` corrects it, which is the right owner for a trip the note did not cause."""
    ids = ", ".join(humanise(i) for i in inter["when"])
    note = governed_note(inter.get("note"))
    # THE SUB-LINE SAYS WHICH OF ITS OWN IDS WERE READ, for the same reason SB-C does: an Interaction
    # whose `when` ids are all LOUD may still name a driver with no series at all (`biodiesel_mandate`
    # is an open EVENT row and enters the loud set by construction), and "all sit among this board's
    # loudest rows" invites a reader to hear a measured co-occurrence.
    unread = [humanise(i) for i in (inter.get("unmeasured") or ())]
    tail = (f"; {', '.join(unread)} {'carries' if len(unread) == 1 else 'carry'} no series this "
            f"board could read") if unread else ""
    row = (f"  amplifier on {board_label(contract)}: {ids} all sit among this board's loudest rows; "
           f"the graph "
           f"records the effect as {amplifier_effect(inter['effect'])}{tail}")
    if note and note != AMPLIFIER_NOTE_REPLACED and register_hits(row + note):
        note = AMPLIFIER_NOTE_REPLACED
    return row + note


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


def price_tape(bd, *, cap: Optional[int] = None) -> tuple:
    """DECLARE THE TAPE COLUMN'S SEATS **BEFORE** ITS FETCH, and return the anchor slugs the seats buy.

    S6 REVIEW, MAJOR 10. :func:`attach_tape` set ``tape_cap`` from the tape it was HANDED, i.e. after
    the reads had happened -- a post-hoc record of the spend wearing the word "cap". `WaveLedger`'s own
    ``priced_before_fetch`` predicate and ``Board.rectangle`` cover the two WAVES only, so nothing
    checked the third column, and design 3.8's law ("cut EACH wave at its cap BEFORE its fetch ... every
    dropped key is NAMED") did not reach it. The seam calls this first, reads only what it returns, and
    then calls :func:`attach_tape` with the measured spend.

    THE CAP IS THE ANCHOR COUNT unless a caller states a smaller one; with the anchor ceiling in the
    walk (``BoardKnobs.max_anchors``) that is a TIER number rather than an estate number, which is what
    made 35 serial mirror reads on the calling thread reachable from one FE gesture."""
    slugs = list(bd.anchor_slugs)
    n = len(slugs) if cap is None else max(0, int(cap))
    kept, dropped = slugs[:n], slugs[n:]
    bd.ledger.tape_cap = max(int(bd.ledger.tape_cap), len(kept))
    if dropped:
        bd.notes.append({"kind": "tape_cap", "cap": n, "names": tuple(dropped)})
    return tuple(kept)


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


def sb_analog_outcome(n: int, o: dict, *, asof: str, scale=1.0) -> tuple:
    """SB-O (sec 6.2, 4.3): the outcome over the band, read at BOTH ENDS. Two handles per outcome, so
    "moved X at the near end and Y at the far end" is two bound figures rather than a range.

    **``scale`` IS THE CARD'S, AND IT IS WHY THIS ROW TAKES ONE AT ALL** (S7 polish (b)). An outcome is
    usually read on a price BENCHMARK, which carries no card and no scale -- but ``analogs`` also builds
    outcomes on a DRIVER'S OWN series (the child row and a scope-keyed far state), off the same array
    the SB-1 row above it prints, and under the same ``narrate_unit`` word. Printing the SB-1 level in
    analyst units while this row printed the native change would put ONE series on ONE page at TWO
    magnitudes under ONE unit -- the precise failure ``rows.shown_value`` exists to close, arriving
    through the other door. A change scales as a level does, and :func:`render_board` supplies the
    card's scale from the board's own series map; 1.0 -- the default -- is a benchmark, and a benchmark
    is native.

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
    # THE CALL AND THE PRINTED WORDS TAKE THE SAME MAGNITUDE -- the two halves of ONE handle.
    # `verify._check_number_handle` value-checks a writer's copy of the printed figure against this
    # call's `shown` pool, so a line printing the scaled change over a call carrying the native one
    # would strip every figure the writer correctly transcribed. Figures AND words together.
    near_v = shown_value(o["near_value"], scale)
    far_v = shown_value(o["far_value"], scale)
    calls = [sb_call(value=round(float(near_v), 4), unit=o.get("unit") or "",
                     knowledge_date=o.get("near_date"), **q),
             sb_call(value=round(float(far_v), 4), unit=o.get("unit") or "",
                     knowledge_date=o.get("far_date"), **q)]
    line = (f"- [N{n}] {o['label']} over the band the graph declares from that state, "
            f"{band_words(o.get('band'))}: moved {_fmt(near_v)} "
            f"{o.get('unit') or ''} by the near end; [N{n + 1}] moved {_fmt(far_v)} "
            f"{o.get('unit') or ''} by the far end")
    return re.sub(r"\s+", " ", line).replace(" ;", ";"), calls


#: What a receipt row says in place of a QUOTED PASSAGE that did not pass this block's register check.
#: The handle, the tier, the source, both dates and the driver all still render beside it -- a reader
#: who wants the passage has the address of the document that carries it.
RECEIPT_QUOTE_REPLACED = ("the passage this document carries here is not in this block's register and "
                          "is replaced by this clause")

#: ...and in place of a SOURCE NAME that is itself the half that trips. The handle still resolves, so
#: the citation is not broken -- only the display name is withheld, and the row says so.
RECEIPT_SOURCE_REPLACED = "a source this block's register does not print"


def sb_receipt(e_handle: int, t_tier: int, r: dict, *, driver_id: str) -> str:
    """SB-R (sec 6.2): the D-HP-1 menu row in ``_ev_block``'s own shape (answer.py:3380) so
    ``cit.unify`` numbers it and the persona's ``[T1]-[T4]`` trust contract is preserved.

    THE QUOTE AND THE SOURCE NAME ARE CORPUS PROSE AND ARE FENCED THE WAY THE AMPLIFIER NOTE IS (S6
    second verify, minor (a)). ``r["text"]`` and ``r["source"]`` were interpolated VERBATIM through an
    ASCII fold, which is a fold and not a fence: retrieved prose is one seam over from
    ``Interaction.note``, it is the same class of ungoverned string, and it lands in a sentence THIS row
    started -- so it can complete a class rule the passage does not carry alone, exactly as the note
    did. Three of these rows render per stanza on deep and five on max.

    THE ROW IS GRADED AS THE DETECTOR WILL READ IT, and a trip replaces the CLAUSE rather than the row.
    The quote goes first because it is the retrieved half and the likeliest dirty one; only if the
    assembled row still trips is the SOURCE NAME replaced too, and even then the ``[E]`` handle, the
    ``[T]`` tier, the reported date, the event date and the driver survive. Deleting the row would take
    a citable document off the menu to correct a sentence inside it, and an ``[E]`` handle minted for a
    row that never rendered is a handle pointing at nothing -- the failure ``Block.add`` refuses."""
    src = ascii_text(r.get("source") or "the record")
    ev = r.get("event_date")
    ev_part = f"; event {ev}" if ev else ""

    def _row(source: str, quote: str) -> str:
        return (f"- [E{e_handle}][T{t_tier}] ({source}, reported {r.get('date')}{ev_part}) "
                f"{{driver: {humanise(driver_id)}}} {quote}".rstrip())

    line = _row(src, ascii_text(r.get("text") or ""))
    if not register_hits(line):
        return line
    line = _row(src, RECEIPT_QUOTE_REPLACED)
    return line if not register_hits(line) else _row(RECEIPT_SOURCE_REPLACED, RECEIPT_QUOTE_REPLACED)


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


def sb_phase_pair(names, board: str, *, opposed: bool) -> str:
    """SB-JOIN: TWO NAMES, ONE READING -- the row that stops a mutually-exclusive phase pair being
    narrated as a two-sided balance (S6 review, major 17). See the class's own note in ROW_CLASSES for
    why it is a class sec 6.2 does not declare.

    LETTERS ONLY AND NO HANDLE: it asserts no magnitude, it corrects the READING of two rows that each
    carry their own. That is the difference between this row and a fence that deletes -- both members
    keep their figure, their handle and their declared sign, and the reader is told the relation.

    **S8 DOCKET -- THE NON-OPPOSED SENTENCE BELOW IS MEASURABLY FALSE AND IS NOT REPAIRED AT S7.**
    "They are phases of one series and not separate readings" is untrue of BOTH non-opposed joins the
    banked S4 blocks carry: ``palm_olein_dce__quick`` joins ``China_import_tariff`` (declared
    ``type: policy_event``) and ``China_import_pace`` (``type: state_marker``), both on
    ``silver_ref: import`` -- two different CLAIMS read on one PSD metric, not two phases of anything;
    and ``soybeans_cbot__quick`` joins ``board_crush`` and ``soybean_crush_margin``, both
    ``type: instrument`` on ``cbot_board_crush_margin`` with the SAME declared sign -- two names for one
    instrument. The form the graph can actually declare is available (a phase pair is the pair signed
    OPPOSITELY on one series: ``El_Nino``/``La_Nina`` carry ``-``/``+`` on one ONI ref,
    ``IOD_positive``/``IOD_negative`` the same shape), and a corrected sentence was built and measured
    at S7 round 1: +140 characters on a board with one non-opposed join, +280 on a board with two.

    IT WAS WITHDRAWN IN ROUND 2 FOR A REASON THAT IS ABOUT THE ARM AND NOT ABOUT THE SENTENCE. S7 ships
    ONE change -- the Scan render caps -- and this class renders on EVERY tier, so keeping it would put
    a reworded sentence in arm A's CONTROL cells (deep and max, which the owner's 09-10 rule says run
    as S6 shipped them) and a SECOND flag in the treatment. Measured: it was the only line on the paid
    tiers that was not byte-identical to HEAD. S8 takes it, with the judged delta already read."""
    joined = " and ".join(names) if len(names) < 3 else (", ".join(names[:-1]) + " and " + names[-1])
    tail = (" The graph declares them opposite signs on this board, which is what two phases of one "
            "series means; they are not two readings that disagree."
            if opposed else
            " They are phases of one series and not separate readings.")
    return (f"BOARD JOIN {joined} on {board}: these are read on ONE series and the rows above print "
            f"the SAME reading under each name." + tail)


def sb_absence(label: str, reason: str) -> str:
    """SB-X (sec 6.2, 6.7): ``_cw_absence``'s shape (cascade.py:7528) with the reason as a SENTENCE from
    the closed map. An absence is a ROW; the reader is never shown a silence."""
    return f"BOARD ABSENCE {label}: {absence_why(reason)}."


def sb_subject_ambiguous(driver_ids, *, label: str = "subject") -> str:
    """SB-X, THE CARRIED-AMBIGUITY ROW (SUBJECT RESOLVER D5). A GENUINELY NEW SHAPE, not a reuse.

    WHY ``sb_absence`` CANNOT DO IT. :func:`absence_why` drops the ``:detail`` tail on purpose -- every
    other detail in the estate is a COUNT, and a count in a letters-only class is a digit a writer may
    copy into a claim. THIS detail is two driver NAMES, which is the whole content of the row: an
    absence line reading "the question could be about either of two drivers" and then not saying which
    two tells the reader nothing they can act on. So the word keeps its own sentence in
    :data:`ABSENCE_WHY` (true and complete on its own, for every caller that reaches it by the ordinary
    route) and this builder adds the second sentence with the names.

    THE NAMES ARE READER WORDS AND NOT IDS. :func:`humanise` is the estate's ONE display vocabulary;
    printing ``el_nino`` here would trip ``register.internal_leaks``, which is never relaxable, on a row
    whose entire job is to be read. The ids ride the board's TRACE and the ``:detail`` tail only, and
    ``seam.reason_dimension`` cuts that tail at the colon so two ids joined by a pipe can never become
    an unbounded CloudWatch dimension value.

    IT ASKS. That is the owner's word -- ambiguity is CARRIED into the answer and the reader is asked
    to name one -- and it is why this row, alone among the absences, addresses the reader directly.

    AND IT COUNTS. :data:`ABSENCE_WHY`'s sentence for this word says "EITHER OF TWO drivers", which is
    true of the state D5 usually carries and false of a one-id carry -- and a one-id carry is reachable
    (``AMBIG_FLOOR`` is a floor, not a pair rule: one candidate can clear it while the planner still
    picks nothing). The plural sentence then printed "either of two drivers ... It could mean El Nino",
    which counts to two and then names one. So the singular gets its OWN sentence here rather than the
    closed word getting a second entry: :data:`ABSENCE_WHY` is one sentence per word by construction,
    and the word is the same fact either way -- the reader was not told which driver the question
    means."""
    names = [humanise(d) for d in (driver_ids or ()) if str(d or "").strip()]
    if not names:
        return sb_absence(label, "subject_ambiguous")
    if len(names) == 1:
        return (f"BOARD ABSENCE {label}: the question may be about a driver this estate tracks and "
                f"does not name it outright. It could mean {names[0]}; say so and this board opens "
                f"on it.")
    joined = (" or ".join(names) if len(names) < 3
              else ", ".join(names[:-1]) + " or " + names[-1])
    return (f"BOARD ABSENCE {label}: {absence_why('subject_ambiguous')}. It could mean {joined}; "
            f"name the one you mean and this board opens on it.")


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


#: The reader-facing name a correction row falls back to when the caller offered none, or offered one
#: that did not itself pass the fence. LETTERS ONLY, no id, no slug.
CORRECTED_ROW_FALLBACK = "a composed line"


def open_sentence(text: str) -> str:
    """THE UNTERMINATED SENTENCE ``text`` ENDS IN, as the REGISTER SCANNER segments it.

    IT READS THE ONE PRODUCER (``register._SENT_ITER``) rather than re-typing its rule, which is the
    whole point: a private copy of a sentence splitter would agree with the detector until the first
    edit, and the class rules are the detectors that read a SENTENCE rather than a token.

    WHY THE BLOCK NEEDS THIS AT ALL -- THE THIRD BLIND SPOT OF THE S6 REVIEW, MEASURED. ``_SENT_ITER``
    splits on ``[.!?;]\\s+`` and DELIBERATELY does not split on a bare newline (its own note: a
    line-wrapped class-rule triple is ONE sentence and IS flagged). Board rows carry no terminal
    punctuation, so every adjacent pair of rows WELDS into one sentence for the scanner -- and a fence
    that grades each row alone cannot see a class rule the weld completes. MEASURED on a `focus_driver`
    Cascade turn through the seam: ``register_leaks`` on the BLOCK returned one `forward-convergence`
    hit while every one of its 259 lines was clean alone, the spread noun and the converge verb coming
    from the convergence render-cap absence row and the futurity from the amplifier line above it."""
    from leviathan.graphrag import register as reg
    return reg._SENT_ITER.split(str(text or ""))[-1] if text else ""


class Block:
    """The rendered block, its calls, and every trip the fence corrected.

    LINES AND CALLS ARE COMMITTED TOGETHER. :meth:`add` builds a candidate line with its candidate
    calls, runs the fence, and either commits BOTH or replaces the line with its SB-X absence and
    commits NEITHER -- because a handle whose call was dropped is a citation pointing at nothing, which
    is a worse failure than the register trip it was trying to correct.

    THE FENCE GRADES A ROW THE WAY THE DETECTOR WILL READ IT, which is not the same as grading the row.
    See :func:`open_sentence`: the scanner welds consecutive unterminated rows into one sentence, so the
    block keeps the OPEN sentence its committed rows end in and grades each candidate against it. A weld
    that trips is CORRECTED BY COMPUTATION rather than by deletion -- the previous row is closed as a
    sentence (the terminator it never carried) so the two rows are two sentences again, which is what
    they always were. Neither row loses a word, a handle or a call."""

    def __init__(self, *, start: int = 1, e_start: int = 1):
        self.lines: list = []
        self.calls: list = []
        self.trips: list = []
        self.classes: list = []
        #: Every weld this block closed, as ``{"at": <index of the row that gained the terminator>,
        #: "hits": (...)}``. Recorded rather than silent: a weld correction changes a committed row's
        #: bytes, and a byte change nobody can count is a byte change nobody can review.
        self.welds: list = []
        #: THE COVERAGE MANIFEST (S7 item 1), parallel to :attr:`lines`: one dict per committed row
        #: carrying the ROLE the render gave it, the ``[N]`` handles it actually minted, and -- for a
        #: letters-only row -- the token groups a reader must utter to have used it.
        #:
        #: IT EXISTS BECAUSE ``calls`` LOSES THE ROW (the G1 gap, measured by the design lane).
        #: ``self.calls`` is flat and ``self.classes`` is parallel to ``lines``, not to ``calls``, so
        #: "which board rows reached the page" could not be computed from the shipped payload at all --
        #: the counters publish twenty-odd numbers about what the board COST and not one about what it
        #: BOUGHT. The stamp is written HERE, where the line and its calls are committed together, for
        #: the same reason they are committed together: a manifest built anywhere else would be a
        #: second opinion about which handles belong to which row.
        self.rows_meta: list = []
        self._next = int(start)
        self._next_e = int(e_start)
        self._open = ""                 # the unterminated sentence the committed rows end in

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

    def add(self, line: str, calls=(), *, label: str = "", display: str = "",
            allow_empty: bool = False, role: str = "", rank=None, tokens=()):
        """Commit ONE row. Returns the line actually committed (possibly the SB-X correction).

        ``role`` / ``rank`` / ``tokens`` FEED :attr:`rows_meta` AND NOTHING ELSE (S7 item 1). They
        change no byte of the block: a caller that passes none of them still gets a manifest entry,
        with an empty role, which is what every row that no coverage rule asks about should carry.
        ``tokens`` is the letters-only surface's own reference test, minted here from the row's own
        display words -- a tuple of ALTERNATIVE GROUPS, all of which must be satisfied inside ONE prose
        sentence for the row to count as referenced (see :func:`board_coverage`).

        A ROW THE FENCE CORRECTED KEEPS ITS ROLE AND LOSES ITS HANDLES, which is the honest record: the
        reader met an SB-X absence where a loud row should have been, so the row is still in the
        denominator and can never be referenced.

        ``label`` IS INTERNAL AND ``display`` IS THE READER'S -- and separating them is the S6 re-fix's
        major 1. The correction row used to interpolate ``label``, which every caller builds from the
        row's own ids (``f"amplifier {c['name']}"``, ``f"phase pair {contract}"``), so THE REGISTER
        FENCE'S OWN CORRECTION SHIPPED RAW INTERNAL IDS INTO THE WRITER PROMPT. MEASURED on the
        four-named-market shape (soft_red_winter_wheat_cbot / corn_cbot / soybeans_cbot /
        malaysian_crude_palm_oil_cme, as-of 2026-09-07, through ``state.seam``): deep and max each
        shipped ``trips=3, register_leaks=3, internal_leaks=3``, the leaked tokens being the raw
        convergence-regime ids ``bearish_glut`` and ``bearish_big_crop_glut``. ``label`` still rides
        ``self.trips``, where it is telemetry and an id is exactly what a reader of a trip wants.

        THE FALLBACK IS FAIL-CLOSED AND CLOSES THE CLASS, NOT THE INSTANCE. A caller that offers no
        display name gets :data:`CORRECTED_ROW_FALLBACK`, and a display name that does not ITSELF pass
        the fence is discarded for the same fallback -- so no future call site can reintroduce the leak
        by handing this method a name built from an id. The assembled correction row is graded too: a
        correction that trips is not a correction."""
        if not line and not allow_empty:
            return ""
        hits = register_hits(line)
        if hits:
            self.trips.append({"label": label or line[:40], "hits": tuple(hits), "line": line})
            line = self._correction(display)
            calls = ()
        elif self._open and self._weld_hits(line):
            # THE WELD (see `open_sentence`). The candidate is clean and the open sentence was clean
            # when it was committed, so the hit belongs to NEITHER row -- it belongs to the join, and
            # the join exists only because a board row carries no terminator. CLOSING the previous row
            # as a sentence is the computation that removes it; deleting either row would delete a
            # clean fact to fix a punctuation defect.
            self.welds.append({"at": len(self.lines) - 1, "hits": tuple(self._weld_hits(line))})
            if self.lines and not str(self.lines[-1]).rstrip().endswith((".", "!", "?", ";")):
                self.lines[-1] = self.lines[-1].rstrip() + "."
                self.classes[-1] = classify(self.lines[-1])
                # THE MANIFEST IS PART OF THE COMMITTED ROW, so a weld correction that rewrites a
                # committed line rewrites its manifest entry too -- otherwise the coverage instrument
                # would grade a row against bytes the reader never saw.
                if self.rows_meta:
                    self.rows_meta[-1]["line"] = self.lines[-1]
                    self.rows_meta[-1]["cls"] = (self.classes[-1] or ("",))[0]
            self._open = ""
        _h0 = self._next
        self.lines.append(line)
        self.classes.append(classify(line))
        self._open = open_sentence((self._open + "\n" + line) if self._open else line)
        for c in calls:
            self.calls.append(c)
            self._next += 1
        self.rows_meta.append({
            "role": str(role or ""), "rank": rank,
            "cls": (self.classes[-1] or ("",))[0],
            "handles": tuple(range(_h0, self._next)),
            "tokens": tuple(tuple(str(t) for t in g if str(t)) for g in (tokens or ()) if g),
            "line": line,
        })
        return line

    def join_rows(self, handles, group: str) -> int:
        """Stamp ``join`` on the manifest entries whose FIRST handle is in ``handles``. Returns how many
        rows were stamped.

        TWO NAMES, ONE READING -- THE COVERAGE HALF OF THE PHASE-PAIR FENCE. The BOARD JOIN line already
        tells the reader that El Nino and La Nina are one ONI reading under two names, and the mandate
        tells the writer to give ONE side and never two (the prod-seat smoke measured it obeying that on
        10 of 10 groups, exactly one member cited each time). Without this stamp the folded twin scored
        as an unused loud row on every single group -- twelve of the fourteen apparently-ignored loud
        rows on the three banked draws -- while the LOOSE read scored it as USED, because the twins
        share one series and therefore one ``shown`` pool. Both readings were artefacts of counting two
        rows where the block declares one.

        IT CHANGES NO BYTE OF THE BLOCK: the manifest is parallel telemetry, both rows keep their line,
        their handles and their own declared sign, and the JOIN row itself still renders."""
        want = {int(h) for h in (handles or ())}
        n = 0
        for m in self.rows_meta:
            hs = tuple(m.get("handles") or ())
            if hs and int(hs[0]) in want:
                m["join"] = str(group)
                n += 1
        return n

    def _weld_hits(self, line: str) -> list:
        """The detectors the OPEN sentence plus this candidate trip together. Empty == no weld."""
        return register_hits(self._open + "\n" + line)

    def _correction(self, display: str = "") -> str:
        """The SB-X row that replaces a line the fence tripped, named in READER words or not at all."""
        name = ascii_text(display or "").strip()
        if name and register_hits(name):
            name = ""                              # a name that trips is no name a reader may be shown
        row = sb_absence(name or CORRECTED_ROW_FALLBACK, "template_register_trip")
        return row if not register_hits(row) else sb_absence(CORRECTED_ROW_FALLBACK,
                                                             "template_register_trip")

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
#:
#: **S7 MOVES THE SCAN ROW AND ONLY THE SCAN ROW**, on the owner's ratified rule of 09-10: "Scan
#: (quick) gets render CAPS at S7; deep and max run UNCAPPED into arm A, the judged delta decides."
#: The measurement it rests on is the S4 board census (36 boards, pg mirror, in-VPC): the QUICK block
#: measured 53 lines / 13,648.5 chars / ~3,412.5 est tokens at the MEDIAN board, against sec 7's own
#: Scan sizing of "~17-20 lines, ~1,100 tokens" -- **3.10x by tokens, 2.79x by lines** -- in front of a
#: writer budget of 105-154 words (`reasoning_modes` 150-220 x `budget_scale` 0.7). Deep measured
#: 2.17x and max 1.72x, which is why they are left alone.
#:
#: THREE NEW KEYS RIDE THE TABLE RATHER THAN THE KNOB ALONE (`fan_names`, `projection`, `edge`), for
#: the reason `render_caps`' own docstring gives: a board built from a hand-built knob tuple has no
#: render fields at all, and a missing attribute read as zero would silently uncap -- or cap to
#: nothing -- a class nobody meant to move. `absence` and `absence_names` stay knob-only because the
#: design plans NO number for them (sec 7 sizes states, spillovers, patterns, stanzas and watch rows
#: and stops); those two are bounds the S6 review added against a measured overrun, not design rows.
#:
#: **AND EVERY ONE OF THE THREE IS ZERO ON DEEP AND ON MAX** (round 2 of S7, the owner's decision). The
#: first cut gave deep a `fan_names` of 24 -- a bound on the ENUMERATION inside one line, never a row --
#: and that is still a departure from "deep and max run UNCAPPED into arm A". A cap arm A did not
#: intend is a second flag in a one-flag experiment. 0 is this table's declared UNCAPPED sentinel and
#: every tier declares every key, so the paid tiers are byte-identical to the S6 render -- which is what
#: makes them the control the judged delta is read against -- without the shape of the table moving.
#:
#: `rank_cuts` IS THE FOURTH AND IT IS NOT A SIZE. It says whether this tier writes a CUT LINE's name
#: list in the board's own rank order or alphabetically; see :func:`rank_cuts`. It rides here because
#: it is a per-tier render constant like the rest, and it is 1 on Scan alone for the same reason the
#: caps are -- an ordering is only a decision where something is cut, and Scan is the only tier that
#: cuts. Deep and max keep HEAD's lexical order, docketed at :func:`_named_rows`.
RENDER_CAPS: dict = {
    "quick": {"spillover": 4, "convergence": 1, "analog": 0, "analog_outcomes": 0, "receipts": 0,
              "fan_names": 8, "projection": 4, "edge": 0, "rank_cuts": 1},
    "deep": {"spillover": 8, "convergence": 4, "analog": 1, "analog_outcomes": 4, "receipts": 3,
             "fan_names": 0, "projection": 0, "edge": 0, "rank_cuts": 0},
    "max": {"spillover": 16, "convergence": 6, "analog": 2, "analog_outcomes": 4, "receipts": 5,
            "fan_names": 0, "projection": 0, "edge": 0, "rank_cuts": 0},
}


def render_caps(mode: str, knobs=None) -> dict:
    """The tier's render caps. ``knobs`` (a :class:`state.board.BoardKnobs`) WINS when it carries the
    S6 render fields, so the caps ride the mode table with every other per-mode constant instead of
    being a second opinion in this module.

    THE TABLE ABOVE STAYS THE DEFAULT rather than becoming a fallback nobody reaches: a board built
    with a nine-field knob tuple (the S2 fixtures, the census, a hand-built preset) has no render
    fields at all, and reading a missing attribute as zero would silently cut every class to nothing.
    ``getattr(..., None)`` per field, table value when absent -- and the shipped presets carry exactly
    the table's numbers, so this returns the same dict either way (pinned)."""
    from leviathan.graphrag import reasoning_modes as rm
    base = dict(RENDER_CAPS.get(rm.base_mode(mode), RENDER_CAPS["deep"]))
    if knobs is None:
        return base
    for name, field in (("spillover", "render_spillover"), ("convergence", "render_convergence"),
                        ("analog", "render_analog"), ("analog_outcomes", "render_analog_outcomes"),
                        ("receipts", "render_receipts"),
                        # S7: the three classes sec 7's Scan row never budgeted at all. MEASURED on the
                        # S4 census, 22.5% of the quick block sits in five unbudgeted classes (SB-J,
                        # SB-P, SB-JOIN, SB-T, SB-H) and SB-E+SB-F rendered 13.3 lines against a
                        # planned 4 -- because the seed's OWN edge line is minted once per state row,
                        # OUTSIDE `render_spillover`, which bounds only the fan index and the far edges.
                        ("fan_names", "render_fan_names"), ("projection", "render_projection"),
                        ("edge", "render_edge")):
        v = getattr(knobs, field, None)
        if v is not None:
            base[name] = int(v)
    # THE ABSENCE CAP IS A KNOB WITH NO TABLE ROW, because the design plans no number for it (sec 7
    # sizes states, spillovers, patterns, stanzas and watch rows and stops). 0 = UNCAPPED = today.
    base["absence"] = int(getattr(knobs, "render_absence", 0) or 0)
    # THE NAMES INSIDE ONE ABSENCE LINE (S6 review, major 12). Every cap above bounds ROWS, and the
    # class that overran hardest overran INSIDE a row: MEASURED at 23,871 characters in ONE `BOARD
    # ABSENCE` line on a `focus_driver` Scan turn, because an absence group names every row it covers
    # and "the NAMES are never cut". They are still never cut SILENTLY -- the line ends with the count
    # it did not print, which is what "every cut names what it cut" asks for. 0 = uncapped.
    base["absence_names"] = int(getattr(knobs, "render_absence_names", 0) or 0)
    return base


def rank_cuts(caps: Optional[dict]) -> bool:
    """Whether this tier's name lists and absence groups are ordered by the BOARD'S OWN RANK rather
    than by the alphabet -- declared on the quick row of :data:`RENDER_CAPS` and nowhere else (S7
    round 2).

    IT IS TIED TO THE CAPS BECAUSE IT IS ONLY A DECISION WHERE SOMETHING IS CUT. A list printed WHOLE
    reaches the reader whole in either order; the order becomes content the moment ``name_list`` or
    ``render_absence`` drops a tail, and Scan is the only tier that drops one. So the rank rides the
    tier that cuts, and deep and max keep HEAD's lexical order byte for byte -- which is what makes
    them arm A's control rather than a second treatment.

    **THE LEXICAL ORDER ON DEEP AND MAX IS A DOCKETED DEFECT, NOT A DESIGN** -- see the S8 docket at
    :func:`_named_rows`."""
    return bool(int((caps or {}).get("rank_cuts") or 0))


_ISO_RX = re.compile(r"\d{4}-\d{2}-\d{2}")

#: The layer words a RECENCY row's own sentence must share with the prose for the row to count as
#: referenced -- the row template's OWN edge phrasing (``narration.recency_rows``), lower-cased, so
#: this is a restatement of the line rather than a second vocabulary.
#:
#: THEY ARE THE EDGE WORDS AND NOT THE DATE WORDS, and the first cut proved why. It admitted "as of"
#: on the numbers layer and a bare "tape" on the tape layer, and re-scoring the three banked prod-seat
#: draws then returned 3 of 7 referenced -- against a human reading of the same three answers that
#: found ZERO. All three "hits" were the loose token: "Reading the board as of 2026-09-07" (the turn's
#: as-of, which nearly every answer states, and not the layer's edge), "Front-month tape context ...
#: settled on 2026-09-04" (a price row, not the tape's edge) and "A dated document already on the
#: record (reported 2026-08-20)" (one document, not the newest). The row's claim is "the newest X is
#: D"; the token must be the part that makes it that claim.
#: A BARE "knowledge date" WAS STILL THE WRONG TOKEN, for the same reason one turn further in: the
#: EVIDENCE movement already tells the writer to date every row it leans on by that row's own
#: knowledge date, so "Note its knowledge date is 2025-12-31" -- a per-ROW sentence, and the correct
#: behaviour under a DIFFERENT rule -- landed in the same sentence as one of the layer's own dates and
#: scored the LAYER row as used. The qualifier is what separates the two claims, and it is the word
#: the row's own template carries.
#: THE COUPLING IS NAMED RATHER THAN HIDDEN: these are the mandate's OWN words for the three layers
#: ("the newest knowledge date the number rows carry, the newest dated document behind the page, the
#: session the board price tape runs through"), so a writer that conveys the layer fact in its own
#: words -- "the most recent number behind this page is dated 2026-09-04" -- scores MISSED. The
#: alternatives above widen the tape and text layers as far as a bounded list can, and the direction of
#: the residual error is UNDER-claim, which is the safe one for an instrument. But a rise in
#: `recency_referenced` at the arm must be read as uptake OR as transcription of the literal being
#: taught, and the two cannot be separated by this counter alone.
#: THE B FOLD (S7). ``numbers`` carried ONE literal -- the mandate's own phrase -- and the S6b prod-seat
#: smoke measured the cost: the banked ``soybeans_now`` answer reads "the newest number row is dated
#: 2026-09-04 and the oldest 2025-12-31", which is the layer fact stated correctly in the writer's own
#: words, and the instrument scored it MISSED. A human read 3 of 3 on that turn and 9 of 9 pooled
#: against the instrument's 5 of 7.
#:
#: THE RULE THAT BOUNDS EVERY ADDITION, AND IT IS THIS MAP'S OWN ARGUMENT ABOVE: every alternative MUST
#: carry a SUPERLATIVE (``newest`` / ``most recent`` / ``oldest``). The superlative is exactly what
#: separates a claim about the LAYER from the EVIDENCE movement's per-ROW rule, which tells the writer
#: to date every row it leans on by that row's own knowledge date -- which is why a bare
#: ``knowledge date`` was correctly refused and stays refused. Nothing here widens the test to a phrase
#: a per-row sentence could satisfy.
_RECENCY_LAYER_WORDS: dict = {
    "numbers": ("newest knowledge date", "newest number row", "newest number", "most recent number",
                "oldest number row", "newest figure", "most recent figure"),
    "text": ("newest dated document", "newest document", "most recent document",
             "most recent dated document"),
    "tape": ("price tape", "tape runs through", "tape edge"),
}


def _date_forms(iso: str) -> tuple:
    """EVERY FORM OF ONE DATE THE BLOCK ITSELF PRINTS, plus the two an ordinary reader writes -- the A
    FOLD of the coverage instrument (S7).

    THE MEASURED MISS. The ``b40_event`` open-event row's tokens were ``2026-05-01`` alone, and the
    banked prod-seat answer reads "Indonesia's move to a forty percent palm blend, dated **1 May 2026**,
    is a demand-side diversion" -- the right event, at D and not D+30, with the window transcribed
    exactly. Bar B18 HELD and the token test did not: ``events_referenced`` scored 0 of 1 on an answer
    that used the row correctly.

    THE FORMS, and every one of them names THE SAME DAY:
      * the ISO string -- what ``sb_event`` prints;
      * ``1 May 2026`` and ``May 1, 2026`` -- the two ordinary-language spellings, both derived from
        :data:`MONTH_NAMES`, no new vocabulary.

    **EVERY FORM IS DAY-PRECISE, AND THAT BOUND IS MEASURED RATHER THAN ARGUED.** The first cut of this
    helper ALSO returned ``month_words(iso)`` (``May 2026``), on the reasoning that the block prints
    that form itself and an instrument refusing it charges the writer for reading the block. Re-scoring
    the banked draws killed it: the CROSSED control -- each board scored against the OTHER scenarios'
    answers -- rose from 5 of 22 watch rows to 9 of 22, i.e. the control rose by MORE than the real
    signal did (7 to 9). A month form is a COARSER claim than the row's date: the three fixtures share
    drivers, so "El Nino" plus "October 2026" in somebody else's answer satisfied a watch row keyed on
    2026-10-01. A fold that lifts a control is not a fold, it is a leak. And the block does not in fact
    print the event DATE in month words -- ``sb_event`` prints the ISO date and puts month words on the
    WINDOW, which is a different fact about a different day.

    A bare year and a bare month are refused for the same reason, one step further out: a bare ``May``
    hits any sentence about spring and a bare ``2026`` hits nearly every sentence on the page.

    ONE HELPER, THREE CALL SITES (events, ``_watch_tokens``, ``_recency_tokens``), so the three graded
    classes can never drift apart on what counts as a date."""
    s = str(iso or "").strip()
    if not _ISO_RX.fullmatch(s):
        return (s,) if s else ()
    mw = month_words(s)
    if not mw:
        return (s,)
    try:
        day = int(s[8:10])
    except ValueError:
        return (s,)
    month, year = mw.split(" ", 1)
    return (s, f"{day} {month} {year}", f"{month} {day}, {year}")


def _date_group(text: str) -> tuple:
    """Every date form for every ISO date in ``text``, as ONE token group. A group is satisfied by any
    member, and two spellings of one date are the same claim -- so they belong in one group, while two
    DIFFERENT dates stay alternatives within it exactly as the ISO-only test already had them."""
    out: list = []
    for iso in _ISO_RX.findall(str(text or "")):
        out.extend(_date_forms(iso))
    return tuple(dict.fromkeys(out))


def _name_words(label: str) -> tuple:
    """A row's own name plus the ONE relaxation the instrument allows: its last word, when that word is
    long enough to be a name rather than a preposition.

    IT IS THE SAME BOUNDED CHARITY AS :func:`_market_words`. The board calls a driver "ending stocks"
    and the prod seat wrote "Malaysian month-end stocks print 2026-09-10" -- one row, one date, one
    plainly-used fact, and a full-label test would have scored it a MISS. The bound is that only the
    LAST word is optional and only at five characters or more, so "IDR USD" does not collapse to a
    three-letter token that hits by accident."""
    lbl = str(label or "").strip()
    if not lbl:
        return ()
    last = lbl.split(" ")[-1]
    return (lbl, last) if (len(last) >= 5 and last != lbl) else (lbl,)


def _watch_tokens(w: dict) -> tuple:
    """A WATCH row's reference test: its own ISO date(s), and the driver it watches, in ONE sentence.

    A DATE ALONE IS NOT ENOUGH AND A NAME ALONE IS NOT EITHER. The block carries thirty-odd ISO dates
    and a `## What to watch` section that repeats one of them proves nothing about WHICH row it came
    from; the pair is what makes the count a count of rows rather than of dates."""
    dates = _date_group(w.get("dates") or "")
    who = ()
    row = w.get("row") or ()
    if isinstance(row, (tuple, list)) and len(row) == 2 and row[1]:
        who = _name_words(humanise(row[1]))
    groups = [g for g in (dates, who) if g]
    return tuple(groups)


def _recency_tokens(layer: str, text: str) -> tuple:
    """A RECENCY row's reference test: its own ISO date(s) AND one of its layer's own edge words.

    A ROW WITH NO DATE IS UNTESTABLE, NOT MISSED ("not carried on this page" is the true statement for
    a layer this turn holds nothing for). Returning no groups is how a row leaves the denominator --
    absent is never zero, and a coverage figure must never charge a writer for a fact nobody served."""
    dates = _date_group(text)
    if not dates:
        return ()
    words = _RECENCY_LAYER_WORDS.get(str(layer or ""), ())
    return (dates, words) if words else (dates,)


def _series_scales(bd) -> dict:
    """``{(table, metric, commodity, country): scale}`` off the board's OWN series map -- the lookup an
    SB-O row needs to print its change on the same scale the SB-1 row above it printed its level (S7
    polish (b)).

    THE JOIN IS ON THE FOUR FIELDS ``outcome_over_band`` COPIES OUT OF THE STATE ROW, because that is
    all it copies: its returned dict carries ``label``, ``unit``, ``table``, ``metric``, ``commodity``,
    ``country`` and the band, and the series KEY it was read under is not among them. Those four
    identify the reading for every producer in this lane -- they are the same four the call record ``q``
    is built from one class up.

    **A CONFLICT REFUSES TO SCALE RATHER THAN GUESSING.** Two cards that share all four fields and
    declare different scales are already a defect the state lane cannot resolve from here, and printing
    ONE of the two scales on a row that might belong to the other would be a figure this function
    invented. ``None`` means native, and the SB-1 rows in that case disagree with each other too, which
    is the failure to fix at the card rather than in the render."""
    out: dict = {}
    for st in (getattr(bd, "series", None) or {}).values():
        key = getattr(st, "key", None)
        k = (str(getattr(st, "table", "") or ""), str(getattr(st, "metric", "") or ""),
             str(getattr(key, "commodity", "") or ""), str(getattr(key, "country", "") or ""))
        try:
            s = float(getattr(st, "scale", 1.0) or 1.0)
        except (TypeError, ValueError):
            s = 1.0
        if k in out and out[k] != s:
            out[k] = None
        else:
            out.setdefault(k, s)
    return out


def _outcome_scale(o: dict, scales: dict) -> float:
    """The card scale for ONE outcome row, or 1.0. A PRICE BENCHMARK carries no card and is native --
    which is the commonest case and the correct one, not a fallback."""
    k = (str(o.get("table") or ""), str(o.get("metric") or ""),
         str(o.get("commodity") or ""), str(o.get("country") or ""))
    s = (scales or {}).get(k)
    return 1.0 if s is None else float(s)


def render_board(bd, *, analogs=(), watch=(), receipts_by_row=None, recency=None, start: int = 1,
                 e_start: int = 1, anchor_label: str = "", loud_only: bool = True, age_clauses=None,
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
    # `start` AND `e_start` ARE BOTH THE TURN'S, NOT THE BLOCK'S (S6). The block used to mint `[E1]`
    # unconditionally, which is correct offline and WRONG at the seam: the turn's own evidence menu is
    # numbered from 1 by `cit.unify` over `uniq`, so a board event receipt would print a handle already
    # pointing at somebody else's document -- the same collision `take_e` was written to remove one
    # scope in. The seam passes `len(uniq) + 1`; the harness and every deck leave it at 1.
    b = Block(start=start, e_start=e_start)
    cap = dict(caps or render_caps(bd.mode, getattr(bd, "knobs", None)))
    ages = dict(age_clauses or {})
    b.add(sb_header(bd, anchor_label=anchor_label), label="header")

    order = {k: i for i, k in enumerate(bd.order)}
    # THE RANK THE **CUT** LINES TAKE, and it is `None` on every tier but Scan (S7 round 2). The state
    # rows above are rank-ordered on EVERY tier and always were -- that is `bd.order`'s own job. What
    # moves here is narrower: the order the NAME LISTS inside cut lines are written in. It is a decision
    # only where a list is cut, Scan is the only tier that cuts one, and deep and max are arm A's
    # control, so they keep HEAD's lexical order byte for byte. `_named_rows(pairs, None)` IS that
    # lexical order.
    rank = order if rank_cuts(cap) else None
    # THE CARD SCALES THIS BOARD READ, built ONCE (S7 polish (b)). Every figure of a card's series on
    # this page -- the SB-1 level and the SB-O change alike -- is multiplied by the SAME number, so a
    # reader never meets one series at two magnitudes under one unit word.
    _scales = _series_scales(bd)
    loud = sorted((r for r in bd.rows if r.legs.get("loud")),
                  key=lambda r: order.get(r.key, len(order)))
    rendered = loud if loud_only else sorted(bd.rows, key=lambda r: order.get(r.key, len(order)))

    from leviathan.graphrag.state.walk import horizon_sits, projection_window

    # -- STATES, each with its edge and its projection ------------------------------------------------
    # THE TWO PER-STATE-ROW CLASSES ARE CAPPED SEPARATELY FROM THE STATE ROW ITSELF (S7), because they
    # are minted once per rendered state and sec 7's Scan row budgets neither. MEASURED on the S4
    # census, per quick board: SB-J 7.8 lines / 1,522 chars (11.4% of the block, NOT BUDGETED AT ALL)
    # and SB-E 10.2 lines / 1,599 chars against a planned four -- the four the design writes are the
    # FAN's far edges, which `render_spillover` already bounds (:1795-1834); the seed's OWN edge line is
    # minted here, outside that cap, once per loud row.
    #
    # THE CUT TAKES `bd.order` AND NOTHING ELSE -- the same rank the state rows above are sorted by and
    # the same rank `role="state", rank=` stamps -- so the rows whose projection and whose link the
    # reader keeps are the board's loudest, not its alphabetically-first.
    #
    # `edge` SHIPS AT 0 = UNCAPPED ON EVERY TIER. The mechanism is minted here and the number is S8's:
    # an SB-E line is the sentence that makes ruling 3 renderable (two boards, two lines, never
    # reconciled), and cutting it is a decision about what the reader is TOLD rather than about length
    # alone. Every cut names what it cut, both of these included.
    handles_by_row: dict = {}
    proj_n, proj_cut = 0, []
    edge_n, edge_cut = 0, []
    for row in rendered:
        st = row.state
        if st is None or status_word(st.status) != "ok":
            continue
        h = b.next_handle
        line, calls = sb_state(h, row, asof=bd.asof, age_clause=ages.get(row.key, ""))
        if line:
            b.add(line, calls, label=f"{row.contract}/{row.driver_id}",
                  display=f"the state row for {row_words(row.contract, row.driver_id)}",
                  # THE RANK IS THE LOUD CUT'S OWN POSITION (S7 item 1), taken from `rendered`, which is
                  # `bd.order`-sorted -- never from the [N] index, which is call order and carries no
                  # rank at all (the utilisation census's own finding: "today's block has NO RANK").
                  role="state", rank=len(handles_by_row))
            handles_by_row[row.key] = h
        if not int(cap.get("edge") or 0) or edge_n < int(cap["edge"]):
            b.add(sb_edge(row), label=f"edge {row.driver_id}",
                  display=f"the declared link for {row_words(row.contract, row.driver_id)}")
            edge_n += 1
        else:
            edge_cut.append(row.key)
        win = bd.windows.get(row.key) or {}
        anchor_date = win.get("near") or st.level_date
        # D18's fourth clause: a `context_only` row is NEVER A PROJECTION ANCHOR. Its STATE row renders
        # (it is read and it is context), and it carries the past-tense clause that says what it is;
        # projecting a window forward from it would be the R9 guard's measured failure written by the
        # board instead of by the writer.
        _proj_full = bool(int(cap.get("projection") or 0)) and proj_n >= int(cap.get("projection") or 0)
        if anchor_date and not row.context_only and _proj_full:
            proj_cut.append(row.key)
        elif anchor_date and not row.context_only:
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
                  label=f"projection {row.driver_id}",
                  display=f"the projection for {row_words(row.contract, row.driver_id)}")
            proj_n += 1
    # EVERY CUT NAMES WHAT IT CUT, and these two are no exception. The names are the ROWS whose clause
    # was dropped, in the board's own rank order, with the remainder stated in words.
    if proj_cut:
        b.add(sb_absence("the effect windows of the rows past this tier's projection cut ("
                         + name_list(_named_rows(proj_cut, rank),
                                     int(cap.get("absence_names") or 0)) + ")", "render_cap"),
              label="projection render cap")
    if edge_cut:
        b.add(sb_absence("the declared links of the rows past this tier's link cut ("
                         + name_list(_named_rows(edge_cut, rank),
                                     int(cap.get("absence_names") or 0)) + ")", "render_cap"),
              label="edge render cap")

    # -- PHASE PAIRS: TWO NAMES, ONE READING (S6 review, major 17) ------------------------------------
    # THE DEFECT, MEASURED VERBATIM ON THE `el_nino_fanout` FIXTURE. The shipped graph puts `El_Nino`
    # and `La_Nina` on ONE global ref (`oni_lag_climate`: silver_noaa_oni / oni_lag6, declared global,
    # `country_rule` none, so no country or commodity narrowing exists) with OPPOSITE declared
    # signs, and `IOD_positive` / `IOD_negative` likewise on `iod_climate`. Loudness ranks |z| of the
    # UNSIGNED state and is phase-blind, so BOTH members land loud on the SAME reading -- and the block
    # printed "[N1] El Nino ... +0.98 degC ... declared to move CBOT soybeans in the OPPOSITE direction"
    # beside "[N4] La Nina ... +0.98 degC ... in the SAME direction": one number, two handle triples,
    # two contradictory signs, and nothing saying they are two phases of one series. The mandate's own
    # movement (1) then instructs the writer that "where the rows lean both ways, say so and name both
    # sides", so the writer would have reported ENSO as pointing both ways off a single reading.
    #
    # SEC 1.5's INVARIANT (one unsigned state, the sign on the edge) ASSUMES EACH DRIVER'S EDGE IS
    # APPLIED TO ITS OWN STATE. A mutually-exclusive phase pair breaks that assumption, and the fence
    # is CORRECTION rather than deletion (doctrine): both rows stay, both keep their handle and their
    # declared sign, and one letters-only row states the relation the reader cannot otherwise see.
    _phase: dict = {}
    for row in rendered:
        st = row.state
        if st is None or status_word(st.status) != "ok" or row.key not in handles_by_row:
            continue
        try:
            _phase.setdefault((row.contract, st.key.label()), []).append(row)
        except Exception:                               # noqa: BLE001 -- an unlabelled key groups alone
            continue
    for (_c, _k), _rows in sorted(_phase.items()):
        if len(_rows) < 2:
            continue
        _names = sorted({humanise(r.driver_id) for r in _rows})
        _signs = {str(r.sign or "") for r in _rows}
        b.add(sb_phase_pair(_names, board_label(_c), opposed=len(_signs) > 1),
              label=f"phase pair {_c}",
              display=f"the phase-pair reading on {board_label(_c)}")
        # THE COVERAGE INSTRUMENT MUST COUNT WHAT THE READER WAS TOLD (S7 fix pass). The line above says
        # these rows are ONE reading under two names, so they are ONE denominator entry -- see
        # `Block.join_rows` for the two measured artefacts that came of counting them as two.
        b.join_rows([handles_by_row[r.key] for r in _rows if r.key in handles_by_row], f"{_c}|{_k}")

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
        _ew = projection_window(row.event_date, row.lag_band)
        _eopen = event_window_open(_ew, bd.asof)
        b.add(sb_event(row, receipt_handle=e, published=rc.get("date") or row.event_date,
                       board=board_label(row.contract),
                       window=_ew, asof=bd.asof),
              label=f"event {row.driver_id}",
              display=f"the event row for {row_words(row.contract, row.driver_id)}",
              # AN OPEN WINDOW IS THE COVERAGE DENOMINATOR; a closed one is history and is not counted
              # against the writer (S7 item 1). `None` -- no window placed -- is neither.
              role=("event_open" if _eopen else ("event_closed" if _eopen is False else "event")),
              # THE EVENT'S OWN DATE PLUS ITS NAME, both in the reader's words. The `[E]` half is
              # DELIBERATELY NOT a token: until phase 3 a board-minted [E] is not in the turn's
              # evidence list (seam.py's declared residual), so scoring the handle would charge a
              # phase-3 gap to the writer.
              tokens=(_date_forms(row.event_date), _name_words(humanise(row.driver_id))))
        if rc.get("date"):
            b.add(sb_receipt(e, int(rc.get("tier") or 3), rc, driver_id=row.driver_id),
                  label=f"event receipt {row.driver_id}",
                  display=f"the event document for {row_words(row.contract, row.driver_id)}")

    # -- PATHS (capped by the walk's own `path_render_k`, which stamped `rendered` per path) ----------
    for p in bd.paths:
        if not p.get("rendered"):
            continue
        hs = [handles_by_row[(p["contract"], h)] for h in p["hops"]
              if (p["contract"], h) in handles_by_row]
        b.add(sb_path(p, anchor=p["contract"], handles=hs), label=f"path {p['ancestor']}",
              display=f"the upstream path into {board_label(p['contract'])}")

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
    far_rendered: list = []                 # the CROSS edges that reached the reader with their own row
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
        b.add(sb_fan(e, names_cap=int(cap.get("fan_names") or 0)), label=f"fan {e['driver_id']}",
              display=f"the spillover index for {humanise(e['driver_id'])}")
        spill += 1
        for f in far_named[:far_per_entry]:
            if spill >= int(cap["spillover"]):
                cut_boards.append(f["contract"])
                continue
            # A CROSS EDGE IS ONE WHOSE FAR BOARD IS NOT THE SEED'S OWN. The fan index carries same-board
            # entries too (a driver declared on this board under another name), and those are not a
            # spillover -- licensing a cross-commodity heading off one would put this board's own rows
            # under a heading about other markets.
            #
            # AND THE ROLE CARRIES THE SAME SPLIT, so the coverage denominator and the licence count ONE
            # population under one word. The first cut stamped every far row `far` while the licence
            # named only the cross ones, which is two numbers about "spillovers" that can disagree on
            # any board carrying a same-board fan entry (none of the three fixtures does, which is
            # exactly why it had to be closed by construction rather than by observation).
            _cross = str(f["contract"]) != str(e["contract"])
            b.add(sb_edge(seed, far=f), label=f"far {f['contract']}/{f['driver_id']}",
                  display=f"the spillover link for {row_words(f['contract'], f['driver_id'])}",
                  role=("far" if _cross else "far_same_board"),
                  tokens=(_market_words(f["contract"]),))
            spill += 1
            if _cross:
                far_rendered.append(str(f["contract"]))
        cut_boards.extend(f["contract"] for f in far_named[far_per_entry:])
    if cut_boards:
        b.add(sb_absence("the far boards past this tier's spillover cut ("
                         + ", ".join(sorted({board_label(c) for c in cut_boards})) + ")", "fan_cap"),
              label="fan render cap")
    # -- THE SPILLOVER LICENCE (S7 item 2) -------------------------------------------------------------
    # MINTED IFF THE FAR ROWS ARE ACTUALLY THERE, and it closes the section they are in rather than
    # opening it -- the reader meets the rows, then the line that says where they belong. See
    # `sb_cross_commodity` for why this exists at all and `SB_CROSS_COMMODITY_PREFIX` for the
    # measurement: without it, SPILLOVERS has no heading and falls into `## Mechanism`, which carried
    # 1 of 239 first-cited handles across the twelve banked turns.
    if far_rendered:
        b.add(sb_cross_commodity(sorted({board_label(c) for c in far_rendered}),
                                 anchor=anchor_label or ", ".join(board_label(s)
                                                                  for s in bd.anchor_slugs)),
              label="cross-commodity licence", display="the spillover licence",
              role="spillover_licence")

    # -- CONVERGENCE ----------------------------------------------------------------------------------
    # THE CAP COUNTS PATTERNS, AND A RENDERED PATTERN KEEPS ITS AMPLIFIER SUB-LINES. Counting both
    # against one budget was the first cut, and it MEASURED wrong on scenario 3: three amplifiers under
    # the earlier patterns exhausted the cap and `biodiesel_energy_floor`'s own
    # `(crude_oil_price, biodiesel_mandate) amplifies` line -- the scenario's whole convexity material,
    # and bar B16's fixture -- was the row that fell off. An amplifier is a SUB-LINE of a row already
    # admitted, digit-free, and bounded by the pattern count it hangs under.
    conv, conv_cut = 0, []
    for c in bd.convergence:
        if conv >= int(cap["convergence"]):
            conv_cut.append(c)
            continue
        b.add(sb_convergence(c), label=f"pattern {c['name']}",
              display=f"the pattern row for {pattern_label(c['name'])} on "
                      f"{board_label(c['contract'])}")
        conv += 1
        for it in c["interactions"]:
            if it.get("rendered"):
                b.add(sb_amplifier(c["contract"], it), label=f"amplifier {c['name']}",
                      display=f"the amplifier under {pattern_label(c['name'])} on "
                              f"{board_label(c['contract'])}")
    # THE THIRD SILENT CUT, SWEPT AT S6 with the two the sitting was sent for. It was a `break`, so a
    # pattern past the cap left no row, no name and no word -- the same shape the analog-outcome cut
    # had at the S3 re-fix. The names are the PATTERN LABELS, which is what a reader can look up.
    if conv_cut:
        b.add(sb_absence("the convergence patterns past this tier's pattern cut ("
                         + ", ".join(sorted({pattern_label(str(c["name"])) for c in conv_cut}))
                         + ")", "render_cap"),
              label="convergence render cap")

    # -- TAPE -----------------------------------------------------------------------------------------
    for slug in bd.anchor_slugs:
        tp = bd.tape.get(slug)
        if tp is None:
            continue
        if status_word(tp.status) != "ok":
            b.add(sb_absence(f"{board_label(slug)} price path", tp.status), label=f"tape {slug}",
                  display=f"the price path of {board_label(slug)}")
            continue
        line, calls = sb_tape(b.next_handle, tp, asof=bd.asof)
        b.add(line, calls, label=f"tape {slug}",
              display=f"the price path of {board_label(slug)}")

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
        b.add(sb_analog_header(a), label=f"analog {a['driver_id']}",
              display=f"the like state for {row_words(a['contract'], a['driver_id'])}")
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
            # THE CARD'S SCALE, so an outcome read on a DRIVER'S own series prints on the same scale as
            # the SB-1 row above it (S7 polish (b)). A benchmark has no card and stays native.
            line, calls = sb_analog_outcome(b.next_handle, o, asof=bd.asof,
                                            scale=_outcome_scale(o, _scales))
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
        _arc = list(a.get("receipts") or ())
        for rc in _arc[: int(cap["receipts"])]:
            b.add(sb_receipt(b.take_e(), rc.get("t", 3), rc, driver_id=a["driver_id"]),
                  label="analog receipt")
        if len(_arc) > int(cap["receipts"]):
            # THE FOURTH SILENT CUT IN THIS FUNCTION, swept by the S6 review after the first three.
            # A stanza's receipts past the tier's cap were dropped with no row, while the branch
            # immediately below names only the ZERO-receipt case -- so a reader met a stanza carrying
            # three documents and could not tell whether the corpus held three or thirty. The names are
            # the STANZA's, never the documents': a document title is retrieved text and this class is
            # letters-only.
            b.add(sb_absence(f"the further documents on this like state past this tier's receipt cut "
                             f"({humanise(a['driver_id'])} on {board_label(a['contract'])})",
                             "render_cap"),
                  label="analog receipt render cap")
        if not _arc:
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
                             ((a["contract"], a["driver_id"]) for a in fired[len(shown_analogs):]),
                             rank))
                         + ")", "render_cap"),
              label="analog render cap")
    for word in sorted({str(a["declined"]) for a in analogs if a.get("declined")}):
        b.add(sb_absence("a like state on this board", word), label="analog absence")

    # -- RECEIPTS on the loud rows ---------------------------------------------------------------------
    # EVERY CUT NAMES WHAT IT CUT (S6, the first of the two cuts this sitting swept). The receipts past
    # the tier's cap were dropped with no row: a reader met a loud driver carrying two documents and
    # could not tell whether the corpus held two or twenty, which is the absence-versus-silence
    # confusion the whole block is built to prevent. The names are the ROWS the receipts hang under,
    # never the documents themselves -- a document title is retrieved text and is not this block's to
    # print in a letters-only class.
    rcpt_cut = []
    for key, rs in sorted((receipts_by_row or {}).items()):
        for r in rs[: int(cap["receipts"])]:
            b.add(sb_receipt(b.take_e(), r.get("tier", 3), r, driver_id=key[1]), label="receipt",
                  display=f"a document on {row_words(key[0], key[1])}")
        if len(rs) > int(cap["receipts"]):
            rcpt_cut.append(key)
    if rcpt_cut:
        b.add(sb_absence("the further documents on the rows past this tier's receipt cut ("
                         + ", ".join(_named_rows(rcpt_cut, rank)) + ")", "render_cap"),
              label="receipt render cap")

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
            # THE KIND-2 WATCH ROW IS ON THE HANDLE SURFACE (SB-V) AND STILL A WATCH ROW. It carries
            # both: its distance figure is bound to its own [N], so `board_coverage` reads it through
            # the same value matcher as every other figure -- and it counts in `watch_referenced`,
            # because the mandate's fourth movement asks for the WATCH rows and does not except this one.
            b.add(line, calls, label=f"watch {w['kind']}", role="watch",
                  tokens=_watch_tokens(w))
            continue
        b.add(sb_watch(w), label=f"watch {w['kind']}", role="watch", tokens=_watch_tokens(w))

    # -- RECENCY ---------------------------------------------------------------------------------------
    for layer, text in (recency or {}).items():
        # THE RECENCY ROW'S REFERENCE TEST IS ITS DATE **AND** ITS LAYER WORD, in ONE sentence -- the
        # `_slot_geo_mismatch` discipline (comparisons, never attempts) applied to a letters-only row.
        # A date alone would pass on any answer that dated one number row by its knowledge date, which
        # is a DIFFERENT rule (the EVIDENCE movement's) and is exactly what the prod-seat smoke saw:
        # rows dated correctly, and 0 of 9 RECENCY rows stated as a fact about their own layer.
        b.add(sb_recency(layer, text), label=f"recency {layer}", role="recency",
              tokens=_recency_tokens(layer, text))

    # -- ABSENCES, GROUPED BY REASON WORD, every name listed --------------------------------------------
    groups: dict = {}
    for row in bd.rows:
        st = row.state
        if st is not None and status_word(st.status) == "ok":
            continue
        reason = (status_word(st.status) if st is not None
                  else {"declared_available_unserved": "unmapped_ref",
                        "planned_text_only": "series_planned"}.get(row.coverage_tier, "series_none"))
        groups.setdefault(reason, []).append(row.key)
    _abs_cap = int(cap.get("absence") or 0)
    _nm_cap = int(cap.get("absence_names") or 0)
    # THE GROUPS RENDER IN THE VOCABULARY'S OWN DECLARATION ORDER, NOT ALPHABETICALLY -- **ON THE TIER
    # THAT CUTS THEM, AND ONLY THERE** (S7, scoped in round 2). `sorted()` is harmless while every group
    # prints; the moment `render_absence` cuts one it decides which ABSENCE WORDS a Scan reader meets --
    # and alphabetically that is "budget_cap, history_truncated, outlook_lane" ahead of
    # "scope_unresolved, unmapped_ref, series_planned", i.e. the incidental reasons ahead of the three
    # that say the estate has no series at all. `state/board.py`'s closed enums are declared in the
    # order the design states them (SERIES_ then EDGE_ then FAN_ / PATH_ / CONV_ / TAPE_ / ANALOG_ /
    # WATCH_ / RENDER_ / BOARD_), so the declaration IS the ranking and no second table is invented
    # here. A word outside every enum sorts last, alphabetically, and still renders.
    # Scan is the only tier with `render_absence` set, so deep and max print every group either way and
    # keep HEAD's lexical order byte for byte -- the control arm A is read against.
    _reasons = sorted(groups, key=_reason_rank) if rank is not None else sorted(groups)
    _abs_shown = _reasons[:_abs_cap] if _abs_cap else _reasons
    for reason in _abs_shown:
        b.add(sb_absence(name_list(_named_rows(groups[reason], rank), _nm_cap), reason),
              label=f"absence {reason}")
    if len(_reasons) > len(_abs_shown):
        # The absence GROUPS are themselves cappable at S6 (`render_absence`, 0 = uncapped on deep and
        # max; Scan takes THREE at S7), and a capped group list names the rows it did not print for the
        # same reason every other cut does. IT ALSO NAMES THE WORDS, because a reason word is the whole
        # content of an absence row: dropping the group and then not saying which reasons were dropped
        # would tell the reader that rows are missing and hide WHY, which is the silence this class
        # exists to refuse.
        # THE CUT REASONS RIDE AS THEIR OWN SENTENCES, never as their closed WORDS: a reason word is a
        # code token and `ABSENCE_FALLBACK`'s note is explicit that a reader must never meet one. Folding
        # N group LINES into one line plus N short clauses is a correction; dropping the reasons and
        # keeping only the names would be a deletion, and this class is the one that exists to refuse
        # exactly that.
        _cut_why = "; ".join(dict.fromkeys(absence_why(r) for r in _reasons[len(_abs_shown):]))
        b.add(sb_absence(f"the further rows this board carries no reading for, because {_cut_why} ("
                         + name_list(_named_rows((k for r in _reasons[len(_abs_shown):]
                                                  for k in groups[r]), rank), _nm_cap) + ")",
                         "render_cap"),
              label="absence render cap")
    # -- THE SECOND OF THE TWO CUTS S6 SWEPT: A ROW THAT WAS READ AND DID NOT MAKE THE LOUD CUT --------
    # It is the sharpest of the silent ones, because it is an absence of a FACT rather than of a gap:
    # the group above names every row with NO reading, and `loud_only` then dropped every row that HAS
    # one and ranked below `loud_k` -- so a reader met a board whose quiet rows were indistinguishable
    # from rows that do not exist. The design's own words are "the loud set, the render caps and the
    # budget decide what is SAID; nothing decides what EXISTS", and a cut that says nothing decides
    # existence for the reader. `loud_only=False` renders them all and this line is then empty.
    _shown_keys = {r.key for r in rendered}
    _quiet = [r for r in bd.rows
              if r.state is not None and status_word(r.state.status) == "ok"
              and r.key not in _shown_keys]
    if _quiet:
        b.add(sb_absence("the rows this board read that sit below this tier's loudness cut ("
                         + name_list(_named_rows((r.key for r in _quiet), rank), _nm_cap) + ")",
                         "render_cap"),
              label="loudness render cap")
    # EVERY CUT NAMES WHAT IT CUT, and until this edit four of them said "named above" while naming
    # the rows NOWHERE -- against sec 3.8's own law ("the tail it cannot afford is NAMED") and B3's
    # "NAMED deferrals equal in count to declared - read". The fan render cap always did it right; these
    # follow it, and the closed sentences behind them now say "named here" because that is where the
    # names are.
    for note in bd.notes:
        if note.get("kind") == "budget_cap":
            named = _named_rows(note.get("pairs") or (), rank)
            b.add(sb_absence("the keys this turn's budget did not reach"
                             + (" (" + name_list(named, _nm_cap) + ")" if named else ""),
                             "budget_cap"),
                  label="budget cap")
        elif note.get("kind") == "path_render_cap":
            named = sorted({humanise(x) for x in (note.get("names") or ())})
            b.add(sb_absence("the upstream paths past this tier's render cut"
                             + (" (" + name_list(named, _nm_cap) + ")" if named else ""),
                             "render_cap"),
                  label="path render cap")
        elif note.get("kind") == "anchor_cap":
            # THE ANCHOR CEILING (S6 review, major 1 / 9 / 12 / 13). Every other cut on this board is
            # about a ROW; this one is about a BOARD, and it is the one the design left unbounded --
            # `resolve_anchors` bounds inferred seeds alone, so a `focus_driver` gesture put 35 DAGs,
            # their whole read budget, their serial tape column and 916 rendered rows on one turn. The
            # cut takes the anchor PRECEDENCE's own order, so a named market outranks a driver's
            # twenty-ninth board, and it names what it dropped like every other cut here.
            named = sorted({board_label(x) for x in (note.get("names") or ())})
            b.add(sb_absence("the further boards carrying this question's anchor, past this tier's "
                             "anchor cut"
                             + (" (" + name_list(named, _nm_cap) + ")" if named else ""),
                             "render_cap"),
                  label="anchor cap")
        elif note.get("kind") == "tape_cap":
            named = sorted({board_label(x) for x in (note.get("names") or ())})
            b.add(sb_absence("the price paths of the anchor boards past this turn's tape seats"
                             + (" (" + name_list(named, _nm_cap) + ")" if named else ""),
                             "budget_cap"),
                  label="tape cap")
        elif note.get("kind") == "fan_states_unread":
            named = _named_rows(note.get("names") or (), rank)
            b.add(sb_absence("the far states of the rows past this tier's cut"
                             + (" (" + name_list(named, _nm_cap) + ")" if named else ""), "fan_cap"),
                  label="fan states unread")
        elif note.get("kind") == "edge_hop_cap":
            b.add(sb_absence("the link direction this tier does not walk", "edge_hop_cap"),
                  label="edge hop cap")
        elif note.get("kind") == "subject_ambiguous":
            # THE CARRIED AMBIGUITY (SUBJECT RESOLVER D5), AND IT IS THE ONE NOTE THAT IS NOT A CUT.
            # Every other branch above names rows or boards a ceiling dropped; this one names a
            # question the estate could not read -- two drivers a typed phrase could mean, which the
            # planner declined to choose between. The note was appended by `seam._stamp_subject` and
            # had NO branch here at all, so the row `sb_subject_ambiguous` exists to mint reached no
            # reader on any turn: the stamp fired, the counter incremented, the trace carried both ids,
            # and the block said nothing. That is the silent-decline class this board's whole closed
            # decline vocabulary exists to close, so it is consumed here beside every other note.
            b.add(sb_subject_ambiguous(note.get("ids") or ()), label="subject ambiguous")
    # THE COVERAGE MANIFEST RIDES THE BOARD (S7 item 1). It is stamped HERE and by nothing else,
    # because this function is the only place that knows which rows a reader actually met -- after
    # every cap, every fence correction and every weld. `Board.coverage` is filled later, at the answer
    # seam, once there is a draft to read it against; this is the half that cannot be recomputed then.
    try:
        bd.rendered_rows = tuple(dict(m) for m in b.rows_meta)
    except Exception:                       # noqa: BLE001 -- a board must never break on its own telemetry
        pass
    return b


def _named_rows(pairs, order=None) -> list:
    """``(contract, driver_id)`` pairs as reader words. ONE producer for every cut line's name list, so
    a named tail can never reach a reader as a raw id (``register.internal_leaks``, :836).

    ``order`` IS THE BOARD'S OWN RANK AND IT IS WHAT DECIDES WHICH NAMES SURVIVE A CAP (S7). Until this
    sitting the return was a bare ``sorted(out)`` -- LEXICAL -- and that was harmless while every list
    was printed whole. It stops being harmless the moment :func:`name_list` cuts one: an alphabetical
    cut hands the reader the rows whose display labels happen to sort first and drops the board's
    loudest, which is the opposite of the ordering every other cut on this page takes. The rank is
    ``Board.order``'s own index, the same tuple ``render_board`` sorts its state rows by; a pair the
    rank does not carry sorts after every ranked one and then alphabetically, so the output stays
    deterministic on a board that ranked nothing.

    Sorting LEXICALLY remains the behaviour when no rank is supplied, because a caller with no board --
    a deck, a fixture, a name list assembled from a note -- has no rank to offer and a stable order is
    still owed.

    **S8 DOCKET -- THE LEXICAL ORDER ON DEEP AND MAX IS A DEFECT THAT IS NOT FIXED HERE.** Round 2 of S7
    scoped the rank to the QUICK tier alone (:func:`rank_cuts`), so deep and max still write every cut
    line's name list alphabetically: an analog stanza cut, a receipt cut, a loudness cut and the two
    walk notes on those tiers hand the reader the rows whose display labels sort first rather than the
    board's loudest. That is the SAME defect this rank was written to close, and it is left standing
    ON PURPOSE and for one measured reason: deep and max are arm A's control cells, the owner's
    ratified rule of 09-10 is that they run as S6 shipped them, and an ordering change inside a control
    is a second flag in a one-flag experiment. Arm A measures deep and max as S6 shipped them; S8 takes
    the rank to the paid tiers once the judged delta has been read."""
    seen: dict = {}
    for p in pairs or ():
        try:
            c, d = p
        except (TypeError, ValueError):
            continue
        words = f"{humanise(d)} on {board_label(c)}"
        rank = 0 if order is None else int(order.get((c, d), len(order)))
        # THE BEST RANK WINS a duplicate name: two pairs can fold to one display string (the same
        # driver on two slugs that share a label), and the louder of the two is the one the reader met.
        if words not in seen or rank < seen[words]:
            seen[words] = rank
    if order is None:
        return sorted(seen)
    return sorted(seen, key=lambda w: (seen[w], w))


#: The count words a capped name list closes with. LETTERS, never a digit: an absence row is a
#: letters-only class, and a bare integer inside one would give `verify._claim_number_spans` a
#: magnitude to bind on a line that backs no figure.
_COUNT_WORDS: tuple = (
    "no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven",
    "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen",
    "twenty",
)


def count_words(n: int) -> str:
    """A small count in WORDS, or "many" past the table. The board's own count-word idiom, in one
    place: the mandate tells the writer that base rates come from the block's count words, so a count
    the block prints as a digit is a magnitude a writer may copy without a handle."""
    n = max(0, int(n))
    return _COUNT_WORDS[n] if n < len(_COUNT_WORDS) else "many"


def name_list(names, cap: int = 0, noun: str = "rows") -> str:
    """A cut's name list, bounded by ``cap`` (0 = uncapped) and CLOSING WITH THE REMAINDER IN WORDS.

    ``noun`` IS WHAT THE REMAINDER COUNTS, and it exists because S7 routes the FAN INDEX through this
    producer too: an SB-F index enumerates BOARDS, and "three further rows this line does not name" on a
    line whose subject is other markets would misname the population it just cut. One producer, one
    remainder sentence, the noun supplied by the caller that knows what it is listing.

    S6 REVIEW, MAJOR 12: every render cap in this module bounds ROWS, and the class that overran
    hardest overran INSIDE one row. MEASURED on a `focus_driver` Scan turn through the seam: one `BOARD
    ABSENCE` line of 23,871 characters, in a block of 171,852 -- against sec 7's ~1,100-token Scan
    budget, on the free tier. The names were never cut because "the NAMES are never cut" (sec 3.6), but
    that sentence is about the FAN INDEX, and a free index is not a free enumeration inside a line.

    THE REMAINDER IS STATED, so the row still says what it cut -- the whole law this sitting swept four
    other cuts to keep. It is stated in WORDS for the reason every count on this board is: the mandate
    licenses the writer to take base rates from the block's count words, and a digit here would be a
    magnitude with no handle behind it."""
    names = list(names or ())
    cap = max(0, int(cap or 0))
    if not cap or len(names) <= cap:
        return ", ".join(names)
    rest = len(names) - cap
    # NUMBER AGREEMENT (S7 round-2 review): a remainder of one takes the singular noun -- 'one further
    # board', never 'one further boards'; the callers pass the plural ('boards', 'rows').
    noun_agreed = noun[:-1] if rest == 1 and noun.endswith("s") else noun
    return (", ".join(names[:cap])
            + f", and {count_words(rest)} further {noun_agreed} this line does not name")



def _anchor_words(st, anchor_date: str) -> str:
    """WHAT THE PROJECTION IS COUNTED FROM, in words -- and the row prints WHICH anchor it used (sec
    3.7). A run's start and a level's date are two different claims about the same series.

    **IT NEVER EMITS A SENTENCE WITH AN EMPTY ANCHOR** (S7 polish (a)). :func:`month_words` now knows
    the bare-year and the ``YYYY-MM`` forms, which closes every form the shipped cards actually write;
    a date this function still cannot place is DECLINED IN WORDS rather than interpolated as nothing.
    "counted from , the effect window opens around December 2024" is a fence that deleted half a clause
    and left the comma -- correct or compute, never delete."""
    words = month_words(anchor_date)
    if not words:
        return "an anchor this card dates by no calendar period this board can place"
    since = (st.run or {}).get("since_date") if (st.run and not st.run.get("declined")) else None
    if since and str(since)[:10] == str(anchor_date)[:10]:
        return f"the run's start in {words}"
    return f"this reading's own date in {words}"


# ---------------------------------------------------------------------------------------------------
# THE COVERAGE INSTRUMENT (S7 item 1) -- A COUNTER, NEVER A FENCE
# ---------------------------------------------------------------------------------------------------
#: The roles whose rows carry a magnitude bound to their own ``[N]``. Every other role is letters-only
#: and is graded on its token groups instead.
_HANDLE_ROLES: frozenset = frozenset({"state", "watch"})

#: THE VERDICT LATTICE, best first. A JOINED denominator entry takes its BEST member's verdict, because
#: the join says the two rows are ONE reading under two names and the mandate tells the writer to give
#: one side and never two -- so a writer that folded them correctly must not be charged for the twin.
_VERDICT_RANK: dict = {"cited": 3, "figure": 2, "tokens": 1, "": 0}


def _best_verdict(a, b):
    """The stronger of two verdicts. ``None`` (UNTESTABLE) loses to every real verdict and wins only
    against another ``None`` -- a group is untestable only when every member of it is."""
    if a is None:
        return b
    if b is None:
        return a
    return a if _VERDICT_RANK.get(a, 0) >= _VERDICT_RANK.get(b, 0) else b


def _row_figures(handles, calls, n_start: int) -> list:
    """The magnitudes a row's own handles were minted with -- ``verify._mismatch_pool``'s pool, read
    from the board's own call records rather than re-parsed off the rendered line.

    ``calls`` IS THE BOARD'S OWN LIST and ``n_start`` is the handle its first call took, so
    ``handle - n_start`` is the index. The board's calls are a CONTIGUOUS ``[N]`` prefix by
    construction (``quantify`` appends them before its base wave), which is what makes this join an
    index rather than a guess -- the G2 gap, answered by arithmetic and said so.

    THE LOOSE READ PASSES ONLY THE ROW'S FIRST HANDLE (see :func:`board_coverage`). This function
    still reads every handle it is given, because a caller wanting the whole pool -- a deck, a census
    -- is asking a different question than the coverage verdict is."""
    from leviathan.graphrag import verify as _vf
    out: list = []
    for h in handles or ():
        i = int(h) - int(n_start)
        if 0 <= i < len(calls or ()):
            out.extend(_vf.row_pool(calls[i]))
    return out


#: THE C FOLD's window, in sentences. **IT STAYS AT ONE, AND THAT IS A MEASURED REFUSAL** (S7).
#:
#: THE FOLD WAS SPECIFIED, BUILT AND RE-SCORED ON THE BANKED PROD-SEAT DRAWS, AND ITS OWN FALSIFIER
#: KILLED IT. The case for widening to an adjacent PAIR was the ``b40_event`` open-event row, which
#: scores 0 of 1 on an answer that states the event date in its first sentence and names the mandate in
#: the next section. Re-scored at two:
#:
#:   * the event row STILL missed -- measured, the date sentence is s0 and the nearest ``mandate``
#:     sentence is s2 (the tldr's second half sits between them), so it needs THREE, which is no longer
#:     a claim about one statement at all;
#:   * ``watch_referenced`` rose 7 -> 9 of 22 on the S6b draws AND 7 -> 9 on the S6 baseline, and the
#:     three rows it gained are all cross-row bleed: two are the El Nino / La Nina watch rows on
#:     ``el_nino_fanout``, whose date (2026-08-31) is the STATE row's own level date, so the window
#:     scored them off a sentence about a different row -- false positive (c) in :func:`board_coverage`'s
#:     own list, reintroduced; the third glues two separate ``## What to watch`` BULLETS together, and
#:     two bullets are two claims;
#:   * it broke the ceiling bar. The human read of the same three answers found 7 of 22 watch rows used.
#:     An instrument that scores 9 where a human reading scores 7 is over-claiming, and the direction of
#:     this instrument's error must stay UNDER-claim.
#:
#: A whole-answer scan is what the first cut of this instrument did and it SATURATED -- 38 of 38 loud
#: rows referenced on three draws whose own human read found fourteen never used. One sentence is where
#: it stays until an answer set says otherwise. The parameter remains because the experiment must be
#: re-runnable at the arm without another edit.
_TOKEN_WINDOW_SENTS = 1


@lru_cache(maxsize=8192)
def _token_rx(token: str):
    """ONE TOKEN AS A WORD-BOUNDED PATTERN, cached because the same handful of tokens is tested against
    every sentence of every answer.

    **THE BARE SUBSTRING TEST OVER-CLAIMED, AND IT OVER-CLAIMED ON DATES** (S7 round 2). ``_date_forms``
    mints ``1 May 2026`` for a row dated ``2026-05-01``, and ``"1 may 2026" in low`` is TRUE of a
    sentence that says **11 May 2026**, **21 May 2026** or **31 May 2026** -- three other days, three
    other claims, one scored hit. The same hole runs the other way through :func:`_name_words`, whose
    one-word relaxation admits ``stocks``: a sentence about **restocking** satisfied a row keyed on
    ending stocks. Both are false positives of exactly the kind :func:`board_coverage`'s own list was
    written against, and the direction of this instrument's error must stay UNDER-claim.

    THE BOUNDARY IS ALPHANUMERIC AND IS APPLIED ONLY WHERE THE TOKEN ITSELF IS. ``\\b`` would be wrong
    at both ends of a token like ``2026-05-01`` inside ``(2026-05-01)``; a lookaround for an adjacent
    letter-or-digit is the claim actually wanted -- "this token is not a fragment of a longer word or
    number". A token that begins or ends in punctuation keeps that end open, because there is nothing
    there to fragment.

    A TRAILING PLURAL ``s`` IS STILL ADMITTED ON A TOKEN THAT ENDS IN A LETTER, and that is a
    deliberate hold rather than an oversight: the layer words are phrases like ``price tape`` and the
    name words are labels like ``ending stocks``, both of which an ordinary sentence pluralises, and
    every one of those hits was already scored under the substring test. Tightening the boundary is a
    correction of a false POSITIVE; dropping the plural would be a new false NEGATIVE in the same edit,
    and one measured change at a time is what makes the arm's counters readable. Dates end in a DIGIT,
    so the fold the defect lives in is untouched by it."""
    t = str(token or "").strip().lower()
    if not t:
        return None
    head = r"(?<![0-9a-z])" if t[0].isalnum() else ""
    tail = (r"s?(?![0-9a-z])" if t[-1].isalpha()
            else (r"(?![0-9a-z])" if t[-1].isdigit() else ""))
    return re.compile(head + re.escape(t) + tail)


def _token_hit(token: str, low: str) -> bool:
    """One token against one lower-cased window. A token that compiles to nothing never matches."""
    rx = _token_rx(str(token or "").lower())
    return bool(rx and rx.search(low))


def _tokens_referenced(groups, sents, *, window: int = _TOKEN_WINDOW_SENTS) -> bool:
    """A WINDOW OF ``window`` ADJACENT SENTENCES carries at least one member of EVERY group, EACH
    MATCHED ON WORD BOUNDARIES (:func:`_token_rx`). No groups == untestable, and the caller keeps an
    untestable row out of the denominator rather than reading it as a no.

    THE WINDOW SLIDES AND DOES NOT POOL: sentences 1-2 and 2-3 are each tested whole, and a match must
    fall inside ONE window. ``verify._SENT_SPLIT`` is the splitter the caller already used -- one
    splitter in the estate -- so this function widens the window and invents no second boundary."""
    if not groups:
        return False
    sents = list(sents or ())
    n = max(1, int(window or 1))
    for i in range(len(sents)):
        low = " ".join(sents[i:i + n]).lower()
        if all(any(_token_hit(t, low) for t in g) for g in groups):
            return True
    return False


def _row_id(i: int, m: dict) -> str:
    """A MISSED row's id: its handle when it has one, else its class and its index in the block.

    A ROW WITHOUT A HANDLE STILL NEEDS A NAME -- four fifths of this block has no handle, and a miss
    list that could only name the fifth that does would be a miss list about the wrong problem."""
    hs = tuple(m.get("handles") or ())
    if hs:
        return "N%d" % int(hs[0])
    return "%s@%d" % (m.get("cls") or "row", int(i))


def board_coverage(bd, prose: str, *, n_start: int = 1, loud_k=None, calls=None) -> dict:
    """WHAT THE WRITER DID WITH THE BOARD, counted against the rendered block. A COUNTER, NEVER A FENCE.

    THE (1b) LESSON IS BINDING, AND IT IS WHY THIS RETURNS NUMBERS AND CHANGES NOTHING. The D-HP
    fixture replay caught out-of-range ``[N]`` 1054 of 1054 and MISSED wrong-but-valid ``[N]`` 217 of
    1054 (79.4%) and wrong-but-real ``[E]`` 791 of 791 (100%): counting handles is not checking
    bindings. "The writer referenced nine board rows" says nothing about whether it referenced the
    RIGHT nine, so the FENCE stays the shipped value check (``verify._check_number_handle``), which
    already binds every board figure with no new class, and this is an INSTRUMENT for the arm. Nothing
    here can strip a sentence, drop a row or decline a leg.

    TWO SURFACES, because four fifths of the block carries no handle at all -- measured at 14 of 83
    rendered lines and 20.2% of the characters on the banked board census.

      * THE HANDLE SURFACE (``state`` rows and the kind-2 ``watch`` row): REFERENCED when its ``[N]``
        is cited, or -- the LOOSE read -- when its OWN LEVEL magnitude appears in a sentence BOUND to
        it, within ``verify._num_matches`` tolerance (the estate's matcher, imported, never a second
        one). Both qualifiers are load-bearing and both were added after the first cut MEASURED
        saturated: see THE THREE FALSE POSITIVES below.
      * THE LETTERS SURFACE (``far`` rows, ``recency`` rows, the unhandled ``watch`` rows, open
        ``event`` rows): REFERENCED when ONE prose sentence carries at least one member of every token
        group the render minted for that row. ``verify._SENT_SPLIT`` is the sentence boundary, for the
        same reason: one splitter in the estate.

    THE THREE FALSE POSITIVES THAT SHAPED THE LOOSE READ, each reproduced on a banked prod-seat draw.
    The first cut ran ``figure_referenced`` over EVERY sentence of the whole answer against the pool of
    ALL THREE handles a state row mints, and scored 38 of 38 loud rows REFERENCED on three draws whose
    own human read found fourteen loud rows never used. The controls said the same thing from the other
    side: strip every ``[N]`` and multiply every magnitude by 1.37 -- so no board number is present at
    any scale -- and the read still returned 10/12, 9/12 and 8/14; a bare number-soup with no words at
    all returned 12/12, 12/12 and 14/14; and each board scored 12/12 or 14/14 against the OTHER
    scenarios' answers. A numerator that survives its own falsifier is not a numerator.

      (a) A JOIN TWIN IS THE SAME SERIES. ``El Nino`` and ``La Nina`` sit on one ONI reading under two
          names, so they share one ``shown`` pool and a sentence about one scored BOTH. The mandate
          tells the writer to give ONE side and never two, so the twin the writer correctly folded was
          a GUARANTEED false positive -- twelve of the fourteen uncited loud rows were exactly that.
          FIXED BY FOLDING: a ``join`` group is ONE denominator entry taking its best member's verdict.
      (b) SIGMA AND PERCENTILE ARE DIMENSIONLESS AND COLLIDE ACROSS EVERY ROW. ``-0.9 sigma`` on an
          export-tax row was matched by the crush row's ``+0.9 sigma`` (``_num_matches`` is
          sign-insensitive and scale-bridging); a percentile hits any two-digit token on the page.
          FIXED BY POOLING ONLY THE ROW'S FIRST HANDLE -- the LEVEL for a state row, the distance for
          the kind-2 watch row -- which is the one magnitude carrying the row's own unit.
      (c) A SENTENCE THAT CITES ANOTHER ROW IS NOT EVIDENCE FOR THIS ONE. A flash-drought row was
          scored referenced by a sentence about reporting-fund length that cited ``[N26]`` and
          ``[N27]``. FIXED BY BINDING: a value match counts only in a sentence that carries this row's
          OWN handle or carries no board handle at all -- the ``audit2.py`` adjacency idiom the smoke
          pass already built, stated as a rule.

    EVEN SO, ``*_cited`` IS THE INFORMATIVE HALF AND A READER SHOULD LEAD WITH IT. The loose read is
    reported separately (``*_figure_only``) and never blended into the tight one.

    THE DENOMINATORS ARE COMPARISONS, NEVER ATTEMPTS (``answer._slot_geo_mismatch``'s discipline). A
    row with no testable surface -- a recency layer this turn carries nothing for -- is UNTESTABLE and
    leaves the denominator, because a coverage figure that charged the writer for a fact nobody served
    would be measuring the board rather than the use of it.

    THE OPEN-EVENT DENOMINATOR IS OPEN EVENTS ONLY. A closed window is history and the mandate asks
    nothing of it; ``events_open`` counts the rows whose window is still open at the as-of, through the
    one producer both consumers read (:func:`event_window_open`).

    ``prose`` MUST BE THE POST-VERIFY ``structured`` BODY and never ``out['answer']``: the
    ``## Sources`` footer re-renders every ledgered ``[N]`` INCLUDING the ones the verifier just
    stripped, so a scan of the rendered page false-passes on fabrications -- eval.py's primary-gate
    trap, stated at its own :423-426."""
    from leviathan.graphrag import verify as _vf
    rows = list(getattr(bd, "rendered_rows", ()) or ())
    # ABSENT IS NEVER ZERO, AND THIS IS THE FUNCTION WRITTEN TO HONOUR IT. A board that rendered no row
    # has nothing to have used, so it returns NOTHING rather than a truthy all-zero dict: `Board.trace`
    # then omits the key (its own docstring's promise) and `eval._judge_state_panel` renders no panel,
    # so the judge is never asked to score `state_use` on a turn whose board put no row on the page.
    # THE PATH IS LIVE, not hypothetical: `seam.fill_stage2`'s SUBJECT RESOLVER ambiguity branch ships a
    # one-line block WITHOUT calling `render_board`, so `_sb['block']` is truthy and `rendered_rows` is
    # still empty -- a fabricated 0-of-0 inside the arm's own new dimension.
    if not rows:
        return {}
    text = str(prose or "")
    sents = _vf.sentences(text)
    cited = _vf.cited_number_handles(text)
    # ``calls`` DEFAULTS TO THE BOARD'S OWN LIST, which the SEAM writes (`bd.calls = calls`) right
    # after the render. An OFFLINE caller -- the harness, a deck, a re-score of a banked draw -- holds
    # the `Block` and not a seam-filled board, so it may hand the block's own list rather than mutating
    # a board to satisfy an instrument. Same list either way; one of the two callers just has it first.
    calls = list(calls if calls is not None else (getattr(bd, "calls", ()) or ()))
    k = int(loud_k if loud_k is not None else (getattr(getattr(bd, "knobs", None), "loud_k", 0) or 0))
    # EVERY HANDLE THE BOARD PUT ON THE PAGE, so a sentence can be asked whether it points at some
    # OTHER board row. A handle outside this set (a cascade row, an agent lookup) says nothing about
    # which board row a sentence is about, so it must not close a sentence to the loose read.
    board_handles = frozenset(int(h) for m in rows for h in (m.get("handles") or ()))
    sent_handles = [frozenset(_vf.cited_number_handles(s)) & board_handles for s in sents]

    def _bound_sents(hs):
        """The sentences a value match on THIS row may be read from: the ones carrying the row's own
        handle, plus the ones carrying no board handle at all.

        THIS IS THE BINDING `verify` ALWAYS HAD AND THE FIRST CUT DROPPED. The verifier charges a
        magnitude per SENTENCE and per CITED HANDLE; a coverage read that ran the same predicate with
        no handle binding at all scored a row referenced by a sentence about a different row (false
        positive (c) above). A sentence that cites another board row is that row's testimony."""
        own = {int(h) for h in hs}
        return [s for s, sh in zip(sents, sent_handles) if (sh & own) or not sh]

    def _verdict(m: dict):
        """``"cited"`` / ``"figure"`` / ``"tokens"`` / ``""`` (missed) / ``None`` (UNTESTABLE).

        THE TIGHT AND THE LOOSE READ ARE TWO ANSWERS AND ARE REPORTED AS TWO. ``cited`` is the tight
        one -- the writer named the handle. ``figure`` is the loose one -- the row's own LEVEL
        magnitude matched, in a sentence bound to the row, through ``_num_matches``, which bridges five
        reporting scales and is therefore evidence that the row reached the page rather than proof that
        THIS row did. The census that measured this corpus reported its used-without-citing figure at
        four tightnesses for exactly that reason; a single blended number would hide the same thing."""
        hs = tuple(m.get("handles") or ())
        groups = tuple(m.get("tokens") or ())
        role = m.get("role")
        if role in _HANDLE_ROLES and hs:
            if cited & {int(h) for h in hs}:
                return "cited"
            # THE FIRST HANDLE ONLY -- the level for a state row, the distance for the kind-2 watch
            # row. The sigma and the percentile are DIMENSIONLESS and collide across every row on the
            # board (false positive (b) above): `_num_matches` is sign-insensitive, so one row's
            # "-0.9 sigma" is matched by another's "+0.9 sigma", and a percentile hits any two-digit
            # token. Nothing is deleted -- both siblings are still served, still handled, still bound
            # by `_check_number_handle`; they are not EVIDENCE OF USE of the row they hang on.
            if _vf.figure_referenced(_bound_sents(hs), _row_figures(hs[:1], calls, n_start)):
                return "figure"
            # A HANDLED ROW MAY STILL CARRY A LETTERS SURFACE -- the kind-2 WATCH row is on both, and
            # a writer that named the row and its date without restating the distance figure USED it.
            # The first cut short-circuited here and forfeited that row's token test silently.
            if groups and _tokens_referenced(groups, sents):
                return "tokens"
            # A HANDLED ROW WITH NO SERVED MAGNITUDE IS STILL TESTABLE: its handle was on the page and
            # was not cited. That is a MISS, not an absent measurement.
            return ""
        if not groups:
            # A HANDLE-ROLE ROW WITH NEITHER HANDLES NOR TOKENS IS ONE THE REGISTER FENCE CORRECTED
            # (`Block.add` sets `calls = ()` and commits the SB-X line). Its own docstring promises the
            # row "is still in the denominator and can never be referenced" -- and the first cut let it
            # fall out of BOTH numerator and denominator, so a board that corrected every loud row read
            # `0 of 0` and a corrected row biased the figure UPWARD, the one direction an instrument
            # must never take. A MISS is what the reader met: an absence where a loud row should be.
            return "" if role in _HANDLE_ROLES else None
        return "tokens" if _tokens_referenced(groups, sents) else ""

    def _bucket(want):
        """(referenced, cited, figure-only, testable, missed ids) over the DENOMINATOR ENTRIES the
        rows whose (index, meta) ``want`` admits make up.

        A DENOMINATOR ENTRY IS A ROW, EXCEPT WHERE THE BLOCK SAYS TWO ROWS ARE ONE READING. Rows
        sharing a ``join`` stamp (``render_board``'s phase pairs, the BOARD JOIN line's own subjects)
        collapse to ONE entry carrying the best member's verdict, because the mandate instructs the
        writer to give one side and never two and the smoke measured it obeying that on 10 of 10
        groups. Counting the folded twin as a separate miss would charge the writer for compliance.

        ``cited`` is the TIGHT read and is always <= ``referenced``; on a letters-only class the two
        are equal by construction, because there is no handle to cite."""
        entries: dict = {}
        order: list = []
        for i, m in enumerate(rows):
            if not want(i, m):
                continue
            key = str(m.get("join") or "") or ("#%d" % i)
            if key not in entries:
                entries[key] = [_verdict(m), _row_id(i, m)]
                order.append(key)
            else:
                entries[key][0] = _best_verdict(entries[key][0], _verdict(m))
        hit, tight, fig, seen, missed = 0, 0, 0, 0, []
        for key in order:
            v, rid = entries[key]
            if v is None:
                continue
            seen += 1
            if v:
                hit += 1
            else:
                missed.append(rid)
            if v == "cited":
                tight += 1
            elif v == "figure":
                fig += 1
        return hit, tight, fig, seen, missed

    # THE LOUD CUT IS THE TIER'S OWN ``loud_k`` AND THE ROWS ARE IN THE WALK'S RANK ORDER, never in [N]
    # order -- the utilisation census measured that today's block has no rank at all and that its index
    # is call order, so a coverage bar ranked by handle would be ranked by nothing.
    _state = [i for i, m in enumerate(rows) if m.get("role") == "state"]
    _top = set(_state[:k] if k else _state)
    loud_ref, loud_cit, loud_fig, loud_seen, loud_missed = _bucket(lambda i, m: i in _top)
    ev_ref, _ev_cit, _ev_fig, ev_seen, ev_missed = _bucket(lambda i, m: m.get("role") == "event_open")
    rec_ref, _rc_cit, _rc_fig, rec_seen, rec_missed = _bucket(lambda i, m: m.get("role") == "recency")
    w_ref, w_cit, w_fig, w_seen, w_missed = _bucket(lambda i, m: m.get("role") == "watch")
    sp_ref, _sp_cit, _sp_fig, sp_seen, sp_missed = _bucket(lambda i, m: m.get("role") == "far")
    return {
        # THE TIGHT READ LEADS. `*_cited` is what a writer NAMED; `*_referenced` adds the bound value
        # match, and `*_figure_only` is exactly the part that rests on it -- reported apart so no reader
        # can blend a loose count into a tight claim (the census's own four-tightness discipline).
        "loud_k": k, "loud_rows": loud_seen, "loud_cited": loud_cit, "loud_referenced": loud_ref,
        "loud_figure_only": loud_fig,
        "events_open": ev_seen, "events_referenced": ev_ref,
        # THE EVENT DENOMINATOR'S OWN SHAPE, so a reader can see what it is NOT counting. A closed
        # window is history and the mandate asks nothing of it; a row with NO window placed is neither
        # open nor closed, and the first cut left it invisible in source comments alone.
        "events_closed": sum(1 for m in rows if m.get("role") == "event_closed"),
        "events_unplaced": sum(1 for m in rows if m.get("role") == "event"),
        "recency_rows": rec_seen, "recency_referenced": rec_ref,
        "watch_rows": w_seen, "watch_referenced": w_ref, "watch_cited": w_cit,
        "watch_figure_only": w_fig,
        # THE SPILLOVER DENOMINATOR IS THE LICENCE'S OWN POPULATION -- far rows across a CROSS edge,
        # the rows the licence line names. A same-board fan far row is not another market and is
        # counted beside it rather than inside it, so the two numbers can never disagree under one word.
        "spillover_rows": sp_seen, "spillover_referenced": sp_ref,
        "spillover_same_board_rows": sum(1 for m in rows if m.get("role") == "far_same_board"),
        "spillover_licensed": any(m.get("role") == "spillover_licence" for m in rows),
        "missed": {"loud": tuple(loud_missed), "events": tuple(ev_missed),
                   "recency": tuple(rec_missed), "watch": tuple(w_missed),
                   "spillover": tuple(sp_missed)},
    }
