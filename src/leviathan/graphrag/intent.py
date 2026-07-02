"""Query-intent classifier for the serving orchestrator (Phase 5).

Decides whether a question needs NUMBERS (observed lookups), REASONING (the causal graph + dated evidence), or
BOTH — so a pure numbers question skips the whole cascade/evidence pipeline and a pure reasoning question skips
the SQL agent. A keyword heuristic settles the clear cases for free; only genuine ambiguity (neither signal
fired) falls to a cheap Haiku classifier.
"""
from __future__ import annotations

import re

HAIKU = "claude-haiku-4-5"

# numbers: asks for a figure/level/quantity of an observed series.
_NUM = re.compile(
    r"\b(how much|how many|what (?:was|were|is|are)|what'?s the|level of|the number|the figure|"
    r"exports?|imports?|production|ending stocks|beginning stocks|stocks-to-use|acreage|area harvested|"
    r"yield|the price|exchange rate|oni|el ni[nñ]o index|how weak|how strong|basis)\b", re.I)
# reasoning: asks why/how/what-if about drivers, cascades, exposure, direction.
_REASON = re.compile(
    r"\b(why|how does|how do|what happens|what would|if .+(?:then|would|will|enough)|explain|mechanism|"
    r"driver|cascade|converge|exposed|bullish|bearish|stack|offset|reinforce|cancel|affect|impact|"
    r"transmit|feed through|scenario|counterfactual|dominate|lead|which .+more|"
    r"a buy|a sell|worth (?:buying|selling)|net long|net short|squeeze|tip into)\b", re.I)


def _mk(intent: str) -> dict:
    return {"intent": intent,
            "needs_numbers": intent in ("numbers_only", "hybrid"),
            "needs_reasoning": intent in ("reasoning", "hybrid")}


def _intent_tool() -> dict:
    return {"name": "set_intent", "description": "Classify what the commodity question needs.",
            "input_schema": {"type": "object", "properties": {
                "intent": {"type": "string", "enum": ["numbers_only", "reasoning", "hybrid"]}},
                "required": ["intent"]}}


def _llm_classify(query: str, call, model: str) -> dict:
    system = ("Classify a commodity question. numbers_only = it ONLY asks for an observed figure/level (export "
              "volume, stocks, production, price, ONI, FX) with no causal reasoning. reasoning = it asks why/how/"
              "what-if about drivers, cascades, exposure or price direction. hybrid = it needs a specific number "
              "AND reasoning around it.")
    out = call(system, query, model=model, tool=_intent_tool()) or {}
    intent = out.get("intent")
    return _mk(intent if intent in ("numbers_only", "reasoning", "hybrid") else "reasoning")


def classify_intent(query: str, *, call=None, model: str = HAIKU) -> dict:
    """{intent: numbers_only|reasoning|hybrid, needs_numbers, needs_reasoning}. Heuristic first; the LLM resolves
    only when neither lexical signal fires (and only if a `call` is available — else default to reasoning)."""
    q = query or ""
    n, r = bool(_NUM.search(q)), bool(_REASON.search(q))
    if n and not r:
        return _mk("numbers_only")
    if r and not n:
        return _mk("reasoning")
    if n and r:
        return _mk("hybrid")
    return _llm_classify(q, call, model) if call is not None else _mk("reasoning")
