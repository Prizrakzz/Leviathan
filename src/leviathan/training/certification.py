"""Candidate certification diagnostics before model promotion.

This module is deliberately separate from broad training sweeps.  It takes a
frozen candidate definition and asks whether the attractive metric is robust,
leakage-safe, and materially better than simple baselines.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
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
    model_params: dict[str, Any] | None = None

    @property
    def candidate_id(self) -> str:
        model_params_sha = _params_sha(self.model_params)
        parts = [
            self.commodity,
            self.feature_set_id,
            self.dataset_key,
            self.target_key,
            self.model_name,
            model_params_sha,
            self.cv_policy,
            self.model_dataset_version,
        ]
        return "__".join(_safe_fragment(part) for part in parts)


def _safe_fragment(value: object) -> str:
    text = "" if value is None else str(value)
    out = "".join(ch if ch.isalnum() or ch in "_.=-" else "_" for ch in text)
    return out.strip("_") or "none"


def _params_sha(model_params: dict[str, Any] | None) -> str:
    if not model_params:
        return "default_params"
    payload = json.dumps(model_params, sort_keys=True, default=str)
    return "params_" + hashlib.sha1(payload.encode("utf-8")).hexdigest()[:10]


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


def fold_metric_rows(result) -> list[dict[str, Any]]:
    """Return per-fold metrics in a JSON-friendly shape."""
    rows: list[dict[str, Any]] = []
    for fold in result.folds:
        rows.append({
            "test_year": fold.test_year,
            "fold_start_train_year": fold.fold_start_train_year,
            "fold_end_train_year": fold.fold_end_train_year,
            "train_year_count": fold.train_year_count,
            "n_train_rows": fold.n_train_rows,
            "n_test_rows": fold.n_test_rows,
            "rmse": fold.rmse,
            "mae": fold.mae,
            "directional_accuracy": fold.directional_accuracy,
            "cv_policy": fold.cv_policy,
        })
    return rows


def bad_production_year_metrics(
    predictions: pd.DataFrame,
    q: float = 0.2,
    *,
    min_independent_country_years: int = 30,
) -> dict[str, float]:
    """Directional recall on the worst production-anomaly years.

    ``extreme_directional_metrics`` scores high-magnitude upside and downside
    events together.  For production-risk work we also need the downside view:
    when the actual target is in the bottom quintile, did the model call the
    anomaly negative?
    """
    df = predictions.dropna(subset=["y_actual", "y_pred"]).copy()
    empty = {
        "bad_year_threshold_actual": float("nan"),
        "n_bad_year_rows": 0.0,
        "n_bad_year_independent_country_years": 0.0,
        "n_bad_year_countries": 0.0,
        "n_bad_year_years": 0.0,
        "bad_year_negative_recall": float("nan"),
        "bad_year_sign_accuracy": float("nan"),
        "validated": 0.0,
        "min_independent_country_years": float(min_independent_country_years),
    }
    if df.empty:
        return empty
    threshold = float(df["y_actual"].quantile(q))
    bad = df.loc[df["y_actual"] <= threshold].copy()
    if bad.empty:
        out = dict(empty)
        out["bad_year_threshold_actual"] = threshold
        return out

    identity_cols = [
        col for col in ("commodity", "country", "crop_year") if col in bad.columns
    ]
    independent = (
        int(bad.drop_duplicates(identity_cols).shape[0])
        if identity_cols else int(len(bad))
    )
    predicted_negative = bad["y_pred"].astype(float) < 0.0
    sign_correct = np.sign(bad["y_pred"].astype(float)) == np.sign(bad["y_actual"].astype(float))
    return {
        "bad_year_threshold_actual": threshold,
        "n_bad_year_rows": float(len(bad)),
        "n_bad_year_independent_country_years": float(independent),
        "n_bad_year_countries": float(bad["country"].nunique()) if "country" in bad.columns else 0.0,
        "n_bad_year_years": float(bad["crop_year"].nunique()) if "crop_year" in bad.columns else 0.0,
        "bad_year_negative_recall": float(predicted_negative.mean()),
        "bad_year_sign_accuracy": float(sign_correct.mean()),
        "validated": float(independent >= min_independent_country_years),
        "min_independent_country_years": float(min_independent_country_years),
    }


def _safe_divide(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return math.nan
    return float(numerator / denominator)


def _fbeta_score(precision: float, recall: float, beta: float = 2.0) -> float:
    if not np.isfinite(precision) or not np.isfinite(recall):
        return math.nan
    beta_sq = beta ** 2
    denom = (beta_sq * precision) + recall
    if denom == 0:
        return math.nan
    return float((1 + beta_sq) * precision * recall / denom)


def downside_alert_metrics(
    predictions: pd.DataFrame,
    *,
    thresholds: tuple[float, ...] = (-0.05, -0.10),
    min_event_rows: int = 5,
) -> dict[str, Any]:
    """Evaluate fixed-threshold downside alert policies on OOF predictions."""
    df = predictions.dropna(subset=["y_actual", "y_pred"]).copy()
    if df.empty:
        return {
            "thresholds": list(thresholds),
            "rows": [],
            "summary": {},
            "min_event_rows": min_event_rows,
        }

    rows: list[dict[str, Any]] = []
    for threshold in thresholds:
        actual = df["y_actual"].astype(float)
        pred = df["y_pred"].astype(float)
        actual_event = actual <= threshold
        alert_policies = {
            "pred_lt_0": pred < 0.0,
            "pred_le_event_threshold": pred <= threshold,
        }
        for policy_name, alert in alert_policies.items():
            tp = int((actual_event & alert).sum())
            fp = int((~actual_event & alert).sum())
            fn = int((actual_event & ~alert).sum())
            tn = int((~actual_event & ~alert).sum())
            precision = _safe_divide(tp, tp + fp)
            recall = _safe_divide(tp, tp + fn)
            false_negative_rate = _safe_divide(fn, tp + fn)
            false_positive_rate = _safe_divide(fp, fp + tn)
            rows.append({
                "threshold": float(threshold),
                "alert_policy": policy_name,
                "n_rows": int(len(df)),
                "n_events": int(actual_event.sum()),
                "n_alerts": int(alert.sum()),
                "true_positives": tp,
                "false_positives": fp,
                "false_negatives": fn,
                "true_negatives": tn,
                "precision": precision,
                "recall": recall,
                "false_negative_rate": false_negative_rate,
                "false_positive_rate": false_positive_rate,
                "f2_score": _fbeta_score(precision, recall, beta=2.0),
                "validated": bool(int(actual_event.sum()) >= min_event_rows),
                "min_event_rows": int(min_event_rows),
            })

    summary: dict[str, Any] = {}
    for row in rows:
        suffix = str(abs(row["threshold"])).replace(".", "p")
        policy = row["alert_policy"]
        prefix = f"downside_{suffix}_{policy}"
        summary[f"{prefix}_n_events"] = row["n_events"]
        summary[f"{prefix}_recall"] = row["recall"]
        summary[f"{prefix}_precision"] = row["precision"]
        summary[f"{prefix}_false_negatives"] = row["false_negatives"]
        summary[f"{prefix}_f2_score"] = row["f2_score"]
        summary[f"{prefix}_validated"] = row["validated"]

    return {
        "thresholds": list(thresholds),
        "rows": rows,
        "summary": summary,
        "min_event_rows": min_event_rows,
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


def promotion_questions(
    *,
    aggregate_metrics: dict[str, Any],
    extreme_metrics: dict[str, float],
    bad_year_metrics: dict[str, float],
    downside_alerts: dict[str, Any],
    baseline: dict[str, Any],
    leakage_audit: dict[str, Any],
    permutation: dict[str, Any],
    country_blocked: dict[str, Any],
    stress: dict[str, Any],
    gate: dict[str, Any],
) -> dict[str, Any]:
    """Phase 10 checklist answers for manual candidate review."""
    model_rmse = aggregate_metrics.get("rmse")
    model_mae = aggregate_metrics.get("mae")
    rows = baseline.get("rows", []) or []

    def _beats(name: str, metric: str) -> bool | None:
        if model_rmse is None or model_mae is None:
            return None
        for row in rows:
            if row.get("baseline_name") == name:
                baseline_value = row.get(metric)
                model_value = aggregate_metrics.get(metric)
                if baseline_value is None or model_value is None:
                    return None
                try:
                    if not np.isfinite(float(baseline_value)) or not np.isfinite(float(model_value)):
                        return None
                    return float(model_value) < float(baseline_value)
                except Exception:  # noqa: BLE001
                    return None
        return None

    country_rmse = (country_blocked.get("aggregate") or {}).get("rmse")
    stress_rmse = (stress.get("metrics") or {}).get("rmse")
    alert_summary = downside_alerts.get("summary", {}) or {}
    return {
        "beats_zero_baseline_rmse": _beats("zero_anomaly", "rmse"),
        "beats_zero_baseline_mae": _beats("zero_anomaly", "mae"),
        "beats_prior_year_baseline_rmse": _beats("prior_year", "rmse"),
        "beats_prior_year_baseline_mae": _beats("prior_year", "mae"),
        "beats_trailing_mean_baseline_rmse": _beats("trailing_mean", "rmse"),
        "beats_trailing_mean_baseline_mae": _beats("trailing_mean", "mae"),
        "beats_trailing_trend_baseline_rmse": _beats("trailing_linear_trend", "rmse"),
        "beats_trailing_trend_baseline_mae": _beats("trailing_linear_trend", "mae"),
        "bad_year_detection_validated": bool(bad_year_metrics.get("validated")),
        "bad_year_negative_recall": bad_year_metrics.get("bad_year_negative_recall"),
        "downside_5pct_pred_lt_0_recall": alert_summary.get(
            "downside_0p05_pred_lt_0_recall"
        ),
        "downside_5pct_pred_lt_0_false_negatives": alert_summary.get(
            "downside_0p05_pred_lt_0_false_negatives"
        ),
        "downside_10pct_pred_lt_0_recall": alert_summary.get(
            "downside_0p1_pred_lt_0_recall"
        ),
        "downside_10pct_pred_lt_0_false_negatives": alert_summary.get(
            "downside_0p1_pred_lt_0_false_negatives"
        ),
        "extreme_metric_sample_validated": bool(extreme_metrics.get("validated")),
        "quintile_directional_accuracy": extreme_metrics.get("directional_accuracy"),
        "leakage_audit_passed": leakage_audit.get("status") == "pass",
        "permutation_sanity_passed": permutation.get("status") == "pass",
        "country_blocked_rmse": country_rmse,
        "country_blocked_rmse_delta_vs_walk_forward": (
            float(country_rmse) - float(model_rmse)
            if country_rmse is not None and model_rmse is not None
            and np.isfinite(float(country_rmse)) and np.isfinite(float(model_rmse))
            else None
        ),
        "stress_year_rmse": stress_rmse,
        "stress_year_rmse_delta_vs_walk_forward": (
            float(stress_rmse) - float(model_rmse)
            if stress_rmse is not None and model_rmse is not None
            and np.isfinite(float(stress_rmse)) and np.isfinite(float(model_rmse))
            else None
        ),
        "feature_importance_review_required": True,
        "ready_for_model_registration": gate.get("status") == "pass",
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
    bad_years = bad_production_year_metrics(predictions)
    downside_alerts = downside_alert_metrics(predictions)
    leakage = audit_feature_leakage(feature_cols, target_col=target_col)
    baseline = baseline_comparison(result.predictions, matrix)
    stress = stress_year_summary(predictions, stress_years)
    country_blocked = country_blocked_validation(
        train_df,
        target_col=target_col,
        feature_cols=feature_cols,
        model=model,
    )
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
    aggregate = {
        "rmse": result.rmse,
        "mae": result.mae,
        "directional_accuracy": result.directional_accuracy,
        "n_folds": result.n_folds,
        "n_prediction_rows": int(len(result.predictions)),
    }
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
            "model_params": spec.model_params or {},
            "model_params_sha": _params_sha(spec.model_params),
        },
        "aggregate_metrics": aggregate,
        "fold_metrics": fold_metric_rows(result),
        "extreme_metrics": extreme,
        "bad_production_year_metrics": bad_years,
        "downside_alert_metrics": downside_alerts,
        "baseline_comparison": baseline,
        "leakage_audit": leakage,
        "stress_year_summary": stress,
        "country_blocked_validation": country_blocked,
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
        "promotion_questions": promotion_questions(
            aggregate_metrics=aggregate,
            extreme_metrics=extreme,
            bad_year_metrics=bad_years,
            downside_alerts=downside_alerts,
            baseline=baseline,
            leakage_audit=leakage,
            permutation=permutation,
            country_blocked=country_blocked,
            stress=stress,
            gate=gate,
        ),
    }
    return _json_safe(report)
