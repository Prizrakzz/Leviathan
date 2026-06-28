"""Build Phase 8 model-ready datasets from immutable gold matrices."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
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
from leviathan.features.calendar import load_crop_calendars
from leviathan.features.feature_sets import FEATURE_SET_COLUMNS, selected_features_for_set
from leviathan.features.spine import load_countries
from leviathan.model_datasets.builder import build_commodity_model_datasets
from leviathan.model_datasets.psd_model_ready import (
    PRESEASON_PLUS_WASDE_REVISION_FEATURE_SET_ID,
    CORN_WASDE_COMPOSITE_FEATURE_SET_IDS,
    PSD_BALANCE_SHEET_SNAPSHOT_FEATURE_SET_ID,
    PSD_MONTHLY_VINTAGE_FEATURE_SET_ID,
    PSDModelReadyBuildConfig,
    PSD_MATRIX_ID_COLUMNS,
    PSD_PRESEASON_PLUS_SNAPSHOT_FEATURE_SET_ID,
    PSD_PRESEASON_PLUS_VINTAGE_FEATURE_SET_ID,
    PSD_SNAPSHOT_MATRIX_ID_COLUMNS,
    PSD_SNAPSHOT_STATIC_FEATURE_SETS,
    snapshot_feature_set_contract_notes,
    annual_model_ready_features_for_set,
    psd_vintage_feature_columns,
    validate_snapshot_feature_set_ids,
    wasde_snapshot_feature_columns,
    WASDE_MONTHLY_REVISION_FEATURE_SET_ID,
    build_psd_commodity_model_datasets,
    build_psd_commodity_snapshot_model_datasets,
)
from leviathan.model_datasets.psd_target_builder import build_psd_target_panel
from leviathan.model_datasets.psd_targets import load_psd_metric_targets
from leviathan.model_datasets.snapshot_stages import load_snapshot_stage_config
from leviathan.model_datasets.targets import (
    default_source_dataset_version,
    load_target_definitions,
)
from leviathan.storage.paths import (
    gold_feature_matrix_version_key,
    gold_feature_set_version_key,
    gold_model_ready_feature_set_summary_key,
    gold_model_ready_feature_set_version_key,
    gold_model_ready_baseline_metrics_key,
    gold_model_ready_manifest_key,
    gold_model_ready_matrix_key,
    gold_model_ready_target_key,
)
from leviathan.storage.s3 import get_thread_local_s3_client
from leviathan.training.feature_quality import (  # noqa: E402
    FeatureQualityPolicy,
    build_feature_quality_report,
    enforce_feature_quality,
)

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
    *PSD_SNAPSHOT_MATRIX_ID_COLUMNS,
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


def _parse_snapshot_stages(raw: str | None) -> tuple[tuple[str, ...], bool]:
    if raw is None:
        return (), False
    normalized = raw.strip()
    if not normalized or normalized.lower() in {"none", "null"}:
        return (), False
    if normalized.lower() in {"all", "default"}:
        return (), True
    return tuple(part.strip() for part in normalized.split(",") if part.strip()), True


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


def _read_parquet_prefix(args: argparse.Namespace, prefix: str) -> pd.DataFrame:
    """Read all parquet files under a local or S3 prefix."""
    normalized = prefix.strip("/")
    if args.local_root:
        root = Path(args.local_root)
        prefix_path = root / normalized
        if not prefix_path.exists():
            return pd.DataFrame()
        keys = sorted(
            path.relative_to(root).as_posix()
            for path in prefix_path.rglob("*.parquet")
            if path.is_file()
        )
    else:
        s3 = get_thread_local_s3_client(args.aws_region)
        keys: list[str] = []
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=args.bucket, Prefix=prefix.rstrip("/") + "/"):
            for obj in page.get("Contents", []):
                key = str(obj["Key"])
                if key.endswith(".parquet"):
                    keys.append(key)
        keys = sorted(keys)
    if not keys:
        return pd.DataFrame()

    frames: list[pd.DataFrame] = []
    with ThreadPoolExecutor(max_workers=min(max(1, int(args.workers)), len(keys))) as executor:
        futures = [executor.submit(_read_parquet, args, key) for key in keys]
        for future in as_completed(futures):
            frame = future.result()
            if not frame.empty:
                frames.append(frame)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


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


def _model_ready_feature_set_sha(
    model_dataset_version: str,
    feature_set_id: str,
    features: list[str],
) -> str:
    payload = {
        "model_dataset_version": model_dataset_version,
        "feature_set_id": feature_set_id,
        "feature_set_version": "1",
        "features": sorted(features),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _source_feature_metadata(feature_membership: pd.DataFrame) -> dict[str, dict]:
    if feature_membership.empty or "feature" not in feature_membership.columns:
        return {}
    metadata: dict[str, dict] = {}
    for row in feature_membership.drop_duplicates("feature").to_dict("records"):
        metadata[str(row["feature"])] = row
    return metadata


def _source_features_for_set(
    feature_membership: pd.DataFrame,
    feature_set_id: str,
    matrix_cols: set[str],
) -> list[str]:
    try:
        selected = selected_features_for_set(feature_membership, feature_set_id)
    except ValueError:
        return []
    return sorted(
        feature
        for feature in selected
        if feature in matrix_cols and not str(feature).startswith("label_")
    )


def _feature_observation(
    *,
    model_dataset_version: str,
    feature_set_id: str,
    feature: str,
    matrix_df: pd.DataFrame,
    source_meta: dict[str, dict],
    commodity: str,
) -> dict:
    meta = source_meta.get(feature, {})
    is_psd_snapshot = feature.startswith("psd_")
    is_wasde_revision = feature.startswith("wasde_")
    is_persistence = feature.startswith("persistence_")
    row_count = int(len(matrix_df))
    non_null_count = int(pd.to_numeric(matrix_df[feature], errors="coerce").notna().sum())
    return {
        "dataset_version": model_dataset_version,
        "feature_set_id": feature_set_id,
        "feature_set_version": "1",
        "feature_set_sha": "",
        "feature": feature,
        "feature_family": str(
            meta.get("feature_family")
            or (
                "psd_balance_sheet_snapshot"
                if is_psd_snapshot else (
                    "official_revisions"
                    if is_wasde_revision else (
                        "persistence_context"
                        if is_persistence else "model_ready_dynamic"
                    )
                )
            )
        ),
        "semantic_scope": str(
            meta.get("semantic_scope")
            or (
                "official_revision"
                if (is_psd_snapshot or is_wasde_revision) else (
                    "target_history_context"
                    if is_persistence else "model_ready_snapshot"
                )
            )
        ),
        "policy": str(
            meta.get("policy") or "fundamental_physical"
        ),
        "mechanism": str(
            meta.get("mechanism")
            or (
                "official_balance_sheet_snapshot_context"
                if is_psd_snapshot else (
                    "official_estimate_revision"
                    if is_wasde_revision else (
                        "prior_year_target_persistence"
                        if is_persistence else "snapshot_static_context"
                    )
                )
            )
        ),
        "sources": str(
            meta.get("sources")
            or (
                "psd"
                if is_psd_snapshot else (
                    "wasde" if is_wasde_revision else (
                        "model_ready_target_history" if is_persistence else ""
                    )
                )
            )
        ),
        "source_cadence": str(
            meta.get("source_cadence")
            or (
                "monthly"
                if (is_psd_snapshot or is_wasde_revision) else (
                    "annual" if is_persistence else ""
                )
            )
        ),
        "empirical_scope": str(meta.get("empirical_scope") or "commodity"),
        "groups": str(meta.get("groups") or ""),
        "is_label": False,
        "row_count": row_count,
        "commodity_count": 1,
        "non_null_count": non_null_count,
        "non_null_rate": float(non_null_count / row_count) if row_count else 0.0,
        "target_compatibility": (
            "psd_production_anomaly,psd_balance_sheet_anomaly,"
            "official_estimate_revision,finalization_gap"
        ),
        "missingness_policy": "tree_models_allow_nan",
        "min_lag_days": 365 if is_persistence else 0,
        "commodity": commodity,
    }


def _annual_feature_set_observations(
    *,
    args: argparse.Namespace,
    matrix_df: pd.DataFrame,
    feature_membership: pd.DataFrame,
    commodity: str,
) -> list[dict]:
    source_meta = _source_feature_metadata(feature_membership)
    requested = tuple(
        args.compatible_feature_sets_tuple
        or tuple(PSDModelReadyBuildConfig().compatible_feature_sets)
    )
    observations: list[dict] = []
    for feature_set_id in requested:
        selected = annual_model_ready_features_for_set(
            matrix_df, feature_membership, feature_set_id
        )
        for feature in selected:
            observations.append(
                _feature_observation(
                    model_dataset_version=args.model_dataset_version,
                    feature_set_id=feature_set_id,
                    feature=feature,
                    matrix_df=matrix_df,
                    source_meta=source_meta,
                    commodity=commodity,
                )
            )
    return observations


def _snapshot_feature_set_observations(
    *,
    args: argparse.Namespace,
    matrix_df: pd.DataFrame,
    feature_membership: pd.DataFrame,
    commodity: str,
) -> list[dict]:
    source_meta = _source_feature_metadata(feature_membership)
    matrix_cols = set(str(col) for col in matrix_df.columns)
    requested = tuple(
        args.compatible_feature_sets_tuple or (WASDE_MONTHLY_REVISION_FEATURE_SET_ID,)
    )
    psd_features = psd_vintage_feature_columns(matrix_df)
    wasde_features = wasde_snapshot_feature_columns(matrix_df)
    preseason_features = _source_features_for_set(
        feature_membership, "preseason_physical", matrix_cols
    )
    observations: list[dict] = []

    for feature_set_id in requested:
        selected = _snapshot_features_for_set(
            feature_set_id,
            matrix_df=matrix_df,
            feature_membership=feature_membership,
        )
        for feature in selected:
            observations.append(
                _feature_observation(
                    model_dataset_version=args.model_dataset_version,
                    feature_set_id=feature_set_id,
                    feature=feature,
                    matrix_df=matrix_df,
                    source_meta=source_meta,
                    commodity=commodity,
                )
            )
    return observations


def _snapshot_features_for_set(
    feature_set_id: str,
    *,
    matrix_df: pd.DataFrame,
    feature_membership: pd.DataFrame,
) -> list[str]:
    matrix_cols = set(str(col) for col in matrix_df.columns)
    psd_features = psd_vintage_feature_columns(matrix_df)
    wasde_features = wasde_snapshot_feature_columns(matrix_df)
    preseason_features = _source_features_for_set(
        feature_membership, "preseason_physical", matrix_cols
    )
    if feature_set_id in {
        PSD_MONTHLY_VINTAGE_FEATURE_SET_ID,
        PSD_BALANCE_SHEET_SNAPSHOT_FEATURE_SET_ID,
    }:
        return psd_features
    if feature_set_id in {
        PSD_PRESEASON_PLUS_VINTAGE_FEATURE_SET_ID,
        PSD_PRESEASON_PLUS_SNAPSHOT_FEATURE_SET_ID,
    }:
        return sorted(set(psd_features) | set(preseason_features))
    if feature_set_id == WASDE_MONTHLY_REVISION_FEATURE_SET_ID:
        return wasde_features
    if feature_set_id == PRESEASON_PLUS_WASDE_REVISION_FEATURE_SET_ID:
        return sorted(set(wasde_features) | set(preseason_features))
    if feature_set_id in CORN_WASDE_COMPOSITE_FEATURE_SET_IDS:
        static_features = _source_features_for_set(feature_membership, feature_set_id, matrix_cols)
        return sorted(set(wasde_features) | set(static_features))
    return _source_features_for_set(feature_membership, feature_set_id, matrix_cols)


def _build_model_ready_feature_sets(
    args: argparse.Namespace,
    results: list[dict],
) -> tuple[pd.DataFrame, dict]:
    observations = [
        observation
        for result in results
        for observation in result.get("model_ready_feature_observations", [])
    ]
    if not observations:
        return pd.DataFrame(columns=FEATURE_SET_COLUMNS), {}

    raw = pd.DataFrame(observations)
    rows: list[dict] = []
    for (feature_set_id, feature), group in raw.groupby(["feature_set_id", "feature"], sort=True):
        first = group.iloc[0].to_dict()
        total_rows = int(group["row_count"].sum())
        non_null_count = int(group["non_null_count"].sum())
        out = {column: first.get(column) for column in FEATURE_SET_COLUMNS}
        out["dataset_version"] = args.model_dataset_version
        out["feature_set_id"] = str(feature_set_id)
        out["feature_set_version"] = "1"
        out["feature"] = str(feature)
        out["row_count"] = total_rows
        out["commodity_count"] = int(group["commodity"].nunique())
        out["non_null_rate"] = float(non_null_count / total_rows) if total_rows else 0.0
        rows.append(out)

    membership = pd.DataFrame(rows)
    for feature_set_id, group in membership.groupby("feature_set_id"):
        features = sorted(group["feature"].astype(str).unique())
        feature_set_sha = _model_ready_feature_set_sha(
            args.model_dataset_version, str(feature_set_id), features
        )
        membership.loc[
            membership["feature_set_id"] == feature_set_id, "feature_set_sha"
        ] = feature_set_sha

    membership = membership[FEATURE_SET_COLUMNS].sort_values(
        ["feature_set_id", "feature"]
    ).reset_index(drop=True)
    summary = {
        "dataset_version": args.model_dataset_version,
        "feature_set_count": int(membership["feature_set_id"].nunique()),
        "selected_row_count": int(len(membership)),
        "feature_count_by_set": {
            str(feature_set_id): int(group["feature"].nunique())
            for feature_set_id, group in membership.groupby("feature_set_id", sort=True)
        },
        "feature_set_shas": {
            str(feature_set_id): str(group["feature_set_sha"].iloc[0])
            for feature_set_id, group in membership.groupby("feature_set_id", sort=True)
        },
    }
    return membership, summary


def _feature_quality_policy(args: argparse.Namespace) -> FeatureQualityPolicy:
    mode = str(args.feature_quality_policy or "").strip().lower()
    if not mode:
        mode = "strict" if getattr(args, "snapshot_mode", False) else "warn"
    if mode not in {"strict", "warn"}:
        raise ValueError("--feature-quality-policy must be 'strict' or 'warn'")
    return FeatureQualityPolicy(mode=mode)


def _append_feature_quality_report(
    result: dict,
    *,
    args: argparse.Namespace,
    matrix_df: pd.DataFrame,
    feature_membership: pd.DataFrame,
    dataset_key: str,
    target_key: str,
    commodity: str,
    feature_set_id: str,
    feature_cols: list[str],
    selected_feature_sets: tuple[str, ...] | None = None,
) -> None:
    report = build_feature_quality_report(
        matrix_df,
        feature_cols,
        membership=feature_membership,
        dataset_key=dataset_key,
        feature_set_id=feature_set_id,
        selected_feature_sets=selected_feature_sets or (feature_set_id,),
        policy=_feature_quality_policy(args),
    )
    report["commodity"] = commodity
    report["target_key"] = target_key
    enforce_feature_quality(report)
    result.setdefault("feature_quality_reports", []).append(report)


def _model_ready_feature_columns(matrix_df: pd.DataFrame) -> list[str]:
    return sorted(
        str(col)
        for col in matrix_df.columns
        if str(col) not in MODEL_READY_NON_FEATURE_COLUMNS
    )


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
    feature_sets_by_target = {
        (str(summary.get("dataset_key")), str(summary.get("target_key"))): tuple(
            str(item) for item in summary.get("compatible_feature_sets", [])
        )
        for summary in built.summaries
        if summary.get("status") == "built"
    }
    for (dataset_key, target_key), matrix_df in built.matrices.items():
        selected_sets = feature_sets_by_target.get((str(dataset_key), str(target_key)), ())
        _append_feature_quality_report(
            result,
            args=args,
            matrix_df=matrix_df,
            feature_membership=feature_membership,
            dataset_key=dataset_key,
            target_key=str(target_key),
            commodity=commodity,
            feature_set_id="compatible_feature_sets",
            feature_cols=_model_ready_feature_columns(matrix_df),
            selected_feature_sets=selected_sets,
        )
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
        "model_ready_feature_observations": [],
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
    selected_sets = args.compatible_feature_sets_tuple or tuple(
        PSDModelReadyBuildConfig().compatible_feature_sets
    )
    for (dataset_key, target_key), matrix_df in built.matrices.items():
        _append_feature_quality_report(
            result,
            args=args,
            matrix_df=matrix_df,
            feature_membership=feature_membership,
            dataset_key=dataset_key,
            target_key=str(target_key),
            commodity=commodity,
            feature_set_id="compatible_feature_sets",
            feature_cols=_model_ready_feature_columns(matrix_df),
            selected_feature_sets=selected_sets,
        )
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
        result["model_ready_feature_observations"].extend(
            _annual_feature_set_observations(
                args=args,
                matrix_df=matrix_df,
                feature_membership=feature_membership,
                commodity=commodity,
            )
        )

    result["baseline_metrics"] = built.baseline_metrics
    result["status"] = "written"
    return result


def _process_psd_snapshot_commodity(
    args: argparse.Namespace,
    commodity: str,
    psd_source: pd.DataFrame,
    psd_targets: pd.DataFrame,
    wasde_source: pd.DataFrame | None,
    feature_membership: pd.DataFrame,
    target_keys: tuple[str, ...],
) -> dict:
    result = {
        "commodity": commodity,
        "status": "unknown",
        "matrix_key": args.psd_source_key,
        "target_outputs": [],
        "matrix_outputs": [],
        "summaries": [],
        "model_ready_feature_observations": [],
    }
    calendar = args.crop_calendars.get(commodity)
    if calendar is None:
        result["status"] = "skipped_missing_crop_calendar"
        return result

    static_feature_matrix = None
    if any(
        feature_set_id in PSD_SNAPSHOT_STATIC_FEATURE_SETS
        for feature_set_id in args.compatible_feature_sets_tuple
    ):
        static_feature_matrix = _read_parquet(
            args,
            gold_feature_matrix_version_key(args.source_dataset_version, commodity),
        )

    built = build_psd_commodity_snapshot_model_datasets(
        psd_source,
        psd_targets,
        commodity=commodity,
        feature_membership=feature_membership,
        calendar=calendar,
        snapshot_config=args.snapshot_config_obj,
        snapshot_stage_ids=args.snapshot_stage_ids,
        as_of_date=args.as_of_date,
        include_named_stages=args.include_named_snapshot_stages,
        static_feature_matrix=static_feature_matrix,
        wasde_source=wasde_source,
        config=(
            PSDModelReadyBuildConfig(
                compatible_feature_sets=args.compatible_feature_sets_tuple
            )
            if args.compatible_feature_sets_tuple else None
        ),
        target_keys=target_keys,
    )
    result["summaries"] = built.summaries
    for (dataset_key, target_key), matrix_df in built.matrices.items():
        for feature_set_id in args.compatible_feature_sets_tuple:
            feature_cols = _snapshot_features_for_set(
                feature_set_id,
                matrix_df=matrix_df,
                feature_membership=feature_membership,
            )
            _append_feature_quality_report(
                result,
                args=args,
                matrix_df=matrix_df,
                feature_membership=feature_membership,
                dataset_key=dataset_key,
                target_key=str(target_key),
                commodity=commodity,
                feature_set_id=feature_set_id,
                feature_cols=feature_cols,
                selected_feature_sets=(feature_set_id,),
            )
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
        result["model_ready_feature_observations"].extend(
            _snapshot_feature_set_observations(
                args=args,
                matrix_df=matrix_df,
                feature_membership=feature_membership,
                commodity=commodity,
            )
        )

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
    model_ready_feature_set_summary: dict | None = None,
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
    feature_quality_reports = [
        report
        for result in results
        for report in result.get("feature_quality_reports", [])
    ]
    feature_quality_status_counts: dict[str, int] = {}
    for report in feature_quality_reports:
        status = str(report.get("status", "unknown"))
        feature_quality_status_counts[status] = (
            feature_quality_status_counts.get(status, 0) + 1
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
            "feature_quality_report_count": int(len(feature_quality_reports)),
            "feature_quality_status_counts": feature_quality_status_counts,
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
        "feature_quality": {
            "report_count": int(len(feature_quality_reports)),
            "status_counts": feature_quality_status_counts,
            "reports": feature_quality_reports,
        },
    }
    if model_ready_feature_set_summary:
        feature_sets_key = gold_model_ready_feature_set_version_key(args.model_dataset_version)
        feature_sets_json_key = gold_model_ready_feature_set_summary_key(
            args.model_dataset_version
        )
        manifest["outputs"].update({
            "model_ready_feature_sets_key": feature_sets_key,
            "model_ready_feature_sets_json_key": feature_sets_json_key,
        })
        manifest["model_ready_feature_sets"] = {
            "task": "build_model_ready_datasets",
            "key": feature_sets_key,
            "summary_key": feature_sets_json_key,
            "summary": model_ready_feature_set_summary,
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
    if getattr(args, "snapshot_mode", False):
        manifest["snapshot_mode"] = True
        manifest["snapshot_config"] = (
            args.snapshot_config or "configs/ml/snapshot_stages.yaml"
        )
        manifest["snapshot_config_sha"] = args.snapshot_config_obj.config_sha
        manifest["snapshot_policy"] = args.snapshot_config_obj.snapshot_policy
        manifest["snapshot_dataset_key"] = args.snapshot_config_obj.default_dataset_key
        manifest["snapshot_stages"] = (
            list(args.snapshot_stage_ids)
            if args.snapshot_stage_ids else (
                "all_named"
                if args.include_named_snapshot_stages else "explicit_as_of_only"
            )
        )
        manifest["explicit_as_of_date"] = args.as_of_date
        manifest["snapshot_feature_set_contracts"] = snapshot_feature_set_contract_notes(
            args.compatible_feature_sets_tuple
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
    parser.add_argument(
        "--wasde-source-prefix",
        default="silver/wasde/",
        dest="wasde_source_prefix",
        help="Parquet prefix for WASDE silver rows used by snapshot revision features.",
    )
    parser.add_argument("--psd-target-config", default=None, dest="psd_target_config")
    parser.add_argument("--snapshot-config", default=None, dest="snapshot_config")
    parser.add_argument("--commodities", default="all")
    parser.add_argument("--target-keys", default="", dest="target_keys")
    parser.add_argument(
        "--snapshot-mode",
        nargs="?",
        const=True,
        default=False,
        type=_bool_arg,
        dest="snapshot_mode",
        help=(
            "Build additive snapshot-stage PSD matrices instead of annual PSD "
            "matrices. Uses all configured stages unless --snapshot-stages or "
            "--as-of-date narrows the request."
        ),
    )
    parser.add_argument(
        "--snapshot-stages",
        default="",
        dest="snapshot_stages",
        help="Comma-separated named snapshot stages, 'all', or blank.",
    )
    parser.add_argument(
        "--as-of-date",
        default=None,
        dest="as_of_date",
        help="Optional explicit as-of date for PSD snapshot matrices.",
    )
    parser.add_argument(
        "--compatible-feature-sets",
        default="",
        dest="compatible_feature_sets",
        help=(
            "Comma-separated feature-set ids to materialize into PSD matrices. "
            "Default keeps the built-in PSD-compatible feature sets."
        ),
    )
    parser.add_argument(
        "--feature-quality-policy",
        default="",
        dest="feature_quality_policy",
        help=(
            "Feature quality gate mode: 'strict' or 'warn'. "
            "Default is strict for snapshot builds and warn otherwise."
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
    psd_source = pd.DataFrame()
    wasde_source: pd.DataFrame | None = None
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
    args.snapshot_stage_ids, requested_named_stages = _parse_snapshot_stages(
        args.snapshot_stages
    )
    requested_snapshot_mode = bool(args.snapshot_mode)
    args.as_of_date = (
        None
        if args.as_of_date is None or str(args.as_of_date).strip().lower() in {"", "none", "null"}
        else str(args.as_of_date).strip()
    )
    args.snapshot_mode = bool(
        requested_snapshot_mode or requested_named_stages or args.as_of_date
    )
    args.include_named_snapshot_stages = bool(
        requested_snapshot_mode or requested_named_stages
    )
    if args.snapshot_mode and args.target_source != "psd":
        raise SystemExit("--snapshot-mode/--snapshot-stages/--as-of-date require --target-source psd")
    if args.snapshot_mode:
        args.snapshot_config_obj = load_snapshot_stage_config(args.snapshot_config)
        args.crop_calendars = load_crop_calendars()
        if not args.compatible_feature_sets_tuple:
            args.compatible_feature_sets_tuple = (WASDE_MONTHLY_REVISION_FEATURE_SET_ID,)
        args.compatible_feature_sets_tuple = validate_snapshot_feature_set_ids(
            args.compatible_feature_sets_tuple
        )
    else:
        args.snapshot_config_obj = None
        args.crop_calendars = {}

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
        if args.snapshot_mode and any(
            feature_set_id in {
                WASDE_MONTHLY_REVISION_FEATURE_SET_ID,
                PRESEASON_PLUS_WASDE_REVISION_FEATURE_SET_ID,
                "official_revision",
            }
            for feature_set_id in args.compatible_feature_sets_tuple
        ):
            logger.info("Loading WASDE silver prefix %s", args.wasde_source_prefix)
            wasde_source = _read_parquet_prefix(args, args.wasde_source_prefix)
            logger.info("Loaded WASDE rows=%d", len(wasde_source))
    else:
        requested_target_keys = ()

    logger.info(
        (
            "Building model-ready datasets version=%s source=%s target_source=%s "
            "commodities=%d targets=%d workers=%d snapshot_mode=%s dry_run=%s"
        ),
        args.model_dataset_version,
        args.source_dataset_version,
        args.target_source,
        len(commodities),
        len(target_definitions) if args.target_source == "faostat" else (
            len(requested_target_keys) if requested_target_keys else len(psd_config.metrics)
        ),
        args.workers,
        args.snapshot_mode,
        args.dry_run,
    )

    results_by_commodity: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=min(args.workers, len(commodities))) as executor:
        future_to_commodity = {}
        for commodity in commodities:
            if args.target_source == "faostat":
                future = executor.submit(
                    _process_commodity,
                    args,
                    commodity,
                    target_definitions,
                    feature_membership,
                )
            elif args.snapshot_mode:
                future = executor.submit(
                    _process_psd_snapshot_commodity,
                    args,
                    commodity,
                    psd_source,
                    psd_targets,
                    wasde_source,
                    feature_membership,
                    requested_target_keys,
                )
            else:
                future = executor.submit(
                    _process_psd_commodity,
                    args,
                    commodity,
                    psd_targets,
                    feature_membership,
                    requested_target_keys,
                )
            future_to_commodity[future] = commodity
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
    model_ready_feature_sets, model_ready_feature_set_summary = _build_model_ready_feature_sets(
        args, results
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
        model_ready_feature_set_summary=(
            model_ready_feature_set_summary
            if not model_ready_feature_sets.empty else None
        ),
    )

    if not args.dry_run:
        if not model_ready_feature_sets.empty:
            feature_sets_key = gold_model_ready_feature_set_version_key(
                args.model_dataset_version
            )
            _write_bytes(
                args,
                feature_sets_key,
                _parquet_bytes(model_ready_feature_sets),
                "application/octet-stream",
            )
            feature_sets_json_key = gold_model_ready_feature_set_summary_key(
                args.model_dataset_version
            )
            _write_bytes(
                args,
                feature_sets_json_key,
                json.dumps(model_ready_feature_set_summary, indent=2, default=str).encode("utf-8"),
                "application/json",
            )
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
