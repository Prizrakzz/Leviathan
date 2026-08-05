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
# PRICE_OBSERVABILITY W4.2 (S3.F5/S2.F10): positioning vocabulary sends managed-money COT asks down the
# NUMBERS lane. Conservative additions only -- each is a positioning LEVEL cue. "net long|net short" are
# ALSO _REASON triggers below (a positioning-flavored reasoning ask), so those two now fire BOTH cues ->
# classify_intent yields hybrid, which still routes to numbers (needs_numbers) WITHOUT dropping the
# reasoning lane -- an additive capability, never a removal. The narrow `funds? <positioning-noun>` clause
# (funds crowded|net|position...) catches the "are funds crowded" shape without matching bare "funds"
# elsewhere. Positioning is HISTORICAL CONTEXT ONLY (R9); routing it to numbers surfaces the dated level/z.
_NUM = re.compile(
    r"\b(how much|how many|what (?:was|were|is|are)|what'?s the|level of|the number|the figure|"
    r"exports?|imports?|production|ending stocks|beginning stocks|stocks-to-use|acreage|area harvested|"
    r"yield|the price|exchange rate|oni|el ni[nñ]o index|how weak|how strong|basis|"
    r"managed[ -]?money|positioning|open interest|net length|net long|net short|"
    r"funds?[ -]+(?:crowded|net|position\w*|long|short)|"
    # F2 floor (defense-in-depth; recon-proved collateral-free on both decks): colloquial export-sales PACE
    # forms. Deliberately NOT 'marketing year' / 'picked up' (proven collateral on the reasoning deck).
    r"export sales|sales pace|pacing|purchases?\s+of)\b", re.I)
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


# ── EXPLICIT price-OUTLOOK ask detector (W5-D4) ───────────────────────────────────────────────────────
# Mirrors _NEWS_EXPLICIT and is_cross_commodity_explicit: a NARROW, deterministic matcher that is a
# NECESSARY condition for the outlook rendering mode, NEVER sufficient. The gate is
#
#     outlook fires IFF plan.answer_mode_outlook AND is_outlook_explicit(query) AND _outlook_on()
#
# and OUTLOOK IS THE ONE MODE THAT MUST FAIL CLOSED. Every other misroute in this system is fail-open by
# design and that is correct -- a numbers question misrouted to reasoning still gets a grounded answer.
# Outlook inverts the asymmetry: a normal question landing in outlook relaxes the market register on a turn
# that never asked for it, which is the exact failure the fence exists to prevent. A MISSED outlook ask
# merely degrades to today's answer (harmless); a FALSE POSITIVE cannot be allowed to relax anything.
#
# So every alternative below requires BOTH a forward-looking cue AND a price/level noun in the same shape.
# Deliberately NOT matched: "why did prices rally in 2010" (backward), "what was the price" (observed
# lookup), "how does the ban affect palm prices" (mechanism -- the register that answers it is unchanged),
# "where were prices in 2010" (historical). When in doubt the regex declines.
# FOLD-PASS 2026-07-30. Four of the six outlook-POSITIVE deck rows red their own `outlook_rendered: true`
# pin BY CONSTRUCTION because the shipped alternations had no slot for a COMMODITY WORD between the modal
# and the price noun ("where do CORN prices go from here", "how high can WHEAT prices go") and because
# `(price|prices)\s+from\s+here` demanded adjacency, which "prices GO from here" breaks. Both are widened
# below: up to three intervening words before the price noun, and a bounded gap before "from here". The
# widening stays narrow enough to keep every declined shape declined (see the unit test's negative list).
_OUTLOOK_LEAD = r"(?:[a-z][\w-]*\s+){0,3}"
_OUTLOOK_EXPLICIT = re.compile(
    r"\b(price|market)s?\s+(outlook|forecast|trajectory|path)\b"
    r"|\boutlook\s+for\s+(the\s+)?(price|prices|market)\b"
    r"|\bwhere\s+(do|does|will|would|might|could)\s+(you\s+|we\s+)?(see\s+)?(the\s+)?" + _OUTLOOK_LEAD +
    r"(price|prices|it|they|things)\b[\w\s]{0,20}?\b(go|going|head|heading|end\s+up|trade|land|settle|be)\b"
    r"|\bwhere\s+(are|is)\s+(the\s+)?" + _OUTLOOK_LEAD + r"(price|prices|this|it|they)\s+(going|headed|heading)\b"
    r"|\bwhat'?s?\s+your\s+(view|call|take)\s+on\s+(the\s+)?" + _OUTLOOK_LEAD + r"(price|prices)\b"
    r"|\bhow\s+(high|low|far)\s+(can|could|might|will|would|do\s+you\s+see)\s+"
    r"(the\s+)?" + _OUTLOOK_LEAD + r"(price|prices|it|they)\b"
    r"|\b(price|prices)\b[\w\s,]{0,25}\bfrom\s+here\b"
    r"|\bwhere\s+(do|does)\s+(this|that|it)\s+leave\s+(the\s+)?" + _OUTLOOK_LEAD + r"(price|prices)\b"
    r"|\b(forward|price)\s+(view|risk)s?\s+from\s+here\b",
    re.I)
# The one alternative that must be CONDITION-AWARE. "what will happen to the price of wheat IF Russia bans
# exports again" is a conditional MECHANISM ask -- the module docstring already lists that class as
# deliberately-not-matched, and PLANNER_SYS's own negative example is the same shape, so the planner leg is
# not a reliable backstop. Split out so a conditional clause declines it without touching the other legs.
_OUTLOOK_HAPPEN = re.compile(
    r"\bwhat\s+(will|would|could|might)\s+happen\s+to\s+(the\s+)?(price|prices)\b", re.I)
_OUTLOOK_CONDITIONAL = re.compile(
    r"\b(if|under|when|should|assuming|in\s+the\s+event|were\s+\w+\s+to|suppose)\b", re.I)


def is_outlook_explicit(query: str) -> bool:
    """Did the user EXPLICITLY ask where PRICES GO FROM HERE (not why they moved, not what they were)?

    NECESSARY, not sufficient -- the answer.py seam ANDs this with the planner's `answer_mode_outlook` and
    the `_outlook_on()` kill-switch, and any leg false runs the turn on the DEFAULT FENCED register."""
    q = query or ""
    if _OUTLOOK_EXPLICIT.search(q):
        return True
    return bool(_OUTLOOK_HAPPEN.search(q)) and not _OUTLOOK_CONDITIONAL.search(q)


# ── episodic-shape detector (D-RC-11) ─────────────────────────────────────────────────────────────────
# The RELEVANCE leg for the '## Episodes' surface: does the question's SHAPE call for enumerating the
# historical record? Cloned from the is_news_explicit / is_outlook_explicit idiom: NARROW, deterministic,
# regex-only, and consumed at the answer.py seam behind GRAPHRAG_EPISODE_RELEVANCE (default off,
# fail-OPEN -- a miss keeps today's behaviour; a hit is only ever a *license*, never a mandate).
# The cue list is CALIBRATED against two fixed corpora and pinned by tests:
#   * every row of the playbook decks (eval_queries_playbooks_v1 + _r6residual) must fire TRUE -- those
#     20 rows pin min_episode_lines/min_episodes_cited and a gate that misses one reds a ratified deck;
#   * the 2026-08-05 desk-probe's non-episodic questions (ranking, S&D-now, recent-weather,
#     verification, compare, context-node, outlook) must fire FALSE -- those are the five uninvited
#     24-35-bullet sections the gate exists to suppress.
# English-only BY DESIGN: the caller fails OPEN on non-Latin queries (suppressing a section because the
# cue list cannot read the language is not a relevance judgment).
_EPISODIC = re.compile(
    r"\beach\s+(?:time|one|occasion|episode)\b"
    r"|\bepisodes?\b"
    r"|\bone\s+by\s+one\b"
    r"|\bone\s+at\s+a\s+time\b"
    r"|\benumerat\w*"
    r"|\busually\s+happens?\b"
    r"|\bwhat\s+did\s+the\s+record\s+show\b"
    r"|\beras?\b"
    r"|\bthrough\s+the\s+(?:19|20)\d{2}\b"                  # 'positioning through the 2022 export ban'
    r"|\bwhen\s+has\b"
    r"|\bhas\s+\w+(?:\s+\w+){0,3}\s+ever\b"
    r"|\bhistor(?:y|ically|ical)\b"
    r"|\bprecedents?\b"
    # 'walk me through' alone is a MECHANISM idiom too ('walk me through how the crush works') --
    # require the enumerable object (the playbook rows all carry one: 'the episodes', 'each episode',
    # 'the individual episodes').
    r"|\bwalk\s+me\s+through\s+(?:the|each|those|every)\b[^.?!]{0,40}?\b(?:episod|record|histor|time)"
    r"|\bplayed\s+out\b"                                    # past tense ONLY: 'how would that play out'
    r"|\bevery\s+time\b"                                    # is a counterfactual, not an enumeration
    r"|\bwatch\s+over\b",                                   # 'what should I watch over weeks, months...'
    re.I)


def is_episodic_explicit(query: str) -> bool:
    """Does the question's shape call for enumerating historical episodes? Deterministic + pure (regex
    only, no I/O, no LLM). NECESSARY leg for the '## Episodes' surface when GRAPHRAG_EPISODE_RELEVANCE
    is on; with the flag off the caller never consults it."""
    return bool(_EPISODIC.search(query or ""))


# ── response-contract selector, tier 1 (D-RC-6) ───────────────────────────────────────────────────────
# PRIORITY-ORDERED, first match wins, None when nothing matches (fail-open to `default` downstream).
# Deliberately NARROW per family — a miss costs nothing (default = today's shape), a wrong hit costs a
# mis-shaped answer — and deliberately NOT numbers/agent._SHAPE_PATTERNS (its `outlook` regex matches
# 'stocks-to-use', and it never runs on a pure reasoning turn). `outlook` is ABSENT from this tuple on
# purpose: the register-affecting outlook gate keeps sole authority (tier 0 preempts). Ordering
# rationale: an asserted-premise check must not fall through to `compare` because it names two markets
# (verification first); 'what if X banned exports again' carries export-ban vocabulary but is a
# hypothetical (counterfactual before enumeration); `compare` beats `recency` so 'compare X and Y
# right now' keeps the comparison shape.
_RC_PATTERNS = (
    ("verification", re.compile(
        r"\bis (?:this|that|it) documented\b|\bcan we (?:only )?infer\b|\bfact[- ]check\b"
        r"|\bis (?:this|that) (?:actually |really )?(?:true|right|correct|the case)\b"
        r"|\bdid \w+(?: \w+){0,4} actually\b|,\s*right\?|\bisn'?t it\?", re.I)),
    ("counterfactual", re.compile(
        r"\bwhat if\b|\bsuppose\b|\bhypothetically\b|\bwhat would happen if\b"
        r"|\bhow would (?:that|this|it) play out\b|\bwere \w+ to\b", re.I)),
    ("enumeration", _EPISODIC),
    ("ranking", re.compile(
        r"\b(?:largest|biggest|top \d+)\b.{0,60}\b(?:producer|exporter|importer|consumer|grower)s?\b"
        r"|\brank(?:s|ed|ing)?\b", re.I)),
    ("compare", re.compile(
        # 'versus normal/average/history' is a BASELINE comparison (recency/mechanism shape), not a
        # two-market compare -- the lookahead keeps those out.
        r"\bcompare\b|\b(?:versus|vs\.?)\s+(?!normal\b|average\b|usual\b|histor|seasonal|last\b|typical\b)"
        r"|\bside by side\b|\bstack up\b"
        r"|\bwhich is (?:tighter|cheaper|richer|stronger|weaker|more exposed)\b", re.I)),
    ("recency", re.compile(
        r"\bright now\b|\bpast \d+ (?:day|week|month)s?\b|\bcurrently\b|\bas of (?:today|now)\b"
        r"|\blatest\b|\brecent(?:ly)?\b|\bthis (?:week|month)\b", re.I)),
    ("context_node", re.compile(
        r"\bdoes \w+(?: \w+){0,3} (?:affect|matter|impact|influence|move)\b|\bwhat role does\b", re.I)),
)


def select_response_contract(query: str) -> str | None:
    """Tier-1 deterministic response-contract selection: the priority-ordered narrow cue tuple, first
    match wins, None on no match OR a non-Latin query (the cue list is English; downstream fails open
    to `default`). Pure regex, no I/O, no LLM. Runs DARK on every eligible turn (the xc_detect
    precedent) — the flag decides only whether the value is passed down, never whether it is stamped."""
    q = query or ""
    for name, rx in _RC_PATTERNS:
        if rx.search(q):
            return name
    return None


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
