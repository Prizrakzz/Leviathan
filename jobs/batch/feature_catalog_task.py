"""Build semantic catalog and feature coverage maps for a gold dataset version."""

from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import pandas as pd

from leviathan.common.config import get_required_env, load_env
from leviathan.common.constants import ALL_COMMODITIES
from leviathan.common.logging import get_logger
from leviathan.features.semantic_catalog import (
    build_feature_entity_map,
    build_feature_group_map,
    build_semantic_catalog,
    load_feature_groups,
    load_taxonomy,
)
from leviathan.features.spine import SPINE_COLUMNS, load_countries
from leviathan.storage.paths import (
    gold_feature_catalog_version_key,
    gold_feature_entity_map_version_key,
    gold_feature_group_map_version_key,
    gold_feature_spine_manifest_key,
    gold_feature_spine_version_key,
)
from leviathan.storage.s3 import get_thread_local_s3_client

logger = get_logger("feature_catalog_task")


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL, text=True
        ).strip()
    except Exception:  # noqa: BLE001 - git is optional inside containers
        return "unknown"


def _bool_arg(value: bool | str) -> bool:
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "t", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "f", "no", "n", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"expected boolean value, got {value!r}")


def _default_commodities() -> list[str]:
    return [str(c) for c in ALL_COMMODITIES if load_countries(str(c))]


def _parse_commodities(raw: str | None) -> list[str]:
    if raw is None or raw.strip().lower() in {"", "all"}:
        return _default_commodities()
    return [part.strip() for part in raw.split(",") if part.strip()]


def _local_path(args: argparse.Namespace, key: str) -> Path:
    return Path(args.local_root) / key


def _read_bytes(args: argparse.Namespace, key: str) -> bytes:
    if args.local_root:
        return _local_path(args, key).read_bytes()
    s3 = get_thread_local_s3_client(args.aws_region)
    return s3.get_object(Bucket=args.bucket, Key=key)["Body"].read()


def _write_bytes(
    args: argparse.Namespace,
    key: str,
    body: bytes,
    content_type: str,
) -> None:
    if args.local_root:
        path = _local_path(args, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        return
    s3 = get_thread_local_s3_client(args.aws_region)
    s3.put_object(Bucket=args.bucket, Key=key, Body=body, ContentType=content_type)


def _target_exists(args: argparse.Namespace, key: str) -> bool:
    if args.local_root:
        return _local_path(args, key).exists()
    s3 = get_thread_local_s3_client(args.aws_region)
    try:
        s3.head_object(Bucket=args.bucket, Key=key)
        return True
    except Exception as exc:  # noqa: BLE001 - keep boto optional in local tests
        response = getattr(exc, "response", {})
        code = str(response.get("Error", {}).get("Code", ""))
        if code in {"404", "NoSuchKey", "NotFound"}:
            return False
        raise


def _assert_writable(args: argparse.Namespace, keys: list[str]) -> None:
    if args.force_overwrite:
        return
    for key in keys:
        if _target_exists(args, key):
            raise FileExistsError(f"refusing to overwrite catalog artifact: {key}")


def _read_spine(args: argparse.Namespace, commodity: str) -> pd.DataFrame:
    key = gold_feature_spine_version_key(args.dataset_version, commodity)
    if not _target_exists(args, key):
        raise FileNotFoundError(f"missing versioned spine for {commodity}: {key}")
    if args.local_root:
        df = pd.read_parquet(_local_path(args, key), columns=SPINE_COLUMNS)
    else:
        df = pd.read_parquet(io.BytesIO(_read_bytes(args, key)), columns=SPINE_COLUMNS)
    df = df.copy()
    df["commodity"] = commodity
    return df


def _to_parquet_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
    return buf.getvalue()


def _catalog_summary(
    catalog_df: pd.DataFrame,
    entity_map_df: pd.DataFrame,
    group_map_df: pd.DataFrame,
) -> dict:
    return {
        "catalog_rows": int(len(catalog_df)),
        "entity_map_rows": int(len(entity_map_df)),
        "group_map_rows": int(len(group_map_df)),
        "unknown_feature_count": int(
            (catalog_df["semantic_scope"] == "unknown_review_required").sum()
        ),
        "policy_counts": {
            str(k): int(v) for k, v in catalog_df["policy"].value_counts().sort_index().items()
        },
        "semantic_scope_counts": {
            str(k): int(v)
            for k, v in catalog_df["semantic_scope"].value_counts().sort_index().items()
        },
        "feature_family_counts": {
            str(k): int(v)
            for k, v in catalog_df["feature_family"].value_counts().sort_index().items()
        },
        "group_counts": {
            str(k): int(v) for k, v in group_map_df["group"].value_counts().sort_index().items()
        },
    }


def _patch_manifest(args: argparse.Namespace, summary: dict, output_keys: dict[str, str]) -> None:
    key = gold_feature_spine_manifest_key(args.dataset_version)
    if not _target_exists(args, key):
        logger.warning("Dataset manifest is missing; semantic catalog summary not patched: %s", key)
        return

    manifest = json.loads(_read_bytes(args, key).decode("utf-8"))
    manifest["semantic_catalog"] = {
        "task": "feature_catalog_task",
        "built_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "git_sha": _git_sha(),
        "summary": summary,
    }
    manifest.setdefault("outputs", {}).update(output_keys)
    _write_bytes(
        args,
        key,
        json.dumps(manifest, indent=2, default=str).encode("utf-8"),
        "application/json",
    )


def build_and_write(args: argparse.Namespace) -> dict:
    commodities = _parse_commodities(args.expected_commodities)
    frames = [_read_spine(args, commodity) for commodity in commodities]
    spine_df = pd.concat(frames, ignore_index=True)
    taxonomy = load_taxonomy(args.taxonomy_config)
    feature_groups = load_feature_groups(args.groups_config)

    catalog_df = build_semantic_catalog(
        spine_df,
        dataset_version=args.dataset_version,
        taxonomy=taxonomy,
        feature_groups=feature_groups,
        expected_commodities=set(commodities),
        unknown_row_threshold=args.unknown_row_threshold,
    )
    entity_map_df = build_feature_entity_map(spine_df, dataset_version=args.dataset_version)
    group_map_df = build_feature_group_map(
        spine_df,
        catalog_df,
        dataset_version=args.dataset_version,
        feature_groups=feature_groups,
    )

    if len(catalog_df) != int(spine_df["feature"].nunique()):
        raise ValueError("catalog row count does not match observed feature count")
    if entity_map_df.empty:
        raise ValueError("feature entity map is empty")
    if group_map_df.empty:
        raise ValueError("feature group map is empty")
    if (
        catalog_df.loc[catalog_df["feature"].str.startswith("cot_"), "policy"]
        .ne("diagnostic_only")
        .any()
    ):
        raise ValueError("COT features must be diagnostic_only")

    output_keys = {
        "feature_catalog_key": gold_feature_catalog_version_key(args.dataset_version),
        "feature_entity_map_key": gold_feature_entity_map_version_key(args.dataset_version),
        "feature_group_map_key": gold_feature_group_map_version_key(args.dataset_version),
    }

    summary = _catalog_summary(catalog_df, entity_map_df, group_map_df)

    if args.dry_run:
        logger.info("Dry run summary: %s", summary)
        return summary

    _assert_writable(args, list(output_keys.values()))

    _write_bytes(
        args,
        output_keys["feature_catalog_key"],
        _to_parquet_bytes(catalog_df),
        "application/octet-stream",
    )
    _write_bytes(
        args,
        output_keys["feature_entity_map_key"],
        _to_parquet_bytes(entity_map_df),
        "application/octet-stream",
    )
    _write_bytes(
        args,
        output_keys["feature_group_map_key"],
        _to_parquet_bytes(group_map_df),
        "application/octet-stream",
    )

    if args.update_manifest:
        _patch_manifest(args, summary, output_keys)

    logger.info(
        "Semantic catalog written: features=%d entity_rows=%d group_rows=%d",
        len(catalog_df),
        len(entity_map_df),
        len(group_map_df),
    )
    return summary


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build semantic feature catalog maps")
    parser.add_argument("--dataset-version", required=True, dest="dataset_version")
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    parser.add_argument("--local-root", default=None, dest="local_root")
    parser.add_argument(
        "--expected-commodities",
        default="all",
        dest="expected_commodities",
        help="Comma-separated commodity slugs, or 'all'.",
    )
    parser.add_argument("--taxonomy-config", default=None, dest="taxonomy_config")
    parser.add_argument("--groups-config", default=None, dest="groups_config")
    parser.add_argument(
        "--unknown-row-threshold",
        type=int,
        default=0,
        dest="unknown_row_threshold",
        help="Fail when an unmatched taxonomy feature has more rows than this threshold.",
    )
    parser.add_argument(
        "--force-overwrite",
        action="store_true",
        default=False,
        dest="force_overwrite",
    )
    parser.add_argument(
        "--update-manifest",
        nargs="?",
        const=True,
        default=True,
        type=_bool_arg,
        dest="update_manifest",
    )
    parser.add_argument("--dry-run", action="store_true", default=False)
    return parser.parse_args()


def main() -> None:
    load_env()
    args = _parse_args()
    if not args.local_root:
        args.bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
        args.aws_region = args.aws_region or get_required_env("AWS_REGION")
    summary = build_and_write(args)
    logger.info("Done dataset_version=%s summary=%s", args.dataset_version, summary)


if __name__ == "__main__":
    main()
