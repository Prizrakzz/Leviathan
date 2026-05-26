"""Unit tests for leviathan.transforms.raw_to_bronze.modis_ndvi.parse_appeears_csv."""
from __future__ import annotations

import pytest

from leviathan.transforms.raw_to_bronze.modis_ndvi import parse_appeears_csv

# ─── Minimal CSV helpers ───────────────────────────────────────────────────────

_HEADER = (
    "Category,ID,Latitude,Longitude,Date,"
    "MOD13Q1_061__250m_16_days_NDVI,"
    "MOD13Q1_061__250m_16_days_pixel_reliability\n"
)

REGION_TO_COUNTRY = {
    "us_midwest_iowa": "united_states",
    "br_cerrado_goias": "brazil",
}

INGEST_DATE = "2026-05-26"

EXPECTED_COLUMNS = {
    "date", "year", "period",
    "commodity", "country", "region",
    "latitude", "longitude",
    "ndvi_raw", "ndvi", "pixel_reliability",
    "ingest_date",
}


def _csv(rows: list[str]) -> bytes:
    return (_HEADER + "\n".join(rows) + "\n").encode()


def _row(
    category: str = "corn_cbot",
    id_: str = "us_midwest_iowa",
    lat: float = 41.5,
    lon: float = -93.0,
    date_: str = "2020-01-01",
    ndvi: float = 0.6,
    quality: float = 1.0,
) -> str:
    return f"{category},{id_},{lat},{lon},{date_},{ndvi},{quality}"


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def base_csv_bytes() -> bytes:
    """Minimal valid AppEEARS CSV: 4 clean rows across 2 regions."""
    return _csv([
        _row(date_="2020-01-01", ndvi=0.6000, quality=0.0),
        _row(date_="2020-02-17", ndvi=0.7000, quality=1.0),
        _row(id_="br_cerrado_goias", date_="2020-01-01", ndvi=0.5000, quality=0.0),
        _row(id_="br_cerrado_goias", date_="2020-02-17", ndvi=0.4000, quality=1.0),
    ])


# ─── Tests ────────────────────────────────────────────────────────────────────

class TestOutputColumns:
    def test_exact_columns(self, base_csv_bytes):
        result = parse_appeears_csv(base_csv_bytes, REGION_TO_COUNTRY, INGEST_DATE)
        assert set(result.columns) == EXPECTED_COLUMNS

    def test_ingest_date_stamped(self, base_csv_bytes):
        result = parse_appeears_csv(base_csv_bytes, REGION_TO_COUNTRY, INGEST_DATE)
        assert (result["ingest_date"] == INGEST_DATE).all()


class TestFillValueDropped:
    def test_ndvi_fill_sentinel_dropped(self):
        """AppEEARS fill sentinel (-3000.0) must be excluded."""
        rows = [
            _row(date_="2020-01-01", ndvi=0.6, quality=1.0),
            _row(date_="2020-02-17", ndvi=-3000.0, quality=-1.0),
        ]
        result = parse_appeears_csv(_csv(rows), REGION_TO_COUNTRY, INGEST_DATE)
        assert len(result) == 1
        assert float(result["ndvi_raw"].iloc[0]) == pytest.approx(0.6, abs=1e-4)

    def test_ndvi_below_physical_min_dropped(self):
        """Anything below -0.3 (e.g. -0.4) must be excluded."""
        rows = [
            _row(date_="2020-01-01", ndvi=0.5),
            _row(date_="2020-02-17", ndvi=-0.4),
        ]
        result = parse_appeears_csv(_csv(rows), REGION_TO_COUNTRY, INGEST_DATE)
        assert len(result) == 1


class TestUpperBound:
    def test_ndvi_above_1_dropped(self):
        """Values > 1.0 are out-of-range and must be excluded."""
        rows = [
            _row(date_="2020-01-01", ndvi=0.8),
            _row(date_="2020-02-17", ndvi=1.01),
        ]
        result = parse_appeears_csv(_csv(rows), REGION_TO_COUNTRY, INGEST_DATE)
        assert len(result) == 1
        assert float(result["ndvi_raw"].iloc[0]) == pytest.approx(0.8, abs=1e-4)


class TestDeduplication:
    def test_duplicate_region_date_kept_once(self):
        """Two rows with the same (commodity, region, date) → one row in output."""
        rows = [
            _row(date_="2020-01-01", ndvi=0.6),
            _row(date_="2020-01-01", ndvi=0.7),  # duplicate same commodity
        ]
        result = parse_appeears_csv(_csv(rows), REGION_TO_COUNTRY, INGEST_DATE)
        assert len(result) == 1

    def test_different_commodities_same_region_date_both_kept(self):
        """Two commodities sharing a region+date must NOT be deduplicated."""
        region_to_country = {**REGION_TO_COUNTRY, "us_midwest_iowa": "united_states"}
        rows = [
            _row(category="corn_cbot",     id_="us_midwest_iowa", date_="2020-01-01", ndvi=0.6),
            _row(category="soybean_cbot",  id_="us_midwest_iowa", date_="2020-01-01", ndvi=0.7),
        ]
        result = parse_appeears_csv(_csv(rows), region_to_country, INGEST_DATE)
        assert len(result) == 2
        assert set(result["commodity"]) == {"corn_cbot", "soybean_cbot"}


class TestPeriodCalculation:
    def test_period_1_jan1(self):
        rows = [_row(date_="2020-01-01")]
        result = parse_appeears_csv(_csv(rows), REGION_TO_COUNTRY, INGEST_DATE)
        assert int(result["period"].iloc[0]) == 1

    def test_period_22_dec17_leapyear(self):
        """Day 352 in 2020 (leap year) = Dec 17 → period 22."""
        rows = [_row(date_="2020-12-17")]
        result = parse_appeears_csv(_csv(rows), REGION_TO_COUNTRY, INGEST_DATE)
        assert int(result["period"].iloc[0]) == 22

    def test_period_23_dec18_leapyear(self):
        """Day 353 in 2020 (leap year) = Dec 18 → period 23."""
        rows = [_row(date_="2020-12-18")]
        result = parse_appeears_csv(_csv(rows), REGION_TO_COUNTRY, INGEST_DATE)
        assert int(result["period"].iloc[0]) == 23


class TestUnknownRegion:
    def test_unknown_region_dropped(self):
        """Rows whose region is absent from region_to_country are dropped."""
        rows = [
            _row(id_="us_midwest_iowa", date_="2020-01-01"),
            _row(id_="unknown_region_xyz", date_="2020-01-01"),
        ]
        result = parse_appeears_csv(_csv(rows), REGION_TO_COUNTRY, INGEST_DATE)
        assert len(result) == 1
        assert result["region"].iloc[0] == "us_midwest_iowa"


class TestMissingColumn:
    def test_missing_ndvi_column_raises(self):
        bad_csv = (
            b"Category,ID,Latitude,Longitude,Date,"
            b"MOD13Q1_061__250m_16_days_pixel_reliability\n"
            b"corn_cbot,us_midwest_iowa,41.5,-93.0,2020-01-01,0.0\n"
        )
        with pytest.raises(ValueError, match="NDVI"):
            parse_appeears_csv(bad_csv, REGION_TO_COUNTRY, INGEST_DATE)


class TestNdviValues:
    def test_ndvi_stored_as_physical_float_no_rescaling(self):
        """AppEEARS already scales NDVI — no additional multiply must be applied."""
        rows = [_row(date_="2020-01-01", ndvi=0.7472)]
        result = parse_appeears_csv(_csv(rows), REGION_TO_COUNTRY, INGEST_DATE)
        assert float(result["ndvi_raw"].iloc[0]) == pytest.approx(0.7472, abs=1e-4)
        assert float(result["ndvi"].iloc[0]) == pytest.approx(0.7472, abs=1e-4)

    def test_ndvi_dtype_float32(self):
        rows = [_row(date_="2020-01-01", ndvi=0.6)]
        result = parse_appeears_csv(_csv(rows), REGION_TO_COUNTRY, INGEST_DATE)
        assert result["ndvi_raw"].dtype == "float32"
        assert result["ndvi"].dtype == "float32"
