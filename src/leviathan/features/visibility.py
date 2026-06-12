"""The point-in-time alignment rule — one implementation, used by every feature.

Encodes the "Crop Year vs Marketing Year — Alignment Rule" from desiredstate.md:

* ``crop_year_direct``     — in-season data dated within crop year Y's span.
  Weather, NDVI, CONAB/NASS surveys.  Known before the harvest outcome.
* ``prior_history``        — data from crop years strictly before Y.
  FAOSTAT YoY/trend features, capacity-recovery lookbacks.  The observation
  year's own outcome is never visible to its features.
* ``prior_marketing_year`` — PSD/WASDE S/D data joined to the PRIOR marketing
  year (``crop_year + mkt_year_offset``), restricted to release vintages dated
  on/before the crop-year start (the estimate available at planting).

No feature computation touches silver data except through ``visible_slice``.
That structural choke point is what the truncate-at-T anti-leakage test relies on.
"""
from __future__ import annotations

from datetime import date

import pandas as pd

from leviathan.features.calendar import CropCalendar


class VisibilityError(Exception):
    """Raised when a visibility class cannot be applied to an input frame."""


def visible_slice(
    df: pd.DataFrame,
    visibility: str,
    calendar: CropCalendar,
    crop_year: int,
) -> pd.DataFrame:
    """Return the subset of *df* visible to features of *crop_year*.

    Dispatch on visibility class; see module docstring.  Input frame
    requirements:

    * ``crop_year_direct``: needs a ``date`` column (datetime64 or date).
    * ``prior_history``: needs a ``year`` column (int) — FAOSTAT-style annual
      data; rows with ``year >= crop_year`` are dropped.
    * ``prior_marketing_year``: needs ``market_year`` (int) and
      ``release_date`` columns — PSD-style vintaged data.
    """
    if visibility == "crop_year_direct":
        return _crop_year_direct(df, calendar, crop_year)
    if visibility == "prior_history":
        return _prior_history(df, crop_year)
    if visibility == "prior_marketing_year":
        return _prior_marketing_year(df, calendar, crop_year)
    raise VisibilityError(f"Unknown visibility class: {visibility!r}")


def _crop_year_direct(
    df: pd.DataFrame, calendar: CropCalendar, crop_year: int
) -> pd.DataFrame:
    if "date" not in df.columns:
        raise VisibilityError("crop_year_direct requires a 'date' column")
    dates = pd.to_datetime(df["date"])
    start = pd.Timestamp(calendar.crop_year_start(crop_year))
    end = pd.Timestamp(calendar.crop_year_end(crop_year))
    return df.loc[(dates >= start) & (dates <= end)]


def _prior_history(df: pd.DataFrame, crop_year: int) -> pd.DataFrame:
    if "year" not in df.columns:
        raise VisibilityError("prior_history requires a 'year' column")
    years = pd.to_numeric(df["year"], errors="coerce")
    return df.loc[years < crop_year]


def _prior_marketing_year(
    df: pd.DataFrame, calendar: CropCalendar, crop_year: int
) -> pd.DataFrame:
    """PSD vintage selection: prior marketing year, latest release at planting.

    Two filters compose:
    1. ``market_year == crop_year + mkt_year_offset`` — for US corn crop year
       2024 (offset -1) this selects marketing year 2023/24, the balance sheet
       known at May planting.  Never the marketing year that begins at harvest.
    2. ``release_date <= crop-year start`` — only WASDE/PSD vintages published
       before the growing season; among those, the latest release wins.
    """
    for col in ("market_year", "release_date"):
        if col not in df.columns:
            raise VisibilityError(f"prior_marketing_year requires a '{col}' column")

    target_my = crop_year + calendar.mkt_year_offset
    cutoff = pd.Timestamp(calendar.crop_year_start(crop_year))

    my = pd.to_numeric(df["market_year"], errors="coerce")
    releases = pd.to_datetime(df["release_date"])
    visible = df.loc[(my == target_my) & (releases <= cutoff)]
    if visible.empty:
        return visible

    latest = pd.to_datetime(visible["release_date"]).max()
    return visible.loc[pd.to_datetime(visible["release_date"]) == latest]


def event_time(calendar: CropCalendar, crop_year: int) -> date:
    """Feature Store ``event_time`` for an observation: the crop-year start date."""
    return calendar.crop_year_start(crop_year)
