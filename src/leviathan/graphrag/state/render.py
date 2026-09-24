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
from leviathan.graphrag.state.rows import (PERIOD_KIND_NOUNS, SIGN_WORDS, VINTAGE_ROLES, RowIdentity,
                                           figure_text, percentile_int, percentile_value,
                                           row_identity, shown_value, status_word)

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
# ``words_for_int``, ``month_words`` and ``MONTH_NAMES`` LIVE IN THE LEAF (``state/rows.py``) since the
# 09-23 fix round and are RE-EXPORTED here under the same names, so every reader of
# ``render.words_for_int`` / ``render.month_words`` gets the same function object it always did. They
# moved because ``rows.RowIdentity.words`` spells a period and an offset and ``rows`` imports nothing:
# one producer, never a second cardinal table.
from leviathan.graphrag.state.rows import (  # noqa: E402  -- the re-export is the point
    MONTH_NAMES, _ONES, _TENS, _WORDS_CEILING, day_words, month_words, words_for_int)


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


def _fmt(v, places: Optional[int] = None) -> str:
    """A magnitude as the reader sees it: no exponent, no trailing zeros, no thousands comma (a comma
    would make ``_claim_number_spans`` read ``2,021`` as a magnitude with punctuation and would put the
    board's own figures on a different footing from the agent's).

    **TWO NAMED MODES, NEVER A MAGIC ARGUMENT VALUE** (09-23 fix round, review RA lexical): ``places=None``
    -- the default -- is THE ONE PRECISION PRODUCER (CONTRACT.md C5, :func:`rows.figure_text`: two decimals
    between one tenth and a thousand, none at a thousand and over, two significant figures under one
    tenth), so no board figure prints ``0`` or ``-0`` for a real small magnitude (R-7: ``_fmt(-0.0035)``
    returned ``"-0"``); an explicit ``places`` (the flag row's event count at 0) is the FIXED rule, and
    never prints ``-0`` either. A figure that belongs to a CARD goes through :func:`shown_figure`, which
    reads the card's own ``display_decimals`` (the tape's settle keeps its tick)."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return ""
    if places is None:
        return figure_text(f)
    s = f"{f:.{int(places)}f}".rstrip("0").rstrip(".")
    return s if s not in ("", "-", "-0") else "0"


# ---------------------------------------------------------------------------------------------------
# THE CLOSED WORD MAPS (sec 6.2: "every literal, sign word, run word and convention word comes from a
# closed map")
# ---------------------------------------------------------------------------------------------------
CONFIDENCE_WORDS: dict = {"high": "high", "medium": "medium", "low": "low"}

#: The SAME three words as an ORDER, strongest first. It is a separate constant because the map above
#: is a VOCABULARY (what the reader is told) and this is a RULE (which of two names for one reading a
#: page should be read under). One table, so a fourth confidence word cannot rank silently as "unknown"
#: in one caller and print as itself in another. ``watch.rank_key``'s own ladder is the same order.
CONFIDENCE_RANK: dict = {"high": 0, "medium": 1, "low": 2}

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
    "far_series_other_table": "that market reads this driver from a different card, which is a different "
                              "series and not this one",
    "lag_undeclared_between_nodes": "the graph declares no lag between these two nodes, only each "
                                    "node's own lag onto the price",
    # fan / path / convergence
    "fan_cap": "the further markets past this tier's fan are named here; their own readings were not "
               "taken",
    "board_unlabeled": "that market carries this driver with no series label",
    "child_uncovered": "that market does not carry this driver",
    "render_cap": "the readings past this tier's render cut are named here",
    "edge_hop_cap": "this tier walks the links in one direction only",
    # S8's THREE NEW CHAIN WORDS (``board.CHAIN_REASONS``). Lane W minted them; clause 9 of
    # ``state/lint.py`` requires a reader SENTENCE for every word of every closed enum, in both
    # directions, DIGIT-FREE -- so until these three landed here `lint.check_state_board()` returned
    # three errors and four decks were red on that one cause. A cut that reads as a zero is
    # indistinguishable from a chain nobody asked for, and a chain BELOW the selection line is still on
    # the page: it is counted, never removed (ruling R2).
    "below_print_line": "the chains below this page's own selection line are counted here; the "
                        "reading behind each of them is still on the page",
    "no_measured_hop": "no hop on that chain carries a served series, so it can only carry the "
                       "direction the graph declares for it",
    "cross_unpriced": "the further market that chain reaches had nothing read on it this turn, so "
                      "the chain stops at this one",
    "when_not_all_loud": "the drivers this amplifier names are not all among the largest moves on this "
                         "page",
    # tape
    "no_tape_slug": "no per-contract price history is served for this market",
    "pre_coverage": "the as-of sits before this market's own price history begins",
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
    "rule_unverified": "the publisher states its next date rather than following a rule this page can "
                       "compute",
    "no_convention": "no desk line is declared for this series",
    "no_open_window": "no declared lag window is open on this row",
    "no_policy_date": "the record holds no forward date for this driver",
    # THE 09-11 NON-OBVIOUS RULING'S TWO WORDS. The first is the honest absence line -- a board that
    # cleared the admission floor with nothing says so in one sentence instead of padding a ceiling
    # with rows nobody would act on. The second is the dated-releases footnote, which is why its
    # sentence says the dates are ELSEWHERE ON THE LINE: `sb_absence` interpolates the label before
    # this sentence, and the label is where the ISO dates ride.
    "watch_floor_unmet": "nothing forward on this page clears the bar this list sets, so none is "
                         "named rather than a weaker one being offered",
    # THE PARTIAL FILL IS ITS OWN SENTENCE. The full-absence words underneath a list that HAS rows
    # read as a contradiction of them -- reproduced on el_nino_fanout at a cap of nine, where six
    # nominations were followed by "nothing forward on this page clears the bar this list sets".
    "watch_nothing_further": "nothing further on this page clears the bar this list sets, so no "
                             "weaker item is offered to fill the space",
    # AND THE CAPPED CORE IS A THIRD SENTENCE (review round 3, MAJOR). The word above is a statement
    # about the ADMISSION BAR and was emitted whenever the DISTINCTNESS CAPS bound the core -- which is
    # a different fact, and on 36 of 108 replayed seats it was printed under alternates that had cleared
    # that very bar. Where the held-back items are on the page, the note names the caps and points at
    # them; where the list was genuinely exhausted, the word above still says so.
    "watch_core_capped": "the core stops short of this tier's ceiling because this list takes one item "
                         "per reading and caps any one kind at a third of the core, so the items above "
                         "marked alternates cleared the same bar and were held back by those caps",
    "release_dates_only": "these are scheduled publication dates the publishers set, named once here "
                          "rather than as items to watch",
    # render / board
    "template_register_trip": "a line this page composed did not pass its own register check and was "
                              "replaced by this note",
    "pg_not_live": "the reader behind these readings is not available on this turn",
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


#: ── S8 DOCKET, POLISH (c): A STATE ROW NAMES ITS SOURCE AND NEVER ITS METRIC ── CLOSED 2026-09-17 ──
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
#:
#: **CLOSED BY THE 2026-09-16 PRE-ARM SMOKE, WHICH SERVED THE DEFECT TO A FUND PM.** The lens read
#: "Argentine export tax sits at 6.65 MMT" (a tax rate in a tonnage unit), "Brazilian supply 118 MMT"
#: over a PSD EXPORTS row and "Flash-drought reading 0.6 z" over ``gold_weather_z.drought_z``. The
#: docket's own remedy is taken exactly as it is written -- reader words DECLARED, never derived -- and
#: the declaration lives in ``state_conventions.yaml``'s own ``reading_words:`` key because
#: ``cascade_map.yaml`` is gitignored and generator-owned (the 09-15 law). :func:`reading_words` is the
#: ONE reader; an undeclared metric renders no clause at all, so the S7 failure mode -- a storage token
#: appended to a line that read correctly -- is unreachable by construction.
@lru_cache(maxsize=1)
def _reading_word_table() -> dict:
    """The declared ``reading_words`` book. Lazily imported: ``state/lint.py`` reads THIS module's
    :data:`ROW_CLASSES`, so a module-level import here would close a cycle."""
    try:
        from leviathan.graphrag.state import lint as _lint
        return dict((_lint.load_conventions() or {}).get("reading_words") or {})
    except Exception:                                   # noqa: BLE001 -- no book is no clause, never a raise
        return {}


def cache_clear() -> None:
    """Drop the two DECLARED BOOKS this module memoises (review round 2, minor 10).

    :func:`_reading_word_table` and :func:`_phase_pair_table` are ``lru_cache(maxsize=1)`` over
    ``lint.load_conventions()``, which the conventions file's own reload can move. ``feeders.cache_clear``
    calls this, so one call clears the whole state lane's memo -- a deck or a process that re-read the
    conventions can no longer keep grading the book it read first."""
    # 09-23 FIX ROUND (review RA minor 7): every memo over the conventions / the registry, not two of them
    for fn in (_reading_word_table, _phase_pair_table, globals().get("convention_lines"),
               globals().get("_hop_identity"), globals().get("_chain_generic_words")):
        try:
            fn.cache_clear()
        except Exception:                               # noqa: BLE001
            pass


def reading_words(table: str, metric: str) -> str:
    """WHAT THE NUMBER IS, in reader words, from the DECLARED table -- or ``''``.

    The exact ``{table}.{metric}`` key wins; ``{table}.*`` is the card-wide default and exists for the
    one measured case a static table cannot enumerate (``silver_fred_fx``, whose metric is swapped for
    the resolved region's currency by ``cascade._region_row``). EMPTY IS A REAL ANSWER and is the whole
    fail-closed property: an undeclared metric prints nothing rather than a storage column name, which
    is the S7 revert's measured failure mode. ``state/lint.py`` clause 13 fails the build when any
    ``(table, metric)`` pair on the board map has no entry, so 'nothing' can only ever mean a card the
    board does not read."""
    t, m = str(table or ""), str(metric or "")
    book = _reading_word_table()
    return ascii_text(book.get(f"{t}.{m}") or book.get(f"{t}.*") or "")


def scoped_reading_words(table: str, metric: str, commodity: str = "") -> str:
    """THE SERIES NAME FOR ONE COMMODITY'S READ OF A SHARED CARD (09-23, lane T's R4) -- or ``''``.

    ``silver_psd.ending_stocks_mt`` serves 63 slugs, and rice's ending stocks are a MILLED-basis figure
    across all classes while the card's words are the generic ones: a basis the card cannot declare once
    for every commodity. So the book may carry a COMMODITY-SCOPED key, ``<table>.<metric>@<slug>``, and it
    wins EXACT-FIRST for the series whose own commodity is that slug; every other read falls through to
    :func:`reading_words` unchanged (whose signature and answer are untouched). The slug is the SERIES'
    commodity (the state key's), never the board the row is read for -- the basis belongs to the series.
    A book with no scoped key answers exactly what :func:`reading_words` answers."""
    c = str(commodity or "")
    if c:
        w = _reading_word_table().get(f"{str(table or '')}.{str(metric or '')}@{c}")
        if w:
            return ascii_text(w)
    return reading_words(table, metric)


#: THE PHASE-PAIR BOOK (see ``state_conventions.yaml``'s own ``phase_pairs:`` header for the defect).
@lru_cache(maxsize=1)
def _phase_pair_table() -> dict:
    try:
        from leviathan.graphrag.state import lint as _lint
        doc = _lint.load_conventions() or {}
        return {"pairs": dict(doc.get("phase_pairs") or {}),
                "conventions": dict(doc.get("conventions") or {})}
    except Exception:                                   # noqa: BLE001
        return {"pairs": {}, "conventions": {}}


def phase_in_force(table: str, metric: str, level) -> dict:
    """WHICH PHASE OF A SIGNED CLIMATE INDEX THE READING ACTUALLY IS -- ``{}`` when the ref declares no
    pair, when the level is unreadable, or when the ``conventions:`` entry it names is not ``abs_bands``.

    THE THRESHOLD IS THE CONVENTION'S OWN FIRST BAND and is never re-typed here: ONI's 0.5 degC is
    ``silverleg._ONI_INTENSITY_BANDS[0]`` (lint-pinned identical), IOD's 0.4 degC is the BoM/JMA event
    cut. One number, one owner -- a phase sentence can never disagree with the band word the SB-1 row
    above it printed.

    Returns ``{driver, words, other_driver, other_words, in_force, band}``. ``in_force`` is False when
    the magnitude sits inside the line: NEITHER phase is declared, which is itself the fact the writer
    needs, and the caller renders it as such rather than picking the nearer side."""
    book = _phase_pair_table()
    pair = (book["pairs"] or {}).get(f"{table}.{metric}")
    if not pair:
        return {}
    conv = (book["conventions"] or {}).get(str(pair.get("convention") or ""))
    if not conv or str(conv.get("kind")) != "abs_bands" or not (conv.get("bands") or []):
        return {}
    try:
        v = float(level)
        band = float((conv.get("bands") or [])[0])
    except (TypeError, ValueError, IndexError):
        return {}
    hot = v >= 0
    side, other = (pair.get("positive") or {}), (pair.get("negative") or {})
    if not hot:
        side, other = other, side
    return {"driver": str(side.get("driver") or ""), "words": str(side.get("words") or ""),
            "other_driver": str(other.get("driver") or ""),
            "other_words": str(other.get("words") or ""),
            "in_force": abs(v) >= band, "band": band}


def phase_reading(st) -> tuple:
    """``(level, is_current)`` -- THE LEVEL A PHASE VERDICT IS READ OFF, and it is not always the row's.

    REVIEW ROUND 2, MAJOR 10. The first cut read :func:`phase_in_force` off ``_rows[0].state.level`` --
    which on a row carrying a DECLARED SAME-SERIES OFFSET is the SHIFTED reading, six months back on the
    palm board. The line then said "the phase in force at this reading is the cool phase" while the very
    same row minted "[N] the newest knowable reading of the same series is +0.98 degC" one line above:
    the page stated a phase that its own newest figure contradicts, which is the smoke's charge ("the
    writer built a palm supply-squeeze story on a cool number") re-created by the fix for it.

    THE PHASE IN FORCE IS A FACT ABOUT NOW, so it is read off the NEWEST KNOWABLE reading wherever the
    producer banked one (``feeders.series_state``'s ``recency['current_level']``), and off the row's own
    level everywhere else. The second element says WHICH, and :func:`_phase_clause` prints it -- a
    verdict read off a different figure from the one above it must say so."""
    cur = getattr(st, "recency", None) or {}
    if _offset_applied(st) and cur.get("current_level") is not None:
        return cur["current_level"], True
    return getattr(st, "level", None), False


def phase_for_state(st) -> dict:
    """:func:`phase_in_force` over :func:`phase_reading`'s level -- the ONE phase producer.

    Both consumers read it: the SB-JOIN line (which states the phase in words) and the quorum row
    (which must not count a pattern condition that is the OPPOSITE phase of the one in force). Two
    readers, one verdict, so a page can never declare the cool phase on one line and count the warm
    phase's driver as showing on another."""
    if st is None:
        return {}
    lvl, current = phase_reading(st)
    pf = phase_in_force(getattr(st, "table", ""), getattr(st, "metric", ""), lvl)
    if not pf:
        return {}
    cur = getattr(st, "recency", None) or {}
    return dict(pf, current=bool(current),
                current_date=str(cur.get("current_level_date") or "") if current else "",
                offset_periods=int(cur.get("offset_periods") or 0) if current else 0,
                cadence=str(getattr(st, "cadence", "") or ""))


def series_by_driver(bd) -> dict:
    """``{driver_id: {key, confidence, sign, phase}}`` FOR THE WHOLE BOARD -- the ONE fold map.

    REVIEW ROUND 2, MAJORS 4 AND 5. Round 1 built this map inline in :func:`render_board` from the
    RENDERED rows and handed it to :func:`sb_convergence` alone, so (a) the quorum's fold applied
    neither the declared-pair nor the sign guard the SB-JOIN fold applies -- two lines on one page could
    call one group "aliases" and "a contradiction the page cannot reconcile" -- and (b) the WATCH
    producer, which narrates the same pattern's count in its own sentence, never saw it at all: the b40
    quorum read "one of the two conditions ... export ban and DMO are one reading and count once here"
    while the watch row read "one of TWO of the two drivers" for the same pattern on the same page.

    ONE PAGE, ONE PATTERN, ONE COUNT: every consumer takes this map, and it is built off ``bd.rows`` --
    the rows the page READ -- because that is the population ``bd.convergence``'s own ``matched_measured``
    was computed over. A driver the render cut still read its series; a driver with no state is absent
    and is therefore distinct by construction."""
    out: dict = {}
    for row in getattr(bd, "rows", ()) or ():
        st = getattr(row, "state", None)
        # THE STATUS IS READ THE SAME DEFENSIVE WAY THE STATE IS, one line up (review round 3). This map
        # is now built inside `watch.stamp_release_clock` as well, which runs on every drawn nomination,
        # and a producer that RAISES there takes the whole watch draw with it: an object carrying no
        # status word is not a measured reading, which is exactly what this loop already skips.
        if st is None or status_word(getattr(st, "status", "") or "") != "ok":
            continue
        try:
            key = st.key.label()
        except Exception:                               # noqa: BLE001 -- an unlabelled key folds alone
            continue
        out.setdefault(str(row.driver_id), {"key": str(key),
                                            "confidence": str(row.confidence or ""),
                                            "sign": str(row.sign or ""),
                                            "phase": phase_for_state(st)})
    return out


# ---------------------------------------------------------------------------------------------------
# THE CARD FIELDS, THE ROW IDENTITY AND THE PRECISION ENTRY POINT (09-23 fix round, CONTRACT.md C1, C5,
# C10) -- the render is the ONE caller that fetches a card and a series name for an identity
# ---------------------------------------------------------------------------------------------------
#: THE C10 FIELDS, BY LEVEL. ``card_fields`` returns exactly these and nothing else, and only where the
#: card declares them, so ``{}`` means "this card declares none of the 09-23 fields" to every reader (lane
#: C falls back to HEAD's rule on it).
CARD_METRIC_FIELDS: tuple = ("basis_words", "display_scale", "display_unit", "display_decimals", "row_grain")
CARD_TABLE_FIELDS: tuple = ("country_axis", "axis_national", "provenance_kind", "period_words",
                            "period_first_known", "cell_noun")


def _card_specs(table: str, metric: str) -> tuple:
    """``(TableSpec | None, Metric | None)`` off the LOADED registry, read lazily and defensively: a
    registry that cannot load is a card that declares nothing, never a raise inside a render."""
    try:
        from leviathan.graphrag.numbers import registry as _reg
        ts = _reg.load_registry().tables.get(str(table or ""))
    except Exception:                                   # noqa: BLE001 -- no registry is no card
        return None, None
    if ts is None:
        return None, None
    ms = (getattr(ts, "metrics", None) or {}).get(str(metric or ""))
    return ts, ms


def card_fields(table: str, metric: str) -> dict:
    """THE ONE READER OF THE 09-23 CARD FIELDS (CONTRACT.md C10). ``{}`` for a card that declares none of
    them -- including every card on a tree where lane T's registry fields have not landed, read with
    ``getattr`` so this module is green before its producer is."""
    ts, ms = _card_specs(table, metric)
    out: dict = {}
    if ms is not None:
        for f in CARD_METRIC_FIELDS:
            v = getattr(ms, f, None)
            if v is not None and v != "":
                out[f] = v
    if ts is not None:
        for f in CARD_TABLE_FIELDS:
            v = getattr(ts, f, None)
            if v is not None and v != "" and v != {}:
                out[f] = v.model_dump() if hasattr(v, "model_dump") else v
    return out


def _card_facts(table: str, metric: str) -> dict:
    """The card's OWN pre-existing declarations the identity derives from where a C10 field is silent:
    the metric's display ``label``, the table's ``period_type`` and ``cadence`` and its declared
    ``country_axis_is_destination``. Declarations, never inferences -- see ``rows.row_identity``."""
    ts, ms = _card_specs(table, metric)
    out: dict = {}
    if ms is not None and getattr(ms, "label", ""):
        out["label"] = ascii_text(str(ms.label))
    if ts is not None:
        out["period_type"] = str(getattr(ts, "period_type", "") or "")
        out["cadence"] = str(getattr(ts, "cadence", "") or "")
        try:
            out["country_axis_is_destination"] = bool(ts.destination_coded())
        except Exception:                               # noqa: BLE001 -- a missing method is an undeclared axis
            out["country_axis_is_destination"] = bool(getattr(ts, "country_axis_is_destination", False))
    return out


def row_identity_for(row) -> Optional[RowIdentity]:
    """THE RENDER'S ONE DOOR TO :func:`rows.row_identity` -- it alone fetches the card
    (:func:`card_fields` + :func:`_card_facts`) and the declared series name (:func:`reading_words`).
    ``None`` for a row that read no state. A card with no declared reader words and no metric label names
    its series by the driver's own display words, which is HEAD's name and the only one left."""
    st = getattr(row, "state", None)
    if st is None:
        return None
    table = str(getattr(st, "table", "") or getattr(getattr(st, "key", None), "ref", "") or "")
    metric = str(getattr(st, "metric", "") or getattr(getattr(st, "key", None), "ref", "") or "")
    card = dict(_card_facts(table, metric))
    card.update(card_fields(table, metric))
    _commodity = str(getattr(getattr(st, "key", None), "commodity", "") or "")
    name = (scoped_reading_words(table, metric, _commodity) or card.get("label")
            or humanise(row.driver_id))
    return row_identity(contract=str(row.contract or ""), driver_id=str(row.driver_id or ""), st=st,
                        card=card, reading_words=name, offset_applied=_offset_applied(st))


@lru_cache(maxsize=256)
def convention_lines(table: str, metric: str) -> tuple:
    """EVERY LINE A PRINTED LEVEL OF ``(table, metric)`` MUST NOT BE ROUNDED ONTO OR ACROSS (C5) -- the
    ``abs_bands`` conventions declared for the refs that read this card, plus the phase band the
    ``phase_pairs`` book names for it. Read off the declared books, never typed here; ``()`` for a card
    whose raw level carries no declared line (a z-banded or percentile-banded convention draws its
    lines on the z or the rank, never on the level)."""
    try:
        from leviathan.graphrag.state import lint as _lint
        convs = dict((_lint.load_conventions() or {}).get("conventions") or {})
        refs = [ref for ref, r in (_lint.board_map() or {}).items()
                if str((r or {}).get("table") or "") == str(table)
                and str((r or {}).get("metric") or "") == str(metric)]
    except Exception:                                   # noqa: BLE001 -- no book is no line, never a raise
        return ()
    out: set = set()
    for ref in refs:
        cv = convs.get(ref) or {}
        if str(cv.get("kind") or "") == "abs_bands":
            out.update(float(b) for b in (cv.get("bands") or ()) if b is not None)
    pair = (_phase_pair_table().get("pairs") or {}).get(f"{table}.{metric}") or {}
    cv = convs.get(str(pair.get("convention") or "")) or {}
    if str(cv.get("kind") or "") == "abs_bands" and (cv.get("bands") or ()):
        out.add(float(cv["bands"][0]))
    return tuple(sorted(out))


def shown_figure(value, *, table: str, metric: str, unit: str = "", two_sided: Optional[bool] = None,
                 grouping: bool = False) -> str:
    """THE ONLY ENTRY POINT A READER CALLS TO PRINT A CARD'S FIGURE (CONTRACT.md C5): the card's
    ``display_scale`` / ``display_unit`` where the value is not already in display units, its
    ``display_decimals`` where declared, the declared LINES (:func:`convention_lines`) and
    :func:`rows.figure_text`'s rule. ``two_sided`` defaults to whether the card's lines are
    two-sided magnitudes (an ``abs_bands`` convention). ``""`` for a value that is not a number."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return ""
    cf = card_fields(table, metric)
    u = str(unit or "")
    d_unit = str(cf.get("display_unit") or "")
    scale = cf.get("display_scale")
    if d_unit and _norm_words(d_unit) != _norm_words(u):
        if scale is not None:
            try:
                v = v * float(scale)
            except (TypeError, ValueError):
                pass
        u = d_unit
    lines = convention_lines(str(table or ""), str(metric or ""))
    if two_sided is None:
        two_sided = bool(lines)
    dec = cf.get("display_decimals")
    return figure_text(v, unit=u, decimals=(int(dec) if dec is not None else None), lines=lines,
                       two_sided=bool(two_sided), grouping=grouping)


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
def role_in_roster(role) -> bool:
    """Is ``role`` a member of the ONE closed vintage-role roster (``rows.VINTAGE_ROLES``)? Case-folded,
    because the roster is a silver vocabulary and this is a render, not a join (citations'
    ``_role_display`` folds the same way)."""
    return str(role or "").strip().lower() in VINTAGE_ROLES


def sb_call(*, table: str, metric: str, commodity: Optional[str], country: Optional[str],
            period: str, asof: str, value, unit: str = "", knowledge_date: Optional[str] = None,
            z_window=None, z_series: Optional[str] = None, role: Optional[str] = None,
            row_id: str = "", stat: str = "", window: Optional[dict] = None, offset_months: int = 0,
            basis: str = "", axis_scope: str = "") -> dict:
    """ONE synthetic call record for ONE magnitude -- ``_cw_call`` / ``_dv_call``'s own shape
    (cascade.py:7465, derived.py:73), so ``citations.unify`` numbers it in call order and
    ``from_number`` labels it from the same record. One producer, one row, one ``shown``.

    ``country`` IS THE RESOLVED SCOPE AND IS NEVER ABSENT ON A MULTI-GEO CARD (K9-2): the board's own
    key resolution produced it, so ``citations._unscoped_multi_geo`` can never fire on a board row.
    ``z_window`` / ``z_series`` ride the ROW (citations.py:1432-1434 reads them there, not off the
    query), which is what renders "vs {n} points of {series}" on a z handle without a second producer.

    **THE 09-23 CONTRACT'S KEYS (C3) ARE KEYWORD-ONLY AND WRITTEN ONLY WHEN NON-EMPTY**, so a call that
    declares none of them has HEAD's exact shape: ``_row_id`` (top level -- which row identity minted this
    call, the join lanes V and A read), and on the row ``stat`` / ``window`` / ``offset_months`` /
    ``basis`` / ``axis_scope`` (the words lane C's label spends).

    **``role`` IS WRITTEN ONLY WHEN IT IS A VINTAGE ROLE** (C3, the belt to lane C's producer fix C11).
    A card's provenance column also carries release stamps (the Pink Sheet's ``2026M09``) and rule
    versions; a token outside ``rows.VINTAGE_ROLES`` writes no ``provenance`` at all, and the caller
    counts the refusal (``Block.counters["role_withheld"]``) -- so a release stamp later than the as-of
    can never reach a label through a board call, whichever feeder wrote it."""
    row: dict = {"value": value}
    if unit:
        row["unit"] = unit
    if knowledge_date:
        row["knowledge_date"] = knowledge_date
    if z_window is not None:
        row["z_window"] = z_window
    if z_series:
        row["z_series"] = z_series
    if role and role_in_roster(role):
        row["provenance"] = role
    if stat:
        row["stat"] = str(stat)
    if window:
        row["window"] = {"from": str(window.get("from") or ""), "to": str(window.get("to") or "")}
    if int(offset_months or 0) > 0:
        row["offset_months"] = int(offset_months)
    if basis:
        row["basis"] = str(basis)
    if axis_scope:
        row["axis_scope"] = str(axis_scope)
    call = {"query": {"table": table, "metric": metric, "commodity": commodity, "country": country,
                      "period": period, "asof": asof},
            "rows": [row], "status": "ok", "_sb": True}
    if row_id:
        call["_row_id"] = str(row_id)
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

#: THE COMPOSED CHAIN's two line markers (S8). They live HERE, above :data:`ROW_CLASSES`, because that
#: table reads them -- the chain rows ride SB-P's own class as alternations (see the class note below,
#: and the section that builds the rows for why). Keeping the marker and its regex on one constant is
#: what stops the class token and the producer drifting into two spellings of one row.
CHAIN_HEAD_PREFIX: str = "CHAIN "
CHAIN_SUB_PREFIX: str = "  chain "

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
    # SB-T NAMES ITS DELIVERY THE WAY THE PICK WAS MADE (09-23, CONTRACT.md C12 / OWNER DECISION 5):
    # "front <YYYY-MM>" only for a pick an activity print decided; "the nearest listed delivery, <Month
    # YYYY>," for every other pick. One class, two spellings of one slot.
    "SB-T": re.compile(r"^- \[N\d+\] .+(?: front " + _YM + r"|, the nearest listed delivery, [A-Z][a-z]+ "
                       r"\d{4},) settle on " + _ISO + r": "),
    # SB-O CARRIES TWO SPELLINGS OF ONE CLAUSE AND STAYS ONE CLASS (S8). The chain's own outcome row
    # is the same object as an analog outcome -- a MOVE over the band declared from that state, one
    # handle per magnitude -- but it is held to ZERO desk-register charges (threat E12) and `the graph`
    # is a charged token, so it spells the clause "over the band declared from that state". Widening
    # the alternation keeps the shipped sample classifying as exactly ("SB-O",) and adds no key that
    # `state/lint.py` -- a file this lane does not own -- would have to grow a sample for.
    "SB-O": re.compile(r"^- \[N\d+\] .+ over the band (?:the graph declares|declared) from that "
                       r"state, "),
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
    # THE FAN INDEX'S OPENING MOVED WITH ITS WORDS (lane D, 2026-09-17): "the same reading is declared
    # on twenty-three other boards" named no SUBJECT and no market a reader could look at next, and the
    # PM lens read it as scoring machinery. The class token is still the line's own opening and still
    # letters-only; what changed is that the DRIVER leads it.
    "SB-F": re.compile(r"^(?:- .+ is a shared driver across |"
                       + SB_CROSS_COMMODITY_PREFIX + r"[ :])"),
    # ...and the quorum row's token likewise: "declared drivers sit among this board's loudest rows" is
    # three internal words in one clause, and the row now says CONDITIONS MET and states the verdict.
    "SB-C": re.compile(r"^- .+ on .+: .+ of the .+ conditions? it names (?:is|are) showing here "),
    "SB-M": re.compile(r"^  amplifier on "),
    # SB-P CARRIES THE TOPOLOGY SECTION AND S8's COMPOSED CHAIN RIDES IT AS A THIRD AND FOURTH
    # ALTERNATION -- the SB-F precedent, taken for the SAME reason and stated in the same terms.
    # `state/lint.py`'s clause 10 keys its sample map on `set(ROW_CLASSES)` and reds a class with no
    # sample, and lint.py is not this lane's file, so a nineteenth key would ship a RED `config_check`
    # this lane cannot green. The chain rows and the UPSTREAM row are the same object to every consumer
    # that matters: both are this section, both are letters-only, neither mints a handle -- and the
    # chain block is what RETIRES the UPSTREAM row from the paid path (DESIGN A.8 item 4).
    "SB-P": re.compile(r"^(?:UPSTREAM |" + CHAIN_HEAD_PREFIX + r"|" + CHAIN_SUB_PREFIX + r")"),
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
    # SB-LEAD IS THE SECOND CLASS BEYOND SEC 6.2's TABLE, AND FOR THE SAME REASON SB-JOIN IS: it says
    # something about the BLOCK'S OWN ORDER rather than about a row's content. ROUND-2 DOCKET item 12
    # asks for the three largest moves to be unmissable -- first in the block, one line each -- and no
    # declared class can carry that, because SB-1 is a row's own figures and SB-X is an absence. It is
    # letters-only, mints no handle and asserts no magnitude, so it adds nothing to the [N] address
    # space and nothing the verifier must bind.
    "SB-LEAD": re.compile(r"^LARGEST MOVE "),
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
    # ONE SERIES, ONE CURRENT VALUE (lane D, the 2026-09-16 smoke). The deep page served the US drought
    # anomaly TWICE and called both current: "0.6 z [N44]" -- the MY2026-07 monthly LEVEL, this block's
    # own row -- and "2.24909 z [N82]", a statistic over a 2025-09..2026-09 WINDOW that reached the page
    # from the cascade's episode leg, both footnoted "newest shown". The block cannot police a figure it
    # did not mint, so it states its OWN contract instead, once, where the reader meets it first: every
    # figure on a state line below is that reading's LEVEL on the date the line names.
    return (f"{SB_MARKER_PREFIX}{bd.asof} for {label}: {words_for_int(n_series)} drivers read on "
            f"their own series, {words_for_int(n_receipts)} carried as dated receipts; "
            f"{rule_words}. Every figure on a state line below is that reading's LEVEL on the date "
            f"the line names; a figure read over a span of dates is a window statistic and is never a "
            f"second current value of the same series.")


def _scalar(block, value, **kw) -> None:
    """Register one printed figure on ``block`` when there is one (C4). A builder called on its own -- a
    deck, a census -- has no block and registers nothing; the printed line is the same either way."""
    if block is not None:
        block.scalar(value, **kw)


def _count(block, name: str, n: int = 1) -> None:
    if block is not None:
        block.count(name, n)


#: THE VERB A WINDOW EXTREME TAKES, READ OFF THE SIDE OF ITS OWN RECORD IT SITS ON (R-5). The chain's
#: lag-window "peak" is the loudest reading inside the window measured by DISTANCE from the middle, so
#: it is a TROUGH whenever it sits below the median -- ``export_pace_lag`` carried a window extreme at the
#: THIRD percentile on both 09-23 soybean boards and the page said it "peaked" there.
def extreme_verb(pct) -> str:
    try:
        return "peaked at" if float(pct) >= 50.0 else "bottomed at"
    except (TypeError, ValueError):
        return "peaked at"


def _band_scalars(block, band) -> None:
    """Register a lag band's two ENDS, in quarters, as the words :func:`band_words` printed them (C4,
    ``lag_band_quarters``). A band with no parse printed no number and registers none."""
    if block is None or band is None or getattr(band, "min_q", None) is None:
        return
    txt = band_words(band)
    for q in dict.fromkeys(x for x in (band.min_q, band.max_q) if x is not None):
        _scalar(block, q, unit="quarters", kind="lag_band_quarters", text=txt)


def sb_state(n: int, row, *, asof: str, age_clause: str = "", block=None, peak_hop=None) -> tuple:
    """SB-1 (sec 6.2): the STATE row, ONE HANDLE PER MAGNITUDE.

    Three handles at most -- the level, the z, the percentile -- each with its own call carrying its
    own single ``shown`` value. A measure that DECLINED mints no handle and says so in words instead:
    ``derived.py:322-331`` is the precedent for minting the percentile under its own handle, and
    ``_cw_cell_line`` (:7449) is the precedent for one magnitude per handle.

    A FLAG ROW (``*_flag`` refs) carries ``flag_state`` where a z and a percentile would be, because a
    sigma over a 0/1 column is a base rate wearing a sigma's clothes (``stats.flag_events``). Its ONE
    magnitude is the event count, and the rest of the sentence is dates and words.

    **THE ROW IS NAMED BY ITS SERIES, AND THE DRIVER IS A ROUTING WORD** (09-23 fix round, CONTRACT.md
    C1). The head used to be ``humanise(row.driver_id)`` -- the DRIVER that routes to a series -- and the
    re-smoke served a drought z-score as "flash drought", PSD all-class milled ending stocks as
    "deliverable" stocks, PSD FSI use as "the ethanol grind" and national carry-in as a "reserve". The head
    is now :meth:`rows.RowIdentity.words` -- the card's declared series name, its declared basis, the
    scope and cell the read actually covers, the period at its own precision, the vintage role where it
    is one, and the declared offset where it was applied -- and the driver rides once as "read here for
    <driver>", so a reader still knows WHY the row is on this page (R-3). The "the reading is ..."
    clause is gone because the reading's words ARE the name now; the fact is kept, one clause earlier.

    **EVERY FIGURE PRINTS THROUGH THE ONE PRECISION PRODUCER** (C5, :func:`shown_figure`): the card's
    decimals where declared, two significant figures under one tenth (never a false ``0``), no decimals
    at a thousand and over, and never rounded onto or across a declared line. The CALL keeps the full
    served value, so the verifier's reader-precision arm backs the printed figure (R-1, R-7).

    **A HOP OF A RENDERED FULL CHAIN MINTS ITS WINDOW PEAK HERE** (C2, ``peak_hop``): the chain row
    prints the lag window's extreme in words, and a figure in words with no address is the one the writer
    re-digitised and the verifier then cut ("peaked at the a level this page could not back percentile")
    -- or deleted with the whole hop clause (max crush, soyoil/palm drought, 09-23). The peak is a board
    fact (``walk.hop_window_peak``, zero reads), so it takes its own call and its own handle, the
    render.py:925-953 pattern, and the chain line cites it."""
    st = row.state
    calls: list = []
    if st is None:
        return "", calls
    unit = st.narrate_unit or st.unit or ""
    ident = row_identity_for(row)
    rid = ident.row_id if ident is not None else ""
    period = str(st.level_date or "")
    # THE ROLE IS SPLICED ONLY WHERE IT IS A VINTAGE ROLE (C3 / C11). A release stamp is not a role, and
    # a stamp later than the as-of reached the 2024 page's footer through exactly this splice.
    role = st.role if role_in_roster(st.role) else None
    if st.role and not role:
        _count(block, "role_withheld")
    if role:
        period = f"{period} {role}".strip()
    label = ident.words() if ident is not None else humanise(row.driver_id)
    route = humanise(row.driver_id)
    reader = table_words(st.table or st.key.ref)
    q = {"table": st.table or st.key.ref, "metric": st.metric or st.key.ref,
         "commodity": st.key.commodity or row.contract, "country": st.key.country or None,
         "period": period, "asof": asof}
    _sw = ident.scope_words() if ident is not None else ""
    mk = {"row_id": rid, "basis": (ident.basis if ident is not None else ""),
          "axis_scope": (_sw[len(" for "):] if _sw.startswith(" for ") else _sw.strip()),
          "offset_months": (ident.offset_months if ident is not None else 0)}
    head = f"- [N{n}] {label}, on {board_label(row.contract)} ({reader}), read here for {route}: "

    parts: list = []
    h = n
    if st.flag_state:
        fs = st.flag_state
        ev = fs.get("events_in_window")
        wp = int(fs.get("window_periods") or 2)
        calls.append(sb_call(value=ev, unit="events", knowledge_date=st.knowledge_date, role=role,
                             stat="level", **mk, **q))
        noun = period_noun(st.cadence, wp)
        ev_txt = _fmt(ev, 0)
        _scalar(block, ev, unit="events", kind="level", row_id=rid, handle=h, text=ev_txt)
        _scalar(block, wp, unit=noun, kind="window_length", row_id=rid,
                text=words_for_int(fs.get("window_periods")))
        parts.append(f"{head}{ev_txt} events in its last {words_for_int(fs.get('window_periods'))} "
                     f"{noun}")
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
                             role=role, stat="level", **mk, **q))
        if st.level_shown is not None:
            _scalar(block, st.level_shown, unit=unit, kind="level", row_id=rid, handle=h, text=lvl)
        parts.append(f"{head}{lvl}")
        if _ok(st.z):
            h += 1
            win = st.z.get("window_n") or st.z.get("window") or st.z.get("n")
            zv = round(float(st.z["value"]), 1)
            calls.append(sb_call(value=zv, unit="sigma", knowledge_date=st.knowledge_date, z_window=win,
                                 z_series=f"{q['table']}.{q['metric']}", stat="sigma", **mk, **q))
            ztxt = f"{float(st.z['value']):+.1f}"
            _scalar(block, zv, unit="sigma", kind="sigma", row_id=rid, handle=h, text=ztxt)
            _wn = period_noun(st.cadence, int(win or 2))
            _scalar(block, win, unit=_wn, kind="window_length", row_id=rid, text=words_for_int(win))
            parts.append(f"[N{h}] {ztxt} sigma on its trailing window of "
                         f"{words_for_int(win)} {_wn}")
        else:
            parts.append("its own history carries no standing this turn: "
                         + absence_why((st.z or {}).get("reason") or "thin_history"))
        if _ok(st.percentile):
            h += 1
            # THE PRINTED ORDINAL AND THE CALL'S VALUE ARE ONE VARIABLE (C5): half-to-even to an integer,
            # except where that lands on or across a decile line the raw rank is not on (89.6 prints
            # "89.6th" and the call carries 89.6 -- never "90th", the top decile it is not in).
            pv = percentile_value(st.percentile["value"])
            pv = int(pv) if pv is not None and float(pv).is_integer() else pv
            ptxt = percentile_int(st.percentile["value"])
            calls.append(sb_call(value=pv, unit="percentile", knowledge_date=st.knowledge_date,
                                 stat="percentile", **mk, **q))
            _scalar(block, pv, unit="percentile", kind="percentile", row_id=rid, handle=h, text=ptxt)
            parts.append(f"[N{h}] {ptxt} percentile of its own record")
        else:
            # A MEASURE THAT DECLINED IS A CLAUSE, NEVER A SILENCE. The z arm already said so; without
            # this one a row whose z computed and whose percentile did not would print two handles and
            # no word about the third, and a reader would not know a rank had been attempted at all.
            parts.append("its own record carries no rank for this reading: "
                         + absence_why((st.percentile or {}).get("reason") or "thin_history"))
        _pk = getattr(peak_hop, "tail_peak_percentile", None) if peak_hop is not None else None
        if _pk is not None:
            h += 1
            pkv = percentile_value(_pk)
            pkv = int(pkv) if pkv is not None and float(pkv).is_integer() else pkv
            pktxt = percentile_int(_pk)
            pdate = str(getattr(peak_hop, "tail_peak_date", "") or "")
            wfrom = str(getattr(peak_hop, "tail_window_from", "") or "")
            calls.append(sb_call(value=pkv, unit="percentile", knowledge_date=st.knowledge_date,
                                 stat="window_peak_percentile",
                                 window={"from": wfrom, "to": str(asof or "")[:10]},
                                 **mk, **dict(q, period=pdate or period)))
            _scalar(block, pkv, unit="percentile", kind="window_peak_percentile", row_id=rid, handle=h,
                    text=pktxt)
            _since = month_words(wfrom)
            parts.append(f"[N{h}] {extreme_verb(_pk)} the {pktxt} percentile in {month_words(pdate)}, "
                         f"the extreme of its lag window"
                         + (f" since {_since}" if _since else ""))
    if st.run and not st.run.get("declined"):
        d = RUN_DIRECTION_WORDS.get(str(st.run.get("direction") or ""), "moving one way")
        ln = int(st.run.get("length") or 0)
        _scalar(block, ln, unit=period_noun(st.cadence, ln), kind="run_length", row_id=rid,
                text=words_for_int(ln))
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
    # THE PERIOD GAP (C11): the newest period this row HOLDS as known is older than a period the SAME
    # SOURCE had already published at the as-of -- a fact about the store (``feeders.stamp_period_gaps``:
    # a sibling series of this slug on this card came back holding that newer period as known then; the
    # 09-23 verifier's F1 retired the calendar constant that used to decide it). It is a LABEL, never a
    # removal -- the row renders, and the reader is told which period this series holds and which newer
    # period its source had published (the 2024 as-of turn served MY2017-MY2020 PSD rows as the March-2024
    # state). The words say only what the store shows: that the source had published the newer period,
    # never that this series' own figure for it exists.
    _gap = dict(getattr(st, "period_gap", None) or {})
    if _gap.get("served") and _gap.get("expected"):
        _gnoun = PERIOD_KIND_NOUNS.get(ident.period_kind if ident is not None else "", "period")
        _gd = day_words(asof) or str(asof or "")[:10]
        parts.append(f"the newest {_gnoun} held for this series as known on {_gd} is "
                     f"{ascii_text(_gap['served'])}; the same source had published "
                     f"{ascii_text(_gap['expected'])} figures by then")
    # THE NEWEST KNOWABLE READING OF THE SAME SERIES, BESIDE THE LAGGED ONE (lane D, the 2026-09-16
    # pre-arm smoke). MEASURED on two served quick turns: the palm board printed
    # "NOAA ONI ... MY2026-01 = -0.39 degC (latest available 2026-03-08)" -- a COOL-phase reading --
    # while the soybean board at the SAME as-of printed MY2026-07 = 1.8 degC off this same table, and
    # the writer built a palm supply-squeeze on the cool number. The shift is the palm author's own
    # DECLARED EFFECT LAG and is not a defect; what WAS a defect is that the only words beside it read
    # "latest available", which a reader takes for DATA LATENCY. The level does not move -- CORRECT or
    # COMPUTE, never delete -- and the board now serves BOTH readings and says which is which, with the
    # newest one carrying its own handle so the writer may print it.
    # **THE OFFSET'S OWN WORDS NOW RIDE THE IDENTITY** (09-23, C1): the row's name says "read six months
    # back -- the reading whose declared lag lands now", so the separate "the date above is ... back"
    # sentence is that same fact said a second time and is not printed; the newest reading still takes
    # its own handle here.
    _cur = getattr(st, "recency", None) or {}
    if _offset_applied(st):
        if not st.flag_state and _cur.get("current_level") is not None:
            h += 1
            _cv = shown_value(_cur["current_level"], getattr(st, "scale", 1.0) or 1.0)
            _cd = str(_cur.get("current_level_date") or "")
            _ckd = _cur.get("current_knowledge_date") or st.knowledge_date
            calls.append(sb_call(value=_cv, unit=unit, knowledge_date=_ckd, stat="current_level",
                                 row_id=rid, basis=mk["basis"], axis_scope=mk["axis_scope"],
                                 **dict(q, period=_cd)))
            _for = f" for {_cd}" if _cd else ""
            # THE SAME SIGN RULE THE LEVEL ABOVE TOOK (review round 2, minor 6). The first cut formatted
            # this one with `_fmt`, so on a two-sided `abs_bands` series the level printed "-0.67 degC"
            # and the newest knowable reading printed "1.8 degC" -- the same series, one line apart, one
            # of them stripped of the sign that says which PHASE it is.
            _two_sided = bool(st.convention and st.convention.get("kind") == "abs_bands")
            _ctxt = _signed_words(_cv, unit, _two_sided, table=q["table"], metric=q["metric"])
            _scalar(block, _cv, unit=unit, kind="current_level", row_id=rid, handle=h, text=_ctxt)
            parts.append(f"[N{h}] the newest knowable reading of the same series is "
                         f"{_ctxt}{_for}")
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
    return _signed_words(v, unit, two_sided, table=str(st.table or st.key.ref),
                         metric=str(st.metric or st.key.ref))


def _signed_words(v, unit: str, two_sided: bool, *, table: str = "", metric: str = "") -> str:
    """ONE value in analyst units under :func:`_level_words`' own sign rule -- extracted so a SECOND
    figure of the same series (the newest knowable reading) cannot print under a different one.

    **IT PRINTS THROUGH THE ONE PRECISION PRODUCER** (09-23, CONTRACT.md C5): :func:`shown_figure` where
    the card is known -- its declared decimals and its declared LINES, so ONI 0.46 is never printed on
    the El Nino line -- and :func:`rows.figure_text` otherwise. The sign rule is the one this function
    always had (a two-sided series or a negative value carries it); what changed is that a magnitude
    under one tenth keeps two significant figures instead of printing ``0`` or ``-0`` (R-7), and a
    magnitude of a thousand or more prints no decimals."""
    if v is None:
        return "no level was read"
    if table or metric:
        txt = shown_figure(v, table=table, metric=metric, unit=unit, two_sided=two_sided)
    else:
        txt = figure_text(v, unit=unit, two_sided=two_sided)
    return txt or "no level was read"


def _ok(measure) -> bool:
    return bool(measure) and not measure.get("declined") and measure.get("value") is not None


def _offset_applied(st) -> bool:
    """Was this row's DECLARED same-series offset actually performed on the array?

    THE PRODUCER SAYS SO IN A BOOLEAN (review round 2, minor 5). ``feeders.series_state`` sets
    ``recency['offset_applied']`` in the ONE branch that actually performs the shift. The first cut
    instead searched ``offset_note`` for the literal :data:`feeders.OFFSET_NOT_APPLIED` and called that
    a one-literal contract -- but FOUR writers set ``apply_offset=False``, and two of them (a ``_Fold``
    refusal on an absent base ref, and one on a different table or native unit) write a note carrying
    neither the literal nor a shift, so the row would have told a reader that its date is an effect lag
    over an UNSHIFTED level. Unreachable on today's shipped map (exactly one ``same_series_as`` row,
    same table, same native unit) and reachable the moment the generator adds a second. The literal
    search survives as the FALLBACK, for a row banked before the flag existed. Imported lazily --
    ``feeders`` imports this module for its display vocabulary."""
    if not getattr(st, "offset_months", 0):
        return False
    _rec = getattr(st, "recency", None) or {}
    if "offset_applied" in _rec:
        return bool(_rec["offset_applied"])
    try:
        from leviathan.graphrag.state.feeders import OFFSET_NOT_APPLIED
    except Exception:                                   # noqa: BLE001
        return False
    return OFFSET_NOT_APPLIED not in str(getattr(st, "offset_note", "") or "")


_NORM_RX = re.compile(r"[^a-z0-9]+")


def _norm_words(s: str) -> str:
    """Two label spellings compared as WORDS: lower-cased, punctuation-folded, leading article dropped.
    'the crush' and 'Crush' are one label; 'exports' and 'Argentina export tax' are not."""
    t = _NORM_RX.sub(" ", str(s or "").lower()).strip()
    return t[4:] if t.startswith("the ") else t


def sb_convention(n: int, row, *, distance, band, label: str, unit_words: str, direction: str,
                  asof: str, band_words: str = "", kind_words: str = "the level a convention names",
                  row_label: str = "", dates: str = "", block=None) -> tuple:
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
    # THE LINE ITSELF IS A CARD THRESHOLD THE ROW PRINTS (C4, ``card_threshold``): a writer copying "the
    # moderate line at 1 degC" copies a declared desk line, not an unbacked figure.
    _scalar(block, band, unit=unit_words or "", kind="card_threshold", text=at)
    who = row_label or f"{humanise(row.driver_id)} on {board_label(row.contract)}"
    tail = f" -- {dates}" if dates else ""
    line = (f"- [N{n}] WATCH {kind_words} {who}: {_fmt(distance)} {unit_words} {direction} the "
            f"{label} line at {at}{tail}")
    return re.sub(r"\s+", " ", line), [call]


def sb_edge(row, *, far: Optional[dict] = None, block=None) -> str:
    """SB-E (sec 6.2): the declared edge in words -- NO handle, NO digit. This is the class that makes
    ruling 3 renderable: two boards, two lines, never reconciled. The lag band it prints in words is
    registered in the served-scalars pool (C4, ``lag_band_quarters``) where a block is handed in."""
    if far is None:
        driver, board = humanise(row.driver_id), board_label(row.contract)
        sign, band, conf = row.sign, row.lag_band, row.confidence
        tail = ""
    else:
        driver, board = humanise(far["driver_id"]), board_label(far["contract"])
        sign, band, conf = far["sign"], far["lag_band"], far["confidence"]
        tail = (" -- the same reading this page carries, read on that market's own edge"
                if far.get("free") else "")
    _band_scalars(block, band)
    return (f"- {driver} is declared to move {board} {sign_words(sign)} with a lag the graph states "
            f"as {band_words(band)}, at {CONFIDENCE_WORDS.get(conf, 'medium')} confidence{tail}")


def sb_projection(*, board: str, anchor_words: str, window: dict, horizon_months=None,
                  horizon_sits: Optional[str] = None, asof: str = "", closes_from: str = "") -> str:
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
    elif closes_from:
        # THE CLOSE IS COUNTED FROM THE NEWEST PRINT (09-23, CONTRACT.md C8) and the line says so: a
        # reading still in its run keeps acting until the maximum lag after its newest print, and the
        # run's start only opens the window.
        body = (f"the effect window on {board} opens around {month_words(window['opens'])} and, counted "
                f"from {closes_from}, closes around {month_words(window['closes'])}")
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


def _effect_window_for(row, st, anchor_date: str) -> tuple:
    """``(window, closes_from_words)`` for ONE SB-J row -- lane W's ONE lag producer
    (``walk.effect_window``, CONTRACT.md C8) in the shape :func:`sb_projection` reads. The window OPENS
    from the anchor the row prints (the run's start, or the reading's own date) and CLOSES the maximum lag
    after the NEWEST print; the second element names that newest print where it is not the anchor, so
    the line can say what the close is counted from. A tree without the producer keeps HEAD's
    ``projection_window`` and prints no second anchor."""
    from leviathan.graphrag.state import walk as _w
    _ew = getattr(_w, "effect_window", None)
    if _ew is None:
        return _w.projection_window(anchor_date, row.lag_band), ""
    band = row.lag_band
    newest = str(getattr(st, "level_date", "") or anchor_date or "")
    run_start = str(anchor_date or "") if str(anchor_date or "")[:10] != newest[:10] else None
    if band is None or band.min_q is None:
        return {"opens": None, "closes": None, "open_ended": False, "declined": "lag_unparsed"}, ""
    ew = _ew(band, newest=newest, run_start=run_start) or {}
    if not ew.get("opens"):
        return {"opens": None, "closes": None, "open_ended": False, "declined": "lag_unparsed"}, ""
    if band.max_q is None or not ew.get("closes"):
        return {"opens": ew["opens"], "closes": None, "open_ended": True, "declined": None}, ""
    _from = ("the newest reading in %s" % month_words(newest)) if (run_start and month_words(newest)) else ""
    return ({"opens": ew["opens"], "closes": ew["closes"], "open_ended": False, "declined": None},
            _from)


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
    seat = f"the largest moves on {anchor}" if anchor else "the largest moves on this page"
    return (f"{SB_CROSS_COMMODITY_PREFIX}: {seat} are declared on {words_for_int(len(named))} other "
            f"{'market' if len(named) == 1 else 'markets'} -- {body} -- and each of the readings above "
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
    tail = (f"; the measured readings on it are {hs}" if hs
            else "; no reading on it carries a measured state")
    lbl = board_label(anchor)
    hops_word = "hop" if int(path["depth"]) == 1 else "hops"
    return (f"UPSTREAM {chain} -> {lbl}: the graph places {humanise(path['hops'][0])} "
            f"{words_for_int(path['depth'])} {hops_word} upstream of the {lbl} price and declares its "
            f"own "
            f"lag onto that price as {band_words(path['lag_band'])}{tail}")


# ---------------------------------------------------------------------------------------------------
# THE COMPOSED CHAIN (S8, DESIGN B.0-B.4) -- the rows that REPLACE SB-P's role on the paid path
# ---------------------------------------------------------------------------------------------------
#: **THE CHAIN ROWS RIDE SB-P's OWN CLASS AS ALTERNATIONS, AND THAT IS A DECISION ABOUT A FILE THIS
#: LANE DOES NOT OWN.** ``state/lint.py``'s clause 10 keys its sample map on ``set(ROW_CLASSES)`` and
#: reds a class that has no sample, so a nineteenth key here would ship a RED ``config_check`` from a
#: lane that cannot write the sample. It is the SB-F precedent, taken for the same reason and stated in
#: the same terms (see the class note in :data:`ROW_CLASSES`): the chain rows and the SB-P row are the
#: same object to every consumer that matters -- both are the TOPOLOGY section, both are letters-only,
#: neither mints a handle -- and the chain block is what retires SB-P from the paid path.
#:
#: **LETTERS ONLY, AND EVERY FIGURE IS CITED AT THE ADDRESS THAT ALREADY MINTED IT.** A hop's level, z
#: and percentile are on that hop's OWN SB-1 line under its own ``[N]``; minting a second address for
#: one magnitude is what sec 6.3 forbids and what :func:`sb_lead` already refuses on the same ground.
#: So a chain row PRINTS THE PERCENTILE IN WORDS (:func:`percentile_words`) and CITES the row's handle
#: -- the figure is backed, the words are free, and the class carries no charged digit.
#:
#: **AND THE CHAIN'S PAGE SENTENCES ARE THE RENDER'S, NEVER ``walk.Chain.notes``.** ``notes`` is the
#: TRACE's arithmetic, built by ``walk.chain_explain`` from raw driver ids ("depth 2, reaching
#: corn_cbot") and from the charged token ``the graph``; ``register.internal_leaks`` and
#: ``register.count_desk_register`` grade the PAGE, and a page sentence built from an id is exactly the
#: leak ``Block._correction`` exists to catch -- which would cost the chain its whole row and its
#: handles. ONE PRODUCER PER SURFACE: ``notes`` for the payload, these functions for the reader.
#:
#: :data:`CHAIN_HEAD_PREFIX` and :data:`CHAIN_SUB_PREFIX` are declared above :data:`ROW_CLASSES`,
#: because that table reads them.
#:
#: The ordinal words 0-19 and the round tens, for :func:`percentile_words`. ``ordinal_words`` stops at
#: ten by design (its only caller counts to three); a PERCENTILE is the board's most common figure and
#: needs the whole hundred, so the two tables sit beside each other rather than one growing teeth it
#: does not need.
_ORDINAL_ONES: tuple = ("zeroth", "first", "second", "third", "fourth", "fifth", "sixth", "seventh",
                        "eighth", "ninth", "tenth", "eleventh", "twelfth", "thirteenth", "fourteenth",
                        "fifteenth", "sixteenth", "seventeenth", "eighteenth", "nineteenth")
_ORDINAL_TENS: tuple = ("", "", "twentieth", "thirtieth", "fortieth", "fiftieth", "sixtieth",
                        "seventieth", "eightieth", "ninetieth")

#: The TAIL measure (``walk.ChainHop.tail``, ``max(|pct-50|/50, min(|z|/2.5, 1))``) said in words, for
#: the hop whose own record carries no percentile this turn. It is a BAND and never a figure: the
#: number it stands for is on that hop's own state line under its own handle.
_TAIL_WORDS: tuple = ((0.80, "at a far tail of its own record"),
                      (0.50, "well away from the middle of its own record"),
                      (0.20, "off the middle of its own record"),
                      (0.0, "near the middle of its own record"))

#: What the chain says where two hops' readings AGREE with, RUN AGAINST, or do not settle the direction
#: declared between them. It is ``walk.CHAIN_AGREEMENT_WORDS`` read as a CLAUSE -- the verdict word is
#: the walk's and the sentence around it is this module's, which is the split every other row keeps.
#:
#: **THE CLAUSES ARE THE ROUND-2 CEILING'S OWN SPELLING** (orchestrator ruling R-3, 2026-09-18): the
#: hop line's scaffolding -- the node, its handle, the declared sign onto the next node, and this
#: clause -- is what a reader cannot lose. "here" said the same thing twice (the line IS here), so it
#: goes; the verdict word and the reading it is about are untouched, and the deck reads these constants
#: rather than their letters, so the pin holds by construction.
#:
#: **THE THREE CHAIN CEILINGS ARE RE-BASELINED ON MEASUREMENT** (orchestrator budget ruling, round 5
#: blocker 9; round 4 took the first two). The 160 / 1,100 / 300 were set BEFORE the rulings that
#: decide what these rows must say, and content ordered by a ruling is never cut to meet a number set
#: before the rulings. THE RULE IS ONE RULE: the MEASURED MAXIMUM over EVERY CELL RENDERED -- both
#: cells of the fixture at all three tiers AND the five 2026-09-16 payload boards -- plus ten per cent,
#: rounded UP to the next fifty. Each number below was measured through the shipped producer with the
#: ROLE the producer stamped, never a prefix guess (``r2d/CENSUS.md`` 7.2, ``r2e/R5_ceilings.json``):
#:
#:     metric            measured max   +10%      CEILING    where the maximum was measured
#:     rendered chain         1,406.5  1,547.2    **1,550**  payload quick_rv_soyoil_palm
#:     longest hop line         304      334.4      **350**  payload quick_rv_soyoil_palm
#:     count line               480      528.0      **550**  fixture max, ONE dated action aged out
#:
#: RE-MEASURED AFTER ROUND 5's OWN EDITS, on the same eleven cells (``r2e/R5_ceilings.json``,
#: ``r2e/R5_aged_page.json``): **1,439.5 / 304 / 439**, so ALL THREE CEILINGS HOLD on every cell, by
#: 110.5 / 46 / 111. The per-chain maximum moved 1,406.5 -> 1,439.5 AFTER the ruling was taken, and the
#: whole of that is the record row's own new word (``walk.chain_history_words`` now says "measured past
#: firings", +9 characters per rendered chain); the ceiling is left at the RULED number and the drift
#: is reported rather than re-based here, because a lane that re-bases its own budget every time it
#: measures has no budget. The count line FELL 480 -> 439 on the aged cell: the distinct-document fix
#: below spells "one" where the round-4 line spelled "two hundred sixty-four".
#:
#: ``per chain`` IS (all chain-row chars minus the once-per-page sides + count rows) / rendered chains,
#: which is the rule the 1,100 was set against. THE COUNT LINE'S BASE IS THE AGED CELL DELIBERATELY:
#: the clause round 4 added costs +47 characters the moment ONE dated action ages out (433 -> 480 at
#: max), and a ceiling measured only on pages where the clause is silent is a ceiling that fails the
#: first time the page says something.
#:
#: THE A.8 NON-CHAIN GATE IS UNTOUCHED AND IT IS THE ONE THAT DECIDES: not one non-chain byte has moved
#: in four rounds of chain fixes (14,801 / 13,740, 20,494 / 19,447, 25,825 / 24,778 on the fixture;
#: byte-identical on all five payloads), and the chain-OFF block is byte-identical to round 3's on all
#: five.
CHAIN_AGREEMENT_CLAUSE: dict = {
    "aligned": "and the readings agree",
    "at_odds": "and the readings run against it",
    "undetermined": "and the readings do not settle it",
}

#: WHERE THIS HOP'S DECLARED LAG RUNS TO from its window peak (owner ruling 5) -- and the ONE spelling
#: of it. It is a fact about THIS HOP's own reading (a shock that peaked and eased is still in transit
#: until this date) and it rides the state clause, beside the peak it belongs to.
#:
#: IT IS NOT THE BAND, AND ROUND 4 STOPPED THE TWO COMPETING. Round 3 had :func:`sb_chain_hop` read
#: this string back off the state clause to decide whether the hop still owed the reader a BAND; the
#: band now prints on the TERMINAL edge alone (round-4 MAJOR 1), where it names the ONE relation it is
#: declared for, so the two clauses answer different questions and neither suppresses the other.
#: **09-23: THE ONE LAG PRODUCER (CONTRACT.md C8).** The date is ``walk.effect_window``'s
#: ``peak_closes`` (lane W stamps it onto ``ChainHop.tail_lag_to``), and the clause now says WHOSE window
#: it is -- the PEAK's -- because "the lag runs to" beside a reading that is still rising read as the
#: whole reading's effect being spent on that date (corn_wheat F4, cotton FA-4).
CHAIN_LAG_RUNS_TO: str = "; the peak's own window runs to %s"

#: **WHY A CHAIN IS ON THE PAGE WHEN IT IS NOT HERE ON ITS RANK** -- the SLOT, in the chain row's own
#: words (owner ruling 2026-09-22, ratified).
#:
#: ``walk.Chain.slot`` names the seat the selection held for it: the chain the question's SUBJECT
#: names, the PAIR the question sets, a chain inside the HORIZON the question asked for, or the other
#: SIGN -- the side the page would otherwise not show. ``top`` is a chain that ranked in on its own
#: score and it renders NO label at all, because "this one earned its place" is what every unlabelled
#: row on this page already says.
#:
#: IT IS A LABEL AND NEVER A CLAIM ABOUT QUALITY. A slot row is ranked, scored and receipted exactly
#: like every other chain and its arithmetic line is the same line; the label states WHY THE SEAT
#: EXISTED, which is a fact about the selection and not about the chain. The round-2 lesson is the
#: reason it is MEASURED on the page and not merely pinned: a label that never renders is a green pin
#: and a dead surface.
#:
#: THE WORDS ARE THE RULING'S OWN, letters only and digit-free, and they carry no instrument token
#: (threat E12: no ``board``, no ``rows``, no ``loud``, no ``the graph``, and no ``slot`` -- the page
#: never says the name of its own machinery).
#: **AND THE BLOCK ADDRESSES THE QUESTION, NEVER THE READER** (round-4 R3-N1, orchestrator ruling).
#: The horizon label shipped as the ruling's verbatim second person ("inside the horizon YOU asked
#: for") and was the ONLY second-person construction in the chain block -- every other row on this page
#: addresses the QUESTION ("a market this question did not name", "the pair this question sets"), and a
#: block that switches person on one of four labels reads as two voices on one list.
CHAIN_SLOT_WORDS: dict = {
    "subject": "the chain this question names",
    "pair": "the pair this question sets",
    "horizon": "inside the horizon this question asks",
    "sign": "the other side",
}

#: WHY A CHAIN RENDERS AS ONE LINE -- **TWO CAUSES, TWO SENTENCES** (round-5 blockers 7 and 10,
#: orchestrator ruling; lane W's W4-R1 names the same defect and the same available fact).
#:
#: Round 3 retired the print line as a selection rule and round 4 stamped ``Chain.full`` in SEAT order,
#: so the ONLY chain that can render short today is a chain the selection held a SEAT for and seated
#: past the ``K + 2`` full bound (``walk.CHAIN_SLOT_FULL_OVER_K``) -- never a top-K chain, and never a
#: chain the print line cut. The row nevertheless said "under this page's own selection line" on every
#: one of them: MEASURED on the shipped pin's own board, four chains scoring 90 / 80 / 70 / 60 against
#: a print line of 40.0, ``chain_counts["below_print_line"] = 0``, ``rendered_one_line = 1`` -- the page
#: stating a cause the producer's own count denies, with a GREEN pin over it.
#:
#: THE SEATED SENTENCE STATES THE BOUND AND NOT A LINE, because that is what happened: the page's
#: full-render budget was spent on the chains above it and this one was carried anyway, which is the
#: opposite of being cut. The BELOW sentence is kept verbatim for the only caller that can still mint
#: it -- a walk that stamps no slot and a print line that cuts -- so nothing is deleted, and the fact
#: deciding between them is ``Chain.slot``, the same field the row's own label is read off.
#: 09-23 DESK VOCABULARY (owner, CONTRACT.md C13): the two causes keep their two sentences and lose the
#: machinery -- "the page's full-render bound" and "this page's own selection line" name the instrument;
#: the reader needs to know the chain is short because the room went to the chains above it, or because
#: it sits under the cut for a full treatment (the ``print line`` row's own replacement words).
CHAIN_ONE_LINE_WORDS: dict = {
    "seated": "shown in one line, because the fuller write-ups above it used this page's room",
    "below": "under this page's cut for a full treatment",
}


def chain_slot_words(ch) -> str:
    """One short clause naming the seat this chain was held for, or ``""`` for a chain that ranked in.

    READ, NEVER REQUIRED: a chain carrying no ``slot`` -- and every chain on a walk that declares none
    -- renders exactly the head it rendered before, so this producer moves not one byte until the
    selection fills the field."""
    return CHAIN_SLOT_WORDS.get(str(getattr(ch, "slot", "") or ""), "")

#: The SELECTION CLAUSE's vocabulary -- DESIGN B.2's rank terms said as facts a desk reads. "loud",
#: "rank" and "score" never appear (threat E12); the arithmetic itself rides the trace.
CHAIN_WHY_TAIL: str = "a reading at the %s percentile of its own record"
CHAIN_WHY_TAIL_BAND: str = "a reading %s"
CHAIN_WHY_REACH: str = "the distance it travels"
#: NO EMBEDDED COMMA IN A CLAUSE THE SELECTION LIST JOINS. `_and_list` separates on commas and puts
#: none before its "and", so a clause carrying its own relative clause reads as two list items on the
#: page ("...the market it reaches, which this question did not name and a buffer..."). The head line
#: already says "-- a market this question did not name" beside it, so the relative clause was also
#: the same fact twice.
CHAIN_WHY_UNNAMED: str = "the further market it reaches"
CHAIN_WHY_EVENT_OPEN: str = "a dated action inside the lag the model allows for it"
CHAIN_WHY_EVENT_CLOSED: str = "a dated action read as history"
CHAIN_WHY_EVENT_DOC: str = "a dated report on the mechanism it names"
CHAIN_WHY_ASYM: str = "a buffer at a tail of its own record"
CHAIN_WHY_CURATED: str = "a sequence the model's own map carries"

#: What the chain says where no dated document reached that hop. **IT NAMES THE DRAW AND NEVER THE
#: CORPUS** (threat E6, the K9 absence-lie class): the board read what this turn retrieved, which is
#: not the same statement as "none exists", and that difference is the whole of the class.
CHAIN_NO_RECEIPT: str = ("no dated document inside this link's lag among the documents retrieved "
                         "for this answer")

#: ...and what it says where the document IS dated outside the window declared for that hop. The
#: correction, never the deletion (threat E4): the row renders, and the words place it.
CHAIN_OUTSIDE_WINDOW: str = "outside the lag the model allows for it"

#: ...and what it says where the newest dated action this turn holds for the chain sits MORE THAN ONE
#: BAND-LENGTH before the as-of (round-4 census 8). ``walk._receipt_in_reach`` is the ONE rule and the
#: walk already refuses to score such a document; :func:`chain_receipt` now refuses to PRINT it as the
#: chain's receipt, and this is what the reader gets instead -- the estate HELD a dated action, it is
#: too old for this chain's own window, and neither half of that is a silence. The date is the
#: document's own, so the reader can see how old "too old" was.
CHAIN_RECEIPT_AGED: str = "a dated action %s, older than the lag the model allows for it"
#: A REPORT SENTENCE THE MECHANISM BOUND REFUSED, named where the chain would otherwise say it retrieved
#: nothing (round-5 census blocker 1): its own noun -- "a dated report", never "a dated action" -- so
#: the page never folds two populations under :data:`CHAIN_RECEIPT_AGED`. Spends no ``[E]`` seat.
CHAIN_RECEIPT_REPORT_OUTSIDE: str = ("a dated report on this link's mechanism, %s, outside the lag the "
                                     "model allows for it")

#: THE SEVEN RANK TERMS IN READER WORDS (DESIGN B.2's ids, said as facts a desk reads). The ORDER is
#: ``walk.CHAIN_TERMS`` -- one producer -- and the WORDS are this page's, for the same reason every
#: other chain sentence is composed here: ``Chain.notes`` spells these facts with raw driver ids and
#: the charged token ``the graph``, and the chain rows are held to zero charges.
#: THEY ARE ONE WORD EACH BECAUSE THE LINE IS A LIST OF PAIRS AND NOT A PARAGRAPH (round-2 item R-3's
#: ceiling). The first cut spelled them out ("distance from its own middle", "how the lags fit the
#: question") and the line MEASURED 278 to 326 characters -- more than the head it was cut out of. Each
#: word here is the fact the term scores, in the same vocabulary the rest of the block already uses:
#: ``tail`` and ``buffer`` are ``CHAIN_WHY_ASYM``'s own words, ``record`` is the record row's,
#: ``action`` is the document row's.
CHAIN_TERM_WORDS: dict = {
    "tail": "tail",
    "reach": "reach",
    "event": "action",
    "history": "record",
    "asymmetry": "buffer",
    "confidence": "strength",
    "lag": "lag fit",
}

#: THE CHAIN'S DOCUMENT ROW NAMES THE HOP THE DOCUMENT ACTS ON (round-2 item R-2). The receipt hop is
#: chosen as the LOUDEST hop and is generally not the last, while this row is emitted after the record
#: line -- so "this hop" and "for it" resolved to the nearest antecedent ON THE PAGE, which is the LAST
#: hop line and is the wrong hop on every chain whose loudest hop is not its last (MEASURED on the max
#: fixture: chain #1 is ``China import tariff -> export pace lag -> psd ending stock su ratio``, its
#: receipt hop is ``export pace lag`` -- hop two of three -- and the row sat under hop three).
#:
#: THE HOP IS NAMED HERE AND NOT INSIDE :func:`chain_receipt`, which keeps returning the hop-free
#: sentence it always returned (:data:`CHAIN_NO_RECEIPT` included): the placement is the RECEIPT's
#: fact and the row is the PAGE's, which is the split every other chain sentence keeps.
CHAIN_DOCUMENT_AT: str = "%sdocument: at %s, %s%s."


def percentile_words(p) -> str:
    """A percentile as an ENGLISH ORDINAL -- ``88`` -> ``eighty-eighth`` -- for the letters-only classes.

    :func:`ordinal` prints ``88th``, which is a charged digit on every class outside
    :data:`FIGURE_CLASSES`. This is the same rank said in letters, so a chain row states the reading's
    standing in words while the FIGURE stays at the one address that minted it."""
    try:
        n = int(round(float(p)))
    except (TypeError, ValueError):
        return ""
    if n < 0 or n > 100:
        return ""
    if n == 100:
        return "one hundredth"
    if n < 20:
        return _ORDINAL_ONES[n]
    t, r = divmod(n, 10)
    return _ORDINAL_TENS[t] if not r else (_TENS[t] + "-" + _ORDINAL_ONES[r])


def tail_words(tail) -> str:
    """The TAIL band in words, for a hop whose own record carries no percentile this turn."""
    try:
        v = abs(float(tail))
    except (TypeError, ValueError):
        return _TAIL_WORDS[-1][1]
    for floor, words in _TAIL_WORDS:
        if v >= floor:
            return words
    return _TAIL_WORDS[-1][1]


def chain_edge_words(sign: str) -> str:
    """The DECLARED relative sign between two hops in reader words, or ``""`` where none is declared.

    IT READS ``rows.SIGN_WORDS`` DIRECTLY rather than going through :func:`sign_words`, and the
    difference is one clause: that function's fallback for an undeclared sign is "in a direction the
    graph does not declare", which carries the charged token ``the graph``
    (``register.DESK_REGISTER_TOKENS``). Every other class on this page can afford that word; the chain
    rows are held to zero, so the UNDECLARED case gets its own clause in the caller."""
    return SIGN_WORDS.get(str(sign or ""), "")


def hop_row_id(hop) -> str:
    """THE ROW IDENTITY'S JOIN KEY for a chain hop -- ``f"{contract}|{driver_id}|{series_key}"``, the same
    spelling :class:`rows.RowIdentity.row_id` mints on the hop's SB-1 row (C1), so a scalar the chain row
    registers and a call the state row minted carry ONE ``row_id``."""
    return "%s|%s|%s" % (str(getattr(hop, "contract", "") or ""), str(getattr(hop, "driver_id", "") or ""),
                         str(getattr(hop, "series_key", "") or ""))


def _hop_series_parts(series_key: str) -> tuple:
    """``(ref, commodity, country, metric)`` off a ``SeriesKey.label()`` -- the key's own spelling
    (``ref|commodity|country[|metric]``), read back rather than re-derived."""
    parts = str(series_key or "").split("|")
    parts += [""] * (4 - len(parts))
    return tuple(parts[:4])


@lru_cache(maxsize=1024)
def _hop_identity(contract: str, driver_id: str, series_key: str,
                  collapse: str = "unknown") -> Optional[RowIdentity]:
    """A chain hop's :class:`rows.RowIdentity`, built from the hop ALONE -- its series key, the board
    map row that key's ref names and the READ'S OWN COLLAPSE the walk stamped on the hop from the SB-1
    row it measured (``ChainHop.collapse``) -- so the render and lane A's join (``answer._chain_hop_rows``)
    compute the SAME name from the SAME object with no board in hand (C9, I-3), and the chain line names
    the cell exactly as the SB-1 row does (review RA M1). A hop built without it (a trace replay, a hand
    stand-in) reads ``"unknown"`` and prints no cell words. ``None`` for a hop with no served series."""
    ref, commodity, country, metric = _hop_series_parts(series_key)
    if not ref:
        return None
    try:
        from leviathan.graphrag.state import lint as _lint
        mrow = dict((_lint.board_map() or {}).get(ref) or {})
    except Exception:                                   # noqa: BLE001 -- no map is no identity
        mrow = {}
    table = str(mrow.get("table") or "")
    metric = str(metric or mrow.get("metric") or "")
    if not table or not metric:
        return None
    from leviathan.graphrag.state.rows import SeriesKey
    import types as _types
    st = _types.SimpleNamespace(key=SeriesKey(ref=ref, commodity=commodity, country=country),
                                table=table, metric=metric, level_date="", knowledge_date="",
                                cadence="", collapse=collapse, role=None, offset_months=0,
                                recency={})
    card = dict(_card_facts(table, metric))
    card.update(card_fields(table, metric))
    name = scoped_reading_words(table, metric, str(commodity or "")) or card.get("label") or ""
    if not name:
        return None
    return row_identity(contract=contract, driver_id=driver_id, st=st, card=card, reading_words=name,
                        offset_applied=False)


def _hop_collapse(hop) -> str:
    """The read's collapse the walk stamped on the hop (``ChainHop.collapse``), ``"unknown"`` where the
    hop carries none (a trace replay, a hand-built stand-in) -- which prints no cell words."""
    c = getattr(hop, "collapse", None)
    return "unknown" if c is None else str(c)


def chain_hop_name(hop) -> str:
    """THE ONE PRINTED HOP NAME (CONTRACT.md C9) -- the hop's OWN ROW IDENTITY minus its date
    (:meth:`rows.RowIdentity.series_words`): the series by its card's declared reader words, the card's
    basis, the scope and the cell rule of the read -- never the driver that routes to it. One row reads
    ONE thing on its SB-1 line and on every chain line that cites it (review RA M1: SB-1 said "the
    stocks-to-use ratio, ending stocks as a share of domestic use, for United States" while every chain
    line citing the same handle dropped the basis, and a cell read as "for SE Asia Palm Belt"). A hop
    with no served series has no series to name, and its driver's own display words are then the whole
    of what the reader can be told. Lane A's positional join compares THIS spelling to the printed one."""
    ident = _hop_identity(str(getattr(hop, "contract", "") or ""), str(getattr(hop, "driver_id", "") or ""),
                          str(getattr(hop, "series_key", "") or ""), _hop_collapse(hop))
    if ident is None or not getattr(hop, "measured", False):
        return humanise(getattr(hop, "driver_id", "") or "")
    return ascii_text(ident.series_words())


def _hop_card_label(hop) -> str:
    """The card's declared metric ``label`` for the series a hop reads, or ``""`` -- resolved the way
    :func:`_hop_identity` resolves its table and metric (the series key and the board map), no read."""
    ref, _commodity, _country, metric = _hop_series_parts(str(getattr(hop, "series_key", "") or ""))
    if not ref:
        return ""
    try:
        from leviathan.graphrag.state import lint as _lint
        mrow = dict((_lint.board_map() or {}).get(ref) or {})
    except Exception:                                   # noqa: BLE001
        return ""
    table = str(mrow.get("table") or "")
    metric = str(metric or mrow.get("metric") or "")
    if not table or not metric:
        return ""
    return str((_card_facts(table, metric) or {}).get("label") or "")


def chain_hop_reader_names(hop) -> tuple:
    """THE SPELLINGS A WRITER MAY NAME ONE HOP BY (C9): the printed :func:`chain_hop_name`, the card's
    declared reader words (with and without a leading article), the card's metric label, and the
    driver's own display words --
    every one written for a reader by a producer this turn already ran. Read by the coverage instrument
    (``chain_referenced``) and by lane A's join; each reader folds and length-bounds them its own way."""
    out: list = []
    name = chain_hop_name(hop)
    ident = _hop_identity(str(getattr(hop, "contract", "") or ""), str(getattr(hop, "driver_id", "") or ""),
                          str(getattr(hop, "series_key", "") or ""))
    cands = [name]
    if ident is not None and ident.name:
        cands += [ident.name, ident.name[4:] if ident.name.lower().startswith("the ") else ""]
    # THE CARD'S OWN METRIC LABEL (09-23, lane T's R3): "weekly exports", "drought z-score", "beginning
    # stocks" -- the trade word a writer reaches for, declared on the card for a reader; the series name
    # above replaced it on the page, so it must still JOIN.
    cands.append(_hop_card_label(hop))
    cands.append(humanise(getattr(hop, "driver_id", "") or ""))
    for c in cands:
        c = ascii_text(str(c or "")).strip()
        if c and c not in out:
            out.append(c)
    return tuple(out)


def _hop_phase_words(hop, row) -> str:
    """"<the pole's phase words> is not in force" for a hop that is a POLE of a declared phase pair whose
    phase is not the one the reading is in -- or ``""`` (09-23, item 6).

    THE DEFECT: the 2024 as-of page ranked a La Nina chain first with the note "La Nina sits at the 95th
    percentile of its own record" while ONI read +1.99 degC, the warm phase; max carried a cool-phase
    chain beside a warm-phase stanza. The verdict is the ONE phase producer's (:func:`phase_for_state`,
    read off the row's own newest knowable level) and lane W's stamp (``ChainHop.phase_in_force``) wins
    where the walk carries it -- both read the same producer. The words are the phase book's own
    (``state_conventions.phase_pairs``); no pole id is special-cased."""
    st = getattr(row, "state", None) if row is not None else None
    pf = phase_for_state(st) if st is not None else {}
    if not pf:
        return ""
    d = str(getattr(hop, "driver_id", "") or "")
    if d == pf.get("driver"):
        own, live = str(pf.get("words") or ""), bool(pf.get("in_force"))
    elif d == pf.get("other_driver"):
        own, live = str(pf.get("other_words") or ""), False
    else:
        return ""
    w_in = getattr(hop, "phase_in_force", None)
    if w_in is not None:
        live = bool(w_in)
    if live or not own:
        return ""
    return "%s is not in force" % ascii_text(own)


def _hop_offset_words(row, handles) -> str:
    """On a hop whose row carries an APPLIED same-series offset: "read six months back, the reading whose
    lag lands now" and the newest reading's own handle beside it (09-23, R-16) -- so the chain never
    presents the lagged reading as the current phase. ``""`` on every other row."""
    st = getattr(row, "state", None) if row is not None else None
    if st is None or not _offset_applied(st):
        return ""
    n = int(getattr(st, "offset_months", 0) or 0)
    if n <= 0:
        return ""
    out = "read %s %s back, the reading whose lag lands now" % (words_for_int(n),
                                                                "month" if n == 1 else "months")
    cur = (handles or {}).get("current")
    return out + ((", with the newest reading at [N%d]" % int(cur)) if cur else "")


def chain_state_words(hop, *, handles=None, block=None, phase_words: str = "",
                      offset_words: str = "") -> str:
    """ONE hop's own reading in words -- its standing, its run and the date it is read through.

    A HOP WITH NO SERVED SERIES SAYS SO AND THE CHAIN STILL RENDERS (DESIGN B.1's closing clause,
    threat E3). Existence is a hard filter only in the sense that an absent series cannot be PRINTED;
    it never removes the chain, and the selection clause then shows what the chain WAS carried on.

    **THE LAG WINDOW'S PEAK RIDES HERE, AND IT REPLACES THE RUN RATHER THAN JOINING IT** (orchestrator
    note 5, 2026-09-18). A shock is IN TRANSIT for the length of its declared lag: a reading that
    peaked at the ninety-seventh percentile three months ago and eased to the eightieth is still acting
    on the next hop while the declared lag runs. So where the walk declares a window peak the clause
    prints BOTH readings and where the lag runs to -- and it drops the run words, because "peaked in
    June, now eightieth" states the direction of travel more precisely than "falling since June" does,
    at fewer characters than printing both (MEASURED: +49 against the compact clause, +65 against
    printing the run beside it).

    **THE NAMES ARE THE WALK'S OWN, READ OFF THE SHIPPED DATACLASS** (round-3 MAJOR 2, census blocker
    2). The first cut read ``tail_peak_month`` and ``lag_window_end`` -- names this lane INVENTED in its
    own handoff -- while ``walk.ChainHop`` shipped ``tail_peak_date`` and ``tail_lag_to``. Both
    ``hasattr`` calls were FALSE on 9 of 9 max hops, "peaked" appeared ZERO times on the page at every
    tier, and the pin could not catch it because it asserted against a ``types.SimpleNamespace``
    carrying the invented names. That is the standing string-identity failure (E11) on the W->R seam,
    and it cost the reader the one sentence that reconciles a mid-record percentile with a
    near-maximum tail term: MEASURED, ``cot mm positioning`` printed at the 28th percentile while
    ``chain_score`` scored its tail on the 94th, on 6 of 6 rendered chains.

    THE FIELDS ARE LANE W's AND THEY ARE READ, NEVER REQUIRED: a hop that declares no peak renders
    exactly the compact clause, so this producer moves not one byte on a board whose walk fills
    neither. ``walk.CHAIN_SEAM_FIELDS`` is the ONE spelling of the seam and
    ``test_state_render.py`` pins every name here against a real :class:`walk.ChainHop`."""
    if not getattr(hop, "measured", False):
        # AND NOT "...; its declared direction is carried alone", which the CLAUSE AFTER IT on the same
        # line states in full ("declared in the same direction onto <next>"). MEASURED on the max cell:
        # forty characters on each of four unmeasured hops, restating the next clause, against a
        # 160-character hop budget (round-2 item R-3).
        return "no series is served at this link"
    bits: list = []
    hs = dict(handles or {})
    rid = hop_row_id(hop)
    p_raw = getattr(hop, "percentile", None)
    pk_raw = getattr(hop, "tail_peak_percentile", None)
    pw = percentile_words(p_raw)
    peak = percentile_words(pk_raw)
    peak_at = month_words(str(getattr(hop, "tail_peak_date", "") or ""))
    runs_to = month_words(str(getattr(hop, "tail_lag_to", "") or ""))
    # THE KNOWLEDGE DATE IN ONE SPELLING (09-23 payload drive): the ESR rows carry ``20260917`` with no
    # separators, which on this letters-only row is an eight-digit charged numeral and a date no reader
    # reads. ``narration.iso_date`` is the estate's ONE normaliser (it never invents precision and
    # returns an unparseable value as given), read here rather than re-typed.
    kd = str(getattr(hop, "knowledge_date", "") or "")
    try:
        from leviathan.graphrag.state.narration import iso_date as _iso
        kd = _iso(kd) or kd
    except Exception:                                   # noqa: BLE001 -- a date is printed as given
        pass
    in_transit = bool(peak and peak_at and pw and peak != pw)
    # **EVERY STANDING THIS LINE STATES IS CITED AT THE ADDRESS THAT MINTED IT** (09-23, CONTRACT.md C2).
    # The words stay letters (SB-P carries no charged digit) and each now sits beside its OWN handle --
    # the percentile's, and the window peak's that the hop's SB-1 row mints -- so a writer that
    # re-digitises "the ninety-eighth" is copying a backed figure, and the verifier keeps the hop clause
    # it cut or deleted on three 09-23 pages. A standing with no handle on this page is still stated in
    # words and COUNTED (``chain_hop_unaddressed``), never dropped.
    pct_cite = (" [N%d]" % int(hs["percentile"])) if hs.get("percentile") else ""
    peak_cite = (" [N%d]" % int(hs["peak"])) if hs.get("peak") else ""
    if in_transit:
        bits.append("%s the %s percentile%s in %s, now the %s%s"
                    % (extreme_verb(pk_raw), peak, peak_cite, peak_at, pw, pct_cite))
        _scalar(block, percentile_value(pk_raw), unit="percentile", kind="window_peak_percentile",
                row_id=rid, handle=hs.get("peak"), text=peak)
        _scalar(block, percentile_value(p_raw), unit="percentile", kind="percentile", row_id=rid,
                handle=hs.get("percentile"), text=pw)
        if not peak_cite or not pct_cite:
            _count(block, "chain_hop_unaddressed")
    else:
        bits.append(("at the %s percentile of its own record%s" % (pw, pct_cite)) if pw
                    else tail_words(getattr(hop, "tail", 0.0)))
        if pw:
            _scalar(block, percentile_value(p_raw), unit="percentile", kind="percentile", row_id=rid,
                    handle=hs.get("percentile"), text=pw)
            if not pct_cite:
                _count(block, "chain_hop_unaddressed")
        d = RUN_DIRECTION_WORDS.get(str(getattr(hop, "run_direction", "") or ""), "")
        since = month_words(str(getattr(hop, "run_since", "") or ""))
        if d and since:
            bits.append("%s since %s" % (d, since))
        elif d:
            bits.append(d)
    if kd:
        bits.append("through %s" % kd)
    # THE OFFSET AND THE PHASE, where the caller read them off the hop's own row (R-16, item 6): a
    # reading six months back says so and cites the newest reading beside it, and a pole of a declared
    # phase pair whose phase is not the one in force says so -- in the phase book's own words.
    if offset_words:
        bits.append(offset_words)
    if phase_words:
        bits.append(phase_words)
    out = ", ".join(bits)
    # **WHERE THE LAG RUNS TO IS THE PEAK CLAUSE'S OWN TAIL AND RIDES ONLY WITH IT.** The clause
    # answers "that reading is three months old -- is it still acting?", which is a question only a
    # reading that PEAKED and eased makes a reader ask; on a hop whose peak IS its latest print the
    # words cost 29 characters to restate the band the same line now carries in full ("with a lag of
    # zero to two quarters"), on a line already over its own budget. MEASURED on the live fixture: it
    # rode four suppressed-peak hops at 29 characters each before this cut.
    return (out + (CHAIN_LAG_RUNS_TO % runs_to)) if (in_transit and runs_to) else out


def chain_why_words(ch) -> list:
    """The SELECTION CLAUSE's terms, in DESIGN B.2's own rank order, as desk words.

    Every clause states a FACT about this chain and none states a number: the points ride the trace and
    the figures ride the hop lines' own handles. A chain that earned only the neutral history term says
    so through the clause it DOES earn, which is the honest reading of threat E3 -- the reader is shown
    what the chain was carried on rather than a silence."""
    terms = dict(getattr(ch, "terms", None) or {})
    why: list = []
    rh = ch.receipt_hop
    if float(terms.get("tail") or 0.0) > 0.0 and rh is not None:
        pw = percentile_words(getattr(rh, "percentile", None))
        why.append(CHAIN_WHY_TAIL % pw if pw
                   else CHAIN_WHY_TAIL_BAND % tail_words(getattr(rh, "tail", 0.0)))
    if ch.unnamed_terminal:
        why.append(CHAIN_WHY_UNNAMED)
    elif int(terms.get("reach") or 0) >= 10:
        why.append(CHAIN_WHY_REACH)
    kind = str(getattr(ch, "receipt_kind", "") or "")
    if kind == "open":
        why.append(CHAIN_WHY_EVENT_OPEN)
    elif kind == "closed":
        why.append(CHAIN_WHY_EVENT_CLOSED)
    elif kind == "mechanism":
        why.append(CHAIN_WHY_EVENT_DOC)
    if int(terms.get("asymmetry") or 0) >= 10:
        why.append(CHAIN_WHY_ASYM)
    if getattr(ch, "curated", ""):
        why.append(CHAIN_WHY_CURATED)
    return why


def _points_words(v) -> str:
    """A rank term's POINTS in WORDS, ROUNDED TO THE NEAREST HALF -- ``7.4`` -> ``seven and a half``,
    ``21.9`` -> ``twenty-two``.

    **THE FIRST CUT TRUNCATED AND THEN SAID "AND A HALF", AND EVERY RENDERED CHAIN PRINTED A FIGURE ITS
    OWN BACKING CONTRADICTED** (round-3 MAJOR 1, census blocker 1). Its docstring claimed "the terms
    land on halves by construction"; MEASURED on the live fixture they do not -- ``walk.chain_score``
    rounds each term to ONE DECIMAL over a weighted share, so ``21.9``, ``23.9``, ``24.8`` and ``11.8``
    are ordinary values, and truncation rendered them "twenty-one and a half", "twenty-three and a
    half", "twenty-four and a half", "eleven and a half": wrong by up to 0.4 points on 1 of 1 / 2 of 2 /
    3 of 3 rendered chains at quick / deep / max, always UNDERSTATING the term. This line's whole
    declared reason (DESIGN B.2) is that a census can check each pair against
    ``Board.trace()["chains"][*]["terms"]``, and a printed figure its own trace contradicts is a
    BACKING FAILURE, not a rounding taste.

    So the value is snapped to the nearest half FIRST and the words are spelled off the snapped
    number -- one expression, no new term, and the pair a census reads is now the pair the page prints.
    A digit here would be a charged digit on a class outside :data:`FIGURE_CLASSES`; same rule as
    :func:`percentile_words`, one term over."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return ""
    h = round(abs(f) * 2.0) / 2.0
    n = int(h)
    return ("minus " if f < 0 else "") + words_for_int(n) + (" and a half" if h != n else "")


def chain_arithmetic_words(ch) -> str:
    """**DESIGN B.2's ARITHMETIC IN ONE LINE, AND THE DATA SCOPE IT WAS SCORED ON.**

    THE ORCHESTRATOR'S RULING OF 2026-09-18 (round-2 item R-3, and note 6): the selection clause names
    its TERMS AND ITS POINTS -- "falsifiable on the page" was B.2's whole reason for the line, and the
    round-1 cut named the terms and left the points on the trace. The points are said in WORDS
    (:func:`_points_words`) because a chain row rides SB-P and SB-P carries no charged digit; the
    census can still check every pair against ``Board.trace()["chains"][*]["terms"]``.

    **AND A LOW SCORE MUST READ AS SCARCE DATA, NEVER AS A BAD CHAIN** (note 6: each anchor is judged
    on the data it has). So the line states what the chain was SCORED ON -- how many of the seven terms
    earned anything, how many hops carry no served series, and, where the walk declares them, that this
    market serves no buffer series or carries no dated events at all. A term that scored zero for want
    of a series is a different fact from a term that scored zero on a reading, and the page says which.

    THE SCOPE FACTS THE RENDER CAN COMPUTE, IT COMPUTES (the terms it was handed, the hops it is
    rendering); the two it cannot -- whether this market has ANY buffer series and whether the corpus
    carries ANY dated event for it -- are read off ``Chain.scope`` when the walk declares it and are
    silent otherwise. Nothing here is required: a chain with no ``scope`` renders the first two facts
    and no third.

    **THE DICT IS ``Chain.scope``, AND ITS KEYS ARE ``buffer_series`` / ``events_in_corpus``**
    (round-3 MAJOR 5, census blocker 2). The first cut read a ``Chain.data_scope`` attribute this lane
    invented in its own handoff against a walk that had already shipped ``Chain.scope``:
    ``hasattr(c, "data_scope")`` was FALSE on every rendered chain, so ruling 6(b)'s absence sentences
    could not print on the first anchor that served no buffer series. ``walk.CHAIN_SEAM_FIELDS`` is
    now the ONE spelling of this seam (``Chain.scope.buffer_series``,
    ``Chain.scope.events_in_corpus``) and the pin resolves every name here against a real
    :class:`walk.Chain` rather than against a stand-in. ``None`` -- an anchor the walk could not read
    -- stays SILENT: only an explicit ``False`` is an absence this page states.

    THE COUNT OF SCORED TERMS IS COMPUTED OFF THE PAIRS THIS LINE PRINTS and not read off
    ``scope["terms_scored"]``, deliberately: the sentence "six of seven terms scored" must agree with
    the six pairs beside it on the SAME line, and a count taken from anywhere else could disagree with
    the enumeration a reader is looking at. The walk publishes the same number by the same rule over
    the same dict, and a pin asserts the two agree on every rendered chain -- so a drift is a RED DECK
    rather than a contradiction on the page."""
    from leviathan.graphrag.state.walk import CHAIN_TERMS
    terms = dict(getattr(ch, "terms", None) or {})
    pairs = []
    for t in CHAIN_TERMS:
        try:
            v = float(terms.get(t) or 0.0)
        except (TypeError, ValueError):
            v = 0.0
        if v > 0.0:
            pairs.append("%s %s" % (CHAIN_TERM_WORDS.get(t, humanise(t)), _points_words(v)))
    scope = ["%s of %s terms scored" % (words_for_int(len(pairs)), words_for_int(len(CHAIN_TERMS)))]
    unmeasured = sum(1 for h in (ch.hops or ()) if not getattr(h, "measured", False))
    if unmeasured:
        # "LINK", NOT "HOP" (09-23 desk vocabulary, CONTRACT.md C13): the instrument's word for a step
        # in a chain is the desk's "link"; the count and its noun are unchanged.
        scope.append("%s %s no series" % (words_for_int(unmeasured),
                                          "link carries" if unmeasured == 1 else "links carry"))
    ds = dict(getattr(ch, "scope", None) or {})
    if ds.get("buffer_series") is False:
        scope.append("this market serves no buffer series")
    if ds.get("events_in_corpus") is False:
        scope.append("this turn retrieved no dated action for this market")
    return "%swhy: %s; %s." % (CHAIN_SUB_PREFIX, ", ".join(pairs) or "no term scored",
                               ", ".join(scope))


def sb_chain_positioning(ch, *, handle=None) -> str:
    """WHERE THE CROWD IS, AND WHICH WAY (owner, 2026-09-18, orchestrator note 1: "how does it know how
    convex the market is?").

    A managed-money net position at a tail of its OWN record is an amplifier when it sits the same way
    the chain argues and CONVEXITY when it sits against it -- the risk a PM's own read flagged twice in
    the 2026-09-16 smoke. This row states which of the two it is, in words, and cites the board's own
    positioning row where this page carries its address; a standing with no address is a quantitative
    claim a reader cannot check, which is the rule the terminal's own standing already keeps.

    THE FACT IS THE WALK's (``Chain.positioning``); the SENTENCE is this page's, and the row is SILENT
    where the walk declares nothing -- no positioning row, no line, never a zero wearing a claim."""
    p = dict(getattr(ch, "positioning", None) or {})
    pw = percentile_words(p.get("percentile"))
    if not pw:
        return ""
    cite = " [N%d]" % int(handle) if handle else ""
    if p.get("against"):
        return ("%spositioning%s: the crowd sits at the %s percentile of its own record the other way "
                "from this sequence, which is what makes a reversal abrupt."
                % (CHAIN_SUB_PREFIX, cite, pw))
    return ("%spositioning%s: the crowd sits at the %s percentile of its own record the same way as "
            "this sequence, which amplifies it rather than cushioning it."
            % (CHAIN_SUB_PREFIX, cite, pw))


def sb_chain_head(ch, *, i: int, n: int, why=()) -> str:
    """The chain's FIRST line: which of the carried chains it is and where it goes.

    **THE SELECTION CLAUSE MOVED TO ITS OWN LINE** (round-2 item R-3): the head is the chain's IDENTITY
    and :func:`chain_arithmetic_words` is its arithmetic, which is both the shape the ruling asks for
    and the cheaper one -- the head carried 234 to 306 characters on the measured cells because the
    identity and the whole desk-words clause shared one sentence. ``why`` is kept in the signature and
    is spent by :func:`sb_chain_one_line`, the form BELOW the print line, where one line is all there
    is and the clause has nowhere else to ride."""
    cross = str(ch.terminal or "") != str(ch.contract or "")
    # THE HEAD NAMES ITS OWN TOP HOP, and that is a COVERAGE fix as much as a reading one. The row's
    # reference test is the token groups it mints, and a head that named only the far market scored
    # MISSED against the block's own rendered text on the max cell -- an instrument charging the
    # writer for a word the row never wrote. A chain's identity is where it starts and where it ends;
    # the head now carries both.
    # 09-23 (CONTRACT.md C9): the top hop is named by ITS SERIES (:func:`chain_hop_name`), never by the
    # driver id that routes to it -- the same spelling the hop line and lane A's join use.
    _from = ("from %s " % chain_hop_name(ch.hops[0])) if ch.hops else ""
    where = ("%sto %s" % (_from, board_label(ch.terminal)) if cross
             else "%sinto the %s price" % (_from, board_label(ch.contract)))
    named = " -- a market this question did not name" if ch.unnamed_terminal else ""
    # "first of one" IS NOT ENGLISH AND THE ANTI-PADDING LAW MAKES IT A COMMON CASE. Rendering fewer
    # than K is the correct outcome when fewer clear the line (`watch.WATCH_SELECTION_CLAUSE`'s own
    # rule), and the free tier's K IS one, so the singular is the tier's ordinary shape and not an
    # edge case.
    which = ("the one this page carries" if int(n) <= 1
             else "%s of %s" % (ordinal_words(i), words_for_int(n)))
    # THE SEAT IT WAS HELD FOR, WHERE IT WAS HELD ONE (owner ruling 2026-09-22). It rides the HEAD
    # rather than the hop line because it is one fact about the CHAIN and the hop line carries three
    # facts about a hop -- a label repeated on every hop would pay for the same word three times on a
    # line already over its own budget.
    slot = chain_slot_words(ch)
    return "%s%s, %s%s%s." % (CHAIN_HEAD_PREFIX, which, (slot + ", ") if slot else "", where, named)


def sb_chain_hop(ch, i: int, *, handle=None, terminal_handle=None, handles=None, block=None,
                 phase_words: str = "", offset_words: str = "") -> str:
    """ONE HOP in DESIGN B.1's order: the node in reader words, its reading cited at the address that
    minted it, the run, the date it is read through, the DECLARED sign onto the next hop with the band,
    and the verdict today's readings return on that declared direction.

    THE NODE IS ``humanise(driver_id)`` AND NOT ``row_words``, because a chain is ONE contract by
    construction (``walk.Chain.contract``) and its head line has already named that market. The
    TERMINAL is the one place a second market can appear and it is named with :func:`board_label`."""
    hop = ch.hops[i]
    nxt = ch.hops[i + 1] if i + 1 < len(ch.hops) else None
    hs = dict(handles or {})
    if handle and not hs.get("level"):
        hs["level"] = handle
    cite = " [N%d]" % int(hs["level"]) if hs.get("level") else ""
    if nxt is not None:
        onto, onto_cite = chain_hop_name(nxt), ""
    elif ch.cross:
        onto = board_label(ch.terminal)
        # THE FAR READING'S STANDING IS PRINTED ONLY WHERE THIS PAGE CARRIES ITS ADDRESS. The far
        # market's own reading lives in ``bd.series`` and NOT in ``bd.rows`` (a board carries ANCHOR
        # boards only), so on most turns no ``[N]`` on this page points at it -- and a standing stated
        # with no address is a quantitative claim a reader cannot check, which is the one thing a
        # letters-only class must not smuggle past the digit rule. Where the handle IS there (a
        # multi-anchor board that rendered the far row) the standing rides with it.
        onto_cite = " [N%d]" % int(terminal_handle) if terminal_handle else ""
        pw = percentile_words(getattr(ch, "terminal_percentile", None))
        if pw and terminal_handle:
            onto_cite += ", whose own reading sits at the %s percentile of its record" % pw
    else:
        onto, onto_cite = "the %s price" % board_label(ch.contract), ""
    way = chain_edge_words(ch.edge_signs[i] if i < len(ch.edge_signs) else "")
    # **THE BAND PRINTS ONLY WHERE ITS DECLARED RELATION IS THE ONE THE CLAUSE ASSERTS** (round-4
    # MAJOR 1, orchestrator ruling). Round 2 cut the band on two false claims and round 3 put it back
    # on EVERY declared hop -- and the restore shipped the figure under the wrong predicate on 23 of 23
    # printed bands across both cells and all three tiers (MEASURED, `r2d/R4_cells_BEFORE.json`).
    #
    # ``ChainHop.lag_band`` IS ``parse_lag(dag_node.lag)`` (``walk.py:1548`` -> ``:4429``) -- the lag the
    # DAG declares for that node -- and this line's clause asserts the edge onto the NEXT HOP, so
    # printing a driver fact inside an edge predicate told the reader that La Nina takes one to two
    # quarters to reach DROUGHT, when one to two quarters is its declared lag into this market. The
    # estate's own standing rule is the writer seam's: a correction that names the wrong row is
    # strictly worse than the word it replaced.
    #
    # SO IT RIDES THE TERMINAL EDGE AND NOTHING ELSE: the last hop, where the clause's own "onto"
    # already names what the edge runs into, so the band and the predicate name ONE relation. A chain
    # whose terminal is a FAR market prints no band, because the cross edge's OWN declared lag
    # (``Chain.cross["lag"]``) is the surface that case wants and it is the orchestrator's to rule on;
    # this producer never guesses one.
    #
    # **AND THE CLAUSE NAMES NO TARGET METRIC** (round-5 blocker 11). Round 4 printed "with a declared
    # lag of <band> TO THE PRICE" on the premise -- written into this comment and into the pin's own
    # docstring -- that "every node of the anchor's DAG declares ``target_metric: price``". MEASURED
    # over the 36 ``configs/graphrag/causal/*.yaml``: 1,208 nodes declare ``price`` and **49 declare
    # something else, in SIX DAGs** (``rough_rice_cbot`` 22 of 33, ``cotton`` 13 of 37, the four wheats
    # 6-8 each; values yield, production, export, stock, import, drought, area). ``NodeRow.target_metric``
    # is on the BOARD (``board.py:719``) and ``ChainHop`` carries none, so this producer cannot read the
    # relation those three words asserted -- and a rice hop whose 0-2 quarter band is declared against
    # YIELD would have printed it "to the price". The band is the hop's own declared lag and the clause
    # now says exactly that and no more; where the hop's target metric reaches the seam, naming it is
    # one clause and a ruling, not a guess. It also ends the noun this lane's R4-O1 recorded
    # ("onto the CBOT soybeans price with a declared lag of ... to the price").
    #
    # AND THE ABSENCE WORDING IS GUARDED (round-3 MINOR 3): ``band_words(None)`` is an honest absence
    # sentence in the SB-E row it was written for ("a lag the table does not carry") and a doubled noun
    # here ("with a declared lag of a lag the table does not carry"). A hop whose band the table does
    # not carry prints no band clause; the hop line still states its reading, its direction and its
    # verdict, and nothing is deleted because there was no figure to delete.
    state = chain_state_words(hop, handles=hs, block=block, phase_words=phase_words,
                              offset_words=offset_words)
    _terminal_edge = (nxt is None) and not ch.cross
    _band = hop.lag_band
    lag = ""
    if _terminal_edge and _band is not None and _band.min_q is not None:
        lag = " with a lag of %s" % band_words(_band)
        _band_scalars(block, _band)
    # **THE EDGE IN DESK WORDS** (09-23, CONTRACT.md C13): the relation is what the MODEL EXPECTS, never
    # what "the graph declares" -- the sign words are still ``rows.SIGN_WORDS``' three, read through
    # :func:`chain_edge_words`, and the no-committed-direction sign keeps its own verb because "expects
    # it to move X with no committed direction" is not a sentence.
    _sg = str(ch.edge_signs[i] if i < len(ch.edge_signs) else "")
    if way and _sg == "0":
        edge = "the model links it to %s%s %s%s" % (onto, onto_cite, way, lag)
    elif way:
        edge = "the model expects it to move %s%s %s%s" % (onto, onto_cite, way, lag)
    else:
        edge = "carried onto %s%s with no direction set between them" % (onto, onto_cite)
    tail = CHAIN_AGREEMENT_CLAUSE.get(str(ch.agreements[i]) if i < len(ch.agreements) else "", "")
    return "%s%s%s: %s; %s%s." % (CHAIN_SUB_PREFIX, chain_hop_name(hop), cite,
                                  state, edge, (", " + tail) if tail else "")


def sb_chain_record(ch, *, block=None) -> str:
    """The RECORD line: how many past firings of this reading the next hop followed, in the past tense
    with its sample size (DESIGN B.2, threat E7 -- history, never a forecast).

    ONE PRODUCER: ``walk.chain_history_words`` builds the sentence off the same stat that WEIGHTED the
    chain, so the number a reader is handed and the number the rank used cannot drift."""
    return "%srecord: %s." % (CHAIN_SUB_PREFIX, chain_record_words(ch.history or {"n_firings": 0},
                                                                   block=block))


def chain_record_words(h: dict, *, block=None) -> str:
    """**THE HISTORY LINE'S PAGE TWIN, IN DESK ENGLISH** (owner, 09-23; CONTRACT.md C13).

    ``walk.chain_history_words`` is the TRACE's sentence and stays byte-identical there: "in five of
    eight measured past firings of this reading the next hop moved the declared way inside the declared
    window; three did not; eight more published no second reading inside it". The owner asked whether a
    desk analyst follows that, and the answer is no -- "firing", "hop", "the declared way" and "the
    declared window" are the instrument's words. This is the SAME FACTS -- ``n_firings`` (the measured
    subset), ``aligned``, ``at_odds``, ``undetermined``, ``unmeasured``, read off the one stat that
    weighted the chain -- in the words a desk uses, so the page and the trace can never disagree on a
    number: "of the past times this reading sat this far out, eight had a next reading to measure: the
    next link moved the way the model expects in five and went the other way in three; eight more times
    no next reading was published inside the lag the model allows".

    A THIN RECORD STILL SAYS SO, and still says WHY when the reason is the next link's own publication
    cadence -- the fact the trace branch was written to keep (a weekly reading against an annual next
    link fires often and is never measured). Every count is in words (SB-P is letters-only) and is
    registered in the served-scalars pool under the record's own noun, ``firings`` (C4)."""
    n = int(h.get("n_firings") or 0)
    un = int(h.get("unmeasured") or 0)
    al = int(h.get("aligned") or 0)
    _scalar(block, n, unit="firings", kind="firings_count", text=words_for_int(n))
    if un:
        _scalar(block, un, unit="firings", kind="firings_count", text=words_for_int(un))
    try:
        from leviathan.graphrag.state.walk import CHAIN_HISTORY_THIN_N as _thin_n
    except Exception:                                   # noqa: BLE001 -- the walk's floor, read not re-typed
        _thin_n = 3
    if n < int(_thin_n):
        if not n and un:
            return ("the record is thin: this reading sat this far out %s %s before, and on none of "
                    "them was a next reading published inside the lag the model allows"
                    % (words_for_int(un), "time" if un == 1 else "times"))
        if not n:
            return ("the record is thin: it holds no past time this reading sat this far out with a "
                    "next reading to measure")
        return ("the record is thin: only %s of the past times this reading sat this far out %s a "
                "next reading to measure" % (words_for_int(n), "has" if n == 1 else "have"))
    _scalar(block, al, unit="firings", kind="firings_aligned", text=words_for_int(al))
    odds = h.get("at_odds")
    und = h.get("undetermined")
    parts = ["the next link moved the way the model expects in %s" % words_for_int(al)]
    if odds is None and und is None:
        rest = n - al
        if rest:
            parts.append("did not in %s" % words_for_int(rest))
    else:
        if int(odds or 0):
            parts.append("went the other way in %s" % words_for_int(int(odds)))
        if int(und or 0):
            parts.append("settled no direction in %s" % words_for_int(int(und)))
    body = parts[0] if len(parts) == 1 else (", ".join(parts[:-1]) + " and " + parts[-1])
    tail = ("" if not un else "; %s more %s no next reading was published inside the lag the model "
            "allows" % (words_for_int(un), "time" if un == 1 else "times"))
    return ("of the past times this reading sat this far out, %s had a next reading to measure: %s%s"
            % (words_for_int(n), body, tail))


#: THE BACKSTOP SENTENCE'S CEILINGS (CONTRACT.md C9, threat A-3): one sentence, at most this many words
#: and this many named nodes -- a chain SENTENCE, never an enumeration of the chain.
CHAIN_PAGE_SENTENCE_MAX_WORDS: int = 45
CHAIN_PAGE_SENTENCE_MAX_NODES: int = 3


def chain_page_sentence(ch, row_handles: dict) -> str:
    """ONE desk-English sentence for ONE rendered chain -- lane A's backstop, appended only where the
    writer narrated no chain the block carried (CONTRACT.md C9).

    "One chain the data carries runs from <hop 1> [Nl] through <hop 2> [Nl] to <terminal>; the readings
    agree with the direction the model expects at <k> of <n> links." DIGIT-FREE except the ``[N]``
    handles (each the hop's own LEVEL address from ``row_handles``), at most
    :data:`CHAIN_PAGE_SENTENCE_MAX_NODES` named nodes (the first hop, the last hop, the terminal) and
    :data:`CHAIN_PAGE_SENTENCE_MAX_WORDS` words -- a middle node is dropped before the limit is broken.
    ``""`` when no hop carries a handle: a sentence with no address would be a claim the page cannot
    back, and the backstop is a correction that computes, never one that asserts."""
    hops = list(getattr(ch, "hops", None) or ())
    if not hops:
        return ""
    rh = dict(row_handles or {})

    def _cite(hop) -> str:
        hs = rh.get((getattr(hop, "contract", ""), getattr(hop, "driver_id", ""))) or {}
        lv = hs.get("level") if isinstance(hs, dict) else hs
        return (" [N%d]" % int(lv)) if lv else ""

    if not any(_cite(h) for h in hops):
        return ""
    cross = str(getattr(ch, "terminal", "") or "") != str(getattr(ch, "contract", "") or "")
    terminal = (board_label(ch.terminal) if cross
                else "the %s price" % board_label(getattr(ch, "contract", "")))
    first, last = hops[0], hops[-1]
    agree = sum(1 for v in (getattr(ch, "agreements", None) or ()) if str(v) == "aligned")
    links = len(getattr(ch, "agreements", None) or ())
    tail = ("; the readings agree with the direction the model expects at %s of %s %s"
            % (words_for_int(agree), words_for_int(links), "link" if links == 1 else "links"))
    forms = []
    if last is not first:
        forms.append("One chain the data carries runs from %s%s through %s%s to %s%s."
                     % (chain_hop_name(first), _cite(first), chain_hop_name(last), _cite(last),
                        terminal, tail))
    forms.append("One chain the data carries runs from %s%s to %s%s."
                 % (chain_hop_name(first), _cite(first), terminal, tail))
    for f in forms:
        if len(f.split()) <= CHAIN_PAGE_SENTENCE_MAX_WORDS:
            return ascii_text(f)
    return ""


#: The card the chain's OUTCOME row is computed over, and the derived metric it computes.
#:
#: **THE CALL RECORD IS THE READER'S ``## Sources`` LINE AND THE DRILL-DOWN's LOCATOR** (round-2 item
#: R-1). The first cut passed ``table="state_board_chain"`` and ``metric="front_price_move_after_
#: firing"``, and MEASURED through the real producer (``citations.from_number``) that rendered
#: ``STATE BOARD CHAIN front_price_move_after_firing CBOT soybeans MYthe front price's own 2025-06-16
#: to 2026-09-04 window = 2.1 percent`` with ``date=None``: a machine id headlining the Sources line
#: (the class ``citations.py:1458-1467`` names in its own words), the metric as its raw snake_case id,
#: the "MYMY" weld (``_period_label`` MY-prefixes any period that neither starts with ``MY`` nor
#: contains ``..``), and no vintage at all. The magnitude is computed off ``bd.tape``, whose own row
#: (:func:`sb_tape`) cites this card -- so the card was there all along.
#:
#: THE METRIC IS THE DERIVED ONE AND NOT ``settle``: the figure is a PERCENT CHANGE over a declared
#: band, and labelling it with the level's name ("settlement price ... = 2.1 percent") is the wrong
#: label rather than a shorter one. :func:`sb_tape` spells its own derived metrics the same way
#: (``settle change over {window}``).
CHAIN_OUTCOME_TABLE: str = "silver_futures_eod"
CHAIN_OUTCOME_METRIC: str = "settle percent change over the declared band"

#: The two ISO dates a price window's scope sentence names, in order -- the only two facts this render
#: needs out of ``walk.chain_outcome``'s prose ``scope``. Lane W is asked for the dates as fields in
#: ``r2b/HANDOFF_R_render.md``; until they land, the sentence's own dates are read here rather than
#: guessed, and a scope naming none leaves the period and the vintage EMPTY rather than inventing one.
_WINDOW_ISO_RX = re.compile(r"(\d{4}-\d{2}-\d{2})\D+(\d{4}-\d{2}-\d{2})")


def _outcome_window(o: dict) -> tuple:
    """``(period in the estate's ".." form, the window's FAR date)``, or ``("", "")``."""
    for k in ("window_from", "window_to"):                      # lane W's fields, when they land
        if not str(o.get(k) or ""):
            break
    else:
        return ("%s..%s" % (str(o["window_from"])[:10], str(o["window_to"])[:10]),
                str(o["window_to"])[:10])
    m = _WINDOW_ISO_RX.search(str(o.get("scope") or ""))
    return ("%s..%s" % (m.group(1), m.group(2)), m.group(2)) if m else ("", "")


def _firings_read_words(o: dict) -> str:
    """``"<m> of <n> firings carry a price reading over the band"`` -- ONE NOUN, BOTH NUMBERS, AND THE
    PRODUCER'S OWN (round-4 census 5).

    ``walk.chain_outcome`` publishes ``n_in`` (how many past firings of this reading the chain found)
    beside ``n`` (how many of those the anchor's own price array could actually read over the declared
    band). The page printed the SUBSET alone -- "across five past firings" -- while the record line two
    rows above printed "in eleven of fourteen past firings of this reading": two counts of one
    population under one noun, with nothing on the page saying that the five were a subset of the
    fourteen. ``walk.chain_outcome_words`` closed exactly this for the TRACE (review MA-5) and the
    PAGE was left on the old spelling; ``Chain.outcome["n_in"]`` was one of the four declared seam
    fields the render read nowhere (census section 9).

    ONE PRODUCER FOR BOTH BRANCHES: the row that MINTS (:func:`sb_chain_outcome`) and the letters-only
    row that says the sample was too thin (:func:`sb_chain_outcome_absent`) print the same clause, so
    the two can never state the sample two ways. Where the walk publishes no denominator the clause
    falls back to the subset's own count and says nothing it cannot back."""
    n, n_in = int(o.get("n") or 0), int(o.get("n_in") or 0)
    # 09-23 DESK VOCABULARY (CONTRACT.md C13): the population is "the past times this reading sat this far
    # out" -- the record line's own noun, one row up -- never the instrument's "firings". The two numbers
    # and which is the subset of which are unchanged.
    if n_in <= 0:
        return ("%s past %s this reading sat this far out %s a price reading over the band"
                % (words_for_int(n), "time" if n == 1 else "times",
                   "carries" if n == 1 else "carry"))
    if n == n_in:
        # THE SUBSET IS THE WHOLE POPULATION: one number, said once, and still named as all of them.
        return ("the one past time this reading sat this far out carries a price reading over the band"
                if n == 1 else
                "all %s past times this reading sat this far out carry a price reading over the band"
                % words_for_int(n))
    return ("%s of the %s past %s this reading sat this far out %s a price reading over the band"
            % (words_for_int(n), words_for_int(n_in), "time" if n_in == 1 else "times",
               "carries" if n == 1 else "carry"))


def sb_chain_outcome(n: int, ch, *, asof: str = "", block=None) -> tuple:
    """SB-O: what the anchor's own front price DID after each of those firings -- past tense, with its
    sample size, its middle and both ends of its range, each under its own handle.

    **IT IS THE ONE CHAIN ROW THAT MINTS**, because the move is a magnitude no other row on this page
    carries: the hops' figures are on their own state lines, but "the front price moved a middle two
    point one percent over the declared window" is arithmetic this leg computed. So it rides SB-O --
    the class that already means "a move over the band declared from that state" -- with ONE HANDLE PER
    MAGNITUDE, exactly as :func:`sb_analog_outcome` does.

    **AND THE SCOPE IS IN THE SENTENCE** (the S8 recon's own measurement): ``bd.tape`` is keyed by
    anchor slug and its window is about three hundred and thirty sessions by declaration, so an outcome
    over a firing older than about eighteen months is not constructible at zero reads.
    ``walk.chain_outcome`` names the window it had; this row prints that name rather than letting the
    reader take it for the whole record.

    **AND THE CALL RECORD NAMES THE CARD THE FIGURE WAS COMPUTED OVER** (round-2 item R-1) -- the
    tape's own card, the contract SLUG (the display name is the label's job, the locator's job is the
    address a drill-down re-runs), the window in the estate's ``..`` period form, this board's as-of
    and the window's far date as the vintage. See :data:`CHAIN_OUTCOME_TABLE` for what the first cut
    rendered instead, measured through the real producer. An outcome computed on some OTHER basis --
    lane C's pair spread through ``walk.stage2(spread_fn=...)`` -- declares its own card on the outcome
    dict and this row reads it, exactly as :func:`sb_analog_outcome` reads its own."""
    o = dict(getattr(ch, "outcome", None) or {})
    if not int(o.get("n") or 0) or o.get("median_move") is None:
        return "", []
    band = ch.hops[ch.receipt_index].lag_band if ch.hops else None
    unit = str(o.get("unit") or "percent")
    per, far = _outcome_window(o)
    q = {"table": str(o.get("table") or CHAIN_OUTCOME_TABLE),
         "metric": str(o.get("metric") or CHAIN_OUTCOME_METRIC),
         "commodity": str(ch.contract or ""), "country": o.get("country"),
         "period": per, "asof": str(asof or "")}
    med, lo, hi = float(o["median_move"]), float(o.get("low") or 0.0), float(o.get("high") or 0.0)
    calls = [sb_call(value=round(med, 4), unit=unit, knowledge_date=far, **q),
             sb_call(value=round(lo, 4), unit=unit, knowledge_date=far, **q),
             sb_call(value=round(hi, 4), unit=unit, knowledge_date=far, **q)]
    way = ("" if not (ch.declared_sign and o.get("share_declared_way") is not None)
           else ", %s of them the way the model expects" % words_for_int(int(o["share_declared_way"])))
    for _k, _v in ((n, med), (n + 1, lo), (n + 2, hi)):
        _scalar(block, round(_v, 4), unit=unit, kind="outcome_move", handle=_k, text=_fmt(_v))
    _scalar(block, int(o.get("n") or 0), unit="firings", kind="firings_count",
            text=words_for_int(int(o.get("n") or 0)))
    if int(o.get("n_in") or 0):
        _scalar(block, int(o["n_in"]), unit="firings", kind="firings_count",
                text=words_for_int(int(o["n_in"])))
    # THE SAMPLE AND ITS DENOMINATOR, IN THE PRODUCER'S OWN NOUN (census 5). See
    # :func:`_firings_read_words`: the count beside the median used to be the SUBSET alone.
    line = ("- [N%d] the %s front price over the band declared from that state, %s: moved a middle "
            "%s %s, %s%s; [N%d] softest moved %s %s; [N%d] strongest moved %s %s"
            % (n, board_label(ch.contract), band_words(band), _fmt(med), unit,
               _firings_read_words(o), way, n + 1, _fmt(lo), unit, n + 2, _fmt(hi), unit))
    return re.sub(r"\s+", " ", line), calls


def sb_chain_outcome_absent(ch) -> str:
    """The letters-only half of the row above: a chain that HAS a record and no price to price it with
    says so. A silence where a price line belongs reads as "nothing happened", which is a claim."""
    o = dict(getattr(ch, "outcome", None) or {})
    if int(o.get("n") or 0) and o.get("median_move") is not None:
        return ""
    # THE DENOMINATOR RIDES THE ABSENCE ROW TOO, because this is the branch the fixture's own rendered
    # chains take and "those firings" named a population the reader could not count (census 5). ONE
    # producer for both rows (:func:`_firings_read_words`), so the sample is never stated two ways.
    if int(o.get("n") or 0):
        return ("%sprice record: %s, and that sample is too thin for a middle figure."
                % (CHAIN_SUB_PREFIX, _firings_read_words(o)))
    if int(o.get("n_in") or 0):
        return ("%sprice record: %s." % (CHAIN_SUB_PREFIX, _firings_read_words(o)))
    return ("%sprice record: the front price here does not reach back to those past times."
            % CHAIN_SUB_PREFIX)


def sb_chain_one_line(ch, *, i: int, n: int, why=()) -> str:
    """A chain rendered in ONE line, carrying its own selection clause AND THE TRUE CAUSE OF ITS LENGTH.

    THE ORCHESTRATOR'S RULING OF 2026-09-17: the page decides FULL versus ONE LINE, never zero, so no
    turn is chain-less while the graph carried one. The reader is told what the chain was carried on
    rather than shown nothing -- the same law every cut on this page keeps.

    **AND THE CAUSE IS READ OFF ``Chain.slot`` RATHER THAN ASSERTED** (round-5 blockers 7 and 10). See
    :data:`CHAIN_ONE_LINE_WORDS` for the measurement: with ``full`` stamped in SEAT order the only
    chain that reaches this producer is one seated past the ``K + 2`` bound, and the row told its
    reader it sat below a selection line the producer's own ``below_print_line = 0`` said nothing sat
    below. A held seat now states the bound; a chain with no seat -- the only caller a print-line cut
    can still mint -- keeps the old sentence, so the correction adds a reading and removes none."""
    seq = ", then ".join(chain_hop_name(h) for h in ch.hops)
    named = " -- a market this question did not name" if ch.unnamed_terminal else ""
    which = ("the one this page carries" if int(n) <= 1
             else "%s of %s" % (ordinal_words(i), words_for_int(n)))
    # A HELD SEAT KEEPS ITS LABEL ON THE ONE-LINE FORM TOO (owner ruling 2026-09-22). A chain held for
    # the question's subject and rendered below the print line is exactly the row a reader most needs
    # the reason for -- it is short BECAUSE it scored low, and the reason it is on the page at all is
    # the seat, not the score.
    slot = chain_slot_words(ch)
    cause = CHAIN_ONE_LINE_WORDS["seated" if slot else "below"]
    return ("%s%s, %s%s: %s, reaching %s%s; it is here for %s."
            % (CHAIN_HEAD_PREFIX, which, (slot + ", ") if slot else "", cause, seq,
               board_label(ch.terminal or ch.contract), named,
               _and_list(list(why)) or "the sequence it composes"))


def sb_chain_sides(rendered) -> str:
    """WHERE THE CARRIED CHAINS DISAGREE, or that they do not, and WHICH HOP runs against the direction
    declared for it (owner, 2026-09-17: disagreement is where convexity lives and must be STRUCTURAL).

    **IT IS COMPOSED HERE AND NOT TAKEN FROM ``walk.chain_disagreement_words``**, which builds the same
    fact for the TRACE and spells it "the direction the graph declares for it" -- ``the graph`` is a
    charged token (``register.DESK_REGISTER_TOKENS``) and every chain row on this page is held to zero
    charges. The FACTS are the walk's (``Chain.side``, ``Chain.against_hops``); the SENTENCE is this
    page's, which is the split every other row here keeps. The request to fold the two spellings back
    into one producer is recorded in the lane's handoff note."""
    rendered = list(rendered or ())
    if not rendered:
        return ""
    sides = {str(c.side) for c in rendered}
    one = len(rendered) == 1
    if "for" in sides and "against" in sides:
        head = "these chains point opposite ways for this market"
    elif sides == {"unsettled"}:
        head = ("the one chain carried here settles no direction for this market today" if one else
                "not one of these chains settles a direction for this market today")
    elif len(sides) == 1:
        only = "higher" if "for" in sides else "lower"
        head = ("the one chain carried here points %s for this market, and no other chain on this page "
                "points the other way" % only if one else
                "every chain carried here points %s for this market, and none points the other way"
                % only)
    else:
        head = "one of these chains settles a direction for this market and the others do not"
    # THE HOPS RUNNING AGAINST THEIR DIRECTION, NAMED BY THEIR SERIES AND FOLDED ON THE HOP'S OWN
    # IDENTITY (09-23, C9 / E11): ``against_hops`` carries driver ids per chain, so each is resolved on
    # ITS OWN chain's hop object -- a driver id alone names a different reading on another board.
    seen: list = []
    names: list = []
    for c in rendered:
        by_id = {str(getattr(h, "driver_id", "") or ""): h for h in (c.hops or ())}
        for a in c.against_hops:
            hop = by_id.get(str(a))
            key = (str(getattr(hop, "contract", "") or c.contract), str(a))
            if key in seen:
                continue
            seen.append(key)
            nm = chain_hop_name(hop) if hop is not None else humanise(a)
            if nm not in names:
                names.append(nm)
    if not seen:
        return ("%ssides: %s; no link on %s runs against the direction the model expects for it."
                % (CHAIN_SUB_PREFIX, head, "it" if one else "them"))
    return ("%ssides: %s; %s %s against the direction the model expects for it (%s)."
            % (CHAIN_SUB_PREFIX, head, words_for_int(len(seen)),
               "link runs" if len(seen) == 1 else "links run", _and_list(names)))


def sb_chain_count(counts: dict, *, k: int, anchor_label: str = "", slots=(), named=()) -> str:
    """DESIGN B.3's COUNT LINE -- the honest closure, in words, on ONE line.

    **IT REPLACES THE SB-X ``path_render_cap`` ENUMERATION AND IT COUNTS RATHER THAN NAMES**, which is
    the whole of DESIGN A.8 item (4): the names are the bytes the cut buys back, and a count with its
    reasons is what a reader can act on. THE COUNTS ARE THE DISTINCT ONES: the pool is
    ``paths x earned crosses``, so the raw total counts one sequence once per priced far market -- a
    true number that reads as machinery (``walk.chain_counts``' own note).

    LETTERS ONLY AND NO INSTRUMENT WORD (threat E12, and the fix lane's own sweep of the block): no
    ``board``, no ``rows``, no ``loud``, no ``the graph``.

    **THE CEILING IS FIVE HUNDRED CHARACTERS AND IT IS A MEASUREMENT** (orchestrator budget ruling,
    round 4). The round-2 ceiling was three hundred, set before the two CONTENT rulings that landed on
    this line -- note 3's ORTHOGONAL SHOCKS clause (about 86 characters at the counts the walk really
    carries) and the HELD-SEAT count (about 47) -- and content ordered by a ruling is never cut to meet
    a number set before the rulings. The measured maximum over both cells and the five 2026-09-16
    payloads is 433; plus ten per cent, rounded up to fifty, is 500. THE RULE SENTENCE IS WHAT PAID FOR
    THE FIRST CUT (item R-3). The line closed with "chosen for how far a reading sits from its own
    record, how far the sequence travels, whether a dated action sits inside its declared window, and
    what past firings did" -- 185 characters restating, once per page, the four terms that
    :func:`chain_arithmetic_words` now prints PER CHAIN with the points each one earned. Two spellings
    of one rule, and the per-chain one is the falsifiable one.

    **AND IT NAMES THE ORTHOGONAL SHOCKS** (owner's word, orchestrator note 3): a chain that crosses a
    commodity boundary on an earned cross edge AND carries an open dated event is the combination the
    question did not ask about, so the line says how many existed and how many rendered. A turn with
    none reads as "no cross-market dated action reached this page in its windows" rather than as
    silence. The two counts are ``walk.chain_counts``' own ``cross_market_event`` /
    ``cross_market_event_rendered``; where the walk declares neither, the clause is absent rather than
    zero.

    **THOSE ARE THE WALK'S SPELLINGS, AND THE FIRST CUT READ ``cross_event`` / ``cross_event_rendered``
    WHICH IT INVENTED** (round-3 MAJOR 4, census blocker 2). The key the line read was ``None`` on all
    three tiers, so the owner's own word -- the orthogonal shock -- reached no reader while the producer
    counted 112 / 342 / 414 of them with ONE rendered on each tier. The refutation that costed the
    clause was itself measured by passing ``cross_event=9`` BY HAND; on the shipped counts the clause is
    LARGER than that report stated, so the count line's ceiling is refuted with arithmetic rather than
    bought by dropping the owner's clause.

    **AND IT COUNTS THE ROWS THE SELECTION HELD A SEAT FOR, IN THE SAME SENTENCE** (owner ruling
    2026-09-22). ``slots`` is the rendered chains' own ``Chain.slot`` words: a chain on this page for
    the question's subject, its pair, its horizon or the other side is here for a reason OTHER than
    rank, and the closure counts those in the same breath as the chains above the line. Each such row
    NAMES which reason in its own head (:data:`CHAIN_SLOT_WORDS`); this line only counts them, and says
    nothing at all where every rendered chain ranked in on its own score.

    **AND THE AGED-OUT DATED ACTIONS ARE COUNTED IN THE SAME SENTENCE** (round-4 census 5). A DOCUMENT
    that the chain's own recency bound refused -- a 2019 action on a 0-1 quarter hop, which
    ``walk._receipt_in_reach`` correctly declines to call today's receipt -- is a thing the estate HAD
    and did not print, and a correction that leaves no trace is a deletion. It folds into the existing
    closure as one more clause and never onto a line of its own, and ZERO is silent because "no dated
    action aged out" is this page's ordinary state.

    **AND THE NUMBER UNDER THAT NOUN IS THE DISTINCT DOCUMENT COUNT, READ OFF THE PRODUCER**
    (round-5 blocker 3). The round-4 line summed ``Chain.receipts_aged_out`` over ``bd.chains`` at the
    call site -- a PER-CHAIN document count over the whole POOL, while ``ChainHop`` is memoised per
    ``(contract, driver_id)``, so ONE document on ONE row was counted once for every pool chain that
    walked that row. MEASURED through the shipped producer with EXACTLY ONE dated action in the
    estate, the page printed "**fifty-five** / **two hundred twenty** / **two hundred sixty-four**
    dated actions aged out of their windows" at quick / deep / max. The noun names DOCUMENTS; the
    number counted (chain, document) pairs -- the estate's own one-series-counted-once law broken on
    the very clause written to keep it.

    ``chain_counts["receipts_aged_out"]`` IS NOW THAT DISTINCT COUNT (``walk._aged_receipt_keys`` over
    the pool, ONE key per ``(contract, driver_id, event_date)``) and this line reads it rather than
    re-summing anything: the noun, the number and the producer's own name are one fact with one owner,
    and a page that prints a figure its own trace row contradicts is a backing failure. The per-chain
    field keeps its own name (``Chain.receipts_aged_out``) for the chain's own answer."""
    c = dict(counts or {})
    seq = int(c.get("distinct_sequences") or 0)
    total = int(c.get("total") or 0)
    if not seq or not total:
        return ""
    # **ONE DENOMINATOR, SAID OUT LOUD.** The first cut put the DISTINCT sequence count at the head and
    # the RAW pool's own sub-counts behind it, so the line read "thirty-six sequences reach it --
    # seventy-five of them read on their own series at more than one hop": two populations under one
    # word, and the larger number was the smaller one's subset by grammar alone. The pool is
    # ``sequences x the priced markets each carries into``, so the line now names BOTH and says which
    # sub-count belongs to which -- the same discipline the fan index keeps between its count and its
    # split.
    parts = ["%s read their own series past one link"
             % words_for_int(int(c.get("state_two_hops") or 0)),
             "%s carry an action" % words_for_int(int(c.get("with_document") or 0))]
    unnamed = int(c.get("distinct_unnamed_markets") or 0)
    if unnamed:
        parts.append("they reach %s %s this question did not name"
                     % (words_for_int(unnamed), "market" if unnamed == 1 else "markets"))
    xe = c.get("cross_market_event")
    if xe is not None:
        # "...CARRIED HERE" AND NOT "...ABOVE", because the closure below already ends in "above" and
        # the two counts are different facts that can take the same value (three cross-market chains
        # rendered, three chains rendered): one sentence, two numbers, two nouns.
        parts.append("%s cross a market carrying an open action, %s of them carried here"
                     % (words_for_int(int(xe or 0)),
                        words_for_int(int(c.get("cross_market_event_rendered") or 0))))
    _aged = max(0, int(c.get("receipts_aged_out") or 0))
    if _aged:
        parts.append("%s dated %s older than the lag the model allows for %s"
                     % (words_for_int(_aged), "action" if _aged == 1 else "actions",
                        "it" if _aged == 1 else "them"))
    # **THE PAIR SLOT'S NO-CANDIDATE STATE, AND NO OTHER SLOT STATE, IS PRINTED** (09-23, CONTRACT.md
    # C7). Lane W stamps one closed word per question slot on ``chain_counts["slot_state"]``; the only one a
    # reader needs is the pair the question set with NO chain running between its two markets -- the
    # palm/rapeseed turn read "the chain this page carries" and never learned that none connected the two.
    # The market names are the anchors' own reader labels, passed by the caller; silent without them.
    _ss = dict(c.get("slot_state") or {}) if isinstance(c.get("slot_state"), dict) else {}
    _named = [str(x) for x in (named or ()) if str(x or "")]
    if _ss.get("pair") == "no_candidate" and len(_named) >= 2:
        parts.append("no chain here runs from one named market to the other (%s)" % _and_list(_named))
    # THE HELD SEATS ARE COUNTED IN THE CLOSURE ITSELF and never on a line of their own: a second line
    # would cost more than the fact is worth, and the reason each one was held is on that chain's own
    # head. ZERO is SILENT here (and not printed in full as the cross-market zero is) because every
    # chain ranking in on its own score is this page's ORDINARY state -- "none of them carried for a
    # reason other than rank" states the default back at a reader who was never told otherwise.
    held = sum(1 for s in (slots or ()) if str(s or "") and str(s) != "top")
    seats = (", %s of them here for a reason other than rank" % words_for_int(held)) if held else ""
    return ("%sCOUNT into %s: %s %s, %s %s in all with the far markets; %s; %s above%s."
            % (CHAIN_HEAD_PREFIX, anchor_label or "this market", words_for_int(seq),
               "sequence" if seq == 1 else "sequences", words_for_int(total),
               "way" if total == 1 else "ways", "; ".join(parts), words_for_int(int(k or 0)), seats))


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
    body = (f"declared {sign_words(head_sign)} on {words_for_int(len(head))} of them "
            f"({name_list(head, head_cap, noun='markets')})")
    if rest:
        other_sign = sorted(s for s in by_sign if s != head_sign)[0]
        body += (f" and {sign_words(other_sign)} on the rest "
                 f"({name_list(rest, max(1, rest_cap) if cap else 0, noun='markets')})")
    n = len(far)
    # THE FAN IN WORDS A PM READS (lane D, the 2026-09-16 smoke). HEAD rendered "the same reading is
    # declared on twenty-three other boards: ..." and the writer transcribed it as "declared on
    # twenty-three other markets, twenty-two in the same direction" -- which the PM lens read as
    # SCORING MACHINERY: a count with no subject and no market a reader could look at next. The count
    # and the split are untouched (they are what "the graph decides relevance" makes visible); what is
    # added is the SUBJECT -- the driver -- and the two markets nearest this question, taken from the
    # fan payload itself by the same deterministic order the watch lane's `_nearest_far` uses.
    who = humanise(entry.get("driver_id") or "") or "the same reading"
    # THE POINTER IS ONLY WORTH PRINTING WHERE THE READER CANNOT PICK: on a two- or three-market fan
    # the split above already names every one of them, and "the nearest two are A and B" under a list
    # that reads "(A, B)" is the same sentence twice.
    near = nearest_far_names(entry, k=2) if n >= 4 else []
    tail = ""
    if near:
        tail = (f". The nearest {'one' if len(near) == 1 else 'two'} to this question "
                f"{'is' if len(near) == 1 else 'are'} {_and_list(near)}")
    return (f"- {who} is a shared driver across {words_for_int(n)} other "
            f"{'market' if n == 1 else 'markets'} this estate tracks, {body}{tail}")


def nearest_far_names(entry: dict, k: int = 2) -> list:
    """The far markets a reader should be pointed at FIRST: highest declared confidence, then soonest
    declared band, then the market's own name.

    IT IS ``watch._nearest_far``'s ORDER, RESTATED AND NOT IMPORTED -- ``watch`` imports this module for
    its display vocabulary, so the arrow only goes one way. The deck pins the two against each other so
    a change to either is a build failure rather than two lines on one page naming two different
    "nearest" markets."""
    rank = {"high": 0, "medium": 1, "low": 2}
    scored = []
    for f in (entry.get("far") or ()):
        if not f.get("sign"):
            continue
        band = f.get("lag_band")
        minq = 99 if (band is None or getattr(band, "min_q", None) is None) else int(band.min_q)
        scored.append(((rank.get(str(f.get("confidence") or ""), 3), minq,
                        str(f.get("contract") or "")), str(f.get("contract") or "")))
    scored.sort(key=lambda t: t[0])
    return [board_label(c) for _, c in scored[: max(0, int(k))]]


def sb_convergence(row: dict, *, series_of: Optional[dict] = None) -> str:
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
    and the row now says which names carry a figure and which carry no series to read.

    **"ARE SHOWING HERE" IS NOW SAID ONLY OF THE ROWS THAT WERE READ** (review round 2, MAJOR 9). Round
    1 kept HEAD's single leading count -- distinct series PLUS the text-only names -- under the verb
    "are showing here", and rendered "four of the four conditions it names are showing here (export pace
    lag, with its own [N] z); three of them carry no series read here (China import tariff, section301
    tariffs and China state reserves)". HEAD's "sit among this board's loudest rows" was a claim about
    RANK and survived that arithmetic; "are showing" is a claim about OBSERVATION and the next clause
    denies it for three of the four. The sentence now leads with the READ count under that verb, states
    the unread ones as NAMED BY THE PATTERN, and then states the total the two make -- which is the
    number the threshold comparison uses, so nothing is deleted and no count changes.

    **AND A CONDITION READ IN THE OPPOSITE PHASE IS NOT A CONDITION MET** (review round 2, MAJOR 10).
    The b40 page declared the cool phase in force on its ONI reading and, fifteen lines below, counted
    ``El_Nino`` into "five of the six conditions it names are showing here" -- the exact story the smoke
    charged. Loudness ranks the UNSIGNED state and is phase-blind, so both members of a declared phase
    pair land loud on one reading; a pattern that asks for the WARM phase is not met by a COOL reading.
    The name is NEVER struck -- it is stated, with the reason -- and the count under-claims, which is the
    only safe direction for a quorum."""
    count = pattern_count(row, series_of)
    fold = count["fold"]
    measured = [humanise(d) for d in fold["keep"]]
    opposed = [humanise(d) for d in fold["phase_opposed"]]
    unread = [humanise(d) for d in count["unread"]]
    n_measured = count["n_measured"]
    n_distinct = count["n_distinct"]
    n_declared = int(row["n_declared"])
    cond = "condition" if n_declared == 1 else "conditions"
    named = (f"({_and_list(measured)}, "
             f"{'with its own [N] z' if n_measured == 1 else 'each with its own [N] z'})"
             if measured else "")
    if n_measured:
        lead = (f"{words_for_int(n_measured)} of the {words_for_int(n_declared)} {cond} it names "
                f"{'is' if n_measured == 1 else 'are'} showing here {named}")
    else:
        # THE PARENTHETICAL READS OFF `n_phase_opposed` AND NOT OFF `n_measured` (review round 3,
        # NEW-3). After MAJOR 10 `n_measured == 0` stopped meaning "nothing was read": a pattern whose
        # only series-bearing driver is the OUT-OF-FORCE member of a declared phase pair reads zero
        # here, and this parenthetical then denied a reading the very next clause prints ("none of
        # those drivers has a series read here; IOD negative names the phase opposite the one in force
        # ON THAT READING"). Where a member WAS read, the opposed clause below states it by name and
        # says why it is not counted, so the absence is stated once and never falsely.
        lead = (f"none of the {words_for_int(n_declared)} {cond} it names is showing here "
                f"(none of those drivers has a series read here"
                + (" in the phase the pattern names)" if count["n_phase_opposed"] else ")"))
    alias_clause, opposed_clause = fold_clause(fold)
    unread_clause = ""
    if unread and n_measured:
        # "ARE COUNTED HERE", NOT "ARE ON THIS PAGE" (review round 3, NEW-2). `n_distinct` is the number
        # the threshold comparison uses, and it is NOT the number of the pattern's names this page
        # carries: a member read in the opposite declared phase is on the page, with its own [N] row and
        # its own clause in this very sentence, and is deliberately left out of the count. The b40 board
        # rendered "IOD negative names the phase opposite the one in force ..., so it is not counted
        # here; ... so FOUR OF THE FIVE ARE ON THIS PAGE" over a page carrying five. The number did not
        # move and must not: it is the quorum's, and it under-claims by construction. The VERB now says
        # which number it is, and the two clauses add up -- four counted plus one not counted is five.
        unread_clause = (f"; {words_for_int(len(unread))} more "
                         f"{'is' if len(unread) == 1 else 'are'} named by the pattern with no series "
                         f"read here ({_and_list(unread)}), so {words_for_int(n_distinct)} of the "
                         f"{words_for_int(n_declared)} are counted here")
    elif unread:
        unread_clause = (f"; all {words_for_int(len(unread))} are named by the pattern with no series "
                         f"read here ({_and_list(unread)})")
    # THE COUNT AND THE NUMBER THE PATTERN ASKS FOR, IN PLAIN WORDS AND WITH NO FIRING CLAIM. Lane A's
    # requested shape was a VERDICT ("the pattern is in force / NOT in force") with the threshold struck
    # from prose. THE VERDICT IS REFUSED HERE AND THE REFUSAL IS THE ESTATE'S OWN: doctrine M-2 and
    # `walk.CONVERGENCE_BANNED_WORDS` put FIRING with `firing.fire_contract` over declared bands and
    # forbid this row the words "met", "fires" and "regime is" -- a board that says a pattern is in
    # force has minted a verdict by arithmetic, which is the K9 class those words were banned for. What
    # lane A's finding actually charges is the INTERNAL VOCABULARY ("declared drivers", "this board's
    # twenty-four loudest rows", "the pattern's own threshold is two") and the unfalsifiable reading
    # that came with it, and all of that goes: the row names the conditions, says how many are showing,
    # says how many the pattern asks for, and does the comparison in words. The reader draws the verdict.
    short = n_distinct < int(row["threshold"])
    return (f"- {pattern_label(row['name'])} on {board_label(row['contract'])}: "
            f"{lead}{alias_clause}{opposed_clause}"
            f"{unread_clause}; it asks for {words_for_int(row['threshold'])}, so the count here is "
            f"{'short of that number' if short else 'at or past that number'}; "
            + ("none of them carries a declared desk band" if not row["n_with_band"] else
               f"{words_for_int(row['n_with_band'])} "
               f"{'carries' if row['n_with_band'] == 1 else 'carry'} a declared desk band"))


def pattern_count(row: dict, series_of: Optional[dict] = None) -> dict:
    """ONE PAGE, ONE PATTERN, ONE COUNT -- the only place a declared pattern's conditions are counted.

    REVIEW ROUND 2, MAJOR 5. Round 1 put the series fold in :func:`sb_convergence` and NOWHERE ELSE, and
    the WATCH producer narrates the same pattern on the same page out of ``pr['n_matched']``. MEASURED
    on the b40 fixture, both lines reachable on arm A's treatment cell: the quorum row read "one of the
    two conditions it names is showing here (export ban ...); export ban and DMO are one reading and
    count once here" while the watch row read "this reading is one of TWO of the two drivers the pattern
    policy-shock spike declares". One page, one pattern, two counts. Both callers now read this.

    ``matched_measured`` WINS WHENEVER THE KEY IS PRESENT, EVEN EMPTY. Round 1's
    ``row.get("matched_measured") or row["matched"]`` fell through to ``matched`` on a pattern whose
    matched drivers were ALL text-only, and then added ``matched_unmeasured`` on top -- every name
    counted twice. The walk writes the three keys together (``walk.py:941``), so their presence is the
    test."""
    _mm = row.get("matched_measured")
    ids = list(_mm) if _mm is not None else list(row.get("matched") or ())
    unread = list(row.get("matched_unmeasured") or ()) if _mm is not None else []
    fold = _series_fold(ids, series_of)
    return {"fold": fold, "unread": unread, "n_unread": len(unread),
            "n_measured": len(fold["keep"]), "n_distinct": len(fold["keep"]) + len(unread),
            "n_phase_opposed": len(fold["phase_opposed"])}


def _phase_opposed(smap: dict, d) -> bool:
    """Is this driver the member of a DECLARED phase pair whose phase is NOT the one in force?

    ONE SPELLING of the test :func:`_series_fold`, :func:`_lead_name` and :func:`group_keep` all apply,
    so a page cannot exclude a name from one line and keep it on another."""
    pf = _smap_entry(smap, d).get("phase") or {}
    return bool(pf.get("in_force")) and str(d) == str(pf.get("other_driver") or "")


def group_keep(smap: dict, key: str, *, strict: bool = False) -> str:
    """THE ONE NAME A SERIES GROUP IS READ UNDER ON THIS PAGE -- the driver id, or ``""`` where the map
    holds no member of that key (and, under ``strict``, where this page has no ground for a name).

    REVIEW ROUND 3, NEW-4. The claim that "the lead, the JOIN and the quorum can never name one reading
    three ways" was a CONSTRUCTION claim and it did not hold: :func:`render_board`'s SB-JOIN chose its
    kept name over the WHOLE series group and :func:`_series_fold` chose over the PATTERN'S MATCHED
    SUBSET, so a group whose highest-confidence member the pattern did not match had the JOIN saying
    "read it under export ban" and the quorum naming CPO levy, on one page, for one reading. The rule is
    unchanged and is now written once: drop a member read in the phase that is NOT in force (the
    quorum's own rule, :func:`_lead_name`'s first step), then take the highest declared confidence,
    ties on the reader label. The POOL is this map -- the board's own read rows -- so every caller
    chooses from the same population as well as by the same rule.

    ``strict`` IS MAJOR 3's RULING, READ BY THE CALLER THAT SUBSTITUTES A NAME THE PATTERN DID NOT
    MATCH. Where the best members TIE and the group's own signs DISAGREE, :func:`sb_phase_pair` prints,
    in words, that "the graph declares them at the same confidence, so this page has no ground of its
    own for preferring one of these names over another and does not offer one" -- and a quorum row that
    then renamed a matched MYR USD to IDR USD would hand the writer the Indonesian rupiah as the reading
    of a Malaysian palm board, which is the exact defect round 2 closed. MEASURED: without this clause
    the b40 substitution-demand-pull row did precisely that. Under ``strict`` the producer returns
    nothing there and the caller keeps the name it already had."""
    pool = [d for d in sorted(smap or {}) if _smap_entry(smap, d)["key"] == str(key or "")]
    live = [d for d in pool if not _phase_opposed(smap, d)]
    pool = live or pool
    if not pool:
        return ""
    ranks = sorted(CONFIDENCE_RANK.get(_smap_entry(smap, d)["confidence"], 3) for d in pool)
    if (strict and len(ranks) > 1 and ranks[0] == ranks[1]
            and len({_smap_entry(smap, d)["sign"] for d in pool}) > 1):
        return ""
    return min(pool, key=lambda d: (CONFIDENCE_RANK.get(_smap_entry(smap, d)["confidence"], 3),
                                    humanise(d)))


def _series_fold(driver_ids, series_of: Optional[dict]) -> dict:
    """Fold a pattern's matched drivers onto DISTINCT SERIES, keeping ONE NAME PER SERIES.

    THE DEFECT, FROM THE SERVED DEEP ANSWER (2026-09-16). The page said, correctly, "note these two are
    one series read under two names -- one reading, not two" about ``board_crush`` and
    ``soybean_crush_margin`` -- and then wrote "the crush-led demand-pull pattern has three of its
    drivers among the loudest readings against a threshold of two", counting BOTH of them. One reading
    cleared a two-driver quorum on its own.

    THE THRESHOLD IS THE GRAPH'S AND IS NOT RE-CURATED. What changes is only that one SERIES can no
    longer satisfy two of a pattern's conditions, which is the direction that under-claims: a pattern
    reads NOT in force where HEAD read it in force, never the other way round.

    THE NAME KEPT IS THE HIGHEST-CONFIDENCE ONE, ties broken on the reader label -- the same rule
    ``render_board``'s phase-pair fold uses, so the two lines never disagree about which of two names a
    page should be read under. A driver with no series key stands alone: a text-only row is not the
    same reading as anything.

    ``series_of`` is :func:`series_by_driver`'s map -- ``{driver_id: {key, confidence, sign, phase}}``,
    the BOARD's own -- and a driver this page did not read is absent from it and therefore distinct. A
    two-tuple ``(key, confidence)`` is still accepted so a caller that knows only those two facts keeps
    working; it simply cannot declare a relation, and an undeclared relation folds as an alias.

    **THE RELATION IS CLASSIFIED, AND THAT IS REVIEW ROUND 2's MAJOR 4.** Round 1 folded on the series
    key ALONE while :func:`sb_phase_pair` required a DECLARED pair or SIGN AGREEMENT before it would say
    "one reading", so on a board where a pattern matched two of a sign-contradictory group the JOIN line
    said "this page cannot reconcile them" and the quorum said "X and Y are one reading and count once
    here". Both folds now read the same two facts -- the declared phase pair and the declared sign -- and
    the group's relation is stated in :data:`FOLD_RELATION_WORDS`' own words, so the two lines cannot
    disagree. The COUNT is the same under all three relations: one series is one reading.

    **AND A MEMBER READ IN THE OPPOSITE PHASE LEAVES THE COUNT** (``phase_opposed``, MAJOR 10). It is
    returned, never dropped: the caller states it."""
    ids = [str(d) for d in (driver_ids or ())]
    smap = dict(series_of or {})
    live, opposed = [], []
    for d in ids:
        if _phase_opposed(smap, d):
            opposed.append(d)
        else:
            live.append(d)
    groups: dict = {}
    order: list = []
    for d in live:
        k = _smap_entry(smap, d)["key"] or f"#{d}"
        if k not in groups:
            groups[k] = []
            order.append(k)
        groups[k].append(d)
    keep, out_groups = [], []
    for k in order:
        members = groups[k]
        # THE NAME IS THE WHOLE GROUP'S AND NOT THE PATTERN'S SUBSET (review round 3, NEW-4). The SB-JOIN
        # line chooses over every row on the series; this chose over the drivers THIS pattern matched, so
        # a group whose highest-confidence member the pattern did not match had the two lines naming one
        # reading two ways -- the JOIN "read it under export ban", the quorum "(CPO levy, with its own
        # [N] z)". :func:`group_keep` is the one rule both now read.
        first = group_keep(smap, k, strict=True) or min(members, key=lambda d: (
            CONFIDENCE_RANK.get(_smap_entry(smap, d)["confidence"], 3), humanise(d)))
        keep.append(first)
        others = tuple(sorted((m for m in members if m != first), key=humanise))
        if others:
            out_groups.append((first, others, fold_relation([first] + list(others), smap)))
    return {"keep": keep, "phase_opposed": opposed, "groups": out_groups,
            # THE LEGACY SHAPE, kept because a banked caller reads it: (kept, aliases) with no relation.
            "aliases": [(k, al) for k, al, _rel in out_groups]}


def _smap_entry(smap: dict, d) -> dict:
    """One driver's fold facts, from either map shape (see :func:`_series_fold`)."""
    v = smap.get(d)
    if isinstance(v, dict):
        return {"key": str(v.get("key") or ""), "confidence": str(v.get("confidence") or ""),
                "sign": str(v.get("sign") or ""), "phase": v.get("phase") or {}}
    t = tuple(v or ())
    return {"key": str(t[0]) if len(t) > 0 else "",
            "confidence": str(t[1]) if len(t) > 1 else "",
            "sign": str(t[2]) if len(t) > 2 else "",
            "phase": (t[3] if len(t) > 3 else {}) or {}}


#: WHAT TWO NAMES ON ONE SERIES ARE TO EACH OTHER -- the CLOSED vocabulary both folds print (MAJOR 4).
#: The three relations are three different facts and a reader acts on them differently: an ALIAS is one
#: claim under two labels; a PHASE PAIR is one index read in two directions, which the graph DECLARES;
#: an UNRECONCILED group is two declared links that sign one figure differently, which this page states
#: and does not resolve. The count is one under all three -- one series is one reading.
FOLD_RELATION_WORDS: dict = {
    "alias": "are one reading and count once here",
    "phase": "are two phases of one reading and count once here",
    "unreconciled": "are one reading the graph signs differently here, and count once",
}


def fold_clause(fold: dict) -> tuple:
    """``(the folded-groups clause, the phase-opposed clause)`` -- the block's ONE spelling of both.

    Two readers: the quorum row and the WATCH producer's ``convergence_amplified`` sentence (review
    round 2, MAJOR 5). Each clause OPENS with its own ``; `` so a caller can splice it anywhere in a
    sentence, and each is ``""`` when there is nothing to say."""
    groups = (fold or {}).get("groups") or []
    opposed = [humanise(d) for d in ((fold or {}).get("phase_opposed") or ())]
    alias = ""
    if groups:
        alias = "; " + "; ".join(
            f"{_and_list([humanise(k)] + [humanise(a) for a in al])} {FOLD_RELATION_WORDS[rel]}"
            for k, al, rel in groups)
    opp = ""
    if opposed:
        opp = (f"; {_and_list(opposed)} "
               f"{'names' if len(opposed) == 1 else 'name'} the phase opposite the one in force on "
               f"that reading, so {'it is' if len(opposed) == 1 else 'they are'} not counted here")
    return alias, opp


def fold_relation(members, smap: dict) -> str:
    """Which of :data:`FOLD_RELATION_WORDS` a folded group is -- the SAME test :func:`render_board`'s
    SB-JOIN loop applies, so the two lines can never call one group two things."""
    ms = [str(m) for m in (members or ())]
    signs = {_smap_entry(smap, m)["sign"] for m in ms}
    for m in ms:
        pf = _smap_entry(smap, m).get("phase") or {}
        pair = {str(pf.get("driver") or ""), str(pf.get("other_driver") or "")}
        if len(ms) == 2 and pair == set(ms):
            return "phase"
    return "alias" if len(signs) < 2 else "unreconciled"


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
AMPLIFIER_EFFECT_UNKNOWN = ("an interaction this page has no word for")

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
    tail = (f"; {_and_list(unread)} {'carries' if len(unread) == 1 else 'carry'} no series read "
            f"here") if unread else ""
    row = (f"  amplifier on {board_label(contract)}: {ids} are all among the largest moves here; "
           f"the graph "
           f"records the effect as {amplifier_effect(inter['effect'])}{tail}")
    if note and note != AMPLIFIER_NOTE_REPLACED and register_hits(row + note):
        note = AMPLIFIER_NOTE_REPLACED
    return row + note


def tape_delivery_words(tape) -> str:
    """THE TAPE'S DELIVERY, NAMED THE WAY IT WAS PICKED (09-23, CONTRACT.md C12 / OWNER DECISION 5).

    " front <YYYY-MM>" ONLY when the pick was made by one of the roll rule's activity-print methods
    (``query.ROLL_METHODS_FRONT``: open interest, volume) -- that is what a desk means by the front month.
    Every other pick -- the named cycle fallback (``cycle_nearest_eligible``) when the rule's inputs are
    absent, or a tape that carries no method at all -- is "the nearest listed delivery, <Month YYYY>,",
    which is what it is (each form carries its own leading separator, so the line reads "CBOT soybeans
    front 2026-11 settle on" or "CBOT soybeans, the nearest listed delivery, November 2026, settle on").
    The method is the tape's OWN stamp (``TapeState.roll_method``, written by the
    feeder from the selected row); the vocabulary is lane T's constant, read, never restated."""
    cm = str(getattr(tape, "contract_month", "") or "")
    method = str(getattr(tape, "roll_method", "") or "")
    try:
        from leviathan.graphrag.numbers.query import ROLL_METHODS_FRONT as _front
    except Exception:                                   # noqa: BLE001 -- no vocabulary, no "front" claim
        _front = frozenset()
    if method and method in _front:
        return f" front {cm}"
    mw = month_words(cm) if len(cm) >= 7 else ""
    return f", the nearest listed delivery, {mw or cm},"


def _tape_known(tape) -> Optional[str]:
    """The tape settle's known date through the feeder's ONE derivation, or the session date when the
    derivation cannot be read (a stamp never breaks a tape)."""
    try:
        from leviathan.graphrag.state import feeders as _F
        return _F.tape_known_date(tape) or getattr(tape, "level_date", None)
    except Exception:                                   # noqa: BLE001
        return getattr(tape, "level_date", None)


def sb_tape(n: int, tape, *, asof: str) -> tuple:
    """SB-T (sec 6.2, D19, B19): the ANCHOR's own tape -- the dated front settle, the four SAME-CONTRACT
    session changes and the level's percentile over the window this read fetched. ONE handle per
    magnitude; the standings that name their populations and realised vol are RESERVED and the line
    says so in words."""
    calls: list = []
    q = {"table": "silver_futures_eod", "metric": "settle", "commodity": tape.slug, "country": None,
         "period": tape.contract_month, "asof": asof}
    h = n
    # ONE SETTLE, ONE KNOWN DATE (09-23, CONTRACT.md C11; lane C's B-3): the session date through the ONE
    # derivation the numbers seat's label of the same settle prints (`feeders.tape_known_date`, the card's
    # publication lag). The printed "settle on <session>" is the SESSION and is unchanged.
    calls.append(sb_call(value=tape.level, unit=tape.unit, knowledge_date=_tape_known(tape), **q))
    # THE SETTLE IS A CARD'S FIGURE and prints through the card's own precision (``shown_figure``: the
    # settle card's ``display_decimals``) -- a desk quotes the tick (1,328.25 never "1328"; integration F-3).
    # ``shown_figure`` returns the figure WITH its unit (``rows.figure_text``), so the unit is printed once.
    parts = [f"- [N{h}] {board_label(tape.slug)}{tape_delivery_words(tape)} settle on "
             f"{tape.level_date}: "
             f"{shown_figure(tape.level, table='silver_futures_eod', metric='settle', unit=tape.unit)}"
             .rstrip()]
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


def analog_count_floor(a: dict) -> str:
    """**HOW FAR BACK THESE DIMENSIONS SEE -- THE PAGE'S ONE PRODUCER FOR THAT YEAR**, and it is
    ``max(first_date)`` over ``record_span``: the first date on which EVERY declared dimension could be
    read at once.

    **ROUND 2 RULED ON THIS BECAUSE ROUND 1 PUT TWO ANSWERS TO ONE QUESTION ON ONE SENTENCE.** Round 1
    took the count's floor from the SEED'S OWN ``record_span`` entry and left the coverage clause's
    "which together reach back to" on ``floor_year`` (``analogs._coverage_floor``, ``max(first_obs)``
    over the LOUD SEEDS -- a RAW series start, bound here to a Z-READABILITY population). Both were
    measured wrong and in the same direction, OPTIMISTIC, and they contradicted each other on the same
    line: 24 of 36 rendered stanzas printed a count floor EARLIER than its own counted population could
    reach (El Nino 1999 against a binding 2023-11-03; ending stocks 1999 against 2015-12-31) and 36 of
    36 printed a reach year the ``record_span`` it names disagrees with (1990 vs 1999-12-31, 2022 vs
    2023-11-03, 2006 vs 2015-12-31). One page read "the record carries three such crossings SINCE 1999
    ... the three dimensions ranked beside it, WHICH TOGETHER REACH BACK TO 2022".

    So there is ONE producer and both clauses spend it. The number is the max and not the min because
    the sentences it serves are about the dimensions TOGETHER: the head-admitted count is admitted only
    where ``dims_seen == dims_declared`` (:func:`analogs.select_analogs`), so its earliest possible
    member is the date the LAST dimension's record opens, and "which together reach back to" says the
    same thing about the same set. A floor EARLIER than that is a claim the population cannot support;
    a floor LATER is a record the reader is denied. Both are pinned.

    IT JOINS NOTHING AND THAT CLOSES A LIVE HAZARD (round-1 minor 3): round 1 matched ``record_span``
    on the driver NAME, and duplicate ids are live on this estate -- 78 rows across the 54 measured
    cells carry one (``['El_Nino','El_Nino','El_Nino']``, three boards' dimensions) -- so the first
    board whose same-named driver had a different record start would silently have taken another
    board's floor. A max over the whole span has no key to get wrong.

    WHAT IT IS NOT, STATED BECAUSE HEAD PRINTED IT AND ROUND 1 KEPT IT: ``floor_year`` is the year the
    LOUD SET's raw series start can see, and the served soybeans page spent it under "the record
    carries one hundred fifty-nine such crossings since 2022" over a window of fifty-six months, with
    all three picked dates (2013-06-30, 2020-04-30, 2017-02-28) PRECEDING the printed floor. It stays
    on the row as the fail-back and is printed by no clause that names ``record_span``.

    IT FAILS BACK, NEVER CLOSED: a row with no ``record_span`` -- every hand-built deck row and every
    census row -- gets ``floor_year`` exactly as it got it at HEAD, so this function can only ever
    correct a floor and never remove one. A span whose entries carry no placeable ``first_date``
    (``analogs._record_span`` writes ``None`` where no position carries a distance component) is the
    same case and takes the same answer: a floor the record cannot back is not invented here."""
    firsts = [str((r or {}).get("first_date") or "")[:10]
              for r in ((a or {}).get("record_span") or ())]
    firsts = [d for d in firsts if len(d) >= 4 and d[:4].isdigit()]
    if firsts:
        return max(firsts)[:4]
    return str((a or {}).get("floor_year") or "")


def analog_selection_clauses(a: dict) -> str:
    """THE SEVENTEEN FACTS THE SELECTION PUTS ON EVERY ANALOG ROW, AS THE SENTENCES THE PAGE OWES.

    **THE MEASURED STATE THIS FUNCTION ANSWERS.** The committed selection half (bbddd4cc) puts
    ``dims_seen``, ``dims_unread``, ``unread_sigma``, ``sign_agree``/``sign_seen``,
    ``dir_agree``/``dir_seen``, ``precedes_dims``, ``record_span``, ``near_asof``,
    ``n_candidates_raw``/``_pit``/``_head``, ``n_dropped_unreadable``, ``per_dim``, ``run_gap`` and
    ``detail`` on every row -- and a census over ``render.py``, ``watch.py``, ``lint.py``,
    ``narration.py``, ``board.py`` and ``answer.py`` by each field's ONE spelling found ZERO readers
    for sixteen of them. The selection stopped declining by rule and started PRINTING facts; nothing
    printed them. These are those sentences.

    **EVERY CLAUSE IS A COUNT AND NOT AN ENUMERATION** (the board SELECTS, never enumerates). Not one
    of them names a dimension: ``record_span`` and ``dims_order`` carry RAW driver ids,
    ``register.internal_leaks`` is never relaxable, and a counts-only clause cannot leak one. They are
    letters-only -- ``words_for_int`` renders every number -- so SB-A mints no handle here and the
    verifier has nothing new to bind.

    **AND NOT ONE OF THEM CARRIES THE TOKEN ``board``**, which is a measurement and not a style note:
    ``register.desk_register_hits`` charges it, the pre-arm sweep drove it 142 -> 65 across this block,
    and the handoff's own suggested wording ("the dimensions this board ranks") cost one charge PER
    STANZA. "ranked beside it" is the same fact at zero.

    THE ORDER IS THE READING'S: how rare the state is, how wide the pool that could be ranked, how much
    of the state was legible, whether the LEVEL agreed, whether the PATH agreed, and then the two
    corrections that qualify the date itself.

    **THE DIRECTION CLAUSE IS THE ONE THAT CHANGES A MIND** (D4). ``sign_agree/sign_seen`` is nearly
    constant by construction -- the distance ranks on the z, so a small z-gap implies a shared sign, and
    it measured 2/2, 4/4 and 5/5 on the live stanzas. ``dir_agree/dir_seen`` measured **0 of 2** on the
    served soybeans deep stanza and 0 of 3 on ``export_pace_lag``: the level matched and the PATH did
    not. Round 3 put direction and run on the KNOWLEDGE axis, so it is a true statement about what a
    desk could have read then. Both ride; the sign clause is cheap and the direction clause is the
    information.

    ``sign_seen == 0`` IS NOT BRANCHED ON, and that is deliberate: it is unreachable after round 2 (a
    fired row always carries a readable sigma) and pinned as such in ``tests/unit/test_state_analogs.py``.
    A branch for an unreachable state is a sentence no measurement can ever grade.

    ``near_asof`` IS APPENDED AND NEVER FILTERED ON (DESIGN C.4, and ``state/lint.py`` clause 16 grades
    exactly that). It is live and silent on the served page today: ``attached_event`` at deep renders a
    stanza picked 2026-01-31 against an as-of of 2026-09-07 and ``attached_event`` at max's TOP stanza
    picks 2025-12-31 -- seven and nine months, both flagged, both rendered, neither saying so. Fences
    correct or compute; this one computes, and the stanza stays on the page.

    A row that carries none of these fields -- every hand-built deck row, every census row -- gets the
    empty string, so the header it composes is HEAD's byte for byte."""
    out: list = []
    seen, decl = a.get("dims_seen"), a.get("dims_declared")
    if seen is not None and decl is not None:
        # ONE PRODUCER FOR "HOW FAR BACK THESE DIMENSIONS SEE" (round-2 blockers 1 and 4). Round 1
        # attached ``floor_year`` here -- ``analogs._coverage_floor``, the LOUD SEEDS' RAW series
        # start -- to a population that is a Z-READABILITY one, and 36 of 36 rendered stanzas printed
        # a year the ``record_span`` this very clause names disagrees with (1990 vs 1999-12-31, 2022
        # vs 2023-11-03, 2006 vs 2015-12-31). The count clause beside it read a THIRD number. There is
        # one question and there is now one answer: :func:`analog_count_floor`.
        floor = analog_count_floor(a)
        out.append("; like on %s of the %s %s compared with it%s"
                   % (words_for_int(seen), words_for_int(decl),
                      "dimension" if int(decl) == 1 else "dimensions",
                      (", which together reach back to %s" % floor) if floor else ""))
        unread = int(a.get("dims_unread") or 0)
        if unread:
            out.append("; the %s it could not read there %s a full sigma apart"
                       % (words_for_int(unread), "counts as" if unread == 1 else "count as"))
    s_agree, s_seen = a.get("sign_agree"), a.get("sign_seen")
    if s_agree is not None and s_seen is not None and int(s_seen) > 0:
        out.append("; the state agreed in sign on %s of the %s a sigma could be read on"
                   % (words_for_int(s_agree), words_for_int(s_seen)))
    d_agree, d_seen = a.get("dir_agree"), a.get("dir_seen")
    if d_agree is not None and d_seen is not None and int(d_seen) > 0:
        out.append("; the path into it agreed on %s of the %s a direction could be read on"
                   % (words_for_int(d_agree), words_for_int(d_seen)))
    pre = int(a.get("precedes_dims") or 0)
    if pre:
        # THE NOUN IS THE **SET'S**, NEVER THE COUNT'S. "one of the dimension" is what a count-driven
        # plural produces here and it is wrong English: the count is the subset, the noun names the
        # population it is drawn from. MEASURED on the served soybeans deep page, where
        # `precedes_dims` is 1 against three declared dimensions.
        out.append("; this date precedes the record of %s of the %s compared with it"
                   % (words_for_int(pre),
                      "dimension" if int(decl or 0) == 1 else "dimensions"))
    if a.get("near_asof"):
        m = a.get("months_to_asof")
        if m is None:
            out.append("; that date sits inside the separation window of the as-of this page is read "
                       "at")
        else:
            out.append("; that date sits %s %s before the as-of this page is read at"
                       % (words_for_int(m), "month" if int(m) == 1 else "months"))
    # WHAT THE RECORD SAID **NEXT**, counted over the WHOLE forward window and never at the tier's cap
    # (round-2 blocker 3: `analogs._receipts_after` walks the window whole, `analogs.analog_rows`
    # publishes its length here and carries only `receipt_cap` rows, and `render_board` prints the cut
    # between the two as its own absence row). It is suppressed in exactly
    # ONE case -- a stanza whose corpus held nothing on EITHER side of the date -- because the stanza's
    # own receipt-absence row already says so in full ("the corpus holds no dated document for this
    # window; the figures above stand on the series alone"), and a header printing "zero dated
    # documents inside the window that followed it" one line above it is one absence stated twice in
    # two spellings. Where the stanza HAS explaining documents, a zero here is a real and different
    # fact and it prints.
    n_after = a.get("n_receipts_after")
    if n_after is not None and (int(n_after) > 0 or (a.get("receipts") or ())):
        n_after = int(n_after)
        out.append("; %s dated %s inside the window that followed it"
                   % (words_for_int(n_after), "document" if n_after == 1 else "documents"))
    return "".join(out)


def sb_analog_header(a: dict, *, chain_dims=(), chain_dim_names=None, chain_hop_names=None) -> str:
    """SB-A (sec 6.2, 4.2): the LIKE STATE header. Counts in words; the coverage floor PRINTED, so a
    loud set that cannot see 2003 says so; the vintage sentence on every stanza.

    ``chain_dims`` IS THE TOP RENDERED CHAIN'S OWN HOP IDS and it is spent by
    :func:`chain_stanza_mark` alone -- see there for the measurement that forced it. It is READ, NEVER
    REQUIRED: the default is the flag-off answer, every other line of this header is untouched by it,
    and a caller that passes none renders exactly the header it rendered before minus a mark it could
    not have attributed. ``chain_dim_names`` rides beside it on exactly the same terms: it is the
    hop-to-dimension PAIRING (``render._chain_dim_name_map`` off ``seam.dim_for_hop``) and it is spent
    by that same clause's TRANSLATED arm, so the ONI collision can be SPOKEN instead of swallowed.

    **THE SELECTION'S OWN FACTS NOW REACH THE READER** (:func:`analog_selection_clauses`) and every
    year this header prints for "how far back these dimensions see" comes off ONE producer
    (:func:`analog_count_floor`). Both are gated on fields the committed selection half puts on a
    produced row, so a hand-built row -- every deck row, every census row -- composes HEAD's header
    byte for byte.

    **THE COUNT BESIDE A PICK IS A POPULATION THE PICK IS A MEMBER OF** (round-2 blocker 2), and that
    is the ruling this header was re-cut on. Round 1 printed ``n_candidates_head`` -- the count the
    SHIPPED selector admits, which requires a candidate observable on EVERY declared dimension -- in
    the sentence that opens "the series sat like this in June 2013", and on 3 of the 18 served stanzas
    the date in that sentence was NOT in the set the number counts: 2013-06-30 beside a three-member
    set beginning 2023-12-31; 2020-04-30 and 2017-02-28 beside a one-member set at 2024-02-29. A
    reader takes the two as one event. So the number the pick stands beside is the RANKED POOL it was
    drawn from -- "one hundred fifty-nine like states ranked, this one the nearest" -- and the
    head-admitted count rides as a SECOND, separately named number, printed only where it differs and
    saying whose population it is ("three of them admitted at the full-coverage floor since 2023").
    Neither number wears the other's population, and ``watch.like_state_base_rate``'s arithmetic is
    untouched: it reads ``n_candidates_head`` off the row, which this header never re-spells.

    "THIS ONE THE NEAREST" IS BACKED BY ``pool_rank`` AND NOT BY THE STANZA'S POSITION, because a max
    tier renders TWO stanzas off one pool and the second one is not the nearest -- ``named_one`` at max
    prints 2020-04-30 and then 2017-02-28. Rank one gets the claim; every other rank gets "among
    them", and a row carrying no rank at all gets "among them" too, which is the weaker true sentence
    rather than the stronger unbacked one.

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
        return (f"LIKE STATE {humanise(a['driver_id'])} across the markets that carry it: "
                f"{words_for_int(n_boards)} of them sat in the top decile of their own history at once "
                f"in {month_words(a['date'])}; the record carries {words_for_int(n_dates)} such "
                f"{'date' if n_dates == 1 else 'dates'} since {str(a['floor_year'])}; each move below "
                f"is read over the lag the model allows for the market it names, and each line below "
                f"prints that lag; measured on the record as revised through {month_words(a['asof'])}")
    # THE COUNT THE PICK STANDS BESIDE IS THE POOL THE PICK CAME OUT OF, AND THE SHIPPED RULE'S OWN
    # COUNT IS A SECOND NUMBER THAT SAYS SO (round-2 blocker 2; see the docstring for the three served
    # stanzas whose date was outside the number printed beside it). `n_candidates` is the set the
    # selector RANKS and every picked row is a member of it by construction; `n_candidates_head` is a
    # SUBSET of that set -- `analogs.select_analogs` counts it inside the same loop that scores -- so
    # "M OF THEM" is exact arithmetic and not a turn of phrase. It prints only where the two differ,
    # because a second number equal to the first is one population wearing two sentences.
    # A ROW WITHOUT `n_candidates_head` IS HEAD'S ROW and gets HEAD's sentence, floor and all.
    n_head = a.get("n_candidates_head")
    n_pool = int(a['n_candidates'])
    if n_head is None:
        rarity = ("the record carries %s such %s since %s"
                  % (words_for_int(n_pool), "crossing" if n_pool == 1 else "crossings",
                     str(a['floor_year'])))
    else:
        rank = a.get("pool_rank")
        # THE NOUN IS THE POPULATION'S (round-2 review MAJOR 2): the ranked pool is 35-75% of the series'
        # own record and is NOT a set of like states -- "like state" is the word the watch's base-rate
        # row spends on the HEAD-admitted set, and one word over two populations a factor of 159 apart
        # is the reading D3 was opened to close. So the pool keeps round 1's accurate noun ("past
        # readings ... could be ranked beside it") and only the admitted count is called a like state.
        # 09-23 DESK VOCABULARY (CONTRACT.md C13): "compared with it", never the instrument's "ranked
        # beside it"; the two numbers and whose population each is are unchanged.
        rarity = ("%s past %s on this series could be compared with it, this one %s"
                  % (words_for_int(n_pool), "reading" if n_pool == 1 else "readings",
                     "the nearest" if rank is not None and int(rank) == 1 else "among them"))
        if int(n_head) != n_pool:
            floor = analog_count_floor(a)
            rarity += ("; %s of them %s like %s, the %s readable on every dimension%s"
                       % (words_for_int(n_head), "is a" if int(n_head) == 1 else "are",
                          "state" if int(n_head) == 1 else "states",
                          "one" if int(n_head) == 1 else "ones",
                          (" since %s" % floor) if floor else ""))
    return (f"LIKE STATE {humanise(a['driver_id'])} on {board_label(a['contract'])}: the series sat "
            f"like this in "
            f"{month_words(a['date'])}; {rarity}"
            f"{analog_selection_clauses(a)}; each move below is "
            f"read over the lag the model allows for the market it names, and each line below prints "
            f"that lag; measured on the record as revised through {month_words(a['asof'])}"
            f"{chain_stanza_mark(a, chain_dims=chain_dims, chain_dim_names=chain_dim_names, hop_names=chain_hop_names)}")


def chain_stanza_mark(a: dict, *, chain_dims=(), chain_dim_names=None, hop_names=None) -> str:
    """THE CLAUSE THAT SAYS THIS STANZA IS THE **THEN** OF THE CHAIN THE PAGE NAMED FIRST -- or ``""``.

    **DESIGN C.2 WAS WIRED AND INAUDIBLE** (round-4 MAJOR 2). ``seam._first_dim`` passed the top
    chain's dimension into ``analogs.select_analogs`` and ``analogs._dims_first`` moved it to the front
    of the vector the coverage line enumerates -- and ``first_dim`` appeared ZERO times in this module,
    so nothing on the page said WHY that dimension led. A reordering nobody is told about is not an
    attribution; lane N's mandate clause is conditional on exactly this mark, and without it the
    condition was never true.

    IT IS A STATEMENT ABOUT READING AND NEVER ABOUT SELECTION, which is why the clause says "read as".
    ``_dims_first`` cannot move the distance (an unweighted mean over the declared dimensions), so the
    stanza the reader is shown is the same stanza either way; what changed is which dimension the
    coverage line enumerates first. And the mark is printed ONLY where the dimension the leg LEADS
    WITH is the one the chain was read on: where ``_dims_first`` no-opped, this clause is absent rather
    than claiming a lead that did not happen. (Round 4's docstring said "only where the order actually
    MOVED", which the CODE never checked and which the census refuted -- ``moved == 0`` with the mark
    on two stanza heads, because the lead was already the chain's. The rule below is the true one.)

    **AND ONLY WHERE THAT DIMENSION IS A HOP THE CHAIN ACTUALLY CARRIES** (round-5 blocker 6).
    ``seam._dim_for_hop`` translates a hop onto the id the analog leg ranks its SERIES under, and on
    the estate's own ONI collision (``board.py:700``: one reading, 35 rows, two directions) the board
    declares ``El_Nino`` where the chain walks ``La_Nina``. MEASURED on 3 of the 4 cells that carry a
    mark -- 4 of the 6 printed marks -- one page read "CHAIN first of three, from LA NINA to ICE
    canola", "chain La Nina [N4]: at the eighty-second percentile", and then "LIKE STATE EL NINO ...;
    read as the history of the chain named first, ON EL NINO": the same series under two spellings, in
    OPPOSITE PHASES, under the one clause on this page whose entire job is attribution. A rename inside
    an attribution is the estate's standing string-identity failure in its smallest form.

    So ``chain_dims`` -- the top rendered chain's own hop ids, handed down by :func:`render_board` from
    the same ``Chain.rank`` order ``seam._first_dim`` reads -- decides: the mark names the chain's OWN
    driver word or it does not print. The TRANSLATION is untouched and still orders the stanza (a
    reading the reader keeps); what it no longer does is put a word the chain never carried inside a
    sentence that says "the chain named first". A caller passing no ``chain_dims`` gets no mark, which
    is the flag-off answer and the honest one: a mark that cannot be checked against the chain is a
    claim about a row this producer cannot see.

    "the chain named first" IS THE PAGE'S OWN ORDINAL and it is now the rank's (round-4 MINOR 2), so
    the row this clause points at is the row ``seam._first_dim`` read.

    **AND THE TRANSLATION IS NOW SPOKEN INSTEAD OF SWALLOWED** (this lane's D5). Round 5 closed the
    rename by going SILENT: where the leg leads with the TRANSLATION of a chain hop, ``fd`` is not in
    ``chain_dims`` and the mark did not print at all. MEASURED over the twelve chain-on served cells:
    six marks printed and two chain-on cells said nothing, one of them for exactly this reason --
    ``named_one`` at deep, where the top chain is ``La_Nina -> drought -> cot_mm_positioning``,
    ``seam._dim_for_hop`` translates ``La_Nina`` onto ``El_Nino`` (one series, ``oni_climate|_global|``,
    two phases), ``analogs._dims_first`` leads the stanza with ``El_Nino`` and the page printed
    "LIKE STATE El Nino ..." with nothing saying why, beside chain rows reading LA NINA. A silence is
    not a correction: the stanza REALLY IS that chain's history, read on the series they share, and the
    reader was owed the pairing.

    So ``chain_dim_names`` -- ``{the analog leg's dimension id: that hop's OWN driver id}``, built by
    ``render_board`` off ``seam.dim_for_hop``, which is the ONE owner of the hop-to-dimension rule --
    gives the clause a SECOND ARM. The first arm is unchanged and still names the dimension. The
    second names the CHAIN'S own word and says the series is the same one: "read as the history of the
    chain named first, which carries that series as La Nina". Neither arm can name a driver the chain
    does not carry, and a caller that passes neither argument gets the flag-off answer, which is
    silence."""
    fd = str((a or {}).get("first_dim") or "")
    order = list((a or {}).get("dims_order") or ())
    if not fd or not order or str(order[0]) != fd:
        return ""
    # **AND ONLY WHERE THE CHAIN'S DIMENSION WAS ACTUALLY READ AT THE LIKE DATE** (09-23, item 6 / R-13).
    # A stanza matched on two of five dimensions was marked as a chain's history although the chain's own
    # dimension carried no reading at that date -- the max page read the warm-phase like state as "the
    # history of the carryout chain named first". The fact is the selection half's own (``per_dim``: a
    # dimension with a z at the like date is one it SAW, analogs.py:773-779); a row carrying no
    # ``per_dim`` (every hand-built deck row) keeps HEAD's rule.
    per = (a or {}).get("per_dim")
    if per is not None:
        seen = {str((r or {}).get("id") or "") for r in (per or ())
                if (r or {}).get("gap") is not None or "z" in tuple((r or {}).get("observed") or ())}
        if fd not in seen:
            return ""
    _hn = dict(hop_names or {})
    if fd in {str(d) for d in (chain_dims or ()) if str(d or "")}:
        return "; read as the history of the chain named first, on %s" % (_hn.get(fd) or humanise(fd))
    # THE TRANSLATED ARM. The pairing is only ever consulted for a hop the TOP CHAIN CARRIES: the name
    # it hands back has to be checkable against `chain_dims`, or this clause would be asserting an
    # attribution off a map nobody on this page can audit.
    own = str((chain_dim_names or {}).get(fd) or "")
    if own and own != fd and own in {str(d) for d in (chain_dims or ()) if str(d or "")}:
        # 09-23 (CONTRACT.md C1/C9): WHERE THE CHAIN NAMES ITS HOP BY ITS SERIES, THE TRANSLATION NEEDS NO
        # SECOND SENTENCE. The pairing exists only because the two ids read ONE series (``seam.dim_for_hop``
        # translates on the series key), so the chain's own name for its hop IS the name of the series the
        # stanza was read on -- the first arm's shape, in the chain's word, never the board's id. A caller
        # with no hop names (every hand-built deck row) keeps the round-5 sentence byte for byte.
        if _hn.get(own):
            return "; read as the history of the chain named first, on %s" % _hn[own]
        return ("; read as the history of the chain named first, which carries that series as %s"
                % humanise(own))
    return ""


def _chain_dim_name_map(bd, hops) -> dict:
    """``{the analog leg's dimension id -> that hop's OWN driver id}`` for the top chain's hops.

    ONE OWNER, READ LAZILY. ``seam._dim_for_hop`` is the rule -- among the rows serving a hop's SERIES
    KEY, the loudest in ``Board.order`` is the id a declared dimension would carry -- and this module
    calls the published accessor rather than re-typing it, because a private second copy would agree
    with the seam until the first edit and then rename a driver inside an ATTRIBUTION. The import is
    lazy: ``seam`` imports this module lazily too, so at module scope the two would close a cycle.

    ONLY TRANSLATIONS ARE KEPT. Where the accessor hands back the hop's own spelling there is nothing
    to translate and arm one of :func:`chain_stanza_mark` already names it. A seam that cannot be
    imported or a hop that answers nothing leaves the entry out, and the mark then says nothing --
    round 5's answer, which is the safe one."""
    try:
        from leviathan.graphrag.state import seam as _seam
    except Exception:                                   # noqa: BLE001 -- a lookup never costs a row
        return {}
    own_ids = {str(getattr(h, "driver_id", "") or "") for h in (hops or ())}
    out: dict = {}
    for h in (hops or ()):
        own = str(getattr(h, "driver_id", "") or "")
        if not own:
            continue
        try:
            got = _seam.dim_for_hop(bd, h)
        except Exception:                               # noqa: BLE001 -- a lookup never costs a row
            continue
        got = str(got or "")
        # A DIMENSION THE CHAIN ITSELF WALKS IS NEVER RE-POINTED. Where two hops of one chain translate
        # onto the same dimension and one of them IS that dimension, arm one owns it: the mark then
        # names the chain's own word without a translation at all.
        if got and got != own and got not in own_ids:
            out.setdefault(got, own)
    return out


#: The three finer reasons ``analogs.select_analogs`` records on ``detail`` when it declines, as the
#: sentence each one owes -- and NOT as a fourth decline word. ``board.ANALOG_REASONS`` keeps its one
#: word (``no_like_state``); ``detail`` is a FIELD on the row, so ``board.DETAIL_REASONS``,
#: :data:`ABSENCE_WHY` and clause 9's one-sentence-per-word rule are all untouched by this map. The
#: slot is the COUNT each reason is honest about, in words, and a reason with nothing to count says so
#: without one.
ANALOG_DETAIL_WHY: dict = {
    "no_candidates": "the record holds no crossing on this series at all, so there is no past state "
                     "to compare this one against",
    # 09-23 DESK VOCABULARY (CONTRACT.md C13): the lag the model allows, never "its own declared window".
    "window_open": "every crossing the record holds is too recent for the lag the model allows it to "
                   "have run out, so none of them has an outcome yet",
    "unobservable": "the candidate dates sit inside the record and carry no reading that can be "
                    "compared there",
}


def sb_analog_decline_detail(a: dict) -> str:
    """SB-A: the ONE extra sentence a declined like state owes, under the word it already declined on.

    WHY IT IS A SENTENCE AND NOT A WORD (this lane's D1, settled by RENDERING the proposal). The
    handoff asked for ``pre_coverage`` to take the analog producer; :data:`ABSENCE_WHY` is keyed by
    WORD ALONE and that word already carries the TAPE leg's sentence, so the proposed row prints, in
    full, "BOARD ABSENCE a like state on this market: the as-of sits before this market's own price
    history begins" -- false for ``unobservable``, where the as-of is today. Clause 9 of
    ``state/lint.py`` forbids a second sentence per word in either direction, so the finer reason
    cannot be a word at all. It is this line.

    IT IS LETTERS-ONLY, like every other member of its class: the one count it may carry renders
    through :func:`words_for_int`, and it names no dimension -- ``record_span`` and ``dims_order`` hold
    raw driver ids and ``register.internal_leaks`` is never relaxable.

    NO SERVED FIXTURE CELL REACHES THIS BRANCH TODAY (0 declines on 18 of 18 served cells after the
    R3a relaxation), so the pin is the deck's and the arm's and this docstring says so rather than
    claiming a page measurement nobody made."""
    why = ANALOG_DETAIL_WHY.get(str((a or {}).get("detail") or ""))
    if not why:
        return ""
    lead = ("LIKE STATE %s on %s: %s"
            % (humanise(str((a or {}).get("driver_id") or "")),
               board_label(str((a or {}).get("contract") or "")), why))
    n = (a or {}).get("n_dropped_unreadable")
    if str((a or {}).get("detail") or "") == "unobservable" and n is not None:
        n = int(n)
        return ("%s; %s such %s were ranked past and none of them could be read"
                % (lead, words_for_int(n), "date" if n == 1 else "dates"))
    n = (a or {}).get("n_candidates_raw")
    if str((a or {}).get("detail") or "") == "window_open" and n is not None:
        n = int(n)
        return ("%s; %s such %s stand in the record" % (lead, words_for_int(n),
                                                        "crossing" if n == 1 else "crossings"))
    return lead


def sb_analog_outcome(n: int, o: dict, *, asof: str, scale=1.0, block=None) -> tuple:
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
    # 09-23 DESK VOCABULARY (CONTRACT.md C13): the class token is the chain outcome's own spelling
    # ("over the band declared from that state", one alternation of SB-O's regex) and the two ends of
    # the band are said as WHEN the lag opened and closed -- never the instrument's "near end" / "far
    # end". Both figures keep their handles and their values.
    _scalar(block, round(float(near_v), 4), unit=o.get("unit") or "", kind="outcome_move", handle=n,
            text=_fmt(near_v))
    _scalar(block, round(float(far_v), 4), unit=o.get("unit") or "", kind="outcome_move", handle=n + 1,
            text=_fmt(far_v))
    line = (f"- [N{n}] {o['label']} over the band declared from that state, "
            f"{band_words(o.get('band'))}: moved {_fmt(near_v)} "
            f"{o.get('unit') or ''} by the time that lag opened; [N{n + 1}] moved {_fmt(far_v)} "
            f"{o.get('unit') or ''} by the time it closed")
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


#: EVERY CHARACTER A PROPOSITION'S IDENTITY IGNORES -- case, punctuation and run-together whitespace.
#: Two chunks of one document, a GAIN paragraph chunked twice and the eleven byte-identical footer
#: copies a PM read on one turn are ONE proposition, and this is what makes them one.
_PROP_FOLD_RX = re.compile(r"[^a-z0-9 ]+")
_PROP_WS_RX = re.compile(r"\s+")

#: How many characters of a folded proposition decide its identity. A whole passage differs in its
#: tail far more often than in its claim (a chunker's window moves, a footer gains a date), so the
#: identity is the OPENING -- long enough that two different claims cannot collide, short enough that
#: one claim re-chunked is one proposition.
PROP_IDENTITY_CHARS: int = 160


def prop_identity(text: str) -> str:
    """The NORMALISED identity of a retrieved proposition -- the key the frequency rule dedupes on.

    **FREQUENCY IS NOT EVIDENCE** (owner, 2026-09-17). A proposition repeated across many documents or
    chunks -- the monthly outlook sentence, a GAIN paragraph chunked twice, the byte-identical footer
    copies -- must not crowd the candidate pool or win a chain's receipt by repetition. A rerank over a
    pool where one sentence occupies six seats is a rerank of six votes for one claim, and the tail
    proposition that a PM pays for loses to it every time. So the pool is folded to one entry per
    proposition BEFORE anything ranks it."""
    s = _PROP_FOLD_RX.sub(" ", ascii_text(str(text or "")).lower())
    return _PROP_WS_RX.sub(" ", s).strip()[:PROP_IDENTITY_CHARS]


def dedupe_props(props, *, asof: str = "") -> list:
    """The candidate pool folded to ONE ENTRY PER PROPOSITION, earliest instance first, each carrying
    the count of the LATER mentions it stands for.

    **THE EARLIEST DATED INSTANCE IS THE EVENT; THE REST ARE ECHOES** (owner, 2026-09-17). The first
    report of a ban IS the action; a later article mentioning it is a mention of the action, and a
    receipt row that dates the action to the echo dates it wrong. So the survivor of a fold is the
    instance with the earliest EVENT date (then the earliest publication date), and the number of
    instances behind it rides on ``echoes`` so the block can print it rather than lose it.

    **PIT IS ONE OF THE TWO HARD FILTERS AND IT IS APPLIED HERE** (DESIGN B.4): a proposition whose
    publication date or whose event date is AFTER the as-of never reaches a reader. Everything else in
    this design corrects or computes; these two delete, by ruling.

    **AND AN ECHO IS ANOTHER DOCUMENT, NEVER ANOTHER CHUNK.** The count says "reported again in four
    later documents", so its unit is the DOCUMENT -- ``(source, published date)`` -- and not the number
    of times one passage reached this pool. The same passage arrives twice on every served turn by
    construction, because the board carries three propositions per row AND the turn's whole grounded
    set is threaded beside them; counting instances would have made every receipt on every turn read
    as an echo of itself."""
    fold: dict = {}
    docs: dict = {}
    order: list = []
    for p in (props or ()):
        if not isinstance(p, dict):
            continue
        d, ed = str(p.get("date") or "")[:10], str(p.get("event_date") or "")[:10]
        if asof and ((d and d > str(asof)[:10]) or (ed and ed > str(asof)[:10])):
            continue
        key = prop_identity(p.get("text"))
        if not key:
            continue
        if key not in fold:
            fold[key] = dict(p)
            docs[key] = {(str(p.get("source") or ""), d)}
            order.append(key)
            continue
        docs[key].add((str(p.get("source") or ""), d))
        # THE SURVIVOR IS THE EARLIEST INSTANCE, and the EVENT date decides before the publication date:
        # two reports of one action carry one event date and two publication dates, and the action is
        # what the chain's receipt is about.
        mine = (ed or "9999", d or "9999")
        kept = fold[key]
        theirs = (str(kept.get("event_date") or "9999")[:10], str(kept.get("date") or "9999")[:10])
        if mine < theirs:
            fold[key] = dict(p)
    return [dict(fold[k], echoes=max(0, len(docs[k]) - 1)) for k in order]


def echo_words(n) -> str:
    """"reported again in four later documents" -- the count the fold above would otherwise throw away.

    IT IS A COUNT AND NOT A WEIGHT. Repetition never moves a chain's rank (frequency is not evidence);
    it is a fact about the corpus that a reader may want, so it is printed and nothing else."""
    try:
        k = int(n or 0)
    except (TypeError, ValueError):
        return ""
    if k <= 0:
        return ""
    return ("reported again in %s later %s" % (words_for_int(k), "document" if k == 1 else "documents"))


def _event_interval(event_date, precision: str = "") -> tuple:
    """The calendar interval a dated event covers AT ITS PRECISION -- lane W's ONE producer
    (``walk.event_interval``, CONTRACT.md C7), read lazily and defensively; a tree without it reads the
    date at face value, which is HEAD's reading."""
    try:
        from leviathan.graphrag.state import walk as _w
        fn = getattr(_w, "event_interval", None)
    except Exception:                                   # noqa: BLE001
        fn = None
    if fn is not None:
        try:
            return tuple(fn(event_date, precision) or ())
        except Exception:                               # noqa: BLE001 -- an unplaceable date has no interval
            return ()
    ed = str(event_date or "")[:10]
    return (ed, ed) if ed else ()


def event_when_words(interval, precision: str = "", *, prep: bool = True) -> str:
    """A dated event's date AT ITS OWN PRECISION, in the PAGE's words (CONTRACT.md C7): ``during 2026``,
    ``in the first quarter of 2026``, ``in January 2026``, ``on 10 March 2025`` -- and, with
    ``prep=False``, the same without the preposition ("2026", "the first quarter of 2026", ...).

    THE DEFECT: the extractor normalises a coarse date to its first day, so "during 2026" is stored as
    2026-01-01 and the board printed "a dated action on 2026-01-01" -- which the cotton writer carried to
    the page as "dated January 2026" (FA-5). The interval is lane W's (:func:`_event_interval`); a year
    is spelled as a year, a quarter as a quarter, and only a DAY is spelled as a day. The day form is the
    long form ``verify._claim_number_spans`` rule (d) already exempts, beside an ISO date's rule (a)."""
    iv = tuple(interval or ())
    if len(iv) != 2 or not iv[0]:
        return ""
    s = str(iv[0])[:10]
    try:
        y, m = int(s[0:4]), int(s[5:7])
    except (TypeError, ValueError):
        return ""
    p = str(precision or "").strip().lower()
    if p == "year":
        return ("during %04d" if prep else "%04d") % y
    if p == "quarter":
        q = ORDINAL_WORDS[(m - 1) // 3 + 1]
        return ("in the %s quarter of %04d" if prep else "the %s quarter of %04d") % (q, y)
    if p == "month":
        mw = month_words(s)
        return ("in %s" % mw) if prep else mw
    dw = day_words(s) or s
    return ("on %s" % dw) if prep else dw


def _event_words(kind: str, *, event_date: str, precision: str = "", published: str = "") -> str:
    """THE RECEIPT'S SENTENCE PER EVENT KIND (CONTRACT.md C7), in the page's own words. The kind is lane
    W's classifier's (``walk.hop_event``); every word here is this page's. ``published`` is the
    document's own date, printed as a day."""
    iv = _event_interval(event_date, precision)
    when = event_when_words(iv, precision) or ("on %s" % str(event_date or "")[:10])
    bare = event_when_words(iv, precision, prep=False) or str(event_date or "")[:10]
    pub = day_words(published) or str(published or "")[:10]
    if kind == "guidance":
        return "a dated forecast, published %s, about %s -- not an action" % (pub, bare)
    if kind == "report_in_reach":
        # A REPORT WRITTEN INSIDE THE PERIOD IT DESCRIBES (review WT F-1): dated by its publication and
        # the period at its precision -- never "a forecast", never "not an action".
        return "a dated report, published %s, about %s" % (pub, bare)
    if kind == "regime_in_force":
        # THE DRAW LAW (review WT M-1; walk's CHAIN_REGIME_WORDS carries it): the newest action is the
        # newest THIS TURN RETRIEVED -- a regime read off a retrieval sample, never off the node's ledger.
        return ("the newest dated policy action on this link that this turn retrieved is %s; the model "
                "treats a policy as in force until a later dated action on the same link" % bare)
    if kind == "action_closed":
        return ("a dated action %s, read as history: the lag the model allows for it has run out"
                % when)
    if kind == "action_aged":
        return CHAIN_RECEIPT_AGED % when
    return "a dated action %s, and the lag the model allows for it is still open" % when


def chain_receipt(ch, pool=None, *, asof: str = "") -> dict:
    """DESIGN B.4's ORDER OF CHOICE at a chain's RECEIPT HOP, over the widest pool this turn HAS.

    ``{"kind", "prop", "words", "hop", "echoes", "outside", "event_kind"}``; ``kind`` is one of ``open``
    / ``closed`` / ``mechanism`` / ``none`` (HEAD's four, which decide the ``[E]`` seat), and
    ``event_kind`` is lane W's closed :data:`walk.EVENT_KINDS` word for the document chosen. The order
    is (1) an OPEN dated action, (2) a recently-CLOSED one read as history -- or, on a node the graph
    types as a policy, the newest dated action read as the REGIME in force until a later dated action
    (owner decision 3) -- (3) a dated FORECAST, which is a document about the mechanism and never an
    action (the cotton turn scored a conditional 2026 forecast as an open action, 20 of 20 points),
    (4) a dated report sentence about that hop's mechanism, (5) none -- and (5) NAMES THE DRAW rather
    than the corpus (:data:`CHAIN_NO_RECEIPT`, threat E6).

    **THE CLASSIFIER IS LANE W's AND IT IS CALLED, NEVER RE-TYPED** (09-23, CONTRACT.md C7):
    ``walk.hop_event`` reads each dated proposition's interval AT ITS PRECISION against its own document
    date. It is called on the WIDER pool this producer folds, so the page and the walk read one rule;
    on a tree where it has not landed, HEAD's own branch below runs unchanged.

    **THE POOL IS FOLDED BEFORE ANYTHING IS CHOSEN** (:func:`dedupe_props`), so a proposition repeated
    in six chunks holds ONE seat and the tail proposition beside it is not crowded out; and the EVENT
    is taken at its EARLIEST instance with the later mentions counted, because the first report of an
    action is the action.

    **AND THE CLOSED BRANCH CARRIES THE WALK'S OWN RECENCY BOUND** (round-4 census 8): a closed action
    more than one band-length before the as-of is NOT this chain's receipt -- ``walk._receipt_in_reach``
    is the one rule -- and it is printed with :data:`CHAIN_RECEIPT_AGED` where the chain would otherwise
    have said it retrieved nothing. Counted, never deleted; and it spends no ``[E]`` seat of the chain's
    own, because a document this chain cannot claim must not cost the page a citation.

    **AND A RECEIPT OUTSIDE ITS WINDOW RENDERS WITH THE WORDS AND NEVER INSIDE IT** (threat E4): the
    correction, not the deletion. ``pool`` -- the subgraph the turn already grounded -- is the WIDER
    half, and where no pool is threaded this reads the walk's own rows, so the harness path and the
    served path agree on every board.

    THE DOCUMENT OF AN AGED ACTION OR A REFUSED REPORT RIDES ``prop`` TOO (09-23, item 4), with ``kind``
    still ``none`` so no seat is spent: the render cites it at the turn's OWN evidence-menu address when
    the menu carries it -- one document, one address -- and prints no handle otherwise."""
    out = {"kind": str(getattr(ch, "receipt_kind", "none") or "none"),
           "prop": dict(getattr(ch, "receipt", None) or {}) or None,
           "words": str(getattr(ch, "receipt_words", "") or ""), "hop": ch.receipt_hop,
           "echoes": 0, "outside": False,
           "event_kind": str(getattr(ch, "event_kind", "") or "")}
    if not ch.hops:
        return out
    import dataclasses

    from leviathan.graphrag.state import walk as _walk
    from leviathan.graphrag.state.walk import _receipt_in_reach, projection_window
    _hop_event = getattr(_walk, "hop_event", None)
    order = [ch.receipt_index] + [i for i in range(len(ch.hops)) if i != ch.receipt_index]
    best = None                                          # the first CLOSED action (or regime) in order
    guide = None                                         # the first dated FORECAST in order
    aged = ""                                            # the newest CLOSED action out of every reach
    aged_prop = None                                     # ...its proposition
    aged_prec = ""                                       # ...and the precision it was dated at
    refused = ""                                         # the newest REPORT sentence the bound refused
    refused_prop = None
    refused_hop = None                                   # ...and the hop it sits on (blocker 1)
    aged_hop = None                                      # ...THE HOP IT SITS ON (round-5 blocker 4)
    aged_ids: set = set()                                # ...and WHICH documents those were
    for i in order:
        hop = ch.hops[i]
        cands = list(hop.receipts_top or ())
        if hop.event_receipt:
            cands = [dict(hop.event_receipt)] + cands
        if pool:
            cands += list(pool.get((hop.contract, hop.driver_id)) or ())
        folded = dedupe_props(cands, asof=asof)
        events = [p for p in folded if str(p.get("event_date") or "")]
        if not events:
            continue
        if _hop_event is not None:
            # THE CLASSIFIER'S STAMP: the walk's own step-5 reading of HEAD's winner, so one document is
            # read one way whoever built the candidate list.
            _stamp = ({"event_date": hop.event_date, "event_open": hop.event_open,
                       "event_precision": getattr(hop, "event_precision", "")}
                      if getattr(hop, "event_date", None) else None)
            _nt = str(getattr(hop, "driver_type", "") or "")
            # EVERY DOCUMENT IS CLASSIFIED ALONE FIRST, for the two facts the chosen one cannot carry: which
            # documents AGED OUT (never re-labelled below as a mechanism report) and the newest of them.
            for p in events:
                one = _hop_event([p], asof=asof, band=hop.lag_band, node_type=_nt, stamped=_stamp)
                if one.get("kind") == "action_aged":
                    aged_ids.add(prop_identity(p.get("text")))
                    ed = str(p["event_date"])[:10]
                    if ed > aged:
                        aged, aged_hop, aged_prop = ed, hop, p
                        aged_prec = str(one.get("precision") or "")
            ev = _hop_event(events, asof=asof, band=hop.lag_band, node_type=_nt, stamped=_stamp)
            ek = str(ev.get("kind") or "none")
            p = dict(ev.get("receipt") or {})
            ed = str(ev.get("event_date") or "")[:10]
            prec = str(ev.get("precision") or "")
            # THE CHOSEN DOCUMENT IS THE FOLDED ONE: its echo count rides it.
            _fold = next((x for x in events if prop_identity(x.get("text")) == prop_identity(p.get("text"))),
                         p)
            cand = {"prop": _fold, "hop": hop, "echoes": int(_fold.get("echoes") or 0),
                    "outside": False, "event_kind": ek,
                    "words": _event_words(ek, event_date=ed, precision=prec,
                                          published=str(p.get("date") or ""))}
            if ek == "action_open":
                return _chain_receipt_words(dict(cand, kind="open"))
            if ek in ("action_closed", "regime_in_force") and best is None:
                best = dict(cand, kind="closed",
                            outside=bool(ek == "action_closed" and i != ch.receipt_index))
            elif ek in ("report_in_reach", "guidance") and (
                    guide is None or (ek == "report_in_reach" and guide.get("event_kind") == "guidance")):
                # a dated report inside its own period (WT F-1) ahead of a forecast: the walk's own order
                guide = dict(cand, kind="mechanism")
            continue
        # ── HEAD's branch, unchanged, for a tree whose walk carries no classifier ─────────────────────
        for p in events:
            ed = str(p["event_date"])[:10]
            opened = event_window_open(projection_window(ed, hop.lag_band), asof)
            kind = "open" if opened else ("closed" if opened is False else "open")
            cand = {"kind": kind, "prop": p, "hop": hop, "echoes": int(p.get("echoes") or 0),
                    "outside": bool(opened is False and i != ch.receipt_index),
                    "event_kind": "action_open" if kind == "open" else "action_closed"}
            if opened is False and not _receipt_in_reach(
                    dataclasses.replace(hop, event_date=ed), asof):
                if ed > aged:
                    aged, aged_hop, aged_prop = ed, hop, p
                    aged_prec = str(p.get("event_date_precision") or "")
                aged_ids.add(prop_identity(p.get("text")))
                continue
            if kind == "open":
                cand["words"] = _event_words("action_open", event_date=ed,
                                             precision=str(p.get("event_date_precision") or ""))
                return _chain_receipt_words(cand)
            if best is None:
                cand["words"] = _event_words("action_closed", event_date=ed,
                                             precision=str(p.get("event_date_precision") or ""))
                best = cand
    if best is not None:
        return _chain_receipt_words(best)
    if guide is not None:
        return _chain_receipt_words(guide)
    for i in order:
        hop = ch.hops[i]
        cands = list(hop.receipts_top or ())
        if pool:
            cands += list(pool.get((hop.contract, hop.driver_id)) or ())
        for p in dedupe_props(cands, asof=asof):
            if not p.get("date"):
                continue
            # ROUND-5 CENSUS BLOCKER 1 (reproduced on both trees): THE SAME BOUND THE WALK'S CHOICE (3)
            # NOW READS, on the candidate's OWN date. Without it a report sentence the score refuses
            # (EVENT 0, "no dated document in this hop's window") was still this page's mechanism
            # receipt -- two producers disagreeing about one document. A refused sentence is
            # RECORDED (newest date, its hop) and NAMED below, never dropped.
            _rd = str(p["date"])[:10]
            if asof and not _receipt_in_reach(dataclasses.replace(hop, event_date=_rd), asof):
                if _rd > refused:
                    refused, refused_hop, refused_prop = _rd, hop, p
                continue
            # AND NOT UNDER A SECOND LABEL EITHER. A dated ACTION the recency bound just refused
            # usually carries a publication date too, so without this the same document came straight
            # back as choice (3) -- "a dated report on this hop's mechanism, 2021-05-13" -- which is
            # the aged action re-labelled rather than the aged action stated. A document this chain
            # cannot claim is never this chain's receipt, whatever the label.
            if prop_identity(p.get("text")) in aged_ids:
                continue
            return _chain_receipt_words({
                "kind": "mechanism", "prop": p, "hop": hop, "echoes": int(p.get("echoes") or 0),
                "outside": False, "event_kind": "report_in_reach",
                "words": "a dated report on this link's mechanism, published %s"
                         % (day_words(str(p["date"])[:10]) or str(p["date"])[:10])})
    # THE AGED DOCUMENT IS PRINTED WHERE IT WOULD OTHERWISE HAVE BEEN THE RECEIPT, never counted as
    # one: ``kind`` stays ``none`` so no ``[E]`` seat of the chain's own is spent and the chain's own
    # ``receipt_kind`` (the walk's, scored) is untouched, and the reader is told the estate HELD a dated
    # action rather than "this turn retrieved none". A correction that leaves no trace is a deletion.
    if aged:
        # **AND THE ROW NAMES THE HOP THE DOCUMENT SITS ON, NEVER THE CHAIN'S RECEIPT HOP** (round-5
        # blocker 4): ``aged`` is a ``max()`` over the dates found on ANY hop, and the producer's own pair
        # (``Chain.aged_receipt_hop`` / ``_date``, the walk's aged set) is preferred where it names the
        # same document.
        _wh = getattr(ch, "aged_receipt_hop", None)
        if _wh is not None and str(getattr(ch, "aged_receipt_date", "") or "")[:10] == aged:
            aged_hop = _wh
        return {"kind": "none", "prop": aged_prop, "event_kind": "action_aged",
                "words": _event_words("action_aged", event_date=aged, precision=aged_prec),
                "hop": aged_hop if aged_hop is not None else ch.receipt_hop,
                "echoes": 0, "outside": False}
    if refused:
        # THE REFUSED REPORT SENTENCE IS NAMED WHERE THE PAGE WOULD OTHERWISE SAY IT RETRIEVED NOTHING
        # (blocker 1), on the hop it sits on; the producer's own pair is preferred where it names the
        # same date (``Chain.mechanism_refused_hop`` / ``_date``, the walk's seam), as for aged actions.
        _mh = getattr(ch, "mechanism_refused_hop", None)
        if _mh is not None and str(getattr(ch, "mechanism_refused_date", "") or "")[:10] == refused:
            refused_hop = _mh
        return {"kind": "none", "prop": refused_prop, "event_kind": "report_outside",
                "words": CHAIN_RECEIPT_REPORT_OUTSIDE % ("published %s" % (day_words(refused)
                                                                          or refused)),
                "hop": refused_hop if refused_hop is not None else ch.receipt_hop,
                "echoes": 0, "outside": False}
    return {"kind": "none", "prop": None, "words": CHAIN_NO_RECEIPT, "hop": ch.receipt_hop,
            "echoes": 0, "outside": False, "event_kind": "none"}


def chain_document_cite(rp: dict, seen_e=None, evidence_ordinals=None) -> str:
    """THE ``[E]`` A CHAIN'S DOCUMENT ROW CITES, or ``""`` -- one document, one address.

    (1) Where the EVENTS section already minted an ``[E]`` for this very proposition on this very row,
    that handle (``seen_e``) -- HEAD's rule. (2) **09-23, item 4 / threat R-14:** a document the chain
    NAMES AND CANNOT CLAIM -- an aged action, a refused report (``kind == "none"`` with the document on
    ``prop``) -- carries the turn's OWN evidence-menu ordinal where the menu holds it, keyed on the
    document's ``source_key`` (the one identity ``citations.unify`` numbers the menu by), so the handle
    resolves to the document the row names. It mints nothing and spends no seat of the chain's cap; a
    document the menu does not hold keeps HEAD's no-address row. The max page's "the dated report at the
    crude hop is from 2005-09-01" had no address, so the writer invented ``[E13]`` and the orphan prune
    removed it (max F13)."""
    rp = dict(rp or {})
    if seen_e and rp.get("prop"):
        return " [E%d]" % int(seen_e)
    if rp.get("kind") == "none" and rp.get("prop") and evidence_ordinals:
        ordn = (evidence_ordinals or {}).get(str((rp.get("prop") or {}).get("source_key") or ""))
        if ordn:
            return " [E%d]" % int(ordn)
    return ""


def sb_chain_document(rp: dict, hop, *, cite_e: str = "") -> str:
    """The chain's DOCUMENT row, NAMING THE HOP THE DOCUMENT ACTS ON (round-2 item R-2).

    See :data:`CHAIN_DOCUMENT_AT` for the measurement that forced it. ``rp`` is
    :func:`chain_receipt`'s own dict, unchanged -- this composes the row around its sentence and adds
    nothing to it, so the four branches (open, closed, mechanism, none) each keep the wording their
    threat model bought and each gains one antecedent the reader can resolve.

    THE SOURCE IS NOT REPEATED HERE. The document reaches the reader's address either as the EVENTS
    section's own ``[E]`` (cited by this row, one document one address) or as the chain's own SB-R row
    below it, and BOTH of those carry the source, the tier and both dates by construction
    (:func:`sb_receipt`). A source named a third time on this row would be the same fact at a third
    address, which is the law this section spends bytes to keep."""
    name = (chain_hop_name(hop) if hop is not None else "") or "this link"
    return CHAIN_DOCUMENT_AT % (CHAIN_SUB_PREFIX, name, str(rp.get("words") or ""), cite_e)


def _chain_receipt_words(cand: dict) -> dict:
    """The echo count and the outside-window clause, appended to a chosen receipt's own sentence."""
    extra = []
    if cand.get("outside"):
        extra.append(CHAIN_OUTSIDE_WINDOW)
    ew = echo_words(cand.get("echoes"))
    if ew:
        extra.append(ew)
    if extra:
        cand["words"] = "%s (%s)" % (cand.get("words") or "", "; ".join(extra))
    return cand


#: The words a nomination wears when its falsifier cannot resolve inside the turn's horizon. ONE
#: PRODUCER (``watch.horizon_miss_clause``), reached through a lazy import because ``watch`` imports
#: THIS module for its display vocabulary -- so the two spellings can never drift.
def _horizon_miss_clause(cause: str, *, next_print: str = "", faster: str = "") -> str:
    from leviathan.graphrag.state.watch import horizon_miss_clause
    return horizon_miss_clause(cause, next_print=next_print, faster=faster)


def sb_watch(w: dict) -> str:
    """SB-W (sec 6.2, 5.1): the UNHANDLED watch row -- letters and ISO dates and nothing else. Every row
    names a table, a level, a date or a document; nothing here produces "watch the weather".

    KIND 2 IS THE ONE WATCH ROW THAT CARRIES A FIGURE and it renders through :func:`sb_convention`
    instead, under its own class, so this builder can never take a handle: an unhandled magnitude on a
    watch row is exactly the digit ``verify._claim_number_spans`` charges.

    ``backing_handle`` IS A CITATION AND NOT A MAGNITUDE (S7b). A non-obvious nomination has to name
    the row it rests on -- the ruling's own words, "its backing row" -- and the estate's way of naming
    a row is its ``[N]``. It mints NOTHING: the handle already belongs to the SB-1 line that printed
    that row's level, exactly as :func:`sb_path` cites the handles of the rows its chain passes
    through, and ``verify._claim_number_spans`` rule (d) exempts a handle from the digit charge. HEAD's
    five kinds carry no such key, so every HEAD row renders byte for byte.

    **THE SLOT MARK IS THE TIER'S CEILING, MADE VISIBLE** (review round 2, MAJOR 2). ``watch.nonobvious_k``
    sized the draw 3 / 5 / 7 and ``watch.nonobvious_rows`` stamped ``slot`` -- and this builder printed
    the SAME line for a ceiling row and a nomination row, so the writer met 6 / 10 / 12-14 equal-looking
    items under a ceiling it could not see (MEASURED, ``scratchpad/s7b_verify/ARMED.txt``). The mark
    names the pass, the row's place in it and that pass's size, IN WORDS -- SB-W is a letters-only class
    and "core item one of five" is letters, where "1 of 5" would be two charged digits on a row that
    asserts no magnitude. It sits after the citation and before the colon, so ``_nomination_coverage``'s
    "- WATCH {kind words} " discriminator, ``classify``'s ``^- WATCH`` and every token group are
    untouched. HEAD's five kinds carry no ``slot``, so they render byte for byte."""
    dates = w.get("dates") or ""
    tail = f" -- {dates}" if dates else ""
    h = w.get("backing_handle")
    # THE HANDLE SITS ON THE LABEL, which is the ROW it names -- not at the end of the body, where it
    # would interrupt the sentence that ends "on these dates" immediately before the ISO tail.
    cite = f" [N{int(h)}]" if h else ""
    mark = ""
    if w.get("slot") and w.get("slot_size"):
        word = "core item" if w.get("slot") == "ceiling" else "alternate"
        mark = (f" ({word} {words_for_int(int(w['slot_index']))} of "
                f"{words_for_int(int(w['slot_size']))})")
    # THE CLOCK (lane D, the 2026-09-16 smoke). The PM graders found NO scheduled catalyst anywhere on
    # five served answers -- no 09-30 Grain Stocks, no 10-09 WASDE, no weekly export sales -- because
    # the calendar was named once in a footnote the writer read as boilerplate ("the scheduled
    # publication dates ... are not watch items"). The ban on calendar-ONLY nominations is untouched;
    # what an admitted row now carries is the date its own series next prints, as a field the writer is
    # told to print. And where that print cannot land inside the turn's horizon the row SAYS SO, in
    # words, rather than offering a falsifier that can never resolve -- the deep turn's item one was an
    # ANNUAL PSD series with a "reads wrong if the next print" clause on a three-month question.
    #
    # **THE NOTE FOLLOWS THE ROW'S OWN DATED TAIL, AND THE CLOCK RIDES INSIDE IT** (review round 2,
    # MAJOR 7). Round 1 spliced the note into the BODY, before ``tail``, and the row rendered
    # "... read it as standing context and watch a faster series on the same mechanism instead
    # -- 2024-12-31; next print 2026-09-09": the like-state date orphaned onto the end of the NOTE's
    # advice, reading as the date of the advice, and a bare "next print" offered two days after the
    # as-of by a note that had just denied any checkable print inside the horizon. Both halves are the
    # same defect -- an insertion that orphans a clause is the fence doctrine's fatal, produced by
    # adding rather than deleting. The row is now ``{body}{tail}``, THEN the clock or the note; and the
    # note NAMES the scheduled print itself (``watch.horizon_miss_clause``), so the two can never
    # contradict each other because only one of them is ever printed.
    body = str(w.get("what") or "")
    clock = f"; next print {w['next_print']}" if w.get("next_print") else ""
    note = ""
    if w.get("horizon_miss"):
        note = " NOTE: " + _horizon_miss_clause(str(w.get("horizon_miss")),
                                                next_print=str(w.get("next_print") or ""),
                                                faster=str(w.get("horizon_faster") or ""))
        clock = ""                                      # the note carries the date; never twice
    return f"- WATCH {w['kind_words']} {w['label']}{cite}{mark}: {body}{tail}{clock}{note}"


#: AN ORDINAL IN WORDS, for the letters-only classes. :func:`ordinal` prints "1st", which is a CHARGED
#: DIGIT on every class outside :data:`FIGURE_CLASSES`; this is the same rank said in letters. Small by
#: design -- the only caller counts to three.
ORDINAL_WORDS: tuple = ("", "first", "second", "third", "fourth", "fifth", "sixth", "seventh",
                        "eighth", "ninth", "tenth")


def ordinal_words(n) -> str:
    try:
        i = int(n)
    except (TypeError, ValueError):
        return ""
    return ORDINAL_WORDS[i] if 0 < i < len(ORDINAL_WORDS) else f"number {words_for_int(i)}"


#: HOW MANY ROWS THE LEAD NAMES. Three, from ROUND-2 DOCKET item 12's own words ("the top three loud
#: rows are named or their omission explained"); it is the ONE place the number lives, so the block,
#: :func:`board_coverage`'s ``missed.loud_top3`` and the mandate cannot drift to two different threes.
LEAD_ROWS: int = 3


def _lead_name(rows):
    """WHICH ROW OF A FOLDED GROUP THE LEAD NAMES -- the two rules already on this page and no third.

    A member read in the OPPOSITE declared phase is dropped first (the quorum's own rule), and what is
    left is chosen by the fold's own rule: the highest-declared-confidence name, ties on the reader
    label. So the lead, the SB-JOIN line and the quorum row can never name one reading three ways.

    REVIEW ROUND 3, NEW-4: that sentence was a CONSTRUCTION CLAIM written beside THREE implementations
    of the rule, and one of the three (:func:`_series_fold`) chose over a different population. All
    three now call :func:`group_keep`, so the claim is a construction."""
    _rs = {str(r.driver_id): r for r in rows}
    _smap = {d: {"key": "-", "confidence": str(r.confidence or ""), "sign": str(r.sign or ""),
                 "phase": phase_for_state(r.state) or {}} for d, r in _rs.items()}
    return _rs.get(group_keep(_smap, "-")) or min(
        rows, key=lambda r: (CONFIDENCE_RANK.get(str(r.confidence or ""), 3),
                             humanise(r.driver_id)))


def sb_lead(i: int, n: int, row) -> str:
    """SB-LEAD: ONE of the board's largest moves, named in words, before the reader meets anything else.

    LETTERS ONLY AND NO HANDLE (see the class note in :data:`ROW_CLASSES`). It asserts no magnitude: the
    reading's level, z and percentile are on its OWN state line a few lines below under their own
    handles, and minting a second address for one figure is what sec 6.3 forbids. What this row carries
    is the RANK -- which the block had nowhere at all, measured on the utilisation census -- plus the one
    word that says why the row leads, taken from the reading's own desk convention where it crossed one.

    IT IS A SELECTION AND NOT AN ENUMERATION: three rows out of a loud set of eight to twenty-four.

    IT STILL NAMES THE ROW BY ITS DRIVER (09-23, left at HEAD's bytes): the state line it points at now
    names the SERIES and carries the driver as "read here for <driver>", so the lead's name is found on
    that line. Moving the lead's own words is docketed -- its pins live in a deck another lane owns."""
    st = getattr(row, "state", None)
    why = ""
    conv = (getattr(st, "convention", None) or {}) if st is not None else {}
    if conv.get("matched") and conv.get("label"):
        why = f", past the line the desk convention calls {conv['label']}"
    return (f"LARGEST MOVE {ordinal_words(i)} of {words_for_int(n)}: "
            f"{row_words(row.contract, row.driver_id)}{why}; its figures are on its own state line "
            f"below.")


def sb_recency(layer: str, text: str) -> str:
    """SB-L (sec 6.2, 6.5): one line per LAYER, each a fact about the layer it names. None of them
    dates another, and no rendered line contains "not a current-state read" (B12)."""
    return f"RECENCY {layer}: {text}"


def sb_phase_pair(names, board: str, *, opposed: bool, phase: Optional[dict] = None,
                  keep: str = "", alias=(), keep_tied: bool = False) -> str:
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
    tiers that was not byte-identical to HEAD. S8 takes it, with the judged delta already read.

    ── THE DOCKET IS TAKEN, 2026-09-17, AND ARM A'S CONTROL IS UNTOUCHED BY CONSTRUCTION ─────────────
    Arm A's control runs with ``GRAPHRAG_STATE_BOARD`` OFF, so this class does not render in it at all
    and the S7 blocker is gone. Both halves land, each on a MEASURED served defect:

    * ``opposed`` GAINS THE PHASE IN FORCE. The line said the two rows are one reading and never said
      WHICH PHASE that reading is, so the palm turn built a supply-squeeze story on "-0.39 degC" -- a
      COOL-phase number -- and the corn page wrote "opposite signs on each board by phase" with no ENSO
      driver admitted. ``phase`` carries :func:`phase_in_force`'s verdict plus each member's reader name
      and this market's declared sign for it, in WORDS: SB-JOIN is letters-only, the magnitude is
      already on the SB-1 row above with its handle, and nothing is minted here.
    * ``not opposed`` LOSES A FALSE SENTENCE. "They are phases of one series and not separate readings"
      is untrue of both non-opposed joins the banked blocks carry, and the served deep answer repeated
      it and then COUNTED BOTH NAMES into a pattern quorum. The sentence now says what is true -- two
      names for one reading, the same declared sign, ONE piece of evidence -- and names which to keep
      and which is its alias, which is the same fold :func:`sb_convergence` now applies to the count.

    ── REVIEW ROUND 2: THE COUNTS AGREE WITH THE LIST, AND NO NAME IS NOMINATED BY A TIE ─────────────
    MAJOR 1 and MAJOR 2, both measured on round 1's OWN rendered artefact (``D/AFTER_blocks.txt``):
    "BOARD JOIN CPO export levy, DMO and export ban ... They are TWO NAMES for ONE reading" over THREE
    names, and "BOARD JOIN IDR USD, INR USD and MYR USD ... that is one reading TWO DECLARED LINKS
    disagree about" over THREE rows and three declared edges. Round 1 hardcoded the numeral and
    pluralised only the alias noun, and the sentence stated a count its own subject list contradicts one
    clause later. Every count here is now :func:`words_for_int` over the list the line itself prints.

    MAJOR 3: THE UNDECLARED FOLD NO LONGER ISSUES AN ARBITRARY INSTRUCTION. "Read it under IDR USD where
    a direction is needed" was the ALPHABETICAL winner of a three-way tie at ``medium`` confidence -- the
    page named the contradiction honestly and then handed the writer the Indonesian rupiah as the reading
    of a Malaysian palm board. Where the members tie, the TIE IS THE FACT and it is said in words with no
    instruction attached; where one member is strictly the highest-confidence link, it is named AS that
    and not as a preference this page invented."""
    joined = _and_list(names)
    n_names = len([n for n in (names or ())])
    n_words = words_for_int(n_names)
    if opposed and phase and phase.get("live_name"):
        # A DECLARED PHASE PAIR: opposite signs on one series is what a phase pair MEANS, and the
        # clause below says which phase the reading actually is.
        tail = (" The graph declares them opposite signs on this market, which is what two phases of "
                "one series means; they are not two readings that disagree.")
        tail += _phase_clause(phase, board)
    elif opposed:
        # OPPOSITE SIGNS ON ONE READING WITH NO DECLARED PAIR IS NOT A PHASE PAIR, AND HEAD SAID IT WAS.
        # MEASURED on the b40 fixture: `IDR USD`, `INR USD` and `MYR USD` fold onto one series key and
        # carry differing signs, and HEAD rendered "which is what two phases of one series means" over
        # them -- a phase explanation for three currency rows. The honest sentence names the
        # contradiction instead of explaining it away, and still deletes nothing.
        tail = (f" The graph signs these names DIFFERENTLY on one and the same figure and this page "
                f"cannot reconcile them: that is one reading {n_words} declared links disagree about, "
                f"not {n_words} readings.")
        if keep and not keep_tied:
            tail += (f" Where a direction is needed, {keep} is the one of them the graph declares at "
                     f"the highest confidence; the others are the same figure read the other way.")
        else:
            tail += (" The graph declares them at the same confidence, so this page has no ground of "
                     "its own for preferring one of these names over another and does not offer one.")
    elif keep and alias:
        tail = (f" They are {n_words} names for ONE reading carrying the SAME declared sign here, so "
                f"this page holds one piece of evidence and not {n_words}: read it under {keep} and "
                f"treat {_and_list(list(alias))} as "
                f"{'that name-s alias' if len(alias) == 1 else 'aliases of that name'}"
                f", counted once wherever this page counts.".replace("name-s", "name's"))
    else:
        tail = (f" They are {n_words} names for ONE reading carrying the same declared sign here, so "
                f"this page holds one piece of evidence and not {n_words}; count them once.")
    return (f"BOARD JOIN {joined} on {board}: these are read on ONE series and the readings above "
            f"print the SAME figure under each name." + tail)


def _and_list(names) -> str:
    """``a``, ``a and b``, ``a, b and c`` -- the block's ONE Oxford-free join, so two builders cannot
    spell a three-name list two ways."""
    ns = [str(n) for n in (names or ())]
    if len(ns) < 2:
        return ns[0] if ns else ""
    return " and ".join(ns) if len(ns) == 2 else (", ".join(ns[:-1]) + " and " + ns[-1])


def _phase_clause(phase: Optional[dict], board: str) -> str:
    """The PHASE-IN-FORCE half of SB-JOIN, in words and with no digit (:func:`phase_in_force`).

    THREE SENTENCES AND NOT ONE, because the three states are three different facts: a phase IS in
    force and this market declares a sign for it; the reading sits INSIDE the convention's own line so
    NEITHER phase is in force and both signs above are conditional; or the pair is undeclared, in which
    case nothing is said at all (fail-closed: this module never guesses which way an index signs).

    **AND IT SAYS WHICH READING IT READ THE PHASE OFF** (review round 2, MAJOR 10). On a row carrying a
    declared same-series offset the level beside the line is the SHIFTED one, and round 1 computed the
    verdict from it: the b40 line said "the phase in force AT THIS READING is the cool phase" while the
    same row minted the newest knowable figure of the same series one line above. :func:`phase_reading`
    now hands this clause the NEWEST KNOWABLE level wherever the producer banked one, and the subject of
    the sentence changes with it -- a verdict about NOW that was read off a six-month-old number has to
    say so, and one read off the newest number has to say that too."""
    if not phase or not phase.get("live_name"):
        return ""
    live, other = str(phase.get("live_name")), str(phase.get("other_name") or "")
    words, other_words = str(phase.get("words") or ""), str(phase.get("other_words") or "")
    current = bool(phase.get("current"))
    subject = "the newest knowable reading of this series" if current else "this reading"
    lag = ""
    if current and int(phase.get("offset_periods") or 0):
        _n = int(phase["offset_periods"])
        lag = (f" The dated reading above sits {words_for_int(_n)} "
               f"{period_noun(str(phase.get('cadence') or 'monthly'), _n)} back on this market's own "
               f"declared effect lag, so whichever phase IT sits in is not the phase in force now.")
    if not phase.get("in_force"):
        both = f"{words} nor {other_words}" if other_words else words
        return (f" {subject[0].upper()}{subject[1:]} sits INSIDE the line this desk convention draws "
                f"for a phase, so neither {both} is in force at it: the signs above are what {board} "
                f"would carry in each phase, not a sign it carries now.{lag}")
    sign = str(phase.get("live_sign") or "with no committed direction")
    out = (f" The phase in force at {subject} is {words}, which this graph names {live}: on "
           f"{board} the graph declares {live} {sign}, and that is this market's declared sign for "
           f"the phase now in force.")
    if other:
        out += (f" {other} states what {board} would carry in {other_words}, which is not the phase "
                f"{subject} is in.")
    return out + lag


def sb_analog_leg_absence(reason: str, *, not_reached: bool = False) -> str:
    """THE LIKE-STATE ABSENCE AS A PM READS IT, and the word ``episode`` handed over with it.

    TWO MEASURED DEFECTS, ONE ROW. (1) ``BoardAnalogs = 0`` on all five smoke turns, and where the LEG
    declined before building a stanza the block said nothing at all -- a silence, which this block's
    own law forbids. (2) The deep page declared two lines apart that no past state is like the present
    one and then wrote "on the 2011 analogue window the ocean reading was -0.68 degC": the writer had
    no other word for a DATED WINDOW, so it reused the one the likeness rule had just denied. The
    cascade's dated window is an EPISODE -- a stretch of the record, chosen by its dates -- and an
    ANALOGUE is a past state the likeness rule ADMITTED. This row gives the writer the second word so
    it does not borrow the first.

    IT DELETES NOTHING AND IT DOES NOT RE-OPEN THE SELECTION RULE (that is S8's): it is one letters-only
    SB-X line saying what did not happen and what the right word for the other thing is."""
    why = ("the like-state leg was not entered on this turn, so no past state was tested at all"
           if not_reached and not reason else absence_why(reason or "no_like_state"))
    return ("BOARD ABSENCE a like state on this page: " + why
            + ". No past state on these readings was admitted as a LIKE STATE, so this page carries no "
              "analogue and no base rate drawn from one. A dated window that reaches the page from "
              "elsewhere is an EPISODE -- a stretch of the record named by its dates -- and calling it "
              "an analogue would claim a likeness this page did not find.")


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
        #: THE ROW'S HANDLES (CONTRACT.md C2): ``{(contract, driver_id): {"level", "sigma",
        #: "percentile", "peak", "current"}}`` -- every magnitude one SB-1 row minted, by what it is.
        #: ``handles_by_row`` in :func:`render_board` (int map to the LEVEL handle) is UNCHANGED beside it;
        #: this is ADDED so a chain hop line can cite each figure at the address that minted it.
        self.row_handles: dict = {}
        #: THE SERVED-SCALARS POOL (CONTRACT.md C4): every figure a committed row PRINTED, in digits or in
        #: words, registered by the template at the moment it formatted that number. A scalar joins the
        #: pool only with the row that printed it (see :meth:`add`) -- a figure on a corrected line was
        #: never printed and backs nothing.
        self._scalars: list = []
        self._pending: list = []
        #: Refusals the render COUNTED rather than printed: ``role_withheld`` (a provenance token outside
        #: the vintage-role roster), ``chain_hop_unaddressed`` (a hop whose standing had no handle on this
        #: page and was stated in words alone). Absent is zero; nothing here changes a byte of the block.
        self.counters: dict = {}

    def scalar(self, value, *, unit: str, kind: str, row_id: Optional[str] = None,
               handle: Optional[int] = None, text: str = "") -> None:
        """REGISTER ONE PRINTED FIGURE (CONTRACT.md C4) -- called by the template AT THE MOMENT it formats
        that number, so the printed words and the registered scalar are the SAME variable. It is PENDING
        until the row that printed it is committed by :meth:`add`, which binds it to that row's class; a
        row the register fence replaced takes its scalars with it."""
        try:
            v = float(value)
        except (TypeError, ValueError):
            return
        self._pending.append({"value": v, "unit": str(unit or ""), "kind": str(kind),
                              "row_id": (str(row_id) if row_id else None),
                              "handle": (int(handle) if handle else None), "text": str(text or "")})

    def served_scalars(self) -> list:
        """Every figure the committed block printed, one dict per figure: ``{value, unit, kind, row_id,
        handle, cls, text}`` -- the pool the verifier reads (C4)."""
        return [dict(s) for s in self._scalars]

    def count(self, name: str, n: int = 1) -> None:
        """Increment one of :attr:`counters`."""
        self.counters[str(name)] = int(self.counters.get(str(name), 0)) + int(n)

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
        pending, self._pending = list(self._pending), []
        if not line and not allow_empty:
            return ""
        hits = register_hits(line)
        if hits:
            self.trips.append({"label": label or line[:40], "hits": tuple(hits), "line": line})
            line = self._correction(display)
            calls = ()
            pending = []                                # a corrected row printed none of its figures
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
        _cls = (self.classes[-1] or ("",))[0]
        for s in pending:
            self._scalars.append(dict(s, cls=_cls))
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
    from; the pair is what makes the count a count of rows rather than of dates.

    **THE THIRD GROUP IS THE FAR BOARD, AND WITHOUT IT A SPILLOVER ROW IS SCORED BY THE WRONG
    SENTENCE** (S7b, threat P-5). A spillover or recurrence nomination is ABOUT SOMEWHERE ELSE -- "this
    same reading is declared on thirty-four other boards, and the nearest of them is ICE robusta
    coffee" -- so the two groups above are satisfied by any sentence naming the NEAR board's driver on
    its own date, which is a sentence about the row the reader was already reading. The numerator would
    rise on answers drawn before the rows existed, and a numerator that rises without a fresh draw
    measures the instrument. ``far_words`` is minted by the producer that knows what the row is about
    and is ABSENT on every one of HEAD's five kinds, so their token tuples are unchanged."""
    dates = _date_group(w.get("dates") or "")
    who = ()
    row = w.get("row") or ()
    if isinstance(row, (tuple, list)) and len(row) == 2 and row[1]:
        who = _name_words(humanise(row[1]))
    far = tuple(str(x) for x in (w.get("far_words") or ()) if str(x).strip())
    groups = [g for g in (dates, who, far) if g]
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
                 caps: Optional[dict] = None, chain_receipts=None,
                 evidence_ordinals: Optional[dict] = None) -> Block:
    """THE WHOLE BLOCK. Deterministic, ASCII, every figure bound to its own call, every cut NAMED.

    ``loud_only`` renders the STATE rows of the loud set (the ``loud_k`` knob is the cut) while every
    OTHER row still reaches the reader: an unmeasured or unread row joins a GROUPED SB-X absence at the
    foot, which is the design's "an unmeasured driver is a ROW that says so", not a filter.

    THE ABSENCES ARE GROUPED BY REASON WORD and every name is listed inside the group. One line per
    unmeasured row was the first cut and it MEASURED 94 SB-X lines on a 47-row board -- more absence
    than board. Sec 0.3's own scenario-1 SB-X list is five lines, and grouping is how thirty-five named
    rows fit in five: the NAMES are never cut (the fan's law, applied here), only the sentences are
    shared.

    ``chain_receipts`` IS THE CHAIN LEG'S OWN DOCUMENT POOL AND IT IS **NOT** ``receipts_by_row``
    (S8, DESIGN B.4). The two feed different sections under different caps: ``receipts_by_row`` drives
    the per-row SB-R enumeration below, capped by ``render_receipts`` (0 / 3 / 5 -- ZERO on the free
    tier, i.e. it would render nothing there), and it stays the DECLARED RESIDUAL the seam names. This
    one is read ONLY at a rendered chain's receipt hop, under ``BoardKnobs.chain_receipts`` (1 / 2 / 3
    per turn), which is what "for CHAINS ONLY, never the per-row cap" means in an argument. Wiring one
    argument to both would have turned on a section the chain flag never asked for and moved a
    board-on / chain-off turn's bytes, which is the one property arm A needs."""
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
    # THE ONE FOLD MAP, built ONCE and read by BOTH the SB-JOIN loop and the quorum row
    # (:func:`series_by_driver` -- review round 2, majors 4 and 5).
    _series_by_driver = series_by_driver(bd)

    # -- THE LEAD: THE THREE LARGEST MOVES, ONE LINE EACH, FIRST IN THE BLOCK -------------------------
    # ROUND-2 DOCKET item 12. `coverage.missed.loud` named the loudest rows the writer never used on
    # three of five served turns (max: N30/N45/N48; corn_wheat: the 100th-percentile managed-money
    # print), and the reason is structural rather than a writer failure: the state rows ARE in rank
    # order, but each is followed by its own edge line and its own projection line, so the top three
    # reach the reader as nine interleaved lines with no mark saying which three lead. This row says it
    # in words, one line per row, before anything else -- and it is LETTERS ONLY and mints NO handle,
    # because the figures are on those rows' own state lines a few lines below and a second address for
    # one magnitude is exactly what sec 6.3 forbids. `board_coverage` grades the same three under
    # `missed.loud_top3`, so an omission is counted where the mandate can name it.
    # AND IT LEADS WITH THREE READINGS, NOT THREE ROWS. Loudness ranks the UNSIGNED state, so both
    # members of a phase pair land loud on ONE reading and an unfolded lead would spend two of its three
    # lines on one ONI print -- the very double count the SB-JOIN line below corrects, and the one
    # `board_coverage`'s own denominator folds. The group's name is chosen by the SAME rule the JOIN and
    # the quorum use (`_lead_name`), so no two lines on this page can name one reading differently.
    _lead_groups: dict = {}
    _lead_order: list = []
    for _r in rendered:
        _st = _r.state
        if _st is None or status_word(_st.status) != "ok":
            continue
        try:
            _gk = (_r.contract, _st.key.label())
        except Exception:                               # noqa: BLE001 -- an unlabelled key stands alone
            _gk = (_r.contract, _r.driver_id)
        if _gk not in _lead_groups:
            _lead_groups[_gk] = []
            _lead_order.append(_gk)
        _lead_groups[_gk].append(_r)
    _lead = [_lead_name(_lead_groups[g]) for g in _lead_order[:LEAD_ROWS]]
    for _i, _r in enumerate(_lead):
        b.add(sb_lead(_i + 1, len(_lead), _r), label=f"lead {_r.driver_id}",
              display=f"the lead line for {row_words(_r.contract, _r.driver_id)}")

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
    # THE WINDOW PEAK EACH RENDERED FULL CHAIN'S HOP PRINTS, minted on that hop's OWN SB-1 row (09-23,
    # CONTRACT.md C2). A row mints it only where it is a hop of a chain this page renders IN FULL, the walk
    # carries a peak, and the peak's printed ordinal differs from the current one -- exactly the hops
    # whose chain line says "peaked at ... now ..." (`chain_state_words`' own in-transit test). Empty on a
    # board-on / chain-off turn (`bd.chains` is not built), so that turn's bytes do not move.
    _peak_hops: dict = {}
    for _c in (getattr(bd, "chains", None) or ()):
        if not (getattr(_c, "rendered", False) and getattr(_c, "full", False)):
            continue
        for _h in (getattr(_c, "hops", None) or ()):
            _pw = percentile_words(getattr(_h, "percentile", None))
            _kw = percentile_words(getattr(_h, "tail_peak_percentile", None))
            if (getattr(_h, "measured", False) and _kw and _pw and _kw != _pw
                    and month_words(str(getattr(_h, "tail_peak_date", "") or ""))):
                _peak_hops.setdefault(_h.key, _h)
    for row in rendered:
        st = row.state
        if st is None or status_word(st.status) != "ok":
            continue
        h = b.next_handle
        line, calls = sb_state(h, row, asof=bd.asof, age_clause=ages.get(row.key, ""), block=b,
                               peak_hop=_peak_hops.get(row.key))
        if line:
            _got = b.add(line, calls, label=f"{row.contract}/{row.driver_id}",
                         display=f"the state row for {row_words(row.contract, row.driver_id)}",
                         # THE RANK IS THE LOUD CUT'S OWN POSITION (S7 item 1), taken from `rendered`,
                         # which is `bd.order`-sorted -- never from the [N] index, which is call order and
                         # carries no rank at all (the utilisation census's own finding).
                         role="state", rank=len(handles_by_row))
            handles_by_row[row.key] = h
            # THE ROW'S WHOLE HANDLE SET (C2), read off the calls it committed by their own `stat` --
            # so a hop line can cite each figure at its own address. A row the fence corrected
            # committed no calls and gets no entry, exactly as its handle points nowhere.
            if _got == line:
                _rh = {"level": None, "sigma": None, "percentile": None, "peak": None, "current": None}
                _k = {"level": "level", "sigma": "sigma", "percentile": "percentile",
                      "window_peak_percentile": "peak", "current_level": "current"}
                for _o, _call in enumerate(calls):
                    _stat = str(((_call.get("rows") or [{}])[0] or {}).get("stat") or "")
                    if _stat in _k:
                        _rh[_k[_stat]] = h + _o
                b.row_handles[row.key] = _rh
        if not int(cap.get("edge") or 0) or edge_n < int(cap["edge"]):
            b.add(sb_edge(row, block=b), label=f"edge {row.driver_id}",
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
            # THE ONE LAG PRODUCER (09-23, CONTRACT.md C8): the window OPENS from the anchor the row
            # names (the run's start or the reading's date) and CLOSES the maximum lag after the
            # NEWEST print, so a reading still in its run is never told its window "closed" while it is
            # still being printed (corn_wheat F4, cotton FA-4). `walk.effect_window` is lane W's; a tree
            # without it keeps HEAD's `projection_window`.
            w, _closes_from = _effect_window_for(row, st, anchor_date)
            b.add(sb_projection(board=board_label(row.contract),
                                anchor_words=_anchor_words(st, anchor_date), window=w,
                                closes_from=_closes_from,
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
        b.add(sb_absence("the effect windows of the readings past this tier's projection cut ("
                         + name_list(_named_rows(proj_cut, rank),
                                     int(cap.get("absence_names") or 0)) + ")", "render_cap"),
              label="projection render cap")
    if edge_cut:
        b.add(sb_absence("the declared links of the readings past this tier's link cut ("
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
        # THE PHASE IN FORCE (lane D, the 2026-09-16 smoke). The join said "one series, two names" and
        # never said WHICH PHASE the reading is, so a cool ONI number carried a warm-phase story. The
        # verdict is computed off the row's OWN level against the convention's own first band, and the
        # two members are matched to it by the DECLARED driver id, never by position.
        # THE PHASE IS READ THROUGH THE ONE PRODUCER (`phase_for_state`), so the verdict this line
        # states and the exclusion the quorum applies are the SAME verdict -- and on an offset row it
        # is read off the NEWEST KNOWABLE level, never off the shifted one (review round 2, MAJOR 10).
        _st0 = _rows[0].state
        _pf = phase_for_state(_st0)
        _ph: dict = {}
        # THE DECLARED-PAIR BRANCH REQUIRES THE GROUP TO **BE** THE DECLARED PAIR (review round 2,
        # MAJOR 1). A third name folded onto the same series key is not a phase of anything, and the
        # phase sentence is written for exactly two; a group of three falls to the undeclared branch,
        # which names the contradiction and counts its own members.
        if _pf and len(_rows) == 2 and {r.driver_id for r in _rows} == {_pf["driver"],
                                                                       _pf["other_driver"]}:
            _live = next((r for r in _rows if r.driver_id == _pf["driver"]), None)
            _oth = next((r for r in _rows if r.driver_id == _pf["other_driver"]), None)
            if _live is not None:
                _ph = {"words": _pf["words"], "other_words": _pf["other_words"],
                       "in_force": _pf["in_force"], "live_name": humanise(_live.driver_id),
                       "live_sign": sign_words(_live.sign),
                       "other_name": humanise(_oth.driver_id) if _oth is not None else "",
                       "other_sign": sign_words(_oth.sign) if _oth is not None else "",
                       "current": _pf.get("current"), "current_date": _pf.get("current_date"),
                       "offset_periods": _pf.get("offset_periods"), "cadence": _pf.get("cadence")}
        # THE ALIAS FOLD, for the non-opposed join: the name a reader should use is the one the graph
        # declares at the HIGHEST confidence (ties break on the reader label, so the choice is
        # deterministic and re-derivable from the block itself).
        # AND WHERE THE CONFIDENCES TIE, THE TIE IS THE FACT (review round 2, MAJOR 3): the alphabetical
        # winner of a three-way `medium` tie is not a reading a page may instruct a writer to take.
        # AND IT IS CHOSEN BY THE ONE PRODUCER THE QUORUM READS (review round 3, NEW-4). This loop's own
        # `min` over `_rows` and `_series_fold`'s `min` over the pattern's MATCHED SUBSET were two
        # choosers over two populations, and where the group's best member was one the pattern did not
        # match they named one reading two ways on one page. `group_keep` is that rule, written once and
        # read from the SAME map -- so the claim in this file that the two lines cannot disagree is now a
        # construction and not an observation.
        _ranks = sorted(CONFIDENCE_RANK.get(str(r.confidence or ""), 3) for r in _rows)
        _tied = len(_ranks) > 1 and _ranks[0] == _ranks[1]
        _keep_id = group_keep(_series_by_driver, _k) or min(
            (r.driver_id for r in _rows),
            key=lambda d: (CONFIDENCE_RANK.get(
                str(next(r.confidence for r in _rows if r.driver_id == d) or ""), 3), humanise(d)))
        _keep = humanise(_keep_id)
        _alias = tuple(n for n in _names if n != _keep)
        b.add(sb_phase_pair(_names, board_label(_c), opposed=len(_signs) > 1, phase=_ph,
                            keep=_keep, alias=_alias, keep_tied=_tied),
              label=f"phase pair {_c}",
              display=f"the phase-pair reading on {board_label(_c)}")
        # THE COVERAGE INSTRUMENT MUST COUNT WHAT THE READER WAS TOLD (S7 fix pass). The line above says
        # these rows are ONE reading under two names, so they are ONE denominator entry -- see
        # `Block.join_rows` for the two measured artefacts that came of counting them as two.
        b.join_rows([handles_by_row[r.key] for r in _rows if r.key in handles_by_row], f"{_c}|{_k}")

    # -- EVENTS ---------------------------------------------------------------------------------------
    #: Every ``[E]`` this section minted, keyed by the ROW and the PROPOSITION it carries, so the chain
    #: section below can CITE a document this page already addressed instead of minting a second handle
    #: for it (S8). Empty on every board whose chain leg did not run, and read by nothing else.
    _ev_e: dict = {}
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
            # ONE DOCUMENT, ONE ADDRESS (sec 6.3's law, read on the [E] surface). The chain section
            # below looks for its receipt at its own hop and would otherwise mint a SECOND `[E]` for a
            # document this section already put on the page under its own handle -- one document, two
            # citations, and a reader with no way to know they are one. The key is the ROW plus the
            # PROPOSITION's own identity, so the fold is the same one the frequency rule uses.
            _ev_e[(row.contract, row.driver_id, prop_identity(rc.get("text")))] = e

    # -- THE COMPOSED CHAIN (S8), OR -- WHERE THE CHAIN LEG DID NOT RUN -- TODAY'S TOPOLOGY LINES -----
    # **THE CHAIN BLOCK REPLACES SB-P's ROLE AND SB-P STAYS CALLABLE** (DESIGN A.8 item 4, and the task
    # brief in terms). `walk._stage2` builds `bd.chains` only when the caller threaded
    # `state_chain=True`, so a board-on / chain-off turn takes the `else` arm and renders byte for byte
    # what the 2026-09-16 smoke rendered -- which is the property arm A is built on. The UPSTREAM rows
    # and the chain rows are never both on one page: they are two spellings of one section, and
    # printing both would tell the reader the same topology twice at twice the bytes.
    #
    # THE CHAINS ARE ALREADY CUT WHEN THEY ARRIVE. `walk.chain_render_set` stamped `rendered` / `full`
    # / `decline` on the whole pool -- top K by rank, the diversity fold on the SERIES key, the print
    # line deciding FULL versus ONE LINE and never zero, and the sign-diversity rule. Nothing here
    # selects: this loop renders what the selection chose and counts what it did not, which is the same
    # division of labour every other capped section on this page keeps.
    # **AND THE PAGE'S ORDINAL IS THE RANK'S, NOT THE POOL'S** (round-4 MINOR 2). `Board.chains`
    # carries the POOL in COMPOSITION order while `Board.trace()["chains"]` publishes RANK order
    # (`walk.chain_trace_set` sorts on `Chain.rank`), so "CHAIN first of three" named the chain the
    # trace listed SECOND -- MEASURED on the live fixture: page tail terms [23.9, 21.9] against trace
    # [21.9, 23.9] on deep and [23.9, 21.9, 24.8] against [21.9, 23.9, 24.8] on max. A reader takes
    # "first of three" for a rank; the judge and the arm report read the trace; and the held-seat label
    # sits on one of those rows, which is what made the split legible. ONE ORDER, and it is the
    # selection's own (`walk.chain_render_set` returns `picked` in exactly this order too).
    _chains = sorted((c for c in (getattr(bd, "chains", None) or ()) if getattr(c, "rendered", False)),
                     key=lambda c: c.rank)
    if _chains:
        _n = len(_chains)
        # THE CHAIN RECEIPT CAP IS THE CHAIN'S OWN AND IS SPENT ACROSS THE TURN, one document per
        # rendered chain at the hop the action acts on (DESIGN B.4). It is NOT `cap["receipts"]`, which
        # bounds the per-row SB-R enumeration and is 0 on the free tier.
        _rcap = max(0, int(getattr(getattr(bd, "knobs", None), "chain_receipts", 0) or 0))
        _rspent = 0
        for _i, _c in enumerate(_chains, start=1):
            _why = chain_why_words(_c)
            _lbl = f"chain {_c.contract} {'/'.join(_c.hop_ids)}"
            _disp = f"the chain into {board_label(_c.terminal or _c.contract)}"
            # THE HEAD'S TOKENS NAME THE TOP HOP BY ITS SERIES (09-23, C9): the reader names the page
            # prints, never the driver id -- `chain_referenced` itself is `chain_referenced_in`.
            _tok = (tuple(chain_hop_reader_names(_c.hops[0])) if _c.hops else ("chain",),
                    _market_words(_c.terminal or _c.contract))
            if not _c.full:
                # BELOW THE PRINT LINE AND STILL ON THE PAGE -- the orchestrator's ruling of
                # 2026-09-17. One line, carrying its own selection clause, so the reader is told what
                # it was carried on rather than shown nothing at all.
                b.add(sb_chain_one_line(_c, i=_i, n=_n, why=_why), label=_lbl, display=_disp,
                      role="chain", rank=_i, tokens=_tok)
                continue
            b.add(sb_chain_head(_c, i=_i, n=_n, why=_why), label=_lbl, display=_disp,
                  role="chain", rank=_i, tokens=_tok)
            # THE ARITHMETIC, ON ITS OWN LINE (round-2 item R-3): the terms, the points each earned in
            # words, and the DATA SCOPE the chain was scored on -- so a low score reads as scarce data
            # and never as a bad chain (orchestrator note 6).
            b.add(chain_arithmetic_words(_c), label=f"{_lbl} why", display=_disp,
                  role="chain_why", rank=_i)
            # ...and WHERE THE CROWD IS, cited at the board's own positioning row when this page
            # carries its address (orchestrator note 1). Silent where the walk declares nothing.
            # E11 AT THIS SEAM TOO: the positioning row's address is the PAIR, never the driver id --
            # `cot_mm_positioning` is a row of every futures board this turn carries. A `key` that
            # arrives as a list (a payload round-trip) is keyed as the tuple `handles_by_row` uses.
            _pk = (getattr(_c, "positioning", None) or {}).get("key")
            _pk = tuple(_pk) if isinstance(_pk, (list, tuple)) else None
            b.add(sb_chain_positioning(_c, handle=handles_by_row.get(_pk) if _pk else None),
                  label=f"{_lbl} positioning", display=_disp, role="chain_positioning", rank=_i)
            _th = handles_by_row.get(_c.terminal_key) if _c.terminal_key else None
            for _j, _hop in enumerate(_c.hops):
                _hrow = bd.row(_hop.contract, _hop.driver_id) if hasattr(bd, "row") else None
                b.add(sb_chain_hop(_c, _j, handle=handles_by_row.get(_hop.key), terminal_handle=_th,
                                   handles=b.row_handles.get(_hop.key), block=b,
                                   phase_words=_hop_phase_words(_hop, _hrow),
                                   offset_words=_hop_offset_words(_hrow, b.row_handles.get(_hop.key))),
                      label=f"chain hop {_hop.driver_id}",
                      display=f"a hop of the chain into {board_label(_c.terminal or _c.contract)}",
                      role="chain_hop", rank=_i,
                      tokens=(tuple(chain_hop_reader_names(_hop)),))
                if b.rows_meta and b.rows_meta[-1].get("role") == "chain_hop":
                    # the hop's OWN addresses (C2 row handles) -- telemetry for `chain_referenced_in`,
                    # never a byte of the block
                    b.rows_meta[-1]["hop_handles"] = tuple(
                        int(v) for v in (b.row_handles.get(_hop.key) or {}).values() if isinstance(v, int) and v)
            b.add(sb_chain_record(_c, block=b), label=f"{_lbl} record",
                  display=f"the record behind the chain into "
                          f"{board_label(_c.terminal or _c.contract)}",
                  role="chain_record", rank=_i)
            # THE OUTCOME ROW CARRIES ITS ROLE LIKE EVERY OTHER CHAIN ROW (review MINOR 4). Without it
            # `rows_meta` said nothing about these two rows -- `Block.add` writes no `label` into the
            # manifest -- so every "every chain line" pin and every census MISSED them, and their bytes
            # were counted as NON-CHAIN: 85 characters per rendered chain, which is the whole of the
            # max cell's 83-character gate miss and then some (MEASURED: max non-chain 26,083 -> 25,825
            # on the receipt cell, i.e. PASS by 175 where the round-2 census read FAIL by 83).
            _oline, _ocalls = sb_chain_outcome(b.next_handle, _c, asof=bd.asof, block=b)
            if _oline:
                b.add(_oline, _ocalls, label=f"{_lbl} outcome",
                      display=f"the price record behind the chain into "
                              f"{board_label(_c.terminal or _c.contract)}",
                      role="chain_outcome", rank=_i)
            else:
                b.add(sb_chain_outcome_absent(_c), label=f"{_lbl} outcome absence",
                      display=f"the price record behind the chain into "
                              f"{board_label(_c.terminal or _c.contract)}",
                      role="chain_outcome", rank=_i)
            # THE RECEIPT, AND ITS SENTENCE IS NOT OPTIONAL. Where a dated action was found the words
            # place it in or out of the window this chain declares (threat E4); where none was, the
            # words name THE DRAW and never the corpus (threat E6). Either way the reader meets a row.
            _rp = chain_receipt(_c, chain_receipts, asof=bd.asof)
            _rh = _rp["hop"] if _rp["hop"] is not None else _c.hops[_c.receipt_index]
            # ONE DOCUMENT, ONE ADDRESS. Where the EVENTS section above already minted an ``[E]`` for
            # this very proposition on this very row, the chain CITES that handle and mints nothing;
            # only a document the page has not addressed spends a seat of the chain's own cap.
            _seen = _ev_e.get((_rh.contract, _rh.driver_id,
                               prop_identity((_rp["prop"] or {}).get("text"))))
            _cite_e = chain_document_cite(_rp, _seen, evidence_ordinals)
            b.add(sb_chain_document(_rp, _rh, cite_e=_cite_e),
                  label=f"{_lbl} document", display=_disp, role="chain_document", rank=_i)
            if _rp["kind"] != "none" and _rp["prop"] and not _seen and _rspent < _rcap:
                b.add(sb_receipt(b.take_e(), int(_rp["prop"].get("tier") or 3), _rp["prop"],
                                 driver_id=_rh.driver_id),
                      label=f"{_lbl} receipt",
                      display=f"the dated document on {row_words(_rh.contract, _rh.driver_id)}",
                      role="chain_receipt", rank=_i)
                _rspent += 1
        # WHERE THE CHAINS DISAGREE, and the honest closure for everything the page did not carry.
        b.add(sb_chain_sides(_chains), label="chain sides",
              display="the direction the chains on this page settle", role="chain_sides")
        b.add(sb_chain_count(getattr(bd, "chain_counts", None) or {}, k=_n,
                             anchor_label=anchor_label
                             or ", ".join(board_label(s) for s in bd.anchor_slugs),
                             # THE SEATS ARE COUNTED OFF THE CHAINS THIS PAGE ACTUALLY RENDERED, not
                             # off a counter (owner ruling 2026-09-22). The count is "how many of the
                             # rows above are here for a reason other than rank", so its population is
                             # this loop's own `_chains` -- one producer, and it cannot drift from the
                             # labels the reader just read on those heads.
                             # THE AGED-OUT DATED ACTIONS ARE NO LONGER SUMMED HERE (round-5 blocker
                             # 3): `chain_counts["receipts_aged_out"]` is the POOL's own DISTINCT
                             # document count and the line reads it off the dict it already has, so
                             # the noun and the number have one owner. The round-4 re-sum over
                             # `bd.chains` printed 264 on an estate holding ONE dated action.
                             slots=tuple(str(getattr(_c, "slot", "") or "") for _c in _chains),
                             named=tuple(board_label(s_) for s_ in bd.anchor_slugs)),
              label="chain count", display="the chains this page did not carry", role="chain_count")
    else:
        # -- PATHS (capped by the walk's own `path_render_k`, which stamped `rendered` per path) ------
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
            b.add(sb_edge(seed, far=f, block=b), label=f"far {f['contract']}/{f['driver_id']}",
                  display=f"the spillover link for {row_words(f['contract'], f['driver_id'])}",
                  role=("far" if _cross else "far_same_board"),
                  tokens=(_market_words(f["contract"]),))
            spill += 1
            if _cross:
                far_rendered.append(str(f["contract"]))
        cut_boards.extend(f["contract"] for f in far_named[far_per_entry:])
    if cut_boards:
        b.add(sb_absence("the further markets past this tier's spillover cut ("
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
    # THE QUORUM COUNTS DISTINCT SERIES (lane D, the 2026-09-16 smoke): the served deep answer said
    # board crush and the crush margin were one reading and then counted BOTH into a two-driver quorum.
    # The map is `series_by_driver(bd)`, built ONCE at the top of this function and read by the SB-JOIN
    # loop as well, so the two folds cannot disagree (review round 2, majors 4 and 5) and the WATCH
    # producer takes the same map for the same pattern's own sentence.
    conv, conv_cut = 0, []
    for c in bd.convergence:
        if conv >= int(cap["convergence"]):
            conv_cut.append(c)
            continue
        b.add(sb_convergence(c, series_of=_series_by_driver), label=f"pattern {c['name']}",
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
    # THE TOP RENDERED CHAIN'S OWN HOP IDS, for the stanza mark's attribution alone (round-5 blocker
    # 6). It is `_chains`, which this function already sorted on `Chain.rank` -- the same order
    # `seam._first_dim` reads -- so the chain the mark says the stanza is read for and the chain the
    # page named FIRST can never be two different rows. Empty on a board-on / chain-off turn, which is
    # the flag-off answer, and the mark is then absent exactly as it is today.
    _chain_hops = tuple((_chains[0].hops or ()) if _chains else ())
    _chain_dims = tuple(str(getattr(h, "driver_id", "") or "") for h in _chain_hops)
    # {the analog leg's dimension id -> that hop's OWN driver id}, for the mark's TRANSLATED arm alone.
    # `seam.dim_for_hop` is the ONE owner of the hop-to-dimension rule (`seam._analog_dims`' own
    # docstring asks for exactly this folding, and `test_state_seam.py` pins the two spellings to
    # agree), so the page and the selection can never read the pairing two ways. It is a pure lookup
    # over rows this board already holds -- no read, no cap, no second selection -- and a failure to
    # import or to answer leaves the map EMPTY, which is round 5's silence exactly.
    _chain_dim_names = _chain_dim_name_map(bd, _chain_hops)
    _chain_hop_names = {str(getattr(h, "driver_id", "") or ""): chain_hop_name(h) for h in _chain_hops}
    for a in shown_analogs:
        b.add(sb_analog_header(a, chain_dims=_chain_dims, chain_dim_names=_chain_dim_names,
                               chain_hop_names=_chain_hop_names),
              label=f"analog {a['driver_id']}",
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
                                            scale=_outcome_scale(o, _scales), block=b)
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
        # THE FIFTH SILENT CUT, AND THE FIRST WHOSE NUMBER WAS PRINTED AS A FACT (round-2 blocker 3).
        # `analogs._receipts_after` used to stop walking at the tier's receipt cap and the header
        # printed `len()` of what it got as "N dated documents inside the window that followed it", so
        # the figure was CONSTANT AT THE CAP whatever the corpus held: measured through the real seam
        # with twelve documents inside the forward window, deep printed three against eleven and max
        # printed five against eight. The count is the WINDOW's now, and the cap -- which still bounds
        # the rows the row CARRIES, for the sitting that mints an `[E]` for them -- says what it cut,
        # exactly as the backward window has said since S6. The names are the STANZA's and never the
        # documents': a document title is retrieved text and this class is letters-only.
        _n_aft = a.get("n_receipts_after")
        # ROUND-2 REVIEW MAJOR 1: NOTHING ON THIS PAGE RENDERS THE FORWARD WINDOW'S ROWS (the only
        # sb_receipt rows are the BACKWARD window's, and `receipts_after` has no reader but the count
        # and the mint), so the honest row withholds the WHOLE count the header just printed -- never
        # "count minus carried" over rows a reader was never shown. The sitting that mints an [E] for
        # the forward rows retires this row by rendering them.
        if _n_aft is not None and int(_n_aft) > 0:
            _more = int(_n_aft)
            # THE COUNT IS THE SUBSET'S AND THE NOUN IS THE COUNTED SET'S. "N more inside the window"
            # would read as N BEYOND the eleven the clause above just printed; "N of the documents
            # counted inside the window" can only be read as part of that same eleven, which is what
            # a cut row is for.
            # THE WHOLE COUNT IS WITHHELD, SO THE NOUN AND THE VERB AGREE WITH IT (one document IS not
            # shown; N documents ARE not shown) -- the singular bar in the render deck.
            b.add(sb_absence(f"the {words_for_int(_more)} "
                             f"{'document' if _more == 1 else 'documents'} counted inside the window "
                             f"that followed this like state {'is' if _more == 1 else 'are'} not shown "
                             f"on this page ({humanise(a['driver_id'])} on {board_label(a['contract'])})",
                             "render_cap"),
                  label="analog receipt after render cap")
        if not _arc:
            # THE CO-LOUD STANZA SPANS BOARDS, so its absence may not name ONE of them: the ordinary
            # line's "on {board}" would attribute the whole stanza to its leading anchor, and the rows
            # above it are several boards' own records.
            where = ("across the markets that carry it" if a.get("co_loud")
                     else f"on {board_label(a['contract'])}")
            stands = ("the markets' own records alone" if a.get("co_loud") else "the series alone")
            b.add(f"LIKE STATE {humanise(a['driver_id'])} {where}: the corpus "
                  f"holds no dated document explaining this state (the window before it); the "
                  f"figures above stand on {stands}",
                  label="analog receipt absence")
    if len(fired) > len(shown_analogs):
        b.add(sb_absence("the like states past this tier's stanza cut ("
                         + ", ".join(_named_rows(
                             ((a["contract"], a["driver_id"]) for a in fired[len(shown_analogs):]),
                             rank))
                         + ")", "render_cap"),
              label="analog render cap")
    _declines = sorted({str(a["declined"]) for a in analogs if a.get("declined")})
    for word in _declines:
        b.add(sb_absence("a like state on this market", word), label="analog absence")
        # THE FINER REASON, UNDER THE SAME WORD (this lane's D1). `select_analogs` records WHY it found
        # nothing on `detail` -- `no_candidates` (the record offered none), `window_open` (every
        # candidate's outcome window is still open) or `unobservable` (candidates survived both
        # point-in-time filters and no declared dimension carried a readable sigma at any of their
        # dates) -- and nothing read it. The handoff asked for a new decline word (`pre_coverage`);
        # RENDERING that word REFUTED it: `ABSENCE_WHY` is keyed by WORD ALONE and clause 9 of
        # `state/lint.py` requires exactly one sentence per word in both directions, so an analog
        # decline on `pre_coverage` prints the TAPE's sentence verbatim -- "the as-of sits before this
        # market's own price history begins" -- which is FALSE for `unobservable`: the as-of is today
        # and it is the CANDIDATE DATES that sit inside the record with nothing readable on them. So
        # the word does not move, `board.ANALOG_REASONS` and `ABSENCE_WHY` stay byte-identical, and the
        # finer reason rides as ONE extra sentence in the same class.
        for line in sorted({sb_analog_decline_detail(a) for a in analogs
                            if str(a.get("declined") or "") == word and a.get("detail")}):
            if line:
                b.add(line, label="analog absence detail")
    # THE HONEST ABSENCE THE PM COULD NOT FIND (lane D, the 2026-09-16 smoke). ``BoardAnalogs`` was 0 on
    # all five served turns, and on the turns where the LEG declined before it built a single stanza --
    # ``not_reached``, or a decline recorded on the leg rather than per candidate -- the section printed
    # NOTHING AT ALL: a reader met a silence where the block's own law is that an absence is a row. The
    # selection rule is untouched (that is S8's); what lands is the SENTENCE, in words a PM can read.
    if not fired and not _declines:
        _leg = (getattr(bd, "legs", None) or {}).get("analog") or {}
        if str(_leg.get("outcome") or "") != "fired":
            b.add(sb_analog_leg_absence(str(_leg.get("reason") or ""),
                                        not_reached=str(_leg.get("outcome")) == "not_reached"),
                  label="analog leg absence", display="the like-state absence on this page")

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
        b.add(sb_absence("the further documents on the readings past this tier's receipt cut ("
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
        # THE NON-OBVIOUS PRODUCER'S TWO NOTE ROWS (S7b). Both are SB-X, because both are the block
        # saying what it is NOT printing: the honest absence line when nothing cleared the admission
        # floor, and the dated-releases footnote that keeps the scheduled prints off the list without
        # losing their dates. Neither spends a ceiling slot and neither is a fired fact.
        # THEY ARE DRIVEN BY THE ROW DICT AND NOT BY A FLAG READ HERE: HEAD's five kinds carry no
        # `form` key, so this branch is unreachable on a HEAD board and the loop below is byte for byte
        # what it was.
        if w.get("form") == "absence":
            b.add(sb_absence(w.get("label") or "a forward item on this page",
                             w.get("reason") or "watch_floor_unmet"),
                  label=f"watch {w['kind']}", role="watch", tokens=())
            continue
        # A NOMINATION NAMES THE ROW IT RESTS ON, through the handle that row's own SB-1 line minted.
        # `handles_by_row` is the render's own map and is complete by here; a row whose state was not
        # rendered simply carries no citation, which is the honest form -- a nomination pointing at a
        # handle the block never printed would be a citation to nothing.
        if w.get("nonobvious") and not w.get("backing_handle"):
            _bh = handles_by_row.get(tuple(w.get("row") or ()))
            if _bh:
                w = {**w, "backing_handle": _bh}
        if w.get("call") is not None and w.get("row_obj") is not None:
            line, calls = sb_convention(b.next_handle, w["row_obj"], distance=w["distance"],
                                        band=w["band"], label=w["conv_label"],
                                        unit_words=w["unit_words"], direction=w["direction"],
                                        asof=bd.asof, band_words=w.get("band_words") or "",
                                        kind_words=w["kind_words"], row_label=w["label"],
                                        dates=w.get("dates") or "", block=b)
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
            # **THE CHAIN COUNT LINE REPLACES THIS ENUMERATION** (DESIGN A.8 item 1 / B.3). It is the
            # largest of the four cuts A.8 buys the chain rows their bytes from -- it NAMES 35 to 137
            # ancestors on the five smoke turns -- and the count line above says the same closure in
            # counts, with its reasons, on one line. Printing both would pay for the closure twice and
            # would tell the reader that the topology was cut when the chain block carried it.
            if _chains:
                continue
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
            b.add(sb_absence("the far states of the readings past this tier's cut"
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
        # THE REFUSALS THE RENDER COUNTED (09-23): ``role_withheld`` and ``chain_hop_unaddressed``.
        # Parallel telemetry beside the manifest -- no trace key and no byte of the block moves.
        bd.render_counters = dict(b.counters)
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


def name_list(names, cap: int = 0, noun: str = "readings") -> str:
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

    **THE DEFAULT NOUN IS ``readings`` AND NOT ``rows`` (lane D, 2026-09-17).** `row` is the block's
    word for a served observation and a PM's word for it is a reading, a series, a print or the record;
    the smoke's fact lens charged it seven times across five answers, the worst of them inside the
    mechanism section. The cut still says exactly what it cut.

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
    # ROUND-2 DOCKET item 12: THE THREE THE BLOCK LEADS WITH GET THEIR OWN NUMERATOR. `missed.loud`
    # names every uncited loud row and a reader cannot tell from it whether the writer skipped the
    # board's LOUDEST reading or its twenty-fourth. These are the same three `sb_lead` names, graded by
    # the same `_bucket` verdict, so "the top three are named or their omission is explained" is a
    # number the arm can read rather than a sentence in a mandate nobody scores.
    # The three READINGS, folded exactly as `_bucket` and `sb_lead` fold them (a phase twin is one
    # entry), so `loud_lead_rows` reads three on a board whose two loudest rows are one ONI print.
    _lead_entries: list = []
    for _i in _state:
        _ek = str(rows[_i].get("join") or "") or ("#%d" % _i)
        if _ek not in _lead_entries:
            _lead_entries.append(_ek)
    _lead_keys = set(_lead_entries[:LEAD_ROWS])
    _lead3 = {i for i in _state
              if (str(rows[i].get("join") or "") or ("#%d" % i)) in _lead_keys}
    l3_ref, _l3_cit, _l3_fig, l3_seen, l3_missed = _bucket(lambda i, m: i in _lead3)
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
        "loud_lead_rows": l3_seen, "loud_lead_referenced": l3_ref,
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
                   "spillover": tuple(sp_missed),
                   # The three the block LEADS with. EMPTY is the bar (docket item 12); a name here is
                   # an omission the mandate is told to explain.
                   "loud_top3": tuple(l3_missed)},
        # THE PAGE ITSELF, and not its sentences: the nomination read is a PER-BULLET read
        # (ruling (7)) and a bullet is a list item, which only the un-split text carries.
        **_nomination_coverage(rows, sents, _verdict, str(getattr(bd, "asof", "") or ""),
                               text=text),
        # THE CHAIN MOVEMENT'S OWN ELEVEN (S8, DESIGN B.6), under the same splat precedent. Every key
        # is ABSENT on a board whose chain leg did not run -- absent is never zero, the contract this
        # whole return keeps -- so a census can tell "the chain rendered nothing" from "the chain was
        # never armed", which are two different facts about a turn.
        **_chain_coverage(bd, rows, _bucket, sents, text=text),
    }


#: THE CHAIN REFERENCE WINDOW, in sentences: ONE, the same as every other class
#: (:data:`_TOKEN_WINDOW_SENTS`). 09-23 FIX ROUND (review RA M3): the first cut widened it to two AND
#: required the literal head noun "chain" or the end market's words in the window -- a keyword gate tuned
#: on the ten pages the drive then graded it on. Both are withdrawn: a chain is referenced where ONE
#: sentence names two distinct links of it, by their identity words, their reader names or their OWN
#: [N] addresses (the block prints every measured hop's address).
_CHAIN_WINDOW_SENTS = 1

#: A word the declared reading-words book spends on this many or more DIFFERENT series names identifies
#: no one series ("record", "price", "against", "anomaly", "temperature" -- MEASURED off the book itself,
#: so the set moves with the book and is never typed here).
_CHAIN_GENERIC_WORD_BOOK_COUNT = 3

_CHAIN_WORD_RX = re.compile(r"[a-z]+")

#: THE TWO LENGTH FLOORS BELOW (a word of >= 4 letters in :func:`chain_hop_identity_words`, a whole reader
#: name of >= 8 characters in :func:`chain_referenced_in`) ARE A TOKEN-GRAIN BOUND, NOT A CLASSIFIER (09-23 fix
#: round, the verifier's LEX-3, decided on a probe: fix_round_0923/final1/lex3_probe*.py/.out). They name no
#: word, no synonym and no subject; they bound the grain below which a word-bounded match in free prose stops
#: identifying one series ("a", "as", "in", "of", "on", "to", "for", "one", "all" -- the function words the
#: reading-words book puts inside series names -- and the name halves "El" / "La"). MEASURED: on the 38
#: rendered chains of the ten 09-23 pages and the eighteen fixture cells, lifting either floor or both moves
#: NO referenced verdict (17 of 20 page chains either way), while the floor-free rule admits those function
#: words as identity words -- a false-narration door. The one cheap derivation from the chains' own names
#: (words shared by >= _CHAIN_GENERIC_WORD_BOOK_COUNT driver names across the shipped graph) catches NONE of
#: those function words (they sit in the book's reading words, not in the driver names) and would strip 82
#: genuine identity words ("crush", "drought", "crude", ...). So the bound stays until a function-word fact
#: is served by the book itself; what it costs is recorded: the short identifiers "oni", "iod", "cot", "trq",
#: "msp", "rfs" never identify a hop on their own -- such a hop is matched by its longer name words where it
#: has them, and by its own [N] address where it has none.


@lru_cache(maxsize=1)
def _chain_generic_words() -> frozenset:
    """The words :data:`_CHAIN_GENERIC_WORD_BOOK_COUNT` or more declared series names share -- derived
    from ``state_conventions.reading_words``, the one book of series names."""
    import collections as _co
    cnt: _co.Counter = _co.Counter()
    for v in (_reading_word_table() or {}).values():
        for w in set(_CHAIN_WORD_RX.findall(ascii_text(str(v)).lower())):
            cnt[w] += 1
    return frozenset(w for w, n in cnt.items() if n >= _CHAIN_GENERIC_WORD_BOOK_COUNT)


def chain_hop_identity_words(ch) -> list:
    """PER HOP OF ONE CHAIN, the words that identify THAT hop and no other on the chain (R-12): every
    word of four letters or more in its :func:`chain_hop_reader_names`, minus the words another hop of
    the same chain also carries, minus the words of the chain's own market labels (a sentence about
    "soybeans" is not about any one link), minus the words the declared book shares across series
    (:func:`_chain_generic_words`). DERIVED from the chain's own names -- the writer's "crude", "crush",
    "drought", "Pacific" are the words the chain's own series names carry -- and never a synonym table."""
    hops = list(getattr(ch, "hops", None) or ())
    per = []
    for h in hops:
        ws = set()
        for n in chain_hop_reader_names(h):
            ws.update(w for w in _CHAIN_WORD_RX.findall(ascii_text(n).lower()) if len(w) >= 4)
        per.append(ws)
    market = set()
    for slug in (getattr(ch, "terminal", "") or "", getattr(ch, "contract", "") or ""):
        for lbl in _market_words(slug):
            market.update(_CHAIN_WORD_RX.findall(ascii_text(lbl).lower()))
    gen = _chain_generic_words()
    out = []
    for i, ws in enumerate(per):
        others = set().union(*(per[j] for j in range(len(per)) if j != i)) if len(per) > 1 else set()
        out.append(frozenset(ws - others - market - gen))
    return out


_CHAIN_ADDR_RX = re.compile(r"\[([^\]]*)\]")
_CHAIN_ADDR_N_RX = re.compile(r"N(\d+)")


def _sentence_addresses(sent: str) -> set:
    """Every [N] index the sentence cites, grouped members included ("[N12][N14]", "[N12, N14]")."""
    out: set = set()
    for m in _CHAIN_ADDR_RX.finditer(str(sent or "")):
        out.update(int(x) for x in _CHAIN_ADDR_N_RX.findall(m.group(1)))
    return out


def chain_referenced_in(ch, sents, hop_handles=None) -> bool:
    """IS THIS RENDERED CHAIN NARRATED IN ``sents``? -- ONE sentence (:data:`_CHAIN_WINDOW_SENTS`) names at
    least TWO distinct links of the chain (its one link, on a one-link chain), each by a full reader name
    (:func:`chain_hop_reader_names`, word-bounded, at least eight characters -- the minimum lane A's chain
    lint already uses), by one of its identity words (:func:`chain_hop_identity_words`), or by one of its
    OWN [N] addresses (``hop_handles``: per hop, the handles the block printed for that hop's row). That is
    the whole rule (THREAT_MODEL R-12), and it is STRUCTURAL: no head noun, no market word is required --
    the 09-23 cut's literal "chain" / end-market anchor was a keyword gate (review RA M3) and is gone.
    MEASURED on the ten 09-23 pages against the human read (fix_round_0923/fix/r12_fix.out): the tariff
    and cotton pages DO name two linked hops of a rendered chain in one sentence ("export pace ... feeds
    the stocks-to-use ratio"; "if El Nino emerges ... weaken the Indian monsoon and raise drought") and
    now read referenced -- the human read's "no" there rested on the chain not being told AS a chain,
    which only a keyword can see. Prose is folded to ASCII first, so "El Nino" with its tilde is one
    spelling. ONE PRODUCER: the coverage counter and lane A's chain backstop both call this."""
    hops = list(getattr(ch, "hops", None) or ())
    if not hops:
        return False
    names = [tuple(n for n in chain_hop_reader_names(h) if len(n) >= 8) for h in hops]
    idw = chain_hop_identity_words(ch)
    addrs = [set(int(x) for x in (hh or ()) if isinstance(x, int) and x > 0)
             for hh in list(hop_handles or ())] + [set() for _ in hops]
    need = min(2, len(hops))
    w = max(1, int(_CHAIN_WINDOW_SENTS))
    raw = [str(x) for x in (sents or ())]
    folded = [ascii_text(x) for x in raw]
    for i in range(len(folded)):
        low = " ".join(folded[max(0, i - w + 1):i + 1]).lower()
        cited = set()
        for x in raw[max(0, i - w + 1):i + 1]:
            cited |= _sentence_addresses(x)
        toks = set(_CHAIN_WORD_RX.findall(low))
        got = sum(1 for k in range(len(hops))
                  if (idw[k] & toks) or any(_token_hit(n.lower(), low) for n in names[k])
                  or (addrs[k] & cited))
        if got >= need:
            return True
    return False


def _chain_coverage(bd, rows, bucket, sents, *, text: str = "") -> dict:
    """WHAT THE WRITER DID WITH THE CHAINS -- DESIGN B.6's eleven counters. A COUNTER, NEVER A FENCE.

    TWO POPULATIONS AND THEY ARE NOT THE SAME NUMBER. The RENDERED half is read off the block's own
    coverage manifest through the same ``_bucket`` verdict every other class here takes, so a chain row
    and a watch row are graded by one rule; the STRUCTURAL half (how many hops agree with the direction
    declared for them, how many run against it, the record's own sample sizes, what sat below the
    selection line) is read off ``Board.chains`` and ``Board.chain_counts``, because those are facts
    about the SELECTION and not about the draft.

    ``chain_receipts_cited`` IS READ ON THE ``[E]`` SURFACE and nothing else. A chain's receipt row
    mints no ``[N]`` and carries no token group, so ``_bucket`` returns no verdict for it at all -- the
    honest read is whether the writer copied the handle the block minted for that document.

    ABSENT IS NEVER ZERO: a board whose chain leg did not run returns ``{}``, so none of these keys
    dilutes a population it was never part of."""
    chains = list(getattr(bd, "chains", None) or ())
    if not chains:
        return {}
    counts = dict(getattr(bd, "chain_counts", None) or {})
    rendered = [c for c in chains if getattr(c, "rendered", False)]
    ch_ref, _ch_cit, _ch_fig, ch_seen, ch_missed = bucket(lambda i, m: m.get("role") == "chain")
    # **A CHAIN IS REFERENCED WHEN THE PROSE NAMES TWO OF ITS LINKS AS A CHAIN** (09-23, CONTRACT.md C9
    # and threat R-12). The row-level token test above required the TERMINAL market's label in the SAME
    # sentence as the top hop, and the terminal is almost always a market the block itself calls "a
    # market this question did not name" -- so the counter read 0 / 0 / 0 / 0 / 1 on five pages that all
    # narrate their chains (CHAIN_ANALOG_READ sec 1). The rule is now :func:`chain_referenced_in`,
    # measured against that human read on the ten 09-23 pages; the denominator (``ch_seen``, the chain
    # rows the reader met) is unchanged, and so is ``missed_chains``' id shape.
    _chain_rows = [(i, m) for i, m in enumerate(rows) if m.get("role") == "chain"]
    if _chain_rows and rendered:
        _ranked = sorted(rendered, key=lambda c: getattr(c, "rank", 0))
        ch_ref, ch_missed = 0, []
        for _i, (_ri, _m) in enumerate(_chain_rows):
            _c = _ranked[_i] if _i < len(_ranked) else None
            # each hop's OWN printed addresses, in hop order (the manifest's `hop_handles`)
            _hh = [m.get("hop_handles") or () for m in rows
                   if m.get("role") == "chain_hop" and m.get("rank") == _i]
            if _c is not None and chain_referenced_in(_c, sents, hop_handles=_hh):
                ch_ref += 1
            else:
                ch_missed.append(_row_id(_ri, _m))
    hp_ref, _hp_cit, _hp_fig, hp_seen, _hp_missed = bucket(lambda i, m: m.get("role") == "chain_hop")
    low = str(text or "\n".join(sents or ())).lower()
    # THE DENOMINATOR IS "A CHAIN WHOSE DOCUMENT THE READER CAN CITE", not "a chain that minted a
    # handle". Where the EVENTS section already addressed the same proposition the chain reuses ITS
    # ``[E]`` (one document, one address), so counting only the rows this section minted would score a
    # correctly-folded document as no document at all.
    _e_rows = [m for m in rows if m.get("role") in ("chain_receipt", "chain_document")
               and re.search(r"\[E\d+\]", str(m.get("line") or ""))]
    _e_cited = 0
    for m in _e_rows:
        hs = re.findall(r"\[E(\d+)\]", str(m.get("line") or ""))
        if any(("[e%s]" % h) in low for h in hs):
            _e_cited += 1
    agree = sum(1 for c in rendered for v in c.agreements if str(v) == "aligned")
    odds = sum(1 for c in rendered for v in c.agreements if str(v) == "at_odds")
    return {
        "chain_rendered": ch_seen, "chain_referenced": ch_ref,
        "chain_hops_rendered": hp_seen, "chain_hops_referenced": hp_ref,
        "chain_hops_agreeing": agree, "chain_hops_at_odds": odds,
        "chain_receipts_rendered": len(_e_rows), "chain_receipts_cited": _e_cited,
        "chain_events_open": sum(1 for c in rendered if str(c.receipt_kind) == "open"),
        "chain_history_n": [int((c.history or {}).get("n_firings") or 0) for c in rendered],
        "chain_below_print_line": int(counts.get("below_print_line") or 0),
        # **AND THE ONE-LINE COUNT GAINS ITS READER** (round-5 blocker 10). Of the declared count keys
        # the render read nowhere, this was the one carrying a fact about the PAGE rather than about
        # the pool: how many of the rows a reader just met were rendered short. It is the denominator
        # for :data:`CHAIN_ONE_LINE_WORDS`'s seated sentence -- a census that finds the sentence on the
        # page and this counter at zero has found the two producers disagreeing, which is exactly the
        # contradiction round 5 closed -- and it rides the same coverage dict as its sibling above.
        "chain_rendered_one_line": int(counts.get("rendered_one_line") or 0),
        "missed_chains": tuple(ch_missed),
    }


#: THE NOMINATION INSTRUMENT'S TWO ERROR FLOORS -- the RETIRED per-sentence read's, and the SHIPPED
#: per-bullet read's (S7b round 4, orchestrator ruling (7): "yes, fix it").
#:
#: BOTH ARE MEASURED ON THE SAME NINE ARMED CELLS (three acceptance fixtures x three tiers) AND BY THE
#: SAME METHOD: score each block AGAINST ITS OWN RENDERED TEXT -- the writer that added nothing,
#: dropped nothing and reproduced everything. A perfect instrument reads ``watch_writer_added`` 0 and
#: ``watch_candidates - watch_candidates_used`` 0 on that input.
#:
#: THE ``bullet_*`` KEYS ARE THE SHIPPED RULE'S FLOOR AND THEY ARE EXACTLY ZERO. That is not a claim of
#: a perfect counter; it is what the rule is FOR. A nomination is used when its own ``[N]`` or its own
#: series key reaches a shipped watch bullet, and a block's nomination line carries its own ``[N]``, so
#: scoring the block against itself can only read all-used and none-added. The floor that MATTERS for
#: this read is therefore not this constant but the two directions of error named in
#: :func:`_nomination_coverage`'s own docstring, which no self-scoring input can exercise.
#:
#: THE FOUR ORIGINAL KEYS ARE KEPT, UNCHANGED, AND THEY ARE NOT THE SHIPPED READ'S. They are the floor
#: of the PER-SENTENCE counter this landing retired -- three to seven "added" and nought to two
#: "unused" at zero writer -- and they are kept because the S7b round-2 and round-3 traces carry
#: numbers produced by THAT counter, and a banked number whose floor has been deleted is a number
#: nobody can read. Correct or compute, never delete.
#:
#: RE-MEASURE WHEN THE SENTENCES MOVE. Both are properties of the rendered block and of the tests
#: above; the decks assert the shape and the report carries the number.
NOMINATION_ZERO_WRITER_BASELINE: dict = {
    "added_at_zero_writer_min": 3, "added_at_zero_writer_max": 7,
    "used_short_at_zero_writer_min": 0, "used_short_at_zero_writer_max": 2,
    "cells": 9,
    "bullet_added_at_zero_writer": 0, "bullet_used_short_at_zero_writer": 0,
    "bullet_exact": True,
    "measured": ("the four per-sentence keys: S7b review round 2 landing, the armed fixtures, three "
                 "scenarios x three tiers (RETIRED read); the bullet keys: S7b round 4, the same nine "
                 "cells, each block scored against its own rendered text"),
}

#: A MARKDOWN HEADING, and the WATCH SECTION is the span a heading whose words include "watch" opens.
_NOM_HEAD_RX = re.compile(r"^[ \t]{0,3}#{1,6}[ \t]+(.*)$", re.M)
#: A MARKDOWN LIST ITEM -- "bullet" in the ruling's own word. Dash, star, plus or a small ordinal.
_NOM_BULLET_RX = re.compile(r"^[ \t]{0,3}(?:[-*+]|\d{1,2}[.)])[ \t]+(.*)$")
_NOM_WATCH_WORD_RX = re.compile(r"\bwatch\b", re.I)
#: THE BLOCK'S OWN WATCH ROW (:func:`sb_watch`'s line, marker already stripped), which is what makes
#: the zero-writer read -- the block handed back verbatim -- readable without a heading it never wrote.
_NOM_BLOCK_MARK_RX = re.compile(r"^[*_\s]*WATCH\s", re.I)
#: WHERE A NOMINATION'S LABEL ENDS: its citation, its slot mark, or the colon that opens its claim.
_NOM_LABEL_CUT_RX = re.compile(r"\s*\[N|\s*\(|:")


def _nom_watch_bullets(text: str) -> list:
    """EVERY SHIPPED WATCH BULLET of ``text``, in page order. A BULLET IS THE WHOLE LIST ITEM.

    THAT IS THE WHOLE POINT OF THIS FUNCTION AND IT IS WHY THE PER-SENTENCE READ WAS WRONG. The
    mandate asks the writer to close with a LIST, and a list item is one item however many sentences it
    takes: the S7b smoke shipped ``- **Crude oil** -- below the elevated line, three months rising,
    about thirty-nine percent of the way from zero [N31]; window 2026-08-31 to 2027-02-28. Wrong if
    ...`` as ONE claim about ONE row, and a counter that graded its sentences separately asked each
    fragment to carry the whole identity. A CONTINUATION LINE RIDES ITS OWN ITEM for the same reason: a
    wrapped bullet is not two bullets. A blank line, a new marker or a heading ends the item.

    TWO SHAPES COUNT AS A WATCH BULLET, and the second is not a convenience:

      * a list item inside a WATCH SECTION -- the span opened by a heading whose words include
        "watch", closed by the next heading of any level. The section is what keeps the MECHANISM
        movement's bullets out: ``soybeans_now`` shipped ten list items, five of them under
        ``## Mechanism`` citing ``[N19]``, ``[N7]``, ``[N1]`` and ``[N34]``, and a rule that counted
        every bullet on the page would have credited the watch list with the mechanism's citations.
        THE HEADING IS NOT THE WRITER'S CHOICE: ``response_contracts`` declares the four and forbids
        a new one, and ``narration.MANDATE_MOVEMENTS`` maps the WATCH movement onto
        ``## What to watch``. The rule keys on the WORD rather than on that literal so a writer that
        wrote "## What to watch for" is still read -- one letter of slack, no second vocabulary;
      * a list item that opens with the block's OWN watch marker. :func:`sb_watch` renders
        ``- WATCH {kind words} ...``, so the zero-writer input -- the block handed back verbatim -- is
        read as the watch list it is, under no heading and with the block's other sixty-odd list items
        (SB-1 rows, path rows, receipts) correctly left out.

    A PAGE WITH NO WATCH HEADING AND NO MARKER HAS NO WATCH BULLETS, and the counters then read 0 used
    and 0 added. That is the fail-closed direction: a writer that shipped no watch list is credited
    with nothing rather than charged for a list nobody can find."""
    t = str(text or "")
    heads = list(_NOM_HEAD_RX.finditer(t))
    spans = [(h.end(), (heads[i + 1].start() if i + 1 < len(heads) else len(t)))
             for i, h in enumerate(heads) if _NOM_WATCH_WORD_RX.search(h.group(1))]
    items: list = []
    cur = None
    pos = 0
    for line in t.split("\n"):
        start, pos = pos, pos + len(line) + 1
        m = _NOM_BULLET_RX.match(line)
        if m:
            cur = [m.group(1), start]
            items.append(cur)
        elif cur is not None:
            if not line.strip() or _NOM_HEAD_RX.match(line):
                cur = None
            else:
                cur[0] += " " + line.strip()
    return [b for b, at in items
            if _NOM_BLOCK_MARK_RX.match(b) or any(a <= at < z for a, z in spans)]


def _nom_identity(line: str, words: tuple) -> tuple:
    """A NOMINATION'S TWO NAMES, READ OFF ITS OWN RENDERED LINE: the ``[N]`` it cites, and its SERIES
    KEY in the words the reader met.

    THE LINE AND NOT THE MANIFEST, for the reason the discriminator above it gives: ``Block.add``
    carries role / handles / tokens / line and NOT the caller's internal ``label``, and the
    nomination's backing citation is PRINTED by :func:`sb_watch` rather than minted as a call, so
    ``handles`` is empty on every one of these rows. What the reader met is the only place both names
    exist together.

    THE SERIES KEY IS THE DRIVER HALF OF THE LABEL. :func:`sb_watch` prints
    ``{kind words} {driver} on {board}{citation}{slot mark}: {claim}``, so the label is cut at the
    first of those three and split at its last `` on ``. :func:`_name_words` then applies the estate's
    ONE relaxation -- the last word alone, at five characters or more -- which is why ``flash drought``
    is also found as ``drought``. That relaxation is the loose half of this read and it is reported
    apart: see ``watch_candidates_cited``."""
    from leviathan.graphrag import verify as _vf
    s = str(line or "")
    body = s
    for w in words:
        if body.startswith(w):
            body = body[len(w):]
            break
    head = _NOM_LABEL_CUT_RX.split(body, maxsplit=1)[0].strip()
    who = head.rsplit(" on ", 1)[0].strip() if " on " in head else head
    return frozenset(_vf.cited_number_handles(s)), _name_words(who)


def _nomination_coverage(rows, sents, verdict_fn, asof: str = "", *, text: str = "") -> dict:
    """THE 2N NOMINATION'S OWN EIGHT NUMBERS -- and ``{}`` on every board that nominated nothing.

    THE RULE, AND IT IS A PER-BULLET RULE (S7b round 4, orchestrator ruling (7)). A NOMINATION IS USED
    when its own ``[N]`` handle, or its own series key, appears in a shipped WATCH BULLET. A SHIPPED
    WATCH BULLET THAT MATCHES NO NOMINATION IS WRITER-ADDED -- which is the one thing the selection
    licence bounds. Both are counted against :func:`_nom_watch_bullets`'s list items and never against
    sentences.

    WHAT IT REPLACES, AND WHY. The first cut asked ``board_coverage``'s own ``_verdict`` -- a
    ONE-SENTENCE window carrying every one of the row's token groups (its ISO dates AND its driver name
    AND, on a spillover, its far board). MEASURED on the three S7b real-seat draws: it read 5 of 37
    nominations used, where a human read of the same pages found every one of the 13 shipped watch
    bullets resting on a nomination, 13 of 13. Two causes, both granularity and neither a writer fault:
    a bullet is not a sentence (the identity is spread across the item -- name in the head, date in the
    tail), and a writer that PARAPHRASES the label ("Brent" for ``crude oil``, "The Pacific reading"
    for ``El Nino``, "Weekly US export sales" for ``export pace lag``) fails a name test while citing
    the row's handle in the same breath. The handle is the identity the writer actually carried, and
    the estate already binds every printed figure to it (``verify._check_number_handle``); this counter
    now reads the same name.

    THE TWO DIRECTIONS OF ERROR, NAMED, because no fence can check "is about this row":

      * ``watch_candidates_used`` OVER-CLAIMS ON PURPOSE when one row backs two nominations. The draw
        hands 2N candidates and the core and the alternate on one reading share one backing ``[N]``,
        so one bullet citing that handle marks BOTH used -- MEASURED 25 of 37 on the three draws
        against 13 bullets. That is the honest reading of "the writer kept this reading", not of "the
        writer kept this kind": which KIND it kept is not recoverable from a paraphrased bullet, and a
        counter that guessed would be measuring the guess.
      * THE SERIES-KEY LEG IS THE LOOSE HALF and is reported apart. ``watch_candidates_cited`` counts
        only the nominations whose own ``[N]`` reached a bullet and is <= ``watch_candidates_used`` by
        construction. MEASURED on the three draws the two are EQUAL (25 and 25): every match the
        shipped pages made was a citation, and the name leg earned nothing it did not already have.

    THE EIGHT KEYS: ``watch_candidates``, ``watch_candidates_used``, ``watch_candidates_cited``,
    ``watch_bullets``, ``watch_writer_added``, ``watch_admitted_zero``, ``watch_nomination_groups`` and
    ``watch_instrument_baseline``. ``watch_bullets`` is the DENOMINATOR ``watch_writer_added`` needs and
    the first cut did not have: "3 added" is a fact about a page only beside the number of bullets that
    page shipped.

    THE EMPTY DICT IS THE CONTRACT (threat: "absent is never zero"). With the non-obvious flag OFF the
    block carries HEAD's five watch kinds, this function returns ``{}`` BEFORE it reads ``text``, and
    ``board_coverage``'s returned dict is byte-identical to HEAD's twenty keys -- which is what the
    flag-off proof asserts on the three S6b fixtures, the sixteen banked census blocks and the 144
    banked board traces. A zero-filled block of eight keys would have made that proof fail on every
    turn and would have fabricated a ``0 of 0`` inside the arm's own dimension on turns that never ran
    the instrument.

    THE DISCRIMINATOR COVERS A KIND'S VARIANT SENTENCES TOO, because it is built from
    ``watch.NONOBVIOUS_KIND_WORDS`` itself: a variant carries its own phrase in that map (MAJOR 1's
    "running away from it"), so a variant row is counted by construction rather than by a second list
    that could fall behind.

    NO NEW EMF COUNTER SHIPS. These ride ``sg.trace['state_board']['coverage']``, which is where
    ``eval._judge_state_panel`` and the orchestrator's emitter already read, and which is
    ``seam.coverage_counters``' own declared home for the population it keeps out of EMF.

    ``sents``, ``verdict_fn`` AND ``asof`` ARE THE RETIRED READ'S INPUTS AND ARE STILL IN THE SIGNATURE.
    They are not read. They stay because this function is called POSITIONALLY by
    :func:`board_coverage` and pinned POSITIONALLY by a deck this lane may not open
    (``test_state_watch.py``'s "absent is never zero" pin), and because a signature is a contract:
    breaking it to tidy three names would be a deletion dressed as hygiene. The page itself arrives as
    the keyword-only ``text``, and a caller that hands none is read as a page with no bullets on it --
    0 used, 0 added -- rather than as a writer who dropped everything."""
    from leviathan.graphrag import verify as _vf
    from leviathan.graphrag.state import watch as _wa
    # THE DISCRIMINATOR IS THE RENDERED LINE AND NOT A LABEL, because `Block.add`'s manifest carries
    # role / rank / class / handles / tokens / line and NOT the caller's internal `label` -- `label` is
    # trip telemetry and stops at `self.trips`. The closed seven-phrase map is what a reader meets, so
    # it is also what the instrument keys on: one vocabulary, and a kind that renamed its words would
    # fail this read loudly rather than silently emptying the numerator.
    words = tuple(f"- WATCH {w} " for w in _wa.NONOBVIOUS_KIND_WORDS.values())
    noms = [m for m in rows
            if m.get("role") == "watch" and str(m.get("line") or "").startswith(words)]
    if not noms:
        return {}
    bullets = _nom_watch_bullets(text)
    low = [b.lower() for b in bullets]
    # ONE HANDLE PARSER IN THE ESTATE. `verify.cited_number_handles` reads a GROUPED token
    # (`[N41,42]`, `[N41-43]`) that the naive `"[N41]" in bullet` cannot see, so a writer that grouped
    # its citations is credited with all of them rather than with none.
    cites = [_vf.cited_number_handles(b) for b in bullets]
    matched = [False] * len(bullets)
    used = cited = 0
    for m in noms:
        hs, key = _nom_identity(str(m.get("line") or ""), words)
        hit_any = hit_cite = False
        for i, lb in enumerate(low):
            by_handle = bool(hs & cites[i])
            if by_handle or any(_token_hit(t, lb) for t in key):
                hit_any = True
                matched[i] = True
            hit_cite = hit_cite or by_handle
        used += int(hit_any)
        cited += int(hit_cite)
    return {"watch_candidates": len(noms), "watch_candidates_used": used,
            "watch_candidates_cited": cited,
            "watch_bullets": len(bullets),
            "watch_writer_added": sum(1 for ok in matched if not ok),
            "watch_admitted_zero": any(str(m.get("line") or "").startswith(
                "BOARD ABSENCE a forward item on this page") for m in rows),
            "watch_nomination_groups": len([g for m in noms for g in (m.get("tokens") or ())]),
            # THE INSTRUMENT'S OWN ERROR FLOOR, CARRIED WITH ITS NUMBERS (review round 2, minor c; the
            # bullet keys added round 4). An arm reading a RATE off these counters needs to know what
            # they return when the writer added nothing and dropped nothing: see
            # `NOMINATION_ZERO_WRITER_BASELINE`, which now carries BOTH the shipped read's floor and
            # the retired read's, because the banked round-2 and round-3 traces were produced by the
            # latter.
            "watch_instrument_baseline": dict(NOMINATION_ZERO_WRITER_BASELINE)}
