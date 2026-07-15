"""Canonical value census (SILVER-V001, Milestone R1).

WHY THIS EXISTS
---------------
Every schema/path/partition/idempotency gate in the readiness campaign passes on
100%-NaN data. CHIRPS certified GREEN while its ``value`` column was entirely
null for 9 of 11 commodities (C-ADD-1); the ESR serving copy collapsed to a single
``as_of_date`` vintage (distinct == 1) and no gate noticed. The value census is the
gate that distinguishes "present + certified" from "actually usable": per
value/numeric column per table it computes, from the parquet **FOOTER row-group
statistics only** (``null_count`` / ``min`` / ``max`` / ``num_rows`` -- NO page
reads, NO Athena), the null-fraction, an all-constant flag, sentinel saturation,
min/max, and a footer-derived lower bound on the distinct count.

MECHANISM (Attack 3, finding #5 -- corrected)
---------------------------------------------
The PRIMARY path is parquet footer statistics, and it applies to EVERY non-ML
table uniformly (the ~31 flat feature-only tables that have no pg mirror are
covered exactly the same way as the 7 mirrored ones). The pg-mirror
``count(value)/count(*)`` path is reserved purely as an optimisation for the 7
mirrored tables and is NOT required for a table to have a ``value_census.json``.
For the projection trio (nasa_power / chirps / cpc_soil) the footer path is the
ONLY path -- INV-3: the census NEVER issues ``start-query-execution`` against a
projection table (there is no Athena client anywhere in this module or its
runner).

This module is PURE + AWS-free: it consumes ``pyarrow`` ``FileMetaData`` footer
objects (which the runner reads via a bounded range-GET, and which unit tests
build from local parquet), and the F010 registry fields ``value_columns`` /
``min_nonnull_frac`` (the single authority, Attack 3 finding #6). It reads no
S3, opens no socket, and prints nothing. ASCII only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Optional, Sequence

# ---------------------------------------------------------------------------
# Sentinel vocabulary. A footer can only prove *saturation* of a sentinel when a
# column is all-constant AT the sentinel (min == max == sentinel); per-value
# sentinel counting would require page/body reads, which the footer path forbids.
# 0.0 is deliberately NOT a sentinel: a legitimately-zero measure (e.g. a dry
# CHIRPS day) must not be mistaken for a missing-value code.
# ---------------------------------------------------------------------------
DEFAULT_SENTINELS: tuple[float, ...] = (
    -999.0,
    -9999.0,
    -99999.0,
    -999999.0,
    9999.0,
    99999.0,
    1e20,
    -1e20,
    9.969209968386869e36,  # common netCDF/GRIB _FillValue
)

# Gate-row kinds (the hard-fail taxonomy an R4 exit criterion consumes).
KIND_ALL_NAN = "all_nan"                       # every present value is NaN/null -> unusable
KIND_NONNULL_BELOW_FLOOR = "nonnull_below_floor"  # non-null fraction < min_nonnull_frac
KIND_SINGLE_VINTAGE = "single_vintage"         # distinct(knowledge_date_col) == 1
KIND_ALL_CONSTANT = "all_constant"             # a value column has zero variance table-wide
KIND_SENTINEL_SATURATED = "sentinel_saturated"  # value column saturated at a sentinel
KIND_STATS_UNAVAILABLE = "stats_unavailable"   # footer carried no statistics -> cannot certify


def _coerce(v: Any) -> Any:
    """Normalise a footer min/max value to a comparable Python scalar (bytes -> str)."""
    if isinstance(v, (bytes, bytearray)):
        try:
            return bytes(v).decode("utf-8", "replace")
        except Exception:  # noqa: BLE001 -- defensive; a non-utf8 stat is still comparable as repr
            return repr(v)
    return v


# ---------------------------------------------------------------------------
# Per-file footer extraction (the only place that touches a pyarrow object).
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class FileColumnStat:
    """Aggregated footer statistics for ONE column within ONE parquet file.

    ``has_min_max`` is False when parquet wrote no comparable min/max for the
    column -- which, for a column whose non-null count is positive, means every
    present value is NaN (parquet excludes NaN from min/max). That is exactly how
    an all-NaN float column (stored as float NaN, not as null) is detected from
    the footer without reading a single data page.
    """

    column: str
    total_rows: int
    null_count: int
    has_min_max: bool
    min_value: Any = None
    max_value: Any = None
    has_stats: bool = True

    @property
    def effective_nonnull(self) -> int:
        """Present, non-NaN values. If parquet has no min/max but rows are present
        and not all null, those present values are all NaN -> effectively missing."""
        present = self.total_rows - self.null_count
        if present <= 0:
            return 0
        return present if self.has_min_max else 0


def file_column_stat(file_metadata: Any, column: str) -> Optional[FileColumnStat]:
    """Extract a :class:`FileColumnStat` for ``column`` from a pyarrow ``FileMetaData``.

    Returns ``None`` when the column is not present in the file. Aggregates across
    all row groups. Never reads a data page (only ``.statistics`` off the footer).
    """
    md = file_metadata
    name_to_idx = {md.schema.column(i).name: i for i in range(md.num_columns)}
    if column not in name_to_idx:
        return None
    ci = name_to_idx[column]
    total_rows = 0
    null_count = 0
    has_min_max = False
    has_stats = False
    gmin: Any = None
    gmax: Any = None
    for rg in range(md.num_row_groups):
        rg_md = md.row_group(rg)
        total_rows += rg_md.num_rows
        st = rg_md.column(ci).statistics
        if st is None:
            continue
        has_stats = True
        null_count += int(st.null_count or 0)
        if st.has_min_max:
            has_min_max = True
            mn = _coerce(st.min)
            mx = _coerce(st.max)
            gmin = mn if gmin is None else min(gmin, mn)
            gmax = mx if gmax is None else max(gmax, mx)
    return FileColumnStat(
        column=column,
        total_rows=total_rows,
        null_count=null_count,
        has_min_max=has_min_max,
        min_value=gmin,
        max_value=gmax,
        has_stats=has_stats,
    )


# ---------------------------------------------------------------------------
# Cross-file column census.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ColumnCensus:
    """The footer-derived census for one column across a sampled set of files."""

    column: str
    total_rows: int
    null_count: int
    nonnull_fraction: float
    all_nan: bool
    all_constant: bool
    constant_value: Any
    sentinel_saturated: bool
    distinct_lower_bound: int          # 0 = unknown, 1 = single-valued, 2 = >= 2 distinct
    min_value: Any
    max_value: Any
    files_sampled: int
    files_with_stats: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "column": self.column,
            "total_rows": self.total_rows,
            "null_count": self.null_count,
            "nonnull_fraction": round(self.nonnull_fraction, 6),
            "all_nan": self.all_nan,
            "all_constant": self.all_constant,
            "constant_value": _jsonable(self.constant_value),
            "sentinel_saturated": self.sentinel_saturated,
            "distinct_lower_bound": self.distinct_lower_bound,
            "min_value": _jsonable(self.min_value),
            "max_value": _jsonable(self.max_value),
            "files_sampled": self.files_sampled,
            "files_with_stats": self.files_with_stats,
        }


def _jsonable(v: Any) -> Any:
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    return str(v)


def census_column(
    file_stats: Sequence[Optional[FileColumnStat]],
    column: str,
    sentinels: Sequence[float] = DEFAULT_SENTINELS,
) -> ColumnCensus:
    """Merge per-file :class:`FileColumnStat` records into one :class:`ColumnCensus`.

    ``file_stats`` entries that are ``None`` (column absent in that file) are ignored.
    """
    present = [s for s in file_stats if s is not None]
    total_rows = sum(s.total_rows for s in present)
    null_count = sum(s.null_count for s in present)
    eff_nonnull = sum(s.effective_nonnull for s in present)
    files_with_stats = sum(1 for s in present if s.has_stats)

    nonnull_fraction = (eff_nonnull / total_rows) if total_rows > 0 else 0.0
    all_nan = total_rows > 0 and eff_nonnull == 0

    # Distinct lower bound + all-constant from the union of per-file min/max.
    mins = [s.min_value for s in present if s.has_min_max]
    maxs = [s.max_value for s in present if s.has_min_max]
    gmin = min(mins) if mins else None
    gmax = max(maxs) if maxs else None
    per_file_constant = all(
        s.min_value == s.max_value for s in present if s.has_min_max
    )
    if not mins:
        distinct_lb = 0                      # no comparable stats -> unknown
    elif gmin == gmax and per_file_constant:
        distinct_lb = 1                      # every present value is the same
    else:
        distinct_lb = 2                      # provably >= 2 distinct

    all_constant = distinct_lb == 1 and not all_nan
    constant_value = gmin if all_constant else None
    sentinel_saturated = bool(
        all_constant
        and isinstance(constant_value, (int, float))
        and any(abs(float(constant_value) - float(s)) < 1e-9 for s in sentinels)
    )

    return ColumnCensus(
        column=column,
        total_rows=total_rows,
        null_count=null_count,
        nonnull_fraction=nonnull_fraction,
        all_nan=all_nan,
        all_constant=all_constant,
        constant_value=constant_value,
        sentinel_saturated=sentinel_saturated,
        distinct_lower_bound=distinct_lb,
        min_value=gmin,
        max_value=gmax,
        files_sampled=len(present),
        files_with_stats=files_with_stats,
    )


# ---------------------------------------------------------------------------
# The gate.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class GateRow:
    """One hard-fail finding. Ordered/serialisable so an R4 exit criterion consumes it."""

    table: str
    column: str
    kind: str
    observed: Any
    threshold: Any
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "table": self.table,
            "column": self.column,
            "kind": self.kind,
            "observed": _jsonable(self.observed),
            "threshold": _jsonable(self.threshold),
            "detail": self.detail,
        }


def evaluate_gate(
    table: str,
    census_by_column: dict[str, ColumnCensus],
    value_columns: Sequence[str],
    min_nonnull_frac: Optional[float],
    *,
    knowledge_date_col: Optional[str] = None,
    knowledge_census: Optional[ColumnCensus] = None,
    floor_overrides: Optional[Mapping[str, float]] = None,
) -> list[GateRow]:
    """Return the ordered list of HARD-FAIL rows for one table (empty == green).

    The hard gate is exactly the plan's step 3: the non-null floor + vintage
    adequacy. A fully sentinel-saturated column is a floor-equivalent (every
    present value is a missing-data code, so it carries zero usable signal) and
    is therefore also hard.

    Value-column HARD checks (each ``value_columns`` entry, floor = ``min_nonnull_frac``):
      * all present values NaN                     -> KIND_ALL_NAN     (the CHIRPS class)
      * non-null fraction < floor                  -> KIND_NONNULL_BELOW_FLOOR
      * saturated at a missing-data sentinel        -> KIND_SENTINEL_SATURATED
      * footer carried no statistics               -> KIND_STATS_UNAVAILABLE
    Vintage-adequacy (only when ``knowledge_date_col`` is declared):
      * distinct(knowledge_date_col) == 1          -> KIND_SINGLE_VINTAGE (the ESR class)

    Plain ``all_constant`` (zero variance at a NON-sentinel value) is a computed
    METRIC, not a hard gate -- see :func:`evaluate_warnings`. It is reported but
    must not false-fail a legitimately-thin partition (the WASDE 1987 scanned
    release, OP-8/AV-11 calibration).

    The vintage check fires whenever a knowledge-date column is declared, regardless
    of ``vintage_retention``: a serving copy that has collapsed to one vintage cannot
    answer a point-in-time question, and that is precisely the ESR-collapse the draft
    left uncaught (latest-only is NOT a licence to ship a single global as_of).
    """
    rows: list[GateRow] = []
    overrides = floor_overrides or {}

    for col in value_columns:
        # OP-8 per-column calibration (min_nonnull_frac_overrides): a user-gated, source-real
        # floor for columns structurally absent at the source over part of the range. The gate
        # stays live -- an all-null regression still hard-fails via KIND_ALL_NAN above the floor.
        floor = overrides.get(col, min_nonnull_frac)
        c = census_by_column.get(col)
        if c is None:
            rows.append(
                GateRow(table, col, KIND_STATS_UNAVAILABLE, None, floor,
                        f"value_column '{col}' not found in any sampled file")
            )
            continue
        if c.total_rows == 0:
            continue  # empty sample -> nothing to assert (an empty table is a different gate)
        if c.files_with_stats == 0:
            rows.append(
                GateRow(table, col, KIND_STATS_UNAVAILABLE, None, floor,
                        f"'{col}' footer carried no row-group statistics")
            )
            continue
        if c.all_nan:
            rows.append(
                GateRow(table, col, KIND_ALL_NAN, 0.0, floor,
                        f"'{col}' is 100% NaN/null across {c.total_rows} sampled rows")
            )
            continue  # all-NaN subsumes the floor breach; one row per column
        if c.sentinel_saturated:
            rows.append(
                GateRow(table, col, KIND_SENTINEL_SATURATED, c.constant_value, floor,
                        f"'{col}' saturated at missing-data sentinel {c.constant_value!r}")
            )
            continue
        if floor is not None and c.nonnull_fraction < floor:
            rows.append(
                GateRow(table, col, KIND_NONNULL_BELOW_FLOOR, c.nonnull_fraction, floor,
                        f"'{col}' non-null fraction {c.nonnull_fraction:.3f} < floor {floor}")
            )

    if knowledge_date_col and knowledge_census is not None:
        kc = knowledge_census
        if kc.total_rows > 0 and kc.distinct_lower_bound == 1:
            rows.append(
                GateRow(table, knowledge_date_col, KIND_SINGLE_VINTAGE, 1, 2,
                        f"knowledge-date '{knowledge_date_col}' has a single vintage "
                        f"({kc.constant_value!r}); PIT-inadequate")
            )
    return rows


def apply_vintage_waiver(
    gate_rows: Sequence[GateRow], waiver: Optional[dict]
) -> tuple[list[GateRow], list[GateRow]]:
    """Split gate rows under a declared, user-gated ``vintage_waiver`` (BF-W2 rider 6).

    Returns ``(kept_hard, waived_warn)``: with a waiver present, KIND_SINGLE_VINTAGE rows are
    DEMOTED to warn rows whose detail names the approval -- reported, never silently green. Every
    other kind stays hard, and without a waiver nothing changes. ``evaluate_gate`` itself remains
    strict by design (the waiver is a REGISTRY declaration consumed at the census runner, so the
    gate function cannot be quietly disarmed by a caller omitting an argument)."""
    if not waiver:
        return list(gate_rows), []
    kept: list[GateRow] = []
    waived: list[GateRow] = []
    for r in gate_rows:
        if r.kind == KIND_SINGLE_VINTAGE:
            waived.append(GateRow(r.table, r.column, r.kind, r.observed, r.threshold,
                                  f"WAIVED ({waiver.get('approved', '?')}): {r.detail}"))
        else:
            kept.append(r)
    return kept, waived


def evaluate_warnings(
    table: str,
    census_by_column: dict[str, ColumnCensus],
    value_columns: Sequence[str],
) -> list[GateRow]:
    """Return the ordered list of soft WARNING rows (reported, never fail the gate).

    Currently: a value column with zero variance table-wide at a non-sentinel value
    (``KIND_ALL_CONSTANT``). This surfaces a suspicious column (e.g. ESR
    ``changes_1000mt`` constant 0, or a thin scanned WASDE partition) without
    false-failing a legitimately-sparse source.
    """
    rows: list[GateRow] = []
    for col in value_columns:
        c = census_by_column.get(col)
        if c is None or c.total_rows == 0 or c.all_nan or c.sentinel_saturated:
            continue
        if c.all_constant:
            rows.append(
                GateRow(table, col, KIND_ALL_CONSTANT, c.constant_value, None,
                        f"'{col}' has zero variance table-wide (constant {c.constant_value!r})")
            )
    return rows


# ---------------------------------------------------------------------------
# Table-level result container (the shape written to value_census.json).
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class TableCensusResult:
    table: str
    partition_mode: str
    value_columns: tuple[str, ...]
    min_nonnull_frac: Optional[float]
    knowledge_date_col: Optional[str]
    vintage_retention: Optional[str]
    columns: dict[str, ColumnCensus]
    gate_rows: tuple[GateRow, ...]
    warn_rows: tuple[GateRow, ...]
    files_sampled: int
    sample_strategy: str
    baseline_id: str = ""
    generated_at: str = ""
    mechanism: str = "parquet_footer_statistics"
    athena_queries_issued: int = 0     # ALWAYS 0 (INV-3 tripwire; see runner)
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def passed(self) -> bool:
        return len(self.gate_rows) == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "table": self.table,
            "package": "SILVER-V001",
            "mechanism": self.mechanism,
            "athena_queries_issued": self.athena_queries_issued,
            "baseline_id": self.baseline_id,
            "generated_at": self.generated_at,
            "partition_mode": self.partition_mode,
            "sample_strategy": self.sample_strategy,
            "files_sampled": self.files_sampled,
            "value_columns": list(self.value_columns),
            "min_nonnull_frac": self.min_nonnull_frac,
            "knowledge_date_col": self.knowledge_date_col,
            "vintage_retention": self.vintage_retention,
            "passed": self.passed,
            "gate_rows": [g.to_dict() for g in self.gate_rows],
            "warn_rows": [g.to_dict() for g in self.warn_rows],
            "columns": {name: c.to_dict() for name, c in self.columns.items()},
            "notes": list(self.notes),
        }


def build_table_result(
    table: str,
    *,
    partition_mode: str,
    value_columns: Sequence[str],
    min_nonnull_frac: Optional[float],
    knowledge_date_col: Optional[str],
    vintage_retention: Optional[str],
    census_by_column: dict[str, ColumnCensus],
    files_sampled: int,
    sample_strategy: str,
    baseline_id: str = "",
    generated_at: str = "",
    notes: Iterable[str] = (),
) -> TableCensusResult:
    """Assemble a :class:`TableCensusResult`, running the gate over the census."""
    knowledge_census = census_by_column.get(knowledge_date_col) if knowledge_date_col else None
    gate_rows = evaluate_gate(
        table,
        census_by_column,
        value_columns,
        min_nonnull_frac,
        knowledge_date_col=knowledge_date_col,
        knowledge_census=knowledge_census,
    )
    warn_rows = evaluate_warnings(table, census_by_column, value_columns)
    return TableCensusResult(
        table=table,
        partition_mode=partition_mode,
        value_columns=tuple(value_columns),
        min_nonnull_frac=min_nonnull_frac,
        knowledge_date_col=knowledge_date_col,
        vintage_retention=vintage_retention,
        columns=census_by_column,
        gate_rows=tuple(gate_rows),
        warn_rows=tuple(warn_rows),
        files_sampled=files_sampled,
        sample_strategy=sample_strategy,
        baseline_id=baseline_id,
        generated_at=generated_at,
        notes=tuple(notes),
    )
