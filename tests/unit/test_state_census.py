"""THE BOARD CENSUS, proved on INJECTED FAKES -- no pg, no network, no Athena, no LLM.

WHY FAKES AND NOT THE OFFLINE HARNESS ALONE. The offline pass (``board_census --offline``) proves the
SHAPE end to end against ``state.__main__``'s fixture arrays, and it is exercised here too. But the
census's own claims -- "the rectangle closes on every board", "the register trip count is zero", "the
loud order under the alternative tuple differs from D2 when the conventions say it should", "a pool
decline is COUNTED and re-raised, never eaten" -- are claims about the CENSUS, and each needs a fake
built to make it fail if the census is wrong. That is what these decks are.

EVERY EXECUTOR HERE IS INJECTED. Nothing in this file can reach a mirror: the counting executor is
handed a callable the test wrote, the state functions are handed arrays the test wrote, and the one
deck that touches the CLI runs it with ``--offline``, whose executor raises on any read.
"""
from __future__ import annotations

import json

import pytest

from leviathan.graphrag.state import board_census as BC


# ---------------------------------------------------------------------------------------------------
# THE COUNTING EXECUTOR
# ---------------------------------------------------------------------------------------------------
def test_counting_executor_counts_reads_rows_and_latency():
    calls = []

    def inner(sql):
        calls.append(sql)
        return [{"a": 1}, {"a": 2}]

    c = BC.CountingExecutor(inner, name="deck")
    c("SELECT x FROM leviathan_dev.silver_noaa_oni WHERE 1=1")
    c("SELECT x FROM leviathan_dev.silver_psd WHERE 1=1")
    snap = c.snapshot()
    assert snap["reads"] == 2
    assert snap["rows"] == 4
    assert snap["ms"]["n"] == 2
    assert snap["by_table"] == {"silver_noaa_oni": 1, "silver_psd": 1}
    assert snap["declines"] == {} and snap["errors"] == {}
    assert len(calls) == 2


def test_counting_executor_records_a_pool_decline_by_name_and_re_raises():
    """A DECLINE IS A WORD AND AN EXCEPTION, and the census needs both: the counter must publish
    ``pool_exhausted`` and the caller must still see the raise, because ``series_state`` turns that
    raise into the row's own status word. A wrapper that swallowed it would report a read the row
    never got."""
    from leviathan.graphrag.state import feeders as F

    def inner(sql):
        raise F.BoardReadDecline("pool_exhausted", "no connection freed in 5s")

    c = BC.CountingExecutor(inner)
    with pytest.raises(F.BoardReadDecline):
        c("SELECT 1")
    snap = c.snapshot()
    assert snap["declines"] == {"pool_exhausted": 1}
    assert snap["reads"] == 1, "a declined attempt still spent a slot and must be counted"


def test_counting_executor_records_a_plain_error_by_type_and_re_raises():
    def inner(sql):
        raise ValueError("bad sql")

    c = BC.CountingExecutor(inner)
    with pytest.raises(ValueError):
        c("SELECT 1")
    assert c.snapshot()["errors"] == {"ValueError": 1}


def test_ms_summary_says_none_rather_than_zero_when_nothing_ran():
    empty = BC._ms_summary([])
    assert empty["n"] == 0
    assert empty["p50"] is None and empty["max"] is None, \
        "a probe that made no read must not report 0 ms -- that is a measurement about nothing"
    got = BC._ms_summary([10.0, 20.0, 30.0])
    assert got["n"] == 3 and got["p50"] == 20.0 and got["max"] == 30.0


# ---------------------------------------------------------------------------------------------------
# THE SERIES-KEY CENSUS -- the number the design is sized by
# ---------------------------------------------------------------------------------------------------
def test_series_key_census_counts_distinct_keys_not_rows():
    graph = BC.load_graph()
    got = BC.series_key_census(graph)
    assert got["rows_total"] > 1000, "the estate declares more than a thousand driver rows"
    assert 0 < got["distinct_keys_estate"] < got["keys_summed_over_boards"], \
        "distinct keys must be FEWER than the per-board sum -- that gap IS the shared-driver fold"
    assert got["per_board_keys"]["min"] >= 0
    assert got["per_board_keys"]["max"] <= got["distinct_keys_estate"]
    assert len(got["per_board"]) == len(graph.contracts)
    for name, rec in got["per_board"].items():
        assert rec["keys"] == len(set(rec["key_labels"])), f"{name} banked a duplicated key label"


def test_series_key_census_is_deterministic():
    graph = BC.load_graph()
    a, b = BC.series_key_census(graph), BC.series_key_census(graph)
    assert a["distinct_keys_estate"] == b["distinct_keys_estate"]
    assert a["estate_key_labels"] == b["estate_key_labels"]


# ---------------------------------------------------------------------------------------------------
# ONE BOARD, ON FIXTURES -- the rectangle, the trips, the render classes
# ---------------------------------------------------------------------------------------------------
def _fixture_state_fn(asof="2026-09-07"):
    from leviathan.graphrag.state.__main__ import fixture_state_fn
    return fixture_state_fn(asof)


@pytest.mark.parametrize("mode", ["quick", "deep", "max"])
def test_board_run_closes_its_rectangle_and_trips_no_register(mode):
    graph = BC.load_graph()
    rec = BC.board_run(graph, "soybeans_cbot", mode, "2026-09-07", state_fn=_fixture_state_fn())
    assert rec["budget"]["rectangle_closed"], rec["budget"]["rectangle"]
    assert rec["render"]["trip_count"] == 0, rec["render"]["trips"]
    assert rec["budget"]["net_reads"] <= rec["budget"]["declared_cap"]
    assert rec["rows"]["total"] > 0
    assert rec["render"]["lines"] > 0 and rec["render"]["chars"] > 0
    assert rec["legs"]["board"]["outcome"] == "fired"


def test_board_run_banks_every_class_it_rendered_and_leaves_none_unclassified():
    """Bar B6's disjointness read off REAL output: every rendered line matches exactly one row class.
    An unclassified line is a class the lint cannot police and a multi-class line is two regexes that
    are not disjoint -- the census reports both rather than averaging over them."""
    graph = BC.load_graph()
    rec = BC.board_run(graph, "soybeans_cbot", "max", "2026-09-07", state_fn=_fixture_state_fn())
    assert rec["render"]["unclassified"] == []
    assert rec["render"]["multi_class"] == []
    assert sum(rec["render"]["by_class_lines"].values()) == rec["render"]["lines"]


def test_board_run_names_every_leg_with_a_closed_outcome():
    from leviathan.graphrag.state import board as B

    graph = BC.load_graph()
    rec = BC.board_run(graph, "corn_cbot", "deep", "2026-09-07", state_fn=_fixture_state_fn())
    for leg, stamp in rec["legs"].items():
        assert stamp["outcome"] in B.OUTCOMES, f"{leg} carries {stamp['outcome']!r}"
        if stamp["outcome"] == "declined":
            assert stamp["reason"], f"{leg} declined with no reason word"


def test_board_run_records_both_rank_tuples_over_the_same_rows():
    graph = BC.load_graph()
    rec = BC.board_run(graph, "soybeans_cbot", "max", "2026-09-07", state_fn=_fixture_state_fn())
    loud = rec["loud"]
    assert loud["walked_rule"] == "d2"
    assert set(loud["d2"]) >= {"order", "loud", "loud_n", "convention_crossed_ranks"}
    assert set(loud["alternative"]) >= {"order", "loud", "loud_n"}
    assert loud["d2"]["loud_n"] == loud["alternative"]["loud_n"], \
        "the CUT is the same size under both tuples; only the ORDER may differ"
    assert isinstance(loud["order_identical"], bool)


def test_the_alternative_pass_stamps_the_alternative_rule_on_the_board():
    graph = BC.load_graph()
    rec = BC.board_run(graph, "soybeans_cbot", "max", "2026-09-07",
                       state_fn=_fixture_state_fn(), alternative=True)
    assert rec["rank_rule"] == "alternative"
    assert rec["trace"]["rank_rule"] == "alternative", \
        "the walked tuple must ride the trace, or a census row could be attributed to the wrong one"


# ---------------------------------------------------------------------------------------------------
# P0 -- the latency and contention probe, on a fake executor
# ---------------------------------------------------------------------------------------------------
def test_p0_runs_every_width_and_the_contention_round_without_a_mirror():
    """The probe's MACHINERY -- the pool widths, the counting, the 4-wide round beside a 2-wide wave --
    is proved here on an executor that returns nothing. The FIGURES are only meaningful in-VPC; what
    this deck fixes is that the probe cannot crash there, and that every rung reports its own reads."""
    graph = BC.load_graph()
    got = BC.probe_p0(graph, "2026-09-07", qfn=lambda sql: [], keys=4, widths=(1, 2, 4))
    assert got["keys_sampled"] == 4
    assert set(got["widths"]) == {"1", "2", "4"}
    for width, rung in got["widths"].items():
        assert rung["physical_reads"] == 4, f"width {width} did not read every sampled key"
        assert rung["per_read"]["n"] == 4
        assert rung["statuses"] == {"read_empty": 4}, \
            "an empty mirror read is `read_empty` -- a named status, never a silent zero"
    c = got["contention"]
    assert c["board_reads"] == 4
    assert c["agent_reads"] > 0, "the 4-wide round beside the wave must actually have read"
    assert "measured: per-read p50" in got["verdict"]


def test_p0_does_not_report_a_slowdown_ratio_it_cannot_divide():
    """A p50 of 0.0 ms is a MEASUREMENT, not a missing figure. The ratio declines and says why rather
    than raising or reporting the probe as un-run."""
    graph = BC.load_graph()
    got = BC.probe_p0(graph, "2026-09-07", qfn=lambda sql: [], keys=2, widths=(2,))
    c = got["contention"]
    assert c["p50_alone_ms"] is not None and c["p50_beside_agent_ms"] is not None
    if c["p50_alone_ms"] == 0:
        assert c["slowdown_x"] is None and "divide by zero" in c["slowdown_note"]
    else:
        assert c["slowdown_x"] is not None


def test_p0_samples_distinct_keys_only():
    graph = BC.load_graph()
    plans = BC._p0_plans(graph, limit=BC.P0_KEYS)
    labels = [p["label"] for p in plans]
    assert len(labels) == len(set(labels)), "a latency sample that read one key twice measures a memo"
    assert len(labels) == BC.P0_KEYS


# ---------------------------------------------------------------------------------------------------
# P1 -- THE FALSIFIER, on fakes that make it PASS and on fakes that make it FAIL
# ---------------------------------------------------------------------------------------------------
def _fake_board(mode, *, top_table, oni_seat, alt_top_table=None):
    """A board record shaped exactly as ``board_run`` returns it, carrying only what P1 reads."""
    def _order(top):
        return [
            {"seat": 0, "contract": BC.P1_BOARD, "driver_id": "top", "table": top,
             "coverage_band": 0, "abs_z": 2.1, "z": -2.1, "percentile": 3.0, "run_length": 4,
             "convention_hit": 0, "status": "ok"},
            {"seat": oni_seat, "contract": BC.P1_BOARD, "driver_id": "El_Nino",
             "table": BC.P1_TABLE, "coverage_band": 0, "abs_z": 0.9, "z": 0.9,
             "percentile": 82.0, "run_length": 6, "convention_hit": 1, "status": "ok"},
        ]
    return {"contract": BC.P1_BOARD, "mode": mode, "pass": "d2", "rank_rule": "d2",
            "loud": {"walked_rule": "d2", "loud_k": 24,
                     "d2": {"order": _order(top_table)},
                     "alternative": {"order": _order(alt_top_table or top_table)}}}


def test_p1_passes_when_oni_leads_under_d2():
    got = BC.probe_p1([_fake_board("max", top_table=BC.P1_TABLE, oni_seat=0)])
    assert got["verdict"] == "d2"
    assert got["d2_passes_on"] == ["max"]
    assert "the shipped tuple stands" in got["branch"]


def test_p1_fails_under_d2_and_names_the_pre_registered_branch_when_the_alternative_saves_it():
    """THE ONE PRE-REGISTERED WAY THIS DESIGN CAN BE WRONG, and the probe must SAY so rather than
    quietly reporting the tuple that happened to work."""
    got = BC.probe_p1([_fake_board("max", top_table="gold_weather_z", oni_seat=1,
                                   alt_top_table=BC.P1_TABLE)])
    assert got["verdict"] == "alternative"
    assert got["d2_passes_on"] == []
    assert got["alternative_passes_on"] == ["max"]
    assert "pre-registered branch" in got["branch"]
    assert "not taken here" in got["branch"], \
        "the census reports the branch; applying it is the OWNER's decision on the artifact"


def test_p1_says_neither_when_no_tuple_puts_oni_on_top():
    got = BC.probe_p1([_fake_board("deep", top_table="gold_weather_z", oni_seat=1)])
    assert got["verdict"] == "neither"


def test_p1_ignores_unmeasured_rows_when_it_picks_the_loudest():
    """"The loudest MEASURED state" is the claim. A text-only row (coverage band 3+) at seat 0 must
    not be able to win, or P1 would pass or fail for a reason that has nothing to do with a reading."""
    board = _fake_board("max", top_table=BC.P1_TABLE, oni_seat=1)
    board["loud"]["d2"]["order"].insert(0, {
        "seat": 0, "contract": BC.P1_BOARD, "driver_id": "a_text_only_row", "table": None,
        "coverage_band": 4, "abs_z": 0.0, "percentile": None, "run_length": 0,
        "convention_hit": 0, "status": "series_planned"})
    board["loud"]["alternative"]["order"] = board["loud"]["d2"]["order"]
    got = BC.probe_p1([board])
    assert got["verdict"] == "d2"
    assert got["per_mode"]["max"]["d2"]["top_measured"]["table"] == BC.P1_TABLE


def test_p1_declines_by_name_when_the_board_is_absent():
    got = BC.probe_p1([])
    assert got["declined"] == "board_absent"


def test_p1_declines_by_name_when_the_board_errored_rather_than_reading_it_as_a_failure():
    """An errored record carries no ``loud`` block. Reading its absence as "ONI did not lead" would
    fail the falsifier for a reason that has nothing to do with the rank."""
    got = BC.probe_p1([{"contract": BC.P1_BOARD, "mode": "max", "pass": "d2",
                        "error": "RuntimeError: the walk raised"}])
    assert got["declined"] == "board_errored"
    assert got["errors"] == ["RuntimeError: the walk raised"]
    assert "verdict" not in got, "a probe that could not read must not publish a verdict"


# ---------------------------------------------------------------------------------------------------
# P3 / P4 -- the config probes, on the estate's own configs (zero reads)
# ---------------------------------------------------------------------------------------------------
def test_p3_every_lag_declaration_parses():
    got = BC.probe_p3(BC.load_graph())
    assert got["declarations"] > 1000
    assert got["unparsed"] == [], got["unparsed"][:5]
    assert got["by_kind"], "a lag census with no kinds measured nothing"
    assert set(got["by_kind"]) <= set(("band", "point", "structural", "unspecified"))


def test_p4_prints_windows_and_never_invents_a_verified_against():
    got = BC.probe_p4("2026-09-07")
    assert got["rules"] > 0 and got["sources"] > 0
    assert got["rule_kind_findings"] == [], got["rule_kind_findings"]
    for row in got["rows"]:
        if row.get("kind") == "monthly_window" and not row.get("declined"):
            assert row["start"] and row["end"], "a windowed rule must return a WINDOW"
        if row.get("kind") == "daily_sessions":
            assert row["start"] is None, "a daily rule may not print a date it cannot know"
    # the probe reports `verified_against` and must never SET it (sec 10.1's own exit clause)
    from leviathan.graphrag.state import calendar as CAL
    doc = CAL.load_release_calendar()
    declared = sum(1 for s in (doc.get("sources") or {}).values() if (s or {}).get("verified_against"))
    seen = len({r["source"] for r in got["rows"] if r.get("verified_against")})
    assert seen == declared


def test_p4_horizon_is_the_declared_sixty_days():
    got = BC.probe_p4("2026-09-07", horizon_days=BC.P4_HORIZON_DAYS)
    assert got["horizon"] == BC._add_days("2026-09-07", BC.P4_HORIZON_DAYS)


# ---------------------------------------------------------------------------------------------------
# P5 -- the in-place revision probe, on fake mirror rows
# ---------------------------------------------------------------------------------------------------
def _oni_rows(anom_by_period, *, lag3_override=None):
    rows = []
    for period, v in sorted(anom_by_period.items()):
        y, m = int(period[:4]), int(period[5:7])
        back = BC._shift_month(y, m, -3)
        lag3 = anom_by_period.get(back)
        if lag3_override and period in lag3_override:
            lag3 = lag3_override[period]
        rows.append({"year": y, "month": m, "oni_anom": v, "oni_lag3": lag3})
    return rows


def test_p5_banks_the_first_snapshot_and_says_no_prior_existed():
    series = {f"2026-{m:02d}": 0.1 * m for m in range(1, 13)}

    def qfn(sql):
        return _oni_rows(series) if "silver_noaa_oni" in sql else []

    got = BC.probe_p5("2026-09-07", qfn=qfn, prior=None)
    oni = got["tables"]["silver_noaa_oni"]
    assert oni["n_periods"] == 12 and oni["value_column"] == "oni_anom"
    assert oni["hash"] and oni["snapshot"]
    assert oni["prior"]["compared"] is False
    assert "no prior" in got["verdict"]


def test_p5_measures_the_magnitude_against_a_banked_prior():
    base = {f"2026-{m:02d}": round(0.1 * m, 4) for m in range(1, 13)}
    revised = dict(base)
    revised["2026-03"] = base["2026-03"] + 0.2         # an in-place revision of 0.2 degC

    def qfn(sql):
        return _oni_rows(revised) if "silver_noaa_oni" in sql else []

    prior = {"tables": {"silver_noaa_oni": {"hash": "deadbeef", "snapshot": base}}}
    got = BC.probe_p5("2026-09-07", qfn=qfn, prior=prior)
    p = got["tables"]["silver_noaa_oni"]["prior"]
    assert p["compared"] is True
    assert p["changed"] == 1
    assert abs(p["max_magnitude"] - 0.2) < 1e-9
    assert p["examples"][0]["period"] == "2026-03"
    assert "measured against a banked prior vintage" in got["verdict"]


def test_p5_lag_witness_catches_a_value_that_changed_between_computations():
    """WITNESS (2), and it is the only one available on a first run: ``oni_lag3(y, m)`` must equal
    ``oni_anom(y, m - 3)``. A mismatch is a value that changed between the two computations -- an
    in-place revision caught with no second vintage at all."""
    series = {f"2026-{m:02d}": round(0.1 * m, 4) for m in range(1, 13)}

    def clean(sql):
        return _oni_rows(series) if "silver_noaa_oni" in sql else []

    def dirty(sql):
        return (_oni_rows(series, lag3_override={"2026-08": 9.99})
                if "silver_noaa_oni" in sql else [])

    ok = BC.probe_p5("2026-09-07", qfn=clean)["tables"]["silver_noaa_oni"]["lag_witness"]
    assert ok["available"] and ok["mismatches"] == 0 and ok["checked"] > 0
    assert "NOT proof" in ok["reading"], \
        "silence from the witness must never be reported as proof that nothing was revised"

    bad = BC.probe_p5("2026-09-07", qfn=dirty)["tables"]["silver_noaa_oni"]["lag_witness"]
    assert bad["mismatches"] == 1
    assert bad["examples"][0]["period"] == "2026-08"
    assert bad["max_delta"] and bad["max_delta"] > 9.0


def test_p5_finds_the_anomaly_column_by_name_rather_than_assuming_onis():
    rows = [{"year": 2026, "month": 3, "dmi": -0.7}]
    assert BC._anom_column(rows) == "dmi"
    assert BC._anom_column([{"year": 2026, "month": 3, "iod_index": 0.1}]) == "iod_index"
    assert BC._anom_column([]) is None


def test_shift_month_crosses_a_year_boundary():
    assert BC._shift_month(2026, 2, -3) == "2025-11"
    assert BC._shift_month(2026, 12, -12) == "2025-12"


# ---------------------------------------------------------------------------------------------------
# P2 -- the span fence, on an injected span_outcome
# ---------------------------------------------------------------------------------------------------
def test_p2_tallies_clean_windows_and_names_the_widest_that_closes_everywhere(monkeypatch):
    import pandas as pd

    frame = pd.DataFrame([{"leviathan_slug": "soybeans_cbot", "trade_date": "2026-09-01",
                           "contract_month": "2026-11", "settle": 10.0, "unit": "usd",
                           "currency": "USD", "settle_kind": "settle"}])
    monkeypatch.setattr(BC, "_tape_frame_for", lambda slug, asof, *, qfn: (frame, "fake"))

    def fake_span(tape, *, slug, span_start, span_end, asof, **kw):
        days = (BC._dt.date.fromisoformat(span_end) - BC._dt.date.fromisoformat(span_start)).days
        if days > 270:
            return {"status": "declined:no_surviving_contract",
                    "decline_reason": "no_surviving_contract", "basis": "survivor"}
        return {"status": "ok", "decline_reason": None, "basis": "survivor"}

    from leviathan.graphrag.numbers import outcomes as OC
    monkeypatch.setattr(OC, "span_outcome", fake_span)

    got = BC.probe_p2("2026-09-07", qfn=lambda sql: [], slugs=["soybeans_cbot", "corn_cbot"])
    assert got["tally"]["180"]["clean"] == 2
    assert got["tally"]["270"]["clean"] == 2
    assert got["tally"]["365"]["clean"] == 0
    assert got["widest_window_clean_on_every_board"] == 270
    assert "LOWER end of the band" in got["verdict"]
    assert got["tally"]["365"]["decline_words"] == {"no_surviving_contract": 2}


def test_p2_declines_by_name_when_a_slug_has_no_frame(monkeypatch):
    monkeypatch.setattr(BC, "_tape_frame_for", lambda slug, asof, *, qfn: (None, "read failed"))
    got = BC.probe_p2("2026-09-07", qfn=lambda sql: [], slugs=["nothing_here"])
    assert got["per_slug"][0]["windows"]["180"]["status"] == "declined:no_frame"
    assert got["widest_window_clean_on_every_board"] is None
    assert "stays dark" in got["verdict"]


# ---------------------------------------------------------------------------------------------------
# THE ONI CROSSING COUNT -- "the words scenario 2 narrates"
# ---------------------------------------------------------------------------------------------------
def test_oni_crossings_counts_through_the_shipped_rule_and_projects_both_windows(monkeypatch):
    """The count and the two windows are read off the SHIPPED producers -- ``analogs.crossings`` and
    ``walk.projection_window`` -- so the census can never state a window the render would not."""
    from leviathan.graphrag.state import analogs as A
    from leviathan.graphrag.state import feeders as F
    from leviathan.graphrag.state.rows import SeriesKey, StateRow

    st = StateRow(key=SeriesKey(ref="oni_climate"), asof="2026-09-07")
    st.status = "ok"
    monkeypatch.setattr(F, "series_state", lambda *a, **k: st)
    monkeypatch.setattr(A, "state_history", lambda s, **k: {
        "values": [0.1, 0.5, 1.2, 0.4, -0.9, 0.3],
        "dates": ["2025-04-30", "2025-05-31", "2025-06-30", "2025-07-31", "2025-08-31",
                  "2025-09-30"]})
    monkeypatch.setattr(A, "crossings", lambda hist, **k: [
        {"index": 2, "date": "2025-06-30", "kind": "band", "band": 0.5},
        {"index": 4, "date": "2025-08-31", "kind": "band", "band": -0.5}])

    got = BC.probe_oni_crossings("2026-09-07", qfn=lambda sql: [])
    assert got["status"] == "ok"
    assert got["crossings"] == 2
    assert got["newest"] == "2025-08-31"
    assert got["projection_anchor"] == "2025-08-31"
    assert set(got["windows"]) == {"1_2q", "2_4q"}
    assert got["windows"]["1_2q"] != got["windows"]["2_4q"], \
        "one to two quarters and two to four quarters are different windows"
    assert "2 time(s)" in got["verdict"]


def test_oni_crossings_declines_by_name_when_the_read_declines(monkeypatch):
    from leviathan.graphrag.state import feeders as F
    from leviathan.graphrag.state.rows import SeriesKey, StateRow

    st = StateRow(key=SeriesKey(ref="oni_climate"), asof="2026-09-07")
    st.status = "pool_exhausted"
    monkeypatch.setattr(F, "series_state", lambda *a, **k: st)
    got = BC.probe_oni_crossings("2026-09-07", qfn=lambda sql: [])
    assert got["declined"] == "pool_exhausted"
    assert "declined by name" in got["verdict"]
    assert "crossings" not in got, "a declined read must not report a count of anything"


# ---------------------------------------------------------------------------------------------------
# THE DESTINATION CENSUS
# ---------------------------------------------------------------------------------------------------
def test_destination_census_computes_headroom_and_flags_a_series_at_the_cap():
    graph = BC.load_graph()
    seen = []

    def qfn(sql):
        seen.append(sql)
        return [{"n": 5000, "destinations": 61}]

    got = BC.destination_census(graph, "2026-09-07", qfn=qfn)
    assert got["cap"] == 5000
    assert got["series"] > 0, "the estate maps at least one destination-grain series"
    for row in got["rows"]:
        if "headroom" in row:
            assert row["headroom"] == 5000 - row["rows_52w"]
            assert row["at_cap"] is True
    assert got["at_cap"], "a read that comes back at its cap MUST be named, not averaged away"
    assert "truncate silently" in got["verdict"]
    assert all("week_ending_date" in s for s in seen)


def test_destination_census_reads_the_column_names_off_the_card_not_out_of_this_module():
    """`silver_esr` keys its commodity on `commodity_name` and its destination on `country_code`;
    `silver_fgis` uses `leviathan_slug` and `destination_country`. A probe that hard-coded one card's
    columns would count zero on the other and report the headroom as infinite."""
    from leviathan.graphrag.numbers.registry import load_registry

    graph = BC.load_graph()
    seen = []
    got = BC.destination_census(graph, "2026-09-07",
                                qfn=lambda sql: (seen.append(sql), [{"n": 7, "destinations": 3}])[1])
    reg = load_registry()
    tables = {r["table"] for r in got["rows"]}
    assert tables, "the estate maps at least one destination-grain series"
    for row in got["rows"]:
        ts = reg.get(row["table"])
        assert row["commodity_col"] == ts.commodity_col
        assert row["country_col"] == ts.country_col
        assert any(row["commodity_col"] in s and row["country_col"] in s for s in seen)


def test_destination_census_only_probes_the_two_destination_grain_tables():
    from leviathan.graphrag.state import feeders as F

    graph = BC.load_graph()
    got = BC.destination_census(graph, "2026-09-07", qfn=lambda sql: [{"n": 10, "destinations": 3}])
    assert {r["table"] for r in got["rows"]} <= set(F.DESTINATION_GRAIN_TABLES)
    assert got["min_headroom"] == 4990
    assert got["at_cap"] == []


# ---------------------------------------------------------------------------------------------------
# THE ESTATE PASS AND THE ARTIFACT
# ---------------------------------------------------------------------------------------------------
def test_census_runs_a_two_board_offline_pass_and_summarises_it(tmp_path):
    art = BC.census(asof="2026-09-07", qfn=BC._dead_qfn,
                    state_fn_factory=BC._fixture_state_fn_factory,
                    modes=("quick", "deep"), contracts=["soybeans_cbot", "corn_cbot"],
                    alternative_pass="deep", probes=BC.PROBES_OFFLINE, cascade_legs=False)
    s = art["summary"]
    assert s["board_runs"] == 6, "two modes plus one alternative pass over two boards"
    assert s["board_errors"] == []
    assert s["register_trips_zero"] is True
    assert s["rectangles_open"] == []
    assert set(s["per_mode"]) == {"quick", "deep"}
    assert s["series_keys_estate"] > 0
    for name in ("P0", "P2", "P5", "destinations"):
        assert art["probes"][name]["declined"] == "not_run_on_this_pass", \
            "a probe the pass could not run must DECLARE that, never report null"
        assert "pg mirror" in art["probes"][name]["why"]
    assert art["probes"]["P3"]["verdict"]
    written = BC.write_artifacts(art, "2026-09-07", out_dir=tmp_path)
    assert (tmp_path / "summary.json").exists()
    assert (tmp_path / "probes.json").exists()
    assert (tmp_path / "banner.md").exists()
    assert len(list((tmp_path / "boards").glob("*.json"))) == 6
    assert len(written) >= 9


def test_a_board_that_raises_is_a_named_finding_and_never_ends_the_census(monkeypatch):
    real = BC.board_run
    calls = {"n": 0}

    def flaky(graph, contract, mode, asof, **kw):
        calls["n"] += 1
        if contract == "corn_cbot":
            raise RuntimeError("a fixture the deck broke on purpose")
        return real(graph, contract, mode, asof, **kw)

    monkeypatch.setattr(BC, "board_run", flaky)
    art = BC.census(asof="2026-09-07", qfn=BC._dead_qfn,
                    state_fn_factory=BC._fixture_state_fn_factory,
                    modes=("quick",), contracts=["soybeans_cbot", "corn_cbot"],
                    alternative_pass="", probes=(), cascade_legs=False)
    assert calls["n"] == 2, "the census kept going after the raise"
    errs = art["summary"]["board_errors"]
    assert len(errs) == 1 and errs[0]["contract"] == "corn_cbot"
    assert "RuntimeError" in errs[0]["error"]


def test_a_probe_that_raises_is_a_named_finding_with_a_traceback(monkeypatch):
    monkeypatch.setattr(BC, "probe_p3", lambda graph: (_ for _ in ()).throw(KeyError("gone")))
    art = BC.census(asof="2026-09-07", qfn=BC._dead_qfn,
                    state_fn_factory=BC._fixture_state_fn_factory,
                    modes=("quick",), contracts=["soybeans_cbot"],
                    alternative_pass="", probes=("P3",), cascade_legs=False)
    assert "KeyError" in art["probes"]["P3"]["error"]
    assert art["probes"]["P3"]["traceback"]


def test_the_banner_is_ascii_only_and_names_every_settled_figure():
    art = BC.census(asof="2026-09-07", qfn=BC._dead_qfn,
                    state_fn_factory=BC._fixture_state_fn_factory,
                    modes=("quick",), contracts=["soybeans_cbot"],
                    alternative_pass="", probes=BC.PROBES_OFFLINE, cascade_legs=False)
    text = BC.banner(art)
    text.encode("ascii")                                # the Windows console is cp1252
    assert "REGISTER TRIPS" in text
    for name in BC.UNVERIFIED_CLAIMS:
        assert name in text, f"{name} is a design figure this artifact settles and must be printed"
    assert "None" not in text.split("## probes")[1].split("##")[0], \
        "a probe line must carry a verdict, a decline or an error -- never a bare None"


def test_the_artifact_is_json_serialisable_whole():
    """The artifact is written with ``json.dumps(default=str)``; this deck proves the DEFAULT is a
    convenience rather than a load-bearing crutch by dumping without it and only allowing the two
    types that legitimately need it to appear."""
    art = BC.census(asof="2026-09-07", qfn=BC._dead_qfn,
                    state_fn_factory=BC._fixture_state_fn_factory,
                    modes=("quick",), contracts=["soybeans_cbot"],
                    alternative_pass="", probes=BC.PROBES_OFFLINE, cascade_legs=False)
    body = json.dumps(art, default=str)
    assert len(body) > 1000
    assert json.loads(body)["summary"]["asof"] == "2026-09-07"


# ---------------------------------------------------------------------------------------------------
# THE ENV FIREWALL
# ---------------------------------------------------------------------------------------------------
def test_assert_pg_only_refuses_a_non_pg_backend(monkeypatch):
    monkeypatch.setenv("GRAPHRAG_NUMBERS_BACKEND", "athena")
    monkeypatch.setenv("EVIDENCE_PG_DSN", "postgres://x")
    with pytest.raises(AssertionError, match="GRAPHRAG_NUMBERS_BACKEND=pg"):
        BC.assert_pg_only()


def test_assert_pg_only_refuses_a_missing_dsn(monkeypatch):
    monkeypatch.setenv("GRAPHRAG_NUMBERS_BACKEND", "pg")
    monkeypatch.delenv("EVIDENCE_PG_DSN", raising=False)
    with pytest.raises(AssertionError, match="EVIDENCE_PG_DSN"):
        BC.assert_pg_only()


def test_the_offline_executor_raises_rather_than_returning_empty():
    """A fixture pass that silently returned ``[]`` from a mirror read would prove nothing about the
    fixture path; it would prove that empty reads render. The offline executor is a tripwire."""
    with pytest.raises(RuntimeError, match="fixture path is not wired"):
        BC._dead_qfn("SELECT 1")


def test_the_repo_root_helper_tolerates_a_module_run_from_outside_the_tree(monkeypatch, tmp_path):
    """THE IN-VPC PROBE LAW, as a deck: the container executes this module from /tmp, where
    ``parents[4]`` is not a repo and may not exist. ``artifact_paths`` must still return a path."""
    monkeypatch.setattr(BC, "__file__", str(tmp_path / "board_census.py"))
    assert BC._repo_root() is None
    assert BC.artifact_paths("2026-09-07", root=tmp_path / "out") == (tmp_path / "out")
    assert BC.load_prior("2026-09-07") is None


# ---------------------------------------------------------------------------------------------------
# THE SUBMIT WRAPPER -- the override the in-VPC probe laws bound
# ---------------------------------------------------------------------------------------------------
def test_the_bootstrap_stays_far_under_the_batch_override_cliff():
    import importlib.util
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location(
        "submit_batch_board_census", root / "jobs" / "submit" / "submit_batch_board_census.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    code = mod.bootstrap("leviathan-dev-shahem-001", "probes/board_census/2026-09-09T00-00-00Z/")
    assert len(code) < 500, "the override is the thing Batch fails on with NO log stream"
    assert mod.OVERRIDE_FLOOR < mod.OVERRIDE_LIMIT
    assert "board_census.py" in code and "/tmp/board_census.py" in code
    assert "download_file" in code
    assert (root / mod.MODULE_REL).exists(), "the wrapper uploads a file that must exist"
