"""G4c: futures z-scores are auditable -- a declared window, a rendered window+series, and the
two pre-existing fences that already restrict z to a per-delivery-month series, PINNED so a
future edit cannot remove them silently."""
from __future__ import annotations

import yaml

from leviathan.graphrag import citations as C
from leviathan.graphrag.numbers import agent as A
from leviathan.graphrag.numbers import query as Q


class TestTheRestrictionAlreadyHolds:
    def test_zscore_is_a_time_axis_stat_so_an_interleaved_read_declines(self):
        assert "zscore" in A._TIME_AXIS_STATS

    def test_a_multi_expiry_multi_session_read_is_curve_as_calendar(self):
        assert Q.curve_as_calendar({"n_expiries": 13, "n_sessions": 22}) is True

    def test_a_single_expiry_calendar_read_computes(self):
        assert Q.curve_as_calendar({"n_expiries": 1, "n_sessions": 250}) is False

    def test_a_single_session_curve_read_computes(self):
        assert Q.curve_as_calendar({"n_expiries": 13, "n_sessions": 1}) is False

    def test_the_continuous_card_cannot_produce_a_series(self):
        with open("configs/graphrag/numbers/tables.yaml", encoding="utf-8") as fh:
            cards = yaml.safe_load(fh)
        spec = cards["tables"]["silver_futures_prices"]
        assert spec.get("levels_only") is True
        assert cards["tables"]["silver_futures_eod"].get("levels_only") is not True


class TestDeclaredWindow:
    def test_the_declared_window_is_250_sessions(self):
        from leviathan.graphrag import params as P
        assert int(P.get("serving.stats.futures_z.window_sessions", 0)) == 250

    def test_callers_may_narrow(self):
        assert A._z_window(60, "silver_futures_eod") == 60

    def test_callers_may_not_silently_widen(self):
        assert A._z_window(5000, "silver_futures_eod") == 250

    def test_an_omitted_window_gets_the_declared_one(self):
        assert A._z_window(None, "silver_futures_eod") == 250

    def test_non_futures_series_are_untouched(self):
        assert A._z_window(None, "silver_wasde") is None
        assert A._z_window(37, "silver_wasde") == 37

    def test_the_default_never_exceeds_history(self):
        """Review FATAL (wf_6906ea5b): stats.zscore treats a non-None window as REQUIRED depth,
        so a bare 250 default would flip every shorter-than-250 handle from computing to
        declining. The default arm clamps to the series length instead."""
        assert A._z_window(None, "silver_futures_eod", 120) == 120
        assert A._z_window(None, "silver_futures_eod", 766) == 250

    def test_the_short_history_default_computes_through_stats(self):
        """End-to-end through ST.zscore: the exact measured regression from the review --
        120 points, no requested window -- must COMPUTE with the honest effective window."""
        from leviathan.graphrag.numbers import stats as ST
        hist = [float(i % 17) for i in range(120)]
        res = ST.zscore(9.0, hist, window=A._z_window(None, "silver_futures_eod", len(hist)))
        assert not res.get("declined"), res
        assert res.get("window") == 120

    def test_an_explicit_over_depth_ask_still_declines(self):
        """The paired negative: an EXPLICIT window beyond history keeps stats' own
        require-this-depth contract -- asking for a 200-point rank over 120 points is
        honestly refused, exactly as before G4c."""
        from leviathan.graphrag.numbers import stats as ST
        hist = [float(i % 17) for i in range(120)]
        res = ST.zscore(9.0, hist, window=A._z_window(200, "silver_futures_eod", len(hist)))
        assert res.get("declined"), res


class TestZRowRender:
    def _row(self, **extra):
        return {"query": {"table": "compute_stat", "metric": "zscore"},
                "rows": [{"value": 2.1, "unit": "sigma", **extra}], "status": "ok"}

    def test_window_and_series_reach_the_sources_line(self):
        cit = C.from_number(self._row(z_window=250, z_series="silver_futures_eod.settle"), 1)
        assert "vs 250 points of silver_futures_eod.settle" in cit.label

    def test_a_partial_pair_renders_nothing_new(self):
        assert "vs " not in C.from_number(self._row(z_window=250), 1).label
        assert "points of" not in C.from_number(self._row(z_series="silver_wasde.x"), 1).label

    def test_a_row_with_neither_is_byte_identical(self):
        assert C.from_number(self._row(), 1).label == C.from_number(self._row(), 1).label
        assert "vs " not in C.from_number(self._row(), 1).label
