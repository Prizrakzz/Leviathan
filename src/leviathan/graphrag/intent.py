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
# reasoning: asks why/how/what-if about drivers, cascades, convexity, exposure, direction.
_REASON = re.compile(
    r"\b(why|how does|how do|what happens|what would|if .+(?:then|would|will|enough)|explain|mechanism|"
    r"driver|cascade|converge|propagat|amplif|dampen|regime|convex|linear|asymmetr|skew|tail|buffer|threshold|"
    r"channel|exposed|bullish|bearish|stack|offset|reinforce|cancel|cost-push|affect|impact|"
    r"transmit|feed through|scenario|counterfactual|dominate|lead|which .+more|tip(?:s|ped)? into|tip from|"
    r"a buy|a sell|worth (?:buying|selling)|net long|net short|squeeze)\b", re.I)


# live: the question is about NOW — breaking policy/shock news, today's state. Only meaningful when the
# as-of is today (the orchestrator's PIT kill-switch disables the live branch for any past as-of).
_LIVE = re.compile(
    r"\b(today|right now|breaking|overnight|as of now|latest news|any news|"
    r"this (?:week|morning)|just (?:banned|announced|imposed|halted|closed|restricted|cut|reinstated))\b", re.I)


def is_live(query: str) -> bool:
    """Does the question ask about the present moment (candidates for the live news branch)?"""
    return bool(_LIVE.search(query or ""))


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
        return _mk("numbers_only")                                   # only a data cue -> pure lookup
    if r and not n:
        return _mk("reasoning")                                      # only a reasoning cue -> pure reasoning
    # AMBIGUOUS (both fired, or neither): a data cue inside a reasoning question ("given the observed X, is it
    # convex") is the exact case the heuristic mis-classifies -> let the cheap LLM adjudicate when available.
    if call is not None:
        return _llm_classify(q, call, model)
    return _mk("hybrid" if (n and r) else "reasoning")               # no LLM: both->hybrid, neither->reasoning
