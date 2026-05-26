"""Unit tests for leviathan.transforms.bronze_to_silver.modis_ndvi."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from leviathan.transforms.bronze_to_silver.modis_ndvi import modis_ndvi_bronze_to_silver

EXPECTED_SILVER_COLUMNS = {
    "date", "year", "period",
    "commodity", "country", "region",
    "latitude", "longitude",
    "ndvi_raw", "ndvi", "pixel_reliability",
    "ndvi_z_score", "baseline_mean", "baseline_std",
    "ingest_date",
}


def _make_bronze(
    regions: list[str] | None = None,
    years: list[int] | None = None,
    periods: list[int] | None = None,
    ndvi: float = 0.6,
    quality: int = 0,
    commodity: str = "corn_cbot",
    country: str = "united_states",
) -> pd.DataFrame:
    """Construct a minimal bronze DataFrame for testing."""
    if regions is None:
        regions = ["r1"]
    if years is None:
        years = list(range(2000, 2022))
    if periods is None:
        periods = [1]

    rows = []
    for region in regions:
        for year in years:
            for period in periods:
                doy = (period - 1) * 16 + 1
                d = date(year, 1, 1) + timedelta(days=doy - 1)
                rows.append({
                    "date": d,
                    "year": year,
                    "period": period,
                    "commodity": commodity,
                    "country": country,
                    "region": region,
                    "latitude": 41.5,
                    "longitude": -93.0,
                    "ndvi_raw": float(ndvi),
                    "ndvi": float(ndvi),
                    "pixel_reliability": quality,
                    "ingest_date": "2026-05-26",
                })
    return pd.DataFrame(rows)


# ─── Tests ────────────────────────────────────────────────────────────────────

class TestOutputColumns:
    def test_exact_silver_columns(self):
        df = _make_bronze(years=list(range(2000, 2022)))
        result = modis_ndvi_bronze_to_silver(df)
        assert set(result.columns) == EXPECTED_SILVER_COLUMNS


class TestQualityFilter:
    def test_quality_2_rows_excluded(self):
        good = _make_bronze(years=list(range(2000, 2022)), quality=0)
        bad = _make_bronze(years=[2023], quality=2)
        df = pd.concat([good, bad], ignore_index=True)
        result = modis_ndvi_bronze_to_silver(df)
        assert (result["pixel_reliability"] != 2).all()
        assert len(result) == len(good)

    def test_all_bad_quality_returns_empty_dataframe(self):
        df = _make_bronze(years=list(range(2000, 2022)), quality=3)
        result = modis_ndvi_bronze_to_silver(df)
        assert result.empty
        assert set(result.columns) == EXPECTED_SILVER_COLUMNS


class TestZScore:
    def test_constant_baseline_gives_nan_zscore(self):
        """std = 0 (constant NDVI in baseline) → z-score must be NaN."""
        df = _make_bronze(years=list(range(2000, 2022)), ndvi=0.5, quality=0)
        current = _make_bronze(years=[2023], ndvi=0.7, quality=0)
        df = pd.concat([df, current], ignore_index=True)
        result = modis_ndvi_bronze_to_silver(df)
        assert result["ndvi_z_score"].isna().all()

    def test_above_mean_gives_positive_zscore(self):
        """NDVI above baseline mean → positive z-score."""
        low = _make_bronze(years=list(range(2000, 2010)), ndvi=0.4, quality=0)
        high = _make_bronze(years=list(range(2010, 2020)), ndvi=0.8, quality=0)
        current = _make_bronze(years=[2023], ndvi=0.9, quality=0)
        df = pd.concat([low, high, current], ignore_index=True)
        result = modis_ndvi_bronze_to_silver(df)
        z = float(result[result["year"] == 2023]["ndvi_z_score"].iloc[0])
        assert z > 0, f"Expected positive z-score for above-mean NDVI, got {z}"

    def test_below_mean_gives_negative_zscore(self):
        """NDVI below baseline mean → negative z-score."""
        low = _make_bronze(years=list(range(2000, 2010)), ndvi=0.4, quality=0)
        high = _make_bronze(years=list(range(2010, 2020)), ndvi=0.8, quality=0)
        current = _make_bronze(years=[2023], ndvi=0.1, quality=0)
        df = pd.concat([low, high, current], ignore_index=True)
        result = modis_ndvi_bronze_to_silver(df)
        z = float(result[result["year"] == 2023]["ndvi_z_score"].iloc[0])
        assert z < 0, f"Expected negative z-score for below-mean NDVI, got {z}"


class TestInsufficientBaseline:
    def test_fewer_than_5_baseline_years_gives_nan_zscore(self):
        """Only 4 baseline years → z-score must be NaN for all rows."""
        df = _make_bronze(years=[2000, 2001, 2002, 2003])  # 4 years < MIN_BASELINE_YEARS
        current = _make_bronze(years=[2023])
        df = pd.concat([df, current], ignore_index=True)
        result = modis_ndvi_bronze_to_silver(df)
        assert result["ndvi_z_score"].isna().all()

    def test_exactly_5_baseline_years_gives_valid_zscore(self):
        """Exactly 5 baseline years with variance → z-score must not be NaN."""
        low = _make_bronze(years=[2000, 2001, 2002], ndvi=0.4, quality=0)
        high = _make_bronze(years=[2003, 2004], ndvi=0.8, quality=0)
        current = _make_bronze(years=[2023], ndvi=0.6, quality=0)
        df = pd.concat([low, high, current], ignore_index=True)
        result = modis_ndvi_bronze_to_silver(df)
        z_2023 = result[result["year"] == 2023]["ndvi_z_score"]
        assert z_2023.notna().all()


class TestDeduplication:
    def test_duplicate_rows_do_not_skew_baseline(self):
        """Duplicate (region, date) rows are removed before baseline computation."""
        normal = _make_bronze(years=list(range(2000, 2010)), ndvi=0.5, quality=0)
        # Inject duplicate for 2005 with wildly different NDVI
        dup = _make_bronze(years=[2005], ndvi=0.99, quality=0)
        current = _make_bronze(years=[2023], ndvi=0.5, quality=0)
        df = pd.concat([normal, dup, current], ignore_index=True)
        result = modis_ndvi_bronze_to_silver(df)
        # After dedup the 2005 row appears once; baseline_mean for region r1 period 1
        # should still be 0.5 (not skewed by 0.99 duplicate)
        current_result = result[result["year"] == 2023]
        assert float(current_result["baseline_mean"].iloc[0]) == pytest.approx(0.5, abs=1e-3)


class TestMissingColumns:
    def test_missing_required_column_raises(self):
        df = _make_bronze()
        df = df.drop(columns=["ndvi"])
        with pytest.raises(ValueError, match="ndvi"):
            modis_ndvi_bronze_to_silver(df)
