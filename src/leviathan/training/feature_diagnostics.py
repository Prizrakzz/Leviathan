"""Diagnostics for model-ready feature matrices.

These checks are intentionally separate from training.  They answer whether a
feature set is worth modeling before another sweep: coverage, missingness,
target-tail sample size, high correlations, and candidate recall summaries.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from leviathan.training.certification_summary import flatten_certification_report


METADATA_COLUMNS = [
    "feature_family",
    "semantic_scope",
    "policy",
    "mechanism",
    "sources",
    "source_cadence",
    "empirical_scope",
    "groups",
    "target_compatibility",
    "missingness_policy",
    "min_lag_days",
]


@dataclass(frozen=True)
class FeatureDiagnosticsArtifacts:
    """DataFrames plus JSON summary produced by a diagnostics run."""

    feature_inventory: pd.DataFrame
    missingness_by_year: pd.DataFrame
    missingness_by_country: pd.DataFrame
    missingness_target_association: pd.DataFrame
    target_tail_summary: pd.DataFrame
    target_tail_by_country: pd.DataFrame
    target_tail_by_year: pd.DataFrame
    correlation_pairs: pd.DataFrame
    preprocessing_audit: dict[str, Any]
    candidate_recall_audit: pd.DataFrame


def _feature_metadata(membership: pd.DataFrame | None) -> pd.DataFrame:
    if membership is None or membership.empty or "feature" not in membership.columns:
        return pd.DataFrame(columns=["feature", *METADATA_COLUMNS])
    cols = ["feature", *[col for col in METADATA_COLUMNS if col in membership.columns]]
    meta = membership[cols].copy()
    meta["feature"] = meta["feature"].astype(str)
    return meta.drop_duplicates("feature", keep="first")


def _numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _safe_float(value: object) -> float:
    if value is None:
        return float("nan")
    try:
        out = float(value)
    except (TypeError, ValueError):
        return float("nan")
    return out if np.isfinite(out) else float("nan")


def _json_safe(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return None if not np.isfinite(value) else value
    if isinstance(value, np.generic):
        return _json_safe(value.item())
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return str(value)


def build_feature_inventory(
    train_df: pd.DataFrame,
    feature_cols: list[str],
    *,
    membership: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Return one row per selected feature with coverage and value stats."""
    rows: list[dict[str, Any]] = []
    n_rows = int(len(train_df))
    for feature in feature_cols:
        if feature not in train_df.columns:
            rows.append({
                "feature": feature,
                "present_in_matrix": False,
                "row_count": n_rows,
                "non_null_count": 0,
                "null_count": n_rows,
                "non_null_rate": 0.0 if n_rows else float("nan"),
                "null_rate": 1.0 if n_rows else float("nan"),
                "dtype": "",
                "is_numeric": False,
                "unique_non_null_count": 0,
                "is_constant": False,
                "is_all_missing": bool(n_rows),
            })
            continue

        series = train_df[feature]
        numeric = _numeric(series)
        non_null = int(series.notna().sum())
        numeric_non_null = int(numeric.notna().sum())
        unique = int(series.dropna().nunique())
        numeric_feature = bool(non_null > 0 and numeric_non_null == non_null)
        row = {
            "feature": feature,
            "present_in_matrix": True,
            "row_count": n_rows,
            "non_null_count": non_null,
            "null_count": int(n_rows - non_null),
            "non_null_rate": float(non_null / n_rows) if n_rows else float("nan"),
            "null_rate": float(1.0 - (non_null / n_rows)) if n_rows else float("nan"),
            "dtype": str(series.dtype),
            "is_numeric": numeric_feature,
            "unique_non_null_count": unique,
            "is_constant": bool(unique <= 1 and non_null > 0),
            "is_all_missing": bool(non_null == 0 and n_rows > 0),
            "mean": _safe_float(numeric.mean()) if numeric_feature else float("nan"),
            "std": _safe_float(numeric.std(ddof=0)) if numeric_feature else float("nan"),
            "min": _safe_float(numeric.min()) if numeric_feature else float("nan"),
            "p01": _safe_float(numeric.quantile(0.01)) if numeric_feature else float("nan"),
            "p05": _safe_float(numeric.quantile(0.05)) if numeric_feature else float("nan"),
            "median": _safe_float(numeric.median()) if numeric_feature else float("nan"),
            "p95": _safe_float(numeric.quantile(0.95)) if numeric_feature else float("nan"),
            "p99": _safe_float(numeric.quantile(0.99)) if numeric_feature else float("nan"),
            "max": _safe_float(numeric.max()) if numeric_feature else float("nan"),
        }
        rows.append(row)

    inventory = pd.DataFrame(rows)
    meta = _feature_metadata(membership)
    if not meta.empty:
        inventory = inventory.merge(meta, on="feature", how="left", validate="one_to_one")
    return inventory.sort_values(["null_rate", "feature"], ascending=[False, True]).reset_index(drop=True)


def _missingness_by_group(
    train_df: pd.DataFrame,
    feature_cols: list[str],
    group_col: str,
) -> pd.DataFrame:
    if group_col not in train_df.columns:
        return pd.DataFrame(columns=["feature", group_col, "row_count", "null_count", "null_rate"])
    rows: list[dict[str, Any]] = []
    for feature in feature_cols:
        if feature not in train_df.columns:
            continue
        for group_value, group in train_df.groupby(group_col, dropna=False):
            row_count = int(len(group))
            null_count = int(group[feature].isna().sum())
            rows.append({
                "feature": feature,
                group_col: group_value,
                "row_count": row_count,
                "null_count": null_count,
                "non_null_count": int(row_count - null_count),
                "null_rate": float(null_count / row_count) if row_count else float("nan"),
            })
    return pd.DataFrame(rows).sort_values(["feature", group_col]).reset_index(drop=True)


def build_missingness_by_year(train_df: pd.DataFrame, feature_cols: list[str]) -> pd.DataFrame:
    """Return feature missingness by crop year."""
    return _missingness_by_group(train_df, feature_cols, "crop_year")


def build_missingness_by_country(train_df: pd.DataFrame, feature_cols: list[str]) -> pd.DataFrame:
    """Return feature missingness by country/origin."""
    return _missingness_by_group(train_df, feature_cols, "country")


def build_missingness_target_association(
    train_df: pd.DataFrame,
    feature_cols: list[str],
    *,
    target_col: str,
    bad_quantile: float = 0.2,
) -> pd.DataFrame:
    """Measure whether missingness correlates with target level or tail events."""
    if target_col not in train_df.columns:
        raise ValueError(f"missing target column: {target_col}")
    target = _numeric(train_df[target_col])
    threshold = float(target.quantile(bad_quantile)) if target.notna().any() else float("nan")
    rows: list[dict[str, Any]] = []
    for feature in feature_cols:
        if feature not in train_df.columns:
            continue
        missing = train_df[feature].isna()
        present = ~missing
        missing_n = int(missing.sum())
        present_n = int(present.sum())
        missing_mean = _safe_float(target[missing].mean()) if missing_n else float("nan")
        present_mean = _safe_float(target[present].mean()) if present_n else float("nan")
        missing_bad = (
            float((target[missing] <= threshold).mean())
            if missing_n and np.isfinite(threshold) else float("nan")
        )
        present_bad = (
            float((target[present] <= threshold).mean())
            if present_n and np.isfinite(threshold) else float("nan")
        )
        rows.append({
            "feature": feature,
            "missing_count": missing_n,
            "present_count": present_n,
            "missing_rate": float(missing_n / len(train_df)) if len(train_df) else float("nan"),
            "missing_target_mean": missing_mean,
            "present_target_mean": present_mean,
            "missing_minus_present_target_mean": (
                missing_mean - present_mean
                if np.isfinite(missing_mean) and np.isfinite(present_mean)
                else float("nan")
            ),
            "bad_quantile": bad_quantile,
            "bad_year_threshold_actual": threshold,
            "missing_bad_year_rate": missing_bad,
            "present_bad_year_rate": present_bad,
            "missing_minus_present_bad_year_rate": (
                missing_bad - present_bad
                if np.isfinite(missing_bad) and np.isfinite(present_bad)
                else float("nan")
            ),
        })
    return pd.DataFrame(rows).sort_values(
        ["missing_rate", "feature"], ascending=[False, True]
    ).reset_index(drop=True)


def _identity_count(df: pd.DataFrame) -> int:
    cols = [col for col in ("country", "crop_year", "snapshot_stage", "as_of_date") if col in df.columns]
    return int(df.drop_duplicates(cols).shape[0]) if cols else int(len(df))


def _event_rows(
    train_df: pd.DataFrame,
    target_col: str,
    *,
    name: str,
    threshold: float,
) -> tuple[dict[str, Any], pd.DataFrame]:
    target = _numeric(train_df[target_col])
    event = target <= threshold
    subset = train_df.loc[event].copy()
    total = int(target.notna().sum())
    row = {
        "event_definition": name,
        "threshold": threshold,
        "row_count": int(len(train_df)),
        "target_non_null_count": total,
        "event_count": int(event.sum()),
        "event_rate": float(event.sum() / total) if total else float("nan"),
        "independent_country_years": _identity_count(subset),
        "country_count": int(subset["country"].nunique()) if "country" in subset.columns else 0,
        "year_count": int(subset["crop_year"].nunique()) if "crop_year" in subset.columns else 0,
        "target_min": _safe_float(target.min()),
        "target_median": _safe_float(target.median()),
        "target_max": _safe_float(target.max()),
    }
    return row, subset


def build_target_tail_reports(
    train_df: pd.DataFrame,
    *,
    target_col: str,
    bad_quantile: float = 0.2,
    thresholds: tuple[float, ...] = (-0.05, -0.10, -0.15),
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return target tail imbalance summaries overall, by country, and by year."""
    if target_col not in train_df.columns:
        raise ValueError(f"missing target column: {target_col}")
    target = _numeric(train_df[target_col])
    quantile_threshold = (
        float(target.quantile(bad_quantile)) if target.notna().any() else float("nan")
    )
    event_specs = [(f"bottom_quantile_{bad_quantile:.2f}", quantile_threshold)]
    event_specs.extend((f"target_le_{value:g}", float(value)) for value in thresholds)

    summary_rows: list[dict[str, Any]] = []
    country_rows: list[dict[str, Any]] = []
    year_rows: list[dict[str, Any]] = []
    for name, threshold in event_specs:
        if not np.isfinite(threshold):
            continue
        row, _ = _event_rows(train_df, target_col, name=name, threshold=threshold)
        summary_rows.append(row)
        event = target <= threshold
        if "country" in train_df.columns:
            for country, group in train_df.assign(_event=event).groupby("country", dropna=False):
                n = int(len(group))
                country_rows.append({
                    "event_definition": name,
                    "country": country,
                    "row_count": n,
                    "event_count": int(group["_event"].sum()),
                    "event_rate": float(group["_event"].mean()) if n else float("nan"),
                })
        if "crop_year" in train_df.columns:
            for year, group in train_df.assign(_event=event).groupby("crop_year", dropna=False):
                n = int(len(group))
                year_rows.append({
                    "event_definition": name,
                    "crop_year": year,
                    "row_count": n,
                    "event_count": int(group["_event"].sum()),
                    "event_rate": float(group["_event"].mean()) if n else float("nan"),
                })

    return (
        pd.DataFrame(summary_rows),
        pd.DataFrame(country_rows),
        pd.DataFrame(year_rows),
    )


def build_correlation_pairs(
    train_df: pd.DataFrame,
    feature_cols: list[str],
    *,
    threshold: float = 0.95,
    max_pairs: int = 1000,
) -> pd.DataFrame:
    """Return highly correlated numeric feature pairs."""
    numeric_cols: list[str] = []
    numeric_series: dict[str, pd.Series] = {}
    for feature in feature_cols:
        if feature not in train_df.columns:
            continue
        numeric = _numeric(train_df[feature])
        if int(numeric.notna().sum()) < 3:
            continue
        if int(numeric.dropna().nunique()) <= 1:
            continue
        numeric_cols.append(feature)
        numeric_series[feature] = numeric

    if len(numeric_cols) < 2:
        return pd.DataFrame(columns=["feature_a", "feature_b", "correlation", "abs_correlation"])

    numeric_frame = pd.DataFrame(numeric_series, index=train_df.index)
    corr = numeric_frame[numeric_cols].corr(min_periods=3)
    rows: list[dict[str, Any]] = []
    for i, feature_a in enumerate(numeric_cols):
        for feature_b in numeric_cols[i + 1:]:
            value = corr.loc[feature_a, feature_b]
            if pd.notna(value) and abs(float(value)) >= threshold:
                rows.append({
                    "feature_a": feature_a,
                    "feature_b": feature_b,
                    "correlation": float(value),
                    "abs_correlation": abs(float(value)),
                })
    if not rows:
        return pd.DataFrame(
            columns=["feature_a", "feature_b", "correlation", "abs_correlation"]
        )
    return pd.DataFrame(rows).sort_values(
        ["abs_correlation", "feature_a", "feature_b"],
        ascending=[False, True, True],
    ).head(max_pairs).reset_index(drop=True)


def build_preprocessing_audit(
    train_df: pd.DataFrame,
    feature_cols: list[str],
    inventory: pd.DataFrame,
    *,
    high_null_threshold: float = 0.5,
) -> dict[str, Any]:
    """Return guidance on scaling, encoding, and missing-value handling."""
    non_numeric = (
        inventory.loc[
            (~inventory["is_numeric"].fillna(False))
            & (~inventory["is_all_missing"].fillna(False)),
            "feature",
        ].astype(str).tolist()
        if not inventory.empty else []
    )
    all_missing = (
        inventory.loc[inventory["is_all_missing"].fillna(False), "feature"].astype(str).tolist()
        if not inventory.empty else []
    )
    constants = (
        inventory.loc[inventory["is_constant"].fillna(False), "feature"].astype(str).tolist()
        if not inventory.empty else []
    )
    high_missing = (
        inventory.loc[
            pd.to_numeric(inventory["null_rate"], errors="coerce").fillna(0.0) >= high_null_threshold,
            "feature",
        ].astype(str).tolist()
        if not inventory.empty else []
    )
    return {
        "row_count": int(len(train_df)),
        "feature_count": int(len(feature_cols)),
        "numeric_feature_count": int(len(feature_cols) - len(non_numeric)),
        "non_numeric_features": non_numeric,
        "all_missing_features": all_missing,
        "constant_features": constants,
        "high_missing_features": high_missing,
        "high_null_threshold": high_null_threshold,
        "tree_model_scaling_policy": (
            "No StandardScaler is required for XGBoost/LightGBM; keep raw numeric "
            "scales unless a non-tree baseline is added."
        ),
        "linear_model_scaling_policy": (
            "Fit StandardScaler/encoders inside each CV training fold only. "
            "Never fit preprocessing on the full matrix before walk-forward CV."
        ),
        "missingness_policy": (
            "Tree models may consume NaN directly, but high-missing features should "
            "get missingness flags or be ablated. Forward-fill only time-series "
            "features where the last known value is point-in-time available."
        ),
        "encoding_policy": (
            "The governed feature set should resolve to numeric model inputs. "
            "Non-numeric features need explicit fold-local encoding or exclusion."
        ),
    }


def candidate_recall_audit_from_reports(
    reports: list[dict[str, Any]],
    *,
    commodity: str | None = None,
    dataset_key: str | None = None,
    target_key: str | None = None,
    feature_set_id: str | None = None,
) -> pd.DataFrame:
    """Flatten certification reports to recall/tail columns for comparison."""
    rows = [flatten_certification_report(report) for report in reports]
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    masks = []
    if commodity:
        masks.append(df["commodity"].astype(str) == commodity)
    if dataset_key:
        masks.append(df["dataset_key"].astype(str) == dataset_key)
    if target_key:
        masks.append(df["target_key"].astype(str) == target_key)
    if feature_set_id:
        masks.append(df["feature_set"].astype(str) == feature_set_id)
    for mask in masks:
        df = df.loc[mask].copy()

    cols = [
        "candidate_id",
        "commodity",
        "feature_set",
        "dataset_key",
        "target_key",
        "model",
        "model_params_sha",
        "cv_policy",
        "aggregate_rmse",
        "aggregate_mae",
        "aggregate_sign_accuracy",
        "n_prediction_rows",
        "quintile_directional_accuracy",
        "n_extreme_independent_country_years",
        "bad_year_negative_recall",
        "bad_year_sign_accuracy",
        "bad_year_metric_validated",
        "best_baseline_rmse",
        "model_vs_best_baseline_rmse_delta",
        "leakage_status",
        "permutation_status",
        "promotion_gate_status",
        "promotion_recommendation",
        "certification_report_uri",
    ]
    present = [col for col in cols if col in df.columns]
    return df[present].sort_values(
        ["promotion_gate_status", "model_vs_best_baseline_rmse_delta", "aggregate_rmse"],
        na_position="last",
    ).reset_index(drop=True)


def build_feature_diagnostics(
    train_df: pd.DataFrame,
    feature_cols: list[str],
    *,
    target_col: str,
    membership: pd.DataFrame | None = None,
    reports: list[dict[str, Any]] | None = None,
    commodity: str | None = None,
    dataset_key: str | None = None,
    target_key: str | None = None,
    feature_set_id: str | None = None,
    bad_quantile: float = 0.2,
    event_thresholds: tuple[float, ...] = (-0.05, -0.10, -0.15),
    correlation_threshold: float = 0.95,
) -> FeatureDiagnosticsArtifacts:
    """Build the complete feature diagnostics bundle."""
    inventory = build_feature_inventory(train_df, feature_cols, membership=membership)
    target_tail_summary, target_tail_by_country, target_tail_by_year = build_target_tail_reports(
        train_df,
        target_col=target_col,
        bad_quantile=bad_quantile,
        thresholds=event_thresholds,
    )
    return FeatureDiagnosticsArtifacts(
        feature_inventory=inventory,
        missingness_by_year=build_missingness_by_year(train_df, feature_cols),
        missingness_by_country=build_missingness_by_country(train_df, feature_cols),
        missingness_target_association=build_missingness_target_association(
            train_df,
            feature_cols,
            target_col=target_col,
            bad_quantile=bad_quantile,
        ),
        target_tail_summary=target_tail_summary,
        target_tail_by_country=target_tail_by_country,
        target_tail_by_year=target_tail_by_year,
        correlation_pairs=build_correlation_pairs(
            train_df,
            feature_cols,
            threshold=correlation_threshold,
        ),
        preprocessing_audit=build_preprocessing_audit(train_df, feature_cols, inventory),
        candidate_recall_audit=candidate_recall_audit_from_reports(
            reports or [],
            commodity=commodity,
            dataset_key=dataset_key,
            target_key=target_key,
            feature_set_id=feature_set_id,
        ),
    )


def write_feature_diagnostics(
    artifacts: FeatureDiagnosticsArtifacts,
    output_dir: str | Path,
    *,
    manifest: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Write diagnostics as Parquet plus JSON summary files."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    frames = {
        "feature_inventory": artifacts.feature_inventory,
        "missingness_by_year": artifacts.missingness_by_year,
        "missingness_by_country": artifacts.missingness_by_country,
        "missingness_target_association": artifacts.missingness_target_association,
        "target_tail_summary": artifacts.target_tail_summary,
        "target_tail_by_country": artifacts.target_tail_by_country,
        "target_tail_by_year": artifacts.target_tail_by_year,
        "correlation_pairs": artifacts.correlation_pairs,
        "candidate_recall_audit": artifacts.candidate_recall_audit,
    }
    paths: dict[str, str] = {}
    for name, frame in frames.items():
        path = out / f"{name}.parquet"
        frame.to_parquet(path, index=False)
        paths[name] = str(path)

    preprocessing_path = out / "preprocessing_audit.json"
    preprocessing_path.write_text(
        json.dumps(_json_safe(artifacts.preprocessing_audit), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    paths["preprocessing_audit"] = str(preprocessing_path)

    manifest_payload = manifest or {}
    manifest_payload["outputs"] = paths
    manifest_path = out / "manifest.json"
    manifest_path.write_text(
        json.dumps(_json_safe(manifest_payload), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    paths["manifest"] = str(manifest_path)
    return paths
