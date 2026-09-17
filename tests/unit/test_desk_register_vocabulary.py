"""PRE-ARM ROUNDS 1-2 (2026-09-17) -- THE DESK REGISTER'S VOCABULARY: the replacement column, the new
mandate rules, and the recency line that stopped teaching the words it bans.

WHY THIS DECK EXISTS, AND IT IS A MEASUREMENT AND NOT AN OPINION. The in-VPC pre-arm smoke of 2026-09-16
served five real turns with every treatment flag lit and shipped **24 pure-lint hits** over the five
served bodies (`register.count_desk_register` over the `tldr` + `mechanism` fields, which is
`eval.py:3696-3710`'s own scope): `board` 10, `row` 7, `loud` 4, `knowledge date` 3. Two independent
grader lenses read the same five pages and scored them 2/5 (PM) and 1/5 (fact) -- and each of the four
words was named by hand, with its replacement.

TWO CORPORA, AND ROUND 2 STOPPED CONFLATING THEM (round-1 review MAJOR 5). `SMOKE_CHARGED` is **THIS
LANE'S CASE LIST**: the five served bodies are the prose every edit in `register.py` and
`state/narration.py` was written against, quoted throughout `A_BUILD.md` as the motivation. They are
unseen to the TABLE that shipped at `5c45f3e6` and that is all they are unseen to; round 1's docstring
called them a negative corpus, which is exactly the shape
`feedback_negative_corpus_must_be_unseen_prose` was written after.

`BANKED_UNSEEN` IS THE NEGATIVE CORPUS: sentences from the 14 banked real-seat answers lane B's
reviewer replayed (`scratchpad/writer_board_use/`, `scratchpad/recency_smoke/`,
`scratchpad/s7_prearm/smoke/`), written by earlier seats on earlier boards, read by no one in this
lane until the rules were already drafted. The two new mandate rules are graded against it here, and
the whole 485-sentence corpus is graded by `scratchpad/prearm_fix_r2/A2_rule_reach.py` (case list
included), whose numbers this deck's own thresholds come from.

The CLEAN corpus is the estate's own already-exempt prose, so a rule that over-reached would red here
rather than in a served answer.

WHAT IS *NOT* PINNED HERE, deliberately: a `board` EXEMPTION. The threat model's A.8 recommended one
(`\\bboards\\b` plus the distributive quantifiers) that would have cleared 7 of the 24. The owner's
ruling is the opposite -- the ban is right and the REPLACEMENT was wrong -- so this deck pins that
"each board's own currency" is still CHARGED and that the table now teaches the words that make the
sentence writable without it.
"""
from __future__ import annotations

import re

import pytest
from leviathan.graphrag import answer as an
from leviathan.graphrag import register as reg
from leviathan.graphrag.state import narration as N
from leviathan.graphrag.state import render as R

# ══════════════════════════════════════════════════════════════════════════════════════════════════
# THE CORPUS -- five served bodies, 2026-09-16, verbatim
# ══════════════════════════════════════════════════════════════════════════════════════════════════
#: (the served sentence, the token it must still be charged for, which turn it came from).
SMOKE_CHARGED = (
    ("the direction is read on each board's own-currency move", "board", "deep"),
    ("read on each board's own-currency move (US dollars and Chinese yuan)", "board", "max"),
    ("again read in each board's own currency with no rate applied.", "board", "max"),
    ("the model gives it opposite signs on each board by phase", "board", "corn/wheat"),
    ("No front delivery month could be named on either board this session", "board", "corn/wheat"),
    ("carries the palm-soyoil premium at high confidence on BOTH boards", "board", "soyoil"),
    ("it predates those boards' own price history", "board", "deep"),
    ("The board leans both ways, and the two legs are not the same weight.", "board", "deep"),
    ("are among this board's largest moves", "board", "palm/rape"),
    ("the channel the model signs as price-pressuring for the US board.", "board", "deep"),
    ("On corn the loud, high-confidence rows lean opposite ways", "loud", "corn/wheat"),
    ("three of its drivers among the loudest readings against a threshold of two", "loud", "deep"),
    ("The same loud state is declared on two other markets the model tracks", "loud", "palm/rape"),
    ("only two of the loudest readings here belong to it", "loud", "soyoil"),
    ("several stocks-to-use and feed-use lookups returned no rows at all at this as-of", "row",
     "corn/wheat"),
    ("Corn's own high-confidence rows point opposite ways", "row", "corn/wheat"),
    ("No CME palm oil price row is served this session", "row", "palm/rape"),
    ("The number rows run through 2026-09-15", "row", "palm/rape"),
    ("the number rows are read as of 2026-09-16", "row", "corn/wheat"),
    ("The newest number carries a knowledge date of 20260904;", "knowledge date", "deep"),
    ("with the newest knowledge date on a number row 20260904 and the oldest 2026-05-31",
     "knowledge date", "max"),
    ("with the newest knowledge date 20260904 and the oldest 2026-08-12", "knowledge date",
     "corn/wheat"),
)

#: The prose that must stay CLEAN -- the estate's own exempt literals and desk English. Every one of
#: these is probed by `config_check.check_register_seam` (f) or is a shipped `render.py` /
#: `narration.py` sentence the writer is INSTRUCTED to produce.
CLEAN = (
    "the board price tape runs through 2026-09-04",
    "It sits past the line the desk convention calls tight.",
    "A wide board crush means processors bid for beans.",
    "The CBOT soybean board tilts higher.",
    "Row crops went in late.",
    "Registered receipts fell again.",
    "Source: Malaysian Palm Oil Board - Monthly Palm Oil Statistics, 2026-09-10.",
    "The Chicago Board of Trade settles at noon.",
)

# ══════════════════════════════════════════════════════════════════════════════════════════════════
# THE UNSEEN CORPUS -- the 14 BANKED real-seat answers (round-2 review MAJOR 5, and F1's re-measure)
# ══════════════════════════════════════════════════════════════════════════════════════════════════
#: NOT THIS LANE'S CASE LIST. Every string below is verbatim from a banked answer an earlier seat
#: served on an earlier board (`scratchpad/writer_board_use/smoke_real|smoke_s6b/turns/*.text.txt`,
#: `scratchpad/recency_smoke/*.text.txt`, `scratchpad/s7_prearm/smoke/turns/*.text.txt`), truncated at
#: a clause boundary and never edited. Round 1 wrote its two mandate rules without reading them.
#:
#: THE PATTERN'S OWN SCORE -- what the round-2 quorum rule is FOR. Each of these prints a threshold
#: NUMBER or the SIZE of a roster, which is the construction the PM lens called "scoring machinery
#: quoted verbatim ... unfalsifiable as served".
BANKED_SCORING = (
    "Coverage: the price-supportive West African deficit pattern needs three of its six drivers; only "
    "Harmattan sits among the loudest rows, so the pattern is one-of-three, not triggered.",
    "A price-supportive demand-pull pattern has five of its eight drivers among the loudest rows "
    "against a threshold of three.",
    "The weather-squeeze pattern, by contrast, has zero of its seven drivers among the loudest rows.",
    "The supply glut pattern has two of five against a threshold of three.",
    "Against it, the trade-war demand-loss pattern also clears its threshold of two.",
    "The board flags the demand-pull pattern with five of its eight drivers among the loudest rows "
    "against a threshold of three, with crude and ethanol amplifying each other.",
    "The tipping condition for convexity: the squeeze pattern needs three of its six drivers and has "
    "one, so watch for arrivals lagging and deliverable stocks drawing down to join dryness.",
)

#: A COUNT IN WORDS -- what `SYSTEM_STATE_BOARD_MANDATE` REQUIRES on the same turn, movement (2) ("how
#: many such cases the record carries, in words"), movement (3) ("name the other markets") and "Base
#: rates come from the block's count words". The desk leg is appended LAST (`answer.py:3682` after
#: `:3656`), so a desk rule that reached one of these would be the instruction that wins.
BANKED_COUNT_IN_WORDS = (
    "History, not forecast: the record carries thirty-three crossings of this low-stocks state "
    "since 2006.",
    "Like state, February 2024: the record carries three such crossings since 2022.",
    "Like-state history: the record carries six crossings of this Brazilian export-levy state "
    "since 1977.",
    "Demand. Crush pull is price-supportive and clears its threshold; export pace is "
    "price-pressuring and clears its threshold.",
    "The reading sits 0.02 degC under the moderate line at 1 degC as of 2026-08-31 -- that is the "
    "threshold to watch, because crossing it is where the desk convention changes label.",
)

#: THE UNDELIMITED DATE -- what the round-2 date rule is FOR, on seats this lane never read. The same
#: defect, two boards and three months earlier: the year, the month and the day run together in the
#: one sentence whose entire job is to state a vintage.
BANKED_UNDELIMITED_DATE = (
    "No dated documents sit behind this page: the newest knowledge date on a number row is 20260816, "
    "the oldest 2026-07-06.",
    "The newest knowledge date on any number row is 20260820, the oldest 2026-05-31; the crush "
    "reading is read through 2026-08-21, a 17-day span to this as-of.",
    "Recency, layer by layer: the newest knowledge date on any number row is 20260816 and the oldest "
    "is 2026-07-06.",
)

#: A BARE YEAR, A MARKETING YEAR AND A PRINTED VALUE -- the 242 tokens of 250 that round 1's date rule
#: reached and is not about. `MY2026` is from the case list's own PSD card prose; the rest are banked.
BANKED_PLAIN_YEAR = (
    "History for this ocean state: the series sat like this once since 2022, in February 2024.",
    "Offsetting: US planted area at 35852 M ha [N13], 98th percentile [N15], which loosens supply on "
    "a high-confidence edge.",
    "The stocks-to-use ratio for MY2026 sits at 10.72 percent on the PSD balance.",
    "It predates the 2012 change and reads on the same series today.",
)

#: EVERY REPLACEMENT PHRASE THE COLUMN TAUGHT AT `5c45f3e6`, as `answer._desk_replacement_phrases`
#: parses it -- the baseline two pins read: nothing HEAD taught may be lost, and every stem HEAD's
#: column earned stays allowed.
_HEAD_PHRASES = {
    "board": [["the", "market"], ["the", "data", "as", "of", "date"]],
    "row": [["the", "record"], ["this", "series"], ["the", "latest", "print"]],
    "the graph": [["the", "mechanism"], ["the", "driver", "model"]],
    "loud": [["the", "largest", "move"],
             ["the", "reading", "furthest", "from", "its", "own", "record"]],
    "knowledge date": [["read", "through", "date"], ["as", "of", "date"],
                       ["an", "older", "reading", "when", "it", "is", "one"]],
}


@pytest.mark.parametrize("sent,token,turn", SMOKE_CHARGED,
                         ids=[f"{t}-{i}" for i, (_s, t, _t) in enumerate(SMOKE_CHARGED)])
def test_every_smoke_residue_sentence_is_still_charged(sent, token, turn):
    """THE BAN IS RIGHT AND STAYS RIGHT, on all 22 sentences the smoke actually served.

    The owner's ruling on the seven `each board` / `either board` / `both boards` charges, which the
    threat model proposed to exempt: the PM lens refused the exemption by refusing the word --
    "'the wheat board' is not how a trader refers to Chicago wheat, and for anyone with grey hair it
    collides with the Canadian Wheat Board, a marketing monopoly that ceased to exist in 2012." The
    remedy is a word the writer did not have, not a licence for the one it reached for."""
    hits = reg.desk_register_hits(sent)
    assert any(n == token for n, _c in hits), (turn, sent, hits)


@pytest.mark.parametrize("sent", CLEAN)
def test_the_estates_own_exempt_prose_stays_clean(sent):
    """The table did not move, so neither may these -- and a future exemption edit reds here first."""
    assert reg.count_desk_register(sent) == 0, reg.desk_register_hits(sent)


def test_no_exemption_row_was_added_for_the_non_unique_board():
    """A.8's recommended row is NOT shipped, and the pin says so by name rather than by absence: a
    later sitting that adds it must delete this test and argue for it in the open."""
    pats = [p for p, _names, _why in reg.DESK_REGISTER_EXEMPT]
    for banned in (r"\bboards\b", "each|either|neither|every|both|per|any"):
        assert not any(banned in p for p in pats), banned
    assert reg.count_desk_register("read on each board's own-currency move") == 1


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# THE REPLACEMENT COLUMN -- the words a PM uses
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_the_replacement_column_teaches_the_exchange_words_the_smoke_needed():
    """"the market" alone cannot carry a sentence about TWO listings, which is where seven of the ten
    `board` charges came from. The column now carries the words that can."""
    repl = dict((n, r) for n, _p, r in reg.DESK_REGISTER_TOKENS)
    for word in ("the exchange", "the contract", "in its own currency"):
        assert word in repl["board"], repl["board"]
    # ...and `the market` is KEPT, because `answer._desk_allowed_stems` reads this column and the
    # rewrite already spends that word successfully ("not just its own board" -> "... its own market",
    # accepted on the palm/rape turn). Dropping a word here withdraws it from the remedy.
    assert "the market" in repl["board"]


def test_the_knowledge_date_row_finally_offers_a_NOUN_phrase():
    """The docket `test_state_narration.py:175-181` opened in so many words: "the `knowledge date` row
    of the table offers no NOUN-PHRASE replacement ... so a `knowledge date` charge in a noun slot has
    no accepted rewrite at all. The one-line remedy is a TABLE edit"."""
    repl = dict((n, r) for n, _p, r in reg.DESK_REGISTER_TOKENS)["knowledge date"]
    assert "the date it was known" in repl                     # a NOUN phrase, at last
    assert "known <date>" in repl                              # the footer's own stamp: [known 2026-09-11]
    # ...and the SPELLING rule lives in the mandate PROSE, never in this column: the column is parsed
    # into PHRASES on `,` / ` or ` alone, so a rule joined on here is swallowed into the phrase beside
    # it. Measured on the first draft of this very row -- see `test_no_HEAD_replacement_phrase_was_lost`.
    assert "never as bare digits" not in repl
    assert ("never as the year, the month and the day run together with no separators"
            in N.desk_register_mandate())


def test_no_HEAD_replacement_phrase_was_lost():
    """THE COLUMN IS A LIST OF PHRASES, AND `answer._desk_replacement_phrases` IS ITS PARSER.

    THE DEFECT THIS PIN CLOSES WAS THIS LANE'S OWN, caught before it shipped. The first draft joined a
    prose rule onto two rows with a SEMICOLON; the parser splits on `,` and ` or ` alone, so `board`'s
    "in its own currency" became part of a fourteen-token string that can never match a substitution,
    and `knowledge date`'s HEAD phrase `an older reading when it is one` -- the one the round-3 note
    MEASURED as the honest rewrite of its own charge -- was swallowed into a fifteen-token one. A
    replacement the parser cannot see is a replacement the writer does not have.

    SO THE INVARIANT IS PARSED, NOT SPELLED: every phrase HEAD taught is still a phrase, token for
    token, and the new ones parse as phrases of their own."""
    now = an._desk_replacement_phrases()
    for name, phrases in _HEAD_PHRASES.items():
        for p in phrases:
            assert p in now[name], (name, p, now[name])
    for p in (["the", "exchange"], ["the", "contract"], ["in", "its", "own", "currency"]):
        assert p in now["board"], (p, now["board"])
    assert ["the", "date", "it", "was", "known"] in now["knowledge date"]
    assert ["the", "signal"] in now["loud"]
    assert ["the", "reading"] in now["row"]


def test_the_loud_row_teaches_the_PM_lens_noun_WITHOUT_its_claim_word():
    """"'loud' and 'rows' are the system talking about its own internals. A desk says 'the two
    strongest signals point opposite ways'." -- PM lens, quick_rv_corn_wheat, major register_leak.

    ROUND 2 (review MAJOR 2) TAKES THE NOUN AND LEAVES THE SUPERLATIVE. Round 1 taught `the strongest
    signal` on the stated ground that "`strongest` is NOT a member of `answer._DESK_CLAIM_RX`'s
    comparative class". IT IS: it is named by hand in the EXTREMITY alternation and `("strongest",
    "weakest")` is a declared `_DESK_CLAIM_ANTONYMS` row -- both asserted below, so the false argument
    cannot be re-made from this file. The column now teaches `the signal`, whose stem is in no claim
    class at all; the writer was never barred from writing "the strongest signal", because `loud` is
    the banned token and `strongest` is not."""
    repl = dict((n, r) for n, _p, r in reg.DESK_REGISTER_TOKENS)["loud"]
    assert "the signal" in repl and "the largest move" in repl
    assert "the strongest signal" not in repl
    assert an._DESK_CLAIM_RX.search("the strongest of them is soybeans")     # it IS a claim word
    assert ("strongest", "weakest") in an._DESK_CLAIM_ANTONYMS               # ...and a declared pair


def test_the_rewrite_still_labels_an_ANTONYM_FLIP_as_a_POLARITY_refusal():
    """THE MEASURED CONSEQUENCE OF MAJOR 2, PINNED AS THE CASE THAT FOUND IT (round-1 review
    `REVIEW_A/r4_flip.py`), because `answer.py:10786` says the refusal map "is read by a human deciding
    what the rewrite is doing wrong" -- a mislabelled refusal is a lie told to a reviewer.

    The reply is REFUSED either way (guard 10 refuses on any claim-multiset difference), so no flip
    ever reached a page. What moved was the WORD on the refusal: with `strongest` inside
    `_desk_allowed_stems()` the census logged `claim` where HEAD logs `polarity`."""
    body = "Only two of the loudest readings here belong to it, and the weakest of them is soybeans."
    cand = "Only two of the largest moves here belong to it, and the strongest of them is soybeans."
    assert an._desk_claim_terms(cand) == ["strongest"], an._desk_claim_terms(cand)
    assert an._desk_claim_terms(body) != an._desk_claim_terms(cand)          # still refused
    assert an._desk_claim_flip(body, cand), "an antonym flip is a POLARITY refusal, not a claim one"


def test_no_replacement_word_is_itself_a_banned_token():
    """THE TABLE MAY NOT LOOP. A replacement that carried a banned word would tell the writer to swap
    one charged word for another, and `answer._desk_allowed_stems` would license it on the same read."""
    for name, _pat, repl in reg.DESK_REGISTER_TOKENS:
        assert reg.count_desk_register(repl) == 0, (name, reg.desk_register_hits(repl))


def test_the_replacement_column_trips_no_shipped_register_detector():
    """`config_check.check_register_seam` (f) already grades this; the deck grades it too, because the
    first draft of the `loud` row ("the most stretched reading") reds on `_LANE_B_ADJ`."""
    for name, _pat, repl in reg.DESK_REGISTER_TOKENS:
        assert not reg._LANE_B_ADJ.search(repl), name
        assert reg.count_flow_words(repl) == 0, name
        assert reg.count_valuation_words(repl) == 0, name
        assert reg.register_leaks(repl) == [], name


def test_every_stem_HEADs_column_taught_is_still_allowed_and_no_CLAIM_WORD_was_added():
    """ONE PRODUCER, and the direction of travel is the guard's own rule: "a word the mandate starts
    teaching is a word the guard starts allowing on the same commit". Every word the column carried at
    `5c45f3e6` is still there, so no accepted rewrite becomes refusable by this edit.

    ROUND 2 RENAMES THIS PIN AND MAKES IT ASSERT WHAT ITS NAME PROMISES (review MINOR 2). It used to be
    called `..._only_ever_GREW` while spot-checking nineteen hand-named words; measured, the set does
    not only grow -- HEAD's `board` phrase read "the market, or 'the data as of <date>'" and the parser
    split on ` or `, so the two-character stem `or` left the set. The invariant is therefore stated
    over HEAD's own phrase table (the one `test_no_HEAD_replacement_phrase_was_lost` carries) and over
    the words a consumer can actually see: every stem of three characters or more that HEAD taught is
    still allowed.

    AND THE CLAIM-WORD EXEMPTION IS FROZEN AT HEAD'S THREE. `_desk_claim_terms` drops any claim word
    whose stem is allowed, so a replacement phrase carrying a fourth one silently widens what guard
    (10) stops seeing and what guard (11) lets a reply drop. HEAD's three are `largest`, `furthest` and
    `older`, all already earned by HEAD's own column; round 1 made it four (review MAJOR 2)."""
    stems = an._desk_allowed_stems()
    head_phrases = [p for ps in _HEAD_PHRASES.values() for p in ps]
    for phrase in head_phrases:
        for word in phrase:
            if len(word) >= 3:
                assert an._desk_stem(word) in stems, (phrase, word)
    for word in ("market", "record", "series", "print", "mechanism", "driver", "largest", "move",
                 "reading", "chain", "report", "latest", "date"):
        assert an._desk_stem(word) in stems, word
    for word in ("exchange", "contract", "currency", "signal", "known"):
        assert an._desk_stem(word) in stems, word
    # ...and the BANNED words never enter it, or the rewrite could introduce one
    for word in ("board", "row", "loud", "node", "receipt", "walk"):
        assert an._desk_stem(word) not in stems, word
    # ...and NO claim word beyond the three HEAD's own column already earned
    claim = sorted(w for w in ("largest", "furthest", "older", "strongest", "weakest", "highest",
                               "lowest", "most", "least", "widest", "nearest", "greatest")
                   if an._desk_stem(w) in stems)
    assert claim == ["furthest", "largest", "older"], claim


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# THE MANDATE -- two new rules, both about how a fact is SPELLED
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_the_mandate_carries_the_SCORING_rule_and_it_is_SCOPED():
    """"This is scoring machinery quoted verbatim. A reader has no idea what the big-crop pattern is,
    which eight drivers compose it, or why three is the threshold, and the sentence is therefore
    unfalsifiable as served." -- PM lens, quick_rv_corn_wheat, MAJOR. The same construction shipped on
    four of the five turns; on the max turn a PM called it "the worst register failure in the note, and
    it is a whole paragraph rather than a word."

    THE RULE CORRECTS AND DOES NOT DELETE (estate doctrine): the writer still states which conditions
    are met and whether the pattern is in force -- the FACT survives, the arithmetic does not.

    ROUND 2 SCOPES IT TO THE THRESHOLD NUMBER AND THE ROSTER SIZE (review FATAL F1 (i)) and REQUIRES
    the met conditions to be NAMED, which is the PM's own remedy ("either explain the pattern in trader
    terms or cut it"). The graders' FATAL on this construction is that the max page's count was
    ARITHMETICALLY WRONG -- one reading served twice under two names, counted twice -- so a rule that
    removed the count would have removed the only surface on which a reader or a fact lens could catch
    it, which is a fence that deletes a backed figure and leaves the claim standing."""
    m = N.desk_register_mandate()
    assert "A PATTERN IS NAMED BY ITS CONDITIONS AND NEVER BY ITS SCORE" in m
    assert "whether the pattern is in force" in m
    assert "say which conditions this market is meeting" in m          # the fact SURVIVES, named
    assert "do not print the number a pattern needs to fire" in m      # the THRESHOLD
    assert "do not print the size of the roster it draws from" in m    # the ROSTER SIZE
    # ...and the ban that reached the board mandate's own required prose is GONE, by name
    assert "never quote a driver count" not in m
    assert "counts the things it is reading" not in m


def test_the_mandate_carries_the_DATE_rule_and_it_CARVES_OUT_THE_BARE_YEAR():
    """"'20260904' is an unformatted integer sitting beside two ISO dates in the same clause. A desk
    writes 'our data runs through 4 September'." -- PM lens, quick_rv_corn_wheat, MAJOR. It shipped on
    three of five turns, in the one sentence whose entire job is to state a vintage.

    ROUND 2 (review FATAL F1 (iii)). "never as a bare run of digits with no separators" reached 250
    undelimited digit runs across the two corpora and 242 of them are not the defect: 47 bare years, 17
    `MY20xx` tokens and 44 printed VALUES on the case list alone. The rule now names the SHAPE and
    states the carve-out in its own text."""
    m = N.desk_register_mandate()
    assert "EVERY CALENDAR DATE YOU PRINT IS SPELLED THE WAY A DESK SPELLS ONE" in m
    assert "never as the year, the month and the day run together with no separators" in m
    assert "A YEAR STANDING ALONE AND A MARKETING YEAR ARE NOT CALENDAR DATES" in m
    assert "since 2022, in 2012, MY2026" in m
    # ...and it explicitly overrides the blocks, because the blocks are where the bare digits come from
    assert "whatever spelling the notes above happen to carry" in m
    assert "never as a bare run of digits with no separators" not in m


def test_the_desk_leg_does_not_contradict_the_BOARD_leg_it_is_appended_after():
    """THE ORDERING IS THE WHOLE POINT (review FATAL F1 (ii)): inside `answer._system` the board
    mandate's leg is appended first and the desk leg after it, so on a contradiction the DESK leg is
    the later instruction and it wins. The order is asserted below off the two producers rather than
    off a line number, because `answer.py` is being edited by another lane this sitting.

    `SYSTEM_STATE_BOARD_MANDATE` orders a COUNT IN WORDS three times -- movement (2)'s "then how many
    such cases the record carries, in words", movement (3)'s "name the other markets the block declares
    the same loud state moves", and the closing "Base rates come from the block's count words". Round
    1's desk leg answered, unscoped, "a sentence that counts the things it is reading has stopped
    writing about markets". Measured over 748 real-seat sentences, 11 carried exactly those
    constructions and round 1's rule reached 10 of them; this deck pins that the clause is gone and
    that the desk leg now says the opposite IN SO MANY WORDS."""
    m = N.desk_register_mandate()
    assert "THAT IS A RULE ABOUT SCORING MACHINERY AND NOT ABOUT COUNTING" in m
    assert "a count in words is a fact about the market" in m
    assert "how many other markets carry the same state" in m          # movement (3)
    assert "how many such cases the record holds" in m                 # movement (2) / base rates
    # ...and the board mandate's own required constructions are UNTOUCHED, byte for byte
    board = N.SYSTEM_STATE_BOARD_MANDATE
    for owed in ("then how many such cases the record carries, in words",
                 "name the other markets the block declares the same loud state moves",
                 "Base rates come from the block's count words"):
        assert owed in board, owed
    # ...and the ORDER is read off the assembled prompt, not off a line number
    sysm = an._system(state_board=True, desk_register=True)
    assert sysm.index(board) < sysm.index(N.desk_register_mandate(state_board=True))


def test_the_anaphor_in_the_ban_half_has_its_ANTECEDENT_back():
    """ROUND-1 REVIEW MAJOR 3. The exchange-name paragraph was wedged between "is the market's own name
    and stays exactly as written" and "So are the other phrases that only LOOK like our words", so "So
    are" took "has stopped writing about markets" as its antecedent and the five EXEMPT idioms attached
    to a BAN clause. Order is asserted, not read: the exemption list follows the sentence it refers
    back to, and the exchange paragraph follows the exemption list and restates its own subject."""
    m = N.desk_register_mandate()
    own_name = m.index("is the market's own name and stays exactly as written")
    so_are = m.index("So are the other phrases that only LOOK like our words")
    write_any = m.index("Write any of those exactly as a desk writes them")
    exchange = m.index("A NAMED EXCHANGE OR INSTITUTION is the market's own name only when")
    assert own_name < so_are < write_any < exchange, (own_name, so_are, write_any, exchange)


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# THE TWO RULES, OPERATIONALISED -- what a careful writer applies to ONE sentence
# ══════════════════════════════════════════════════════════════════════════════════════════════════
#: A PROMPT RULE CANNOT BE EXECUTED, so round 2 writes the predicate out and grades the PREDICATE, and
#: a reviewer who disagrees can disagree with the predicate rather than with a number. These are the
#: same two regexes `scratchpad/prearm_fix_r2/A2_rule_reach.py` runs over all 748 sentences of the two
#: corpora; the deck carries the CASES, the script carries the census.
_CARD = (r"(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|"
         r"fifteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|zero|no|\d+)")
_SCORE_CTX = re.compile(r"\bpattern\b|\bthreshold\b|\bquorum\b", re.I)
#: the PATTERN'S OWN SCORE: a threshold NUMBER, or a roster SIZE (an x-of-y whose y is stated).
_SCORE_SPAN = re.compile(
    r"threshold\s+(?:of|is|at)\s+" + _CARD + r"\b"
    r"|\b" + _CARD + r"[-\s]driver\s+threshold\b"
    r"|\b" + _CARD + r"\s+of\s+(?:its\s+|the\s+|that\s+pattern's\s+|those\s+)?(?:own\s+)?" + _CARD +
    r"\b"
    r"|\b(?:needs?|requires?)\s+" + _CARD + r"\s+of\s+(?:its\s+|the\s+)?" + _CARD + r"?\s*"
    r"(?:drivers?|conditions?|legs?)\b"
    r"|\bof\s+(?:its|the)\s+" + _CARD + r"\s+(?:drivers?|conditions?|legs?)\b"
    r"|\b" + _CARD + r"-of-" + _CARD + r"\b", re.I)
#: the UNDELIMITED CALENDAR DATE: year, month and day (or year and month) run together. A bare year, a
#: marketing year and a printed VALUE are outside it BY CONSTRUCTION -- `35852` never begins `19|20`
#: followed by a legal month, `2026` is four digits, and `MY2026` opens no word boundary before `2`.
_UNDELIMITED_DATE = re.compile(
    r"(?<![\d-])(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])?(?![\d-])")


def _reaches_scoring(sent: str) -> bool:
    return bool(_SCORE_CTX.search(sent)) and bool(_SCORE_SPAN.search(sent))


def _reaches_date(sent: str) -> bool:
    return bool(_UNDELIMITED_DATE.search(sent))


@pytest.mark.parametrize("sent", BANKED_SCORING)
def test_the_scoring_rule_REACHES_the_machinery_on_seats_this_lane_never_read(sent):
    """THE RULE IS FOR SOMETHING, and the unseen corpus is where that is shown: three months and two
    boards earlier, other seats printed the same threshold numbers and roster sizes."""
    assert _reaches_scoring(sent), sent


@pytest.mark.parametrize("sent", BANKED_COUNT_IN_WORDS)
def test_the_scoring_rule_LEAVES_the_board_mandate_s_OWN_required_prose(sent):
    """THE MEASUREMENT THAT ROUND 1 DID NOT RUN (review FATAL F1 (a)/(b)). Each of these is a
    construction `SYSTEM_STATE_BOARD_MANDATE` REQUIRES on the same turn -- a base rate in count words,
    a spillover roster, an in-force statement with no number, and a MARKET level called a threshold.
    Round 1's rule reached 10 of the 11 such sentences in the two corpora; round 2's reaches none."""
    assert not _reaches_scoring(sent), sent


@pytest.mark.parametrize("sent", BANKED_UNDELIMITED_DATE)
def test_the_date_rule_REACHES_the_undelimited_date_on_seats_this_lane_never_read(sent):
    assert _reaches_date(sent), sent


@pytest.mark.parametrize("sent", BANKED_PLAIN_YEAR)
def test_the_date_rule_LEAVES_the_bare_year_the_marketing_year_and_the_printed_value(sent):
    """REVIEW F1 (iii), measured: round 1's "a bare run of digits with no separators" reached 47 bare
    years, 17 `MY20xx` tokens and 44 printed VALUES on the case list alone."""
    assert not _reaches_date(sent), sent


def test_the_rules_OWN_WORKED_EXAMPLES_OBEY_THE_RULES():
    """REVIEW F1 (iv). Round 1's quorum example was "two of the pattern's conditions are met, so it is
    not in force" -- a count of conditions naming none of them, i.e. the exact construction the rule
    exists to remove, handed to the writer as the model sentence to copy.

    BOTH RULES ARE NOW GRADED BY THEIR OWN PREDICATE. The worked example names its conditions and
    prints neither a threshold number nor a roster size; and no digit run anywhere in either half of
    the shipped mandate is an undelimited calendar date, so the only digits the writer meets in this
    literal are ones its own date rule permits."""
    example = ("the crush margin is wide and the meal basis is firm, two of its conditions are met, "
               "and it is not in force")
    m = N.desk_register_mandate()
    assert example in m, "the worked example moved; re-cut this pin beside it"
    assert not _reaches_scoring(example), _SCORE_SPAN.search(example)
    for half in (m, N.desk_register_mandate(state_board=True)):
        assert not _reaches_date(half), _UNDELIMITED_DATE.findall(half)


def test_the_mandate_stops_teaching_the_bare_commodity_board():
    """The lint EXEMPTS `<commodity> board` (row 4) and therefore scores ZERO on "the one channel that
    supports the wheat board too" -- a sentence the PM lens called a MAJOR register leak. Measured:
    row 4's UNIQUE licence over rows 3 and 5 is +2 charges on the five served bodies, both of them
    "the wheat board", and +1 on the fourteen banked answers. The exemption is DOCKETED rather than
    removed on the eve of the arm (it moves the reported number on BOTH cells for a reason that is not
    the treatment); the PROMPT is corrected instead, which costs no charge on either cell."""
    m = N.desk_register_mandate()
    assert "is the market's own name only when the exchange or the institution is actually named" in m
    assert "a bare wheat board is not" in m
    # ROUND-2 MINOR 4: the aside no longer asserts a DATE. The Canadian Wheat Board's single-desk
    # monopoly ended in 2012 but the entity continued and was later sold, so "closed in 2012" was
    # loose -- and this wheat-specific aside ships on every cocoa, coffee and palm turn that lights the
    # flag. The PM's point survives without the year, and the date rule's own carve-out now owns 2012.
    assert "closed in 2012" not in m
    # ...and the ban half's SELF-LINT is a declared number: the literal must quote the words it bans.
    # HEAD 22 -> 23, the one added charge being "on each board is the instrument's own word".
    assert reg.count_desk_register(m) == 23, reg.desk_register_hits(m)
    assert "Chicago wheat or the CBOT wheat" in m
    # the exemption itself did NOT move -- this test is the record of that decision
    assert reg.count_desk_register("it is the one channel that supports the wheat board too") == 0


def test_the_recency_clause_names_the_replacement_for_the_blocks_own_words():
    """The board mandate's movement (2) instructs "the newest knowledge date the number rows carry" and
    `test_board_coverage.py:642` pins that instruction, so it may not be reworded -- the desk clause is
    where the writer is told what to write instead, and it rides the leg that supplies the facts."""
    board_half = N.desk_register_mandate(state_board=True)
    ban_half = N.desk_register_mandate()
    assert "the newest number behind this page was known" in board_half
    assert "the newest number behind this page was known" not in ban_half
    assert "three dated facts" in board_half and "the board price tape" in board_half


def test_both_mandate_halves_are_still_register_clean_at_build():
    """A shipped literal's register trip is a BUILD failure, never a stripped answer at serve time."""
    assert N.check_literals() == []
    for m in (N.desk_register_mandate(), N.desk_register_mandate(state_board=True)):
        m.encode("ascii")
        assert "{" not in m and "}" not in m
        assert R.register_hits(m) == []
        assert N.BANNED_RECENCY_PHRASE not in m


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# THE RECENCY LINE -- the ten-day lie, and the words that carried it
# ══════════════════════════════════════════════════════════════════════════════════════════════════
class _Series:
    def __init__(self, kd):
        self.knowledge_date = kd


class _Board:
    """The smallest board `recency_rows` reads: an as-of, a recency map and a series map."""

    def __init__(self, numbers, kds, asof="2026-09-16", text="2026-04-17"):
        self.asof = asof
        self.recency = {"numbers": numbers, "text": text}
        self.series = {str(i): _Series(k) for i, k in enumerate(kds)}


def test_iso_date_normalises_every_spelling_the_estate_actually_serves():
    assert N.iso_date("20260904") == "2026-09-04"           # the ESR rows' own spelling
    assert N.iso_date("2026-09-14") == "2026-09-14"         # already ISO: identity
    assert N.iso_date("202607") == "2026-07"                # month precision is KEPT as month
    assert N.iso_date("2026-09-14T00:00:00") == "2026-09-14"
    assert N.iso_date("") == "" and N.iso_date(None) == ""


def test_iso_date_DECLINES_rather_than_guessing():
    """`age_clause`'s own rule, one function up: an unreadable date returns itself and never a guess.
    A normaliser that invented a date would be a worse defect than the one it replaces."""
    assert N.iso_date("not-a-date") == "not-a-date"
    assert N.iso_date("20261340") == "20261340"             # month 13 / day 40: not a date
    assert N.iso_date("2026") == "2026"                     # a year is not given a month


def test_the_newest_knowledge_date_was_a_LEXICAL_max_and_is_now_a_real_one():
    """THE MEASURED TEN-DAY LIE, reproduced. The served answers read "the newest knowledge date on a
    number row 20260904" while nine cited rows were known 2026-09-11..15. Both grader lenses found the
    mechanism: "'20260904' only sorts newest if the dates are compared as strings across two formats
    ('2026-09-14' < '20260904' character-wise), and 20260904 is the one row in the footer printed
    without dashes."

    THE HEAD BEHAVIOUR IS ASSERTED TOO, so the pin fails if the defect is ever reintroduced by a
    producer that sorts before this module sees the values."""
    assert max(["20260904", "2026-09-14"]) == "20260904"      # HEAD's comparison, and it is wrong
    bd = _Board("20260904", ["20260904", "2026-09-14", "2026-08-01"])
    newest, oldest = N.knowledge_edges(bd)
    assert newest == "2026-09-14" and oldest == "2026-08-01"
    assert "known 2026-09-14" in N.recency_rows(bd, tape_edge="2026-09-04")["numbers"]


def test_the_edges_are_computed_over_every_row_the_page_serves_not_one_subset():
    """`bd.recency["numbers"]` is a max over `bd.series` -- the BOARD's own map -- and the reader's
    footer also carries the rows the NUMBERS AGENT looked up, which the board never saw. On the max
    turn nine cited rows were newer than the date the sentence declared newest. `extra_kd` is how the
    caller that holds the footer hands those in; it defaults to empty, so nothing is invented."""
    bd = _Board("20260904", ["20260904", "2026-08-01"])
    assert N.knowledge_edges(bd) == ("2026-09-04", "2026-08-01")
    assert N.knowledge_edges(bd, ["2026-09-15", "20260911", "2012-04-10"]) == ("2026-09-15",
                                                                              "2012-04-10")


def test_the_three_SB_L_LINES_SCORE_ZERO_ON_THE_LINT_THE_MANDATE_ENFORCES():
    """THE BLOCK MAY NOT TEACH WHAT THE PROMPT BANS. The `numbers` line was the block's ONLY source of
    `knowledge date` (3 of 3 served charges) and of three of the seven `row` charges -- the writer
    transcribed it on three of five turns. The tape line is UNCHANGED and stays exempt."""
    rows = N.recency_rows(_Board("2026-09-04", ["2026-08-01"]), tape_edge="2026-09-04")
    assert set(rows) == {"numbers", "text", "tape"}
    for layer, text in rows.items():
        assert reg.count_desk_register(text) == 0, (layer, reg.desk_register_hits(text))
    assert rows["tape"] == "the board price tape runs through 2026-09-04"     # byte for byte, HEAD's


def test_every_recency_layer_still_scores_its_own_coverage_word():
    """A REWORD THAT COST THE COUNTER WOULD BE A TRADE, NOT A FIX. `_RECENCY_LAYER_WORDS` accepts seven
    phrasings for the numbers layer and FOUR of them are desk-clean; the line now uses one of those
    four, so `recency_referenced` still scores a writer who copies it.

    ROUND 2 (review MINOR 6) ASKS THE PRODUCER THAT SCORES, not the dict it reads. `_recency_tokens`
    returns `(dates, words)` and a row with NO date returns `()` -- it leaves the denominator rather
    than scoring zero -- so a line that lost its date would pass a dict lookup and still cost the
    counter. Both groups are asserted here."""
    rows = N.recency_rows(_Board("2026-09-04", ["2026-08-01"]), tape_edge="2026-09-04")
    for layer, text in rows.items():
        groups = R._recency_tokens(layer, text)
        assert len(groups) == 2, (layer, text, groups)         # (dates, words): the row is testable
        dates, words = groups
        assert dates, (layer, text)
        assert any(w in text.lower() for w in words), (layer, text, words)
    assert "newest number" in rows["numbers"]


def test_the_AS_OF_is_normalised_like_every_other_date_on_the_line():
    """ROUND-2 MINOR 1. `read as of {bd.asof}` was the ONE date on the SB-L line printed raw while
    every other date went through `iso_date`, so a producer handing an undelimited as-of would have the
    block print -- in the reader's own prose, from the block the writer is told to transcribe -- the
    exact spelling the mandate beside it forbids."""
    line = N.recency_rows(_Board("2026-09-04", ["2026-08-01"], asof="20260916"),
                          tape_edge="2026-09-04")["numbers"]
    assert "read as of 2026-09-16" in line and "20260916" not in line, line
    # ...and an unreadable as-of prints exactly as it printed before: `iso_date` DECLINES, never guesses
    odd = N.recency_rows(_Board("2026-09-04", ["2026-08-01"], asof="not-a-date"),
                         tape_edge="2026-09-04")["numbers"]
    assert "read as of not-a-date" in odd, odd


def test_extra_kd_takes_the_FOOTER_S_OWN_ROWS_and_not_only_strings():
    """ROUND-2 MAJOR 4. Round 1 shipped `extra_kd` as an iterable of STRINGS, so the wiring at the
    caller was a comprehension that had to reach for the right attribute; a caller that reached for the
    wrong one would hand in empty strings and the union would collapse silently back to the board's own
    pool -- a fix that looks wired and is not. The producer takes the footer's own members, so the call
    site is the list itself.

    AN UNREADABLE MEMBER CONTRIBUTES NOTHING AND NEVER RAISES: this runs on the render path of every
    board turn."""
    bd = _Board("20260904", ["20260904", "2026-08-01"])
    assert N.knowledge_edges(bd) == ("2026-09-04", "2026-08-01")
    rows = [{"knowledge_date": "2026-09-14"}, {"data_date": "20260911"},
            {"year": 2012, "month": 4}]
    assert N.knowledge_edges(bd, rows) == ("2026-09-14", "2012-04")
    assert N.knowledge_edges(bd, ["2026-09-15", "20260911"])[0] == "2026-09-15"   # bare strings still
    assert N.knowledge_edges(bd, [None, object(), {}, "", 17]) == ("2026-09-04", "2026-08-01")


def test_the_column_extractor_is_citations_OWN_and_this_module_keeps_NO_SECOND_ONE():
    """ROUND-3 MAJOR 1 -- THE PARITY CLAIM WAS FALSE AND IS NOW A CALL INSTEAD OF A SENTENCE.

    Round 2 read a served row off a four-name tuple of its own and said in three docstrings that those
    were "the same four columns in the same order as `citations._row_known_date`". MEASURED, they were
    not: that function reads `knowledge_date`, `data_date` and THEN the row's own (year, month) as
    'YYYY-MM', and it reads neither `known` nor `date`. The (year, month) branch is the whole climate
    class -- the cards with no date column at all -- and dropping it made the deep smoke page's stated
    OLDEST 2012-04-10 against a footer whose own oldest row is `[known 2011-04]`: a twelve-month error
    in the unsafe direction, in the one sentence whose job is the page's vintage.

    So there is no parity sentence to keep true: the dict branch CALLS the one extractor."""
    from leviathan.graphrag.citations import Citation, _row_known_date

    assert not hasattr(N, "_kd_of") and not hasattr(N, "_KD_FIELDS")     # no second extractor, at all
    bd = _Board("", [])                                     # a board with NO pool of its own
    for row in ({"year": 2011, "month": 4}, {"year": "2026", "month": "07"},
                {"knowledge_date": "20260904"}, {"data_date": "2026-09-11"},
                {"knowledge_date": "", "year": 2012, "month": 4}, {"month": 13, "year": 2011}, {}):
        assert N.knowledge_edges(bd, [row])[0] == N.iso_date(_row_known_date(row) or ""), row
    # A CITATION IS READ OFF `.date`, which `citations.py` has already filled from that same function.
    c = Citation(id="N61", kind="number", label="x", source="gold_weather_z", date="2011-04")
    assert N.knowledge_edges(bd, [c])[0] == "2011-04"


def test_the_CLIMATE_ROW_alone_stamps_the_month_it_was_known():
    """ROUND-3 MAJOR 1, THE PIN ON ITS OWN. The round-2 deck carried this row inside a four-member list
    whose oldest came from the member beside it, so the pin was green with the year/month member
    contributing nothing -- a pin that does not pin. Here the row is the ONLY member, and it is the
    exact class the served footers carry (`silver_noaa_oni` / `silver_noaa_iod` / `gold_weather_z`,
    which have no date column: `citations.py:290-312`). The deep smoke body's own oldest stamp is
    `[known 2011-04]`."""
    bd = _Board("", [])
    assert N.knowledge_edges(bd, [{"year": 2011, "month": 4}]) == ("2011-04", "2011-04")
    line = N.recency_rows(bd, extra_kd=[{"year": 2011, "month": 4}], tape_edge="")["numbers"]
    assert "known 2011-04" in line and "2012" not in line, line


def test_the_ledger_sentence_stopped_teaching_the_words_its_own_mandate_bans():
    """`RECENCY_LEDGER_SENTENCE` is the PROSE form of the same three facts (unshipped per WP-A9, and
    graded at build like every other literal here). It scored `row` x2 + `knowledge date` x1 -- the
    estate's own reference text teaching three of the four residue words."""
    assert reg.count_desk_register(N.RECENCY_LEDGER_SENTENCE) == 0
    s = N.recency_ledger(asof="2026-09-07", kd_max="20260904", kd_min="2025-12-31",
                         record_through="2026-08-20", tape_edge="2026-09-04")
    assert "none dates the others" in s                       # the sentence's own closing rule
    assert "20260904" not in s and "2026-09-04" in s          # every date goes through iso_date
    assert reg.count_desk_register(s) == 0


def test_the_SB_L_numbers_line_is_A_SENTENCE_on_all_four_branches_and_invents_no_edge():
    """ROUND-3 MAJOR 3 -- THE DEGENERATE BRANCHES, WHICH NO ROUND-2 PIN REACHED (every `_Board` in the
    deck carried a non-empty `numbers` recency, so only branch A was exercised).

    (A) recency + series: unchanged, both edges printed.
    (B) recency SET, series EMPTY and (C) recency SET, series dates BLANK: round 2 printed
        "and the oldest <THE NEWEST>" -- `knowledge_edges` keeps `bd.recency["numbers"]`, a MAX, in the
        pool it takes a MIN over, so the line stated an edge the board does not hold. HEAD printed no
        oldest clause here and neither does this.
    (D) NOTHING AT ALL: round 2 printed "the newest number here is known not carried on this page",
        which is not a sentence -- inside a block the mandate tells the writer to TRANSCRIBE. The
        fallback replaces the PREDICATE again, as it did at HEAD.
    (E) series only: the improvement round 2 bought is kept (HEAD called the newest "not carried" while
        naming an oldest), minus the fabricated equal edge."""
    def line(bd, **kw):
        return N.recency_rows(bd, tape_edge="2026-09-04", **kw)["numbers"]

    a = line(_Board("2026-09-04", ["2026-09-04", "2025-12-31"], asof="2026-09-07"))
    assert a == ("read as of 2026-09-07; the newest number here is known 2026-09-04 "
                 "and the oldest 2025-12-31"), a
    for degenerate in (_Board("2026-09-04", [], asof="2026-09-07"),
                       _Board("2026-09-04", ["", None], asof="2026-09-07")):
        b = line(degenerate)
        assert b == "read as of 2026-09-07; the newest number here is known 2026-09-04", b
        assert "the oldest" not in b, b
    d = line(_Board("", [], asof="2026-09-07"))
    assert d == ("read as of 2026-09-07; the newest number here is not carried on this page"), d
    assert "is known not carried" not in d, d                  # the round-2 non-sentence
    e = line(_Board("", ["2026-08-01"], asof="2026-09-07"))
    assert e == "read as of 2026-09-07; the newest number here is known 2026-08-01", e
    # ...and a kd_min the CALLER states is the caller's own fact, printed as given on every branch
    assert line(_Board("2026-09-04", [], asof="2026-09-07"),
                kd_min="2025-01-02").endswith("and the oldest 2025-01-02")
    # EVERY BRANCH IS STILL A SCORABLE SB-L ROW: the layer word survives the fallback
    for text in (a, d, e):
        assert any(w in text for w in R._RECENCY_LAYER_WORDS["numbers"]), text


def test_the_ledger_sentence_fallback_is_A_SENTENCE_too():
    """ROUND-3 MAJOR 3, the same break in the same file: `recency_ledger` fills a missing edge with
    "not carried on this page", and round 1's "the newest number IS KNOWN {kd_max}" made that read "is
    known not carried on this page". HEAD's predicate is restored; `number` is kept because
    `render._RECENCY_LAYER_WORDS` scores it. UNSHIPPED (WP-A9): no served byte moves either way."""
    s = N.recency_ledger(asof="2026-09-07")
    assert "the newest number is not carried on this page" in s, s
    assert "is known not carried" not in s, s
    assert reg.count_desk_register(N.RECENCY_LEDGER_SENTENCE) == 0
    assert "newest number" in N.RECENCY_LEDGER_SENTENCE           # the coverage scorer's own word
    assert N.check_literals() == []


def test_the_recency_row_VALUES_do_not_move_when_the_dates_were_already_iso():
    """THE BYTE-IDENTICAL STATEMENT, at the level where it can be checked: on a board whose dates are
    already ISO and correctly ordered, this edit moves the WORDS and not one date. That is why the
    change is a pure correction and not a new reading."""
    bd = _Board("2026-09-04", ["2026-09-04", "2025-12-31"], asof="2026-09-07")
    line = N.recency_rows(bd, tape_edge="2026-09-04")["numbers"]
    assert "2026-09-04" in line and "2025-12-31" in line
    assert "read as of 2026-09-07" in line
