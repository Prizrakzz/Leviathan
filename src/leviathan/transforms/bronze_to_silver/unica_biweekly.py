"""Silver transforms for UNICA Center-South biweekly (quinzenal) bulletin data.

Converts the five bronze Parquet tables produced by the biweekly PDF extract
into four clean silver tables.  Each function is a pure data transformation —
no S3 or AWS dependencies.

Output tables
-------------
season_history     : One row per (harvest_year, fortnight_seq, region).
                     Deduplicated — each slot keeps the reading from ONE
                     bulletin (see "Slot-atomic dedup" below).

release_series     : One row per (harvest_year, position_date, region).
                     The accumulated-total vintage series as published on each
                     bulletin release date; used for revision-surprise features.

corn_ethanol       : One row per (harvest_year, fortnight_seq).
                     Corn-derived ethanol production by fortnight; deduplicated.

monthly_ethanol_sales : One row per (harvest_year, month_num).
                     Prefers a reading that carries figures over an unreported
                     month's empty skeleton, then final (non-partial) totals,
                     then the latest bulletin.

Fortnight calendar
------------------
UNICA's crushing season runs April–March and is divided into 24 fortnight
positions.  The (seq -> DD/MM) mapping is a fixed bijection, verified over
every bronze bulletin::

    seq  1 = 16/04   seq  7 = 16/07   seq 13 = 16/10   seq 19 = 16/01
    seq  2 = 01/05   seq  8 = 01/08   seq 14 = 01/11   seq 20 = 01/02
    ...                                                seq 24 = 01/04

April therefore appears TWICE: ``16/04`` opens the season (start year) and
``01/04`` closes it (end year).  See :func:`_resolve_fortnight_date`.

Bronze integrity repairs
------------------------
The bronze PDF extractor binds table variables by PAGE/ROW POSITION rather
than by the page's own caption, so bulletins whose PDF carries an extra
leading page (history tables) or an extra header row (Tabela 1) come out with
every metric bound to the NEXT variable name, and pt-BR number parsing is
applied to English-language bulletins whose separators are reversed.  Both
classes are detected here STRUCTURALLY — from the parsed content, never from a
date stamp — and either repaired or refused:

* ``_repair_separator_scale``  : a value carrying a fractional part is a
  comma-thousands string mis-read as a decimal; restore it by x1000.
* ``_detect_history_shift``    : a contiguous leading run of under-covered
  variables means the history page window started early by that many pages;
  relabel and derive what the shift truncated.
* ``_unshift_snapshot``        : Tabela 1 rows whose ethanol identity fails
  while ``cane_crushed`` is empty are relabeled by one row.

Every repair is validated against UNICA's own invariants
(``ethanol_total == anhydrous + hydrous``; ``total == external + internal``;
``centro_sul == sao_paulo + demais_estados``; non-negative production) and
anything that fails validation is REFUSED rather than published.

A second, subtler class is a reading that PARSED but is EMPTY: every bulletin
lists all twelve months of the season, so a month UNICA has not reported yet
still produces a labelled row with no figures on it.  Ranking on recency alone
lets those skeletons win the dedup and blank out whole seasons, so a reading
that carries figures always outranks one that does not.

Slot-atomic dedup
-----------------
``season_history`` deduplicates whole slots, not individual variables.  A
silver row's five metrics all come from ONE bulletin, so the row is internally
coherent and ``source_idm`` / ``source_position_date`` describe every value on
it.  Bulletins are ranked per slot by (number of MEASURED metrics desc,
position date desc): the most complete reading wins, and among equally
complete readings the latest vintage wins.
"""
from __future__ import annotations

import datetime
import math
from typing import Optional

import pandas as pd

from leviathan.common.logging import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

# Doc types whose cover date is printed US-style (MM/DD/YYYY).
_MDY_DOC_TYPES = frozenset({"biweekly_new_en"})

# Relative tolerance for UNICA's published-rounding identities.
_IDENTITY_RTOL = 1e-9


def _parse_flexible_date(
    s: Optional[str],
    doc_type: Optional[str] = None,
) -> Optional[datetime.date]:
    """Parse a bulletin position-date string in either DD/MM/YYYY or MM/DD/YYYY.

    UNICA's cover line is free text: Portuguese bulletins print ``posição até
    16/10/2025`` (DD/MM/YYYY) while English ones print ``Position until
    10/16/2025`` (MM/DD/YYYY).  The bronze extractor passes whichever it found
    through unchanged, so the same column holds both conventions.

    Resolution order (structural first, never keyed on the stamp itself):

    1. If exactly one of the two leading components exceeds 12, only one
       reading is a real date — take it.
    2. Otherwise fall back to *doc_type*: English bulletins are MM/DD/YYYY,
       everything else is DD/MM/YYYY.

    Args:
        s:        Raw date string, e.g. ``"16/10/2025"`` or ``"10/16/2025"``.
        doc_type: Bronze ``doc_type`` for the emitting bulletin, used only to
                  break a genuine ambiguity.

    Returns:
        Resolved :class:`datetime.date`, or ``None`` when *s* is missing or
        cannot be read as a date under either convention.
    """
    if not s or not isinstance(s, str):
        return None
    txt = s.strip()
    if not txt:
        return None

    # Already ISO (idempotent re-parse of an output of this function).
    try:
        return datetime.datetime.strptime(txt[:10], "%Y-%m-%d").date()
    except ValueError:
        pass

    parts = txt.split("/")
    if len(parts) != 3:
        return None
    try:
        a, b, year = int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError:
        return None

    dmy_ok = 1 <= b <= 12
    mdy_ok = 1 <= a <= 12
    if dmy_ok and not mdy_ok:
        day, month = a, b
    elif mdy_ok and not dmy_ok:
        day, month = b, a
    elif dmy_ok and mdy_ok:
        # Genuinely ambiguous -- the document's own language decides.
        if doc_type in _MDY_DOC_TYPES:
            day, month = b, a
        else:
            day, month = a, b
    else:
        return None

    try:
        return datetime.date(year, month, day)
    except ValueError:
        return None


def _resolve_position_date(
    s: Optional[str],
    doc_type: Optional[str] = None,
) -> Optional[datetime.date]:
    """Parse a bulletin position-date string to a :class:`datetime.date`.

    Thin alias over :func:`_parse_flexible_date`; retained as the transform's
    named seam for position-date resolution.
    """
    return _parse_flexible_date(s, doc_type)


def _iso_or_none(d: Optional[datetime.date]) -> Optional[str]:
    """Render a date as ``YYYY-MM-DD``; ``None`` passes through."""
    return d.isoformat() if d is not None else None


# The UNICA season is 24 fortnight positions: 16/04 (start year) through
# 01/04 (end year).  Built once and shared.
def _build_fortnight_calendar() -> list[tuple[int, int, bool]]:
    """Return ``[(day, month, is_end_year)]`` for fortnight seq 1..24."""
    slots: list[tuple[int, int, bool]] = []
    # April opens on the 16th; May..December then January..March/April follow.
    slots.append((16, 4, False))
    for month in range(5, 13):
        slots.append((1, month, False))
        slots.append((16, month, False))
    for month in range(1, 4):
        slots.append((1, month, True))
        slots.append((16, month, True))
    slots.append((1, 4, True))
    return slots


_FORTNIGHT_CALENDAR: list[tuple[int, int, bool]] = _build_fortnight_calendar()

# (day, month) -> is_end_year.  April is the only month present twice, and the
# two entries disagree -- which is exactly the ambiguity this table resolves.
_FORTNIGHT_YEAR_SIDE: dict[tuple[int, int], bool] = {
    (d, m): end for d, m, end in _FORTNIGHT_CALENDAR
}


def _split_harvest_year(harvest_year: str) -> Optional[tuple[int, int]]:
    """Split ``"YYYY_YYYY"`` into ``(start_year, end_year)``; ``None`` if unparseable."""
    if not isinstance(harvest_year, str):
        return None
    parts = harvest_year.replace("/", "_").split("_")
    if len(parts) != 2:
        return None
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None


def _resolve_fortnight_date(
    label: Optional[str],
    harvest_year: str,
    fortnight_seq: Optional[int] = None,
) -> Optional[datetime.date]:
    """Resolve a ``DD/MM`` fortnight label to a full calendar date.

    The season runs 16/04 of the start year through 01/04 of the end year, so
    the month alone does NOT determine the year: April is the season's first
    position (``16/04``, start year) AND its last (``01/04``, end year).
    Resolving by month alone stamps ``01/04`` a full year early, placing the
    season's final position before its first.

    The year side is therefore taken from the season calendar
    (:data:`_FORTNIGHT_YEAR_SIDE`), which distinguishes the two Aprils by day.
    When *fortnight_seq* is supplied it is used as the primary key and the
    label only has to agree; a label that contradicts its sequence is refused.

    Args:
        label:         ``"DD/MM"`` string, e.g. ``"15/04"``.
        harvest_year:  ``"YYYY_YYYY"`` string, e.g. ``"2023_2024"``.
        fortnight_seq: 1-based position within the season, when known.

    Returns:
        Resolved :class:`datetime.date`, or ``None`` if the inputs are
        unparseable or mutually inconsistent.
    """
    years = _split_harvest_year(harvest_year)
    if years is None:
        return None
    year_start, year_end = years

    day = month = None
    if isinstance(label, str) and label.strip():
        bits = label.strip().split("/")
        if len(bits) == 2:
            try:
                day, month = int(bits[0]), int(bits[1])
            except ValueError:
                day = month = None

    seq_slot = None
    if fortnight_seq is not None and not pd.isna(fortnight_seq):
        try:
            idx = int(fortnight_seq)
        except (TypeError, ValueError):
            idx = 0
        if 1 <= idx <= len(_FORTNIGHT_CALENDAR):
            seq_slot = _FORTNIGHT_CALENDAR[idx - 1]

    if seq_slot is not None:
        s_day, s_month, s_end = seq_slot
        # A label that disagrees with its sequence means the two disagree about
        # which position this is -- refuse rather than guess.
        if day is not None and (day, month) != (s_day, s_month):
            logger.warning(
                "fortnight_date: label %s contradicts seq %s (%02d/%02d) for %s",
                label, fortnight_seq, s_day, s_month, harvest_year,
            )
            return None
        day, month, is_end = s_day, s_month, s_end
    else:
        if day is None or month is None:
            return None
        side = _FORTNIGHT_YEAR_SIDE.get((day, month))
        if side is None:
            # Off-calendar label (e.g. a month-end stamp): months 1-3 belong to
            # the end year, 4-12 to the start year, and a low-day April closes.
            if month in (1, 2, 3):
                is_end = True
            elif month == 4:
                is_end = day < 16
            else:
                is_end = False
        else:
            is_end = side

    try:
        return datetime.date(year_end if is_end else year_start, month, day)
    except (ValueError, TypeError):
        return None


def _resolve_ingest_date(s: Optional[str]) -> Optional[datetime.date]:
    """Parse an ``YYYY-MM-DD`` ingest-date string to a :class:`datetime.date`.

    Returns ``None`` on failure.
    """
    if not s or not isinstance(s, str):
        return None
    try:
        return datetime.datetime.strptime(s.strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _repair_separator_scale(value):
    """Undo a comma-thousands separator that was read as a decimal point.

    The bronze number parser applies pt-BR conventions (``.`` thousands, ``,``
    decimal) to EVERY bulletin, including the English-language ones which print
    ``12,151``.  Under pt-BR rules that string becomes ``12.151`` — exactly one
    thousandth of the true value.

    UNICA publishes these tables in whole tonnes / cubic metres / kilolitres,
    so a fractional part is itself the tell: it can only be a mis-read group
    separator.  Values with up to three decimal places are restored by x1000;
    anything else is left alone (a multi-group English number fails the bronze
    parse outright and arrives as null, so it never reaches here).

    Args:
        value: Parsed bronze value, possibly ``None``/``NaN``.

    Returns:
        The value at its true scale.
    """
    if value is None:
        return value
    try:
        v = float(value)
    except (TypeError, ValueError):
        return value
    if math.isnan(v) or v == int(v):
        return v
    scaled = v * 1000.0
    if abs(scaled - round(scaled)) > 1e-6:
        # More than three decimals -- not a single mis-read group separator.
        return v
    return float(round(scaled))


def _scale_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Apply :func:`_repair_separator_scale` across *columns* in place."""
    for col in columns:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").map(_repair_separator_scale)
    return df


def _close_enough(left, right) -> bool:
    """Exact-within-float-noise comparison used by the invariant checks."""
    if left is None or right is None:
        return False
    if pd.isna(left) or pd.isna(right):
        return False
    scale = max(abs(float(left)), abs(float(right)), 1.0)
    return abs(float(left) - float(right)) <= _IDENTITY_RTOL * scale


# ---------------------------------------------------------------------------
# Table 1: season_history
# ---------------------------------------------------------------------------

# Ordered exactly as the bronze extractor consumes the Tabela 3-7 page window.
# A page-window shift relabels each metric with the NEXT name in this list.
_HISTORY_VAR_ORDER: list[str] = [
    "cane_crushed",
    "sugar_produced",
    "ethanol_total",
    "ethanol_anhydrous",
    "ethanol_hydrous",
]

_SEASON_HISTORY_VAR_MAP: dict[str, str] = {
    "cane_crushed":       "cane_crushed_t",
    "sugar_produced":     "sugar_produced_t",
    "ethanol_total":      "ethanol_total_m3",
    "ethanol_anhydrous":  "ethanol_anhydrous_m3",
    "ethanol_hydrous":    "ethanol_hydrous_m3",
}

SEASON_HISTORY_COLUMNS: list[str] = [
    "harvest_year",
    "fortnight_seq",
    "fortnight_label",
    "fortnight_date",
    "region",
    "cane_crushed_t",
    "sugar_produced_t",
    "ethanol_total_m3",
    "ethanol_anhydrous_m3",
    "ethanol_hydrous_m3",
    "source_idm",
    "source_position_date",
]

_SEASON_HISTORY_METRICS: list[str] = [
    "cane_crushed_t",
    "sugar_produced_t",
    "ethanol_total_m3",
    "ethanol_anhydrous_m3",
    "ethanol_hydrous_m3",
]

_ETHANOL_TRIPLE: list[str] = [
    "ethanol_total_m3",
    "ethanol_anhydrous_m3",
    "ethanol_hydrous_m3",
]

# The anhydrous/hydrous SPLIT is all-or-nothing -- one leg alone says nothing
# and silently breaks the identity.  ``ethanol_total`` may stand on its own:
# it is a published aggregate in its own right, and a two-page shift truncates
# the split while leaving the total intact.
_ETHANOL_SPLIT: list[str] = [
    "ethanol_anhydrous_m3",
    "ethanol_hydrous_m3",
]

# A variable covering less than this fraction of the best-covered variable in
# the same bulletin did not get its own page -- it is a shift artefact.
_COVERAGE_DEFICIT_FRAC = 0.5

# A shift hypothesis must reproduce UNICA's invariants on at least this share
# of the slots it touches, or the bulletin is refused outright.
_SHIFT_VALIDATION_FRAC = 0.9


def _detect_history_shift(counts: dict[str, int]) -> int:
    """Infer how many pages the bronze history window started early.

    The bronze extractor walks a fixed five-page tail window and binds page *i*
    to ``_HISTORY_VAR_ORDER[i]``.  When the real Tabela 3-7 block sits *k*
    pages later than the window assumes, the first *k* names collect whatever
    non-table pages preceded the block (nothing, or a stray fragment) and every
    real page lands under the name *k* positions further along; the last *k*
    real pages fall outside the window entirely and are lost.

    The signature is therefore a CONTIGUOUS LEADING RUN of under-covered
    variables, which is what this reads off the per-variable value counts.

    Args:
        counts: ``{bronze variable name: non-null value count}`` for one
                bulletin.

    Returns:
        The inferred shift *k* (0 when the bulletin is well-formed).
    """
    best = max(counts.values(), default=0)
    if best <= 0:
        return 0
    floor = best * _COVERAGE_DEFICIT_FRAC
    shift = 0
    for var in _HISTORY_VAR_ORDER:
        if counts.get(var, 0) < floor:
            shift += 1
        else:
            break
    return min(shift, len(_HISTORY_VAR_ORDER))


def _apply_history_shift(df: pd.DataFrame, shift: int) -> pd.DataFrame:
    """Relabel one bulletin's history rows by *shift* positions.

    Each metric is moved back to the variable it actually measures; the names
    that collected nothing (the leading *shift* entries) are dropped along with
    their stray values.
    """
    if shift <= 0:
        return df
    remap = {
        _HISTORY_VAR_ORDER[i]: _HISTORY_VAR_ORDER[i - shift]
        for i in range(shift, len(_HISTORY_VAR_ORDER))
    }
    out = df[df["variable"].isin(remap)].copy()
    out["variable"] = out["variable"].map(remap)
    return out


def _validate_history_block(wide: pd.DataFrame) -> tuple[bool, str]:
    """Check one bulletin's relabelled slots against UNICA's own invariants.

    Verifies, over the slots the bulletin covers:

    * uniform coverage — every recovered metric is present on every slot;
    * region additivity — ``centro_sul == sao_paulo + demais_estados``;
    * the ethanol identity — ``total == anhydrous + hydrous`` wherever the
      whole triple survived the shift;
    * ordering — ``cane >= sugar``, ``cane >= ethanol_total``.

    Returns:
        ``(ok, reason)``.  ``reason`` is empty when the block validates.
    """
    if wide.empty:
        return False, "no rows"

    present = [c for c in _SEASON_HISTORY_METRICS if wide[c].notna().any()]
    if not present:
        return False, "no metrics survived"

    # Uniform coverage: a genuine page yields every slot it covers.
    nonnull = {c: int(wide[c].notna().sum()) for c in present}
    if min(nonnull.values()) < _SHIFT_VALIDATION_FRAC * max(nonnull.values()):
        return False, f"ragged coverage {nonnull}"

    checks = 0
    fails = 0

    # Region additivity per (harvest_year, fortnight_seq).
    piv = wide.pivot_table(
        index=["harvest_year", "fortnight_seq"], columns="region",
        values=present, aggfunc="first",
    )
    for metric in present:
        for reg in ("centro_sul", "sao_paulo", "demais_estados"):
            if (metric, reg) not in piv.columns:
                break
        else:
            cs, sp, de = (piv[(metric, r)] for r in
                          ("centro_sul", "sao_paulo", "demais_estados"))
            mask = cs.notna() & sp.notna() & de.notna()
            checks += int(mask.sum())
            fails += int((~((cs - sp - de).abs() <= _IDENTITY_RTOL * cs.abs().clip(lower=1.0)))[mask].sum())

    tot, anh, hyd = (wide[c] for c in _ETHANOL_TRIPLE)
    triple = tot.notna() & anh.notna() & hyd.notna()
    if triple.any():
        checks += int(triple.sum())
        fails += int((~((anh + hyd - tot).abs() <= _IDENTITY_RTOL * tot.abs().clip(lower=1.0)))[triple].sum())

    cane, sugar = wide["cane_crushed_t"], wide["sugar_produced_t"]
    order = cane.notna() & sugar.notna()
    if order.any():
        checks += int(order.sum())
        fails += int((cane < sugar)[order].sum())

    if not checks:
        # Nothing here can be cross-checked -- a lone metric on a lone region
        # carries no way to tell a measurement from a mis-read fragment.
        return False, "no invariant applicable"
    if fails > (1.0 - _SHIFT_VALIDATION_FRAC) * checks:
        return False, f"invariants failed {fails}/{checks}"
    return True, ""


def _prepare_history_bulletin(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    """Turn one bulletin's long history rows into validated wide slots.

    Applies the shift repair, derives what the shift truncated, quarantines
    impossible readings, and refuses the bulletin when the result cannot be
    reconciled with UNICA's invariants.

    Returns:
        Wide frame keyed on ``(harvest_year, fortnight_seq, region)``, or
        ``None`` when the bulletin is refused.
    """
    counts = df.groupby("variable")["value"].count().to_dict()
    shift = _detect_history_shift(counts)
    idm = df["idm"].iloc[0]

    shifted = _apply_history_shift(df, shift)
    if shifted.empty:
        logger.warning("season_history: idm=%s refused (shift=%d left no rows)", idm, shift)
        return None

    shifted = shifted.copy()
    shifted["variable"] = shifted["variable"].map(_SEASON_HISTORY_VAR_MAP)

    wide = shifted.pivot_table(
        index=["harvest_year", "fortnight_seq", "region"],
        columns="variable", values="value", aggfunc="first",
    ).reset_index()
    wide.columns.name = None
    for col in _SEASON_HISTORY_METRICS:
        if col not in wide.columns:
            wide[col] = float("nan")

    # Remember which cells the bulletin actually PUBLISHED, before anything is
    # derived or quarantined.  The dedup rank is scored against this mask so a
    # reconstructed leg can never outrank a published one, and a value that the
    # repairs later void stops counting toward the bulletin's completeness.
    published = wide[_SEASON_HISTORY_METRICS].notna()

    # A one-page shift truncates ethanol_hydrous but leaves total and anhydrous
    # intact, and UNICA defines total = anhydrous + hydrous exactly -- so the
    # missing leg is recoverable by arithmetic, not by guesswork.
    if shift == 1:
        need = (
            wide["ethanol_hydrous_m3"].isna()
            & wide["ethanol_total_m3"].notna()
            & wide["ethanol_anhydrous_m3"].notna()
        )
        wide.loc[need, "ethanol_hydrous_m3"] = (
            wide.loc[need, "ethanol_total_m3"] - wide.loc[need, "ethanol_anhydrous_m3"]
        )

    ok, reason = _validate_history_block(wide)
    if not ok:
        logger.warning(
            "season_history: idm=%s REFUSED after shift=%d -- %s", idm, shift, reason
        )
        return None

    # Accumulated production cannot run negative: where it does, the underlying
    # cell was mis-read.  Drop the whole ethanol triple for that (season,
    # position) across every region -- additivity ties the three together, so a
    # single impossible leg condemns the group, not just its own cell.
    neg = wide[_SEASON_HISTORY_METRICS].lt(0).any(axis=1)
    if neg.any():
        bad_slots = set(map(tuple, wide.loc[neg, ["harvest_year", "fortnight_seq"]].values))
        mask = wide.set_index(["harvest_year", "fortnight_seq"]).index.isin(bad_slots)
        wide.loc[mask, _ETHANOL_TRIPLE] = float("nan")
        logger.warning(
            "season_history: idm=%s nulled ethanol triple on %d slot(s) with negative values",
            idm, len(bad_slots),
        )
        still_neg = wide[_SEASON_HISTORY_METRICS].lt(0).any(axis=1)
        if still_neg.any():
            wide = wide[~still_neg].copy()

    # The split is all-or-nothing: a lone leg cannot be reconciled with any
    # total, so it is dropped rather than left to break the identity.
    half = wide[_ETHANOL_SPLIT].notna().any(axis=1) & wide[_ETHANOL_SPLIT].isna().any(axis=1)
    if half.any():
        wide.loc[half, _ETHANOL_SPLIT] = float("nan")

    # A published split with no total implies the total exactly.
    need_total = (
        wide["ethanol_total_m3"].isna()
        & wide["ethanol_anhydrous_m3"].notna()
        & wide["ethanol_hydrous_m3"].notna()
    )
    wide.loc[need_total, "ethanol_total_m3"] = (
        wide.loc[need_total, "ethanol_anhydrous_m3"] + wide.loc[need_total, "ethanol_hydrous_m3"]
    )

    wide["_measured"] = (wide[_SEASON_HISTORY_METRICS].notna() & published).sum(axis=1)

    if shift:
        logger.info("season_history: idm=%s repaired (page shift=%d)", idm, shift)
    return wide


def transform_season_history(df_bronze: pd.DataFrame) -> pd.DataFrame:
    """Transform ``fortnight_production`` bronze rows to the season history silver.

    Each bulletin is repaired and validated in isolation (see
    :func:`_prepare_history_bulletin`), then slots are deduplicated ATOMICALLY:
    the winning bulletin supplies all five metrics for that slot, so the row is
    internally coherent and its ``source_idm`` describes every value on it.
    Bulletins are ranked by (measured metrics desc, position date desc).

    Args:
        df_bronze: Concatenation of all ``fortnight_production`` bronze Parquets.
            Required columns: ``harvest_year``, ``idm``, ``fortnight_seq``,
            ``fortnight_label``, ``region``, ``variable``, ``period``,
            ``value``, ``unit``, ``position_date``, ``ingest_date``.

    Returns:
        Wide DataFrame keyed on ``(harvest_year, fortnight_seq, region)``,
        one row per slot.  See ``SEASON_HISTORY_COLUMNS`` for the full schema.

    Raises:
        ValueError: If required columns are missing.
    """
    required = {
        "harvest_year", "idm", "fortnight_seq", "fortnight_label",
        "region", "variable", "period", "value", "position_date", "ingest_date",
    }
    missing = required - set(df_bronze.columns)
    if missing:
        raise ValueError(f"season_history bronze missing columns: {sorted(missing)}")

    df = df_bronze.copy()
    if "doc_type" not in df.columns:
        df["doc_type"] = None

    # Keep only current-year readings (not the prior-year comparison values).
    df = df[df["period"] == "current"].copy()
    if df.empty:
        logger.warning("season_history: no 'current' period rows in bronze input")
        return pd.DataFrame(columns=SEASON_HISTORY_COLUMNS)

    df = df[df["variable"].isin(_SEASON_HISTORY_VAR_MAP)].copy()
    if df.empty:
        logger.warning("season_history: no recognised variables in bronze input")
        return pd.DataFrame(columns=SEASON_HISTORY_COLUMNS)

    df["value"] = pd.to_numeric(df["value"], errors="coerce").map(_repair_separator_scale)

    df["_pos_date"] = [
        _resolve_position_date(p, d) for p, d in zip(df["position_date"], df["doc_type"])
    ]
    df["_ing_date"] = df["ingest_date"].map(_resolve_ingest_date)
    df["_sort_date"] = df["_pos_date"].where(df["_pos_date"].notna(), df["_ing_date"])

    blocks: list[pd.DataFrame] = []
    for (idm, _hy), grp in df.groupby(["idm", "harvest_year"], sort=False):
        wide = _prepare_history_bulletin(grp)
        if wide is None:
            continue
        meta = grp.iloc[0]
        wide["source_idm"] = idm
        wide["source_position_date"] = _iso_or_none(meta["_pos_date"])
        wide["_sort_date"] = meta["_sort_date"]
        blocks.append(wide)

    if not blocks:
        logger.warning("season_history: every bulletin was refused")
        return pd.DataFrame(columns=SEASON_HISTORY_COLUMNS)

    allrows = pd.concat(blocks, ignore_index=True)

    # Slot-atomic dedup: most complete reading first, then latest vintage.
    allrows = allrows.sort_values(
        ["_measured", "_sort_date"], ascending=[False, False], na_position="last"
    ).drop_duplicates(
        subset=["harvest_year", "fortnight_seq", "region"], keep="first"
    )

    allrows["fortnight_date"] = [
        _resolve_fortnight_date(None, hy, seq)
        for hy, seq in zip(allrows["harvest_year"], allrows["fortnight_seq"])
    ]
    allrows["fortnight_label"] = [
        f"{_FORTNIGHT_CALENDAR[int(s) - 1][0]:02d}/{_FORTNIGHT_CALENDAR[int(s) - 1][1]:02d}"
        if 1 <= int(s) <= len(_FORTNIGHT_CALENDAR) else None
        for s in allrows["fortnight_seq"]
    ]

    wide = allrows.sort_values(
        ["harvest_year", "region", "fortnight_seq"]
    ).reset_index(drop=True)

    for col in SEASON_HISTORY_COLUMNS:
        if col not in wide.columns:
            wide[col] = None

    logger.info(
        "season_history: %d rows (%d seasons, %d regions, %d bulletins)",
        len(wide), wide["harvest_year"].nunique(),
        wide["region"].nunique(), wide["source_idm"].nunique(),
    )
    return wide[SEASON_HISTORY_COLUMNS].reset_index(drop=True)


# ---------------------------------------------------------------------------
# Table 2: release_series
# ---------------------------------------------------------------------------

_RELEASE_SERIES_VARS: set[str] = {
    "cane_crushed",
    "sugar_produced",
    "ethanol_total",
    "ethanol_anhydrous",
    "ethanol_hydrous",
}

# Row order of UNICA's Tabela 1, which the bronze extractor binds by index.
_SNAPSHOT_VAR_ORDER: list[str] = [
    "cane_crushed",
    "sugar_produced",
    "ethanol_anhydrous",
    "ethanol_hydrous",
    "ethanol_total",
]

RELEASE_SERIES_COLUMNS: list[str] = [
    "harvest_year",
    "position_date",
    "region",
    "cane_crushed_current_t",
    "cane_crushed_prior_t",
    "sugar_produced_current_t",
    "sugar_produced_prior_t",
    "ethanol_total_current_m3",
    "ethanol_total_prior_m3",
    "ethanol_anhydrous_current_m3",
    "ethanol_anhydrous_prior_m3",
    "ethanol_hydrous_current_m3",
    "ethanol_hydrous_prior_m3",
]

# Maps (variable, unit) → prefix used in column construction.
_RELEASE_VAR_UNIT: dict[str, str] = {
    "cane_crushed":      "t",
    "sugar_produced":    "t",
    "ethanol_total":     "m3",
    "ethanol_anhydrous": "m3",
    "ethanol_hydrous":   "m3",
}

# Tabela 1 is published in THOUSANDS of tonnes / cubic metres, while these
# columns are named for whole tonnes and cubic metres.
_SNAPSHOT_UNIT_SCALE = 1000.0

_RELEASE_METRICS: list[str] = [c for c in RELEASE_SERIES_COLUMNS
                               if c.endswith(("_t", "_m3"))]

# Tabela 1 rounds every figure to the nearest thousand, so a regional split can
# miss its own total by a rounding unit per region even when it is correct.
_SNAPSHOT_REGION_RTOL = 2e-3
_SNAPSHOT_REGION_ATOL = 3.0 * _SNAPSHOT_UNIT_SCALE


def _unshift_snapshot(vals: dict[str, Optional[float]]) -> Optional[dict[str, Optional[float]]]:
    """Repair one Tabela 1 reading whose rows were bound one position early.

    The bronze extractor binds Tabela 1 by absolute row index.  Bulletins whose
    table carries an extra header row therefore hand every figure to the NEXT
    variable in :data:`_SNAPSHOT_VAR_ORDER`: ``sugar_produced`` receives cane,
    ``ethanol_anhydrous`` receives sugar, and so on, while ``cane_crushed``
    receives nothing and ``ethanol_total`` is pushed off the end.

    Detection is structural: a well-formed reading has ``cane_crushed``
    populated and satisfies ``total == anhydrous + hydrous``; a shifted one has
    neither.  The truncated total is recovered from the identity.

    Args:
        vals: ``{bronze variable: value}`` for one (bulletin, region, vintage).

    Returns:
        The corrected mapping, or ``None`` when the reading is neither
        well-formed nor a recognisable one-row shift.
    """
    cane = vals.get("cane_crushed")
    tot, anh, hyd = (vals.get(k) for k in
                     ("ethanol_total", "ethanol_anhydrous", "ethanol_hydrous"))

    has_cane = cane is not None and not pd.isna(cane)
    identity_ok = (
        anh is not None and hyd is not None and tot is not None
        and not pd.isna(anh) and not pd.isna(hyd) and not pd.isna(tot)
        and _close_enough(anh + hyd, tot)
    )
    if has_cane and identity_ok:
        return dict(vals)
    if has_cane or identity_ok:
        # Half-consistent: neither hypothesis explains it.
        return dict(vals) if identity_ok else None

    shifted = {
        _SNAPSHOT_VAR_ORDER[i - 1]: vals.get(_SNAPSHOT_VAR_ORDER[i])
        for i in range(1, len(_SNAPSHOT_VAR_ORDER))
    }
    shifted["ethanol_total"] = None
    a, h = shifted.get("ethanol_anhydrous"), shifted.get("ethanol_hydrous")
    if a is not None and h is not None and not pd.isna(a) and not pd.isna(h):
        shifted["ethanol_total"] = a + h
    new_cane = shifted.get("cane_crushed")
    if new_cane is None or pd.isna(new_cane):
        return None
    return shifted


def _validate_snapshot_reading(vals: dict[str, Optional[float]]) -> bool:
    """Check one repaired Tabela 1 reading against UNICA's own invariants.

    A reading is published only when it is complete and self-consistent: all
    five figures present and non-negative, cane above both sugar and ethanol,
    and ``total == anhydrous + hydrous``.  Anything else means the row binding
    was not what either hypothesis assumed, so it is refused rather than
    guessed at.
    """
    got = {}
    for var in _SNAPSHOT_VAR_ORDER:
        v = vals.get(var)
        if v is None or pd.isna(v) or float(v) < 0:
            return False
        got[var] = float(v)
    if got["cane_crushed"] < got["sugar_produced"]:
        return False
    if got["cane_crushed"] < got["ethanol_total"]:
        return False
    return _close_enough(got["ethanol_anhydrous"] + got["ethanol_hydrous"],
                         got["ethanol_total"])


def _reconcile_release_regions(wide: pd.DataFrame) -> pd.DataFrame:
    """Drop regional splits that do not reconcile with their Center-South total.

    ``sao_paulo`` and ``demais_estados`` are read from hard-coded Tabela 1
    column offsets that a handful of bulletins do not honour.  For each release
    date the split is kept only when every metric satisfies ``centro_sul ==
    sao_paulo + demais_estados``; otherwise the Center-South row -- which
    cross-validates exactly against the season history -- is published alone.
    """
    if wide.empty:
        return wide

    keep_idx: list = []
    for (_hy, _pos), grp in wide.groupby(["harvest_year", "position_date"], sort=False):
        by_region = {r: g.iloc[0] for r, g in grp.groupby("region", sort=False)}
        cs = by_region.get("centro_sul")
        sp, de = by_region.get("sao_paulo"), by_region.get("demais_estados")
        ok = cs is not None and sp is not None and de is not None
        if ok:
            for col in _RELEASE_METRICS:
                a, b, c = cs.get(col), sp.get(col), de.get(col)
                if any(v is None or pd.isna(v) for v in (a, b, c)):
                    continue
                tol = max(_SNAPSHOT_REGION_RTOL * abs(float(a)), _SNAPSHOT_REGION_ATOL)
                if abs(float(a) - float(b) - float(c)) > tol:
                    ok = False
                    break
        if ok:
            keep_idx.extend(grp.index.tolist())
        elif cs is not None:
            keep_idx.extend(grp.index[grp["region"] == "centro_sul"].tolist())
            logger.warning(
                "release_series: %s %s regional split refused (does not reconcile)",
                _hy, _pos,
            )
        else:
            logger.warning(
                "release_series: %s %s dropped (no centro_sul reading)", _hy, _pos,
            )
    return wide.loc[sorted(keep_idx)]


def transform_release_series(df_bronze: pd.DataFrame) -> pd.DataFrame:
    """Transform ``summary_snapshot`` bronze rows to the release series silver.

    Repairs applied here:

    * ``position_date`` is resolved to a real calendar date and emitted as an
      ISO ``YYYY-MM-DD`` string, so the as-of comparison this column feeds is
      chronological rather than the accident of ``DD/MM/YYYY`` text order --
      and a bulletin ingested twice under two cover conventions (a pt
      ``DD/MM/YYYY`` stamp and its English ``MM/DD/YYYY`` twin) collapses to
      one row.  ISO text sorts identically to the underlying dates, so this
      closes the ordering defect without a catalog type change;
    * Tabela 1 row-binding is un-shifted per reading and the truncated
      ``ethanol_total`` recovered from the anhydrous/hydrous identity;
    * values are scaled from Tabela 1's published thousands to the whole
      tonnes / cubic metres the column names promise.

    Args:
        df_bronze: Concatenation of all ``summary_snapshot`` bronze Parquets.
            Required columns: ``harvest_year``, ``idm``, ``period_type``,
            ``region``, ``variable``, ``current_value``, ``prior_value``,
            ``position_date``.

    Returns:
        Wide DataFrame keyed on ``(harvest_year, position_date, region)``.
        See ``RELEASE_SERIES_COLUMNS`` for the full schema.

    Raises:
        ValueError: If required columns are missing.
    """
    required = {
        "harvest_year", "idm", "period_type", "region",
        "variable", "current_value", "prior_value", "position_date",
    }
    missing = required - set(df_bronze.columns)
    if missing:
        raise ValueError(f"release_series bronze missing columns: {sorted(missing)}")

    df = df_bronze.copy()
    if "doc_type" not in df.columns:
        df["doc_type"] = None

    df = df[df["period_type"] == "accumulated"].copy()
    if df.empty:
        logger.warning("release_series: no 'accumulated' period_type rows in bronze input")
        return pd.DataFrame(columns=RELEASE_SERIES_COLUMNS)

    df = df[df["variable"].isin(_RELEASE_SERIES_VARS)].copy()
    if df.empty:
        return pd.DataFrame(columns=RELEASE_SERIES_COLUMNS)

    repaired = pd.Series(False, index=df.index)
    for col in ("current_value", "prior_value"):
        raw = pd.to_numeric(df[col], errors="coerce")
        df[col] = raw.map(_repair_separator_scale)
        repaired |= raw.notna() & (df[col] != raw)
    # Which bulletins needed the separator repair at all -- used to break a tie
    # between a release ingested twice, in favour of the parse that was already
    # at the right scale.
    _needed_repair = set(df.loc[repaired, "idm"].unique())

    df["_pos_date"] = [
        _resolve_position_date(p, d) for p, d in zip(df["position_date"], df["doc_type"])
    ]

    rows: list[dict] = []
    keys = ["harvest_year", "idm", "_pos_date", "region"]
    for (hy, idm, pos, region), grp in df.groupby(keys, sort=False, dropna=False):
        if pos is None or (isinstance(pos, float) and pd.isna(pos)):
            logger.warning("release_series: idm=%s dropped (unparseable position_date)", idm)
            continue
        rec: dict = {
            "harvest_year": hy, "position_date": _iso_or_none(pos),
            "region": region, "_source_idm": idm,
        }
        measured = 0
        current_ok = False
        for vtype, src in (("current", "current_value"), ("prior", "prior_value")):
            vals = {
                var: (sub[src].iloc[0] if not sub.empty else None)
                for var, sub in grp.groupby("variable", sort=False)
            }
            fixed = _unshift_snapshot({v: vals.get(v) for v in _SNAPSHOT_VAR_ORDER})
            if fixed is None or not _validate_snapshot_reading(fixed):
                continue
            if vtype == "current":
                current_ok = True
            for var, val in fixed.items():
                col = f"{var}_{vtype}_{_RELEASE_VAR_UNIT.get(var, '')}"
                rec[col] = float(val) * _SNAPSHOT_UNIT_SCALE
                measured += 1
        if not current_ok:
            logger.warning(
                "release_series: idm=%s region=%s dropped (current vintage failed validation)",
                idm, region,
            )
            continue
        rec["_measured"] = measured
        rec["_repaired"] = idm in _needed_repair
        rows.append(rec)

    if not rows:
        return pd.DataFrame(columns=RELEASE_SERIES_COLUMNS)

    wide = pd.DataFrame(rows)
    for col in RELEASE_SERIES_COLUMNS:
        if col not in wide.columns:
            wide[col] = float("nan")

    # Two bulletins carrying the same release (a pt cover stamp and its English
    # MM/DD twin at a thousandth of the scale) now resolve to one calendar day.
    # Keep the fuller reading, and on a tie the parse that never needed the
    # separator repair -- the one that was already at the published scale.
    wide = wide.sort_values(
        ["_measured", "_repaired", "_source_idm"], ascending=[False, True, True],
        na_position="last",
    ).drop_duplicates(subset=["harvest_year", "position_date", "region"], keep="first")

    wide = _reconcile_release_regions(wide.reset_index(drop=True))

    wide = wide.sort_values(
        ["harvest_year", "region", "position_date"]
    ).reset_index(drop=True)

    logger.info(
        "release_series: %d rows (%d seasons, %d unique position_dates)",
        len(wide), wide["harvest_year"].nunique(), wide["position_date"].nunique(),
    )
    return wide[RELEASE_SERIES_COLUMNS].reset_index(drop=True)


# ---------------------------------------------------------------------------
# Table 3: corn_ethanol
# ---------------------------------------------------------------------------

CORN_ETHANOL_COLUMNS: list[str] = [
    "harvest_year",
    "fortnight_seq",
    "fortnight_label",
    "fortnight_date",
    "anhydrous_quinzenal_kl",
    "hydrous_quinzenal_kl",
    "total_quinzenal_kl",
    "anhydrous_accum_kl",
    "hydrous_accum_kl",
    "total_accum_kl",
    "source_idm",
    "source_position_date",
]

_CORN_ETHANOL_VALUE_COLS: list[str] = [
    "anhydrous_quinzenal_kl",
    "hydrous_quinzenal_kl",
    "total_quinzenal_kl",
    "anhydrous_accum_kl",
    "hydrous_accum_kl",
    "total_accum_kl",
]

_CORN_TRIPLES: list[tuple[str, str, str]] = [
    ("anhydrous_quinzenal_kl", "hydrous_quinzenal_kl", "total_quinzenal_kl"),
    ("anhydrous_accum_kl", "hydrous_accum_kl", "total_accum_kl"),
]


def transform_corn_ethanol(df_bronze: pd.DataFrame) -> pd.DataFrame:
    """Transform ``corn_ethanol`` bronze rows to the corn ethanol silver.

    Deduplicates per ``(harvest_year, fortnight_seq)``, preferring the reading
    with the most populated value columns and then the latest bulletin, so a
    partially-parsed bulletin never displaces a complete one.

    Args:
        df_bronze: Concatenation of all ``corn_ethanol`` bronze Parquets.
            Required columns: ``harvest_year``, ``idm``, ``fortnight_seq``,
            ``fortnight_label``, ``position_date``, ``ingest_date``, and all
            six numeric value columns.

    Returns:
        Wide DataFrame keyed on ``(harvest_year, fortnight_seq)``.
        See ``CORN_ETHANOL_COLUMNS`` for the full schema.

    Raises:
        ValueError: If required columns are missing.
    """
    required = {
        "harvest_year", "idm", "fortnight_seq", "fortnight_label",
        "position_date", "ingest_date",
    }
    missing = required - set(df_bronze.columns)
    if missing:
        raise ValueError(f"corn_ethanol bronze missing columns: {sorted(missing)}")

    df = df_bronze.copy()
    if "doc_type" not in df.columns:
        df["doc_type"] = None

    for col in _CORN_ETHANOL_VALUE_COLS:
        if col not in df.columns:
            df[col] = float("nan")
    df = _scale_columns(df, _CORN_ETHANOL_VALUE_COLS)

    # A negative production reading is impossible -- void the whole triple it
    # belongs to rather than publish a broken identity.
    for anh, hyd, tot in _CORN_TRIPLES:
        bad = df[[anh, hyd, tot]].lt(0).any(axis=1)
        if bad.any():
            df.loc[bad, [anh, hyd, tot]] = float("nan")
        partial = df[[anh, hyd, tot]].notna().any(axis=1) & df[[anh, hyd, tot]].isna().any(axis=1)
        known = partial & df[anh].notna() & df[hyd].notna()
        df.loc[known, tot] = df.loc[known, anh] + df.loc[known, hyd]
        still = df[[anh, hyd, tot]].notna().any(axis=1) & df[[anh, hyd, tot]].isna().any(axis=1)
        if still.any():
            df.loc[still, [anh, hyd, tot]] = float("nan")

    df["_pos_date"] = [
        _resolve_position_date(p, d) for p, d in zip(df["position_date"], df["doc_type"])
    ]
    df["_ing_date"] = df["ingest_date"].map(_resolve_ingest_date)
    df["_sort_date"] = df["_pos_date"].where(df["_pos_date"].notna(), df["_ing_date"])
    df["_measured"] = df[_CORN_ETHANOL_VALUE_COLS].notna().sum(axis=1)

    df = (
        df.sort_values(["_measured", "_sort_date"], ascending=[False, False],
                       na_position="last")
        .drop_duplicates(subset=["harvest_year", "fortnight_seq"], keep="first")
    )

    df = df.rename(columns={"idm": "source_idm"})
    df["source_position_date"] = df["_pos_date"].map(_iso_or_none)

    df["fortnight_date"] = [
        _resolve_fortnight_date(lbl, hy, seq)
        for lbl, hy, seq in zip(df["fortnight_label"], df["harvest_year"], df["fortnight_seq"])
    ]

    for col in CORN_ETHANOL_COLUMNS:
        if col not in df.columns:
            df[col] = None

    df = df.sort_values(["harvest_year", "fortnight_seq"]).reset_index(drop=True)

    logger.info(
        "corn_ethanol: %d rows (%d seasons)", len(df), df["harvest_year"].nunique(),
    )
    return df[CORN_ETHANOL_COLUMNS].reset_index(drop=True)


# ---------------------------------------------------------------------------
# Table 4: monthly_ethanol_sales
# ---------------------------------------------------------------------------

MONTHLY_ETHANOL_SALES_COLUMNS: list[str] = [
    "harvest_year",
    "month_num",
    "month_label",
    "month_date",
    "is_partial",
    "total_current_m3",
    "total_prior_m3",
    "external_current_m3",
    "external_prior_m3",
    "internal_current_m3",
    "internal_prior_m3",
    "source_idm",
    "source_position_date",
]

_MONTHLY_SALES_VALUE_COLS: list[str] = [
    "total_current_m3",
    "total_prior_m3",
    "external_current_m3",
    "external_prior_m3",
    "internal_current_m3",
    "internal_prior_m3",
]

# Tabela 9 splits each month's sales into export ("external") and domestic
# ("internal") legs that sum to the total.  Verified exact on every bronze row
# carrying all three.
_MONTHLY_SALES_TRIPLES: list[tuple[str, str, str]] = [
    ("total_current_m3", "external_current_m3", "internal_current_m3"),
    ("total_prior_m3", "external_prior_m3", "internal_prior_m3"),
]


def transform_monthly_ethanol_sales(df_bronze: pd.DataFrame) -> pd.DataFrame:
    """Transform ``monthly_ethanol_sales`` bronze rows to the monthly sales silver.

    Deduplication prefers the latest bulletin where the month is final
    (``is_partial == False``).  If only partial readings exist for a month,
    the latest partial reading is used.

    Args:
        df_bronze: Concatenation of all ``monthly_ethanol_sales`` bronze Parquets.
            Required columns: ``harvest_year``, ``idm``, ``month_num``,
            ``month_label``, ``is_partial``, ``position_date``, ``ingest_date``,
            and the six numeric value columns.

    Returns:
        Wide DataFrame keyed on ``(harvest_year, month_num)``.
        See ``MONTHLY_ETHANOL_SALES_COLUMNS`` for the full schema.

    Raises:
        ValueError: If required columns are missing.
    """
    required = {
        "harvest_year", "idm", "month_num", "month_label",
        "is_partial", "position_date", "ingest_date",
    }
    missing = required - set(df_bronze.columns)
    if missing:
        raise ValueError(f"monthly_ethanol_sales bronze missing columns: {sorted(missing)}")

    df = df_bronze.copy()
    if "doc_type" not in df.columns:
        df["doc_type"] = None

    df["is_partial"] = df["is_partial"].astype(bool)

    for col in _MONTHLY_SALES_VALUE_COLS:
        if col not in df.columns:
            df[col] = float("nan")
    df = _scale_columns(df, _MONTHLY_SALES_VALUE_COLS)

    df["_pos_date"] = [
        _resolve_position_date(p, d) for p, d in zip(df["position_date"], df["doc_type"])
    ]
    df["_ing_date"] = df["ingest_date"].map(_resolve_ingest_date)
    df["_sort_date"] = df["_pos_date"].where(df["_pos_date"].notna(), df["_ing_date"])

    # Every bulletin lists all twelve months of the season, so a month UNICA
    # has not reported yet arrives as a labelled row with no figures on it.
    # That skeleton is not a reading and must never displace a bulletin that
    # actually carries the month -- ranking on recency alone hands whole
    # seasons to whichever empty skeleton happens to be stamped latest.
    df["_has_values"] = df[_MONTHLY_SALES_VALUE_COLS].notna().any(axis=1)

    # Sort so that: rows carrying figures come first, then final rows
    # (is_partial=False) before partial ones, then the latest date.
    df = df.sort_values(
        ["_has_values", "is_partial", "_sort_date"],
        ascending=[False, True, False],
        na_position="last",
    ).drop_duplicates(subset=["harvest_year", "month_num"], keep="first")

    # Tabela 9's export leg is not captured by the bronze column mapping for
    # the newer layout, but total = external + internal is exact wherever all
    # three survive -- so the missing leg is arithmetic, not a guess.
    for tot, ext, internal in _MONTHLY_SALES_TRIPLES:
        need = df[ext].isna() & df[tot].notna() & df[internal].notna()
        derived = df.loc[need, tot] - df.loc[need, internal]
        df.loc[need, ext] = derived.where(derived >= 0)

    # Add month_date: month 4-12 → year_start, 1-3 → year_end.
    def _month_date(row: pd.Series) -> Optional[str]:
        years = _split_harvest_year(str(row["harvest_year"]))
        if years is None:
            return None
        year_start, year_end = years
        try:
            m = int(row["month_num"])
        except (TypeError, ValueError):
            return None
        if m <= 0 or m > 12:
            return None
        return f"{year_start if m >= 4 else year_end}-{m:02d}-01"

    df["month_date"] = df.apply(_month_date, axis=1)

    df = df.rename(columns={"idm": "source_idm"})
    df["source_position_date"] = df["_pos_date"].map(_iso_or_none)

    for col in MONTHLY_ETHANOL_SALES_COLUMNS:
        if col not in df.columns:
            df[col] = None

    df = df.sort_values(["harvest_year", "month_num"]).reset_index(drop=True)

    logger.info(
        "monthly_ethanol_sales: %d rows (%d seasons)",
        len(df), df["harvest_year"].nunique(),
    )
    return df[MONTHLY_ETHANOL_SALES_COLUMNS].reset_index(drop=True)
