"""Deproject + within-year COMPACTION for the weather trio (SILVER-F047, Milestone R2).

THE MISSING WRITER (Attack 2 finding #2, CONFIRMED-BROKEN). ``bronze_to_silver_chirps_task.py`` (and
its nasa/cpc siblings) have ONLY the projected MONTH-grain writer -- one ~9 KB object per
commodity x country x region x year x MONTH, ~590k tiny files across the trio. A plain
``--force-overwrite`` value rebuild fixes the NaN values but re-mints that same tiny-file layout. The
value rebuild and the deproject+compact are genuinely TWO operations; this module is the second one:
it merges the twelve monthly objects of a (commodity, year) into ONE registered-partition object.

TARGET LAYOUT (the coarse registered grain): ``commodity=<c>/year=<y>/part-000.parquet`` --
``country`` / ``region`` / ``month`` become in-file physical columns (they already are), and the
registered Glue partition keys collapse to ``[commodity, year]`` (~1,400 partitions/table vs ~590k
tiny files). Registered MONTH-grain is rejected (~590k catalog entries would make ``get-partitions``
itself slow, INV-3).

THE ``year=`` INVARIANT (Attack 3 finding #3, CONFIRMED-BROKEN). The feature extractor bounds every
weather read by parsing ``year=`` out of the S3 key (``extractors.py`` ``_YEAR_PARTITION_RE`` /
``_year_from_path``; a file lacking a ``year=`` segment is skipped and the probe returns "structural
missingness" -> silently NaNs every weather feature). So compaction MUST stay WITHIN year and preserve
the ``year=YYYY/`` path segment. :func:`compacted_silver_key` and :func:`compaction_plan` enforce this;
:func:`assert_year_segment_preserved` is the guard the tests assert.

Pure + AWS-free + ASCII only. The batch job (jobs/batch/compact_weather_silver_task.py) does S3 I/O and
routes every write through the F015 shadow publisher + F013 registered-partition publisher (gated;
default dry-run). This module only decides WHAT to compact and validates the layout.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import pandas as pd
import pyarrow as pa

from leviathan.transforms.bronze_to_silver._weather_schema import (
    CHIRPS_IS_PRELIMINARY,
    NASA_POWER_COMPACTED_SCHEMA,
    schema_for,
    to_parquet_bytes,
)

# The registered partition keys of the compacted layout (the coarse target).
COMPACTED_PARTITION_KEYS = ["commodity", "year"]

# Natural key each compacted object dedups on (within its commodity+year). WIDE has no ``variable``;
# LONG carries it. We include both and intersect with present columns at runtime.
_NATURAL_KEY_CANDIDATES = ["country", "region", "date", "variable"]

# Producer-additive columns a HISTORICAL frame may simply not have, and the value that is TRUE of those
# bytes when it does not. ``'0'`` (final) for ``is_preliminary``: the CHIRPS prelim product was
# unreachable when every pre-2026-09-15 silver object was written, so defaulting a missing column to
# "final" states a fact about the parquet rather than filling a hole.
_ADDITIVE_BACKFILL: dict[str, str] = {CHIRPS_IS_PRELIMINARY: "0"}

# The preliminary flag's POLARITY, stated because the NAME IS INVERTED relative to the winner:
# ``is_preliminary`` TRUE ('1') is the row that must LOSE to its final ('0') sibling. Sorting ascending
# on the flag and taking ``keep="last"`` therefore keeps... the PRELIM row. So the sort is DESCENDING:
# '1' first, '0' last, keep-last keeps the FINAL. '0'/'1' strings order the same way lexicographically
# as numerically, which is part of why the string surface was chosen.
_PRELIM_WINS_LAST_ASCENDING = False

_YEAR_SEGMENT_RE = re.compile(r"(?:^|/)year=(\d{4})(?:/|$)")


def compacted_silver_key(source: str, commodity: str, year: int) -> str:
    """The coarse registered-partition object key for one (commodity, year). Preserves ``year=``.

    ``silver/weather/source=<source>/commodity=<commodity>/year=<year>/part-000.parquet`` -- NO
    country/region/month path segments (they are in-file columns now), but the ``year=`` segment the
    feature extractor depends on SURVIVES."""
    return (
        f"silver/weather/source={source}/commodity={commodity}"
        f"/year={int(year)}/part-000.parquet"
    )


def assert_year_segment_preserved(key: str) -> int:
    """Return the year parsed from a compacted key, or raise if the ``year=`` segment is missing.

    This is the F047 guard that a compaction grain never drops ``year=`` (which would make the feature
    extractor return zero paths and silently NaN every weather feature -- the exact CHIRPS-class
    failure this plan exists to prevent)."""
    m = _YEAR_SEGMENT_RE.search(key.replace("\\", "/"))
    if not m:
        raise ValueError(
            f"compacted key {key!r} has no 'year=' segment -- would break bounded weather extraction "
            f"(extractors._year_from_path). F047 forbids a coarser-than-year grain."
        )
    return int(m.group(1))


def compact_partition(frames: list[pd.DataFrame], table_name: str) -> pd.DataFrame:
    """Merge the monthly frames of ONE (commodity, year) into a single deduplicated compacted frame.

    ``frames`` are the per-month projected silver frames (already the correct long/wide shape).
    Returns a frame with the SAME columns as the pinned schema for ``table_name`` (a strict superset
    of the natural key), sorted, with exact natural-key duplicates collapsed (keep-last). Raises on an
    empty input (an empty year is never written -- F044 existence rule carried into compaction).

    THE ADDITIVE BACKFILL IS LOAD-BEARING, NOT TIDINESS (2026-09-15). ``enforce_arrow_schema`` RAISES on
    a missing column -- "fails closed rather than writing an inference-typed object" -- and ``reindex``
    below inserts NaN for a column a frame lacks. So the moment ``CHIRPS_LONG_SCHEMA`` gained
    ``is_preliminary``, EVERY compaction of a pre-existing (commodity, year) would have raised, because
    no 1981-2026 canonical object carries it: silver_chirps would have stopped advancing entirely, which
    is the freeze class this whole arc exists to end. The backfill happens BEFORE the reindex precisely
    so that no NaN is ever handed to a schema with no boolean branch to cast it.

    AND THE SUPERSESSION IS EXPLICIT, NOT POSITIONAL. A fresh FINAL row beating a stale PRELIM row used
    to depend on list-concatenation order alone (the caller passes canonical frames before staging
    frames, and ``keep="last"`` happens to favour the later one); ``is_preliminary`` is not in the
    natural key and could not break the tie. One ``sorted()`` added for determinism, or a parallel read
    that returned frames in a different order, would have flipped it and let a PRELIM row overwrite a
    FINAL one -- silently, with no error and no census signal. The flag is now part of the pre-dedup
    sort, so the final wins regardless of frame order."""
    non_empty = [f for f in frames if f is not None and not f.empty]
    if not non_empty:
        raise ValueError("compact_partition: no non-empty monthly frames to compact")
    df = pd.concat(non_empty, ignore_index=True)
    schema = schema_for(table_name)
    cols = [f.name for f in schema]
    for name, default in _ADDITIVE_BACKFILL.items():
        if name in cols:
            if name not in df.columns:
                df[name] = default
            else:
                df[name] = df[name].where(df[name].notna(), default)
    key = [c for c in _NATURAL_KEY_CANDIDATES if c in df.columns]
    if key:
        prelim_col = CHIRPS_IS_PRELIMINARY if CHIRPS_IS_PRELIMINARY in df.columns else None
        if prelim_col is not None:
            # DESCENDING on the flag: '1' (preliminary) first, '0' (final) LAST, so keep-last keeps the
            # FINAL row whatever order the frames arrived in. kind="stable" so rows that tie on the flag
            # keep their incoming order and the pre-lane keep-last behaviour is otherwise untouched.
            df = df.sort_values(key + [prelim_col],
                                ascending=[True] * len(key) + [_PRELIM_WINS_LAST_ASCENDING],
                                kind="stable")
        df = df.drop_duplicates(subset=key, keep="last")
    sort_cols = [c for c in ("country", "region", "date", "variable") if c in df.columns]
    if sort_cols:
        df = df.sort_values(sort_cols).reset_index(drop=True)
    # Reindex to the pinned schema column set (drops the partition-only ``commodity`` for nasa WIDE).
    return df.reindex(columns=cols)


def compacted_bytes(df: pd.DataFrame, table_name: str) -> bytes:
    """Serialise a compacted frame to snappy parquet under the pinned INV-2 schema for ``table_name``."""
    return to_parquet_bytes(df, schema_for(table_name))


@dataclass(frozen=True)
class CompactionUnit:
    """One compaction output: which (commodity, year), its final registered key + partition values,
    and how many monthly source objects it collapses (the file-count-collapse evidence)."""

    source: str
    table_name: str
    commodity: str
    year: int
    canonical_key: str
    partition_values: list[str]
    source_month_objects: int

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "table": self.table_name,
            "commodity": self.commodity,
            "year": self.year,
            "canonical_key": self.canonical_key,
            "partition_values": self.partition_values,
            "source_month_objects": self.source_month_objects,
        }


def compaction_plan(
    source: str,
    table_name: str,
    commodity: str,
    month_keys_by_year: dict[int, list[str]],
) -> list[CompactionUnit]:
    """Build the per-(commodity, year) compaction plan from a map of year -> its month object keys.

    Pure planning (no I/O): the caller LISTs the projected month objects and buckets them by the
    ``year=`` in each key; this turns that bucketing into the ordered set of compaction units, each
    validated to preserve the ``year=`` segment."""
    units: list[CompactionUnit] = []
    for year in sorted(month_keys_by_year):
        canonical_key = compacted_silver_key(source, commodity, year)
        assert_year_segment_preserved(canonical_key)
        units.append(
            CompactionUnit(
                source=source,
                table_name=table_name,
                commodity=commodity,
                year=int(year),
                canonical_key=canonical_key,
                partition_values=[commodity, str(int(year))],
                source_month_objects=len(month_keys_by_year[year]),
            )
        )
    return units


def compacted_schema(table_name: str) -> pa.Schema:
    """The pinned arrow schema of the compacted object (identical columns to the projected object --
    compaction merges files, it never changes the column set)."""
    if table_name == "silver_nasa_power":
        return NASA_POWER_COMPACTED_SCHEMA
    return schema_for(table_name)
