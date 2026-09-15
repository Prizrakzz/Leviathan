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

THAT MAPPING IS ABOUT NAMES, NOT ABOUT ORDER, and the first S6 build's mandate read as though it were
about both -- see :data:`MANDATE_MOVEMENTS` for the measurement and the correction.

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
    "history. Cover these four movements as a mentor, in this order of ideas, under the headings your "
    "response contract already names and adding no heading of your own; where a movement has no "
    "heading of its own, narrate it inside the section its ideas belong to. (1) DIRECTION: state your "
    "read of where the anchor market's balance sits now, which way the loud drivers lean and which "
    "leg you expect to dominate, citing the rows by handle; where the rows lean both ways, say so and "
    "name both sides -- unless a BOARD JOIN row says two of them are one reading under two names, "
    "which is one side and never two. Where a loud row is a large move on a short or thin history, or "
    "a run the block names "
    "no mechanism for, say whether you read it as an isolated shock or as a mechanism the graph "
    "explains -- that judgement is yours; the block only orders. (2) EVIDENCE: for each driver you "
    "lean on, give the figure in its unit and the plain meaning in the same sentence, and date it by "
    "the row's own knowledge date; a LIKE STATE stanza is history -- say what measured then, over the "
    "stated lag band, at both ends, then how many such cases the record carries, in words, and never "
    "present it as what will happen; when the block says no documents exist for it, say so. The "
    "RECENCY rows belong to this movement and are owed to the reader like any other evidence: give "
    "each layer its own plain sentence -- the newest knowledge date the number rows carry, the newest "
    "dated document behind the page, the session the board price tape runs through -- so the reader "
    "learns how far each layer reaches instead of inferring one edge from another. "
    "(3) SPILLOVERS: name the other markets the block declares the same loud state moves, each with "
    "the sign word the block gives for THAT market and with its lag words where the block states them "
    "for it; where the block gives a market a direction and no lag, say the direction and leave the "
    "lag unstated rather than borrowing another market's. The sign can differ across markets and you "
    "must keep each market's own, never reconciling two signs into one. When the block carries a "
    "CROSS-COMMODITY line, that line is the board's own and it names the markets the rows above "
    "reach: those markets are what the cross-commodity section holds on this turn, each with the sign "
    "words and the lag words its own row carries. That line licenses the section and states nothing "
    "else: it carries no stocks-to-use rows and no handle of its own, it is not a link in a "
    "transmission chain, and it opens no fork heading. A CROSS-COMMODITY line that sets two "
    "commodities' stocks-to-use rows side by side is a different line under its own rule; read each "
    "line by the rows beneath it. (4) WATCH: close with "
    "the WATCH rows -- the next scheduled print, the level a convention names, the date a declared lag "
    "window opens -- as concrete items with their dates; never a generic caution. Write every "
    "PROJECTION in the conditional mood, carry its band as two calendar months, and say what it is "
    "counted from. Base rates come from the block's count words, never from a figure you compute. A "
    "BOARD ABSENCE row is a fact about coverage: name the gap in words and assert no number for it. "
    "State each RECENCY row as a fact about the layer it names; none of them dates the answer as a "
    "whole. Use no heading called then or now."
)

#: S7b R2 -- THE DESK REGISTER. A SECOND, FLAG-SCOPED LITERAL, appended under `GRAPHRAG_DESK_REGISTER`
#: and NEVER an edit to the mandate above, which is the `_SYSTEM_CASCADE_WALK_MANDATE` idiom
#: ``answer.py`` already uses. Editing :data:`SYSTEM_STATE_BOARD_MANDATE` in place would change the
#: system prompt on EVERY board-on turn with the new flag off, and the prompt is the first row of this
#: sitting's byte-identity set.
#:
#: WHY IT EXISTS, MEASURED (2026-09-11, ``scratchpad/lingo_leaks.py`` over the NINE banked real-seat
#: answers): 195 internal-vocabulary hits, 21.7 per answer -- ``board`` 64, ``row``/``rows`` 54,
#: "the graph" 40, ``loud`` 13, "knowledge date" 10, ``convention`` 6, "state read" 2, ``receipt`` 2,
#: ``node`` 1. The opening sentence of one prod-seat answer reads "Reading the board at 2026-09-07, the
#: loudest thing on ICE cocoa is...". THE WRITER COPIES THE BLOCK'S VOCABULARY, which is the predictable
#: price of handing it a block, and no shipped detector charges a word of it: every one of those tokens
#: is ordinary English, so ``register_leaks`` -- which catches slugs and ``conf=`` -- is blind by design.
#:
#: IT NAMES THE REPLACEMENTS RATHER THAN ONLY THE BAN, and the table comes from
#: ``register.desk_register_table()`` so the prompt that teaches the vocabulary and the lint that counts
#: it can never disagree about which words are meant. A ban with no replacement is how a writer loses a
#: fact rather than a word.
#:
#: THE ONE EXCEPTION IS STATED IN THE LITERAL ITSELF, because it is the mandate's own required sentence:
#: movement (2) above instructs the writer to write "the session the board price tape runs through", and
#: :data:`RECENCY_LEDGER_SENTENCE` prints "The board price tape runs through {tape_edge}". A rule that
#: banned ``board`` without naming that phrase would order the writer to disobey the mandate it ships
#: beside. The lint carries the same exemption as DATA (``register.DESK_REGISTER_EXEMPT``), and neither
#: this literal nor ``render.py``'s "past the line the desk convention calls X" is reworded to suit it.
#: REVIEW MAJOR 4 (2026-09-11): THE BAN IS TURN-WIDE, THE RECENCY INSTRUCTION IS NOT.
#: The mandate shipped as ONE literal on a FLAG-ONLY gate, so its last movement -- "say the newest and
#: oldest dates the numbers on this page carry, the date of the newest document behind it, and the
#: session the board price tape runs through" -- rode every flag-on turn, including turns with no board
#: and no recency leg. Measured: ``_system(desk_register=True)`` carried "board price tape" and "The
#: RECENCY movement" while :data:`SYSTEM_STATE_BOARD_MANDATE` and :data:`SYSTEM_RECENCY_CLAUSE` were
#: both absent -- an unconditional instruction whose three facts come from a block that is not there.
#: That is the exact failure the lane guarded ONE LINE ABOVE at ``answer._system``'s ``watch_selection``
#: leg ("a writer is never told to select from candidates the board did not nominate"), not applied
#: here. The BAN half is legitimately turn-wide -- "the graph" leaks on a cascade-walk turn that carries
#: no board at all, which is why the leg is not folded into ``state_board`` -- so the literal SPLITS and
#: only the half whose facts the board supplies rides the board's own gate.
SYSTEM_DESK_REGISTER_MANDATE = (
    "REGISTER: you are writing for a commodity desk, so write about the MARKET and never about the "
    "instrument that produced the reading. The blocks above are working notes to you; their words are "
    "not the reader's words. Do not tell the reader what you are reading from -- no naming of the "
    "board, the graph, a state read, a series key, a node, a knowledge date, a convention, a receipt, "
    "a row or a walk, and no calling a reading loud. Say the market thing instead: {table}. A named "
    "exchange, institution or commodity board is the market's own name and stays exactly as written -- "
    "the CBOT soybean board, the board crush, the Malaysian Palm Oil Board. Everything else the blocks "
    "name, name in the reader's words: give the "
    "figure, its unit, the market it belongs to and the date it was read through, and let those stand "
    "as the reason. Keep every citation "
    "handle exactly where it is; changing a word never changes a figure."
)

#: The RECENCY half, appended by :func:`desk_register_mandate` ONLY when the board's own mandate ships
#: on the same turn -- the leg that supplies the three dated facts it instructs about, and the only leg
#: on which :data:`RECENCY_LEDGER_SENTENCE`'s tape line is a sentence the writer has been told to write.
DESK_REGISTER_RECENCY_CLAUSE = (
    " One more phrase is the market's own and stays exactly as the blocks give it: the board price "
    "tape, which is the sentence you are told to write for the tape layer. The RECENCY movement keeps "
    "every one of its three facts and changes only their "
    "words: say the newest and oldest dates the numbers on this page carry, the date of the newest "
    "document behind it, and the session the board price tape runs through -- three dated facts, each "
    "about the layer it names, and none of them dating the answer as a whole."
)

#: The four movements, the heading each lands under, and the FALLBACK where that heading is a licensed
#: one rather than a canonical one (D-RC-3). It is a TABLE rather than prose so a reviewer can check the
#: claim "no new heading" mechanically against ``response_contracts``' own two sets.
#:
#: SPILLOVERS IS THE ONE MOVEMENT WITHOUT A CANONICAL HOME, and the S6 review measured what that costs.
#: ``## Cross-commodity`` and ``## Complex-wide move`` are RESERVED literals the contract licenses per
#: turn, not members of ``CANONICAL``: 0 of the 10 shipped ``response_contracts.CONTRACTS`` carry either
#: in ``sections``, and both are INJECTED-ONLY -- licensed by a ``CROSS-COMMODITY`` / ``CO-MOVE`` marker
#: LINE. AT S6 THE BOARD MINTED NEITHER, on any of the three acceptance fixtures, so the fallback was
#: not the exception: it was the only branch on every board turn shipped.
#:
#: WHAT THAT COST, MEASURED TWICE. Over the twelve banked cascade turns ``## Mechanism`` carried 1 of
#: 239 first-cited handles (0.4%) against ``## The record``'s 147 -- so the movement was aimed at the
#: one section the writer keeps number-free. And on three prod-seat draws over the acceptance fixtures
#: SPILLOVERS was the only movement of the four that broke: dropped entirely on ``soybeans_now`` (ten
#: off-anchor fan rows, zero named), parked after ``## What to watch`` on ``el_nino_fanout``, and
#: placed correctly only on ``b40_event``, where the anchor board IS the spillover subject.
#:
#: S7 GIVES IT THE HOME RATHER THAN REWORDING THE MOVEMENT. ``render.sb_cross_commodity`` mints the
#: ``CROSS-COMMODITY`` licence line the persona already keys the heading on, iff the block rendered at
#: least one FAR row across a cross edge -- so ``## Cross-commodity`` is now the LIVE branch on a board
#: turn that has spillovers and the fallback stays exactly where it was for a board that has none. The
#: mandate gains ONE sentence scoping that line (the four movements keep ONE producer, which is the
#: G5 law); the persona paragraph at answer.py:550-577 is NOT touched, so a flag-off turn is
#: byte-identical.
#:
#: AND THE SCOPING SENTENCE IS WHERE FOUR CONSUMERS OF THE BARE WORD ARE ANSWERED AT ONCE, which is the
#: reason it sits in the mandate rather than in any of them. The token ``CROSS-COMMODITY`` is read by
#: ``_SYSTEM_CASCADE_A`` (answer.py:550-577, the su_ratio rule -- "two DIFFERENT commodities'
#: stocks-to-use ratios ... show BOTH commodities' su_ratio [N] rows"), by ``_SYSTEM_CASCADE_B``
#: (answer.py:709, "if there is NO CROSS-COMMODITY line ... do not invent a fork"), by
#: ``_SYSTEM_TRANSMISSION`` (answer.py:783, "a link whose line begins CROSS-COMMODITY is a
#: relative-value divergence"), and by ``numbers/cascade.py``'s own world-balance leg, which mints a
#: second line under the same word on a turn that runs both legs. EDITING ANY OF THE THREE PERSONA
#: PARAGRAPHS WOULD CHANGE THE SYSTEM PROMPT ON EVERY FLAG-OFF TURN -- they are unconditional module
#: constants -- so the scope is stated in the ONE literal that ships only when the board does: the
#: board's line carries no stocks-to-use rows and no handle, is not a chain link, opens no fork, and a
#: line that DOES set two su_ratio rows side by side keeps its own rule. The eval-side half of the same
#: collision (`_cascade_asserts`' `reroute_v2_expected` negative branch, which reds on the HEADING) is
#: exempted there, gated on this turn's own `state_board` trace.
#:
#: AND THE FALLBACK COLLIDED HEAD-ON WITH THE SPINE. The mandate used to open "narrate it as a mentor in
#: this order and no other" with SPILLOVERS THIRD, while ``response_contracts`` orders "'## Mechanism',
#: '## The record', '## Where the record disagrees', '## What to watch'" and forbids returning to
#: Mechanism after The record. A writer had to break one of the two on 100% of board turns and no deck
#: graded which. THE MANDATE NOW STATES AN ORDER OF IDEAS UNDER THE CONTRACT'S OWN HEADINGS rather than
#: a heading sequence, which is what the design's "the four movements map onto the response-contract
#: spine with no new heading" was always true ABOUT -- names, never order. This table records the
#: mapping and the fallback so "no new heading" stays a claim a reviewer can check mechanically against
#: ``response_contracts``' own two sets.
MANDATE_MOVEMENTS: tuple = (
    ("DIRECTION", "## Mechanism", ""),
    ("EVIDENCE", "## The record", ""),
    ("SPILLOVERS", "## Cross-commodity", "## Mechanism"),
    ("WATCH", "## What to watch", ""),
)


def watch_selection_mandate() -> str:
    """S7b LANE W's SELECTION CLAUSE, appended to the board mandate under its own flag.

    LANDED BY THE TWO-LANE SEAM PROTOCOL (threat model sec 6.1): the constant is lane W's and lives in
    ``state/watch.py``; this lane appends it and nothing else. It belongs in the MANDATE and not in the
    block because the block's rows are SB-W lines -- a licence sentence rendered as a row would need a
    class of its own in ``render.ROW_CLASSES``, which is in this sitting's byte-identical set, and
    would red ``lint._check_row_classes`` (every class needs a sample).

    ONE PRODUCER, never a second copy of the text: a mandate that quoted the clause would drift from
    the one ``test_state_watch.py`` grades for register-cleanliness."""
    from leviathan.graphrag.state.watch import WATCH_SELECTION_CLAUSE
    return WATCH_SELECTION_CLAUSE


def desk_register_mandate(state_board: bool = False) -> str:
    """:data:`SYSTEM_DESK_REGISTER_MANDATE` with its replacement table filled from
    ``register.desk_register_table()`` -- ONE producer for the words the prompt teaches and the words
    the lint counts, so a token added to the lint cannot silently leave the prompt behind.

    THE SLOT IS FILLED HERE AND NOT AT THE SEAM for the reason the ledger sentence's is: a caller that
    formatted its own copy would be a second producer of a shipped literal, and ``check_literals`` grades
    THIS function's output, not the raw template.

    ``state_board`` APPENDS :data:`DESK_REGISTER_RECENCY_CLAUSE` (review MAJOR 4). Default False, which
    is the turn-wide ban alone: the recency instruction names three facts only the board block carries,
    so it ships iff that block does. The caller passes ``answer._system``'s own ``state_board`` bool --
    the flag AND the block's marker -- never a second reading of anything."""
    from leviathan.graphrag.register import desk_register_table
    base = SYSTEM_DESK_REGISTER_MANDATE.format(table=desk_register_table())
    return base + DESK_REGISTER_RECENCY_CLAUSE if state_board else base


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
    # S7b R2: the desk-register literal is graded as its FORMATTED output (`desk_register_mandate()`),
    # because that is what ships; the raw template carries a slot and would red the slot clause below.
    # It is graded by the SAME four register detectors, the SAME ASCII rule and the SAME banned recency
    # phrase as the mandate it rides beside -- a shipped literal's register trip is a BUILD failure here
    # and never a stripped answer at serve time.
    try:
        # BOTH HALVES, graded together: `state_board=True` is the widest text that can ship, so a
        # register trip in the flag-scoped RECENCY clause is a build failure exactly as one in the ban
        # half is (review MAJOR 4 split the literal; it did not split the grading).
        _desk = ("SYSTEM_DESK_REGISTER_MANDATE", desk_register_mandate(state_board=True))
    except Exception as exc:                        # noqa: BLE001 -- named, never raised onward
        errs.append(f"narration: could not render desk_register_mandate: {exc}")
        _desk = ("SYSTEM_DESK_REGISTER_MANDATE", "")
    for name, text in (("SYSTEM_STATE_BOARD_MANDATE", SYSTEM_STATE_BOARD_MANDATE),
                       ("RECENCY_LEDGER_SENTENCE", RECENCY_LEDGER_SENTENCE),
                       ("SYSTEM_RECENCY_CLAUSE", SYSTEM_RECENCY_CLAUSE),
                       _desk):
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
        for _n, _t in (("SYSTEM_STATE_BOARD_MANDATE", SYSTEM_STATE_BOARD_MANDATE), _desk):
            if _t and not pace_register_ok(_t):
                errs.append(f"narration.{_n}: pace_register_ok is False")
    except Exception as exc:                        # noqa: BLE001 -- named, never raised onward
        errs.append(f"narration: could not run pace_register_ok: {exc}")
    for _n, _t in (("SYSTEM_STATE_BOARD_MANDATE", SYSTEM_STATE_BOARD_MANDATE), _desk):
        if BANNED_RECENCY_PHRASE in _t:
            errs.append(f"narration.{_n}: carries the banned recency phrase")
    return errs
