"""Build Phase 8 persistence and downside-alert evidence."""
from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
import sys
from typing import Any

import boto3
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from leviathan.common.config import get_required_env, load_env  # noqa: E402
from leviathan.storage.paths import gold_model_ready_matrix_key  # noqa: E402
from leviathan.training.certification_summary import (  # noqa: E402
    certification_ranking_frame,
)
from leviathan.training.phase8_alerts import (  # noqa: E402
    baseline_alert_metrics_frame,
    render_phase8_markdown,
    target_reframe_audit_frame,
)


DEFAULT_MODEL_DATASET_VERSION = (
    "20260628T153733Z_e9149b93_phase6_corn_composite_model_ready"
)
DEFAULT_DATASET_KEY = "psd_snd_anomaly"
DEFAULT_COMMODITY = "corn_cbot"
DEFAULT_TARGET_KEY = "psd_production_anomaly_pct"


def _read_parquet(
    *,
    s3,
    bucket: str | None,
    local_root: Path | None,
    key: str,
) -> pd.DataFrame:
    if local_root is not None:
        return pd.read_parquet(local_root / key)
    if s3 is None or bucket is None:
        raise ValueError("S3 bucket/client required when --local-root is not set")
    body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
    return pd.read_parquet(io.BytesIO(body))


def _list_report_keys(s3, bucket: str, prefix: str) -> list[str]:
    paginator = s3.get_paginator("list_objects_v2")
    keys: list[str] = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for item in page.get("Contents", []):
            key = str(item["Key"])
            if key.endswith("/certification_report.json"):
                keys.append(key)
    return sorted(keys)


def _read_report(s3, bucket: str, key: str) -> dict[str, Any]:
    body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
    report = json.loads(body.decode("utf-8"))
    report.setdefault("inputs", {})["certification_report_uri"] = f"s3://{bucket}/{key}"
    return report


def _candidate_reports(
    *,
    s3,
    bucket: str | None,
    reports_prefix: str,
    model_dataset_version: str,
) -> list[dict[str, Any]]:
    if s3 is None or bucket is None:
        return []
    reports: list[dict[str, Any]] = []
    for key in _list_report_keys(s3, bucket, reports_prefix):
        report = _read_report(s3, bucket, key)
        candidate = report.get("candidate", {}) or {}
        if str(candidate.get("model_dataset_version")) == model_dataset_version:
            reports.append(report)
    return reports


def _write_frame(path: Path, df: pd.DataFrame) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    return str(path)


def main() -> None:
    load_env()
    parser = argparse.ArgumentParser(
        description="Build Phase 8 target persistence and downside-alert report."
    )
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    parser.add_argument("--local-root", default=None, dest="local_root")
    parser.add_argument("--model-dataset-version", default=DEFAULT_MODEL_DATASET_VERSION)
    parser.add_argument("--dataset-key", default=DEFAULT_DATASET_KEY)
    parser.add_argument("--commodity", default=DEFAULT_COMMODITY)
    parser.add_argument("--target-key", default=DEFAULT_TARGET_KEY)
    parser.add_argument(
        "--reports-prefix",
        default="model_artifacts/candidate_certification/",
    )
    parser.add_argument(
        "--output-dir",
        default="data/phase8/persistence_alert_corn",
    )
    args = parser.parse_args()

    local_root = Path(args.local_root) if args.local_root else None
    bucket = args.bucket or (None if local_root else get_required_env("LEVIATHAN_BUCKET"))
    region = args.aws_region or (None if local_root else get_required_env("AWS_REGION"))
    s3 = boto3.client("s3", region_name=region) if local_root is None else None
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    matrix_key = gold_model_ready_matrix_key(
        args.model_dataset_version,
        args.dataset_key,
        args.commodity,
        args.target_key,
    )
    matrix = _read_parquet(
        s3=s3,
        bucket=bucket,
        local_root=local_root,
        key=matrix_key,
    )
    target_audit = target_reframe_audit_frame(matrix)
    baseline_alerts = baseline_alert_metrics_frame(matrix)
    reports = _candidate_reports(
        s3=s3,
        bucket=bucket,
        reports_prefix=args.reports_prefix,
        model_dataset_version=args.model_dataset_version,
    )
    candidate_comparison = certification_ranking_frame(reports) if reports else pd.DataFrame()

    outputs = {
        "target_reframe_audit": _write_frame(
            output_dir / "phase8_target_reframe_audit.parquet", target_audit
        ),
        "baseline_alert_metrics": _write_frame(
            output_dir / "phase8_baseline_alert_metrics.parquet", baseline_alerts
        ),
    }
    if not candidate_comparison.empty:
        outputs["candidate_comparison"] = _write_frame(
            output_dir / "phase8_candidate_comparison.parquet", candidate_comparison
        )

    markdown = render_phase8_markdown(
        target_audit=target_audit,
        baseline_alerts=baseline_alerts,
        candidate_comparison=candidate_comparison,
    )
    report_path = output_dir / "phase8_persistence_alert_report.md"
    report_path.write_text(markdown, encoding="utf-8")
    outputs["markdown_report"] = str(report_path)

    manifest = {
        "task": "build_phase8_persistence_alert_report",
        "model_dataset_version": args.model_dataset_version,
        "dataset_key": args.dataset_key,
        "commodity": args.commodity,
        "target_key": args.target_key,
        "matrix_key": matrix_key,
        "candidate_report_count": int(len(reports)),
        "outputs": outputs,
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
