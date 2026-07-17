"""Transparent WASDE snapshot anomaly scores.

The first anomaly-detector pass is intentionally simple and auditable. It
computes rolling prior-only level z-scores, prior percentiles, revision shocks,
revision streak scores, and a small equal-weight balance-sheet stress composite.

All learned normalization statistics are fit from rows with ``as_of_date``
strictly before the scored snapshot. The implementation scores unique WASDE
snapshots first, then expands the scores back to each target row so multiple
targets do not inflate the prior-history counts.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd

from leviathan.model_datasets.wasde_snapshot_targets import GROUP_KEY as TARGET_GROUP_KEY

SNAPSHOT_SCORE_ID_COLUMNS = [
    "dataset_key",
    "contract_key",
    "origin_key",
    "target_market_year",
    "target_key",
    "as_of_date",
    "snapshot_stage",
]

SNAPSHOT_BASE_ID_COLUMNS = [
    "dataset_key",
    "contract_key",
    "origin_key",
    "target_market_year",
    "as_of_date",
    "snapshot_stage",
]

SCORE_COLUMNS = [
    *SNAPSHOT_SCORE_ID_COLUMNS,
    "detector_id",
    "score_name",
    "source_feature",
    "source_attribute",
    "source_transform",
    "raw_value",
    "score_value",
    "stress_direction",
    "prior_observation_count",
    "normalization_group_used",
    "component_count",
    "score_null_reason",
]

ROLLING_GROUPINGS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("contract_origin_stage", ("contract_key", "origin_key", "snapshot_stage")),
    ("contract_stage", ("contract_key", "snapshot_stage")),
    ("commodity_group_stage", ("commodity_group", "snapshot_stage")),
)

LOWER_IS_STRESS = {
    "stock_to_use",
    "ending_stocks",
    "production",
    "beginning_stocks",
    "total_supply",
}

HIGHER_IS_STRESS = {
    "exports",
    "domestic_total",
    "total_use",
    "feed",
    "feed_residual",
}

COMPOSITE_ATTRIBUTES = LOWER_IS_STRESS | HIGHER_IS_STRESS
ZSCORE_CAP = 8.0
ROBUST_Z_MIN_HISTORY = 8
REVISION_MIN_RELATIVE_MOM_CHANGE = 0.01
REVISION_MIN_RELATIVE_CUMULATIVE_CHANGE = 0.02
REVISION_MIN_STRESS_STREAK = 2.0


@dataclass(frozen=True)
class WasdeSnapshotAnomalyScoreResult:
    """Container for transparent anomaly score outputs."""

    scores: pd.DataFrame
    score_coverage: pd.DataFrame
    report: dict[str, object]


def _normalize_frame(matrix: pd.DataFrame) -> pd.DataFrame:
    out = matrix.copy()
    if "as_of_date" in out.columns:
        out["as_of_date"] = pd.to_datetime(out["as_of_date"], errors="coerce")
    if "target_market_year" in out.columns:
        out["target_market_year"] = pd.to_numeric(
            out["target_market_year"], errors="coerce"
        )
    return out


def _safe_float(value: object) -> float:
    try:
        out = float(value)
    except Exception:  # noqa: BLE001
        return np.nan
    return out if np.isfinite(out) else np.nan


def _clip_score(value: float, *, cap: float = ZSCORE_CAP) -> float:
    if not np.isfinite(value):
        return np.nan
    return float(np.clip(value, -float(cap), float(cap)))


def _extract_feature_spec(feature: str) -> tuple[str, str] | None:
    """Return ``(attribute, transform)`` for a supported WASDE feature."""
    if not feature.startswith("wasde_"):
        return None
    if feature in {
        "wasde_commodity",
        "wasde_origin",
        "wasde_region",
        "wasde_mapping_sha",
    }:
        return None
    body = feature.removeprefix("wasde_")
    suffixes = (
        ("_consecutive_revision_count", "revision_streak"),
        ("_revision_since_first", "revision_since_first"),
        ("_mom_revision", "mom_revision"),
        ("_latest", "level"),
        ("_estimate", "level"),
    )
    for suffix, transform in suffixes:
        if body.endswith(suffix):
            return body[: -len(suffix)], transform
    return None


def _stress_direction(attribute: str) -> str:
    if attribute in LOWER_IS_STRESS:
        return "lower_is_stress"
    if attribute in HIGHER_IS_STRESS:
        return "higher_is_stress"
    return "context_dependent"


def _orient_z(value: float, direction: str) -> float:
    if not np.isfinite(value):
        return np.nan
    if direction == "lower_is_stress":
        return float(-value)
    if direction == "higher_is_stress":
        return float(value)
    return np.nan


def _orient_percentile(percentile: float, direction: str) -> float:
    if not np.isfinite(percentile):
        return np.nan
    if direction == "lower_is_stress":
        return float(1.0 - percentile)
    if direction == "higher_is_stress":
        return float(percentile)
    return np.nan


def _numeric_feature_columns(matrix: pd.DataFrame) -> tuple[str, ...]:
    features: list[str] = []
    for column in matrix.columns:
        name = str(column)
        spec = _extract_feature_spec(name)
        if spec is None:
            continue
        attribute, _ = spec
        if _stress_direction(attribute) == "context_dependent":
            continue
        numeric = pd.to_numeric(matrix[column], errors="coerce")
        if numeric.notna().any():
            features.append(name)
    return tuple(sorted(features))


def _companion_feature_columns(feature_columns: Iterable[str]) -> tuple[str, ...]:
    companions: set[str] = set()
    for feature in feature_columns:
        spec = _extract_feature_spec(str(feature))
        if spec is None:
            continue
        attribute, transform = spec
        if transform == "revision_streak":
            companions.add(_feature_for_transform(attribute, "latest"))
            companions.add(_feature_for_transform(attribute, "mom_revision"))
            companions.add(_feature_for_transform(attribute, "revision_since_first"))
    return tuple(sorted(companions))


def _unique_snapshot_frame(
    matrix: pd.DataFrame,
    feature_columns: Iterable[str],
) -> pd.DataFrame:
    source = _normalize_frame(matrix)
    required = set(SNAPSHOT_BASE_ID_COLUMNS)
    missing = sorted(required - set(source.columns))
    if missing:
        raise ValueError(f"snapshot matrix missing required columns: {missing}")
    features = tuple(feature_columns)
    companion_features = _companion_feature_columns(features)
    keep_cols = []
    seen: set[str] = set()
    for col in [
        *SNAPSHOT_BASE_ID_COLUMNS,
        "commodity",
        "commodity_group",
        "wasde_commodity",
        "wasde_origin",
        "source_release_count_visible",
        *features,
        *companion_features,
    ]:
        if col in source.columns and col not in seen:
            keep_cols.append(col)
            seen.add(col)
    base = source[keep_cols].drop_duplicates(SNAPSHOT_BASE_ID_COLUMNS).copy()
    return base.sort_values(SNAPSHOT_BASE_ID_COLUMNS).reset_index(drop=True)


def _build_prior_index_cache(base: pd.DataFrame) -> dict[tuple[str, int], np.ndarray]:
    """Return prior row positions by grouping and row position.

    The cache is feature-agnostic and enforces ``as_of_date < current_date`` so
    rows from the same release date never enter one another's history.
    """
    cache: dict[tuple[str, int], np.ndarray] = {}
    dates = pd.to_datetime(base["as_of_date"], errors="coerce")
    for grouping_name, grouping_cols in ROLLING_GROUPINGS:
        if not set(grouping_cols).issubset(base.columns):
            continue
        for _, group in base.groupby(list(grouping_cols), dropna=False, sort=False):
            positions = group.index.to_numpy(dtype=int)
            group_dates = dates.loc[positions].to_numpy()
            for pos, current_date in zip(positions, group_dates, strict=False):
                prior_positions = positions[group_dates < current_date]
                cache[(grouping_name, int(pos))] = prior_positions.astype(int)
    return cache


def _prior_history(
    base: pd.DataFrame,
    row: pd.Series,
    feature: str,
    *,
    min_prior_observations: int,
    require_std: bool,
    prior_index_cache: dict[tuple[str, int], np.ndarray],
    row_pos: int,
) -> tuple[pd.Series, str, str]:
    for grouping_name, grouping_cols in ROLLING_GROUPINGS:
        if not set(grouping_cols).issubset(base.columns):
            continue
        prior_positions = prior_index_cache.get((grouping_name, int(row_pos)))
        if prior_positions is None or len(prior_positions) == 0:
            continue
        history = pd.to_numeric(base.loc[prior_positions, feature], errors="coerce").dropna()
        if len(history) < int(min_prior_observations):
            continue
        if require_std:
            std = float(history.std(ddof=0))
            if not np.isfinite(std) or std == 0.0:
                return history, grouping_name, "zero_prior_std"
        return history, grouping_name, ""
    return pd.Series(dtype=float), "", "insufficient_prior_history"


def _zscore(value: float, history: pd.Series) -> float:
    prior = pd.to_numeric(history, errors="coerce").dropna()
    if len(prior) >= ROBUST_Z_MIN_HISTORY:
        lower = float(prior.quantile(0.05))
        upper = float(prior.quantile(0.95))
        prior = prior.clip(lower=lower, upper=upper)
    std = float(prior.std(ddof=0))
    if not np.isfinite(std) or std == 0.0:
        return np.nan
    return _clip_score(float((value - float(prior.mean())) / std))


def _percentile(value: float, history: pd.Series) -> float:
    prior = pd.to_numeric(history, errors="coerce").dropna()
    if prior.empty:
        return np.nan
    return float((prior <= value).mean())


def _component_stress_value(row: pd.Series) -> float:
    value = _safe_float(row.get("score_value"))
    if not np.isfinite(value):
        return np.nan
    if str(row.get("detector_id")) == "stage_level_percentile":
        return float(np.clip(value, 0.0, 1.0))
    clipped = float(np.clip(value, -8.0, 8.0))
    return float(1.0 / (1.0 + np.exp(-clipped)))


def _feature_for_transform(attribute: str, transform: str) -> str:
    return f"wasde_{attribute}_{transform}"


def _revision_relative_magnitude(value: float, latest: float) -> float:
    if not np.isfinite(value):
        return np.nan
    denominator = abs(latest) if np.isfinite(latest) and abs(latest) > 0 else 1.0
    return float(abs(value) / denominator)


def _magnitude_filtered_streak_score(
    row: pd.Series,
    *,
    attribute: str,
    direction: str,
    streak_value: float,
) -> tuple[float, str]:
    oriented_streak = _orient_z(streak_value, direction)
    if not np.isfinite(oriented_streak):
        return np.nan, "invalid_streak"
    if oriented_streak < REVISION_MIN_STRESS_STREAK:
        return np.nan, "revision_streak_below_minimum"

    latest = _safe_float(row.get(_feature_for_transform(attribute, "latest")))
    mom_revision = _safe_float(row.get(_feature_for_transform(attribute, "mom_revision")))
    cumulative_revision = _safe_float(
        row.get(_feature_for_transform(attribute, "revision_since_first"))
    )
    mom_stress = _orient_z(mom_revision, direction)
    cumulative_stress = _orient_z(cumulative_revision, direction)
    mom_magnitude = _revision_relative_magnitude(mom_revision, latest)
    cumulative_magnitude = _revision_relative_magnitude(cumulative_revision, latest)

    mom_confirmed = (
        np.isfinite(mom_stress)
        and mom_stress > 0
        and np.isfinite(mom_magnitude)
        and mom_magnitude >= REVISION_MIN_RELATIVE_MOM_CHANGE
    )
    cumulative_confirmed = (
        np.isfinite(cumulative_stress)
        and cumulative_stress > 0
        and np.isfinite(cumulative_magnitude)
        and cumulative_magnitude >= REVISION_MIN_RELATIVE_CUMULATIVE_CHANGE
    )
    if not mom_confirmed and not cumulative_confirmed:
        return np.nan, "revision_streak_magnitude_filter"
    return _clip_score(oriented_streak, cap=12.0), ""


def _score_feature_row(
    base: pd.DataFrame,
    row_pos: int,
    row: pd.Series,
    feature: str,
    *,
    min_prior_observations: int,
    prior_index_cache: dict[tuple[str, int], np.ndarray],
) -> list[dict[str, object]]:
    spec = _extract_feature_spec(feature)
    if spec is None:
        return []
    attribute, transform = spec
    direction = _stress_direction(attribute)
    if direction == "context_dependent":
        return []

    value = _safe_float(row.get(feature))
    base_payload = {
        "dataset_key": row["dataset_key"],
        "contract_key": row["contract_key"],
        "origin_key": row["origin_key"],
        "target_market_year": row["target_market_year"],
        "as_of_date": row["as_of_date"],
        "snapshot_stage": row["snapshot_stage"],
        "source_feature": feature,
        "source_attribute": attribute,
        "source_transform": transform,
        "raw_value": value,
        "stress_direction": direction,
        "component_count": np.nan,
    }
    if not np.isfinite(value):
        return [{
            **base_payload,
            "detector_id": "missing_input",
            "score_name": f"{feature}_missing_input",
            "score_value": np.nan,
            "prior_observation_count": 0,
            "normalization_group_used": "",
            "score_null_reason": "missing_value",
        }]

    rows: list[dict[str, object]] = []
    if transform == "level":
        history, group_name, reason = _prior_history(
            base,
            row,
            feature,
            min_prior_observations=min_prior_observations,
            require_std=True,
            prior_index_cache=prior_index_cache,
            row_pos=row_pos,
        )
        raw_z = _zscore(value, history) if not reason else np.nan
        score = _orient_z(raw_z, direction)
        rows.append({
            **base_payload,
            "detector_id": "stage_level_z",
            "score_name": f"{feature}_stage_z",
            "score_value": score,
            "prior_observation_count": int(len(history)),
            "normalization_group_used": group_name,
            "score_null_reason": "" if np.isfinite(score) else reason or "invalid_zscore",
        })

        history, group_name, reason = _prior_history(
            base,
            row,
            feature,
            min_prior_observations=min_prior_observations,
            require_std=False,
            prior_index_cache=prior_index_cache,
            row_pos=row_pos,
        )
        pct = _percentile(value, history) if not reason else np.nan
        score = _orient_percentile(pct, direction)
        rows.append({
            **base_payload,
            "detector_id": "stage_level_percentile",
            "score_name": f"{feature}_stress_percentile",
            "score_value": score,
            "prior_observation_count": int(len(history)),
            "normalization_group_used": group_name,
            "score_null_reason": "" if np.isfinite(score) else reason or "invalid_percentile",
        })
    elif transform in {"mom_revision", "revision_since_first"}:
        history, group_name, reason = _prior_history(
            base,
            row,
            feature,
            min_prior_observations=min_prior_observations,
            require_std=True,
            prior_index_cache=prior_index_cache,
            row_pos=row_pos,
        )
        raw_z = _zscore(value, history) if not reason else np.nan
        score = _orient_z(raw_z, direction)
        rows.append({
            **base_payload,
            "detector_id": "revision_shock",
            "score_name": f"{feature}_shock_z",
            "score_value": score,
            "prior_observation_count": int(len(history)),
            "normalization_group_used": group_name,
            "score_null_reason": "" if np.isfinite(score) else reason or "invalid_zscore",
        })
    elif transform == "revision_streak":
        score, reason = _magnitude_filtered_streak_score(
            row,
            attribute=attribute,
            direction=direction,
            streak_value=value,
        )
        rows.append({
            **base_payload,
            "detector_id": "revision_streak",
            "score_name": f"{feature}_stress_streak",
            "score_value": score,
            "prior_observation_count": 0,
            "normalization_group_used": "not_normalized",
            "score_null_reason": "" if np.isfinite(score) else reason,
        })
    return rows


def _expand_scores_to_targets(matrix: pd.DataFrame, snapshot_scores: pd.DataFrame) -> pd.DataFrame:
    source = _normalize_frame(matrix)
    target_cols = [*SNAPSHOT_BASE_ID_COLUMNS, "target_key"]
    target_rows = source[target_cols].drop_duplicates().copy()
    if snapshot_scores.empty:
        return pd.DataFrame(columns=SCORE_COLUMNS)
    expanded = target_rows.merge(
        snapshot_scores,
        on=SNAPSHOT_BASE_ID_COLUMNS,
        how="inner",
        validate="many_to_many",
    )
    return expanded[SCORE_COLUMNS].sort_values(
        SNAPSHOT_SCORE_ID_COLUMNS + ["detector_id", "score_name", "source_feature"]
    ).reset_index(drop=True)


def _build_composite_scores(
    scores: pd.DataFrame,
    *,
    min_components: int,
) -> pd.DataFrame:
    usable = scores.loc[
        scores["detector_id"].isin({"stage_level_percentile", "revision_shock", "revision_streak"})
        & scores["source_attribute"].isin(COMPOSITE_ATTRIBUTES)
        & pd.to_numeric(scores["score_value"], errors="coerce").notna()
    ].copy()
    if usable.empty:
        return pd.DataFrame(columns=SCORE_COLUMNS)
    usable["score_value"] = pd.to_numeric(usable["score_value"], errors="coerce")
    usable["_component_stress_value"] = usable.apply(_component_stress_value, axis=1)
    rows: list[dict[str, object]] = []
    for keys, group in usable.groupby(SNAPSHOT_SCORE_ID_COLUMNS, dropna=False, sort=True):
        values = dict(zip(SNAPSHOT_SCORE_ID_COLUMNS, keys, strict=False))
        component_count = int(group["_component_stress_value"].notna().sum())
        if component_count < int(min_components):
            score_value = np.nan
            reason = "insufficient_components"
        else:
            score_value = float(group["_component_stress_value"].mean())
            reason = ""
        rows.append({
            **values,
            "detector_id": "composite_balance_sheet_stress",
            "score_name": "wasde_composite_balance_sheet_stress",
            "source_feature": "multiple",
            "source_attribute": "balance_sheet",
            "source_transform": "equal_weight_components",
            "raw_value": np.nan,
            "score_value": score_value,
            "stress_direction": "higher_is_stress",
            "prior_observation_count": int(
                pd.to_numeric(group["prior_observation_count"], errors="coerce").dropna().min()
            ) if component_count else 0,
            "normalization_group_used": ",".join(
                sorted(set(group["normalization_group_used"].dropna().astype(str)))
            ),
            "component_count": component_count,
            "score_null_reason": reason,
        })
    return pd.DataFrame(rows, columns=SCORE_COLUMNS)


def build_score_coverage_report(scores: pd.DataFrame) -> pd.DataFrame:
    """Summarize non-null score coverage by detector and score."""
    columns = [
        "detector_id",
        "score_name",
        "source_attribute",
        "row_count",
        "non_null_count",
        "non_null_rate",
        "target_count",
        "origin_count",
        "stage_count",
        "score_min",
        "score_median",
        "score_max",
        "null_reasons",
    ]
    if scores.empty:
        return pd.DataFrame(columns=columns)
    rows: list[dict[str, object]] = []
    for (detector_id, score_name, attr), group in scores.groupby(
        ["detector_id", "score_name", "source_attribute"], dropna=False, sort=True
    ):
        values = pd.to_numeric(group["score_value"], errors="coerce")
        finite = values.dropna()
        null_reasons = sorted(
            reason
            for reason in group.loc[values.isna(), "score_null_reason"].dropna().astype(str).unique()
            if reason
        )
        rows.append({
            "detector_id": str(detector_id),
            "score_name": str(score_name),
            "source_attribute": str(attr),
            "row_count": int(len(group)),
            "non_null_count": int(values.notna().sum()),
            "non_null_rate": float(values.notna().mean()) if len(values) else 0.0,
            "target_count": int(group["target_key"].nunique()),
            "origin_count": int(group["origin_key"].nunique()),
            "stage_count": int(group["snapshot_stage"].nunique()),
            "score_min": _safe_float(finite.min()) if not finite.empty else None,
            "score_median": _safe_float(finite.median()) if not finite.empty else None,
            "score_max": _safe_float(finite.max()) if not finite.empty else None,
            "null_reasons": ",".join(null_reasons),
        })
    return pd.DataFrame(rows, columns=columns).sort_values(
        ["detector_id", "source_attribute", "score_name"]
    ).reset_index(drop=True)


def build_wasde_snapshot_anomaly_scores(
    matrix: pd.DataFrame,
    *,
    feature_columns: Iterable[str] | None = None,
    min_prior_observations: int = 10,
    min_composite_components: int = 2,
) -> WasdeSnapshotAnomalyScoreResult:
    """Build transparent rolling prior-only anomaly scores for a matrix."""
    source = _normalize_frame(matrix)
    features = tuple(feature_columns or _numeric_feature_columns(source))
    base = _unique_snapshot_frame(source, features)
    prior_index_cache = _build_prior_index_cache(base)
    score_rows: list[dict[str, object]] = []
    for row_pos, row in base.iterrows():
        for feature in features:
            score_rows.extend(
                _score_feature_row(
                    base,
                    int(row_pos),
                    row,
                    feature,
                    min_prior_observations=min_prior_observations,
                    prior_index_cache=prior_index_cache,
                )
            )
    snapshot_scores = pd.DataFrame(score_rows)
    if snapshot_scores.empty:
        expanded = pd.DataFrame(columns=SCORE_COLUMNS)
    else:
        expanded = _expand_scores_to_targets(source, snapshot_scores)
    composite = _build_composite_scores(
        expanded,
        min_components=min_composite_components,
    )
    scores = (
        pd.concat([expanded, composite], ignore_index=True)
        if not composite.empty else expanded.copy()
    )
    if not scores.empty:
        scores = scores[SCORE_COLUMNS].sort_values(
            SNAPSHOT_SCORE_ID_COLUMNS + ["detector_id", "score_name", "source_feature"]
        ).reset_index(drop=True)
    coverage = build_score_coverage_report(scores)
    non_null = pd.to_numeric(scores.get("score_value", pd.Series(dtype=float)), errors="coerce")
    detector_counts = (
        coverage.groupby("detector_id")["non_null_count"].sum().astype(int).to_dict()
        if not coverage.empty else {}
    )
    status = "go" if int(non_null.notna().sum()) > 0 else "blocked"
    report = {
        "phase": "wasde_snapshot_anomaly_phase1_scores",
        "status": status,
        "input": {
            "row_count": int(len(source)),
            "unique_snapshot_count": int(len(base)),
            "target_count": int(source["target_key"].nunique()) if "target_key" in source.columns else 0,
            "annual_group_count": int(source[TARGET_GROUP_KEY].drop_duplicates().shape[0])
            if set(TARGET_GROUP_KEY).issubset(source.columns) else 0,
        },
        "parameters": {
            "min_prior_observations": int(min_prior_observations),
            "min_composite_components": int(min_composite_components),
            "feature_count": int(len(features)),
        },
        "scores": {
            "row_count": int(len(scores)),
            "non_null_score_count": int(non_null.notna().sum()),
            "non_null_score_rate": float(non_null.notna().mean()) if len(non_null) else 0.0,
            "detector_non_null_counts": {str(k): int(v) for k, v in detector_counts.items()},
        },
        "phase2_recommendation": {
            "proceed": status == "go",
            "notes": [
                "Evaluate alert thresholds using grouped annual outcomes only.",
                "Compare transparent detectors against current-level and prior-year baselines.",
                "Run false-negative and false-positive RCA before trying opaque ML detectors.",
            ],
        },
    }
    return WasdeSnapshotAnomalyScoreResult(
        scores=scores,
        score_coverage=coverage,
        report=report,
    )


def score_name_to_attribute(score_name: str) -> str:
    """Best-effort helper for debugging score names."""
    match = re.match(r"wasde_(.*?)(?:_latest|_estimate|_mom_revision|_revision_since_first|_consecutive_revision_count)", score_name)
    return match.group(1) if match else ""
