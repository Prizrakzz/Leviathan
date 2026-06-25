from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
import pytest

from jobs.batch.feature_catalog_task import build_and_write
from leviathan.features.semantic_catalog import (
    build_feature_entity_map,
    build_feature_group_map,
    build_semantic_catalog,
    load_feature_groups,
    load_taxonomy,
)
from leviathan.storage.paths import (
    gold_feature_catalog_version_key,
    gold_feature_entity_map_version_key,
    gold_feature_group_map_version_key,
    gold_feature_spine_manifest_key,
    gold_feature_spine_version_key,
)


def _spine_rows() -> pd.DataFrame:
    return pd.DataFrame([
        {
            "commodity": "corn_cbot",
            "country": "united_states",
            "crop_year": 2023,
            "feature": "nass_ge_pct_z",
            "value": 1.0,
            "is_label": False,
            "event_time": "2023-12-31",
        },
        {
            "commodity": "corn_cbot",
            "country": "united_states",
            "crop_year": 2024,
            "feature": "nass_ge_pct_z",
            "value": 2.0,
            "is_label": False,
            "event_time": "2024-12-31",
        },
        {
            "commodity": "soybeans_cbot",
            "country": "united_states",
            "crop_year": 2024,
            "feature": "pink_sheet_energy_z",
            "value": 0.5,
            "is_label": False,
            "event_time": "2024-12-31",
        },
        {
            "commodity": "soybeans_cbot",
            "country": "united_states",
            "crop_year": 2024,
            "feature": "cot_mm_net_pct_oi_z",
            "value": 0.2,
            "is_label": False,
            "event_time": "2024-12-31",
        },
        {
            "commodity": "soybeans_cbot",
            "country": "united_states",
            "crop_year": 2024,
            "feature": "label_production_t",
            "value": 100.0,
            "is_label": True,
            "event_time": "2024-12-31",
        },
    ])


def test_taxonomy_classifies_policy_sensitive_features() -> None:
    taxonomy = load_taxonomy()

    assert taxonomy.classify("label_production_t").semantic_scope == "target_label"
    assert taxonomy.classify("cot_mm_net_pct_oi_z").policy == "diagnostic_only"
    assert taxonomy.classify("pink_sheet_energy_z").policy == "certified_economic_driver"
    assert taxonomy.classify("brl_fx_pct_90d").policy == "certified_economic_driver"
    assert taxonomy.classify("nass_ge_pct_z").feature_family == "crop_condition"


def test_build_semantic_catalog_and_maps() -> None:
    spine = _spine_rows()
    taxonomy = load_taxonomy()
    groups = load_feature_groups()

    catalog = build_semantic_catalog(
        spine,
        dataset_version="v1",
        taxonomy=taxonomy,
        feature_groups=groups,
        expected_commodities={"corn_cbot", "soybeans_cbot"},
    )
    entity_map = build_feature_entity_map(spine, dataset_version="v1")
    group_map = build_feature_group_map(
        spine,
        catalog,
        dataset_version="v1",
        feature_groups=groups,
    )

    assert set(catalog["feature"]) == set(spine["feature"])
    assert catalog.loc[
        catalog["feature"] == "pink_sheet_energy_z", "policy"
    ].iloc[0] == "certified_economic_driver"
    assert catalog.loc[
        catalog["feature"] == "cot_mm_net_pct_oi_z", "policy"
    ].iloc[0] == "diagnostic_only"
    assert bool(catalog.loc[catalog["feature"] == "label_production_t", "is_label"].iloc[0])
    assert not entity_map.empty
    assert not group_map.empty
    assert "us_row_crops" in set(group_map["group"])


def test_unknown_high_volume_feature_fails() -> None:
    spine = _spine_rows()
    spine.loc[len(spine)] = {
        "commodity": "corn_cbot",
        "country": "united_states",
        "crop_year": 2024,
        "feature": "mystery_feature",
        "value": 1.0,
        "is_label": False,
        "event_time": "2024-12-31",
    }

    with pytest.raises(ValueError, match="missing taxonomy rules"):
        build_semantic_catalog(
            spine,
            dataset_version="v1",
            taxonomy=load_taxonomy(),
            feature_groups=load_feature_groups(),
            expected_commodities={"corn_cbot", "soybeans_cbot"},
        )


def test_feature_catalog_task_writes_outputs_and_patches_manifest(tmp_path: Path) -> None:
    version = "v1"
    for commodity in ["corn_cbot", "soybeans_cbot"]:
        df = _spine_rows().loc[lambda x: x["commodity"] == commodity].drop(columns=["commodity"])
        key = gold_feature_spine_version_key(version, commodity)
        path = tmp_path / key
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path, index=False, engine="pyarrow", compression="snappy")

    manifest_key = gold_feature_spine_manifest_key(version)
    manifest_path = tmp_path / manifest_key
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps({"dataset_version": version, "outputs": {}}))

    args = argparse.Namespace(
        dataset_version=version,
        bucket=None,
        aws_region=None,
        local_root=str(tmp_path),
        expected_commodities="corn_cbot,soybeans_cbot",
        taxonomy_config=None,
        groups_config=None,
        unknown_row_threshold=0,
        force_overwrite=False,
        update_manifest=True,
        dry_run=False,
    )

    summary = build_and_write(args)

    assert summary["catalog_rows"] == 4
    assert (tmp_path / gold_feature_catalog_version_key(version)).exists()
    assert (tmp_path / gold_feature_entity_map_version_key(version)).exists()
    assert (tmp_path / gold_feature_group_map_version_key(version)).exists()

    manifest = json.loads(manifest_path.read_text())
    assert manifest["semantic_catalog"]["summary"]["catalog_rows"] == 4
    assert manifest["outputs"]["feature_entity_map_key"] == gold_feature_entity_map_version_key(version)
