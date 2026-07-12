"""Bronze transform for the ICCO QBCS (Quarterly Bulletin of Cocoa Statistics) summary JSON.

SILVER-F051 (half-orphan restore): ``fetch_icco_qbcs_summary.py`` writes the parsed QBCS
release summary to ``raw/production/source=icco_qbcs_summary/release_date=<d>/*.json`` but no
tracked bronze/silver transform existed. This module + ``bronze_to_silver/icco_cocoa.py`` restore
the producer; the bronze layout was reverse-engineered from the live physical bronze
(``bronze/production/source=icco_qbcs/release_date=<d>/part-000.parquet``, 8 rows/release).

Raw JSON shape (one file per quarterly release)::

    {
      "release_date": "2012-11-30",
      "cocoa_year_prior":   "2010/11",
      "cocoa_year_current": "2011/12",
      "prior":   {"world_production_kt": .., "world_grindings_kt": .., "surplus_deficit_kt": ..,
                  "end_season_stocks_kt": ..},
      "current": {"world_production_kt": .., ...},
      ...
    }

Each release carries two cocoa-year snapshots (``current`` = the in-season estimate for the
just-completed/ongoing cocoa year, ``prior`` = the previous year revised). The bronze is the
long form: 8 rows per release (2 vintages x 4 metrics), which the b2s step then reduces to one
authoritative row per cocoa year.
"""
from __future__ import annotations

import json

import pandas as pd

from leviathan.common.logging import get_logger

logger = get_logger(__name__)

# The four ICCO balance-sheet metrics, in the physical bronze column order.
_METRICS = ("world_production_kt", "world_grindings_kt", "end_season_stocks_kt", "surplus_deficit_kt")
# current is emitted before prior (matches the physical bronze row order).
_VINTAGES = ("current", "prior")

BRONZE_COLUMNS: list[str] = ["release_date", "cocoa_year", "vintage", "metric", "value_kt", "source"]


def extract_icco_bronze(raw_json: bytes | str | dict) -> pd.DataFrame:
    """Parse one ICCO QBCS summary JSON into the long-format bronze DataFrame (8 rows).

    Args:
        raw_json: Raw JSON bytes/str, or an already-decoded dict, for one release.

    Returns:
        DataFrame with columns :data:`BRONZE_COLUMNS` -- one row per (vintage, metric).

    Raises:
        ValueError: If the JSON lacks a release_date or both vintage blocks.
    """
    doc = raw_json if isinstance(raw_json, dict) else json.loads(raw_json)
    release_date = doc.get("release_date")
    if not release_date:
        raise ValueError("ICCO bronze: raw JSON has no release_date")

    records: list[dict] = []
    for vintage in _VINTAGES:
        block = doc.get(vintage)
        cocoa_year = doc.get(f"cocoa_year_{vintage}")
        if not isinstance(block, dict) or not cocoa_year:
            continue
        for metric in _METRICS:
            val = block.get(metric)
            records.append({
                "release_date": release_date,
                "cocoa_year": cocoa_year,
                "vintage": vintage,
                "metric": metric,
                "value_kt": float(val) if val is not None else None,
                "source": "icco_qbcs",
            })

    if not records:
        raise ValueError(f"ICCO bronze: release {release_date} has no current/prior block")

    df = pd.DataFrame(records)[BRONZE_COLUMNS]
    logger.info("ICCO bronze: release=%s rows=%d cocoa_years=%s",
                release_date, len(df), sorted(df["cocoa_year"].unique()))
    return df
