"""Shared types for the leviathan pipeline.

Import these instead of repeating inline TypedDict / Literal definitions
across modules.
"""
from __future__ import annotations

from typing import Literal, TypedDict

# ProcessResult is the return type used by base_jobs worker methods.
# "success" = written, "skipped" = already existed, "failed" = dead-lettered.
ProcessResult = tuple[Literal["success", "failed", "skipped"], str]

# A single geographic sampling location loaded from a commodity's regions YAML.
class Region(TypedDict):
    country: str
    region: str
    latitude: float
    longitude: float


# ---------------------------------------------------------------------------
# Quality report types (leviathan.common.quality)
# ---------------------------------------------------------------------------

class RangeViolation(TypedDict):
    """Per-variable range-violation summary returned by check_value_ranges."""
    out_of_range_count: int
    observed_min: float
    observed_max: float
    expected_min: float | None
    expected_max: float | None


class QualityReportHardFailures(TypedDict, total=False):
    """Hard-failure fields in a QualityReport (all optional — absent means no failure)."""
    missing_columns: list[str]
    required_nulls: dict[str, int]
    dtype_mismatch: list[str]
    duplicate_natural_keys: int


class QualityReportWarnings(TypedDict, total=False):
    """Warning fields in a QualityReport (all optional — absent means no warning)."""
    range_violations: dict[str, RangeViolation]
    missing_countries: list[str]


class QualityReport(TypedDict):
    """Structured quality-check report returned by run_silver_quality_checks."""
    commodity: str
    source: str
    checked_at: str
    row_count: int
    passed: bool
    hard_failures: QualityReportHardFailures
    warnings: QualityReportWarnings


# ---------------------------------------------------------------------------
# Schema types (leviathan.common.validation)
# ---------------------------------------------------------------------------

class SchemaDict(TypedDict, total=False):
    """Schema definition loaded from a leviathan.schemas YAML file.

    All keys are optional because different source types use different subsets
    (e.g. 'required_path' is JSON-only; 'required_columns' is DataFrame-only).
    """
    source: str
    type: str
    required_path: str
    required_parameters: list[str]
    date_key_length: int
    required_columns: list[str]
    expected_elements: list[str]
    year_col: str
    min_year: int


# ---------------------------------------------------------------------------
# NASA POWER API response types (leviathan.ingestion.weather.nasa_power)
# ---------------------------------------------------------------------------

class NasaPowerProperties(TypedDict):
    """'properties' block of the NASA POWER GeoJSON point response."""
    parameter: dict[str, dict[str, float | int | None]]


class NasaPowerPayload(TypedDict):
    """Top-level NASA POWER daily point API response (fields we actually access)."""
    properties: NasaPowerProperties


