"""Geography ROUTING index (Phase 5.8) — country -> {contracts, drivers} for query routing.

Geography is routing metadata, NOT a causal node: a country has no mechanism, so the causal DAGs stay
commodity-anchored (design decision 2026-07-06). This module lets the orchestrator answer geography-led
questions that name no tradeable contract ("news on India", "Black Sea wheat") by resolving a country to
the contracts + drivers it materially moves — the ~13 majors are curated in ``configs/graphrag/
geography.yaml`` and every country's HOME contracts are additionally derived from
``commodity_hierarchy.yaml`` ``origin`` (so a curation omission can never drop them).

Public code; reads the git-ignored ``configs/graphrag/`` IP at runtime (same pattern as ``hierarchy`` /
``config_check``). Entirely deterministic + hermetic — no network, no model.

    python -m leviathan.graphrag.geography      # prints check_geography result
"""
from __future__ import annotations

import functools
import sys
from pathlib import Path

import yaml

_CFG = Path(__file__).resolve().parents[3] / "configs" / "graphrag"


@functools.lru_cache(maxsize=1)
def _geo() -> dict:
    return yaml.safe_load((_CFG / "geography.yaml").read_text(encoding="utf-8")) or {}


@functools.lru_cache(maxsize=1)
def _origin_index() -> dict[str, list[str]]:
    """origin_token -> [contract slugs] from commodity_hierarchy.yaml (the auto-derived HOME contracts)."""
    from leviathan.graphrag import hierarchy as hy
    out: dict[str, list[str]] = {}
    for slug, spec in (hy._hierarchy().get("contracts", {})).items():
        origin = spec.get("origin")
        if origin and origin != "global":
            out.setdefault(origin, []).append(slug)
    return out


def _countries() -> dict[str, dict]:
    return _geo().get("countries", {})


@functools.lru_cache(maxsize=1)
def _matcher():
    """Accent/case-insensitive, WORD-BOUNDARY matcher over every country's aliases -> the alias->country
    map. Word-boundary (via harvest.build_matcher) means 'india' never matches inside 'indiana'."""
    from leviathan.graphrag import harvest as hv
    alias_to_id: dict[str, str] = {}
    forms: list[str] = []
    for cid, spec in _countries().items():
        for a in (spec.get("aliases") or []):
            alias_to_id[a.lower()] = cid
            forms.append(a)
    return hv.build_matcher(forms), alias_to_id


def all_country_ids() -> list[str]:
    return list(_countries().keys())


def resolve_country(text: str) -> str | None:
    """The country a query names, or None. First lexical hit wins (queries name one country in practice)."""
    if not text:
        return None
    matcher, alias_to_id = _matcher()
    hits = matcher.findall(text) if matcher else []
    for h in hits:
        cid = alias_to_id.get(str(h).lower())
        if cid:
            return cid
    return None


def contracts_for(country: str, graph=None) -> list[str]:
    """The tracked contracts a country moves = curated ∪ origin-derived HOME contracts, order-preserving,
    de-duplicated. Filtered to real ``graph.contracts`` when a graph is given (routing must never emit an
    id the graph doesn't have)."""
    spec = _countries().get(country) or {}
    out: list[str] = list(spec.get("contracts") or [])
    for slug in _origin_index().get(spec.get("origin_token", ""), []):
        if slug not in out:
            out.append(slug)
    if graph is not None:
        valid = set(getattr(graph, "contracts", {}) or {})
        out = [c for c in out if c in valid]
    return out


def drivers_for(country: str) -> list[str]:
    return list((_countries().get(country) or {}).get("drivers") or [])


def check_geography() -> list[str]:
    """Every curated contract is a real graph contract (causal DAG stem); every driver exists in
    driver_slices.yaml; every region is an entity_vocabulary region; every origin_token is a hierarchy
    origin. Offline — reads the causal dir + configs, no graph load."""
    errs: list[str] = []
    contracts = {p.stem for p in (_CFG / "causal").glob("*.yaml")}
    ds = yaml.safe_load((_CFG / "driver_slices.yaml").read_text(encoding="utf-8")) or {}
    drivers = set((ds.get("drivers") or {}).keys()) | set((ds.get("dag_alias") or {}).keys())
    vocab_nodes = (yaml.safe_load((_CFG / "entity_vocabulary.yaml").read_text(encoding="utf-8")) or {}).get("nodes", {})
    regions = set(vocab_nodes.get("region") or [])
    origins = set(vocab_nodes.get("country_origin") or [])   # the 44 canonical country tokens (a country
    # with no HOME contract — India, Russia, Ukraine — is still a valid origin_token; origin-derive yields [])

    if not contracts:
        errs.append("no causal DAG stems found — cannot validate geography contracts")
    for cid, spec in _countries().items():
        if not (spec.get("aliases") or []):
            errs.append(f"country {cid}: no aliases (undetectable)")
        for c in (spec.get("contracts") or []):
            if c not in contracts:
                errs.append(f"country {cid}: contract {c!r} is not a real graph contract")
        for d in (spec.get("drivers") or []):
            if d not in drivers:
                errs.append(f"country {cid}: driver {d!r} not in driver_slices.yaml")
        for r in (spec.get("regions") or []):
            if r not in regions:
                errs.append(f"country {cid}: region {r!r} not an entity_vocabulary region")
        ot = spec.get("origin_token")
        if ot and ot not in origins:
            errs.append(f"country {cid}: origin_token {ot!r} not a hierarchy origin")
    return errs


def main() -> int:
    errs = check_geography()
    if errs:
        print("FAIL geography:")
        for e in errs:
            print(f"  - {e}")
        return 1
    print(f"PASS geography ({len(_countries())} countries; contracts/drivers/regions resolve)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
