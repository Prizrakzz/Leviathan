from __future__ import annotations

import warnings
from collections.abc import Mapping
from typing import Any

import matplotlib
import numpy as np
import pandas as pd
import pytest

matplotlib.use("Agg", force=True)
import matplotlib.pyplot as plt  # noqa: E402

from leviathan.eda.reader_charts import (
    SUPPORTED_CHART_TYPES,
    chart_scope_record,
    compute_chart_payload,
    compute_chart_payloads,
    render_chart_payload,
)


def _plan(chart_type: str, columns: list[str], chart_id: str | None = None) -> dict[str, Any]:
    return {
        "chart_id": chart_id or chart_type,
        "chart_type": chart_type,
        "columns": columns,
        "exactness": "exact",
        "status": "ready",
        "title": chart_type.replace("_", " ").title(),
    }


def _provenance(frame: pd.DataFrame) -> dict[str, Any]:
    return {
        "analysis_rows": len(frame),
        "exactness": "exact",
        "source_rows": len(frame),
    }


@pytest.fixture
def monthly_frame() -> pd.DataFrame:
    rows = []
    dates = pd.date_range("2018-01-01", periods=72, freq="MS")
    for entity_index, entity in enumerate(("alpha", "beta", "gamma")):
        for index, date in enumerate(dates):
            rows.append(
                {
                    "commodity": entity,
                    "date": date,
                    "value": 100 + 8 * entity_index + index + 12 * np.sin(index / 6),
                    "value_2": 60 + 4 * entity_index + 0.4 * index,
                }
            )
    frame = pd.DataFrame(rows)
    frame.loc[frame.index[::31], "value_2"] = np.nan
    return frame


@pytest.fixture
def annual_frame() -> pd.DataFrame:
    rows = []
    for commodity in ("corn", "soy"):
        for state_index, state in enumerate(("IA", "IL", "NE")):
            for year in range(2000, 2024):
                rows.append(
                    {
                        "commodity": commodity,
                        "state": state,
                        "year": year,
                        "production_mt": 1_000 + 30 * (year - 2000) + 80 * state_index,
                        "yield_t_ha": 2.5 + 0.03 * (year - 2000) + 0.1 * state_index,
                    }
                )
    return pd.DataFrame(rows)


@pytest.fixture
def progress_frame() -> pd.DataFrame:
    rows = []
    for market_year in (2021, 2022, 2023):
        for commodity in ("corn", "soy"):
            for week in range(1, 21):
                rows.append(
                    {
                        "commodity": commodity,
                        "date": pd.Timestamp(f"{market_year}-01-01") + pd.Timedelta(weeks=week),
                        "market_year": market_year,
                        "pct_planted": min(100.0, week * 5 + (2 if commodity == "corn" else -2)),
                        "week_of_year": week,
                    }
                )
    return pd.DataFrame(rows)


@pytest.fixture
def vintage_frame() -> pd.DataFrame:
    rows = []
    for commodity in ("corn", "soy"):
        for marketing_year in ("2022/23", "2023/24", "2024/25"):
            prior = None
            for release in range(6):
                estimate = 100 + release * 4 + (8 if commodity == "soy" else 0)
                rows.append(
                    {
                        "attribute": "production",
                        "commodity": commodity,
                        "estimate": estimate,
                        "marketing_year": marketing_year,
                        "release_date": pd.Timestamp("2022-01-01")
                        + pd.DateOffset(months=release),
                        "revision": np.nan if prior is None else estimate - prior,
                    }
                )
                prior = estimate
    return pd.DataFrame(rows)


@pytest.fixture
def icco_frame() -> pd.DataFrame:
    years = np.arange(2000, 2024)
    return pd.DataFrame(
        {
            "cocoa_year": years,
            "end_stocks_kt": 1_200 + 20 * np.sin(np.arange(len(years)) / 3),
            "grindings_kt": 3_000 + 35 * np.arange(len(years)),
            "production_kt": 3_100 + 42 * np.arange(len(years)),
            "su_ratio": 0.4 - 0.003 * np.arange(len(years)),
            "surplus_deficit_kt": 150 * np.sin(np.arange(len(years)) / 2),
        }
    )


def _parity_evidence() -> list[dict[str, Any]]:
    return [
        {
            "compact_only_keys": 0,
            "matched_keys": 120,
            "raw_only_keys": 0,
            "relationship": "silver_esr_to_silver_esr_compact",
            "status": "complete",
            "value_parity": {
                "outstanding_sales_1000mt": {
                    "comparable_rows": 120,
                    "mismatch_rate": 0.0,
                    "mismatch_rows": 0,
                },
                "weekly_exports_1000mt": {
                    "comparable_rows": 120,
                    "mismatch_rate": 0.01,
                    "mismatch_rows": 1,
                },
            },
        }
    ]


@pytest.mark.parametrize(
    ("chart_type", "fixture_name", "columns"),
    [
        ("line", "monthly_frame", ["date", "value", "commodity"]),
        ("distribution", "monthly_frame", ["value", "commodity"]),
        ("coverage_heatmap", "monthly_frame", ["date", "commodity"]),
        ("seasonal_profile", "monthly_frame", ["date", "value", "commodity"]),
        ("anomaly_heatmap", "monthly_frame", ["date", "value", "commodity"]),
        ("change_distribution", "monthly_frame", ["date", "value", "commodity"]),
        ("calendar_heatmap", "monthly_frame", ["date", "value", "commodity"]),
        ("ranked_bar", "annual_frame", ["year", "production_mt", "commodity", "state"]),
        ("year_over_year", "monthly_frame", ["date", "value", "commodity"]),
        ("composition", "monthly_frame", ["date", "value", "value_2", "commodity"]),
        ("season_curve", "progress_frame", ["date", "pct_planted", "commodity"]),
        ("increment", "progress_frame", ["date", "pct_planted", "commodity"]),
        ("milestone", "progress_frame", ["date", "pct_planted", "commodity"]),
        ("vintage_line", "vintage_frame", ["release_date", "estimate", "commodity"]),
        (
            "revision_distribution",
            "vintage_frame",
            ["release_date", "estimate", "commodity"],
        ),
        ("release_depth", "vintage_frame", ["release_date", "commodity"]),
        ("first_latest", "vintage_frame", ["release_date", "estimate", "commodity"]),
        ("missingness_bar", "monthly_frame", ["value", "value_2"]),
        ("signed_bar", "icco_frame", ["cocoa_year", "surplus_deficit_kt"]),
        ("dual_axis", "icco_frame", ["cocoa_year", "end_stocks_kt", "su_ratio"]),
    ],
)
def test_every_frame_chart_type_builds_scoped_payload_and_figure(
    request: pytest.FixtureRequest,
    chart_type: str,
    fixture_name: str,
    columns: list[str],
) -> None:
    frame = request.getfixturevalue(fixture_name)
    payload = compute_chart_payload(
        frame,
        _plan(chart_type, columns),
        _provenance(frame),
        units={
            "end_stocks_kt": "kt",
            "estimate": "native unit",
            "pct_planted": "%",
            "production_mt": "mt",
            "su_ratio": "ratio",
            "surplus_deficit_kt": "kt",
            "value": "index",
            "value_2": "index",
        },
    )
    assert payload["status"] == "ready", payload["omission_reason"]
    assert payload["records"]
    assert payload["aggregation"] != "not computed"
    assert payload["scope"]
    assert payload["source_rows"] == len(frame)
    assert payload["analysis_rows"] == len(frame)
    assert payload["plotted_rows"] > 0
    assert payload["plotted_rows"] == len(payload["records"])
    assert payload["exactness"] == "exact"
    assert payload["unit"]
    assert chart_scope_record(payload)["aggregation"] == payload["aggregation"]
    figure = render_chart_payload(payload)
    assert figure is not None
    assert getattr(figure, "_leviathan_chart_payload")["chart_id"] == chart_type
    plt.close(figure)


def test_parity_requires_and_renders_bound_relationship_evidence(monthly_frame: pd.DataFrame) -> None:
    plan = _plan("parity", [], "paired_parity")
    omitted = compute_chart_payload(monthly_frame, plan, _provenance(monthly_frame))
    assert omitted["status"] == "omitted"
    assert "relationship evidence" in omitted["omission_reason"]

    payload = compute_chart_payload(
        monthly_frame,
        plan,
        _provenance(monthly_frame),
        relationship_evidence=_parity_evidence(),
    )
    assert payload["status"] == "ready"
    assert payload["plotted_rows"] == len(payload["records"]) == 7
    assert "matched keys=120" in payload["scope"]
    assert "No compact-only coverage extension" in payload["scope"]
    assert {row["measure"] for row in payload["records"] if row["panel"] == "key coverage"} == {
        "raw rows",
        "compact rows",
        "matched keys",
        "raw-only keys",
        "compact-only keys",
    }
    figure = render_chart_payload(payload)
    assert figure is not None
    plt.close(figure)


def test_parity_scope_labels_later_compact_keys_as_coverage_extension(
    monthly_frame: pd.DataFrame,
) -> None:
    evidence = _parity_evidence()
    evidence[0]["compact_only_keys"] = 80
    evidence[0]["compact_coverage_extension"] = {
        "classification": "later_snapshot_extension",
        "key_count": 80,
        "entirely_after_raw_latest_as_of": True,
        "interpretation": (
            "Compact-only keys are later snapshots beyond the raw frame's latest as-of date; "
            "they extend compact coverage and do not contradict shared-key parity."
        ),
    }

    payload = compute_chart_payload(
        monthly_frame,
        _plan("parity", [], "paired_parity"),
        _provenance(monthly_frame),
        relationship_evidence=evidence,
    )

    assert payload["status"] == "ready"
    assert "later snapshots" in payload["scope"]
    assert "do not contradict shared-key parity" in payload["scope"]


def test_line_preserves_entities_and_latest_ranking_uses_one_period(
    monthly_frame: pd.DataFrame, annual_frame: pd.DataFrame
) -> None:
    line = compute_chart_payload(
        monthly_frame,
        _plan("line", ["date", "value", "commodity"]),
        _provenance(monthly_frame),
    )
    assert len({row["series"] for row in line["records"]}) == 3
    assert "series remain separate" in line["aggregation"]

    ranking = compute_chart_payload(
        annual_frame,
        _plan("ranked_bar", ["year", "production_mt", "commodity", "state"]),
        _provenance(annual_frame),
    )
    periods = {row["period"] for row in ranking["records"]}
    assert len(periods) == 1
    assert next(iter(periods)).startswith("2023-")
    assert "latest comparable period only" in ranking["aggregation"]


def test_two_column_coverage_counts_all_contributing_rows(monthly_frame: pd.DataFrame) -> None:
    payload = compute_chart_payload(
        monthly_frame,
        _plan("coverage_heatmap", ["date", "commodity"]),
        _provenance(monthly_frame),
    )
    assert payload["status"] == "ready"
    assert sum(row["value"] for row in payload["records"]) == len(monthly_frame)


def _pilot_cases(
    monthly: pd.DataFrame,
    annual: pd.DataFrame,
    progress: pd.DataFrame,
    vintage: pd.DataFrame,
) -> Mapping[str, tuple[pd.DataFrame, list[dict[str, Any]], list[dict[str, Any]]]]:
    weather_plans = [
        _plan("coverage_heatmap", ["date", "commodity"], "coverage"),
        _plan("seasonal_profile", ["date", "value", "commodity"], "climatology"),
        _plan("distribution", ["value"], "distribution"),
        _plan("anomaly_heatmap", ["date", "value", "commodity"], "anomalies"),
    ]
    continuous = [
        _plan("line", ["date", "value", "commodity"], "history"),
        _plan("change_distribution", ["date", "value", "commodity"], "changes"),
        _plan("calendar_heatmap", ["date", "value", "commodity"], "seasonality"),
        _plan("distribution", ["value", "commodity"], "measure_distribution"),
    ]
    annual_plans = [
        _plan("line", ["year", "production_mt", "yield_t_ha", "commodity"], "history"),
        _plan("ranked_bar", ["year", "production_mt", "commodity", "state"], "latest_ranking"),
        _plan("distribution", ["production_mt", "commodity"], "distribution"),
        _plan("coverage_heatmap", ["year", "commodity"], "coverage"),
    ]
    monthly_plans = [
        _plan("line", ["date", "value", "value_2", "commodity"], "history"),
        _plan("seasonal_profile", ["date", "value", "commodity"], "seasonality"),
        _plan("year_over_year", ["date", "value", "commodity"], "year_over_year"),
        _plan("composition", ["date", "value", "value_2", "commodity"], "composition"),
    ]
    progress_plans = [
        _plan("season_curve", ["date", "pct_planted", "commodity"], "season_curves"),
        _plan("increment", ["date", "pct_planted", "commodity"], "increments"),
        _plan("milestone", ["date", "pct_planted", "commodity"], "milestones"),
        _plan("coverage_heatmap", ["date", "commodity"], "coverage"),
    ]
    vintage_plans = [
        _plan("vintage_line", ["release_date", "estimate", "commodity"], "vintage_trajectory"),
        _plan("revision_distribution", ["release_date", "estimate", "commodity"], "revision_distribution"),
        _plan("release_depth", ["release_date", "commodity"], "release_depth"),
        _plan("first_latest", ["release_date", "estimate", "commodity"], "first_latest"),
    ]
    esr = progress.rename(
        columns={"date": "week_ending_date", "pct_planted": "weekly_exports_1000mt"}
    ).copy()
    esr["outstanding_sales_1000mt"] = 1_000 - esr["weekly_exports_1000mt"]
    esr["as_of_date"] = esr["week_ending_date"] + pd.Timedelta(days=7)
    esr_plans = [
        _plan("season_curve", ["week_ending_date", "weekly_exports_1000mt", "commodity"], "weekly_flow"),
        _plan("season_curve", ["week_ending_date", "outstanding_sales_1000mt", "commodity"], "outstanding"),
        _plan("coverage_heatmap", ["as_of_date", "commodity"], "vintage_coverage"),
        _plan("parity", [], "paired_parity"),
    ]
    derived = annual.loc[annual["commodity"].eq("corn")].copy()
    derived_plans = [
        _plan("line", ["year", "production_mt", "yield_t_ha", "state"], "measure_history"),
        _plan("missingness_bar", ["production_mt", "yield_t_ha"], "missingness"),
    ]
    return {
        "silver_chirps": (monthly, weather_plans, []),
        "silver_nasa_power": (monthly, weather_plans, []),
        "silver_futures_prices": (monthly, continuous, []),
        "silver_nass_annual": (annual, annual_plans, []),
        "silver_mpob": (monthly, monthly_plans, []),
        "silver_nass_crop_progress": (progress, progress_plans, []),
        "silver_wasde": (vintage, vintage_plans, []),
        "silver_esr": (esr, esr_plans, _parity_evidence()),
        "silver_esr_compact": (esr, esr_plans, _parity_evidence()),
        "silver_mpob_annual": (derived, derived_plans, []),
    }


def test_ten_non_quarantine_pilots_render_all_semantically_supported_plans(
    monthly_frame: pd.DataFrame,
    annual_frame: pd.DataFrame,
    progress_frame: pd.DataFrame,
    vintage_frame: pd.DataFrame,
) -> None:
    cases = _pilot_cases(monthly_frame, annual_frame, progress_frame, vintage_frame)
    assert len(cases) == 10
    for table, (frame, plans, relationship_evidence) in cases.items():
        payloads = compute_chart_payloads(
            frame,
            plans,
            _provenance(frame),
            relationship_evidence=relationship_evidence,
        )
        omitted = [payload for payload in payloads if payload["status"] != "ready"]
        if table == "silver_mpob_annual":
            assert len(omitted) == 1
            assert omitted[0]["chart_id"] == "missingness"
            assert "all-zero missingness chart" in omitted[0]["omission_reason"]
        elif table == "silver_mpob":
            assert len(omitted) == 1
            assert omitted[0]["chart_id"] == "composition"
            assert "component measures are incompatible" in omitted[0]["omission_reason"]
        else:
            assert not omitted, (table, omitted)
        ready = [payload for payload in payloads if payload["status"] == "ready"]
        assert all(payload["plotted_rows"] == len(payload["records"]) for payload in ready)
        figures = [render_chart_payload(payload) for payload in ready]
        assert all(figure is not None for figure in figures), table
        for figure in figures:
            plt.close(figure)


def test_model_predictions_remains_zero_chart_quarantine(monthly_frame: pd.DataFrame) -> None:
    plans = [
        _plan("missingness_bar", [], "output_missingness"),
        _plan("coverage_heatmap", ["date", "commodity"], "output_coverage"),
    ]
    payloads = compute_chart_payloads(
        monthly_frame,
        plans,
        _provenance(monthly_frame),
        quarantine=True,
    )
    assert not [payload for payload in payloads if payload["status"] == "ready"]
    assert all(render_chart_payload(payload) is None for payload in payloads)


def test_line_renderer_breaks_declared_calendar_week_gaps() -> None:
    frame = pd.DataFrame(
        {
            "commodity": "corn",
            "state": "IA",
            "year": 2024,
            "week_of_year": [1, 2, 3, 8, 9, 10, 11, 12],
            "pct_planted": [2.0, 6.0, 12.0, 48.0, 61.0, 74.0, 86.0, 94.0],
        }
    )
    plan = {
        **_plan(
            "line",
            ["week_of_year", "pct_planted", "year", "commodity", "state"],
            "planting_progress",
        ),
        "max_series": 4,
        "max_x_gap": 1,
        "minimum_rows": 8,
        "series_dimensions": ["year"],
        "split_by": ["commodity", "state"],
        "time_components": ["week_of_year"],
    }
    payload = compute_chart_payload(frame, plan, _provenance(frame))

    assert payload["status"] == "ready"
    assert payload["encoding"]["max_x_gap"] == 1.0
    assert "line breaks where the x-axis gap exceeds 1" in payload["scope"]
    figure = render_chart_payload(payload)
    assert figure is not None
    plotted_segments = [line.get_xdata().tolist() for line in figure.axes[0].lines]
    assert plotted_segments == [[1.0, 2.0, 3.0], [8.0, 9.0, 10.0, 11.0, 12.0]]
    plt.close(figure)


def test_incompatible_futures_measures_are_split_with_bounded_time_ticks(
    monthly_frame: pd.DataFrame,
) -> None:
    frame = monthly_frame.rename(
        columns={"value": "close", "value_2": "log_return"}
    ).copy()
    frame["log_return"] = frame.groupby("commodity")["close"].pct_change(
        fill_method=None
    )
    plans = [
        _plan("line", ["date", "close", "log_return", "commodity"], "history"),
        _plan(
            "distribution",
            ["close", "log_return", "commodity"],
            "distribution",
        ),
    ]

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        payloads = compute_chart_payloads(
            frame,
            plans,
            _provenance(frame),
            units={"close": "USD", "log_return": "decimal return"},
        )
        ready = [payload for payload in payloads if payload["status"] == "ready"]
        figures = [render_chart_payload(payload) for payload in ready]

    assert {payload["chart_id"] for payload in ready} == {
        "distribution",
        "distribution__log_return",
        "history",
        "history__log_return",
    }
    for payload in ready:
        assert len({row["measure"] for row in payload["records"]}) == 1
        assert payload["unit"] in {"USD", "decimal return"}
        assert payload["plotted_rows"] == len(payload["records"])
    line_figures = [
        figure
        for figure, payload in zip(figures, ready)
        if payload["chart_type"] == "line"
    ]
    assert line_figures
    assert all(
        len([label for label in figure.axes[0].get_xticklabels() if label.get_visible()])
        <= 8
        for figure in line_figures
    )
    for figure in figures:
        plt.close(figure)

    direct = compute_chart_payload(
        frame,
        plans[0],
        _provenance(frame),
        units={"close": "USD", "log_return": "decimal return"},
    )
    assert direct["status"] == "omitted"
    assert "rendered separately" in direct["omission_reason"]


def test_vintage_axes_use_explicit_release_dates_without_inference_warnings(
    vintage_frame: pd.DataFrame,
) -> None:
    frame = vintage_frame.copy()
    frame["release_date"] = frame["release_date"].dt.strftime("%Y-%m-%d")
    plans = [
        _plan(
            "vintage_line",
            ["marketing_year", "estimate", "release_date", "commodity"],
            "trajectory",
        ),
        _plan(
            "release_depth",
            ["marketing_year", "release_date", "commodity"],
            "release_depth",
        ),
        _plan(
            "first_latest",
            ["marketing_year", "estimate", "release_date", "commodity"],
            "first_latest",
        ),
    ]
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        payloads = compute_chart_payloads(frame, plans, _provenance(frame))
        figures = [
            render_chart_payload(payload)
            for payload in payloads
            if payload["status"] == "ready"
        ]
    assert all(payload["status"] == "ready" for payload in payloads)
    assert "time=release_date" in payloads[0]["scope"]
    assert all("release_time=release_date" in payload["scope"] for payload in payloads[1:])
    assert all(
        payload["plotted_rows"] == len(payload["records"])
        for payload in payloads
    )
    for figure in figures:
        assert figure is not None
        plt.close(figure)


def test_all_zero_missingness_is_omitted_with_reader_reason(
    annual_frame: pd.DataFrame,
) -> None:
    payload = compute_chart_payload(
        annual_frame,
        _plan("missingness_bar", [], "missingness"),
        _provenance(annual_frame),
    )
    assert payload["status"] == "omitted"
    assert "all-zero missingness chart" in payload["omission_reason"]


def test_heatmap_labels_are_bounded(monthly_frame: pd.DataFrame) -> None:
    payload = compute_chart_payload(
        monthly_frame,
        _plan("coverage_heatmap", ["date", "commodity"]),
        _provenance(monthly_frame),
    )
    figure = render_chart_payload(payload)
    assert figure is not None
    assert len(figure.axes[0].get_xticklabels()) <= 8
    assert len(figure.axes[0].get_yticklabels()) <= 8
    plt.close(figure)


def test_year_month_components_render_monthly_instead_of_annual_pooling() -> None:
    frame = pd.DataFrame(
        [
            {
                "commodity": "oni",
                "month": month,
                "value": year - 2019 + month / 100,
                "year": year,
            }
            for year in range(2020, 2023)
            for month in range(1, 13)
        ]
    )
    plan = {
        **_plan("line", ["year", "month", "value", "commodity"], "monthly_history"),
        "measure_units": {"value": "index"},
        "series_dimensions": ["commodity"],
        "time_components": ["year", "month"],
    }
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        payload = compute_chart_payload(frame, plan, _provenance(frame))
        figure = render_chart_payload(payload)
    assert payload["status"] == "ready"
    assert "time=year+month" in payload["scope"]
    assert payload["plotted_rows"] == 36
    assert len({row["x"] for row in payload["records"]}) == 36
    assert figure is not None
    assert len(figure.axes[0].get_xticklabels()) <= 8
    plt.close(figure)

    invalid = frame.copy()
    invalid.loc[invalid.index[:9], "month"] = 13
    omitted = compute_chart_payload(invalid, plan, _provenance(invalid))
    assert omitted["status"] == "omitted"
    assert "invalid for more than 20%" in omitted["omission_reason"]


def test_vintage_selects_twelve_complete_fully_labelled_series_without_pooling() -> None:
    rows = []
    for attribute_index in range(13):
        for release in range(2):
            rows.append(
                {
                    "attribute": f"attribute_{attribute_index:02d}",
                    "commodity": "corn",
                    "estimate": 100 + attribute_index + release,
                    "marketing_year": "2024/25",
                    "release_date": f"2024-0{release + 1}-01",
                    "row_label": f"row_{attribute_index:02d}",
                }
            )
    frame = pd.DataFrame(rows)
    plan = {
        **_plan(
            "vintage_line",
            [
                "release_date",
                "estimate",
                "marketing_year",
                "commodity",
                "attribute",
                "row_label",
            ],
            "vintage",
        ),
        "measure_units": {"estimate": "metric tonnes"},
        "series_dimensions": [
            "marketing_year",
            "commodity",
            "attribute",
            "row_label",
        ],
    }
    payload = compute_chart_payload(frame, plan, _provenance(frame))
    assert payload["status"] == "ready"
    assert len({row["series"] for row in payload["records"]}) == 12
    assert "excluded series=1" in payload["scope"]
    assert "complete but outside cap=1" in payload["scope"]
    assert "no pooling" in payload["scope"]
    assert all(
        set(("marketing_year=", "commodity=", "attribute=", "row_label="))
        <= {part.split("=", maxsplit=1)[0] + "=" for part in row["series"].split(" | ")}
        for row in payload["records"]
    )


def test_wasde_single_series_charts_name_every_selected_semantic_dimension() -> None:
    dimensions = [
        "marketing_year",
        "commodity",
        "region",
        "attribute",
        "table_type",
    ]
    selected_values = {
        "marketing_year": "2025/26",
        "commodity": "Corn",
        "region": "United States",
        "attribute": "Production",
        "table_type": "World balance",
    }
    rows = []
    for index, release_date in enumerate(pd.date_range("2025-05-01", periods=3, freq="MS")):
        rows.append(
            {
                **selected_values,
                "release_date": release_date,
                "estimate": 100.0 + index,
                "revision": float(index),
            }
        )
    for index, release_date in enumerate(pd.date_range("2025-05-01", periods=2, freq="MS")):
        rows.append(
            {
                **selected_values,
                "commodity": "Wheat",
                "release_date": release_date,
                "estimate": 80.0 + index,
                "revision": float(-index),
            }
        )
    frame = pd.DataFrame(rows)
    plans = [
        {
            **_plan(
                "vintage_line",
                ["release_date", "estimate", *dimensions],
                "vintage_trajectory",
            ),
            "max_series": 1,
            "minimum_rows": 2,
            "series_dimensions": dimensions,
        },
        {
            **_plan(
                "revision_distribution",
                ["release_date", "estimate", "revision", *dimensions],
                "revision_distribution",
            ),
            "max_series": 1,
            "series_dimensions": dimensions,
        },
    ]

    for plan in plans:
        payload = compute_chart_payload(frame, plan, _provenance(frame))
        assert payload["status"] == "ready"
        assert payload["selected_series"] == [
            "marketing_year=2025/26 | commodity=Corn | region=United States | "
            "attribute=Production | table_type=World balance"
        ]
        for column, value in selected_values.items():
            assert f"{column}={value}" in payload["scope"]
        figure = render_chart_payload(payload)
        assert figure is not None
        for column, value in selected_values.items():
            assert f"{column}={value}" in figure._suptitle.get_text()
        plt.close(figure)


def test_row_level_units_are_preserved_or_explicitly_rejected() -> None:
    dates = pd.date_range("2024-01-01", periods=8, freq="MS")
    frame = pd.DataFrame(
        [
            {"date": date, "unit": unit, "value": index, "variable": variable}
            for variable, unit in (("rain", "mm"), ("temperature", "celsius"))
            for index, date in enumerate(dates)
        ]
    )
    plan = {
        **_plan("line", ["date", "value", "variable", "unit"], "long_value"),
        "series_dimensions": ["variable"],
        "unit_column": "unit",
    }
    payload = compute_chart_payload(frame, plan, _provenance(frame))
    assert payload["status"] == "omitted"
    assert "2 row-level units" in payload["omission_reason"]
    assert "were not overlaid" in payload["omission_reason"]

    rain = frame.loc[frame["variable"].eq("rain")].copy()
    ready = compute_chart_payload(rain, plan, _provenance(rain))
    assert ready["status"] == "ready"
    assert ready["unit"] == "mm"
    assert all(
        "variable=rain | unit=mm" == row["series"] for row in ready["records"]
    )

    split = compute_chart_payloads(frame, [plan], _provenance(frame))
    assert len(split) == 2
    assert all(payload["status"] == "ready" for payload in split)
    assert {payload["unit"] for payload in split} == {"mm", "celsius"}
    assert all("no cross-unit pooling" in payload["scope"] for payload in split)


def test_row_unit_split_uses_dominant_contributing_unit_as_representative() -> None:
    dates = pd.date_range("2024-01-01", periods=18, freq="MS")
    frame = pd.DataFrame(
        {
            "date": dates,
            "estimate": [100.0 + index for index in range(18)],
            "unit": ["Thousand Metric Tons"] * 10 + ["Con't"] * 8,
        }
    )
    plan = {
        **_plan("line", ["date", "estimate", "unit"], "wasde_history"),
        "measure_columns": ["estimate"],
        "unit_column": "unit",
        "max_series": 4,
    }

    payloads = compute_chart_payloads(frame, [plan], _provenance(frame))

    assert [payload["unit"] for payload in payloads] == [
        "Thousand Metric Tons",
        "Con't",
    ]
    assert payloads[0]["chart_id"] == "wasde_history"
    assert payloads[1]["chart_id"].endswith("__unit_con_t")


def test_compatible_measures_can_share_one_overlay(monthly_frame: pd.DataFrame) -> None:
    plan = {
        **_plan("line", ["date", "value", "value_2", "commodity"], "levels"),
        "measure_units": {"value": "index points", "value_2": "index points"},
    }
    payloads = compute_chart_payloads(monthly_frame, [plan], _provenance(monthly_frame))
    assert len(payloads) == 1
    assert payloads[0]["status"] == "ready"
    assert {row["measure"] for row in payloads[0]["records"]} == {"value", "value_2"}
    assert payloads[0]["unit"] == "index points"


def test_line_sufficiency_uses_distinct_x_within_each_series() -> None:
    dates = pd.date_range("2024-01-01", periods=8, freq="MS")
    frame = pd.DataFrame(
        [
            {"date": date, "geography": "complete", "value": index}
            for index, date in enumerate(dates)
        ]
        + [
            {"date": dates[0], "geography": "repeated", "value": index}
            for index in range(20)
        ]
    )
    plan = {
        **_plan("line", ["date", "value", "geography"], "history"),
        "measure_units": {"value": "index"},
        "series_dimensions": ["geography"],
    }
    payload = compute_chart_payload(frame, plan, _provenance(frame))
    assert payload["status"] == "ready"
    assert {row["series"] for row in payload["records"]} == {"geography=complete"}
    assert payload["plotted_rows"] == 8


def test_single_ordered_component_is_not_misrepresented_as_a_date() -> None:
    frame = pd.DataFrame(
        {
            "commodity": ["coffee"] * 8,
            "production_thousand_bags": np.arange(8) + 100,
            "region": ["national"] * 8,
            "safra_year": [2024] * 8,
            "survey_number": np.arange(1, 9),
        }
    )
    plan = {
        **_plan(
            "line",
            [
                "survey_number",
                "production_thousand_bags",
                "safra_year",
                "commodity",
                "region",
            ],
            "survey_sequence",
        ),
        "measure_units": {"production_thousand_bags": "thousand bags"},
        "series_dimensions": ["safra_year", "commodity", "region"],
        "time_components": ["survey_number"],
    }
    payload = compute_chart_payload(frame, plan, _provenance(frame))
    assert payload["status"] == "ready"
    assert "time=survey_number" in payload["scope"]
    assert {row["x"] for row in payload["records"]} == set(range(1, 9))
    figure = render_chart_payload(payload)
    assert figure is not None
    assert figure.axes[0].get_xlabel() == "survey_number"
    plt.close(figure)


def test_high_cardinality_annual_panel_uses_bounded_non_pooled_views() -> None:
    frame = pd.DataFrame(
        [
            {
                "commodity": commodity,
                "production_mt": 1_000 + commodity_index * 100 + state_index * 10 + year,
                "state": state,
                "year": year,
            }
            for commodity_index, commodity in enumerate(
                ("corn", "cotton", "rice", "soy", "wheat")
            )
            for state_index, state in enumerate(("IA", "IL", "NE", "TX"))
            for year in range(2016, 2024)
        ]
    )
    dimensions = ["commodity", "state"]
    common = {
        "measure_units": {"production_mt": "metric tonnes"},
        "series_dimensions": dimensions,
    }
    plans = [
        {
            **_plan(
                "line",
                ["year", "production_mt", *dimensions],
                "history",
            ),
            **common,
        },
        {
            **_plan(
                "ranked_bar",
                ["year", "production_mt", *dimensions],
                "latest_ranking",
            ),
            **common,
        },
        {
            **_plan(
                "distribution",
                ["production_mt", *dimensions],
                "distribution",
            ),
            **common,
        },
        {
            **_plan(
                "coverage_heatmap",
                ["year", *dimensions],
                "coverage",
            ),
            **common,
        },
    ]
    payloads = compute_chart_payloads(frame, plans, _provenance(frame))
    by_id = {payload["chart_id"]: payload for payload in payloads}
    assert by_id["history"]["status"] == "ready"
    assert "selected 12 of 20 complete semantic series" in by_id["history"]["scope"]
    assert "excluded series=8" in by_id["history"]["scope"]
    for chart_id in ("latest_ranking", "distribution", "coverage"):
        payload = by_id[chart_id]
        assert payload["status"] == "ready", payload["omission_reason"]
        expected = 4 if chart_id == "distribution" else 12
        assert (
            f"top {expected} of 20 semantic series by contributing-row count"
            in payload["scope"]
        )
        assert payload["plotted_rows"] == len(payload["records"])


def test_reviewed_tiny_exact_history_can_treat_each_annual_point_as_meaningful() -> None:
    frame = pd.DataFrame(
        {
            "commodity": ["palm_oil"] * 6,
            "production_cpo_mt": np.arange(6) * 100_000 + 17_000_000,
            "year": np.arange(2018, 2024),
        }
    )
    default_plan = {
        **_plan(
            "line",
            ["year", "production_cpo_mt", "commodity"],
            "measure_history",
        ),
        "measure_units": {"production_cpo_mt": "metric tonnes"},
        "series_dimensions": ["commodity"],
    }
    omitted = compute_chart_payload(frame, default_plan, _provenance(frame))
    assert omitted["status"] == "omitted"
    assert "at least 8 distinct ordered observations" in omitted["omission_reason"]

    reviewed_plan = {
        **default_plan,
        "intentional_points": True,
        "minimum_rows": 2,
    }
    ready = compute_chart_payload(frame, reviewed_plan, _provenance(frame))
    assert ready["status"] == "ready"
    assert ready["plotted_rows"] == 6
    figure = render_chart_payload(ready)
    assert figure is not None
    plt.close(figure)


def test_measure_plans_group_only_compatible_unit_and_scale_families() -> None:
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=8, freq="MS"),
            "commodity": ["cocoa"] * 8,
            "production_kg": np.arange(8) + 100,
            "imports_kg": np.arange(8) + 50,
            "import_share_pct": np.linspace(10, 20, 8),
        }
    )
    plan = {
        **_plan(
            "line",
            [
                "date",
                "production_kg",
                "imports_kg",
                "import_share_pct",
                "commodity",
            ],
            "history",
        ),
        "measure_units": {
            "production_kg": "kg",
            "imports_kg": "kg",
            "import_share_pct": "%",
        },
        "series_dimensions": ["commodity"],
    }
    payloads = compute_chart_payloads(frame, [plan], _provenance(frame))
    ready = [payload for payload in payloads if payload["status"] == "ready"]
    assert len(ready) == 2
    assert {row["measure"] for row in ready[0]["records"]} == {
        "production_kg",
        "imports_kg",
    }
    assert {row["measure"] for row in ready[1]["records"]} == {
        "import_share_pct"
    }
    assert [payload["unit"] for payload in ready] == ["kg", "%"]


def test_complete_series_selection_reports_cap_and_underpowered_counts() -> None:
    dates = pd.date_range("2024-01-01", periods=8, freq="MS")
    rows = []
    for index in range(20):
        available = dates if index < 15 else dates[:-1]
        rows.extend(
            {
                "date": date,
                "region": f"region_{index:02d}",
                "commodity": "corn",
                "value": index + position,
            }
            for position, date in enumerate(available)
        )
    frame = pd.DataFrame(rows)
    plan = {
        **_plan("line", ["date", "value", "commodity", "region"], "history"),
        "measure_units": {"value": "index"},
        "series_dimensions": ["commodity", "region"],
    }
    payload = compute_chart_payload(frame, plan, _provenance(frame))
    assert payload["status"] == "ready"
    assert len({row["series"] for row in payload["records"]}) == 12
    assert "selected 12 of 15 complete semantic series" in payload["scope"]
    assert "excluded series=8" in payload["scope"]
    assert "complete but outside cap=3, underpowered=5" in payload["scope"]
    assert all("commodity=corn | region=" in row["series"] for row in payload["records"])


def test_progress_scale_series_selection_handles_4798_complete_series() -> None:
    frame = pd.DataFrame(
        [
            {
                "week": week,
                "commodity": "corn",
                "region": f"region_{series_index:04d}",
                "progress_pct": week * 10 + series_index / 10_000,
            }
            for series_index in range(4_798)
            for week in range(1, 9)
        ]
    )
    plan = {
        **_plan(
            "season_curve",
            ["week", "progress_pct", "commodity", "region"],
            "progress_curve",
        ),
        "measure_units": {"progress_pct": "%"},
        "series_dimensions": ["commodity", "region"],
    }
    payload = compute_chart_payload(frame, plan, _provenance(frame))
    assert payload["status"] == "ready"
    assert len({row["series"] for row in payload["records"]}) == 12
    assert "selected 12 of 4,798 complete semantic series" in payload["scope"]
    assert "excluded series=4,786" in payload["scope"]
    assert "no pooling" in payload["scope"]


def test_coverage_over_600_cells_is_adaptively_bucketed_without_row_loss() -> None:
    frame = pd.DataFrame(
        [
            {"year": year, "region": f"region_{region:02d}"}
            for region in range(12)
            for year in range(1900, 2000)
        ]
    )
    plan = {
        **_plan("coverage_heatmap", ["year", "region"], "coverage"),
        "coverage_grain": "year",
        "series_dimensions": ["region"],
    }
    payload = compute_chart_payload(frame, plan, _provenance(frame))
    assert payload["status"] == "ready"
    assert payload["plotted_rows"] <= 600
    assert sum(row["value"] for row in payload["records"]) == len(frame)
    assert "cell cap" in payload["scope"]
    assert "600 populated cells" in payload["scope"]


def test_split_by_contract_preserves_futures_facets_without_pooling() -> None:
    frame = pd.DataFrame(
        [
            {"date": date, "contract": contract, "close": index + offset}
            for contract, offset in (("cocoa", 100), ("corn", 10))
            for index, date in enumerate(pd.date_range("2024-01-01", periods=8, freq="D"))
        ]
    )
    plan = {
        **_plan("line", ["date", "contract", "close"], "contract_history"),
        "measure_columns": ["close"],
        "measure_units": {"close": "normalized index"},
        "split_by": ["contract"],
    }
    payload = compute_chart_payload(frame, plan, _provenance(frame))
    assert payload["status"] == "ready"
    assert {row["facet"] for row in payload["records"]} == {
        "contract=cocoa",
        "contract=corn",
    }
    assert {row["semantic_series"] for row in payload["records"]} == {
        "contract=cocoa",
        "contract=corn",
    }
    assert {row["series"] for row in payload["records"]} == {"all observations"}
    figure = render_chart_payload(payload)
    assert figure is not None
    assert {axis.get_title() for axis in figure.axes if axis.get_visible()} >= {
        "contract=cocoa",
        "contract=corn",
    }
    plt.close(figure)


def test_split_by_prevents_same_state_pooling_across_commodity_and_country() -> None:
    frame = pd.DataFrame(
        [
            {
                "commodity": commodity,
                "country": country,
                "production_mt": year + offset,
                "state": "shared-state",
                "year": year,
            }
            for commodity, country, offset in (
                ("corn", "US", 100),
                ("soy", "BR", 1_000),
            )
            for year in range(2016, 2024)
        ]
    )
    plan = {
        **_plan(
            "line",
            ["year", "production_mt", "state", "commodity", "country"],
            "production_history",
        ),
        "measure_columns": ["production_mt"],
        "measure_units": {"production_mt": "metric tonnes"},
        "series_dimensions": ["state"],
        "split_by": ["commodity", "country"],
    }
    payload = compute_chart_payload(frame, plan, _provenance(frame))
    assert payload["status"] == "ready"
    assert len({row["semantic_series"] for row in payload["records"]}) == 2
    assert {row["series"] for row in payload["records"]} == {
        "state=shared-state"
    }
    assert len(payload["records"]) == 16
    assert "label dimensions=state, commodity, country" in payload["scope"]


def test_crop_curve_split_and_measure_routes_keep_week_axis_and_full_grain() -> None:
    frame = pd.DataFrame(
        [
            {
                "commodity": commodity,
                "progress_pct": week * 5 + offset,
                "state": state,
                "week_number": week,
                "year": year,
            }
            for commodity, state, offset in (("corn", "IA", 0), ("soy", "IL", 2))
            for year in (2023, 2024)
            for week in range(1, 9)
        ]
    )
    plan = {
        **_plan(
            "season_curve",
            ["week_number", "progress_pct", "year", "commodity", "state"],
            "progress",
        ),
        "cutoff_mode": "governed_axis",
        "measure_columns": ["progress_pct"],
        "measure_units": {"progress_pct": "%"},
        "series_dimensions": ["year"],
        "split_by": ["commodity", "state"],
        "time_components": ["week_number"],
    }
    payload = compute_chart_payload(frame, plan, _provenance(frame))
    assert payload["status"] == "ready"
    assert {row["cutoff"] for row in payload["records"]} == set(range(1, 9))
    assert len({row["semantic_series"] for row in payload["records"]}) == 4
    assert {row["facet"] for row in payload["records"]} == {
        "commodity=corn | state=IA",
        "commodity=soy | state=IL",
    }
    assert all(row["series"].startswith("year=") for row in payload["records"])


def test_datetime_season_cutoff_is_ordinal_within_series_not_iso_week() -> None:
    dates = pd.date_range("2024-12-15", periods=8, freq="W")
    frame = pd.DataFrame(
        {
            "market_year": ["2024/25"] * 8,
            "week_ending_date": dates,
            "weekly_exports_1000mt": np.arange(8) + 10,
        }
    )
    plan = {
        **_plan(
            "season_curve",
            ["week_ending_date", "weekly_exports_1000mt", "market_year"],
            "weekly_flow",
        ),
        "cutoff_mode": "within_series_ordinal",
        "measure_columns": ["weekly_exports_1000mt"],
        "measure_units": {"weekly_exports_1000mt": "thousand tonnes"},
        "series_dimensions": ["market_year"],
    }
    payload = compute_chart_payload(frame, plan, _provenance(frame))
    assert payload["status"] == "ready"
    assert {row["cutoff"] for row in payload["records"]} == set(range(1, 9))
    assert "derived; not ISO week" in payload["scope"]
    assert payload["encoding"]["x_label"].endswith("(derived; not ISO week)")


def test_supported_type_inventory_is_complete() -> None:
    assert SUPPORTED_CHART_TYPES == {
        "anomaly_heatmap",
        "calendar_heatmap",
        "change_distribution",
        "composition",
        "coverage_heatmap",
        "distribution",
        "dual_axis",
        "first_latest",
        "increment",
        "line",
        "milestone",
        "missingness_bar",
        "parity",
        "ranked_bar",
        "release_depth",
        "revision_distribution",
        "season_curve",
        "seasonal_profile",
        "signed_bar",
        "vintage_line",
        "year_over_year",
    }
