"""Candidate certification diagnostics before model promotion.

This module is deliberately separate from broad training sweeps.  It takes a
frozen candidate definition and asks whether the attractive metric is robust,
leakage-safe, and materially better than simple baselines.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

import numpy as np
import pandas as pd
from sklearn.base import clone

from leviathan.model_datasets.baselines import BASELINE_COLUMNS
from leviathan.training.cv import walk_forward_cv
from leviathan.training.model_ready import (
    MODEL_READY_EXCLUDED_FEATURE_COLUMNS,
    MODEL_READY_TARGET_COL,
    model_ready_baseline_metrics_for_predictions,
    model_ready_metric_log_values,
)
from leviathan.training.slices import extreme_directional_metrics

DEFAULT_STRESS_YEARS = (2010, 2011, 2012, 2020, 2021, 2022)


@dataclass(frozen=True)
class CandidateSpec:
    commodity: str
    feature_set_id: str
    dataset_key: str
    target_key: str
    model_name: str
    cv_policy: str
    model_dataset_version: str
    source_dataset_version: str | None = None
    min_train_years: int = 10

    @property
    def candidate_id(self) -> str:
        parts = [
            self.commodity,
            self.feature_set_id,
            self.dataset_key,
            self.target_key,
            self.model_name,
            self.cv_policy,
            self.model_dataset_version,
        ]
        return "__".join(_safe_fragment(part) for part in parts)


def _safe_fragment(value: object) -> str:
    text = "" if value is None else str(value)
    out = "".join(ch if ch.isalnum() or ch in "_.=-" else "_" for ch in text)
    return out.strip("_") or "none"


def _json_safe(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return None if math.isnan(value) or math.isinf(value) else value
    if isinstance(value, np.generic):
        return _json_safe(value.item())
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return str(value)


def regression_metrics(actual: pd.Series, pred: pd.Series) -> dict[str, float]:
    """RMSE/MAE/sign accuracy for a candidate or baseline."""
    actual_f = pd.to_numeric(actual, errors="coerce")
    pred_f = pd.to_numeric(pred, errors="coerce")
    valid = actual_f.notna() & pred_f.notna()
    if int(valid.sum()) == 0:
        return {"n_rows": 0.0, "rmse": math.nan, "mae": math.nan, "sign_accuracy": math.nan}
    residual = actual_f[valid] - pred_f[valid]
    return {
        "n_rows": float(int(valid.sum())),
        "rmse": float(np.sqrt((residual ** 2).mean())),
        "mae": float(residual.abs().mean()),
        "sign_accuracy": float(
            (np.sign(actual_f[valid]) == np.sign(pred_f[valid])).mean()
        ),
    }


def audit_feature_leakage(
    feature_cols: list[str],
    *,
    target_col: str = MODEL_READY_TARGET_COL,
) -> dict[str, Any]:
    """Flag feature columns that should never be model inputs."""
    blocked_exact = {
        target_col,
        MODEL_READY_TARGET_COL,
        "actual_value",
        "trend_prediction",
        "prior_year_value",
        "history_years",
        "is_trainable",
        "excluded_reason",
    } | set(BASELINE_COLUMNS.values()) | set(MODEL_READY_EXCLUDED_FEATURE_COLUMNS)

    hard: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    for feature in sorted(feature_cols):
        lower = feature.lower()
        if feature in blocked_exact:
            hard.append({"feature": feature, "reason": "blocked identity/target/baseline column"})
        elif lower.startswith("label_"):
            hard.append({"feature": feature, "reason": "label column selected as feature"})
        elif "baseline" in lower:
            hard.append({"feature": feature, "reason": "baseline-derived column selected"})
        elif "target" in lower or "actual" in lower:
            warnings.append({"feature": feature, "reason": "name resembles target/actual data"})
        elif lower.startswith("psd_") and "final" in lower:
            warnings.append({"feature": feature, "reason": "PSD final-value naming needs review"})

    return {
        "status": "fail" if hard else ("warn" if warnings else "pass"),
        "hard_findings": hard,
        "warnings": warnings,
    }


def baseline_comparison(predictions: pd.DataFrame, matrix: pd.DataFrame) -> dict[str, Any]:
    """Compare candidate predictions against materialized target baselines."""
    baseline_df = model_ready_baseline_metrics_for_predictions(predictions, matrix)
    flat = model_ready_metric_log_values(predictions, baseline_df)
    rows = baseline_df.to_dict(orient="records") if not baseline_df.empty else []
    return {"rows": rows, "metrics": flat}


def stress_year_summary(
    predictions: pd.DataFrame,
    stress_years: tuple[int, ...] = DEFAULT_STRESS_YEARS,
) -> dict[str, Any]:
    """Score candidate predictions only on configured stress years."""
    df = predictions.loc[predictions["crop_year"].isin(set(stress_years))].copy()
    metrics = regression_metrics(df.get("y_actual", pd.Series(dtype=float)), df.get("y_pred", pd.Series(dtype=float)))
    return {
        "stress_years": list(stress_years),
        "present_stress_years": sorted(int(y) for y in df["crop_year"].dropna().unique())
        if "crop_year" in df.columns else [],
        "metrics": metrics,
        "extreme_metrics": extreme_directional_metrics(df),
    }


def country_blocked_validation(
    train_df: pd.DataFrame,
    *,
    target_col: str,
    feature_cols: list[str],
    model: object,
) -> dict[str, Any]:
    """Train on all but one country and score the held-out country.

    This is not a production inference scheme.  It is a diagnostic for whether a
    commodity model is mostly memorizing country-specific behavior.
    """
    rows: list[dict[str, Any]] = []
    frames: list[pd.DataFrame] = []
    countries = sorted(str(c) for c in train_df["country"].dropna().unique())
    for country in countries:
        train = train_df[(train_df["country"] != country) & train_df[target_col].notna()]
        test = train_df[(train_df["country"] == country) & train_df[target_col].notna()]
        if train.empty or test.empty:
            rows.append({
                "country": country,
                "status": "skip",
                "reason": "empty train or test split",
            })
            continue
        fitted = clone(model)
        fitted.fit(train[feature_cols], train[target_col].astype(float))
        y_pred = fitted.predict(test[feature_cols])
        metrics = regression_metrics(test[target_col], pd.Series(y_pred, index=test.index))
        rows.append({
            "country": country,
            "status": "ok",
            "n_train_rows": int(len(train)),
            "n_test_rows": int(len(test)),
            **metrics,
        })
        pred = test[[col for col in ("country", "crop_year", "snapshot_stage", "as_of_date") if col in test.columns]].copy()
        pred["y_actual"] = test[target_col].to_numpy(dtype=float)
        pred["y_pred"] = y_pred
        frames.append(pred)

    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return {
        "rows": rows,
        "aggregate": regression_metrics(
            combined.get("y_actual", pd.Series(dtype=float)),
            combined.get("y_pred", pd.Series(dtype=float)),
        ),
        "extreme_metrics": extreme_directional_metrics(combined),
    }


def leave_year_out_sensitivity(
    train_df: pd.DataFrame,
    *,
    target_col: str,
    feature_cols: list[str],
    model: object,
    cv_policy: str,
    min_train_years: int,
    stress_years: tuple[int, ...] = DEFAULT_STRESS_YEARS,
) -> dict[str, Any]:
    """Rerun CV after excluding each configured stress year from training data."""
    rows: list[dict[str, Any]] = []
    available = set(int(y) for y in train_df["crop_year"].dropna().unique())
    for year in stress_years:
        if year not in available:
            rows.append({"held_out_year": year, "status": "skip", "reason": "year absent"})
            continue
        subset = train_df[train_df["crop_year"] != year].copy()
        try:
            result = walk_forward_cv(
                subset,
                target_col,
                feature_cols,
                clone(model),
                min_train_years=min_train_years,
                cv_policy=cv_policy,
            )
        except ValueError as exc:
            rows.append({"held_out_year": year, "status": "skip", "reason": str(exc)})
            continue
        rows.append({
            "held_out_year": year,
            "status": "ok",
            "rmse": result.rmse,
            "mae": result.mae,
            "directional_accuracy": result.directional_accuracy,
            "n_folds": result.n_folds,
            **{
                f"extreme_{key}": value
                for key, value in extreme_directional_metrics(result.predictions).items()
            },
        })
    return {"rows": rows}


def _permuted_target(
    train_df: pd.DataFrame,
    target_col: str,
    *,
    rng: np.random.Generator,
) -> pd.DataFrame:
    out = train_df.copy()
    for _, idx in out.groupby("country").groups.items():
        values = out.loc[idx, target_col].to_numpy(copy=True)
        rng.shuffle(values)
        out.loc[idx, target_col] = values
    return out


def permutation_sanity_check(
    train_df: pd.DataFrame,
    *,
    target_col: str,
    feature_cols: list[str],
    model: object,
    cv_policy: str,
    min_train_years: int,
    actual_predictions: pd.DataFrame,
    trials: int = 20,
    random_seed: int = 1729,
) -> dict[str, Any]:
    """Shuffle labels and confirm the headline metric degrades toward random."""
    actual_extreme = extreme_directional_metrics(actual_predictions)
    if trials <= 0:
        return {
            "trials": 0,
            "status": "skip",
            "actual_extreme_directional_accuracy": actual_extreme["directional_accuracy"],
        }

    rng = np.random.default_rng(random_seed)
    rows: list[dict[str, Any]] = []
    for trial in range(trials):
        shuffled = _permuted_target(train_df, target_col, rng=rng)
        try:
            result = walk_forward_cv(
                shuffled,
                target_col,
                feature_cols,
                clone(model),
                min_train_years=min_train_years,
                cv_policy=cv_policy,
            )
        except ValueError as exc:
            rows.append({"trial": trial, "status": "skip", "reason": str(exc)})
            continue
        extreme = extreme_directional_metrics(result.predictions)
        rows.append({
            "trial": trial,
            "status": "ok",
            "rmse": result.rmse,
            "directional_accuracy": result.directional_accuracy,
            "extreme_directional_accuracy": extreme["directional_accuracy"],
            "n_extreme_independent_country_years": extreme[
                "n_extreme_independent_country_years"
            ],
        })

    ok = pd.DataFrame([row for row in rows if row.get("status") == "ok"])
    if ok.empty:
        return {
            "trials": trials,
            "status": "skip",
            "rows": rows,
            "reason": "no permutation trials completed",
            "actual_extreme_directional_accuracy": actual_extreme["directional_accuracy"],
        }
    null = pd.to_numeric(ok["extreme_directional_accuracy"], errors="coerce").dropna()
    p95 = float(null.quantile(0.95)) if len(null) else math.nan
    actual = float(actual_extreme["directional_accuracy"])
    passed = bool(np.isfinite(actual) and np.isfinite(p95) and actual > p95)
    return {
        "trials": trials,
        "status": "pass" if passed else "fail",
        "actual_extreme_directional_accuracy": actual,
        "null_extreme_directional_accuracy_mean": float(null.mean()) if len(null) else math.nan,
        "null_extreme_directional_accuracy_p95": p95,
        "rows": rows,
    }


def promotion_gate(
    *,
    leakage_audit: dict[str, Any],
    extreme_metrics: dict[str, float],
    baseline: dict[str, Any],
    permutation: dict[str, Any],
) -> dict[str, Any]:
    """Conservative promotion gate for Phase 10 readiness."""
    hard_failures: list[str] = []
    warnings: list[str] = []

    if leakage_audit["hard_findings"]:
        hard_failures.append("hard leakage findings")
    if not bool(extreme_metrics["validated"]):
        warnings.append("extreme metric lacks minimum independent country-year count")
    if permutation.get("status") == "fail":
        hard_failures.append("permutation sanity test failed")
    delta = baseline.get("metrics", {}).get("model_vs_best_baseline_rmse_delta")
    if delta is not None and np.isfinite(float(delta)) and float(delta) > 0:
        warnings.append("candidate does not beat best baseline on RMSE")

    if hard_failures:
        status = "fail"
        recommendation = "do_not_promote"
    elif warnings:
        status = "warn"
        recommendation = "hold_for_more_validation"
    else:
        status = "pass"
        recommendation = "eligible_for_manual_review"
    return {
        "status": status,
        "recommendation": recommendation,
        "hard_failures": hard_failures,
        "warnings": warnings,
    }


def build_candidate_certification_report(
    *,
    spec: CandidateSpec,
    matrix: pd.DataFrame,
    train_df: pd.DataFrame,
    feature_cols: list[str],
    target_col: str,
    model: object,
    stress_years: tuple[int, ...] = DEFAULT_STRESS_YEARS,
    permutation_trials: int = 20,
    random_seed: int = 1729,
) -> dict[str, Any]:
    """Run the full certification gauntlet and return a JSON-safe report."""
    result = walk_forward_cv(
        train_df,
        target_col,
        feature_cols,
        clone(model),
        min_train_years=spec.min_train_years,
        cv_policy=spec.cv_policy,
    )
    predictions = result.predictions.copy()
    predictions["commodity"] = spec.commodity
    extreme = extreme_directional_metrics(predictions)
    leakage = audit_feature_leakage(feature_cols, target_col=target_col)
    baseline = baseline_comparison(result.predictions, matrix)
    permutation = permutation_sanity_check(
        train_df,
        target_col=target_col,
        feature_cols=feature_cols,
        model=model,
        cv_policy=spec.cv_policy,
        min_train_years=spec.min_train_years,
        actual_predictions=predictions,
        trials=permutation_trials,
        random_seed=random_seed,
    )
    gate = promotion_gate(
        leakage_audit=leakage,
        extreme_metrics=extreme,
        baseline=baseline,
        permutation=permutation,
    )
    report = {
        "candidate": {
            "candidate_id": spec.candidate_id,
            "commodity": spec.commodity,
            "feature_set_id": spec.feature_set_id,
            "dataset_key": spec.dataset_key,
            "target_key": spec.target_key,
            "model_name": spec.model_name,
            "cv_policy": spec.cv_policy,
            "model_dataset_version": spec.model_dataset_version,
            "source_dataset_version": spec.source_dataset_version,
            "min_train_years": spec.min_train_years,
        },
        "aggregate_metrics": {
            "rmse": result.rmse,
            "mae": result.mae,
            "directional_accuracy": result.directional_accuracy,
            "n_folds": result.n_folds,
            "n_prediction_rows": int(len(result.predictions)),
        },
        "extreme_metrics": extreme,
        "baseline_comparison": baseline,
        "leakage_audit": leakage,
        "stress_year_summary": stress_year_summary(predictions, stress_years),
        "country_blocked_validation": country_blocked_validation(
            train_df,
            target_col=target_col,
            feature_cols=feature_cols,
            model=model,
        ),
        "leave_stress_year_out_sensitivity": leave_year_out_sensitivity(
            train_df,
            target_col=target_col,
            feature_cols=feature_cols,
            model=model,
            cv_policy=spec.cv_policy,
            min_train_years=spec.min_train_years,
            stress_years=stress_years,
        ),
        "permutation_sanity": permutation,
        "promotion_gate": gate,
    }
    return _json_safe(report)
