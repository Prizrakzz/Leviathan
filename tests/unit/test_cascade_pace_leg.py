"""CONVERGENCE_TIER1 T2a -- the cascade pace leg (hermetic: no pg/Athena/LLM; hand-built records).

Covers: the _node_specs pace gate (kwarg-threaded, default OFF -> byte-identical specs; pace-capable
sub-annual tables only; annual/MY grain and event flags NEVER get a sub-annual window), _group_by_node
keeping pace records OUT of the era buckets, _pace_legs' deterministic streak/window_change [N] rows on a
synthetic weekly series, the <2-points honest decline (E-STREAK-NODATA), and the eval surface
(pace_fired boolean + the pace_expected pin + the per-answer record), mirroring the test_cascade_esr_pace /
test_reroute_v2_surface idioms."""
from __future__ import annotations

from types import SimpleNamespace

from leviathan.graphrag import eval as ev
from leviathan.graphrag.numbers import cascade as cq

_ESR_ROW = {
    "table": "silver_esr", "metric": "weekly_exports_1000mt", "agg": "latest", "period_type": "date",
    "leg_mode": "current", "country_rule": "none", "native_unit": "1000 MT", "narrate_unit": "1000 MT",
    "scale": 1, "coverage_start": 1990,
}
_PSD_EXPORT_ROW = {
    "table": "silver_psd", "metric": "exports_mt", "agg": "latest", "period_type": "marketing_year",
    "narrate_unit": "MMT", "scale": 0.000001,
}
_FROST_ROW = {
    "table": "gold_weather_z", "metric": "frost_event_flag", "period_type": "year_month",
    "native_unit": "flag", "narrate_unit": "flag", "scale": 1,
}
_FX_ROW = {
    "table": "silver_fred_fx", "metric": "brl_usd", "period_type": "date", "scale": 1,
    "narrate_unit": "local currency per USD",
}

_ERAS = [("2012-06-01", "2012-11-01")]


def _node(contract="corn_cbot", ref="esr_exports", nid="us_export_pace"):
    return SimpleNamespace(contract=contract, id=nid, prior={"silver_ref": ref, "region": "US"}, evidence=[])


# -- the _node_specs pace gate ---------------------------------------------------------------------------
def test_pace_off_default_specs_byte_identical():
    base = cq._node_specs(_node(), _ESR_ROW, "corn_cbot", None, _ERAS, asof="2026-07-01")
    off = cq._node_specs(_node(), _ESR_ROW, "corn_cbot", None, _ERAS, asof="2026-07-01", pace=False)
    assert base == off                                            # the kwarg default IS off
    assert [s["leg"] for s in base] == [("current", None)]        # no pace leg exists flag-off


def test_pace_on_weekly_table_adds_one_series_spec():
    specs = cq._node_specs(_node(), _ESR_ROW, "corn_cbot", None, _ERAS, asof="2026-07-01", pace=True)
    legs = [s["leg"] for s in specs]
    assert legs == [("current", None), ("pace", None)]
    p = specs[-1]
    assert p["agg"] == "series" and p["asof"] == "2026-07-01" and p["t2"] == "2026-07-01"
    assert p["t1"] == "2026-04-22"                                # asof - 70d (the weekly pace window)


def test_pace_on_daily_fx_table_adds_spec_with_daily_window():
    specs = cq._node_specs(_node(ref="fred_fx_macro", nid="BRL_FX"), _FX_ROW, "soybeans_cbot", None,
                           _ERAS, asof="2026-07-01", pace=True)
    p = [s for s in specs if s["leg"] == ("pace", None)]
    assert len(p) == 1 and p[0]["t1"] == "2026-06-10"             # asof - 21d


def test_pace_never_on_annual_my_grain():
    specs = cq._node_specs(_node(ref="export", nid="export"), _PSD_EXPORT_ROW, "corn_cbot",
                           "United States", _ERAS, asof="2026-07-01", pace=True)
    assert not any(s["leg"][0] == "pace" for s in specs)          # MY grain: no sub-annual window, ever


def test_pace_never_on_event_flags_or_unlisted_tables():
    specs = cq._node_specs(_node(ref="frost_event_flag", nid="frost"), _FROST_ROW, "arabica_coffee",
                           "Brazil", _ERAS, asof="2026-07-01", pace=True)
    assert not any(s["leg"][0] == "pace" for s in specs)          # flag metric: recency is T2b, not pace
    row = {"table": "silver_wasde", "metric": "ending_stocks", "period_type": "marketing_year", "scale": 1}
    assert cq._pace_grain(row) is None                            # annual tables absent from PACE_TABLES
    assert cq._pace_grain(_FROST_ROW) is None
    assert cq._pace_grain(_ESR_ROW) == "week"
    assert cq._pace_grain(_FX_ROW) == "day"
    assert cq._pace_grain({"table": "silver_pink_sheet", "period_type": "date"}) == "month"


def test_pace_requires_asof():
    specs = cq._node_specs(_node(), _ESR_ROW, "corn_cbot", None, _ERAS, asof=None, pace=True)
    assert not any(s["leg"][0] == "pace" for s in specs)


# -- _group_by_node: pace records never pollute the era buckets ------------------------------------------
def _pace_rec(values_dates, key=("corn_cbot", "us_export_pace"), asof="2026-07-01"):
    return {"query": {"commodity": "corn_cbot", "metric": "weekly_exports_1000mt",
                      "period": "2026-04-22..2026-07-01", "asof": asof},
            "rows": [{"value": str(v), "unit": "1000 MT", "week_ending_date": d} for v, d in values_dates],
            "status": "ok", "node_key": key, "leg": ("pace", None), "era_idx": None, "my": None}


def test_group_by_node_routes_pace_out_of_eras():
    key = ("corn_cbot", "us_export_pace")
    rec = _pace_rec([(500, "2026-06-14"), (560, "2026-06-21")])
    kept = [{"specs": [{"node_key": key}], "row": _ESR_ROW}]
    grouped = cq._group_by_node([rec], kept)
    assert grouped[key]["eras"] == {}                             # NEVER an era bucket (would poison _era_delta)
    assert grouped[key]["current"] is None
    assert grouped[key]["pace"] is rec


# -- _pace_legs: the deterministic streak + window_change rows -------------------------------------------
def _kept(row=_ESR_ROW, key=("corn_cbot", "us_export_pace")):
    return [{"specs": [{"node_key": key}], "row": row}]


def test_pace_streak_and_window_change_rows_on_synthetic_weekly_series():
    rec = _pace_rec([(500.0, "2026-06-07"), (520.0, "2026-06-14"), (560.0, "2026-06-21"),
                     (610.0, "2026-06-28")])
    calls: list = []
    lines, trace = cq._pace_legs([rec], _kept(), 0, calls)
    assert len(calls) == 2 and len(lines) == 2
    chg, stk = calls
    assert chg["query"]["metric"] == "weekly_exports_1000mt_pace_change"
    assert chg["rows"][0]["value"] == 50.0 and chg["rows"][0]["unit"] == "1000 MT"
    assert chg["rows"][0]["_provenance"]["week_ending_date"] == "2026-06-28"   # as-known at the LATEST point
    assert stk["query"]["metric"] == "weekly_exports_1000mt_pace_streak"
    assert stk["rows"][0]["value"] == 3 and stk["rows"][0]["unit"] == "weeks"
    # W4 A/B RCA (2026-08-01): each line binds the magnitude it prints. The streak line renders its run as
    # a DIGIT ("in each of the last 3 weeks"), so 3 is a magnitude a citation may legitimately quote.
    assert chg["shown"] == [50.0] and stk["shown"] == [3.0]
    # W4: every reader-facing [N] line ends with the SERIES scope tag (contract, country, table)
    assert lines[0] == ("- [N1] change in weekly exports from the prior week (weekly pace): "
                        "+50 1000 MT [series: corn_cbot; table: USDA FAS Export Sales (ESR)]")
    assert lines[1] == ("- [N2] weekly exports rose in each of the last 3 weeks "
                        "[series: corn_cbot; table: USDA FAS Export Sales (ESR)]")
    assert trace == [{"node_key": ["corn_cbot", "us_export_pace"], "table": "silver_esr",
                      "metric": "weekly_exports_1000mt", "grain": "week", "n_points": 4,
                      "streak": 3, "window_change": 50.0, "streak_direction": "up"}]


def test_pace_declining_series_says_fell():
    rec = _pace_rec([(610.0, "2026-06-07"), (560.0, "2026-06-14"), (520.0, "2026-06-21")])
    calls: list = []
    lines, trace = cq._pace_legs([rec], _kept(), 4, calls)        # base continues the N-count
    assert lines[0].startswith("- [N5] change in weekly exports from the prior week")
    assert "-40" in lines[0]
    assert lines[1] == ("- [N6] weekly exports fell in each of the last 2 weeks "
                        "[series: corn_cbot; table: USDA FAS Export Sales (ESR)]")
    assert trace[0]["streak_direction"] == "down"


def test_pace_single_move_emits_change_row_but_no_streak():
    rec = _pace_rec([(500.0, "2026-06-14"), (560.0, "2026-06-21")])   # one move: run of 1 < 2
    calls: list = []
    lines, trace = cq._pace_legs([rec], _kept(), 0, calls)
    assert len(calls) == 1 and calls[0]["query"]["metric"].endswith("_pace_change")
    assert trace[0]["streak"] is None and trace[0]["window_change"] == 60.0


def test_pace_under_two_points_honest_absence_no_rows_no_trace():
    rec = _pace_rec([(742.5, "2026-06-28")])                      # <MIN_STREAK_N: no pace claim
    calls: list = []
    lines, trace = cq._pace_legs([rec], _kept(), 0, calls)
    assert lines == [] and trace == [] and calls == []            # pace_fired stays false downstream


def test_pace_skips_non_ok_and_non_pace_and_annual_rows():
    bad = {**_pace_rec([(1, "2026-06-14"), (2, "2026-06-21")]), "status": "error"}
    cur = {**_pace_rec([(1, "2026-06-14"), (2, "2026-06-21")]), "leg": ("current", None)}
    psd_key = ("corn_cbot", "export")
    psd_pace = _pace_rec([(1, "2026-06-14"), (2, "2026-06-21")], key=psd_key)   # defensive: PSD grain None
    kept = _kept() + [{"specs": [{"node_key": psd_key}], "row": _PSD_EXPORT_ROW}]
    calls: list = []
    lines, trace = cq._pace_legs([bad, cur, psd_pace], kept, 0, calls)
    assert lines == [] and trace == [] and calls == []


def test_pace_scale_prescales_the_change_row():
    key = ("cocoa", "grind_pace")
    row = {"table": "silver_pink_sheet", "metric": "cocoa_price", "period_type": "date",
           "narrate_unit": "cents/kg", "scale": 0.1}
    rec = _pace_rec([(2500.0, "2026-04-30"), (2600.0, "2026-05-31")], key=key)
    calls: list = []
    lines, _tr = cq._pace_legs([rec], [{"specs": [{"node_key": key}], "row": row}], 0, calls)
    assert calls[0]["rows"][0]["value"] == 10.0                   # (2600-2500) * 0.1, pre-scaled
    assert "monthly pace" in lines[0] and "month" in lines[0]


# -- cross-section collapse (skeptic fold): per-period, never destinationB-destinationA ------------------
def _esr_multi_dest_rec(week_rows, key=("corn_cbot", "us_export_pace")):
    """rows = [(value, week_ending_date), ...] in SQL order (period-ascending, multiple destinations per
    week) -- the REAL silver_esr series shape (grain per destination x week; no destination column)."""
    return {"query": {"commodity": "corn_cbot", "metric": "weekly_exports_1000mt", "asof": "2026-07-01"},
            "rows": [{"value": str(v), "unit": "1000 MT", "data_date": d} for v, d in week_rows],
            "status": "ok", "node_key": key, "leg": ("pace", None), "era_idx": None, "my": None}


def test_pace_esr_collapses_destinations_per_week_probe_scenario():
    # THE PROBE: flat vals[-1]-vals[-2] deltas two destinations inside the latest week (+565-class garbage,
    # direction inverted). True weekly TOTALS: 610 -> 565 = -45. The fix sums destinations per week.
    rec = _esr_multi_dest_rec([(300.0, "2026-06-21"), (310.0, "2026-06-21"),
                               (280.0, "2026-06-28"), (285.0, "2026-06-28")])
    calls: list = []
    lines, trace = cq._pace_legs([rec], _kept(), 0, calls)
    assert len(calls) == 1                                        # change row only (1 period-move: no streak)
    assert calls[0]["rows"][0]["value"] == -45.0                  # 565 - 610, NEVER 285 - 280
    assert "-45" in lines[0] and "prior week" in lines[0]
    assert trace[0]["window_change"] == -45.0
    assert trace[0]["n_points"] == 2                              # PERIODS, not raw cross-section rows
    assert trace[0]["collapse"] == "sum"                          # attached only when a merge happened


def test_pace_esr_streak_runs_on_weekly_totals():
    rec = _esr_multi_dest_rec([(100.0, "2026-06-14"), (200.0, "2026-06-14"),   # total 300
                               (150.0, "2026-06-21"), (200.0, "2026-06-21"),   # total 350
                               (180.0, "2026-06-28"), (230.0, "2026-06-28")])  # total 410
    calls: list = []
    lines, trace = cq._pace_legs([rec], _kept(), 0, calls)
    assert trace[0]["window_change"] == 60.0 and trace[0]["streak"] == 2       # totals rose 2 weeks
    assert lines[1] == ("- [N2] weekly exports rose in each of the last 2 weeks "
                        "[series: corn_cbot; table: USDA FAS Export Sales (ESR)]")


def test_pace_weather_collapses_regions_per_month_mean():
    key = ("arabica_coffee", "heat")
    row = {"table": "gold_weather_z", "metric": "heat_stress_z", "period_type": "year_month",
           "narrate_unit": "z", "scale": 1}
    rec = {"query": {"commodity": "arabica_coffee", "metric": "heat_stress_z", "asof": "2026-07-01"},
           "rows": [{"value": "0.3", "unit": "z", "year": "2026", "month": "5"},     # region A
                    {"value": "0.5", "unit": "z", "year": "2026", "month": "5"},     # region B
                    {"value": "0.8", "unit": "z", "year": "2026", "month": "6"},
                    {"value": "1.2", "unit": "z", "year": "2026", "month": "6"}],
           "status": "ok", "node_key": key, "leg": ("pace", None), "era_idx": None, "my": None}
    calls: list = []
    lines, trace = cq._pace_legs([rec], [{"specs": [{"node_key": key}], "row": row}], 0, calls)
    assert calls[0]["rows"][0]["value"] == 0.6                    # mean 1.0 - mean 0.4, NEVER 1.2 - 0.8
    assert trace[0]["collapse"] == "mean" and trace[0]["n_points"] == 2


def test_pace_undeclared_cross_section_declines_whole():
    key = ("corn_cbot", "mm_net")
    row = {"table": "silver_cot", "metric": "mm_net_position", "period_type": "date",
           "narrate_unit": "contracts", "scale": 1}
    rec = {"query": {}, "rows": [{"value": "100", "data_date": "2026-06-21"},
                                 {"value": "120", "data_date": "2026-06-21"},    # duplicate period, no
                                 {"value": "140", "data_date": "2026-06-28"}],   # declared collapse
           "status": "ok", "node_key": key, "leg": ("pace", None), "era_idx": None, "my": None}
    calls: list = []
    lines, trace = cq._pace_legs([rec], [{"specs": [{"node_key": key}], "row": row}], 0, calls)
    assert lines == [] and trace == [] and calls == []            # honest absence, never a cross delta


def test_pace_single_row_periods_carry_no_collapse_key():
    rec = _pace_rec([(500.0, "2026-06-14"), (560.0, "2026-06-21")])
    calls: list = []
    _lines, trace = cq._pace_legs([rec], _kept(), 0, calls)
    assert "collapse" not in trace[0]                             # absent, not null (nothing merged)


def test_pace_register_ok_fence():
    assert cq.pace_register_ok("rose in each of the last 3 weeks") is True
    assert cq.pace_register_ok("the weekly pace was 742.5, up 12.5 from the prior week") is True
    for bad in ("exports are accelerating", "momentum is building", "shipments are picking up",
                "demand is slowing", "decelerating pace", "gaining steam"):
        assert cq.pace_register_ok(bad) is False


# -- eval surface: pace_fired boolean + pace_expected pin + the per-answer record ------------------------
def _out(*, fired=False):
    trace = {"quantify": []}
    if fired:
        trace["quantify_pace"] = [{"metric": "weekly_exports_1000mt", "streak": 3, "window_change": 50.0}]
    return {"trace": trace, "structured": {"tldr": "", "mechanism": "## Mechanism\nprose"},
            "citations": [], "intent_decision": {"planner": "llm"}}


def test_cascade_stats_pace_fired_is_boolean():
    assert ev._cascade_stats(_out(fired=False))["pace_fired"] is False
    assert ev._cascade_stats(_out(fired=True))["pace_fired"] is True
    out = {"trace": {"quantify": []}, "structured": {"tldr": "", "mechanism": ""}, "citations": []}
    assert ev._cascade_stats(out)["pace_fired"] is False          # absent key -> False, never KeyError


def test_pace_expected_pin_true_and_false():
    assert ev._cascade_asserts({"expect": {"pace_expected": True}}, _out(fired=True))["pace_expected"] is True
    assert ev._cascade_asserts({"expect": {"pace_expected": True}}, _out(fired=False))["pace_expected"] is False
    assert ev._cascade_asserts({"expect": {"pace_expected": False}}, _out(fired=False))["pace_expected"] is True
    assert ev._cascade_asserts({"expect": {"pace_expected": False}}, _out(fired=True))["pace_expected"] is False


def test_pace_pin_absent_leaves_other_asserts_byte_identical():
    q = {"expect": {"cascade_fired": False}}
    res = ev._cascade_asserts(q, _out(fired=True))
    assert "pace_expected" not in res and res == {"cascade_fired": True}


def test_per_answer_record_carries_pace_fired():
    rec = ev._per_answer_record({"q": {"id": "p1"}, "out": _out(fired=True), "rubric": {}}, "single")
    assert rec["pace_fired"] is True
    rec2 = ev._per_answer_record({"q": {"id": "p2"}, "out": {"answer": ""}}, "single")
    assert rec2["pace_fired"] is False


def test_pace_does_not_pollute_sibling_stats():
    cs = ev._cascade_stats(_out(fired=True))
    assert cs["reroute_v2_pairs"] == 0 and cs["comove_fired"] is False and cs["price_leg_fired"] is False
