from __future__ import annotations

import pandas as pd

from leviathan.features.calendar import CropCalendar
from leviathan.features.computations.base import FeatureContext
from leviathan.features.computations.psd_vintages import compute_psd_monthly_vintage_features
from leviathan.features.registry import load_registry
from leviathan.features.semantic_catalog import build_semantic_catalog, load_taxonomy


COUNTRY = "united_states"


def _calendar() -> CropCalendar:
    return CropCalendar(
        commodity="corn_cbot",
        crop_year_start_month=5,
        mkt_year_offset=-1,
        stages={},
        gdd_window=None,
    )


def _psd_rows(include_future_revision: bool = True) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for year in range(2016, 2024):
        rows.extend([
            {
                "leviathan_slug": "corn_cbot",
                "country": COUNTRY,
                "market_year": year,
                "release_date": f"{year}-02-10",
                "production_mt": 100.0 + 10.0 * (year - 2016),
            },
            {
                "leviathan_slug": "corn_cbot",
                "country": COUNTRY,
                "market_year": year,
                "release_date": f"{year}-04-10",
                "production_mt": 102.0 + 10.0 * (year - 2016),
            },
        ])

    rows.extend([
        {
            "leviathan_slug": "corn_cbot",
            "country": COUNTRY,
            "market_year": 2024,
            "release_date": "2024-01-10",
            "production_mt": 200.0,
        },
        {
            "leviathan_slug": "corn_cbot",
            "country": COUNTRY,
            "market_year": 2024,
            "release_date": "2024-03-10",
            "production_mt": 210.0,
        },
        {
            "leviathan_slug": "corn_cbot",
            "country": COUNTRY,
            "market_year": 2024,
            "release_date": "2024-04-10",
            "production_mt": 215.0,
        },
    ])
    if include_future_revision:
        rows.append({
            "leviathan_slug": "corn_cbot",
            "country": COUNTRY,
            "market_year": 2024,
            "release_date": "2024-06-10",
            "production_mt": 999.0,
        })
    return pd.DataFrame(rows)


def _compute(df: pd.DataFrame) -> pd.DataFrame:
    ctx = FeatureContext(
        commodity="corn_cbot",
        crop_years=[2024],
        countries=[COUNTRY],
        calendar=_calendar(),
        inputs={"psd": df},
    )
    return compute_psd_monthly_vintage_features(ctx, spec=None).sort_values(
        ["country", "crop_year", "feature"]
    ).reset_index(drop=True)


def test_psd_vintage_features_use_only_visible_releases() -> None:
    features = _compute(_psd_rows(include_future_revision=True))
    values = dict(zip(features["feature"], features["value"], strict=True))

    assert values["psd_production_latest_estimate_as_of"] == 215.0
    assert values["psd_production_mom_revision"] == 5.0
    assert values["psd_production_revision_since_first_forecast"] == 15.0
    assert values["psd_production_consecutive_revision_count"] == 2.0
    assert values["psd_production_month_code"] == 4.0
    assert values["psd_production_release_count_for_market_year"] == 3.0
    assert "psd_production_current_vs_trend" in values


def test_future_revisions_do_not_change_snapshot_features() -> None:
    with_future = _compute(_psd_rows(include_future_revision=True))
    without_future = _compute(_psd_rows(include_future_revision=False))

    pd.testing.assert_frame_equal(with_future, without_future)


def test_psd_monthly_vintage_family_is_registry_backed() -> None:
    registry = load_registry()
    families = {spec.family for spec in registry.specs_for("corn_cbot")}

    assert "psd_monthly_vintage_features" in families


def test_psd_monthly_vintage_taxonomy_classifies_before_generic_psd() -> None:
    taxonomy = load_taxonomy()
    rule = taxonomy.classify("psd_production_mom_revision")

    assert rule.feature_family == "psd_balance_sheet_snapshot"
    assert rule.semantic_scope == "origin_balance_sheet"
    assert rule.source_cadence == "monthly"


def test_psd_monthly_vintage_features_do_not_change_label_count() -> None:
    registry = load_registry()
    spec = next(s for s in registry.specs_for("corn_cbot") if s.family == "psd_monthly_vintage_features")
    result = _compute(_psd_rows())
    result["is_label"] = spec.is_label
    result["event_time"] = pd.Timestamp("2024-05-01")
    result["commodity"] = "corn_cbot"

    catalog = build_semantic_catalog(
        result,
        dataset_version="test",
        taxonomy=load_taxonomy(),
        feature_groups={},
        expected_commodities={"corn_cbot"},
    )

    assert not result["is_label"].any()
    assert not catalog["is_label"].any()
