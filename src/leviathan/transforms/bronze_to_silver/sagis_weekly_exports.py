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
  * ``week_ending_date`` -- the ISO calendar date of the last day of the ``week_ending`` free-text
                           range (e.g. ``'3 - 9 May 2003'`` -> ``2003-05-09``). This is the
                           leakage-safe point-in-time as-of anchor the numbers agent card needs; the
                           source labels most weeks WITHOUT a year, so the year is inferred by
                           carry-forward + Dec->Jan wrap detection re-anchored on the weeks that DO
                           carry an explicit year (see :func:`derive_week_ending_dates`). It is the
                           TRUE week-ending date; the numbers card applies its own publication lag on
                           top (data_date semantics, +5d ratified) -- NOT baked in here.

Output: ``[season, crop, week_number, week_ending, week_ending_date, prog_exports_mt,
pct_of_prior_yr, z_vs_3yr_avg, source]``. Pure + AWS-free.
"""
from __future__ import annotations

import datetime as dt
import re
import statistics
from dataclasses import dataclass
from typing import Optional

import pandas as pd

from leviathan.common.logging import get_logger

logger = get_logger(__name__)

OUTPUT_COLUMNS: list[str] = [
    "season", "crop", "week_number", "week_ending", "week_ending_date", "prog_exports_mt",
    "pct_of_prior_yr", "z_vs_3yr_avg", "source",
]

NATURAL_KEY = ["season", "crop", "week_number"]
_SEASON_START_RE = re.compile(r"(\d{4})")

# --- week_ending free-text -> ISO date parsing --------------------------------------------------
# SAGIS labels each row's week as a free-text day range whose END carries the week-ending day. The
# real formats (probed against the live silver 2026-07-23, all 1204 rows) are:
#   '3 - 9 May 2003'  week-1, explicit 4-digit year         '10 - 16 May'   no year
#   '31 May - 6 Jun'  cross-month, no year                  '27 Dec - 2 Jan 2004'  cross-year+year
#   '2 - 8Aug'        missing space before the month        "30 Apr - 6 May '05"   two-digit year
#   '07 Oct/Okt 2016' bilingual English/Afrikaans month     '1 - 7 Mar/Mrt 2014'   zero-padded day
# Every row carries exactly ONE separating dash, so splitting on the first dash isolates the END.
_MONTHS: dict[str, int] = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    # Afrikaans abbreviations SAGIS interleaves as "Month/Maand" (English first): Mrt=Mar, Mei=May,
    # Okt=Oct, Des=Dec. The others coincide with the English 3-letter form.
    "mrt": 3, "mei": 5, "okt": 10, "des": 12,
}
_DASH = "[-–—]"                                    # hyphen / en-dash / em-dash
_END_RE = re.compile(r"^(\d{1,2})\s*([A-Za-z]+(?:/[A-Za-z]+)?)\.?\s*((?:19|20)\d{2}|'\d{2})?\.?$")

# --- D-LD (2026-08-18): the MONTH-WORD-LESS label eras the DELIVERIES sibling publishes ----------
# MEASURED against all 3,007 rows of the canonical silver_sagis_weekly_deliveries parquet: from
# 2013-14 onward SAGIS prints the delivery week as a purely NUMERIC range with no month word at
# all, so ``_END_RE`` (which requires a letter month token) returned None for 2,244 of them --
# 763/3,007 = 25.4% coverage. The live end-token forms:
#     '24/02 - 02/03/2018'      '27/04-03/05/2013'      '01/08 - 07/08/2026'
# Day order is SOUTH AFRICAN dd/mm[/yyyy], verified on the data's own edge: '01/08 - 07/08/2026'
# is the week ending FRIDAY 7 August 2026 (the newest published week), not 8 July. A token whose
# month field falls outside 1-12 is REFUSED rather than swapped -- guessing the order would mint a
# silently wrong week, and a null date is honest where a wrong one is not.
_NUMERIC_END_RE = re.compile(r"^(\d{1,2})[/.](\d{1,2})(?:[/.]((?:19|20)\d{2}|\d{2}))?\.?$")
# An ALREADY-ISO label: ``sagis_deliveries.canonical_week_ending`` emits 'YYYY-MM-DD' whenever the
# source sheet carried a real date cell, which is precisely the row with the BEST source date and
# would otherwise be the one row shape with no anchor. Matched on the WHOLE label BEFORE the dash
# split, because 'YYYY-MM-DD' would be torn at its first hyphen by the range splitter.
_ISO_END_RE = re.compile(r"^((?:19|20)\d{2})-(\d{1,2})-(\d{1,2})$")


def _month_number(token: str) -> Optional[int]:
    """Resolve a (possibly bilingual ``Eng/Afr``) month token to 1-12, else None."""
    for part in token.split("/"):
        key = part.strip().lower()[:3]
        if key in _MONTHS:
            return _MONTHS[key]
    return None


def _parse_numeric_end(raw: str, end: str) -> Optional[tuple[int, int, Optional[int]]]:
    """Month-word-less fallback -> ``(day, month, year_or_None)``, else None.

    Reached ONLY when the letter-month branch resolved nothing, so it cannot change a single value
    that already parses: ``silver_sagis_weekly_exports`` derives 1,204/1,204 of its week dates on
    the letter branch alone and never enters here.
    """
    iso = _ISO_END_RE.match(raw)
    if iso:
        year, month, day = int(iso.group(1)), int(iso.group(2)), int(iso.group(3))
        return (day, month, year) if 1 <= month <= 12 and 1 <= day <= 31 else None
    m = _NUMERIC_END_RE.match(end)
    if not m:
        return None
    day, month = int(m.group(1)), int(m.group(2))
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None                                  # never swap d/m to force a parse
    ytok = m.group(3)
    year: Optional[int] = None
    if ytok:
        year = int(ytok) if len(ytok) == 4 else 2000 + int(ytok)
    return day, month, year


def parse_week_ending_end(text: Optional[str]) -> Optional[tuple[int, int, Optional[int]]]:
    """Parse the END of a SAGIS free-text week range -> ``(day, month, year_or_None)``.

    Splits off everything after the single separating dash and parses the day, month (English or the
    bilingual ``Eng/Afr`` form), and an optional trailing year (4-digit or ``'YY`` short form). When
    the label carries NO month word at all -- the numeric ``dd/mm[/yyyy]`` and ISO eras the
    deliveries sibling publishes -- :func:`_parse_numeric_end` is tried as a strictly None-only
    fallback. Returns None on anything unparseable (fail-soft -- the caller emits a null date,
    never a guess).
    """
    if not text:
        return None
    raw = str(text).strip()
    end = re.split(r"\s*" + _DASH + r"\s*", raw, maxsplit=1)[-1].strip()
    m = _END_RE.match(end)
    if m:
        month = _month_number(m.group(2))
        if month is not None:
            day = int(m.group(1))
            ytok = m.group(3)
            year: Optional[int] = None
            if ytok:
                year = 2000 + int(ytok[1:]) if ytok.startswith("'") else int(ytok)
            return day, month, year
    return _parse_numeric_end(raw, end)


def derive_week_ending_dates(
    season: str, weeks: list[tuple[int, Optional[str]]]
) -> dict[int, Optional[dt.date]]:
    """Derive the ISO ``week_ending_date`` for every ``(week_number, week_ending)`` in ONE season+crop.

    The source labels only some weeks (week-1 and the Dec->Jan cross-year week) with an explicit
    year; the rest omit it. Year inference, in ascending week order:
      * anchor the running year to the season-start calendar year (from ``'YYYY-YY'``) at the first
        week that lacks an explicit year;
      * an explicit trailing year, wherever it appears, RE-ANCHORS the running year exactly (so the
        cross-year week's ``2004`` corrects the carry at the wrap, and any drift is self-healing);
      * otherwise bump the year by one whenever the parsed end-month DECREASES vs the previous week
        (the Dec->Jan boundary) -- robust even for a 53-week season that laps its start month.
    Rows whose ``week_ending`` is null/unparseable map to None (fail-soft). No lookahead beyond the
    already-known label text; this is a pure timing derivation and never touches a measured value.
    """
    out: dict[int, Optional[dt.date]] = {}
    cur_year: Optional[int] = None
    prev_month: Optional[int] = None
    for week_number, text in sorted(weeks, key=lambda w: w[0]):
        parsed = parse_week_ending_end(text)
        if parsed is None:
            out[week_number] = None
            continue
        day, month, year = parsed
        if year is not None:
            cur_year = year
        elif cur_year is None:
            cur_year = season_start_year(season)
        elif prev_month is not None and month < prev_month:
            cur_year += 1
        prev_month = month
        if cur_year is None:
            out[week_number] = None
            continue
        try:
            out[week_number] = dt.date(cur_year, month, day)
        except ValueError:
            out[week_number] = None                          # e.g. an impossible day/month -> null
    return out


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

    # Derive the ISO week-ending DATE per (season, crop) group from the free-text week_ending range
    # (year inferred by carry-forward + wrap detection, re-anchored on explicit-year weeks). Held as
    # python ``datetime.date`` -> the flat publisher encodes it date32[day] per the contract.
    date_by_key: dict[tuple, Optional[dt.date]] = {}
    for (season, crop), grp in df.groupby(["season", "crop"]):
        weeks = [(int(w), we) for w, we in zip(grp["week_number"], grp["week_ending"])]
        for wk, when in derive_week_ending_dates(season, weeks).items():
            date_by_key[(season, crop, wk)] = when
    df["week_ending_date"] = [
        date_by_key.get((r["season"], r["crop"], int(r["week_number"])))
        for _, r in df.iterrows()
    ]

    df = df.sort_values(NATURAL_KEY).reset_index(drop=True)
    return df[OUTPUT_COLUMNS]
