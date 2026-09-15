"""SUPERSESSION: how a landed FINAL block replaces a month already complete on PRELIM.

THE DEFECT THIS EXISTS TO CLOSE, and it BROKE THE DESIGN AS BRIEFED.  ``_rewrite_admitted`` was a
SCALAR on observed days and EQUAL was a deliberate no-op (AV-12, the ordinary same-day rerun).  When the
FINAL block lands over a complete PRELIM month the observed count goes 31 -> 31 -- EQUAL -- so the final
would be REFUSED and the prelim would stand forever.  "The final supersedes the prelim" simply does not
happen under the shipped yardstick, and the 25-day revision horizon would be a promise the estate
documents and never keeps.  MEASURED proof the vintages differ: malaysia_palm 2026-07-15 read
6.5214 mm from the final block and 7.6490 mm from the prelim, a 17% over-read at one cell.

THE FIX IS A SECOND AXIS, not a stretched scalar: ``(observed_days, final_days)`` as a lexicographic
pair, strictly increasing in either component and decreasing in neither.  ``observed_days`` keeps the
anti-shrink floor exactly; ``final_days`` carries supersession.

EVERY CASE RUNS THROUGH BOTH BATCH MODULES.  The helper trio is duplicated (the entrypoints are invoked
BY PATH, so a cross-task import would resolve at runtime and not in a deck), and running the same table
through both is the drift pin -- the same shape ``test_chirps_bronze_completeness_skip.py`` uses.
"""
from __future__ import annotations

import importlib.util
import json
import sys
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
BOTH = pytest.mark.parametrize("mod", [daily, yearly], ids=["daily", "yearly"])

_PART = "bronze/weather/source=chirps/commodity=c/country=x/region=r/year=2026/month=08/part-000.parquet"
_META = _PART.replace("part-000.parquet", "_meta.json")


class _Body:
    def __init__(self, data):
        self._data = data

    def read(self):
        return self._data


class _S3:
    def __init__(self, objects: dict):
        self.objects = objects
        self.gets: list[str] = []

    def get_object(self, Bucket: str, Key: str):  # noqa: N803
        self.gets.append(Key)
        if Key not in self.objects:
            raise KeyError(Key)
        return {"Body": _Body(self.objects[Key])}


def _parquet_bytes(values: list) -> bytes:
    import io
    buf = io.BytesIO()
    pd.DataFrame({"precipitation_mm": values, "day": range(1, len(values) + 1)}).to_parquet(
        buf, index=False, engine="pyarrow", compression="snappy")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# THE DECISION TABLE -- named, and the row that carries the whole lane is the third one
# ---------------------------------------------------------------------------
@BOTH
@pytest.mark.parametrize(
    "new_obs, stored_obs, new_final, stored_final, admitted, why",
    [
        (31, 22, None, None, True,
         "the pre-lane rule, unstated final axis: 31 > 22 writes"),
        (22, 22, None, None, False,
         "the pre-lane rule, unstated final axis: EQUAL is the ordinary rerun"),
        (31, 31, 31, 0, True,
         "THE LANE'S WHOLE POINT: the FINAL block lands over a complete PRELIM month. Observed is "
         "EQUAL (31 -> 31) and the scalar rule refused it; the final axis 0 -> 31 admits it"),
        (31, 31, 20, 0, True,
         "a HALF-final month supersedes an all-prelim one: 20 > 0 on the final axis"),
        (31, 31, 31, 31, False,
         "an all-final month re-fetched: nothing moved on either axis, so nothing is rewritten -- "
         "the daily re-read of a settled month stays a no-op"),
        (31, 31, 0, 31, False,
         "A VINTAGE REGRESSION. This run saw ZERO final days where the stored partition holds 31 "
         "(UCSB served the prelim while the final block was briefly unreachable). Refused for exactly "
         "the reason an observed-day shrink is refused: a rewrite REPLACES"),
        (25, 31, 25, 0, False,
         "the observed-day SHRINK still binds even when the final axis improves -- a throttled run "
         "that reached 25 of 31 days may not replace a 31-day partition and call it a refresh"),
        (31, 22, 0, 22, False,
         "more observed days but FEWER final days: the pair decreased in one component, so no"),
        (31, None, 31, None, False,
         "an unreadable stored count is an UNKNOWN on both axes; --force_overwrite names the overwrite"),
    ],
)
def test_the_named_supersession_table(mod, new_obs, stored_obs, new_final, stored_final, admitted, why):
    assert mod._rewrite_admitted(new_obs, stored_obs, new_final, stored_final) is admitted, why


@BOTH
class TestTheScalarRuleIsUntouched:
    def test_the_pre_lane_two_argument_form_is_byte_for_byte_the_old_verdict(self, mod):
        """The whole pre-lane decision table, called with two arguments exactly as the shipped callers
        called it. An unstated final axis means the verdict is the scalar one."""
        for new, stored, want in ((31, 0, True), (31, 22, True), (22, 22, False), (0, 0, False),
                                  (19, 22, False), (1, 31, False), (31, None, False), (0, None, False)):
            assert mod._rewrite_admitted(new, stored) is want, (new, stored)

    def test_a_stated_new_final_alone_does_not_change_the_verdict(self, mod):
        """Both sides must be known for the axis to decide anything -- a half-stated pair is no pair."""
        assert mod._rewrite_admitted(31, 31, 31, None) is False
        assert mod._rewrite_admitted(31, 31, None, 0) is False


# ---------------------------------------------------------------------------
# T-B2 -- reading the stored counts must never ask for the new column
# ---------------------------------------------------------------------------
@BOTH
class TestStoredDayCounts:
    def test_a_lane_written_meta_answers_both_axes_in_ONE_small_get(self, mod):
        s3 = _S3({_META: json.dumps(
            {"row_count": 31, "nonnull_count": 31, "final_days": 20, "prelim_days": 11}).encode()})
        assert mod._stored_day_counts(s3, "b", _PART) == (31, 20)
        assert s3.gets == [_META]

    def test_a_PRE_LANE_meta_declares_no_final_days_and_its_observed_days_are_ALL_FINAL(self, mod):
        """The default is a TRUE STATEMENT about those bytes, not a convenience: the prelim product was
        unreachable when every pre-2026-09-15 partition was written, so all of its observed days came
        from the FINAL block."""
        s3 = _S3({_META: json.dumps({"row_count": 31, "nonnull_count": 22}).encode()})
        assert mod._stored_day_counts(s3, "b", _PART) == (22, 22)

    def test_a_legacy_partition_with_NO_meta_falls_back_to_the_parquet_and_still_reads_all_final(self, mod):
        s3 = _S3({_PART: _parquet_bytes([1.0] * 22 + [None] * 9)})
        assert mod._stored_day_counts(s3, "b", _PART) == (22, 22)

    def test_IT_NEVER_ASKS_PYARROW_FOR_is_preliminary(self, mod):
        """T-B2, and it is the one that would have switched the self-heal OFF for all of 1981-2025.
        Asking for a column a pre-lane partition does not have RAISES, the except books that as UNKNOWN,
        and UNKNOWN DECLINES the rewrite -- so the one column added to CARRY supersession would have
        killed it. Proven structurally: the only parquet read in the module names precipitation_mm."""
        import inspect
        src = inspect.getsource(mod._stored_day_counts)
        assert 'columns=["precipitation_mm"]' in src
        assert "is_preliminary" not in src.split('"""')[2]     # not in the CODE, only in the docstring

    def test_a_legacy_partition_WITHOUT_the_column_is_still_readable_end_to_end(self, mod):
        """The behavioural half of the assertion above: an 11-column partition reads cleanly."""
        s3 = _S3({_PART: _parquet_bytes([1.0] * 31)})
        assert mod._stored_day_counts(s3, "b", _PART) == (31, 31)
        assert mod._stored_nonnull_days(s3, "b", _PART) == 31

    def test_an_unreadable_everything_is_UNKNOWN_on_BOTH_axes(self, mod):
        assert mod._stored_day_counts(_S3({}), "b", _PART) == (None, None)

    def test_a_boolean_final_days_is_not_an_integer_count(self, mod):
        """``isinstance(True, int)`` is True in Python; a bool in that field is corrupt, not a count --
        and the fallback then reads the observed count, which is the honest pre-lane statement."""
        s3 = _S3({_META: json.dumps({"nonnull_count": 31, "final_days": True}).encode()})
        assert mod._stored_day_counts(s3, "b", _PART) == (31, 31)


# ---------------------------------------------------------------------------
# T-B6 -- the asymmetry, at month grain
# ---------------------------------------------------------------------------
class TestMonthGrainAsymmetry:
    @pytest.mark.parametrize(
        "final_days, prelim_days, is_preliminary, why",
        [
            (31, 0, False, "only ALL final days make a month final"),
            (0, 31, True, "an all-prelim month is preliminary"),
            (20, 11, True, "a HALF-final month is PRELIMINARY -- ANY prelim day does it. A naive "
                           "`is_preliminary = not final_days` would settle this month as final and "
                           "the re-check would never fire"),
            (30, 1, True, "one prelim day in thirty-one is still a month that will be revised"),
        ],
    )
    def test_any_prelim_day_makes_the_month_preliminary(self, final_days, prelim_days,
                                                        is_preliminary, why):
        assert (prelim_days > 0) is is_preliminary, why

    def test_the_two_task_modules_write_the_same_rule(self):
        """Both entrypoints must state the asymmetry the same way. ``prelim_days > 0`` and never
        ``final_days == 0`` or ``not final_days``: the second would settle a 20-final/11-prelim month as
        FINAL and the re-check would never fire for it (T-B6)."""
        import re
        rule = re.compile(r'"is_preliminary":\s*prelim_days > 0')
        for mod in (daily, yearly):
            src = (_REPO / "jobs" / "batch" / f"{mod.__name__}.py").read_text(encoding="utf-8")
            assert rule.search(src), mod.__name__
            assert not re.search(r'"is_preliminary":\s*(not |final_days ==)', src), mod.__name__


# ---------------------------------------------------------------------------
# T-B4 -- the final RE-CHECK window, and the constant it shares with the fetcher
# ---------------------------------------------------------------------------
class TestTheReCheckWindowSharesTheFetchConstant:
    def test_the_re_check_reads_the_fetcher_s_OWN_reach_function(self):
        """P0 demands ONE named constant for the fetch window and the final re-check window. The daily
        task imports ``is_prelim_reachable`` from the fetcher rather than restating a day count, so the
        month a run may READ prelim for and the month it may RE-CHECK for a landed final cannot drift."""
        import inspect
        src = inspect.getsource(daily._months_to_process)
        assert "is_prelim_reachable(year, month, today)" in src
        from leviathan.ingestion.weather.chirps import PRELIM_MONTH_REACH, is_prelim_reachable
        assert daily.is_prelim_reachable is is_prelim_reachable
        assert daily.PRELIM_MONTH_REACH == PRELIM_MONTH_REACH == 1

    def test_the_clause_is_UNREACHABLE_at_reach_1_and_that_is_stated_rather_than_hidden(self):
        """Honest about its own status: under PRELIM_MONTH_REACH = 1 the loop already appends the
        current and previous month UNCONDITIONALLY and the reach admits nothing older, so the FINAL-axis
        clause cannot fire today. It is written as the INVARIANT -- widen the reach and a prelim month
        would otherwise be stranded past the horizon, which is T-E6's failure mode."""
        import inspect
        from datetime import date
        src = inspect.getsource(daily._months_to_process)
        assert "UNREACHABLE" in src
        today = date(2026, 9, 15)
        # every month the FINAL-axis clause could apply to is already unconditional or out of reach
        for month in range(1, today.month + 1):
            unconditional = month >= today.month - 1
            assert unconditional or not daily.is_prelim_reachable(2026, month, today), month


# ---------------------------------------------------------------------------
# T-C1 -- the cost gate's mitigation (b): ONE open per day per RUN, across ALL commodities
# ---------------------------------------------------------------------------
class TestCrossCommodityDedup:
    """The daily task opened the raster once per (day, COMMODITY) while its sibling year task opened it
    once per day for every commodity at once. While an unpublished day cost an instant 404 that
    difference was invisible; with the PRELIM fallback each such day is a real multi-MB transfer that
    ``/vsigzip/`` must inflate from byte 0, so the per-commodity shape would have multiplied the daily
    run's egress by the commodity count against a public academic host whose pool this task caps at 5
    'to avoid throttling UCSB'."""

    def _cache(self, monkeypatch, locations, product="prelim"):
        calls: list[tuple] = []

        def _fetch(y, m, d, locs, today=None):
            calls.append((y, m, d, tuple(sorted(loc["region"] for loc in locs))))
            return {loc["region"]: 1.0 + i for i, loc in enumerate(locs)}, product

        monkeypatch.setattr(daily, "fetch_chirps_daily_values_with_product", _fetch)
        return daily._DayRasterCache(locations), calls

    def test_the_same_day_is_opened_ONCE_however_many_times_it_is_asked_for(self, monkeypatch):
        flat = daily._build_flat_locations({
            "corn_cbot": [{"country": "us", "region": "ia", "latitude": 42.0, "longitude": -93.0}],
            "soybeans_cbot": [{"country": "br", "region": "mt", "latitude": -12.6, "longitude": -55.4}],
        })
        cache, calls = self._cache(monkeypatch, flat)
        for _ in range(7):
            cache.get(2026, 8, 20)
        assert len(calls) == 1, calls

    def test_every_commodity_reads_ITS_OWN_pixels_out_of_that_one_open(self, monkeypatch):
        corn = [{"country": "us", "region": "ia", "latitude": 42.0, "longitude": -93.0}]
        soy = [{"country": "br", "region": "mt", "latitude": -12.6, "longitude": -55.4}]
        flat = daily._build_flat_locations({"corn_cbot": corn, "soybeans_cbot": soy})
        cache, calls = self._cache(monkeypatch, flat)
        by_coord, product, failure = cache.get(2026, 8, 20)
        assert product == "prelim" and failure is None
        assert by_coord[daily._coord(corn[0])] == 1.0
        assert by_coord[daily._coord(soy[0])] == 2.0
        assert len(calls) == 1

    def test_the_union_drops_DUPLICATE_coordinates_across_commodities(self, monkeypatch):
        """Two contracts naming the same growing cell cost ONE pixel, not two."""
        shared = {"country": "br", "region": "mt", "latitude": -12.6, "longitude": -55.4}
        flat = daily._build_flat_locations({
            "corn_cbot": [dict(shared)],
            "soybeans_cbot": [dict(shared, region="mato_grosso")],   # same cell, different token
        })
        assert len(flat) == 1
        cache, calls = self._cache(monkeypatch, flat)
        by_coord, _p, _f = cache.get(2026, 8, 20)
        assert len(by_coord) == 1
        assert by_coord[daily._coord(shared)] == 1.0

    def test_TWO_COORDINATES_SHARING_A_REGION_TOKEN_DO_NOT_COLLIDE(self, monkeypatch):
        """The failure this design forecloses. ``_read_cog_values`` keys its return by
        ``loc["region"]``, so two DIFFERENT cells that happen to carry the same token across two
        commodities' region files would collapse into one dict entry and silently give both the same
        reading. The cache fetches under index-derived names, so the tokens cannot collide."""
        a = {"country": "us", "region": "main", "latitude": 42.0, "longitude": -93.0}
        b = {"country": "br", "region": "main", "latitude": -12.6, "longitude": -55.4}
        flat = daily._build_flat_locations({"x": [a], "y": [b]})
        assert len(flat) == 2
        cache, calls = self._cache(monkeypatch, flat)
        by_coord, _p, _f = cache.get(2026, 8, 20)
        assert by_coord[daily._coord(a)] != by_coord[daily._coord(b)]
        assert len({r for _y, _m, _d, regs in calls for r in regs}) == 2

    def test_a_FAILED_day_is_cached_as_a_failure_and_not_retried_per_commodity(self, monkeypatch):
        """The retry budget belongs to ``_read_cog_values``' tenacity wrapper. Re-opening a day that
        just failed, once per commodity, is exactly the throttling spiral the pool cap of 5 exists to
        avoid -- and T-C1's stated failure shape: the job gets slow, then starts losing days."""
        def _boom(y, m, d, locs, today=None):
            raise RuntimeError("HTTP 503")

        monkeypatch.setattr(daily, "fetch_chirps_daily_values_with_product", _boom)
        flat = daily._build_flat_locations(
            {"x": [{"country": "us", "region": "ia", "latitude": 42.0, "longitude": -93.0}]})
        cache = daily._DayRasterCache(flat)
        for _ in range(5):
            values, product, failure = cache.get(2026, 8, 20)
        assert values == {} and product == "absent" and failure == "RuntimeError"

    def test_out_of_band_coordinates_never_enter_the_union_at_all(self, monkeypatch):
        """|lat| > 50 reads as None today (``src.index`` lands outside the raster), so excluding the
        coordinate changes no row and only stops paying for a read whose answer is already known."""
        flat = daily._build_flat_locations({
            "canola_ice": [{"country": "canada", "region": "ab", "latitude": 53.9, "longitude": -116.6}],
            "cocoa": [{"country": "ghana", "region": "gh", "latitude": 6.5, "longitude": -1.6}],
        })
        assert [loc["region"] for loc in flat] == ["gh"]

    def test_an_UNREADABLE_coordinate_is_a_NULL_reading_and_not_a_dead_commodity(self, monkeypatch):
        """``_coord`` returns None rather than raising, so a malformed config entry yields the same
        None the pre-lane ``values.get(region)`` gave it -- which the all-null write gate then handles
        -- instead of taking the whole commodity-month down with a ValueError."""
        bad = {"country": "us", "region": "x", "latitude": None, "longitude": -93.0}
        assert daily._coord(bad) is None
        assert daily._build_flat_locations({"x": [bad]}) == []


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
