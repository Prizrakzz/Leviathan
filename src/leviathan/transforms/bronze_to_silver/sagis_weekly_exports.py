"""SILVER-F059: SAGIS weekly exports producer (silver_sagis_weekly_exports).

Grain / natural key: ``season x crop x week_number``.

SAGIS publishes ONE cumulative (progressive) weekly export file per marketing season, re-uploaded
each week under a new filename. :func:`select_authoritative_snapshot` picks the governed snapshot
per season (the reuse point for the SB-F042 shared snapshot selector -- kept local here so this
producer has no cross-lane import dependency; consolidate when F042 lands): the snapshot with the
widest week coverage, then the latest release. Within that snapshot, grade-breakdown rows and the
'Total' row are filtered so exports are NEVER double-counted, uniqueness is enforced BEFORE any
comparison metric, and the trailing metrics are STRICTLY no-lookahead (only earlier seasons feed
them):

  * ``pct_of_prior_yr`` -- 100 * prog_exports_mt / (prior season, same week_number). None if absent.
  * ``z_vs_3yr_avg``    -- (prog - mean) / std over the <=3 most recent PRIOR seasons at the same
                           week_number. None when <2 prior seasons (std undefined) -- insufficient
                           history is honestly null, never fabricated.

Output: ``[season, crop, week_number, week_ending, prog_exports_mt, pct_of_prior_yr, z_vs_3yr_avg,
source]``. Pure + AWS-free.
"""
from __future__ import annotations

import re
import statistics
from dataclasses import dataclass
from typing import Optional

import pandas as pd

from leviathan.common.logging import get_logger

logger = get_logger(__name__)

OUTPUT_COLUMNS: list[str] = [
    "season", "crop", "week_number", "week_ending", "prog_exports_mt",
    "pct_of_prior_yr", "z_vs_3yr_avg", "source",
]

NATURAL_KEY = ["season", "crop", "week_number"]
_SEASON_START_RE = re.compile(r"(\d{4})")


class SagisDoubleCountError(ValueError):
    """A week carried both a total and grade rows in a way that would double-count (fail closed)."""


@dataclass(frozen=True)
class WeeklyExportRow:
    """One parsed SAGIS weekly export observation from governed bronze."""

    season: str                     # 'YYYY-YY' or 'YYYY/YY'
    crop: str
    week_number: int
    prog_exports_mt: Optional[float]
    week_ending: Optional[str] = None
    is_total: bool = True           # True = season/grade total row; False = a single-grade row
    snapshot_id: str = ""           # the source file identity (a season may have many snapshots)
    snapshot_week: int = 0          # widest week the snapshot covers (snapshot recency proxy)
    snapshot_release_date: Optional[str] = None
    source: str = "sagis_weekly"


def season_start_year(season: str) -> Optional[int]:
    m = _SEASON_START_RE.search(season or "")
    return int(m.group(1)) if m else None


def select_authoritative_snapshot(rows: list[WeeklyExportRow]) -> list[WeeklyExportRow]:
    """Keep only the governed snapshot per season (widest week coverage, then latest release).

    This is the F042-style governed selector, local to avoid a cross-lane dependency."""
    # rank each snapshot per season
    best_snap: dict[str, tuple] = {}
    for r in rows:
        rank = (r.snapshot_week, r.snapshot_release_date or "", r.snapshot_id)
        cur = best_snap.get(r.season)
        if cur is None or rank > cur:
            best_snap[r.season] = rank
    winner_id: dict[str, str] = {}
    # resolve the winning snapshot_id per season from the winning rank
    for r in rows:
        rank = (r.snapshot_week, r.snapshot_release_date or "", r.snapshot_id)
        if rank == best_snap[r.season]:
            winner_id[r.season] = r.snapshot_id
    return [r for r in rows if r.snapshot_id == winner_id.get(r.season)]


def _dedupe_grade_total(rows: list[WeeklyExportRow]) -> list[dict]:
    """Filter grade vs total rows so exports are counted once per (season, crop, week).

    Prefer an explicit total row; if a week has ONLY grade rows, sum them (documented). Mixing a
    total row with grade rows for the same key AND disagreeing is a double-count error."""
    by_key: dict[tuple, dict] = {}
    grades: dict[tuple, list[float]] = {}
    for r in rows:
        key = (r.season, r.crop, int(r.week_number))
        if r.is_total:
            existing = by_key.get(key)
            if existing is not None and existing["prog_exports_mt"] != r.prog_exports_mt:
                raise SagisDoubleCountError(
                    f"two conflicting total rows for {key}: "
                    f"{existing['prog_exports_mt']} vs {r.prog_exports_mt}"
                )
            by_key[key] = {
                "season": r.season, "crop": r.crop, "week_number": int(r.week_number),
                "week_ending": r.week_ending, "prog_exports_mt": r.prog_exports_mt,
                "source": r.source,
            }
        else:
            if r.prog_exports_mt is not None:
                grades.setdefault(key, []).append(float(r.prog_exports_mt))
    # weeks with only grade rows -> sum them
    for key, vals in grades.items():
        if key not in by_key:
            season, crop, week = key
            by_key[key] = {
                "season": season, "crop": crop, "week_number": week,
                "week_ending": None, "prog_exports_mt": sum(vals), "source": "sagis_weekly",
            }
    return list(by_key.values())


def _prior_seasons(all_starts: list[int], current_start: int, n: int) -> list[int]:
    """The <=n most recent prior season start-years (strict no-lookahead: strictly earlier)."""
    earlier = sorted((s for s in set(all_starts) if s < current_start), reverse=True)
    return earlier[:n]


def transform_weekly_exports(rows: list[WeeklyExportRow]) -> pd.DataFrame:
    """Transform governed SAGIS weekly export bronze into the silver table with trailing metrics."""
    chosen = select_authoritative_snapshot(rows)
    deduped = _dedupe_grade_total(chosen)
    if not deduped:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    df = pd.DataFrame.from_records(deduped)
    if df.duplicated(subset=NATURAL_KEY).any():
        raise SagisDoubleCountError("season x crop x week_number not unique after grade/total filter")

    df["_start"] = df["season"].map(season_start_year)

    # Build a lookup: (crop, start_year, week) -> prog_exports_mt (from the authoritative snapshots).
    lookup: dict[tuple, float] = {}
    for _, r in df.iterrows():
        if r["_start"] is not None and pd.notna(r["prog_exports_mt"]):
            lookup[(r["crop"], int(r["_start"]), int(r["week_number"]))] = float(r["prog_exports_mt"])

    starts_by_crop: dict[str, list[int]] = {}
    for crop, grp in df.groupby("crop"):
        starts_by_crop[crop] = sorted({int(s) for s in grp["_start"] if pd.notna(s)})

    pct_list: list[Optional[float]] = []
    z_list: list[Optional[float]] = []
    for _, r in df.iterrows():
        crop = r["crop"]
        start = r["_start"]
        week = int(r["week_number"])
        cur = r["prog_exports_mt"]
        if start is None or pd.isna(cur):
            pct_list.append(None)
            z_list.append(None)
            continue
        start = int(start)
        prior_yr = lookup.get((crop, start - 1, week))
        pct_list.append(100.0 * float(cur) / prior_yr if prior_yr not in (None, 0) else None)

        prior_starts = _prior_seasons(starts_by_crop.get(crop, []), start, 3)
        hist = [lookup[(crop, s, week)] for s in prior_starts if (crop, s, week) in lookup]
        if len(hist) >= 2:
            mean = statistics.fmean(hist)
            sd = statistics.stdev(hist)
            z_list.append((float(cur) - mean) / sd if sd > 0 else None)
        else:
            z_list.append(None)

    df["pct_of_prior_yr"] = pct_list
    df["z_vs_3yr_avg"] = z_list
    df = df.sort_values(NATURAL_KEY).reset_index(drop=True)
    return df[OUTPUT_COLUMNS]
