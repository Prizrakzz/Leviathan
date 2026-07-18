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


# EXPLICIT news ask — the narrow subset of _LIVE where the user literally requested news/headlines. Split
# from _LIVE (the news-agent root-cause fix): _LIVE's ambient nowness words ("today", "right now") also
# appear in numbers/reasoning questions ("corn exports today?"), so they must never FORCE the live route;
# an explicit "any news ..." must. Used two ways in the orchestrator: (1) deterministic promotion to the
# live route when the dispatcher misroutes an explicit ask at a today as-of, and (2) the visible
# suppression note when the PIT kill-switch (historical as-of) vetoes an explicit ask — never silently.
_NEWS_EXPLICIT = re.compile(
    r"\b(any news|latest news|news (?:on|about|around|regarding|related|from|for)|headlines|"
    r"what just happened|breaking news|what's new|whats new)\b", re.I)


def is_news_explicit(query: str) -> bool:
    """Did the user LITERALLY ask for news/headlines (not just mention the present moment)?"""
    return bool(_NEWS_EXPLICIT.search(query or ""))


# ── trivial-turn router (F1): pure-regex greeting/smalltalk/meta detector — NO I/O, NO LLM ────────────────
# A greeting or "what can you do?" today pays TWO Sonnet calls (dispatch planner + synthesis) to return a
# vacuous note. is_trivial is the cheap up-front gate (mirrors is_news_explicit) that lets the orchestrator
# short-circuit those turns to a canned mentor-register reply. FALSE POSITIVES ARE THE FAILURE MODE: a real
# question that merely OPENS with a greeting ("hi, also what is wheat doing") MUST fall through.
#
# Two guards, BOTH must pass to classify a turn as trivial:
#   (i)  FULL-STRING anchor (PRIMARY): the ENTIRE normalized message (trailing terminal punctuation stripped)
#        must BE a greeting/smalltalk/meta phrase. A greeting TOKEN embedded anywhere in a longer real message
#        never matches -- this is what defeats the escaping-vocabulary shape "hey what's driving cocoa" that
#        slips the data-cue backstop below (neither _NUM nor _REASON fires on it). The word-boundary +
#        short-length disjunct an earlier draft allowed is DELIBERATELY DROPPED.
#   (ii) data/reasoning-cue BACKSTOP (anti-hijack veto): if intent._NUM or intent._REASON fires ANYWHERE in
#        the message, return None. Belt-and-braces only -- guard (i) already blocks every hijack (a hijack is
#        longer than the pure phrase), so (ii) can only make the router MORE conservative (more fall-through),
#        never less safe. A side effect: whole-message meta phrases that themselves contain a cue token --
#        "what is this" / "what are you" (trip _NUM's "what is/are"), "how does this work" (trips _REASON's
#        "how does") -- fall THROUGH rather than route to the canned meta reply. That is intentional: it is
#        fail-open (the pipeline still answers them) and avoids mis-canning "how does [the corn cascade] work".
_TRIVIAL_GREETING = re.compile(
    r"(?:hi+|hey+|hello+|heya|hiya|yo|howdy|greetings|good\s+(?:morning|afternoon|evening|day))"
    r"(?:\s+(?:there|all|team|everyone|folks|mate|friend|desk))?", re.I)
_TRIVIAL_SMALLTALK = re.compile(
    r"(?:(?:ok(?:ay)?|great|perfect|awesome|cool|nice)\s+)?"
    r"(?:thanks(?:\s+(?:a\s+lot|so\s+much|again))?|thank\s+(?:you|u)(?:\s+(?:so\s+much|very\s+much))?|"
    r"thx|ty|cheers|much\s+appreciated|appreciate\s+it|"
    r"bye|goodbye|see\s+(?:you|ya)(?:\s+later)?|good\s*night|gn|later)", re.I)
# META vocab is restricted to phrases that DO NOT trip _NUM/_REASON (see guard (ii) above) so every branch is
# genuinely matchable rather than a dead alternation silently vetoed by the backstop.
_TRIVIAL_META = re.compile(
    r"(?:who\s+are\s+you|what\s+(?:can|do)\s+you\s+do|what\s+can\s+you\s+help\s+(?:me\s+)?with|"
    r"what\s+can\s+(?:i|you)\s+ask|what\s+do\s+you\s+cover|what\s+data\s+do\s+you\s+(?:have|cover)|"
    r"what\s+can\s+this\s+do|help)(?:\s+me)?", re.I)

# Cheap short-token PRE-FILTER only (never sufficient on its own; guard (i) carries the load).
_TRIVIAL_PREFILTER_MAX_TOKENS = 6      # v1 default (plan Wave 1): a length pre-filter, NOT a classifier.
_TRIVIAL_CLASSES = (("meta", _TRIVIAL_META), ("smalltalk", _TRIVIAL_SMALLTALK), ("greeting", _TRIVIAL_GREETING))


def is_trivial(query: str) -> str | None:
    """Classify a turn as a trivial social turn eligible for the canned mentor reply, else None (fall through
    to the normal pipeline). Deterministic + pure (regex only, no I/O, no LLM). Returns
    "greeting" | "smalltalk" | "meta" | None. See the guard commentary above -- guard (i) FULL-STRING anchor
    is primary, guard (ii) _NUM/_REASON backstop is the anti-hijack veto. Fail-safe by design: any genuinely
    ambiguous or real turn returns None so the orchestrator runs it normally."""
    q = (query or "").strip()
    if not q:
        return None
    if _NUM.search(q) or _REASON.search(q):                 # (ii) backstop veto: any data/reasoning cue -> real
        return None
    if len(q.split()) > _TRIVIAL_PREFILTER_MAX_TOKENS:      # cheap pre-filter: no pure greeting is this long
        return None
    core = re.sub(r"[.!?\s]+$", "", q).strip()              # (i) strip trailing terminal punctuation for the anchor
    for klass, rx in _TRIVIAL_CLASSES:
        if rx.fullmatch(core):                              # FULL-STRING: the WHOLE message must be the phrase
            return klass
    return None


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
