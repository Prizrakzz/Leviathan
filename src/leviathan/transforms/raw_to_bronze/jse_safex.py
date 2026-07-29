"""PRICE_AND_PLAYBOOKS W1a -- the JSE/SAFEX ``NEW DAYAGR.xls`` raw -> bronze transform.

WHAT THIS MODULE OWNS
---------------------
The venue-specific half of ``silver_futures_eod``'s JSE leg, and nothing else:

  * :data:`JSE_SECTION_MAP` -- the TWO contract sections this leg keeps out of the 31 the sheet
    carries, matched by EXACT string equality. No unit / currency / settle_kind / source lives
    here: that authority is :mod:`leviathan.silver.futures_eod_contracts`, and an import-time
    assertion binds this map to the ``source == "jse_safex"`` rows of ``CONTRACT_MAP`` both ways;
  * the legacy-OLE read, the two-row header resolve, and the section/expiry row discrimination;
  * the ``Aug-2026 -> '2026-08'`` delivery-month decode;
  * the ``0 == no trade`` price sentinel.

Pure: pandas + xlrd + the house logger. No boto3, no S3, no network.

THE DEFECT THIS MODULE EXISTS TO NOT COMMIT
-------------------------------------------
**The section discriminator is an EXACT match and never a substring.** The sheet carries 31 contract
sections and FOUR of them contain the substring "MAIZE"::

    WHITE MAIZE FUTURE            9 expiries   <- KEEP  (south_african_white_maize_jse)
    WHITE MAIZE GRADE 2 FUTURE    2 expiries   <- REJECT (a different deliverable contract)
    YELLOW MAIZE FUTURE           9 expiries   <- KEEP  (south_african_yellow_maize_jse)
    YELLOW MAIZE GRADE 2 FUTURE   2 expiries   <- REJECT

Grade 2 has its OWN mark-to-market (Sep-2026 white grade-2 MTM 3098 against grade-1 3527), so a
``"WHITE MAIZE" in row`` test does not fail -- it silently MERGES two deliverable contracts into one
slug and lands a plausible wrong number. It also changes the row count from 18/day to 22/day, and
the plan's original floor of 20 sat BETWEEN those two numbers, so an implementer chasing a red gate
would have been pushed straight INTO the bug. That is why the armed floor is >= 14 and why it is a
count of silver rows rather than anything else.

The sheet additionally carries US-referenced and QUANTO sections (``CORN CONTRACT``,
``SOYA BEANS FUTURE``, ``SOFT RED WHEAT FUTURES``, ``COFFEE QUANTO``, ...) and a cash/parity block
(``MAIZE US NO 2 YELLOW ... GULF ... CBOT``) whose columns mean something else entirely. A loose
parse eats all of it.

HOW "FAIL ON AN UNRECOGNISED SECTION" IS IMPLEMENTED, AND WHY IT IS SCOPED
--------------------------------------------------------------------------
The plan asks the parser to fail on an unrecognised section header. Applied literally to all 31
sections that would mean curating 31 upstream strings we do not control, and a single upstream
rename anywhere in the sheet -- in a section this leg does not even read -- would take the whole
leg down. So the fail-closed rule is scoped to the DEFECT CLASS, precisely:

  * a section whose text begins with ``WHITE MAIZE`` or ``YELLOW MAIZE`` must be either one of the
    two kept sections or one of the two curated GRADE 2 rejects. Anything else is a HARD ERROR --
    that is exactly the grade / variant proliferation this rule exists for;
  * every other section is skipped and COUNTED (the stats dict carries the full observed section
    list, so drift is measured rather than assumed);
  * and BOTH kept sections must have been seen, or the parse is a HARD ERROR. That is the rename
    detector: an upstream ``WHITE MAIZE FUTURE -> WHITE MAIZE FUTURES`` cannot silently yield an
    empty leg.

The per-day row floor (gate 5, >= 14) is the third backstop underneath both.

TWO MORE THINGS THE SHEET DOES
------------------------------
1. **There is no open and no close.** The published columns are
   ``Cloisng Bid | Closing Offer | MTM | VWAP | High | Low`` -- note the upstream typo ``Cloisng``,
   which is real, reproduces exactly, and must NOT be "corrected" anywhere. So ``open`` and
   ``close`` are NULL BY SOURCE on both JSE slugs -- not by a settle-only convention -- and the
   bid/offer pair is deliberately discarded (it is a quote, not a traded or marked level).
2. **``0`` means "no trade" and must map to NULL, never zero.** Zero ZAR/t is not a price. The mask
   is applied to every PRICE column and never to ``volume`` / ``open_interest``, which are true
   counts whose zero is meaningful.
"""
from __future__ import annotations

import re
from typing import Optional

import pandas as pd

from leviathan.common.logging import get_logger
from leviathan.silver import futures_eod_contracts as FC

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------
# EXACT strings. Not prefixes, not substrings, not case-folded contains.
JSE_SECTION_MAP: dict[str, str] = {
    "WHITE MAIZE FUTURE": "south_african_white_maize_jse",
    "YELLOW MAIZE FUTURE": "south_african_yellow_maize_jse",
}

# The two curated look-alikes. Named here so they are REJECTED deliberately and visibly, rather
# than falling through an else-branch that would also swallow a genuinely new grade.
JSE_REJECTED_SECTIONS: frozenset[str] = frozenset({
    "WHITE MAIZE GRADE 2 FUTURE",
    "YELLOW MAIZE GRADE 2 FUTURE",
})

# The scope of the fail-closed unrecognised-section rule (see the module docstring).
_GUARDED_SECTION_PREFIXES = ("WHITE MAIZE", "YELLOW MAIZE")

JSE_SOURCE = "jse_safex"

# The sheet name the portal publishes. Read positionally as sheet 0 if the name ever changes.
JSE_SHEET_NAME = "Sheet1"

# ---------------------------------------------------------------------------
# Columns
# ---------------------------------------------------------------------------
# The header is TWO rows and its wording carries an upstream typo, so the resolve is by ACCEPTED
# TOKEN SET per field rather than by one exact string -- and the typo is listed VERBATIM instead of
# being normalized away. Every field below is REQUIRED: an unresolved column is a hard error naming
# the tokens actually seen, because a JSE leg that silently drops open_interest degrades
# futures_roll's open_interest front-month rule into the nearest-month tie-break with no error and
# no gate (the -1.0 fill in front_month).
#
# The layout observed 2026-07-27 (11 columns) is, for the first live comparison:
#   0 expiry | 1 change | 2 closing bid | 3 closing offer | 4 MTM | 5 VWAP | 6 high | 7 low
#   8 volume | 9 open interest | 10 option volume
_FIELD_TOKENS: dict[str, tuple[str, ...]] = {
    # "cloisng" IS the upstream spelling. Both are accepted; neither is corrected in place.
    "bid": ("cloisng bid", "closing bid"),
    "offer": ("closing offer", "cloisng offer"),
    "mtm": ("mtm", "mark to market", "m t m"),
    "vwap": ("vwap",),
    "high": ("high", "day high"),
    "low": ("low", "day low"),
    "volume": ("volume", "vol", "futures volume", "fut vol"),
    "open_interest": ("oi", "open interest", "o i"),
    "option_volume": ("option volume", "opt vol", "optvol", "options volume"),
}
# Unresolved is fatal for these; the rest are carried when present and NULL when not.
_REQUIRED_FIELDS = ("mtm", "high", "low", "volume", "open_interest")

# The title line: "COMMODITY DERIVATIVES MARKET / DOMESTIC FUTURES PRICES 27-Jul-2026".
_HEADER_DATE_RE = re.compile(r"(\d{1,2})-([A-Za-z]{3})-(\d{4})")
# A data row's first cell: "Aug-2026" / "Mar-2028".
_EXPIRY_RE = re.compile(r"^([A-Za-z]{3})-(\d{4})$")
_MONTHS = {m: i for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), start=1)}

CONTRACT_MONTH_FMT = "%04d-%02d"

# How far into the sheet the two-row header may sit before we give up looking for it.
_HEADER_SEARCH_ROWS = 12

BRONZE_COLUMNS: list[str] = [
    "trade_date", "leviathan_slug", "section", "raw_symbol", "contract_month",
    "mtm", "vwap", "high", "low", "bid", "offer", "volume", "open_interest",
]


def _lint_section_map() -> list[str]:
    """JSE_SECTION_MAP must be EXACTLY the ``source == 'jse_safex'`` slugs of CONTRACT_MAP."""
    errs: list[str] = []
    mapped = set(JSE_SECTION_MAP.values())
    curated = {slug for slug, rec in FC.CONTRACT_MAP.items() if rec["source"] == JSE_SOURCE}
    for slug in sorted(mapped - curated):
        errs.append(f"{slug}: in JSE_SECTION_MAP but not a source={JSE_SOURCE!r} CONTRACT_MAP slug")
    for slug in sorted(curated - mapped):
        errs.append(f"{slug}: a source={JSE_SOURCE!r} CONTRACT_MAP slug with no JSE section")
    for section in sorted(JSE_SECTION_MAP):
        if not section.startswith(_GUARDED_SECTION_PREFIXES):
            errs.append(f"{section!r}: a kept section outside the guarded prefixes "
                        f"{_GUARDED_SECTION_PREFIXES} -- the unrecognised-section rule would not "
                        f"cover its look-alikes")
    overlap = sorted(set(JSE_SECTION_MAP) & JSE_REJECTED_SECTIONS)
    if overlap:
        errs.append(f"section(s) {overlap} are both kept and rejected")
    return errs


assert not _lint_section_map(), \
    "jse_safex.JSE_SECTION_MAP is malformed: " + "; ".join(_lint_section_map())


def _norm(value) -> str:
    """A cell -> a single-spaced lowercase ASCII token string ('' for blank/numeric)."""
    if value is None:
        return ""
    text = str(value)
    text = re.sub(r"[^0-9A-Za-z]+", " ", text)
    return " ".join(text.split()).strip().lower()


def _section_text(value) -> str:
    """A cell -> the UPPERCASE single-spaced section label used for the exact match."""
    if value is None:
        return ""
    return " ".join(str(value).split()).strip().upper()


def read_grid(payload: bytes) -> list[list]:
    """The JSE sheet as a list-of-rows of raw cell values.

    Legacy OLE, so ``xlrd`` (2.x still reads .xls; it dropped only .xlsx). Opened with
    ``ignore_workbook_corruption=True``: the CEPEA archive workbooks in this same wave are
    LibreOffice-generated and raise ``CompDocError: Workbook corruption: seen[2] == 4`` without it,
    and the flag costs nothing on a well-formed book."""
    import xlrd  # lazy: the vendor import is a [batch] extra, and the module must import without it

    book = xlrd.open_workbook(file_contents=payload, ignore_workbook_corruption=True,
                              formatting_info=False)
    try:
        sheet = book.sheet_by_name(JSE_SHEET_NAME)
    except Exception:  # noqa: BLE001 -- an upstream sheet rename must not take the leg down
        sheet = book.sheet_by_index(0)
        logger.warning("jse: sheet %r absent; falling back to sheet 0 (%r)",
                       JSE_SHEET_NAME, sheet.name)
    return [[sheet.cell_value(r, c) for c in range(sheet.ncols)] for r in range(sheet.nrows)]


def header_trade_date(grid: list[list]) -> Optional[str]:
    """The ``YYYY-MM-DD`` in the sheet's own title line, or None.

    This is the ONLY trade-date authority for this leg. It is NOT the raw key's ``as_of_date=``
    segment: the portal object is overwritten daily and is T-1 at fetch time, so the two are
    different facts and the plan's post-ship verification asserts header-date == trade_date on
    every row -- which is only a real check because they are independently sourced."""
    for row in grid[:_HEADER_SEARCH_ROWS]:
        for cell in row:
            if not isinstance(cell, str):
                continue
            m = _HEADER_DATE_RE.search(cell)
            if m:
                month = _MONTHS.get(m.group(2).lower())
                if month:
                    return f"{int(m.group(3)):04d}-{month:02d}-{int(m.group(1)):02d}"
    return None


def resolve_columns(grid: list[list]) -> tuple[int, dict[str, int]]:
    """``(first_data_row, {field: column_index})`` from the TWO-row header.

    The two header rows are concatenated PER COLUMN before matching, because the wording splits
    across them ("Closing" above "Bid"). Matching is against a curated token set per field -- which
    is how the upstream ``Cloisng`` typo is honoured verbatim rather than silently repaired."""
    best: tuple[int, dict[str, int]] | None = None
    limit = min(len(grid), _HEADER_SEARCH_ROWS)
    for r in range(limit):
        width = max((len(grid[i]) for i in (r, r + 1) if i < len(grid)), default=0)
        merged: list[str] = []
        for c in range(width):
            parts = [_norm(grid[i][c]) for i in (r, r + 1)
                     if i < len(grid) and c < len(grid[i])]
            merged.append(" ".join(p for p in parts if p).strip())
        found: dict[str, int] = {}
        for field, tokens in _FIELD_TOKENS.items():
            for c, text in enumerate(merged):
                if text in tokens:
                    found[field] = c
                    break
        if "mtm" in found and (best is None or len(found) > len(best[1])):
            best = (r + 2, found)
        if best is not None and len(best[1]) == len(_FIELD_TOKENS):
            break
    if best is None:
        raise ValueError(
            "jse: no MTM column found in the first "
            f"{_HEADER_SEARCH_ROWS} rows -- the sheet layout changed and the parse cannot be "
            "trusted; refusing to guess positionally"
        )
    first_data_row, cols = best
    missing = [f for f in _REQUIRED_FIELDS if f not in cols]
    if missing:
        seen = sorted({_norm(c) for row in grid[:_HEADER_SEARCH_ROWS] for c in row if _norm(c)})
        raise ValueError(
            f"jse: required column(s) {missing} did not resolve from the two-row header. Header "
            f"tokens actually seen: {seen}. Add the upstream spelling to _FIELD_TOKENS -- do NOT "
            f"fall back to a positional guess, and do NOT drop open_interest (futures_roll's "
            f"open_interest rule degrades SILENTLY into the nearest-month tie-break without it)"
        )
    return first_data_row, cols


def contract_month_str(expiry: str) -> str:
    """``'Aug-2026' -> '2026-08'``. Fail-closed on anything else."""
    m = _EXPIRY_RE.match(str(expiry).strip())
    if not m:
        raise ValueError(f"jse: {expiry!r} is not a MMM-YYYY delivery month")
    month = _MONTHS.get(m.group(1).lower())
    if month is None:
        raise ValueError(f"jse: {expiry!r} carries an unknown month name")
    return CONTRACT_MONTH_FMT % (int(m.group(2)), month)


def _cell_number(value) -> float:
    """A price/count cell -> float; blank, '-' and non-numeric text -> NaN."""
    if value is None or isinstance(value, bool):
        return float("nan")
    if isinstance(value, (int, float)):
        return float(value)
    tok = str(value).strip().replace(",", "").replace(" ", "")
    if not tok or tok in {"-", "--", "n/a", "N/A"}:
        return float("nan")
    try:
        return float(tok)
    except ValueError:
        return float("nan")


def _expiry_text(value) -> str:
    """The first cell of a row -> its ``MMM-YYYY`` text, or '' when it is not an expiry."""
    if isinstance(value, str):
        return value.strip() if _EXPIRY_RE.match(value.strip()) else ""
    return ""


def build_jse_bronze(payload: bytes, *, as_of_date: Optional[str] = None
                     ) -> tuple[pd.DataFrame, dict]:
    """One raw ``NEW DAYAGR.xls`` -> the bronze rows for the TWO kept sections + a stats dict.

    ``as_of_date`` is the FETCH date from the raw key. It is carried into the stats for audit and
    is NEVER used as ``trade_date``: the sheet's own header date is the session, and the file is
    T-1 at fetch time."""
    return build_jse_bronze_from_grid(read_grid(payload), as_of_date=as_of_date)


def build_jse_bronze_from_grid(grid: list[list], *, as_of_date: Optional[str] = None
                               ) -> tuple[pd.DataFrame, dict]:
    """The parse proper, over an already-read cell grid.

    Split from :func:`build_jse_bronze` at the OLE boundary on purpose: everything interesting on
    this leg is grid logic (the exact section match, the two-row header resolve, the no-trade
    sentinel), and separating it means the tests exercise all of it hermetically without needing a
    legacy .xls WRITER -- which no library in this estate has."""
    session = header_trade_date(grid)
    if session is None:
        raise ValueError(
            "jse: the sheet carries no 'DD-Mon-YYYY' header date -- the trade date has no other "
            "authority on this leg (the raw key's as_of_date is the FETCH day, not the session) "
            "and inventing one would misdate a whole partition"
        )
    first_data_row, cols = resolve_columns(grid)

    rows: list[dict] = []
    sections_seen: list[str] = []
    kept_sections: set[str] = set()
    rejected_rows = 0
    zero_price_cells = 0
    current: Optional[str] = None
    current_section = ""
    for row in grid[first_data_row:]:
        if not row:
            continue
        head = row[0]
        expiry = _expiry_text(head)
        if not expiry:
            label = _section_text(head)
            if not label:
                continue                       # a spacer row inside or between sections
            sections_seen.append(label)
            if label in JSE_SECTION_MAP:
                current, current_section = JSE_SECTION_MAP[label], label
                kept_sections.add(label)
            elif label in JSE_REJECTED_SECTIONS:
                current, current_section = None, label
            elif label.startswith(_GUARDED_SECTION_PREFIXES):
                raise ValueError(
                    f"jse: unrecognised maize section {label!r}. The two KEPT sections are "
                    f"{sorted(JSE_SECTION_MAP)} and the two curated rejects are "
                    f"{sorted(JSE_REJECTED_SECTIONS)}. A new grade or a rename must be an explicit "
                    f"decision -- a substring match here is what silently MERGES two deliverable "
                    f"contracts into one slug and lands a plausible wrong number"
                )
            else:
                current, current_section = None, label
            continue
        if current is None:
            rejected_rows += 1
            continue
        vals: dict[str, float] = {}
        for field in ("mtm", "vwap", "high", "low", "bid", "offer", "volume", "open_interest"):
            col = cols.get(field)
            vals[field] = _cell_number(row[col]) if col is not None and col < len(row) \
                else float("nan")
        # The no-trade sentinel: 0 is not a ZAR/t price. Counts are left alone -- a zero volume or
        # a zero open interest is a true observation.
        for field in ("mtm", "vwap", "high", "low", "bid", "offer"):
            if vals[field] == 0.0:
                zero_price_cells += 1
                vals[field] = float("nan")
        rows.append({
            "trade_date": session,
            "leviathan_slug": current,
            "section": current_section,
            "raw_symbol": expiry,             # VERBATIM. Never parsed into meaning at ingest.
            "contract_month": contract_month_str(expiry),
            **vals,
        })

    absent = sorted(set(JSE_SECTION_MAP) - kept_sections)
    if absent:
        raise ValueError(
            f"jse: kept section(s) {absent} are ABSENT from the sheet (sections seen: "
            f"{sorted(set(sections_seen))}). Either the portal renamed them or it served a "
            f"different file; an empty leg must be a hard error, not a quiet short day"
        )

    df = pd.DataFrame(rows, columns=BRONZE_COLUMNS)
    if len(df):
        df["trade_date"] = pd.to_datetime(df["trade_date"]).astype("datetime64[us]")
        for col in ("volume", "open_interest"):
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
    stats = {
        "trade_date": session,
        "as_of_date": as_of_date,
        "grid_rows": len(grid),
        "header_row": first_data_row - 2,
        "columns": {k: int(v) for k, v in sorted(cols.items())},
        "sections_seen": sorted(set(sections_seen)),
        "sections_kept": sorted(kept_sections),
        "rows_kept": int(len(df)),
        "rows_rejected": rejected_rows,
        "zero_price_cells": zero_price_cells,
    }
    logger.info("jse bronze %s: %d row(s) from %d section(s) of %d, zero-price cells %d",
                session, len(df), len(kept_sections), len(set(sections_seen)), zero_price_cells)
    return df, stats
