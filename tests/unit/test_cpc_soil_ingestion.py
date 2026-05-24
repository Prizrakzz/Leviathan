"""Unit tests for CPC Soil Moisture ingestion helpers.

Tests are pure Python — no S3/AWS/network dependencies.
Synthetic GeoTIFF files are created in memory via rasterio MemoryFile.
"""
from __future__ import annotations

import io
import tarfile

import numpy as np
import pytest
import rasterio
from rasterio.crs import CRS
from rasterio.transform import from_bounds

from leviathan.ingestion.weather.cpc_soil_moisture import (
    extract_region_values,
    extract_tifs_from_tarball,
)
from leviathan.storage.paths import raw_cpc_tif_key


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tif_bytes(
    data: np.ndarray,
    west: float = -180.0,
    east: float = 180.0,
    south: float = -90.0,
    north: float = 90.0,
    nodata: float = -9999.0,
) -> bytes:
    """Create a minimal single-band GeoTIFF in memory from a 2-D numpy array."""
    height, width = data.shape
    transform = from_bounds(west, south, east, north, width, height)
    buf = io.BytesIO()
    with rasterio.open(
        buf,
        mode="w",
        driver="GTiff",
        height=height,
        width=width,
        count=1,
        dtype=data.dtype,
        crs=CRS.from_epsg(4326),
        transform=transform,
        nodata=nodata,
    ) as dst:
        dst.write(data, 1)
    return buf.getvalue()


def _make_tarball(files: dict[str, bytes]) -> bytes:
    """Create an in-memory .tif.tar.gz with the given {filename: bytes} contents."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, content in files.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(content)
            tf.addfile(info, io.BytesIO(content))
    return buf.getvalue()


# ---------------------------------------------------------------------------
# raw_cpc_tif_key
# ---------------------------------------------------------------------------

class TestRawCpcTifKey:
    def test_path_format(self) -> None:
        key = raw_cpc_tif_key("w", "20240115", "w.20240115.tif")
        assert key == "raw/weather/source=cpc_soil/variable=w/date=20240115/w.20240115.tif"

    def test_variable_in_path(self) -> None:
        key = raw_cpc_tif_key("swe", "20240601", "swe.20240601.tif")
        assert "variable=swe" in key

    def test_date_in_path(self) -> None:
        key = raw_cpc_tif_key("w", "20001231", "w.20001231.tif")
        assert "date=20001231" in key


# ---------------------------------------------------------------------------
# extract_region_values
# ---------------------------------------------------------------------------

class TestExtractRegionValues:
    """Tests use a 4×4 global GeoTIFF (0.5° per cell matching CPC resolution)."""

    def _grid(self) -> np.ndarray:
        """4-row × 4-col float32 grid filled with recognisable values."""
        return np.array(
            [[10.0, 20.0, 30.0, 40.0],
             [50.0, 60.0, 70.0, 80.0],
             [90.0, 100.0, 110.0, 120.0],
             [130.0, 140.0, 150.0, 160.0]],
            dtype=np.float32,
        )

    def test_hit_returns_pixel_value(self) -> None:
        """A location inside the raster returns the correct pixel float value."""
        data = self._grid()
        tif_bytes = _make_tif_bytes(data)
        # Centre of the raster (roughly 0°N, 0°E) — will land in row 1 or 2, col 1 or 2
        location = [{"region": "test_region", "latitude": 0.0, "longitude": 0.0}]
        result = extract_region_values(tif_bytes, location)
        assert "test_region" in result
        assert result["test_region"] is not None
        assert isinstance(result["test_region"], float)

    def test_nodata_returns_none(self) -> None:
        """A pixel equal to the nodata sentinel returns None."""
        data = np.full((4, 4), -9999.0, dtype=np.float32)
        tif_bytes = _make_tif_bytes(data, nodata=-9999.0)
        location = [{"region": "r", "latitude": 0.0, "longitude": 0.0}]
        result = extract_region_values(tif_bytes, location)
        assert result["r"] is None

    def test_embedded_nodata_respected(self) -> None:
        """nodata embedded in the TIF header overrides the function default."""
        data = np.full((4, 4), -1.0, dtype=np.float32)
        tif_bytes = _make_tif_bytes(data, nodata=-1.0)
        location = [{"region": "r", "latitude": 0.0, "longitude": 0.0}]
        result = extract_region_values(tif_bytes, location, nodata=-9999.0)
        assert result["r"] is None  # embedded nodata (-1.0) takes precedence

    def test_out_of_bounds_returns_none(self) -> None:
        """A location outside the raster extent returns None (not an exception)."""
        data = self._grid()
        # Raster covers 10°W–10°E, 10°S–10°N — outside any global CPC TIF would be unusual,
        # but we restrict extent to force the boundary condition.
        tif_bytes = _make_tif_bytes(data, west=-10.0, east=10.0, south=-10.0, north=10.0)
        location = [{"region": "far_away", "latitude": 80.0, "longitude": 150.0}]
        result = extract_region_values(tif_bytes, location)
        assert result["far_away"] is None

    def test_multiple_locations(self) -> None:
        """Multiple locations are all returned in one call."""
        data = self._grid()
        tif_bytes = _make_tif_bytes(data)
        locations = [
            {"region": "a", "latitude": 45.0,  "longitude": -90.0},
            {"region": "b", "latitude": -45.0, "longitude": 90.0},
        ]
        result = extract_region_values(tif_bytes, locations)
        assert set(result.keys()) == {"a", "b"}

    def test_empty_locations_returns_empty(self) -> None:
        data = self._grid()
        tif_bytes = _make_tif_bytes(data)
        assert extract_region_values(tif_bytes, []) == {}


# ---------------------------------------------------------------------------
# extract_tifs_from_tarball
# ---------------------------------------------------------------------------

class TestExtractTifsFromTarball:
    def test_extracts_two_files(self) -> None:
        """Two valid daily TIFs in a tarball are returned with correct YYYYMMDD keys."""
        dummy = b"FAKE_TIF_BYTES"
        tar_bytes = _make_tarball({
            "w.20240101.tif": dummy,
            "w.20240102.tif": dummy,
        })
        result = extract_tifs_from_tarball(tar_bytes, variable="w")
        assert set(result.keys()) == {"20240101", "20240102"}
        assert result["20240101"] == dummy

    def test_skips_non_tif_members(self) -> None:
        """Non-.tif files in the archive are ignored."""
        tar_bytes = _make_tarball({
            "w.20240101.tif": b"OK",
            "README.txt": b"ignore me",
            "w.20240101.tif.md5": b"ignore",
        })
        result = extract_tifs_from_tarball(tar_bytes, variable="w")
        assert set(result.keys()) == {"20240101"}

    def test_skips_wrong_variable(self) -> None:
        """Files for a different variable prefix are ignored."""
        tar_bytes = _make_tarball({
            "w.20240101.tif": b"soil",
            "e.20240101.tif": b"evap",
        })
        result = extract_tifs_from_tarball(tar_bytes, variable="w")
        assert set(result.keys()) == {"20240101"}

    def test_path_prefix_stripped(self) -> None:
        """Filenames with a leading directory path are handled correctly."""
        tar_bytes = _make_tarball({"subdir/w.20240315.tif": b"DATA"})
        result = extract_tifs_from_tarball(tar_bytes, variable="w")
        assert "20240315" in result

    def test_empty_tarball_returns_empty(self) -> None:
        tar_bytes = _make_tarball({})
        assert extract_tifs_from_tarball(tar_bytes, variable="w") == {}
