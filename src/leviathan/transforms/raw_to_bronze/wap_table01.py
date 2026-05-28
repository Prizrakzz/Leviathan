"""WAP Table 01 → bronze/ Parquet transform (Phase 3, sources A and B).

Extracts Table 01 (World Crop Production Summary) from WAP PDFs using pdfplumber
and writes a long/tidy Parquet file to S3.

Each row in the output Parquet represents one (release_month, commodity,
row_label) combination with 19 country columns as float64 nullable.

Source B (Archive.org, pre-2002) PDFs have mirrored/reversed text on page 6 —
a PDF artifact from the FAS publication process.  The cell text is un-reversed
before parsing.  Narrative pages (0–5) are clean and do not need this fix.

Returns None (never raises) when pdfplumber cannot find the table or when the
extracted structure does not match the expected 19-column schema.  Callers
should log a warning and skip the bronze write for that release.
"""
from __future__ import annotations

import io
import logging
from typing import TYPE_CHECKING

import pandas as pd
import pdfplumber
from botocore.exceptions import ClientError

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

logger = logging.getLogger(__name__)

# Page index (0-based) that contains Table 01 in WAP PDFs.
_TABLE01_PAGE_IDX = 6

# Canonical commodity names in the table, mapped to snake_case slugs.
_COMMODITY_SLUG: dict[str, str] = {
    "WHEAT": "wheat",
    "COARSE GRAINS": "coarse_grains",
    "RICE": "rice",
    "RICE, MILLED": "rice",
    "TOTAL GRAINS": "total_grains",
    "OILSEEDS": "oilseeds",
    "COTTON": "cotton",
}

# Country column order in Table 01 (matches PDF column order left-to-right).
COUNTRY_COLUMNS: list[str] = [
    "world",
    "total_foreign",
    "us",
    "canada",
    "mexico",
    "eu27",
    "russia",
    "ukraine",
    "china",
    "india",
    "indonesia",
    "pakistan",
    "thailand",
    "argentina",
    "brazil",
    "australia",
    "south_africa",
    "turkey",
    "all_others",
]


# ---------------------------------------------------------------------------
# Text un-reversal helpers
# ---------------------------------------------------------------------------

def _unreverse_table_text(text: str) -> str:
    """Reverse each line in *text* to fix archive.org era page-6 PDF artifact.

    Archive.org WAP PDFs (pre-2002) store Table 01 text mirrored: pdfplumber
    reads "TABLE 1" as "1 ELBAT".  Reversing each line restores legibility.

    Args:
        text: Raw page text from pdfplumber, with lines separated by ``\\n``.
    """
    return "\n".join(line[::-1] for line in text.splitlines())


def _unreverse_table(
    raw_table: list[list[str | None]],
) -> list[list[str | None]]:
    """Reverse every non-None string cell in a pdfplumber 2D table array.

    Used for archive.org era (pre-2002) PDFs where cell text is reversed.
    """
    return [
        [cell[::-1] if isinstance(cell, str) else cell for cell in row]
        for row in raw_table
    ]


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _clean_cell(cell: str | None) -> str:
    """Return a stripped string, or '' for None."""
    if cell is None:
        return ""
    return str(cell).strip()


def _is_commodity_header(cell: str) -> bool:
    """Return True if *cell* matches a recognised Table 01 commodity name."""
    return cell.upper().strip() in _COMMODITY_SLUG


def _try_float(value: str) -> float | None:
    """Parse *value* as float (handling commas); return None on failure."""
    try:
        return float(value.replace(",", "").replace(" ", ""))
    except (ValueError, AttributeError):
        return None


def _is_year_label(label: str) -> bool:
    """Return True if *label* looks like a crop-year or month label.

    Matches patterns like '2008/09', '2009/10 prel.', '2010/11 proj.', 'May',
    'Jun', 'Est.', 'Proj.' etc — anything that is NOT a commodity header.
    """
    return not _is_commodity_header(label) and bool(label)


def _parse_packed_table01(
    col0_text: str,
    col1_text: str,
    release_month: str,
    raw_key: str,
) -> pd.DataFrame | None:
    """Parse the 'packed' Table 01 layout produced by modern WAP PDFs.

    pdfplumber collapses all commodity rows into col 0 (newline-separated
    labels) and col 1 (newline-separated space-delimited value rows).  The
    header line '---Million metric tons---' in col 1 is skipped.

    For each commodity block, the label column may contain one more label than
    value lines (an oldest historical year shown as a comparison reference
    without a corresponding numeric row).  When labels > values within a block,
    the *first* data label is skipped so the remaining labels align with values.
    """
    labels = [l.strip() for l in col0_text.splitlines() if l.strip()]
    value_lines = [
        l.strip()
        for l in col1_text.splitlines()
        if l.strip() and not l.strip().startswith("---")
    ]

    # Split labels into commodity blocks: each block starts at a commodity header.
    blocks: list[tuple[str, list[str]]] = []  # (commodity_slug, [data_labels])
    current_commodity: str | None = None
    current_labels: list[str] = []

    for label in labels:
        if _is_commodity_header(label):
            if current_commodity is not None:
                blocks.append((current_commodity, current_labels))
            current_commodity = _COMMODITY_SLUG[label.upper().strip()]
            current_labels = []
        elif current_commodity is not None:
            current_labels.append(label)

    if current_commodity is not None:
        blocks.append((current_commodity, current_labels))

    if not blocks:
        return None

    # Allocate value lines evenly across commodity blocks.
    n_commodities = len(blocks)
    n_values = len(value_lines)
    rows_per_commodity = n_values // n_commodities if n_commodities else 0

    if rows_per_commodity == 0:
        return None

    records: list[dict] = []
    value_idx = 0

    for commodity_slug, data_labels in blocks:
        # If block has more labels than value rows, skip leading (oldest) labels.
        if len(data_labels) > rows_per_commodity:
            data_labels = data_labels[len(data_labels) - rows_per_commodity:]

        for row_label in data_labels:
            if value_idx >= len(value_lines):
                break
            tokens = value_lines[value_idx].split()
            value_idx += 1

            if len(tokens) != len(COUNTRY_COLUMNS):
                continue

            record: dict = {
                "release_month": release_month,
                "raw_key": raw_key,
                "commodity": commodity_slug,
                "row_label": row_label,
            }
            for col, val in zip(COUNTRY_COLUMNS, tokens):
                record[col] = _try_float(val)

            records.append(record)

    if not records:
        return None

    df = pd.DataFrame(records)
    for col in COUNTRY_COLUMNS:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    return df


def _parse_table01_rows(
    raw_table: list[list[str | None]],
    release_month: str,
    raw_key: str,
) -> pd.DataFrame | None:
    """Convert a pdfplumber 2D table array into a long/tidy DataFrame.

    Handles two table layouts produced by different PDF generations:

    1. **Packed layout** (modern, 2003+): pdfplumber returns ~3 rows where
       col 0 contains all commodity/year labels stacked and col 1 contains all
       numeric values stacked.  Delegated to ``_parse_packed_table01``.

    2. **Row-per-row layout** (legacy / archive.org era): each data row is its
       own row in the 2D array with 20 cells (commodity/label + 19 countries).

    Returns None when no parseable data rows are found.
    """
    if not raw_table:
        return None

    # Detect packed layout: a data row where col 0 is multi-line and cols 2+
    # are all None indicates the packed format.
    for row in raw_table:
        if not row or len(row) < 2:
            continue
        col0 = _clean_cell(row[0])
        col1 = _clean_cell(row[1])
        rest_none = all(c is None for c in row[2:]) if len(row) > 2 else False
        if col0 and col1 and "\n" in col0 and rest_none:
            return _parse_packed_table01(col0, col1, release_month, raw_key)

    # Fall through to row-per-row parser (legacy layout)
    records: list[dict] = []
    current_commodity: str | None = None

    for row in raw_table:
        if not row:
            continue
        cells = [_clean_cell(c) for c in row]
        first = cells[0] if cells else ""

        if not first:
            continue

        if _is_commodity_header(first):
            current_commodity = _COMMODITY_SLUG[first.upper().strip()]
            continue

        if current_commodity is None:
            continue

        row_label = first
        country_values = cells[1:]

        if len(country_values) < len(COUNTRY_COLUMNS):
            continue

        record: dict = {
            "release_month": release_month,
            "raw_key": raw_key,
            "commodity": current_commodity,
            "row_label": row_label,
        }
        for col, val in zip(COUNTRY_COLUMNS, country_values[: len(COUNTRY_COLUMNS)]):
            record[col] = _try_float(val)

        records.append(record)

    if not records:
        return None

    df = pd.DataFrame(records)
    for col in COUNTRY_COLUMNS:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    return df


# ---------------------------------------------------------------------------
# Public extraction entry-point
# ---------------------------------------------------------------------------

def extract_table01(
    pdf_bytes: bytes,
    release_month: str,
    raw_key: str,
) -> pd.DataFrame | None:
    """Extract WAP Table 01 from *pdf_bytes* and return a long/tidy DataFrame.

    Handles both source eras:
    - Source A (2002+): clean table text, parsed directly.
    - Source B (pre-2002): cell text is reversed — un-reversal is applied
      before parsing.

    Returns None (with a WARNING log) when:
    - The PDF has fewer than 7 pages (no Table 01 page).
    - pdfplumber returns no table on page 6.
    - The extracted table structure cannot be matched to the expected schema.

    Never raises.  Callers should skip the bronze write on None and continue.

    Args:
        pdf_bytes:     Raw PDF bytes from S3.
        release_month: YYYY-MM string; determines archive.org era detection.
        raw_key:       S3 source key for lineage.
    """
    archiveorg_era = int(release_month[:4]) < 2002

    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            if len(pdf.pages) <= _TABLE01_PAGE_IDX:
                logger.warning(
                    "Table01 skip — fewer than %d pages  key=%s",
                    _TABLE01_PAGE_IDX + 1,
                    raw_key,
                )
                return None

            page = pdf.pages[_TABLE01_PAGE_IDX]
            raw_table = page.extract_table()

    except Exception as exc:  # noqa: BLE001
        logger.warning("pdfplumber failed on page 6  key=%s: %s", raw_key, exc)
        return None

    if not raw_table:
        logger.warning("Table01 not found on page 6  key=%s", raw_key)
        return None

    if archiveorg_era:
        raw_table = _unreverse_table(raw_table)

    df = _parse_table01_rows(raw_table, release_month, raw_key)
    if df is None:
        logger.warning("Table01 parsing yielded no rows  key=%s", raw_key)

    return df


# ---------------------------------------------------------------------------
# S3 persistence helpers
# ---------------------------------------------------------------------------

def table01_exists(s3_client: "S3Client", bucket: str, key: str) -> bool:
    """Return True if a table01.parquet already exists at *key* in *bucket*.

    Used as the idempotency gate before any extraction is attempted.
    """
    try:
        s3_client.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "404":
            return False
        raise


def write_table01(
    s3_client: "S3Client",
    bucket: str,
    key: str,
    df: pd.DataFrame,
) -> None:
    """Serialise *df* as snappy-compressed Parquet and write it to S3."""
    buf = io.BytesIO()
    df.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
    s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=buf.getvalue(),
        ContentType="application/octet-stream",
    )
