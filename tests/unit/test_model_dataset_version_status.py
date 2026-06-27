from __future__ import annotations

import pytest

from leviathan.model_datasets.version_status import (
    get_model_dataset_version_status,
    load_model_dataset_version_registry,
)


PSD_SMOKE_VERSION = "20260627T121215Z_phase5_psd_smoke"
PSD_SNAPSHOT_VERSION = "20260627T190257Z_1a042698_phase9_psd_snapshot_corn"
FAOSTAT_FULL_VERSION = "20260626T104732Z_a2576e84_phase8_model_ready"


def test_registry_loads_known_model_dataset_versions() -> None:
    registry = load_model_dataset_version_registry()

    assert PSD_SMOKE_VERSION in registry.versions
    assert PSD_SNAPSHOT_VERSION in registry.versions
    assert FAOSTAT_FULL_VERSION in registry.versions
    assert registry.versions[PSD_SMOKE_VERSION].status == "active"
    assert registry.versions[PSD_SNAPSHOT_VERSION].status == "active"
    assert registry.versions[FAOSTAT_FULL_VERSION].status == "legacy"


def test_select_default_returns_psd_active_dataset_only() -> None:
    registry = load_model_dataset_version_registry()

    selected = registry.select_default(
        target_source="psd",
        dataset_key="psd_snd_anomaly",
    )

    assert selected.dataset_version == PSD_SMOKE_VERSION
    assert selected.default_discovery_allowed


def test_select_default_returns_psd_snapshot_dataset() -> None:
    registry = load_model_dataset_version_registry()

    selected = registry.select_default(
        target_source="psd",
        dataset_key="psd_snd_anomaly_snapshot",
    )

    assert selected.dataset_version == PSD_SNAPSHOT_VERSION
    assert selected.default_discovery_allowed


def test_legacy_faostat_dataset_is_not_default_discoverable() -> None:
    registry = load_model_dataset_version_registry()
    legacy = registry.get(FAOSTAT_FULL_VERSION)

    assert legacy.is_legacy_like
    assert not legacy.default_discovery_allowed
    with pytest.raises(ValueError, match="no active model-ready dataset version"):
        registry.select_default(
            target_source="faostat",
            dataset_key="annual_physical_anomaly",
        )


def test_unknown_model_dataset_version_is_explicitly_unknown() -> None:
    status = get_model_dataset_version_status("missing_version_for_local_test")

    assert status.status == "unknown"
    assert status.is_legacy_like
    assert not status.default_discovery_allowed
    assert "not listed" in status.notes
