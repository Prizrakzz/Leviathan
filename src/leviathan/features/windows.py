"""Per-(commodity, tier) training-window manifest for ML experiments.

The feature spine emits every feature at its source's natural start year, with
structural NaN before that — so feature families cover very different spans
(fundamentals from ~1981, CHIRPS/NASA climate from ~1990, MODIS/CPC/FX from
~2000-2009, COT/WAP from ~2015-2017).  There is therefore no single training
window: it depends on which features a model uses.

This module turns the named tiers in ``configs/features/feature_tiers.yaml``
plus a commodity's wide feature matrix into a concrete window recommendation:

  - ``label_first_year`` / ``label_last_year`` — the supervised span (targets).
    For tree models with the missingness-as-signal CV, train on the full label
    span using the whole tier; young features are NaN-padded.
  - ``dense_start_year`` — first year where at least ``dense_threshold`` of the
    tier's present features are non-null; the floor for models that can't
    consume NaN.

Pure functions only — the generator (jobs/batch/build_training_windows.py)
reads gold and writes the manifest; this module is unit-tested in isolation.
"""
from __future__ import annotations

import pandas as pd


def resolve_tier_families(tiers: dict, tier_name: str) -> list[str]:
    """Resolve a tier's family prefixes, following ``includes`` transitively."""
    seen: set[str] = set()
    order: list[str] = []

    def _walk(name: str) -> None:
        spec = tiers.get(name)
        if spec is None:
            raise KeyError(f"unknown tier '{name}'")
        for parent in spec.get("includes", []) or []:
            _walk(parent)
        for fam in spec.get("families", []) or []:
            if fam not in seen:
                seen.add(fam)
                order.append(fam)

    _walk(tier_name)
    return order


def _columns_for_families(columns: list[str], families: list[str]) -> list[str]:
    """Feature columns belonging to any family (exact name or ``family_*``)."""
    fams = set(families)
    out = []
    for col in columns:
        if col in fams or any(col.startswith(f + "_") for f in fams):
            out.append(col)
    return out


def compute_training_windows(
    matrix_df: pd.DataFrame,
    tiers_config: dict,
    commodity: str,
) -> pd.DataFrame:
    """One window row per tier for a commodity's wide feature matrix.

    Args:
        matrix_df:     Wide matrix — country, crop_year, <features>, label_*.
        tiers_config:  Parsed feature_tiers.yaml ({"tiers": {...},
                       "dense_threshold": float}).
        commodity:     Slug, copied onto every output row.

    Returns columns: commodity, tier, n_features, label_first_year,
        label_last_year, n_label_years, dense_start_year, dense_window_years,
        present_families.
    """
    tiers = tiers_config.get("tiers", {})
    dense_threshold = float(tiers_config.get("dense_threshold", 0.8))

    feature_cols = [
        c for c in matrix_df.columns
        if c not in ("country", "crop_year") and not c.startswith("label_")
    ]
    label_cols = [c for c in matrix_df.columns if c.startswith("label_")]

    # Supervised span: years with at least one non-null label value.
    if label_cols and not matrix_df.empty:
        lab_years = matrix_df.loc[matrix_df[label_cols].notna().any(axis=1), "crop_year"]
        label_first = int(lab_years.min()) if len(lab_years) else None
        label_last = int(lab_years.max()) if len(lab_years) else None
        n_label_years = int(lab_years.nunique()) if len(lab_years) else 0
    else:
        label_first = label_last = None
        n_label_years = 0

    # Per-year fraction of a tier's families that are *present* — a family
    # counts as present in a year if any of its (possibly per-region) columns is
    # non-null in a majority of that year's rows.  Family-level granularity is
    # what matters for windowing: it tracks which data sources reported, not how
    # many of a commodity's hundreds of weather regions happen to be filled.
    def _family_density_by_year(present_fams: list[str]) -> pd.Series:
        if not present_fams or matrix_df.empty:
            return pd.Series(dtype=float)
        year = matrix_df["crop_year"]
        per_family = []
        for fam in present_fams:
            fam_cols = [c for c in feature_cols if c == fam or c.startswith(fam + "_")]
            any_nonnull = matrix_df[fam_cols].notna().any(axis=1)
            # present in a year when ≥half the rows carry the family that year
            per_family.append(any_nonnull.groupby(year).mean().ge(0.5))
        return pd.concat(per_family, axis=1).mean(axis=1)

    rows = []
    for tier_name in tiers:
        fams = resolve_tier_families(tiers, tier_name)
        cols = _columns_for_families(feature_cols, fams)
        present_families = sorted({
            f for f in fams
            if any(c == f or c.startswith(f + "_") for c in cols)
        })

        dens = _family_density_by_year(present_families)
        dense_years = dens[dens >= dense_threshold].index
        dense_start = int(dense_years.min()) if len(dense_years) else None
        dense_window = (
            int(label_last - dense_start + 1)
            if dense_start is not None and label_last is not None and label_last >= dense_start
            else 0
        )

        rows.append({
            "commodity": commodity,
            "tier": tier_name,
            "n_features": len(cols),
            "label_first_year": label_first,
            "label_last_year": label_last,
            "n_label_years": n_label_years,
            "dense_start_year": dense_start,
            "dense_window_years": dense_window,
            "present_families": ",".join(present_families),
        })

    return pd.DataFrame(rows, columns=[
        "commodity", "tier", "n_features", "label_first_year", "label_last_year",
        "n_label_years", "dense_start_year", "dense_window_years", "present_families",
    ])
