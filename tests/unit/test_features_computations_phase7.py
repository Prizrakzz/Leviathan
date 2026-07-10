from __future__ import annotations

import pandas as pd
import pytest
from leviathan.features.calendar import CropCalendar
from leviathan.features.computations.base import FeatureContext
from leviathan.features.computations.phase7_fundamentals import (
    compute_ams_cotton_quality,
    compute_nass_citrus_revisions,
    compute_unica_sugar_biweekly,
    compute_wasde_direct_revisions,
)

CORN = CropCalendar(
    commodity="corn_cbot",
    crop_year_start_month=5,
    mkt_year_offset=-1,
    stages={},
)
JAN = CropCalendar(
    commodity="frozen_orange_juice",
    crop_year_start_month=1,
    mkt_year_offset=-1,
    stages={},
)
SUGAR = CropCalendar(
    commodity="raw_sugar",
    crop_year_start_month=4,
    mkt_year_offset=-1,
    stages={},
)

PARAMS = {"baselines": {"window_years": 5, "min_years": 2}}


def test_wasde_direct_revisions_use_latest_prior_release_and_streak() -> None:
    rows = []
    for year, rev in {
        2019: -1.0,
        2020: -0.5,
        2021: 0.0,
        2022: 1.0,
        2023: 2.0,
    }.items():
        rows.extend([
            {
                "release_date": f"{year + 1}-02-10",
                "commodity": "corn",
                "table_type": "world",
                "region": "united_states",
                "marketing_year": f"{year}/{str(year + 1)[-2:]}",
                "attribute": "production",
                "estimate": 100.0 + year,
                "revision": rev,
            },
            {
                "release_date": f"{year + 1}-04-10",
                "commodity": "corn",
                "table_type": "world",
                "region": "united_states",
                "marketing_year": f"{year}/{str(year + 1)[-2:]}",
                "attribute": "production",
                "estimate": 101.0 + year,
                "revision": rev + 0.25,
            },
            {
                "release_date": f"{year + 1}-04-10",
                "commodity": "corn",
                "table_type": "world",
                "region": "united_states",
                "marketing_year": f"{year}/{str(year + 1)[-2:]}",
                "attribute": "ending_stocks",
                "estimate": 20.0,
                "revision": rev / 2.0,
            },
            {
                "release_date": f"{year + 1}-06-10",
                "commodity": "corn",
                "table_type": "world",
                "region": "united_states",
                "marketing_year": f"{year}/{str(year + 1)[-2:]}",
                "attribute": "production",
                "estimate": 999.0,
                "revision": 999.0,
            },
        ])

    ctx = FeatureContext(
        commodity="corn_cbot",
        crop_years=[2024],
        countries=["united_states"],
        calendar=CORN,
        inputs={"wasde": pd.DataFrame(rows)},
        params=PARAMS,
    )
    result = compute_wasde_direct_revisions(ctx, None)
    values = result.set_index("feature")["value"]

    assert values["wasde_latest_revision"] == pytest.approx(2.25)
    assert values["wasde_consecutive_revision_count"] == pytest.approx(2.0)
    assert "wasde_production_revision_z" in values
    assert "wasde_ending_stocks_revision_z" in values
    assert values["wasde_latest_revision"] != 999.0


def test_nass_citrus_revisions_emit_prior_completed_us_orange_features() -> None:
    rows = []
    for idx, (season_start, base) in enumerate({
        2019: 50.0,
        2020: 55.0,
        2021: 53.0,
        2022: 58.0,
        2023: 62.0,
    }.items(), start=1):
        rows.extend([
            {
                "season": f"{season_start}-{str(season_start + 1)[-2:]}",
                "release_date": f"{season_start + 1}-01-12",
                "report_month": 1,
                "crop": "all_orange",
                "state": "united_states",
                "forecast_1000_boxes": base,
                "revision_1000_boxes": float(idx),
            },
            {
                "season": f"{season_start}-{str(season_start + 1)[-2:]}",
                "release_date": f"{season_start + 1}-03-12",
                "report_month": 3,
                "crop": "all_orange",
                "state": "united_states",
                "forecast_1000_boxes": base + float(idx),
                "revision_1000_boxes": float(idx + 1),
            },
        ])

    ctx = FeatureContext(
        commodity="frozen_orange_juice",
        crop_years=[2024],
        countries=["united_states", "brazil"],
        calendar=JAN,
        inputs={"nass_citrus": pd.DataFrame(rows)},
        params=PARAMS,
    )
    result = compute_nass_citrus_revisions(ctx, None)

    assert set(result["country"]) == {"united_states"}
    assert {
        "nass_citrus_forecast_revision_z",
        "nass_citrus_prior_report_change_z",
        "nass_citrus_finalization_gap_z",
    } <= set(result["feature"])


def test_ams_cotton_quality_uses_prior_season_tenderability() -> None:
    df = pd.DataFrame({
        "commodity": ["cotton"] * 6,
        "season": [2018, 2019, 2020, 2021, 2022, 2023],
        "geography": ["us_total"] * 6,
        "percent_tenderable": [60.0, 65.0, 64.0, 70.0, 72.0, 77.0],
        "avg_staple": [34.0, 34.5, 35.0, 35.5, 36.0, 36.5],
    })
    ctx = FeatureContext(
        commodity="cotton",
        crop_years=[2024],
        countries=["united_states", "brazil"],
        calendar=JAN,
        inputs={"ams_cotton_quality": df},
        params=PARAMS,
    )
    result = compute_ams_cotton_quality(ctx, None)
    values = result.set_index("feature")["value"]

    assert set(result["country"]) == {"united_states"}
    assert values["ams_percent_tenderable"] == pytest.approx(77.0)
    assert "ams_percent_tenderable_z" in values
    assert "ams_avg_staple_z" in values


def test_unica_sugar_biweekly_uses_prior_center_south_harvest() -> None:
    rows = []
    for year, cane, sugar in [
        (2020, 100.0, 9.0),
        (2021, 110.0, 10.0),
        (2022, 120.0, 12.0),
        (2023, 130.0, 13.0),
        (2024, 140.0, 15.4),
    ]:
        rows.append({
            "harvest_year": f"{year}_{year + 1}",
            "fortnight_seq": 1,
            "fortnight_date": f"{year}-04-16",
            "region": "centro_sul",
            "cane_crushed_t": cane,
            "sugar_produced_t": sugar,
            "ethanol_total_m3": cane / 2.0,
            "source_position_date": f"{year + 1}-02-01",
        })
        rows.append({
            "harvest_year": f"{year}_{year + 1}",
            "fortnight_seq": 2,
            "fortnight_date": f"{year}-05-01",
            "region": "centro_sul",
            "cane_crushed_t": cane * 2.0,
            "sugar_produced_t": sugar * 2.0,
            "ethanol_total_m3": cane,
            "source_position_date": f"{year + 1}-02-01",
        })
    ctx = FeatureContext(
        commodity="raw_sugar",
        crop_years=[2025],
        countries=["brazil", "india"],
        calendar=SUGAR,
        inputs={"unica_biweekly": pd.DataFrame(rows)},
        params=PARAMS,
    )
    result = compute_unica_sugar_biweekly(ctx, None)
    values = result.set_index("feature")["value"]

    assert set(result["country"]) == {"brazil"}
    assert values["unica_sugar_mix_pct"] == pytest.approx(11.0)
    assert values["unica_ethanol_mix_pct"] == pytest.approx(50.0)
    assert "unica_cane_crush_pace_z" in values
    assert "unica_sugar_output_pace_z" in values
