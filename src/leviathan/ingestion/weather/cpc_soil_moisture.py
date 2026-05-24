"""NOAA CPC Leaky Bucket Model — soil moisture daily GeoTIFF ingestion helpers.

Data source: CPC Leaky Bucket hydrological model.  One GeoTIFF per variable per
day, global 0.5°×0.5° grid (720×360 cells), EPSG:4326.

FTP root: https://ftp.cpc.ncep.noaa.gov/wd51yf/global_daily/
  - GeoTIFF/w.YYYYMMDD.tif          — rolling current-year daily files
  - clim/w.YYYY.tif.tar.gz           — annual archives, 2000–present

Variable codes
--------------
  w   soil moisture (mm, 0–760 scale; 760 = 100% capacity)
  e   evaporation (mm/day)
  p   precipitation — CPC Unified (mm/day)
  r   runoff (mm/day)
  swe snow water equivalent (mm)
  t   surface air temperature (°C)

Primary agricultural use: ``w`` (soil moisture).
"""
from __future__ import annotations

import io
import tarfile
from datetime import datetime

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from leviathan.common.logging import get_logger
from leviathan.common.types import Region

import rasterio  # noqa: E402

logger = get_logger(__name__)

CPC_FTP_BASE = "https://ftp.cpc.ncep.noaa.gov/wd51yf/global_daily"
_NODATA = -9999.0
_REQUEST_TIMEOUT = 60  # seconds — daily TIF ~854KB; tarball ~85MB may need longer
_TARBALL_TIMEOUT = 300  # seconds — annual tarballs are ~82–89MB


# ---------------------------------------------------------------------------
# Download helpers
# ---------------------------------------------------------------------------

@retry(
    retry=retry_if_exception_type(requests.RequestException),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=30),
    reraise=True,
)
def download_cpc_daily_tif(date_str: str, variable: str = "w") -> bytes:
    """Download a single CPC daily GeoTIFF file (~854KB).

    Args:
        date_str: Date in ``YYYYMMDD`` format, e.g. ``"20240115"``.
        variable: Variable prefix, e.g. ``"w"`` (soil moisture).

    Returns:
        Raw bytes of the GeoTIFF file.

    Raises:
        requests.HTTPError: On 4xx/5xx responses (after retries).
        requests.RequestException: On network errors (after retries).
    """
    url = f"{CPC_FTP_BASE}/GeoTIFF/{variable}.{date_str}.tif"
    logger.info("Downloading CPC daily TIF: %s", url)
    resp = requests.get(url, timeout=_REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.content


@retry(
    retry=retry_if_exception_type(requests.RequestException),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=10, max=60),
    reraise=True,
)
def download_cpc_annual_tarball(year: int, variable: str = "w") -> bytes:
    """Download an annual CPC GeoTIFF tarball (~82–89MB).

    Contains one GeoTIFF per calendar day for the given year (365 or 366 files).

    Args:
        year: Calendar year, e.g. ``2024``.  Available 2000–present.
        variable: Variable prefix, e.g. ``"w"`` (soil moisture).

    Returns:
        Raw bytes of the ``.tif.tar.gz`` archive.
    """
    url = f"{CPC_FTP_BASE}/clim/{variable}.{year}.tif.tar.gz"
    logger.info("Downloading CPC annual tarball: %s (~85MB, may take a moment)", url)
    resp = requests.get(url, timeout=_TARBALL_TIMEOUT)
    resp.raise_for_status()
    logger.info("Downloaded %d bytes for %s %d tarball", len(resp.content), variable, year)
    return resp.content


# ---------------------------------------------------------------------------
# Tarball extraction
# ---------------------------------------------------------------------------

def extract_tifs_from_tarball(tar_bytes: bytes, variable: str = "w") -> dict[str, bytes]:
    """Extract daily GeoTIFF files from an annual CPC tarball.

    Args:
        tar_bytes: Raw bytes of the ``.tif.tar.gz`` archive.
        variable: Variable prefix used to build expected filenames, e.g. ``"w"``.

    Returns:
        Dict mapping ``YYYYMMDD`` date strings to their GeoTIFF bytes.
        Files that cannot be parsed or extracted are skipped with a warning.
    """
    result: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:gz") as tf:
        for member in tf.getmembers():
            if not member.isfile():
                continue
            # Expected filename: w.YYYYMMDD.tif (may have path prefix from tar)
            basename = member.name.rsplit("/", 1)[-1]
            if not (basename.startswith(f"{variable}.") and basename.endswith(".tif")):
                logger.debug("Skipping unexpected tarball member: %s", member.name)
                continue
            # Parse date: w.YYYYMMDD.tif -> YYYYMMDD
            stem = basename[len(variable) + 1:-4]  # strip "w." prefix and ".tif" suffix
            try:
                datetime.strptime(stem, "%Y%m%d")
            except ValueError:
                logger.warning("Cannot parse date from tarball member: %s — skipping", member.name)
                continue
            fobj = tf.extractfile(member)
            if fobj is None:
                logger.warning("Cannot extract member: %s — skipping", member.name)
                continue
            result[stem] = fobj.read()

    logger.info("Extracted %d daily TIFs from tarball", len(result))
    return result


# ---------------------------------------------------------------------------
# Raster pixel extraction
# ---------------------------------------------------------------------------

def extract_region_values(
    tif_bytes: bytes,
    locations: list[Region],
    nodata: float = _NODATA,
) -> dict[str, float | None]:
    """Extract the pixel value at each location from a CPC GeoTIFF.

    Reads the full band array once into memory (CPC files are not COGs — they
    cannot be HTTP range-read).  Returns ``None`` for nodata pixels and for
    locations outside the raster extent.

    Args:
        tif_bytes: Raw bytes of a single-band CPC GeoTIFF (~854KB).
        locations: List of dicts with keys ``region``, ``latitude``, ``longitude``.
        nodata: Fallback nodata sentinel if the file has no embedded nodata value.

    Returns:
        Dict mapping region name → float value (e.g. soil_moisture_mm) or ``None``.
    """
    result: dict[str, float | None] = {}
    with rasterio.open(io.BytesIO(tif_bytes)) as src:
        actual_nodata = float(src.nodata) if src.nodata is not None else nodata
        band = src.read(1)  # read full array once; reuse for all locations
        for loc in locations:
            region: str = loc["region"]
            try:
                row, col = src.index(loc["longitude"], loc["latitude"])
                if not (0 <= row < src.height and 0 <= col < src.width):
                    logger.debug("Location %s outside CPC raster extent — None", region)
                    result[region] = None
                    continue
                value = float(band[row, col])
                result[region] = None if value == actual_nodata else value
            except Exception as exc:  # noqa: BLE001 — rasterio index can raise for edge cases
                logger.warning("Pixel read failed for region=%s: %s — None", region, exc)
                result[region] = None

    return result
