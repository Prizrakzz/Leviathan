"""Build Phase 8 model-ready datasets from immutable gold matrices."""
from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import pandas as pd

from leviathan.common.config import get_required_env, load_env
from leviathan.common.constants import ALL_COMMODITIES
from leviathan.common.logging import get_logger
from leviathan.features.spine import load_countries
from leviathan.model_datasets.builder import build_commodity_model_datasets
from leviathan.model_datasets.psd_model_ready import (
    PSDModelReadyBuildConfig,
    PSD_MATRIX_ID_COLUMNS,
    build_psd_commodity_model_datasets,
)
from leviathan.model_datasets.psd_target_builder import build_psd_target_panel
from leviathan.model_datasets.psd_targets import load_psd_metric_targets
from leviathan.model_datasets.targets import (
    default_source_dataset_version,
    load_target_definitions,
)
from leviathan.storage.paths import (
    gold_feature_matrix_version_key,
    gold_feature_set_version_key,
    gold_model_ready_baseline_metrics_key,
    gold_model_ready_manifest_key,
    gold_model_ready_matrix_key,
    gold_model_ready_target_key,
)
from leviathan.storage.s3 import get_thread_local_s3_client

logger = get_logger("build_model_ready_datasets")

MODEL_READY_NON_FEATURE_COLUMNS = {
    *{
        "source_dataset_version",
        "dataset_key",
        "commodity",
        "target_key",
        "country",
        "crop_year",
        "target_value",
        "actual_value",
        "trend_prediction",
        "prior_year_value",
        "trailing_mean_prediction",
        "zero_anomaly_baseline",
        "prior_year_anomaly_baseline",
        "trailing_mean_anomaly_baseline",
        "trailing_trend_anomaly_baseline",
        "history_years",
        "is_trainable",
        "excluded_reason",
        "target_title",
        "target_unit",
    },
    *PSD_MATRIX_ID_COLUMNS,
}


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL, text=True
        ).strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def _default_model_dataset_version() -> str:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    git_sha = _git_sha()
    suffix = git_sha[:12] if git_sha and git_sha != "unknown" else "unknown"
    return f"{stamp}_{suffix}_model_ready"


def _bool_arg(value: bool | str) -> bool:
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "t", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "f", "no", "n", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"expected boolean value, got {value!r}")


def _parse_commodities(raw: str) -> list[str]:
    if raw.strip().lower() == "all":
        return [str(c) for c in ALL_COMMODITIES if load_countries(str(c))]
    commodities = [part.strip() for part in raw.split(",") if part.strip()]
    unknown = [c for c in commodities if c not in ALL_COMMODITIES]
    if unknown:
        raise SystemExit(f"ERROR: Unknown commodities: {unknown}")
    return commodities


def _parse_csv_tuple(raw: str | None) -> tuple[str, ...]:
    if raw is None:
        return ()
    normalized = raw.strip()
    if not normalized or normalized.lower() in {"none", "null", "default"}:
        return ()
    return tuple(part.strip() for part in normalized.split(",") if part.strip())


def _local_path(args: argparse.Namespace, key: str) -> Path:
    if not args.local_root:
        raise ValueError("local path requested without --local-root")
    return Path(args.local_root) / key


def _read_bytes(args: argparse.Namespace, key: str) -> bytes:
    if args.local_root:
        return _local_path(args, key).read_bytes()
    s3 = get_thread_local_s3_client(args.aws_region)
    return s3.get_object(Bucket=args.bucket, Key=key)["Body"].read()


def _read_parquet(args: argparse.Namespace, key: str) -> pd.DataFrame:
    body = _read_bytes(args, key)
    return pd.read_parquet(io.BytesIO(body))


def _target_exists(args: argparse.Namespace, key: str) -> bool:
    if args.local_root:
        return _local_path(args, key).exists()
    s3 = get_thread_local_s3_client(args.aws_region)
    try:
        s3.head_object(Bucket=args.bucket, Key=key)
        return True
    except Exception as exc:  # noqa: BLE001
        response = getattr(exc, "response", {})
        code = str(response.get("Error", {}).get("Code", ""))
        if code in {"404", "NoSuchKey", "NotFound"}:
            return False
        raise


def _write_bytes(
    args: argparse.Namespace,
    key: str,
    body: bytes,
    content_type: str,
) -> str:
    exists = _target_exists(args, key)
    if exists and args.skip_existing_versioned:
        return "skipped_existing"
    if exists and not args.force_overwrite:
        raise FileExistsError(f"refusing to overwrite immutable model-ready object: {key}")

    if args.local_root:
        path = _local_path(args, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    else:
        s3 = get_thread_local_s3_client(args.aws_region)
        s3.put_object(Bucket=args.bucket, Key=key, Body=body, ContentType=content_type)
    return "written"


def _parquet_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
    return buf.getvalue()


def _process_commodity(
    args: argparse.Namespace,
    commodity: str,
    target_definitions,
    feature_membership: pd.DataFrame,
) -> dict:
    matrix_key = gold_feature_matrix_version_key(args.source_dataset_version, commodity)
    result = {
        "commodity": commodity,
        "status": "unknown",
        "matrix_key": matrix_key,
        "target_outputs": [],
        "matrix_outputs": [],
        "summaries": [],
    }
    try:
        matrix = _read_parquet(args, matrix_key)
    except FileNotFoundError:
        result["status"] = "skipped_missing_matrix"
        return result
    except Exception as exc:  # noqa: BLE001
        response = getattr(exc, "response", {})
        code = str(response.get("Error", {}).get("Code", ""))
        if code in {"404", "NoSuchKey", "NotFound"}:
            result["status"] = "skipped_missing_matrix"
            return result
        raise

    built = build_commodity_model_datasets(
        matrix,
        commodity=commodity,
        source_dataset_version=args.source_dataset_version,
        target_definitions=target_definitions,
        feature_membership=feature_membership,
    )
    result["summaries"] = built.summaries
    if args.dry_run:
        result["status"] = "dry_run"
        return result

    for dataset_key, target_df in built.target_tables.items():
        key = gold_model_ready_target_key(
            args.model_dataset_version, dataset_key, commodity
        )
        status = _write_bytes(
            args, key, _parquet_bytes(target_df), "application/octet-stream"
        )
        result["target_outputs"].append({
            "dataset_key": dataset_key,
            "key": key,
            "status": status,
            "row_count": int(len(target_df)),
        })

    for (dataset_key, target_key), matrix_df in built.matrices.items():
        key = gold_model_ready_matrix_key(
            args.model_dataset_version, dataset_key, commodity, target_key
        )
        status = _write_bytes(
            args, key, _parquet_bytes(matrix_df), "application/octet-stream"
        )
        result["matrix_outputs"].append({
            "dataset_key": dataset_key,
            "target_key": target_key,
            "key": key,
            "status": status,
            "row_count": int(len(matrix_df)),
            "column_count": int(len(matrix_df.columns)),
            "feature_count": int(
                len([c for c in matrix_df.columns if c not in MODEL_READY_NON_FEATURE_COLUMNS])
            ),
        })

    result["baseline_metrics"] = built.baseline_metrics
    result["status"] = "written"
    return result


def _process_psd_commodity(
    args: argparse.Namespace,
    commodity: str,
    psd_targets: pd.DataFrame,
    feature_membership: pd.DataFrame,
    target_keys: tuple[str, ...],
) -> dict:
    matrix_key = gold_feature_matrix_version_key(args.source_dataset_version, commodity)
    result = {
        "commodity": commodity,
        "status": "unknown",
        "matrix_key": matrix_key,
        "target_outputs": [],
        "matrix_outputs": [],
        "summaries": [],
    }
    try:
        matrix = _read_parquet(args, matrix_key)
    except FileNotFoundError:
        result["status"] = "skipped_missing_matrix"
        return result
    except Exception as exc:  # noqa: BLE001
        response = getattr(exc, "response", {})
        code = str(response.get("Error", {}).get("Code", ""))
        if code in {"404", "NoSuchKey", "NotFound"}:
            result["status"] = "skipped_missing_matrix"
            return result
        raise

    built = build_psd_commodity_model_datasets(
        matrix,
        psd_targets,
        commodity=commodity,
        feature_membership=feature_membership,
        config=(
            PSDModelReadyBuildConfig(
                compatible_feature_sets=args.compatible_feature_sets_tuple
            )
            if args.compatible_feature_sets_tuple else None
        ),
        target_keys=target_keys,
    )
    result["summaries"] = built.summaries
    if args.dry_run:
        result["status"] = "dry_run"
        return result

    for dataset_key, target_df in built.target_tables.items():
        key = gold_model_ready_target_key(
            args.model_dataset_version, dataset_key, commodity
        )
        status = _write_bytes(
            args, key, _parquet_bytes(target_df), "application/octet-stream"
        )
        result["target_outputs"].append({
            "dataset_key": dataset_key,
            "key": key,
            "status": status,
            "row_count": int(len(target_df)),
        })

    for (dataset_key, target_key), matrix_df in built.matrices.items():
        key = gold_model_ready_matrix_key(
            args.model_dataset_version, dataset_key, commodity, target_key
        )
        status = _write_bytes(
            args, key, _parquet_bytes(matrix_df), "application/octet-stream"
        )
        result["matrix_outputs"].append({
            "dataset_key": dataset_key,
            "target_key": target_key,
            "key": key,
            "status": status,
            "row_count": int(len(matrix_df)),
            "column_count": int(len(matrix_df.columns)),
            "feature_count": int(
                len([c for c in matrix_df.columns if c not in MODEL_READY_NON_FEATURE_COLUMNS])
            ),
        })

    result["baseline_metrics"] = built.baseline_metrics
    result["status"] = "written"
    return result


def _build_manifest(
    args: argparse.Namespace,
    *,
    target_config_sha: str,
    target_config: dict,
    commodities: list[str],
    results: list[dict],
    baseline_metrics: pd.DataFrame,
    target_source: str,
    psd_mapping_sha: str | None = None,
) -> dict:
    built = [r for r in results if r["status"] in {"written", "dry_run"}]
    failed = [r for r in results if r["status"] == "error"]
    skipped = [r for r in results if str(r["status"]).startswith("skipped")]
    target_summaries = [
        summary
        for result in results
        for summary in result.get("summaries", [])
    ]
    built_targets = [s for s in target_summaries if s.get("status") == "built"]

    target_status_counts: dict[str, int] = {}
    mapping_confidence_counts: dict[str, int] = {}
    for summary in built_targets:
        for key, value in (summary.get("target_status_counts") or {}).items():
            target_status_counts[str(key)] = target_status_counts.get(str(key), 0) + int(value)
        for key, value in (summary.get("mapping_confidence_counts") or {}).items():
            mapping_confidence_counts[str(key)] = (
                mapping_confidence_counts.get(str(key), 0) + int(value)
            )

    manifest = {
        "task": "build_model_ready_datasets",
        "dataset_kind": "gold_model_ready_dataset_version",
        "target_source": target_source,
        "model_dataset_version": args.model_dataset_version,
        "source_dataset_version": args.source_dataset_version,
        "built_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "git_sha": _git_sha(),
        "target_config_sha": target_config_sha,
        "target_config_defaults": target_config.get("defaults", {}),
        "requested_commodities": commodities,
        "summary": {
            "requested_commodity_count": len(commodities),
            "processed_commodity_count": len(built),
            "skipped_commodity_count": len(skipped),
            "failed_commodity_count": len(failed),
            "built_target_count": len(built_targets),
            "target_row_count": int(sum(
                o.get("row_count", 0)
                for r in results for o in r.get("target_outputs", [])
            )),
            "matrix_count": int(sum(len(r.get("matrix_outputs", [])) for r in results)),
            "baseline_metric_count": int(len(baseline_metrics)),
            "target_status_counts": target_status_counts,
            "mapping_confidence_counts": mapping_confidence_counts,
        },
        "targets": target_summaries,
        "baseline_metrics": {
            "key": gold_model_ready_baseline_metrics_key(args.model_dataset_version),
            "row_count": int(len(baseline_metrics)),
        },
        "outputs": {
            "target_prefix": (
                f"gold/model_ready_targets/"
                f"dataset_version={args.model_dataset_version}/"
            ),
            "matrix_prefix": (
                f"gold/model_ready_matrices/"
                f"dataset_version={args.model_dataset_version}/"
            ),
            "baseline_metrics_key": gold_model_ready_baseline_metrics_key(
                args.model_dataset_version
            ),
            "manifest_key": gold_model_ready_manifest_key(args.model_dataset_version),
        },
        "commodities": results,
    }
    if psd_mapping_sha:
        manifest["psd_mapping_sha"] = psd_mapping_sha
        manifest["psd_metric_target_config"] = (
            args.psd_target_config or "configs/ml/psd_metric_targets.yaml"
        )
        manifest["psd_compatible_feature_sets"] = (
            list(args.compatible_feature_sets_tuple)
            if args.compatible_feature_sets_tuple else "default"
        )
    return manifest


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build model-ready datasets from gold feature matrix versions"
    )
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    parser.add_argument("--local-root", default=None, dest="local_root")
    parser.add_argument("--source-dataset-version", default=None, dest="source_dataset_version")
    parser.add_argument("--model-dataset-version", default=None, dest="model_dataset_version")
    parser.add_argument("--target-config", default=None, dest="target_config")
    parser.add_argument(
        "--target-source",
        choices=["faostat", "psd"],
        default="faostat",
        dest="target_source",
    )
    parser.add_argument(
        "--psd-source-key",
        default="silver/psd/part-000.parquet",
        dest="psd_source_key",
    )
    parser.add_argument("--psd-target-config", default=None, dest="psd_target_config")
    parser.add_argument("--commodities", default="all")
    parser.add_argument("--target-keys", default="", dest="target_keys")
    parser.add_argument(
        "--compatible-feature-sets",
        default="",
        dest="compatible_feature_sets",
        help=(
            "Comma-separated feature-set ids to materialize into PSD matrices. "
            "Default keeps the built-in PSD-compatible feature sets."
        ),
    )
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument(
        "--skip-existing-versioned",
        nargs="?",
        const=True,
        default=False,
        type=_bool_arg,
    )
    parser.add_argument(
        "--force-overwrite",
        nargs="?",
        const=True,
        default=False,
        type=_bool_arg,
    )
    parser.add_argument("--dry-run", action="store_true", default=False)
    return parser.parse_args()


def main() -> None:
    load_env()
    args = _parse_args()
    target_definitions = []
    psd_targets = pd.DataFrame()
    psd_mapping_sha = None
    if args.target_source == "faostat":
        target_definitions, target_config_sha, target_config = load_target_definitions(
            args.target_config
        )
        if args.target_keys and args.target_keys.strip().lower() not in {"none", "null"}:
            allowed = {part.strip() for part in args.target_keys.split(",") if part.strip()}
            target_definitions = [
                definition for definition in target_definitions
                if definition.target_key in allowed
            ]
            missing = allowed - {definition.target_key for definition in target_definitions}
            if missing:
                raise SystemExit(f"unknown target keys: {sorted(missing)}")
        if not target_definitions:
            raise SystemExit("no target definitions selected")
        args.source_dataset_version = (
            args.source_dataset_version
            or default_source_dataset_version(target_config)
        )
    else:
        psd_config = load_psd_metric_targets(args.psd_target_config)
        target_config_sha = psd_config.config_sha
        target_config = psd_config.raw
        psd_mapping_sha = psd_config.config_sha
        requested_target_keys = (
            tuple(part.strip() for part in args.target_keys.split(",") if part.strip())
            if args.target_keys and args.target_keys.strip().lower() not in {"none", "null"}
            else ()
        )
        missing = set(requested_target_keys) - set(psd_config.metrics)
        if missing:
            raise SystemExit(f"unknown PSD target keys: {sorted(missing)}")
    if not args.source_dataset_version:
        raise SystemExit("--source-dataset-version is required")
    args.model_dataset_version = (
        args.model_dataset_version or _default_model_dataset_version()
    )
    args.workers = max(1, int(args.workers))
    args.compatible_feature_sets_tuple = _parse_csv_tuple(args.compatible_feature_sets)

    if not args.local_root:
        args.bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
        args.aws_region = args.aws_region or get_required_env("AWS_REGION")

    commodities = _parse_commodities(args.commodities)
    feature_membership = _read_parquet(
        args, gold_feature_set_version_key(args.source_dataset_version)
    )
    if args.target_source == "psd":
        psd_source = _read_parquet(args, args.psd_source_key)
        psd_targets = build_psd_target_panel(
            psd_source,
            source_dataset_version=args.source_dataset_version,
            config=psd_config,
            commodities=commodities,
        )
        if requested_target_keys:
            psd_targets = psd_targets.loc[
                psd_targets["target_key"].isin(set(requested_target_keys))
            ].copy()
    else:
        requested_target_keys = ()

    logger.info(
        (
            "Building model-ready datasets version=%s source=%s target_source=%s "
            "commodities=%d targets=%d workers=%d dry_run=%s"
        ),
        args.model_dataset_version,
        args.source_dataset_version,
        args.target_source,
        len(commodities),
        len(target_definitions) if args.target_source == "faostat" else (
            len(requested_target_keys) if requested_target_keys else len(psd_config.metrics)
        ),
        args.workers,
        args.dry_run,
    )

    results_by_commodity: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=min(args.workers, len(commodities))) as executor:
        future_to_commodity = {
            executor.submit(
                _process_commodity if args.target_source == "faostat" else _process_psd_commodity,
                args,
                commodity,
                target_definitions if args.target_source == "faostat" else psd_targets,
                feature_membership,
                *(() if args.target_source == "faostat" else (requested_target_keys,)),
            ): commodity
            for commodity in commodities
        }
        for future in as_completed(future_to_commodity):
            commodity = future_to_commodity[future]
            try:
                result = future.result()
                logger.info("%s: %s", commodity, result["status"])
                results_by_commodity[commodity] = result
            except Exception as exc:  # noqa: BLE001
                logger.exception("%s: model-ready build failed", commodity)
                results_by_commodity[commodity] = {
                    "commodity": commodity,
                    "status": "error",
                    "error": str(exc),
                    "summaries": [],
                    "target_outputs": [],
                    "matrix_outputs": [],
                }

    results = [results_by_commodity[c] for c in commodities]
    failed = [r for r in results if r["status"] == "error"]
    metrics_frames = [
        r["baseline_metrics"] for r in results
        if isinstance(r.get("baseline_metrics"), pd.DataFrame)
        and not r["baseline_metrics"].empty
    ]
    baseline_metrics = (
        pd.concat(metrics_frames, ignore_index=True)
        if metrics_frames else pd.DataFrame(
            columns=[
                "dataset_key",
                "commodity",
                "target_key",
                "baseline_name",
                "n_rows",
                "rmse",
                "mae",
                "directional_accuracy",
            ]
        )
    )
    manifest = _build_manifest(
        args,
        target_config_sha=target_config_sha,
        target_config=target_config,
        commodities=commodities,
        results=results,
        baseline_metrics=baseline_metrics,
        target_source=args.target_source,
        psd_mapping_sha=psd_mapping_sha,
    )

    if not args.dry_run:
        baseline_key = gold_model_ready_baseline_metrics_key(args.model_dataset_version)
        _write_bytes(
            args,
            baseline_key,
            _parquet_bytes(baseline_metrics),
            "application/octet-stream",
        )
        manifest_key = gold_model_ready_manifest_key(args.model_dataset_version)
        _write_bytes(
            args,
            manifest_key,
            json.dumps(manifest, indent=2, default=str).encode("utf-8"),
            "application/json",
        )

    logger.info("Done summary=%s", manifest["summary"])
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
