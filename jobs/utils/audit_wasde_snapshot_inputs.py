"""Build the Phase 0 read-only audit for WASDE snapshot modeling."""
from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
import sys

import boto3
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from leviathan.common.config import load_env  # noqa: E402
from leviathan.model_datasets.wasde_snapshot_audit import (  # noqa: E402
    build_phase0_audit_report,
    build_psd_target_compatibility_audit,
    build_static_feature_reuse_audit,
    build_wasde_inventory,
    build_wasde_region_mapping_candidates,
    build_wasde_region_quality,
    render_phase0_markdown,
)

DEFAULT_BUCKET = "leviathan-dev-shahem-001"
DEFAULT_REGION = "us-east-1"
DEFAULT_WASDE_PREFIX = "silver/wasde/"
DEFAULT_PSD_KEY = "silver/psd/part-000.parquet"
DEFAULT_OUTPUT_DIR = "data/phase_wasde_snapshot"
DEFAULT_REPORT_MD = "docs/WASDE_SNAPSHOT_PHASE0_AUDIT.md"


def _list_parquet_keys(s3, bucket: str, prefix: str) -> list[str]:
    keys: list[str] = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        keys.extend(
            str(obj["Key"])
            for obj in page.get("Contents", [])
            if str(obj["Key"]).endswith(".parquet")
        )
    return sorted(keys)


def _read_parquet_key(s3, bucket: str, key: str) -> pd.DataFrame:
    body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
    return pd.read_parquet(io.BytesIO(body))


def _read_parquet_prefix(s3, bucket: str, prefix: str) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for key in _list_parquet_keys(s3, bucket, prefix):
        frame = _read_parquet_key(s3, bucket, key)
        if not frame.empty:
            frames.append(frame)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _write_frame(path: Path, frame: pd.DataFrame) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)
    return str(path)


def _write_json(path: Path, payload: dict) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return str(path)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bucket", default=DEFAULT_BUCKET)
    parser.add_argument("--aws-region", default=DEFAULT_REGION, dest="aws_region")
    parser.add_argument("--wasde-prefix", default=DEFAULT_WASDE_PREFIX, dest="wasde_prefix")
    parser.add_argument("--psd-key", default=DEFAULT_PSD_KEY, dest="psd_key")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, dest="output_dir")
    parser.add_argument("--report-md", default=DEFAULT_REPORT_MD, dest="report_md")
    parser.add_argument(
        "--source-dataset-version",
        default="phase0_wasde_snapshot_audit",
        dest="source_dataset_version",
    )
    return parser.parse_args()


def main() -> None:
    load_env()
    args = _parse_args()
    output_dir = Path(args.output_dir)
    report_md = Path(args.report_md)

    s3 = boto3.client("s3", region_name=args.aws_region)
    wasde = _read_parquet_prefix(s3, args.bucket, args.wasde_prefix)
    psd = _read_parquet_key(s3, args.bucket, args.psd_key)

    wasde_inventory = build_wasde_inventory(wasde)
    region_quality = build_wasde_region_quality(wasde)
    mapping_candidates = build_wasde_region_mapping_candidates(region_quality)
    psd_target_audit, target_class_balance = build_psd_target_compatibility_audit(
        psd,
        source_dataset_version=args.source_dataset_version,
    )
    static_feature_reuse = build_static_feature_reuse_audit()
    report = build_phase0_audit_report(
        bucket=args.bucket,
        wasde_inventory=wasde_inventory,
        region_quality=region_quality,
        mapping_candidates=mapping_candidates,
        psd_target_audit=psd_target_audit,
        target_class_balance=target_class_balance,
        static_feature_reuse=static_feature_reuse,
    )

    outputs = {
        "wasde_inventory": _write_frame(
            output_dir / "phase0_wasde_inventory.parquet", wasde_inventory
        ),
        "region_quality": _write_frame(
            output_dir / "wasde_region_quality.parquet", region_quality
        ),
        "region_mapping_candidates": _write_frame(
            output_dir / "wasde_region_mapping_candidates.parquet",
            mapping_candidates,
        ),
        "psd_target_audit": _write_frame(
            output_dir / "phase0_psd_target_audit.parquet", psd_target_audit
        ),
        "target_class_balance": _write_frame(
            output_dir / "phase0_target_class_balance.parquet", target_class_balance
        ),
        "static_feature_reuse": _write_frame(
            output_dir / "static_feature_reuse_audit.parquet", static_feature_reuse
        ),
        "phase0_audit_report": _write_json(
            output_dir / "phase0_audit_report.json", report
        ),
    }
    report_md.parent.mkdir(parents=True, exist_ok=True)
    report_md.write_text(
        render_phase0_markdown(
            report,
            wasde_inventory=wasde_inventory,
            region_quality=region_quality,
            psd_target_audit=psd_target_audit,
            target_class_balance=target_class_balance,
            static_feature_reuse=static_feature_reuse,
        ),
        encoding="utf-8",
    )
    outputs["phase0_markdown_report"] = str(report_md)

    print(json.dumps({"report": report, "outputs": outputs}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
