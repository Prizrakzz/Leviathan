"""S7b R2 -- THE DESK REGISTER: the flag-scoped mandate literal, the correcting lint's one bounded
rewrite, and the bar-adjective remedy that rides beside it.

WHAT THIS DECK HOLDS, and it is the same two halves the S6 seam deck holds:

  FLAG OFF  -- `_system()` renders HEAD's bytes with the leg absent AND with it explicitly False;
               `narration.SYSTEM_STATE_BOARD_MANDATE`, `MANDATE_MOVEMENTS`, the three recency literals
               and `check_literals()` are untouched; neither new pass is called, neither stamps a trace
               key, and no model call is made.

  FLAG ON    -- proven with an INJECTED FAKE CALLER and no network: every rewrite assertion below runs
               at zero spend. That is not a convenience -- an LLM call inside the answer path is the
               one thing in this sitting that can cost money or lose a sentence, and both failure modes
               are falsifiable in CI only if the caller is injectable.

NOTHING HERE READS OR WRITES AN ENVIRONMENT VARIABLE except through `monkeypatch`, and every flag-off
assertion asserts the DEFAULT, so a runner with either S7b flag set cannot green them.
"""
from __future__ import annotations

import re

import pytest
from leviathan.graphrag import answer as an
from leviathan.graphrag import register as reg
from leviathan.graphrag import verify as vf
from leviathan.graphrag.state import narration as N


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# 1. THE MANDATE LITERAL -- flag-scoped, register-safe, and it never touches the board's own
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_the_board_mandate_and_every_recency_literal_are_untouched():
    """DR-8: `SYSTEM_STATE_BOARD_MANDATE` ships whenever `_state_board_block_on(vp)` holds, so a word
    edited into it changes the prompt on EVERY board-on turn with the desk flag OFF. The desk register
    is a SECOND literal for exactly that reason -- the `_SYSTEM_CASCADE_WALK_MANDATE` idiom."""
    assert N.SYSTEM_STATE_BOARD_MANDATE.startswith("THE STATE OF THE WORLD block above is this turn's "
                                                   "board:")
    assert N.SYSTEM_STATE_BOARD_MANDATE.endswith("Use no heading called then or now.")
    assert N.MANDATE_MOVEMENTS == (("DIRECTION", "## Mechanism", ""), ("EVIDENCE", "## The record", ""),
                                   ("SPILLOVERS", "## Cross-commodity", "## Mechanism"),
                                   ("WATCH", "## What to watch", ""))
    assert N.BANNED_RECENCY_PHRASE == "not a current-state read"
    assert N.SYSTEM_DESK_REGISTER_MANDATE not in N.SYSTEM_STATE_BOARD_MANDATE
    # S8 LANE N, the same law one flag over: the chain movement is a SUBSTITUTION and never an edit, so
    # the constant must not learn it and the FOUR-row table must not grow a fifth row. Both are what a
    # chain-flag-OFF board turn ships, and both are in S8's byte-identical set.
    assert N.MANDATE_CHAIN_MOVEMENT not in N.SYSTEM_STATE_BOARD_MANDATE
    assert "THE CHAIN" not in N.SYSTEM_STATE_BOARD_MANDATE
    assert len(N.MANDATE_MOVEMENTS) == 4


def test_the_desk_mandate_is_graded_by_check_literals():
    """A shipped literal's register trip is a BUILD failure here and never a stripped answer at serve
    time -- `state/lint.py`'s own reason for grading the mandate, extended to the new one."""
    assert N.check_literals() == []
    m = N.desk_register_mandate()
    m.encode("ascii")                                    # ASCII-only; the file is UTF-8
    assert "{" not in m and "}" not in m                 # the slot is filled by the producer
    assert reg.register_leaks(m) == []
    assert reg.count_flow_words(m) == 0
    assert reg.count_valuation_words(m) == 0
    assert not reg._LANE_B_ADJ.search(m)
    assert N.BANNED_RECENCY_PHRASE not in m


def test_the_mandate_and_the_lint_share_one_vocabulary_producer():
    """A token added to the lint that never reached the prompt would ban a word the writer was never
    told to replace -- a ban with no replacement is how a writer loses a fact rather than a word."""
    table = reg.desk_register_table()
    assert table in N.desk_register_mandate()
    for name, _pat, repl in reg.DESK_REGISTER_TOKENS:
        assert name in table and repl in table


def test_the_mandate_answers_the_recency_movement_it_would_otherwise_contradict():
    """The board mandate's movement (2) instructs 'the newest knowledge date the number rows carry', and
    `render`'s SB-L rows print the same words. NEITHER is reworded (DR-2: rewording changes the flag-on
    block and prompt for every board turn), so this literal must say what to write INSTEAD or the writer
    is handed two orders and no way to obey both.

    RE-ANCHORED 2026-09-11 (review MAJOR 4), and the anchor MOVED rather than loosened: the answering
    clause is the thing that must exist, and it must exist ON THE LEG THAT SUPPLIES ITS FACTS. It shipped
    on a FLAG-ONLY gate, so `_system(desk_register=True)` carried "say the newest and oldest dates the
    numbers on this page carry, the date of the newest document behind it, and the session the board
    price tape runs through" on turns where `SYSTEM_STATE_BOARD_MANDATE` and `SYSTEM_RECENCY_CLAUSE` were
    both absent -- an unconditional instruction about three facts nothing on the page carried. The ban
    half stays turn-wide ("the graph" leaks on a boardless cascade walk); the recency half rides
    `state_board`."""
    m = N.desk_register_mandate(state_board=True)
    assert "RECENCY" in m
    assert "the board price tape" in m                   # the ONE phrase that stays as the blocks give it
    assert "three dated facts" in m
    ban = N.desk_register_mandate()
    assert "RECENCY" not in ban and "board price tape" not in ban, ban
    assert "no naming of the " in ban, "the BAN half is turn-wide and must survive the split"


def test_system_is_byte_identical_with_the_leg_off():
    """The OFF arm's prompt, at the function level: absent and explicitly-False must be the same bytes,
    on every combination of the legs this lane can reach."""
    for kw in ({}, {"state_board": True}, {"state_board": True, "handles": True},
               {"handles": True, "outlook": True}, {"episodes": True, "recency": True}):
        assert an._system(**kw) == an._system(desk_register=False, **kw), kw


def test_the_leg_appends_the_literal_and_nothing_else():
    # RE-ANCHORED 2026-09-11 (review MAJOR 4) BY NAME: the leg appends the mandate for THIS TURN'S
    # SHAPE. On a board turn that is both halves; on a boardless one it is the turn-wide ban alone.
    base = an._system(state_board=True)
    lit = an._system(state_board=True, desk_register=True)
    assert lit == base + N.desk_register_mandate(state_board=True)
    # ...and it rides its OWN leg, so a board-off turn still gets it. "the graph" leaks on a cascade
    # walk that carries no board at all, which is why the vocabulary is the ANSWER's and not the block's.
    assert N.desk_register_mandate() in an._system(desk_register=True)
    assert an._system(desk_register=True) == an._system() + N.desk_register_mandate()


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# 2. THE CORRECTING LINT AND ITS ONE BOUNDED REWRITE
# ══════════════════════════════════════════════════════════════════════════════════════════════════
_DIRTY = {
    "tldr": "Reading the board at 2026-09-07, the loudest row on CBOT soybeans is the crush [N1].",
    "mechanism": ("The graph carries this as price-supportive [N2]. Crush margin is 1.06 USD per bushel "
                  "[N3] and the market rallied on the day. Two rows have spent their knowledge date."),
}


def _clean_copy():
    return dict(_DIRTY)


def test_the_lint_counts_and_makes_no_call_without_one():
    """The flag can be on with no caller threaded (an injected-fake serving path, the dossier lane): the
    lint still COUNTS, and says so with a closed word rather than pretending it rewrote something."""
    d = _clean_copy()
    out = an._desk_register_lint(d)
    assert out["outcome"] == "no_caller"
    assert out["hits_before"] >= 5 and out["hits_after"] == out["hits_before"]
    assert out["rewritten"] == 0
    assert d == _DIRTY                                    # not one byte moved


def test_a_clean_answer_makes_no_call_at_all():
    seen = []
    d = {"tldr": "CBOT soybeans tilt higher into the quarter [N1].", "mechanism": "Crush is wide [N2]."}
    out = an._desk_register_lint(d, call=lambda *a, **k: seen.append(1))
    assert out == {"hits_before": 0, "hits_after": 0, "sentences": 0, "offered": 0, "rewritten": 0,
                   "outcome": "clean", "usd": None}
    assert seen == []


def _fake(sentences, usage=None):
    """A caller that returns a fixed list and records exactly one invocation."""
    calls = []

    def _c(system, user, *, model="", tool=None, max_tokens=None):
        calls.append({"system": system, "user": user, "model": model, "tool": tool,
                      "max_tokens": max_tokens})
        out = {"sentences": list(sentences)}
        if usage:
            out["_usage"] = usage
        return out
    return _c, calls


def test_the_happy_path_rewrites_only_the_offending_sentences():
    d = _clean_copy()
    offending = reg.desk_register_sentences(d["tldr"]) + reg.desk_register_sentences(d["mechanism"])
    assert len(offending) == 3
    call, calls = _fake([
        "Reading the market at 2026-09-07, the largest move on CBOT soybeans is the crush [N1].",
        "The mechanism carries this as price-supportive [N2].",
        "Two series are read through older dates.",
    ])
    out = an._desk_register_lint(d, call=call, model="claude-opus-5")
    assert len(calls) == 1, "the ruling is ONE bounded rewrite call per turn"
    # ROUND 4 (owner ruling (5)): the rewrite is SUBSTITUTION-ONLY, so the third reply -- which
    # restructures the sentence ("have spent their" -> "are read through") rather than substituting a
    # table phrase -- is refused and the writer's own sentence stands. THE MEASURED CONSEQUENCE, stated
    # rather than papered over: the `knowledge date` row of the table offers no NOUN-PHRASE replacement
    # ("read through <date>" is a verb phrase), so a `knowledge date` charge in a noun slot has no
    # accepted rewrite at all. The one-line remedy is a TABLE edit (teach "the as-of date"), which is an
    # owner call about the mandate's own prompt and not this lane's to take.
    assert out["outcome"] == "rewritten" and out["rewritten"] == 2
    assert out["refused"] == {"edit_outside_table": 1}, out
    assert out["hits_after"] == 2 and out["hits_before"] >= 5   # `row` + `knowledge date`, both kept
    assert "the market rallied on the day" in d["mechanism"], "a clean sentence was rewritten"
    assert "1.06 USD per bushel [N3]" in d["mechanism"], "a clean sentence lost its figure"


def test_the_call_is_bounded_in_sentences_chars_and_output_tokens():
    d = {"tldr": "", "mechanism": " ".join(f"The board is loud on leg {i}." for i in range(40))}
    call, calls = _fake(["x"] * 40)
    out = an._desk_register_lint(d, call=call)
    assert out["sentences"] == 40
    assert out["offered"] == an._DESK_REWRITE_MAX_SENTENCES
    assert calls[0]["max_tokens"] == an._DESK_REWRITE_MAX_TOKENS
    assert len(calls[0]["user"]) <= an._DESK_REWRITE_MAX_CHARS + 200


@pytest.mark.parametrize("bad,why", [
    ("The largest move on CBOT soybeans is the crush.", "a DROPPED handle"),
    ("At 2026-09-08 the largest move on CBOT soybeans is the crush [N1].", "a CHANGED date"),
    ("At 2026-09-07 the largest move on 2 CBOT soybean boards is the crush [N1].", "an ADDED numeral"),
    ("At 2026-09-07 the largest move on CBOT soybeans is the crush [N2].", "a RE-POINTED handle"),
    ("", "an EMPTY return"),
])
def test_every_refusal_leaves_the_original_sentence_standing(bad, why):
    """DR-4 / DR-5: the rewrite is a deletion vector and a claim vector, and both are closed by
    construction. `verify_citations` has ALREADY run when this pass fires, so any numeral a rewrite
    invents is UNVERIFIED -- the pass is FORBIDDEN to touch one, and the forbiddance is enforced."""
    d = {"tldr": _DIRTY["tldr"], "mechanism": ""}
    before = d["tldr"]
    call, _calls = _fake([bad])
    out = an._desk_register_lint(d, call=call)
    assert out["rewritten"] == 0, why
    assert out["outcome"] == "unchanged", why
    assert d["tldr"] == before, why


def test_a_rewrite_that_does_not_reduce_the_count_is_refused():
    d = {"tldr": "The board is loud today [N1].", "mechanism": ""}
    call, _c = _fake(["The board is loud again today [N1]."])
    out = an._desk_register_lint(d, call=call)
    assert out["rewritten"] == 0 and d["tldr"] == "The board is loud today [N1]."


@pytest.mark.parametrize("bad_out", [None, {}, {"sentences": "not a list"}, {"sentences": []},
                                     {"sentences": ["a", "b"]}])
def test_a_malformed_return_is_bad_shape_and_changes_nothing(bad_out):
    d = {"tldr": _DIRTY["tldr"], "mechanism": ""}
    before = dict(d)
    out = an._desk_register_lint(d, call=lambda *a, **k: bad_out)
    assert out["outcome"] == "bad_shape"
    assert d == before


def test_a_raising_caller_fails_open_with_a_named_word():
    """DR-3: a timeout, a refusal, a 429 or a degraded shape must not lose the sentence. Named
    exception, never bare, and the failure word reaches the trace."""
    def boom(*_a, **_k):
        raise TimeoutError("no answer")
    d = {"tldr": _DIRTY["tldr"], "mechanism": ""}
    before = dict(d)
    out = an._desk_register_lint(d, call=boom)
    assert out["outcome"] == "call_failed:TimeoutError"
    assert d == before


def test_the_measured_cost_rides_the_census_and_is_never_fabricated():
    d = {"tldr": _DIRTY["tldr"], "mechanism": ""}
    call, _c = _fake(["Reading the market at 2026-09-07, the largest move on CBOT soybeans is the "
                      "crush [N1]."],
                     usage={"model": "claude-opus-5", "in": 1600, "out": 1200})
    out = an._desk_register_lint(d, call=call)
    assert out["rewritten"] == 1
    assert out["usd"] == pytest.approx(1600 * 5.0 / 1e6 + 1200 * 25.0 / 1e6)
    assert out["usd"] <= 0.05, "the owner's ceiling, measured rather than asserted"
    # an unpriced model reports NO cost rather than a wrong one
    d2 = {"tldr": _DIRTY["tldr"], "mechanism": ""}
    call2, _c2 = _fake(["Reading the market at 2026-09-07, the largest move on CBOT soybeans is the "
                        "crush [N1]."],
                       usage={"model": "some-unpriced-seat", "in": 10, "out": 10})
    assert an._desk_register_lint(d2, call=call2)["usd"] is None


def test_the_lint_never_loops_and_never_deletes():
    """DR-6: the lint counts, trips at most one call, and re-counts. A rewrite that still leaks must NOT
    re-enter, and no path may shorten the answer."""
    d = _clean_copy()
    call, calls = _fake(["The largest move on CBOT soybeans is the crush [N1].",
                         "The board still carries this as price-supportive [N2].",
                         "Two series are read through older dates."])
    out = an._desk_register_lint(d, call=call, model="claude-opus-5")
    assert len(calls) == 1
    assert out["hits_after"] >= 1, "the fixture leaves a leak on purpose, and it is NOT re-attempted"
    assert "1.06 USD per bushel [N3]" in d["mechanism"]
    assert "the market rallied on the day" in d["mechanism"]


def test_the_digit_and_handle_invariants_are_the_ones_the_lint_enforces():
    assert an._desk_digits("Crush is 1.06 USD [N12] on 2026-09-04.") == ["04", "06", "09", "1", "2026"]
    assert an._desk_handles("a [N12] b [E3, 4] c") == ["[E3,4]", "[N12]"]
    assert an._desk_digits("a [N12] b") == []            # a handle's index is an ADDRESS, not a claim


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# 3. THE BAR-ADJECTIVE REMEDY -- correcting, letters-only, idempotent, never a deletion
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def _cot(pct):
    q = {"table": "silver_cot", "metric": "mm_net", "commodity": "soybeans", "country": "US",
         "period": "2026-09-04", "asof": "2026-09-07"}
    return [{"query": dict(q), "rows": [{"value": pct, "unit": "percentile"}], "status": "ok"}]


def test_a_licensed_sentence_is_counted_and_left_exactly_as_written():
    d = {"tldr": "Positioning is crowded at the 4th percentile [N1].", "mechanism": ""}
    before = dict(d)
    out = an._bind_bar_adjectives(d, _cot(4))
    assert out["licensed"] == 1 and out["corrected"] == 0
    assert d == before


def test_a_contradicting_figure_gains_the_clause_that_names_it():
    """OWNER RULING (3), 2026-09-15 16:30Z. The one correction left standing: the sentence calls
    positioning crowded AND cites a served percentile that sits INSIDE the band the adjective claims to
    be outside of, so the clause names that figure and that band. Words are free -- this is not about
    the word, it is about the page contradicting itself."""
    lo, hi = vf._bar_bands("positioning")
    d = {"tldr": "Positioning is crowded at the 28th percentile [N1].", "mechanism": ""}
    out = an._bind_bar_adjectives(d, _cot(28))
    assert out["weak"] == 1 and out["corrected"] == 1 and out["adjectives_unbacked"] == 0
    assert d["tldr"].endswith(an._BAR_BAND_CLAUSE.format(pct=an._bar_num(28), lo=an._bar_num(lo),
                                                         hi=an._bar_num(hi)) + ".")
    assert "[N1]" in d["tldr"]


def test_an_unbound_adjective_is_counted_and_left_exactly_as_written():
    """OWNER RULING (3) + (4). Rounds 1-3 appended a DECLINE clause here ("no served percentile for
    that market is cited beside the word"); the ruling retires it -- an adjective with no figure beside
    it is a word, and words are free -- and puts a COUNTER in its place. The sentence is the census'
    one genuine present verdict, and not one byte of it moves."""
    s = ("A governed spread series is not yet served, so I will characterise the gap only in words: "
         "soyoil prints above palm, and soyoil is the more stretched of the two against its own "
         "five-year mean.")
    d = {"tldr": s, "mechanism": ""}
    out = an._bind_bar_adjectives(d, [])
    assert out["unbound"] == 1 and out["corrected"] == 0
    assert out["adjectives_unbacked"] == 1
    assert d["tldr"] == s
    assert not hasattr(an, "_BAR_UNBOUND_CLAUSE") and not hasattr(an, "_BAR_STALE_CLAUSE")


def test_the_remedy_moves_a_digit_only_by_copying_the_served_figure_and_the_band():
    """RO-5 / cycle-10, kept in the form the ruling asks for. The clause NAMES the figure and the band,
    so the digit multiset is no longer frozen -- what is enforced instead is that every digit it gains
    is COPIED rather than computed: the served row's own value and the convention's own two bounds, and
    nothing else. A sentence that earns no clause is unchanged, handles included."""
    lo, hi = vf._bar_bands("positioning")
    for text, calls, gained in (
            ("Positioning is crowded at the 28th percentile [N1].", _cot(28),
             [an._bar_num(28), an._bar_num(lo), an._bar_num(hi)]),
            ("The soyoil-palm spread is rich -- 118.4 USD/t [N12], 96th percentile [N13].", [], []),
            ("Positioning is crowded at the 4th percentile [N1].", _cot(4), [])):
        d = {"tldr": text, "mechanism": ""}
        an._bind_bar_adjectives(d, calls)
        assert sorted(an._desk_digits(d["tldr"])) == sorted(an._desk_digits(text) + gained), text
        assert an._desk_handles(d["tldr"]) == an._desk_handles(text), text
        assert len(d["tldr"]) >= len(text), "the remedy never shortens a sentence"


def test_the_remedy_is_idempotent():
    d = {"tldr": "Positioning is crowded at the 28th percentile [N1].", "mechanism": ""}
    an._bind_bar_adjectives(d, _cot(28))
    once = dict(d)
    an._bind_bar_adjectives(d, _cot(28))
    assert d == once


def test_the_correcting_clause_is_clean_under_both_s7b_instruments():
    """The two instruments in this sitting must not charge each other: a clause that tripped the desk
    lint would make the bar fence's own remedy the next rewrite's input. ROUND 4: the TEMPLATE carries
    no digit of its own -- every numeral arrives through `.format`, from the served row and from the
    convention's own band."""
    assert not re.search(r"\d", an._BAR_BAND_CLAUSE)
    clause = an._BAR_BAND_CLAUSE.format(pct="42", lo="10", hi="90")
    assert reg.count_desk_register(clause) == 0, reg.desk_register_hits(clause)
    assert reg.register_leaks(clause) == []
    assert reg.count_flow_words(clause) == 0 and reg.count_valuation_words(clause) == 0


def test_a_licensed_sentence_survives_the_strip_end_to_end():
    """The remedy and the licence are two halves of one instrument: the remedy qualifies the sentence and
    the licence is what stops `sanitize` deleting it on the way to the reader."""
    d = {"tldr": "Positioning is crowded at the 28th percentile [N1].", "mechanism": ""}
    an._bind_bar_adjectives(d, _cot(28))
    def lic(s):
        return vf.bar_adjective_verdict(s, _cot(28))
    assert d["tldr"] not in reg.sanitize(d["tldr"])                       # HEAD: struck
    assert d["tldr"] in reg.sanitize(d["tldr"], bar_licence=lic)          # licensed: kept, qualified


def test_neither_pass_raises_on_junk():
    """`state/`'s law #1 read one module over: an instrument must never be the thing that breaks an
    answer."""
    for junk in (None, {}, {"tldr": None}, {"tldr": 3, "mechanism": []}, {"mechanism": ""}):
        assert isinstance(an._bind_bar_adjectives(junk, None), dict)
        assert isinstance(an._desk_register_lint(junk), dict)


def test_a_sentence_that_spans_lines_is_never_offered_and_never_reflowed():
    """MEASURED on the nine banked answers: 16 of 129 offending sentences carry a LINE BREAK, because
    `register._SENT_ITER` splits on a terminator plus whitespace and deliberately does NOT break on a
    bare newline (S1.F2/W0-1: the strip and the scanner must segment identically) -- so a markdown
    heading or an unterminated bullet welds to its successor. Offering one to a numbered-list prompt
    makes the reply ambiguous, and splicing a one-line reply back would reflow the writer's own
    bullets. Skipped, stamped, and left exactly as written."""
    body = "## Mechanism@The board is loud here [N1]. Rows carry no date.".replace("@", "\n")
    d = {"tldr": "", "mechanism": body}
    offending = reg.desk_register_sentences(body)
    assert any("\n" in s for s in offending), "the fixture no longer carries a multi-line unit"
    call, calls = _fake(["The market is quiet here [N1]."])
    out = an._desk_register_lint(d, call=call)
    assert out["multiline_skipped"] >= 1
    assert out["offered"] == out["sentences"] - out["multiline_skipped"]
    assert "## Mechanism\nThe board is loud here [N1]." in d["mechanism"]


def test_an_answer_whose_every_charged_sentence_spans_lines_makes_no_call():
    seen = []
    d = {"tldr": "", "mechanism": "## The record\nThe board is loud"}
    out = an._desk_register_lint(d, call=lambda *a, **k: seen.append(1))
    assert out["outcome"] == "nothing_offerable"
    assert seen == [], "a turn with nothing offerable must not spend"
    assert out["hits_before"] >= 1 and out["hits_after"] == out["hits_before"]


def test_a_bullet_or_heading_marker_is_cut_before_the_offer_and_re_attached_verbatim():
    """A rewrite is a DELETION VECTOR for structure too, and no digit or handle check can see it:
    offering "- The board is loud [N1]" as item 3 of a numbered list invites a reply that drops the
    dash, and the page silently stops being a list. `register._SENT_KEEP` splits on a terminator plus
    whitespace, so the whitespace rides the DELIMITER and the marker stays glued to the sentence -- the
    marker is therefore CUT before the offer and RE-ATTACHED verbatim on acceptance. The model is never
    asked about it, so it can never lose it."""
    d = {"tldr": "", "mechanism": "- The board is loud here [N1]. Prices firmed."}
    call, calls = _fake(["The market is the largest move here [N1]."])
    out = an._desk_register_lint(d, call=call, model="claude-opus-5")
    assert calls[0]["user"].startswith("1. The board is loud here [N1]"), calls[0]["user"]
    assert out["rewritten"] == 1
    assert d["mechanism"].startswith("- The market is the largest move here [N1]."), d["mechanism"]


def test_the_offer_carries_no_marker_even_when_the_model_would_have_kept_it():
    d = {"tldr": "", "mechanism": "## The record The board is loud [N1]."}
    call, calls = _fake(["The market is the largest move [N1]."])
    an._desk_register_lint(d, call=call)
    assert "##" not in calls[0]["user"], calls[0]["user"]
    assert d["mechanism"].startswith("## "), d["mechanism"]


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# S7b REVIEW FIXES (2026-09-11) -- the rewrite's guards, the decline clause and the mandate's reach.
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_major3_the_clause_that_denied_a_citation_is_gone_rather_than_reworded():
    """REVIEW MAJOR 3, CLOSED BY THE RULING RATHER THAN BY A BETTER SENTENCE. The decline clause shipped
    as " -- no served figure is cited for that reading" and was appended to sentences that VISIBLY cite
    a figure; round 3 reworded it to name the missing RANK. Round 4 removes it: a word with no figure
    beside it is a word, and words are free. What is graded is that the symbol is GONE -- dead text
    pretending to be a fence is how a later reader believes a correction still ships -- and that the
    counter carries the population instead."""
    assert not hasattr(an, "_BAR_UNBOUND_CLAUSE")
    assert not hasattr(an, "_BAR_STALE_CLAUSE")
    assert "percentile" not in an._BAR_BAND_CLAUSE      # it names the FIGURE, not the missing rank
    cen = an._bind_bar_adjectives({"tldr": "Positioning is crowded here.", "mechanism": ""}, [])
    assert cen["adjectives_unbacked"] == 1 and cen["corrected"] == 0
    d = {"tldr": "CBOT corn managed-money net length is stretched at +1.8 sigma vs the 3-yr mean [N5].",
         "mechanism": ""}
    before = an._desk_digits(d["tldr"])
    an._bind_bar_adjectives(d, [])
    assert "[N5]" in d["tldr"] and "+1.8 sigma" in d["tldr"]
    assert an._desk_digits(d["tldr"]) == before, "no clause, so not one digit moves"
    assert d["tldr"].endswith("[N5].")          # the sentence ships exactly as the writer wrote it


def test_major4_the_recency_instruction_rides_the_leg_that_supplies_its_facts():
    """REVIEW MAJOR 4. The mandate shipped on a FLAG-ONLY gate, so its last movement -- three dated
    facts off the board block -- rode every flag-on turn including turns with no board and no recency
    leg. Measured: `_system(desk_register=True)` carried "board price tape" and "The RECENCY movement"
    while SYSTEM_STATE_BOARD_MANDATE and SYSTEM_RECENCY_CLAUSE were both absent."""
    flag_only = an._system(desk_register=True)
    assert "The RECENCY movement" not in flag_only and "board price tape" not in flag_only
    assert N.SYSTEM_STATE_BOARD_MANDATE not in flag_only
    both = an._system(desk_register=True, state_board=True)
    assert "The RECENCY movement" in both and "board price tape" in both
    # the BAN half is legitimately turn-wide: "the graph" leaks on a boardless cascade walk
    assert "no naming of the " in flag_only
    assert N.check_literals() == []


def test_major5_a_rewrite_cannot_invent_a_claim_on_a_sentence_that_carries_no_numeral():
    """REVIEW MAJOR 5. The five shipped refusals are digit-and-handle only. MEASURED over the nine
    banked answers: 59 of 113 offerable offending sentences (52.2%) carry NEITHER a digit NOR a handle,
    leaving "fewer instrument words" as the only acceptance test -- and those 59 are overwhelmingly the
    estate's honest-absence prose. Proved with an injected caller: this exact input was accepted as
    "Argentine rain has already broken the drought and prices will fall." and spliced into `mechanism`
    AFTER `verify_citations` had closed."""
    d = {"tldr": "", "mechanism": "The graph carries this in the same direction as price at high "
                                  "confidence."}
    call, _calls = _fake(["Argentine rain has already broken the drought and prices will fall."])
    out = an._desk_register_lint(d, call=call)
    assert out["rewritten"] == 0 and out["outcome"] == "unchanged"
    assert out["refused"] == {"vocabulary": 1}
    assert d["mechanism"].startswith("The graph carries this")


def test_major5_a_declared_absence_cannot_be_inverted_with_the_input_s_own_words():
    """Closed vocabulary alone cannot see a polarity flip, so the negation / absence token count is its
    own refusal. These are the estate's real honest-absence shapes.

    EVERY PROBE BODY MUST BE CHARGED, and the pin asserts it BEFORE it asserts the refusal. The first
    draft of this deck offered "So there is no current-state price read available on this turn." -- the
    banked sentence with its TAIL CLAUSE CUT OFF, and the tail is where the charged word lived. Shorn of
    "-- only the driver ROWS", the probe carried no banned token at all, so `_desk_register_lint`
    returned `clean` at `hits_before == 0`, never reached a caller, and the polarity assertion below
    graded a guard that had not run. A refusal pin whose input is never offered grades nothing, so the
    charged count and `offered == 1` are asserted first. The second body is now the banked sentence
    WHOLE (its em dash spelled ASCII), charged on `row`; the third is the estate's other honest-absence
    shape, charged twice on `board` and `state read` -- so the guard is graded both when the instrument
    word sits inside the negated clause and when it sits in the tail beyond it."""
    for body, reply in (
            ("The graph names no served series for drought or heat stress.",
             "Drought and heat stress names series."),
            ("So there is no current-state price read available on this turn -- only the driver rows.",
             "So there is a current-state price read available on this turn -- only the driver prints."),
            ("So there is no current-state read on the board for this turn.",
             "So there is a current-state read on the market for this turn.")):
        assert reg.count_desk_register(body) >= 1, body   # the lint must have something to offer
        d = {"tldr": "", "mechanism": body}
        call, _c = _fake([reply])
        out = an._desk_register_lint(d, call=call)
        assert out["offered"] == 1, (body, out)           # ... and it must have reached the caller
        assert out["rewritten"] == 0, (body, reply)
        assert "polarity" in (out.get("refused") or {}), out
        assert d["mechanism"] == body


def test_major5_a_deletion_is_not_a_rewrite():
    """The overlap and mass floors: a reply that keeps one content word in seven is a different
    sentence, and "The market." is a deletion wearing a substitution."""
    d = {"tldr": "", "mechanism": "The graph carries this in the same direction as price here."}
    call, _c = _fake(["The mechanism."])
    out = an._desk_register_lint(d, call=call)
    assert out["rewritten"] == 0 and set(out["refused"]) <= {"overlap", "mass"}


def test_major5_an_honest_register_substitution_is_still_accepted():
    """The guards must cost the remedy nothing it should have: every content word here comes from the
    offered sentence or from the replacement table the mandate itself teaches."""
    d = {"tldr": "", "mechanism": "Reading the board here, the loudest thing is weather."}
    call, _c = _fake(["Reading the market here, the largest move is weather."])
    out = an._desk_register_lint(d, call=call)
    assert out["rewritten"] == 1 and out["outcome"] == "rewritten" and out["hits_after"] == 0
    assert "refused" not in out


def test_major6_the_cut_and_reattach_closes_the_marker_in_both_directions():
    """REVIEW MAJOR 6. `split[f][i] = head + cand` accepted the reply with no structural check on `cand`
    itself, so three probes all shipped: a newline split one bullet into a bullet plus an orphan line
    (the "the page silently stops being a list" failure `_DESK_MARKER_RX` exists to prevent, arriving
    from the other side); a re-added marker yielded "- - The market..."; and a reply carrying its own
    terminator yielded "..", because the offered chunk's terminator lives in the `_SENT_KEEP`
    delimiter."""
    d = {"tldr": "", "mechanism": "- The board reads two-sided [N1]."}
    call, _c = _fake(["The market reads two-sided [N1]\nand a second line."])
    out = an._desk_register_lint(d, call=call)
    assert out["rewritten"] == 0 and out["refused"] == {"structure": 1}
    assert d["mechanism"] == "- The board reads two-sided [N1]."

    d = {"tldr": "", "mechanism": "- The board reads two-sided [N1]."}
    call, _c = _fake(["- The market reads two-sided [N1]."])
    an._desk_register_lint(d, call=call)
    assert d["mechanism"] == "- The market reads two-sided [N1].", d["mechanism"]

    d = {"tldr": "", "mechanism": "- The board reads two-sided [N1]. A second sentence here."}
    call, _c = _fake(["The market reads two-sided [N1]."])
    an._desk_register_lint(d, call=call)
    assert ".." not in d["mechanism"], d["mechanism"]
    assert d["mechanism"].startswith("- The market reads two-sided [N1]. A second"), d["mechanism"]


def test_the_verifier_off_lane_relieves_no_strike_it_cannot_correct():
    """REVIEW MINOR. `GRAPHRAG_VERIFY=off` is a documented rollback. The licence was threaded into BOTH
    strip passes unconditionally while `_bind_bar_adjectives` sat inside the verifier gate, so on that
    lane the strike was relieved and NO correction ran -- a bare unbacked valuation verdict shipped
    unqualified, worse than either arm. One predicate now."""
    assert an._bar_licence_for(lambda _s: "licensed", {"enabled": False}) is None
    assert an._bar_licence_for(lambda _s: "licensed", {}) is None
    sentinel = object()
    assert an._bar_licence_for(sentinel, {"enabled": True}) is sentinel


def test_the_persona_is_not_freed_on_a_lane_where_both_fences_still_strike(monkeypatch):
    """COHERENCE AUDIT 2026-09-16, adversarial review MAJOR 1 -- THE SAME DEFECT AS THE TEST ABOVE, IN
    THE THIRD CONSUMER.

    `_bar_licence_for` re-anchors the licence on the verifier's own dict, but it runs AFTER the model
    call; the persona's `register_licence` leg (WP-A4, which retires the cheap/rich strike the owner
    freed) is resolved BEFORE it. So on the documented `GRAPHRAG_VERIFY=off` rollback the writer was
    told the word was free while BOTH strip passes still struck at full force, and `reg.sanitize`
    deletes such a sentence together with its citation: suppress-not-correct, arriving through the one
    change written to prevent it. The lane is now ANDed at the licence's own seam, ONCE per body, in
    verify.py's own spelling -- so the charge, the remedy and the PROMPT answer to one predicate."""
    import inspect as _insp

    monkeypatch.delenv("GRAPHRAG_VERIFY", raising=False)
    assert an._verify_lane_enabled() is True                  # unset = on, verify.py's own default
    monkeypatch.setenv("GRAPHRAG_VERIFY", "on")
    assert an._verify_lane_enabled() is True
    monkeypatch.setenv("GRAPHRAG_VERIFY", "off")
    assert an._verify_lane_enabled() is False
    assert 'os.environ.get("GRAPHRAG_VERIFY", "on")' in _insp.getsource(an._verify_lane_enabled)
    assert 'os.environ.get("GRAPHRAG_VERIFY", "on") == "off"' in _insp.getsource(vf.verify_citations)
    for body in (an._answer_l2, an.answer):
        src = _insp.getsource(body)
        assert "if _register_licence_on() and _verify_lane_enabled():" in src, body.__name__
        assert src.count("register_licence=(_bar_licence is not None)") == 1, body.__name__
        assert "_bar_licence_for(" in src, body.__name__      # the re-anchor is KEPT, never replaced


def test_the_rewrite_s_cost_ceiling_is_a_number_the_census_is_graded_against():
    """REVIEW MINOR: the $0.038 arithmetic assumes a plain call, and `_call_opus` applies
    `synth_thinking`, `synth_effort` and an ephemeral cache breakpoint to every call it makes. So the
    ceiling is a CONSTANT and a measured cost above it stamps `over_ceiling` -- the smoke reads the real
    number rather than the comment's arithmetic."""
    assert an._DESK_REWRITE_USD_CEILING == 0.05
    src = __import__("inspect").getsource(an._desk_register_lint)
    assert "over_ceiling" in src and "_DESK_REWRITE_USD_CEILING" in src
    import leviathan.graphrag.answer as _a
    blk = __import__("inspect").getsource(_a).split("_DESK_REWRITE_MAX_SENTENCES = 10")[0]
    assert "synth_thinking" in blk and "cache_control" in blk, "the interaction must be STATED"


def test_the_lint_s_field_scope_is_stated_rather_than_implied():
    """REVIEW MINOR: the production lint reads `tldr` + `mechanism`, while the 195/192 baselines are
    measured over the whole served body (`render()` also emits the mermaid block and the sources list,
    and `_footer` is appended OUTSIDE the sanitize input). The two numbers are different populations."""
    doc = an._desk_register_lint.__doc__
    assert "tldr" in doc and "mechanism" in doc and "_footer" in doc
    d = {"tldr": "The board is loud.", "mechanism": "", "sources": "The board is loud."}
    out = an._desk_register_lint(d, call=None)
    assert out["hits_before"] == 2 and out["outcome"] == "no_caller"


# ══ S7b R2 ROUND-3: A ONE-WORD BUDGET IS A ONE-WORD CLAIM EDIT ═══════════════════════════════════════
#: The verifier's adversarial replies, (why, offered body, model reply). Every one was ACCEPTED and
#: spliced into `mechanism` AFTER `verify_citations` had closed, passing all nine shipped refusals.
ROUND3_CLAIM_EDITS = (
    ("direction", "The graph carries this in the same direction as price at high confidence.",
     "The mechanism carries this in the opposite direction as price at high confidence."),
    ("confidence", "The graph carries this in the same direction as price at high confidence.",
     "The mechanism carries this in the same direction as price at low confidence."),
    ("reading", "The board reads two-sided here.", "The market reads bullish here."),
    ("reading (a fenced word, at that)", "The board reads two-sided here.",
     "The market reads stretched here."),
    ("magnitude", "The board is the loudest driver on cocoa here.",
     "The market is the weakest driver on cocoa here."),
    ("hedge", "The board may be two-sided here.", "The market is two-sided here."),
    ("date", "The board is read through the knowledge date of September 2026.",
     "The market is read through the date of October 2026."),
)
ROUND3_DELETIONS = (
    ("a driver", "The board reads two-sided here and drought risk is rising.",
     "The market reads two-sided here and risk is rising."),
    ("a market", "The board is the loudest driver on corn and on wheat and on cocoa here.",
     "The market is the largest move on corn and on wheat here."),
)


def test_round3_every_claim_probe_is_actually_offered_to_the_rewrite():
    """ROUND 2's LESSON FIRST, AGAIN: a refusal pin whose body is never CHARGED grades a guard that
    never ran. Each body below is asserted charged and `offered == 1` before any refusal is read."""
    for why, body, cand in ROUND3_CLAIM_EDITS + ROUND3_DELETIONS:
        assert reg.count_desk_register(body) >= 1, (why, body)
        d = {"tldr": "", "mechanism": body}
        call, _c = _fake([cand])
        out = an._desk_register_lint(d, call=call)
        assert out["offered"] == 1, (why, out)


def test_round3_a_one_word_budget_cannot_buy_a_claim():
    """GUARD (10). The budget of ONE new content word is exactly what one claim edit costs, and every
    one of these passes the nine shipped refusals: modals are `_DESK_STOPWORDS` so the vocabulary and
    overlap guards cannot see a deleted hedge; `_desk_digits` compares NUMERALS so a month name moves a
    date without moving a digit; and 'opposite' / 'low' / 'bullish' / 'weakest' each cost exactly one
    word. The closed class is conserved as a MULTISET OF WORDS, never of classes -- a per-class count
    would read 'high' -> 'low' as one degree word for one degree word."""
    for why, body, cand in ROUND3_CLAIM_EDITS:
        d = {"tldr": "", "mechanism": body}
        call, _c = _fake([cand])
        out = an._desk_register_lint(d, call=call)
        assert out["rewritten"] == 0, (why, cand)
        _r = out.get("refused") or {}
        assert set(_r) & {"claim", "polarity"}, (why, out)
        # ...and the LABEL is the one the ruling names: an antonym swap is `polarity`, a word from
        # nowhere is `claim`. Asserted per probe rather than as a set, so a guard that started naming
        # every refusal the same way would redden here.
        assert ("polarity" in _r) == an._desk_claim_flip(body, cand), (why, _r)
        assert d["mechanism"] == body, why


def test_round3_a_deleted_clause_is_not_a_register_substitution():
    """GUARD (11). A BUDGET COULD NOT SEPARATE THESE FROM AN HONEST REWRITE: the deck's own honest
    substitution drops TWO content words and these drop ONE, so the test is WHERE the word sat. A word
    within `_DESK_LOSS_WINDOW` of a charged span is part of the phrase being replaced; 'drought' sits
    six words from `board` and 'cocoa' nine from `loudest`."""
    for why, body, cand in ROUND3_DELETIONS:
        d = {"tldr": "", "mechanism": body}
        call, _c = _fake([cand])
        out = an._desk_register_lint(d, call=call)
        assert out["rewritten"] == 0, (why, cand)
        assert "loss" in (out.get("refused") or {}), (why, out)
        assert d["mechanism"] == body, why


def test_round4_the_rewrite_is_substitution_only_and_here_is_what_that_costs():
    """OWNER RULING (5): a reply is accepted ONLY if it is the offered sentence with its BANNED TOKENS
    replaced by the TABLE's own phrases. The ACCEPTED column is the honest substitutions -- including a
    partial one, which keeps a banned word but removes another and touches nothing else. The REFUSED
    column is the honest rewrites that RESTRUCTURE, and it is pinned rather than hidden: that is the
    measured price of the rule, and the price is paid in a sentence the writer keeps rather than in one
    the page loses."""
    for why, body, cand in (
            ("the table's own replacement", "The board is the loudest driver on cocoa here.",
             "The market is the largest move on cocoa here."),
            ("a table phrase used in part", "The state read on this node is thin.",
             "The latest print on this driver is thin."),
            ("a plural fold", "Two rows have spent their day.",
             "Two records have spent their day."),
            ("two tokens, one of them left alone", "Two rows have spent their knowledge date.",
             "Two records have spent their knowledge date.")):
        d = {"tldr": "", "mechanism": body}
        call, _c = _fake([cand])
        out = an._desk_register_lint(d, call=call)
        assert out["rewritten"] == 1, (why, out.get("refused"))
        assert "refused" not in out, (why, out)
        assert d["mechanism"] == cand, why
    for why, body, cand, reason in (
            ("it restructures the clause", "Two rows have spent their knowledge date.",
             "Two series are read through older dates.", "edit_outside_table"),
            ("it drops a content word outside the table",
             "Reading the board at 2026-09-07, the loudest thing on ICE cocoa is West African weather.",
             "As of 2026-09-07, the largest move on ICE cocoa is West African weather.",
             "edit_outside_table"),
            # ...and this one is refused by a COARSER guard that ran first, which is this module's own
            # stated ordering rule -- the reply is refused either way, and `_desk_substitution_only`
            # says no about it independently.
            ("it edits a word outside a charged span",
             "The board is the loudest driver on cocoa here.",
             "The market is the largest move on cocoa there.", "overlap")):
        d = {"tldr": "", "mechanism": body}
        call, _c = _fake([cand])
        out = an._desk_register_lint(d, call=call)
        assert out["rewritten"] == 0, (why, out)
        assert reason in (out.get("refused") or {}), (why, out)
        assert not an._desk_substitution_only(body, cand), why
        assert d["mechanism"] == body, why


def test_round3_the_claim_class_exempts_the_mandates_own_table_and_the_charged_words():
    """Two exemptions and both are the instrument's own. The body's CHARGED spans are masked (the
    rewrite exists to lose those words -- 'the LOUDEST thing' is charged and must be replaceable), and
    any surface the replacement table teaches is dropped from both sides, so 'the largest move, the
    reading furthest from its own record' is not read as a magnitude edit."""
    assert an._desk_claim_terms("The board is the loudest driver here.") == []   # 'loudest' is charged
    assert an._desk_claim_terms("The market is the largest move here.") == []    # 'largest' is taught
    assert an._desk_claim_terms("The market is the weakest driver here.") == ["weakest"]
    assert an._desk_claim_terms("It reads two-sided here.") == ["two-sided"]
    assert an._desk_claim_terms("It reads two sided here.") == ["two-sided"]     # one surface, folded
    assert an._desk_claim_terms("It may be high here.") == ["high", "may"]
    for w in ("largest", "furthest", "reading", "move"):
        assert an._desk_stem(w) in an._desk_allowed_stems(), w


def test_round3_the_loss_window_is_placed_by_span_and_never_by_a_stem_list():
    """`loud` charges 'loudest', whose stem is not 'loud' -- the same reason
    `_desk_content_ex_instrument` reads spans. An unplaceable mask returns the EMPTY set, so the guard
    refuses every loss rather than permitting one it could not place."""
    los = an._desk_losable_stems("The board reads two-sided here and drought risk is rising.")
    assert "board" in los and "read" in los and "two" in los
    assert "drought" not in los and "rising" not in los
    los2 = an._desk_losable_stems("Two rows have spent their knowledge date.")
    assert "spent" in los2 and "knowledge" in los2
    assert an._desk_losable_stems("The market rallied.") == frozenset()   # no charged span, no permission
    assert an._DESK_LOSS_WINDOW == 2


def test_round3_the_coarser_reason_is_reported_first():
    """The two new guards are asked LAST. Every guard above them names a COARSER failure of the same
    reply -- a deletion ('The mechanism.') also moves a claim word, an inverted absence also drops one
    -- and the census' `refused` map is read by a human deciding what the rewrite is doing wrong. The
    reply is refused either way, which is the only thing the page ever sees."""
    d = {"tldr": "", "mechanism": "The graph carries this in the same direction as price here."}
    call, _c = _fake(["The mechanism."])
    out = an._desk_register_lint(d, call=call)
    assert out["rewritten"] == 0 and set(out["refused"]) <= {"overlap", "mass"}
    d2 = {"tldr": "", "mechanism": "The graph names no served series for drought or heat stress."}
    call2, _c2 = _fake(["Drought and heat stress names series."])
    out2 = an._desk_register_lint(d2, call=call2)
    assert out2["rewritten"] == 0 and "polarity" in out2["refused"]


# ══ ROUND 4 (2026-09-15) -- THE REMEDY'S OWN THREE. ══════════════════════════════════════════════════
def _r4_call(pct=3.0, kd="2026-09-05", asof="2026-09-07", commodity="corn_cbot"):
    from leviathan.graphrag.state import render as _rd
    return _rd.sb_call(period="2026-09", asof=asof, table="silver_cot", metric="mm_net",
                       commodity=commodity, country="United States", value=pct, unit="percentile",
                       knowledge_date=kd)


def test_round4_a_stale_row_neither_licenses_nor_contradicts():
    """OWNER RULING (3): "the freshness bound stays (a stale row cannot license nor contradict)". A row
    past its card's own promise is still `weak_adjective` -- the census counts it and the report carries
    its date for the trace -- but NOTHING is appended to the page: a fifteen-year-old percentile is not
    a figure a correcting clause may quote at a reader. Round 3 appended the date here; the ruling
    retired that clause with the other two."""
    base = "Corn positioning is crowded [N1]."
    d = {"tldr": base, "mechanism": ""}
    cen = an._bind_bar_adjectives(d, [_r4_call(55.0, kd="2011-01-04")])
    assert cen["weak"] == 1 and cen["corrected"] == 0 and cen["adjectives_unbacked"] == 0
    assert d["tldr"] == base
    assert vf.bar_adjective_report(base, [_r4_call(55.0, kd="2011-01-04")])["stale"] == "2011-01-04"
    # a FRESH row that CLEARS the bar takes no clause either, and a fresh row that does not earns one
    d2 = {"tldr": base, "mechanism": ""}
    cen2 = an._bind_bar_adjectives(d2, [_r4_call(3.0, kd="2026-09-05")])
    assert cen2["licensed"] == 1 and d2["tldr"] == base
    d3 = {"tldr": base, "mechanism": ""}
    cen3 = an._bind_bar_adjectives(d3, [_r4_call(55.0, kd="2026-09-05")])
    assert cen3["corrected"] == 1 and d3["tldr"] != base
    assert reg.register_leaks(d3["tldr"]) == [] and reg.desk_register_hits(d3["tldr"]) == []


def test_round4_an_ordered_marker_is_stripped_not_spliced():
    """MINOR (2026-09-15). `_DESK_MARKER_RX` held the three UNORDERED shapes, so a reply of
    "a) The market reads ..." passed every guard and spliced to "- a) The market reads ...", a corrupted
    list item on the served page. The three ordered shapes join it; the marker still rides back from
    the BODY exactly once."""
    for lead in ("a) ", "A. ", "1. ", "iv) "):
        assert an._DESK_MARKER_RX.match(lead + "The market reads two-sided here [N2].").end() == len(lead)
    d = {"tldr": "", "mechanism": "- The board reads two-sided here [N2]."}
    call, _c = _fake(["a) The market reads two-sided here [N2]."])
    out = an._desk_register_lint(d, call=call)
    assert out["rewritten"] == 1, out
    assert d["mechanism"] == "- The market reads two-sided here [N2]."


def test_round4_the_over_ceiling_stamp_is_a_report_and_not_a_refusal():
    """MINOR (2026-09-15), stated rather than changed. The cost is only knowable after the call
    RETURNS, so refusing the reply cannot refund it; what the census owes the smoke is the MEASURED
    number and a flag, which is what it stamps."""
    d = {"tldr": "", "mechanism": "The board reads two-sided here [N2]."}
    call, _c = _fake(["The market reads two-sided here [N2]."],
                     usage={"model": "claude-opus-5", "in": 2_000_000, "out": 2_000_000})
    out = an._desk_register_lint(d, call=call, model="claude-opus-5")
    assert out["outcome"] == "rewritten" and out["rewritten"] == 1
    assert out.get("over_ceiling") is True and out["usd"] > an._DESK_REWRITE_USD_CEILING
    assert d["mechanism"] == "The market reads two-sided here [N2]."


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# 3. S8 LANE N -- THE FIFTH MOVEMENT, "THE CHAIN" (DESIGN B.5)
#
# TWO HALVES, exactly as section 1 holds them for the desk register:
#   FLAG OFF -- `state_board_mandate()` and `state_board_mandate(nonobvious=True)` are HEAD's bytes,
#               the constant never learns the paragraph, the movement table never grows a row, and
#               `_system` cannot move because no leg in `answer.py` threads the kwarg in this lane.
#   FLAG ON  -- the paragraph lands as movement (3), SPILLOVERS and WATCH renumber, the non-obvious
#               WATCH variant survives the renumbering, and every literal rule `check_literals` grades
#               is PROVED TO FIRE rather than merely observed to pass.
# ══════════════════════════════════════════════════════════════════════════════════════════════════
_HEAD_MANDATE = N.SYSTEM_STATE_BOARD_MANDATE
_HEAD_NONOBVIOUS = _HEAD_MANDATE.replace(N.MANDATE_WATCH_HEAD_RX, N.MANDATE_WATCH_NONOBVIOUS)


def test_chain_the_flag_off_mandate_is_HEAD_byte_for_byte_on_both_arms():
    """S8's prompt-side byte-identical set, at the function level: absent and explicitly-False are the
    same bytes, on BOTH watch arms, and both are HEAD's own text.

    THIS IS THE ARM'S WHOLE INSTRUMENT. Arm A measures ONE thing, so a board-ON / chain-OFF turn must be
    byte-identical to the 2026-09-16 smoke or nothing it reports can be attributed."""
    assert N.state_board_mandate() == _HEAD_MANDATE
    assert N.state_board_mandate(chain=False) == _HEAD_MANDATE
    assert N.state_board_mandate(nonobvious=True) == _HEAD_NONOBVIOUS
    assert N.state_board_mandate(nonobvious=True, chain=False) == _HEAD_NONOBVIOUS
    assert N.MANDATE_CHAIN_MOVEMENT not in N.state_board_mandate()
    assert N.MANDATE_CHAIN_MOVEMENT not in N.state_board_mandate(nonobvious=True)


def test_chain_the_assembled_system_prompt_cannot_move_in_this_lane():
    """THE SEAM IS LANE A's AND THIS LANE PROVES IT HAS NOT MOVED. `answer._system` threads only
    `nonobvious` today, so every combination of the legs this deck can reach still carries HEAD's
    mandate and none of them carries the chain paragraph. When lane A adds `state_chain`, THIS is the
    assertion that has to be extended rather than deleted."""
    for kw in ({}, {"state_board": True}, {"state_board": True, "watch_selection": True},
               {"state_board": True, "desk_register": True}, {"state_board": True, "handles": True}):
        out = an._system(**kw)
        assert N.MANDATE_CHAIN_MOVEMENT not in out, kw
        assert "(3) THE CHAIN" not in out, kw
    assert _HEAD_MANDATE in an._system(state_board=True)
    assert _HEAD_NONOBVIOUS in an._system(state_board=True, watch_selection=True)


def test_chain_the_movement_lands_as_three_and_renumbers_the_two_below_it():
    """DESIGN B.5: the movement goes BETWEEN EVIDENCE and SPILLOVERS. Renumbering is arithmetic and it
    is graded as arithmetic -- five movements, one to five, each exactly once, in the text that ships."""
    lit = N.state_board_mandate(chain=True)
    assert re.findall(r"\(\d\) [A-Z][A-Z ]*:", lit) == ["(1) DIRECTION:", "(2) EVIDENCE:",
                                                        "(3) THE CHAIN:", "(4) SPILLOVERS:",
                                                        "(5) WATCH:"]
    assert "(3) SPILLOVERS" not in lit and "(4) WATCH" not in lit
    assert "Cover these five movements" in lit and "Cover these four movements" not in lit
    assert N.MANDATE_CHAIN_MOVEMENT in lit
    # the JOIN is grammatical at both ends -- a substitution that welded two clauses is a defect of the
    # shipped text and of nothing smaller
    assert "another. (3) THE CHAIN: take the chains" in lit
    assert "named first. (4) SPILLOVERS: name the other markets" in lit


def test_chain_the_non_obvious_watch_variant_survives_the_renumbering():
    """BOTH FLAGS LIT IS A REAL TURN and the two substitutions must compose. The watch needle is cut
    against HEAD's `(4) WATCH`; the chain pass renumbers it to `(5)`. Applied the wrong way round the
    watch variant would silently stop shipping on exactly the turns that lit both flags."""
    both = N.state_board_mandate(nonobvious=True, chain=True)
    assert N.MANDATE_WATCH_NONOBVIOUS.replace("(4) WATCH", "(5) WATCH") in both
    assert "the next scheduled print" not in both          # HEAD's watch movement is gone
    assert "the items the block nominates" in both
    assert N.MANDATE_CHAIN_MOVEMENT in both
    # and the chain-only arm keeps HEAD's watch movement, renumbered and otherwise untouched
    chain_only = N.state_board_mandate(chain=True)
    assert N.MANDATE_WATCH_HEAD_RX.replace("(4) WATCH", "(5) WATCH") in chain_only


def test_chain_a_reworded_mandate_reds_loudly_rather_than_renumbering_nothing():
    """THE NEEDLES ARE ASSERTED, `response_contracts.apply`'s own reason. A mandate reworded in another
    lane must fail HERE, at build, not quietly ship a paragraph numbered (3) beside a SPILLOVERS still
    numbered (3)."""
    for gone in (N.MANDATE_COUNT_RX, N.MANDATE_SPILLOVERS_RX, N.MANDATE_WATCH_NUMBER_RX):
        broken = _HEAD_MANDATE.replace(gone, gone.replace("(", "[").replace(")", "]")
                                       if "(" in gone else gone.upper())
        saved = N.SYSTEM_STATE_BOARD_MANDATE
        try:
            N.SYSTEM_STATE_BOARD_MANDATE = broken
            with pytest.raises(AssertionError):
                N.state_board_mandate(chain=True)
        finally:
            N.SYSTEM_STATE_BOARD_MANDATE = saved
    assert N.state_board_mandate(chain=True)               # and the real one still renders


def test_chain_the_movement_table_is_flag_scoped_like_the_literal_it_describes():
    """`MANDATE_MOVEMENTS`' standing claim -- graded by `test_state_render.py`'s B15 deck -- is that
    every movement it names appears in `SYSTEM_STATE_BOARD_MANDATE`. The chain movement does NOT appear
    there and must not, so the table is flag-scoped too and `mandate_movements` is the ONE producer."""
    assert N.mandate_movements() is N.MANDATE_MOVEMENTS
    chained = N.mandate_movements(chain=True)
    assert [m[0] for m in chained] == ["DIRECTION", "EVIDENCE", "CHAIN", "SPILLOVERS", "WATCH"]
    assert chained[2] == N.MANDATE_CHAIN_ROW == ("CHAIN", "## Mechanism", "")
    # B15's three rules, re-graded on the text the chain row actually ships with
    from leviathan.graphrag import response_contracts as RC
    known = set(RC.CANONICAL) | {v for v in vars(RC).values()
                                 if isinstance(v, str) and v.startswith("## ")}
    known |= {x for v in vars(RC).values() if isinstance(v, (tuple, list, frozenset, set))
              for x in v if isinstance(x, str) and x.startswith("## ")}
    lit = N.state_board_mandate(chain=True)
    for movement, heading, fallback in chained:
        assert movement in lit
        assert heading in known, heading               # never a heading the contract does not own
        if fallback:
            assert fallback in RC.CANONICAL


def test_chain_the_movement_is_desk_clean_and_that_is_a_BUILD_rule():
    """THE LANE'S OWN MEASUREMENT, made mechanical (`narration._check_chain_movement`).

    The chain movement and the desk-register mandate ship in the SAME system prompt on a lit turn, so a
    movement that said "the graph" or "the rows" would order the writer to disobey the literal beside
    it. It is written in the reader's words from the first draft rather than reworded after a lint
    charged it -- the table teaches a replacement for every word it avoids."""
    m = N.MANDATE_CHAIN_MOVEMENT
    assert reg.count_desk_register(m) == 0, reg.desk_register_hits(m)
    assert reg.desk_register_hits(m) == []
    assert reg.register_leaks(m) == [] and reg.count_flow_words(m) == 0
    assert reg.count_valuation_words(m) == 0 and not reg._LANE_B_ADJ.search(m)
    for w in N.CHAIN_MOVEMENT_BANNED_WORDS:
        assert w not in m.lower(), w
    assert N.CHAIN_MOVEMENT_BANNED_WORDS == ("loud", "rank", "score", "board")
    m.encode("ascii")
    assert "{" not in m and "}" not in m
    assert N.BANNED_RECENCY_PHRASE not in m
    # THE ONE DIGIT IS THE MOVEMENT'S OWN ENUMERATOR, which is structural and not a magnitude -- the
    # same decision `check_literals` records for "(1) DIRECTION ... (4) WATCH".
    assert [c for c in m if c.isdigit()] == ["3"]


def test_chain_check_literals_is_PROVED_to_fire_on_the_new_literal():
    """A lint that has never been seen to fail is a lint nobody has tested (this deck's own law, and
    `test_state_lint.py`'s). Every rule `_check_chain_movement` adds is tripped here."""
    assert N.check_literals() == []
    saved = N.MANDATE_CHAIN_MOVEMENT
    cases = {
        "the graph declares": "the graph",             # a desk-register charge
        "the loudest hop":    "loud",                  # the instrument's selection vocabulary
        "rank the chains":    "rank",
        "score the chains":   "score",
        "read the board":     "board",
        "not a current-state read": "recency",         # the one sentence a board may never contain
        "narrate {k} of them":      "format slot",     # only the ledger sentence carries one
        "narrate two of them — hop by hop": "ascii",   # the file is UTF-8, the literal is ASCII
    }
    try:
        for bad, why in cases.items():
            N.MANDATE_CHAIN_MOVEMENT = "(3) THE CHAIN: " + bad + " and stop."
            errs = N.check_literals()
            assert errs, (bad, why)
            assert any("MANDATE_CHAIN_MOVEMENT" in e or "chain" in e for e in errs), (errs, why)
            if why == "format slot":
                assert any("format slot" in e for e in errs), errs
            if why == "ascii":
                assert any("not ASCII" in e for e in errs), errs
    finally:
        N.MANDATE_CHAIN_MOVEMENT = saved
    assert N.check_literals() == []


def test_chain_a_renumbering_that_lost_a_movement_is_caught_by_arithmetic():
    """The register detectors cannot see a movement numbered twice or a movement dropped. The count
    clause can, and it grades the LITERAL against the TABLE so the two can never disagree about how
    many movements ship."""
    saved = N.MANDATE_CHAIN_MOVEMENT
    try:
        N.MANDATE_CHAIN_MOVEMENT = "(2) THE CHAIN: take the chains the block puts first and stop."
        errs = N.check_literals()
        assert any("numbers movement" in e for e in errs), errs
    finally:
        N.MANDATE_CHAIN_MOVEMENT = saved
    assert N.check_literals() == []


@pytest.mark.parametrize("clause", [
    # the hop-by-hop narration, in the present tense, off the block's own order
    "take the chains the block puts first, in the order it gives them",
    "hop by hop, in the present tense",
    "give the figure in its unit and the plain meaning in the same sentence",
    "which way the driver model declares that hop pushes the next one",
    # the agreement WORD comes from the block, never from the writer
    "agree with that declared direction or run against it -- the block gives you the word",
    # the receipt, by handle, with its date -- and the honest absence beside it (threat E6)
    "Cite the chain's dated report at the hop it acts on, by its handle, and say when it is dated",
    "where the block says no dated document reaches a hop's window, say so",
    # the record: a COUNT with its sample size, in the past tense (threat E7)
    "the block's own count of past firings and how many moved the declared way",
    "history, never a forecast",
    # the OUTCOME line the owner added, as history and never as a forecast
    "give the chain's own outcome line the same way, as what measured after those firings",
    "never as what is coming",
    # the RELATIVE-VALUE call the owner added -- one sentence, or an honest refusal to settle it
    "Where the question sets one market against another, make the call on the pair",
    "which of the two the record leans toward and the reading that carries it",
    "saying plainly that the record does not settle it",
    # anti-padding (threat E2) and the count line
    "Narrate the chains the block puts first and not the rest of the driver model",
    "where the block prints a count of further chains, state the count and move on",
    # ROUND 2, review MAJOR 4: the chain under the print line is RENDERED IN ONE LINE, never dropped,
    # so the writer is ordered to give it its sentence -- the other half of the 2026-09-17 deviation
    "Where the block carries a chain in one line instead of in full, that chain still gets its "
    "sentence",
    "a turn whose block carries a chain never reaches the reader without one",
    # ROUND 2, ORCHESTRATOR_NOTES item 6: the arithmetic line states the DATA SCOPE, and a short one
    # reads as scarce data and never as a weak chain
    "Where the block states what it could read for a chain",
    "the terms it could do the arithmetic for, the hops no series served, a buffer series this "
    "market does not carry",
    "what this market's data covers on this turn, never that the chain itself is a weak one",
    # the two consequences B.5 names: the record does not restate, and the stanza is the chain's THEN
    "Do not restate under the record a reading this movement has already given its figure to",
    # ROUND 2, review MAJOR 3: the like-state attribution is CONDITIONED on the block's own marker
    "where the block marks a LIKE STATE stanza as the chain's, read that stanza as the history of "
    "the chain you named first",
])
def test_chain_every_clause_DESIGN_B5_names_is_in_the_shipped_movement(clause):
    """B.5's paragraph, clause for clause. The WORDS are the reader's (the desk-register table's own
    replacements) and the SUBSTANCE is the design's -- this is the pin that keeps the second true while
    the first is edited."""
    assert clause in N.MANDATE_CHAIN_MOVEMENT


def test_chain_the_like_state_attribution_is_CONDITIONAL_and_both_states_are_pinned():
    """REVIEW MAJOR 3. DESIGN C.2's sentence is true only where the stanza carries the top chain's own
    receipt hop, and `analogs.analog_rows(..., first_dim=None)` has NO caller in `state/` that passes
    it -- measured on this tree. Unconditioned, the mandate ORDERED the writer to read whichever
    stanza the selector picked as the history of a chain it may have nothing to do with: threat E11's
    cross-attribution arriving through the prompt instead of through a join.

    BOTH STATES ARE PINNED and the sentence is written so that ONE sentence covers them:

      UNWIRED (today)  -- the block marks no stanza, the condition is not met, and the writer is given
                          NO attribution to make. The literal must therefore carry the marker clause.
      WIRED (lane R)   -- the block marks the stanza as the chain's, the condition is met, and the
                          same sentence orders exactly what C.2 asks for. The literal must therefore
                          NOT name `first_dim`, a flag or any wiring, or it would go stale on the
                          commit that satisfies it."""
    m = N.MANDATE_CHAIN_MOVEMENT
    assert "where the block marks a LIKE STATE stanza as the chain's" in m
    assert "read that stanza as the history of the chain you named first" in m
    # the UNCONDITIONED order is gone in every spelling it could survive in
    assert "read a LIKE STATE stanza as the history" not in m
    assert "read the LIKE STATE stanza as the history" not in m
    # and the clause names no wiring, so lane R's commit cannot make it false
    for wiring in ("first_dim", "GRAPHRAG_", "flag", "kwarg", "analog_rows"):
        assert wiring not in m, wiring
    # it is still the LAST clause of the movement, so the join into (4) SPILLOVERS is the pinned one
    assert m.rstrip().endswith("read that stanza as the history of the chain you named first.")
    assert "you named first. (4) SPILLOVERS: name the other markets" in N.state_board_mandate(
        chain=True)


def test_chain_the_top_chain_is_NARRATED_even_when_the_block_gives_it_one_line():
    """REVIEW MAJOR 4, and the orchestrator's 2026-09-17 deviation carried all the way to the prompt.
    The print line decides FULL versus ONE LINE and never ZERO -- `render.sb_chain_one_line` is called
    for every `rendered and not full` chain -- so a block that carries a chain ALWAYS carries at least
    one. HEAD's paragraph ordered the writer to narrate "the ones it renders in full" and to state a
    COUNT of the rest, and a one-line chain is NEITHER: on a thin turn the writer had no order to
    mention a chain at all.

    THE NEGATIVE PIN THE ORCHESTRATOR ASKED FOR, on this lane's own half: the movement must order the
    sentence for the one-line chain, and it must not make narrating a chain conditional on the block
    rendering it in full. (The render half of that pin -- a fixture board whose top chain sits below
    the print line renders ONE LINE -- is `tests/unit/test_state_chain_render.py`'s, lane R's file.)"""
    m = N.MANDATE_CHAIN_MOVEMENT
    assert "in one line instead of in full" in m
    assert "that chain still gets its sentence" in m
    assert "never reaches the reader without one" in m
    # the count clause is still there and is still about the REST -- the one-line chain is not a count
    assert "where the block prints a count of further chains, state the count and move on" in m
    assert m.index("in one line instead of in full") > m.index("state the count and move on")
    # and the order is unconditional on the block's own rendering: "renders in full" appears ONCE, in
    # the opening clause, and the one-line sentence is what covers the rest
    assert m.count("renders in full") == 1


def test_chain_the_arithmetic_line_is_read_as_DATA_SCOPE_and_never_as_a_weak_chain():
    """ORCHESTRATOR_NOTES item 6, applied to the mandate's words. The rank is RELATIVE WITHIN ONE
    BOARD, so a data-poor anchor still gets its best chains and the arithmetic line states the SCOPE:
    the terms it could do, the hops no series served, the buffer series this market does not carry. A
    reader handed a short arithmetic line with no scope beside it reads it as a weak chain, which is
    the one thing the ruling says it is not.

    AND IT SAYS SO WITHOUT THE INSTRUMENT'S OWN WORD FOR THE TOTAL: `score` is the third entry of
    `CHAIN_MOVEMENT_BANNED_WORDS`, so the clause states what the total MEANS instead of naming it."""
    m = N.MANDATE_CHAIN_MOVEMENT
    assert "Where the block states what it could read for a chain" in m
    assert "the terms it could do the arithmetic for" in m
    assert "the hops no series served" in m
    assert "a buffer series this market does not carry" in m
    assert "what this market's data covers on this turn, never that the chain itself is a weak one" in m
    for w in N.CHAIN_MOVEMENT_BANNED_WORDS:
        assert w not in m.lower(), w


def test_chain_the_flag_scoped_TABLE_and_the_flag_scoped_LITERAL_agree_in_both_states():
    """THE ORCHESTRATOR'S DEVIATION, PINNED AS BUILT. `MANDATE_MOVEMENTS` keeps FOUR rows and the fifth
    is produced only under `chain=True`, because the table's standing claim -- graded by
    `test_state_render.py`'s B15 deck -- is that every movement it names appears in the literal it
    describes. A chain row appears only when the chain paragraph is in the literal, and that is
    asserted here in BOTH directions rather than in the one that happens to ship.

    AND THE FLAG-OFF LITERAL IS PINNED BY ITS BYTES, not by a comparison with itself: a sha256 banked
    on 2026-09-18 against the constant this tree carries, which the r2 census proved byte-identical to
    HEAD (`cen/byteid_system.out`, 790 cells / 0 differing, object identity preserved)."""
    import hashlib
    assert N.mandate_movements() is N.MANDATE_MOVEMENTS
    assert len(N.MANDATE_MOVEMENTS) == 4
    assert [m[0] for m in N.MANDATE_MOVEMENTS] == ["DIRECTION", "EVIDENCE", "SPILLOVERS", "WATCH"]
    assert N.MANDATE_CHAIN_ROW not in N.MANDATE_MOVEMENTS
    # the table DESCRIBES the literal, in both states
    for chain in (False, True):
        lit = N.state_board_mandate(chain=chain)
        for movement, _h, _f in N.mandate_movements(chain=chain):
            assert movement in lit, (chain, movement)
        assert ("CHAIN" in lit) is chain
    # THE FLAG-OFF BYTES, banked
    assert hashlib.sha256(N.SYSTEM_STATE_BOARD_MANDATE.encode("utf-8")).hexdigest() == (
        "26cf673ec832026dc0315e11d1fd7b211440bf10759f86791e3d0d1802c8dc4f")
    assert N.state_board_mandate() is N.SYSTEM_STATE_BOARD_MANDATE
    assert len(N.SYSTEM_STATE_BOARD_MANDATE) == 3495


def test_chain_the_movement_carries_no_word_budget():
    """DESIGN B.5, stated: length follows from SELECTION, not from a number. The measured note is
    1,145-1,833 words against a 150-220-word budget nobody obeys, so the movement gains the anti-padding
    SENTENCE and no count; lane E measures whether that alone moves the length."""
    low = N.MANDATE_CHAIN_MOVEMENT.lower()
    for budget in ("no more than", "at most ", "keep it to", "in under", "words or fewer",
                   "sentences or fewer", "a paragraph each"):
        assert budget not in low, budget
    # the only digit in the literal is the movement's own enumerator, which is the same proof one
    # assertion over: a budget cannot be stated without a number.
    assert [c for c in N.MANDATE_CHAIN_MOVEMENT if c.isdigit()] == ["3"]
