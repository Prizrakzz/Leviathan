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

    # Build a lookup: (release_month, commodity) → marketing_year of proj. row
    proj_rows = df[
        (df["vintage_type"] == "year") & (df["vintage_status"] == "proj.")
    ][["release_month", "commodity", "marketing_year"]].drop_duplicates(
        subset=["release_month", "commodity"]
    )
    proj_map: dict[tuple, str] = {
        (row["release_month"], row["commodity"]): row["marketing_year"]
        for _, row in proj_rows.iterrows()
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

    # Step 8 — sort
    long_df = long_df.sort_values(
        ["release_month", "commodity", "marketing_year", "vintage_type", "country"],
        na_position="last",
    ).reset_index(drop=True)

    return long_df


def build_revision_table(df_long: pd.DataFrame) -> pd.DataFrame:
    """Build revision series by self-joining to the prior release_month.

    For each (commodity, marketing_year, vintage_type, vintage_status,
    month_abbr, country) observation, finds the immediately preceding
    release_month (in calendar order) that also contains that observation
    and computes revision_mmt = value_mmt - prior_value_mmt.

    Observations with no prior release (e.g. first appearance of a marketing
    year) have prior_release_month=NaN, prior_value_mmt=NaN, revision_mmt=NaN.

    Args:
        df_long: Output of build_long_table().

    Returns:
        DataFrame with REVISION_COLUMNS columns.
    """
    if df_long.empty:
        return pd.DataFrame(columns=REVISION_COLUMNS)

    # Sorted list of unique release months
    release_months = sorted(df_long["release_month"].unique())

    # Map each release_month to the immediately preceding one in the dataset
    month_to_prior: dict[str, str | None] = {
        rm: (release_months[i - 1] if i > 0 else None)
        for i, rm in enumerate(release_months)
    }

    join_keys = [
        "commodity", "marketing_year", "vintage_type",
        "vintage_status", "month_abbr", "country",
    ]
    # These join-key columns can contain None/NaN; pandas merge treats NaN as
    # non-matching by default, so fill with a sentinel before merging.
    nullable_keys = ["marketing_year", "vintage_status", "month_abbr"]
    _FILL = "__NULL__"

    df_curr = df_long.copy()
    df_curr["prior_release_month"] = df_curr["release_month"].map(month_to_prior)
    for col in nullable_keys:
        df_curr[col] = df_curr[col].fillna(_FILL)

    # Prior side: rename release_month and value_mmt for the merge
    df_prior = df_long[["release_month"] + join_keys + ["value_mmt"]].copy()
    df_prior = df_prior.rename(
        columns={"release_month": "prior_release_month", "value_mmt": "prior_value_mmt"}
    )
    for col in nullable_keys:
        df_prior[col] = df_prior[col].fillna(_FILL)

    # Left merge on (prior_release_month, join_keys)
    result = df_curr.merge(
        df_prior,
        on=["prior_release_month"] + join_keys,
        how="left",
    )

    result["revision_mmt"] = result["value_mmt"] - result["prior_value_mmt"]

    # Restore NaN in nullable columns
    for col in nullable_keys:
        result[col] = result[col].replace(_FILL, None)

    # Rows where no prior release exists → all NaN
    no_prior = result["prior_release_month"].isna()
    result.loc[no_prior, "prior_value_mmt"] = float("nan")
    result.loc[no_prior, "revision_mmt"] = float("nan")

    return result[REVISION_COLUMNS].sort_values(
        ["release_month", "commodity", "marketing_year", "vintage_type", "country"],
        na_position="last",
    ).reset_index(drop=True)
