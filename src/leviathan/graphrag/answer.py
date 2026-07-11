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

from leviathan.graphrag import citations as cit
from leviathan.graphrag import evidence as ev
from leviathan.graphrag import extract as ex
from leviathan.graphrag import graph as gph
from leviathan.graphrag import harvest as hv
from leviathan.graphrag import params as _prm
from leviathan.graphrag import register as reg

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
    "the reader smarter about the setup. Never give a position, a size, or a price target.\n"
    "TONE & FORMAT: You MAY use **bold** for the lead term of a point and '-' bullets for a short enumeration, "
    "sparingly and professionally; do NOT use tables, code fences, blockquotes, or _underscore_ emphasis. Structure "
    "the `mechanism` field under these four markdown headings, in this exact order and wording: '## Mechanism', "
    "'## The record', '## Where the record disagrees', '## What to watch'. Always include '## Mechanism' and "
    "'## What to watch'. Include '## The record' whenever you cite any dated or observed evidence. Include "
    "'## Where the record disagrees' ONLY when there is a genuine conflict -- opposing same-confidence drivers, "
    "sources of different trust tiers that disagree, or members/eras that diverge; OMIT that heading when there is "
    "no disagreement (never write a 'no disagreement' line).\n"
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
    "countries into one figure. If there is NO DIVERGENCE line and NO REROUTE line, do NOT invent a fork. "
    "If a leg reads 'not yet in effect as of <asof>' or '(record silent for that era)', narrate that ABSENCE "
    "honestly; never fabricate a value for it. "
    "HANDLE DISCIPLINE (the verifier strips violations): an OBSERVED number takes ONLY its [N] handle -- "
    "never an [E] handle, never a bare number, never an invented handle variant. COPY EACH ROW FIGURE "
    "EXACTLY AS PRINTED -- never round or re-scale it (\"3.36%\" stays \"3.36%\", never \"roughly 3 percent\"; a "
    "stripped-down figure matches no row and is discarded). A magnitude you DERIVE yourself -- a ratio, "
    "share, sum, or shortfall computed across rows (e.g. a stocks-to-use ratio from a stocks level and a "
    "use level) -- has NO row: state it WITHOUT ANY NUMERAL (\"a razor-thin buffer\", \"a far larger "
    "cushion\"), and NEVER place a derived or rounded number in the same sentence as a row citation, or it "
    "strips the good handle with it. NAME EACH ERA BY ITS MARKETING YEAR OR PERIOD (\"the 2016/17 season\", "
    "\"the 2018/19 drought\"), NEVER as \"era 0\"/\"era 1\" -- the bare index reads as an uncited magnitude and "
    "a reader must never see an internal label. Name each leg by the COUNTRY shown in its row, exactly. "
    "And in the record as everywhere else: never 'bullish' or 'bearish' -- direction is prose ('fell', "
    "'rose to fill the gap'), magnitude is the [N] row.\n")


def _count_banned_mood(structured: dict) -> int:
    """P9-A hard-gate metric: banned mood words on the RAW model output, BEFORE _humanize_structured/
    sanitize (which neutralize them) — measuring after would read 0 forever. Rides the trace to eval."""
    return len(reg._MOOD.findall((structured.get("tldr") or "") + " " + (structured.get("mechanism") or "")))


def _system() -> str:
    """The active reader-facing persona. GRAPHRAG_MENTOR_VOICE default on -> mentor; =off -> the prior string.
    GRAPHRAG_CASCADE_QUANT on -> append the OBSERVED CASCADE NUMBERS addendum (P9-B: the loop supplies the
    [N] rows). Read PER CALL, never memoized: a serving process is long-lived, so a once-at-import read would
    make the env-flip rollback a silent no-op until a redeploy — defeating the gate's purpose."""
    if os.environ.get("GRAPHRAG_MENTOR_VOICE", "on") == "off":
        return _SYSTEM_LEGACY
    base = _SYSTEM_MENTOR
    if os.environ.get("GRAPHRAG_CASCADE_QUANT", "on") != "off":
        base = base + _SYSTEM_CASCADE
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
                    return (f"{d} (OBSERVED {b.get('value')} {b.get('unit', '')}, z={b.get('z')}, "
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
                vlines.append(tl.render_line(n.id, n.episodes))
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


def _answer_l2(query: str, graph: gph.CausalGraph, *, model, asof, near, call, retrieve, routed,
               extra_context: str | None = None, extra_number_calls: list | None = None,
               extra_resolver=None, focus_driver: str | None = None, use_blocks: bool = False,
               silver_lookup=None, on_stage=None, numbers_lookup=None) -> dict:
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
        try:                                                      # GRACEFUL (R6): a raise here must NEVER 500
            _cblock, _quant_trace, _reroute_trace = cq.quantify(sg, graph, qfn=numbers_lookup, asof=asof,
                                                                near=near,
                                                                extra_number_calls=extra_number_calls)
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
    structured = call(_system(), _pack(sp, vp, use_blocks), model=model, tool=_answer_tool(), **call_kw)
    _banned_mood = _count_banned_mood(structured)                 # P9-A: RAW output, pre-sanitize (see helper)
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
    _attach_provenance(structured, verifier)                     # stamp source_key for durable chip join (6.4)
    _humanize_structured(structured)                              # clean the fields the UI renders directly (6.1)
    if os.environ.get("GRAPHRAG_ANSWER_V2", "off") == "on":       # P9-C typed sections: a DERIVED view of the
        secs = _sectionize(structured.get("mechanism") or "")     # FINAL prose (post-verify+humanize); read per
        if secs:                                                  # call so the env-flip rollback stays live
            structured["sections"] = secs
    if verifier.get("enabled"):                                   # ONE validated source list, model-numbered
        body = reg.sanitize(render(structured, include_ledger=False)
                            + _cited_sources_block(structured, verifier, extra_number_calls))
    else:                                                         # verifier off -> legacy two-list rendering
        footer = ("\n\n## Sources\n" + cit.render(ev_cits)) if ev_cits else ""
        body = reg.sanitize(render(structured) + footer)
    if degraded:
        body = _DEGRADED_BANNER.format(m=degraded) + body
    return {"answer": body, "structured": structured, "contract": contracts[0] if contracts else None,
            "contracts": contracts, "citations": [c.model_dump() for c in ev_cits], "evidence": evidence,
            "model": model, "trace": {"planner": "l2", "fired_regimes": sg.fired_regimes,
                                      "citation_verifier": verifier, "banned_mood_words": _banned_mood,
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


def _humanize_structured(d: dict) -> None:
    """Sanitize the structured fields the UI renders DIRECTLY into reader register (6.1). The frontend
    shows `structured.{tldr,mechanism,sources}`, NOT the flattened body, so this is where leaked internal
    tokens, raw regime ids, and internal source ids are removed for the live AND persisted note. Runs
    AFTER verify (which mutates tldr/mechanism to strip fabricated citations) and mutates in place, so
    the object returned + persisted is already clean."""
    if not isinstance(d, dict):
        return
    for fld in ("tldr", "mechanism"):
        v = d.get(fld)
        if isinstance(v, str) and v:
            d[fld] = reg.sanitize(v)
    srcs = d.get("sources")
    if isinstance(srcs, list):
        from leviathan.graphrag import display as dp
        for s in srcs:
            if not isinstance(s, dict):
                continue
            if s.get("source"):
                s["source"] = dp.source_name(str(s["source"]))
            if isinstance(s.get("note"), str) and s["note"]:
                s["note"] = reg.sanitize(s["note"])


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


def _call_opus(system: str, user, *, model: str, tool: dict, on_token=None) -> dict:
    """The real serving call — provider-routed (Anthropic API or Bedrock via providers.py) with the
    production fallback chain (backoff retry -> Sonnet->Haiku degradation, tagged). PROMPT CACHING: the
    system prompt is always a cached block, and when `user` arrives as a (stable_prefix, volatile_tail)
    tuple the stable part — the per-contract graph context, byte-identical across a session's turns —
    gets its own cache breakpoint (manual blocks work identically on both providers). Turn 2+ of a
    conversation reads the shared prefix at ~0.1x input price. Injected test fakes keep the plain-string
    `user` API; only this real path structures blocks. When `on_token` is set (SSE turns) the note STREAMS
    token-by-token via serving_call_stream (buffered otherwise — byte-identical for eval/POST)."""
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
        out, degraded = pv.serving_call(client, sys_blocks, user, **kw)
    if degraded and isinstance(out, dict):
        out["_degraded_model"] = degraded          # popped by the consumer -> visible caveat + trace
    return out


def answer(query: str, *, graph: gph.CausalGraph, model: str = SONNET, k: int = 5, asof: str | None = None,
           near: str | None = None, max_contracts: int = 2, retrieve=None, call=None, route_fn=None,
           driver_retrieve=None, extra_context: str | None = None, extra_number_calls: list | None = None,
           extra_resolver=None, planner: str | None = None, focus_driver: str | None = None,
           silver_lookup=None, on_stage=None, numbers_lookup=None) -> dict:
    """Answer grounded in the graph(s) + dated evidence, structured for a reader. Routes (tiered lexical->semantic->
    LLM) to up to `max_contracts` (a soy<->corn question synthesizes both). Also pulls CROSS-CUTTING DRIVER evidence
    (WS-MS6 — B40/freight/FX/El Nino cascade triggers). Returns {answer (markdown), structured, contract(s),
    evidence, trace}."""
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
                          silver_lookup=silver_lookup, on_stage=on_stage, numbers_lookup=numbers_lookup)
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
    structured = call(_system(), _pack(sp, vp, use_blocks), model=model, tool=_answer_tool())
    _banned_mood = _count_banned_mood(structured)                 # P9-A: RAW output, pre-sanitize
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
    _attach_provenance(structured, verifier)                     # stamp source_key for durable chip join (6.4)
    _humanize_structured(structured)                              # clean the fields the UI renders directly (6.1)
    if os.environ.get("GRAPHRAG_ANSWER_V2", "off") == "on":       # P9-C typed sections -- the one-hop twin of
        secs = _sectionize(structured.get("mechanism") or "")     # the L2 seam: same post-verify+humanize
        if secs:                                                  # ordering, same per-call flag read
            structured["sections"] = secs
    if verifier.get("enabled"):                                   # ONE validated source list, model-numbered
        body = reg.sanitize(render(structured, include_ledger=False)
                            + _cited_sources_block(structured, verifier, extra_number_calls))
    else:                                                         # verifier off -> legacy two-list rendering
        footer = ("\n\n## Sources\n" + cit.render(ev_cits)) if ev_cits else ""
        body = reg.sanitize(render(structured) + footer)          # sanitizer strips leaked internal tokens
    if degraded:
        body = _DEGRADED_BANNER.format(m=degraded) + body
    return {"answer": body, "structured": structured, "contract": contracts[0],
            "contracts": contracts, "citations": [c.model_dump() for c in ev_cits],
            "evidence": evidence, "model": model,
            "trace": {"routed": routed, "contracts": contracts, "banned_mood_words": _banned_mood,
                      "n_drivers": sum(len(graph.contracts[c].drivers) for c in contracts), "regimes": regimes,
                      "drivers": drivers, "n_driver_evidence": len(driver_hits),
                      "evidence_ids": ev_ids, "has_diagram": _valid_mermaid(structured.get("diagram_mermaid")),
                      **({"degraded_model": degraded} if degraded else {}),
                      "citation_verifier": verifier, "model": model}}
