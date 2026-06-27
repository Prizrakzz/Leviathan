from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from leviathan.model_datasets.psd_target_builder import (
    PSD_TARGET_COLUMNS,
    build_psd_target_panel,
)
from leviathan.model_datasets.psd_targets import load_psd_metric_targets

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
    include_early_release: bool = True,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    values = values if values is not None else [10.0, 11.0, 12.0, 13.0, 14.0, 18.0]
    for offset, value in enumerate(values):
        year = start_year + offset
        if include_early_release:
            rows.append({
                "leviathan_slug": slug,
                "country": country,
                "market_year": year,
                "release_date": f"{year}-05-01",
                "production_mt": 999.0 if offset == len(values) - 1 else value - 1.0,
                "ending_stocks_mt": value + 20.0,
                "su_ratio": value / 100.0,
                "exports_mt": value + 30.0,
                "imports_mt": value + 40.0,
                "consumption_mt": value + 50.0,
            })
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


def test_psd_target_builder_selects_latest_release_and_uses_prior_year_trend() -> None:
    panel = build_psd_target_panel(
        _psd_rows(),
        source_dataset_version="gold_v",
        commodities=["corn_cbot"],
    )
    row = panel.loc[
        (panel["origin_key"] == "united_states")
        & (panel["target_key"] == "psd_production_anomaly_pct")
        & (panel["target_market_year"] == 2005)
    ].iloc[0]

    assert row["actual_value"] == 18.0
    assert row["target_observation_release_date"] == pd.Timestamp("2006-02-01")
    assert row["history_years"] == 5
    assert row["is_trainable"]
    assert row["trend_prediction"] == pytest.approx(15.0)
    assert row["target_value"] == pytest.approx(0.2)


def test_psd_target_builder_emits_required_metadata_columns() -> None:
    panel = build_psd_target_panel(
        _psd_rows(),
        source_dataset_version="gold_v",
        commodities=["corn_cbot"],
    )
    row = panel.loc[panel["target_key"] == "psd_production_anomaly_pct"].iloc[-1]

    assert list(panel.columns) == PSD_TARGET_COLUMNS
    assert row["dataset_key"] == "psd_snd_anomaly"
    assert row["commodity"] == "corn_cbot"
    assert row["contract_key"] == "corn_cbot"
    assert row["target_source"] == "psd"
    assert row["target_source_table"] == "silver_psd"
    assert row["target_family"] == "psd_production_anomaly"
    assert row["target_attribute"] == "production_mt"
    assert row["target_status"] == "direct"
    assert row["mapping_confidence"] == "high"
    assert row["psd_source_slug"] == "corn_cbot"
    assert row["psd_commodity"] == "corn"
    assert row["psd_country"] == "United States"
    assert row["origin_key"] == "united_states"
    assert row["origin_role"] == "contract_origin"
    assert row["crop_year"] == row["target_market_year"]
    assert row["target_source_vintage"] == row["target_observation_release_date"]
    assert row["psd_mapping_sha"] == load_psd_metric_targets().config_sha


def test_psd_target_builder_builds_all_six_metric_targets() -> None:
    panel = build_psd_target_panel(
        _psd_rows(),
        source_dataset_version="gold_v",
        commodities=["corn_cbot"],
    )

    assert set(panel["target_key"]) == {
        "psd_production_anomaly_pct",
        "psd_ending_stocks_anomaly_pct",
        "psd_stock_to_use_anomaly_pct",
        "psd_exports_anomaly_pct",
        "psd_imports_anomaly_pct",
        "psd_domestic_use_anomaly_pct",
    }


def test_psd_target_builder_skips_unmapped_cocoa_and_fcoj() -> None:
    empty = pd.DataFrame(columns=["leviathan_slug", "country", "market_year", "release_date", *METRIC_COLUMNS])

    panel = build_psd_target_panel(
        empty,
        source_dataset_version="gold_v",
        commodities=["cocoa", "frozen_orange_juice"],
    )

    assert panel.empty
    assert list(panel.columns) == PSD_TARGET_COLUMNS


def test_psd_target_builder_preserves_proxy_status_for_wheat() -> None:
    panel = build_psd_target_panel(
        _psd_rows(slug="soft_red_winter_wheat_cbot", country="United States"),
        source_dataset_version="gold_v",
        commodities=["soft_red_winter_wheat_cbot"],
    )
    row = panel.loc[panel["target_key"] == "psd_production_anomaly_pct"].iloc[-1]

    assert row["target_status"] == "aggregate_proxy"
    assert row["mapping_confidence"] == "low"
    assert row["psd_commodity"] == "wheat"


def test_psd_target_builder_marks_short_history_untrainable() -> None:
    panel = build_psd_target_panel(
        _psd_rows(values=[10.0, 11.0, 12.0], include_early_release=False),
        source_dataset_version="gold_v",
        commodities=["corn_cbot"],
    )

    assert panel["is_trainable"].sum() == 0
    assert set(panel["excluded_reason"]) == {"insufficient_history"}


def test_psd_target_builder_rejects_unknown_attribute_columns() -> None:
    bad = _psd_rows().drop(columns=["production_mt"])

    with pytest.raises(ValueError, match="missing required columns"):
        build_psd_target_panel(bad, source_dataset_version="gold_v", commodities=["corn_cbot"])


def test_psd_target_builder_rejects_conflicting_duplicate_source_rows() -> None:
    rows = _psd_rows(include_early_release=False)
    duplicate = rows.iloc[[0]].copy()
    duplicate["production_mt"] = 12345.0
    bad = pd.concat([rows, duplicate], ignore_index=True)

    with pytest.raises(ValueError, match="conflicting duplicate rows"):
        build_psd_target_panel(bad, source_dataset_version="gold_v", commodities=["corn_cbot"])


def test_psd_target_builder_marks_near_zero_trend_denominator() -> None:
    panel = build_psd_target_panel(
        _psd_rows(values=[0.0, 0.0, 0.0, 0.0, 0.0, 1.0], include_early_release=False),
        source_dataset_version="gold_v",
        commodities=["corn_cbot"],
    )
    row = panel.loc[
        (panel["target_key"] == "psd_production_anomaly_pct")
        & (panel["target_market_year"] == 2005)
    ].iloc[0]

    assert row["excluded_reason"] == "invalid_trend_denominator"
    assert not row["is_trainable"]
    assert np.isnan(row["target_value"])
