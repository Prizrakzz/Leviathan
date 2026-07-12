"""USDA AMS cotton-quality bronze -> silver transform (SILVER-F050, half-orphan restore).

``fetch_usda_ams_cotton_annual.py`` writes the Annual Cotton Quality Report PDFs to raw and an
(untracked) step produced the long-format bronze, but no tracked bronze->silver transform existed.
This module restores it; the mapping was reverse-engineered + validated bit-for-bit against the
27-row physical silver (``silver/ams_cotton_quality/part-000.parquet``).

Bronze (long) -> silver (one wide row per commodity x geography x season):

  * The silver row is the NATIONAL (``geography == "us_total"``) view -- the national_narrative +
    national_summary extraction scopes. Regional / appendix rows (``geography == "unknown"``) are
    dropped: they are per-region breakouts, not the national aggregate.
  * Metrics pivot to columns: percent_tenderable, samples_classed, avg_staple, avg_micronaire,
    avg_strength. Any metric absent from the national rows for a season stays NULL.
  * ``source_pages`` is the sorted, comma-joined set of PDF page numbers the national metrics came
    from; ``source_raw_key`` / ``source_file_etag`` carry the PDF provenance.

INV-2 null-type fix (the s3-lane hazard this package closes): in the tracked corpus
``avg_micronaire`` never appears and ``avg_strength`` appears only in regional scope, so both silver
columns are ALL-NULL. Written with pandas inference they land as Arrow ``null`` (Glue declares
``double`` -> a crawler/merge read hazard). The producer routes through the SILVER-F015 flat
publisher whose INV-2 schema pins them ``double``, so an all-null measurement column can never
become Arrow ``null`` again. (The transform still pivots them from the national rows if a future
report publishes them nationally.)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from leviathan.common.logging import get_logger

logger = get_logger(__name__)

_NATIONAL_GEOGRAPHY = "us_total"
# The five wide silver measurement columns (pinned present even when a season lacks the metric).
_METRIC_COLUMNS = ("percent_tenderable", "samples_classed", "avg_staple", "avg_micronaire", "avg_strength")

SILVER_COLUMNS: list[str] = [
    "commodity",
    "season",
    "geography",
    "percent_tenderable",
    "samples_classed",
    "avg_staple",
    "avg_micronaire",
    "avg_strength",
    "source_pages",
    "source_raw_key",
    "source_file_etag",
    "source",
]


def build_ams_cotton_silver(df_bronze: pd.DataFrame) -> pd.DataFrame:
    """Transform the AMS cotton-quality bronze into the wide national silver table.

    Args:
        df_bronze: Long-format bronze across every ingested season; must carry ``season``,
            ``geography``, ``metric``, ``value``, ``source_page``, ``source_raw_key``,
            ``source_file_etag``, ``source``.

    Returns:
        DataFrame with columns :data:`SILVER_COLUMNS`, one row per (commodity, geography, season),
        sorted by season, with zero natural-key duplicates.

    Raises:
        ValueError: If required columns are missing or the bronze is empty.
    """
    required = {"season", "geography", "metric", "value", "source_page",
                "source_raw_key", "source_file_etag", "source"}
    missing = required - set(df_bronze.columns)
    if missing:
        raise ValueError(f"AMS cotton bronze missing required columns: {sorted(missing)}")
    if df_bronze.empty:
        raise ValueError("AMS cotton bronze DataFrame is empty")

    nat = df_bronze[df_bronze["geography"] == _NATIONAL_GEOGRAPHY].copy()
    if nat.empty:
        raise ValueError("AMS cotton bronze has no national (us_total) rows")

    dup = nat.duplicated(subset=["season", "metric"]).sum()
    if dup:
        raise ValueError(f"AMS cotton bronze: {int(dup)} duplicate (season, metric) national rows")

    wide = nat.pivot_table(index="season", columns="metric", values="value", aggfunc="first")
    for col in _METRIC_COLUMNS:
        if col not in wide.columns:
            wide[col] = np.nan
    wide = wide[list(_METRIC_COLUMNS)]

    pages = (
        nat.groupby("season")["source_page"]
        .apply(lambda s: ",".join(str(int(x)) for x in sorted(set(s))))
        .rename("source_pages")
    )
    prov = nat.groupby("season").agg(
        source_raw_key=("source_raw_key", "first"),
        source_file_etag=("source_file_etag", "first"),
        source=("source", "first"),
    )

    df = wide.join(pages).join(prov).reset_index()
    df["commodity"] = "cotton"
    df["geography"] = _NATIONAL_GEOGRAPHY
    df = df.sort_values("season").reset_index(drop=True)

    result = df[SILVER_COLUMNS]
    if result.duplicated(subset=["commodity", "geography", "season"]).any():
        raise ValueError("AMS cotton silver: duplicate (commodity, geography, season) rows")
    logger.info("AMS cotton silver: %d seasons (%s..%s)  micronaire_nonnull=%d strength_nonnull=%d",
                len(result), int(result["season"].min()), int(result["season"].max()),
                int(result["avg_micronaire"].notna().sum()), int(result["avg_strength"].notna().sum()))
    return result
