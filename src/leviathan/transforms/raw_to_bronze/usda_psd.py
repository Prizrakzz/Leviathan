"""Bronze transform for USDA FAS Production, Supply & Distribution (PSD) data.

Converts the bulk psd_alldata.zip (ZIP containing a single CSV) from S3 raw
into a typed pandas DataFrame.  No commodity filtering at bronze — all
commodities and attributes are retained so that silver can apply
commodity-specific selections via Athena WHERE clause.

Key schema note
---------------
The ``month_code`` column (renamed from the raw ``Month`` column) encodes
the WASDE release month when this vintage was published:

    1  = June estimate
    2  = July estimate
    ...
    12 = May estimate  (for marketing years that start June 1)

This enables revision-surprise feature engineering at silver without
requiring a separate revision history table.
"""
from __future__ import annotations

import io
import re
import zipfile

import pandas as pd

from leviathan.common.logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Column rename map: raw CSV header → bronze snake_case name
# ---------------------------------------------------------------------------

_RENAME: dict[str, str] = {
    "Commodity_Code":        "commodity_code",
    "Commodity_Description": "commodity_desc",
    "Country_Code":          "country_code",
    "Country_Name":          "country_name",
    "Market_Year":           "market_year",
    "Month":                 "month_code",
    "Attribute_ID":          "attribute_id",
    "Attribute_Description": "attribute_desc",
    "Unit_ID":               "unit_id",
    "Unit_Description":      "unit_desc",
    "Value":                 "value",
}

_INT_COLS = frozenset({
    "commodity_code", "country_code", "market_year",
    "month_code", "attribute_id", "unit_id",
})


def _snake(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return re.sub(r"_+", "_", s).strip("_")


def extract_usda_psd(raw_bytes: bytes, release_date: str) -> pd.DataFrame:
    """Parse raw psd_alldata.zip bytes into a typed bronze DataFrame.

    Args:
        raw_bytes:    Raw bytes of the ZIP file as stored in S3.
        release_date: Download/release date in ``YYYY-MM-DD`` format, stored
                      as a metadata column to support revision diffing.

    Returns:
        DataFrame with bronze schema covering all commodities and attributes.

    Raises:
        FileNotFoundError: If the ZIP contains no CSV file.
        ValueError:        If the resulting DataFrame is empty.
    """
    with zipfile.ZipFile(io.BytesIO(raw_bytes)) as archive:
        csv_names = [n for n in archive.namelist() if n.lower().endswith(".csv")]
        if not csv_names:
            raise FileNotFoundError("No CSV found inside psd_alldata.zip")
        csv_name = csv_names[0]
        logger.info("Reading PSD CSV: %s", csv_name)
        with archive.open(csv_name) as f:
            df = pd.read_csv(f, low_memory=False)

    if df.empty:
        raise ValueError(f"PSD CSV '{csv_name}' is empty")

    # Apply the known rename map first, then snake-case any remaining columns.
    df = df.rename(columns={k: v for k, v in _RENAME.items() if k in df.columns})
    df.columns = [
        col if col in set(_RENAME.values()) else _snake(col)
        for col in df.columns
    ]

    # Type casts
    for col in _INT_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")

    if "value" in df.columns:
        df["value"] = pd.to_numeric(df["value"], errors="coerce")

    # Bronze metadata
    df["release_date"] = release_date
    df["source"] = "usda_psd"

    logger.info(
        "PSD extract complete  release=%s  rows=%d  commodities=%d",
        release_date,
        len(df),
        df["commodity_code"].nunique() if "commodity_code" in df.columns else -1,
    )
    return df
