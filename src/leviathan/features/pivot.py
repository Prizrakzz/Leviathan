"""Pivot the long-format feature spine to a wide training matrix.

Two outputs produced after all commodity spines are built:

  gold/feature_matrix/commodity={slug}/part-0.parquet
      Wide format — one row per (country, crop_year).
      Columns: every feature name + label columns (already prefixed ``label_``
      by the computation layer).  Consumed directly by training jobs; no pivot
      needed at training time.

  gold/feature_catalog/feature_catalog.parquet
      Metadata table mapping each feature name to its taxonomy scope.
      Training scripts use this to select feature subsets by scope rather than
      hardcoding column lists.

Scope derivation is empirical: a feature's scope is inferred from which
commodities it actually appears in across the full run.
  universal  — present in every successfully written commodity
  group      — present in 2+ commodities but not all
  commodity  — present in exactly one commodity
"""
from __future__ import annotations

import pandas as pd


def build_feature_matrix(spine_df: pd.DataFrame) -> pd.DataFrame:
    """Pivot a commodity's long-format spine to a wide training matrix.

    Input columns:  country, crop_year, feature, value, is_label, event_time
    Output columns: country, crop_year, <feature_cols...>, <label_cols...>

    Label feature names already carry the ``label_`` prefix from the
    computation layer, so no renaming is needed here.  The natural key
    (country, crop_year, feature) guarantees uniqueness within a partition;
    aggfunc="first" satisfies the pivot_table API without any aggregation.
    """
    if spine_df.empty:
        return pd.DataFrame(columns=["country", "crop_year"])

    matrix = spine_df.pivot_table(
        index=["country", "crop_year"],
        columns="feature",
        values="value",
        aggfunc="first",
    ).reset_index()
    matrix.columns.name = None
    return matrix.sort_values(["country", "crop_year"]).reset_index(drop=True)


def build_feature_catalog(
    feature_commodity_map: dict[str, set[str]],
    feature_is_label: dict[str, bool],
    written_commodities: set[str],
) -> pd.DataFrame:
    """Build the feature catalog from observed feature→commodity membership.

    Args:
        feature_commodity_map: Maps each feature name to the set of commodity
            slugs whose spine contains that feature.
        feature_is_label: Maps each feature name to its is_label flag.
        written_commodities: The set of commodities that successfully wrote
            data in this run — used as the denominator for scope=universal.

    Returns:
        DataFrame with columns:
            feature     — column name as it appears in the wide feature matrix
            scope       — "universal" | "group" | "commodity"
            group       — group name when scope=="group", else None
            commodity   — slug when scope=="commodity", else None
            is_label    — True for training targets; False for model inputs
    """
    rows = []
    for feature in sorted(feature_commodity_map):
        present_in = feature_commodity_map[feature]

        if present_in >= written_commodities:
            scope: str = "universal"
            group: str | None = None
            commodity_col: str | None = None
        elif len(present_in) == 1:
            scope = "commodity"
            group = None
            commodity_col = next(iter(present_in))
        else:
            scope = "group"
            group = None
            commodity_col = None

        rows.append({
            "feature": feature,
            "scope": scope,
            "group": group,
            "commodity": commodity_col,
            "is_label": feature_is_label.get(feature, False),
        })

    return pd.DataFrame(rows, columns=["feature", "scope", "group", "commodity", "is_label"])
