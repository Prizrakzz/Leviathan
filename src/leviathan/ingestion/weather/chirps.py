"""CHIRPS v2.0 daily precipitation -- the FINAL product, and the PRELIM product behind it.

TWO PRODUCTS, ONE GRID.  CHIRPS v2.0 publishes the authoritative ``global_daily`` series as a whole
MONTH BLOCK +11..+16 days past month-end (Last-Modified, five months over five years: 2026-07 -> +14,
2025-08 -> +12, 2024-08 -> +14, 2020-08 -> +16, sampled 2026-09-11, and 2026-08 -> +11 measured
2026-09-15 -- ONE block write at 2026-09-11 21:10Z, hours after the 09-11 probe recorded it absent,
which is what moved the lower bound from 12 to 11), and a PRELIM daily series at the same resolution in
PENTAD BLOCKS ~2 days after each pentad closes (worst observed slip +4), so a COMPLETE month of prelim
exists +2 days past month-end.  The two rasters are byte-compatible -- MEASURED, not assumed: identical
7200x2000 grid, float32, EPSG:4326, affine (0.05, 0, -180, 0, -0.05, 50.0), ``nodata=None``, untiled,
and ``src.index(lon, lat)`` resolves to the SAME pixel on both.  **The product swap is a URL swap and
nothing else in the reader** -- :func:`_read_cog_values` is untouched by the prelim lane.

THE HORIZON IS A FENCE, NOT AN OPTIMISATION (T-A3).  The prelim archive is LIVE back to at least 2020
(2020-08-15 / 2024-08-15 / 2025-08-15 all HTTP 200 with their original mtimes), so "final, else prelim"
written with NO window would reach prelim for any historical day whose final 404s -- back to 1981.  The
bronze rewrite rule is strictly monotone on observed days, so a 1981 month sitting at 30/31 would gain a
31st PRELIM day, be rewritten, and enter ``weather_z._drought_runs``' trailing-prior-year baseline for
that (region, month) for every subsequent year: history would MOVE.  :data:`PRELIM_MONTH_REACH` is what
makes the whole 1981..2026-07 corpus byte-identical, and it is the same constant the bronze tasks use
for their final RE-CHECK window.
"""
from __future__ import annotations

import os
from datetime import date

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from leviathan.common.logging import get_logger
from leviathan.common.types import Region

# GDAL/vsicurl settings — must be applied before rasterio is imported.
# These tell the GDAL HTTP driver to skip directory enumeration (expensive on
# remote files), retry on transient errors, and cache COG overview tiles.
os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
os.environ.setdefault("GDAL_HTTP_MAX_RETRY", "3")
os.environ.setdefault("GDAL_HTTP_RETRY_DELAY", "1")
# 120, NOT 30, AND THE 30 WAS MEASURED WRONG rather than merely conservative. CHIRPS ships an UNTILED
# stripped TIFF whose IFD sits at byte 57,600,008 (= 7200*2000*4 + 8), i.e. AFTER the whole image, and
# /vsigzip/ cannot seek a gzip stream -- so reaching ONE pixel means inflating all 57.6 MB. At 30 s,
# 17 of the 31 opens of 2026-08 died on `TIFFReadDirectory:Failed to read directory at offset
# 57600008` (scratchpad/chirps_prelim/COST_MEASUREMENT.md; every failure was a 10-11 MB gz file, every
# 2.1-2.6 MB file succeeded) -- a timeout reads as a LOST DAY, never as an error. The blast radius is
# bounded because the daily task's _DayRasterCache opens each day's raster ONCE per run, so the worst
# case is ~62 opens x 120 s of ceiling, not 1,922. This number is PROVISIONAL and the thing that
# revises it is one reading: `fetch_failures` per month in bronze _meta.json after the FIRST Fargate
# run (a us-east-1 link, not the home link this was measured on). Still a setdefault, so the jobdef
# environment overrides it WITHOUT a rebuild -- which is the whole point of leaving it here.
os.environ.setdefault("GDAL_HTTP_TIMEOUT", "120")
os.environ.setdefault("CPL_VSIL_CURL_CACHE_SIZE", "200000000")

import rasterio  # noqa: E402
from rasterio.errors import RasterioIOError  # noqa: E402
from rasterio.windows import Window  # noqa: E402

logger = get_logger(__name__)

_BASE_URL = "https://data.chc.ucsb.edu/products/CHIRPS-2.0/global_daily/tifs/p05"
# The PRELIM sibling.  Hardcoded BESIDE _BASE_URL and pinned by a deck rather than read from
# configs/sources/chirps.yaml on purpose (T-A4): that config declares a THIRD, CHIRPS-3.0 path which
# MEASURED 404 on 2026-09-11 and which no code has ever read.  A lane that "fixed" the config/code
# divergence while adding prelim would point this fetcher at a dead host and take CHIRPS fully dark
# behind green job exits.  The divergence is a standing docket item, not a drive-by fix here.
_PRELIM_BASE_URL = "https://data.chc.ucsb.edu/products/CHIRPS-2.0/prelim/global_daily/tifs/p05"
_NODATA = -9999.0

# The product a day's values came from.  ABSENT is NOT an error -- it is "neither product publishes
# this day yet", which for a future or just-closed day is the ordinary state of the world.
PRODUCT_FINAL = "final"
PRODUCT_PRELIM = "prelim"
PRODUCT_ABSENT = "absent"

# HOW FAR BACK THE PRELIM FALLBACK MAY REACH, IN MONTHS, counted from the current calendar month.
# 1 == {current month, previous month} and nothing older.  ONE constant, TWO users: this module's
# fallback window and the bronze tasks' final RE-CHECK window (jobs/batch/chirps_*_to_bronze_task.py),
# so the month a run may read prelim for and the month it may re-check for a landed final can never
# drift apart.
#
# WHY MONTH-INDEXED AND NOT A DAY COUNT.  A day-count horizon (``today - month_end(M) <= 28``) and the
# month-indexed rule are NOT the same fence: on the 29th/30th/31st of a month the day-count rule drops
# the previous month OUT while ``_months_to_process`` -- which is month-indexed -- keeps processing it,
# so the fetch window and the re-check window would disagree for three days a month.  The month-indexed
# rule is the one ``_months_to_process`` already expresses, it never reaches M-2 under either reading
# (which is the whole of T-A3's guarantee), and it exceeds the FINAL's declared 25-day revision horizon
# by at most 3 days at a month boundary -- which buys one extra final RE-CHECK and nothing else:
# fail-CLOSED, and cheap.
#
# KEEP IT INDEPENDENT of ``_COMPLETENESS_LOOKBACK_DAYS = 120`` in the bronze tasks.  That constant is a
# patience window for a month the source may yet complete, and at 120 days it would reach prelim for any
# incomplete current-year month back to roughly M-4.
PRELIM_MONTH_REACH = 1


def _month_index(year: int, month: int) -> int:
    """A monotone month ordinal, so 'how many months apart' is one subtraction and never a day count."""
    return int(year) * 12 + (int(month) - 1)


def is_prelim_reachable(year: int, month: int, today: date | None = None) -> bool:
    """May the PRELIM product be read for a day of ``year``-``month``?  See :data:`PRELIM_MONTH_REACH`.

    True only for the current month and the ``PRELIM_MONTH_REACH`` months before it.  A FUTURE month is
    False (neither product exists for it, and admitting it would only buy 404s), and every month older
    than the reach is False -- which is what keeps the 1981..2026-07 corpus byte-identical to the
    pre-prelim fetcher: outside this window :func:`fetch_chirps_daily_values` is the pre-lane function,
    request for request."""
    delta = _month_index(today.year, today.month) if today is not None else _month_index(
        date.today().year, date.today().month)
    return 0 <= delta - _month_index(year, month) <= PRELIM_MONTH_REACH


def day_url_template(year: int, month: int, *, preliminary: bool = False) -> str:
    """One month's URL with the DAY left as ``{DD}`` -- the provenance string bronze ``_meta.json``
    records, and the ONE authority for either product's path.

    Both batch tasks used to carry the final template AND the prelim template as their own f-string
    literals (four copies of two paths), so a base-URL move could take the recorded provenance out of
    step with the bytes actually fetched -- a drift whose only symptom would be a correct-looking
    ``source_url_template`` beside rows read from somewhere else. The day builders below now format
    THIS string, so the filename shape exists exactly once in the estate."""
    base = _PRELIM_BASE_URL if preliminary else _BASE_URL
    return f"{base}/{year}/chirps-v2.0.{year}.{month:02d}.{{DD}}.tif.gz"


def _build_cog_url(year: int, month: int, day: int) -> str:
    return day_url_template(year, month).format(DD=f"{day:02d}")


def _build_prelim_cog_url(year: int, month: int, day: int) -> str:
    """The PRELIM URL for one day -- the FINAL path with ``prelim/`` inserted, and nothing else."""
    return day_url_template(year, month, preliminary=True).format(DD=f"{day:02d}")


def _is_absent(exc: BaseException) -> bool:
    """Is this ``RasterioIOError`` the source saying "no such file", as opposed to refusing to serve it?

    THE PREDICATE IS NARROW ON PURPOSE (T-A2).  ``_read_cog_values`` raises ``RasterioIOError`` for MANY
    causes, and a 503 / connection reset from a throttled UCSB is one of them.  A naive
    "the final failed -> try prelim" would mint a PRELIM reading for a day whose FINAL EXISTS every time
    the host is under load -- and since the day then counts as observed, that wrong vintage is permanent
    for the month.  So the fallback fires only on the SAME 404 predicate the pre-lane code used, and any
    other I/O error propagates to the retry path exactly as it always did."""
    text = str(exc)
    return "404" in text or "does not exist" in text.lower()


def fetch_chirps_daily_values(
    year: int,
    month: int,
    day: int,
    locations: list[Region],
    today: date | None = None,
) -> dict[str, float | None]:
    """Extract daily CHIRPS precipitation (mm) for each named location.

    Opens the CHIRPS COG file once via HTTP range-read and extracts a
    single pixel value per location.  A 404 response (file not yet published
    or outside the historical record) is handled silently — all regions are
    returned as None.  Other I/O errors are retried up to three times by the
    inner helper before propagating.

    THE VALUES-ONLY WRAPPER (T-A1).  This signature is PUBLIC -- both CHIRPS Batch entrypoints and
    ``tests/unit/test_chirps_ingestion.py`` read its return as "the values" -- so the prelim lane does
    NOT change it.  The product dimension lives on
    :func:`fetch_chirps_daily_values_with_product`, and this function drops it.  For any month outside
    :data:`PRELIM_MONTH_REACH` -- every month of 1981 through the month before last -- the two functions
    issue exactly the pre-lane request and return exactly the pre-lane dict.

    Args:
        year: Calendar year.
        month: Calendar month (1–12).
        day: Calendar day (1–31).
        locations: List of dicts, each with keys 'region', 'latitude', 'longitude'.
        today: The run's calendar day, for the prelim reach test (default: the system date).

    Returns:
        Dict mapping region name → precipitation mm (float) or None.
    """
    return fetch_chirps_daily_values_with_product(year, month, day, locations, today=today)[0]


def fetch_chirps_daily_values_with_product(
    year: int,
    month: int,
    day: int,
    locations: list[Region],
    today: date | None = None,
) -> tuple[dict[str, float | None], str]:
    """The same pixel read, plus WHICH PRODUCT answered: ``final`` | ``prelim`` | ``absent``.

    FINAL FIRST, ALWAYS.  The authoritative block is requested for every day; only when it answers the
    narrow 404 predicate (:func:`_is_absent`) -- and only when the day's month is still within
    :data:`PRELIM_MONTH_REACH` -- is the PRELIM URL tried.  Any other I/O error on either product
    propagates after the inner retry, so a throttled host can never be mistaken for an unpublished day.

    THE PRODUCT IS A PROPERTY OF THE DAY, NOT OF A REGION (T-B3).  There is ONE global raster per day
    per product, so the returned string describes the FILE every location was read out of.  That is
    why the caller must persist the product from THIS result and never re-derive it from the rows: a
    region whose one prelim day happens to sit on a nodata pixel has no prelim-valued row at all, and a
    row-derived flag would call that month final while prelim bytes fed it.

    ``absent`` returns the same all-None dict the pre-lane 404 branch returned -- a TRUTHY dict, which
    is exactly why the bronze all-null write gate exists one layer up."""
    url = _build_cog_url(year, month, day)
    try:
        return _read_cog_values(url, locations), PRODUCT_FINAL
    except RasterioIOError as exc:
        if not _is_absent(exc):
            raise
        logger.info("CHIRPS FINAL not available (404): %s", url)

    if not is_prelim_reachable(year, month, today):
        # Outside the reach this is the pre-lane return, request for request: one GET, all-None.
        return {loc["region"]: None for loc in locations}, PRODUCT_ABSENT

    prelim_url = _build_prelim_cog_url(year, month, day)
    try:
        values = _read_cog_values(prelim_url, locations)
    except RasterioIOError as exc:
        if not _is_absent(exc):
            raise
        logger.info("CHIRPS PRELIM not available either (404): %s -- skipping day", prelim_url)
        return {loc["region"]: None for loc in locations}, PRODUCT_ABSENT
    logger.info("CHIRPS PRELIM read (the final block has not landed): %s", prelim_url)
    return values, PRODUCT_PRELIM


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

    with rasterio.open(f"/vsigzip//vsicurl/{url}") as src:
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
            except Exception as exc:  # noqa: BLE001 — intentional: rasterio pixel read raises diverse errors (numpy/GDAL); set None and continue
                logger.warning("Pixel read failed for region=%s: %s", region, exc)
                result[region] = None

    return result
