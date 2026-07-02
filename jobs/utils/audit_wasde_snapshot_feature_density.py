"""Audit live WASDE snapshot dynamic feature density before model-ready writes."""
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
from leviathan.model_datasets.wasde_snapshot_features import (  # noqa: E402
    DEFAULT_ATTRIBUTES,
    build_wasde_feature_quality_report,
    build_wasde_snapshot_dynamic_features,
    prepare_wasde_snapshot_feature_source,
)
from leviathan.model_datasets.wasde_snapshot_mapping import (  # noqa: E402
    load_wasde_snapshot_mappings,
    normalize_wasde_token,
)
from leviathan.model_datasets.wasde_snapshot_targets import assign_snapshot_stage  # noqa: E402

DEFAULT_BUCKET = "leviathan-dev-shahem-001"
DEFAULT_REGION = "us-east-1"
DEFAULT_WASDE_PREFIX = "silver/wasde/"
DEFAULT_DATASET_KEY = "corn_wasde_snapshot_solo"
DEFAULT_OUTPUT_LOCAL = "data/phase_wasde_snapshot"


def _parse_csv(value: str | None) -> tuple[str, ...]:
    if not value or str(value).strip().lower() in {"none", "default", "all"}:
        return ()
    return tuple(item.strip().lower() for item in value.split(",") if item.strip())


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
    columns: list[str],
    workers: int,
) -> pd.DataFrame:
    keys = _list_parquet_keys(s3, bucket, prefix)
    if not keys:
        return pd.DataFrame()
    frames: list[pd.DataFrame] = []
    failures: list[str] = []
    with ThreadPoolExecutor(max_workers=max(1, int(workers))) as pool:
        futures = {
            pool.submit(_read_parquet_key, s3, bucket, key, columns): key
            for key in keys
        }
        for future in as_completed(futures):
            key = futures[future]
            try:
                frame = future.result()
                if not frame.empty:
                    frames.append(frame)
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{key}: {exc}")
    if failures:
        raise RuntimeError("failed to read WASDE parquet keys: " + "; ".join(failures[:5]))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _write_parquet(path: Path, frame: pd.DataFrame) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)
    return str(path)


def _write_json(path: Path, payload: dict[str, object]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
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


def _write_s3_json(s3, bucket: str, key: str, payload: dict[str, object]) -> str:
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(payload, indent=2, sort_keys=True, default=str).encode("utf-8"),
        ContentType="application/json",
    )
    return f"s3://{bucket}/{key}"


def _surface_origins(dataset_key: str) -> tuple[str, ...]:
    cfg = load_wasde_snapshot_mappings()
    surface = cfg.surfaces[dataset_key]
    return tuple(origin.origin_key for origin in surface.target_origins)


def _filter_wasde_for_surface(
    wasde_df: pd.DataFrame,
    *,
    dataset_key: str,
    origins: tuple[str, ...],
) -> pd.DataFrame:
    cfg = load_wasde_snapshot_mappings()
    surface = cfg.surfaces[dataset_key]
    source = wasde_df.copy()
    commodity = source["commodity"].map(normalize_wasde_token)
    region = source["region"].map(normalize_wasde_token)
    origin = region.map(lambda value: cfg.region_aliases.get(value, value))
    return source.loc[
        (commodity == surface.primary_wasde_commodity)
        & (origin.isin(set(origins)))
    ].copy()


def _build_release_snapshot_rows(
    wasde_df: pd.DataFrame,
    *,
    dataset_key: str,
    origins: tuple[str, ...],
    max_snapshots_per_group: int,
) -> pd.DataFrame:
    cfg = load_wasde_snapshot_mappings()
    surface = cfg.surfaces[dataset_key]
    source = prepare_wasde_snapshot_feature_source(
        wasde_df,
        mapping_config=cfg,
        attributes=DEFAULT_ATTRIBUTES,
    )
    source = source.loc[source["wasde_origin"].isin(origins)].copy()
    spine = (
        source[["wasde_commodity", "wasde_origin", "target_market_year", "release_date"]]
        .drop_duplicates()
        .sort_values(["wasde_origin", "target_market_year", "release_date"])
        .reset_index(drop=True)
    )
    if max_snapshots_per_group > 0:
        spine = spine.groupby(
            ["wasde_commodity", "wasde_origin", "target_market_year"],
            group_keys=False,
            sort=False,
        ).tail(max_snapshots_per_group)
    spine["dataset_key"] = dataset_key
    spine["contract_key"] = surface.primary_contract
    spine["origin_key"] = spine["wasde_origin"]
    spine["as_of_date"] = spine["release_date"]
    spine["snapshot_stage"] = spine["as_of_date"].map(assign_snapshot_stage)
    return spine[
        [
            "dataset_key",
            "contract_key",
            "origin_key",
            "target_market_year",
            "as_of_date",
            "snapshot_stage",
            "wasde_commodity",
            "wasde_origin",
        ]
    ].reset_index(drop=True)


def _summarize(
    *,
    dataset_key: str,
    origins: tuple[str, ...],
    snapshots: pd.DataFrame,
    features: pd.DataFrame,
    quality: pd.DataFrame,
    min_non_null_rate: float,
) -> dict[str, object]:
    usable = quality.loc[
        quality["non_null_rate"].ge(float(min_non_null_rate))
        & (
            quality["constant_rate"].isna()
            | quality["constant_rate"].lt(1.0)
        )
    ].copy()
    stock_features = quality.loc[
        quality["feature"].astype(str).str.startswith("wasde_stock_to_use_")
    ].copy()
    latest_features = quality.loc[
        quality["feature"].astype(str).str.endswith("_latest")
    ].copy()
    return {
        "phase": "phase2_wasde_dynamic_feature_density",
        "dataset_key": dataset_key,
        "origins": list(origins),
        "snapshot_rows": int(len(snapshots)),
        "feature_rows": int(len(features)),
        "feature_count": int(len(quality)),
        "usable_feature_count": int(len(usable)),
        "min_non_null_rate": float(min_non_null_rate),
        "stock_to_use_feature_count": int(len(stock_features)),
        "stock_to_use_max_non_null_rate": (
            float(stock_features["non_null_rate"].max()) if not stock_features.empty else None
        ),
        "latest_feature_min_non_null_rate": (
            float(latest_features["non_null_rate"].min()) if not latest_features.empty else None
        ),
        "latest_feature_median_non_null_rate": (
            float(latest_features["non_null_rate"].median()) if not latest_features.empty else None
        ),
        "top_features": quality.sort_values(
            ["non_null_rate", "constant_rate", "feature"],
            ascending=[False, True, True],
        ).head(20).to_dict("records"),
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bucket", default=DEFAULT_BUCKET)
    parser.add_argument("--aws-region", default=DEFAULT_REGION, dest="aws_region")
    parser.add_argument("--wasde-prefix", default=DEFAULT_WASDE_PREFIX, dest="wasde_prefix")
    parser.add_argument("--dataset-key", default=DEFAULT_DATASET_KEY, dest="dataset_key")
    parser.add_argument("--origins", default="", help="Comma-separated normalized origins.")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--min-history-years", type=int, default=5, dest="min_history_years")
    parser.add_argument("--min-non-null-rate", type=float, default=0.5, dest="min_non_null_rate")
    parser.add_argument(
        "--max-snapshots-per-group",
        type=int,
        default=0,
        dest="max_snapshots_per_group",
        help="Optional tail limit per origin/market-year group for quick local debugging.",
    )
    parser.add_argument("--output-local", default=DEFAULT_OUTPUT_LOCAL, dest="output_local")
    parser.add_argument("--output-prefix", default="", dest="output_prefix")
    parser.add_argument("--dry-run", action="store_true", dest="dry_run")
    return parser.parse_args()


def main() -> None:
    load_env()
    args = _parse_args()
    origins = _parse_csv(args.origins) or _surface_origins(args.dataset_key)
    s3 = boto3.client("s3", region_name=args.aws_region)
    wasde = _read_parquet_prefix(
        s3,
        args.bucket,
        args.wasde_prefix,
        workers=max(1, args.workers),
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
    wasde = _filter_wasde_for_surface(
        wasde,
        dataset_key=args.dataset_key,
        origins=origins,
    )
    snapshots = _build_release_snapshot_rows(
        wasde,
        dataset_key=args.dataset_key,
        origins=origins,
        max_snapshots_per_group=max(0, int(args.max_snapshots_per_group)),
    )
    features = build_wasde_snapshot_dynamic_features(
        wasde,
        snapshots,
        attributes=DEFAULT_ATTRIBUTES,
        min_history_years=max(1, int(args.min_history_years)),
    )
    quality = build_wasde_feature_quality_report(features)
    summary = _summarize(
        dataset_key=args.dataset_key,
        origins=origins,
        snapshots=snapshots,
        features=features,
        quality=quality,
        min_non_null_rate=args.min_non_null_rate,
    )

    if args.dry_run:
        print(json.dumps(summary, indent=2, sort_keys=True, default=str))
        return

    output_dir = Path(args.output_local)
    outputs = {
        "summary": _write_json(output_dir / "wasde_snapshot_feature_density_summary.json", summary),
        "quality": _write_parquet(output_dir / "wasde_snapshot_feature_density_quality.parquet", quality),
        "snapshots": _write_parquet(output_dir / "wasde_snapshot_feature_density_spine.parquet", snapshots),
    }
    if args.output_prefix:
        prefix = args.output_prefix.strip("/")
        outputs["s3_summary"] = _write_s3_json(
            s3,
            args.bucket,
            f"{prefix}/feature_density_summary.json",
            summary,
        )
        outputs["s3_quality"] = _write_s3_frame(
            s3,
            args.bucket,
            f"{prefix}/feature_density_quality.parquet",
            quality,
        )
        outputs["s3_snapshots"] = _write_s3_frame(
            s3,
            args.bucket,
            f"{prefix}/feature_density_spine.parquet",
            snapshots,
        )

    print(json.dumps({"summary": summary, "outputs": outputs}, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
