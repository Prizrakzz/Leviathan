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

AMS-1 (D-LD Tranche 2 pre-step) -- the PIT ANCHOR. The table had NO date column of any kind: the
only chronological axis was ``season``, a crop-year INTEGER. Every as-of guard branch in the numbers
read path needs a knowledge/date column (or a year+month pair), so the table could not be carded at
all -- ``build_sql`` raised ``no knowledge/date column to anchor the as-of guard`` on the first
lookup. This transform now DERIVES ``release_date`` (ISO ``YYYY-MM-DD``), the conservative,
never-leak publication stamp, exactly as ``conab_coffee.survey_release_date`` does. See
``ams_release_date``. It is a TIMING column only -- it never touches a measured value.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from leviathan.common.logging import get_logger

logger = get_logger(__name__)

_NATIONAL_GEOGRAPHY = "us_total"
# The five wide silver measurement columns (pinned present even when a season lacks the metric).
_METRIC_COLUMNS = ("percent_tenderable", "samples_classed", "avg_staple", "avg_micronaire", "avg_strength")

# ---------------------------------------------------------------------------
# AMS-1: release_date -- the derived, conservative, never-leak vintage anchor.
# ---------------------------------------------------------------------------
# AMS publishes the Annual Cotton Quality Report for crop season Y during Y+1 (measured lower bound:
# the season-2025 PDF was already retrievable from AMS at our 2026-07-16 fetch stamp). We have ONE
# observed release date, which is not enough to pin a tight calendar day (the estate's "collect 3
# fires then declare" rule), so the stamp is derived at the START OF THE NEXT CLASSING SEASON --
# 1 September of season+1 -- by which the prior season's summary is unambiguously out.
#
# CONSERVATIVE BY CONSTRUCTION: the derived date is always ON OR AFTER the real release, so the
# point-in-time guard can never LEAK a season before it was published. The cost is a withhold of at
# most a few months on the freshest season, which is the SAFE direction. Tightening the pin to 08-01
# requires three observed AMS release dates first; until then the conservative pin stands.
#
# The stamp is a pure function of the season, so it is strictly increasing in season -- knowledge
# date DESC and season DESC agree, which is what makes the latest-vintage collapse deterministic.
_RELEASE_YEAR_OFFSET = 1
_RELEASE_MONTH = 9
_RELEASE_DAY = 1

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
    # AMS-1 additive tail (kept LAST to mirror the Glue ADD COLUMNS append + the widened hand DDL;
    # the conab_coffee survey_release_date precedent). The publisher pins physical order from the
    # F010 contract, so this list's order is the catalog's, not an accident.
    "release_date",
]


def ams_release_date(season: object) -> str:
    """Conservative ISO ``YYYY-MM-DD`` publication stamp for one AMS cotton crop season.

    ``season`` is the crop year START (2025 = the 2025/26 US crop); the stamp is 1 September of
    ``season + 1``. Fail-loud on a missing / non-integral season: a null PIT anchor would silently
    drop the row from the leakage-safe as-of guard (``null <= asof`` is UNKNOWN), which is the
    quietest possible way to lose a season.
    """
    if season is None or pd.isna(season):
        raise ValueError("AMS cotton: cannot derive release_date from a null season")
    try:
        year = int(season)
        integral = float(season) == float(year)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"AMS cotton: season {season!r} is not an integral crop year; cannot derive a "
            f"leakage-safe release_date"
        ) from exc
    if not integral:
        raise ValueError(
            f"AMS cotton: season {season!r} is not an integral crop year; cannot derive a "
            f"leakage-safe release_date"
        )
    return f"{year + _RELEASE_YEAR_OFFSET:04d}-{_RELEASE_MONTH:02d}-{_RELEASE_DAY:02d}"


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
    # AMS-1: the derived PIT anchor. Always populated -- season is the pivot index, never null.
    df["release_date"] = [ams_release_date(s) for s in df["season"]]
    df = df.sort_values("season").reset_index(drop=True)

    result = df[SILVER_COLUMNS]
    if result.duplicated(subset=["commodity", "geography", "season"]).any():
        raise ValueError("AMS cotton silver: duplicate (commodity, geography, season) rows")
    if result["release_date"].isna().any():
        raise ValueError("AMS cotton silver: null release_date (the PIT anchor must never be null)")
    logger.info("AMS cotton silver: %d seasons (%s..%s)  release_date %s..%s  "
                "micronaire_nonnull=%d strength_nonnull=%d",
                len(result), int(result["season"].min()), int(result["season"].max()),
                result["release_date"].min(), result["release_date"].max(),
                int(result["avg_micronaire"].notna().sum()), int(result["avg_strength"].notna().sum()))
    return result
