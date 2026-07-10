from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from leviathan.model_datasets.psd_targets import load_psd_metric_targets

ROOT = Path(__file__).resolve().parents[2]
COMMODITY_DIR = ROOT / "configs" / "commodities"
PSD_CONFIG = ROOT / "configs" / "ml" / "psd_metric_targets.yaml"

PSD_SILVER_COLUMNS = {
    "leviathan_slug",
    "country",
    "market_year",
    "release_date",
    "production_mt",
    "imports_mt",
    "exports_mt",
    "ending_stocks_mt",
    "consumption_mt",
    "su_ratio",
    "area_harvested_1000ha",
    "yield_mt_ha",
}


def _commodity_slugs() -> set[str]:
    slugs: set[str] = set()
    for path in COMMODITY_DIR.glob("*.yaml"):
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        slugs.add(str(raw["commodity"]))
    return slugs


def test_psd_target_config_loads_with_sha_and_metric_families() -> None:
    cfg = load_psd_metric_targets()

    assert cfg.config_sha
    assert set(cfg.metrics) == {
        "psd_production_anomaly_pct",
        "psd_ending_stocks_anomaly_pct",
        "psd_stock_to_use_anomaly_pct",
        "psd_exports_anomaly_pct",
        "psd_imports_anomaly_pct",
        "psd_domestic_use_anomaly_pct",
    }
    assert cfg.metrics["psd_production_anomaly_pct"].target_family == (
        "psd_production_anomaly"
    )
    assert cfg.metrics["psd_stock_to_use_anomaly_pct"].psd_attribute == "su_ratio"
    assert cfg.metrics["psd_stock_to_use_anomaly_pct"].stress_event_direction == (
        "lower_is_stress"
    )
    assert cfg.metrics["psd_exports_anomaly_pct"].stress_event_direction == (
        "higher_is_stress"
    )


def test_psd_target_mapping_covers_every_commodity_config() -> None:
    cfg = load_psd_metric_targets()

    assert set(cfg.contract_mappings) == _commodity_slugs()
    assert len(cfg.contract_mappings) == 31


def test_psd_target_metrics_reference_existing_silver_columns() -> None:
    cfg = load_psd_metric_targets()

    for metric in cfg.metrics.values():
        assert metric.psd_attribute in PSD_SILVER_COLUMNS


def test_cocoa_and_fcoj_are_explicitly_non_psd_targets() -> None:
    cfg = load_psd_metric_targets()

    cocoa = cfg.contract_mappings["cocoa"]
    fcoj = cfg.contract_mappings["frozen_orange_juice"]

    assert cocoa.target_status == "unmapped"
    assert cocoa.allowed_as_target is False
    assert cocoa.allowed_targets == ()
    assert cfg.raw["contract_mappings"][4]["non_psd_target_source"] == "icco_cocoa"

    assert fcoj.target_status == "unmapped"
    assert fcoj.allowed_as_feature is False
    assert fcoj.allowed_targets == ()
    fcoj_raw = next(
        item for item in cfg.raw["contract_mappings"]
        if item["contract_key"] == "frozen_orange_juice"
    )
    assert fcoj_raw["non_psd_target_source"] == "nass_citrus"


def test_wheat_class_contracts_are_aggregate_proxies() -> None:
    cfg = load_psd_metric_targets()

    for contract in {
        "soft_red_winter_wheat_cbot",
        "hard_red_winter_wheat_kcbt",
        "hard_red_spring_wheat_mgex",
        "french_wheat_matif",
    }:
        mapping = cfg.contract_mappings[contract]
        assert mapping.target_status == "aggregate_proxy"
        assert mapping.mapping_confidence in {"low", "medium"}
        assert "all-wheat" in mapping.note or "aggregate wheat" in mapping.note


def test_proxy_and_aggregate_proxy_mappings_are_never_silent() -> None:
    cfg = load_psd_metric_targets()

    for mapping in cfg.contract_mappings.values():
        if mapping.target_status in {"proxy", "aggregate_proxy"}:
            assert mapping.note
            assert mapping.mapping_confidence in {"low", "medium"}
            assert mapping.allowed_targets
            assert mapping.target_origins


def test_legacy_faostat_targets_are_declared_as_baselines() -> None:
    cfg = load_psd_metric_targets()
    legacy = cfg.raw["legacy_target_family"]

    assert legacy["dataset_key"] == "annual_physical_anomaly"
    assert legacy["status"] == "legacy_baseline"
    assert legacy["target_source"] == "faostat"
    assert set(legacy["target_keys"]) == {
        "production_anomaly_pct",
        "yield_anomaly_pct",
        "area_harvested_anomaly_pct",
    }


def test_invalid_proxy_without_note_fails_validation(tmp_path: Path) -> None:
    raw = yaml.safe_load(PSD_CONFIG.read_text(encoding="utf-8"))
    first_proxy = next(
        item for item in raw["contract_mappings"]
        if item["target_status"] in {"proxy", "aggregate_proxy"}
    )
    first_proxy["note"] = ""
    bad_path = tmp_path / "bad_psd_metric_targets.yaml"
    bad_path.write_text(yaml.safe_dump(raw), encoding="utf-8")

    with pytest.raises(ValueError, match="require note"):
        load_psd_metric_targets(bad_path)


def test_unmapped_contracts_cannot_define_trainable_targets(tmp_path: Path) -> None:
    raw = yaml.safe_load(PSD_CONFIG.read_text(encoding="utf-8"))
    cocoa = next(item for item in raw["contract_mappings"] if item["contract_key"] == "cocoa")
    cocoa["allowed_as_target"] = True
    cocoa["allowed_targets"] = ["psd_production_anomaly_pct"]
    bad_path = tmp_path / "bad_psd_metric_targets.yaml"
    bad_path.write_text(yaml.safe_dump(raw), encoding="utf-8")

    with pytest.raises(ValueError, match="unmapped rows cannot be trainable"):
        load_psd_metric_targets(bad_path)


def test_invalid_stress_event_direction_fails_validation(tmp_path: Path) -> None:
    raw = yaml.safe_load(PSD_CONFIG.read_text(encoding="utf-8"))
    raw["target_metrics"][0]["stress_event_direction"] = "sideways"
    bad_path = tmp_path / "bad_psd_metric_targets.yaml"
    bad_path.write_text(yaml.safe_dump(raw), encoding="utf-8")

    with pytest.raises(ValueError, match="stress_event_direction"):
        load_psd_metric_targets(bad_path)
