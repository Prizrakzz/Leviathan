"""Compute NDVI z-scores against a 2000–2020 climatological baseline.

Takes the full bronze record for a commodity (all regions, all years, all periods),
filters to quality=0 or 1, derives a per-(region, period) baseline from the
2000–2020 window, then outputs z-score-enhanced silver.

Silver output columns
---------------------
    date, year, period, commodity, country, region,
    latitude, longitude, ndvi_raw, ndvi, pixel_reliability,
    ndvi_z_score, baseline_mean, baseline_std,
    ingest_date

Quality rules
-------------
- ``pixel_reliability`` must be 0 (good) or 1 (marginal) to be kept.
- A baseline cell (region, period) needs at least ``MIN_BASELINE_YEARS``
  valid years in 2000–2020; if not met, ``ndvi_z_score`` is NaN.
- ``baseline_std == 0`` → ``ndvi_z_score = NaN`` (constant signal, no info).
"""
from __future__ import annotations

import pandas as pd

from leviathan.common.logging import get_logger

logger = get_logger(__name__)

_BASELINE_START = 2000
_BASELINE_END = 2020
_QUALITY_KEEP = frozenset([0, 1])
_MIN_BASELINE_YEARS = 5


def modis_ndvi_bronze_to_silver(
    df: pd.DataFrame,
    source_label: str = "dataframe",
) -> pd.DataFrame:
    """Transform a MODIS NDVI bronze DataFrame to silver.

    Args:
        df:           Concatenated bronze DataFrame for one commodity,
                      containing all regions, years, and periods.
        source_label: Descriptive label used in log messages.

    Returns:
        Silver DataFrame with z-score columns added.  Rows with unknown
        baseline (< MIN_BASELINE_YEARS valid observations) receive NaN
        for ``ndvi_z_score``.
    """
    _REQUIRED = {
        "date", "year", "period", "commodity", "country", "region",
        "latitude", "longitude", "ndvi_raw", "ndvi", "pixel_reliability",
    }
    missing = _REQUIRED - set(df.columns)
    if missing:
        raise ValueError(f"Missing required MODIS NDVI bronze columns in {source_label}: {missing}")

    df = df.copy()

    # Deduplicate: guard against duplicate (region, date) rows inflating the baseline
    before_dedup = len(df)
    df = df.drop_duplicates(subset=["region", "date"])
    if len(df) < before_dedup:
        logger.warning(
            "%s: dropped %d duplicate (region, date) rows before baseline computation",
            source_label, before_dedup - len(df),
        )

    # Cast to expected types
    df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int16")
    df["period"] = pd.to_numeric(df["period"], errors="coerce").astype("Int8")
    df["pixel_reliability"] = pd.to_numeric(df["pixel_reliability"], errors="coerce").astype("Int8")
    df["ndvi"] = pd.to_numeric(df["ndvi"], errors="coerce").astype("float32")
    df["ndvi_raw"] = pd.to_numeric(df["ndvi_raw"], errors="coerce").astype("float32")

    # Quality filter: keep only good + marginal pixels
    before = len(df)
    df = df[df["pixel_reliability"].isin(_QUALITY_KEEP)].copy()
    logger.info(
        "%s: %d rows after quality filter (dropped %d)", source_label, len(df), before - len(df)
    )

    if df.empty:
        logger.warning("%s: no rows remain after quality filter", source_label)
        return _empty_silver()

    # Build per-(region, period) baseline from 2000–2020 observations
    baseline_mask = (
        df["year"].between(_BASELINE_START, _BASELINE_END)
        & df["ndvi"].notna()
    )
    baseline_df = df[baseline_mask].copy()
    baseline_df["year_int"] = baseline_df["year"].astype(int)

    # Count distinct years per (region, period) cell
    year_counts = (
        baseline_df.groupby(["region", "period"])["year_int"]
        .nunique()
        .rename("year_count")
    )

    baseline_stats = (
        baseline_df.groupby(["region", "period"])["ndvi"]
        .agg(baseline_mean="mean", baseline_std="std")
        .join(year_counts)
        .reset_index()
    )

    # Nullify baseline cells with insufficient history
    insufficient = baseline_stats["year_count"] < _MIN_BASELINE_YEARS
    if insufficient.any():
        logger.info(
            "%s: %d (region, period) cells have < %d baseline years — z-score will be NaN",
            source_label, int(insufficient.sum()), _MIN_BASELINE_YEARS,
        )
    baseline_stats.loc[insufficient, ["baseline_mean", "baseline_std"]] = float("nan")

    baseline_stats = baseline_stats[["region", "period", "baseline_mean", "baseline_std"]]

    # Merge baseline into full DataFrame
    df = df.merge(baseline_stats, on=["region", "period"], how="left")

    # Compute z-score; guard against zero std (constant signal)
    zero_std = (df["baseline_std"] == 0)
    if zero_std.any():
        logger.info(
            "%s: %d rows have baseline_std=0 — z-score set to NaN", source_label, int(zero_std.sum())
        )
        df.loc[zero_std, "baseline_std"] = float("nan")

    df["ndvi_z_score"] = (
        (df["ndvi"] - df["baseline_mean"]) / df["baseline_std"]
    ).astype("float32")

    df["baseline_mean"] = df["baseline_mean"].astype("float32")
    df["baseline_std"] = df["baseline_std"].astype("float32")

    # Final column order
    silver = df[[
        "date", "year", "period",
        "commodity", "country", "region",
        "latitude", "longitude",
        "ndvi_raw", "ndvi", "pixel_reliability",
        "ndvi_z_score", "baseline_mean", "baseline_std",
        "ingest_date",
    ]].copy()

    silver = silver.sort_values(
        ["country", "region", "year", "period"]
    ).reset_index(drop=True)

    logger.info(
        "%s: silver transform complete — %d rows, %d unique regions, years %s–%s",
        source_label,
        len(silver),
        silver["region"].nunique(),
        int(silver["year"].min()),
        int(silver["year"].max()),
    )
    return silver


def _empty_silver() -> pd.DataFrame:
    return pd.DataFrame(columns=[
        "date", "year", "period",
        "commodity", "country", "region",
        "latitude", "longitude",
        "ndvi_raw", "ndvi", "pixel_reliability",
        "ndvi_z_score", "baseline_mean", "baseline_std",
        "ingest_date",
    ])
