"""Unit tests for leviathan.features.registry."""
from __future__ import annotations

import pytest
from leviathan.common.constants import ALL_COMMODITIES
from leviathan.features.computations import COMPUTATIONS
from leviathan.features.registry import RegistryError, load_registry


def test_real_registry_loads_and_resolves() -> None:
    registry = load_registry()
    assert registry.specs, "registry must not be empty"
    for spec in registry.specs:
        assert spec.family in COMPUTATIONS
        assert spec.commodities, f"{spec.family}: empty commodity set"
        assert all(c in ALL_COMMODITIES for c in spec.commodities)
    # exactly one label family in v1
    labels = [s for s in registry.specs if s.is_label]
    assert [s.family for s in labels] == ["faostat_labels"]
    assert len(registry.params_hash) == 64


def test_calendar_sentinel_resolves_to_calendar_commodities() -> None:
    registry = load_registry()
    precip = next(s for s in registry.specs if s.family == "stage_precip_z")
    assert "arabica_coffee" in precip.commodities
    # frozen_orange_juice has no crop calendar entry
    assert "frozen_orange_juice" not in precip.commodities


def test_sources_for_aggregates_across_specs() -> None:
    registry = load_registry()
    sources = registry.sources_for("arabica_coffee")
    assert "weather:chirps" in sources
    assert "weather:nasa_power" in sources
    assert "production:faostat" in sources
    assert "psd" in sources


def _write_minimal_configs(tmp_path, features_yaml: str) -> None:
    (tmp_path / "feature_params.yaml").write_text("baselines: {}\n", encoding="utf-8")
    (tmp_path / "features.yaml").write_text(features_yaml, encoding="utf-8")


def test_unknown_family_rejected(tmp_path) -> None:
    _write_minimal_configs(tmp_path, (
        "- family: not_a_real_family\n"
        "  sources: ['psd']\n"
        "  visibility: prior_history\n"
        "  commodities: all\n"
    ))
    with pytest.raises(RegistryError, match="no computation registered"):
        load_registry(tmp_path, calendar_commodities=set())


def test_bad_visibility_rejected(tmp_path) -> None:
    _write_minimal_configs(tmp_path, (
        "- family: psd_available\n"
        "  sources: ['psd']\n"
        "  visibility: latest\n"
        "  commodities: all\n"
    ))
    with pytest.raises(RegistryError, match="visibility"):
        load_registry(tmp_path, calendar_commodities=set())


def test_unknown_commodity_rejected(tmp_path) -> None:
    _write_minimal_configs(tmp_path, (
        "- family: psd_available\n"
        "  sources: ['psd']\n"
        "  visibility: prior_marketing_year\n"
        "  commodities: ['wagyu_beef']\n"
    ))
    with pytest.raises(RegistryError, match="unknown commodities"):
        load_registry(tmp_path, calendar_commodities=set())


def test_duplicate_family_rejected(tmp_path) -> None:
    spec = (
        "- family: psd_available\n"
        "  sources: ['psd']\n"
        "  visibility: prior_marketing_year\n"
        "  commodities: all\n"
    )
    _write_minimal_configs(tmp_path, spec + spec)
    with pytest.raises(RegistryError, match="duplicate family"):
        load_registry(tmp_path, calendar_commodities=set())
