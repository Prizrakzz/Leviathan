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
