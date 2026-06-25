"""Build metadata tables for an immutable gold_v2 feature-spine version."""
from __future__ import annotations

import argparse
import io
import json
import logging
import sys
from pathlib import Path

import pandas as pd
import pyarrow.dataset as ds

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from leviathan.catalog.registry import load_dataset_registry  # noqa: E402
from leviathan.common.config import get_required_env, load_env  # noqa: E402
from leviathan.common.logging import get_logger  # noqa: E402
from leviathan.features.catalog_v2 import build_feature_catalog_v2  # noqa: E402
from leviathan.storage.paths import (  # noqa: E402
    gold_v2_feature_catalog_key,
    gold_v2_feature_entity_map_key,
    gold_v2_feature_group_map_key,
)
from leviathan.storage.s3 import get_thread_local_s3_client  # noqa: E402

logger = get_logger("feature_catalog_v2_task")

_REQUIRED_REGISTRY_IDS = {
    "gold_v2_feature_catalog",
    "gold_v2_feature_entity_map",
    "gold_v2_feature_group_map",
}


def _parse_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def _root(args: argparse.Namespace) -> str:
    return args.local_root.rstrip("\\/") if args.local_root else f"s3://{args.bucket}"


def _local_path(args: argparse.Namespace, key: str) -> Path:
    return Path(args.local_root) / key


def _prefix_exists(args: argparse.Namespace, prefix: str) -> bool:
    prefix = prefix.rstrip("/") + "/"
    if args.local_root:
        path = _local_path(args, prefix)
        return path.exists() and any(path.rglob("*"))
    s3 = get_thread_local_s3_client(args.aws_region)
    resp = s3.list_objects_v2(Bucket=args.bucket, Prefix=prefix, MaxKeys=1)
    return bool(resp.get("KeyCount"))


def _write_bytes(args: argparse.Namespace, key: str, body: bytes, content_type: str) -> None:
    if args.local_root:
        path = _local_path(args, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        return
    s3 = get_thread_local_s3_client(args.aws_region)
    s3.put_object(Bucket=args.bucket, Key=key, Body=body, ContentType=content_type)


def _write_parquet(args: argparse.Namespace, key: str, df: pd.DataFrame) -> None:
    buf = io.BytesIO()
    df.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
    _write_bytes(args, key, buf.getvalue(), "application/octet-stream")


def _assert_registry_entries() -> None:
    ids = set(load_dataset_registry().by_id())
    missing = sorted(_REQUIRED_REGISTRY_IDS - ids)
    if missing:
        raise SystemExit(f"gold_v2 catalog registry entries missing: {missing}")


def _assert_immutable_prefixes_absent(args: argparse.Namespace) -> None:
    prefixes = [
        f"gold_v2/feature_catalog/dataset_version={args.dataset_version}",
        f"gold_v2/feature_entity_map/dataset_version={args.dataset_version}",
        f"gold_v2/feature_group_map/dataset_version={args.dataset_version}",
    ]
    existing = [prefix for prefix in prefixes if _prefix_exists(args, prefix)]
    if existing:
        raise SystemExit(
            "dataset_version catalog outputs already exist; gold_v2 metadata is immutable: "
            + ", ".join(existing)
        )


def _read_spine(args: argparse.Namespace) -> pd.DataFrame:
    location = f"{_root(args)}/gold_v2/feature_spine/dataset_version={args.dataset_version}"
    try:
        dataset = ds.dataset(location, format="parquet", partitioning="hive")
    except (FileNotFoundError, OSError) as exc:
        raise SystemExit(f"gold_v2 spine version not found at {location}: {exc}") from exc
    fragments = list(dataset.get_fragments())
    if not fragments:
        raise SystemExit(f"gold_v2 spine version has no parquet fragments: {location}")
    table = dataset.to_table()
    df = table.to_pandas()
    if df.empty:
        raise SystemExit(f"gold_v2 spine version is empty: {location}")
    if "dataset_version" not in df.columns:
        df["dataset_version"] = args.dataset_version
    if "commodity" not in df.columns:
        df["commodity"] = df["contract_slug"]
    return df


def _validate_expected_commodities(
    df: pd.DataFrame,
    expected: list[str],
    *,
    allow_partial: bool,
) -> list[str]:
    if not expected:
        return []
    present = set(df["commodity"].astype(str)) if "commodity" in df.columns else set(df["contract_slug"].astype(str))
    missing = sorted(set(expected) - present)
    if missing and not allow_partial:
        raise SystemExit(
            "gold_v2 spine is missing expected commodities: "
            + ",".join(missing)
            + " (use --allow-partial to catalog a smoke subset)"
        )
    return missing


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build gold_v2 feature catalog metadata.")
    parser.add_argument("--dataset-version", required=True, dest="dataset_version")
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    parser.add_argument("--local-root", default=None, dest="local_root")
    parser.add_argument("--expected-commodities", default=None, dest="expected_commodities")
    parser.add_argument("--allow-partial", action="store_true", default=False, dest="allow_partial")
    parser.add_argument("--dry-run", action="store_true", default=False)
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
        stream=sys.stderr,
    )
    load_env()
    args = _parse_args()
    if not args.local_root:
        args.bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
        args.aws_region = args.aws_region or get_required_env("AWS_REGION")

    _assert_registry_entries()
    if not args.dry_run:
        _assert_immutable_prefixes_absent(args)

    spine = _read_spine(args)
    expected = _parse_csv(args.expected_commodities)
    missing = _validate_expected_commodities(
        spine,
        expected,
        allow_partial=args.allow_partial,
    )
    result = build_feature_catalog_v2(spine, dataset_version=args.dataset_version)

    if not args.dry_run:
        _write_parquet(args, gold_v2_feature_catalog_key(args.dataset_version), result.catalog)
        _write_parquet(args, gold_v2_feature_entity_map_key(args.dataset_version), result.entity_map)
        _write_parquet(args, gold_v2_feature_group_map_key(args.dataset_version), result.group_map)

    payload = {
        "dataset_version": args.dataset_version,
        "dry_run": bool(args.dry_run),
        "spine_rows": int(len(spine)),
        "feature_count": int(result.catalog["feature"].nunique()) if not result.catalog.empty else 0,
        "catalog_rows": int(len(result.catalog)),
        "entity_map_rows": int(len(result.entity_map)),
        "group_map_rows": int(len(result.group_map)),
        "missing_expected_commodities": missing,
    }
    logger.info("gold_v2 catalog done %s", payload)
    print(json.dumps(payload, indent=2, default=str))


if __name__ == "__main__":
    main()
