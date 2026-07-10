"""Assemble WASDE snapshot model-ready matrices."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

import numpy as np
import pandas as pd

from leviathan.model_datasets.psd_targets import PSDMetricTargetConfig
from leviathan.model_datasets.wasde_snapshot_features import (
    DEFAULT_ATTRIBUTES,
    DYNAMIC_FEATURE_ID_COLUMNS,
    DYNAMIC_FEATURE_METADATA_COLUMNS,
    build_wasde_snapshot_dynamic_features,
    dynamic_feature_columns,
    validate_wasde_snapshot_features,
)
from leviathan.model_datasets.wasde_snapshot_mapping import (
    WasdeSnapshotMappingConfig,
    load_wasde_snapshot_mappings,
)
from leviathan.model_datasets.wasde_snapshot_static_join import (
    join_static_features_to_wasde_snapshots,
)
from leviathan.model_datasets.wasde_snapshot_targets import (
    GROUP_KEY as TARGET_GROUP_KEY,
)
from leviathan.model_datasets.wasde_snapshot_targets import (
    NATURAL_KEY as TARGET_NATURAL_KEY,
)
from leviathan.model_datasets.wasde_snapshot_targets import (
    build_wasde_snapshot_target_rows,
    validate_snapshot_target_rows,
)

SNAPSHOT_MATRIX_NATURAL_KEY = TARGET_NATURAL_KEY
SNAPSHOT_CV_COLUMNS = ["cv_group", "cv_time", "sample_weight"]
TARGET_LEAKAGE_PREFIXES = ("label_", "target_")
TARGET_LEAKAGE_COLUMNS = {
    "target_value",
    "target_anomaly_pct",
    "actual_value",
    "trend_prediction",
    "target_event_label",
}


@dataclass(frozen=True)
class WasdeSnapshotModelReadyResult:
    """Container for an assembled WASDE snapshot model-ready matrix."""

    matrix: pd.DataFrame
    targets: pd.DataFrame
    dynamic_features: pd.DataFrame
    static_manifest: pd.DataFrame
    feature_columns: tuple[str, ...]
    dynamic_feature_columns: tuple[str, ...]
    static_feature_columns: tuple[str, ...]
    summary: dict[str, object]


def _target_filter(targets: pd.DataFrame, target_keys: Iterable[str] = ()) -> pd.DataFrame:
    requested = tuple(str(target_key) for target_key in target_keys if str(target_key))
    if not requested:
        return targets
    out = targets.loc[targets["target_key"].astype(str).isin(set(requested))].copy()
    missing = sorted(set(requested) - set(out["target_key"].astype(str).unique()))
    if missing:
        raise ValueError(f"requested target keys are missing from snapshot targets: {missing}")
    return validate_snapshot_target_rows(out)


def _non_target_dynamic_metadata(dynamic_features: pd.DataFrame) -> list[str]:
    return [
        column
        for column in DYNAMIC_FEATURE_METADATA_COLUMNS
        if column in dynamic_features.columns and column not in {"wasde_commodity", "wasde_origin"}
    ]


def _selected_static_feature_columns(
    feature_matrix: pd.DataFrame,
    static_manifest: pd.DataFrame,
    dynamic_cols: Iterable[str],
) -> list[str]:
    if static_manifest.empty:
        return []
    dynamic = {str(col) for col in dynamic_cols}
    selected = static_manifest.loc[
        static_manifest["decision"].astype(str).isin({"allowed", "stage_masked"}),
        "feature",
    ].astype(str)
    return sorted(
        feature
        for feature in selected.unique()
        if feature in feature_matrix.columns
        and feature not in dynamic
        and not feature.startswith(TARGET_LEAKAGE_PREFIXES)
        and feature not in TARGET_LEAKAGE_COLUMNS
    )


def _feature_frame_for_targets(
    dynamic_features: pd.DataFrame,
    *,
    static_feature_matrix: pd.DataFrame | None,
    static_feature_sets: Mapping[str, Iterable[str]] | pd.DataFrame | None,
    feature_policy_map: Mapping[str, str] | None,
    allow_diagnostic: bool,
) -> tuple[pd.DataFrame, pd.DataFrame, list[str], list[str]]:
    dynamic_valid = validate_wasde_snapshot_features(dynamic_features)
    dynamic_cols = dynamic_feature_columns(dynamic_valid)
    static_manifest = pd.DataFrame(
        columns=[
            "feature_set_id",
            "feature",
            "decision",
            "reason",
            "allowed_snapshot_stages",
            "blocked_snapshot_stages",
            "feature_policy",
            "non_null_rate",
            "constant_rate",
        ]
    )
    feature_matrix = dynamic_valid.copy()
    static_cols: list[str] = []
    if static_feature_matrix is not None:
        feature_matrix, static_manifest = join_static_features_to_wasde_snapshots(
            dynamic_valid,
            static_feature_matrix,
            static_feature_sets,
            feature_policy_map=feature_policy_map,
            allow_diagnostic=allow_diagnostic,
            dynamic_feature_columns=dynamic_cols,
        )
        static_cols = _selected_static_feature_columns(feature_matrix, static_manifest, dynamic_cols)
    return feature_matrix, static_manifest, dynamic_cols, static_cols


def build_wasde_snapshot_model_ready_matrix_from_targets(
    snapshot_targets: pd.DataFrame,
    wasde_df: pd.DataFrame,
    *,
    static_feature_matrix: pd.DataFrame | None = None,
    static_feature_sets: Mapping[str, Iterable[str]] | pd.DataFrame | None = None,
    feature_policy_map: Mapping[str, str] | None = None,
    mapping_config: WasdeSnapshotMappingConfig | None = None,
    attributes: tuple[str, ...] = DEFAULT_ATTRIBUTES,
    min_history_years: int = 5,
    target_keys: Iterable[str] = (),
    allow_diagnostic: bool = False,
) -> WasdeSnapshotModelReadyResult:
    """Assemble a model-ready matrix from existing snapshot targets."""
    targets = _target_filter(validate_snapshot_target_rows(snapshot_targets), target_keys)
    if targets.empty:
        empty = pd.DataFrame(columns=SNAPSHOT_MATRIX_NATURAL_KEY)
        return WasdeSnapshotModelReadyResult(
            matrix=empty,
            targets=targets,
            dynamic_features=pd.DataFrame(),
            static_manifest=pd.DataFrame(),
            feature_columns=(),
            dynamic_feature_columns=(),
            static_feature_columns=(),
            summary={"status": "empty", "row_count": 0},
        )

    cfg = mapping_config or load_wasde_snapshot_mappings()
    dynamic_features = build_wasde_snapshot_dynamic_features(
        wasde_df,
        targets,
        mapping_config=cfg,
        attributes=attributes,
        min_history_years=min_history_years,
    )
    feature_matrix, static_manifest, dynamic_cols, static_cols = _feature_frame_for_targets(
        dynamic_features,
        static_feature_matrix=static_feature_matrix,
        static_feature_sets=static_feature_sets,
        feature_policy_map=feature_policy_map,
        allow_diagnostic=allow_diagnostic,
    )

    feature_cols = tuple(sorted(set(dynamic_cols) | set(static_cols)))
    metadata_cols = _non_target_dynamic_metadata(feature_matrix)
    join_cols = list(DYNAMIC_FEATURE_ID_COLUMNS)
    feature_payload_cols = join_cols + metadata_cols + list(feature_cols)
    feature_payload = feature_matrix[feature_payload_cols].copy()
    matrix = targets.merge(
        feature_payload,
        on=join_cols,
        how="left",
        validate="many_to_one",
    )
    matrix = validate_wasde_snapshot_model_ready_matrix(
        matrix,
        feature_columns=feature_cols,
        expected_row_count=len(targets),
    )
    summary = summarize_wasde_snapshot_model_ready_matrix(
        matrix,
        feature_columns=feature_cols,
        static_manifest=static_manifest,
    )
    return WasdeSnapshotModelReadyResult(
        matrix=matrix,
        targets=targets,
        dynamic_features=dynamic_features,
        static_manifest=static_manifest,
        feature_columns=feature_cols,
        dynamic_feature_columns=tuple(sorted(dynamic_cols)),
        static_feature_columns=tuple(sorted(static_cols)),
        summary=summary,
    )


def build_wasde_snapshot_model_ready_matrix(
    psd_df: pd.DataFrame,
    wasde_df: pd.DataFrame,
    *,
    source_dataset_version: str,
    dataset_key: str = "corn_wasde_snapshot_solo",
    static_feature_matrix: pd.DataFrame | None = None,
    static_feature_sets: Mapping[str, Iterable[str]] | pd.DataFrame | None = None,
    feature_policy_map: Mapping[str, str] | None = None,
    mapping_config: WasdeSnapshotMappingConfig | None = None,
    psd_config: PSDMetricTargetConfig | None = None,
    attributes: tuple[str, ...] = DEFAULT_ATTRIBUTES,
    min_history_years: int = 5,
    target_keys: Iterable[str] = (),
    target_event_threshold_type: str = "fixed_10pct",
    allow_diagnostic: bool = False,
) -> WasdeSnapshotModelReadyResult:
    """Build targets, dynamic WASDE features, static features, and final matrix."""
    cfg = mapping_config or load_wasde_snapshot_mappings()
    targets = build_wasde_snapshot_target_rows(
        psd_df,
        wasde_df,
        source_dataset_version=source_dataset_version,
        dataset_key=dataset_key,
        mapping_config=cfg,
        psd_config=psd_config,
        target_event_threshold_type=target_event_threshold_type,
    )
    return build_wasde_snapshot_model_ready_matrix_from_targets(
        targets,
        wasde_df,
        static_feature_matrix=static_feature_matrix,
        static_feature_sets=static_feature_sets,
        feature_policy_map=feature_policy_map,
        mapping_config=cfg,
        attributes=attributes,
        min_history_years=min_history_years,
        target_keys=target_keys,
        allow_diagnostic=allow_diagnostic,
    )


def validate_wasde_snapshot_model_ready_matrix(
    matrix: pd.DataFrame,
    *,
    feature_columns: Iterable[str],
    expected_row_count: int | None = None,
) -> pd.DataFrame:
    """Validate row grain, leakage controls, and CV metadata for a snapshot matrix."""
    if matrix.empty:
        return matrix.copy()
    missing = set(SNAPSHOT_MATRIX_NATURAL_KEY) - set(matrix.columns)
    if missing:
        raise ValueError(f"WASDE snapshot model-ready matrix missing key columns: {sorted(missing)}")
    missing_cv = set(SNAPSHOT_CV_COLUMNS) - set(matrix.columns)
    if missing_cv:
        raise ValueError(f"WASDE snapshot model-ready matrix missing CV columns: {sorted(missing_cv)}")
    out = matrix.copy()
    out["as_of_date"] = pd.to_datetime(out["as_of_date"], errors="coerce")
    duplicate_mask = out.duplicated(SNAPSHOT_MATRIX_NATURAL_KEY, keep=False)
    if duplicate_mask.any():
        examples = (
            out.loc[duplicate_mask, SNAPSHOT_MATRIX_NATURAL_KEY]
            .drop_duplicates()
            .sort_values(SNAPSHOT_MATRIX_NATURAL_KEY)
            .head(5)
            .to_dict("records")
        )
        raise ValueError(f"duplicate WASDE snapshot model-ready rows: {examples}")
    if expected_row_count is not None and len(out) != int(expected_row_count):
        raise ValueError(
            "WASDE snapshot model-ready row count changed: "
            f"expected={expected_row_count} actual={len(out)}"
        )
    if "source_release_date_max" in out.columns:
        out["source_release_date_max"] = pd.to_datetime(
            out["source_release_date_max"], errors="coerce"
        )
        future = out.loc[
            out["source_release_date_max"].notna()
            & (out["source_release_date_max"] > out["as_of_date"])
        ]
        if not future.empty:
            raise ValueError(
                "WASDE snapshot model-ready matrix contains future release data: "
                f"{future[SNAPSHOT_MATRIX_NATURAL_KEY + ['source_release_date_max']].head(5).to_dict('records')}"
            )

    features = tuple(str(feature) for feature in feature_columns)
    missing_features = sorted(set(features) - set(out.columns))
    if missing_features:
        raise ValueError(f"declared feature columns are missing from matrix: {missing_features[:10]}")
    leaky = sorted(
        feature
        for feature in features
        if feature.startswith(TARGET_LEAKAGE_PREFIXES) or feature in TARGET_LEAKAGE_COLUMNS
    )
    if leaky:
        raise ValueError(f"leaky feature columns selected for snapshot matrix: {leaky}")

    if out["cv_group"].astype(str).str.contains(r"\d{4}-\d{2}-\d{2}", regex=True).any():
        raise ValueError("cv_group must not include monthly snapshot dates")
    grouped_weight = out.groupby(TARGET_GROUP_KEY, dropna=False)["sample_weight"].sum()
    if not grouped_weight.empty:
        bad_weights = grouped_weight.loc[~np.isclose(grouped_weight.astype(float), 1.0, atol=1e-6)]
        if not bad_weights.empty:
            raise ValueError(
                "sample weights must sum to one for each annual outcome group: "
                f"{bad_weights.head(5).to_dict()}"
            )
    return out.sort_values(SNAPSHOT_MATRIX_NATURAL_KEY).reset_index(drop=True)


def summarize_wasde_snapshot_model_ready_matrix(
    matrix: pd.DataFrame,
    *,
    feature_columns: Iterable[str],
    static_manifest: pd.DataFrame | None = None,
) -> dict[str, object]:
    """Return compact diagnostics for a WASDE snapshot model-ready matrix."""
    features = tuple(str(feature) for feature in feature_columns)
    trainable = (
        int(matrix["is_trainable"].fillna(False).astype(bool).sum())
        if "is_trainable" in matrix.columns else 0
    )
    non_null_rates = {
        feature: float(matrix[feature].notna().mean())
        for feature in features
        if feature in matrix.columns and len(matrix) > 0
    }
    manifest_counts = {}
    if static_manifest is not None and not static_manifest.empty:
        manifest_counts = {
            str(key): int(value)
            for key, value in static_manifest["decision"].value_counts().sort_index().items()
        }
    return {
        "status": "built" if len(matrix) else "empty",
        "row_count": int(len(matrix)),
        "trainable_row_count": trainable,
        "target_key_count": int(matrix["target_key"].nunique()) if "target_key" in matrix.columns else 0,
        "snapshot_count": int(matrix["as_of_date"].nunique()) if "as_of_date" in matrix.columns else 0,
        "annual_outcome_group_count": int(
            matrix[TARGET_GROUP_KEY].drop_duplicates().shape[0]
        ) if set(TARGET_GROUP_KEY).issubset(matrix.columns) else 0,
        "feature_count": int(len(features)),
        "feature_non_null_min": min(non_null_rates.values()) if non_null_rates else np.nan,
        "feature_non_null_median": float(np.median(list(non_null_rates.values()))) if non_null_rates else np.nan,
        "static_manifest_decision_counts": manifest_counts,
    }

