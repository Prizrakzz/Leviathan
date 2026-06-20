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
}


def _vocab() -> tuple[set[str], set[str]]:
    v = yaml.safe_load((_CFG / "entity_vocabulary.yaml").read_text(encoding="utf-8"))
    node_types = set(v.get("nodes", {}).keys())
    edges = set(v.get("edges", {}).keys())
    return node_types, edges


def validate() -> list[str]:
    node_types, edges = _vocab()
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
            # vocab consistency for extraction labels
            for ent in rec.get("entities", []):
                if ent.get("type") not in node_types:
                    errs.append(f"{fname}:{ln} entity type {ent.get('type')!r} not a vocab node type")
            for ed in rec.get("edges", []):
                if ed.get("rel") not in edges:
                    errs.append(f"{fname}:{ln} edge rel {ed.get('rel')!r} not in vocab edges")
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
