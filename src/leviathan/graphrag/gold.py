"""GraphRAG Phase 1 W6 — gold-set format validator (public code, reads git-ignored gold/).

Validates the five JSONL gold sets: required fields present, and every referenced entity *type*
/ edge *relation* exists in the vocabulary — so a label can never silently reference a node/edge
the graph won't have. Does NOT judge label *correctness* (that's domain review); it enforces
*format + vocab-consistency* so the §9 gates compute on well-formed data.

    python -m leviathan.graphrag.gold
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

_REPO = Path(__file__).resolve().parents[3]
_CFG = _REPO / "configs" / "graphrag"
_GOLD = _CFG / "gold"

_REQUIRED = {
    "extraction.jsonl": {"id", "chunk", "entities", "edges"},
    "routing.jsonl": {"id", "query", "intent", "retrieval_modes"},
    "cascade.jsonl": {"id", "root", "template", "expected_hops"},
    "entity_linking.jsonl": {"id", "mention", "expected"},
    "generalization.jsonl": {"id", "query", "expect"},
    "expansion.jsonl": {"id", "concept", "expected_nodes", "policy"},
}

_EXPANSION_POLICIES = {"enumerate_divergent", "benchmark", "aggregate", "abstain"}


def _vocab() -> tuple[dict[str, set[str]], set[str], set[str]]:
    v = yaml.safe_load((_CFG / "entity_vocabulary.yaml").read_text(encoding="utf-8"))
    # node_members maps each node *type* → its closed set of canonical terms. `event` (and any
    # empty list) is an OPEN type: instances are minted at extraction, so membership isn't checked.
    node_members = {t: set(terms) for t, terms in v.get("nodes", {}).items() if terms}
    node_types = set(v.get("nodes", {}).keys())
    edges = set(v.get("edges", {}).keys())
    return node_members, node_types, edges


def validate() -> list[str]:
    node_members, node_types, edges = _vocab()
    errs: list[str] = []
    for fname, required in _REQUIRED.items():
        path = _GOLD / fname
        if not path.exists():
            errs.append(f"{fname}: missing")
            continue
        n = 0
        for ln, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            line = line.strip()
            if not line:
                continue
            n += 1
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as e:
                errs.append(f"{fname}:{ln} invalid JSON ({e})")
                continue
            missing = required - rec.keys()
            if missing:
                errs.append(f"{fname}:{ln} missing fields {sorted(missing)}")
            # vocab consistency + node-model enforcement for extraction labels.
            for ent in rec.get("entities", []):
                etype, eid = ent.get("type"), ent.get("id")
                if etype not in node_types:
                    errs.append(f"{fname}:{ln} entity type {etype!r} not a vocab node type")
                # Node-model: a closed-type entity id MUST be a canonical node (no composites like
                # `arabica_production` typed commodity; metrics belong in `quant`, never as entities).
                elif etype in node_members and eid not in node_members[etype]:
                    errs.append(f"{fname}:{ln} entity {eid!r} is not a canonical {etype} node "
                                f"(use the canonical term; metrics go in `quant`)")
            for ed in rec.get("edges", []):
                if ed.get("rel") not in edges:
                    errs.append(f"{fname}:{ln} edge rel {ed.get('rel')!r} not in vocab edges")
            # expansion labels: expected_nodes must be real nodes; policy from the closed set.
            if fname == "expansion.jsonl":
                all_nodes = set().union(*node_members.values())
                for nd in rec.get("expected_nodes", []):
                    if nd not in all_nodes:
                        errs.append(f"{fname}:{ln} expected_node {nd!r} not a vocab node")
                if rec.get("policy") not in _EXPANSION_POLICIES:
                    errs.append(f"{fname}:{ln} policy {rec.get('policy')!r} not in {_EXPANSION_POLICIES}")
        if n == 0:
            errs.append(f"{fname}: empty")
        else:
            print(f"  {fname}: {n} records")
    return errs


def main() -> int:
    print("gold-set validation:")
    errs = validate()
    if errs:
        print("FAIL gold:")
        for e in errs:
            print(f"  - {e}")
        return 1
    print("PASS gold (format + vocab-consistency; correctness pending domain review)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
