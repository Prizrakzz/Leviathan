"""Helpers for freezing an existing MLflow experiment run."""
from __future__ import annotations

from typing import Any

from leviathan.ops.ml_platform import canonical_sha256, parse_s3_uri

KNOWN_LIMITATIONS = [
    "Production-level target rather than an official-revision or anomaly target.",
    "No fitted model artifact was logged.",
    "The feature-spine Git SHA is unknown.",
    "The run failed one or more hard governance gaps.",
    "This record is an engineering baseline, not a candidate model.",
]


def baseline_prefix(baseline_id: str) -> str:
    if not baseline_id or "/" in baseline_id:
        raise ValueError("baseline_id must be a non-empty path-safe identifier")
    return f"model_artifacts/experiment_baselines/baseline_id={baseline_id}"


def source_artifacts_from_tags(tags: dict[str, str]) -> list[dict[str, str]]:
    """Return copy instructions for S3 artifacts referenced by the run."""
    mappings = {
        "predictions_uri": "predictions.parquet",
        "snapshot_uri": "training_snapshot.parquet",
    }
    artifacts: list[dict[str, str]] = []
    for tag, filename in mappings.items():
        uri = tags.get(tag)
        if not uri:
            continue
        bucket, key = parse_s3_uri(uri)
        artifacts.append({
            "tag": tag,
            "source_uri": uri,
            "source_bucket": bucket,
            "source_key": key,
            "filename": filename,
        })
    return artifacts


def build_baseline_record(
    *,
    baseline_id: str,
    run_metadata: dict[str, Any],
    copied_artifacts: list[dict[str, Any]],
    created_at: str,
) -> dict[str, Any]:
    core = {
        "baseline_id": baseline_id,
        "created_at": created_at,
        "run_metadata": run_metadata,
        "artifacts": copied_artifacts,
        "known_limitations": KNOWN_LIMITATIONS,
    }
    return {
        "schema_version": 1,
        **core,
        "record_sha256": canonical_sha256(core),
    }
