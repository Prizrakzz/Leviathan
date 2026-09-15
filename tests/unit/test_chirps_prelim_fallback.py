"""THE CHIRPS v2.0 PRELIM FALLBACK -- the URL swap, the narrow 404 predicate, and the HORIZON FENCE.

WHAT THIS DECK IS FOR.  ``gold_weather_z.drought_z`` rides CHIRPS v2.0 FINAL, which publishes a whole
month AS ONE BLOCK +11..+16 days past month-end (Last-Modified, FIVE blocks over five years: 2026-07 ->
+14, 2025-08 -> +12, 2024-08 -> +14, 2020-08 -> +16, sampled 2026-09-11, and 2026-08 -> +11 measured
2026-09-15 -- ONE block write at Last-Modified 2026-09-11 21:10Z, hours after the 09-11 probe recorded
it absent, which is what moved the lower bound down from 12).  CHIRPS v2.0 also publishes a PRELIM daily series
in PENTAD BLOCKS, each landing ~+2 days past its pentad (worst observed slip +4), so a COMPLETE month of
prelim exists +2 days past month-end.  Reading it moves a SERVED board metric about eighteen days
earlier -- provided three things hold, and this deck pins all three.

1. THE PRODUCT SWAP IS A URL SWAP AND NOTHING ELSE.  MEASURED on real fixtures 2026-09-11: final and
   prelim carry an IDENTICAL 7200x2000 grid, float32, EPSG:4326, affine (0.05, 0, -180, 0, -0.05, 50.0),
   ``nodata=None``, untiled, and ``src.index(lon, lat)`` resolves to the SAME pixel on both
   (us_corn_ohio -> px(199,1929); malaysia_palm -> px(939,5629); brazil_soy -> px(1259,2479)).  So
   ``_read_cog_values`` is UNTOUCHED and both products go through it, sentinel and all.

2. THE FALLBACK FIRES ONLY ON A 404 (T-A2).  ``_read_cog_values`` raises ``RasterioIOError`` for many
   causes; a 503 or connection reset from a throttled UCSB is one of them.  A wrapper that fell through
   to prelim on ANY I/O error would mint a prelim reading for a day whose FINAL EXISTS every time the
   host is under load -- and since the day then counts as observed, that wrong vintage is permanent for
   the month.  MEASURED proof the vintages differ: malaysia_palm 2026-07-15 read 6.5214 mm final vs
   7.6490 mm prelim, a 17% over-read at one cell.

3. THE HORIZON IS THE BYTE-IDENTITY FENCE (T-A3, the worst fail-open in the lane).  The prelim archive
   is LIVE back to at least 2020 (2020-08-15 / 2024-08-15 / 2025-08-15 all HTTP 200 with their original
   mtimes), so "final, else prelim" written with no window would reach prelim for ANY historical day
   whose final 404s -- back to 1981.  The bronze rewrite rule is strictly monotone on observed days, so
   a 1981 month sitting at 30/31 would gain a 31st PRELIM day, be REWRITTEN, and enter
   ``weather_z._drought_runs``' trailing-prior-year baseline for that (region, month) for every
   subsequent year: the drought_z of years the lane never touched would move, silently.
"""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import rasterio.errors
from leviathan.ingestion.weather import chirps

_LOCATIONS = [
    {"region": "us_corn_iowa", "latitude": 42.03, "longitude": -93.64},
    {"region": "br_corn_mato_grosso", "latitude": -12.64, "longitude": -55.42},
]
_TODAY = date(2026, 9, 15)


@pytest.fixture(autouse=True)
def _no_retry_sleep():
    """Remove the BACKOFF, never the RETRY.

    ``_read_cog_values`` is wrapped in ``wait_exponential(multiplier=2, min=2, max=30)`` over three
    attempts, so every 404 case below costs a real 6 seconds of sleeping and this deck would take
    well over a minute doing nothing. The wait is swapped for zero and the ATTEMPT COUNT is left
    alone -- the retry behaviour under test (a 404 still exhausts its attempts before the fallback
    decides anything) is unchanged, only the wall clock moves."""
    from tenacity import wait_none
    original = chirps._read_cog_values.retry.wait
    chirps._read_cog_values.retry.wait = wait_none()
    try:
        yield
    finally:
        chirps._read_cog_values.retry.wait = original


def _dataset(value: float, nodata=None):
    ds = MagicMock()
    ds.__enter__ = lambda s: s
    ds.__exit__ = MagicMock(return_value=False)
    ds.nodata = nodata
    ds.height, ds.width = 2000, 7200
    ds.index.return_value = (1259, 2479)
    ds.read.return_value = np.array([[value]], dtype=np.float32)
    return ds


def _404() -> rasterio.errors.RasterioIOError:
    return rasterio.errors.RasterioIOError("HTTP response code: 404")


# ---------------------------------------------------------------------------
# The two URLs, pinned as strings (T-A4: configs/sources/chirps.yaml declares a THIRD, CHIRPS-3.0 path
# that MEASURED 404 and that no code reads -- these constants are hardcoded so a config "fix" cannot
# point the fetcher at a dead host)
# ---------------------------------------------------------------------------
class TestUrls:
    def test_the_final_url_is_byte_for_byte_the_pre_lane_string(self):
        assert chirps._build_cog_url(2020, 6, 15) == (
            "https://data.chc.ucsb.edu/products/CHIRPS-2.0/global_daily/tifs/p05/2020/"
            "chirps-v2.0.2020.06.15.tif.gz")

    def test_the_prelim_url_is_the_final_url_with_one_path_segment_inserted(self):
        assert chirps._build_prelim_cog_url(2026, 8, 20) == (
            "https://data.chc.ucsb.edu/products/CHIRPS-2.0/prelim/global_daily/tifs/p05/2026/"
            "chirps-v2.0.2026.08.20.tif.gz")
        final = chirps._build_cog_url(2026, 8, 20)
        assert chirps._build_prelim_cog_url(2026, 8, 20) == final.replace(
            "CHIRPS-2.0/global_daily", "CHIRPS-2.0/prelim/global_daily")

    def test_neither_base_url_points_at_the_dead_chirps_3_path(self):
        for url in (chirps._BASE_URL, chirps._PRELIM_BASE_URL):
            assert "CHIRPS-2.0" in url and "CHIRPS-3" not in url


# ---------------------------------------------------------------------------
# The horizon -- T-A3
# ---------------------------------------------------------------------------
class TestPrelimReach:
    def test_the_current_month_is_reachable(self):
        assert chirps.is_prelim_reachable(2026, 9, _TODAY) is True

    def test_the_previous_month_is_reachable(self):
        assert chirps.is_prelim_reachable(2026, 8, _TODAY) is True

    def test_M_MINUS_2_IS_NOT(self):
        """The whole fence in one assertion: two months back is already history."""
        assert chirps.is_prelim_reachable(2026, 7, _TODAY) is False

    def test_a_1981_backfill_month_is_not_reachable(self):
        assert chirps.is_prelim_reachable(1981, 1, _TODAY) is False

    @pytest.mark.parametrize("year", [2014, 2020, 2024, 2025])
    def test_no_historical_year_is_reachable_even_though_its_prelim_files_EXIST(self, year):
        """2020-08-15 / 2024-08-15 / 2025-08-15 prelim all HTTP 200 on 2026-09-11 with their ORIGINAL
        mtimes. The archive is live; the fence is what keeps history from moving."""
        for month in range(1, 13):
            assert chirps.is_prelim_reachable(year, month, _TODAY) is False

    def test_the_january_edge_reaches_back_across_the_year_boundary(self):
        jan = date(2027, 1, 9)
        assert chirps.is_prelim_reachable(2026, 12, jan) is True
        assert chirps.is_prelim_reachable(2026, 11, jan) is False

    def test_a_FUTURE_month_is_not_reachable(self):
        """Neither product exists for it, and admitting it would only buy a second 404 per day."""
        assert chirps.is_prelim_reachable(2026, 10, _TODAY) is False
        assert chirps.is_prelim_reachable(2027, 1, _TODAY) is False

    def test_the_reach_is_ONE_named_constant_and_it_is_the_month_count(self):
        assert chirps.PRELIM_MONTH_REACH == 1
        assert chirps._month_index(2027, 1) - chirps._month_index(2026, 12) == 1


class TestTheHistoricalCorpusNeverTouchesPrelim:
    def test_a_2014_day_whose_FINAL_404s_does_NOT_reach_prelim(self):
        """P0's deck, written before any prelim read existed. ONE URL -- the final's -- all-None, and
        product=absent. The url SET is the assertion and not the call count: ``_read_cog_values`` is
        wrapped in a three-attempt tenacity retry, so one logical request is three opens of the SAME
        url, exactly as it was before this lane."""
        with patch("rasterio.open", side_effect=_404()) as opened:
            values, product = chirps.fetch_chirps_daily_values_with_product(
                2014, 3, 9, _LOCATIONS, today=_TODAY)
        assert product == chirps.PRODUCT_ABSENT
        assert values == {"us_corn_iowa": None, "br_corn_mato_grosso": None}
        urls = {c[0][0] for c in opened.call_args_list}
        assert len(urls) == 1, urls
        assert all("prelim" not in u for u in urls)

    def test_and_the_values_only_wrapper_is_the_pre_lane_function_there(self):
        with patch("rasterio.open", side_effect=_404()) as opened:
            out = chirps.fetch_chirps_daily_values(2014, 3, 9, _LOCATIONS, today=_TODAY)
        assert out == {"us_corn_iowa": None, "br_corn_mato_grosso": None}
        assert len({c[0][0] for c in opened.call_args_list}) == 1


# ---------------------------------------------------------------------------
# The fallback itself -- T-A1, T-A2
# ---------------------------------------------------------------------------
class TestFallback:
    def test_a_published_FINAL_is_read_and_prelim_is_never_requested(self):
        with patch("rasterio.open", return_value=_dataset(4.5)) as opened:
            values, product = chirps.fetch_chirps_daily_values_with_product(
                2026, 8, 20, _LOCATIONS, today=_TODAY)
        assert product == chirps.PRODUCT_FINAL
        assert values == {"us_corn_iowa": 4.5, "br_corn_mato_grosso": 4.5}
        assert all("prelim" not in c[0][0] for c in opened.call_args_list)

    def test_an_ABSENT_final_inside_the_reach_falls_through_to_PRELIM(self):
        calls: list[str] = []

        def _open(url, *a, **kw):
            calls.append(url)
            if "prelim" not in url:
                raise _404()
            return _dataset(7.5)

        with patch("rasterio.open", side_effect=_open):
            values, product = chirps.fetch_chirps_daily_values_with_product(
                2026, 8, 20, _LOCATIONS, today=_TODAY)
        assert product == chirps.PRODUCT_PRELIM
        assert values == {"us_corn_iowa": 7.5, "br_corn_mato_grosso": 7.5}
        # the FINAL is exhausted FIRST (three attempts on the same url), and only then the prelim
        assert all("prelim" not in u for u in calls[:-1]), calls
        assert "prelim" in calls[-1]

    def test_neither_product_published_is_ABSENT_and_the_all_None_dict_is_still_TRUTHY(self):
        """The all-None dict is what the bronze all-null WRITE GATE exists to refuse: a truthy dict of
        Nones is exactly what minted the 2026-08-22 August skeleton."""
        with patch("rasterio.open", side_effect=_404()):
            values, product = chirps.fetch_chirps_daily_values_with_product(
                2026, 9, 14, _LOCATIONS, today=_TODAY)
        assert product == chirps.PRODUCT_ABSENT
        assert values == {"us_corn_iowa": None, "br_corn_mato_grosso": None}
        assert bool(values) is True

    def test_A_503_ON_THE_FINAL_DOES_NOT_REACH_PRELIM(self):
        """T-A2, and it is the one that would have been invisible. A throttled host must never be read
        as an unpublished day: the prelim value would be minted for a day whose final EXISTS, the day
        would count as observed, and the wrong vintage would be permanent for that month."""
        calls: list[str] = []

        def _open(url, *a, **kw):
            calls.append(url)
            raise rasterio.errors.RasterioIOError("HTTP response code: 503")

        with patch("rasterio.open", side_effect=_open):
            with pytest.raises(rasterio.errors.RasterioIOError, match="503"):
                chirps.fetch_chirps_daily_values_with_product(2026, 8, 20, _LOCATIONS, today=_TODAY)
        assert all("prelim" not in url for url in calls), calls

    def test_a_connection_reset_on_the_final_propagates_exactly_as_before(self):
        with patch("rasterio.open", side_effect=rasterio.errors.RasterioIOError("connection reset")):
            with pytest.raises(rasterio.errors.RasterioIOError, match="connection reset"):
                chirps.fetch_chirps_daily_values_with_product(2026, 8, 20, _LOCATIONS, today=_TODAY)

    def test_a_503_ON_THE_PRELIM_propagates_too_and_is_never_read_as_absence(self):
        def _open(url, *a, **kw):
            if "prelim" not in url:
                raise _404()
            raise rasterio.errors.RasterioIOError("HTTP response code: 503")

        with patch("rasterio.open", side_effect=_open):
            with pytest.raises(rasterio.errors.RasterioIOError, match="503"):
                chirps.fetch_chirps_daily_values_with_product(2026, 8, 20, _LOCATIONS, today=_TODAY)

    def test_the_predicate_is_the_pre_lane_one_verbatim(self):
        assert chirps._is_absent(rasterio.errors.RasterioIOError("HTTP response code: 404")) is True
        assert chirps._is_absent(rasterio.errors.RasterioIOError("... does not exist ...")) is True
        assert chirps._is_absent(rasterio.errors.RasterioIOError("HTTP response code: 503")) is False
        assert chirps._is_absent(rasterio.errors.RasterioIOError("connection reset")) is False


# ---------------------------------------------------------------------------
# T-A5 -- the nodata sentinel is the SAME for both products
# ---------------------------------------------------------------------------
class TestNodataSentinel:
    def test_the_sentinel_constant_has_not_moved(self):
        assert chirps._NODATA == -9999.0

    def test_a_PRELIM_fill_value_is_a_NULL_and_never_a_dry_day(self):
        """MEASURED: BOTH products declare ``nodata=None``, so ``_read_cog_values`` falls back to
        -9999.0 for both. If a prelim file ever shipped a different fill, -9999 would land as a real
        reading, be clipped to 0.0 at silver (chirps_weather.py clip(lower=0.0)) and count as a REAL DRY
        DAY -- inflating every drought run, undetectably, because 0.0 mm is an observation the estate
        deliberately keeps."""
        def _open(url, *a, **kw):
            if "prelim" not in url:
                raise _404()
            return _dataset(-9999.0, nodata=None)

        with patch("rasterio.open", side_effect=_open):
            values, product = chirps.fetch_chirps_daily_values_with_product(
                2026, 8, 20, _LOCATIONS, today=_TODAY)
        assert product == chirps.PRODUCT_PRELIM
        assert values == {"us_corn_iowa": None, "br_corn_mato_grosso": None}

    def test_a_declared_nodata_on_the_prelim_file_is_honoured_over_the_fallback(self):
        def _open(url, *a, **kw):
            if "prelim" not in url:
                raise _404()
            return _dataset(-1.0, nodata=-1.0)

        with patch("rasterio.open", side_effect=_open):
            values, _ = chirps.fetch_chirps_daily_values_with_product(
                2026, 8, 20, _LOCATIONS, today=_TODAY)
        assert values == {"us_corn_iowa": None, "br_corn_mato_grosso": None}


# ---------------------------------------------------------------------------
# T-A1 -- the wrapper does not mutate the public signature
# ---------------------------------------------------------------------------
class TestWrapperNotMutate:
    def test_the_values_only_function_still_returns_a_bare_values_dict(self):
        with patch("rasterio.open", return_value=_dataset(1.25)):
            out = chirps.fetch_chirps_daily_values(2020, 6, 15, _LOCATIONS)
        assert out == {"us_corn_iowa": 1.25, "br_corn_mato_grosso": 1.25}
        assert not isinstance(out, tuple)

    def test_the_product_function_returns_a_two_tuple_of_values_and_a_known_product(self):
        with patch("rasterio.open", return_value=_dataset(1.25)):
            out = chirps.fetch_chirps_daily_values_with_product(2020, 6, 15, _LOCATIONS)
        assert isinstance(out, tuple) and len(out) == 2
        assert out[1] in {chirps.PRODUCT_FINAL, chirps.PRODUCT_PRELIM, chirps.PRODUCT_ABSENT}

    def test_the_reader_stack_is_the_same_vsigzip_vsicurl_idiom_for_BOTH_products(self):
        def _open(url, *a, **kw):
            if "prelim" not in url:
                raise _404()
            return _dataset(2.0)

        with patch("rasterio.open", side_effect=_open) as opened:
            chirps.fetch_chirps_daily_values_with_product(2026, 8, 20, _LOCATIONS, today=_TODAY)
        for call in opened.call_args_list:
            assert call[0][0].startswith("/vsigzip//vsicurl/")


# ---------------------------------------------------------------------------
# THE READ TIMEOUT (close-out 2026-09-15) -- 120, and an env value still wins
# ---------------------------------------------------------------------------
# CHIRPS ships an UNTILED stripped TIFF whose IFD sits at byte 57,600,008 (7200*2000*4 + 8), AFTER the
# whole image, and /vsigzip/ cannot seek a gzip stream -- so reading ONE pixel means inflating 57.6 MB.
# At the shipped 30 s, 17 of the 31 opens of 2026-08 died on
# `TIFFReadDirectory:Failed to read directory at offset 57600008`
# (scratchpad/chirps_prelim/COST_MEASUREMENT.md), and a timeout reads as a LOST DAY, never an error.
# 120 is PROVISIONAL -- that was a home link, not us-east-1 -- and the number that revises it is
# fetch_failures per month after the first Fargate run.
class TestTheGdalReadTimeout:
    def test_the_default_is_120_and_it_is_a_SETDEFAULT(self):
        import inspect
        src = inspect.getsource(chirps)
        assert 'os.environ.setdefault("GDAL_HTTP_TIMEOUT", "120")' in src, (
            "the default moved, or setdefault became an assignment -- an assignment would take the "
            "jobdef-environment lever away and make every retune a rebuild")
        assert "57600008" in src, "the measurement that chose the number must stay beside it"

    def test_a_JOBDEF_ENVIRONMENT_VALUE_WINS_WITHOUT_A_REBUILD(self):
        """The operating lever, pinned as behaviour and not as prose: the runbook tells the operator to
        raise this from containerOverrides if the first smoke still shows TIFFReadDirectory failures,
        and that instruction is only true while the import cannot clobber a value already set."""
        import os
        import subprocess
        import sys
        probe = ("import os, leviathan.ingestion.weather.chirps; "
                 "print(os.environ['GDAL_HTTP_TIMEOUT'])")

        raised = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True,
                                env={**os.environ, "GDAL_HTTP_TIMEOUT": "300"})
        assert raised.returncode == 0, raised.stderr[-500:]
        assert raised.stdout.strip() == "300", "the module overwrote the jobdef's value"

        bare = dict(os.environ)
        bare.pop("GDAL_HTTP_TIMEOUT", None)
        default = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True,
                                 env=bare)
        assert default.returncode == 0, default.stderr[-500:]
        assert default.stdout.strip() == "120"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
