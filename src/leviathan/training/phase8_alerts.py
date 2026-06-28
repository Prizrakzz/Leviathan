"""Phase 8 persistence and downside-alert diagnostics."""
from __future__ import annotations

from typing import Any, Iterable

import pandas as pd

from leviathan.model_datasets.baselines import BASELINE_COLUMNS
from leviathan.training.certification import downside_alert_metrics, regression_metrics


FIXED_DOWNSIDE_THRESHOLDS = (-0.05, -0.10)


def _format_markdown_value(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value).replace("|", "\\|")


def _markdown_table(df: pd.DataFrame) -> str:
    if df.empty:
        return ""
    columns = [str(col) for col in df.columns]
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for row in df.itertuples(index=False, name=None):
        lines.append(
            "| " + " | ".join(_format_markdown_value(value) for value in row) + " |"
        )
    return "\n".join(lines)


def target_reframe_audit_frame(matrix: pd.DataFrame) -> pd.DataFrame:
    """Summarize target persistence and fixed downside-event counts."""
    required = {"country", "crop_year", "target_value"}
    missing = required - set(matrix.columns)
    if missing:
        raise ValueError(f"matrix missing required target columns: {sorted(missing)}")

    frame = matrix.copy()
    frame["target_value"] = pd.to_numeric(frame["target_value"], errors="coerce")
    if "prior_year_anomaly_baseline" in frame.columns:
        frame["prior_year_anomaly_baseline"] = pd.to_numeric(
            frame["prior_year_anomaly_baseline"], errors="coerce"
        )
        frame["target_residual_vs_prior_year"] = (
            frame["target_value"] - frame["prior_year_anomaly_baseline"]
        )
        frame["target_worsened_vs_prior_year"] = (
            frame["target_value"] < frame["prior_year_anomaly_baseline"]
        )
    else:
        frame["target_residual_vs_prior_year"] = pd.NA
        frame["target_worsened_vs_prior_year"] = pd.NA

    rows: list[dict[str, Any]] = []
    trainable = (
        frame.loc[frame["is_trainable"].fillna(False).astype(bool)].copy()
        if "is_trainable" in frame.columns else frame.copy()
    )
    for scope, group in [("all_rows", frame), ("trainable_rows", trainable)]:
        out: dict[str, Any] = {
            "scope": scope,
            "row_count": int(len(group)),
            "country_count": int(group["country"].nunique()) if "country" in group else 0,
            "year_min": int(group["crop_year"].min()) if len(group) else None,
            "year_max": int(group["crop_year"].max()) if len(group) else None,
            "target_non_null_count": int(group["target_value"].notna().sum()),
            "target_mean": float(group["target_value"].mean()) if len(group) else None,
            "target_median": float(group["target_value"].median()) if len(group) else None,
        }
        if "target_worsened_vs_prior_year" in group.columns:
            worsened = group["target_worsened_vs_prior_year"].dropna()
            out["worsened_vs_prior_year_count"] = int(worsened.sum()) if len(worsened) else 0
            out["worsened_vs_prior_year_rate"] = (
                float(worsened.mean()) if len(worsened) else None
            )
        for threshold in FIXED_DOWNSIDE_THRESHOLDS:
            name = str(abs(threshold)).replace(".", "p")
            events = group["target_value"] <= threshold
            out[f"downside_{name}_event_count"] = int(events.sum())
            out[f"downside_{name}_event_rate"] = (
                float(events.mean()) if len(group) else None
            )
        rows.append(out)
    return pd.DataFrame(rows)


def baseline_alert_metrics_frame(
    matrix: pd.DataFrame,
    *,
    baseline_columns: Iterable[str] | None = None,
    thresholds: tuple[float, ...] = FIXED_DOWNSIDE_THRESHOLDS,
) -> pd.DataFrame:
    """Evaluate materialized baselines as fixed-threshold alert policies."""
    required = {"country", "crop_year", "target_value"}
    missing = required - set(matrix.columns)
    if missing:
        raise ValueError(f"matrix missing required target columns: {sorted(missing)}")

    baseline_columns = tuple(baseline_columns or BASELINE_COLUMNS.values())
    trainable = (
        matrix.loc[matrix["is_trainable"].fillna(False).astype(bool)].copy()
        if "is_trainable" in matrix.columns else matrix.copy()
    )
    rows: list[dict[str, Any]] = []
    for baseline_col in baseline_columns:
        if baseline_col not in trainable.columns:
            continue
        predictions = trainable[["country", "crop_year", "target_value", baseline_col]].rename(
            columns={"target_value": "y_actual", baseline_col: "y_pred"}
        )
        reg = regression_metrics(predictions["y_actual"], predictions["y_pred"])
        alert = downside_alert_metrics(predictions, thresholds=thresholds)
        baseline_name = next(
            (
                name
                for name, column in BASELINE_COLUMNS.items()
                if column == baseline_col
            ),
            baseline_col,
        )
        for row in alert["rows"]:
            rows.append({
                "baseline_name": baseline_name,
                "baseline_column": baseline_col,
                "rmse": reg["rmse"],
                "mae": reg["mae"],
                "sign_accuracy": reg["sign_accuracy"],
                **row,
            })
    return pd.DataFrame(rows)


def render_phase8_markdown(
    *,
    target_audit: pd.DataFrame,
    baseline_alerts: pd.DataFrame,
    candidate_comparison: pd.DataFrame | None = None,
) -> str:
    """Render a compact Phase 8 report."""
    lines = [
        "# Phase 8 Persistence And Alert Evaluation",
        "",
        "## Target Reframe",
    ]
    if target_audit.empty:
        lines.append("No target audit rows were produced.")
    else:
        lines.append(_markdown_table(target_audit))

    lines.extend(["", "## Baseline Alert Metrics"])
    if baseline_alerts.empty:
        lines.append("No baseline alert rows were produced.")
    else:
        sort_cols = ["threshold", "alert_policy", "baseline_name"]
        ordered = baseline_alerts.sort_values(sort_cols)
        lines.append(
            _markdown_table(ordered[
                [
                    "baseline_name",
                    "threshold",
                    "alert_policy",
                    "n_events",
                    "n_alerts",
                    "recall",
                    "precision",
                    "false_negatives",
                    "f2_score",
                    "rmse",
                    "mae",
                ]
            ])
        )

    if candidate_comparison is not None:
        lines.extend(["", "## Candidate Comparison"])
        if candidate_comparison.empty:
            lines.append("No matching candidate certification reports were found.")
        else:
            display_cols = [
                col for col in [
                    "candidate_id",
                    "feature_set",
                    "model",
                    "aggregate_rmse",
                    "aggregate_mae",
                    "model_vs_best_baseline_rmse_delta",
                    "bad_year_negative_recall",
                    "downside_5pct_pred_lt_0_recall",
                    "downside_5pct_pred_lt_0_false_negatives",
                    "promotion_gate_status",
                ]
                if col in candidate_comparison.columns
            ]
            lines.append(
                _markdown_table(candidate_comparison[display_cols]
                .sort_values(["aggregate_mae", "candidate_id"], na_position="last")
                )
            )

    lines.extend([
        "",
        "## Interpretation Guardrails",
        "",
        "- RMSE/MAE baseline wins do not prove downside-alert usefulness.",
        "- Fixed-threshold recall and false negatives should be reviewed before wider sweeps.",
        "- Persistence features are target-history context and should stay model-ready-only.",
    ])
    return "\n".join(lines) + "\n"
