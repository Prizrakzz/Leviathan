"""Silver transform for USDA FGIS Export Inspections data.

Aggregates per-shipment FGIS bronze rows into weekly export volumes keyed by
(leviathan_slug, marketing_year, week_of_marketing_year, destination_country),
plus a cumulative season-to-date (CTD) column.

Design notes
------------
* **Grain filtering** — only the five Leviathan-mapped grain classes are
  retained (YC, YSB, HRW, HRS, SRW).  Other grains (sorghum, barley,
  white wheat, etc.) are silently dropped — they have no corresponding
  futures contract in the Leviathan universe.

* **Week alignment** — ``week_of_marketing_year`` is 1-indexed and aligns
  to the commodity's marketing year start (fixed calendar date):

      corn / soybeans : Sep 1   (week 1 = Sep 1 – Sep 7)
      wheat classes   : Jun 1   (week 1 = Jun 1 – Jun 7)

  ``week_ending_date`` is the deterministic last day of that 7-day window,
  independent of whether any shipments actually occurred that week.

* **CTD** — cumulative metric tonnes within (leviathan_slug, marketing_year,
  destination_country), ordered by week_of_marketing_year.  Destination-level
  CTD enables China-demand-surge detection without a gold-layer pivot.
  Total-across-destinations aggregation is deferred to the gold layer.

* **No as_of partition** — FGIS records are legal certifications; there is no
  survey-revision risk.  One silver partition per (leviathan_slug,
  marketing_year) covers the full season.

* **Input spans two CY files** — a marketing year starting Sep 1 or Jun 1
  always spans two calendar years.  The caller is responsible for passing a
  DataFrame that contains rows from all relevant CY bronze files.

No S3 or AWS dependencies — pure data transformation.
"""
from __future__ import annotations

import datetime

import pandas as pd

from leviathan.common.logging import get_logger

logger = get_logger(__name__)

# Maps the FGIS ``class`` column value to a Leviathan commodity slug.
# Only classes with a direct CBOT/KCBT/MGEX futures contract are mapped;
# other classes are silently excluded from silver.
_CLASS_TO_SLUG: dict[str, str] = {
    "YC":  "corn_cbot",
    "YSB": "soybeans_cbot",
    "HRW": "hard_red_winter_wheat_kcbt",
    "HRS": "hard_red_spring_wheat_mgex",
    "SRW": "soft_red_winter_wheat_cbot",
}

# Marketing year start month for each Leviathan slug.
# Used to compute week_of_marketing_year and week_ending_date.
_SLUG_MY_START_MONTH: dict[str, int] = {
    "corn_cbot":                   9,  # Sep 1
    "soybeans_cbot":               9,  # Sep 1
    "hard_red_winter_wheat_kcbt":  6,  # Jun 1
    "hard_red_spring_wheat_mgex":  6,  # Jun 1
    "soft_red_winter_wheat_cbot":  6,  # Jun 1
}

# Columns that must be present in the bronze DataFrame.
_REQUIRED_COLS: frozenset[str] = frozenset({
    "class",
    "cert_date",
    "metric_ton",
    "destination",
    "marketing_year",
    "source",
})

# Canonical silver column order.
OUTPUT_COLUMNS: list[str] = [
    "leviathan_slug",
    "marketing_year",
    "week_of_marketing_year",
    "week_ending_date",
    "destination_country",
    "exports_mt_weekly",
    "exports_mt_ctd",
    "source",
]


def _my_start_date(slug: str, marketing_year: int) -> datetime.date:
    """Return the first calendar date of a commodity's marketing year."""
    month = _SLUG_MY_START_MONTH[slug]
    return datetime.date(marketing_year, month, 1)


def _week_of_my(date: datetime.date, my_start: datetime.date) -> int:
    """Compute 1-indexed week number relative to marketing year start.

    Week 1 is the 7-day window beginning on *my_start*.  Handles the
    Dec→Jan calendar rollover transparently (e.g. corn MY2024 week 18
    starts 2025-01-05).

    Returns:
        Week number (minimum 1).
    """
    delta = (date - my_start).days
    return max(1, delta // 7 + 1)


def _week_end_date(week: int, my_start: datetime.date) -> datetime.date:
    """Return the last calendar day of *week* (1-indexed) relative to MY start."""
    return my_start + datetime.timedelta(days=(week - 1) * 7 + 6)


def transform_fgis_bronze_to_silver(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate FGIS per-shipment bronze rows into weekly silver data.

    Processes all marketing years present in *df*.  The caller should pass
    the union of all relevant calendar-year bronze Parquets (e.g. for corn
    MY2024 supply both the CY2024 and CY2025 bronze DataFrames).

    Args:
        df: Bronze FGIS DataFrame.  May span multiple calendar years and
            multiple marketing years.  Must include columns listed in
            ``_REQUIRED_COLS``.

    Returns:
        Wide-format silver DataFrame with one row per
        (leviathan_slug, marketing_year, week_of_marketing_year,
        destination_country).  Returns an empty DataFrame with the correct
        schema if no mapped rows exist.

    Raises:
        ValueError: If required columns are absent from *df*.
    """
    # --- Validate required columns ---
    missing = _REQUIRED_COLS - set(df.columns)
    if missing:
        raise ValueError(
            f"FGIS bronze DataFrame is missing required columns: "
            f"{sorted(missing)}.  Got: {sorted(df.columns)}"
        )

    df = df.copy()

    # --- Map class -> leviathan_slug; drop unmapped grains ---
    class_col = df["class"].astype(str).str.strip().str.upper()
    df["leviathan_slug"] = class_col.map(_CLASS_TO_SLUG)
    before = len(df)
    df = df.dropna(subset=["leviathan_slug"]).reset_index(drop=True)
    dropped = before - len(df)
    if dropped:
        logger.debug(
            "FGIS silver: dropped %d rows with unmapped class codes", dropped
        )

    if df.empty:
        logger.warning("FGIS silver: no rows remain after class filtering")
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    # --- Normalize destination country ---
    df["destination_country"] = (
        df["destination"].astype(str).str.strip().str.upper()
    )

    # --- Parse date ---
    df["_date"] = pd.to_datetime(df["cert_date"], errors="coerce").dt.date
    null_dates = df["_date"].isna().sum()
    if null_dates:
        logger.warning(
            "FGIS silver: dropping %d row(s) with null date", null_dates
        )
        df = df.dropna(subset=["_date"]).reset_index(drop=True)

    # --- Compute week_of_marketing_year and week_ending_date ---
    # Vectorise over unique (slug, marketing_year, date) triples to avoid
    # per-row Python overhead on large DataFrames.
    triple_cols = ["leviathan_slug", "marketing_year", "_date"]
    unique = df[triple_cols].drop_duplicates().copy()

    weeks: list[int] = []
    wends: list[datetime.date] = []
    for _, row in unique.iterrows():
        slug = row["leviathan_slug"]
        my = int(row["marketing_year"])
        date = row["_date"]
        my_start = _my_start_date(slug, my)
        w = _week_of_my(date, my_start)
        weeks.append(w)
        wends.append(_week_end_date(w, my_start))

    unique["week_of_marketing_year"] = weeks
    unique["week_ending_date"] = wends

    df = df.merge(
        unique[triple_cols + ["week_of_marketing_year", "week_ending_date"]],
        on=triple_cols,
        how="left",
    )

    # --- Aggregate: sum mt per (slug, MY, week, destination_country) ---
    agg = (
        df.groupby(
            [
                "leviathan_slug",
                "marketing_year",
                "week_of_marketing_year",
                "week_ending_date",
                "destination_country",
            ],
            as_index=False,
            dropna=False,
        )
        .agg(
            exports_mt_weekly=("metric_ton", "sum"),
            source=("source", "first"),
        )
    )

    # --- Sort for stable CTD cumsum ---
    agg = agg.sort_values(
        [
            "leviathan_slug",
            "marketing_year",
            "destination_country",
            "week_of_marketing_year",
        ]
    ).reset_index(drop=True)

    # --- Cumulative season-to-date per (slug, MY, destination) ---
    agg["exports_mt_ctd"] = agg.groupby(
        ["leviathan_slug", "marketing_year", "destination_country"],
        sort=False,
    )["exports_mt_weekly"].cumsum()

    # --- Cast types ---
    agg["marketing_year"] = agg["marketing_year"].astype("Int32")
    agg["week_of_marketing_year"] = agg["week_of_marketing_year"].astype("Int32")
    agg["exports_mt_weekly"] = agg["exports_mt_weekly"].astype("float64")
    agg["exports_mt_ctd"] = agg["exports_mt_ctd"].astype("float64")

    # --- Enforce output column order ---
    agg = agg[OUTPUT_COLUMNS].reset_index(drop=True)

    logger.info(
        "FGIS silver transform: rows=%d marketing_years=%s slugs=%s",
        len(agg),
        sorted(agg["marketing_year"].dropna().unique().tolist()),
        sorted(agg["leviathan_slug"].unique().tolist()),
    )

    return agg
