"""Unit tests for leviathan.features.calendar."""
from __future__ import annotations

from datetime import date

import pytest
from leviathan.features.calendar import CropCalendar, load_crop_calendars


@pytest.fixture()
def arabica() -> CropCalendar:
    """Arabica: Apr-start crop year, grain_fill crosses the calendar boundary."""
    return CropCalendar(
        commodity="arabica_coffee",
        crop_year_start_month=4,
        mkt_year_offset=-1,
        stages={
            "frost_risk": (6, 7),
            "flowering": (8, 10),
            "grain_fill": (11, 3),
        },
        gdd_window=("flowering", "grain_fill"),
    )


@pytest.fixture()
def corn() -> CropCalendar:
    return CropCalendar(
        commodity="corn_cbot",
        crop_year_start_month=5,
        mkt_year_offset=-1,
        stages={"planting": (5, 5), "silking": (7, 7), "grain_fill": (8, 8)},
        gdd_window=("planting", "grain_fill"),
    )


def test_crop_year_span(corn: CropCalendar) -> None:
    assert corn.crop_year_start(2024) == date(2024, 5, 1)
    assert corn.crop_year_end(2024) == date(2025, 4, 30)


def test_stage_window_same_year(corn: CropCalendar) -> None:
    window = corn.stage_window("silking", 2024)
    assert window.start_date == date(2024, 7, 1)
    assert window.end_date == date(2024, 7, 31)


def test_stage_window_cross_year(arabica: CropCalendar) -> None:
    """grain_fill Nov-Mar belongs to crop year 2023 (Apr 2023 - Mar 2024)."""
    window = arabica.stage_window("grain_fill", 2023)
    assert window.start_date == date(2023, 11, 1)
    assert window.end_date == date(2024, 3, 31)


def test_stage_window_before_start_month_lands_next_calendar_year(
    arabica: CropCalendar,
) -> None:
    """A Jan-Mar-only stage for an Apr-start crop year falls in year+1."""
    cal = CropCalendar(
        commodity="x", crop_year_start_month=4, mkt_year_offset=-1,
        stages={"late": (1, 3)},
    )
    window = cal.stage_window("late", 2023)
    assert window.start_date == date(2024, 1, 1)
    assert window.end_date == date(2024, 3, 31)


def test_gdd_dates_span_stages(arabica: CropCalendar) -> None:
    start, end = arabica.gdd_dates(2023)
    assert start == date(2023, 8, 1)   # flowering start
    assert end == date(2024, 3, 31)    # grain_fill end (next calendar year)


def test_unknown_stage_raises(corn: CropCalendar) -> None:
    with pytest.raises(KeyError):
        corn.stage_window("flowering", 2024)


def test_load_real_config() -> None:
    calendars = load_crop_calendars()
    assert "arabica_coffee" in calendars
    assert "corn_cbot" in calendars
    arabica = calendars["arabica_coffee"]
    assert arabica.crop_year_start_month == 4
    assert arabica.stages["grain_fill"] == (11, 3)
    # gdd_window stages must all exist (loader validates)
    for cal in calendars.values():
        if cal.gdd_window:
            assert cal.gdd_window[0] in cal.stages
            assert cal.gdd_window[1] in cal.stages


def test_load_rejects_bad_month(tmp_path) -> None:
    bad = tmp_path / "crop_calendars.yaml"
    bad.write_text(
        "corn_cbot:\n  crop_year_start_month: 13\n  stages: {}\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="crop_year_start_month"):
        load_crop_calendars(bad)


def test_load_rejects_gdd_stage_not_in_stages(tmp_path) -> None:
    bad = tmp_path / "crop_calendars.yaml"
    bad.write_text(
        "corn_cbot:\n"
        "  crop_year_start_month: 5\n"
        "  stages:\n    planting: [5, 5]\n"
        "  gdd_window: [planting, harvest]\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="gdd_window"):
        load_crop_calendars(bad)
