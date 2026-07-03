"""Static annual feature reuse for WASDE snapshot model-ready rows."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Mapping

import numpy as np
import pandas as pd

SNAPSHOT_ID_COLUMNS = [
    "dataset_key",
    "contract_key",
    "origin_key",
    "target_market_year",
    "as_of_date",
    "snapshot_stage",
]

STATIC_KEY_COLUMNS = ["contract_key", "origin_key", "crop_year"]
STATIC_TARGET_YEAR_COLUMN = "target_market_year"

DEFAULT_SAFE_STATIC_FEATURE_SETS = frozenset({
    "corn_preseason_core",
    "preseason_physical",
    "planting_incentives",
    "trade_competitiveness",
    "balance_sheet",
})

STAGE_LIMITED_STATIC_FEATURE_SETS = frozenset({
    "inseason_weather",
    "inseason_weather_dense",
    "crop_condition",
    "physical_flow",
})

INSEASON_ALLOWED_STAGES = frozenset({
    "early_season",
    "midseason",
    "late_season",
    "post_harvest",
    "finalization",
})

STATIC_METADATA_COLUMNS = frozenset({
    "source_dataset_version",
    "dataset_key",
    "commodity",
    "contract_key",
    "commodity_group",
    "origin",
    "origin_key",
    "country",
    "crop_year",
    "target_market_year",
    "target_key",
    "target_family",
    "target_attribute",
    "target_source",
    "target_value",
    "target_anomaly_pct",
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
    "psd_source_slug",
    "psd_commodity",
    "psd_country",
    "origin_role",
    "mapping_confidence",
    "target_status",
    "as_of_date",
    "snapshot_stage",
    "snapshot_policy",
    "snapshot_sequence",
    "snapshot_count",
    "snapshot_month_code",
    "sample_weight",
    "cv_group",
    "cv_time",
    "target_event_label",
    "target_event_threshold",
    "target_event_threshold_type",
    "target_event_direction",
    "target_event_definition",
    "feature_set_id",
    "feature_set_version",
    "feature_set_sha",
})

EXACT_LEAKAGE_FEATURES = frozenset({
    "target_value",
    "target_anomaly_pct",
    "actual_value",
    "trend_prediction",
    "target_event_label",
})

MARKET_SIGNAL_PATTERNS = tuple(
    re.compile(pattern)
    for pattern in (
        r"^futures_",
        r"^calendar_spread_",
        r"^technical_",
        r"^vol_regime",
        r"^cot_",
    )
)

LAGGED_PSD_TOKENS = (
    "prior",
    "lag",
    "previous",
    "trailing",
    "trend",
    "yoy",
    "history",
    "available",
    "source_disagreement",
)

STATIC_FEATURE_MANIFEST_COLUMNS = [
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


@dataclass(frozen=True)
class StaticFeatureDecision:
    """Policy decision for one requested static feature."""

    feature: str
    feature_set_id: str
    decision: str
    reason: str
    allowed_snapshot_stages: tuple[str, ...]
    blocked_snapshot_stages: tuple[str, ...]


def _as_feature_set_map(
    feature_sets: Mapping[str, Iterable[str]] | pd.DataFrame | None,
    *,
    static_matrix: pd.DataFrame,
) -> dict[str, list[str]]:
    if feature_sets is None:
        feature_cols = [
            str(col)
            for col in static_matrix.columns
            if str(col) not in STATIC_METADATA_COLUMNS
        ]
        return {"static_matrix": sorted(feature_cols)}
    if isinstance(feature_sets, pd.DataFrame):
        required = {"feature_set_id", "feature"}
        missing = required - set(feature_sets.columns)
        if missing:
            raise ValueError(f"feature set membership missing columns: {sorted(missing)}")
        grouped: dict[str, list[str]] = {}
        for feature_set_id, group in feature_sets.groupby("feature_set_id", sort=True):
            grouped[str(feature_set_id)] = sorted(group["feature"].astype(str).unique())
        return grouped
    return {
        str(feature_set_id): sorted({str(feature) for feature in features})
        for feature_set_id, features in feature_sets.items()
    }


def _normalize_snapshot_frame(snapshot_rows: pd.DataFrame) -> pd.DataFrame:
    missing = set(SNAPSHOT_ID_COLUMNS) - set(snapshot_rows.columns)
    if missing:
        raise ValueError(f"snapshot frame missing columns: {sorted(missing)}")
    out = snapshot_rows.copy()
    out["target_market_year"] = pd.to_numeric(
        out["target_market_year"], errors="coerce"
    ).astype("Int64")
    out["as_of_date"] = pd.to_datetime(out["as_of_date"], errors="coerce")
    out = out.dropna(subset=["target_market_year", "as_of_date"]).copy()
    out["target_market_year"] = out["target_market_year"].astype(int)
    duplicates = out.duplicated(SNAPSHOT_ID_COLUMNS, keep=False)
    if duplicates.any():
        examples = (
            out.loc[duplicates, SNAPSHOT_ID_COLUMNS]
            .drop_duplicates()
            .head(5)
            .to_dict("records")
        )
        raise ValueError(f"duplicate WASDE snapshot rows: {examples}")
    return out.sort_values(SNAPSHOT_ID_COLUMNS).reset_index(drop=True)


def _normalize_static_matrix(static_matrix: pd.DataFrame) -> pd.DataFrame:
    out = static_matrix.copy()
    if "contract_key" not in out.columns and "commodity" in out.columns:
        out["contract_key"] = out["commodity"].astype(str)
    if "origin_key" not in out.columns and "country" in out.columns:
        out["origin_key"] = out["country"].astype(str)
    if "crop_year" not in out.columns and STATIC_TARGET_YEAR_COLUMN in out.columns:
        out["crop_year"] = out[STATIC_TARGET_YEAR_COLUMN]
    missing = set(STATIC_KEY_COLUMNS) - set(out.columns)
    if missing:
        raise ValueError(f"static feature matrix missing columns: {sorted(missing)}")
    out["crop_year"] = pd.to_numeric(out["crop_year"], errors="coerce").astype("Int64")
    out = out.dropna(subset=["crop_year"]).copy()
    out["crop_year"] = out["crop_year"].astype(int)
    return out


def _non_null_rate(series: pd.Series) -> float:
    if len(series) == 0:
        return np.nan
    return float(series.notna().mean())


def _constant_rate(series: pd.Series) -> float:
    non_null = series.dropna()
    if non_null.empty:
        return np.nan
    counts = non_null.value_counts(dropna=True, normalize=True)
    return float(counts.max()) if not counts.empty else np.nan


def _is_lagged_psd_context(feature: str) -> bool:
    lowered = feature.lower()
    return lowered.startswith("psd_") and any(token in lowered for token in LAGGED_PSD_TOKENS)


def classify_static_feature_availability(
    feature: str,
    feature_set_id: str,
    *,
    snapshot_stages: Iterable[str],
    feature_policy: str | None = None,
    allow_diagnostic: bool = False,
    dynamic_feature_columns: Iterable[str] = (),
) -> StaticFeatureDecision:
    """Classify whether a static feature is safe for snapshot reuse."""
    feature = str(feature)
    feature_set_id = str(feature_set_id)
    stages = tuple(sorted({str(stage) for stage in snapshot_stages}))
    dynamic_cols = {str(col) for col in dynamic_feature_columns}
    policy = str(feature_policy or "")

    if feature in dynamic_cols:
        return StaticFeatureDecision(feature, feature_set_id, "blocked", "dynamic_feature_collision", (), stages)
    if feature in EXACT_LEAKAGE_FEATURES or feature.startswith("label_") or feature.startswith("target_"):
        return StaticFeatureDecision(feature, feature_set_id, "blocked", "target_or_label_leakage", (), stages)
    if feature.startswith("psd_") and not _is_lagged_psd_context(feature):
        return StaticFeatureDecision(feature, feature_set_id, "blocked", "same_year_psd_context_not_lagged", (), stages)
    if policy == "excluded_market_signal" or any(pattern.search(feature) for pattern in MARKET_SIGNAL_PATTERNS):
        return StaticFeatureDecision(feature, feature_set_id, "blocked", "excluded_market_signal", (), stages)
    if policy == "diagnostic_only" and not allow_diagnostic:
        return StaticFeatureDecision(feature, feature_set_id, "blocked", "diagnostic_only", (), stages)

    if feature_set_id in STAGE_LIMITED_STATIC_FEATURE_SETS:
        allowed = tuple(stage for stage in stages if stage in INSEASON_ALLOWED_STAGES)
        blocked = tuple(stage for stage in stages if stage not in INSEASON_ALLOWED_STAGES)
        if not allowed:
            return StaticFeatureDecision(feature, feature_set_id, "blocked", "stage_limited_feature_unavailable", (), blocked)
        if blocked:
            return StaticFeatureDecision(feature, feature_set_id, "stage_masked", "masked_for_preseason_stages", allowed, blocked)
        return StaticFeatureDecision(feature, feature_set_id, "allowed", "stage_limited_feature_available", allowed, ())

    return StaticFeatureDecision(feature, feature_set_id, "allowed", "static_feature_available", stages, ())


def build_static_feature_reuse_manifest(
    snapshot_rows: pd.DataFrame,
    static_matrix: pd.DataFrame,
    feature_sets: Mapping[str, Iterable[str]] | pd.DataFrame | None = None,
    *,
    feature_policy_map: Mapping[str, str] | None = None,
    allow_diagnostic: bool = False,
    dynamic_feature_columns: Iterable[str] = (),
) -> pd.DataFrame:
    """Return an auditable feature-level manifest for static snapshot reuse."""
    snapshots = _normalize_snapshot_frame(snapshot_rows)
    static = _normalize_static_matrix(static_matrix)
    feature_set_map = _as_feature_set_map(feature_sets, static_matrix=static)
    policies = {str(key): str(value) for key, value in (feature_policy_map or {}).items()}
    snapshot_stages = tuple(snapshots["snapshot_stage"].astype(str).unique())

    rows: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for feature_set_id, features in feature_set_map.items():
        for feature in features:
            key = (str(feature_set_id), str(feature))
            if key in seen:
                continue
            seen.add(key)
            if feature not in static.columns:
                rows.append({
                    "feature_set_id": feature_set_id,
                    "feature": feature,
                    "decision": "missing_static_feature",
                    "reason": "feature_not_in_static_matrix",
                    "allowed_snapshot_stages": "",
                    "blocked_snapshot_stages": ",".join(sorted(snapshot_stages)),
                    "feature_policy": policies.get(feature, ""),
                    "non_null_rate": np.nan,
                    "constant_rate": np.nan,
                })
                continue

            decision = classify_static_feature_availability(
                feature,
                feature_set_id,
                snapshot_stages=snapshot_stages,
                feature_policy=policies.get(feature),
                allow_diagnostic=allow_diagnostic,
                dynamic_feature_columns=dynamic_feature_columns,
            )
            rows.append({
                "feature_set_id": feature_set_id,
                "feature": feature,
                "decision": decision.decision,
                "reason": decision.reason,
                "allowed_snapshot_stages": ",".join(decision.allowed_snapshot_stages),
                "blocked_snapshot_stages": ",".join(decision.blocked_snapshot_stages),
                "feature_policy": policies.get(feature, ""),
                "non_null_rate": _non_null_rate(static[feature]),
                "constant_rate": _constant_rate(static[feature]),
            })

    if not rows:
        return pd.DataFrame(columns=STATIC_FEATURE_MANIFEST_COLUMNS)
    return (
        pd.DataFrame(rows)
        .reindex(columns=STATIC_FEATURE_MANIFEST_COLUMNS)
        .sort_values(["feature_set_id", "feature"])
        .reset_index(drop=True)
    )


def _selected_feature_stage_rules(manifest: pd.DataFrame) -> dict[str, tuple[str, ...]]:
    rules: dict[str, set[str]] = {}
    for _, row in manifest.iterrows():
        decision = str(row["decision"])
        if decision not in {"allowed", "stage_masked"}:
            continue
        feature = str(row["feature"])
        stages = {
            stage
            for stage in str(row.get("allowed_snapshot_stages") or "").split(",")
            if stage
        }
        rules.setdefault(feature, set()).update(stages)
    return {feature: tuple(sorted(stages)) for feature, stages in rules.items()}


def _dedupe_static_keys(static: pd.DataFrame, feature_cols: list[str]) -> pd.DataFrame:
    if not feature_cols:
        return static[STATIC_KEY_COLUMNS].drop_duplicates().copy()
    duplicate_mask = static.duplicated(STATIC_KEY_COLUMNS, keep=False)
    if not duplicate_mask.any():
        return static[STATIC_KEY_COLUMNS + feature_cols].copy()

    conflicts: list[dict[str, object]] = []
    for key_values, group in static.loc[duplicate_mask].groupby(STATIC_KEY_COLUMNS, sort=False):
        for feature in feature_cols:
            if group[feature].nunique(dropna=False) > 1:
                if not isinstance(key_values, tuple):
                    key_values = (key_values,)
                conflicts.append(dict(zip(STATIC_KEY_COLUMNS, key_values), feature=feature))
                break
    if conflicts:
        raise ValueError(f"duplicate static feature keys with conflicting values: {conflicts[:5]}")
    return static[STATIC_KEY_COLUMNS + feature_cols].drop_duplicates(STATIC_KEY_COLUMNS, keep="last")


def join_static_features_to_wasde_snapshots(
    snapshot_rows: pd.DataFrame,
    static_matrix: pd.DataFrame,
    feature_sets: Mapping[str, Iterable[str]] | pd.DataFrame | None = None,
    *,
    feature_policy_map: Mapping[str, str] | None = None,
    allow_diagnostic: bool = False,
    dynamic_feature_columns: Iterable[str] = (),
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Left-join safe annual/static features onto WASDE snapshot rows.

    The join preserves the snapshot grain and masks stage-limited features for
    snapshot stages where those features would not yet be known.
    """
    snapshots = _normalize_snapshot_frame(snapshot_rows)
    static = _normalize_static_matrix(static_matrix)
    manifest = build_static_feature_reuse_manifest(
        snapshots,
        static,
        feature_sets,
        feature_policy_map=feature_policy_map,
        allow_diagnostic=allow_diagnostic,
        dynamic_feature_columns=dynamic_feature_columns,
    )
    stage_rules = _selected_feature_stage_rules(manifest)
    selected_features = sorted(stage_rules)
    collisions = sorted(
        feature
        for feature in selected_features
        if feature in snapshots.columns and feature not in SNAPSHOT_ID_COLUMNS
    )
    if collisions:
        raise ValueError(f"static features collide with snapshot columns: {collisions}")
    dynamic_collisions = sorted(set(selected_features) & {str(col) for col in dynamic_feature_columns})
    if dynamic_collisions:
        raise ValueError(f"static features collide with dynamic features: {dynamic_collisions}")

    static_for_join = _dedupe_static_keys(static, selected_features)
    joined = snapshots.merge(
        static_for_join,
        left_on=["contract_key", "origin_key", "target_market_year"],
        right_on=["contract_key", "origin_key", "crop_year"],
        how="left",
        validate="many_to_one",
        suffixes=("", "_static"),
    )
    if "crop_year_static" in joined.columns:
        joined = joined.drop(columns=["crop_year_static"])
    if "crop_year" in joined.columns and "crop_year" not in snapshots.columns:
        joined = joined.drop(columns=["crop_year"])

    for feature, allowed_stages in stage_rules.items():
        if feature not in joined.columns:
            continue
        allowed = set(allowed_stages)
        if allowed and allowed != set(snapshots["snapshot_stage"].astype(str).unique()):
            joined.loc[~joined["snapshot_stage"].astype(str).isin(allowed), feature] = np.nan

    validate_static_snapshot_join(snapshots, joined, manifest)
    return joined, manifest


def validate_static_snapshot_join(
    before: pd.DataFrame,
    after: pd.DataFrame,
    manifest: pd.DataFrame,
) -> None:
    """Validate row preservation and leakage-control outcomes after a static join."""
    before_norm = _normalize_snapshot_frame(before)
    after_norm = _normalize_snapshot_frame(after)
    if len(before_norm) != len(after_norm):
        raise ValueError(f"static snapshot join changed row count: before={len(before_norm)} after={len(after_norm)}")
    if after_norm.duplicated(SNAPSHOT_ID_COLUMNS).any():
        raise ValueError("static snapshot join produced duplicate snapshot keys")
    before_cols = set(before.columns)
    blocked_features = set(
        manifest.loc[
            manifest["decision"].astype(str).isin({"blocked", "missing_static_feature"}),
            "feature",
        ].astype(str)
    )
    leaked = sorted((set(after.columns) - before_cols) & blocked_features)
    if leaked:
        raise ValueError(f"blocked static features were joined: {leaked}")
