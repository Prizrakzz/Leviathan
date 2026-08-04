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


# ===================================================================================================
# U1 -- THE UNIT-COMPATIBILITY GUARD (FUTURES_READPATH wave; D-FR-4/5/6/7/8/16/17 + U3's trace key).
#
# THE DEFECT. `percentile`/`zscore` take the VALUE from one handle and the HISTORY from another and
# never compared their units. hard_red_spring_wheat_mgex settles in USD/bushel (~7.02) while every CBOT
# /KCBT wheat settles in US cents/bushel (~430) -- source-faithful, NEVER converted (tables.yaml:938-940)
# -- so ranking one inside the other's history minted a cited [N] percentile off by a factor of 100, at
# the 0th percentile, silently: _STAT_UNIT overwrites the OUTPUT unit to "percentile" before any renderer
# could notice the inputs disagreed.
#
# The fixtures below take their unit strings FROM THE LIVE REGISTRY, never hand-typed, so a card whose
# unit vocabulary is re-spelled re-baselines these pins loudly instead of leaving them green and wrong.
# ===================================================================================================
from leviathan.graphrag import register as _R  # noqa: E402


def _fut_unit(slug: str) -> str:
    """The GOVERNING serving unit for a silver_futures_eod contract slug (tables.yaml unit_overrides,
    three-way lint-bound to CONTRACT_MAP and config_check)."""
    return _A.load_registry().get("silver_futures_eod").metrics["settle"].unit_overrides[slug]


def _wasde_unit(commodity: str) -> str:
    """The GOVERNING serving unit for a silver_wasde avg_farm_price commodity."""
    return _A.load_registry().get("silver_wasde").metrics["avg_farm_price"].unit_overrides[commodity]


def _H(series, unit, kd="2026-01-14") -> dict:
    """A turn-scoped handle exactly as the agent loop mints one: {series, kd, unit}."""
    return {"series": list(series), "kd": kd, "unit": unit}


_HIST = [440.0, 450.0, 460.0, 470.0, 480.0, 490.0, 500.0, 510.0]     # 8 points = MIN_PERCENTILE_N


# -- the three-state table (D-FR-5), one row per outcome --------------------------------------------
def test_unit_compatible_is_a_three_state_rule_not_an_equality_test():
    """known==known -> compute; known!=known -> decline; exactly-one-known -> decline; both-unknown ->
    compute. The two naive alternatives are BOTH wrong and this pins why: a pure fail-closed rule would
    newly refuse the ~17 of 19 cards that declare no unit source at all (the both-unknown row), and a
    pure equality test would pass `"" == ""` (query.py:779 writes "" on an unresolvable commodity) and
    `None == None` (the pattern-records mint hardcodes it) as if two unrelated quantities were one."""
    cents, dollars = _fut_unit("corn_cbot"), _fut_unit("hard_red_spring_wheat_mgex")
    assert S.unit_compatible(cents, cents) is True                    # known == known
    assert S.unit_compatible(cents, dollars) is False                 # known != known (the 100x defect)
    assert S.unit_compatible(cents, None) is False                    # exactly one known
    assert S.unit_compatible(None, cents) is False                    # ...and mirrored
    assert S.unit_compatible(cents, "") is False                      # "" is UNKNOWN, not a unit
    assert S.unit_compatible("", cents) is False
    assert S.unit_compatible(None, None) is True                      # no unit dimension in play
    assert S.unit_compatible("", "") is True
    assert S.unit_compatible(None, "") is True


def test_unit_normalization_is_strip_and_casefold_and_nothing_else():
    """The ONLY normalization is strip()+casefold(). No mapping, no aliasing, no conversion -- 4.4 and
    tables.yaml:970-972 ("NEVER FX-converted at ingest or at serving"). The negative half is the point:
    two spellings of the SAME quantity stay incompatible, because closing that gap is a CONFIG edit
    (one spelling per (currency, physical unit)), never a runtime alias table here."""
    assert S.unit_compatible("US cents/bushel", "  us CENTS/BUSHEL ") is True
    assert S.unit_compatible("$/bu", "USD/bushel") is False           # same quantity, different spelling
    assert S.unit_compatible("US cents/bushel", "USD/bushel") is False  # genuinely 100x apart


def test_the_four_false_decline_pairs_are_pinned_as_declines():
    """D-FR-16 RATIFIED COST, pinned rather than discovered. The estate's unit vocabulary is not
    normalized across cards, so these four DIMENSIONALLY AND NUMERICALLY IDENTICAL pairs are refused
    today -- "where does today's cotton futures price sit against the historical US farm price" is an
    ordinary desk question with both legs in cents per pound, and it declines. Accepted because a false
    DECLINE is an honest refusal a reader can act on while a false COMPUTE is a wrong [N].

    IF D-FR-16 ever takes exit (b) (normalize the CARD vocabulary under a config_check lint), this test
    INVERTS to compute and the lint carries the guarantee. Until then, red here means someone closed the
    gap with a runtime alias -- which 4.1 and 4.4 forbid outright."""
    for wasde_c, fut_slug in (("corn", "hard_red_spring_wheat_mgex"),      # $/bu     vs USD/bushel
                              ("cotton", "cotton"),                        # c/lb     vs US cents/lb
                              ("soybean_meal", "soybean_meal_cbot"),       # $/s.t.   vs USD/short ton
                              ("rice", "rough_rice_cbot")):                # $/cwt    vs USD/cwt
        a, b = _wasde_unit(wasde_c), _fut_unit(fut_slug)
        assert a != b, (wasde_c, fut_slug, a, b)                   # non-vacuity: the spellings DO differ
        assert S.unit_compatible(a, b) is False, (a, b)
    # ...and the fifth pair on that table is a GENUINE 100x mismatch, correctly declined for a real reason.
    assert S.unit_compatible(_wasde_unit("corn"), _fut_unit("corn_cbot")) is False


# -- the guard at its ratified seam (_dispatch_stat) -------------------------------------------------
def test_guard_declines_the_hrs_usd_vs_hrw_cents_pair():
    """THE HEADLINE 100x CASE. A USD/bushel MGEX value scored against a US cents/bushel KCBT history is
    REFUSED: an honest `declined` on the stats contract (never a raise, which _exec_stat would class as
    `status: "error"` and _STATUS_STATE routes to a different C2 state), value None, and a reason that
    NAMES BOTH UNITS so the model can narrate the absence."""
    cents, dollars = _fut_unit("hard_red_winter_wheat_kcbt"), _fut_unit("hard_red_spring_wheat_mgex")
    handles = {"L1": _H(_HIST, cents), "L2": _H([7.0250], dollars)}
    res = _A._dispatch_stat("percentile", {"series_handle": "L1", "value_handle": "L2"}, handles)
    assert res["declined"] is True and res["value"] is None
    assert cents in res["reason"] and dollars in res["reason"]
    assert res["guard"] == S.UNIT_GUARD and res["units"] == f"{cents} vs {dollars}"
    assert "never converts" in res["reason"]


def test_guard_anti_vacuity_matched_units_compute_and_are_byte_identical():
    """The R8 (a) idiom: the decline cannot pass by refusing a call that was never coming. The SAME
    fixture with matched units computes, and the returned dict is BYTE-EQUAL to the pure stats call --
    not a substring match, the whole dict -- so the guard added no key, no rounding and no reshaping to
    the compatible path."""
    cents = _fut_unit("hard_red_winter_wheat_kcbt")
    handles = {"L1": _H(_HIST, cents), "L2": _H([505.0], cents)}
    res = _A._dispatch_stat("percentile", {"series_handle": "L1", "value_handle": "L2"}, handles)
    assert res == S.percentile(505.0, _HIST)
    assert res["declined"] is False and res["value"] == 87.5


def test_guard_both_unknown_path_is_byte_identical():
    """D-FR-5's compute row: a percentile across two UNITLESS cards computes exactly as it did before the
    guard existed. ~17 of 19 cards declare no unit source, so this is the common path and it must not
    move by a byte."""
    handles = {"L1": _H(_HIST, None), "L2": _H([505.0], None)}
    assert _A._dispatch_stat("percentile", {"series_handle": "L1", "value_handle": "L2"}, handles) \
        == S.percentile(505.0, _HIST)
    blanks = {"L1": _H(_HIST, ""), "L2": _H([505.0], "")}            # query.py:779's unresolvable-commodity ""
    assert _A._dispatch_stat("percentile", {"series_handle": "L1", "value_handle": "L2"}, blanks) \
        == S.percentile(505.0, _HIST)


def test_guard_asymmetric_path_declines_without_ever_printing_none():
    """Exactly-one-known -> DECLINE (D-FR-5), in both directions. The asymmetric leg carries its OWN
    wording: the guard established that one side cannot be SHOWN compatible, which is weaker than
    "different units", and the literal `None` must never reach prose the model narrates."""
    cents = _fut_unit("corn_cbot")
    for handles in ({"L1": _H(_HIST, None), "L2": _H([505.0], cents)},
                    {"L1": _H(_HIST, cents), "L2": _H([505.0], None)}):
        res = _A._dispatch_stat("zscore", {"series_handle": "L1", "value_handle": "L2"}, handles)
        assert res["declined"] is True and res["guard"] == S.UNIT_GUARD
        assert cents in res["reason"] and "None" not in res["reason"]
        assert "no unit label" in res["reason"]
        assert res["units"] in (f"{S.UNIT_UNLABELLED} vs {cents}", f"{cents} vs {S.UNIT_UNLABELLED}")


def test_empty_handle_declines_for_EMPTINESS_never_for_units():
    """U1's ORDERING FOLD. A lookup that returned no rows mints {"series": [], "unit": None} -- and a
    COVERAGE-DECLINED silver_futures_eod read is exactly that shape, i.e. this arrives on the very path
    the wave exists to fix. Under the three-state rule known-vs-unknown declines, so a unit-first order
    would hand the model "different units (US cents/bushel against None)" as the explanation for an
    EMPTY READ. The reason must name the empty read and must contain NEITHER "different units" NOR the
    literal None."""
    cents = _fut_unit("corn_cbot")
    handles = {"L1": _H(_HIST, cents), "L2": _H([], None)}
    res = _A._dispatch_stat("percentile", {"series_handle": "L1", "value_handle": "L2"}, handles)
    assert res["declined"] is True and res["guard"] == S.EMPTY_GUARD
    assert "no rows at all" in res["reason"]
    assert "different units" not in res["reason"] and "None" not in res["reason"]
    assert "units" not in res                                   # no unit pair recorded on a coverage gap


def test_emptiness_is_ordered_FIRST_even_when_the_units_also_differ():
    """The ordering is load-bearing, not cosmetic: an empty handle whose unit ALSO differs still declines
    with the EMPTINESS reason. Both sides of the fixture are wrong; only one explanation is true."""
    handles = {"L1": _H(_HIST, _fut_unit("corn_cbot")),
               "L2": _H([], _fut_unit("hard_red_spring_wheat_mgex"))}   # empty AND a different unit
    res = _A._dispatch_stat("percentile", {"series_handle": "L1", "value_handle": "L2"}, handles)
    assert res["guard"] == S.EMPTY_GUARD and "no rows at all" in res["reason"]
    assert "different units" not in res["reason"]
    # ...and the mirrored case: the HISTORY handle is the empty one.
    mirrored = {"L1": _H([], _fut_unit("corn_cbot")),
                "L2": _H([7.02], _fut_unit("hard_red_spring_wheat_mgex"))}
    res2 = _A._dispatch_stat("percentile", {"series_handle": "L1", "value_handle": "L2"}, mirrored)
    assert res2["guard"] == S.EMPTY_GUARD and "history series" in res2["reason"]


def test_guard_n_is_the_series_handles_length_never_zero_and_never_the_value_handles():
    """4.6: `n` is positional and REQUIRED on the _decline contract and it reaches the model. At the
    guard's seam no series has been resolved, so `n` carries the SERIES handle's own length -- the sample
    the stat WOULD have run over. It is never a fabricated 0 a reader could mistake for "no data", and
    never the value handle's length. The unit refusal is about the COMPARISON, not about thinness."""
    handles = {"L1": _H(_HIST, _fut_unit("corn_cbot")),                       # 8 points
               "L2": _H([7.0, 7.1, 7.2], _fut_unit("hard_red_spring_wheat_mgex"))}   # 3 points
    res = _A._dispatch_stat("percentile", {"series_handle": "L1", "value_handle": "L2"}, handles)
    assert res["n"] == len(handles["L1"]["series"]) == 8
    assert res["n"] != 0 and res["n"] != len(handles["L2"]["series"])
    # the EMPTY-value-handle decline keeps the same rule (the history is still 8 points long).
    empty = {"L1": _H(_HIST, _fut_unit("corn_cbot")), "L2": _H([], None)}
    assert _A._dispatch_stat("percentile", {"series_handle": "L1", "value_handle": "L2"}, empty)["n"] == 8


def test_guard_does_not_fire_on_a_single_handle_for_any_unit_value():
    """The trigger is `value_handle is not None`, so every one-handle stat is untouched for EVERY unit
    value -- including the mixed-unit case the guard structurally CANNOT reach (D-FR-17(i)): a unit_col
    card's commodity-less lookup returns mixed-unit rows, the handle samples rows[0] alone, and there is
    no second handle to compare against. Byte-equality against the pure stats call is the pin."""
    for unit in (None, "", _fut_unit("corn_cbot"), _fut_unit("hard_red_spring_wheat_mgex")):
        h = {"L1": _H(_HIST, unit)}
        assert _A._dispatch_stat("streak", {"series_handle": "L1", "direction": "up"}, h) \
            == S.streak(_HIST, "up")
        assert _A._dispatch_stat("revision_count", {"series_handle": "L1", "direction": "up"}, h) \
            == S.revision_count(_HIST, "up")
        assert _A._dispatch_stat("window_change", {"series_handle": "L1", "t1": 0, "t2": -1}, h) \
            == S.window_change(_HIST, 0, -1)
        assert _A._dispatch_stat("extrema", {"series_handle": "L1"}, h) == S.extrema(_HIST)
        assert _A._dispatch_stat("yoy_delta", {"series_handle": "L1", "periods": 2}, h) \
            == S.yoy_delta(_HIST, periods=2)
        # ...and the two value-taking stats fall back to series[-1] exactly as before.
        assert _A._dispatch_stat("percentile", {"series_handle": "L1"}, h) == S.percentile(_HIST[-1], _HIST)
        assert _A._dispatch_stat("zscore", {"series_handle": "L1"}, h) == S.zscore(_HIST[-1], _HIST)


def test_the_trigger_is_the_value_handle_not_the_stat_and_that_cost_is_named():
    """A STATED CONSEQUENCE of the ratified trigger, pinned so it is not discovered on a deck. The
    trigger asks only whether a second handle was referenced -- it does not ask whether the stat READS
    it. So a `streak` carrying a spurious cross-unit value_handle declines, even though streak ignores
    the value entirely. That is a nonsense request declined, not a number lost; the alternative (gating
    on the stat name) would silently re-open the defect the moment a new value-taking stat is added."""
    handles = {"L1": _H(_HIST, _fut_unit("corn_cbot")),
               "L2": _H([7.02], _fut_unit("hard_red_spring_wheat_mgex"))}
    res = _A._dispatch_stat("streak", {"series_handle": "L1", "value_handle": "L2", "direction": "up"},
                            handles)
    assert res["declined"] is True and res["guard"] == S.UNIT_GUARD and res["stat"] == "streak"


def test_the_level_versus_delta_class_is_pinned_as_UNCOVERED():
    """D-FR-17(ii), pinned so nobody reads U1 as closing the wrong-number class. _STAT_UNIT covers only
    streak/revision_count/percentile/zscore, so window_change / yoy_delta / extrema mint chained handles
    carrying the RAW PRICE UNIT. A percentile of a +70-cent DELTA inside a distribution of ~470-cent
    LEVELS is therefore known == known -> COMPUTES, at the 0th percentile, minted as a cited [N]. It is
    a level-versus-delta confusion, not a unit mismatch, and unit equality is the wrong instrument for
    it -- closing it needs a `kind` (level/delta/score) field on the handle, which is its own item."""
    cents = _fut_unit("corn_cbot")
    handles = {"L1": _H(_HIST, cents), "L2": _H([5.0], cents)}       # L2 = a window_change on L1's card
    res = _A._dispatch_stat("percentile", {"series_handle": "L1", "value_handle": "L2"}, handles)
    assert res["declined"] is False and res["value"] == 0.0          # the 0th percentile, computed
    assert res == S.percentile(5.0, _HIST)


# -- the registered templates (D-FR-14 exit (1)'s in-lane half) --------------------------------------
def test_stat_decline_templates_are_registered_register_clean_and_actually_emitted():
    """WHY A REGISTERED DICT AND NOT AN f-STRING AT THE CALL SITE: config_check's futures_lite census
    iterates FUTURES_DECLINE_TEMPLATES BY NAME and the C2 census iterates question SHAPES -- a string
    built inside _dispatch_stat is enumerated by neither, so a register leak in prose the model then
    narrates would be invisible to a green config_check.

    Held to the same bar the futures templates are (leaks / valuation / flow clean, sanitize-stable,
    never the word "settle") under BOTH registers. The last block is the NON-VACUITY half: a registered
    template nobody emits is dead prose, so each one is matched against a real guard fire."""
    assert set(_A.STAT_DECLINE_TEMPLATES) == {"unit_mismatch", "unit_unknown", "empty_series"}
    assert not (set(_A.STAT_DECLINE_TEMPLATES) & set(_A.FUTURES_DECLINE_TEMPLATES))
    for name, t in _A.STAT_DECLINE_TEMPLATES.items():
        rendered = t.format(a="US cents/bushel", b="USD/bushel", known="US cents/bushel",
                            which="history series")
        for probe in (t, rendered):
            assert not _R.register_leaks(probe), (name, probe)
            assert not _R.exec_leaks(probe), (name, probe)
            assert _R.count_valuation_words(probe) == 0 and _R.count_flow_words(probe) == 0
            assert not re.search(r"(?i)settle", probe), (name, probe)
            assert probe.isascii()
            for mr in (_R.FENCED, _R.OUTLOOK):
                assert _R.sanitize(probe, market_register=mr) == probe, (name, mr)
    cents, dollars = _fut_unit("corn_cbot"), _fut_unit("hard_red_spring_wheat_mgex")
    fires = {
        "unit_mismatch": _A._dispatch_stat(
            "percentile", {"series_handle": "L1", "value_handle": "L2"},
            {"L1": _H(_HIST, cents), "L2": _H([7.02], dollars)})["reason"],
        "unit_unknown": _A._dispatch_stat(
            "percentile", {"series_handle": "L1", "value_handle": "L2"},
            {"L1": _H(_HIST, cents), "L2": _H([7.02], None)})["reason"],
        "empty_series": _A._dispatch_stat(
            "percentile", {"series_handle": "L1", "value_handle": "L2"},
            {"L1": _H(_HIST, cents), "L2": _H([], None)})["reason"],
    }
    for name, reason in fires.items():
        head = _A.STAT_DECLINE_TEMPLATES[name].split("{")[0]
        assert head and head in reason, (name, reason)


# -- end to end through the agent loop, on the defect's OWN table ------------------------------------
def _eod_use(commodity, agg, tid):
    return _tu(_A.TOOL_NAME, {"table": "silver_futures_eod", "metric": "settle",
                              "commodity": commodity, "agg": agg}, tid)


def _eod_rows(vals, kd):
    """Rows as the EOD card returns them -- unit deliberately absent, because _apply_unit_overrides
    (query.py:811) is what stamps the governing unit post-fetch. That is the seam the guard reads."""
    return [{"value": str(v), "knowledge_date": kd, "contract_month": "2026-03"} for v in vals]


def _eod_qf(sql):
    return _eod_rows([7.0250], "2026-01-14") if "hard_red_spring" in sql \
        else _eod_rows(_HIST, "2026-01-14")


_Q_WHEAT = "how does spring wheat compare with winter wheat history"


def test_loop_cross_unit_stat_declines_injects_nothing_and_records_the_trace_key():
    """END TO END on silver_futures_eod itself, with the units minted by _apply_unit_overrides from the
    card (never hand-set on the fixture rows). The stat REFUSES: the model gets `status: "declined"`
    with both units named, `calls` gains ZERO entries (so no [N] row, no citation, no fabricated
    percentile), and U3's `unit_mismatch_guard` key carries the pair."""
    said = ("Those two contracts are quoted on different scales, so I am not ranking one in the "
            "other's history.")
    client = _FakeClient([
        _rp([_eod_use("hard_red_winter_wheat_kcbt", "series", "t1")]),
        _rp([_eod_use("hard_red_spring_wheat_mgex", "latest", "t2")]),
        _rp([_tu(_A.STATS_TOOL_NAME,
                 {"stat": "percentile", "series_handle": "L1", "value_handle": "L2"}, "t3")]),
        _rp([_txt(said)]),
    ])
    out = _A.answer_numbers(_Q_WHEAT, asof="2026-01-15", client=client, query_fn=_eod_qf)
    tables = [(c.get("query") or {}).get("table") for c in out["calls"]]
    assert tables == ["silver_futures_eod", "silver_futures_eod"]     # the two LOOKUPS, and nothing else
    assert not [c for c in out["calls"] if (c.get("query") or {}).get("table") == _A.STATS_TOOL_NAME]
    # the units really were minted by the card's unit_overrides, not by the fixture.
    assert [c["rows"][0]["unit"] for c in out["calls"]] == \
        [_fut_unit("hard_red_winter_wheat_kcbt"), _fut_unit("hard_red_spring_wheat_mgex")]
    payload = _json.loads(client.sent[3]["messages"][-1]["content"][0]["content"])
    assert payload["status"] == "declined" and payload["value"] is None
    assert _fut_unit("hard_red_winter_wheat_kcbt") in payload["reason"]
    assert _fut_unit("hard_red_spring_wheat_mgex") in payload["reason"]
    # U3, with the two units RECORDED -- presence alone cannot tell a wired key from a dead one.
    expected = _fut_unit("hard_red_winter_wheat_kcbt") + " vs " + _fut_unit("hard_red_spring_wheat_mgex")
    assert out[_A.UNIT_MISMATCH_TRACE_KEY] == [expected]
    # 4.6: the refusal is MODEL-FACING ONLY. It mints NO preface -- the answer is the model's own text
    # byte for byte -- and other_decline_fired stays False, which is what keeps U1 out of the decline
    # register: a new lead here would silence the C2 question-shape line on every co-occurring turn.
    assert out["answer"] == said
    assert _A.other_decline_fired(out["answer"]) is False


def test_loop_matched_units_compute_and_the_trace_key_is_ABSENT():
    """U3's non-vacuity twin AND the loop-level anti-vacuity half. The same three-call shape with BOTH
    handles on the same card computes, injects its [N] row, and leaves `unit_mismatch_guard` off the
    result entirely -- a key that is always present measures nothing."""
    client = _FakeClient([
        _rp([_eod_use("hard_red_winter_wheat_kcbt", "series", "t1")]),
        _rp([_eod_use("hard_red_winter_wheat_kcbt", "latest", "t2")]),
        _rp([_tu(_A.STATS_TOOL_NAME,
                 {"stat": "percentile", "series_handle": "L1", "value_handle": "L2"}, "t3")]),
        _rp([_txt("It sits in the 87.5th percentile of its own history [N].")]),
    ])
    out = _A.answer_numbers(_Q_WHEAT, asof="2026-01-15", client=client,
                            query_fn=lambda sql: _eod_rows(_HIST, "2026-01-14"))
    stat_calls = [c for c in out["calls"] if (c.get("query") or {}).get("table") == _A.STATS_TOOL_NAME]
    assert len(stat_calls) == 1 and stat_calls[0]["rows"][0]["unit"] == "percentile"
    assert _A.UNIT_MISMATCH_TRACE_KEY not in out


def test_loop_a_COVERAGE_DECLINED_read_is_narrated_as_empty_never_as_a_unit_mismatch():
    """THE REVIEW'S #4 FINDING, reproduced end to end on the plan's own headline slug. At this as-of
    hard_red_spring_wheat_mgex is BEFORE its coverage floor, so the read is declined upstream and comes
    back with `rows: []` -> the handle mints unit=None. Known-vs-unknown declines under the three-state
    rule, so without the emptiness ordering the model would be handed "different units (US cents/bushel
    against None)" as the explanation for a COVERAGE GAP, and would narrate it. It gets the empty-read
    reason instead, and U3's key stays off -- a coverage gap is not a unit event and must not inflate
    the guard's census."""
    client = _FakeClient([
        _rp([_eod_use("hard_red_winter_wheat_kcbt", "series", "t1")]),
        _rp([_eod_use("hard_red_spring_wheat_mgex", "latest", "t2")]),
        _rp([_tu(_A.STATS_TOOL_NAME,
                 {"stat": "percentile", "series_handle": "L1", "value_handle": "L2"}, "t3")]),
        _rp([_txt("That contract is not covered this far back, so there is nothing to rank.")]),
    ])
    out = _A.answer_numbers(_Q_WHEAT, asof="2024-07-01", client=client, query_fn=_eod_qf)
    mgex = next(c for c in out["calls"]
                if (c.get("query") or {}).get("commodity") == "hard_red_spring_wheat_mgex")
    # NON-VACUITY: the empty handle came from a REAL upstream coverage decline, not from a stubbed row.
    assert mgex["status"] == "declined" and mgex["rows"] == [] and mgex.get("coverage_route")
    payload = _json.loads(client.sent[3]["messages"][-1]["content"][0]["content"])
    assert payload["status"] == "declined" and payload["guard"] == S.EMPTY_GUARD
    assert "no rows at all" in payload["reason"]
    assert "different units" not in payload["reason"] and "None" not in payload["reason"]
    assert _A.UNIT_MISMATCH_TRACE_KEY not in out


def test_loop_chained_window_change_handle_still_computes_the_level_vs_delta_percentile():
    """D-FR-17(ii) end to end: the chained mint reads injected[0]["rows"][0]["unit"], and _STAT_UNIT does
    not cover window_change, so the DELTA handle inherits the RAW price unit. The guard sees known ==
    known and computes -- ranking a delta inside a distribution of levels. Pinned as UNCOVERED so no
    reviewer reads U1 as closing the wrong-number class; it changes only when a handle carries a
    level/delta/score kind."""
    client = _FakeClient([
        _rp([_eod_use("hard_red_winter_wheat_kcbt", "series", "t1")]),
        _rp([_tu(_A.STATS_TOOL_NAME,
                 {"stat": "window_change", "series_handle": "L1", "t1": 0, "t2": -1}, "t2")]),
        _rp([_tu(_A.STATS_TOOL_NAME,
                 {"stat": "percentile", "series_handle": "L1", "value_handle": "L2"}, "t3")]),
        _rp([_txt("done")]),
    ])
    out = _A.answer_numbers(_Q_WHEAT, asof="2026-01-15", client=client,
                            query_fn=lambda sql: _eod_rows(_HIST, "2026-01-14"))
    stat_rows = [c["rows"][0] for c in out["calls"]
                 if (c.get("query") or {}).get("table") == _A.STATS_TOOL_NAME]
    assert len(stat_rows) == 2
    # the window_change handle carried the RAW price unit -- that is the whole mechanism.
    assert stat_rows[0]["unit"] == _fut_unit("hard_red_winter_wheat_kcbt")
    assert stat_rows[0]["value"] == 70.0                       # 510 - 440, a DELTA
    assert stat_rows[1]["unit"] == "percentile" and stat_rows[1]["value"] == 0.0   # ...at the 0th pct
    assert _A.UNIT_MISMATCH_TRACE_KEY not in out
