from __future__ import annotations

import argparse

import pandas as pd
import pytest

from jobs.batch.feature_catalog_v2_task import (
    _assert_immutable_prefixes_absent,
    _read_spine,
    _validate_expected_commodities,
)
from leviathan.storage.paths import (
    gold_v2_feature_catalog_key,
    gold_v2_feature_entity_map_key,
    gold_v2_feature_group_map_key,
)


def test_gold_v2_catalog_path_helpers_are_non_overlapping() -> None:
    version = "20240601T000000Z_deadbeef"
    assert gold_v2_feature_catalog_key(version) == (
        "gold_v2/feature_catalog/dataset_version=20240601T000000Z_deadbeef/part-000.parquet"
    )
    assert gold_v2_feature_entity_map_key(version).startswith("gold_v2/feature_entity_map/")
    assert gold_v2_feature_group_map_key(version).startswith("gold_v2/feature_group_map/")


def test_catalog_task_refuses_existing_local_prefix(tmp_path) -> None:
    version = "20240601T000000Z_deadbeef"
    existing = tmp_path / "gold_v2" / "feature_catalog" / f"dataset_version={version}"
    existing.mkdir(parents=True)
    (existing / "part-000.parquet").write_bytes(b"x")
    args = argparse.Namespace(
        local_root=str(tmp_path),
        dataset_version=version,
        bucket=None,
        aws_region=None,
    )
    with pytest.raises(SystemExit, match="immutable"):
        _assert_immutable_prefixes_absent(args)


def test_catalog_task_reads_hive_partitioned_local_spine(tmp_path) -> None:
    version = "20240601T000000Z_deadbeef"
    path = (
        tmp_path
        / "gold_v2"
        / "feature_spine"
        / f"dataset_version={version}"
        / "commodity=corn_cbot"
    )
    path.mkdir(parents=True)
    pd.DataFrame({
        "entity_type": ["contract_origin"],
        "entity_id": ["corn_cbot:united_states"],
        "physical_commodity": ["corn"],
        "contract_slug": ["corn_cbot"],
        "origin": ["united_states"],
        "crop_year": [2024],
        "as_of_date": [pd.Timestamp("2024-12-31")],
        "snapshot_stage": ["crop_year_end"],
        "feature": ["nass_ge_pct_latest"],
        "value": [62.0],
        "feature_available_at": [pd.Timestamp("2024-07-01")],
        "source": ["nass_crop_progress"],
        "source_vintage": ["v1"],
        "is_label": [False],
    }).to_parquet(path / "part-000.parquet", index=False)
    args = argparse.Namespace(local_root=str(tmp_path), dataset_version=version)
    df = _read_spine(args)
    assert df["dataset_version"].iloc[0] == version
    assert df["commodity"].iloc[0] == "corn_cbot"


def test_catalog_task_blocks_missing_expected_commodity() -> None:
    df = pd.DataFrame({"commodity": ["corn_cbot"]})
    with pytest.raises(SystemExit, match="missing expected commodities"):
        _validate_expected_commodities(
            df,
            ["corn_cbot", "soybean_oil_cbot"],
            allow_partial=False,
        )
    assert _validate_expected_commodities(
        df,
        ["corn_cbot", "soybean_oil_cbot"],
        allow_partial=True,
    ) == ["soybean_oil_cbot"]
