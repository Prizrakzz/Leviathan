"""Build the Phase 0 read-only audit for WASDE snapshot modeling."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    build_phase1_source_truth_report,
    build_origin_attribute_coverage,
    build_parser_artifact_report,
    build_psd_target_compatibility_audit,
    build_release_sequence_coverage,
    build_static_feature_reuse_audit,
    build_stock_to_use_constructibility,
    build_wasde_inventory,
    build_wasde_region_mapping_candidates,
    build_wasde_region_quality,
    build_wasde_mapping_gaps,
    build_wasde_source_truth_audit,
    render_phase0_markdown,
)

DEFAULT_BUCKET = "leviathan-dev-shahem-001"
DEFAULT_REGION = "us-east-1"
DEFAULT_WASDE_PREFIX = "silver/wasde/"
DEFAULT_PSD_KEY = "silver/psd/part-000.parquet"
DEFAULT_OUTPUT_DIR = "data/phase_wasde_snapshot"
DEFAULT_REPORT_MD = "docs/WASDE_SNAPSHOT_PHASE0_AUDIT.md"
DEFAULT_PHASE1_VERSION = "phase1_wasde_source_truth_audit"


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


def _read_parquet_key(s3, bucket: str, key: str, columns: list[str] | None = None) -> pd.DataFrame:
    body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
    return pd.read_parquet(io.BytesIO(body), columns=columns)


def _read_parquet_prefix(
    s3,
    bucket: str,
    prefix: str,
    *,
    workers: int = 8,
    columns: list[str] | None = None,
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    keys = _list_parquet_keys(s3, bucket, prefix)
    if not keys:
        return pd.DataFrame()
    if workers <= 1:
        for key in keys:
            frame = _read_parquet_key(s3, bucket, key, columns=columns)
            if not frame.empty:
                frames.append(frame)
    else:
        with ThreadPoolExecutor(max_workers=max(1, int(workers))) as pool:
            futures = {
                pool.submit(_read_parquet_key, s3, bucket, key, columns): key
                for key in keys
            }
            failures: list[str] = []
            for future in as_completed(futures):
                key = futures[future]
                try:
                    frame = future.result()
                    if not frame.empty:
                        frames.append(frame)
                except Exception as exc:  # noqa: BLE001
                    failures.append(f"{key}: {exc}")
            if failures:
                raise RuntimeError(
                    "failed to read WASDE parquet keys: " + "; ".join(failures[:5])
                )
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _write_frame(path: Path, frame: pd.DataFrame) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)
    return str(path)


def _write_json(path: Path, payload: dict) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return str(path)


def _parquet_bytes(frame: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    frame.to_parquet(buf, index=False, compression="snappy", engine="pyarrow")
    return buf.getvalue()


def _write_s3_frame(s3, bucket: str, key: str, frame: pd.DataFrame) -> str:
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=_parquet_bytes(frame),
        ContentType="application/octet-stream",
    )
    return f"s3://{bucket}/{key}"


def _write_s3_json(s3, bucket: str, key: str, payload: dict) -> str:
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(payload, indent=2, sort_keys=True).encode("utf-8"),
        ContentType="application/json",
    )
    return f"s3://{bucket}/{key}"


def _parse_csv(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(part.strip().lower() for part in value.split(",") if part.strip())


def _filter_commodities(frame: pd.DataFrame, commodities: tuple[str, ...]) -> pd.DataFrame:
    if not commodities or frame.empty or "commodity" not in frame.columns:
        return frame
    return frame.loc[frame["commodity"].astype(str).str.lower().isin(set(commodities))].copy()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bucket", default=DEFAULT_BUCKET)
    parser.add_argument("--aws-region", default=DEFAULT_REGION, dest="aws_region")
    parser.add_argument("--wasde-prefix", default=DEFAULT_WASDE_PREFIX, dest="wasde_prefix")
    parser.add_argument("--psd-key", default=DEFAULT_PSD_KEY, dest="psd_key")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, dest="output_dir")
    parser.add_argument("--output-local", default=None, dest="output_local")
    parser.add_argument("--output-prefix", default="", dest="output_prefix")
    parser.add_argument(
        "--report-md",
        default="",
        dest="report_md",
        help=(
            "Optional markdown report path. Omit for scoped Phase 1 audits so "
            "they do not overwrite the broader Phase 0 report."
        ),
    )
    parser.add_argument("--commodities", default="", help="Comma-separated WASDE commodities to audit.")
    parser.add_argument("--surfaces", default="", help="Reserved for future surface-scoped reporting.")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--dry-run", action="store_true", dest="dry_run")
    parser.add_argument(
        "--source-dataset-version",
        default="phase0_wasde_snapshot_audit",
        dest="source_dataset_version",
    )
    return parser.parse_args()


def main() -> None:
    load_env()
    args = _parse_args()
    output_dir = Path(args.output_local or args.output_dir)
    report_md = Path(args.report_md) if args.report_md else None
    commodities = _parse_csv(args.commodities)

    s3 = boto3.client("s3", region_name=args.aws_region)
    wasde_columns = [
        "release_date",
        "commodity",
        "table_type",
        "region",
        "marketing_year",
        "attribute",
        "estimate",
        "revision",
    ]
    wasde = _read_parquet_prefix(
        s3,
        args.bucket,
        args.wasde_prefix,
        workers=max(1, args.workers),
        columns=wasde_columns,
    )
    wasde = _filter_commodities(wasde, commodities)
    psd = _read_parquet_key(s3, args.bucket, args.psd_key)

    wasde_inventory = build_wasde_inventory(wasde)
    region_quality = build_wasde_region_quality(wasde)
    mapping_candidates = build_wasde_region_mapping_candidates(region_quality)
    source_truth = build_wasde_source_truth_audit(wasde)
    origin_attribute_coverage = build_origin_attribute_coverage(source_truth)
    release_sequence_coverage = build_release_sequence_coverage(source_truth)
    parser_artifacts = build_parser_artifact_report(source_truth)
    mapping_gaps = build_wasde_mapping_gaps(source_truth)
    stock_to_use_constructibility = build_stock_to_use_constructibility(source_truth)
    phase1_report = build_phase1_source_truth_report(
        bucket=args.bucket,
        source_truth=source_truth,
        origin_attribute_coverage=origin_attribute_coverage,
        parser_artifacts=parser_artifacts,
        mapping_gaps=mapping_gaps,
        stock_to_use_constructibility=stock_to_use_constructibility,
        commodities=commodities,
    )
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

    if args.dry_run:
        print(json.dumps({
            "dry_run": True,
            "wasde_rows": int(len(wasde)),
            "source_truth_rows": int(len(source_truth)),
            "phase1_report": phase1_report,
            "would_write_local": str(output_dir),
            "would_write_s3_prefix": args.output_prefix,
        }, indent=2, sort_keys=True))
        return

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
        "phase1_source_truth_audit": _write_frame(
            output_dir / "phase1_wasde_source_truth_audit.parquet",
            source_truth,
        ),
        "phase1_origin_attribute_coverage": _write_frame(
            output_dir / "wasde_origin_attribute_coverage.parquet",
            origin_attribute_coverage,
        ),
        "phase1_release_sequence_coverage": _write_frame(
            output_dir / "wasde_release_sequence_coverage.parquet",
            release_sequence_coverage,
        ),
        "phase1_parser_artifacts": _write_frame(
            output_dir / "wasde_parser_artifacts.parquet",
            parser_artifacts,
        ),
        "phase1_mapping_gaps": _write_frame(
            output_dir / "wasde_mapping_gaps.parquet",
            mapping_gaps,
        ),
        "phase1_stock_to_use_constructibility": _write_frame(
            output_dir / "wasde_stock_to_use_constructibility.parquet",
            stock_to_use_constructibility,
        ),
        "phase1_audit_report": _write_json(
            output_dir / "phase1_wasde_source_truth_audit.json",
            phase1_report,
        ),
    }
    if report_md is not None:
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

    if args.output_prefix:
        prefix = args.output_prefix.strip("/")
        s3_outputs = {
            "phase1_source_truth_audit": _write_s3_frame(
                s3,
                args.bucket,
                f"{prefix}/source_truth_audit.parquet",
                source_truth,
            ),
            "phase1_origin_attribute_coverage": _write_s3_frame(
                s3,
                args.bucket,
                f"{prefix}/origin_attribute_coverage.parquet",
                origin_attribute_coverage,
            ),
            "phase1_release_sequence_coverage": _write_s3_frame(
                s3,
                args.bucket,
                f"{prefix}/release_sequence_coverage.parquet",
                release_sequence_coverage,
            ),
            "phase1_parser_artifacts": _write_s3_frame(
                s3,
                args.bucket,
                f"{prefix}/parser_artifacts.parquet",
                parser_artifacts,
            ),
            "phase1_mapping_gaps": _write_s3_frame(
                s3,
                args.bucket,
                f"{prefix}/mapping_gaps.parquet",
                mapping_gaps,
            ),
            "phase1_stock_to_use_constructibility": _write_s3_frame(
                s3,
                args.bucket,
                f"{prefix}/stock_to_use_constructibility.parquet",
                stock_to_use_constructibility,
            ),
            "phase1_audit_report": _write_s3_json(
                s3,
                args.bucket,
                f"{prefix}/audit_summary.json",
                phase1_report,
            ),
        }
        outputs["s3"] = s3_outputs

    print(json.dumps({
        "report": report,
        "phase1_report": phase1_report,
        "outputs": outputs,
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
