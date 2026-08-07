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


# P9-B: appended to the mentor persona ONLY when GRAPHRAG_CASCADE_QUANT is on -- the quantify loop supplies
# the [N] rows, so (unlike Phase A) a [N]-cited dated lag is backed and will NOT be stripped.
_SYSTEM_CASCADE = (
    "\nOBSERVED CASCADE NUMBERS. When an 'OBSERVED CASCADE NUMBERS' block is present, narrate the record from "
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
    its OWN default-off flag rather than riding this one."""
    if os.environ.get("GRAPHRAG_STRIP_AUDIT", "off") == "off":
        return None
    snap = {k: str(v) for k, v in parts.items() if v}
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
    `_psd_component_rows` (silver_psd, reached five deep through the RV2/transmission engines),
    cascade's `_cot_outcome_read` (gold_cot_outcomes), and silverleg's `_rows` (whose three callers pass
    silver_psd / silver_fred_fx / silver_noaa_oni as literals). Every one of those names its table as a
    literal and no such card declares `contract_month_col`, so `_newest_first_applies` is structurally
    False there and a threaded flag could not move one byte of their SQL. All of it is pinned in
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


def _system(*, outlook: bool = False, episodes: bool | None = None, recency: bool = False,
            response_contract: str | None = None, budget: str | None = None,
            census: dict | None = None) -> str:
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
    if _pattern_records_on():
        from leviathan.graphrag.numbers import pattern_records as _pr   # lazy: avoid an import cycle
        base = base + _pr.RECORDED_HISTORY_ADDENDUM
    if episodes is None:                                           # no prompt to inspect -> the FLAG leg only
        episodes = _timeline_on()                                  #   (a floor, not the seam invariant)
    if episodes:                                                   # W4-D3: the reserved '## Episodes' heading
        base = base + _SYSTEM_EPISODES
    if outlook:                                                    # W5-D5: the reserved '## Outlook' heading
        base = base + _SYSTEM_OUTLOOK
    if recency:                                                    # D-RC-13: dating discipline (flag resolved
        base = base + _SYSTEM_RECENCY                              #   by the caller's seam, threaded DOWN)
    base = base + _rc.directive(response_contract, census=census)  # D-RC Phase B: emphasis LAST ('' for
    return base                                                    #   default/None -- the fail-open pin)


_SYSTEM = _SYSTEM_MENTOR                                              # module-level default (importers/tests)


def route(query: str, graph: gph.CausalGraph) -> list[str]:
    """TIER 1 (lexical): contracts whose id/aliases/commodity-token appear in the query (accent/case-insensitive),
    most-hits first. Fast + precise, but blind to coreference/paraphrase ('a frost in Brazil', 'that contract')."""
    scored = []
    for cid, c in graph.contracts.items():
        forms = [cid, cid.replace("_", " ")] + list(c.aliases) + cid.split("_")
        m = hv.build_matcher(forms)
        n = len(m.findall(query))
        if n:
            scored.append((n, cid))
    return [cid for _, cid in sorted(scored, reverse=True)]


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
    exposed to the dollar') by mapping the question to ids from the tracked list."""
    call = call or _call_opus
    ids = list(graph.contracts)
    sys = ("Map a commodities question to the tracked futures-contract id(s) it concerns. Resolve coreference and "
           "comparisons. Return ONLY ids from the provided list, the 1-2 most relevant, via pick_contracts.")
    user = f"TRACKED CONTRACTS: {ids}\n\nQUESTION: {query}"
    out = call(sys, user, model=ex.HAIKU, tool=_route_llm_tool())
    return [c for c in (out.get("contracts") or []) if c in graph.contracts][:k]


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


def _ev_block(evidence: list[dict]) -> str:
    def _one(e: dict) -> str:
        head = f"[T{source_tier(e['source'])}] ({e['source']}, reported {e['date']}"
        ev_dt = _usable_date(e.get("event_date"))
        if ev_dt and ev_dt != str(e["date"])[:10]:             # WS-MS6: show WHEN the event happened vs was reported
            head += f"; event {ev_dt}"
        head += ")"
        drv = f" {{driver: {e['driver']}}}" if e.get("driver") else ""   # cross-cutting cascade trigger
        return f"- {head}{drv} {e['text']}"
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


def _l2_blocks(sg, graph: gph.CausalGraph, asof: str | None = None, order: list | None = None) -> list[str]:
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
    cache prefix; everything per-turn (convergence state, active lists, retrieved evidence) is volatile."""
    stable: list[str] = []
    volatile: list[str] = []
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
            lines.append(f"REACHED VIA CASCADE HOP: {e.get('_from')} --{e.get('relation')}({e.get('sign')})--> {cid}"
                         f" [{kind}: {note}] {e.get('mechanism') or ''}")
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
                vlines.append(f"--- DATED EVIDENCE for {cid} ---\n" + _ev_block(n.evidence))
            elif n.kind == "driver" and n.evidence:
                vlines.append(f"--- DATED EVIDENCE for driver {n.id} ---\n" + _ev_block(n.evidence))
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
    sg = pl.grounded_subgraph(query, graph, route_fn=lambda q, g: routed,
                              **_rm.walk_kwargs(mode_knobs))
    if focus_driver and not any(n.kind == "driver" and n.id == focus_driver for n in sg.nodes):
        for cid in sg.seeds:                                       # first seed contract that carries the driver
            if any(d.id == focus_driver for d in graph.contracts[cid].drivers):
                node = pl.GroundedNode(kind="driver", id=focus_driver, contract=cid, depth=1, relevance=1.0)
                node.prior = pl._prior(graph, node)
                sg.nodes.append(node)
                sg.trace.setdefault("kept", []).append(list(node.key))
                sg.trace["focus_driver"] = focus_driver
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
    pl.ground(sg, query, graph, retrieve=retr, silver_lookup=silver_lookup, asof=asof, near=near,
              probe_retrieve=probe_retr, on_stage=on_stage,       # probes = cheap existence checks, no reranker
              **_rm.ground_kwargs(mode_knobs))                    # D-AM-10: {} unless a mode is honored
    _gm = sg.trace.get("ground_ms") or {}
    _emit(on_stage, "walking", nodes=len(sg.nodes), regimes=len(sg.fired_regimes),
          ms_fill=_gm.get("fill"), ms_rest=_gm.get("rest"))
    _emit(on_stage, "retrieving", props=int(sg.trace.get("n_evidence", 0) or 0))
    contracts = sg.seeds
    # D-DV-2 presentation order, resolved ONCE and consumed by BOTH the render below and the flat
    # evidence list further down -- two derivations of the same sequence is how they drift apart.
    _ev_order = _render_order(sg.nodes, (mode_knobs or {}).get("order_policy"))
    stable_blocks, volatile_blocks = _l2_blocks(sg, graph, asof=asof, order=_ev_order)
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
            _cblock, _quant_trace, _reroute_trace = cq.quantify(sg, graph, qfn=numbers_lookup, asof=asof,
                                                                near=near,
                                                                extra_number_calls=extra_number_calls,
                                                                xc_request=xc_request, comove=_comove_on(),
                                                                price_request=_price_request,
                                                                **_pace_kw, **_chain_kw, **_xmit_kw,
                                                                **_hl_kw, **_ol_kw, **_epo_kw, **_cto_kw,
                                                                **_fnf_kw)
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
    # Stays in the VOLATILE tail (never the cached constant) so the cache prefix is unchanged. n_ev is a
    # PRE-dedup overcount of graph-node evidence (answer.py dedups below) -- a loose cap that can never
    # SUPPRESS a legit [E], only forbid an invented one; it binds HARD only when n_ev == 0 (a dark chain).
    n_ev = sum(len(getattr(n, "evidence", []) or []) for n in sg.nodes)
    n_num = len(extra_number_calls or [])
    sg.trace["injected_n"] = n_num                               # W6.1-0: [N] rows injected (cited-vs-injected denom)
    _ledger_line = (
        f"GROUNDING LEDGER: {n_ev} dated evidence item(s) and {n_num} observed number row(s) are "
        f"available for this question. Cite AT MOST {n_ev} distinct [E] handles, each mapping to one "
        f"item above; " + ("emit NO [N] handles (there are no number rows)."
                           if n_num == 0 else f"[N] handles run [N1]..[N{n_num}]."))
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
    call_kw = {"on_token": on_token} if (on_token is not None and call is _call_opus) else {}
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
                              response_contract=_rc_active, budget=_mode_budget(_rc_active, mode_knobs),
                              census=_census),                    # D-CC-1: None on every dark turn
                      _pack(sp, vp, use_blocks), model=model, tool=_answer_tool(), **call_kw)
    sg.trace["ms_synth_llm"] = int((time.perf_counter() - _t_synth) * 1000)
    _banned_mood = _count_banned_mood(structured)                 # P9-A: RAW output, pre-sanitize (see helper)
    _banned_val = _count_banned_valuation(structured)             # DP-6: valuation/flow raw counts, pre-sanitize
    _banned_flow = _count_banned_flow(structured)
    _banned_exec = _count_banned_exec(structured)                 # W5: A2 execution idioms, RAW (pinned 0 always)
    _unbacked = _count_unbacked_levels(structured)                # W5.0: bare price levels, RAW (derivation gate)
    # A4: the counters above are computed HERE and the draft they were computed on is destroyed BELOW --
    # verify_citations mutates `structured` in place, _humanize_structured rewrites it, sanitize cleans the
    # render. Snapshot it while it still exists (flag-gated; None -> the key is absent, not null).
    _raw_draft = raw_draft_snapshot(tldr=structured.get("tldr"), mechanism=structured.get("mechanism"))
    degraded = _pop_degraded(structured)
    _synth_usage = _pop_usage(structured)                         # D-AM-4: same pop channel, both bodies
    if sg.mermaid and _valid_mermaid(sg.mermaid):
        structured["diagram_mermaid"] = sg.mermaid                # deterministic diagram overrides the LLM's
    evidence = [{**h, "contract": n.contract} for n in _ev_order for h in n.evidence]
    seen_docs, uniq = set(), []
    for h in evidence:
        sk = h.get("source_key")
        if sk and sk not in seen_docs:
            seen_docs.add(sk)
            uniq.append(h)
    ev_cits = cit.unify(uniq, extra_number_calls)                 # machine-readable list (UI drill-down)
    from leviathan.graphrag import verify as vf
    # D-DV-1c: the RENDERED contract set, not sg.seeds. _l2_blocks builds a context block for EVERY walk
    # contract including cross-commodity hops, so a hop's regime names are SHOWN to the model as legitimate
    # structure -- and were then stripped on sight as "foreign". A latent bug that deep (3 seeds + tracked
    # hops) amplifies. `contracts` stays sg.seeds everywhere else: that is the ANSWER's scope, not the
    # prompt's.
    verifier = vf.verify_citations(structured, evidence, extra_number_calls,
                                   foreign_names=_foreign_regime_names(
                                       graph, sorted({n.contract for n in sg.nodes})))
    _emit(on_stage, "verifying", checked=int(verifier.get("checked", 0) or 0),
          stripped=int(verifier.get("stripped", 0) or 0))
    # F7 `verified`: the verifier is DONE, so the streamed draft's citation handles are now reconcilable —
    # this is the ONLY signal that permits the UI to ACTIVATE them (RCA F7c: the `token` draft is
    # PRE-verifier, and strips run p50 1 / p90 7 / max 16, so a handle activated earlier could disappear).
    _emit(on_stage, "verified", strips=int(verifier.get("stripped", 0) or 0))
    _attach_provenance(structured, verifier)                     # stamp source_key for durable chip join (6.4)
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
    if verifier.get("enabled"):                                   # ONE validated source list, model-numbered
        _pre_sanitize = (render(structured, include_ledger=False)
                         + _cited_sources_block(structured, verifier, extra_number_calls))
    else:                                                         # verifier off -> legacy two-list rendering
        footer = ("\n\n## Sources\n" + cit.render(ev_cits)) if ev_cits else ""
        _pre_sanitize = render(structured) + footer
    # A4b SEAM 2: the assembled body on its way INTO the render-seam sanitize. Both branches now name the
    # same local and ONE sanitize call consumes it -- same arguments, same register, same output bytes.
    # This pass is the only one that ever sees the cited-sources block and the numbers footer, so it is
    # the only place a leak living OUTSIDE tldr/mechanism (which the raw counters never scan) can be seen.
    body = reg.sanitize(_pre_sanitize, market_register=_mr)
    _raw_draft = _fold_draft(_raw_draft, sanitize_input_snapshot(body_pre_sanitize=_pre_sanitize))
    if degraded:
        body = _DEGRADED_BANNER.format(m=degraded) + body
    return {"answer": body, "structured": structured, "contract": contracts[0] if contracts else None,
            "contracts": contracts, "citations": [c.model_dump() for c in ev_cits], "evidence": evidence,
            "model": model, "trace": {"planner": "l2", "fired_regimes": sg.fired_regimes,
                                      "citation_verifier": verifier, "banned_mood_words": _banned_mood,
                                      "banned_valuation_words": _banned_val, "banned_flow_words": _banned_flow,
                                      "banned_exec_words": _banned_exec, "unbacked_levels": _unbacked,
                                      "outlook_mode": _outlook, "market_register": _mr,
                                      **({"degraded_model": degraded} if degraded else {}),
                                      **({"synth_usage": _synth_usage} if _synth_usage else {}),   # D-AM-4
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


def _answer_tool() -> dict:
    s = {"type": "string"}
    return {"name": "emit_answer", "description": "Emit the reader-first structured answer.",
            "input_schema": {"type": "object", "properties": {
                "tldr": s, "mechanism": s, "diagram_mermaid": s,
                "sources": {"type": "array", "items": {"type": "object", "properties": {
                    "ref": {"type": "integer"}, "source": s, "date": s, "note": s}}}},
                "required": ["tldr", "mechanism", "sources"]}}


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
    parts = [f"**TL;DR.** {(d.get('tldr') or '').strip()}", "", f"**Why.** {(d.get('mechanism') or '').strip()}"]
    if _valid_mermaid(d.get("diagram_mermaid")):
        parts += ["", "**Cascade / convergence**", "```mermaid", d["diagram_mermaid"].strip(), "```"]
    srcs = d.get("sources") or []
    if srcs and include_ledger:
        parts += ["", "**Sources**"] + [f"[{x.get('ref')}] {x.get('source')} · {x.get('date')} — {x.get('note', '')}"
                                         for x in srcs]
    return "\n".join(parts).strip()


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
    answer only when even this form does not survive."""
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
        return {"episodes_scaffolded": {"fired": False, "n_bullets": 0, "n_receipted": 0},
                "episodes_model_authored": True}

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
        plan.append((span, node, ref, str(receipt.get("date"))[:10],
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


def _cited_sources_block(d: dict, vreport: dict, number_calls: list | None) -> str:
    """The single reader-facing `## Sources` list: the model's OWN handles, every entry resolved by the
    verifier to a real item's true metadata. Cited-only — retrieved-but-uncited items stay machine-side
    (res['evidence'] / res['citations'])."""
    resolved = (vreport or {}).get("resolved") or {}
    lines, seen = [], set()
    for s in (d.get("sources") or []):
        ref = str(s.get("ref", "")).strip().strip("[]")
        if not ref or ref in seen:
            continue
        seen.add(ref)
        if ref.upper().startswith("N"):
            try:
                idx = int(ref[1:])
                c = cit.from_number((number_calls or [])[idx - 1], idx)
                lines.append(f"[{ref}] {c.label}" + (f"  [known {c.date}]" if c.date else ""))
            except (ValueError, IndexError):
                continue
        elif ref in resolved:
            r = resolved[ref]
            from leviathan.graphrag import display as dp
            lines.append(f"[{ref}] {dp.source_name(str(r.get('source') or ''))} "
                         f"({r.get('date')}): {r.get('snippet')}")
    return ("\n\n## Sources\n" + "\n".join(lines)) if lines else ""


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
               max_tokens: int | None = None) -> dict:
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
    # max_tokens: TURN default 6000 (citv2 lost a turn to truncation at 4096; 6000 is headroom, not
    # spend). Callers composing DOCUMENTS (dossier.synthesize) pass their own ceiling -- forwarded
    # only when provided, mirroring `temperature` exactly.
    kw = dict(model=pv.resolve_model(model), max_tokens=max_tokens or 6000, tool=tool,
              degrade_to=ex.HAIKU, usage_sink=_sink)  # answers grew
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
    if model == SONNET:
        import os as _os
        model = (_os.environ.get("GRAPHRAG_SYNTH_MODEL")
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
    routed = route_fn(query, graph)
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
    stable_blocks, volatile_blocks, evidence, ev_ids, regimes = [], [], [], [], []
    for c in contracts:
        hits = retrieve(query, ev.node_for(c), k=k, asof=asof, near=near)   # variants share a commodity-node slice
        stable_blocks.append(_context_block(graph, c))             # byte-stable per contract -> cache prefix
        volatile_blocks.append(f"--- DATED EVIDENCE for {c} ---\n" + _ev_block(hits))
        evidence += [{**h, "contract": c} for h in hits]
        ev_ids += [h["source_key"] for h in hits]
        regimes += [s.name for s in graph.contracts[c].convergence]
    # WS-MS6: cross-cutting driver/cascade evidence (the B40/freight/FX/El Nino triggers the commodity slices drop)
    drivers = _active_drivers(query, contracts, graph) if ev.driver_specs() else []
    driver_hits = _driver_evidence(query, drivers, k=_DRIVER_K, asof=asof, near=near, retrieve_fn=driver_retrieve)
    if driver_hits:
        volatile_blocks.append("--- CROSS-CUTTING DRIVER EVIDENCE (cascade/convergence triggers; tie to silver) ---\n"
                               + _ev_block(driver_hits))
        evidence += [{**h, "contract": "(driver)"} for h in driver_hits]
    if extra_context:                                              # hybrid numbers / conversation state (volatile)
        volatile_blocks.append(extra_context)
    # D-RC-13 on the one-hop body: this body has no GROUNDING LEDGER line, so the record-edge sentence
    # rides its own volatile block (same text, same flag, '' when off -> byte-identical assembly).
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
    structured = call(_system(outlook=_outlook, episodes=_episodes, recency=_recency_stamp_on(),
                              response_contract=_rc_active,
                              budget=_mode_budget(_rc_active, mode_knobs),    # D-AM-10, both bodies
                              census=_census),                                # D-CC-1, both bodies
                      _pack(sp, vp, use_blocks), model=model, tool=_answer_tool())
    _banned_mood = _count_banned_mood(structured)                 # P9-A: RAW output, pre-sanitize
    _banned_val = _count_banned_valuation(structured)             # DP-6: valuation/flow raw counts, pre-sanitize
    _banned_flow = _count_banned_flow(structured)
    _banned_exec = _count_banned_exec(structured)                 # W5: A2 execution idioms, RAW (pinned 0 always)
    _unbacked = _count_unbacked_levels(structured)                # W5.0: bare price levels, RAW (derivation gate)
    # A4 on the SECOND synthesis path. There is no single choke point -- verify_citations is called from
    # _answer_l2 AND from here, and this is the documented GRAPHRAG_PLANNER=onehop rollback lane. Snapshotting
    # only the L2 body would leave the fallback with no raw draft, i.e. a silent hole in the audit exactly on
    # the path a rollback puts every turn on.
    _raw_draft = raw_draft_snapshot(tldr=structured.get("tldr"), mechanism=structured.get("mechanism"))
    degraded = _pop_degraded(structured)
    _synth_usage = _pop_usage(structured)                         # D-AM-4: same pop channel, both bodies
    # unified provenance footer (Phase 4): document-level, deduped by source_key. Numbers citations join here in
    # the Phase-5 hybrid path; the per-prop page/char slots ride along for the page-citation recovery.
    seen_docs, uniq = set(), []
    for h in evidence:
        sk = h.get("source_key")
        if sk and sk not in seen_docs:
            seen_docs.add(sk)
            uniq.append(h)
    ev_cits = cit.unify(uniq, extra_number_calls)                 # machine-readable list (UI drill-down)
    from leviathan.graphrag import verify as vf
    verifier = vf.verify_citations(structured, evidence, extra_number_calls,
                                   foreign_names=_foreign_regime_names(graph, contracts))
    _emit(on_stage, "verifying", checked=int(verifier.get("checked", 0) or 0),
          stripped=int(verifier.get("stripped", 0) or 0))
    _emit(on_stage, "verified", strips=int(verifier.get("stripped", 0) or 0))   # F7: handles may ACTIVATE now
    _attach_provenance(structured, verifier)                     # stamp source_key for durable chip join (6.4)
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
    if verifier.get("enabled"):                                   # ONE validated source list, model-numbered
        _pre_sanitize = (render(structured, include_ledger=False)
                         + _cited_sources_block(structured, verifier, extra_number_calls))
    else:                                                         # verifier off -> legacy two-list rendering
        footer = ("\n\n## Sources\n" + cit.render(ev_cits)) if ev_cits else ""
        _pre_sanitize = render(structured) + footer
    body = reg.sanitize(_pre_sanitize, market_register=_mr)       # strips leaked internal tokens
    _raw_draft = _fold_draft(_raw_draft, sanitize_input_snapshot(body_pre_sanitize=_pre_sanitize))
    if degraded:
        body = _DEGRADED_BANNER.format(m=degraded) + body
    return {"answer": body, "structured": structured, "contract": contracts[0],
            "contracts": contracts, "citations": [c.model_dump() for c in ev_cits],
            "evidence": evidence, "model": model,
            "trace": {"routed": routed, "contracts": contracts, "banned_mood_words": _banned_mood,
                      "banned_valuation_words": _banned_val, "banned_flow_words": _banned_flow,
                      "banned_exec_words": _banned_exec, "unbacked_levels": _unbacked,
                      "outlook_mode": _outlook, "market_register": _mr,
                      "record_through": _rec_through,              # D-RC-13: observational, both bodies
                      **({"response_contract": _rc_active} if _rc_active else {}),   # Phase B twin stamp
                      **({"composition_census": _census} if _census is not None else {}),   # D-CC-1 twin
                      **_tldr_dir,                                 # D-RC-12: absent when the flag is off
                      "fork_basis": _fork_basis_v,                 # D-DT-2 c1 (V-9): the SECOND mint site
                      "n_drivers": sum(len(graph.contracts[c].drivers) for c in contracts), "regimes": regimes,
                      "drivers": drivers, "n_driver_evidence": len(driver_hits),
                      "evidence_ids": ev_ids, "has_diagram": _valid_mermaid(structured.get("diagram_mermaid")),
                      **({"degraded_model": degraded} if degraded else {}),
                      **({"synth_usage": _synth_usage} if _synth_usage else {}),   # D-AM-4
                      **({"raw_draft": _raw_draft} if _raw_draft else {}),   # A4, audited runs only
                      **_scaf_trace,                               # D-DT-1: absent when the flag is off
                      "citation_verifier": verifier, "model": model}}
