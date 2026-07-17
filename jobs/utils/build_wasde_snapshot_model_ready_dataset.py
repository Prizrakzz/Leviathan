"""Build immutable WASDE release-date snapshot model-ready datasets."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
from typing import Iterable

import boto3
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from leviathan.common.config import load_env  # noqa: E402
from leviathan.features.feature_sets import FEATURE_SET_COLUMNS  # noqa: E402
from leviathan.model_datasets.baselines import compute_baseline_metrics  # noqa: E402
from leviathan.model_datasets.wasde_snapshot_diagnostics import (  # noqa: E402
    build_baseline_diagnostics,
    diagnose_wasde_snapshot_matrix,
)
from leviathan.model_datasets.wasde_snapshot_features import (  # noqa: E402
    DEFAULT_ATTRIBUTES,
    build_wasde_feature_quality_report,
)
from leviathan.model_datasets.wasde_snapshot_mapping import (  # noqa: E402
    load_wasde_snapshot_mappings,
    normalize_wasde_token,
)
from leviathan.model_datasets.wasde_snapshot_model_ready import (  # noqa: E402
    WasdeSnapshotModelReadyResult,
    build_wasde_snapshot_model_ready_matrix,
)
from leviathan.storage.paths import (  # noqa: E402
    gold_model_ready_baseline_metrics_key,
    gold_model_ready_feature_set_summary_key,
    gold_model_ready_feature_set_version_key,
    gold_model_ready_manifest_key,
    gold_model_ready_matrix_key,
    gold_model_ready_target_key,
)

DEFAULT_BUCKET = "leviathan-dev-shahem-001"
DEFAULT_REGION = "us-east-1"
DEFAULT_SOURCE_DATASET_VERSION = "20260626T010217Z_6725de02_phase7_full"
DEFAULT_MODEL_DATASET_SUFFIX = "phase3_wasde_snapshot_model_ready"
DEFAULT_PSD_KEY = "silver/psd/part-000.parquet"
DEFAULT_WASDE_PREFIX = "silver/wasde/"
DEFAULT_DATASET_KEY = "corn_wasde_snapshot_solo"
DEFAULT_COMMODITY = "corn_cbot"
DEFAULT_TARGET_KEYS = "psd_stock_to_use_anomaly_pct,psd_ending_stocks_anomaly_pct"
DEFAULT_FEATURE_SET_IDS = "wasde_monthly_revision"
DEFAULT_PHASE2_DENSITY_PREFIX = (
    "model_artifacts/wasde_snapshot_feature_density/"
    "dataset_version=20260629T115343Z_phase2_wasde_feature_density"
)
BASELINE_NAMES = ("zero_anomaly", "prior_year", "trailing_mean", "trailing_linear_trend")


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL, text=True
        ).strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def _default_model_dataset_version() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    sha = _git_sha()
    suffix = sha[:8] if sha and sha != "unknown" else "unknown"
    return f"{stamp}_{suffix}_{DEFAULT_MODEL_DATASET_SUFFIX}"


def _parse_csv(raw: str | None) -> tuple[str, ...]:
    if raw is None:
        return ()
    normalized = str(raw).strip()
    if not normalized or normalized.lower() in {"none", "null", "default"}:
        return ()
    return tuple(part.strip() for part in normalized.split(",") if part.strip())


def _bool_arg(value: bool | str) -> bool:
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "t", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "f", "no", "n", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"expected boolean value, got {value!r}")


def _list_parquet_keys(s3, bucket: str, prefix: str) -> list[str]:
    keys: list[str] = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix.rstrip("/") + "/"):
        keys.extend(
            str(obj["Key"])
            for obj in page.get("Contents", [])
            if str(obj["Key"]).endswith(".parquet")
        )
    return sorted(keys)


def _read_parquet_key(s3, bucket: str, key: str, columns: list[str] | None = None) -> pd.DataFrame:
    body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
    return pd.read_parquet(io.BytesIO(body), columns=columns)


def _read_json_key(s3, bucket: str, key: str) -> dict:
    body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
    return json.loads(body.decode("utf-8"))


def _read_parquet_prefix(
    s3,
    bucket: str,
    prefix: str,
    *,
    columns: list[str] | None,
    workers: int,
) -> pd.DataFrame:
    keys = _list_parquet_keys(s3, bucket, prefix)
    if not keys:
        return pd.DataFrame()
    frames: list[pd.DataFrame] = []
    failures: list[str] = []
    with ThreadPoolExecutor(max_workers=min(max(1, int(workers)), len(keys))) as pool:
        futures = {pool.submit(_read_parquet_key, s3, bucket, key, columns): key for key in keys}
        for future in as_completed(futures):
            key = futures[future]
            try:
                frame = future.result()
                if not frame.empty:
                    frames.append(frame)
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{key}: {exc}")
    if failures:
        raise RuntimeError("failed to read parquet prefix: " + "; ".join(failures[:5]))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _parquet_bytes(frame: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    frame.to_parquet(buf, index=False, compression="snappy", engine="pyarrow")
    return buf.getvalue()


def _object_exists(s3, bucket: str, key: str) -> bool:
    try:
        s3.head_object(Bucket=bucket, Key=key)
        return True
    except Exception as exc:  # noqa: BLE001
        code = str(getattr(exc, "response", {}).get("Error", {}).get("Code", ""))
        if code in {"404", "NoSuchKey", "NotFound"}:
            return False
        raise


def _put_bytes(
    s3,
    *,
    bucket: str,
    key: str,
    body: bytes,
    content_type: str,
    skip_existing_versioned: bool,
) -> str:
    if _object_exists(s3, bucket, key):
        if skip_existing_versioned:
            return "skipped_existing"
        raise FileExistsError(f"refusing to overwrite immutable object: {key}")
    s3.put_object(Bucket=bucket, Key=key, Body=body, ContentType=content_type)
    return "written"


def _put_parquet(
    s3,
    *,
    bucket: str,
    key: str,
    frame: pd.DataFrame,
    skip_existing_versioned: bool,
) -> str:
    return _put_bytes(
        s3,
        bucket=bucket,
        key=key,
        body=_parquet_bytes(frame),
        content_type="application/octet-stream",
        skip_existing_versioned=skip_existing_versioned,
    )


def _put_json(
    s3,
    *,
    bucket: str,
    key: str,
    payload: dict,
    skip_existing_versioned: bool,
) -> str:
    return _put_bytes(
        s3,
        bucket=bucket,
        key=key,
        body=json.dumps(payload, indent=2, sort_keys=True, default=str).encode("utf-8"),
        content_type="application/json",
        skip_existing_versioned=skip_existing_versioned,
    )


def _feature_set_sha(
    *,
    model_dataset_version: str,
    feature_set_id: str,
    features: Iterable[str],
) -> str:
    payload = {
        "model_dataset_version": model_dataset_version,
        "feature_set_id": feature_set_id,
        "feature_set_version": "1",
        "features": sorted(str(feature) for feature in features),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _selected_dynamic_features(
    matrix: pd.DataFrame,
    features: Iterable[str],
    *,
    min_non_null_rate: float,
) -> tuple[str, ...]:
    selected: list[str] = []
    for feature in features:
        if feature not in matrix.columns:
            continue
        non_null_rate = float(matrix[feature].notna().mean()) if len(matrix) else 0.0
        if non_null_rate <= 0.0:
            continue
        selected.append(str(feature))
    if not selected:
        raise ValueError("WASDE snapshot matrix produced zero non-empty dynamic features")
    dense = [
        feature
        for feature in selected
        if float(matrix[feature].notna().mean()) >= float(min_non_null_rate)
        and int(matrix[feature].dropna().nunique()) > 1
    ]
    return tuple(sorted(dense or selected))


def build_model_ready_feature_membership(
    *,
    model_dataset_version: str,
    feature_set_ids: tuple[str, ...],
    feature_columns: tuple[str, ...],
    matrix: pd.DataFrame,
) -> tuple[pd.DataFrame, dict]:
    """Build model-ready feature-set rows for WASDE dynamic columns."""
    rows: list[dict[str, object]] = []
    row_count = int(len(matrix))
    for feature_set_id in feature_set_ids:
        sha = _feature_set_sha(
            model_dataset_version=model_dataset_version,
            feature_set_id=feature_set_id,
            features=feature_columns,
        )
        for feature in feature_columns:
            non_null_count = int(matrix[feature].notna().sum()) if feature in matrix.columns else 0
            rows.append({
                "dataset_version": model_dataset_version,
                "feature_set_id": feature_set_id,
                "feature_set_version": "1",
                "feature_set_sha": sha,
                "feature": feature,
                "feature_family": "official_revisions",
                "semantic_scope": "official_revision",
                "policy": "fundamental_physical",
                "mechanism": "official_estimate_revision",
                "sources": "wasde",
                "source_cadence": "monthly",
                "empirical_scope": "commodity",
                "groups": "grains",
                "is_label": False,
                "row_count": row_count,
                "commodity_count": 1,
                "non_null_rate": float(non_null_count / row_count) if row_count else 0.0,
                "target_compatibility": "psd_balance_sheet_anomaly,official_estimate_revision",
                "missingness_policy": "tree_models_allow_nan",
                "min_lag_days": 0,
            })
    membership = pd.DataFrame(rows, columns=FEATURE_SET_COLUMNS).sort_values(
        ["feature_set_id", "feature"]
    ).reset_index(drop=True)
    summary = {
        "dataset_version": model_dataset_version,
        "feature_set_count": int(membership["feature_set_id"].nunique()) if not membership.empty else 0,
        "selected_row_count": int(len(membership)),
        "feature_count_by_set": {
            str(feature_set_id): int(group["feature"].nunique())
            for feature_set_id, group in membership.groupby("feature_set_id", sort=True)
        } if not membership.empty else {},
        "feature_set_shas": {
            str(feature_set_id): str(group["feature_set_sha"].iloc[0])
            for feature_set_id, group in membership.groupby("feature_set_id", sort=True)
        } if not membership.empty else {},
    }
    return membership, summary


def _with_training_aliases(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    if "country" not in out.columns and "origin_key" in out.columns:
        out["country"] = out["origin_key"]
    if "crop_year" not in out.columns and "target_market_year" in out.columns:
        out["crop_year"] = out["target_market_year"]
    return out


def _target_matrix_outputs(matrix: pd.DataFrame) -> dict[str, pd.DataFrame]:
    outputs: dict[str, pd.DataFrame] = {}
    for target_key, group in matrix.groupby("target_key", sort=True):
        outputs[str(target_key)] = _with_training_aliases(group).reset_index(drop=True)
    return outputs


def _baseline_metrics(matrix_by_target: dict[str, pd.DataFrame], dataset_key: str, commodity: str) -> pd.DataFrame:
    frames = [
        compute_baseline_metrics(
            matrix,
            dataset_key=dataset_key,
            commodity=commodity,
            target_key=target_key,
            baseline_names=BASELINE_NAMES,
        )
        for target_key, matrix in matrix_by_target.items()
    ]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _safe_records(frame: pd.DataFrame) -> list[dict]:
    if frame.empty:
        return []
    return json.loads(frame.to_json(orient="records", date_format="iso"))


def _phase2_density_summary(s3, *, bucket: str, prefix: str) -> dict:
    if not prefix:
        return {}
    key = f"{prefix.strip('/')}/feature_density_summary.json"
    try:
        return _read_json_key(s3, bucket, key)
    except Exception as exc:  # noqa: BLE001
        return {"status": "missing_or_unreadable", "key": key, "error": str(exc)}


def _filter_wasde_for_surface(
    wasde_df: pd.DataFrame,
    *,
    dataset_key: str,
) -> pd.DataFrame:
    """Limit WASDE rows to commodity/origin pairs allowed by the snapshot surface."""
    cfg = load_wasde_snapshot_mappings()
    surface = cfg.surfaces[dataset_key]
    allowed_pairs: set[tuple[str, str]] = set()
    for origin in surface.target_origins:
        allowed_pairs.add((surface.primary_wasde_commodity, origin.origin_key))
        for alias in origin.wasde_region_aliases:
            allowed_pairs.add((surface.primary_wasde_commodity, cfg.region_aliases.get(alias, alias)))
    for context in surface.context_commodities:
        for origin in context.origins:
            allowed_pairs.add((context.wasde_commodity, origin))
    for member in surface.active_segment_members:
        for origin in member.origins:
            allowed_pairs.add((member.wasde_commodity, origin))

    source = wasde_df.copy()
    commodity = source["commodity"].map(normalize_wasde_token)
    region = source["region"].map(normalize_wasde_token)
    origin = region.map(lambda value: cfg.region_aliases.get(value, value))
    mask = [
        (str(comm), str(org)) in allowed_pairs
        for comm, org in zip(commodity, origin, strict=False)
    ]
    return source.loc[mask].copy()


def build_manifest(
    *,
    args: argparse.Namespace,
    result: WasdeSnapshotModelReadyResult,
    selected_features: tuple[str, ...],
    feature_set_summary: dict,
    baseline_metrics: pd.DataFrame,
    diagnostics: dict[str, dict],
    phase2_density_summary: dict,
    output_records: dict,
) -> dict:
    stock_quality = result.summary.copy()
    dynamic_quality = build_wasde_feature_quality_report(result.dynamic_features)
    stock_rows = dynamic_quality.loc[
        dynamic_quality["feature"].astype(str).str.startswith("wasde_stock_to_use_")
    ]
    stock_note = {
        "stock_to_use_feature_count": int(len(stock_rows)),
        "stock_to_use_max_non_null_rate": (
            float(stock_rows["non_null_rate"].max()) if not stock_rows.empty else None
        ),
        "warning": (
            "stock/use features are near-threshold and should be treated as secondary "
            "until feature diagnostics prove they help"
        ),
    }
    return {
        "task": "build_wasde_snapshot_model_ready_dataset",
        "dataset_kind": "gold_model_ready_dataset_version",
        "snapshot_mode": True,
        "snapshot_policy": "wasde_release_month_v1",
        "release_date_snapshot_mode": True,
        "model_dataset_version": args.model_dataset_version,
        "source_dataset_version": args.source_dataset_version,
        "dataset_key": args.dataset_key,
        "commodity": args.commodity,
        "target_keys": list(args.target_keys_tuple),
        "feature_set_ids": list(args.feature_set_ids_tuple),
        "built_at": datetime.now(timezone.utc).isoformat(),
        "git_sha": _git_sha(),
        "inputs": {
            "psd_source_key": args.psd_source_key,
            "wasde_source_prefix": args.wasde_source_prefix,
            "phase2_density_prefix": args.phase2_density_prefix,
            "phase2_density_summary": phase2_density_summary,
        },
        "summary": {
            **result.summary,
            "selected_feature_count": int(len(selected_features)),
            "baseline_metric_count": int(len(baseline_metrics)),
            "stock_to_use_coverage": stock_note,
        },
        "outputs": output_records,
        "model_ready_feature_sets": feature_set_summary,
        "diagnostics": diagnostics,
        "dynamic_feature_quality_top": _safe_records(
            dynamic_quality.sort_values(
                ["non_null_rate", "constant_rate", "feature"],
                ascending=[False, True, True],
            ).head(30)
        ),
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bucket", default=DEFAULT_BUCKET)
    parser.add_argument("--aws-region", default=DEFAULT_REGION, dest="aws_region")
    parser.add_argument("--source-dataset-version", default=DEFAULT_SOURCE_DATASET_VERSION, dest="source_dataset_version")
    parser.add_argument("--model-dataset-version", default="", dest="model_dataset_version")
    parser.add_argument("--psd-source-key", default=DEFAULT_PSD_KEY, dest="psd_source_key")
    parser.add_argument("--wasde-source-prefix", default=DEFAULT_WASDE_PREFIX, dest="wasde_source_prefix")
    parser.add_argument("--dataset-key", default=DEFAULT_DATASET_KEY, dest="dataset_key")
    parser.add_argument("--commodity", default=DEFAULT_COMMODITY)
    parser.add_argument("--target-keys", default=DEFAULT_TARGET_KEYS, dest="target_keys")
    parser.add_argument("--feature-set-ids", default=DEFAULT_FEATURE_SET_IDS, dest="feature_set_ids")
    parser.add_argument("--phase2-density-prefix", default=DEFAULT_PHASE2_DENSITY_PREFIX, dest="phase2_density_prefix")
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--min-history-years", type=int, default=5, dest="min_history_years")
    parser.add_argument("--min-non-null-rate", type=float, default=0.5, dest="min_non_null_rate")
    parser.add_argument("--dry-run", action="store_true", default=False)
    parser.add_argument(
        "--skip-existing-versioned",
        nargs="?",
        const=True,
        default=False,
        type=_bool_arg,
        dest="skip_existing_versioned",
    )
    return parser.parse_args()


def main() -> None:
    load_env()
    args = _parse_args()
    args.workers = max(1, int(args.workers))
    args.model_dataset_version = args.model_dataset_version or _default_model_dataset_version()
    args.target_keys_tuple = _parse_csv(args.target_keys)
    args.feature_set_ids_tuple = _parse_csv(args.feature_set_ids) or ("wasde_monthly_revision",)
    if not args.target_keys_tuple:
        raise SystemExit("--target-keys must select at least one target")
    if not 0.0 <= float(args.min_non_null_rate) <= 1.0:
        raise SystemExit("--min-non-null-rate must be between 0 and 1")

    s3 = boto3.client("s3", region_name=args.aws_region)
    phase2_summary = _phase2_density_summary(
        s3,
        bucket=args.bucket,
        prefix=args.phase2_density_prefix,
    )
    if phase2_summary and phase2_summary.get("usable_feature_count") == 0:
        raise SystemExit("Phase 2 density summary reports zero usable features; refusing to build")

    psd = _read_parquet_key(s3, args.bucket, args.psd_source_key)
    wasde = _read_parquet_prefix(
        s3,
        args.bucket,
        args.wasde_source_prefix,
        workers=args.workers,
        columns=[
            "release_date",
            "commodity",
            "table_type",
            "region",
            "marketing_year",
            "attribute",
            "estimate",
            "revision",
        ],
    )
    if wasde.empty:
        raise SystemExit(f"no WASDE parquet rows found under {args.wasde_source_prefix}")
    wasde = _filter_wasde_for_surface(wasde, dataset_key=args.dataset_key)
    if wasde.empty:
        raise SystemExit(f"no WASDE rows matched snapshot surface {args.dataset_key}")

    mapping = load_wasde_snapshot_mappings()
    result = build_wasde_snapshot_model_ready_matrix(
        psd,
        wasde,
        source_dataset_version=args.source_dataset_version,
        dataset_key=args.dataset_key,
        mapping_config=mapping,
        attributes=DEFAULT_ATTRIBUTES,
        min_history_years=max(1, int(args.min_history_years)),
        target_keys=args.target_keys_tuple,
    )
    if result.matrix.empty:
        raise SystemExit("WASDE snapshot model-ready matrix is empty")

    selected_features = _selected_dynamic_features(
        result.matrix,
        result.dynamic_feature_columns,
        min_non_null_rate=float(args.min_non_null_rate),
    )
    matrix_by_target = _target_matrix_outputs(result.matrix)
    target_table = _with_training_aliases(result.targets)
    baseline_metrics = _baseline_metrics(matrix_by_target, args.dataset_key, args.commodity)
    membership, feature_set_summary = build_model_ready_feature_membership(
        model_dataset_version=args.model_dataset_version,
        feature_set_ids=args.feature_set_ids_tuple,
        feature_columns=selected_features,
        matrix=result.matrix,
    )

    diagnostics: dict[str, dict] = {}
    for target_key, matrix in matrix_by_target.items():
        report = diagnose_wasde_snapshot_matrix(
            matrix,
            feature_columns=selected_features,
        )
        diagnostics[target_key] = {
            "integrity": report.integrity,
            "readiness": report.readiness,
            "target_diagnostics": _safe_records(report.target_diagnostics),
            "feature_quality": _safe_records(report.feature_quality),
            "leakage_issues": _safe_records(report.leakage_issues),
            "baseline_diagnostics": _safe_records(build_baseline_diagnostics(matrix)),
        }
        if not report.leakage_issues.empty and (report.leakage_issues["severity"] == "fail").any():
            raise SystemExit(f"{target_key}: leakage audit failed")
        if report.integrity.get("duplicate_key_count"):
            raise SystemExit(f"{target_key}: duplicate snapshot matrix keys")
        if report.integrity.get("bad_weight_group_count"):
            raise SystemExit(f"{target_key}: sample weights do not sum to one")

    target_key = gold_model_ready_target_key(
        args.model_dataset_version, args.dataset_key, args.commodity
    )
    matrix_keys = {
        target_key_name: gold_model_ready_matrix_key(
            args.model_dataset_version,
            args.dataset_key,
            args.commodity,
            target_key_name,
        )
        for target_key_name in matrix_by_target
    }
    output_records = {
        "target_key": target_key,
        "matrix_keys": matrix_keys,
        "baseline_metrics_key": gold_model_ready_baseline_metrics_key(args.model_dataset_version),
        "model_ready_feature_sets_key": gold_model_ready_feature_set_version_key(args.model_dataset_version),
        "model_ready_feature_sets_json_key": gold_model_ready_feature_set_summary_key(args.model_dataset_version),
        "manifest_key": gold_model_ready_manifest_key(args.model_dataset_version),
    }
    manifest = build_manifest(
        args=args,
        result=result,
        selected_features=selected_features,
        feature_set_summary=feature_set_summary,
        baseline_metrics=baseline_metrics,
        diagnostics=diagnostics,
        phase2_density_summary=phase2_summary,
        output_records=output_records,
    )

    if args.dry_run:
        print(json.dumps({
            "manifest": manifest,
            "target_rows": int(len(target_table)),
            "matrix_rows_by_target": {
                target_key_name: int(len(matrix))
                for target_key_name, matrix in matrix_by_target.items()
            },
        }, indent=2, sort_keys=True, default=str))
        return

    write_status = {
        "target": _put_parquet(
            s3,
            bucket=args.bucket,
            key=target_key,
            frame=target_table,
            skip_existing_versioned=args.skip_existing_versioned,
        ),
        "baseline_metrics": _put_parquet(
            s3,
            bucket=args.bucket,
            key=output_records["baseline_metrics_key"],
            frame=baseline_metrics,
            skip_existing_versioned=args.skip_existing_versioned,
        ),
        "feature_sets": _put_parquet(
            s3,
            bucket=args.bucket,
            key=output_records["model_ready_feature_sets_key"],
            frame=membership,
            skip_existing_versioned=args.skip_existing_versioned,
        ),
        "feature_sets_json": _put_json(
            s3,
            bucket=args.bucket,
            key=output_records["model_ready_feature_sets_json_key"],
            payload=feature_set_summary,
            skip_existing_versioned=args.skip_existing_versioned,
        ),
    }
    for target_key_name, matrix in matrix_by_target.items():
        write_status[f"matrix:{target_key_name}"] = _put_parquet(
            s3,
            bucket=args.bucket,
            key=matrix_keys[target_key_name],
            frame=matrix,
            skip_existing_versioned=args.skip_existing_versioned,
        )
    manifest["write_status"] = write_status
    write_status["manifest"] = _put_json(
        s3,
        bucket=args.bucket,
        key=output_records["manifest_key"],
        payload=manifest,
        skip_existing_versioned=args.skip_existing_versioned,
    )
    print(json.dumps({
        "model_dataset_version": args.model_dataset_version,
        "manifest_key": output_records["manifest_key"],
        "write_status": write_status,
        "summary": manifest["summary"],
    }, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
