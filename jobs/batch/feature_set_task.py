"""Build model-purpose feature-set membership for an immutable gold version."""
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
from leviathan.common.logging import get_logger
from leviathan.features.feature_sets import (
    build_feature_set_membership,
    load_feature_set_config,
)
from leviathan.storage.paths import (
    gold_feature_catalog_version_key,
    gold_feature_group_map_version_key,
    gold_feature_set_summary_key,
    gold_feature_set_version_key,
    gold_feature_spine_manifest_key,
)
from leviathan.storage.s3 import get_thread_local_s3_client

logger = get_logger("feature_set_task")


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
    except Exception as exc:  # noqa: BLE001 - keep boto optional in tests
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
            raise FileExistsError(f"refusing to overwrite feature-set artifact: {key}")


def _read_parquet(args: argparse.Namespace, key: str) -> pd.DataFrame:
    if not _target_exists(args, key):
        raise FileNotFoundError(f"missing required artifact: {key}")
    if args.local_root:
        return pd.read_parquet(_local_path(args, key))
    return pd.read_parquet(io.BytesIO(_read_bytes(args, key)))


def _to_parquet_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
    return buf.getvalue()


def _patch_manifest(args: argparse.Namespace, summary: dict, output_keys: dict[str, str]) -> None:
    manifest_key = gold_feature_spine_manifest_key(args.dataset_version)
    if not _target_exists(args, manifest_key):
        logger.warning("Dataset manifest missing; feature-set summary not patched: %s", manifest_key)
        return
    manifest = json.loads(_read_bytes(args, manifest_key).decode("utf-8"))
    manifest["feature_sets"] = {
        "task": "feature_set_task",
        "built_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "git_sha": _git_sha(),
        "summary": summary,
    }
    manifest.setdefault("outputs", {}).update(output_keys)
    _write_bytes(
        args,
        manifest_key,
        json.dumps(manifest, indent=2, default=str).encode("utf-8"),
        "application/json",
    )


def build_and_write(args: argparse.Namespace) -> dict:
    specs, config_sha = load_feature_set_config(args.feature_sets_config)
    catalog_df = _read_parquet(args, gold_feature_catalog_version_key(args.dataset_version))
    group_map_df = _read_parquet(args, gold_feature_group_map_version_key(args.dataset_version))
    membership_df, summary = build_feature_set_membership(
        catalog_df,
        group_map_df,
        dataset_version=args.dataset_version,
        specs=specs,
        config_sha=config_sha,
    )

    output_keys = {
        "feature_sets_key": gold_feature_set_version_key(args.dataset_version),
        "feature_sets_json_key": gold_feature_set_summary_key(args.dataset_version),
    }

    if args.dry_run:
        logger.info("Dry run summary: %s", summary)
        return summary

    _assert_writable(args, list(output_keys.values()))
    _write_bytes(
        args,
        output_keys["feature_sets_key"],
        _to_parquet_bytes(membership_df),
        "application/octet-stream",
    )
    _write_bytes(
        args,
        output_keys["feature_sets_json_key"],
        json.dumps(summary, indent=2, default=str).encode("utf-8"),
        "application/json",
    )

    if args.update_manifest:
        _patch_manifest(args, summary, output_keys)

    logger.info(
        "Feature sets written: sets=%d selected_rows=%d",
        summary["feature_set_count"],
        summary["selected_row_count"],
    )
    return summary


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build model-purpose feature-set membership")
    parser.add_argument("--dataset-version", required=True, dest="dataset_version")
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    parser.add_argument("--local-root", default=None, dest="local_root")
    parser.add_argument("--feature-sets-config", default=None, dest="feature_sets_config")
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
