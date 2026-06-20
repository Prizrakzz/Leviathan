"""GraphRAG commodity hierarchy / concept expansion (Phase 1.5).

Bridges CONTRACT (a tradeable leviathan slug) ↔ NODE (the causal graph node) ↔ GROUP/COMPLEX (a set
a user names at once). The cascade reasons over *nodes*; the user holds *contracts* and asks about
*groups/complexes*. ``expand_concept`` turns a resolved concept into the member set + the recommended
expansion policy, so "effect of El Niño on all wheat" runs a cascade per class node and the
synthesizer can surface where members diverge — never one blended answer that averages the spread away.

Inputs are *canonical* names (the entity-linker resolves free text → canonical via the vocab aliases
first). Public code; reads the git-ignored ``configs/graphrag/`` IP at runtime (same pattern as
``config_check``/``gold``).

    python -m leviathan.graphrag.hierarchy      # prints coverage_check result
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import get_args

import yaml

from leviathan.common.types import CommodityName

_CFG = Path(__file__).resolve().parents[3] / "configs" / "graphrag"
_LEGACY_VOCAB = Path(__file__).resolve().parents[3] / "configs" / "sources" / "entity_vocabulary.yaml"
ALL_CONTRACTS = frozenset(get_args(CommodityName))


def _hierarchy() -> dict:
    return yaml.safe_load((_CFG / "commodity_hierarchy.yaml").read_text(encoding="utf-8"))


def _vocab_nodes() -> set[str]:
    v = yaml.safe_load((_CFG / "entity_vocabulary.yaml").read_text(encoding="utf-8"))
    return {t for terms in v.get("nodes", {}).values() if terms for t in terms}


@dataclass(frozen=True)
class ExpansionResult:
    concept: str
    kind: str                    # complex | group | node | contract | unknown
    nodes: tuple[str, ...]       # causal nodes to run the cascade over
    contracts: tuple[str, ...]   # tradeable instruments those nodes map to
    policy: str                  # enumerate_divergent | benchmark | abstain
    multi: bool                  # >1 node → divergences must be surfaced, never averaged


def contract_to_node(slug: str) -> tuple[str, str] | None:
    """A held position → (causal node, reference origin). None if the slug isn't a known contract."""
    spec = _hierarchy().get("contracts", {}).get(slug)
    return (spec["node"], spec.get("origin", "global")) if spec else None


def contracts_for_nodes(nodes) -> list[str]:
    want = set(nodes)
    return [s for s, spec in _hierarchy().get("contracts", {}).items() if spec["node"] in want]


def nodes_in_group(group: str) -> list[str]:
    return list(_hierarchy().get("groups", {}).get(group, []))


def members_of_complex(name: str) -> list[str]:
    return list(_hierarchy().get("complexes", {}).get(name, []))


def expand_concept(concept: str) -> ExpansionResult:
    """Resolve a canonical concept to its member nodes + expansion policy.

    Precedence **complex > group > node > contract** — so a bare commodity name (``corn``,
    ``arabica_coffee``) expands to all its contracts, while a suffixed position slug
    (``soft_red_winter_wheat_cbot``) resolves to its single instrument. A name shared by a node and a
    complex (``wheat``) expands to the complex (the node is the un-expanded concept).
    """
    h = _hierarchy()
    if concept in h.get("complexes", {}):
        nodes = members_of_complex(concept)
        return ExpansionResult(concept, "complex", tuple(nodes), tuple(contracts_for_nodes(nodes)),
                               "enumerate_divergent", len(nodes) > 1)
    if concept in h.get("groups", {}):
        nodes = nodes_in_group(concept)
        return ExpansionResult(concept, "group", tuple(nodes), tuple(contracts_for_nodes(nodes)),
                               "enumerate_divergent", len(nodes) > 1)
    if concept in _vocab_nodes():
        contracts = contracts_for_nodes([concept])
        return ExpansionResult(concept, "node", (concept,), tuple(contracts), "benchmark", False)
    if concept in h.get("contracts", {}):
        node = h["contracts"][concept]["node"]
        return ExpansionResult(concept, "contract", (node,), (concept,), "benchmark", False)
    return ExpansionResult(concept, "unknown", (), (), "abstain", False)


def coverage_check() -> list[str]:
    """Every leviathan contract maps to a real vocab node; no stray keys; group/complex members real.

    Also confirms the harvest lost nothing — every legacy-canonical commodity still resolves.
    """
    h = _hierarchy()
    contracts = h.get("contracts", {})
    nodes = _vocab_nodes()
    errs: list[str] = []

    for slug in ALL_CONTRACTS:
        if slug not in contracts:
            errs.append(f"contract {slug!r} not mapped in commodity_hierarchy")
    for slug, spec in contracts.items():
        if slug not in ALL_CONTRACTS:
            errs.append(f"hierarchy contract {slug!r} not in ALL_COMMODITIES")
        if spec["node"] not in nodes:
            errs.append(f"contract {slug}: node {spec['node']!r} not a vocab node")
    for grp, members in h.get("groups", {}).items():
        for m in members:
            if m not in nodes:
                errs.append(f"group {grp}: member {m!r} not a vocab node")
    for cx, members in h.get("complexes", {}).items():
        for m in members:
            if m not in nodes:
                errs.append(f"complex {cx}: member {m!r} not a vocab node")

    # harvest completeness: every legacy canonical slug still resolves to a contract node.
    if _LEGACY_VOCAB.exists():
        legacy = yaml.safe_load(_LEGACY_VOCAB.read_text(encoding="utf-8"))
        for name, spec in (legacy.get("commodities") or {}).items():
            canon = spec.get("canonical")
            if canon and canon not in contracts:
                errs.append(f"legacy canonical {canon!r} ({name}) no longer resolves to a contract")
    return errs


def main() -> int:
    errs = coverage_check()
    if errs:
        print("FAIL hierarchy:")
        for e in errs:
            print(f"  - {e}")
        return 1
    print(f"PASS hierarchy ({len(ALL_CONTRACTS)} contracts mapped to nodes; groups/complexes resolve)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
