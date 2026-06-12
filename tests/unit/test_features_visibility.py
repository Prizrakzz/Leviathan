"""Unit tests for leviathan.features.visibility.

The prior_marketing_year tests pin the worked example documented in
desiredstate.md: US corn crop year 2024 (planted May 2024) must join marketing
year 2023/24 using the latest release published on/before 2024-05-01 — never
the 2024/25 marketing year that begins at harvest, never a later vintage.
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest
from leviathan.features.calendar import CropCalendar
from leviathan.features.visibility import VisibilityError, event_time, visible_slice

CORN = CropCalendar(
    commodity="corn_cbot", crop_year_start_month=5, mkt_year_offset=-1,
    stages={"planting": (5, 5)},
)


def test_crop_year_direct_bounds() -> None:
    df = pd.DataFrame({
        "date": ["2024-04-30", "2024-05-01", "2025-04-30", "2025-05-01"],
        "value": [1.0, 2.0, 3.0, 4.0],
    })
    visible = visible_slice(df, "crop_year_direct", CORN, 2024)
    # Crop year 2024 = [2024-05-01, 2025-04-30] inclusive
    assert visible["value"].tolist() == [2.0, 3.0]


def test_prior_history_excludes_observation_year() -> None:
    df = pd.DataFrame({"year": [2022, 2023, 2024, 2025], "value": [1, 2, 3, 4]})
    visible = visible_slice(df, "prior_history", CORN, 2024)
    assert visible["year"].tolist() == [2022, 2023]


def test_prior_marketing_year_desiredstate_worked_example() -> None:
    """US corn crop_year 2024 -> MY 2023, latest release <= 2024-05-01."""
    df = pd.DataFrame({
        "market_year": [2023, 2023, 2023, 2024, 2023],
        "release_date": [
            "2024-02-08",  # visible, superseded
            "2024-04-11",  # visible, latest before planting -> WINS
            "2024-06-12",  # after crop-year start -> excluded
            "2024-04-11",  # wrong marketing year (the one starting at harvest)
            "2023-11-09",  # visible, superseded
        ],
        "su_ratio": [0.10, 0.12, 0.14, 0.99, 0.08],
    })
    visible = visible_slice(df, "prior_marketing_year", CORN, 2024)
    assert len(visible) == 1
    assert visible["su_ratio"].iloc[0] == 0.12


def test_prior_marketing_year_no_vintage_before_planting() -> None:
    df = pd.DataFrame({
        "market_year": [2023],
        "release_date": ["2024-06-12"],
        "su_ratio": [0.14],
    })
    visible = visible_slice(df, "prior_marketing_year", CORN, 2024)
    assert visible.empty


def test_unknown_visibility_class_raises() -> None:
    with pytest.raises(VisibilityError):
        visible_slice(pd.DataFrame(), "latest", CORN, 2024)


def test_missing_columns_raise() -> None:
    with pytest.raises(VisibilityError, match="date"):
        visible_slice(pd.DataFrame({"x": [1]}), "crop_year_direct", CORN, 2024)
    with pytest.raises(VisibilityError, match="year"):
        visible_slice(pd.DataFrame({"x": [1]}), "prior_history", CORN, 2024)
    with pytest.raises(VisibilityError, match="market_year"):
        visible_slice(pd.DataFrame({"x": [1]}), "prior_marketing_year", CORN, 2024)


def test_event_time_is_crop_year_start() -> None:
    assert event_time(CORN, 2024) == date(2024, 5, 1)
