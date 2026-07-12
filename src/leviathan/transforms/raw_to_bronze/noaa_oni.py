"""Bronze transform for the NOAA CPC Oceanic Nino Index (ONI) ascii file (SILVER-F057).

Parses the whitespace-delimited ``oni.ascii.txt`` file published by NOAA CPC at:
    https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt

This producer is built FROM SCRATCH (C-WRONG-8 full orphan): ``silver_noaa_oni`` was
consumed everywhere (``silverleg.py``, ``numbers/agent.py``, ``macro_climate.py``) but
produced by nothing in the tracked estate. The source, grain, columns and every derived
value in this module were reverse-engineered from the live physical silver parquet
(``silver/weather/source=noaa_oni/part-000.parquet``, 915 rows, 1950-01..2026-03) plus the
registry contract; see ``docs/adr/ADR-002-noaa-oni-source.md`` for the source decision.

File format
-----------
A one-line header, then one row per overlapping 3-month season (12 rows/year), 1950-present::

     SEAS  YR   TOTAL   ANOM
      DJF 1950  24.72  -1.53
      JFM 1950  25.17  -1.34
      ...
      MAM 2026  28.08   0.51

Columns: ``SEAS`` the 3-month season label (DJF..NDJ), ``YR`` the year, ``TOTAL`` the
absolute Nino-3.4 SST (degC), ``ANOM`` the ONI anomaly (degC, the 3-month running SST
anomaly). ANOM is published to two decimals -- this is the *unrounded* ONI, not the
one-decimal figure shown on the CPC website table.

What is the ONI?
----------------
The Oceanic Nino Index is NOAA's canonical ENSO state: the 3-month running mean of the
ERSSTv5 SST anomaly in the Nino-3.4 region (5N-5S, 120W-170W). An El Nino event is
classified when the ONI is >= +0.5 degC and a La Nina when it is <= -0.5 degC. The IOD
(``noaa_iod``) is the orthogonal Indian-Ocean driver; ONI is the Pacific one.

Season -> month convention
--------------------------
Each overlapping 3-month season is stamped to its CENTER month so the table is one row per
(year, month): DJF -> Jan(1), JFM -> Feb(2), FMA -> Mar(3), MAM -> Apr(4), AMJ -> May(5),
MJJ -> Jun(6), JJA -> Jul(7), JAS -> Aug(8), ASO -> Sep(9), SON -> Oct(10), OND -> Nov(11),
NDJ -> Dec(12). Verified against the live silver (season/month agree 1:1 across all 915 rows).

Missing-value handling (INV-4)
------------------------------
The ONI file publishes only completed seasons, so it has no sentinel rows in practice. This
parser still guards defensively: an unparseable ANOM stays ``None`` (never synthesized as
zero) so the absent-measure-stays-null invariant holds if NOAA ever ships a placeholder.
"""
from __future__ import annotations

import re

import pandas as pd

from leviathan.common.logging import get_logger

logger = get_logger(__name__)

# The 12 overlapping 3-month ONI seasons, each mapped to its CENTER month (1-12).
SEASON_TO_MONTH: dict[str, int] = {
    "DJF": 1, "JFM": 2, "FMA": 3, "MAM": 4, "AMJ": 5, "MJJ": 6,
    "JJA": 7, "JAS": 8, "ASO": 9, "SON": 10, "OND": 11, "NDJ": 12,
}

# A defensive missing sentinel: any value at/below this is treated as absent. The live ONI
# file uses no sentinel, but NOAA sibling files (e.g. detrend.nino34) use -99.9 / -9999.
_MISSING_SENTINEL = -99.0

# A data row is three whitespace-separated numeric-ish fields after a 3-letter season token.
_DATA_ROW_RE = re.compile(r"^\s*([A-Z]{3})\s+(\d{4})\s+(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s*$")

BRONZE_COLUMNS: list[str] = [
    "year",
    "month",
    "season",
    "oni_total",
    "oni_anom",
    "source",
]


def extract_oni_bronze(raw_bytes: bytes) -> pd.DataFrame:
    """Parse the NOAA CPC ONI ascii file into a long-format bronze DataFrame.

    Args:
        raw_bytes: Raw bytes of ``oni.ascii.txt`` from S3 (or an HTTP fetch).

    Returns:
        DataFrame with columns :data:`BRONZE_COLUMNS`, one row per (year, month), sorted
        chronologically. ``oni_total`` / ``oni_anom`` are ``NaN`` for any sentinel row.

    Raises:
        ValueError: If no parseable data rows are found, or a season token is unrecognized.
    """
    text = raw_bytes.decode("utf-8", errors="replace")
    lines = text.strip().splitlines()

    records: list[dict] = []
    skipped = 0
    for line in lines:
        m = _DATA_ROW_RE.match(line)
        if not m:
            # Header (" SEAS  YR   TOTAL   ANOM") and any stray footer line.
            skipped += 1
            continue
        season, year_s, total_s, anom_s = m.group(1), m.group(2), m.group(3), m.group(4)
        if season not in SEASON_TO_MONTH:
            raise ValueError(f"ONI bronze: unrecognized season token {season!r}")
        year = int(year_s)
        total = _parse_measure(total_s)
        anom = _parse_measure(anom_s)
        records.append({
            "year": year,
            "month": SEASON_TO_MONTH[season],
            "season": season,
            "oni_total": total,
            "oni_anom": anom,
        })

    if not records:
        raise ValueError("ONI bronze: no parseable rows found -- file may be malformed or empty")

    df = pd.DataFrame(records)
    df["source"] = "noaa_oni"
    df = (
        df[BRONZE_COLUMNS]
        .sort_values(["year", "month"])
        .reset_index(drop=True)
    )

    non_null = int(df["oni_anom"].notna().sum())
    logger.info(
        "ONI bronze: %d rows parsed  non-null_anom=%d  years=%d-%d  (skipped %d header/footer lines)",
        len(df), non_null, int(df["year"].min()), int(df["year"].max()), skipped,
    )
    return df


def _parse_measure(token: str):
    try:
        val = float(token)
    except (TypeError, ValueError):
        return None
    return None if val <= _MISSING_SENTINEL else val
