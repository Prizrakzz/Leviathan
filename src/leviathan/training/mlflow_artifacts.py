"""MLflow artifact helpers for experiment-readiness smoke runs.

The trainer writes large prediction outputs to S3 for Athena, but a researcher
should still be able to inspect a run from the MLflow UI.  These helpers log a
compact bundle of tables, JSON metadata, stepped metrics, a fitted model, and a
small replay sample that can prove the logged artifact still predicts.
"""
from __future__ import annotations

from dataclasses import asdict
import inspect
import json
import math
from pathlib import Path
import tempfile
import time
from typing import Any

import numpy as np
import pandas as pd
from sklearn.base import clone


def _json_safe(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return value
    if isinstance(value, np.generic):
        return _json_safe(value.item())
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return str(value)


def _safe_frame(df: pd.DataFrame, *, max_rows: int | None = None) -> pd.DataFrame:
    """Return a compact frame with JSON/parquet-friendly scalar values."""
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.head(max_rows).copy() if max_rows is not None else df.copy()
    for col in out.columns:
        if pd.api.types.is_object_dtype(out[col]):
            out[col] = out[col].map(_json_safe)
    return out.replace({np.nan: None})


def log_json_artifact(mlflow, payload: dict[str, Any], artifact_file: str) -> None:
    """Log JSON through MLflow with a tempfile fallback for older clients."""
    payload = _json_safe(payload)
    if hasattr(mlflow, "log_dict"):
        mlflow.log_dict(payload, artifact_file)
        return
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / Path(artifact_file).name
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        mlflow.log_artifact(str(path), artifact_path=str(Path(artifact_file).parent))


def log_text_artifact(mlflow, text: str, artifact_file: str) -> None:
    """Log a text artifact through MLflow with a tempfile fallback."""
    if hasattr(mlflow, "log_text"):
        mlflow.log_text(text, artifact_file)
        return
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / Path(artifact_file).name
        path.write_text(text, encoding="utf-8")
        mlflow.log_artifact(str(path), artifact_path=str(Path(artifact_file).parent))


def log_dataframe_artifacts(
    mlflow,
    df: pd.DataFrame | None,
    *,
    name: str,
    artifact_dir: str = "tables",
    max_rows: int | None = 1000,
) -> None:
    """Log a DataFrame as UI-friendly JSON plus replay-friendly parquet."""
    if df is None or df.empty:
        return
    frame = _safe_frame(df, max_rows=max_rows)
    json_path = f"{artifact_dir}/{name}.json"
    if hasattr(mlflow, "log_table"):
        mlflow.log_table(frame, artifact_file=json_path)
    else:
        log_json_artifact(mlflow, {"rows": frame.to_dict(orient="records")}, json_path)

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"{name}.parquet"
        frame.to_parquet(path, index=False)
        mlflow.log_artifact(str(path), artifact_path=artifact_dir)


def fold_metrics_frame(result) -> pd.DataFrame:
    """Return one row per walk-forward fold."""
    return pd.DataFrame([asdict(fold) for fold in result.folds])


def selected_features_frame(feature_cols: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        {"feature_rank": range(1, len(feature_cols) + 1), "feature": feature_cols}
    )


def feature_importance_frame(model: object, feature_cols: list[str]) -> pd.DataFrame:
    """Return fitted model feature importances when exposed by the estimator."""
    values = getattr(model, "feature_importances_", None)
    if values is None:
        return pd.DataFrame()
    arr = np.asarray(values, dtype=float)
    if len(arr) != len(feature_cols):
        return pd.DataFrame()
    out = pd.DataFrame({"feature": feature_cols, "importance": arr})
    return out.sort_values(["importance", "feature"], ascending=[False, True]).reset_index(drop=True)


def log_fold_step_metrics(mlflow, result) -> None:
    """Log fold metrics with test_year as the MLflow metric step."""
    try:
        run = mlflow.active_run()
        if run is not None:
            from mlflow.entities import Metric
            from mlflow.tracking import MlflowClient

            timestamp = int(time.time() * 1000)
            metrics = []
            for fold in result.folds:
                step = int(fold.test_year)
                for name, value in (
                    ("fold_rmse", fold.rmse),
                    ("fold_mae", fold.mae),
                    ("fold_directional_accuracy", fold.directional_accuracy),
                ):
                    if value is None or not np.isfinite(value):
                        continue
                    metrics.append(Metric(name, float(value), timestamp, step))
            if metrics:
                MlflowClient().log_batch(run.info.run_id, metrics=metrics)
            return
    except Exception:  # noqa: BLE001 - fall back to fluent calls for older clients
        pass

    for fold in result.folds:
        step = int(fold.test_year)
        for name, value in (
            ("fold_rmse", fold.rmse),
            ("fold_mae", fold.mae),
            ("fold_directional_accuracy", fold.directional_accuracy),
        ):
            if value is None or not np.isfinite(value):
                continue
            try:
                mlflow.log_metric(name, float(value), step=step)
            except TypeError:
                mlflow.log_metric(f"{name}_{step}", float(value))


def fit_final_model(model: object, train_df: pd.DataFrame, feature_cols: list[str], target_col: str):
    """Fit a fresh final model on all eligible training rows."""
    train = train_df.loc[train_df[target_col].notna()].copy()
    if train.empty:
        raise ValueError("cannot fit final model: no non-null target rows")
    fitted = clone(model)
    fitted.fit(train[feature_cols], train[target_col].astype(float))
    return fitted


def build_model_replay_sample(
    model: object,
    train_df: pd.DataFrame,
    feature_cols: list[str],
    target_col: str,
    *,
    max_rows: int = 200,
) -> pd.DataFrame:
    """Build a compact sample whose predictions must replay from the model artifact."""
    cols = ["country", "crop_year"] + feature_cols + [target_col]
    sample = train_df.loc[train_df[target_col].notna(), cols].sort_values(
        ["country", "crop_year"]
    )
    if len(sample) > max_rows:
        sample = sample.tail(max_rows)
    sample = sample.reset_index(drop=True)
    sample["y_pred_logged"] = np.asarray(model.predict(sample[feature_cols]), dtype=float)
    return sample


def _model_log_kwargs(log_model_fn, artifact_path: str) -> dict[str, Any]:
    """Handle MLflow 2.x artifact_path and MLflow 3.x name signatures."""
    params = inspect.signature(log_model_fn).parameters
    if "artifact_path" in params:
        return {"artifact_path": artifact_path}
    if "name" in params:
        return {"name": artifact_path}
    return {"artifact_path": artifact_path}


def log_fitted_model(
    mlflow,
    *,
    model: object,
    model_family: str,
    train_df: pd.DataFrame,
    feature_cols: list[str],
    target_col: str,
    artifact_path: str = "model",
    registered_model_name: str | None = None,
    registered_model_tags: dict[str, Any] | None = None,
) -> None:
    """Log the fitted estimator with the matching MLflow flavor."""
    input_example = train_df[feature_cols].head(5).copy()
    signature = None
    try:
        from mlflow.models import infer_signature

        signature = infer_signature(input_example, model.predict(input_example))
    except Exception:  # noqa: BLE001 - signature is valuable but not fatal
        signature = None

    if model_family == "xgboost":
        import mlflow.xgboost as flavor

        flavor_name = "xgboost"
    elif model_family == "lightgbm":
        import mlflow.lightgbm as flavor

        flavor_name = "lightgbm"
    else:
        import mlflow.sklearn as flavor

        flavor_name = "sklearn"

    kwargs = _model_log_kwargs(flavor.log_model, artifact_path)
    params = inspect.signature(flavor.log_model).parameters
    if "signature" in params and signature is not None:
        kwargs["signature"] = signature
    if "input_example" in params:
        kwargs["input_example"] = input_example
    if "serialization_format" in params:
        kwargs["serialization_format"] = "cloudpickle"
    if "pip_requirements" in params:
        kwargs["pip_requirements"] = [
            "pandas",
            "numpy",
            "scikit-learn",
            "xgboost" if model_family == "xgboost" else "lightgbm",
        ]
    if registered_model_name and "registered_model_name" in params:
        kwargs["registered_model_name"] = registered_model_name
    model_info = flavor.log_model(model, **kwargs)
    if registered_model_name and "registered_model_name" not in params:
        model_uri = getattr(model_info, "model_uri", None)
        if not model_uri:
            run = mlflow.active_run()
            if run is not None:
                model_uri = f"runs:/{run.info.run_id}/{artifact_path}"
        if model_uri:
            mlflow.register_model(model_uri, registered_model_name)
    mlflow.set_tag("fitted_model_artifact_path", artifact_path)
    mlflow.set_tag("fitted_model_flavor", flavor_name)
    if registered_model_name:
        mlflow.set_tag("registered_model_name", registered_model_name)
    if registered_model_name and registered_model_tags:
        try:
            from mlflow.tracking import MlflowClient

            run = mlflow.active_run()
            run_id = run.info.run_id if run is not None else None
            client = MlflowClient()
            versions = client.search_model_versions(f"name='{registered_model_name}'")
            for version in versions:
                if run_id is not None and version.run_id != run_id:
                    continue
                for key, value in registered_model_tags.items():
                    if value is not None:
                        client.set_model_version_tag(
                            registered_model_name,
                            version.version,
                            str(key),
                            str(value),
                        )
                mlflow.set_tag("registered_model_version", str(version.version))
                break
        except Exception as exc:  # noqa: BLE001 - run tags still preserve provenance
            mlflow.set_tag("registered_model_tagging_error", str(exc))


def build_training_log_text(
    *,
    run_id: str,
    args: object,
    feature_cols: list[str],
    train_df: pd.DataFrame,
    result,
    predictions_uri: str | None,
    extra: dict[str, Any] | None = None,
) -> str:
    """Build a compact text artifact for the MLflow UI."""
    env_keys = [
        "AWS_BATCH_JOB_ID",
        "AWS_BATCH_JOB_ATTEMPT",
        "AWS_BATCH_JOB_QUEUE",
        "AWS_BATCH_JOB_DEFINITION",
        "AWS_REGION",
    ]
    lines = [
        "Leviathan MLflow training run",
        f"run_id={run_id}",
        f"commodity={getattr(args, 'commodity', '')}",
        f"model={getattr(args, 'model', '')}",
        f"selection={getattr(args, 'feature_set', None) or getattr(args, 'tier', '')}",
        f"target={getattr(args, 'target_key', None) or getattr(args, 'target', '')}",
        f"dataset_version={getattr(args, 'dataset_version', None)}",
        f"model_dataset_version={getattr(args, 'model_dataset_version', None)}",
        f"source_dataset_version={getattr(args, 'source_dataset_version', None)}",
        f"cv_policy={getattr(args, 'cv_policy', '')}",
        f"min_train_years={getattr(args, 'min_train_years', '')}",
        f"train_start_year={getattr(args, 'train_start_year', '')}",
        f"rolling_window_years={getattr(args, 'rolling_window_years', '')}",
        f"n_train_rows={len(train_df)}",
        f"n_features={len(feature_cols)}",
        f"n_folds={result.n_folds}",
        f"rmse={result.rmse}",
        f"mae={result.mae}",
        f"directional_accuracy={result.directional_accuracy}",
        f"predictions_uri={predictions_uri or ''}",
    ]
    for key in env_keys:
        value = __import__("os").environ.get(key)
        if value:
            lines.append(f"{key}={value}")
    for key, value in (extra or {}).items():
        lines.append(f"{key}={value}")
    return "\n".join(lines) + "\n"


def log_experiment_review_bundle(
    mlflow,
    *,
    result,
    predictions: pd.DataFrame,
    train_df: pd.DataFrame,
    feature_cols: list[str],
    target_col: str,
    final_model: object,
    replay_sample: pd.DataFrame,
    baseline_metrics: pd.DataFrame | None,
    gaps: pd.DataFrame | None,
    args: object,
    run_id: str,
    predictions_uri: str | None,
    logged_metadata: dict[str, Any],
) -> None:
    """Log all compact review artifacts needed for Phase 10 certification."""
    log_fold_step_metrics(mlflow, result)
    log_dataframe_artifacts(mlflow, predictions, name="cv_predictions", max_rows=2000)
    log_dataframe_artifacts(mlflow, fold_metrics_frame(result), name="fold_metrics")
    log_dataframe_artifacts(mlflow, result.sliced_metrics, name="slice_metrics")
    log_dataframe_artifacts(mlflow, baseline_metrics, name="baseline_comparison")
    log_dataframe_artifacts(mlflow, gaps, name="gap_checks")
    log_dataframe_artifacts(mlflow, selected_features_frame(feature_cols), name="selected_features")
    log_dataframe_artifacts(mlflow, replay_sample, name="model_replay_sample")
    log_dataframe_artifacts(
        mlflow,
        feature_importance_frame(final_model, feature_cols),
        name="feature_importance",
    )
    log_json_artifact(
        mlflow,
        {
            "feature_cols": feature_cols,
            "target_col": target_col,
            "n_train_rows": int(len(train_df)),
            "n_features": int(len(feature_cols)),
            "n_folds": int(result.n_folds),
            "metrics": _json_safe(result.as_mlflow_metrics()),
            "logged_metadata": _json_safe(logged_metadata),
        },
        "metadata/training_summary.json",
    )
    log_json_artifact(
        mlflow,
        {"feature_cols": feature_cols},
        "metadata/selected_features.json",
    )
    log_text_artifact(
        mlflow,
        build_training_log_text(
            run_id=run_id,
            args=args,
            feature_cols=feature_cols,
            train_df=train_df,
            result=result,
            predictions_uri=predictions_uri,
            extra={
                "feature_set_sha": logged_metadata.get("feature_set_sha"),
                "data_fingerprint": logged_metadata.get("data_fingerprint"),
            },
        ),
        "logs/training.log",
    )
