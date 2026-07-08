"""GraphRAG Phase 1 config validators — the W3/W5 exit gate, as code.

Public code; it reads the git-ignored ``configs/graphrag/`` IP at runtime. Two checks:

  * **vocab linter** — no surface form is both a node and an edge; arbitration targets resolve
    to real roles; aliases point at real canonical nodes; node/edge name hygiene.
  * **node_silver_map resolver** — every metric's (table, column) actually exists in the silver
    Athena DDLs (``sql/athena/ddl/``), so silver-confirmation (§4.3) isn't hand-wave.

    python -m leviathan.graphrag.config_check        # exits non-zero on any failure
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

_REPO = Path(__file__).resolve().parents[3]
_CFG = _REPO / "configs" / "graphrag"
_DDL = _REPO / "sql" / "athena" / "ddl"


def _load(name: str) -> dict:
    return yaml.safe_load((_CFG / name).read_text(encoding="utf-8"))


def lint_vocab() -> list[str]:
    v = _load("entity_vocabulary.yaml")
    errs: list[str] = []
    node_terms = {t for terms in v.get("nodes", {}).values() if terms for t in terms}
    edge_terms = set(v.get("edges", {}).keys())

    both = node_terms & edge_terms
    if both:
        errs.append(f"terms are BOTH node and edge (arbitration violation): {sorted(both)}")

    for surface, rule in (v.get("arbitration") or {}).items():
        role, canon = rule.get("role"), rule.get("canonical")
        if role not in ("node", "edge"):
            errs.append(f"arbitration[{surface}]: role must be node|edge, got {role!r}")
        if role == "node" and canon not in node_terms:
            errs.append(f"arbitration[{surface}] → node {canon!r} not in any node list")
        if role == "edge" and canon not in edge_terms:
            errs.append(f"arbitration[{surface}] → edge {canon!r} not in edges")

    for canon, al in (v.get("aliases") or {}).items():
        if canon not in node_terms:
            errs.append(f"aliases: canonical {canon!r} is not a defined node")
        # An alias surface form must NOT itself be a node term — that's an identity collision
        # (e.g. `canola` listed as a commodity node AND an alias of `rapeseed`; or a distinct
        # sub-region listed as an alias of its parent). Such a term has two canonical identities.
        for surface in (al or []):
            if surface in node_terms and surface != canon:
                errs.append(f"aliases[{canon}]: {surface!r} is also a node term "
                            f"(alias collides with a canonical node — pick one identity)")

    for vn, rule in (v.get("verb_normalization") or {}).items():
        if rule.get("edge") not in edge_terms:
            errs.append(f"verb_normalization[{vn}] → edge {rule.get('edge')!r} not in edges")

    return errs


def check_node_silver_map() -> list[str]:
    m = _load("node_silver_map.yaml")
    errs: list[str] = []
    for metric, spec in m.get("metrics", {}).items():
        if spec.get("derived"):
            continue
        table, col = spec.get("table"), spec.get("column")
        ddl = _DDL / f"{table}.sql"
        if not ddl.exists():
            errs.append(f"metric {metric}: DDL {table}.sql not found")
            continue
        text = ddl.read_text(encoding="utf-8")
        if not re.search(rf"\b{re.escape(col)}\b", text):
            errs.append(f"metric {metric}: column {col!r} not in {table}.sql")
        aoc = spec.get("as_of_column")
        if spec.get("as_of_supported") and aoc and not re.search(rf"\b{re.escape(aoc)}\b", text):
            errs.append(f"metric {metric}: as_of_column {aoc!r} not in {table}.sql")
    return errs


def check_hierarchy() -> list[str]:
    """Commodity hierarchy integrity — every contract maps to a real node, full slug coverage,
    group/complex members real, legacy canonicals still resolve. Delegates to the resolver itself
    so config-lint and the runtime expander agree by construction."""
    from leviathan.graphrag.hierarchy import coverage_check
    return coverage_check()


def check_geography() -> list[str]:
    """Geography routing index integrity (5.8) — every curated contract/driver/region/origin id is real.
    Delegates to the resolver so lint and the runtime router agree by construction."""
    from leviathan.graphrag.geography import check_geography as _cg
    return _cg()


def check_display_names() -> list[str]:
    """Display-name registry integrity (6.1) — every convergence regime has a curated label (so no raw
    internal id can leak to the reader). Delegates to the resolver so lint and the runtime sanitizer
    agree by construction."""
    from leviathan.graphrag.display import check_display_names as _cd
    return _cd()


def check_driver_slices() -> list[str]:
    """Driver-slice darkness lint (7-P2 W2) — every causal DAG driver id resolves to an evidence slice or
    carries a waiver (hard), and no id is double-owned (hard). Topical-token drift is a separate advisory
    (driver_slice_alias_warnings, printed as WARN, never fatal). Delegates to the evidence resolver so lint
    and the runtime slice router agree by construction."""
    from leviathan.graphrag.evidence import check_driver_slices as _cds
    return _cds()


def main() -> int:
    failures = 0
    for label, errs in (("vocab", lint_vocab()), ("node_silver_map", check_node_silver_map()),
                        ("hierarchy", check_hierarchy()), ("geography", check_geography()),
                        ("display_names", check_display_names()),
                        ("driver_slices", check_driver_slices())):
        if errs:
            failures += len(errs)
            print(f"FAIL {label}:")
            for e in errs:
                print(f"  - {e}")
        else:
            print(f"PASS {label}")
    # Advisory (non-fatal): topical-token near-misses a human reviews but that never fail the build.
    from leviathan.graphrag.evidence import bare_name_warnings, driver_slice_alias_warnings
    warns = driver_slice_alias_warnings()
    if warns:
        print(f"WARN driver_slices ({len(warns)} topical near-misses — human-reviewed aliases, non-fatal):")
        for w in warns:
            print(f"  - {w}")
    # Advisory (non-fatal): a commodity node whose matcher misses its own bare head-commodity word (the C1
    # coffee-bug class) — caught by lint, not by a billed shadow rebuild. Fix = one extra_terms line.
    bare = bare_name_warnings()
    if bare:
        print(f"WARN bare_name ({len(bare)} nodes miss their own head-commodity word -- non-fatal):")
        for w in bare:
            print(f"  - {w}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
