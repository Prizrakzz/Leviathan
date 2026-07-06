"""Fold-safe target and baseline construction."""

from __future__ import annotations

import numpy as np
import pandas as pd

from leviathan.model_datasets.schema_columns import BASELINE_COLUMNS, TARGET_COLUMNS
from leviathan.model_datasets.targets import TargetDefinition


def _finite(value: object) -> bool:
    try:
        return bool(np.isfinite(float(value)))
    except Exception:  # noqa: BLE001
        return False


def _pct_deviation(value: float | None, baseline: float | None) -> float:
    if not _finite(value) or not _finite(baseline):
        return np.nan
    baseline_f = float(baseline)
    if baseline_f == 0:
        return np.nan
    return (float(value) - baseline_f) / abs(baseline_f)


def _linear_prediction(years: np.ndarray, values: np.ndarray, year: float) -> float:
    if len(years) < 2 or len(np.unique(years)) < 2:
        return np.nan
    coeffs = np.polyfit(years.astype(float), values.astype(float), 1)
    return float(np.polyval(coeffs, float(year)))


def build_trailing_anomaly_targets(
    matrix: pd.DataFrame,
    definition: TargetDefinition,
    *,
    commodity: str,
    source_dataset_version: str,
) -> pd.DataFrame:
    """Build a target panel using only prior years for each row's baseline."""
    required = {"country", "crop_year", definition.label_column}
    missing = required - set(matrix.columns)
    if missing:
        raise ValueError(
            f"{commodity}/{definition.target_key}: missing required columns {sorted(missing)}"
        )
    if definition.target_type != "trailing_trend_pct_anomaly":
        raise ValueError(f"unsupported target_type: {definition.target_type}")

    base = matrix[["country", "crop_year", definition.label_column]].copy()
    base = base.rename(columns={definition.label_column: "actual_value"})
    base["crop_year"] = pd.to_numeric(base["crop_year"], errors="coerce")
    base["actual_value"] = pd.to_numeric(base["actual_value"], errors="coerce")
    base = base.sort_values(["country", "crop_year"]).reset_index(drop=True)

    rows: list[dict] = []
    for country, group in base.groupby("country", sort=False):
        history = (
            group[["crop_year", "actual_value"]]
            .dropna(subset=["crop_year", "actual_value"])
            .sort_values("crop_year")
        )
        by_year = {
            int(row.crop_year): float(row.actual_value) for row in history.itertuples(index=False)
        }

        for row in group.itertuples(index=False):
            crop_year = int(row.crop_year) if _finite(row.crop_year) else None
            actual = float(row.actual_value) if _finite(row.actual_value) else np.nan
            prior = (
                history.loc[history["crop_year"] < crop_year]
                if crop_year is not None
                else history.iloc[0:0]
            )
            history_years = int(len(prior))
            prior_year_value = by_year.get(crop_year - 1) if crop_year is not None else np.nan
            trailing_mean = float(prior["actual_value"].mean()) if history_years > 0 else np.nan
            trend_prediction = (
                _linear_prediction(
                    prior["crop_year"].to_numpy(dtype=float),
                    prior["actual_value"].to_numpy(dtype=float),
                    float(crop_year),
                )
                if history_years >= definition.min_history_years and crop_year is not None
                else np.nan
            )
            target_value = _pct_deviation(actual, trend_prediction)
            is_trainable = bool(
                crop_year is not None
                and _finite(actual)
                and history_years >= definition.min_history_years
                and _finite(trend_prediction)
                and _finite(target_value)
            )
            if not _finite(actual):
                excluded_reason = "missing_actual"
            elif history_years < definition.min_history_years:
                excluded_reason = "insufficient_history"
            elif not _finite(trend_prediction):
                excluded_reason = "missing_trend"
            elif not _finite(target_value):
                excluded_reason = "invalid_target"
            else:
                excluded_reason = ""

            rows.append(
                {
                    "source_dataset_version": source_dataset_version,
                    "dataset_key": definition.dataset_key,
                    "commodity": commodity,
                    "target_key": definition.target_key,
                    "target_title": definition.title,
                    "target_unit": definition.target_unit,
                    "country": str(country),
                    "crop_year": crop_year,
                    "actual_value": actual,
                    "target_value": target_value,
                    "trend_prediction": trend_prediction,
                    "prior_year_value": prior_year_value,
                    "trailing_mean_prediction": trailing_mean,
                    "zero_anomaly_baseline": 0.0,
                    "prior_year_anomaly_baseline": _pct_deviation(
                        prior_year_value, trend_prediction
                    ),
                    "trailing_mean_anomaly_baseline": _pct_deviation(
                        trailing_mean, trend_prediction
                    ),
                    "trailing_trend_anomaly_baseline": 0.0,
                    "history_years": history_years,
                    "is_trainable": is_trainable,
                    "excluded_reason": excluded_reason,
                }
            )

    return pd.DataFrame(rows, columns=TARGET_COLUMNS)


def compute_baseline_metrics(
    target_df: pd.DataFrame,
    *,
    dataset_key: str,
    commodity: str,
    target_key: str,
    baseline_names: tuple[str, ...],
) -> pd.DataFrame:
    """Compute simple baseline metrics in target space."""
    rows = []
    trainable = target_df.loc[
        target_df["is_trainable"].fillna(False).astype(bool) & target_df["target_value"].notna()
    ].copy()
    for baseline_name in baseline_names:
        column = BASELINE_COLUMNS.get(baseline_name)
        if column is None or column not in trainable.columns:
            continue
        valid = trainable.loc[trainable[column].notna(), ["target_value", column]]
        if valid.empty:
            rows.append(
                {
                    "dataset_key": dataset_key,
                    "commodity": commodity,
                    "target_key": target_key,
                    "baseline_name": baseline_name,
                    "n_rows": 0,
                    "rmse": np.nan,
                    "mae": np.nan,
                    "directional_accuracy": np.nan,
                }
            )
            continue
        residual = valid["target_value"].astype(float) - valid[column].astype(float)
        actual_sign = np.sign(valid["target_value"].astype(float))
        pred_sign = np.sign(valid[column].astype(float))
        rows.append(
            {
                "dataset_key": dataset_key,
                "commodity": commodity,
                "target_key": target_key,
                "baseline_name": baseline_name,
                "n_rows": int(len(valid)),
                "rmse": float(np.sqrt((residual**2).mean())),
                "mae": float(residual.abs().mean()),
                "directional_accuracy": float((actual_sign == pred_sign).mean()),
            }
        )
    return pd.DataFrame(rows)
