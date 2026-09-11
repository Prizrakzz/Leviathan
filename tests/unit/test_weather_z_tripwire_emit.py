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
        def _boom():
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
        def _boom():
            raise ModuleNotFoundError("No module named 'leviathan.graphrag.numbers'")
        monkeypatch.setattr(task, "_claimed_ym", _boom)

        task._emit_freshness_tripwire("corn_cbot", _LIVE)
        assert len(_named(cw, task._TIP_YM_METRIC)) == len(wz.ALL_METRICS)

    def test_a_card_that_DECLARES_NO_LAG_behaves_the_same_way(self, cw, monkeypatch):
        """``None`` is the card's own "I make no promise" -- reported as absence, not as zero behind."""
        monkeypatch.setattr(task, "_claimed_ym", lambda: None)
        task._emit_freshness_tripwire("corn_cbot", _LIVE)
        assert len(_named(cw, task._TIP_YM_METRIC)) == len(wz.ALL_METRICS)
        assert _named(cw, task._TIP_BEHIND_METRIC) == []


class TestTheHealthyPath:
    def test_both_metrics_ride_one_call_dimensioned_per_metric(self, cw, monkeypatch):
        monkeypatch.setattr(task, "_claimed_ym", lambda: 202608)
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
        monkeypatch.setattr(task, "_claimed_ym", lambda: 202608)
        rows = [_row(m, 2026, 8) for m in wz.ALL_METRICS if m != wz.METRIC_DROUGHT_Z]
        rows.append(_row(wz.METRIC_DROUGHT_Z, 2026, 7))
        task._emit_freshness_tripwire("corn_cbot", _gold(rows))

        by_metric = {next(dim["Value"] for dim in d["Dimensions"] if dim["Name"] == "Metric"): d["Value"]
                     for d in _named(cw, task._TIP_BEHIND_METRIC)}
        assert by_metric[wz.METRIC_DROUGHT_Z] == 1.0
        assert by_metric[wz.METRIC_TMAX_ANOMALY] == 0.0


class TestItCanNeverChangeTheProducersVerdict:
    def test_an_EMPTY_frame_emits_nothing_and_does_not_raise(self, cw, monkeypatch):
        monkeypatch.setattr(task, "_claimed_ym", lambda: 202608)
        task._emit_freshness_tripwire("corn_cbot", _gold([]))
        assert cw.calls == []

    def test_a_dead_CloudWatch_is_swallowed(self, monkeypatch):
        class _Dead:
            def put_metric_data(self, **kw):
                raise RuntimeError("cloudwatch is down")
        monkeypatch.setitem(__import__("sys").modules, "boto3",
                            types.SimpleNamespace(client=lambda name: _Dead()))
        monkeypatch.setattr(task, "_claimed_ym", lambda: 202608)
        task._emit_freshness_tripwire("corn_cbot", _LIVE)   # must not raise

    def test_BOTH_halves_failing_at_once_is_still_only_a_log_line(self, monkeypatch):
        class _Dead:
            def put_metric_data(self, **kw):
                raise RuntimeError("cloudwatch is down")

        def _boom():
            raise KeyError("unknown table 'gold_weather_z'")
        monkeypatch.setitem(__import__("sys").modules, "boto3",
                            types.SimpleNamespace(client=lambda name: _Dead()))
        monkeypatch.setattr(task, "_claimed_ym", _boom)
        task._emit_freshness_tripwire("corn_cbot", _LIVE)   # must not raise


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
