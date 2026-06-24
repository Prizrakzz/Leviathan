from __future__ import annotations

from pathlib import Path

from leviathan.certification.source_certification import (
    SourceContract,
    feature_source_coverage,
    load_source_contracts,
)


def test_feature_source_coverage_detects_missing_contract(tmp_path: Path) -> None:
    features = tmp_path / "features.yaml"
    features.write_text(
        """
- family: one
  sources: ["source_a", "source_b"]
- family: two
  sources: ["source_a"]
""",
        encoding="utf-8",
    )
    contracts = (
        SourceContract(
            source_key="source_a",
            title="Source A",
            glue_table="silver_a",
            s3_prefix="s3://bucket/a/",
            status="core",
            grain="id",
        ),
    )

    coverage = feature_source_coverage(features, contracts)

    assert coverage["feature_sources"] == ["source_a", "source_b"]
    assert coverage["missing_contract_sources"] == ["source_b"]
    assert coverage["families_by_missing_source"] == {"source_b": ["one"]}


def test_checked_in_contracts_cover_checked_in_feature_registry() -> None:
    contracts = load_source_contracts("configs/datasets/source_contracts.yaml")

    coverage = feature_source_coverage("configs/features/features.yaml", contracts)

    assert coverage["missing_contract_sources"] == []
    assert "production:faostat" in coverage["contract_sources"]
    assert "weather:chirps" in coverage["contract_sources"]
    assert "nass_crop_progress" in coverage["contract_sources"]


def test_checked_in_contracts_do_not_include_graphrag_sources() -> None:
    contracts = load_source_contracts("configs/datasets/source_contracts.yaml")

    source_keys = {contract.source_key for contract in contracts}

    assert all(not source_key.startswith("graphrag") for source_key in source_keys)
