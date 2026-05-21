from __future__ import annotations

import os

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from leviathan.common.logging import get_logger
from leviathan.common.types import Region

# GDAL/vsicurl settings — must be applied before rasterio is imported.
# These tell the GDAL HTTP driver to skip directory enumeration (expensive on
# remote files), retry on transient errors, and cache COG overview tiles.
os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
os.environ.setdefault("GDAL_HTTP_MAX_RETRY", "3")
os.environ.setdefault("GDAL_HTTP_RETRY_DELAY", "1")
os.environ.setdefault("GDAL_HTTP_TIMEOUT", "30")
os.environ.setdefault("CPL_VSIL_CURL_CACHE_SIZE", "200000000")

import rasterio  # noqa: E402
from rasterio.errors import RasterioIOError  # noqa: E402
from rasterio.windows import Window  # noqa: E402

logger = get_logger(__name__)

_BASE_URL = "https://data.chc.ucsb.edu/products/CHIRPS-3.0/global_daily/cogs/p05"
_NODATA = -9999.0


def _build_cog_url(year: int, month: int, day: int) -> str:
    return f"{_BASE_URL}/{year}/chirps-v3.0.{year}.{month:02d}.{day:02d}.cog.tif"


def fetch_chirps_daily_values(
    year: int,
    month: int,
    day: int,
    locations: list[Region],
) -> dict[str, float | None]:
    """Extract daily CHIRPS precipitation (mm) for each named location.

    Opens the CHIRPS v3 COG file once via HTTP range-read and extracts a
    single pixel value per location.  A 404 response (file not yet published
    or outside the historical record) is handled silently — all regions are
    returned as None.  Other I/O errors are retried up to three times by the
    inner helper before propagating.

    Args:
        year: Calendar year.
        month: Calendar month (1–12).
        day: Calendar day (1–31).
        locations: List of dicts, each with keys 'region', 'latitude', 'longitude'.

    Returns:
        Dict mapping region name → precipitation mm (float) or None.
    """
    url = _build_cog_url(year, month, day)
    try:
        return _read_cog_values(url, locations)
    except RasterioIOError as exc:
        if "404" in str(exc) or "does not exist" in str(exc).lower():
            logger.info("CHIRPS file not available (404): %s — skipping day", url)
            return {loc["region"]: None for loc in locations}
        raise


@retry(
    retry=retry_if_exception_type(RasterioIOError),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=30),
    reraise=True,
)
def _read_cog_values(
    url: str,
    locations: list[Region],
) -> dict[str, float | None]:
    """Open one COG URL and read one pixel per location via HTTP range requests."""
    logger.info("CHIRPS COG range-read: %s (%d locations)", url, len(locations))
    result: dict[str, float | None] = {}

    with rasterio.open(f"/vsicurl/{url}") as src:
        nodata = float(src.nodata) if src.nodata is not None else _NODATA

        for loc in locations:
            region: str = loc["region"]
            try:
                row, col = src.index(loc["longitude"], loc["latitude"])
                if not (0 <= row < src.height and 0 <= col < src.width):
                    logger.debug("Location %s outside raster extent — skipping", region)
                    result[region] = None
                    continue
                value = float(src.read(1, window=Window(col, row, 1, 1))[0, 0])
                result[region] = None if value == nodata else value
            except Exception as exc:  # noqa: BLE001 — rasterio pixel read can raise diverse exceptions; log and set None
                logger.warning("Pixel read failed for region=%s: %s", region, exc)
                result[region] = None

    return result
