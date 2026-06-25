"""Build immutable point-in-time gold_v2 feature datasets.

This is the Phase 4 smoke builder.  It is additive to legacy ``gold/`` and
never overwrites an existing dataset_version prefix.
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import logging
import subprocess
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from leviathan.catalog.registry import load_dataset_registry  # noqa: E402
from leviathan.common.config import get_required_env, load_env  # noqa: E402
from leviathan.common.logging import get_logger  # noqa: E402
from leviathan.features.availability import normalize_availability  # noqa: E402
from leviathan.features.extractors import SourceProbe, extract_all  # noqa: E402
from leviathan.features.pivot import build_feature_matrix_v2  # noqa: E402
from leviathan.features.spine_v2 import (  # noqa: E402
    DEFAULT_V2_COMMODITIES,
    SOURCE_DATASET_IDS,
    build_spine_v2,
    default_as_of_dates,
    default_dataset_version,
    v2_source_keys_for_commodity,
)
from leviathan.storage.paths import (  # noqa: E402
    gold_v2_dataset_manifest_key,
    gold_v2_feature_matrix_key,
    gold_v2_feature_spine_key,
    gold_v2_preflight_report_key,
)
from leviathan.storage.s3 import get_thread_local_s3_client  # noqa: E402

logger = get_logger("feature_spine_v2_task")

_REQUIRED_REGISTRY_IDS = {
    "gold_v2_feature_spine",
    "gold_v2_feature_matrix",
    "gold_v2_dataset_manifests",
}
_UNSUPPORTED_READY_LATER = {"unica"}


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL, text=True
        ).strip()
    except Exception:  # noqa: BLE001
        return "unknown"


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


def _write_json(args: argparse.Namespace, key: str, payload: dict) -> None:
    _write_bytes(
        args,
        key,
        json.dumps(payload, indent=2, sort_keys=True, default=str).encode("utf-8"),
        "application/json",
    )


def _assert_registry_entries() -> None:
    ids = set(load_dataset_registry().by_id())
    missing = sorted(_REQUIRED_REGISTRY_IDS - ids)
    if missing:
        raise SystemExit(f"gold_v2 registry entries missing: {missing}")


def _assert_immutable_prefixes_absent(args: argparse.Namespace) -> None:
    prefixes = [
        f"gold_v2/feature_spine/dataset_version={args.dataset_version}",
        f"gold_v2/feature_matrix/dataset_version={args.dataset_version}",
        f"gold_v2/dataset_manifests/dataset_version={args.dataset_version}",
    ]
    existing = [prefix for prefix in prefixes if _prefix_exists(args, prefix)]
    if existing:
        raise SystemExit(
            "dataset_version already exists; gold_v2 is immutable: "
            + ", ".join(existing)
        )


def _source_report_from_probe(
    probe: SourceProbe | None,
    *,
    source_key: str,
    dataset_id: str | None,
    inputs: dict[str, pd.DataFrame],
    allow_waivers: bool,
) -> dict:
    if source_key in _UNSUPPORTED_READY_LATER:
        status = "waived" if allow_waivers else "block"
        return {
            "source_key": source_key,
            "dataset_id": dataset_id,
            "certification_status": status,
            "row_count": 0,
            "max_date": None,
            "blockers": [] if allow_waivers else ["source reader not implemented for v2 smoke"],
            "waiver": "UNICA v2 source-date certification deferred" if allow_waivers else None,
        }
    if probe is None or not probe.exists or probe.num_rows == 0:
        status = "waived" if allow_waivers else "block"
        return {
            "source_key": source_key,
            "dataset_id": dataset_id,
            "certification_status": status,
            "row_count": int(probe.num_rows) if probe else 0,
            "max_date": None,
            "blockers": [] if allow_waivers else ["source missing or empty"],
            "waiver": "missing source allowed by --allow-waivers" if allow_waivers else None,
        }
    max_date = None
    if source_key in inputs:
        try:
            normal = normalize_availability(source_key, inputs[source_key])
            max_value = normal["feature_available_at"].max()
            max_date = None if pd.isna(max_value) else pd.Timestamp(max_value).date().isoformat()
        except Exception as exc:  # noqa: BLE001
            return {
                "source_key": source_key,
                "dataset_id": dataset_id,
                "certification_status": "block",
                "row_count": int(probe.num_rows),
                "max_date": None,
                "blockers": [f"availability normalization failed: {exc}"],
                "waiver": None,
            }
    return {
        "source_key": source_key,
        "dataset_id": dataset_id,
        "certification_status": "pass",
        "row_count": int(probe.num_rows),
        "max_date": max_date,
        "blockers": [],
        "waiver": None,
    }


def _load_commodity_inputs(
    args: argparse.Namespace,
    commodity: str,
) -> tuple[dict[str, pd.DataFrame], list[dict], list[SourceProbe]]:
    requested = v2_source_keys_for_commodity(commodity)
    extractable = requested - _UNSUPPORTED_READY_LATER
    inputs, probes = extract_all(_root(args), commodity, extractable)
    by_source = {probe.source_key: probe for probe in probes}
    reports = [
        _source_report_from_probe(
            by_source.get(source_key),
            source_key=source_key,
            dataset_id=SOURCE_DATASET_IDS.get(source_key),
            inputs=inputs,
            allow_waivers=args.allow_waivers,
        )
        for source_key in sorted(requested)
    ]
    return inputs, reports, probes


def _as_of_dates(args: argparse.Namespace, crop_years: list[int]) -> dict[int, pd.Timestamp]:
    if args.as_of_date:
        as_of = pd.to_datetime(args.as_of_date, errors="raise").normalize()
        return {year: as_of for year in crop_years}
    return default_as_of_dates(crop_years)


def _flatten_manifest_strings(values: list[dict], status: str) -> str:
    return ",".join(
        item["source_key"]
        for item in values
        if item["certification_status"] == status
    )


def _should_skip_commodity_for_waiver(commodity: str, source_reports: list[dict]) -> bool:
    """Raw sugar is excluded from first v2 writes until UNICA dates certify cleanly."""
    if commodity != "raw_sugar":
        return False
    return any(
        report["source_key"] == "unica"
        and report["certification_status"] == "waived"
        for report in source_reports
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build immutable PIT gold_v2 feature spine.")
    parser.add_argument("--dataset-version", default=None, dest="dataset_version")
    parser.add_argument(
        "--commodities",
        default=",".join(DEFAULT_V2_COMMODITIES),
        help="Comma-separated commodity slugs.",
    )
    parser.add_argument("--snapshot-policy", default="default_v1", dest="snapshot_policy")
    parser.add_argument("--start-crop-year", type=int, default=2018, dest="start_crop_year")
    parser.add_argument("--end-crop-year", type=int, default=None, dest="end_crop_year")
    parser.add_argument("--as-of-date", default=None, dest="as_of_date")
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    parser.add_argument("--local-root", default=None, dest="local_root")
    parser.add_argument("--dry-run", action="store_true", default=False)
    parser.add_argument("--allow-waivers", action="store_true", default=False, dest="allow_waivers")
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
        stream=sys.stderr,
    )
    load_env()
    args = _parse_args()
    args.dataset_version = args.dataset_version or default_dataset_version()
    if not args.local_root:
        args.bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
        args.aws_region = args.aws_region or get_required_env("AWS_REGION")

    _assert_registry_entries()
    if not args.dry_run:
        _assert_immutable_prefixes_absent(args)

    commodities = _parse_csv(args.commodities) or DEFAULT_V2_COMMODITIES
    end_year = args.end_crop_year or dt.date.today().year
    crop_years = list(range(int(args.start_crop_year), int(end_year) + 1))
    as_of_dates = _as_of_dates(args, crop_years)
    git_sha = _git_sha()

    logger.info(
        "gold_v2 build version=%s commodities=%s years=%s-%s dry_run=%s allow_waivers=%s",
        args.dataset_version, ",".join(commodities), crop_years[0], crop_years[-1],
        args.dry_run, args.allow_waivers,
    )

    all_spines: list[pd.DataFrame] = []
    all_matrices: list[pd.DataFrame] = []
    preflight_sources: list[dict] = []
    commodity_results: list[dict] = []

    for commodity in commodities:
        inputs, source_reports, _ = _load_commodity_inputs(args, commodity)
        preflight_sources.extend(
            {**report, "commodity": commodity}
            for report in source_reports
        )
        blockers = [
            report for report in source_reports
            if report["certification_status"] == "block"
        ]
        if blockers:
            commodity_results.append({
                "commodity": commodity,
                "status": "blocked_preflight",
                "blockers": blockers,
            })
            continue
        if _should_skip_commodity_for_waiver(commodity, source_reports):
            commodity_results.append({
                "commodity": commodity,
                "status": "waived_excluded",
                "reason": "UNICA source-date certification is waived; raw_sugar excluded from this v2 write.",
            })
            continue

        build = build_spine_v2(
            commodity=commodity,
            crop_years=crop_years,
            inputs=inputs,
            as_of_dates=as_of_dates,
            snapshot_policy=args.snapshot_policy,
        )
        if not build.passed:
            commodity_results.append({
                "commodity": commodity,
                "status": "validation_failed",
                "report": build.report,
            })
            continue

        matrix = build_feature_matrix_v2(build.df)
        commodity_results.append({
            "commodity": commodity,
            "status": "dry_run" if args.dry_run else "written",
            "spine_rows": int(len(build.df)),
            "matrix_rows": int(len(matrix)),
            "feature_count": int(build.df["feature"].nunique()) if not build.df.empty else 0,
            "report": build.report,
        })
        all_spines.append(build.df)
        all_matrices.append(matrix)

        if not args.dry_run:
            _write_parquet(
                args,
                gold_v2_feature_spine_key(args.dataset_version, commodity),
                build.df,
            )
            _write_parquet(
                args,
                gold_v2_feature_matrix_key(args.dataset_version, commodity),
                matrix,
            )

    blocked = [row for row in preflight_sources if row["certification_status"] == "block"]
    if blocked:
        logger.error("gold_v2 preflight blocked %d source(s)", len(blocked))

    spine_rows = int(sum(len(frame) for frame in all_spines))
    matrix_rows = int(sum(len(frame) for frame in all_matrices))
    preflight_report = {
        "dataset_version": args.dataset_version,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "base_git_sha": git_sha,
        "certified_sources": [row for row in preflight_sources if row["certification_status"] == "pass"],
        "blocked_sources": blocked,
        "warning_only_sources": [row for row in preflight_sources if row["certification_status"] == "warn"],
        "allowed_waivers": [row for row in preflight_sources if row["certification_status"] == "waived"],
        "source_row_counts": {
            f"{row['commodity']}:{row['source_key']}": row["row_count"]
            for row in preflight_sources
        },
        "source_max_dates": {
            f"{row['commodity']}:{row['source_key']}": row["max_date"]
            for row in preflight_sources
        },
    }
    manifest = {
        "dataset_version": args.dataset_version,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "base_git_sha": git_sha,
        "snapshot_policy": args.snapshot_policy,
        "commodities": ",".join(commodities),
        "certified_sources": _flatten_manifest_strings(preflight_sources, "pass"),
        "blocked_sources": _flatten_manifest_strings(preflight_sources, "block"),
        "warning_sources": _flatten_manifest_strings(preflight_sources, "warn"),
        "waivers": _flatten_manifest_strings(preflight_sources, "waived"),
        "spine_row_count": spine_rows,
        "matrix_row_count": matrix_rows,
        "commodity_results": commodity_results,
        "preflight_report_key": gold_v2_preflight_report_key(args.dataset_version),
    }

    if not args.dry_run and not blocked:
        _write_json(args, gold_v2_preflight_report_key(args.dataset_version), preflight_report)
        _write_json(args, gold_v2_dataset_manifest_key(args.dataset_version), manifest)

    logger.info(
        "gold_v2 done version=%s spine_rows=%d matrix_rows=%d blocked=%d dry_run=%s",
        args.dataset_version, spine_rows, matrix_rows, len(blocked), args.dry_run,
    )
    print(json.dumps({
        "dataset_version": args.dataset_version,
        "spine_rows": spine_rows,
        "matrix_rows": matrix_rows,
        "blocked_sources": len(blocked),
        "commodity_results": commodity_results,
    }, indent=2, default=str))

    if blocked:
        raise SystemExit(1)
    if any(row["status"] == "validation_failed" for row in commodity_results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
