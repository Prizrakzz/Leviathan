"""Unit tests for slice-based model evaluation."""
from __future__ import annotations

import numpy as np
import pandas as pd

from leviathan.training.slices import (
    classify_stress_years,
    compute_slice_metrics,
    evaluate_gaps,
    extreme_directional_metrics,
    flatten_for_mlflow,
    gaps_passed,
    load_gap_rules,
    load_taxonomy,
    rollup_cross_commodity,
)


def _preds(commodity: str, country: str, n: int = 30, start: int = 1995,
           err: float = 0.05, drop_year: int | None = None, drop: float = 0.5) -> pd.DataFrame:
    years = list(range(start, start + n))
    actual = np.linspace(100.0, 130.0, n)
    if drop_year is not None:
        actual[years.index(drop_year)] *= (1 - drop)
    return pd.DataFrame({
        "commodity": commodity, "country": country, "crop_year": years,
        "y_actual": actual, "y_pred": actual * (1 + err),
    })


def test_load_taxonomy_inverts_lists() -> None:
    tax = load_taxonomy()
    assert tax["commodity_crop_type"]["arabica_coffee"] == "tree"
    assert tax["commodity_crop_type"]["corn_cbot"] == "annual"
    assert tax["commodity_group"]["corn_cbot"] == "grains"
    assert tax["commodity_group"]["soybeans_cbot"] == "oilseeds"
    assert tax["commodity_group"]["raw_sugar"] == "softs"
    assert "brazil" in tax["data_rich_countries"]


def test_classify_stress_years_trend_and_named() -> None:
    tax = load_taxonomy()
    # plant a 50% drop in a NON-named year to isolate the trend detector
    df = _preds("arabica_coffee", "brazil", n=30, start=1995, drop_year=2015)
    out = classify_stress_years(df, tax["stress"]).set_index("crop_year")["year_type"]
    assert out.loc[2015] == "stress"        # trend-residual outlier
    assert out.loc[2021] == "stress"        # named macro shock year
    assert out.loc[2005] == "normal"


def test_compute_slice_metrics_dimensions_and_flatten() -> None:
    tax = load_taxonomy()
    preds = pd.concat([
        _preds("arabica_coffee", "brazil"),      # tree / softs / rich
        _preds("corn_cbot", "united_states"),    # annual / grains / rich
        _preds("robusta_coffee", "vietnam"),     # tree / softs / sparse
    ], ignore_index=True)
    sm = compute_slice_metrics(preds, tax)
    dims = set(sm["slice_dim"])
    assert {"overall", "crop_type", "group", "data_richness", "country", "year_type"} <= dims
    ct = set(sm[sm["slice_dim"] == "crop_type"]["slice_value"])
    assert ct == {"tree", "annual"}
    assert set(sm[sm["slice_dim"] == "data_richness"]["slice_value"]) == {"rich", "sparse"}

    flat = flatten_for_mlflow(sm)
    assert "rmse" in flat and "directional_accuracy" in flat            # overall
    assert any(k.startswith("rmse_crop_type_") for k in flat)
    assert any(k.startswith("directional_accuracy_country_") for k in flat)


def test_rollup_cross_commodity_exposes_crop_type() -> None:
    tax = load_taxonomy()
    by = {
        "arabica_coffee": _preds("arabica_coffee", "brazil", err=0.30),   # worse (tree)
        "corn_cbot": _preds("corn_cbot", "united_states", err=0.02),      # better (annual)
    }
    sm = rollup_cross_commodity(by, tax)
    ct = sm[sm["slice_dim"] == "crop_type"].set_index("slice_value")["rmse"]
    assert ct["tree"] > ct["annual"]   # the rollup makes the divergence visible


def _gap_slices() -> pd.DataFrame:
    return pd.DataFrame([
        ("crop_type", "tree", 1.3, 0.60), ("crop_type", "annual", 1.0, 0.70),
        ("year_type", "stress", 2.0, 0.40), ("year_type", "normal", 1.0, 0.70),
        ("country", "vietnam", 1.0, 0.40), ("country", "brazil", 1.0, 0.80),
        ("data_richness", "sparse", 1.5, 0.6), ("data_richness", "rich", 1.0, 0.7),
        ("group", "softs", 1.4, 0.6), ("group", "grains", 1.0, 0.7),
    ], columns=["slice_dim", "slice_value", "rmse", "directional_accuracy"]).assign(n_obs=10, mae=1.0)


def test_evaluate_gaps_pass_and_hard_fail() -> None:
    g = evaluate_gaps(_gap_slices(), load_gap_rules()).set_index("rule")
    assert g.loc["tree_vs_annual_rmse", "status"] == "pass"             # 30% <= 40%
    assert g.loc["sparse_vs_rich_country_rmse", "status"] == "pass"     # 50% <= 60%
    assert g.loc["softs_vs_grains_rmse", "status"] == "pass"            # 40% <= 50%
    assert g.loc["stress_not_worse_than_normal_direction", "status"] == "fail"  # 0.40 < 0.70
    assert g.loc["country_directional_floor", "status"] == "fail"       # vietnam 0.40 < 0.45
    # two HARD failures -> disqualified
    assert gaps_passed(evaluate_gaps(_gap_slices(), load_gap_rules())) is False


def test_extreme_directional_metrics_counts_independent_snapshot_country_years() -> None:
    rows = []
    for country, year, actual in [
        ("argentina", 2020, -0.8),
        ("brazil", 2021, 0.9),
    ]:
        for stage in ["preseason", "early_inseason", "midseason", "late_inseason"]:
            rows.append({
                "commodity": "corn_cbot",
                "country": country,
                "crop_year": year,
                "snapshot_stage": stage,
                "y_actual": actual,
                "y_pred": actual * 0.5,
            })
    metrics = extreme_directional_metrics(
        pd.DataFrame(rows),
        q=1.0,
        min_independent_country_years=3,
    )

    assert metrics["directional_accuracy"] == 1.0
    assert metrics["n_extreme_rows"] == 8
    assert metrics["n_extreme_independent_country_years"] == 2
    assert metrics["validated"] == 0.0
