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
import io
import json
import logging
import subprocess
import sys

import pandas as pd
from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.features.calendar import load_crop_calendars
from leviathan.features.extractors import SourceProbe, extract_all
from leviathan.features.registry import load_registry
from leviathan.features.spine import (
    SPINE_NATURAL_KEY,
    SpineBuildResult,
    build_spine,
    default_calendar,
    load_countries,
)
from leviathan.storage.s3 import get_thread_local_s3_client

logger = get_logger("feature_spine_task")

_SPINE_PREFIX = "gold/feature_spine"
_DEFAULT_START_CROP_YEAR = 1981
# Crop years compared by --verify-pit must have windows that fully precede the
# truncation cutoff; a 2-year guard covers windows that span calendar years.
_PIT_BOUNDARY_GUARD_YEARS = 2


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL, text=True
        ).strip()
    except Exception:  # noqa: BLE001 — git absent inside the container is fine
        return "unknown"


def _spine_key(commodity: str) -> str:
    return f"{_SPINE_PREFIX}/commodity={commodity}/part-000.parquet"


def _manifest_key(commodity: str) -> str:
    return f"{_SPINE_PREFIX}/_manifests/commodity={commodity}/run.json"


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
) -> dict:
    result_log: dict = {"commodity": commodity, "status": "unknown", "rows": 0}

    countries = load_countries(commodity)
    if not countries:
        logger.warning("%s: no geography config — skipping", commodity)
        result_log["status"] = "skipped_no_geography"
        return result_log

    root = args.local_root if args.local_root else f"s3://{args.bucket}"
    inputs, probes = extract_all(root, commodity, registry.sources_for(commodity))
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

    if args.dry_run:
        result_log["status"] = "dry_run"
        return result_log

    buf = io.BytesIO()
    build.df.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
    _write_bytes(args, _spine_key(commodity), buf.getvalue(),
                 "application/octet-stream")

    manifest = {
        "task": "feature_spine_task",
        "commodity": commodity,
        "built_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "git_sha": git_sha,
        "params_hash": registry.params_hash,
        "crop_years": [min(crop_years), max(crop_years)],
        "inputs": [_probe_dict(p) for p in probes],
        "report": build.report,
    }
    _write_bytes(args, _manifest_key(commodity),
                 json.dumps(manifest, indent=2, default=str).encode(),
                 "application/json")

    result_log["status"] = "written"
    logger.info("%-8s  rows=%-7d %s", "written", len(build.df), commodity)
    return result_log


def _probe_dict(probe: SourceProbe) -> dict:
    return {
        "source": probe.source_key,
        "location": probe.location,
        "exists": probe.exists,
        "num_files": probe.num_files,
        "num_rows": probe.num_rows,
        "files": list(probe.files),
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="silver/* → gold/feature_spine")
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    parser.add_argument(
        "--local-root", default=None, dest="local_root",
        help="Read/write a local directory instead of S3 (testing).",
    )
    parser.add_argument(
        "--commodity", action="append", default=None,
        help="Limit to specific commodities (repeatable); default = all with geography.",
    )
    parser.add_argument("--start-crop-year", type=int,
                        default=_DEFAULT_START_CROP_YEAR, dest="start_crop_year")
    parser.add_argument("--end-crop-year", type=int, default=None, dest="end_crop_year")
    parser.add_argument("--dry-run", action="store_true", default=False)
    parser.add_argument(
        "--verify-pit", action="store_true", default=False, dest="verify_pit",
        help="Rebuild with inputs truncated at T and assert the past is unchanged.",
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

    if not args.local_root:
        args.bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
        args.aws_region = args.aws_region or get_required_env("AWS_REGION")

    end_year = args.end_crop_year or datetime.date.today().year
    crop_years = list(range(args.start_crop_year, end_year + 1))

    registry = load_registry()
    calendars = load_crop_calendars()
    git_sha = _git_sha()

    if args.commodity:
        commodities = args.commodity
    else:
        from leviathan.common.constants import ALL_COMMODITIES
        commodities = [c for c in ALL_COMMODITIES if load_countries(c)]

    logger.info(
        "Feature spine task  commodities=%d  crop_years=%d-%d  dry_run=%s  verify_pit=%s",
        len(commodities), crop_years[0], crop_years[-1], args.dry_run, args.verify_pit,
    )

    results = [
        _process_commodity(args, c, crop_years, registry, calendars, git_sha)
        for c in commodities
    ]

    written = sum(1 for r in results if r["status"] == "written")
    dry = sum(1 for r in results if r["status"] == "dry_run")
    skipped = sum(1 for r in results if r["status"].startswith("skipped"))
    failed = sum(1 for r in results
                 if r["status"] in ("validation_failed", "pit_check_failed"))

    logger.info("Done  written=%d  dry_run=%d  skipped=%d  failed=%d",
                written, dry, skipped, failed)
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
