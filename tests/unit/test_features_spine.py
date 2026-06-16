"""Spine assembly tests + the truncate-at-T anti-leakage property test."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from leviathan.features.calendar import load_crop_calendars
from leviathan.features.registry import load_registry
from leviathan.features.spine import (
    SPINE_COLUMNS,
    SPINE_NATURAL_KEY,
    build_spine,
    default_calendar,
)

COUNTRY = "united_states"
REGION = "us_corn_belt"
YEARS = list(range(1995, 2015))


@pytest.fixture(scope="module")
def registry():
    return load_registry()


@pytest.fixture(scope="module")
def corn_calendar():
    return load_crop_calendars()["corn_cbot"]


def _weather(variable: str, source: str, rng: np.random.RandomState) -> pd.DataFrame:
    frames = []
    for year in YEARS:
        days = pd.date_range(f"{year}-05-01", f"{year}-10-31", freq="D")
        if variable == "precipitation_mm":
            values = np.clip(rng.normal(4.0 + 0.1 * (year % 5), 2.0, len(days)), 0, None)
        elif variable == "temperature_2m_max_c":
            values = rng.normal(28.0, 3.0, len(days))
        else:
            values = rng.normal(15.0, 3.0, len(days))
        frames.append(pd.DataFrame({
            "date": days, "year": days.year, "month": days.month, "day": days.day,
            "country": COUNTRY, "region": REGION, "source": source,
            "variable": variable, "value": values,
        }))
    return pd.concat(frames, ignore_index=True)


@pytest.fixture(scope="module")
def synthetic_inputs() -> dict[str, pd.DataFrame]:
    rng = np.random.RandomState(42)
    chirps = _weather("precipitation_mm", "chirps", rng)
    nasa = pd.concat([
        _weather("temperature_2m_max_c", "nasa_power", rng),
        _weather("temperature_2m_min_c", "nasa_power", rng),
    ], ignore_index=True)

    faostat_rows = []
    for year in range(1993, 2015):
        production = 1000.0 + 40.0 * (year - 1993) + rng.normal(0, 25)
        for variable, value in (
            ("production_quantity", production),
            ("area_harvested", production / 10.0),
            ("yield", 10.0),
        ):
            faostat_rows.append({
                "country": COUNTRY, "variable": variable, "year": year,
                "value": value, "unit": "t",
            })
    faostat = pd.DataFrame(faostat_rows)

    psd_rows = []
    for my in range(1994, 2015):
        # One April release of marketing year `my`, published in my+1 —
        # visible to crop year my+1 (planting May 1 of my+1).
        psd_rows.append({
            "leviathan_slug": "corn_cbot", "country": COUNTRY,
            "market_year": my, "wasde_release_month": 4,
            "release_date": f"{my + 1}-04-11",
            "su_ratio": 0.10 + 0.005 * (my % 7),
            "su_ratio_yoy_delta": 0.001 * (my % 5 - 2),
            "production_mt_revision": float(my % 3),
            "ending_stocks_mt_revision": float(my % 2),
        })
    psd = pd.DataFrame(psd_rows)

    return {
        "weather:chirps": chirps,
        "weather:nasa_power": nasa,
        "production:faostat": faostat,
        "psd": psd,
    }


def _build(registry, calendar, inputs, crop_years):
    return build_spine(
        commodity="corn_cbot",
        crop_years=crop_years,
        countries=[COUNTRY],
        calendar=calendar,
        registry=registry,
        inputs=inputs,
    )


def test_spine_structure_and_validation(registry, corn_calendar, synthetic_inputs) -> None:
    result = _build(registry, corn_calendar, synthetic_inputs, YEARS)
    assert result.passed, result.report["hard_failures"]
    df = result.df
    assert list(df.columns) == SPINE_COLUMNS
    assert not df.duplicated(subset=SPINE_NATURAL_KEY).any()
    assert df["crop_year"].dtype == "int32"
    assert df["value"].dtype == "float64"

    features = set(df["feature"])
    # Weather, production, and S/D families all present
    assert f"chirps_precip_z_{REGION}_silking" in features
    assert f"gdd_z_{REGION}" in features
    assert "faostat_production_yoy" in features
    assert "psd_ending_stock_su_ratio" in features
    assert "label_production_quantity" in features

    # Labels flagged, features not
    labels = df.loc[df["feature"] == "label_production_quantity", "is_label"]
    assert labels.all()
    assert not df.loc[df["feature"] == "faostat_production_yoy", "is_label"].any()

    # event_time = crop-year start (May 1 for corn)
    sample = df.iloc[0]
    assert sample["event_time"].month == 5
    assert sample["event_time"].year == sample["crop_year"]


def test_spine_empty_inputs_yields_availability_flags_only(registry) -> None:
    result = build_spine(
        commodity="frozen_orange_juice",
        crop_years=[2010],
        countries=["brazil"],
        calendar=default_calendar("frozen_orange_juice"),
        registry=registry,
        inputs={},
    )
    assert result.passed
    features = set(result.df["feature"])
    assert features <= {"faostat_available", "psd_available"}
    assert (result.df["value"] == 0.0).all()


def test_validation_rejects_duplicate_natural_keys(registry, corn_calendar) -> None:
    """Two specs emitting the same feature name must block the write."""
    from leviathan.features.spine import _validate

    dupes = pd.DataFrame({
        "country": [COUNTRY, COUNTRY],
        "crop_year": [2010, 2010],
        "feature": ["psd_available", "psd_available"],
        "value": [1.0, 0.0],
        "is_label": [False, False],
        "_family": ["psd_available", "psd_available"],
    })
    report = _validate(dupes, list(registry.specs), "corn_cbot")
    assert not report["passed"]
    assert report["hard_failures"]["duplicate_natural_keys"] == 1


def test_validation_rejects_out_of_range_values(registry) -> None:
    from leviathan.features.spine import _validate

    bad = pd.DataFrame({
        "country": [COUNTRY],
        "crop_year": [2010],
        "feature": ["psd_available"],
        "value": [7.0],            # availability flag must be 0/1
        "is_label": [False],
        "_family": ["psd_available"],
    })
    report = _validate(bad, list(registry.specs), "corn_cbot")
    assert not report["passed"]
    assert "psd_available" in report["hard_failures"]["range_violations"]


# ---------------------------------------------------------------------------
# Anti-leakage property test: deleting the future must not change the past
# ---------------------------------------------------------------------------

def _truncate(inputs: dict[str, pd.DataFrame], cutoff_year: int) -> dict[str, pd.DataFrame]:
    cutoff = pd.Timestamp(f"{cutoff_year}-01-01")
    out = {}
    for key, df in inputs.items():
        if "date" in df.columns:
            out[key] = df.loc[pd.to_datetime(df["date"]) < cutoff]
        elif "release_date" in df.columns:
            out[key] = df.loc[pd.to_datetime(df["release_date"]) < cutoff]
        elif "year" in df.columns:
            out[key] = df.loc[pd.to_numeric(df["year"]) < cutoff_year]
        else:
            out[key] = df
    return out


def test_truncate_at_t_leaves_the_past_byte_identical(
    registry, corn_calendar, synthetic_inputs
) -> None:
    cutoff_year = 2010
    compare_through = cutoff_year - 2  # windows spanning calendar years

    full = _build(registry, corn_calendar, synthetic_inputs, YEARS)
    truncated = _build(
        registry, corn_calendar,
        _truncate(synthetic_inputs, cutoff_year),
        [y for y in YEARS if y <= compare_through],
    )

    full_past = (
        full.df.loc[full.df["crop_year"] <= compare_through]
        .sort_values(SPINE_NATURAL_KEY).reset_index(drop=True)
    )
    trunc_past = (
        truncated.df.loc[truncated.df["crop_year"] <= compare_through]
        .sort_values(SPINE_NATURAL_KEY).reset_index(drop=True)
    )

    pd.testing.assert_frame_equal(full_past, trunc_past)
    assert len(full_past) > 0, "property test must compare a non-empty past"
