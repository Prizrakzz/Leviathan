"""Display-name registry (Phase 6.1) — the SINGLE source of user-facing names for internal ids.

Evidence `source=` partition ids, silver table names, and convergence-regime names are INTERNAL and must
never reach the reader. This module maps them to official / plain-English names (from the git-ignored
``configs/graphrag/display_names.yaml``) and, for anything unmapped, falls back to a readable Title-Cased
de-underscore — so a missing id is never shown as a raw slug.

Public code; reads the git-ignored ``configs/graphrag/`` IP at runtime (same pattern as ``geography`` /
``hierarchy``). Entirely deterministic + hermetic — no network, no model.

    python -m leviathan.graphrag.display        # prints check_display_names result
"""
from __future__ import annotations

import functools
import re
import sys
from pathlib import Path

import yaml

_CFG = Path(__file__).resolve().parents[3] / "configs" / "graphrag"


@functools.lru_cache(maxsize=1)
def _cfg() -> dict:
    p = _CFG / "display_names.yaml"
    if not p.exists():
        return {}
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def _sources() -> dict[str, str]:
    return _cfg().get("sources") or {}


def _tables() -> dict[str, str]:
    return _cfg().get("tables") or {}


def _regimes() -> dict[str, str]:
    return _cfg().get("regimes") or {}


def _titleize(raw: str) -> str:
    """Readable fallback for an unmapped id: de-underscore + word-title, keeping short tokens upper
    (US, EU, FX, ONI, PSD) and not lower-casing an already-mixed token."""
    words = []
    for w in re.split(r"[_\s]+", (raw or "").strip()):
        if not w:
            continue
        words.append(w.upper() if len(w) <= 3 else (w if any(c.isupper() for c in w) else w.capitalize()))
    return " ".join(words)


def source_name(raw: str) -> str:
    """Official display name for a document-evidence source id (usda_gain_corn -> 'USDA FAS GAIN Report —
    Corn'); unmapped -> Title-Cased de-underscore. Idempotent for already-official strings (a value not
    matching any id and containing a space/dash is returned unchanged)."""
    if not raw:
        return raw
    m = _sources()
    if raw in m:
        return m[raw]
    # already a display name (has spacing/punctuation, not a bare slug) -> leave as is
    if " " in raw or "—" in raw:
        return raw
    return _titleize(raw)


def table_label(table: str) -> str:
    """Display label for a silver table (silver_noaa_oni -> 'NOAA ONI'); unmapped -> strip 'silver_' +
    upper de-underscore (preserves the legacy citations._source_label output for unmapped tables)."""
    if not table:
        return table
    m = _tables()
    if table in m:
        return m[table]
    return table.replace("silver_", "").replace("_", " ").upper()


def _dir_suffix(name: str) -> str:
    n = name.lower()
    if n.startswith("bullish_") or "bull" in n:
        return " (bullish)"
    if n.startswith("bearish_") or "bear" in n:
        return " (bearish)"
    return ""


def regime_label(name: str) -> str:
    """Human label for a convergence-regime id (bullish_drought_squeeze -> 'drought squeeze (bullish)');
    unmapped -> strip a bullish_/bearish_ prefix, de-underscore, append the inferred direction. Always
    readable — a raw regime id can never reach the reader through this path."""
    if not name:
        return name
    m = _regimes()
    if name in m:
        return m[name]
    core = re.sub(r"^(bullish|bearish|neutral)_", "", name.lower())
    return _titleize(core) + _dir_suffix(name)


def _nodes() -> dict[str, str]:
    return _cfg().get("nodes") or {}


@functools.lru_cache(maxsize=1)
def _contracts_hier() -> dict:
    """contract slug -> hierarchy meta ({node, exchange, ...}) for map node labels. Same source as the
    register slug map, read lazily so display.py stays import-cycle-free."""
    try:
        from leviathan.graphrag import evidence as ev
        return ev._hier().get("contracts") or {}
    except Exception:  # noqa: BLE001 — hierarchy missing -> de-underscore fallback
        return {}


def _contract_label(slug: str) -> str:
    meta = _contracts_hier().get(slug)
    if isinstance(meta, dict):
        node = str(meta.get("node") or slug).replace("_", " ")
        exch = meta.get("exchange")
        return f"{exch} {node}".strip() if exch else node
    return slug.replace("_", " ")


def node_label(node_id: str, kind: str | None = None, contract: str | None = None) -> str:
    """Human label for a causal-map node (6.3) — the one-vocabulary rule extended to the DAG surface. A
    curated `nodes:` override wins; contract/commodity nodes get '{EXCH} {node}' from the hierarchy; a
    driver id is de-underscored PRESERVING token case (so BRL/USD/ENSO/La_Niña read right — title-casing
    would mangle them). A raw slug never renders as node text."""
    if not node_id:
        return node_id
    ov = _nodes().get(node_id)
    if ov:
        return ov
    if kind in ("contract", "commodity"):
        return _contract_label(node_id)
    return node_id.replace("_", " ")


@functools.lru_cache(maxsize=1)
def all_driver_ids() -> frozenset[str]:
    """Every driver id declared across configs/graphrag/causal/*.yaml (for the `nodes:` override lint)."""
    ids: set[str] = set()
    for p in sorted((_CFG / "causal").glob("*.yaml")):
        try:
            doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except Exception:  # noqa: BLE001
            continue
        for d in (doc.get("drivers") or []):
            did = d.get("id") if isinstance(d, dict) else None
            if did:
                ids.add(str(did))
    return frozenset(ids)


@functools.lru_cache(maxsize=1)
def all_regime_ids() -> tuple[str, ...]:
    """Every convergence-regime name declared across configs/graphrag/causal/*.yaml (the authoritative
    set the sanitizer humanizes and the lint checks). Longest-first so substitution never leaves a
    partial. Hermetic — reads the YAMLs directly, no graph load."""
    ids: set[str] = set()
    for p in sorted((_CFG / "causal").glob("*.yaml")):
        try:
            doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except Exception:  # noqa: BLE001 — a malformed YAML is caught by causal_check, not here
            continue
        for sig in (doc.get("convergence") or []):
            nm = sig.get("name") if isinstance(sig, dict) else None
            if nm:
                ids.add(str(nm))
    return tuple(sorted(ids, key=len, reverse=True))


def check_display_names() -> list[str]:
    """Registry integrity: every curated regime/table key is a plausible id, and — the guarantee —
    EVERY convergence regime in the causal DAGs has a curated `regimes:` entry (so no unpolished regime
    id can leak). Offline; reads the causal dir + display_names.yaml, no graph load."""
    errs: list[str] = []
    if not _cfg():
        errs.append("display_names.yaml missing or empty")
        return errs
    causal_ids = set(all_regime_ids())
    if not causal_ids:
        errs.append("no convergence regimes found in causal/*.yaml — cannot validate regime coverage")
    curated = set(_regimes())
    for rid in sorted(causal_ids - curated):
        errs.append(f"regime {rid!r} has no display label in display_names.yaml (regimes:)")
    for rid in sorted(curated - causal_ids):
        errs.append(f"regime label {rid!r} is stale — not a real convergence regime in causal/*.yaml")
    for t in _tables():
        if not t.startswith("silver_"):
            errs.append(f"table key {t!r} should start with 'silver_'")
    drivers = all_driver_ids()
    for nid in sorted(_nodes()):                                    # every `nodes:` override is a real driver id
        if drivers and nid not in drivers:
            errs.append(f"node override {nid!r} is not a real driver id in causal/*.yaml")
    return errs


def main() -> int:
    errs = check_display_names()
    if errs:
        print("FAIL display_names:")
        for e in errs:
            print(f"  - {e}")
        return 1
    print(f"PASS display_names ({len(_sources())} sources, {len(_tables())} tables, "
          f"{len(_regimes())} regimes; all causal regimes labelled)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
