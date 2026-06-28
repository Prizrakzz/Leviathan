"""Build model-ready matrices from PSD target panels."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pandas as pd

from leviathan.features.calendar import CropCalendar
from leviathan.features.computations.psd_vintages import (
    build_psd_vintage_snapshot_join_audit,
    build_psd_vintage_snapshot_feature_matrix,
    summarize_psd_vintage_feature_quality,
    validate_psd_vintage_feature_quality,
)
from leviathan.features.feature_sets import selected_features_for_set
from leviathan.model_datasets.baselines import compute_baseline_metrics
from leviathan.model_datasets.builder import CommodityModelDataset
from leviathan.model_datasets.feature_pruning import prune_model_ready_features
from leviathan.model_datasets.psd_target_builder import PSD_TARGET_COLUMNS
from leviathan.model_datasets.snapshot_stages import (
    SnapshotStageConfig,
    resolve_snapshot_dates,
)
from leviathan.model_datasets.wasde_snapshot import (
    build_wasde_snapshot_feature_matrix,
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
PSD_BALANCE_SHEET_SNAPSHOT_FEATURE_SET_ID = "psd_balance_sheet_snapshot"
PSD_SNAPSHOT_MATRIX_ID_COLUMNS = PSD_MATRIX_ID_COLUMNS + PSD_SNAPSHOT_COLUMNS
PSD_SNAPSHOT_TARGET_COLUMNS = PSD_TARGET_COLUMNS + PSD_SNAPSHOT_COLUMNS
PSD_MONTHLY_VINTAGE_FEATURE_SET_ID = "psd_monthly_vintage_features"
PSD_PRESEASON_PLUS_VINTAGE_FEATURE_SET_ID = "preseason_physical_plus_psd_vintage"
PSD_PRESEASON_PLUS_SNAPSHOT_FEATURE_SET_ID = "preseason_physical_plus_psd_snapshot"
WASDE_MONTHLY_REVISION_FEATURE_SET_ID = "wasde_monthly_revision"
PRESEASON_PLUS_WASDE_REVISION_FEATURE_SET_ID = "preseason_physical_plus_wasde_revision"
DEFAULT_PSD_SNAPSHOT_FEATURE_SETS = (WASDE_MONTHLY_REVISION_FEATURE_SET_ID,)
PSD_SNAPSHOT_DYNAMIC_ID_COLUMNS = {"country", "crop_year", "snapshot_stage", "as_of_date"}
PSD_VINTAGE_FEATURE_SUFFIXES = (
    "latest_estimate_as_of",
    "mom_revision",
    "revision_since_first_forecast",
    "consecutive_revision_count",
    "current_vs_trend",
    "month_code",
    "release_count_for_market_year",
)
PSD_SNAPSHOT_STATIC_FEATURE_SETS = {
    "preseason_physical",
    PSD_PRESEASON_PLUS_VINTAGE_FEATURE_SET_ID,
    PSD_PRESEASON_PLUS_SNAPSHOT_FEATURE_SET_ID,
    PRESEASON_PLUS_WASDE_REVISION_FEATURE_SET_ID,
}
PSD_SNAPSHOT_FEATURE_SET_ALIASES = {
    PSD_MONTHLY_VINTAGE_FEATURE_SET_ID: PSD_BALANCE_SHEET_SNAPSHOT_FEATURE_SET_ID,
    PSD_PRESEASON_PLUS_VINTAGE_FEATURE_SET_ID: PSD_PRESEASON_PLUS_SNAPSHOT_FEATURE_SET_ID,
}
PSD_CANONICAL_SNAPSHOT_FEATURE_SETS = {
    PSD_BALANCE_SHEET_SNAPSHOT_FEATURE_SET_ID,
    WASDE_MONTHLY_REVISION_FEATURE_SET_ID,
    PRESEASON_PLUS_WASDE_REVISION_FEATURE_SET_ID,
}
PSD_LEGACY_SNAPSHOT_FEATURE_SETS = set(PSD_SNAPSHOT_FEATURE_SET_ALIASES)
PSD_SUPPORTED_SNAPSHOT_FEATURE_SETS = {
    *PSD_CANONICAL_SNAPSHOT_FEATURE_SETS,
    *PSD_LEGACY_SNAPSHOT_FEATURE_SETS,
    "preseason_physical",
    PSD_PRESEASON_PLUS_SNAPSHOT_FEATURE_SET_ID,
}


@dataclass(frozen=True)
class PSDModelReadyBuildConfig:
    """Configuration for PSD model-ready matrix materialization."""

    compatible_feature_sets: tuple[str, ...] = DEFAULT_PSD_FEATURE_SETS
    baselines: tuple[str, ...] = PSD_BASELINES


def snapshot_feature_set_contract_notes(feature_set_ids: Iterable[str]) -> list[dict[str, str]]:
    """Return canonical/legacy status notes for requested snapshot feature sets."""
    notes: list[dict[str, str]] = []
    for feature_set_id in tuple(str(feature_set_id) for feature_set_id in feature_set_ids):
        canonical = PSD_SNAPSHOT_FEATURE_SET_ALIASES.get(feature_set_id, feature_set_id)
        status = "legacy_alias" if feature_set_id in PSD_LEGACY_SNAPSHOT_FEATURE_SETS else "canonical"
        note = {
            "feature_set_id": feature_set_id,
            "status": status,
            "canonical_feature_set_id": canonical,
        }
        if feature_set_id == PSD_MONTHLY_VINTAGE_FEATURE_SET_ID:
            note["message"] = (
                "Legacy compatibility alias. Current silver/psd is latest-bulk, "
                "not true monthly release history; use psd_balance_sheet_snapshot "
                "for PSD context and wasde_monthly_revision for revision signal."
            )
        elif feature_set_id == PSD_PRESEASON_PLUS_VINTAGE_FEATURE_SET_ID:
            note["message"] = (
                "Legacy compatibility alias for preseason physical context plus PSD "
                "snapshot context. Use preseason_physical_plus_wasde_revision for "
                "the current monthly revision signal."
            )
        elif feature_set_id == PSD_BALANCE_SHEET_SNAPSHOT_FEATURE_SET_ID:
            note["message"] = (
                "PSD snapshot context requires visible PSD balance-sheet snapshot "
                "features. It is not a monthly revision signal unless archived PSD "
                "monthly releases are ingested."
            )
        elif feature_set_id == WASDE_MONTHLY_REVISION_FEATURE_SET_ID:
            note["message"] = "Canonical monthly official revision feature set from WASDE."
        elif feature_set_id == PRESEASON_PLUS_WASDE_REVISION_FEATURE_SET_ID:
            note["message"] = "Canonical combined static physical context plus WASDE revision feature set."
        else:
            note["message"] = "Supported snapshot feature set."
        notes.append(note)
    return notes


def validate_snapshot_feature_set_ids(feature_set_ids: Iterable[str]) -> tuple[str, ...]:
    """Fail fast on unsupported snapshot feature-set ids."""
    requested = tuple(str(feature_set_id) for feature_set_id in feature_set_ids)
    unknown = sorted(set(requested) - PSD_SUPPORTED_SNAPSHOT_FEATURE_SETS)
    if unknown:
        supported = sorted(PSD_SUPPORTED_SNAPSHOT_FEATURE_SETS)
        raise ValueError(
            "unsupported PSD snapshot feature sets "
            f"{unknown}; supported snapshot feature sets are {supported}"
        )
    return requested


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
        and any(str(col).endswith(suffix) for suffix in PSD_VINTAGE_FEATURE_SUFFIXES)
    )


def wasde_snapshot_feature_columns(matrix: pd.DataFrame) -> list[str]:
    """Return dynamic WASDE revision columns from a snapshot matrix."""
    return sorted(
        str(col)
        for col in matrix.columns
        if str(col).startswith("wasde_")
        and str(col) not in PSD_SNAPSHOT_DYNAMIC_ID_COLUMNS
    )


def _normalize_snapshot_key_dates(matrix: pd.DataFrame) -> pd.DataFrame:
    out = matrix.copy()
    if "as_of_date" in out.columns:
        out["as_of_date"] = pd.to_datetime(out["as_of_date"], errors="coerce").dt.date
    return out


def _drop_all_missing_feature_columns(
    matrix: pd.DataFrame,
    feature_cols: Iterable[str],
) -> tuple[list[str], list[str]]:
    kept: list[str] = []
    dropped: list[str] = []
    for feature in feature_cols:
        if feature not in matrix.columns:
            continue
        if matrix[feature].notna().any():
            kept.append(str(feature))
        else:
            dropped.append(str(feature))
    return sorted(kept), sorted(dropped)


def _snapshot_static_feature_set_ids(feature_set_ids: Iterable[str]) -> tuple[str, ...]:
    ids = set(str(feature_set_id) for feature_set_id in feature_set_ids)
    out: set[str] = set()
    if {
        PSD_PRESEASON_PLUS_VINTAGE_FEATURE_SET_ID,
        PSD_PRESEASON_PLUS_SNAPSHOT_FEATURE_SET_ID,
        PRESEASON_PLUS_WASDE_REVISION_FEATURE_SET_ID,
    } & ids:
        out.add("preseason_physical")
    out.update(feature_set_id for feature_set_id in ids if feature_set_id in PSD_SNAPSHOT_STATIC_FEATURE_SETS)
    return tuple(sorted(out))


def _snapshot_feature_columns(
    dynamic_features: pd.DataFrame,
    feature_membership: pd.DataFrame,
    feature_set_ids: Iterable[str],
    *,
    static_feature_matrix: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, list[str], dict[str, list[str]], dict[str, list[str]]]:
    """Resolve dynamic and optional static feature columns for snapshot matrices."""
    requested = validate_snapshot_feature_set_ids(feature_set_ids)
    raw_psd_cols = psd_vintage_feature_columns(dynamic_features)
    psd_cols, dropped_psd_cols = _drop_all_missing_feature_columns(
        dynamic_features,
        raw_psd_cols,
    )
    raw_wasde_cols = wasde_snapshot_feature_columns(dynamic_features)
    wasde_cols, dropped_wasde_cols = _drop_all_missing_feature_columns(
        dynamic_features,
        raw_wasde_cols,
    )
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
        if feature_set_id in {
            PSD_MONTHLY_VINTAGE_FEATURE_SET_ID,
            PSD_BALANCE_SHEET_SNAPSHOT_FEATURE_SET_ID,
        }:
            selected_by_set[feature_set_id] = psd_cols
        elif feature_set_id in {
            PSD_PRESEASON_PLUS_VINTAGE_FEATURE_SET_ID,
            PSD_PRESEASON_PLUS_SNAPSHOT_FEATURE_SET_ID,
        }:
            selected_by_set[feature_set_id] = sorted(set(psd_cols) | set(static_cols))
        elif feature_set_id == WASDE_MONTHLY_REVISION_FEATURE_SET_ID:
            selected_by_set[feature_set_id] = wasde_cols
        elif feature_set_id == PRESEASON_PLUS_WASDE_REVISION_FEATURE_SET_ID:
            selected_by_set[feature_set_id] = sorted(set(wasde_cols) | set(static_cols))
        else:
            selected_by_set[feature_set_id] = _feature_union(
                feature_matrix, feature_membership, (feature_set_id,)
            )

    for feature_set_id in requested:
        selected = selected_by_set.get(feature_set_id, [])
        if feature_set_id == PSD_BALANCE_SHEET_SNAPSHOT_FEATURE_SET_ID and not psd_cols:
            raise ValueError(
                "PSD snapshot feature set psd_balance_sheet_snapshot emitted zero "
                "usable PSD snapshot features. Current silver/psd may be latest-bulk "
                "only; use wasde_monthly_revision for monthly revision signal."
            )
        if feature_set_id == WASDE_MONTHLY_REVISION_FEATURE_SET_ID and not wasde_cols:
            raise ValueError(
                "WASDE snapshot feature set wasde_monthly_revision emitted zero "
                "usable WASDE revision features. Provide silver/wasde rows with "
                "release_date <= snapshot as_of_date."
            )
        if feature_set_id == PRESEASON_PLUS_WASDE_REVISION_FEATURE_SET_ID:
            if not wasde_cols:
                raise ValueError(
                    "preseason_physical_plus_wasde_revision requires non-empty "
                    "WASDE revision features."
                )
            if not static_cols:
                raise ValueError(
                    "preseason_physical_plus_wasde_revision requires non-empty "
                    "preseason_physical static features."
                )
        if feature_set_id == "preseason_physical" and not selected:
            raise ValueError("snapshot feature set preseason_physical emitted zero features")

    feature_cols = sorted({
        feature for features in selected_by_set.values() for feature in features
    })
    dropped = {
        "psd": dropped_psd_cols,
        "wasde": dropped_wasde_cols,
    }
    return feature_matrix, feature_cols, selected_by_set, dropped


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


def _snapshot_context_for_targets(
    target_df: pd.DataFrame,
    snapshots: pd.DataFrame,
) -> pd.DataFrame:
    """Attach target-origin market-year mapping to named snapshot dates."""
    required = {"country", "crop_year", "target_market_year"}
    missing = required - set(target_df.columns)
    if missing:
        raise ValueError(f"PSD snapshot targets missing columns {sorted(missing)}")

    context = target_df[["country", "crop_year", "target_market_year"]].drop_duplicates()
    conflicts = context.groupby(["country", "crop_year"], sort=False)[
        "target_market_year"
    ].nunique()
    conflicts = conflicts.loc[conflicts > 1]
    if not conflicts.empty:
        raise ValueError(
            "PSD snapshot target market-year conflicts "
            f"{conflicts.reset_index()[['country', 'crop_year']].to_dict('records')[:5]}"
        )

    out = context.merge(
        snapshots[["crop_year", "snapshot_stage", "as_of_date", "snapshot_policy"]],
        on="crop_year",
        how="inner",
        validate="many_to_many",
    )
    duplicates = out.duplicated(
        ["country", "crop_year", "snapshot_stage", "as_of_date"], keep=False
    )
    if duplicates.any():
        keys = (
            out.loc[
                duplicates,
                ["country", "crop_year", "snapshot_stage", "as_of_date"],
            ]
            .drop_duplicates()
            .sort_values(["country", "crop_year", "snapshot_stage"])
            .to_dict("records")
        )
        raise ValueError(f"duplicate PSD snapshot context keys {keys[:5]}")
    return out.reset_index(drop=True)


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
        pruning = prune_model_ready_features(
            matrix_df,
            feature_cols,
            selected_feature_sets=build_config.compatible_feature_sets,
        )
        if pruning.dropped_features:
            matrix_df = matrix_df.drop(columns=pruning.dropped_features, errors="ignore")
        target_feature_cols = pruning.kept_features
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
            "feature_count": int(len(target_feature_cols)),
            "pruned_feature_count": int(len(pruning.dropped_features)),
            "review_feature_count": int(len(pruning.review_features)),
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
    wasde_source: pd.DataFrame | None = None,
    config: PSDModelReadyBuildConfig | None = None,
    target_keys: tuple[str, ...] = (),
) -> CommodityModelDataset:
    """Build additive PSD snapshot-stage model-ready matrices for one commodity."""
    snapshot_dataset_key = snapshot_config.default_dataset_key or PSD_SNAPSHOT_DATASET_KEY
    build_config = config or PSDModelReadyBuildConfig(
        compatible_feature_sets=DEFAULT_PSD_SNAPSHOT_FEATURE_SETS
    )
    compatible_feature_sets = validate_snapshot_feature_set_ids(
        build_config.compatible_feature_sets
    )
    contract_notes = snapshot_feature_set_contract_notes(compatible_feature_sets)
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
    snapshot_context = _snapshot_context_for_targets(target_df, snapshots)
    dynamic_features = build_psd_vintage_snapshot_feature_matrix(
        feature_source,
        countries=countries,
        snapshots=snapshot_context,
    )
    dynamic_features = _normalize_snapshot_key_dates(dynamic_features)
    wasde_features = build_wasde_snapshot_feature_matrix(
        wasde_source,
        commodity=commodity,
        countries=countries,
        snapshots=snapshot_context,
    )
    wasde_features = _normalize_snapshot_key_dates(wasde_features)
    if wasde_snapshot_feature_columns(wasde_features):
        dynamic_features = dynamic_features.merge(
            wasde_features,
            on=["country", "crop_year", "snapshot_stage", "as_of_date"],
            how="left",
            validate="one_to_one",
        )
    vintage_join_audit = build_psd_vintage_snapshot_join_audit(
        feature_source,
        countries=countries,
        snapshots=snapshot_context,
    )
    feature_matrix, feature_cols, selected_by_set, dropped_dynamic_cols = _snapshot_feature_columns(
        dynamic_features,
        feature_membership,
        compatible_feature_sets,
        static_feature_matrix=static_feature_matrix,
    )
    dynamic_cols = psd_vintage_feature_columns(dynamic_features)
    wasde_cols = wasde_snapshot_feature_columns(dynamic_features)
    vintage_quality = summarize_psd_vintage_feature_quality(
        feature_matrix,
        feature_cols=dynamic_cols,
    )
    wasde_quality = summarize_psd_vintage_feature_quality(
        feature_matrix,
        feature_cols=wasde_cols,
    )
    if include_named_stages and dynamic_cols:
        validate_psd_vintage_feature_quality(
            feature_matrix,
            feature_cols=dynamic_cols,
            require_suffixes=("latest_estimate_as_of",),
        )
    vintage_join_audit_summary = {
        "row_count": int(len(vintage_join_audit)),
        "missing_reason_counts": (
            {
                str(k): int(v)
                for k, v in vintage_join_audit["missing_reason"]
                .fillna("")
                .value_counts()
                .sort_index()
                .items()
            }
            if "missing_reason" in vintage_join_audit.columns else {}
        ),
        "visible_rows": (
            int((vintage_join_audit["visible_rows"] > 0).sum())
            if "visible_rows" in vintage_join_audit.columns else 0
        ),
        "visible_non_null_rows": (
            int((vintage_join_audit["visible_non_null_rows"] > 0).sum())
            if "visible_non_null_rows" in vintage_join_audit.columns else 0
        ),
    }

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
            "compatible_feature_sets": list(compatible_feature_sets),
            "snapshot_feature_set_contracts": contract_notes,
            "feature_count_by_set": {
                feature_set_id: int(len(features))
                for feature_set_id, features in selected_by_set.items()
            },
            "vintage_feature_quality": vintage_quality,
            "wasde_feature_quality": wasde_quality,
            "dropped_empty_vintage_features": dropped_dynamic_cols.get("psd", []),
            "dropped_empty_wasde_features": dropped_dynamic_cols.get("wasde", []),
            "vintage_join_audit": vintage_join_audit_summary,
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
