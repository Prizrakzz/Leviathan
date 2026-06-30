from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from leviathan.model_datasets.wasde_snapshot_mapping import (
    allowed_snapshot_context,
    load_wasde_snapshot_mappings,
    mapping_sha,
    resolve_wasde_origin,
    surface_contracts,
)

ROOT = Path(__file__).resolve().parents[2]
MAPPING_CONFIG = ROOT / "configs" / "ml" / "wasde_snapshot_mappings.yaml"


def _raw_config() -> dict:
    return yaml.safe_load(MAPPING_CONFIG.read_text(encoding="utf-8"))


def _write_config(tmp_path: Path, raw: dict) -> Path:
    path = tmp_path / "wasde_snapshot_mappings.yaml"
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return path


def test_wasde_snapshot_mapping_config_loads_with_stable_sha() -> None:
    cfg = load_wasde_snapshot_mappings()

    assert cfg.config_sha
    assert cfg.config_sha == mapping_sha(cfg)
    assert cfg.config_sha == mapping_sha(cfg.raw)
    assert set(cfg.surfaces) == {
        "corn_wasde_snapshot_solo",
        "corn_wasde_snapshot_with_substitutes",
        "grains_wasde_snapshot_segment",
    }
    assert "production" in cfg.core_attributes
    assert "aggregate_region" in cfg.excluded_region_classes


def test_corn_solo_target_origins_are_phase0_clean_origins() -> None:
    cfg = load_wasde_snapshot_mappings()
    scope = allowed_snapshot_context(cfg, "corn_wasde_snapshot_solo")

    assert scope["primary_contract"] == "corn_cbot"
    assert scope["primary_wasde_commodity"] == "corn"
    assert scope["target_origins"] == [
        "united_states",
        "brazil",
        "argentina",
        "ukraine",
    ]
    assert scope["context_commodities"] == []


def test_region_resolution_allows_aliases_and_rejects_out_of_scope_regions() -> None:
    cfg = load_wasde_snapshot_mappings()

    assert resolve_wasde_origin(
        cfg, "corn_wasde_snapshot_solo", "corn", "US"
    ) == "united_states"
    assert resolve_wasde_origin(
        cfg, "corn_wasde_snapshot_solo", "corn", "Brazil"
    ) == "brazil"
    assert resolve_wasde_origin(
        cfg, "corn_wasde_snapshot_solo", "corn", "World"
    ) is None
    assert resolve_wasde_origin(
        cfg, "corn_wasde_snapshot_solo", "corn", "123456"
    ) is None
    assert resolve_wasde_origin(
        cfg, "corn_wasde_snapshot_solo", "corn", "China"
    ) is None


def test_substitute_surface_keeps_corn_as_primary_target() -> None:
    cfg = load_wasde_snapshot_mappings()
    scope = allowed_snapshot_context(cfg, "corn_wasde_snapshot_with_substitutes")

    assert scope["primary_contract"] == "corn_cbot"
    assert scope["target_origins"] == [
        "united_states",
        "brazil",
        "argentina",
        "ukraine",
    ]
    context = {item["wasde_commodity"]: item for item in scope["context_commodities"]}
    assert set(context) == {"wheat", "soybeans", "soybean_meal", "soybean_oil"}
    assert context["wheat"]["context_role"] == "feed_substitute"
    assert "soft_red_winter_wheat_cbot" in context["wheat"]["contracts"]
    assert resolve_wasde_origin(
        cfg, "corn_wasde_snapshot_with_substitutes", "soybeans", "Brazil"
    ) == "brazil"


def test_surface_contracts_exclude_deferred_members_by_default() -> None:
    cfg = load_wasde_snapshot_mappings()

    active_contracts = surface_contracts(cfg, "grains_wasde_snapshot_segment")
    all_contracts = surface_contracts(
        cfg, "grains_wasde_snapshot_segment", include_deferred=True
    )

    assert "corn_cbot" in active_contracts
    assert "rough_rice_cbot" in active_contracts
    assert "soft_red_winter_wheat_cbot" in active_contracts
    assert "hard_red_winter_wheat_kcbt" not in active_contracts
    assert "hard_red_spring_wheat_mgex" not in active_contracts
    assert "hard_red_winter_wheat_kcbt" in all_contracts
    assert "hard_red_spring_wheat_mgex" in all_contracts


def test_active_segment_members_are_compatible_with_psd_target_origins() -> None:
    cfg = load_wasde_snapshot_mappings()
    segment = cfg.surfaces["grains_wasde_snapshot_segment"]

    members = {member.contract_key: member for member in segment.segment_members}
    assert members["corn_cbot"].is_active
    assert members["rough_rice_cbot"].is_active
    assert members["soft_red_winter_wheat_cbot"].is_active
    assert not members["hard_red_winter_wheat_kcbt"].is_active
    assert not members["hard_red_spring_wheat_mgex"].is_active


def test_alias_collision_raises(tmp_path: Path) -> None:
    raw = _raw_config()
    origins = raw["surfaces"][0]["target_origins"]
    origins[1]["wasde_region_aliases"].append("us")
    bad_path = _write_config(tmp_path, raw)

    with pytest.raises(ValueError, match="region alias 'us' maps to both"):
        load_wasde_snapshot_mappings(bad_path, validate_psd=False)


def test_aggregate_target_origin_raises(tmp_path: Path) -> None:
    raw = _raw_config()
    raw["surfaces"][0]["target_origins"][0]["wasde_region_aliases"] = ["world"]
    bad_path = _write_config(tmp_path, raw)

    with pytest.raises(ValueError, match="aggregate region is not allowed"):
        load_wasde_snapshot_mappings(bad_path, validate_psd=False)


def test_target_origin_missing_from_psd_mapping_raises(tmp_path: Path) -> None:
    raw = _raw_config()
    raw["surfaces"][0]["target_origins"].append({
        "origin_key": "china",
        "wasde_region_aliases": ["china"],
        "role": "target_origin",
        "mapping_confidence": "high",
    })
    bad_path = _write_config(tmp_path, raw)

    with pytest.raises(ValueError, match="target origins not present in PSD mapping"):
        load_wasde_snapshot_mappings(bad_path)
