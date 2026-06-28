"""Build Phase 7 root-cause evidence for corn composite model failures."""
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
from leviathan.training.feature_diagnostics import (  # noqa: E402
    build_correlation_pairs,
    build_feature_inventory,
    build_missingness_target_association,
)
from leviathan.training.model_ready import load_model_ready_training_dataset  # noqa: E402
from leviathan.training.phase7_root_cause import (  # noqa: E402
    baseline_audit_frame,
    certification_comparison_frame,
    feature_family_audit_frame,
    feature_set_quality_frame,
    render_markdown_report,
    root_cause_findings,
    tail_recall_audit_frame,
    target_health_frame,
)


DEFAULT_SOURCE_VERSION = "20260628T153733Z_e9149b93_phase6_corn_composites"
DEFAULT_ANNUAL_MODEL_VERSION = (
    "20260628T153733Z_e9149b93_phase6_corn_composite_model_ready"
)
DEFAULT_SNAPSHOT_MODEL_VERSION = (
    "20260628T160000Z_66c0e0a9_phase6_corn_wasde_snapshot_model_ready"
)
DEFAULT_ANNUAL_FEATURE_SETS = (
    "corn_preseason_core",
    "corn_preseason_core_plus_weather_dense",
    "corn_preseason_core_plus_flow",
    "corn_weather_flow",
    "corn_full_fundamental_stack",
)
DEFAULT_SNAPSHOT_FEATURE_SETS = (
    "corn_preseason_core",
    "corn_preseason_core_plus_wasde",
    "preseason_physical_plus_wasde_revision",
)


def _split_csv(value: str | None, default: tuple[str, ...]) -> tuple[str, ...]:
    if value is None or not str(value).strip():
        return default
    return tuple(part.strip() for part in str(value).split(",") if part.strip())


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


def _reports_for_versions(
    reports: list[dict[str, Any]],
    versions: set[str],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for report in reports:
        version = str((report.get("candidate") or {}).get("model_dataset_version", ""))
        if version in versions:
            out.append(report)
    return out


def _write_frame(path: Path, df: pd.DataFrame) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    return str(path)


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return None if pd.isna(value) else value
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return str(value)


def _build_feature_audits(
    s3,
    *,
    bucket: str,
    model_dataset_version: str,
    source_dataset_version: str,
    dataset_key: str,
    commodity: str,
    target_key: str,
    feature_sets: tuple[str, ...],
    mode: str,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    quality_frames: list[pd.DataFrame] = []
    family_frames: list[pd.DataFrame] = []
    inventory_frames: list[pd.DataFrame] = []
    missing_assoc_frames: list[pd.DataFrame] = []
    correlation_frames: list[pd.DataFrame] = []

    for feature_set in feature_sets:
        dataset = load_model_ready_training_dataset(
            s3,
            bucket=bucket,
            model_dataset_version=model_dataset_version,
            dataset_key=dataset_key,
            commodity=commodity,
            target_key=target_key,
            feature_set_id=feature_set,
            source_dataset_version=source_dataset_version,
        )
        inventory = build_feature_inventory(
            dataset.train_df,
            dataset.feature_cols,
            membership=dataset.feature_membership,
        )
        correlations = build_correlation_pairs(dataset.train_df, dataset.feature_cols)
        missing_assoc = build_missingness_target_association(
            dataset.train_df,
            dataset.feature_cols,
            target_col=dataset.target_col,
        )

        inventory.insert(0, "mode", mode)
        inventory.insert(1, "feature_set", feature_set)
        missing_assoc.insert(0, "mode", mode)
        missing_assoc.insert(1, "feature_set", feature_set)
        correlations.insert(0, "mode", mode)
        correlations.insert(1, "feature_set", feature_set)

        inventory_frames.append(inventory)
        missing_assoc_frames.append(missing_assoc)
        correlation_frames.append(correlations)
        quality_frames.append(
            feature_set_quality_frame(
                mode=mode,
                feature_set_id=feature_set,
                train_df=dataset.train_df,
                inventory=inventory,
                correlation_pairs=correlations,
            )
        )
        family_frames.append(
            feature_family_audit_frame(
                mode=mode,
                feature_set_id=feature_set,
                inventory=inventory,
            )
        )

    return (
        pd.concat(quality_frames, ignore_index=True) if quality_frames else pd.DataFrame(),
        pd.concat(family_frames, ignore_index=True) if family_frames else pd.DataFrame(),
        pd.concat(inventory_frames, ignore_index=True) if inventory_frames else pd.DataFrame(),
        pd.concat(missing_assoc_frames, ignore_index=True) if missing_assoc_frames else pd.DataFrame(),
        pd.concat(correlation_frames, ignore_index=True) if correlation_frames else pd.DataFrame(),
    )


def main() -> None:
    load_env()
    parser = argparse.ArgumentParser(
        description="Build Phase 7 root-cause report from frozen corn composite artifacts."
    )
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    parser.add_argument("--source-dataset-version", default=DEFAULT_SOURCE_VERSION)
    parser.add_argument("--annual-model-dataset-version", default=DEFAULT_ANNUAL_MODEL_VERSION)
    parser.add_argument("--snapshot-model-dataset-version", default=DEFAULT_SNAPSHOT_MODEL_VERSION)
    parser.add_argument("--commodity", default="corn_cbot")
    parser.add_argument("--target-key", default="psd_production_anomaly_pct")
    parser.add_argument("--annual-dataset-key", default="psd_snd_anomaly")
    parser.add_argument("--snapshot-dataset-key", default="psd_snd_anomaly_snapshot")
    parser.add_argument("--annual-feature-sets", default="")
    parser.add_argument("--snapshot-feature-sets", default="")
    parser.add_argument(
        "--reports-prefix",
        default="model_artifacts/candidate_certification/",
    )
    parser.add_argument(
        "--output-dir",
        default="data/phase7/root_cause_corn_composites",
    )
    args = parser.parse_args()

    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    region = args.aws_region or get_required_env("AWS_REGION")
    s3 = boto3.client("s3", region_name=region)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    report_keys = _list_report_keys(s3, bucket, args.reports_prefix)
    reports = [_read_report(s3, bucket, key) for key in report_keys]
    versions = {
        args.annual_model_dataset_version,
        args.snapshot_model_dataset_version,
    }
    filtered_reports = _reports_for_versions(reports, versions)

    annual_feature_sets = _split_csv(args.annual_feature_sets, DEFAULT_ANNUAL_FEATURE_SETS)
    snapshot_feature_sets = _split_csv(
        args.snapshot_feature_sets,
        DEFAULT_SNAPSHOT_FEATURE_SETS,
    )

    reference_dataset = load_model_ready_training_dataset(
        s3,
        bucket=bucket,
        model_dataset_version=args.annual_model_dataset_version,
        dataset_key=args.annual_dataset_key,
        commodity=args.commodity,
        target_key=args.target_key,
        feature_set_id=annual_feature_sets[0],
        source_dataset_version=args.source_dataset_version,
    )
    target_health = target_health_frame(reference_dataset.matrix)
    candidate_comparison = certification_comparison_frame(
        filtered_reports,
        model_dataset_versions=versions,
    )
    baseline_audit = baseline_audit_frame(filtered_reports)
    tail_recall = tail_recall_audit_frame(filtered_reports)

    annual_quality, annual_family, annual_inventory, annual_missing, annual_corr = (
        _build_feature_audits(
            s3,
            bucket=bucket,
            model_dataset_version=args.annual_model_dataset_version,
            source_dataset_version=args.source_dataset_version,
            dataset_key=args.annual_dataset_key,
            commodity=args.commodity,
            target_key=args.target_key,
            feature_sets=annual_feature_sets,
            mode="annual",
        )
    )
    snapshot_quality, snapshot_family, snapshot_inventory, snapshot_missing, snapshot_corr = (
        _build_feature_audits(
            s3,
            bucket=bucket,
            model_dataset_version=args.snapshot_model_dataset_version,
            source_dataset_version=args.source_dataset_version,
            dataset_key=args.snapshot_dataset_key,
            commodity=args.commodity,
            target_key=args.target_key,
            feature_sets=snapshot_feature_sets,
            mode="snapshot",
        )
    )
    feature_set_quality = pd.concat(
        [annual_quality, snapshot_quality],
        ignore_index=True,
    )
    feature_block_audit = pd.concat(
        [annual_family, snapshot_family],
        ignore_index=True,
    )
    feature_inventory = pd.concat(
        [annual_inventory, snapshot_inventory],
        ignore_index=True,
    )
    missingness_target = pd.concat(
        [annual_missing, snapshot_missing],
        ignore_index=True,
    )
    correlation_pairs = pd.concat(
        [annual_corr, snapshot_corr],
        ignore_index=True,
    )

    findings = root_cause_findings(
        candidate_comparison,
        feature_set_quality,
        tail_recall,
        baseline_audit,
    )
    version_manifest = {
        "source_gold_dataset_version": args.source_dataset_version,
        "annual_model_dataset_version": args.annual_model_dataset_version,
        "snapshot_model_dataset_version": args.snapshot_model_dataset_version,
        "commodity": args.commodity,
        "target_key": args.target_key,
    }
    report_md = render_markdown_report(
        title="Phase 7 Corn Composite Root-Cause Investigation",
        versions=version_manifest,
        findings=findings,
        candidate_comparison=candidate_comparison,
        feature_set_quality=feature_set_quality,
        tail_recall=tail_recall,
        baseline_audit=baseline_audit,
    )

    outputs = {
        "candidate_comparison": _write_frame(
            output_dir / "phase7_candidate_comparison.parquet",
            candidate_comparison,
        ),
        "target_health": _write_frame(
            output_dir / "phase7_target_health.parquet",
            target_health,
        ),
        "feature_set_quality": _write_frame(
            output_dir / "phase7_feature_set_quality.parquet",
            feature_set_quality,
        ),
        "feature_block_audit": _write_frame(
            output_dir / "phase7_feature_block_audit.parquet",
            feature_block_audit,
        ),
        "feature_inventory": _write_frame(
            output_dir / "phase7_feature_inventory.parquet",
            feature_inventory,
        ),
        "missingness_target_association": _write_frame(
            output_dir / "phase7_missingness_target_association.parquet",
            missingness_target,
        ),
        "correlation_pairs": _write_frame(
            output_dir / "phase7_correlation_pairs.parquet",
            correlation_pairs,
        ),
        "baseline_audit": _write_frame(
            output_dir / "phase7_baseline_audit.parquet",
            baseline_audit,
        ),
        "tail_recall_audit": _write_frame(
            output_dir / "phase7_tail_recall_audit.parquet",
            tail_recall,
        ),
    }
    report_path = output_dir / "phase7_root_cause_report.md"
    report_path.write_text(report_md, encoding="utf-8")
    outputs["root_cause_report"] = str(report_path)

    manifest = {
        **version_manifest,
        "reports_read": len(reports),
        "reports_matched": len(filtered_reports),
        "annual_feature_sets": annual_feature_sets,
        "snapshot_feature_sets": snapshot_feature_sets,
        "outputs": outputs,
        "findings": findings,
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(_json_safe(manifest), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    outputs["manifest"] = str(manifest_path)

    print(json.dumps(_json_safe({
        "output_dir": str(output_dir),
        "reports_read": len(reports),
        "reports_matched": len(filtered_reports),
        "outputs": outputs,
        "findings": findings,
    }), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
