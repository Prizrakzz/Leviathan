"""Bronze transform for the NOAA PSL Indian Ocean Dipole (IOD) DMI text file.

Parses the fixed-width ``dmi.had.long.data`` file published by NOAA PSL at:
    https://psl.noaa.gov/gcos_wgsp/Timeseries/Data/dmi.had.long.data

File format
-----------
Year-range header on line 0, then one row per year with 12 monthly values,
followed by 4 footer metadata lines:

    1870 2025
    1870    -0.438    -0.336     0.177    -0.048  ...
    1871    -0.273    -0.170    -0.212    -0.148  ...
    ...
    2025    -0.196     0.017     0.059     0.149  -9999.000  -9999.000  ...
    Created Mon Jun 16 09:50:15 MDT 2025
    using SST anomaly 10S:10N,50E-70E minus 10S:0,90E-110E area averaged
    Timeseries output created at NOAA PSL
    https://psl.noaa.gov/gcos_wgsp/timeseries/DMI

Missing value sentinel: ``-9999.0`` (future months in the current year).

What is the DMI?
----------------
The Dipole Mode Index (DMI) measures the difference in SST anomaly between
the western Indian Ocean (50°E–70°E, 10°S–10°N) and the eastern Indian Ocean
(90°E–110°E, 10°S–equator).  Positive IOD (DMI > +0.4) → warmer western
Indian Ocean → drought in East Africa, India, SE Asia; wetter in East Africa
Horn.  Negative IOD (DMI < −0.4) → opposite pattern.

The IOD is orthogonal to ENSO.  It is the primary large-scale climate driver
for Ethiopia (Sidama/Yirgacheffe arabica coffee origin) where ENSO's signal
is weak and inconsistent.

Phase thresholds follow JMA convention: ±0.4 °C for event onset.

Source
------
HadSST-derived DMI from the NOAA/GCOS Working Group.
Monthly data from January 1870.  Updated monthly in-place.
"""
from __future__ import annotations

import re

import pandas as pd

from leviathan.common.logging import get_logger

logger = get_logger(__name__)

# Missing value sentinel confirmed from live file inspection
_MISSING_SENTINEL = -999.0   # values ≤ this are NaN (actual sentinel is -9999.0)

# IOD phase thresholds (JMA convention)
_POSITIVE_IOD_THRESHOLD =  0.4
_NEGATIVE_IOD_THRESHOLD = -0.4

# Regex: a data row starts with a 4-digit year
_DATA_ROW_RE = re.compile(r"^\s*(\d{4})\s+")

BRONZE_COLUMNS: list[str] = [
    "year",
    "month",
    "date",
    "dmi_value",
    "source",
]


def _classify_phase(val: float | None) -> str:
    if val is None:
        return "unknown"
    if val >= _POSITIVE_IOD_THRESHOLD:
        return "positive"
    if val <= _NEGATIVE_IOD_THRESHOLD:
        return "negative"
    return "neutral"


def extract_iod_bronze(raw_bytes: bytes) -> pd.DataFrame:
    """Parse the NOAA PSL DMI text file into a long-format bronze DataFrame.

    Args:
        raw_bytes: Raw bytes of the ``dmi.had.long.data`` file from S3.

    Returns:
        DataFrame with columns :data:`BRONZE_COLUMNS`.  One row per
        (year, month), 1870–present.  Future months in the current year
        have ``dmi_value = NaN``.

    Raises:
        ValueError: If no parseable data rows are found.
    """
    text = raw_bytes.decode("utf-8", errors="replace")
    lines = text.strip().splitlines()

    records: list[dict] = []
    skipped = 0

    for line in lines:
        if not _DATA_ROW_RE.match(line):
            # Header (line 0 = "1870 2025") and footer lines — skip
            continue

        parts = line.split()
        if len(parts) < 2:
            skipped += 1
            continue

        try:
            year = int(parts[0])
        except ValueError:
            skipped += 1
            continue

        for month_idx, val_str in enumerate(parts[1:13], start=1):
            try:
                val = float(val_str)
            except ValueError:
                val = None
            else:
                val = None if val <= _MISSING_SENTINEL else val

            records.append({
                "year":      year,
                "month":     month_idx,
                "dmi_value": val,
            })

    if not records:
        raise ValueError(
            "IOD bronze: no parseable rows found — file may be malformed or empty"
        )

    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df[["year", "month"]].assign(day=1))
    df["source"] = "noaa_iod"
    df["dmi_value"] = df["dmi_value"].astype("float32")

    df = (
        df[BRONZE_COLUMNS]
        .sort_values(["year", "month"])
        .reset_index(drop=True)
    )

    if skipped:
        logger.warning("IOD bronze: skipped %d unparseable lines", skipped)

    non_null = int(df["dmi_value"].notna().sum())
    logger.info(
        "IOD bronze: %d rows parsed  non-null=%d  years=%d–%d",
        len(df),
        non_null,
        int(df["year"].min()),
        int(df["year"].max()),
    )
    return df
