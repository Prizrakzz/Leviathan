"""Build feature diagnostics for one model-ready training slice."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import boto3

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from leviathan.common.config import get_required_env, load_env  # noqa: E402
from leviathan.training.feature_diagnostics import (             # noqa: E402
    build_feature_diagnostics,
    write_feature_diagnostics,
)
from leviathan.training.model_ready import (                     # noqa: E402
    load_model_ready_training_dataset,
    sanitize_artifact_name,
)


def _optional_ref(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    if normalized.lower() in {"", "none", "null"}:
        return None
    return normalized


def _parse_float_tuple(value: str) -> tuple[float, ...]:
    if not value.strip():
        return ()
    return tuple(float(part.strip()) for part in value.split(",") if part.strip())


def _list_report_keys(s3, bucket: str, prefix: str) -> list[str]:
    paginator = s3.get_paginator("list_objects_v2")
    keys: list[str] = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for item in page.get("Contents", []):
            key = str(item["Key"])
            if key.endswith("/certification_report.json"):
                keys.append(key)
    return sorted(keys)


def _read_report(s3, bucket: str, key: str) -> dict:
    report = json.loads(
        s3.get_object(Bucket=bucket, Key=key)["Body"].read().decode("utf-8")
    )
    report.setdefault("inputs", {})["certification_report_uri"] = f"s3://{bucket}/{key}"
    return report


def _read_reports(s3, bucket: str, prefix: str, limit: int) -> list[dict]:
    keys = _list_report_keys(s3, bucket, prefix)
    if limit > 0:
        keys = keys[-limit:]
    return [_read_report(s3, bucket, key) for key in keys]


def _default_output_dir(args: argparse.Namespace) -> Path:
    parts = [
        sanitize_artifact_name(args.model_dataset_version),
        sanitize_artifact_name(args.dataset_key),
        sanitize_artifact_name(args.commodity),
        sanitize_artifact_name(args.target_key),
        sanitize_artifact_name(args.feature_set),
    ]
    return Path("data") / "feature_diagnostics" / "__".join(parts)


def main() -> None:
    load_env()
    parser = argparse.ArgumentParser(
        description="Build diagnostics for one model-ready feature set."
    )
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    parser.add_argument("--model-dataset-version", required=True, dest="model_dataset_version")
    parser.add_argument("--dataset-key", required=True, dest="dataset_key")
    parser.add_argument("--commodity", required=True)
    parser.add_argument("--target-key", required=True, dest="target_key")
    parser.add_argument("--feature-set", required=True, dest="feature_set")
    parser.add_argument("--source-dataset-version", default=None, dest="source_dataset_version")
    parser.add_argument("--bad-quantile", type=float, default=0.2, dest="bad_quantile")
    parser.add_argument(
        "--event-thresholds",
        default="-0.05,-0.10,-0.15",
        help="Comma-separated target thresholds for downside event diagnostics.",
    )
    parser.add_argument(
        "--correlation-threshold",
        type=float,
        default=0.95,
        dest="correlation_threshold",
    )
    parser.add_argument(
        "--certification-prefix",
        default="model_artifacts/candidate_certification/",
        dest="certification_prefix",
    )
    parser.add_argument("--certification-limit", type=int, default=0, dest="certification_limit")
    parser.add_argument("--skip-certification", action="store_true", dest="skip_certification")
    parser.add_argument("--output-dir", default="", dest="output_dir")
    args = parser.parse_args()

    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    aws_region = args.aws_region or get_required_env("AWS_REGION")
    s3 = boto3.client("s3", region_name=aws_region)

    dataset = load_model_ready_training_dataset(
        s3,
        bucket=bucket,
        model_dataset_version=args.model_dataset_version,
        dataset_key=args.dataset_key,
        commodity=args.commodity,
        target_key=args.target_key,
        feature_set_id=args.feature_set,
        source_dataset_version=_optional_ref(args.source_dataset_version),
    )
    reports = [] if args.skip_certification else _read_reports(
        s3,
        bucket,
        args.certification_prefix,
        args.certification_limit,
    )
    output_dir = Path(args.output_dir) if args.output_dir else _default_output_dir(args)
    artifacts = build_feature_diagnostics(
        dataset.train_df,
        dataset.feature_cols,
        target_col=dataset.target_col,
        membership=dataset.feature_membership,
        reports=reports,
        commodity=args.commodity,
        dataset_key=args.dataset_key,
        target_key=args.target_key,
        feature_set_id=args.feature_set,
        bad_quantile=args.bad_quantile,
        event_thresholds=_parse_float_tuple(args.event_thresholds),
        correlation_threshold=args.correlation_threshold,
    )
    paths = write_feature_diagnostics(
        artifacts,
        output_dir,
        manifest={
            "bucket": bucket,
            "aws_region": aws_region,
            "model_dataset_version": args.model_dataset_version,
            "source_dataset_version": dataset.source_dataset_version,
            "dataset_key": args.dataset_key,
            "commodity": args.commodity,
            "target_key": args.target_key,
            "feature_set": args.feature_set,
            "feature_count": len(dataset.feature_cols),
            "train_row_count": int(len(dataset.train_df)),
            "matrix_uri": dataset.matrix_uri,
            "manifest_uri": dataset.manifest_uri,
            "baseline_metrics_uri": dataset.baseline_metrics_uri,
            "bad_quantile": args.bad_quantile,
            "event_thresholds": list(_parse_float_tuple(args.event_thresholds)),
            "correlation_threshold": args.correlation_threshold,
            "certification_report_count_read": len(reports),
        },
    )

    print(json.dumps({
        "output_dir": str(output_dir),
        "feature_count": len(dataset.feature_cols),
        "train_row_count": int(len(dataset.train_df)),
        "candidate_recall_rows": int(len(artifacts.candidate_recall_audit)),
        "high_correlation_pairs": int(len(artifacts.correlation_pairs)),
        "paths": paths,
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
