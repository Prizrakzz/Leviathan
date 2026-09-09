"""THE NARRATION CONTRACT -- STATE ENGINE DESIGN sec 6.4 (the mandate, shipped only when the board is
there) and 6.5 (per-layer recency as FACTS, never a verdict). Sitting S3.

WHAT THIS MODULE IS. Three literals and the arithmetic that fills them: the mandate the writer is handed
beside the board block, the age clause a stale row carries, and the two recency sentences that replace
the estate's single "the record here runs through <month year>" clause with per-layer facts. It is
LANE-FREE: nothing here is appended to a prompt in this sitting. S6 appends
:data:`SYSTEM_STATE_BOARD_MANDATE` in ``_system()`` under ``if state_board:``, in the SAME COMMIT as the
block -- which is doctrine M-7 and the estate's own measured reason: under a conditional LICENSE alone
the writer transcribed the walk on one of three walk-fired rows.

WHY THE MANDATE IS A LITERAL AND NOT A BUILDER. It is graded at BUILD by all four register detectors
(``state/lint.py``), it is pinned byte-for-byte by a deck, and it carries no figure of its own -- so the
one thing it can never do is acquire a number by interpolation. Every figure the writer prints comes
from a board row with its own handle.

THE FOUR MOVEMENTS MAP ONTO THE SHIPPED SPINE WITH NO NEW HEADING (D-RC-3): DIRECTION -> ``## Mechanism``;
EVIDENCE, analogs included -> ``## The record``; SPILLOVERS -> ``## Cross-commodity`` /
``## Complex-wide move`` where the contract licenses them, else inside ``## Mechanism``; WATCH ->
``## What to watch``. The mandate is APPENDED and never a rewrite of the fixed four, and it sits ABOVE
``_SYSTEM_HANDLES``, which stays last because it narrows every number rule.

ASCII-ONLY; the file is UTF-8.
"""
from __future__ import annotations

import datetime as _dt
from typing import Optional

# ---------------------------------------------------------------------------------------------------
# 6.4 THE MANDATE
# ---------------------------------------------------------------------------------------------------
#: The mandate literal (sec 6.4), Draft B's text merged with Draft D's, including the JUDGEMENT sentence
#: the owner's ruling 1 assigns to the writer. Letters only, no forecast verb, no heading called then or
#: now, and no figure -- ``state/lint.py`` runs ``pace_register_ok``, ``count_flow_words``,
#: ``count_valuation_words``, ``register_leaks`` and ``_LANE_B_ADJ`` over it at build.
SYSTEM_STATE_BOARD_MANDATE = (
    "THE STATE OF THE WORLD block above is this turn's board: every driver the graph declares for the "
    "markets in play, read on its own series at this as-of and ranked by how far it sits from its own "
    "history. Narrate it as a mentor in this order and no other. (1) DIRECTION: state your read of "
    "where the anchor market's balance sits now, which way the loud drivers lean and which leg you "
    "expect to dominate, citing the rows by handle; where the rows lean both ways, say so and name "
    "both sides. Where a loud row is a large move on a short or thin history, or a run the block names "
    "no mechanism for, say whether you read it as an isolated shock or as a mechanism the graph "
    "explains -- that judgement is yours; the block only orders. (2) EVIDENCE: for each driver you "
    "lean on, give the figure in its unit and the plain meaning in the same sentence, and date it by "
    "the row's own knowledge date; a LIKE STATE stanza is history -- say what measured then, over the "
    "stated lag band, at both ends, then how many such cases the record carries, in words, and never "
    "present it as what will happen; when the block says no documents exist for it, say so. "
    "(3) SPILLOVERS: name every other market the block declares the same loud state moves, with the "
    "sign word and the lag words the block gives for THAT market; the sign can differ across markets "
    "and you must keep each market's own, never reconciling two signs into one. (4) WATCH: close with "
    "the WATCH rows -- the next scheduled print, the level a convention names, the date a declared lag "
    "window opens -- as concrete items with their dates; never a generic caution. Write every "
    "PROJECTION in the conditional mood, carry its band as two calendar months, and say what it is "
    "counted from. Base rates come from the block's count words, never from a figure you compute. A "
    "BOARD ABSENCE row is a fact about coverage: name the gap in words and assert no number for it. "
    "State each RECENCY row as a fact about the layer it names; none of them dates the answer as a "
    "whole. Use no heading called then or now."
)

#: The four movements, the heading each lands under, and the FALLBACK where that heading is a licensed
#: one rather than a canonical one (D-RC-3). It is a TABLE rather than prose so a reviewer can check the
#: claim "no new heading" mechanically against ``response_contracts``' own two sets.
#:
#: SPILLOVERS IS THE ONE MOVEMENT WITHOUT A CANONICAL HOME, and that is why the third entry carries two
#: headings: ``## Cross-commodity`` and ``## Complex-wide move`` are RESERVED literals the contract
#: licenses per turn, not members of ``CANONICAL``, so on a turn that licenses neither the movement is
#: narrated inside ``## Mechanism``. Recording the fallback here is what keeps "no new heading" a
#: checkable claim instead of an assurance.
MANDATE_MOVEMENTS: tuple = (
    ("DIRECTION", "## Mechanism", ""),
    ("EVIDENCE", "## The record", ""),
    ("SPILLOVERS", "## Cross-commodity", "## Mechanism"),
    ("WATCH", "## What to watch", ""),
)


def mandate_for(volatile_prompt: Optional[str]) -> str:
    """The mandate, or the empty string when the board's own marker is NOT in the prompt.

    THE GATE IS THE PRODUCER'S CONSTANT, never a second copy of the marker string
    (``render.SB_MARKER_PREFIX``; the CW_MARKER_PREFIX law). A mandate that shipped without its block
    would instruct a writer to narrate rows nobody handed it, which is the failure mode the estate
    already measured on the walk."""
    from leviathan.graphrag.state.render import block_marker_present
    return SYSTEM_STATE_BOARD_MANDATE if block_marker_present(volatile_prompt) else ""


# ---------------------------------------------------------------------------------------------------
# 6.5 (1) THE AGE CLAUSE -- per ROW, in the hyphen-compound orthography
# ---------------------------------------------------------------------------------------------------
#: The DECLARED age limit per cadence, in DAYS (sec 6.5 (1), Draft B's table). It is a TABLE and not
#: "two times the cadence" (doctrine m-4): a monthly ONI three months old is stale and a daily FX three
#: days old is not, and no multiple of a cadence says both.
AGE_LIMIT_DAYS: dict = {
    "daily": 7, "weekly": 21, "weekly_destination": 21, "biweekly": 35, "monthly": 75,
    "annual": 400, "release": 400,
}

#: The estate's own constant, restated so the two clauses can be compared: ``CW_WINDOW_AGE_MONTHS`` (12)
#: stays the WALK's threshold for a firing window's age and is NOT the board's -- the board dates a ROW
#: by its cadence, which is a different question about a different object.
WALK_WINDOW_AGE_MONTHS = 12


def age_clause(knowledge_date: Optional[str], asof: str, cadence: str) -> str:
    """The row's AGE CLAUSE, or "" when the row is fresh enough for its own cadence.

    THE ORTHOGRAPHY IS LOAD-BEARING and it is ``_cw_window_age_note``'s, verbatim in shape
    (cascade.py:7413): a hyphen compound with a ``_STAT_HEAD`` noun ("17-month span to this as-of")
    clears ``verify._claim_number_spans`` rule (f), so a writer can copy the clause into a handled
    sentence and it survives; the space spelling ("17 months before this as-of") would strip the whole
    sentence as ``number_unbacked``, because "before" is a ``_DUR_STOP``. The noun is "span" and not
    "gap" for a second reason: the walk's mandate forbids the writer to derive a gap between two rows,
    and a row printing the word would teach the idiom it fences.

    THE UNIT SWITCHES AT TWO YEARS and the year count is FLOORED -- the same safe direction the estate's
    clause takes: an understated age is never an overstated freshness."""
    limit = AGE_LIMIT_DAYS.get(cadence or "", AGE_LIMIT_DAYS["monthly"])
    try:
        kd = _dt.date.fromisoformat(str(knowledge_date or "")[:10])
        a = _dt.date.fromisoformat(str(asof or "")[:10])
    except ValueError:
        return ""                                   # an unreadable date DECLINES, never guesses
    days = (a - kd).days
    if days <= int(limit):
        return ""
    months = (a.year * 12 + a.month) - (kd.year * 12 + kd.month)
    if a.day < kd.day:
        months -= 1
    if months < 1:
        return f"read through {kd.isoformat()}, {days}-day span to this as-of"
    n, unit = (months // 12, "year") if months >= 24 else (months, "month")
    return f"read through {kd.isoformat()}, {n}-{unit} span to this as-of"


# ---------------------------------------------------------------------------------------------------
# 6.5 (2) THE LEDGER SENTENCE -- one fact per LAYER
# ---------------------------------------------------------------------------------------------------
#: The then/now design's sentence 5c (i), which EXTENDS ``_recency_ledger_suffix`` (answer.py:1799).
#: THREE EDGES, each a fact about the layer it names, and the closing clause states in so many words
#: that none of them dates the others -- which is the whole point: a single "the record here runs
#: through <month>" sentence has THE ANSWER as its subject and can be inflated into "not a current-state
#: read", and neither sentence here has a subject that permits that reading.
RECENCY_LEDGER_SENTENCE = (
    "The number rows on this page are read as of {asof}, and each row carries its own knowledge date; "
    "the newest is {kd_max} and the oldest {kd_min}. The newest dated document behind this answer is "
    "{record_through}. The board price tape runs through {tape_edge}. Each of those is a fact about "
    "the layer it names, and none dates the others."
)

#: ``_SYSTEM_RECENCY``'s replacement clause (sec 6.5 (3)). It replaces the shipped sentence whose
#: subject is the ANSWER; both of these have a CLAIM as their subject, so neither can be read as a
#: verdict on the answer as a whole.
SYSTEM_RECENCY_CLAUSE = (
    "When a claim rests on a dated document, date that claim by the document's own date; when it rests "
    "on a number row, date it by that row's own knowledge date. The GROUNDING LEDGER states every "
    "edge. State each edge as a fact about the layer it names."
)

#: The sentence a rendered board may never contain (bar B12). It is the phrase the V2-5 panel produced
#: when one layer's age was allowed to date the whole page.
BANNED_RECENCY_PHRASE = "not a current-state read"


def recency_ledger(*, asof: str, kd_max: str = "", kd_min: str = "", record_through: str = "",
                   tape_edge: str = "") -> str:
    """The ledger sentence with the board's own four dates. A missing edge prints the plain words for
    "this layer carries nothing on this page" rather than an empty slot -- an empty slot would read as
    a date the reader could not see."""
    none_words = "not carried on this page"
    return RECENCY_LEDGER_SENTENCE.format(
        asof=asof or none_words, kd_max=kd_max or none_words, kd_min=kd_min or none_words,
        record_through=record_through or none_words, tape_edge=tape_edge or none_words)


def recency_rows(bd, *, kd_min: str = "", record_through: str = "", tape_edge: str = "") -> dict:
    """The three SB-L lines (sec 6.2, 6.5 (2)) as ``{layer: text}``, in the design's own layer order.

    THREE SEPARATE ROWS AND NOT ONE SENTENCE, because the render's SB-L class is per layer and because a
    reader who meets three dated facts cannot fold them into one verdict about the page. The ledger
    SENTENCE above is the same three facts for the prose ledger; both come from this one producer."""
    kd_max = str(bd.recency.get("numbers") or "")
    text = str(bd.recency.get("text") or record_through or "")
    # THE OLDEST KNOWLEDGE DATE IS DERIVED FROM THE BOARD when the caller does not state one. It is on
    # the ledger sentence by name ("the newest is {kd_max} and the oldest {kd_min}") and a caller who
    # had to compute it would be a second producer of a fact the board already holds.
    oldest = kd_min or min((str(st.knowledge_date) for st in bd.series.values()
                            if st.knowledge_date), default="")
    numbers = (f"read as of {bd.asof}; the newest knowledge date on a number row is "
               f"{kd_max or 'not carried on this page'}"
               + (f" and the oldest is {oldest}" if oldest else ""))
    text_line = (f"the newest dated document behind this answer is "
                 f"{text or 'not carried on this page'}")
    tape_line = (f"the board price tape runs through {tape_edge or 'not carried on this page'}")
    return {"numbers": numbers, "text": text_line, "tape": tape_line}


def check_literals() -> list:
    """Every literal in this module is register-clean and digit-free where its class requires it.
    Returns the complaints; empty == clean. ``state/lint.py`` calls it, and so does the S3 deck --
    the mandate is a shipped literal and a build failure is the only acceptable place to find one."""
    from leviathan.graphrag.state.render import register_hits
    errs: list = []
    for name, text in (("SYSTEM_STATE_BOARD_MANDATE", SYSTEM_STATE_BOARD_MANDATE),
                       ("RECENCY_LEDGER_SENTENCE", RECENCY_LEDGER_SENTENCE),
                       ("SYSTEM_RECENCY_CLAUSE", SYSTEM_RECENCY_CLAUSE)):
        hits = register_hits(text)
        if hits:
            errs.append(f"narration.{name}: {', '.join(hits)}")
        try:
            text.encode("ascii")
        except UnicodeEncodeError:
            errs.append(f"narration.{name}: not ASCII")
        # NO DIGIT CLAUSE HERE, and the absence is a decision rather than an oversight. Sec 6.4 calls
        # the mandate "ASCII, letters only", but its own quoted literal numbers the four movements
        # "(1) DIRECTION ... (4) WATCH" -- and those enumerators are structural, not magnitudes. The
        # letters-only law is about the BLOCK's own row classes, where a digit outside a figure-bearing
        # class trips `verify._claim_number_spans` on a line a writer may copy. A SYSTEM prompt is never
        # extracted for claim magnitudes, so the rule does not reach it. What IS graded here is what
        # actually binds: ASCII, all four register detectors, `pace_register_ok`, and the banned
        # recency phrase.
        if "{" in text and name != "RECENCY_LEDGER_SENTENCE":
            errs.append(f"narration.{name}: carries a format slot; only the ledger sentence has one")
    try:
        from leviathan.graphrag.numbers.cascade import pace_register_ok
        if not pace_register_ok(SYSTEM_STATE_BOARD_MANDATE):
            errs.append("narration.SYSTEM_STATE_BOARD_MANDATE: pace_register_ok is False")
    except Exception as exc:                        # noqa: BLE001 -- named, never raised onward
        errs.append(f"narration: could not run pace_register_ok: {exc}")
    if BANNED_RECENCY_PHRASE in SYSTEM_STATE_BOARD_MANDATE:
        errs.append("narration.SYSTEM_STATE_BOARD_MANDATE: carries the banned recency phrase")
    return errs
