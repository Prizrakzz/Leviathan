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
    return hits
