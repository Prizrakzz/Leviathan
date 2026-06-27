"""Certify a frozen model candidate before Phase 10 promotion."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

import boto3

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from leviathan.storage.paths import model_candidate_certification_key  # noqa: E402
from leviathan.training.certification import (                         # noqa: E402
    CandidateSpec,
    build_candidate_certification_report,
)
from leviathan.training.model_ready import load_model_ready_training_dataset  # noqa: E402
from leviathan.training.models import make_tree_model                         # noqa: E402


def _optional_ref(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    if normalized.lower() in {"", "none", "null"}:
        return None
    return normalized


def _stress_years(value: str | None) -> tuple[int, ...]:
    normalized = _optional_ref(value)
    if normalized is None:
        return (2010, 2011, 2012, 2020, 2021, 2022)
    return tuple(int(part.strip()) for part in normalized.split(",") if part.strip())


def main() -> None:
    parser = argparse.ArgumentParser(description="Certify one model-ready candidate.")
    parser.add_argument("--commodity", required=True)
    parser.add_argument("--feature-set", required=True, dest="feature_set")
    parser.add_argument("--model-dataset-version", required=True, dest="model_dataset_version")
    parser.add_argument("--dataset-key", required=True, dest="dataset_key")
    parser.add_argument("--target-key", required=True, dest="target_key")
    parser.add_argument("--model", default="lightgbm", choices=["xgboost", "lightgbm"])
    parser.add_argument("--model-params-json", default="{}", dest="model_params_json")
    parser.add_argument("--cv-policy", default="expanding_post_2000", dest="cv_policy")
    parser.add_argument("--min-train-years", type=int, default=10, dest="min_train_years")
    parser.add_argument("--source-dataset-version", default=None, dest="source_dataset_version")
    parser.add_argument("--permutation-trials", type=int, default=20, dest="permutation_trials")
    parser.add_argument("--stress-years", default=None, dest="stress_years")
    parser.add_argument("--bucket", default=os.environ.get("LEVIATHAN_BUCKET"))
    parser.add_argument("--aws-region", default=os.environ.get("AWS_REGION", "us-east-1"),
                        dest="aws_region")
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
    spec = CandidateSpec(
        commodity=args.commodity,
        feature_set_id=args.feature_set,
        dataset_key=args.dataset_key,
        target_key=args.target_key,
        model_name=args.model,
        cv_policy=args.cv_policy,
        model_dataset_version=args.model_dataset_version,
        source_dataset_version=dataset.source_dataset_version,
        min_train_years=args.min_train_years,
        model_params=model_params,
    )
    report = build_candidate_certification_report(
        spec=spec,
        matrix=dataset.matrix,
        train_df=dataset.train_df,
        feature_cols=dataset.feature_cols,
        target_col=dataset.target_col,
        model=make_tree_model(args.model, **model_params),
        stress_years=_stress_years(args.stress_years),
        permutation_trials=args.permutation_trials,
    )
    report["inputs"] = {
        "manifest_uri": dataset.manifest_uri,
        "matrix_uri": dataset.matrix_uri,
        "baseline_metrics_uri": dataset.baseline_metrics_uri,
    }

    key = model_candidate_certification_key(spec.candidate_id)
    uri = f"s3://{args.bucket}/{key}"
    report["inputs"]["certification_report_uri"] = uri
    body = json.dumps(report, indent=2, sort_keys=True).encode("utf-8")
    if args.dry_run:
        print(json.dumps({"dry_run": True, "report_uri": uri, "report": report}, indent=2))
        return
    s3.put_object(Bucket=args.bucket, Key=key, Body=body, ContentType="application/json")
    print(json.dumps({
        "report_uri": uri,
        "promotion_gate": report["promotion_gate"],
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
