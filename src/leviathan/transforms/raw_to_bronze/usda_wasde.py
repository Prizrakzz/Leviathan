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
    "total supply":         "total_supply",
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
_SEP_RE = re.compile(r"^={5,}", re.MULTILINE)

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
# Format A / TXT parser (colon-delimited) — heading-based table detection
# ---------------------------------------------------------------------------

def _extract_attrs_from_header(header_lines: list[str]) -> list[str]:
    """Extract ordered attribute column names from colon-format header lines.

    Strategy: take the last two "candidate" header lines (those with ':' and
    at least two non-separator, non-empty parts), accumulate tokens column by
    column, normalize via ``_normalise_attr``, then append ``ending_stocks``
    if the word "Ending" appears anywhere in the header but isn't yet present.
    """
    candidate_lines: list[str] = []
    for line in header_lines:
        if ":" not in line or _SEP_RE.match(line.strip()):
            continue
        parts = line.split(":")
        non_empty = [
            p.strip() for p in parts
            if p.strip() and not re.match(r"^=+$", p.strip())
        ]
        if len(non_empty) >= 2:
            candidate_lines.append(line)

    if not candidate_lines:
        return []

    last_lines = candidate_lines[-2:] if len(candidate_lines) >= 2 else candidate_lines

    col_tokens: list[list[str]] = []
    for line in last_lines:
        parts = line.split(":")
        value_parts = parts[1:] if len(parts) > 1 else []
        while len(col_tokens) < len(value_parts):
            col_tokens.append([])
        for i, part in enumerate(value_parts):
            s = part.strip()
            if s and not re.match(r"^=+$", s):
                col_tokens[i].append(s)

    attrs: list[str] = []
    for tokens in col_tokens:
        if not tokens:
            continue
        joined = " ".join(tokens)
        joined = re.sub(r"-\s*", "", joined)           # "Produc- tion" → "Production"
        joined = re.sub(r"\s*\d+/\s*", " ", joined)   # strip footnote refs "2/"
        joined = re.sub(r"\s+", " ", joined).strip()
        attr = _normalise_attr(joined)
        if attr:
            attrs.append(attr)

    header_flat = " ".join(header_lines).lower()
    if "ending" in header_flat and "ending_stocks" not in attrs:
        attrs.append("ending_stocks")

    return attrs


def _extract_us_year_cols(header_lines: list[str]) -> list[tuple[str, str, str]]:
    """Extract (market_year, status, projection_month) for each US-table value column.

    US tables have years as column headers, items as row labels.  The header
    may span several lines and the last projected year may carry two months
    (December, January) as space-separated tokens in a single colon cell.
    """
    year_by_col: dict[int, tuple[str, str]] = {}
    month_by_col: dict[int, list[str]] = {}

    for line in header_lines:
        if ":" not in line or _SEP_RE.match(line.strip()):
            continue
        parts = line.split(":")
        for col_idx, part in enumerate(parts[1:]):   # skip col 0 (Item label)
            s = part.strip()
            if not s or re.match(r"^=+$", s):
                continue
            # Year pattern: "1992/93", "1993/94 (Est.)", "1994/95 Projections"
            my_m = re.match(
                r"(\d{4}/\d{2,4})\s*"
                r"(?:\(?(Est(?:imated)?\.?|Proj(?:ected)?\.?)\)?|Proj(?:ections?)?)?",
                s, re.IGNORECASE,
            )
            if my_m:
                raw = my_m.group(0)
                my, st = _parse_market_year_and_status(raw)
                if re.search(r"Proj", raw, re.IGNORECASE) and not st:
                    st = "Proj."
                year_by_col[col_idx] = (my, st)
                continue
            # Standalone status: "Est." alone
            if re.match(r"^Est", s, re.IGNORECASE):
                if col_idx in year_by_col:
                    year_by_col[col_idx] = (year_by_col[col_idx][0], "Est.")
                continue
            # Month names (may be multiple space-separated in one colon cell)
            months = re.findall(
                r"(January|February|March|April|May|June|July|August"
                r"|September|October|November|December)",
                s, re.IGNORECASE,
            )
            if months:
                month_by_col[col_idx] = [m.capitalize() for m in months]

    if not year_by_col:
        return []

    max_col = max(
        max(year_by_col),
        max(month_by_col) if month_by_col else 0,
    )
    result: list[tuple[str, str, str]] = []
    for i in range(max_col + 1):
        my, st = year_by_col.get(i, ("", ""))
        months = month_by_col.get(i, [])
        if months:
            for m in months:
                result.append((my, st, m))
        else:
            result.append((my, st, ""))
    return result


def _parse_world_table_data(
    data_lines: list[str],
    release_date: str,
    table_name: str,
    unit: str,
    attrs: list[str],
) -> list[dict]:
    """Parse a World-table data section into row dicts.

    Handles two sub-layouts found in WASDE Format A / TXT:

    * **Year-as-banner** (standard): ``: 1998/99`` banner lines appear before
      each group of region rows (``Region : v1 v2 ...``).
    * **Year-as-row** (summary tables): ``: World`` region banners appear before
      groups of year rows (``1998/99 : v1 v2 ...``), with commodity sub-headers
      like ``Oilseeds :`` setting context between groups.

    Both layouts are also compatible with plain standalone year lines (no
    leading ``:``) that appear in test fixtures and some scanned-era output.
    """
    rows: list[dict] = []
    market_year = ""
    status = ""
    projection_month = ""
    region_context = ""     # set by ': World' / ': United States' banners
    commodity_context = ""  # set by 'Oilseeds :' / 'Oilmeals :' sub-headers

    for line in data_lines:
        stripped = line.strip()
        if not stripped:
            continue

        # ------------------------------------------------------------------
        # Lines starting with ':' are context banners
        # ------------------------------------------------------------------
        if stripped.startswith(":"):
            content = stripped.lstrip(":").strip()
            if not content:
                continue

            # Year banner: ': 1998/99', ': 1999/00 (Est.)', ': 2000/01 (Proj.)'
            my_m = re.match(
                r"(\d{4}/\d{2,4})\s*"
                r"(?:\(?(Est(?:imated)?\.?|Proj(?:ected)?\.?)\)?)?\s*$",
                content, re.IGNORECASE,
            )
            if my_m:
                market_year, status = _parse_market_year_and_status(content)
                projection_month = ""
                continue

            # Month banner: ': December', ': January'
            pm_m = _PROJ_MONTH_RE.match(content)
            if pm_m:
                projection_month = pm_m.group(1).capitalize()
                continue

            # Region banner: ': World', ': United States' (no digits → region name)
            if not re.search(r"\d", content):
                region_context = re.sub(r"\s*\d+/?\s*$", "", content).strip()
                commodity_context = ""  # reset commodity on new region
            continue

        # ------------------------------------------------------------------
        # Lines without ':' may be standalone year banners or footnotes
        # ------------------------------------------------------------------
        if ":" not in line:
            my_m = re.match(
                r"^\s*(\d{4}/\d{2,4})\s*"
                r"(?:\(?(Est(?:imated)?\.?|Proj(?:ected)?\.?)\)?)?\s*$",
                stripped, re.IGNORECASE,
            )
            if my_m:
                market_year, status = _parse_market_year_and_status(my_m.group(0).strip())
                projection_month = ""
            continue

        # ------------------------------------------------------------------
        # Data rows: "Label : val1  val2  ..."
        # ------------------------------------------------------------------
        parts = line.split(":", 1)
        label_raw = parts[0].strip()
        values_raw = parts[1].strip() if len(parts) > 1 else ""

        if not label_raw:
            continue

        # Strip trailing footnote superscripts like " 3/" or " 5/"
        label = re.sub(r"\s+\d+/?\s*$", "", label_raw).strip()
        if not label:
            continue

        # Detect embedded projection-month suffix in region label before other
        # checks — e.g. "Argentina Dec" → region="Argentina", pm="December".
        # This pattern occurs on WASDE continuation pages where countries with
        # off-season harvests carry their own December/January marker.
        _MONTH_ABBREVS = {
            "jan": "January", "feb": "February", "mar": "March",
            "apr": "April",   "may": "May",       "jun": "June",
            "jul": "July",    "aug": "August",    "sep": "September",
            "oct": "October", "nov": "November",  "dec": "December",
        }
        embedded_m = re.search(
            r"\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.?\s*$",
            label, re.IGNORECASE,
        )
        if embedded_m:
            abbrev = embedded_m.group(1)[:3].lower()
            projection_month = _MONTH_ABBREVS.get(abbrev, embedded_m.group(1))
            label = label[: embedded_m.start()].strip()

        # Check whether the label is a year (year-as-row format)
        year_m = re.match(
            r"(\d{4}/\d{2,4})\s*"
            r"(?:\(?(Est(?:imated)?\.?|Proj(?:ected)?\.?)\)?)?\s*$",
            label, re.IGNORECASE,
        )
        # Check whether the label is a projection month (month-as-row format)
        month_m = _PROJ_MONTH_RE.match(label) if not year_m else None

        if year_m:
            market_year, status = _parse_market_year_and_status(label)
            projection_month = ""
            region = region_context
        elif month_m:
            projection_month = month_m.group(1).capitalize()
            region = region_context
        else:
            region = label

        # Extract numeric values from values_raw
        vals = [
            _parse_number(n)
            for n in re.findall(r"[\d,]+\.?\d*|-{1,2}", values_raw)
        ]

        if not vals:
            # No values → could be a commodity sub-header like "Oilseeds :"
            if not year_m and not month_m:
                commodity_context = label
            continue

        if not region or not market_year:
            continue

        full_table_name = (
            f"{table_name} - {commodity_context}"
            if commodity_context else table_name
        )

        for idx, val in enumerate(vals):
            attr = attrs[idx] if idx < len(attrs) else f"col_{idx}"
            rows.append({
                "release_date":     release_date,
                "table_name":       full_table_name,
                "region":           region,
                "market_year":      market_year,
                "status":           status,
                "projection_month": projection_month,
                "attribute":        attr,
                "value":            val,
                "unit":             unit,
            })

    return rows


def _parse_us_table_data(
    header_lines: list[str],
    data_lines: list[str],
    release_date: str,
    table_name: str,
    unit: str,
) -> list[dict]:
    """Parse a US-table data section (items as rows, years as columns).

    Extracts year/month column assignments from ``header_lines``, then emits
    one row per (item, year) combination.
    """
    year_cols = _extract_us_year_cols(header_lines)
    if not year_cols:
        return []

    rows: list[dict] = []
    current_unit = unit

    # Infer region from table name
    if "U.S." in table_name or "United States" in table_name:
        region = "United States"
    else:
        region = re.sub(
            r"\s+Supply and Use.*", "", table_name, flags=re.IGNORECASE
        ).strip()

    for line in data_lines:
        stripped = line.strip()
        if not stripped or _SEP_RE.match(stripped):
            continue
        # Inline unit line (no ':')
        if ":" not in line:
            u_m = re.search(
                r"(Million|Thousand|Short ton|metric ton|bushel|pound|bale|cwt)",
                line, re.IGNORECASE,
            )
            if u_m:
                current_unit = re.sub(r"\s+", " ", line.strip())
            continue

        parts = line.split(":", 1)
        item_raw = parts[0].strip()
        values_raw = parts[1].strip() if len(parts) > 1 else ""

        if not item_raw or not values_raw:
            continue

        item_raw = re.sub(r"\s+\d+/?\s*$", "", item_raw).strip()
        attribute = _normalise_attr(item_raw)
        if not attribute:
            continue

        vals = [
            _parse_number(n)
            for n in re.findall(r"[\d,]+\.?\d*|-{1,2}", values_raw)
        ]
        if not vals:
            continue

        for idx, val in enumerate(vals):
            if idx < len(year_cols):
                my, st, pm = year_cols[idx]
            else:
                my, st, pm = "", "", ""
            if not my:
                continue
            rows.append({
                "release_date":     release_date,
                "table_name":       table_name,
                "region":           region,
                "market_year":      my,
                "status":           st,
                "projection_month": pm,
                "attribute":        attribute,
                "value":            val,
                "unit":             current_unit,
            })

    return rows


def _parse_colon_table_v2(
    block_lines: list[str],
    release_date: str,
    table_name: str,
    unit: str,
) -> list[dict]:
    """Parse one colon-format table block into row dicts.

    Expected structure within ``block_lines``:
    ``heading lines → sep1 (=====) → header lines → sep2 (=====) → data lines → [sep3]``

    Dispatches to the World-table parser if header lines contain no year
    patterns (standard), or to the US-table parser otherwise.
    """
    sep_indices = [
        i for i, ln in enumerate(block_lines)
        if _SEP_RE.match(ln.strip())
    ]
    if len(sep_indices) < 2:
        return []

    sep1 = sep_indices[0]
    sep2 = sep_indices[1]
    header_lines = block_lines[sep1 + 1: sep2]

    data_end = sep_indices[-1] if len(sep_indices) >= 3 else len(block_lines)
    data_lines = block_lines[sep2 + 1: data_end]

    header_flat = " ".join(header_lines)
    if re.search(r"\d{4}/\d{2}", header_flat):
        # US-style: years appear as column headers
        return _parse_us_table_data(
            header_lines, data_lines, release_date, table_name, unit,
        )

    attrs = _extract_attrs_from_header(header_lines)
    return _parse_world_table_data(
        data_lines, release_date, table_name, unit, attrs,
    )


def _parse_colon_page(page_text: str, release_date: str) -> list[dict]:
    """Parse a full colon-format page (may contain multiple tables).

    Locates every ``Supply and Use`` heading that is followed by a separator
    line within five lines, treats the text from each heading to the next as
    one table block, and dispatches to ``_parse_colon_table_v2``.
    """
    rows: list[dict] = []
    lines = page_text.splitlines()

    # Find all heading lines: contain "Supply and Use" and are followed by
    # a separator (=====) within the next 5 lines.
    heading_indices: list[tuple[int, str, str]] = []  # (line_idx, table_name, unit)

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if re.search(r"Supply and Use", stripped, re.IGNORECASE):
            for j in range(i + 1, min(i + 6, len(lines))):
                if _SEP_RE.match(lines[j].strip()):
                    tname = re.sub(r"\s*\d+/?\s*$", "", stripped).strip()
                    tunit = _parse_unit(tname)
                    heading_indices.append((i, tname, tunit))
                    break

    if not heading_indices:
        return rows

    for idx, (start_i, tname, tunit) in enumerate(heading_indices):
        end_i = (
            heading_indices[idx + 1][0]
            if idx + 1 < len(heading_indices)
            else len(lines)
        )
        block_lines = lines[start_i: end_i]
        rows.extend(_parse_colon_table_v2(block_lines, release_date, tname, tunit))

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
