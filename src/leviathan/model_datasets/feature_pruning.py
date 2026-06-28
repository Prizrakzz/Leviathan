"""Model-ready feature pruning policies shared by builders and trainers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pandas as pd

DENSE_WEATHER_FEATURE_SETS = {
    "inseason_weather_dense",
    "preseason_physical_plus_weather_dense",
}
DENSE_WEATHER_PREFIX = "weather_dense_"
DENSE_WEATHER_CORE_MIN_NON_NULL_RATE = 0.20
DENSE_WEATHER_REVIEW_MIN_NON_NULL_RATE = 0.50


@dataclass(frozen=True)
class FeaturePruningResult:
    """Result of pruning model-ready features at the training-row grain."""

    kept_features: list[str]
    dropped_features: list[str]
    review_features: list[str]
    row_count: int


def _selected_set_ids(feature_set_ids: Iterable[str] | None) -> set[str]:
    return {str(item) for item in (feature_set_ids or ()) if str(item).strip()}


def _trainable_frame(matrix: pd.DataFrame) -> pd.DataFrame:
    frame = matrix.copy()
    if "is_trainable" in frame.columns:
        frame = frame.loc[frame["is_trainable"].fillna(False).astype(bool)].copy()
    if "target_value" in frame.columns:
        frame = frame.loc[frame["target_value"].notna()].copy()
    return frame


def prune_model_ready_features(
    matrix: pd.DataFrame,
    feature_cols: Iterable[str],
    *,
    selected_feature_sets: Iterable[str] | None = None,
    min_dense_weather_non_null_rate: float = DENSE_WEATHER_CORE_MIN_NON_NULL_RATE,
    review_dense_weather_non_null_rate: float = DENSE_WEATHER_REVIEW_MIN_NON_NULL_RATE,
) -> FeaturePruningResult:
    """Drop ultra-sparse dense-weather features using trainable model rows.

    Feature-set membership is resolved from the long gold catalog, whose
    non-null rates can differ from the target-specific model-ready training
    matrix after joins and trainability filters.  This helper applies the
    final ML-facing gate only to dense weather feature sets.
    """

    selected_sets = _selected_set_ids(selected_feature_sets)
    features = sorted(str(feature) for feature in feature_cols)
    if not (selected_sets & DENSE_WEATHER_FEATURE_SETS):
        return FeaturePruningResult(features, [], [], 0)

    frame = _trainable_frame(matrix)
    row_count = int(len(frame))
    if row_count == 0:
        return FeaturePruningResult(features, [], [], row_count)

    kept: list[str] = []
    dropped: list[str] = []
    review: list[str] = []
    for feature in features:
        if feature not in frame.columns:
            continue
        if not feature.startswith(DENSE_WEATHER_PREFIX):
            kept.append(feature)
            continue
        non_null_rate = float(frame[feature].notna().sum() / row_count)
        if non_null_rate < min_dense_weather_non_null_rate:
            dropped.append(feature)
        else:
            kept.append(feature)
            if non_null_rate < review_dense_weather_non_null_rate:
                review.append(feature)

    return FeaturePruningResult(
        kept_features=sorted(kept),
        dropped_features=sorted(dropped),
        review_features=sorted(review),
        row_count=row_count,
    )
