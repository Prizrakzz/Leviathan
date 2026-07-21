"""W3.5 deterministic stats tool belt -- arithmetic pins, honest declines, purity, enum surface.

Every headline number is HAND-COMPUTED in the assertion so a silent formula change is caught. The
declines pin the documented minimum-n contract (a percentile over 3 points MUST refuse). The enum
tests freeze the tool-schema surface and the descriptive-only fence.
"""
from __future__ import annotations

import re

import pytest

from leviathan.graphrag.numbers import stats as S


# ---------------------------------------------------------------------------------------------------
# streak
# ---------------------------------------------------------------------------------------------------
def test_streak_up_counts_trailing_run():
    r = S.streak([1, 2, 3, 4], "up")
    assert r == {"stat": "streak", "declined": False, "value": 3, "n": 4,
                 "direction": "up", "latest": 4.0}


def test_streak_down_ignores_earlier_up():
    # last two moves are down (5->4, 4->2); the 2->5 rise is before the run -> down-streak = 2
    r = S.streak([2, 5, 4, 2], "down")
    assert r["value"] == 2 and r["latest"] == 2.0


def test_streak_flat_breaks_run():
    r = S.streak([1, 2, 3, 3], "up")   # last move is flat -> run 0
    assert r["value"] == 0


def test_streak_opposite_direction_is_zero():
    assert S.streak([4, 3, 2, 1], "up")["value"] == 0


def test_streak_short_series_declines():
    r = S.streak([5], "up")
    assert r["declined"] is True and r["value"] is None and r["n"] == 1


def test_streak_bad_direction_raises():
    with pytest.raises(ValueError):
        S.streak([1, 2, 3], "sideways")


# ---------------------------------------------------------------------------------------------------
# percentile
# ---------------------------------------------------------------------------------------------------
def test_percentile_midrank_pin():
    hist = [10, 20, 30, 40, 50, 60, 70, 80]         # n=8
    # value 45: 4 below (10,20,30,40), 0 equal -> 100*4/8 = 50.0
    assert S.percentile(45, hist)["value"] == 50.0


def test_percentile_handles_ties_midrank():
    hist = [10, 20, 30, 40, 50, 60, 70, 80]
    # value 30: 2 below (10,20), 1 equal (30) -> 100*(2 + 0.5)/8 = 31.25
    assert S.percentile(30, hist)["value"] == 31.25


def test_percentile_order_independent():
    hist = [80, 10, 50, 30, 70, 20, 60, 40]
    assert S.percentile(45, hist)["value"] == 50.0


def test_percentile_three_points_refuses():
    r = S.percentile(2, [1, 2, 3])
    assert r["declined"] is True and r["value"] is None and r["n"] == 3


def test_percentile_min_n_is_eight():
    assert S.MIN_PERCENTILE_N == 8
    assert S.percentile(4, [1, 2, 3, 4, 5, 6, 7])["declined"] is True    # 7 refuses
    assert S.percentile(4, [1, 2, 3, 4, 5, 6, 7, 8])["declined"] is False  # 8 computes


# ---------------------------------------------------------------------------------------------------
# zscore
# ---------------------------------------------------------------------------------------------------
def test_zscore_population_pin():
    hist = [0, 0, 0, 0, 10, 10, 10, 10]             # mean 5, popvar 25, std 5
    r = S.zscore(10, hist)
    assert r["mean"] == 5.0 and r["std"] == 5.0 and r["value"] == 1.0
    assert S.zscore(0, hist)["value"] == -1.0
    assert S.zscore(5, hist)["value"] == 0.0


def test_zscore_window_takes_last_points():
    hist = [999, 999, 0, 0, 0, 0, 10, 10, 10, 10]   # first two ignored by window=8
    r = S.zscore(10, hist, window=8)
    assert r["window"] == 8 and r["value"] == 1.0


def test_zscore_zero_variance_declines():
    r = S.zscore(4, [4, 4, 4, 4, 4, 4, 4, 4])
    assert r["declined"] is True and "variance" in r["reason"]


def test_zscore_short_history_declines():
    r = S.zscore(4, [1, 2, 3, 4, 5, 6, 7])          # 7 < MIN_ZSCORE_N
    assert r["declined"] is True and r["value"] is None


def test_zscore_window_below_min_declines():
    r = S.zscore(4, list(range(20)), window=4)
    assert r["declined"] is True


def test_zscore_window_larger_than_history_declines():
    r = S.zscore(4, [1, 2, 3, 4, 5, 6, 7, 8, 9], window=12)
    assert r["declined"] is True and r["value"] is None


# ---------------------------------------------------------------------------------------------------
# window_change
# ---------------------------------------------------------------------------------------------------
def test_window_change_pin():
    r = S.window_change([100, 110, 120], 0, 2)
    assert r["value"] == 20.0 and r["pct_change"] == 20.0
    assert r["start_val"] == 100.0 and r["end_val"] == 120.0


def test_window_change_negative_indices():
    r = S.window_change([100, 110, 120], -3, -1)
    assert r["value"] == 20.0


def test_window_change_zero_start_pct_none():
    r = S.window_change([0, 5], 0, 1)
    assert r["value"] == 5.0 and r["pct_change"] is None


def test_window_change_out_of_range_declines():
    r = S.window_change([1, 2, 3], 0, 9)
    assert r["declined"] is True and r["value"] is None


def test_window_change_empty_declines():
    assert S.window_change([], 0, 1)["declined"] is True


# ---------------------------------------------------------------------------------------------------
# revision_count
# ---------------------------------------------------------------------------------------------------
def test_revision_count_three_upward():
    r = S.revision_count([100, 102, 105, 108], "up")
    assert r["value"] == 3 and r["latest"] == 108.0


def test_revision_count_run_breaks_on_reversal():
    r = S.revision_count([100, 105, 103], "up")     # last move down -> up-run 0
    assert r["value"] == 0


def test_revision_count_single_vintage_declines():
    r = S.revision_count([100], "up")
    assert r["declined"] is True and r["n"] == 1


# ---------------------------------------------------------------------------------------------------
# extrema
# ---------------------------------------------------------------------------------------------------
def test_extrema_pin_first_occurrence_indices():
    r = S.extrema([3, 1, 4, 1, 5])
    assert r["min"] == 1.0 and r["max"] == 5.0
    assert r["argmin"] == 1 and r["argmax"] == 4     # first-occurrence min at index 1


def test_extrema_order_independent_values():
    assert S.extrema([5, 4, 3, 2, 1])["min"] == 1.0
    assert S.extrema([5, 4, 3, 2, 1])["max"] == 5.0


def test_extrema_single_point():
    r = S.extrema([7])
    assert r["min"] == 7.0 and r["max"] == 7.0 and r["declined"] is False


def test_extrema_empty_declines():
    r = S.extrema([])
    assert r["declined"] is True and r["min"] is None and r["max"] is None


# ---------------------------------------------------------------------------------------------------
# yoy_delta
# ---------------------------------------------------------------------------------------------------
def test_yoy_delta_annual_pin():
    r = S.yoy_delta([100, 120])
    assert r["value"] == 20.0 and r["pct_change"] == 20.0
    assert r["latest"] == 120.0 and r["prior"] == 100.0


def test_yoy_delta_monthly_periods_12():
    series = [10] + [0] * 11 + [15]                  # 13 points; point 12 back is 10
    r = S.yoy_delta(series, periods=12)
    assert r["prior"] == 10.0 and r["latest"] == 15.0 and r["value"] == 5.0


def test_yoy_delta_insufficient_for_periods_declines():
    r = S.yoy_delta([1, 2, 3], periods=12)           # need 13 points
    assert r["declined"] is True and r["value"] is None


def test_yoy_delta_zero_prior_pct_none():
    r = S.yoy_delta([0, 9])
    assert r["value"] == 9.0 and r["pct_change"] is None


def test_yoy_delta_bad_periods_declines():
    assert S.yoy_delta([1, 2, 3], periods=0)["declined"] is True


# ---------------------------------------------------------------------------------------------------
# input hygiene (shared _floats contract)
# ---------------------------------------------------------------------------------------------------
def test_none_cell_raises_typeerror():
    with pytest.raises(TypeError):
        S.streak([1, None, 3], "up")


def test_nonnumeric_cell_raises_typeerror():
    with pytest.raises(TypeError):
        S.percentile(1, [1, 2, "x", 4, 5, 6, 7, 8])


def test_bool_cell_rejected():
    with pytest.raises(TypeError):
        S.extrema([True, 1, 2])


def test_numeric_strings_are_coerced():
    # Athena-shaped stringified cells still parse (integrator normally converts, but be forgiving)
    r = S.window_change(["100", "120"], 0, 1)
    assert r["value"] == 20.0


# ---------------------------------------------------------------------------------------------------
# purity: no mutation, determinism
# ---------------------------------------------------------------------------------------------------
def test_inputs_not_mutated():
    series = [3, 1, 2]
    hist = [1, 2, 3, 4, 5, 6, 7, 8]
    S.streak(series, "up")
    S.extrema(series)
    S.percentile(4, hist)
    assert series == [3, 1, 2]
    assert hist == [1, 2, 3, 4, 5, 6, 7, 8]


def test_deterministic_repeated_calls():
    args = ([0, 0, 0, 0, 10, 10, 10, 10],)
    assert S.zscore(10, *args) == S.zscore(10, *args)


def test_module_has_no_io_imports():
    # structural purity guarantee: the module must not reach past its arguments.
    src = _read_stats_source()
    for banned in ("import os", "import boto3", "import requests", "open(", "import socket",
                   "from leviathan.graphrag import pgstore", "urllib", "datetime.now", "time.time"):
        assert banned not in src, f"stats.py must be pure; found {banned!r}"


# ---------------------------------------------------------------------------------------------------
# enum surface + descriptive-only fence
# ---------------------------------------------------------------------------------------------------
def test_registry_names_frozen():
    assert set(S.STAT_REGISTRY) == {
        "streak", "percentile", "zscore", "window_change",
        "revision_count", "extrema", "yoy_delta",
    }
    assert S.STAT_NAMES == frozenset(S.STAT_REGISTRY)


def test_registry_maps_to_module_callables():
    for name, fn in S.STAT_REGISTRY.items():
        assert callable(fn)
        assert getattr(S, name) is fn


def test_banned_pattern_flags_forward_looking_names():
    for bad in ("fit_line", "price_trend", "forecast", "projected_stocks",
                "extrapolate", "predict_yield", "TREND", "linfit"):
        assert S.is_banned_name(bad) is True


def test_banned_pattern_allows_descriptive_names():
    for ok in S.STAT_REGISTRY:
        assert S.is_banned_name(ok) is False


def test_no_registered_name_is_banned():
    assert not any(S.is_banned_name(n) for n in S.STAT_REGISTRY)


def test_banned_pattern_source_terms():
    for term in ("fit", "trend", "forecast", "project", "extrapolat", "predict"):
        assert re.search(term, S.BANNED_PATTERN.pattern)


# ---------------------------------------------------------------------------------------------------
def _read_stats_source() -> str:
    import inspect
    return inspect.getsource(S)


# ===================================================================================================
# compute_stat AGENT-LOOP integration (W3.5): the tool is enum-locked, handles are turn-scoped, the
# result is an injected [N] row the all-numbers guard value-checks, and the kill-switch removes it.
# Mocked LLM (FakeClient) + injected rows; no spend, no AWS, no model calls.
# ===================================================================================================
import types  # noqa: E402
import json as _json  # noqa: E402

from leviathan.graphrag.numbers import agent as _A  # noqa: E402
from leviathan.graphrag import orchestrator as _O  # noqa: E402


def _tu(name, inp, tid="t"):
    return types.SimpleNamespace(type="tool_use", name=name, input=inp, id=tid)


def _txt(t):
    return types.SimpleNamespace(type="text", text=t)


def _rp(content):
    return types.SimpleNamespace(content=content, stop_reason="x")


class _Msgs:
    def __init__(self, outer):
        self.outer = outer

    def create(self, **kw):
        self.outer.sent.append(kw)
        return self.outer.queue.pop(0)


class _FakeClient:
    def __init__(self, queue):
        self.queue = list(queue)
        self.sent = []
        self.messages = _Msgs(self)


def _series_rows(vals, unit="USD/mt", kd="2024-06-01"):
    return [{"value": str(v), "knowledge_date": kd, "unit": unit} for v in vals]


def test_compute_stat_row_cites_and_value_checks():
    """A lookup mints handle L1; compute_stat percentile scores its last point (80 in [10..80] midrank =
    93.75); the result is injected as a compute_stat [N] call carrying provenance, and stating that exact
    value value-checks clean (mismatched == 0)."""
    rows = _series_rows([10, 20, 30, 40, 50, 60, 70, 80])
    client = _FakeClient([
        _rp([_tu(_A.TOOL_NAME, {"table": "silver_pink_sheet", "metric": "palm_oil_cpo_usd_t",
                                "agg": "series"}, "t1")]),
        _rp([_tu(_A.STATS_TOOL_NAME, {"stat": "percentile", "series_handle": "L1"}, "t2")]),
        _rp([_txt("Palm sits in the 93.75th percentile of its own history [N].")]),
    ])
    out = _A.answer_numbers("palm percentile?", asof="2024-07-01", client=client,
                            query_fn=lambda sql: rows)
    stat_calls = [c for c in out["calls"] if (c.get("query") or {}).get("table") == _A.STATS_TOOL_NAME]
    assert len(stat_calls) == 1
    sc = stat_calls[0]
    assert sc["rows"][0]["value"] == 93.75 and sc["rows"][0]["unit"] == "percentile"
    assert sc["stat_provenance"] == {"stat": "percentile", "params": {}, "input_handles": ["L1"]}
    # the lookup minted the turn-scoped handle L1 that the stat referenced.
    lk = next(c for c in out["calls"] if (c.get("query") or {}).get("table") == "silver_pink_sheet")
    assert lk["handle"] == "L1"
    # all-numbers guard: the STATED 93.75 matches the injected row -> nothing mismatched.
    nv = _O._verify_numbers_answer(out["answer"], out["calls"])
    assert nv["mismatched"] == 0, nv


def test_uncited_stat_shaped_number_still_strips():
    """If the model narrates a stat-shaped magnitude the tool did NOT produce (states 100.0 while the
    computed percentile is 93.75), the all-numbers guard flags it -- run_numbers_only prepends the caution
    banner (the fabrication is caught, never served clean)."""
    rows = _series_rows([10, 20, 30, 40, 50, 60, 70, 80])
    seq = [
        _rp([_tu(_A.TOOL_NAME, {"table": "silver_pink_sheet", "metric": "palm_oil_cpo_usd_t",
                                "agg": "series"}, "t1")]),
        _rp([_tu(_A.STATS_TOOL_NAME, {"stat": "percentile", "series_handle": "L1"}, "t2")]),
        _rp([_txt("Palm is at the 100th percentile of its history.")]),
    ]
    out = _A.answer_numbers("palm percentile?", asof="2024-07-01", client=_FakeClient(seq),
                            query_fn=lambda sql: rows)
    nv = _O._verify_numbers_answer(out["answer"], out["calls"])
    assert nv["mismatched"] >= 1 and 100.0 in nv["mismatch_values"]
    res = _O.run_numbers_only("palm percentile?", asof="2024-07-01",
                              client=_FakeClient(seq), query_fn=lambda sql: rows)
    assert "does not match any looked-up row" in res["answer"]     # the deterministic caution banner


def test_cross_turn_handle_is_refused():
    """Handles are TURN-SCOPED: a compute_stat referencing a handle never minted this turn (a cross-turn /
    stale id) is REFUSED -- no value row is injected, and the model is told the handle is unknown."""
    rows = _series_rows([10, 20, 30, 40, 50, 60, 70, 80])
    client = _FakeClient([
        _rp([_tu(_A.TOOL_NAME, {"table": "silver_pink_sheet", "metric": "palm_oil_cpo_usd_t",
                                "agg": "series"}, "t1")]),
        _rp([_tu(_A.STATS_TOOL_NAME, {"stat": "percentile", "series_handle": "L9"}, "t2")]),  # never minted
        _rp([_txt("I could not compute that.")]),
    ])
    out = _A.answer_numbers("palm percentile?", asof="2024-07-01", client=client,
                            query_fn=lambda sql: rows)
    # only the lookup call landed -- the refused stat injected NO [N] row.
    assert [((c.get("query") or {}).get("table")) for c in out["calls"]] == ["silver_pink_sheet"]
    refusal = _json.loads(client.sent[2]["messages"][-1]["content"][0]["content"])
    assert refusal["status"] == "error" and "turn-scoped" in refusal["error"] and "L9" in refusal["error"]


def test_kill_switch_removes_tool_and_prompt_bullet(monkeypatch):
    """GRAPHRAG_STATS_TOOL=off removes compute_stat from the schema AND the stats bullet from the prompt;
    a stat tool_use then resolves to an unknown-tool error (no injection). On (default) it is present."""
    reg = _A.load_registry()
    monkeypatch.setenv("GRAPHRAG_STATS_TOOL", "off")
    assert _A._stats_tool_on() is False
    sp_off = _A.system_prompt(reg)
    assert _A.STATS_TOOL_NAME not in sp_off and "compute_stat tool" not in sp_off
    client = _FakeClient([
        _rp([_tu(_A.STATS_TOOL_NAME, {"stat": "percentile", "series_handle": "L1"}, "t1")]),
        _rp([_txt("no stats available")]),
    ])
    out = _A.answer_numbers("q", asof="2024-07-01", client=client, query_fn=lambda sql: [])
    assert out["calls"] == []                                       # tool disabled -> nothing executed/injected
    err = _json.loads(client.sent[0]["messages"][-1]["content"][0]["content"])
    assert err["status"] == "error" and "unknown tool" in err["error"]
    # and the schema built for the loop carried only lookup_number.
    sent_tools = {t["name"] for t in client.sent[0]["tools"]}
    assert sent_tools == {_A.TOOL_NAME}
    monkeypatch.setenv("GRAPHRAG_STATS_TOOL", "on")
    assert _A._stats_tool_on() is True
    assert _A.STATS_TOOL_NAME in {t["name"] for t in [_A.tool_schema(reg), _A.stats_tool_schema()]}
    assert "compute_stat tool" in _A.system_prompt(reg)


def test_config_check_stats_enum_ban_is_green_and_non_vacuous():
    """config_check.check_stats_registry imports STAT_REGISTRY and FAILS on any forward-looking name; green
    on the shipped registry, and it actually inspects >=1 name (non-vacuous)."""
    from leviathan.graphrag import config_check as CC
    assert CC.check_stats_registry() == []
    assert len(S.STAT_REGISTRY) >= 1
    # negative: a smuggled projection name is caught (restore afterwards).
    S.STAT_REGISTRY["price_forecast"] = S.percentile
    try:
        errs = CC.check_stats_registry()
        assert any("price_forecast" in e for e in errs)
    finally:
        del S.STAT_REGISTRY["price_forecast"]
    assert CC.check_stats_registry() == []
