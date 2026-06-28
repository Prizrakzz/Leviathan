from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from leviathan.model_datasets.wasde_snapshot_targets import (
    WASDE_SNAPSHOT_TARGET_COLUMNS,
    assign_snapshot_stage,
    build_wasde_snapshot_target_rows,
    validate_snapshot_target_rows,
)

METRIC_COLUMNS = [
    "production_mt",
    "ending_stocks_mt",
    "su_ratio",
    "exports_mt",
    "imports_mt",
    "consumption_mt",
]


def _psd_rows(
    *,
    slug: str = "corn_cbot",
    country: str = "United States",
    start_year: int = 2000,
    values: list[float] | None = None,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    values = values if values is not None else [10.0, 11.0, 12.0, 13.0, 14.0, 12.0]
    for offset, value in enumerate(values):
        year = start_year + offset
        rows.append({
            "leviathan_slug": slug,
            "country": country,
            "market_year": year,
            "release_date": f"{year + 1}-02-01",
            "production_mt": value,
            "ending_stocks_mt": value + 20.0,
            "su_ratio": value / 100.0,
            "exports_mt": value + 30.0,
            "imports_mt": value + 40.0,
            "consumption_mt": value + 50.0,
        })
    return pd.DataFrame(rows)


def _wasde_rows(
    *,
    commodity: str = "corn",
    region: str = "United States",
    market_year: str = "2005/06",
    release_dates: list[str] | None = None,
    attributes: list[str] | None = None,
) -> pd.DataFrame:
    release_dates = release_dates or ["2005-05-12", "2005-06-10", "2005-08-12"]
    attributes = attributes or ["production", "ending_stocks"]
    rows: list[dict[str, object]] = []
    for release_date in release_dates:
        for attribute in attributes:
            rows.append({
                "release_date": release_date,
                "commodity": commodity,
                "region": region,
                "marketing_year": market_year,
                "attribute": attribute,
                "estimate": 100.0,
            })
    return pd.DataFrame(rows)


def _target_rows(**kwargs: object) -> pd.DataFrame:
    return build_wasde_snapshot_target_rows(
        _psd_rows(**{k: v for k, v in kwargs.items() if k in {"slug", "country", "start_year", "values"}}),
        _wasde_rows(),
        source_dataset_version="test_v",
        dataset_key="corn_wasde_snapshot_solo",
        target_event_threshold_type="fixed_10pct",
    )


def test_expands_one_annual_target_to_multiple_wasde_snapshots() -> None:
    rows = _target_rows()
    target = rows.loc[
        (rows["contract_key"] == "corn_cbot")
        & (rows["origin_key"] == "united_states")
        & (rows["target_market_year"] == 2005)
        & (rows["target_key"] == "psd_production_anomaly_pct")
    ]

    assert list(rows.columns) == WASDE_SNAPSHOT_TARGET_COLUMNS
    assert len(target) == 3
    assert target["as_of_date"].dt.strftime("%Y-%m-%d").tolist() == [
        "2005-05-12",
        "2005-06-10",
        "2005-08-12",
    ]
    assert target["snapshot_stage"].tolist() == [
        "preseason",
        "preseason",
        "early_season",
    ]
    assert target["target_value"].nunique() == 1


def test_cv_group_is_contract_origin_year_not_month() -> None:
    rows = _target_rows()
    target = rows.loc[
        (rows["target_market_year"] == 2005)
        & (rows["target_key"] == "psd_production_anomaly_pct")
    ]

    assert set(target["cv_group"]) == {"corn_cbot|united_states|2005"}
    assert target["cv_time"].astype(int).unique().tolist() == [2005]
    assert not target["cv_group"].astype(str).str.contains("2005-05-12").any()


def test_sample_weights_sum_to_one_per_group_target() -> None:
    rows = _target_rows()
    weights = rows.groupby([
        "dataset_key",
        "contract_key",
        "origin_key",
        "target_market_year",
        "target_key",
    ])["sample_weight"].sum()

    assert weights.min() == pytest.approx(1.0)
    assert weights.max() == pytest.approx(1.0)


def test_fixed_10pct_lower_is_stress_event_label() -> None:
    rows = _target_rows()
    target = rows.loc[
        (rows["target_market_year"] == 2005)
        & (rows["target_key"] == "psd_production_anomaly_pct")
    ].iloc[0]

    assert target["target_value"] == pytest.approx(-0.2)
    assert bool(target["target_event_label"]) is True
    assert target["target_event_threshold"] == pytest.approx(0.10)
    assert target["target_event_direction"] == "lower_is_stress"


def test_fixed_5pct_higher_is_stress_event_label() -> None:
    psd = _psd_rows(values=[10.0, 11.0, 12.0, 13.0, 14.0, 18.0])
    rows = build_wasde_snapshot_target_rows(
        psd,
        _wasde_rows(),
        source_dataset_version="test_v",
        dataset_key="corn_wasde_snapshot_solo",
        target_event_threshold_type="fixed_5pct",
    )
    exports = rows.loc[
        (rows["target_market_year"] == 2005)
        & (rows["target_key"] == "psd_exports_anomaly_pct")
    ].iloc[0]

    assert exports["target_event_direction"] == "higher_is_stress"
    assert bool(exports["target_event_label"]) is True
    assert exports["target_event_threshold"] == pytest.approx(0.05)


def test_history_quintile_event_labels_use_prior_history() -> None:
    psd = _psd_rows(values=[
        10.0, 12.0, 14.0, 16.0, 18.0,
        8.0, 20.0, 19.0, 21.0, 22.0, 14.0,
    ])
    wasde = pd.concat([
        _wasde_rows(market_year="2005/06"),
        _wasde_rows(market_year="2010/11"),
    ], ignore_index=True)
    rows = build_wasde_snapshot_target_rows(
        psd,
        wasde,
        source_dataset_version="test_v",
        dataset_key="corn_wasde_snapshot_solo",
        target_event_threshold_type="history_quintile",
    )
    first_trainable = rows.loc[
        (rows["target_market_year"] == 2005)
        & (rows["target_key"] == "psd_production_anomaly_pct")
    ].iloc[0]
    later_year = rows.loc[
        (rows["target_market_year"] == 2010)
        & (rows["target_key"] == "psd_production_anomaly_pct")
    ].iloc[0]

    assert pd.isna(first_trainable["target_event_label"])
    assert first_trainable["target_event_definition"] == "insufficient_prior_history_for_quintile"
    assert not pd.isna(later_year["target_event_threshold"])


def test_missing_target_rows_are_flagged_not_silently_dropped() -> None:
    wasde = _wasde_rows(market_year="2010/11")
    rows = build_wasde_snapshot_target_rows(
        _psd_rows(),
        wasde,
        source_dataset_version="test_v",
        dataset_key="corn_wasde_snapshot_solo",
    )

    assert not rows.empty
    assert set(rows["excluded_reason"]) == {"missing_target"}
    assert rows["is_trainable"].sum() == 0
    assert not rows["target_available"].any()


def test_deferred_contracts_are_excluded_from_grain_segment_targets() -> None:
    psd = pd.concat([
        _psd_rows(slug="corn_cbot", country="United States"),
        _psd_rows(slug="rough_rice_cbot", country="United States"),
        _psd_rows(slug="soft_red_winter_wheat_cbot", country="United States"),
        _psd_rows(slug="hard_red_winter_wheat_kcbt", country="United States"),
    ], ignore_index=True)
    wasde = pd.concat([
        _wasde_rows(commodity="corn", region="United States"),
        _wasde_rows(commodity="rice", region="United States"),
        _wasde_rows(commodity="wheat", region="United States"),
    ], ignore_index=True)

    rows = build_wasde_snapshot_target_rows(
        psd,
        wasde,
        source_dataset_version="test_v",
        dataset_key="grains_wasde_snapshot_segment",
    )

    assert "corn_cbot" in set(rows["contract_key"])
    assert "rough_rice_cbot" in set(rows["contract_key"])
    assert "soft_red_winter_wheat_cbot" in set(rows["contract_key"])
    assert "hard_red_winter_wheat_kcbt" not in set(rows["contract_key"])


def test_duplicate_snapshot_target_keys_raise() -> None:
    rows = _target_rows()
    duplicate = pd.concat([rows, rows.iloc[[0]]], ignore_index=True)

    with pytest.raises(ValueError, match="duplicate WASDE snapshot target rows"):
        validate_snapshot_target_rows(duplicate)


def test_snapshot_stage_assignment_is_deterministic() -> None:
    assert assign_snapshot_stage("2024-05-12") == "preseason"
    assert assign_snapshot_stage("2024-08-12") == "early_season"
    assert assign_snapshot_stage("2024-10-12") == "midseason"
    assert assign_snapshot_stage("2024-12-12") == "late_season"
    assert assign_snapshot_stage("2025-02-12") == "post_harvest"
    assert assign_snapshot_stage("2025-04-12") == "finalization"


def test_untrainable_annual_targets_remain_untrainable_after_expansion() -> None:
    rows = build_wasde_snapshot_target_rows(
        _psd_rows(values=[10.0, 11.0, 12.0]),
        _wasde_rows(market_year="2002/03"),
        source_dataset_version="test_v",
        dataset_key="corn_wasde_snapshot_solo",
    )

    assert not rows["is_trainable"].any()
    assert set(rows["excluded_reason"]) == {"insufficient_history"}
    assert np.isfinite(rows["sample_weight"]).all()
