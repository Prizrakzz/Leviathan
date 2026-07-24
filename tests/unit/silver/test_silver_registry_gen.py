"""SILVER-F010: the generator is deterministic and the checked-in tree is byte-identical to a
fresh render from the R0 baseline (first-parquet inference is prohibited; the registry is derived
only from the frozen baseline artifacts). AWS-free.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
_GEN = _REPO / "scripts" / "silver" / "gen_registry_from_baseline.py"
_TABLES = _REPO / "configs" / "silver" / "tables"


@pytest.fixture(scope="module")
def gen():
    spec = importlib.util.spec_from_file_location("gen_registry_from_baseline", _GEN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_generator_is_deterministic_in_memory(gen):
    ctx = gen._build_context()
    names = sorted(p.stem for p in gen.TABLES_JSON.glob("*.json"))
    first = {n: gen._dump_yaml(gen.build_contract(n, ctx)) for n in names}
    second = {n: gen._dump_yaml(gen.build_contract(n, ctx)) for n in names}
    assert first == second


def test_checked_in_tree_matches_fresh_render(gen):
    """Regenerating produces zero diff for the checked-in contracts (the F011 idempotency gate)."""
    ctx = gen._build_context()
    names = sorted(p.stem for p in gen.TABLES_JSON.glob("*.json"))
    drift = []
    for n in names:
        rendered = gen._dump_yaml(gen.build_contract(n, ctx))
        on_disk = (_TABLES / f"{n}.yaml").read_text(encoding="utf-8")
        if rendered != on_disk:
            drift.append(n)
    assert drift == [], f"registry drift; re-run the generator: {drift}"


def test_generator_covers_exactly_the_44_baseline_tables(gen):
    baseline = {p.stem for p in gen.TABLES_JSON.glob("*.json")}
    on_disk = {p.stem for p in _TABLES.glob("*.yaml")}
    assert baseline == on_disk
    # 43 R0 tables + the T2B gold_pattern_records ledger (synthetic R0 record, plan sec 1.2).
    assert len(on_disk) == 44
    assert "gold_pattern_records" in on_disk


def test_no_yaml_lacks_a_baseline_record(gen):
    # every emitted contract cites its exact source baseline record.
    import yaml
    for p in _TABLES.glob("*.yaml"):
        c = yaml.safe_load(p.read_text(encoding="utf-8"))
        src = c["provenance"]["generated_from"]
        assert (_REPO / src).exists(), src
