"""Trivial-turn classifier (F1) — intent.is_trivial: pure regex, no spend, no I/O.

FALSE POSITIVES ARE THE FAILURE MODE: a real question that merely opens with a greeting must fall through.
Guard (i) is a FULL-STRING anchor (the whole message must BE a greeting/smalltalk/meta phrase); guard (ii) is
the _NUM/_REASON data-cue backstop. The escaping-vocabulary rows below are the ones that slip guard (ii) and
are caught ONLY by the full-string anchor (verifier F3) — without them the anchor is unverified.
"""
from __future__ import annotations

from leviathan.graphrag import intent as it


# ── POSITIVE: the whole message IS a trivial phrase -> a non-None class ────────────────────────────────────
def test_greetings_classify_greeting():
    for q in ("hi", "hello", "hey", "hello there", "hi there!", "good morning", "good afternoon",
              "good evening", "howdy", "yo", "hey team"):
        assert it.is_trivial(q) == "greeting", q


def test_smalltalk_classify_smalltalk():
    for q in ("thanks", "thanks!", "thank you", "thanks so much", "thx", "ty", "cheers",
              "ok thanks", "much appreciated", "appreciate it", "bye", "goodbye", "see you", "good night"):
        assert it.is_trivial(q) == "smalltalk", q


def test_meta_classify_meta():
    for q in ("who are you", "what can you do", "what do you do", "what do you cover",
              "what data do you have", "what can i ask", "help", "what can you help with"):
        assert it.is_trivial(q) == "meta", q


def test_trailing_punctuation_and_whitespace_tolerated():
    assert it.is_trivial("  hello!!  ") == "greeting"
    assert it.is_trivial("thanks...") == "smalltalk"
    assert it.is_trivial("who are you?") == "meta"


# ── FALL-THROUGH (None): a real question, empty, or a greeting glued to a real ask ─────────────────────────
def test_greeting_plus_real_question_falls_through():
    # the task's headline requirement: a greeting that opens a real question MUST fall through
    assert it.is_trivial("hi, also what is wheat doing") is None


def test_real_questions_fall_through():
    for q in ("hello can you explain the corn cascade",     # _REASON: explain
              "thanks -- and what were soybean exports?",    # _NUM: what were
              "why is coffee bullish",                       # _REASON: why
              "help me understand the frost channel",        # _REASON: channel (+ not a full-string phrase)
              "what were corn exports",                      # _NUM: what were
              "is corn a buy"):                              # _REASON: a buy
        assert it.is_trivial(q) is None, q


def test_empty_and_whitespace_fall_through():
    for q in ("", "   ", "\n\t", None):
        assert it.is_trivial(q) is None, repr(q)


def test_terse_ambiguous_falls_through():
    # deterministic-only v1 (D2=no Haiku): a bare terse token that could be a greeting OR a truncated real
    # question is ambiguous -> fall through (fail-open). Bare month words are NOT standalone greetings.
    for q in ("morning", "afternoon", "evening", "update", "status"):
        assert it.is_trivial(q) is None, q


def test_escaping_vocabulary_falls_through():
    # verifier F3 REQUIRED rows: each carries a greeting TOKEN, is short, and fires NEITHER _NUM nor _REASON,
    # so the data-cue backstop MISSES them -- they fall through ONLY because guard (i) is a full-string anchor
    # (the greeting is not the WHOLE message). If the full-string anchor ever regresses, these flip to a class.
    for q in ("hey what's driving cocoa", "morning, is corn moving", "yo cocoa update", "hi hows sugar looking"):
        assert it.is_trivial(q) is None, q
        # prove they genuinely escape the backstop (so the anchor is what carries them):
        assert not (it._NUM.search(q) or it._REASON.search(q)), q


def test_meta_phrases_that_trip_the_backstop_fall_through():
    # whole-message meta phrases that contain a _NUM/_REASON token are intentionally fail-open (guard ii veto):
    # "what is this"/"what are you" trip _NUM's 'what is/are'; "how does this work" trips _REASON's 'how does'.
    for q in ("what is this", "what are you", "how does this work", "how do you work"):
        assert it.is_trivial(q) is None, q


# ── PROPERTIES: the two guards, stated as invariants ──────────────────────────────────────────────────────
def test_property_data_cue_always_falls_through():
    # guard (ii): for any string where _NUM or _REASON fires, is_trivial is None.
    probes = ["hi what were corn exports", "hello why is coffee bullish", "thanks how does drought hit corn",
              "good morning what's the price of sugar", "hey explain the cascade", "who are you and what is corn"]
    for q in probes:
        if it._NUM.search(q) or it._REASON.search(q):
            assert it.is_trivial(q) is None, q


def test_property_non_full_string_greeting_falls_through():
    # guard (i): a greeting token embedded in a longer non-phrase message never classifies.
    for q in ("hi everyone i have a question about corn balance sheets",
              "hey so about that soybean thesis", "thanks now onto wheat"):
        assert it.is_trivial(q) is None, q
