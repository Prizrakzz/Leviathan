"""Finalize a sharded immutable feature-spine dataset version.

Sharded feature-spine backfills intentionally write one commodity at a time and
skip the dataset-level artifacts to avoid write races.  This task is the cheap
second pass: validate that every expected commodity shard exists, then write the
version-level feature catalog and dataset manifest.
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import pandas as pd
import pyarrow.parquet as pq

from leviathan.common.config import get_required_env, load_env
from leviathan.common.constants import ALL_COMMODITIES
from leviathan.common.logging import get_logger
from leviathan.features.pivot import build_feature_catalog
from leviathan.features.spine import load_countries
from leviathan.storage.paths import (
    gold_feature_catalog_version_key,
    gold_feature_matrix_version_key,
    gold_feature_spine_commodity_manifest_key,
    gold_feature_spine_manifest_key,
    gold_feature_spine_version_key,
    gold_training_windows_version_key,
)
from leviathan.storage.s3 import get_thread_local_s3_client

logger = get_logger("feature_spine_finalize_task")


@dataclass(frozen=True)
class FinalizeOptions:
    dataset_version: str
    commodities: list[str]
    bucket: str | None = None
    aws_region: str | None = None
    local_root: Path | None = None
    fail_if_exists: bool = True
    dry_run: bool = False
    source_certification_report: str = ""


def _bool_arg(value: bool | str) -> bool:
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "t", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "f", "no", "n", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"expected boolean value, got {value!r}")


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL, text=True
        ).strip()
    except Exception:  # noqa: BLE001 - git is optional inside Batch containers
        return "unknown"


def _default_commodities() -> list[str]:
    return [str(c) for c in ALL_COMMODITIES if load_countries(str(c))]


def _parse_commodities(raw: str | None) -> list[str]:
    if raw is None or raw.strip().lower() in {"", "all"}:
        return _default_commodities()
    return [part.strip() for part in raw.split(",") if part.strip()]


def _local_path(options: FinalizeOptions, key: str) -> Path:
    if options.local_root is None:
        raise ValueError("local path requested without local_root")
    return options.local_root / key


def _read_bytes(options: FinalizeOptions, key: str) -> bytes:
    if options.local_root is not None:
        return _local_path(options, key).read_bytes()
    s3 = get_thread_local_s3_client(options.aws_region)
    return s3.get_object(Bucket=options.bucket, Key=key)["Body"].read()


def _write_bytes(
    options: FinalizeOptions,
    key: str,
    body: bytes,
    content_type: str,
) -> None:
    if options.local_root is not None:
        path = _local_path(options, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        return
    s3 = get_thread_local_s3_client(options.aws_region)
    s3.put_object(Bucket=options.bucket, Key=key, Body=body, ContentType=content_type)


def _target_exists(options: FinalizeOptions, key: str) -> bool:
    if options.local_root is not None:
        return _local_path(options, key).exists()
    s3 = get_thread_local_s3_client(options.aws_region)
    try:
        s3.head_object(Bucket=options.bucket, Key=key)
        return True
    except Exception as exc:  # noqa: BLE001 - boto optional in local tests
        response = getattr(exc, "response", {})
        code = str(response.get("Error", {}).get("Code", ""))
        if code in {"404", "NoSuchKey", "NotFound"}:
            return False
        raise


def _assert_missing(options: FinalizeOptions, key: str) -> None:
    if options.fail_if_exists and _target_exists(options, key):
        raise FileExistsError(f"refusing to overwrite immutable dataset artifact: {key}")


def _read_json(options: FinalizeOptions, key: str) -> dict:
    return json.loads(_read_bytes(options, key).decode("utf-8"))


def _parquet_metadata(options: FinalizeOptions, key: str) -> pq.FileMetaData:
    if options.local_root is not None:
        return pq.read_metadata(_local_path(options, key))
    return pq.read_metadata(io.BytesIO(_read_bytes(options, key)))


def _read_spine_features(options: FinalizeOptions, key: str) -> pd.DataFrame:
    columns = ["feature", "is_label"]
    if options.local_root is not None:
        return pd.read_parquet(_local_path(options, key), columns=columns)
    return pd.read_parquet(io.BytesIO(_read_bytes(options, key)), columns=columns)


def _read_training_windows(options: FinalizeOptions, key: str) -> pd.DataFrame:
    columns = ["commodity", "tier", "n_label_years", "dense_start_year"]
    if options.local_root is not None:
        return pd.read_parquet(_local_path(options, key), columns=columns)
    return pd.read_parquet(io.BytesIO(_read_bytes(options, key)), columns=columns)


def _require_present(options: FinalizeOptions, key: str, label: str) -> None:
    if not _target_exists(options, key):
        raise FileNotFoundError(f"missing {label}: {key}")


def _summarize_inputs(inputs: list[dict]) -> list[dict]:
    """Keep source provenance compact enough for a dataset-level manifest."""
    summarized = []
    for probe in inputs:
        summarized.append({
            "source": probe.get("source"),
            "location": probe.get("location"),
            "exists": probe.get("exists"),
            "num_files": int(probe.get("num_files") or 0),
            "num_rows": int(probe.get("num_rows") or 0),
        })
    return summarized


def _validate_commodity(options: FinalizeOptions, commodity: str) -> dict:
    spine_key = gold_feature_spine_version_key(options.dataset_version, commodity)
    matrix_key = gold_feature_matrix_version_key(options.dataset_version, commodity)
    manifest_key = gold_feature_spine_commodity_manifest_key(
        options.dataset_version, commodity
    )

    _require_present(options, spine_key, f"spine partition for {commodity}")
    _require_present(options, matrix_key, f"matrix partition for {commodity}")
    _require_present(options, manifest_key, f"commodity manifest for {commodity}")

    manifest = _read_json(options, manifest_key)
    if manifest.get("dataset_version") != options.dataset_version:
        raise ValueError(
            f"{commodity} manifest dataset_version mismatch: "
            f"{manifest.get('dataset_version')!r} != {options.dataset_version!r}"
        )
    if manifest.get("commodity") != commodity:
        raise ValueError(
            f"{commodity} manifest commodity mismatch: {manifest.get('commodity')!r}"
        )
    if manifest.get("spine_version_key") != spine_key:
        raise ValueError(f"{commodity} manifest points at wrong spine key")
    if manifest.get("matrix_version_key") != matrix_key:
        raise ValueError(f"{commodity} manifest points at wrong matrix key")

    report = manifest.get("report") or {}
    if report.get("passed") is not True:
        raise ValueError(f"{commodity} report did not pass validation")
    hard_failures = report.get("hard_failures") or []
    if hard_failures:
        raise ValueError(f"{commodity} report has hard failures: {hard_failures}")

    spine_meta = _parquet_metadata(options, spine_key)
    matrix_meta = _parquet_metadata(options, matrix_key)
    if spine_meta.num_rows <= 0:
        raise ValueError(f"{commodity} spine partition is empty")
    if matrix_meta.num_rows <= 0:
        raise ValueError(f"{commodity} matrix partition is empty")

    reported_rows = report.get("row_count")
    if reported_rows is not None and int(reported_rows) != int(spine_meta.num_rows):
        raise ValueError(
            f"{commodity} row count mismatch: report={reported_rows} "
            f"parquet={spine_meta.num_rows}"
        )

    return {
        "commodity": commodity,
        "status": "validated",
        "spine_rows": int(spine_meta.num_rows),
        "matrix_rows": int(matrix_meta.num_rows),
        "matrix_columns": int(matrix_meta.num_columns),
        "feature_count": int(report.get("feature_count") or 0),
        "label_row_count": int(report.get("label_row_count") or 0),
        "warning_count": len(report.get("soft_warnings") or []),
        "hard_failure_count": len(hard_failures),
        "built_at": manifest.get("built_at"),
        "git_sha": manifest.get("git_sha"),
        "crop_years": manifest.get("crop_years"),
        "inputs": _summarize_inputs(manifest.get("inputs") or []),
        "spine_version_key": spine_key,
        "matrix_version_key": matrix_key,
        "manifest_key": manifest_key,
        "report": report,
    }


def _build_catalog(
    options: FinalizeOptions,
    commodity_summaries: list[dict],
) -> pd.DataFrame:
    feature_commodity_map: dict[str, set[str]] = defaultdict(set)
    feature_is_label: dict[str, bool] = {}
    written_commodities = {summary["commodity"] for summary in commodity_summaries}

    for summary in commodity_summaries:
        commodity = summary["commodity"]
        features = _read_spine_features(options, summary["spine_version_key"])
        for row in features.drop_duplicates("feature").itertuples(index=False):
            feature = str(row.feature)
            feature_commodity_map[feature].add(commodity)
            feature_is_label[feature] = bool(row.is_label)

    return build_feature_catalog(
        feature_commodity_map,
        feature_is_label,
        written_commodities,
    )


def _source_summary(commodity_summaries: list[dict]) -> dict[str, dict[str, int]]:
    summary: dict[str, dict[str, int]] = defaultdict(
        lambda: {"num_files": 0, "num_rows": 0, "seen_in_commodities": 0}
    )
    for commodity in commodity_summaries:
        seen_sources: set[str] = set()
        for probe in commodity.get("inputs", []):
            source = str(probe.get("source", "unknown"))
            summary[source]["num_files"] += int(probe.get("num_files") or 0)
            summary[source]["num_rows"] += max(0, int(probe.get("num_rows") or 0))
            seen_sources.add(source)
        for source in seen_sources:
            summary[source]["seen_in_commodities"] += 1
    return dict(sorted(summary.items()))


def _training_windows_summary(options: FinalizeOptions) -> dict:
    parquet_key = gold_training_windows_version_key(options.dataset_version)
    markdown_key = gold_training_windows_version_key(
        options.dataset_version, "training_windows.md"
    )
    parquet_exists = _target_exists(options, parquet_key)
    markdown_exists = _target_exists(options, markdown_key)
    if not parquet_exists and not markdown_exists:
        return {
            "available": False,
            "training_windows_key": parquet_key,
            "training_windows_markdown_key": markdown_key,
            "row_count": 0,
            "commodity_count": 0,
            "tier_count": 0,
            "tiers": [],
            "label_window_rows": 0,
            "dense_window_rows": 0,
        }
    if not parquet_exists or not markdown_exists:
        raise FileNotFoundError(
            "partial training-window artifact set for "
            f"{options.dataset_version}: parquet={parquet_exists}, markdown={markdown_exists}"
        )

    windows = _read_training_windows(options, parquet_key)
    return {
        "available": True,
        "training_windows_key": parquet_key,
        "training_windows_markdown_key": markdown_key,
        "row_count": int(len(windows)),
        "commodity_count": int(windows["commodity"].nunique()),
        "tier_count": int(windows["tier"].nunique()),
        "tiers": sorted(str(tier) for tier in windows["tier"].dropna().unique()),
        "label_window_rows": int((windows["n_label_years"].fillna(0) > 0).sum()),
        "dense_window_rows": int(windows["dense_start_year"].notna().sum()),
    }


def _build_dataset_manifest(
    options: FinalizeOptions,
    commodity_summaries: list[dict],
    catalog_df: pd.DataFrame,
) -> dict:
    crop_years = [
        year
        for summary in commodity_summaries
        for year in (summary.get("crop_years") or [])
        if year is not None
    ]
    git_shas = sorted({
        str(summary.get("git_sha"))
        for summary in commodity_summaries
        if summary.get("git_sha")
    })
    training_windows = _training_windows_summary(options)

    return {
        "task": "feature_spine_finalize_task",
        "dataset_kind": "legacy_gold_feature_spine_version",
        "dataset_version": options.dataset_version,
        "finalized_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "finalizer_git_sha": _git_sha(),
        "commodity_build_git_shas": git_shas,
        "source_certification_report": options.source_certification_report or None,
        "crop_years": [min(crop_years), max(crop_years)] if crop_years else None,
        "summary": {
            "commodity_count": len(commodity_summaries),
            "total_spine_rows": sum(c["spine_rows"] for c in commodity_summaries),
            "total_matrix_rows": sum(c["matrix_rows"] for c in commodity_summaries),
            "total_label_rows": sum(c["label_row_count"] for c in commodity_summaries),
            "feature_count": int(len(catalog_df)),
            "label_feature_count": int(catalog_df["is_label"].sum()),
            "universal_feature_count": int((catalog_df["scope"] == "universal").sum()),
            "group_feature_count": int((catalog_df["scope"] == "group").sum()),
            "commodity_feature_count": int((catalog_df["scope"] == "commodity").sum()),
            "warning_count": sum(c["warning_count"] for c in commodity_summaries),
            "hard_failure_count": sum(c["hard_failure_count"] for c in commodity_summaries),
            "training_windows_available": bool(training_windows["available"]),
            "training_windows_row_count": int(training_windows["row_count"]),
            "training_windows_commodity_count": int(training_windows["commodity_count"]),
        },
        "source_summary": _source_summary(commodity_summaries),
        "training_windows": training_windows,
        "commodities": commodity_summaries,
        "outputs": {
            "feature_spine_prefix": (
                f"gold/feature_spine_versions/"
                f"dataset_version={options.dataset_version}/"
            ),
            "feature_matrix_prefix": (
                f"gold/feature_matrix_versions/"
                f"dataset_version={options.dataset_version}/"
            ),
            "commodity_manifest_prefix": (
                f"gold/feature_spine_commodity_manifests/"
                f"dataset_version={options.dataset_version}/"
            ),
            "feature_catalog_key": gold_feature_catalog_version_key(
                options.dataset_version
            ),
            "manifest_key": gold_feature_spine_manifest_key(options.dataset_version),
            "training_windows_key": training_windows["training_windows_key"],
            "training_windows_markdown_key": (
                training_windows["training_windows_markdown_key"]
            ),
        },
    }


def finalize_dataset(options: FinalizeOptions) -> dict:
    catalog_key = gold_feature_catalog_version_key(options.dataset_version)
    manifest_key = gold_feature_spine_manifest_key(options.dataset_version)
    _assert_missing(options, catalog_key)
    _assert_missing(options, manifest_key)

    commodity_summaries = [
        _validate_commodity(options, commodity) for commodity in options.commodities
    ]
    catalog_df = _build_catalog(options, commodity_summaries)
    dataset_manifest = _build_dataset_manifest(options, commodity_summaries, catalog_df)

    if options.dry_run:
        return dataset_manifest

    buf = io.BytesIO()
    catalog_df.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
    _write_bytes(options, catalog_key, buf.getvalue(), "application/octet-stream")
    _write_bytes(
        options,
        manifest_key,
        json.dumps(dataset_manifest, indent=2, default=str).encode("utf-8"),
        "application/json",
    )
    logger.info(
        "Finalized feature-spine dataset %s: %d commodities, %d features",
        options.dataset_version,
        len(commodity_summaries),
        len(catalog_df),
    )
    return dataset_manifest


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Finalize a sharded gold/feature_spine dataset version"
    )
    parser.add_argument("--dataset-version", required=True, dest="dataset_version")
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    parser.add_argument("--local-root", default=None, dest="local_root")
    parser.add_argument(
        "--expected-commodities",
        default="all",
        dest="expected_commodities",
        help="Comma-separated commodity slugs, or 'all' for every commodity with geographies.",
    )
    parser.add_argument(
        "--fail-if-exists",
        nargs="?",
        const=True,
        default=True,
        type=_bool_arg,
        dest="fail_if_exists",
    )
    parser.add_argument(
        "--force-overwrite",
        action="store_true",
        default=False,
        dest="force_overwrite",
        help="Overwrite existing catalog/manifest artifacts.",
    )
    parser.add_argument("--dry-run", action="store_true", default=False)
    parser.add_argument(
        "--source-certification-report",
        default="",
        dest="source_certification_report",
    )
    return parser.parse_args()


def main() -> None:
    load_env()
    args = _parse_args()
    if not args.local_root:
        args.bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
        args.aws_region = args.aws_region or get_required_env("AWS_REGION")

    options = FinalizeOptions(
        dataset_version=args.dataset_version,
        commodities=_parse_commodities(args.expected_commodities),
        bucket=args.bucket,
        aws_region=args.aws_region,
        local_root=Path(args.local_root) if args.local_root else None,
        fail_if_exists=bool(args.fail_if_exists) and not args.force_overwrite,
        dry_run=bool(args.dry_run),
        source_certification_report=args.source_certification_report,
    )
    manifest = finalize_dataset(options)
    logger.info(
        "Done dataset_version=%s commodities=%d dry_run=%s",
        options.dataset_version,
        manifest["summary"]["commodity_count"],
        options.dry_run,
    )


if __name__ == "__main__":
    main()
