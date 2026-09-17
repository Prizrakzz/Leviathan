"""Output-register linter — flags INTERNAL representation leaking into a reader-facing answer.

The reasoner grounds on the causal graph's signs / driver-ids / thresholds, but the PROSE must read in a
commodity researcher's register (bullish/bearish, spelled-out contract names) — NOT `conf=high`, a bare `(+)`,
a raw slug like `soybeans_no_2_dce`, or "the node fired". This deterministic detector complements the LLM judge
with an objective, free signal on whether the register discipline held (and is reusable at serving time to warn
or auto-flag). Patterns are deliberately conservative to avoid false positives (a quant legitimately says "leg",
"tail", "edge"), so it under-flags rather than cries wolf.
"""
from __future__ import annotations

import functools
import re

# Unambiguous internal markers — these never belong in reader prose.
_MARKERS = re.compile(r"(conf\s*=|sign\s*=|edge_type|any_n_of|silver_ref|silver_status|target_metric\s*=)", re.I)
# A bare +/- used as a direction marker: "(+)", "(-)", "(+/-)", "sign +".
_SIGN = re.compile(r"\(\s*[+\-]\s*\)|\(\s*\+\s*/\s*\-\s*\)|\bsign\s*[:=]?\s*[+\-]")
# Causal-graph jargon that a researcher would never write.
_JARGON = re.compile(r"\bnode fired\b|\bthe node\b|\bcausal node\b|\bgraph edge\b|\bthe edge sign\b", re.I)
# Internal-architecture prose that names OUR layers, not the market — a reader must never see these (P1.1 A1).
# NB: 'the node fired' is already covered by _JARGON; do not duplicate it here.
_PROSE_PHRASES = re.compile(
    r"\bcausal graph\b|\bmapped graph\b|\blive-feature layer\b|\bsilver numbers layer\b|\bdated evidence item\b",
    re.I)
# SAGIS/CEC crop codes (silver_sagis_cec.crop, numbers-depth wave Lane A3) are UNDERSCORED tokens but are
# NOT contract slugs, so the _slugs() hierarchy check never flags them — yet an underscored crop code in
# reader prose is the SAME register leak. Detect + rewrite the underscored forms to a friendly label; the
# single-word SAGIS crops (wheat, soybeans, sorghum, barley, canola, oats, groundnuts) are fine in prose
# and need no handling. The rewrite is a plain de-underscore, so sanitize() stays idempotent.
_SAGIS_CROP_CODES = ("total_maize", "white_maize", "yellow_maize", "sunflower_seed", "dry_beans")
_SAGIS_CROP_RX = re.compile(r"\b(" + "|".join(re.escape(c) for c in _SAGIS_CROP_CODES) + r")\b")


@functools.lru_cache(maxsize=1)
def _slugs() -> tuple[str, ...]:
    """Multi-token contract slugs that must NOT appear verbatim in prose (spell out 'the Dalian soybean contract').
    Single-word ids (corn, cotton, cocoa) are fine in prose, so only underscored slugs are flagged."""
    try:
        from leviathan.graphrag import evidence as ev
        contracts = ev._hier().get("contracts") or {}
        return tuple(sorted({c for c in contracts if "_" in c}, key=len, reverse=True))
    except Exception:  # noqa: BLE001 — hierarchy missing -> just skip the slug check
        return ()


@functools.lru_cache(maxsize=1)
def _labeled_metric_slugs() -> tuple[str, ...]:
    """Underscored numbers-registry METRIC ids that carry an analyst `label` (owner's word 2026-08-22:
    internal names never reach prose). LABELED-ONLY by design: a labeled metric's slug in reader prose
    is a regression (the display layer exists and was bypassed), while an unlabeled metric's slug is
    today's accepted state -- the fence tightens family-by-family exactly as labels land, never as a
    false-positive storm over the legacy family."""
    try:
        from leviathan.graphrag.numbers.registry import load_registry
        reg = load_registry()
        out = set()
        for ts in reg.tables.values():
            for mid, m in (ts.metrics or {}).items():
                if "_" in mid and getattr(m, "label", ""):
                    out.add(mid)
        return tuple(sorted(out, key=len, reverse=True))
    except Exception:  # noqa: BLE001 -- registry missing -> just skip the metric-slug check
        return ()


@functools.lru_cache(maxsize=1)
def _metric_labels() -> tuple[tuple[str, str], ...]:
    """(metric slug, analyst label) pairs the SANITIZER may substitute, longest-slug-first.

    PA-10(b) (2026-08-25): `_labeled_metric_slugs` has DETECTED this class since the GN-2 label fold, and
    `sanitize` repaired only contract slugs (968-969), regime ids (970-971) and SAGIS crop codes (972) --
    so the one leak class the estate can name with the reader's own word for it was the one class left
    unrepaired. The detector is untouched: the fence's COUNT still reports every occurrence (that number is
    the run-6 census' instrument), and repair is what changes.

    AN AMBIGUOUS SLUG IS NOT SUBSTITUTED. The same metric id lives on several cards ("su_ratio" is three
    metrics on three cards until PA-2's labels land), and picking one card's label for a bare token in
    prose would assert a meaning the text may not have -- the estate's standing refusal ("both labels or
    neither, and never a guess from a partial pair", citations.py). Measured over the shipped registry at
    authoring time: 203 labeled underscored slugs, ZERO ambiguous, so today this excludes nothing; it is
    the fence that keeps a future duplicate label from minting a wrong analyst name.

    Deterministic by construction: sorted by (-len, slug), so equal-length slugs cannot ride dict order."""
    try:
        from leviathan.graphrag.numbers.registry import load_registry
        by_slug: dict[str, set[str]] = {}
        for ts in load_registry().tables.values():
            for mid, m in (ts.metrics or {}).items():
                lab = str(getattr(m, "label", "") or "").strip()
                if "_" in mid and lab:
                    by_slug.setdefault(mid, set()).add(lab)
        return tuple((mid, next(iter(labs))) for mid, labs in
                     sorted(by_slug.items(), key=lambda kv: (-len(kv[0]), kv[0])) if len(labs) == 1)
    except Exception:  # noqa: BLE001 -- registry missing -> no metric repair, exactly today's behaviour
        return ()


def _regime_ids() -> tuple[str, ...]:
    """Convergence-regime ids (bullish_drought_squeeze, ...) that must be humanized in prose, longest-first.
    Sourced from the display registry (authoritative over the causal DAGs)."""
    try:
        from leviathan.graphrag import display as dp
        return dp.all_regime_ids()
    except Exception:  # noqa: BLE001 — registry missing -> skip regime handling
        return ()


def _strip_mermaid(text: str) -> str:
    return re.sub(r"```mermaid.*?```", " ", text or "", flags=re.S)   # the diagram MAY carry signs; the prose may not


def _ctx(text: str, m) -> str:
    return text[max(0, m.start() - 12):m.end() + 12].replace("\n", " ").strip()


# -- Price/positioning register fence (PRICE_OBSERVABILITY W0.1) -----------------------------------------
# The fence lives in the REGISTER, not the DATA: valuation/flow prose is a leak even when no row could back
# it. Lane A = hard-leak phrase CLASSES (`_VALUATION_PHRASES`=R2, `_FLOW_PHRASES`=R8) plus two structural
# CLASS rules (forward-convergence, persistence-denial) that fence the CLASS, not a word list. Lane B = bare
# mood-adjectives gated on a price/positioning WINDOW noun (ag prose collides on bare 'rich'/'crowded', so a
# window noun must be present and the ag-collision nouns are excluded). Lane A + class rules ride
# register_leaks (so they extend to the suggester's chip drop for free); Lane B rides the raw counters
# (`count_valuation_words`/`count_flow_words`) plus `lane_b_hits` for the chip guard. sanitize() STRIPS the
# offending sentence for every new lane -- never a paraphrase, which would mint a claim no row backs.
_VALUATION_PHRASES = re.compile(
    r"\bprice (target|objective)s?\b"
    r"|\btake[- ]profits?\b"
    r"|\bstop[- ]loss(es)?\b"
    r"|\b(go|get|stay|add to) (long|short)s?\b"
    r"|\bbuy the dip\b"
    r"|\b(fade|fading) the (move|rally|spread|breakout)\b"
    r"|\bworth fading\b"
    r"|\b(spread|premium|discount|basis)s? (is|are|looks?|trades?|sits?|screens?|seems?|appears?)"
    r"( \w+ly)? (cheap|rich|expensive)\b"
    r"|\brelative value trade\b"
    r"|\b(under|over)valued\b"
    r"|\bmispriced\b"
    r"|\bdislocated\b"
    r"|\boverdone\b"
    r"|\bovershot\b"
    r"|\bat attractive levels\b"
    r"|\bfair value\b"
    r"|\bscreens (cheap|rich|expensive)\b"
    # Reversion idioms that carry the forward-convergence CLASS without an in-sentence spread-noun (W0.3
    # S1.F4: the plan enumerates bare "due for a correction" / "mean reversion favors the discount narrowing"
    # as class positives; the spread-noun+verb+futurity triple misses them, so fence the idiom directly).
    r"|\bdue for a (correction|pullback|reversal|bounce|snapback|reversion)\b"
    r"|\bmean[- ]reversion\b"
    # Entry/timing BUY-VERDICT idioms (F2: the bait row "is this a good level to buy?" produced a genuine buy
    # recommendation that escaped the cheap/rich lexicon -- val=flow=0, so `banned_valuation: 0` false-passed.
    # These are pure market-timing advice, banned for the same reason as price-targets/take-profit. Each alt
    # requires an explicit buy/enter/accumulate verb, the noun-phrase "a buy/sell", "entry (point)", or
    # "buying opportunity", so honest level/range prose ("prices entered a new range") never trips.
    r"|\b(good|great|nice|solid|attractive|cheap|decent|compelling)\s+(level|zone|area|spot|price|point)s?\s+to\s+(buy|accumulate|enter|add|get\s+long|load\s+up)\b"
    r"|\bgood\s+(time|point|spot|opportunity)\s+to\s+(buy|accumulate|enter|add)\b"
    r"|\battractive\s+entry\b"
    r"|\bentry\s+point\b"
    r"|\b(good|great|nice|solid|attractive|compelling)\s+entry\b"
    r"|\bbuying\s+opportunit(y|ies)\b"
    r"|\b(is|are|remains?|looks?|screens?|seems?|appears?)\s+a\s+(buy|sell)\b"
    r"|\ba\s+(buy|sell)\s+at\b"
    r"|\bload\s+up\b"
    r"|\baccumulate\s+here\b",
    re.I)
_FLOW_PHRASES = re.compile(
    # POSITIONING squeeze only (R8 intent: "squeeze risk/potential", "vulnerable to a squeeze") -- the
    # FUNDAMENTAL "drought squeeze"/"supply squeeze" regime vocabulary is legitimate researcher prose and the
    # display registry humanizes regime ids INTO it, so a bare squeez\w* would false-flag the mentor voice.
    r"\bsqueez\w* (risk|potential|play|setup|target)"
    r"|\b(short|long|bear|bull|positioning|funds?)[ -]squeez\w*"
    r"|\bvulnerable to (a |an |the )?squeez\w*"
    r"|\b(risk|threat) of (a |an |the )?squeez\w*"
    r"|\bsqueeze the (shorts|longs)\b"
    # POSITIONING/timing squeeze evasions (S1.F4/W0-2/R8): the plan's literal `squeez\w*` cannot ship bare --
    # the display registry humanizes ~24 regime ids INTO "<fundamental> squeeze (price-supportive)" prose
    # ("drought/supply/China demand/delivery/crush/feedstock/premium squeeze"), so a bare stem strips honest
    # mentor content. These idioms are provably disjoint from that regime vocabulary (no regime label carries
    # primed/ripe/poised/set-up-for, "squeeze higher/lower", "squeeze is coming/looms", "getting squeezed",
    # "expect a squeeze", or "squeeze <modal>"), so they widen positioning coverage without the collision.
    r"|\b(primed|ripe|poised|readied) (for|to) (a |an |the )?squeez\w*"
    r"|\bset ?up for (a |an |the )?squeez\w*"
    r"|\bsqueez\w* (higher|lower|sharply|violently)\b"
    r"|\b(a |an |the )?squeez\w* (is |looks? |appears? |seems? )?(coming|looms|looming|imminent|brewing|building|ahead)\b"
    r"|\b(getting|get|got|being) squeez(e|es|ed|ing)\b"
    r"|\bexpect\w* (a |an |the )?squeez\w*"
    r"|\bsqueez\w* (could|would|will|should|may|might)\b"
    r"|\bpain trade\b"
    r"|\bforced (covering|liquidation|selling)\b"
    r"|\bcapitulat\w*"
    r"|\b(shorts|longs) (will|would) (have to|need to)( \w+)?"
    r"|\bcrowded (long|short|trade|position\w*)"
    r"|\bone-sided positioning\b"
    r"|\boffside\b"
    r"|\bcoiled spring\b"
    r"|\bdry powder\b"
    r"|\bstretched positioning\b"
    r"|\bif funds (cover|liquidate|unwind)\b",
    re.I)

# ── W5.0 DERIVATION GATE: the A1/A2 partition of detector A ────────────────────────────────────────────
# User decision 2026-07-28 (supersedes "NO PRICE TARGET, EVER"): the fence gates on DERIVATION, not on
# vocabulary. A price LEVEL is legal iff it is computed from a cited surface and rendered with its
# arithmetic visible; a BARE number is a refusal. Detector A therefore splits in two:
#
#   A1  targets / levels / valuation (`price target`, `fair value`, `cheap/rich`, `undervalued`, ...)
#       -> PERMITTED on an outlook turn, under the derivation gate below.
#   A2  EXECUTION / ADVICE idioms (`go long`, `stop-loss`, `take-profit`, `is a buy`, `load up`,
#       `entry point`, sizing, risk/reward)
#       -> FENCED UNCONDITIONALLY, on every turn including outlook. Nothing can back it: the platform
#          holds no position, no sizing and no risk model, so "go long here" is unbacked BY CONSTRUCTION
#          -- the same test A1 now passes and A2 cannot.
#
# `_EXEC_PHRASES` is a STRICT SUBSET of `_VALUATION_PHRASES` (verbatim alternatives, same relative order),
# so today's fenced behaviour is byte-identical: on a fenced turn the superset already banned every one of
# these. It exists so the OUTLOOK relaxation can keep them fenced while releasing A1.
_EXEC_PHRASES = re.compile(
    r"\btake[- ]profits?\b"
    r"|\bstop[- ]loss(es)?\b"
    r"|\b(go|get|stay|add to) (long|short)s?\b"
    r"|\bbuy the dip\b"
    r"|\b(fade|fading) the (move|rally|spread|breakout)\b"
    r"|\bworth fading\b"
    r"|\brelative value trade\b"
    r"|\bat attractive levels\b"
    r"|\b(good|great|nice|solid|attractive|cheap|decent|compelling)\s+(level|zone|area|spot|price|point)s?\s+to\s+(buy|accumulate|enter|add|get\s+long|load\s+up)\b"
    r"|\bgood\s+(time|point|spot|opportunity)\s+to\s+(buy|accumulate|enter|add)\b"
    r"|\battractive\s+entry\b"
    r"|\bentry\s+point\b"
    r"|\b(good|great|nice|solid|attractive|compelling)\s+entry\b"
    r"|\bbuying\s+opportunit(y|ies)\b"
    r"|\b(is|are|remains?|looks?|screens?|seems?|appears?)\s+a\s+(buy|sell)\b"
    r"|\ba\s+(buy|sell)\s+at\b"
    r"|\bload\s+up\b"
    r"|\baccumulate\s+here\b",
    re.I)
# A2, part two: execution idioms the pre-W5 lexicon never carried (sizing, risk/reward, entry/exit LEVELS,
# scaling). These are NOT members of `_VALUATION_PHRASES` and are deliberately NOT added to
# `register_leaks` -- adding them would change what a FENCED (non-outlook) turn strips, and W5's
# blast-radius gate is "every non-outlook answer byte-identical". They are enforced two ways instead:
# (1) `_is_banned_sentence` strips them on an OUTLOOK turn, where A1 relaxes and the coverage is needed;
# (2) `exec_leaks()` reports them on EVERY turn, so the deck pin `banned_exec: 0` catches them everywhere
# even where the strip does not reach. Widen (1)+(2) freely; touching `register_leaks` is the blast radius.
#
# FOLD-PASS 2026-07-30, two measured defects fixed together:
#   (a) A COMPLETE trade plan survived BOTH registers and PASSED both pins -- 'Buy at 240. Stop at 218.
#       First target is 268. Size at 2% of NAV. Risk 22 points to make 28. I'd be a buyer.' None of those
#       shapes was in the lexicon. They are added below, each bound to a NUMBER or an ordinal.
#   (b) `_EXEC_EXTRA` fired UNCONDITIONALLY on every turn and its looser alternations ate honest ag prose:
#       'Crushers cut exposure to Argentine beans', 'The mill will exit the position of a net exporter',
#       'Traders had time to buy before the ban', 'The entry price for the tender was set by COFCO',
#       'Position sizing of the state reserve auctions was unclear' -- 6 of 12 realistic sentences DELETED
#       on non-outlook turns. So the alternation splits in three:
#         _EXEC_EXTRA  -- unambiguous execution idioms, fire on their own;
#         _EXEC_AMBIG  -- shapes that collide with market-mechanics prose, fire ONLY inside an advisory /
#                         first-or-second-person frame or an IMPERATIVE sentence opening;
#         _POSITION_SIZING -- fires only beside a trading noun ('3 lots'), never beside 'auctions'.
_EXEC_EXTRA = re.compile(
    r"\bsiz(e|ing) (the |your |a )?(trade|position)\b"
    r"|\brisk[/ -]rewards?\b|\brisk[- ]to[- ]reward\b|\breward[/ -]to[- ]risk\b"
    # NB: bare 'target' is deliberately ABSENT -- 'target price' is a real USDA farm-policy term (Price Loss
    # Coverage) AND is the A1 vocabulary W5.0 releases under the derivation gate. Only the ORDER shapes
    # below ('target at 268', 'first target is 268') are fenced, and each requires a number.
    r"|\b(stop|entry|exit)s?\s+(at|of|around|near)\s+\d"
    r"|\btargets?\s+(at|around|near)\s+\d"
    r"|\b(first|second|third|next|final|initial)\s+targets?\s+(is|are|at|near|around|of)?\s*\d"
    r"|\brisk(ing)?\s+\d+(\.\d+)?\s*(points?|ticks?|cents?|bps|handles?|%)\b"
    # 'economies of scale in the crush' is honest ag prose -- the lookbehind drops it while keeping the
    # trading idiom 'scale in below 240'.
    r"|(?<!of )\bscal(e|ing) (in|out)\b"
    r"|\b(initiate|put on|leg into) (a |an |the )?(long|short|position|trade)s?\b"
    # ADVISORY FRAMES only. A bare 'buy now' is NOT fenced: 'China may buy now rather than wait' is honest
    # commentary about a physical buyer. What is fenced is advice ADDRESSED TO THE READER.
    r"|\b(you|we|one) (should|could|might|ought to|want to) (buy|sell|short|go long|accumulate)\b"
    r"|\b(should|would) (you|we|i) (buy|sell|short)\b"
    # 'time to buy' NARROWED to the advisory shape. The bare form deleted 'Traders had time to buy before
    # the ban took effect.' and 'Reasons to buy Brazilian arabica included the frost.' -- both descriptive.
    r"|\b(now|today|this|it'?s|its)\s+(is\s+)?(the\s+)?time\s+to\s+(buy|sell|short|accumulate)\b"
    r"|\bi'?d (buy|sell|be (long|short))\b"
    r"|\b(i|we)\s?[’']d\s+(be\s+)?(a\s+)?(buyer|seller)s?\b"
    r"|\b(i|we)\s+(would\s+be|am|are|remain|stay)\s+(a\s+)?(buyer|seller)s?\b"
    r"|\b(we|i)\s+(like|love)\s+(it|this|them)\s+(here|at)\b"
    r"|\brecommend\w* (buying|selling|shorting|going (long|short))\b",
    re.I)
# The AMBIGUOUS half: identical vocabulary, but every one of these also has an honest market-mechanics
# reading, so each fires only when the sentence carries an advisory frame or opens on an imperative.
_EXEC_AMBIG = re.compile(
    r"\b(entry|exit|stop) (level|price|zone)s?\b"
    # 'cut' pairs ONLY with a trading noun -- "Crushers cut exposure to Argentine beans" is honest prose
    # and must survive, while "cut your longs" is an instruction.
    r"|\b(trim|reduce|cut) (the |your )?(longs?|shorts?|exposure)\b"
    r"|\b(trim|exit|add to) (the |your )?position\b"
    r"|\b(buy|sell|short|long)(ing)?\s+(it\s+|them\s+)?(at|from|near|around|below|above)\s+\d"
    r"|\bsiz(e|ing)\s+(at|to)\s+\d",
    re.I)
_POSITION_SIZING = re.compile(r"\bposition siz\w*\b", re.I)
_TRADING_NOUN = re.compile(
    r"\b(lots?|contracts?|nav|book|risk|trade|trades|longs?|shorts?|equity|capital|notional|percent|%)\b", re.I)
# First/second-person address -- the frame that turns market description into advice. NB 'us' is
# DELIBERATELY absent: `\bus\b` is case-insensitive and would match "US corn ending stocks" on essentially
# every row in this corpus, handing the ambiguous alternations a frame they must not have.
_ADVISORY_FRAME = re.compile(r"\b(you|your|yours|we|our|ours|i|me|my|mine)\b", re.I)
# An IMPERATIVE opening: the sentence (after a bullet marker and an optional discourse conjunction) starts
# on a trading verb. 'Buy at 240.' / '- Trim the position into strength.' are instructions; 'The mill will
# exit the position of a net exporter this year.' is not.
_EXEC_IMPERATIVE = re.compile(
    r"^\s*(?:[-*+•]\s*|\d+[.)]\s*)?(?:so\s+|and\s+|then\s+|but\s+|now\s+|also\s+)?"
    r"(buy|sell|short|long|add|trim|cut|reduce|exit|enter|size|scale|initiate|accumulate|stop|target|risk)\b",
    re.I)
# The C-FAMILY reversion idioms that live inside `_VALUATION_PHRASES` for historical reasons. Detector C
# (forward convergence) stays fenced on outlook turns -- "the premium should narrow" is a SPREAD FORECAST,
# and an outlook leans on regimes, buffers and episodes, not on convergence. Also a strict subset.
_REVERSION_PHRASES = re.compile(
    r"\bdue for a (correction|pullback|reversal|bounce|snapback|reversion)\b"
    r"|\bmean[- ]reversion\b",
    re.I)

# The two register scopes. `sanitize`/`_strip_banned_sentences`/`_is_banned_sentence` take this as a
# keyword-only argument DEFAULTED TO `FENCED`, so every existing call site keeps today's behaviour and the
# relaxation can only reach a seam that opted in explicitly. There is deliberately NO os.environ read in
# this module: the mode is decided at the answer.py seam and passed DOWN as an argument, so a mis-plumbed
# enable can never relax the suggester chip guard or the numbers/news/live bodies.
FENCED = "fenced"
OUTLOOK = "outlook"

# -- the derivation gate itself -------------------------------------------------------------------------
# A level is BACKED when the unit that carries it shows the arithmetic and cites every input:
#   (a) an ANCHOR  -- a sentence naming a spot/settle level, carrying a number AND a citation handle;
#   (b) MOVES      -- a sentence carrying signed percentage move(s) AND a citation handle (the episode set);
#   (c) an OPERATOR-- an explicit '->' / 'implies' linking the anchor and the moves to the outputs.
# All three -> derived outputs may be rendered uncited (they are computed, not observed). Any one missing
# -> every sentence carrying an uncited level token is STRIPPED. Fail-closed: the default is NOT backed.
_OUTLOOK_HEADING = re.compile(r"^#{1,6}\s*Outlook\b.*$", re.I | re.M)
_NEXT_HEADING = re.compile(r"^#{1,6}\s+\S", re.M)
# ── D-HP-3 (handle-prose wave, H0): THE GROUPED/RANGED HANDLE SHAPE, and why this module had to learn it.
# MEASURED AT FOLD TIME against the shipped module: `_level_tokens("Use of [N1, 23] fell.")` returned
# `['23']` and `_level_tokens("Use of [N13, 14] fell.")` returned `['14']`. Both `_CIT_HANDLE` and the old
# `_NUM_NOISE` head carried ONLY the SOLITARY `\[[EN]\d+\]` shape, while the bare-CONTINUATION member form
# `[N1, 23]` is explicitly LEGAL to `verify._HANDLE` (verify.py:97 `_H_MEMBER_ANY`, "continuation behind a
# PREFIXED lead: prefix optional", pinned at test_cycle10_no_rewrites.py:180). So a grouped handle's member
# indices shed into `_NUM_TOKEN` as candidate PRICE LEVELS. MEASURED CONSEQUENCE, both legs:
#   * OUTLOOK: `sanitize('Palm olein use of [N1, 23] fell in the quarter.', market_register=OUTLOOK)` == ''
#     -- the whole sentence stripped, fail-closed, for citing its evidence in a grouped token.
#   * FENCED: the sentence survives (the derivation gate is OUTLOOK-scoped -- the plan's clause says
#     "under FENCED ... is STRIPPED"; the measured strip is on OUTLOOK. RECORDED, not silently adopted),
#     but `unbacked_levels`/`unbacked_level_count` -- the `price_target_backed` teeth -- still count `23`
#     as an unbacked level on EVERY register. A counter that charges a citation is the same defect.
# Handle-prose raises grouped-handle density BY DESIGN, so this is a regression VECTOR, not a cosmetic
# parse divergence.
#
# THE SPELLING, AND ITS ONE NAMED DIVERGENCE FROM `orchestrator._HANDLE_TOKEN_RX` (D-HP-6 consumer 8).
# The orchestrator's scrub reads `\[\s*[NE]?\d+[a-z]?(?:\s*[,;<dash>-]\s*[NE]?\d+[a-z]?)*\s*\]` -- the LEAD
# member's prefix is OPTIONAL there. Copying that verbatim into a LEVEL scrubber re-opens the year-range
# hazard `verify._HANDLE` closed deliberately (verify.py:85-92: "`[1980-1990]` and `[5900-9999]` are not
# [handles], because their lead is bare"). MEASURED: with the orchestrator spelling copied verbatim,
# `_level_tokens('band [5900-9999] held.')` goes `['5900','9999']` -> `[]` -- a bracketed price band stops
# being an unbacked level, i.e. the gate passes by being WEAKENED. That is the exact regression class the
# 2026-07-31 `_POLICY_LEAD` narrowing exists to refuse. SO: the LEAD MUST CARRY ITS PREFIX here, which is
# `verify._HANDLE`'s own rule and the one this wave's chosen producer already enforces. Continuations stay
# prefix-optional, which is the whole leak. A solitary BARE `[3]` is excluded for the same reason: it is
# indistinguishable from a bracketed price `[1450]`. DIVERGENCES RECORDED, direction TIGHTENING, both
# asserted in tests/unit/test_dhp_handle_grammar.py.
# ASCII SOURCE: the dash variants are built from CODEPOINTS (verify.py's `_QUOTE_EDGE` discipline).
_H_DASHES = "-" + "".join(chr(c) for c in (0x2010, 0x2011, 0x2012, 0x2013, 0x2014, 0x2015, 0x2212))
_H_SEP = r"(?:,|;|&|/|and|[" + _H_DASHES + r"])"          # verify.py:95, verbatim (`-` FIRST: never a range)
_HANDLE_TOKEN = (r"\[\s*[NE]\d+[a-z]?(?:\s*" + _H_SEP + r"\s*[NE]?\d+[a-z]?)*\s*\]")
_CIT_HANDLE = re.compile(_HANDLE_TOKEN, re.I)
_MOVE_TOKEN = re.compile(r"[+\-−]\s?\d+(?:\.\d+)?\s*%")
_DERIV_OP = re.compile(r"->|→|\bimplie[sd]\b|\bimplying\b|\bworks out to\b|\bgives\b")
# A sentence carrying one of these is stating a DERIVED OUTPUT, not quoting an observed row. It is held to
# the derivation standard EVEN WHEN IT CARRIES A HANDLE -- otherwise a model laundered an unbacked target
# by attaching the episode citation to the sentence that stated the levels ("episodes moved +18% [E2] ->
# 268 / 243 / 220"), which cites the MOVES but never the SPOT the arithmetic started from.
_DERIV_OUTPUT = re.compile(
    r"->|→|\bimplie[sd]\b|\bimplying\b|\bworks out to\b|\bgives\b|\bmedian\b|\bmidpoint\b|\btargets?\b",
    re.I)
# ── FALSE-POSITIVE NARROWING, 2026-07-31 (W5 gate reproduction) ────────────────────────────────────────
# The first VALID W5 judged run failed `price_target_backed` on 7 of 13 pinned rows. A faithful
# reproduction over the reconstructed `structured.tldr`/`structured.mechanism` (the fields the counter
# actually reads -- NOT the rendered answer, whose '## Sources' footer the counter never sees) measured 25
# hits on the four rows that reproduce, of which 23 (92%) were NOT price levels. Six NAMED shapes, each
# closed by its own narrow rule; the ambiguous ones are gated on the SENTENCE FRAME rather than deleted
# from the lexicon. This is the `_EXEC_EXTRA` / `_EXEC_AMBIG` / `_POSITION_SIZING` discipline applied to
# the level detector, and for the same reason: a looser alternation ate honest ag prose there, and here a
# looser EXEMPTION would re-open the laundering the gate exists to refuse.
#
# WHAT IS DELIBERATELY UNCHANGED: the base rule. An uncited number in an uncited sentence is still an
# unbacked level. The genuine catch this run found -- '1,105 USD/mt' stated with no handle on the
# risk/reward bait row -- still fires, and every four-digit bare target in `_LEVEL_TABLE` still fires.
#
# (A) ARROW-AS-RANGE-SEPARATOR, 13 of the 25 hits and the dominant class. `_DERIV_OUTPUT` reads '->' /
#     U+2192 as a DERIVATION OPERATOR, which VOIDS the citation exemption in `unbacked_levels` -- that is
#     correct, and it is there because a model laundered a target by citing the MOVES and never the SPOT.
#     But the engine's own era narration writes a marketing-year RANGE with the same glyph
#     ('MY2008->MY2009'), so sentences cited end-to-end lost their exemption and every [N]-handled MMT
#     trade quantity in them was flagged: the gate was punishing the best-grounded prose in the corpus.
#     The two conventions are separable WITHOUT touching the operator. In the laundering case the arrow is
#     followed by BARE UNCITED numbers ('moved +18% [E2] -> 268 / 243 / 220'); in the range case BOTH
#     sides are 'MY'-prefixed marketing-year LABELS and never a number the reader could trade on. So the
#     range form is scrubbed and the operator is looked for in what remains -- a real derivation arrow
#     elsewhere in the same sentence still fires, and a range arrow alone no longer satisfies `_DERIV_OP`
#     either (that direction TIGHTENS the gate: a range glyph must not certify 'the arithmetic is shown').
_MY_RANGE_ARROW = re.compile(r"MY\s?\d{4}(?:/\d{2,4})?\s*(?:->|→)\s*MY\s?\d{4}(?:/\d{2,4})?")


def _deriv_output(sent: str):
    """`_DERIV_OUTPUT`, with marketing-year RANGE arrows scrubbed first (class A). Returns the match."""
    return _DERIV_OUTPUT.search(_MY_RANGE_ARROW.sub(" ", sent or ""))


_ANCHOR_WORD = re.compile(
    r"\b(spot|settle[sd]?|settlement|front[- ]month|last trade|last settle|current level|currently trad\w+|"
    r"trading at|closed at)\b", re.I)
# Numeric noise that is never a price level: citation handles, ISO/partial dates, marketing years,
# percentages, and bare calendar years.
_NUM_NOISE = re.compile(
    _HANDLE_TOKEN                                    # citation handles (solitary AND grouped/ranged)
    + r"|\b\d{4}-\d{2}(-\d{2})?\b"                   # 2024-01 / 2024-01-10
    # (C) MARKETING YEAR. `\b\d{4}/...` could not fire on 'MY2000/01' -- the 'MY' prefix destroys the
    # leading word boundary, so nothing was scrubbed, and `_NUM_TOKEN`'s `(?<![\w.])` then blocked '2000'
    # (preceded by 'Y') while letting the two-digit TAIL '01' through as a level. 2 of the 25 hits. The
    # dash form 'MY2008-MY2009' was already safe (both halves MY-prefixed); only the SLASH form leaked.
    r"|\b(?:MY\s?)?\d{4}/\d{2,4}\b"                  # 2023/24 or MY2000/01 marketing year
    r"|\b\d{1,2}/\d{1,2}(/\d{2,4})?\b"               # 3/15 or 3/15/24
    r"|[+\-−]?\s?\d+(?:\.\d+)?\s*%"             # percentages (a MOVE, not a level)
    r"|\bQ[1-4]\b", re.I)
# FOLD-PASS 2026-07-30. The old token regex was `\d{1,3}(?:,\d{3})*(?:\.\d+)?(?![\w%])` -- it capped the
# integer run at THREE digits and could only extend it through a comma, and the `(?![\w%])` tail made it
# fail to match ANY prefix of a longer run. Measured consequence: `_level_tokens('target 1450 here') == []`
# and `sanitize('Soybeans should reach 1450 ...', OUTLOOK)` served the number VERBATIM. That is the
# MAJORITY of this platform's quote conventions -- soybeans/rough rice ~1000-1800 cents, cocoa 2000-12000
# USD/t, MCPO ~3500-4500 MYR/t, palm olein ~7000-9000 CNY/t. The plan's own worked example (227.25 ->
# 268/243/220) is 3-digit, which is exactly why every test and every lint probe missed it.
_NUM_TOKEN = re.compile(
    r"(?<![\w.])\d{1,3}(?:,\d{3})+(?:\.\d+)?(?![\w%])"   # thousands-separated FIRST (ordered alternation)
    r"|(?<![\w.])\d+(?:\.\d+)?(?![\w%])")                # ... else a bare run of any length
# A bare 4-digit integer is a CALENDAR YEAR only when it is plausibly one (1900-2035) AND the sentence
# frames it temporally. The old `^(1[89]|20)\d\d$` discarded 1800-2099 unconditionally -- so 'cocoa at
# 2050' and even '1,850' were silently years and never levels. A separator or a decimal point is never a
# year, so '1,850' and '2010.5' are levels regardless of frame.
_YEAR_SHAPE = re.compile(r"^(?:19\d\d|20[0-2]\d|203[0-5])$")
_YEAR_LEAD = re.compile(                                  # 'in 2010', 'since mid-2014', 'back in 1994'
    r"\b(?:in|since|during|throughout|through|until|till|from|after|before|around|circa|by|as\s+of|"
    r"back\s+in|between|versus|vs\.?)\s+(?:(?:early|mid|late)[-\s])?$", re.I)
# (B) THE YEAR FRAMES, 5 of the 25 hits. Every frame test below anchors with `$` IMMEDIATELY before the
# token, so any intervening word defeated it and a plain calendar year became a price level. Three gaps
# were measured, and each is closed by naming the shape rather than by loosening the anchor:
#   * a MONTH between the lead and the year -- 'as of October 2009', 'as of December 2007'. `as of` is in
#     `_YEAR_LEAD` already; the month is what broke it. A month name immediately before a year-shaped
#     integer is a DATE unconditionally -- no price is ever written 'December 2007' -- so `_YEAR_MONTH`
#     needs no trailing-noun corroboration, exactly like `_YEAR_LEAD`.
#   * a POSSESSIVE determiner -- "Indonesia's 2022 ban". Same shape as `_YEAR_DET`, so it carries the same
#     corroboration requirement (`_YEAR_NOUN` must follow), which is what keeps it narrow.
#   * a determiner + ADJECTIVE -- 'The subsequent 2010 rally'. NB the adjective slot is a CLOSED LIST, not
#     `\w+`: with a free slot, 'the price target 2025 remains ...' would satisfy determiner + 2 words +
#     trailing lowercase noun and a real level would be silently reclassified as a year. None of the words
#     below can appear in a level frame.
# 1850 / 1,850 / 1015.5 are untouched by all of this: `_YEAR_SHAPE` rejects 1850 outright, and a comma or
# a decimal point short-circuits `_is_year_token` before any frame is consulted.
_YEAR_MONTH = re.compile(
    r"\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?"
    r"|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+$", re.I)
_YEAR_POSS = re.compile(r"\b[\w.]+[’']s\s+(?:(?:early|mid|late)[-\s])?$", re.I)
_YEAR_ADJ = (r"(?:subsequent|following|ensuing|preceding|prior|previous|next|last|latter|former|earlier"
             r"|later|same|infamous|notorious|famous|record|historic|devastating|eventual|initial"
             r"|original|brutal|severe|recent|big|great|major|so-called)")
_YEAR_DET = re.compile(
    r"\b(?:the|that|this|its|our|their)\s+(?:" + _YEAR_ADJ + r"\s+)?(?:(?:early|mid|late)[-\s])?$", re.I)
_YEAR_START = re.compile(r"(?:^|[(\[,;]\s*)$")            # clause-initial '2022 saw prices double'
_YEAR_NOUN = re.compile(r"^\s*[-–—/]?\s*[a-z]", re.I)   # '... 2010 case', '... 1994 frost'


def _is_year_token(scrubbed: str, m) -> bool:
    """Is this `_NUM_TOKEN` match a calendar year rather than a price level? See `_YEAR_SHAPE` above."""
    tok = m.group(0)
    core = tok.replace(",", "")
    if "," in tok or "." in core or not _YEAR_SHAPE.match(core):
        return False
    before, after = scrubbed[:m.start()], scrubbed[m.end():]
    if _YEAR_LEAD.search(before) or _YEAR_MONTH.search(before):
        return True
    framed = _YEAR_DET.search(before) or _YEAR_POSS.search(before) or _YEAR_START.search(before)
    return bool(framed and _YEAR_NOUN.match(after))


# (D) SIGMA / Z-SCORE / PERCENTILE, 2 of the 25 hits: '0.215615 sigma above its 5-year mean'. A
#     dimensionless standard-deviation distance is not a level. ADJACENCY-gated, not sentence-gated -- the
#     statistic word must sit immediately beside the token -- so the real price in the SAME sentence
#     ('1,105 USD/mt') is untouched and still counts. That row must, and does, still fail.
# (E) POLICY / STATUTE IDENTIFIER, 1 hit: 'the US Section 301 / retaliatory tariff driver'. One token, and
#     the whole of that row's failure. A number that NAMES a legal instrument is not a quote.
# (F) HYPHENATED QUANTITY COMPOUND, 1 hit: 'a 15-million-bushel U.S. ...'. `_NUM_TOKEN`'s `(?![\w%])` tail
#     is satisfied by the hyphen, so the unit that follows was never seen. The exclusion is a CLOSED LIST
#     of magnitude/volume/duration words, NOT `-\w`: '240-260' must stay two levels (a fabricated range is
#     exactly the shape the gate exists for), and '$4.85-per-bushel' must stay one -- neither 'per' nor a
#     digit is in the list, and price units (cent/dollar/point) are deliberately excluded from it too.
_SIGMA_UNIT = re.compile(
    r"^\s*(?:sigma|σ|z[-\s]?scores?|standard deviations?|std\.?\s?devs?|percentiles?)\b", re.I)
_SIGMA_LEAD = re.compile(
    r"\b(?:sigma|σ|z[-\s]?score|standard deviations?|percentile)\s+(?:of|at|=)\s+$", re.I)
# NARROWED after the adversarial pass (2026-07-31). The first draft carried 22 lead words on the
# strength of ONE measured token ('Section 301'), and nine of them -- order, number, no., act, title,
# rule, schedule, resolution, docket -- are ordinary desk vocabulary that sits directly in front of a
# price. `order` was fatal: 'work the order 1850', 'a resting order 4.85', 'our limit order 1450',
# 'put a stop order 1780' all went unbacked=1 -> 0 and were SERVED VERBATIM instead of stripped, in
# BOTH registers. That is the gate passing by being weakened -- the precise regression this fix
# exists to avoid. Only the legal-instrument lexicon survives, and every word here is one no desk
# uses before a level. Do not re-add a word without a measured false positive to justify it.
_POLICY_LEAD = re.compile(
    r"\b(?:section|chapter|article|clause|paragraph|para|annex|appendix|exhibit"
    r"|regulation|law|statute|decree)\s+$", re.I)
_HYPHEN_QTY = re.compile(
    r"^-(?:million|billion|trillion|thousand|hundred|bushel|bu|tonne|ton|metric|mmt|mt|kt|acre|hectare|ha"
    r"|day|week|month|year|hour|lot|head|litre|liter|gallon|pound|lb|kg|kilo|bag|container|vessel|cargo"
    r"|mile|km|member|country|page|fold)s?\b", re.I)


def _level_tokens(sent: str) -> list[str]:
    """Candidate PRICE-LEVEL tokens in one sentence. Deliberately narrow: handles, dates, marketing years,
    percentages and TEMPORALLY-FRAMED calendar years are scrubbed first, and a token must carry a decimal
    point or at least two integer digits -- so 'three episodes', 'the 8th percentile' and 'in 2010' are
    never levels while '227.25', '4.85', '268', '1,240', '1450' and '8500' are.

    Three further NAMED shapes are excluded (2026-07-31 W5 repro, classes D/E/F above), each requiring a
    corroborating token IMMEDIATELY beside the number: a statistic unit ('0.215615 sigma'), a statute lead
    ('Section 301'), or a magnitude/volume compound modifier ('15-million-bushel'). Nothing here relaxes
    the base rule -- a bare, uncited number in an uncited sentence remains an unbacked level."""
    scrubbed = _NUM_NOISE.sub(" ", sent or "")
    out: list[str] = []
    for m in _NUM_TOKEN.finditer(scrubbed):
        tok = m.group(0)
        core = tok.replace(",", "")
        if _is_year_token(scrubbed, m):
            continue
        before, after = scrubbed[:m.start()], scrubbed[m.end():]
        if _POLICY_LEAD.search(before):                                  # (E) 'Section 301'
            continue
        if _HYPHEN_QTY.match(after):                                     # (F) '15-million-bushel'
            continue
        if "." in core and (_SIGMA_UNIT.match(after) or _SIGMA_LEAD.search(before)):
            continue                                                     # (D) '0.215615 sigma above'
        if "." in core or len(core.split(".")[0]) >= 2:
            out.append(tok)
    return out


def _outlook_span(text: str) -> tuple[int, int]:
    """(start, end) of the DERIVATION UNIT inside `text`: the '## Outlook' section when one is rendered,
    else the whole text. Callers use the SPAN, not the substring, so the derivation verdict can be applied
    PER SENTENCE POSITION -- one complete derivation under '## Outlook' must not exempt a level minted
    three sections away (which is exactly what a text-wide flag did before the 2026-07-30 fold-pass)."""
    t = text or ""
    m = _OUTLOOK_HEADING.search(t)
    if not m:
        return (0, len(t))
    start = m.end()
    nxt = _NEXT_HEADING.search(t, start)
    return (start, nxt.start() if nxt else len(t))


def _iter_sentences(text: str):
    """(offset, sentence) pairs on the SAME boundaries `_SENT_ITER.split` produces, but carrying the
    offset so a sentence can be tested for membership of the derivation unit."""
    pos = 0
    for m in _SENT_ITER.finditer(text or ""):
        yield pos, (text or "")[pos:m.start()]
        pos = m.end()
    yield pos, (text or "")[pos:]


def outlook_unit(text: str) -> str:
    """The DERIVATION UNIT for a piece of prose: the '## Outlook' section when one is rendered, else the
    whole text. Scoping to the section keeps a derivation shown under '## Outlook' from silently backing a
    level minted three sections away."""
    lo, hi = _outlook_span(text)
    return (text or "")[lo:hi]


def outlook_derivation_ok(text: str) -> bool:
    """Is the arithmetic SHOWN and every input CITED in this text's derivation unit? Fail-closed."""
    unit = outlook_unit(text)
    if not unit.strip():
        return False
    anchor = moves = False
    for sent in _SENT_ITER.split(unit):
        cited = bool(_CIT_HANDLE.search(sent))
        if cited and _ANCHOR_WORD.search(sent) and _level_tokens(sent):
            anchor = True
        if cited and _MOVE_TOKEN.search(sent):
            moves = True
    # Class A, the tightening direction: a marketing-year RANGE arrow must not certify "the arithmetic is
    # shown". Scrubbing it here means an answer that carries only 'MY2008->MY2009' no longer satisfies the
    # OPERATOR leg of the gate, so it cannot fail OPEN through the engine's own era narration.
    return bool(anchor and moves and _DERIV_OP.search(_MY_RANGE_ARROW.sub(" ", unit)))


def unbacked_levels(text: str, *, derivation_ok: bool | None = None) -> list[tuple[str, str]]:
    """(level-token, short-context) for every price level stated WITHOUT backing -- an uncited number in a
    sentence that carries no citation handle, on prose whose derivation is not complete. This is the
    deterministic teeth behind `price_target_backed`: it catches the FABRICATED number the lexicon never
    could ('$4.85' with nothing behind it), which is the failure mode this platform exists to refuse.

    SCOPED (fold-pass 2026-07-30): a complete derivation exempts ONLY the sentences that live inside the
    derivation unit -- `outlook_unit`'s own span. Before this the verdict was text-wide, so one worked
    example under '## Outlook' laundered every bare level in every other section, which is precisely the
    laundering `outlook_unit` exists to prevent. When no '## Outlook' heading is rendered the whole text
    IS the unit, so single-section prose behaves exactly as it did."""
    prose = _strip_mermaid(text)
    if derivation_ok is None:
        derivation_ok = outlook_derivation_ok(prose)
    lo, hi = _outlook_span(prose)
    hits: list[tuple[str, str]] = []
    for off, sent in _iter_sentences(prose):
        if derivation_ok and lo <= off < hi:
            continue
        # A cited number traces to a row and is backed BY the citation -- unless the sentence is stating a
        # DERIVED output, which no single handle can back (the arithmetic needs its anchor too).
        if _CIT_HANDLE.search(sent) and not _deriv_output(sent):
            continue
        for tok in _level_tokens(sent):
            hits.append((tok, sent.strip()[:60]))
    return hits


def unbacked_level_count(text: str) -> int:
    """RAW pre-sanitize unbacked-level count (the DP-6 counter idiom): measured on EVERY turn, enforced by
    the strip only where the register relaxed. Pinned by the deck as `price_target_backed`."""
    return len(unbacked_levels(text))


def _exec_extra_hits(sent: str) -> list:
    """A2-EXTRA matches in ONE sentence. The unconditional idioms always fire; the AMBIGUOUS alternations
    (entry/exit/stop LEVEL, trim/cut exposure, add-to/exit the position, buy/sell at <n>, size at <n>)
    fire only when the sentence carries a first-or-second-person advisory frame or OPENS on an imperative
    trading verb -- otherwise 'The mill will exit the position of a net exporter this year.' is deleted.
    'position sizing' needs a trading noun beside it, so the state reserve's auctions survive."""
    hits = list(_EXEC_EXTRA.finditer(sent))
    if _ADVISORY_FRAME.search(sent) or _EXEC_IMPERATIVE.match(sent):
        hits += list(_EXEC_AMBIG.finditer(sent))
    if _TRADING_NOUN.search(sent):
        hits += list(_POSITION_SIZING.finditer(sent))
    return hits


def exec_leaks(text: str) -> list[tuple[str, str]]:
    """(token, short-context) for each A2 EXECUTION/ADVICE idiom. Unconditional -- there is no register
    scope in which this is permitted, so the deck pins it to 0 on every row, outlook included.

    SENTENCE-SCOPED for the EXTRA half (fold-pass 2026-07-30): the ambiguous alternations need the
    sentence's frame to decide, and reporting must agree with what `_is_banned_sentence` strips."""
    prose = _strip_mermaid(text)
    hits: list[tuple[str, str]] = []
    for m in _EXEC_PHRASES.finditer(prose):
        hits.append((m.group(0).strip(), _ctx(prose, m)))
    for _off, sent in _iter_sentences(prose):
        for m in _exec_extra_hits(sent):
            hits.append((m.group(0).strip(), _ctx(sent, m)))
    return hits


def count_exec_words(text: str) -> int:
    """RAW pre-sanitize A2 count (mirrors count_valuation_words/count_flow_words)."""
    return len(exec_leaks(text))


# CLASS rule members (both pure regex): a spread-noun + a convergence verb + a modal/futurity marker in ONE
# sentence is a forward-convergence claim; a persistence-denial word beside a price/spread noun is the mirror.
# Past-tense dated facts ("the spread narrowed through 2016 [N2]") carry no futurity marker and stay legal.
_SPREAD_NOUN = re.compile(r"\b(premium|discount|spread|basis|gap)\b", re.I)
_CONVERGE_VERB = re.compile(
    # Inflectional forms only (S1.F1): open `\w*` stems for narrow/close/correct greedily match the -ly ADVERBS
    # 'narrowly'/'closely'/'correctly' -- honest prose ("watched closely", "narrowly defined", "interpreted
    # correctly"), NOT convergence verbs. Anchoring to the verb inflections stops the false fence while still
    # catching narrow(s|ed|ing) / close(s|d)/closing / correct(s|ed|ing|ion).
    r"\b(normali[sz]\w*|revert\w*|converge\w*|narrow(s|ed|ing)?|clos(e|es|ed|ing)"
    r"|resolv\w*|correct(s|ed|ing|ion|ions)?|compress\w*|unwind\w*|snap)\b",
    re.I)
_FUTURITY = re.compile(r"\b(should|will|would|could|likely|room to|due|poised|set to|expect\w*)\b", re.I)
_PRICE_SPREAD_NOUN = re.compile(r"\b(price|spread|premium|discount|basis|gap)s?\b", re.I)
_PERSISTENCE = re.compile(r"\b(unsustainable|cannot last|won[\u2019']?t last|rarely persists?|never stays)\b", re.I)
# Lane B: the ambiguous mood-adjectives split into a valuation triad and a positioning triad, each gated on a
# WINDOW noun (or a relative-value comparison marker) and suppressed when an ag-collision noun is the subject.
_LANE_B_VAL_RX = re.compile(r"\b(cheap|rich|expensive)\b", re.I)
_LANE_B_FLOW_RX = re.compile(r"\b(stretched|vulnerable|crowded)\b", re.I)
_LANE_B_ADJ = re.compile(r"\b(cheap|rich|expensive|stretched|vulnerable|crowded)\b", re.I)
_WINDOW_NOUN = re.compile(
    r"\b(prices?|premiums?|discounts?|spreads?|basis|valuation|positioning|net (long|short)|net length"
    r"|book|longs|shorts)\b", re.I)
_WINDOW_COMPARISON = re.compile(
    r"\b(vs\.?|versus|relative to|compared (to|with)|cheaper than|richer than)\b", re.I)
# "suppl(y|ies)": the pattern carried the plural only, so "expensive ... supply" statements (honest
# FX/cost fundamentals) counted as Lane-B valuation -- one token explained all three 2026-08-04
# banned_valuation deck reds (verified in code and reproduced across runs by two independent passes).
_EXCLUDED_NOUN = re.compile(r"\b(stocks?|suppl(?:y|ies)|crop|soil|lineup)\b", re.I)   # honest ag fundamentals -> not Lane B
_SENT_ITER = re.compile(r"(?<=[.!?;])\s+")                                      # sentence boundaries (counter/scan)
# The strip MUST segment identically to the scanner (S1.F2/W0-1): the scanner (_SENT_ITER) does NOT break on a
# bare `\n` lacking terminal punctuation, so a line-wrapped/bulleted class-rule triple is ONE sentence and IS
# flagged. A prior `|\n+` here split that unit into leak-free fragments -> the strip removed nothing and
# register_leaks(sanitize(x)) != [] (invariant broken). Dropping `\n+` keeps the two passes on the same unit.
_SENT_KEEP = re.compile(r"([.!?;]\s+)")                                         # sentence + delimiter (strip)


def _lane_b_in_sentence(sent: str, rx) -> int:
    if _EXCLUDED_NOUN.search(sent):
        return 0
    if _WINDOW_NOUN.search(sent) or _WINDOW_COMPARISON.search(sent):
        return len(rx.findall(sent))
    return 0


def _class_rule_hits(prose: str) -> list[tuple[str, str]]:
    hits: list[tuple[str, str]] = []
    for sent in _SENT_ITER.split(prose):
        if _SPREAD_NOUN.search(sent) and _CONVERGE_VERB.search(sent) and _FUTURITY.search(sent):
            hits.append(("forward-convergence", sent.strip()[:60]))
        if _PERSISTENCE.search(sent) and _PRICE_SPREAD_NOUN.search(sent):
            hits.append(("persistence-denial", sent.strip()[:60]))
    return hits


def count_valuation_words(text: str) -> int:
    """RAW pre-sanitize valuation count (DP-6): Lane A R2 phrases + both class rules + Lane B valuation triad."""
    prose = _strip_mermaid(text)
    n = len(_VALUATION_PHRASES.findall(prose))
    for sent in _SENT_ITER.split(prose):
        if _SPREAD_NOUN.search(sent) and _CONVERGE_VERB.search(sent) and _FUTURITY.search(sent):
            n += 1
        if _PERSISTENCE.search(sent) and _PRICE_SPREAD_NOUN.search(sent):
            n += 1
        n += _lane_b_in_sentence(sent, _LANE_B_VAL_RX)
    return n


def count_flow_words(text: str) -> int:
    """RAW pre-sanitize flow/positioning count (DP-6): Lane A R8 phrases + Lane B positioning triad."""
    prose = _strip_mermaid(text)
    n = len(_FLOW_PHRASES.findall(prose))
    for sent in _SENT_ITER.split(prose):
        n += _lane_b_in_sentence(sent, _LANE_B_FLOW_RX)
    return n


def lane_b_hits(text: str) -> int:
    """Lane B windowed-adjective count only (the suggester chip guard: Lane A already rides register_leaks)."""
    prose = _strip_mermaid(text)
    n = 0
    for sent in _SENT_ITER.split(prose):
        n += _lane_b_in_sentence(sent, _LANE_B_VAL_RX) + _lane_b_in_sentence(sent, _LANE_B_FLOW_RX)
    return n


# ══ S7b R1 -- WORDS ARE FREE (owner ruling 2026-09-15 16:30Z, superseding the closed-world ruling). ══
# THE FLAG KEEPS ITS NAME AND CHANGES ITS MEANING. `GRAPHRAG_REGISTER_LICENCE` no longer buys a
# sentence its words back by proving a figure behind them; it RETIRES THE VALUATION / FLOW-WORD STRIKE
# outright. The owner read HEAD's fence striking sentences for the words `crowded`, `rich` and
# `tight` and ruled: the writer should talk like that. The estate's own doctrine already said it --
# `feedback_fences_correct_never_delete`: WORDS ARE FREE, ONLY PRINTED FIGURES MUST BE BACKED -- and two
# rounds of "licence" were spent earning back a freedom the writer should simply have had.
#
# SO THE CLASSIFICATION IS THE INSTRUMENT. Every rule the FENCED strip can convict a sentence on was
# read and put in one of two columns; the column decides what the flag does to it, and nothing else
# does. The full table with its corpus exemplars is `scratchpad/s7b/fix4/RULE_CLASSIFICATION.md`; the
# short form is here, because a reader of this file must not have to go and find it.
#
#   RETIRED UNDER THE FLAG -- a rule that strikes on WORDS ALONE:
#     * Lane B, both triads (`cheap|rich|expensive` / `stretched|vulnerable|crowded` beside a window
#       noun)                     -- "Positioning looks crowded here."
#     * the Lane-A BAR shapes     -- "The spread screens cheap." / "Managed money is crowded long."
#     * the Lane-A SQUEEZE family, all eighteen alternations -- "vulnerable to a squeeze", "a squeeze
#       is coming", "expect a squeeze": a positioning OPINION, printing no figure and dating nothing
#     * the Lane-A flow nouns     -- "pain trade", "forced covering", "capitulation", "offside",
#       "coiled spring", "dry powder", "one-sided positioning", "if funds cover"
#     * the Lane-A valuation ADJECTIVES that name no figure -- "undervalued", "overvalued",
#       "mispriced", "dislocated", "overdone", "overshot", "screens cheap"
#   KEPT, FLAG ON OR OFF, BYTE FOR BYTE:
#     * A2 EXECUTION (`_EXEC_PHRASES` / `_EXEC_EXTRA` / `_EXEC_AMBIG` / `_POSITION_SIZING`) -- the
#       owner's ratified decision, neither widened nor relieved by this ruling
#     * the two structural CLASS rules: forward convergence (a spread noun + a convergence verb + a
#       futurity marker) and persistence denial ("that premium cannot last") -- both are FORECASTS
#     * the C-family REVERSION idioms ("due for a correction", "mean-reversion") -- forecasts again
#     * the two Lane-A members that name a FIGURE the platform cannot back: `price target` /
#       `price objective` and `fair value` (the ruling names both)
#     * every printed-figure fence outside this module's word lanes: `bare_digit_verdict`, the OUTLOOK
#       derivation gate, `unbacked_levels` -- none of them is asked about a word at all
#
# THE PRE-EXISTING A2 HOLE IS NAMED, NOT WIDENED (ruling (2a)). A sentence that hangs an instruction
# off a clause edge in a shape the A2 detector never carried -- "..., so hold the length into the
# report" -- ships at HEAD today, because `_EXEC_PHRASES` and `_EXEC_EXTRA` do not see it and nothing
# else charges it. Rounds 3 and 4 tried to close that hole with a frame list inside the licence and the
# review measured both attempts failing in both directions at once (advice still shipping, readings
# deleted). This round does not try again: the hole is HEAD's, it is stated here, and it is MEASURED BOTH
# WAYS. Real-seat: 0 true execution instructions in the 729 + 148 + 149 sentences (fix4/ACCEPTANCE.txt).
# Constructed (vr5/v3_a2hole.py, 40 instruction tails x 5 retired-word carriers): 80 of 200 sentences
# that HEAD struck -- for the WORD they carried, never for the instruction -- SHIP under the flag
# ('Positioning is crowded, so trim the position.'), because the word fence was HEAD's only INCIDENTAL
# screen over instruction shapes the A2 detector never saw; the same instruction on a neutral carrier
# ('The ending-stocks row moved, so buy at 240.') ships at HEAD with no flag anywhere. The A2 regexes are
# byte-identical to HEAD, `licence_kept_charge` asks them FIRST, and the licence is monotone (0 strikes
# added over 992 sentences). The instrument that watches this class is `exec_leaks` on the judge read. What
# closes it, when the estate decides to close it, is a widening of the A2 detector on BOTH arms, which
# is a blast-radius decision and not a licence's to take.
#
# WHAT THE FLAG MAY NOT DO, RESTATED AS CODE: the licence is an ARGUMENT (this module reads no
# environment), it is asked LAST, and it can only ever turn a `True` into a `False` on a sentence whose
# every charge is in the retired column. `register_leaks`, `internal_leaks`, `market_leaks`,
# `count_valuation_words`, `count_flow_words`, `lane_b_hits` and `exec_leaks` take no licence argument
# and are numerically unchanged on both arms: the COUNTERS keep counting the words the STRIKE now lets
# through, which is what makes the arm measurable.
#: The KEPT half of Lane A -- the two alternations that name a FIGURE rather than a mood. Copied
#: VERBATIM out of `_VALUATION_PHRASES` (same words, same order), so a phrase can be in this set only
#: by being in that one. `take-profit`, `stop-loss`, `go long`, `buy the dip`, `worth fading`,
#: `relative value trade`, `at attractive levels`, `entry point`, `is a buy`, `load up` and
#: `accumulate here` are absent NOT because they are free but because `_EXEC_PHRASES` -- a strict
#: subset of the same pattern -- has already convicted them two screens up, on every register and
#: under every licence.
_LICENCE_KEPT_VAL = re.compile(
    r"\bprice (target|objective)s?\b"
    r"|\bfair value\b", re.I)


def licence_kept_charge(sent: str) -> str:
    """The reason this sentence is STILL struck with the licence on, or "" when words-are-free keeps it.

    ONE PRODUCER, FOUR READERS: `_is_banned_sentence`'s licence clause, `bar_shaped_spans` (and through
    it `register_leaks_excluding_bar`, the declared population the eval gate reads), `config_check`
    clause (n1) and the deck. The round-2 lesson is why it is public: a pin that infers the predicate
    from a strip decision grades a guard that may never have run.

    PURE, and it names the FIRST column the sentence falls in -- the same order `_is_banned_sentence`
    decides in, so the two can never disagree about why."""
    s = str(sent or "")
    if _EXEC_PHRASES.search(s) or _exec_extra_hits(s):
        return "a2_execution"
    if _REVERSION_PHRASES.search(s):
        return "forecast_reversion"
    if _SPREAD_NOUN.search(s) and _CONVERGE_VERB.search(s) and _FUTURITY.search(s):
        return "forecast_convergence"
    if _PERSISTENCE.search(s) and _PRICE_SPREAD_NOUN.search(s):
        return "forecast_persistence"
    if _LICENCE_KEPT_VAL.search(s):
        return "unbacked_figure_claim"
    return ""


def _is_banned_sentence(sent: str, *, market_register: str = FENCED, derivation_ok: bool = False,
                        bar_licence=None) -> bool:
    """Is this ONE sentence banned under `market_register`?

    FENCED (the default, today's behaviour byte-for-byte): A or B or C or D or E.
    OUTLOOK (W5.0): A2 execution idioms, the C-family reversion idioms and the C forward-convergence class
    rule stay banned; A1 / B / D / E are PERMITTED and the DERIVATION GATE takes over -- a sentence stating
    an uncited price level is banned unless the unit's arithmetic is shown and its inputs cited.

    `bar_licence` (S7b R1) is the WORDS-ARE-FREE LICENCE, and it is an ARGUMENT for the reason every
    other scope here is: this module reads no environment, so a mis-plumbed enable can never relax the
    suggester chip guard, the numbers/news/live bodies or a lint. DEFAULT None = today's decision byte
    for byte on every input.

    IT IS READ AS A FLAG AND NO LONGER CALLED, and that is the owner's 2026-09-15 16:30Z ruling in one
    line. Rounds 1-3 threaded a callable `sentence -> verify.bar_adjective_verdict` and asked it whether
    a FIGURE backed the sentence's adjective; the strike is now retired for the WORD regardless of the
    verdict, so the verdict has exactly one job left and it is not this one -- it decides the CORRECTING
    CLAUSE at `answer._bind_bar_adjectives`, where a served figure that CONTRADICTS the adjective earns
    an appended clause. The seam still threads the same callable, so the signature, the plumbing and the
    dark contract are unchanged and any truthy licence reads the same.

    WHAT THE LICENCE MAY DO, AND ONLY THIS: relieve the STRIKE on a sentence whose every market-lane
    charge is a WORDS-ONLY one (`licence_kept_charge` returns "" -- the classification block above says
    which rules those are, and why each is in the column it is in).

    WHAT IT MAY NOT DO: it is not consulted for A2 execution, for the reversion idioms, for the
    forward-convergence or persistence-denial class rules, for the two Lane-A members that name a figure
    (`price target`, `fair value`), or anywhere on the OUTLOOK derivation gate -- an unbacked price level
    is a refusal no register ruling speaks to. And it never touches `register_leaks` / `internal_leaks` /
    `market_leaks` / `count_valuation_words` / `count_flow_words` / `lane_b_hits`: the chip guard and the
    eval metrics are numerically unchanged, which is the same blast-radius line `_EXEC_EXTRA` /
    `_EXEC_AMBIG` already draw two screens up."""
    outlook = (market_register == OUTLOOK)
    # A2 EXECUTION / ADVICE -- unconditional, no register scope permits it (W5.0 + the user's ratified
    # decision: no entry/exit levels, no stops, no sizing, no risk/reward framing, no buy/sell/long/short
    # advice). `_EXEC_PHRASES` is a subset of A so on a fenced turn it changes nothing. `_EXEC_EXTRA` /
    # `_EXEC_AMBIG` are the ONE deliberate exception to "every non-outlook answer byte-identical": they
    # strip sizing/risk-reward/entry-level prose on EVERY turn, because the fence is a user decision about
    # what this tool will say, not a property of the outlook mode. `_EXEC_AMBIG` is frame-gated so the
    # exception costs no honest market-mechanics prose (see `_exec_extra_hits`). All of it stays out of
    # `register_leaks` so the chip guard, the eval `register_leaks` metric and the R2/R8 lints are
    # numerically unchanged; only the strip tightens.
    if _EXEC_PHRASES.search(sent) or _exec_extra_hits(sent):
        return True
    # C-family: the reversion idioms and the forward-convergence class rule -- unconditional.
    if _REVERSION_PHRASES.search(sent):
        return True
    if _SPREAD_NOUN.search(sent) and _CONVERGE_VERB.search(sent) and _FUTURITY.search(sent):
        return True
    if not outlook:
        # THE DECISION IS HEAD'S, TRUTH TABLE FOR TRUTH TABLE, and the shape changed only so the
        # licence has one place to be asked. HEAD read: `if LaneA: True` / `if persistence: True` /
        # `return bool(LaneB)`. Over the three independent predicates the two agree on all eight
        # rows -- LaneA true still returns True (through the tail below), persistence still returns
        # True on its own, LaneB alone still returns True, and nothing matching still returns False.
        # Lane B stays LAZY behind the `or`, exactly as HEAD's ordering made it, so a sentence a Lane-A
        # phrase already convicted does not pay for the window-noun scan.
        if _PERSISTENCE.search(sent) and _PRICE_SPREAD_NOUN.search(sent):
            return True                     # the persistence-denial CLASS rule: structural, never licensed
        if not (_VALUATION_PHRASES.search(sent) or _FLOW_PHRASES.search(sent)
                or _lane_b_in_sentence(sent, _LANE_B_VAL_RX)
                or _lane_b_in_sentence(sent, _LANE_B_FLOW_RX)):
            return False
        # WORDS ARE FREE, and the clause is asked LAST -- after every unconditional clause above has
        # had its say, so the only charges left to retire are the words-only ones. `licence_kept_charge`
        # re-asks the three clauses above (they cannot fire here, having returned True already) because
        # ONE producer answering "why is this still struck" is worth three redundant searches on a LIT
        # turn and costs a dark one nothing.
        if bar_licence is not None:
            return bool(licence_kept_charge(sent))
        return True
    # OUTLOOK: the vocabulary ban is replaced by the derivation gate. A BARE number is a refusal, and so is
    # a DERIVED output whose anchor was never cited -- see unbacked_levels for why a handle is not enough.
    if derivation_ok:
        return False
    if _CIT_HANDLE.search(sent) and not _deriv_output(sent):
        return False
    return bool(_level_tokens(sent))


def _strip_banned_sentences(seg: str, *, market_register: str = FENCED,
                            derivation_ok: bool | None = None,
                            unit_span: tuple[int, int] | None = None,
                            bar_licence=None) -> str:
    """Drop each sentence carrying a Lane A / class-rule / Lane B leak (the verify.py strip precedent). Never
    a paraphrase. Superset of register_leaks' new-lane conditions, so register_leaks(sanitize(x)) == [] holds
    WITH `bar_licence=None` -- which is every flag-off turn, and the invariant HEAD ships.

    UNDER A LICENCE THE INVARIANT IS `register_leaks_excluding_bar(sanitize(x, bar_licence=...)) == []`,
    and the difference is the point of the instrument rather than a hole in it: a bar-adjective sentence
    the licence keeps is a sentence `market_leaks` still charges, because the counters take no licence
    (`check_register_seam` clause (d), the suggester chip guard rests on it). MEASURED on the 97-case
    corpus: licence OFF 0/97 violations of the old form, licence ON 2/97 -- and 0/97 of the new form on
    both arms. A consumer that must not charge the instrument's own output calls the second producer and
    says which population it means; see the block note above `bar_shaped_spans`.

    Under `market_register=OUTLOOK` the fast path is skipped (the derivation gate fires on plain numbers that
    carry no fence vocabulary at all) and `derivation_ok` is computed once for the segment when not supplied.

    `unit_span` is the DERIVATION UNIT's (start, end) inside `seg`; a complete derivation exempts only the
    sentences whose offset falls inside it. Default: computed from `seg` (whole seg when no '## Outlook'
    heading is rendered, so single-section prose is unchanged)."""
    outlook = (market_register == OUTLOOK)
    # THE FAST PATH IS HEAD'S ON BOTH ARMS AGAIN. Round 3 skipped it under a licence because the advice
    # CUT had to walk every sentence of a lit turn; the cut is gone (the ruling removed it), and the
    # licence can only ever RELIEVE a charge -- so a segment carrying none of this vocabulary has
    # nothing to relieve and the screen is exact on either arm.
    if not outlook and not (_VALUATION_PHRASES.search(seg) or _FLOW_PHRASES.search(seg) or _LANE_B_ADJ.search(seg)
                            or _PERSISTENCE.search(seg) or _EXEC_EXTRA.search(seg) or _EXEC_AMBIG.search(seg)
                            or _POSITION_SIZING.search(seg)
                            or (_SPREAD_NOUN.search(seg) and _CONVERGE_VERB.search(seg))):
        return seg
    if outlook and derivation_ok is None:
        derivation_ok = outlook_derivation_ok(seg)
    lo, hi = unit_span if unit_span is not None else _outlook_span(seg)
    toks = _SENT_KEEP.split(seg)
    out: list[str] = []
    pos = 0
    for i in range(0, len(toks), 2):
        text = toks[i]
        delim = toks[i + 1] if i + 1 < len(toks) else ""
        start, pos = pos, pos + len(text) + len(delim)
        if text and _is_banned_sentence(text, market_register=market_register,
                                        derivation_ok=bool(derivation_ok) and lo <= start < hi,
                                        bar_licence=bar_licence):
            # CYCLE-10 (2026-08-08): THE DROPPED UNIT LEAVES ITS LINE BREAKS BEHIND. `_SENT_KEEP` captures
            # `[.!?;]\s+`, so a unit that ended a LINE owned the terminating "\n" -- dropping it welded the
            # next line onto the previous one. Measured on the gate-7 covenant footer, byte-exact:
            #     "[3] USDA WASDE (2014-01-01): U.S. <banned sentence>\n[4] World Bank ..."
            #  -> "[3] USDA WASDE (2014-01-01): U.S. [4] World Bank ..."
            # -- two `## Sources` rows on one line, which is how a provenance list stops parsing as a list.
            # The same weld joins two prose paragraphs when the strip takes the last sentence of one.
            # WHITESPACE ONLY, and deliberately so: not one strip DECISION moves, no counter moves, and
            # `register_leaks(sanitize(x)) == []` / the OUTLOOK `unbacked_levels` invariant are untouched
            # (a newline carries no token). What is preserved is the line structure the caller wrote.
            out.append("\n" * delim.count("\n"))
            continue
        out.append(text + delim)
    return "".join(out)


def internal_leaks(text: str) -> list[tuple[str, str]]:
    """INTERNAL-REPRESENTATION leaks only: markers, bare signs, graph jargon, internal-architecture prose,
    raw contract slugs, raw regime ids, underscored SAGIS crop codes.

    NEVER RELAXABLE. A slug or a `conf=` in reader prose is a BUG, not a register question -- no intent, no
    flag and no market_register scope may permit it. W5's relaxation applies to `market_leaks` alone."""
    prose = _strip_mermaid(text)
    hits: list[tuple[str, str]] = []
    for rx in (_MARKERS, _SIGN, _JARGON, _PROSE_PHRASES):
        for m in rx.finditer(prose):
            hits.append((m.group(0).strip(), _ctx(prose, m)))
    for slug in _slugs():
        for m in re.finditer(r"\b" + re.escape(slug) + r"\b", prose):
            hits.append((slug, _ctx(prose, m)))
    for rid in _regime_ids():                                            # raw convergence-regime id in prose
        for m in re.finditer(r"\b" + re.escape(rid) + r"\b", prose):
            hits.append((rid, _ctx(prose, m)))
    for mid in _labeled_metric_slugs():                                  # a LABELED metric's raw slug in prose
        # (?<!\.) exempts DOT-QUALIFIED addresses: "silver_wasde.avg_farm_price" in agent guidance is
        # API syntax the agent queries WITH (an address), not display prose -- the leak class is the
        # BARE slug in narration (owner-ratified 2026-08-22, the price-observability bullet fixture).
        for m in re.finditer(r"(?<!\.)\b" + re.escape(mid) + r"\b", prose):
            hits.append((mid, _ctx(prose, m)))
    for m in _SAGIS_CROP_RX.finditer(prose):                             # underscored SAGIS crop code in prose
        hits.append((m.group(0), _ctx(prose, m)))
    return hits


# ══ S7b R2 -- THE DESK REGISTER. A THIRD POPULATION, AND IT IS NOT `internal_leaks`. ═══════════════════
# `internal_leaks` catches a BUG: a slug, a `conf=`, a graph token -- text that is not English at all.
# This catches something else entirely: ordinary, well-formed English that names THE INSTRUMENT instead
# of the market. "Reading the board at 2026-09-07, the loudest thing on ICE cocoa is..." is grammatical,
# register-clean by every shipped detector, and tells a desk reader about our machinery.
#
# MEASURED, 2026-09-11, over the NINE banked real-seat answers (`scratchpad/lingo_leaks.py`,
# re-runnable): 195 internal-vocabulary hits -- board 64, row/rows 54, "the graph" 40, loud 13,
# knowledge date 10, convention 6, driver 3, state read 2, receipt 2, node 1. 21.7 per answer. The
# writer COPIES THE BLOCK'S VOCABULARY, which is the predictable cost of handing it a block.
#
# AND 20 OF THE 195 ARE ORDINARY MARKET ENGLISH (`scratchpad/s7b/lingo_context.py`: INSTRUMENT 175 /
# MARKET 20, 10.3%). A BARE TOKEN COUNT WOULD CHARGE THE WRITER FOR OBEYING THE MANDATE:
#   * "the board price tape runs through 2026-09-04" is `narration.RECENCY_LEDGER_SENTENCE`'s own words
#     AND the mandate's movement (2) instruction AND `render._RECENCY_LAYER_WORDS`' `tape` group;
#   * "past the line the desk convention calls tight" is `state/render.py:703` VERBATIM -- block text the
#     writer is supposed to copy;
#   * "board crush" is a real CBOT spread and the convention ref `cbot_board_crush_margin`;
#   * "the CBOT soybean board" is how a desk says it.
# So the ban is BY PHRASE WITH A DECLARED EXEMPTION TABLE, and NO `render.py` or `narration.py` literal is
# reworded to suit it: rewording either would change the flag-on block and the flag-on prompt for every
# board turn, which is the byte-identity this whole sitting rests on. EXEMPT, never reword.
#
# `driver` IS DELIBERATELY NOT A MEMBER. `_JARGON_SUBS` REWRITES "the node" INTO "the driver" (:893-898):
# a lint charging the word would charge the estate's own repair. The context census agrees -- 0
# INSTRUMENT / 3 MARKET on all three occurrences.
#
# NOT SHIPPED, and stated rather than silently omitted: `cascade`, `spillover`, `fan-out`, `the walk` and
# `series key` are in the measurement's vocabulary and scored ZERO on all nine answers. The estate's own
# "one specific example, one fix, one pin" law says a word with no measured hit earns no clause, and the
# first three are ordinary desk English besides.
#: (name, pattern, the plain words that replace it). The replacements are the mandate's own table, so the
#: lint and the prompt teach ONE vocabulary.
DESK_REGISTER_TOKENS: tuple = (
    # PRE-ARM ROUND 1 (2026-09-17) -- THE REPLACEMENT COLUMN IS WHERE THE RESIDUE ACTUALLY LIVES, and
    # the in-VPC smoke measured it. "the market" alone cannot carry a sentence about TWO listings, so
    # the writer reached past the table for the instrument's own word and wrote "read on each board's
    # own-currency move" (three times across two turns), "opposite signs on each board by phase", "on
    # either board this session" and "high confidence on BOTH boards" -- SEVEN of the ten `board`
    # charges on the five served bodies. The PM lens refused the obvious exemption and named the cost
    # of the missing word instead: "'the wheat board' is not how a trader refers to Chicago wheat, and
    # for anyone with grey hair it collides with the Canadian Wheat Board, a marketing monopoly that
    # ceased to exist in 2012." SO THE BAN STANDS AND THE TABLE LEARNS THE WORDS A DESK ACTUALLY USES:
    # the exchange, the contract, the exchange's own name, and "in its own currency" for the sentence
    # that has to distinguish two listings. "the market" is KEPT rather than replaced -- it is the word
    # the rewrite already spends successfully ("not just its own board" -> "not just its own market",
    # accepted on the palm/rape turn) and `answer._desk_allowed_stems` reads this column, so dropping a
    # word here would withdraw it from the remedy on the same commit.
    # THE COLUMN IS A LIST OF PHRASES AND NOTHING ELSE. `answer._desk_replacement_phrases` splits it on
    # `,` and ` or ` alone, so a clause joined with a SEMICOLON parses as ONE fourteen-token phrase that
    # can never match a substitution -- measured on this row's own first draft, where "in its own
    # currency" was swallowed whole. A RULE belongs in the mandate prose; only WORDS belong here.
    # AND NOTHING HEAD TAUGHT IS WITHDRAWN. "the data as of <date>" trails the new words rather than
    # being replaced by them: `_desk_allowed_stems` reads this column, so deleting a phrase would make
    # a rewrite HEAD accepts refusable on this commit -- the exact failure this row exists to avoid.
    ("board", r"\bboards?\b",
     "the market, the exchange, the contract, the exchange's own name, in its own currency, "
     "the data as of <date>"),
    ("row", r"\brows?\b", "the reading, the record, this series, the latest print"),
    ("the graph", r"\bthe graph\b", "the mechanism, the driver model"),
    # THE REPLACEMENT WORDS ARE THEMSELVES REGISTER-GRADED. "the most stretched reading" was the first
    # draft here and it reds `narration.check_literals` on `lane_b_adjective`: `stretched` is one of
    # `_LANE_B_ADJ`'s six. A prompt that taught a fenced word would be the convention registry's own
    # 2026-09-11 collision (yaml:15-21) re-enacted in the mandate.
    # PRE-ARM ROUND 1: `the strongest signal` was added here as the PM lens' own replacement, quoted --
    # "'loud' and 'rows' are the system talking about its own internals. A desk says 'the two strongest
    # signals point opposite ways'." -- with the safety note "it is a superlative and NOT a member of
    # `answer._DESK_CLAIM_RX`'s comparative class, so teaching it does not license a polarity flip".
    # ROUND 2: THAT NOTE WAS FALSE AND THE PHRASE IS WITHDRAWN. `strongest` is named BY HAND in
    # `_DESK_CLAIM_RX`'s EXTREMITY alternation (answer.py:10336) and `("strongest", "weakest")` is a
    # declared row of `_DESK_CLAIM_ANTONYMS` (answer.py:10419). MEASURED on a real-seat shape
    # ("...the weakest of them is soybeans." -> "...the strongest of them is soybeans."): with the
    # phrase taught, `_desk_claim_terms(cand)` falls from `['strongest']` to `[]`, so the rewrite
    # census logs the refusal as `claim` where HEAD logs `polarity` -- and `answer.py:10786` says that
    # map "is read by a human deciding what the rewrite is doing wrong". The reply is refused either
    # way (guard 10 refuses on any multiset difference), so no flip ever reached a page; what was at
    # stake is the DIAGNOSTIC and guard (11)'s LOSS set, which subtracts `_desk_allowed_stems()` and
    # would have let a reply drop the word `strongest` from an offered sentence with no charge.
    # `the signal` REPLACES IT AND KEEPS THE PM'S NOUN: it teaches the word the lens asked for, adds
    # the stem `signal` -- which is in NO claim class -- and leaves `strongest` fully charged. The
    # writer was never barred from writing "the strongest signal": `loud` is the banned token, not
    # `strongest`, and this column is what the writer is TAUGHT and what the REWRITE is allowed to
    # spend, which are not the same licence.
    ("loud", r"\bloud(?:est|er|ness)?\b",
     "the largest move, the signal, the reading furthest from its own record"),
    # ROUND-3 (2026-09-15): `an older reading` IS PART OF THE REPLACEMENT, and it is here because the
    # claim guard gained the comparative class on the same commit. The measured honest rewrite of this
    # row's own charge is "Two rows have spent their knowledge date." -> "Two series are read through
    # OLDER dates.", and a guard that froze the comparative multiset would have refused it while the
    # adversarial inversion ("NEWER dates") is refused for the reason it should be -- a claim word from
    # nowhere. ONE PRODUCER, again: `answer._desk_allowed_stems` reads this column, so teaching the
    # word and permitting it are the same edit.
    # PRE-ARM ROUND 1 (2026-09-17): THE NOUN-PHRASE REPLACEMENT, WHICH THIS ROW OWED AND THE DECK
    # DOCKETED IN SO MANY WORDS -- `test_state_narration.py:175-181`: "the `knowledge date` row of the
    # table offers no NOUN-PHRASE replacement ('read through <date>' is a verb phrase), so a
    # `knowledge date` charge in a noun slot has no accepted rewrite at all. The one-line remedy is a
    # TABLE edit". `the date it was known` is that noun phrase. `known <date>` joins it because the
    # served footer already stamps rows `[known 2026-09-11]`, so the reader meets one spelling.
    # THE SPELLING RULE ("an ISO date or the month spelled, never bare digits") is NOT in this column
    # and that is deliberate: it is a RULE, and a rule joined on here with a semicolon would be parsed
    # by `answer._desk_replacement_phrases` as part of the PHRASE beside it -- measured, it swallowed
    # HEAD's own working `an older reading when it is one` into a fifteen-token string. The rule ships
    # in `SYSTEM_DESK_REGISTER_MANDATE` instead, where it is prose and binds the whole answer, which is
    # what the smoke needed: `20260904` reached reader prose on three turns, and the PM lens refused it
    # -- "'20260904' is an unformatted integer sitting beside two ISO dates in the same clause. A desk
    # writes 'our data runs through 4 September'."
    ("knowledge date", r"\bknowledge dates?\b",
     "known <date>, read through <date>, as of <date>, the date it was known, an older reading when "
     "it is one"),
    ("convention", r"\bconventions?\b", "the desk's own line for this series"),
    ("state read", r"\bstate reads?\b", "the latest print"),
    ("receipt", r"\breceipts?\b", "the dated report"),
    ("node", r"\bnodes?\b", "the driver"),
    ("series key", r"\bseries keys?\b", "this series"),
    ("the walk", r"\bthe walk\b", "the chain"),
)
#: The EXEMPTIONS, each with (a) the TOKENS it exempts and (b) the measured reason it is here. A token
#: hit whose span falls inside one of these AND whose name this row names is ordinary market English and
#: is never charged.
#:
#: ROUND-3 REVIEW MINOR (2026-09-15): THE SECOND FIELD IS NEW AND IT CLOSES A LATENT SWALLOW. The rows
#: were applied as pure SPAN CONTAINMENT across all eleven tokens, so an exemption written for `board`
#: silently dropped every `loud` / `row` / `convention` charge lying inside its own window --
#: 'On the CME, the loudest thing on the board is the crush.' and 'Against the MATIF curve, the loudest
#: row on the board is drought.' both scored ZERO under the 40-character exchange window, and
#: 'The Current Board reads two-sided.' / '## State Of The World Board' scored zero under the
#: proper-name rule. MEASURED ZERO on the nine banked answers (15 `board` and 3 `convention` swallows,
#: every one legitimately about its own token, 0 foreign), so this is a latent hole closed rather than a
#: loss recovered -- and every row here exempts exactly ONE token, which is the whole point: an
#: exemption is an argument about a WORD, never about the characters near it.
#:
#: PRE-ARM ROUND 1 (2026-09-17) -- TWO EXEMPTION DECISIONS, BOTH MEASURED, BOTH RECORDED HERE BECAUSE A
#: DECISION NOT TO ADD A ROW IS STILL A DECISION.
#:
#: (1) NO ROW IS ADDED FOR THE NON-UNIQUE `board` (`\bboards\b`, `each|either|both|every board`), which
#: `THREAT_MODEL_FIXES.md` A.8 recommended and which would have exempted 7 of the 24 charges on the
#: five in-VPC smoke bodies. THE OWNER'S RULING IS THAT THE BAN IS RIGHT AND THE REPLACEMENT WAS WRONG:
#: "each board's own currency" is not market English, it is the instrument's own self-word wearing a
#: quantifier, and the fix is to teach "each exchange's own currency" -- which is what
#: `DESK_REGISTER_TOKENS`' `board` row now does. MEASURED SUPPORT: re-read by hand, 0 of the 24 charges
#: on the case list is a false charge, so there is nothing for an exemption to recover.
#:
#: (2) ROW 4 (`<commodity> boards?`) IS LEFT IN PLACE AND DOCKETED, not removed. MEASURED with rows 3
#: (`<exchange> ... board`) and 5 (`<Proper Name> Board`) still standing, row 4's UNIQUE licence is
#: +2 charges on the case list and +1 on the fourteen banked answers -- and the two on the case list
#: are both "the wheat board", which the PM lens called a MAJOR register leak on the corn/wheat turn
#: ("not how a trader refers to Chicago wheat ... it collides with the Canadian Wheat Board"). So the
#: lint is measurably blind to a leak a reader catches. IT IS NOT REMOVED ON THE EVE OF THE ARM: it
#: raises the reported number on BOTH cells for a reason that is not the treatment, which is exactly
#: the metric-redefinition threat A.5(1) names, and the third recovered span ("the two South African
#: maize boards") is a defensible exchange usage. The MANDATE is corrected instead -- it now says a
#: board name is the market's own only when the exchange or the institution is named with it -- which
#: costs zero lint charges on either cell. DOCKET: revisit row 4 after arm A.
DESK_REGISTER_EXEMPT: tuple = (
    (r"\bthe board price tape\b", ("board",),
     "narration.RECENCY_LEDGER_SENTENCE and the mandate's movement (2): the writer is TOLD to write it"),
    (r"\bboard (?:price|prices|margin|margins|spread|spreads|crush|lot|lots)\b", ("board",),
     "a futures board's own price / margin / spread; 'board crush' is a CBOT spread and the convention "
     "ref cbot_board_crush_margin"),
    (r"\b(?:CBOT|CME|ICE|DCE|BMD|Bursa|MATIF|Euronext|JSE|B3|KCBT|MGEX|NYBOT|LIFFE|ZCE|CZCE|SHFE|MDEX)"
     r"\b[^.\n]{0,40}?\bboards?\b", ("board",), "'<exchange> ... board' -- the CBOT soybean board"),
    (r"\b(?:soybean|soyabean|soy|corn|maize|wheat|palm|cocoa|coffee|sugar|cotton|rice|canola|rapeseed"
     r"|oat|barley|sorghum|hog|cattle)s?\s+boards?\b", ("board",),
     "'<commodity> board' -- desk English"),
    # REVIEW MAJOR 7 (2026-09-11): A NAMED INSTITUTION IS NOT THE INSTRUMENT. The commodity rule above
    # requires the crop token ADJACENT to `board`, so "Ghana Cocoa Board" and "Canadian Wheat Board"
    # were exempt while "Malaysian Palm Oil Board" was CHARGED -- in prose, in an abbreviation gloss and
    # in a "Source: Malaysian Palm Oil Board - Monthly Palm Oil Statistics, 2026-09-10." line (3 of 3
    # probes). MPOB is a SERVED SOURCE FAMILY in this estate -- `silver_mpob` is a board table and
    # `mpob_ending_stocks` is one of the four `verify.BAR_FAMILY_REFS` level-decile refs the licence
    # itself reads -- so the lint was charging a document title the brief's own requirement names, and
    # then handing that sentence to a rewrite told not to say "board". CASE IS THE DISCRIMINATOR and it
    # is spelled with a scoped flag reset, because the whole table compiles case-insensitively: TWO OR
    # MORE capitalised words before a capital "Board" is a proper name ("Malaysian Palm Oil Board"), one
    # is not ("The Board"), and the instrument's own leak is always lower case ("reading the board").
    # ROUND-3 REVIEW MINOR (2026-09-15): A CASE TEST IS NOT A NAME TEST. The rule scored ZERO on
    # 'The Current Board reads two-sided.', 'The State Board is two-sided.', 'Our Internal Driver
    # Board reads two-sided.', 'The Leviathan State Board reads two-sided.', 'On The Cocoa Board the
    # reading is two-sided.' and the heading '## State Of The World Board' -- while the identical
    # lower-case "the board reads two-sided" is charged. Title Case is a STYLE, and a headline, a
    # heading and a capitalised determiner all wear it; the lint's own note says an exemption is "an
    # argument about a WORD, never about the characters near it", and this one had become an argument
    # about capitalisation. So the capitalised run must now be made of NAME words: a leading
    # determiner or pronoun cannot be one (it is grammar, not a name), and neither can any of this
    # instrument's OWN self-reference words, which is what every measured false exemption was built
    # out of. MEASURED COST ON THE NINE BANKED ANSWERS: ZERO -- all 18 exemptions there are
    # legitimate and all 18 survive.
    (r"(?-i:\b(?:(?!(?:The|A|An|This|That|These|Those|Our|Its|Their|My|Your|His|Her|Each|Every"
     r"|Some|Any|No|Of|On|In|At|For|State|Current|Latest|World|Internal|External|Driver|Drivers"
     r"|Board|Reading|Readings|Graph|Walk|Cascade|Leviathan)\b)[A-Z][A-Za-z&.'’-]+\s+){2,5}"
     r"Board\b)", ("board",),
     "a NAMED institution: '<Proper Name> Board' -- Malaysian Palm Oil Board, Ghana Cocoa Board, "
     "Canadian Wheat Board. MPOB is a served source family (silver_mpob / mpob_ending_stocks). The "
     "run may not be built out of determiners or of this instrument's own words"),
    (r"(?-i:\bBoard\s+of\s+(?:Trade|Directors|Governors)\b)", ("board",),
     "'Board of Trade' -- the Chicago Board of Trade's own name, and the two corporate-body idioms"),
    (r"\bthe desk convention calls\b", ("convention",),
     "state/render.py:703 VERBATIM -- the block's own sentence"),
    (r"\b(?:market|desk|trade|trading|industry|reporting|delivery|contract)\s+conventions?\b",
     ("convention",), "ordinary market English for a trade practice"),
    (r"\brow\s+crops?\b", ("row",), "corn and soybeans ARE row crops"),
    (r"\b(?:registered|warehouse|delivery|shipping|exchange|depositary)\s+receipts?\b",
     ("receipt",), "a deliverable-supply term"),
    (r"\breceipts?\s+of\b", ("receipt",),
     "REVIEW MAJOR 7: 'receipt of X' is the ordinary English RECEIVING, not the instrument's dated "
     "report -- measured on 'the USDA Agricultural Marketing Service Livestock Mandatory Reporting "
     "receipt of bids'"),
    (r"\bdeath\s+cross\b|\bnode\s+of\s+the\s+(?:port|terminal)\b", ("node",),
     "reserved: named market idioms"),
)
_DESK_TOKEN_RX = tuple((n, re.compile(p, re.I), r) for n, p, r in DESK_REGISTER_TOKENS)
#: (compiled, the frozen set of token names it exempts, why). An EMPTY name set would exempt every
#: token; no row declares one today and the lint below refuses one that names a token off the table.
_DESK_EXEMPT_RX = tuple((re.compile(p, re.I), frozenset(names), why)
                        for p, names, why in DESK_REGISTER_EXEMPT)


def check_desk_exempt_table() -> list[str]:
    """Every exemption names at least one token, and every token it names is on the ban table. Read by
    `config_check` -- an exemption for a word the table does not carry is dead text pretending to be a
    fence, and one naming NOTHING is the span-containment swallow this round closed."""
    known = {n for n, _p, _r in DESK_REGISTER_TOKENS}
    errs: list[str] = []
    for pat, names, _why in DESK_REGISTER_EXEMPT:
        if not names:
            errs.append(f"desk_register_exempt: {pat!r} names no token -- it would exempt all eleven")
        for n in names:
            if n not in known:
                errs.append(f"desk_register_exempt: {pat!r} names {n!r}, which is not a banned token")
    return errs


def _desk_exempt_spans(prose: str) -> list[tuple[int, int, frozenset]]:
    """(start, end, the token names this span exempts) for every exemption match in ``prose``."""
    return [(m.start(), m.end(), names)
            for rx, names, _why in _DESK_EXEMPT_RX for m in rx.finditer(prose)]


def desk_register_spans(text: str) -> list[tuple[int, int, str]]:
    """(start, end, token) for each charged INSTRUMENT word, as offsets into ``_strip_mermaid(text)``.

    THE PRODUCER `desk_register_hits` IS BUILT ON, so the count and the span can never disagree about
    which words are charged. It exists because a consumer needs the SPANS and not the labels: the
    rewrite's overlap guard (answer.`_desk_content_ex_instrument`) measures how much of a sentence
    SURVIVED a rewrite, and the instrument words are exactly the part it is allowed to lose. Masking by
    span is right where a stem list would be wrong -- the `loud` pattern charges "loudest", whose stem
    is not "loud"."""
    prose = _CIT_HANDLE.sub(lambda m: " " * len(m.group(0)), _strip_mermaid(text))
    exempt = _desk_exempt_spans(prose)
    out: list[tuple[int, int, str]] = []
    for name, rx, _repl in _DESK_TOKEN_RX:
        for m in rx.finditer(prose):
            if any(a <= m.start() and m.end() <= b and name in names for a, b, names in exempt):
                continue
            out.append((m.start(), m.end(), name))
    return sorted(out)


def desk_register_masked(text: str) -> str:
    """``text`` with every CHARGED instrument word blanked out, same length, same offsets. The unit a
    caller means when it asks "what did this sentence say APART from naming the instrument"."""
    prose = _CIT_HANDLE.sub(lambda m: " " * len(m.group(0)), _strip_mermaid(text))
    chars = list(prose)
    for a, b, _n in desk_register_spans(text):
        for i in range(a, min(b, len(chars))):
            chars[i] = " "
    return "".join(chars)


def desk_register_hits(text: str) -> list[tuple[str, str]]:
    """(token, short-context) for each INSTRUMENT word in reader prose, exemptions applied. Empty = clean.

    CITATION HANDLES ARE MASKED FIRST -- the ruling's own scope ("outside [N] handles"): a handle is an
    address the reader clicks, not prose, and `[N13]`-shaped text carries none of these words anyway.
    Masking rather than deleting keeps every offset, so a context window still reads as written.

    A SEPARATE PRODUCER FROM `internal_leaks`, AND IT MUST STAY ONE. That detector is NEVER RELAXABLE and
    is the suggester's chip guard; this one is a REGISTER question with a CORRECTING remedy, and folding
    a correctable population into an uncorrectable one would make the guard relaxable by the back door."""
    prose = _CIT_HANDLE.sub(lambda m: " " * len(m.group(0)), _strip_mermaid(text))
    spans = _desk_exempt_spans(prose)
    hits: list[tuple[str, str]] = []
    for name, rx, _repl in _DESK_TOKEN_RX:
        for m in rx.finditer(prose):
            if any(a <= m.start() and m.end() <= b and name in names for a, b, names in spans):
                continue
            hits.append((name, _ctx(prose, m)))
    return hits


def count_desk_register(text: str) -> int:
    """RAW instrument-word count (the DP-6 counter idiom): measured wherever it is asked, enforced only
    where the answer seam threaded the flag."""
    return len(desk_register_hits(text))


def desk_register_sentences(text: str) -> list[str]:
    """The OFFENDING SENTENCES, as a MEASUREMENT of the charged population -- `scratchpad/lingo_leaks.py`
    and the deck read it; the SERVING remedy does not.

    REVIEW MINOR (2026-09-11), corrected: this used to claim "same segmentation as every other pass
    here (`_SENT_ITER`), so the rewrite's unit and the lint's unit can never disagree about where a
    sentence ends". The rewrite (`answer._desk_register_lint`) splits on `_SENT_KEEP`, not `_SENT_ITER`.
    THE BOUNDARIES AGREE -- both are `[.!?;]\\s+` -- but the CHUNKS do not: `_SENT_ITER` keeps the
    terminator on the sentence and `_SENT_KEEP` moves it into the delimiter, so the two producers return
    unequal strings for the same text. The rewrite needs the offsets `_SENT_KEEP` gives it (it splices
    back by index), which is why it does not call this function, and why this function has no serving
    caller to disagree with."""
    out: list[str] = []
    for sent in _SENT_ITER.split(_strip_mermaid(text or "")):
        if sent.strip() and desk_register_hits(sent):
            out.append(sent)
    return out


def desk_register_table() -> str:
    """The banned-word table as the mandate and the rewrite prompt both print it. ONE producer, so the
    prompt the writer is given and the prompt the rewrite is given teach the same replacements."""
    return "; ".join(f"{n} -> {r}" for n, _p, r in DESK_REGISTER_TOKENS)


def market_leaks(text: str) -> list[tuple[str, str]]:
    """MARKET-REGISTER leaks: Lane A valuation (A1+A2) + Lane A flow, plus the two structural class rules
    (forward convergence, persistence denial). This is the RELAXABLE subset -- on an outlook turn A1/B/D are
    permitted and the derivation gate replaces them. It is still measured on every turn."""
    prose = _strip_mermaid(text)
    hits: list[tuple[str, str]] = []
    for rx in (_VALUATION_PHRASES, _FLOW_PHRASES):
        for m in rx.finditer(prose):
            hits.append((m.group(0).strip(), _ctx(prose, m)))
    return hits + _class_rule_hits(prose)


def register_leaks(text: str) -> list[tuple[str, str]]:
    """(token, short-context) for each internal-representation leak in the reader prose. Empty list = clean.

    W5-D1: now the CONCATENATION of the two halves -- `internal_leaks` (never relaxable) and `market_leaks`
    (the intent-scoped subset). Behaviour-identical to the pre-split detector on every input; only the ORDER
    of the returned pairs changed (internal tokens first, market phrases last), and no consumer reads order
    -- eval takes len(), the chip guard and the lints take truthiness. Kept as the single public entry point
    so the suggester chip guard (server.py) and the config lints need no edit and CANNOT be relaxed."""
    return internal_leaks(text) + market_leaks(text)


# ══ S7b R1 REVIEW MAJOR 2 (2026-09-11) -- THE LICENCE BREAKS THIS MODULE'S OWN POST-SANITIZE INVARIANT,
# AND THE HONEST FIX IS TO NAME THE RESIDUAL RATHER THAN TO HIDE IT. ══════════════════════════════════
# `_strip_banned_sentences`' docstring states "register_leaks(sanitize(x)) == [] holds". MEASURED on the
# 97-case corpus: licence OFF 0/97 violations, licence ON 2/97 -- "A crowded long here unwinds sharply
# if the catalyst pauses." and "With managed money crowded long on the report date...". That is the
# instrument WORKING (the ruling is categorical: never strike the sentence), but two consumers read the
# invariant as a PASS/FAIL and were never told:
#   * `eval.follow_up_fenced_ok` ends `and not reg.register_leaks(ans)`, so a flag-on turn that KEPT a
#     licensed sentence failed a conversation gate about carrying the PRIOR turn's vocabulary forward;
#   * the headline `register_leaks` eval metric rises on the treatment arm for the same reason.
# THE COUNTERS THEMSELVES DO NOT MOVE AND TAKE NO LICENCE -- that is `check_register_seam` clause (d)
# and the chip guard rests on it. What ships instead is a SECOND, PURE reading that names the residual
# by shape, so a consumer that must not charge the instrument's own output can subtract it and say so.
#: The seven bar adjectives, as REGISTER's own copy of `verify.BAR_ADJECTIVES`' words. It is a copy
#: because this module imports nothing at module scope and `verify` is the heavier leaf; the two are
#: asserted EQUAL by `config_check.check_register_seam` clause (d), so a word added to one and not the
#: other is a build failure rather than a silent divergence.
_BAR_ADJ_WORDS_RX = re.compile(r"\b(cheap|rich|expensive|stretched|vulnerable|crowded|squeez\w*)\b", re.I)


def bar_shaped_spans(prose: str) -> list[tuple[int, int]]:
    """The (start, end) spans of the sentences the words-are-free licence is PERMITTED to keep: a
    market-lane charge, and every one of those charges in the RETIRED column (`licence_kept_charge`
    returns ""). PURE -- no rows, no verdict, no flag: it answers "could the licence have kept this
    sentence", never "did it".

    ROUND 4 WIDENED THE POPULATION WITH THE RULING, and the NAME is kept because the eval selector, the
    seam check and the deck all address it: the licence no longer needs a BAR ADJECTIVE to keep a
    sentence ("this is a pain trade" is a flow word like any other), so the bar-adjective screen that
    stood here is gone and the one producer decides alone. The subtraction and the strip therefore still
    agree sentence for sentence, which is the only property `register_leaks_excluding_bar` rests on."""
    spans: list[tuple[int, int]] = []
    toks = _SENT_KEEP.split(str(prose or ""))
    pos = 0
    for i in range(0, len(toks), 2):
        text = toks[i]
        delim = toks[i + 1] if i + 1 < len(toks) else ""
        start, pos = pos, pos + len(text) + len(delim)
        if not text.strip():
            continue
        if not (_VALUATION_PHRASES.search(text) or _FLOW_PHRASES.search(text)
                or _lane_b_in_sentence(text, _LANE_B_VAL_RX)
                or _lane_b_in_sentence(text, _LANE_B_FLOW_RX)):
            continue
        if not licence_kept_charge(text):
            spans.append((start, start + len(text)))
    return spans


def register_leaks_excluding_bar(text: str) -> list[tuple[str, str]]:
    """`register_leaks` MINUS the Lane-A hits that belong to a sentence the words-are-free licence may
    keep. Equal to `register_leaks` on every text carrying no such sentence, which is every flag-off
    turn ever served.

    WHAT IT DOES NOT RELAX, and the list is the same one `_is_banned_sentence` decides ABOVE its licence
    clause: `internal_leaks` in full (never relaxable, the suggester's chip guard), both structural
    class rules, every A2 execution idiom, and any sentence carrying a hard Lane-A phrase beside its
    charge beside its words (`licence_kept_charge` names it, so the span is never exempt). It takes NO
    licence
    argument and reads no environment: a consumer choosing it is making a declared statement about
    which population it means, not turning a fence off."""
    prose = _strip_mermaid(text)
    spans = bar_shaped_spans(prose)
    hits: list[tuple[str, str]] = list(internal_leaks(text))
    for rx in (_VALUATION_PHRASES, _FLOW_PHRASES):
        for m in rx.finditer(prose):
            if any(a <= m.start() < b for a, b in spans):
                continue
            hits.append((m.group(0).strip(), _ctx(prose, m)))
    return hits + _class_rule_hits(prose)


# ── sanitizer: rewrite the internal tokens into reader register (prompt discipline alone did not hold) ─────────
_CONF = re.compile(r"\bconf\s*=\s*([A-Za-z0-9.]+)", re.I)                 # conf=high -> "high confidence"
_SIGNKV = re.compile(r"\bsign\s*[:=]?\s*([+\-])")                        # sign=+ / sign + -> bullish/bearish
_PARENSIGN = re.compile(r"\(\s*\+\s*/\s*\-\s*\)|\(\s*([+\-])\s*\)")      # (+/-)->mixed ; (+)->bullish ; (-)->bearish
_STRUCT = re.compile(r"\b(edge_type|any_n_of|silver_ref|silver_status|target_metric)\s*=\s*[\w./+-]+", re.I)
_STRUCT_BARE = re.compile(r"\s*\b(edge_type|any_n_of|silver_ref|silver_status)\b", re.I)
_JARGON_SUBS = [                                                         # graph vocab -> reader vocab (mirror _JARGON)
    (re.compile(r"\bnode fired\b", re.I), "driver activated"),
    (re.compile(r"\bcausal node\b", re.I), "the driver"),
    (re.compile(r"\bgraph edge\b", re.I), "the link"),
    (re.compile(r"\bthe edge sign\b", re.I), "the direction"),
    (re.compile(r"\bthe node\b", re.I), "the driver"),
    # Internal-architecture prose (mirror _PROSE_PHRASES). Multi-word forms first so a shorter phrase can't
    # partial-match inside a longer one; none of these reintroduce a detected token.
    (re.compile(r"\bmapped graph\b", re.I), "tracked driver model"),
    (re.compile(r"\bcausal graph\b", re.I), "driver model"),
    (re.compile(r"\blive-feature layer\b", re.I), "real-time data"),
    (re.compile(r"\bsilver numbers layer\b", re.I), "observed data"),
    (re.compile(r"\bdated evidence item\b", re.I), "dated source"),
]


def _regime_label(rid: str) -> str:
    """Humanize a convergence-regime id via the display registry (bullish_drought_squeeze ->
    'drought squeeze (bullish)'); falls back to the raw de-underscored id if the registry is missing."""
    try:
        from leviathan.graphrag import display as dp
        return dp.regime_label(rid)
    except Exception:  # noqa: BLE001
        return rid.replace("_", " ")


def _sign_phrase(s: str) -> str:                                         # bare, mid-sentence (from sign=+ / sign +)
    return "points to higher prices" if s == "+" else "points to lower prices"


def _paren_sign(s: str) -> str:                                          # parenthetical (from (+) / (-))
    return "upward price pressure" if s == "+" else "downward price pressure"


_MOOD = re.compile(r"\b(bullish|bearish)\b", re.I)                       # mood labels never belong in reader prose


def _mood_word(m) -> str:                                                # safety net (mirror the regime suffix vocab)
    return "price-supportive" if m.group(1).lower() == "bullish" else "price-pressuring"


def _conf_sub(m) -> str:
    v = m.group(1).lower()
    return f"{'medium' if v == 'med' else v} confidence"


@functools.lru_cache(maxsize=1)
def _display_map() -> dict[str, str]:
    """slug -> reader name from the hierarchy: '{exchange} {node}' (soybeans_cbot -> 'CBOT soybeans',
    soybean_oil_dce -> 'DCE soybean oil'); fallback to the de-underscored slug."""
    try:
        from leviathan.graphrag import evidence as ev
        contracts = ev._hier().get("contracts") or {}
    except Exception:  # noqa: BLE001
        return {}
    out: dict[str, str] = {}
    for slug, meta in contracts.items():
        if "_" not in slug:
            continue
        if isinstance(meta, dict):
            node = str(meta.get("node") or slug).replace("_", " ")
            exch = meta.get("exchange")
            out[slug] = (f"{exch} {node}".strip() if exch else node)
        else:
            out[slug] = slug.replace("_", " ")
    return out


def sanitize(text: str, *, market_register: str = FENCED, bar_licence=None) -> str:
    """Rewrite internal tokens into a commodity researcher's register: `conf=high`->"high confidence",
    `sign=+`->"points to higher prices", `(+)`->"(upward price pressure)", any residual "bullish"/"bearish"
    ->"price-supportive"/"price-pressuring", raw contract slugs->spelled-out names, structural markers stripped.
    Leaves the ```mermaid block untouched (the diagram may carry signs), and preserves citation markers
    ([E1]/[N2]), numbers, and dates. Idempotent.

    INVARIANTS (W5-D2 Step 4):
        internal_leaks(sanitize(x, market_register=ANY))     == []   # unconditional -- a leak is a bug
        exec_leaks(sanitize(x, market_register=ANY))         == []   # A2 execution idioms, unconditional
        market_leaks(sanitize(x, market_register=FENCED))    == []   # today's invariant, unchanged
        unbacked_levels(sanitize(x, market_register=OUTLOOK)) == []  # W5.0: a bare number is a refusal

    `market_register` is KEYWORD-ONLY and defaults to FENCED, so the twelve existing call sites are
    byte-identical and the relaxation reaches only a seam that opted in by name. On OUTLOOK the mood words
    (bullish/bearish) also survive, per W5.0 -- they are a directional read, and the derivation gate, not
    the lexicon, is what keeps that read honest.

    `bar_licence` (S7b R1) rides the SAME discipline for the same reason and reaches exactly ONE decision
    -- `_is_banned_sentence`'s strike -- so the four invariants above hold with it on and off, with one
    stated exception which is the whole point of it: `market_leaks(sanitize(x, FENCED))` may now return a
    BAR-ADJECTIVE pair that the strip used to delete. The adjective is still COUNTED everywhere it was
    (the counters are untouched); what changed is that the reader keeps the sentence, its figure and its
    handle. IDEMPOTENT with the licence on: the licence is a pure function of the sentence, and the
    remedy that binds a figure runs upstream at the answer seam, never here."""
    if not text:
        return text
    outlook = (market_register == OUTLOOK)
    # ONE derivation verdict for the whole text -- but it is APPLIED per sentence position, only inside the
    # derivation unit (`_outlook_span`). Computed before the mermaid split so a fenced diagram cannot
    # change it. `_has_unit` records whether a '## Outlook' heading was rendered at all: if one was and
    # THIS segment does not carry it, the segment sits outside the unit and gets NO exemption (fail-closed
    # -- a mermaid fence between the heading and its prose must never widen the gate).
    deriv_ok = outlook_derivation_ok(_strip_mermaid(text)) if outlook else False
    _has_unit = bool(_OUTLOOK_HEADING.search(_strip_mermaid(text))) if outlook else False
    disp = _display_map()
    parts = re.split(r"(```mermaid.*?```)", text, flags=re.S)             # keep the diagram fenced-off
    for i, seg in enumerate(parts):
        if seg.startswith("```mermaid"):
            continue
        seg = _CONF.sub(_conf_sub, seg)
        seg = _SIGNKV.sub(lambda m: _sign_phrase(m.group(1)), seg)
        seg = _PARENSIGN.sub(lambda m: "(mixed)" if m.group(1) is None else f"({_paren_sign(m.group(1))})", seg)
        seg = _STRUCT.sub("", seg)
        seg = _STRUCT_BARE.sub("", seg)
        for rx, repl in _JARGON_SUBS:
            seg = rx.sub(repl, seg)
        for slug in _slugs():                                            # longest-first (from _slugs) -> no partials
            seg = re.sub(r"\b" + re.escape(slug) + r"\b", disp.get(slug, slug.replace("_", " ")), seg)
        for rid in _regime_ids():                                        # longest-first -> humanize regime ids
            seg = re.sub(r"\b" + re.escape(rid) + r"\b", _regime_label(rid), seg)
        # PA-10(b): a LABELED metric slug is replaced by its analyst label, the way the three classes above
        # are. `(?<!\.)` is the DETECTOR's own exemption, copied verbatim: "silver_wasde.avg_farm_price" in
        # agent guidance is an ADDRESS the agent queries with, not display prose (owner-ratified
        # 2026-08-22), and a sanitizer that rewrote it would break the syntax it is teaching. Longest-first,
        # so a slug that contains a shorter one cannot be half-rewritten. Labels carry no underscores, so
        # the pass stays idempotent -- the same property the SAGIS de-underscore relies on.
        for _mid, _lab in _metric_labels():                              # lambda repl: a label is LITERAL
            seg = re.sub(r"(?<!\.)\b" + re.escape(_mid) + r"\b", lambda _m, _l=_lab: _l, seg)
        seg = _SAGIS_CROP_RX.sub(lambda m: m.group(1).replace("_", " "), seg)   # SAGIS crop code -> friendly
        if not outlook:                                                  # W5.0: _MOOD permitted on outlook turns
            seg = _MOOD.sub(_mood_word, seg)                             # neutralize any residual mood word
        _span = None
        if outlook:
            _span = _outlook_span(seg) if (not _has_unit or _OUTLOOK_HEADING.search(seg)) else (0, 0)
        seg = _strip_banned_sentences(seg, market_register=market_register,   # LAST: strip valuation/flow/
                                      derivation_ok=deriv_ok,                 #  Lane-B / A2 / unbacked-level
                                      unit_span=_span, bar_licence=bar_licence)
        parts[i] = seg                                                   #   (never a paraphrase -- DP-6 strip)
    return "".join(parts)
