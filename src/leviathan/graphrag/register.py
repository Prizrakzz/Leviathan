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
_EXCLUDED_NOUN = re.compile(r"\b(stocks?|supplies|crop|soil|lineup)\b", re.I)   # honest ag fundamentals -> not Lane B
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


def _is_banned_sentence(sent: str) -> bool:
    if _VALUATION_PHRASES.search(sent) or _FLOW_PHRASES.search(sent):
        return True
    if _SPREAD_NOUN.search(sent) and _CONVERGE_VERB.search(sent) and _FUTURITY.search(sent):
        return True
    if _PERSISTENCE.search(sent) and _PRICE_SPREAD_NOUN.search(sent):
        return True
    return bool(_lane_b_in_sentence(sent, _LANE_B_VAL_RX) or _lane_b_in_sentence(sent, _LANE_B_FLOW_RX))


def _strip_banned_sentences(seg: str) -> str:
    """Drop each sentence carrying a Lane A / class-rule / Lane B leak (the verify.py strip precedent). Never
    a paraphrase. Superset of register_leaks' new-lane conditions, so register_leaks(sanitize(x)) == [] holds."""
    if not (_VALUATION_PHRASES.search(seg) or _FLOW_PHRASES.search(seg) or _LANE_B_ADJ.search(seg)
            or _PERSISTENCE.search(seg) or (_SPREAD_NOUN.search(seg) and _CONVERGE_VERB.search(seg))):
        return seg
    toks = _SENT_KEEP.split(seg)
    out: list[str] = []
    for i in range(0, len(toks), 2):
        text = toks[i]
        delim = toks[i + 1] if i + 1 < len(toks) else ""
        if text and _is_banned_sentence(text):
            continue
        out.append(text + delim)
    return "".join(out)


def register_leaks(text: str) -> list[tuple[str, str]]:
    """(token, short-context) for each internal-representation leak in the reader prose. Empty list = clean."""
    prose = _strip_mermaid(text)
    hits: list[tuple[str, str]] = []
    for rx in (_MARKERS, _SIGN, _JARGON, _PROSE_PHRASES, _VALUATION_PHRASES, _FLOW_PHRASES):
        for m in rx.finditer(prose):
            hits.append((m.group(0).strip(), _ctx(prose, m)))
    hits += _class_rule_hits(prose)
    for slug in _slugs():
        for m in re.finditer(r"\b" + re.escape(slug) + r"\b", prose):
            hits.append((slug, _ctx(prose, m)))
    for rid in _regime_ids():                                            # raw convergence-regime id in prose
        for m in re.finditer(r"\b" + re.escape(rid) + r"\b", prose):
            hits.append((rid, _ctx(prose, m)))
    for m in _SAGIS_CROP_RX.finditer(prose):                             # underscored SAGIS crop code in prose
        hits.append((m.group(0), _ctx(prose, m)))
    return hits


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


def sanitize(text: str) -> str:
    """Rewrite internal tokens into a commodity researcher's register: `conf=high`->"high confidence",
    `sign=+`->"points to higher prices", `(+)`->"(upward price pressure)", any residual "bullish"/"bearish"
    ->"price-supportive"/"price-pressuring", raw contract slugs->spelled-out names, structural markers stripped.
    Leaves the ```mermaid block untouched (the diagram may carry signs), and preserves citation markers
    ([E1]/[N2]), numbers, and dates. Idempotent, and register_leaks(sanitize(x)) == []."""
    if not text:
        return text
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
        seg = _SAGIS_CROP_RX.sub(lambda m: m.group(1).replace("_", " "), seg)   # SAGIS crop code -> friendly
        seg = _MOOD.sub(_mood_word, seg)                                 # neutralize any residual mood word
        seg = _strip_banned_sentences(seg)                               # LAST: strip valuation/flow/Lane-B sentences
        parts[i] = seg                                                   #   (never a paraphrase -- DP-6 strip)
    return "".join(parts)
