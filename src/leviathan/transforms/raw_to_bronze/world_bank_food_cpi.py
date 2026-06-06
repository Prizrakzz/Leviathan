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
    data[0] — metadata: {"page": 1, "pages": 1, "total": 66, ...}
    data[1] — records:  [{"countryiso3code": "IND", "date": "2024",
                           "value": 4.85, ...}, ...]

Records arrive newest-first.  ``value`` is null for years with no release.
Single page for all four countries (pages=1 confirmed in live testing).

Countries ingested
------------------
    IND — India       (1960–present; food CPI driver: wheat, rice export bans)
    RUS — Russia      (1993–present; food CPI driver: wheat export quotas)
    IDN — Indonesia   (1960–present; food CPI driver: CPO export bans)
    UKR — Ukraine     (1993–present; food CPI driver: wheat/corn export risk)
"""
from __future__ import annotations

import json

import pandas as pd

from leviathan.common.logging import get_logger

logger = get_logger(__name__)

BRONZE_COLUMNS: list[str] = [
    "country_iso",
    "country_name",
    "year",
    "cpi_yoy_pct",
    "source",
]


def extract_food_cpi_bronze(raw_bytes: bytes, country_iso: str) -> pd.DataFrame:
    """Parse a World Bank DataBank JSON response into bronze Parquet.

    Args:
        raw_bytes:   Raw bytes of the ``part-000.json`` file from S3.
        country_iso: ISO 3166-1 alpha-3 code for logging/validation,
                     e.g. ``"IND"``.

    Returns:
        DataFrame with columns :data:`BRONZE_COLUMNS`.  One row per year,
        oldest first.  Years with no release have ``cpi_yoy_pct = NaN``.

    Raises:
        ValueError: If the response is not a valid two-element array or
                    contains no records.
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
        "Food CPI bronze %s: %d rows  non-null=%d  range=%d–%d  pages=%s",
        country_iso,
        len(df),
        non_null,
        int(df["year"].min()),
        int(df["year"].max()),
        pages,
    )
    return df
