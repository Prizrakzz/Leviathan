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
import re
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
#: THE EXEMPTION SIDE IS NAMED TOO, AND IT USED TO NAME TWO OF NINE (coherence audit 2026-09-16,
#: WP-A8). ``register.DESK_REGISTER_EXEMPT`` carries NINE rows; the literal named the board classes and
#: (on the board leg) the board price tape, and nothing else -- so the prompt FORBADE what the lint
#: PERMITS: "the desk convention calls" (whose stated reason is that ``state/render.py`` prints
#: ``past the line the desk convention calls {label}`` on a loud row, i.e. the writer was told never to
#: name a convention on a turn whose own rows print the phrase), market/desk/trade/delivery/contract
#: convention, row crops, registered and warehouse and delivery receipts, "receipts of", Board of Trade,
#: and the named chart/port idioms. This module's own doctrine is the argument: "A ban with no
#: replacement is how a writer loses a fact rather than a word" -- and a ban with no EXEMPTION is how it
#: loses one it was allowed to keep.
#: THE TWO HALVES STILL HAVE TWO PRODUCERS, and that is DOCKETED rather than done: folding the exemption
#: sentence out of ``DESK_REGISTER_EXEMPT`` the way ``{table}`` is folded out of
#: ``DESK_REGISTER_TOKENS`` needs a WRITER-FACING display column on that tuple, because its ``why``
#: column is addressed to a reviewer and names file paths, review rounds and served table families --
#: text that must never reach a writer's prompt. Until that column exists, a row added to the lint's
#: exemption table owes an edit here.
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
#:
#: PRE-ARM ROUND 2 (2026-09-17) -- THE THREE NEW RULES ARE SCOPED, AND THE SCOPE IS A MEASUREMENT.
#: Round 1 added them with no negative corpus; re-measured over 748 real-seat sentences (the five
#: 2026-09-16 served bodies and the 14 banked answers) they reached prose the board mandate REQUIRES on
#: the same turn -- and inside ``answer._system`` the desk leg is appended LAST, after the board
#: mandate's own leg (measured 2026-09-17: ``state_board_mandate`` at answer.py:3697,
#: ``desk_register_mandate`` at answer.py:3723; the file is moving under another lane this sitting, so
#: the ORDER is the fact and the line numbers are the read). On a contradiction the desk leg wins.
#:
#: (1) THE COUNTING BAN IS GONE AND A SCORING BAN REPLACES IT. "a sentence that counts the things it
#: is reading has stopped writing about markets" was unscoped, while ``SYSTEM_STATE_BOARD_MANDATE``
#: movement (2) orders "how many such cases the record carries, IN WORDS", movement (3) orders "name
#: the other markets the block declares the same loud state moves", and the mandate closes "Base rates
#: come from the block's count words". MEASURED: 11 sentences in the two corpora carry exactly those
#: constructions ("declared on twenty-three other markets, twenty-two in the same direction"; "the
#: record carries thirty-three crossings of this low-stocks state since 2006") and round 1's rule
#: reached 10 of them. The rule now bans the PATTERN'S OWN SCORE -- the threshold NUMBER and the ROSTER
#: SIZE -- and REQUIRES the met conditions to be named in the market's words, which is the PM lens' own
#: remedy ("either explain the pattern in trader terms or cut it") and keeps the surface the graders'
#: FATAL rests on: the max page's quorum was ARITHMETICALLY WRONG (one reading served twice under two
#: names and counted twice), and a reader can only catch that when the met conditions are NAMED.
#: RE-MEASURED: sentences reached 123 -> 34 over both corpora (case list 30 -> 10, banked 93 -> 24),
#: and of the 11 board-required constructions round 2 reaches ZERO.
#:
#: (2) THE DATE RULE CARVES OUT THE BARE YEAR AND THE MARKETING YEAR. "never as a bare run of digits
#: with no separators" reached 250 tokens across the two corpora of which 242 are not the defect -- 47
#: bare years, 17 ``MY20xx`` tokens and 44 printed VALUES on the case list alone (89 / 0 / 45 on the
#: banked fourteen). It now names the SHAPE (year, month and day run together) and states the carve-out
#: in the rule itself. RE-MEASURED: sentences reached 145 -> 8, tokens 250 -> 8, and the 8 are exactly
#: the eight ``20260904`` / ``20260816`` / ``20260820`` recency sentences the rule was written for.
#:
#: (3) EVERY WORKED EXAMPLE IN THIS LITERAL OBEYS THE RULE IT ILLUSTRATES. Round 1's quorum example was
#: "two of the pattern's conditions are met, so it is not in force" -- a count of conditions that named
#: none of them, i.e. the construction the rule exists to remove, offered to the writer as the model
#: sentence. The example now NAMES the conditions, and every digit run printed anywhere in this literal
#: (2022, 2012, MY2026) is one its own date rule permits. Both are pinned mechanically.
#:
#: (4) THE ANAPHOR IS REPAIRED (round-1 review MAJOR 3). The exchange-name paragraph was wedged between
#: "is the market's own name and stays exactly as written" and "So are the other phrases...", so "So
#: are" took a BAN clause as its antecedent and the five exempt idioms attached to it. The two-listing
#: paragraph now follows "Write any of those exactly as a desk writes them" and restates its own
#: subject, so neither sentence depends on the other's position.
SYSTEM_DESK_REGISTER_MANDATE = (
    "REGISTER: you are writing for a commodity desk, so write about the MARKET and never about the "
    "instrument that produced the reading. The blocks above are working notes to you; their words are "
    "not the reader's words. Do not tell the reader what you are reading from -- no naming of the "
    "board, the graph, a state read, a series key, a node, a knowledge date, a convention, a receipt, "
    "a row or a walk, and no calling a reading loud. Say the market thing instead: {table}. A named "
    "exchange, institution or commodity board is the market's own name and stays exactly as written -- "
    "the CBOT soybean board, the board crush, the Malaysian Palm Oil Board, the Chicago Board of Trade. "
    "So are the other phrases that only LOOK like our words: the desk convention (and a market, trade, "
    "delivery or contract convention), row crops, warehouse and delivery receipts and the receipt OF "
    "something, and the named chart and port idioms. Write any of those exactly as a desk writes them. "
    "A NAMED EXCHANGE OR INSTITUTION is the market's own name only when the exchange or the "
    "institution is actually named with it: the CBOT soybean board is how a desk writes it and a bare "
    "wheat board is not -- that one reads as the old single-desk marketing monopoly rather than as "
    "Chicago wheat, so write Chicago wheat or the CBOT wheat contract. Where two listings are in play, "
    "name them -- CBOT and ZCE, Chicago and Dalian -- or write each exchange's own currency; writing "
    "'on each board' is the instrument's own word wearing a quantifier, and no desk says it. "
    "Everything else the blocks "
    "name, name in the reader's words: give the "
    "figure, its unit, the market it belongs to and the date it was read through, and let those stand "
    "as the reason. Keep every citation "
    "handle exactly where it is; changing a word never changes a figure. "
    "TWO MORE RULES, BOTH ABOUT HOW A FACT IS SPELLED AND NEITHER ABOUT WHICH FACT. A PATTERN IS "
    "NAMED BY ITS CONDITIONS AND NEVER BY ITS SCORE: say which conditions this market is meeting, in "
    "the market's own words, and whether the pattern is in force -- the crush margin is wide and the "
    "meal basis is firm, two of its conditions are met, and it is not in force -- but do not print the "
    "number a pattern needs to fire, and do not print the size of the roster it draws from, because a "
    "reader shown a score and not a condition can check neither. THAT IS A RULE ABOUT SCORING "
    "MACHINERY AND NOT ABOUT COUNTING: a count in words is a fact about the market and is owed to the "
    "reader wherever the blocks give one -- how many other markets carry the same state and which way "
    "each of them leans, and how many such cases the record holds behind a like-state reading. AND "
    "EVERY CALENDAR DATE YOU PRINT IS SPELLED THE WAY A DESK SPELLS ONE -- an ISO date, or the day and "
    "the month written out -- never as the year, the month and the day run together with no "
    "separators, whatever spelling the notes above happen to carry. A YEAR STANDING ALONE AND A "
    "MARKETING YEAR ARE NOT CALENDAR DATES AND STAY EXACTLY AS THEY ARE: since 2022, in 2012, MY2026."
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
    "about the layer it names, and none of them dating the answer as a whole. Where the blocks above "
    "or the movement that asks for this reach for a knowledge date or a number row, those are the "
    "blocks' words and not yours: write the newest number behind this page was known, and then the "
    "date, in the same desk spelling every other date on the page wears."
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


#: COHERENCE AUDIT 2026-09-16 (WP-A2) -- THE MANDATE'S MOVEMENT (4) DESCRIBES THE PRE-RULING WATCH.
#: :data:`SYSTEM_STATE_BOARD_MANDATE` closes with "the WATCH rows -- the next scheduled print, the level
#: a convention names, the date a declared lag window opens -- as concrete items with their dates".
#: Under ``GRAPHRAG_WATCH_NONOBVIOUS`` the ``next_release`` kind is BANNED AT NOMINATION
#: (``state/watch.py:475-479``: "NO RELEASE-CALENDAR ITEM ... the scheduled prints are named ONCE, in a
#: single dated footnote outside the ceiling") and ``release_footnote`` renders them as an ABSENCE-class
#: line; none of the seven ``NONOBVIOUS_KIND_WORDS`` is "the next scheduled print". So on a lit turn the
#: mandate asked for the one class the producer refuses, and the ranked convex nominations fell off the
#: ceiling to make room for WASDE dates every desk already has.
#:
#: AND "CLOSE WITH THE WATCH ROWS" IS DENIED BY ITS OWN NEIGHBOUR. ``WATCH_SELECTION_CLAUSE`` ships on
#: the SAME turn and opens "The WATCH items are CANDIDATES nominated for you, NOT A LIST TO REPRODUCE."
#: The mandate told the writer to reproduce them.
#:
#: IT IS A SUBSTITUTED SENTENCE ON A FLAG THAT ALREADY EXISTS, never an edit to the mandate: the mandate
#: literal is board-gated, and a board turn with the watch flag OFF must keep HEAD's bytes. TWO DEFECTS
#: THAT LIVE AT HEAD ARE DELIBERATELY NOT TOUCHED HERE, because touching them would move flag-off prompt
#: bytes on every board turn -- (a) the parenthetical names only THREE of the five HEAD ``KIND_WORDS``,
#: omitting ``analog_trigger`` and ``policy_date``, and (b) "close with THE WATCH ROWS" reads as
#: reproduce even with the watch flag off. Both are docketed.
MANDATE_WATCH_HEAD_RX: str = (
    "(4) WATCH: close with "
    "the WATCH rows -- the next scheduled print, the level a convention names, the date a declared lag "
    "window opens -- as concrete items with their dates; never a generic caution."
)
MANDATE_WATCH_NONOBVIOUS: str = (
    "(4) WATCH: close with "
    "the items the block nominates, and give each one you keep its mechanism, the dated reading it "
    "rests on and the reading that would show it wrong, as concrete items with their dates; never a "
    "generic caution. Where nothing cleared the bar, say so plainly rather than filling the space. The "
    "scheduled prints are NOT watch items here; the block names them once, in its own dated note, and "
    "that note is where they stay."
)


def state_board_mandate(nonobvious: bool = False) -> str:
    """:data:`SYSTEM_STATE_BOARD_MANDATE`, with movement (4) restated for the NON-OBVIOUS watch draw.

    ``nonobvious`` is ``answer._system``'s own ``watch_selection`` bool -- the flag AND the block's own
    marker -- so the writer is never told to narrate nominations the board did not draw. DEFAULT FALSE,
    which is HEAD's literal byte for byte and is what every board turn with the watch flag off ships.

    THE NEEDLE IS ASSERTED, for ``response_contracts.apply``'s stated reason: a reworded mandate must
    red loudly here rather than quietly stop being corrected on the one lane that needs it."""
    if not nonobvious:
        return SYSTEM_STATE_BOARD_MANDATE
    assert MANDATE_WATCH_HEAD_RX in SYSTEM_STATE_BOARD_MANDATE, (
        "narration: the mandate's WATCH movement was reworded and the non-obvious variant's needle no "
        "longer matches -- re-cut MANDATE_WATCH_HEAD_RX beside it")
    return SYSTEM_STATE_BOARD_MANDATE.replace(MANDATE_WATCH_HEAD_RX, MANDATE_WATCH_NONOBVIOUS)


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
#: **UNSHIPPED AS A SENTENCE** (coherence audit 2026-09-16, WP-A9): nothing in ``src/`` calls
#: :func:`recency_ledger` or renders this template -- the SB-L lines a reader actually meets are
#: :func:`recency_rows`' three, minted at ``state/seam.py:395``, and ``register.py:1089`` cites this
#: name for the WORDS the writer is told to write (the tape line), not for a call site. It is the
#: prose-ledger form of the same three facts and is graded at build like every other literal here; a
#: correction to the SHIPPED tape line belongs in :func:`recency_rows`.
#:
#: The then/now design's sentence 5c (i), which EXTENDS ``_recency_ledger_suffix`` (answer.py:1799).
#: THREE EDGES, each a fact about the layer it names, and the closing clause states in so many words
#: that none of them dates the others -- which is the whole point: a single "the record here runs
#: through <month>" sentence has THE ANSWER as its subject and can be inflated into "not a current-state
#: read", and neither sentence here has a subject that permits that reading.
#: PRE-ARM ROUND 1 (2026-09-17) -- REWORDED OFF THE INSTRUMENT'S OWN VOCABULARY. It scored `row` x2 +
#: `knowledge date` x1 on `register.count_desk_register`, which is the estate's own reference text
#: teaching the three words the mandate beside it bans. It is the PROSE form of :func:`recency_rows`'
#: three lines and it is reworded in the same sitting and the same shape, so the two producers still
#: say one thing. `newest number` is deliberate: it is a member of `render._RECENCY_LAYER_WORDS`
#: ("numbers"), so a writer who copies this sentence still scores `recency_referenced` -- four of that
#: tuple's seven accepted phrasings are desk-clean and this is one of them. The tape clause is
#: UNTOUCHED: `config_check` probes "the board price tape runs through 2026-09-04" by name as the ONE
#: exempt sibling, and the mandate's movement (2) instructs the writer to produce it.
#: PRE-ARM ROUND 3 (2026-09-17), review MAJOR 3 -- THE SAME BROKEN FALLBACK AS THE SHIPPED SB-L LINE,
#: AND IT IS FIXED THE SAME WAY: BY REVERTING TO HEAD'S PREDICATE. Round 1 spelled the clause "the
#: newest number IS KNOWN {kd_max}", and :func:`recency_ledger` fills a missing edge with the plain
#: words "not carried on this page" -- so an edge-less layer printed "the newest number is known not
#: carried on this page", which is not a sentence. HEAD's predicate ("the newest is {kd_max}") survives
#: the fallback; the one word this keeps from round 1 is `number`, because
#: `render._RECENCY_LAYER_WORDS["numbers"]` scores `newest number` and the retired `newest knowledge
#: date` is the wording the mandate beside it bans. NOTHING ELSE in the literal moves, and it is
#: UNSHIPPED (WP-A9), so this changes no served byte on any flag.
RECENCY_LEDGER_SENTENCE = (
    "The figures on this page are read as of {asof}, and each carries the date it was known; the "
    "newest number is {kd_max} and the oldest {kd_min}. The newest dated document behind this "
    "answer is {record_through}. The board price tape runs through {tape_edge}. Each of those is a "
    "fact about the layer it names, and none dates the others."
)

#: ``_SYSTEM_RECENCY``'s replacement clause (sec 6.5 (3)). It replaces the shipped sentence whose
#: subject is the ANSWER; both of these have a CLAIM as their subject, so neither can be read as a
#: verdict on the answer as a whole.
#:
#: **UNSHIPPED -- IT REACHES NO WRITER, AND IT HAS ALREADY DIVERGED FROM THE ONE THAT DOES**
#: (coherence audit 2026-09-16, WP-A9). MEASURED: nothing in ``src/`` reads this name except
#: :func:`check_literals`' own roster below; the only other readers are
#: ``tests/unit/test_state_render.py:548-549`` and ``tests/unit/test_state_seam.py:317``. WHAT SHIPS is
#: ``answer._SYSTEM_RECENCY_EDGE_FACTS`` (answer.py:3036-3040) -- this text PLUS "and the as-of is the
#: question's 'today'", an addition answer.py:3028-3031 documents as deliberate ("a FACT ABOUT A THIRD
#: LAYER ... folded into the ledger sentence rather than deleted"). SO: a correction made HERE changes
#: no prompt byte. Make it at ``answer._SYSTEM_RECENCY_EDGE_FACTS``, which is inside
#: ``_SYSTEM_RECENCY_FACTS`` and rides GRAPHRAG_RECENCY_FACTS. This constant is kept, not deleted,
#: because it is the design's own wording and the build grades it under all four register detectors --
#: it is a reference text, and it is labelled one.
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
    a date the reader could not see.

    EVERY DATE GOES THROUGH :func:`iso_date` (pre-arm round 1): this sentence's whole job is to state a
    vintage, and a vintage stated as ``20260904`` is the one the PM lens refused outright."""
    none_words = "not carried on this page"
    return RECENCY_LEDGER_SENTENCE.format(
        asof=iso_date(asof) or none_words, kd_max=iso_date(kd_max) or none_words,
        kd_min=iso_date(kd_min) or none_words,
        record_through=iso_date(record_through) or none_words,
        tape_edge=iso_date(tape_edge) or none_words)


#: A DATE THE ESTATE'S PRODUCERS ACTUALLY HAND THIS MODULE, in every spelling they hand it in. The ESR
#: rows carry ``20260904`` with no separators; the PSD and WASDE rows carry ``2026-09-11``; the monthly
#: climate rows carry ``2026-07``. `_DATE_YMD` and `_DATE_YM` are the two undelimited ones.
_DATE_YMD = re.compile(r"^(\d{4})(\d{2})(\d{2})$")
_DATE_YM = re.compile(r"^(\d{4})(\d{2})$")


def iso_date(value) -> str:
    """ONE date in ONE spelling -- the spelling a reader reads and a ``max()`` can be trusted with.

    THIS IS THE FIX FOR A MEASURED, TEN-DAY-WIDE LIE (in-VPC pre-arm smoke 2026-09-16, two turns). The
    served answers read "the newest knowledge date on a number row 20260904" while nine cited rows on
    the same page were known 2026-09-11..15, and both grader lenses found the mechanism before this
    module did: the newest date is chosen by a LEXICAL ``max`` over MIXED SPELLINGS, and ``"20260904"``
    sorts above ``"2026-09-14"`` because ``-`` (0x2D) sorts below ``0`` (0x30). The same mixture is why
    a bare run of digits reached reader prose at all -- the fact grader, verbatim: "a lexical max over
    mixed date spellings ... which also explains why an unformatted date reached the reader's prose".

    SO THE SPELLING IS NORMALISED BEFORE THE COMPARISON AND NOT ONLY BEFORE THE PRINT. A print-side fix
    alone would spell the WRONG date correctly, which is worse than the defect it replaces.

    IT NEVER INVENTS PRECISION. A month-precision date stays month-precision (``202607`` -> ``2026-07``)
    rather than acquiring a day, and an unparseable value is RETURNED AS GIVEN rather than guessed --
    :func:`age_clause`'s own rule, one function up. Because a month-precision string sorts BELOW every
    day-precision string inside the same month, a mixed-precision pool understates freshness and
    overstates age, which is the safe direction on both ends."""
    s = str(value or "").strip().split("T")[0].split(" ")[0]
    if not s:
        return ""
    m = _DATE_YMD.match(s)
    if m:
        y, mo, d = m.groups()
        try:
            _dt.date(int(y), int(mo), int(d))
        except ValueError:
            return s                                    # not a date: return it, never guess
        return f"{y}-{mo}-{d}"
    m = _DATE_YM.match(s)
    if m and 1 <= int(m.group(2)) <= 12:
        return f"{m.group(1)}-{m.group(2)}"
    return s


def knowledge_edges(bd, extra_kd=()) -> tuple:
    """(newest, oldest) knowledge date across EVERY reading this page can see, normalised to ISO.

    THREE POOLS, UNIONED, AND THAT IS THE SECOND HALF OF THE SAME DEFECT. ``bd.recency["numbers"]`` is
    a max over ``bd.series`` alone -- the BOARD's own series map -- while the reader's footer also
    carries the rows the NUMBERS AGENT looked up, which the board never saw. On the max turn nine cited
    rows were newer than the date the sentence declared newest. ``extra_kd`` is how a caller that holds
    the served footer (the seam, or ``answer.py``) hands those dates in; it defaults to empty, so a
    caller that passes nothing gets exactly the board's own pool and nothing is invented for it.

    THE BOARD'S OWN PRECOMPUTED EDGE IS KEPT IN THE POOL rather than replaced, because a producer
    upstream may know an edge this map does not carry -- but it is normalised like every other member,
    so it can no longer win the comparison by being spelled without separators.

    ``extra_kd`` TAKES THE FOOTER'S OWN MEMBERS: a date string, a SERVED-ROW DICT, or a ``Citation``.

    THERE IS EXACTLY ONE COLUMN EXTRACTOR IN THE ESTATE AND IT IS NOT HERE (pre-arm round 3, review
    MAJOR 1). Round 2 read a served row off a four-name tuple of its own (``knowledge_date``,
    ``data_date``, ``known``, ``date``) and CLAIMED those were "the same four columns in the same order
    as ``citations._row_known_date``". They were not, and the drift was already costing:
    ``citations._row_known_date`` reads ``knowledge_date``, ``data_date`` and THEN THE ROW'S OWN
    ``(year, month)`` as ``YYYY-MM``, and it reads neither ``known`` nor ``date``. The (year, month)
    branch is the whole climate class -- ``silver_noaa_oni``, ``silver_noaa_iod``, ``gold_weather_z``
    carry no date column at all (``citations.py:290-312``) -- and it is ON THE SERVED PAGES: the deep
    smoke body's footer carries four month-only stamps and its OLDEST row is ``[known 2011-04]``. A
    second extractor that dropped it would have produced ``2012-04-10`` as the page's oldest: a
    twelve-month error in the unsafe direction, in the one sentence whose whole job is the page's
    vintage. So the dict branch CALLS ``citations._row_known_date`` and a ``Citation`` is read off its
    ``.date``, which ``citations.py:2022`` has already filled from that same function.

    AN UNREADABLE MEMBER CONTRIBUTES NOTHING rather than raising: this is on the render path of every
    board turn, and a ledger that refused to print because one row carried an odd type would be a worse
    failure than the ten-day error it exists to close. THE IMPORT IS LAZY AND GUARDED for the same
    reason plus one more -- ``state/``'s law #1 is that it never raises, and this module must keep no
    import-time dependency on ``citations`` (``citations._series_truncated``'s own precedent, one file
    over, guard included). A caller that passes nothing never reaches the import at all."""
    pool = {iso_date(bd.recency.get("numbers"))}
    for st in getattr(bd, "series", {}).values():
        pool.add(iso_date(getattr(st, "knowledge_date", "")))
    rows = list(extra_kd or ())
    if rows:
        try:
            from leviathan.graphrag.citations import _row_known_date
        except Exception:                               # noqa: BLE001 -- unimportable citations means a
            _row_known_date = None                      # dict says nothing, never a turn taken down
        for kd in rows:
            if kd is None:
                continue
            if isinstance(kd, str):
                pool.add(iso_date(kd))
                continue
            try:
                if isinstance(kd, dict):
                    v = _row_known_date(kd) if _row_known_date is not None else None
                else:
                    v = getattr(kd, "date", None)       # a Citation: `.date` IS `_row_known_date(row)`
            except Exception:                           # noqa: BLE001 -- an odd row contributes nothing
                v = None
            pool.add(iso_date(v or ""))
    pool.discard("")
    return (max(pool) if pool else "", min(pool) if pool else "")


def recency_rows(bd, *, kd_min: str = "", record_through: str = "", tape_edge: str = "",
                 extra_kd=()) -> dict:
    """The three SB-L lines (sec 6.2, 6.5 (2)) as ``{layer: text}``, in the design's own layer order.

    THREE SEPARATE ROWS AND NOT ONE SENTENCE, because the render's SB-L class is per layer and because a
    reader who meets three dated facts cannot fold them into one verdict about the page. The ledger
    SENTENCE above is the same three facts for the prose ledger; both come from this one producer.

    PRE-ARM ROUND 1 (2026-09-17), and the two halves are separate changes to one line.
    THE FACT: the edges are COMPUTED by :func:`knowledge_edges` over a normalised union instead of
    transcribed from one lexically-sorted subset -- see that function for the measured ten-day error.
    THE WORDS: "the newest knowledge date on a number row is ..." was the block's ONLY source of
    `knowledge date` and of three of the seven `row` charges on the five served bodies -- the writer
    transcribed it on three turns. It is reworded to the phrasing ``config_check``'s own exemption note
    names as the intended one ("the newest date on these numbers is ..."), spelled with `newest number`
    so `render._RECENCY_LAYER_WORDS["numbers"]` still scores the layer. THE TAPE LINE DOES NOT MOVE:
    `config_check` probes it verbatim as the one exempt sibling and the mandate instructs it.

    PRE-ARM ROUND 3 (2026-09-17), review MAJOR 3 -- THE DEGENERATE BRANCHES, WHICH NO PIN REACHED.
    The round-2 reword folded the words into the SENTENCE and left the FALLBACK inside the slot, so a
    board with no number date at all printed "the newest number here is known not carried on this
    page" -- not a sentence, inside a block the mandate tells the writer to transcribe. The fallback is
    HEAD's again: it replaces the PREDICATE, so the empty branch is grammatical, and it still carries
    `newest number` so the layer keeps scoring.
    AND THE OLDEST CLAUSE NO LONGER STATES AN EDGE THE BOARD DOES NOT HOLD. `knowledge_edges` keeps
    `bd.recency["numbers"]` -- a MAX -- in the pool it takes a MIN over, so a board whose series map
    carried no date printed "and the oldest <the newest>": a fabricated edge, and exactly the class
    ROUND2_DOCKET #8 names. The derived min is printed only when it is a real date DISTINCT from the
    max; a kd_min the CALLER states is its own fact and prints as given."""
    text = str(bd.recency.get("text") or record_through or "")
    # THE OLDEST KNOWLEDGE DATE IS DERIVED FROM THE BOARD when the caller does not state one. It is on
    # the ledger sentence by name ("the newest is {kd_max} and the oldest {kd_min}") and a caller who
    # had to compute it would be a second producer of a fact the board already holds.
    kd_max, derived_min = knowledge_edges(bd, extra_kd)
    oldest = iso_date(kd_min) or (derived_min if derived_min != kd_max else "")
    # ROUND-2 MINOR 1: THE AS-OF GOES THROUGH THE SAME NORMALISER AS EVERY OTHER DATE ON THE LINE.
    # It was the one date on the SB-L line printed raw, so a producer handing an undelimited as-of
    # would have the block print, in the reader's own prose, the exact spelling the mandate beside it
    # now forbids -- from the block the writer is told to transcribe. `iso_date` declines rather than
    # guessing, so a value it cannot read prints exactly as it printed before.
    newest = (f"the newest number here is known {kd_max}" if kd_max
              else "the newest number here is not carried on this page")
    numbers = (f"read as of {iso_date(bd.asof)}; {newest}"
               + (f" and the oldest {oldest}" if oldest else ""))
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
    # COHERENCE AUDIT 2026-09-16 (WP-A2): the NON-OBVIOUS mandate variant is a shipped literal the
    # moment GRAPHRAG_WATCH_NONOBVIOUS is lit, so it is graded here by the same four register
    # detectors, the same ASCII rule and the same banned recency phrase as the mandate it replaces --
    # the `desk_register_mandate(state_board=True)` precedent one block up: grade the WIDEST text that
    # can ship, because a register trip in a flag-scoped literal is a BUILD failure and never a
    # stripped answer at serve time.
    try:
        _watch_mandate = ("SYSTEM_STATE_BOARD_MANDATE[nonobvious]", state_board_mandate(nonobvious=True))
    except Exception as exc:                        # noqa: BLE001 -- named, never raised onward
        errs.append(f"narration: could not render state_board_mandate(nonobvious=True): {exc}")
        _watch_mandate = ("SYSTEM_STATE_BOARD_MANDATE[nonobvious]", "")
    for name, text in (("SYSTEM_STATE_BOARD_MANDATE", SYSTEM_STATE_BOARD_MANDATE),
                       _watch_mandate,
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
        for _n, _t in (("SYSTEM_STATE_BOARD_MANDATE", SYSTEM_STATE_BOARD_MANDATE),
                       _watch_mandate, _desk):
            if _t and not pace_register_ok(_t):
                errs.append(f"narration.{_n}: pace_register_ok is False")
    except Exception as exc:                        # noqa: BLE001 -- named, never raised onward
        errs.append(f"narration: could not run pace_register_ok: {exc}")
    for _n, _t in (("SYSTEM_STATE_BOARD_MANDATE", SYSTEM_STATE_BOARD_MANDATE),
                   _watch_mandate, _desk):
        if BANNED_RECENCY_PHRASE in _t:
            errs.append(f"narration.{_n}: carries the banned recency phrase")
    return errs
