"""Serving-parameter loader — the missing reader for configs/graphrag/params.yaml (section 9.1's rule:
no knob may be hardcoded; every value is a reviewable, versioned decision).

The RERANK_POOL episode is the motivating case: a quality-relevant retrieval knob shipped as a code
constant on an assertion, caught only by a paid eval challenge. Externalized knobs are visible in
review, tunable without a code change, and A/B-able later (Langfuse) without new plumbing.

Contract: `get("serving.walk.tau", 0.35)` — dotted path into params.yaml, code default as fallback.
The YAML is PRIVATE IP (gitignored, rides in the image); a public clone without it runs entirely on
the code defaults, so defaults MUST stay in the call sites, not here.
"""
from __future__ import annotations

import os
from pathlib import Path

_CACHE: dict | None = None


def _load() -> dict:
    global _CACHE
    if _CACHE is None:
        path = os.environ.get("GRAPHRAG_PARAMS", "configs/graphrag/params.yaml")
        try:
            import yaml
            _CACHE = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        except Exception:  # noqa: BLE001 — missing/broken config -> code defaults, never fatal
            _CACHE = {}
    return _CACHE


def get(path: str, default):
    """Dotted-path read with the call site's default as the authority when the YAML lacks the key."""
    node = _load()
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return default if node is None else node


def reload() -> None:
    """Drop the memo (tests + long-lived processes after a config edit)."""
    global _CACHE
    _CACHE = None
