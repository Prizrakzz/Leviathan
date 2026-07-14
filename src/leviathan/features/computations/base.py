"""Shared context object and helpers for feature computations.

Every computation is a pure function ``(FeatureContext, FeatureSpec) -> DataFrame``
returning long-format rows ``[country, crop_year, feature, value]``.  No S3, no
AWS, no side effects — fully unit-testable with synthetic frames.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from leviathan.features.calendar import CropCalendar

RESULT_COLUMNS = ["country", "crop_year", "feature", "value"]


@dataclass
class FeatureContext:
    """Inputs available to one commodity's feature computations."""
    commodity: str
    crop_years: list[int]
    countries: list[str]
    calendar: CropCalendar | None
    inputs: dict[str, pd.DataFrame] = field(default_factory=dict)
    params: dict = field(default_factory=dict)


def empty_result() -> pd.DataFrame:
    return pd.DataFrame(columns=RESULT_COLUMNS)


def make_result(rows: list[tuple[str, int, str, float]]) -> pd.DataFrame:
    """Build a result frame, dropping NaN values (absence == missing in long format)."""
    if not rows:
        return empty_result()
    df = pd.DataFrame(rows, columns=RESULT_COLUMNS)
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df.dropna(subset=["value"]).reset_index(drop=True)


def assign_crop_year(df: pd.DataFrame, calendar: CropCalendar) -> pd.Series:
    """Vectorized crop-year assignment for a silver weather frame.

    A row dated in month ``m`` of calendar year ``y`` belongs to crop year
    ``y`` when ``m >= crop_year_start_month``, else ``y - 1`` (the crop year
    whose 12-month span contains the date).
    """
    year = pd.to_numeric(df["year"], errors="coerce").astype("Int64")
    month = pd.to_numeric(df["month"], errors="coerce").astype("Int64")
    return (year - (month < calendar.crop_year_start_month).astype(int)).astype("Int64")


def stage_month_set(start_month: int, end_month: int) -> set[int]:
    """Inclusive month set for a stage window; handles calendar-year wrap."""
    if start_month <= end_month:
        return set(range(start_month, end_month + 1))
    return set(range(start_month, 13)) | set(range(1, end_month + 1))


def trailing_baseline_z(
    yearly: pd.Series,
    window_years: int,
    min_years: int,
) -> pd.Series:
    """Z-score of each year's value vs. the TRAILING baseline of prior years.

    ``z[Y] = (x[Y] - mean(x[Y-window..Y-1])) / std(x[Y-window..Y-1])``

    The baseline excludes the observation year itself (shift before rolling),
    so the feature for year Y never sees Y or any later year — the property the
    truncate-at-T anti-leakage test asserts.  Fewer than *min_years* prior
    observations, or zero baseline variance, yield NaN.
    """
    yearly = yearly.sort_index()
    prior_mean = yearly.shift(1).rolling(window_years, min_periods=min_years).mean()
    prior_std = yearly.shift(1).rolling(window_years, min_periods=min_years).std()
    z = (yearly - prior_mean) / prior_std
    return z.replace([np.inf, -np.inf], np.nan)


def max_consecutive_true(mask: np.ndarray) -> int:
    """Longest run of True in a boolean array (0 for empty/all-False)."""
    if mask.size == 0:
        return 0
    best = run = 0
    for flag in mask:
        run = run + 1 if flag else 0
        if run > best:
            best = run
    return best


# The climatological dry-day floor (mm/day). CHIRPS daily precipitation is heavily
# zero-inflated outside the always-wet tropics (78% zero days on the corn belt): the
# bottom-percentile threshold of such a baseline is 0.0 and a day can never be STRICTLY
# below zero rain, so every dry-run degenerates to 0 and the run z-score dies on zero
# variance (BF-W1 live find: drought_z emitted for only 4/31 commodities). The standard
# convention treats a day under ~1 mm as dry; the floor binds ONLY where the percentile
# degenerates below it, so genuinely wet climatologies keep their relative threshold.
DRY_DAY_FLOOR_MM = 1.0


def dry_day_threshold(baseline: np.ndarray, percentile: float) -> float:
    """The dry-day precipitation threshold for a baseline sample: the requested
    bottom-``percentile`` value, floored at :data:`DRY_DAY_FLOOR_MM`.

    Shared by the feature-layer ``compute_drought_z`` and the gold ``weather_z``
    mirror so the two definitions cannot drift."""
    return max(float(np.percentile(baseline, percentile)), DRY_DAY_FLOOR_MM)
