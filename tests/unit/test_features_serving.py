"""Unit tests for the sanctioned inference-feature loader (gold mode)."""
from __future__ import annotations

import pandas as pd
import pytest

from leviathan.features.serving import load_inference_features


def _make_gold(tmp_path) -> str:
    d = tmp_path / "gold" / "feature_matrix" / "commodity=test_x"
    d.mkdir(parents=True)
    pd.DataFrame({
        "country": ["brazil", "brazil", "brazil"],
        "crop_year": [2023, 2024, 2025],
        "gdd_z_region": [0.1, 0.2, 0.3],
        "label_production_quantity": [100.0, 110.0, None],
    }).to_parquet(d / "part-0.parquet", index=False)
    return tmp_path.as_posix()


def _make_gold_v2(tmp_path) -> str:
    d = (
        tmp_path / "gold_v2" / "feature_matrix"
        / "dataset_version=v1" / "commodity=test_x"
    )
    d.mkdir(parents=True)
    pd.DataFrame({
        "entity_type": ["contract_origin", "contract_origin"],
        "entity_id": ["test_x:origin", "test_x:origin"],
        "physical_commodity": ["test", "test"],
        "contract_slug": ["test_x", "test_x"],
        "origin": ["origin", "origin"],
        "crop_year": [2024, 2025],
        "as_of_date": [pd.Timestamp("2024-07-01"), pd.Timestamp("2025-07-01")],
        "snapshot_stage": ["custom_as_of", "custom_as_of"],
        "nass_ge_pct_latest": [62.0, 70.0],
    }).to_parquet(d / "part-0.parquet", index=False)
    return tmp_path.as_posix()


def test_gold_mode_defaults_to_latest_year(tmp_path) -> None:
    out = load_inference_features("test_x", root=_make_gold(tmp_path), prefer="gold")
    assert out["crop_year"].tolist() == [2025]
    assert "gdd_z_region" in out.columns


def test_gold_mode_specific_year(tmp_path) -> None:
    out = load_inference_features("test_x", 2024, root=_make_gold(tmp_path), prefer="gold")
    assert out["crop_year"].tolist() == [2024]
    assert out["gdd_z_region"].iloc[0] == pytest.approx(0.2)


def test_requires_bucket_or_root() -> None:
    with pytest.raises(ValueError):
        load_inference_features("test_x")


def test_invalid_prefer_rejected(tmp_path) -> None:
    with pytest.raises(ValueError):
        load_inference_features("test_x", root=_make_gold(tmp_path), prefer="bogus")


def test_gold_v2_requires_version_and_as_of(tmp_path) -> None:
    with pytest.raises(ValueError, match="dataset_version"):
        load_inference_features(
            "test_x",
            root=_make_gold_v2(tmp_path),
            prefer="gold_v2",
            as_of_date="2024-07-01",
        )


def test_gold_v2_loads_exact_snapshot(tmp_path) -> None:
    out = load_inference_features(
        "test_x",
        2024,
        root=_make_gold_v2(tmp_path),
        prefer="gold_v2",
        dataset_version="v1",
        as_of_date="2024-07-01",
        snapshot_stage="custom_as_of",
    )
    assert out["crop_year"].tolist() == [2024]
    assert out["nass_ge_pct_latest"].iloc[0] == pytest.approx(62.0)
    assert out["dataset_version"].iloc[0] == "v1"
