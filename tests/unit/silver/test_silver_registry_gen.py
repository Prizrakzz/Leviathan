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


def test_generator_covers_exactly_the_45_baseline_tables(gen):
    baseline = {p.stem for p in gen.TABLES_JSON.glob("*.json")}
    on_disk = {p.stem for p in _TABLES.glob("*.yaml")}
    assert baseline == on_disk
    # 43 R0 tables + two SYNTHETIC R0 records: the T2B gold_pattern_records ledger (T2B plan sec 1.2)
    # and silver_futures_eod (PRICE_AND_PLAYBOOKS W1.0) -- both authored from a ratified schema so the
    # generator can emit their contracts byte-stably before any AWS object exists.
    assert len(on_disk) == 45
    assert "gold_pattern_records" in on_disk
    assert "silver_futures_eod" in on_disk


class TestNullableOverrides:
    """PRICE_AND_PLAYBOOKS W1.0: the one column fact ``build_contract`` cannot derive.

    The default ``nullable = cn not in natural_key`` is a heuristic, and silver_futures_eod breaks it
    in BOTH directions at once: ``contract_month`` is a natural-key member that is legitimately NULL
    (the two CEPEA cash references), while instrument_kind / settle_kind / unit / source are non-null
    by contract yet sit outside the key. The flag is load-bearing -- ``pa_schema_from_contract`` turns
    it into ``pa.field(..., nullable=...)`` -- so a wrong value either fails the pyarrow encode on
    legal data or silently admits an illegal null."""

    def test_the_override_beats_the_natural_key_default(self, gen):
        ctx = gen._build_context()
        c = gen.build_contract("silver_futures_eod", ctx)
        by = {col["name"]: col for col in c["physical_columns"]}
        assert "contract_month" in c["natural_key"]
        assert by["contract_month"]["nullable"] is True      # key member, still nullable
        for cn in ("instrument_kind", "settle_kind", "unit", "source"):
            assert by[cn]["nullable"] is False, cn           # non-key, still non-null

    def test_an_unknown_override_column_fails_closed(self, gen):
        # a typo would otherwise be a silent no-op -- exactly the failure mode a nullability knob
        # must not have.
        ctx = gen._build_context()
        overrides = gen.CURATION_OVERRIDES["silver_futures_eod"]["nullable_overrides"]
        overrides["typo_col"] = True
        try:
            with pytest.raises(KeyError, match="not a declared physical column"):
                gen.build_contract("silver_futures_eod", ctx)
        finally:
            overrides.pop("typo_col")


def test_no_yaml_lacks_a_baseline_record(gen):
    # every emitted contract cites its exact source baseline record.
    import yaml
    for p in _TABLES.glob("*.yaml"):
        c = yaml.safe_load(p.read_text(encoding="utf-8"))
        src = c["provenance"]["generated_from"]
        assert (_REPO / src).exists(), src
