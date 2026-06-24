from __future__ import annotations

import argparse

import pytest

from jobs.batch.feature_spine_v2_task import _assert_immutable_prefixes_absent
from jobs.batch.feature_spine_v2_task import _should_skip_commodity_for_waiver
from leviathan.storage.paths import (
    gold_v2_dataset_manifest_key,
    gold_v2_feature_matrix_key,
    gold_v2_preflight_report_key,
    gold_v2_feature_spine_key,
)


def test_gold_v2_path_helpers_are_non_overlapping() -> None:
    version = "20240601T000000Z_deadbeef"
    spine = gold_v2_feature_spine_key(version, "corn_cbot")
    matrix = gold_v2_feature_matrix_key(version, "corn_cbot")
    manifest = gold_v2_dataset_manifest_key(version)
    preflight = gold_v2_preflight_report_key(version)
    assert spine == (
        "gold_v2/feature_spine/dataset_version=20240601T000000Z_deadbeef/"
        "commodity=corn_cbot/part-000.parquet"
    )
    assert matrix.startswith("gold_v2/feature_matrix/")
    assert manifest.startswith("gold_v2/dataset_manifests/")
    assert preflight.startswith("gold_v2/preflight_reports/")
    assert not spine.startswith("gold/")
    assert not matrix.startswith("gold/")


def test_immutable_dataset_version_refuses_existing_local_prefix(tmp_path) -> None:
    version = "20240601T000000Z_deadbeef"
    existing = tmp_path / "gold_v2" / "feature_spine" / f"dataset_version={version}" / "commodity=corn_cbot"
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


def test_raw_sugar_is_excluded_when_unica_is_waived() -> None:
    assert _should_skip_commodity_for_waiver(
        "raw_sugar",
        [{"source_key": "unica", "certification_status": "waived"}],
    )
    assert not _should_skip_commodity_for_waiver(
        "corn_cbot",
        [{"source_key": "unica", "certification_status": "waived"}],
    )
