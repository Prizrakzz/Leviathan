"""Bronze transform for USDA WASDE (World Agricultural Supply and Demand Estimates).

Converts raw WASDE files (PDF or TXT) into a tidy long-format DataFrame with
one row per (release_date, table_name, region, market_year, attribute).

Three source formats are handled:

* **Digital PDF 2000–2026** — pdfplumber text extraction, two sub-formats:
  - Format A (~2000–2013): colon-delimited fixed-width ASCII tables
  - Format B (~2014–2026): columnar layout, bounding-box alignment
* **TXT 1995–1999** — plain text decode; same colon-delimited Format A layout
* **Scanned PDF 1973–1994** — AWS Textract LINE blocks (submitted/polled
  externally); reconstruct rows from y-coordinate clustering

Output schema
-------------
release_date    : str  — "YYYY-MM-DD", sourced from the raw S3 partition key
table_name      : str  — e.g. "World Wheat Supply and Use"
region          : str  — e.g. "Argentina", "World", "United States"
market_year     : str  — e.g. "2009/10"
status          : str  — "Proj." | "Est." | ""
projection_month: str  — "January" | "December" | "" (current-year projections only)
attribute       : str  — see _ATTRIBUTE_ALIASES
value           : float — NaN if the cell was blank or unparseable
unit            : str  — from the page heading, e.g. "Million Metric Tons"
"""
from __future__ import annotations

import io
import re
from typing import Literal

import pandas as pd
import pdfplumber

from leviathan.common.logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Attribute name normalisation
# ---------------------------------------------------------------------------
# Maps raw header words/fragments → canonical attribute names.
_ATTRIBUTE_ALIASES: dict[str, str] = {
    # Supply-side
    "beginning stocks":     "beginning_stocks",
    "beginning":            "beginning_stocks",
    "beg. stocks":          "beginning_stocks",
    "beg stocks":           "beginning_stocks",
    "produc":               "production",       # truncated header "Produc-\ntion"
    "production":           "production",
    "output":               "production",
    "imports":              "imports",
    "supply, total":        "total_supply",
    "supply total":         "total_supply",
    "total supply":         "total_supply",
    # Use-side
    "feed":                 "feed",
    "domestic 2/":          "domestic_total",
    "domestic":             "domestic_total",
    "domestic total":       "domestic_total",
    "domestic use":         "domestic_total",
    "total":                "domestic_total",
    "food":                 "food_use",
    "seed":                 "seed_use",
    "feed and residual":    "feed_residual",
    "feed/residual":        "feed_residual",
    "use, total":           "total_use",
    "use total":            "total_use",
    "total use":            "total_use",
    "exports":              "exports",
    "trade 2/":             "trade",
    "trade":                "trade",
    "ending stocks":        "ending_stocks",
    "ending":               "ending_stocks",
    "stocks":               "ending_stocks",
    # US-specific
    "planted":              "planted_area",
    "harvested":            "harvested_area",
    "yield per harvested":  "yield",
    "yield":                "yield",
    "avg. farm price":      "avg_farm_price",
    # Oilseed/product tables
    "crush":                "crush",
    "residual":             "residual",
}

# Pages (0-indexed) to skip: narrative (0–6) and admin/livestock (30+)
_SKIP_BEFORE = 7   # skip pages 0–6
_SKIP_FROM   = 30  # skip pages 30+

# Regex: market year line, e.g. "2009/10", "2009/10 (Proj.)", "2008/09 (Est.)"
_MY_RE = re.compile(
    r"^\s*(\d{4}/\d{2,4})"          # market year e.g. 2009/10 or 2009/2010
    r"(?:\s+\(?(Est\.?|Proj\.?|Estimated|Projected)\)?)?"  # optional status
    r"\s*:?\s*$",
    re.IGNORECASE,
)

# Regex: projection month line, e.g. "December :", "January :"
_PROJ_MONTH_RE = re.compile(
    r"^\s*(January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s*:?\s*$",
    re.IGNORECASE,
)

# Regex: a data row (starts with a region label, has numbers after colons)
_DATA_ROW_RE = re.compile(r"[\d,]+\.\d+|[\d,]{2,}")

# Separator line in Format A / TXT
_SEP_RE = re.compile(r"^={5,}")

# Unit extraction from table heading
_UNIT_RE = re.compile(
    r"\(([^)]+)\)|"                          # e.g. "(Million Metric Tons)"
    r"(Million\s+\w+(?:\s+\w+)*)\s*$",       # e.g. "Million Metric Tons"
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Public helpers (also used by tests)
# ---------------------------------------------------------------------------

def _detect_format(text: str) -> Literal["colon", "columnar"]:
    """Return "colon" if the text contains Format-A separator lines, else "columnar"."""
    return "colon" if _SEP_RE.search(text) else "columnar"


def _parse_unit(heading_text: str) -> str:
    """Extract unit string from a table heading line.

    Examples
    --------
    "World Wheat Supply and Use 1/ (Million Metric Tons)" -> "Million Metric Tons"
    "U.S. Wheat Supply and Use 1/ Million bushels"        -> "Million bushels"
    "World and U.S. Supply and Use for Cotton 1/ Million 480-lb. bales" -> "Million 480-lb. bales"
    """
    m = _UNIT_RE.search(heading_text)
    if m:
        return (m.group(1) or m.group(2) or "").strip()
    # Fallback: look for "Million" anywhere
    m2 = re.search(r"(Million[^/\n]*?)(?:\s*$|\s*1/)", heading_text, re.IGNORECASE)
    if m2:
        return m2.group(1).strip()
    return ""


def _parse_market_year_and_status(label: str) -> tuple[str, str]:
    """Parse a market-year label into (market_year, status).

    Examples
    --------
    "2009/10"              -> ("2009/10", "")
    "2009/10 (Proj.)"      -> ("2009/10", "Proj.")
    "2008/09 (Est.)"       -> ("2008/09", "Est.")
    "2008/09 (Estimated)"  -> ("2008/09", "Est.")
    """
    label = label.strip()
    m = re.match(
        r"(\d{4}/\d{2,4})"
        r"(?:\s+\(?(Est(?:imated)?\.?|Proj(?:ected)?\.?)\)?)?",
        label,
        re.IGNORECASE,
    )
    if not m:
        return (label, "")
    my = m.group(1)
    raw_status = (m.group(2) or "").strip()
    if re.match(r"^Est", raw_status, re.IGNORECASE):
        return (my, "Est.")
    if re.match(r"^Proj", raw_status, re.IGNORECASE):
        return (my, "Proj.")
    return (my, "")


def _strip_filler(text: str) -> str:
    """Remove 'filler' tokens emitted by pdfplumber in Format B interleaved rows."""
    return re.sub(r"\bfiller\b", "", text, flags=re.IGNORECASE).strip()


def _normalise_attr(raw: str) -> str:
    """Map a raw header fragment to a canonical attribute name."""
    key = raw.strip().lower().rstrip(".")
    if key in _ATTRIBUTE_ALIASES:
        return _ATTRIBUTE_ALIASES[key]
    # Try prefix match
    for k, v in _ATTRIBUTE_ALIASES.items():
        if key.startswith(k):
            return v
    return key.replace(" ", "_").replace("/", "_").replace(",", "")


def _parse_number(s: str) -> float:
    """Parse a number string to float; return NaN on failure."""
    s = s.strip().replace(",", "")
    if not s or s in ("-", "--", "N/A", "n/a"):
        return float("nan")
    try:
        return float(s)
    except ValueError:
        return float("nan")


# ---------------------------------------------------------------------------
# Format A / TXT parser (colon-delimited)
# ---------------------------------------------------------------------------

def _parse_colon_table_block(
    block_lines: list[str],
    release_date: str,
    table_name: str,
    unit: str,
) -> list[dict]:
    """Parse a single colon-delimited table block into a list of row dicts."""
    rows: list[dict] = []

    # Rebuild the header from lines before the first data rows.
    # Header lines are those that contain mostly text (no numbers after colons).
    # Find the column headers by looking for lines with attribute keywords.
    header_attrs: list[str] = []
    header_found = False

    market_year = ""
    status = ""
    projection_month = ""
    col_count = 0

    for raw_line in block_lines:
        line = raw_line.strip()

        # Skip separators and empty lines
        if not line or _SEP_RE.match(line):
            continue

        # Market year context line  e.g. ": 2009/10 (Proj.) :"
        # or plain "2009/10 (Proj.)"
        clean = re.sub(r"^\s*:\s*", "", line).strip()
        if _MY_RE.match(clean):
            m = _MY_RE.match(clean)
            market_year, status = _parse_market_year_and_status(m.group(0).strip())
            projection_month = ""
            continue

        # Projection month  e.g. "December :"
        pm_m = _PROJ_MONTH_RE.match(clean)
        if pm_m:
            projection_month = pm_m.group(1).capitalize()
            continue

        # Try to split on colons: "Region : v1  v2  v3 ..."
        # Format A lines look like:
        #   "World 3/ : 127.59 610.46 113.39 ..."  or
        #   "Argentina : 1.37  18.00  0.02 ..."
        if ":" in line:
            # Split at FIRST colon (region : values) or detect header line
            parts = line.split(":", 1)
            label_part = parts[0].strip()
            values_part = parts[1].strip() if len(parts) > 1 else ""

            # Detect header line: label contains known attribute words, no digits
            label_lower = label_part.lower()
            if not header_found and not _DATA_ROW_RE.search(line):
                # Could be a header fragment line like ":Beginning:Produc-:"
                # Extract attribute tokens from the whole line
                tokens = re.split(r"[:]+", line)
                attrs_in_line = [
                    _normalise_attr(t) for t in tokens
                    if t.strip() and not re.match(r"^\d", t.strip())
                    and len(t.strip()) > 2
                ]
                if attrs_in_line and any(
                    a in _ATTRIBUTE_ALIASES.values() for a in attrs_in_line
                ):
                    header_attrs.extend(a for a in attrs_in_line if a not in header_attrs)
                continue

            if not market_year:
                continue

            # Data row: extract numbers from values_part
            # Numbers may be space-separated; some cells may be blank
            nums_raw = re.findall(r"[\d,]+\.?\d*|-{1,2}", values_part)
            if not nums_raw:
                continue

            region = re.sub(r"\s*\d+/\s*$", "", label_part).strip()  # strip footnote refs
            region = re.sub(r"\s+\d+\s*$", "", region).strip()

            if not region:
                continue

            values = [_parse_number(n) for n in nums_raw]

            # Pair values with header attributes
            used_attrs = header_attrs if header_attrs else []
            for idx, val in enumerate(values):
                attr = used_attrs[idx] if idx < len(used_attrs) else f"col_{idx}"
                rows.append({
                    "release_date":     release_date,
                    "table_name":       table_name,
                    "region":           region,
                    "market_year":      market_year,
                    "status":           status,
                    "projection_month": projection_month,
                    "attribute":        attr,
                    "value":            val,
                    "unit":             unit,
                })
        # Lines without colon: could be header continuation or footnote
        # Skip footnotes (start with digit or "1/")
        elif re.match(r"^\s*\d+/", line):
            continue

    return rows


def _parse_colon_page(page_text: str, release_date: str) -> list[dict]:
    """Parse a full colon-format page (may contain multiple tables)."""
    rows: list[dict] = []
    lines = page_text.splitlines()

    # Split into table blocks on separator lines, keeping the heading that
    # precedes each separator.
    table_blocks: list[tuple[str, str, list[str]]] = []  # (table_name, unit, lines)
    current_heading_lines: list[str] = []
    current_table_lines: list[str] = []
    in_table = False
    table_name = ""
    unit = ""

    for line in lines:
        if _SEP_RE.match(line.strip()):
            if not in_table:
                # First separator for this block: heading is what came before
                # Find the table name (last non-empty heading line before sep)
                for hl in reversed(current_heading_lines):
                    if hl.strip() and "Supply and Use" in hl:
                        table_name = hl.strip()
                        unit = _parse_unit(hl)
                        break
                else:
                    # Fallback: use last non-empty line
                    for hl in reversed(current_heading_lines):
                        if hl.strip():
                            table_name = hl.strip()
                            unit = _parse_unit(hl)
                            break
                in_table = True
                current_table_lines = []
            else:
                # Closing separator
                table_blocks.append((table_name, unit, current_table_lines))
                in_table = False
                current_heading_lines = []
                current_table_lines = []
                table_name = ""
                unit = ""
        elif in_table:
            current_table_lines.append(line)
        else:
            current_heading_lines.append(line)

    # Flush any unclosed block
    if in_table and current_table_lines:
        table_blocks.append((table_name, unit, current_table_lines))

    for tname, tunit, tlines in table_blocks:
        if not tname:
            continue
        rows.extend(_parse_colon_table_block(tlines, release_date, tname, tunit))

    return rows


# ---------------------------------------------------------------------------
# Format B parser (columnar, bounding-box alignment)
# ---------------------------------------------------------------------------

def _parse_columnar_page(page, release_date: str) -> list[dict]:
    """Parse a single pdfplumber Page object using bounding-box word extraction."""
    rows: list[dict] = []

    # Extract words with bounding boxes
    words = page.extract_words(x_tolerance=5, y_tolerance=5)
    if not words:
        return rows

    # Group words into lines by y-coordinate (within 5 pts)
    from collections import defaultdict
    lines_by_y: dict[int, list[dict]] = defaultdict(list)
    for w in words:
        y_bucket = round(w["top"] / 5) * 5
        lines_by_y[y_bucket].append(w)

    sorted_ys = sorted(lines_by_y.keys())
    line_groups: list[list[dict]] = [
        sorted(lines_by_y[y], key=lambda w: w["x0"])
        for y in sorted_ys
    ]

    # Get full page text to detect page heading / table name
    page_text = page.extract_text() or ""
    page_text = _strip_filler(page_text)

    # Detect table name from page heading (first line containing "Supply and Use")
    table_name = ""
    unit = ""
    for line in page_text.splitlines():
        line_clean = line.strip()
        if "Supply and Use" in line_clean:
            table_name = line_clean
            unit = _parse_unit(line_clean)
            break

    if not table_name:
        return rows

    # Find header row: a line whose words map mostly to attribute names
    header_row_idx = -1
    col_positions: list[tuple[float, str]] = []  # (x_center, attribute)

    for i, word_group in enumerate(line_groups):
        words_text = [_strip_filler(w["text"]) for w in word_group]
        words_lower = [w.lower() for w in words_text]
        attr_hits = sum(
            1 for w in words_lower
            if any(alias.startswith(w[:5]) for alias in _ATTRIBUTE_ALIASES if len(w) >= 4)
        )
        if attr_hits >= 3:
            header_row_idx = i
            # Build column position map
            for w in word_group:
                wtext = _strip_filler(w["text"])
                if not wtext or not re.search(r"[a-zA-Z]", wtext):
                    continue
                attr = _normalise_attr(wtext)
                x_center = (w["x0"] + w["x1"]) / 2.0
                col_positions.append((x_center, attr))
            break

    if header_row_idx < 0 or not col_positions:
        return rows

    # Merge adjacent header words into multi-word attribute names
    # e.g. "Beginning" + "Stocks" -> "beginning_stocks"
    merged_cols: list[tuple[float, str]] = []
    i = 0
    while i < len(col_positions):
        x0, a0 = col_positions[i]
        if i + 1 < len(col_positions):
            x1, a1 = col_positions[i + 1]
            combined = f"{a0} {a1}".lower()
            if combined.replace("_", " ") in _ATTRIBUTE_ALIASES:
                merged_cols.append(((x0 + x1) / 2, _ATTRIBUTE_ALIASES[combined.replace("_", " ")]))
                i += 2
                continue
        merged_cols.append((x0, a0))
        i += 1

    col_positions = merged_cols

    def _assign_col(x_center: float) -> str:
        """Assign a word's x-center to the nearest column attribute."""
        if not col_positions:
            return "col_0"
        return min(col_positions, key=lambda cp: abs(cp[0] - x_center))[1]

    # Parse data rows
    market_year = ""
    status = ""
    projection_month = ""

    for word_group in line_groups[header_row_idx + 1:]:
        words_clean = [_strip_filler(w["text"]) for w in word_group]
        line_text = " ".join(words_clean).strip()
        if not line_text:
            continue

        # Market year line
        if _MY_RE.match(line_text):
            m = _MY_RE.match(line_text)
            market_year, status = _parse_market_year_and_status(m.group(0))
            projection_month = ""
            continue

        # Projection month line
        pm_m = _PROJ_MONTH_RE.match(line_text)
        if pm_m:
            projection_month = pm_m.group(1).capitalize()
            continue

        if not market_year:
            continue

        # Check if this is a data line: first word is region, rest are numbers
        first_word_is_alpha = bool(re.match(r"[A-Za-z]", words_clean[0])) if words_clean else False
        has_numbers = bool(_DATA_ROW_RE.search(line_text))

        if not (first_word_is_alpha and has_numbers):
            continue

        # Collect region name (words until first numeric word)
        region_words: list[str] = []
        num_words: list[dict] = []  # original word dicts with positions
        for w_orig, w_text in zip(word_group, words_clean):
            if re.match(r"^[\d,]+\.?\d*$", w_text):
                num_words.append(w_orig)
            elif not num_words:
                # Part of region name — but skip if it's a footnote superscript
                if not re.match(r"^\d+/?$", w_text):
                    region_words.append(w_text)

        region = re.sub(r"\s+\d+\s*$", "", " ".join(region_words)).strip()
        if not region:
            continue

        for w_orig in num_words:
            w_text = _strip_filler(w_orig["text"])
            val = _parse_number(w_text)
            x_center = (w_orig["x0"] + w_orig["x1"]) / 2.0
            attr = _assign_col(x_center)
            rows.append({
                "release_date":     release_date,
                "table_name":       table_name,
                "region":           region,
                "market_year":      market_year,
                "status":           status,
                "projection_month": projection_month,
                "attribute":        attr,
                "value":            val,
                "unit":             unit,
            })

    return rows


# ---------------------------------------------------------------------------
# Public parse functions
# ---------------------------------------------------------------------------

def parse_wasde_txt(txt_bytes: bytes, release_date: str) -> pd.DataFrame:
    """Parse a WASDE TXT file (1995–1999 era) into a tidy bronze DataFrame.

    Args:
        txt_bytes:    Raw bytes of the .txt file from S3.
        release_date: Release date string "YYYY-MM-DD" from the S3 partition key.

    Returns:
        DataFrame with the standard bronze WASDE schema.
    """
    text = txt_bytes.decode("utf-8", errors="replace")
    rows: list[dict] = []

    # TXT files have the same colon-delimited format as PDF Format A.
    # They contain multiple tables separated by ===== lines.
    # We process the whole document as one long colon page.
    rows = _parse_colon_page(text, release_date)

    return _to_dataframe(rows)


def parse_wasde_pdf_digital(pdf_bytes: bytes, release_date: str) -> pd.DataFrame:
    """Parse a digital WASDE PDF (2000–2026 era) into a tidy bronze DataFrame.

    Reads pages 7–29 (0-indexed), skipping narrative pages 0–6 and
    livestock/admin pages 30+. Auto-detects Format A (colon) vs Format B
    (columnar) per page.

    Args:
        pdf_bytes:    Raw PDF bytes from S3.
        release_date: Release date string "YYYY-MM-DD" from the S3 partition key.

    Returns:
        DataFrame with the standard bronze WASDE schema.
    """
    rows: list[dict] = []

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        total = len(pdf.pages)
        for page_idx in range(_SKIP_BEFORE, min(_SKIP_FROM, total)):
            page = pdf.pages[page_idx]
            text = page.extract_text() or ""
            text_clean = _strip_filler(text)

            # Only process pages that contain a "Supply and Use" table
            if "Supply and Use" not in text_clean:
                continue

            fmt = _detect_format(text_clean)
            try:
                if fmt == "colon":
                    page_rows = _parse_colon_page(text_clean, release_date)
                else:
                    page_rows = _parse_columnar_page(page, release_date)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Page %d parse error (%s) release=%s: %s",
                    page_idx + 1, fmt, release_date, exc,
                )
                page_rows = []

            rows.extend(page_rows)

    return _to_dataframe(rows)


def parse_wasde_pdf_scanned(
    textract_blocks: list[dict],
    release_date: str,
) -> pd.DataFrame:
    """Parse WASDE Textract LINE blocks (1973–1994 scanned era) into bronze.

    Reconstructs table rows from Textract LINE blocks by grouping on
    y-coordinate and treating the resulting text as colon-delimited Format A
    (the scanned era used the same printed layout as the early digital PDFs).

    Args:
        textract_blocks: List of Textract Block dicts (BlockType="LINE").
        release_date:    Release date string "YYYY-MM-DD".

    Returns:
        DataFrame with the standard bronze WASDE schema.
    """
    # Filter to LINE blocks only and sort by page + top y
    line_blocks = [
        b for b in textract_blocks
        if b.get("BlockType") == "LINE"
    ]
    line_blocks.sort(key=lambda b: (
        b.get("Page", 1),
        b.get("Geometry", {}).get("BoundingBox", {}).get("Top", 0),
    ))

    # Reconstruct text preserving page breaks
    current_page = None
    text_lines: list[str] = []
    for block in line_blocks:
        page_num = block.get("Page", 1)
        if current_page is not None and page_num != current_page:
            text_lines.append("")  # page break
        current_page = page_num
        text_lines.append(block.get("Text", ""))

    full_text = "\n".join(text_lines)
    rows = _parse_colon_page(full_text, release_date)
    return _to_dataframe(rows)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_SCHEMA_COLS = [
    "release_date",
    "table_name",
    "region",
    "market_year",
    "status",
    "projection_month",
    "attribute",
    "value",
    "unit",
]


def _to_dataframe(rows: list[dict]) -> pd.DataFrame:
    """Convert a list of row dicts to a typed DataFrame with the canonical schema."""
    if not rows:
        return pd.DataFrame(columns=_SCHEMA_COLS).astype(
            {"value": "float64"}
        )

    df = pd.DataFrame(rows, columns=_SCHEMA_COLS)
    df["value"] = pd.to_numeric(df["value"], errors="coerce")

    # Drop rows where region or attribute is empty
    df = df[df["region"].str.strip().astype(bool)]
    df = df[df["attribute"].str.strip().astype(bool)]

    # De-duplicate: keep last occurrence for each natural key
    # (duplicate pages can occur when a table spans two pages with repeated headers)
    key_cols = [
        "release_date", "table_name", "region",
        "market_year", "status", "projection_month", "attribute",
    ]
    df = df.drop_duplicates(subset=key_cols, keep="last")
    df = df.reset_index(drop=True)

    return df
