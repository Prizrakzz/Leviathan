from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from leviathan.model_datasets.wasde_snapshot_features import (
    build_wasde_feature_quality_report,
    build_wasde_snapshot_dynamic_features,
    dynamic_feature_columns,
    prepare_wasde_snapshot_feature_source,
    validate_wasde_snapshot_features,
)


def _wasde_row(
    release_date: str,
    *,
    year: int = 2024,
    commodity: str = "corn",
    region: str = "United States",
    attribute: str = "production",
    estimate: float = 100.0,
) -> dict[str, object]:
    return {
        "release_date": release_date,
        "commodity": commodity,
        "region": region,
        "marketing_year": f"{year}/{str(year + 1)[-2:]}",
        "attribute": attribute,
        "estimate": estimate,
    }


def _wasde_history() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for year, base, second_revision in [
        (2020, 80.0, 1.0),
        (2021, 90.0, 2.0),
        (2022, 100.0, 3.0),
        (2023, 110.0, 4.0),
    ]:
        rows.extend([
            _wasde_row(f"{year}-05-12", year=year, estimate=base),
            _wasde_row(f"{year}-06-12", year=year, estimate=base + second_revision),
            _wasde_row(f"{year}-07-12", year=year, estimate=base + second_revision + 2.0),
        ])
    rows.extend([
        _wasde_row("2024-05-12", estimate=120.0),
        _wasde_row("2024-06-12", estimate=117.0),
        _wasde_row("2024-07-12", estimate=113.0),
        _wasde_row("2024-05-12", attribute="ending_stocks", estimate=20.0),
        _wasde_row("2024-06-12", attribute="ending_stocks", estimate=18.0),
        _wasde_row("2024-07-12", attribute="ending_stocks", estimate=16.0),
        _wasde_row("2024-05-12", attribute="domestic_total", estimate=70.0),
        _wasde_row("2024-06-12", attribute="domestic_total", estimate=72.0),
        _wasde_row("2024-07-12", attribute="domestic_total", estimate=74.0),
        _wasde_row("2024-05-12", attribute="exports", estimate=30.0),
        _wasde_row("2024-06-12", attribute="exports", estimate=31.0),
        _wasde_row("2024-07-12", attribute="exports", estimate=32.0),
    ])
    return pd.DataFrame(rows)


def _snapshot_targets(as_of_dates: list[str] | None = None) -> pd.DataFrame:
    as_of_dates = as_of_dates or ["2024-05-12", "2024-06-12", "2024-07-12"]
    rows: list[dict[str, object]] = []
    for as_of in as_of_dates:
        rows.append({
            "dataset_key": "corn_wasde_snapshot_solo",
            "contract_key": "corn_cbot",
            "origin_key": "united_states",
            "target_market_year": 2024,
            "as_of_date": as_of,
            "snapshot_stage": "preseason",
            "wasde_commodity": "corn",
            "wasde_origin": "united_states",
            "target_key": "psd_production_anomaly_pct",
        })
    return pd.DataFrame(rows)


def test_latest_visible_estimate_uses_as_of_cutoff() -> None:
    features = build_wasde_snapshot_dynamic_features(
        _wasde_history(),
        _snapshot_targets(["2024-06-12"]),
        min_history_years=2,
    )
    row = features.iloc[0]

    assert row["wasde_production_latest"] == pytest.approx(117.0)
    assert row["wasde_production_mom_revision"] == pytest.approx(-3.0)
    assert row["source_release_date_max"] == pd.Timestamp("2024-06-12")


def test_off_release_snapshot_uses_latest_prior_release() -> None:
    features = build_wasde_snapshot_dynamic_features(
        _wasde_history(),
        _snapshot_targets(["2024-06-30"]),
        min_history_years=2,
    )
    row = features.iloc[0]

    assert row["wasde_production_latest"] == pytest.approx(117.0)
    assert row["wasde_production_mom_revision"] == pytest.approx(-3.0)
    assert row["source_release_date_max"] == pd.Timestamp("2024-06-12")
    assert row["source_release_date_max"] <= row["as_of_date"]


def test_mom_revision_uses_previous_release_only() -> None:
    features = build_wasde_snapshot_dynamic_features(
        _wasde_history(),
        _snapshot_targets(["2024-07-12"]),
        min_history_years=2,
    )

    assert features.iloc[0]["wasde_production_mom_revision"] == pytest.approx(-4.0)


def test_revision_since_first_forecast_and_streak() -> None:
    features = build_wasde_snapshot_dynamic_features(
        _wasde_history(),
        _snapshot_targets(["2024-07-12"]),
        min_history_years=2,
    )
    row = features.iloc[0]

    assert row["wasde_production_revision_since_first"] == pytest.approx(-7.0)
    assert row["wasde_production_latest_vs_first_forecast_pct"] == pytest.approx(-7.0 / 120.0)
    assert row["wasde_production_consecutive_revision_count"] == pytest.approx(-2.0)


def test_revision_z_uses_prior_market_years_only() -> None:
    features = build_wasde_snapshot_dynamic_features(
        _wasde_history(),
        _snapshot_targets(["2024-06-12"]),
        min_history_years=2,
    )
    row = features.iloc[0]

    assert np.isfinite(row["wasde_production_revision_z"])
    assert row["wasde_production_revision_z"] < 0


def test_cross_attribute_stock_to_use_estimate() -> None:
    features = build_wasde_snapshot_dynamic_features(
        _wasde_history(),
        _snapshot_targets(["2024-07-12"]),
        min_history_years=2,
    )
    row = features.iloc[0]

    assert row["wasde_total_use_estimate"] == pytest.approx(106.0)
    assert row["wasde_stock_to_use_estimate"] == pytest.approx(16.0 / 106.0)
    assert row["wasde_ending_stocks_to_use_estimate"] == pytest.approx(16.0 / 106.0)


def test_stock_to_use_revision_features_are_emitted() -> None:
    features = build_wasde_snapshot_dynamic_features(
        _wasde_history(),
        _snapshot_targets(["2024-07-12"]),
        min_history_years=2,
    )
    row = features.iloc[0]
    first_stock_to_use = 20.0 / 100.0
    latest_stock_to_use = 16.0 / 106.0
    prior_stock_to_use = 18.0 / 103.0

    assert row["wasde_stock_to_use_mom_revision"] == pytest.approx(
        latest_stock_to_use - prior_stock_to_use
    )
    assert row["wasde_stock_to_use_revision_since_first"] == pytest.approx(
        latest_stock_to_use - first_stock_to_use
    )
    assert row["wasde_stock_to_use_latest_vs_first_forecast_pct"] == pytest.approx(
        (latest_stock_to_use - first_stock_to_use) / first_stock_to_use
    )
    assert "wasde_stock_to_use_latest_z_by_release_sequence" in features.columns
    assert "wasde_stock_to_use_latest_vs_trend_pct" in features.columns


def test_total_use_estimate_prefers_official_total_use() -> None:
    source = pd.concat([
        _wasde_history(),
        pd.DataFrame([
            _wasde_row("2024-07-12", attribute="total_use", estimate=120.0),
        ]),
    ], ignore_index=True)
    features = build_wasde_snapshot_dynamic_features(
        source,
        _snapshot_targets(["2024-07-12"]),
        min_history_years=2,
    )
    row = features.iloc[0]

    assert row["wasde_total_use_estimate"] == pytest.approx(120.0)
    assert row["wasde_stock_to_use_estimate"] == pytest.approx(16.0 / 120.0)


def test_latest_estimate_alias_columns_are_emitted() -> None:
    features = build_wasde_snapshot_dynamic_features(
        _wasde_history(),
        _snapshot_targets(["2024-06-12"]),
        min_history_years=2,
    )

    assert features.iloc[0]["wasde_production_latest_z_by_release_sequence"] == pytest.approx(
        features.iloc[0]["wasde_production_latest_z"]
    )
    assert features.iloc[0]["wasde_production_latest_vs_trend_pct"] == pytest.approx(
        features.iloc[0]["wasde_production_latest_vs_trend_z"]
    )


def test_missing_attribute_emits_nan_not_zero() -> None:
    features = build_wasde_snapshot_dynamic_features(
        _wasde_history(),
        _snapshot_targets(["2024-07-12"]),
        min_history_years=2,
    )

    assert pd.isna(features.iloc[0]["wasde_imports_latest"])
    assert features.iloc[0]["wasde_imports_latest"] != 0.0


def test_no_feature_uses_future_release() -> None:
    features = build_wasde_snapshot_dynamic_features(
        _wasde_history(),
        _snapshot_targets(["2024-06-12"]),
        min_history_years=2,
    )

    assert features.iloc[0]["wasde_production_latest"] == pytest.approx(117.0)
    assert features.iloc[0]["wasde_production_latest"] != pytest.approx(113.0)
    assert features.iloc[0]["source_release_date_max"] <= features.iloc[0]["as_of_date"]


def test_duplicate_wasde_cells_raise_on_conflict() -> None:
    source = pd.concat([
        _wasde_history(),
        pd.DataFrame([_wasde_row("2024-06-12", estimate=999.0)]),
    ], ignore_index=True)

    with pytest.raises(ValueError, match="conflicting duplicate cells"):
        prepare_wasde_snapshot_feature_source(source)


def test_overlapping_us_and_world_tables_prefer_world_for_non_us_origin() -> None:
    source = pd.DataFrame([
        {
            **_wasde_row(
                "1991-06-11",
                year=1989,
                region="Argentina",
                attribute="production",
                estimate=0.59,
            ),
            "table_type": "us",
        },
        {
            **_wasde_row(
                "1991-06-11",
                year=1989,
                region="Argentina",
                attribute="production",
                estimate=0.09,
            ),
            "table_type": "world",
            "revision": -0.5,
        },
    ])

    prepared = prepare_wasde_snapshot_feature_source(source)

    assert len(prepared) == 1
    assert prepared.iloc[0]["estimate"] == pytest.approx(0.09)
    assert prepared.iloc[0]["wasde_origin"] == "argentina"


def test_dynamic_features_align_to_snapshot_target_grain() -> None:
    targets = pd.concat([_snapshot_targets(), _snapshot_targets()], ignore_index=True)
    features = build_wasde_snapshot_dynamic_features(
        _wasde_history(),
        targets,
        min_history_years=2,
    )

    assert len(features) == 3
    assert not features.duplicated([
        "dataset_key",
        "contract_key",
        "origin_key",
        "target_market_year",
        "as_of_date",
        "snapshot_stage",
    ]).any()


def test_validate_rejects_future_source_release() -> None:
    features = build_wasde_snapshot_dynamic_features(
        _wasde_history(),
        _snapshot_targets(["2024-06-12"]),
        min_history_years=2,
    )
    features.loc[0, "source_release_date_max"] = pd.Timestamp("2024-07-12")

    with pytest.raises(ValueError, match="future source releases"):
        validate_wasde_snapshot_features(features)


def test_feature_quality_report_flags_all_missing_features() -> None:
    features = build_wasde_snapshot_dynamic_features(
        _wasde_history(),
        _snapshot_targets(["2024-07-12"]),
        min_history_years=2,
    )
    quality = build_wasde_feature_quality_report(features)
    by_feature = quality.set_index("feature")

    assert "wasde_imports_latest" in by_feature.index
    assert by_feature.loc["wasde_imports_latest", "non_null_rate"] == 0.0
    assert by_feature.loc["wasde_production_latest", "non_null_rate"] == 1.0
    assert by_feature.loc["wasde_stock_to_use_estimate", "attribute"] == "stock_to_use"
    assert set(dynamic_feature_columns(features)) >= {
        "wasde_production_latest",
        "wasde_production_mom_revision",
        "wasde_stock_to_use_estimate",
    }
