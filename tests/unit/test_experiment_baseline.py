"""Tests for immutable MLflow baseline records."""
from __future__ import annotations

import pytest
from leviathan.audit.experiment_baseline import (
    KNOWN_LIMITATIONS,
    baseline_prefix,
    build_baseline_record,
    source_artifacts_from_tags,
)


def test_baseline_prefix_is_immutable_namespace() -> None:
    assert baseline_prefix("corn-initial") == (
        "model_artifacts/experiment_baselines/baseline_id=corn-initial"
    )
    with pytest.raises(ValueError):
        baseline_prefix("../bad")


def test_source_artifacts_from_tags() -> None:
    artifacts = source_artifacts_from_tags({
        "predictions_uri": "s3://bucket/predictions.parquet",
        "snapshot_uri": "s3://bucket/snapshot.parquet",
    })
    assert [item["filename"] for item in artifacts] == [
        "predictions.parquet",
        "training_snapshot.parquet",
    ]


def test_build_baseline_record_is_deterministic_for_same_input() -> None:
    kwargs = {
        "baseline_id": "corn-initial",
        "run_metadata": {"run": {"run_uuid": "abc"}, "tags": {}},
        "copied_artifacts": [{"name": "predictions.parquet", "sha256": "a" * 64}],
        "created_at": "2026-06-23T12:00:00+00:00",
    }
    first = build_baseline_record(**kwargs)
    second = build_baseline_record(**kwargs)
    assert first["record_sha256"] == second["record_sha256"]
    assert first["known_limitations"] == KNOWN_LIMITATIONS

