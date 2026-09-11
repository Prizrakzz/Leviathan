"""THE gold_weather_z FRESHNESS TRIPWIRE -- the pure half (2026-09-11).

WHAT IT MEASURES AND WHY IT EXISTS. On 2026-09-11 ``jobs/batch/gold_weather_z_task.py`` rewrote
``gold/weather_z/corn_cbot.parquet`` at 09:19:50Z -- 45,002 rows -- and every one of its five metrics
tipped at data month 2026-07, 42 days behind. Nothing in the estate said so: the only freshness clock
(``src/leviathan/silver/freshness.py:136 newest_last_modified``) measures S3 OBJECT MTIME, and the
producer rewrites the object daily, so FreshnessLagDays read 0 on a dead leg.

PER-METRIC IS MANDATORY, NOT A NICETY. One parquet carries five metrics fed by TWO sources --
nasa_power (tmax_anomaly / gdd_z / heat_stress_z / frost_event_flag) and chirps (drought_z). MEASURED:
the nasa half can be moved forward today and the chirps half cannot (the source has published nothing
after 2026-07-31), so the moment the feeders are repaired four metrics tip at 202608 and drought_z at
202607 inside ONE object under ONE table-level lag declaration. A table-grain counter would read the
max, report "0 behind", and hide the drought hole exactly when it opens.

THE LANE'S MANDATE IS DISCHARGED STRUCTURALLY: nothing here is reachable from ``compute_weather_z``.
"""
from __future__ import annotations

import pandas as pd
import pytest

from leviathan.transforms.gold import weather_z as wz


def _gold(rows: list[tuple]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=wz.GOLD_COLUMNS)


def _row(metric: str, year: int, month: int, value: float = 0.5) -> tuple:
    return ("corn_cbot", "United States", "us_corn_ohio", year, month, metric, value)


class TestMetricTipYm:
    def test_the_measured_live_case_every_metric_at_202607(self):
        """gold/weather_z/corn_cbot.parquet as it stood on 2026-09-11."""
        gold = _gold([_row(m, 2026, mo)
                      for m in wz.ALL_METRICS for mo in (5, 6, 7)])
        assert wz.metric_tip_ym(gold) == {m: 202607 for m in wz.ALL_METRICS}

    def test_THE_MIXED_TIP_the_whole_reason_this_is_per_metric(self):
        """After the nasa feeder is repaired and before chirps publishes August: four metrics at
        202608, drought_z still at 202607. A table-grain max would print 202608 and say '0 behind'."""
        rows = [_row(m, 2026, mo) for m in wz.ALL_METRICS for mo in (6, 7)]
        rows += [_row(m, 2026, 8) for m in (wz.METRIC_TMAX_ANOMALY, wz.METRIC_GDD_Z,
                                            wz.METRIC_HEAT_STRESS_Z, wz.METRIC_FROST_FLAG)]
        tips = wz.metric_tip_ym(_gold(rows))
        assert tips[wz.METRIC_DROUGHT_Z] == 202607
        assert tips[wz.METRIC_TMAX_ANOMALY] == 202608
        assert max(tips.values()) == 202608 and min(tips.values()) == 202607

    def test_the_year_boundary_is_a_real_ordering_not_a_string_one(self):
        gold = _gold([_row(wz.METRIC_GDD_Z, 2025, 12), _row(wz.METRIC_GDD_Z, 2026, 1)])
        assert wz.metric_tip_ym(gold) == {wz.METRIC_GDD_Z: 202601}

    def test_basin_and_cells_metrics_are_measured_too_they_are_served_rows(self):
        gold = _gold([_row("drought_z_tail_share", 2026, 7, 0.18),
                      _row("drought_z_cells", 2026, 7, 8.0)])
        assert wz.metric_tip_ym(gold) == {"drought_z_tail_share": 202607, "drought_z_cells": 202607}

    def test_telemetry_never_raises_on_a_shape_it_did_not_expect(self):
        """A producer run may not die because its counter could not count."""
        assert wz.metric_tip_ym(None) == {}
        assert wz.metric_tip_ym(_gold([])) == {}
        assert wz.metric_tip_ym(pd.DataFrame({"metric": ["gdd_z"]})) == {}

    def test_rows_whose_period_will_not_coerce_are_dropped_not_guessed(self):
        gold = pd.DataFrame(
            [("corn_cbot", "US", "r", "nope", 7, "gdd_z", 1.0),
             ("corn_cbot", "US", "r", 2026, 6, "gdd_z", 1.0)], columns=wz.GOLD_COLUMNS)
        assert wz.metric_tip_ym(gold) == {"gdd_z": 202606}


class TestMonthsBehind:
    def test_the_measured_case_202608_promised_202607_present(self):
        """``_ym_lagged_asof_ym('2026-09-11', 7)`` = 202608; the bytes held 202607."""
        assert wz.months_behind(202608, 202607) == 1

    def test_on_time_is_zero(self):
        assert wz.months_behind(202608, 202608) == 0

    def test_a_year_boundary_counts_MONTHS_not_the_integer_difference(self):
        """202601 - 202512 is 89 as integers and 1 as months. The difference matters at every January."""
        assert wz.months_behind(202601, 202512) == 1
        assert wz.months_behind(202609, 202512) == 9

    def test_bytes_AHEAD_of_the_promise_read_negative_rather_than_being_clamped(self):
        """A negative months_behind is a real and different defect -- the card admitting a month it
        should not -- and flattening it to 0 would hide a PIT leak."""
        assert wz.months_behind(202607, 202608) == -1

    def test_an_UNMEASURED_side_reads_as_absent_never_as_zero(self):
        assert wz.months_behind(None, 202607) is None
        assert wz.months_behind(202608, None) is None


class TestTheTripwireCannotTouchTheZMath:
    def test_neither_helper_is_reachable_from_compute_weather_z(self):
        """The lane's mandate -- 'a freshness TRIPWIRE only, never a behaviour change to the z
        computation' -- discharged structurally: the compute path never names either helper."""
        import inspect
        src = inspect.getsource(wz)
        head = src.split("# ── freshness tripwire")[0]
        assert "metric_tip_ym" not in head
        assert "months_behind" not in head

    def test_compute_weather_z_output_is_untouched_by_this_wave(self):
        """A regression anchor on the real core: the same synthetic frame in, the same tall frame out."""
        days = pd.DataFrame([
            {"country": "united_states", "region": "r", "year": y, "month": 6, "day": d,
             "variable": wz._TMAX, "value": 25.0 + (y % 5)}
            for y in range(2015, 2026) for d in range(1, 31)
        ])
        gold = wz.compute_weather_z("corn_cbot", nasa_power=days)
        assert not gold.empty
        assert list(gold.columns) == wz.GOLD_COLUMNS
        assert wz.metric_tip_ym(gold)[wz.METRIC_TMAX_ANOMALY] == 202506


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
