"""AWS Batch task: silver/* → gold/feature_spine (long-format training matrix).

Builds the point-in-time-correct feature spine per commodity from validated
silver inputs, per the declarative registry in configs/features/features.yaml.

Output:   gold/feature_spine/commodity={slug}/part-000.parquet
Manifest: gold/feature_spine/_manifests/commodity={slug}/run.json
          (input fragment fingerprints, params hash, git SHA, quality report —
           a spine partition is reproducible from its manifest)

Per-commodity partitions are fully rewritten on every run: at this grain
(~10-15k rows) incremental upserts are complexity with zero payoff, and a
whole-partition single-object PUT is atomic and idempotent by construction.

Usage
-----
    # Smoke test — one commodity, no writes
    python jobs/batch/feature_spine_task.py --commodity arabica_coffee --dry-run

    # Full run, all commodities with geography configs
    python jobs/batch/feature_spine_task.py \\
        --bucket leviathan-dev-shahem-001 --aws-region us-east-1

    # Anti-leakage verification on real data (no writes)
    python jobs/batch/feature_spine_task.py --verify-pit --dry-run

    # Local data root (testing without S3)
    python jobs/batch/feature_spine_task.py --local-root /tmp/lake --dry-run
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import io
import json
import logging
import subprocess
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import pandas as pd
from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.features.calendar import load_crop_calendars
from leviathan.features.extractors import SourceLoadPlan, SourceProbe, extract_all
from leviathan.features.pivot import build_feature_catalog, build_feature_matrix
from leviathan.features.registry import load_registry
from leviathan.features.spine import (
    SPINE_NATURAL_KEY,
    SpineBuildResult,
    build_spine,
    default_calendar,
    load_countries,
)
from leviathan.storage.paths import (
    gold_feature_catalog_version_key,
    gold_feature_matrix_version_key,
    gold_feature_spine_commodity_manifest_key,
    gold_feature_spine_manifest_key,
    gold_feature_spine_version_key,
)
from leviathan.storage.s3 import get_thread_local_s3_client

logger = get_logger("feature_spine_task")

_SPINE_PREFIX = "gold/feature_spine"
_MATRIX_PREFIX = "gold/feature_matrix"
_CATALOG_KEY = "gold/feature_catalog/feature_catalog.parquet"
_DEFAULT_START_CROP_YEAR = 1981
_REPO_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_FINGERPRINTS = (
    "configs/features/features.yaml",
    "configs/features/feature_params.yaml",
    "configs/features/crop_calendars.yaml",
)
# Crop years compared by --verify-pit must have windows that fully precede the
# truncation cutoff; a 2-year guard covers windows that span calendar years.
_PIT_BOUNDARY_GUARD_YEARS = 2


def _source_year_bounds(crop_years: list[int], registry) -> tuple[int, int]:
    """Broad enough for trailing-baseline weather features, bounded for smoke runs."""
    baselines = registry.shared_params.get("baselines", {})
    lookback = int(baselines.get("window_years", 30))
    return min(crop_years) - lookback - 2, max(crop_years) + 2


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL, text=True
        ).strip()
    except Exception:  # noqa: BLE001 — git absent inside the container is fine
        return "unknown"


def _default_dataset_version(git_sha: str) -> str:
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = git_sha[:12] if git_sha and git_sha != "unknown" else "unknown"
    return f"{stamp}_{suffix}"


def _bool_arg(value: bool | str) -> bool:
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "t", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "f", "no", "n", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"expected boolean value, got {value!r}")


def _optional_int_arg(value: str | int | None) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"none", "null", "all"}:
        return None
    return int(text)


def _spine_key(commodity: str) -> str:
    return f"{_SPINE_PREFIX}/commodity={commodity}/part-000.parquet"


def _manifest_key(commodity: str) -> str:
    return f"{_SPINE_PREFIX}/_manifests/commodity={commodity}/run.json"


def _matrix_key(commodity: str) -> str:
    return f"{_MATRIX_PREFIX}/commodity={commodity}/part-0.parquet"


def _write_bytes(args: argparse.Namespace, key: str, body: bytes,
                 content_type: str) -> None:
    if args.local_root:
        from pathlib import Path
        path = Path(args.local_root) / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        return
    s3 = get_thread_local_s3_client(args.aws_region)
    s3.put_object(Bucket=args.bucket, Key=key, Body=body, ContentType=content_type)


def _read_bytes(args: argparse.Namespace, location: str) -> bytes:
    parsed = urlparse(location)
    if parsed.scheme == "s3":
        s3 = get_thread_local_s3_client(args.aws_region)
        return s3.get_object(Bucket=parsed.netloc, Key=parsed.path.lstrip("/"))["Body"].read()

    path = Path(location)
    if path.exists():
        return path.read_bytes()

    if args.local_root:
        return (Path(args.local_root) / location).read_bytes()

    s3 = get_thread_local_s3_client(args.aws_region)
    return s3.get_object(Bucket=args.bucket, Key=location)["Body"].read()


def _target_exists(args: argparse.Namespace, key: str) -> bool:
    if args.local_root:
        return (Path(args.local_root) / key).exists()

    s3 = get_thread_local_s3_client(args.aws_region)
    try:
        s3.head_object(Bucket=args.bucket, Key=key)
        return True
    except Exception as exc:  # noqa: BLE001 - keep boto optional for local tests
        response = getattr(exc, "response", {})
        code = str(response.get("Error", {}).get("Code", ""))
        if code in {"404", "NoSuchKey", "NotFound"}:
            return False
        raise


def _assert_absent(args: argparse.Namespace, key: str) -> None:
    if args.fail_if_version_exists and _target_exists(args, key):
        raise FileExistsError(
            f"refusing to overwrite immutable feature-spine dataset object: {key}"
        )


def _sha256_bytes(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _file_sha256(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _config_fingerprints() -> dict[str, str]:
    fingerprints: dict[str, str] = {}
    for rel in _CONFIG_FINGERPRINTS:
        path = _REPO_ROOT / rel
        if path.exists():
            fingerprints[rel] = _file_sha256(path)

    geo_dir = _REPO_ROOT / "configs" / "geographies"
    if geo_dir.exists():
        digest = hashlib.sha256()
        for path in sorted(geo_dir.glob("*.yaml")):
            digest.update(path.name.encode("utf-8"))
            digest.update(path.read_bytes())
        fingerprints["configs/geographies/*.yaml"] = digest.hexdigest()
    return fingerprints


def _source_certification_metadata(args: argparse.Namespace) -> dict:
    location = (args.source_certification_report or "").strip()
    if not location or location.lower() in {"none", "null"}:
        return {"provided": False}

    body = _read_bytes(args, location)
    metadata: dict = {
        "provided": True,
        "location": location,
        "sha256": _sha256_bytes(body),
        "status_counts": {},
    }
    try:
        parsed = json.loads(body.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        metadata["parse_error"] = str(exc)
        return metadata

    if isinstance(parsed.get("status_counts"), dict):
        metadata["status_counts"] = dict(sorted(parsed["status_counts"].items()))
    else:
        rows = parsed.get("source_results") or parsed.get("sources") or parsed.get("results") or []
        if isinstance(rows, dict):
            rows = list(rows.values())
        counts: dict[str, int] = defaultdict(int)
        for row in rows:
            if isinstance(row, dict):
                counts[str(row.get("status", "unknown"))] += 1
        metadata["status_counts"] = dict(sorted(counts.items()))
    for key in (
        "contracts_sha256",
        "feature_registry_sha256",
        "generated_at",
        "base_git_sha",
    ):
        if key in parsed:
            metadata[key] = parsed[key]
    return metadata


def _spine_version_key(args: argparse.Namespace, commodity: str) -> str:
    return gold_feature_spine_version_key(args.dataset_version, commodity)


def _matrix_version_key(args: argparse.Namespace, commodity: str) -> str:
    return gold_feature_matrix_version_key(args.dataset_version, commodity)


def _versioned_manifest_key(args: argparse.Namespace, commodity: str) -> str:
    return gold_feature_spine_commodity_manifest_key(args.dataset_version, commodity)


def _dataset_manifest_key(args: argparse.Namespace) -> str:
    return gold_feature_spine_manifest_key(args.dataset_version)


def _catalog_version_key(args: argparse.Namespace) -> str:
    return gold_feature_catalog_version_key(args.dataset_version)


def _truncate_inputs(
    inputs: dict[str, pd.DataFrame], cutoff_year: int
) -> dict[str, pd.DataFrame]:
    """Drop all input data dated on/after Jan 1 of *cutoff_year* (PIT check)."""
    cutoff = pd.Timestamp(datetime.date(cutoff_year, 1, 1))
    truncated: dict[str, pd.DataFrame] = {}
    for key, df in inputs.items():
        if "date" in df.columns:
            truncated[key] = df.loc[pd.to_datetime(df["date"]) < cutoff]
        elif "release_date" in df.columns:
            truncated[key] = df.loc[pd.to_datetime(df["release_date"]) < cutoff]
        elif "year" in df.columns:
            years = pd.to_numeric(df["year"], errors="coerce")
            truncated[key] = df.loc[years < cutoff_year]
        else:
            truncated[key] = df
    return truncated


def _verify_point_in_time(
    full: SpineBuildResult,
    commodity: str,
    crop_years: list[int],
    countries: list[str],
    calendar,
    registry,
    inputs: dict[str, pd.DataFrame],
) -> bool:
    """Truncate-at-T property: deleting future data must not change the past.

    Rebuilds the spine with inputs truncated at T and asserts row equality for
    every observation with crop_year <= T - guard.  Any difference means some
    feature is reading the future.
    """
    cutoff_year = max(crop_years) - 5
    compare_through = cutoff_year - _PIT_BOUNDARY_GUARD_YEARS

    truncated_result = build_spine(
        commodity=commodity,
        crop_years=[y for y in crop_years if y <= compare_through],
        countries=countries,
        calendar=calendar,
        registry=registry,
        inputs=_truncate_inputs(inputs, cutoff_year),
    )

    full_past = (
        full.df.loc[full.df["crop_year"] <= compare_through]
        .sort_values(SPINE_NATURAL_KEY).reset_index(drop=True)
    )
    trunc_past = (
        truncated_result.df.loc[truncated_result.df["crop_year"] <= compare_through]
        .sort_values(SPINE_NATURAL_KEY).reset_index(drop=True)
    )

    if full_past.equals(trunc_past):
        logger.info(
            "PIT check PASSED for %s: %d past rows identical after truncation at %d",
            commodity, len(full_past), cutoff_year,
        )
        return True

    merged = full_past.merge(
        trunc_past, on=SPINE_NATURAL_KEY, how="outer",
        suffixes=("_full", "_trunc"), indicator=True,
    )
    mismatched = merged.loc[merged["_merge"] != "both"]
    value_diff = merged.loc[
        (merged["_merge"] == "both")
        & ~(
            (merged["value_full"] == merged["value_trunc"])
            | (merged["value_full"].isna() & merged["value_trunc"].isna())
        )
    ]
    logger.error(
        "PIT check FAILED for %s: %d row-presence diffs, %d value diffs — "
        "a feature is reading the future. Sample: %s",
        commodity, len(mismatched), len(value_diff),
        value_diff[SPINE_NATURAL_KEY].head(5).to_dict("records")
        or mismatched[SPINE_NATURAL_KEY].head(5).to_dict("records"),
    )
    return False


def _process_commodity(
    args: argparse.Namespace,
    commodity: str,
    crop_years: list[int],
    registry,
    calendars,
    git_sha: str,
    source_workers: int = 1,
) -> dict:
    result_log: dict = {"commodity": commodity, "status": "unknown", "rows": 0}

    countries = load_countries(commodity)
    if not countries:
        logger.warning("%s: no geography config — skipping", commodity)
        result_log["status"] = "skipped_no_geography"
        return result_log

    root = args.local_root if args.local_root else f"s3://{args.bucket}"
    load_plan = SourceLoadPlan(
        year_min=args.source_year_min,
        year_max=args.source_year_max,
        workers=max(1, int(source_workers)),
    )
    inputs, probes = extract_all(
        root, commodity, registry.sources_for(commodity), plan=load_plan
    )
    if not inputs:
        logger.warning("%s: no silver inputs found — skipping", commodity)
        result_log["status"] = "skipped_no_inputs"
        return result_log

    calendar = calendars.get(commodity) or default_calendar(commodity)
    build = build_spine(
        commodity=commodity,
        crop_years=crop_years,
        countries=countries,
        calendar=calendar,
        registry=registry,
        inputs=inputs,
    )
    result_log["rows"] = len(build.df)
    result_log["report"] = build.report

    if not build.passed:
        result_log["status"] = "validation_failed"
        return result_log

    if args.verify_pit and not _verify_point_in_time(
        build, commodity, crop_years, countries, calendar, registry, inputs
    ):
        result_log["status"] = "pit_check_failed"
        return result_log

    # Collect per-feature metadata for the catalog (before dry_run guard so
    # dry runs also report which features were computed).
    feature_meta = (
        build.df[["feature", "is_label"]]
        .drop_duplicates("feature")
        .set_index("feature")["is_label"]
        .to_dict()
    )
    result_log["feature_meta"] = {f: bool(b) for f, b in feature_meta.items()}
    result_log["feature_count"] = int(build.df["feature"].nunique())
    result_log["label_row_count"] = int(build.df["is_label"].sum())
    result_log["inputs"] = [_probe_dict(p) for p in probes]

    matrix_df = build_feature_matrix(build.df)
    result_log["matrix_rows"] = int(len(matrix_df))
    result_log["matrix_columns"] = int(len(matrix_df.columns))

    latest_keys = {
        "spine": _spine_key(commodity),
        "matrix": _matrix_key(commodity),
        "manifest": _manifest_key(commodity),
    }
    versioned_keys = {}
    if args.write_versioned:
        versioned_keys = {
            "spine": _spine_version_key(args, commodity),
            "matrix": _matrix_version_key(args, commodity),
            "manifest": _versioned_manifest_key(args, commodity),
        }
    result_log["latest_keys"] = latest_keys
    result_log["versioned_keys"] = versioned_keys

    manifest = {
        "task": "feature_spine_task",
        "commodity": commodity,
        "dataset_version": args.dataset_version if args.write_versioned else None,
        "built_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "git_sha": git_sha,
        "params_hash": registry.params_hash,
        "crop_years": [min(crop_years), max(crop_years)],
        "inputs": result_log["inputs"],
        "report": build.report,
        "matrix_key": latest_keys["matrix"],
        "matrix_version_key": versioned_keys.get("matrix"),
        "spine_key": latest_keys["spine"],
        "spine_version_key": versioned_keys.get("spine"),
        "versioned_only": bool(args.versioned_only),
    }

    buf = io.BytesIO()
    build.df.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
    spine_body = buf.getvalue()

    buf = io.BytesIO()
    matrix_df.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
    matrix_body = buf.getvalue()

    manifest_body = json.dumps(manifest, indent=2, default=str).encode()

    if args.dry_run:
        result_log["status"] = "dry_run"
        return result_log

    if args.write_versioned:
        for key in versioned_keys.values():
            _assert_absent(args, key)

    if not args.versioned_only:
        _write_bytes(args, latest_keys["spine"], spine_body, "application/octet-stream")
        _write_bytes(args, latest_keys["matrix"], matrix_body, "application/octet-stream")
        _write_bytes(args, latest_keys["manifest"], manifest_body, "application/json")
        logger.info("%-8s  cols=%-5d %s (latest feature matrix)", "written",
                    len(matrix_df.columns) - 2, commodity)

    if args.write_versioned:
        _write_bytes(args, versioned_keys["spine"], spine_body, "application/octet-stream")
        _write_bytes(args, versioned_keys["matrix"], matrix_body, "application/octet-stream")
        _write_bytes(args, versioned_keys["manifest"], manifest_body, "application/json")
        logger.info("%-8s  cols=%-5d %s (versioned feature matrix)",
                    "written", len(matrix_df.columns) - 2, commodity)

    result_log["status"] = "written"
    logger.info("%-8s  rows=%-7d %s", "written", len(build.df), commodity)
    return result_log


def _process_commodities(
    args: argparse.Namespace,
    commodities: list[str],
    crop_years: list[int],
    registry,
    calendars,
    git_sha: str,
) -> list[dict]:
    workers = max(1, int(args.workers))
    if len(commodities) <= 1 or workers <= 1:
        return [
            _process_commodity(
                args, c, crop_years, registry, calendars, git_sha,
                source_workers=workers,
            )
            for c in commodities
        ]

    results_by_commodity: dict[str, dict] = {}
    logger.info(
        "Processing %d commodities with %d worker threads",
        len(commodities), min(workers, len(commodities)),
    )
    with ThreadPoolExecutor(max_workers=min(workers, len(commodities))) as executor:
        future_to_commodity = {
            executor.submit(
                _process_commodity,
                args,
                commodity,
                crop_years,
                registry,
                calendars,
                git_sha,
                1,
            ): commodity
            for commodity in commodities
        }
        for future in as_completed(future_to_commodity):
            commodity = future_to_commodity[future]
            try:
                results_by_commodity[commodity] = future.result()
            except Exception as exc:  # noqa: BLE001 - keep processing other commodities
                logger.exception("%s: commodity build failed", commodity)
                results_by_commodity[commodity] = {
                    "commodity": commodity,
                    "status": "error",
                    "rows": 0,
                    "error": str(exc),
                }
    return [results_by_commodity[c] for c in commodities]


def _probe_dict(probe: SourceProbe) -> dict:
    return {
        "source": probe.source_key,
        "location": probe.location,
        "exists": probe.exists,
        "num_files": probe.num_files,
        "num_rows": probe.num_rows,
        "files": list(probe.files),
    }


def _build_dataset_manifest(
    args: argparse.Namespace,
    *,
    commodities: list[str],
    crop_years: list[int],
    git_sha: str,
    registry,
    results: list[dict],
    source_certification: dict,
) -> dict:
    summaries = []
    source_summary: dict[str, dict[str, int]] = defaultdict(
        lambda: {"num_files": 0, "num_rows": 0, "seen_in_commodities": 0}
    )

    for result in results:
        summary = {
            "commodity": result.get("commodity"),
            "status": result.get("status"),
            "rows": int(result.get("rows", 0)),
            "feature_count": int(result.get("feature_count", 0)),
            "label_row_count": int(result.get("label_row_count", 0)),
            "matrix_rows": int(result.get("matrix_rows", 0)),
            "matrix_columns": int(result.get("matrix_columns", 0)),
            "latest_keys": result.get("latest_keys", {}),
            "versioned_keys": result.get("versioned_keys", {}),
            "report": result.get("report", {}),
            "error": result.get("error"),
        }
        summaries.append(summary)
        for probe in result.get("inputs", []):
            source = str(probe.get("source", "unknown"))
            row_count = int(probe.get("num_rows") or 0)
            source_summary[source]["num_files"] += int(probe.get("num_files") or 0)
            source_summary[source]["num_rows"] += max(0, row_count)
            source_summary[source]["seen_in_commodities"] += 1

    written = [r for r in summaries if r["status"] == "written"]
    dry = [r for r in summaries if r["status"] == "dry_run"]
    skipped = [r for r in summaries if str(r["status"]).startswith("skipped")]
    failed = [
        r for r in summaries
        if r["status"] in ("validation_failed", "pit_check_failed", "error")
    ]

    return {
        "task": "feature_spine_task",
        "dataset_kind": "legacy_gold_feature_spine_version",
        "dataset_version": args.dataset_version,
        "built_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "git_sha": git_sha,
        "params_hash": registry.params_hash,
        "config_fingerprints": _config_fingerprints(),
        "source_certification": source_certification,
        "crop_years": [min(crop_years), max(crop_years)],
        "source_years": [
            getattr(args, "source_year_min", None),
            getattr(args, "source_year_max", None),
        ],
        "workers": int(getattr(args, "workers", 1)),
        "requested_commodities": commodities,
        "summary": {
            "requested_commodity_count": len(commodities),
            "written_count": len(written),
            "dry_run_count": len(dry),
            "skipped_count": len(skipped),
            "failed_count": len(failed),
            "total_spine_rows": sum(r["rows"] for r in written),
            "total_label_rows": sum(r["label_row_count"] for r in written),
            "total_matrix_rows": sum(r["matrix_rows"] for r in written),
        },
        "source_summary": dict(sorted(source_summary.items())),
        "commodities": summaries,
        "outputs": {
            "feature_spine_prefix": (
                f"gold/feature_spine_versions/dataset_version={args.dataset_version}/"
            ),
            "feature_matrix_prefix": (
                f"gold/feature_matrix_versions/dataset_version={args.dataset_version}/"
            ),
            "feature_catalog_key": _catalog_version_key(args),
            "manifest_key": _dataset_manifest_key(args),
        },
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="silver/* to gold/feature_spine")
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    parser.add_argument(
        "--local-root", default=None, dest="local_root",
        help="Read/write a local directory instead of S3 (testing).",
    )
    parser.add_argument(
        "--commodity", action="append", default=None,
        help=(
            "Limit to specific commodities (repeatable); default = all with geography. "
            "Use --commodity all to force all commodities through Batch parameters."
        ),
    )
    parser.add_argument("--start-crop-year", type=int,
                        default=_DEFAULT_START_CROP_YEAR, dest="start_crop_year")
    parser.add_argument("--end-crop-year", type=int, default=None, dest="end_crop_year")
    parser.add_argument(
        "--workers", type=int, default=4,
        help=(
            "Internal worker threads. Single-commodity jobs parallelize source "
            "extraction; multi-commodity jobs parallelize commodities."
        ),
    )
    parser.add_argument(
        "--source-year-min", type=_optional_int_arg, default=None, dest="source_year_min",
        help="Optional lower bound for partitioned source reads; smoke/debug only.",
    )
    parser.add_argument(
        "--source-year-max", type=_optional_int_arg, default=None, dest="source_year_max",
        help="Optional upper bound for partitioned source reads; smoke/debug only.",
    )
    parser.add_argument("--dry-run", action="store_true", default=False)
    parser.add_argument(
        "--verify-pit", action="store_true", default=False, dest="verify_pit",
        help="Rebuild with inputs truncated at T and assert the past is unchanged.",
    )
    parser.add_argument(
        "--dataset-version", default=None, dest="dataset_version",
        help=(
            "Immutable dataset version for gold/feature_*_versions. "
            "Defaults to YYYYMMDDTHHMMSSZ_<git_sha> when versioned writes are enabled."
        ),
    )
    parser.add_argument(
        "--write-versioned", nargs="?", const=True, default=False, type=_bool_arg,
        dest="write_versioned",
        help="Also write immutable gold feature spine/matrix/catalog version outputs.",
    )
    parser.add_argument(
        "--versioned-only", nargs="?", const=True, default=False, type=_bool_arg,
        dest="versioned_only",
        help="Write only immutable versioned outputs; leave mutable latest paths untouched.",
    )
    parser.add_argument(
        "--fail-if-version-exists", nargs="?", const=True, default=True, type=_bool_arg,
        dest="fail_if_version_exists",
        help="Refuse to overwrite existing immutable versioned objects.",
    )
    parser.add_argument(
        "--source-certification-report", default="", dest="source_certification_report",
        help="Local path, S3 URI, or bucket key for the Phase 2 source certification report.",
    )
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        stream=sys.stderr,
    )
    load_env()
    args = _parse_args()

    if args.versioned_only:
        args.write_versioned = True
    if args.dataset_version and args.dataset_version.strip().lower() in {"none", "null"}:
        args.dataset_version = None
    if (
        args.source_certification_report
        and args.source_certification_report.strip().lower() in {"none", "null"}
    ):
        args.source_certification_report = ""

    if not args.local_root:
        args.bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
        args.aws_region = args.aws_region or get_required_env("AWS_REGION")

    end_year = args.end_crop_year or datetime.date.today().year
    crop_years = list(range(args.start_crop_year, end_year + 1))

    registry = load_registry()
    calendars = load_crop_calendars()
    git_sha = _git_sha()
    args.workers = max(1, int(args.workers))
    computed_source_year_min, computed_source_year_max = _source_year_bounds(
        crop_years, registry
    )
    if args.source_year_min is None:
        args.source_year_min = computed_source_year_min
    if args.source_year_max is None:
        args.source_year_max = computed_source_year_max
    if args.write_versioned and not args.dataset_version:
        args.dataset_version = _default_dataset_version(git_sha)
    source_certification = (
        _source_certification_metadata(args) if args.write_versioned else {"provided": False}
    )

    if args.commodity and [c.lower() for c in args.commodity] != ["all"]:
        commodities = args.commodity
    else:
        from leviathan.common.constants import ALL_COMMODITIES
        commodities = [c for c in ALL_COMMODITIES if load_countries(c)]

    logger.info(
        (
            "Feature spine task  commodities=%d  crop_years=%d-%d  dry_run=%s  "
            "verify_pit=%s  write_versioned=%s  versioned_only=%s  "
            "dataset_version=%s  workers=%d  source_years=%d-%d"
        ),
        len(commodities), crop_years[0], crop_years[-1], args.dry_run,
        args.verify_pit, args.write_versioned, args.versioned_only,
        args.dataset_version, args.workers, args.source_year_min, args.source_year_max,
    )

    results = _process_commodities(
        args, commodities, crop_years, registry, calendars, git_sha
    )

    written = sum(1 for r in results if r["status"] == "written")
    dry = sum(1 for r in results if r["status"] == "dry_run")
    skipped = sum(1 for r in results if r["status"].startswith("skipped"))
    failed = sum(1 for r in results
                 if r["status"] in ("validation_failed", "pit_check_failed", "error"))

    # Build and write the feature catalog from observed feature→commodity
    # membership across all successfully written commodities.
    feature_commodity_map: dict[str, set[str]] = defaultdict(set)
    feature_is_label: dict[str, bool] = {}
    written_commodities: set[str] = set()

    for r in results:
        if r["status"] in ("written", "dry_run") and r.get("feature_meta"):
            slug = r["commodity"]
            if r["status"] == "written":
                written_commodities.add(slug)
            for feat, is_lbl in r["feature_meta"].items():
                feature_commodity_map[feat].add(slug)
                feature_is_label[feat] = is_lbl

    if feature_commodity_map and not args.dry_run and written_commodities:
        catalog_df = build_feature_catalog(
            feature_commodity_map, feature_is_label, written_commodities
        )
        buf = io.BytesIO()
        catalog_df.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
        catalog_body = buf.getvalue()
        if not args.versioned_only:
            _write_bytes(args, _CATALOG_KEY, catalog_body, "application/octet-stream")
        if args.write_versioned:
            catalog_key = _catalog_version_key(args)
            _assert_absent(args, catalog_key)
            _write_bytes(args, catalog_key, catalog_body, "application/octet-stream")
        logger.info(
            "Feature catalog written: %d features (%d universal, %d group, %d commodity-specific)",
            len(catalog_df),
            (catalog_df["scope"] == "universal").sum(),
            (catalog_df["scope"] == "group").sum(),
            (catalog_df["scope"] == "commodity").sum(),
        )

    if args.write_versioned and not args.dry_run and written:
        manifest_key = _dataset_manifest_key(args)
        _assert_absent(args, manifest_key)
        dataset_manifest = _build_dataset_manifest(
            args,
            commodities=commodities,
            crop_years=crop_years,
            git_sha=git_sha,
            registry=registry,
            results=results,
            source_certification=source_certification,
        )
        _write_bytes(
            args,
            manifest_key,
            json.dumps(dataset_manifest, indent=2, default=str).encode(),
            "application/json",
        )
        logger.info("Dataset manifest written: %s", manifest_key)

    logger.info("Done  written=%d  dry_run=%d  skipped=%d  failed=%d",
                written, dry, skipped, failed)
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
