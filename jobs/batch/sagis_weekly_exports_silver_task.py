"""SILVER-F059 batch task: SAGIS weekly-export RAW workbooks -> silver_sagis_weekly_exports.

Restores the C-WRONG-8 half-orphan producer on the SILVER-F015 publisher. Reads the cumulative
per-season SAGIS import/export Excel snapshots from RAW S3 -- exactly as the
``sagis_deliveries_task`` sibling does -- selects the authoritative snapshot per (season, crop) by
PUBLICATION METADATA, sums the published PROGRESSIVE EXPORT total, and computes the leakage-free
trailing metrics (pct_of_prior_yr, z_vs_3yr_avg). Publishes shadow-first (``--publish-mode``
default dry-run).

WHY RAW, AND WHY THIS IS A CORRECTNESS FIX AND NOT ONLY A FRESHNESS ONE (census B9/P9, 2026-09-22)
---------------------------------------------------------------------------------------------------
Until this change ``load_rows`` read ``bronze/production/source=sagis_weekly/dataset=
imp_exp_progressive/``, a prefix **NO PHASE IN THE REPOSITORY PRODUCES**. ``configs/silver/dags/
sagis_weekly.json`` carries phases ``fetch`` + ``silver`` and no ``bronze`` phase at all, while its
own ``chain_shape`` string claimed ``fetch->bronze(shared parser)->silver x3``; there is no
``raw_to_bronze`` module for this dataset either. Those 24 bronze objects were written once by a
tool that is not in git and last changed 2026-06-03. The weekly Friday fire therefore re-derived
the SAME dead bronze every week, exited 0, passed parity 12/12 and wrote a canonical parquet whose
newest week ended **2024-04-26** -- 879 days stale on 2026-09-22 -- while RAW carried
``IMP-EXP_Progressive_Koring_2025-2026_50.xlsx``, fetched 2026-09-18. Write-green, data-dead.

MEASURED AGAINST THE PUBLISHED CANONICAL (all 70 raw workbooks parsed offline, 2026-09-22): of the
1,204 canonical rows this reader reproduces **884 EXACTLY** -- every row of 2003-04..2011-12 for
both crops, byte-identical -- and **320 DIFFER, because the canonical ones are wrong**:

  * 2016-17 and 2019-20 maize: the canonical value is the **WHITE sheet alone** (32/32 and 50/50
    rows equal to the white-only progressive total). South Africa's YELLOW maize exports were
    silently absent from a series called "South Africa maize export pace".
  * 2022-23 maize: the canonical value is the **NAMIBIA destination column** of the white sheet
    (week 50: canonical 3,969 = white-sheet NAMIBIA cell; the real progressive total is
    1,452,511 white + 1,983,289 yellow = 3,435,800). Wrong by ~865x, and a WEEKLY cell served as a
    SEASON-TO-DATE total.
  * 2012-13 maize: the canonical value is the **IMPORTS** progressive total (week 1: canonical
    2,848 = the white-maize imports column; exports were 4,224).
  * 2013-14, 2017-18, 2023-24 maize diverge on the same class.

So the stale half of this table was ALSO the corrupt half. A mis-mapped column is worse than a
stale one, which is why this reader is validated by reproducing the 884 rows that were right rather
than by trusting that a repoint is mechanical.

THE THREE WORKBOOK ERAS, ALL PRESENT IN THE LIVE RAW TREE
---------------------------------------------------------
  (A) one export-only sheet per flow -- ``RSA EXPORTS`` (wheat, 2013-14 onward) with a header row
      ``Week | <destinations...> | Week Total/Totaal | Progressive Total/Totaal``;
  (B) the SAME shape split by maize colour -- ``White RSA EXPORTS`` + ``YELLOW RSA EXPORTS``, which
      must be SUMMED to get the national total (this is the era the old bronze got wrong);
  (C) one combined sheet ``RSA Imp & Exp - RSA Inv & Uitv`` (both crops, 2003-04..2013-14) whose
      two-row header band carries Imports blocks and then Exports blocks, each block ending in its
      own ``Prog Total``; the RIGHTMOST export block is the crop TOTAL.
In eras (A) and (B) the 2013-2018 files label the progressive column ``Total/Totaal`` -- the SAME
string as the week total beside it -- so the column is taken as the rightmost labelled column of
the header band, which is the progressive total in every era measured.
"""
from __future__ import annotations

import argparse
import io
import logging
import re
import sys
from urllib.parse import unquote

import pandas as pd

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.silver.flat_producer import (
    add_standard_producer_args,
    authorize_for_contract,
    build_flat_publish,
)
from leviathan.silver.registry import load_registry
from leviathan.storage.paths import silver_sagis_weekly_key
from leviathan.transforms.bronze_to_silver.sagis_common import parse_season
from leviathan.transforms.bronze_to_silver.sagis_weekly_exports import (
    WeeklyExportRow,
    transform_weekly_exports,
)

logger = get_logger("sagis_weekly_exports_silver_task")

TABLE = "silver_sagis_weekly_exports"
# RAW, as the sagis_deliveries sibling reads it (sagis_deliveries_task.py:37). The old
# bronze/ prefix is NOT read any more: nothing in the repository writes it.
_RAW_PREFIX = "raw/production/source=sagis_weekly/dataset=imp_exp_progressive/"
_CROP_RE = re.compile(r"/crop=([^/]+)/")
_WORKBOOK_SUFFIXES = (".xls", ".xlsx")


def _canon(value) -> str:
    """A header cell as a comparable token: lowercase, alphanumerics, single spaces."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return re.sub(r"[^a-z0-9]+", " ", str(value).lower()).strip()


def _is_export_sheet(name: str) -> bool:
    """True for an EXPORT-only sheet (era A/B).

    The exclusions are load-bearing, not tidiness: ``EXPORTS OF IMPORTED WHEAT`` and
    ``WHITE EXPORTS OF IMPORTED MAIZE`` are re-export sheets that would double-count, and
    ``White EXPORT PER HARBOUR`` is the same tonnage split by port."""
    n = _canon(name)
    if "import" in n or "harbour" in n or "per country" in n or "per land" in n:
        return False
    return "export" in n or "uitvoer" in n


def _is_combined_sheet(name: str) -> bool:
    """True for the era-C combined imports+exports sheet (``RSA Imp & Exp - RSA Inv & Uitv``)."""
    n = _canon(name)
    return ("rsa" in n and "imp" in n and "exp" in n) or ("rsa" in n and "inv" in n and "uitv" in n)


def _week_column(df: pd.DataFrame) -> int | None:
    """The column holding the week numbers: the leftmost one carrying 1, 2, 3, ... ascending.

    Anchored on the ascending run from 1 rather than on a header word because the header is
    bilingual, merged and sometimes blank; a destination column of tonnages does not open 1,2,3,...
    and climb by one. The floor is TWO weeks, not ten: the first snapshot of a new season carries
    only the weeks published so far (``IMP-EXP_Progressive_Mielies_2026-2027_2.xlsx`` holds two),
    and a ten-week floor would make every season invisible for its first nine weeks -- which is
    exactly the window a weekly export-pace table exists to answer."""
    for col in range(min(4, df.shape[1])):
        values = pd.to_numeric(df.iloc[:, col], errors="coerce").dropna()
        weeks = [int(v) for v in values if float(v).is_integer() and 1 <= v <= 53]
        head = weeks[:3]
        if len(weeks) >= 2 and head == list(range(1, len(head) + 1)):
            return col
    return None


def _first_data_row(df: pd.DataFrame, week_col: int) -> int:
    """The row where week 1 sits -- i.e. the first row under the header band."""
    col = pd.to_numeric(df.iloc[:, week_col], errors="coerce")
    hits = col[col == 1]
    return int(hits.index[0]) if len(hits) else 0


def _label_column(df: pd.DataFrame, week_col: int, first_row: int) -> int | None:
    """The free-text ``week_ending`` column: the next mostly-text column right of the week column.

    The floor is a SHARE of the rows scanned, never a fixed count. A fixed floor of five text cells
    silently returns None on the first snapshot of a new season -- which carries two or three week
    rows -- and a null ``week_ending`` there costs the whole season its ``week_ending_date``, the
    card's only point-in-time anchor. A destination column of tonnages has zero text cells, so the
    share test separates them just as well on two rows as on fifty."""
    for col in range(week_col + 1, min(week_col + 3, df.shape[1])):
        cells = [v for v in df.iloc[first_row:first_row + 20, col]]
        if not cells:
            continue
        text = sum(1 for v in cells if isinstance(v, str) and v.strip())
        if text >= max(1, (len(cells) + 1) // 2):
            return col
    return None


def _prog_column_export_sheet(df: pd.DataFrame, first_row: int) -> int | None:
    """Era A/B: the PROGRESSIVE export total column of an export-only sheet."""
    for row in range(first_row):
        for col in range(df.shape[1] - 1, -1, -1):
            if _canon(df.iat[row, col]).startswith("progressive total"):
                return col
    # 2013-2018: the header prints 'Total/Totaal' TWICE -- week total, then progressive total --
    # so the name cannot discriminate. The RIGHTMOST labelled column of the header band is the
    # progressive total in every era measured (24 season-crops, 2003-04..2026-27).
    for row in range(first_row - 1, -1, -1):
        labelled = [c for c in range(df.shape[1]) if _canon(df.iat[row, c])]
        if len(labelled) >= 4 and any(_canon(df.iat[row, c]) == "week" for c in labelled):
            return labelled[-1]
    return None


def _prog_column_combined_sheet(df: pd.DataFrame, first_row: int) -> int | None:
    """Era C: the RIGHTMOST ``Prog Total`` that belongs to an EXPORT block.

    The header band prints a flow word (``Imports /`` / ``Exports /``, or the Afrikaans
    ``Invoere`` / ``Uitvoere``) at the head of each block and a ``Prog Total /`` at its end, so a
    Prog-Total column is an export column when the nearest flow word to its LEFT on the same row
    says exports. The rightmost such block is the crop TOTAL (white + yellow for maize), which is
    exactly the 14,199 MT that canonical 2003-04 maize week 1 carries."""
    best: int | None = None
    for row in range(first_row):
        cells = [_canon(df.iat[row, col]) for col in range(df.shape[1])]
        if not any(c.startswith("prog") and "total" in c for c in cells):
            continue
        flow = ""
        for col, cell in enumerate(cells):
            if cell.startswith("export") or cell.startswith("uitvoer"):
                flow = "exports"
            elif cell.startswith("import") or cell.startswith("invoer"):
                flow = "imports"
            if cell.startswith("prog") and "total" in cell and flow == "exports":
                best = col
    return best


def read_workbook_exports(workbook: bytes, filename: str) -> list[dict]:
    """One raw SAGIS workbook -> ``[{week_number, week_ending, prog_exports_mt}]``.

    Colour-split maize sheets (era B) are SUMMED per week, which is the whole national total and
    the half the dead bronze dropped. A week whose progressive cell is empty is skipped rather
    than zero-filled, and the footer ``Total`` row has no week number so it never enters."""
    xl = pd.ExcelFile(io.BytesIO(workbook))
    export_sheets = [s for s in xl.sheet_names if _is_export_sheet(s)]
    if export_sheets:
        sheets, picker = export_sheets, _prog_column_export_sheet
    else:
        combined = [s for s in xl.sheet_names if _is_combined_sheet(s)]
        if not combined:
            logger.error("sagis exports: %s has no export sheet (sheets=%s) -- skipped",
                         filename, xl.sheet_names)
            return []
        sheets, picker = combined[:1], _prog_column_combined_sheet

    merged: dict[int, dict] = {}
    for sheet in sheets:
        df = xl.parse(sheet, header=None)
        week_col = _week_column(df)
        if week_col is None:
            logger.error("sagis exports: %s sheet %r has no week column -- skipped",
                         filename, sheet)
            continue
        first_row = _first_data_row(df, week_col)
        prog_col = picker(df, first_row)
        if prog_col is None:
            logger.error("sagis exports: %s sheet %r has no progressive-total column -- skipped",
                         filename, sheet)
            continue
        label_col = _label_column(df, week_col, first_row)
        weeks = pd.to_numeric(df.iloc[:, week_col], errors="coerce")
        values = pd.to_numeric(df.iloc[:, prog_col], errors="coerce")
        for i in range(first_row, df.shape[0]):
            week = weeks.iat[i]
            if pd.isna(week) or not float(week).is_integer() or not 1 <= week <= 53:
                continue
            value = values.iat[i]
            if pd.isna(value):
                continue
            label = df.iat[i, label_col] if label_col is not None else None
            label = None if (label is None or (isinstance(label, float) and pd.isna(label))) \
                else str(label).strip() or None
            rec = merged.setdefault(int(week), {"week_number": int(week), "week_ending": label,
                                                "prog_exports_mt": 0.0})
            rec["prog_exports_mt"] += float(value)
            if rec["week_ending"] is None:
                rec["week_ending"] = label
    return [merged[w] for w in sorted(merged)]


def load_rows(bucket: str, aws_region: str, s3=None) -> list[WeeklyExportRow]:
    """Every authoritative raw workbook's export rows, one snapshot per (season, crop).

    THE SELECTION KEY IS (season, crop) AND IT IS DONE HERE, deliberately. SAGIS re-uploads one
    cumulative file per season per crop under a new filename each week, so overlapping snapshots
    report the same (season, crop, week) many times. The ranking is the deliveries sibling's:
    widest week coverage first (read from the DATA, because several older filenames carry no week
    token at all), then the S3 ``LastModified`` publication timestamp, then the key -- never
    filename lexical order.

    It is NOT left to ``sagis_weekly_exports.select_authoritative_snapshot``, and that is a
    measurement rather than a preference: that selector keys its winner on ``season`` ALONE, so
    with real per-file identities the wheat and maize snapshots of the same season label compete
    and ONE CROP'S ROWS ARE DROPPED ENTIRELY. It never bit before only because the governed bronze
    schema carried no snapshot columns at all, so every row reached it with ``snapshot_id=''`` and
    the selector was a no-op over a single identity. This producer therefore hands it the same
    single identity it has always seen -- keeping that stage byte-identical across the repoint --
    and does the real selection here, where the S3 publication metadata actually exists. The
    season-keyed selector is docketed for repair in its own change."""
    from leviathan.storage.s3 import get_thread_local_s3_client, list_s3_keys_with_mtime

    s3 = s3 or get_thread_local_s3_client(aws_region)
    key_to_mtime = list_s3_keys_with_mtime(bucket, _RAW_PREFIX, aws_region=aws_region)

    candidates: dict[tuple, tuple] = {}          # (season, crop) -> (rank, key, rows)
    unkeyed = 0
    for key, mtime in sorted(key_to_mtime.items()):
        if not key.lower().endswith(_WORKBOOK_SUFFIXES):
            continue
        crop_match = _CROP_RE.search(key)
        filename = unquote(key.rsplit("/", 1)[-1])
        season = parse_season(filename)
        if crop_match is None or season is None:
            unkeyed += 1
            logger.error("sagis exports: cannot key %s (crop=%s season=%s) -- skipped",
                         key, crop_match and crop_match.group(1), season)
            continue
        crop = crop_match.group(1)
        try:
            body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
            rows = read_workbook_exports(body, filename)
        except Exception as exc:  # noqa: BLE001 -- one unreadable snapshot must not lose the season
            logger.error("sagis exports: read failed key=%s: %s", key, exc)
            continue
        if not rows:
            continue
        rank = (max(r["week_number"] for r in rows),
                mtime.isoformat() if mtime is not None else "", key)
        current = candidates.get((season, crop))
        if current is None or rank > current[0]:
            candidates[(season, crop)] = (rank, key, rows)

    out: list[WeeklyExportRow] = []
    for (season, crop), (rank, key, rows) in sorted(candidates.items()):
        for r in rows:
            out.append(WeeklyExportRow(
                season=season,
                crop=crop,
                week_number=int(r["week_number"]),
                prog_exports_mt=float(r["prog_exports_mt"]),
                week_ending=r["week_ending"],
                is_total=True,           # the PUBLISHED progressive total, never a grade row
            ))
    logger.info("sagis exports: %d rows from %d authoritative snapshots (%d raw objects listed, "
                "%d unkeyable); seasons %s",
                len(out), len(candidates), len(key_to_mtime), unkeyed,
                sorted({s for s, _ in candidates}))
    return out


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SAGIS weekly exports bronze -> silver")
    add_standard_producer_args(parser)
    return parser.parse_args()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s",
                        stream=sys.stderr)
    load_env()
    args = _parse_args()
    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    aws_region = get_required_env("AWS_REGION")

    contract = load_registry().table(TABLE)
    df = transform_weekly_exports(load_rows(bucket, aws_region))
    logger.info("silver rows: %d", len(df))
    if df.empty:
        logger.error("empty silver output; aborting")
        return 1

    auth = authorize_for_contract(contract, publish_mode=args.publish_mode)
    from leviathan.storage.s3 import get_thread_local_s3_client
    publish_s3 = None if args.publish_mode == "dry-run" else get_thread_local_s3_client(aws_region)
    plan = build_flat_publish(
        df=df, contract=contract, canonical_key=silver_sagis_weekly_key("exports"),
        auth=auth, s3_client=publish_s3, job="sagis_weekly_exports_silver", run_id=args.run_id,
    )
    manifest = plan.run()
    logger.info("publish %s state=%s mode=%s rows=%d", TABLE, manifest.state.value,
                args.publish_mode, len(df))
    return 0


if __name__ == "__main__":
    sys.exit(main())
