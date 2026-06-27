"""Replay verification for MLflow model artifacts."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class ReplayVerificationResult:
    run_id: str
    status: str
    n_rows: int
    max_abs_error: float
    mean_abs_error: float
    tolerance: float
    model_uri: str
    sample_artifact: str

    @property
    def passed(self) -> bool:
        return self.status == "pass"

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "n_rows": self.n_rows,
            "max_abs_error": self.max_abs_error,
            "mean_abs_error": self.mean_abs_error,
            "tolerance": self.tolerance,
            "model_uri": self.model_uri,
            "sample_artifact": self.sample_artifact,
        }


def compare_logged_predictions(
    logged: pd.Series | np.ndarray,
    replayed: pd.Series | np.ndarray,
    *,
    tolerance: float,
) -> tuple[str, float, float]:
    """Compare logged and replayed predictions."""
    logged_arr = np.asarray(logged, dtype=float)
    replayed_arr = np.asarray(replayed, dtype=float)
    if logged_arr.shape != replayed_arr.shape:
        raise ValueError(
            f"prediction shape mismatch: logged={logged_arr.shape}, replayed={replayed_arr.shape}"
        )
    errors = np.abs(logged_arr - replayed_arr)
    max_error = float(errors.max()) if len(errors) else 0.0
    mean_error = float(errors.mean()) if len(errors) else 0.0
    return ("pass" if max_error <= tolerance else "fail", max_error, mean_error)


def verify_mlflow_run_replay(
    run_id: str,
    *,
    tracking_uri: str | None = None,
    tolerance: float = 1e-8,
    model_artifact_path: str = "model",
    sample_artifact_path: str = "tables/model_replay_sample.parquet",
    feature_artifact_path: str = "metadata/selected_features.json",
) -> ReplayVerificationResult:
    """Load a run's model artifact and verify it replays logged sample predictions."""
    import mlflow

    if tracking_uri:
        mlflow.set_tracking_uri(tracking_uri)

    feature_path = mlflow.artifacts.download_artifacts(
        run_id=run_id,
        artifact_path=feature_artifact_path,
    )
    features = json.loads(Path(feature_path).read_text(encoding="utf-8"))["feature_cols"]
    sample_path = mlflow.artifacts.download_artifacts(
        run_id=run_id,
        artifact_path=sample_artifact_path,
    )
    sample = pd.read_parquet(sample_path)
    missing = sorted(set(features) - set(sample.columns))
    if missing:
        raise ValueError(f"replay sample missing feature columns: {missing}")
    if "y_pred_logged" not in sample.columns:
        raise ValueError("replay sample missing y_pred_logged")

    model_uri = f"runs:/{run_id}/{model_artifact_path}"
    model = mlflow.pyfunc.load_model(model_uri)
    replayed = model.predict(sample[features])
    status, max_error, mean_error = compare_logged_predictions(
        sample["y_pred_logged"], replayed, tolerance=tolerance,
    )
    return ReplayVerificationResult(
        run_id=run_id,
        status=status,
        n_rows=int(len(sample)),
        max_abs_error=max_error,
        mean_abs_error=mean_error,
        tolerance=tolerance,
        model_uri=model_uri,
        sample_artifact=sample_artifact_path,
    )
