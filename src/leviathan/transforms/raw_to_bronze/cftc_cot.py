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
15 of 31 Leviathan contracts have CFTC disaggregated futures data
(US-listed contracts on CBOT, ICE US, CME).  Non-US exchanges (DCE,
Euronext MATIF, JSE, BMF, ICE Europe) are not covered by CFTC.
The join is keyed on ``CFTC_Contract_Market_Code`` (stable across market
renames); see the _CODE_TO_SLUG block for the 2026-08-21 re-key record.

Column selection
----------------
Only 8 of the 191 raw columns are retained; the remaining 183 are dropped
(percentage breakdowns, trader counts, old/other sub-categories, etc.).
"""
from __future__ import annotations

import csv
import io

import pandas as pd

from leviathan.common.logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# CFTC market code → Leviathan slug mapping (THE JOIN KEY since 2026-08-21)
# ---------------------------------------------------------------------------
#
# RE-KEYED FROM MARKET NAME TO CFTC_Contract_Market_Code (D-EC COT recovery, 2026-08-21).
# The name join was the silent-loss class: CFTC renames markets and the exact-string map reads the
# rename as no-data. Measured against every raw file era (weekly 20260814 + bulk 2006_2016 + annual
# 2018) before this edit:
#   * frozen_orange_juice: the old map's two name keys ("FROZEN CONCENTRATED ORANGE JUICE - ICE
#     FUTURES", "FCOJ-A - ICE FUTURES U.S.") matched ZERO rows in ANY era -- the raw name has been
#     "FRZN CONCENTRATED ORANGE JUICE - ICE FUTURES U.S." since 2006. 1,049 weeks silently absent
#     from silver since inception (tables.yaml's "FCOJ is absent" note was this defect, not a gap).
#   * wheat x3: "WHEAT - CHICAGO BOARD OF TRADE"/"- KANSAS CITY BOARD OF TRADE"/"- MINNEAPOLIS
#     GRAIN EXCHANGE" (2006-2013/14, ~1,190 rows) never matched the modern-name keys -- the W4b
#     legacy-name gap. Codes 001602/001612/001626 span every rename (incl. MGEX -> MIAX).
#   * canola_ice (135731, incl. its one week as "CANOLA OIL") and the CME USD Malaysian palm
#     contract (037021) were never mapped at all.
# Codes are the stable identity: every rename measured kept its code. NEAR-MISS TRAPS measured and
# deliberately NOT mapped: 002603 MINI CORN, 005603 MINI SOYBEANS, 00160F BLACK SEA WHEAT FINANCIAL,
# 037642 MALAYSIAN PALM OIL CALENDAR SWAP (a different contract from 037021).

_CODE_TO_SLUG: dict[str, str] = {
    "001602": "soft_red_winter_wheat_cbot",     # WHEAT / WHEAT-SRW - CBOT
    "001612": "hard_red_winter_wheat_kcbt",     # WHEAT - KCBT / WHEAT-HRW - CBOT
    "001626": "hard_red_spring_wheat_mgex",     # WHEAT - MGEX / WHEAT-HRSpring - MGEX / MIAX
    "002602": "corn_cbot",                      # CORN - CBOT
    "005602": "soybeans_cbot",                  # SOYBEANS - CBOT
    "007601": "soybean_oil_cbot",               # SOYBEAN OIL - CBOT
    "026603": "soybean_meal_cbot",              # SOYBEAN MEAL - CBOT
    "033661": "cotton",                         # COTTON NO. 2 - NYBOT / ICE
    "037021": "malaysian_crude_palm_oil_cme",   # USD MALAYSIAN CRUDE PALM OIL - CME
    "039601": "rough_rice_cbot",                # ROUGH RICE - CBOT
    "040701": "frozen_orange_juice",            # FRZN CONCENTRATED ORANGE JUICE - ICE
    "073732": "cocoa",                          # COCOA - NYBOT / ICE
    "080732": "raw_sugar",                      # SUGAR NO. 11 - NYBOT / ICE
    "083731": "arabica_coffee",                 # COFFEE C - NYBOT / ICE
    "135731": "canola_ice",                     # CANOLA (OIL) - ICE
}

# Every market NAME observed carrying a mapped code, across all measured eras. NOT a join input --
# purely the rename tripwire: a mapped code arriving under an unseen name is logged (INFO) so the
# next CFTC rename is visible in the run log instead of silent, and the map above stays the one
# producer of the join fact.
_KNOWN_NAMES: frozenset[str] = frozenset({
    "CORN - CHICAGO BOARD OF TRADE", "SOYBEANS - CHICAGO BOARD OF TRADE",
    "SOYBEAN OIL - CHICAGO BOARD OF TRADE", "SOYBEAN MEAL - CHICAGO BOARD OF TRADE",
    "WHEAT - CHICAGO BOARD OF TRADE", "WHEAT-SRW - CHICAGO BOARD OF TRADE",
    "WHEAT - KANSAS CITY BOARD OF TRADE", "WHEAT-HRW - CHICAGO BOARD OF TRADE",
    "WHEAT - MINNEAPOLIS GRAIN EXCHANGE", "WHEAT-HRSpring - MINNEAPOLIS GRAIN EXCHANGE",
    "WHEAT-HRSpring - MIAX FUTURES EXCHANGE",
    "COFFEE C - ICE FUTURES U.S.", "COFFEE C - NEW YORK BOARD OF TRADE",
    "COCOA - ICE FUTURES U.S.", "COCOA - NEW YORK BOARD OF TRADE",
    "COTTON NO. 2 - ICE FUTURES U.S.", "COTTON NO. 2 - NEW YORK BOARD OF TRADE",
    "SUGAR NO. 11 - ICE FUTURES U.S.", "SUGAR NO. 11 - NEW YORK BOARD OF TRADE",
    "ROUGH RICE - CHICAGO BOARD OF TRADE",
    "FRZN CONCENTRATED ORANGE JUICE - ICE FUTURES U.S.",
    "CANOLA - ICE FUTURES U.S.", "CANOLA OIL - ICE FUTURES U.S.",
    "USD MALAYSIAN CRUDE PALM OIL", "USD Malaysian Crude Palm Oil C - CHICAGO MERCANTILE EXCHANGE",
})

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

# ---------------------------------------------------------------------------
# Header handling
# ---------------------------------------------------------------------------
#
# The disaggregated "short format" is a fixed 191-column schema.  Two on-disk
# variants exist and both land in this parser:
#
#   * Headered  — the annual / 2006-2016 bulk ZIP files (backfill).  Line 1 is
#     the column header row.
#   * Headerless — the live weekly ``newcot`` TXT files (f_disagg.txt /
#     c_disagg.txt).  CFTC dropped the header row in 2026; line 1 is now the
#     first data row.
#
# We parse by *column name* (``usecols`` below), so a headerless file must have
# a header stitched back on before pandas sees it.  ``_CANONICAL_COLUMNS`` is
# the exact CFTC column order (verbatim from the published headered files); the
# import-time self-check below guarantees it stays aligned with ``_KEEP_COLS``.
_HEADER_MARKER = "Market_and_Exchange_Names"
_EXPECTED_FIELD_COUNT = 191

_CANONICAL_COLUMNS: list[str] = [
    "Market_and_Exchange_Names", "As_of_Date_In_Form_YYMMDD", "Report_Date_as_YYYY-MM-DD",
    "CFTC_Contract_Market_Code", "CFTC_Market_Code", "CFTC_Region_Code", "CFTC_Commodity_Code",
    "Open_Interest_All", "Prod_Merc_Positions_Long_All", "Prod_Merc_Positions_Short_All",
    "Swap_Positions_Long_All", "Swap__Positions_Short_All", "Swap__Positions_Spread_All",
    "M_Money_Positions_Long_All", "M_Money_Positions_Short_All",
    "M_Money_Positions_Spread_All", "Other_Rept_Positions_Long_All",
    "Other_Rept_Positions_Short_All", "Other_Rept_Positions_Spread_All",
    "Tot_Rept_Positions_Long_All", "Tot_Rept_Positions_Short_All",
    "NonRept_Positions_Long_All", "NonRept_Positions_Short_All", "Open_Interest_Old",
    "Prod_Merc_Positions_Long_Old", "Prod_Merc_Positions_Short_Old", "Swap_Positions_Long_Old",
    "Swap__Positions_Short_Old", "Swap__Positions_Spread_Old", "M_Money_Positions_Long_Old",
    "M_Money_Positions_Short_Old", "M_Money_Positions_Spread_Old",
    "Other_Rept_Positions_Long_Old", "Other_Rept_Positions_Short_Old",
    "Other_Rept_Positions_Spread_Old", "Tot_Rept_Positions_Long_Old",
    "Tot_Rept_Positions_Short_Old", "NonRept_Positions_Long_Old",
    "NonRept_Positions_Short_Old", "Open_Interest_Other", "Prod_Merc_Positions_Long_Other",
    "Prod_Merc_Positions_Short_Other", "Swap_Positions_Long_Other",
    "Swap__Positions_Short_Other", "Swap__Positions_Spread_Other",
    "M_Money_Positions_Long_Other", "M_Money_Positions_Short_Other",
    "M_Money_Positions_Spread_Other", "Other_Rept_Positions_Long_Other",
    "Other_Rept_Positions_Short_Other", "Other_Rept_Positions_Spread_Other",
    "Tot_Rept_Positions_Long_Other", "Tot_Rept_Positions_Short_Other",
    "NonRept_Positions_Long_Other", "NonRept_Positions_Short_Other",
    "Change_in_Open_Interest_All", "Change_in_Prod_Merc_Long_All",
    "Change_in_Prod_Merc_Short_All", "Change_in_Swap_Long_All", "Change_in_Swap_Short_All",
    "Change_in_Swap_Spread_All", "Change_in_M_Money_Long_All", "Change_in_M_Money_Short_All",
    "Change_in_M_Money_Spread_All", "Change_in_Other_Rept_Long_All",
    "Change_in_Other_Rept_Short_All", "Change_in_Other_Rept_Spread_All",
    "Change_in_Tot_Rept_Long_All", "Change_in_Tot_Rept_Short_All",
    "Change_in_NonRept_Long_All", "Change_in_NonRept_Short_All", "Pct_of_Open_Interest_All",
    "Pct_of_OI_Prod_Merc_Long_All", "Pct_of_OI_Prod_Merc_Short_All", "Pct_of_OI_Swap_Long_All",
    "Pct_of_OI_Swap_Short_All", "Pct_of_OI_Swap_Spread_All", "Pct_of_OI_M_Money_Long_All",
    "Pct_of_OI_M_Money_Short_All", "Pct_of_OI_M_Money_Spread_All",
    "Pct_of_OI_Other_Rept_Long_All", "Pct_of_OI_Other_Rept_Short_All",
    "Pct_of_OI_Other_Rept_Spread_All", "Pct_of_OI_Tot_Rept_Long_All",
    "Pct_of_OI_Tot_Rept_Short_All", "Pct_of_OI_NonRept_Long_All",
    "Pct_of_OI_NonRept_Short_All", "Pct_of_Open_Interest_Old", "Pct_of_OI_Prod_Merc_Long_Old",
    "Pct_of_OI_Prod_Merc_Short_Old", "Pct_of_OI_Swap_Long_Old", "Pct_of_OI_Swap_Short_Old",
    "Pct_of_OI_Swap_Spread_Old", "Pct_of_OI_M_Money_Long_Old", "Pct_of_OI_M_Money_Short_Old",
    "Pct_of_OI_M_Money_Spread_Old", "Pct_of_OI_Other_Rept_Long_Old",
    "Pct_of_OI_Other_Rept_Short_Old", "Pct_of_OI_Other_Rept_Spread_Old",
    "Pct_of_OI_Tot_Rept_Long_Old", "Pct_of_OI_Tot_Rept_Short_Old",
    "Pct_of_OI_NonRept_Long_Old", "Pct_of_OI_NonRept_Short_Old", "Pct_of_Open_Interest_Other",
    "Pct_of_OI_Prod_Merc_Long_Other", "Pct_of_OI_Prod_Merc_Short_Other",
    "Pct_of_OI_Swap_Long_Other", "Pct_of_OI_Swap_Short_Other", "Pct_of_OI_Swap_Spread_Other",
    "Pct_of_OI_M_Money_Long_Other", "Pct_of_OI_M_Money_Short_Other",
    "Pct_of_OI_M_Money_Spread_Other", "Pct_of_OI_Other_Rept_Long_Other",
    "Pct_of_OI_Other_Rept_Short_Other", "Pct_of_OI_Other_Rept_Spread_Other",
    "Pct_of_OI_Tot_Rept_Long_Other", "Pct_of_OI_Tot_Rept_Short_Other",
    "Pct_of_OI_NonRept_Long_Other", "Pct_of_OI_NonRept_Short_Other", "Traders_Tot_All",
    "Traders_Prod_Merc_Long_All", "Traders_Prod_Merc_Short_All", "Traders_Swap_Long_All",
    "Traders_Swap_Short_All", "Traders_Swap_Spread_All", "Traders_M_Money_Long_All",
    "Traders_M_Money_Short_All", "Traders_M_Money_Spread_All", "Traders_Other_Rept_Long_All",
    "Traders_Other_Rept_Short_All", "Traders_Other_Rept_Spread_All",
    "Traders_Tot_Rept_Long_All", "Traders_Tot_Rept_Short_All", "Traders_Tot_Old",
    "Traders_Prod_Merc_Long_Old", "Traders_Prod_Merc_Short_Old", "Traders_Swap_Long_Old",
    "Traders_Swap_Short_Old", "Traders_Swap_Spread_Old", "Traders_M_Money_Long_Old",
    "Traders_M_Money_Short_Old", "Traders_M_Money_Spread_Old", "Traders_Other_Rept_Long_Old",
    "Traders_Other_Rept_Short_Old", "Traders_Other_Rept_Spread_Old",
    "Traders_Tot_Rept_Long_Old", "Traders_Tot_Rept_Short_Old", "Traders_Tot_Other",
    "Traders_Prod_Merc_Long_Other", "Traders_Prod_Merc_Short_Other", "Traders_Swap_Long_Other",
    "Traders_Swap_Short_Other", "Traders_Swap_Spread_Other", "Traders_M_Money_Long_Other",
    "Traders_M_Money_Short_Other", "Traders_M_Money_Spread_Other",
    "Traders_Other_Rept_Long_Other", "Traders_Other_Rept_Short_Other",
    "Traders_Other_Rept_Spread_Other", "Traders_Tot_Rept_Long_Other",
    "Traders_Tot_Rept_Short_Other", "Conc_Gross_LE_4_TDR_Long_All",
    "Conc_Gross_LE_4_TDR_Short_All", "Conc_Gross_LE_8_TDR_Long_All",
    "Conc_Gross_LE_8_TDR_Short_All", "Conc_Net_LE_4_TDR_Long_All",
    "Conc_Net_LE_4_TDR_Short_All", "Conc_Net_LE_8_TDR_Long_All", "Conc_Net_LE_8_TDR_Short_All",
    "Conc_Gross_LE_4_TDR_Long_Old", "Conc_Gross_LE_4_TDR_Short_Old",
    "Conc_Gross_LE_8_TDR_Long_Old", "Conc_Gross_LE_8_TDR_Short_Old",
    "Conc_Net_LE_4_TDR_Long_Old", "Conc_Net_LE_4_TDR_Short_Old", "Conc_Net_LE_8_TDR_Long_Old",
    "Conc_Net_LE_8_TDR_Short_Old", "Conc_Gross_LE_4_TDR_Long_Other",
    "Conc_Gross_LE_4_TDR_Short_Other", "Conc_Gross_LE_8_TDR_Long_Other",
    "Conc_Gross_LE_8_TDR_Short_Other", "Conc_Net_LE_4_TDR_Long_Other",
    "Conc_Net_LE_4_TDR_Short_Other", "Conc_Net_LE_8_TDR_Long_Other",
    "Conc_Net_LE_8_TDR_Short_Other", "Contract_Units", "CFTC_Contract_Market_Code_Quotes",
    "CFTC_Market_Code_Quotes", "CFTC_Commodity_Code_Quotes", "CFTC_SubGroup_Code",
    "FutOnly_or_Combined",
]

# Fail fast at import time if the canonical schema ever drifts out of sync with
# the columns we actually select — a misaligned header would silently corrupt
# every downstream value (wrong physical column mapped to each name).
if len(_CANONICAL_COLUMNS) != _EXPECTED_FIELD_COUNT:
    raise RuntimeError(
        f"_CANONICAL_COLUMNS has {len(_CANONICAL_COLUMNS)} entries, "
        f"expected {_EXPECTED_FIELD_COUNT}"
    )
if _CANONICAL_COLUMNS[0] != _HEADER_MARKER:
    raise RuntimeError("_CANONICAL_COLUMNS[0] must be the header marker column")
_missing_keep = [c for c in _KEEP_COLS if c not in _CANONICAL_COLUMNS]
if _missing_keep:
    raise RuntimeError(f"_KEEP_COLS not covered by _CANONICAL_COLUMNS: {_missing_keep}")

_CANONICAL_HEADER = ",".join(_CANONICAL_COLUMNS)


def _ensure_header(raw_bytes: bytes) -> bytes:
    """Return *raw_bytes* guaranteed to start with a column header row.

    Headered files (annual / bulk backfill) are returned unchanged.  Headerless
    files (live weekly ``newcot`` TXT) get the canonical CFTC header prepended.

    Fails closed if a headerless first row does not have exactly
    :data:`_EXPECTED_FIELD_COUNT` fields — refusing to stitch on a header that
    would misalign the columns (schema drift, truncation, or a wrong payload).
    """
    if not raw_bytes:
        return raw_bytes

    first_line = raw_bytes.split(b"\n", 1)[0].decode("utf-8", errors="replace").rstrip("\r")
    if _HEADER_MARKER in first_line:
        return raw_bytes  # already headered

    n_fields = len(next(csv.reader([first_line])))
    if n_fields != _EXPECTED_FIELD_COUNT:
        raise ValueError(
            f"Headerless COT file has {n_fields} fields on the first row, "
            f"expected {_EXPECTED_FIELD_COUNT}; refusing to prepend the canonical "
            "header (possible schema drift or wrong payload)."
        )
    return _CANONICAL_HEADER.encode("utf-8") + b"\n" + raw_bytes


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
    # Weekly newcot files are headerless (CFTC dropped the header row in 2026);
    # stitch the canonical header back on so the by-name column selection works.
    raw_bytes = _ensure_header(raw_bytes)

    df = pd.read_csv(
        io.BytesIO(raw_bytes),
        usecols=lambda c: c in _KEEP_COLS,
        # THE JOIN KEY MUST BE READ AS TEXT: CFTC codes carry leading zeros ("002602", "040701")
        # and pandas' numeric inference strips them, which would miss every _CODE_TO_SLUG key.
        # (Alphanumeric codes like 00160F would mask this on full files by forcing object dtype --
        # a small or filtered file without one reads the column numeric, so the dtype is pinned.)
        dtype={"CFTC_Contract_Market_Code": str},
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

    # Normalise the two identity columns: strip whitespace
    df["Market_and_Exchange_Names"] = (
        df["Market_and_Exchange_Names"].astype(str).str.strip()
    )
    df["CFTC_Contract_Market_Code"] = (
        df["CFTC_Contract_Market_Code"].astype(str).str.strip()
    )

    # Map to leviathan slugs BY CFTC CODE — filter to our markets only. The code survives every
    # market rename (measured: FCOJ, the 2013/14 wheat renames, MGEX->MIAX, CANOLA OIL->CANOLA);
    # the name join this replaces silently lost 1,049 FCOJ weeks to a rename-class mismatch.
    df["leviathan_slug"] = df["CFTC_Contract_Market_Code"].map(_CODE_TO_SLUG)
    df = df[df["leviathan_slug"].notna()].copy()

    # The rename tripwire: a mapped code under a name we have never seen is tomorrow's rename,
    # caught in the log today instead of read as no-data in three years.
    unseen = df.loc[~df["Market_and_Exchange_Names"].isin(_KNOWN_NAMES),
                    ["CFTC_Contract_Market_Code", "Market_and_Exchange_Names"]].drop_duplicates()
    for code, name in unseen.itertuples(index=False):
        logger.info("COT %s: mapped code %s arrived under a NEW market name %r "
                    "(join unaffected -- code-keyed; add the name to _KNOWN_NAMES)",
                    year_label, code, name)

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
