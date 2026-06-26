"""Build model-ready target tables and matrices from gold feature matrices."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pandas as pd

from leviathan.features.feature_sets import selected_features_for_set
from leviathan.model_datasets.baselines import (
    TARGET_COLUMNS,
    build_trailing_anomaly_targets,
    compute_baseline_metrics,
)
from leviathan.model_datasets.targets import TargetDefinition

MATRIX_ID_COLUMNS = [
    "source_dataset_version",
    "dataset_key",
    "commodity",
    "target_key",
    "country",
    "crop_year",
    "target_value",
    "actual_value",
    "trend_prediction",
    "prior_year_value",
    "trailing_mean_prediction",
    "zero_anomaly_baseline",
    "prior_year_anomaly_baseline",
    "trailing_mean_anomaly_baseline",
    "trailing_trend_anomaly_baseline",
    "history_years",
    "is_trainable",
    "excluded_reason",
]


@dataclass(frozen=True)
class CommodityModelDataset:
    commodity: str
    target_tables: dict[str, pd.DataFrame]
    matrices: dict[tuple[str, str], pd.DataFrame]
    baseline_metrics: pd.DataFrame
    summaries: list[dict]


def _feature_union(
    matrix: pd.DataFrame,
    membership_df: pd.DataFrame,
    feature_set_ids: Iterable[str],
) -> list[str]:
    features: set[str] = set()
    for feature_set_id in feature_set_ids:
        try:
            features.update(selected_features_for_set(membership_df, feature_set_id))
        except ValueError:
            continue
    matrix_cols = set(matrix.columns)
    return sorted(
        feature
        for feature in features
        if feature in matrix_cols and not feature.startswith("label_")
    )


def _target_builder(matrix: pd.DataFrame, definition: TargetDefinition, **kwargs) -> pd.DataFrame:
    if definition.target_type == "trailing_trend_pct_anomaly":
        return build_trailing_anomaly_targets(matrix, definition, **kwargs)
    raise ValueError(f"unsupported target_type: {definition.target_type}")


def _matrix_for_target(
    matrix: pd.DataFrame,
    target_df: pd.DataFrame,
    feature_cols: list[str],
) -> pd.DataFrame:
    feature_frame = matrix[["country", "crop_year"] + feature_cols].copy()
    merged = target_df[MATRIX_ID_COLUMNS].merge(
        feature_frame,
        on=["country", "crop_year"],
        how="left",
        validate="one_to_one",
    )
    return merged[MATRIX_ID_COLUMNS + feature_cols].sort_values(
        ["country", "crop_year"]
    ).reset_index(drop=True)


def build_commodity_model_datasets(
    matrix: pd.DataFrame,
    *,
    commodity: str,
    source_dataset_version: str,
    target_definitions: list[TargetDefinition],
    feature_membership: pd.DataFrame,
) -> CommodityModelDataset:
    """Build all configured model-ready datasets for one commodity."""
    target_tables_by_dataset: dict[str, list[pd.DataFrame]] = {}
    matrices: dict[tuple[str, str], pd.DataFrame] = {}
    metrics_frames: list[pd.DataFrame] = []
    summaries: list[dict] = []

    for definition in target_definitions:
        if not definition.allows_commodity(commodity):
            continue
        if definition.label_column not in matrix.columns:
            summaries.append({
                "commodity": commodity,
                "dataset_key": definition.dataset_key,
                "target_key": definition.target_key,
                "status": "skipped_missing_label",
                "label_column": definition.label_column,
            })
            continue
        if matrix[definition.label_column].notna().sum() == 0:
            summaries.append({
                "commodity": commodity,
                "dataset_key": definition.dataset_key,
                "target_key": definition.target_key,
                "status": "skipped_empty_label",
                "label_column": definition.label_column,
            })
            continue

        target_df = _target_builder(
            matrix,
            definition,
            commodity=commodity,
            source_dataset_version=source_dataset_version,
        )
        feature_cols = _feature_union(
            matrix, feature_membership, definition.compatible_feature_sets
        )
        model_df = _matrix_for_target(matrix, target_df, feature_cols)
        baseline_metrics = compute_baseline_metrics(
            target_df,
            dataset_key=definition.dataset_key,
            commodity=commodity,
            target_key=definition.target_key,
            baseline_names=definition.baselines,
        )

        target_tables_by_dataset.setdefault(definition.dataset_key, []).append(target_df)
        matrices[(definition.dataset_key, definition.target_key)] = model_df
        metrics_frames.append(baseline_metrics)
        trainable_rows = int(target_df["is_trainable"].fillna(False).astype(bool).sum())
        summaries.append({
            "commodity": commodity,
            "dataset_key": definition.dataset_key,
            "target_key": definition.target_key,
            "status": "built",
            "row_count": int(len(target_df)),
            "trainable_row_count": trainable_rows,
            "feature_count": int(len(feature_cols)),
            "label_column": definition.label_column,
            "target_type": definition.target_type,
            "min_history_years": int(definition.min_history_years),
            "compatible_feature_sets": list(definition.compatible_feature_sets),
        })

    target_tables = {
        dataset_key: pd.concat(frames, ignore_index=True)[TARGET_COLUMNS]
        for dataset_key, frames in target_tables_by_dataset.items()
    }
    baseline_metrics = (
        pd.concat(metrics_frames, ignore_index=True)
        if metrics_frames else pd.DataFrame(
            columns=[
                "dataset_key",
                "commodity",
                "target_key",
                "baseline_name",
                "n_rows",
                "rmse",
                "mae",
                "directional_accuracy",
            ]
        )
    )
    return CommodityModelDataset(
        commodity=commodity,
        target_tables=target_tables,
        matrices=matrices,
        baseline_metrics=baseline_metrics,
        summaries=summaries,
    )
