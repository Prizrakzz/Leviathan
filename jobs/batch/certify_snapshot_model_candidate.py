"""Certify one WASDE snapshot model candidate with grouped walk-forward CV."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import io
import json
import math
import os
from pathlib import Path
import sys
from typing import Any

import boto3
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from leviathan.storage.paths import snapshot_candidate_certification_key  # noqa: E402
from leviathan.training.model_ready import load_model_ready_training_dataset  # noqa: E402
from leviathan.training.models import make_tree_model                         # noqa: E402
from leviathan.training.wasde_snapshot_cv import (                            # noqa: E402
    resolve_snapshot_feature_stack_id,
)
from leviathan.training.wasde_snapshot_smoke import (                         # noqa: E402
    run_wasde_snapshot_training_smoke,
)


def _optional_ref(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    if normalized.lower() in {"", "none", "null"}:
        return None
    return normalized


def _safe_fragment(value: object) -> str:
    text = "" if value is None else str(value)
    out = "".join(ch if ch.isalnum() or ch in "_.=-" else "_" for ch in text)
    return out.strip("_") or "none"


def _params_sha(model_params: dict[str, Any] | None) -> str:
    if not model_params:
        return "default_params"
    payload = json.dumps(model_params, sort_keys=True, default=str)
    return "params_" + hashlib.sha1(payload.encode("utf-8")).hexdigest()[:10]


def _candidate_id(
    *,
    commodity: str,
    feature_set: str,
    feature_stack: str,
    dataset_key: str,
    target_key: str,
    model: str,
    model_params: dict[str, Any],
    model_dataset_version: str,
) -> str:
    parts = [
        commodity,
        feature_set,
        feature_stack,
        dataset_key,
        target_key,
        model,
        _params_sha(model_params),
        model_dataset_version,
    ]
    return "__".join(_safe_fragment(part) for part in parts)


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


def _frame_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    if df is None or df.empty:
        return []
    out = df.copy()
    for col in out.columns:
        if pd.api.types.is_object_dtype(out[col]):
            out[col] = out[col].map(_json_safe)
    return [_json_safe(row) for row in out.to_dict(orient="records")]


def _put_json(s3, *, bucket: str, key: str, payload: dict[str, Any]) -> str:
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(_json_safe(payload), indent=2, sort_keys=True).encode("utf-8"),
        ContentType="application/json",
    )
    return f"s3://{bucket}/{key}"


def _put_parquet(s3, *, bucket: str, key: str, frame: pd.DataFrame) -> str | None:
    if frame is None or frame.empty:
        return None
    buf = io.BytesIO()
    frame.to_parquet(buf, index=False)
    s3.put_object(Bucket=bucket, Key=key, Body=buf.getvalue())
    return f"s3://{bucket}/{key}"


def _fold_rows(result) -> list[dict[str, Any]]:
    if result is None:
        return []
    return [_json_safe(asdict(fold)) for fold in result.folds]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Certify one grouped WASDE snapshot model candidate."
    )
    parser.add_argument("--commodity", required=True)
    parser.add_argument("--feature-set", required=True, dest="feature_set")
    parser.add_argument("--feature-stack", default="auto", dest="feature_stack")
    parser.add_argument("--model-dataset-version", required=True, dest="model_dataset_version")
    parser.add_argument("--dataset-key", required=True, dest="dataset_key")
    parser.add_argument("--target-key", required=True, dest="target_key")
    parser.add_argument("--model", default="lightgbm", choices=["xgboost", "lightgbm"])
    parser.add_argument("--model-params-json", default="{}", dest="model_params_json")
    parser.add_argument("--min-train-years", type=int, default=10, dest="min_train_years")
    parser.add_argument(
        "--min-trainable-annual-groups",
        type=int,
        default=20,
        dest="min_trainable_annual_groups",
    )
    parser.add_argument("--min-event-groups", type=int, default=5, dest="min_event_groups")
    parser.add_argument("--min-non-null-rate", type=float, default=0.2, dest="min_non_null_rate")
    parser.add_argument("--collapse-policy", default="latest", dest="collapse_policy")
    parser.add_argument("--source-dataset-version", default=None, dest="source_dataset_version")
    parser.add_argument("--bucket", default=os.environ.get("LEVIATHAN_BUCKET"))
    parser.add_argument(
        "--aws-region",
        default=os.environ.get("AWS_REGION", "us-east-1"),
        dest="aws_region",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.bucket:
        raise SystemExit("LEVIATHAN_BUCKET or --bucket is required")
    try:
        model_params = json.loads(args.model_params_json or "{}")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"--model-params-json is not valid JSON: {exc}") from exc
    if not isinstance(model_params, dict):
        raise SystemExit("--model-params-json must decode to a JSON object")

    feature_stack = resolve_snapshot_feature_stack_id(args.feature_set, args.feature_stack)
    candidate_id = _candidate_id(
        commodity=args.commodity,
        feature_set=args.feature_set,
        feature_stack=feature_stack,
        dataset_key=args.dataset_key,
        target_key=args.target_key,
        model=args.model,
        model_params=model_params,
        model_dataset_version=args.model_dataset_version,
    )
    s3 = boto3.client("s3", region_name=args.aws_region)
    dataset = load_model_ready_training_dataset(
        s3,
        bucket=args.bucket,
        model_dataset_version=args.model_dataset_version,
        dataset_key=args.dataset_key,
        commodity=args.commodity,
        target_key=args.target_key,
        feature_set_id=args.feature_set,
        source_dataset_version=_optional_ref(args.source_dataset_version),
    )
    model = make_tree_model(args.model, **model_params)
    result = run_wasde_snapshot_training_smoke(
        dataset.matrix,
        model=model,
        feature_stack_id=feature_stack,
        feature_columns=dataset.feature_cols,
        min_train_years=args.min_train_years,
        min_trainable_annual_groups=args.min_trainable_annual_groups,
        min_event_groups=args.min_event_groups,
        min_non_null_rate=args.min_non_null_rate,
        collapse_policy=args.collapse_policy,
    )

    prefix_uri = f"s3://{args.bucket}/model_artifacts/snapshot_candidate_certification/candidate_id={candidate_id}/"
    artifacts: dict[str, str | None] = {
        "artifact_prefix_uri": prefix_uri,
        "certification_report_uri": f"{prefix_uri}certification_report.json",
    }
    if result.cv_result is not None and not args.dry_run:
        artifacts["oof_predictions_uri"] = _put_parquet(
            s3,
            bucket=args.bucket,
            key=snapshot_candidate_certification_key(candidate_id, "oof_predictions.parquet"),
            frame=result.cv_result.predictions,
        )
        artifacts["baseline_diagnostics_uri"] = _put_parquet(
            s3,
            bucket=args.bucket,
            key=snapshot_candidate_certification_key(candidate_id, "baseline_diagnostics.parquet"),
            frame=result.cv_result.baseline_diagnostics,
        )
        artifacts["dropped_features_uri"] = _put_parquet(
            s3,
            bucket=args.bucket,
            key=snapshot_candidate_certification_key(candidate_id, "dropped_features.parquet"),
            frame=result.cv_result.dropped_features,
        )
        artifacts["fold_metrics_uri"] = _put_parquet(
            s3,
            bucket=args.bucket,
            key=snapshot_candidate_certification_key(candidate_id, "fold_metrics.parquet"),
            frame=pd.DataFrame(_fold_rows(result.cv_result)),
        )

    cv = result.cv_result
    report = {
        "candidate": {
            "candidate_id": candidate_id,
            "commodity": args.commodity,
            "feature_set_id": args.feature_set,
            "feature_stack_id": feature_stack,
            "dataset_key": args.dataset_key,
            "target_key": args.target_key,
            "model_name": args.model,
            "model_params": model_params,
            "model_params_sha": _params_sha(model_params),
            "model_dataset_version": args.model_dataset_version,
            "source_dataset_version": dataset.source_dataset_version,
            "min_train_years": args.min_train_years,
            "min_trainable_annual_groups": args.min_trainable_annual_groups,
            "min_event_groups": args.min_event_groups,
            "min_non_null_rate": args.min_non_null_rate,
            "collapse_policy": args.collapse_policy,
        },
        "inputs": {
            "manifest_uri": dataset.manifest_uri,
            "matrix_uri": dataset.matrix_uri,
            "baseline_metrics_uri": dataset.baseline_metrics_uri,
            "feature_set_meta": dataset.feature_set_meta,
        },
        "readiness": result.readiness,
        "diagnostics": {
            "integrity": result.diagnostics.integrity,
            "leakage_issues": _frame_records(result.diagnostics.leakage_issues),
            "target_diagnostics": _frame_records(result.diagnostics.target_diagnostics),
            "feature_quality_summary": (
                result.diagnostics.feature_quality["quality_bucket"]
                .value_counts(dropna=False)
                .astype(int)
                .to_dict()
                if not result.diagnostics.feature_quality.empty
                else {}
            ),
        },
        "cv": {
            "status": "skipped" if cv is None else "completed",
            "folds": _fold_rows(cv),
            "selected_feature_count": 0 if cv is None else len(cv.feature_columns),
            "selected_features": [] if cv is None else list(cv.feature_columns),
            "snapshot_metrics": {} if cv is None else cv.snapshot_metrics,
            "annual_metrics": {} if cv is None else cv.annual_metrics,
        },
        "artifacts": artifacts,
    }
    report = _json_safe(report)
    report_key = snapshot_candidate_certification_key(candidate_id)
    if args.dry_run:
        print(json.dumps({"dry_run": True, "report_uri": f"s3://{args.bucket}/{report_key}", "report": report}, indent=2))
        return
    report_uri = _put_json(s3, bucket=args.bucket, key=report_key, payload=report)
    print(json.dumps({
        "candidate_id": candidate_id,
        "report_uri": report_uri,
        "readiness": report["readiness"],
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
