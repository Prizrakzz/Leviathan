"""Bronze producer for USDA NASS Florida Citrus *monthly production forecast* PDFs.

SILVER-F056 completion (stale-producer restore). ``fetch_usda_nass_citrus.py`` writes the citrus
forecast PDFs to raw, and :mod:`leviathan.transforms.bronze_to_silver.nass_citrus` reduces the long
bronze to silver -- but the raw->bronze step that produced the long bronze was *untracked*, so new
releases never reached bronze and silver froze at the 2024-25 season. This module is that missing,
tracked producer.

It parses the page-1 ``Citrus Production by Type - States and United States`` table of a monthly
forecast PDF (``cit{MM}{YY}.pdf``) into the long bronze schema the silver transform consumes::

    release_date  season  report_month  crop  state  col_label  col_type  value_1000_boxes  source

The four value columns of the table are classified by their header token:

  * the RIGHTMOST column is always the ``current_forecast`` (this report's new forecast);
  * a remaining **month-name** header (e.g. "December", "October") is a ``prior_forecast``;
  * a remaining **year-pair** header (e.g. "2023-2024") is an ``actual``.

The first forecast of a season (October) carries three year-pair actuals + the season-labelled
current forecast and NO prior; December's prior is October (November has no forecast round).

Faithful-replication note
-------------------------
The value/label mapping and the crop/state universe were reverse-engineered and validated
**value-for-value** against the physical bronze corpus written by the untracked step
(2024-25 October/December/January reports reproduce exactly: 89/90/90 rows). Two behaviours of the
original are reproduced ON PURPOSE so newly-produced bronze stays consistent with the frozen corpus
and its silver census baseline:

  * ``Lemons`` is not a recognised crop header, so lemon rows inherit the last recognised crop
    (``grapefruit``); in silver they collapse under the (crop, state) natural key (only the spurious
    ``grapefruit / arizona`` survives). Re-labelling lemons is a *taxonomy* decision, out of scope
    for this stale-producer restore.
  * grapefruit ``Red`` / ``White`` sub-rows are dropped (only ``Florida-All`` is kept), matching the
    original state whitelist.
"""
from __future__ import annotations

import datetime as _dt
import io
import re

import pandas as pd

from leviathan.common.logging import get_logger

logger = get_logger(__name__)

SOURCE = "usda_nass_citrus"

BRONZE_COLUMNS: list[str] = [
    "release_date",
    "season",
    "report_month",
    "crop",
    "state",
    "col_label",
    "col_type",
    "value_1000_boxes",
    "source",
]

# Recognised crop-section headers -> leviathan crop slug. A header NOT in this map (e.g. "Lemons")
# does not change the active crop -- see the faithful-replication note above.
_CROP_MAP: dict[str, str] = {
    "non-valencia oranges": "non_valencia_orange",
    "valencia oranges": "valencia_orange",
    "all oranges": "all_orange",
    "grapefruit": "grapefruit",
    "tangerines and mandarins": "tangerine_mandarin",
}

# Recognised state labels (after footnote-superscript stripping) -> state slug. Grapefruit
# ``Red``/``White`` sub-rows are absent here and are therefore dropped.
_STATE_MAP: dict[str, str] = {
    "florida": "florida",
    "florida-all": "florida",
    "california": "california",
    "texas": "texas",
    "arizona": "arizona",
    "united states": "united_states",
}

_MONTHS: dict[str, int] = {
    m.lower(): i
    for i, m in enumerate(
        ["January", "February", "March", "April", "May", "June", "July",
         "August", "September", "October", "November", "December"], start=1)
}

_DOTS = re.compile(r"\.{2,}")                 # the dotted leader between a row label and its values
_FOOTNOTE_SUP = re.compile(r"(?:\s*\d+)+$")   # trailing footnote(s): "California 3 4", "Florida5"
_FULLDATE = re.compile(r"^([A-Z][a-z]+) (\d{1,2}), (\d{4})$")
_UNITS_PREFIX = "(1,000 boxes)"


# ---------------------------------------------------------------------------
# Season derivation (fetch-time scoping; the CURRENT open forecast season)
# ---------------------------------------------------------------------------
def _coerce_date(as_of: "str | _dt.date | _dt.datetime | None") -> _dt.date:
    if as_of is None:
        return _dt.date.today()
    if isinstance(as_of, _dt.datetime):
        return as_of.date()
    if isinstance(as_of, _dt.date):
        return as_of
    s = str(as_of).strip().replace("Z", "").replace("z", "")
    # tolerate a bare date, a full ISO timestamp, or a trailing offset
    try:
        return _dt.datetime.fromisoformat(s).date()
    except ValueError:
        return _dt.date.fromisoformat(s[:10])


def current_forecast_season(as_of: "str | _dt.date | _dt.datetime | None" = None) -> str:
    """Return the CURRENT open Florida-citrus forecast season (``YYYY-YY``) for ``as_of``.

    The forecast season runs October -> July. October..December belong to the season that starts
    that calendar year; January..July belong to the season that started the previous year. During
    the August-September closed period (no forecast round) the derivation **falls forward** to the
    upcoming season that starts the coming October -- so a fetch scoped to "the current season" in
    the off-season targets the season about to open, never the one that just closed.

    Examples: Oct 2025 -> ``2025-26``; Jan 2026 -> ``2025-26``; Jul 2026 -> ``2025-26``;
    Aug/Sep 2026 -> ``2026-27`` (fall-forward).
    """
    d = _coerce_date(as_of)
    if d.month >= 10:        # Oct-Dec: season opened this calendar year
        start = d.year
    elif d.month <= 7:       # Jan-Jul: season opened the previous calendar year
        start = d.year - 1
    else:                    # Aug-Sep: closed -> fall forward to the season opening this October
        start = d.year
    return f"{start}-{(start + 1) % 100:02d}"


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------
def _report_month_from_filename(filename: str) -> int:
    """``cit0125.pdf`` -> 1, ``cit1024.pdf`` -> 10 (the ``cit{MM}{YY}.pdf`` convention)."""
    m = re.search(r"cit(\d{2})(\d{2})", filename)
    if not m:
        raise ValueError(f"cannot derive report_month from citrus filename {filename!r}")
    return int(m.group(1))


def _release_date(lines: list[str]) -> str:
    """First standalone ``Month DD, YYYY`` line -> ``YYYY-MM-DD`` (empty if none)."""
    for ln in lines:
        m = _FULLDATE.match(ln.strip())
        if m and m.group(1).lower() in _MONTHS:
            mo = _MONTHS[m.group(1).lower()]
            return f"{int(m.group(3)):04d}-{mo:02d}-{int(m.group(2)):02d}"
    return ""


def _classify_columns(labels: list[str]) -> list[str]:
    """Header tokens -> col_type per column: rightmost=current_forecast; month-name=prior_forecast;
    year-pair (or anything else) = actual."""
    out: list[str] = []
    last = len(labels) - 1
    for i, lab in enumerate(labels):
        if i == last:
            out.append("current_forecast")
        elif lab.lower() in _MONTHS:
            out.append("prior_forecast")
        else:
            out.append("actual")
    return out


def _strip_footnote(label: str) -> str:
    return _FOOTNOTE_SUP.sub("", label.strip()).strip()


def parse_forecast_table_text(text: str, season: str, filename: str) -> pd.DataFrame:
    """Parse the extracted page text of ONE monthly forecast PDF into long bronze rows.

    Pure (no I/O) so it is unit-testable with a synthetic table fixture. ``text`` is the
    ``pdfplumber`` first-page ``extract_text()`` output; ``season`` is ``YYYY-YY``; ``filename`` is
    the ``cit{MM}{YY}.pdf`` raw filename (report_month source).
    """
    report_month = _report_month_from_filename(filename)
    lines = text.splitlines()
    release_date = _release_date(lines)

    # The 4 column headers are the non-empty line immediately above the "(1,000 boxes)" units line.
    try:
        units_idx = next(i for i, ln in enumerate(lines) if ln.strip().startswith(_UNITS_PREFIX))
    except StopIteration as exc:  # pragma: no cover - malformed page
        raise ValueError(f"citrus forecast page missing '{_UNITS_PREFIX}' units row ({filename})") from exc
    labels = lines[units_idx - 1].split()
    if len(labels) != 4:
        raise ValueError(f"citrus forecast header expected 4 columns, got {labels!r} ({filename})")
    col_types = _classify_columns(labels)

    rows: list[tuple] = []
    crop: str | None = None
    for ln in lines[units_idx + 1:]:
        s = ln.strip()
        if not s:
            continue
        base = _strip_footnote(s).lower()
        if base in _CROP_MAP:                 # crop-section header (Lemons NOT in map -> crop carries)
            crop = _CROP_MAP[base]
            continue
        parts = _DOTS.split(s)
        if len(parts) != 2 or crop is None:   # not a "<label> .... <values>" data row
            continue
        state = _STATE_MAP.get(_strip_footnote(parts[0]).lower())
        if state is None:                     # Red / White sub-rows and any non-state label -> drop
            continue
        vals = parts[1].split()
        if len(vals) != 4:
            continue
        for j, tok in enumerate(vals):
            if tok == "(NA)":                 # not-available cell -> that (col_type) row is omitted
                continue
            try:
                value = float(tok.replace(",", ""))
            except ValueError:
                continue
            rows.append((release_date, season, report_month, crop, state,
                         labels[j], col_types[j], value, SOURCE))

    df = pd.DataFrame(rows, columns=BRONZE_COLUMNS)
    df["report_month"] = df["report_month"].astype("int64")
    df["value_1000_boxes"] = df["value_1000_boxes"].astype("float64")
    logger.info("NASS citrus bronze parse: %s season=%s month=%d release=%s rows=%d",
                filename, season, report_month, release_date or "?", len(df))
    return df


def extract_nass_citrus_forecast_bronze(pdf_bytes: bytes, season: str, filename: str) -> pd.DataFrame:
    """Open a monthly forecast PDF and return its long bronze DataFrame (:data:`BRONZE_COLUMNS`)."""
    import pdfplumber

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        text = pdf.pages[0].extract_text() or ""
    df = parse_forecast_table_text(text, season, filename)
    if df.empty:
        raise ValueError(f"NASS citrus forecast produced zero bronze rows from {filename}")
    return df
