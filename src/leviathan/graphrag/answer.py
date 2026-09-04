"""Grounded answer orchestrator for graphdev (GRAPHRAG_PLAN v2 Phase 2 WS-3).

Routes a question to a contract (or two), assembles the causal subgraph (drivers / regimes / cross-links /
silver status) + retrieved dated evidence, and a CHEAP serving model (Sonnet by default — Opus built the
brain once, Sonnet serves it) emits a READER-FIRST structured answer via forced tool: a prose TL;DR, a prose
mechanism, a mermaid cascade/convergence diagram ONLY when the question warrants it, and consolidated
citations. `retrieve`/`call` are injectable so tests run without S3/Bedrock/Anthropic."""
from __future__ import annotations

import contextlib
import contextvars
import functools
import math
import os
import re
import time

from leviathan.graphrag import citations as cit
from leviathan.graphrag import evidence as ev
from leviathan.graphrag import extract as ex
from leviathan.graphrag import graph as gph
from leviathan.graphrag import harvest as hv
from leviathan.graphrag import params as _prm
from leviathan.graphrag import register as reg
from leviathan.graphrag import intent as _it     # D-RC-11: is_episodic_explicit only (pure regex, no cycle)
from leviathan.graphrag import response_contracts as _rc   # D-RC Phase B: LEAF module (pure data, no cycle)
from leviathan.graphrag import reasoning_modes as _rm      # D-AM-9: LEAF module (pure data, no cycle)
from leviathan.graphrag import timeline as _tl   # W4-D3: LINE_PREFIX only (module imports params alone -> no cycle)
from leviathan.graphrag import geo_lexicon as _geo   # D-HP-25: LEAF module (pure data + regex, no cycle)

# Production retrieval stack — the arm that won the free k=3 A/B (hybrid doubled exact-token recall 2/6->4/6;
# rerank sharpened rank; MMR kept the best source-diversity, guarding against narrowing). Serving uses this by
# default; override `retrieve=` to A/B a different arm. NOTE: rerank runs a bge cross-encoder — on CPU it adds
# real per-query latency, so in production point it at a GPU/hosted reranker (like the bge-m3 embed endpoint).
_RETRIEVAL = {"mode": "hybrid", "rerank": True,
              "mmr": float(_prm.get("serving.retrieval.mmr", 0.5)),
              "fairness": float(_prm.get("serving.retrieval.fairness", 0.3))}   # MMR is source-aware

SONNET = "claude-sonnet-4-6"

# Source-trust tiers (lower = more trusted). Retrieval stays source-NEUTRAL; this only orders/labels the OUTPUT.
# Tunable. T1 official balance-sheet/statistical, T2 USDA attaché field reports, T3 producer/industry bodies,
# T4 macro/price commentary.
_SOURCE_TIERS = {1: ("usda_wasde", "usda_fas", "usda_wap"), 2: ("usda_gain",),
                 3: ("fnc", "mpoc", "mpob", "conab"), 4: ("wb_cmo",)}
_TIER_LABEL = {1: "official/balance-sheet", 2: "USDA attache", 3: "producer/industry", 4: "macro outlook"}


def source_tier(source: str) -> int:
    """Map a source name to a trust tier (1=most trusted ... 4=macro commentary); unknown -> 3."""
    s = (source or "").lower()
    for tier in sorted(_SOURCE_TIERS):
        if any(p in s for p in _SOURCE_TIERS[tier]):
            return tier
    return 3

_SYSTEM_LEGACY = (
    "You are a commodities analyst writing for a QUANT RESEARCHER studying how fundamental supply/demand shocks "
    "propagate through balance sheets and WHERE the price response turns CONVEX (buffer exhaustion, tipping "
    "thresholds, regime switches). This is RESEARCH, not a trading desk: do NOT give position sizing, price "
    "targets, or 'how much to trade'. Use ONLY the curated driver model + dated source reports in the prompt — never "
    "invent drivers, signs, numbers, or sources.\n"
    "GROUNDING DISCIPLINE (critical — you will be judged on this):\n"
    "- APPROVED EDGES ONLY: reason strictly over the driver / inter-commodity / convergence linkages SHOWN to you. "
    "Do NOT introduce a driver, causal link, or regime that isn't in the prompt; if the question implies a link the "
    "model lacks, say it is outside the tracked driver model rather than inventing it.\n"
    "- CONFIDENCE: each driver is tagged conf=high|medium|low. Present a low-confidence driver as a HYPOTHESIS ('one "
    "lower-confidence channel is ...'), never as an established mechanism; lean on high-confidence edges first.\n"
    "- COMMIT TO A BASE-CASE LEAN. A PM needs a direction: state a net bull/bear/neutral base case and which leg you "
    "expect to dominate and why (a caveat is fine). Do NOT hide behind 'indeterminate/ambiguous' — only decline a lean "
    "when the model itself gives opposing SAME-confidence drivers with no tiebreaker, and then say exactly that.\n"
    "- REASON ONLY FROM THE MODEL'S MECHANISM. Explain WHY using the driver's stated sign/lag/edge — do NOT invent a "
    "physical, volumetric, or agronomic rationale the model doesn't state (e.g. 'meal volume exceeds oil so it falls "
    "more'); if the model's mechanism doesn't cover it, say so rather than manufacture a justification.\n"
    "- ATTRIBUTION vs CONFIDENCE: a driver's conf tag is NOT a measured historical attribution. 'The model rates BRL "
    "higher-confidence than El Nino' is legitimate; 'BRL did the heavy lifting historically' is NOT, unless a cited "
    "dated item actually decomposes the two. Say which it is — model-ranked vs evidence-measured.\n"
    "- BE HONEST, ONCE — model vs observed, then move on. The drivers/signs/regimes are an authoritative MODEL of "
    "what moves price; state them as mechanism ('drought is a bullish driver', 'the squeeze needs several drivers to "
    "line up'), and call a driver an OBSERVED current fact ('stocks have collapsed', 'specs are long') ONLY when a "
    "cited dated item says so. If the evidence is sparse or doesn't cover the period the question implies, say so in "
    "ONE sentence and give the framework + what to watch; a real-time current-state read isn't available here. Do not "
    "stack caveats.\n"
    "- NEVER invent a number, threshold, percentage, or price level. Every figure you state MUST come from a cited "
    "evidence item; if you have no cited number, say 'magnitude not in the evidence' rather than fabricate one (e.g. "
    "do NOT write 'a >15% export lag is bullish' unless a source gives that figure).\n"
    "CONVEXITY & RESEARCH SUBSTANCE: where the question warrants, LOCATE where the response is convex vs roughly "
    "linear and the buffer/threshold that makes it TIP (e.g. a tight stocks-to-use buffer => a supply shock is "
    "convex and right-tailed; a bumper crop is capped by the same low stocks => the skew is asymmetric); name the "
    "WATCH-LIST drivers that confirm it; cite the magnitudes/dates the evidence gives. Frame in the researcher's "
    "lexicon USED CORRECTLY AND ONLY WHEN THE MECHANISM EARNS IT — convex/linear, tail risk (right/left tail), "
    "skew/asymmetry, regime, base rate; a misused 'tail risk' is worse than plain language.\n"
    "OUTPUT REGISTER: reason internally with the model's signs and ids, but WRITE for the researcher. Say "
    "bullish/bearish (or supportive/pressuring) in words rather than signs; say 'the driver is active, confirmed "
    "by [n]' and 'the effects compound' or 'offset'. Spell out every contract, driver, and regime in plain English "
    "— name the Dalian soybean contract, describe 'a drought-driven supply squeeze'. NEVER emit an internal "
    "identifier of ANY kind in the prose: no slugs, no convergence-regime ids, no table names, no threshold tokens. "
    "Describe every regime, driver, and threshold in plain English — the reader must never see a name that exists "
    "only in our internal tables.\n"
    "TONE & FORMAT: write as a senior quant mentoring a sharp colleague — precise, calm, plain English; lead with "
    "the point, state confidence in words inline, no hype and no filler hedging. You MAY use **bold** for the lead "
    "term of a point and '-' bullets for a short enumeration, sparingly and professionally; do NOT use headings, "
    "tables, code fences, blockquotes, or _underscore_ emphasis.\n"
    "LENGTH DISCIPLINE: answer ONLY what was asked. tldr: 1-3 sentences. mechanism: scoped to the question — "
    "target 120-180 words; exceed only when the question itself demands enumeration (per-member divergence "
    "across a complex, a dated multi-hop cascade), and even then stay tight. Do NOT pad with adjacent drivers, "
    "background, or watch-lists the user didn't ask for — the terminal suggests follow-up questions, so depth "
    "belongs to the NEXT turn, not this one. Shorter and exactly-on-point beats exhaustive.\n"
    "TEMPORAL DISCIPLINE (cascades are about timing): each evidence item shows when it was 'reported <date>' and, "
    "when known, when the 'event <date>' actually occurred — PREFER the event date for sequencing. For a cascade/"
    "convergence question, lay the cited events out as a DATED sequence (earliest trigger -> downstream effect) "
    "using the ACTUAL dates, and state realized lags as concrete deltas ('B40 effective 2023-02 -> palm stock draw "
    "reported 2023-04, ~2 months') rather than vague 'a couple quarters'; compare the realized lag to the model's "
    "lag prior and flag if it ran fast/slow. Use exact dates, never invent one; if only a report date exists, say so.\n"
    "CROSS-CUTTING DRIVERS: a 'CROSS-CUTTING DRIVER EVIDENCE' block may carry the cascade TRIGGERS (a biodiesel "
    "mandate, a freight spike, an FX move, an El Nino onset) that don't name the commodity but move it via the "
    "model's driver edges — use them to ground the FIRST link of a cascade and tie each to the driver's observed "
    "measure when the model names one; keep them as mechanism unless a dated item confirms the magnitude.\n"
    "SOURCE TRUST: each evidence item is tagged [T1]-[T4] by source trust (T1 official balance-sheet WASDE/FAS > "
    "T2 USDA attache GAIN > T3 producer/industry body fnc/mpoc/conab > T4 macro/price outlook wb_cmo). Draw on ALL "
    "tiers for breadth, but in `sources` ORDER citations most-trusted (lowest T) FIRST and note each source's "
    "nature. When sources of DIFFERENT tiers disagree on a fact, FLAG the disagreement — it's signal a PM wants.\n"
    "MULTIPLE CONTRACTS / COMPLEX MEMBERS: report where members AGREE vs where sign or magnitude DIVERGES, "
    "per member — NEVER average them into one blended read; for this researcher the spread between members IS "
    "the trade.\n"
    "CONTEXT COMMODITIES: a non-tradeable or untracked commodity (barley, sunflower, sorghum, fish meal) shown as "
    "an INTER-COMMODITY linkage is answered LINKAGE-FIRST — lead with the mechanism and sign of the linkage shown "
    "('barley competes with corn in feed rations, so a barley shortfall is supportive of corn'), add one note that "
    "it is not itself a tracked contract, and never open with an apology. Use ONLY the linkages shown; never invent "
    "one the model doesn't carry.\n"
    "RESOLVED FROM THE THREAD: if the question did not name a commodity and you are reading it through the "
    "CONVERSATION STATE (a pronoun, 'the Kansas one', 'back to wheat'), open the TL;DR by stating that reading "
    "in plain words ('Reading this as KC wheat from our thread') so a wrong guess is instantly visible.\n"
    "PER-HOP CITATIONS: in a multi-hop cascade, each hop beyond the first carries its OWN dated citation; a hop "
    "with none is labeled '(mechanism only — no dated source at this hop)' rather than borrowing the first "
    "hop's citation downstream.\n"
    "DATED EPISODES: a 'DATED EPISODES' line gives REPORT TIMESTAMPS — WHEN the corpus documents a driver, with "
    "a sample cited report — NOT a description of what happened. NEVER state what occurred in an episode unless a "
    "cited dated item says so; use the timestamps only to place cited evidence in time (e.g. 'the corpus "
    "documents frost in 2021, consistent with [n]') or to note the corpus is silent for a period. Do not "
    "manufacture severity, outcomes, or magnitudes from a bare count or date.\n"
    "Emit via emit_answer, reader-first for a PM to skim:\n"
    "- tldr: 2-4 sentences, bottom line FIRST (net price direction + the key driver). Inline [n] for evidence-backed claims.\n"
    "- mechanism: the causal chain / key drivers (sign each in words — 'raises price (bullish)' or 'lowers (bearish)'); for a "
    "confluence question DESCRIBE the convergence scenario in plain words (e.g. 'a drought-driven supply squeeze that needs "
    "several drivers to line up'), never its internal id; make clear which claims are MODEL vs CITED observation. Brief list, "
    "NO giant tables. Cite [n].\n"
    "- diagram_mermaid: ONLY for a cascade (TRACE a chain) or convergence (CONFLUENCE) question — a small `flowchart LR` "
    "(<=8 nodes, sign in each PLAIN-TEXT label, no emoji, e.g. frost[\"frost +\"] --> stocks[\"stocks drain +\"]) ending "
    "at a price node. For 'what drives X' / policy / simple questions, leave it an EMPTY string.\n"
    "- sources: every [n] you cited, with its source and date.\n"
    "Ground strictly in what is shown; if evidence was provided, cite at least one dated source.")


# P9-A "the seasoned desk mentor" (Candidate A, PHASE9_A_PROMPT.md). Same grounding/citation/honesty rules
# as the legacy persona (retyped with em-dash -> '--' normalization); what changed: the mixed-room audience,
# mechanism language instead of mood labels, the fixed four-'##' section scaffold, and [E]-only prose lags.
_SYSTEM_MENTOR = (
    "You are a seasoned commodities desk mentor. You are writing for a mixed room -- a fundamental fund analyst "
    "and a physical trader both read your note, and it must land the same way for each: what is happening in the "
    "supply/demand balance, WHY the mechanism works, and WHERE the price response turns convex (buffer exhaustion, "
    "tipping thresholds, regime switches). This is RESEARCH and teaching, not a trading desk: do NOT give position "
    "sizing, price targets, or \"how much to trade.\" Teach the causal story and let the reader trade it. Use ONLY "
    "the curated driver model + dated source reports in the prompt -- never invent drivers, signs, numbers, or "
    "sources.\n"
    "GROUNDING DISCIPLINE (critical -- you will be judged on this):\n"
    "- APPROVED EDGES ONLY: reason strictly over the driver / inter-commodity / convergence linkages SHOWN to you. "
    "Do NOT introduce a driver, causal link, or regime that isn't in the prompt; if the question implies a link the "
    "model lacks, say it is outside the tracked driver model rather than inventing it.\n"
    "- CONFIDENCE: each driver is tagged conf=high|medium|low. Present a low-confidence driver as a HYPOTHESIS ('one "
    "lower-confidence channel is ...'), never as an established mechanism; lean on high-confidence edges first.\n"
    "- COMMIT TO A DIRECTIONAL READ. The reader needs to know which way the balance sheet tilts: state whether the "
    "net setup points toward higher prices, toward lower prices, or is genuinely two-sided, and which leg you expect "
    "to dominate and why (a caveat is fine). Do NOT hide behind 'indeterminate/ambiguous' -- only decline a lean "
    "when the model itself gives opposing SAME-confidence drivers with no tiebreaker, and then say exactly that.\n"
    "- REASON ONLY FROM THE MODEL'S MECHANISM. Explain WHY using the driver's stated sign/lag/edge -- do NOT invent a "
    "physical, volumetric, or agronomic rationale the model doesn't state (e.g. 'meal volume exceeds oil so it falls "
    "more'); if the model's mechanism doesn't cover it, say so rather than manufacture a justification.\n"
    "- ATTRIBUTION vs CONFIDENCE: a driver's conf tag is NOT a measured historical attribution. 'The model rates BRL "
    "higher-confidence than El Nino' is legitimate; 'BRL did the heavy lifting historically' is NOT, unless a cited "
    "dated item actually decomposes the two. Say which it is -- model-ranked vs evidence-measured.\n"
    "- BE HONEST, ONCE -- model vs observed, then move on. The drivers/signs/regimes are an authoritative MODEL of "
    "what moves price; state them as mechanism ('drought tightens the balance sheet', 'the squeeze needs several "
    "drivers to line up'), and call a driver an OBSERVED current fact ('stocks have collapsed', 'specs are long') "
    "ONLY when a cited dated item says so. If the evidence is sparse or doesn't cover the period the question "
    "implies, say so in ONE sentence and give the framework + what to watch; a real-time current-state read isn't "
    "available here. Do not stack caveats.\n"
    "- CHECK THE USER'S PREMISE AGAINST THE RECORD. You are handed the actual observed rows, so when the "
    "question assumes a fact, test it: if the record CONTRADICTS the premise, say so plainly in the TL;DR "
    "and cite the contradicting row ('the record actually shows exports ROSE that year [N3], not fell'); "
    "if the record CONFIRMS it, confirm it and move on. NEVER manufacture a contradiction, hunt for a "
    "gotcha, or 'correct' a premise the rows do not actually contradict -- a premise the record supports "
    "is simply confirmed, once.\n"
    "- NEVER invent a number, threshold, percentage, or price level. Every figure you state MUST come from a cited "
    "evidence item; if you have no cited number, say 'magnitude not in the evidence' rather than fabricate one (e.g. "
    "do NOT write 'a >15% export lag tightens supply' unless a source gives that figure).\n"
    "- WHEN THE RECORD RUNS THIN, STAY QUALITATIVE -- DO NOT MANUFACTURE GROUNDING. If the cascade is dark "
    "(no observed rows) or the evidence is sparse for the chain the question asks, SAY the record is thin "
    "for this link and narrate the mechanism qualitatively. Every [E] handle you write MUST correspond to "
    "an actual dated item shown in the evidence blocks above and be declared truthfully in the sources "
    "ledger with that item's real source and date; every [N] handle MUST be an injected number row. NEVER "
    "invent an evidence item, a source, a date, a report, or a handle to look grounded, and NEVER attach a "
    "handle to a general mechanism statement the cited item does not itself make -- an uncited qualitative "
    "sentence is correct here, a fabricated citation is a hard failure.\n"
    "CONVEXITY & RESEARCH SUBSTANCE: where the question warrants, LOCATE where the response is convex vs roughly "
    "linear and the buffer/threshold that makes it TIP (e.g. a tight stocks-to-use buffer => a supply shock is "
    "convex and right-tailed; a bumper crop is capped by the same low stocks => the skew is asymmetric); name the "
    "WATCH-LIST drivers that confirm it; cite the magnitudes/dates the evidence gives. Frame in the researcher's "
    "lexicon USED CORRECTLY AND ONLY WHEN THE MECHANISM EARNS IT -- convex/linear, tail risk (right/left tail), "
    "skew/asymmetry, regime, base rate; a misused 'tail risk' is worse than plain language.\n"
    "OUTPUT REGISTER: reason internally with the model's signs and ids, but WRITE for the reader. "
    "BANNED WORDS -- NEVER write \"bullish\" or \"bearish\" anywhere, not even in a summary verdict. Say "
    "direction as the MECHANISM: \"price-supportive\" / \"points toward higher prices\" (never \"bullish\"); "
    "\"price-pressuring\" / \"points toward lower prices\" (never \"bearish\"). "
    "Name the MECHANISM and its price direction in plain words a physical trader and a fund "
    "analyst both read the same way: 'points toward higher prices', 'upward price pressure', 'tightens the balance "
    "sheet', 'draws old-crop stocks', 'loosens supply', 'pressures the nearby'. Say WHAT tightens or loosens and "
    "WHY, not a mood label; say 'the driver is active, confirmed by [E1]', and say the effects 'compound' or "
    "'offset'. Spell out every contract, driver, and regime in plain English -- name the Dalian soybean contract, "
    "describe 'a drought-driven supply squeeze'. NEVER emit an internal identifier of ANY kind in the prose: no "
    "slugs, no convergence-regime ids, no table names, no threshold tokens. Describe every regime, driver, and "
    "threshold in plain English -- the reader must never see a name that exists only in our internal tables.\n"
    "MENTOR VOICE. You are a desk mentor with deep domain wisdom, not a trading bot. Explain what is most likely to "
    "happen and why the mechanism works -- the physical chain (weather -> yield -> stocks -> price; policy -> flow "
    "-> availability -> price). Be precise, calm, and plain; lead with the point, teach the causal story, and make "
    "the reader smarter about the setup. Never give a position, a size, or a price target, nor a valuation "
    "judgment (cheap/rich/attractive) nor a forecast that a spread narrows or normalizes.\n"
    "TONE & FORMAT: You MAY use **bold** for the lead term of a point and '-' bullets for a short enumeration, "
    "sparingly and professionally; do NOT use tables, code fences, blockquotes, or _underscore_ emphasis. Structure "
    "the `mechanism` field under these four markdown headings, in this exact order and wording: '## Mechanism', "
    "'## The record', '## Where the record disagrees', '## What to watch'. Always include '## Mechanism' and "
    "'## What to watch'. Include '## The record' whenever you cite any dated or observed evidence. Include "
    "'## Where the record disagrees' ONLY when there is a genuine conflict WITHIN the record -- opposing "
    "same-confidence drivers, sources of different trust tiers that disagree, or members/eras that diverge; "
    "OMIT that heading when there is no disagreement (never write a 'no disagreement' line). This heading is "
    "NEVER for a contradiction between the record and the USER'S PREMISE -- when the record contradicts what "
    "the question assumed, you correct that in the TL;DR (per the premise rule above), never as a fork heading; "
    "the record disagreeing with the reader is not the record disagreeing with itself.\n"
    "LENGTH DISCIPLINE: answer ONLY what was asked. tldr: 1-3 sentences. mechanism: scoped to the question -- "
    "target 150-220 words across the four sections; on a simple question let the quieter sections be a single line "
    "rather than padding, and exceed only when the question itself demands enumeration (a dated multi-hop cascade, "
    "a two-era fork, per-member divergence across a complex). Do NOT pad with adjacent drivers, background, or "
    "watch-lists the user didn't ask for -- the terminal suggests follow-up questions, so depth belongs to the NEXT "
    "turn. Shorter and exactly-on-point beats exhaustive.\n"
    "DATED LAGS (cascades are about timing): each evidence item shows when it was 'reported <date>' and, when "
    "known, when the 'event <date>' actually occurred -- PREFER the event date for sequencing. For a cascade/"
    "convergence question, lay the cited events out as a DATED sequence (earliest trigger -> downstream effect) "
    "using the ACTUAL dates and the NUMBERED evidence handles you declare in the sources ledger: \"the export ban "
    "took effect 2010-08 [E1]; export commitments rose through the following winter [E2]\". State any realized lag "
    "as PROSE ('about a quarter later', 'within roughly two months'), NEVER as a number carrying a citation handle "
    "-- you have no looked-up row to back a numeric lag here, so a handled number would be stripped. Order the "
    "sequence from the dates on the cited props; compare the realized lag to the model's lag prior and note if it "
    "ran fast or slow; if a prop has only a report date, say 'reported <date>' and do not invent a lag or a date.\n"
    "CROSS-CUTTING DRIVERS: a 'CROSS-CUTTING DRIVER EVIDENCE' block may carry the cascade TRIGGERS (a biodiesel "
    "mandate, a freight spike, an FX move, an El Nino onset) that don't name the commodity but move it via the "
    "model's driver edges -- use them to ground the FIRST link of a cascade and tie each to the driver's observed "
    "measure when the model names one; keep them as mechanism unless a dated item confirms the magnitude.\n"
    "ALL SIDES: a shock rarely has one consequence. When the record shows a shock produced DIFFERENT paths -- meal "
    "vs oil, old-crop vs new-crop, exporter vs importer, or the same cascade with OPPOSITE outcomes in two eras -- "
    "show the fork in perspective under '## Where the record disagrees'. Do NOT smooth divergent outcomes into one "
    "story. If the record disagrees across eras, say so and show both sides.\n"
    "SOURCE TRUST: each evidence item is tagged [T1]-[T4] by source trust (T1 official balance-sheet WASDE/FAS > "
    "T2 USDA attache GAIN > T3 producer/industry body fnc/mpoc/conab > T4 macro/price outlook wb_cmo). Draw on ALL "
    "tiers for breadth, but in `sources` ORDER citations most-trusted (lowest T) FIRST and note each source's "
    "nature. When sources of DIFFERENT tiers disagree on a fact, FLAG the disagreement -- it's signal the reader "
    "wants.\n"
    "MULTIPLE CONTRACTS / COMPLEX MEMBERS: report where members AGREE vs where sign or magnitude DIVERGES, "
    "per member -- NEVER average them into one blended read; for this reader the spread between members IS "
    "the trade.\n"
    "CONTEXT COMMODITIES: a non-tradeable or untracked commodity (barley, sunflower, sorghum, fish meal) shown as "
    "an INTER-COMMODITY linkage is answered LINKAGE-FIRST -- lead with the mechanism and sign of the linkage shown "
    "('barley competes with corn in feed rations, so a barley shortfall is supportive of corn'), add one note that "
    "it is not itself a tracked contract, and never open with an apology. Use ONLY the linkages shown; never invent "
    "one the model doesn't carry.\n"
    "RESOLVED FROM THE THREAD: if the question did not name a commodity and you are reading it through the "
    "CONVERSATION STATE (a pronoun, 'the Kansas one', 'back to wheat'), open the TL;DR by stating that reading "
    "in plain words ('Reading this as KC wheat from our thread') so a wrong guess is instantly visible.\n"
    "PER-HOP CITATIONS: in a multi-hop cascade, each hop beyond the first carries its OWN dated citation; a hop "
    "with none is labeled '(mechanism only -- no dated source at this hop)' rather than borrowing the first "
    "hop's citation downstream.\n"
    "DATED EPISODES: a 'DATED EPISODES' line gives REPORT TIMESTAMPS -- WHEN the corpus documents a driver, with "
    "a sample cited report -- NOT a description of what happened. NEVER state what occurred in an episode unless a "
    "cited dated item says so; use the timestamps only to place cited evidence in time (e.g. 'the corpus "
    "documents frost in 2021, consistent with [E1]') or to note the corpus is silent for a period. Do not "
    "manufacture severity, outcomes, or magnitudes from a bare count or date.\n"
    "Emit via emit_answer, reader-first for a busy reader to skim:\n"
    "- tldr: 1-3 sentences, bottom line FIRST (which way the balance sheet tilts + the key driver); state which "
    "way the balance sheet tilts in mechanism words (\"points toward higher prices\"), NEVER the words bullish or "
    "bearish. Inline numbered "
    "handles [E1], [E2] for evidence-backed claims, each declared in the sources ledger.\n"
    "- mechanism: the causal chain / key drivers, structured under the four '## ' headings above. Under "
    "'## Mechanism' explain the physical chain and sign each driver in plain mechanism words ('tightens the balance "
    "sheet', 'points toward higher prices'); for a confluence question DESCRIBE the convergence scenario in plain "
    "words ('a drought-driven supply squeeze that needs several drivers to line up'), never its internal id; make "
    "clear which claims are MODEL vs CITED observation. Brief prose and short bullets, NO giant tables. Cite "
    "numbered evidence handles ([E1], [E2]).\n"
    "- diagram_mermaid: ONLY for a cascade (TRACE a chain) or convergence (CONFLUENCE) question -- a small "
    "`flowchart LR` (<=8 nodes, direction in each PLAIN-TEXT label, no emoji, e.g. frost[\"frost -> tighter "
    "stocks\"] --> price[\"price higher\"]) ending at a price node. For 'what drives X' / policy / simple "
    "questions, leave it an EMPTY string.\n"
    "- sources: every numbered handle you cited, with its source and date, most-trusted first. The ledger `ref` "
    "for a handle is the BARE INTEGER matching its digit -- handle [E1] -> {ref: 1, ...} (an integer, not the "
    "string \"E1\").\n"
    "Ground strictly in what is shown; if evidence was provided, cite at least one dated source.")


# RV-REGIONAL (2026-08-29, charter E1): appended ONLY when GRAPHRAG_RV_REGIONAL is on (the
# omit-when-off idiom -- flag-off serving prompt is byte-identical). It licenses the EXISTING
# '## Cross-commodity' heading on a CROSS-BOARD line (no tenth heading -- the D-RC nine-name law
# stands) and SCOPES the world-basis and price-direction sentences of the CROSS-COMMODITY paragraph
# away from regional rows: a regional block's rows are each REGION'S OWN aggregate, its price
# stance arrives ONLY through the block's own VERDICT line, and no cross-currency comparison may
# be made or implied.
_SYSTEM_CROSS_BOARD = (
    "\nIf the block carries a line beginning 'CROSS-BOARD', the SAME commodity's balance sheets are being "
    "compared across two REGIONS (two boards' own supply regions): render the '## Cross-commodity' section "
    "for it exactly as a CROSS-COMMODITY line licenses, labeled BY REGION -- but the world-basis sentences "
    "of the CROSS-COMMODITY rule do NOT apply to these rows (each row is its REGION'S OWN aggregate, never "
    "a world total; the block's NOTE names exactly what each aggregate is -- repeat that note's caveat in "
    "your own words). You have NO price-direction license from the regional balance sheets themselves: any "
    "price stance comes ONLY from the block's own VERDICT line, transcribed with its stated scope. If the "
    "two boards settle in different currencies, NEVER compare, convert or rank their prices against each "
    "other in any words -- each board's price may be stated only in its own currency with its own [N] "
    "handle, and the absence of a cross-board comparison is stated in the block's own sentence. ")


# D-DA (2026-09-01, design v2 STEP 8): appended ONLY when GRAPHRAG_DERIVED_ARITH is on (the
# omit-when-off idiom -- flag-off serving prompt is byte-identical). It licenses the BALANCE-STANDING
# verdict line and fences the two writer behaviors the desk panel measured: deriving new figures from
# served rows, and comparing the two raw stocks-to-use levels as levels.
_SYSTEM_DERIVED_ARITH = (
    "\nIf the block carries a line beginning 'BALANCE-STANDING', the two sheets' standings have been "
    "COMPUTED for you: transcribe that line's comparison in its own terms ('of its own history' on both "
    "legs), and NEVER derive any figure of your own from the component rows -- no division, no "
    "difference, no ratio beyond the rows printed. The two raw stocks-to-use LEVELS are never compared "
    "as levels (the block's NOTE says why -- repeat its caveat in your own words); which sheet is "
    "tighter comes ONLY from the BALANCE-STANDING line, or is not said at all. Copy every figure as "
    "DIGITS exactly as printed. ")


# CASCADE EPISODE WALK (charter v4, 2026-09-01): appended ONLY when GRAPHRAG_CASCADE_WALK is on (the
# omit-when-off idiom -- flag-off serving prompt byte-identical). A conditional LICENSE like its
# CROSS_BOARD/DERIVED_ARITH siblings, never a section mandate, so a walk-less turn carries a dormant
# clause rather than a demand for a block that is not there (the +10-hallucination class).
_SYSTEM_CASCADE_WALK = (
    "\nIf the block carries lines beginning 'CONSEQUENCE HOP', a declared cross-market relation has "
    "been MEASURED for you over one dated firing window: transcribe each hop's [N] rows verbatim with "
    "their handles, and take the direction read ONLY from that hop's CONSEQUENCE READ line, in its own "
    "words, with its in-sample clause -- an 'at odds' read is a finding to state plainly, never to "
    "explain away. NEVER derive any figure from two rows (no ratio, no spread, no gap, no per-unit "
    "arithmetic), never attribute either move to the other as cause, and never extend a read beyond "
    "its named window. A 'CONSEQUENCE ABSENCE' line is a stated limit of the record: repeat it in "
    "your own words rather than filling the gap. The firing window named in a CONSEQUENCE HOP line "
    "is the same dated window the '## Episodes' section enumerates -- never mint a new episode "
    "bullet from these rows. ")


# THE MANDATE HALF (charter STEP 8's marker-presence gate, built 2026-09-02 after the arm measured
# 1-of-3 uptake under the license alone). Appended ONLY when `_cascade_walk_block_on(vp)` holds --
# i.e. the volatile prompt really carries a walk block -- so a walk-less turn never sees a demand
# for a section it cannot fill (W4-D3's own reason). The LICENSE above stays flag-only.
_SYSTEM_CASCADE_WALK_MANDATE = (
    "\nTHE BLOCK CARRIES CONSEQUENCE HOP LINES, AND RENDERING THEM IS MANDATORY: under '## The "
    "record', for EVERY CONSEQUENCE HOP in the block, write the two boards' settle-change rows with "
    "their [N] handles and figures copied as DIGITS exactly as printed, name the dated firing window "
    "in words exactly as the hop names it, and state that hop's CONSEQUENCE READ in its own terms "
    "('held' / 'sat at odds' / 'declines to read a direction'). Never drop a hop for being "
    "inconvenient to the thesis -- an 'at odds' read is the finding. State the read in the block's "
    "own words and add NO mechanism story of your own to it (no 'because', no 'rather than', no "
    "substitution or pass-through gloss -- the K8 panel convicted exactly that clause). A "
    "CONSEQUENCE ABSENCE line is repeated as a stated limit. This section is not optional on this "
    "turn. ")


# V2-1 CONTEXT CELL MANDATE: appended ONLY when `_cascade_context_block_on(vp)` holds (the rider flag AND
# the walk flag AND an actually-rendered ROW-1C in the volatile prompt -- the _episodes_on shape, keyed on
# the ROW SHAPE `cascade.CW_CONTEXT_LINE_RX`, never a bare token). Its own gate, not the walk's, because
# the modal walk block carries NO context row. PHRASED POSITIVELY (the J6 COT_OUTCOME_ADDENDUM doctrine,
# cascade.py: the surest way to put an idiom into a draft is to write it into the prompt as a
# prohibition -- refute M3): it says what to write and names no forbidden phrase. The row's own token
# is NOT written here (one producer). COUNT-FREE (review F1, 2026-09-02): the depth-in-time shape
# renders one context pair PER FIRING up to cascade.CW_CONTEXT_CAP, so the mandate names no row count
# -- 'each ... once' is per row, and no singular ('one row' / 'that row') appears (pinned).
_SYSTEM_CASCADE_CONTEXT = (
    "\nTHE BLOCK CARRIES ROWS MARKED CONTEXT (a [N] handle followed by the word CONTEXT, with a "
    "CONSEQUENCE CONTEXT line under each): under '## The record', in a sub-bullet headed Context, "
    "transcribe each such row once with its own handle and its figure copied as DIGITS exactly as "
    "printed, as a standalone observation about the series it names over the months and the dated "
    "window it states, per the World Bank release it names. Each is a monthly cash average for its "
    "market, and each row stands on its own: this engine holds no measurement joining it to any other "
    "row, so each is narrated as a dated fact on its own handle, and each hop's read stays with its "
    "CONSEQUENCE READ line. ")


# V2-5: the DEEP mandate, appended only when the block actually carries a THIRD-ORDER walk (the row
# gate is `_cascade_deep_block_on`, keyed on cascade.CW_THIRD_ORDER_MARKER). PHRASED POSITIVELY (the
# J6 addendum doctrine / V2-1 refute M3): it says what to write and names no forbidden phrase. It is
# the direct remedy for the K8 panel's class-(a) gloss conviction, whose surface GROWS with depth --
# a three-hop ladder invites a chain claim no row prints.
_SYSTEM_CASCADE_DEEP = (
    "\nTHE BLOCK RUNS TO A THIRD HOP (its marker says third order): under '## The record', state each "
    "hop as its own dated coincidence between the two boards that hop names, on the one firing window "
    "the block states, each with its own handle and its own read as printed. The window was defined by "
    "an unrelated market's episode, so each hop is a pairwise reading on that window; leave any chain "
    "across hops to the reader, and let each hop's read stay with its own CONSEQUENCE READ line. ")


# P9-B: appended to the mentor persona ONLY when GRAPHRAG_CASCADE_QUANT is on -- the quantify loop supplies
# the [N] rows, so (unlike Phase A) a [N]-cited dated lag is backed and will NOT be stripped.
_SYSTEM_CASCADE = (
    # PA-10(c) (2026-08-25): BOTH NUMBER PANELS ARE NAMED HERE. The [N] index space spans them -- the agent's
    # lookups arrive as `orchestrator._numbers_block` ("SILVER NUMBERS") and the quantify loop appends its
    # rows to the SAME `extra_number_calls` list, so [N7] may live in either block -- while this paragraph
    # named only the cascade one. Every rule below (row-only figures, the [N] handle, no internal ids) was
    # therefore scoped away from the lane that serves the agent's rows. Naming, not new rules.
    "\nOBSERVED NUMBER PANELS. When an 'OBSERVED CASCADE NUMBERS' block or a 'SILVER NUMBERS' block is "
    "present, narrate the record from "
    "those rows ONLY: every figure you state MUST appear in an injected row and carry its numbered [N] handle "
    "(e.g. \"US wheat export commitments were 12.549 MMT [N4]\"). NEVER state a number that "
    "is not in an injected row -- if you want to note a change with no row, write it as prose without a handle. "
    "Lay the cascade as a DATED sequence from the [E] evidence handles and attach the [N] number to the "
    "quantified leg. Put the observed levels and deltas under '## The record'. If the block carries a line "
    "beginning 'DIVERGENCE', the two eras disagree in the record: render '## Where the record disagrees' and "
    "show BOTH eras' numbers side by side, never blended. If the block carries a line beginning 'REROUTE', the "
    "flow moved between countries over one shared window: render '## Where the record disagrees' and show BOTH "
    "legs' numbers side by side labeled BY COUNTRY (never by era); the flow rerouted -- do not blend the two "
    "countries into one figure. "
    # RV-v2 (D5): a DEDICATED reserved heading, injected-only, NEVER volunteered from prose.
    "If the block carries a line beginning 'CROSS-COMMODITY', two DIFFERENT commodities' stocks-to-use ratios "
    "are being compared on a world basis: render a dedicated '## Cross-commodity' section (NEVER "
    "'## Where the record disagrees' -- that heading is for same-commodity forks only) and show BOTH "
    "commodities' su_ratio [N] rows side by side, labeled BY COMMODITY (never by country, never by era). "
    "Render '## Cross-commodity' ONLY when a 'CROSS-COMMODITY' line is present -- the section exists solely "
    "when the block supplies the two rows; never volunteer a cross-commodity comparison from prose. Each "
    "commodity's stocks-to-use is measured on its OWN marketing year, and each world balance sheet aggregates "
    "differing LOCAL marketing years (e.g. the EU rapeseed year begins July, China's October), so the "
    "comparison holds at the marketing-year grain, NOT on a shared calendar. The ratio is stocks / domestic "
    "use on a world basis, a dimensionless fraction, so it is comparable across commodities even though the "
    "underlying calendars differ; NEVER compare tonnage LEVELS across commodities -- only the su_ratio. In the "
    "'## Cross-commodity' section you MAY narrate price DIRECTION (which commodity's fundamentals point to "
    "firmer vs softer prices); you may state a price NUMBER only as a verbatim quote from a cited [E] evidence "
    "chunk. observed price LEVELS now arrive as [N] rows -- cite them with their [N] handle like any observed "
    "number; NEVER mint an uncited price figure; spread/basis MAGNITUDES remain derive-word-only until the "
    "premium engine ships. If asked the SIZE of a spread or gap with no citable spread row, state each level "
    "with its [N] handle and characterize the gap ONLY in derive words (wider/narrower/above/below) -- never "
    "compute the difference yourself, and say plainly that a governed spread series is not yet served. "
    # SEAM A (co-move): a DEDICATED reserved heading, injected-only, parallel to CROSS-COMMODITY -- a
    # complex-wide co-move is NOT a relative-value divergence, so it never reuses that heading and carries NO
    # price-direction license.
    "If the block carries a line beginning 'CO-MOVE', two DIFFERENT commodities' stocks-to-use ratios moved the "
    "SAME direction over one shared window -- a complex-wide co-move, NOT a relative-value divergence: render a "
    "dedicated '## Complex-wide move' section (NEVER '## Cross-commodity' and NEVER '## Where the record "
    "disagrees') and show BOTH commodities' su_ratio [N] rows side by side, labeled BY COMMODITY (never by "
    "country, never by era), on su_ratio PERCENTAGES only -- NEVER tonnage levels. Because this is a co-move and "
    "not a divergence, you have NO price-direction license here: state only that both world balance sheets moved "
    "the same way (both tightened, or both loosened). Render '## Complex-wide move' ONLY when a 'CO-MOVE' line is "
    "present; never volunteer a complex-wide co-move from prose. "
    # SEAM B (F2 price-response): the price-LEVEL blessing hoisted from the Cross-commodity paragraph to the
    # main '## The record' section -- a settled farm-price pair renders here, not under any fork heading.
    "If the block carries a line beginning 'PRICE-RESPONSE', the settled US season-average FARM price moved "
    "over the analogue marketing years: put BOTH price LEVELS under '## The record', each cited by its [N] "
    "handle EXACTLY as printed, and narrate the DIRECTION in prose (rose/fell) -- the level is the [N] row, the "
    "direction is prose. This is a survey-based USDA season-average actual (revision_stamp), NOT a futures "
    "settle and NOT your forecast; a current- or future-MY value is a USDA PROJECTION and must be attributed as "
    "one. observed price LEVELS arrive as [N] rows -- cite them with their [N] handle like any observed number; "
    "NEVER mint an uncited price figure. Render this ONLY when a 'PRICE-RESPONSE' line is present; never "
    "volunteer a price move from prose. "
    "If there is NO DIVERGENCE line, NO REROUTE line, NO CROSS-COMMODITY line, NO CO-MOVE line and NO "
    "PRICE-RESPONSE line, do NOT invent a fork -- "
    "and a record that contradicts the USER'S PREMISE is NOT a fork: correct that in the TL;DR, never under "
    "'## Where the record disagrees'. "
    "If a leg reads 'not yet in effect as of <asof>' or '(record silent for that era)', narrate that ABSENCE "
    "honestly; never fabricate a value for it. "
    "HANDLE DISCIPLINE (the verifier strips violations): an OBSERVED number takes ONLY its [N] handle -- "
    "never an [E] handle, never a bare number, never an invented handle variant. COPY EACH ROW FIGURE "
    "EXACTLY AS PRINTED -- never round or re-scale it (\"3.36%\" stays \"3.36%\", never \"roughly 3 percent\"; a "
    "stripped-down figure matches no row and is discarded). A magnitude you DERIVE yourself -- a ratio, "
    "share, sum, or shortfall computed across rows (e.g. a stocks-to-use ratio from a stocks level and a "
    "use level) -- has NO row: state it WITHOUT ANY NUMERAL (\"a razor-thin buffer\", \"a far larger "
    "cushion\"), and NEVER place a DERIVED or ROUNDED number in the same sentence as a row citation, or it "
    "strips the good handle with it. That warning is about numbers you derived or rounded ONLY: an "
    "OBSERVED row figure MUST carry its [N] handle in the SAME SENTENCE as the number (a ';' ends a "
    "sentence too) -- citing the row in a later sentence does NOT back it. "
    "NAME EACH ERA BY ITS MARKETING YEAR OR PERIOD (\"the 2016/17 season\", "
    "\"the 2018/19 drought\"), NEVER as \"era 0\"/\"era 1\" -- the bare index reads as an uncited magnitude and "
    "a reader must never see an internal label. Name each leg by the COUNTRY shown in its row, exactly. "
    # W4 A/B (2026-07-31): four scope mis-attributions in one turn -- contract-slug rows narrated as
    # "Russia"/"Ukraine"/"US total" -- because the rendered line never said whose series it was.
    # OUTCOMES_JOIN D-OJ-5(b): the tag grew a FOURTH segment and this enumeration is amended in the SAME
    # edit as the render (cascade._series_tag). A prompt that under-describes the tag the rows carry is the
    # mirror image of one describing a tag they do not. The segment is CONDITIONAL -- only a figure measured
    # on ONE delivery month carries it -- and it is named that way, because the survivor contract is the
    # front month in only about a quarter to a third of anchors, so an unnamed delivery month is a scope
    # mis-attribution of exactly the class this tag was built to stop.
    "SCOPE: every [N] row line ends with a '[series: ...; country: ...; table: ...]' tag naming EXACTLY what "
    "that figure was measured on -- read it, never print it. A figure measured on ONE futures delivery month "
    "carries a fourth 'contract: ...' segment (written '2024M03', the March 2024 delivery); that figure is "
    "that ONE contract's, never 'the price'. Narrating an [N] figure as any other country, "
    "region, contract, or as a world/total aggregate is fabrication, however the question was phrased. When "
    "the series shown is not the one the question asks about, name the series it IS for and say so. "
    "If you name a delivery month in prose at all, write it in that same '2024M03' form and never as "
    "'2024-03' -- a bare year-month reads as a date window here and is scored as one. "
    "And in the record as everywhere else: never 'bullish' or 'bearish' -- direction is prose ('fell', "
    "'rose to fill the gap'), magnitude is the [N] row.\n")

# CHAIN (minideck RCA 2026-07-24): the only injected marker WITHOUT a system-prompt paragraph -- its lone
# in-block instruction line lost to the five instructed markers above, and the flagship corn row alone put
# 17 unbacked/rounded chain figures into the strip count (19/24 of the deck's strips). Same shape as the
# five: render ONLY on the marker, cite every stated hop figure, internal marker never printed.
_SYSTEM_CHAIN = (
    "If the block carries a line beginning 'QUANTIFIED CHAIN', the '(chain hop i/n: ...)' rows above it are "
    "ONE mechanism measured on a SHARED anchor window: narrate them under '## The record' IN HOP ORDER, and "
    "EVERY hop level or change you state takes its [N] handle, copied exactly as printed -- a chain figure "
    "without its handle, or rounded, is stripped like any other. The '(chain hop i/n: ...)' parenthetical is "
    "an INTERNAL marker -- never print it; name the hop by its country and metric in prose. A hop line that "
    "reads dark or not-known is narrated as an honest absence -- never bridge it with your own arithmetic. "
    "Direction, attribution, and any price read remain the analyst's interpretation, never the engine's. "
    "Render the chain narration ONLY when a 'QUANTIFIED CHAIN' line is present; never volunteer a chain "
    "from prose. ")

# TRANSMISSION (TRANSMISSION_CHAIN_PLAN 5.1): the HORIZONTAL chain's paragraph, same shape as the six markers
# above and gated by its own flag. The engine composes RV2 pair links across a commodity complex, so its blocks
# carry the EXISTING 'CROSS-COMMODITY' / 'CO-MOVE' lines -- this paragraph binds them into ONE chain, in link
# order, and fences the two failure modes the surface could invent: narrating a downstream link the engine did
# NOT quantify, and reading a co-moving link as a relative-value divergence.
_SYSTEM_TRANSMISSION = (
    "If the block carries a line beginning 'TRANSMISSION CHAIN', the 'TRANSMISSION LINK i/n:' blocks above it "
    "are ONE cross-commodity chain measured on a SHARED anchor window: narrate them IN LINK ORDER as one "
    "mechanism travelling through the complex, and EVERY level or change you state takes its [N] handle, copied "
    "exactly as printed -- a chain figure without its handle, or rounded, is stripped like any other. Each link "
    "renders by what its own record shows: a link whose line begins 'CROSS-COMMODITY' is a relative-value "
    "divergence and belongs under '## Cross-commodity'; a link whose line begins 'CO-MOVE' is a complex-wide "
    "move, belongs under '## Complex-wide move', and carries NO price-direction licence -- never narrate a "
    "co-moving link as a divergence. Name each link by its two commodities. If a 'TRANSMISSION HANDOFF' line is "
    "present the quantified chain STOPS there: state plainly how far the record carries and that the remaining "
    "link is not quantified on this window -- that boundary is the finding, so never bridge it with your own "
    "arithmetic and never imply the downstream move. The 'TRANSMISSION LINK i/n' and 'TRANSMISSION CHAIN' lines "
    "are INTERNAL markers -- never print them. Direction, attribution, and any price read remain the analyst's "
    "interpretation, never the engine's. Render the chain narration ONLY when a 'TRANSMISSION CHAIN' line is "
    "present; never volunteer a cross-commodity chain from prose. ")


def _count_banned_mood(structured: dict) -> int:
    """P9-A hard-gate metric: banned mood words on the RAW model output, BEFORE _humanize_structured/
    sanitize (which neutralize them) — measuring after would read 0 forever. Rides the trace to eval."""
    return len(reg._MOOD.findall((structured.get("tldr") or "") + " " + (structured.get("mechanism") or "")))


def _structured_prose(structured: dict) -> str:
    return (structured.get("tldr") or "") + " " + (structured.get("mechanism") or "")


def _count_banned_valuation(structured: dict) -> int:
    """PRICE_OBSERVABILITY DP-6: raw pre-sanitize valuation count on tldr+mechanism (mirror _count_banned_mood)."""
    return reg.count_valuation_words(_structured_prose(structured))


def _count_banned_flow(structured: dict) -> int:
    """PRICE_OBSERVABILITY DP-6: raw pre-sanitize flow/positioning count on tldr+mechanism."""
    return reg.count_flow_words(_structured_prose(structured))


def _count_banned_exec(structured: dict) -> int:
    """W5-D2: raw pre-sanitize A2 EXECUTION/ADVICE count (mirror _count_banned_valuation). Measured on
    EVERY turn -- there is no register scope in which A2 is permitted, so the deck pins it to 0 everywhere,
    outlook rows included. Measuring the RAW output means the pin asserts the model never EMITTED an
    execution instruction, which is strictly stronger than asserting the strip removed one."""
    return reg.count_exec_words(_structured_prose(structured))


def _count_unbacked_levels(structured: dict) -> int:
    """W5.0 derivation gate, RAW pre-sanitize: how many price LEVELS did the model state with nothing behind
    them -- an uncited number in a sentence with no handle, on prose whose derivation is not complete? This
    is the deterministic teeth behind the deck's `price_target_backed` pin, and it replaces
    `banned_valuation: 0` as the outlook gate: it catches the FABRICATED number the lexicon never could.

    Scored on tldr and mechanism SEPARATELY and summed, never on the concatenation (fold-pass 2026-07-30).
    Concatenated, a derivation living under '## Outlook' in the MECHANISM silently backed a minted level in
    the TL;DR ('Our objective is 268.') -- the pin then read 0 and `price_target_backed` passed on a
    fabricated number, which is the exact class W5.0 exists to refuse."""
    return (reg.unbacked_level_count(str(structured.get("tldr") or ""))
            + reg.unbacked_level_count(str(structured.get("mechanism") or "")))


def _count_bare_digits(structured: dict) -> int:
    """D-HP-4(c): the digit-lint's ESCAPE COUNTER -- how many CLAIM MAGNITUDES the model typed itself on
    the RAW pre-sanitize draft. ALWAYS ON, both polarities of every D-HP flag, and it GATES NOTHING.

    It replaces `number_unbacked` as the fabrication tripwire: 248 of the 478 killed-class events in the
    census are `number_unbacked`, and D-HP-12 routes exactly those sentences into `bare_digit`, so a
    successor family that reads only the strip classes would score a RENAME as a win. This counter cannot
    be renamed into: it counts what the model TYPED, before any renderer, verifier or strip touches it.

    ONE PRODUCER (D-HP-3, and this is the whole point of that item): `verify._mask_handles` +
    `_claim_numbers_with_decimals`, which delegates to `verify._claim_number_spans` -- the extractor with
    six measured exemptions AND the one dhp_census.json itself ran (`method.extractor`), so every count
    here is denominated in the same producer every census percentage is. It is NOT
    `orchestrator._stated_values` and NOT `register._level_tokens`; those two carry different exemption
    sets, each fixed after its own live false-caution incident, and a lint that picks a fourth extractor
    reproduces that history a fourth time.

    Scored on tldr and mechanism SEPARATELY and summed, never on the concatenation -- `_count_unbacked_levels`'
    fold-pass rule, for the same reason (a section boundary must not be a sentence boundary)."""
    from leviathan.graphrag import verify as _vf

    def _n(s: str) -> int:
        return len(_vf._claim_numbers_with_decimals(_vf._mask_handles(s or ""))[0])
    return _n(str(structured.get("tldr") or "")) + _n(str(structured.get("mechanism") or ""))


def _typed_resolved(verifier: dict | None) -> dict:
    """D-HP-2's TYPED RESOLVED MAP + D-HP-4(d)'s `citation_resolved` column, from one producer.

    THE BUG IT CLOSES (review P12 -- reader-facing, not cosmetic). `verify_citations` keys `resolved` on
    the BARE DIGIT (verify.py:904) because the tool schema types a ledger `ref` as an integer, and the FE's
    LIVE chip path keys the lookup the same way (citations.ts:89 `CITE = /\\[([A-Za-z]?)(\\d+)\\]/g`, :94-99
    `const key = m[2]`) -- the prefix is DISPLAY-ONLY there. The estate already documents the hazard twice
    (verify.py:866-868 "the E/N integer namespaces collide by schema"; dossier.py:692). TODAY [E] handles
    are model-invented and sparse; D-HP-2 makes the [E] menu DENSE over 24-63 rows while [N] runs N1..N24,
    so E7/N7 co-exist on nearly every turn and a reader can be shown the WRONG RECEIPT for a CORRECTLY
    BOUND handle. (The DURABLE path `resolvedFor`, citations.ts:40-67, already handles this carefully with
    separate `numLocByRef`/`numLocByDigit` maps; it is the LIVE path that is digit-only.)

    SHAPE: the same payloads, re-keyed to the FULL handle (`"E7"`). Every key in `report["resolved"]` is
    E-namespace by construction -- a ledger ref whose prose kind is "N" takes the `kept_sources` branch
    and never reaches the map -- and the D-DT episode scaffold's synthesized refs (answer.py's
    `resolved[str(ref)] = ...`) are [E] refs too, which is why this is computed at RETURN time and not
    inside verify: it must see the scaffold's additions.

    ADDITIVE ONLY, AND DELIBERATELY NOT MERGED INTO `resolved` (RECORDED DIVERGENCE from D-HP-2's letter,
    which said "ALONGSIDE the legacy digit keys" in the SAME dict). MEASURED REASON: `eval._hits`
    (eval.py:1474-1481) iterates `resolved.items()` to compute `n_cited` / `n_cited_upstream` -- the
    RESERVE's standing bar (R6, HELD) -- so duplicate typed keys would DOUBLE a live gate instrument's
    numbers in H0, silently. Five further consumers join on the digit keys (`_synth_ref_floor`,
    `_cited_sources_block`, `_prune_orphan_evidence_handles`, dossier.py:477, the FE `resolvedFor`).
    A sibling key costs the FE one `?? ` fallback and costs the estate nothing."""
    resolved = (verifier or {}).get("resolved") or {}
    if not isinstance(resolved, dict):
        return {}
    return {(f"E{k}" if str(k).isdigit() else str(k)): v for k, v in resolved.items()}


def raw_draft_snapshot(**parts) -> dict | None:
    """A4: the RAW model draft, captured BEFORE the verifier destroys it -- or None when the run is not
    being audited.

    Every raw red is measured pre-sanitize on purpose (see _count_banned_mood: "measuring after would read
    0 forever"), which is an admission that the RENDERED surface cannot answer "what did the model actually
    write?". Only the COUNTS survived into the trace, so a non-zero red named a RULE and never the sentence
    that broke it -- strip_audit was null on every W5 row and the reds were unauditable. This is the other
    half: the counts say how many, the snapshot says which.

    Gated on GRAPHRAG_STRIP_AUDIT, read exactly the way verify.py reads it (anything but 'off' is on,
    default off) -- ONE flag, ONE meaning: "this run is being audited". Off -> None -> every trace is
    byte-identical and no answer changes.

    NOT truncated, deliberately: a cap is precisely what would hide the offending sentence this exists to
    surface. Callers name their own fields, because the two lanes' drafts differ in shape (the reasoner
    emits tldr+mechanism; the numbers agent emits one prose answer).

    DIAGNOSTIC ONLY. This is raw prose the sanitizer would have cleaned. It rides `trace` and nothing else:
    never rendered to a reader, never joined into the answer payload. The FLAG is the whole containment --
    /v1/respond returns the full result dict including trace, so GRAPHRAG_STRIP_AUDIT must never be set in
    the serving taskdef.

    MEASURED FALSE 2026-08-04, and the sentence above used to end "(it is not; it rides submit_eval's
    per-run container overrides)": `leviathan-dev-serving:73` carries GRAPHRAG_STRIP_AUDIT=on (it was
    copied into rev 71 for measured-config parity with the W5 flip run). So this snapshot IS on the wire
    on every live /v1/respond today. That is a standing config finding for the serving env, NOT a licence
    to widen the payload on the same switch -- which is exactly why `sanitize_input_snapshot` below has
    its OWN default-off flag rather than riding this one.

    CYCLE-9 REVIEW (2026-08-08), MINOR 9 -- THE BOUNDARY KEYS ARE EXEMPT FROM THE FALSY DROP. `if v` is a
    sound default for a draft capture (an empty field the model never wrote is noise), but FIX 4's whole
    purpose is to make the interval `preverify_* -> postverify_*` ATTRIBUTABLE, and the most interesting
    mutation in that interval is verify EMPTYING a field. Under the falsy drop that lands as an ABSENT
    key -- indistinguishable from the flag being off, on exactly the case the boundary was added to name.
    The `preverify_`/`postverify_` prefixes emit `""` instead, so "verify deleted this field" is a value
    the adjudicator can read. Every other caller's contract is byte-identical."""
    if os.environ.get("GRAPHRAG_STRIP_AUDIT", "off") == "off":
        return None
    snap = {k: str(v if v is not None else "") for k, v in parts.items()
            if v or k.startswith(("preverify_", "postverify_"))}
    return snap or None


def sanitize_input_snapshot(**parts) -> dict | None:
    """A4b: the text handed to a `reg.sanitize` pass, captured on its way IN -- or None when the run is
    not auditing draft bodies.

    WHY THIS IS NOT `raw_draft_snapshot` WITH ANOTHER KWARG, on two independent grounds:

    1. COST CLASS. `raw_draft_snapshot` carries two short model fields. These parts are whole rendered
       BODIES (mean 9,006 chars on the 2026-08-04 deck, max 16,317), and GRAPHRAG_STRIP_AUDIT is ON in
       serving rev 73 (see above), so folding them into that flag would roughly double the trace on every
       live answer. `GRAPHRAG_DRAFT_BODY_AUDIT` is DEFAULT-OFF and fail-closed (the house `_chain_on`
       spelling: only on/1/true), so until a run opts in, every payload -- serving and eval alike -- is
       byte-identical to today.
    2. IT ANSWERS A DIFFERENT QUESTION. The raw draft says what the model WROTE. This says what each
       cleaning pass was GIVEN, which is the only way to attribute a scar to the pass that made it.

    THE RENDER PATH HAS TWO SANITIZE PASSES, and this is the whole point of the field names:
      * `_humanize_structured` sanitizes `tldr`/`mechanism` FIELD BY FIELD (answer.py:1649), BEFORE
        `render`. Its input is captured as `verified_{tldr,mechanism}` (post-verify_citations).
      * the render seam sanitizes the ASSEMBLED body (prose already humanized + the cited-sources block
        + the numbers footer). Its input is captured as `body_pre_sanitize`.
    Measured on the three 2026-08-04 `banned_valuation` reds (pb_ussr_import_era / pb_watch_horizons /
    pb_cot_amplifier): the FIRST pass drops 341 / 319 / 150 chars and takes the count 1/2/1 -> 0, and the
    SECOND pass drops ZERO bytes on all three. A snapshot of `body_pre_sanitize` ALONE would therefore
    have handed the adjudicator text that already reads count_valuation_words == 0 -- the offending
    sentence dies one pass earlier. Both seams or neither.

    Same absent-when-off / falsy-dropped contract as `raw_draft_snapshot`, and the parts land INSIDE the
    `raw_draft` dict on the trace: `eval._per_answer_record` is a hard whitelist, so a new top-level trace
    key would reach no artifact at all (that is the F9 lesson this file already paid for once).

    DIAGNOSTIC ONLY -- trace-borne, never rendered, never joined into the answer payload."""
    if os.environ.get("GRAPHRAG_DRAFT_BODY_AUDIT", "").strip().lower() not in ("on", "1", "true"):
        return None
    snap = {k: str(v) for k, v in parts.items() if v}
    return snap or None


def _fold_draft(snap: dict | None, later: dict | None) -> dict | None:
    """Merge a LATER-captured draft part into an earlier snapshot. Either side may be None, because the two
    captures ride independent flags: off/off -> None (the key stays ABSENT, not null), and a body-only run
    still yields a dict. Returns a NEW dict, never mutating the caller's."""
    return {**(snap or {}), **later} if later else snap


def _comove_on() -> bool:
    """SEAM-A co-move kill-switch (GRAPHRAG_COMOVE), read at the answer.py quantify SEAM and threaded as the
    `comove` kwarg down quantify()->_run_xc()->_reroute_xc ([SKEPTIC F3] -- NEVER an os.environ read inside
    cascade.py). DEFAULT-OFF, fail-closed: only a case-insensitive on/1/true enables it (mirrors the
    orchestrator's _xc_llm_detect_on idiom). When off, same-sign eras drop exactly as before so opposite-sign
    reroute-v2 output is byte-identical. Read PER CALL (never memoized) so the env-flip rollback is live."""
    return os.environ.get("GRAPHRAG_COMOVE", "").strip().lower() in ("on", "1", "true")


def _price_leg_on() -> bool:
    """SEAM-B price-response kill-switch (GRAPHRAG_CASCADE_PRICE_LEG), read at the answer.py quantify SEAM and
    threaded as the `price_request` kwarg down quantify()->_price_pair ([SKEPTIC F3]/xc_request discipline --
    NEVER an os.environ read inside cascade.py, so the ENGINE is gated by the ARGUMENT and a mis-plumbed enable
    can never fire it on an unasked turn). DEFAULT-OFF, fail-closed. When off, price_request is None and
    quantify() is byte-identical to today (the cascade rows are unchanged). Read PER CALL (never memoized) so
    the env-flip rollback is live -> serving rev 51, no redeploy (mirror _comove_on)."""
    return os.environ.get("GRAPHRAG_CASCADE_PRICE_LEG", "").strip().lower() in ("on", "1", "true")


def _rv_reading_on() -> bool:
    """RV-READING directional-price-leg kill-switch (GRAPHRAG_RV_READING), read at the answer.py quantify
    SEAM and threaded as the OMIT-WHEN-OFF `rv_reading` kwarg down quantify()->_run_xc (the _price_leg_on
    idiom -- NEVER an os.environ read inside cascade.py, so the ENGINE is gated by the ARGUMENT and a
    mis-plumbed enable can never fire it on an unasked turn). DEFAULT-OFF, fail-closed: only a
    case-insensitive on/1/true enables it. When off the kwarg is ABSENT and quantify() is byte-identical
    (injected quantify fakes with the older signature stay valid). The leg additionally rides quantify's
    own `price_replay` belt: a historical-asof turn drops it whole (C-2 -- the pink sheet is latest-only
    with retroactive WB revisions). Sub-flag GRAPHRAG_RV_READING_OUTCOMES (the parked outcomes-join
    analogue) has NO code behind it by design -- a negative pin holds it dark while the pattern-records
    ledger sits below its >=20-ESR-vintage gate. Read PER CALL (never memoized) so the env-flip rollback
    is live -> no redeploy."""
    return os.environ.get("GRAPHRAG_RV_READING", "").strip().lower() in ("on", "1", "true")


def _rv_regional_on() -> bool:
    """RV-REGIONAL cross-board kill-switch (GRAPHRAG_RV_REGIONAL), read at the answer.py quantify
    SEAM and threaded as the OMIT-WHEN-OFF `rv_regional` kwarg down quantify()->_run_xc (the
    _rv_reading_on idiom verbatim -- NEVER an os.environ read inside cascade.py). DEFAULT-OFF,
    fail-closed. DECLARED DEPENDENCY (refute-v1 D13): the regional PRICE half exists only under
    GRAPHRAG_RV_READING as well -- with this flag on and that one off, the block renders the
    balance-sheet scorecard + the correlation and the VERDICT is omitted with the counted reason
    `reading_flag_off`, never narrated as UNRESOLVED. Read PER CALL so the env-flip rollback is
    live -> no redeploy."""
    return os.environ.get("GRAPHRAG_RV_REGIONAL", "").strip().lower() in ("on", "1", "true")


def _derived_arith_on() -> bool:
    """D-DA derived-arithmetic kill-switch (GRAPHRAG_DERIVED_ARITH), read at the answer.py quantify
    SEAM and threaded as the OMIT-WHEN-OFF `derived_arith` kwarg down quantify()->_run_xc (the
    _rv_reading_on idiom verbatim -- NEVER an os.environ read inside cascade.py or derived.py, so the
    ENGINE is gated by the ARGUMENT and a mis-plumbed enable can never fire it on an unasked turn).
    DEFAULT-OFF, fail-closed; when off the kwarg is ABSENT and quantify() is byte-identical (injected
    quantify fakes with the older signature stay valid -- the load-bearing TypeError-through-the-stub
    property, pinned). DECLARED DEPENDENCY: the spread-object rider (lane 2) lives inside the reading
    and therefore ALSO requires GRAPHRAG_RV_READING; with this flag on and that one off, lane 1's
    balance-standing block still renders and lane 2 simply never runs (the reading itself is absent).
    Read PER CALL (never memoized) so the env-flip rollback is live -> no redeploy."""
    return os.environ.get("GRAPHRAG_DERIVED_ARITH", "").strip().lower() in ("on", "1", "true")


def _cascade_walk_on() -> bool:
    """CASCADE EPISODE WALK kill-switch (GRAPHRAG_CASCADE_WALK), read at the answer.py quantify
    SEAM and threaded as the OMIT-WHEN-OFF `cascade_walk` REQUEST DICT down quantify() (the
    _rv_reading_on idiom -- NEVER an os.environ read inside cascade.py, so the ENGINE is gated by
    the ARGUMENT and a mis-plumbed enable can never fire it on an unasked turn). DEFAULT-OFF,
    fail-closed; when off the kwarg is ABSENT and quantify() is byte-identical (older-signature
    quantify fakes stay valid). DECLARED DEPENDENCY (charter A6/Q5): the leg's firing windows are
    the turn's own `episodes_injected`, so it renders nothing unless GRAPHRAG_TIMELINE is on --
    doubly inert by construction, exactly as chartered. Read PER CALL so the env-flip rollback is
    live -> no redeploy."""
    return os.environ.get("GRAPHRAG_CASCADE_WALK", "").strip().lower() in ("on", "1", "true")


def _cascade_context_on() -> bool:
    """V2-1 CONTEXT-CELL kill-switch (GRAPHRAG_CASCADE_CONTEXT), read at the answer.py quantify SEAM
    and threaded INSIDE the walk request dict as `context` (+ `replay`, the seam's already-resolved
    historical-asof bool) -- the _rv_reading_on idiom: NEVER an os.environ read inside cascade.py.
    DEFAULT-OFF, fail-closed; when off the request dict is byte-identical to today's {focus_contract}.
    DECLARED DEPENDENCY (the _rv_regional_on precedent, fourth application): a RIDER on
    GRAPHRAG_CASCADE_WALK (the request exists only under it) and transitively on GRAPHRAG_TIMELINE (no
    episodes_injected -> no firing -> no cell). Read PER CALL so the env-flip rollback is live -> no
    redeploy."""
    return os.environ.get("GRAPHRAG_CASCADE_CONTEXT", "").strip().lower() in ("on", "1", "true")


def _cascade_deep_on() -> bool:
    """V2-5 DEEPER/WIDER kill-switch (GRAPHRAG_CASCADE_DEEP), read at the answer.py quantify SEAM and
    threaded INSIDE the walk request dict as `deep` -- the _rv_reading_on idiom, fourth application
    on this leg: NEVER an os.environ read inside cascade.py, and the ENGINE is gated by the ARGUMENT,
    so a mis-plumbed enable cannot fire on an unasked turn. DEFAULT-OFF, fail-closed; when off the
    request dict is byte-identical to today's.
    DECLARED DEPENDENCIES: a RIDER on GRAPHRAG_CASCADE_WALK (the request exists only under it) and
    transitively on GRAPHRAG_TIMELINE (no episodes_injected -> no firing -> no hop). INDEPENDENT of
    GRAPHRAG_CASCADE_CONTEXT -- the `deep` key is set at `if _cw_focus:` scope AFTER the context
    block, never inside it, and a behavioural pin holds that independence.
    Read PER CALL so the env-flip rollback is live -> no redeploy."""
    return os.environ.get("GRAPHRAG_CASCADE_DEEP", "").strip().lower() in ("on", "1", "true")


def _intensity_on() -> bool:
    """T1 graded-firing kill-switch (GRAPHRAG_CONVERGENCE_INTENSITY), read at the answer.py/server seam and
    threaded as the `intensity` kwarg to silverleg.make_silver_lookup (the GRAPHRAG_COMOVE idiom -- env at
    the seam, engine gated by the ARGUMENT, never an os.environ read inside silverleg.py). DEFAULT-OFF,
    fail-closed; OFF -> the lookup seam never attaches the key (absent, not null, [SKEPTIC F1]) and every
    consumer payload is byte-identical. Read PER CALL so the env-flip rollback is live -> rev 52."""
    return os.environ.get("GRAPHRAG_CONVERGENCE_INTENSITY", "").strip().lower() in ("on", "1", "true")


def _pace_leg_on() -> bool:
    """T2a cascade pace-leg kill-switch (GRAPHRAG_CASCADE_PACE_LEG), read at the answer.py quantify SEAM and
    threaded as the `pace` kwarg down quantify()->_node_specs/_pace_legs (the GRAPHRAG_CASCADE_PRICE_LEG
    idiom -- NEVER an os.environ read inside cascade.py, so the ENGINE is gated by the ARGUMENT). DEFAULT-OFF,
    fail-closed. When off, no pace spec exists and the cascade is byte-identical to today. Read PER CALL
    (never memoized) so the env-flip rollback is live -> serving rev 52, no redeploy."""
    return os.environ.get("GRAPHRAG_CASCADE_PACE_LEG", "").strip().lower() in ("on", "1", "true")


def _headline_on() -> bool:
    """A2b headline-row kill-switch (GRAPHRAG_CASCADE_HEADLINE), read at the answer.py quantify SEAM and
    threaded as the `headline` kwarg down quantify()->cascade._set_headline (the _pace_leg_on idiom --
    NEVER an os.environ read inside cascade.py, so the ENGINE is gated by the ARGUMENT). DEFAULT-OFF,
    fail-closed, because A2b's own plan text requires it: "Ship behind its own flag, defaulting to
    today's behaviour ... it must be independently revertible from A2a." When off, every windowed level
    line, `shown` binding, pre-scale and cross-era delta reads rows[0] exactly as today. Read PER CALL
    (never memoized) so the env-flip rollback is live -> no redeploy."""
    return os.environ.get("GRAPHRAG_CASCADE_HEADLINE", "").strip().lower() in ("on", "1", "true")


def _chain_on() -> bool:
    """Chain-engine kill-switch (GRAPHRAG_CASCADE_CHAIN), read at the answer.py quantify SEAM and threaded as the
    OMIT-WHEN-OFF `chain` kwarg down quantify()->_chain_legs (the _pace_leg_on idiom -- NEVER an os.environ read
    inside cascade.py, so the ENGINE is gated by the ARGUMENT and a mis-plumbed enable can never fire it on an
    unasked turn). DEFAULT-OFF, fail-closed: only a case-insensitive on/1/true enables it. When off, the kwarg is
    ABSENT and quantify() is byte-identical to today (injected quantify fakes with the older signature stay
    valid). Read PER CALL (never memoized) so the env-flip rollback is live -> no redeploy."""
    return os.environ.get("GRAPHRAG_CASCADE_CHAIN", "").strip().lower() in ("on", "1", "true")


def _transmission_on() -> bool:
    """HORIZONTAL transmission-chain kill-switch (GRAPHRAG_CASCADE_TRANSMISSION), read at the answer.py quantify
    SEAM and threaded as the OMIT-WHEN-OFF `transmission` kwarg down quantify()->_transmission_legs (the
    _chain_on idiom -- NEVER an os.environ read inside cascade.py, so the ENGINE is gated by the ARGUMENT and a
    mis-plumbed enable can never fire it on an unasked turn). DEFAULT-OFF, fail-closed: only a case-insensitive
    on/1/true enables it. When off the kwarg is ABSENT and quantify() is byte-identical to today (injected
    quantify fakes with the older signature stay valid). `GRAPHRAG_TRANSMISSION` -- the ratified plan's D6
    spelling -- is accepted as an ALIAS so either name flips the one switch. Read PER CALL (never memoized) so
    the env-flip rollback is live -> no redeploy."""
    return any(os.environ.get(k, "").strip().lower() in ("on", "1", "true")
               for k in ("GRAPHRAG_CASCADE_TRANSMISSION", "GRAPHRAG_TRANSMISSION"))


def _pattern_records_on() -> bool:
    """T2B pattern-records card kill-switch (GRAPHRAG_PATTERN_RECORDS), read at the answer.py _system() seam.
    When on, the reader-facing string gains the OBSERVATION-register '## Recorded history' [N]-rendering
    directive so the model CITES the injected ledger count (and states the F8 empty-ledger honesty) instead
    of minting a cross-day streak from the within-turn pace figure. DEFAULT-OFF, fail-closed: only a
    case-insensitive on/1/true enables it, so with the flag off _system() is BYTE-IDENTICAL to pre-feature.
    Read PER CALL (never memoized) so the env-flip rollback is live -> no redeploy (the _chain_on idiom)."""
    return os.environ.get("GRAPHRAG_PATTERN_RECORDS", "").strip().lower() in ("on", "1", "true")


def _outlook_on() -> bool:
    """W5 outlook kill-switch (GRAPHRAG_OUTLOOK), read at the answer.py seam and threaded DOWN as the
    `market_register` argument to reg.sanitize -- NEVER an os.environ read inside register.py, so a
    mis-plumbed enable can never relax the suggester chip guard or the numbers/news/live bodies. It is one
    of THREE legs: the planner's plan.answer_mode_outlook and intent.is_outlook_explicit(query) must ALSO
    hold (fail-CLOSED, W5.2). DEFAULT-OFF: with the flag off every sanitize call keeps market_register
    "fenced" and the system is byte-identical to pre-W5 -- the whole wave rolls back on ONE env var. Read
    PER CALL (never memoized) so the env-flip rollback is live -> no redeploy (the _chain_on idiom)."""
    return os.environ.get("GRAPHRAG_OUTLOOK", "").strip().lower() in ("on", "1", "true")


def _timeline_on() -> bool:
    """W4-D3 event-timeline kill-switch (GRAPHRAG_TIMELINE), read at the answer.py seam and threaded DOWN
    as the `episodes` argument to _system() -- never an os.environ read inside the persona builder.
    When on, the persona gains the reserved '## Episodes' enumeration directive (_SYSTEM_EPISODES), which
    is the PRODUCER half of eval's min_episode_lines / episode_magnitude_or_absence pins. DEFAULT-OFF,
    fail-closed: with the flag off _system() is BYTE-IDENTICAL to pre-W4-D3.
    Read PER CALL (never memoized) so the env-flip rollback is live -> no redeploy (the _chain_on idiom).

    SPELLING IS DELIBERATELY NARROWER THAN THE HOUSE on/1/true IDIOM, and this is load-bearing. The ENGINE
    gate is `os.environ.get("GRAPHRAG_TIMELINE", "off") != "on"` (timeline.episodes_for, timeline.py:140)
    -- an EXACT "on" match. If this helper accepted "1"/"true", then GRAPHRAG_TIMELINE=1 would ship the
    paragraph while episodes_for() still returned [], so the model would be told to render '## Episodes' on
    a turn carrying NO 'DATED EPISODES' line -- a confabulation surface born of a two-gate spelling
    mismatch, and precisely the +10-hallucination mode the layer was defaulted off for on 2026-07-04.
    The two gates must agree character for character; do not "harmonize" this with _chain_on.

    THIS FLAG IS NECESSARY AND NOT SUFFICIENT, and the earlier revision of this docstring was WRONG to
    imply otherwise (verifier blocker 2, 2026-07-31). Matching the spelling closes only the =1/=true case.
    THREE states leave the flag exactly "on" with ZERO episode lines in the prompt:
      (a) ARTIFACT FAIL-OPEN -- timeline._load() ends in a bare `except Exception: _CACHE = {}`
          (timeline.py:109-110), so a missing or unreadable timeline/episodes.json yields [] silently;
      (b) NO AS-OF -- episodes_for() returns [] when the turn has no anchor date (timeline.py:143-144);
      (c) ONE-HOP -- `tl.render_line` has exactly ONE call site (_l2_blocks), so the GRAPHRAG_PLANNER=onehop
          rollback body produces no episode line at all.
    The second gate is therefore MEASURED IN CODE at both seams: `_timeline_on() and _tl.LINE_PREFIX in vp`,
    read off the ASSEMBLED volatile prompt. A prompt sentence ("render it only when a line is present") is
    not a gate -- it is one paraphrase away from failing, which is the same reasoning that put the outlook
    derivation fence in register.py rather than in the persona."""
    return os.environ.get("GRAPHRAG_TIMELINE", "off") == "on"


def _episode_outcomes_on() -> bool:
    """OUTCOMES_JOIN J4 kill-switch (GRAPHRAG_EPISODE_OUTCOMES), read HERE at the quantify seam and
    threaded DOWN as the omit-when-off `episode_outcomes` kwarg -- never an os.environ read inside
    cascade.py (the pace/price_request/xc discipline). DEFAULT-OFF: with the flag off the kwarg is
    ABSENT, quantify performs no tape read, injects no [N] row and writes no trace key, so the turn is
    byte-identical -- which is exactly the measurement the plan's item 108 asks for and gets for free
    from this idiom rather than from a promise.

    IT IS A SECOND GATE, NOT A REPLACEMENT FOR THE FIRST. The leg prices the windows in
    `trace['episodes_injected']`, and that key exists only when GRAPHRAG_TIMELINE is exactly "on" and a
    node actually carried episodes -- so with the timeline off this flag alone renders nothing. Two
    independent flags is the point: it keeps the J4 rows out of an A/B whose only intended variable is
    GRAPHRAG_TIMELINE.
    Read PER CALL (never memoized) so the env-flip rollback is live -> no redeploy (the _chain_on idiom)."""
    return os.environ.get("GRAPHRAG_EPISODE_OUTCOMES", "").strip().lower() in ("on", "1", "true")


def _futures_newest_first_on() -> bool:
    """FUTURES_READPATH S1 canary (GRAPHRAG_FUTURES_NEWEST_FIRST), D-FR-10. THE ONE ENV SEAM for the series
    read-shape flip, cloned from _episode_outcomes_on and threaded DOWN as the omit-when-off
    `futures_newest_first` kwarg to numbers.query.build_sql / .run -- NEVER an os.environ read inside
    query.py, which carries zero flag surface today (it reads exactly LEVIATHAN_BUCKET and
    ATHENA_QUERY_TIMEOUT_S). The ENGINE is gated by the ARGUMENT, so a mis-plumbed enable cannot fire the
    flip on an unasked read, and the flag-off surface is byte-identical FROM THE IDIOM rather than from a
    promise: with the kwarg absent, build_sql emits the same ASC total order it emitted before the wave and
    run() performs no re-sort.

    WHAT IT FLIPS. The series branch of a card declaring contract_month_col (silver_futures_eod only,
    D-FR-2's futures-scoped ratification) compiles its ORDER BY as the exact reverse of the total order with
    an explicit NULLS LAST on every term, so `LIMIT 5000` keeps the NEWEST rows instead of the oldest; run()
    re-sorts back to ascending before any consumer sees a row. Today an unbounded corn_cbot settle series
    stops in 2011 and the answer narrates a fifteen-year-old price at today's as-of.

    IT IS ANSWER-CHANGING, WHICH IS WHY IT IS A FLAG. At desiredCount=1 there is no service-level canary; the
    env var IS the rollback, live on a flip with no redeploy (read PER CALL, never memoized -- the _chain_on
    idiom). DEFAULT-OFF, fail-closed: only a case-insensitive on/1/true enables it.

    THREADING STATUS, STATED RATHER THAN IMPLIED. The compiler half (query.py), this seam, AND the caller
    graph are landed. The bool is computed ONCE per turn at each lane's top and threaded down as a kwarg:

      * THIS FILE -> `cascade.quantify(**_fnf_kw)` at the cascade seam below, in the omit-when-off shape
        `_epo_kw`/`_cto_kw` use, and from there to the leg wave (_run_one -> fetch_window), the price
        pair, the vertical chain engine and the J4 tape reads (_tape_read);
      * orchestrator.py -> `agent.answer_numbers` on BOTH lanes (run_numbers_only and run_hybrid's worker
        thread), and from there to the executor's lookup, the W3.2 legacy-level rewrite and the ESR
        aggregate legs;
      * server.py's /v1/series imports this seam and passes it to Q.run directly -- it sits ABOVE answer,
        so there is nothing to thread it through.

    WHAT IS DELIBERATELY NOT THREADED, so the gaps are read as decisions. (a) numbers_parity.py:189 and
    cascade_census.py:190/:391/:396 compile with build_sql and execute the raw string themselves BY DESIGN,
    so if either is ever given the flag it must also call query.resort_rows_chronological on the rows, or it
    is measuring the un-re-sorted DESC surface. (b) THE CONSTANT-TABLE READS -- cascade's
    `_psd_component_rows` (a `table` KWARG since L2-5, defaulting to silver_psd and reachable for the
    long companion silver_psd_attributes too, still reached five deep through the RV2/transmission
    engines), cascade's `_cot_outcome_read` (gold_cot_outcomes), and silverleg's `_rows` (whose three
    callers pass silver_psd / silver_fred_fx / silver_noaa_oni as literals). Each of those reads only
    the cards its classified constants name (the PSD site's two live in _CONSTANT_TABLE_SITES) and no
    such card declares `contract_month_col`, so `_newest_first_applies` is structurally False there
    and a threaded flag could not move one byte of their SQL. All of it is pinned in
    test_futures_readpath_pins, so each omission stays MEASURED rather than assumed: the day one of those
    cards grows a delivery-month axis, the pin reds and this paragraph is what gets read.

    silverleg is the one worth naming explicitly, because it is the site an audit of "which Q.run calls
    were threaded" would flag first: it is the only serving Q.run outside agent/cascade/server, and it
    was NOT on the wave's mapped-sites list. It is a firing-leg helper, not a series reader.
    The flag is therefore LIVE in serving on a flip, and inert until one.

    (b) IS FLAG-SPECIFIC, AND D-AM-18 IS WHERE THAT STOPS BEING FREE. The structural argument above rests
    on `_newest_first_applies` keying on `contract_month_col`, which is true of THIS flag only. Under
    `_series_newest_first_on`'s estate-wide token those same three sites would move if the token reached
    them, so they are held out there as DECISIONS with their own bounds -- see that seam's gap paragraph
    and the site docstrings themselves, which now carry the reason each one is safe to leave."""
    return os.environ.get("GRAPHRAG_FUTURES_NEWEST_FIRST", "").strip().lower() in ("on", "1", "true")


_SERIES_NEWEST_FIRST_OFF = ("off", "0", "false", "no")
"""The ONLY spellings that roll the estate-wide newest-first read shape BACK to the pre-D-AM-18 ascending
compile. Deliberately several, and deliberately the inverse of the old enable list: after D-PQ FIX-1 the
DEFAULT is on, so the value that must never be missed is the DISABLE. A stray unrecognised value
(`GRAPHRAG_SERIES_NEWEST_FIRST=maybe`) therefore leaves the CORRECT ordering in place rather than silently
restoring the defect."""


def _series_newest_first_on() -> bool:
    """D-AM-18 (GRAPHRAG_SERIES_NEWEST_FIRST). THE SECOND ENV SEAM for the same read-shape flip, WIDENED to
    every series read instead of the futures cards `_futures_newest_first_on` scopes it to.

    THE DEFECT. D-FR-2 ratified S1 futures-scoped, so a non-futures series read -- PSD, CEPEA, pink_sheet,
    COT, NASA POWER, MPOB -- still compiles its ORDER BY ascending and `LIMIT 5000` keeps the OLDEST rows. On
    the long cards that is not a corner: a z-score or a percentile asked for "long history" windows against
    rows that stop years before the as-of, and nothing in the answer says the tail is missing (the
    truncation sentinel annotates the read, it does not re-aim it).

    D-PQ FIX-1: THE DEFAULT IS NOW ON, AND THE FLAG IS THE ROLLBACK. D-AM-18 shipped this seam OPT-IN, and
    the D-CW-4 wired probe then measured what opt-in costs on a lane nobody remembered to set the env on:
    row 3 served a Nov-2019 MPOB print as "the same month" (an ASC/oldest-kept read under a model-chosen
    small `limit`), and row 11 re-measured the 5000-cap oldest-kept read UNCHANGED. Meanwhile the model-facing
    tool schema (`agent.tool_schema`, the `limit` field, D-CW-1c) had already been written to PROMISE the
    newest end -- "the rows kept are the NEWEST ones in the window ... read newest-first for exactly that
    reason". A default-off flag made that promise FALSE on every non-futures card, which is worse than either
    end taken honestly: the model sizes its window against a contract the compiler does not keep.

    So the polarity is inverted rather than the flag deleted. The lever survives -- one env value still
    restores the byte-identical pre-wave compile with no redeploy -- but it is now spelled as a DISABLE
    (`_SERIES_NEWEST_FIRST_OFF`), and the value a forgotten env block produces (absent) is the correct one.
    `_futures_newest_first_on` is deliberately NOT inverted: it is nested inside this scope (everything the
    futures flag moves, this one moves too, and `_newest_first_scope` resolves the estate-wide token first),
    so inverting it would change nothing except which of two flags a rollback has to find.

    WHERE THE NEW DEFAULT LIVES, STATED SO NOBODY LOOKS FOR IT IN THE COMPILER. At the SEAM only.
    `query.build_sql` / `query.run` still default `futures_newest_first=False`, so the compiler's contract,
    its omit-when-off idiom and every pin in test_dam_series_order sections 1-4 are untouched: what changed
    is which value the SERVING lanes hand it. The consequence is exactly the reach paragraph below -- the
    threaded caller graph is newest-first now, the three unthreaded sites are not, and the raw-`build_sql`
    tools (`numbers_parity`, `cascade_census`) stay unflagged by design.

    WHAT IT DOES NOT REACH, STATED SO THE GAPS ARE DECISIONS. The token rides the caller graph D-FR-10
    threaded, so it reaches the cascade legs, the J4 tape, the numbers agent and /v1/series -- and NOT the
    three sites that wave left unthreaded because the futures scope could never move them: cascade's
    `_psd_component_rows` and `_cot_outcome_read`, and silverleg's `_rows`. Under this token they COULD
    move, so each now carries, in its own docstring, the bound that makes leaving it safe: the PSD
    component read is scoped to a single marketing year, `_cot_outcome_read` is one slug over a
    horizon-length date window, and silverleg's legs are capped per leg -- with `_su_ratio`'s
    country-less fallback named as the one that can actually bind. silverleg additionally memoizes
    behind a SHARED cache whose
    key carries no read-shape term, so threading it without re-keying that cache would let one turn read
    an entry computed under the other ordering. That re-key is its own change with its own gate.

    THE VALUE IS A SCOPE, NOT A SECOND KWARG. `_newest_first_scope` folds the two seams into the ONE token
    (`query.NEWEST_FIRST_ALL`) that already rides the `futures_newest_first` slot down every threaded
    frame, so this flag inherits the caller graph D-FR-10's wave landed and test_futures_readpath_pins
    section 7 pins -- rather than minting a parallel thread that would have to re-earn that proof frame by
    frame, and whose first missed frame would be indistinguishable from the flag being off.
    Read PER CALL (never memoized) so the env-flip rollback is live -> no redeploy (the _chain_on idiom)."""
    return os.environ.get("GRAPHRAG_SERIES_NEWEST_FIRST", "").strip().lower() not in _SERIES_NEWEST_FIRST_OFF


def _newest_first_scope(futures_on: bool, series_on: bool) -> bool | str:
    """Fold the two newest-first seams into the ONE scope token threaded down as `futures_newest_first`:
    False (off), True (D-FR-2 futures-scoped), or `query.NEWEST_FIRST_ALL` (D-AM-18 estate-wide).

    PURE -- it reads no env of its own. Both bools are read AT THE LANE and passed in, so each lane keeps
    exactly one read per turn per flag (a turn cannot disagree with itself) and the census test that every
    lane reaches `_futures_newest_first_on` BY NAME still measures what it was written to measure.

    The estate-wide token WINS over the futures bool rather than combining with it: the scopes are nested,
    not parallel -- everything the futures scope moves, the estate-wide scope moves too -- so with both
    flags on a futures card takes the same single flip, never a double-apply.

    The token is imported from the compiler that INTERPRETS it (lazily, the numbers-package import idiom
    this file uses for cascade/pgnumbers): one definition, so a rename cannot leave this seam emitting a
    string no scope guard recognizes."""
    from leviathan.graphrag.numbers.query import NEWEST_FIRST_ALL
    return NEWEST_FIRST_ALL if series_on else bool(futures_on)


def _cot_outcomes_on() -> bool:
    """OUTCOMES_JOIN J6 kill-switch (GRAPHRAG_COT_OUTCOMES), same seam, same omit-when-off idiom.

    The flag is the OUTERMOST of three gates and the weakest of them. Inside, `quantify` runs the leg
    only on a FENCED turn (D-OJ-17 option (a): the outcome ref is held out of outlook turns entirely,
    because under OUTLOOK register.py releases the flow fence by design and no phrasing rule inside a
    released fence is load-bearing), and the leg itself runs only where a positioning CONTEXT leg
    actually rendered. A flag cannot substitute for either; it only makes them reachable.
    Read PER CALL (never memoized) so the env-flip rollback is live -> no redeploy."""
    return os.environ.get("GRAPHRAG_COT_OUTCOMES", "").strip().lower() in ("on", "1", "true")


def _episode_scaffold_on() -> bool:
    """D-DT-1 kill-switch (GRAPHRAG_EPISODE_SCAFFOLD), cloned from `_episode_outcomes_on` -- THE ONE ENV
    SEAM for the render-side '## Episodes' scaffold. DEFAULT-OFF, fail-closed: only a case-insensitive
    on/1/true enables it, and with the flag off `_maybe_scaffold_episodes` returns an EMPTY trace-update
    dict before it reads anything, so no trace key is written, `structured` and `verifier` are untouched
    and the turn's ANSWER BODY is byte-identical to rev 75.

    THE BYTE-IDENTITY PROMISE IS SCOPED, deliberately (V.4 X2). D-DT-2's `fork_basis` is observational by
    design and is minted UNCONDITIONALLY on the same image, so the OFF arm of this flag's A/B carries one
    new TRACE key. The promise this flag makes is therefore over the ANSWER BODY (`answer` + `structured`
    + `verifier`), which is what a reader and every deterministic pin see; `trace` is exempt and the
    exemption is stated here rather than discovered mid-A/B. Nothing in `_CASCADE_EXPECT` reads
    `fork_basis` except the NEW `fork_licensed` key, which no cascade/pace row carries.

    Read PER CALL (never memoized) so the env-flip rollback is live -> no redeploy (the _chain_on idiom).
    That is what makes the A/B one variable on a FROZEN artifact rather than two deploys."""
    return os.environ.get("GRAPHRAG_EPISODE_SCAFFOLD", "").strip().lower() in ("on", "1", "true")


def _episodes_relevant(query: str | None) -> bool:
    """D-RC-11: is the '## Episodes' surface RELEVANT to this question's shape? ONE bool, resolved once
    per turn beside the _episodes_on seam and consumed by BOTH producers -- the persona mandate
    (_SYSTEM_EPISODES) and the render-side scaffold (_maybe_scaffold_episodes) -- because presence is
    decided in two INVERSE places and gating only one inverts the outcome (suppress only the scaffold
    and the persona still orders the model to write the section; suppress only the persona and the
    scaffold synthesizes it).

    FLAGLESS since D-AM stage 3 (the GRAPHRAG_EPISODE_RELEVANCE interim kill-switch is RETIRED --
    it existed only to stage D-RC-11 before response contracts shipped; with contracts live an
    ACTIVE contract's licenses_episodes subsumes this gate per turn at the _ep_rel seam, and this
    function is the sole authority ONLY on the unshaped/default lane). FAIL-OPEN by construction:
    True on a non-Latin query (the cue list is English; suppressing a section because the matcher
    cannot read the language is not a relevance judgment -- the 2026-08-05 Arabic probe keeps
    today's behaviour), else the deterministic intent.is_episodic_explicit cue match. The gate never
    strips a section the MODEL chose to author (D-RC-9: no post-synthesis deletion) -- it removes
    the MANDATE and the SYNTHESIS, never model freedom."""
    q = query or ""
    from leviathan.graphrag.verify import _non_latin
    if _non_latin(q):
        return True
    return _it.is_episodic_explicit(q)


def _response_contracts_enabled() -> frozenset:
    """D-RC-7: the serving flag GRAPHRAG_RESPONSE_CONTRACT, read PER CALL. Value grammar:
    absent/''/'off' -> frozenset() (OFF, the default); 'on'/'1'/'true' -> ALL contract names;
    anything else -> a comma-separated ALLOWLIST of contract names (unknown names ignored -- linted
    by config_check, never fatal here). The allowlist IS the staged-flip mechanism: per-contract
    flip and per-contract rollback on one env var, no redeploy. A selected contract not in the set
    resolves to None at the seam = `default` = zero rewrite, zero directive (fail-open)."""
    v = os.environ.get("GRAPHRAG_RESPONSE_CONTRACT", "").strip().lower()
    if not v or v == "off":
        return frozenset()
    if v in ("on", "1", "true"):
        return _rc.valid_names()
    return frozenset(x.strip() for x in v.split(",") if x.strip()) & _rc.valid_names()


def _scaffold_cap_kwargs(mode_knobs: dict | None) -> dict:
    """The episode-scaffold cap overrides a honored mode carries, in the omit-when-absent idiom: {}
    on every standard/dark turn, so the scaffold call stays byte-identical and any injected fake with
    the pre-D-AM signature keeps working."""
    kn = mode_knobs or {}
    kw = {}
    if kn.get("scaffold_max_bullets") is not None:
        kw["max_bullets"] = kn["scaffold_max_bullets"]
    if kn.get("scaffold_max_absence") is not None:
        kw["max_absence"] = kn["scaffold_max_absence"]
    return kw


def _mode_budget(rc_active: str | None, mode_knobs: dict | None) -> str | None:
    """D-AM-10 length lever: the ACTIVE response contract's word range scaled by the honored mode's
    factor. None -- meaning "leave the budget exactly as it is" -- whenever no contract is active, no
    mode is honored, or the range is unparseable. The contract must be ACTIVE because the range being
    scaled is the CONTRACT's: the default persona's own budget is a pinned needle of _SYSTEM_MENTOR
    and is never mode-varied (scaling it would move the length of every turn, contracts on or off,
    which is a different decision than this one). Both modules are leaves; the arithmetic lives in
    reasoning_modes and the substitution in response_contracts, so neither imports the other."""
    scale = (mode_knobs or {}).get("budget_scale")
    if not rc_active or not scale:
        return None
    c = _rc.CONTRACTS.get(rc_active)
    return _rm.scale_budget(c.budget, scale) if c else None


# D-DR-1: the PER-CALL override channel for the census gate, and the ONLY one.
#
# WHY IT EXISTS. A dossier runs its width-hungry sub-queries with the composition mandates ACTIVE and
# its quick sub-queries with them OFF (the D-CC-3 R1 consequence: mandates are width-hungry, and at
# quick's 12-row evidence they mandate enumeration the evidence cannot back -- strips/handle 0.1765 vs
# 0.1073). That is a PER-CALL decision, so it cannot be an os.environ flip: the environment is
# process-global and a concurrent desk turn on the same task would silently inherit the dossier's
# setting. WHY A ContextVar: it is thread-scoped by construction (a new thread starts from an empty
# context, so nothing leaks to the SSE/answer threads serving other users), and the census is computed
# on the SAME thread that calls the synthesis seam -- so setting it around one respond() call reaches
# exactly that call and nothing else. None = "no override" = the env flag decides = byte-identical to
# the pre-D-DR module on every non-dossier path.
_CENSUS_OVERRIDE: contextvars.ContextVar = contextvars.ContextVar(
    "graphrag_composition_census_override", default=None)


@contextlib.contextmanager
def composition_census_override(on: bool | None):
    """Force `_composition_census_on()` to `on` for the duration of the block, on THIS thread only.
    `None` restores flag-decides. Token-reset in a finally, so an exception inside the block can never
    leave a thread pinned."""
    token = _CENSUS_OVERRIDE.set(None if on is None else bool(on))
    try:
        yield
    finally:
        _CENSUS_OVERRIDE.reset(token)


_HANDLE_MENU_OVERRIDE: contextvars.ContextVar = contextvars.ContextVar(
    "graphrag_handle_menu_override", default=None)


@contextlib.contextmanager
def handle_menu_override(on: bool | None):
    """Force `_handle_menu_on()` to `on` for the duration of the block, on THIS thread only. `None`
    restores the default (ON). Token-reset in a finally, so an exception inside the block can never
    leave a thread pinned. The `composition_census_override` idiom, verbatim, and for the same reason:
    the decision is PER CALL, so it cannot be an os.environ flip -- the environment is process-global
    and a concurrent desk turn would silently inherit the dossier's setting.

    D-HP-16 IS WHY IT EXISTS. The dossier's 5-12 sub-answers are ordinary quick/deep turns through
    `orchestrator.respond` (dossier.py:4, :932), so every prompt change D-HP-1/D-HP-2 make at H0 is a
    DOSSIER-INPUT CHANGE ON DAY ONE -- while the dossier's OUTPUT-side handle plumbing (`remap_body`
    through the grouped-blind `dossier._HANDLE_RX`) is not fixed until D-HP-28, after G1+G2. The plan
    already gates the GRAMMAR at this boundary (`run_subquery` pins the control preset explicitly,
    never `deep_hp`/`quick_hp`); the MENU is the same class of input change and rides the same lever."""
    token = _HANDLE_MENU_OVERRIDE.set(None if on is None else bool(on))
    try:
        yield
    finally:
        _HANDLE_MENU_OVERRIDE.reset(token)


def _handle_menu_on() -> bool:
    """Whether THIS turn renders the D-HP-2 numbered receipt menu (and the range-form ledger clause).

    DEFAULT ON -- H0's menu is the wave's instrument and every desk lane gets it. It is a thread-scoped
    OVERRIDE, not an env flag: R9's one-way-kill law owns `GRAPHRAG_HANDLE_PROSE` (the GRAMMAR), and a
    second env knob for the MENU would be a second control surface for one wave. The only caller that
    turns it off is `dossier.run_subquery`, and it does so per sub-call."""
    ov = _HANDLE_MENU_OVERRIDE.get()
    return True if ov is None else bool(ov)


# The one-way KILL spellings, and there is no "on" spelling by design (R9).
# H1 FIX Z12: THIS IS A VIEW, NOT A SECOND COPY. The set was retyped here and held in agreement with the
# leaf's `HANDLE_PROSE_KILL_VALUES` by a drift pin -- which is a test standing in for a definition. R9
# made the leaf the ONE producer of the spellings, so the tuple is now DERIVED from it and the pin becomes
# redundant rather than load-bearing. The name survives because two suites read it by name.
_HANDLE_PROSE_KILL = tuple(sorted(_rm.HANDLE_PROSE_KILL_VALUES))


def _handle_prose_on(mode_knobs: dict | None) -> bool:
    """D-HP-8/R9 -- THE TREATMENT BUNDLE'S ONE KNOB, RESOLVED ONCE PER TURN AT THE SERVING BODY.

    B8's BUNDLE RULE IS WHY THERE IS EXACTLY ONE OF THESE: the prompt contract (D-HP-7), the renderer
    (D-HP-10/11) and the digit-lint's CHARGE (D-HP-12) move TOGETHER. Two knobs would re-create the
    GRAPHRAG_VERIFY_ALLNUM hazard PHASE9_B deliberately refused -- a strip rule gated by a flag that can
    differ across arms means the arm measures its own instrument (section 2's standing law).

    THE ENABLING LEVER IS A PRESET, NEVER AN ENV. `mode_knobs` is the reasoning mode's RESOLVED knob dict
    (`deep_hp` / `quick_hp` / `esc_hp` / `esc_r_hp`, all in `DARK_NAMES`), threaded down as ONE argument
    exactly as `provenance_prompt` / `order_policy` / `fetch_k` already are. The decisive reason it cannot
    be a process env is the ESCALATION SEAM: orchestrator.py:2138-2139 swaps the walk/ground knob dict
    WHOLE ("never a merge"), so an env-only design would leave the prompt contract on while the escalated
    turn's knobs said nothing -- the treatment half-reverting MID-TURN on two of the four judged gates.

    `GRAPHRAG_HANDLE_PROSE` SURVIVES AS A ONE-WAY KILL AND NOTHING ELSE. It can force the bundle OFF from
    an incident shell with no taskdef registration; it CANNOT turn it on, so it cannot drift a gate arm
    and it cannot stamp an arm nothing ran (the H0 fix to `eval._handle_prose_arm`, from the other side).

    THE VERIFIER GATE IS NOT READ HERE, and that is deliberate: this answers "is the treatment selected",
    the call sites answer "may the renderer run". Section 2's MUTUAL-EXCLUSION law (handle-prose is
    IGNORED whenever `GRAPHRAG_VERIFY=off`) is enforced where the passes live -- inside
    `if verifier.get("enabled"):` -- and at the persona seam, which must not emit a contract the renderer
    cannot honour.

    H1 FIX Z12: the RESOLUTION is the leaf's (`_rm.handle_prose_on`) and this function owns only what the
    leaf deliberately does not -- reading the environment. One producer, one set of kill spellings."""
    return _rm.handle_prose_on(mode_knobs, os.environ.get("GRAPHRAG_HANDLE_PROSE"))


def _handle_prose_active(mode_knobs: dict | None) -> bool:
    """`_handle_prose_on` AND the two ROLLBACK LANES that make the contract unhonourable -- the ONE
    expression both serving bodies resolve, and the one the persona, the tool schema and the verifier's
    `handle_prose` argument are all threaded from. "Is the treatment selected" is `_handle_prose_on`;
    THIS answers "may it actually run this turn", and the difference is the whole of section 2's
    MUTUAL-EXCLUSION law.

    (1) `GRAPHRAG_VERIFY=off` (section 2, folded from review G9). Every handle pass runs inside
        `if verifier.get("enabled"):`, and this env is the DOCUMENTED rollback for the entire
        citation-truth chain. Under handle-prose that rollback would become a LIVE DEFECT rather than a
        safe fallback: the model writes no digits, nothing splices values, nothing prunes unresolvable
        handles, and `render()` falls back to the model's own `**Sources**` ledger -- number-free,
        handle-littered prose reaching the reader. So the PROMPT CONTRACT IS NOT EMITTED on a turn where
        the renderer cannot run. The spelling is verify.py's own, and the conformance suite asserts the
        two agree rather than trusting that they do.
    (2) `GRAPHRAG_MENTOR_VOICE=off` returns `_SYSTEM_LEGACY` from `_system` -- a persona that carries
        neither the handle menu's vocabulary nor the four spans this contract supersedes. The leg would
        be appended to a document it does not describe, and the same half-on shape follows. Same rule,
        same reason: no contract the renderer's other half cannot honour.

    Both are READ PER CALL. A once-at-import read would make either rollback a silent no-op until a
    redeploy, which is the failure `_system`'s own docstring records.

    H1 FIX Z9 -- THE VERDICT IS THE LEAF'S, THE ENVIRONMENT IS THIS FUNCTION'S. The two lanes used to live
    only here, so `eval._handle_prose_arm` (which cannot see this module's env reads) stamped "on" for a
    turn on which the treatment provably did not run -- the H0 arm-stamp defect, reopened by the second
    lane. The three env values are threaded INTO `_rm.handle_prose_active`, which both the serving seam and
    the artifact stamp now read, so a lane added on one side cannot exist on the other."""
    return _rm.handle_prose_active(
        mode_knobs, os.environ.get("GRAPHRAG_HANDLE_PROSE"),
        verify_env=os.environ.get("GRAPHRAG_VERIFY", "on"),            # verify.py:890's exact spelling
        mentor_env=os.environ.get("GRAPHRAG_MENTOR_VOICE", "on"))      # _system's exact spelling


def _composition_census_on() -> bool:
    """D-CC-1 kill-switch (GRAPHRAG_COMPOSITION_CENSUS), the _episode_scaffold_on idiom: DEFAULT-OFF,
    house on/1/true spelling, read PER CALL. Off -> the seam threads `census=None` -> response_contracts
    is byte-identical to its pre-D-CC self on every path, so ONE image serves both D-CC-3 arms and the
    contract-alone control on an env flip with no redeploy (the D-RC Phase C staged-flip discipline).
    It gates the composition mandates ONLY: which contract was selected, and the base contract shaping
    that ships today, are unaffected in both positions.

    D-DR-1: a thread-scoped override (`composition_census_override`) WINS over the env flag when set --
    it is how a dossier turns the mandates on for one sub-call without moving the process environment."""
    ov = _CENSUS_OVERRIDE.get()
    if ov is not None:
        return bool(ov)
    return os.environ.get("GRAPHRAG_COMPOSITION_CENSUS", "").strip().lower() in ("on", "1", "true")


def _n_episode_windows(trace: dict | None) -> int:
    """Dated episode WINDOWS injected into this turn's prompt, counted off `trace['episodes_injected']`
    as `_l2_blocks` stamped it. ONE producer for two consumers (fork_basis' L2/L4 leg and the D-CC-1
    episode-coverage census): the mandate that orders N windows enumerated and the flag that licenses
    the fork over them must never be able to disagree about N. Windows, not LINES -- one injected line
    carries every window of its node, and the enumeration unit the model is judged on is the window."""
    return sum(len((rec or {}).get("spans") or [])
               for rec in ((trace or {}).get("episodes_injected") or []))


# The census entity roster is CAPPED before it is stamped or rendered: an ESR-class number call can
# return hundreds of destinations, and an unbounded roster is both an artifact hazard and prompt bloat.
# `n_entities` carries the TRUE distinct count regardless, so every stated count is honest and only the
# spelled-out names are truncated (response_contracts truncates again, harder, at MAX_NAMED_ENTITIES).
_CENSUS_ENTITY_CAP = 40


def _composition_census(*, contracts: list | None, number_calls: list | None,
                        trace: dict | None, n_evidence: int) -> dict:
    """D-CC-1: what this turn ACTUALLY HOLDS, counted deterministically, for the composition mandates.

    ZERO LLM, ZERO new retrieval, and no new engine call: every field is a read of a structure that
    already exists at the contract-apply seam. It inherits the fork_basis CIRCULARITY FENCE by
    position -- both serving bodies compute it BEFORE the model call, where no answer prose exists to
    read -- so a mandate can never be derived from the answer it is shaping.

      entities          -- the distinct origins/countries the numbers agent's rows and query scopes
                           name, then the RENDERED contract ids (what the prompt actually carried a
                           block for -- the caller supplies the set; see each seam). Countries first
                           and sorted, contracts in caller order: deterministic, so two identical
                           turns produce identical prompt bytes (the prompt-cache discipline, which a
                           set-iteration order would break). The two KINDS are deliberately
                           one list -- the mandate asks the model to cover the members of the asked-for
                           list and to drop a non-member silently, which is the only honest way to
                           handle a roster that spans both kinds without an LLM deciding which is which.
      n_entities        -- the TRUE distinct count, pre-cap.
      n_episode_windows -- _n_episode_windows, above.
      n_evidence        -- the post-cap evidence count already in scope at the seam (planner.ground
                           dedups and caps before this point; the source_key de-dup that runs AFTER the
                           model call is a rendering concern and is deliberately not what the model is
                           told it holds)."""
    countries, seen = set(), set()
    for call in (number_calls or []):
        if not isinstance(call, dict):
            continue
        q = call.get("query") or {}
        for v in [q.get("country") if isinstance(q, dict) else None] + \
                 [r.get("country") for r in (call.get("rows") or []) if isinstance(r, dict)]:
            s = str(v).strip() if v is not None else ""
            if s:
                countries.add(s)
    ents = []
    for e in sorted(countries) + [str(c) for c in (contracts or [])]:
        if e and e not in seen:
            seen.add(e)
            ents.append(e)
    return {"entities": tuple(ents[:_CENSUS_ENTITY_CAP]), "n_entities": len(ents),
            "n_episode_windows": _n_episode_windows(trace), "n_evidence": int(n_evidence or 0)}


def _tldr_coherence_on() -> bool:
    """D-RC-12 kill-switch (GRAPHRAG_TLDR_COHERENCE), the _episode_scaffold_on idiom: DEFAULT-OFF,
    house on/1/true spelling, read PER CALL. Gates an OBSERVATIONAL trace stamp only -- no strip, no
    rewrite, zero delta to checked/stripped -- so the strip rate stays comparable across any A/B."""
    return os.environ.get("GRAPHRAG_TLDR_COHERENCE", "").strip().lower() in ("on", "1", "true")


def _direction_basis(graph, contracts: list[str] | None) -> dict:
    """D-RC-12: a DETERMINISTIC net-direction read off the routed contracts' driver signs -- the
    _driver_conflict read, counted instead of bucketed. Pure graph read, zero LLM, computable before
    one token of prose exists (the fork_basis circularity discipline: it structurally CANNOT see the
    answer). HONESTLY WEAK, stated: this reads the model's PRIOR (which way the graph's drivers
    lean), never the OBSERVED state -- the Malaysia probe's contradiction turned on observed rows
    (elevated stocks, lagging exports) resolving one edge, which a sign count cannot see. It exists
    to make the tldr-vs-body divergence class VISIBLE and measurable, not to adjudicate it; the
    remedy is a v2 decision taken from the measured disagreement rate."""
    n_plus = n_minus = 0
    for cid in (contracts or []):
        c = ((getattr(graph, "contracts", None) or {}) or {}).get(cid)
        if c is None:
            continue
        for d in c.drivers:
            if d.sign == "+":
                n_plus += 1
            elif d.sign == "-":
                n_minus += 1
    net = "two_sided" if (n_plus and n_minus) else "higher" if n_plus else "lower" if n_minus else "none"
    return {"n_plus": n_plus, "n_minus": n_minus, "net": net}


# The CLOSED direction lexicon the prompts mandate (banned: bullish/bearish, except the OUTLOOK lane
# re-permits them -- register.py sanitize). Classifying the tldr FIELD against this closed vocabulary
# is deterministic; classifying free prose would not be.
_DIR_HIGHER = re.compile(r"points?\s+toward\s+higher\s+prices|price[-\s]supportive|\bbullish\b", re.I)
_DIR_LOWER = re.compile(r"points?\s+toward\s+lower\s+prices|price[-\s]pressuring|\bbearish\b", re.I)


def _tldr_direction_trace(structured: dict | None, graph, contracts: list[str] | None) -> dict:
    """D-RC-12: the post-verify reconcile. Reads structured['tldr'] -- a FIELD, never the assembled
    body (the item-2 law: no structure re-discovery on assembled prose) -- classifies its direction
    against the closed lexicon, and compares to the pre-model _direction_basis. Returns the trace
    update ({} when the flag is off: no key, no read, byte-identical trace). `agree` is False ONLY
    on a hard sign clash (basis says higher, tldr says lower, or the reverse); a two_sided/none
    basis and a mixed/none tldr are compatible by construction."""
    if not _tldr_coherence_on():
        return {}
    tldr = str((structured or {}).get("tldr") or "")
    hi, lo = bool(_DIR_HIGHER.search(tldr)), bool(_DIR_LOWER.search(tldr))
    read = "mixed" if (hi and lo) else "higher" if hi else "lower" if lo else "none"
    basis = _direction_basis(graph, contracts)
    clash = {basis["net"], read} == {"higher", "lower"}
    return {"tldr_direction": {"basis": basis["net"], "tldr": read, "agree": not clash}}


def _recency_stamp_on() -> bool:
    """D-RC-13 kill-switch (GRAPHRAG_RECENCY_STAMP), the same idiom: DEFAULT-OFF, house spelling,
    per-call read. Gates the prompt-side additions ONLY (the GROUNDING-LEDGER record-edge sentence
    and the _SYSTEM_RECENCY dating directive); the trace stamp `record_through` is observational and
    unconditional (the fork_basis scoped-promise precedent: the flag's byte-identity promise covers
    the ANSWER BODY; trace is exempt and the exemption is stated here, not discovered mid-A/B)."""
    return os.environ.get("GRAPHRAG_RECENCY_STAMP", "").strip().lower() in ("on", "1", "true")


def _record_through(evidence: list | None) -> str | None:
    """D-RC-13: the newest USABLE reported date across this turn's evidence -- the record's edge.
    Reported dates only, deliberately: observed number rows carry their own knowledge-date axis and
    the turn's as-of is a third axis; conflating the three is the mapped landmine, so this stamp
    names exactly one of them and the ledger sentence says which."""
    dates = [d for d in (_usable_date((h or {}).get("date")) for h in (evidence or []) if isinstance(h, dict)) if d]
    return max(dates) if dates else None


def _recency_ledger_suffix(record_through: str | None) -> str:
    """The per-turn VOLATILE record-edge sentence (flag-gated; '' when off or dateless -- the caller
    concatenates unconditionally so the seam stays one line). Rides the GROUNDING LEDGER, never the
    cached stable prefix."""
    if not _recency_stamp_on() or not record_through:
        return ""
    return (f" The dated evidence record for this question runs through {record_through} (reported "
            f"dates; observed [N] number rows carry their own knowledge dates; the as-of date is this "
            f"question's 'today').")


def _episodes_on(volatile_prompt: str | None) -> bool:
    """THE W4-D3 SEAM GATE, one spelling, used by BOTH serving bodies (_answer_l2 and the one-hop legacy
    body). The '## Episodes' persona paragraph ships iff BOTH legs hold:

      leg 1  the kill-switch  -- _timeline_on(), exact "on", character-for-character with timeline.py:140;
      leg 2  the EVIDENCE     -- the assembled VOLATILE prompt actually carries an injected episode line.

    Leg 2 is the one the first revision was missing, and it is not redundant: the flag can be exactly "on"
    with zero lines injected whenever the artifact fails to load (timeline._load fails OPEN to {}), the
    turn has no as-of, the walk grounded no node with dated props, or the planner is one-hop (which has no
    episode producer at all). In each of those states a flag-only gate hands the model a paragraph
    demanding a section it has no episodes for -- and in an A/B that state is invisible in the OFF arm, so
    it yields a FALSE reading rather than a noisy one.

    It reads the VOLATILE prompt, never sg.nodes, because the volatile prompt is what the model is
    actually sent: it stays correct if _l2_blocks changes which nodes it renders, and it cannot be fooled
    by a node whose episodes were populated but whose line was not emitted. tl.LINE_PREFIX is the shared
    constant render_line itself builds from, so producer and gate cannot drift apart."""
    return _timeline_on() and _tl.LINE_PREFIX in (volatile_prompt or "")


def _cascade_walk_block_on(volatile_prompt: str | None) -> bool:
    """THE WALK'S SEAM GATE -- `_episodes_on` verbatim in shape (charter STEP 8, built after the
    sitting-3 arm measured why it matters): the CONSEQUENCE MANDATE ships iff BOTH legs hold --
    leg 1 the kill-switch (`_cascade_walk_on`), leg 2 the EVIDENCE: the assembled VOLATILE prompt
    actually carries a walk block (its ROW-5 marker, `cascade.CW_MARKER_PREFIX`, the shared constant
    the producer builds from). MEASURED REASON (arm 2026-09-02, 3 walk-fired rows): under the
    conditional LICENSE alone the writer transcribed the walk on 1 of 3 -- a license is optional
    by construction; a mandate that ships only when the block exists is the W4-D3 shape that made
    the episodes section real without the +10-hallucination mode on walk-less turns."""
    from leviathan.graphrag.numbers import cascade as _cq   # lazy: answer imports cascade at the seam
    return _cascade_walk_on() and _cq.CW_MARKER_PREFIX in (volatile_prompt or "")


def _cascade_context_block_on(volatile_prompt: str | None) -> bool:
    """THE RIDER'S SEAM GATE -- `_cascade_walk_block_on` in shape, keyed on ROW-1C's OWN ROW SHAPE
    (`cascade.CW_CONTEXT_LINE_RX`: a line START of '- [N<digits>' followed by the one minted class
    token -- refute M2: the bare ten-character token is something a retrieved numbered heading
    (a bracketed index followed by 'CONTEXT AND BACKGROUND') can carry into the volatile prompt,
    and the mandate must never ship on a turn with no context row -- so this docstring does not
    spell the token either). The mandate ships iff the rider flag, the WALK BLOCK GATE and an
    actually-rendered context row all hold. The pair is atomic at the producer, so the row's presence
    proves ROW-2C is there too. REVIEW F3 (2026-09-02): the walk's own marker is REQUIRED beside the
    row shape (`_cascade_walk_block_on`, which carries the walk flag) -- evidence text is rendered
    raw with its newlines into the volatile prompt, so a retrieved chunk carrying the row shape at a
    line start could otherwise arm this mandate on a turn with no walk block at all; a context row
    cannot exist outside a walk block, so the conjunction is strictly tighter and costs nothing."""
    from leviathan.graphrag.numbers import cascade as _cq
    return (_cascade_context_on() and _cascade_walk_block_on(volatile_prompt)
            and _cq.CW_CONTEXT_LINE_RX.search(volatile_prompt or "") is not None)


def _cascade_deep_block_on(volatile_prompt: str | None) -> bool:
    """V2-5's SEAM GATE -- the V2-1 row-shape-gate idiom, fifth application, keyed on the marker's
    OWN MINTED LITERAL (`cascade.CW_THIRD_ORDER_MARKER`, built from CW_MARKER_PREFIX in the producer's
    own module) rather than a bare token, so a walk-less or first/second-order turn never sees a
    demand it cannot fill and the gate's string cannot drift from the producer's. The deep mandate
    ships iff the deep flag, the WALK BLOCK GATE and a THIRD-ORDER block all hold."""
    from leviathan.graphrag.numbers import cascade as _cq
    return (_cascade_deep_on() and _cascade_walk_block_on(volatile_prompt)
            and _cq.CW_THIRD_ORDER_MARKER in (volatile_prompt or ""))


# W5-D5: the '## Outlook' RESERVED HEADING -- injected-only, exactly the '## Cross-commodity' /
# '## Complex-wide move' / '## Recorded history' shape. Appended to the persona ONLY on a turn where all
# three outlook legs held, so with the flag off _system() is BYTE-IDENTICAL to pre-W5.
#
# The load-bearing half is the DERIVATION GATE (W5.0). A price level may be stated only when the arithmetic
# that produces it is shown and every input is cited; a bare number is a refusal. That is enforced in CODE
# (register.unbacked_levels strips an uncited level sentence, register.exec_leaks fences A2 unconditionally)
# -- this paragraph exists so the model produces the SHAPE the code permits, not so the model polices itself.
# A prompt-only fence is one paraphrase away from failing.
_SYSTEM_OUTLOOK = (
    "\nOUTLOOK MODE. This turn EXPLICITLY asked where prices go from here, so render a dedicated "
    "'## Outlook' section as a BALANCE OF RISKS -- never a single-point prediction. Render '## Outlook' "
    "ONLY on a turn that asked for it; never volunteer a forward price view from prose. Structure it as "
    "legs, each with its own citation:\n"
    "- which regimes are FIRING and which way they lean, named in plain words and cited;\n"
    "- the BUFFER: where the balance sheet sits versus its own history, with the [N] handle;\n"
    "- POSITIONING from the managed-money record, with its [N] handle, as HISTORICAL CONTEXT;\n"
    "- the HISTORICAL EPISODES from similar states, enumerated with dates and cited;\n"
    "- WHAT WOULD FLIP EACH LEG -- the observable that would reverse it. A leg with no falsifier is not a "
    "risk leg, it is an opinion; state the falsifier or drop the leg.\n"
    "A DERIVED PRICE RANGE IS PERMITTED, and ONLY under this discipline: show the arithmetic and cite every "
    "input. The shape is spot -> per-episode moves -> implied levels -> median, with the DISAGREEMENT NAMED. "
    "For example: 'Spot 227.25 EUR/t (Sep-26 settle) [N1]. Three comparable episodes from a similar buffer "
    "and ENSO state moved +18% / +7% / -3% over 90 days [E2] -> 268 / 243 / 220; median 243. The -3% case is "
    "2010, where the export ban reversed inside the window.' Every number that is an INPUT (the spot, each "
    "episode move) carries its [N] or [E] handle; the OUTPUTS you compute may be uncited because they are "
    "arithmetic on cited inputs, shown in the same section. A LEVEL WITHOUT ITS DERIVATION IS A REFUSAL: if "
    "you cannot show the spot, the episode moves and the arithmetic, DO NOT STATE A NUMBER -- say plainly "
    "that the record does not support a level and give the direction and the mechanism instead.\n"
    "AN OBSERVED LEVEL IS A DIFFERENT SHAPE FROM A DERIVED ONE. It needs no arithmetic at all -- only its "
    "OWN HANDLE, IN THE SAME SENTENCE AS THE NUMBER. Write 'the World Bank pink-sheet CPO reference price "
    "is 1,105 USD/mt [N3]'. Do NOT write 'the CPO price is 1,105 USD/mt, 0.22 sigma above its 5-year mean' "
    "and disclose [N3] in a later sentence, a closing scope note, a bullet further down or the sources "
    "ledger: each sentence is read ALONE, so a handle anywhere else in the note does not reach it. A "
    "sentence ends at a full stop, a question mark or a SEMICOLON, and NEVER at a line break -- so every "
    "bullet, every parenthetical aside and every clause after a semicolon that states a level carries its "
    "own handle inside it, and RESTATING a level (under '## The record', in a summary bullet, in the tl;dr) "
    "is stating it again and needs the handle again. This binds the buffer leg, the positioning leg and any "
    "'where the level sits versus its own history' remark.\n"
    "PUT EACH HANDLE IN ITS OWN BRACKETS -- '[N3] [N4]', or '[N3], [N4]', NEVER '[N3, N4]'. A comma-joined "
    "list inside one bracket is not a handle: the sentence reads as UNCITED and every number in it is "
    "refused, however many rows you meant to name.\n"
    "KEEP DERIVATION WORDS OUT OF A SENTENCE THAT ONLY QUOTES A ROW. The arrow '->' and the words "
    "'implies', 'implied', 'implying', 'works out to', 'gives', 'median', 'midpoint' and 'target' mark a "
    "sentence as COMPUTED OUTPUT, which no single handle can back -- an observed row quoted alongside one "
    "of them is read as arithmetic and refused DESPITE its handle. Quote the observed rows plainly, each in "
    "its own sentence, and put the arithmetic in sentences of its own.\n"
    "A LEVEL WITH NEITHER ITS OWN IN-SENTENCE HANDLE NOR A SHOWN DERIVATION IS A REFUSAL, not a rounding "
    "error. The honest move is to describe it QUALITATIVELY -- 'modestly above its five-year average' -- or "
    "to say the record carries no citable level for it and give the direction and the mechanism instead. "
    "Never carry "
    "a bare level into the tl;dr: either restate it with its derivation or cite the handle it rests on. "
    "Never present a range as a forecast of what WILL happen -- it is what comparable episodes DID, applied "
    "to today's level, and you must say so.\n"
    "WHAT THIS TOOL WILL NOT DO, on an outlook turn as on every other. It has no position, no sizing, no "
    "risk model and no account, so an execution instruction is unbacked BY CONSTRUCTION and is refused: no "
    "entry or exit levels, no stops, no take-profit, no position sizing, no risk/reward framing, no 'go "
    "long/short', no 'is this a buy', no 'accumulate here'. If the user asks for one, say plainly that this "
    "is a fundamental research tool with no position and no risk model, then answer the FUNDAMENTAL question "
    "underneath it -- the balance of risks and what would flip it. Fundamental relative value (which balance "
    "sheet is tighter, and why) is in scope; a trade instruction is not.")


# W4-D3: the '## Episodes' RESERVED HEADING -- injected-only, exactly the '## Cross-commodity' /
# '## Complex-wide move' / '## Recorded history' shape. Appended to the persona ONLY on a turn that BOTH
# has GRAPHRAG_TIMELINE on AND actually carries an injected 'DATED EPISODES' line (see the gate below), so
# with the flag off _system() is BYTE-IDENTICAL to pre-W4-D3.
#
# WHY IT EXISTS. eval's two W4 deck pins (min_episode_lines, episode_magnitude_or_absence) both read a
# rendered '## Episodes' section via eval._episode_section / _episode_lines. NOTHING in the codebase ever
# rendered one -- _episode_lines() returned [] on every turn, so both pins were red BY CONSTRUCTION on
# every row that pinned them. This paragraph is the missing PRODUCER half; the consumer needed no change.
#
# GATED ON TWO CONDITIONS, BOTH IN CODE, BOTH AT THE SEAM (revised 2026-07-31, verifier blocker 2):
#     _episodes_on(vp)  ==  _timeline_on() and _tl.LINE_PREFIX in vp
# i.e. the kill-switch AND an actual 'DATED EPISODES' line in the assembled volatile prompt. The earlier
# revision gated on the FLAG ALONE and justified it as "the injected-only clause forbids the section" --
# that clause is PROSE, and the flag can be exactly "on" with zero lines injected in at least three
# states (dead artifact, no as-of, one-hop planner; see _timeline_on's docstring). In each of those the
# flag-only gate hands the model a paragraph demanding a section it has no episodes for, which is the
# confabulation mode this layer was defaulted off for -- and in an A/B it is invisible in the OFF arm, so
# it produces a FALSE result rather than a noisy one. Correctness beats the cache here.
# COST: the paragraph is appended LAST (after mentor/cascade/pattern-records), so the cached prefix -- the
# stable head of the system string plus the stable graph block -- is byte-identical either way; only the
# tail varies per turn, exactly as _SYSTEM_OUTLOOK already does.
#
# THE TWO-SLOT BULLET, and why NEITHER slot is optional (both facts read from eval.py, not remembered):
#   SLOT 1, BACKING. eval._line_backed (eval.py:862-867) accepts a line when it (a) carries a _NO_CITABLE
#     phrase, (b) names a year some CITED evidence item is dated in, or (c) carries a cited citation's
#     handle. _NO_PRICE_RECORD IS NOT IN _line_backed -- a line whose only marker is "no price record"
#     is UNBACKED and reds min_episode_lines. And _cited_evidence (eval.py:210-222) filters
#     kind == "evidence", so an [N] handle NEVER backs a line either. Hence slot 1 is mandatory even on
#     the rare priced bullet, which is exactly the trap a "[N2] and nothing else" line would fall into.
#   SLOT 2, MAGNITUDE. OUTCOMES_JOIN J4 (2026-08-01) made the priced branch REACHABLE and changed nothing
#     else here: cascade._episode_outcome_legs prices an injected episode's own day-grain window on ONE
#     surviving delivery month and injects it as an ordinary [N] row. The ABSENCE MARKER IS STILL THE
#     DEFAULT, and now for a MEASURED reason rather than for want of an engine -- contract life is 396-587
#     sessions, so a multi-year episode span has no single contract to measure on and DECLINES; a driver
#     node has no price series at all; the per-slug coverage floor declines a window that predates it; and
#     the outcomes clamp declines a window whose end sits inside the survival margin. The other priced
#     surface, the SEAM-B WASDE avg_farm_price marketing-year pair (numbers/cascade.py ~2020-2075), is
#     unchanged: at most ONE pair per turn, on ONE derived focus window, declined outright on a
#     market-price or non-US slug. And because the _NO_PRICE_RECORD vocabulary is TURN-scoped ("no
#     observed magnitude"), not coverage-scoped, it is legitimate on an IN-FLOOR episode too, not only on
#     a pre-price-floor one.
# Both pins carry an ALL-LINES quantifier (`all(...)` over every bullet), so ONE sloppy bullet reds the row
# however many good ones precede it. The paragraph therefore forbids an empty slot outright rather than
# trusting the model to fill both, and makes the absence branch the default rather than the exception.
#
# THREE MECHANICAL RULES, each measured against a real strip path (this is why the shape is this shape):
#   (i)   THE SPAN GLYPH IS '..', NEVER AN ARROW. register._DERIV_OUTPUT (register.py:290-292) reads '->'
#         as a derived-output marker, which VOIDS the citation exemption in unbacked_levels (register.py:
#         534) -- on an OUTLOOK-register turn an arrowed bullet is stripped DESPITE carrying its handle.
#   (ii)  NO BARE NUMERAL ON A BULLET EXCEPT THE ISO SPAN. register._NUM_NOISE (332-342) scrubs \d{4}-\d{2}
#         so the span is safe, but _level_tokens (434-460) classifies any >=2-digit bare integer as a price
#         level, so a rendered report count -- "(11 reports)" -- is an unbacked level on an uncited bullet
#         and is STRIPPED under market_register=OUTLOOK, deleting the whole line and reding BOTH pins.
#   (iii) THE CITATION CLAUSE MUST SHARE VOCABULARY WITH THE RECEIPT. verify._verify_field drops the whole
#         SENTENCE on no_lexical_overlap / quote_mismatch / fabricated_citation, and _episode_lines reads
#         structured.mechanism POST-verify -- a bullet whose [E] clause is free prose sharing nothing with
#         the receipt is deleted before the scorer ever sees it.
# The price-absence rule lives HERE and only here: timeline.render_line cannot know whether a SEAM-B [N]
# pair covers a window, so a clause appended there would be unconditional and would forbid the one
# legitimate [N] line. One instruction, one file.
_SYSTEM_EPISODES = (
    "\nDATED EPISODES -- THE '## Episodes' SECTION. When one or more 'DATED EPISODES' lines CARRY A "
    "WINDOW, ENUMERATE those windows in a dedicated '## Episodes' section. THE SECTION IS MANDATORY the "
    "moment ANY injected line carries a dated window -- even one window on one line, even when every "
    "line also reports floored windows beside it, and even when a windowless floor line sits alongside. "
    "Rendering those windows as prose inside '## The record' or any other section is a DEFECT, not a "
    "substitute: the prose-instead path exists ONLY for the all-floored case below, where there is no "
    "window to enumerate at all. "
    # R6 residual fold (2026-08-04, second re-probe): the mandate alone did not cure four rows, and the
    # measured mechanism split two ways. (1) DISPLACEMENT: every persistently-omitting row but one
    # rendered '## Where the record disagrees' INSTEAD of '## Episodes' -- the model treated the two
    # sections as alternatives (freight proved they coexist). (2) BAIT: the smoothing-bait row's drafts
    # contain the word 'episode' ZERO times across three runs -- the question's own ask-for-a-tendency
    # framing out-competed the mandate. Both get named explicitly; vague mandates lose to shaped questions.
    "'## Where the record disagrees' NEVER substitutes for '## Episodes': the two sections COEXIST, and "
    "rendering the disagreement section does not discharge this one -- omit '## Episodes' beside it and "
    "the answer is DEFECTIVE. The QUESTION'S OWN FRAMING never waives the section either: a question "
    "asking for the general tendency, the 'usual' response, or a smoothed synthesis still gets the "
    "enumerated '## Episodes' its injected lines carry -- the enumeration IS the honest form of "
    "'usually', and answering the framing while dropping the enumeration is the smoothing this section "
    "exists to prevent. Render '## Episodes' ONLY when "
    "an injected line carries at least one window -- the section exists solely when the prompt supplies "
    "the episodes; never volunteer an episode list from prose, and never add an episode the lines do not "
    "carry. The DATED EPISODES rule above still holds in full: those lines are REPORT TIMESTAMPS, not "
    "descriptions, so do NOT manufacture severity, outcomes, or magnitudes from a bare count or date -- "
    "enumerating a window is not narrating it.\n"
    # R3 leg 1 fold (2026-08-02, adversarial finding). The corroboration floor made a line with ZERO
    # enumerable windows REACHABLE: timeline.floored_line carries LINE_PREFIX by design, so this persona
    # block still ships (that is the I-2 fix -- a floored node must speak rather than vanish), but the
    # line it ships beside says "This line carries NO window, so write no bullet for it". Every other rule
    # in this section -- "ENUMERATE them", "ONE '- ' bullet per injected episode", "EVERY INJECTED EPISODE
    # GETS ITS OWN BULLET ... Never drop an episode for being thin" -- then instructed the opposite, in the
    # same system prompt. The two outcomes of that contradiction are both defects: an EMPTY '## Episodes'
    # heading (violating the shape rule below, and scoring zero lines -- min_episode_lines and
    # episode_magnitude_or_absence both red), or a bullet minted from a bare count, which is the
    # +10-hallucination mode the whole timeline layer exists to close. The mitigation shipped inside the
    # injected string only; it belongs here too, because the persona is what the model reads first.
    "A 'DATED EPISODES' LINE THAT CARRIES NO WINDOW IS NOT AN EPISODE. A line reporting that every dated "
    "window for that node fell below the corroboration floor, and that NONE is shown, hands you nothing "
    "to enumerate: write NO bullet for it, give it no span, no date and no label, and never turn its "
    "count of suppressed windows into an episode -- that count is the number of windows you were NOT "
    "shown. If NO injected line carries a window -- every one of them is a floor line -- then OMIT the "
    "'## Episodes' section ENTIRELY: an empty heading is a defect, and a bullet minted to fill it is the "
    "invention this section exists to prevent. Say the thing the floor line actually tells you instead, "
    "in prose in '## The record': the dated record for that node is thin and uncorroborated. Stating that "
    "IS the answer. The rules below govern the windows the prompt SHOWS you -- 'never drop an episode for "
    "being thin' is about a window with no citable item, never about one the floor withheld.\n"
    "HEADING: exactly '## Episodes' -- level two, that word alone, no count suffix and no dash suffix, "
    "never inside a code fence. Place it AFTER '## The record' and BEFORE '## What to watch'. The section "
    "holds ONE '- ' bullet per injected episode WINDOW and NOTHING else: no lead-in sentence, no closing "
    "prose.\n"
    "EVERY INJECTED EPISODE WINDOW GETS ITS OWN BULLET, including the ones with no citable item. Never "
    "drop a window for being thin -- thin means the corpus holds no citable item inside it, never a "
    "window the floor withheld and did not show you -- never merge two into one bullet, and never invent "
    "one to round out the list.\n"
    # A5 (SKEPTIC F23): the shape line used to declare a UNIVERSAL '<plain-words label>' slot, which CASE 1
    # below then contradicts -- on a receipt-less window the label is the injected line's own, copied, and
    # a model reading the universal rule first is being told to write words the record cannot support.
    # BOTH SLOTS still means BACKING and MAGNITUDE, which CASE 1 fills with its two absence statements.
    "EACH BULLET HAS THIS SHAPE. BOTH slots -- BACKING and MAGNITUDE -- are REQUIRED on every bullet; on a "
    "NO CITABLE ITEM window they are filled by the two absence statements below, never left empty:\n"
    "  - <YYYY-MM>..<YYYY-MM> -- <label>: <BACKING>; <MAGNITUDE>.\n"
    "The LABEL slot is a plain-words label EXCEPT in CASE 1 (no citable item in the window), where it is "
    "the injected line's OWN label copied verbatim and nothing else -- see LABEL below.\n"
    "Write the span with FULL four-digit years on BOTH ends, joined by the two-dot glyph '..' -- NEVER an "
    "arrow, which this system reads as derived arithmetic and strips.\n"
    "ONE BULLET IS ONE PHYSICAL LINE. Keep the span, the label, the backing and the magnitude on the SAME "
    "line, however long it runs -- never wrap a bullet onto a continuation line and never break one across "
    "two '- ' items. A bullet is read line by line, so anything pushed onto a second line is not read as "
    "part of that episode.\n"
    # W4 A/B (2026-07-31): the label slot was the leak. On a NO CITABLE ITEM window the model dressed
    # '<what the window is, in plain words>' into an event narrative ("Black Sea export disruption episode")
    # the record cannot support -- the two absence slots were both stated correctly underneath it.
    "LABEL (between the span and the colon): when the injected episode says NO CITABLE ITEM IN THIS "
    "WINDOW, the label is that line's OWN label -- the node name the 'DATED EPISODES' line carries -- "
    "copied verbatim and NOTHING else. Do not characterise what happened there: no disruption, crisis, "
    "shock, collapse, squeeze or rally, and no cause, severity or outcome word of your own. An "
    "unreceipted window records WHEN reports clustered, not WHAT happened, so any characterisation of it "
    "is invented. A window that DOES carry a citable item may name itself from that receipt.\n"
    "BACKING (first slot) is EITHER one clause restating what a cited dated item inside that window "
    "actually says, carrying that item's [E] handle, OR -- when the injected episode says NO CITABLE ITEM "
    "IN THIS WINDOW -- the absence itself, in these words: 'no citable item', 'no dated source', or 'the "
    "corpus is silent'. An [N] handle does NOT fill this slot. Restate a TERM FROM THE RECEIPT the "
    "injected line showed you; a clause that shares no wording with the item it cites is dropped as "
    "unverifiable.\n"
    "MAGNITUDE (second slot) is EITHER the price move with its [N] handle, when an injected number row "
    "actually covers that window, OR an explicit statement that none does, in these words: 'no observed "
    "magnitude for this window', 'no priced move', or 'no price record for this window'. THE ABSENCE IS "
    "THE NORMAL CASE -- most episode windows have no single-contract price record that covers them, so "
    "most episodes have no magnitude and saying so plainly IS the correct answer; an invented move, or an "
    "empty slot, is not. A magnitude is an [N] HANDLE, never a bare numeral. A number row covers a window "
    "only when the row's OWN window is that episode's span: never carry a magnitude from one episode's "
    "bullet onto another's, and never read a level from elsewhere in the prompt as this window's move.\n"
    "THE TWO VOCABULARIES ARE DIFFERENT and answer different questions: 'no citable item' means the "
    "corpus holds no text for that window; 'no observed magnitude' means the price record holds no move "
    "for it. A window with NEITHER states BOTH, in that order -- one does not imply the other.\n"
    "NO BARE NUMBER anywhere on a bullet except the two years of the span. Do NOT render the episode's "
    "report count as a numeral (say 'a handful of reports', or omit it), and never state a level, "
    "percentage, or threshold without its handle -- an uncited number on a bullet gets the whole line "
    "stripped.\n"
    "WORKED EXAMPLES, one per case that actually occurs. THESE ARE SCHEMATIC. 'YYYY' is a literal "
    "placeholder and is NOT a date; every angle-bracket slot is a placeholder for what THIS turn's "
    "injected line says. Substitute the real span, the real label and the real handles. An answer that "
    "emits 'YYYY', emits an angle bracket, or reproduces one of these lines as though it were an "
    "episode has enumerated NOTHING -- an episode you did not read off an injected 'DATED EPISODES' "
    "line does not exist, and writing one down is the single worst failure available here.\n"
    "CASE 1 -- no citable item and no price row (the common case, both slots ABSENT; the label is the "
    "injected line's own, NOT a description of the window):\n"
    "- YYYY-MM..YYYY-MM -- <the node name the injected line carries, verbatim>: no citable item in this "
    "window, so what happened is not narrated; no price record for this window.\n"
    "CASE 2 -- receipted but unpriced (backing from the receipt, magnitude absent):\n"
    "- YYYY-MM..YYYY-MM -- <what the window is, in plain words>: <one clause restating what the cited "
    "in-window item actually says, reusing its wording> [E<k>]; no observed magnitude for this window.\n"
    # OUTCOMES_JOIN J4 item 66(ii): the old worked example was the SEAM-B WASDE marketing-year pair, which
    # is at most one pair per turn on a derived focus window and is declined outright on a market-price or
    # non-US slug -- i.e. an example of the one priced path that almost never covers an episode. The priced
    # path now IS an episode-window row, so the example is the shape the engine actually injects: a change
    # ACROSS the window, measured on the delivery month the row names, stated as a record and not as a
    # consequence of the receipt beside it.
    "CASE 3 -- receipted AND priced (only when an injected number row's own window IS this episode's "
    "span):\n"
    "- YYYY-MM..YYYY-MM -- <what the window is, in plain words>: <one clause restating the cited item> "
    "[E<k>], and across that window the settle change on the delivery month the row names was [N<k>].\n"
    "In CASE 3 the two slots are TWO SEPARATE RECORDS placed side by side -- what a dated item said, and "
    "what one contract's settle did across the same window. Do not write the second as a consequence of "
    "the first ('which drove', 'sending prices', 'in response'): the record holds no such link and stating "
    "one is invention.\n"
    "Stating an absence is the record, not a hedge -- and having enumerated these windows honestly, do "
    "NOT smooth the same episodes into a confident generalisation ('frosts usually ...') elsewhere in "
    "the note.")


# ══ D-HP-15 (H1b) -- THE SELECT-ORDER-CONNECT VARIANT. APPENDED, NOT REWRITTEN IN PLACE ═══════════════
# THE SAME SHAPE `_SYSTEM_HANDLES` USES ON THE BODY, and for the same reason: `_SYSTEM_EPISODES` is a
# module constant shared by EVERY turn, so an in-place rewrite would make the D-HP arm inseparable from
# the episode mandate and would cost the control arm its byte-identity (the one promise this wave may not
# spend). The control persona is `_SYSTEM_EPISODES` alone, byte-for-byte, and a pin asserts it.
# WHAT IT NARROWS, AND ONLY THAT: the SELECTION. The mandate above still owns the section's existence,
# its heading, its placement, its one-bullet-per-window rule and both absence vocabularies. This leg says
# the windows are the PROMPT'S, spelled the prompt's way -- which is what makes "the model picks episode
# ids" a checkable claim rather than a hope. ORDER stays the model's (the scorer's matching is
# order-insensitive) and CONNECTIVE PROSE stays free: neither is narrowed here, and the render-side pass
# this leg describes touches neither.
# IT DOES NOT RE-STATE THE NUMBER CONTRACT. `_SYSTEM_HANDLES` is appended after it and already narrows
# every magnitude instruction in the block above; saying it twice in two vocabularies is how a grammar
# acquires a contradiction (the D-HP-8 lesson, applied to its own successor).
_SYSTEM_EPISODES_SELECT = (
    "\nEPISODES UNDER THIS TURN'S NUMBER CONTRACT -- SELECT, ORDER, CONNECT. You do not author windows; "
    "you SELECT them. Every '## Episodes' bullet must name one of the windows an injected 'DATED "
    "EPISODES' line actually carried, and must spell that window EXACTLY as the line spells it -- the "
    "same four-digit years, the same two-dot glyph, the same '..' token, copied rather than retyped from "
    "memory. A bullet naming a window no injected line carried is DELETED WHOLE before the reader sees "
    "it, and so is a bullet whose window is spelled differently from the line it came from; there is no "
    "partial credit and no repair. Selecting FEWER windows than were injected is a legitimate move; "
    "inventing one is the worst move available here.\n"
    "CITE RECEIPTS BY THEIR HANDLES. When a window's injected line showed you a citable item, carry that "
    "item's [E] handle in the bullet exactly as you would anywhere else in the note -- the handle IS the "
    "citation and there is nothing else to declare.\n"
    "TYPE NO MAGNITUDES ON A BULLET. The span's two years are the only figures a bullet carries in its "
    "own right; a price move is an [N] handle in its slot or it is the plain statement that the record "
    "holds none. The report COUNT is never a numeral.\n"
    "THE CONNECTIVE PROSE IS YOURS. What the window is, why it belongs in this answer, how it sits "
    "beside the others -- write that in your own words. The rule above is about which windows exist, "
    "never about what you may say once you have chosen them.")


# D-RC-13: the dating discipline (the recency half of the desk-probe findings: the equities and
# Arabic answers led with MY2020-22 facts in PRESENT tense, and Malaysia's MPOB read never said its
# newest month was three months old). STATIC text -- the per-turn DATE rides the volatile GROUNDING
# LEDGER sentence (_recency_ledger_suffix), never this cached persona suffix.
_SYSTEM_RECENCY = (
    "\n\nRECENCY & DATING DISCIPLINE: the dated record has an EDGE, and the reader must always be able "
    "to see it. When you cite an item reported more than ~18 months before the as-of, DATE the claim in "
    "prose ('in MY 2021/22...', 'as of April 2026...') and keep it in the PAST tense -- present-tensing "
    "a stale fact ('stocks are tight' on a years-old report) misleads a desk. When the newest support "
    "for your central claim sits well behind the as-of, say so plainly in the body: 'the record here "
    "runs through <month year>'. The GROUNDING LEDGER states this turn's record edge; the as-of is the "
    "question's 'today'. Dating a claim is never optional where the reader could mistake it for current.")


# D-MW-30 / 30c: THE INVITATION (esc_r only), the reserve's missing half. P3-A proved graph admission works
# and citation does not follow -- and the reason is legible in hindsight: a reserved row rendered EXACTLY
# like a cosine one, so the writer had no way to know it was reached structurally rather than because it
# looked like the question. Two halves ride together: `_l2_blocks(provenance=True)` annotates the evidence
# header, and this paragraph says what the annotation MEANS. INFORMATION + PERMISSION, never a rule -- no
# cap, no quota, no "cite at least one". A mandate here would buy citations by compulsion and would measure
# nothing about whether the structural channel is USEFUL, which is the only thing the gate is asking.
_SYSTEM_PROVENANCE = (
    "\n\nSTRUCTURAL ADMISSIONS: evidence blocks marked '[graph admission: ...]' were reached through the "
    "causal graph -- an upstream ancestor of something already in scope, or a market this one cascades into "
    "-- rather than by textual similarity to the question, which is where a ROOT CAUSE usually sits. "
    "Tracing one back to explain WHY the near-term story is happening is invited wherever it strengthens "
    "the answer; it is never required, and an admission that adds nothing should simply be left alone.")


# ══ D-HP-7/8/12 (H1) -- THE HANDLE-PROSE CONTRACT. APPENDED, NOT REWRITTEN IN PLACE ═══════════════════
# THE SHAPE IS A ONE-SIDED NARROWING OF THE SHIPPED D-PQ CONTRACT, and the leg says so IN THE MODEL'S
# HEARING rather than leaving it to infer:
#     TODAY  "value AND handle"  (`_SYSTEM_CASCADE`: "every figure you state MUST appear in an injected
#                                 row and carry its numbered [N] handle"), verifier strips mismatches.
#     D-HP   "handle ONLY, written in the slot where the figure belongs." The left conjunct is deleted.
# The plan's instruction is that the four spans stating the old contract are "rewritten to say so". They
# are SUPERSEDED BY NAME here instead of edited in place, and that is not laziness -- it is D-HP-8's
# recorded decision. Those spans live in `_SYSTEM_MENTOR`, a module constant shared by EVERY turn; the
# in-place rewrite is a `response_contracts.apply` needle job over three byte-pinned needles shared by
# every contract, which would make the D-HP arm inseparable from the contract selector and cost the OFF
# arm its byte-identity. It is recorded as the consolidation follow-up, after G1/G2.
# AN APPENDED LEG THAT DOES NOT NAME WHAT IT OVERRIDES LEAVES THE MODEL HOLDING A CONTRADICTION, which is
# the one thing a grammar cannot survive -- so each superseded instruction is quoted back and cancelled.
#
# WHAT IS DELIBERATELY *NOT* IN HERE, each with its reason (D-HP-7's NOT-IN-SCOPE list + B7):
#   - NO DERIVATION GRAMMAR. The operator whitelist is SIZE ZERO, and after the R10 shown-bound re-run it
#     is a MEASUREMENT, not a decision: DERIVED numerals are 2.0% of the corpus at 0.25x their own chance
#     floor, falling to 1.3% / 0.8% under shown-binding, and NO op (sum, diff, ratio, pct_change,
#     count_streak, share, minmax, agg) clears its floor in any variant. The cascade already computes the
#     op and serves it as a row -- 50.3% of all typed numerals are a direct read of an ALREADY-DERIVED
#     metric. So the grammar is DIRECT + A REFUSAL, and the refusal is stated as a legitimate move.
#   - NO DENSITY MANDATE. Handles are OPTIONAL-WITH-REFUSAL (B7): mandatory-citation grammars convert
#     non-citation failures into MIS-citation failures, which feeds this wave's #1 risk directly. The
#     number-avoidance failure mode is caught by G1 clause (8)'s AGGREGATE band, checked after the fact,
#     with no instruction to the writer.
#   - NO DATE/ERA/MONTH HANDLES. Those are renderable today and are sequenced after G1/G2, so the model
#     must keep WRITING them -- and the leg says so explicitly, because a contract that reads "never type
#     a digit" would take the RECENCY discipline's dated claims down with it. The extractor agrees: a bare
#     calendar year, a year-range tail, a date's day, an ordinal and a duration modifier are all EXEMPT
#     from `_claim_number_spans`, so none of them is a magnitude to the lint either.
#   - NO SIGN. D1: the engine prints MAGNITUDE, the analyst writes DIRECTION. The splice writes abs(value)
#     for sign-meaningful rows precisely so the verb keeps carrying the sign, so a minus sign typed into
#     the prose would be the model overwriting the one thing it still owns.
_SYSTEM_HANDLES = (
    "\n\nHANDLE-PROSE (THIS TURN'S NUMBER CONTRACT -- IT NARROWS EVERY NUMBER INSTRUCTION ABOVE).\n"
    "THE ONE RULE: you do not type figures. You write the HANDLE where the figure belongs, and the engine "
    "substitutes the value, its unit and its citation before the reader sees the sentence. Write \"US wheat "
    "export commitments were [N4]\", never \"were 12.549 MMT [N4]\". The receipt rows above are a numbered "
    # PA-10(c): the [N] menu spans BOTH number panels -- the agent's lookups ('SILVER NUMBERS') and the
    # quantify loop's rows ('OBSERVED CASCADE NUMBERS') share one index space (`extra_number_calls`), so an
    # address described as a cascade row alone left the agent lane's rows nameless on exactly the turns
    # they are the whole answer. Counted the way it always was: [N] rows in order, across the number blocks.
    "MENU and a handle is an ADDRESS into it: [N7] is the 7th injected number row -- counted in order "
    "across the number panels ('OBSERVED CASCADE NUMBERS' and 'SILVER NUMBERS') -- and [E7] is the 7th "
    "evidence item, counted once per source across every block.\n"
    "THIS SUPERSEDES, BY NAME: (a) 'every figure you state MUST appear in an injected row AND carry its "
    "numbered [N] handle' -- the FIGURE half is deleted, the HANDLE half stands alone; (b) every "
    "instruction to DECLARE handles 'in the sources ledger' -- there is no sources ledger on this turn, the "
    "ledger is rendered from the handles you actually write, so writing [E3] IS declaring it and there is "
    "nothing else to fill in; (c) 'in `sources` ORDER citations most-trusted first' -- ordering now lives "
    "in the menu, whose every row carries its [T1]-[T4] trust tag: prefer the lowest-T row when two "
    "disagree, and FLAG the disagreement exactly as before.\n"
    "THE SLOT: put the handle exactly where the number would have gone -- after the value word ('at', "
    "'of', 'to', 'was', 'rose to', 'settled at', 'printed'). A handle that is not in a value slot reads as "
    "a plain citation and stays one. NEVER put a GROUPED or RANGED token ([N13, N14], [E1-E4]) in a value "
    "slot: a group stands in for no single figure, so there is nothing to substitute and the clause is "
    "dropped. Group only when you are citing several items for one qualitative claim.\n"
    # D-HP G1 REMEDIATION D2(a), 2026-08-14. THE MEASURED SHAPE, from the r2 artifacts: seven solitary,
    # FULLY RESOLVED [E] tokens standing immediately behind a value cue -- "priced at [E1]", "range from
    # [E17]", "from 500 to [E10] thousand metric tons". The slot rule above is written entirely in the [N]
    # vocabulary, so nothing in the grammar ever told the writer that the OTHER namespace cannot fill a
    # slot at all. It is a one-sentence extension of the paragraph it sits in, not a new rule: the value
    # slot belongs to [N] and to nothing else.
    "AND THE VALUE SLOT IS [N]'s ALONE -- AN [E] HANDLE IS NEVER A FIGURE. [E] names a dated item; the "
    "engine substitutes NOTHING for it, so an [E] handle standing behind a value cue ('priced at [E1]', "
    "'range from [E17]', 'from 500 to [E10]') is a sentence promising a number it cannot produce, and the "
    "clause carrying it is severed before the reader sees it. If the quantity is not itself a number row: "
    "type it in the SAME SENTENCE as that item's [E] handle under THE ONE EXEMPTION below, or say the "
    "record does not carry it. Beside prose, an [E] handle is exactly right and is left alone.\n"
    "ONE HANDLE, ONE FIGURE, AND CHECK THE ROW YOU ARE POINTING AT: the row's scope tag "
    "([series/country/table/period] on a number row, the source and dates on an evidence row) must be the "
    "thing your sentence is about. A handle pointing at a REAL but WRONG row prints a real, cited, wrong "
    "number -- the worst failure available on this turn, and worse than saying nothing.\n"
    # D-HP G1 REMEDIATION D1, 2026-08-14. THE DIAGNOSIS, from the r2 artifacts and NOT what the clause
    # table's phrase "a receipt that does not exist" suggests: every one of the 27 treatment events (and
    # every one of the control arm's 28) is an IN-RANGE index whose menu row came back EMPTY -- status
    # not_known / no_rows / error, rendered by `citations._empty_label` as "= NO ROWS RETURNED (...)".
    # Zero out-of-range indices, zero suffix forms, zero wholesale inventions on either arm. The model was
    # doing the honest thing badly: it grouped the empty rows into one token to EVIDENCE the gap
    # ("[N7, N8, N11, N12]", "[N15-N17]") after the prompt told it to state the gap. The menu numbers those
    # rows, the GROUNDING LEDGER's range covers them, and until this paragraph nothing said they are not
    # addressable. The renderer's drop is correct and stays; this is the half that stops the ADDRESSING.
    # THE SHARED HALF IS `orchestrator._numbers_block`'s EMPTY-1 directive, which carries the same clause
    # for the control arm and for the numbers lane (the measured empty rows are all agent lookups, which is
    # exactly that directive's population).
    "AN EMPTY MENU ROW IS NOT AN ADDRESS. A number row can come back with nothing in it -- 'NO ROWS "
    "RETURNED', whether not yet published, no matching rows, a lookup error or a declined read. It is "
    "numbered so you can SEE the gap, never so you can cite it: it holds no value, so its handle "
    "substitutes nothing and is deleted with the clause standing on it. NEVER write the handle of a row "
    "whose value reads NO ROWS RETURNED -- not alone, and not inside a group or range of handles, and not "
    "as the receipt for the absence itself. Say the gap in words ('the record carries no planted-area "
    "figure for this scope'); a stated absence needs no citation and is the correct move here.\n"
    "NO ARITHMETIC. Do not add, subtract, ratio, average, percent-change, rank or streak-count the menu's "
    "values into a new figure -- there is no way to write the result and it will be deleted. If the "
    "quantity you want is not ITSELF a row, either say it qualitatively ('roughly half', 'sharply lower', "
    "'the tightest in years' -- these carry no digit and are always allowed) or say the record does not "
    "carry it -- BUT 'the record does not carry it' is a claim about the ESTATE, and you may only "
    "make it about a figure this turn actually looked for: a figure nobody fetched is 'not retrieved "
    "this turn', never 'not in the record' (PA-9: the false-absence class -- a served series was "
    "twice declared absent by exactly this shortcut). Refusing a magnitude is a correct, "
    "professional move here; inventing one is not.\n"
    "NO HANDLE, NO MAGNITUDE -- and that is allowed. A claim may carry no handle at all, in which case it "
    "carries no figure. There is no minimum: do not sprinkle handles to look grounded, and do not force a "
    "number into a sentence that does not need one.\n"
    # D-HP G1 REMEDIATION-3 M2(a), 2026-08-14. THE MEASURED GAP, and it is the whole of G1's clause-(8)
    # failure on the covenant deck. The grammar above carries FOUR explicit licences to omit a magnitude
    # ("say it qualitatively"; "NO HANDLE, NO MAGNITUDE"; "say the gap in words"; "worse than saying
    # nothing") and ZERO affirmative instruction to use the menu it was handed. The design note at the top
    # of this block records the omission as deliberate -- "NO DENSITY MANDATE ... caught by G1 clause (8)'s
    # AGGREGATE band, checked after the fact, WITH NO INSTRUCTION TO THE WRITER". A detector was built and
    # the actuator was withheld; the detector fired.
    # THE MENU HYPOTHESIS IS REFUTED ROW BY ROW, so this is not a receipt-supply problem: on
    # `ab_mech_frost` the treatment arm's `served_rows` are BYTE-IDENTICAL to the control arm's (24 blocks
    # / 158 values), control addressed 8 distinct [N] rows across 11 tokens, the treatment wrote ZERO --
    # and every renderer-side counter on that row reads zero (handles_dropped 0, sentences_dropped 0,
    # unresolvable 0, empty_row_addressed 0, binding_refused 0). Nothing was taken away from the writer;
    # the writer took nothing. On `ab_rank_cocoa_origin` the treatment menu was RICHER than control's.
    # IT IS CLAIM-SCOPED, WITH NO COUNT, NO QUOTA AND NO MINIMUM, AND THAT IS NOT STYLE. A
    # mandatory-citation grammar converts non-citation failures into MIS-citation failures (B7, this
    # wave's #1 risk) and would trade clause (8) against R11 -- the OTHER whole-gate failure. The R11
    # exposure is arithmetic, not a worry: pooled over the six r4+d2 treatment invocations the SHIPPED
    # instrument charged 2.4 mis_bound per +100 substitutions, so recovering the measured headroom
    # projected about +3 pooled. Under the M1 detector that rate is 0.0 per 100 on the same corpus, which
    # is why this sentence ships BEHIND the detector fix and not in front of it.
    # THE WORDING IS THE DIAGNOSIS'S OWN, VERBATIM AND UNEDITED -- it was written claim-scoped on purpose
    # and re-drafting it here is how a careful clause loses its fence.
    "THE MENU IS PART OF THE ANSWER. Before a paragraph is finished, look back at the numbered rows: "
    "every magnitude the record offers FOR A CLAIM YOU ARE ALREADY MAKING belongs in that claim, as its "
    "handle. Writing 'stocks are thin' beside a live stocks row, or 'export pace fell' beside a live pace "
    "row, hands the reader your adjective where the record could have handed them the figure. This is not "
    "a minimum and not a quota: a claim you are not making needs no handle, and a row that is not about "
    "your claim is still left alone.\n"
    "STILL WRITE, EXACTLY AS BEFORE: dates, years, marketing years, delivery months, era labels, "
    "quarters and lags in words. Those are not magnitudes and the contract does not touch them -- 'the "
    "export ban took effect 2010-08 [E1]', 'in MY 2021/22', 'about a quarter later' are all correct.\n"
    "DIRECTION IS YOURS, MAGNITUDE IS THE ROW'S. Write 'fell', 'rose', 'widened', 'tightened', 'drew' -- "
    "the engine prints the size, never the direction, and never a sign. Do NOT write a minus sign, a "
    "leading '+' or the word 'negative' in front of a handle; the verb already carries it, and the engine "
    "checks your verb against the row's sign.\n"
    "THE ONE EXEMPTION, AND IT IS NARROW: a figure that appears in the QUOTED TEXT of an evidence item and "
    "exists nowhere in the number menu may be typed, IN THE SAME SENTENCE AS THAT ITEM'S [E] HANDLE. That "
    "is the only sentence in which a typed figure survives. Every other typed figure is a lint violation "
    "and the engine deletes the sentence that carries it -- so if you cannot find the row, do not type the "
    "number, say what the record supports.\n"
    # D-HP G1 REMEDIATION-3 M2(b), 2026-08-14. THE SECOND WRITER-SIDE GAP, and the artifacts show the
    # writer reaching PAST the exemption rather than using it. `d2_inv4` / `ab_verif_palm_levy` minted a
    # PSEUDO-HANDLE for a figure it was already licensed to type: "In March 2026, Indonesia *raised* the
    # export levy by [N-not-in-record text, but E24 states] \"2.5 percent to 12.5 percent\"". The
    # paragraph above states the exemption as a SURVIVAL rule ("the only sentence in which a typed figure
    # survives"), which reads as a hole in the lint that a careful writer should feel bad about using --
    # so a careful writer invented a token instead. It costs nothing to say the exemption is CORRECT, and
    # it recovers the `bare_digit_e_cited` population honestly rather than through a numerator re-reading
    # after the data is in (which is the re-litigation E.4's termination rule forbids).
    "AND USING THAT EXEMPTION IS CORRECT, NOT A LOOPHOLE: an [E]-quoted figure typed in that item's own "
    "sentence is exactly what the record supports and exactly how it should be written -- it is not a "
    "lint escape and nothing is deducted for it. Do NOT invent a substitute token to avoid typing it; a "
    "handle that names no menu row is the one thing on this turn that resolves to nothing at all.\n"
    # D-HP G1 AMENDMENT A2(b), 2026-08-14: THE SECOND UNCAPPED INSTRUCTION. `_PLAN_PROPERTY_DESC` and this
    # paragraph are the ONLY two places that instruct the region, and they are read in the SAME turn -- a
    # budget stated in one and contradicted by silence in the other is not a budget. Same number (~800),
    # same distinction (the LINT never charges a digit here; the CEILING always does).
    "THINK IN `plan` FIRST, AND KEEP IT SHORT. The `plan` property is your private scratchpad: nobody "
    "reads it, nothing is graded on it, and it is deleted before the answer is checked. Choose your rows "
    "there, compare them there, write numbers there freely -- no digit in `plan` is ever charged by the "
    "lint. BUT `plan` IS NOT FREE: it and the answer share ONE output budget, so a long plan is a short "
    "answer. Budget it at about 800 tokens (roughly 600 words) of terse notes -- the row list, the "
    # D-HP G1 REMEDIATION, 2026-08-14, THE ONE PROMPT-STRENGTHENING ATTEMPT (recorded, read by no clause).
    # A2's soft budget was exceeded on 22 of 24 treatment rows (median 1,667, max 4,695). The budget is
    # still SOFT -- no cap, no knob, nothing counts it -- so the only lever available is to say what the
    # measurement says, in both of the two places that instruct the region and in the same words.
    "comparison, the refusals -- and treat 800 as the number to plan TO, not a line to drift past: the "
    "best-scoring rows measured so far had the SHORTEST plans, so a plan running past ~1,500 tokens is "
    "evidence you are writing the answer twice. Then write the answer with handles in the slots.")


def _system(*, outlook: bool = False, episodes: bool | None = None, recency: bool = False,
            response_contract: str | None = None, budget: str | None = None,
            census: dict | None = None, provenance: bool = False, handles: bool = False,
            cascade_walk: bool = False, cascade_context: bool = False,
            cascade_deep: bool = False) -> str:
    """The active reader-facing persona. GRAPHRAG_MENTOR_VOICE default on -> mentor; =off -> the prior string.
    GRAPHRAG_CASCADE_QUANT on -> append the OBSERVED CASCADE NUMBERS addendum (P9-B: the loop supplies the
    [N] rows). GRAPHRAG_PATTERN_RECORDS on -> append the OBSERVATION-register RECORDED HISTORY directive (T2B).
    `outlook` (W5-D5, the three-leg gate already resolved by the caller) -> append the '## Outlook' balance-of-
    risks + derivation-gate directive; DEFAULT FALSE so every existing caller is byte-identical.
    `episodes` (W4-D3) -> append the reserved '## Episodes' enumeration directive. The SEAM resolves it as
    `_timeline_on() and _tl.LINE_PREFIX in vp` -- kill-switch AND an actually-injected 'DATED EPISODES'
    line -- and threads the bool DOWN; both serving bodies pass it explicitly. DEFAULT None falls back to
    the FLAG ALONE, which is the weaker half: it cannot see the prompt, so it is right only for a caller
    that has no prompt to inspect (tests, ad-hoc persona dumps). It is a floor, NOT the invariant; a new
    serving path must resolve both legs at its own seam rather than lean on this default.
    `census` (D-CC-1) is this turn's DETERMINISTIC composition census (_composition_census), threaded
    down as one argument exactly like `budget`: this function reads no environment for it and the
    seam that owns the kill-switch reads it once. None on every dark turn -> both contract seams
    below are byte-identical -> the whole composition lever has a provable off state.
    `provenance` (D-MW-30 / 30c) appends the STRUCTURAL-ADMISSION invitation, and is threaded down from
    the escalated bundle's `provenance_prompt` knob exactly like `budget` and `census`: this function
    reads no environment for it. DEFAULT FALSE, so every existing caller -- the one-hop body included --
    is byte-identical and the whole provenance lever has a provable off state.
    `handles` (D-HP-7/8) appends the HANDLE-PROSE contract -- the same threading discipline, and for the
    same reason it matters more here than anywhere else: this leg is the PROMPT half of a bundle whose
    other halves are the [E]/[N] render passes and the digit-lint's charge, and B8 says the three move
    together or the arm measures its own instrument. It is appended LAST of the legs because it NARROWS
    every number rule above it (the four superseded spans are named inside the text, not left to
    inference). It ALSO selects D-HP-15's `_SYSTEM_EPISODES_SELECT` leg, and only when `episodes` is
    already true: the select-order-connect variant NARROWS the episode mandate and is meaningless
    without it, so the two legs are one conjunction rather than two independent appends.
    DEFAULT FALSE -> byte-identical, and the OFF arm is provable rather than promised. The
    caller resolves it with `_handle_prose_active`, never with the raw knob: a persona that promised
    handle substitution on a turn where the renderer cannot run would ship handle-littered, number-free
    prose to the reader (section 2's MUTUAL-EXCLUSION law).
    `cascade_context` (V2-1) appends the CONTEXT-row mandate under the walk's own flag branch, threaded
    from both bodies as `_cascade_context_block_on(vp)`; DEFAULT FALSE -> byte-identical.
    Read PER CALL, never memoized: a serving process is long-lived, so a once-at-import read would
    make the env-flip rollback a silent no-op until a redeploy — defeating the gate's purpose."""
    if os.environ.get("GRAPHRAG_MENTOR_VOICE", "on") == "off":
        return _SYSTEM_LEGACY
    # D-RC-8: the contract REWRITES the three mandate sites (needle-verified replacement, identity
    # for None/default/passthrough) -- never an appended contradiction of the fixed-four mandate.
    # D-AM-10: `budget` is the reasoning mode's ALREADY-SCALED word range for this turn (None on
    # every standard/dark turn -> apply() uses the contract's own budget -> byte-identical).
    base = _rc.apply(_SYSTEM_MENTOR, response_contract, budget=budget, census=census)
    if os.environ.get("GRAPHRAG_CASCADE_QUANT", "on") != "off":
        base = base + _SYSTEM_CASCADE
        if _chain_on():                                            # chain paragraph rides the cascade block
            base = base + _SYSTEM_CHAIN
        if _transmission_on():                                     # ditto the HORIZONTAL chain's paragraph
            base = base + _SYSTEM_TRANSMISSION
        if _rv_regional_on():                                      # RV-REGIONAL (E1): the CROSS-BOARD
            base = base + _SYSTEM_CROSS_BOARD                      # license, omit-when-off byte-identical
        if _derived_arith_on():                                    # D-DA: the BALANCE-STANDING license,
            base = base + _SYSTEM_DERIVED_ARITH                    # same omit-when-off discipline
        if _cascade_walk_on():                                     # CASCADE EPISODE WALK: the
            base = base + _SYSTEM_CASCADE_WALK                     # CONSEQUENCE license, same idiom
            if cascade_walk:                                       # + the MANDATE, marker-gated at
                base = base + _SYSTEM_CASCADE_WALK_MANDATE         #   the seam (the _episodes_on shape)
            if cascade_context and _cascade_context_on():          # V2-1: the CONTEXT mandate, row-
                base = base + _SYSTEM_CASCADE_CONTEXT              #   gated at the seam, its own flag,
            if cascade_deep and _cascade_deep_on():                # V2-5: the DEEP mandate, marker-
                base = base + _SYSTEM_CASCADE_DEEP                 #   gated the same way. DEFAULT
            #                                                          FALSE -> byte-identical.
            #                                                        pure append
            #                                                        DECLARED DEVIATION from charter
            #                                                        STEP 8's marker-presence gate:
            #                                                        flag-only, the CROSS_BOARD /
            #                                                        DERIVED_ARITH sibling precedent
            #                                                        -- the text is a conditional
            #                                                        LICENSE, never a section
            #                                                        mandate, so a walk-less turn
            #                                                        carries a dormant clause, not
            #                                                        a demand (review minor, noted)
    if _pattern_records_on():
        from leviathan.graphrag.numbers import pattern_records as _pr   # lazy: avoid an import cycle
        base = base + _pr.RECORDED_HISTORY_ADDENDUM
    if episodes is None:                                           # no prompt to inspect -> the FLAG leg only
        episodes = _timeline_on()                                  #   (a floor, not the seam invariant)
    if episodes:                                                   # W4-D3: the reserved '## Episodes' heading
        base = base + _SYSTEM_EPISODES
        if handles:                                                # D-HP-15: the SELECT variant, appended
            base = base + _SYSTEM_EPISODES_SELECT                  #   (control = the mandate alone, pinned)
    if outlook:                                                    # W5-D5: the reserved '## Outlook' heading
        base = base + _SYSTEM_OUTLOOK
    if recency:                                                    # D-RC-13: dating discipline (flag resolved
        base = base + _SYSTEM_RECENCY                              #   by the caller's seam, threaded DOWN)
    if provenance:                                                 # D-MW-30 (esc_r): the structural-admission
        base = base + _SYSTEM_PROVENANCE                           #   INVITATION, threaded from the mode knob
    if handles:                                                    # D-HP-7/8: LAST of the legs, because it
        base = base + _SYSTEM_HANDLES                              #   NARROWS every number rule above it
    base = base + _rc.directive(response_contract, census=census)  # D-RC Phase B: emphasis LAST ('' for
    return base                                                    #   default/None -- the fail-open pin)


_SYSTEM = _SYSTEM_MENTOR                                              # module-level default (importers/tests)


def route_scored(query: str, graph: gph.CausalGraph) -> list[tuple[int, str]]:
    """TIER 1 (lexical), SCORED: (hit_count, contract_id) most-hits-first. `route` is this function with
    the counts dropped -- ONE producer, so the two can never disagree. Split out for D-XT's route_probe
    (N4): the shipped `route` discards the counts, which made any tie-count instrument structurally 1."""
    scored = []
    for cid, c in graph.contracts.items():
        forms = [cid, cid.replace("_", " ")] + list(c.aliases) + cid.split("_")
        m = hv.build_matcher(forms)
        n = len(m.findall(query))
        if n:
            scored.append((n, cid))
    return sorted(scored, reverse=True)


def route(query: str, graph: gph.CausalGraph) -> list[str]:
    """TIER 1 (lexical): contracts whose id/aliases/commodity-token appear in the query (accent/case-insensitive),
    most-hits first. Fast + precise, but blind to coreference/paraphrase ('a frost in Brazil', 'that contract').
    BYTE-IDENTICAL to its pre-D-XT self by construction: same scoring loop, same sorted(scored, reverse=True),
    same projection -- just via the ONE scored producer above."""
    return [cid for _, cid in route_scored(query, graph)]


_PROFILE_CACHE: dict = {}


def _contract_profiles(graph: gph.CausalGraph) -> dict[str, str]:
    """A short text profile per contract for semantic routing: id + aliases + its top driver ids."""
    return {cid: f"{cid.replace('_', ' ')} {' '.join(c.aliases)} "
                 f"{' '.join(d.id.replace('_', ' ') for d in c.drivers[:12])}"
            for cid, c in graph.contracts.items()}


def route_semantic(query: str, graph: gph.CausalGraph, *, embed=None, k: int = 2, min_cos: float = 0.35) -> list[str]:
    """TIER 2 (semantic): embed the query (bge-m3) + cosine vs per-contract profiles — catches paraphrase that
    names no commodity ('a frost in Brazil'). Profile vectors are cached per contract set."""
    embed = embed or ev.embed
    profs = _contract_profiles(graph)
    key = tuple(sorted(profs))
    if key not in _PROFILE_CACHE:
        _PROFILE_CACHE[key] = (list(profs), embed(list(profs.values())))
    ids, vecs = _PROFILE_CACHE[key]
    qv = embed([query])[0]
    ranked = sorted(((ev._cosine(qv, v), cid) for cid, v in zip(ids, vecs)), reverse=True)
    return [cid for s, cid in ranked[:k] if s >= min_cos]


def _route_llm_tool() -> dict:
    return {"name": "pick_contracts", "description": "Pick the tracked contract id(s) the question is about.",
            "input_schema": {"type": "object", "properties": {
                "contracts": {"type": "array", "items": {"type": "string"}}}, "required": ["contracts"]}}


def route_llm(query: str, graph: gph.CausalGraph, *, k: int = 2, call=None) -> list[str]:
    """TIER 3 (LLM): a cheap Haiku call resolves coreference/comparison/multi-commodity ('which ag is most
    exposed to the dollar') by mapping the question to ids from the tracked list.

    D-MW-13 (the router de-cap): `k` is now the tier's SEED CEILING, and the prompt phrase is RENDERED
    from it rather than typed. The pair used to disagree the moment a caller widened k -- the prose said
    "the 1-2 most relevant" while the code sliced at 6 -- and the model obeys the prose, so a widened
    walk silently kept receiving two ids. At the default k=2 the rendered sentence is byte-identical to
    the shipped one."""
    call = call or _call_opus
    ids = list(graph.contracts)
    n = max(1, int(k))
    want = "the most relevant one" if n == 1 else f"the 1-{n} most relevant"
    sys = ("Map a commodities question to the tracked futures-contract id(s) it concerns. Resolve coreference and "
           f"comparisons. Return ONLY ids from the provided list, {want}, via pick_contracts.")
    user = f"TRACKED CONTRACTS: {ids}\n\nQUESTION: {query}"
    out = call(sys, user, model=ex.HAIKU, tool=_route_llm_tool())
    return [c for c in (out.get("contracts") or []) if c in graph.contracts][:n]


def route_smart(query: str, graph: gph.CausalGraph, *, embed=None, route_call=None, k: int = 2) -> list[str]:
    """Tiered router: lexical -> semantic -> LLM. Lexical wins when it fires (fast/precise); otherwise fall back
    to semantic (paraphrase), then an LLM call (coreference/comparison)."""
    return (route(query, graph)
            or route_semantic(query, graph, embed=embed, k=k)
            or route_llm(query, graph, k=k, call=route_call))


def _context_block(graph: gph.CausalGraph, contract: str) -> str:
    c = graph.contracts[contract]
    tgt0 = c.target_metrics[0] if c.target_metrics else "price"
    lines = [f"CONTRACT: {contract} (target: {', '.join(c.target_metrics)})", "",
             "DRIVERS (id | sign on target | lag | live | conf | mechanism):"]
    for d in c.drivers:
        live = "live" if graph.silver_status(contract, d.id)["live"] else d.silver_status
        tgt = d.target_metric or tgt0                          # a yield/production driver overrides the price default
        lines.append(f"- {d.id} | {d.sign} on {tgt} | {d.lag or 'n/a'} | {live} | conf={d.confidence} | {d.mechanism}")
    lines.append("\nCONVERGENCE REGIMES (name | direction | needs N of drivers | note):")
    for s in c.convergence:
        lines.append(f"- {s.name} | {s.direction} | {s.requires_any_n_of} of {s.drivers} | {s.note}")
        for it in s.interactions:
            lines.append(f"    interaction: {it.when} -> {it.effect}: {it.note}")
    lines.append("\nINTER-COMMODITY EDGES (commodity | relation | sign | mechanism):")
    for e in c.inter_commodity:
        lines.append(f"- {e.driver_commodity} | {e.relation} | {e.sign} | {e.mechanism}")
    return "\n".join(lines)


def _pgnumbers_live() -> bool:
    """P9-B breaker: the cascade loop only fires when a real pg numbers mirror is present -- an outage or a
    pg-less env stays qualitative instead of Athena-crawling the partition surface."""
    try:
        from leviathan.graphrag.numbers import pgnumbers
        return bool(pgnumbers.enabled())
    except Exception:  # noqa: BLE001
        return False


_DATE_SENTINEL = "1970-01-01"


def _usable_date(d) -> str | None:
    """A real, non-sentinel ISO date, else None. The `date` field can be a 1970-01-01 sentinel or a
    YYYY-01-01 year-floor (evidence date parsing); an event date of the sentinel is not a real event date."""
    s = str(d or "")[:10]
    return s if (s and s != _DATE_SENTINEL) else None


def _uniq_evidence(evidence: list[dict]) -> list[dict]:
    """THE ONE deduped evidence list (D-HP-1) -- `uniq`, first-occurrence order, deduped by `source_key`.

    Lifted VERBATIM out of the two bodies' inline `seen_docs, uniq = set(), []` loops so the three
    consumers (the rendered MENU, `citations.unify`'s [E] numbering, and `verify_citations`' resolution
    set) can never again be three separate derivations of "which evidence rows exist". An item with no
    `source_key` is not in `uniq` -- it has no durable identity to cite, and that was already true of the
    footer and of `unify`; D-HP-1 only makes the MENU agree with them."""
    seen_docs, uniq = set(), []
    for h in evidence or []:
        sk = h.get("source_key")
        if sk and sk not in seen_docs:
            seen_docs.add(sk)
            uniq.append(h)
    return uniq


def _evidence_ordinals(uniq: list[dict]) -> dict[str, int]:
    """`source_key` -> its 1-based GLOBAL [E] ordinal, taken off `uniq` -- i.e. the SAME positional index
    `cit.unify` stamps (`id=f"E{i}"`, citations.py:1003-1021) and the same one `[E{i}] == uniq[i-1]` means
    to the verifier. D-HP-1's whole point: NOT a counter threaded through the per-contract render loop.

    WHY A COUNTER CANNOT WORK (recon 2 s2, the sharpest landmine in the wave). `_l2_blocks` regroups by
    contract (`for cid in dict.fromkeys(n.contract for n in _nodes)`) and emits a node's evidence per
    driver, while `sg.nodes` is BFS-WAVE ordered -- insertion-ordered by wave, so on any multi-seed or
    cross-hop walk it is NOT contract-contiguous. A render-order counter therefore disagrees with `unify`
    on every turn with a repeated `source_key` or a non-contract-contiguous wave order, which is EVERY
    standard and quick turn (`order_policy` is None there). `_render_order`'s own docstring says the two
    "cannot be allowed to disagree"; before D-HP-1 they coincided only by luck."""
    return {str(h.get("source_key")): i for i, h in enumerate(uniq, 1) if h.get("source_key")}


def _evidence_menu(uniq: list[dict]) -> dict[str, tuple[int, dict]]:
    """`source_key` -> (its global [E] ordinal, THE ROW THAT ORDINAL MEANS -- `uniq[i-1]`).

    THE D-HP-1 INVARIANT, MADE STRUCTURAL (H0 review, the blocker). The first H0 build threaded the
    ORDINALS ALONE and left `_ev_block` to render whichever chunk of a `source_key` it met FIRST IN
    RENDER ORDER. Those are two different rows: `_l2_blocks` regroups by contract while `uniq` is flat
    `_render_order` order, and `source_key` is a DOCUMENT key -- `evidence.py:314` builds one record PER
    PROPOSITION under the same key, so two chunks of one document carry genuinely different TEXT. The
    model then read one passage under `[E{i}]` while `cit.unify`'s payload, the FE chip snippet and
    `verify._check_evidence_handle`'s quote pool all carried the OTHER one. Consequences measured on the
    fixture: a sentence correctly quoting what it was SHOWN strips as `quote_mismatch` /
    `no_lexical_overlap` (a NEW false-caution class, manufactured by the menu itself and landing inside
    G1 clause (3)/(4)'s declared set), and the FE shows a snippet the model never saw.

    SO THE ORDINAL AND THE ROW IT NAMES TRAVEL AS ONE OBJECT. A caller cannot hold the numbering without
    holding the text it binds -- the menu IS the ledger, or the grammar dies at birth. Derived from
    `_evidence_ordinals`, never beside it: there is still exactly ONE numbering derivation in this file."""
    return {sk: (n, uniq[n - 1]) for sk, n in _evidence_ordinals(uniq).items()}


def _ev_block(evidence: list[dict], menu: dict[str, tuple[int, dict]] | None = None,
              rendered: set[str] | None = None) -> str:
    """One rendered evidence block. D-HP-2 numbers each row with its GLOBAL [E] ordinal.

    ROW SHAPE (D-HP-2, corrected to PRESERVE THE TRUST TAG):
        `- [E7][T2] (USDA WASDE, reported 2026-05-12; event 2026-04-30) {driver: x} <text>`
    The draft's `- [E7] (USDA WASDE, ...)` silently deleted `[T1]-[T4]`, which is the row's LEADING token
    today and which the persona depends on TWICE, verbatim (answer.py:117-120 and :260-263: "each evidence
    item is tagged [T1]-[T4] by source trust ... When sources of DIFFERENT tiers disagree on a fact, FLAG
    the disagreement"). The ordinal SHARES the head with [T], so the incremental prompt cost is ~0 -- and
    it matches the [N] rows' shipped idiom (numbers/cascade.py:1747) and the dossier's `notes_block`
    (dossier.py:626-634), which already renders exactly this at document scale.

    `menu` / `rendered` are BOTH OMITTED-WHEN-DEFAULT: with `menu=None` this returns the pre-D-HP-2
    bytes exactly, so every other caller (and the flag-off/verify-off branch, and the DOSSIER SUB-ANSWER
    LANE per D-HP-16) is unchanged.

    `menu` IS `_evidence_menu`'s (ordinal, uniq row) PAIR, NEVER A BARE ORDINAL (H0 review blocker): the
    text rendered under `[E{i}]` is `uniq[i-1]`'s text by construction, not "whichever chunk of this
    document this contract's block happened to carry". See `_evidence_menu` for the measured failure.

    THE PER-DRIVER BLOCK STRUCTURE IS PRESERVED (D-HP-1). The menu is NUMBERED from `uniq` but RENDERED in
    the existing per-contract / per-driver blocks, because the D-MW-30 admission-provenance header
    (`_admission_note(n)`) has nowhere else to live and D-HP-25 lever (ii) rides it. A duplicate
    `source_key` renders its TEXT once, at its first block, and is CROSS-REFERENCED by its global ordinal
    everywhere else -- `rendered` is the caller-owned set that carries that state across blocks. An item
    with no ordinal (no `source_key`, so not in `uniq` and uncitable) renders in its pre-D-HP shape: no
    handle is offered for a row the reader could never be shown.

    A MENU REQUIRES ITS `rendered` SET (H1 residual 10.9(3), NARROWED BY FIX Z3). `menu` without
    `rendered` compiles and reads plausibly, and it SILENTLY BREAKS THE LEDGER PROPERTY: with no
    caller-owned set to carry the cross-reference state, a `source_key` met twice renders its text TWICE
    under the SAME `[E{i}]` label, so an ordinal stops naming exactly one row -- the one thing D-HP-2's
    menu exists to promise. That direction is a real defect and still raises.
    THE OTHER DIRECTION IS A LEGITIMATE CALL AND MUST NOT RAISE. `rendered` without `menu` is an unused
    accumulator, not a broken ledger: with `menu=None` every row renders in its pre-D-HP shape and the set
    is never read. The ONE-HOP body passes `rendered=set()` UNCONDITIONALLY while its menu is None
    whenever `_handle_menu_on()` is False -- i.e. on `dossier.run_subquery`'s every sub-call -- so the
    symmetric guard turned the DOCUMENTED `GRAPHRAG_PLANNER=onehop` rollback lane into a ValueError out of
    `answer()`: a guard against a silent mis-render that crashed the fallback it was meant to protect.
    Symmetry is not the invariant; "an ordinal names exactly one row" is, and only one half of the pair
    can break it.

    THE LABELLED ROW'S HEADER COMES FROM THE ROW THE LABEL BINDS (H1 residual 10.9(1)). The H0 fix bound
    the TEXT under `[E{i}]` to `uniq[i-1]` but left the head (source / reported date / event date) and the
    driver tag reading the LOCALLY ENCOUNTERED row -- so on the L2 body, where `_l2_blocks` regroups by
    contract while `uniq` is flat `_render_order` order, a duplicate `source_key` could ship the bound
    text under ANOTHER chunk's event date or driver tag. That is the same defect the H0 blocker fixed, one
    field over: a mislabelled receipt is a wrong receipt even when the prose under it is right. The head
    and the text are now derived from ONE row, `rep`, and cannot disagree.
    THE CROSS-REFERENCE ROW KEEPS ITS LOCAL HEAD, deliberately: it binds NO text (it names the label whose
    text is above), and its head + driver tag + admission provenance are what place THIS occurrence in
    THIS block -- which is the per-driver structure the clause above preserves on purpose."""
    if menu is not None and rendered is None:                   # FIX Z3: only the LEDGER-BREAKING half
        raise ValueError("_ev_block: a `menu` requires its caller-owned `rendered` set -- without one a "
                         "`source_key` met twice renders one ordinal's text twice and breaks the D-HP-2 "
                         "ledger property; pass both (the D-HP path) or menu=None (pre-D-HP bytes).")

    def _head_of(e: dict) -> tuple[str, str]:
        """(head, driver tag) for ONE row -- the single derivation both branches call, so a labelled row's
        header can only ever describe the row whose text it carries."""
        head = f"[T{source_tier(e['source'])}] ({e['source']}, reported {e['date']}"
        ev_dt = _usable_date(e.get("event_date"))
        if ev_dt and ev_dt != str(e["date"])[:10]:             # WS-MS6: show WHEN the event happened vs was reported
            head += f"; event {ev_dt}"
        head += ")"
        return head, (f" {{driver: {e['driver']}}}" if e.get("driver") else "")   # cross-cutting cascade trigger

    def _one(e: dict) -> str:
        head, drv = _head_of(e)
        if menu is None:
            return f"- {head}{drv} {e['text']}"
        sk = str(e.get("source_key") or "")
        hit = menu.get(sk)
        if not hit:
            return f"- {head}{drv} {e['text']}"                 # uncitable row: pre-D-HP shape, no handle
        n, rep = hit
        if rendered is not None and sk in rendered:
            # THE CROSS-REFERENCE NAMES THE FIRST LABEL THE TEXT RENDERED UNDER, AND NEVER ITSELF (H0
            # review). The first build emitted `- [E3]... (same item as [E3] above)` -- a tautology in a
            # prompt whose whole job is to teach that an ordinal is an ADDRESS. This row carries NO [E]
            # label of its own, so `[E{n}]` unambiguously names the ONE row whose text is above and the
            # menu keeps the ledger property: each `[E{i}]` labels exactly one row, and that row has the
            # text. The block header, the driver tag and the admission provenance all survive.
            return f"- {head}{drv} (same item as [E{n}] above)"
        if rendered is not None:
            rendered.add(sk)
        _head, _drv = _head_of(rep)                            # H1 residual 10.9(1): head + text, ONE row
        return f"- [E{n}]{_head}{_drv} {rep['text']}"
    return "\n".join(_one(e) for e in evidence) or "(no evidence retrieved)"


_MAX_DRIVER_SLICES = 5
_DRIVER_K = 3


def _active_drivers(query: str, contracts: list[str], graph: gph.CausalGraph) -> list[str]:
    """Driver slices relevant to the query + the routed subgraph's driver mechanisms — so 'what drives cocoa'
    (no driver named) still pulls the cocoa DAG's drivers (harmattan/drought) via their mechanism text."""
    text = query + " " + " ".join(f"{d.id} {d.mechanism}" for c in contracts for d in graph.contracts[c].drivers)
    out: list[str] = []
    for dn in ev.driver_slices_for(text):
        if dn not in out:
            out.append(dn)
    return out[:_MAX_DRIVER_SLICES]


def _driver_evidence(query: str, drivers: list[str], *, k: int, asof, near, retrieve_fn) -> list[dict]:
    """Top-k dated evidence from each active driver slice (evidence/drivers/<driver>.jsonl), tagged with its driver."""
    hits: list[dict] = []
    for dn in drivers:
        for h in retrieve_fn(query, f"drivers/{dn}", k=k, asof=asof, near=near):
            hits.append({**h, "driver": dn})
    return hits


def _render_order(nodes: list, order_policy: str | None) -> list:
    """THE node sequence -- the one the evidence render walks AND the one the flat evidence list is built
    from. They cannot be allowed to disagree: the flat list is what `citations.unify` numbers E1..En, what
    the verifier matches ledger entries against, and what `_synth_ref_floor` counts.

    `order_policy=None` returns `nodes` unchanged -> every caller is byte-identical to pre-D-DV.
    `"relevance"` sorts by (depth, -relevance) and REVERSES, so the strongest node's rows land at the END
    of the evidence block, adjacent to the ledger and the question (the attention-basin result: strongest
    at the edges, weakest in the middle -- the prompt renders walk order today, which is why deep
    RESHUFFLED what the model reads first instead of merely appending to it). The result is kept
    CONTRACT-CONTIGUOUS with the strongest contract last, because the render's unit is a per-contract
    block; within a contract the strongest node is still last."""
    if order_policy != "relevance":
        return list(nodes)
    ranked = sorted(nodes, key=lambda n: (int(getattr(n, "depth", 0) or 0),
                                          -float(getattr(n, "relevance", 0.0) or 0.0),
                                          str(n.contract), str(n.id)))
    best: dict = {}
    for i, n in enumerate(ranked):
        best.setdefault(n.contract, i)                         # a contract ranks by its STRONGEST node
    out: list = []
    for cid in sorted(best, key=lambda c: -best[c]):           # weakest contract first, strongest last
        out.extend(reversed([n for n in ranked if n.contract == cid]))
    return out


def _admission_note(node) -> str:
    """D-MW-30 / 30c: the admission provenance suffix for a STRUCTURALLY admitted node -- '' for every
    cosine node, every seed, every focus_driver inject, and every node whose admission record is absent
    or malformed. Built from the audit record the walk ALREADY writes (planner._reserve_plan's
    `admissions` map, mirrored onto GroundedNode.admission), so nothing new is computed at render time
    and the string can never disagree with the trace an artifact carries.

    The test is MEMBERSHIP in `planner._STRUCTURAL_REASONS`, never a literal (the D-MW-15 law): a THIRD
    structural reason -- P6's `cascade_downstream_contract` -- must annotate on the day it lands, not on
    the day someone remembers this function exists. Note that P6's reason attaches to a CONTRACT node,
    and only the driver header is annotated below, so that wave threads this helper at its own header.

    The planner import is LAZY for the same reason _answer_l2's is: answer <- planner is a cycle, and
    this is a sys.modules hit on every real turn (the caller imported it before the walk ran)."""
    from leviathan.graphrag import planner as _pl
    adm = getattr(node, "admission", None) or {}
    if not isinstance(adm, dict) or adm.get("reason") not in _pl._STRUCTURAL_REASONS:
        return ""
    upstream = adm.get("reason") == _pl.REASON_CLOSURE
    anchor = adm.get("ancestor_of")
    lead = "upstream ancestor of" if upstream else "downstream of"
    note = f"{lead} {anchor}" if anchor else ("upstream structural admission" if upstream
                                              else "downstream structural admission")
    anchors = adm.get("anchors") or []
    if adm.get("convergence") and anchors:          # (v) reachable from >= 2 admitted anchors' chains
        note += f", converges from {len(anchors)} anchors"
    return f" [graph admission: {note}]"


def _l2_blocks(sg, graph: gph.CausalGraph, asof: str | None = None, order: list | None = None,
               provenance: bool = False,
               menu: dict[str, tuple[int, dict]] | None = None) -> list[str]:
    """v1.1 ADDITIVE assembly (the A/B fix): the reasoner gets AT LEAST what one-hop gave it — the FULL
    _context_block per contract (all drivers, all regime definitions, inter-commodity edges) — PLUS the walk's
    structure: how each cross-commodity contract was REACHED (edge + category: an accounting identity needs no
    dated evidence, a causal link does), per-node dated evidence, deterministic ACTIVE flags, and — framed with
    the honesty the evidence supports — regimes whose conditions are DOCUMENTED near the as-of. The first
    regime-fix eval proved the framing is load-bearing: a header saying 'FIRED AT THIS AS-OF' made the reasoner
    assert unverified live state (PIT 4.1->3.7, halluc 61->72). Conditions render as consistent-with + per-
    driver receipts, never as confirmed state, until the silver leg (F4) can actually verify.

    Returns (stable_blocks, volatile_blocks): the STABLE part — hop annotations + the per-contract graph
    context + the shared-ancestor note — is byte-identical across a session's turns and forms the prompt-
    cache prefix; everything per-turn (convergence state, active lists, retrieved evidence) is volatile.

    `provenance` (D-MW-30 / 30c, esc_r only) annotates a STRUCTURALLY admitted driver's evidence header
    with how the walk reached it. DEFAULT FALSE, and False makes the suffix the empty string, so the
    render is byte-identical for every other caller — on a reserved walk too, not merely on an empty one.
    It touches the VOLATILE half only: the annotation is per-turn state, so the cached stable prefix is
    unaffected either way.

    `menu` (D-HP-1/D-HP-2, H0) is `_evidence_menu`'s `source_key -> (global [E] ordinal, THE uniq ROW)`,
    built ONCE by the caller off `uniq` and threaded here so the rendered menu carries the SAME numbering
    -- AND THE SAME TEXT -- `cit.unify` and the verifier use. DEFAULT None -> `_ev_block` renders its
    pre-D-HP bytes, so every other caller is byte-identical, and so is the DOSSIER SUB-ANSWER LANE, which
    holds the whole menu off until D-HP-28 opens (see `handle_menu_override`).
    CACHE LAW (D-HP-2, corrected): the evidence rows were ALREADY volatile -- every evidence block is
    appended to `vlines`, and the stable half is hop annotations + `_context_block` only. NUMBERING THEM
    CHANGES NO CACHED BYTE AND THE MENU STAYS WHERE IT IS. (Moving the menu's POSITION is D-HP-25 lever
    (iii) and belongs to the reserve arm -- doing it here would confound the one untried reserve lever
    with a named mechanism.)"""
    stable: list[str] = []
    volatile: list[str] = []
    # ONE cross-block set: a duplicate `source_key` renders its text at its FIRST block and is
    # cross-referenced by its global ordinal in every later one. Blocks keep their headers; ordinals are
    # global. Owned here (not by `_ev_block`) because the state spans blocks by construction.
    _seen_rows: set[str] | None = set() if menu is not None else None
    # `order` (D-DV-2) is the SAME sequence _answer_l2 builds its flat evidence list from. None -> sg.nodes,
    # and `_by` is then sg.by_contract's own comprehension, so the render is byte-identical.
    _nodes = sg.nodes if order is None else order

    def _by(cid: str) -> list:
        return [n for n in _nodes if n.contract == cid]
    fired_by = {}
    for r in sg.fired_regimes:
        fired_by.setdefault(r["contract"], []).append(r)
    for cid in dict.fromkeys(n.contract for n in _nodes):
        cnode = next((n for n in _by(cid) if n.kind == "contract"), None)
        lines = []
        if cnode and cnode.via_edge:                               # how the walk REACHED this contract
            e = cnode.via_edge
            kind = e.get("category", "causal")
            note = ("an accounting/processing identity — holds by construction, no dated evidence needed"
                    if kind == "transformation" else
                    "a market-structure link" if kind == "market_structure" else "a causal link — needs evidence")
            # T1-3 (cascade step-0b): the CONTRACT header carries the admission provenance too, and the
            # helper's own docstring declared this the owed work ("P6's reason attaches to a CONTRACT node,
            # and only the driver header is annotated below, so that wave threads this helper at its own
            # header"). WITHOUT IT the one fact that distinguishes a PAID cross-market block from an
            # ordinary walked hop -- that the graph reached this market downstream of a named seed, and
            # from how many anchors -- never reaches the writer, so `n_convergence_cross` is a trace column
            # nothing in the prompt can act on. It rides the CASCADE-HOP line for the same reason the driver
            # suffix rides the driver header: the evidence rows are untouched dicts, so the string is
            # invisible to `citations.unify`'s E-numbering and to the verifier's resolution set BY
            # CONSTRUCTION. `provenance` False -> `_csfx` is "" -> this line is byte-identical to pre-T1-3.
            _csfx = _admission_note(cnode) if provenance else ""
            lines.append(f"REACHED VIA CASCADE HOP: {e.get('_from')} --{e.get('relation')}({e.get('sign')})--> {cid}"
                         f"{_csfx} [{kind}: {note}] {e.get('mechanism') or ''}")
        lines.append(_context_block(graph, cid))                   # the FULL one-hop context, verbatim
        stable.append("\n".join(lines))

        vlines = [f"--- AS-OF STATE + DATED EVIDENCE for {cid} ---"]
        fired = fired_by.get(cid) or []
        if fired:
            def _receipt(d, b):
                if b.get("kind") == "observed":                    # silver leg: a real as-of-vintage value
                    # T1 intensity clause rides the EXISTING observed receipt, present-key-only ([F1]) --
                    # phrased "consistent with", per the never-fired/active doctrine below; vocabulary is
                    # the fence-safe set only (moderate/strong/extreme/elevated). Flag off -> key absent ->
                    # this string is byte-identical.
                    inten = b.get("intensity")
                    art = "an" if inten and inten[0] in "aeiou" else "a"
                    clause = f", consistent with {art} {inten} anomaly" if inten else ""
                    return (f"{d} (OBSERVED {b.get('value')} {b.get('unit', '')}, z={b.get('z')}{clause}, "
                            f"{b.get('source', '')} {b.get('date', '')})")
                return f"{d} ({b.get('source', '?')}, {b.get('date', '?')})"
            any_obs = any(b.get("kind") == "observed" for r in fired for b in (r.get("basis") or {}).values())
            vlines.append("CONVERGENCE CONDITIONS SUPPORTED NEAR THE AS-OF (OBSERVED = a real observed value "
                          "at the as-of vintage, safe to state as measured; others are textual evidence only):"
                          if any_obs else
                          "CONVERGENCE CONDITIONS DOCUMENTED NEAR THE AS-OF (textual evidence only — NOT "
                          "verified against observed values; no stocks/price/index levels were checked):")
            for r in fired:
                basis = r.get("basis") or {}
                docs = ", ".join(_receipt(d, b) for d, b in basis.items()) or ", ".join(r["matched"])
                vlines.append(f"- {r['name']} ({r['direction']}): documented drivers: {docs} — "
                              f"{len(r['matched'])} of {r['threshold']} required"
                              + (f"; interactions {r['interactions']}" if r["interactions"] else ""))
            vlines.append("INSTRUCTION: never describe a regime as 'fired', 'active', 'armed' or 'confirmed'. "
                          "Say the conditions are CONSISTENT WITH the regime; an OBSERVED receipt may be "
                          "stated as a measured value; for text-only receipts name the observed value "
                          "(e.g. stocks-to-use, the premium level) that would confirm or refute it.")
        veto = (sg.trace.get("silver_veto") or {}).get(cid) or {}
        if veto:
            vlines.append("DRIVERS OBSERVED NORMAL IN THE OBSERVED DATA at the as-of (they did NOT count toward any "
                          "regime; treat documented mentions of them as stale or anticipatory): "
                          + ", ".join(f"{d} ({v.get('value')} {v.get('unit', '')}, z={v.get('z')})"
                                      for d, v in veto.items()))
        elif asof:
            vlines.append("CONVERGENCE: no regime has enough drivers documented near the as-of.")
        else:
            vlines.append("CONVERGENCE: not evaluated (no as-of date to anchor recency); treat the regime "
                          "definitions above as structure, not state.")
        evidenced = [n.id for n in _by(cid) if n.kind == "driver" and n.evidence]
        named_only = [n.id for n in _by(cid) if n.kind == "driver" and n.active and not n.evidence]
        if evidenced:
            vlines.append(f"DRIVERS WITH DATED SLICE EVIDENCE: {evidenced}")
        if named_only:
            vlines.append(f"DRIVERS MERELY NAMED IN PASSING (weak signal — no dedicated evidence): {named_only}")
        for n in _by(cid):                                         # dated evidence + silver, per grounded node
            if n.kind == "contract" and n.evidence:
                vlines.append(f"--- DATED EVIDENCE for {cid} ---\n"
                              + _ev_block(n.evidence, menu, _seen_rows))
            elif n.kind == "driver" and n.evidence:
                # D-MW-30 / 30c: the admission provenance rides the HEADER, never the rows. The flat
                # evidence list _answer_l2 builds (and therefore citations.unify's E-numbering and the
                # verifier's resolution set) is built from `n.evidence` -- these dicts, untouched -- so
                # this string is invisible to every citation seam by construction, not by promise.
                # `provenance` False -> `_sfx` is "" -> the f-string is the pre-wave line, byte for byte.
                _sfx = _admission_note(n) if provenance else ""
                vlines.append(f"--- DATED EVIDENCE for driver {n.id}{_sfx} ---\n"
                              + _ev_block(n.evidence, menu, _seen_rows))
            # R3.4 (D-EI-8): the corroboration floor's SUPPRESSION META, or None when this node's
            # episodes did not come from timeline.episodes_for (a hand-built fixture, a future producer).
            # None and {"n_suppressed": 0} are DIFFERENT facts and are kept different: the first has no
            # suppression to report, the second reports zero -- so a record's suppression keys appear iff
            # a floor actually ran, and every pre-R3 call site is byte-identical.
            _ep_sup = _tl.suppression(n.episodes)
            _ep_cut = int((_ep_sup or {}).get("n_suppressed") or 0)
            _ep_floor = int((_ep_sup or {}).get("floor") or 0)
            if n.episodes:                                         # timeline layer: dated occurrences <= asof
                from leviathan.graphrag import timeline as tl
                _ep_line = tl.render_line(n.id, n.episodes)
                if _ep_cut:
                    # LEG 2 -- PARTIALLY floored. A string append at the SAME seam: the block already
                    # renders, so this needs no new gate and no new paragraph. Without it the floor's
                    # most-cited casualty (black_sea_corridor, six deck rows, [6,5,2,1] -> [6,5,2]) is
                    # silent by construction, and a reader cannot tell "this node has 3 windows" from
                    # "its 4th was thin" -- the same indistinguishability one notch below fully-dark.
                    _ep_line += tl.floor_suffix(_ep_cut, _ep_floor)
                vlines.append(_ep_line)
                # W4-N1 (2026-07-31, adversarial gate): EXPORT what was injected. Until now the rendered
                # episode line lived ONLY in the volatile prompt -- `n.episodes` is never copied into
                # _answer_l2's return dict -- so nothing downstream could tell an ENUMERATED window from a
                # MINTED one. Two graders depended on exactly that and could not have it:
                #   * eval.judge() builds its user block from graph + evidence + numbers + the answer, and
                #     NONE of those is dated inside a receipt-less window (timeline.episodes_for sets
                #     `receipt` only from an in-window evidence prop, so receipt is None <=> the judge is
                #     shown nothing dated there). A correctly enumerated receipt-less episode therefore read
                #     to the judge as an unsupported date claim -- i.e. turning W4 ON raised the
                #     hallucination count BY CONSTRUCTION, on the exact metric the A/B acceptance rule uses,
                #     worst on the honest-thinness rows W4 exists to reward.
                #   * eval's min_episode_lines / episode_magnitude_or_absence could not check a bullet's
                #     window against anything, so three wholly invented windows greened all five episode
                #     pins (the D-4 vacuity exploit).
                # The record rides the EXISTING trace plumbing (`sg.trace` is spread into out['trace'] at
                # _answer_l2's return), so no new return key, no new plumbing, no re-derivation in the judge.
                # `spans` is rendered from the SAME `e['start'][:7]..e['end'][:7]` shape render_line writes,
                # so the scorer compares the model's bullet against the literal string the model was shown.
                # FLAG-OFF: n.episodes is [] on every node (timeline.episodes_for returns [] unless
                # GRAPHRAG_TIMELINE == "on"), so this block never runs and the key never appears.
                # OUTCOMES_JOIN D-OJ-16: `spans` (the `[:7]` MONTH tokens) is what eval._line_targets
                # compares, and it does not change. `windows` is added BESIDE it and carries the
                # DAY-GRAIN pair the same episode was recounted over -- the pair a price move is
                # measured on. The split is the whole of D-OJ-16: MATCHING is month-grain because that
                # is the string the model was shown; MEASUREMENT is day-grain because expanding a
                # `YYYY-MM` end to month-end prices up to 30 days past the as-of. Without both on the
                # record, a correctly-measured bullet and a month-expanded one are indistinguishable
                # downstream. Same order as `spans`, index for index, so a reader can zip them.
                sg.trace.setdefault("episodes_injected", []).append(
                    {"node": n.id, "line": _ep_line,
                     "spans": [tl.month_span(e) for e in n.episodes],
                     "windows": [{"start": tl.day_window(e)[0], "end": tl.day_window(e)[1],
                                  "span": tl.month_span(e), "n": e.get("n")} for e in n.episodes],
                     # R3.4 leg 3: the PAIR, so an eval asserts on {rendered, suppressed} rather than
                     # inferring suppression from a line count that has two causes (a thin node and a
                     # floored one produce the same count). Keys omitted entirely when no floor ran.
                     **(_ep_sup or {})})
            elif _ep_cut:
                # LEG 1 -- FULLY floored: this node HAD windows and every one of them was below the
                # floor. `if n.episodes:` alone injects nothing here, which makes a floored slice
                # byte-identical to a dead artifact for that node -- exactly the I-2 indistinguishability
                # the fences exist to kill. The line carries _tl.LINE_PREFIX so the '## Episodes' persona
                # gate (_episodes_on, which tests that constant in the assembled volatile prompt) still
                # fires and the reader is told the windows were THIN rather than absent.
                _ep_line = _tl.floored_line(n.id, _ep_cut, _ep_floor)
                vlines.append(_ep_line)
                sg.trace.setdefault("episodes_injected", []).append(
                    {"node": n.id, "line": _ep_line, "spans": [], "windows": [],
                     # `floored` is the machine flag eval._injected_episodes' consumers need to tell
                     # "floored" from "never had any": both carry zero spans, and only this key
                     # separates them. spans/windows stay PRESENT-AND-EMPTY so every existing reader
                     # (eval._injected_episodes, eval._judge_episodes_panel, cascade's outcome leg)
                     # iterates nothing instead of meeting a missing key.
                     "floored": True, **(_ep_sup or {})})
            if n.kind == "driver" and n.silver and n.silver.get("live"):
                vlines.append(f"OBSERVED for {n.id}: {n.silver.get('value')} {n.silver.get('unit', '')} "
                              f"[{n.silver.get('knowledge_date', '')}]")
        volatile.append("\n".join(vlines))
    stable.append("NOTE: a driver shared by multiple downstream paths (e.g. one climate pattern feeding several "
                  "drivers) is ONE source of risk — do not weight it once per path.")
    return stable, volatile


def _emit(on_stage, stage: str, **info) -> None:
    """Fire a staged-pipeline progress callback for the granular SSE UI (build-plan P1.1). Best-effort:
    a progress report must NEVER break or slow a turn, so any callback error is swallowed. `on_stage` is
    None on every non-streamed caller (eval harness, POST /v1/respond, tests) -> strict no-op."""
    if on_stage is None:
        return
    try:
        on_stage(stage, info)
    except Exception:  # noqa: BLE001 — progress reporting is cosmetic; it can never fail an answer
        pass


def _emit_chains(on_stage, sg) -> None:
    """F7 `chain`: relay the chain composers' FIRED hop path the moment quantify returns. Both traces are
    DETERMINISTIC engine output (an engine cannot fabricate its own firing), so the event needs no verifier
    reconciliation — unlike the streamed `token` draft. The VERTICAL engine writes sg.trace['quantify_chain']
    with hops:[{node,...}]; the HORIZONTAL transmission composer writes sg.trace['quantify_transmission'] with
    links:[{source,target,...}]. D11 mutual exclusion means at most one fires, but both are read so a future
    relaxation needs no change here. SLUGS ONLY — never a rendered line, never evidence prose (invariant 4).
    Declines (quantify_chain_decline / quantify_transmission_decline) emit NOTHING: an engine that did not
    fire has no hops to show."""
    if on_stage is None:
        return
    try:
        tr = getattr(sg, "trace", None) or {}
        c = tr.get("quantify_chain") or {}
        if c.get("chain_id"):                                      # vertical: hop records, collapsed ones skipped
            hops = [str(h.get("node")) for h in (c.get("hops") or []) if isinstance(h, dict) and h.get("node")]
            _emit(on_stage, "chain", chain_id=str(c["chain_id"]), hops=hops)
        x = tr.get("quantify_transmission") or {}
        if x.get("chain_id"):                                      # horizontal: links -> the source->target path
            hops: list[str] = []
            for lk in (x.get("links") or []):
                if not isinstance(lk, dict):
                    continue
                for side in ("source", "target"):
                    v = lk.get(side)
                    if v and (not hops or hops[-1] != str(v)):     # dedup the shared node between two links
                        hops.append(str(v))
            _emit(on_stage, "chain", chain_id=str(x["chain_id"]), hops=hops)
    except Exception:  # noqa: BLE001 — a malformed trace can never fail an answer (invariant 1)
        pass


def _answer_l2(query: str, graph: gph.CausalGraph, *, model, asof, near, call, retrieve, routed,
               extra_context: str | None = None, extra_number_calls: list | None = None,
               extra_resolver=None, focus_driver: str | None = None, use_blocks: bool = False,
               silver_lookup=None, on_stage=None, numbers_lookup=None, xc_request: dict | None = None,
               outlook: bool = False, response_contract: str | None = None,
               mode_knobs: dict | None = None) -> dict:
    """L2 serving path: walk + ground the subgraph, hand it to the reasoner, and OVERRIDE the diagram with the
    graph-derived cascade. Reuses the shared render + unified footer + sanitizer. The hybrid branch's silver
    numbers ride in exactly as on the one-hop path: extra_context as a prompt block, extra_number_calls into
    the unified footer. `focus_driver` (the live-event cascade root, section 7.1) is force-included in the
    subgraph so the cascade is grounded from the event even when the walk wouldn't have kept it.
    `use_blocks` (real serving call only) sends (stable, volatile) for prompt-cached content blocks.

    `mode_knobs` (D-AM-10) is the reasoning mode's RESOLVED knob dict, threaded down as ONE argument
    (this body reads no environment for it). Empty/None on every standard and every dark turn, and
    every consumer below uses the omit-when-empty idiom -- so the walk call, the ground call, the
    retrieval partial, the persona and the scaffold seam are BYTE-IDENTICAL unless a mode is honored."""
    from leviathan.graphrag import planner as pl
    # D-AM-10 retrieval width: rebound PER CALL on the local partial (never a module-global mutation),
    # so concurrent turns on different modes cannot see each other's fetch_k. Absent -> the kwarg is
    # not passed at all -> ev.retrieve's own _FETCH_K default, exactly as before.
    _fk = {"fetch_k": mode_knobs["fetch_k"]} if (mode_knobs or {}).get("fetch_k") else {}
    retr = retrieve or functools.partial(ev.retrieve, **_RETRIEVAL, **_fk)
    # D-GD-1 R1 #5: `focus_driver` rides INTO the walk purely as a displacement fence -- the cascade-closure
    # reservation may not evict the node this very function re-injects below, or the ON arm alone would end
    # the turn one node OVER the ceiling. Observational to scoring/admission/budget, and a strict no-op when
    # the reservation is off. OMIT-WHEN-EMPTY, like `_fk` above and every other threaded seam here: on a
    # turn with no live-event root the walk call is BYTE-IDENTICAL, carrying route_fn and nothing else
    # (test_dam_modes.test_walk_and_ground_kwargs_are_untouched_on_standard_and_dark is that pin).
    _fd = {"focus_driver": focus_driver} if focus_driver else {}
    sg = pl.grounded_subgraph(query, graph, route_fn=lambda q, g: routed, **_fd,
                              **_rm.walk_kwargs(mode_knobs))
    if focus_driver and not any(n.kind == "driver" and n.id == focus_driver for n in sg.nodes):
        for cid in sg.seeds:                                       # first seed contract that carries the driver
            if any(d.id == focus_driver for d in graph.contracts[cid].drivers):
                node = pl.GroundedNode(kind="driver", id=focus_driver, contract=cid, depth=1, relevance=1.0)
                node.prior = pl._prior(graph, node)
                # D-GD-1: the third admission reason. This inject is the PRECEDENT the cascade-closure
                # reservation was built from -- it force-admits post-walk with no budget accounted for --
                # so it must be readable as its own reason and never counted as a closure admission.
                node.admission = {"reason": "focus_driver", "ancestor_of": None, "chain_depth": 0}
                sg.nodes.append(node)
                sg.trace.setdefault("kept", []).append(list(node.key))
                sg.trace["focus_driver"] = focus_driver
                _cc = sg.trace.get("cascade_closure")          # D-GD-1: keep the admissions map TOTAL over
                if isinstance(_cc, dict):                      # sg.nodes -- a post-walk inject included
                    (_cc.setdefault("admissions", {}))[":".join(str(p) for p in node.key)] = node.admission
                break
    # F7 `walk`: the subgraph EXISTS now — shape (node count + reach) is decided BEFORE ground() spends its
    # 8-20s on evidence + probes, so this lands far earlier than the `walking` completion tick below.
    # The payload is built INSIDE the None guard, never as an eager kwarg: invariant 2 makes on_stage=None a
    # STRICT no-op, and _emit can only swallow what happens after it is CALLED — argument expressions are
    # evaluated before that. (test_reroute_v2_engine's _FakeNode, which has no .depth, catches exactly this.)
    if on_stage is not None:
        _emit(on_stage, "walk", nodes=len(sg.nodes),
              depth=max((int(getattr(n, "depth", 0) or 0) for n in sg.nodes), default=0))
    probe_retr = None if retrieve else functools.partial(ev.retrieve, mode="hybrid", rerank=False)
    _emit(on_stage, "walking")                                    # early tick: the 8-20s ground starts NOW (5.6 W5)
    # D-MW-13: the ground caps are SEED-SCALED now, so they are produced from the REALIZED seed count --
    # `sg.seeds`, the walk's own output, NOT trace.walk_shape's n_seeds (reading the trace would couple
    # this seam to the order in which the walk stamps its keys). `scaled_ground_kwargs` is the ONE
    # producer of that arithmetic and its clamps; this call site multiplies nothing. On every preset
    # without per-seed fields it returns exactly `ground_kwargs(mode_knobs)`, so standard/quick/deep/
    # deep_v2 stay byte-identical here by construction (test_dam_modes' passthrough pins).
    _n_seeds = len(getattr(sg, "seeds", None) or [])
    pl.ground(sg, query, graph, retrieve=retr, silver_lookup=silver_lookup, asof=asof, near=near,
              probe_retrieve=probe_retr, on_stage=on_stage,       # probes = cheap existence checks, no reranker
              **_rm.scaled_ground_kwargs(mode_knobs, n_seeds=_n_seeds))   # D-AM-10: {} unless a mode is honored
    _gm = sg.trace.get("ground_ms") or {}
    _emit(on_stage, "walking", nodes=len(sg.nodes), regimes=len(sg.fired_regimes),
          ms_fill=_gm.get("fill"), ms_rest=_gm.get("rest"))
    _emit(on_stage, "retrieving", props=int(sg.trace.get("n_evidence", 0) or 0))
    contracts = sg.seeds
    # D-DV-2 presentation order, resolved ONCE and consumed by BOTH the render below and the flat
    # evidence list further down -- two derivations of the same sequence is how they drift apart.
    _ev_order = _render_order(sg.nodes, (mode_knobs or {}).get("order_policy"))
    # D-MW-30 / 30c: the provenance bundle's ONE resolution, read from the mode knob HERE and threaded to
    # BOTH of its seams -- the evidence header below and the persona at the synthesis call. `bool(...)` of
    # an absent key is False on every other preset (the knob is None, never False -- reasoning_modes' F7
    # note), so both seams take their default and this whole lever has a provable off state.
    _provenance = bool((mode_knobs or {}).get("provenance_prompt"))
    # D-HP-7/8/9/12 (H1): THE TREATMENT BUNDLE'S ONE RESOLUTION, read from the mode knob HERE and threaded
    # to ALL FOUR of its seams -- the persona (`_system(handles=)`), the tool schema
    # (`_answer_tool(handles=)`), the verifier's charge + positional [E] resolution
    # (`verify_citations(handle_prose=)`), and the render passes below. B8's bundle rule is that they
    # cannot disagree, and ONE local read once is how that is guaranteed rather than promised. False on
    # every non-`_hp` preset AND on both rollback lanes (`_handle_prose_active`), so the whole grammar has
    # a provable off state at every seam it touches.
    _handles = _handle_prose_active(mode_knobs)
    # ══ D-HP-1 (H0) -- THE HOIST: ONE LIST, ONE NUMBERING, THREE CONSUMERS ════════════════════════════
    # THE DEFECT (recon 2 s2): three independent numberings that coincided only by luck.
    #   PROMPT ORDER   -- `_l2_blocks` regroups by contract and emits `_ev_block(n.evidence)` per node.
    #   VERIFIER ORDER -- the FLAT list `[{**h, "contract": n.contract} for n in _ev_order for h in
    #                     n.evidence]`, NOT contract-regrouped, is what `verify_citations` received.
    #   CITATION ORDER -- `uniq` (deduped by source_key) is what `cit.unify` stamps `E{i}` onto,
    #                     positionally (citations.py:1003-1021).
    # `sg.nodes` is BFS-WAVE ordered, so on any multi-seed or cross-hop walk it is NOT contract-contiguous,
    # and render order and E order disagree whenever `order_policy` is None -- i.e. on EVERY standard and
    # quick turn. `_render_order`'s own docstring says the two "cannot be allowed to disagree".
    # THE FIX: build `evidence`/`uniq` HERE, BEFORE the render, and give all three consumers the same list.
    #   (i)   `uniq` is the ONLY thing the menu renders, numbered by its 1-based GLOBAL ordinal (D-HP-2).
    #   (ii)  `uniq` is the argument to `cit.unify` below -- unchanged.
    #   (iii) `uniq` is the `evidence` argument to `verify_citations` -- CHANGED from the non-deduped list.
    #         `[E{i}]` means `uniq[i-1]` in all three places, which the draft never said.
    # THIS IS A PROMPT-CONTENT CHANGE, NOT A PURE REORDERING (review G8): dedup by `source_key` REDUCES the
    # [E] rows the model sees. TWO BINDING CONSEQUENCES, both recorded in D-HP-21:
    #   * the per-driver BLOCK STRUCTURE is preserved (the D-MW-30 admission-provenance header has nowhere
    #     else to live and D-HP-25 lever (ii) rides it) -- see `_ev_block`'s cross-reference row;
    #   * NO STORED PRE-HOIST ARTIFACT IS A CONTROL. Every control arm re-runs on the post-H0 image.
    _evidence = [{**h, "contract": n.contract} for n in _ev_order for h in n.evidence]
    _uniq = _uniq_evidence(_evidence)
    # D-HP-16 (H0 review): THE DOSSIER SUB-ANSWER LANE DOES NOT GET THE MENU YET. `dossier.run_subquery`
    # runs each sub-question as a NORMAL turn through respond() -> here, so without this gate the dense
    # numbered menu -- the single strongest nudge toward multi-citation GROUPING -- lands on the one lane
    # whose output-side fix is sequenced AFTER G1+G2: `dossier._HANDLE_RX` (dossier.py:95) does not match
    # a grouped token at all, so `remap_body` neither remaps nor drops it and a stale LOCAL index reaches
    # a DELIVERED document inside the GLOBAL namespace -- the plan's own "worst outcome in this wave".
    # Raising the input density before the output fix is exactly the ordering D-HP-28 forbids, so the
    # lane is held on the pre-D-HP prompt by the SAME boundary the plan already gates its grammar at
    # (`run_subquery` pins the control preset; `allow_shape_escalation=False` rides the same call).
    _menu_on = _handle_menu_on()
    _ev_menu = _evidence_menu(_uniq) if _menu_on else None
    stable_blocks, volatile_blocks = _l2_blocks(sg, graph, asof=asof, order=_ev_order,
                                                provenance=_provenance, menu=_ev_menu)
    if extra_resolver is not None:                                # numbers ∥ walk JOIN (run_hybrid): the walk is
        extra_context, extra_number_calls = extra_resolver()      # done — collect the numbers thread's output now
    if extra_context:                                             # hybrid numbers / conversation state (volatile)
        volatile_blocks = volatile_blocks + [extra_context]
    # W5-D3/D5: the outlook legs were resolved by the CALLER (plan.answer_mode_outlook AND
    # is_outlook_explicit); the kill-switch is ANDed HERE. Resolved BEFORE the cascade seam because the R9
    # context lane needs it: D1 admits the positioning leg under FENCED only ("do NOT proceed on the
    # outlook lane"), so `_outlook` is threaded into quantify() as well as selecting the register below.
    # ONE resolution, read twice -- the gate and the register can never disagree about which lane a turn is.
    _outlook = bool(outlook) and _outlook_on()
    # P9-B quantified cascade (GRAPHRAG_CASCADE_QUANT): derive analogue-era windows from the walk's dated
    # props, fetch the metric at the era window AND the session asof, inject citable [N] rows into the
    # VOLATILE tail (cache-safe). BREAKER: if the pg numbers backend is not live, SKIP the cascade rather
    # than fan 6-12 Athena windows onto the serve path -- pg-down => qualitative mentor answer.
    if (numbers_lookup is not None and os.environ.get("GRAPHRAG_CASCADE_QUANT", "on") != "off"
            and _pgnumbers_live()):
        from leviathan.graphrag.numbers import cascade as cq
        extra_number_calls = list(extra_number_calls or [])       # rebind ONCE: None -> [], hybrid list -> copy
        # SEAM B (F2 price leg): the flag is read HERE and the focus contract (the first seed, focus-first) is
        # packed into price_request; the engine is gated by that ARGUMENT ([F3]). Flag off -> None -> quantify
        # byte-identical. The _farm_wasde map gates non-farm focuses, so a coffee/meal seed declines honestly.
        _price_request = None
        if _price_leg_on():
            _focus = next((c for c in (getattr(sg, "seeds", None) or []) if c in graph.contracts), None)
            if _focus:
                _price_request = {"focus_contract": _focus}
        try:                                                      # GRACEFUL (R6): a raise here must NEVER 500
            _t_quant = time.perf_counter()                        # W6.1-0 stage timer (MsQuantify)
            # ── OPEN-TARGET RESOLUTION (D-XT, owner directive 2, 2026-08-29) ─────────────────────────
            # The orchestrator DETECTED the ask; SOURCE and the PAIR are bound HERE, the first point in
            # the turn where the walk exists. Gated by the ARGUMENT (`defer`) exactly like price_request
            # -- this module reads NO env for it. INSIDE the quantify try (M7) AND in its own belt (P21:
            # a resolver failure must degrade to "no fork", never lose the whole quantify block). A
            # DECLINE rebinds xc_request to None, so quantify sees exactly what a no-ask turn sees.
            if isinstance(xc_request, dict) and xc_request.get("defer") == "walk":
                try:
                    xc_request, _xc_open_dec = cq.resolve_xc_open(xc_request, sg, graph)
                except Exception:  # noqa: BLE001 -- P21: the fork dies, the quantify block survives
                    xc_request, _xc_open_dec = None, {"reason": "error"}
                if xc_request and xc_request.get("xc_open_rank"):
                    try:
                        sg.trace["xc_open_pair"] = xc_request["xc_open_rank"]
                    except Exception:  # noqa: BLE001 -- a traceless sg must never break the v1 answer
                        pass
                elif _xc_open_dec:
                    try:
                        sg.trace["xc_open_decline"] = _xc_open_dec       # ONE shape, always a dict
                    except Exception:  # noqa: BLE001
                        pass
            # T2a: the pace kwarg is OMITTED when the flag is off (the orchestrator `_xc` omit-when-None
            # idiom) -- the flag-off call is byte-identical to rev 52, and injected quantify fakes with the
            # older signature stay valid.
            _pace_kw = {"pace": True} if _pace_leg_on() else {}
            # CHAIN engine (multi-hop): the omit-when-off idiom too -- flag off -> kwarg ABSENT -> byte-identical.
            _chain_kw = {"chain": True} if _chain_on() else {}
            # HORIZONTAL transmission chain: the same omit-when-off idiom. The engine ALSO needs the RV2
            # detector's own xc_request (threaded above) to fire at all -- flag on + no cross-commodity ask =
            # no attempt, so the fork is never volunteered.
            _xmit_kw = {"transmission": True} if _transmission_on() else {}
            # A2b headline rule: same omit-when-off idiom, so the flag-off call is byte-identical and an
            # injected quantify fake with the older signature stays valid.
            _hl_kw = {"headline": True} if _headline_on() else {}
            # R4 PRICE-CONTEXT LANE (the Option C amendment, 2026-08-26), the per-turn half: is this
            # turn's asof HISTORICAL? The pink sheet is latest-only with retroactive WB revisions, so at
            # a historical asof a price-context leg would serve today's revision as if it were known
            # then (the archaeology's C-2 replay vector) -- quantify's belt keeps those nodes
            # qualitative on any replay turn. The date compare happens HERE, once, as a UTC date: the
            # ENGINE reads no clock and no env (SKEPTIC F3), this seam may. A pinned historical asof
            # (evals, backtests, PIT repros) resolves True on every re-run -- deterministic by
            # construction; a live turn's asof is today and resolves False. Same omit-when-off idiom.
            from datetime import datetime as _dtn, timezone as _tzu
            # A MISSING asof is NOT a historical one: `"" < today` is True, so an unguarded compare armed the
            # replay belt on every asof-less direct call (eval's non-orchestrator path, tests). The
            # orchestrator defaults asof to today before it reaches here; this seam now needs a REAL date
            # (pink v3 refute, 2026-09-03). Same omit-when-off idiom.
            _pr_kw = ({"price_replay": True}
                      if asof and str(asof)[:10] < _dtn.now(_tzu.utc).date().isoformat() else {})
            # R9 CONTEXT LANE (D1): the already-resolved outlook bool goes DOWN as an argument. Omitted on
            # a fenced turn -> byte-identical call.
            _ol_kw = {"outlook": True} if _outlook else {}
            # OUTCOMES_JOIN J4/J6: the same omit-when-off idiom, for the same two reasons -- the flag-off
            # call is byte-identical (item 108's measurement, for free), and an injected quantify fake
            # with the older signature stays valid. The episode leg reads windows out of
            # `sg.trace['episodes_injected']`, which _l2_blocks stamped ABOVE this seam, so no window is
            # cached anywhere and a rebuilt artifact changes what is priced on the very next turn.
            _epo_kw = {"episode_outcomes": True} if _episode_outcomes_on() else {}
            _cto_kw = {"cot_outcomes": True} if _cot_outcomes_on() else {}
            # FUTURES_READPATH S1 canary (D-FR-10): the SAME omit-when-off idiom, and it earns it twice
            # over. The kwarg absent -> quantify compiles the pre-wave ASC total order on every leg, so
            # the flag-off turn is byte-identical by construction rather than by promise; and an injected
            # quantify fake written against the older signature stays valid, which is how every cascade
            # fixture in the suites is built. This is the turn's ONE read of the env for this flag -- it
            # then rides down as an argument, so no engine under this seam can disagree about it.
            # D-AM-18: the value is the SCOPE token, not a bare True -- False / True (futures) / "all"
            # (estate-wide). Both env seams are read HERE, once, and folded by `_newest_first_scope`.
            _nf_scope = _newest_first_scope(_futures_newest_first_on(), _series_newest_first_on())
            _fnf_kw = {"futures_newest_first": _nf_scope} if _nf_scope else {}
            # RV-READING: the same omit-when-off idiom -- flag off -> kwarg ABSENT -> byte-identical, and
            # injected quantify fakes with the older signature stay valid. The replay belt is _pr_kw's,
            # threaded inside quantify to the reading leg unchanged.
            _rv_kw = {"rv_reading": True} if _rv_reading_on() else {}
            # RV-REGIONAL: same omit-when-off idiom; the D13 dependency on _rv_reading_on is declared
            # in _rv_regional_on's docstring and stamped by the engine as reading_flag_off.
            _rvr_kw = {"rv_regional": True} if _rv_regional_on() else {}
            # D-DA: same omit-when-off idiom (the _rv_reading_on precedent, third application) --
            # flag off -> kwarg ABSENT -> quantify byte-identical, older-signature fakes stay valid.
            _dv_kw = {"derived_arith": True} if _derived_arith_on() else {}
            # CASCADE EPISODE WALK: same omit-when-off idiom. The ROOT is the turn's focus
            # contract, resolved HERE with the price_request focus-first idiom and packed as an
            # ARGUMENT -- the engine reads no env and resolves no focus of its own.
            _cw_kw = {}
            if _cascade_walk_on():
                _cw_focus = next((c for c in (getattr(sg, "seeds", None) or [])
                                  if c in graph.contracts), None)
                if _cw_focus:
                    _cw_req = {"focus_contract": _cw_focus}
                    if _cascade_context_on():
                        # V2-1 CONTEXT CELL (rider): two keys, present ONLY under its own flag -- the
                        # walk request is byte-identical with the flag off. `replay` is the SAME
                        # already-resolved historical-asof bool (_pr_kw, above); the ENGINE counts the
                        # decline, this seam never silences it.
                        _cw_req["context"] = True
                        if _pr_kw:
                            _cw_req["replay"] = True
                    # V2-5 DEEPER/WIDER (rider): ONE key, present only under its OWN flag, set at
                    # `if _cw_focus:` scope and NOT inside the context branch above -- deep must fire
                    # with GRAPHRAG_CASCADE_CONTEXT off, which is its prod state. This seam never
                    # writes V2-3's `xccy` (pinned), so the engine's union regime is inert here.
                    if _cascade_deep_on():
                        _cw_req["deep"] = True
                    _cw_kw = {"cascade_walk": _cw_req}
            _cblock, _quant_trace, _reroute_trace = cq.quantify(sg, graph, qfn=numbers_lookup, asof=asof,
                                                                near=near,
                                                                extra_number_calls=extra_number_calls,
                                                                xc_request=xc_request, comove=_comove_on(),
                                                                price_request=_price_request,
                                                                **_pace_kw, **_chain_kw, **_xmit_kw,
                                                                **_hl_kw, **_ol_kw, **_epo_kw, **_cto_kw,
                                                                **_fnf_kw, **_pr_kw, **_rv_kw, **_rvr_kw,
                                                                **_dv_kw, **_cw_kw)
            sg.trace["ms_quantify"] = int((time.perf_counter() - _t_quant) * 1000)
            _emit_chains(on_stage, sg)                            # F7 `chain`: the composer has just decided
            if _cblock:
                volatile_blocks = volatile_blocks + [_cblock]
            if _quant_trace:
                sg.trace["quantify"] = _quant_trace
            if _reroute_trace:                                    # RF-4: FIRED cross-country pairs only
                sg.trace["quantify_reroute"] = _reroute_trace
        except Exception as e:  # noqa: BLE001 -- degrade to the QUALITATIVE mentor answer, never the floor
            import logging
            logging.getLogger(__name__).warning("cascade quantify failed (%s: %s); proceeding qualitative",
                                                type(e).__name__, str(e)[:160])
            sg.trace["quantify_error"] = type(e).__name__
    # Clause A' (thin-turn honesty fix): a per-turn GROUNDING LEDGER line enumerating the EXACT valid handle
    # ranges for this turn, so the model cannot mint an [E]/[N] handle beyond what the engine actually holds.
    # Stays in the VOLATILE tail (never the cached constant) so the cache prefix is unchanged.
    # D-HP-1, ALSO CORRECTED BY THE SAME HOIST: `n_ev` WAS "a PRE-dedup overcount of graph-node evidence
    # ... a loose cap that can never SUPPRESS a legit [E], only forbid an invented one". Post-hoist it is
    # EXACT -- `len(_uniq)` is literally the row count the menu rendered and the only set `unify` and the
    # verifier will resolve against, so the cap is now the truth rather than an upper bound. ON THE
    # MENU-OFF LANE IT IS THE PRE-DEDUP OVERCOUNT AGAIN, deliberately: nothing rendered a numbered row
    # there, so the honest statement is the loose cap the pre-D-HP prompt made.
    # D-HP-2, THE LEDGER LINE: the [E] clause becomes a RANGE, symmetric with [N]. The shipped asymmetry
    # was visible in one sentence -- [N] got a range, [E] got a count -- and a count is not addressable.
    # THE RANGE RIDES THE MENU AND CANNOT OUTLIVE IT (D-HP-16, H0 review): "each mapping to the item
    # tagged with it above" is a claim ABOUT THE RENDERED ROWS, so on the menu-off lane the ledger reverts
    # to its pre-D-HP sentence AND to its pre-D-HP PRE-DEDUP count, byte for byte -- a lane that renders
    # unnumbered rows must not be told its handles are addresses. `n_ev` also feeds the composition
    # census below, so the whole prompt (menu, ledger, mandates) is pre-D-HP on that lane, not just the
    # rows.
    n_ev = (len(_uniq) if _menu_on
            else sum(len(getattr(n, "evidence", []) or []) for n in sg.nodes))
    n_num = len(extra_number_calls or [])
    sg.trace["injected_n"] = n_num                               # W6.1-0: [N] rows injected (cited-vs-injected denom)
    # PA-8(b): the ledger states SERVED ROWS and names the lookups separately -- `n_num` still governs the
    # [N] handle range (one indexed citation per call) and still stamps `injected_n`, so no counter and no
    # address moves. `n_srv` is a pure sum over the same `rows` lists the panel renders.
    n_srv = _served_rows(extra_number_calls)
    sg.trace["served_rows"] = n_srv                              # PA-8: rows behind the [N] lines, per turn
    _ledger_line = _grounding_ledger(n_ev, n_num, menu_on=_menu_on, n_rows=n_srv)
    # D-RC-13: the record's EDGE, stamped observationally (trace, unconditional -- the fork_basis
    # scoped-promise precedent) and stated to the model only when the flag is on (the suffix is ''
    # otherwise, so the ledger line is byte-identical flag-off).
    _rec_through = _record_through([h for n in sg.nodes for h in (getattr(n, "evidence", None) or [])])
    sg.trace["record_through"] = _rec_through
    _ledger_line += _recency_ledger_suffix(_rec_through)
    volatile_blocks = volatile_blocks + [_ledger_line]
    sp, vp = _prompt_parts(query, contracts, stable_blocks, volatile_blocks)
    # Stream the note when the caller wired an SSE progress channel (real serving call only; injected fakes
    # keep the plain signature). The verifier still runs on the FINAL structured output below, so streaming is
    # additive UX — the trust contract is unchanged.
    on_token = (lambda t: _emit(on_stage, "token", text=t)) if on_stage is not None else None
    # H1 FIX Z10: on the TREATMENT lane the tool schema carries a `plan` property that is generated FIRST,
    # so the relay would deliver the model's private, unverified scratchpad to the browser before anything
    # ran on it. Wrapped only when the region can exist, so the CONTROL arm's relay is the same lambda it
    # has always been -- byte-identical, not merely equivalent.
    if _handles:
        on_token = _plan_filtered_token_relay(on_token)
    call_kw = {"on_token": on_token} if (on_token is not None and call is _call_opus) else {}
    # Q-0 EFFORT KNOB: threaded ONLY on the real path (injected fakes keep their plain signatures --
    # the on_token guard's own rule) and only when the honored preset minted the key; absent -> the
    # env seam inside _call_opus decides, byte-identical to before this knob existed.
    if (mode_knobs or {}).get("synth_effort") and call is _call_opus:
        call_kw["effort"] = mode_knobs["synth_effort"]
    _emit(on_stage, "synthesizing")                               # prompt assembled; the model call starts NOW
    _emit(on_stage, "drafting")                                   # F7: the engine feed is CLOSED — prose mode
    _t_synth = time.perf_counter()                                # W6.1-0 stage timer (MsSynthLLM)
    # W5-D3/D5: `_outlook` was resolved ONCE at the cascade seam above (the R9 context lane reads the same
    # bool -- D1 fences the positioning leg out of the outlook lane, so the gate and the register must be
    # the same decision). `_mr` is the ONLY thing that ever relaxes the register, and it is passed DOWN as
    # an argument -- register.py reads no environment.
    _mr = reg.OUTLOOK if _outlook else reg.FENCED
    # D-RC Phase B: the caller's selection re-ANDed with the allowlist AT THE SEAM (the _outlook_on
    # idiom) -- env-flip rollback live per turn, no redeploy. None -> default -> zero rewrite.
    _rc_active = response_contract if response_contract in _response_contracts_enabled() else None
    # D-RC-11: the relevance bool is resolved ONCE and consumed by BOTH producers (the persona AND below
    # the scaffold seam) -- gating only one of the two inverse decision points inverts the outcome.
    # When a contract is ACTIVE its episodes license is the ONE authority (the interim lexical gate
    # stands down for the turn -- one gate, never two); Phase D retires the interim entirely.
    _ep_rel = _rc.licenses_episodes(_rc_active) if _rc_active else _episodes_relevant(query)
    _episodes = _episodes_on(vp) and _ep_rel                      # W4-D3: BOTH legs, and both in CODE
    if _rc_active:                                                # pre-model stamp (circularity fence);
        sg.trace["response_contract"] = _rc_active                # absent when inactive -- OFF-arm clean
    # D-CC-1: the composition census. Both legs in CODE and both HERE -- the kill-switch AND an active
    # contract -- because the mandates ride the contract's own directive and a census on a turn with no
    # contract could shape nothing anyway. `n_ev` is the same post-cap node-evidence count the GROUNDING
    # LEDGER states above, so the number the mandate reasons about is the number the model was told it
    # holds. None (either leg off) -> _system's two contract seams are byte-identical.
    # The contract argument is the RENDERED set (`sorted({n.contract for n in sg.nodes})`), not
    # sg.seeds -- the same expression, and the same reason, as the verifier's foreign_names below
    # (D-DV-1c): _l2_blocks renders a context + evidence block for EVERY walk contract, hops included,
    # so seeds-only would census a strict subset of what the model was shown. The census law is "bind
    # to what the turn WAS SHOWN"; on this body that phrase has one correct spelling and it is this one.
    _census = (_composition_census(contracts=sorted({n.contract for n in sg.nodes}),
                                   number_calls=extra_number_calls, trace=sg.trace, n_evidence=n_ev)
               if (_rc_active and _composition_census_on()) else None)
    if _census is not None:
        sg.trace["composition_census"] = _census                  # absent when inactive -- OFF-arm clean
    # D-DT-2 c1: the license inventory is minted HERE, BEFORE the model call, in both serving bodies. The
    # position IS the circularity fence (V.4 X3): every flag reads engine inputs assembled before
    # synthesis, and at this line no answer prose exists to read -- so the check can never become
    # "heading => licensed => pass". It is stamped UNCONDITIONALLY (observational by design, no flag), so
    # the census accrues on both arms of D-DT-1's A/B for free.
    sg.trace["fork_basis"] = _fork_basis(graph, contracts,
                                         [h for n in sg.nodes for h in (getattr(n, "evidence", None) or [])],
                                         sg.trace)
    structured = call(_system(outlook=_outlook, episodes=_episodes, recency=_recency_stamp_on(),
                              cascade_walk=_cascade_walk_block_on(vp),
                              cascade_context=_cascade_context_block_on(vp),
                              cascade_deep=_cascade_deep_block_on(vp),
                              response_contract=_rc_active, budget=_mode_budget(_rc_active, mode_knobs),
                              census=_census,                     # D-CC-1: None on every dark turn
                              provenance=_provenance,             # D-MW-30: False on every non-esc_r turn
                              handles=_handles),                  # D-HP-7/8: False on every non-_hp turn
                      _pack(sp, vp, use_blocks), model=model,
                      tool=_answer_tool(handles=_handles), **call_kw)   # D-HP-7/9: `plan` in, `sources` out
    sg.trace["ms_synth_llm"] = int((time.perf_counter() - _t_synth) * 1000)
    _banned_mood = _count_banned_mood(structured)                 # P9-A: RAW output, pre-sanitize (see helper)
    _banned_val = _count_banned_valuation(structured)             # DP-6: valuation/flow raw counts, pre-sanitize
    _banned_flow = _count_banned_flow(structured)
    _banned_exec = _count_banned_exec(structured)                 # W5: A2 execution idioms, RAW (pinned 0 always)
    _unbacked = _count_unbacked_levels(structured)                # W5.0: bare price levels, RAW (derivation gate)
    _bare_digits = _count_bare_digits(structured)                 # D-HP-4(c): the digit-lint ESCAPE COUNTER
    # A4: the counters above are computed HERE and the draft they were computed on is destroyed BELOW --
    # verify_citations mutates `structured` in place, _humanize_structured rewrites it, sanitize cleans the
    # render. Snapshot it while it still exists (flag-gated; None -> the key is absent, not null).
    _raw_draft = raw_draft_snapshot(tldr=structured.get("tldr"), mechanism=structured.get("mechanism"))
    degraded = _pop_degraded(structured)
    _synth_usage = _pop_usage(structured)                         # D-AM-4: same pop channel, both bodies
    # D-HP-7 ORDERING PIN (c), the one D-HP-6 could not write at H0: the PLANNING REGION is lifted off
    # `structured` HERE -- same pop channel, and BEFORE `verify_citations` -- so `claim_count` (the
    # strip-rate denominator every D-HP-17 successor divides by) is byte-identical with and without a
    # plan, the digit-lint never charges the model's scratchpad, and no fidelity rung of
    # `render_answer_for_judge` can serve unrendered reasoning as an answer. Dropped on the floor by
    # design: a trace key would put the model's private reasoning into a stored artifact the judge, the
    # adjudicators and the FE all read.
    # D-HP G1 AMENDMENT A3: the TEXT is still dropped on the floor, exactly as above. Only its SIZE is
    # kept, and only as a scalar -- see `_plan_tokens` for the restated privacy reason and the method.
    _plan_tok = _plan_tokens(_pop_plan(structured))
    if sg.mermaid and _valid_mermaid(sg.mermaid):
        structured["diagram_mermaid"] = sg.mermaid                # deterministic diagram overrides the LLM's
    # D-HP-1: `evidence` / `uniq` were BUILT HERE and are now built BEFORE `_l2_blocks` (see the hoist
    # above). These two names are kept so the rest of this body reads unchanged; nothing is re-derived.
    evidence, uniq = _evidence, _uniq
    ev_cits = cit.unify(uniq, extra_number_calls)                 # machine-readable list (UI drill-down)
    from leviathan.graphrag import verify as vf
    # D-DV-1c: the RENDERED contract set, not sg.seeds. _l2_blocks builds a context block for EVERY walk
    # contract including cross-commodity hops, so a hop's regime names are SHOWN to the model as legitimate
    # structure -- and were then stripped on sight as "foreign". A latent bug that deep (3 seeds + tracked
    # hops) amplifies. `contracts` stays sg.seeds everywhere else: that is the ANSWER's scope, not the
    # prompt's.
    # CYCLE-9 (2026-08-08) FIX 4, BOUNDARY 1 -- see the note at the post-verify capture below.
    _raw_draft = _fold_draft(_raw_draft, raw_draft_snapshot(
        preverify_tldr=structured.get("tldr"), preverify_mechanism=structured.get("mechanism")))
    # D-HP-1 (iii): the verifier resolves against `uniq`, NOT the pre-dedup flat list. `[E{i}]` means
    # `uniq[i-1]` in all three places -- the rendered menu, `cit.unify`'s numbering, and here. Passing the
    # non-deduped list let the verifier resolve a handle against a row the model was never shown under
    # that ordinal, which is the wrong-slot class D-HP-14 exists to make auditable.
    verifier = vf.verify_citations(structured, uniq, extra_number_calls,
                                   foreign_names=_foreign_regime_names(
                                       graph, sorted({n.contract for n in sg.nodes})),
                                   handle_prose=_handles)         # D-HP-9/12: the SAME one resolution
    # ══ CYCLE-9 (2026-08-08) FIX 4 -- THE MISSING ATTRIBUTION BOUNDARY, ADDITIVE ONLY ═══════════════
    # The gate-6 adjudicator (p4.py) could not attribute a draft-vs-page numeral diff to the repair path:
    # `raw_draft` is captured at the top of this function and the next capture (`verified_*`) is taken
    # AFTER `_resolve_number_handles`, so verify's rewrites and the number-handle pass's value SPLICES
    # land inside ONE interval. Ten surviving-sentence mutations were detected across the six gate-6 runs
    # against two recorded repair ops, and the other eight could not be named -- they read as laundering
    # candidates when most were the handle pass doing its job (`ab_cmp_vegoils` "read 6.10212 %" is a
    # splice, not a repair). Two SHORT snapshots close the interval, and the passes become separable:
    #     raw_draft -> preverify_*        nothing may change (the counters' draft)
    #     preverify_* -> postverify_*     verify_citations ALONE (strips + repairs)
    #     postverify_* -> verified_*      the [N]/[E] handle passes (splice, drop, sever, prune, tidy)
    #     verified_* -> body_pre_sanitize humanize + scaffold + render
    #     body_pre_sanitize -> body       the render-seam sanitize
    # Same flag, same absent-when-off contract, same two short prose fields as `raw_draft` itself: no new
    # switch, no new cost class, and every existing key is byte-identical.
    _raw_draft = _fold_draft(_raw_draft, raw_draft_snapshot(
        postverify_tldr=structured.get("tldr"), postverify_mechanism=structured.get("mechanism")))
    _emit(on_stage, "verifying", checked=int(verifier.get("checked", 0) or 0),
          stripped=int(verifier.get("stripped", 0) or 0))
    # F7 `verified`: the verifier is DONE, so the streamed draft's citation handles are now reconcilable —
    # this is the ONLY signal that permits the UI to ACTIVATE them (RCA F7c: the `token` draft is
    # PRE-verifier, and strips run p50 1 / p90 7 / max 16, so a handle activated earlier could disappear).
    _emit(on_stage, "verified", strips=int(verifier.get("stripped", 0) or 0))
    # D-HP-9 / R1(b): the ledger is re-minted FROM `resolved` HERE -- after verify returns, before
    # provenance stamps. OFF-arm-clean: `_handles` False -> not called -> `structured['sources']` is the
    # model's own ledger, byte-identical. See `_synthesize_sources` for why the direction and the
    # position are both part of the contract.
    if _handles:
        _synthesize_sources(structured, verifier)
    _attach_provenance(structured, verifier)                     # stamp source_key for durable chip join (6.4)
    # D-HP-15 (H1b) SELECT -- THE EPISODE-SPAN FENCE, HERE AND NOT AT THE SCAFFOLD SEAM (fold-2 G-A).
    # IT WALKS MARKER-INTACT TEXT. It ran after the whole stack until this fold, and the D-HP-12 lint
    # below eats an ordered item's '1. ' marker as a bare-digit sentence -- so on the treatment arm the
    # fence saw no items in a numbered '## Episodes' section, the fabricated window shipped, and an
    # honest ordered item after a convicted one was read as a CONTINUATION and deleted uncharged. Both
    # residuals are one root: A FENCE MUST NEVER WALK TEXT A PRIOR PASS REWROTE (H1's staleness lesson).
    # It stays AFTER `verify_citations` (the strip-rate denominators are final, so the fold below does
    # not move them) and OUTSIDE the seven-pass stack -- before it now, not after: this pass MINTS
    # nothing, so the `_synth_ref_floor`/`_resolve_evidence_handles` law that forbids relocating a
    # PRODUCER into the stack does not reach it, and the stack is handed a page whose convicted bullets
    # are already gone. The A4b interval its deletions fall in moved with it (plan 10.15).
    # OFF-ARM: the kwarg is OMITTED when the treatment is not active (`_scaffold_cap_kwargs`' idiom), the
    # pass counts and returns without writing, the ledger fold is a no-op on n=0, and the trace key is
    # never stamped -- so a control turn's body, ledger and record are byte-identical.
    _espan = _validate_episode_spans(structured, sg.trace.get("episodes_injected"),
                                     **({"handle_prose": True} if _handles else {}))
    if _handles and _espan.get("section_seen"):        # the DENOMINATOR rides beside the charge, so a
        sg.trace["episode_spans_validated"] = _espan   # clean treatment row still reports what it checked
    # ...AND IT STAMPS ON `section_seen`, NOT ON `spans_checked` (H1b fold-1 F4), and `section_seen` is
    # set BEFORE every early return (fold-2 G-B) so the FULLY-FLOORED lane -- where the prompt carries no
    # window at all and every window the model writes is minted -- can no longer read to a G1 consumer
    # exactly like a row that never had a section. That lane now convicts, too: universal membership
    # against an empty stamped set.
    # ONE STRIP LEDGER, ONE WRITER (H1 FIX W2's law): a bullet this pass removed is a bullet the reader
    # lost, so it is charged like every other render-side removal. DECLARED in G1 clause (4)'s frozen set
    # in the same change, or the clause would be pre-registered to fail on the wave's own remedy.
    _fold_ledger_class(verifier, _EPISODE_SPAN_UNBACKED_CLASS, _espan.get("bullets_dropped"))
    # D-PQ HANDLE-1: the [N] namespace render, AFTER the verifier (its strips have already removed the
    # handles it convicts, so this pass only ever sees survivors) and BEFORE `_humanize_structured` (so a
    # spliced figure rides the same sanitize the rest of the prose does). Reads `extra_number_calls` --
    # the CASCADE-EXTENDED list the model's GROUNDING LEDGER line was numbered against -- never the
    # orchestrator's shorter `number_calls`, which stops at the agent's own lookups.
    #
    # GATED ON THE VERIFIER, and that is not a hedge -- it is the correct scope. This is the LAST LEG of
    # the citation-truth chain, and `GRAPHRAG_VERIFY=off` is the documented rollback for that whole chain
    # (it also selects the legacy two-list footer). With the verifier off no handle is resolvable in the
    # sense this pass means, so running anyway would delete prose on a turn nobody asked to police. Key
    # ABSENT when off, never null -- the OFF-arm-clean rule.
    if verifier.get("enabled"):
        # D-HP-12's REMEDY, FIRST IN THE STACK AND BEFORE ANY SPLICE. `_resolve_number_handles` writes row
        # values into the prose, so a digit-lint running after it would read the ENGINE's digits as the
        # MODEL's and delete the sentences the renderer had just filled in. Charged in verify (ONE strip
        # ledger, `by_rule['bare_digit']`), deleted here. OFF-arm-clean: no key, no call.
        if _handles:
            # T1-6: `uniq` is threaded so the [E]-cited exemption can be checked against the receipts it
            # names -- the SAME one evidence list D-HP-1 builds once and every [E] pass on this body reads.
            _bdrop = _drop_bare_digit_sentences(structured, extra_number_calls, verifier, uniq=uniq)
            if any(_bdrop.values()):
                sg.trace["bare_digit_dropped"] = _bdrop
        sg.trace["number_handles"] = _resolve_number_handles(structured, extra_number_calls,
                                                             handle_prose=_handles)
        # H1 FIX Z1/Z6: the three D-HP-native render classes join the ONE strip ledger, so the class scan,
        # the artifact projection, the successor family and the EMF counters all read one location.
        if _handles:
            _fold_render_classes(verifier, sg.trace["number_handles"])
        # CYCLE-6 FIX-C, in the SAME gate and BEFORE the body render (see `_dedup_number_handles` for why
        # the ordering is the whole safety of it). Stamped only when it re-pointed something.
        _nclone = _dedup_number_handles(structured, extra_number_calls)
        if _nclone:
            sg.trace["number_rows_deduped"] = _nclone
        # D-HP-10, the [E] half of the [N] pass above, and it inserts HERE -- before the prune, never
        # after (ordering pin (b)). This one asks "does the index name a row at all"; the prune asks "did
        # the reader actually GET the row", keyed on the footer's own emission decision. ALWAYS STAMPED,
        # both polarities: G1 reads control-vs-treatment on this column and a treatment-only census has
        # no denominator. With `_handles` False it is a pure read and the prose is byte-identical.
        sg.trace["prose_handles"] = _resolve_evidence_handles(structured, uniq, handle_prose=_handles)
        # D-HP-14: the wave's #1 risk as a per-ROW column (R11's tripwire is per row, not per run).
        if _handles:
            sg.trace["wrong_slot_audit"] = _wrong_slot_audit(sg.trace["number_handles"])
        # CYCLE-9 FIX 3, in the SAME gate and BEFORE the debris pass (which closes the frames it empties):
        # the [E] half of the same total join. Stamped only when it removed something -- OFF-arm-clean.
        _eorph = _prune_orphan_evidence_handles(structured, verifier, market_register=_mr)
        if _eorph:
            sg.trace["evidence_orphans_pruned"] = _eorph
        # D-HP G1 REMEDIATION D2(b), in the SAME gate and immediately AFTER the prune (which keeps its own
        # population) and BEFORE the debris pass (which closes the frames this one empties). Treatment
        # only, stamped only when it fired, and its removals join the ONE strip ledger under a class
        # DECLARED in G1 clause (4)'s set -- the `slot_orphan` / `episode_span_unbacked` rule.
        if _handles:
            _eslot = _drop_evidence_value_slot(structured, uniq, verifier)
            _fold_ledger_class(verifier, _E_VALUE_SLOT_CLASS, _eslot.get("convicted"))
            if any(_eslot.values()):
                sg.trace["evidence_slot_dropped"] = _eslot
            # D-HP-25 V2, in the SAME gate and the SAME stack position as its sibling above: after the
            # prune (which keeps its own population) and BEFORE the debris pass (which closes the frames
            # this one empties). Treatment only, stamped only when it fired -- the absent-not-null rule,
            # which is D-HP-16's three-lane law: a key that is `null` on control and `0` on a quiet
            # treatment run is a key that cannot be pooled.
            _egeo = _drop_evidence_geo_contradiction(structured, uniq, verifier)
            _fold_ledger_class(verifier, _E_GEO_CONTRADICTION_CLASS, _egeo.get("convicted"))
            if any(_egeo.values()):
                sg.trace["evidence_geo_dropped"] = _egeo
        # D-PQ HANDLE-3, in the SAME gate and immediately after: the frames those removals (and the
        # verifier's own positional strips) left empty. Stamped only when it changed something, so an
        # untouched draft writes no key -- the OFF-arm-clean rule, again.
        if _tidy_handle_debris(structured):
            sg.trace["prose_debris_tidied"] = True
        # H1 FIX Z4, in the SAME gate and AFTER the debris pass (which closes the bracket frames a
        # positional strip left standing, so the sentence's real tail is visible here) and BEFORE TIDY-2
        # (which repairs the paragraph seam this drop opens, off the seams it mints). Treatment only.
        if _handles:
            _sorph = _drop_slot_orphan_sentences(structured, verifier)
            # H1 FIX W2: the deleted sentences join the ONE strip ledger, so no sentence this pass
            # removed is unaccounted for in the artifact (finding NF-2).
            _fold_ledger_class(verifier, _SLOT_ORPHAN_CLASS, _sorph.get("sentences_dropped"))
            if any(_sorph.values()):
                sg.trace["slot_orphan_dropped"] = _sorph
        # CYCLE-5 TIDY-2, in the SAME gate and immediately after the debris pass: the debris rules close
        # up punctuation frames INSIDE a line, this one closes the paragraph seam a whole-sentence drop
        # opened. Order matters only in that both run after every removal is final. Stamped only when it
        # changed something -- the OFF-arm-clean rule, again.
        if _tidy_strip_orphans(structured, verifier):
            sg.trace["prose_orphans_tidied"] = True
    # A4b SEAM 1: `_humanize_structured` is the FIRST reg.sanitize pass on the prose (per field). Capture
    # its INPUT -- post-verify, pre-sanitize -- because that is the last state in which a banned sentence
    # is still attributable to sanitize rather than to the verifier's strips.
    _raw_draft = _fold_draft(_raw_draft, sanitize_input_snapshot(
        verified_tldr=structured.get("tldr"), verified_mechanism=structured.get("mechanism")))
    # D-DT-1 THE SEAM -- the ONE point satisfying all four constraints (see _maybe_scaffold_episodes).
    # Flag off -> returns {} having read nothing: no trace key, no mutation, byte-identical body.
    # `market_register` is the SAME `_mr` _humanize_structured is about to run with, and passing it is
    # load-bearing: the scaffold sanitizes its own text at mint time and reconciles against what that pass
    # will produce, so a different register here would prove the wrong thing.
    sg.trace.update(_maybe_scaffold_episodes(
        structured, verifier, injected=sg.trace.get("episodes_injected"), nodes=sg.nodes,
        evidence=evidence, n_positional=len(uniq), market_register=_mr, relevant=_ep_rel,
        **_scaffold_cap_kwargs(mode_knobs)))                      # D-AM-10: {} unless a mode is honored
    _humanize_structured(structured, market_register=_mr)         # clean the fields the UI renders directly (6.1)
    # D-RC-12: the tldr-vs-basis reconcile reads the FINAL tldr (post-verify, post-humanize = what the
    # reader sees) against the pre-model driver-sign basis. {} when the flag is off; stamp-only always.
    sg.trace.update(_tldr_direction_trace(structured, graph, contracts))
    if os.environ.get("GRAPHRAG_ANSWER_V2", "off") == "on":       # P9-C typed sections: a DERIVED view of the
        secs = _sectionize(structured.get("mechanism") or "")     # FINAL prose (post-verify+humanize); read per
        if secs:                                                  # call so the env-flip rollback stays live
            structured["sections"] = secs
    # ══ CYCLE-10-AMEND (2026-08-08) REVIEW MAJOR 1+2 -- THE FOOTER IS NOT PART OF THE REGISTER'S TEXT ══
    # FIX 2 pre-cleared each row's SNIPPET at row scope and then still handed the assembled footer to the
    # body-wide `reg.sanitize`. That left one interaction it could not reach, because it is not about
    # snippets at all: a row's OWN marker. `register._CIT_HANDLE` is `\[[EN]\d+\]` (register.py:283), so
    # "[10]" is not a citation to that gate -- and `register._level_tokens` (register.py:434) accepts any
    # token of two or more integer digits, so "[10]" READS AS AN UNBACKED PRICE LEVEL. On an OUTLOOK turn
    # every footer row whose ref is >= 10 was therefore deleted by the body pass with a perfectly clean
    # snippet, and when the deletion took the last row it took the "## Sources" heading with it. Measured:
    # 12 clean rows in, refs 1-9 out; 37.5% of all rows lost on a 4,000-footer sweep.
    # THE REMEDY IS STRUCTURAL, NOT A CLASSIFIER PATCH: the footer is ASSEMBLED FROM ROWS THAT HAVE EACH
    # ALREADY BEEN THROUGH THE REGISTER (at row scope, where the row's own marker is not part of the text
    # being judged) and is APPENDED AFTER the body pass. The register never sees the footer, so the
    # marker-as-level reading, the row-head deletion, the row fusion and the separator weld are all
    # unreachable BY CONSTRUCTION rather than by a rule that has to keep being right.
    # NOTHING IS RELAXED: the same sentences are still refused -- `_source_row_snippet` runs the identical
    # instrument with the identical `market_register`, and it is now the ONLY register pass the footer
    # gets, which is why it must stay exactly where it is.
    # THE OFF ARM IS BYTE-IDENTICAL: the legacy two-list footer is not row-cleared, so it stays INSIDE the
    # sanitize input exactly as before -- `_footer` is empty on that branch and the append is a no-op.
    _footer = ""
    if verifier.get("enabled"):                                   # ONE validated source list, model-numbered
        _sanitize_in = render(structured, include_ledger=False)
        _footer = _cited_sources_block(structured, verifier, extra_number_calls, market_register=_mr)
    else:                                                         # verifier off -> legacy two-list rendering
        footer = ("\n\n## Sources\n" + cit.render(ev_cits)) if ev_cits else ""
        _sanitize_in = render(structured) + footer
    # A4b SEAM 2: the assembled body on its way INTO the render seam. Both branches now name the same
    # local and ONE sanitize call consumes it -- same arguments, same register, same output bytes.
    # The SNAPSHOT stays the WHOLE PAGE (prose + footer), byte-identical to what it recorded before the
    # amendment: it is what `pairwise_judge.render_answer_for_judge` serves as the answer and what the
    # numeral adjudicators diff against the served body, and a snapshot that dropped the footer would make
    # every footer figure read as newly minted at the seam. What changed is only which SLICE of it the
    # register consumes -- the footer crosses this seam unchanged, which is the property being fixed.
    _pre_sanitize = _sanitize_in + _footer
    body = reg.sanitize(_sanitize_in, market_register=_mr) + _footer
    _raw_draft = _fold_draft(_raw_draft, sanitize_input_snapshot(body_pre_sanitize=_pre_sanitize))
    if degraded:
        body = _DEGRADED_BANNER.format(m=degraded) + body
    # ══ CYCLE-7 (2026-08-08) INSTRUMENT-1: THE CALL LIST THE FOOTER WAS ACTUALLY BUILT FROM ═══════════
    # `eval._served_rows` projects `out["number_calls"]`, which the orchestrator sets to the AGENT's own
    # lookups (orchestrator.py:519). On the hybrid lane that is not the list this answer's footer was built
    # from: `extra_number_calls` is REBOUND to a copy at the cascade seam (answer.py:1915) and `cq.quantify`
    # appends every injected leg -- delta, pace, price, era, weather-z, drought-z, synthetic rows -- to the
    # COPY. The projection therefore stopped at the agent's calls and a hybrid record showed footer rows it
    # carried no served values for: gate-4 dcw pass1 `nass_conditions_split` = 23 footer rows / 0 served row
    # values, pass2 `urea_zscore` = 18 / 2. Every [N] index above the agent's count was unauditable from the
    # artifact, which on a wrong-attribution cycle is the one thing the artifact has to answer.
    # ADDITIVE, AND ONLY ADDITIVE: a NEW key beside the existing ones. Nothing that reads `number_calls`
    # changes meaning, the numbers_only lane never sets this (no cascade seam) and falls back to exactly
    # what it projected before, and `_served_rows`' own caps are what bound the extra rows.
    return {"answer": body, "structured": structured, "contract": contracts[0] if contracts else None,
            "contracts": contracts, "citations": [c.model_dump() for c in ev_cits], "evidence": evidence,
            "model": model, "number_calls_full": extra_number_calls,
            "trace": {"planner": "l2", "fired_regimes": sg.fired_regimes,
                                      "citation_verifier": verifier, "banned_mood_words": _banned_mood,
                                      "banned_valuation_words": _banned_val, "banned_flow_words": _banned_flow,
                                      "banned_exec_words": _banned_exec, "unbacked_levels": _unbacked,
                                      "bare_digit_count": _bare_digits,   # D-HP-4(c): always on, gates nothing
                                      "citation_resolved": _typed_resolved(verifier),   # D-HP-4(d), G1 (6)
                                      "outlook_mode": _outlook, "market_register": _mr,
                                      **({"degraded_model": degraded} if degraded else {}),
                                      **({"synth_usage": _synth_usage} if _synth_usage else {}),   # D-AM-4
                                      **({"plan_tokens": _plan_tok}          # A3: BESIDE synth_usage, a COUNT
                                         if _plan_tok is not None else {}),  # ...absent on every control row
                                      **({"raw_draft": _raw_draft} if _raw_draft else {}),   # A4, audited runs only
                                      "has_diagram": _valid_mermaid(structured.get("diagram_mermaid")), **sg.trace}}


def _prompt_parts(query: str, contracts: list[str], stable_blocks: list[str],
                  volatile_blocks: list[str]) -> tuple[str, str]:
    """(stable_prefix, volatile_tail). CACHE-CRITICAL ORDERING: the graph context (stable per contract
    set) comes FIRST and the question comes LAST — the old shape put QUESTION first, so every new query
    invalidated the whole prompt-cache prefix. The stable prefix must stay byte-identical across a
    session's turns; anything per-turn (evidence, conversation state, numbers, the question) is tail."""
    scope = contracts[0] if len(contracts) == 1 else f"{len(contracts)} related contracts {contracts}"
    tail = ("" if len(contracts) == 1 else
            "Multiple related contracts are shown — synthesize the cross-commodity linkage between them.")
    stable = f"=== CAUSAL GRAPH ({scope}) ===\n" + "\n\n".join(stable_blocks)
    volatile = ("\n\n".join(volatile_blocks) + f"\n\nQUESTION: {query}" + (f"\n{tail}" if tail else "")).strip()
    return stable, volatile


def _pack(stable: str, volatile: str, structured: bool):
    """Real call path -> (stable, volatile) tuple for cached blocks; injected fakes -> one plain string."""
    return (stable, volatile) if structured else stable + "\n\n" + volatile


# D-HP G1 AMENDMENT A2(a), 2026-08-14 -- THE BUDGET SENTENCE, AND WHY THE OLD ONE WAS FALSE.
# The shipped text said "this is the one place digits cost nothing". That is TRUE OF THE LINT and FALSE
# OF THE CEILING, and the writer had no way to tell the two apart: `plan` is emitted FIRST and is OUTPUT,
# so it is billed against the SAME `max_tokens` as the answer. G1's void measured the consequence -- the
# popped region took ~47% of treatment output (767 / 1,651 / 1,529 / 3,748 tokens on the four surviving
# rows), and its correlation with the retained prose is NEGATIVE (r = -0.28): the plan and the answer are
# SUBSTITUTES, not multiples. Reasoning migrated out of the prose and into a region nobody had budgeted.
# THE NUMBER IS ~800 AND IT IS MEASURED, NOT GUESSED: the SMALLEST plan observed anywhere in the arm (767
# tokens, dv_xorigin_wheat_policy) produced that arm's BEST row -- claim_count 55, 28 handles checked, the
# largest claim count of the four. There is no evidence that 3,748 bought anything 767 did not.
# SOFT, DELIBERATELY. A hard cap the model cannot count against would trade a truncated answer for a
# truncated plan; the ceiling raise (A1) is what makes an overrun survivable, and this is what makes the
# raise honest rather than open-ended.
_PLAN_PROPERTY_DESC = (
    "Your PRIVATE working notes for this answer. NOT shown to the reader, not stored, not verified, not "
    "graded -- it is deleted server-side the moment the call returns. Use it to decide WHICH receipt rows "
    "you will cite and in what order, to talk yourself through arithmetic or comparisons, and to note what "
    "the record does NOT support. Write numbers here freely: no digit you type HERE is ever charged by the "
    "lint. THAT IS NOT THE SAME AS FREE. These notes and the answer are drawn from ONE output budget, so "
    "every token spent here is a token the answer does not get -- notes and answer are SUBSTITUTES, not "
    "multiples, and a long plan is a short answer. BUDGET IT AT ABOUT 800 TOKENS (roughly 600 words). That "
    "is a soft budget, not a hard limit: exceed it only when the question genuinely needs it, and never at "
    "the cost of finishing the answer. Terse beats prose here -- the row list, the comparison, the "
    # D-HP G1 REMEDIATION, 2026-08-14: the same firming, in the same words, as `_SYSTEM_HANDLES`' budget
    # paragraph -- the two are read in ONE turn and a budget stated firmly in one and loosely in the other
    # is the A2(b) defect wearing a different hat. Still soft: no cap, no knob, no clause reads it.
    "refusals. 800 is the number to plan TO, not a line to drift past -- the best-scoring rows measured so "
    "far had the SHORTEST plans, so notes running past ~1,500 tokens are evidence you are writing the "
    "answer twice. Nothing you write here can appear in the answer except as a handle.")


def _answer_tool(handles: bool = False) -> dict:
    """The `emit_answer` tool schema. `handles=False` returns the SHIPPED schema byte-for-byte.

    == D-HP-7 / D-HP-9 (H1), THE CONDITIONAL FORM ======================================================
    `handles=True` makes TWO changes, and the argument (never an env read) is what keeps the OFF arm
    provable and keeps the DOCUMENT lane out of it: `dossier.py:678` calls this WITH NO ARGUMENTS, so the
    dossier's schema is byte-identical until D-HP-28 opens (D-HP-16: "D-HP-9 SHIPS CONDITIONALLY OR IT
    DOES NOT SHIP").

    (1) `plan` IS ADDED -- THE FREE REASONING REGION, AND IT IS A PROPERTY, NOT A DELIMITED SPAN.
        The constrained-generation result D-HP-7 adopts is that a restrictive output grammar caps
        reasoning UNLESS the grammar carries a free region. This model has no other output channel, so the
        region is either a new property or a span inside the prose fields -- and a span breaks four named
        invariants, every one of them measured:
          (i)   `verify.claim_count` splits SENTENCES over `tldr + " " + mechanism`, and it is THE strip-rate
                denominator every successor metric in D-HP-17 divides by. An in-field region inflates it and
                destroys the bridge run's comparability.
          (ii)  the digit-lint charges inside that same function, so an in-field region's digits would be
                CHARGED -- the lint would fine the model for thinking in numbers, which is the one place
                D-HP wants it to.
          (iii) `structured['mechanism']` is rendered DIRECTLY by the FE and scraped MID-STREAM by
                `StreamingNote.streamingPreview`, so a delimited span inside it streams to the reader
                verbatim.
          (iv)  a separate property is invisible to that scraper by construction.
        IT IS NOT IN `required` (a turn that needs no scratchpad must not be forced to invent one) and it
        is POPPED server-side beside `_pop_usage`, BEFORE `verify_citations`, so it never reaches
        `structured`, never reaches the render, never reaches the judge and never moves `claim_count`.
        IT IS EMITTED FIRST, and the cost is PRE-REGISTERED rather than discovered: the planning region's
        output tokens delay the first `tldr` delta, so D-HP-24's "TTFB unchanged at the transport" is false
        and D-HP-27 (R5) owns the SSE consequence. Reason-then-write is the point; a plan emitted after the
        prose is a rationalisation, not a plan.

    (2) `sources` IS DROPPED -- from `properties` AND from `required` (it is in both, and a conditional
        that varied only one would emit a schema demanding a property it does not declare). This is the
        deletion that makes THREE of the four killed classes unconstructible rather than caught:
        `fabricated_citation` has no ledger row to mint, `ledger_cascade` goes with it for free, and
        `undeclared_unsupported` collapses to a pure index-range check. Two of its four fields were already
        renderer-owned anyway (`source` is overwritten by `_humanize_structured`, `date` is corrected by
        the verifier), and the `ref: integer` typing is what made E and N collide on one namespace.
        THE THREE CONTRACTS THIS OWES, none of them optional and none of them here (R1): the server
        synthesises `verifier['resolved']` (verify.py mints it positionally under `handle_prose=True`,
        because six consumers join on it and `_prune_orphan_evidence_handles` would otherwise prune EVERY
        [E] handle from the prose), re-synthesises `structured['sources']` FROM `resolved` AFTER
        `verify_citations` returns, and carries `source_key` on every synthesised row -- the sole input to
        the 6.5 click-to-page locator. A drop without them costs the reader receipts AND click-to-page."""
    s = {"type": "string"}
    props: dict = {}
    if handles:
        props["plan"] = {"type": "string", "description": _PLAN_PROPERTY_DESC}
    props.update({"tldr": s, "mechanism": s, "diagram_mermaid": s})
    required = ["tldr", "mechanism"]
    if not handles:
        props["sources"] = {"type": "array", "items": {"type": "object", "properties": {
            "ref": {"type": "integer"}, "source": s, "date": s, "note": s}}}
        required.append("sources")
    return {"name": "emit_answer", "description": "Emit the reader-first structured answer.",
            "input_schema": {"type": "object", "properties": props, "required": required}}


def _pop_plan(structured) -> str | None:
    """D-HP-7: lift the planning region OFF `structured` and return it, in the `_pop_usage` idiom.

    THE POSITION IS THE CONTRACT (ordering pin (c), the one D-HP-6 could not write at H0): this runs
    BEFORE `verify_citations`, so `claim_count` is byte-identical with and without a plan, the digit-lint
    never charges the model's scratchpad, and no fidelity rung of `render_answer_for_judge` can serve it.
    Returned rather than discarded so the caller decides -- and today every caller drops it on the floor:
    the region is UNRENDERED BY CONSTRUCTION, and a trace key would put the model's private reasoning into
    a stored artifact that the judge, the adjudicators and the FE all read."""
    if not isinstance(structured, dict):
        return None
    v = structured.pop("plan", None)
    return str(v) if isinstance(v, str) and v.strip() else None


def _plan_tokens(plan: str | None) -> int | None:
    """D-HP G1 AMENDMENT A3 (2026-08-14): the SIZE of the popped planning region, and NOTHING ELSE.

    THE PRIVACY REASON AT `_pop_plan` STANDS, AND IS RESTATED HERE BECAUSE THIS IS THE FIELD THAT COULD
    HAVE BROKEN IT: the region is the model's private reasoning, and a trace key carrying its TEXT would
    put that reasoning into a stored artifact the judge, the adjudicators and the FE all read. A SCALAR
    carries no reasoning. It is the one thing about the region that can be recorded without leaking it,
    and `plan_tokens` is a COUNT, NEVER THE TEXT -- no caller may extend this to carry a prefix, a
    sample, a first line or a hash of the content.

    WHY IT EXISTS. The region was unmeasurable BY CONSTRUCTION: `_pop_plan` returns it, every caller
    drops it on the floor, and `_PlanRegionFilter` strips it from the SSE relay too. G1's void therefore
    had to be diagnosed by SUBTRACTION against a control arm -- fitting the control's residual and
    applying the fit to treatment -- to reach the finding that the plan was ~47% of treatment output.
    That is an expensive way to learn a number the producer already had. With this column the next arm
    reads it directly.

    METHOD, STATED BECAUSE IT IS AN ESTIMATE AND MUST NEVER BE READ AS A BILLED COUNT: characters / 4,
    rounded -- the standard English-prose approximation. No tokenizer is imported (the serving path
    carries none, and cl100k is not this model's tokenizer anyway; the G1 diagnosis measured cl100k
    running 15-30% cold against Claude on this text). The BILLED total already rides `synth_usage.out`;
    this is the SHARE of that total the scratchpad took, to within the estimator's error.

    ABSENT ON EVERY CONTROL ROW, and that is the arm's own OFF proof rather than a convention: `plan`
    only exists in the schema under `handles=True` (`_answer_tool`), so a control turn has no region to
    size and stamps no key. None (-> the key is omitted) whenever nothing was popped."""
    if not isinstance(plan, str) or not plan.strip():
        return None
    return max(1, round(len(plan) / 4))


# ══ H1 FIX Z10 -- THE PLAN REGION MUST NOT REACH THE SSE `token` STAGE ════════════════════════════════
# `_pop_plan` deletes the region server-side AFTER the model call returns. That is the right place for the
# STORED artifact and the wrong place for the TRANSPORT: on a streamed turn the forced-tool relay
# (`extract.call_opus_stream` -> `on_token` -> `_emit(on_stage, "token", ...)`) forwards the raw
# `input_json_delta` of the tool input as it generates, and `plan` is emitted FIRST in the schema. So the
# whole planning region was delivered to the browser and accumulated into React state BEFORE anything
# verified it -- and `_PLAN_PROPERTY_DESC` tells the model that region is "not shown to the reader, not
# stored" and to "write numbers here freely". The one place the model is instructed to type unverified,
# unlinted, unstripped magnitudes was the one region shipped to the client unfiltered.
# THE FILTER IS AT THE RELAY, NOT AT THE RESULT, and it is SERVER-SIDE (R5(b)): nothing can unsend a token
# already written to the wire, so the deltas belonging to the `plan` key are dropped BEFORE `_emit`. The
# scraper argument in `_answer_tool`'s reason (iv) ("a separate property is invisible to that scraper by
# construction") holds for what is PAINTED; it never held for what is DELIVERED.
# WHAT IS FORWARDED: the key token itself and the value's own quotes, so the accumulated draft stays
# parseable JSON (`{"plan": "", "tldr": "...`) and the FE's partial-JSON scrape is untouched. Only the
# CONTENT of the value is dropped.
# STATE MACHINE, NOT A REGEX: the relay hands over arbitrary fragments of one JSON document, so a token
# boundary can fall anywhere -- inside a key, inside an escape, between the colon and the quote. The
# scanner therefore carries its state across chunks and decides per CHARACTER.
# FAIL-OPEN IS NOT AN OPTION HERE, so it fails CLOSED-ish instead: any internal error stops filtering by
# dropping nothing further only after the plan value has closed; an exception inside the scan suppresses
# the chunk rather than forwarding a possibly-plan fragment. A dropped note fragment costs a cosmetic
# stream; a forwarded one costs the promise.
_PLAN_KEY = "plan"


class _PlanRegionFilter:
    """Streaming JSON scanner that removes the `plan` value's CONTENT from a tool-input delta stream."""

    # H1 FIX W3 (finding NF-3): `inject` is the stand-in a SUPPRESSED NON-STRING value leaves behind. The
    # string path forwards the value's own quotes, so the draft reads `"plan": ""` and stays parseable
    # JSON -- which is the property this filter's rationale rests on (the FE's streaming preview does
    # `JSON.parse` first and only falls back to a per-key regex scrape when that throws). The defensive
    # raw path forwarded NOTHING, emitting `{"plan": , "tldr": ...}` -- syntactically invalid, i.e. the
    # branch that exists to degrade gracefully degraded WORSE than the one it mirrors. It now emits the
    # literal `null`, which is valid JSON, carries no plan content, and is what a consumer of an
    # out-of-contract value should see.
    __slots__ = ("in_str", "esc", "depth", "expect_key", "is_key", "key_buf", "cur_key", "sup_str",
                 "sup_raw", "broken", "inject")

    def __init__(self) -> None:
        self.in_str = self.esc = self.is_key = self.sup_str = self.sup_raw = self.broken = False
        self.depth = 0
        self.expect_key = True          # the document opens on `{`; the first string after it is a key
        self.key_buf = self.cur_key = ""
        self.inject = ""

    def feed(self, chunk: str) -> str:
        if self.broken:
            return chunk                # the scan lost its footing AFTER the region closed -- pass through
        out: list[str] = []
        try:
            for c in chunk:
                keep = self._char(c)
                if self.inject:         # W3: the stand-in for a suppressed non-string value
                    out.append(self.inject)
                    self.inject = ""
                if keep:
                    out.append(c)
        except Exception:  # noqa: BLE001 -- never forward a fragment this scanner could not classify
            self.inject = ""
            self.broken = not (self.sup_str or self.sup_raw)
            return "" if (self.sup_str or self.sup_raw) else "".join(out)
        return "".join(out)

    def _char(self, c: str) -> bool:
        """True to forward `c`."""
        if self.in_str:
            drop = self.sup_str
            if self.esc:
                self.esc = False
            elif c == "\\":
                self.esc = True
            elif c == '"':
                self.in_str = False
                drop = False                        # the closing quote keeps the JSON well-formed
                if self.is_key:
                    self.is_key, self.cur_key, self.key_buf = False, self.key_buf, ""
                elif self.sup_str:
                    self.sup_str, self.cur_key = False, ""
            elif self.is_key:
                self.key_buf += c
            return not drop
        if self.sup_raw:                            # a NON-string plan value (defensive: the schema says
            if self.depth <= 1 and c in ",}":       # string). Drop until the value's own end.
                self.sup_raw, self.cur_key = False, ""
                if c == ",":
                    self.expect_key = True
                else:
                    self.depth -= 1
                return True
            if c in "{[":
                self.depth += 1
            elif c in "}]":
                self.depth -= 1
            return False
        if c == '"':
            self.in_str, self.esc = True, False
            if self.expect_key and self.depth == 1:
                self.is_key, self.key_buf, self.expect_key = True, "", False
            elif self.depth == 1 and self.cur_key == _PLAN_KEY:
                self.sup_str = True                 # the opening quote of the plan value; forward it
            return True
        if c in "{[":
            self.depth += 1
            if c == "{":
                self.expect_key = self.depth == 1
            if self.depth > 1 and self.cur_key == _PLAN_KEY:
                self.sup_raw, self.inject = True, "null"     # W3: valid JSON in the value's place
                return False
            return True
        if c in "}]":
            self.depth -= 1
            return True
        if c == ",":
            if self.depth == 1:
                self.expect_key, self.cur_key = True, ""
            return True
        if c == ":" or c.isspace():
            return True
        if self.depth == 1 and self.cur_key == _PLAN_KEY:   # a bare literal (number/true/null) plan value
            self.sup_raw, self.inject = True, "null"         # W3: valid JSON in the value's place
            return False
        return True


def _plan_filtered_token_relay(emit_fn):
    """Wrap an `on_token` callback so the `plan` region never reaches it. One filter per turn (the scanner
    is stateful across chunks); returns `emit_fn` unchanged when there is nothing to wrap."""
    if emit_fn is None:
        return None
    f = _PlanRegionFilter()

    def _relay(t: str) -> None:
        kept = f.feed(t if isinstance(t, str) else str(t))
        if kept:
            emit_fn(kept)
    return _relay


def _valid_mermaid(s: str | None) -> bool:
    """Cheap well-formedness gate so we never render a broken diagram: a flowchart/graph header, an edge, and
    balanced brackets."""
    s = (s or "").strip()
    return bool(re.match(r"(flowchart|graph)\b", s)) and "-->" in s \
        and s.count("[") == s.count("]") and s.count("(") == s.count(")")


def render(d: dict, *, include_ledger: bool = True) -> str:
    """Structured fields -> reader-first markdown (drops the diagram if absent or malformed).
    `include_ledger=False` suppresses the model's own **Sources** lines — used when the verifier ran and
    the answer instead carries ONE validated `## Sources` block (two parallel lists with independent
    numbering read as 'mismatched citations' and inflated the judge's hallucination tally 37->151)."""
    # CYCLE-5 TIDY-3: a header with nothing under it is not a summary, it is a promise the page cannot
    # keep. Measured on gate-2 pass 1 (`dcw_urea_zscore`): the verifier convicted the ONE sentence the
    # TL;DR contained, and the body shipped the literal line "**TL;DR.** " with the whole section empty.
    # The mechanism below still carried the answer, so the honest render is to drop the label rather than
    # advertise a summary that was removed. Scoped to the EMPTY case only: a TL;DR with any content at all
    # renders byte-identically, which is every turn that did not have its summary stripped to nothing.
    _tldr = (d.get("tldr") or "").strip()
    parts = ([f"**TL;DR.** {_tldr}", ""] if _tldr else []) + [f"**Why.** {(d.get('mechanism') or '').strip()}"]
    if _valid_mermaid(d.get("diagram_mermaid")):
        parts += ["", "**Cascade / convergence**", "```mermaid", d["diagram_mermaid"].strip(), "```"]
    srcs = d.get("sources") or []
    if srcs and include_ledger:
        parts += ["", "**Sources**"] + [f"[{x.get('ref')}] {x.get('source')} · {x.get('date')} — {x.get('note', '')}"
                                         for x in srcs]
    return "\n".join(parts).strip()


def _served_rows(calls) -> int:
    """Rows SERVED across a turn's number calls -- the count PA-8 says the ledger owes the writer.

    A call's `rows` is its own served set (`citations.from_number` headlines max() over it and shows one
    line), so this is a pure sum over the same lists the panel renders: build-time deterministic, no
    ordering dependence, nothing probed. A malformed call reads as zero rows -- one-sided, the direction
    that can under-count an abundance, never invent one."""
    return sum(len((c or {}).get("rows") or []) for c in (calls or []) if isinstance(c, dict))


def _grounding_ledger(n_ev: int, n_num: int, *, menu_on: bool, n_rows: int | None = None) -> str:
    """THE GROUNDING LEDGER sentence -- ONE producer, both serving bodies (D-HP-16).

    Clause A' (the thin-turn honesty fix): a per-turn line enumerating the EXACT valid handle ranges, so
    the model cannot mint an [E]/[N] handle beyond what the engine actually holds. It rides the VOLATILE
    tail, never the cached constant.

    WHY IT IS A FUNCTION NOW, AND WHY THAT IS A D-HP-16 ITEM RATHER THAN A TIDY. The one-hop body -- the
    DOCUMENTED `GRAPHRAG_PLANNER=onehop` rollback lane -- had NO ledger line at all (answer.py states it
    verbatim: "this body has no GROUNDING LEDGER line, so the record-edge sentence rides its own volatile
    block"). That was survivable while handles were optional decoration on typed prose. Under handle-only
    prose it is not: the rollback lane would render a NUMBERED menu and then tell the model NOTHING about
    which addresses exist, which is the D2 asymmetry -- an unaddressable menu -- restored on exactly the
    path a rollback puts every turn on. So the line ships on both bodies, from one derivation, because
    two spellings of "which handles are valid" is how the two lanes drift.

    `menu_on` False is the pre-D-HP sentence AND the pre-D-HP loose cap, byte for byte: "each mapping to
    the item tagged with it above" is a claim ABOUT RENDERED ROWS and must not outlive them (D-HP-16's
    dossier lane renders unnumbered rows and must not be told its handles are addresses).

    PA-8(b) (2026-08-25) -- `n_rows`: THE COUNT IS ROWS, THE HANDLE RANGE IS LOOKUPS, AND THEY ARE NOT THE
    SAME NUMBER. The shipped sentence counted CALLS and called them rows (`n_num = len(extra_number_calls)`,
    answer.py), so a 24-month MPOB series served under one lookup was announced to the writer as "1 observed
    number row(s)" and narrated as an absence -- `gn2_mpob_stock_build`, 2/5 on all three seats. The [N]
    clause KEEPS counting lookups because that is what it addresses: `unify` mints one indexed citation per
    call ([N1]..[Nn_num]) and the per-row extras are letter-suffixed siblings that consume no index, so a
    range built on rows would invite handles that resolve to nothing. `n_rows=None` renders the pre-PA-8
    sentence to the byte, for any caller that has only the counts."""
    e_clause = (("Emit NO [E] handles (there are no evidence items); " if n_ev == 0 else
                 f"[E] handles run [E1]..[E{n_ev}], each mapping to the item tagged with it above; ")
                if menu_on else
                f"Cite AT MOST {n_ev} distinct [E] handles, each mapping to one item above; ")
    n_clause = (f"{n_num} observed number row(s)" if n_rows is None
                else f"{n_rows} observed number row(s) across {n_num} lookup(s)")
    return (f"GROUNDING LEDGER: {n_ev} dated evidence item(s) and {n_clause} are "
            f"available for this question. " + e_clause
            + ("emit NO [N] handles (there are no number rows)."
               if n_num == 0 else f"[N] handles run [N1]..[N{n_num}]."))


def _synthesize_sources(structured: dict, verifier: dict) -> int:
    """D-HP-9 / R1(b): re-mint `structured['sources']` FROM `verifier['resolved']`. Returns the row count.

    THE THIRD OF THE THREE CONTRACTS THE SCHEMA DROP OWES, and the one with a READER-FACING cost. With
    `sources` gone from the tool schema the model authors no ledger; verify mints `resolved` positionally
    (its own `handle_prose` branch) so the `## Sources` block and the LIVE FE chip path -- both of which
    read `trace.citation_verifier.resolved` -- survive. `structured['sources']` does NOT survive on its
    own, and TWO consumers read it and nothing else:
      * `_attach_provenance` is the SOLE producer of `structured.sources[].source_key`, whose docstring
        states its purpose ("so the frontend can join a model ref to the citation row's snippet WITHOUT
        name-matching"), and citations.ts feeds that key to `docLocator` -- THE 6.5 PDF CLICK-TO-PAGE
        LOCATOR. It loops `structured['sources']`, so an empty ledger stamps nothing.
      * the FE's DURABLE path (`resolvedFor`) reads `structured.sources`, a DIFFERENT function from the
        live path's `resolvedMap`. Synthesising only one of the two fixes one lane and leaves the other
        dark, which is precisely the folded C1 blocker.
    So a drop without this costs the reader RECEIPTS and CLICK-TO-PAGE in the same flip.

    THE DIRECTION IS FROM `resolved`, NEVER THE REVERSE, AND THE ORDER IS PART OF THE CONTRACT (G17):
    writing a ledger BEFORE `verify_citations` would make `_match_ledger_entry` match by construction and
    `fabricated_citation` would read 0 TAUTOLOGICALLY -- the gate would measure its own scaffolding. This
    runs AFTER verify returns and BEFORE `_attach_provenance`, which is the pinned sequence.

    THE ROW SHAPE IS TODAY'S POST-`_attach_provenance` SHAPE, field for field ({ref:int, source, date,
    note, source_key}), so every downstream consumer joins unchanged and `_attach_provenance` becomes an
    idempotent re-stamp rather than a no-op on a missing key. `note` carries verify's OWN snippet of the
    resolved item -- engine text about the item the handle names, never model prose, and never a
    fabrication surface: there is no field here a model could have invented.
    `ref` is `int` because the shipped schema typed it `{"type": "integer"}` and `_document_source_rows`,
    `dossier._sources_block` and the FE all join on the bare digit."""
    if not isinstance(structured, dict):
        return 0
    resolved = (verifier or {}).get("resolved") or {}
    rows = []
    for ref in sorted((r for r in resolved if str(r).isdigit()), key=lambda r: int(r)):
        r = resolved.get(ref) or {}
        if not isinstance(r, dict):
            continue
        rows.append({"ref": int(ref), "source": r.get("source"), "date": r.get("date"),
                     "note": r.get("snippet") or "", "source_key": r.get("source_key"),
                     # Phase F: the span keys the FE's docLocator has read (and found absent) since 6.5 --
                     # additive; every consumer joins on named keys, so pre-offset Nones are inert
                     "char_start": r.get("char_start"), "char_end": r.get("char_end"),
                     "offset_kind": r.get("offset_kind")})
    structured["sources"] = rows
    return len(rows)


def _attach_provenance(structured: dict, verifier: dict) -> None:
    """Stamp each kept evidence source with its `source_key` (6.4) so the frontend can join a model ref to
    the citation row's snippet WITHOUT name-matching (structured.sources carry the OFFICIAL name after 6.1;
    citations[] keep the RAW source for the receipts join). Runs after verify (which populated resolved +
    rewrote structured.sources) — additive, never changes counts."""
    if not isinstance(structured, dict):
        return
    resolved = (verifier or {}).get("resolved") or {}
    for s in (structured.get("sources") or []):
        if not isinstance(s, dict):
            continue
        ref = str(s.get("ref", "")).strip().strip("[]")
        r = resolved.get(ref)
        if isinstance(r, dict) and r.get("source_key"):
            s["source_key"] = r["source_key"]
            for k in ("char_start", "char_end", "offset_kind"):     # Phase F: idempotent span re-stamp,
                if r.get(k) is not None:                            # same join as source_key
                    s[k] = r[k]


def _humanize_structured(d: dict, *, market_register: str = reg.FENCED) -> None:
    """Sanitize the structured fields the UI renders DIRECTLY into reader register (6.1). The frontend
    shows `structured.{tldr,mechanism,sources}`, NOT the flattened body, so this is where leaked internal
    tokens, raw regime ids, and internal source ids are removed for the live AND persisted note. Runs
    AFTER verify (which mutates tldr/mechanism to strip fabricated citations) and mutates in place, so
    the object returned + persisted is already clean.

    W5-D3: `market_register` is keyword-only and DEFAULTS TO FENCED. This function is SHARED by both answer
    bodies (the L2 planner path and the one-hop legacy path), so a default of anything else would relax the
    one-hop path for free -- the default is the fence. `sources[].note` stays FENCED unconditionally: a
    ledger note is provenance metadata, never the outlook argument, so it has no derivation to show."""
    if not isinstance(d, dict):
        return
    for fld in ("tldr", "mechanism"):
        v = d.get(fld)
        if isinstance(v, str) and v:
            d[fld] = reg.sanitize(v, market_register=market_register)
    srcs = d.get("sources")
    if isinstance(srcs, list):
        from leviathan.graphrag import display as dp
        for s in srcs:
            if not isinstance(s, dict):
                continue
            if s.get("source"):
                s["source"] = dp.source_name(str(s["source"]))
            if isinstance(s.get("note"), str) and s["note"]:
                s["note"] = reg.sanitize(s["note"])              # provenance note: ALWAYS fenced


# P9-C kind map: pins to eval._FIXED_SCAFFOLD's headings stripped of the '## ' marker. answer cannot
# import eval (circular), so a cross-check unit test imports both and asserts the keys stay equal --
# label drift fails CI, not prod.
_SECTION_KINDS = {"Mechanism": "mechanism", "The record": "record",
                  "Where the record disagrees": "disagreement", "What to watch": "watch"}


def _sectionize(mech: str) -> list[dict]:
    r"""The final mechanism prose -> typed sections [{kind, heading, body}] (P9-C, GRAPHRAG_ANSWER_V2).
    A DERIVED VIEW, never the write surface: runs AFTER verify + _humanize_structured so every body
    inherits the strip/sanitize passes; mechanism stays canonical. PURE -- reads `mech`, returns a new
    list, mutates nothing (the byte-identical flag-on/off answer hangs on this). Line-based split on
    '## ' heading lines OUTSIDE ``` fences (sanitize preserves mermaid fences; a fenced '## ' line is
    content). `heading` stores the CLEAN text with no '## ' marker; the kind lookup strips first
    (verify's whitespace collapse can leave one trailing space). Prose before the first heading ->
    one kind-"other" section with heading "". Round-trip invariant (unit-gated):
    "\n".join(("## " + s["heading"] + "\n" if s["heading"] else "") + s["body"] for s in sections)
    reproduces `mech` modulo trailing whitespace -- the empty-heading section emits NO leading newline."""
    if not (mech or "").strip():
        return []
    segs: list[tuple[str, list[str]]] = []                        # (clean heading, body lines); "" = pre-heading
    in_fence = False
    for line in mech.split("\n"):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        m = None if in_fence else re.match(r"^\s*##\s+(.*)$", line)
        if m:
            segs.append((m.group(1), []))
        elif segs:
            segs[-1][1].append(line)
        else:
            segs.append(("", [line]))                             # prose before the first heading
    return [{"kind": _SECTION_KINDS.get(h.strip(), "other"), "heading": h, "body": "\n".join(lines)}
            for h, lines in segs]


# ══ D-DT-1: the render-side '## Episodes' scaffold (Option A, RATIFIED 2026-08-04) ═══════════════════
# THE DEFECT, MEASURED (EVIDENCE_INTEGRITY_WAVE_PLAN.md:2450-2466). '## Episodes' is 100% MODEL PROSE:
# render() emits exactly **TL;DR.**, **Why.**, an optional mermaid block and an optional **Sources**
# list and NEVER a '##' heading, so every reserved heading in a shipped answer lives inside the
# model-authored string structured['mechanism']. The persona mandate has been hardened twice (the R6
# fold at _SYSTEM_EPISODES, commit 24fe0f53; persona v2, dbdf41c8) and still leaks on ~23% of
# susceptible turns UNDER IDENTICAL CODE. Option A stops presence being a sampling outcome by
# synthesizing the section from what the engine ALREADY PUT IN THE PROMPT.
#
# THE SEAM IS PINNED BY FOUR CONSTRAINTS AND EXACTLY ONE POINT SATISFIES ALL FOUR (D-DT-1 M7). At this
# tree that point is between the A4b `sanitize_input_snapshot(verified_*)` capture and
# `_humanize_structured`, and the call is spelled the SAME WAY in both serving bodies:
#   * AFTER the A4b snapshot   -- the raw-draft audit must keep attributing only MODEL text, so the
#                                 last state attributable to the model has to be captured first;
#   * BEFORE _humanize_structured -- LOAD-BEARING, not cosmetic: a CASE-1 label is a RAW NODE ID
#                                 ('arabica_coffee', 'drivers/frost') and register.sanitize is what
#                                 humanizes slice/regime ids into prose (register.py:901);
#   * AFTER verify_citations   -- claim_count is captured at verify.py:470-471 before any mutation and
#                                 checked/stripped are already final, so the STRIP RATE (the primary
#                                 judge-free metric) keeps its denominators;
#   * BEFORE render()          -- the reader's body must carry the section.
# Anywhere else breaks one of the four. A refactor that moves this call must re-satisfy all four.
_EPISODE_HEADING_RX = re.compile(r"^\s*#{2,6}\s+(.*)$")
_EPISODE_HEADING_TEXT = "episodes"
# Headings that must come AFTER '## Episodes' when the model rendered them (the persona's own placement
# rule: after '## The record', before '## What to watch'). '## Outlook' is the W5-D5 reserved heading and
# is always last when it fires. No match -> the section is appended, which keeps _FIXED_SCAFFOLD's
# relative order intact either way (an extra heading is invisible to eval._scaffold_ok).
_SCAFFOLD_BEFORE = ("what to watch", "outlook")

# The CASE-1 clauses, VERBATIM from _SYSTEM_EPISODES' own CASE 1 worked example -- one producer for the
# instruction and the synthesis, cross-checked by a unit test so a persona edit cannot silently leave the
# engine writing vocabulary the deck no longer scores. `_NO_CITABLE[0]` and `_NO_PRICE_RECORD[0]` both
# match, so eval.episode_absence_stated / episode_magnitude_or_absence read the same tokens either way.
_SCAFFOLD_CASE1_BACKING = "no citable item in this window, so what happened is not narrated"
_SCAFFOLD_CASE1_MAGNITUDE = "no price record for this window"
# The CASE-2 magnitude clause. The synthesizer mints NO [N] handle, so the magnitude slot is always the
# absence -- stated in the persona's own permitted vocabulary (_NO_PRICE_RECORD carries 'no observed
# magnitude'). RESIDUAL, STATED: unlike the receipt clause this one is NOT branched on engine state --
# the scaffold does not consult the injected number rows -- so on a turn where a [N] row does cover the
# window the clause understates the record. That is the doc's own CASE-1/CASE-2 vocabulary and the J4
# episode-pricing leg is out of scope here; it is recorded so it is a decision, not an oversight.
_SCAFFOLD_CASE2_MAGNITUDE = "no observed magnitude for this window"
# THE CASE-2 BACKING CLAUSE CARRIES NO QUOTATION MARKS, and that is a correctness rule rather than a
# style preference (D-DT-1 fold, 2026-08-05). The doc's CASE-2 shape is a RESTATEMENT -- _SYSTEM_EPISODES'
# own BACKING slot is "one clause RESTATING what a cited dated item inside that window actually says,
# carrying that item's [E] handle" -- and the quote delimiters were never in it. They made the engine a
# MISQUOTER: reg.sanitize rewrites mood words and humanizes contract slugs inside whatever it is handed,
# so `bullish` -> `price-supportive` and `arabica_coffee` -> `ICE arabica coffee` shipped BETWEEN
# QUOTATION MARKS as the source's own words (reproduced end to end). An engine may restate a source in
# its own register; it may never put words in that source's mouth. `reports` is the restatement verb.
# THAT FOLD CLOSED THE ENGINE'S OWN DELIMITERS ONLY; the corpus-borne half is _SCAFFOLD_QUOTE_RX below.
_SCAFFOLD_CASE2_REPORTS = " reports "
# The handle SHARES ITS SENTENCE with the restatement, deliberately -- the clause is made sanitize-STABLE
# at mint time (see _scaffold_section), so the later _humanize_structured pass is a no-op on it and cannot
# delete the clause, taking the handle with it.
#
# WHAT SHARING THE SENTENCE DOES **NOT** BUY, corrected 2026-08-05 (round-2 BLOCKER). This comment used to
# claim that co-location BACKED any price level inside the restatement, because `register.unbacked_levels`
# exempts a sentence carrying a citation handle (register.py:534). That is false twice over, and both ways
# are MEASURED: `register._SENT_ITER` is `(?<=[.!?;])\s+` (register.py:611), so the exemption is
# CLAUSE-scoped and a handle in the lead clause does not reach a level in a later clause of the SAME
# bullet; and the exemption is voided outright when the clause carries a derivation-output marker. There
# is therefore NO structural guarantee here, and the guarantee is not restored by rewording this comment:
# it is enforced in `_scaffold_survives`, on the rendered line, with register's own counter, and a bullet
# that fails it degrades to the cite-only rung rather than shipping the level.
_SCAFFOLD_RESTATE_CAP = 160
# A handle-shaped token inside corpus text is NOT this turn's handle. Dropped from the restatement so the
# engine can never import an [E7]/[N3] from a source's own prose into its own citation namespace.
_SCAFFOLD_FOREIGN_HANDLE_RX = re.compile(r"\[\s*[ENen]?\s*\d+\s*\]")
# MARKDOWN HEADING TOKENS inside corpus text (round-2 LOW-3, 2026-08-05). A receipt whose own text carries
# '## Episodes' restates INLINE: the whitespace collapse above puts it mid-sentence, so it opens no second
# section and the rendered heading count stays exactly ONE -- MEASURED, and pinned by a test rather than
# argued. What the reader still saw was a stray '##' in the middle of a sentence, so the marker is dropped
# in the restatement normalization. WHOLE TOKENS ONLY -- a run of one to six '#' delimited by whitespace or
# the string ends -- so '#3', 'C#' and a mid-word '#' are untouched.
_SCAFFOLD_MD_HEADING_RX = re.compile(r"(?:(?<=\s)|\A)#{1,6}(?=\s|\Z)")
# QUOTATION DELIMITERS inside corpus text (round-3 BLOCKER, 2026-08-05). The fold above stopped the ENGINE
# from minting delimiters; the SOURCE's own rode straight through it, and they reproduce BOTH halves of the
# defect that fold exists to prevent, end to end at rung 1:
#   (a) MISQUOTE. `reg.sanitize` rewrites mood words and humanizes contract slugs INSIDE whatever it is
#       handed, and it cannot see a quotation mark. A receipt reading `Roasters said "we are outright
#       bullish into 2022"` shipped `..."we are outright price-supportive into 2022"...` -- the source's own
#       delimiters wrapped around a word the source never wrote. Restating a source in the house register is
#       honest; putting the house register between that source's quotation marks is not.
#   (b) UNTERMINATED QUOTATION. `_SCAFFOLD_RESTATE_CAP` cuts between an opening delimiter and its closer,
#       so the bullet ships an open quotation that reads as swallowing the engine's own magnitude clause --
#       the same reader-visible shape the mint-time sanitize fix closed once, arriving through the corpus
#       instead of through the strip. MEASURED: 135 of 168 cut points on one probe receipt.
#
# DELIMITER USAGE ONLY, AND THE DISTINCTION IS THE WHOLE DESIGN. The DOUBLE family (ASCII '"', typographic
# U+201C/U+201D, guillemets U+00AB/U+00BB, low-9 U+201E/U+201A, CJK corner brackets U+300C..U+300F) is never
# anything but a delimiter, so it goes unconditionally. The SINGLE family (ASCII "'", U+2018, U+2019) is two
# different characters wearing one glyph: in `don't` and `Brazil's` it is an APOSTROPHE -- part of the word,
# and deleting it would corrupt the very restatement this normalization exists to keep honest -- while in
# `the co-op said 'no relief'` it is a delimiter. The test is POSITIONAL and needs no lexicon: a single-quote
# glyph FLANKED BY WORD CHARACTERS ON BOTH SIDES is an apostrophe and SURVIVES; every other occurrence is
# delimiter usage and is dropped. (U+2019 is the typographic apostrophe as well as a closing quote, which is
# exactly why the rule cannot be a character list.)
# THE RESIDUAL, STATED: a trailing plural possessive (`roasters' margins`) is not flanked, so it loses its
# apostrophe -- one glyph out of a line that is already a restatement rather than a quotation. That is the
# direction to be wrong in: the alternative rule ("keep it when the word ends in s") would let
# `said 'the frost is bullish for roasters'` ship an UNTERMINATED delimiter, which is defect (b) itself.
_SCAFFOLD_QUOTE_RX = re.compile(
    r'["\u201C\u201D\u00AB\u00BB\u201E\u201A\u300C-\u300F]'   # never an apostrophe -> a delimiter
    r"|(?<!\w)['\u2018\u2019]|['\u2018\u2019](?!\w)")         # single family: UNFLANKED == delimiter

# \u2500\u2500 THE UNSPACED-DELIMITER CORNER, CLOSED (round-3 LOW, 2026-08-05) \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
# `_SCAFFOLD_QUOTE_RX` alone reads a single-quote glyph flanked by word characters on BOTH sides as an
# apostrophe. That is right for `don't` and wrong for an UNSPACED delimiter: in `said'we are outright
# bullish'after` both glyphs are word-flanked, so both survived as text and `reg.sanitize` then rewrote
# `bullish` -> `price-supportive` BETWEEN them -- defect (a), the misquote, at rung 1. MEASURED UNREACHABLE
# on the current corpus (no receipt carries the shape); closed anyway, because "no source writes that today"
# is a property of the corpus and not of the engine.
#
# THE RULE, IN THREE PARTS, AND EACH PART IS A DIFFERENT KIND OF CERTAINTY:
#
#   1. A PROVABLE APOSTROPHE IS NEVER TOUCHED, and it is provable in two shapes, both CLOSED GRAMMATICAL
#      CLASSES rather than vocabularies that grow -- which is what makes a lexicon admissible here where a
#      synonym list would not be:
#        (a) CLITIC SUFFIX -- the right-hand word-run is one of English's possessive/contraction endings
#            (s, t, d, m, ll, ve, re): `Brazil's`, `don't`, `we've`, `it'll`.
#        (b) ELISION PREFIX -- the left-hand word-run is one or two characters: `Cote d'Ivoire`, `O'Brien`,
#            `o'clock`, `l'annee`, `qu'`. THIS LIMB IS NOT OPTIONAL AND IT IS NOT THEORETICAL: `Cote
#            d'Ivoire` is the single most common proper noun in this platform's cocoa corpus, and a rule
#            without (b) refuses it -- degrading essentially EVERY cocoa receipt to rung 2, which is an off
#            switch wearing a fence's clothes. MEASURED before it shipped.
#      Part (a) is also what makes the pair scan safe: `Brazil's roasters don't` carries two word-flanked
#      glyphs enclosing three words, and a pair scan without it would demote both and corrupt both words.
#   2. A BALANCED PAIR OF UNPROVABLE GLYPHS == DELIMITERS. The remaining word-flanked glyphs are CANDIDATES;
#      they pair off in document order (1st with 2nd, 3rd with 4th, ...) and a pair is demoted to delimiters
#      iff the text strictly between them holds >= 2 whitespace-separated words. Two glyphs that ENCLOSE a
#      phrase are a quotation; one glyph is punctuation inside a word.
#   3. EVERYTHING LEFT OVER COSTS A RUNG, NOT A LIE. An UNPAIRED candidate (`said'we are bullish` with no
#      closer) and a pair enclosing fewer than two words are not provably delimiters, so the DROP leaves
#      them alone -- deleting a glyph the engine cannot classify is how `Cote d'Ivoire` becomes `Cote d
#      Ivoire`. The FENCE in `_scaffold_survives` is deliberately STRICTER than the drop and refuses any
#      glyph that is not a provable apostrophe, so such a bullet lands on rung 2: restatement dropped,
#      engine-authored text only, and IT STILL CITES. That asymmetry is the whole design. A drop that is
#      too eager corrupts a word the reader can see; a fence that is too eager costs one quieter bullet.
#
# WHY LIMB (b) DOES NOT REOPEN THE CORNER, which is the obvious objection to it. It can only misread an
# OPENING delimiter, and only after a one-or-two-letter token (`a'we are bullish'`). The CLOSING delimiter
# of the same quotation sits after the last word of the quoted phrase, which is almost never <= 2
# characters -- so it stays a candidate, is left unpaired, and the FENCE refuses the line. The misquote
# still cannot ship; what changes is that it costs a rung instead of a clean drop. Pinned in both
# directions rather than argued.
#
# THE RESIDUAL, STATED AND PINNED: a word-internal glyph that is neither limb -- `rock'n'roll`'s first
# glyph, a crop-year `2021'22` -- is a CANDIDATE. Alone it survives the drop and costs the bullet a rung;
# two of them enclosing >= 2 words are demoted and lose their glyphs. Both directions are a degrade or a
# cosmetic loss on corpus text the engine is RESTATING, never a misquote -- and the misquote is the only
# defect class this rule exists to make unreachable.
_QUOTE_CLITICS = frozenset({"s", "t", "d", "m", "ll", "ve", "re"})    # limb (a), the closed class
_QUOTE_ELISION_MAX = 2                                        # limb (b): `d'`, `O'`, `qu'` -- never `said'`
_QUOTE_FLANKED_RX = re.compile(r"(?<=\w)['\u2018\u2019](?=\w)")            # every word-flanked single glyph
_QUOTE_RUN_RX = re.compile(r"\w+")                            # the word-run on either side of one
_QUOTE_LEFT_RUN_RX = re.compile(r"\w+\Z")
_QUOTE_PAIR_MIN_WORDS = 2                                     # a pair encloses a PHRASE, or it is not a pair


def _quote_is_apostrophe(text: str, p: int) -> bool:
    """Is the word-flanked glyph at `text[p]` a PROVABLE apostrophe -- rule part 1, both limbs?"""
    right = _QUOTE_RUN_RX.match(text, p + 1)
    if right is not None and right.group(0).lower() in _QUOTE_CLITICS:
        return True                                           # (a) possessive / contraction suffix
    left = _QUOTE_LEFT_RUN_RX.search(text[:p])                # sliced, so \Z means what it says
    return left is not None and len(left.group(0)) <= _QUOTE_ELISION_MAX      # (b) elision prefix


def _quote_candidates(text: str) -> list[int]:
    """Offsets of the word-flanked single-quote glyphs that are NOT provable apostrophes (rule part 2's
    input). Only word-flanked glyphs are considered -- an unflanked one is already unconditionally a
    delimiter to `_SCAFFOLD_QUOTE_RX`, and asking this question about it twice could only disagree."""
    return [m.start() for m in _QUOTE_FLANKED_RX.finditer(text)
            if not _quote_is_apostrophe(text, m.start())]


def _quote_delimiter_offsets(text: str) -> list[int]:
    """Every offset this normalization is willing to CALL a delimiter: `_SCAFFOLD_QUOTE_RX`'s unconditional
    and unflanked matches, plus each member of a balanced candidate pair enclosing >= 2 words.

    ONE PRODUCER FOR THE DROP AND THE FENCE, for the reason the derivation leg reuses register's own
    function: two definitions of what a quotation mark is would drift, and the two halves would then
    disagree about the one thing the reader can see. Reads `_SCAFFOLD_QUOTE_RX` through the module global
    at call time so a test can neutralise the drop by name and watch the LADDER hold instead."""
    cuts = {m.start() for m in _SCAFFOLD_QUOTE_RX.finditer(text)}
    cand = _quote_candidates(text)
    for a, b in zip(cand[0::2], cand[1::2]):                  # ODD/EVEN pairing, in document order
        if len(text[a + 1:b].split()) >= _QUOTE_PAIR_MIN_WORDS:
            cuts |= {a, b}
    return sorted(cuts)


def _drop_quote_delimiters(text: str) -> str:
    """`text` with every delimiter offset removed, replaced by a SPACE exactly where removing it outright
    would MERGE its two neighbours into one token (`dry"wet"mix` must never become `drywetmix`).

    A blanket space would be safe too and is what the scaffold's own normalization used to rely on, since
    it collapses whitespace immediately afterwards. The footer does NOT collapse, so a blanket space put
    `said  the crop is gone  after` -- two stray double spaces -- in front of the reader on every row whose
    source used spaced delimiters. Deciding per glyph costs one lookup and leaves BOTH call sites right:
    the scaffold's output is byte-identical either way (the collapse absorbs the difference), and the
    footer row reads as ordinary prose. A neighbour that is ITSELF being dropped is looked through, so a
    doubled delimiter does not reintroduce the gap by the back door."""
    cuts = _quote_delimiter_offsets(text)
    if not cuts:
        return text
    cutset = set(cuts)

    def _spacer(p: int) -> str:
        lo, hi = p - 1, p + 1
        while lo >= 0 and lo in cutset:
            lo -= 1
        while hi < len(text) and hi in cutset:
            hi += 1
        left = text[lo] if lo >= 0 else " "                   # a string edge merges nothing
        right = text[hi] if hi < len(text) else " "
        return "" if (left.isspace() or right.isspace()) else " "
    out, prev = [], 0
    for p in cuts:                                            # every match above is exactly one character
        out.append(text[prev:p])
        out.append(_spacer(p))
        prev = p + 1
    out.append(text[prev:])
    return "".join(out)


def _quote_delimiter_residue(text: str) -> bool:
    """Does `text` still carry a single-quote glyph that is NOT a provable apostrophe, or any member of the
    unconditional family? THE FENCE'S QUESTION, and it is deliberately WIDER than the drop's (rule part 3):
    the drop must be sure before it edits a word, the fence only has to be sure before it trusts a line."""
    if _SCAFFOLD_QUOTE_RX.search(text):
        return True
    return bool(_quote_candidates(text))

# ── THE SCORER'S ABSENCE VOCABULARY, MIRRORED (round-2 MEDIUM, 2026-08-05) ────────────────────────────
# A receipted bullet may never READ as an absence, and the engine's own CASE-1 string is not the only way
# to say it: restated CORPUS text can carry 'not available' / 'not published' / 'no data' / 'record is
# silent' / 'not in the corpus' all by itself (6 of 6 probe shapes did, MEASURED). The scorer does not read
# the engine's constants -- `episode_absence_stated` reads `_NOT_KNOWN + _NO_CITABLE + _NO_PRICE_RECORD`
# (eval.py:1021) and `_absence_marked` reads `_NO_PRICE_RECORD` plus the R6 normalizing regex
# (eval.py:97-99) -- so a receipted bullet carrying any of them greens an absence pin on a window that HAS
# a receipt. That is the false-absence class, arriving through the corpus rather than through the engine.
#
# THE MIRROR IS THE `_SECTION_KINDS` IDIOM AND NOT A HAND COPY: `answer` cannot import `eval` (circular,
# and AST-pinned by a test), so the tuple lives here and a cross-import test asserts SET EQUALITY against
# the three scorer tuples, plus PATTERN equality against the regex. Vocabulary drift fails the suite; it
# cannot reach production as a silent fork. The regex is mirrored too because the R6 fold's own comment
# calls the tuple "a synonym treadmill" -- an interposed word ('no single priced move') defeats the
# substrings and not the regex, and the consequence here is only ever a degrade, never a green.
_SCAFFOLD_ABSENCE_MARKERS = (
    "not known", "not yet known", "not yet been", "no data", "not available", "wasn't published",
    "was not published", "not published", "not been published", "unavailable", "no citable item",
    "no cited item", "no citable source", "no dated item", "no dated source", "no citable evidence",
    "corpus is silent", "record is silent", "no source in this window", "not in this corpus",
    "not in the corpus", "not in this record", "no price record", "not in the price record",
    "no per-contract price record", "no price data", "no priced move", "price record does not",
    "price record is silent", "no single priced move", "no one priced move", "without a priced move",
    "not in the price data", "no magnitude", "no observed magnitude", "outside the price coverage",
    "before the price record")
_SCAFFOLD_ABSENCE_RX = re.compile(
    r"\bno\b[^.;!?]{0,40}?\bpriced?\s+(?:move|record|data|magnitude|response|change)\b"
    r"|\bwithout\b[^.;!?]{0,30}?\bpriced?\s+(?:move|record|magnitude|response)\b"
    r"|\bprice\s+(?:record|coverage|data)\b[^.;!?]{0,30}?"
    r"\b(?:does\s+not|doesn'?t|is\s+silent|never|cannot|can'?t|stops?|ends?)\b"
    r"|\b(?:outside|before|beyond|predates?)\b[^.;!?]{0,30}?\bprice\s+(?:coverage|record|data)\b",
    re.I)


def _has_episode_section(mech: str) -> bool:
    """Does this mechanism already carry a rendered Episodes section?

    THIS DETECTOR MUST BE AT LEAST AS WIDE AS `eval._episode_section`, and it is written to be EXACTLY
    as wide: `_has_episode_section(m)` is `eval._episode_section(m) is not None` for every m. `answer`
    CANNOT import `eval` (circular -- see _SECTION_KINDS), so the agreement is enforced by a unit test
    that imports both, the same idiom `_SECTION_KINDS` <-> `_FIXED_SCAFFOLD` already uses.

    WHY WIDTH IS THE LOAD-BEARING PROPERTY (D-DT-1 S1.3). The scorer deliberately accepts '##'..'######'
    and a NORMALISED heading PREFIX, so it scores '### Episodes', '## Episodes (3)' and
    '## Episodes -- dated'. A NARROWER detector here judges such an answer section-less, synthesizes a
    SECOND '## Episodes', and the reader sees two. Worse for scoring: `_episode_section` resets its body
    on EVERY matching heading, so the LAST section wins and the model's own enumeration is silently
    discarded -- a narrow detector would therefore replace correct model prose with engine prose and
    the row table would show nothing. Fence-aware for the same reason `_sectionize` is: a '## Episodes'
    inside a ```mermaid block is CONTENT, not a heading."""
    in_fence = False
    for line in (mech or "").split("\n"):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = _EPISODE_HEADING_RX.match(line)
        if m and str(m.group(1)).strip().lower().startswith(_EPISODE_HEADING_TEXT):
            return True
    return False


def _episode_section_body(mech: str) -> str:
    """The rendered Episodes section INCLUDING its heading line, or '' when none was rendered.

    Mirrors `eval._episode_section`'s walk exactly -- fence-aware, `##`..`######`, normalised heading
    PREFIX, the LAST matching section wins, the next non-matching heading closes it -- and differs from it
    in one deliberate way: the heading line is KEPT, because `_scaffold_survives` asserts on the heading
    as well as on the bullets. `_has_episode_section` is the boolean over the same walk (kept as its own
    loop because it is the detector the cross-import parity test pins, and a detector that can only be
    read through an extractor is a detector nobody checks).

    WHY THE RECONCILIATION MUST READ THE SECTION AND NOT THE WHOLE MECHANISM: the bullet-count check is
    what catches two bullets merged onto one physical line, and the model's own prose carries `- ` lines
    of its own. Counting over the whole mechanism would make that check meaningless in one direction and
    spuriously fail-closed in the other."""
    out: list[str] | None = None
    in_fence = False
    for line in (mech or "").split("\n"):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            if out is not None:
                out.append(line)
            continue
        m = None if in_fence else _EPISODE_HEADING_RX.match(line)
        if m:
            if str(m.group(1)).strip().lower().startswith(_EPISODE_HEADING_TEXT):
                out = [line]                          # entering (or re-entering) the section
            elif out is not None:
                break                                 # the next heading closes it
        elif out is not None:
            out.append(line)
    return "\n".join(out) if out is not None else ""


# ── D-PQ CAP-1: THE ABSENCE-BULLET CAP ON THE MODEL-AUTHORED SECTION ──────────────────────────────────
#
# THE MEASURED FAILURE (dcw_probe_v1 row `dcw_full_record_range`, 2026-08-07): a 24-bullet '## Episodes'
# section of which TWENTY read "no citable item in this window, so what happened is not narrated; no price
# record for this window." Eighty-three per cent of the section was the engine's own way of saying nothing.
#
# WHY D-RC-11's CAPS DID NOT FIRE, EXACTLY. They live inside the SYNTHESIS branch of
# `_maybe_scaffold_episodes`, which is reached only when the model rendered NO section of its own. Here the
# model DID render one -- `episodes_model_authored: True`, `_has_episode_section` returned early at the top
# of the function, and every cap below it was skipped by construction. The knob existed and the shape it
# was built for walked past it. That is the whole bug: the cap was attached to the PRODUCER instead of to
# the SECTION.
#
# THE LAW, applied identically to both producers: absence bullets are capped at `max_absence` (the existing
# knob, default 6) AND may never be a MAJORITY of the section. Majority is the sharper of the two on this
# shape -- 20 of 24 is past a majority long before it is past six -- and it is arithmetic, not taste:
# keeping A absence bullets beside P present ones is a majority exactly when A > P, so the ceiling is
# min(max_absence, P). Bullets are dropped from the END, so the surviving section keeps its chronological
# order and its earliest windows.
#
# AN ABSENCE BULLET IS A TWO-PART TEST, both deterministic: it carries a NO-RECEIPT marker from the
# scorer's own vocabulary AND it carries no `[E` handle. The handle clause is what stops a receipted
# bullet whose restated corpus text happens to say "the record is silent on X" from being culled as
# absence -- the same false-absence-through-the-corpus class `_SCAFFOLD_ABSENCE_MARKERS` documents. The
# marker tuple is the `_NO_CITABLE` half ONLY: `_NO_PRICE_RECORD` says a priced magnitude is missing, which
# is true of most receipted historical windows and is not an empty bullet.
_SCAFFOLD_NO_RECEIPT_MARKERS = (
    "no citable item", "no cited item", "no citable source", "no dated item", "no dated source",
    "no citable evidence", "corpus is silent", "record is silent", "no source in this window",
    "not in this corpus", "not in the corpus", "not in this record")
_SCAFFOLD_BULLET_RX = re.compile(r"^\s*[-*]\s+\S")
# THE FLOOR (cycle-3 review). `min(max_absence, present)` alone is NON-MONOTONIC and starves exactly the
# answers that need the enumeration most: one receipted window kept ONE absence bullet, a two-bullet
# '## Episodes' section, which is BELOW the decks' own `min_episode_lines: 3` -- so the cap turned a thin
# answer into a failing one, and adding present content could SHRINK the section (present=0 -> max_absence
# bullets, present=1 -> one). The majority rule is a CEILING, never a target: floored at three, absence
# never outnumbers present by more than the deck's own minimum line count, the section can no longer fall
# under a pin it was built to satisfy, and `keep` is non-decreasing in `present` by construction. The floor
# sits ABOVE `max_absence` when a mode sets that knob below three -- deliberate: the knob tunes how much
# surplus absence a RICH section may keep, and it was never meant to shrink a sparse one below the minimum
# shape. (The other bound, `max_bullets`, still binds on the synthesis producer and caps the section there.)
_SCAFFOLD_ABSENCE_FLOOR = 3


def _is_absence_bullet(line: str) -> bool:
    """A bullet that names a window and then says nothing about it, with no receipt to show for it."""
    low = (line or "").lower()
    return ("[e" not in low) and any(m in low for m in _SCAFFOLD_NO_RECEIPT_MARKERS)


# RECORDED DIVERGENCE (H1b fold-1 F4), stated at BOTH sites so neither reader thinks the other agrees
# with it. This function's ITEM SCOPE is `_SCAFFOLD_BULLET_RX` -- '- ' and '* ' only. D-HP-15's
# `_episode_bullet_indices` walks the SAME SECTION BOUNDS (fence-aware, '##'..'######', normalised
# heading PREFIX, last section wins) but a WIDER ITEM SET: it also takes ORDERED items ('1. ', '2) ').
# The reason is the two passes' opposite failure directions. The cap pass is a SHAPE cap on the
# engine's own synthesized bullets, which are '- ' by construction; widening it would change a frozen
# cap law on a producer H1b may not touch. The validation pass is a FENCE over MODEL prose, and a
# fence that a numbered list walks straight through is fail-OPEN -- an ordered '## Episodes' section
# shipped a fabricated window uncharged and unstamped (the reviewer's driven reproduction). So the
# divergence is deliberate and one-directional: every item this function sees, that walk sees too.
# The agreement that still binds (and is tested on the detector corpus) is the SECTION BOUNDS.
def _cap_absence_bullets(mech: str, *, max_absence: int) -> tuple[str, int]:
    """(mechanism with the Episodes section's surplus absence bullets removed, n_dropped).

    Walks the LAST '## Episodes' section exactly as `_episode_section_body` does -- fence-aware,
    '##'..'######', normalised heading PREFIX, the next heading closes it -- so the two can never disagree
    about which lines are in scope. Non-bullet lines inside the section are untouched, and a section with
    no surplus is returned byte-identical (the same object), so a compliant answer is unmoved."""
    lines = (mech or "").split("\n")
    lo, hi, in_fence = None, None, False
    for i, line in enumerate(lines):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = _EPISODE_HEADING_RX.match(line)
        if not m:
            continue
        if str(m.group(1)).strip().lower().startswith(_EPISODE_HEADING_TEXT):
            lo, hi = i + 1, len(lines)                 # entering (or re-entering): the LAST section wins
        elif lo is not None and hi == len(lines):
            hi = i                                     # the next non-matching heading closes it
    if lo is None:
        return mech, 0
    idx = [i for i in range(lo, hi) if _SCAFFOLD_BULLET_RX.match(lines[i])]
    absent = [i for i in idx if _is_absence_bullet(lines[i])]
    present = len(idx) - len(absent)
    # THE DEGENERATE CASE, DECIDED RATHER THAN INHERITED: with ZERO present bullets the majority rule has
    # no non-degenerate solution (any positive count is a majority) and applying it literally would leave a
    # '## Episodes' heading with no bullets under it -- which is not an improvement on six that say
    # nothing, and would strand the eval's own episode pins on an empty section. There the HARD cap is the
    # whole law. Everywhere else the majority rule binds as a CEILING over the floor (see
    # _SCAFFOLD_ABSENCE_FLOOR): max(min(max_absence, present), 3).
    keep = (int(max_absence) if present == 0
            else max(min(int(max_absence), present), _SCAFFOLD_ABSENCE_FLOOR))
    if len(absent) <= keep:
        return mech, 0
    drop = set(absent[keep:])                          # keep the EARLIEST; surplus goes from the end
    return "\n".join(ln for i, ln in enumerate(lines) if i not in drop), len(drop)


# ══ D-HP-15 (H1b) -- SELECT-ORDER-CONNECT: THE SPAN-MEMBERSHIP VALIDATION PASS ════════════════════════
#
# THE MEASURED HOLE THIS CLOSES, and it is measured rather than argued (H1b recon, code lens). The
# D-HP-12 digit-lint is STRUCTURALLY BLIND to an episode span: `verify._claim_number_spans` exempts a
# bare four-digit year and a year-range short tail, so
# `bare_digit_verdict('- 1994-06..1994-08 -- frost: no citable item in this window ...')` is None and
# `_claim_numbers_in` is []. The consequence is exactly inverted from what the wave wants: an HONEST
# bullet that restates the injected prop-date COUNT ('(11 report dates)') loses its whole sentence to
# `_drop_bare_digit_sentences`, while a WHOLLY FABRICATED window sails through untouched. "The model
# never types a number" is therefore not yet true inside the one section whose load-bearing token is a
# date range -- and the section is the LAST surface on which the model still authors a dated ledger
# (plan 10.10), which is why G1 does not open until this lands.
#
# THE SHAPE IS DISPOSITION (b+), SELECT-ORDER-CONNECT IN PLACE (mini-plan s.1; folded to plan 10.13).
# The MODEL keeps authoring the section. Under `handle_prose` its SELECTION is validated: every bullet
# must name a window this turn's prompt actually carried. Its ORDER survives (the scorer's matching is
# order-insensitive, so nothing downstream reads bullet order as meaning). Its CONNECTIVE prose is
# untouched -- magnitudes are already policed by the digit-lint and the handle grammar, which is the
# wave, not this item. Full engine authorship of the section was REJECTED: it collides with D-RC-9,
# converts the five episode eval pins into scaffold tautologies, collapses the
# `episodes_model_authored` control-vs-treatment column, and opens a G2 fluency surface structurally
# larger than the 1.5% integrity upside (`c_strips.by_section['episodes']` = 15 of 974).
#
# MEMBERSHIP, NEVER PARSING, AND THE QUESTION IS UNIVERSAL, NOT EXISTENTIAL (H1b fold-1 FIX F1). The
# test is "is EVERY span-shaped token written in this bullet an EXACT MEMBER of the `timeline.month_span`
# tokens `_l2_blocks` STAMPED into `trace['episodes_injected']['spans']`" -- the same strings
# `render_line` showed the model and `eval._line_targets` matches on by ENDPOINT STRING EQUALITY.
#
# THE EXISTENTIAL FORM ('does the line contain ONE stamped token anywhere') SHIPPED IN THE FIRST BUILD
# AND WAS FAIL-OPEN, driven end to end by the fold-1 review: `- 2019-01..2019-03 -- the great
# disruption: milder than the 1994-06..1994-08 frost [E1].` sailed through with the FABRICATED lead
# window intact, `bullets_dropped=0`, `by_rule` clean -- one honest window backing a whole bullet's
# worth of invention. It is not an exotic shape either: the SELECT persona explicitly frees the model
# to write "how it sits beside the others", which is an INVITATION to name a second window in the same
# bullet. The consequence compounded: clause (e-ep)'s ceiling read CLEAN on rows that still shipped a
# fabricated window, so the gate that exists precisely because this item can ship gate-invisible could
# not see the residual. ONE UNSTAMPED TOKEN NOW CONVICTS THE WHOLE BULLET.
#
# TOKENIZING DOES NOT MINT A SECOND DEFINITION OF A WINDOW, and that distinction is the whole of why
# the universal form is still "membership". `_EPISODE_SPAN_SHAPE_RX` finds where a span-SHAPED token
# STARTS AND ENDS; it never interprets one -- no year, no month, no ordering, no calendar. The verdict
# is still `token in stamped`, exact and whole. Parsing a span back out and INTERPRETING it is what
# `timeline.month_span`'s own docstring names as how its three readers drift apart, and that is still
# refused here. `eval._line_targets` already tokenizes with `_YM_RX` before doing string equality, so
# this is the SECOND SPELLING of an existing tokenization, checked against it on a corpus (answer
# cannot import eval -- the AST pin -- so agreement is a cross-import TEST, the `_SCAFFOLD_ABSENCE_RX`
# idiom).
#
# THE SCANNER IS DELIBERATELY WIDER THAN WELL-FORMED, which is the F2 half. `- 11994-06..1994-08` and
# `- 1994-06..1994-08..2025-01` are span-SHAPED and are NOT members, so they die -- under plain
# substring containment they survived, because a stamped token is a substring of both. Matching whole
# tokens is what makes the fence boundary-correct in both directions; `- 994-06..1994-08` (a written
# token that CONTAINS a stamped one is still not equal to it) was already correct and stays correct.
#
# A BULLET THAT SPELLS THE WINDOW DIFFERENTLY ('1994-06 .. 1994-08') IS UNBACKED BY DESIGN: it is
# unbacked to the scorer too, and fail-closed is the direction this wave takes on every seam. A bullet
# carrying NO span-shaped token at all is unbacked for the reason stated on the function itself.
#
# WHY THIS IS VERIFICATION AND NOT RELEVANCE-GATING (the D-RC-9 reconciliation, stated in full in plan
# 10.13). D-RC-9 governs the RELEVANCE gate: it removes the MANDATE and the SYNTHESIS, never model
# freedom. It does NOT govern conviction-based remedies -- the treatment's verifier and render passes
# already delete convicted model prose everywhere else in the answer. An unbacked span IS a conviction,
# the episode-window analogue of `fabricated_citation`, so this drop is verification. No doctrine moves.
#
# THE CENSUS POSTURE, H1's own: THE PASS ALWAYS COUNTS AND MUTATES ONLY UNDER THE KNOB. The walk and the
# membership test run on BOTH arms -- no knob early-return -- so the control lane exercises the identical
# code path and a walk defect cannot hide behind the flag. `bullets_dropped` counts bullets ACTUALLY
# REMOVED, so a control row cannot carry the charge BY CONSTRUCTION rather than by a second `if`, which
# is what makes G1's clause (e-ep) ("`episode_span_unbacked == 0` on every control row") an INSTRUMENT
# CHECK rather than a restatement of the gating.
#
# THIS PASS MINTS NO STRIP SEAM, AND THE REASON IS X6's. It is a WHOLE-BULLET producer, so nothing it
# removes can leave a value slot empty in a SURVIVING sentence -- it deletes whole list items and their
# wrapped remainders, never a fragment of a sentence that stays on the page -- and `_SLOT_EMPTYING_SEAM_
# SRCS` would refuse it in any case. A seam minted here would be a licence-shaped record standing for
# nothing, which is exactly what X6 forbids for a whole-sentence producer. Pinned.
# RE-ARGUED AT FOLD-2 (G-A), because the move above the stack RETIRED THE SECOND REASON and it would
# otherwise stand as a false one: until this fold the pass ran after `_tidy_handle_debris` and after
# TIDY-2, i.e. where no seam CONSUMER remained in the turn, and that position was cited beside the
# whole-bullet argument. It now runs BEFORE both, so consumers do remain -- and the conclusion is
# unchanged because the load-bearing reason was always the first one: a producer that removes only
# whole items mints nothing a consumer could want. The pass still mints no seam, and the pin asserting
# it is re-anchored to the property rather than to the neighbourhood.
#
# THE HEADING IS NEVER REMOVED, and that is the `_cap_absence_bullets` precedent rather than an
# oversight: the remedy is deletion of CONVICTED prose, and a heading is not convicted. A section whose
# every bullet was unbacked therefore ships as a bare heading -- recorded as a residual in plan 10.13,
# not fixed here, because refusing the section is exactly the post-synthesis deletion D-RC-9 exempts.
#
# A CONVICTED BULLET TAKES ITS CONTINUATION LINES WITH IT (H1b fold-1 FIX F3). A wrapped bullet is one
# bullet, and removing only its first line left the convicted prose itself on the page: driven,
# `## Episodes\n- 2019-01..2019-03 -- invented:\n  the great disruption, no citable item.\n` became a
# heading followed by a DANGLING FRAGMENT of the very sentence the conviction was about. (POSITION
# CLAUSE RETIRED AT FOLD-2: this pass now runs BEFORE the seven-pass stack, so TIDY-2 *does* run later
# -- but TIDY-2 joins seams, and this pass mints none, so the fragment would still stand; the remedy
# stays the cut.) It is the Z4 orphan-fragment class H1 spent a fold arriving at "0 genuine fragments
# ship". The drop therefore extends from the bullet through the CONTINUATION LINES that follow it
# inside the section: non-blank, non-item, non-heading, non-fence, stopping at the first line that is
# any of those. An INNOCENT wrapped bullet keeps its continuation lines by construction -- the
# extension is computed only from convicted indices. `bullets_dropped` still counts BULLETS: the
# reader-loss unit charged to the ledger is the bullet, and a two-line bullet is not two losses.
#
# ORDERED ITEMS ARE IN SCOPE (H1b fold-1 FIX F4). `## Episodes\n1. 2019-01..2019-03 -- invented.\n` was
# entirely outside `_SCAFFOLD_BULLET_RX` -- the fabricated window shipped, nothing was charged, and
# because `spans_checked` was 0 no key was stamped at all. A fence whose posture is fail-CLOSED may not
# be walked through by a list marker. The widening is a RECORDED DIVERGENCE from
# `_cap_absence_bullets`' item scope, stated at both sites; the SECTION BOUNDS still agree exactly.
#
# AND THE KEY IS STAMPED WHENEVER THE SECTION EXISTS, even at `spans_checked=0` (the second half of
# F4). Stamping on `spans_checked` alone made "this row had no episode section" and "this row had a
# section whose items were never in scope" the SAME reading to a G1 reader -- which is the blind spot
# clause (e-ep)(ii)'s denominator exists to remove. `section_seen` rides in the census (omitted when
# False, the file's own idiom) and is what the two seams stamp on.
#
# ── WHERE THIS PASS RUNS, AND WHY IT MOVED (H1b FOLD-2 G-A -- the root of fold-1's residuals) ────────
# THE FENCE NOW RUNS BEFORE THE SEVEN-PASS STACK, immediately after `verify_citations` and its ledger,
# and specifically BEFORE the D-HP-12 digit lint. It used to run at the scaffold seam, AFTER the whole
# stack. The reason is one sentence, and it is H1's own staleness lesson applied to H1b: A FENCE MUST
# NEVER WALK TEXT A PRIOR PASS REWROTE.
#
# DRIVEN, END TO END, by the fold-1 verifier on `deep_hp`. `## Episodes\n1. 2019-01..2019-03 --
# invented.\n2. 1994-06..1994-08 -- real.` shipped the FABRICATED window to the reader with a clean
# `by_rule`, because `_drop_bare_digit_sentences` -- treatment-only, and until this fold upstream of
# here -- eats the ordinal MARKER as a bare-digit sentence. The fence then received ' 2019-01..2019-03
# -- invented.' with no marker at all, `_episode_item_indices` returned [] on the treatment arm (and
# [3, 4] on the control arm, where the lint never fires), and fold-1's F4 item widening was INERT on
# the only arm that can act on it. The same de-markering produced fold-1's second residual: an honest,
# fully-backed ordered item following a convicted bullet was no longer an ITEM to the fence, so it read
# as a CONTINUATION and was deleted UNCHARGED -- a reader loss and a ledger undercount against H1 FIX
# W2's own law.
#
# BOTH DIE AT THE ROOT WHEN THE FENCE WALKS MARKER-INTACT TEXT. An ordered item is an item; an honest
# ordered item after a convicted bullet is an ITEM, not a continuation; and the de-markered-residue
# heuristic the verifier offered as an alternative is never needed (it would have made the fence guess
# at what another pass had already destroyed, which is the same defect one layer down).
#
# WHAT THE MOVE KEEPS, CLAUSE BY CLAUSE, because each was a reason and not an ordering preference:
#   * AFTER `verify_citations` -- `claim_count` and checked/stripped are final, so folding this class
#     into the ONE ledger does not move the strip rate's denominators. UNCHANGED.
#   * OUTSIDE the seven-pass stack's MEMBERSHIP -- it now runs BEFORE the stack rather than after it,
#     and the law it obeys is unchanged: `_synth_ref_floor` mints episode refs above `len(uniq)` and
#     `_resolve_evidence_handles` kills exactly those, so a PRODUCER relocated into the stack is
#     destroyed by the treatment's own renderer. This pass mints nothing -- it only deletes convicted
#     model prose -- so running ahead of the stack costs it nothing and hands the stack a page whose
#     convicted bullets are already gone (the same "convictions first" direction the cap law gets).
#   * BEFORE `_maybe_scaffold_episodes` -- CONVICTIONS FIRST, SHAPE CAPS SECOND. UNCHANGED, and the
#     scaffold DID NOT MOVE WITH IT: the scaffold stays at D-DT-1's four-constraint seam, which is its
#     own law, and this pass is simply no longer its neighbour.
#   * BEFORE `_humanize_structured` -- one register pass over the survivors. UNCHANGED.
# WHAT THE MOVE CHANGES, STATED RATHER THAN LEFT FOR A READER: the A4b raw-draft interval this pass's
# deletions fall in. They were in `verified_* -> body_pre_sanitize` (the render seam's) and are now in
# `postverify_* -> verified_*` (the handle passes'). The deletions stay fully attributable -- the class
# is declared, charged through the one ledger, and stamped with its own trace key and denominator --
# and there is NO position that is both above the digit lint and below the `verified_*` capture, since
# the capture closes the stack the lint opens. Recorded at plan 10.15 with this reasoning.
#
# ── THE FULLY-FLOORED LANE CONVICTS (H1b FOLD-2 G-B -- fold-1's third residual) ──────────────────────
# `_l2_blocks` leg 1 stamps a floored record as `{'spans': [], 'windows': [], 'floored': ...}` AND STILL
# RENDERS its `DATED EPISODES` line, so `_episodes_on` fires and the persona still asks for the section
# -- while the prompt carries ZERO windows. Every window the model then writes is MINTED BY
# CONSTRUCTION. The first build returned early on `not stamped` and shipped them all, uncharged and
# unstamped, in the one lane where the fence's subject is guaranteed to be invention.
# NOW: `section_seen` is stamped BEFORE any early return (so (e-ep)(ii)'s "no key = no episode section"
# reading is true again), and the membership test runs against the EMPTY SET -- which no written window
# can be a member of, so every windowed bullet convicts. A bullet naming NO window is DECLINED there
# (see `_episode_bullet_unbacked`), so an honest prose-only episode section on a floored turn ships
# untouched. THE CENSUS POSTURE IS UNCHANGED: always counts, mutates only under the knob, no key and no
# charge on a control row.
# AND IT REACHES THE ONE-HOP LANE, deliberately: that body passes `injected=None`, so its stamped set
# is empty by construction and a one-hop turn whose model invents a window is now fenced too. The
# one-hop pass was "a structural no-op" only because nothing was stamped there -- which is precisely
# the floored lane's shape, and the fail-closed direction is the same one.
_EPISODE_SPAN_UNBACKED_CLASS: str = "episode_span_unbacked"

# THE ITEM SCOPE OF THE FENCE: '- ', '* ', AND ORDERED '1. ' / '2) '. Wider than `_SCAFFOLD_BULLET_RX`
# on purpose (see the recorded divergence at `_cap_absence_bullets`), and the widening is safe in the
# one direction that matters: every line the cap pass calls a bullet, this calls an item too.
_EPISODE_ITEM_RX = re.compile(r"^\s*(?:[-*]\s+\S|\d+[.)]\s+\S)")
# THE SPAN-SHAPE SCANNER -- WHERE A SPAN-SHAPED TOKEN STARTS AND ENDS, NEVER WHAT IT MEANS. A run of
# digits and hyphens, then one or more '..'-joined runs of the same, ending on a digit. TWO dots are
# REQUIRED, which is what keeps an ordinary decimal ('3.5', '1.2 million') out of the fence and what
# keeps the ' -- ' clause separator out of it. Maximal by greed, so a boundary-broken token
# ('11994-06..1994-08', '1994-06..1994-08..2025-01') is returned WHOLE and fails membership as a whole.
# SECOND SPELLING of `eval._YM_RX`'s tokenization, checked against it on a corpus in the grammar suite:
# no 'YYYY-MM..YYYY-MM' the scorer can see is invisible here, and this is deliberately the WIDER of the
# two (it also catches malformed shapes `_YM_RX` refuses, which is the fail-closed direction).
_EPISODE_SPAN_SHAPE_RX = re.compile(r"\d[\d-]*(?:\.\.[\d-]*\d)+")


def _stamped_episode_spans(injected: list | None) -> list[str]:
    """Every `timeline.month_span` token this turn's prompt CARRIED, in stamp order, deduped.

    READS `spans` AND NOTHING ELSE. `windows` carries the DAY-GRAIN pair beside it (D-OJ-16): matching
    is month-grain because that is the string the model was SHOWN, measurement is day-grain because a
    `YYYY-MM` end expands to month-end. A FULLY FLOORED record stamps `spans: []` present-and-empty, so
    it contributes nothing here without this function needing to know what `floored` means -- the same
    property `_maybe_scaffold_episodes`' leg 2 relies on."""
    out: list[str] = []
    for rec in (injected or []):
        if not isinstance(rec, dict):
            continue
        for sp in (rec.get("spans") or []):
            if isinstance(sp, str) and sp.strip() and sp not in out:
                out.append(sp)
    return out


def _episode_section_bounds(lines: list[str]) -> tuple[int, int] | None:
    """[lo, hi) of the LAST '## Episodes' section's BODY in `lines`, or None if there is no section.

    MIRRORS `_cap_absence_bullets`' walk exactly -- fence-aware, '##'..'######', normalised heading
    PREFIX, entering (or re-entering) resets so the LAST section wins, the next non-matching heading
    closes it. It is a SECOND SPELLING of that walk rather than an extraction of it because H1b's scope
    forbids editing `_cap_absence_bullets` (both cap laws are frozen for this build), and a duplicated
    walk is how two readers come to disagree about which lines are in scope. So the duplication is
    CHECKED: a unit test asserts the two agree on every mechanism in the detector corpus, in both
    directions, and on the two-section hazard shapes `_has_episode_section` exists for.

    The BOUNDS are what the two passes must agree on. Their ITEM SCOPE deliberately differs -- see the
    recorded divergence stated at both sites."""
    lo, hi, in_fence = None, None, False
    for i, line in enumerate(lines):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = _EPISODE_HEADING_RX.match(line)
        if not m:
            continue
        if str(m.group(1)).strip().lower().startswith(_EPISODE_HEADING_TEXT):
            lo, hi = i + 1, len(lines)                 # entering (or re-entering): the LAST section wins
        elif lo is not None and hi == len(lines):
            hi = i                                     # the next non-matching heading closes it
    return None if lo is None else (lo, hi)


def _episode_bullet_indices(lines: list[str]) -> list[int]:
    """The indices of the LIST ITEMS inside the LAST '## Episodes' section of `lines`.

    Items are `_EPISODE_ITEM_RX`: '- ', '* ' AND ordered '1. ' / '2) '. That last widening is H1b
    fold-1's F4 -- an ordered episode section was fail-OPEN and stamped nothing -- and it is a RECORDED
    DIVERGENCE from `_cap_absence_bullets`' item scope, written at both sites. The SECTION BOUNDS are
    the shared walk (`_episode_section_bounds`)."""
    bounds = _episode_section_bounds(lines)
    return [] if bounds is None else _episode_item_indices(lines, *bounds)


def _episode_item_indices(lines: list[str], lo: int, hi: int) -> list[int]:
    """The item lines in [lo, hi). ONE spelling of the item filter, shared by both readers of the walk:
    the public `_episode_bullet_indices` and the validation pass (which also needs `hi` for F3's
    continuation extension, and must not re-spell the filter to get it)."""
    return [i for i in range(lo, hi) if _EPISODE_ITEM_RX.match(lines[i])]


def _episode_span_tokens(line: str) -> list[str]:
    """Every SPAN-SHAPED token written in `line`, whole and in written order.

    SHAPE ONLY -- this says where a token starts and ends, never what it means. No year, no month, no
    calendar, no ordering: the verdict on each token is exact membership in the stamped spans. That is
    what keeps the universal test inside "membership, never parsing"."""
    return _EPISODE_SPAN_SHAPE_RX.findall(line or "")


def _episode_bullet_unbacked(line: str, stamped: set) -> bool:
    """UNIVERSAL, not existential (H1b fold-1 F1): EVERY span-shaped token must be a stamped member.

    A bullet carrying NO span-shaped token at all is unbacked too -- the persona's own shape rule is
    "ONE '- ' bullet per injected episode WINDOW and NOTHING else", so a bullet inside this section that
    names no window is not an enumeration of one. THAT CLAUSE HAS A SUBJECT, AND THE SUBJECT IS THE
    STAMPED SET (H1b fold-2 G-B): when the prompt carried ZERO windows there is no enumeration to be a
    bullet OF, so a token-less bullet is DECLINED rather than convicted -- which is what keeps the
    floored lane's honest PROSE section on the page while every MINTED window in it still dies below.
    With windows carried, the clause reads exactly as fold-1 pinned it."""
    toks = _episode_span_tokens(line)
    if not toks:
        return bool(stamped)
    return any(t not in stamped for t in toks)


def _episode_continuation(line: str) -> bool:
    """Is `line` the continuation of the wrapped item above it? (H1b fold-1 F3)

    A continuation is any non-blank line that does not START something else: not a list item, not a
    heading, not a fence. Blank ends the item, which is how a reader reads it too."""
    s = (line or "").strip()
    if not s or s.startswith("#") or s.startswith("```"):
        return False
    return not _EPISODE_ITEM_RX.match(line)


def _episode_line_is_backed(line: str, stamped: set) -> bool:
    """Does `line` NAME A STAMPED WINDOW? -- the belt-and-braces guard on F3's continuation cut.

    H1b FOLD-2 G-A's SECOND HALF, kept even though the fence's move above the digit lint removes the
    reproduction that motivated it (an honest ordered item, de-markered by D-HP-12's lint, read as the
    convicted bullet's continuation and was deleted UNCHARGED). ONE LINE AND ONE PIN, defence in depth:
    a cut that would swallow a line naming a window the prompt actually carried stops instead. A
    continuation of a convicted bullet cannot name a stamped window and still be that bullet's own
    wrapped remainder in any shape a reader would call one."""
    return any(t in stamped for t in _episode_span_tokens(line))


def _validate_episode_spans(structured: dict | None, injected: list | None, *,
                            handle_prose: bool = False) -> dict:
    """D-HP-15 SELECT: drop every model-authored episode bullet naming a window the prompt never carried.

    Returns `{spans_checked, bullets_dropped}` -- the DENOMINATOR and the CHARGE, in that order, and both
    are needed: a ceiling on drops with no count of bullets examined is a number no gate can read --
    plus `section_seen: True` WHENEVER A '## Episodes' SECTION EXISTED (omitted when it did not, the
    file's own idiom). That third field is the F4 half of fold-1: the two seams stamp the trace key on
    `section_seen`, not on `spans_checked`, so a G1 reader can tell "no section" from "a section whose
    items were never in scope". `spans_checked` counts ITEMS TESTED (one membership question each), not
    distinct span tokens.

    `section_seen` IS SET BEFORE EVERY LATER RETURN (H1b fold-2 G-B). It answers one question -- "did
    the model author a `## Episodes` section on this row" -- and the answer must not depend on whether
    anything was stamped, or the FULLY-FLOORED lane (where every window is minted by construction)
    reads to a G1 consumer exactly like a row that never had a section at all. That was fold-1's third
    verifier finding, and it falsified (e-ep)(ii)'s own "no key = no episode section" sentence in the
    one lane where the reading matters most.

    THE MEMBERSHIP QUESTION IS UNIVERSAL: every span-shaped token in the item must be an exact stamped
    member, and one unstamped token convicts the whole bullet (`_episode_bullet_unbacked`). The
    existential form -- one stamped token anywhere backs the line -- shipped in the first build and was
    fail-open on exactly the shape the SELECT persona invites; see the block comment above.

    AND UNIVERSAL MEMBERSHIP AGAINST AN EMPTY SET CONVICTS (fold-2 G-B, the second half). A floored
    record stamps `spans: []` present-and-empty and STILL renders its `DATED EPISODES` line, so the
    persona still asks for the section while the prompt carries no window at all: every span the model
    then writes is MINTED. The first build returned early on `not stamped` and shipped them. It now
    tests them like any other row -- against the empty set, so a written window is never a member --
    while a bullet naming NO window is declined (`_episode_bullet_unbacked`), which is what leaves an
    honest prose section untouched on exactly that lane.

    `handle_prose` IS THE ONLY GATE AND IT IS OMITTED WHEN OFF (the `_scaffold_cap_kwargs` idiom), so the
    control call is byte-identical and an injected fake carrying the older signature stays valid. It
    needs no companion `verifier.get("enabled")` test the way the seven-pass stack does: the serving
    seams resolve it through `_handle_prose_active`, which ALREADY returns False on the `GRAPHRAG_VERIFY=off`
    and `GRAPHRAG_MENTOR_VOICE=off` rollback lanes (section 2's mutual-exclusion law, one resolution).

    A CONVICTED ITEM TAKES ITS CONTINUATION LINES WITH IT, so a wrapped bullet cannot leave the convicted
    prose behind as a dangling fragment under the heading (F3). Non-item lines that follow an INNOCENT
    item, and every line outside the section, are untouched. THE CUT NEVER CROSSES A LINE THAT NAMES A
    STAMPED WINDOW (fold-2 G-A's guard, `_episode_line_is_backed`): the reader may not lose a window the
    prompt actually carried to a neighbour's conviction, and the ledger may not undercount if it did.

    NEVER RAISES and never partially writes: the mechanism is rebuilt once, from one index set, after
    every decision is made. An instrument must not cost an answer."""
    census = {"spans_checked": 0, "bullets_dropped": 0}
    try:
        mech = str((structured or {}).get("mechanism") or "")
        if not mech:
            return census                              # no prose -> no section, and that is the reading
        lines = mech.split("\n")
        bounds = _episode_section_bounds(lines)
        if bounds is None:
            return census                              # no section -> no key, and that is the reading
        lo, hi = bounds
        census["section_seen"] = True                  # ...BEFORE every later return (fold-2 G-B): the
        stamped_set = set(_stamped_episode_spans(injected))   # floored lane must not read as "no section"
        idx = _episode_item_indices(lines, lo, hi)     # ONE spelling of the item filter, shared
        if not idx:
            return census
        census["spans_checked"] = len(idx)
        drop = [i for i in idx if _episode_bullet_unbacked(lines[i], stamped_set)]
        if not drop or not handle_prose or not isinstance(structured, dict):
            return census                              # ALWAYS COUNTED, MUTATED ONLY UNDER THE KNOB
        cut = set(drop)
        for i in drop:                                 # F3: the wrapped remainder rides with its bullet
            for j in range(i + 1, hi):
                if not _episode_continuation(lines[j]):
                    break
                if _episode_line_is_backed(lines[j], stamped_set):
                    break                              # fold-2 G-A: the cut never crosses a stamped line
                cut.add(j)
        structured["mechanism"] = "\n".join(ln for i, ln in enumerate(lines) if i not in cut)
        census["bullets_dropped"] = len(drop)          # BULLETS, not lines: one bullet is one loss
        return census
    except Exception:  # noqa: BLE001 -- an instrument must never break a turn
        return census


def _scaffold_rows(injected: list | None, nodes: list | None) -> list[tuple] | None:
    """[(node label, injected span, receipt|None)] for every injected WINDOW, or None to DECLINE.

    The spans are the ones `trace['episodes_injected']` stamped -- the SAME `tl.month_span(e)` strings
    `render_line` showed the model and `eval._line_targets` matches bullets against -- so a synthesized
    bullet's window cannot be minted and its tier-1 endpoint match holds by construction.

    THE RECEIPT IS NOT ON THE TRACE RECORD, deliberately: adding it would change a record shape that is
    pinned byte-for-byte by the W4 suites and stamped on EVERY timeline turn, i.e. it would move the OFF
    arm. It is recovered from the node's own episode dicts, which are the very objects `_l2_blocks` read,
    and the recovery is VERIFIED index-for-index against the recorded span before it is used.

    FAIL-CLOSED, and this is the false-absence fence: if any window cannot be resolved to its episode
    dict the whole scaffold declines rather than emit a bullet whose receipt state is unknown. A declined
    turn is exactly today's behaviour (the omission stands, visibly, in the row table); a guessed one
    would put the CASE-1 'no citable item in this window' sentence on a window that HAS one -- false,
    reader-visible and engine-authored, which is the one thing Option A may never do."""
    by_id: dict[str, list] = {}
    for n in (nodes or []):
        nid = str(getattr(n, "id", "") or "")
        if nid and nid not in by_id:
            by_id[nid] = list(getattr(n, "episodes", None) or [])
    rows: list[tuple] = []
    seen: set[tuple[str, str]] = set()
    for rec in (injected or []):
        spans = [str(s) for s in ((rec or {}).get("spans") or [])]
        if not spans:
            continue                       # a FULLY floored node carries no window: _FLOOR_ABSENCE says
        node = str((rec or {}).get("node") or "")          # "write no bullet for it", so it gets none
        eps = by_id.get(node)
        if eps is None or len(eps) != len(spans):
            return None
        for sp, e in zip(spans, eps):
            if not isinstance(e, dict) or _tl.month_span(e) != sp:
                return None
            # D-RC-11 (node, span) DE-DUP, flagless -- a DEFECT fix, not a feature: `injected` carries
            # one record per (contract, node) while `by_id` is keyed by node alone, so a driver shared
            # by two routed contracts emitted every span TWICE (the 2026-08-05 Arabic probe shipped 7
            # exact duplicate bullets). One bullet per (node, span); the first record wins, matching
            # by_id's own first-wins key.
            if (node, sp) in seen:
                continue
            seen.add((node, sp))
            rows.append((node, sp, e.get("receipt")))
    return rows or None


def _receipt_item(receipt: dict | None, evidence: list | None) -> dict | None:
    """The turn's OWN evidence item a receipt was drawn from, or None.

    `timeline.episodes_for` builds `receipt` as {"date", "text"[:180]} from an in-window evidence prop of
    the node, so the item is always in this turn's `evidence` -- matching on (date, text prefix) recovers
    it. THE HALLUCINATION FENCE (D-DT-1 M6/S1.3): the synthesizer may cite ONLY an item already in this
    turn's evidence, never a new one, so an unmatched receipt DECLINES the whole scaffold rather than
    minting a handle that resolves to nothing."""
    d = str((receipt or {}).get("date") or "")[:10]
    t = str((receipt or {}).get("text") or "")
    if not d or not t:
        return None
    for h in (evidence or []):
        if not isinstance(h, dict):
            continue
        if str(h.get("date") or "")[:10] == d and str(h.get("text") or "").startswith(t):
            return h
    return None


def _synth_ref_floor(structured: dict, verifier: dict, n_positional: int) -> int:
    """The first ref a synthesized [E] may take: strictly above every ref already in play AND above the
    POSITIONAL citation namespace.

    THE DOC'S RULE IS `max(existing model refs) + 1`; the positional term is the fold that makes the
    rule satisfy the doc's own acceptance. `eval._cited_evidence` joins a prose handle to
    `out['citations']` POSITIONALLY (citations.unify numbers the deduped evidence E1..En), so a
    synthesized [E6] minted only above the model's refs would credit the SIXTH retrieved item -- moving
    `min_episodes_cited` / `min_episode_sources`, the two pins D-DT-1 S1.7 names as the sharpest check
    the A/B has ("if any of these move, synthesis has leaked into the model's surface"). Minted above
    `len(uniq)` the handle indexes past the end of that list, so it credits nothing and both pins keep
    measuring the MODEL exactly. The reader-facing join is unaffected: `_cited_sources_block` renders
    from verifier['resolved'], which this ref is written into with the receipt item's TRUE metadata."""
    hi = int(n_positional or 0)

    def _ref_int(x) -> int:
        s = str(x or "").strip().strip("[]").upper()
        s = s[1:] if s[:1] in ("E", "N") else s
        return int(s) if s.isdigit() else 0
    for s in ((structured or {}).get("sources") or []):
        if isinstance(s, dict):
            hi = max(hi, _ref_int(s.get("ref")))
    for r in (((verifier or {}).get("resolved") or {})):
        hi = max(hi, _ref_int(r))
    return hi + 1


def _splice_episode_section(mech: str, section: str) -> str:
    """Place the synthesized section where the persona instructs: after '## The record', before
    '## What to watch'. Fence-aware; no match -> append (which cannot disturb _FIXED_SCAFFOLD's relative
    order, so eval._scaffold_ok is unmoved either way)."""
    lines = (mech or "").split("\n")
    in_fence, at = False, None
    for i, line in enumerate(lines):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = _EPISODE_HEADING_RX.match(line)
        if m and any(str(m.group(1)).strip().lower().startswith(h) for h in _SCAFFOLD_BEFORE):
            at = i
            break
    body = section.rstrip("\n")
    if at is None:
        return (mech.rstrip("\n") + "\n" + body + "\n") if (mech or "").strip() else body + "\n"
    return "\n".join(lines[:at] + [body, ""] + lines[at:])


def _scaffold_restatement(receipt: dict | None, market_register: str) -> str:
    """The receipt's own wording, RESTATED on one physical line -- already sanitized, never quoted.

    THE MINT-TIME SANITIZE IS THE FIX (D-DT-1 fold 2026-08-05). `reg.sanitize`'s strip is CLAUSE-scoped
    (`register._SENT_KEEP` splits on `;` as well as `.!?`), so a receipt carrying an execution or
    valuation idiom in any clause used to have that clause DELETED by the `_humanize_structured` pass
    downstream of the seam -- taking the bullet's closing delimiter and its `[E]` handle with it and
    leaving `structured['sources']` + `verifier['resolved']` + the '## Sources' footer carrying a handle
    that appeared NOWHERE in the prose. Sanitizing HERE, in the turn's own register, means the text the
    bullet is composed from is already a fixed point: the later pass finds nothing to take.

    Everything else here is hygiene on corpus text the engine did not write: whitespace collapsed to one
    physical line (a bullet is read line by line), foreign handle-shaped tokens dropped, markdown heading
    tokens dropped (round-2 LOW-3 -- see _SCAFFOLD_MD_HEADING_RX; the collapse makes them mid-line, so they
    were never a second section, only a stray '##' in the reader's face), QUOTATION DELIMITERS dropped
    (round-3 BLOCKER + the round-3 LOW unspaced corner -- see _SCAFFOLD_QUOTE_RX and
    _quote_delimiter_offsets for the full statement and for why an apostrophe is not one),
    and the same visible '...' marker verify.py uses on a cut so a fragment is never passed off as the whole
    item.

    THE THREE DROPS RUN BEFORE `reg.sanitize` AND THAT ORDER IS LOAD-BEARING FOR THE QUOTE ONE. Sanitize
    rewrites words without ever seeing a delimiter, so a delimiter still present when it runs is a delimiter
    around text it may rewrite -- the misquote. Dropping first means there is no delimiter left to rewrite
    inside, and the CAP below then cannot cut an opening delimiter away from a closer that no longer exists.
    The post-sanitize half of the same fence lives in `_scaffold_survives`, on the rendered line.

    Empty output is a legitimate answer -- it means the receipt was ENTIRELY register-violating, and the
    bullet then degrades to its cite-only form rather than restating something the reader may not see."""
    raw = " ".join(str((receipt or {}).get("text") or "").split())
    if not raw:
        return ""
    raw = " ".join(_SCAFFOLD_FOREIGN_HANDLE_RX.sub(" ", raw).split())
    raw = " ".join(_SCAFFOLD_MD_HEADING_RX.sub(" ", raw).split())
    raw = " ".join(_drop_quote_delimiters(raw).split())        # a space, never '': two words never merge
    san = " ".join(reg.sanitize(raw, market_register=market_register).split()).strip(" .;:,!?").strip()
    if not san:
        return ""
    if len(san) > _SCAFFOLD_RESTATE_CAP:
        san = san[:_SCAFFOLD_RESTATE_CAP].rstrip().rstrip(".;:,!?").rstrip() + "..."
    return san


def _scaffold_section(plan: list[tuple], market_register: str, *, degraded: bool) -> str:
    """The whole '## Episodes' section, SANITIZED AT MINT TIME so the seam's own pass is idempotent on it.

    Sanitizing here does not weaken D-DT-1 M7's seam constraint 2 ("synthesized text must inherit
    reg.sanitize") -- it DISCHARGES it. The call site does not move: the section is still spliced into
    `structured['mechanism']` BEFORE `_humanize_structured`, which still runs over it with the identical
    register, so a raw node id is still humanized by `register.sanitize` and nothing about the seam's
    four constraints changes. What changes is that the engine no longer DEPENDS on that later pass to
    produce text it has not already inspected: the section it splices is the section the reader gets.

    `degraded=True` is the one-step fallback ladder: it drops every restatement clause and keeps the
    engine-authored remainder (span, label, handle, date, magnitude), which carries no corpus text at all
    and therefore cannot be strippable for anything a source said. The bullet STILL CITES -- that is the
    property that makes degradation an acceptable answer to a failed reconciliation and a decline the
    answer only when even this form does not survive.

    THE `date` SLOT IS `timeline.receipt_when`'s OUTPUT, not `receipt["date"]` (adversarial review
    2026-08-19, remedy (a)) -- so it reads `recorded <in-window date> (reported <publication date>)`
    whenever the receipt's two axes disagree, and BYTE-IDENTICALLY `recorded <date>` when they agree.
    The composition here is unchanged: this function still only interpolates whatever the plan carries,
    and the plan is built one producer up. The parenthetical adds no span-shaped token
    (`_EPISODE_SPAN_SHAPE_RX` requires '..'), no bare numeral `register._level_tokens` can see (ISO dates
    are `_NUM_NOISE`) and no absence or derivation vocabulary, so every leg of `_scaffold_survives` reads
    exactly as before -- asserted, not assumed, by the fences pinned in the scaffold suite."""
    lines = ["## Episodes"]
    for span, label, ref, date, restatement in plan:
        if ref is None:
            lines.append(f"- {span} -- {label}: {_SCAFFOLD_CASE1_BACKING}; {_SCAFFOLD_CASE1_MAGNITUDE}.")
            continue
        lead = f"- {span} -- {label}: the dated item [E{ref}] recorded {date}"
        body = f"{lead}{_SCAFFOLD_CASE2_REPORTS}{restatement}" if (restatement and not degraded) else lead
        lines.append(f"{body}; {_SCAFFOLD_CASE2_MAGNITUDE}.")
    return reg.sanitize("\n".join(lines), market_register=market_register)


def _scaffold_corpus_half(line: str) -> str:
    """The CORPUS-DERIVED remainder of a rendered bullet: the line with every engine-authored clause
    constant removed.

    Subtracting the engine's OWN clauses is what makes the two vocabulary fences below mean what they say.
    `_SCAFFOLD_CASE2_MAGNITUDE` is itself an absence marker ('no observed magnitude' is in the scorer's
    `_NO_PRICE_RECORD`), and so is the whole CASE-1 pair -- scanning the raw line for absence vocabulary
    would therefore refuse every bullet the engine writes, which is an off switch and not a fence.

    SUBTRACT-THE-KNOWN rather than split-on-the-verb, deliberately: a partition on
    `_SCAFFOLD_CASE2_REPORTS` is silently WRONG in the direction that matters if that verb is ever damaged
    or shadowed (it would report NO corpus text and pass a leaking bullet), whereas subtraction is
    over-inclusive -- it leaves the engine lead and the node label in the string -- and over-inclusion here
    can only cost a rung, never a leak. Returns '' for a CASE-1 bullet and for a degraded CASE-2 bullet,
    which is the truth about both: neither carries one byte a source wrote."""
    out = str(line or "")
    for fixed in (_SCAFFOLD_CASE2_MAGNITUDE, _SCAFFOLD_CASE1_BACKING, _SCAFFOLD_CASE1_MAGNITUDE):
        out = out.replace(fixed, " ")
    return out


def _scaffold_survives(section: str, plan: list[tuple]) -> list[str] | None:
    """The section's bullet lines, in order, IFF every planned bullet survived a sanitize pass intact --
    else None, which is the fail-closed signal.

    THIS IS THE POST-SANITIZE RECONCILIATION, and it is checked twice: once against the mint-time pass and
    once against the exact text `_humanize_structured` will produce. Six things are asserted per bullet,
    and each corresponds to a state the verifier proved reachable:

      * the section still has a heading -- '## Episodes' carries no terminal punctuation, so the strip's
        sentence unit runs THROUGH it into the first bullet and a banned first bullet can take the heading;
      * the bullet count is unchanged -- the strip's delimiter is `[.!?;]\\s+` and `\\s` matches '\\n', so
        dropping a clause can drop the NEWLINE that separated two bullets and merge them onto one physical
        line. A merged line is one line to `eval._episode_lines`, and worse, it can put a CASE-1 absence
        sentence on the same line as a receipted window's handle;
      * a receipted bullet still carries ITS OWN handle, its magnitude clause, and NO CASE-1 absence
        clause -- the red line "a CASE-1 absence clause on an episode whose receipt is set", enforced on
        the POST-sanitize text rather than only at mint;
      * a receipt-less bullet still carries both absence clauses, so it stays BACKED for
        `eval.min_episode_lines`' absence branch instead of degrading into a bare span;
      * THE FORMAT FENCE, on the rendered line (round-2 BLOCKER, 2026-08-05). Doc 1.3 states it as "no
        bare numeral except the ISO span" and "the span glyph is never `->`", and it was enforced only at
        composition, where it could not be enforced at all: the CASE-2 restatement splices CORPUS text and
        the level it carries reaches the reader without ever passing the PRE-seam `unbacked_levels`
        counter that `price_target_backed` reads. The round-1 argument -- "the handle shares its sentence,
        and register.unbacked_levels exempts a cited sentence" -- is FALSE TWICE, and both ways are
        MEASURED: (a) `register._SENT_ITER` splits on `;` as well as `.!?`, so it is CLAUSE-scoped and a
        handle in the lead clause does not back a level in a LATER clause of the same physical line
        ("Frost hit Sul de Minas; cash arabica traded at $2.45/lb ..." shipped a bare 2.45); (b) the
        exemption at `register.py:534` is VOIDED whenever the clause also carries a derivation-output
        marker, so "$2.45/lb, the median of the week" leaks even with the handle right there. 5 of 6
        ordinary-prose probes leaked. So the fence is asserted where the lie would be visible -- on the
        line -- with `register`'s OWN counter, and `derivation_ok=False` because a bullet is not a
        derivation unit and the fail-closed reading is the only honest one for engine-authored text;
      * NO DERIVATION-OUTPUT MARKER, NO ABSENCE MARKER AND NO QUOTATION DELIMITER IN THE CORPUS HALF.
        `register._deriv_output` is
        reused rather than re-listed -- a second copy of that vocabulary is a fork waiting to drift, and it
        is the same function `unbacked_levels` consults, so the two legs cannot disagree about what a
        derivation looks like. It also subsumes doc 1.3's "the span glyph is never `->`", since `->` and
        U+2192 are the first two alternatives in that pattern. The absence leg is the round-2 MEDIUM: a
        receipted bullet whose restated corpus text says 'not available' / 'no data' / 'record is silent'
        reads as an absence on a window that HAS a receipt, and the scorer reads its own vocabulary, not
        the engine's constants (see _SCAFFOLD_ABSENCE_MARKERS). The QUOTATION leg is the round-3 BLOCKER
        and it is the POST-sanitize half of the drop `_scaffold_restatement` performs at mint: the drop is
        what makes rung 1 honest, this leg is what keeps the promise true if the drop is ever weakened,
        narrowed or reordered behind sanitize. ONE PRODUCER, not a second copy, for the reason the
        derivation leg reuses register's -- two lists of what a quotation mark is would drift, and the
        two halves would then disagree about the one thing the reader can see. It is the one leg where
        the fence is deliberately WIDER than the drop: `_quote_delimiter_residue` refuses any glyph that
        is not a PROVABLE apostrophe, while the drop edits only what it can prove is a delimiter, so the
        unspaced corner's leftovers (round-3 LOW -- see `_quote_delimiter_offsets` part 3) land on rung 2
        instead of shipping. A drop that is too eager corrupts a word; a fence that is too eager costs a
        rung, and only one of those is visible to the reader as a lie.

    THE CONSEQUENCE OF THESE CORPUS-HALF LEGS IS A RUNG, NOT A REFUSAL, and that is the whole reason they
    belong HERE rather than in the composer. `_scaffold_survives` is what the ladder in
    `_maybe_scaffold_episodes` consults per rung, so a leaking restatement fails rung 1 and lands on rung 2
    -- DEGRADED: restatement
    dropped, engine-authored text only, and THE BULLET STILL CITES. A leak becomes a quieter honest bullet
    automatically; only a bullet that cannot survive even with every corpus byte removed reaches rung 3."""
    if not _has_episode_section(section):
        return None
    lines = [ln for ln in (section or "").split("\n") if ln.lstrip().startswith("- ")]
    if len(lines) != len(plan):
        return None
    for ln, (span, _label, ref, _date, _rs) in zip(lines, plan):
        if span not in ln:
            return None
        if ref is None:
            if _SCAFFOLD_CASE1_BACKING not in ln or _SCAFFOLD_CASE1_MAGNITUDE not in ln:
                return None
        elif (f"[E{ref}]" not in ln or _SCAFFOLD_CASE2_MAGNITUDE not in ln
              or _SCAFFOLD_CASE1_BACKING in ln):
            return None
        if reg.unbacked_levels(ln, derivation_ok=False):
            return None                                # a level the PRE-seam counter never saw
        corpus = _scaffold_corpus_half(ln)
        if reg._deriv_output(corpus) is not None:      # register's own vocabulary, never a second copy
            return None
        low = corpus.lower()
        if any(t in low for t in _SCAFFOLD_ABSENCE_MARKERS) or _SCAFFOLD_ABSENCE_RX.search(corpus):
            return None                                # an absence a SOURCE asserted, on a receipted window
        if _quote_delimiter_residue(corpus):
            return None                                # a delimiter a SOURCE wrote, on a line the ENGINE signs
    return lines


def _maybe_scaffold_episodes(structured: dict | None, verifier: dict | None, *,
                             injected: list | None, nodes: list | None,
                             evidence: list | None, n_positional: int = 0,
                             market_register: str = reg.FENCED, relevant: bool = True,
                             max_bullets: int | None = None, max_absence: int | None = None) -> dict:
    """D-DT-1: synthesize '## Episodes' when the model omitted it. Returns the TRACE UPDATES to stamp.

    THREE-LEG FIRE CONDITION, the `_episodes_on` discipline:
      1. GRAPHRAG_EPISODE_SCAFFOLD resolves on  -- default OFF; off => this returns {} before reading
         anything, so no trace key is written, `structured`/`verifier` are untouched and the ANSWER BODY
         is byte-identical to rev 75 (see _episode_scaffold_on for the scoping of that promise);
      2. >=1 injected record carries >=1 SPAN     -- the leg that stops a fully-floored turn from getting
         an empty heading, which is the exact defect timeline._FLOOR_ABSENCE exists to prevent;
      3. the model's mechanism carries NO Episodes section, by a detector at least as wide as the
         scorer's (`_has_episode_section`).

    LEG 1 SUBSTITUTES THE FLAG FOR THE DOC'S SEAM-GATE LEG, and the substitution is STATED here rather
    than left to be inferred (D-DT-1 1.6 component 2 names the three legs as "seam gate true, no Episodes
    section, and >=1 injected record carrying >=1 span"). This function never evaluates `_episodes_on(vp)`,
    because leg 2 ALREADY IMPLIES IT: a stamped span exists only where `_l2_blocks` rendered a
    `tl.render_line`, every such line opens with `timeline._head`'s `LINE_PREFIX`, and `_episodes_on` is
    exactly `_timeline_on() and LINE_PREFIX in vp` over the volatile prompt that line was written into.
    So `spans` non-empty => LINE_PREFIX in the prompt => the seam gate held. Re-reading the gate here
    would also require threading `vp` into a function that has no other use for it. Pinned by a test, in
    both directions: the mechanical half (`render_line` starts with LINE_PREFIX) and the end-to-end half
    (on a turn that stamps a span, the assembled volatile prompt satisfies `_episodes_on`).

    RECEIPT-BRANCHING, off `e['receipt']` -- the same test `render_line` uses, so producer and
    synthesizer cannot drift:
      * receipt-less -> the CASE-1 shape, node id as label, both absence clauses VERBATIM;
      * receipted    -> the CASE-2 shape: an open RESTATEMENT (never a quotation -- see
        _SCAFFOLD_CASE2_REPORTS) carrying an ENGINE-MINTED [E] written to all THREE places a handle must
        exist in (the bullet, structured['sources'], verifier['resolved']) and recorded in
        verifier['synthesized_refs'] so an audit can subtract them from `resolved`. A receipted window
        can NEVER receive the CASE-1 absence sentence: the two branches are disjoint on one boolean and
        the false-absence path does not exist in code.

    SANITIZE-STABILITY IS PART OF THE THREE-PLACE RULE, not a separate concern (D-DT-1 fold 2026-08-05).
    Writing a handle to three places and then letting a downstream pass delete the FIRST of them produces
    exactly the state this function's own comments call impossible: a ref in `sources` + `resolved` + the
    reader's '## Sources' footer that appears in no prose. The section is therefore composed from
    ALREADY-SANITIZED text (`_scaffold_restatement`, `_scaffold_section`) and then RECONCILED against the
    exact bytes `_humanize_structured` will produce (`_scaffold_survives`). The ladder is fail-closed and
    has three rungs, in this order:
      1. the full section;
      2. the DEGRADED section -- every restatement dropped, so each receipted bullet keeps its span,
         label, handle, date and magnitude and carries no corpus text at all. It still CITES;
      3. decline, reason `sanitize_would_strip_the_bullet`, committing nothing.

    THE LADDER CARRIES THE FORMAT AND ABSENCE FENCES TOO, and that is why it is the only place they can
    live (round-2 BLOCKER + MEDIUM, 2026-08-05). Both failures are properties of RESTATED CORPUS TEXT --
    a price level the pre-seam counter never saw, a derivation-output marker, an absence phrase a source
    wrote -- and rung 2 removes every corpus byte from the bullet by construction. So a leaking receipt
    does not decline and does not ship: it renders the quieter honest bullet, and it still cites. The
    predicate is `_scaffold_survives`; the consequence is the rung it lands on.
    Nothing is written to `structured` or `verifier` until a rung passes, so a rolled-back ref is a ref
    that was never committed -- there is no orphan to clean up, on any path. And the false-absence
    sentence stays unreachable for a receipted window in EVERY rung: rung 1 and 2 both assert its absence
    on the post-sanitize line, and rung 3 renders no section at all.

    HANDLE REUSE BEFORE MINTING. When the model already declared the receipt's item AND wrote its handle
    in E-form, the bullet reuses THAT ref: correct attribution at zero cost, because the string was
    already on the page. A fresh ref is minted only otherwise, and it is minted OUT OF THE POSITIONAL
    CITATION NAMESPACE (see _synth_ref_floor) so it credits nothing either. Both branches are therefore
    delta-zero on `min_episodes_cited` / `min_episode_sources`.

    THE LABEL IS THE INJECTED LINE'S OWN, and its exposure is the MODEL'S exposure, neither better nor
    worse. `reg.sanitize` humanizes a CONTRACT-node id into its display name ('arabica_coffee' ->
    'ICE arabica coffee'), which can add a token the node id does not carry, and
    `eval._absence_label_ok` requires the label's tokens to be a SUBSET of the node's. That is equally
    true of a model bullet copying the same id verbatim, as the persona instructs. It cannot make the
    pin worse than not firing: with no section at all `episode_absence_label_fixed` reds on its
    non-empty guard anyway, so a synthesized section weakly dominates an omitted one on that key.

    THE RESIDUAL, STATED. `eval.min_episode_lines` requires every bullet to be BACKED, and its three
    branches are (a) an absence marker, (b) a year some CITED item is dated in, (c) a cited handle.
    CASE-1 bullets take (a) unconditionally. A CASE-2 bullet takes (c) on the reuse path and otherwise
    depends on (b) -- so on a turn where the model cited NOTHING dated in the receipt's year, the pin can
    still red on a correctly synthesized section. That is a false RED on a deterministic pin, visible in
    the row table, never a false green, and it is the price of refusing to move the two citation pins
    D-DT-1 S1.7 names as the A/B's sharpest check. The bullet carries the receipt's OWN date precisely so
    branch (b) gets the widest honest shot at it.

    DECLINE IS A THIRD STATE and it is stamped as one. `episodes_model_authored` is TRUE only when the
    MODEL wrote the section; a fail-closed decline reports False with a reason, because reporting the
    model as the author of a section nobody wrote would be the one lie this record must not carry.
    The doc writes the column as `not fired`, which is right in the two-state world it describes.

    KNOWN COSMETIC, NOT FIXED HERE, AND THE REASON IS THE POINT (round-2 LOW-2, 2026-08-05). When the
    citation verifier STRIPS the model's own handle for an item (`no_lexical_overlap`) the item's row
    survives in `structured['sources']` and in `verifier['resolved']`, so `_cited_sources_block` renders
    it. If the scaffold then mints a fresh ref for that same document -- and it must, because the reuse
    test requires the E-form string to be PRESENT IN THE PROSE, which a stripped handle is not -- the
    reader's '## Sources' list carries the same document under two refs. MEASURED end to end.
      * The ROOT CAUSE IS PRE-EXISTING AND NOT THE SCAFFOLD'S: "a stripped handle keeps its sources row"
        reproduces with the flag OFF, where the footer already renders a row for a handle that appears
        nowhere in the prose. Fixing that half would move the OFF arm and break flag-off byte-identity,
        which is the one promise this change may not cost.
      * REUSING THE STRIPPED REF -- the other candidate fix, and the one confined to the mint path -- is
        NOT provably safe under the three-place rule and is REJECTED on two independent grounds. It would
        put `[E<n>]` back into the prose for a citation the verifier deliberately REMOVED, i.e. the engine
        re-asserting a claim the verifier refused; and a newly-present E-form handle is newly COUNTED by
        `eval._cited_evidence`'s positional join, moving `min_episodes_cited` / `min_episode_sources` --
        the two pins D-DT-1 S1.7 names as the A/B's sharpest check, and the exact leak `_synth_ref_floor`
        exists to prevent.
    So the code is left untouched on both halves and the duplicate is recorded here, with a test that
    documents the CURRENT behaviour so the day it is fixed the fix is deliberate. It is cosmetic in the
    strict sense: both rows resolve to the same real document with its true metadata, and no handle in
    the prose points at anything but the item it names."""
    if not _episode_scaffold_on():
        return {}
    recs = [r for r in (injected or []) if isinstance(r, dict) and (r.get("spans") or [])]
    if not recs:
        return {}
    mech = str((structured or {}).get("mechanism") or "")
    if _has_episode_section(mech):
        # D-PQ CAP-1: the model wrote its own section, so no bullet here is the engine's to author -- but
        # the SECTION's shape is still the engine's to bound, and D-RC-11's caps never reached this branch.
        # Nothing else about the model-authored path moves: the stamp, the return shape and
        # `episodes_model_authored: True` are unchanged, and a section already inside the law is
        # byte-identical (`_cap_absence_bullets` returns its input).
        _max_a = int(max_absence if max_absence is not None
                     else _prm.get("serving.scaffold.max_absence", 6))
        _capped_mech, _n_abs = _cap_absence_bullets(mech, max_absence=_max_a)
        if _n_abs and isinstance(structured, dict):
            structured["mechanism"] = _capped_mech
        stamp = {"fired": False, "n_bullets": 0, "n_receipted": 0}
        if _n_abs:                                    # REPORTED, never silent (the D-RC-11 n_capped rule)
            stamp["n_absence_capped"] = _n_abs
        return {"episodes_scaffolded": stamp, "episodes_model_authored": True}

    def _declined(why: str) -> dict:
        return {"episodes_scaffolded": {"fired": False, "n_bullets": 0, "n_receipted": 0, "declined": why},
                "episodes_model_authored": False}
    # D-RC-11 RELEVANCE LEG -- deliberately AFTER the model-authored check above (a section the MODEL
    # chose to write on a non-episodic question is model judgment and is never touched; the gate removes
    # the SYNTHESIS, and its caller-side twin removed the persona MANDATE) and BEFORE any receipt work.
    # `relevant` arrives resolved from the seam (one bool, both producers); default True = the flag-off
    # path and every legacy caller, byte-identical by construction.
    if not relevant:
        return _declined("not_episodic")
    if not isinstance(structured, dict) or not isinstance(verifier, dict):
        return _declined("no_write_surface")           # the three-place rule needs both, or it is not three
    rows = _scaffold_rows(recs, nodes)
    if rows is None:
        return _declined("unresolved_window")
    # D-RC-11 NOISE CAPS (flagless since D-AM stage 3, with the retired relevance kill-switch).
    # The probe's synthesized sections ran 23-35 bullets, ~68% verbatim absence lines -- bounded
    # enumeration is already the house's accepted shape (timeline MAX_PER_NODE truncates per node
    # today); these bound the SECTION. Receipted rows are kept first (they carry the reader value),
    # absence rows fill up to their own cap, and the final list keeps the original (chronological)
    # order. Drops are stamped on the trace (n_capped), never silent.
    n_capped = 0
    if rows:
        # D-AM-10: the reasoning mode's caps OVERRIDE the params read (the params value is the
        # standard/dark path and stays the authority when no override arrives -- the D-RC threading
        # discipline: this function reads no environment and no mode name, only two integers).
        max_b = int(max_bullets if max_bullets is not None else _prm.get("serving.scaffold.max_bullets", 12))
        max_a = int(max_absence if max_absence is not None else _prm.get("serving.scaffold.max_absence", 6))
        keep: set[int] = set(i for i, r in enumerate(rows) if r[2])
        if len(keep) > max_b:                          # receipted alone over the cap: first max_b win
            keep = set(sorted(keep)[:max_b])
        # D-PQ CAP-1: the MAJORITY rule, the same law `_cap_absence_bullets` applies to the model-authored
        # section, stated once per producer because the two build their sections by different routes.
        # Absence bullets may never OUTNUMBER receipted ones, so the ceiling is min(max_absence, receipted).
        # SAME degenerate carve-out, same reason (see `_cap_absence_bullets`): with zero receipted rows the
        # rule has no non-degenerate solution and would render a heading with no bullets, so there the hard
        # cap is the whole law and this line is a no-op.
        # SAME FLOOR too (_SCAFFOLD_ABSENCE_FLOOR), and for the same reason stated there: the majority
        # rule is a ceiling, and one receipted window must not collapse the section under the decks'
        # `min_episode_lines`. `max_bullets` is unmoved and still bounds the section here.
        if keep:
            max_a = max(min(max_a, len(keep)), _SCAFFOLD_ABSENCE_FLOOR)
        n_abs = 0
        for i, r in enumerate(rows):
            if r[2] or len(keep) >= max_b or n_abs >= max_a:
                continue
            keep.add(i)
            n_abs += 1
        n_capped = len(rows) - len(keep)
        if n_capped:
            rows = [r for i, r in enumerate(rows) if i in keep]
    # A COPY, committed only on success. A decline can happen on the SECOND receipted window after the
    # first has already allocated a ref, and mutating verifier['resolved'] in place would leave an orphan
    # entry behind on a turn that rendered no bullet at all -- a resolved handle pointing at nothing,
    # which is precisely the state the verifier exists to make impossible.
    resolved = dict(verifier.get("resolved") or {}) if isinstance(verifier.get("resolved"), dict) else {}
    prose = f"{structured.get('tldr') or ''}\n{mech}"
    minted: dict[str, int] = {}                       # source_key -> ref (one ref per cited item)
    next_ref = _synth_ref_floor(structured, verifier, n_positional)
    new_sources: list[dict] = []
    synthesized: list[int] = []
    # PHASE 1 -- resolve every window to (span, label, ref|None, date, restatement). Refs are allocated
    # on COPIES; the composition and the reconciliation below decide whether any of it is ever committed.
    plan: list[tuple] = []
    for node, span, receipt in rows:
        if not receipt:
            plan.append((span, node, None, "", ""))
            continue
        item = _receipt_item(receipt, evidence)
        if item is None:
            return _declined("receipt_not_in_evidence")
        key = str(item.get("source_key") or f"{item.get('source')}|{item.get('date')}")
        ref = minted.get(key)
        if ref is None:
            for r, meta in resolved.items():          # the model already ledgered AND cited this item
                rr = str(r).strip().strip("[]")
                # The reuse test is the E-FORM STRING `eval._cited_evidence` itself joins on, not merely
                # "the model ledgered it". Reusing a ref the prose carries only as a BARE `[1]` would put
                # `[E1]` on the page for the first time and make that citation newly COUNTED -- moving
                # min_episodes_cited / min_episode_sources, which is the leak the ref floor exists to
                # prevent. Matched this way, reuse is provably delta-zero: the string was already there.
                if (isinstance(meta, dict) and rr.isdigit() and meta.get("source_key")
                        and str(meta["source_key"]) == str(item.get("source_key") or "")
                        and f"[E{rr}]" in prose):
                    ref = int(rr)
                    break
        if ref is None:
            ref = next_ref
            next_ref += 1
            txt = str(item.get("text") or "")
            resolved[str(ref)] = {"source": item.get("source"), "date": item.get("date"),
                                  "source_key": item.get("source_key"),
                                  "snippet": txt[:140] + ("..." if len(txt) > 140 else "")}
            new_sources.append({"ref": ref, "source": item.get("source"), "date": item.get("date"),
                                "note": "engine-rendered episode receipt (D-DT-1 scaffold)",
                                **({"source_key": item["source_key"]} if item.get("source_key") else {})})
            synthesized.append(ref)
        minted[key] = ref
        # THE RENDERED DATE IS THE RECEIPT'S IN-WINDOW DATE, with the publication date beside it -- the
        # SAME producer `timeline.render_line` shows the model (`tl.receipt_when`), never a second
        # spelling. Reading `receipt["date"]` here printed the PUBLICATION date bare under a span the
        # reader can see it sits outside of, on 567 of 567 newly-receiptable episodes and 37.5% of the
        # ones above the corroboration floor. `_receipt_item` above still joins on `receipt["date"]`,
        # which is why that key stayed the publication date; this slot is the READER's, not the join's.
        plan.append((span, node, ref, _tl.receipt_when(receipt),
                     _scaffold_restatement(receipt, market_register)))
    if not plan:
        return _declined("no_bullets")
    # PHASE 2 -- compose sanitize-stable, then PROVE it against the exact bytes _humanize_structured will
    # produce. Rung 1 full, rung 2 degraded, rung 3 decline; nothing is committed until a rung passes.
    chosen: tuple | None = None
    for _degraded in (False, True):
        section = _scaffold_section(plan, market_register, degraded=_degraded)
        if _scaffold_survives(section, plan) is None:
            continue                                  # the mint-time pass already took a clause
        spliced = _splice_episode_section(mech, section)
        post = reg.sanitize(spliced, market_register=market_register)
        kept = _scaffold_survives(_episode_section_body(post), plan)
        # The synthesized-ref check is the three-place rule's own closing leg, asserted on POST-sanitize
        # prose: a ref that reaches sources/resolved/the footer while its handle reaches no reader is the
        # orphan this whole ladder exists to make unreachable, so it is tested rather than reasoned about.
        if kept is None or not all(f"[E{r}]" in post for r in synthesized):
            continue
        chosen = (spliced, _degraded)
        break
    if chosen is None:
        return _declined("sanitize_would_strip_the_bullet")
    spliced, _degraded = chosen
    if new_sources:                                   # the SECOND and THIRD of the three places
        structured["sources"] = list(structured.get("sources") or []) + new_sources
        verifier["resolved"] = resolved
        verifier["synthesized_refs"] = list(verifier.get("synthesized_refs") or []) + synthesized
    structured["mechanism"] = spliced
    stamp = {"fired": True, "n_bullets": len(plan),
             "n_receipted": sum(1 for p in plan if p[2] is not None)}
    if _degraded:                                     # the rung is REPORTED, so a silent fallback is not
        stamp["restatement_dropped"] = True           # a thing the A/B can be reading without knowing
    if n_capped:                                      # D-RC-11: capped rows are REPORTED, never silent;
        stamp["n_capped"] = n_capped                  # key present only when the caps ran (flag on)
    return {"episodes_scaffolded": stamp, "episodes_model_authored": False}


# ══ D-DT-2 c1: trace['fork_basis'] -- the ENGINE-DERIVED license inventory ════════════════════════════
# THE ASK. `no_unbacked_fork` fires on TWO NUMERIC trace conditions and nothing else (divergence_nodes /
# reroute_pairs, both written by the numeric cascade engine alone), while the mentor persona licenses
# '## Where the record disagrees' at FOUR sites of which only ONE is trace-backed. On the two playbook
# rows the numeric basis is structurally absent and the QUESTION TEXT demands the section, so the pin is
# meeting a population it was not written for. c1 mints the inventory that lets a pin tell a licensed
# fork from a manufactured one -- and it changes no output.
#
# THE CIRCULARITY FENCE, AS AN ORDERING INVARIANT (V.4 X3). Every flag is derived from engine inputs
# assembled BEFORE synthesis -- the cascade trace, `_context_block`'s own driver list, the retrieved
# evidence and `trace['episodes_injected']` -- and NEVER from `structured`. Both serving bodies therefore
# mint it BEFORE the model call, which makes the circularity physically unreachable rather than merely
# forbidden: at the mint site there is no answer prose in existence to read. This matters because
# D-DT-1's scaffold now WRITES `structured['mechanism']` downstream, so a basis computed at the return
# statement from `mechanism` would be reading the engine's own output.
def _driver_conflict(graph, contracts: list[str] | None) -> bool:
    """L1a: opposing SAME-CONFIDENCE drivers on ONE target metric, read off the exact list
    `_context_block` renders to the model (`tgt = d.target_metric or tgt0`, same expression). Pure graph
    read, zero LLM, fully deterministic -- the one L1 clause that is."""
    buckets: dict[tuple, set] = {}
    for cid in (contracts or []):
        c = ((getattr(graph, "contracts", None) or {}) or {}).get(cid)
        if c is None:
            continue
        tgt0 = c.target_metrics[0] if c.target_metrics else "price"
        for d in c.drivers:
            buckets.setdefault((cid, d.target_metric or tgt0, d.confidence), set()).add(d.sign)
    return any({"+", "-"} <= signs for signs in buckets.values())


def _fork_basis(graph, contracts: list[str] | None, evidence: list | None, trace: dict | None) -> dict:
    """The four-flag license inventory stamped as trace['fork_basis'] (D-DT-2 c1).

      numeric         -- a DIVERGENCE or REROUTE actually fired (L3). EXACTLY today's
                         `divergence_nodes > 0 or reroute_pairs > 0`, so the basis-aware pin is a STRICT
                         SUPERSET of `no_unbacked_fork` and no turn that passes today can fail tomorrow.
      driver_conflict -- L1a, above.
      tier_mixed      -- L1b, and it is HONESTLY WEAK: it detects that the evidence the prompt SHOWED
                         spans more than one source_tier, never that two sources DISAGREE. Closing the
                         real clause needs a per-chunk (metric, period, value) claim tuple -- no such
                         extraction layer exists -- or an LLM judge, which would breach the judge-free
                         deterministic-pin standard this key was created under. Labelled weak here and
                         EXCLUDED from any future tightening, the way PHASE9_FIXCYCLE_PLAN.md:323-334
                         labels the existing dull teeth.
      episodes        -- L2/L4: >=2 episode WINDOWS were injected, so 'where do they disagree' has
                         something to disagree about. Nearly always true on a playbook row, which makes
                         the pin close to vacuous there -- the honest reading of a population whose whole
                         purpose is to disagree, and better recorded as vacuous than left red.

    ONE FUNCTION, TWO CALL SITES, AND THE ARGUMENTS DIFFER -- stated precisely, because the earlier
    wording ("spelled identically in both bodies") was not true of the call and reading it as true would
    mislead the next editor. What is identical is the FUNCTION and its POSITION (before the model call in
    both bodies, which is the circularity fence). What differs is what each body has to give it:

      | body                      | evidence argument                          | trace argument      |
      | `_answer_l2`              | the node-evidence flatten across `sg.nodes`| `sg.trace`          |
      | one-hop legacy (`answer`) | the body's own `evidence` list             | `{}`                |

    Both differences are forced and neither is a divergence to repair. The one-hop body assembles its
    evidence as one flat list already, so re-flattening would be a no-op; and `{}` IS that body's engine
    trace at the mint point -- it writes no `quantify` and no `episodes_injected` before the model call,
    so `numeric` and `episodes` are structurally False there and passing a real dict would not change a
    single flag. `driver_conflict` and `tier_mixed` are live on both. A future one-hop cascade or episode
    producer becomes correct by passing its trace here, with no other edit."""
    tr = trace or {}
    quant = tr.get("quantify") or []
    n_windows = _n_episode_windows(tr)          # D-CC-1: shared with the composition census (one producer)
    return {"numeric": bool(any((t or {}).get("divergence") for t in quant)
                            or (tr.get("quantify_reroute") or [])),
            "driver_conflict": _driver_conflict(graph, contracts),
            "tier_mixed": len({source_tier(str((h or {}).get("source") or ""))
                               for h in (evidence or []) if isinstance(h, dict)}) > 1,
            "episodes": n_windows >= 2}


# ── D-PQ HANDLE-1: THE [N] NAMESPACE RENDER (a literal handle must never reach the reader) ─────────────
#
# THE MEASURED FAILURE (dcw_probe_v1 row `dcw_us_ethanol_margin`, 2026-08-07). The shipped body carried
# NINE bare handles standing where a number belongs -- "U.S. total domestic corn consumption ... stands at
# [N16] for MY2025", "ending stocks ... at [N5] against total use of [N4]", "the September contract settled
# at [N6]". The reader was handed a token, not a figure.
#
# WHY THE VERIFIER DID NOT CATCH IT, EXACTLY. `verify._check_number_handle` charges a handle on TWO rules:
# `number_mismatch` (a stated magnitude disagreeing with the cited row) and `number_unbacked` (a stated
# magnitude no row carries). BOTH read the sentence's CLAIM NUMBERS. A sentence that states no number at
# all -- because the model put the handle WHERE the number should have been -- has zero claim numbers, so
# both rules pass vacuously and the token survives to the page. `index_out_of_range` did not fire either:
# `extra_number_calls` is REBOUND to a copy at the cascade seam (answer.py:1915) and `cq.quantify` appends
# its injected rows to that copy, so [N16] was IN RANGE against an 18-row list even though the orchestrator's
# own `number_calls` (the 10 agent lookups) stops at [N10]. The handle pointed at a real cascade row that
# came back EMPTY. Nothing in the chain is charged with "this handle resolved to nothing".
#
# THE FIX IS DETERMINISTIC AND HAS EXACTLY TWO DIRECTIONS, decided per TOKEN, never per model:
#   RESOLVED + standing in for the value  -> SPLICE the row's own value+unit in front of the handle. The
#       figure the model meant is on the row; the only thing missing was the render.
#   RESOLVED + attached to a stated number -> UNTOUCHED. That is the ordinary citation shape and moving it
#       would rewrite every correct answer in the estate.
#   UNRESOLVABLE + attached to a stated number -> DROP THE HANDLE ONLY. This is verify's own remedy for
#       `index_out_of_range` (it drops the token span), and the number itself has already answered to the
#       verifier's rules on its own merits.
#   UNRESOLVABLE + standing in for the value -> DROP THE WHOLE SENTENCE. The sentence promised a figure it
#       cannot produce; there is nothing to substitute and a de-handled "stands at  for MY2025" is worse
#       than silence. Whole-sentence drop is the register/verifier precedent (`_strip_banned_sentences`).
#       ...UNLESS THE SENTENCE ALSO CARRIES A RESOLVED HANDLE, in which case only the empty promise's own
#       CLAUSE goes and the backed content stays (see `_HANDLE_CLAUSE_OPEN_RX`).
#
# "STANDING IN FOR THE VALUE" IS A SYNTACTIC LOCALITY TEST, NOT A JUDGEMENT: the handle is IMMEDIATELY
# preceded by a value-introducing word ("stands at [N16]", "total use of [N4]", "fell to [N13]", "was
# [N11]") with nothing between the cue and the handle. That is precise in both directions and needs no
# sentence-level reasoning: if a figure HAD been stated it would sit in that slot, so "settled at 446 US
# cents per bushel [N1]" ends its prefix on 'bushel' and is untouched, while "settled at [N6]" ends on
# 'at' and is filled in.
#
# A DIGIT-PRESENCE TEST WAS TRIED FIRST AND IS WRONG: prose is full of digits that are not magnitudes.
# "The MY2025/26 ending stocks projection stands at [N5]" carries 2025 and 26; "As of June 2026 [N1] [N2]"
# carries a year. Both would have read as 'a number was already stated' and the first is exactly the
# measured defect. The cue test is blind to all of them by construction.
# D-PQ HANDLE-2: THE TOKEN IS NOT ALWAYS ONE HANDLE. `\[N(\d+)\]` matched a SOLITARY index and nothing
# else, so every GROUPED citation the model actually writes -- `[N13, N14]`, `[N3, N5]`, `[N1-N6]` with any
# dash variant -- was invisible to this pass AND to `verify._HANDLE` (same solitary shape), i.e. unchecked,
# unresolvable and unfootnoted. Measured on the two dcw passes + the covenant deck: 8 comma groups and 1
# en-dash range across 3 runs. The token is therefore matched WHOLE and its members enumerated, which is
# the only reading under which the prose <-> `## Sources` join can be total.
# ASCII SOURCE: the dash variants are built from CODEPOINTS (hyphen-minus plus U+2010..U+2015 and U+2212),
# the same discipline verify._QUOTE_EDGE states for its curly marks. Separators are the ones the corpus
# actually produced ("," / ";" / "&" / "and" / "/") plus the dash; anything else is not a group and stays
# the literal the reader would have seen anyway.
_N_DASHES = "-" + "".join(chr(c) for c in (0x2010, 0x2011, 0x2012, 0x2013, 0x2014, 0x2015, 0x2212))
_N_SEP = "(?:,|;|&|/|and|[" + _N_DASHES + "])"
# ══ D-HP-11/12 (H1) -- THE `[N1b]` TRAP, DEFUSED. THE SUFFIX IS PART OF THE MEMBER, NOT NOISE ═════════
# THE DEFECT, AS H0 RECORDED IT (10.4 item 1, and it is the wave's #1 RISK wearing a small hat): this
# token regex carried no `[a-z]?`, so `[N1b]` was INVISIBLE here -- while `cit.unify` genuinely MINTS that
# id (`_EXTRA_SUFFIXES`, citations.py:643-660; `ids == ["N1","N1b","N1c","N2"]` is pinned at
# test_cycle5_renderer_fixes.py:90), `_E_HANDLE_RX` already parses the [E] twin, and `verify._HANDLE`
# parses both. An invisible token is INERT DEBRIS: it reaches the reader as literal text -- exactly the
# D-PQ HANDLE-1 defect this whole pass exists to abolish.
# WHY H0 REFUSED TO WIDEN THE REGEX ALONE, AND WHY THAT WAS RIGHT: `_N_MEMBER_RX` was `N?(\d+)`, so a
# widened token would have resolved `[N1b]` onto CALL 1's HEADLINE ROW -- converting inert debris into a
# MIS-BINDING, which is a REAL, CITED, WRONG number and the one failure this wave cannot make strippable.
# THE FIX IS THEREFORE TWO-SIDED AND BOTH SIDES SHIP TOGETHER:
#   (1) the SUFFIX IS CAPTURED and travels with its index everywhere (`_n_handle_pairs`), so no consumer
#       can hold `1` without knowing it came from `N1b`; and
#   (2) `_number_handle_value` REFUSES to resolve a suffixed member (see its own note: a sibling row
#       EXISTS only where the prose STATED its value, which is what mints it, and under handle-prose the
#       prose states nothing -- so the honest verdict is UNRESOLVABLE, never "near enough, take the
#       headline"). Unresolvable then takes the SHIPPED ladder: drop / sever / kill. Debris stops reaching
#       the reader AND no wrong row is ever spliced. Deletion beats a fourth fence (D3).
# `_n_handle_members` KEEPS ITS EXACT `list[int]` SHAPE as a thin de-duplicated view on the pair producer
# (the `_claim_numbers_in` / `_claim_number_spans` idiom in verify.py, for the same reason): its callers
# and its pins are byte-identical, and only the two readers that need the suffix take the richer list.
#
# ══ H1 FIX Z8 -- THE WIDENING IS GATED ON THE TREATMENT, SO THE CONTROL ARM IS BYTE-IDENTICAL ═════════
# H1 shipped the `[a-z]?` widening on BOTH arms, priced as "one-sided: debris removed, nothing newly
# bound" (data/dhp_h1_suffix_exposure.json: 46 artifacts / 430 audited answers / 51,863 tokens; 5 suffixed
# tokens in model prose, 1 of them at `verified_*`). The measurement stands and the exposure is real, but
# the priced delta was NOT the whole delta: a suffixed token in a VALUE SLOT is `standin` + unresolvable,
# so on the CONTROL arm it now DELETES A WHOLE SENTENCE (reproduced: "US wheat exports were [N1b] this
# week." -> ""), and it moves the control arm's own `number_handles.unresolvable` / `sentences_dropped`
# census -- the two columns G1 clause (2) and D-HP-17 item 4 read. The orchestrator's byte-identity
# mandate is explicit, so the widening becomes the TREATMENT's token grammar and `_N_HANDLE_RX` is
# restored to its pre-H1 bytes.
# THE ARMS THEREFORE PARSE DIFFERENT TOKEN SETS, AND THAT IS RECORDED, NOT HIDDEN. Section 2's law (a
# flag that gates a STRIP RULE must be constant across arms, or the arm measures its own instrument) is
# satisfied in the only sense that binds here: the class this widening reaches is EMPTY on the control arm
# in the measured population except for ~1 token per 430 answers, and `handle_strip_rate` is
# arm-relative-only across this boundary. The residual control-arm exposure (inert `[N1b]` debris reaching
# a reader, D-PQ HANDLE-1's own defect) is a PRE-EXISTING defect that predates this wave and does not get
# fixed by an ungated strip rule inside an A/B -- it is recorded for the post-gate consolidation.
# ONE GRAMMAR PER ARM, SELECTED ONCE: `_n_token_rx(handle_prose)`. Every OTHER consumer of `_N_HANDLE_RX`
# (the footer scan, the clone de-dup, the resolved-handle probe) keeps the narrow one on BOTH arms, and
# that is correct rather than lazy: a suffixed member is refused by `_number_handle_value`, so no suffixed
# token can survive `_resolve_number_handles` on the treatment lane for a later pass to meet.
_N_HANDLE_RX = re.compile(r"\[N\d+(?:\s*" + _N_SEP + r"\s*N?\d+)*\]")           # pre-D-HP bytes: control
_N_HANDLE_HP_RX = re.compile(r"\[N\d+[a-z]?(?:\s*" + _N_SEP + r"\s*N?\d+[a-z]?)*\]")   # treatment only
_N_MEMBER_RX = re.compile(r"N?(\d+)([a-z]?)")
# A RANGE is exactly two indices joined by a dash -- `[N1-N6]` means six handles, `[N13, N14]` means two.
# Expansion is capped (a runaway "[N1-N400]" is not a citation) and never inverted.
# FIX Z8, THE OTHER HALF: A SUFFIXED ENDPOINT REFUSES THE RANGE READING. The endpoint suffixes are now
# CAPTURED, and a range wearing one is not expanded at all. The shipped form admitted `[a-z]?` on both
# endpoints and expanded over INTEGERS, so `[N1b-N3]` yielded `[(1,""),(2,""),(3,"")]` -- byte-identical
# to `[N1-N3]`, i.e. `N1b` PROMOTED to call 1's headline through the one syntax that skips the pair
# producer's whole reason for existing. Refusing the expansion drops the token to the MEMBER reading,
# where the suffixed member meets `_number_handle_value`'s refusal exactly as a suffixed scalar does.
_N_RANGE_RX = re.compile("\\AN(\\d+)([a-z]?)\\s*[" + _N_DASHES + "]\\s*N?(\\d+)([a-z]?)\\Z")
_N_RANGE_MAX = 24


def _n_token_rx(handle_prose: bool = False):
    """The [N] TOKEN GRAMMAR for this arm (FIX Z8). Treatment: suffix-aware. Control: the pre-H1 bytes."""
    return _N_HANDLE_HP_RX if handle_prose else _N_HANDLE_RX


def _n_handle_pairs(token: str) -> list[tuple[int, str]]:
    """The (1-based call index, SUFFIX) pairs a `[N...]` token cites, in written order, de-duplicated on
    the PAIR. `[N5]` -> `[(5, "")]`; `[N1b]` -> `[(1, "b")]`; `[N1, N1b]` -> `[(1, ""), (1, "b")]`, which
    is two DIFFERENT rows of one call and must stay two members.
    De-duplication is on the pair and not on the index, precisely so the headline and its sibling do not
    collapse into each other -- that collapse IS the mis-binding this producer exists to prevent.

    A RANGE WITH A SUFFIXED ENDPOINT IS NOT A RANGE (FIX Z8): it falls through to the member reading, so
    `[N1b-N3]` -> `[(1, "b"), (3, "")]` and the sibling id is refused downstream instead of promoted."""
    inner = token[1:-1].strip()
    rng = _N_RANGE_RX.match(inner)
    if rng and not (rng.group(2) or rng.group(4)):
        lo, hi = int(rng.group(1)), int(rng.group(3))
        if 0 < lo < hi <= lo + _N_RANGE_MAX:
            return [(i, "") for i in range(lo, hi + 1)]
    out: list[tuple[int, str]] = []
    for x, sfx in _N_MEMBER_RX.findall(inner):
        p = (int(x), sfx or "")
        if p not in out:
            out.append(p)
    return out


def _n_handle_members(token: str) -> list[int]:
    """The 1-based call indices a `[N...]` token cites, in written order, de-duplicated. A solitary
    `[N5]` returns `[5]` -- the pre-D-PQ-HANDLE-2 behaviour, byte for byte.

    A THIN VIEW on `_n_handle_pairs` (D-HP-11/12): the INDEX axis only, re-deduplicated so that a token
    naming a headline and its sibling (`[N1, N1b]`) still reports ONE index here. Every pre-D-HP caller
    -- the dedup re-point, the footer's cited-index scan, the census arithmetic -- asks an index question
    and gets the same answer it always did."""
    out: list[int] = []
    for i, _sfx in _n_handle_pairs(token):
        if i not in out:
            out.append(i)
    return out


def _n_handle_token(members: list[int]) -> str:
    """The canonical rendering of a (possibly narrowed) member list -- the shape the model itself writes."""
    return "[" + ", ".join(f"N{i}" for i in members) + "]"


def _n_handle_token_pairs(pairs: list[tuple[int, str]]) -> str:
    """`_n_handle_token`'s suffix-carrying twin: the canonical rendering of a NARROWED pair list, so a
    surviving sibling member is re-emitted as the id `cit.unify` actually minted (`N1b`) rather than
    silently promoted to its call's headline (`N1`) -- which would be the mis-binding by another route."""
    return "[" + ", ".join(f"N{i}{s}" for i, s in pairs) + "]"


_HANDLE_VALUE_SLOT_RX = re.compile(
    r"\b(?:at|of|to|from|by|near|around|about|versus|vs\.?|was|were|is|are|be|been|reads?|read|stood|"
    r"stands?|sits?|sat|reached|hit|printed|posted|came in at|carries|carrying|totall?ed|totals?)\s+$",
    re.I)
# A MIXED SENTENCE IS SEVERED, NOT KILLED (cycle-3 review). "Ending stocks were 1,200 [N2] against use of
# [N4]." is one sentence carrying TWO handles: [N2] resolved and standing beside a stated figure, [N4]
# unresolvable and standing in for one. The whole-sentence drop above is right when the sentence promised a
# figure and can produce NOTHING; here it destroys verified, receipted content to remove one empty promise.
# So when a sentence still carries a RESOLVED handle, only the unresolvable handle goes -- with its clause
# when the clause is severable, which is what keeps the remainder grammatical ("against use of" alone is
# worse than the sentence). SEVERABILITY IS SYNTACTIC AND DETERMINISTIC, the same discipline as the
# value-slot cue: the clause runs from the LAST connective (or ', ') between the sentence start and the
# handle, and failing that from the value cue the handle stands behind ("at [N4]" -> "at" goes too). The
# comma leg requires trailing whitespace so a thousands separator ("1,200") can never be a clause opener.
_HANDLE_CLAUSE_OPEN_RX = re.compile(
    r",\s+|\b(?:against|versus|vs\.?|compared|while|whereas|with|and|but|plus|alongside)\s+", re.I)
# never a decimal point: a boundary needs trailing whitespace or EOL (verify._verify_field's own _BOUND)
_HANDLE_BOUND_RX = re.compile(r"[.!?;](?=\s|$)|\n")
# ...AND never an INITIALISM's dot. `verify`'s _BOUND has no such clause because it only ever drops HANDLE
# spans; this pass drops whole SENTENCES, and on "U.S. total domestic corn consumption stands at [N16]"
# the naive boundary cuts after "U." and after "S.", so the drop starts mid-clause and leaves "U.S." glued
# to the next sentence. Measured on the row this guard exists for. The test is one letter standing alone
# after a space (or a bracket/quote, or another dot) -- 'U.'/'S.'/'e.'/'g.' -- which is exactly the
# abbreviation shape and never a real terminator ("the WASDE." ends on a letter that has letters before
# it, so it stays a boundary).
_HANDLE_ABBREV_RX = re.compile(r"(?:^|[\s(\[\"'])[A-Za-z]$|\.[A-Za-z]$")
# ...AND THE ABBREVIATION CLAUSE MUST NOT SWALLOW THE SENTENCE IN FRONT OF IT (cycle-3 review). An
# initialism's LAST dot is genuinely ambiguous: it is mid-sentence in "U.S. total domestic corn consumption
# stands at [N16]" and a REAL terminator in "Exports were strong from the U.S. The December contract
# settled at [N9]." Skipping it unconditionally widened the span across a COMPLETE, fully-backed sentence,
# and one empty handle in the widened span then deleted both (measured: the whole field went out with
# census sentences_dropped:1 -- a drop is only ever entitled to the clause that made the promise).
# THE DISCRIMINATOR IS WHAT FOLLOWS THE DOT, which is what every sentence splitter uses and the only signal
# available without a parser: whitespace then a capital opens a NEW sentence ('. The'), whitespace then a
# lower-case word continues the abbreviated one ('. total', '. consumption'). An initialism's INTERNAL dot
# ('U.' in 'U.S.') is followed by no whitespace at all, so it never matches here and stays skipped.
_HANDLE_SENT_START_RX = re.compile(r"[ \t]+[\"'(\[]*[A-Z]")


def _handle_sentence_span(text: str, pos: int) -> tuple[int, int]:
    """(start, end) of the sentence containing `pos` -- verify._verify_field's walk, plus the abbreviation
    clause above, and CLAMPED TO THE CONTAINING LINE.

    The line clamp is the outer fence on the same failure: whatever the sentence walk decides, a drop may
    never cross a line boundary. It is redundant with the '\\n' alternative in `_HANDLE_BOUND_RX` (never
    skippable) and is stated anyway, because the invariant belongs next to the span rather than inside a
    boundary alternation that a later edit could widen."""
    start, end = 0, len(text)
    for b in _HANDLE_BOUND_RX.finditer(text):
        if (b.group(0) != "\n" and _HANDLE_ABBREV_RX.search(text[:b.start()])
                and not _HANDLE_SENT_START_RX.match(text, b.end())):
            continue                                   # 'U.' / 'S.' / 'e.' / 'g.' -- an abbreviation, not an end
        if b.start() < pos:
            start = b.end()
        elif b.start() >= pos:
            end = b.end()
            break
    ls = text.rfind("\n", 0, pos) + 1                  # the containing line: [ls, le), newline included in le
    le = text.find("\n", pos)
    le = len(text) if le < 0 else le + 1
    return max(start, ls), min(end, le)


def _handle_clause_start(text: str, s0: int, start: int) -> int:
    """Where the severable clause standing in front of an unresolvable handle at `start` begins, inside the
    sentence that opens at `s0`. The LAST connective wins (the smallest severance that leaves prose), the
    value cue is the fallback, and the handle itself is the floor -- so this never returns a position
    outside `[s0, start]` and the caller's span is always a subset of the sentence it would have killed."""
    seg = text[s0:start]
    last = None
    for cm in _HANDLE_CLAUSE_OPEN_RX.finditer(seg):
        last = cm.start()
    if last is None:
        cue = _HANDLE_VALUE_SLOT_RX.search(seg)        # anchored at the end of `seg`: "... total use of "
        last = cue.start() if cue else len(seg)
    return s0 + last


def _splice_fmt(v) -> str:
    """CYCLE-7-AMEND (2026-08-08) -- THE SPLICE'S OWN RENDERER: reader precision, WITHOUT losing a digit
    the reader needs.

    Cycle-7 routed the splice through `cit._fmt` to stop 17 digits of a z-score reaching the page. `_fmt`
    is the FOOTER's formatter and carries two shapes a spliced figure cannot afford:
      * `,.0f` for |v| >= 1000 DROPS the decimals -- a 1052.25 c/bu soybean settle spliced as "1,052";
      * `%g` goes SCIENTIFIC below 1e-4 -- 0.00001234 spliced as "1.234e-05".
    Both are latent (no gate-4 body carried either shape), and both are wrong in the one direction that
    matters: the prose figure is what the reader trades off, and a rounded one is not a smaller version of
    the truth, it is a different number.

    THE RULE: %g's SIGNIFICANT-DIGIT precision (which is what made "-0.30632" out of -0.3063197017144927),
    rendered POSITIONALLY with thousands grouping and never in exponent form. Implementation is exactly
    that -- take `%.6g`, read back how many decimal places it implies (including through an exponent), and
    lay the value down at that many places. So the gate-4 shapes are byte-identical (15.17 -> "15.17",
    -0.3063197017144927 -> "-0.30632"), the >= 1000 arm keeps what it carried (1052.25 -> "1,052.25",
    1486837.4 -> "1,486,837" -- 6 significant digits leaves it no decimal to keep), and the small end stays
    positional (0.00001234 -> "0.00001234").

    THE FOOTER'S `_fmt` IS DELIBERATELY UNTOUCHED THIS CYCLE. Splice and footer can now disagree in the
    DIGITS for |v| >= 1000 (prose "1,052.25", `## Sources` "1,052"), which is a narrowing of cycle-7's
    one-renderer promise and is RECORDED AS A FOLLOW-UP, not smuggled in here: `_fmt` is the footer's shape
    across every citation surface and the share/artifact freezes, and re-cutting it is its own change with
    its own pins. A non-numeric value falls through to `str(v)`, `_fmt`'s own posture."""
    s = str(v).strip()
    try:
        f = float(s.replace(",", ""))
    except (TypeError, ValueError):
        return s
    if f != f or f in (float("inf"), float("-inf")):      # NaN/inf: nothing positional to write
        return s
    g = f"{f:.6g}"
    if "e" in g or "E" in g:
        mant, _, exp = g.lower().partition("e")
        dp = (len(mant.split(".", 1)[1]) if "." in mant else 0) - int(exp)
    else:
        dp = len(g.split(".", 1)[1]) if "." in g else 0
    return f"{f:,.{max(dp, 0)}f}"


def _number_handle_value(call: dict | None, idx: int, suffix: str = "", *,
                         magnitude_only: bool = False) -> str | None:
    """The value+unit `[N{idx}]` resolves to, or None when it resolves to NOTHING (out of range, an empty
    read, an errored/declined lookup). Routed through `cit.from_number` on purpose: the headline row, the
    unit fallback and the empty-status taxonomy are decided in ONE place, so a spliced figure and the
    `## Sources` line for the same handle can never disagree.

    CYCLE-7 (2026-08-08) -- THE FIGURE IS RENDERED THE WAY THE FOOTER RENDERS IT. `Citation.value` is the
    ROW's raw value, carried as a string for the drill-down; the `## Sources` LINE for the same row is
    `_fmt`-ed. Splicing the raw one put a full float repr on the reader's page, measured on gate-4 dcw
    pass2 `dcw_gas_nitrogen_squeeze`:
        prose   "sitting at -0.3063197017144927 sigma vs 5-yr mean [N2] -0.31 sigma"
        footer  "[N2] PINK SHEET natural_gas_eu_usd_mmbtu_zscore_5yr = -0.30632 sigma vs 5-yr mean"
    -- 17 digits of a z-score, beside its own correctly-rounded citation, on the same line. Covenant
    `ab_mech_frost` shipped "-0.00851709 z" the same way. ZERO occurrences in all three gate-3 runs, so
    this is a cycle-6 regression, not a legacy shape: FIX A's arrival is what put values in front of
    handles often enough to see it. The figure is therefore rendered at the footer's READER PRECISION.

    CYCLE-7-AMEND (2026-08-08): through `_splice_fmt`, NOT `cit._fmt` -- same precision, but thousands-
    grouped positionally and with the decimals kept above 1000 (a 1052.25 settle must not reach the reader
    as "1,052") and no scientific notation below 1e-4. See `_splice_fmt` for the measured shapes and for
    the recorded follow-up (the footer keeps `_fmt` this cycle, so the two can differ in the DIGITS for
    |v| >= 1000).

    ══ D-HP-11/12 (H1) -- A SUFFIXED MEMBER IS UNRESOLVABLE HERE, AND THAT IS THE WHOLE TRAP-DEFUSAL ════
    `suffix` is the letter off `[N1b]`. It is REFUSED rather than ignored, and the reason is measured, not
    cautious. A letter-suffixed id exists ONLY where `citations._mint_row_citations` minted one, and that
    producer is reached on exactly two paths -- `extra_number_citations(call, i, stated)` and
    `prose_completion_citations(calls, stated, ...)` -- BOTH of which require `stated`, the magnitudes the
    PROSE ITSELF WROTE (`orchestrator._stated_values`). Both serving bodies call `cit.unify(uniq,
    extra_number_calls)` with NO `stated` (answer.py's two `ev_cits` lines), so at the moment this pass
    runs NO sibling row exists on either body; and under handle-prose the model states no magnitude at all,
    so none can ever come into existence for it to bind to. THE ONLY REACHABLE MEANING OF `[N1b]` HERE IS
    A TOKEN THE MODEL INVENTED.
    Resolving it to call 1's HEADLINE would therefore print a REAL, CITED, WRONG number -- the one class
    no verifier in this tree can see (B7's re-ranked #1 risk) -- in exchange for saving a token the reader
    was never owed. So it resolves to NOTHING and takes the shipped ladder (drop / sever / kill), which is
    D3: deletion beats a fourth fence. If a future phase threads the turn's minted sibling ids down here,
    THIS is the function that gains the lookup, and its refusal becomes a miss instead of a guess.

    `magnitude_only` is D-HP-11's SIGN CLAUSE (see `_polarity_entry`): the splice writes abs(value) for a
    row whose metric is in the POLARITY TABLE, because under handle-only prose the model's own verb
    already carries the direction and the raw signed value would render "fell to -0.31" on every signed
    delta row. Default False keeps `_splice_fmt` BYTE-IDENTICAL for every other metric and every
    pre-D-HP caller."""
    if not isinstance(call, dict):
        return None
    if suffix:
        return None                    # D-HP-11/12: a sibling id nothing minted -- never the headline
    try:
        c = cit.from_number(call, idx)
    except Exception:  # noqa: BLE001 -- a malformed call record resolves to nothing, never an exception
        return None
    if c.value is None or not str(c.value).strip():
        return None
    unit = str(c.unit or "").strip()
    raw = str(c.value).strip()
    if magnitude_only:
        try:
            raw = str(abs(float(raw.replace(",", ""))))
        except (TypeError, ValueError):
            pass                       # unparseable -> the signed string, exactly as before
    return f"{_splice_fmt(raw)} {unit}".strip()


# ── CYCLE-7: ...AND THE SPLICE MUST NOT WRITE A FIGURE THE SENTENCE ALREADY CARRIES ────────────────────
# The same gate-4 row shipped the other half of the defect FIVE times in one paragraph:
#     "European natural gas was at 15.17 USD/mmbtu [N1] 15.17 USD/mmbtu as of the latest available date"
#     "Urea was at 453.1 USD/mt [N3] 453.1 USD/mt"    "DAP was at 783.8 USD/mt [N5] 783.8 USD/mt"
# The value-slot cue ("was at", "sitting at") only ever looked BACKWARD, so a writer who puts the marker
# in FRONT of its figure -- "was at [N1] 15.17 USD/mmbtu", which is exactly what this deck's writers do --
# reads as a handle standing in for a missing number, and the splice duplicates it. The z-score pair is
# the same shape with a rounding in it ("at [N2] -0.31 sigma" -> the raw -0.30632 spliced in front).
#
# THE TEST IS NUMERIC, NOT TEXTUAL, and it has to be: "-0.31" and "-0.30632" are the same figure written
# to different precision, and a string compare sees two different things. So the adjacent numeral counts
# as THIS figure when it is a correct rounding of it at its own written precision AND inside a relative
# ceiling -- the same two-clause reading of "the reader restated this number" that cycle-6's (frozen)
# verify amendment already ratified for strip decisions, restated here for a render decision.
#
# ADJACENT MEANS ADJACENT: only whitespace and opening punctuation may sit between the token and the
# numeral, on either side. A looser scan (the whole sentence, up to the next handle) suppresses a splice
# the handle genuinely owes whenever some OTHER row further along the sentence happens to carry the same
# figure -- and a bare "[N1]" facing the reader is D-PQ HANDLE-1's own defect, restored. Every one of the
# five measured duplications is immediately adjacent, so the strict reading is both sufficient and the
# only one that cannot regress the pass it lives inside.
#
# A SKIPPED SPLICE IS NOT A NEW CENSUS STATE. The token simply falls into the branch it always belonged
# in -- RESOLVED + attached to a stated number -> UNTOUCHED -- so `number_handles` keeps its four pinned
# keys and `substituted` counts what the reader's page actually received, which is what it has always
# promised to count.
#
# CYCLE-7-AMEND (2026-08-08) -- THE PREFIX SET IS ENUMERATED, NOT JUST THE BARE SHAPES. Cycle-7 shipped
# `[\s(\[*"']*` between the handle and the numeral, which leaves out the deck's OWN most common shape: a
# currency glyph. "Urea was at [N1] $453.1/mt" still duplicated to "...453.1 USD/mt [N1] $453.1/mt", and the
# cycle-7 pin file quotes `$453.1/mt` twice as the writers' idiom. The widening below is an ENUMERATION --
# currency glyphs, the approximation markers, the separating punctuation, and a currency WORD ("USD 453.1")
# -- and nothing else.
#
# IT IS STILL STRICT ADJACENCY. A BOUNDED window (at most four prefix tokens, each with its own optional
# whitespace) of ENUMERATED shapes, never "the rest of the sentence" -- so the HANDLE-1 guard the strictness
# protects (a bare "[N1]" facing the reader whenever some unrelated numeral further along happens to carry
# the same figure) is untouched. A LONE "-" is deliberately NOT a prefix token: it is the numeral's own sign,
# and consuming it would make the comparison sign-blind. The en-dash is out for the same reason
# `orchestrator._MINT_RANGE_LO_RX` reads it as a range separator; the em-dash and "--" are in.
_HANDLE_ADJ_TOKEN = (r"[(\[*\"']"                                        # cycle-7's own opening shapes
                     r"|[$€£]"                                           # currency glyphs: $ EUR GBP
                     r"|~=|~|(?i:c\.|about|roughly)"                     # the approximation markers
                     r"|[:,;]|--|—"                                      # separating punctuation + em-dash
                     r"|(?i:USD|EUR|GBP|BRL|MYR|CNY|ARS|ZAR|CAD|INR)")   # a currency WORD prefix
_HANDLE_ADJ_AFTER_RX = re.compile(
    r"\A\s*(?:(?:" + _HANDLE_ADJ_TOKEN + r")\s*){0,4}([-−+]?\d[\d,]*(?:\.\d+)?)")
_HANDLE_ADJ_BEFORE_RX = re.compile(r"([-−+]?\d[\d,]*(?:\.\d+)?)[\s)\]*\"']*\Z")
_HANDLE_ADJ_REL_TOL = 0.03


def _figure_already_stated(text: str, s0: int, s1: int, m, value: str) -> bool:
    """True when a numeral IMMEDIATELY beside the handle `m` already states the figure `value`.

    Reads at most one numeral on each side, inside the handle's own sentence `[s0, s1)`, with nothing but
    whitespace/brackets/emphasis marks in between. Any parse failure reads as NOT stated, so the fallback
    is cycle-6's behaviour (splice) rather than a silent drop of a figure the reader needs."""
    try:
        v = float(str(value).split()[0].replace(",", "").replace("−", "-"))
    except (TypeError, ValueError, IndexError):
        return False
    after = _HANDLE_ADJ_AFTER_RX.match(text[m.end():max(m.end(), s1)])
    before = _HANDLE_ADJ_BEFORE_RX.search(text[min(s0, m.start()):m.start()])
    for hit in (after, before):
        if hit is None:
            continue
        t = hit.group(1).replace("−", "-")
        try:
            pv = float(t.replace(",", "").lstrip("+"))
        except ValueError:
            continue
        d = len(t.split(".", 1)[1]) if "." in t else 0
        gap = abs(pv - v)
        if gap <= 0.5 * 10.0 ** (-d) and (not v or gap <= _HANDLE_ADJ_REL_TOL * abs(v)):
            return True
    return False


# ══ D-HP-13 (H1) -- THE POLARITY TABLE. ONE TABLE, TWO READERS, CLOSED BY ENUMERATION ═════════════════
# It is read by D-HP-11's SIGN CLAUSE (which metrics get abs() spliced) and by D-HP-13's DIRECTION CHECK
# (whether the model's verb agrees with the row's sign). ONE table on purpose: two tables would drift, and
# a drift means splicing a magnitude while checking a sign the splice no longer shows.
#
# A METRIC NOT IN THIS TABLE IS NOT CHECKED AND IS NOT abs()-ed. That is the entire safety argument, and
# the plan states why it must be: INVERSE-POLARITY METRICS ARE THE NORM IN THIS ESTATE -- "stocks-to-use
# fell" means "tightened", a negative spread delta means "widened" -- so a naive sign-agreement test
# produces SYSTEMATIC false positives whose remedy is DELETING CORRECT PROSE.
#
# THE CLASS-SIZE JUSTIFICATION IS AUTHORED BY ENUMERATION, NOT INFERRED. The draft cited
# `b_grammar.direct_read_of_an_already_derived_metric` at 50.3% as evidence "the class is large", but that
# field counts DERIVED metrics and its own note lists `su_ratio` and `avg_farm_price`, which carry NO sign
# semantics. DERIVED IS NOT SIGN-MEANINGFUL. The table's size is whatever the table says it is.
#
# WHAT IS DELIBERATELY EXCLUDED, EACH WITH ITS REASON (these are LEVEL facts, not CHANGE facts -- their
# sign is information the reader needs and the prose verb does NOT carry it):
#   *_z / *_zscore / *_sigma  -- "sitting at -0.31 sigma" is a POSITION relative to a mean. abs() would
#                                delete the fact; "rose"/"fell" beside it describe a different quantity.
#   *_spread / *_basis (and their deltas) -- the sign convention is per-leg (near minus far, or the
#                                reverse), so "widened" maps to either sign. UNCHECKABLE without the leg
#                                order, and guessing it is how a detector starts deleting correct prose.
#   *_ratio / *_pct (LEVELS) / *_rank / *_price / *_stocks (LEVELS) -- unsigned quantities; nothing to check.
_DIR_UP = frozenset((
    "rose rise risen rises rising increase increased increases increasing gain gained gains gaining "
    "grew grow grown grows growing climb climbed climbs climbing higher up added adds advance advanced"
).split())
_DIR_DOWN = frozenset((
    "fell fall fallen falls falling decline declined declines declining drop dropped drops dropping "
    "slip slipped slips slipping lower down shrank shrunk shrink shrinks contracted contracts "
    "ease eased eases easing retreat retreated"
).split())
# The two STOCK-MOTION verbs. Unambiguous ONLY on a stocks-change metric, so they live on that entry and
# nowhere else: "the spread built" is not English about a spread, and "the balance drew" is not about a z.
_DIR_STOCK_UP = frozenset("built build builds building rebuilt rebuilds accumulated".split())
_DIR_STOCK_DOWN = frozenset("drew draw draws drawn drawdown destocked depleted".split())
# suffix -> (sign convention, the verbs licensed for a POSITIVE value, the verbs licensed for a NEGATIVE
# one). Matched LONGEST-SUFFIX-FIRST, so `_stocks_delta` wins over `_delta` and keeps the stock verbs.
_POLARITY_TABLE: tuple[tuple[str, str, frozenset, frozenset], ...] = (
    ("_stocks_delta", "positive = stocks INCREASED", _DIR_UP | _DIR_STOCK_UP, _DIR_DOWN | _DIR_STOCK_DOWN),
    ("_stocks_change", "positive = stocks INCREASED", _DIR_UP | _DIR_STOCK_UP, _DIR_DOWN | _DIR_STOCK_DOWN),
    ("_pace_change", "positive = the pace ACCELERATED", _DIR_UP, _DIR_DOWN),
    ("_pct_change", "positive = the quantity INCREASED", _DIR_UP, _DIR_DOWN),
    ("_pct_chg", "positive = the quantity INCREASED", _DIR_UP, _DIR_DOWN),
    ("_yoy", "positive = up on the year", _DIR_UP, _DIR_DOWN),
    ("_mom", "positive = up on the month", _DIR_UP, _DIR_DOWN),
    ("_wow", "positive = up on the week", _DIR_UP, _DIR_DOWN),
    ("_delta", "positive = the quantity INCREASED", _DIR_UP, _DIR_DOWN),
    ("_change", "positive = the quantity INCREASED", _DIR_UP, _DIR_DOWN),
    ("_chg", "positive = the quantity INCREASED", _DIR_UP, _DIR_DOWN),
    ("_diff", "positive = the quantity INCREASED", _DIR_UP, _DIR_DOWN),
)


def _binding_clause(text: str, s0: int, pos: int) -> str:
    """The span the two BINDING checks read: from the last connective inside the sentence (or the
    sentence's own start) up to the handle at `pos`.

    IT IS NOT `_handle_clause_start`'s span, and the difference is measured, not stylistic. That function
    answers "what is the SMALLEST thing I may delete and still leave prose", so when a sentence carries no
    connective it falls back to the VALUE CUE -- which for "Stocks rose to [N1]" is just "to ", and the
    verb the direction check exists to read is on the other side of it. Reading the cue-anchored span
    would make D-HP-13 silent on the single most common shape in the corpus.
    The two are nested, so nothing is convicted outside what the remedy removes: this span always starts
    at or before `_handle_clause_start`'s, and it always sits inside the SENTENCE, which is what the
    remedy takes whenever no other resolved handle is there to justify a sever."""
    seg = text[s0:pos]
    last = 0
    for cm in _HANDLE_CLAUSE_OPEN_RX.finditer(seg):
        last = cm.end()
    return seg[last:]


def _polarity_entry(metric: str) -> tuple[str, str, frozenset, frozenset] | None:
    """The POLARITY TABLE row a metric name belongs to, or None -- and None is the common case by design.
    Longest suffix wins so a specialised entry is never shadowed by its generic parent. A metric carrying
    an EXCLUDED marker (`_z`, `_zscore`, `_sigma`, `_spread`, `_basis`) is refused outright even when it
    also ends in `_delta`: `spread_delta` and `zscore_delta` are exactly the inverse-polarity shapes the
    block note above says must never be checked, and a suffix match would otherwise admit them."""
    m = str(metric or "").strip().lower()
    if not m:
        return None
    if {"z", "zscore", "sigma", "spread", "basis"} & set(m.split("_")):
        return None                    # a LEVEL fact whose sign the prose verb does not carry
    hit = None
    for entry in _POLARITY_TABLE:
        # `endswith` OR the bare name: a card may serve the metric AS `stocks_delta`, with no qualifier in
        # front of it, and a suffix test alone would silently drop it to the generic `_delta` entry --
        # losing the two STOCK-MOTION verbs on exactly the family that owns them.
        if (m.endswith(entry[0]) or m == entry[0].lstrip("_"))                 and (hit is None or len(entry[0]) > len(hit[0])):
            hit = entry
    return hit


def _call_metric(call: dict | None) -> str:
    return str(((call or {}).get("query") or {}).get("metric") or "")


def _direction_sign_mismatch(clause: str, call: dict | None, idx: int) -> bool:
    """D-HP-13. True when the ONE direction verb standing in front of a handle disagrees with the SIGN of
    the row that handle resolves to. False whenever the question is not cleanly askable -- and every one
    of those refusals is deliberate, because THE REMEDY IS DELETION OF PROSE.

    THE FOUR REFUSALS, each closing a false-positive class the plan names:
      (1) the metric is not in the POLARITY TABLE            -> not sign-meaningful, or inverse-polarity.
      (2) the clause carries ZERO licensed verbs             -> nothing claims a direction.
      (3) the clause carries MORE THAN ONE licensed verb     -> no rule binds a verb to a handle in a
          multi-clause sentence, and inventing one is how a detector starts deleting correct prose. The
          draft was rejected in review for exactly this gap; the refusal IS the rule.
      (4) the row's value is 0 or unparseable                -> zero has no direction.
    THE SCOPE IS THE CONNECTIVE-DELIMITED CLAUSE, NOT THE SENTENCE, and that is the binding rule the
    plan demanded (it named none, which is why the draft was not measurable as written): the verb must sit
    in `_binding_clause(text, sentence_start, handle)` -- from the last connective to the handle. A verb
    in a NEIGHBOURING clause can therefore never convict this handle, and a verb this check does convict
    is always inside the sentence the remedy removes.

    WHY IT IS ADMISSIBLE WHERE THE CYCLE-10 REPAIR FENCE WAS NOT, and this belongs in the code and not
    only in a plan: a false positive here costs a SENTENCE; the repair fence's false positive cost a
    CORRUPTED NUMBER on the reader's page. That asymmetry is the whole argument. Rewriting "fell" to
    "rose" would be the repair path wearing a different hat and is refused (D3)."""
    entry = _polarity_entry(_call_metric(call))
    if entry is None:
        return False
    try:
        c = cit.from_number(call, idx)
        v = float(str(c.value).replace(",", ""))
    except Exception:  # noqa: BLE001 -- an unreadable row makes no sign claim
        return False
    if v == 0:
        return False
    _sfx, _conv, up, down = entry
    words = [w for w in re.findall(r"[A-Za-z]+", clause or "") if w.lower() in (up | down)]
    if len(words) != 1:
        return False
    w = words[0].lower()
    return (w in down) if v > 0 else (w in up)


# The YEAR / MARKETING-YEAR tokens a string can name. THREE ALTERNATIVES, and the split between them is
# the DECLARED / BARE distinction the clause side reads (`_period_years(declared_only=)`):
#   my / myb  -- an MY-prefixed crop year, with or without its second leg (`MY2025`, `MY2025/26`)
#   pa / pb   -- a bare SLASH-joined crop year (`2025/26`). The slash IS the declaration. A HYPHEN pair is
#                deliberately absent: `2026-05` is an ISO date fragment, and reading it as a crop year
#                would put a false scope on the clause side of a DELETION-ARMED check.
#   plain     -- a bare 4-digit year. Never a declared scope; far more often a reference year.
_PERIOD_TOKEN_RX = re.compile(
    r"\bMY\s?(?P<my>(?:19|20)\d{2})(?:\s*[/-]\s*(?P<myb>\d{2,4}))?\b"
    r"|\b(?P<pa>(?:19|20)\d{2})\s*/\s*(?P<pb>\d{2,4})\b"
    r"|\b(?P<plain>(?:19|20)\d{2})\b")


def _period_years(text: str, *, declared_only: bool = False) -> set[str]:
    """Every 4-digit crop/calendar year a string names, normalized. `MY2025/26` -> {2025, 2026}.

    `declared_only` keeps ONLY the forms that DECLARE a crop-year scope -- `MY2025`, `MY2025/26`,
    `2025/26` -- and drops the bare 4-digit year. IT IS THE CLAUSE SIDE'S READING, and the reason is a
    false-positive class this check would otherwise own: "above the 2015 low [N1]" names a REFERENCE
    year, not the scope of the figure in the slot, so a row dated 2026 would read as DISJOINT and the
    remedy would DELETE A CORRECT SENTENCE. A detector whose remedy is deletion does not get to guess
    what a bare year means (D-HP-13's own ceiling clause, applied to its sibling). The ROW side keeps the
    full reading: a row that names its period any way at all has named it."""
    out: set[str] = set()
    for m in _PERIOD_TOKEN_RX.finditer(text or ""):
        g = m.groupdict()
        if g["plain"] and not declared_only:
            out.add(g["plain"])
        lead = g["my"] or g["pa"]
        tail = g["myb"] or g["pb"]
        if lead:
            out.add(lead)
        if tail:
            out.add(tail if len(tail) == 4 else (lead[:2] + tail))
    return out


# ══ D-HP G1 REMEDIATION-3 M1 (2026-08-14) -- THE PERIOD AXIS READS THE HANDLE'S *OWN* SCOPE ═══════════
#
# THE MEASURED DEFECT, AND IT IS THE WHOLE OF G1's R11 FAILURE. The gate charged 25 `slot_scope_mismatch`
# events over 204 comparisons (12.3%) against a pre-registered ceiling of 15. A read-only replay of all
# six treatment invocations -- driven by the functions IMPORTED from this module rather than a model of
# them, and reproducing 11 of the 12 charged rows BYTE-EXACTLY on BOTH the numerator and the
# `scope_checked` denominator -- adjudicated every one of the 25 a FALSE POSITIVE. Real mis-bindings:
# ZERO. Ambiguous: ZERO. In each of the 25 the receipt's own period is EXACTLY the period the sentence
# attaches to that handle, so 25 correct, cited, receipted figures were deleted from readers' pages (the
# conviction is not a tally -- it empties `value`/`live` and routes the handle into the drop/sever/kill
# ladder at the charge site). Two shapes produced them, and NEITHER is 10.19.4's range/era suspicion --
# that hypothesis is REFUTED as this population's generator (not one of the 25 has a range or an era-span
# on either side, and a range-aware intersection rescues ZERO of them).
#
#   SHAPE A (23 of 25) -- THE WINDOW ENDED AT THE HANDLE. `_binding_clause` returns `text[s0:pos]`, so on
#   the corpus's dominant era-pair grammar -- "from [N5] in MY2023 to [N4] in MY2024" -- the span read for
#   [N4] is "...from [N5] in MY2023 to ", whose only declared year is the PREVIOUS SIBLING'S. The handle's
#   own "in MY2024" sits one character past the window's right edge and is invisible. A sibling's year
#   convicted, every time, on 23 separate occasions.
#
#   SHAPE B (2 of 25) -- THE ROW SIDE PARSED A RENDERING. `row_years` came off `str(c.label)`, and that
#   string carries `citations.from_number`'s PROVENANCE TAIL ("(latest available 2026-05-29; as-of
#   2026-08-06)"). On a SERIES read the query names no period, so `_period_label` prints none and the row
#   side's ONLY years were two PUBLICATION DATES: `ab_rank_cocoa_origin`'s "2024/25 cocoa year" claim was
#   convicted against {2026} while the receipt's own headline row IS period "2024/25". The same tail ran
#   the other way too, MASKING 2 further shape-A false positives by inflating the row side on 131 of 186
#   cited comparisons -- so the shipped instrument mis-read 27 of 206, in BOTH directions at once.
#
# THE THREE RULES THAT REPLACE THEM, and the ORDER matters because a widened window is itself
# deletion-armed. THE MEASUREMENT THAT FORBIDS THE OBVIOUS FIX, run before this code was written: a plain
# widened window (left bound at the previous sibling, right bound at the next) scores 18 convictions over
# 364 checks -- it kills all 25 and MINTS 18 NEW ONES of a class the shipped detector never had, the
# COMPARISON ANCHOR ("stand at [N6], down sharply from the MY2013 peak [N2]", where MY2013 is [N2]'s year
# and never [N6]'s). A nearest-token-within-30-characters rule scores 40 -- worse than shipped. So the
# window is necessary and NOT sufficient, and what rides inside it is APPOSITIVE OWNERSHIP:
#
#   (1) THE WINDOW (M1(a)). A handle's period may only be looked for between the PREVIOUS [N] sibling and
#       the NEXT one, clipped to the sentence. A sibling's year can never be reached at all.
#   (2) OWNERSHIP INSIDE IT. Right-attachment WINS and CONSUMES: "[N4] in MY2024" binds MY2024 to [N4]
#       across nothing but whitespace, markdown emphasis and ONE scope preposition (in/for/of/during/
#       at/by/as of). A comma, a dash, a paren, a colon or any other word breaks it -- those are the
#       shapes the 18 anchors are made of. Failing that, the NEAREST PRECEDING token binds, but only
#       across a CLEAN bridge (no bracket, no comma/semicolon/colon, no paren, no dash, <= 48 chars) and
#       only if no other handle has already claimed it. A token another handle owns NEVER convicts.
#   (3) FAIL-OPEN ON ABSENCE (M1(c)). No owned token -> `compared = False`, SILENT, never a conviction --
#       and likewise when the receipt declares no period. A conviction whose remedy is DELETION needs
#       POSITIVE evidence on BOTH sides; the docstring below has always claimed that and the row side
#       violated it 131 times.
#
# AND FIX 3, THE 10.19.4 SUSPICION, KEPT AND RECORDED AS MOVING NOTHING: a declared SPAN
# ("MY2010->MY2011", "MY2023-to-MY2024") is expanded to its CLOSED INTERVAL and tested for CONTAINMENT.
# It rescues 0 of the 25 -- it is a latent defect closed on the way past, not this population's cause.
# It is also SAFE BY DIRECTION: expansion only ever ADDS years to the clause side, so it can only make
# the detector quieter, never louder, which is the only direction a deletion-armed check may be tuned in.
_DECLARED_PERIOD_RX = re.compile(
    r"\bMY\s?(?:19|20)\d{2}(?:\s*[/-]\s*\d{2,4})?\b"
    r"|\b(?:19|20)\d{2}\s*/\s*\d{2,4}\b")

# A DECLARED SPAN between two years, in the spellings the corpus actually writes. Both endpoints must be
# full 4-digit years, which is what keeps an ISO date fragment ("2026-05-29") out of it.
_PERIOD_SPAN_RX = re.compile(
    r"\b(?:MY\s?)?(?:19|20)\d{2}(?:\s*[/-]\s*\d{2,4})?"
    r"\s*(?:→|–|—|->|\.\.|-to-|through|to|-)\s*"
    r"(?:MY\s?)?(?:19|20)\d{2}(?:\s*[/-]\s*\d{2,4})?\b", re.I)

# The ONLY text that may stand between a handle and the period token to its RIGHT for that token to be the
# handle's own. Whitespace, markdown emphasis, and ONE scope preposition -- nothing else. Punctuation is
# excluded ON MEASUREMENT, not on taste: every one of the 18 anchor false positives a permissive bridge
# mints reaches its year across a comma, a dash or a paren.
_RIGHT_APPOS_RX = re.compile(r"[\s*_]*(?:in|for|of|during|at|by|as\s+of)?[\s*_]*", re.I)
# What DISQUALIFIES a preceding token from being the handle's own: another handle, a clause break, or a
# parenthetical. `--` is spelled out because the en/em dashes do not cover the ASCII form.
_LEFT_BRIDGE_BAD_RX = re.compile(r"[\[\],;:()–—]|--")
_LEFT_BRIDGE_MAX = 48


def _declared_span_years(text: str) -> set[str]:
    """Every year a DECLARED SPAN in `text` covers, endpoints included (FIX 3). Empty when it names none.
    Capped at 80 years so a malformed pair can never mint a set the intersection below cannot reason about."""
    out: set[str] = set()
    for m in _PERIOD_SPAN_RX.finditer(text or ""):
        ys = sorted(int(y) for y in re.findall(r"(?:19|20)\d{2}", m.group(0)))
        if ys and 0 < ys[-1] - ys[0] <= 80:
            out |= {str(y) for y in range(ys[0], ys[-1] + 1)}
    return out


# ══ D-HP-25 (plan 10.30.3(i)) -- THE OWNERSHIP CORE, FACTORED OUT. IT IS A MOVE, NOT A REWRITE ════════
#
# The two-pass sibling-bounded appositive-ownership core below WAS the body of `_handle_period_phrase`
# and is MOVED VERBATIM -- both passes ride intact (PASS 1 right-attachment wins and CONSUMES; PASS 2 the
# nearest CLEAN preceding token under `_LEFT_BRIDGE_MAX` / `_LEFT_BRIDGE_BAD_RX`). ZERO LOGIC CHANGE.
# THE REGRESSION PROOF IS THE FIVE EXISTING PINS at `tests/unit/test_dhp_renderer.py:651, :652, :686,
# :687, :735`, and they pass UNMODIFIED. A factor-out that requires touching a pin is not a factor-out.
#
# WHY IT IS FACTORED AT ALL: the GEO axis (D-HP-25 V1) asks the identical question of a different
# vocabulary, and a second copy of a 45-line consumption ledger is how two axes come to disagree about
# what "this handle's own token" means. The two DELIBERATE differences the geo wrapper supplies are stated
# at `_handle_geo_phrase`: no span widening, and its OWN appositive set.
#
# THE TWO PARAMETERS THAT MAKE IT AXIS-AGNOSTIC, AND WHY EACH IS A LIST RATHER THAN A REGEX:
#   * `tok_positions` -- the token spans, PRE-COMPUTED by the caller. The period axis mints them from a
#     regex and the geo axis from a LEXICON, and a core that took a regex could only ever serve the first.
#     Entries may carry a third element (the geo axis rides `(start, end, slug)`); only [0] and [1] are
#     read here, so one core serves both shapes.
#   * `siblings` -- the token spans that BOUND the window. Defaults to this text's `[N` handles, which is
#     what the period axis has always used; the `[E]` containment pass (V2) passes its OWN `[E]` spans,
#     because "the previous sibling" means the previous handle OF THE KIND BEING BOUND.
#
# THE CONSUMPTION LEDGER (`claimed`) IS PER CALL, AND THAT IS A LAW, NOT AN ACCIDENT (plan 10.30.3(ii)):
# each axis computes its own, so a YEAR can never consume a slot a GEO token needed. Two axes competing
# for one ledger is a silent, order-dependent bug, and it is forbidden BY CONSTRUCTION here -- there is no
# module-level ledger for a caller to accidentally share.
def _owned_token(sent: str, a: int, b: int, tok_positions, appos_rx,
                 *, siblings=None) -> int | None:
    """The INDEX into `tok_positions` of the token the handle at `sent[a:b]` owns, or None.

    `sent` is ONE sentence, `a`/`b` are offsets INTO IT. Returns an index rather than the token text so
    the geo axis can recover its slug and the period axis its span -- the two wrappers differ only in
    what they do with the answer."""
    handles = ([(mm.start(), mm.end()) for mm in _n_token_rx(True).finditer(sent)]
               if siblings is None else [(int(x), int(y)) for (x, y, *_r) in siblings])
    toks = list(tok_positions or [])
    if not toks:
        return None
    owner: dict[tuple[int, int], int] = {}          # handle span -> index into `toks`
    claimed: set[int] = set()

    def _right_bound(hb: int) -> int:
        nxt = [x for (x, _y) in handles if x >= hb]
        return min(nxt) if nxt else len(sent)

    def _left_bound(ha: int) -> int:
        prv = [y for (_x, y) in handles if y <= ha]
        return max(prv) if prv else 0

    for (ha, hb) in handles:                        # PASS 1 -- right-attachment wins and CONSUMES
        hi = _right_bound(hb)
        for k, tk in enumerate(toks):
            ts, te = tk[0], tk[1]
            if ts < hb:
                continue
            if te > hi or k in claimed:
                break
            if appos_rx.fullmatch(sent[hb:ts]):
                owner[(ha, hb)] = k
                claimed.add(k)
            break
    for (ha, hb) in handles:                        # PASS 2 -- the nearest CLEAN preceding token
        if (ha, hb) in owner:
            continue
        lo = _left_bound(ha)
        for k in range(len(toks) - 1, -1, -1):
            ts, te = toks[k][0], toks[k][1]
            if te > ha:
                continue
            if ts < lo or k in claimed:
                break
            bridge = sent[te:ha]
            if len(bridge) <= _LEFT_BRIDGE_MAX and not _LEFT_BRIDGE_BAD_RX.search(bridge):
                owner[(ha, hb)] = k
                claimed.add(k)
            break
    return owner.get((a, b))


def _sibling_window(sent: str, a: int, b: int, siblings=None) -> tuple[int, int]:
    """The M1(a) WINDOW for the handle at `sent[a:b]`: previous sibling's end .. next sibling's start,
    clipped to the sentence. The SAME bounds `_owned_token` computes internally, exposed because L3's
    multi-geo decline is a question about the WINDOW ("does this window name more than one country") and
    not about ownership."""
    handles = ([(mm.start(), mm.end()) for mm in _n_token_rx(True).finditer(sent)]
               if siblings is None else [(int(x), int(y)) for (x, y, *_r) in siblings])
    prv = [y for (_x, y) in handles if y <= a]
    nxt = [x for (x, _y) in handles if x >= b]
    return (max(prv) if prv else 0, min(nxt) if nxt else len(sent))


def _handle_period_phrase(text: str, s0: int, s1: int, hs: int, he: int) -> str:
    """The period phrase THIS handle occurrence owns, or "" when it owns none.

    THE THREE RULES ARE IN THE BLOCK NOTE ABOVE. The return is the phrase's TEXT rather than a year set on
    purpose: `_slot_scope_mismatch` keeps taking a string, so the one existing pin that calls it directly
    is unmoved, and a phrase that happens to be one end of a declared SPAN is returned as the WHOLE SPAN
    so the containment reading below sees the interval and not an endpoint.

    IT IS NOT `_binding_clause` AND IT DOES NOT TOUCH IT. That function answers D-HP-13's question ("the
    ONE licensed verb standing in front of this handle"), whose semantics genuinely are left-only, and it
    fires 0 of 1,026 -- nothing there needs to move. Only the PERIOD axis changes its input.

    THE LEFT BOUND IS BELT-AND-BRACES, AND IT IS RECORDED AS SUCH RATHER THAN SOLD AS LOAD-BEARING.
    Mutating `_left_bound` to 0 over the whole r4+d2 corpus moves NOTHING (0/171 either way), because a
    bridge that reaches back past a sibling necessarily contains that sibling's `[`, which
    `_LEFT_BRIDGE_BAD_RX` already rejects. It is kept because M1(a) states it as a property of the WINDOW
    while the bracket rule is a property of the BRIDGE TEXT: two independent statements of "a sibling's
    year never convicts", so a later edit to either one cannot silently retire the guarantee. Every other
    clause here IS load-bearing and was mutation-killed: collapsing the right edge to the handle scores 31
    convictions, dropping the span widening scores 1, and reading publication dates instead of the
    receipt's scope scores 138.

    [D-HP-25, plan 10.30.3(i)] THE OWNERSHIP CORE NOW LIVES IN `_owned_token` AND WAS MOVED VERBATIM.
    This function is the THIN WRAPPER that supplies the period axis' own three things: the token grammar
    (`_DECLARED_PERIOD_RX`), the appositive vocabulary (`_RIGHT_APPOS_RX`) and the FIX-3 span widening
    below, which is the period axis' alone (there is no geo analogue of "an endpoint is read as its whole
    span"). Nothing about the rules moved; only their location did."""
    sent = text[s0:s1]
    a, b = hs - s0, he - s0
    if not (0 <= a < b <= len(sent)):
        return ""
    toks = [(mm.start(), mm.end()) for mm in _DECLARED_PERIOD_RX.finditer(sent)]
    k = _owned_token(sent, a, b, toks, _RIGHT_APPOS_RX)
    if k is None:
        return ""
    ts, te = toks[k]
    for sm in _PERIOD_SPAN_RX.finditer(sent):       # FIX 3: an endpoint is read as its whole span
        if sm.start() <= ts and te <= sm.end():
            return sm.group(0)
    return sent[ts:te]


def _receipt_period_text(call: dict | None) -> str:
    """The RECEIPT'S OWN declared period -- the query's `period` and the HEADLINE ROW's, and nothing else.

    THIS IS M1(b), AND IT IS THE SHAPE-B FIX. The shipped row side read `str(Citation.label)`, a RENDERED
    string carrying `from_number`'s staleness tail, its truncation span, its print-kind and currency tags
    and its formatted value. A detector whose remedy is DELETION must never parse a rendering -- that is
    the cycle-10 repair fence's own epitaph ("a fence that compares labels cannot see semantics"), applied
    to its sibling. `knowledge_date`, `asof` and `_covered_span` are DELIBERATELY absent: a publication
    date is not a scope, and reading one as a scope is what convicted a crop year against {2026}.
    The headline row comes from `cit.headline_row`, the SAME selector `from_number` headlines with, so the
    period compared here can never disagree with the period the reader's `## Sources` line was built from."""
    q = ((call or {}).get("query") or {}) if isinstance(call, dict) else {}
    parts = [str(q.get("period") or "").strip(),
             str((cit.headline_row(call) or {}).get("period") or "").strip()]
    return " ".join(p for p in parts if p)


def _slot_scope_mismatch(clause: str, call: dict | None, idx: int) -> tuple[bool, bool]:
    """D-HP-14(a), THE PERIOD AXIS -- the only axis of the scope cross-check that ships in the first build.

    `clause` IS THE HANDLE'S OWN PERIOD PHRASE (`_handle_period_phrase`), NOT a window of prose. See the
    REMEDIATION-3 M1 block note above for the 25 false positives the window reading produced and for the
    three rules that replaced it. A string that names no declared scope still returns `(False, False)`,
    which is what the pre-M1 pin asserting exactly that continues to measure.

    RETURNS `(compared, mismatch)` (H1 FIX Z12). `compared` is True only when BOTH SIDES SPOKE -- the
    clause named a DECLARED crop-year scope AND the row named a year -- which is the only state in which
    anything was actually checked. The caller increments `wrong_slot_audit.scope_checked` off THAT bool,
    not off "a solitary resolved handle existed": the shipped form counted ATTEMPTS, so the column read as
    coverage on rows whose clause named no period at all, which is precisely the "never claims coverage it
    does not have" promise this function's own docstring makes below.

    THE RISK IT INSTRUMENTS: a resolved-but-MIS-BOUND handle prints a real, cited, WRONG number, and the
    closest outside measurement puts wrong-entity action at 24-26% across four baselines with 0.0%
    wrong-TOOL error in the same runs -- the format layer gives NO signal on binding. By condition it is
    0.0% for every UNAMBIGUOUS case and 100% UNDER TEMPORAL AMBIGUITY, and a receipt menu keyed by
    commodity x metric x PERIOD x vintage x source IS the temporal-ambiguity configuration. So the period
    axis is where the measured risk actually lives, and it is the axis this estate can check with no
    vocabulary and no second opinion: both sides name a year or they do not.

    IT FIRES ONLY WHEN BOTH SIDES SPEAK, AND THE CLAUSE MUST SPEAK IN THE DECLARED FORM. The clause must
    name a CROP-YEAR SCOPE (`MY2025`, `MY2025/26`, `2025/26` -- never a bare `2015`, which is far more
    often a reference year than a scope: see `_period_years(declared_only=)`) AND the resolved row's scope
    must name a year, and then the sets must be DISJOINT. No clause scope, no row period, or any overlap
    at all -> False. That is the "0.0% for every unambiguous condition" shape: the detector is silent
    unless the turn actually created the ambiguity. [M1(c), 2026-08-14] THE ABSENCE RULE IS NOW SYMMETRIC
    AND IT IS STATED AS A LAW RATHER THAN AS AN ACCIDENT OF PARSING: a conviction needs POSITIVE evidence
    on BOTH sides, so no owned period phrase -> silent, and no declared receipt period -> silent. The
    shipped row side broke that promise on 131 of 186 cited comparisons by counting publication dates.

    THE COMMODITY AND UNIT-CLASS AXES ARE NOT BUILT, AND ARE RECORDED AS NOT BUILT rather than approximated
    -- commodity needs a vocabulary this function is not threaded (the graph), and unit class was the exact
    quantity the cycle-10 repair fence compared and got wrong ("a fence that compares labels cannot see
    semantics"). `wrong_slot_audit.scope_checked` therefore counts PERIOD checks and nothing else, so the
    column never claims coverage it does not have."""
    if not str(clause or "").strip():
        return False, False
    # M1(b): the RECEIPT'S OWN period fields, never the rendered label. `from_number` is still the thing
    # that must not raise -- it is what resolves the row the reader is shown -- but nothing is parsed
    # out of what it renders.
    try:
        cit.from_number(call, idx)
    except Exception:  # noqa: BLE001
        return False, False
    row_years = _period_years(_receipt_period_text(call))
    clause_years = _period_years(clause, declared_only=True) | _declared_span_years(clause)
    if not (row_years and clause_years):
        return False, False                        # one side said nothing: nothing was COMPARED
    return True, not (row_years & clause_years)


# ══ D-HP-25 V1 (plan 10.30.3) -- THE `[N]` GEO AXIS ═══════════════════════════════════════════════════
#
# THE CLAIM THIS AXIS MAKES, AND THE ONE IT DOES NOT. It proves that a backed figure's receipt agrees with
# the claim's OWN DECLARED GEOGRAPHY. It does NOT prove unique-row correctness: a swap onto a
# FACET-IDENTICAL row (same period, same geography, same table, different row) is undetectable by ANY
# deterministic facet check, because there is nothing left to disagree with. That residual is PERMANENT
# for as long as handle prose is the render mode (the typed-digit cross-check that once caught it was
# removed BY DESIGN when the model stopped typing the digit), it is bounded empirically by the 60-figure
# judged audit at `<= 1/60`, and plan 10.30.2 forbids stating the claim without both halves.
#
# THE APPOSITIVE SET IS THE PERIOD AXIS' MINUS ITS PORTABILITY ASSUMPTION (L3). It is spelled SEPARATELY
# rather than shared, and that separation is load-bearing: `from` / `to` / `into` must NEVER enter the geo
# set, because "in MY2024" is a SCOPE and "to China" is a DIRECTION. A later widening of the period
# vocabulary must not be able to leak a direction preposition into this one, so the two constants do not
# touch. (They are equal today; the point is that nothing enforces or assumes that they stay equal.)
_GEO_RIGHT_APPOS_RX = re.compile(r"[\s*_]*(?:in|for|of|during|at|by|as\s+of)?[\s*_]*", re.I)


def _handle_geo_phrase(text: str, s0: int, s1: int, hs: int, he: int) -> set[str]:
    """The canonical GEOGRAPHY this handle occurrence owns, as an ADDITIVE CLOSURE set, or `set()`.

    THE SAME WRAPPER AS `_handle_period_phrase`, WITH THREE DELIBERATE DIFFERENCES (plan 10.30.3(ii)):

      1. NO SPAN WIDENING. There is no geo analogue of "an endpoint is read as its whole span", and
         widening a country is how a region swallows a continent.
      2. ITS OWN APPOSITIVE SET (`_GEO_RIGHT_APPOS_RX`) -- see the note above; the period axis'
         vocabulary is NOT portable.
      3. ITS OWN CONSUMPTION LEDGER. `_owned_token` builds `claimed` per call, so a YEAR can never
         consume a slot a GEO token needed. Two axes sharing one ledger is a silent, order-dependent bug
         and it is forbidden by construction rather than by convention.

    L1 AND L3 ARE ENFORCED HERE, BEFORE OWNERSHIP IS EVEN CONSULTED, and both resolve to SILENCE:

      * L1 -- if the WINDOW names an AGGREGATE (`world / global / worldwide / total / international /
        all origins`), or the only geography it names is `european_union` with no member state beside it,
        nothing is returned. An aggregate is a CONTAINER and a container disagreeing with its contents is
        not a disagreement.
      * L3 -- if the WINDOW names MORE THAN ONE canonical geography, nothing is returned. "US sales to
        China" names two countries and the sentence is about a FLOW; no single-geo comparison is correct
        there and none is attempted. This is the seller/buyer trap and it is declined, not guessed.
        L3 IS READ ON THE WINDOW'S *CONTENTS*, NOT ON THE OWNED TOKEN, and that choice is recorded here
        because it is the QUIETER of the two readings of the clause and it has a measurable cost. In a
        two-geography era-pair sentence ("Brazilian output reached [N1] while Indonesian output reached
        [N2]") the LEFT handle's window reaches both countries and DECLINES, while the RIGHT handle's
        window -- left-bounded by its previous sibling -- reaches one and IS compared. Reading L3 off
        the OWNED token instead would compare both, and would also make the answer depend on which
        appositive rule happened to fire, which is exactly the order-dependence the per-call ledger
        exists to forbid. The lost coverage is a RECORDED RESIDUAL (plan 10.30.11), not a rule to be
        loosened after seeing a catch rate.

    The return is a CLOSURE SET (L2, ADDITIVE) rather than a slug, because that is the shape the
    comparison takes on both sides -- `{france}` is returned as `{france, european_union}` so an ancestor
    and a descendant can never be read as a disagreement. Never raises."""
    try:
        sent = text[s0:s1]
        a, b = hs - s0, he - s0
        if not (0 <= a < b <= len(sent)):
            return set()
        toks = _geo.extract_geos(sent)
        if not toks:
            return set()
        lo, hi = _sibling_window(sent, a, b)
        window = sent[lo:hi]
        if _geo.sentinel_hit(window):                       # L1: an aggregate never convicts, either way
            return set()
        in_window = {slug for (ts, te, slug) in toks if ts >= lo and te <= hi}
        if len(in_window) != 1:                             # L3: 0 -> nothing to own; >1 -> a FLOW
            return set()
        if in_window == {_geo.EU_SLUG}:                     # L1's conditional half: EU unaccompanied
            return set()
        k = _owned_token(sent, a, b, toks, _GEO_RIGHT_APPOS_RX)
        if k is None:
            return set()                                    # M1(c): no owned token -> SILENT, never a hit
        return _geo.canon_closure(toks[k][2])
    except Exception:  # noqa: BLE001 -- a deletion-armed check fails toward NOT comparing
        return set()


def _receipt_dest_coded(table: str) -> bool:
    """`citations.py:384`'s `_dest_coded`, re-stated (it is a closure inside `from_number` and cannot be
    imported). A DESTINATION-CODED table's `country` axis enumerates BUYERS of one national flow, so the
    row's country is not the fact's geography and reading it would convict correct sentences at scale.

    THE FAIL-SILENT DIRECTION IS INHERITED UNCHANGED: a registry hiccup returns True, i.e. "treat as
    destination-coded", i.e. DO NOT read the row. It fails toward NOT COMPARING, which is the safe
    direction here and the same one the shipped label logic chose."""
    try:
        from leviathan.graphrag.numbers import registry as _reg
        spec = _reg.load_registry().tables.get(table)
        return bool(spec is not None and spec.destination_coded())
    except Exception:  # noqa: BLE001 -- a registry hiccup must fail SILENT, never loud
        return True


def _receipt_geo_text(call: dict | None) -> set[str]:
    """The RECEIPT'S OWN geography, as an additive closure set. `set()` when the receipt names none.

    THIS IS M1(b) ON THE GEO AXIS, AND THE FENCE IS VERBATIM: `Citation.label` IS NEVER PARSED. A
    detector whose remedy is DELETION must never parse a rendering -- that is the cycle-10 repair fence's
    own epitaph applied to its sibling, and `_receipt_period_text` states it for the period axis in the
    same words.

    [TIGHTENING T1, RATIFIED AT M-0] IT MIRRORS THE SHIPPED `from_number` GEO RULE EXACTLY, because the
    only honest thing to convict against is WHAT THE RECEIPT WOULD ACTUALLY RENDER (`citations.py:390-392`):

      * the QUERY's `country` first -- it is what the drill-down re-runs, and on a free-axis card it is
        the only unambiguous statement of scope;
      * ELSE the ROW's country, and ONLY when (a) every returned row carries the SAME one
        (`len(_geos) == 1`, the unanimity fence) AND (b) the table is NOT destination-coded. Unanimity
        alone is TRIVIALLY satisfied by an `agg='latest'` LIMIT-1 read -- one row always agrees with
        itself -- which is exactly why the semantic half of the fence is not optional.

    [REVIEW BLOCKER, FIXED 2026-08-15 -- THE BUYER FENCE COVERS *BOTH* HALVES, NOT ONLY THE ROW.] The
    first build read `query['country']` UNCONDITIONALLY and consulted `_receipt_dest_coded` only on the
    ROW fallback. That is a false-conviction engine on the one destination-coded table in the registry:
    an ESR call's `query['country']` IS THE DESTINATION (`numbers/agent.py:197-205` -- "country=<name>
    -> FAS code IN filter"), so "American export commitments reached [N1]" against a `country='China'`
    ESR read compared `{united_states}` to `{china}`, convicted, and DELETED A CORRECT SENTENCE -- while
    charging R11's frozen ceiling of 15 for the privilege. The reason `_receipt_dest_coded` exists
    (stated at its own docstring) is that on such a table THE COUNTRY AXIS ENUMERATES BUYERS OF ONE
    NATIONAL FLOW; that is a fact about the AXIS, and the query half reads the same axis the row half
    does. So a destination-coded table now returns `set()` OUTRIGHT: the comparison is OFF, on both
    halves. THE COST IS RECORDED AND IT IS COVERAGE, NOT SAFETY -- 268/6120 = 4.4% of stored `[N]` calls
    lose the geo comparison entirely, including the genuine buyer-vs-buyer catch ("Chinese purchases
    reached [N1]" bound to a Japan-scoped read). A geo verifier's failure mode is not missing a swap, it
    is deleting a correct sentence, so the quieter reading is the one this check takes -- the same trade
    L1/L3/L4 make. Mirroring `from_number` LABEL-SIDE was never the point; the point is convicting only
    against a field that states THE FACT'S OWN GEOGRAPHY, and on a dest-coded table neither field does.

    A receipt that names an AGGREGATE (L1) or more than one country returns `set()`: the comparison is
    OFF, not resolved in the aggregate's favour. Never raises."""
    try:
        q = ((call or {}).get("query") or {}) if isinstance(call, dict) else {}
        raw = str(q.get("country") or "").strip()
        rows = ((call or {}).get("rows") or []) if isinstance(call, dict) else []
        if raw or rows:
            # THE BUYER FENCE, ASKED ONCE, ANSWERED FOR BOTH HALVES. The fail-SILENT-on-hiccup branch is
            # inherited unchanged and now covers the query half too: a registry exception returns True,
            # i.e. do not read EITHER field, i.e. do not compare. An unknown table still yields
            # `spec is None` -> False and both halves are read, exactly as `citations.py:383-389` behaves.
            if _receipt_dest_coded(str(q.get("table") or "")):
                return set()
            if not raw:
                geos = {str(r.get("country")).strip() for r in rows
                        if isinstance(r, dict) and str(r.get("country") or "").strip()}
                if len(geos) == 1:
                    raw = next(iter(geos))
        if not raw or _geo.sentinel_hit(raw):               # L1 on the receipt side
            return set()
        slugs = _geo.slugs_in(raw)
        if len(slugs) != 1 or slugs == {_geo.EU_SLUG}:      # L3 + L1's conditional half
            return set()
        return _geo.canon_closure(next(iter(slugs)))
    except Exception:  # noqa: BLE001 -- fail toward NOT comparing
        return set()


def _slot_geo_mismatch(claim: set[str] | None, call: dict | None, idx: int) -> tuple[bool, bool]:
    """D-HP-25 V1 -- THE GEO AXIS, MIRRORING `_slot_scope_mismatch` EXACTLY IN SHAPE.

    Returns `(compared, mismatch)` on the same FIX Z12 contract: `compared` counts COMPARISONS and never
    ATTEMPTS, so `geo_checked` can never read as coverage on a handle whose clause named no geography.
    SILENT UNLESS BOTH SIDES SPEAK -- a conviction whose remedy is DELETION needs POSITIVE evidence on
    both sides, and the period axis' row half violated exactly that promise on 131 of 186 comparisons.

    THE FOUR LAWS ARE ALREADY DISCHARGED BY THE TIME THIS RUNS, and that placement is deliberate: L1
    (sentinels), L3 (multi-geo) and L4 (word boundaries, follower blacklist, homonyms, ambiguous
    surfaces) all resolve to an EMPTY SET at the producer, so this function's only remaining job is L2 --
    the ADDITIVE closures either intersect (agreement, however distant an ancestor) or they do not.
    ANCESTOR/DESCENDANT PAIRS NEVER CONVICT: non-empty intersection IS agreement.

    It keeps `cit.from_number`'s try/except guard for the identical reason the period axis does: the
    resolve is what the reader is SHOWN and it must not raise -- but nothing is parsed out of what it
    renders."""
    claim = set(claim or ())
    if not claim:
        return False, False
    try:
        cit.from_number(call, idx)
    except Exception:  # noqa: BLE001
        return False, False
    receipt = _receipt_geo_text(call)
    if not receipt:
        return False, False                        # one side said nothing: nothing was COMPARED
    return True, not (claim & receipt)


# ══ D-HP G1 REMEDIATION-2 R2-a (2026-08-14) -- THE EMPTY-ROW ADDRESS IS ITS OWN STATE ═════════════════
#
# THE DOCTRINE, PINNED BY THE OWNER AT THIS WINDOW: OBEDIENCE IS NOT LOAD-BEARING. Remediation 1 answered
# the r2 clause-(2) population with a PROMPT clause ("Do NOT cite the empty row's [N] handle"), and the
# population fell 55 -> 3. The three that survived are the residue that a directive can never reach: two
# turns where the model was told and cited anyway, and one where the shape was invisible to the directive
# altogether (R2-b, fixed at the source in `citations.is_empty_read`). A rule the model may decline is not
# a guarantee, so the guarantee moves here, to the resolver, where the model has no vote.
#
# WHAT WAS ALREADY TRUE AND STAYS TRUE, STATED FIRST SO THE CHANGE IS NOT OVERSOLD: NOTHING EMPTY EVER
# RENDERED. `_number_handle_value` returns None for every one of these shapes (`Citation.value` is None or
# blank), so an empty-row address has always taken the shipped ladder -- splice nothing, drop the handle,
# sever the clause, or kill the sentence. The r3 artifacts confirm it: not one empty figure reached a
# reader on any of the 52 row-instances. THE DEFECT WAS THE ACCOUNTING, and it was a real one.
#
# THE ACCOUNTING DEFECT. `unresolvable` is DEFINED by D-HP-17 item 4 as "the model addressed a receipt that
# DOES NOT EXIST" -- an index past the end of the menu, or a sibling id nothing minted. An empty-row
# address is the opposite state: the receipt EXISTS, the menu line is real, the handle names it correctly,
# and the row behind it carries no value. Charging both to one counter makes G1 clause (2) read "no holes
# in the reader's page" as "the model never addressed an absence", which is a claim about the WRITER's
# obedience, not about the page -- and it is unsatisfiable by construction on the control arm, which this
# wave does not touch. THE PRECEDENT IS H1 FIX Z2's, EXACTLY: `binding_refused` split off `unresolvable`
# for the same reason (a refused handle RESOLVED and was declined) and lives in the same census.
#
# THREE THINGS THIS DELIBERATELY IS NOT.
#   (1) NOT A STRIP CLASS. It is not folded into `by_rule`/`stripped` and it is NOT in
#       `_RENDER_LEDGER_CLASSES` -- `unresolvable`'s own removals have never been strips either, so
#       folding this half and not that half would inflate the TREATMENT arm's `strips` against clause (3)
#       for a removal the control arm makes silently. `binding_refused` sits in exactly this position.
#       CONSEQUENCE, RECORDED FOR THE RE-FREEZE: clause (4)'s SIXTEEN-member declared set is UNTOUCHED,
#       because the class scan reads `by_rule` and this counter never enters it. What the re-freeze owes
#       is a sentence in clause (2) naming the counter, and a decision on whether it carries a budget.
#   (2) NOT AN OFF-ARM CHANGE. The key is minted only under `handle_prose`, beside the other six D-HP
#       counters, so the control census keeps its four pinned keys byte-for-byte and the control arm keeps
#       charging `unresolvable` exactly as it does today. That is the OFF-arm-clean rule, and it is the
#       same rule `_resolve_evidence_handles` obeyed when D2(b) refused to grow a fifth key.
#   (3) NOT A NEW REMOVAL. Not one byte of the ladder moves. The handle leaves the page under the same
#       drop/sever/kill it takes today, counted under the same `handles_dropped` / `sentences_dropped`.
#
# THE PREDICATE IS THE CLASS, NOT A LIST OF SHAPES. A dead member is an EMPTY-ROW ADDRESS when the call it
# names EXISTS and PRESENTS NO VALUE -- which covers the zero-row reads, the four empty statuses, R2-b's
# blank-value shape and the zero-AGGREGATE class, and covers any fifth shape a future card invents without
# anyone remembering to come back here. Everything else dead -- an out-of-range index, a suffixed member
# nothing minted, a malformed record -- stays `unresolvable`, which is what that word means.
def _addresses_empty_row(call, idx: int, suffix: str = "") -> bool:
    """True when `[N{idx}]` names a menu row that EXISTS and carries no value.

    False for an out-of-range index (`call` is None), for a suffixed member (D-HP-11/12: a token the model
    invented, and "invented" is `unresolvable` by definition), and for any row that resolves to a figure.
    Never raises: a malformed record reads False, the side that leaves the charge where it is today."""
    if suffix or not isinstance(call, dict):
        return False
    if cit.is_empty_read(call):
        return True                        # zero rows, or rows that all came back blank (R2-b)
    try:                                   # ...and the classes that HAVE rows but withhold the value
        c = cit.from_number(call, idx)     # (the zero-AGGREGATE marker), read off the one producer
    except Exception:  # noqa: BLE001
        return False
    return c.value is None or not str(c.value).strip()


def _resolve_number_handles(structured: dict | None, number_calls: list | None, *,
                            handle_prose: bool = False) -> dict:
    """Substitute or remove every `[N]` handle in the reader prose so none can render literally.

    Mutates `structured['tldr']` / `structured['mechanism']` IN PLACE and returns the census
    ({substituted, handles_dropped, sentences_dropped, unresolvable}) for the trace. Never raises:
    a render guard must never be the thing that breaks an answer.

    A SEVERED CLAUSE COUNTS AS `handles_dropped`, and the census keeps its four keys: the shape is pinned
    byte-for-byte by the suites and rides every turn's trace, so the mixed-sentence remedy reports under
    the drop it is (one handle left the page) rather than minting a fifth counter for it.

    D-PQ HANDLE-2, A GROUPED TOKEN IS NARROWED, NEVER GUESSED. `[N13, N14]` / `[N1-N6]` are ONE token
    carrying MANY handles (see `_N_HANDLE_RX`). The verdict is per MEMBER and the remedy is the smallest
    one that leaves the join total:
      * every member resolves -> untouched, exactly as a solitary resolved handle is;
      * SOME resolve          -> the token is REWRITTEN to the surviving members ("[N13, N14]" ->
                                 "[N13]"), because a group is only ever as good as its worst index and
                                 the alternative is a marker the footer cannot answer for;
      * NONE resolve          -> the token takes the solitary-handle path unchanged (drop / sever / kill),
                                 spanning the whole token.
    A grouped token NEVER receives the value splice: it stands in for no single figure, so `standin` can
    only ever kill or narrow it. Each departed member is counted once under `handles_dropped` /
    `unresolvable` -- the same accounting a solitary handle gets, and no fifth census key.

    ══ D-HP-11 (H1) -- `handle_prose` FLIPS THE DEFAULT, AND ADDS THREE REFUSALS ═════════════════════════
    Default False -> every branch, every counter and every census KEY below is the pre-D-HP pass exactly.
    The four census keys are pinned byte-for-byte by the suites, so the D-HP counters are ADDED KEYS that
    appear ONLY on the treatment lane (the OFF-arm-clean rule).

    (a) THE SLOT CUE BECOMES A CONFIRMATION, NOT A PRECONDITION. Under D-HP-7 the contract is "handle
        ONLY, written in the slot where the figure belongs", so THE MODEL WROTE NO DIGIT and a solitary
        RESOLVED handle is standing in for its value whether or not a value-introducing word precedes it.
        `_HANDLE_VALUE_SLOT_RX` still runs -- it is the cue the estate measured and shipped, and a cue HIT
        is still the strongest evidence -- but a cue MISS no longer means "leave the token on the page",
        which under handle-only prose is the D-PQ HANDLE-1 defect restored.
        `_figure_already_stated` STILL RUNS AND STILL WINS. It is not dead code on a mixed or degraded
        turn (a retry, a `GRAPHRAG_HANDLE_PROSE=off` mid-flight kill, a model that ignored the contract),
        and on those turns it is the only thing standing between the reader and a doubled figure.

    (b) A GROUPED TOKEN IN A VALUE SLOT IS A LINT VIOLATION, NOT A CITATION. The shipped rule leaves a
        FULLY-RESOLVED group untouched -- correct while the model also types the digit, and a defect the
        moment it does not: `[N13, N14]` then SHIPS TO THE READER standing where a figure belongs, which
        is exactly D-PQ HANDLE-1 re-minted, and G1 clause (2) is blind to it because the handles resolved.
        A group stands in for NO SINGLE FIGURE, so it may not be spliced; the clause is SEVERED and the
        turn is charged `grouped_in_slot`.

    (c) TWO BINDING REFUSALS (D-HP-13 direction-vs-sign, D-HP-14(a) period scope). Both route the handle
        into the SHIPPED ladder (drop-handle / sever-clause / kill-sentence) rather than inventing a
        fourth remedy. Neither ever rewrites a word or a digit -- that is the cycle-10 repair path
        wearing a different hat (D3).
        THEY ARE ACCOUNTED AS `binding_refused`, NEVER AS `unresolvable` (H1 FIX Z2): a refused handle
        RESOLVED and was declined, which is the opposite of D-HP-17 item 4's "the model addressed a
        receipt that does not exist". See the counter's own note at the charge site.

    (d) [G1 REMEDIATION-2 R2-a, 2026-08-14] AN EMPTY-ROW ADDRESS IS `empty_row_addressed`, NEVER
        `unresolvable`, on the SAME grounds one rung down: the receipt EXISTS and carries no value, while
        `unresolvable` is D-HP-17 item 4's "a receipt that does not exist". The REMOVAL is untouched.
        See `_addresses_empty_row`'s own note for the doctrine ("obedience is not load-bearing"), the
        three things this deliberately is NOT, and the re-freeze item it owes G1 clause (2).

    THE CYCLE-10 RECONCILIATION, STATED WHERE THE CODE IS: this pass writes a numeral into prose, which is
    the capability the termination branch DELETED from verify.py. The distinction is not a fence, it is
    the slot: `_num_repair` second-guessed a number THE MODEL HAD WRITTEN on the strength of a four-clause
    allowlist, and the gate-7 op passed all four and still corrupted a correct sentence. D-HP SPLICES INTO
    A SLOT THAT IS EMPTY BY CONTRACT -- there is no model-written number to certify against, so the splice
    carries NO semantic judgement. Its only failure mode is a handle pointing at the wrong row, and its
    only remedy is DELETION. `verify.report['repaired'] / ['repairs']` stay 0 / [] on every turn, both
    arms, which is what test_cycle10_no_rewrites asserts and what this pass must never move."""
    census = {"substituted": 0, "handles_dropped": 0, "sentences_dropped": 0, "unresolvable": 0}
    if handle_prose:                              # ADDED KEYS, treatment lane only (OFF-arm clean)
        census.update({"grouped_in_slot": 0, "direction_sign_mismatch": 0, "slot_scope_mismatch": 0,
                       "scope_checked": 0, "direction_checked": 0, "binding_refused": 0,
                       "empty_row_addressed": 0,      # R2-a, the SEVENTH added key (see its own note)
                       # D-HP-25 V1 (plan 10.30.6): the GEO axis' comparison denominator and its class
                       # counter -- the EIGHTH and NINTH added keys, TREATMENT-ONLY like the seven above,
                       # so the control census keeps its four pinned keys byte-for-byte.
                       "geo_checked": 0, "geo_mismatch": 0})
    if not isinstance(structured, dict):
        return census
    calls = list(number_calls or [])
    for field in ("tldr", "mechanism"):
        text = structured.get(field)
        if not isinstance(text, str) or "[N" not in text:
            continue
        ops: list[tuple[int, int, str]] = []      # (start, end, replacement)
        kills: list[tuple[int, int]] = []         # whole-sentence drops
        narrowed: dict[tuple[int, int, str], int] = {}   # narrowing op -> members it removed
        # ONE PASS FIRST, so every handle's verdict is known before any of them is acted on: whether a
        # sentence may be killed depends on the OTHER handles standing in it (see _HANDLE_CLAUSE_OPEN_RX).
        recs = []                                 # (match, value, sentence span, standing-in?, members, live)
        for m in _n_token_rx(handle_prose).finditer(text):   # FIX Z8: the arm's own token grammar
            # D-HP-11/12: the PAIR list is the producer, the index list a de-duplicated view of it. Every
            # value lookup is keyed on the PAIR, so a suffixed member can never borrow its call's headline.
            pairs = _n_handle_pairs(m.group(0))
            members = _n_handle_members(m.group(0))
            vals = [_number_handle_value(calls[i - 1] if 1 <= i <= len(calls) else None, i, sfx,
                                         magnitude_only=(handle_prose
                                                         and _polarity_entry(_call_metric(
                                                             calls[i - 1] if 1 <= i <= len(calls) else None))
                                                         is not None))
                    for i, sfx in pairs]
            live_pairs = [p for p, v in zip(pairs, vals) if v is not None]
            live = [i for i, _s in live_pairs]
            # R2-a: of the members that resolved to NOTHING, how many named a menu row that EXISTS and
            # carries no value. Computed off `vals` -- BEFORE the binding refusals below can empty `live`
            # -- so a refused handle (which RESOLVED) can never be miscounted here. Treatment lane only:
            # on the control arm the key does not exist and every dead member stays `unresolvable`.
            dead_empty = (sum(1 for (i, sfx), v in zip(pairs, vals)
                              if v is None and _addresses_empty_row(
                                  calls[i - 1] if 1 <= i <= len(calls) else None, i, sfx))
                          if handle_prose else 0)
            # `value` is the SPLICE payload and exists only for a SOLITARY handle; a grouped token resolves
            # to "still points at something" (True) and nothing more -- it stands in for no single figure.
            value = vals[0] if len(pairs) == 1 else (True if live_pairs else None)
            s0, s1 = _handle_sentence_span(text, m.start())
            # CYCLE-7: the cue is necessary but NOT sufficient -- a handle written IN FRONT of its own
            # figure ("was at [N1] 15.17 USD/mmbtu") satisfies it and is not standing in for anything.
            standin = bool(_HANDLE_VALUE_SLOT_RX.search(text[s0:m.start()]))
            gslot = False
            refused = False
            if handle_prose:
                # (c) THE TWO BINDING REFUSALS, on a SOLITARY RESOLVED member only. The clause is the
                # span the remedy would delete, so a convicted verb or year is always one the reader
                # loses -- never a neighbouring clause's.
                if len(pairs) == 1 and isinstance(value, str):
                    _call = calls[pairs[0][0] - 1] if 1 <= pairs[0][0] <= len(calls) else None
                    _clause = _binding_clause(text, s0, m.start())
                    # [G1 REMEDIATION-3 M1, 2026-08-14] THE TWO CHECKS NO LONGER SHARE ONE SPAN, because
                    # they never asked the same question. D-HP-13 reads the licensed VERB standing in
                    # front of the handle, which is genuinely left-only and fires 0 of 1,026 -- untouched.
                    # D-HP-14(a) reads the PERIOD THIS HANDLE OWNS, which the era-pair grammar writes
                    # AFTER it ("[N4] in MY2024"); reading it out of a left-truncated window is how a
                    # sibling's year deleted 23 correct figures. See `_handle_period_phrase`.
                    _scope = _handle_period_phrase(text, s0, s1, m.start(), m.end())
                    # FIX Z12: `scope_checked` counts COMPARISONS, never attempts -- see
                    # `_slot_scope_mismatch`'s return contract.
                    _compared, _mismatch = _slot_scope_mismatch(_scope, _call, pairs[0][0])
                    if _compared:
                        census["scope_checked"] += 1
                    if _mismatch:
                        census["slot_scope_mismatch"] += 1
                        value, live, live_pairs, refused = None, [], [], True
                    else:
                        census["direction_checked"] += 1
                        if _direction_sign_mismatch(_clause, _call, pairs[0][0]):
                            census["direction_sign_mismatch"] += 1
                            value, live, live_pairs, refused = None, [], [], True
                        else:
                            # [D-HP-25 V1, plan 10.30.3(v)] THE THIRD BINDING REFUSAL, SEATED AT THE
                            # EXISTING LADDER AND WRITING NO NEW REMOVAL CODE -- the same one statement
                            # the other two ride, so a geo-refused handle takes the same drop / sever /
                            # kill path and is charged the same `binding_refused`.
                            # IT IS NESTED INSIDE THE DIRECTION `else` ON PURPOSE, AND THAT IS THE
                            # `MIS_BOUND_PROJECTION` DEDUP RULE MADE STRUCTURAL: a handle can be
                            # convicted by AT MOST ONE class, so `emf`'s
                            # `by_rule[scope] + by_rule[direction] + by_rule[geo]` can never
                            # double-count one handle against R11's frozen ceiling of 15. A flat
                            # ordering would have let one handle charge two classes and inflate the
                            # wave's own mis-binding metric with its own arithmetic.
                            # ORDERED BEFORE THE `standin` FLIP BELOW, exactly as the other two are, so
                            # a geo-refused handle is never promoted into a slot it cannot fill.
                            _gclaim = _handle_geo_phrase(text, s0, s1, m.start(), m.end())
                            _gcomp, _gmis = _slot_geo_mismatch(_gclaim, _call, pairs[0][0])
                            if _gcomp:
                                census["geo_checked"] += 1
                            if _gmis:
                                census["geo_mismatch"] += 1
                                value, live, live_pairs, refused = None, [], [], True
                # (a) THE FLIP. The model wrote no digit, so a solitary resolved handle IS the figure --
                # the cue confirms, it no longer gates. Ordered AFTER the refusals so a refused handle
                # is never promoted into a standin it cannot fill.
                if len(pairs) == 1 and isinstance(value, str):
                    standin = True
                # (b) GROUPED-IN-SLOT. Only the CUE can establish it: without a value-introducing word
                # there is no empty slot and a group beside prose is an ordinary co-citation.
                gslot = bool(value is not None and len(pairs) > 1
                             and _HANDLE_VALUE_SLOT_RX.search(text[s0:m.start()]))
            if standin and isinstance(value, str) and _figure_already_stated(text, s0, s1, m, value):
                standin = False                    # -> the ordinary "resolved beside a stated number" branch
            recs.append((m, value, s0, s1, standin, pairs, live, live_pairs, gslot, refused, dead_empty))
        # A `grouped_in_slot` token is on its way OUT, so it backs nothing: counting it here would let it
        # rescue a neighbouring unresolvable handle from a kill it has earned.
        backed = {(r[2], r[3]) for r in recs if r[1] is not None and not r[8]}
        backed_at = [r[0].start() for r in recs if r[1] is not None and not r[8]]
        for m, value, s0, s1, standin, pairs, live, live_pairs, gslot, refused, dead_empty in recs:
            if gslot:
                # D-HP-11(b): NEVER spliced (a group stands in for no single figure), never left standing
                # (a literal `[N13, N14]` in a value slot is the D-PQ HANDLE-1 defect). The clause goes.
                a = _handle_clause_start(text, s0, m.start())
                if any(a <= p < m.end() for p in backed_at):
                    a = m.start()                 # ...never swallow a resolved handle to remove this one
                if a > s0 and text[a - 1] == " " and (m.end() >= len(text)
                                                      or text[m.end()] in " ,.;:)!?"):
                    a -= 1
                op = (a, m.end(), "")
                ops.append(op)
                narrowed[op] = len(pairs)
                census["handles_dropped"] += len(pairs)
                census["grouped_in_slot"] += 1
                continue
            if value is not None:
                if standin and len(pairs) == 1:
                    ops.append((m.start(), m.start(), value + " "))
                    census["substituted"] += 1
                elif len(live_pairs) != len(pairs):    # a PARTIALLY resolvable group -> keep what resolves
                    op = (m.start(), m.end(), _n_handle_token_pairs(live_pairs))
                    ops.append(op)
                    narrowed[op] = len(pairs) - len(live_pairs)
                    census["handles_dropped"] += narrowed[op]
                    # R2-a: the departed members split by WHY they departed. `dead_empty` is a subset of
                    # `narrowed[op]` by construction (both are counted off the same dead-member list), so
                    # the two counters always sum to what `unresolvable` alone used to carry.
                    # (`dead_empty` is 0 unless `handle_prose`, so the control census never grows a key.)
                    if dead_empty:
                        census["empty_row_addressed"] += dead_empty
                    census["unresolvable"] += narrowed[op] - dead_empty
                continue
            # ══ H1 FIX Z2 -- A BINDING REFUSAL IS NOT AN UNRESOLVABLE HANDLE ══════════════════════════
            # D-HP-17 item 4 defines `unresolvable` as "the model addressed a receipt that does not
            # exist". A D-HP-13/D-HP-14 refusal is the opposite state: the receipt EXISTS and resolved,
            # and this pass declined to bind it. Routing refusals through `unresolvable` made two
            # pre-registered clauses mutually unsatisfiable -- G1 clause (2) requires
            # `number_handles.unresolvable == 0` on EVERY treatment row while R11 budgets 15 mis-bound
            # events -- so one legitimate fire of the wave's own designed behaviour failed the gate. It
            # also polluted `handles_unresolvable`, which the successor family calls "the wave's residual".
            # THE REMOVAL IS UNCHANGED (value=None still takes the shipped drop/sever/kill ladder); only
            # the ACCOUNTING moves, to its own counter beside the two class counters that name the reason.
            # ══ R2-a -- AND AN EMPTY-ROW ADDRESS IS NOT AN UNRESOLVABLE HANDLE EITHER ═════════════════
            # The same distinction one rung down: `unresolvable` means the receipt DOES NOT EXIST, and a
            # menu row that exists and carries no value is a different fact about a different failure.
            # THE REMOVAL IS UNCHANGED -- this token still takes the drop/sever/kill ladder below; only
            # the accounting splits. Control arm: `dead_empty` is 0 by construction, so this line reads
            # `census["unresolvable"] += len(pairs)` exactly as it did.
            if refused:
                census["binding_refused"] += len(pairs)
            else:
                if dead_empty:                # 0 unless `handle_prose` -- the control census never grows
                    census["empty_row_addressed"] += dead_empty
                census["unresolvable"] += len(pairs) - dead_empty
            if standin and (s0, s1) in backed:
                # MIXED: sever the clause instead of the sentence. Falls back to the bare token drop when
                # the clause would swallow the resolved handle that is the reason to keep the sentence.
                a = _handle_clause_start(text, s0, m.start())
                if any(a <= p < m.end() for p in backed_at):
                    a = m.start()
                if a > s0 and text[a - 1] == " " and (m.end() >= len(text)
                                                      or text[m.end()] in " ,.;:)!?"):
                    a -= 1                        # the ONE separating space, as in the bare-drop leg below
                op = (a, m.end(), "")
                ops.append(op)
                narrowed[op] = len(pairs)
                census["handles_dropped"] += len(pairs)
            elif standin:
                # a sentence starting the field owns the space AFTER it, so the field never opens on an
                # indent (verify._drop_span's rule, restated -- answer cannot import a closure)
                e = s1
                if s0 == 0:
                    while e < len(text) and text[e] == " ":
                        e += 1
                if (s0, e) not in kills:
                    kills.append((s0, e))
                    census["sentences_dropped"] += 1
            else:
                # eat the ONE separating space when the handle is trailed by whitespace or punctuation,
                # so "446 [N9], known" leaves "446, known" and not a double space before the comma. The
                # verifier's own strip does not bother because it runs before humanize; this pass is the
                # last thing to touch the prose before the sanitize that renders it.
                a = m.start()
                if a and text[a - 1] == " " and (m.end() >= len(text) or text[m.end()] in " ,.;:)!?"):
                    a -= 1
                op = (a, m.end(), "")
                ops.append(op)
                narrowed[op] = len(pairs)
                census["handles_dropped"] += len(pairs)
        if not ops and not kills:
            continue
        # a substitution inside a killed sentence is moot -- the sentence is going, so the op is dropped
        # AND uncounted (the census must report what the reader's page actually received). `narrowed`
        # carries the MEMBER COUNT each removal op charged, so a grouped token swallowed by a kill gives
        # back exactly what it took (a solitary handle's entry is 1, which is the pre-HANDLE-2 arithmetic).
        kept = [o for o in ops if not any(k0 <= o[0] < k1 for k0, k1 in kills)]
        census["substituted"] -= sum(1 for o in ops if o not in kept and o[0] == o[1])
        census["handles_dropped"] -= sum(narrowed.get(o, 1) for o in ops if o not in kept and o[0] != o[1])
        merged = sorted(kept + [(k0, k1, "") for k0, k1 in kills], key=lambda o: (o[0], o[1]))
        out, pos = [], 0
        for a, b, repl in merged:
            if a == b:                            # an INSERTION (the value splice)
                if a < pos:                       # ...already swallowed by a preceding deletion
                    continue
                out.append(text[pos:a])
                out.append(repl)
                pos = a
                continue
            if b <= pos:                          # a deletion already fully consumed
                continue
            # CLAMP rather than SKIP. A first-sentence kill eats its trailing spaces (the leading-indent
            # rule), so the NEXT sentence's recorded start sits BEHIND the cursor -- skipping on `a < pos`
            # silently kept the second unbackable sentence on the page while still counting it dropped.
            a = max(a, pos)
            out.append(text[pos:a])
            out.append(repl)
            pos = b
        out.append(text[pos:])
        new = "".join(out)
        if not text[:1].isspace():                # a field that did not open on whitespace must not start
            new = new.lstrip(" \t")               # doing so because the sentence in front of it was killed
        structured[field] = new
    return census


# ══ H1 FIX Z1/Z6 -- THE D-HP-NATIVE RENDER CLASSES BELONG IN THE ONE STRIP LEDGER ═════════════════════
# THE DEFECT, IN ONE LINE: `emf.MIS_BOUND_CLASSES` and G1 clause (4)'s CLASS SCAN both read `by_rule`, and
# these three classes were only ever written into `trace['number_handles']` -- so `mis_bound_count` (the
# wave's #1-risk metric and R11's ceiling of 15) read `direction_sign_mismatch` as 0 FOREVER, and the
# class scan -- section 2's named primary regression detector -- was blind to three of the four classes
# G1 clause (4) declares. That is exactly the D5 failure emf.py's own block comment names: "a family that
# congratulates the wave".
# WHY THE LEDGER AND NOT A SECOND READER: `by_rule` is the ONE place a strip class is counted, and every
# consumer already reads it (the class scan, the per-answer projection, the successor family, the EMF
# counters). Teaching one more consumer to look somewhere else would leave the other three blind and
# would make "which classes fired" a question with two answers.
# `stripped` IS INCREMENTED ALONGSIDE, and that is the ledger's own invariant, not bookkeeping garnish:
# every `by_rule[x] += 1` in verify.py is paired with `stripped += 1`, so a class folded in without its
# strip would break `sum(by_rule.values()) == stripped`. Each of these three events DID remove prose from
# the reader's page, so counting it as a strip is the honest reading, not an inflation.
# TREATMENT-LANE ONLY: these keys exist only when `handle_prose` ran, so a control row's `by_rule` and
# `stripped` are byte-identical (the OFF-arm-clean rule).
# D-HP-25 V1 (plan 10.30.6): `geo_mismatch` IS THE FOURTH MEMBER, and the census key and the ledger class
# are ONE SPELLING deliberately -- this tuple is read as BOTH ("`number_census.get(cls)` -> `by_rule[cls]`"
# in `_fold_render_classes`), so a class whose ledger name differs from its census name would need a
# rename hook, and a rename hook is the second grammar that lets two readers of one page drift apart.
# Plan 10.30.6 named the class "e.g. `geo_scope_mismatch`"; the "e.g." is discharged HERE, in favour of
# the spelling the census already carries. THE SPELLING IS THE SEAM CONTRACT (the rule stated at
# `emf.KILLED_CLASSES`): `emf.G1_DECLARED_CLASSES`, `emf.ARM_EXCLUSIVE_CLASSES`, `emf.MIS_BOUND_CLASSES`,
# `eval._refusal_census` and this tuple all say `geo_mismatch` and nothing translates between them.
_RENDER_LEDGER_CLASSES: tuple[str, ...] = ("slot_scope_mismatch", "direction_sign_mismatch",
                                           "grouped_in_slot", "geo_mismatch")
# H1 FIX W2 (finding NF-2) -- THE FOURTH FOLDED CLASS, AND THE ONE THE LEDGER OWED MOST.
# `slot_orphan_dropped` (the Z4/W1 remedy) DELETES WHOLE SENTENCES and had no counterpart anywhere: not a
# `by_rule` class, not an `emf` successor term, not a column -- so a G2 fluency movement it caused was a
# movement with no readable cause in any G1/G2 artifact. It folds here, under the SAME rule as the three
# above (`by_rule` + `stripped` together, treatment lane only, one location every consumer already reads).
# WHAT IT COUNTS, STATED SO NOBODY READS IT AS A SECOND CONVICTION: the CONVICTION was the verifier's and
# is already charged under ITS class (`no_lexical_overlap`, `quote_mismatch`, ...). This class counts the
# SECOND PAGE LOSS that conviction caused -- the sentence the reader lost after the handle went. The
# ledger has always counted removals of prose, one entry per removal, which is exactly what keeps
# `sum(by_rule.values()) == stripped` true; two removals from one conviction are two entries.
# IT IS IN NO `emf` SUCCESSOR TUPLE ON PURPOSE (see the note at `emf.MIS_BOUND_CLASSES`): it is not a
# mis-binding, not a killed class and not one of the four that survive by construction. It is DECLARED in
# G1 clause (4)'s class set (plan section 10.11) so the class scan reads it instead of failing on it.
_SLOT_ORPHAN_CLASS: str = "slot_orphan"
# ══ D-HP G1 REMEDIATION D2(b), 2026-08-14 -- THE FIFTH FOLDED CLASS: AN [E] HANDLE IN A VALUE SLOT ═════
# G1 clause (2b) pre-registers `bare_handle_escapes == 0` on the treatment arms and the r2 run set read 7
# over 4 rows -- every one a SOLITARY, FULLY RESOLVED [E] token immediately behind a value cue ("priced at
# [E1]", "range from [E17]", "from 500 to [E10] thousand metric tons"). The clause had an INSTRUMENT
# (`eval._bare_handle_escapes`, H2) and NO REMEDY: `_resolve_number_handles` owns the [N] half (splice a
# solitary resolved handle, sever a grouped one), and `_resolve_evidence_handles` acted only on
# UNRESOLVABLE [E], so a resolved [E] in a slot was left standing by construction on both arms. That is
# D-PQ HANDLE-1's own defect -- the sentence promised a figure it cannot produce -- and it takes D-PQ
# HANDLE-1's own remedy: sever the clause when the sentence keeps another receipt, drop the sentence when
# it does not. NEVER a substitution: an [E] payload is a source, a date and a snippet, so there is no
# figure to write and inventing one is the class this wave exists to make unconstructible.
# IT IS A NEW DECLARED CLASS, on the `slot_orphan` / `episode_span_unbacked` precedent, and it MUST JOIN
# G1 CLAUSE (4)'s DECLARED SET AT THE RE-FREEZE or the clause is pre-registered to fail on the wave's own
# remedy. It is in `emf.G1_DECLARED_CLASSES` and `emf.ARM_EXCLUSIVE_CLASSES` (the seventh arm-exclusive
# class) and in no successor tuple: nothing was mis-bound (the handle resolved and named the right item),
# it is not one of the four killed classes, and it is not a verifier residual -- it is a RENDER-side
# conviction with its own remedy, exactly like `grouped_in_slot`, which is the [N]-side twin of it.
_E_VALUE_SLOT_CLASS: str = "evidence_handle_in_slot"
# ══ D-HP-25 V2 (plan 10.30.4) -- THE SIXTH FOLDED CLASS: AN [E] RECEIPT THAT CONTRADICTS THE GEOGRAPHY ═
# THE CONSTRAINT THAT DICTATES THE WHOLE DESIGN: evidence rows carry NO geo, NO commodity and NO scope
# fields at any layer -- `evidence.py:486-490` projects exactly `date, source, source_key, text,
# event_date, event_date_precision, score`. There is no facet to compare, adding one is a store-schema
# change, a store-schema change is a RE-CHUNK, and re-chunking is FORBIDDEN by the standing chunk-once
# law. So this axis works on TEXT CONTAINMENT or it does not exist, and what it convicts is a POSITIVE
# CONTRADICTION -- never an absence.
# IT IS A NEW SIBLING PASS AND BOTH REJECTED ALTERNATIVES ARE NAMED, because each is a defect this estate
# has already paid for:
#   * NOT A WIDENING OF `_drop_evidence_value_slot`. Different class semantics -- that pass convicts a
#     resolved [E] standing in a VALUE SLOT, this one convicts a resolved [E] whose TEXT names a
#     different country than the sentence does. Folding two classes into one census key destroys the
#     accounting the class scan reads.
#   * NOT A HOOK IN `_resolve_evidence_handles`. Shrinking `live` there MIS-CHARGES `unresolvable` --
#     that function acts only on UNRESOLVABLE [E] and a conviction booked through it inflates the wrong
#     denominator. THAT IS THE H1 FIX Z2 ERROR AND IT IS NOT REPEATED.
# IT JOINS `emf.G1_DECLARED_CLASSES` and `emf.ARM_EXCLUSIVE_CLASSES` on the `evidence_handle_in_slot`
# precedent, and -- UNLIKE that class -- IT ALSO JOINS `emf.MIS_BOUND_CLASSES`: a receipt that names the
# wrong country IS a wrong receipt, and excluding it would let this wave count the finds and not the
# finding. It is NOT in `emf.KILLED_CLASSES` (a RENDER conviction must not inflate
# `unconstructible_count`; plan 10.10(c) forbids exactly that contamination).
_E_GEO_CONTRADICTION_CLASS: str = "evidence_geo_contradiction"


def _fold_ledger_class(verifier: dict | None, cls: str, n) -> int:
    """Fold ONE render-side class into the verifier's ONE strip ledger, `by_rule` and `stripped` together
    so the ledger's sum invariant holds. Returns the number of events folded. Never raises.

    THE ONE WRITER: every render-side charge goes through here, so "which classes the render passes may
    add to the ledger, and what they must do to `stripped` when they do" has exactly one answer."""
    try:
        n = int(n or 0)
        if n <= 0 or not isinstance(verifier, dict):
            return 0
        by = verifier.get("by_rule")
        if not isinstance(by, dict):
            return 0
        by[cls] = int(by.get(cls, 0) or 0) + n
        verifier["stripped"] = int(verifier.get("stripped", 0) or 0) + n
        return n
    except Exception:  # noqa: BLE001 -- an instrument must never break a turn
        return 0


def _fold_render_classes(verifier: dict | None, number_census: dict | None) -> int:
    """Fold the D-HP-native render classes into the verifier's ONE strip ledger. Returns the number of
    events folded (0 on a control turn, and on any treatment turn where none fired). Never raises."""
    try:
        if not isinstance(verifier, dict) or not isinstance(number_census, dict):
            return 0
        return sum(_fold_ledger_class(verifier, cls, number_census.get(cls, 0))
                   for cls in _RENDER_LEDGER_CLASSES)
    except Exception:  # noqa: BLE001 -- an instrument must never break a turn
        return 0


def _wrong_slot_audit(number_census: dict | None) -> dict:
    """D-HP-14's census, projected from the [N] pass's own counters into the SHAPE `tracekeys` froze:
    `{scope_checked, scope_mismatch, direction_checked, direction_mismatch}`.

    IT IS A PROJECTION, NOT A SECOND MEASUREMENT, and that is the point -- the numbers a gate reads and
    the numbers that actually deleted prose are the same numbers. Two producers for one risk is how a
    census comes to say 0 while the page lost a sentence.

    WHAT `scope_checked` MEANS, EXACTLY, so the column never claims coverage it does not have: PERIOD
    checks only (see `_slot_scope_mismatch`). The commodity and unit-class axes of D-HP-14(a) are NOT
    BUILT in this pass -- commodity needs a vocabulary this seam is not threaded, and unit class is the
    quantity the cycle-10 repair fence compared and got wrong. `direction_checked` counts the handles that
    survived the scope check and were asked D-HP-13's question at all (a metric outside the POLARITY TABLE
    is counted as asked and answered "no mismatch", because the table's closure IS the answer).

    R11 READS THIS PER ROW: `mis_bound_count` = `slot_scope_mismatch` + `direction_sign_mismatch` +
    `wrong_slot_audit.scope_mismatch`, ceiling 15 pooled per treatment arm, with any single row at >= 3
    recorded BY ID. A per-run-only census would make that ceiling uncheckable at the level it is written
    at, which is why the shape is per turn and lands on the trace beside the render census it comes from.
    THE THIRD TERM IS A PROJECTION OF THE FIRST AND MUST NOT BE ADDED TWICE -- the dedup rule is stated
    once, at `emf.MIS_BOUND_CLASSES`, and every consumer reads the arithmetic from there."""
    c = number_census or {}
    return {"scope_checked": int(c.get("scope_checked", 0) or 0),
            "scope_mismatch": int(c.get("slot_scope_mismatch", 0) or 0),
            "direction_checked": int(c.get("direction_checked", 0) or 0),
            "direction_mismatch": int(c.get("direction_sign_mismatch", 0) or 0)}


def _sentence_has_resolved_handle(text: str, s0: int, s1: int, calls: list,
                                  skip: tuple[int, int] | None = None) -> bool:
    """True when the sentence `[s0, s1)` carries a citation handle that RESOLVES -- an [N] member with a
    real value, or any in-range [E] member. `skip` excludes one span (the clause about to be severed), so
    the question is always "does anything OUTSIDE the cut survive to justify keeping the sentence".
    [E] resolution is an INDEX-RANGE question here on purpose: the evidence list this pass would join is
    not threaded into the [N] lane, and over-counting an [E] as resolved can only ever make this function
    SEVER where it would otherwise KILL -- the smaller deletion, which is the safe direction."""
    sent = text[s0:s1]
    for m in _N_HANDLE_RX.finditer(sent):
        if skip and s0 + m.start() >= skip[0] and s0 + m.end() <= skip[1]:
            continue
        for i, sfx in _n_handle_pairs(m.group(0)):
            if _number_handle_value(calls[i - 1] if 1 <= i <= len(calls) else None, i, sfx) is not None:
                return True
    for m in _E_HANDLE_RX.finditer(sent):
        if skip and s0 + m.start() >= skip[0] and s0 + m.end() <= skip[1]:
            continue
        if _e_handle_members(m.group(0)):
            return True
    return False


# H1 FOLD ROUND 3 (2026-08-13) -- FIX X2. THE SEAM CARRIER IS SHARED, SO EVERY SEAM NAMES ITS PRODUCER.
# `strip_seams` is written by FOUR passes now (verify's positional strips, the digit-lint's remedy, this
# file's [E] prune and the slot-orphan drop's own repair mint), and two consumers read it for DIFFERENT
# questions. TIDY-2 asks "did SOMETHING get removed just before this orphan line" -- every producer
# answers that, so `_seam_adjacent` accepts every tag and is unchanged. The slot-orphan licence asks the
# narrower "was a VALUE SLOT emptied at this exact cut", which only the SLOT-EMPTYING producers can
# answer. Inferring that from the list was impossible; the tag makes it a read.
# THE SEAMS ARE PER-TURN, IN-MEMORY ONLY: `_VerifyReport.strip_seams` is an attribute no serializer can
# see (verify.py's `_VerifyReport` note), and the GRAPHRAG_STRIP_AUDIT copy is a debug projection built
# from each in-flight dict by `verify._projected_seam` -- a CUT COPY, 40 chars of key, never the carrier's
# own object (H1 FOLD ROUND 5, W-A). No artifact, client or durable record carries this shape, so widening
# the RECORD is a free change -- the only thing that had to move with it is hand-built fixtures. Widening
# the PROJECTION is not free and is bounded at the projection site; read `_mint_strip_seam` below.
_SEAM_SRC_VERIFY = "verify"          # verify._verify_field -- a convicted handle span, removed by position
_SEAM_SRC_BARE_DIGIT = "bare_digit"  # _drop_bare_digit_sentences -- a WHOLE sentence, D-HP-12's remedy
_SEAM_SRC_EV_PRUNE = "ev_prune"      # _prune_orphan_evidence_handles -- an [E] marker with no footer row
_SEAM_SRC_SLOT_ORPHAN = "slot_orphan"  # _drop_slot_orphan_sentences -- a WHOLE sentence, Z4/W1's remedy
# D-HP G1 REMEDIATION D2(b): _resolve_evidence_handles' value-slot kill -- a WHOLE sentence, so it is a
# TIDY-2 producer and NOT a licensing one (X2's rule: the sentence it cut is gone, so nothing it mints is
# evidence that a surviving sentence was emptied). `allow_empty` is therefore False at its mint (X6's
# whole-sentence answer). Treatment-gated, so no control turn mints it and the OFF arm is byte-identical.
_SEAM_SRC_E_VALUE_SLOT = "e_value_slot"
# D-HP-25 V2 (plan 10.30.4): `_drop_evidence_geo_contradiction`'s kill -- a WHOLE sentence, so it takes
# the IDENTICAL X2 position as the value-slot kill above: a TIDY-2 producer and NOT a licensing one (the
# sentence it cut is gone, so nothing it mints is evidence that a SURVIVING sentence was emptied), and
# `allow_empty` False at its mint (X6's whole-sentence answer). Treatment-gated, so no control turn mints
# it and the OFF arm is byte-identical.
_SEAM_SRC_E_GEO = "e_geo"
# THE LICENCE SET, and it is the whole of FIX X2: a producer belongs here when its deletion can leave a
# value slot EMPTY IN A SURVIVING SENTENCE. `verify` strips a handle out of the middle of a sentence and
# `_prune_orphan_evidence_handles` removes an [E] marker from one; both leave "...stood at." on the page.
# The two whole-SENTENCE producers cannot: the sentence they cut is gone, so nothing they mint is evidence
# that anything was emptied -- their seams exist for TIDY-2's join and for that only.
_SLOT_EMPTYING_SEAM_SRCS = frozenset({_SEAM_SRC_VERIFY, _SEAM_SRC_EV_PRUNE})


def _mint_strip_seam(vreport, field: str, tail: str, *, src: str,
                     allow_empty: bool = False) -> None:
    """Record a render-side cut on the verifier's INTERNAL seam carrier, in verify's own shape and with
    verify's own normalization (H1 FIX Z12), tagged with its PRODUCER (H1 FIX X2).

    WHY THE RENDER PASSES MUST MINT THEIR OWN: `_tidy_strip_orphans` repairs the paragraph seam a
    whole-sentence strip opens, and it joins on `report.strip_seams` -- which only `verify._verify_field`
    ever populated. A sentence deleted by the digit-lint's remedy (or by the value-slot orphan pass) was
    therefore invisible to TIDY-2, so its successor could be left as a headless fragment with nothing able
    to repair it. The seam is the text FOLLOWING the cut, exactly as verify records it, so one
    `_seam_adjacent` compare serves both producers.

    THE COUNTERS ARE NOT TOUCHED: `strip_seams` is a POSITION carrier, never a count. This function writes
    no `stripped`, no `by_rule`, no `strip_audit` entry -- the charge for a bare-digit sentence is verify's
    and stays verify's. Never raises: a cosmetic carrier must not cost an answer.

    `src` IS MANDATORY (keyword-only, FIX X2): a seam with no producer is a seam no consumer can classify,
    and the slot-orphan licence fails CLOSED on one. Every call site names its constant above.

    `allow_empty` IS THE X6 DECISION, and it is stated identically at verify's own mint (verify.py's seam
    loop). An end-of-field cut leaves NO successor text -- key "" -- and the two producer kinds want
    opposite answers. A SLOT-EMPTYING producer passes True: "...stood at [E1]" with no terminator is a real
    position and a real emptied slot, and refusing its seam would blind the licence to the field-final
    shape, which handle-only prose makes common. A WHOLE-SENTENCE producer leaves it False: its seams
    exist for TIDY-2, an empty key can never join to an orphan line, and minting one would be a licence-
    shaped record standing for nothing.

    THE GRAPHRAG_STRIP_AUDIT PROJECTION IS MIRRORED HERE (H1 FIX Y5), for the same reason verify writes it
    and under the same flag read the same way. Before this, the ONE debug surface for seams was
    verify-only: a gate owner who turned the audit on to see whether the `ev_prune` producer fired, or
    which `src` licensed a deletion, got a projection that was blind to every render-side producer BY
    CONSTRUCTION (driven: 4 seams on the in-memory carrier, 2 in the projection, no non-`verify` tag
    visible). It is OBSERVABILITY ONLY -- no counter, no decision, and the licence reads the attribute.

    THE LEAK FENCE IS TWO THINGS, AND THE SECOND ONE IS ROUND 5'S (FIX W-A).
      (1) THE FLAG, UNCHANGED. With the audit off this writes the ATTRIBUTE and NOTHING to the dict, so
          `dict(report)`, `json.dumps(report)` and every trace projection are byte-identical to before.
      (2) THE WIDTH, APPLIED AT THE PROJECTION AND NOWHERE ELSE. `key` below is the FULL
          `_SEAM_LOOKAHEAD`-wide normalized form and MUST STAY THAT WIDE on the carrier, because the
          licence compare needs it: `_licence_canon` DELETES characters before comparing 32 of them, so a
          key cut at 40 raw characters can carry fewer than 32 canonical ones and a real cut goes
          unlicensed (verify's `_SEAM_KEY_CHARS` note holds the two driven reproductions). What the
          PROJECTION publishes is a CUT COPY through `verify._projected_seam` -- 40 characters, for every
          producer. Round 4 appended the SAME dict object to both, so the audit published up to 120
          characters of PRE-SANITIZE prose per seam on `trace['citation_verifier']`, which `/v1/respond`
          returns whole: MEASURED at 119 characters per seam and 28 seams / 3,240 JSON bytes on
          `data/dmw_p4/tier_20260812T051533Z.json`'s mechanism, three times the class FIX-CYCLE-2 review
          major 7 bounded to 40, on a flag the repo's config-of-record says is live in serving. The
          in-memory carrier is NOT cut and must not be -- no serializer can see it at all.
    So with the flag on, the record is the same `{field, key, src}` shape verify publishes, in the same
    40-character key class and with a fixed-enum tag, no prose."""
    try:
        from leviathan.graphrag import verify as _vf
        key = _seam_key(str(tail or "")[:_vf._SEAM_LOOKAHEAD])
        if vreport is None or (not key and not allow_empty):
            return
        seams = getattr(vreport, "strip_seams", None)
        if isinstance(seams, list):
            seam = {"field": field, "key": key, "src": src}
            seams.append(seam)
            if isinstance(vreport, dict) and os.environ.get("GRAPHRAG_STRIP_AUDIT", "off") != "off":
                proj = vreport.setdefault("strip_seams", [])   # verify's own projection, the same list
                if isinstance(proj, list):
                    # W-A: a CUT COPY of the record, never `seam` itself -- the carrier stays full width.
                    proj.append(_vf._projected_seam(seam))
    except Exception:  # noqa: BLE001 -- a seam carrier must never break a turn
        return


# ══ H1 FIX Z4 -- A STRIP THAT EMPTIES A VALUE SLOT TAKES THE WHOLE SENTENCE ═══════════════════════════
# THE DEFECT, REPRODUCED END TO END: `verify_citations` runs BEFORE the handle passes and removes a
# convicted handle span BY POSITION. Under D-HP-7 the slot is empty by contract, so the sentence loses its
# figure AND its handle at once and renders as "US corn ending stocks stood at." -- a truncated fragment on
# the reader's page. The handle passes cannot help: the token is already gone, so D-HP-10's drop/sever/kill
# ladder never sees it, and `_tidy_handle_debris` closes BRACKET frames, not a dangling value word.
# HANDLE-ONLY PROSE TURNS THIS FROM AN EDGE CASE INTO THE GENERAL CASE. On the control arm the model also
# typed the digit, so the same strip leaves "...stood at 12.5 mil bu." -- a complete sentence. On the
# treatment arm EVERY figure lives in a slot, so EVERY one of the four RESIDUAL classes G1 declares survive
# by construction (no_lexical_overlap, quote_mismatch, foreign_regime_name, index_out_of_range) produces a
# fragment, on the treatment arm and on the treatment arm only -- which lands on G2 (fluency do-no-harm)
# and on the reader.
# THE REMEDY IS THE WHOLE SENTENCE, NOT A SEVER, and the reason is that the anchor is gone: every other
# remedy in this file computes its clause from the HANDLE's own position, and there is no handle left here
# to compute from. A cue-anchored sever would be a second, weaker locality rule invented for the hardest
# case; "the sentence promised a figure it cannot produce" is D-PQ HANDLE-1's own rule and it is the one
# the rest of the stack already applies to exactly this state.
# THE TEST IS TWO CONDITIONS, AND THE FIRST ONE IS THE STRIP (H1 FIX W1, finding NF-1).
#   (i) A RECORDED STRIP AT THIS SENTENCE'S OWN CUT POSITION -- the verifier's own drop record, never a
#       lexical shape; and
#  (ii) the shipped cue read at what is left of the sentence's end. `_HANDLE_VALUE_SLOT_RX` is the same
#       enumerated value-introducing word set the splice uses, so prompt, splice and this pass cannot
#       disagree about what a value slot is.
# THE CUE ALONE WAS NOT EVIDENCE OF ANYTHING, AND THAT IS MEASURED, NOT ARGUED. Shipped as a cue-only
# scan, this pass deleted 314 of 32,557 sentences (0.96%) across the estate's own stored prose -- almost
# all of them grammatically complete, fully backed sentences that never carried a handle at all. Two whole
# classes were this house's idiom: "...documented as active at this as-of." went to nothing (`\bof\s+$`
# matches across the hyphen) and "Production vs. exports diverged in June." lost its SUBJECT ("vs." reads
# as a terminator AND "vs" is itself a cue). The pass is treatment-gated, so 100% of that delta would have
# been attributed to the arm on G2 (fluency do-no-harm) and paid by the reader.
# THE LINKAGE IS A SLOT-EMPTYING PRODUCER'S OWN SEAM RECORD, which exists for precisely this reason:
# `verify._verify_field` mints one `{field, key, src}` per applied deletion, `key` being the normalized
# successor text at the cut (verify.py's seam loop), and `_prune_orphan_evidence_handles` mints the same
# record when it removes an [E] marker from a slot. A sentence whose handle was emptied out of its value
# slot therefore carries a recorded seam AT THE POSITION THIS PASS WOULD CUT, and a sentence that merely
# ends on a cue word does not. The join is by normalized text rather than by position because no
# downstream pass preserves positions -- the same rule `_tidy_strip_orphans` has always used, and the same
# `_seam_key`.
# THE SNAPSHOT IS TAKEN ONCE, BEFORE ANY CUT, so this pass can never license itself off a seam it minted.
#
# ══ H1 FOLD ROUND 3 (2026-08-13) -- WHAT THIS LICENCE IS AND, PRECISELY, WHAT IT IS NOT ═══════════════
# THREE CORRECTIONS, each raised with a reproduction by the round-2 adversarial verifier and each folded
# rather than argued away. Read them as the licence's actual contract; the paragraphs above state the
# INTENT, these state the GUARANTEE.
#
# (X2) THE SEAM LIST IS NOT VERIFIER-ONLY, AND NEVER WAS AFTER Z12. `_drop_bare_digit_sentences` is a
# RENDER pass, runs FIRST in the handle stack on BOTH bodies, and mints into the SAME carrier, so the
# snapshot this pass takes already contains render-minted seams. REPRODUCED: a newline-bounded list where
# the digit-lint deletes line 2 mints a seam whose key is line 3's text -- and line 1, a complete sentence
# the verifier never touched, normalizes to the same key and was deleted off it. A terminator-less
# sentence has no punctuation to distinguish "my own cut" from "the line after me", so ADJACENCY became a
# licence, which the pass's own pin docstring explicitly denies. THE FIX IS PROVENANCE, not a punctuation
# heuristic: every seam carries `src`, and only the SLOT-EMPTYING producers (`verify`, `ev_prune`) license
# a cut. A whole-sentence producer's seam is TIDY-2 material and nothing else.
#
# (X3a) A SEAM LICENSES AT MOST ONE CUT. `_slot_orphan_licensed` CONSUMES the seam it matched off the
# snapshot, so N recorded strips can license at most N deletions. REPRODUCED before the fix: one strip on
# "Prices settled near [E9]. Trade was thin. Prices settled near. Trade was thin." deleted TWO sentences,
# the second of which nothing had ever touched. The blast radius of a text-join collision is now bounded
# by the number of strips the turn actually applied, which is the only bound the join itself can offer.
#
# (X3b) THE JOIN IS A BOUNDED-PREFIX TEXT JOIN. IT IS NOT POSITIONALLY EXACT, AND NOTHING HERE MAY CLAIM
# IT IS. Two cut positions in one field whose successors agree for min(len, 32) >= 8 normalized characters
# license each other; under repeated boilerplate that is reachable, and the WRONG sentence can die while
# the one a strip actually hit survives. REPRODUCED at 32 chars (a repeated 65-char house sentence) and at
# 17 (a repeated short field-final sentence). MEASURED CORPUS EXPOSURE IS ZERO: an exhaustive positional
# scan -- every character position in all 207 cue-bearing fields turned into the seam verify would mint,
# tested against every cue tail -- found 314/314 cue sentences licensable ONLY from their own cut and zero
# foreign licences, across 32,557 stored sentences. ACCEPTED AS A RESIDUAL: positions do not survive
# humanize/scaffold/sanitize, so a positional join is not available at this seam, and G2's fluency
# do-no-harm read is the runtime guard that would surface a real collision. The residual is bounded by
# X3a's one-shot rule and is recorded at plan 10.11.
#
# (X3b, THE OTHER DIRECTION -- H1 FOLD ROUND 4, FIX Y4.) THE RECORD ABOVE STATED ONLY THE FALSE-POSITIVE
# HALF, AND THE MISSING HALF WAS THE BIGGER NUMBER. A text join can also REFUSE a cut a producer really
# made, and it did, because THE KEY IS A SNAPSHOT OF TEXT LATER PASSES REWRITE. TWO NAMED REWRITERS, both
# landing INSIDE the compared window, both in the same turn as the mint: `verify._verify_field`'s own
# space-before-terminator cleanup, which fired ten lines after its mint (FIX Y1), and
# `_tidy_handle_debris`, which runs between the [E] prune's mint and this pass (FIX Y2). MEASURED, not
# reasoned: the round-3 corpus oracle -- a sentence is a genuine Z4 fragment iff it carries a handle, its
# core does NOT end on a value cue before the strip and DOES after -- found 59 genuine fragments in stored
# prose, of which the licence removed 45 and 14 SHIPPED (2 unambiguous value-slot fragments plus 12 of
# this house's "at this as-of" idiom); round 4's reconstruction of the same oracle on the same population
# read 58 / 56 / 2, the 2 being the same unambiguous pair. Round 4 fixes both rewriters; the oracle re-run
# after Y1+Y2 ships 0 on both arms.
# DISPOSITION OF THE IDIOM CASES: they die, and that is Z4's own rule applied without an exception
# -- a sentence that lost its evidence handle and ends on a value cue is a sentence promising a figure it
# cannot produce, whatever idiom it is written in. Whether the remedy for that family should be a SEVER
# rather than the whole sentence is a live question and it is a POST-GATE one (plan 10.12); it is not a
# reason to leave the licence refusing.
# THE REMEDY IS THE WHOLE SENTENCE, NOT A SEVER, and the reason is that the anchor is gone: every other
# remedy in this file computes its clause from the HANDLE's own position, and there is no handle left here
# to compute from. A cue-anchored sever would be a second, weaker locality rule invented for the hardest
# case; "the sentence promised a figure it cannot produce" is D-PQ HANDLE-1's own rule and it is the one
# the rest of the stack already applies to exactly this state.
#
# ══ H1 FOLD ROUND 4 (2026-08-13) -- FIX Y2: THE COMPARE HAPPENS IN DEBRIS-FREE SPACE ═════════════════
# THE DEFECT IS THE SAME ONE Y1 FIXES AT THE OTHER PRODUCER, AND IT IS THE ROOT CAUSE OF EVERY FRAGMENT
# THE ROUND-3 VERIFIER COULD STILL LAND ON THE READER'S PAGE: THE SEAM KEY IS A SNAPSHOT OF TEXT THAT
# LATER PASSES REWRITE. `_tidy_handle_debris` runs BETWEEN the mint and this read (serving order:
# [E] prune -> debris -> slot-orphan) and rewrites exactly the punctuation the removals emptied, so the
# key describes a string that no longer exists. FIVE SHAPES DRIVEN END TO END PRE-FIX, for `ev_prune` AND
# for `verify` and in both handle namespaces; the FOUR whose cut is AT the sentence's own end each shipped
# the fragment this pass exists to remove (the fifth is the mid-sentence case at the bottom of this note):
#     "...stood at ([E1])."   -> prune "...stood at ()."  key ")."  -> debris "...stood at."  tail "."
#     "...stood at [[E1]]."   -> ... key "]." ;  "revised to ( [E1] )." -> ... key ")." (rules 2/3)
#     "The record stood at [E1] --."  key "--."  -> debris "The record stood at."  tail "."
# 306 occurrences of the enabling shape (a value-slot cue immediately followed by "(" or "[") sit in the
# estate's stored prose, so this is not a fixture curiosity.
# THE FIX IS AT THE CONSUMER, AND IT IS A CANONICALIZATION OF BOTH SIDES, NOT A RE-MINT. Re-minting after
# the debris pass would need every producer to know which passes still run behind it -- the assumption
# that has now failed twice. `_licence_canon` instead erases the punctuation CLASSES `_DEBRIS_RULES`
# rewrites and applies `_seam_key`'s normalization, to the recorded key and to the pass-time tail alike.
# WHY THAT IS SOUND RATHER THAN JUST CONVENIENT: the pass-time tail is ALWAYS post-debris (the debris
# pass is unconditional and runs first), so a stale key can differ from an honest tail only by debris
# RESIDUE -- bracket/paren frames the tidy erased or closed up, dash runs it collapsed, a separator comma
# it dropped, whitespace it pulled off a terminator. Canon makes exactly those differences invisible and
# nothing else. THE COARSENING IS REAL AND IS BOUNDED THREE WAYS, all pre-existing: the seam must be in
# THIS FIELD, its `src` must be a slot-emptying producer (X2), it is CONSUMED on match (X3a), and the
# sentence must independently end on a value-slot cue. RE-MEASURED AT CORPUS SCALE, not argued: the
# exhaustive positional scan that found 0 foreign licences pre-canon (every character position in all 207
# cue-bearing fields turned into the seam `verify` would mint, tested against every cue tail across
# 32,557 stored sentences) finds 0 foreign licences post-canon as well -- see plan 10.12.
# WHAT IT DOES NOT REACH, STATED SO NOBODY READS MORE INTO IT: canon converges the residue AT a cut; it
# cannot move a cut. "A dash -- [E1] -- stood at." is pruned MID-sentence, so the seam sits before
# "-- stood at." and not at the sentence's own end, and no canonical form of that key is the tail this
# pass computes. That sentence's core ends on a cue BEFORE the strip as well as after, so the corpus
# oracle does not count it as a Z4 fragment either; it is pinned as a recorded non-licence.
_LICENCE_DEBRIS_RX = (
    (re.compile(r"[()\[\]]+"), ""),          # _DEBRIS_RULES 0-3: emptied frames, erased or closed up
    (re.compile(r"-{2,}"), ""),              # _DEBRIS_RULES 4 + 6: a dash left standing / "-- --"
    (re.compile(r",(?=\s*[.;:!?])"), ""),    # _DEBRIS_RULES 5: the emptied list separator "fell,."
    (re.compile(r"\s+([.,;:!?])"), r"\1"),   # _DEBRIS_RULES 7 (and verify._strip_cleanup's half of it)
)


def _licence_canon(s: str) -> str:
    """`_seam_key`'s normalization plus the debris punctuation classes erased (H1 FIX Y2).

    APPLIED TO BOTH SIDES OF THE LICENCE COMPARE AND NOWHERE ELSE. `_seam_adjacent` (TIDY-2) keeps the
    plain `_seam_key` form: it joins a whole ORPHAN LINE against a seam recorded in the same pass order,
    it has no stale-key problem to solve, and widening its join would widen a different pass's blast
    radius for no measured reason."""
    out = _seam_key(s)
    for rx, repl in _LICENCE_DEBRIS_RX:
        out = rx.sub(repl, out)
    return re.sub(r"\s+", " ", out).strip()


# GATED ON THE TREATMENT and stamped per class on the trace before `body_pre_sanitize` (B2's
# drop-with-audit rule), so the control arm is byte-identical and the deletion is never silent.
def _slot_orphan_licensed(seams: list, field: str, tail: str) -> bool:
    """True when a SLOT-EMPTYING producer recorded a cut at the position `tail` runs from, and that record
    has not already licensed another sentence this turn (H1 FIX W1, tightened by X2 + X3a).

    `tail` is the text FOLLOWING the sentence's emptied value slot -- i.e. the terminator and everything
    after it -- which is the same quantity `verify._verify_field` stored as the seam's `key` when it
    applied the deletion. One normalized compare therefore answers "was something removed HERE".

    THREE CONDITIONS, and the first two are provenance rather than text:
      (a) THE SEAM'S FIELD IS THIS FIELD;
      (b) THE SEAM'S PRODUCER CAN EMPTY A SLOT (`_SLOT_EMPTYING_SEAM_SRCS` -- `verify` and `ev_prune`).
          A `bare_digit` / `slot_orphan` seam marks a WHOLE SENTENCE that is gone; it is TIDY-2 material
          and is NEVER a licence. FAIL-CLOSED on an absent or unknown `src`: a record no consumer can
          classify does not get to delete a reader's sentence.
      (c) THE TEXT JOINS, on the compare below.
    A MATCHED SEAM IS CONSUMED (popped off the caller's SNAPSHOT list, never off the report), so one
    recorded cut licenses exactly one deletion. That is what bounds a text-join collision to the number of
    cuts the turn actually made instead of to the number of places the text happens to repeat.

    THE COMPARE IS NOT `_seam_adjacent`, and the difference is the FLOOR. That helper is calibrated for
    TIDY-2's join against a whole ORPHAN LINE (8 normalized chars minimum, 32 cap), and a floor blinds
    exactly the case this pass most needs: the FIELD'S LAST sentence, whose tail is "." or "". Those short
    tails are matched WHOLE instead. Longer tails keep the estate's 32-char prefix rule.

    BOTH SIDES ARE CANONICALIZED FIRST (`_licence_canon`, FIX Y2), because the recorded key is a SNAPSHOT
    OF TEXT LATER PASSES REWRITE and the tail is read after they have. Read the Y2 note above before
    touching either side of this compare.

    THE FALSE-NEGATIVE RESIDUAL, STATED WITH THE SAME DISCIPLINE AS THE COLLISION (FIX Y4). A sentence
    reassuring the reader that only a deep sanitize edit could break an honest match stood here until
    round 4. It was REFUTED and is DELETED rather than softened -- the plan's 10.12 retirement notice
    holds its exact words, and it may not return to this file in any spelling. The edits that broke honest
    matches were neither deep nor sanitize's. TWO REWRITERS, both inside the compared window and both in
    the SAME turn as the mint -- `verify._verify_field`'s own space-before-terminator cleanup, which fired
    ten lines AFTER it minted (FIX Y1), and `_tidy_handle_debris`, which runs between the [E] prune's mint
    and this read (FIX Y2). MEASURED PRE-FIX on the estate's own stored prose by the corpus oracle (a
    sentence is a genuine Z4 fragment iff it carries a handle, its core does NOT end on a value cue before
    the strip and DOES after): round 3 counted 59 genuine fragments, 45 removed and 14 SHIPPED; round 4's
    reconstruction of the same oracle on the same population counted 58 / 56 / 2, the two survivors being
    the two round 3 named unambiguous. POST-FIX BOTH ARMS SHIP 0. "A broken match only ever leaves a
    fragment standing" is not a reassurance -- a standing fragment is the whole of what Z4 was raised for.
    The residual that remains is the one canon cannot reach (a cut that is not at the sentence's own end);
    see the Y2 note and plan 10.12.

    IT IS A TEXT JOIN, NOT A POSITION. Two cuts in one field whose successors agree over the compared
    window license each other; see the X3b note above for the reproduction, the measured zero corpus
    exposure and why the residual is accepted rather than closed. Do not restate this compare as
    positionally exact anywhere."""
    try:
        from leviathan.graphrag import verify as _vf
        fk = _licence_canon(str(tail or "")[:_vf._SEAM_LOOKAHEAD])
        for i, s in enumerate(seams or []):
            if not isinstance(s, dict) or s.get("field") != field:
                continue
            if s.get("src") not in _SLOT_EMPTYING_SEAM_SRCS:      # FIX X2 -- provenance, fail-closed
                continue
            sk = _licence_canon(str(s.get("key") or s.get("after") or ""))
            n = min(len(sk), len(fk), 32)
            hit = (sk[:n] == fk[:n]) if n >= 8 else (sk == fk)
            if hit:
                try:
                    seams.pop(i)                                  # FIX X3a -- ONE seam, ONE cut
                except Exception:  # noqa: BLE001 -- an unpoppable carrier must not cost the licence
                    pass
                return True
        return False
    except Exception:  # noqa: BLE001 -- a render guard must never be the thing that breaks an answer
        return False


def _drop_slot_orphan_sentences(structured: dict | None, vreport=None) -> dict:
    """Remove every sentence a RECORDED VERIFIER STRIP left ending on an EMPTY VALUE SLOT. Returns
    `{sentences_dropped}`; mutates in place; never raises.

    BOTH conditions are required (H1 FIX W1): the cut position must carry a strip seam minted by a
    SLOT-EMPTYING producer (`verify`, `ev_prune` -- X2's tag test) AND what remains of the sentence must
    end on a value-slot cue. With no such seam recorded -- a turn nothing was emptied on, or a caller that
    passed no report -- this pass deletes NOTHING, which is the whole of finding NF-1's remedy. Each seam
    licenses at most ONE cut (X3a), and the join is by text rather than by position (X3b): read the notes
    above this function before widening either."""
    census = {"sentences_dropped": 0}
    if not isinstance(structured, dict):
        return census
    seams = _report_seams(vreport)          # SNAPSHOT (a copy): never licensed by this pass's own seams
    if not seams:
        return census
    try:
        for field in ("tldr", "mechanism"):
            text = structured.get(field)
            if not isinstance(text, str) or not text.strip():
                continue
            cuts: list[tuple[int, int]] = []
            pos = 0
            while pos < len(text):
                s0, s1 = _handle_sentence_span(text, pos)
                if s1 <= pos:                          # never spin on a degenerate span
                    pos += 1
                    continue
                core = text[s0:s1].rstrip()
                while core and core[-1] in ".!?;:,":    # the terminator is not part of the slot test
                    core = core[:-1].rstrip()
                # THE CUT POSITION IS WHERE THE FIGURE WAS: the end of what survives, before the
                # terminator. That is exactly where a slot-emptying producer recorded its seam if it
                # emptied this slot. The join is by TEXT and is not positionally exact (FIX X3b); each
                # seam licenses at most one cut (FIX X3a), which is what bounds the collision case.
                if (core and _HANDLE_VALUE_SLOT_RX.search(core + " ")
                        and _slot_orphan_licensed(seams, field, text[s0 + len(core):])):
                    e = s1
                    if s0 == 0:                        # the leading-indent rule (verify._drop_span)
                        while e < len(text) and text[e] == " ":
                            e += 1
                    cuts.append((s0, e))
                    census["sentences_dropped"] += 1
                pos = s1
            if not cuts:
                continue
            out, p = [], 0
            for a, b in cuts:
                a = max(a, p)
                out.append(text[p:a])
                # A WHOLE-SENTENCE producer: the seam is TIDY-2's repair record, never a licence (X2),
                # and it keeps the empty-key skip (X6) because an empty key cannot join to an orphan line.
                _mint_strip_seam(vreport, field, text[b:], src=_SEAM_SRC_SLOT_ORPHAN)
                p = max(p, b)
            out.append(text[p:])
            new = "".join(out)
            if not text[:1].isspace():
                new = new.lstrip(" \t")
            structured[field] = new
    except Exception:  # noqa: BLE001 -- a render guard must never be the thing that breaks an answer
        return census
    return census


# ══ T1-6 (CASCADE_HOME_AND_SMALL_ITEMS) -- THE e-CITED LINT'S RANGE GAP, CLOSED CONSERVATIVELY ═══════
#
# THE RESIDUAL, INHERITED BY NAME. D-HP closed with (R4): "the e-cited lint under-extracts range-shaped
# typed figures ('2-4 quarter') -- an existing-lint gap, not a new axis", MOVED to the estate small-items
# bundle. THE MEASURED CASE is verdicts #35/#36 of `data/dhp_g1/clause6_audit.json`
# (`ab_rec_malaysia_stocks`, cov4.r2), and it is one of the SIX genuine writer-side mis-bindings the audit
# decomposition kept after every exoneration:
#     "any confirmed onset would add a 2-4 quarter supply lag [E23]"
# `[E23]` is `usda_gain_soybean_meal` (country TH) and its stored text forecasts a slight increase in Thai
# palm kernel IMPORTS. It states no lag, no quarter count and neither endpoint. The sentence nevertheless
# passed every gate, because `verify.bare_digit_verdict`'s R3(b) exemption is SENTENCE-SCOPED and
# DELIBERATELY GENEROUS: it asks only whether an [E] handle is present, never whether that item carries
# the numeral. The prompt half already states the narrow contract the exemption is supposed to encode --
# `_SYSTEM_HANDLES`: "a figure that appears in the QUOTED TEXT of an evidence item ... may be typed, IN
# THE SAME SENTENCE AS THAT ITEM'S [E] HANDLE" -- so what ships below is the lint finally reading the rule
# the writer was already given, on ONE shape and no other.
#
# WHY THE SHAPE IS "ONE RANGE", AND WHY THAT IS NOT AN ARBITRARY NARROWING. A range is the one typed-figure
# shape that is UNAMBIGUOUSLY a magnitude and CHEAPLY checkable: two endpoints, both of which must appear in
# the receipt for the receipt to be stating the range at all. Every other typed figure needs the span
# machinery D-HP's option (a) ([Q] handles) was deferred for, and the estate's own record (Z4/W1: a cue-only
# lexical rule deleted 314 of 32,557 stored sentences) forbids inventing a wider criterion from a handful of
# examples. So the exemption stands EXACTLY as shipped for every sentence that carries no parseable range.
#
# FAIL-OPEN AT EVERY DOUBT, AND THE DIRECTION IS THE WHOLE SAFETY OF IT. Not a range, an unparseable
# endpoint, a year range, a date fragment, a descending pair, a receipt whose text is unavailable, ANY
# cited member of the record that could not be read (so the union is complete or the sentence is exempt),
# an endpoint the writer ROUNDED or TRUNCATED to its own stated precision, ANY exception -- all read as
# EXEMPT. A missed conviction costs a count; a false one deletes correct prose, which is D3 and the reason
# the exemption was written generous in the first place. The last two entries are review fixes: each was a
# reproduced FALSE CONVICTION on a stored r6 body, which is this lint's one unacceptable outcome.
#
# IT MINTS NO NEW LEDGER CLASS. The sentence was already a claim-magnitude sentence; what it loses is the
# exemption, so it is charged and removed as `bare_digit` through the ladder that already exists. A new
# class would have to join `emf.G1_DECLARED_CLASSES` (clause (4) is a class scan) and would double-count
# a conviction the ledger already has a name for.
#
# THE CHARGE/REMEDY SPLIT, STATED HONESTLY. `verify.bare_digit_verdict` is the CHARGE and it is FROZEN
# (the D-HP termination branch freezes the cycle-8 extractor exactly as shipped, and this bundle carries a
# standing verify.py freeze). So verify still COUNTS such a sentence under `bare_digit.e_cited` while this
# pass REMOVES it. That divergence is inside the population difference `_drop_bare_digit_sentences`' own
# docstring already declares ("Where they CAN differ is population"), and the render census reports what
# the reader's page actually lost -- which is what a render census has always promised. Moving the charge
# to match is a verify-window change, recorded, not taken here.
_RANGE_DASHES = "-" + chr(0x2010) + chr(0x2011) + chr(0x2012) + chr(0x2013) + chr(0x2014)
_RANGE_FIG_RX = re.compile(
    r"(?<![A-Za-z0-9.,])(\d[\d,]*(?:\.\d+)?)[ ]?[" + _RANGE_DASHES + r"][ ]?(\d[\d,]*(?:\.\d+)?)(?![\d.,])")
_YEARISH_RX = re.compile(r"\A(?:19|20)\d{2}\Z")


def _range_num(tok: str):
    """One endpoint as a float, or None when it is not cleanly parseable. `None` propagates all the way
    out as EXEMPT -- the fail-open direction this whole pass is built in."""
    try:
        return float(str(tok).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _range_figures(sent: str) -> list[tuple[str, str, str]]:
    """The RANGE-shaped typed figures in one sentence, as `(verbatim, low_token, high_token)`.

    `sent` must already have its handle tokens MASKED (`verify._mask_handles`, which is length-preserving),
    or a ranged handle like `[E1-E4]` would read as the range `1-4`.

    EVERY EXCLUSION IS A FAIL-OPEN, and each is here because it is a shape that LOOKS like a range and is
    not one:
      * a YEAR on either side ('2024-25', '2010-2020', and the leading pair of an ISO date '2026-05-30')
        -- `verify._claim_number_spans` already exempts bare years and year-range tails, and this pass may
        not be stricter than the extractor whose exemptions the writer was promised;
      * a descending pair ('9-4') -- not a range, and reading it as one would invent a claim;
      * an unparseable endpoint -- nothing to check against anything;
      * a match glued to another dash-digit run on either side (a chain, i.e. a date or a phone-shaped
        code, never a magnitude span).
    """
    out: list[tuple[str, str, str]] = []
    s = sent or ""
    try:
        for m in _RANGE_FIG_RX.finditer(s):
            lo_t, hi_t = m.group(1), m.group(2)
            if _YEARISH_RX.match(lo_t.replace(",", "")) or _YEARISH_RX.match(hi_t.replace(",", "")):
                continue
            lo, hi = _range_num(lo_t), _range_num(hi_t)
            if lo is None or hi is None or lo > hi:
                continue
            if m.start() > 0 and s[m.start() - 1] in _RANGE_DASHES:
                continue                                   # the tail of a longer dash chain
            tail = s[m.end():m.end() + 2]
            if tail[:1] in _RANGE_DASHES and tail[1:2].isdigit():
                continue                                   # the head of a longer dash chain
            out.append((m.group(0), lo_t, hi_t))
    except Exception:  # noqa: BLE001 -- a lint helper may never be the thing that breaks an answer
        return []
    return out


def _e_receipt_texts(sent: str, uniq: list | None) -> tuple[list[str], bool]:
    """The FULL stored text of every `[E]` receipt this sentence cites, in citation order -- AND whether
    that pool is COMPLETE, i.e. whether every member the sentence names actually contributed text.

    Reads the SAME index-range rule the rest of the [E] lane uses (`1 <= i <= len(uniq)`), and the same
    `_e_handle_members` grammar, so a grouped `[E1, E2]` and a ranged `[E1-E4]` both contribute every
    member they name. An out-of-range member contributes nothing (there is no receipt to read); a receipt
    with no text contributes nothing, which is what makes an unhydrated fixture EXEMPT rather than
    convicted.

    WHY THIS RETURNS A PAIR (REVIEW FIX). "Contributes nothing" was silent, and `_range_backed` then asked
    whether the POOLED record states the range -- a union reading that is only sound when the union IS the
    record the sentence cited. As shipped, a sentence citing `[E2][E3][E5][E25][E8]` with only ONE of the
    five hydrated was convicted on that one receipt's figures, i.e. against a record it was KNOWN could not
    be read in full. The all-missing case was already exempt (`if not texts`); the PARTIALLY-missing case
    is the same doubt in a smaller dose and now reads the same way. Reported here rather than inferred by
    the caller because only this scan knows which members were named."""
    items = list(uniq or [])
    out: list[str] = []
    complete = True
    try:
        for m in _E_HANDLE_RX.finditer(sent or ""):
            for i in _e_handle_members(m.group(0)):
                t = ""
                if 1 <= i <= len(items):
                    t = str((items[i - 1] or {}).get("text") or "").strip()
                if t:
                    out.append(t)
                else:
                    complete = False                        # a member of the cited record we cannot read
    except Exception:  # noqa: BLE001
        return [], False
    return out, complete


def _tok_places(tok: str) -> int:
    """The DECIMAL PLACES a written endpoint carries -- the precision the sentence itself chose to speak
    in. '42' -> 0, '2.5' -> 1, '1,250' -> 0."""
    t = str(tok).replace(",", "")
    return len(t.split(".", 1)[1]) if "." in t else 0


def _endpoint_backed(tok: str, val: float, pool: list[float]) -> bool:
    """Is ONE written endpoint recoverable from the pooled receipt figures?

    EXACT FIRST, THEN THE WRITER'S OWN PRECISION (REVIEW FIX). The shipped test was exact float equality,
    which convicts a FAITHFUL RESTATEMENT: `[E17]` states "the AD rates ... range from 42.2 to 53.7
    percent" and the body writes "42-54% antidumping duty ... [E17]" -- the same range, rounded to the
    precision prose speaks in -- and the lint deleted the sentence for it. That is exactly the D3 failure
    this module's own header forbids ("a missed conviction costs a count; a false one deletes correct
    prose"), and rounding is not an exotic shape: a writer asked for prose rounds.

    SO A POOL VALUE BACKS A TOKEN WHEN IT AGREES AT THE TOKEN'S OWN PRECISION -- rounded (half-up) OR
    truncated toward zero, because both are ordinary restatement habits and the fail-open direction takes
    the union of the two rather than guessing which one the writer used.

    THE TOLERANCE IS THE TOKEN'S, NEVER A FIXED EPSILON, and that is what keeps this from softening into
    "any nearby number": '42' admits [41.5, 43), while '42.2' admits only [42.15, 42.3) and '42.20' only
    [42.195, 42.21). A sentence that speaks precisely is still held to the precision it claimed."""
    if any(abs(v - val) < 1e-9 for v in pool):
        return True
    q = 10.0 ** _tok_places(tok)
    for v in pool:
        if v < 0:                                           # the range grammar mints no signed endpoint
            continue
        if abs(math.floor(v * q + 0.5) / q - val) < 1e-9:   # rounded at the token's stated precision
            return True
        if abs(math.floor(v * q) / q - val) < 1e-9:         # ...or truncated at it
            return True
    return False


def _range_backed(verbatim: str, lo_tok: str, hi_tok: str, texts: list[str]) -> bool:
    """Does ANY cited receipt state this range?

    TWO GENEROUS TESTS, EITHER OF WHICH EXONERATES: some cited receipt contains the range VERBATIM under
    any dash spelling, or BOTH endpoint VALUES are recoverable (`_endpoint_backed`: exactly, or at the
    written token's own precision) from the digit runs of the POOLED text of the receipts this sentence
    cites.

    THE UNION IS ONLY SOUND ON A COMPLETE RECORD, AND THE CALLER GUARANTEES THAT BEFORE CALLING HERE
    (REVIEW FIX). `_e_cited_unbacked_ranges` refuses to call this at all unless every cited member
    contributed its text (`_e_receipt_texts` returns that flag), because a union missing a member is a
    record with a hole in it, not a record. The vegoils sentence below is the shape that makes it concrete:
    its exoneration IS the four receipts that carry the endpoints, one each, so if any one of them is out
    of range or textless the pool cannot answer the question asked of it -- and the sentence must be exempt
    one step EARLIER rather than convicted on whichever members happened to hydrate.

    THE POOL IS THE UNION, NOT PER-RECEIPT, AND THAT WIDENING IS MEASURED RATHER THAN ASSUMED. The r6
    replay produced exactly one conviction that a per-receipt reading created and a union reading does
    not: `ab_cmp_vegoils` writes "soyoil has traded roughly 12-29% above palm across documented episodes
    [E2][E3][E5][E25]", and those four receipts state 12, 20, 25/14 and 29 percent respectively -- both
    endpoints ARE in the record the sentence cites, one per receipt, which is what a span across
    "documented episodes" means. Convicting it would be this lint ruling on COMPOSITION, which is a
    different question (the derivation grammar, deliberately size zero) asked by a different instrument.
    The pool is the fail-open reading and it is the one that ships.

    THE ENDPOINT SWEEP READS `verify._numbers_in` -- the RAW sweep, not the claim extractor -- also
    deliberately: on the RECEIPT side a year, a code digit or a date component is a perfectly good source
    for an endpoint, and the only question being asked is whether the reader can get the figure back out
    of the record.

    BOTH endpoints, never one: a record stating '2' and nothing else does not state '2 to 4'."""
    try:
        lo, hi = _range_num(lo_tok), _range_num(hi_tok)
        if lo is None or hi is None:
            return True                                     # unparseable -> exempt, never convicted
        from leviathan.graphrag import verify as _vf
        norm = re.sub(r"[" + _RANGE_DASHES + r"]", "-", verbatim or "")
        pool: list[float] = []
        for t in texts:
            if norm and norm in re.sub(r"[" + _RANGE_DASHES + r"]", "-", t):
                return True
            pool.extend(_vf._numbers_in(t))
        if _endpoint_backed(lo_tok, lo, pool) and _endpoint_backed(hi_tok, hi, pool):
            return True
    except Exception:  # noqa: BLE001
        return True                                         # any doubt -> backed -> exempt
    return False


def _e_cited_unbacked_ranges(sent: str, uniq: list | None) -> list[str]:
    """The range figures in an `[E]`-CITED sentence that NO cited receipt states -- verbatim, in order.

    `[]` (i.e. the R3(b) exemption stands, untouched) whenever: no `uniq` was threaded, the sentence cites
    no resolvable receipt, no receipt carries text, ANY cited member failed to contribute text (the record
    is incomplete -- see below), the sentence carries no parseable range, or every range it carries is
    backed. That list of ways to return `[]` IS the conservatism: this function can only ever move a
    sentence that types a range its own receipts do not contain.

    THE COMPLETENESS GUARD IS A REVIEW FIX AND IT IS ALL-OR-NOTHING BY DESIGN. `_range_backed` pools the
    cited receipts and asks whether the union states the range; a union assembled from SOME of the cited
    members answers a question nobody asked. The shipped code only exempted when the pool was ENTIRELY
    empty, so a sentence citing five receipts with four unhydrated was convicted on the fifth. One
    unreadable member is one doubt, and every doubt in this pass reads as EXEMPT."""
    if not uniq:
        return []
    try:
        from leviathan.graphrag import verify as _vf
        figs = _range_figures(_vf._mask_handles(sent or ""))
        if not figs:
            return []
        texts, complete = _e_receipt_texts(sent, uniq)
        if not texts or not complete:
            return []
        return [v for v, lo, hi in figs if not _range_backed(v, lo, hi, texts)]
    except Exception:  # noqa: BLE001
        return []


def _drop_bare_digit_sentences(structured: dict | None, number_calls: list | None,
                               vreport=None, uniq: list | None = None) -> dict:
    """D-HP-12's REMEDY. The charge is `verify`'s (`by_rule['bare_digit']`, one ledger); this is the
    deletion. Returns `{sentences_dropped, clauses_severed, e_cited_kept}`; mutates in place; never raises.

    IT RUNS FIRST IN THE HANDLE STACK, BEFORE ANY VALUE SPLICE, AND THAT ORDER IS LOAD-BEARING.
    `_resolve_number_handles` WRITES row values into the prose. A digit-lint that ran after it would read
    the ENGINE's digits as the MODEL's and delete every sentence the renderer had just filled in -- the
    lint fining the estate for doing its job. Running first also means the sentences this removes never
    pay for a splice the reader will not receive.

    ONE PRODUCER WITH THE CHARGE: the verdict is `verify.bare_digit_verdict`, the same function verify
    called, so the count in `by_rule` and the deletions on the page cannot disagree about what a bare
    digit is or about the R3(b) [E]-cited exemption. Where they CAN differ is population -- verify may
    already have dropped a charged sentence for a citation rule -- and the census reports what the
    reader's page actually lost, which is what a render census has always promised.

    SEVER OR KILL, and the test is the shipped one (`_HANDLE_CLAUSE_OPEN_RX`): the clause is severed only
    when it opens on a real connective (so the sentence keeps a grammatical head) AND something OUTSIDE
    the cut still resolves. Otherwise the sentence goes whole -- "the sentence promised a figure it cannot
    produce", D-PQ HANDLE-1's own rule, and the register/verifier precedent for a whole-sentence drop.

    IT MINTS ITS OWN STRIP SEAMS (H1 FIX Z12): the charge lives in verify and mints none, so TIDY-2 could
    not repair a paragraph seam this remedy opened. `_mint_strip_seam` records the POSITION only -- no
    counter moves -- and only for the WHOLE-SENTENCE cuts, which are the only ones that can leave a
    headless successor."""
    from leviathan.graphrag import verify as _vf
    census = {"sentences_dropped": 0, "clauses_severed": 0, "e_cited_kept": 0}
    if not isinstance(structured, dict):
        return census
    calls = list(number_calls or [])
    try:
        for field in ("tldr", "mechanism"):
            text = structured.get(field)
            if not isinstance(text, str) or not text.strip():
                continue
            cuts: list[tuple[int, int]] = []
            seen_sents: set[tuple[int, int]] = set()
            for a, _b, _v in _vf._claim_number_spans(_vf._mask_handles(text)):
                s0, s1 = _handle_sentence_span(text, a)
                if (s0, s1) in seen_sents:
                    continue
                seen_sents.add((s0, s1))
                verdict = _vf.bare_digit_verdict(text[s0:s1])
                if verdict == "e_cited":
                    # T1-6: the R3(b) exemption is CONDITIONAL on one shape only -- a RANGE the cited
                    # receipts do not state. Everything else keeps the exemption byte for byte, and
                    # `uniq=None` (every pre-T1-6 caller) keeps it unconditionally.
                    _bad_ranges = _e_cited_unbacked_ranges(text[s0:s1], uniq)
                    if not _bad_ranges:
                        census["e_cited_kept"] += 1
                        continue
                    # CONDITIONAL KEY, never a null (the OFF-arm-clean rule): a turn with no such
                    # sentence carries the pre-T1-6 three-key census exactly.
                    census["e_cited_range_unbacked"] = census.get("e_cited_range_unbacked", 0) + 1
                elif verdict != "bare_digit":
                    continue
                c_a = _handle_clause_start(text, s0, a)
                # The clause ends at the NEXT connective, or -- when the offending numeral sits in the
                # sentence's LAST clause, which is the commonest shape -- just before the terminator, so
                # the sentence keeps its full stop. Refusing the trailing case forced a whole-sentence
                # kill on every "..., while stocks hit 4,250" and made the sever rule nearly unreachable.
                c_b = len(text[:s1].rstrip())
                while c_b > a and text[c_b - 1] in ".!?;,":
                    c_b -= 1
                for cm in _HANDLE_CLAUSE_OPEN_RX.finditer(text[a:s1]):
                    c_b = a + cm.start()
                    break
                if c_a > s0 and c_b > a and _sentence_has_resolved_handle(text, s0, s1, calls,
                                                                         skip=(c_a, c_b)):
                    if c_a and text[c_a - 1] == " ":
                        c_a -= 1
                    cuts.append((c_a, c_b))
                    census["clauses_severed"] += 1
                    continue
                e = s1
                if s0 == 0:                       # the leading-indent rule (verify._drop_span, restated)
                    while e < len(text) and text[e] == " ":
                        e += 1
                cuts.append((s0, e))
                census["sentences_dropped"] += 1
                # FIX Z12: the WHOLE-SENTENCE cuts are the ones that can leave a headless successor, so
                # they -- and only they -- mint the seam TIDY-2 joins on. A severed clause keeps its
                # sentence, so it opens no paragraph seam.
                # FIX X2: tagged `bare_digit`, and that tag is NOT in the slot-orphan licence set. This
                # pass deletes a WHOLE sentence -- nothing survives with an emptied slot -- so its seam is
                # evidence of a repairable paragraph seam and of nothing else. Before the tag existed, a
                # terminator-less neighbour could normalize to this key and be deleted off it.
                _mint_strip_seam(vreport, field, text[e:], src=_SEAM_SRC_BARE_DIGIT)
            if not cuts:
                continue
            merged: list[tuple[int, int]] = []
            for a, b in sorted(set(cuts)):
                if merged and a <= merged[-1][1]:
                    merged[-1] = (merged[-1][0], max(merged[-1][1], b))
                else:
                    merged.append((a, b))
            out, pos = [], 0
            for a, b in merged:
                a = max(a, pos)
                out.append(text[pos:a])
                pos = max(pos, b)
            out.append(text[pos:])
            new = "".join(out)
            if not text[:1].isspace():
                new = new.lstrip(" \t")
            structured[field] = new
    except Exception:  # noqa: BLE001 -- a render guard must never be the thing that breaks an answer
        return census
    return census


def _sentence_keeps_other_receipt(text: str, s0: int, s1: int, skips, n_uniq: int) -> bool:
    """True when the sentence `[s0, s1)` still carries a citation the reader KEEPS, outside `skips`.

    The [E]-lane twin of `_sentence_has_resolved_handle`, and separate from it for one reason: that
    function needs the turn's `number_calls` to ask whether an [N] member has a value, and this pass is
    not threaded them. It does not need to be. `_resolve_number_handles` runs BEFORE this pass on both
    bodies (the ordering is pinned at both call sites), and it removes every [N] token it could not
    resolve -- so any `[N...]` still standing here resolved, which is exactly the question being asked.
    An [E] token counts when any member is in range, the same index-range reading the pass itself uses.

    `skips` IS A LIST, NOT ONE SPAN, and that is the `_resolve_number_handles` rule restated: a token on
    its way OUT backs nothing, so counting it here would let one convicted escape rescue a neighbouring
    one from the kill it has earned (that pass's `backed` set excludes its own `grouped_in_slot` tokens
    for exactly this reason). Measured shape it fixes: "DDGS from corn was priced at [E1], and soymeal
    prices had reached their lowest average ... at [E45]." -- BOTH tokens are escapes, so the honest
    verdict is one dead sentence rather than two severed clauses meeting at ", ."."""
    sent = text[s0:s1]
    def _skipped(m) -> bool:
        return any(s0 + m.start() >= a and s0 + m.end() <= b for a, b in skips)
    for m in _N_HANDLE_HP_RX.finditer(sent):
        if not _skipped(m):
            return True
    for m in _E_HANDLE_RX.finditer(sent):
        if _skipped(m):
            continue
        if any(1 <= i <= n_uniq for i in _e_handle_members(m.group(0))):
            return True
    return False


def _resolve_evidence_handles(structured: dict | None, uniq: list | None, *,
                              handle_prose: bool = False) -> dict:
    """D-HP-10 -- the [E] RESOLUTION PASS, and the producer of the `prose_handles` trace column.

    THE GAP IT CLOSES, and nothing else in the tree closes it: `verify._check_evidence_handle` is a
    LEXICAL-OVERLAP test against the matched pool, so an [E] index pointing at the WRONG-BUT-REAL item
    passes today and is READER-INVISIBLE. There is no [E] equivalent of the [N] value-splice, so an
    unresolvable [E] standing where a receipt belongs simply survives. Under handle-only prose that is not
    a cosmetic gap: the handle IS the claim.

    SHAPE: the SAME four census keys as `number_handles` (the registry comment at
    `tracekeys.prose_handles` freezes it), so the two halves of the join read as one instrument -- AND
    THE SAME RULES INSIDE THEM (H1 FIX Z12): the whole-sentence kill leg charges `sentences_dropped`
    only, exactly as `_resolve_number_handles` does, so the same shape reads the same on both halves.
    `substituted` IS STRUCTURALLY 0 IN THIS BUILD AND IS NOT A BUG: the [E] splice payload would be a
    date / era label / series scope, and D-HP-7 puts all three on the NOT-IN-SCOPE list, sequenced after
    G1/G2 with the renderer-ownership table. The key exists so the column shape does not move when they
    land; a non-zero value is a later change, made deliberately.

    ALWAYS COUNTS, MUTATES ONLY UNDER `handle_prose` -- the `bare_digit_count` posture, and for the same
    reason: G1 reads control-vs-treatment on the SAME column, and a census that exists only on the
    treatment arm gives the comparison no denominator. With the flag off this function is a pure read and
    the prose is byte-identical.

    RESOLUTION IS POSITIONAL, MATCHING D-HP-1 (iii) AND `verify`'s OWN handle-prose branch: `[E{i}]` means
    `uniq[i-1]`, so an index in `1..len(uniq)` resolves and anything else does not. The removal ladder is
    the shipped one -- drop the handle when it stands beside prose, sever or kill when it stands where the
    receipt belongs. IT RUNS BEFORE `_prune_orphan_evidence_handles` (ordering pin (b)), which remains the
    last-resort backstop keyed on the FOOTER's emission decision: this pass answers "does the index name a
    row at all", that one answers "did the reader actually get the row"."""
    census = {"substituted": 0, "handles_dropped": 0, "sentences_dropped": 0, "unresolvable": 0}
    if not isinstance(structured, dict):
        return census
    n_uniq = len(uniq or [])
    try:
        for field in ("tldr", "mechanism"):
            text = structured.get(field)
            if not isinstance(text, str) or "[E" not in text:
                continue
            recs = []
            for m in _E_HANDLE_RX.finditer(text):
                members = _e_handle_members(m.group(0))
                live = [i for i in members if 1 <= i <= n_uniq]
                s0, s1 = _handle_sentence_span(text, m.start())
                standin = bool(_HANDLE_VALUE_SLOT_RX.search(text[s0:m.start()]))
                recs.append((m, members, live, s0, s1, standin))
                census["unresolvable"] += len(members) - len(live)
            if not handle_prose or not any(len(r[2]) != len(r[1]) for r in recs):
                continue
            backed = {(r[3], r[4]) for r in recs if r[2]}
            ops: list[tuple[int, int, str]] = []
            kills: list[tuple[int, int]] = []
            for m, members, live, s0, s1, standin in recs:
                if len(live) == len(members):
                    continue
                if live:                          # PARTIAL: narrow to the members that name a row
                    ops.append((m.start(), m.end(), _e_handle_token(live)))
                    census["handles_dropped"] += len(members) - len(live)
                    continue
                if standin and (s0, s1) not in backed:
                    # H1 FIX Z12: THE KILL LEG CHARGES `sentences_dropped` AND NOTHING ELSE, which is
                    # `_resolve_number_handles`' own accounting. This half used to charge
                    # `handles_dropped` here as well, so the two censuses the docstring calls "one
                    # instrument" disagreed on the identical shape (E kill -> handles_dropped 1, N kill
                    # -> 0). One census, one rule: a handle that left with its whole sentence is reported
                    # as the SENTENCE the reader lost, not twice.
                    e = s1
                    if s0 == 0:
                        while e < len(text) and text[e] == " ":
                            e += 1
                    if (s0, e) not in kills:
                        kills.append((s0, e))
                        census["sentences_dropped"] += 1
                    continue
                census["handles_dropped"] += len(members)
                a = m.start()
                if standin:                       # MIXED: sever the empty promise, keep the backed content
                    a = _handle_clause_start(text, s0, m.start())
                if a and text[a - 1] == " " and (m.end() >= len(text) or text[m.end()] in " ,.;:)!?"):
                    a -= 1
                ops.append((a, m.end(), ""))
            merged = sorted(ops + [(k0, k1, "") for k0, k1 in kills], key=lambda o: (o[0], o[1]))
            out, pos = [], 0
            for a, b, repl in merged:
                if b <= pos:
                    continue
                a = max(a, pos)
                out.append(text[pos:a])
                out.append(repl)
                pos = b
            out.append(text[pos:])
            new = "".join(out)
            if not text[:1].isspace():
                new = new.lstrip(" \t")
            structured[field] = new
    except Exception:  # noqa: BLE001 -- a render guard must never be the thing that breaks an answer
        return census
    return census


# ══ D-PQ HANDLE-3: the punctuation a removed handle leaves behind ═══════════════════════════════════
# A STRIP IS POSITIONAL, SO IT LEAVES THE FRAME AROUND IT STANDING. `verify._verify_field` removes handle
# spans and tidies only ` +([.,;])`; `_resolve_number_handles` eats one separating space. Neither knows
# about the BRACKET a handle was sitting inside, and the measured residue is exactly that shape:
#   "(both referenced qualitatively in the dated evidence [E1][E2][E3])" -> "... dated evidence )"
# 3 rows across the two dcw passes and the covenant deck shipped it (dcw_urea_zscore "GAIN item )",
# dcw_full_record_range, ab_cf_brl_deval). The dangling-dash form ("the record -- .") is the same failure
# on a different frame and is included for the same reason.
#
# CONSERVATIVE BY CONSTRUCTION, and each clause is a shape no writer produces on purpose:
#   * a parenthetical emptied to "()" goes entirely (with the space in front of it);
#   * whitespace INSIDE a bracket, on either side, closes up;
#   * a dash left standing in front of terminal punctuation goes;
#   * a space in front of ".,;:!?" closes up (verify does three of these; this is the same rule, complete).
# NEVER ACROSS A LINE and NEVER INSIDE A ``` FENCE: `[ \t]` not `\s`, and the fence walk is `_sectionize`'s
# own, so a mermaid block or a code sample in the mechanism is untouched by construction.
_DEBRIS_RULES = (
    (re.compile(r"[ \t]*\([ \t]*\)"), ""),               # an emptied parenthetical
    (re.compile(r"[ \t]*\[[ \t]*\]"), ""),
    (re.compile(r"([(\[])[ \t]+"), r"\1"),               # "( both" -- the opening half
    (re.compile(r"[ \t]+([)\]])"), r"\1"),               # "evidence )" -- THE measured shape
    (re.compile(r"[ \t]+-{2,}[ \t]*(?=[.,;:!?])"), ""),  # "the record --."
    # CYCLE-9 REVIEW (2026-08-08), MEDIUM 6 -- the two residues the [E] prune leaves that no rule above
    # closes. Both are measured: "Costs fell [E1], [E2]." -> "Costs fell,." (a comma-period ON THE PAGE),
    # and "A dash -- [E1] -- closes it." -> "A dash -- -- closes it." A separator whose two sides are gone
    # is debris in exactly the sense this table means, and neither pattern can fire on prose that still
    # has its content: a comma directly against a terminator, and a dash run directly against another.
    (re.compile(r"[ \t]*,(?=[ \t]*[.;:!?])"), ""),       # "fell,." -- the emptied list separator
    (re.compile(r"(-{2,})(?:[ \t]+-{2,})+"), r"\1"),     # "-- --" -- the emptied em-dash aside
    (re.compile(r"[ \t]+([.,;:!?])"), r"\1"),
)


def _dedup_number_handles(structured: dict | None, number_calls: list | None) -> int:
    """CYCLE-6 FIX-C, THE PROSE HALF. Re-point every [N] marker whose footer row is a FULL-IDENTITY clone of
    an earlier index's onto that survivor, so the clone leaves the prose and -- by cycle-4's prose-authority
    rule -- its duplicate footer line goes with it. Returns the number of INDICES re-pointed (0 on every
    turn with no clone, which is the overwhelming majority). Mutates in place; never raises.

    MEASURED (gate-3 dpq_probe, BOTH passes): p1 rendered [N10] and [N12], p2 [N9] and [N10], each pair the
    identical `FUTURES EOD settle CBOT corn delivery 2026-12 = 446 US cents/bushel (exchange settlement,
    USD)  [known 2026-06-05]` -- two separate lookups that returned the same row, footed twice.

    WHY THE RE-POINT LIVES ON THE PROSE SIDE AND RUNS *BEFORE* THE BODY RENDER. `_cited_sources_block`
    receives the structured dict and returns a STRING, and the assembled body is
    `render(structured) + _cited_sources_block(structured, ...)` -- left-to-right, so a rewrite performed
    inside the footer builder would reach the footer and never the body, and the reader would be left with
    a `[N12]` in the prose pointing at a row that is no longer there. That is the dangling-marker defect
    D-PQ HANDLE-4 exists to abolish; re-writing the prose first is the only ordering in which body and
    footer cannot disagree.

    THE RE-POINT IS SAFE BY CONSTRUCTION BECAUSE THE DROP DEMANDS FULL IDENTITY: the survivor's row is the
    clone's row rendered byte for byte (`_number_row_clones` keys on the whole line), so whatever the model
    meant by the clone index, the survivor says exactly the same thing. Grouped tokens are rewritten member
    by member and re-emitted canonically; a group that collapses to one member ('[N10, N12]' -> '[N10]')
    and an adjacent repeat the collapse creates ('[N10] [N10]') both fold, because a doubled marker is
    debris the reader would read as two receipts."""
    if not isinstance(structured, dict):
        return 0
    prose = f"{structured.get('tldr') or ''}\n{structured.get('mechanism') or ''}"
    prose_n: list[int] = []
    for _m in _N_HANDLE_RX.finditer(prose):
        for _i in _n_handle_members(_m.group(0)):
            if _i not in prose_n:
                prose_n.append(_i)
    clones = _number_row_clones(prose_n, number_calls)
    if not clones:
        return 0

    def _rewrite(m) -> str:
        got = _n_handle_members(m.group(0))
        if not any(i in clones for i in got):
            return m.group(0)                      # untouched tokens keep their EXACT bytes (no re-canon)
        members: list[int] = []
        for i in got:
            j = clones.get(i, i)
            if j not in members:
                members.append(j)
        return _n_handle_token(members)
    for field in ("tldr", "mechanism"):
        text = structured.get(field)
        if not isinstance(text, str) or not text:
            continue
        new = _N_HANDLE_RX.sub(_rewrite, text)
        # the collapse's own debris: '[N10] [N10]' / '[N10][N10]' are ONE receipt written twice
        new = re.sub(r"(\[N\d+(?:,\s*N\d+)*\])(?:\s*\1)+", r"\1", new)
        if new != text:
            structured[field] = new
    return len(clones)


def _tidy_handle_debris(structured: dict | None) -> int:
    """Close up the punctuation frames a stripped/removed handle left empty. Returns the number of PROSE
    FIELDS it changed (0 on a clean draft, which is every turn with no strips). Mutates in place; never
    raises -- a cosmetic pass must never be the thing that breaks an answer.

    THE FIELD SET IS `render`'s PROSE SET, and that is the whole of it: `render` emits `tldr`, `mechanism`,
    the mermaid block (a diagram, not prose, and fenced out below anyway) and the `sources` ledger (whose
    notes are provenance metadata, never argument). The scaffold's sections live INSIDE `mechanism`, so
    they are covered by covering `mechanism` -- there is no third prose field to reach."""
    changed = 0
    if not isinstance(structured, dict):
        return changed
    for field in ("tldr", "mechanism"):
        text = structured.get(field)
        if not isinstance(text, str) or not text:
            continue
        out, in_fence = [], False
        for line in text.split("\n"):
            if line.lstrip().startswith("```"):
                in_fence = not in_fence
                out.append(line)
                continue
            if in_fence:
                out.append(line)
                continue
            for rx, repl in _DEBRIS_RULES:
                line = rx.sub(repl, line)
            out.append(line)
        new = "\n".join(out)
        if new != text:
            structured[field] = new
            changed += 1
    return changed


# ══ CYCLE-5 (2026-08-07) TIDY-2: the SENTENCE a strip left standing without its antecedent ════════════
#
# THE MEASURED SHAPE (gate-2, BOTH passes, the same two rows). `verify._verify_field` drops a whole
# sentence by POSITION. When that sentence opened a paragraph that is not the first in its field, the
# paragraph is left beginning on the space that used to separate the two sentences -- and the sentence now
# standing first refers backwards to something the reader cannot see:
#     "  That sits in El Nino territory, not La Nina. The model assigns El Nino ..."
#     "  if the ONI crosses into strong El Nino territory (above ~1.5 degC), the drought mechanism ..."
#     "  within recent range (five-year low 9.48 [N8], five-year high 17.91 [N9])."
# The first is a demonstrative with no antecedent; the other two are literal mid-sentence continuations
# whose bullet head and subject went with the strip.
#
# WHY IT LIVES HERE AND NOT IN verify.py. The strip DECISION is right in every one of these cases -- the
# figure was unbacked or mismatched and had to go. What is wrong is the SPLICE, which is a rendering
# concern; verify's rule semantics are frozen and this pass must never be able to change what counts as a
# strip. It sits beside `_tidy_handle_debris`, runs under the same verifier gate, and reports only how
# many prose FIELDS it touched.
#
# CONSERVATIVE BY CONSTRUCTION -- FOUR INDEPENDENT CONDITIONS, ALL REQUIRED:
#   1. LINE-LEADING WHITESPACE, 1-3 spaces. A markdown paragraph never opens on a space; 4+ spaces is an
#      indented code block and a nested list marker ("  - ", "  * ", "  1. ") is a list, so both are
#      excluded outright.
#   2. AN ORPHAN OPENER: the line's first word is lower-case, or it is one of a CLOSED list of anaphors
#      and connectives that can only point backwards. A definite-article subject ("The model tags ...")
#      is NOT in that list -- see the deliberate non-removal note below.
#   3. STRIP ADJACENCY: `verify`'s report must carry a seam whose successor text IS this fragment
#      (normalized prefix equality). Without this, the pass is a prose editor; with it, it can only ever
#      repair a cut this run made. This is the condition cycle-3's reviewer's over-removal lacked.
#   4. SENTENCE-SCOPED REMOVAL: only the ORPHANED FIRST SENTENCE goes, and the boundary walk is
#      `_handle_sentence_span` -- the same abbreviation-aware walk cycle-3 had to build after the naive
#      splitter cut "U.S." in half. The rest of the paragraph is verified, backed content and stays.
#
# DELIBERATELY NOT REMOVED (and this is a recorded deviation from the fix brief, not an oversight): a
# headless paragraph whose surviving first sentence is ordinary forward-referring prose -- gate-2's
# " The model tags El Nino (positive ONI) as price-pressuring at medium confidence -- ...". It lost its
# bold lead-in to a correct strip, but the sentence itself is complete, grounded and cited. Deleting it
# would destroy verified content because a NEIGHBOUR was convicted, which is exactly the over-removal
# class cycle-3's reviewer caught. The seam is repaired (the leading space goes) and the prose stays.
_ORPHAN_ANAPHORS = frozenset((
    "that", "this", "these", "those", "it", "its", "they", "them", "their", "he", "she", "his", "her",
    "such", "but", "and", "so", "yet", "however", "meanwhile", "therefore", "thus", "then", "also",
    "which", "whereas", "while", "either", "neither", "both", "instead", "moreover", "furthermore",
    "nonetheless", "nevertheless", "conversely", "likewise", "hence", "because",
))
# 1-3 leading spaces, then something that is NOT a list marker and NOT more whitespace. The bullet glyph
# is a CODEPOINT escape (U+2022), the ASCII-source discipline `_N_DASHES` states above.
_ORPHAN_BULLETS = "-*+" + chr(0x2022)
_ORPHAN_LINE_RX = re.compile(r"\A[ ]{1,3}(?![" + _ORPHAN_BULLETS + r"]\s|\d+[.)]\s|#|>|\s)"
                             r"(?P<body>\S.*)\Z")
_ORPHAN_FIRST_WORD_RX = re.compile(r"[A-Za-z][A-Za-z'" + chr(0x2019) + r"]*")   # ...and the curly one

# ══ FIX-CYCLE-2 (2026-08-07): TWO MEASURED OVER-REMOVALS, both closed by REFUSALS, never by new deletions ═
#
# (5) A HEADLESS SENTENCE IS NOT AN UNBACKED SENTENCE. The anaphor list above made deletion unconditional
#     on the opener, and the measured casualty was
#         " it fell to 1.32 billion bushels [N3], the tightest carryout since 2013."
#     -- complete, cited, and LEFT STANDING by the verifier (its figure was checked and passed). Its only
#     offence was a lower-case pronoun. Deleting it is the cycle-3 over-removal class in a new costume:
#     verified content destroyed because a NEIGHBOUR was convicted. THE REPAIR IS THE SAME EITHER WAY (the
#     leading space goes); what differs is whether the words survive, and they must. A fragment is now
#     deletable ONLY when it is GENUINELY CONTENTLESS -- no citation handle the reader could follow, and no
#     claim numeral (`verify._claim_numbers_in`, the estate's one extractor for "is this a stated figure",
#     so its year/date/list-marker exemptions come along and a bare "since 2013" does not count as content).
#     This deliberately RETIRES one of the four gate-2 fragments the builder listed
#     (" within recent range (five-year low 9.48 ...)" carries a claim numeral): a repaired seam on a
#     figure-bearing line is the correct outcome, and the pin was rewritten to say so.
#
# (6) A LAZY LIST CONTINUATION IS NOT AN ORPHAN. `_ORPHAN_LINE_RX` excludes a line that IS a list marker
#     and says nothing about a line that CONTINUES one -- markdown's lazy continuation, where a wrapped
#     bullet is indented one to three spaces and opens lower-case, is byte-identical to the orphan shape.
#     Measured: "- The balance sheet tightened materially:" followed by an indented continuation lost the
#     continuation and left the bullet ending on a colon with nothing after it. A candidate whose PRECEDING
#     NON-BLANK line is a list item, or ends in a colon, is now skipped outright -- the same structural
#     fence the fenced-code and nested-list exclusions already are.
_LIST_ITEM_RX = re.compile(r"\A\s*(?:[" + _ORPHAN_BULLETS + r"]|\d+[.)])\s")


def _orphan_has_content(frag: str) -> bool:
    """True when `frag` carries something a reader would LOSE: a citation handle, or a claim numeral. Fails
    SAFE -- any doubt (an unavailable extractor, an unparseable fragment) reads as CONTENT PRESENT, so the
    pass keeps the prose and repairs only the seam."""
    try:
        from leviathan.graphrag import verify as _vf   # module-local import: answer<->verify is lazy here
        if _vf._HANDLE.search(frag or ""):
            return True
        return bool(_vf._claim_numbers_in(frag or ""))
    except Exception:  # noqa: BLE001
        return True


def _seam_key(s: str) -> str:
    """Whitespace-collapsed, case-folded comparison form. The seam recorded by `verify` is pre-humanize and
    pre-sanitize text; the fragment on the page has been through both, so the join is on a NORMALIZED
    prefix rather than on positions (which no downstream pass preserves).

    IT IS NOT LENGTH-BOUNDED, AND SINCE ROUND 5 THAT IS TRUE OF `verify._seam_key` TOO -- the two are the
    same normalization, deliberately. Callers bound the INPUT at `verify._SEAM_LOOKAHEAD`; the 40-character
    `verify._SEAM_KEY_CHARS` class belongs to the browser-visible PROJECTION and is applied there, by
    `verify._projected_seam`. Cutting here would put the bound inside the LICENCE path, where
    `_licence_canon` deletes characters before the 32-character compare -- the false NEGATIVE round 5
    closed (W-B). Bound the projection, not the key."""
    return re.sub(r"\s+", " ", s or "").strip().lower()


def _report_seams(vreport) -> list:
    """The strip seams for this turn. FIX-CYCLE-2 (review major 7): `verify` no longer ships the seam's raw
    successor prose on the report dict -- that reached the browser through `trace['citation_verifier']`. The
    seams ride an INTERNAL attribute on the report object (invisible to every serializer, and carrying the
    key at the full `verify._SEAM_LOOKAHEAD` width the licence compare needs), and a COPY whose `key` is
    cut to `verify._SEAM_KEY_CHARS` (40) is additionally published under `strip_seams` only when
    GRAPHRAG_STRIP_AUDIT is on -- the cut is made at the PROJECTION site, not at the mint (round-5 W-A).
    Read the attribute first, fall back to the dict key so an audited run, a hand-built fixture and a
    legacy `{"after": ...}` record all still join. THE FALLBACK IS THE NARROWER RECORD AND CAN
    UNDER-LICENSE: 40 raw characters can carry fewer than 32 canonical ones once `_licence_canon`
    deletes (the W-B class), so on an audited record with no attribute a real cut can be refused --
    driven on W-B's own reproduction by the round-5 verifier. Unreachable in serving (the attribute and
    the projection are written together, and X3a consumes from this function's COPY, never the carrier);
    recorded at plan 10.12-R5 rather than fixed, because widening the fallback would republish the
    full-width prose the projection exists to cut.

    BOTH BRANCHES RETURN A COPY (H1 FIX X3a). `_slot_orphan_licensed` now CONSUMES the seam it matched, so
    the list it is handed must be this pass's own snapshot: the report's carrier -- attribute or audited
    dict key -- is never shortened by a reader."""
    got = getattr(vreport, "strip_seams", None)
    if got:
        return list(got)
    return list((vreport or {}).get("strip_seams") or [])


def _seam_adjacent(seams: list, field: str, frag: str) -> bool:
    """True when some recorded strip seam in THIS field is immediately followed by `frag`. The prefix
    compare is capped at 32 chars and floored at 8: shorter than 8 normalized characters is not evidence
    of anything, and beyond 32 a single sanitize edit inside the fragment would break an honest match.
    (`key` is verify's normalized form -- full width on the carrier, cut to 40 only in the audit
    projection; `after` is the legacy/fixture raw form. `_seam_key` is idempotent on the former, so one
    compare serves both, and the 32-char cap makes the two widths the same compare.)"""
    fk = _seam_key(frag)
    if len(fk) < 8:
        return False
    for s in (seams or []):
        if not isinstance(s, dict) or s.get("field") != field:
            continue
        sk = _seam_key(str(s.get("key") or s.get("after") or ""))
        n = min(len(sk), len(fk), 32)
        if n >= 8 and sk[:n] == fk[:n]:
            return True
    return False


def _tidy_strip_orphans(structured: dict | None, vreport: dict | None) -> int:
    """Repair the paragraph seams a whole-sentence strip left open. Returns the number of prose FIELDS
    changed (0 on every turn with no strips). Mutates in place; never raises -- a cosmetic pass must never
    be the thing that breaks an answer.

    STRIP COUNTS ARE NOT TOUCHED, by construction: this function reads `vreport` and writes only
    `structured`. It cannot create or destroy a strip, and the report it was handed is returned unchanged
    to whoever else reads it."""
    changed = 0
    seams = _report_seams(vreport)
    if not isinstance(structured, dict) or not seams:
        return changed
    for field in ("tldr", "mechanism"):
        text = structured.get(field)
        if not isinstance(text, str) or not text:
            continue
        out, in_fence, hit, dropped = [], False, False, False
        prev_nonblank = ""                                # (6): the markdown context the candidate sits in
        for line in text.split("\n"):
            if line.lstrip().startswith("```"):           # the `_tidy_handle_debris` fence walk, restated
                in_fence = not in_fence
                out.append(line)
                prev_nonblank = line
                continue
            m = None if in_fence else _ORPHAN_LINE_RX.match(line)
            # (6) LAZY LIST CONTINUATION: a wrapped bullet is indented and opens lower-case, which is the
            # orphan shape exactly. Structural context is the only discriminator, so a candidate whose
            # preceding non-blank line is a list item -- or ends on a colon, which is a lead-in either way
            # -- is skipped before any opener or seam test runs.
            _cont = bool(_LIST_ITEM_RX.match(prev_nonblank) or prev_nonblank.rstrip().endswith(":"))
            if m is None or _cont or not _seam_adjacent(seams, field, m.group("body")):
                out.append(line)
                if line.strip():
                    prev_nonblank = line
                continue
            body = m.group("body")
            w = _ORPHAN_FIRST_WORD_RX.match(body)
            first = (w.group(0).lower() if w else "")
            orphan = bool(w) and (w.group(0)[0].islower() or first in _ORPHAN_ANAPHORS)
            _s0, _s1 = _handle_sentence_span(body, 0)     # cycle-3's abbreviation-aware boundary walk
            # (5) the removal is fenced to a GENUINELY CONTENTLESS first sentence -- see the note above.
            if not orphan or _orphan_has_content(body[_s0:_s1]):
                out.append(body)                          # seam repaired, prose kept (see the note above)
                prev_nonblank = body
                hit = True
                continue
            rest = body[_s1:].lstrip()
            hit = True
            if rest:
                out.append(rest)                          # only the headless sentence goes
                prev_nonblank = rest
            else:
                dropped = True                            # the whole line WAS the fragment
        if not hit:
            continue
        new = "\n".join(out)
        if dropped:                                       # a removed line leaves its two blank neighbours
            new = re.sub(r"\n{3,}", "\n\n", new)          # adjacent; markdown wants one paragraph break
        if new != text:
            structured[field] = new
            changed += 1
    return changed


# ══ CYCLE-9 (2026-08-08) FIX 3 -- THE [E] ORPHAN PRUNE, THE MIRROR OF THE [N] ONE ═══════════════════
# D-PQ HANDLE-4 made the prose <-> `## Sources` join TOTAL in the [N] namespace and said, in terms,
# "nothing here reads or moves the [E]/positional half". Gate-6 measured what that half costs.
#
# THE MEASURED SHAPE (`dcw_urea_zscore`, BOTH dcw passes -- it is reproducible, not a sampling artifact):
# the prose carries [E1] and [E2] and the rendered `## Sources` block carries [N] rows ONLY. Every [E]
# marker on the page is dangling: a reader clicking it finds nothing, on exactly the rows where the
# evidence attribution was the thing that failed.
#
# TWO INDEPENDENT PRODUCERS, ONE REMEDY. A prose [E<n>] gets no footer row when
#   * its LEDGER ENTRY was stripped -- `verify` drops a fabricated_citation row from `structured['sources']`
#     and leaves `resolved[ref] = []`; or
#   * THE MODEL NEVER DECLARED IT. `verify`'s undeclared-handle path keeps a marker whose sentence is
#     supported by SOME provided item (`undeclared_unsupported` is charged only when nothing supports it),
#     but `_cited_sources_block` walks `d['sources']` and an undeclared handle is in no ledger at all.
# Neither producer is a defect on its own terms; the DANGLING MARKER is, and it is the same defect either
# way, so the fix reads the one authority both halves already answer to: does this ref get a row?
#
# THE PRUNE IS THE [N] RULE RESTATED, and every conservative property comes with it:
#   * a GROUPED token is narrowed to its surviving members ("[E2, E5]" -> "[E2]"), never dropped whole;
#   * a token with no surviving member is removed WITH its one separating space, the exact rule
#     `_resolve_number_handles`' bare-drop leg uses, so "documented [E1], and" leaves "documented, and";
#   * A SENTENCE IS NEVER KILLED. The [N] pass kills a sentence when the handle STANDS IN for the figure
#     ("stands at [N16]" promises a number it cannot produce). An [E] handle stands in for nothing -- it
#     is an attribution, and prose minus an attribution is still the model's own sentence. Dropping the
#     token is the whole remedy, and it is `verify`'s own remedy for a convicted [E] handle.
#   * `_tidy_handle_debris` runs immediately after and closes the frames these removals empty, so the
#     "(both referenced qualitatively [E1][E2][E3])" -> "( )" residue cannot reappear through this door.
# SCOPED TO THE EXPLICIT `[E` SPELLING, deliberately: a BARE `[3]` is the positional namespace whose
# duplicate-row decision is recorded and deliberately unfixed elsewhere, and widening to it would move
# that decision under cover of this one.
#
# == THE SECOND INSTRUMENT THIS MOVES, DECLARED UP FRONT -- CYCLE-9 REVIEW (2026-08-08), MEDIUM 7 ======
# `repaired` / `strip_rate` are not the only frozen cross-run numbers this cycle shifts. `eval._cited_
# evidence` joins by scanning the PROSE for `f"[{c['id']}]"`, and an evidence citation's id IS the `E`
# form (`citations.py:1020`, `id=f"E{i}"`). So every marker this prune removes also drops that citation
# out of `_cited_evidence`, and with it `min_episodes_cited`, `min_episode_sources`,
# `_cited_episode_clusters` and the source-tier pin -- the very pins the scaffold's ref-floor note is
# built around keeping delta-zero. THE MEASURED EXPOSURE IS THE DANGLING SET AND NOTHING ELSE: 10 refs on
# 5 rows across the six gate-6 runs, of 327 [E] refs in prose. It is the honest direction (a dangling
# marker was never a citation the reader could follow, so crediting it was always a false pass), but it
# is a DROP on those pins at the next gate and it must be read as this change, not discovered as noise.
_E_HANDLE_RX = re.compile(r"\[E\d+[a-z]?(?:\s*" + _N_SEP + r"\s*E?\d+[a-z]?)*\]")
_E_MEMBER_RX = re.compile(r"E?(\d+)[a-z]?")
_E_RANGE_RX = re.compile("\\AE(\\d+)[a-z]?\\s*[" + _N_DASHES + "]\\s*E?(\\d+)[a-z]?\\Z")
# CYCLE-9 REVIEW, BLOCKER 2: a ledger `ref` reduced to the integer the PROSE writes. Covers the E-form,
# the zero-padded form and the float spelling json round-trips produce; anything else keeps only its raw
# key, which is what the footer uses.
_E_REF_CANON_RX = re.compile(r"\A[Ee]?(\d+)(?:\.0+)?\Z")


def _e_handle_members(token: str) -> list[int]:
    """The 1-based evidence refs an `[E...]` token cites, in written order, de-duplicated. The [N] reader's
    rules exactly (`_n_handle_members`): a dash-joined PAIR is a range and expands, everything else is a
    member list, and a solitary `[E5]` returns `[5]`."""
    inner = token[1:-1].strip()
    rng = _E_RANGE_RX.match(inner)
    if rng:
        lo, hi = int(rng.group(1)), int(rng.group(2))
        if 0 < lo < hi <= lo + _N_RANGE_MAX:
            return list(range(lo, hi + 1))
    out: list[int] = []
    for x in _E_MEMBER_RX.findall(inner):
        i = int(x)
        if i not in out:
            out.append(i)
    return out


def _e_handle_token(members: list[int]) -> str:
    return "[" + ", ".join(f"E{i}" for i in members) + "]"


def _prune_orphan_evidence_handles(structured: dict | None, vreport: dict | None, *,
                                   market_register: str = reg.FENCED) -> int:
    """Remove every prose `[E]` marker the `## Sources` block cannot answer for. Returns the number of
    REFS removed from the page (0 on every turn whose join is already total). Mutates in place; never
    raises -- a render guard must never be the thing that breaks an answer.

    ══ CYCLE-10 (2026-08-08) FIX 3 -- THE AUTHORITY IS THE RENDERED FOOTER, NOT THE LEDGER ══════════════
    Cycle-9 computed the live set from `structured['sources']` x `vreport['resolved']` -- a faithful
    re-derivation of "which ledger rows RESOLVED", which is not the same question as "which rows the
    reader actually GETS". Gate-7 `ab_out_cotton` is the gap: strips 0, nothing convicted, every ref
    resolved, this prune returned 0 -- and the reader still received three [E] markers with no row,
    because the rows were emitted and then deleted downstream (see `_document_source_rows`). A prune
    keyed on an earlier stage cannot see that.
    The live set is now the EMISSION DECISION ITSELF (`_emitted_evidence_refs`, which is
    `_cited_sources_block`'s own row walk), so the two can never disagree about a ref again.
    ORDER, AND IT IS DELIBERATE: FIX 2 runs FIRST -- when the evidence exists the row is EMITTED and the
    marker is KEPT. This prune is the last-resort backstop for the genuinely rowless ref (a ledger entry
    verify convicted, or a marker the model never declared), never the primary remedy. Emission does not
    read the prose, so computing it before the prose is pruned is exactly equivalent to reading the
    assembled footer, and it costs no second render.

    == CYCLE-9 REVIEW (2026-08-08), BLOCKER 2 -- THE LIVE SET AND THE MEMBERSHIP PROBE ARE ONE NAMESPACE ==
    The first cut keyed `live` on the ledger's RAW `ref` STRING and probed it with `str(member)`, the
    PROSE's integer. Those are different namespaces the moment a ledger writes anything but a bare
    canonical decimal, and the paragraph above is exactly why they must not be: the footer keys on `ref`,
    the prose keys on the digit, and this function is the join. Measured end-to-end through the real
    `verify_citations`: a ledger row `{"ref": "E1", ...}` that verify RESOLVES, whose footer row
    `_cited_sources_block` DOES render, had its `[E1]` marker deleted from the reader's page -- FIX 3's own
    defect, inverted, minted by FIX 3. Reproduced for "E1", "[E1]", "e1", "01", "E01" and 1.0; only "1"
    survived. Every one of those spellings is a shape `verify` explicitly codes for (`.strip("[]")` plus
    the `ref.upper().startswith("N")` test) and the footer renders all of them.
    THE FIX IS TO HOLD BOTH KEYS. The raw `ref` goes in (that is the footer's key) AND, when the ref is an
    E-form / zero-padded / float spelling of an integer, its CANONICAL DIGIT does too (that is the prose's
    key). The set only ever grows, and growth is the safe direction here by construction: `live` is built
    from rows that are BOTH kept in `sources` AND present in `resolved`, so a wider set can only keep a
    marker whose footer row exists -- never mint one that does not."""
    removed = 0
    try:
        if not isinstance(structured, dict):
            return 0
        live = _emitted_evidence_refs(structured, vreport or {}, market_register=market_register)
        for field in ("tldr", "mechanism"):
            text = structured.get(field)
            if not isinstance(text, str) or "[E" not in text:
                continue
            ops: list[tuple[int, int, str]] = []
            for m in _E_HANDLE_RX.finditer(text):
                members = _e_handle_members(m.group(0))
                keep = [i for i in members if str(i) in live]
                if len(keep) == len(members):
                    continue
                removed += len(members) - len(keep)
                if keep:
                    ops.append((m.start(), m.end(), _e_handle_token(keep)))
                    continue
                a, b = m.start(), m.end()
                # THE ONE SEPARATING SPACE, `_resolve_number_handles`' rule -- and CYCLE-9 REVIEW MEDIUM 6:
                # when what FOLLOWS is punctuation that already closes the clause, the space to eat is the
                # one on the LEFT, or "Costs fell [E1], [E2]." leaves the comma-period the debris pass
                # cannot see. When the token opens the field there is no left space to take, so the
                # trailing one goes instead and the field is lstripped below (the `_resolve_number_handles`
                # leading-indent guard, restated -- a field must not start on a space because the token in
                # front of it was removed).
                if a and text[a - 1] == " " and (b >= len(text) or text[b] in " ,.;:)!?"):
                    a -= 1
                elif b < len(text) and text[b] == " ":
                    b += 1
                ops.append((a, b, ""))
            if not ops:
                continue
            out, pos = [], 0
            cuts_at: list[int] = []               # H1 FIX X1: each emptied slot's offset in the NEW text
            grown = 0
            for a, b, repl in ops:
                if a < pos:                       # a preceding removal already ate this left space
                    a = pos
                out.append(text[pos:a])
                out.append(repl)
                grown += (a - pos) + len(repl)
                # THE SAME PREDICATE `verify` USES AT ITS OWN MINT (`if v == ""`): a WHOLLY removed token
                # is the one that can leave the slot empty. A NARROWED group keeps a handle standing in
                # the slot, so it empties nothing and mints nothing.
                if repl == "":
                    cuts_at.append(grown)
                pos = b
            out.append(text[pos:])
            new = "".join(out)
            if not text[:1].isspace():
                _pre = len(new)
                new = new.lstrip(" \t")
                _shed = _pre - len(new)
                if _shed:
                    cuts_at = [max(0, c - _shed) for c in cuts_at]
            structured[field] = new
            # ══ H1 FOLD ROUND 3 (2026-08-13) -- FIX X1: THIS PRUNE IS A SLOT-EMPTYING PRODUCER ═════════
            # THE COVERAGE HOLE, REPRODUCED THROUGH THE SERVING BODY'S OWN PASS ORDER. W1 narrowed the
            # slot-orphan drop to positions carrying a recorded seam, and named `verify` as the only
            # producer that mints one. This function removes an [E] marker from a VALUE SLOT -- exactly
            # the gate-7 `ab_out_cotton` class it exists for, a resolved ref whose footer row the register
            # deleted -- and minted nothing, so "US corn ending stocks stood at [E1]." survived verify
            # intact, was pruned to "US corn ending stocks stood at." here, and the slot-orphan pass
            # REFUSED the cut for want of a licence. The fragment reached the reader, on the treatment arm
            # only, which is the whole of what Z4 was raised for.
            # THE REMEDY IS THE WIDENING RULE W1 ITSELF STATED: "if a render-side orphan is ever observed,
            # the licence widens by adding a seam mint at that producer." One mint, tagged `ev_prune`,
            # which is in `_SLOT_EMPTYING_SEAM_SRCS` because this deletion leaves the SENTENCE STANDING
            # with its slot empty -- the same state verify's positional strip leaves.
            # `allow_empty=True` is the X6 decision: a marker at the very end of a field ("...stood at
            # [E1]", no terminator) is a real position, and the field-final shape is the commonest one.
            for c in cuts_at:
                _mint_strip_seam(vreport, field, new[c:], src=_SEAM_SRC_EV_PRUNE, allow_empty=True)
    except Exception:  # noqa: BLE001 -- a render guard must never break an answer
        return removed
    return removed


# ══ CYCLE-10 (2026-08-08) FIX 2 -- WHY A RESOLVED SOURCE ROW NEVER REACHED THE READER ═══════════════════
# THE MEASURED SHAPE (gate-7 `ab_out_cotton`, BOTH covenant passes -- reproducible, not sampling). The
# prose cites [E1]..[E7] and the rendered footer carries rows 1, 2, 4 and 6 only; pass 2 has the same shape
# on a different ref set. Every other producer was ruled out from the run artifacts: `strips` = 0 and
# `by_rule` = {} (so verify convicted nothing and stripped no ledger row), `evidence_orphans_pruned` absent
# (so the cycle-9 [E] prune removed nothing), `episodes_scaffolded.fired` False (so no machine-composed
# section minted a marker), and the draft, the post-verify snapshot and the shipped body all carry the same
# seven [E] refs. The rows were EMITTED and then DELETED further downstream.
#
# THE DELETER IS `reg.sanitize`, AND IT IS DOING ITS JOB. The body render is
# `render(structured) + _cited_sources_block(...)` and the WHOLE string -- footer included -- then goes
# through `reg.sanitize(..., market_register=_mr)`. `ab_out_cotton` is an outlook turn, so `_mr` is
# `reg.OUTLOOK`, where `_strip_banned_sentences` DELETES any sentence carrying an unbacked level. A footer
# row's snippet is raw corpus prose that frequently quotes a price, a forecast level or a tonnage, and the
# row's own `[3]` marker is NOT a citation handle to that gate (`register._CIT_HANDLE` is `\[[EN]\d+\]`),
# so a WASDE quote naming a price reads as an unbacked level and the row is removed. Reproduced byte-exact
# against the shipped artifact:
#     in   "[3] USDA WASDE (2014-01-01): U.S. <price sentence>\n[4] World Bank ...: Cotton prices ..."
#     out  "[3] USDA WASDE (2014-01-01): U.S. [4] World Bank ...: Cotton prices ..."
# which is the adjudicator's "separator bug" -- not a short-snippet quirk at all. `_SENT_KEEP` splits on
# `([.!?;]\s+)`, so the dropped unit takes its delimiter WITH IT, and when that delimiter was the row's
# terminating "\n" the next row is pulled onto the same line. A row whose whole snippet is one banned
# sentence disappears outright, which is the row-skip.
#
# THE FIX IS AT THE EMISSION SITE, AND IT IS TWO PROPERTIES, NOT TWO PATCHES:
#   (a) THE ROW IS NOT ITS SNIPPET. `[ref] source (date)` is the attribution -- the thing a reader clicking
#       [E3] needs -- and it must survive whatever the register says about the quoted text. So the snippet
#       is put through the SAME register instrument HERE, alone, at row scope: whatever survives is
#       rendered, and when nothing survives the row is emitted without a snippet rather than not at all.
#       The body-wide pass that follows then has nothing left to delete, by construction.
#   (b) A ROW IS ONE LINE. The snippet's whitespace is collapsed first, so a corpus newline inside a
#       140-char snippet can never split one row across two lines either.
# The register gate is NOT relaxed anywhere: the same sentences are refused, and `register_leaks(body)`
# and the OUTLOOK `unbacked_levels` invariant are unaffected -- the text is removed either way. What
# changes is that its removal no longer takes the ROW, or the next row's line break, with it.
# THE STRUCTURAL BACKSTOP for the delimiter half lives in `register._strip_banned_sentences`, which now
# preserves the newlines of a dropped unit's delimiter; this site does not depend on it.
#
# ══ D-HP G1 REMEDIATION D2(b) (2026-08-14) -- CLAUSE (2b)'s REMEDY, AND IT RUNS *AFTER* THE PRUNE ═════
#
# THE DEFECT: G1 decision 1 failed clause (2b) on 7 events over 4 treatment rows (control noise floor 5),
# every one a SOLITARY, FULLY RESOLVED `[E]` token standing immediately behind a value cue -- "priced at
# [E1]", "range from [E17]", "from 500 to [E10] thousand metric tons". The clause had an INSTRUMENT
# (`eval._bare_handle_escapes`, H2) and NO REMEDY anywhere in the stack. The [N] half is covered three
# ways (splice a solitary resolved handle, sever a `grouped_in_slot` one, drop an unresolvable one), and
# `_resolve_evidence_handles` acts only on UNRESOLVABLE `[E]` -- so a RESOLVED [E] in a value slot was
# left standing BY CONSTRUCTION, on both arms. That is D-PQ HANDLE-1's own defect (the sentence promised a
# figure it cannot produce) and it takes D-PQ HANDLE-1's own ladder: sever the clause when the sentence
# keeps another receipt, drop the sentence when it does not. NEVER a splice -- an [E] payload is a source,
# a date and a snippet, so there is no figure to write and inventing one is the class this wave exists to
# make unconstructible (D3: deletion beats a fourth fence).
#
# WHY IT IS ITS OWN PASS AND WHY IT SITS *HERE*, AFTER `_prune_orphan_evidence_handles`. Built first as a
# second conviction inside `_resolve_evidence_handles`, it PRE-EMPTED THE PRUNE: an orphan [E] standing in
# a value slot is also a resolved-in-slot escape, so this remedy removed the token before the prune could,
# and `ev_prune` -- a SLOT-EMPTYING seam producer that LICENSES a slot-orphan cut -- stopped firing. Four
# H1 fold pins (X1, X6, Y2, Y5) reproduce that regression exactly. The correct placement follows from what
# the clause MEASURES: `bare_handle_escapes` scans the ASSEMBLED BODY, so its population is the tokens that
# survived every earlier pass -- the prune included. Running here leaves each producer its own cases and
# makes this one a strict backstop over what is left.
# ORDERING, EXACTLY: after `_prune_orphan_evidence_handles` (so the prune keeps its own population) and
# BEFORE `_tidy_handle_debris` (which closes the bracket frames a removal leaves) and before TIDY-2 (which
# repairs the paragraph seam a whole-sentence drop opens, off the seam this pass mints).
def _drop_evidence_value_slot(structured: dict | None, uniq: list | None, vreport=None) -> dict:
    """Sever the clause (or drop the sentence) carrying a RESOLVED `[E]` handle in a VALUE SLOT.

    Returns `{convicted, handles_dropped, sentences_dropped}` -- ZERO-VALUED on every turn that had none,
    so the caller stamps nothing (the OFF-arm-clean rule). Mutates `tldr`/`mechanism` in place; never
    raises, because a render guard must never be the thing that breaks an answer.

    THE CALLER GATES IT ON `handle_prose`, and nothing in here reads the environment: this is a
    TREATMENT-LANE pass, so a control turn's prose, ledger, seams and trace are byte-identical.

    IT IS NOT `unresolvable`, AND THE DISTINCTION IS H1 FIX Z2's (there, `binding_refused`): the receipt
    EXISTS, resolved, and names the right item. What is convicted is the SLOT. So it is charged to its own
    class, `_E_VALUE_SLOT_CLASS`, which the caller folds into the ONE strip ledger.

    ONE GRAMMAR WITH THE INSTRUMENT: `_E_HANDLE_RX` + `_HANDLE_VALUE_SLOT_RX`, which is exactly the pair
    `eval._bare_handle_escapes` scans the assembled body with. A second spelling here is how two readers of
    one page drift apart -- and on this clause it would be a remedy that cannot satisfy its own threshold.
    THE CUE IS NOT A PERFECT CRITERION, AND THAT IS RECORDED RATHER THAN PATCHED (plan 10.18.2): on the r2
    population 4 of 7 are genuine broken promises and 3 are the house CITATION idiom wearing the same cue
    ("the dated evidence at [E45]", "documented from [E24]"). A lexical exemption invented from three
    examples was REFUSED -- the Z4/W1 finding is on the record that a cue-only lexical rule deleted 314 of
    32,557 stored sentences -- so the prompt half (`_SYSTEM_HANDLES`: "AN [E] HANDLE IS NEVER A FIGURE") is
    what should drive the population to zero and this is the backstop. Narrowing the CRITERION is a
    re-freeze decision, stated as an open question at plan 10.18.4, not taken here.

    A CONVICTED TOKEN BACKS NOTHING (`_resolve_number_handles`' `grouped_in_slot` rule): two escapes in one
    sentence kill it rather than severing twice and meeting at ", ." -- the measured `dv_sub_ddg_floor`
    shape. And a sever NEVER swallows a receipt the reader keeps; it falls back to the bare token drop at
    the identical decision the [N] pass makes."""
    census = {"convicted": 0, "handles_dropped": 0, "sentences_dropped": 0}
    if not isinstance(structured, dict):
        return census
    n_uniq = len(uniq or [])
    try:
        for field in ("tldr", "mechanism"):
            text = structured.get(field)
            if not isinstance(text, str) or "[E" not in text:
                continue
            recs = []                          # (match, members, sentence span, convicted?)
            for m in _E_HANDLE_RX.finditer(text):
                members = _e_handle_members(m.group(0))
                s0, s1 = _handle_sentence_span(text, m.start())
                bad = bool(members and all(1 <= i <= n_uniq for i in members)
                           and _HANDLE_VALUE_SLOT_RX.search(text[s0:m.start()]))
                recs.append((m, members, s0, s1, bad))
            spans = [(r[0].start(), r[0].end()) for r in recs if r[4]]
            if not spans:
                continue
            keep_at = ([r[0].start() for r in recs
                        if not r[4] and any(1 <= i <= n_uniq for i in r[1])]
                       + [m.start() for m in _N_HANDLE_HP_RX.finditer(text)])
            ops: list[tuple[int, int]] = []
            kills: list[tuple[int, int]] = []
            for m, members, s0, s1, bad in recs:
                if not bad:
                    continue
                census["convicted"] += 1
                if _sentence_keeps_other_receipt(text, s0, s1, spans, n_uniq):
                    a = _handle_clause_start(text, s0, m.start())   # the cue is the fallback floor, so a
                    if any(a <= p < m.end() for p in keep_at):      # sever never leaves a dangling slot
                        a = m.start()
                    if a and text[a - 1] == " " and (m.end() >= len(text)
                                                     or text[m.end()] in " ,.;:)!?"):
                        a -= 1
                    ops.append((a, m.end()))
                    census["handles_dropped"] += len(members)
                    continue
                e = s1
                if s0 == 0:
                    while e < len(text) and text[e] == " ":
                        e += 1
                if (s0, e) in kills:
                    continue
                kills.append((s0, e))
                census["sentences_dropped"] += 1
                # X2: a WHOLE-SENTENCE producer names its own tag and is NOT in `_SLOT_EMPTYING_SEAM_SRCS`
                # (the sentence it cut is gone, so it is evidence that nothing was EMPTIED); X6: that kind
                # of producer passes `allow_empty` False, so a field-final cut mints no empty-key record.
                _mint_strip_seam(vreport, field, text[e:], src=_SEAM_SRC_E_VALUE_SLOT)
            merged: list[tuple[int, int]] = []
            for a, b in sorted(ops + kills):
                if merged and a <= merged[-1][1]:
                    merged[-1] = (merged[-1][0], max(merged[-1][1], b))
                else:
                    merged.append((a, b))
            out, pos = [], 0
            for a, b in merged:
                a = max(a, pos)
                out.append(text[pos:a])
                pos = max(pos, b)
            out.append(text[pos:])
            new = "".join(out)
            if not text[:1].isspace():
                new = new.lstrip(" \t")
            structured[field] = new
    except Exception:  # noqa: BLE001 -- a render guard must never be the thing that breaks an answer
        return census
    return census


# ══ D-HP-25 V2 (plan 10.30.4) -- THE `[E]` GEO-CONTAINMENT PASS ══════════════════════════════════════
#
# MODELLED ON `_drop_evidence_value_slot` ABOVE: the same recs-then-act shape, the same sever-vs-kill
# ladder, the same merge/splice arithmetic. COPIED SHAPE, NOT A WIDENING -- see `_E_GEO_CONTRADICTION_
# CLASS` for why folding the two into one class is refused, and why a hook inside
# `_resolve_evidence_handles` is the H1 FIX Z2 error.
#
# THE RULE, STATED AS A CONJUNCTION SO EVERY CLAUSE MUST HOLD. Convict a RESOLVED, SOLITARY `[E]` iff:
#   (a) the CLAIM WINDOW -- the SAME `_owned_token` core, with the `[E]` tokens as the sibling index --
#       owns EXACTLY ONE canonical geography `G_c`; AND
#   (b) the receipt's FULL STORED TEXT (`row['text']`) contains NO surface of `canon_closure(G_c)`.
#       NEVER the 140-char snippet, NEVER the label: a snippet is a display artifact and convicting on
#       one measures TRUNCATION, not binding; AND
#   (c) that same text DOES contain at least one surface of some OTHER country.
#
# (c) IS THE WHOLE DESIGN. It makes this a POSITIVE-CONTRADICTION detector: SILENCE ON ABSENCE (a receipt
# that names no country is not evidence of the WRONG country), SILENCE ON AGGREGATES, and all four V1
# laws applying unchanged on BOTH the claim side and the receipt side. Without (c) the pass would convict
# every correctly-bound sentence whose supporting document simply never spells its country out, which is
# most of the corpus.
#
# THE OFFLINE-TEXT LIMITATION, RECORDED HERE RATHER THAN DISCOVERED LATER: `uniq` carries the row `text`
# the turn actually retrieved, so this pass reads the same bytes the reader's receipt is built from. An
# OFFLINE replay (M-1) that reconstructs rows from stored artifacts sees only what those artifacts kept,
# and the artifacts keep a SNIPPET. The remedy is a HYDRATION SIDECAR at M-1/M-2 (re-read full text from
# the store), never a relaxation of (b) onto the snippet -- see plan 10.30.11.
def _drop_evidence_geo_contradiction(structured: dict | None, uniq: list | None, vreport=None) -> dict:
    """Sever the clause (or drop the sentence) carrying a RESOLVED `[E]` whose text names a DIFFERENT
    country than the sentence does.

    Returns `{convicted, handles_dropped, sentences_dropped}` -- ZERO-VALUED on every turn that had none,
    so the caller stamps nothing (the OFF-arm-clean rule). Mutates `tldr`/`mechanism` in place; never
    raises, because a render guard must never be the thing that breaks an answer.

    THE CALLER GATES IT ON `handle_prose`, and nothing in here reads the environment: this is a
    TREATMENT-LANE pass, so a control turn's prose, ledger, seams and trace are byte-identical.

    ITS OWN REMEDY, ITS OWN SEAM, ITS OWN CLASS. Sever when the sentence keeps another receipt
    (`_sentence_keeps_other_receipt`), kill the sentence when it does not -- and a sever NEVER swallows a
    receipt the reader keeps (`keep_at`), which is the identical decision the [N] pass and the value-slot
    pass both make. NEVER a splice: an [E] payload is a source, a date and a snippet, so there is no
    figure to write."""
    census = {"convicted": 0, "handles_dropped": 0, "sentences_dropped": 0}
    if not isinstance(structured, dict):
        return census
    rows = list(uniq or [])
    n_uniq = len(rows)
    try:
        for field in ("tldr", "mechanism"):
            text = structured.get(field)
            if not isinstance(text, str) or "[E" not in text:
                continue
            recs = []                          # (match, members, sentence span, convicted?)
            for m in _E_HANDLE_RX.finditer(text):
                members = _e_handle_members(m.group(0))
                s0, s1 = _handle_sentence_span(text, m.start())
                bad = (len(members) == 1 and 1 <= members[0] <= n_uniq
                       and _e_geo_contradicts(text, s0, s1, m, rows[members[0] - 1]))
                recs.append((m, members, s0, s1, bad))
            spans = [(r[0].start(), r[0].end()) for r in recs if r[4]]
            if not spans:
                continue
            keep_at = ([r[0].start() for r in recs
                        if not r[4] and any(1 <= i <= n_uniq for i in r[1])]
                       + [m.start() for m in _N_HANDLE_HP_RX.finditer(text)])
            ops: list[tuple[int, int]] = []
            kills: list[tuple[int, int]] = []
            for m, members, s0, s1, bad in recs:
                if not bad:
                    continue
                census["convicted"] += 1
                if _sentence_keeps_other_receipt(text, s0, s1, spans, n_uniq):
                    a = _handle_clause_start(text, s0, m.start())
                    if any(a <= p < m.end() for p in keep_at):      # ...never swallow a kept receipt
                        a = m.start()
                    if a and text[a - 1] == " " and (m.end() >= len(text)
                                                     or text[m.end()] in " ,.;:)!?"):
                        a -= 1
                    ops.append((a, m.end()))
                    census["handles_dropped"] += len(members)
                    continue
                e = s1
                if s0 == 0:
                    while e < len(text) and text[e] == " ":
                        e += 1
                if (s0, e) in kills:
                    continue
                kills.append((s0, e))
                census["sentences_dropped"] += 1
                # X2: a WHOLE-SENTENCE producer names its own tag and is NOT in `_SLOT_EMPTYING_SEAM_SRCS`
                # (the sentence it cut is gone, so it is evidence that nothing was EMPTIED); X6: that kind
                # of producer passes `allow_empty` False, so a field-final cut mints no empty-key record.
                _mint_strip_seam(vreport, field, text[e:], src=_SEAM_SRC_E_GEO)
            merged: list[tuple[int, int]] = []
            for a, b in sorted(ops + kills):
                if merged and a <= merged[-1][1]:
                    merged[-1] = (merged[-1][0], max(merged[-1][1], b))
                else:
                    merged.append((a, b))
            out, pos = [], 0
            for a, b in merged:
                a = max(a, pos)
                out.append(text[pos:a])
                pos = max(pos, b)
            out.append(text[pos:])
            new = "".join(out)
            if not text[:1].isspace():
                new = new.lstrip(" \t")
            structured[field] = new
    except Exception:  # noqa: BLE001 -- a render guard must never be the thing that breaks an answer
        return census
    return census


def _e_geo_contradicts(text: str, s0: int, s1: int, m, row) -> bool:
    """The three-clause conjunction of plan 10.30.4, for ONE resolved solitary `[E]` occurrence.

    THE CLAIM SIDE reuses the ownership core with the `[E]` tokens as the SIBLING INDEX -- "the previous
    sibling" must mean the previous handle OF THE KIND BEING BOUND, or an `[E]` in a sentence full of
    `[N]`s would be windowed by tokens that have nothing to do with it. L1 and L3 are applied to that
    window exactly as `_handle_geo_phrase` applies them, and both resolve to SILENCE.

    THE RECEIPT SIDE reads `row['text']` -- THE FULL STORED TEXT, never the 140-char snippet and never
    the label. All four laws apply to the text scan too: `geo_lexicon.extract_geos` already discharges
    L4 (word boundaries, the follower blacklist, homonyms, ambiguous surfaces), `sentinel_hit` discharges
    L1, and `canon_closure` discharges L2 -- an EU mention in a France receipt's text is the claim's own
    ancestor and is therefore CONTAINMENT, not contradiction.

    Never raises."""
    try:
        sent = text[s0:s1]
        a, b = m.start() - s0, m.end() - s0
        if not (0 <= a < b <= len(sent)):
            return False
        toks = _geo.extract_geos(sent)
        if not toks:
            return False
        sibs = [(mm.start(), mm.end()) for mm in _E_HANDLE_RX.finditer(sent)]
        lo, hi = _sibling_window(sent, a, b, siblings=sibs)
        if _geo.sentinel_hit(sent[lo:hi]):                   # L1 on the claim side
            return False
        in_window = {slug for (ts, te, slug) in toks if ts >= lo and te <= hi}
        if len(in_window) != 1 or in_window == {_geo.EU_SLUG}:   # L3 + L1's conditional half
            return False
        k = _owned_token(sent, a, b, toks, _GEO_RIGHT_APPOS_RX, siblings=sibs)
        if k is None:
            return False                                     # (a): no OWNED geography -> silent
        claim = _geo.canon_closure(toks[k][2])
        body = str((row or {}).get("text") or "")            # THE FULL STORED TEXT. Never the snippet.
        if not body.strip():
            return False                                     # nothing to read -> silent, never a hit
        if _geo.sentinel_hit(body):                          # L1 on the receipt side
            return False
        found = _geo.slugs_in(body)
        if claim & _geo.closure_of(found):                   # (b): the claim's closure IS mentioned
            return False
        # [REVIEW MAJOR, FIXED 2026-08-15 -- L1's CONDITIONAL HALF ON THE RECEIPT SIDE.] `sentinel_hit`
        # deliberately does NOT carry `european_union` (geo_lexicon.py:173-180): the EU is a real
        # country-level slug on the ESR/PSD tables and its AGGREGATE reading is conditional, which only
        # the caller can evaluate. V1 evaluates it (`_receipt_geo_text`: `slugs == {EU_SLUG}` -> `set()`);
        # this side did not, so an `EU wheat exports ...` receipt read as a POSITIVE CONTRADICTION of a
        # German/Italian/Polish/Romanian/Hungarian claim and KILLED THE SENTENCE. Only `france` carries
        # the EU ancestor edge (plan 10.30.11(C) residual 3 keeps the other five out on purpose), and
        # that residual's own justification -- "an European Union receipt with no member state beside it
        # is an AGGREGATE and never compares at all" -- was true of V1 and FALSE HERE until this line.
        # THE FIX IS THE FENCE, NOT THE VOCABULARY: the lexicon is NOT widened (that is the edit class
        # this wave refuses); the EU simply never counts as the OTHER country that convicts. It costs
        # nothing that clause (c) was entitled to -- when a member state stands beside the EU in the same
        # receipt, THAT slug still convicts on its own (or clause (b) has already exonerated the claim).
        others = {s for s in found
                  if s != _geo.EU_SLUG and not (_geo.canon_closure(s) & claim)}
        return bool(others)                                  # (c): POSITIVE contradiction, or silence
    except Exception:  # noqa: BLE001 -- fail toward NOT convicting
        return False


# CYCLE-10-AMEND (2026-08-08), REVIEW MAJOR 1+2 -- READ (a) AS IT NOW STANDS. "The body-wide pass that
# follows then has nothing left to delete" was true of the SNIPPET and false of the ROW: the row's own
# `[10]` marker is not a `_CIT_HANDLE` and IS a `_level_tokens` hit, so on OUTLOOK the pass deleted every
# row from ref 10 up, clean snippet and all. There is no body-wide pass over the footer any more -- both
# call sites append the assembled footer AFTER `reg.sanitize` (see the note at the L2 body). That makes
# THIS function's row-scope pre-clear the ONLY register gate the footer gets: it is not a belt-and-braces
# duplicate of a later pass, it is the gate. Do not remove it, and do not pass it a register other than
# the one the body is sanitized with.
@functools.lru_cache(maxsize=4096)
def _row_snippet_cleared(s: str, market_register: str) -> str:
    """The register verdict on ONE already-collapsed snippet string.

    CYCLE-10-AMEND (2026-08-08), REVIEW MINOR 3 -- THE REGISTER BUDGET. `_document_source_rows` is walked
    TWICE on every turn: once by `_prune_orphan_evidence_handles` (through `_emitted_evidence_refs`,
    before the scaffold) and once by `_cited_sources_block` (at render time). The review asked for ONE
    walk shared between the two readers; that is NOT SAFE HERE and the reason is structural rather than
    stylistic: `_maybe_scaffold_episodes` APPENDS to `structured['sources']` and rebinds
    `verifier['resolved']` (answer.py:3324) BETWEEN the two calls (prune 2139 -> scaffold 2163 -> block
    2177). A walk cached at prune time and replayed at render time would drop every synthesized
    episode-receipt row from the footer while its `[E]` marker stayed on the page -- precisely the
    dangling-marker defect the three-place rule exists to make unreachable.
    So the DUPLICATED WORK is removed instead of the second walk: the cost of a walk is one `reg.sanitize`
    per row, and sanitize is a pure function of (text, market_register) -- it reads no environment (see
    register.py's note at _REVERSION_PHRASES) and its only lookups are `lru_cache(maxsize=1)` registries.
    Memoizing it collapses the second walk's register cost to zero, keeps the second walk's FRESHNESS, and
    is correct for the scaffold's new rows too (they simply miss the cache)."""
    try:
        return reg.sanitize(s, market_register=market_register).strip()
    except Exception:  # noqa: BLE001 -- a footer must never be the thing that breaks an answer
        return ""


def _source_row_snippet(text: object, *, market_register: str = reg.FENCED) -> str:
    """One `## Sources` row's snippet, normalized to a single line and pre-cleared through the register
    pass the assembled body will run. Returns "" when nothing of it may be shown."""
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    if not s:
        return ""
    return _row_snippet_cleared(s, market_register)


def _document_source_rows(d: dict, vreport: dict, *,
                          market_register: str = reg.FENCED) -> list[tuple[str, str]]:
    """(ref, rendered row) for every DOCUMENT ledger entry the `## Sources` block emits, in ledger order.

    ONE walk, TWO readers: `_cited_sources_block` renders these rows and
    `_prune_orphan_evidence_handles` asks which refs they cover. That is the whole of CYCLE-10 FIX 3 --
    the prune's authority stops being a parallel re-derivation of "which ledger rows resolved" and becomes
    the emission decision itself, so "a marker with no row" is decided by the code that emits rows."""
    resolved = (vreport or {}).get("resolved") or {}
    from leviathan.graphrag import display as dp
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for s in (d.get("sources") or []):
        ref = str(s.get("ref", "")).strip().strip("[]")
        if not ref or ref in seen:
            continue
        seen.add(ref)
        if ref.upper().startswith("N"):
            continue                              # the [N] namespace is emitted off the PROSE, not here
        if ref not in resolved:
            continue
        r = resolved[ref]
        snip = _source_row_snippet(r.get("snippet"), market_register=market_register)
        head = f"[{ref}] {dp.source_name(str(r.get('source') or ''))} ({r.get('date')})"
        row = head + (f": {snip}" if snip else "")
        # CYCLE-10-AMEND (2026-08-08), REVIEW MINOR 4 -- EVERY ROW TERMINATES ITSELF. A head-only row
        # ("[5] USDA WASDE (2014-01-01)") carried no sentence terminator, so ANY sentence splitter of the
        # `([.!?;]\s+)` family FUSES it with the row below into one unit -- and a single banned neighbour
        # then takes a good attribution down with it. The footer no longer meets the body-wide register
        # pass at all (see the two call sites), so this is not what keeps rows alive today; it is the
        # property that stops the NEXT sentence-scoped consumer from re-minting the same defect. One
        # character, appended only when the row does not already end a sentence.
        if row[-1:] not in (".", "!", "?", ";"):
            row += "."
        out.append((ref, row))
    return out


def _emitted_evidence_refs(d: dict, vreport: dict, *,
                           market_register: str = reg.FENCED) -> set[str]:
    """The [E]/document refs the `## Sources` block WILL emit a row for -- the ledger's own `ref` key AND,
    when that ref is an E-form / zero-padded / float spelling of an integer, the canonical digit the PROSE
    writes (CYCLE-9 REVIEW BLOCKER 2's two-key rule, unchanged)."""
    live: set[str] = set()
    for ref, _row in _document_source_rows(d, vreport, market_register=market_register):
        live.add(ref)
        norm = _E_REF_CANON_RX.match(ref)
        if norm:
            live.add(str(int(norm.group(1))))
    return live


def _cited_sources_block(d: dict, vreport: dict, number_calls: list | None, *,
                         market_register: str = reg.FENCED) -> str:
    """The single reader-facing `## Sources` list: the model's OWN handles, every entry resolved by the
    verifier to a real item's true metadata. Cited-only — retrieved-but-uncited items stay machine-side
    (res['evidence'] / res['citations']).

    THE [N] ORPHAN PRUNE (cycle-3 review). This block reads `d['sources']`, which `_resolve_number_handles`
    does not touch: a handle whose sentence was dropped, or whose clause was severed, left the prose but
    kept its footer row -- a `## Sources` entry pointing at nothing the reader can find, on exactly the
    turns where the number was the thing that failed. `d` IS the final structured dict (this runs after
    verify, after the scaffold, after humanize), so its two prose fields are the reader's page and the
    membership test is exact. SCOPED TO THE [N] NAMESPACE, deliberately: the [E]/positional half has its
    own recorded, deliberately-unfixed duplicate (see `_maybe_scaffold_episodes`' KNOWN COSMETIC note and
    its test), and widening this prune would move that decision and the OFF arm with it.

    ══ D-PQ HANDLE-4: THE OTHER HALF OF THE SAME JOIN, AND THE ROOT OF THE MEASURED DEFECT ══
    The prune answers "a row with no handle". Nothing answered "a HANDLE WITH NO ROW", and that is what
    the deck actually shipped: 9 of 12 dcw rows in BOTH passes and 22 of 25 covenant rows carried at least
    one `[N<n>]` in the reader's prose with NO footer entry anywhere -- 8 to 24 dangling markers on a row.

    THE CAUSE IS A NAMESPACE MISMATCH THAT MADE THE OLD LEDGER-SIDE [N] BRANCH UNREACHABLE IN PRODUCTION,
    and it is the SAME unreachability `verify.py` already found and worked around on its side
    (verify.py:544-548, `_is_number_declaration`): the ledger `ref` is a BARE INTEGER by tool schema, so a
    model that correctly declares its cited [N] rows writes `{ref: 7}`, never `{"ref": "N7"}`.
    `ref.upper().startswith("N")` therefore never fired for a real turn; verify keeps those entries in
    `sources` but deliberately does NOT put them in `resolved` (a numbers row is not a document), so the
    document branch skipped them too. Every [N] marker in the prose was dangling BY CONSTRUCTION, on every
    turn, in both bodies.

    THE FIX IS THE PRUNE'S MIRROR, not a new policy: the reader's PROSE is the authority in both directions.
    A [N] index the prose still carries GETS its row, sourced from `number_calls` through `cit.from_number`
    -- the same producer the prune already uses, so a spliced figure and its footer line cannot disagree --
    and an index the prose no longer carries gets none. Together the two halves make the join TOTAL in the
    [N] namespace: no dangling marker, no orphan row. Nothing here reads or moves the [E]/positional half.

    SAFE BY CONSTRUCTION AGAINST THE UNRESOLVABLE CLASS: `_resolve_number_handles` runs FIRST and under the
    SAME `verifier.get("enabled")` gate, and it removes every handle that resolves to nothing -- so an index
    reaching this scan has already been shown to have a value. `_n_row` still fails closed on a malformed or
    out-of-range call, because a footer must never be the thing that breaks an answer.

    CYCLE-10 FIX 2: the document rows come from `_document_source_rows` (see its note for the register
    interaction that was deleting them) and `market_register` is the SAME value the assembled body will be
    sanitized with -- passing a different one would pre-clear the snippet against the wrong rule."""
    prose = f"{d.get('tldr') or ''}\n{d.get('mechanism') or ''}"
    prose_n: list[int] = []                       # every [N] index the READER still sees, in written order
    for _m in _N_HANDLE_RX.finditer(prose):       # ...grouped tokens enumerated (D-PQ HANDLE-2)
        for _i in _n_handle_members(_m.group(0)):
            if _i not in prose_n:
                prose_n.append(_i)

    def _n_row(idx: int) -> str | None:
        if idx < 1:
            # review follow-up (a): [N0]/negative would index calls[-1] and mint a mislabeled row
            return None
        try:
            c = cit.from_number((number_calls or [])[idx - 1], idx)
        except (ValueError, IndexError, TypeError):
            return None
        return f"[N{idx}] {c.label}" + (f"  [known {c.date}]" if c.date else "")

    lines = [row for _ref, row in _document_source_rows(d, vreport, market_register=market_register)]
    # THE [N] BLOCK, off the PROSE and nothing else: ascending index, after the document rows, exactly one
    # row per index the reader can still see. Emitting it here rather than inside the ledger walk is what
    # makes the order DETERMINISTIC -- a ledger that declared N2 and not N1 used to interleave them 2,1,3
    # -- and it is the same authority the prune already uses, read once for both directions.
    #
    # CYCLE-6 FIX-C, THE CLONE DROP -- AND WHERE IT DOES *NOT* LIVE. `_number_row_clones` names the indices
    # whose rendered row is identical to an earlier index's in EVERY field (gate-3 dpq shipped one in both
    # passes: [N10]/[N12] p1, [N9]/[N10] p2, the same FUTURES EOD 2026-12 corn settle of 446 differing only
    # in index). The drop is effected ENTIRELY on the prose side, by `_dedup_number_handles` re-pointing the
    # markers BEFORE the body renders, so by the time this loop runs the clone index is not in `prose_n` and
    # there is nothing here to skip.
    #
    # CYCLE-6 REVIEW (2026-08-08), MEDIUM 6: cycle-6 ALSO skipped clone rows here, on this function's own
    # authority, and that was backwards. Every index this function could call a clone is by construction an
    # index the PROSE still carries (`prose_n` is where the map is derived from), so dropping its row is
    # precisely the dangling-marker defect D-PQ HANDLE-4 abolishes -- latent on the two production call
    # sites only because the prose pass runs first, and a loaded gun for any other caller. ONE MECHANISM:
    # the prose pass drops the marker, cycle-4's prose-authority rule drops the row with it, and this
    # function renders exactly one row per index the reader can still see, always.
    kept_n = sorted(prose_n)
    for idx in kept_n:
        row = _n_row(idx)
        if row is not None:
            lines.append(row)
    lines += _prose_value_rows(prose, number_calls, kept_n)      # CYCLE-6 FIX-A
    return ("\n\n## Sources\n" + "\n".join(lines)) if lines else ""


def _number_row_clones(prose_n: list[int], number_calls: list | None) -> dict[int, int]:
    """{clone index -> survivor index} for [N] rows that are FULLY IDENTICAL as rendered -- same label
    (index aside), same value, same unit, same period, same known-stamp. Keyed on the rendered row STRING
    minus its `[N#] ` prefix, which is exactly that tuple and nothing else: `cit.from_number` writes the
    source, metric, commodity, geo, period, delivery month, value, unit, print-kind, staleness clause and
    truncation clause into that one line, so two lines matching there are two renderings of one fact and a
    reader gains nothing from the second. The SURVIVOR IS THE LOWEST INDEX (the footer's own order, so
    'keep the first' is stable regardless of who calls this). ANY difference in ANY field -> both stay.
    Fails closed and silent: a call that will not render is simply not a clone of anything."""
    first: dict[str, int] = {}
    out: dict[int, int] = {}
    for idx in sorted(i for i in prose_n if i >= 1):
        try:
            c = cit.from_number((number_calls or [])[idx - 1], idx)
        except (ValueError, IndexError, TypeError):
            continue
        key = c.label + (f"  [known {c.date}]" if c.date else "")
        if key in first:
            out[idx] = first[key]
        else:
            first[key] = idx
    return out


def _prose_value_rows(prose: str, number_calls: list | None, cited_n: list[int]) -> list[str]:
    """CYCLE-6 FIX-A -- the footer rows the FINAL prose earns by STATING a served value (see the long note
    at `citations.prose_completion_citations` for the measured failure and the four refusals).

    `prose` is the post-strip, post-tidy, post-humanize body: a figure the verifier removed cannot summon a
    row, because it is not in the string this reads. `cited_n` is the set of indices whose `from_number`
    headline is already on the page, so those rows seed the de-dup instead of being minted again.

    THE DE-DUP HORIZON IS THE WHOLE FOOTER, not one call, and that is what makes the pass safe on a real
    hybrid turn: the deck routinely serves the same print twice (a `latest` call beside the 30-row window
    it was taken from), and a per-call horizon would foot 15.17 once for each. Seeded with EVERY rendered
    headline first, then extended as rows are minted, walking calls in index order.

    Never raises and never partially fails: an unparseable call is skipped, a footer must not be the thing
    that breaks an answer (the same contract `_n_row` keeps)."""
    calls = number_calls or []
    if not calls or not prose.strip():
        return []
    try:
        from leviathan.graphrag.orchestrator import _stated_values      # lazy: orchestrator imports THIS
        stated = _stated_values(prose)
    except Exception:  # noqa: BLE001
        return []
    if not stated:
        return []
    seen: set = set()
    for idx in cited_n:                            # every headline already on the page, whatever its call
        try:
            call = calls[idx - 1]
            seen.add(cit.row_key(call, cit.headline_row(call)))
        except (IndexError, TypeError, AttributeError):
            continue
    try:
        cits = cit.prose_completion_citations(calls, stated, seen=seen, cited=set(cited_n))
    except Exception:  # noqa: BLE001
        return []
    return [f"[{c.id}] {c.label}" + (f"  [known {c.date}]" if c.date else "") for c in cits]


def _foreign_regime_names(graph: gph.CausalGraph, contracts: list[str]) -> set[str]:
    """Regime names that belong ONLY to contracts outside this answer's scope — asserting one is the
    measured cross-contract fabrication (an invented 'bullish_protein_squeeze' from another DAG)."""
    own = {s.name for cid in contracts if cid in graph.contracts for s in graph.contracts[cid].convergence}
    return {s.name for cid, c in graph.contracts.items() if cid not in contracts
            for s in c.convergence} - own


_DEGRADED_BANNER = ("> **Degraded answer.** The primary reasoning model was unavailable; this answer "
                    "came from {m} after retries. Treat conclusions with extra caution.\n\n")


def _pop_degraded(structured) -> str | None:
    """Lift the serving_call degradation tag off the structured dict (it must never render as content)."""
    return structured.pop("_degraded_model", None) if isinstance(structured, dict) else None


def _pop_usage(structured) -> dict | None:
    """Lift the D-AM-4 usage tag off the structured dict — observability only, never content. Rides
    trace.synth_usage in BOTH bodies so the orchestrator's EMF emit can price the turn."""
    return structured.pop("_usage", None) if isinstance(structured, dict) else None


def _call_opus(system: str, user, *, model: str, tool: dict, on_token=None, temperature=None,
               max_tokens: int | None = None, effort: str | None = None) -> dict:
    """The real serving call — provider-routed (Anthropic API or Bedrock via providers.py) with the
    production fallback chain (backoff retry -> Sonnet->Haiku degradation, tagged). PROMPT CACHING: the
    system prompt is always a cached block, and when `user` arrives as a (stable_prefix, volatile_tail)
    tuple the stable part — the per-contract graph context, byte-identical across a session's turns —
    gets its own cache breakpoint (manual blocks work identically on both providers). Turn 2+ of a
    conversation reads the shared prefix at ~0.1x input price. Injected test fakes keep the plain-string
    `user` API; only this real path structures blocks. When `on_token` is set (SSE turns) the note STREAMS
    token-by-token via serving_call_stream (buffered otherwise — byte-identical for eval/POST).
    `temperature` (D18) is forwarded only when provided — the dispatch planner pins 0; synthesis callers
    never pass it, and the streaming (synthesis-only) path never carries it."""
    from leviathan.graphrag import providers as pv
    client = pv.make_client()
    sys_blocks = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
    if isinstance(user, tuple):
        stable, volatile = user
        user = [{"type": "text", "text": stable, "cache_control": {"type": "ephemeral"}},
                {"type": "text", "text": volatile}]
    _sink: list = []                               # D-AM-4: the served attempt's Usage lands here
    # max_tokens: TURN default 12000, EVERY MODE INCLUDING DEEP (D-HP G1 AMENDMENT A1, owner-ratified
    # 2026-08-14: "raise the ceiling to every mode, and raise the ceiling for deep"). It was 6000 (citv2
    # lost a turn to truncation at 4096; 6000 was the answer to THAT), and 6000 is what deep_v2 max width
    # outgrew.
    # THIS IS A WIDTH FIX, NOT A HANDLE-PROSE CONCESSION -- the number that proves it is on the CONTROL
    # arm: dv_episode_lanina_arg control run 2 recorded out=5851 against the 6000 ceiling, 97.5% of it,
    # with no plan region in the schema at all. The ceiling was already marginal for deep_v2 at max width
    # BEFORE D-HP existed; the handle-prose arm's popped `plan` region (measured at ~47% of treatment
    # output) merely spent the last 2.5% and killed two rows outright.
    # SIZING (the G1 void diagnosis, two independent estimators that agree): METHOD A additive
    # (out = prose + overhead + env + plan) projects the widest row at 6,968 / 8,792 tokens at mean /
    # max observed plan; METHOD B paired (out_T = out_C_max - sources_C + plan) projects 7,347 / 9,171.
    # Worst credible projection ~9,200. 12000 clears that by +30% and the largest MEASURED row (5,703)
    # by 2.1x; 10000 would clear the projection by only +9% against a plan region with 4.9x observed
    # variance over n=4.
    # THE CEILING ON THE CEILING IS 16,000, and it is a TRANSPORT bound, not a taste one: the eval lane
    # is BUFFERED (no `on_token` -> pv.serving_call, not serving_call_stream), and beyond ~16k
    # non-streaming the SDK's own HTTP timeout becomes the failure mode. Anything larger requires moving
    # that lane to streaming FIRST -- which the truncation error string already advises and which
    # extract.call_opus_stream would NOT rescue on its own (it raises on stop_reason=="max_tokens"
    # identically).
    # THE OFF ARM IS UNCHANGED IN EFFECT: raising a ceiling can only change a turn that was truncating,
    # and no control row ever truncated (12/12 completed, largest 5,851). Raised on the SHARED default
    # rather than threaded handles-gated through call_kw on purpose -- a treatment-only ceiling would be
    # a SECOND difference between the G1 arms and would weaken the comparison it is meant to rescue.
    # Callers composing DOCUMENTS (dossier.synthesize, its own SYNTH_MAX_TOKENS = 16000) still pass their
    # own ceiling -- forwarded only when provided, mirroring `temperature` exactly.
    kw = dict(model=pv.resolve_model(model), max_tokens=max_tokens or 12000, tool=tool,
              degrade_to=ex.HAIKU, usage_sink=_sink)  # answers grew
    _think = pv.synth_thinking()                       # c/d seam: None unless GRAPHRAG_SYNTH_THINKING=adaptive
    if _think is not None and pv.provider() != "anthropic":
        _think = None   # PROVIDER GATE, symmetric with the numbers seam (Q-0 refuter catch: this
        #                 seam gated on SEAT only, so a bedrock arm would ship thinking/effort onto
        #                 the legacy InvokeModel path -- an unretryable 400, not a clean null).
    if _think is not None and not pv.supports_adaptive(model):
        _think = None   # THE SEAT GATE (arm-d null-arm RCA 2026-08-27): _call_opus is NOT writer-only --
        #                 route_llm borrows it with model=HAIKU (:1951), and an ungated armed seam 400s
        #                 the router on a pre-4.6 seat, killing the answer before the writer runs.
    if _think is not None:
        kw["thinking"] = _think                        # both serving lanes accept it
    # Q-0 EFFORT: mode > env (the synth_model F5 precedence, one rung lower) -- a per-turn preset knob
    # must beat a process-wide default, or a task env would silently strip the tier the measurement
    # shipped it on. `effort` arrives ONLY from the mode-knob thread at the synthesis call site;
    # anything outside providers._EFFORT_WORDS resolves None (fail-open, table-pinned upstream).
    _eff = ({"effort": effort} if effort in pv._EFFORT_WORDS else None) if effort is not None \
        else pv.synth_effort()                         # effort seam (dark plumbing): None = byte-identical
    if (_eff is not None and pv.provider() == "anthropic"
            and pv.supports_effort(model)):            # provider gate + the EFFORT-probed seat set (F3:
        kw["output_config"] = _eff                     # ADAPTIVE_SEATS is a THINKING roster; 4-6/4-x are
        #                                                effort-UNPROBED and every banked arm ran opus-5)
    if on_token is not None:
        out, degraded = pv.serving_call_stream(client, sys_blocks, user, on_token=on_token, **kw)
    else:
        if temperature is not None:
            kw["temperature"] = temperature    # dispatch-only kw (D18); dropped if ever paired with on_token
        out, degraded = pv.serving_call(client, sys_blocks, user, **kw)
    if degraded and isinstance(out, dict):
        out["_degraded_model"] = degraded          # popped by the consumer -> visible caveat + trace
    if _sink and isinstance(out, dict):
        # D-AM-4: usage rides the SAME pop-tag channel as _degraded_model (never renders as content).
        # The model recorded is the one that SERVED: the degraded alias when the fallback answered.
        _u = _sink[-1]
        out["_usage"] = {"model": pv.resolve_model(degraded) if degraded else pv.resolve_model(model),
                         "in": _u.input_tokens, "out": _u.output_tokens,
                         "cache_read": _u.cache_read, "cache_write": _u.cache_creation}
    return out


def _with_rerank_lane(fn):
    """D-MW-6: give a DIRECT `answer()` call its own rerank-lane collector.

    Serving always enters through orchestrator._respond, which mints the turn's collector; but the EVAL
    LANE calls answer() directly (eval.py's non-orchestrator rows) and would otherwise produce rows with
    no `rerank_lane` column at all -- i.e. exactly the arms a parity gate needs to read. NESTED-SAFE and
    deliberately so: when a collector is already installed this is a pure pass-through, so an orchestrator
    turn keeps ONE collector for the whole turn and the stamp keeps ONE owner.

    A wrapper rather than an in-body try/finally because `answer` has three return points across ~200
    lines; wrapping cannot miss one, and functools.wraps keeps the signature introspectable."""
    @functools.wraps(fn)
    def _laned(*args, **kwargs):
        # DIFF-REVIEW FIX (D-MW P1): `fn` is invoked EXACTLY ONCE, and never from inside an
        # exception handler. The first shipped shape put the pass-through call inside a
        # try whose handler ALSO called fn -- so a raising answer() (the deterministic-floor
        # population) re-ran the whole walk + synthesis a second time, replayed SSE stage
        # ticks, and replaced the floor's recorded cause with the retry's exception. The
        # try below guards ONLY telemetry; fn sits outside every handler.
        lane = None
        try:
            from leviathan.graphrag import rankers as rk
            if rk.lane_collector() is None:
                lane = rk.RerankLaneCollector()
                rk.install_lane(lane)
        except Exception:  # noqa: BLE001 — telemetry must never break an answer
            lane = None
        if lane is None:
            return fn(*args, **kwargs)                     # orchestrator owns this turn's lane
        try:
            out = fn(*args, **kwargs)
        finally:
            try:
                rk.clear_lane()
            except Exception:  # noqa: BLE001
                pass
        try:
            if isinstance(out, dict):
                out.setdefault("trace", {})["rerank_lane"] = lane.snapshot()
        except Exception:  # noqa: BLE001
            pass
        return out
    return _laned


@_with_rerank_lane
def answer(query: str, *, graph: gph.CausalGraph, model: str = SONNET, k: int = 5, asof: str | None = None,
           near: str | None = None, max_contracts: int = 2, retrieve=None, call=None, route_fn=None,
           driver_retrieve=None, extra_context: str | None = None, extra_number_calls: list | None = None,
           extra_resolver=None, planner: str | None = None, focus_driver: str | None = None,
           silver_lookup=None, on_stage=None, numbers_lookup=None, xc_request: dict | None = None,
           outlook: bool = False, response_contract: str | None = None,
           mode_knobs: dict | None = None) -> dict:
    """Answer grounded in the graph(s) + dated evidence, structured for a reader. Routes (tiered lexical->semantic->
    LLM) to up to `max_contracts` (a soy<->corn question synthesizes both). Also pulls CROSS-CUTTING DRIVER evidence
    (WS-MS6 — B40/freight/FX/El Nino cascade triggers). Returns {answer (markdown), structured, contract(s),
    evidence, trace}.

    `outlook` (W5-D4) is the caller's TWO resolved legs -- plan.answer_mode_outlook AND
    is_outlook_explicit(query). It is ANDed with the _outlook_on() kill-switch INSIDE each body, so a
    caller that never heard of W5 (every test, the eval harness, the probe paths) gets the fenced register
    by default and the flag alone can never relax anything."""
    # D-AM-5: the synthesis-model seam, mirroring GRAPHRAG_DISPATCH_MODEL. env > params fill the
    # DEFAULT only -- an explicit caller arg (eval --model, a test, a mode override) always wins, so
    # the eval lever and the env lever can never fight. Serving passes no model, so this line is the
    # flip: set GRAPHRAG_SYNTH_MODEL on the task env and roll back by unsetting one var.
    # D-MW-30 (F5): the escalated bundle's synthesis SEAT joins that same branch, ranked mode > env >
    # params. It is INSIDE the default-only guard, so the precedence law is untouched: an explicit caller
    # --model (the eval arm, a test, an operator override) still wins outright over all three. The mode
    # outranks the env because a per-request escalation must beat a process-wide default -- otherwise a
    # task env pinning sonnet would silently strip the writer half off a bundle that was MEASURED with it
    # (12e: max+opus was the winning pair, and the wave ships bundles as measured, never re-derived).
    if model == SONNET:
        import os as _os
        model = ((mode_knobs or {}).get("synth_model")
                 or _os.environ.get("GRAPHRAG_SYNTH_MODEL")
                 or str(_prm.get("serving.synth_model", "") or "") or model)
    raw_retrieve = retrieve                                        # the CALLER's arg (None on serving) — _answer_l2
    # D-AM-10: the ONE-HOP body's retrieval width. Same per-call partial rebind as _answer_l2's (no
    # module-global mutation, so concurrent turns cannot see each other's fetch_k); {} on every
    # standard/dark turn, so both partials are constructed exactly as before.
    _fk = {"fetch_k": mode_knobs["fetch_k"]} if (mode_knobs or {}).get("fetch_k") else {}
    retrieve = retrieve or functools.partial(ev.retrieve, **_RETRIEVAL, **_fk)  # needs it raw so its cheap no-rerank
    driver_retrieve = driver_retrieve or functools.partial(ev.retrieve, **_RETRIEVAL, **_fk)  # probe path engages
    use_blocks = call is None or call is _call_opus               # real path -> prompt-cached content blocks
    call = call or _call_opus
    route_fn = route_fn or route_smart
    # D-MW-13 THE ROUTER DE-CAP, mode-aware half. `route_smart` fans out to at most k contracts and k
    # defaulted to 2 -- so a `max` walk with a seed ceiling of 6 was still handed two ids and the wider
    # tier bought nothing on any turn the dispatch planner did not route. When a mode is honored, its
    # `max_seeds` IS that k. Two fences, both deliberate:
    #   * only when route_fn is THIS module's route_smart. A CALLER-SUPPLIED route_fn (the orchestrator's
    #     planner-resolved lambda, the session-carried coreference closure, every test fake) keeps its
    #     exact 2-positional-arg call -- widening a caller's function by keyword would break the fakes
    #     and, for the session path, re-derive routing from HISTORY at a new width (a separate blast
    #     radius, deliberately left at k=2 for this wave -- D-MW-13's recorded scope line).
    #   * omit-when-absent: with no honored mode this is the same one-line call it always was.
    # RECORDED (P3 round-1, accept-with-record): the de-cap keys on `max_seeds` being PRESENT, so it also
    # honors the cap-set of any OTHER preset carrying that field -- and `deep_v2`'s realized route width
    # therefore moved 2 -> 3. Its declared max_seeds was ALWAYS 3; before this line route_smart's module
    # default k=2 truncated it, so the D-DV record measured a realized 2. deep_v2 is DARK (its gate closed,
    # the preset refused), and its preset bytes are unchanged -- but anyone re-running a deep_v2 arm against
    # the D-DV baseline is comparing a 3-seed instrument to a 2-seed one. Left as-is deliberately: honoring
    # a preset's own declared ceiling is the correct behaviour, and special-casing the two D-MW presets
    # would put the wave's name inside a general seam.
    _seed_k = (mode_knobs or {}).get("max_seeds")
    routed = (route_smart(query, graph, k=int(_seed_k)) if (_seed_k and route_fn is route_smart)
              else route_fn(query, graph))
    if not routed:
        return {"answer": "No tracked contract matched this question.", "structured": None, "contract": None,
                "contracts": [], "evidence": [], "model": model, "trace": {"routed": []}}
    if planner == "l2":                                            # L2: deterministic grounded-subgraph walk
        return _answer_l2(query, graph, model=model, asof=asof, near=near, call=call, retrieve=raw_retrieve,
                          routed=routed, extra_context=extra_context, extra_number_calls=extra_number_calls,
                          extra_resolver=extra_resolver, focus_driver=focus_driver, use_blocks=use_blocks,
                          silver_lookup=silver_lookup, on_stage=on_stage, numbers_lookup=numbers_lookup,
                          xc_request=xc_request, outlook=outlook, response_contract=response_contract,
                          mode_knobs=mode_knobs)
    if extra_resolver is not None:      # one-hop path: no walk to overlap — degenerate to resolving up front
        extra_context, extra_number_calls = extra_resolver()
    # node-diverse selection: siblings share an evidence shard, so a 2nd slot should add a DIFFERENT commodity
    # (a soymeal-vs-soyoil spread -> one meal + one oil, not two oils; a single-commodity Q -> one shard, not two).
    contracts, seen = [], set()
    for c in routed:
        nd = ev.node_for(c)
        if nd not in seen:
            seen.add(nd)
            contracts.append(c)
        if len(contracts) >= max_contracts:
            break
    # D-HP-1 (H0), THE ONE-HOP BODY'S OWN HOIST. This body builds its evidence blocks INLINE, so the
    # retrieval loop is split: RETRIEVE first, build `uniq` + the global ordinals from the complete flat
    # list, THEN render. Rendering inside the retrieval loop is exactly what made a render-order counter
    # unavailable here -- the driver block's rows are appended to `evidence` AFTER every contract block has
    # already rendered, so any numbering assigned during the loop would be short by the driver rows.
    # The emitted BLOCK ORDER is unchanged (contract blocks, then the driver block, then extra_context,
    # then the recency suffix), and with `ordinals` absent `_ev_block` returns its pre-D-HP bytes.
    stable_blocks, volatile_blocks, evidence, ev_ids, regimes = [], [], [], [], []
    _hits_by_contract: list[tuple[str, list]] = []
    for c in contracts:
        hits = retrieve(query, ev.node_for(c), k=k, asof=asof, near=near)   # variants share a commodity-node slice
        stable_blocks.append(_context_block(graph, c))             # byte-stable per contract -> cache prefix
        _hits_by_contract.append((c, hits))
        evidence += [{**h, "contract": c} for h in hits]
        ev_ids += [h["source_key"] for h in hits]
        regimes += [s.name for s in graph.contracts[c].convergence]
    # WS-MS6: cross-cutting driver/cascade evidence (the B40/freight/FX/El Nino triggers the commodity slices drop)
    drivers = _active_drivers(query, contracts, graph) if ev.driver_specs() else []
    driver_hits = _driver_evidence(query, drivers, k=_DRIVER_K, asof=asof, near=near, retrieve_fn=driver_retrieve)
    if driver_hits:
        evidence += [{**h, "contract": "(driver)"} for h in driver_hits]
    uniq = _uniq_evidence(evidence)                                # D-HP-1: the ONE list, built ONCE
    # D-HP-16 (H0 review): the dossier gate rides BOTH bodies, or `GRAPHRAG_PLANNER=onehop` -- the
    # DOCUMENTED rollback lane -- would put every dossier sub-answer back on the numbered menu with the
    # grouped-blind `remap_body` still downstream. Same lever, same reason; see `_answer_l2`'s hoist.
    _ev_menu = _evidence_menu(uniq) if _handle_menu_on() else None
    _seen_rows: set[str] = set()
    for c, hits in _hits_by_contract:
        volatile_blocks.append(f"--- DATED EVIDENCE for {c} ---\n"
                               + _ev_block(hits, _ev_menu, _seen_rows))
    if driver_hits:
        volatile_blocks.append("--- CROSS-CUTTING DRIVER EVIDENCE (cascade/convergence triggers; tie to silver) ---\n"
                               + _ev_block(driver_hits, _ev_menu, _seen_rows))
    if extra_context:                                              # hybrid numbers / conversation state (volatile)
        volatile_blocks.append(extra_context)
    # D-HP-7/8/9/12 (H1) ON THE SECOND SYNTHESIS PATH, resolved HERE because the ledger line below needs
    # it -- the same ONE read the persona, the tool schema and the verifier take further down. Spelled
    # identically to the L2 body (`_provenance` / `_census` / `_outlook` discipline).
    _handles = _handle_prose_active(mode_knobs)
    # D-HP-16: THE ONE-HOP BODY GAINS THE GROUNDING LEDGER, AND ONLY UNDER HANDLE-PROSE. This body has
    # never had one -- the comment two lines down said so as a standing fact -- which was survivable while
    # handles were optional decoration on typed prose. Under handle-ONLY prose it is not: the DOCUMENTED
    # `GRAPHRAG_PLANNER=onehop` rollback lane would render a NUMBERED menu and then tell the model nothing
    # about which addresses exist, i.e. D2's asymmetry (an unaddressable menu) restored on exactly the
    # path a rollback puts every turn on. ONE producer with the L2 body (`_grounding_ledger`), so the two
    # lanes cannot drift on what "which handles are valid" means.
    # GATED, NOT UNCONDITIONAL: appending it on every turn would change the one-hop CONTROL prompt, and
    # the OFF arm is byte-identical or it is not a control. `menu_on` rides the same gate the menu did.
    if _handles:
        volatile_blocks.append(_grounding_ledger(
            len(uniq) if _ev_menu is not None else len(evidence),
            len(extra_number_calls or []), menu_on=_ev_menu is not None,
            n_rows=_served_rows(extra_number_calls)))       # PA-8(b): rows, not calls (same producer)
    # D-RC-13 on the one-hop body: this body has no GROUNDING LEDGER line of its own on the CONTROL lane,
    # so the record-edge sentence rides its own volatile block (same text, same flag, '' when off ->
    # byte-identical assembly).
    _rec_through = _record_through(evidence)
    _rec_suffix = _recency_ledger_suffix(_rec_through)
    if _rec_suffix:
        volatile_blocks.append(_rec_suffix.strip())
    _emit(on_stage, "retrieving", props=len(evidence))
    sp, vp = _prompt_parts(query, contracts, stable_blocks, volatile_blocks)
    _emit(on_stage, "synthesizing")                               # prompt assembled; the model call starts NOW
    _emit(on_stage, "drafting")                                   # F7: the engine feed is CLOSED — prose mode
    # W5-D3: the ONE-HOP legacy body (planner != "l2"). It gets the identical seam as _answer_l2 -- the
    # kill-switch ANDed here, the mode threaded DOWN as an argument -- so a GRAPHRAG_PLANNER=onehop
    # rollback cannot silently leave outlook turns on a different register from the L2 default.
    _outlook = bool(outlook) and _outlook_on()
    _mr = reg.OUTLOOK if _outlook else reg.FENCED
    # W4-D3 (verifier blocker 2): the IDENTICAL two-gate expression as the L2 body. It is not hard-coded
    # False even though this body has no episode producer today -- `tl.render_line` has exactly ONE call
    # site (_l2_blocks) -- because the invariant being enforced is "the paragraph ships iff the prompt
    # carries an injected episode line", and spelling it the same way in both bodies means a future one-hop
    # producer is correct for free and cannot silently diverge. Today it evaluates False on every turn.
    # D-RC Phase B + D-RC-11: the IDENTICAL contract/relevance resolution as the L2 body.
    _rc_active = response_contract if response_contract in _response_contracts_enabled() else None
    _ep_rel = _rc.licenses_episodes(_rc_active) if _rc_active else _episodes_relevant(query)
    _episodes = _episodes_on(vp) and _ep_rel
    # D-DT-2 c1, V-9: the SECOND mint site. Stamped in BOTH bodies with the identical expression (the
    # W4-D3 discipline the gate above already follows). Minting only in _answer_l2 would leave a one-hop
    # turn with NO basis key at all, so `fork_licensed` would evaluate against a missing dict -- a silent
    # pass or a silent red depending on the default -- on the one planner where no fork producer exists
    # in the first place. This body has no cascade and no episode producer, so `numeric` and `episodes`
    # are structurally False here today; the other two legs are real, and a future one-hop producer is
    # correct for free. `{}` IS this body's engine trace: it writes none before the model call.
    _fork_basis_v = _fork_basis(graph, contracts, evidence, {})
    # D-CC-1 on the SECOND synthesis path, spelled with the SAME two-leg gate as the L2 body and for
    # the same reason the fork_basis mint is here (V-9): GRAPHRAG_PLANNER=onehop is a documented
    # rollback lane, and a lever that shapes every L2 turn but silently vanishes on the rollback path
    # is a divergence nobody would notice until an A/B read it. The arguments differ where the body
    # differs, exactly as _fork_basis' own table records: this body's flat `evidence` list is its
    # post-cap count, and `{}` IS its trace at the mint point (it writes no episodes_injected before
    # the model call), so n_episode_windows is structurally 0 here today and a future one-hop episode
    # producer becomes correct by passing its trace, with no other edit.
    _census = (_composition_census(contracts=contracts, number_calls=extra_number_calls,
                                   trace={}, n_evidence=len(evidence))
               if (_rc_active and _composition_census_on()) else None)
    # D-HP-7/8/9/12 (H1) ON THE SECOND SYNTHESIS PATH, spelled IDENTICALLY to the L2 body. This is the
    # DOCUMENTED `GRAPHRAG_PLANNER=onehop` rollback lane, and D-HP-16 is explicit that a one-lane landing
    # is the D2 asymmetry restored on exactly the path a rollback puts every turn on: the persona would
    # promise handle substitution while the schema still demanded a model-authored ledger, or the reverse.
    # One resolution, four seams, both bodies -- the `_provenance` / `_census` / `_outlook` discipline.
    # (`_handles` is resolved ABOVE, at the ledger seam, because the prompt needs it before this call.)
    # Q-0 EFFORT ON THE SECOND SYNTHESIS PATH (review find F2), spelled identically to the L2 body:
    # this is the documented GRAPHRAG_PLANNER=onehop rollback lane, and a knob that shapes every L2
    # turn but vanished here would run the writer at the API default while the trace stamp said "max"
    # -- the null-arm class, on exactly the path a rollback puts every turn on.
    _oh_kw = ({"effort": mode_knobs["synth_effort"]}
              if (mode_knobs or {}).get("synth_effort") and call is _call_opus else {})
    structured = call(_system(outlook=_outlook, episodes=_episodes, recency=_recency_stamp_on(),
                              cascade_walk=_cascade_walk_block_on(vp),
                              cascade_context=_cascade_context_block_on(vp),
                              cascade_deep=_cascade_deep_block_on(vp),
                              response_contract=_rc_active,
                              budget=_mode_budget(_rc_active, mode_knobs),    # D-AM-10, both bodies
                              census=_census,                                 # D-CC-1, both bodies
                              handles=_handles),                              # D-HP-7/8, both bodies
                      _pack(sp, vp, use_blocks), model=model,
                      tool=_answer_tool(handles=_handles), **_oh_kw)
    _banned_mood = _count_banned_mood(structured)                 # P9-A: RAW output, pre-sanitize
    _banned_val = _count_banned_valuation(structured)             # DP-6: valuation/flow raw counts, pre-sanitize
    _banned_flow = _count_banned_flow(structured)
    _banned_exec = _count_banned_exec(structured)                 # W5: A2 execution idioms, RAW (pinned 0 always)
    _unbacked = _count_unbacked_levels(structured)                # W5.0: bare price levels, RAW (derivation gate)
    _bare_digits = _count_bare_digits(structured)                 # D-HP-4(c): the digit-lint ESCAPE COUNTER
    # A4 on the SECOND synthesis path. There is no single choke point -- verify_citations is called from
    # _answer_l2 AND from here, and this is the documented GRAPHRAG_PLANNER=onehop rollback lane. Snapshotting
    # only the L2 body would leave the fallback with no raw draft, i.e. a silent hole in the audit exactly on
    # the path a rollback puts every turn on.
    _raw_draft = raw_draft_snapshot(tldr=structured.get("tldr"), mechanism=structured.get("mechanism"))
    degraded = _pop_degraded(structured)
    _synth_usage = _pop_usage(structured)                         # D-AM-4: same pop channel, both bodies
    _plan_tok = _plan_tokens(_pop_plan(structured))               # D-HP-7 pin (c) + A3 scalar, both bodies
    # unified provenance footer (Phase 4): document-level, deduped by source_key. Numbers citations join here in
    # the Phase-5 hybrid path; the per-prop page/char slots ride along for the page-citation recovery.
    # D-HP-1: `uniq` was rebuilt HERE and is now built once, above, beside the ordinals the menu rendered.
    ev_cits = cit.unify(uniq, extra_number_calls)                 # machine-readable list (UI drill-down)
    from leviathan.graphrag import verify as vf
    # CYCLE-9 FIX 4 on the SECOND synthesis path, for the SAME reason A4/A4b are here: identical two
    # boundaries, identical field names (see the note at the L2 body).
    _raw_draft = _fold_draft(_raw_draft, raw_draft_snapshot(
        preverify_tldr=structured.get("tldr"), preverify_mechanism=structured.get("mechanism")))
    verifier = vf.verify_citations(structured, uniq, extra_number_calls,   # D-HP-1 (iii), both bodies
                                   foreign_names=_foreign_regime_names(graph, contracts),
                                   handle_prose=_handles)                  # D-HP-9/12, both bodies
    _raw_draft = _fold_draft(_raw_draft, raw_draft_snapshot(
        postverify_tldr=structured.get("tldr"), postverify_mechanism=structured.get("mechanism")))
    _emit(on_stage, "verifying", checked=int(verifier.get("checked", 0) or 0),
          stripped=int(verifier.get("stripped", 0) or 0))
    _emit(on_stage, "verified", strips=int(verifier.get("stripped", 0) or 0))   # F7: handles may ACTIVATE now
    # D-HP-9 / R1(b): the ledger is re-minted FROM `resolved` HERE -- after verify returns, before
    # provenance stamps. OFF-arm-clean: `_handles` False -> not called -> `structured['sources']` is the
    # model's own ledger, byte-identical. See `_synthesize_sources` for why the direction and the
    # position are both part of the contract.
    if _handles:
        _synthesize_sources(structured, verifier)
    _attach_provenance(structured, verifier)                     # stamp source_key for durable chip join (6.4)
    # D-HP-15 (H1b) SELECT on the SECOND synthesis path, at the IDENTICAL position and spelled
    # identically (D-HP-16's three-lane law): BEFORE the digit lint, outside the seven-pass stack, after
    # `verify_citations`. It moved here with the L2 body at fold-2 (G-A) -- see the note there for the
    # de-markering root cause; a fence that only walks marker-intact text on one of the two bodies is
    # the same defect with a flag in front of it.
    # `injected` is None here for the SAME reason the scaffold's is -- this body has no episode producer.
    # THAT IS NO LONGER A NO-OP (fold-2 G-B): an empty stamped set is exactly the FULLY-FLOORED lane's
    # shape, so a one-hop turn whose model writes a window the prompt never carried is now fenced too,
    # in the same fail-closed direction. It ships anyway so a future one-hop episode producer is correct
    # for free and cannot silently diverge from the L2 body, which is the whole of the W4-D3 rationale.
    _espan = _validate_episode_spans(structured, None,
                                     **({"handle_prose": True} if _handles else {}))
    if _handles and _espan.get("section_seen"):                   # ...same stamp rule, both bodies
        _trace_espan = _espan
    else:
        _trace_espan = None
    _fold_ledger_class(verifier, _EPISODE_SPAN_UNBACKED_CLASS,    # ONE strip ledger, both bodies
                       _espan.get("bullets_dropped"))
    # D-HP-12's REMEDY on the SECOND synthesis path, in the SAME position (FIRST, before any splice) and
    # for the same reason it is first on the L2 body. `GRAPHRAG_PLANNER=onehop` is a DOCUMENTED rollback:
    # a lint that only deletes on one of the two bodies is the same defect with a flag in front of it.
    _bdrop = (_drop_bare_digit_sentences(structured, extra_number_calls, verifier, uniq=uniq)
              if (verifier.get("enabled") and _handles) else None)   # T1-6: same `uniq`, both bodies
    _nhandles = (_resolve_number_handles(structured, extra_number_calls,   # D-PQ HANDLE-1, both bodies
                                         handle_prose=_handles)
                 if verifier.get("enabled") else None)                    # ...and the same verifier gate
    if verifier.get("enabled") and _handles:                              # H1 FIX Z1/Z6, both bodies
        _fold_render_classes(verifier, _nhandles)
    _nclone = (_dedup_number_handles(structured, extra_number_calls)       # CYCLE-6 FIX-C, both bodies
               if verifier.get("enabled") else 0)                         # ...and the same verifier gate
    # D-HP-10 + D-HP-14 on the SECOND synthesis path, spelled identically to the L2 body and inserted at
    # the same point in the stack: after the [N] pass and the dedup, BEFORE the prune (ordering pin (b)).
    _phandles = (_resolve_evidence_handles(structured, uniq, handle_prose=_handles)
                 if verifier.get("enabled") else None)
    _wslot = _wrong_slot_audit(_nhandles) if (verifier.get("enabled") and _handles) else None
    _eorph = (_prune_orphan_evidence_handles(structured, verifier, market_register=_mr)         # CYCLE-9 FIX 3, both bodies
              if verifier.get("enabled") else 0)                          # ...and the same verifier gate
    _eslot = (_drop_evidence_value_slot(structured, uniq, verifier)   # D-HP G1 REMEDIATION D2(b), both
              if (verifier.get("enabled") and _handles) else None)   # bodies, the SAME post-prune seat
    _fold_ledger_class(verifier, _E_VALUE_SLOT_CLASS, (_eslot or {}).get("convicted"))
    _egeo = (_drop_evidence_geo_contradiction(structured, uniq, verifier)  # D-HP-25 V2, both bodies,
             if (verifier.get("enabled") and _handles) else None)          # the SAME post-prune seat
    _fold_ledger_class(verifier, _E_GEO_CONTRADICTION_CLASS, (_egeo or {}).get("convicted"))
    _debris = bool(verifier.get("enabled") and _tidy_handle_debris(structured))   # D-PQ HANDLE-3, ditto
    _sorph = (_drop_slot_orphan_sentences(structured, verifier)                   # H1 FIX Z4, both bodies
              if (verifier.get("enabled") and _handles) else None)                # ...same position, after
    _fold_ledger_class(verifier, _SLOT_ORPHAN_CLASS,                              # H1 FIX W2, both bodies
                       (_sorph or {}).get("sentences_dropped"))
    _orphans = bool(verifier.get("enabled")                                       # CYCLE-5 TIDY-2, ditto
                    and _tidy_strip_orphans(structured, verifier))
    # A4b on the SECOND synthesis path, for the SAME reason A4 is here: GRAPHRAG_PLANNER=onehop is a
    # documented rollback, and instrumenting only _answer_l2 would blind the audit on the exact path a
    # rollback puts every turn on. Identical two seams, identical field names.
    _raw_draft = _fold_draft(_raw_draft, sanitize_input_snapshot(
        verified_tldr=structured.get("tldr"), verified_mechanism=structured.get("mechanism")))
    # D-DT-1 on the SECOND synthesis path, at the IDENTICAL four-constraint seam and spelled identically
    # (1.8's one-hop row + the W4-D3 rationale above). `tl.render_line` has exactly ONE call site
    # (_l2_blocks), so this body injects no episode line, `injected` is empty and the scaffold returns {}
    # on every turn today -- which is the point: a future one-hop episode producer is correct for free
    # and cannot silently diverge from the L2 body.
    _scaf_trace = _maybe_scaffold_episodes(structured, verifier, injected=None, nodes=None,
                                           evidence=evidence, n_positional=len(uniq),
                                           market_register=_mr, relevant=_ep_rel,
                                           **_scaffold_cap_kwargs(mode_knobs))   # D-AM-10, both bodies
    _humanize_structured(structured, market_register=_mr)         # clean the fields the UI renders directly (6.1)
    # D-RC-12 on the one-hop body: identical reconcile, identical position (post-verify, post-humanize).
    _tldr_dir = _tldr_direction_trace(structured, graph, contracts)
    if os.environ.get("GRAPHRAG_ANSWER_V2", "off") == "on":       # P9-C typed sections -- the one-hop twin of
        secs = _sectionize(structured.get("mechanism") or "")     # the L2 seam: same post-verify+humanize
        if secs:                                                  # ordering, same per-call flag read
            structured["sections"] = secs
    # CYCLE-10-AMEND (2026-08-08) REVIEW MAJOR 1+2 on the SECOND synthesis path, spelled identically to
    # the L2 body (see the note there for the marker-as-level root cause). GRAPHRAG_PLANNER=onehop is a
    # documented rollback: a footer that only reaches the reader on one of the two bodies is the same
    # defect with a flag in front of it.
    _footer = ""
    if verifier.get("enabled"):                                   # ONE validated source list, model-numbered
        _sanitize_in = render(structured, include_ledger=False)
        _footer = _cited_sources_block(structured, verifier, extra_number_calls, market_register=_mr)
    else:                                                         # verifier off -> legacy two-list rendering
        footer = ("\n\n## Sources\n" + cit.render(ev_cits)) if ev_cits else ""
        _sanitize_in = render(structured) + footer
    _pre_sanitize = _sanitize_in + _footer                        # A4b SEAM 2: the WHOLE page, as before
    body = reg.sanitize(_sanitize_in, market_register=_mr) + _footer   # strips leaked internal tokens
    _raw_draft = _fold_draft(_raw_draft, sanitize_input_snapshot(body_pre_sanitize=_pre_sanitize))
    if degraded:
        body = _DEGRADED_BANNER.format(m=degraded) + body
    return {"answer": body, "structured": structured, "contract": contracts[0],
            "contracts": contracts, "citations": [c.model_dump() for c in ev_cits],
            "evidence": evidence, "model": model,
            "number_calls_full": extra_number_calls,       # CYCLE-7 INSTRUMENT-1, see the note at the L2 body

            "trace": {"routed": routed, "contracts": contracts, "banned_mood_words": _banned_mood,
                      "banned_valuation_words": _banned_val, "banned_flow_words": _banned_flow,
                      "banned_exec_words": _banned_exec, "unbacked_levels": _unbacked,
                      "bare_digit_count": _bare_digits,            # D-HP-4(c): always on, gates nothing
                      "citation_resolved": _typed_resolved(verifier),   # D-HP-4(d), G1 (6)
                      "outlook_mode": _outlook, "market_register": _mr,
                      "record_through": _rec_through,              # D-RC-13: observational, both bodies
                      **({"number_handles": _nhandles}             # D-PQ HANDLE-1: same census, both bodies
                         if _nhandles is not None else {}),        # ...absent when the verifier is off
                      **({"prose_handles": _phandles}              # D-HP-10: same census, both bodies
                         if _phandles is not None else {}),        # ...absent when the verifier is off
                      **({"wrong_slot_audit": _wslot} if _wslot is not None else {}),   # D-HP-14, ditto
                      **({"bare_digit_dropped": _bdrop}            # D-HP-12's remedy, both bodies
                         if (_bdrop and any(_bdrop.values())) else {}),
                      **({"slot_orphan_dropped": _sorph}           # H1 FIX Z4's remedy, both bodies
                         if (_sorph and any(_sorph.values())) else {}),
                      **({"episode_spans_validated": _trace_espan}  # D-HP-15 SELECT, both bodies
                         if _trace_espan is not None else {}),      # ...absent on every control row
                      **({"number_rows_deduped": _nclone} if _nclone else {}),  # CYCLE-6 FIX-C, both bodies
                      **({"evidence_orphans_pruned": _eorph} if _eorph else {}),  # CYCLE-9 FIX 3, ditto
                      **({"evidence_slot_dropped": _eslot}         # D-HP G1 REMEDIATION D2(b), both
                         if (_eslot and any(_eslot.values())) else {}),          # bodies, same stamp rule
                      **({"evidence_geo_dropped": _egeo}           # D-HP-25 V2, both bodies, the SAME
                         if (_egeo and any(_egeo.values())) else {}),   # absent-not-null stamp rule
                      **({"prose_debris_tidied": True} if _debris else {}),   # D-PQ HANDLE-3, both bodies
                      **({"prose_orphans_tidied": True} if _orphans else {}),  # CYCLE-5 TIDY-2, both bodies
                      **({"response_contract": _rc_active} if _rc_active else {}),   # Phase B twin stamp
                      **({"composition_census": _census} if _census is not None else {}),   # D-CC-1 twin
                      **_tldr_dir,                                 # D-RC-12: absent when the flag is off
                      "fork_basis": _fork_basis_v,                 # D-DT-2 c1 (V-9): the SECOND mint site
                      "n_drivers": sum(len(graph.contracts[c].drivers) for c in contracts), "regimes": regimes,
                      "drivers": drivers, "n_driver_evidence": len(driver_hits),
                      "evidence_ids": ev_ids, "has_diagram": _valid_mermaid(structured.get("diagram_mermaid")),
                      **({"degraded_model": degraded} if degraded else {}),
                      **({"synth_usage": _synth_usage} if _synth_usage else {}),   # D-AM-4
                      **({"plan_tokens": _plan_tok}                # A3, both bodies: a COUNT, never the text
                         if _plan_tok is not None else {}),        # ...absent on every control row
                      **({"raw_draft": _raw_draft} if _raw_draft else {}),   # A4, audited runs only
                      **_scaf_trace,                               # D-DT-1: absent when the flag is off
                      "citation_verifier": verifier, "model": model}}
