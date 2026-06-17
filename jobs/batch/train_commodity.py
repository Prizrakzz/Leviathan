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
import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from leviathan.features.registry import load_registry          # noqa: E402
from leviathan.features.windows import resolve_tier_families    # noqa: E402
from leviathan.training.cv import walk_forward_cv               # noqa: E402
from leviathan.training.slices import (                         # noqa: E402
    evaluate_gaps, gaps_passed, load_gap_rules,
)
from leviathan.training.tracking import log_training_run        # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("train_commodity")

_REPO = Path(__file__).resolve().parents[2]
_MATRIX_PREFIX = "gold/feature_matrix/"
_PRED_PREFIX = "silver/model_predictions/"
_TIERS_PATH = _REPO / "configs" / "features" / "feature_tiers.yaml"
_CONFIG_DIR = _REPO / "configs" / "features"


def _make_model(name: str):
    """Tree regressors — NaN-native, no scaling needed (missingness-as-signal)."""
    common = dict(n_estimators=400, max_depth=4, learning_rate=0.03, subsample=0.8)
    if name == "xgboost":
        from xgboost import XGBRegressor
        return XGBRegressor(**common, colsample_bytree=0.8, n_jobs=-1)
    if name == "lightgbm":
        from lightgbm import LGBMRegressor
        return LGBMRegressor(**common, n_jobs=-1, verbose=-1)
    raise SystemExit(f"unknown --model {name!r} (xgboost|lightgbm)")


def _read_matrix(s3, bucket: str, commodity: str) -> pd.DataFrame | None:
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=f"{_MATRIX_PREFIX}commodity={commodity}/"):
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


def _write_predictions(s3, bucket, args, predictions, run_id, feature_set_sha) -> str | None:
    if predictions.empty:
        return None
    df = predictions.copy()
    df["commodity"] = args.commodity
    df["tier"] = args.tier
    df["target"] = args.target
    df["model"] = args.model
    df["feature_set_sha"] = feature_set_sha
    df["run_id"] = run_id
    df["as_of_date"] = datetime.date.today().isoformat()
    pred_date = datetime.date.today().isoformat()
    key = (
        f"{_PRED_PREFIX}model_family=tier1_production/prediction_date={pred_date}/"
        f"{args.commodity}__{args.tier}__{args.target}__{args.model}.parquet"
    )
    buf = io.BytesIO()
    df.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
    s3.put_object(Bucket=bucket, Key=key, Body=buf.getvalue())
    return f"s3://{bucket}/{key}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Train one commodity model → MLflow.")
    parser.add_argument("--commodity", required=True)
    parser.add_argument("--tier", default="climate",
                        help="named feature set: fundamentals|climate|trade_condition|full")
    parser.add_argument("--target", default="production_quantity",
                        help="label target (production_quantity|area_harvested|yield)")
    parser.add_argument("--model", default="xgboost", help="xgboost|lightgbm")
    parser.add_argument("--bucket", default=os.environ.get("LEVIATHAN_BUCKET"))
    parser.add_argument("--aws-region", default=os.environ.get("AWS_REGION", "us-east-1"),
                        dest="aws_region")
    parser.add_argument("--experiment", default="leviathan-tier1-production")
    parser.add_argument("--tracking-uri", default=os.environ.get("MLFLOW_TRACKING_URI"),
                        dest="tracking_uri")
    parser.add_argument("--min-train-years", type=int, default=5, dest="min_train_years")
    parser.add_argument("--no-snapshot", action="store_true")
    args = parser.parse_args()
    if not args.bucket:
        raise SystemExit("LEVIATHAN_BUCKET (or --bucket) is required")

    import mlflow
    if args.tracking_uri:
        mlflow.set_tracking_uri(args.tracking_uri)
    mlflow.set_experiment(args.experiment)

    s3 = boto3.client("s3", region_name=args.aws_region)
    matrix = _read_matrix(s3, args.bucket, args.commodity)
    if matrix is None or matrix.empty:
        raise SystemExit(f"no feature_matrix for {args.commodity}")

    target_col = f"label_{args.target}"
    if target_col not in matrix.columns or matrix[target_col].notna().sum() == 0:
        logger.warning("%s has no %s labels — skipping.", args.commodity, target_col)
        return  # clean skip (exit 0): an expected gap, not a failure

    feature_cols = _tier_feature_cols(matrix, args.tier)
    if not feature_cols:
        logger.warning("%s tier %s resolved to 0 feature columns — skipping.",
                       args.commodity, args.tier)
        return

    registry = load_registry(_CONFIG_DIR)
    model = _make_model(args.model)
    run_name = f"{args.commodity}-{args.tier}-{args.target}-{args.model}"

    train_slice = matrix[["country", "crop_year"] + feature_cols + [target_col]].copy()

    with mlflow.start_run(run_name=run_name) as run:
        try:
            result = walk_forward_cv(
                matrix, target_col, feature_cols, model,
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
        mlflow.set_tag("target", args.target)
        logged = log_training_run(
            args.commodity, args.tier, train_slice, feature_cols, result,
            target_col=target_col, params_hash=registry.params_hash,
            bucket=args.bucket, aws_region=args.aws_region, mlflow=mlflow,
            snapshot=not args.no_snapshot, gaps=gaps,
        )
        pred_uri = _write_predictions(
            s3, args.bucket, args, result.predictions, run.info.run_id,
            logged["feature_set_sha"],
        )
        if pred_uri:
            mlflow.set_tag("predictions_uri", pred_uri)

        passed = gaps_passed(gaps) if gaps is not None else None
        logger.info(
            "run %s  rmse=%.4f  dir_acc=%s  gaps_passed=%s  folds=%d",
            run.info.run_id, result.rmse, result.directional_accuracy, passed, result.n_folds,
        )


if __name__ == "__main__":
    main()
