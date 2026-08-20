"""Bronze transform for the World Bank Pink Sheet (monthly commodity prices).

SILVER-F023 carried 15 of the workbook's 71 monthly series. SILVER-F063 (the SERIES WIDENING,
2026-08-20) carries 37, and -- more importantly -- makes the OTHER 34 an explicit, checked-in
REFUSAL rather than an accident. This is the same projection-failure class as the PSD 13-of-63
census: a producer that quietly projects a narrow slice of a wide source leaves the rest dark, and
nothing in the pipeline ever says so.

Source format
-------------
Excel workbook, sheet "Monthly Prices" (header on row 5, index=4; units on row 6). Column 0 holds
dates in ``YYYYMXX`` format (e.g. ``"1960M01"``). MEASURED 2026-08-20 against BOTH raw releases held
in S3 (``release=2026M05`` and ``release=2026M07``): 72 columns = 1 date + 71 price series, and the
71 header strings are BYTE-IDENTICAL between the two releases.

Disposition (measured, not assumed)
-----------------------------------
Every one of the 71 source series is dispositioned exactly once:

  * 37 are KEPT -- see :data:`_SERIES_PATTERNS`;
  * 34 are REFUSED with a written reason -- see :data:`_REFUSED_SERIES`.

The governing rule for the widening is ONE PRICE LEG PER GRAPH NODE. A series is kept when it
prices a node that exists in ``configs/graphrag/commodity_hierarchy.yaml`` (a contract, a
context_commodity) or a slice in ``configs/graphrag/driver_slices.yaml``, and when no already-kept
column prices that same node. That rule is what refuses Crude oil average/Dubai/WTI (Brent is the
kept crude leg), Rice Thai 25%/A.1/Viet-5% (Thai 5% is the kept rice leg), Rubber TSR20 (RSS3 is
the kept rubber leg, with 3x the history), and four of the five base metals. It is also what KEEPS
pairs that look redundant but are not: HRW/SRW wheat are two distinct contract nodes; US/EU natural
gas price two distinct ammonia-feedstock markets; world/EU/US sugar are one dumping price and two
policy-administered prices (the wedge IS the ``import_quota_trq`` / ``subsidy`` signal); groundnuts
and groundnut oil are seed and crush product.

Two target series named in the widening brief DO NOT EXIST in this workbook and are refused on
measurement, not opinion: **copra** and **olive oil**. ``olive_oil`` is a live context_commodity
node with no Pink Sheet leg; that is a real coverage gap, and it belongs in a gap register rather
than in a fabricated column.

Header-drift instrument
-----------------------
:func:`_match_columns` now reports any workbook header claimed by NEITHER a kept pattern NOR the
refusal table. That warning is the durable fix for the projection-failure class: when the World
Bank adds a 72nd series, the log says so instead of the series silently never existing.

Output schema
-------------
Long/tidy format:  (release_ym, date, series_name, value_usd, source)

Bronze ``series_name`` carries the SOURCE unit (``sugar_world_usd_kg``); the silver column carries
the CONTRACT unit (``raw_sugar_world_usd_t``). The kg->tonne scaling is an explicit, tested rule in
``bronze_to_silver/pink_sheet.py``; it is never applied here.
"""
from __future__ import annotations

import io
from typing import Sequence

import pandas as pd

from leviathan.common.logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# KEPT: substring patterns -> canonical bronze series names (37 series).
#
# Each pattern must match EXACTLY ONE column, and no two patterns may claim the SAME column
# (see ``_match_columns``). For a REQUIRED series (all 37 are required) a missing, ambiguous or
# double-claimed header FAILS the extract -- a disappeared header must never publish a silently
# narrowed table.
#
# Patterns were resolved against the measured 2026M07 header list; every one resolves 1:1 and the
# 37 claims are disjoint (pinned by tests/unit/test_transforms_pink_sheet_widening.py).
# ---------------------------------------------------------------------------
_SERIES_PATTERNS: dict[str, str] = {
    # -- fertilizer + energy (SILVER-F010 original six) ----------------------
    "urea":                "urea_e_europe_bulk_spot_usd_mt",
    "dap":                 "dap_spot_usd_mt",
    "potassium chloride":  "potassium_chloride_std_usd_mt",
    "natural gas, us":     "natural_gas_us_usd_mmbtu",
    "natural gas, europe": "natural_gas_europe_usd_mmbtu",
    "phosphate rock":      "phosphate_rock_usd_mt",
    # -- commodity prices (SILVER-F023 restoration) --------------------------
    "crude oil, brent":    "crude_oil_brent_usd_bbl",
    "soybeans":            "soybeans_usd_mt",
    "soybean oil":         "soybean_oil_usd_mt",
    "soybean meal":        "soybean_meal_usd_mt",
    "palm oil":            "palm_oil_usd_mt",
    "sugar, world":        "sugar_world_usd_kg",
    "wheat, us hrw":       "wheat_us_hrw_usd_mt",
    "wheat, us srw":       "wheat_us_srw_usd_mt",
    "rapeseed oil":        "rapeseed_oil_usd_mt",
    # -- SILVER-F063 (a): pricing legs for D15 CONTEXT_COMMODITY nodes -------
    # Each of these quantifies a node in commodity_hierarchy.context_commodities that previously
    # had narrative coverage and NO price at all.
    "coconut oil":         "coconut_oil_usd_mt",        # node: coconut
    "groundnuts":          "groundnuts_usd_mt",         # node: peanut (the seed)
    "groundnut oil":       "groundnut_oil_usd_mt",      # node: peanut (the crush product)
    "palm kernel oil":     "palm_kernel_oil_usd_mt",    # node: palm_kernel
    "fish meal":           "fish_meal_usd_mt",          # node: fish_meal / marine_protein_fishmeal
    "sunflower oil":       "sunflower_oil_usd_mt",      # node: sunflower_oil / sunflower_oil_balance
    "barley":              "barley_usd_mt",             # node: barley / feed_grain_substitution
    "sorghum":             "sorghum_usd_mt",            # node: sorghum / feed_grain_substitution
    "orange":              "orange_usd_kg",             # node: fresh_citrus (FRESH FRUIT, not FCOJ)
    # -- SILVER-F063 (b): benchmarks that quantify EXISTING contract nodes ---
    "cotton, a index":     "cotton_a_index_usd_kg",     # node: cotton (contract)
    "rubber, rss3":        "rubber_rss3_usd_kg",        # node: natural_rubber (slice)
    "coffee, arabica":     "coffee_arabica_usd_kg",     # node: arabica_coffee (contract)
    "coffee, robusta":     "coffee_robusta_usd_kg",     # node: robusta_coffee (contract)
    "cocoa":               "cocoa_usd_kg",              # node: cocoa (contract)
    "rice, thai 5%":       "rice_thai_5pct_usd_mt",     # node: rough_rice_cbot / rice
    "maize":               "maize_usd_mt",              # node: corn_cbot + the 3 maize contracts
    "sugar, eu":           "sugar_eu_usd_kg",           # node: import_quota_trq / subsidy wedge
    "sugar, us":           "sugar_us_usd_kg",           # node: us_farm_program / import_quota_trq
    "beef":                "beef_usd_kg",               # node: cattle_cycle_herd_size / cattle_on_feed
    "chicken":             "chicken_usd_kg",            # node: broiler_economics
    # -- SILVER-F063 (c): fertilizer chain completion + macro context --------
    "tsp":                 "tsp_usd_mt",                # node: fertilizer (the 3rd phosphate product)
    "copper":              "copper_usd_mt",             # node: metals (macro_context, priority=context)
}

# The governed series whose absence/ambiguity is FATAL to the extract (all 37).
_REQUIRED_SERIES: frozenset[str] = frozenset(_SERIES_PATTERNS.values())

# ---------------------------------------------------------------------------
# REFUSED: exact workbook header -> written reason (34 series).
#
# Keyed by the EXACT header string as measured 2026-08-20 (compared after ``.strip()``), NOT by
# substring -- substring matching on this table would be its own trap ("Platinum" contains "tin").
#
# This table has two jobs. It is the disposition record a reviewer reads to see that no series was
# forgotten, and it is the reference set for the header-drift warning: a workbook column that is
# neither claimed nor listed here is a NEW World Bank series, and the log says so.
# ---------------------------------------------------------------------------
_REFUSED_SERIES: dict[str, str] = {
    # -- same node already priced by a kept leg (one leg per node) -----------
    "Crude oil, average":  "same node as the kept Brent leg (driver slice `crude`); a second crude "
                           "benchmark adds no ag signal and the Brent-WTI spread is not an ag question",
    "Crude oil, Dubai":    "same node as the kept Brent leg",
    "Crude oil, WTI":      "same node as the kept Brent leg (US domestic benchmark)",
    "Natural gas index":   "composite of US/Europe/Japan gas; the two ammonia-feedstock legs that "
                           "actually price urea (US, Europe) are kept individually",
    "Rice, Thai 25% ":     "grade variant of the kept Rice, Thai 5% leg; no separate node",
    "Rice, Thai A.1":      "grade variant of the kept Rice, Thai 5% leg; no separate node",
    "Rice, Viet Namese 5%": "origin variant of the kept Rice, Thai 5% leg; no separate node",
    "Rubber, TSR20 **":    "same node as the kept Rubber, RSS3 leg (`natural_rubber` slice names "
                           "both). RSS3 is kept for history: 798/798 months from 1960-01 vs TSR20's "
                           "330/798 from 1999-01, and a 5-yr z from 1962 vs 2004",
    "Aluminum":            "`metals` is ONE macro_context slice; copper is the kept leg for it",
    "Iron ore, cfr spot":  "`metals` is ONE macro_context slice; copper is the kept leg for it",
    "Nickel":              "`metals` is ONE macro_context slice; copper is the kept leg for it",
    "Zinc":                "`metals` is ONE macro_context slice; copper is the kept leg for it",
    # -- no node anywhere in the graph (the corpus-boundary class) -----------
    "Coal, Australian":    "no node: no coal contract, context_commodity or driver slice",
    "Coal, South African **": "no node: no coal contract, context_commodity or driver slice",
    "Liquefied natural gas, Japan": "no node: Japanese LNG feeds no ammonia plant this desk models",
    "Tea, avg 3 auctions": "no node: tea appears in NO contract, NO complex, NO group (the "
                           "`tropicals` group is arabica/robusta/cocoa/orange_juice) and NO driver "
                           "slice. Not desk-relevant; refused on the graph, not on taste",
    "Tea, Colombo":        "no node (see Tea, avg 3 auctions)",
    "Tea, Kolkata":        "no node (see Tea, avg 3 auctions)",
    "Tea, Mombasa":        "no node (see Tea, avg 3 auctions)",
    "Banana, Europe":      "no node: banana is neither a contract nor a context_commodity; "
                           "`fresh_citrus` is citrus, not banana",
    "Banana, US":          "no node (see Banana, Europe)",
    "Lamb **":             "no node: the livestock slices name cattle, hogs and broilers; no sheep",
    "Shrimps, Mexican":    "no node: `marine_protein_fishmeal` is FEED protein (anchovy -> fishmeal), "
                           "not shellfish for human consumption",
    "Tobacco, US import u.v.": "no node: not a modelled commodity",
    "Logs, Cameroon":      "no node: timber is outside the ag corpus boundary",
    "Logs, Malaysian":     "no node: timber is outside the ag corpus boundary",
    "Sawnwood, Cameroon":  "no node: timber is outside the ag corpus boundary",
    "Sawnwood, Malaysian": "no node: timber is outside the ag corpus boundary",
    "Plywood":             "no node: timber is outside the ag corpus boundary",
    "Lead":                "no node: the `metals` slice names copper/aluminium/iron ore/zinc/nickel; "
                           "lead is in none of them",
    "Tin":                 "no node: absent from the `metals` slice term list",
    "Gold":                "no node: precious metals are absent from every slice; the junk-mass class",
    "Platinum":            "no node: precious metals are absent from every slice; the junk-mass class",
    "Silver":              "no node: precious metals are absent from every slice; the junk-mass class",
}

# Series the graph HAS a node for but the World Bank does NOT publish in this workbook. Recorded so
# the gap is visible rather than mistaken for an oversight. MEASURED 2026-08-20: neither string
# appears in any of the 71 headers of release 2026M05 or 2026M07.
_ABSENT_FROM_SOURCE: dict[str, str] = {
    "copra": "context_commodity `coconut` is priced via Coconut oil instead; the World Bank "
             "publishes no copra series",
    "olive_oil": "context_commodity `olive_oil` has NO Pink Sheet leg at all -- a real, open "
                 "coverage gap, not a refusal",
}

# Columns ``extract_pink_sheet`` derives and adds to the frame BEFORE the header match runs. They
# are not World Bank series and must never be reported as header drift.
_DERIVED_COLUMNS: frozenset[str] = frozenset({"date"})

_SHEET_NAME = "Monthly Prices"
_HEADER_ROW = 4   # 0-indexed; row 5 in the workbook (1-indexed)


def _match_columns(
    columns: Sequence[str],
    patterns: dict[str, str],
    required: "frozenset[str]" = frozenset(),
) -> dict[str, str]:
    """Return a rename map {original_header: canonical_name} for matched series.

    Fail-closed conditions for a canonical name in ``required``:

    * NO match          -- the header disappeared;
    * AMBIGUOUS match   -- one pattern matched >1 header;
    * DOUBLE CLAIM      -- two patterns matched the SAME header.

    The double-claim check is new in SILVER-F063 and closes a latent bug that the 15->37 widening
    would otherwise have made likely: the rename map is keyed by the ORIGINAL header, so two
    patterns resolving to one header silently overwrote each other and one governed series vanished
    from bronze with no error. At 15 patterns that was luck; at 37 it is a coin flip.

    A non-required series only WARNs (legacy behaviour). Any header claimed by no pattern and absent
    from :data:`_REFUSED_SERIES` is reported as NEW-SERIES drift.
    """
    col_lower = {c: c.lower() for c in columns}
    result: dict[str, str] = {}
    claimed_by: dict[str, str] = {}          # header -> pattern that claimed it
    missing: list[str] = []
    ambiguous: list[str] = []
    double_claimed: list[str] = []
    for pattern, canonical in patterns.items():
        matches = [orig for orig, low in col_lower.items() if pattern.lower() in low]
        if not matches:
            if canonical in required:
                missing.append(canonical)
            else:
                logger.warning("Pink Sheet: no column matched pattern '%s'", pattern)
            continue
        if len(matches) > 1:
            if canonical in required:
                ambiguous.append(f"{canonical} <- {matches}")
                continue
            logger.warning(
                "Pink Sheet: pattern '%s' matched %d columns %s - using first",
                pattern, len(matches), matches,
            )
        hit = matches[0]
        if hit in claimed_by:
            double_claimed.append(
                f"{hit!r} claimed by '{claimed_by[hit]}' -> {result[hit]} AND "
                f"'{pattern}' -> {canonical}"
            )
            continue
        claimed_by[hit] = pattern
        result[hit] = canonical

    if missing or ambiguous or double_claimed:
        raise ValueError(
            "Pink Sheet: required governed series unresolved -- "
            f"missing={sorted(missing)} ambiguous={sorted(ambiguous)} "
            f"double_claimed={sorted(double_claimed)}. "
            "Refusing to publish a narrowed table (SILVER-F023/F063)."
        )

    # Header-drift instrument (SILVER-F063): a column that is neither kept nor explicitly refused is
    # a series the World Bank added since 2026-08-20. Say so -- the whole point of this wave is that
    # 16-of-71 went unremarked for a year.
    #
    # Both sides are compared stripped: several workbook headers carry trailing spaces
    # ('Rice, Thai 25% ', 'Urea '), so a raw-string comparison would report a refused series as new
    # drift on every single run and train the reader to ignore the warning.
    # ``_DERIVED_COLUMNS`` are added by ``extract_pink_sheet`` before matching and are not workbook
    # series at all.
    refused_stripped = {k.strip() for k in _REFUSED_SERIES}
    unaccounted = [
        c for c in columns
        if c not in claimed_by
        and str(c).strip() not in refused_stripped
        and str(c) not in _DERIVED_COLUMNS
    ]
    if unaccounted:
        logger.warning(
            "Pink Sheet: %d workbook column(s) are NEITHER kept NOR in the refusal table -- the "
            "World Bank appears to have added series since the 2026-08-20 census: %s. Disposition "
            "them in _SERIES_PATTERNS or _REFUSED_SERIES.",
            len(unaccounted), sorted(str(c) for c in unaccounted),
        )
    return result


def extract_pink_sheet(
    raw_bytes: bytes,
    release_ym: str,
) -> pd.DataFrame:
    """Parse a raw Pink Sheet XLSX into a long/tidy bronze DataFrame.

    Args:
        raw_bytes:  Raw bytes of the Excel workbook as stored in S3.
        release_ym: Release year-month in ``YYYYMmm`` format (e.g. ``"2026M07"``),
                    stored as a metadata column.

    Returns:
        Long-format DataFrame with columns
        ``(release_ym, date, series_name, value_usd, source)``.

    Raises:
        ValueError: If the sheet or date column cannot be found, or if any required
                    series column is missing, ambiguous or double-claimed.
    """
    df_raw = pd.read_excel(
        io.BytesIO(raw_bytes),
        sheet_name=_SHEET_NAME,
        header=_HEADER_ROW,
        engine="openpyxl",
    )

    if df_raw.empty:
        raise ValueError(f"Pink Sheet sheet '{_SHEET_NAME}' is empty")

    # Column 0 contains dates in "YYYYMXX" format (e.g. "1960M01") or blank
    # rows used as separators.
    date_col = df_raw.columns[0]
    df_raw = df_raw.dropna(subset=[date_col])

    # Remove aggregates / notes rows that don't look like dates
    date_mask = df_raw[date_col].astype(str).str.match(r"^\d{4}M\d{2}$")
    df_raw = df_raw.loc[date_mask].copy()

    if df_raw.empty:
        raise ValueError(f"Pink Sheet: no valid date rows found in '{_SHEET_NAME}'")

    # Parse dates
    df_raw["date"] = pd.to_datetime(
        df_raw[date_col].astype(str), format="%YM%m", errors="coerce"
    ).dt.date
    df_raw = df_raw.dropna(subset=["date"])

    # Match target series columns
    other_cols = list(df_raw.columns[1:])
    rename_map = _match_columns(other_cols, _SERIES_PATTERNS, required=_REQUIRED_SERIES)
    if not rename_map:
        raise ValueError(
            f"Pink Sheet: no target series columns found. Available: {other_cols[:10]}"
        )

    # Keep only matched columns + date
    keep = ["date"] + list(rename_map.keys())
    df_wide = df_raw[[c for c in keep if c in df_raw.columns]].rename(columns=rename_map)

    # Melt to long format
    value_cols = [c for c in df_wide.columns if c != "date"]
    df_long = df_wide.melt(id_vars=["date"], value_vars=value_cols,
                           var_name="series_name", value_name="value_usd")
    df_long["value_usd"] = pd.to_numeric(df_long["value_usd"], errors="coerce")

    # Bronze metadata
    df_long["release_ym"] = release_ym
    df_long["source"] = "world_bank_pink_sheet"

    df_long = df_long.sort_values(["series_name", "date"]).reset_index(drop=True)

    logger.info(
        "Pink Sheet extract complete  release=%s  rows=%d  series=%d  kept=%s",
        release_ym,
        len(df_long),
        df_long["series_name"].nunique(),
        sorted(df_long["series_name"].unique()),
    )
    return df_long
