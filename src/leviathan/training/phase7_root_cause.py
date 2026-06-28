"""Phase 7 root-cause utilities for corn composite model failures.

The goal of this module is descriptive, not promotional: collect target,
baseline, feature-quality, and certification evidence into stable tables that
explain why a candidate grid did or did not deserve wider sweeps.
"""
from __future__ import annotations

from typing import Any, Iterable

import numpy as np
import pandas as pd

from leviathan.training.certification_summary import flatten_certification_report


def _num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _safe_float(value: object) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return float("nan")
    return out if np.isfinite(out) else float("nan")


def _get(obj: dict[str, Any], path: str, default: Any = None) -> Any:
    cur: Any = obj
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def certification_comparison_frame(
    reports: Iterable[dict[str, Any]],
    *,
    model_dataset_versions: Iterable[str] = (),
) -> pd.DataFrame:
    """Flatten and filter certification reports for candidate comparison."""
    rows = [flatten_certification_report(report) for report in reports]
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    versions = {str(version) for version in model_dataset_versions if str(version)}
    if versions and "model_dataset_version" in df.columns:
        df = df.loc[df["model_dataset_version"].astype(str).isin(versions)].copy()
    if df.empty:
        return df

    numeric_cols = [
        "aggregate_rmse",
        "aggregate_mae",
        "aggregate_sign_accuracy",
        "bad_year_negative_recall",
        "best_baseline_rmse",
        "best_baseline_mae",
        "model_vs_best_baseline_rmse_delta",
        "model_vs_best_baseline_mae_delta",
        "country_blocked_rmse",
        "stress_year_rmse",
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.sort_values(
        ["promotion_gate_status", "aggregate_mae", "aggregate_rmse", "candidate_id"],
        na_position="last",
    ).reset_index(drop=True)


def target_health_frame(
    matrix: pd.DataFrame,
    *,
    target_col: str = "target_value",
    bad_quantile: float = 0.2,
    thresholds: tuple[float, ...] = (-0.05, -0.10, -0.15),
) -> pd.DataFrame:
    """Summarize target distribution by overall/country/decade scopes."""
    if target_col not in matrix.columns:
        raise ValueError(f"matrix missing target column {target_col!r}")
    df = matrix.copy()
    if "is_trainable" in df.columns:
        df = df.loc[df["is_trainable"].fillna(False).astype(bool)].copy()
    df = df.loc[df[target_col].notna()].copy()
    if df.empty:
        return pd.DataFrame()
    df[target_col] = _num(df[target_col])
    if "crop_year" in df.columns:
        df["decade"] = (_num(df["crop_year"]) // 10 * 10).astype("Int64")

    global_bad_threshold = float(df[target_col].quantile(bad_quantile))
    specs: list[tuple[str, list[str]]] = [("overall", [])]
    if "country" in df.columns:
        specs.append(("country", ["country"]))
    if "decade" in df.columns:
        specs.append(("decade", ["decade"]))
    if {"country", "decade"} <= set(df.columns):
        specs.append(("country_decade", ["country", "decade"]))

    rows: list[dict[str, Any]] = []
    for scope_type, cols in specs:
        groups = [((), df)] if not cols else df.groupby(cols, dropna=False, sort=True)
        for key, group in groups:
            if not isinstance(key, tuple):
                key = (key,)
            target = _num(group[target_col])
            row: dict[str, Any] = {
                "scope_type": scope_type,
                "row_count": int(len(group)),
                "target_non_null_count": int(target.notna().sum()),
                "target_mean": _safe_float(target.mean()),
                "target_std": _safe_float(target.std(ddof=0)),
                "target_min": _safe_float(target.min()),
                "target_p05": _safe_float(target.quantile(0.05)),
                "target_p20": _safe_float(target.quantile(0.20)),
                "target_median": _safe_float(target.median()),
                "target_p80": _safe_float(target.quantile(0.80)),
                "target_p95": _safe_float(target.quantile(0.95)),
                "target_max": _safe_float(target.max()),
                "bad_quantile": bad_quantile,
                "bad_quantile_threshold_global": global_bad_threshold,
                "bad_quantile_event_count": int((target <= global_bad_threshold).sum()),
                "bad_quantile_event_rate": _safe_float((target <= global_bad_threshold).mean()),
            }
            for col, value in zip(cols, key, strict=False):
                row[col] = value
            for threshold in thresholds:
                name = str(threshold).replace("-", "neg_").replace(".", "p")
                event = target <= threshold
                row[f"target_le_{name}_count"] = int(event.sum())
                row[f"target_le_{name}_rate"] = _safe_float(event.mean())
            rows.append(row)
    return pd.DataFrame(rows)


def baseline_audit_frame(reports: Iterable[dict[str, Any]]) -> pd.DataFrame:
    """Return one row per candidate x materialized baseline comparison."""
    rows: list[dict[str, Any]] = []
    for report in reports:
        flat = flatten_certification_report(report)
        candidate_id = flat.get("candidate_id")
        model_rmse = _get(report, "aggregate_metrics.rmse")
        model_mae = _get(report, "aggregate_metrics.mae")
        for baseline in (_get(report, "baseline_comparison.rows", []) or []):
            baseline_name = baseline.get("baseline_name")
            rmse = baseline.get("rmse")
            mae = baseline.get("mae")
            rows.append({
                "candidate_id": candidate_id,
                "feature_set": flat.get("feature_set"),
                "model": flat.get("model"),
                "model_params_sha": flat.get("model_params_sha"),
                "model_dataset_version": flat.get("model_dataset_version"),
                "baseline_name": baseline_name,
                "baseline_rmse": _safe_float(rmse),
                "baseline_mae": _safe_float(mae),
                "baseline_sign_accuracy": _safe_float(baseline.get("sign_accuracy")),
                "model_rmse": _safe_float(model_rmse),
                "model_mae": _safe_float(model_mae),
                "model_minus_baseline_rmse": (
                    _safe_float(model_rmse) - _safe_float(rmse)
                    if np.isfinite(_safe_float(model_rmse)) and np.isfinite(_safe_float(rmse))
                    else float("nan")
                ),
                "model_minus_baseline_mae": (
                    _safe_float(model_mae) - _safe_float(mae)
                    if np.isfinite(_safe_float(model_mae)) and np.isfinite(_safe_float(mae))
                    else float("nan")
                ),
                "beats_baseline_rmse": (
                    bool(_safe_float(model_rmse) < _safe_float(rmse))
                    if np.isfinite(_safe_float(model_rmse)) and np.isfinite(_safe_float(rmse))
                    else None
                ),
                "beats_baseline_mae": (
                    bool(_safe_float(model_mae) < _safe_float(mae))
                    if np.isfinite(_safe_float(model_mae)) and np.isfinite(_safe_float(mae))
                    else None
                ),
            })
    return pd.DataFrame(rows)


def tail_recall_audit_frame(reports: Iterable[dict[str, Any]]) -> pd.DataFrame:
    """Return bad-year and extreme-sample diagnostics per candidate."""
    rows: list[dict[str, Any]] = []
    for report in reports:
        flat = flatten_certification_report(report)
        bad = _get(report, "bad_production_year_metrics", {}) or {}
        extreme = _get(report, "extreme_metrics", {}) or {}
        permutation = _get(report, "permutation_sanity", {}) or {}
        n_bad = _safe_float(bad.get("n_bad_year_rows"))
        recall = _safe_float(bad.get("bad_year_negative_recall"))
        estimated_false_negatives = (
            n_bad * (1.0 - recall)
            if np.isfinite(n_bad) and np.isfinite(recall)
            else float("nan")
        )
        rows.append({
            "candidate_id": flat.get("candidate_id"),
            "feature_set": flat.get("feature_set"),
            "model": flat.get("model"),
            "model_params_sha": flat.get("model_params_sha"),
            "model_dataset_version": flat.get("model_dataset_version"),
            "bad_year_threshold_actual": _safe_float(bad.get("bad_year_threshold_actual")),
            "n_bad_year_rows": n_bad,
            "n_bad_year_independent_country_years": _safe_float(
                bad.get("n_bad_year_independent_country_years")
            ),
            "bad_year_negative_recall": recall,
            "estimated_false_negative_count": _safe_float(estimated_false_negatives),
            "bad_year_sign_accuracy": _safe_float(bad.get("bad_year_sign_accuracy")),
            "bad_year_metric_validated": bool(bad.get("validated")),
            "n_extreme_independent_country_years": _safe_float(
                extreme.get("n_extreme_independent_country_years")
            ),
            "quintile_directional_accuracy": _safe_float(extreme.get("directional_accuracy")),
            "extreme_metric_validated": bool(extreme.get("validated")),
            "permutation_status": permutation.get("status"),
            "actual_extreme_directional_accuracy": _safe_float(
                permutation.get("actual_extreme_directional_accuracy")
            ),
            "null_extreme_directional_accuracy_mean": _safe_float(
                permutation.get("null_extreme_directional_accuracy_mean")
            ),
            "null_extreme_directional_accuracy_p95": _safe_float(
                permutation.get("null_extreme_directional_accuracy_p95")
            ),
        })
    return pd.DataFrame(rows)


def feature_set_quality_frame(
    *,
    mode: str,
    feature_set_id: str,
    train_df: pd.DataFrame,
    inventory: pd.DataFrame,
    correlation_pairs: pd.DataFrame,
) -> pd.DataFrame:
    """Build one feature-set quality row from diagnostics artifacts."""
    if inventory.empty:
        return pd.DataFrame([{
            "mode": mode,
            "feature_set": feature_set_id,
            "train_rows": int(len(train_df)),
            "features": 0,
            "gate": "FAIL",
        }])
    null_rate = pd.to_numeric(inventory.get("null_rate"), errors="coerce").fillna(0.0)
    non_numeric = ~inventory.get("is_numeric", pd.Series([True] * len(inventory))).fillna(True).astype(bool)
    constants = inventory.get("is_constant", pd.Series([False] * len(inventory))).fillna(False).astype(bool)
    all_missing = inventory.get("is_all_missing", pd.Series([False] * len(inventory))).fillna(False).astype(bool)
    features = int(len(inventory))
    rows = int(len(train_df))
    gate = "PASS"
    if int(all_missing.sum()) or int(non_numeric.sum()):
        gate = "FAIL"
    elif int((null_rate > 0.8).sum()) or features > max(30, rows * 0.5):
        gate = "REVIEW"
    return pd.DataFrame([{
        "mode": mode,
        "feature_set": feature_set_id,
        "train_rows": rows,
        "features": features,
        "features_per_row": _safe_float(features / rows) if rows else float("nan"),
        "all_missing": int(all_missing.sum()),
        "missing_gt80": int((null_rate > 0.8).sum()),
        "missing_gt50": int((null_rate > 0.5).sum()),
        "constant": int(constants.sum()),
        "non_numeric": int(non_numeric.sum()),
        "median_null_rate": _safe_float(null_rate.median()),
        "max_null_rate": _safe_float(null_rate.max()),
        "high_corr_pairs": int(len(correlation_pairs)),
        "gate": gate,
    }])


def feature_family_audit_frame(
    *,
    mode: str,
    feature_set_id: str,
    inventory: pd.DataFrame,
) -> pd.DataFrame:
    """Summarize coverage by semantic feature family."""
    if inventory.empty:
        return pd.DataFrame()
    df = inventory.copy()
    if "feature_family" not in df.columns:
        df["feature_family"] = "unknown"
    df["feature_family"] = df["feature_family"].fillna("unknown").astype(str)
    df["null_rate"] = pd.to_numeric(df.get("null_rate"), errors="coerce")
    rows: list[dict[str, Any]] = []
    for family, group in df.groupby("feature_family", sort=True, dropna=False):
        null_rate = pd.to_numeric(group["null_rate"], errors="coerce").fillna(0.0)
        rows.append({
            "mode": mode,
            "feature_set": feature_set_id,
            "feature_family": family,
            "feature_count": int(len(group)),
            "median_null_rate": _safe_float(null_rate.median()),
            "max_null_rate": _safe_float(null_rate.max()),
            "missing_gt50": int((null_rate > 0.5).sum()),
            "missing_gt80": int((null_rate > 0.8).sum()),
            "constant_count": int(group.get("is_constant", pd.Series(False, index=group.index)).fillna(False).astype(bool).sum()),
        })
    return pd.DataFrame(rows)


def root_cause_findings(
    candidate_comparison: pd.DataFrame,
    feature_set_quality: pd.DataFrame,
    tail_recall: pd.DataFrame,
    baseline_audit: pd.DataFrame,
) -> list[str]:
    """Generate concise evidence-backed findings for the Markdown report."""
    findings: list[str] = []
    if not candidate_comparison.empty:
        best = candidate_comparison.sort_values("aggregate_mae", na_position="last").iloc[0]
        findings.append(
            "Best current Phase 7 candidate by MAE is "
            f"{best.get('feature_set')} / {best.get('model')} "
            f"with MAE={_safe_float(best.get('aggregate_mae')):.4f}, "
            f"RMSE={_safe_float(best.get('aggregate_rmse')):.4f}."
        )
        pass_count = int((candidate_comparison.get("promotion_gate_status") == "pass").sum())
        findings.append(f"Promotion gate pass count is {pass_count} of {len(candidate_comparison)}.")
    if not baseline_audit.empty:
        prior = baseline_audit.loc[baseline_audit["baseline_name"] == "prior_year"]
        if not prior.empty:
            beat_rate = prior["beats_baseline_rmse"].fillna(False).astype(bool).mean()
            findings.append(
                "Prior-year persistence remains the key hurdle: "
                f"models beat it on RMSE in {beat_rate:.0%} of candidate comparisons."
            )
    if not tail_recall.empty:
        recall = pd.to_numeric(tail_recall["bad_year_negative_recall"], errors="coerce")
        findings.append(
            "Downside recall is weak: median bad-year negative recall is "
            f"{_safe_float(recall.median()):.3f}."
        )
        extreme_valid = int(tail_recall["extreme_metric_validated"].fillna(False).astype(bool).sum())
        findings.append(
            "Extreme/quintile metrics are sample-size constrained: "
            f"{extreme_valid} of {len(tail_recall)} candidates have validated extreme samples."
        )
    if not feature_set_quality.empty:
        review = feature_set_quality.loc[feature_set_quality["gate"].astype(str) != "PASS"]
        findings.append(
            f"Feature quality gates mark {len(review)} of {len(feature_set_quality)} "
            "feature-set surfaces for review."
        )
    return findings


def _markdown_table(df: pd.DataFrame) -> str:
    """Render a small Markdown table without optional pandas dependencies."""
    if df.empty:
        return ""
    text = df.copy()
    for col in text.columns:
        text[col] = text[col].map(
            lambda value: ""
            if pd.isna(value)
            else f"{value:.4f}" if isinstance(value, float) else str(value)
        )
    headers = [str(col) for col in text.columns]
    rows = text.astype(str).values.tolist()
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(cell).replace("\n", " ") for cell in row) + " |")
    return "\n".join(lines)


def render_markdown_report(
    *,
    title: str,
    versions: dict[str, str],
    findings: list[str],
    candidate_comparison: pd.DataFrame,
    feature_set_quality: pd.DataFrame,
    tail_recall: pd.DataFrame,
    baseline_audit: pd.DataFrame,
) -> str:
    """Render a compact Phase 7 root-cause report."""
    lines = [f"# {title}", ""]
    lines.append("## Frozen Evidence")
    for key, value in versions.items():
        lines.append(f"- {key}: `{value}`")
    lines.append("")
    lines.append("## Findings")
    for finding in findings:
        lines.append(f"- {finding}")
    lines.append("")
    lines.append("## Candidate Leaderboard")
    if candidate_comparison.empty:
        lines.append("No matching certification reports were found.")
    else:
        cols = [
            "feature_set",
            "model",
            "aggregate_mae",
            "aggregate_rmse",
            "bad_year_negative_recall",
            "permutation_status",
            "promotion_gate_status",
            "promotion_recommendation",
        ]
        present = [col for col in cols if col in candidate_comparison.columns]
        lines.append(_markdown_table(candidate_comparison[present].head(20)))
    lines.append("")
    lines.append("## Feature Quality")
    if feature_set_quality.empty:
        lines.append("No feature quality rows were generated.")
    else:
        lines.append(_markdown_table(feature_set_quality))
    lines.append("")
    lines.append("## Baseline Interpretation")
    if baseline_audit.empty:
        lines.append("No baseline comparison rows were found.")
    else:
        by_baseline = (
            baseline_audit.groupby("baseline_name", dropna=False)
            .agg(
                candidates=("candidate_id", "nunique"),
                beat_rmse_rate=("beats_baseline_rmse", "mean"),
                median_rmse_delta=("model_minus_baseline_rmse", "median"),
                median_mae_delta=("model_minus_baseline_mae", "median"),
            )
            .reset_index()
        )
        lines.append(_markdown_table(by_baseline))
    lines.append("")
    lines.append("## Tail Recall Interpretation")
    if tail_recall.empty:
        lines.append("No tail-recall rows were found.")
    else:
        cols = [
            "feature_set",
            "model",
            "bad_year_negative_recall",
            "estimated_false_negative_count",
            "n_bad_year_independent_country_years",
            "quintile_directional_accuracy",
            "extreme_metric_validated",
            "permutation_status",
        ]
        present = [col for col in cols if col in tail_recall.columns]
        lines.append(_markdown_table(tail_recall[present].sort_values(
            ["bad_year_negative_recall", "estimated_false_negative_count"],
            ascending=[False, True],
            na_position="last",
        )))
    lines.append("")
    lines.append("## Recommended Next Actions")
    lines.extend([
        "- Do not expand to all commodities until corn has a candidate that beats prior-year persistence or has a clear alert-only use case.",
        "- Treat annual dense weather as a controlled ablation: it is not broken, but the first grid shows it diluted performance versus preseason core.",
        "- Keep WASDE snapshot composites out of serious sweeps until the sparse revision surface is fixed or explicitly stage-filtered.",
        "- Add alert-threshold evaluation on top of regression before building a separate tail classifier.",
        "- Compare against a persistence-aware model or include lagged anomaly/persistence features deliberately, because prior-year is the current benchmark to beat.",
    ])
    lines.append("")
    return "\n".join(lines)
