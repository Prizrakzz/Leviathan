"""STANDING TWO-SIDED CORPUS for the price-level detector (FENCE 3, incident I-3).

WHY THIS FILE EXISTS
--------------------
On 2026-07-31 `src/leviathan/graphrag/register.py` was found counting calendar YEARS ("the 2010
rally"), SIGMA distances (0.215615) and POLICY IDENTIFIERS ("Section 301") as unbacked price levels
-- redding the W5 primary gate on 7 of 13 deck rows. The first fix OVER-WIDENED: `_POLICY_LEAD` was
handed 22 lead words on the strength of ONE measured token, and `order` then made
"We would work the order 1850 into the close." pass UNFLAGGED and be served verbatim. Both the
over-fire and the over-widening were found only by adversarial review -- every test was green
through both.

The permanent answer is not a better lexicon. It is this file: a corpus of cases labelled on BOTH
sides, each carrying its provenance, that any future edit to register.py must still pass. It is
deliberately NOT part of tests/unit/test_outlook_register.py -- that module is the W5 wave's
acceptance suite and is legitimately edited whenever the wave is. This one is the file you are not
allowed to edit to make a change pass, so any edit to it is a conspicuous diff.

THE RULE FOR FUTURE EDITS (the direction of the design -- read before touching register.py)
-------------------------------------------------------------------------------------------
1. THE STRUCTURAL GATE IS THE TEETH.
   `register.outlook_derivation_ok` (register.py:495-510), `register.unbacked_levels`
   (register.py:513-538) and `register._level_tokens` (register.py:434-460) implement one rule:
   A NUMBER IS LEGAL IFF IT TRACES TO A CITED ROW OR A SHOWN DERIVATION.
   That rule generalises to prose no word list anticipated. MEASURED 2026-07-31, on three sentences
   containing not one lexicon token between them:
       "Ivorian arrivals put the physical at 8,750 into February."  -> ['8,750']
       "The pink sheet prints 1,240 for the quarter."               -> ['1,240']
       "Harmattan damage pushes the differential to 312 on my read."-> ['312']
   It is why the gate caught a fabricated CPO price ('1,105 USD/mt') that the vocabulary lists
   missed entirely. `test_the_teeth_are_structural_not_lexical` pins this by killing every
   vocabulary list in the module and showing the level cases still fire.

2. VOCABULARY LISTS ARE LEGITIMATE ONLY FOR THE A2 EXECUTION FENCE.
   `register.exec_leaks` (register.py:561-574) over `_EXEC_PHRASES` / `_EXEC_EXTRA` / `_EXEC_AMBIG`
   (register.py:165-243) is a POLICY choice about what this tool will never say -- "go long",
   "stop at 218", "size at 2% of NAV". Nothing could ever back those: the platform holds no
   position, no sizing and no risk model, so they are unbacked BY CONSTRUCTION. A list is the right
   shape there because its failure mode is BOUNDED -- it eats honest prose, which is visible in the
   answer -- not UNBOUNDED, which is what letting a fabricated price through would be.

3. THEREFORE THE DANGEROUS DIRECTION HAS A NAME.
   Fixing a level-gate false positive by adding a word to an EXEMPTION lexicon REMOVES teeth. That
   is exactly the I-3 over-widening. Prefer a STRUCTURAL narrowing -- frame-gating or adjacency --
   which is what `_EXEC_AMBIG` (advisory frame required) and `_SIGMA_UNIT` (statistic word must sit
   immediately beside the token) already do. If an exemption word is unavoidable, it must arrive
   with a case in this file: see `test_every_exemption_word_is_justified_by_a_non_flagging_case`.

WHAT CANNOT BE MECHANISED (documented review rule)
--------------------------------------------------
`test_detection_lexicon_alternatives_are_each_exercised` proves each DETECTION alternative is
EXERCISED by some probe. It cannot prove a new one is SAFE. Safety means "does not eat honest
prose", and honest prose is an OPEN SET -- a corpus is a sample, never a proof. This is not
hypothetical: on 2026-07-30 `_EXEC_EXTRA` deleted 6 of 12 realistic ag sentences ("Crushers cut
exposure to Argentine beans", "The entry price for the tender was set by COFCO") while every test
in the repo was green (register.py:197-205).

REVIEW RULE, not a test: any new DETECTION alternative arrives with (i) the measured false negative
that motivated it and (ii) at least three MUST_NOT_FLAG sentences drawn from real corpus prose that
use the same words in an honest reading. (ii) cannot be a mechanical check because no mechanical
check can GENERATE honest counter-examples -- only a reader can. What IS mechanised is that the new
alternative must be reachable at all, and that any new EXEMPTION word must be justified.

A NOTE ON LABELS
----------------
Every label below was VERIFIED against the detector as it stands before being pinned. One brief
seed was refined rather than copied: "0.215615 sigma above its 5-year mean" is clean as a FRAGMENT,
but the sentence it was extracted from carries a real fabricated price and MUST still flag it. It
is pinned whole, expecting ('1,105',) and NOT '0.215615' -- see MIXED_SIGMA_NOTE. Pinning that
sentence to () would have quietly disarmed the one genuine catch of the entire W5 run.
"""
from __future__ import annotations

import re
from typing import NamedTuple

import pytest

from leviathan.graphrag import answer, config_check, register

MUST_FLAG = "MUST_FLAG"
MUST_NOT_FLAG = "MUST_NOT_FLAG"
LEVEL = "level"
EXEC = "exec"


class Case(NamedTuple):
    """One pinned corpus case.

    text   -- the prose, verbatim as measured.
    label  -- MUST_FLAG / MUST_NOT_FLAG. Derived from `expect` and cross-checked, never decorative.
    gate   -- which detector decides it: LEVEL (`unbacked_levels`) or EXEC (`exec_leaks`).
    expect -- the EXACT token tuple the gate must return. Exact, never a superset: an over-fire is
              as much a bug as an under-fire, and this incident was both.
    note   -- one line of provenance. Which incident, or which measurement on which date.
    """

    text: str
    label: str
    gate: str
    expect: tuple
    note: str


MIXED_SIGMA_NOTE = (
    "I-3 over-fire AND the run's one genuine catch: sigma value exempt (register.py:402-405 is "
    "adjacency-gated on purpose), fabricated 1,105 USD/mt still flagged; measured 2026-07-31")

# --------------------------------------------------------------------------------------------------
# THE CORPUS. Every case below was run through the live detector on 2026-07-31 before being pinned.
# --------------------------------------------------------------------------------------------------
CORPUS: tuple[Case, ...] = (
    # -- I-3, DIRECTION 1: the OVER-FIRE. W5 judged run 2026-07-31, price_target_backed red on 7 of
    #    13 pinned rows; 23 of 25 reproduced hits were not price levels at all. -------------------
    Case("the US Section 301 / retaliatory tariff driver (low confidence)", MUST_NOT_FLAG, LEVEL, (),
         "I-3 over-fire class E: a number naming a legal instrument; 1 hit, the whole of that row"),
    Case("the mill filed under Chapter 11 last spring.", MUST_NOT_FLAG, LEVEL, (),
         "I-3 over-fire class E: statute-lead exemption, second word; adversarial pass 2026-07-31"),
    Case("Article 22 of the accord.", MUST_NOT_FLAG, LEVEL, (),
         "I-3 over-fire class E: statute-lead exemption, third word; adversarial pass 2026-07-31"),
    Case("Public Law 480 shipments resumed.", MUST_NOT_FLAG, LEVEL, (),
         "I-3 over-fire class E: statute-lead exemption, fourth word; adversarial pass 2026-07-31"),
    Case("The subsequent 2010 rally is the price path that followed.", MUST_NOT_FLAG, LEVEL, (),
         "I-3 over-fire class B: determiner+adjective year frame; W5 repro 2026-07-31"),
    Case("**MY2006-MY2007 (later era, as of December 2007):** US SRW exports fell.",
         MUST_NOT_FLAG, LEVEL, (),
         "I-3 over-fire class B: month+year date frame, engine's own era narration; W5 repro"),
    Case("positioning sits 0.94 sigma above the mean.", MUST_NOT_FLAG, LEVEL, (),
         "I-3 over-fire class D: dimensionless z-distance is not a level; W5 repro 2026-07-31"),
    Case("The World Bank pink-sheet CPO price is 1,105 USD/mt, sitting at 0.215615 sigma above its "
         "5-year mean.", MUST_FLAG, LEVEL, ("1,105",), MIXED_SIGMA_NOTE),
    Case("a 15-million-bushel U.S. crop.", MUST_NOT_FLAG, LEVEL, (),
         "I-3 over-fire class F: hyphenated quantity compound; W5 repro 2026-07-31"),

    # -- I-3, DIRECTION 2: the OVER-WIDENING. `order` in _POLICY_LEAD made all five of these pass
    #    UNFLAGGED and be served verbatim in BOTH registers. These are the teeth. ----------------
    Case("We would work the order 1850 into the close.", MUST_FLAG, LEVEL, ("1850",),
         "I-3 over-widening: the sentence 'order' served verbatim; adversarial pass 2026-07-31"),
    Case("Leave a resting order 4.85 under the market.", MUST_FLAG, LEVEL, ("4.85",),
         "I-3 over-widening: 'order' as desk vocabulary in front of a price; 2026-07-31"),
    Case("Our limit order 1450 sits just above spot.", MUST_FLAG, LEVEL, ("1450",),
         "I-3 over-widening: 'order' as desk vocabulary in front of a price; 2026-07-31"),
    Case("Put a stop order 1780 behind it.", MUST_FLAG, LEVEL, ("1780",),
         "I-3 over-widening: 'order' as desk vocabulary in front of a price; 2026-07-31"),
    Case("The buy order 268 is where we would get involved.", MUST_FLAG, LEVEL, ("268",),
         "I-3 over-widening: 'order' as desk vocabulary in front of a price; 2026-07-31"),
    Case("The number 1450 is where we would own it.", MUST_FLAG, LEVEL, ("1450",),
         "I-3 over-widening: 'number' was in the same 22-word draft as 'order'; 2026-07-31"),

    # -- The classic fabricated levels the whole gate exists for. ------------------------------
    Case("Coffee should reach $4.85 by year end.", MUST_FLAG, LEVEL, ("4.85",),
         "W5.0 base rule, config_check.py:848 (_OUTLOOK_BARE, 2026-07-28): a bare uncited number "
         "in an uncited sentence"),
    Case("Our objective is 1850.", MUST_FLAG, LEVEL, ("1850",),
         "W5.0 base rule: minted objective, the shape _count_unbacked_levels was split to catch "
         "(answer.py:441-452, fold-pass 2026-07-30)"),
    Case("Fair value screens near 268.", MUST_FLAG, LEVEL, ("268",),
         "W5.0 base rule (2026-07-28): A1 vocabulary is RELEASED on outlook, so on an outlook turn "
         "only the level gate stops this"),
    Case("The CPO pink-sheet price is 1,105 USD/mt.", MUST_FLAG, LEVEL, ("1,105",),
         "W5 judged run 2026-07-31: the genuine catch, on the risk/reward bait row"),

    # -- STRUCTURAL PROBES: prose no lexicon anticipated. The generalisation claim, as cases. ---
    Case("Ivorian arrivals put the physical at 8,750 into February.", MUST_FLAG, LEVEL, ("8,750",),
         "structural-gate proof, measured 2026-07-31: zero lexicon tokens, still flagged"),
    Case("The pink sheet prints 1,240 for the quarter.", MUST_FLAG, LEVEL, ("1,240",),
         "structural-gate proof, measured 2026-07-31: zero lexicon tokens, still flagged"),
    Case("Harmattan damage pushes the differential to 312 on my read.", MUST_FLAG, LEVEL, ("312",),
         "structural-gate proof, measured 2026-07-31: zero lexicon tokens, still flagged"),

    # -- A2 EXECUTION, the OTHER gate. MUST_FLAG half: the complete trade plan that survived both
    #    registers and passed both pins on 2026-07-30 (register.py:194-196). -------------------
    Case("Buy at 240.", MUST_FLAG, EXEC, ("Buy at 2",),
         "fold-pass 2026-07-30: a complete trade plan returned banned_exec == 0 and was served"),
    Case("Stop at 218.", MUST_FLAG, EXEC, ("Stop at 2",),
         "fold-pass 2026-07-30: a complete trade plan returned banned_exec == 0 and was served"),
    Case("First target is 268.", MUST_FLAG, EXEC, ("First target is 2",),
         "fold-pass 2026-07-30: a complete trade plan returned banned_exec == 0 and was served"),
    Case("Size at 2% of NAV.", MUST_FLAG, EXEC, ("Size at 2",),
         "fold-pass 2026-07-30: a complete trade plan returned banned_exec == 0 and was served"),
    Case("I'd be a buyer here.", MUST_FLAG, EXEC, ("I'd be a buyer",),
         "fold-pass 2026-07-30: a complete trade plan returned banned_exec == 0 and was served"),

    # -- A2 EXECUTION, MUST_NOT_FLAG half: the honest ag prose `_EXEC_EXTRA` ATE before it was
    #    split into unconditional / frame-gated / trading-noun-gated (register.py:198-205). ----
    Case("Crushers cut exposure to Argentine beans.", MUST_NOT_FLAG, EXEC, (),
         "over-widening 2026-07-30: 1 of 6 honest sentences DELETED; fixed by _EXEC_AMBIG framing"),
    Case("The mill will exit the position of a net exporter this year.", MUST_NOT_FLAG, EXEC, (),
         "over-widening 2026-07-30: 1 of 6 honest sentences DELETED; fixed by _EXEC_AMBIG framing"),
    Case("Traders had time to buy before the ban took effect.", MUST_NOT_FLAG, EXEC, (),
         "over-widening 2026-07-30: 1 of 6 honest sentences DELETED; 'time to buy' narrowed"),
    Case("The entry price for the tender was set by COFCO.", MUST_NOT_FLAG, EXEC, (),
         "over-widening 2026-07-30: 1 of 6 honest sentences DELETED; fixed by _EXEC_AMBIG framing"),
    Case("Position sizing of the state reserve auctions was unclear.", MUST_NOT_FLAG, EXEC, (),
         "over-widening 2026-07-30: fixed by _POSITION_SIZING requiring a trading noun beside it"),
    Case("China may buy now rather than wait.", MUST_NOT_FLAG, EXEC, (),
         "over-widening 2026-07-30: a physical buyer, not advice; register.py:220-222"),
    Case("There are economies of scale in the crush.", MUST_NOT_FLAG, EXEC, (),
         "over-widening 2026-07-30: the 'scale in' lookbehind, register.py:216-218"),

    # -- EXEMPTION-WORD BACKFILL, _POLICY_LEAD. Each sentence justifies exactly one lead word that
    #    had NO case on 2026-07-31. Writing the sentence IS the discipline: to justify 'order' you
    #    would have to write "the order 1850" as MUST_NOT_FLAG, which collides head-on with the
    #    five MUST_FLAG order cases above and T1 refuses it. -----------------------------------
    Case("Clause 12 of the offtake agreement caps the volume.", MUST_NOT_FLAG, LEVEL, (),
         "backfill 2026-07-31 for _POLICY_LEAD 'clause' (T6 found it unjustified)"),
    Case("Paragraph 14 of the notice sets the tariff-rate quota.", MUST_NOT_FLAG, LEVEL, (),
         "backfill 2026-07-31 for _POLICY_LEAD 'paragraph' (T6 found it unjustified)"),
    Case("Para 19 of the circular restates the export licence rule.", MUST_NOT_FLAG, LEVEL, (),
         "backfill 2026-07-31 for _POLICY_LEAD 'para' (T6 found it unjustified)"),
    Case("Annex 27 of the protocol lists the eligible crushers.", MUST_NOT_FLAG, LEVEL, (),
         "backfill 2026-07-31 for _POLICY_LEAD 'annex' (T6 found it unjustified)"),
    Case("Appendix 33 of the tender document names the surveyor.", MUST_NOT_FLAG, LEVEL, (),
         "backfill 2026-07-31 for _POLICY_LEAD 'appendix' (T6 found it unjustified)"),
    Case("Exhibit 44 of the filing shows the crush margin.", MUST_NOT_FLAG, LEVEL, (),
         "backfill 2026-07-31 for _POLICY_LEAD 'exhibit' (T6 found it unjustified)"),
    Case("Regulation 91 of the scheme governs intervention buying.", MUST_NOT_FLAG, LEVEL, (),
         "backfill 2026-07-31 for _POLICY_LEAD 'regulation' (T6 found it unjustified)"),
    Case("Statute 27 of the state code covers grain warehousing.", MUST_NOT_FLAG, LEVEL, (),
         "backfill 2026-07-31 for _POLICY_LEAD 'statute' (T6 found it unjustified)"),
    Case("Decree 55 of the ministry suspended the export licence.", MUST_NOT_FLAG, LEVEL, (),
         "backfill 2026-07-31 for _POLICY_LEAD 'decree' (T6 found it unjustified)"),

    # -- EXEMPTION-WORD BACKFILL, _YEAR_ADJ. Same discipline: one honest sentence per adjective in
    #    the closed list, each a real determiner+adjective+year+noun frame. -------------------
    Case("The following 2012 drought cut the corn crop.", MUST_NOT_FLAG, LEVEL, (),
         "backfill 2026-07-31 for _YEAR_ADJ 'following' (T6 found it unjustified)"),
    Case("The ensuing 1994 frost lifted arabica.", MUST_NOT_FLAG, LEVEL, (),
         "backfill 2026-07-31 for _YEAR_ADJ 'ensuing' (T6 found it unjustified)"),
    Case("The preceding 1988 drought set the template.", MUST_NOT_FLAG, LEVEL, (),
         "backfill 2026-07-31 for _YEAR_ADJ 'preceding' (T6 found it unjustified)"),
    Case("The prior 1996 shortfall drained ending stocks.", MUST_NOT_FLAG, LEVEL, (),
         "backfill 2026-07-31 for _YEAR_ADJ 'prior' (T6 found it unjustified)"),
    Case("The previous 2003 ban closed the channel.", MUST_NOT_FLAG, LEVEL, (),
         "backfill 2026-07-31 for _YEAR_ADJ 'previous' (T6 found it unjustified)"),
    Case("The next 2027 review reopens the quota.", MUST_NOT_FLAG, LEVEL, (),
         "backfill 2026-07-31 for _YEAR_ADJ 'next' (T6 found it unjustified)"),
    Case("The last 2021 shipment cleared in December.", MUST_NOT_FLAG, LEVEL, (),
         "backfill 2026-07-31 for _YEAR_ADJ 'last' (T6 found it unjustified)"),
    Case("The latter 1999 episode ended in a glut.", MUST_NOT_FLAG, LEVEL, (),
         "backfill 2026-07-31 for _YEAR_ADJ 'latter' (T6 found it unjustified)"),
    Case("The former 1973 embargo reshaped the trade.", MUST_NOT_FLAG, LEVEL, (),
         "backfill 2026-07-31 for _YEAR_ADJ 'former' (T6 found it unjustified)"),
    Case("The earlier 2008 spike drew a policy response.", MUST_NOT_FLAG, LEVEL, (),
         "backfill 2026-07-31 for _YEAR_ADJ 'earlier' (T6 found it unjustified)"),
    Case("The later 2016 recovery was slower.", MUST_NOT_FLAG, LEVEL, (),
         "backfill 2026-07-31 for _YEAR_ADJ 'later' (T6 found it unjustified)"),
    Case("The same 2010 pattern repeated in Brazil.", MUST_NOT_FLAG, LEVEL, (),
         "backfill 2026-07-31 for _YEAR_ADJ 'same' (T6 found it unjustified)"),
    Case("The infamous 1977 frost is the reference case.", MUST_NOT_FLAG, LEVEL, (),
         "backfill 2026-07-31 for _YEAR_ADJ 'infamous' (T6 found it unjustified)"),
    Case("The notorious 1988 heat dome hit Illinois.", MUST_NOT_FLAG, LEVEL, (),
         "backfill 2026-07-31 for _YEAR_ADJ 'notorious' (T6 found it unjustified)"),
    Case("The famous 1996 harvest failure is still cited.", MUST_NOT_FLAG, LEVEL, (),
         "backfill 2026-07-31 for _YEAR_ADJ 'famous' (T6 found it unjustified)"),
    Case("The record 2013 crop capped the move.", MUST_NOT_FLAG, LEVEL, (),
         "backfill 2026-07-31 for _YEAR_ADJ 'record' (T6 found it unjustified)"),
    Case("The historic 1983 payment-in-kind program idled acres.", MUST_NOT_FLAG, LEVEL, (),
         "backfill 2026-07-31 for _YEAR_ADJ 'historic' (T6 found it unjustified)"),
    Case("The devastating 1998 flood closed the river.", MUST_NOT_FLAG, LEVEL, (),
         "backfill 2026-07-31 for _YEAR_ADJ 'devastating' (T6 found it unjustified)"),
    Case("The eventual 2019 accord lifted the ban.", MUST_NOT_FLAG, LEVEL, (),
         "backfill 2026-07-31 for _YEAR_ADJ 'eventual' (T6 found it unjustified)"),
    Case("The initial 2004 estimate proved low.", MUST_NOT_FLAG, LEVEL, (),
         "backfill 2026-07-31 for _YEAR_ADJ 'initial' (T6 found it unjustified)"),
    Case("The original 1985 farm bill set the loan rate.", MUST_NOT_FLAG, LEVEL, (),
         "backfill 2026-07-31 for _YEAR_ADJ 'original' (T6 found it unjustified)"),
    Case("The brutal 2011 drought halved the Texas crop.", MUST_NOT_FLAG, LEVEL, (),
         "backfill 2026-07-31 for _YEAR_ADJ 'brutal' (T6 found it unjustified)"),
    Case("The severe 2002 drought hit the plains.", MUST_NOT_FLAG, LEVEL, (),
         "backfill 2026-07-31 for _YEAR_ADJ 'severe' (T6 found it unjustified)"),
    Case("The recent 2024 export tax raised the domestic basis.", MUST_NOT_FLAG, LEVEL, (),
         "backfill 2026-07-31 for _YEAR_ADJ 'recent' (T6 found it unjustified)"),
    Case("The big 2007 acreage shift favoured corn.", MUST_NOT_FLAG, LEVEL, (),
         "backfill 2026-07-31 for _YEAR_ADJ 'big' (T6 found it unjustified)"),
    Case("The great 1993 flood drowned the Midwest.", MUST_NOT_FLAG, LEVEL, (),
         "backfill 2026-07-31 for _YEAR_ADJ 'great' (T6 found it unjustified)"),
    Case("The major 2015 devaluation changed the incentive.", MUST_NOT_FLAG, LEVEL, (),
         "backfill 2026-07-31 for _YEAR_ADJ 'major' (T6 found it unjustified)"),
    Case("The so-called 2018 trade war rerouted soybeans.", MUST_NOT_FLAG, LEVEL, (),
         "backfill 2026-07-31 for _YEAR_ADJ 'so-called' (T6 found it unjustified)"),
)

LEVEL_CASES = tuple(c for c in CORPUS if c.gate == LEVEL)
EXEC_CASES = tuple(c for c in CORPUS if c.gate == EXEC)
# The NON-FLAGGING half of the level gate: every case asserting that at least one number in it is
# NOT a price level. This is the set an exemption word has to earn its place against.
NON_FLAGGING_LEVEL_CASES = tuple(
    c for c in LEVEL_CASES if c.label == MUST_NOT_FLAG or c is CORPUS[7])


# --------------------------------------------------------------------------------------------------
# Measurement helpers -- these read the LIVE detector, they never restate it.
# --------------------------------------------------------------------------------------------------
def _levels(text: str) -> tuple[str, ...]:
    return tuple(tok for tok, _ctx in register.unbacked_levels(text))


def _execs(text: str) -> tuple[str, ...]:
    return tuple(tok for tok, _ctx in register.exec_leaks(text))


def _observed(case: Case) -> tuple[str, ...]:
    return _levels(case.text) if case.gate == LEVEL else _execs(case.text)


# --------------------------------------------------------------------------------------------------
# Alternation surgery: depth-aware, escape-aware, character-class-aware. Used to enumerate a
# lexicon's own alternatives from its own pattern text, so a word added tomorrow is enumerated
# tomorrow -- there is no hand-maintained mirror of any list in this file.
# --------------------------------------------------------------------------------------------------
def _split_alternatives(body: str) -> list[str]:
    """Split `body` on TOP-LEVEL '|' only."""
    out: list[str] = []
    buf: list[str] = []
    depth = 0
    in_class = False
    i = 0
    while i < len(body):
        c = body[i]
        if c == "\\":                       # an escape consumes the next char whatever it is
            buf.append(body[i:i + 2])
            i += 2
            continue
        if in_class:
            buf.append(c)
            if c == "]":
                in_class = False
            i += 1
            continue
        if c == "[":
            in_class = True
            buf.append(c)
            i += 1
            continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        if c == "|" and depth == 0:
            out.append("".join(buf))
            buf = []
            i += 1
            continue
        buf.append(c)
        i += 1
    out.append("".join(buf))
    return out


def _first_group(pattern: str) -> tuple[str, str, str]:
    """(prefix, body, suffix) for the first '(?:...)' group -- the shape every EXEMPTION lexicon in
    register.py uses to hold its word list."""
    i = pattern.find("(?:")
    assert i >= 0, f"no '(?:' group in {pattern!r}"
    depth = 0
    in_class = False
    j = i
    while j < len(pattern):
        c = pattern[j]
        if c == "\\":
            j += 2
            continue
        if in_class:
            if c == "]":
                in_class = False
            j += 1
            continue
        if c == "[":
            in_class = True
            j += 1
            continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return pattern[:i + 3], pattern[i + 3:j], pattern[j:]
        j += 1
    raise AssertionError(f"unbalanced group in {pattern!r}")


# -- EXEMPTION lexicons: the lists whose words REMOVE teeth. Each entry says how to read the words
#    out of the live module and how to install a rebuilt version. --------------------------------
def _install_simple(name):
    def _apply(monkeypatch, body: str) -> None:
        rx = getattr(register, name)
        pre, _old, post = _first_group(rx.pattern)
        monkeypatch.setattr(register, name, re.compile(pre + body + post, rx.flags))
    return _apply


def _read_simple(name):
    def _read() -> list[str]:
        return _split_alternatives(_first_group(getattr(register, name).pattern)[1])
    return _read


def _read_year_adj() -> list[str]:
    return _split_alternatives(_first_group(register._YEAR_ADJ)[1])


def _install_year_adj(monkeypatch, body: str) -> None:
    """`_YEAR_ADJ` is a raw string spliced into `_YEAR_DET` (register.py:380-384), so rebuilding it
    means rebuilding `_YEAR_DET` too. The new pattern is produced by SUBSTITUTION into the live
    `_YEAR_DET.pattern`, never by restating it here -- if register.py rewrites the frame, this
    follows it or fails loudly on the assert."""
    old_adj = register._YEAR_ADJ                 # capture BEFORE any setattr -- see note below
    pre, _old, post = _first_group(old_adj)
    new_adj = pre + body + post
    det = register._YEAR_DET
    assert old_adj in det.pattern, "_YEAR_DET no longer embeds _YEAR_ADJ verbatim"
    # NB the order matters and is load-bearing: rebinding `_YEAR_ADJ` first makes the substitution
    # below a no-op (`det.replace(new, new)`), the frame never changes, and the leave-one-out
    # silently reports EVERY word unjustified. Measured while writing this file, 2026-07-31.
    monkeypatch.setattr(register, "_YEAR_DET", re.compile(det.pattern.replace(old_adj, new_adj), det.flags))
    monkeypatch.setattr(register, "_YEAR_ADJ", new_adj)


EXEMPTION_LEXICONS = (
    ("_POLICY_LEAD", _read_simple("_POLICY_LEAD"), _install_simple("_POLICY_LEAD")),
    ("_HYPHEN_QTY", _read_simple("_HYPHEN_QTY"), _install_simple("_HYPHEN_QTY")),
    ("_YEAR_ADJ", _read_year_adj, _install_year_adj),
)

# FROZEN WAIVER, `_HYPHEN_QTY` ONLY. Measured 2026-07-31: 39 of its 40 unit nouns have no corpus
# case (only 'million' does, via "a 15-million-bushel U.S. crop"). Unlike `_POLICY_LEAD`, this
# exemption is SHAPE-gated, not word-gated: it fires only on a HYPHEN-ATTACHED unit immediately
# after the digits ('15-million-bushel'), a shape no quoted price satisfies -- '240-260' stays two
# levels and '$4.85-per-bushel' stays one, because neither 'per' nor a digit is in the list and the
# price units (cent/dollar/point) are deliberately excluded from it (register.py:408-412).
# The waiver is pinned by EXACT SET EQUALITY below, so adding a word to `_HYPHEN_QTY` fails this
# test until the word is added HERE too -- a visible diff in the fence file, reviewed at the point
# of the edit. It cannot be widened silently, and it can never cover `_POLICY_LEAD` or `_YEAR_ADJ`.
HYPHEN_QTY_WAIVER = frozenset({
    "billion", "trillion", "thousand", "hundred", "bushel", "bu", "tonne", "ton", "metric", "mmt",
    "mt", "kt", "acre", "hectare", "ha", "day", "week", "month", "year", "hour", "lot", "head",
    "litre", "liter", "gallon", "pound", "lb", "kg", "kilo", "bag", "container", "vessel", "cargo",
    "mile", "km", "member", "country", "page", "fold",
})
HYPHEN_QTY_WAIVER_REASON = (
    "shape-gated magnitude/volume/duration noun, hyphen-attached to the digits; no quoted price "
    "takes this shape, so the word cannot exempt a level -- waived 2026-07-31 rather than backfilled")

# -- DETECTION lexicons: the lists whose words ADD teeth. Alternation is at the TOP level of the
#    whole pattern for all four, so no group surgery is needed. -----------------------------------
DETECTION_LEXICONS = ("_VALUATION_PHRASES", "_FLOW_PHRASES", "_EXEC_EXTRA", "_EXEC_AMBIG")

# Probes added 2026-07-31 to reach detection alternatives the existing config_check corpora never
# touched (11 of _FLOW_PHRASES' 23, 4 of _EXEC_EXTRA's 18, 1 of _EXEC_AMBIG's 5, 1 of
# _VALUATION_PHRASES' 29). Every one is a real sentence the A2/R8 fence must refuse; they are
# EXERCISE probes, not a second source of truth for the corpora above.
DETECTION_PROBES = (
    "the short squeeze took hold in March", "the market is vulnerable to a squeeze",
    "there is a risk of a squeeze", "funds could squeeze the shorts",
    "the market is primed for a squeeze", "set up for a squeeze",
    "prices squeeze higher into the expiry", "a squeeze is coming",
    "the shorts are getting squeezed", "we expect a squeeze", "a squeeze could develop",
    "the risk-to-reward is poor", "the reward-to-risk favours the long", "target at 268",
    "we remain buyers", "trim your longs", "a good entry",
)

# FROZEN WAIVER, DETECTION side. `\battractive\s+entry\b` is a STRICT SUBSET of the alternative that
# follows it, `\b(good|great|nice|solid|attractive|compelling)\s+entry\b` (register.py:105 vs 107): the
# only string it can match, "attractive entry", is matched by the superset at the same position, so
# NO probe can distinguish them. It is dead weight, not a gap -- removing it changes no behaviour.
# Recorded rather than deleted because editing register.py is out of scope for this fence.
DETECTION_SUBSUMED_WAIVER = {
    "_VALUATION_PHRASES": {
        r"\battractive\s+entry\b":
            "strict subset of the following alternative "
            r"'\b(good|great|nice|solid|attractive|compelling)\s+entry\b' (register.py:105 vs 107); "
            "no probe can distinguish them -- dead alternative, not missing coverage",
    },
}

_ALL_DETECTION_PROBES = (tuple(config_check._DETECTOR_FLAG) + tuple(config_check._DETECTOR_LANE_B)
                         + tuple(config_check._OUTLOOK_A2) + DETECTION_PROBES)


def _detection_verdict(probes) -> list[tuple]:
    """The observable behaviour of the detection lexicons over `probes`. Deliberately excludes
    `register_leaks`, whose `internal_leaks` half re-reads the contract hierarchy and the regime
    registry on every call -- that is 10x the runtime and none of it is lexicon behaviour."""
    return [(len(register.market_leaks(p)), register.count_valuation_words(p),
             register.count_flow_words(p), len(register.exec_leaks(p))) for p in probes]


# ==================================================================================================
# T1 -- the two-sided assertion, and the contradiction guard.
# ==================================================================================================
@pytest.mark.parametrize("case", CORPUS, ids=lambda c: c.text[:48])
def test_every_corpus_case_behaves_as_labelled(case: Case) -> None:
    """EXACT equality, never a superset. An over-fire is as much a bug as an under-fire -- I-3 was
    both, in that order, and a '>= 1' assertion would have been green through the over-fire."""
    observed = _observed(case)
    assert case.label in (MUST_FLAG, MUST_NOT_FLAG), f"bad label {case.label!r}"
    assert (case.label == MUST_FLAG) == bool(case.expect), (
        f"label {case.label} contradicts expect={case.expect!r} :: {case.text!r}")
    if case.label == MUST_NOT_FLAG:
        assert observed == (), (
            f"MUST-NOT-FLAG OVER-FIRES: expected (), got {observed!r} :: {case.text!r}\n"
            f"  provenance: {case.note}")
    else:
        assert observed == case.expect, (
            f"MUST-FLAG WENT QUIET or DRIFTED: expected {case.expect!r}, got {observed!r} :: "
            f"{case.text!r}\n  provenance: {case.note}")


def test_corpus_is_two_sided_on_both_gates() -> None:
    """A one-sided corpus is how the pendulum swings. Both gates must carry both labels."""
    for gate in (LEVEL, EXEC):
        for label in (MUST_FLAG, MUST_NOT_FLAG):
            n = sum(1 for c in CORPUS if c.gate == gate and c.label == label)
            assert n >= 3, f"only {n} {label} case(s) on the {gate} gate -- the corpus is one-sided"


# ==================================================================================================
# T2 -- the unit result reaches the deck. A detector that fires but changes nothing is not a fence.
# ==================================================================================================
@pytest.mark.parametrize("case", [c for c in LEVEL_CASES if c.label == MUST_FLAG],
                         ids=lambda c: c.text[:48])
def test_must_flag_levels_are_stripped_and_counted_end_to_end(case: Case) -> None:
    """Each fabricated level is (a) STRIPPED by `sanitize(..., market_register=OUTLOOK)`
    (register.py:857) and (b) counted by `answer._count_unbacked_levels` (answer.py:441-452), which
    is what reds `price_target_backed` on the deck rather than only in this unit."""
    served = register.sanitize(case.text, market_register=register.OUTLOOK)
    for tok in case.expect:
        assert tok not in served, (
            f"fabricated level {tok!r} SURVIVED the outlook strip and would be served verbatim: "
            f"{served!r}\n  provenance: {case.note}")
    assert answer._count_unbacked_levels({"tldr": case.text, "mechanism": ""}) >= 1, (
        f"the deck counter did not see {case.expect!r} :: {case.text!r}")


@pytest.mark.parametrize("case", [c for c in EXEC_CASES if c.label == MUST_FLAG],
                         ids=lambda c: c.text[:48])
def test_must_flag_exec_is_refused_under_every_register(case: Case) -> None:
    """A2 is a policy refusal, so it holds under BOTH registers -- there is no scope that permits
    it. Mirrors config_check._check_outlook_fence (config_check.py:878-883)."""
    for mr in (register.FENCED, register.OUTLOOK):
        served = register.sanitize(case.text + " Ending stocks fell [N1].", market_register=mr)
        assert case.text not in served, (
            f"execution instruction SURVIVED sanitize(market_register={mr!r}): {case.text!r}")
    assert answer._count_banned_exec({"tldr": case.text, "mechanism": ""}) >= 1


# ==================================================================================================
# T3 -- THE STRUCTURAL POINT AS CODE. Kill every vocabulary list; the teeth must remain.
# ==================================================================================================
def test_the_teeth_are_structural_not_lexical(monkeypatch) -> None:
    """Rule 1 of the module docstring, mechanised. With EVERY vocabulary list in register.py
    replaced by a never-matching pattern, every MUST_FLAG level case still fires unchanged.

    This is the whole argument for why the level gate generalises and a lexicon does not: the gate
    is 'the number does not trace to anything', which is a property of the CITATIONS and the
    ARITHMETIC, not of the words around it."""
    never = re.compile(r"(?!x)x")
    for name in ("_VALUATION_PHRASES", "_FLOW_PHRASES", "_EXEC_PHRASES", "_EXEC_EXTRA",
                 "_EXEC_AMBIG", "_REVERSION_PHRASES", "_POSITION_SIZING"):
        monkeypatch.setattr(register, name, never)
    for case in LEVEL_CASES:
        if case.label != MUST_FLAG:
            continue
        assert _levels(case.text) == case.expect, (
            f"the level gate LOST {case.expect!r} when the vocabulary lists were removed -- it is "
            f"leaning on the lexicon, which is the failure mode this fence exists to refuse :: "
            f"{case.text!r}")


def test_novel_phrasing_no_lexicon_anticipated_still_fires(monkeypatch) -> None:
    """The generalisation claim, named. These three sentences contain no valuation phrase, no flow
    phrase and no execution idiom -- `market_leaks` and `exec_leaks` are both empty -- and the level
    gate flags them anyway."""
    novel = [c for c in LEVEL_CASES if c.note.startswith("structural-gate proof")]
    assert len(novel) >= 3, "the structural probes were removed from the corpus"
    for case in novel:
        assert register.market_leaks(case.text) == [], (
            f"probe is no longer lexicon-free, it proves nothing structural: {case.text!r}")
        assert register.exec_leaks(case.text) == [], (
            f"probe is no longer lexicon-free, it proves nothing structural: {case.text!r}")
        assert _levels(case.text) == case.expect, f"structural gate went quiet on {case.text!r}"


def test_the_derivation_gate_is_what_makes_a_level_legal(monkeypatch) -> None:
    """The positive half of rule 1: the SAME number is legal when its arithmetic is shown and every
    input is cited, and illegal when it is not. Nothing about the vocabulary changes between the
    two, so the gate is provably about DERIVATION."""
    derived = config_check._OUTLOOK_DERIVED
    bare = config_check._OUTLOOK_BARE
    assert register.outlook_derivation_ok(derived) is True
    assert register.outlook_derivation_ok(bare) is False
    assert _levels(derived) == ()
    assert _levels(bare) != ()
    assert "268" in register.sanitize(derived, market_register=register.OUTLOOK)
    assert "268" not in register.sanitize(bare, market_register=register.OUTLOOK)


# ==================================================================================================
# T5 -- the A2 fence IS a lexicon, and that is the correct shape THERE and only there.
# ==================================================================================================
def test_the_a2_fence_is_a_lexicon_and_that_is_deliberate(monkeypatch) -> None:
    """Rule 2 of the module docstring. With the LEVEL gate fully disarmed (`_level_tokens` stubbed
    to return nothing), every A2 execution probe still fires. The two gates are independent: A2 is
    a POLICY list about what this tool will never say, and nothing could ever back it, so a list is
    the right shape and its blast radius is bounded."""
    monkeypatch.setattr(register, "_level_tokens", lambda sent: [])
    assert _levels("Coffee should reach 268 by year end.") == (), "the level gate was not disarmed"
    for probe in config_check._OUTLOOK_A2:
        assert register.exec_leaks(probe), (
            f"A2 probe went quiet once the level gate was disarmed -- the execution fence is "
            f"leaning on the level gate, which it must not: {probe!r}")


# ==================================================================================================
# T6 -- part (c), MECHANISED: every EXEMPTION word must be justified by a non-flagging case.
# ==================================================================================================
@pytest.mark.parametrize("name,read,install", EXEMPTION_LEXICONS, ids=[e[0] for e in EXEMPTION_LEXICONS])
def test_every_exemption_word_is_justified_by_a_non_flagging_case(name, read, install, monkeypatch) -> None:
    """Leave-one-out over the lexicon's OWN pattern text: drop each alternative, rebuild the regex,
    and re-run every corpus case that asserts a number is NOT a level. If dropping the word changes
    no verdict, the word is buying nothing and is pure attack surface -- which is precisely how
    'order' entered `_POLICY_LEAD` and served "work the order 1850" verbatim.

    The word list is read from the live module, so a word added tomorrow is enumerated tomorrow.
    There is no hand-maintained mirror to fall out of date."""
    alternatives = read()
    assert len(alternatives) > 1, f"{name}: cannot leave-one-out a single-alternative lexicon"
    baseline = [_levels(c.text) for c in NON_FLAGGING_LEVEL_CASES]
    unjustified = []
    for alt in alternatives:
        rest = [a for a in alternatives if a != alt]
        with monkeypatch.context() as mp:
            install(mp, "|".join(rest))
            observed = [_levels(c.text) for c in NON_FLAGGING_LEVEL_CASES]
        if observed == baseline:
            unjustified.append(alt)
    if name == "_HYPHEN_QTY":
        assert set(unjustified) == set(HYPHEN_QTY_WAIVER), (
            f"_HYPHEN_QTY waiver is stale. Reason on file: {HYPHEN_QTY_WAIVER_REASON}\n"
            f"  newly unjustified (add a case, or add to the waiver with a reason): "
            f"{sorted(set(unjustified) - set(HYPHEN_QTY_WAIVER))}\n"
            f"  now justified (drop from the waiver): "
            f"{sorted(set(HYPHEN_QTY_WAIVER) - set(unjustified))}")
        return
    assert unjustified == [], (
        f"{name}: exemption word(s) {unjustified!r} justified by NO corpus case. An exemption word "
        f"REMOVES teeth from the level gate. Add the measured false positive that motivated it as a "
        f"MUST_NOT_FLAG case in this file, or remove the word. Do NOT waive it: 'order' was added on "
        f"exactly this evidence standard and served a fabricated level verbatim (incident I-3).")


def test_the_hyphen_qty_waiver_cannot_absorb_a_word_gated_exemption() -> None:
    """The waiver is frozen to ONE lexicon by construction. If a future edit tries to reuse it for
    `_POLICY_LEAD` or `_YEAR_ADJ`, the branch above never consults it and the assertion still
    fires. This test pins that the waived set is exactly the shape-gated unit nouns and carries a
    stated reason, so the waiver can never become a general escape hatch."""
    assert HYPHEN_QTY_WAIVER_REASON.strip(), "a waiver without a stated reason is not a waiver"
    live = set(_split_alternatives(_first_group(register._HYPHEN_QTY.pattern)[1]))
    assert HYPHEN_QTY_WAIVER <= live, (
        f"waiver names words that are no longer in _HYPHEN_QTY: {sorted(HYPHEN_QTY_WAIVER - live)}")
    for other, read, _install in EXEMPTION_LEXICONS:
        if other == "_HYPHEN_QTY":
            continue
        assert not (set(read()) & HYPHEN_QTY_WAIVER), (
            f"{other} now shares words with the _HYPHEN_QTY waiver -- the waiver must not become a "
            f"general exemption escape hatch")


# ==================================================================================================
# T7 -- the mirror for the DETECTION lexicons: every alternative must be REACHABLE by some probe.
# ==================================================================================================
def test_detection_lexicon_alternatives_are_each_exercised(monkeypatch) -> None:
    """Leave-one-out over the four detection alternations. An alternative no probe reaches is an
    unproven claim: it was written from imagination, and the 2026-07-30 `_EXEC_EXTRA` incident is
    what imagination costs (6 of 12 honest ag sentences deleted, every test green).

    NOTE THE LIMIT, stated in the module docstring: this proves each alternative is EXERCISED. It
    cannot prove one is SAFE -- that needs honest counter-examples, which only a reader can write."""
    baseline_clean = {p: _detection_verdict([p])[0] for p in config_check._DETECTOR_CLEAN}
    for probe in config_check._DETECTOR_CLEAN:
        assert not register.register_leaks(probe) and not register.count_valuation_words(probe) \
            and not register.count_flow_words(probe), f"honest probe FALSE-flagged: {probe!r}"
    for case in CORPUS:
        if case.gate == EXEC and case.label == MUST_NOT_FLAG:
            assert _execs(case.text) == (), f"honest ag prose FALSE-flagged: {case.text!r}"

    baseline = _detection_verdict(_ALL_DETECTION_PROBES)
    unexercised: dict[str, list[str]] = {}
    for name in DETECTION_LEXICONS:
        rx = getattr(register, name)
        alternatives = _split_alternatives(rx.pattern)
        for alt in alternatives:
            rest = [a for a in alternatives if a != alt]
            with monkeypatch.context() as mp:
                mp.setattr(register, name, re.compile("|".join(rest), rx.flags))
                observed = _detection_verdict(_ALL_DETECTION_PROBES)
            if observed == baseline:
                unexercised.setdefault(name, []).append(alt)

    for name, alts in unexercised.items():
        waived = DETECTION_SUBSUMED_WAIVER.get(name, {})
        surprises = [a for a in alts if a not in waived]
        assert surprises == [], (
            f"{name}: alternative(s) {surprises!r} are reached by NO probe. Either add a probe that "
            f"only that alternative can match (DETECTION_PROBES in this file), or -- if it is a "
            f"strict subset of another alternative and therefore dead -- record it in "
            f"DETECTION_SUBSUMED_WAIVER with the alternative that subsumes it.")
    for name, waived in DETECTION_SUBSUMED_WAIVER.items():
        stale = [a for a in waived if a not in unexercised.get(name, [])]
        assert stale == [], (
            f"{name}: waived alternative(s) {stale!r} ARE now exercised -- drop them from "
            f"DETECTION_SUBSUMED_WAIVER so the waiver stays exactly as small as it needs to be")


def test_baseline_lexicons_are_not_already_degenerate() -> None:
    """A guard on T6/T7 themselves: a leave-one-out proves nothing if the alternation is a single
    alternative or the splitter silently returned garbage."""
    for name in DETECTION_LEXICONS:
        alts = _split_alternatives(getattr(register, name).pattern)
        assert len(alts) >= 5, f"{name}: splitter returned {len(alts)} alternative(s)"
        assert all(a.strip() for a in alts), f"{name}: splitter produced an empty alternative"
        assert re.compile("|".join(alts), getattr(register, name).flags).pattern == \
            getattr(register, name).pattern, f"{name}: splitter is not round-trip faithful"
    for name, read, _install in EXEMPTION_LEXICONS:
        alts = read()
        assert len(alts) >= 5, f"{name}: splitter returned {len(alts)} alternative(s)"
        assert all(a.strip() for a in alts), f"{name}: splitter produced an empty alternative"


# ==================================================================================================
# T8 -- provenance. A corpus without provenance is a pile, and a pile gets edited to make CI green.
# ==================================================================================================
_PROVENANCE = re.compile(r"\bI-\d\b|\b20\d\d-\d\d-\d\d\b|\b20\d\d-\d\d\b")


@pytest.mark.parametrize("case", CORPUS, ids=lambda c: c.text[:48])
def test_every_case_carries_provenance(case: Case) -> None:
    """Each case names the incident or the measurement that produced it. Without that, a future
    reader cannot tell a measured case from a guess, and will delete the one that blocks them."""
    assert case.note.strip(), f"case has no provenance note :: {case.text!r}"
    assert _PROVENANCE.search(case.note), (
        f"provenance must name an incident (I-1/I-2/I-3) or a measurement date :: "
        f"{case.note!r} for {case.text!r}")
    assert case.gate in (LEVEL, EXEC), f"unknown gate {case.gate!r}"


def test_corpus_has_no_duplicate_texts() -> None:
    """Two cases with the same text and different labels is the contradiction that a future
    'just add the word' fix would create. Fail on the duplicate, not on the coin-flip."""
    seen: dict[str, Case] = {}
    for case in CORPUS:
        prior = seen.get(case.text)
        assert prior is None, (
            f"duplicate corpus text {case.text!r}: {prior.label}/{prior.gate} vs "
            f"{case.label}/{case.gate}")
        seen[case.text] = case
