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


# ── cross-commodity RV explicit-ask detector (reroute v2, RV-W1.1) ────────────────────────────────────
# Mirrors _NEWS_EXPLICIT: a NARROW, deterministic matcher that is a NECESSARY condition for the v2
# cross-commodity relative-value fork, NEVER sufficient. The orchestrator LAW (RV-W1.3) binds the captured
# target, resolves the curated pair, and fails closed -- this regex only decides "did the user EXPLICITLY
# ask about the effect on / relative value against ANOTHER commodity". It must NOT match a single-commodity
# mechanism question ("how does the ban affect PALM prices?" -- the affected thing is the SAME commodity);
# the C8 correction makes that safe two ways: (a) the effected object is CAPTURED as <X> and the gate
# declines when resolve(<X>) == SOURCE, and (b) a background commodity present only as CONTEXT is never the
# grammatical object so it is never captured. Returns (matched, target_span): target_span is the captured
# effected-commodity text for a NAMED-target ask, or None for an OPEN-target ask ("what else does this
# affect?", D7). Off-topic / context-only mentions never match.

# The effected-object capture: a short, NON-GREEDY commodity noun phrase terminated by punctuation,
# end-of-string, an apostrophe (possessive asks -- "what does that do to palm's stocks" captures palm;
# the char class excludes apostrophes so without this terminator EVERY possessive phrasing misses, the
# 2026-07-19 clean-window positive-pin failure), or a connective/attribute word -- so a trailing context
# clause is never swallowed ("what does that do to palm given the soyoil glut" captures palm, not soyoil).
_XC_TERM = (
    r"(?=$|[?.,;:!'’]|\s+(?:given|amid|amidst|with|because|since|as|when|if|despite|after|before|while|"
    r"now\s+that|due\s+to|of|and|but|so|then|or|vs\.?|versus|prices?|markets?|demand|supply|output|"
    r"production|futures|glut|surplus|shortage|already|now)\b)")


# The object must NOT open with an interrogative / auxiliary / pronoun -- else "and what happens next?"
# captures the whole clause as a target. This keeps the capture to a plausible commodity noun phrase; final
# slug resolution (a non-commodity span -> None) is the complex_map resolver's job.
_XC_STOP = (r"(?!(?:what|how|why|when|where|who|which|whose|does|do|did|is|are|was|were|will|would|should|"
            r"could|can|it|its|this|that|these|those|there|then|next|happen|happens|going|get|gets|much|"
            r"many|anything|everything|nothing)\b)")


def _xc_obj(name: str) -> str:
    """A named non-greedy commodity-phrase capture (letters/spaces/hyphens), guarded against opening on an
    interrogative/aux/pronoun and terminated by _XC_TERM."""
    return rf"(?P<{name}>{_XC_STOP}[a-z][a-z \-]*?){_XC_TERM}"


# NAMED-target shapes: each captures the effected object as group <x>. Compiled INDIVIDUALLY (one <x> per
# pattern) because a single alternation cannot redefine a group name.
_XC_NAMED = [re.compile(p, re.I) for p in (
    r"what\s+(?:does|would|will)\s+(?:this|that|it)\s+do\s+(?:to|for)\s+" + _xc_obj("x"),
    r"what\s+(?:does|would|will)\s+(?:this|that|it)\s+mean\s+for\s+" + _xc_obj("x"),
    r"(?:effect|effects|impact|impacts|implications|fallout|read[- ]?across|spillover|spill\s+over|"
    r"ripple|knock[- ]?on)\b[\w\s,'-]*?\b(?:on|for|to|into|onto)\s+" + _xc_obj("x"),
    r"how\s+(?:does|would|will|might)\s+(?:this|that|it)\s+affect\s+" + _xc_obj("x"),
    r"(?:does|would|will)\s+(?:it|this|that)\s+help\s+or\s+hurt\s+" + _xc_obj("x"),
    r"\bwhat\s+about\s+" + _xc_obj("x"),
    r"^(?:so\s+|ok(?:ay)?\s+)?and\s+" + _xc_obj("x") + r"\s*\?",     # short follow-up "and soyoil?"
    r"\brelative\s+to\s+" + _xc_obj("x"),
    r"\bsubstitut\w*\s+(?:for|with|to|into|toward|towards)\s+" + _xc_obj("x"),
)]

# RELATIVE-VALUE (two named legs). The SECOND leg is returned as target_span; SOURCE resolves in the gate.
_XC_VS = [re.compile(p, re.I) for p in (
    _xc_obj("x") + r"\s+(?:vs\.?|versus)\s+" + _xc_obj("y"),
    r"which\s+(?:one\s+)?(?:tightens?|loosens?|benefits?|gains?|wins?|is\s+tighter)\b[\w\s,'-]*?\b"
    + _xc_obj("x") + r"\s+or\s+" + _xc_obj("y"),
)]

# OPEN-target shapes (D7): explicit read-across ask that names no second commodity -> (True, None); the gate
# picks the single most-material realizable curated pair for SOURCE (PAIR_CAP=1).
_XC_OPEN = [re.compile(p, re.I) for p in (
    r"what\s+else\s+(?:does|would|will|could|might)\s+(?:this|that|it)\s+(?:affect|hit|touch|move|impact|do)",
    r"\bany\s+(?:other\s+)?(?:knock[- ]?on|spillover|spill\s+over|ripple|read[- ]?across|cross[- ]?commodity)",
    r"\b(?:knock[- ]?on|spillover|spill\s+over|read[- ]?across)(?:\s+effects?)?\s*\??\s*$",
    r"what\s+other\s+(?:commodit(?:y|ies)|markets?|balance\s+sheets?)\b",
    r"which\s+other\s+commodit(?:y|ies)\b",
    r"\bany\s+(?:other\s+)?commodit(?:y|ies)\s+(?:affected|impacted|hit)\b",
)]

_XC_ARTICLE = re.compile(r"^(?:the|a|an)\s+", re.I)

# The user's ASK lives in the FINAL clause. Several NAMED shapes (effect/impact/read-across/spillover on <X>,
# relative to <X>, substitut... <X>) carry NO interrogative anchor, so on the raw string they match a
# commodity named inside a *declarative context clause* that merely describes what already happened -- e.g.
# "palm rallied despite the impact on soyoil -- why did palm move?" would capture soyoil even though the
# actual question is single-commodity. That violates the DOES-NOT-DO fence ("never volunteered ... when a
# second commodity appears only as context"). Fix: run the matcher ONLY over the final clause -- the user's
# ASK -- and fence off any leading declarative CONTEXT clause two ways:
#   (1) A leading subordinator FRAME ("Given/With/Despite/Amid/After/Because ... , <ask>") is a declarative
#       set-up the user prepends before the real ask; it is stripped up to its first comma so a cross-commodity
#       mention living only inside the frame ("Given the read-across to soyoil, why did palm rally?") is never
#       searched. NOTE: "relative to <X>, ..." is deliberately NOT a subordinator here -- "relative to" is a
#       first-class comparison anchor (a legitimate RV ask), so it is preserved.
#   (2) The remainder is split on STRONG terminals (. ! ? ;), dash separators (-- / em/en dash), AND a comma
#       bound to a coordinating conjunction (", so/but/yet/and/then ..."); only the LAST segment is searched.
#       A comma+conjunction almost always introduces a NEW main clause (the real ask) after a declarative
#       context clause ("palm rallied despite the impact on soyoil, so why did palm move?") -- so splitting
#       there and keeping the tail drops the context. The conjunction MUST be comma-led: bare " and " never
#       splits ("corn and soybeans both rallied" stays whole), and "or" is excluded so the RV shape
#       "which tightens, soyoil or palm?" is preserved.
# The interrogative-anchored shapes ("what does this do to <X>") already sit in the ask, so this never removes
# a legitimate match -- it only fences off context clauses. Erring toward MORE splitting is fail-closed: a
# missed legitimate RV-plus-follow-up still answers single-commodity, whereas a fired context clause is the
# fence violation.
_XC_LEAD_CONTEXT = re.compile(
    r"^(?:given|with|amid|amidst|despite|after|before|because|since|while|if|now\s+that|due\s+to)\b[^,]*,\s*",
    re.I)
_XC_CLAUSE_SPLIT = re.compile(
    r"[.!?;]+|\s+--+\s+|\s*[—–]\s*|\s+-\s+|,\s*(?:so|but|yet|and|then)\s+", re.I)
# (3) A TRAILING subordinate/context clause inside the final clause is cut before matching -- the
#     residual attack class the leading strip + comma-conjunction split both miss ("why did palm rally
#     GIVEN the read-across to soyoil?", "..., WITH the read-across to soyoil?"). Two alternations:
#     the unambiguous subordinators cut bare or comma-led; with/after/before cut ONLY when followed by
#     a determiner ("with the read-across ...") so the entry-9 pattern preposition ("substitute with
#     palm oil") and bare temporal tails survive. Cutting is fail-closed (a lost ", why?" tail merely
#     declines); a survived context clause is the fence violation (2026-07-18 verify-wave recheck).
_XC_TRAIL_CONTEXT = re.compile(
    r"\s*,?\s+(?:given|amid|amidst|despite|because|since|while|whereas|now\s+that|due\s+to)\b.*$"
    r"|\s*,?\s+(?:with|after|before)\s+(?:the|a|an|this|that|these|those|all)\b.*$",
    re.I)
_XC_TERMINAL = re.compile(r"[?!.]+$")


def _xc_final_clause(q: str) -> str:
    """The trailing clause of the query -- the user's ASK. Strips a leading subordinator context frame, then
    returns everything after the last strong/comma-conjunction clause boundary. Re-attaches the query's own
    terminal punctuation (the split drops it) so shapes that require a trailing '?' (the short "and soyoil?"
    follow-up) still see it."""
    raw = q.strip()
    body = _XC_LEAD_CONTEXT.sub("", raw, count=1).strip() or raw
    parts = [p.strip() for p in _XC_CLAUSE_SPLIT.split(body) if p and p.strip()]
    tail = parts[-1] if parts else body
    tail = _XC_TRAIL_CONTEXT.sub("", tail, count=1).strip() or tail   # (3) drop a trailing context clause
    m = _XC_TERMINAL.search(raw)
    if m and not tail.endswith(("?", "!", ".")):
        tail = tail + m.group(0)
    return tail


def _xc_clean(span: str | None) -> str | None:
    """Trim a captured target span to a bare commodity phrase (drop a leading article, surrounding
    punctuation/space). Slug resolution itself is the complex_map resolver's job (RV-W1.3)."""
    if not span:
        return None
    t = _XC_ARTICLE.sub("", span.strip().strip("-").strip()).strip()
    return t or None


def is_cross_commodity_explicit(query: str) -> tuple[bool, str | None]:
    """Did the user EXPLICITLY ask about the effect on / relative value against ANOTHER commodity?
    Returns (matched, target_span): target_span is the captured effected-commodity text for a named-target
    ask, or None for an open-target ask. NECESSARY, not sufficient -- the orchestrator LAW binds and
    resolves it and fails closed. See the module commentary above and RV-W1.1 / the C8 correction."""
    raw = (query or "").strip()
    if not raw:
        return (False, None)
    q = _xc_final_clause(raw)                             # fence off leading context clauses -- search the ASK only
    if not q:
        return (False, None)
    for rx in _XC_VS:                                     # relative-value FIRST: "do to X versus Y" must bind
        m = rx.search(q)                                  # Y (the second leg), not X -- X is usually the SOURCE
        if m:                                             # itself and NAMED-first would C8-decline the whole ask
            span = _xc_clean(m.group("y")) or _xc_clean(m.group("x"))
            if span:
                return (True, span)
    for rx in _XC_NAMED:                                  # named-target: bind TARGET to the captured <X>
        m = rx.search(q)
        if m:
            span = _xc_clean(m.group("x"))
            if span:
                return (True, span)
    for rx in _XC_OPEN:                                   # open-target ask (D7): gate ranks the pairs
        if rx.search(q):
            return (True, None)
    return (False, None)


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
