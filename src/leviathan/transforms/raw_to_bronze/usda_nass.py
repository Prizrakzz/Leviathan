"""Bronze transform for USDA NASS QuickStats bulk crops download.

Reads the tab-delimited, gzip-compressed QuickStats CROPS sector file and
produces two bronze series:

``annual``
    Standard annual crop statistics (Area Planted, Area Harvested, Yield,
    Production) at the national and state level.  Filtered to the leviathan
    commodity universe.

``crop_progress``
    Weekly Crop Progress percentages (Good/Excellent % is the primary
    feature; all PROGRESS and CONDITION rows are retained).  Filtered to
    grains + oilseeds only.

Memory note
-----------
The full .gz file is ~1 GB uncompressed.  This transform streams it in
chunks of 100,000 rows to stay within Fargate container memory limits.
The Batch submission script should allocate ≥4 GB of container memory.

Commodity mapping
-----------------
NASS uses its own ``commodity_desc`` values (e.g. "CORN", "SOYBEANS").
The mapping to leviathan slugs is defined in ``_NASS_SLUG_MAP`` below.
Only rows whose ``commodity_desc`` appears in this map are retained.
"""
from __future__ import annotations

import io
from collections import defaultdict

import pandas as pd

from leviathan.common.logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Commodity mapping: NASS commodity_desc → leviathan slug
# ---------------------------------------------------------------------------

# Annual crops: area / yield / production
_ANNUAL_COMMODITY_MAP: dict[str, str] = {
    "CORN":           "corn_cbot",
    "SOYBEANS":       "soybean_meal_cbot",   # proxy — NASS has no meal-only series
    "WHEAT":          "soft_red_winter_wheat_cbot",
    "WHEAT, WINTER":  "soft_red_winter_wheat_cbot",
    "WHEAT, SPRING":  "hard_red_spring_wheat_mgex",
    "WHEAT, DURUM":   "hard_red_spring_wheat_mgex",
    "COTTON":         "cotton",
    "RICE":           "rough_rice_cbot",
    "SORGHUM":        "corn_cbot",   # sorghum aggregated with coarse grains
    "OATS":           "corn_cbot",   # coarse grains
    "BARLEY":         "corn_cbot",   # coarse grains
    "SUGARCANE":      "raw_sugar",
    "SUGAR BEETS":    "raw_sugar",
    "SUNFLOWER":      "soybean_meal_cbot",  # oilseeds proxy
    "CANOLA":         "canola_ice",
}

# Weekly crop progress: Good/Excellent % and related condition/progress rows
_PROGRESS_COMMODITY_MAP: dict[str, str] = {
    "CORN":       "corn_cbot",
    "SOYBEANS":   "soybean_meal_cbot",
    "WHEAT":      "soft_red_winter_wheat_cbot",
    "COTTON":     "cotton",
    "SORGHUM":    "corn_cbot",
    "RICE":       "rough_rice_cbot",
    "OATS":       "corn_cbot",
    "BARLEY":     "corn_cbot",
}

# Columns to keep in annual series
_ANNUAL_KEEP_COLS = [
    "source_desc", "sector_desc", "group_desc", "commodity_desc",
    "class_desc", "prodn_practice_desc", "util_practice_desc",
    "domain_desc", "domaincat_desc", "short_desc", "freq_desc",
    "reference_period_desc",
    "statisticcat_desc", "unit_desc",
    "agg_level_desc", "state_alpha", "state_name",
    "county_code", "county_name",
    "year", "value",
    "CV_%",
]

# Columns to keep in crop progress series
_PROGRESS_KEEP_COLS = [
    "source_desc", "commodity_desc", "class_desc",
    "prodn_practice_desc", "util_practice_desc",
    "domain_desc", "domaincat_desc", "short_desc",
    "statisticcat_desc", "unit_desc",
    "agg_level_desc", "state_alpha", "state_name",
    "year", "week_ending", "value",
]

_ANNUAL_STAT_CATS = frozenset({
    "AREA PLANTED", "AREA HARVESTED", "YIELD", "PRODUCTION",
})

_PROGRESS_STAT_CATS = frozenset({
    "PROGRESS", "CONDITION",
})

_CHUNKSIZE = 100_000


def _normalize_col(c: str) -> str:
    return c.strip().lower().replace(" ", "_").replace("%", "pct")


def extract_usda_nass(
    raw_source: "bytes | IO[bytes]",
    download_date: str,
) -> dict[str, pd.DataFrame]:
    """Stream-parse the NASS QuickStats .gz and return two series DataFrames.

    Args:
        raw_source:    Either raw bytes of the .gz file, or a file-like object
                       (e.g. a boto3 StreamingBody or an ``io.BytesIO``).
                       Passing a file-like avoids an in-memory copy of the
                       compressed file.
        download_date: Download date in ``YYYY-MM-DD`` format (metadata column).

    Returns:
        Dict with keys ``"annual"`` and ``"crop_progress"``, each mapping to
        a DataFrame.  Either value may be an empty DataFrame if no matching
        rows were found (unlikely with a valid NASS bulk file).
    """
    annual_frames: list[pd.DataFrame] = []
    progress_frames: list[pd.DataFrame] = []

    source: "bytes | IO[bytes]" = (
        io.BytesIO(raw_source) if isinstance(raw_source, bytes) else raw_source
    )

    reader = pd.read_csv(
        source,
        sep="\t",
        compression="gzip",
        low_memory=False,
        chunksize=_CHUNKSIZE,
        encoding="latin-1",
    )

    for chunk in reader:
        # Normalize column names
        chunk.columns = [_normalize_col(c) for c in chunk.columns]

        if "commodity_desc" not in chunk.columns or "statisticcat_desc" not in chunk.columns:
            logger.warning("NASS chunk missing expected columns — skipping")
            continue

        comm = chunk["commodity_desc"].astype(str).str.strip().str.upper()
        stat = chunk["statisticcat_desc"].astype(str).str.strip().str.upper()

        # Annual slice
        annual_mask = (
            comm.isin(_ANNUAL_COMMODITY_MAP)
            & stat.isin(_ANNUAL_STAT_CATS)
        )
        if annual_mask.any():
            sub = chunk.loc[annual_mask].copy()
            sub["leviathan_slug"] = comm[annual_mask].map(_ANNUAL_COMMODITY_MAP)
            keep = [_normalize_col(c) for c in _ANNUAL_KEEP_COLS if _normalize_col(c) in sub.columns]
            keep = ["leviathan_slug"] + [c for c in keep if c not in ("leviathan_slug",)]
            annual_frames.append(sub[keep])

        # Crop progress slice
        progress_mask = (
            comm.isin(_PROGRESS_COMMODITY_MAP)
            & stat.isin(_PROGRESS_STAT_CATS)
        )
        if progress_mask.any():
            sub = chunk.loc[progress_mask].copy()
            sub["leviathan_slug"] = comm[progress_mask].map(_PROGRESS_COMMODITY_MAP)
            keep = [_normalize_col(c) for c in _PROGRESS_KEEP_COLS if _normalize_col(c) in sub.columns]
            keep = ["leviathan_slug"] + [c for c in keep if c not in ("leviathan_slug",)]
            progress_frames.append(sub[keep])

    def _concat(frames: list[pd.DataFrame]) -> pd.DataFrame:
        if not frames:
            return pd.DataFrame()
        df = pd.concat(frames, ignore_index=True)
        if "value" in df.columns:
            df["value"] = pd.to_numeric(
                df["value"].astype(str).str.replace(",", "", regex=False),
                errors="coerce",
            )
        if "year" in df.columns:
            df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")
        if "county_code" in df.columns:
            # Chunked read_csv infers float64 for all-blank county chunks and
            # object for county-level chunks.  After concat the column holds
            # Python float NaN mixed with str values (e.g. '033').  Normalise
            # so PyArrow infers utf8 with nulls instead of trying DOUBLE.
            notna_mask = df["county_code"].notna()
            df["county_code"] = df["county_code"].astype(str).where(notna_mask, None)
        df["download_date"] = download_date
        df["source"] = "usda_nass"
        return df

    annual_df = _concat(annual_frames)
    progress_df = _concat(progress_frames)

    logger.info(
        "NASS extract complete  download=%s  annual_rows=%d  progress_rows=%d",
        download_date,
        len(annual_df),
        len(progress_df),
    )
    return {"annual": annual_df, "crop_progress": progress_df}
