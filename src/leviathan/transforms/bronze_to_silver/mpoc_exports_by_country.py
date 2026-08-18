"""SILVER-F053: MPOC exports-by-country producer (silver_mpoc_exports_by_country).

Grain: ``year x country``. Consumes the "Exports to Major Countries" table off each annual MPOC
Trade Statistics page (parsed by the F052 adapter). Normalizes country names + numeric units and
resolves ONLY exact duplicates (an identical (year, country, exports_mt) triple that appears twice
is collapsed; a CONFLICTING value for the same key fails closed).

D-LD TRANCHE 2 (2026-08-18) PIT-ANCHOR PRE-STEP
-----------------------------------------------
The table shipped as four columns (``year``, ``country``, ``exports_mt``, ``source``) -- no date, no
month, no vintage. That made it STRUCTURALLY unservable to the numbers lane: ``TableSpec.knowledge_col()``
has nothing to return and ``query._guard`` raises on every read, which is why D-PQ tranche 1a refused
it (tests/unit/test_dpq_dark_tables.py, reason ``"guard"``). The remedy is the WIRING-WAVE-1 idiom
``silver_sagis_weekly_exports`` used for ``week_ending_date`` and ``silver_conab_coffee`` for
``survey_release_date``: ONE producer-derived column.

``year_ending_date`` = ``date(year, 12, 31)`` -- the PERIOD END of the calendar year the row measures,
held as a python ``datetime.date`` so the flat publisher encodes it ``date32[day]`` per the INV-2
contract. It is deliberately the period end and NOT a guessed publication date: the publication guess
belongs in the card's ``publication_lag_days`` (+60d), where it is auditable and tunable, not baked
irreversibly into the data. MPOC's Jan-Dec destination table for year Y prints the FOLLOWING January,
so data_date + 60d makes year Y citable from (Y+1)-03-01 -- never early, at most ~6 weeks late.

NOTE ON THE PLAN ROW: the D-LD plan designated this table ``wide/year_month``. It is not and cannot
be -- there is no month column here (that is the sibling ``silver_mpoc_trade_stats_monthly``), and
``year_month`` semantics raise without BOTH ``year_col`` and ``month_col``. The corrected designation
is ``data_date`` on ``year_ending_date``.

Pure + AWS-free. The batch task (jobs/batch/mpoc_exports_by_country_silver_task.py) wires the F052
adapter (raw HTML -> tables) + the SILVER-F015 publisher; this module is only the transform.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Optional

import pandas as pd

from leviathan.common.logging import get_logger
from leviathan.silver.mpoc.adapter import (
    NormalizedTable,
    diagnose_table_drift,
    find_table_by_header,
    normalize_country,
    parse_number,
)

logger = get_logger(__name__)

# v2 (D-LD tranche 2): APPENDED ``year_ending_date`` -- the derived PIT anchor (see the module
# docstring). Appended LAST so the four original columns keep their declaration order; the F010
# contract's physical_columns must gain the same 5th entry (date32[day]) before a re-run, because
# flat_producer.encode_parquet fails closed on a DataFrame column the contract does not declare.
OUTPUT_COLUMNS: list[str] = ["year", "country", "exports_mt", "source", "year_ending_date"]

# Table resolution + the required header the F052 drift check enforces on each year page.
#
# The live MPOC pages no longer carry a per-table "Exports to Major Countries" heading (all section
# titles sit in the tab-widget nav, ahead of every panel), so identity-by-heading resolves the wrong
# table or none at all. The country-grain tables are instead identified by a first header cell that
# reads COUNTRY; the "Exports to Major Countries" table is the FIRST such table, ahead of the
# trailing full-destination list (which shares the same header). See find_table_by_header.
_EXPORTS_FIRST_COL = "country"
_EXPORTS_REQUIRED_COLUMNS = ["country"]

# Countries that are aggregate rollups, not real destinations -- excluded from the country grain.
_AGGREGATE_COUNTRIES = {"total", "others", "world"}


@dataclass(frozen=True)
class MpocExportsRelease:
    """One annual MPOC Trade Statistics page's normalized tables + its provenance."""

    year: int
    tables: list[NormalizedTable]
    source: str = "mpoc"


class MpocDriftError(ValueError):
    """A year page's layout drifted from the expected exports-table contract (fail closed)."""


class MpocConflictError(ValueError):
    """The same natural key carried two different values across the input (fail closed)."""


def _exports_column_index(table: NormalizedTable, year: int) -> int:
    """Pick the header column holding THIS year's exports value.

    Preference order: a header cell naming the page year; else the last column whose header
    mentions exports/tonnes/mt; else the last column. Column 0 is always the country label."""
    header_l = [h.lower() for h in table.header]
    for i, h in enumerate(header_l):
        if i == 0:
            continue
        if str(year) in h:
            return i
    for i in range(len(header_l) - 1, 0, -1):
        if any(tok in header_l[i] for tok in ("export", "tonne", "mt", "volume")):
            return i
    return len(table.header) - 1 if len(table.header) > 1 else 1


def _rows_for_release(release: MpocExportsRelease) -> list[dict]:
    table = find_table_by_header(release.tables, first_col=_EXPORTS_FIRST_COL)
    drift = diagnose_table_drift(
        table,
        expected_columns=_EXPORTS_REQUIRED_COLUMNS,
    )
    if drift:
        raise MpocDriftError(
            f"MPOC exports {release.year}: layout drift {[d.to_dict() for d in drift]}"
        )
    assert table is not None  # drift check guarantees it
    col = _exports_column_index(table, release.year)
    year = int(release.year)
    # The derived PIT anchor: the period END of the calendar year this page measures. Computed ONCE
    # per release (every row on a year page shares it) and held as a python ``datetime.date`` so the
    # flat publisher encodes date32[day] under the contract's INV-2 target type.
    year_ending_date = dt.date(year, 12, 31)
    out: list[dict] = []
    unmapped: list[str] = []
    for row in table.rows:
        if not row:
            continue
        country = normalize_country(row[0])
        if country is None:
            # OBSERVABILITY, not a behaviour change: a label the vocabulary cannot map is still
            # skipped, but it is no longer skipped SILENTLY. This is the class that cost 9 rows
            # (CHINA P.R / U.S.A) undetected for the table's whole life -- an absent country reads
            # to a desk as "stopped buying", so the drop must at minimum leave a trace.
            unmapped.append(str(row[0]))
            continue
        if country in _AGGREGATE_COUNTRIES:
            continue
        value = parse_number(row[col]) if col < len(row) else None
        out.append({
            "year": year,
            "country": country,
            "exports_mt": value,
            "source": release.source,
            "year_ending_date": year_ending_date,
        })
    if unmapped:
        logger.warning(
            "MPOC exports %d: %d country label(s) outside the canonical vocabulary were dropped: %s",
            year, len(unmapped), unmapped,
        )
    return out


def transform_exports_by_country(releases: list[MpocExportsRelease]) -> pd.DataFrame:
    """Transform a set of annual MPOC exports pages into the silver exports-by-country table.

    Exact duplicates (identical value for a (year, country) key) are collapsed; a conflicting
    value for the same key raises :class:`MpocConflictError`. Rows are sorted (year, country)."""
    records: list[dict] = []
    for rel in releases:
        records.extend(_rows_for_release(rel))
    if not records:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    df = pd.DataFrame.from_records(records)
    # Resolve ONLY exact duplicates; a conflicting value for the same key is a hard error.
    conflicts: list[tuple] = []
    keep_idx: list[int] = []
    seen: dict[tuple, Optional[float]] = {}
    for idx, r in df.iterrows():
        key = (r["year"], r["country"])
        val = r["exports_mt"]
        if key not in seen:
            seen[key] = val
            keep_idx.append(idx)
        else:
            prev = seen[key]
            same = (prev == val) or (pd.isna(prev) and pd.isna(val))
            if not same:
                conflicts.append((key, prev, val))
    if conflicts:
        raise MpocConflictError(f"conflicting exports values for keys: {conflicts}")

    df = df.loc[keep_idx].sort_values(["year", "country"]).reset_index(drop=True)
    return df[OUTPUT_COLUMNS]
