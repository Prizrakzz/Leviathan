"""SAGIS weekly producer-deliveries producer (SILVER-F042, atomic fix 2 of 2).

Builds ``silver_sagis_weekly_deliveries`` (grain: season x crop x week_number) from the
per-week delivery records carried by overlapping cumulative SAGIS snapshots. Depends on
the shared snapshot parser (:mod:`leviathan.transforms.bronze_to_silver.sagis_common`).

The four correctness rules the plan calls out:
  1. **Authoritative selection.** For each (season, crop, week_number) the record from the
     highest-authority snapshot (publication metadata, then week number) wins. Two records
     that DISAGREE at the SAME authority level fail closed (no silent average/keep-last).
  2. **Grade/total double-count guard.** ``prog_total_mt`` is the PUBLISHED cumulative total
     when present; otherwise the summed per-grade cumulative. The published total and the
     summed grades are NEVER both counted. When both exist they are reconciled (a mismatch
     beyond tolerance is flagged).
  3. **Uniqueness before comparison.** prior-year / trailing-z comparisons are computed only
     AFTER the natural key is unique -- and only against PRIOR seasons (no future leakage).
  4. The known ``2011-12 x wheat x week 51`` overlap (two snapshots reporting week 51) resolves
     to the later-published snapshot.

Pure + AWS-free. ASCII only.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional, Sequence

import numpy as np
import pandas as pd
import pyarrow as pa

from leviathan.common.logging import get_logger
from leviathan.transforms.bronze_to_silver.sagis_common import (
    SagisSnapshot,
    rank_snapshots,
    same_authority,
)

logger = get_logger(__name__)

SOURCE = "sagis_weekly"

# Fetcher crop labels -> canonical delivery crop. A grade dataset decomposes its base crop;
# it contributes grade totals, never a separate additive crop row.
_CROP_CANONICAL: dict[str, str] = {
    "maize": "maize",
    "maize_grade": "maize",
    "wheat": "wheat",
    "soybeans": "soybeans",
    "sunflower": "sunflower",
}
_GRADE_CROPS = {"maize_grade"}

# Tolerance for reconciling summed grades against the published total (fraction of total).
_GRADE_RECONCILE_TOL = 0.02

_SILVER_COLUMNS: list[str] = [
    "season", "crop", "week_number", "week_ending",
    "prog_total_mt", "prior_prog_total_mt", "pct_of_prior_yr", "z_vs_3yr_avg", "source",
]

# INV-2 explicit writer schema, matching the silver_sagis_weekly_deliveries registry.
SILVER_ARROW_SCHEMA = pa.schema([
    ("season", pa.string()),
    ("crop", pa.string()),
    ("week_number", pa.int64()),
    ("week_ending", pa.string()),
    ("prog_total_mt", pa.float64()),
    ("prior_prog_total_mt", pa.float64()),
    ("pct_of_prior_yr", pa.float64()),
    ("z_vs_3yr_avg", pa.float64()),
    ("source", pa.string()),
])

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass
class DeliveryWeekRecord:
    """One (snapshot, week) delivery observation before authoritative selection.

    ``prog_total_mt`` is the published cumulative total for base-crop records; grade-dataset
    records instead carry ``grade_totals_mt`` (per-grade cumulative) and no total.
    """

    snapshot: SagisSnapshot
    season: str
    crop_label: str                       # raw fetcher label (maize / maize_grade / ...)
    week_number: int
    week_ending_label: Optional[str] = None
    week_ending_date: Optional[str] = None   # ISO, only when reliably parsed
    prog_total_mt: Optional[float] = None
    grade_totals_mt: Optional[dict[str, float]] = None

    @property
    def crop(self) -> str:
        return _CROP_CANONICAL.get(self.crop_label, self.crop_label)

    @property
    def is_grade(self) -> bool:
        return self.crop_label in _GRADE_CROPS


def canonical_week_ending(rec: DeliveryWeekRecord) -> Optional[str]:
    """The week_ending value to emit: the reliably-parsed ISO date, else the raw label."""
    if rec.week_ending_date and _ISO_DATE_RE.match(rec.week_ending_date):
        return rec.week_ending_date
    return rec.week_ending_label


def reconcile_grade_total(
    total: Optional[float], grade_totals: Optional[dict[str, float]]
) -> tuple[Optional[float], Optional[str]]:
    """Return ``(prog_total_mt, reconcile_flag)`` enforcing the no-double-count rule.

    * both present -> keep the PUBLISHED total; flag if summed grades disagree beyond tol;
    * total only   -> the total;
    * grades only  -> the summed grades (a fallback, never added to a total);
    * neither      -> (None, "no_value").
    """
    summed = None
    if grade_totals:
        summed = float(sum(v for v in grade_totals.values() if v is not None))
    if total is not None and summed is not None:
        if total != 0 and abs(summed - total) / abs(total) > _GRADE_RECONCILE_TOL:
            return total, f"grade_total_mismatch(sum={summed:.1f},total={total:.1f})"
        return total, "reconciled"
    if total is not None:
        return total, "total_only"
    if summed is not None:
        return summed, "grades_only"
    return None, "no_value"


def select_authoritative(records: Sequence[DeliveryWeekRecord]) -> list[dict]:
    """Collapse per-snapshot records to ONE authoritative row per (season, crop, week_number).

    Raises:
        ValueError: if two records at the SAME authority level disagree on the published
            total for the same key (an unresolved conflict).
    """
    by_key: dict[tuple, list[DeliveryWeekRecord]] = {}
    for r in records:
        by_key.setdefault((r.season, r.crop, r.week_number), []).append(r)

    rows: list[dict] = []
    for (season, crop, week), recs in by_key.items():
        totals = [r for r in recs if not r.is_grade]
        grades = [r for r in recs if r.is_grade]

        chosen_total: Optional[DeliveryWeekRecord] = None
        if totals:
            ranked = rank_snapshots([r.snapshot for r in totals])
            best_snap = ranked[-1]
            best = [r for r in totals if r.snapshot is best_snap][0]
            # Fail closed if a co-authoritative record disagrees on the total.
            for r in totals:
                if r is best:
                    continue
                if same_authority(r.snapshot, best_snap) and r.prog_total_mt != best.prog_total_mt:
                    raise ValueError(
                        f"SAGIS deliveries: conflicting co-authoritative total for "
                        f"({season},{crop},week {week}): {r.prog_total_mt} vs {best.prog_total_mt} "
                        f"(snapshots {r.snapshot.filename} / {best.snapshot.filename})"
                    )
            chosen_total = best

        chosen_grade: Optional[DeliveryWeekRecord] = None
        if grades:
            ranked = rank_snapshots([r.snapshot for r in grades])
            best_snap = ranked[-1]
            chosen_grade = [r for r in grades if r.snapshot is best_snap][0]

        total_val = chosen_total.prog_total_mt if chosen_total else None
        grade_map = chosen_grade.grade_totals_mt if chosen_grade else None
        prog_total, flag = reconcile_grade_total(total_val, grade_map)
        if flag and flag.startswith("grade_total_mismatch"):
            logger.warning("SAGIS deliveries %s %s wk%d: %s", season, crop, week, flag)

        we_rec = chosen_total or chosen_grade
        rows.append({
            "season": season,
            "crop": crop,
            "week_number": int(week),
            "week_ending": canonical_week_ending(we_rec) if we_rec else None,
            "prog_total_mt": prog_total,
        })
    return rows


def _season_shift(season: str, back: int) -> str:
    """Shift a ``YYYY/YY`` season back by ``back`` years: ('2011/12', 1) -> '2010/11'."""
    start = int(season.split("/")[0])
    s0 = start - back
    return f"{s0}/{str(s0 + 1)[-2:]}"


def records_from_normalized(
    normalized: Sequence[dict], snapshot: SagisSnapshot,
) -> list[DeliveryWeekRecord]:
    """Build :class:`DeliveryWeekRecord` list from normalized week dicts for one snapshot.

    Each ``normalized`` dict carries: ``week_number`` (int, required), ``week_ending_label``
    / ``week_ending_date`` (optional), and EITHER ``prog_total_mt`` (base-crop total) OR
    ``grade_totals_mt`` (dict, grade dataset). ``season`` / ``crop`` come from the snapshot.
    Rows without a usable week_number or season are skipped (quarantined, never mis-keyed).
    """
    out: list[DeliveryWeekRecord] = []
    for row in normalized:
        wk = row.get("week_number")
        if wk is None or snapshot.season is None:
            continue
        out.append(DeliveryWeekRecord(
            snapshot=snapshot,
            season=snapshot.season,
            crop_label=snapshot.crop,
            week_number=int(wk),
            week_ending_label=row.get("week_ending_label"),
            week_ending_date=row.get("week_ending_date"),
            prog_total_mt=row.get("prog_total_mt"),
            grade_totals_mt=row.get("grade_totals_mt"),
        ))
    return out


# Documented default column mapping for the SAGIS ProdProgressive delivery sheets. The exact
# published column headers vary by era/crop; this map is the calibration point (a real run
# passes explicit ``column_map``). NOT part of the deterministic acceptance surface -- the
# selection/aggregation/comparison logic (tested) is source-layout-independent.
DEFAULT_DELIVERY_COLUMN_MAP: dict[str, str] = {
    "week_number": "week_no",
    "week_ending_label": "week_ending",
    "prog_total_mt": "cumulative_tons",
}


def read_deliveries_xlsx(
    xlsx_bytes: bytes,
    snapshot: SagisSnapshot,
    *,
    column_map: Optional[dict[str, str]] = None,
    sheet_name: object = 0,
    header: int = 0,
) -> list[DeliveryWeekRecord]:
    """Thin adapter: read one SAGIS delivery snapshot's xlsx bytes into records.

    Reads the sheet with pandas, renames the documented source columns via ``column_map``,
    coerces types, and delegates to :func:`records_from_normalized`. The Excel layout is a
    documented assumption (``DEFAULT_DELIVERY_COLUMN_MAP``); the deterministic producer logic
    downstream does not depend on it.
    """
    import io

    cmap = column_map or DEFAULT_DELIVERY_COLUMN_MAP
    df = pd.read_excel(io.BytesIO(xlsx_bytes), sheet_name=sheet_name, header=header)
    inv = {src: dst for dst, src in cmap.items()}
    df = df.rename(columns=inv)
    normalized: list[dict] = []
    for _, r in df.iterrows():
        wk = r.get("week_number")
        try:
            wk = int(wk)
        except (TypeError, ValueError):
            continue
        rec: dict = {"week_number": wk}
        if "week_ending_label" in df.columns:
            val = r.get("week_ending_label")
            rec["week_ending_label"] = None if pd.isna(val) else str(val)
        if "prog_total_mt" in df.columns:
            val = r.get("prog_total_mt")
            rec["prog_total_mt"] = None if pd.isna(val) else float(val)
        normalized.append(rec)
    return records_from_normalized(normalized, snapshot)


def build_deliveries_silver(records: Sequence[DeliveryWeekRecord]) -> pd.DataFrame:
    """Build the deliveries silver table from per-snapshot records.

    Authoritative selection -> uniqueness assertion -> prior-year + trailing-z comparisons
    (PRIOR seasons only). Returns a DataFrame with the frozen contract column order.
    """
    if not records:
        return pd.DataFrame(columns=_SILVER_COLUMNS)

    rows = select_authoritative(records)
    df = pd.DataFrame(rows)

    # Uniqueness of the natural key BEFORE any comparison (no leakage from a dup).
    if df.duplicated(subset=["season", "crop", "week_number"]).any():
        raise ValueError("SAGIS deliveries: duplicate (season, crop, week_number) after selection")

    # Index for prior-season lookups: (season, crop, week) -> prog_total_mt.
    lut = {
        (r.season, r.crop, r.week_number): r.prog_total_mt
        for r in df.itertuples(index=False)
    }

    prior_tot, pct, zscore = [], [], []
    for r in df.itertuples(index=False):
        p1 = lut.get((_season_shift(r.season, 1), r.crop, r.week_number))
        prior_tot.append(p1)
        cur = r.prog_total_mt
        pct.append(
            (cur / p1 * 100.0) if (cur is not None and p1 not in (None, 0) and not _isnan(p1)) else np.nan
        )
        # Trailing 3 PRIOR seasons (never the current/future) for the z-score.
        hist = [
            lut.get((_season_shift(r.season, k), r.crop, r.week_number)) for k in (1, 2, 3)
        ]
        hist = [h for h in hist if h is not None and not _isnan(h)]
        if cur is not None and not _isnan(cur) and len(hist) >= 2:
            mu = float(np.mean(hist))
            sd = float(np.std(hist, ddof=0))
            zscore.append((cur - mu) / sd if sd > 0 else np.nan)
        else:
            zscore.append(np.nan)

    df["prior_prog_total_mt"] = prior_tot
    df["pct_of_prior_yr"] = pct
    df["z_vs_3yr_avg"] = zscore
    df["source"] = SOURCE

    for c in ("prog_total_mt", "prior_prog_total_mt", "pct_of_prior_yr", "z_vs_3yr_avg"):
        df[c] = df[c].astype("float64")
    df["week_number"] = df["week_number"].astype("int64")

    return df[_SILVER_COLUMNS].sort_values(
        ["season", "crop", "week_number"]
    ).reset_index(drop=True)


def _isnan(x) -> bool:
    return isinstance(x, float) and np.isnan(x)
