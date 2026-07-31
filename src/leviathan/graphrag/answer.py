"""Grounded answer orchestrator for graphdev (GRAPHRAG_PLAN v2 Phase 2 WS-3).

Routes a question to a contract (or two), assembles the causal subgraph (drivers / regimes / cross-links /
silver status) + retrieved dated evidence, and a CHEAP serving model (Sonnet by default — Opus built the
brain once, Sonnet serves it) emits a READER-FIRST structured answer via forced tool: a prose TL;DR, a prose
mechanism, a mermaid cascade/convergence diagram ONLY when the question warrants it, and consolidated
citations. `retrieve`/`call` are injectable so tests run without S3/Bedrock/Anthropic."""
from __future__ import annotations

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
#   SLOT 2, MAGNITUDE. There is NO per-episode price engine. The only historical price surface a turn
#     injects is the SEAM-B WASDE avg_farm_price marketing-year pair (numbers/cascade.py ~2020-2075): at
#     most ONE pair per turn, on ONE derived focus window, declined outright on a market-price or non-US
#     slug. So the ABSENCE MARKER IS THE DEFAULT and the [N] branch is the exception -- and because the
#     _NO_PRICE_RECORD vocabulary is TURN-scoped ("no observed magnitude"), not coverage-scoped, it is
#     legitimate on an IN-FLOOR episode too, not only on a pre-price-floor one.
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
    "\nDATED EPISODES -- THE '## Episodes' SECTION. When one or more 'DATED EPISODES' lines are present, "
    "ENUMERATE them in a dedicated '## Episodes' section. Render '## Episodes' ONLY when a 'DATED "
    "EPISODES' line is present -- the section exists solely when the prompt supplies the episodes; never "
    "volunteer an episode list from prose, and never add an episode the lines do not carry. The DATED "
    "EPISODES rule above still holds in full: those lines are REPORT TIMESTAMPS, not descriptions, so do "
    "NOT manufacture severity, outcomes, or magnitudes from a bare count or date -- enumerating a window "
    "is not narrating it.\n"
    "HEADING: exactly '## Episodes' -- level two, that word alone, no count suffix and no dash suffix, "
    "never inside a code fence. Place it AFTER '## The record' and BEFORE '## What to watch'. The section "
    "holds ONE '- ' bullet per injected episode and NOTHING else: no lead-in sentence, no closing prose.\n"
    "EVERY INJECTED EPISODE GETS ITS OWN BULLET, including the ones with no citable item. Never drop an "
    "episode for being thin, never merge two into one bullet, and never invent one to round out the list.\n"
    "EACH BULLET HAS THIS SHAPE, and BOTH slots are REQUIRED:\n"
    "  - <YYYY-MM>..<YYYY-MM> -- <plain-words label>: <BACKING>; <MAGNITUDE>.\n"
    "Write the span with FULL four-digit years on BOTH ends, joined by the two-dot glyph '..' -- NEVER an "
    "arrow, which this system reads as derived arithmetic and strips.\n"
    "ONE BULLET IS ONE PHYSICAL LINE. Keep the span, the label, the backing and the magnitude on the SAME "
    "line, however long it runs -- never wrap a bullet onto a continuation line and never break one across "
    "two '- ' items. A bullet is read line by line, so anything pushed onto a second line is not read as "
    "part of that episode.\n"
    "BACKING (first slot) is EITHER one clause restating what a cited dated item inside that window "
    "actually says, carrying that item's [E] handle, OR -- when the injected episode says NO CITABLE ITEM "
    "IN THIS WINDOW -- the absence itself, in these words: 'no citable item', 'no dated source', or 'the "
    "corpus is silent'. An [N] handle does NOT fill this slot. Restate a TERM FROM THE RECEIPT the "
    "injected line showed you; a clause that shares no wording with the item it cites is dropped as "
    "unverifiable.\n"
    "MAGNITUDE (second slot) is EITHER the price move with its [N] handle, when an injected number row "
    "actually covers that window, OR an explicit statement that none does, in these words: 'no observed "
    "magnitude for this window', 'no priced move', or 'no price record for this window'. THE ABSENCE IS "
    "THE NORMAL CASE -- no per-episode price history is served here, so most episodes have no magnitude "
    "and saying so plainly IS the correct answer; an invented move, or an empty slot, is not. A magnitude "
    "is an [N] HANDLE, never a bare numeral.\n"
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
    "CASE 1 -- no citable item and no price row (the common case, both slots ABSENT):\n"
    "- YYYY-MM..YYYY-MM -- <what the window is, in plain words>: no citable item in this window, so what "
    "happened is not narrated; no price record for this window.\n"
    "CASE 2 -- receipted but unpriced (backing from the receipt, magnitude absent):\n"
    "- YYYY-MM..YYYY-MM -- <what the window is, in plain words>: <one clause restating what the cited "
    "in-window item actually says, reusing its wording> [E<k>]; no observed magnitude for this window.\n"
    "CASE 3 -- receipted AND priced (rare; only when an injected number row really covers the window):\n"
    "- YYYY-MM..YYYY-MM -- <what the window is, in plain words>: <one clause restating the cited item> "
    "[E<k>], with the season-average farm price across those marketing years at [N<k>].\n"
    "Stating an absence is the record, not a hedge -- and having enumerated these windows honestly, do "
    "NOT smooth the same episodes into a confident generalisation ('frosts usually ...') elsewhere in "
    "the note.")


def _system(*, outlook: bool = False, episodes: bool | None = None) -> str:
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
    Read PER CALL, never memoized: a serving process is long-lived, so a once-at-import read would
    make the env-flip rollback a silent no-op until a redeploy — defeating the gate's purpose."""
    if os.environ.get("GRAPHRAG_MENTOR_VOICE", "on") == "off":
        return _SYSTEM_LEGACY
    base = _SYSTEM_MENTOR
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
    return base


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


def _l2_blocks(sg, graph: gph.CausalGraph, asof: str | None = None) -> list[str]:
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
    fired_by = {}
    for r in sg.fired_regimes:
        fired_by.setdefault(r["contract"], []).append(r)
    for cid in dict.fromkeys(n.contract for n in sg.nodes):
        cnode = next((n for n in sg.by_contract(cid) if n.kind == "contract"), None)
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
        evidenced = [n.id for n in sg.by_contract(cid) if n.kind == "driver" and n.evidence]
        named_only = [n.id for n in sg.by_contract(cid) if n.kind == "driver" and n.active and not n.evidence]
        if evidenced:
            vlines.append(f"DRIVERS WITH DATED SLICE EVIDENCE: {evidenced}")
        if named_only:
            vlines.append(f"DRIVERS MERELY NAMED IN PASSING (weak signal — no dedicated evidence): {named_only}")
        for n in sg.by_contract(cid):                              # dated evidence + silver, per grounded node
            if n.kind == "contract" and n.evidence:
                vlines.append(f"--- DATED EVIDENCE for {cid} ---\n" + _ev_block(n.evidence))
            elif n.kind == "driver" and n.evidence:
                vlines.append(f"--- DATED EVIDENCE for driver {n.id} ---\n" + _ev_block(n.evidence))
            if n.episodes:                                         # timeline layer: dated occurrences <= asof
                from leviathan.graphrag import timeline as tl
                _ep_line = tl.render_line(n.id, n.episodes)
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
                sg.trace.setdefault("episodes_injected", []).append(
                    {"node": n.id, "line": _ep_line,
                     "spans": [f"{e['start'][:7]}..{e['end'][:7]}" for e in n.episodes]})
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
               outlook: bool = False) -> dict:
    """L2 serving path: walk + ground the subgraph, hand it to the reasoner, and OVERRIDE the diagram with the
    graph-derived cascade. Reuses the shared render + unified footer + sanitizer. The hybrid branch's silver
    numbers ride in exactly as on the one-hop path: extra_context as a prompt block, extra_number_calls into
    the unified footer. `focus_driver` (the live-event cascade root, section 7.1) is force-included in the
    subgraph so the cascade is grounded from the event even when the walk wouldn't have kept it.
    `use_blocks` (real serving call only) sends (stable, volatile) for prompt-cached content blocks."""
    from leviathan.graphrag import planner as pl
    retr = retrieve or functools.partial(ev.retrieve, **_RETRIEVAL)
    sg = pl.grounded_subgraph(query, graph, route_fn=lambda q, g: routed)
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
              probe_retrieve=probe_retr, on_stage=on_stage)       # probes = cheap existence checks, no reranker
    _gm = sg.trace.get("ground_ms") or {}
    _emit(on_stage, "walking", nodes=len(sg.nodes), regimes=len(sg.fired_regimes),
          ms_fill=_gm.get("fill"), ms_rest=_gm.get("rest"))
    _emit(on_stage, "retrieving", props=int(sg.trace.get("n_evidence", 0) or 0))
    contracts = sg.seeds
    stable_blocks, volatile_blocks = _l2_blocks(sg, graph, asof=asof)
    if extra_resolver is not None:                                # numbers ∥ walk JOIN (run_hybrid): the walk is
        extra_context, extra_number_calls = extra_resolver()      # done — collect the numbers thread's output now
    if extra_context:                                             # hybrid numbers / conversation state (volatile)
        volatile_blocks = volatile_blocks + [extra_context]
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
            _cblock, _quant_trace, _reroute_trace = cq.quantify(sg, graph, qfn=numbers_lookup, asof=asof,
                                                                near=near,
                                                                extra_number_calls=extra_number_calls,
                                                                xc_request=xc_request, comove=_comove_on(),
                                                                price_request=_price_request,
                                                                **_pace_kw, **_chain_kw, **_xmit_kw)
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
    # W5-D3/D5: the outlook legs were resolved by the caller (plan.answer_mode_outlook AND
    # is_outlook_explicit); the kill-switch is ANDed HERE, at the seam. `_mr` is the ONLY thing that ever
    # relaxes the register, and it is passed DOWN as an argument -- register.py reads no environment.
    _outlook = bool(outlook) and _outlook_on()
    _mr = reg.OUTLOOK if _outlook else reg.FENCED
    _episodes = _episodes_on(vp)                                  # W4-D3: BOTH legs, and both in CODE
    structured = call(_system(outlook=_outlook, episodes=_episodes), _pack(sp, vp, use_blocks), model=model,
                      tool=_answer_tool(), **call_kw)
    sg.trace["ms_synth_llm"] = int((time.perf_counter() - _t_synth) * 1000)
    _banned_mood = _count_banned_mood(structured)                 # P9-A: RAW output, pre-sanitize (see helper)
    _banned_val = _count_banned_valuation(structured)             # DP-6: valuation/flow raw counts, pre-sanitize
    _banned_flow = _count_banned_flow(structured)
    _banned_exec = _count_banned_exec(structured)                 # W5: A2 execution idioms, RAW (pinned 0 always)
    _unbacked = _count_unbacked_levels(structured)                # W5.0: bare price levels, RAW (derivation gate)
    degraded = _pop_degraded(structured)
    if sg.mermaid and _valid_mermaid(sg.mermaid):
        structured["diagram_mermaid"] = sg.mermaid                # deterministic diagram overrides the LLM's
    evidence = [{**h, "contract": n.contract} for n in sg.nodes for h in n.evidence]
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
    # F7 `verified`: the verifier is DONE, so the streamed draft's citation handles are now reconcilable —
    # this is the ONLY signal that permits the UI to ACTIVATE them (RCA F7c: the `token` draft is
    # PRE-verifier, and strips run p50 1 / p90 7 / max 16, so a handle activated earlier could disappear).
    _emit(on_stage, "verified", strips=int(verifier.get("stripped", 0) or 0))
    _attach_provenance(structured, verifier)                     # stamp source_key for durable chip join (6.4)
    _humanize_structured(structured, market_register=_mr)         # clean the fields the UI renders directly (6.1)
    if os.environ.get("GRAPHRAG_ANSWER_V2", "off") == "on":       # P9-C typed sections: a DERIVED view of the
        secs = _sectionize(structured.get("mechanism") or "")     # FINAL prose (post-verify+humanize); read per
        if secs:                                                  # call so the env-flip rollback stays live
            structured["sections"] = secs
    if verifier.get("enabled"):                                   # ONE validated source list, model-numbered
        body = reg.sanitize(render(structured, include_ledger=False)
                            + _cited_sources_block(structured, verifier, extra_number_calls),
                            market_register=_mr)
    else:                                                         # verifier off -> legacy two-list rendering
        footer = ("\n\n## Sources\n" + cit.render(ev_cits)) if ev_cits else ""
        body = reg.sanitize(render(structured) + footer, market_register=_mr)
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


def _call_opus(system: str, user, *, model: str, tool: dict, on_token=None, temperature=None) -> dict:
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
    kw = dict(model=pv.resolve_model(model), max_tokens=6000, tool=tool, degrade_to=ex.HAIKU)  # answers grew
    # (sources block + per-hop citations): citv2 lost a turn to truncation at 4096; 6000 is headroom, not spend
    if on_token is not None:
        out, degraded = pv.serving_call_stream(client, sys_blocks, user, on_token=on_token, **kw)
    else:
        if temperature is not None:
            kw["temperature"] = temperature    # dispatch-only kw (D18); dropped if ever paired with on_token
        out, degraded = pv.serving_call(client, sys_blocks, user, **kw)
    if degraded and isinstance(out, dict):
        out["_degraded_model"] = degraded          # popped by the consumer -> visible caveat + trace
    return out


def answer(query: str, *, graph: gph.CausalGraph, model: str = SONNET, k: int = 5, asof: str | None = None,
           near: str | None = None, max_contracts: int = 2, retrieve=None, call=None, route_fn=None,
           driver_retrieve=None, extra_context: str | None = None, extra_number_calls: list | None = None,
           extra_resolver=None, planner: str | None = None, focus_driver: str | None = None,
           silver_lookup=None, on_stage=None, numbers_lookup=None, xc_request: dict | None = None,
           outlook: bool = False) -> dict:
    """Answer grounded in the graph(s) + dated evidence, structured for a reader. Routes (tiered lexical->semantic->
    LLM) to up to `max_contracts` (a soy<->corn question synthesizes both). Also pulls CROSS-CUTTING DRIVER evidence
    (WS-MS6 — B40/freight/FX/El Nino cascade triggers). Returns {answer (markdown), structured, contract(s),
    evidence, trace}.

    `outlook` (W5-D4) is the caller's TWO resolved legs -- plan.answer_mode_outlook AND
    is_outlook_explicit(query). It is ANDed with the _outlook_on() kill-switch INSIDE each body, so a
    caller that never heard of W5 (every test, the eval harness, the probe paths) gets the fenced register
    by default and the flag alone can never relax anything."""
    raw_retrieve = retrieve                                        # the CALLER's arg (None on serving) — _answer_l2
    retrieve = retrieve or functools.partial(ev.retrieve, **_RETRIEVAL)         # needs it raw so its cheap no-rerank
    driver_retrieve = driver_retrieve or functools.partial(ev.retrieve, **_RETRIEVAL)   # probe path actually engages
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
                          xc_request=xc_request, outlook=outlook)
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
    _episodes = _episodes_on(vp)
    structured = call(_system(outlook=_outlook, episodes=_episodes),
                      _pack(sp, vp, use_blocks), model=model, tool=_answer_tool())
    _banned_mood = _count_banned_mood(structured)                 # P9-A: RAW output, pre-sanitize
    _banned_val = _count_banned_valuation(structured)             # DP-6: valuation/flow raw counts, pre-sanitize
    _banned_flow = _count_banned_flow(structured)
    _banned_exec = _count_banned_exec(structured)                 # W5: A2 execution idioms, RAW (pinned 0 always)
    _unbacked = _count_unbacked_levels(structured)                # W5.0: bare price levels, RAW (derivation gate)
    degraded = _pop_degraded(structured)
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
    _humanize_structured(structured, market_register=_mr)         # clean the fields the UI renders directly (6.1)
    if os.environ.get("GRAPHRAG_ANSWER_V2", "off") == "on":       # P9-C typed sections -- the one-hop twin of
        secs = _sectionize(structured.get("mechanism") or "")     # the L2 seam: same post-verify+humanize
        if secs:                                                  # ordering, same per-call flag read
            structured["sections"] = secs
    if verifier.get("enabled"):                                   # ONE validated source list, model-numbered
        body = reg.sanitize(render(structured, include_ledger=False)
                            + _cited_sources_block(structured, verifier, extra_number_calls),
                            market_register=_mr)
    else:                                                         # verifier off -> legacy two-list rendering
        footer = ("\n\n## Sources\n" + cit.render(ev_cits)) if ev_cits else ""
        body = reg.sanitize(render(structured) + footer, market_register=_mr)   # strips leaked internal tokens
    if degraded:
        body = _DEGRADED_BANNER.format(m=degraded) + body
    return {"answer": body, "structured": structured, "contract": contracts[0],
            "contracts": contracts, "citations": [c.model_dump() for c in ev_cits],
            "evidence": evidence, "model": model,
            "trace": {"routed": routed, "contracts": contracts, "banned_mood_words": _banned_mood,
                      "banned_valuation_words": _banned_val, "banned_flow_words": _banned_flow,
                      "banned_exec_words": _banned_exec, "unbacked_levels": _unbacked,
                      "outlook_mode": _outlook, "market_register": _mr,
                      "n_drivers": sum(len(graph.contracts[c].drivers) for c in contracts), "regimes": regimes,
                      "drivers": drivers, "n_driver_evidence": len(driver_hits),
                      "evidence_ids": ev_ids, "has_diagram": _valid_mermaid(structured.get("diagram_mermaid")),
                      **({"degraded_model": degraded} if degraded else {}),
                      "citation_verifier": verifier, "model": model}}
