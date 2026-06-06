"""Bronze transform for CFTC Disaggregated Commitments of Traders (COT) TXT files.

Processes the futures-only disaggregated COT files published weekly by the
U.S. Commodity Futures Trading Commission.  Files are stored under:
    raw/production/source=cftc_cot/disagg_futures/backfill/fut_disagg_{year}.txt

The disaggregated COT breaks open interest into four trader categories:
  - Producer/Merchant/Processor/User  (commercial hedgers)
  - Swap Dealers
  - Managed Money                      ← primary ML feature
  - Other Reportables

Output schema
-------------
Long/tidy: one row per (report_date, leviathan_slug).

    report_date     str   YYYY-MM-DD (data as of Tuesday, released Friday)
    leviathan_slug  str   Leviathan contract identifier
    market_name     str   Original CFTC market string
    cftc_code       str   CFTC_Contract_Market_Code
    open_interest   int   Total open interest (all participants)
    mm_long         int   Managed money long contracts
    mm_short        int   Managed money short contracts
    mm_spread       int   Managed money spread contracts
    mm_net          int   mm_long − mm_short  (primary signal)
    mm_pct_oi       float mm_net / open_interest × 100 (normalised)
    source          str   "cftc_cot"

Market coverage
---------------
14 of 31 Leviathan contracts have CFTC disaggregated futures data
(US-listed contracts on CBOT, ICE US, CME).  Non-US exchanges (DCE,
Euronext MATIF, JSE, BMF) are not covered by CFTC.

Column selection
----------------
Only 8 of the 191 raw columns are retained; the remaining 183 are dropped
(percentage breakdowns, trader counts, old/other sub-categories, etc.).
"""
from __future__ import annotations

import io

import pandas as pd

from leviathan.common.logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Market name → Leviathan slug mapping
# ---------------------------------------------------------------------------

_MARKET_TO_SLUG: dict[str, str] = {
    "CORN - CHICAGO BOARD OF TRADE":                    "corn_cbot",
    "SOYBEANS - CHICAGO BOARD OF TRADE":                "soybeans_cbot",
    "SOYBEAN OIL - CHICAGO BOARD OF TRADE":             "soybean_oil_cbot",
    "SOYBEAN MEAL - CHICAGO BOARD OF TRADE":            "soybean_meal_cbot",
    "WHEAT-SRW - CHICAGO BOARD OF TRADE":               "soft_red_winter_wheat_cbot",
    "WHEAT-HRW - CHICAGO BOARD OF TRADE":               "hard_red_winter_wheat_kcbt",
    "WHEAT-HRSpring - MINNEAPOLIS GRAIN EXCHANGE":      "hard_red_spring_wheat_mgex",
    "WHEAT-HRSpring - MIAX FUTURES EXCHANGE":           "hard_red_spring_wheat_mgex",
    "COFFEE C - ICE FUTURES U.S.":                      "arabica_coffee",
    "COCOA - ICE FUTURES U.S.":                         "cocoa",
    "COTTON NO. 2 - ICE FUTURES U.S.":                  "cotton",
    "SUGAR NO. 11 - ICE FUTURES U.S.":                  "raw_sugar",
    "ROUGH RICE - CHICAGO BOARD OF TRADE":              "rough_rice_cbot",
    "FROZEN CONCENTRATED ORANGE JUICE - ICE FUTURES":   "frozen_orange_juice",
    "FCOJ-A - ICE FUTURES U.S.":                        "frozen_orange_juice",
}

# Raw columns we keep (8 of 191)
_KEEP_COLS: list[str] = [
    "Report_Date_as_YYYY-MM-DD",
    "Market_and_Exchange_Names",
    "CFTC_Contract_Market_Code",
    "Open_Interest_All",
    "M_Money_Positions_Long_All",
    "M_Money_Positions_Short_All",
    "M_Money_Positions_Spread_All",
    "FutOnly_or_Combined",
]

BRONZE_COLUMNS: list[str] = [
    "report_date",
    "leviathan_slug",
    "market_name",
    "cftc_code",
    "open_interest",
    "mm_long",
    "mm_short",
    "mm_spread",
    "mm_net",
    "mm_pct_oi",
    "source",
]


def parse_cot_txt(raw_bytes: bytes, year_label: str) -> pd.DataFrame:
    """Parse a CFTC disaggregated futures TXT file into long-format bronze.

    Args:
        raw_bytes:   Raw bytes of the ``.txt`` (CSV) file from S3.
        year_label:  Label used for logging, e.g. ``"2024"`` or ``"2006_2016"``.

    Returns:
        Long-format DataFrame with columns :data:`BRONZE_COLUMNS`.
        Only rows for Leviathan-mapped markets are retained.
        Empty DataFrame if no mapped markets are found.
    """
    df = pd.read_csv(
        io.BytesIO(raw_bytes),
        usecols=lambda c: c in _KEEP_COLS,
        low_memory=False,
    )

    # Validate we got futures-only rows
    if "FutOnly_or_Combined" in df.columns:
        fut_only = df["FutOnly_or_Combined"].astype(str).str.strip() == "FutOnly"
        if not fut_only.all():
            n_other = (~fut_only).sum()
            logger.warning(
                "COT %s: %d non-FutOnly rows found and dropped", year_label, n_other
            )
            df = df[fut_only].copy()

    # Normalise market name: strip whitespace
    df["Market_and_Exchange_Names"] = (
        df["Market_and_Exchange_Names"].astype(str).str.strip()
    )

    # Map to leviathan slugs — filter to our markets only
    df["leviathan_slug"] = df["Market_and_Exchange_Names"].map(_MARKET_TO_SLUG)
    df = df[df["leviathan_slug"].notna()].copy()

    if df.empty:
        logger.warning("COT %s: no mapped markets found", year_label)
        return pd.DataFrame(columns=BRONZE_COLUMNS)

    # Numeric coercion
    for col in ["Open_Interest_All", "M_Money_Positions_Long_All",
                "M_Money_Positions_Short_All", "M_Money_Positions_Spread_All"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # Derived columns
    df["mm_net"] = df["M_Money_Positions_Long_All"] - df["M_Money_Positions_Short_All"]
    df["mm_pct_oi"] = (df["mm_net"] / df["Open_Interest_All"] * 100).round(4)

    # Rename to bronze schema
    df = df.rename(columns={
        "Report_Date_as_YYYY-MM-DD":    "report_date",
        "Market_and_Exchange_Names":     "market_name",
        "CFTC_Contract_Market_Code":     "cftc_code",
        "Open_Interest_All":             "open_interest",
        "M_Money_Positions_Long_All":    "mm_long",
        "M_Money_Positions_Short_All":   "mm_short",
        "M_Money_Positions_Spread_All":  "mm_spread",
    })

    df["cftc_code"] = df["cftc_code"].astype(str).str.strip()
    df["source"]    = "cftc_cot"

    result = (
        df[BRONZE_COLUMNS]
        .sort_values(["report_date", "leviathan_slug"])
        .reset_index(drop=True)
    )

    slugs = sorted(result["leviathan_slug"].unique().tolist())
    dates = f"{result['report_date'].min()} – {result['report_date'].max()}"
    logger.info(
        "COT bronze %s: %d rows  %d slugs  dates=%s  slugs=%s",
        year_label, len(result), len(slugs), dates, slugs,
    )
    return result
