"""Build model-ready matrices from PSD target panels."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pandas as pd

from leviathan.features.calendar import CropCalendar
from leviathan.features.computations.psd_vintages import (
    build_psd_vintage_snapshot_feature_matrix,
)
from leviathan.features.feature_sets import selected_features_for_set
from leviathan.model_datasets.baselines import compute_baseline_metrics
from leviathan.model_datasets.builder import CommodityModelDataset
from leviathan.model_datasets.psd_target_builder import PSD_TARGET_COLUMNS
from leviathan.model_datasets.snapshot_stages import (
    SnapshotStageConfig,
    resolve_snapshot_dates,
)

PSD_DATASET_KEY = "psd_snd_anomaly"
PSD_SNAPSHOT_DATASET_KEY = "psd_snd_anomaly_snapshot"
PSD_BASELINES = ("zero_anomaly", "prior_year", "trailing_mean", "trailing_linear_trend")
DEFAULT_PSD_FEATURE_SETS = (
    "preseason_physical",
    "inseason_weather",
    "crop_condition",
    "official_revision",
    "physical_flow",
    "balance_sheet",
    "planting_incentives",
    "trade_competitiveness",
    "tail_risk",
    "data_quality",
)

PSD_MATRIX_ID_COLUMNS = [
    "source_dataset_version",
    "dataset_key",
    "commodity",
    "contract_key",
    "target_key",
    "target_source",
    "target_family",
    "target_attribute",
    "target_source_table",
    "target_unit",
    "target_value_unit",
    "target_status",
    "mapping_confidence",
    "psd_source_slug",
    "psd_commodity",
    "psd_country",
    "origin_key",
    "origin_role",
    "country",
    "crop_year",
    "target_market_year",
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
    "target_release_context",
    "target_observation_release_date",
    "target_source_vintage",
    "psd_mapping_sha",
]

PSD_TARGET_NATURAL_KEY = ["commodity", "country", "crop_year", "target_key"]
PSD_SNAPSHOT_COLUMNS = ["snapshot_stage", "as_of_date", "snapshot_policy"]
PSD_SNAPSHOT_MATRIX_ID_COLUMNS = PSD_MATRIX_ID_COLUMNS + PSD_SNAPSHOT_COLUMNS
PSD_SNAPSHOT_TARGET_COLUMNS = PSD_TARGET_COLUMNS + PSD_SNAPSHOT_COLUMNS
PSD_MONTHLY_VINTAGE_FEATURE_SET_ID = "psd_monthly_vintage_features"
PSD_PRESEASON_PLUS_VINTAGE_FEATURE_SET_ID = "preseason_physical_plus_psd_vintage"
DEFAULT_PSD_SNAPSHOT_FEATURE_SETS = (PSD_MONTHLY_VINTAGE_FEATURE_SET_ID,)
PSD_SNAPSHOT_DYNAMIC_ID_COLUMNS = {"country", "crop_year", "snapshot_stage", "as_of_date"}
PSD_SNAPSHOT_STATIC_FEATURE_SETS = {
    "preseason_physical",
    PSD_PRESEASON_PLUS_VINTAGE_FEATURE_SET_ID,
}


@dataclass(frozen=True)
class PSDModelReadyBuildConfig:
    """Configuration for PSD model-ready matrix materialization."""

    compatible_feature_sets: tuple[str, ...] = DEFAULT_PSD_FEATURE_SETS
    baselines: tuple[str, ...] = PSD_BASELINES


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


def psd_vintage_feature_columns(matrix: pd.DataFrame) -> list[str]:
    """Return dynamic PSD monthly-vintage feature columns from a snapshot matrix."""
    return sorted(
        str(col)
        for col in matrix.columns
        if str(col).startswith("psd_")
        and str(col) not in PSD_SNAPSHOT_DYNAMIC_ID_COLUMNS
    )


def _snapshot_static_feature_set_ids(feature_set_ids: Iterable[str]) -> tuple[str, ...]:
    ids = set(str(feature_set_id) for feature_set_id in feature_set_ids)
    out: set[str] = set()
    if PSD_PRESEASON_PLUS_VINTAGE_FEATURE_SET_ID in ids:
        out.add("preseason_physical")
    out.update(feature_set_id for feature_set_id in ids if feature_set_id in PSD_SNAPSHOT_STATIC_FEATURE_SETS)
    return tuple(sorted(out))


def _snapshot_feature_columns(
    dynamic_features: pd.DataFrame,
    feature_membership: pd.DataFrame,
    feature_set_ids: Iterable[str],
    *,
    static_feature_matrix: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, list[str], dict[str, list[str]]]:
    """Resolve dynamic and optional static feature columns for snapshot matrices."""
    requested = tuple(str(feature_set_id) for feature_set_id in feature_set_ids)
    dynamic_cols = psd_vintage_feature_columns(dynamic_features)
    static_cols: list[str] = []
    feature_matrix = dynamic_features.copy()

    static_set_ids = _snapshot_static_feature_set_ids(requested)
    if static_feature_matrix is not None and static_set_ids:
        _validate_feature_matrix(static_feature_matrix, "snapshot_static_features")
        static_cols = _feature_union(
            static_feature_matrix, feature_membership, static_set_ids
        )
        if static_cols:
            static_frame = static_feature_matrix[
                ["country", "crop_year"] + static_cols
            ].copy()
            static_frame = static_frame.drop_duplicates(["country", "crop_year"])
            feature_matrix = feature_matrix.merge(
                static_frame,
                on=["country", "crop_year"],
                how="left",
                validate="many_to_one",
            )

    selected_by_set: dict[str, list[str]] = {}
    for feature_set_id in requested:
        if feature_set_id == PSD_MONTHLY_VINTAGE_FEATURE_SET_ID:
            selected_by_set[feature_set_id] = dynamic_cols
        elif feature_set_id == PSD_PRESEASON_PLUS_VINTAGE_FEATURE_SET_ID:
            selected_by_set[feature_set_id] = sorted(set(dynamic_cols) | set(static_cols))
        else:
            selected_by_set[feature_set_id] = _feature_union(
                feature_matrix, feature_membership, (feature_set_id,)
            )

    feature_cols = sorted({
        feature for features in selected_by_set.values() for feature in features
    })
    return feature_matrix, feature_cols, selected_by_set


def _validate_feature_matrix(matrix: pd.DataFrame, commodity: str) -> None:
    required = {"country", "crop_year"}
    missing = required - set(matrix.columns)
    if missing:
        raise ValueError(f"{commodity}: feature matrix missing columns {sorted(missing)}")
    duplicates = matrix.duplicated(["country", "crop_year"], keep=False)
    if duplicates.any():
        keys = (
            matrix.loc[duplicates, ["country", "crop_year"]]
            .drop_duplicates()
            .sort_values(["country", "crop_year"])
            .to_dict("records")
        )
        raise ValueError(f"{commodity}: duplicate feature matrix keys {keys[:5]}")


def _validate_psd_targets(targets: pd.DataFrame, commodity: str) -> None:
    required = set(PSD_MATRIX_ID_COLUMNS) | {"target_title"}
    missing = required - set(targets.columns)
    if missing:
        raise ValueError(f"{commodity}: PSD target panel missing columns {sorted(missing)}")
    duplicates = targets.duplicated(PSD_TARGET_NATURAL_KEY, keep=False)
    if duplicates.any():
        keys = (
            targets.loc[duplicates, PSD_TARGET_NATURAL_KEY]
            .drop_duplicates()
            .sort_values(PSD_TARGET_NATURAL_KEY)
            .to_dict("records")
        )
        raise ValueError(f"{commodity}: duplicate PSD target keys {keys[:5]}")


def _mark_missing_features(model_df: pd.DataFrame) -> pd.DataFrame:
    out = model_df.copy()
    if "_features_available" not in out.columns:
        return out
    missing = out["_features_available"].ne(True)
    if missing.any():
        out.loc[missing, "is_trainable"] = False
        blank_reason = out["excluded_reason"].fillna("").astype(str).str.len() == 0
        out.loc[missing & blank_reason, "excluded_reason"] = "missing_features"
    return out.drop(columns=["_features_available"])


def _matrix_for_target(
    feature_matrix: pd.DataFrame,
    target_df: pd.DataFrame,
    feature_cols: list[str],
) -> pd.DataFrame:
    feature_frame = feature_matrix[["country", "crop_year"] + feature_cols].copy()
    feature_frame["_features_available"] = True
    merged = target_df[PSD_MATRIX_ID_COLUMNS].merge(
        feature_frame,
        on=["country", "crop_year"],
        how="left",
        validate="many_to_one",
    )
    merged = _mark_missing_features(merged)
    return merged[PSD_MATRIX_ID_COLUMNS + feature_cols].sort_values(
        ["country", "crop_year"]
    ).reset_index(drop=True)


def _psd_source_for_target_origins(
    psd_source: pd.DataFrame,
    target_df: pd.DataFrame,
    *,
    commodity: str,
) -> pd.DataFrame:
    required = {"leviathan_slug", "country", "market_year", "release_date"}
    missing = required - set(psd_source.columns)
    if missing:
        raise ValueError(f"{commodity}: PSD source missing columns {sorted(missing)}")

    frames: list[pd.DataFrame] = []
    mappings = target_df[
        ["origin_key", "psd_source_slug", "psd_country"]
    ].drop_duplicates()
    for mapping in mappings.itertuples(index=False):
        subset = psd_source.loc[
            (psd_source["leviathan_slug"] == mapping.psd_source_slug)
            & (psd_source["country"] == mapping.psd_country)
        ].copy()
        if subset.empty:
            subset = psd_source.loc[
                (psd_source["leviathan_slug"] == mapping.psd_source_slug)
                & (psd_source["country"] == mapping.origin_key)
            ].copy()
        if subset.empty:
            continue
        subset["country"] = str(mapping.origin_key)
        frames.append(subset)

    if not frames:
        return pd.DataFrame(columns=list(psd_source.columns))
    return pd.concat(frames, ignore_index=True).drop_duplicates().reset_index(drop=True)


def _expand_targets_to_snapshots(
    target_group: pd.DataFrame,
    snapshots: pd.DataFrame,
) -> pd.DataFrame:
    target = target_group.copy()
    snapshot_frame = snapshots[PSD_SNAPSHOT_COLUMNS[:2] + ["crop_year", "snapshot_policy"]].copy()
    expanded = target.merge(
        snapshot_frame,
        on="crop_year",
        how="inner",
        validate="many_to_many",
    )
    duplicates = expanded.duplicated(
        ["commodity", "country", "crop_year", "target_key", "snapshot_stage", "as_of_date"],
        keep=False,
    )
    if duplicates.any():
        keys = (
            expanded.loc[
                duplicates,
                ["commodity", "country", "crop_year", "target_key", "snapshot_stage", "as_of_date"],
            ]
            .drop_duplicates()
            .sort_values(["commodity", "country", "crop_year", "target_key", "snapshot_stage"])
            .to_dict("records")
        )
        raise ValueError(f"duplicate PSD snapshot target keys {keys[:5]}")
    return expanded


def _matrix_for_snapshot_target(
    feature_matrix: pd.DataFrame,
    target_df: pd.DataFrame,
    feature_cols: list[str],
) -> pd.DataFrame:
    feature_frame = feature_matrix[
        ["country", "crop_year", "snapshot_stage", "as_of_date"] + feature_cols
    ].copy()
    feature_frame["_features_available"] = True
    merged = target_df[PSD_SNAPSHOT_MATRIX_ID_COLUMNS].merge(
        feature_frame,
        on=["country", "crop_year", "snapshot_stage", "as_of_date"],
        how="left",
        validate="many_to_one",
    )
    merged = _mark_missing_features(merged)
    return merged[PSD_SNAPSHOT_MATRIX_ID_COLUMNS + feature_cols].sort_values(
        ["country", "crop_year", "snapshot_stage"]
    ).reset_index(drop=True)


def build_psd_commodity_model_datasets(
    feature_matrix: pd.DataFrame,
    psd_targets: pd.DataFrame,
    *,
    commodity: str,
    feature_membership: pd.DataFrame,
    config: PSDModelReadyBuildConfig | None = None,
    target_keys: tuple[str, ...] = (),
) -> CommodityModelDataset:
    """Build model-ready PSD target/matrix artifacts for one commodity."""
    build_config = config or PSDModelReadyBuildConfig()
    _validate_feature_matrix(feature_matrix, commodity)
    if psd_targets.empty:
        summaries = [{
            "commodity": commodity,
            "dataset_key": PSD_DATASET_KEY,
            "status": "skipped_no_psd_targets",
        }]
        return CommodityModelDataset(
            commodity=commodity,
            target_tables={},
            matrices={},
            baseline_metrics=pd.DataFrame(
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
            ),
            summaries=summaries,
        )

    target_df = psd_targets.loc[psd_targets["commodity"] == commodity].copy()
    if target_keys:
        target_df = target_df.loc[target_df["target_key"].isin(set(target_keys))].copy()
    if target_df.empty:
        summaries = [{
            "commodity": commodity,
            "dataset_key": PSD_DATASET_KEY,
            "status": "skipped_no_selected_psd_targets",
        }]
        return CommodityModelDataset(
            commodity=commodity,
            target_tables={},
            matrices={},
            baseline_metrics=pd.DataFrame(
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
            ),
            summaries=summaries,
        )

    _validate_psd_targets(target_df, commodity)
    feature_cols = _feature_union(
        feature_matrix, feature_membership, build_config.compatible_feature_sets
    )
    matrices: dict[tuple[str, str], pd.DataFrame] = {}
    metrics_frames: list[pd.DataFrame] = []
    summaries: list[dict] = []

    for target_key, target_group in target_df.groupby("target_key", sort=True):
        target_group = target_group.sort_values(["country", "crop_year"]).reset_index(drop=True)
        matrix_df = _matrix_for_target(feature_matrix, target_group, feature_cols)
        matrices[(PSD_DATASET_KEY, str(target_key))] = matrix_df
        metrics_frames.append(
            compute_baseline_metrics(
                matrix_df,
                dataset_key=PSD_DATASET_KEY,
                commodity=commodity,
                target_key=str(target_key),
                baseline_names=build_config.baselines,
            )
        )
        trainable_rows = int(matrix_df["is_trainable"].fillna(False).astype(bool).sum())
        summaries.append({
            "commodity": commodity,
            "dataset_key": PSD_DATASET_KEY,
            "target_key": str(target_key),
            "status": "built",
            "row_count": int(len(matrix_df)),
            "trainable_row_count": trainable_rows,
            "feature_count": int(len(feature_cols)),
            "target_source": "psd",
            "target_family": str(target_group["target_family"].iloc[0]),
            "target_attribute": str(target_group["target_attribute"].iloc[0]),
            "target_status_counts": {
                str(k): int(v)
                for k, v in target_group["target_status"].value_counts().sort_index().items()
            },
            "mapping_confidence_counts": {
                str(k): int(v)
                for k, v in target_group["mapping_confidence"].value_counts().sort_index().items()
            },
            "origin_count": int(target_group["origin_key"].nunique()),
            "target_market_year_min": int(target_group["target_market_year"].min()),
            "target_market_year_max": int(target_group["target_market_year"].max()),
        })

    baseline_metrics = (
        pd.concat(metrics_frames, ignore_index=True)
        if metrics_frames else pd.DataFrame()
    )
    return CommodityModelDataset(
        commodity=commodity,
        target_tables={PSD_DATASET_KEY: target_df[PSD_TARGET_COLUMNS]},
        matrices=matrices,
        baseline_metrics=baseline_metrics,
        summaries=summaries,
    )


def build_psd_commodity_snapshot_model_datasets(
    psd_source: pd.DataFrame,
    psd_targets: pd.DataFrame,
    *,
    commodity: str,
    feature_membership: pd.DataFrame,
    calendar: CropCalendar,
    snapshot_config: SnapshotStageConfig,
    snapshot_stage_ids: tuple[str, ...] = (),
    as_of_date: str | None = None,
    include_named_stages: bool = True,
    static_feature_matrix: pd.DataFrame | None = None,
    config: PSDModelReadyBuildConfig | None = None,
    target_keys: tuple[str, ...] = (),
) -> CommodityModelDataset:
    """Build additive PSD snapshot-stage model-ready matrices for one commodity."""
    snapshot_dataset_key = snapshot_config.default_dataset_key or PSD_SNAPSHOT_DATASET_KEY
    build_config = config or PSDModelReadyBuildConfig(
        compatible_feature_sets=DEFAULT_PSD_SNAPSHOT_FEATURE_SETS
    )
    target_df = psd_targets.loc[psd_targets["commodity"] == commodity].copy()
    if target_keys:
        target_df = target_df.loc[target_df["target_key"].isin(set(target_keys))].copy()
    if target_df.empty:
        summaries = [{
            "commodity": commodity,
            "dataset_key": snapshot_dataset_key,
            "status": "skipped_no_selected_psd_targets",
        }]
        return CommodityModelDataset(
            commodity=commodity,
            target_tables={},
            matrices={},
            baseline_metrics=pd.DataFrame(
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
            ),
            summaries=summaries,
        )

    _validate_psd_targets(target_df, commodity)
    target_df["dataset_key"] = snapshot_dataset_key
    crop_years = sorted(
        int(year) for year in pd.to_numeric(target_df["crop_year"], errors="coerce").dropna().unique()
    )
    snapshots = resolve_snapshot_dates(
        calendar=calendar,
        crop_years=crop_years,
        config=snapshot_config,
        stage_ids=snapshot_stage_ids,
        as_of_date=as_of_date,
        include_named_stages=include_named_stages,
    )
    feature_source = _psd_source_for_target_origins(
        psd_source, target_df, commodity=commodity
    )
    countries = sorted(target_df["country"].astype(str).unique())
    dynamic_features = build_psd_vintage_snapshot_feature_matrix(
        feature_source,
        countries=countries,
        snapshots=snapshots,
    )
    feature_matrix, feature_cols, selected_by_set = _snapshot_feature_columns(
        dynamic_features,
        feature_membership,
        build_config.compatible_feature_sets,
        static_feature_matrix=static_feature_matrix,
    )

    matrices: dict[tuple[str, str], pd.DataFrame] = {}
    target_tables: dict[str, list[pd.DataFrame]] = {snapshot_dataset_key: []}
    metrics_frames: list[pd.DataFrame] = []
    summaries: list[dict] = []

    for target_key, target_group in target_df.groupby("target_key", sort=True):
        target_group = target_group.sort_values(["country", "crop_year"]).reset_index(drop=True)
        snapshot_targets = _expand_targets_to_snapshots(target_group, snapshots)
        matrix_df = _matrix_for_snapshot_target(feature_matrix, snapshot_targets, feature_cols)
        matrices[(snapshot_dataset_key, str(target_key))] = matrix_df
        target_tables[snapshot_dataset_key].append(
            snapshot_targets[PSD_SNAPSHOT_TARGET_COLUMNS]
        )
        metrics_frames.append(
            compute_baseline_metrics(
                matrix_df,
                dataset_key=snapshot_dataset_key,
                commodity=commodity,
                target_key=str(target_key),
                baseline_names=build_config.baselines,
            )
        )
        trainable_rows = int(matrix_df["is_trainable"].fillna(False).astype(bool).sum())
        summaries.append({
            "commodity": commodity,
            "dataset_key": snapshot_dataset_key,
            "target_key": str(target_key),
            "status": "built",
            "row_count": int(len(matrix_df)),
            "trainable_row_count": trainable_rows,
            "feature_count": int(len(feature_cols)),
            "target_source": "psd",
            "target_family": str(target_group["target_family"].iloc[0]),
            "target_attribute": str(target_group["target_attribute"].iloc[0]),
            "snapshot_policy": snapshot_config.snapshot_policy,
            "snapshot_stages": sorted(matrix_df["snapshot_stage"].astype(str).unique()),
            "snapshot_count_per_target_row": int(len(snapshots["snapshot_stage"].unique())),
            "compatible_feature_sets": list(build_config.compatible_feature_sets),
            "feature_count_by_set": {
                feature_set_id: int(len(features))
                for feature_set_id, features in selected_by_set.items()
            },
            "target_status_counts": {
                str(k): int(v)
                for k, v in target_group["target_status"].value_counts().sort_index().items()
            },
            "mapping_confidence_counts": {
                str(k): int(v)
                for k, v in target_group["mapping_confidence"].value_counts().sort_index().items()
            },
            "origin_count": int(target_group["origin_key"].nunique()),
            "target_market_year_min": int(target_group["target_market_year"].min()),
            "target_market_year_max": int(target_group["target_market_year"].max()),
        })

    baseline_metrics = (
        pd.concat(metrics_frames, ignore_index=True)
        if metrics_frames else pd.DataFrame()
    )
    final_target_tables = {
        dataset_key: pd.concat(frames, ignore_index=True)
        for dataset_key, frames in target_tables.items()
        if frames
    }
    return CommodityModelDataset(
        commodity=commodity,
        target_tables=final_target_tables,
        matrices=matrices,
        baseline_metrics=baseline_metrics,
        summaries=summaries,
    )
