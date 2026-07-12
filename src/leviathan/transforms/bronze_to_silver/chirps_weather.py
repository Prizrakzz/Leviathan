"""bronze -> silver CHIRPS precipitation (LONG) + typed availability (SILVER-F044 narrowed).

F044 (narrowed to AVAILABILITY only; the all-NaN VALUE defect is SILVER-F045): a physical silver
partition must exist ONLY when >= 1 valid source observation exists. A 404 / not-yet-published date is
a typed *availability* result, never an all-null-filled map. The long transform already drops rows with
a null ``value`` (so an all-missing bronze melts to an empty frame and the writer creates no object),
which satisfies the existence rule; F044 makes the classification EXPLICIT and typed so a caller can
distinguish "published, real data" from "not yet published / empty" instead of inferring it from a row
count. It does NOT touch value validity -- a bronze that is present-but-all-NaN is F045's rebuild.
"""
from __future__ import annotations

from enum import Enum

import pandas as pd

from leviathan.common.logging import get_logger
from leviathan.transforms.bronze_to_silver._weather_long import melt_weather_to_long

logger = get_logger(__name__)


class WeatherAvailability(str, Enum):
    """Typed outcome of classifying a CHIRPS bronze read (F044)."""

    AVAILABLE = "available"                    # >= 1 valid (non-null value) observation -> write partition
    EMPTY_NO_VALID_OBS = "empty_no_valid_obs"  # present but zero valid observations -> write NOTHING
    NOT_PUBLISHED = "not_published"            # no bronze bytes at all (404 / not yet published)


def classify_availability(silver_long: pd.DataFrame | None) -> WeatherAvailability:
    """Classify a transformed long frame. ``None`` -> NOT_PUBLISHED (no source bytes); an empty frame
    -> EMPTY_NO_VALID_OBS (present but no valid obs -> no partition); otherwise AVAILABLE.

    This is the F044 guard: a partition is written iff this returns ``AVAILABLE``. It never fabricates
    a null-filled row for a missing date."""
    if silver_long is None:
        return WeatherAvailability.NOT_PUBLISHED
    if silver_long.empty:
        return WeatherAvailability.EMPTY_NO_VALID_OBS
    return WeatherAvailability.AVAILABLE


def chirps_bronze_to_silver(df: pd.DataFrame, source_label: str = "dataframe") -> pd.DataFrame:
    """Apply silver cleaning rules to a CHIRPS bronze DataFrame.

    Returns a long/tidy DataFrame with one row per (date, region, variable).
    Columns: date, year, month, day, country, region, commodity, source, ingest_date, variable, value.

    A row whose ``value`` (precipitation) is null is DROPPED (never written as a NaN-filled partition,
    F044). A valid 0.0 mm dry-day reading is a real observation and is retained.
    """
    df = df.copy()
    # Clip only when present; the required-column contract (and its ValueError) is enforced inside
    # melt_weather_to_long, so a missing column must reach there rather than raising a bare KeyError.
    if "precipitation_mm" in df.columns:
        df["precipitation_mm"] = df["precipitation_mm"].clip(lower=0.0)
    silver = melt_weather_to_long(df, "precipitation_mm", source_label)
    availability = classify_availability(silver)
    logger.info(
        "CHIRPS silver transform: %d input rows -> %d long rows (availability=%s)",
        len(df), len(silver), availability.value,
    )
    return silver
