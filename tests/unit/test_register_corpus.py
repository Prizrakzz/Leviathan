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
from leviathan.graphrag.numbers import agent as agent_mod
from leviathan.graphrag.numbers import cascade
from leviathan.graphrag.numbers import outcomes
from leviathan.graphrag.numbers import pattern_records

MUST_FLAG = "MUST_FLAG"
MUST_NOT_FLAG = "MUST_NOT_FLAG"
LEVEL = "level"
EXEC = "exec"
# C1/D1, 2026-08-01: the THIRD gate this corpus pins -- the RAW flow/positioning register
# (`register.count_flow_words`, which `answer._count_banned_flow` is), added when the R9 context lane
# opened a deterministic COT leg. C1's acceptance bound is that the leg's rendered lines and its
# narration addendum add ZERO raw flow hits, and the teeth are the forward-looking rewrites that MUST
# still fire if anyone turns the leg into guidance. Note what this gate does NOT claim: under OUTLOOK
# the flow fence is RELEASED by design (register.py `if not outlook:`), so a MUST_FLAG flow case is
# COUNTED on every turn but STRIPPED only on a fenced one -- pinned below rather than assumed.
FLOW = "flow"


class Case(NamedTuple):
    """One pinned corpus case.

    text   -- the prose, verbatim as measured.
    label  -- MUST_FLAG / MUST_NOT_FLAG. Derived from `expect` and cross-checked, never decorative.
    gate   -- which detector decides it: LEVEL (`unbacked_levels`), EXEC (`exec_leaks`) or FLOW
              (`count_flow_words`, surfaced token-wise by `_flows`).
    expect -- the EXACT token tuple the gate must return. Exact, never a superset: an over-fire is
              as much a bug as an under-fire, and this incident was both.
    note   -- one line of provenance. Which incident, or which measurement on which date.
    """

    text: str
    label: str
    gate: str
    expect: tuple
    note: str


# J6 / OUTCOMES_JOIN D-OJ-18. The pairing line's pinned arguments, and the line itself rendered from
# the LIVE renderer at import. Kept as a named constant so `test_every_j6_rendered_line_is_pinned` can
# re-render and compare rather than restate: a corpus case that is a COPY of a render stops pinning the
# render the day the render moves, which is the one thing this file is for.
J6_LINE_ARGS = dict(event_date="2024-03-12", horizon_days=90, value=8.2431,
                    contract_month="2024-07", coverage_start="2010-06-06")
J6_LINE = cascade.cot_outcome_line(7, "corn_cbot", **J6_LINE_ARGS)

# J5 / OUTCOMES_JOIN item 83. The SAME discipline, applied to the other conditional-performance
# sentence this wave adds: a median, a decile spread and "N of them closed higher" over past firings of
# one (driver, contract) pair. It carries no arrow and a citation handle, so on an OUTLOOK turn
# `register._is_banned_sentence` returns False for it and it ships as a setup -- which is why the leg
# now holds itself out of outlook turns entirely (D-OJ-17 option (a), `pattern_outcome_legs(outlook=)`)
# and why the sentence is pinned HERE, to the live renderer, on the FENCED lane it does run on.
J5_SCOPE = {"driver_or_chain_id": "export_pace", "contract": "corn_cbot"}
J5_SIGNAL = {"horizon_days": 30, "outcome_suppressed": None, "basis": outcomes.BASIS_SURVIVOR,
             "joined": 9, "n_closed": 8, "n_pending": 1, "median": 2.4, "p10": -3.1, "p90": 7.8,
             "n_up": 5, "n_independent": 8, "first_closed_firing": "2024-01-03",
             "last_closed_firing": "2025-02-11", "first_pending_close": "2026-08-20"}
J5_LINE = pattern_records.pattern_outcome_answer(J5_SCOPE, (7, {}), dict(J5_SIGNAL),
                                                 asof="2026-07-31")

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

    # -- C1 / D1, THE R9 CONTEXT LANE. MUST_NOT_FLAG half: the deterministic COT context leg as the
    #    engine actually renders it, plus the narration addendum that closes it. This is C1's
    #    acceptance bound -- "the leg adds ZERO raw flow-register hits" -- written as cases so it
    #    survives every later edit to the leg. Rendered verbatim 2026-08-01 from cascade.quantify
    #    (pace on, silver_cot mapped as the context leg); the live-render half, which follows the
    #    engine wherever the render goes, is tests/unit/test_cascade_cot_context.py. -------------
    Case("- [N1] corn_cbot mm_net 2025-07-31..2026-07-31 (current, as-of 2026-07-31): 118432 "
         "contracts [series: corn_cbot; table: silver_cot]", MUST_NOT_FLAG, FLOW, (),
         "C1/D1 context leg, rendered verbatim by cascade.quantify 2026-08-01: the dated level"),
    Case("- [N2] change in mm_net from the prior week (weekly pace): +2400 contracts "
         "[series: corn_cbot; table: silver_cot]", MUST_NOT_FLAG, FLOW, (),
         "C1/D1 context leg, rendered verbatim 2026-08-01: the weekly window_change row"),
    Case("- [N3] mm_net rose in each of the last 3 weeks [series: corn_cbot; table: silver_cot]",
         MUST_NOT_FLAG, FLOW, (),
         "C1/D1 context leg, rendered verbatim 2026-08-01: the streak row, past tense"),
    # The addendum is read from the ENGINE, never restated: an edit that smuggles the flow register
    # back into the prompt fails right here, which is the point of pinning the object and not a copy.
    Case(cascade.POSITIONING_CONTEXT_ADDENDUM, MUST_NOT_FLAG, FLOW, (),
         "C1/D1 acceptance bound, measured 2026-08-01: the narration addendum names no flow idiom, "
         "because writing the prohibition into the prompt is how the idiom reaches the draft"),
    Case("Managed money net length was 118432 contracts on the 2026-07-28 report date [N1].",
         MUST_NOT_FLAG, FLOW, (),
         "C1/D1, measured 2026-08-01: the honest past-tense narration the leg exists to enable"),

    # -- C1 / D1, THE TEETH. Each is a forward-looking rewrite of a line above, and each MUST still
    #    fire. The first is not hypothetical: rep_outlook_r3.md:397 recorded `register leaks (1):
    #    crowded long` on the exact row C1 targets, with ZERO cot rows in the panel -- the model
    #    reaches for this register whether or not a number exists, which is why the leg must not
    #    hand it one AND a vocabulary. ------------------------------------------------------------
    Case("A crowded long here unwinds sharply if the catalyst pauses.", MUST_FLAG, FLOW,
         ("crowded long",),
         "MEASURED post-sanitize residual on ol_soyoil_positioning_leg, rep_outlook_r3.md:413, "
         "2026-07-31 -- the leak that made D1 a decision rather than a formality"),
    Case("- [N5] corn_cbot managed-money net length is stretched at +1.8 sigma vs the 3-yr mean "
         "[series: corn_cbot; table: COT]", MUST_FLAG, FLOW, ("stretched",),
         "C1/D1 teeth 2026-08-01: the context leg's own line turned into a verdict (the tag carries "
         "dp.table_label per A1, so this mirrors the shipped render)"),
    Case("This is one-sided positioning heading into the December expiry.", MUST_FLAG, FLOW,
         ("one-sided positioning",),
         "C1/D1 teeth 2026-08-01: the idiom eval_queries_outlook_v1 names as DELETED on a fenced turn"),
    Case("If funds liquidate, the nearby could fall.", MUST_FLAG, FLOW, ("If funds liquidate",),
         "C1/D1 teeth 2026-08-01: the conditional-unwind shape, the leg's most direct forward reading"),
    Case("POSITIONING CONTEXT: net length is crowded relative to the 3-yr window, so watch for a "
         "squeeze.", MUST_FLAG, FLOW, ("crowded",),
         "C1/D1 teeth 2026-08-01: the ADDENDUM itself, rewritten forward -- the exact edit this "
         "corpus exists to refuse"),

    # -- C2 / D3, THE HONEST DECLINE LINE. The four shapes' rendered sentences, verbatim from
    #    agent.shape_decline_line 2026-08-01. They are pinned here and NOT only in the C2 lint
    #    because a decline is prose the reader is served on a turn that produced no number: it is
    #    the sentence most likely to be edited later for tone, and tone is exactly how a positioning
    #    ABSENCE turns into a positioning READ. test_every_c2_decline_line_is_pinned re-renders them
    #    off the live template + config, so an edit to either fails here rather than in production.
    Case("One limitation to flag before the numbers: the record holds no managed-money positioning "
         "reading for that window, so positioning is not narrated here.", MUST_NOT_FLAG, FLOW, (),
         "C2/D3 decline line, rendered verbatim by agent.shape_decline_line 2026-08-01: the "
         "positioning shape -- absence stated about the RECORD, with no idiom to attach to"),
    Case("One limitation to flag before the numbers: the record holds no ENSO reading and no "
         "drought-index reading for that window, so the seasonal signal is not quantified here.",
         MUST_NOT_FLAG, FLOW, (),
         "C2/D3 decline line, rendered verbatim 2026-08-01: the seasonality shape, both subjects "
         "empty -- the multi-subject join is pinned too, not just the single"),
    Case("One limitation to flag before the numbers: the record holds no weekly export-sales "
         "reading for that window, so export pace is not quantified here.", MUST_NOT_FLAG, FLOW, (),
         "C2/D3 decline line, rendered verbatim 2026-08-01: the pace shape"),
    Case("One limitation to flag before the numbers: the record holds no stocks-to-use reading for "
         "that window, so the balance-sheet anchor is not quantified here.", MUST_NOT_FLAG, FLOW, (),
         "C2/D3 decline line, rendered verbatim 2026-08-01: the outlook shape -- the s/u miss the "
         "judge named on 37 of 58 rows, now stated instead of silent"),

    # -- C2 / F4, THE SCOPED FORM -- the sentence the reader ACTUALLY gets. The four above are the
    #    unscoped renders, kept because they are the register baseline; but "the record holds no X for
    #    that window" is a claim about THE RECORD on the strength of a fetch that only proved the
    #    MODEL'S QUERY matched nothing (agent._exec's own comment: "filter/scope mismatch OR a lake
    #    gap"). shape_decline now always names the read -- slug, window, as-of -- and the slug renders
    #    through display._contract_label so sanitize is a no-op on it. Pinned with the canonical
    #    agent.SHAPE_SCOPE_PROBE, which the C2 build lint censuses with too.
    Case("One limitation to flag before the numbers: the record holds no managed-money positioning "
         "reading for CBOT corn over 2026-01-01..2026-07-31, so positioning is not narrated here.",
         MUST_NOT_FLAG, FLOW, (),
         "C2/F4 scoped decline line, rendered verbatim 2026-08-01: naming the contract and the window "
         "adds no idiom -- the absence is still about a READ and still has nothing to attach to"),
    Case("One limitation to flag before the numbers: the record holds no ENSO reading for CBOT corn over "
         "2026-01-01..2026-07-31 and no drought-index reading for CBOT corn over 2026-01-01..2026-07-31, "
         "so the seasonal signal is not quantified here.", MUST_NOT_FLAG, FLOW, (),
         "C2/F4 scoped decline line, rendered verbatim 2026-08-01: the multi-subject join, each subject carrying its OWN scope"),
    Case("One limitation to flag before the numbers: the record holds no weekly export-sales reading for "
         "CBOT corn over 2026-01-01..2026-07-31, so export pace is not quantified here.",
         MUST_NOT_FLAG, FLOW, (), "C2/F4 scoped decline line, rendered verbatim 2026-08-01: the pace shape"),
    Case("One limitation to flag before the numbers: the record holds no stocks-to-use reading for CBOT "
         "corn over 2026-01-01..2026-07-31, so the balance-sheet anchor is not quantified here.",
         MUST_NOT_FLAG, FLOW, (), "C2/F4 scoped decline line, rendered verbatim 2026-08-01: the outlook shape"),

    # -- C2 / D3, THE TEETH. The decline rewritten to editorialize past its own absence. This is the
    #    live failure mode, not a hypothetical one: rep_outlook_r3.md:413 put "a crowded long
    #    unwinds sharply" in the SAME paragraph as "the current state of managed-money length is not
    #    in the record here". A decline sentence that acquires a flow clause is that render exactly.
    Case("The record holds no managed-money positioning reading for that window, but positioning is "
         "stretched all the same.", MUST_FLAG, FLOW, ("stretched",),
         "C2/D3 teeth 2026-08-01: the r3 render's own shape (rep_outlook_r3.md:413) -- an absence "
         "clause with a flow verdict bolted on"),

    # -- J6 / D-OJ-17+18, THE COT OUTCOME PAIRING. MUST_NOT_FLAG half: the pairing as the engine
    #    renders it, its narration addendum, and the honest desk sentence the two rows support. This
    #    leg is the one that puts a POSITIONING observation and a PRICE MOVE in the same block, so it
    #    is the one most likely to be edited into a performance claim later -- which is why the line
    #    is pinned to the LIVE renderer (test_every_j6_rendered_line_is_pinned) and the addendum to the
    #    LIVE object, not to copies of either. ---------------------------------------------------
    Case(J6_LINE, MUST_NOT_FLAG, FLOW, (),
         "J6/D-OJ-18, rendered verbatim by cascade.cot_outcome_line 2026-08-01: a level of record and "
         "a move of record, joined by nothing -- and the per-slug coverage start stated on the line"),
    Case(cascade.COT_OUTCOME_ADDENDUM, MUST_NOT_FLAG, FLOW, (),
         "J6/D-OJ-18 acceptance bound, measured 2026-08-01: the pairing's narration addendum names no "
         "flow idiom and refuses the causal reading the pairing invites, without naming one either"),
    Case(J5_LINE, MUST_NOT_FLAG, FLOW, (),
         "J5/item 83, rendered verbatim by pattern_records.pattern_outcome_answer 2026-08-01: the "
         "OTHER conditional-performance sentence of this wave -- a median, a decile spread and a count "
         "that closed higher, all past tense, with the pending count never dropped and the basis "
         "stated. It is arrow-free and cited, which is exactly why the leg holds itself out of OUTLOOK "
         "turns rather than relying on a phrasing rule (adversarial finding 9)"),
    Case("Managed money net length was 118432 contracts on the 2024-03-12 report date [N1], and across "
         "the 90 days that followed, the July delivery settle changed by 8.2431% [N7].",
         MUST_NOT_FLAG, FLOW, (),
         "J6/D-OJ-18, measured 2026-08-01: the honest two-record narration the leg exists to enable -- "
         "two dated facts, each on its own handle, with no verb joining them"),

    # -- J6 / D-OJ-17+18, THE TEETH. Each is the pairing rewritten forward, which is the edit this leg
    #    makes tempting: it hands a draft a positioning level and a realized move in the same block, and
    #    the step from "and then" to "and therefore" is one word. NOTE WHAT THESE DO AND DO NOT PROVE --
    #    see test_the_performance_framing_is_not_caught_by_any_register_detector in
    #    tests/unit/test_outcomes_serving_legs.py: the flow lexicon catches the POSITIONING idioms, and
    #    it does NOT catch a bare conditional-performance claim. That is skeptic F13, and it is why J6's
    #    real fences are structural (outlook-held-out, POSITIONING_TABLES membership, the unit
    #    whitelist) rather than a word list. -----------------------------------------------------
    Case("With managed money crowded long on the report date, the following quarter looks like the "
         "last one.", MUST_FLAG, FLOW, ("crowded long",),
         "J6 teeth 2026-08-01: the pairing turned into a setup -- the same idiom rep_outlook_r3.md:413 "
         "produced with ZERO cot rows in the panel, now with two real rows beside it"),
    Case("If funds unwind from here, the next 90-day window repeats that move.", MUST_FLAG, FLOW,
         ("If funds unwind",),
         "J6 teeth 2026-08-01: the conditional-unwind shape, which is what a realized forward move "
         "beside a positioning level invites most directly"),
    Case("POSITIONING AND PRICE: net length is crowded relative to the record, so the window ahead "
         "should rhyme.", MUST_FLAG, FLOW, ("crowded",),
         "J6 teeth 2026-08-01: the ADDENDUM itself, rewritten forward -- the exact edit this corpus "
         "exists to refuse, in the J6 lane as well as the C1 one"),
)

LEVEL_CASES = tuple(c for c in CORPUS if c.gate == LEVEL)
EXEC_CASES = tuple(c for c in CORPUS if c.gate == EXEC)
FLOW_CASES = tuple(c for c in CORPUS if c.gate == FLOW)
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


def _flows(text: str) -> tuple[str, ...]:
    """The RAW flow-register surfaces `register.count_flow_words` counts, returned as the matched TEXT
    so a case can pin exactly WHICH idiom fired rather than a bare integer. It re-walks the counter's
    own two halves (the Lane A `_FLOW_PHRASES` alternation and the Lane B windowed triad) off the live
    objects -- and `test_flow_surfaces_agree_with_the_counter` asserts `len()` of this equals
    `count_flow_words` on every case, so this mirror can never drift from the number the decks pin."""
    prose = register._strip_mermaid(text)
    hits = [m.group(0) for m in register._FLOW_PHRASES.finditer(prose)]
    for sent in register._SENT_ITER.split(prose):
        if register._EXCLUDED_NOUN.search(sent):
            continue
        if register._WINDOW_NOUN.search(sent) or register._WINDOW_COMPARISON.search(sent):
            hits += register._LANE_B_FLOW_RX.findall(sent)
    return tuple(hits)


def _observed(case: Case) -> tuple[str, ...]:
    if case.gate == LEVEL:
        return _levels(case.text)
    return _flows(case.text) if case.gate == FLOW else _execs(case.text)


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
    """A one-sided corpus is how the pendulum swings. Every gate must carry both labels."""
    for gate in (LEVEL, EXEC, FLOW):
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
# T2b (C1/D1) -- the RAW flow gate reaches the deck, and the OUTLOOK asymmetry is pinned, not assumed.
# ==================================================================================================
@pytest.mark.parametrize("case", CORPUS, ids=lambda c: c.text[:48])
def test_flow_surfaces_agree_with_the_counter(case: Case) -> None:
    """`_flows` is a mirror of `count_flow_words`, and a mirror that drifts is worse than none: the
    corpus would pin tokens the deck's counter never charged. Asserted on EVERY case, not just the
    flow ones, so a register.py edit that moves a phrase between the two halves is caught here."""
    assert len(_flows(case.text)) == register.count_flow_words(case.text), (
        f"the corpus flow mirror drifted from register.count_flow_words :: {case.text!r}")


@pytest.mark.parametrize("case", [c for c in FLOW_CASES if c.label == MUST_NOT_FLAG],
                         ids=lambda c: c.text[:48])
def test_context_lane_lines_bound_raw_banned_flow_at_zero(case: Case) -> None:
    """C1's acceptance bound, end to end: the deterministic COT context leg -- its rendered lines AND
    its narration addendum -- adds nothing to the RAW counter the decks pin (`banned_flow: 0` on the
    four fenced positioning rows, `max_banned_flow` on the outlook row). A leg that shipped and moved
    this number would have passed every OTHER check C1 lists, which is exactly why the bound exists."""
    assert answer._count_banned_flow({"tldr": case.text, "mechanism": ""}) == 0, (
        f"the context leg added raw flow register: {_flows(case.text)!r} :: {case.text!r}")


@pytest.mark.parametrize("case", [c for c in FLOW_CASES if c.label == MUST_FLAG],
                         ids=lambda c: c.text[:48])
def test_must_flag_flow_is_counted_everywhere_but_stripped_only_when_fenced(case: Case) -> None:
    """The teeth, and the fence correction D1 turns on, as ONE measurement.

    COUNTED on every turn: `_count_banned_flow` reads the RAW draft, so the deck sees the idiom
    whatever register the answer was written in. STRIPPED only under FENCED: `register.py`'s
    `_FLOW_PHRASES` / Lane B arms sit inside `if not outlook:`, so the OUTLOOK register releases the
    vocabulary BY DESIGN (eval_queries_outlook_v1 ratifies it with `max_banned_flow: 6`). That
    asymmetry is the whole of D1's "FENCED lane: proceed / OUTLOOK lane: do NOT proceed on C1 alone",
    and it is pinned here so nobody has to take the plan's word for it."""
    assert answer._count_banned_flow({"tldr": case.text, "mechanism": ""}) == len(case.expect)
    # Asserted on the SURFACE, not the whole string: sanitize also humanizes internal slugs
    # (corn_cbot -> "CBOT corn"), so a whole-text compare would read a display rewrite as a strip.
    fenced = register.sanitize(case.text, market_register=register.FENCED)
    outlook = register.sanitize(case.text, market_register=register.OUTLOOK)
    for tok in case.expect:
        assert tok not in fenced, (
            f"the FENCED flow fence went quiet on {tok!r} -- C1 rests on this strip :: {case.text!r}")
        assert tok in outlook, (
            f"the OUTLOOK register now strips flow vocabulary {tok!r}. That is a WELCOME change, but "
            f"it is a register-doctrine change -- update D1's outlook clause, not this line")


def test_the_pinned_addendum_is_the_engines_own_object() -> None:
    """The addendum case must read the LIVE constant, not a copy of it: a copy would let an edit to
    the engine's prompt line ship past this corpus, which is the one thing this file is for."""
    pinned = [c for c in FLOW_CASES if c.text == cascade.POSITIONING_CONTEXT_ADDENDUM]
    assert len(pinned) == 1, "the R9 context-lane addendum is no longer pinned by this corpus"
    assert pinned[0].label == MUST_NOT_FLAG and pinned[0].expect == ()


def test_every_j6_rendered_line_is_pinned() -> None:
    """J6's rendered pairing is pinned to the LIVE renderer, the addendum discipline applied to the one
    line that carries BOTH a positioning observation and a realized forward move. Any edit to
    `cascade.cot_outcome_line` -- a joining verb, a direction word, a dropped coverage start -- fails
    HERE, in the file that may not be edited to make a change pass, rather than in production."""
    texts = {c.text for c in CORPUS}
    assert cascade.cot_outcome_line(7, "corn_cbot", **J6_LINE_ARGS) in texts, (
        "the J6 pairing line is no longer pinned by this corpus -- add the new render as a case (with "
        "the measurement that justifies the new wording) rather than deleting the old one")
    pinned = [c for c in FLOW_CASES if c.text == cascade.COT_OUTCOME_ADDENDUM]
    assert len(pinned) == 1 and pinned[0].label == MUST_NOT_FLAG and pinned[0].expect == ()
    # The line states its own coverage floor: item 89's "every J6 output states its own per-slug start
    # date", because MGEX positioning runs from 2014 while its tape starts 2025 and a reader shown one
    # number and no floor cannot tell which part of the record was measurable at all.
    assert "record begins 2010-06-06" in J6_LINE


def test_every_j5_rendered_statement_line_is_pinned() -> None:
    """J5's statement branch is pinned to its LIVE renderer for the same reason J6's is: it is a CITED,
    ARROW-FREE CONDITIONAL PERFORMANCE sentence, the one shape `register._is_banned_sentence` returns
    False for under OUTLOOK. Until this pass the corpus pinned only `cascade.cot_outcome_line` and the
    J6 addendum, so an edit to this sentence -- a joining verb, a hit-rate framing, a dropped pending
    clause -- shipped unseen (adversarial finding 9)."""
    texts = {c.text for c in CORPUS}
    live = pattern_records.pattern_outcome_answer(J5_SCOPE, (7, {}), dict(J5_SIGNAL), asof="2026-07-31")
    assert live in texts, (
        "the J5 outcome STATEMENT line is no longer pinned by this corpus -- add the new render as a "
        "case (with the measurement that justifies the new wording) rather than deleting the old one")
    # the three properties the sentence may never lose: past tense with no joining verb, the pending
    # count carried beside the closed one, and the basis stated (the survivor is the front contract in
    # only 25.5-31.7% of anchors, so an unnamed basis is a scope mis-attribution).
    assert "has not closed yet" in live and "neither a firing rate nor" in live
    assert "five calendar days" in live         # NOT "five sessions": the constant is timedelta(days=5)
    # and the OUTLOOK lane never reaches it at all -- the structural half of the same finding
    legs, sig = pattern_records.pattern_outcome_legs(
        {**J5_SCOPE, "kind": "pace"}, "2026-07-31", lambda sql: [], outlook=True)
    assert legs == [] and sig["outcome_suppressed"] == pattern_records.PO_SUP_OUTLOOK_HELD


def test_every_c2_decline_line_is_pinned() -> None:
    """C2's reader-facing sentences are pinned to the LIVE renderer, the addendum discipline applied
    to prose that comes from a CONFIG as well as from code. Two things can move it -- the template in
    agent.shape_decline_line and the `subject`/`omission` strings in question_shapes.yaml -- and a
    config edit is exactly the kind that ships without anyone re-reading the register rule. Rendering
    every shape's ALL-subjects sentence here means either edit fails in this file.

    BOTH FORMS (F4, 2026-08-01). The SCOPED render is the one a reader actually receives -- shape_decline
    always supplies scopes now -- so pinning only the unscoped form would lint a sentence nobody ships."""
    texts = {c.text for c in CORPUS}
    table = agent_mod.load_shape_table()
    assert table, "the C2 shape table did not load -- the corpus below would be vacuous"
    for shape in sorted(table):
        subjects = [str(r.get("subject")) for r in (table[shape].get("requires") or [])
                    if str(r.get("subject") or "").strip()]
        if not subjects:
            continue
        for scopes in (None, [agent_mod.SHAPE_SCOPE_PROBE] * len(subjects)):
            line = agent_mod.shape_decline_line(shape, subjects, scopes)
            assert line in texts, (
                f"the C2 decline line for shape {shape!r} (scoped={scopes is not None}) is no longer "
                f"pinned by this corpus:\n  {line!r}\nAdd it as a case (with the measurement that "
                f"justifies the new wording) rather than deleting the old one -- D3's register "
                f"constraint is what this pins")


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
    assert case.gate in (LEVEL, EXEC, FLOW), f"unknown gate {case.gate!r}"


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
