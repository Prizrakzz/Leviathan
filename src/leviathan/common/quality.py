"""Silver-layer data quality checks for Leviathan.

Provides a set of targeted check functions and a top-level runner
``run_silver_quality_checks`` that executes all checks and returns a
structured quality report dict.

Hard failures (``report["passed"] == False``):
- Missing required columns
- Nulls in required non-null columns (date, country, commodity, source,
  variable, value)
- Wrong dtype for key numeric columns (year, month, day, value)
- Duplicate natural-key rows

Soft failures (WARNING logged, included in report but ``passed`` stays True):
- Variable values outside expected physical ranges
- Expected countries missing from output

Usage
-----
    from leviathan.common.quality import run_silver_quality_checks, write_quality_report_to_s3

    report = run_silver_quality_checks(silver_df, commodity, source, expected_countries)
    write_quality_report_to_s3(report, bucket, source, commodity, aws_region)
    if not report["passed"]:
        raise RuntimeError(f"Silver quality failed: {report['hard_failures']}")
"""
from __future__ import annotations

import datetime
import json

import pandas as pd

from leviathan.common.logging import get_logger
from leviathan.common.types import (
    QualityReport,
    QualityReportHardFailures,
    QualityReportWarnings,
    RangeViolation,
)

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SILVER_VARIABLE_RANGES: dict[str, tuple[float | None, float | None]] = {
    "precipitation_mm":          (0.0,   2000.0),
    "temperature_2m_mean_c":     (-80.0,   60.0),
    "temperature_2m_max_c":      (-80.0,   60.0),
    "temperature_2m_min_c":      (-80.0,   60.0),
    "relative_humidity_2m_pct":  (0.0,   100.0),
    "wind_speed_2m_m_s":         (0.0,   120.0),
    "solar_radiation_mj_m2_day": (0.0,    50.0),
    "production_quantity":       (0.0,     None),
    "area_harvested":            (0.0,     None),
    "yield":                     (0.0,     None),
}

# Columns that must have zero null values in any silver partition.
SILVER_REQUIRED_NON_NULL: list[str] = [
    "date", "country", "commodity", "source", "variable", "value",
]

# Natural key uniquely identifying a single measurement.
SILVER_NATURAL_KEY: list[str] = [
    "date", "country", "region", "commodity", "source", "variable",
]

# Minimum set of columns every silver partition must contain.
SILVER_REQUIRED_COLUMNS: list[str] = [
    "date", "year", "month", "day", "country", "region",
    "commodity", "source", "ingest_date", "variable", "value",
]

# Expected pandas dtype category per column ("int" or "float").
SILVER_EXPECTED_DTYPES: dict[str, str] = {
    "year":  "int",
    "month": "int",
    "day":   "int",
    "value": "float",
}


class QualityCheckError(Exception):
    """Raised by callers when a silver quality report contains hard failures."""


# ---------------------------------------------------------------------------
# Individual check functions
# ---------------------------------------------------------------------------

def check_required_columns(df: pd.DataFrame) -> list[str]:
    """Return names of required columns that are absent from *df*."""
    return [c for c in SILVER_REQUIRED_COLUMNS if c not in df.columns]


def check_required_nulls(df: pd.DataFrame) -> dict[str, int]:
    """Return ``{column: null_count}`` for required non-null columns that have nulls."""
    result: dict[str, int] = {}
    for col in SILVER_REQUIRED_NON_NULL:
        if col in df.columns:
            count = int(df[col].isna().sum())
            if count > 0:
                result[col] = count
    return result


def check_data_types(df: pd.DataFrame) -> list[str]:
    """Return names of columns whose dtype kind does not match ``SILVER_EXPECTED_DTYPES``."""
    mismatched: list[str] = []
    for col, expected_kind in SILVER_EXPECTED_DTYPES.items():
        if col not in df.columns:
            continue
        actual_kind = df[col].dtype.kind
        if expected_kind == "int" and actual_kind not in ("i", "u"):
            mismatched.append(col)
        elif expected_kind == "float" and actual_kind != "f":
            mismatched.append(col)
    return mismatched


def check_deduplication(df: pd.DataFrame) -> int:
    """Return the number of duplicate rows on ``SILVER_NATURAL_KEY`` (should be 0)."""
    key_cols = [c for c in SILVER_NATURAL_KEY if c in df.columns]
    if not key_cols:
        return 0
    return int(df.duplicated(subset=key_cols).sum())


def check_value_ranges(df: pd.DataFrame) -> dict[str, RangeViolation]:
    """Return per-variable range-violation summaries for the silver long format.

    Only variables that have out-of-range rows are included in the result.
    Each entry contains: ``out_of_range_count``, ``observed_min``,
    ``observed_max``, ``expected_min``, ``expected_max``.
    """
    if "variable" not in df.columns or "value" not in df.columns:
        return {}
    violations: dict[str, RangeViolation] = {}
    for variable, (low, high) in SILVER_VARIABLE_RANGES.items():
        subset = df.loc[df["variable"] == variable, "value"].dropna()
        if subset.empty:
            continue
        mask = pd.Series(True, index=subset.index)
        if low is not None:
            mask &= subset >= low
        if high is not None:
            mask &= subset <= high
        out_of_range = int((~mask).sum())
        if out_of_range > 0:
            violations[variable] = {
                "out_of_range_count": out_of_range,
                "observed_min": float(subset.min()),
                "observed_max": float(subset.max()),
                "expected_min": low,
                "expected_max": high,
            }
    return violations


def check_expected_entities(
    df: pd.DataFrame,
    expected_countries: list[str],
) -> list[str]:
    """Return expected country keys that do not appear in *df*."""
    if "country" not in df.columns or not expected_countries:
        return []
    present = set(df["country"].dropna().unique())
    return [c for c in expected_countries if c not in present]


# ---------------------------------------------------------------------------
# Top-level runner
# ---------------------------------------------------------------------------

def run_silver_quality_checks(
    df: pd.DataFrame,
    commodity: str,
    source: str,
    expected_countries: list[str] | None = None,
) -> QualityReport:
    """Run all silver quality checks and return a structured quality report dict.

    The report is always returned (even on failure) so the caller can persist it
    before deciding whether to abort.  Set ``report["passed"]`` to ``False``
    means one or more hard checks failed; the caller should raise
    :exc:`QualityCheckError` (or equivalent) in that case.

    Args:
        df:                 Silver DataFrame to validate.
        commodity:          Commodity identifier for report metadata.
        source:             Source identifier for report metadata.
        expected_countries: Optional list of country keys that must appear.

    Returns:
        Quality report dict suitable for JSON serialisation.
    """
    hard_failures: QualityReportHardFailures = {}
    warnings_dict: QualityReportWarnings = {}
    report: QualityReport = {
        "commodity": commodity,
        "source": source,
        "checked_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "row_count": len(df),
        "passed": True,
        "hard_failures": hard_failures,
        "warnings": warnings_dict,
    }

    # ---- Hard checks --------------------------------------------------------
    missing_cols = check_required_columns(df)
    if missing_cols:
        hard_failures["missing_columns"] = missing_cols
        report["passed"] = False

    null_counts = check_required_nulls(df)
    if null_counts:
        hard_failures["required_nulls"] = null_counts
        report["passed"] = False

    dtype_issues = check_data_types(df)
    if dtype_issues:
        hard_failures["dtype_mismatch"] = dtype_issues
        report["passed"] = False

    dup_count = check_deduplication(df)
    if dup_count > 0:
        hard_failures["duplicate_natural_keys"] = dup_count
        report["passed"] = False

    # ---- Soft checks --------------------------------------------------------
    range_violations = check_value_ranges(df)
    if range_violations:
        warnings_dict["range_violations"] = range_violations
        for var, info in range_violations.items():
            logger.warning(
                "[%s/%s] Range violation: '%s' has %d out-of-range values "
                "(observed min=%s, max=%s; expected [%s, %s])",
                source, commodity, var,
                info["out_of_range_count"],
                info["observed_min"], info["observed_max"],
                info["expected_min"], info["expected_max"],
            )

    if expected_countries:
        missing_entities = check_expected_entities(df, expected_countries)
        if missing_entities:
            warnings_dict["missing_countries"] = missing_entities
            logger.warning(
                "[%s/%s] Expected countries absent from silver output: %s",
                source, commodity, missing_entities,
            )

    return report


# ---------------------------------------------------------------------------
# S3 report writer
# ---------------------------------------------------------------------------

def write_quality_report_to_s3(
    report: QualityReport,
    bucket: str,
    source: str,
    commodity: str,
    aws_region: str = "us-east-1",
) -> str:
    """Write *report* as a JSON file to S3 under ``quality/silver/``.

    Returns the S3 key that was written.  Failures are logged but not re-raised
    so that a report-write failure does not mask the underlying quality result.
    """
    import boto3  # noqa: PLC0415 — lazy import; avoids boto3 dep at module load in unit tests
    from botocore.config import Config  # noqa: PLC0415

    ts = (
        datetime.datetime.now(datetime.timezone.utc)
        .isoformat()
        .replace(":", "-")
        .replace("+", "Z")
        .split(".")[0]
        + "Z"
    )
    key = f"quality/silver/source={source}/commodity={commodity}/{ts}_report.json"
    try:
        boto3.client(
            "s3",
            region_name=aws_region,
            config=Config(retries={"max_attempts": 3, "mode": "standard"}),
        ).put_object(
            Body=json.dumps(report, indent=2, default=str).encode("utf-8"),
            Bucket=bucket,
            Key=key,
            ContentType="application/json",
        )
        logger.info("Wrote silver quality report: s3://%s/%s", bucket, key)
    except Exception:  # noqa: BLE001 — non-critical S3 write; any failure is logged but does not abort the job
        logger.exception("Failed to write silver quality report for %s/%s — continuing", source, commodity)
    return key
