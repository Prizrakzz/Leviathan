"""Load Phase 8 model-ready datasets for MLflow training.

The model-ready layer already materializes target values, leakage-safe
baselines, and target-specific matrices.  This module keeps the trainer honest:
it selects features only through the governed feature-set membership artifact
and excludes every target/baseline identity column from the model input.
"""
from __future__ import annotations

from dataclasses import dataclass
import io
import json
import math
import re
from typing import Any

import numpy as np
import pandas as pd

from leviathan.features.feature_sets import selected_features_for_set
from leviathan.model_datasets.baselines import BASELINE_COLUMNS
from leviathan.model_datasets.builder import MATRIX_ID_COLUMNS
from leviathan.model_datasets.psd_model_ready import (
    PSD_MATRIX_ID_COLUMNS,
    PSD_SNAPSHOT_COLUMNS,
)
from leviathan.model_datasets.version_status import (
    ModelDatasetVersionStatus,
    get_model_dataset_version_status,
)
from leviathan.storage.paths import (
    gold_feature_set_version_key,
    gold_model_ready_baseline_metrics_key,
    gold_model_ready_manifest_key,
    gold_model_ready_matrix_key,
)

MODEL_READY_TARGET_COL = "target_value"

MODEL_READY_EXCLUDED_FEATURE_COLUMNS = set(MATRIX_ID_COLUMNS) | set(PSD_MATRIX_ID_COLUMNS) | {
    "target_title",
    "target_unit",
} | set(PSD_SNAPSHOT_COLUMNS)
MODEL_READY_ROW_ID_COLUMNS = ["country", "crop_year", "snapshot_stage", "as_of_date"]


@dataclass(frozen=True)
class ModelReadyTrainingDataset:
    """Resolved model-ready data and provenance for a single training job."""

    matrix: pd.DataFrame
    train_df: pd.DataFrame
    feature_cols: list[str]
    target_col: str
    feature_set_id: str
    feature_set_meta: dict[str, str]
    manifest: dict[str, Any]
    manifest_uri: str
    matrix_uri: str
    baseline_metrics: pd.DataFrame
    baseline_metrics_uri: str
    source_dataset_version: str
    model_dataset_status: ModelDatasetVersionStatus


def _read_s3_bytes(s3, bucket: str, key: str) -> bytes:
    return s3.get_object(Bucket=bucket, Key=key)["Body"].read()


def _read_s3_parquet(s3, bucket: str, key: str) -> pd.DataFrame:
    return pd.read_parquet(io.BytesIO(_read_s3_bytes(s3, bucket, key)))


def _read_s3_json(s3, bucket: str, key: str) -> dict[str, Any]:
    return json.loads(_read_s3_bytes(s3, bucket, key).decode("utf-8"))


def _safe_str(value: object) -> str:
    return "" if value is None else str(value)


def sanitize_artifact_name(value: str) -> str:
    """Return a conservative S3/object-name fragment."""
    return re.sub(r"[^A-Za-z0-9_.=-]+", "_", value).strip("_") or "dataset"


def infer_source_dataset_version(
    manifest: dict[str, Any] | None,
    matrix: pd.DataFrame | None = None,
    explicit: str | None = None,
) -> str:
    """Resolve the source gold dataset version for feature-set lookup."""
    if explicit:
        return explicit
    if manifest:
        source = manifest.get("source_dataset_version")
        if source:
            return str(source)
    if matrix is not None and "source_dataset_version" in matrix.columns and not matrix.empty:
        values = matrix["source_dataset_version"].dropna().astype(str).unique()
        if len(values) == 1:
            return str(values[0])
        if len(values) > 1:
            raise ValueError(
                f"model-ready matrix has multiple source_dataset_version values: {sorted(values)}"
            )
    raise ValueError("source dataset version is required or must be present in manifest/matrix")


def select_model_ready_features(
    matrix: pd.DataFrame,
    membership: pd.DataFrame,
    feature_set_id: str,
) -> tuple[list[str], dict[str, str]]:
    """Select governed feature columns present in a model-ready matrix."""
    selected = selected_features_for_set(membership, feature_set_id)
    feature_cols = [
        feature
        for feature in selected
        if feature in matrix.columns
        and feature not in MODEL_READY_EXCLUDED_FEATURE_COLUMNS
        and not feature.startswith("label_")
    ]
    rows = membership.loc[membership["feature_set_id"] == feature_set_id]
    meta = {"feature_set_id": feature_set_id}
    if not rows.empty:
        for source_col, tag_col in (
            ("feature_set_version", "feature_set_version"),
            ("feature_set_sha", "feature_set_catalog_sha"),
            ("dataset_version", "feature_set_dataset_version"),
        ):
            if source_col in rows.columns:
                meta[tag_col] = str(rows[source_col].iloc[0])
    return sorted(feature_cols), meta


def _row_identity_columns(df: pd.DataFrame) -> list[str]:
    return [col for col in MODEL_READY_ROW_ID_COLUMNS if col in df.columns]


def training_frame_from_model_ready_matrix(
    matrix: pd.DataFrame,
    feature_cols: list[str],
    *,
    target_col: str = MODEL_READY_TARGET_COL,
) -> pd.DataFrame:
    """Return trainable rows with identity, features, and target only."""
    required = {"country", "crop_year", "is_trainable", target_col}
    missing = required - set(matrix.columns)
    if missing:
        raise ValueError(f"model-ready matrix missing required columns: {sorted(missing)}")
    if not feature_cols:
        raise ValueError("model-ready feature set resolved to zero usable columns")

    trainable = matrix.loc[matrix["is_trainable"].fillna(False).astype(bool)].copy()
    trainable = trainable.loc[trainable[target_col].notna()].copy()
    id_cols = _row_identity_columns(trainable)
    cols = id_cols + feature_cols + [target_col]
    return trainable[cols].sort_values(id_cols).reset_index(drop=True)


def load_model_ready_training_dataset(
    s3,
    *,
    bucket: str,
    model_dataset_version: str,
    dataset_key: str,
    commodity: str,
    target_key: str,
    feature_set_id: str,
    source_dataset_version: str | None = None,
) -> ModelReadyTrainingDataset:
    """Load a model-ready matrix, feature set, manifest, and baseline metrics."""
    matrix_key = gold_model_ready_matrix_key(
        model_dataset_version, dataset_key, commodity, target_key
    )
    manifest_key = gold_model_ready_manifest_key(model_dataset_version)
    baseline_key = gold_model_ready_baseline_metrics_key(model_dataset_version)

    matrix = _read_s3_parquet(s3, bucket, matrix_key)
    try:
        manifest = _read_s3_json(s3, bucket, manifest_key)
    except Exception:  # noqa: BLE001 - older local/smoke versions may lack it
        manifest = {}
    source_version = infer_source_dataset_version(
        manifest, matrix, explicit=source_dataset_version
    )
    version_status = get_model_dataset_version_status(model_dataset_version)
    membership = _read_s3_parquet(s3, bucket, gold_feature_set_version_key(source_version))
    feature_cols, feature_set_meta = select_model_ready_features(
        matrix, membership, feature_set_id
    )
    train_df = training_frame_from_model_ready_matrix(matrix, feature_cols)

    try:
        baseline_metrics = _read_s3_parquet(s3, bucket, baseline_key)
    except Exception:  # noqa: BLE001 - non-fatal for ad-hoc smoke versions
        baseline_metrics = pd.DataFrame()

    return ModelReadyTrainingDataset(
        matrix=matrix,
        train_df=train_df,
        feature_cols=feature_cols,
        target_col=MODEL_READY_TARGET_COL,
        feature_set_id=feature_set_id,
        feature_set_meta=feature_set_meta,
        manifest=manifest,
        manifest_uri=f"s3://{bucket}/{manifest_key}",
        matrix_uri=f"s3://{bucket}/{matrix_key}",
        baseline_metrics=baseline_metrics,
        baseline_metrics_uri=f"s3://{bucket}/{baseline_key}",
        source_dataset_version=source_version,
        model_dataset_status=version_status,
    )


def _metric_values(actual: pd.Series, pred: pd.Series) -> dict[str, float]:
    actual_f = pd.to_numeric(actual, errors="coerce")
    pred_f = pd.to_numeric(pred, errors="coerce")
    valid = actual_f.notna() & pred_f.notna()
    if int(valid.sum()) == 0:
        return {
            "n_rows": 0.0,
            "rmse": math.nan,
            "mae": math.nan,
            "sign_accuracy": math.nan,
        }
    residual = actual_f[valid] - pred_f[valid]
    return {
        "n_rows": float(int(valid.sum())),
        "rmse": float(np.sqrt((residual ** 2).mean())),
        "mae": float(residual.abs().mean()),
        "sign_accuracy": float((np.sign(actual_f[valid]) == np.sign(pred_f[valid])).mean()),
    }


def model_ready_baseline_metrics_for_predictions(
    predictions: pd.DataFrame,
    matrix: pd.DataFrame,
    *,
    baseline_names: tuple[str, ...] | None = None,
) -> pd.DataFrame:
    """Score materialized baselines on the exact CV rows predicted by a model."""
    if predictions.empty:
        return pd.DataFrame(
            columns=["baseline_name", "n_rows", "rmse", "mae", "sign_accuracy"]
        )
    names = baseline_names or tuple(BASELINE_COLUMNS)
    join_cols = [
        col for col in ("country", "crop_year", "snapshot_stage", "as_of_date")
        if col in predictions.columns and col in matrix.columns
    ]
    cols = join_cols + [
        col for name, col in BASELINE_COLUMNS.items()
        if name in names and col in matrix.columns
    ]
    joined = predictions.merge(
        matrix[cols],
        on=join_cols,
        how="left",
        validate="one_to_one",
    )
    rows: list[dict[str, float | str]] = []
    for baseline_name in names:
        column = BASELINE_COLUMNS.get(baseline_name)
        if column is None or column not in joined.columns:
            continue
        rows.append({
            "baseline_name": baseline_name,
            **_metric_values(joined["y_actual"], joined[column]),
        })
    return pd.DataFrame(rows)


def model_ready_metric_log_values(
    predictions: pd.DataFrame,
    baseline_metrics: pd.DataFrame,
) -> dict[str, float]:
    """Build flat MLflow metric names for model-ready baseline comparison."""
    metrics: dict[str, float] = {}
    if not predictions.empty:
        model_scores = _metric_values(predictions["y_actual"], predictions["y_pred"])
        for key, value in model_scores.items():
            if key != "n_rows" and np.isfinite(value):
                metrics[f"target_space_model_{key}"] = float(value)

    if baseline_metrics.empty:
        return metrics
    for row in baseline_metrics.itertuples(index=False):
        name = _safe_str(getattr(row, "baseline_name", "baseline"))
        for metric in ("rmse", "mae", "sign_accuracy"):
            value = getattr(row, metric, math.nan)
            if np.isfinite(value):
                metrics[f"baseline_{name}_{metric}"] = float(value)
    finite_rmse = pd.to_numeric(baseline_metrics.get("rmse"), errors="coerce").dropna()
    if not finite_rmse.empty and "target_space_model_rmse" in metrics:
        best = float(finite_rmse.min())
        metrics["best_baseline_rmse"] = best
        metrics["model_vs_best_baseline_rmse_delta"] = (
            metrics["target_space_model_rmse"] - best
        )
    finite_mae = pd.to_numeric(baseline_metrics.get("mae"), errors="coerce").dropna()
    if not finite_mae.empty and "target_space_model_mae" in metrics:
        best = float(finite_mae.min())
        metrics["best_baseline_mae"] = best
        metrics["model_vs_best_baseline_mae_delta"] = (
            metrics["target_space_model_mae"] - best
        )
    return metrics


def attach_model_ready_baselines_to_predictions(
    predictions: pd.DataFrame,
    matrix: pd.DataFrame,
) -> pd.DataFrame:
    """Return predictions enriched with actual target-space baseline columns."""
    baseline_cols = [
        col for col in BASELINE_COLUMNS.values()
        if col in matrix.columns
    ]
    if not baseline_cols or predictions.empty:
        return predictions.copy()
    join_cols = [
        col for col in ("country", "crop_year", "snapshot_stage", "as_of_date")
        if col in predictions.columns and col in matrix.columns
    ]
    return predictions.merge(
        matrix[join_cols + baseline_cols],
        on=join_cols,
        how="left",
        validate="one_to_one",
    )
