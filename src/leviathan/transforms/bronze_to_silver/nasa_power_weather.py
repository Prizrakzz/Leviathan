"""bronze -> silver NASA POWER: canonical WIDE producer (SILVER-F021, Milestone R2).

C-WRONG-7 / F021: the LIVE silver_nasa_power parquet/Glue/DDL are WIDE -- one row per
(commodity[path], country, region, year, month, date) with the six measurement columns as columns and
``source_file_name`` retained (15 physical parquet columns). The prior transform MELTED to a
``variable``/``value`` LONG shape and dropped ``source_file_name`` -- so a rebuild would have written a
schema that does not match the catalog. This module restores the canonical wide projection:

  * explicit ordered wide output matching ``silver_nasa_power.sql`` / the F010 registry contract;
  * ``source_file_name`` preserved;
  * NASA missing sentinels (-999 family) scrubbed to NaN (a fill code is never a real reading);
  * an UNKNOWN raw parameter fails closed (never silently melted into a mystery variable); solar
    radiation is intentionally NOT added (a separate additive-schema decision);
  * conflicting duplicate natural keys (same date/country/region/source, different measures) fail
    closed rather than a silent keep-last;
  * the INV-2 pinned pyarrow writer schema (``_weather_schema.NASA_POWER_WIDE_SCHEMA``) is the single
    write authority -- the batch task writes THROUGH it, no ``df.to_parquet`` inference.

Pure + AWS-free. ``clean_one_weather_df`` (the old long entrypoint) is retained as a thin, explicitly
deprecated shim that raises, so no caller silently gets the wrong shape.
"""
from __future__ import annotations

import pandas as pd

from leviathan.common.logging import get_logger
from leviathan.transforms.bronze_to_silver._weather_schema import (
    ACCEPTED_NASA_PARAMS,
    NASA_EXCLUDED_PARAMS,
    NASA_WIDE_MEASURE_COLS,
    scrub_sentinels,
)

logger = get_logger(__name__)

# Back-compat export: some tests/callers import the rename map. It is the ACCEPTED (canonical) set;
# solar is excluded from the wide contract on purpose (F021).
WEATHER_RENAME_MAP = dict(ACCEPTED_NASA_PARAMS)

# The ordered WIDE silver output columns (matches the R0 baseline arrow_columns exactly; commodity is
# NOT written -- it lives only in the S3 path partition).
WIDE_ID_COLS = [
    "date",
    "year",
    "month",
    "day",
    "country",
    "region",
    "source",
    "ingest_date",
    "source_file_name",
]
WIDE_OUTPUT_COLS = WIDE_ID_COLS + NASA_WIDE_MEASURE_COLS

# Bronze id columns that must be present (commodity is required in bronze for grouping upstream but is
# dropped from the wide silver parquet -- it is the partition dir).
_REQUIRED_BRONZE_ID = {"date", "year", "month", "day", "country", "region", "commodity", "source"}
_DEDUP_KEY = ["date", "country", "region", "source"]


class ConflictingWeatherKeys(ValueError):
    """Two bronze rows share a (date, country, region, source) key but disagree on a measurement."""


def nasa_power_bronze_to_silver(
    df: pd.DataFrame,
    source_label: str = "dataframe",
    *,
    strict_params: bool = True,
) -> pd.DataFrame:
    """Clean a NASA POWER bronze DataFrame into the canonical WIDE silver shape (F021).

    Returns a DataFrame with EXACTLY ``WIDE_OUTPUT_COLS`` in order, one row per
    (date, country, region, source) within the commodity partition. Raises:

      * ``ValueError`` if a required bronze id column is missing;
      * ``ValueError`` (``strict_params``) if a raw parameter column is neither an accepted canonical
        parameter nor a known-excluded one (an unknown unit/parameter must not be silently dropped);
      * ``ConflictingWeatherKeys`` if two rows with the same natural key disagree on any measurement.
    """
    missing = _REQUIRED_BRONZE_ID - set(df.columns)
    if missing:
        raise ValueError(f"Missing required NASA POWER bronze columns in {source_label}: {missing}")

    df = df.copy()

    # 1. Rename accepted raw parameters to canonical measurement columns; validate the raw vocabulary.
    known_raw = set(ACCEPTED_NASA_PARAMS) | set(NASA_EXCLUDED_PARAMS)
    id_like = _REQUIRED_BRONZE_ID | {"ingest_date", "source_file_name"}
    unknown = [
        c for c in df.columns
        if c not in id_like and c not in known_raw and c not in NASA_WIDE_MEASURE_COLS
    ]
    if unknown and strict_params:
        raise ValueError(
            f"Unknown NASA POWER parameter column(s) in {source_label}: {unknown} "
            f"(accepted raw: {sorted(ACCEPTED_NASA_PARAMS)}; excluded: {sorted(NASA_EXCLUDED_PARAMS)})"
        )
    df = df.rename(columns=ACCEPTED_NASA_PARAMS)
    # Drop the deliberately-excluded parameters (solar) if present.
    df = df.drop(columns=[c for c in NASA_EXCLUDED_PARAMS.values() if c in df.columns], errors="ignore")

    # 2. Coerce id types + scrub sentinels on measurement columns.
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    for c in ("year", "month", "day"):
        df[c] = pd.to_numeric(df[c], errors="coerce").astype("Int64")
    for col in NASA_WIDE_MEASURE_COLS:
        if col in df.columns:
            df[col] = scrub_sentinels(df[col])
        else:
            df[col] = pd.Series(pd.NA, index=df.index, dtype="float64")

    # 3. Provenance columns that may be absent in a minimal bronze fixture.
    if "ingest_date" not in df.columns:
        df["ingest_date"] = pd.NA
    if "source_file_name" not in df.columns:
        df["source_file_name"] = pd.NA

    # 4. Drop rows lacking any required id (date/year/month/day/country/region).
    df = df.dropna(subset=["date", "year", "month", "day", "country", "region"])
    for c in ("year", "month", "day"):
        df[c] = df[c].astype(int)

    # 5. Reject conflicting duplicate natural keys (differing measures); collapse exact duplicates.
    _reject_conflicting_keys(df, source_label)
    df = df.drop_duplicates(subset=_DEDUP_KEY, keep="last")

    silver = df.reindex(columns=WIDE_OUTPUT_COLS)
    silver = silver.sort_values(["country", "region", "date"]).reset_index(drop=True)
    logger.info(
        "NASA POWER wide silver: %d input rows -> %d wide rows (%d measure cols)",
        len(df), len(silver), len(NASA_WIDE_MEASURE_COLS),
    )
    return silver


def _reject_conflicting_keys(df: pd.DataFrame, source_label: str) -> None:
    measures = [c for c in NASA_WIDE_MEASURE_COLS if c in df.columns]
    if not measures:
        return
    # A key is conflicting when its rows carry >1 distinct non-null value in any measurement column.
    grouped = df.groupby(_DEDUP_KEY, dropna=False)
    for col in measures:
        distinct = grouped[col].nunique(dropna=True)
        bad = distinct[distinct > 1]
        if len(bad):
            first = bad.index[0]
            raise ConflictingWeatherKeys(
                f"{source_label}: conflicting NASA POWER measurements for key {dict(zip(_DEDUP_KEY, first))} "
                f"on column {col!r} ({int(bad.iloc[0])} distinct values); refuse silent keep-last"
            )


def clean_one_weather_df(df: pd.DataFrame, source_label: str = "dataframe") -> pd.DataFrame:  # noqa: D401
    """DEPRECATED (F021): the long melt is retired. NASA POWER silver is WIDE.

    Kept only to fail loudly so a stale caller does not silently produce the wrong (long) shape.
    Use :func:`nasa_power_bronze_to_silver`.
    """
    raise NotImplementedError(
        "clean_one_weather_df (long melt) was retired by SILVER-F021: silver_nasa_power is WIDE. "
        "Call nasa_power_bronze_to_silver(df) instead."
    )
