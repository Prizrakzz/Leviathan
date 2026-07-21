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
    "tion":                 "production",       # hyphen-split suffix "Produc-/tion" in scanned era
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
    # NB: the modern US oil/meal "Avg. Price" label drift is resolved by the
    # transposed-US parser's own EXPLICIT map (_US_ITEM_ALIASES), NOT here.  A
    # bare "avg. price" alias in this SHARED table is consumed only by the
    # greedy-prefix _normalise_attr on the colon-era US + World columnar paths
    # (the pre-2011 / World tables the byte-identical mandate protects) and is
    # dead for W1's goal -- so it is deliberately omitted (F2-avg-price finding).
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

# Y-coordinate tolerance for grouping Textract LINE blocks into visual rows (scanned era)
_SCANNED_Y_TOLERANCE = 0.003

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
    """Remove 'filler' tokens emitted by pdfplumber in Format B interleaved rows.

    The PDFMaker fragment-merge (``_merge_word_fragments``) can also GLUE a
    ``Filler`` token to the following word ("FillerMillion" for a "Million Pounds"
    unit banner), which a bare ``\\bfiller\\b`` boundary strip misses (there is no
    word boundary inside "FillerMillion").  A capital ``Filler`` immediately
    followed by another capital letter is that glued glyph-artifact, so it is
    stripped as a prefix too -- resolving the oil/meal unit to "Million Pounds"
    (F2 finding).  A standalone lower/upper "filler" word is handled by the first
    strip; the glued-prefix strip is deliberately narrow (capital ``Filler`` +
    following capital) so it can never mangle a legitimate word.
    """
    text = re.sub(r"\bfiller\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\bFiller(?=[A-Z])", "", text)
    return text.strip()


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

    last_lines = candidate_lines[-3:] if len(candidate_lines) >= 3 else candidate_lines

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


_SYNTHETIC_SEP = "=" * 70


def _colon_inject_data_section(lines: list[str]) -> list[str]:
    """Convert colon-free data rows in a scanned-era data section to colon format.

    1989-era WASDE PDFs have space-delimited rather than colon-delimited data
    rows because Textract OCR groups each visual row as a single LINE block.
    This function injects colons so that ``_parse_world_table_data`` can
    consume the rows normally.

    Patterns handled:

    * ``"World 3/ 143.84 477.35 ..."`` → ``"World 3/ : 143.84 : 477.35 : ..."``
      (mixed label + values on same line)
    * A pure-text label line immediately followed by a pure-numeric line →
      merged into ``"label : val1 : val2 : ..."``.  Covers the common case
      where Textract places the region name on one LINE block and the row
      values on the next.
    * A pure-numeric line immediately followed by a pure-text label line →
      merged.  Covers the rarer OCR artefact where Textract places the label
      below its own row values (observed for some rows in 1989-02 corn table).
    * Lines that already contain ``:`` are passed through unchanged.
    * Year banners, footnotes, and separator lines are passed through unchanged.
    """

    def _is_pure_num(tok: str) -> bool:
        return bool(re.match(r"^-?\d+\.?\d*$", tok))

    def _is_label_tok(tok: str) -> bool:
        # A "label" token contains letters OR is a bare footnote ref (e.g. "3/")
        return bool(re.search(r"[a-zA-Z]", tok) or re.match(r"^\d+/$", tok))

    # ---- Pass 1: classify each line ----------------------------------------
    # tag ∈ {'pass', 'mixed', 'text', 'nums'}
    tags: list[str] = []
    # (original_line, tokens_list, last_label_token_index)
    info: list[tuple[str, list[str], int]] = []

    for line in lines:
        s = line.strip()
        toks = s.split() if s else []

        # Empty / separator / already contains ':' → pass through unchanged
        if not s or _SEP_RE.match(s) or ":" in line:
            tags.append("pass")
            info.append((line, toks, -1))
            continue

        # Year banner (e.g. "1989/90 (Projected) 3/") → pass through
        if re.match(r"^\d{4}/\d{2,4}\b", s):
            tags.append("pass")
            info.append((line, toks, -1))
            continue

        # Footnote line (starts with "N/" e.g. "1/") or long descriptive text
        if re.match(r"^\d+/", s) or len(s) > 60:
            tags.append("pass")
            info.append((line, toks, -1))
            continue

        # Count pure-numeric tokens first so that lines like "135.6 823.5 ..."
        # are handled as 'nums' rather than falling into the no-letter check below.
        num_count = sum(1 for t in toks if _is_pure_num(t))

        if num_count == len(toks):
            if len(toks) >= 2:
                tags.append("nums")
            else:
                # Single-value fragment — can't reliably assign a region
                tags.append("pass")
            info.append((line, toks, -1))
            continue

        # No letters at all (e.g. "*******", "--------") → pass through
        if not re.search(r"[a-zA-Z]", s):
            tags.append("pass")
            info.append((line, toks, -1))
            continue

        # Find the last label token
        last_lbl = max(
            (j for j, t in enumerate(toks) if _is_label_tok(t)), default=-1
        )
        vals_after = toks[last_lbl + 1:] if last_lbl >= 0 else []

        if (
            last_lbl >= 0
            and len(vals_after) >= 2
            and all(_is_pure_num(t) for t in vals_after)
        ):
            # Mixed: label tokens followed by numeric value tokens
            tags.append("mixed")
            info.append((line, toks, last_lbl))
        else:
            # Pure text label or unrecognised layout → candidate region label
            tags.append("text")
            info.append((line, toks, -1))

    # ---- Pass 2: emit -------------------------------------------------------
    result: list[str] = []
    n = len(tags)
    skip: set[int] = set()

    def _next_real(start: int) -> int:
        """Index of next non-empty line after *start* (skips blank pass-lines)."""
        j = start
        while j < n and tags[j] == "pass" and not info[j][0].strip():
            j += 1
        return j

    for i in range(n):
        if i in skip:
            continue

        tag = tags[i]
        line, toks, lbl_end = info[i]

        if tag == "pass":
            result.append(line)

        elif tag == "mixed":
            vals = toks[lbl_end + 1:]
            label = " ".join(toks[: lbl_end + 1])
            result.append(label + " : " + " : ".join(vals))

        elif tag == "text":
            # Look ahead: merge with immediately following pure-numeric line
            j = _next_real(i + 1)
            if j < n and tags[j] == "nums":
                nums_toks = info[j][1]
                result.append(line.strip() + " : " + " : ".join(nums_toks))
                skip.add(j)
            else:
                result.append(line)

        elif tag == "nums":
            # Look ahead: merge with immediately following text label.
            # This handles the OCR artefact where Textract places the region
            # label below its own row values in Y-order.
            j = _next_real(i + 1)
            if j < n and tags[j] == "text":
                text_label = info[j][0].strip()
                result.append(text_label + " : " + " : ".join(toks))
                skip.add(j)
            else:
                # Orphan numerics with no adjacent label → pass through.
                # _parse_world_table_data will skip these (unavoidable data loss).
                result.append(line)

    return result


def _inject_scanned_seps(block_lines: list[str]) -> list[str]:
    """Inject synthetic ===== separators into a scanned-era block that lacks them.

    Scanned WASDE tables (1985–1994) were printed in the same colon-delimited
    Format A layout as the digital era but without the ===== horizontal rules.
    This function inserts two synthetic separators so that
    ``_parse_colon_table_v2`` can locate the header and data sections:

    * sep1: immediately after the heading line (block_lines[0])
    * sep2: before the first market-year banner or first numeric data line
    """
    SEP = _SYNTHETIC_SEP
    # Scan from line 1 onward to find where header lines end
    header_end = len(block_lines)  # fallback: treat all remaining lines as header
    for k in range(1, len(block_lines)):
        ln = block_lines[k].strip()
        if not ln:
            continue
        # Standalone market-year banner — allow trailing annotations/footnotes
        # e.g. "1991/92", "1989/90 (Projected) 3/" → data section starts here
        if _MY_RE.match(ln) or re.match(r"^\d{4}/\d{2,4}\b", ln):
            header_end = k
            break
        # Line with ':' where any post-label cell contains a digit → data row
        if ":" in ln:
            parts = ln.split(":")
            if any(re.search(r"\d", p) for p in parts[1:]):
                header_end = k
                break
    data_section = _colon_inject_data_section(block_lines[header_end:])
    return (
        [block_lines[0], SEP]
        + block_lines[1:header_end]
        + [SEP]
        + data_section
    )


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
                r"(?:\(?(Est(?:imated)?\.?|Proj(?:ected)?\.?)\)?)?"
                r"(?:\s+\d+/)?\s*$",
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


def _parse_colon_page(
    page_text: str, release_date: str, *, require_sep: bool = True
) -> list[dict]:
    """Parse a full colon-format page (may contain multiple tables).

    Locates every ``Supply and Use`` heading, treats the text from each heading
    to the next as one table block, and dispatches to ``_parse_colon_table_v2``.

    When ``require_sep=True`` (default), the heading must be followed by a
    separator line (=====) within five lines — matching the digital-era layout.
    When ``require_sep=False``, every heading is accepted unconditionally and
    synthetic separators are injected via ``_inject_scanned_seps`` so that the
    downstream parser can locate header vs data sections.
    """
    rows: list[dict] = []
    lines = page_text.splitlines()

    heading_indices: list[tuple[int, str, str]] = []  # (line_idx, table_name, unit)

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if re.search(r"Supply and Use", stripped, re.IGNORECASE):
            if not require_sep:
                tname = re.sub(r"\s*\d+/?\s*$", "", stripped).strip()
                tunit = _parse_unit(tname)
                heading_indices.append((i, tname, tunit))
            else:
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
        if not require_sep:
            block_lines = _inject_scanned_seps(block_lines)
        rows.extend(_parse_colon_table_v2(block_lines, release_date, tname, tunit))

    return rows


# ---------------------------------------------------------------------------
# Format B parser (columnar, bounding-box alignment)
# ---------------------------------------------------------------------------

def _merge_word_fragments(words: list[dict], *, max_gap: float = 1.0) -> list[dict]:
    """Glue same-line word FRAGMENTS back into words (the WASDE July-2026 PDFMaker class).

    Acrobat PDFMaker (wasde0726.pdf, creator 'Acrobat PDFMaker 26 for Word') emits header glyphs in
    text runs that pdfplumber's position-sorted word extractor splits into character clusters
    ('Beg|in|n|in|g' for 'Beginning') REGARDLESS of x_tolerance -- measured inter-fragment gaps are
    <= 0.06pt while a real space is ~2.5pt wide and column gaps are >= 13pt. Merging same-line
    neighbors closer than ``max_gap`` (1pt) is therefore a provable no-op on well-formed PDFs
    (Distiller-era words are always separated by at least one space width) and exactly reassembles
    the PDFMaker fragments. Live-caught at the BF-W2 step-21 dry-run: 742/1,718 rows quarantined as
    unknown_attribute because 'Beginning Stocks'/'Ending Stocks'/'Domestic Total' headers shredded."""
    out: list[dict] = []
    for w in sorted(words, key=lambda w: (round(w["top"] / 5) * 5, w["x0"])):
        prev = out[-1] if out else None
        if (prev is not None
                and abs(prev["top"] - w["top"]) < 3
                and -3.0 <= w["x0"] - prev["x1"] <= max_gap):   # small NEGATIVE gaps are kerning
            #                                                     overlaps ('Domest'+'ic' at -0.01pt);
            #                                                     real columns never overlap
            prev["text"] += w["text"]
            prev["x1"] = w["x1"]
            prev["bottom"] = max(prev["bottom"], w["bottom"])
        else:
            out.append(dict(w))
    return out


def _parse_columnar_page(page, release_date: str) -> list[dict]:
    """Parse a single pdfplumber Page object using bounding-box word extraction."""
    rows: list[dict] = []

    # Extract words with bounding boxes (fragment-merged: the PDFMaker header-shred class)
    words = _merge_word_fragments(page.extract_words(x_tolerance=5, y_tolerance=5))
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
# Format B (columnar) US-table parser  (W1: WASDE US-tables restoration)
#
# Modern digital WASDE PDFs emit NO "=====" separators, so US pages (10-16) fall
# through _detect_format -> "columnar" and were fed to _parse_columnar_page, which
# is hard-wired for WORLD geometry (regions-as-rows) and yields 0 rows on the
# TRANSPOSED US tables (items-as-rows, years-as-columns).  These functions parse
# the transposed layout off page.extract_words (fragment-merged) column-by-column.
# World pages keep the _parse_columnar_page path byte-identical -- ONLY pages whose
# heading STARTS with "U.S." + carry a year-column header are diverted here.
# ---------------------------------------------------------------------------

# Item-label -> canonical attribute for the transposed US tables.  This is an
# EXPLICIT, EXACT map (recon MISS #2): the generic greedy-prefix _normalise_attr
# silently collapses distinct US use-side lines onto core attributes ("Domestic &
# Residual" -> domestic_total, "Food, Feed & other Industrial" -> food_use), which
# would OVERWRITE the genuine core rows on the natural key.  Here, only CORE lines
# resolve to whitelist terms; every genuinely-new niche line falls to a clean
# snake_case slug that the silver 19-term gate quarantines (never mis-emitted).
_US_ITEM_ALIASES: dict[str, str] = {
    "area planted":            "planted_area",
    "planted":                 "planted_area",   # cotton renders bare "Planted" (Area header split)
    "planted area":            "planted_area",
    "area harvested":          "harvested_area",
    "harvested":               "harvested_area",
    "harvested area":          "harvested_area",
    "yield per harvested acre": "yield",
    "yield":                   "yield",
    "beginning stocks":        "beginning_stocks",
    "production":              "production",
    "imports":                 "imports",
    "supply, total":           "total_supply",
    "supply total":            "total_supply",
    "food":                    "food_use",
    "seed":                    "seed_use",
    "feed and residual":       "feed_residual",
    "feed":                    "feed",
    "domestic, total":         "domestic_total",
    "domestic total":          "domestic_total",
    "domestic use":            "domestic_total",
    "domestic":                "domestic_total",
    "exports":                 "exports",
    "exports, total":          "exports",         # rice/cotton line -> exports (recon step 7)
    "use, total":              "total_use",
    "use total":               "total_use",
    "ending stocks":           "ending_stocks",
    "crushings":               "crush",
    "crush":                   "crush",
    "residual":                "residual",
    "avg. farm price":         "avg_farm_price",
    "avg farm price":          "avg_farm_price",
    "avg. price":              "avg_farm_price",  # 2019+ oil/meal label drift
    "avg price":               "avg_farm_price",
}

# horizontal x-cutoff (pt) below which a line's leftmost word is an ITEM label; a
# line whose leftmost word sits to the right of this is a unit-context banner
# ("Million Acres", "Bushels") or footnote, never a data row.
_US_LABEL_MAX_X = 200.0
# max gap (pt) between a range's LOW num, its "-" separator, and its HIGH num; a
# real range prints "LOW - HIGH" at <~6pt internal gaps while a null "-" or a
# column break is >=~40pt away (columns are ~79pt apart).
_US_RANGE_GAP = 20.0

_US_MONTH_MAP: dict[str, str] = {}
for _full, _abbr in (
    ("January", "jan"), ("February", "feb"), ("March", "mar"), ("April", "apr"),
    ("May", "may"), ("June", "jun"), ("July", "jul"), ("August", "aug"),
    ("September", "sep"), ("October", "oct"), ("November", "nov"), ("December", "dec"),
):
    _US_MONTH_MAP[_full.lower()] = _full
    _US_MONTH_MAP[_abbr] = _full
_US_MONTH_MAP["sept"] = "September"

_US_NUM_RE = re.compile(r"^-?\d[\d,]*\.?\d*$")               # 2,993 | 44.5 | -0.04 | 0
_US_JOINED_RANGE_RE = re.compile(r"^([\d,]+\.?\d*)\s*-\s*([\d,]+\.?\d*)$")  # "7.00-8.20" (pre-merged)
# Range-era (2011-2015) SECONDARY sub-table year headers render REVERSED + status-
# GLUED: the soybean-oil/meal + corn sub-tables print "10/2009 .Est11/2010
# .Proj12/2011 .Proj12/2011" (a "SS/YYYY" end-suffix/start-year form with the
# "(Est.)"/"(Proj.)" marker fused as a prefix to the NEXT year).  The forward
# ^(\d{4})/(\d{2,4}) matcher misses these, so no sub-table opens and the secondary
# commodity's rows merge into and (via keep-last dedup) overwrite the primary on
# the natural key (F1 blocker).  This recognises the reversed+glued form.
_US_REVERSED_YEAR_RE = re.compile(
    r"^[.\s(]*"
    r"(?:(Est|Proj)[a-z]*\.?\s*)?"    # optional glued status prefix ".Est"/".Proj"
    r"(\d{2})/(\d{4})\b",             # SS/YYYY  ("10/2009" == marketing year 2009/10)
    re.IGNORECASE,
)
_US_HYPHENS = ("-", "--", "–", "—")
_US_UNIT_KW_RE = re.compile(
    r"\b(Acres|Bushels?|Pounds?|Tons?|Metric|Hundredweight|Bales?|Cents|cwt|Short|Thousand|Million)\b",
    re.IGNORECASE,
)
# A single ALL-CAPS commodity token ("SOYBEAN", "OIL", "LONG-GRAIN", "BARLEY").
_US_ALLCAPS_WORD_RE = re.compile(r"^[A-Z][A-Z0-9&/.\-]*$")
# A bare "(Est.)"/"(Proj.)" status marker token, possibly glue-prefixed with ".".
_US_STATUS_TOKEN_RE = re.compile(r"^[.(]?(?:Est|Proj)[a-z.)]*$", re.IGNORECASE)


def _us_month_full(token: str) -> str:
    return _US_MONTH_MAP.get(token.strip().rstrip(".").lower(), "")


def _us_commodity_banner(texts: list[str]) -> str | None:
    """Return the ALL-CAPS commodity phrase if this line is a sub-table banner.

    Handles the clean form ("SOYBEAN OIL", "CORN", "TOTAL RICE") AND the range-era
    glyph-shredded form where the reversed year header's status markers spill onto
    the banner line as trailing tokens ("BARLEY .Est .Proj .Proj" on the 2011-2015
    Sorghum/Barley/Oats page).  A leading run of all-caps tokens is the commodity;
    any remaining tokens must all be bare status markers, else this is not a banner.
    Returns ``None`` for a normal mixed-case data label ("Area Planted").
    """
    toks = [t for t in texts if t]
    if not toks:
        return None
    lead: list[str] = []
    i = 0
    # A commodity phrase is a run of ALL-CAPS words, allowing a bare "&" connector
    # ("MEDIUM & SHORT-GRAIN RICE"); it must contain at least one real all-caps word.
    while i < len(toks) and (_US_ALLCAPS_WORD_RE.match(toks[i]) or toks[i] == "&"):
        lead.append(toks[i])
        i += 1
    if not any(_US_ALLCAPS_WORD_RE.match(t) for t in lead):
        return None
    if any(not _US_STATUS_TOKEN_RE.match(t) for t in toks[i:]):
        return None
    banner = " ".join(lead).strip(" &")
    if len(banner) < 2 or "SUPPLY" in banner:
        return None
    return banner


def _match_reversed_us_year(token: str) -> tuple[str, str] | None:
    """Recognise a range-era reversed+glued year token -> ``(market_year, status)``.

    ``"10/2009"`` -> ``("2009/10", "")``; ``".Est11/2010"`` -> ``("2010/11", "Est.")``;
    ``".Proj12/2011"`` -> ``("2011/12", "Proj.")``.  Returns ``None`` for anything
    that is not this reversed ``SS/YYYY`` form (the forward ``YYYY/SS`` header is
    handled by the normal matcher, so the two never collide).
    """
    m = _US_REVERSED_YEAR_RE.match(token)
    if not m:
        return None
    raw_status, suffix, start = m.group(1), m.group(2), m.group(3)
    status = ""
    if raw_status:
        status = "Proj." if raw_status.lower().startswith("proj") else "Est."
    return f"{start}/{suffix}", status


def _is_num_word(text: str) -> bool:
    return bool(_US_NUM_RE.match(text))


def _extract_us_columns(word_group: list[dict]) -> list[dict]:
    """Parse a US year-column header line into ordered column descriptors.

    Each descriptor is ``{"my", "status", "month", "x0", "x1"}``.  Handles the
    year+status forms ``"2011/12"``, ``"2011/12 Proj."`` (separate tokens) and
    ``"2025/26Est."`` (concatenated, the oil/meal sub-table shape).  Returns a
    list only when >=2 year tokens are present (the transposed signature) so a
    single-year row-banner (the wheat by-class block) is never mistaken for one.
    """
    cols: list[dict] = []
    for w in sorted(word_group, key=lambda w: w["x0"]):
        t = _strip_filler(w["text"])
        if not t:
            continue
        ym = re.match(r"^(\d{4})/(\d{2,4})", t)
        rev = None if ym else _match_reversed_us_year(t)
        if ym:
            my, _st = _parse_market_year_and_status(t)
            status = ""
            if re.search(r"proj", t, re.IGNORECASE):
                status = "Proj."
            elif re.search(r"est", t, re.IGNORECASE):
                status = "Est."
            cols.append({"my": my, "status": status, "month": "",
                         "x0": w["x0"], "x1": w["x1"]})
        elif rev is not None:               # range-era reversed+glued year token
            my, status = rev
            cols.append({"my": my, "status": status, "month": "",
                         "x0": w["x0"], "x1": w["x1"]})
        elif cols and re.match(r"^\(?proj", t, re.IGNORECASE):
            cols[-1]["status"] = "Proj."
            cols[-1]["x1"] = w["x1"]
        elif cols and re.match(r"^\(?est", t, re.IGNORECASE):
            cols[-1]["status"] = "Est."
            cols[-1]["x1"] = w["x1"]
    return cols if len(cols) >= 2 else []


def _assign_us_months(cols: list[dict], word_group: list[dict]) -> None:
    """Attach each month token on the month-header line to its nearest column."""
    for w in word_group:
        mo = _us_month_full(_strip_filler(w["text"]))
        if not mo:
            continue
        xc = (w["x0"] + w["x1"]) / 2.0
        best = min(range(len(cols)),
                   key=lambda i: abs((cols[i]["x0"] + cols[i]["x1"]) / 2.0 - xc))
        cols[best]["month"] = mo


def _is_us_month_line(texts: list[str]) -> bool:
    toks = [t for t in texts if t]
    return bool(toks) and all(_us_month_full(t) for t in toks)


def _normalise_us_item(label: str) -> str:
    """Map a US-table item label to a canonical attribute via the EXPLICIT map.

    Unknown labels fall to a clean snake_case slug (NO greedy prefix) so the
    silver 19-term gate quarantines them rather than corrupting a core attribute.
    """
    key = (label or "").strip().lower()
    key = re.sub(r"\([^)]*\)", " ", key)      # drop unit tags "($/bu)", "(c/lb)", "(%)"
    key = re.sub(r"\d+/", " ", key)            # drop footnote refs "2/", "3/"
    key = re.sub(r"[*]+", " ", key)            # drop "*"/"**" acreage-source markers
    key = re.sub(r"\s+", " ", key).strip().rstrip(".").strip()
    if not key:
        return ""
    if key in _US_ITEM_ALIASES:
        return _US_ITEM_ALIASES[key]
    return re.sub(r"[^a-z0-9]+", "_", key).strip("_")


def _us_row_cells(word_group: list[dict]) -> tuple[str | None, list[dict]]:
    """Split a data line into (item_label, value cells) with LOW-HIGH range merge.

    Range values ("7.00 - 8.20") are recombined into ONE cell BEFORE column
    assignment (value=midpoint, low/high retained) -- otherwise the value-token
    stream mis-tokenizes the range into three cells and shifts every column.
    Each cell is ``{"value", "low", "high", "xc"}``; ``xc`` is the cell's x-center
    (the HIGH token's center for a range, since values are right-aligned).
    """
    ws = sorted(word_group, key=lambda w: w["x0"])
    texts = [_strip_filler(w["text"]) for w in ws]
    first_val = next((i for i, t in enumerate(texts)
                      if _is_num_word(t) or _US_JOINED_RANGE_RE.match(t)), None)
    if first_val is None:
        return (None, [])
    label = " ".join(t for t in texts[:first_val] if t).strip()
    vz = list(zip(ws[first_val:], texts[first_val:]))
    cells: list[dict] = []
    i, n = 0, len(vz)
    while i < n:
        w, t = vz[i]
        jr = _US_JOINED_RANGE_RE.match(t)
        if jr:  # defensive: a pre-merged "LOW-HIGH" single token
            lo, hi = _parse_number(jr.group(1)), _parse_number(jr.group(2))
            cells.append({"value": (lo + hi) / 2.0, "low": lo, "high": hi,
                          "xc": (w["x0"] + w["x1"]) / 2.0})
            i += 1
            continue
        if _is_num_word(t):
            if (i + 2 < n and vz[i + 1][1] in _US_HYPHENS and _is_num_word(vz[i + 2][1])
                    and (vz[i + 1][0]["x0"] - w["x1"]) <= _US_RANGE_GAP
                    and (vz[i + 2][0]["x0"] - vz[i + 1][0]["x1"]) <= _US_RANGE_GAP):
                lo, hi = _parse_number(t), _parse_number(vz[i + 2][1])
                hw = vz[i + 2][0]
                mid = (lo + hi) / 2.0 if (lo == lo and hi == hi) else float("nan")
                cells.append({"value": mid, "low": lo, "high": hi,
                              "xc": (hw["x0"] + hw["x1"]) / 2.0})
                i += 3
                continue
            cells.append({"value": _parse_number(t), "low": None, "high": None,
                          "xc": (w["x0"] + w["x1"]) / 2.0})
            i += 1
        elif t in _US_HYPHENS:  # standalone null cell (preserve column alignment)
            cells.append({"value": float("nan"), "low": None, "high": None,
                          "xc": (w["x0"] + w["x1"]) / 2.0})
            i += 1
        else:  # footnote / "*" marker between value columns
            i += 1
    return (label, cells)


# A unit-bearing parenthetical inside an item label ("($/bu)", "(c/lb)",
# "($/s.t.)", "($/cwt)", "(%)") overrides the accumulated quantity unit FOR THAT
# ROW -- price/yield lines carry their own unit tag (recon step 4/5).  A non-unit
# parenthetical ("(rough equiv.)") is ignored.
_US_LABEL_UNIT_RE = re.compile(r"\(([^)]*(?:\$|/|%|cwt)[^)]*)\)")


def _us_label_unit(label: str) -> str:
    m = _US_LABEL_UNIT_RE.search(label or "")
    return m.group(1).strip() if m else ""


def _us_subtable_name(sublabel: str) -> str:
    """Build a table_name from an all-caps commodity sub-banner ("SOYBEAN OIL")."""
    clean = re.sub(r"\s+", " ", sublabel).strip().title()
    return f"U.S. {clean} Supply and Use"


def _emit_us_subtable(sub: dict, release_date: str) -> list[dict]:
    """Emit bronze rows for one accumulated US sub-table.

    Column x-anchors are learned from the FULL rows (those with exactly N value
    cells span all N columns left-to-right); every row's cells are then assigned
    to the nearest anchor -- so sparse rows (a niche line printed in only some
    columns) land in the correct column instead of shifting.
    """
    cols = sub["cols"]
    n = len(cols)
    rows_cells = sub["rows_cells"]
    if n == 0 or not rows_cells:
        return []

    full = [cells for (_lbl, cells, _u) in rows_cells if len(cells) == n]
    if full:
        anchors = []
        for i in range(n):
            xs = sorted(cells[i]["xc"] for cells in full)
            anchors.append(xs[len(xs) // 2])
    else:
        anchors = [(c["x0"] + c["x1"]) / 2.0 for c in cols]

    out: list[dict] = []
    tname = sub["table_name"]
    for label, cells, unit in rows_cells:
        attribute = _normalise_us_item(label)
        if not attribute:
            continue
        row_unit = _us_label_unit(label) or unit   # label's own unit tag wins
        for cell in cells:
            ci = min(range(n), key=lambda i: abs(anchors[i] - cell["xc"]))
            col = cols[ci]
            if not col["my"]:
                continue
            out.append({
                "release_date":     release_date,
                "table_name":       tname,
                "region":           "United States",
                "market_year":      col["my"],
                "status":           col["status"],
                "projection_month": col["month"],
                "attribute":        attribute,
                "value":            cell["value"],
                "unit":             row_unit,
                "value_low":        cell["low"],
                "value_high":       cell["high"],
            })
    return out


def _parse_us_columnar_page(page, release_date: str) -> list[dict]:
    """Parse a separator-less US (transposed) columnar page into bronze rows.

    A page may carry several sub-tables of DIFFERING geometry: the wheat page has
    the main balance sheet PLUS a "by Class" block (classes-as-columns), soybeans
    has SOYBEANS + OIL + MEAL, feed-grain has FEED GRAINS + CORN, rice has total +
    long-grain.  Each proper transposed sub-table opens with a year-column header
    (>=2 market years on one line); the by-class block (single-year row banners)
    never opens one and is therefore skipped cleanly, yielding zero rows.
    """
    words = _merge_word_fragments(page.extract_words(x_tolerance=5, y_tolerance=5))
    if not words:
        return []

    from collections import defaultdict
    lines_by_y: dict[int, list[dict]] = defaultdict(list)
    for w in words:
        lines_by_y[round(w["top"] / 5) * 5].append(w)
    line_groups = [sorted(lines_by_y[y], key=lambda w: w["x0"]) for y in sorted(lines_by_y)]

    page_text = _strip_filler(page.extract_text() or "")
    page_heading = ""
    for line in page_text.splitlines():
        if "Supply and Use" in line:
            page_heading = re.sub(r"\s*\d+/?\s*$", "", line.strip()).strip()
            break
    page_unit = _parse_unit(page_heading)

    rows: list[dict] = []
    current: dict | None = None

    def _close() -> None:
        nonlocal current
        if current is not None:
            rows.extend(_emit_us_subtable(current, release_date))
        current = None

    for grp in line_groups:
        texts = [t for t in (_strip_filler(w["text"]) for w in grp) if t]
        if not texts:
            continue
        joined = " ".join(texts)

        # The bottom-of-page "Note:" / footnote block ends all tables. Stop here:
        # footnote prose carries stray digits (and even year-like tokens) that
        # would otherwise be mis-read as data rows or a spurious sub-table.
        if re.match(r"^Note\s*:", joined, re.IGNORECASE):
            _close()
            break

        # A "Supply and Use" heading (page heading OR the by-class sub-heading)
        # terminates any open sub-table; the by-class block opens no new one.
        if "Supply and Use" in joined:
            _close()
            continue

        cols = _extract_us_columns(grp)
        if cols:                     # new transposed sub-table
            _close()
            current = {"table_name": page_heading, "cols": cols,
                       "unit": page_unit or "", "rows_cells": [], "has_data": False}
            continue

        if current is None:
            continue

        if _is_us_month_line(texts):
            _assign_us_months(current["cols"], grp)
            continue

        leftmost_x0 = min(w["x0"] for w in grp if _strip_filler(w["text"]))

        # all-caps commodity sub-banner ("SOYBEAN OIL", "CORN", "BARLEY .Est ...") --
        # a HARD sub-table boundary.  Normally it arrives right after this sub-table's
        # year-column header (has_data False) and just NAMES the open table.  If it
        # arrives once data rows exist, an upstream sub-table boundary was missed
        # (an unrecognised/glyph-shredded year-header form, e.g. the interleaved-
        # Filler reversed years on the 2011-2015 Sorghum/Barley/Oats page); CLOSE the
        # current table so the new commodity's rows can never merge into and overwrite
        # it on the natural key (F1; the sorghum-vs-barley/oats contamination probe).
        banner = _us_commodity_banner(texts)
        if banner is not None and leftmost_x0 < _US_LABEL_MAX_X:
            if current["has_data"]:
                _close()
            else:
                current["table_name"] = _us_subtable_name(banner)
            continue

        # unit-context banner ("Million Acres", "Bushels") sits to the right
        if leftmost_x0 >= _US_LABEL_MAX_X:
            if _US_UNIT_KW_RE.search(joined):
                current["unit"] = joined
            continue

        # data row -- a real US item label is short; reject footnote/prose lines
        # that slipped through (defense-in-depth behind the "Note:" break).
        label, cells = _us_row_cells(grp)
        if not label or not cells:
            continue
        if len(label) > 50 or len(label.split()) > 7:
            continue
        current["rows_cells"].append((label, cells, current["unit"]))
        current["has_data"] = True

    _close()
    return rows


def _is_us_transposed_heading(heading: str) -> bool:
    """True when a columnar page heading marks a US-specific transposed table.

    The five US pages' headings START with "U.S." ("U.S. Wheat Supply and Use");
    the World tables ("World Wheat ...") and the combined summary pages ("World
    and U.S. Supply and Use for Grains") do NOT -- so World pages keep the
    _parse_columnar_page path byte-identical.
    """
    return bool(re.match(r"^\s*U\s*\.?\s*S\s*\.?\b", heading or "", re.IGNORECASE))


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
                    # First "Supply and Use" heading decides US-transposed vs World.
                    heading = next(
                        (ln.strip() for ln in text_clean.splitlines()
                         if "Supply and Use" in ln), "")
                    if _is_us_transposed_heading(heading):
                        page_rows = _parse_us_columnar_page(page, release_date)
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
    # Filter to LINE blocks only
    line_blocks = [
        b for b in textract_blocks
        if b.get("BlockType") == "LINE"
    ]

    # Group LINE blocks into visual rows by (page, Y-bucket).
    # Textract emits each text fragment as a separate LINE block; blocks at
    # the same printed Y coordinate must be sorted left-to-right and joined.
    from collections import defaultdict
    groups: dict[tuple[int, int], list[tuple[float, str]]] = defaultdict(list)
    for block in line_blocks:
        page_num = block.get("Page", 1)
        bb = block.get("Geometry", {}).get("BoundingBox", {})
        top = bb.get("Top", 0.0)
        left = bb.get("Left", 0.0)
        y_bucket = round(top / _SCANNED_Y_TOLERANCE)
        groups[(page_num, y_bucket)].append((left, block.get("Text", "")))

    # Emit one visual line per group, sorted by (page, y_bucket)
    text_lines: list[str] = []
    prev_page: int | None = None
    for (page_num, _y_bucket), fragments in sorted(groups.items()):
        if prev_page is not None and page_num != prev_page:
            text_lines.append("")  # page break
        prev_page = page_num
        fragments.sort(key=lambda t: t[0])  # sort by Left coordinate
        text_lines.append(" ".join(frag for _left, frag in fragments))

    # Orphan continuation merge: a line that starts with ':' and contains only
    # colons and numeric tokens is a wide-row continuation fragment; merge it
    # upward into the preceding line.
    _ORPHAN_RE = re.compile(r"^[\s:0-9.,\-/]+$")
    merged: list[str] = []
    for line in text_lines:
        if line.startswith(":") and _ORPHAN_RE.match(line) and merged:
            merged[-1] = merged[-1] + " " + line
        else:
            merged.append(line)

    full_text = "\n".join(merged)
    rows = _parse_colon_page(full_text, release_date, require_sep=False)
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
    # Additive (W1): USDA range-era ("LOW - HIGH") prices store the midpoint in
    # ``value`` and the printed bounds here (F036-style; None/NaN for point values).
    "value_low",
    "value_high",
]


def _to_dataframe(rows: list[dict]) -> pd.DataFrame:
    """Convert a list of row dicts to a typed DataFrame with the canonical schema."""
    if not rows:
        return pd.DataFrame(columns=_SCHEMA_COLS).astype(
            {"value": "float64", "value_low": "float64", "value_high": "float64"}
        )

    df = pd.DataFrame(rows, columns=_SCHEMA_COLS)
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df["value_low"] = pd.to_numeric(df["value_low"], errors="coerce")
    df["value_high"] = pd.to_numeric(df["value_high"], errors="coerce")

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
