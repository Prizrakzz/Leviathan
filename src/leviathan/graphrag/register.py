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


def register_leaks(text: str) -> list[tuple[str, str]]:
    """(token, short-context) for each internal-representation leak in the reader prose. Empty list = clean."""
    prose = _strip_mermaid(text)
    hits: list[tuple[str, str]] = []
    for rx in (_MARKERS, _SIGN, _JARGON):
        for m in rx.finditer(prose):
            hits.append((m.group(0).strip(), _ctx(prose, m)))
    for slug in _slugs():
        for m in re.finditer(r"\b" + re.escape(slug) + r"\b", prose):
            hits.append((slug, _ctx(prose, m)))
    for rid in _regime_ids():                                            # raw convergence-regime id in prose
        for m in re.finditer(r"\b" + re.escape(rid) + r"\b", prose):
            hits.append((rid, _ctx(prose, m)))
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
]


def _regime_label(rid: str) -> str:
    """Humanize a convergence-regime id via the display registry (bullish_drought_squeeze ->
    'drought squeeze (bullish)'); falls back to the raw de-underscored id if the registry is missing."""
    try:
        from leviathan.graphrag import display as dp
        return dp.regime_label(rid)
    except Exception:  # noqa: BLE001
        return rid.replace("_", " ")


def _sign_word(s: str) -> str:
    return "bullish" if s == "+" else "bearish"


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
    `sign=+`/`(+)`->"bullish", raw contract slugs->spelled-out names, structural markers stripped. Leaves the
    ```mermaid block untouched (the diagram may carry signs), and preserves citation markers ([E1]/[N2]),
    numbers, and dates. Idempotent, and register_leaks(sanitize(x)) == []."""
    if not text:
        return text
    disp = _display_map()
    parts = re.split(r"(```mermaid.*?```)", text, flags=re.S)             # keep the diagram fenced-off
    for i, seg in enumerate(parts):
        if seg.startswith("```mermaid"):
            continue
        seg = _CONF.sub(_conf_sub, seg)
        seg = _SIGNKV.sub(lambda m: _sign_word(m.group(1)), seg)
        seg = _PARENSIGN.sub(lambda m: "(mixed)" if m.group(1) is None else f"({_sign_word(m.group(1))})", seg)
        seg = _STRUCT.sub("", seg)
        seg = _STRUCT_BARE.sub("", seg)
        for rx, repl in _JARGON_SUBS:
            seg = rx.sub(repl, seg)
        for slug in _slugs():                                            # longest-first (from _slugs) -> no partials
            seg = re.sub(r"\b" + re.escape(slug) + r"\b", disp.get(slug, slug.replace("_", " ")), seg)
        for rid in _regime_ids():                                        # longest-first -> humanize regime ids
            seg = re.sub(r"\b" + re.escape(rid) + r"\b", _regime_label(rid), seg)
        parts[i] = seg
    return "".join(parts)
