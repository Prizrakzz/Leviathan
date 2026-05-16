"""Unit tests for leviathan.ingestion.weather.chirps."""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_dataset(value: float, nodata: float = -9999.0, height: int = 2000, width: int = 7200):
    """Return a mock rasterio dataset that yields *value* for any pixel read."""
    ds = MagicMock()
    ds.__enter__ = lambda s: s
    ds.__exit__ = MagicMock(return_value=False)
    ds.nodata = nodata
    ds.height = height
    ds.width = width
    ds.index.return_value = (100, 200)  # always in-bounds
    ds.read.return_value = np.array([[value]], dtype=np.float32)
    return ds


_LOCATIONS = [
    {"region": "us_corn_iowa", "latitude": 42.03, "longitude": -93.64},
    {"region": "br_corn_mato_grosso", "latitude": -12.64, "longitude": -55.42},
]


# ---------------------------------------------------------------------------
# Tests: fetch_chirps_daily_values
# ---------------------------------------------------------------------------

class TestFetchChirpsDailyValues:
    def test_returns_float_values_for_valid_pixels(self):
        mock_ds = _make_mock_dataset(value=12.5)
        with patch("rasterio.open", return_value=mock_ds):
            from leviathan.ingestion.weather.chirps import fetch_chirps_daily_values
            result = fetch_chirps_daily_values(2020, 6, 15, _LOCATIONS)

        assert result == {"us_corn_iowa": 12.5, "br_corn_mato_grosso": 12.5}

    def test_returns_none_for_nodata_pixels(self):
        mock_ds = _make_mock_dataset(value=-9999.0, nodata=-9999.0)
        with patch("rasterio.open", return_value=mock_ds):
            from leviathan.ingestion.weather.chirps import fetch_chirps_daily_values
            result = fetch_chirps_daily_values(2020, 6, 15, _LOCATIONS)

        assert result == {"us_corn_iowa": None, "br_corn_mato_grosso": None}

    def test_returns_all_none_on_404(self):
        """A 404 (file not yet released) must not raise — return all None."""
        import rasterio.errors

        with patch("rasterio.open", side_effect=rasterio.errors.RasterioIOError("HTTP 404")):
            from leviathan.ingestion.weather.chirps import fetch_chirps_daily_values
            result = fetch_chirps_daily_values(2026, 12, 31, _LOCATIONS)

        assert result == {"us_corn_iowa": None, "br_corn_mato_grosso": None}

    def test_raises_on_non_404_io_error(self):
        """Non-404 I/O errors should propagate after retries are exhausted."""
        import rasterio.errors

        with patch("rasterio.open", side_effect=rasterio.errors.RasterioIOError("connection reset")):
            from leviathan.ingestion.weather.chirps import fetch_chirps_daily_values
            with pytest.raises(rasterio.errors.RasterioIOError, match="connection reset"):
                fetch_chirps_daily_values(2020, 6, 15, _LOCATIONS)

    def test_out_of_bounds_pixel_returns_none(self):
        """Locations outside the raster extent must return None, not raise."""
        mock_ds = _make_mock_dataset(value=5.0)
        # Make index() return coordinates outside the raster
        mock_ds.index.return_value = (9999, 9999)
        mock_ds.height = 2000
        mock_ds.width = 7200

        with patch("rasterio.open", return_value=mock_ds):
            from leviathan.ingestion.weather.chirps import fetch_chirps_daily_values
            result = fetch_chirps_daily_values(2020, 6, 15, _LOCATIONS)

        assert result == {"us_corn_iowa": None, "br_corn_mato_grosso": None}

    def test_uses_vsicurl_url_prefix(self):
        """The COG URL passed to rasterio.open must use the /vsicurl/ prefix."""
        mock_ds = _make_mock_dataset(value=1.0)
        with patch("rasterio.open", return_value=mock_ds) as mock_open:
            from leviathan.ingestion.weather.chirps import fetch_chirps_daily_values
            fetch_chirps_daily_values(2020, 6, 15, _LOCATIONS)

        call_url: str = mock_open.call_args[0][0]
        assert call_url.startswith("/vsicurl/")
        assert "chirps-v3.0.2020.06.15.cog.tif" in call_url
