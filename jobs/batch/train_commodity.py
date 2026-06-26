"""Train one commodity model and log a fully-reproducible MLflow run.

The experiment runner that ties the training stack together:

  gold/feature_matrix  → pick a TIER's feature columns (configs/features/
  feature_tiers.yaml) → anti-leakage walk-forward CV (leviathan.training.cv) →
  slice/stress metrics + governance gaps (leviathan.training.slices) →
  reproducibility logging (leviathan.training.tracking) → MLflow.

Feature selection is config-driven: you pass ``--tier`` (a named feature set),
never a column list.  To change a model's features, edit feature_tiers.yaml —
the feature_set_sha changes automatically and MLflow tags every run with it.

Also writes the per-(country, crop_year) predictions to
``silver/model_predictions/`` so results are queryable in Athena alongside the
MLflow UI.

Invoked by the ``leviathan-dev-train`` Batch job definition:
    python jobs/batch/train_commodity.py --commodity corn_cbot --tier climate \
        --target production_quantity --model xgboost
"""
from __future__ import annotations

import argparse
import datetime
import io
import logging
import os
import sys
from pathlib import Path

import boto3
import numpy as np
import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from leviathan.features.feature_sets import selected_features_for_set  # noqa: E402
from leviathan.features.registry import load_registry          # noqa: E402
from leviathan.features.windows import resolve_tier_families    # noqa: E402
from leviathan.storage.paths import gold_feature_set_version_key  # noqa: E402
from leviathan.training.cv import walk_forward_cv               # noqa: E402
from leviathan.training.model_ready import (                    # noqa: E402
    attach_model_ready_baselines_to_predictions,
    load_model_ready_training_dataset,
    model_ready_baseline_metrics_for_predictions,
    model_ready_metric_log_values,
    sanitize_artifact_name,
)
from leviathan.training.slices import (                         # noqa: E402
    evaluate_gaps, gaps_passed, load_gap_rules, quintile_directional_accuracy,
)
from leviathan.training.tracking import log_training_run        # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("train_commodity")

_REPO = Path(__file__).resolve().parents[2]
_MATRIX_PREFIX = "gold/feature_matrix/"
_MATRIX_VERSION_PREFIX = "gold/feature_matrix_versions/"
_PRED_PREFIX = "silver/model_predictions/"
_TIERS_PATH = _REPO / "configs" / "features" / "feature_tiers.yaml"
_CONFIG_DIR = _REPO / "configs" / "features"


def _str2bool(v) -> bool:
    """Parse a bool that may arrive bare (``--detrend``) or valued (``--detrend true``).

    The Batch job definition substitutes ``Ref::detrend`` → "true"/"false" as a CLI
    *value*, while local/manual use passes the bare flag — both must work.
    """
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("1", "true", "yes", "y", "on")


def _optional_ref(value: str | None) -> str | None:
    """Normalize optional AWS Batch Ref parameters.

    Batch job definitions cannot reliably preserve empty-string defaults.  Use
    ``none`` in the job definition and normalize it back to ``None`` here.
    """
    if value is None:
        return None
    normalized = str(value).strip()
    if normalized.lower() in {"", "none", "null"}:
        return None
    return normalized


def _make_model(name: str, **hp):
    """Tree regressors — NaN-native, no scaling needed (missingness-as-signal)."""
    common = dict(
        n_estimators=hp.get("n_estimators", 400),
        max_depth=hp.get("max_depth", 4),
        learning_rate=hp.get("learning_rate", 0.03),
        subsample=hp.get("subsample", 0.8),
        reg_lambda=hp.get("reg_lambda", 1.0),
        min_child_weight=hp.get("min_child_weight", 1),
    )
    if name == "xgboost":
        from xgboost import XGBRegressor
        return XGBRegressor(**common, colsample_bytree=hp.get("colsample_bytree", 0.8), n_jobs=-1)
    if name == "lightgbm":
        from lightgbm import LGBMRegressor
        return LGBMRegressor(**common, colsample_bytree=hp.get("colsample_bytree", 0.8),
                             n_jobs=-1, verbose=-1)
    raise SystemExit(f"unknown --model {name!r} (xgboost|lightgbm)")


def _detrend_target(matrix: pd.DataFrame, target_col: str, min_years: int = 5) -> pd.DataFrame:
    """Replace the level target with its fractional deviation from a TRAILING
    linear trend, per country (anti-leakage: the trend uses only years < Y).

    Stress/anomaly features predict *deviations*, not levels — a level target is
    ~95% a deterministic area×yield trend that swamps the signal.  This turns the
    problem into "production surprise vs the trend extrapolation", which the
    features can actually move.  Years without ``min_years`` of prior data → NaN
    (dropped by CV).
    """
    df = matrix.copy()
    out = pd.Series(np.nan, index=df.index)
    for _, grp in df.groupby("country"):
        g = grp[["crop_year", target_col]].dropna(subset=[target_col]).sort_values("crop_year")
        years = g["crop_year"].to_numpy(dtype=float)
        vals = g[target_col].to_numpy(dtype=float)
        for i in range(len(g)):
            if i < min_years:
                continue
            coeffs = np.polyfit(years[:i], vals[:i], 1)        # trend on prior years only
            trend = np.polyval(coeffs, years[i])
            if trend != 0:
                out.loc[g.index[i]] = (vals[i] - trend) / abs(trend)
    df[target_col] = out
    return df


def _read_matrix(
    s3,
    bucket: str,
    commodity: str,
    dataset_version: str | None = None,
) -> pd.DataFrame | None:
    if dataset_version:
        prefix = (
            f"{_MATRIX_VERSION_PREFIX}"
            f"dataset_version={dataset_version}/"
            f"commodity={commodity}/"
        )
    else:
        prefix = f"{_MATRIX_PREFIX}commodity={commodity}/"
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            if obj["Key"].endswith(".parquet"):
                body = s3.get_object(Bucket=bucket, Key=obj["Key"])["Body"].read()
                return pd.read_parquet(io.BytesIO(body))
    return None


def _tier_feature_cols(matrix: pd.DataFrame, tier: str) -> list[str]:
    tiers = yaml.safe_load(_TIERS_PATH.read_text(encoding="utf-8"))["tiers"]
    fams = set(resolve_tier_families(tiers, tier))
    candidates = [
        c for c in matrix.columns
        if c not in ("country", "crop_year") and not c.startswith("label_")
    ]
    return [c for c in candidates if c in fams or any(c.startswith(f + "_") for f in fams)]


def _read_feature_set_membership(s3, bucket: str, dataset_version: str) -> pd.DataFrame:
    key = gold_feature_set_version_key(dataset_version)
    body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
    return pd.read_parquet(io.BytesIO(body))


def _feature_set_cols(
    matrix: pd.DataFrame,
    membership: pd.DataFrame,
    feature_set_id: str,
) -> tuple[list[str], dict[str, str]]:
    selected = selected_features_for_set(membership, feature_set_id)
    feature_cols = [feature for feature in selected if feature in matrix.columns]
    rows = membership.loc[membership["feature_set_id"] == feature_set_id]
    if rows.empty:
        return [], {}
    return feature_cols, {
        "feature_set_id": feature_set_id,
        "feature_set_version": str(rows["feature_set_version"].iloc[0]),
        "feature_set_catalog_sha": str(rows["feature_set_sha"].iloc[0]),
    }


def _write_predictions(s3, bucket, args, predictions, run_id, feature_set_sha) -> str | None:
    if predictions.empty:
        return None
    selection_name = args.feature_set or args.tier
    target_name = args.target_key or args.target
    df = predictions.copy()
    df["commodity"] = args.commodity
    df["tier"] = selection_name
    df["feature_set_id"] = selection_name
    df["target"] = target_name
    if args.model_dataset_version:
        df["dataset_key"] = args.dataset_key
        df["target_key"] = args.target_key
        df["model_dataset_version"] = args.model_dataset_version
        if args.source_dataset_version:
            df["source_dataset_version"] = args.source_dataset_version
    df["model"] = args.model
    df["feature_set_sha"] = feature_set_sha
    df["run_id"] = run_id
    df["as_of_date"] = datetime.date.today().isoformat()
    pred_date = datetime.date.today().isoformat()
    dataset_part = f"{args.dataset_key}__" if args.model_dataset_version else ""
    key = (
        f"{_PRED_PREFIX}model_family=tier1_production/prediction_date={pred_date}/"
        f"{args.commodity}__{selection_name}__{dataset_part}{target_name}__{args.model}.parquet"
    )
    buf = io.BytesIO()
    df.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
    s3.put_object(Bucket=bucket, Key=key, Body=buf.getvalue())
    return f"s3://{bucket}/{key}"


def _optuna_search(matrix, target_col, feature_cols, args, mlflow) -> dict:
    """Search hyperparameters with Optuna, maximising quintile-directional accuracy
    (the design's primary metric).  Each trial is a full walk-forward CV; the best
    params are returned and logged."""
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)

    def objective(trial):
        hp = dict(
            max_depth=trial.suggest_int("max_depth", 2, 5),
            learning_rate=trial.suggest_float("learning_rate", 0.01, 0.2, log=True),
            n_estimators=trial.suggest_int("n_estimators", 100, 600),
            reg_lambda=trial.suggest_float("reg_lambda", 0.1, 10.0, log=True),
            min_child_weight=trial.suggest_int("min_child_weight", 1, 10),
            subsample=trial.suggest_float("subsample", 0.6, 1.0),
            colsample_bytree=trial.suggest_float("colsample_bytree", 0.6, 1.0),
        )
        try:
            res = walk_forward_cv(matrix, target_col, feature_cols,
                                  _make_model(args.model, **hp),
                                  min_train_years=args.min_train_years)
        except ValueError:
            return -1.0
        score = quintile_directional_accuracy(res.predictions)
        return -1.0 if np.isnan(score) else score

    study = optuna.create_study(direction="maximize")
    study.optimize(objective, n_trials=args.n_trials, show_progress_bar=False)
    mlflow.set_tag("hpo", "optuna")
    mlflow.log_param("n_trials", args.n_trials)
    mlflow.log_metric("best_quintile_dir_acc", study.best_value)
    for k, v in study.best_params.items():
        mlflow.log_param(f"hp_{k}", v)
    logger.info("optuna best quintile_dir_acc=%.3f params=%s", study.best_value, study.best_params)
    return study.best_params


def main() -> None:
    parser = argparse.ArgumentParser(description="Train one commodity model to MLflow.")
    parser.add_argument("--commodity", required=True)
    parser.add_argument("--tier", default="climate",
                        help="named feature set: fundamentals|climate|trade_condition|full")
    parser.add_argument(
        "--feature-set",
        default=None,
        dest="feature_set",
        help=(
            "Model-purpose feature set resolved from gold/feature_set_versions "
            "for --dataset-version. Overrides --tier when provided."
        ),
    )
    parser.add_argument("--target", default="production_quantity",
                        help="label target (production_quantity|area_harvested|yield)")
    parser.add_argument("--model", default="xgboost", help="xgboost|lightgbm")
    parser.add_argument("--detrend", nargs="?", const=True, default=False, type=_str2bool,
                        help="predict fractional deviation from a trailing trend (anomaly), "
                             "not the level — the recommended target for stress features. "
                             "Bare flag or 'true'/'false' (Batch passes a value).")
    parser.add_argument("--bucket", default=os.environ.get("LEVIATHAN_BUCKET"))
    parser.add_argument("--aws-region", default=os.environ.get("AWS_REGION", "us-east-1"),
                        dest="aws_region")
    parser.add_argument("--experiment", default="leviathan-tier1-production")
    parser.add_argument("--tracking-uri", default=os.environ.get("MLFLOW_TRACKING_URI"),
                        dest="tracking_uri")
    parser.add_argument(
        "--dataset-version", default=None, dest="dataset_version",
        help=(
            "Read immutable gold/feature_matrix_versions/dataset_version=... "
            "instead of mutable gold/feature_matrix."
        ),
    )
    parser.add_argument(
        "--model-dataset-version", default=None, dest="model_dataset_version",
        help=(
            "Read Phase 8 gold/model_ready_matrices/dataset_version=... instead "
            "of legacy feature matrices."
        ),
    )
    parser.add_argument(
        "--dataset-key", default="annual_physical_anomaly", dest="dataset_key",
        help="Model-ready dataset_key, e.g. annual_physical_anomaly.",
    )
    parser.add_argument(
        "--target-key", default=None, dest="target_key",
        help="Model-ready target_key, e.g. production_anomaly_pct.",
    )
    parser.add_argument(
        "--source-dataset-version", default=None, dest="source_dataset_version",
        help=(
            "Optional source gold dataset version for model-ready feature-set lookup. "
            "Usually inferred from the model-ready manifest."
        ),
    )
    parser.add_argument("--min-train-years", type=int, default=10, dest="min_train_years")
    parser.add_argument("--no-snapshot", action="store_true")
    # manual hyperparameters (ignored under --optuna)
    parser.add_argument("--max-depth", type=int, default=4, dest="max_depth")
    parser.add_argument("--n-estimators", type=int, default=400, dest="n_estimators")
    parser.add_argument("--learning-rate", type=float, default=0.03, dest="learning_rate")
    parser.add_argument("--reg-lambda", type=float, default=1.0, dest="reg_lambda")
    # hyperparameter search
    parser.add_argument("--optuna", nargs="?", const=True, default=False, type=_str2bool,
                        help="search hyperparameters with Optuna (bare flag or 'true'/'false')")
    parser.add_argument("--n-trials", type=int, default=30, dest="n_trials")
    args = parser.parse_args()
    args.dataset_version = _optional_ref(args.dataset_version)
    args.model_dataset_version = _optional_ref(args.model_dataset_version)
    args.dataset_key = _optional_ref(args.dataset_key) or "annual_physical_anomaly"
    args.target_key = _optional_ref(args.target_key)
    args.source_dataset_version = _optional_ref(args.source_dataset_version)
    args.feature_set = _optional_ref(args.feature_set)
    if not args.bucket:
        raise SystemExit("LEVIATHAN_BUCKET (or --bucket) is required")

    import mlflow
    if args.tracking_uri:
        mlflow.set_tracking_uri(args.tracking_uri)
    mlflow.set_experiment(args.experiment)

    s3 = boto3.client("s3", region_name=args.aws_region)
    model_ready_dataset = None
    model_ready_mode = bool(args.model_dataset_version)

    if model_ready_mode:
        if args.dataset_version:
            raise SystemExit("--dataset-version and --model-dataset-version are mutually exclusive")
        if args.detrend:
            raise SystemExit(
                "--detrend is not valid with --model-dataset-version; "
                "targets are already anomaly values"
            )
        if not args.target_key:
            raise SystemExit("--target-key is required with --model-dataset-version")
        selection_name = args.feature_set or args.tier
        if not selection_name:
            raise SystemExit("--feature-set or --tier is required")

        model_ready_dataset = load_model_ready_training_dataset(
            s3,
            bucket=args.bucket,
            model_dataset_version=args.model_dataset_version,
            dataset_key=args.dataset_key,
            commodity=args.commodity,
            target_key=args.target_key,
            feature_set_id=selection_name,
            source_dataset_version=args.source_dataset_version,
        )
        args.source_dataset_version = model_ready_dataset.source_dataset_version
        args.feature_set = selection_name
        matrix = model_ready_dataset.matrix
        train_slice = model_ready_dataset.train_df
        target_col = model_ready_dataset.target_col
        feature_cols = model_ready_dataset.feature_cols
        feature_set_meta = model_ready_dataset.feature_set_meta
        if train_slice.empty:
            logger.warning(
                "%s %s/%s has no trainable model-ready rows - skipping.",
                args.commodity, args.dataset_key, args.target_key,
            )
            return
    else:
        matrix = _read_matrix(s3, args.bucket, args.commodity, args.dataset_version)
    if matrix is None or matrix.empty:
        suffix = f" dataset_version={args.dataset_version}" if args.dataset_version else ""
        raise SystemExit(f"no feature_matrix for {args.commodity}{suffix}")

    target_col = f"label_{args.target}"
    if (not model_ready_mode) and (
        target_col not in matrix.columns or matrix[target_col].notna().sum() == 0
    ):
        logger.warning("%s has no %s labels — skipping.", args.commodity, target_col)
        return  # clean skip (exit 0): an expected gap, not a failure

    if (not model_ready_mode) and args.detrend:
        matrix = _detrend_target(matrix, target_col)
        if matrix[target_col].notna().sum() == 0:
            logger.warning("%s: detrend left no usable target — skipping.", args.commodity)
            return

    feature_set_meta: dict[str, str] = {}
    if (not model_ready_mode) and args.feature_set:
        if not args.dataset_version:
            raise SystemExit("--feature-set requires --dataset-version")
        membership = _read_feature_set_membership(s3, args.bucket, args.dataset_version)
        feature_cols, feature_set_meta = _feature_set_cols(
            matrix, membership, args.feature_set
        )
        selection_name = args.feature_set
    else:
        feature_cols = _tier_feature_cols(matrix, args.tier)
        selection_name = args.tier
    if model_ready_mode and model_ready_dataset is not None:
        target_col = model_ready_dataset.target_col
        feature_cols = model_ready_dataset.feature_cols
        feature_set_meta = model_ready_dataset.feature_set_meta
        selection_name = model_ready_dataset.feature_set_id
        train_slice = model_ready_dataset.train_df
    if not feature_cols:
        logger.warning("%s tier %s resolved to 0 feature columns — skipping.",
                       args.commodity, selection_name)
        return

    registry = load_registry(_CONFIG_DIR)
    target_name = args.target_key if model_ready_mode else args.target
    run_suffix = args.dataset_key if model_ready_mode else ("detrend" if args.detrend else "")
    run_name_parts = [args.commodity, selection_name, str(target_name)]
    if run_suffix:
        run_name_parts.append(str(run_suffix))
    run_name_parts.append(args.model)
    run_name = "-".join(run_name_parts)

    if not model_ready_mode:
        train_slice = matrix[["country", "crop_year"] + feature_cols + [target_col]].copy()
    training_matrix = train_slice if model_ready_mode else matrix

    with mlflow.start_run(run_name=run_name) as run:
        if args.optuna:
            best = _optuna_search(training_matrix, target_col, feature_cols, args, mlflow)
            model = _make_model(args.model, **best)
        else:
            model = _make_model(
                args.model, max_depth=args.max_depth, n_estimators=args.n_estimators,
                learning_rate=args.learning_rate, reg_lambda=args.reg_lambda,
            )
        try:
            result = walk_forward_cv(
                training_matrix, target_col, feature_cols, model,
                min_train_years=args.min_train_years,
            )
        except ValueError as exc:
            logger.warning("%s: insufficient data for walk-forward CV — %s", args.commodity, exc)
            mlflow.set_tag("status", "skipped_insufficient_data")
            return

        result.with_slices(args.commodity)
        gaps = evaluate_gaps(result.sliced_metrics, load_gap_rules()) \
            if result.sliced_metrics is not None else None

        mlflow.set_tag("model", args.model)
        mlflow.set_tag("target", target_name)
        mlflow.set_tag("detrend", str(args.detrend))
        mlflow.set_tag("feature_selection_mode", "feature_set" if args.feature_set else "tier")
        for key, value in feature_set_meta.items():
            mlflow.set_tag(key, value)
        model_ready_tags: dict[str, str] = {}
        model_ready_params: dict[str, int | str] = {}
        if model_ready_dataset is not None:
            model_ready_tags = {
                "training_dataset_kind": "gold_model_ready",
                "model_dataset_version": args.model_dataset_version,
                "source_gold_dataset_version": model_ready_dataset.source_dataset_version,
                "dataset_key": args.dataset_key,
                "target_key": args.target_key,
                "model_ready_manifest_uri": model_ready_dataset.manifest_uri,
                "model_ready_matrix_uri": model_ready_dataset.matrix_uri,
                "baseline_metrics_uri": model_ready_dataset.baseline_metrics_uri,
            }
            if model_ready_dataset.manifest.get("target_config_sha"):
                model_ready_tags["target_config_sha"] = str(
                    model_ready_dataset.manifest["target_config_sha"]
                )
            model_ready_params = {
                "model_ready_total_rows": int(len(model_ready_dataset.matrix)),
                "model_ready_trainable_rows": int(len(train_slice)),
                "model_ready_excluded_rows": int(
                    len(model_ready_dataset.matrix) - len(train_slice)
                ),
            }
            for key, value in model_ready_tags.items():
                if value is not None:
                    mlflow.set_tag(key, value)
        if args.dataset_version:
            mlflow.set_tag("dataset_version", args.dataset_version)
            mlflow.set_tag(
                "feature_matrix_uri",
                (
                    f"s3://{args.bucket}/{_MATRIX_VERSION_PREFIX}"
                    f"dataset_version={args.dataset_version}/commodity={args.commodity}/"
                ),
            )
        q_dir = quintile_directional_accuracy(result.predictions)
        if not np.isnan(q_dir):
            mlflow.log_metric("quintile_directional_accuracy", q_dir)

        predictions_to_write = result.predictions
        if model_ready_dataset is not None:
            baseline_eval = model_ready_baseline_metrics_for_predictions(
                result.predictions,
                model_ready_dataset.matrix,
            )
            for key, value in model_ready_metric_log_values(
                result.predictions, baseline_eval
            ).items():
                mlflow.log_metric(key, value)
            predictions_to_write = attach_model_ready_baselines_to_predictions(
                result.predictions,
                model_ready_dataset.matrix,
            )

        logged = log_training_run(
            args.commodity, selection_name, train_slice, feature_cols, result,
            target_col=target_col, params_hash=registry.params_hash,
            bucket=args.bucket, aws_region=args.aws_region, mlflow=mlflow,
            snapshot=not args.no_snapshot, gaps=gaps,
            extra_tags=model_ready_tags,
            extra_params=model_ready_params,
            snapshot_name=(
                sanitize_artifact_name(
                    f"{args.commodity}__{args.dataset_key}__{args.target_key}__{selection_name}"
                )
                if model_ready_dataset is not None else None
            ),
        )
        pred_uri = _write_predictions(
            s3, args.bucket, args, predictions_to_write, run.info.run_id,
            logged["feature_set_sha"],
        )
        if pred_uri:
            mlflow.set_tag("predictions_uri", pred_uri)

        passed = gaps_passed(gaps) if gaps is not None else None
        logger.info(
            "run %s  rmse=%.4f  dir_acc=%s  quintile_dir=%.3f  gaps_passed=%s  folds=%d",
            run.info.run_id, result.rmse, result.directional_accuracy, q_dir, passed, result.n_folds,
        )


if __name__ == "__main__":
    main()
