"""Pin tests for ESR export features — convention-proof marketing-year selection.

Background (docs/ML_EXPERIMENT_DATA_AUDIT_REPORT.md section 3.1): silver_esr's ``market_year`` is the FAS
END-year label (corn/soy MY Sep-2023..Aug-2024 = 2024; PSD calls it 2023), and marketing-year boundaries differ
per commodity class (wheat Jun..Jun, soybean oil Oct..Oct).  The old ``crop_year + mkt_year_offset`` selection
was correct for corn/soybeans only because the label mismatch and the offset cancelled — and was a full year
STALE for winter wheat.  These tests pin the replacement rule: for each crop year, use the latest programme
whose last reported week ends BEFORE the crop-year start.  Labels are opaque; only week dates decide.
"""
from __future__ import annotations

import pandas as pd
import pytest
from leviathan.features.calendar import CropCalendar
from leviathan.features.computations.base import FeatureContext
from leviathan.features.computations.esr_exports import compute_esr_exports

CORN = CropCalendar(commodity="corn_cbot", crop_year_start_month=5, mkt_year_offset=-1,
                    stages={"planting": (5, 5)})
SRW = CropCalendar(commodity="soft_red_winter_wheat_cbot", crop_year_start_month=10, mkt_year_offset=-1,
                   stages={"planting": (10, 10)})


def esr_frame(programmes: dict[int, tuple[str, str]], value: float = 100.0) -> pd.DataFrame:
    """One weekly row at each programme's first + last week: {label: (first_week, last_week)}."""
    rows = []
    for label, (first, last) in programmes.items():
        for week in (first, last):
            rows.append({"market_year": label, "week_ending_date": pd.Timestamp(week),
                         "weekly_exports_1000mt": value, "outstanding_sales_1000mt": value,
                         "gross_new_sales_1000mt": value, "changes_1000mt": 0.0})
    return pd.DataFrame(rows)


def ctx_for(df: pd.DataFrame, crop_years: list[int], calendar: CropCalendar) -> FeatureContext:
    return FeatureContext(commodity=calendar.commodity, crop_years=crop_years,
                          countries=["united_states"], calendar=calendar, inputs={"esr": df}, params={})


# END-year labelled programmes, corn/soy style (Sep..early-Sep windows, as in the real silver).
CORN_PROGRAMMES = {
    2020: ("2019-09-05", "2020-09-03"),
    2021: ("2020-09-03", "2021-09-02"),
    2022: ("2021-09-02", "2022-09-01"),
    2023: ("2022-09-01", "2023-08-31"),
    2024: ("2023-09-07", "2024-09-05"),   # in progress at May-2024 planting (ends Sep-2024)
}


def _values(result: pd.DataFrame, crop_year: int) -> dict[str, float]:
    sel = result[result["crop_year"] == crop_year]
    return dict(zip(sel["feature"], sel["value"]))


def test_selects_latest_completed_programme_not_in_progress():
    # crop year 2024 starts May-2024: label-2024 (ends Sep-2024) is IN PROGRESS -> must use label-2023
    # (ended Aug-2023), the latest completed programme.  Values grow by label, so the z-score of the
    # selected year differs between labels — pin via equality with a frame truncated at the completed year.
    df_all = esr_frame(CORN_PROGRAMMES)
    df_all["weekly_exports_1000mt"] = df_all["market_year"] * 1.0          # distinct totals per label
    df_completed_only = df_all[df_all["market_year"] <= 2023]
    out_all = compute_esr_exports(ctx_for(df_all, [2024], CORN), None)
    out_completed = compute_esr_exports(ctx_for(df_completed_only, [2024], CORN), None)
    assert not out_all.empty
    assert _values(out_all, 2024) == _values(out_completed, 2024)          # in-progress label-2024 invisible


def test_leakage_guard_in_progress_programme_never_selected():
    # Make the in-progress programme wildly different; the crop-year 2024 features must not move.
    base = esr_frame(CORN_PROGRAMMES)
    spiked = base.copy()
    spiked.loc[spiked["market_year"] == 2024, "weekly_exports_1000mt"] = 9_999.0
    out_base = compute_esr_exports(ctx_for(base, [2024], CORN), None)
    out_spiked = compute_esr_exports(ctx_for(spiked, [2024], CORN), None)
    assert _values(out_base, 2024) == _values(out_spiked, 2024)


def test_label_independence_shifting_labels_changes_nothing():
    # The ESR incident, made structurally unrepeatable: relabel every programme (+5) -> identical output.
    df = esr_frame(CORN_PROGRAMMES)
    shifted = df.copy()
    shifted["market_year"] = shifted["market_year"] + 5
    out_a = compute_esr_exports(ctx_for(df, [2023, 2024], CORN), None)
    out_b = compute_esr_exports(ctx_for(shifted, [2023, 2024], CORN), None)
    pd.testing.assert_frame_equal(out_a.reset_index(drop=True), out_b.reset_index(drop=True))


def test_winter_wheat_uses_freshest_completed_programme():
    # SRW crop year 2024 starts Oct-2024.  Wheat programmes run Jun..Jun (END-year labels): label-2024
    # ended Jun-2024 -> COMPLETED at Oct-2024 planting and must be selected.  The old offset arithmetic
    # picked label-2023 (ended Jun-2023) — a full year stale.
    wheat = {y: (f"{y-1}-06-05", f"{y}-06-01") for y in range(2019, 2025)}
    df = esr_frame(wheat)
    df["weekly_exports_1000mt"] = df["market_year"] * 1.0
    out = compute_esr_exports(ctx_for(df, [2024], SRW), None)
    df_2024_only = df[df["market_year"] <= 2024]
    df_2023_only = df[df["market_year"] <= 2023]
    fresh = compute_esr_exports(ctx_for(df_2024_only, [2024], SRW), None)
    stale = compute_esr_exports(ctx_for(df_2023_only, [2024], SRW), None)
    assert _values(out, 2024) == _values(fresh, 2024)                     # selected the Jun-2024-ended programme
    assert _values(out, 2024) != _values(stale, 2024)                     # NOT the year-stale one


def test_no_completed_programme_emits_nothing():
    df = esr_frame({2024: ("2023-09-07", "2024-09-05")})                  # only an in-progress programme
    out = compute_esr_exports(ctx_for(df, [2024], CORN), None)
    assert out.empty or (out["crop_year"] != 2024).all()
