from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
import pytest

from jobs.batch.feature_set_task import build_and_write
from leviathan.features.feature_sets import (
    build_feature_set_membership,
    load_feature_set_config,
    selected_features_for_set,
)
from leviathan.storage.paths import (
    gold_feature_catalog_version_key,
    gold_feature_group_map_version_key,
    gold_feature_set_summary_key,
    gold_feature_set_version_key,
    gold_feature_spine_manifest_key,
)


def _catalog() -> pd.DataFrame:
    rows = [
        ("label_production_quantity", "labels", "target_label", "fundamental_physical", "supervised_target", "production:faostat", "annual", "universal", "", True, 10, 2, 1.0),
        ("pink_sheet_energy_z", "input_costs", "economic_driver", "certified_economic_driver", "energy_fertilizer_cost", "pink_sheet", "monthly", "universal", "grains,oilseeds", False, 10, 2, 1.0),
        ("brl_fx_pct_90d", "fx_macro", "economic_driver", "certified_economic_driver", "producer_export_incentive", "fred_fx", "daily", "universal", "grains,oilseeds", False, 8, 2, 0.8),
        ("crush_margin_z", "processing_economics", "economic_driver", "certified_economic_driver", "oilseed_processing_margin", "futures_prices", "daily", "group", "oilseeds", False, 6, 1, 0.6),
        ("cot_mm_net_pct_oi_z", "market_positioning", "diagnostic_market_context", "diagnostic_only", "positioning_context", "cot", "weekly", "universal", "grains", False, 9, 2, 0.9),
        ("nass_ge_pct_z", "crop_condition", "inseason_crop_condition", "fundamental_physical", "good_excellent_condition", "nass_crop_progress", "weekly", "commodity", "us_row_crops", False, 5, 1, 0.5),
        ("wasde_latest_revision", "official_revisions", "official_revision", "fundamental_physical", "official_estimate_revision", "wasde", "monthly", "commodity", "grains", False, 5, 1, 0.5),
        ("ams_percent_tenderable", "cotton_quality", "quality_tenderability", "fundamental_physical", "cotton_quality_tenderable_supply", "ams_cotton_quality", "annual", "commodity", "cotton", False, 5, 1, 0.5),
        ("fgis_export_pace_yoy", "export_pace", "origin_physical_flow", "fundamental_physical", "export_inspection_pace", "fgis", "weekly", "commodity", "us_row_crops", False, 5, 1, 0.5),
        ("psd_available", "balance_sheet", "origin_balance_sheet", "fundamental_physical", "stock_use_balance", "psd", "annual", "universal", "grains", False, 10, 2, 1.0),
        ("faostat_available", "faostat_production", "origin_production_history", "fundamental_physical", "production_trend_baseline", "production:faostat", "annual", "universal", "grains", False, 10, 2, 1.0),
        ("gdd_z_us_midwest", "growing_degree_days", "origin_weather", "fundamental_physical", "crop_development_speed", "weather:nasa_power", "daily", "commodity", "grains", False, 4, 1, 0.4),
    ]
    return pd.DataFrame(rows, columns=[
        "feature",
        "feature_family",
        "semantic_scope",
        "policy",
        "mechanism",
        "sources",
        "source_cadence",
        "empirical_scope",
        "groups",
        "is_label",
        "row_count",
        "commodity_count",
        "non_null_rate",
    ]).assign(dataset_version="v1")


def _group_map() -> pd.DataFrame:
    rows = []
    for row in _catalog().itertuples(index=False):
        for group in str(row.groups).split(","):
            if group:
                rows.append({
                    "dataset_version": "v1",
                    "feature": row.feature,
                    "group": group,
                    "commodity_count": row.commodity_count,
                    "row_count": row.row_count,
                    "non_null_rate": row.non_null_rate,
                    "semantic_scope": row.semantic_scope,
                    "policy": row.policy,
                })
    return pd.DataFrame(rows)


def test_feature_sets_exclude_labels_and_core_diagnostics() -> None:
    specs, config_sha = load_feature_set_config()
    membership, summary = build_feature_set_membership(
        _catalog(), _group_map(), dataset_version="v1", specs=specs, config_sha=config_sha
    )

    assert summary["feature_set_count"] == 13
    assert "label_production_quantity" not in set(membership["feature"])
    core = membership.loc[membership["feature_set_id"] != "diagnostic_market_context"]
    assert "diagnostic_only" not in set(core["policy"])
    diagnostic = selected_features_for_set(membership, "diagnostic_market_context")
    assert diagnostic == ["cot_mm_net_pct_oi_z"]


def test_economic_driver_sets_are_certified_only() -> None:
    specs, config_sha = load_feature_set_config()
    membership, _ = build_feature_set_membership(
        _catalog(), _group_map(), dataset_version="v1", specs=specs, config_sha=config_sha
    )

    economic_sets = membership.loc[
        membership["feature_set_id"].isin([
            "processing_economics",
            "planting_incentives",
            "trade_competitiveness",
        ])
    ]
    assert set(economic_sets["policy"]) == {"certified_economic_driver"}
    assert selected_features_for_set(membership, "processing_economics") == ["crush_margin_z"]


def test_quality_tenderability_selects_cotton_quality_only() -> None:
    specs, config_sha = load_feature_set_config()
    membership, _ = build_feature_set_membership(
        _catalog(), _group_map(), dataset_version="v1", specs=specs, config_sha=config_sha
    )

    assert selected_features_for_set(membership, "quality_tenderability") == [
        "ams_percent_tenderable"
    ]


def test_zero_feature_set_fails(tmp_path: Path) -> None:
    config = tmp_path / "sets.yaml"
    config.write_text(
        """
schema_version: 1
feature_sets:
  - id: impossible
    version: 1
    allowed_feature_families: [does_not_exist]
""",
        encoding="utf-8",
    )
    specs, config_sha = load_feature_set_config(config)
    with pytest.raises(ValueError, match="zero features"):
        build_feature_set_membership(
            _catalog(), _group_map(), dataset_version="v1", specs=specs, config_sha=config_sha
        )


def test_feature_set_task_writes_outputs_and_patches_manifest(tmp_path: Path) -> None:
    version = "v1"
    catalog_key = gold_feature_catalog_version_key(version)
    group_key = gold_feature_group_map_version_key(version)
    manifest_key = gold_feature_spine_manifest_key(version)

    for key, df in [(catalog_key, _catalog()), (group_key, _group_map())]:
        path = tmp_path / key
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path, index=False, engine="pyarrow", compression="snappy")

    manifest_path = tmp_path / manifest_key
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps({"dataset_version": version, "outputs": {}}))

    args = argparse.Namespace(
        dataset_version=version,
        bucket=None,
        aws_region=None,
        local_root=str(tmp_path),
        feature_sets_config=None,
        force_overwrite=False,
        update_manifest=True,
        dry_run=False,
    )

    summary = build_and_write(args)

    assert summary["feature_set_count"] == 13
    assert (tmp_path / gold_feature_set_version_key(version)).exists()
    assert (tmp_path / gold_feature_set_summary_key(version)).exists()
    manifest = json.loads(manifest_path.read_text())
    assert manifest["feature_sets"]["summary"]["feature_set_count"] == 13
    assert manifest["outputs"]["feature_sets_key"] == gold_feature_set_version_key(version)
    assert manifest["outputs"]["feature_sets_json_key"] == gold_feature_set_summary_key(version)
