"""WAP Table 01 bronze → silver transforms.

Reads the wide-format bronze Parquet produced by ``wap_task.py`` and produces
two long-format silver tables:

``silver/wap_table01/part-000.parquet``
    One row per (release_month, commodity, marketing_year, vintage_type,
    vintage_status, month_abbr, country).  Values in million metric tonnes.

``silver/wap_table01_revisions/part-000.parquet``
    Same grain, with added columns for the prior release month, prior value,
    and the revision (difference between this and the prior estimate).

Scope / exclusions
------------------
- **Legacy EU era** (2002-08 → 2004-04, 20 releases): excluded.  These files
  use different country columns (eu, fsu12, …) and have suspected commodity
  misassignment in the PDF extraction.  Filter: files missing ``eu27``.
- **Noise row** ``"Oilseeds 2/"``: footnote bleed from PDF extraction; dropped.
- Month-label variants normalised: ``"July" → "Jul"``, ``"Aug." → "Aug"``, etc.
"""
from __future__ import annotations

import re
from typing import Any

import pandas as pd
import pyarrow as pa

from leviathan.common.logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MODERN_COUNTRY_COLUMNS: list[str] = [
    "world", "total_foreign", "us", "canada", "mexico",
    "eu27", "russia", "ukraine",
    "china", "india", "indonesia", "pakistan", "thailand",
    "argentina", "brazil", "australia", "south_africa", "turkey", "all_others",
]

_MONTH_NORMALIZE: dict[str, str] = {
    "July": "Jul",
    "June": "Jun",
    "Aug.": "Aug",
    "Sept.": "Sep",
    "Oct.": "Oct",
    "Nov.": "Nov",
    "Dec.": "Dec",
    "Jan.": "Jan",
    "Feb.": "Feb",
    "Mar.": "Mar",
    "Apr.": "Apr",
}

_VALID_MONTHS: frozenset[str] = frozenset([
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
])

_YEAR_RE = re.compile(r"^(\d{4}/\d{2})(.*)")

# Bronze releases with confirmed commodity-row scrambling in the source PDF.
# 2007-06: rice/total_grains/oilseeds/cotton world values are cyclically
# shifted (rice=1056, total_grains=416, oilseeds=2019, cotton=390 MMT) —
# all wrong by ~2–5x.  Excluding avoids ±1971 MMT artefacts in revisions.
_KNOWN_BAD_RELEASES: frozenset[str] = frozenset(["2007-06"])

SILVER_COLUMNS: list[str] = [
    "release_month",
    "commodity",
    "row_label",
    "marketing_year",
    "vintage_type",
    "vintage_status",
    "month_abbr",
    "country",
    "value_mmt",
]

REVISION_COLUMNS: list[str] = SILVER_COLUMNS + [
    "prior_release_month",
    "prior_value_mmt",
    "revision_mmt",
]

# Complete logical-series business key (excludes release_month; a revision links the
# same series ACROSS releases). row_label decomposes to vintage_type/status/month_abbr,
# so these columns are its equivalent -- plus the derived marketing_year for month rows.
BUSINESS_KEY: list[str] = [
    "commodity", "marketing_year", "vintage_type",
    "vintage_status", "month_abbr", "country",
]

# INV-2 explicit writer schemas for the two WAP silver tables, matching the registry
# target_arrow_type vocabulary (all string keys; value/revision measures float64). The
# base silver_wap_table01 is not this lane's registry file, but the revision table
# (silver_wap_table01_revisions) IS -- its schema is reconciled to the registry by test.
SILVER_ARROW_SCHEMA = pa.schema([
    ("release_month", pa.string()),
    ("commodity", pa.string()),
    ("row_label", pa.string()),
    ("marketing_year", pa.string()),
    ("vintage_type", pa.string()),
    ("vintage_status", pa.string()),
    ("month_abbr", pa.string()),
    ("country", pa.string()),
    ("value_mmt", pa.float64()),
])

REVISION_ARROW_SCHEMA = pa.schema([
    ("release_month", pa.string()),
    ("commodity", pa.string()),
    ("row_label", pa.string()),
    ("marketing_year", pa.string()),
    ("vintage_type", pa.string()),
    ("vintage_status", pa.string()),
    ("month_abbr", pa.string()),
    ("country", pa.string()),
    ("value_mmt", pa.float64()),
    ("prior_release_month", pa.string()),
    ("prior_value_mmt", pa.float64()),
    ("revision_mmt", pa.float64()),
])

# Validation patterns (INV: validate release month + marketing year + row label +
# country + units before output).
_RELEASE_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")
_MARKETING_YEAR_RE = re.compile(r"^\d{4}/\d{2}$")


def _is_projection_status(status: Any) -> bool:
    """True when a year row's status marks it the current-crop projection.

    Generalised (SILVER-F043): case-insensitive ``proj`` prefix after stripping a
    trailing footnote marker (e.g. ``"proj. 1/"`` -> ``proj.``), so the 2016-08
    oilseeds block whose projection row carries a footnote is still recognised.
    """
    if status is None or (isinstance(status, float) and pd.isna(status)):
        return False
    s = str(status).strip().lower()
    return s.startswith("proj")


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def normalize_row_label(label: str) -> str:
    """Apply month-label normalisation map; return label unchanged if not in map.

    Examples::

        normalize_row_label("July") == "Jul"
        normalize_row_label("Aug.") == "Aug"
        normalize_row_label("Jan")  == "Jan"
        normalize_row_label("Oilseeds 2/") == "Oilseeds 2/"
    """
    return _MONTH_NORMALIZE.get(label, label)


def parse_row_label(label: str) -> dict[str, Any]:
    """Classify a row_label into vintage_type and associated attributes.

    Returns a dict with keys:
        vintage_type  – "year" | "month" | "noise"
        marketing_year – e.g. "2024/25" (year rows only, else None)
        vintage_status – e.g. "prel." | "proj." | "" (year rows only, else None)
        month_abbr     – e.g. "Jan" (month rows only, else None)

    Examples::

        parse_row_label("2024/25 prel.")
        # → {"vintage_type": "year", "marketing_year": "2024/25",
        #    "vintage_status": "prel.", "month_abbr": None}

        parse_row_label("Jan")
        # → {"vintage_type": "month", "marketing_year": None,
        #    "vintage_status": None, "month_abbr": "Jan"}

        parse_row_label("Oilseeds 2/")
        # → {"vintage_type": "noise", "marketing_year": None,
        #    "vintage_status": None, "month_abbr": None}
    """
    m = _YEAR_RE.match(label)
    if m:
        marketing_year = m.group(1)
        status = m.group(2).strip()
        return {
            "vintage_type": "year",
            "marketing_year": marketing_year,
            "vintage_status": status,
            "month_abbr": None,
        }
    if label in _VALID_MONTHS:
        return {
            "vintage_type": "month",
            "marketing_year": None,
            "vintage_status": None,
            "month_abbr": label,
        }
    return {
        "vintage_type": "noise",
        "marketing_year": None,
        "vintage_status": None,
        "month_abbr": None,
    }


def _derive_marketing_year_for_months(df: pd.DataFrame) -> pd.DataFrame:
    """Fill marketing_year on month rows from the proj. year row in each block.

    Each (release_month, commodity) block contains one row with
    vintage_status == "proj." whose marketing_year is the current-crop year.
    All month rows in that same block refer to the same marketing year.

    Args:
        df: DataFrame with columns vintage_type, vintage_status, marketing_year,
            release_month, commodity already populated.

    Returns:
        Copy of df with marketing_year filled on month rows.
    """
    df = df.copy()

    # Build a lookup: (release_month, commodity) -> marketing_year of the projection
    # year row (generalised proj-status detection, SILVER-F043). If a block has MORE
    # than one distinct projection marketing_year (ambiguous source evidence), it is
    # NOT imputed -- the key is left None and the month rows are quarantined downstream.
    is_proj = df["vintage_status"].map(_is_projection_status)
    proj_rows = df[(df["vintage_type"] == "year") & is_proj][
        ["release_month", "commodity", "marketing_year"]
    ].drop_duplicates()
    counts = proj_rows.groupby(["release_month", "commodity"])["marketing_year"].nunique()
    ambiguous = set(counts[counts > 1].index)
    proj_rows = proj_rows.drop_duplicates(subset=["release_month", "commodity"])
    proj_map: dict[tuple, str] = {
        (row["release_month"], row["commodity"]): row["marketing_year"]
        for _, row in proj_rows.iterrows()
        if (row["release_month"], row["commodity"]) not in ambiguous
    }

    month_mask = df["vintage_type"] == "month"
    for idx in df.index[month_mask]:
        key = (df.at[idx, "release_month"], df.at[idx, "commodity"])
        if key in proj_map:
            df.at[idx, "marketing_year"] = proj_map[key]

    return df


def melt_to_long(df: pd.DataFrame) -> pd.DataFrame:
    """Melt country columns to long format.

    Drops:
    - Rows where vintage_type == "noise"
    - Rows where value_mmt is NaN (e.g. cotton russia/ukraine in early modern era)

    Country columns melted are those present in df that appear in
    MODERN_COUNTRY_COLUMNS.

    Returns:
        DataFrame with SILVER_COLUMNS column order.
    """
    # Drop noise rows
    df = df[df["vintage_type"] != "noise"].copy()

    # Only melt columns that are actually present
    present_countries = [c for c in MODERN_COUNTRY_COLUMNS if c in df.columns]

    id_cols = [c for c in df.columns if c not in present_countries]
    melted = df.melt(
        id_vars=id_cols,
        value_vars=present_countries,
        var_name="country",
        value_name="value_mmt",
    )

    # Drop NaN values (cotton russia/ukraine NaN pattern)
    melted = melted.dropna(subset=["value_mmt"])

    return melted[SILVER_COLUMNS].reset_index(drop=True)


# ---------------------------------------------------------------------------
# Main entry points
# ---------------------------------------------------------------------------

def build_long_table(dfs: list[pd.DataFrame]) -> pd.DataFrame:
    """Build the WAP Table 01 long-format silver table from bronze DataFrames.

    Applies the full pipeline:
    1. Exclude legacy EU era (files without eu27 column).
    2. Concatenate all remaining DataFrames.
    3. Drop ``"Oilseeds 2/"`` noise rows.
    4. Normalize month-label variants (e.g. July → Jul).
    5. Parse row_label into vintage_type, marketing_year, vintage_status, month_abbr.
    6. Derive marketing_year for month rows from their block's proj. row.
    7. Melt country columns to long format; drop NaN values.
    8. Sort by (release_month, commodity, marketing_year, vintage_type, country).

    Args:
        dfs: List of bronze DataFrames, one per release_month Parquet.

    Returns:
        Long-format DataFrame with SILVER_COLUMNS columns.
    """
    # Step 1 — exclude legacy EU era (identified by presence of the old "eu"
    # column, which replaced eu27 in the 2002-2004 reporting format).
    # Note: the 2015-02→2016-08 releases genuinely lack eu27 in the source
    # PDFs but are otherwise modern-schema (russia/ukraine present); they are
    # included here and melt_to_long will simply skip the absent eu27 column.
    modern = [df for df in dfs if "eu" not in df.columns]

    # Step 1b — drop releases with confirmed bronze extraction errors
    modern = [
        df for df in modern
        if not (
            "release_month" in df.columns
            and df["release_month"].iloc[0] in _KNOWN_BAD_RELEASES
        )
    ]

    if not modern:
        return pd.DataFrame(columns=SILVER_COLUMNS)

    # Step 2 — concat
    combined = pd.concat(modern, ignore_index=True)

    # Step 3 — drop Oilseeds 2/ noise row
    combined = combined[combined["row_label"] != "Oilseeds 2/"].copy()

    # Step 4 — normalize month labels
    combined["row_label"] = combined["row_label"].map(normalize_row_label)

    # Step 5 — parse row_label
    parsed = combined["row_label"].map(parse_row_label)
    combined["vintage_type"] = parsed.map(lambda d: d["vintage_type"])
    combined["marketing_year"] = parsed.map(lambda d: d["marketing_year"])
    combined["vintage_status"] = parsed.map(lambda d: d["vintage_status"])
    combined["month_abbr"] = parsed.map(lambda d: d["month_abbr"])

    # Step 6 — derive marketing_year for month rows
    combined = _derive_marketing_year_for_months(combined)

    # Step 7 — melt
    long_df = melt_to_long(combined)

    # Step 8 — quarantine + validate, then return only the publishable rows.
    valid, _quarantine = _split_quarantine(long_df)

    # Step 9 — sort
    valid = valid.sort_values(
        ["release_month", "commodity", "marketing_year", "vintage_type", "country"],
        na_position="last",
    ).reset_index(drop=True)

    return valid


def _split_quarantine(long_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split a melted long frame into (publishable, quarantined) by natural-key validity.

    SILVER-F043: a missing parser result is NEVER published as a null natural-key
    component. Rows are quarantined -- not silently kept, not silently dropped -- when:
      * marketing_year is null (a month row whose block had no unambiguous projection
        year); or
      * release_month / row_label / country fail their format/presence validation; or
      * value_mmt (the unit-bearing measure) is null.
    """
    if long_df.empty:
        return long_df.copy(), long_df.iloc[0:0].copy()

    df = long_df.copy()
    my = df["marketing_year"].astype("object")
    reasons = pd.Series("", index=df.index, dtype="object")

    def _flag(mask: pd.Series, reason: str) -> None:
        nonlocal reasons
        hit = mask & (reasons == "")
        reasons = reasons.mask(hit, reason)

    _flag(my.isna(), "null_marketing_year")
    _flag(~df["release_month"].astype(str).str.match(_RELEASE_MONTH_RE), "bad_release_month")
    _flag(my.notna() & ~my.astype(str).str.match(_MARKETING_YEAR_RE), "bad_marketing_year")
    _flag(df["row_label"].isna() | (df["row_label"].astype(str).str.strip() == ""), "empty_row_label")
    _flag(~df["country"].isin(MODERN_COUNTRY_COLUMNS), "unknown_country")
    _flag(df["value_mmt"].isna(), "null_value_mmt")

    bad = reasons != ""
    quarantine = df[bad].copy()
    quarantine["quarantine_reason"] = reasons[bad]
    valid = df[~bad].copy()
    if bool(bad.any()):
        logger.info(
            "WAP long: quarantined %d/%d rows (%s)",
            int(bad.sum()), len(df),
            quarantine["quarantine_reason"].value_counts().to_dict(),
        )
    return valid, quarantine


def build_long_table_with_quarantine(
    dfs: list[pd.DataFrame],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Like :func:`build_long_table` but also returns the quarantined rows.

    The publishable frame carries only rows with a complete, valid natural key; the
    quarantine frame carries every excluded row plus a ``quarantine_reason`` column.
    """
    valid = build_long_table(dfs)
    # Re-derive the quarantine set by re-running the pipeline up to the split. Cheap for
    # the modest WAP volume and keeps a single code path (build_long_table) authoritative.
    modern = [df for df in dfs if "eu" not in df.columns]
    modern = [
        df for df in modern
        if not ("release_month" in df.columns
                and df["release_month"].iloc[0] in _KNOWN_BAD_RELEASES)
    ]
    if not modern:
        empty = pd.DataFrame(columns=SILVER_COLUMNS + ["quarantine_reason"])
        return valid, empty
    combined = pd.concat(modern, ignore_index=True)
    combined = combined[combined["row_label"] != "Oilseeds 2/"].copy()
    combined["row_label"] = combined["row_label"].map(normalize_row_label)
    parsed = combined["row_label"].map(parse_row_label)
    combined["vintage_type"] = parsed.map(lambda d: d["vintage_type"])
    combined["marketing_year"] = parsed.map(lambda d: d["marketing_year"])
    combined["vintage_status"] = parsed.map(lambda d: d["vintage_status"])
    combined["month_abbr"] = parsed.map(lambda d: d["month_abbr"])
    combined = _derive_marketing_year_for_months(combined)
    long_df = melt_to_long(combined)
    _valid, quarantine = _split_quarantine(long_df)
    return valid, quarantine


def build_revision_table(df_long: pd.DataFrame) -> pd.DataFrame:
    """Build revision series linked to the PREVIOUS AVAILABLE observation of the same key.

    SILVER-F043 fix. The prior estimate for a row is the value from the previous
    release_month in which THAT COMPLETE LOGICAL KEY actually appears -- NOT the previous
    GLOBAL release (the historical bug, which produced a null prior whenever the key
    happened to skip the immediately-preceding release). This is a grouped chronological
    ``shift(1)`` over :data:`BUSINESS_KEY`, so every non-first revision necessarily
    references an actual prior row for the same key.

    First appearance of a key has prior_release_month / prior_value_mmt / revision_mmt = NaN.

    Args:
        df_long: Output of :func:`build_long_table` (already natural-key-valid).

    Returns:
        DataFrame with :data:`REVISION_COLUMNS`. Its business-key set is identical to the
        input (one revision row per long row).

    Raises:
        ValueError: If the same (release_month + BUSINESS_KEY) occurs more than once --
            an unresolved natural-key conflict that revision linkage must not silently
            average or drop.
    """
    if df_long.empty:
        return pd.DataFrame(columns=REVISION_COLUMNS)

    df = df_long.copy()

    # Fail closed on an in-release natural-key collision (no silent drop/keep-last).
    dup_mask = df.duplicated(subset=["release_month"] + BUSINESS_KEY, keep=False)
    if bool(dup_mask.any()):
        examples = (
            df.loc[dup_mask, ["release_month"] + BUSINESS_KEY]
            .drop_duplicates()
            .head(5)
            .to_dict("records")
        )
        raise ValueError(
            "WAP revisions: duplicate (release_month + business key) rows -- "
            f"unresolved natural-key conflict; examples: {examples}"
        )

    # Order within each logical series by release_month (YYYY-MM sorts chronologically),
    # then shift within the group to the previous release WHERE THE KEY APPEARS.
    df = df.sort_values(BUSINESS_KEY + ["release_month"], na_position="last").reset_index(drop=True)
    grp = df.groupby(BUSINESS_KEY, dropna=False, sort=False)
    df["prior_release_month"] = grp["release_month"].shift(1)
    df["prior_value_mmt"] = grp["value_mmt"].shift(1)
    df["revision_mmt"] = df["value_mmt"] - df["prior_value_mmt"]

    return df[REVISION_COLUMNS].sort_values(
        ["release_month", "commodity", "marketing_year", "vintage_type", "country"],
        na_position="last",
    ).reset_index(drop=True)


def assert_identical_business_keys(base: pd.DataFrame, revisions: pd.DataFrame) -> None:
    """SILVER-F043: base and revisions shadow outputs must have identical business-key sets.

    Raises ValueError if the two frames disagree on the set of
    (release_month + BUSINESS_KEY) rows.
    """
    key_cols = ["release_month"] + BUSINESS_KEY

    def _keyset(df: pd.DataFrame) -> set:
        if df.empty:
            return set()
        return set(map(tuple, df[key_cols].fillna("\x00NULL").to_numpy().tolist()))

    b, r = _keyset(base), _keyset(revisions)
    if b != r:
        only_base = list(b - r)[:5]
        only_rev = list(r - b)[:5]
        raise ValueError(
            "WAP base vs revisions business-key sets differ: "
            f"{len(b - r)} only-in-base (e.g. {only_base}), "
            f"{len(r - b)} only-in-revisions (e.g. {only_rev})"
        )
