"""THE M-2 IMMUTABILITY ASSUMPTION, CLOSED -- ``chirps_to_bronze_task._months_to_process`` (2026-09-11).

THE LATENT FREEZE. The daily task always refetches the current AND previous month; an OLDER
current-year month was refetched only when a sentinel bronze object was ABSENT
(``chirps_to_bronze_task.py:70-81``, the 2026-08-22 partial-month fix). Its stated reason was "by M-2
the source is final and the sentinel may again be trusted".

THAT REASON IS MEASURABLY FALSE FOR CHIRPS. v2.0 finals publish in MONTH BLOCKS: on 2026-09-11 the
directory index of .../global_daily/tifs/p05/2026/ ended at ``chirps-v2.0.2026.07.31.tif.gz`` and every
August day HEADed 404, eleven days past month-end -- so the whole August block will land AFTER August
becomes M-2 on 2026-10-01. The 2026-08-22 all-null skeleton was already present, so from that date the
sentinel would have proved "processed" forever and August would never have been re-downloaded again,
not even after the source published it.

So the sentinel test is now a COMPLETENESS test: absent -> download; present but holding fewer observed
days than the calendar month has -> download; complete -> leave it, permanently. A month drops out of
the window the instant it completes, which is what makes the extra cost self-retiring.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

_REPO = Path(__file__).resolve().parents[2]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, _REPO / "jobs" / "batch" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


daily = _load("chirps_to_bronze_task")
yearly = _load("chirps_year_to_bronze_task")


def _loc(region: str, lat: float, country: str = "united_states") -> dict:
    return {"country": country, "region": region, "latitude": lat, "longitude": 0.0}


class _Body:
    def __init__(self, data):
        self._data = data

    def read(self):
        return self._data


class _S3:
    """head_object answers from ``present``; get_object serves meta/parquet bodies."""

    def __init__(self, present: set, bodies: dict | None = None):
        self.present = set(present)
        self.bodies = dict(bodies or {})
        self.heads: list[str] = []
        self.gets: list[str] = []

    def head_object(self, Bucket: str, Key: str):  # noqa: N803
        self.heads.append(Key)
        if Key not in self.present:
            raise RuntimeError("404")
        return {"ContentLength": 1}

    def get_object(self, Bucket: str, Key: str):  # noqa: N803
        self.gets.append(Key)
        if Key not in self.bodies:
            raise KeyError(Key)
        return {"Body": _Body(self.bodies[Key])}


def _key(month: int, region: str = "us_corn_ohio", year: int = 2026) -> str:
    from leviathan.storage.paths import bronze_weather_key
    return bronze_weather_key("chirps", "corn_cbot", "united_states", region, year, month,
                              "part-000.parquet")


def _meta_body(nonnull: int) -> bytes:
    return json.dumps({"row_count": 31, "nonnull_count": nonnull}).encode()


def _months(s3, locations, *, today: date, year: int = 2026, force: bool = False) -> list[int]:
    return daily._months_to_process(s3, "b", "corn_cbot", locations, year, force, today)


# ---------------------------------------------------------------------------
# the completeness lookback window
# ---------------------------------------------------------------------------
class TestCompletenessWindow:
    def test_a_recently_ended_month_is_inside_the_window(self):
        """August 2026 on 2026-09-11: eleven days past month-end, exactly the live case."""
        assert daily._within_completeness_window(2026, 8, date(2026, 9, 11)) is True

    def test_a_settled_month_falls_out_and_returns_the_pre_fix_existence_test(self):
        """Past the lookback the sentinel is trusted on EXISTENCE again, so a 1981 backfill month is
        never re-probed and the pre-fix cost profile is restored for every settled month."""
        assert daily._within_completeness_window(2026, 1, date(2026, 12, 31)) is False

    def test_the_boundary_is_inclusive_and_measured_from_MONTH_END(self):
        w = daily._COMPLETENESS_LOOKBACK_DAYS
        end = date(2026, 8, 31)
        assert daily._within_completeness_window(2026, 8, end) is True
        assert daily._within_completeness_window(
            2026, 8, date.fromordinal(end.toordinal() + w)) is True
        assert daily._within_completeness_window(
            2026, 8, date.fromordinal(end.toordinal() + w + 1)) is False

    def test_the_window_is_measured_not_guessed(self):
        """>= the longest CHIRPS block lag actually observed (the July 2026 block was complete by
        2026-08-22, <= 22 days past month-end) with real headroom, and bounded so a month the source
        will never complete stops costing a daily re-download within one quarter."""
        assert 90 <= daily._COMPLETENESS_LOOKBACK_DAYS <= 190


# ---------------------------------------------------------------------------
# the window itself
# ---------------------------------------------------------------------------
class TestMonthWindow:
    def test_an_INCOMPLETE_older_month_re_enters_the_window(self, monkeypatch):
        """THE AUGUST CASE FROM 2026-10-01, when August becomes M-2. Before this fix the present
        all-null skeleton proved "processed" and August was never downloaded again."""
        today = date(2026, 10, 5)
        aug = _key(8)
        s3 = _S3(present={_key(m) for m in range(1, 10)},
                 bodies={aug.replace("part-000.parquet", "_meta.json"): _meta_body(0)})
        got = _months(s3, [_loc("us_corn_ohio", 40.0)], today=today)
        assert 8 in got, f"an all-null August stayed out of the window: {got}"

    def test_a_COMPLETE_older_month_leaves_the_window_permanently(self, monkeypatch):
        """Self-retiring: the instant a month holds every calendar day it stops costing anything."""
        today = date(2026, 10, 5)
        bodies = {}
        for m in range(1, 10):
            import calendar
            bodies[_key(m).replace("part-000.parquet", "_meta.json")] = _meta_body(
                calendar.monthrange(2026, m)[1])
        s3 = _S3(present={_key(m) for m in range(1, 10)}, bodies=bodies)
        got = _months(s3, [_loc("us_corn_ohio", 40.0)], today=today)
        assert got == [9, 10], f"a complete month stayed in the window: {got}"

    def test_an_ABSENT_sentinel_still_re_downloads_exactly_as_before(self):
        today = date(2026, 10, 5)
        s3 = _S3(present={_key(m) for m in range(1, 10) if m != 4})
        got = _months(s3, [_loc("us_corn_ohio", 40.0)], today=today)
        assert 4 in got

    def test_an_UNREADABLE_sentinel_count_does_NOT_spend_a_month_of_raster_reads(self):
        """Unknown is never grounds to act -- here the act is downloading 31 global rasters per
        commodity, so an unreadable count must not trigger it."""
        today = date(2026, 10, 5)
        s3 = _S3(present={_key(m) for m in range(1, 10)}, bodies={})   # head OK, no body readable
        got = _months(s3, [_loc("us_corn_ohio", 40.0)], today=today)
        assert got == [9, 10], got

    def test_the_current_and_previous_month_are_still_unconditional(self):
        """The 2026-08-22 partial-month fix is preserved byte for byte; no head_object is spent on them."""
        today = date(2026, 9, 11)
        s3 = _S3(present={_key(m) for m in range(1, 10)},
                 bodies={_key(m).replace("part-000.parquet", "_meta.json"): _meta_body(31)
                         for m in range(1, 10)})
        got = _months(s3, [_loc("us_corn_ohio", 40.0)], today=today)
        assert 8 in got and 9 in got
        assert all(not h.endswith("month=08/part-000.parquet") for h in s3.heads)

    def test_force_overwrite_still_takes_every_elapsed_month(self):
        today = date(2026, 9, 11)
        s3 = _S3(present=set())
        assert _months(s3, [_loc("us_corn_ohio", 40.0)], today=today, force=True) == list(range(1, 10))

    def test_a_PAST_year_is_untouched_by_any_of_this(self):
        s3 = _S3(present=set())
        assert _months(s3, [_loc("us_corn_ohio", 40.0)], today=date(2026, 9, 11), year=2019) == \
            list(range(1, 13))


# ---------------------------------------------------------------------------
# the sentinel choice -- forced by the all-null write gate
# ---------------------------------------------------------------------------
class TestSentinelLocation:
    def test_the_sentinel_must_be_a_region_CHIRPS_CAN_COVER(self):
        """THE REGRESSION THE WRITE GATE OPENED. An out-of-band region (|lat| > 50) is now never
        written at all, so ``locations[0]`` sitting in Saskatchewan would leave a commodity with NO
        sentinel for ANY month -- and every elapsed month back in the window forever, re-downloading
        global rasters daily. The sentinel is the in-band region nearest the equator instead."""
        picked = daily._sentinel_location([_loc("saskatchewan", 52.0, "canada"),
                                           _loc("us_corn_ohio", 40.0)])
        assert picked["region"] == "us_corn_ohio"

    def test_nearest_the_equator_among_in_band_regions_is_deterministic(self):
        picked = daily._sentinel_location([_loc("north", 48.0), _loc("south", -12.0),
                                           _loc("mid", 33.0)])
        assert picked["region"] == "south"

    def test_a_commodity_wholly_outside_the_band_is_STRUCTURAL_ABSENCE_not_a_gap(self):
        assert daily._sentinel_location([_loc("saskatchewan", 52.0, "canada"),
                                         _loc("poland", 52.5, "poland")]) is None

    def test_and_such_a_commodity_downloads_NOTHING_rather_than_every_month_forever(self):
        s3 = _S3(present=set())
        got = _months(s3, [_loc("saskatchewan", 52.0, "canada")], today=date(2026, 9, 11))
        assert got == [], f"an out-of-band commodity queued {got} months of global raster reads"

    def test_an_UNSTATED_latitude_is_not_an_EXCLUSION(self):
        """FOUND BY tests/unit/test_weather_fetch_trailing_months.py, which carries a Region fixture
        with no ``latitude`` key at all: the first cut of this helper raised KeyError and took the
        whole commodity down. An unknown cannot be PROVEN out of band, and excluding every region
        would leave the commodity with NO sentinel -- every elapsed month back in the window
        permanently. It ranks last and is used only when nothing else qualifies."""
        locs = [{"country": "cote_divoire", "region": "abengourou"}]
        assert daily._sentinel_location(locs) is locs[0], "the pre-fix sentinel, byte for byte"
        assert daily._abs_latitude({"latitude": None}) is None
        assert daily._abs_latitude({"latitude": "not a number"}) is None
        assert daily._abs_latitude({"latitude": "-12.5"}) == 12.5

    def test_a_KNOWN_in_band_region_still_outranks_an_unstated_one(self):
        locs = [{"country": "x", "region": "unstated"}, _loc("us_corn_ohio", 40.0)]
        assert daily._sentinel_location(locs)["region"] == "us_corn_ohio"

    def test_an_empty_location_list_is_None_not_an_IndexError(self):
        assert daily._sentinel_location([]) is None

    def test_the_coverage_band_constant_has_not_drifted_between_the_two_tasks(self):
        """The constant is DUPLICATED (the two Batch entrypoints are invoked by path, so a cross-task
        import would resolve at runtime and not in this deck). This assertion is the pin that makes
        the duplication safe -- configs/sources/chirps.yaml coverage.lat_max = 50 is the source."""
        assert daily.CHIRPS_LAT_LIMIT == yearly.CHIRPS_LAT_LIMIT == 50.0


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
