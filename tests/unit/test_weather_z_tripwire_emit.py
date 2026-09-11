"""THE gold_weather_z FRESHNESS TRIPWIRE -- the EMITTER half (2026-09-11, added in review).

``tests/unit/test_weather_z_metric_tip.py`` pins the pure functions (``metric_tip_ym`` /
``months_behind``). This deck pins the half that actually publishes: what reaches CloudWatch, and --
the defect this file was opened for -- WHAT STILL REACHES IT WHEN THE CARD SIDE FAILS.

THE DEFECT, MEASURED. ``_claimed_ym()`` calls ``NumbersRegistry.get('gold_weather_z')``, which RAISES
``KeyError`` on an unknown table (numbers/registry.py:403-406) rather than returning None. A table is
unknown for two ordinary operational reasons: ``GRAPHRAG_NUMBERS_DISABLE=gold_weather_z`` (the
documented single-table rollback idiom, registry.py:621 ``_disabled_tables()``), and an image without
``configs/graphrag`` baked in -- this jobdef runs on the EMBEDDER image (rev 8,
leviathan-dev-leviathan-embedder@sha256:78264c51bc2a). Under the original SINGLE try that KeyError left
put_metric_data calls = 0 and datums = 0: the whole tripwire silenced, INCLUDING ``WeatherZTipYm``,
which does not depend on the card at all. The card read now sits in its own try, so a card-side fault
costs the DENOMINATOR and nothing else.
"""
from __future__ import annotations

import types

import pandas as pd
import pytest
from leviathan.transforms.gold import weather_z as wz

from jobs.batch import gold_weather_z_task as task


def _gold(rows: list[tuple]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=wz.GOLD_COLUMNS)


def _row(metric: str, year: int, month: int, value: float = 0.5) -> tuple:
    return ("corn_cbot", "United States", "us_corn_ohio", year, month, metric, value)


_LIVE = _gold([_row(m, 2026, 7) for m in wz.ALL_METRICS])


class _CW:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list]] = []

    def put_metric_data(self, Namespace, MetricData):   # noqa: N803 -- the boto3 kwarg names
        self.calls.append((Namespace, MetricData))


@pytest.fixture
def cw(monkeypatch):
    client = _CW()
    monkeypatch.setitem(__import__("sys").modules, "boto3",
                        types.SimpleNamespace(client=lambda name: client))
    return client


def _datums(client: _CW) -> list:
    return [d for _, data in client.calls for d in data]


def _named(client: _CW, name: str) -> list:
    return [d for d in _datums(client) if d["MetricName"] == name]


class TestACardSideFailureCannotSilenceTheTip:
    def test_a_KeyError_from_the_card_still_publishes_every_TIP_datum(self, cw, monkeypatch):
        """THE REGRESSION. Five metrics in, five WeatherZTipYm datums out, zero months_behind."""
        def _boom(_metric=""):
            raise KeyError("unknown table 'gold_weather_z'")
        monkeypatch.setattr(task, "_claimed_ym", _boom)

        task._emit_freshness_tripwire("corn_cbot", _LIVE)

        assert len(cw.calls) == 1, "the card fault must not cost the put_metric_data call"
        tips = _named(cw, task._TIP_YM_METRIC)
        assert len(tips) == len(wz.ALL_METRICS)
        assert {d["Value"] for d in tips} == {202607.0}
        assert _named(cw, task._TIP_BEHIND_METRIC) == [], \
            "no denominator -> months_behind ABSENT, never zero"

    def test_an_ImportError_from_the_card_is_the_same_story(self, cw, monkeypatch):
        """The unbaked-configs posture: the graphrag import itself fails, not just the lookup."""
        def _boom(_metric=""):
            raise ModuleNotFoundError("No module named 'leviathan.graphrag.numbers'")
        monkeypatch.setattr(task, "_claimed_ym", _boom)

        task._emit_freshness_tripwire("corn_cbot", _LIVE)
        assert len(_named(cw, task._TIP_YM_METRIC)) == len(wz.ALL_METRICS)

    def test_a_card_that_DECLARES_NO_LAG_behaves_the_same_way(self, cw, monkeypatch):
        """``None`` is the card's own "I make no promise" -- reported as absence, not as zero behind."""
        monkeypatch.setattr(task, "_claimed_ym", lambda _metric="": None)
        task._emit_freshness_tripwire("corn_cbot", _LIVE)
        assert len(_named(cw, task._TIP_YM_METRIC)) == len(wz.ALL_METRICS)
        assert _named(cw, task._TIP_BEHIND_METRIC) == []


class TestTheHealthyPath:
    def test_both_metrics_ride_one_call_dimensioned_per_metric(self, cw, monkeypatch):
        monkeypatch.setattr(task, "_claimed_ym", lambda _metric="": 202608)
        task._emit_freshness_tripwire("corn_cbot", _LIVE)

        ns, _ = cw.calls[0]
        assert ns == task._TIP_METRIC_NAMESPACE
        behind = _named(cw, task._TIP_BEHIND_METRIC)
        assert len(behind) == len(wz.ALL_METRICS)
        assert {d["Value"] for d in behind} == {1.0}, "202608 promised, 202607 present"
        for d in _datums(cw):
            assert {dim["Name"] for dim in d["Dimensions"]} == {"Commodity", "Metric"}

    def test_the_MIXED_tip_survives_the_emitter_which_is_the_whole_point(self, cw, monkeypatch):
        """Four metrics moved to 202608, drought_z still 202607: two DIFFERENT behind values in one
        call. A table-grain counter would take the max and print '0 behind'."""
        monkeypatch.setattr(task, "_claimed_ym", lambda _metric="": 202608)
        rows = [_row(m, 2026, 8) for m in wz.ALL_METRICS if m != wz.METRIC_DROUGHT_Z]
        rows.append(_row(wz.METRIC_DROUGHT_Z, 2026, 7))
        task._emit_freshness_tripwire("corn_cbot", _gold(rows))

        by_metric = {next(dim["Value"] for dim in d["Dimensions"] if dim["Name"] == "Metric"): d["Value"]
                     for d in _named(cw, task._TIP_BEHIND_METRIC)}
        assert by_metric[wz.METRIC_DROUGHT_Z] == 1.0
        assert by_metric[wz.METRIC_TMAX_ANOMALY] == 0.0


class TestTheDenominatorIsPerMetricToo:
    """2026-09-11: the NUMERATOR was already per metric; the DENOMINATOR was one blanket number.

    That asymmetry is what made the tripwire's own headline wrong. With one claimed month for five
    metrics, the emitter published "1 month behind" for all of them on the live 2026-09-11 frame --
    right about the four NASA metrics (a real raw->bronze freeze) and wrong about ``drought_z``, which
    at its own CHIRPS block lag is EXACTLY ON its promise that day: the August block has not published
    and drought_z does not owe it yet. Both halves of the counter now read the same per-metric rule,
    ``registry.lag_days_for``.

    THE CHIRPS LAG MOVED 45 -> 25 (2026-09-11, verify pass, same day) and this deck moved with it. The
    45 was a MISREADING of the two HTTP-HEAD observations that produced it: July PRESENT at day 22 past
    month-end is an UPPER bound (lag <= 22) and August ABSENT at day 11 is a LOWER one (lag > 11), so
    the final product's lag is 11 < lag <= 22 and the card declares 22 plus a 3-day margin. What that
    changes HERE, measured: at the pinned 2026-09-11 clock ``drought_z`` claims 202607 rather than
    202606, so against the live 202607 frame it reads 0 months behind rather than -1. The SPLIT the
    class is about is unchanged -- one metric clear, four behind -- and pinning the value the shipped
    declaration actually produces is what keeps the deck grading the card rather than its own memory.
    """

    @staticmethod
    def _pinned(metric: str = "") -> int:
        """``_claimed_ym`` with its ONLY calendar-dependent part frozen at the wave's own wall clock.

        Everything else is the shipped code path -- the real registry, the real card, the real
        ``lag_days_for`` precedence -- because the claim under test is what the DECLARATION says, and a
        hand-written denominator would grade this deck's opinion of it. ``_claimed_ym`` reads
        ``datetime.now(timezone.utc)`` inside its own body, so pinning the date means standing in for
        the function rather than patching a clock it does not expose."""
        from leviathan.graphrag.numbers.query import _ym_lagged_asof_ym
        from leviathan.graphrag.numbers.registry import lag_days_for, load_registry
        return _ym_lagged_asof_ym("2026-09-11",
                                  lag_days_for(load_registry().get("gold_weather_z"), metric))

    def test_the_card_answers_a_DIFFERENT_month_for_the_two_sources(self):
        assert self._pinned("drought_z") == 202607          # CHIRPS block, 25 d
        assert self._pinned("tmax_anomaly") == 202608       # NASA daily, 5 d
        assert self._pinned("") == 202608, "no metric named -> the card default"
        assert self._pinned("drought_z_tail_share") == 202607, "a derived sibling keeps the stem's"

    def test_the_accessor_really_is_wired_to_the_metric_on_TODAYS_clock_too(self):
        """The pinned helper above proves the ARITHMETIC; this proves the SHIPPED function reads its
        argument at all, on whatever day the deck runs, without pinning a calendar."""
        from datetime import datetime, timezone

        from leviathan.graphrag.numbers.query import _ym_lagged_asof_ym
        today = datetime.now(timezone.utc).date().isoformat()
        assert task._claimed_ym("drought_z") == _ym_lagged_asof_ym(today, 25)
        assert task._claimed_ym("tmax_anomaly") == _ym_lagged_asof_ym(today, 5)

    def test_the_MEASURED_live_frame_splits_the_two_sources_instead_of_blaming_both(self, cw,
                                                                                   monkeypatch):
        """``_LIVE`` is every metric at 202607 -- the tip measured off gold/weather_z/corn_cbot.parquet
        on 2026-09-11. The four NASA metrics are one month behind; drought_z is exactly ON its own
        promise (its 25-day CHIRPS lag admits 202607, and 202607 is what the bytes hold), which is the
        verdict the blanket denominator could not reach and the misread 45 overshot in the other
        direction."""
        monkeypatch.setattr(task, "_claimed_ym", self._pinned)
        task._emit_freshness_tripwire("corn_cbot", _LIVE)
        by_metric = {next(dim["Value"] for dim in d["Dimensions"] if dim["Name"] == "Metric"): d["Value"]
                     for d in _named(cw, task._TIP_BEHIND_METRIC)}
        assert by_metric[wz.METRIC_DROUGHT_Z] == 0.0
        for nasa in (wz.METRIC_TMAX_ANOMALY, wz.METRIC_GDD_Z, wz.METRIC_HEAT_STRESS_Z,
                     wz.METRIC_FROST_FLAG):
            assert by_metric[nasa] == 1.0, nasa
        assert len(set(by_metric.values())) == 2, \
            "one blanket denominator would have made every one of these the same number"


class TestItCanNeverChangeTheProducersVerdict:
    def test_an_EMPTY_frame_emits_nothing_and_does_not_raise(self, cw, monkeypatch):
        monkeypatch.setattr(task, "_claimed_ym", lambda _metric="": 202608)
        task._emit_freshness_tripwire("corn_cbot", _gold([]))
        assert cw.calls == []

    def test_a_dead_CloudWatch_is_swallowed(self, monkeypatch):
        class _Dead:
            def put_metric_data(self, **kw):
                raise RuntimeError("cloudwatch is down")
        monkeypatch.setitem(__import__("sys").modules, "boto3",
                            types.SimpleNamespace(client=lambda name: _Dead()))
        monkeypatch.setattr(task, "_claimed_ym", lambda _metric="": 202608)
        task._emit_freshness_tripwire("corn_cbot", _LIVE)   # must not raise

    def test_BOTH_halves_failing_at_once_is_still_only_a_log_line(self, monkeypatch):
        class _Dead:
            def put_metric_data(self, **kw):
                raise RuntimeError("cloudwatch is down")

        def _boom(_metric=""):
            raise KeyError("unknown table 'gold_weather_z'")
        monkeypatch.setitem(__import__("sys").modules, "boto3",
                            types.SimpleNamespace(client=lambda name: _Dead()))
        monkeypatch.setattr(task, "_claimed_ym", _boom)
        task._emit_freshness_tripwire("corn_cbot", _LIVE)   # must not raise


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
