"""Phase 7 smoke wrapper for WASDE snapshot training."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pandas as pd

from leviathan.model_datasets.wasde_snapshot_diagnostics import (
    WasdeSnapshotDiagnosticsReport,
    diagnose_wasde_snapshot_matrix,
)
from leviathan.training.wasde_snapshot_cv import (
    SnapshotCVResult,
    ensure_snapshot_cv_columns,
    run_grouped_walk_forward_cv,
)


@dataclass(frozen=True)
class WasdeSnapshotSmokeResult:
    """Combined diagnostics and training-smoke output."""

    diagnostics: WasdeSnapshotDiagnosticsReport
    cv_result: SnapshotCVResult | None
    readiness: dict[str, object]


def run_wasde_snapshot_training_smoke(
    matrix: pd.DataFrame,
    *,
    model: object,
    feature_stack_id: str,
    feature_columns: Iterable[str] | None = None,
    static_manifest: pd.DataFrame | None = None,
    min_train_years: int = 5,
    min_trainable_annual_groups: int = 20,
    min_event_groups: int = 5,
    min_non_null_rate: float = 0.2,
    collapse_policy: str = "latest",
) -> WasdeSnapshotSmokeResult:
    """Run diagnostics, then grouped walk-forward CV if the matrix is not failed."""
    matrix = ensure_snapshot_cv_columns(matrix)
    diagnostics = diagnose_wasde_snapshot_matrix(
        matrix,
        feature_columns=feature_columns,
        static_manifest=static_manifest,
        min_trainable_annual_groups=min_trainable_annual_groups,
        min_event_groups=min_event_groups,
    )
    if diagnostics.readiness["status"] == "fail":
        return WasdeSnapshotSmokeResult(
            diagnostics=diagnostics,
            cv_result=None,
            readiness={
                **diagnostics.readiness,
                "training_status": "skipped_failed_diagnostics",
            },
        )

    try:
        cv = run_grouped_walk_forward_cv(
            matrix,
            model=model,
            feature_stack_id=feature_stack_id,
            feature_columns=feature_columns,
            min_train_years=min_train_years,
            min_non_null_rate=min_non_null_rate,
            collapse_policy=collapse_policy,
        )
    except ValueError as exc:
        return WasdeSnapshotSmokeResult(
            diagnostics=diagnostics,
            cv_result=None,
            readiness={
                **diagnostics.readiness,
                "status": "fail",
                "training_status": "failed_cv",
                "training_error": str(exc),
            },
        )
    baseline_zero = cv.baseline_diagnostics.loc[
        cv.baseline_diagnostics["baseline_name"] == "zero_anomaly"
    ]
    baseline_mae = (
        float(baseline_zero["mae"].iloc[0])
        if not baseline_zero.empty and pd.notna(baseline_zero["mae"].iloc[0])
        else float("nan")
    )
    model_mae = float(cv.annual_metrics.get("mae", float("nan")))
    readiness = {
        **diagnostics.readiness,
        "training_status": "completed",
        "cv_fold_count": len(cv.folds),
        "feature_stack_id": feature_stack_id,
        "selected_feature_count": len(cv.feature_columns),
        "model_annual_mae": model_mae,
        "zero_baseline_mae": baseline_mae,
        "model_minus_zero_baseline_mae": (
            model_mae - baseline_mae
            if pd.notna(model_mae) and pd.notna(baseline_mae)
            else float("nan")
        ),
        "model_downside_recall": cv.annual_metrics.get("recall", float("nan")),
        "model_false_negative_count": cv.annual_metrics.get("false_negative_count", float("nan")),
    }
    return WasdeSnapshotSmokeResult(
        diagnostics=diagnostics,
        cv_result=cv,
        readiness=readiness,
    )
