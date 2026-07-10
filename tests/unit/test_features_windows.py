"""Unit tests for the per-(commodity, tier) training-window manifest."""
from __future__ import annotations

import numpy as np
import pandas as pd
from leviathan.features.windows import (
    compute_training_windows,
    resolve_tier_families,
)

TIERS = {
    "tiers": {
        "fundamentals": {"families": ["psd_available", "faostat_production_yoy"]},
        "climate": {"includes": ["fundamentals"], "families": ["gdd_z", "chirps_precip_z"]},
        "full": {"includes": ["climate"], "families": ["modis_ndvi_z"]},
    },
    "dense_threshold": 0.99,
}


def test_resolve_tier_families_follows_includes_transitively() -> None:
    assert resolve_tier_families(TIERS["tiers"], "fundamentals") == [
        "psd_available", "faostat_production_yoy",
    ]
    full = resolve_tier_families(TIERS["tiers"], "full")
    # Parents first, no duplicates, child families last.
    assert full == [
        "psd_available", "faostat_production_yoy", "gdd_z", "chirps_precip_z",
        "modis_ndvi_z",
    ]


def _matrix() -> pd.DataFrame:
    years = list(range(1990, 2025))
    df = pd.DataFrame({"country": "us", "crop_year": years})
    # Fundamentals present the whole span.
    df["psd_available"] = 1.0
    df["faostat_production_yoy"] = 0.1
    # Climate present from 1995 (region-suffixed columns).
    df["gdd_z_us_belt"] = np.where(df["crop_year"] >= 1995, 0.5, np.nan)
    df["chirps_precip_z_us_belt_silking"] = np.where(df["crop_year"] >= 1995, 0.2, np.nan)
    # MODIS present only from 2010.
    df["modis_ndvi_z_us_belt_grain_fill"] = np.where(df["crop_year"] >= 2010, 0.3, np.nan)
    # Label present 1990-2022.
    df["label_production_quantity"] = np.where(df["crop_year"] <= 2022, 1000.0, np.nan)
    return df


def test_compute_training_windows_tier_membership_and_windows() -> None:
    out = compute_training_windows(_matrix(), TIERS, "corn_cbot")
    out = out.set_index("tier")

    # Label window is shared (driven by labels, not features).
    assert (out["label_first_year"] == 1990).all()
    assert (out["label_last_year"] == 2022).all()

    # Cumulative feature counts.
    assert out.loc["fundamentals", "n_features"] == 2
    assert out.loc["climate", "n_features"] == 4          # + gdd_z, chirps_precip_z
    assert out.loc["full", "n_features"] == 5             # + modis

    # dense_start reflects the youngest family in each tier.
    assert out.loc["fundamentals", "dense_start_year"] == 1990
    assert out.loc["climate", "dense_start_year"] == 1995  # gdd/chirps start
    assert out.loc["full", "dense_start_year"] == 2010      # modis starts


def test_no_labels_yields_null_window_but_still_lists_features() -> None:
    m = _matrix().drop(columns=["label_production_quantity"])
    out = compute_training_windows(m, TIERS, "x").set_index("tier")
    assert out["label_first_year"].isna().all()
    assert out.loc["full", "n_features"] == 5
