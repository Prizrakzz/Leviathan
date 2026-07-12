"""WIDE-schema silver quality checks for NASA POWER (SILVER-F021).

The shared ``leviathan.common.quality.run_silver_quality_checks`` hard-codes the LONG weather schema
(it requires ``variable`` + ``value`` + ``commodity`` columns). The canonical silver_nasa_power table
is WIDE (one measurement column per variable, ``commodity`` is a path-only partition), so the LONG
runner cannot validate it -- it would false-fail on ``missing_columns``. This module is the wide-schema
equivalent: same HARD failure taxonomy (missing columns, required-null, dtype, duplicate natural key),
same SOFT range warnings, but evaluated against the wide measurement columns. It reuses the shared
``SILVER_VARIABLE_RANGES`` so the physical bounds are one authority.

Pure + AWS-free + ASCII only.
"""
from __future__ import annotations

import datetime

import pandas as pd

from leviathan.common.logging import get_logger
from leviathan.common.quality import SILVER_VARIABLE_RANGES
from leviathan.transforms.bronze_to_silver._weather_schema import NASA_WIDE_MEASURE_COLS

logger = get_logger(__name__)

# The WIDE silver schema (matches nasa_power_weather.WIDE_OUTPUT_COLS). ``commodity`` lives only in the
# S3 path, so it is intentionally NOT a required output column.
WIDE_REQUIRED_COLUMNS = [
    "date", "year", "month", "day", "country", "region", "source", "ingest_date", "source_file_name",
] + NASA_WIDE_MEASURE_COLS
WIDE_REQUIRED_NON_NULL = ["date", "year", "month", "day", "country", "region", "source"]
# One row per (date, country, region, source) within the commodity partition.
WIDE_NATURAL_KEY = ["date", "country", "region", "source"]


def check_wide_required_columns(df: pd.DataFrame) -> list[str]:
    return [c for c in WIDE_REQUIRED_COLUMNS if c not in df.columns]


def check_wide_required_nulls(df: pd.DataFrame) -> dict[str, int]:
    out: dict[str, int] = {}
    for col in WIDE_REQUIRED_NON_NULL:
        if col in df.columns:
            n = int(df[col].isna().sum())
            if n:
                out[col] = n
    return out


def check_wide_dtypes(df: pd.DataFrame) -> list[str]:
    issues: list[str] = []
    for col in ("year", "month", "day"):
        if col in df.columns and not pd.api.types.is_integer_dtype(df[col]):
            issues.append(f"{col} not integer-typed ({df[col].dtype})")
    for col in NASA_WIDE_MEASURE_COLS:
        if col in df.columns and not pd.api.types.is_numeric_dtype(df[col]):
            issues.append(f"{col} not numeric-typed ({df[col].dtype})")
    return issues


def check_wide_duplicates(df: pd.DataFrame) -> int:
    key = [c for c in WIDE_NATURAL_KEY if c in df.columns]
    if len(key) != len(WIDE_NATURAL_KEY):
        return 0
    return int(df.duplicated(subset=key).sum())


def check_wide_ranges(df: pd.DataFrame) -> dict[str, dict]:
    """Soft range warnings over the wide measurement columns (never hard-fail)."""
    out: dict[str, dict] = {}
    for col in NASA_WIDE_MEASURE_COLS:
        if col not in df.columns:
            continue
        low, high = SILVER_VARIABLE_RANGES.get(col, (None, None))
        vals = pd.to_numeric(df[col], errors="coerce").dropna()
        if vals.empty:
            continue
        bad = 0
        if low is not None:
            bad += int((vals < low).sum())
        if high is not None:
            bad += int((vals > high).sum())
        if bad:
            out[col] = {"out_of_range_count": bad, "observed_min": float(vals.min()),
                        "observed_max": float(vals.max()), "expected_min": low, "expected_max": high}
    return out


def run_wide_weather_quality_checks(df: pd.DataFrame, commodity: str, source: str) -> dict:
    """Wide-schema equivalent of run_silver_quality_checks. ``passed`` is False on any HARD failure."""
    hard: dict = {}
    report = {
        "commodity": commodity, "source": source,
        "checked_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "row_count": len(df), "passed": True, "hard_failures": hard, "warnings": {},
        "schema": "wide",
    }
    missing = check_wide_required_columns(df)
    if missing:
        hard["missing_columns"] = missing
        report["passed"] = False
    nulls = check_wide_required_nulls(df)
    if nulls:
        hard["required_nulls"] = nulls
        report["passed"] = False
    dtypes = check_wide_dtypes(df)
    if dtypes:
        hard["dtype_mismatch"] = dtypes
        report["passed"] = False
    dups = check_wide_duplicates(df)
    if dups:
        hard["duplicate_natural_keys"] = dups
        report["passed"] = False
    ranges = check_wide_ranges(df)
    if ranges:
        report["warnings"]["range_violations"] = ranges
        for var, info in ranges.items():
            logger.warning("[%s/%s] wide range violation: '%s' %d out-of-range (min=%s max=%s)",
                           source, commodity, var, info["out_of_range_count"],
                           info["observed_min"], info["observed_max"])
    return report
