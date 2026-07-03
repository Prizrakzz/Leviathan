from __future__ import annotations

import pandas as pd
import pytest

from leviathan.model_datasets.wasde_snapshot_anomaly_scores import (
    build_wasde_snapshot_anomaly_scores,
)


def _row(
    *,
    year: int,
    origin: str = "united_states",
    stage: str = "preseason",
    stock_to_use: float = 10.0,
    ending_latest: float = 100.0,
    ending_revision: float = 0.0,
    ending_revision_since_first: float = 0.0,
    exports_revision: float = 0.0,
    streak: float = 0.0,
) -> dict[str, object]:
    return {
        "source_dataset_version": "unit_source",
        "dataset_key": "corn_wasde_snapshot_solo",
        "contract_key": "corn_cbot",
        "commodity": "corn_cbot",
        "commodity_group": "grains",
        "origin": origin,
        "origin_key": origin,
        "target_market_year": year,
        "crop_year": year,
        "target_key": "psd_stock_to_use_anomaly_pct",
        "target_family": "psd_balance_sheet_anomaly",
        "target_attribute": "stock_to_use",
        "target_source": "psd",
        "target_value": -0.2 if stock_to_use < 9.0 else 0.1,
        "target_event_label": stock_to_use < 9.0,
        "target_event_threshold": -0.1,
        "target_event_threshold_type": "fixed_10pct",
        "target_event_direction": "lower_is_stress",
        "as_of_date": f"{year}-06-12",
        "snapshot_stage": stage,
        "sample_weight": 1.0,
        "cv_group": f"corn_cbot|{origin}|{year}",
        "cv_time": year,
        "is_trainable": True,
        "wasde_commodity": "corn",
        "wasde_origin": origin,
        "wasde_stock_to_use_latest": stock_to_use,
        "wasde_ending_stocks_latest": ending_latest,
        "wasde_ending_stocks_mom_revision": ending_revision,
        "wasde_ending_stocks_revision_since_first": ending_revision_since_first,
        "wasde_exports_mom_revision": exports_revision,
        "wasde_ending_stocks_consecutive_revision_count": streak,
    }


def _matrix(rows: list[dict[str, object]]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def _score(
    scores: pd.DataFrame,
    *,
    year: int,
    detector: str,
    source_feature: str,
) -> pd.Series:
    match = scores.loc[
        (scores["target_market_year"] == year)
        & (scores["detector_id"] == detector)
        & (scores["source_feature"] == source_feature)
    ]
    assert len(match) == 1
    return match.iloc[0]


def test_rolling_zscore_excludes_current_row() -> None:
    matrix = _matrix([
        _row(year=2000, stock_to_use=10.0),
        _row(year=2001, stock_to_use=12.0),
        _row(year=2002, stock_to_use=8.0),
    ])

    result = build_wasde_snapshot_anomaly_scores(
        matrix,
        feature_columns=("wasde_stock_to_use_latest",),
        min_prior_observations=2,
    )
    current = _score(
        result.scores,
        year=2002,
        detector="stage_level_z",
        source_feature="wasde_stock_to_use_latest",
    )

    assert current["normalization_group_used"] == "contract_origin_stage"
    assert current["prior_observation_count"] == 2
    assert current["score_value"] == pytest.approx(3.0)


def test_rolling_zscore_excludes_future_rows() -> None:
    base = _matrix([
        _row(year=2000, stock_to_use=10.0),
        _row(year=2001, stock_to_use=12.0),
        _row(year=2002, stock_to_use=8.0),
    ])
    with_future = pd.concat([
        base,
        _matrix([_row(year=2003, stock_to_use=1000.0)]),
    ], ignore_index=True)

    base_result = build_wasde_snapshot_anomaly_scores(
        base,
        feature_columns=("wasde_stock_to_use_latest",),
        min_prior_observations=2,
    )
    future_result = build_wasde_snapshot_anomaly_scores(
        with_future,
        feature_columns=("wasde_stock_to_use_latest",),
        min_prior_observations=2,
    )

    base_score = _score(
        base_result.scores,
        year=2002,
        detector="stage_level_z",
        source_feature="wasde_stock_to_use_latest",
    )["score_value"]
    future_score = _score(
        future_result.scores,
        year=2002,
        detector="stage_level_z",
        source_feature="wasde_stock_to_use_latest",
    )["score_value"]
    assert future_score == pytest.approx(base_score)


def test_prior_percentile_excludes_future_rows() -> None:
    base = _matrix([
        _row(year=2000, stock_to_use=10.0),
        _row(year=2001, stock_to_use=12.0),
        _row(year=2002, stock_to_use=8.0),
    ])
    with_future = pd.concat([
        base,
        _matrix([_row(year=2003, stock_to_use=1.0)]),
    ], ignore_index=True)

    base_result = build_wasde_snapshot_anomaly_scores(
        base,
        feature_columns=("wasde_stock_to_use_latest",),
        min_prior_observations=2,
    )
    future_result = build_wasde_snapshot_anomaly_scores(
        with_future,
        feature_columns=("wasde_stock_to_use_latest",),
        min_prior_observations=2,
    )

    base_score = _score(
        base_result.scores,
        year=2002,
        detector="stage_level_percentile",
        source_feature="wasde_stock_to_use_latest",
    )["score_value"]
    future_score = _score(
        future_result.scores,
        year=2002,
        detector="stage_level_percentile",
        source_feature="wasde_stock_to_use_latest",
    )["score_value"]
    assert base_score == pytest.approx(1.0)
    assert future_score == pytest.approx(base_score)


def test_tightness_score_increases_when_stock_to_use_falls() -> None:
    matrix = _matrix([
        _row(year=2000, stock_to_use=10.0),
        _row(year=2001, stock_to_use=12.0),
        _row(year=2002, stock_to_use=8.0),
        _row(year=2003, stock_to_use=20.0),
    ])

    result = build_wasde_snapshot_anomaly_scores(
        matrix,
        feature_columns=("wasde_stock_to_use_latest",),
        min_prior_observations=2,
    )
    low_score = _score(
        result.scores,
        year=2002,
        detector="stage_level_percentile",
        source_feature="wasde_stock_to_use_latest",
    )["score_value"]
    high_score = _score(
        result.scores,
        year=2003,
        detector="stage_level_percentile",
        source_feature="wasde_stock_to_use_latest",
    )["score_value"]

    assert low_score > high_score


def test_revision_shock_direction_for_exports_and_stocks() -> None:
    matrix = _matrix([
        _row(year=2000, ending_revision=0.0, exports_revision=0.0),
        _row(year=2001, ending_revision=1.0, exports_revision=-1.0),
        _row(year=2002, ending_revision=-2.0, exports_revision=2.0),
    ])

    result = build_wasde_snapshot_anomaly_scores(
        matrix,
        feature_columns=(
            "wasde_ending_stocks_mom_revision",
            "wasde_exports_mom_revision",
        ),
        min_prior_observations=2,
    )
    stocks = _score(
        result.scores,
        year=2002,
        detector="revision_shock",
        source_feature="wasde_ending_stocks_mom_revision",
    )
    exports = _score(
        result.scores,
        year=2002,
        detector="revision_shock",
        source_feature="wasde_exports_mom_revision",
    )

    assert stocks["score_value"] > 0
    assert exports["score_value"] > 0


def test_composite_stress_uses_expected_signs() -> None:
    matrix = _matrix([
        _row(year=2000, stock_to_use=10.0, ending_revision=0.0, exports_revision=0.0),
        _row(year=2001, stock_to_use=12.0, ending_revision=1.0, exports_revision=-1.0),
        _row(year=2002, stock_to_use=8.0, ending_revision=-2.0, exports_revision=2.0),
        _row(year=2003, stock_to_use=20.0, ending_revision=2.0, exports_revision=-2.0),
    ])

    result = build_wasde_snapshot_anomaly_scores(
        matrix,
        feature_columns=(
            "wasde_stock_to_use_latest",
            "wasde_ending_stocks_mom_revision",
            "wasde_exports_mom_revision",
        ),
        min_prior_observations=2,
        min_composite_components=2,
    )
    composite = result.scores.loc[
        result.scores["detector_id"] == "composite_balance_sheet_stress"
    ].set_index("target_market_year")

    assert composite.loc[2002, "score_value"] > composite.loc[2003, "score_value"]


def test_insufficient_prior_history_returns_null_reason() -> None:
    matrix = _matrix([
        _row(year=2000, stock_to_use=10.0),
        _row(year=2001, stock_to_use=12.0),
    ])

    result = build_wasde_snapshot_anomaly_scores(
        matrix,
        feature_columns=("wasde_stock_to_use_latest",),
        min_prior_observations=5,
    )

    assert set(result.scores["score_null_reason"]) == {"insufficient_prior_history"}


def test_fallback_group_is_recorded() -> None:
    matrix = _matrix([
        _row(year=2000, origin="united_states", stock_to_use=10.0),
        _row(year=2000, origin="brazil", stock_to_use=11.0),
        _row(year=2001, origin="brazil", stock_to_use=13.0),
        _row(year=2002, origin="united_states", stock_to_use=8.0),
    ])

    result = build_wasde_snapshot_anomaly_scores(
        matrix,
        feature_columns=("wasde_stock_to_use_latest",),
        min_prior_observations=2,
    )
    current = _score(
        result.scores,
        year=2002,
        detector="stage_level_percentile",
        source_feature="wasde_stock_to_use_latest",
    )

    assert current["normalization_group_used"] == "contract_stage"
    assert current["prior_observation_count"] == 3


def test_scores_expand_to_each_target_without_double_counting_history() -> None:
    rows = [
        _row(year=2000, stock_to_use=10.0),
        _row(year=2001, stock_to_use=12.0),
        _row(year=2002, stock_to_use=8.0),
    ]
    second_target = []
    for row in rows:
        clone = dict(row)
        clone["target_key"] = "psd_ending_stocks_anomaly_pct"
        clone["target_attribute"] = "ending_stocks"
        clone["cv_group"] = clone["cv_group"].replace(
            "psd_stock_to_use_anomaly_pct",
            "psd_ending_stocks_anomaly_pct",
        )
        second_target.append(clone)
    matrix = _matrix([*rows, *second_target])

    result = build_wasde_snapshot_anomaly_scores(
        matrix,
        feature_columns=("wasde_stock_to_use_latest",),
        min_prior_observations=2,
    )
    scored_2002 = result.scores.loc[
        (result.scores["target_market_year"] == 2002)
        & (result.scores["detector_id"] == "stage_level_z")
        & (result.scores["source_feature"] == "wasde_stock_to_use_latest")
    ]

    assert set(scored_2002["target_key"]) == {
        "psd_stock_to_use_anomaly_pct",
        "psd_ending_stocks_anomaly_pct",
    }
    assert set(scored_2002["prior_observation_count"]) == {2}


def test_zscore_is_capped_when_prior_scale_is_tiny() -> None:
    matrix = _matrix([
        _row(year=2000, stock_to_use=10.0),
        _row(year=2001, stock_to_use=10.001),
        _row(year=2002, stock_to_use=1.0),
    ])

    result = build_wasde_snapshot_anomaly_scores(
        matrix,
        feature_columns=("wasde_stock_to_use_latest",),
        min_prior_observations=2,
    )
    score = _score(
        result.scores,
        year=2002,
        detector="stage_level_z",
        source_feature="wasde_stock_to_use_latest",
    )

    assert score["score_value"] == pytest.approx(8.0)


def test_revision_streak_requires_adverse_revision_magnitude() -> None:
    matrix = _matrix([
        _row(
            year=2000,
            ending_latest=100.0,
            ending_revision=-0.1,
            ending_revision_since_first=-0.1,
            streak=-3.0,
        )
    ])

    result = build_wasde_snapshot_anomaly_scores(
        matrix,
        feature_columns=("wasde_ending_stocks_consecutive_revision_count",),
        min_prior_observations=0,
    )
    score = _score(
        result.scores,
        year=2000,
        detector="revision_streak",
        source_feature="wasde_ending_stocks_consecutive_revision_count",
    )

    assert pd.isna(score["score_value"])
    assert score["score_null_reason"] == "revision_streak_magnitude_filter"


def test_revision_streak_scores_when_adverse_revision_is_material() -> None:
    matrix = _matrix([
        _row(
            year=2000,
            ending_latest=100.0,
            ending_revision=-2.0,
            ending_revision_since_first=-5.0,
            streak=-3.0,
        )
    ])

    result = build_wasde_snapshot_anomaly_scores(
        matrix,
        feature_columns=("wasde_ending_stocks_consecutive_revision_count",),
        min_prior_observations=0,
    )
    score = _score(
        result.scores,
        year=2000,
        detector="revision_streak",
        source_feature="wasde_ending_stocks_consecutive_revision_count",
    )

    assert score["score_value"] == pytest.approx(3.0)
