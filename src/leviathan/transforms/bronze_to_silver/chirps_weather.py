"""bronze -> silver CHIRPS precipitation (LONG) + typed availability (SILVER-F044 narrowed).

F044 (narrowed to AVAILABILITY only; the all-NaN VALUE defect is SILVER-F045): a physical silver
partition must exist ONLY when >= 1 valid source observation exists. A 404 / not-yet-published date is
a typed *availability* result, never an all-null-filled map. The long transform already drops rows with
a null ``value`` (so an all-missing bronze melts to an empty frame and the writer creates no object),
which satisfies the existence rule; F044 makes the classification EXPLICIT and typed so a caller can
distinguish "published, real data" from "not yet published / empty" instead of inferring it from a row
count. It does NOT touch value validity -- a bronze that is present-but-all-NaN is F045's rebuild.
"""
from __future__ import annotations

from enum import Enum

import numpy as np
import pandas as pd

from leviathan.common.logging import get_logger
from leviathan.transforms.bronze_to_silver._weather_long import melt_weather_to_long
from leviathan.transforms.bronze_to_silver._weather_schema import CHIRPS_IS_PRELIMINARY

logger = get_logger(__name__)

# The '0'/'1' surface of the preliminary flag at silver. '1' = the day was read from the CHIRPS v2.0
# PRELIM product; '0' = from the authoritative FINAL block. A STRING and not a bool, per the
# ``gold_board_crush.is_roll_boundary`` precedent -- see ``_weather_schema`` for the mechanical reason.
_PRELIM_TRUE = "1"
_PRELIM_FALSE = "0"
_MERGE_KEYS = ["date", "country", "region", "source"]
# ``melt_weather_to_long``'s OWN dropna subset, quoted here so the two sides are the same list and not
# two lists that agree today. _preliminary_flags must drop on exactly this or a row the melt discards
# (a null ``year``, say) could still win the flags' ``keep='last'`` and flip a kept row's flag.
_MELT_DROPNA_SUBSET = ["date", "year", "month", "day", "country", "region"]


class WeatherAvailability(str, Enum):
    """Typed outcome of classifying a CHIRPS bronze read (F044)."""

    AVAILABLE = "available"                    # >= 1 valid (non-null value) observation -> write partition
    EMPTY_NO_VALID_OBS = "empty_no_valid_obs"  # present but zero valid observations -> write NOTHING
    NOT_PUBLISHED = "not_published"            # no bronze bytes at all (404 / not yet published)


def classify_availability(silver_long: pd.DataFrame | None) -> WeatherAvailability:
    """Classify a transformed long frame. ``None`` -> NOT_PUBLISHED (no source bytes); an empty frame
    -> EMPTY_NO_VALID_OBS (present but no valid obs -> no partition); otherwise AVAILABLE.

    This is the F044 guard: a partition is written iff this returns ``AVAILABLE``. It never fabricates
    a null-filled row for a missing date."""
    if silver_long is None:
        return WeatherAvailability.NOT_PUBLISHED
    if silver_long.empty:
        return WeatherAvailability.EMPTY_NO_VALID_OBS
    return WeatherAvailability.AVAILABLE


def _preliminary_flags(bronze: pd.DataFrame) -> pd.DataFrame | None:
    """The bronze ``is_preliminary`` flag, deduplicated onto the melt's own natural key.

    ``melt_weather_to_long`` projects ``SILVER_WEATHER_ID_COLS + [variable_col]`` and drops everything
    else, and it is SHARED with cpc_soil (whose id columns must not move), so the flag cannot ride
    through it -- it is re-attached here by a left merge on the melt's own dedup key. The coercions
    below mirror the melt's exactly -- ``date`` to ``.dt.date``, ``year``/``month``/``day`` through
    ``pd.to_numeric(errors='coerce').astype('Int64')``, the dropna over all SIX of
    :data:`_MELT_DROPNA_SUBSET`, and the same ``keep='last'`` -- so the two sides can never disagree
    about which duplicate won. The six matter and three would not: with a dropna over
    ``[date, country, region]`` only, a bronze row carrying a null ``year`` but a valid ``date`` is
    DROPPED by the melt and KEPT here, where ``keep='last'`` can hand it the merge key and flip the
    surviving row's flag. ``year``/``month``/``day`` are projected only to be dropped on; the returned
    frame is ``_MERGE_KEYS + [is_preliminary]`` and nothing else, so the merge shape is unchanged.

    Returns None when bronze does not carry the column at all -- a pre-prelim-lane partition, which the
    caller defaults to FINAL because prelim was unreachable when those bytes were written.

    CALLED AFTER ``melt_weather_to_long``, NEVER BEFORE IT. This projects the id columns, so on a frame
    missing one it raises a bare ``KeyError: "['source'] not in index"`` -- while the required-column
    contract that callers are promised (and that ``chirps_bronze_to_silver``'s docstring states) is the
    ``ValueError`` melt raises with the full missing set named. Running the melt first keeps the typed
    error first; the order is load-bearing, not incidental."""
    if CHIRPS_IS_PRELIMINARY not in bronze.columns:
        return None
    carried = [c for c in _MELT_DROPNA_SUBSET if c not in _MERGE_KEYS]
    flags = bronze.loc[:, _MERGE_KEYS + carried + [CHIRPS_IS_PRELIMINARY]].copy()
    flags["date"] = pd.to_datetime(flags["date"], errors="coerce").dt.date
    for col in ("year", "month", "day"):
        flags[col] = pd.to_numeric(flags[col], errors="coerce").astype("Int64")
    flags = flags.dropna(subset=_MELT_DROPNA_SUBSET)
    flags = flags.drop_duplicates(subset=_MERGE_KEYS, keep="last")
    return flags.loc[:, _MERGE_KEYS + [CHIRPS_IS_PRELIMINARY]]


def _to_prelim_string(series: pd.Series) -> pd.Series:
    """Native bool / 0-1 / '0'-'1' / NaN -> the pinned ``'0'``/``'1'`` string; anything unknown -> ``'0'``.

    NaN reaches here two ways and BOTH are honestly final: a legacy bronze row the left merge could not
    match, and a bronze partition minted before the prelim fetch existed. Prelim was unreachable when
    either was written, so ``'0'`` is a statement about those bytes and not a convenience.

    THE NULL TEST COMES FIRST, and it is not decoration. ``v == 1`` on a ``pd.NA`` returns ``pd.NA``,
    and ``or`` then calls ``bool()`` on it -- ``TypeError: boolean value of NA is ambiguous``, raised
    from the seam's ONLY coercion. Today's read path cannot produce one (``base_jobs._read_one`` uses
    ``pq.read_table(...).to_pandas()``, i.e. numpy bool or object+None, and a concat across pre-lane and
    post-lane partitions yields ``np.nan``), but ONE nullable- or Arrow-backed reader upstream would
    turn a null into a crash instead of a ``'0'``. ``pd.isna`` reads all three the same way."""
    truthy = series.map(_prelim_cell_truthy)
    return pd.Series([_PRELIM_TRUE if bool(t) else _PRELIM_FALSE for t in truthy],
                     index=series.index, dtype="object")


def _is_scalar_cell(v: object) -> bool:
    """True iff ``v == 1`` on this cell is guaranteed to yield a single, ``bool()``-able answer.

    ``np.ndim`` is the test and not ``isinstance``, so a reader that hands us some array-like nobody
    has thought of yet is still refused rather than compared. It is wrapped because ``np.ndim`` falls
    back to ``np.asarray(v).ndim``, which RAISES on a ragged list under numpy >= 1.24 -- a guard that
    raises while proving a cell cannot raise would be the whole defect again."""
    try:
        return np.ndim(v) == 0
    except Exception:  # noqa: BLE001 -- ragged / unconvertible => not a scalar, which is the answer
        return False


def _prelim_cell_truthy(v: object) -> bool:
    """One bronze ``is_preliminary`` cell -> bool. RAISES ON NOTHING, by construction.

    THE ORDER IS THE CONTRACT, and every step of it was driven over nine dtypes (native bool, numpy
    bool_, int, float, str, None, np.nan, pd.NA, list, ndarray):

    1. ``pd.isna(v) is True`` -- IDENTITY, never ``if pd.isna(v)``. On a list- or ndarray-valued cell
       pandas returns an ARRAY of per-element nulls, and ``bool()`` of that is itself the ambiguous
       truth value this whole function exists to avoid. The identity test reads a non-scalar answer as
       "not a null scalar" and falls through.
    2. ``v is True`` / ``isinstance(v, str)`` -- the two shapes today's writers actually produce
       (``chirps_to_bronze_task`` writes a native bool; a hand-written CSV writes ``'1'``).
    3. THE SCALAR GUARD, and this is the line the previous cut did not have. Reaching ``v == 1`` with
       an ndarray cell raises ``ValueError: The truth value of an array with more than one element is
       ambiguous`` -- MEASURED, not feared -- from the seam's ONLY coercion, i.e. the transform dies
       instead of writing a partition. A non-scalar cell is not a per-day flag, so it is '0', which is
       exactly what the pre-lane comparison chain did with a list (``[1, 2] == 1`` is plain ``False``).
       Unreachable from either bronze builder today; reachable from any future reader, and the cost of
       being wrong here is the producer, not one row.
    4. Only then ``v == 1``, on a value that cannot be anything but a single comparable."""
    if pd.isna(v) is True:
        return False
    if v is True:
        return True
    if isinstance(v, str):
        return v.strip() in ("1", "true", "True")
    if not _is_scalar_cell(v):
        return False
    return bool(v == 1)


def chirps_bronze_to_silver(df: pd.DataFrame, source_label: str = "dataframe") -> pd.DataFrame:
    """Apply silver cleaning rules to a CHIRPS bronze DataFrame.

    Returns a long/tidy DataFrame with one row per (date, region, variable).
    Columns: date, year, month, day, country, region, commodity, source, ingest_date, variable, value,
    is_preliminary.

    A row whose ``value`` (precipitation) is null is DROPPED (never written as a NaN-filled partition,
    F044). A valid 0.0 mm dry-day reading is a real observation and is retained.

    ``is_preliminary`` is ALWAYS emitted, as the ``'0'``/``'1'`` string the pinned silver schema
    declares, and defaults to ``'0'`` (final) for a bronze frame that does not carry it. Always, and
    not only when bronze has it, because ``_weather_schema.enforce_arrow_schema`` RAISES on a missing
    column: a transform that emitted the column conditionally would fail the writer closed on every
    legacy (commodity, month) the b2s job re-reads.
    """
    df = df.copy()
    # Clip only when present; the required-column contract (and its ValueError) is enforced inside
    # melt_weather_to_long, so a missing column must reach there rather than raising a bare KeyError.
    if "precipitation_mm" in df.columns:
        df["precipitation_mm"] = df["precipitation_mm"].clip(lower=0.0)
    # MELT FIRST, FLAGS SECOND. melt_weather_to_long enforces the required-column contract and raises
    # ValueError naming every missing column; _preliminary_flags projects those same id columns and
    # would raise a bare KeyError on the way past. It reads the ORIGINAL bronze frame either way --
    # melt copies its input and never mutates the caller's -- so the order costs nothing and buys the
    # typed error. (Measured: with the flags first, a frame missing `source` raised
    # KeyError "['source'] not in index" instead of the documented ValueError.)
    silver = melt_weather_to_long(df, "precipitation_mm", source_label)
    flags = _preliminary_flags(df)
    if flags is not None and not silver.empty:
        silver = silver.merge(flags, on=_MERGE_KEYS, how="left")
        silver[CHIRPS_IS_PRELIMINARY] = _to_prelim_string(silver[CHIRPS_IS_PRELIMINARY])
    else:
        silver[CHIRPS_IS_PRELIMINARY] = pd.Series(
            [_PRELIM_FALSE] * len(silver), index=silver.index, dtype="object")
    availability = classify_availability(silver)
    prelim_rows = int((silver[CHIRPS_IS_PRELIMINARY] == _PRELIM_TRUE).sum()) if len(silver) else 0
    logger.info(
        "CHIRPS silver transform: %d input rows -> %d long rows (availability=%s, preliminary=%d)",
        len(df), len(silver), availability.value, prelim_rows,
    )
    return silver
