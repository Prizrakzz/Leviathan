"""SILVER-F056 stale-producer restore: raw->bronze citrus producer + season derivation.

Pins the two behaviours the stale-producer fix turns on:
  * ``current_forecast_season`` returns the CURRENT open forecast season and, during the Aug-Sep
    closed period, FALLS FORWARD to the season about to open (never the one that just closed);
  * ``parse_forecast_table_text`` reproduces the untracked producer's long-bronze layout -- column
    classification (rightmost=current, month-name=prior, year-pair=actual), crop carry-down
    (Lemons inherits ``grapefruit``), Red/White drop, (NA) drop, and footnote stripping.
"""
from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from leviathan.transforms.raw_to_bronze.nass_citrus import (
    BRONZE_COLUMNS,
    _report_month_from_filename,
    current_forecast_season,
    parse_forecast_table_text,
)


# ---------------------------------------------------------------------------
# Season derivation (the named fixed behaviour)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("as_of,expected", [
    ("2025-10-15", "2025-26"),   # October  -> season opens this year
    ("2025-12-01", "2025-26"),   # December -> same open season
    ("2026-01-13", "2025-26"),   # January  -> season opened last year
    ("2026-07-11", "2025-26"),   # July     -> still last-opened season (season end)
    ("1999-11-01", "1999-00"),   # end-year wraps to 00
])
def test_current_open_season(as_of, expected):
    assert current_forecast_season(as_of) == expected


@pytest.mark.parametrize("as_of", ["2026-08-01", "2026-08-15", "2026-09-30"])
def test_closed_season_falls_forward(as_of):
    # Aug/Sep is the closed period: the just-closed season was 2025-26; a "current season" fetch
    # must target the UPCOMING season opening this October, not the one that closed.
    got = current_forecast_season(as_of)
    assert got == "2026-27"
    assert got != "2025-26"


def test_season_accepts_date_datetime_and_iso_timestamp():
    assert current_forecast_season(dt.date(2026, 1, 13)) == "2025-26"
    assert current_forecast_season(dt.datetime(2026, 1, 13, 18, 0, 0)) == "2025-26"
    # the EventBridge scheduled-time context attribute resolves to an ISO timestamp with a Z suffix
    assert current_forecast_season("2026-01-13T18:00:00Z") == "2025-26"


def test_report_month_from_filename():
    assert _report_month_from_filename("cit0125.pdf") == 1
    assert _report_month_from_filename("cit1024.pdf") == 10
    with pytest.raises(ValueError):
        _report_month_from_filename("notacitrusfile.pdf")


# ---------------------------------------------------------------------------
# Producer table parse
# ---------------------------------------------------------------------------
# A mid-season (January) page: 2 year-pair actuals + a month-name prior + the current month, with a
# footnoted state ("California 3"), the grapefruit Red/White sub-rows, and a Lemons block whose
# Florida row carries (NA) actuals -- every quirk the untracked producer reproduced.
_JAN_TEXT = "\n".join([
    "JANUARY FORECAST",
    "January 10, 2025",
    "Citrus Production by Type - States and United States",
    "Production 1 2024-2025 Forecasted Production 1",
    "Crop and State",
    "2022-2023 2023-2024 December January",
    "(1,000 boxes) (1,000 boxes) (1,000 boxes) (1,000 boxes)",
    "Non-Valencia Oranges 2",
    "Florida ............................ 6,150 6,760 5,000 5,000",
    "California 3 ....................... 36,000 38,200 39,000 39,000",
    "Grapefruit",
    "Florida-All ....................... 1,810 1,790 1,200 1,200",
    "Red ............................... 1,560 1,550 1,050 1,050",
    "White ............................. 250 240 150 150",
    "Lemons",
    "Florida 4 ......................... (NA) (NA) 500 600",
    "Arizona ........................... 1,400 950 900 900",
    "1 Net pounds per box: footnote text.",
])

# A first-of-season (October) page: THREE year-pair actuals + the season-labelled current forecast,
# and NO prior_forecast column.
_OCT_TEXT = "\n".join([
    "OCTOBER FORECAST",
    "October 11, 2024",
    "Citrus Production by Type - States and United States",
    "Production 1 2024-2025 Forecasted Production 1",
    "Crop and State",
    "2021-2022 2022-2023 2023-2024 2024-2025",
    "(1,000 boxes) (1,000 boxes) (1,000 boxes) (1,000 boxes)",
    "All Oranges",
    "Florida ............................ 15,820 17,960 15,000 12,000",
])


def _parse_jan():
    return parse_forecast_table_text(_JAN_TEXT, "2024-25", "cit0125.pdf")


def test_schema_release_date_and_report_month():
    df = _parse_jan()
    assert list(df.columns) == BRONZE_COLUMNS
    assert (df["release_date"] == "2025-01-10").all()
    assert (df["report_month"] == 1).all()
    assert (df["season"] == "2024-25").all()
    assert (df["source"] == "usda_nass_citrus").all()
    assert df["report_month"].dtype == "int64"
    assert df["value_1000_boxes"].dtype == "float64"


def test_column_type_classification_midseason():
    df = _parse_jan()
    nvo_fl = df[(df.crop == "non_valencia_orange") & (df.state == "florida")]
    triples = set(zip(nvo_fl["col_type"], nvo_fl["col_label"], nvo_fl["value_1000_boxes"]))
    # two year-pair actuals, a month-name prior, and the rightmost month as current
    assert ("actual", "2022-2023", 6150.0) in triples
    assert ("actual", "2023-2024", 6760.0) in triples
    assert ("prior_forecast", "December", 5000.0) in triples
    assert ("current_forecast", "January", 5000.0) in triples
    assert set(nvo_fl["col_type"]) == {"actual", "prior_forecast", "current_forecast"}


def test_footnoted_state_is_parsed():
    df = _parse_jan()
    cal = df[(df.crop == "non_valencia_orange") & (df.state == "california")]
    assert len(cal) == 4  # "California 3" footnote stripped -> row kept, 4 columns
    assert cal[cal.col_type == "current_forecast"]["value_1000_boxes"].iloc[0] == 39000.0


def test_grapefruit_red_white_dropped():
    df = _parse_jan()
    # Red / White sub-rows are not recognised states -> never emitted
    assert not df["state"].isin(["red", "white"]).any()
    gf_fl_all = df[(df.crop == "grapefruit") & (df.state == "florida") & (df.col_type == "actual")]
    assert set(gf_fl_all["value_1000_boxes"]) == {1810.0, 1790.0}  # only Florida-All actuals


def test_lemons_carry_grapefruit_and_na_drop():
    df = _parse_jan()
    # Lemons is not a recognised crop header -> its rows inherit the last crop (grapefruit)
    gf_az = df[(df.crop == "grapefruit") & (df.state == "arizona")]
    assert not gf_az.empty
    assert gf_az[gf_az.col_type == "current_forecast"]["value_1000_boxes"].iloc[0] == 900.0
    # the Lemons Florida row's (NA) actuals are dropped, but its forecasts survive -> grapefruit/
    # florida current now has BOTH the Florida-All (1200) and the carried lemon (600) value
    gf_fl_cur = df[(df.crop == "grapefruit") & (df.state == "florida")
                   & (df.col_type == "current_forecast")]
    assert set(gf_fl_cur["value_1000_boxes"]) == {1200.0, 600.0}
    # no (NA) leaked in as a value
    assert df["value_1000_boxes"].notna().all()


def test_october_three_actuals_no_prior():
    df = parse_forecast_table_text(_OCT_TEXT, "2024-25", "cit1024.pdf")
    assert (df["report_month"] == 10).all()
    ao_fl = df[(df.crop == "all_orange") & (df.state == "florida")]
    assert (ao_fl["col_type"] != "prior_forecast").all()          # October has no prior forecast
    assert (ao_fl["col_type"] == "actual").sum() == 3             # three year-pair actual columns
    cur = ao_fl[ao_fl.col_type == "current_forecast"].iloc[0]
    assert cur["col_label"] == "2024-2025" and cur["value_1000_boxes"] == 12000.0


def test_empty_or_malformed_page_is_handled():
    # a page with the units row but a non-4-column header raises (fail-closed, not silent junk)
    bad = "\n".join(["x", "a b c", "(1,000 boxes) (1,000 boxes) (1,000 boxes)"])
    with pytest.raises(ValueError):
        parse_forecast_table_text(bad, "2024-25", "cit0125.pdf")
