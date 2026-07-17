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
from dataclasses import dataclass
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
    """Shift a canonical ``YYYY-YY`` season back by ``back`` years: ('2011-12', 1) -> '2010-11'."""
    start = int(season.split("-")[0])
    s0 = start - back
    return f"{s0}-{str(s0 + 1)[-2:]}"


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


# Column mapping for the SAGIS ProdProgressive delivery sheets, CALIBRATED against the real
# published workbooks (BF-W3 lane run, 2026-07-15): three sheets per crop file (Total/White/
# Yellow -- Total is authoritative), title block above the table (header at row index ~4),
# columns "Week" / "Week Ending" / "Prog. Total". The pre-calibration placeholder
# (week_no/week_ending/cumulative_tons, sheet 0, header 0) parsed 0 of 2,668 golden rows.
# Explicit ``column_map``/``sheet_name``/``header`` args remain the per-era calibration seam.
DEFAULT_DELIVERY_COLUMN_MAP: dict[str, str] = {
    "week_number": "Week",
    "week_ending_label": "Week Ending",
    "prog_total_mt": "Prog. Total",
}

_HEADER_SCAN_ROWS = 24   # title block depth to scan for the real header row (old .xls maize era
                         # carries the header at row index 16-17, under the grade-legend block)


def _canon_header(s: object) -> str:
    """Header token canonicalization across publication eras: case, punctuation and spacing
    drift ('Week Ending' vs 'Week ending'; 'Prog. Total' vs 'Prog Total'), and the 2010-12
    old-.xls era prints the AFRIKAANS 'Prog Totaal' in the English header row."""
    return " ".join(str(s).strip().lower().replace(".", " ").replace("totaal", "total").split())


def _pick_total_sheet(xl: "pd.ExcelFile") -> object:
    """The authoritative sheet: the one whose name contains 'total' (case-insensitive);
    single-sheet workbooks and unmatched layouts fall back to the first sheet."""
    for name in xl.sheet_names:
        if "total" in str(name).lower():
            return name
    return xl.sheet_names[0]


def _detect_header_row(xl: "pd.ExcelFile", sheet: object, cmap: dict[str, str]) -> int:
    """Scan the title block for the row carrying the mapped source headers (the week column at
    minimum). SAGIS places a multi-row title above the table; hardcoding 0 read the title as
    headers and yielded zero records."""
    probe = xl.parse(sheet, header=None, nrows=_HEADER_SCAN_ROWS)
    want = {_canon_header(v) for v in cmap.values()}
    for i, (_, row) in enumerate(probe.iterrows()):
        cells = {_canon_header(c) for c in row.tolist()}
        if len(want & cells) >= 2:
            return i
    return 0


def read_deliveries_xlsx(
    xlsx_bytes: bytes,
    snapshot: SagisSnapshot,
    *,
    column_map: Optional[dict[str, str]] = None,
    sheet_name: object = None,
    header: Optional[int] = None,
) -> list[DeliveryWeekRecord]:
    """Thin adapter: read one SAGIS delivery snapshot's xlsx bytes into records.

    Selects the authoritative sheet (auto: the 'Total' sheet), detects the real header row
    under the title block (auto), renames the documented source columns via ``column_map``,
    coerces types, and delegates to :func:`records_from_normalized`. Explicit ``sheet_name``/
    ``header`` override the detection (the per-era calibration seam); the deterministic
    producer logic downstream does not depend on the layout.
    """
    import io

    cmap = column_map or DEFAULT_DELIVERY_COLUMN_MAP
    xl = pd.ExcelFile(io.BytesIO(xlsx_bytes))
    sheet = sheet_name if sheet_name is not None else _pick_total_sheet(xl)
    hdr = header if header is not None else _detect_header_row(xl, sheet, cmap)
    df = xl.parse(sheet, header=hdr)
    # match source headers by CANONICAL token (era drift: 'Week ending', 'Prog Total').
    # WIDE GRADE-BLOCK eras (old .xls maize; the 2016-18 'Table 1' era): White/Yellow/Total
    # blocks repeat the same headers side by side and the TOTAL block is rightmost -- the
    # published prog total is therefore the LAST 'prog total' column, never the first (the
    # first is the White block; picking it minted white-only values for 2016-17, live-caught).
    # Every other mapped target keeps first-match; unmatched columns pass through untouched.
    inv = {_canon_header(src): dst for dst, src in cmap.items()}
    cols = list(df.columns)
    rename, taken = {}, set()
    prog_src = _canon_header(cmap.get("prog_total_mt", ""))
    # pandas dedupes repeated headers as 'Prog Total.1' / '.2' -- canonically 'prog total N';
    # accept the bare token plus the dedup-suffixed forms so the LAST block is reachable.
    prog_pat = re.compile(rf"{re.escape(prog_src)}( \d+)?$")
    prog_matches = [c for c in cols if prog_pat.fullmatch(_canon_header(c))]
    if prog_matches:
        rename[prog_matches[-1]] = "prog_total_mt"
        taken.add("prog_total_mt")
    for col in cols:
        dst = inv.get(_canon_header(col))
        if dst and dst not in taken and col not in rename:
            rename[col] = dst
            taken.add(dst)
    df = df.rename(columns=rename)
    # UNIT SCALE (old-era finals publish in '000 ton; the modern era in tons). The label alone
    # LIES on at least one file (wheat 2005-06 says '000 ton over plain-ton values), so the
    # scale applies ONLY when the label says thousands AND the magnitudes agree: a full-season
    # cumulative below 50,000 cannot be tons for any SA crop, and a '000-ton cumulative above
    # it (>= 50M tons) is equally impossible. Both signals must point the same way.
    scale = 1.0
    try:
        probe = xl.parse(sheet, header=None, nrows=hdr)
        says_thousand = any("'000" in str(v) for _, r in probe.iterrows() for v in r.tolist())
    except Exception:  # noqa: BLE001 -- a probe failure never blocks the read
        says_thousand = False
    if says_thousand and "prog_total_mt" in df.columns:
        vals = pd.to_numeric(df["prog_total_mt"], errors="coerce").dropna()
        if len(vals) and float(vals.max()) < 50_000:
            scale = 1000.0
            logger.info("SAGIS deliveries %s: '000-ton era detected (max %.0f) -> x1000",
                        snapshot.filename, float(vals.max()))
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
            # source cells carry stray trailing blanks in the old .xls era -- strip, and an
            # all-blank label is no label.
            s = None if pd.isna(val) else str(val).strip()
            rec["week_ending_label"] = s or None
        if "prog_total_mt" in df.columns:
            val = r.get("prog_total_mt")
            try:
                rec["prog_total_mt"] = None if pd.isna(val) else float(val) * scale
            except (TypeError, ValueError):
                rec["prog_total_mt"] = None
        # print-layout GHOST TAIL (old .xls era, live-caught): a second page block repeats the
        # bare week-number column 4..53 with every value cell empty. A week number with neither
        # a week-ending label nor a prog total is not an observation -- emitting it minted
        # None-valued records that collided with the real weeks at the co-authoritative guard.
        if rec.get("week_ending_label") is None and rec.get("prog_total_mt") is None:
            continue
        normalized.append(rec)
    # WITHIN-FILE revision collapse (live-caught: wheat 2011-12 week 51): a repeated week
    # number inside ONE snapshot is a sequential post-season adjustment of the cumulative
    # ('24 Oct' -3711 then '28 Nov' -26); the sheet's bottom-most occurrence is the season
    # final. Cross-snapshot conflicts still fail closed at the co-authoritative guard --
    # this collapse only ever applies within a single file.
    by_week: dict[int, dict] = {}
    dups = 0
    for rec in normalized:
        if rec["week_number"] in by_week:
            dups += 1
        by_week[rec["week_number"]] = rec
    if dups:
        logger.info("SAGIS deliveries %s: %d within-file week revisions collapsed (last wins)",
                    snapshot.filename, dups)
    return records_from_normalized(list(by_week.values()), snapshot)


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

    # Derived-column semantics REVERSE-ENGINEERED from the golden physical (BF-W3 lane,
    # exact-match verified 782/800 pct + 500/500 z sampled rows): pct_of_prior_yr is the plain
    # RATIO prog / prior-season-same-week (never x100), and z_vs_3yr_avg uses the SAMPLE std
    # (ddof=1) over the trailing <=3 prior seasons' same week. prior_prog_total_mt is emitted
    # for EVERY row with a prior observation -- the golden populated it only from 2023-24
    # onward (a builder quirk on this non-census-gated column; documented deviation).
    prior_tot, pct, zscore = [], [], []
    for r in df.itertuples(index=False):
        p1 = lut.get((_season_shift(r.season, 1), r.crop, r.week_number))
        prior_tot.append(p1)
        cur = r.prog_total_mt
        pct.append(
            (cur / p1) if (cur is not None and p1 not in (None, 0) and not _isnan(p1)) else np.nan
        )
        # Trailing 3 PRIOR seasons (never the current/future) for the z-score.
        hist = [
            lut.get((_season_shift(r.season, k), r.crop, r.week_number)) for k in (1, 2, 3)
        ]
        hist = [h for h in hist if h is not None and not _isnan(h)]
        if cur is not None and not _isnan(cur) and len(hist) >= 2:
            mu = float(np.mean(hist))
            sd = float(np.std(hist, ddof=1))
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
