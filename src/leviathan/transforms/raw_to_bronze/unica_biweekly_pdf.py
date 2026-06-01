"""Bronze extraction for UNICA Center-South bi-weekly (quinzenal) PDF bulletins.

Parses production, ethanol, and sales data from the unicadata.com.br biweekly
bulletins and returns up to five long/tidy DataFrames, one per output table.

Supported document types
------------------------
biweekly_old_pt
    10–12 page Portuguese bulletins (2012/13 – ~2016/17).  History tables are
    2-row × 3-col blobs; summary table is a single 27-row table covering both
    accumulated and fortnightly periods.

biweekly_new_pt
    13–17 page Portuguese bulletins (~2017/18 onward).  History tables are
    4-row × 4-col with SP/CS/DE columns; separate accumulated and fortnightly
    tables on the Tabela 1 page.

biweekly_new_en
    11-page English-language bulletins.  Same layout as biweekly_new_pt.

season_final_pt
    26–32 page Portuguese season-final reports.  Extracts 8 sub-tables into
    a single EAV DataFrame (season_final_extras).

season_close_en_double
    Special 20-page double-issue bulletin (idm=32820684).  Split into two
    byte streams: a season closure section and a biweekly section, then each
    is transformed independently.

Skipped types
    season_estimate, skip_offtopic, unknown → transform_pdf returns
    {"_classification": <label>} with no DataFrame keys.

Output tables
-------------
fortnight_production : historical fortnight-by-fortnight accumulated values
summary_snapshot     : current-report snapshot (accumulated + fortnightly)
corn_ethanol         : corn-derived ethanol by fortnight
monthly_ethanol_sales: ethanol sales by month and market destination
season_final_extras  : EAV table for season-final supplementary sub-tables

No S3 or AWS dependencies — pure data transformation.
"""
from __future__ import annotations

import io
import re
from typing import Optional

import pandas as pd
import pdfplumber

from leviathan.common.logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Document type labels
# ---------------------------------------------------------------------------

SKIP_OFFTOPIC = "skip_offtopic"
SEASON_ESTIMATE = "season_estimate"
UNKNOWN = "unknown"

_DOC_TYPES = [
    "biweekly_old_pt",
    "biweekly_new_pt",
    "biweekly_new_en",
    "season_final_pt",
    "season_close_en_double",
    SEASON_ESTIMATE,
    SKIP_OFFTOPIC,
    UNKNOWN,
]

# ---------------------------------------------------------------------------
# Variable metadata (order matches Tabelas 3-7 page order)
# ---------------------------------------------------------------------------

_HISTORY_VARS = [
    ("cane_crushed",       "t"),
    ("sugar_produced",     "t"),
    ("ethanol_total",      "m3"),
    ("ethanol_anhydrous",  "m3"),
    ("ethanol_hydrous",    "m3"),
]

_SUMMARY_VAR_ROWS_NEW = {
    # row index (0-based, after header rows) in the 15-row accumulated table
    # -> (variable, unit)
    2:  ("cane_crushed",      "t"),
    3:  ("sugar_produced",    "t"),
    4:  ("ethanol_anhydrous", "m3"),
    5:  ("ethanol_hydrous",   "m3"),
    6:  ("ethanol_total",     "m3"),
    # rows 7-14 are ATR, mix%, etc. — not extracted here
}

_SUMMARY_VAR_ROWS_OLD = {
    # 27-row table; first section = accumulated (rows 2-12), second = fortnightly (rows 15-25)
    2:  ("cane_crushed",      "t"),
    3:  ("sugar_produced",    "t"),
    4:  ("ethanol_anhydrous", "m3"),
    5:  ("ethanol_hydrous",   "m3"),
    6:  ("ethanol_total",     "t"),
}

_MONTH_MAP = {
    "abr": 4, "mai": 5, "jun": 6, "jul": 7, "ago": 8, "set": 9,
    "out": 10, "nov": 11, "dez": 12, "jan": 1, "fev": 2, "mar": 3,
    "apr": 4, "may": 5,  "aug": 8, "sep": 9, "oct": 10, "dec": 12,
}

# Rotated-text artifacts that appear in pdfplumber cell content for the
# monthly sales table column labels (not month names).
_SALES_ARTIFACTS = frozenset({
    "la", "t", "o", "lonat", "lonatE", "latot", "E", "T",
    "a", "t\no\nt", "lo", "nat", "tot",
})


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------


def classify_pdf(pdf_bytes: bytes) -> str:
    """Classify a raw UNICA biweekly PDF into one of the known document types.

    Returns one of the strings in ``_DOC_TYPES``.  Uses page count combined
    with keywords found on the first page to disambiguate formats.

    Args:
        pdf_bytes: Raw bytes of the PDF file.
    """
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            n = len(pdf.pages)
            p1_text = (pdf.pages[0].extract_text() or "").lower()
    except Exception as exc:  # noqa: BLE001
        logger.warning("classify_pdf: failed to open PDF: %s", exc)
        return SKIP_OFFTOPIC

    if n <= 9:
        if "estimativa" in p1_text:
            return SEASON_ESTIMATE
        return SKIP_OFFTOPIC

    if n >= 35:
        return SKIP_OFFTOPIC

    if n == 20:
        if "harvest closure" in p1_text or "fechamento" in p1_text:
            return "season_close_en_double"
        return SKIP_OFFTOPIC

    if 18 <= n <= 19:
        return SKIP_OFFTOPIC

    if 26 <= n <= 33:
        if "relatório final" in p1_text or "relatorio final" in p1_text:
            return "season_final_pt"
        return SKIP_OFFTOPIC

    # 10–17 pages: biweekly family
    is_quinzenal = "acompanhamento quinzenal" in p1_text or (
        "quinzenal" in p1_text and "safra" in p1_text
    )
    is_english = "bi-weekly bulletin" in p1_text or "bi-weekly" in p1_text

    if is_english and 10 <= n <= 12:
        return "biweekly_new_en"

    if 10 <= n <= 12:
        if is_quinzenal:
            return "biweekly_old_pt"
        return SKIP_OFFTOPIC

    if 13 <= n <= 17:
        if is_quinzenal or is_english:
            if is_english:
                return "biweekly_new_en"
            return "biweekly_new_pt"
        return SKIP_OFFTOPIC

    return UNKNOWN


# ---------------------------------------------------------------------------
# Number parsing helpers
# ---------------------------------------------------------------------------


def _parse_br_num(s: str) -> Optional[float]:
    """Parse a Brazilian-format number string to float.

    Handles:
    - Thousands separator ``.`` (e.g. ``"1.234.567"``)
    - Decimal comma ``,`` (e.g. ``"1.234,56"``)
    - Kerning spaces inside digits (e.g. ``"1 89.559"`` → ``189559``)
    - Leading/trailing whitespace
    - Negative values (e.g. ``"-38.523"``)

    Returns ``None`` when the input cannot be parsed as a number.
    """
    if s is None:
        return None
    cleaned = s.strip()
    # Strip kerning spaces between digit groups (old PDFs)
    cleaned = re.sub(r"(\d)\s+(\d)", r"\1\2", cleaned)
    # Remove thousands separator (dot before 3+ digits not at end)
    cleaned = cleaned.replace(".", "")
    # Replace decimal comma with dot
    cleaned = cleaned.replace(",", ".")
    # Strip trailing percentage sign before conversion
    cleaned = cleaned.replace("%", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_cover_date(page_text: str) -> Optional[str]:
    """Extract the position/reference date from the cover page text.

    Returns the date string as ``DD/MM/YYYY`` or ``None`` if not found.
    Handles both Portuguese (``posição até``) and English (``Position until``).
    """
    m = re.search(r"posi[çc][aã]o at[eé]\s+(\d{2}/\d{2}/\d{4})", page_text, re.IGNORECASE)
    if not m:
        m = re.search(r"position until\s+(\d{2}/\d{2}/\d{4})", page_text, re.IGNORECASE)
    return m.group(1) if m else None


def _extract_fortnight_dates(page_text: str) -> list[str]:
    """Return all ``DD/MM`` fortnight date labels found in page text."""
    return re.findall(r"\b(\d{2}/\d{2})\b", page_text)


def _unpack_triplets(cell: str) -> list[tuple[Optional[float], Optional[float], Optional[float]]]:
    """Parse a packed cell containing one or more ``prior current var%`` triplets.

    Each triplet is on its own newline.  Returns a list of
    ``(prior, current, var_pct)`` tuples; elements may be ``None`` when the
    value is missing or unparseable.
    """
    result: list[tuple[Optional[float], Optional[float], Optional[float]]] = []
    if not cell:
        return result
    for raw_line in cell.split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split()
        prior = _parse_br_num(parts[0]) if len(parts) >= 1 else None
        current = _parse_br_num(parts[1]) if len(parts) >= 2 else None
        var_pct: Optional[float] = None
        if len(parts) >= 3:
            var_pct = _parse_br_num(parts[2])
        result.append((prior, current, var_pct))
    return result


def _unpack_pair_columns(cell: str) -> list[tuple[Optional[float], Optional[float]]]:
    """Parse a packed SP+CS blob where each line has two values separated by space.

    Used for the old-format history tables where all three regions are in a
    single text blob ordered as SP lines / CS lines.

    Returns a list of ``(prior, current)`` pairs per line.
    """
    result: list[tuple[Optional[float], Optional[float]]] = []
    if not cell:
        return result
    for raw_line in cell.split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split()
        prior = _parse_br_num(parts[0]) if len(parts) >= 1 else None
        current = _parse_br_num(parts[1]) if len(parts) >= 2 else None
        result.append((prior, current))
    return result


# ---------------------------------------------------------------------------
# Fortnight history (Table A)
# ---------------------------------------------------------------------------


def _parse_fortnight_history_new(
    pdf: pdfplumber.PDF,
    doc_type: str,
    harvest_year: str,
    idm: str,
    position_date: Optional[str],
    ingest_date: str,
) -> list[dict]:
    """Parse fortnight accumulation history from new-format bulletins (13-17pp).

    Uses Tabelas 3–7 which occupy the 5 pages immediately before the corn
    ethanol and monthly sales pages (i.e. pages[-9:-4] in a 13pp bulletin,
    adjusting to the actual number of history pages).

    Structure per page: tbl[0] is 4r×4c.
      row[0]: header continuation (partial text from title)
      row[1]: region subheader (São Paulo / South-Central / Other states)
      row[2]: year-comparison subheader (prior / current / var%)
      row[3]: data — one packed cell per region, containing all fortnight rows
    """
    records: list[dict] = []

    n = len(pdf.pages)
    # History pages are always Tabelas 3-7 (5 pages), followed by corn ethanol
    # and monthly sales, then a disclaimer page.
    # In 13pp: p5-p9 are history (0-indexed 4-8); p10=corn; p11=sales; p12=disclaimer.
    # Tail-index: pages[-9] through pages[-5].
    history_start = max(0, n - 9)
    history_pages = pdf.pages[history_start : n - 4]

    for page_idx, (var_name, unit) in enumerate(_HISTORY_VARS):
        if page_idx >= len(history_pages):
            break
        page = history_pages[page_idx]
        page_text = page.extract_text() or ""
        date_labels = _extract_fortnight_dates(page_text)
        tables = page.extract_tables()
        if not tables:
            logger.warning(
                "fortnight_history_new: no table on history page idx=%d idm=%s",
                page_idx, idm,
            )
            continue

        tbl = tables[0]
        if len(tbl) < 4:
            logger.warning("fortnight_history_new: tbl too short rows=%d idm=%s", len(tbl), idm)
            continue

        data_row = tbl[3]
        # col[1]=SP packed, col[2]=CS packed, col[3]=DE (may be None)
        sp_cell = data_row[1] if len(data_row) > 1 else None
        cs_cell = data_row[2] if len(data_row) > 2 else None
        de_cell = data_row[3] if len(data_row) > 3 else None

        sp_triplets = _unpack_triplets(sp_cell or "")
        cs_triplets = _unpack_triplets(cs_cell or "")
        de_triplets = _unpack_triplets(de_cell or "")

        n_rows = max(len(sp_triplets), len(cs_triplets))

        for row_idx in range(n_rows):
            label = date_labels[row_idx] if row_idx < len(date_labels) else None

            sp_prior, sp_cur, _ = sp_triplets[row_idx] if row_idx < len(sp_triplets) else (None, None, None)
            cs_prior, cs_cur, _ = cs_triplets[row_idx] if row_idx < len(cs_triplets) else (None, None, None)

            if row_idx < len(de_triplets):
                de_prior, de_cur, _ = de_triplets[row_idx]
            else:
                # Demais Estados = Centro-Sul - São Paulo (exact UNICA definition)
                de_prior = (cs_prior - sp_prior) if (cs_prior is not None and sp_prior is not None) else None
                de_cur = (cs_cur - sp_cur) if (cs_cur is not None and sp_cur is not None) else None

            for region, prior_val, cur_val in [
                ("centro_sul",    cs_prior, cs_cur),
                ("sao_paulo",     sp_prior, sp_cur),
                ("demais_estados", de_prior, de_cur),
            ]:
                for period_type, value in [("prior", prior_val), ("current", cur_val)]:
                    records.append({
                        "harvest_year":   harvest_year,
                        "idm":            idm,
                        "doc_type":       doc_type,
                        "position_date":  position_date,
                        "fortnight_label": label,
                        "fortnight_seq":  row_idx + 1,
                        "region":         region,
                        "variable":       var_name,
                        "period":         period_type,
                        "value":          value,
                        "unit":           unit,
                        "ingest_date":    ingest_date,
                    })

    return records


def _parse_fortnight_history_old(
    pdf: pdfplumber.PDF,
    doc_type: str,
    harvest_year: str,
    idm: str,
    position_date: Optional[str],
    ingest_date: str,
) -> list[dict]:
    """Parse fortnight history from old-format (10-12pp) bulletins.

    Old-format Tabelas 3-7 (pages 3-7, 0-indexed 2-6) use a 2-row × 3-col
    layout.  All three region values are packed into col[1] as a single text
    blob (SP lines, then CS lines concatenated).  col[2] is also present but
    typically None.

    The blob line order is:  all SP fortnights then all CS fortnights.
    len(fortnight_dates) gives the count of fortnight rows.
    """
    records: list[dict] = []

    history_pages = pdf.pages[2:7]

    for page_idx, (var_name, unit) in enumerate(_HISTORY_VARS):
        if page_idx >= len(history_pages):
            break
        page = history_pages[page_idx]
        page_text = page.extract_text() or ""
        date_labels = _extract_fortnight_dates(page_text)
        tables = page.extract_tables()
        if not tables:
            logger.warning(
                "fortnight_history_old: no table on history page idx=%d idm=%s",
                page_idx, idm,
            )
            continue

        tbl = tables[0]
        if len(tbl) < 2:
            continue

        data_row = tbl[1]
        # col[1] contains SP lines then CS lines; col[2] appears unused (None)
        blob = data_row[1] if len(data_row) > 1 else None
        if not blob:
            continue

        pairs = _unpack_pair_columns(blob)
        n_ft = len(date_labels) or (len(pairs) // 2)

        sp_pairs = pairs[:n_ft]
        cs_pairs = pairs[n_ft : n_ft * 2]

        for row_idx in range(max(len(sp_pairs), len(cs_pairs))):
            label = date_labels[row_idx] if row_idx < len(date_labels) else None

            sp_prior, sp_cur = sp_pairs[row_idx] if row_idx < len(sp_pairs) else (None, None)
            cs_prior, cs_cur = cs_pairs[row_idx] if row_idx < len(cs_pairs) else (None, None)
            de_prior = (cs_prior - sp_prior) if (cs_prior is not None and sp_prior is not None) else None
            de_cur = (cs_cur - sp_cur) if (cs_cur is not None and sp_cur is not None) else None

            for region, prior_val, cur_val in [
                ("centro_sul",    cs_prior, cs_cur),
                ("sao_paulo",     sp_prior, sp_cur),
                ("demais_estados", de_prior, de_cur),
            ]:
                for period_type, value in [("prior", prior_val), ("current", cur_val)]:
                    records.append({
                        "harvest_year":   harvest_year,
                        "idm":            idm,
                        "doc_type":       doc_type,
                        "position_date":  position_date,
                        "fortnight_label": label,
                        "fortnight_seq":  row_idx + 1,
                        "region":         region,
                        "variable":       var_name,
                        "period":         period_type,
                        "value":          value,
                        "unit":           unit,
                        "ingest_date":    ingest_date,
                    })

    return records


# ---------------------------------------------------------------------------
# Summary snapshot (Table B)
# ---------------------------------------------------------------------------


def _parse_summary_row_triplet(
    tbl: list[list],
    row_idx: int,
    col_cs: int,
    col_sp: int,
    col_de: Optional[int],
) -> dict[str, tuple[Optional[float], Optional[float], Optional[float]]]:
    """Extract (prior, current, var_pct) for CS, SP, DE from one table row."""
    if row_idx >= len(tbl):
        return {}
    row = tbl[row_idx]
    cs = _unpack_triplets(row[col_cs] if col_cs < len(row) else None or "")
    sp = _unpack_triplets(row[col_sp] if col_sp < len(row) else None or "")
    de = _unpack_triplets(row[col_de] if col_de is not None and col_de < len(row) else None or "")

    cs_vals = cs[0] if cs else (None, None, None)
    sp_vals = sp[0] if sp else (None, None, None)
    de_vals = de[0] if de else (None, None, None)

    # Fallback: DE = CS - SP
    if de_vals[1] is None and cs_vals[1] is not None and sp_vals[1] is not None:
        de_vals = (
            (cs_vals[0] - sp_vals[0]) if (cs_vals[0] is not None and sp_vals[0] is not None) else None,
            cs_vals[1] - sp_vals[1],
            None,
        )

    return {
        "centro_sul":     cs_vals,
        "sao_paulo":      sp_vals,
        "demais_estados": de_vals,
    }


def _snapshot_records_from_table(
    tbl: list[list],
    var_row_map: dict[int, tuple[str, str]],
    col_cs: int,
    col_sp: int,
    col_de: Optional[int],
    period_type: str,
    harvest_year: str,
    idm: str,
    doc_type: str,
    position_date: Optional[str],
    ingest_date: str,
) -> list[dict]:
    records: list[dict] = []
    for row_idx, (var_name, unit) in var_row_map.items():
        region_vals = _parse_summary_row_triplet(tbl, row_idx, col_cs, col_sp, col_de)
        for region, (prior_val, cur_val, var_pct) in region_vals.items():
            records.append({
                "harvest_year":  harvest_year,
                "idm":           idm,
                "doc_type":      doc_type,
                "position_date": position_date,
                "period_type":   period_type,
                "region":        region,
                "variable":      var_name,
                "current_value": cur_val,
                "prior_value":   prior_val,
                "var_pct":       var_pct,
                "unit":          unit,
                "ingest_date":   ingest_date,
            })
    return records


def _parse_summary_snapshot_new(
    pdf: pdfplumber.PDF,
    doc_type: str,
    harvest_year: str,
    idm: str,
    position_date: Optional[str],
    ingest_date: str,
) -> list[dict]:
    """Parse the Tabela 1 summary snapshot from new-format bulletins.

    Page pages[-10] (0-indexed).  Contains up to two tables:
    - tbl[0]: 15r × 5c — accumulated snapshot
    - tbl[1]: 13r × 4c — fortnightly snapshot (always present per probing)
    """
    records: list[dict] = []
    n = len(pdf.pages)
    page_idx = n - 10
    if page_idx < 0:
        page_idx = 3  # fallback for shorter bulletins

    page = pdf.pages[page_idx]
    tables = page.extract_tables()
    if not tables:
        logger.warning("summary_snapshot_new: no tables on page %d idm=%s", page_idx, idm)
        return records

    # Accumulated table (tbl[0]): 15r×5c
    # col[1]=CS, col[3]=SP, col[4]=DE
    if len(tables) >= 1:
        records.extend(
            _snapshot_records_from_table(
                tables[0],
                _SUMMARY_VAR_ROWS_NEW,
                col_cs=1, col_sp=3, col_de=4,
                period_type="accumulated",
                harvest_year=harvest_year, idm=idm, doc_type=doc_type,
                position_date=position_date, ingest_date=ingest_date,
            )
        )

    # Fortnightly table (tbl[1]): 13r×4c; col[1]=CS, col[2]=SP, col[3]=DE
    if len(tables) >= 2:
        records.extend(
            _snapshot_records_from_table(
                tables[1],
                _SUMMARY_VAR_ROWS_NEW,
                col_cs=1, col_sp=2, col_de=3,
                period_type="fortnightly",
                harvest_year=harvest_year, idm=idm, doc_type=doc_type,
                position_date=position_date, ingest_date=ingest_date,
            )
        )

    return records


def _parse_summary_snapshot_old(
    pdf: pdfplumber.PDF,
    doc_type: str,
    harvest_year: str,
    idm: str,
    position_date: Optional[str],
    ingest_date: str,
) -> list[dict]:
    """Parse the Tabela 1 summary snapshot from old-format bulletins.

    Old-format uses a single 27-row × 5-col table on page 2 (0-indexed 1).
    Rows 1–12 = accumulated; row 13 is a divider with "QUINZENAL" header;
    rows 14–25 = fortnightly.

    Columns: [0]=label [1]=CS [2]=None [3]=SP [4]=DE
    """
    records: list[dict] = []
    if len(pdf.pages) < 2:
        return records

    tables = pdf.pages[1].extract_tables()
    if not tables:
        return records

    tbl = tables[0]
    # Accumulated section: rows 2-6
    records.extend(
        _snapshot_records_from_table(
            tbl, _SUMMARY_VAR_ROWS_OLD,
            col_cs=1, col_sp=3, col_de=4,
            period_type="accumulated",
            harvest_year=harvest_year, idm=idm, doc_type=doc_type,
            position_date=position_date, ingest_date=ingest_date,
        )
    )
    # Fortnightly section: same variable order, offset by ~13 rows
    fortnightly_var_rows = {k + 13: v for k, v in _SUMMARY_VAR_ROWS_OLD.items()}
    records.extend(
        _snapshot_records_from_table(
            tbl, fortnightly_var_rows,
            col_cs=1, col_sp=3, col_de=4,
            period_type="fortnightly",
            harvest_year=harvest_year, idm=idm, doc_type=doc_type,
            position_date=position_date, ingest_date=ingest_date,
        )
    )
    return records


# ---------------------------------------------------------------------------
# Corn ethanol (Table C)
# ---------------------------------------------------------------------------


def _parse_corn_ethanol(
    pdf: pdfplumber.PDF,
    doc_type: str,
    harvest_year: str,
    idm: str,
    position_date: Optional[str],
    ingest_date: str,
) -> list[dict]:
    """Parse Tabela 8 (corn ethanol production) from biweekly bulletins.

    Page: pages[-4] (0-indexed n-4).
    Table structure: 3r × 5c
      row[0]: column group headers
      row[1]: sub-headers (anidro / hidratado / total)
      row[2]: data — all fortnights packed, one cell per column group

    Col layout:
      [0]: fortnight label (packed or 'Quinzena')
      [1]: quinzenal anidro+hidratado pairs packed vertically
      [2]: quinzenal total
      [3]: accumulated anidro+hidratado pairs
      [4]: accumulated total (may be None)
    """
    records: list[dict] = []
    n = len(pdf.pages)
    page = pdf.pages[n - 4]
    page_text = page.extract_text() or ""
    date_labels = _extract_fortnight_dates(page_text)
    tables = page.extract_tables()
    if not tables:
        logger.warning("corn_ethanol: no table on page %d idm=%s", n - 4, idm)
        return records

    tbl = tables[0]
    if len(tbl) < 3:
        return records

    data_row = tbl[2]
    quinzenal_cell = data_row[1] if len(data_row) > 1 else None
    accum_cell = data_row[3] if len(data_row) > 3 else None

    # Each line in the quinzenal cell has two numbers: anhydrous and hydrous
    quinzenal_pairs = _unpack_pair_columns(quinzenal_cell or "")
    accum_pairs = _unpack_pair_columns(accum_cell or "")

    # Total cells (col[2] and col[4]) have one number per line
    def _parse_single_col(cell: Optional[str]) -> list[Optional[float]]:
        if not cell:
            return []
        result = []
        for line in cell.split("\n"):
            line = line.strip()
            if line:
                result.append(_parse_br_num(line.split()[0]))
        return result

    q_totals = _parse_single_col(data_row[2] if len(data_row) > 2 else None)
    a_totals = _parse_single_col(data_row[4] if len(data_row) > 4 else None)

    n_rows = max(len(quinzenal_pairs), len(accum_pairs))

    for row_idx in range(n_rows):
        label = date_labels[row_idx] if row_idx < len(date_labels) else None
        q_anhy, q_hydr = quinzenal_pairs[row_idx] if row_idx < len(quinzenal_pairs) else (None, None)
        a_anhy, a_hydr = accum_pairs[row_idx] if row_idx < len(accum_pairs) else (None, None)
        q_tot = q_totals[row_idx] if row_idx < len(q_totals) else (
            (q_anhy + q_hydr) if (q_anhy is not None and q_hydr is not None) else None
        )
        a_tot = a_totals[row_idx] if row_idx < len(a_totals) else (
            (a_anhy + a_hydr) if (a_anhy is not None and a_hydr is not None) else None
        )

        records.append({
            "harvest_year":          harvest_year,
            "idm":                   idm,
            "doc_type":              doc_type,
            "position_date":         position_date,
            "fortnight_label":       label,
            "fortnight_seq":         row_idx + 1,
            "anhydrous_quinzenal_kl": q_anhy,
            "hydrous_quinzenal_kl":  q_hydr,
            "total_quinzenal_kl":    q_tot,
            "anhydrous_accum_kl":    a_anhy,
            "hydrous_accum_kl":      a_hydr,
            "total_accum_kl":        a_tot,
            "ingest_date":           ingest_date,
        })

    return records


# ---------------------------------------------------------------------------
# Monthly ethanol sales (Table D)
# ---------------------------------------------------------------------------


_MONTH_ABBR_RE = re.compile(
    r"(abr|mai|jun|jul|ago|set|out|nov|dez|jan|fev|mar|apr|may|aug|sep|oct|dec)",
    re.IGNORECASE,
)


def _is_artifact_cell(cell: Optional[str]) -> bool:
    """Return True if the cell contains only rotated-text rendering artifacts."""
    if cell is None:
        return True
    stripped = cell.strip()
    if not stripped:
        return True
    # Artifact: only letters that are rotated column-header fragments
    if stripped in _SALES_ARTIFACTS:
        return True
    # Multi-character artifact: only single non-digit chars separated by newlines
    parts = [p.strip() for p in stripped.replace("\n", " ").split() if p.strip()]
    if all(len(p) <= 2 and not p[0].isdigit() for p in parts):
        return True
    return False


def _parse_month_rows(blob: str) -> list[tuple[str, int, bool, list[Optional[float]]]]:
    """Parse month rows from a packed column-0 sales cell.

    Each meaningful line contains: ``MonthAbbr [prior_total prior_ext prior_int] [*]``
    but in practice the values are spread across multiple columns.

    Returns a list of (month_label, month_num, is_partial) tuples for each
    non-artifact line that starts with a month abbreviation.
    """
    result = []
    for raw_line in blob.split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        m = _MONTH_ABBR_RE.match(line)
        if not m:
            continue
        abbr = m.group(1).lower()
        month_num = _MONTH_MAP.get(abbr, 0)
        is_partial = "*" in line
        # The remainder of the line contains the packed values for Total, Ext, Int
        remainder = line[m.end():].strip().lstrip("*").strip()
        nums = [_parse_br_num(p) for p in remainder.split() if p]
        result.append((line.split()[0].rstrip("*"), month_num, is_partial, nums))
    return result


def _parse_monthly_sales(
    pdf: pdfplumber.PDF,
    doc_type: str,
    harvest_year: str,
    idm: str,
    position_date: Optional[str],
    ingest_date: str,
) -> list[dict]:
    """Parse Tabela 9 (monthly ethanol sales) from biweekly bulletins.

    Page: pages[-3] (0-indexed n-3).
    Table structure: 11r × 5c (new) or 10r × 5c (old).

    pdfplumber merges all month rows into a single cell in row[1] or row[2]
    of col[0].  Values for each column are similarly packed.  The "rotated"
    Produto label (latot/lonatE) fragments appear in additional rows.

    All numeric values are in m³.
    """
    records: list[dict] = []
    n = len(pdf.pages)
    page = pdf.pages[n - 3]
    tables = page.extract_tables()
    if not tables:
        logger.warning("monthly_sales: no table on page %d idm=%s", n - 3, idm)
        return records

    tbl = tables[0]

    # Find the data row: the first row after the header rows where col[0]
    # starts with a month abbreviation or contains month abbreviations.
    month_blob: Optional[str] = None
    total_blob: Optional[str] = None
    ext_blob: Optional[str] = None
    int_blob: Optional[str] = None

    for row in tbl:
        if not row:
            continue
        cell0 = row[0] if row[0] else ""
        if _MONTH_ABBR_RE.search(cell0):
            month_blob = cell0
            # In the old format all values are in col[0]; in new format
            # they are spread across col[0] and internal cols.
            # Strategy: parse month labels from col[0], then parse packed
            # cols 2, 3, 4 for total / external / internal respectively.
            # The new format has col[2]=Total, col[3]=Ext, col[4]=Int.
            # Old format embeds all values in col[0].
            total_blob = row[2] if len(row) > 2 else None
            ext_blob = row[3] if len(row) > 3 else None
            int_blob = row[4] if len(row) > 4 else None
            break

    if not month_blob:
        logger.warning("monthly_sales: could not find month data row idm=%s", idm)
        return records

    month_rows = _parse_month_rows(month_blob)

    # Parse value blobs: each line corresponds to one month in order
    def _col_vals(blob: Optional[str]) -> list[tuple[Optional[float], Optional[float]]]:
        """Parse a packed column blob with two values per line (prior, current)."""
        if not blob:
            return []
        result = []
        for line in blob.split("\n"):
            line = line.strip()
            if not line or _is_artifact_cell(line):
                continue
            parts = line.split()
            prior = _parse_br_num(parts[0]) if len(parts) >= 1 else None
            current = _parse_br_num(parts[1]) if len(parts) >= 2 else None
            result.append((prior, current))
        return result

    total_vals = _col_vals(total_blob)
    ext_vals = _col_vals(ext_blob)
    int_vals = _col_vals(int_blob)

    for row_idx, (month_label, month_num, is_partial, inline_nums) in enumerate(month_rows):
        # Prefer parsed column blobs; fall back to inline_nums in col[0]
        tot_prior, tot_cur = total_vals[row_idx] if row_idx < len(total_vals) else (None, None)
        ext_prior, ext_cur = ext_vals[row_idx] if row_idx < len(ext_vals) else (None, None)
        int_prior, int_cur = int_vals[row_idx] if row_idx < len(int_vals) else (None, None)

        # Old-format fallback: all 6 values packed inline in month_blob col[0]
        if tot_cur is None and len(inline_nums) >= 6:
            tot_prior, tot_cur  = inline_nums[0], inline_nums[1]
            ext_prior, ext_cur  = inline_nums[2], inline_nums[3]
            int_prior, int_cur  = inline_nums[4], inline_nums[5]
        elif tot_cur is None and len(inline_nums) >= 2:
            tot_prior, tot_cur = inline_nums[0], inline_nums[1]

        records.append({
            "harvest_year":       harvest_year,
            "idm":                idm,
            "doc_type":           doc_type,
            "position_date":      position_date,
            "month_label":        month_label,
            "month_num":          month_num,
            "is_partial":         is_partial,
            "total_current_m3":   tot_cur,
            "total_prior_m3":     tot_prior,
            "external_current_m3": ext_cur,
            "external_prior_m3":  ext_prior,
            "internal_current_m3": int_cur,
            "internal_prior_m3":  int_prior,
            "ingest_date":        ingest_date,
        })

    return records


# ---------------------------------------------------------------------------
# Season-final extras (Table E) — EAV
# ---------------------------------------------------------------------------


def _parse_season_final_extras(
    pdf: pdfplumber.PDF,
    harvest_year: str,
    idm: str,
    ingest_date: str,
) -> list[dict]:
    """Parse supplementary sub-tables from season-final reports (EAV output).

    Extracts the following sub-tables and stores them with a ``table_id``
    discriminator.  Each sub-table has its own row/column structure; values
    are stored in a generic EAV schema with ``dim1``, ``dim2``, ``variable``,
    ``value``, and ``unit`` columns.

    Sub-tables extracted:
    +-----------------------+------+-----------------------------------+
    | table_id              | page | description                       |
    +=======================+======+===================================+
    | state_breakdown       |    3 | production by state               |
    | atr_quality           |   12 | ATR and quality metrics           |
    | supply_demand_ethanol |   21 | ethanol supply/demand balance     |
    | supply_demand_sugar   |   22 | sugar supply/demand balance       |
    | cane_prices           |   23 | ATR and cane prices               |
    | corn_ethanol_final    |   24 | corn ethanol by fortnight         |
    +-----------------------+------+-----------------------------------+
    """
    records: list[dict] = []
    n = len(pdf.pages)

    # Read pdf_season from p1 text
    p1_text = pdf.pages[0].extract_text() or ""
    season_match = re.search(r"safra\s+(\d{4}/\d{4})", p1_text, re.IGNORECASE)
    pdf_season = season_match.group(1) if season_match else None

    base = {
        "harvest_year": harvest_year,
        "idm":          idm,
        "pdf_season":   pdf_season,
        "ingest_date":  ingest_date,
    }

    def _eav_from_table(tbl, table_id, unit=""):
        rows = []
        for ri, row in enumerate(tbl):
            for ci, cell in enumerate(row):
                val = _parse_br_num(cell) if cell else None
                if val is None:
                    continue
                rows.append({
                    **base,
                    "table_id": table_id,
                    "dim1":     ri,
                    "dim2":     ci,
                    "variable": f"row{ri}_col{ci}",
                    "value":    val,
                    "unit":     unit,
                })
        return rows

    # Page targets (1-indexed → 0-indexed)
    targets = [
        (2,  "state_breakdown",       ""),
        (11, "atr_quality",           ""),
        (16, "sugar_exports_monthly", "t"),
        (17, "ethanol_imports_monthly","m3"),
        (20, "supply_demand_ethanol", "m3"),
        (21, "supply_demand_sugar",   "t"),
        (22, "cane_prices",           ""),
        (23, "corn_ethanol_final",    "m3"),
    ]

    for page_idx, table_id, unit in targets:
        if page_idx >= n:
            continue
        tables = pdf.pages[page_idx].extract_tables()
        if not tables:
            continue
        records.extend(_eav_from_table(tables[0], table_id, unit))

    return records


# ---------------------------------------------------------------------------
# Double-issue split
# ---------------------------------------------------------------------------


def split_double_issue(pdf_bytes: bytes) -> tuple[bytes, bytes]:
    """Split a double-issue 20-page PDF into two separate byte streams.

    The first occurrence of a second cover page (identified by the presence
    of a known cover keyword on any page after the first) marks the split
    point.  Scans pages[1:] for a second cover.

    Returns ``(part1_bytes, part2_bytes)``.  If no split point is found,
    returns the original bytes as part1 and empty bytes as part2.
    """
    cover_keywords = [
        "harvest closure",
        "bi-weekly bulletin",
        "acompanhamento quinzenal",
        "bi-weekly",
        "safra",
    ]

    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError:
        logger.error("split_double_issue: pypdf not available")
        return pdf_bytes, b""

    reader = PdfReader(io.BytesIO(pdf_bytes))
    n = len(reader.pages)

    split_idx: Optional[int] = None
    for i in range(1, n):
        # Use pdfplumber for text extraction consistency
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as plumber_pdf:
            page_text = (plumber_pdf.pages[i].extract_text() or "").lower()
        if any(kw in page_text for kw in cover_keywords):
            split_idx = i
            break

    if split_idx is None:
        return pdf_bytes, b""

    def _write_pages(indices: list[int]) -> bytes:
        writer = PdfWriter()
        for idx in indices:
            writer.add_page(reader.pages[idx])
        buf = io.BytesIO()
        writer.write(buf)
        return buf.getvalue()

    part1 = _write_pages(list(range(split_idx)))
    part2 = _write_pages(list(range(split_idx, n)))
    return part1, part2


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def transform_pdf(
    pdf_bytes: bytes,
    harvest_year: str,
    idm: str,
    ingest_date: str,
) -> dict[str, pd.DataFrame]:
    """Transform a raw UNICA biweekly PDF into up to five bronze DataFrames.

    Args:
        pdf_bytes:    Raw bytes of the PDF file.
        harvest_year: Harvest year from the S3 partition key, e.g.
                      ``"2023_2024"`` or ``"2023/2024"``.
        idm:          Bulletin identifier, e.g. ``"pdf_1775f0afde26b483"`` or
                      ``"12439002"``.
        ingest_date:  ISO date string for when the bronze files are written,
                      e.g. ``"2026-06-01"``.

    Returns:
        Dictionary with keys from the five output table names (see module
        docstring).  For skipped/off-topic PDFs the dictionary contains only
        ``{"_classification": <label>}`` with no DataFrame entries.
    """
    doc_type = classify_pdf(pdf_bytes)
    logger.info("transform_pdf  idm=%s  doc_type=%s", idm, doc_type)

    if doc_type in (SKIP_OFFTOPIC, SEASON_ESTIMATE, UNKNOWN):
        return {"_classification": doc_type}

    # Handle double-issue by splitting and recursing
    if doc_type == "season_close_en_double":
        part1, part2 = split_double_issue(pdf_bytes)
        result: dict[str, pd.DataFrame] = {"_classification": doc_type}
        if part2:
            sub = transform_pdf(part2, harvest_year, idm, ingest_date)
            for k, v in sub.items():
                if not k.startswith("_"):
                    result[k] = v
        return result

    # For season_final, only extract Table E
    if doc_type == "season_final_pt":
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            extras_records = _parse_season_final_extras(pdf, harvest_year, idm, ingest_date)
        result = {"_classification": doc_type}
        if extras_records:
            result["season_final_extras"] = pd.DataFrame(extras_records)
        return result

    # Biweekly variants
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        p1_text = pdf.pages[0].extract_text() or ""
        position_date = _parse_cover_date(p1_text)

        hy_norm = harvest_year.replace("/", "_")

        if doc_type in ("biweekly_new_pt", "biweekly_new_en"):
            hist_records = _parse_fortnight_history_new(
                pdf, doc_type, hy_norm, idm, position_date, ingest_date
            )
            snap_records = _parse_summary_snapshot_new(
                pdf, doc_type, hy_norm, idm, position_date, ingest_date
            )
        else:  # biweekly_old_pt
            hist_records = _parse_fortnight_history_old(
                pdf, doc_type, hy_norm, idm, position_date, ingest_date
            )
            snap_records = _parse_summary_snapshot_old(
                pdf, doc_type, hy_norm, idm, position_date, ingest_date
            )

        corn_records = _parse_corn_ethanol(
            pdf, doc_type, hy_norm, idm, position_date, ingest_date
        )
        sales_records = _parse_monthly_sales(
            pdf, doc_type, hy_norm, idm, position_date, ingest_date
        )

    result = {"_classification": doc_type}

    if hist_records:
        result["fortnight_production"] = pd.DataFrame(hist_records)
    if snap_records:
        result["summary_snapshot"] = pd.DataFrame(snap_records)
    if corn_records:
        result["corn_ethanol"] = pd.DataFrame(corn_records)
    if sales_records:
        result["monthly_ethanol_sales"] = pd.DataFrame(sales_records)

    return result
