"""Bronze transform for World Bank DataBank food CPI JSON files.

Parses the JSON response from the World Bank DataBank API for indicator
``FP.CPI.TOTL.ZG`` (Inflation, consumer prices, annual %) per country.

Data note
---------
``FP.CPI.TOTL.ZG`` is **overall** CPI annual percentage change, not a
food-specific sub-index.  World Bank does not publish a standardised
country-level food CPI series.  Overall CPI is used as a proxy because:

  - Food comprises 35–50% of the CPI basket in all four target countries
    (India, Russia, Indonesia, Ukraine) — see IMF COICOP weights.
  - Overall CPI and food CPI are highly correlated in these countries.
  - Governments respond to overall headline inflation, not food sub-indices.
  - This is the signal that precedes export restriction announcements.

Column names use ``cpi_yoy_pct`` (honest) rather than ``food_cpi_yoy_pct``
(the feature taxonomy name used for conceptual clarity in desiredstate.md).

API endpoint
------------
    https://api.worldbank.org/v2/country/{ISO3}/indicator/FP.CPI.TOTL.ZG
        ?format=json&date=1960:2025&per_page=200

Response structure (two-element JSON array):
    data[0] — metadata: {"page": 1, "pages": 1, "total": 66,
                          "lastupdated": "2026-07-13", ...}
    data[1] — records:  [{"countryiso3code": "IND", "date": "2024",
                           "value": 4.85, ...}, ...]

Records arrive newest-first.  ``value`` is null for years with no release.
Single page for all four countries (pages=1 confirmed in live testing).

Point-in-time anchors (D-LD, 2026-08-18)
----------------------------------------
The table had NO date column of any kind: eight physical columns, all of them
either an identity, a bigint calendar year or a measure.  Every PIT semantics
was therefore unavailable -- ``year_month`` needs a month column, ``data_date``
and ``ingest`` need a date column to point at, and comparing the bigint ``year``
to an ISO as-of string is a type error on both serving backends -- so every
agent lookup raised
``ValueError: table silver_food_cpi has no knowledge/date column to anchor the
as-of guard``.  Two columns are derived HERE, at the producer, the same
pre-step mechanism CONAB's ``survey_release_date`` and SAGIS's
``week_ending_date`` already use:

``data_date``
    ``'{year}-12-31'`` -- the year-end OBSERVATION date for the calendar year
    the row reports.  A pure function of ``year``; never a publication date.

``release_date``
    the World Bank's own ``lastupdated`` metadata field, which this parser
    already read and threw away (only ``pages`` was kept).  It is the source's
    own publication stamp for the WHOLE latest-only series -- one global value
    per release -- and it rides to serving as the row's provenance stamp.

Both are ISO ``YYYY-MM-DD`` strings and both are NON-NULL by contract: a PIT
anchor that can be null is not an anchor.  A response whose metadata carries no
usable ``lastupdated`` raises rather than defaulting -- a guessed release date
would silently mint provenance the publisher never asserted.

Countries ingested
------------------
    IND — India       (1960–present; food CPI driver: wheat, rice export bans)
    RUS — Russia      (1993–present; food CPI driver: wheat export quotas)
    IDN — Indonesia   (1960–present; food CPI driver: CPO export bans)
    UKR — Ukraine     (1993–present; food CPI driver: wheat/corn export risk)
"""
from __future__ import annotations

import json
import re

import pandas as pd

from leviathan.common.logging import get_logger

logger = get_logger(__name__)

BRONZE_COLUMNS: list[str] = [
    "country_iso",
    "country_name",
    "year",
    "cpi_yoy_pct",
    "source",
    # D-LD PIT anchors (derived, never published verbatim by the source as row fields).
    "data_date",
    "release_date",
]

#: The World Bank DataBank metadata key carrying the release stamp of the whole series.
RELEASE_DATE_META_KEY = "lastupdated"

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def observation_data_date(year: int) -> str:
    """The year-end OBSERVATION date for a calendar-year row: ``'{year}-12-31'``.

    A pure function of the reported year -- this is the date the observation is ABOUT, not the
    date it was published (that is :data:`RELEASE_DATE_META_KEY` -> ``release_date``).  Defined
    once here and reused by the silver transform so the two layers can never disagree.
    """
    y = int(year)
    if y < 1000 or y > 9999:
        raise ValueError(f"Food CPI: year {year!r} is not a 4-digit calendar year")
    return f"{y:04d}-12-31"


def release_date_from_meta(meta: object, country_iso: str) -> str:
    """Extract the World Bank release stamp (``lastupdated``) from the response metadata.

    Fails closed: the stamp is the table's provenance anchor and its publication-lag guard's only
    dated evidence, so a missing or non-ISO value raises rather than defaulting to today (which
    would let the as-of guard run ahead of a release we cannot date) or to null (a PIT anchor that
    can be null is not an anchor).
    """
    value = meta.get(RELEASE_DATE_META_KEY) if isinstance(meta, dict) else None
    text = str(value).strip() if value is not None else ""
    if not _ISO_DATE.match(text):
        raise ValueError(
            f"Food CPI {country_iso}: response metadata carries no usable "
            f"{RELEASE_DATE_META_KEY!r} release stamp (got {value!r}); refusing to guess a "
            f"publication date for the PIT guard"
        )
    return text


def extract_food_cpi_bronze(raw_bytes: bytes, country_iso: str) -> pd.DataFrame:
    """Parse a World Bank DataBank JSON response into bronze Parquet.

    Args:
        raw_bytes:   Raw bytes of the ``part-000.json`` file from S3.
        country_iso: ISO 3166-1 alpha-3 code for logging/validation,
                     e.g. ``"IND"``.

    Returns:
        DataFrame with columns :data:`BRONZE_COLUMNS`.  One row per year,
        oldest first.  Years with no release have ``cpi_yoy_pct = NaN``, but
        ``data_date`` / ``release_date`` are non-null on EVERY row (a published
        absence is still an observation of that country-year).

    Raises:
        ValueError: If the response is not a valid two-element array, contains
                    no records, or carries no usable ``lastupdated`` stamp.
    """
    try:
        data = json.loads(raw_bytes.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"Food CPI {country_iso}: invalid JSON — {exc}") from exc

    if not isinstance(data, list) or len(data) < 2:
        raise ValueError(
            f"Food CPI {country_iso}: unexpected response structure "
            f"(expected 2-element array, got {type(data).__name__})"
        )

    meta    = data[0]
    records = data[1]

    if not isinstance(records, list) or not records:
        raise ValueError(
            f"Food CPI {country_iso}: empty records array in response"
        )

    # Read the release stamp BEFORE parsing rows: it is a property of the whole response, and a
    # response we cannot date must not produce bronze at all (fail closed, never a guessed stamp).
    release_date = release_date_from_meta(meta, country_iso)

    rows: list[dict] = []
    for rec in records:
        year_str = rec.get("date")
        value    = rec.get("value")
        iso3     = rec.get("countryiso3code", country_iso)
        name     = rec.get("country", {}).get("value", "")

        try:
            year = int(year_str)
        except (TypeError, ValueError):
            logger.warning("Food CPI %s: unparseable date %r — skipping", country_iso, year_str)
            continue

        rows.append({
            "country_iso":  iso3,
            "country_name": name,
            "year":         year,
            "cpi_yoy_pct":  float(value) if value is not None else None,
            # PIT anchors: the year-end observation date this row is ABOUT, and the release that
            # published it. Non-null on every row, including the published-absence rows.
            "data_date":    observation_data_date(year),
            "release_date": release_date,
        })

    if not rows:
        raise ValueError(f"Food CPI {country_iso}: no parseable records")

    df = pd.DataFrame(rows)
    df["cpi_yoy_pct"] = df["cpi_yoy_pct"].astype("float32")
    df["source"] = "wb_food_cpi"

    df = (
        df[BRONZE_COLUMNS]
        .sort_values("year")
        .reset_index(drop=True)
    )

    non_null = int(df["cpi_yoy_pct"].notna().sum())
    pages    = meta.get("pages", "?")
    logger.info(
        "Food CPI bronze %s: %d rows  non-null=%d  range=%d-%d  pages=%s  release_date=%s",
        country_iso,
        len(df),
        non_null,
        int(df["year"].min()),
        int(df["year"].max()),
        pages,
        release_date,
    )
    return df
