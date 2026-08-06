"""D-AM-17 -- the carry/spread stat, the S4 curve-as-calendar wiring, and the stat-mint expiry labels.

ONE change, four surfaces, and this file is the acceptance surface for all four:

  S4 WIRED. `query.series_shape` / `curve_as_calendar` / `curve_as_calendar_reason` shipped with ZERO
    production callers -- the shape of a read was measurable and nothing measured it. The shape is now
    taken at the handle mint and any TIME-AXIS stat over an interleaved read (many delivery months AND
    many sessions) refuses. Both anti-vacuity twins are here: the single-session CURVE and the
    single-expiry CALENDAR must still compute, or the guard is just an outage.
  EXPIRY LABELS ON STAT MINTS. An injected [N] row was {value, unit, knowledge_date} -- a derived price
    figure with no delivery month and no provenance kind, i.e. the bare level tables.yaml:954-963 forbids
    quoting. The labels now ride the row when they are UNAMBIGUOUS, and are OMITTED when they are not
    (that same doctrine's other half: never attach a delivery month to a row that has none).
  THE SPREAD STAT. Two NAMED expiries out of ONE single-as-of curve. Every failure is a REFUSAL, and the
    refusals are the point: a front-month inference is unavailable by construction (no front-month flag,
    no open-interest metric), so a spread whose legs were not named is declined, never guessed.
  KILL-SWITCH PARITY. The spread arm exists in the tool schema and in the system prompt TOGETHER, behind
    the one switch the stats belt already uses -- the model is never told about an arm it does not have,
    and never handed one it was not told how to call.

Pure/hermetic: no AWS, no LLM, no pg. The agent-loop tests drive a fake client with stubbed rows.
"""
from __future__ import annotations

import inspect
import json as _json
import types

import pytest

from leviathan.graphrag.numbers import agent as NA
from leviathan.graphrag.numbers import query as Q
from leviathan.graphrag.numbers import stats as ST

EOD = "silver_futures_eod"
CORN_UNIT = "US cents/bushel"

# A real corn term structure, measured shape: THIRTEEN delivery months on ONE session (the shape the
# curve12 deck rows pin). Thirteen and not a handful on purpose -- a five-row curve trips MIN_PERCENTILE_N
# and every "the curve still computes" twin below would then be passing for the wrong reason.
CURVE_MONTHS = ("2026-07", "2026-09", "2026-12", "2027-03", "2027-05", "2027-07", "2027-09",
                "2027-12", "2028-03", "2028-05", "2028-07", "2028-12", "2029-12")
CURVE_LEVELS = (417.5, 427.0, 446.0, 461.5, 470.75, 476.25, 470.5, 478.25, 489.0, 493.25, 495.0,
                502.5, 511.75)
SESSION = "2026-06-05"


def _curve_rows(session: str = SESSION, kind: str = "settlement") -> list[dict]:
    """The documented CURVE read: agg='latest' with several months named -> one row per expiry, one as-of."""
    return [{"value": str(v), "contract_month": m, "data_date": session, "knowledge_date": session,
             "unit": CORN_UNIT, "settle_kind": kind}
            for m, v in zip(CURVE_MONTHS, CURVE_LEVELS)]


def _calendar_rows(month: str = "2026-12", n: int = 22) -> list[dict]:
    """The other shape: ONE delivery month through time."""
    return [{"value": str(430.0 + i), "contract_month": month, "data_date": f"2026-06-{i + 1:02d}",
             "knowledge_date": f"2026-06-{i + 1:02d}", "unit": CORN_UNIT, "settle_kind": "settlement"}
            for i in range(n)]


def _interleaved_rows(n_sessions: int = 22) -> list[dict]:
    """The read S4 exists to refuse: every delivery month on every session, so a positional walk counts
    ROWS and is wrong by the expiry multiplicity."""
    out = []
    for d in range(1, n_sessions + 1):
        for j, m in enumerate(CURVE_MONTHS):
            out.append({"value": str(430.0 + d + j), "contract_month": m,
                        "data_date": f"2026-06-{d:02d}", "knowledge_date": f"2026-06-{d:02d}",
                        "unit": CORN_UNIT, "settle_kind": "settlement"})
    return out


def _cash_rows(n: int = 6) -> list[dict]:
    """The two CEPEA cash references: contract_month NULL BY DESIGN (instrument_kind makes it legal)."""
    return [{"value": str(1433.64 + i), "contract_month": None, "data_date": f"2026-06-{i + 1:02d}",
             "knowledge_date": f"2026-06-{i + 1:02d}", "unit": "BRL/bag"} for i in range(n)]


def _unlabelled_rows(n: int = 10) -> list[dict]:
    """A card with no delivery month and no provenance kind at all (the ~17-of-19 majority)."""
    return [{"value": str(900 + i), "knowledge_date": f"2024-{i + 1:02d}-01", "unit": "USD/mt"}
            for i in range(n)]


def _handle(rows: list[dict]) -> dict:
    """A handle in the EXACT shape the live mint builds -- assembled through the live helpers so this
    fixture cannot drift away from `agent.py`'s mint without a test here moving too."""
    vals, exps = NA._series_axis(rows)
    return {"series": vals, "expiries": exps, "kd": NA._handle_kd(rows),
            "unit": (rows[0].get("unit") if rows else None),
            "shape": Q.series_shape(rows), "labels": NA._handle_labels(rows)}


# ==================================================================================================
# 1. THE REGISTRY SURFACE -- spread joins the enum without disturbing it
# ==================================================================================================
class TestRegistrySurface:
    def test_spread_is_registered_and_maps_to_the_module_callable(self):
        assert ST.STAT_REGISTRY["spread"] is ST.spread
        assert "spread" in ST.STAT_NAMES and ST.STAT_NAMES == frozenset(ST.STAT_REGISTRY)

    def test_the_seven_pre_wave_names_all_survive(self):
        # A widening, never a rewrite: the enum is the agent's tool surface and dropping a name here is a
        # silent capability removal no other test in this file would notice.
        assert {"streak", "percentile", "zscore", "window_change", "revision_count", "extrema",
                "yoy_delta"} <= set(ST.STAT_REGISTRY)
        assert len(ST.STAT_REGISTRY) == 8

    def test_spread_passes_the_descriptive_only_fence(self):
        assert ST.is_banned_name("spread") is False
        from leviathan.graphrag import config_check as CC
        assert CC.check_stats_registry() == []

    def test_the_schema_enum_is_DERIVED_from_the_registry_not_relisted(self):
        # The one enum, in one place: a second hardcoded list is how a registered stat becomes uncallable.
        assert NA.stats_tool_schema()["input_schema"]["properties"]["stat"]["enum"] == sorted(ST.STAT_NAMES)


# ==================================================================================================
# 2. THE ARITHMETIC, HAND-COMPUTED
# ==================================================================================================
class TestSpreadArithmetic:
    def test_far_minus_near_is_hand_computed(self):
        vals, exps = NA._series_axis(_curve_rows())
        r = ST.spread(vals, exps, "2026-12", "2027-03")     # 461.5 - 446.0
        assert r["declined"] is False and r["value"] == pytest.approx(15.5)
        assert (r["near"], r["far"]) == ("2026-12", "2027-03")
        assert (r["near_val"], r["far_val"]) == (446.0, 461.5)
        assert r["n"] == 13 and r["stat"] == "spread"

    def test_the_sign_follows_the_named_legs_not_the_row_order(self):
        # The legs are selected BY NAME, so asking for the pair the other way round negates the figure --
        # and it must, or the number cited does not mean what the question asked.
        vals, exps = NA._series_axis(_curve_rows())
        fwd = ST.spread(vals, exps, "2026-12", "2027-03")["value"]
        rev = ST.spread(vals, exps, "2027-03", "2026-12")["value"]
        assert fwd == pytest.approx(-rev) and fwd > 0

    def test_it_reaches_across_the_curve_not_just_to_the_neighbour(self):
        vals, exps = NA._series_axis(_curve_rows())
        assert ST.spread(vals, exps, "2026-07", "2027-05")["value"] == pytest.approx(53.25)


# ==================================================================================================
# 3. THE FLOOR -- one family, never a second laxer constant
# ==================================================================================================
class TestSpreadFloor:
    def test_the_floor_is_INHERITED_from_the_window_change_family(self):
        assert ST.MIN_SPREAD_N == ST.MIN_WINDOW_CHANGE_N == 2
        # AM-3's rule is about how the constant is DECLARED, not about the number it happens to equal
        # today: a fresh `MIN_SPREAD_N = 2` would satisfy the equality above and still fork the family.
        src = inspect.getsource(ST)
        assert "MIN_SPREAD_N = MIN_WINDOW_CHANGE_N" in src, (
            "MIN_SPREAD_N must be declared AS the window-change floor, not as its own literal")

    def test_a_one_row_read_refuses_on_the_floor(self):
        rows = _curve_rows()[:1]
        vals, exps = NA._series_axis(rows)
        r = ST.spread(vals, exps, "2026-07", "2026-12")
        assert r["declined"] is True and r["value"] is None and r["n"] == 1
        assert f">={ST.MIN_SPREAD_N}" in r["reason"]

    def test_an_empty_read_refuses_rather_than_raising(self):
        r = ST.spread([], [], "2026-12", "2027-03")
        assert r["declined"] is True and r["n"] == 0


# ==================================================================================================
# 4. THE NAMED-EXPIRY REFUSALS -- every one a decline, never an exception
# ==================================================================================================
class TestSpreadRefusals:
    def test_a_month_absent_from_the_read_is_refused_and_the_available_ones_are_named(self):
        vals, exps = NA._series_axis(_curve_rows())
        r = ST.spread(vals, exps, "2026-12", "2030-12")
        assert r["declined"] is True and r["value"] is None
        assert "2030-12" in r["reason"] and "2027-03" in r["reason"]   # what was asked, and what there was

    def test_an_INTERLEAVED_read_is_refused_because_each_leg_is_not_one_figure(self):
        # This is "the handle is not a single-as-of curve", proven by the data rather than asserted: on a
        # multi-session read each named month lands on 22 rows, so there is no single price to difference.
        vals, exps = NA._series_axis(_interleaved_rows())
        r = ST.spread(vals, exps, "2026-12", "2027-03")
        assert r["declined"] is True and "more than one row" in r["reason"]

    def test_a_CALENDAR_read_is_refused_because_the_far_leg_was_never_read(self):
        vals, exps = NA._series_axis(_calendar_rows())
        r = ST.spread(vals, exps, "2026-12", "2027-03")
        assert r["declined"] is True and "2027-03" in r["reason"]

    def test_the_same_month_twice_is_refused(self):
        vals, exps = NA._series_axis(_curve_rows())
        r = ST.spread(vals, exps, "2026-12", "2026-12")
        assert r["declined"] is True and "same delivery month" in r["reason"]

    @pytest.mark.parametrize("near,far", [(None, "2027-03"), ("2026-12", None), ("", "2027-03"),
                                          ("2026-12", "  "), (None, None)])
    def test_an_UNNAMED_leg_is_refused_and_no_front_month_is_invented(self, near, far):
        # THE CLASS THIS WAVE EXISTS TO FORECLOSE. There is no front-month flag and no open-interest
        # metric anywhere in this lookup, so "the front month" cannot be derived -- and a nearest-listed
        # expiry silently standing in for it is the quiet substitution the card's doctrine refuses.
        vals, exps = NA._series_axis(_curve_rows())
        r = ST.spread(vals, exps, near, far)
        assert r["declined"] is True and r["value"] is None
        assert "front-month" in r["reason"]

    def test_rows_with_NO_delivery_month_are_refused_as_not_a_curve(self):
        vals, exps = NA._series_axis(_cash_rows())
        r = ST.spread(vals, exps, "2026-12", "2027-03")
        assert r["declined"] is True and "no delivery month at all" in r["reason"]

    def test_a_MISALIGNED_label_axis_is_refused_rather_than_matched_by_luck(self):
        # The axes are built in one pass so this cannot arise from the mint; it is refused anyway, because
        # the failure mode is a spread of the WRONG two contracts that looks exactly like a right answer.
        r = ST.spread([417.5, 427.0, 446.0], ["2026-07", "2026-09"], "2026-07", "2026-09")
        assert r["declined"] is True and "labels" in r["reason"]

    def test_every_refusal_shape_is_the_uniform_decline_contract(self):
        vals, exps = NA._series_axis(_curve_rows())
        for near, far in (("2026-12", "2030-12"), ("2026-12", "2026-12"), (None, "2027-03")):
            r = ST.spread(vals, exps, near, far)
            assert set(r) >= {"stat", "declined", "value", "n", "reason", "near", "far"}
            assert r["stat"] == "spread" and r["declined"] is True and r["value"] is None


# ==================================================================================================
# 5. THE UNIT FENCE -- spread is a DIFFERENCE, and D-FR-17(ii) does not reopen on it
# ==================================================================================================
class TestSpreadUnitFence:
    def test_spread_carries_its_OWN_output_unit(self):
        assert NA._STAT_UNIT["spread"] == "spread"

    def test_a_spread_ranked_inside_a_LEVEL_distribution_now_DECLINES(self):
        # The measured class: a +15.5 carry ranked in a pool of ~430-cent levels computes a 0th percentile
        # and cites it. window_change inherits the raw price unit and still falls into that hole (pinned
        # UNCOVERED in test_futures_readpath_pins); the stat added by THIS wave does not.
        handles = {"s": _handle(_calendar_rows()), "d": {"series": [15.5], "unit": "spread", "kd": None}}
        res = NA._dispatch_stat("percentile", {"series_handle": "s", "value_handle": "d"}, handles)
        assert res["declined"] is True and res["guard"] == ST.UNIT_GUARD

    def test_ANTI_VACUITY_the_hole_is_still_open_for_window_change(self):
        # Without this twin the test above reads as "the unit guard catches everything", which is exactly
        # the false comfort D-FR-17(ii) was written down to prevent.
        assert "window_change" not in NA._STAT_UNIT


# ==================================================================================================
# 6. S4 -- the curve-as-calendar guard, finally CALLED
# ==================================================================================================
TIME_AXIS_CALLS = {
    "streak": {"direction": "up"},
    "window_change": {"t1": 0, "t2": -1},
    "percentile": {},
    "zscore": {},
    "yoy_delta": {"periods": 1},
}


class TestS4Wiring:
    def test_the_shape_verdict_is_carried_on_the_minted_handle(self):
        h = _handle(_interleaved_rows())
        assert h["shape"]["n_expiries"] == 13 and h["shape"]["n_sessions"] == 22
        assert Q.curve_as_calendar(h["shape"]) is True

    @pytest.mark.parametrize("stat", sorted(TIME_AXIS_CALLS))
    def test_every_time_axis_stat_REFUSES_an_interleaved_read(self, stat):
        h = _handle(_interleaved_rows())
        res = NA._dispatch_stat(stat, {"series_handle": "s", **TIME_AXIS_CALLS[stat]}, {"s": h})
        assert res["declined"] is True and res["value"] is None
        assert res["guard"] == ST.CURVE_GUARD
        assert res["n"] == len(h["series"]), "n is the sample the stat WOULD have run over, never a 0"

    def test_the_reason_is_query_pys_own_string_rendered_from_the_MEASURED_shape(self):
        h = _handle(_interleaved_rows())
        res = NA._dispatch_stat("window_change", {"series_handle": "s", "t1": 0, "t2": -1}, {"s": h})
        assert res["reason"] == Q.curve_as_calendar_reason(h["shape"])
        assert "13 delivery months" in res["reason"] and "22 sessions" in res["reason"]

    @pytest.mark.parametrize("stat", sorted(TIME_AXIS_CALLS))
    def test_ANTI_VACUITY_TWIN_1_a_single_expiry_CALENDAR_still_computes(self, stat):
        h = _handle(_calendar_rows())
        assert h["shape"]["n_expiries"] == 1 and h["shape"]["n_sessions"] == 22
        res = NA._dispatch_stat(stat, {"series_handle": "s", **TIME_AXIS_CALLS[stat]}, {"s": h})
        assert res["declined"] is False

    def test_ANTI_VACUITY_TWIN_2_a_single_session_CURVE_still_computes(self):
        # The bare ">1 distinct contract_month" test OVER-DECLINES: this is the read the curve12 deck
        # exercises, and extrema / a rank within the curve are legitimate curve statistics over it.
        h = _handle(_curve_rows())
        assert h["shape"]["n_expiries"] == 13 and h["shape"]["n_sessions"] == 1
        assert NA._dispatch_stat("percentile", {"series_handle": "s"}, {"s": h})["declined"] is False
        assert NA._dispatch_stat("extrema", {"series_handle": "s"}, {"s": h})["declined"] is False

    def test_ANTI_VACUITY_TWIN_3_a_handle_with_NO_shape_computes_exactly_as_before(self):
        # Pre-wave byte-identity: chained stat handles and post-answer legs carry no shape, and an absent
        # shape must read as "nothing measured", never as a refusal.
        bare = {"series": [400.0 + i for i in range(30)], "unit": CORN_UNIT, "kd": None}
        got = NA._dispatch_stat("window_change", {"series_handle": "s", "t1": 0, "t2": -1}, {"s": bare})
        assert got == ST.window_change(bare["series"], 0, -1)

    def test_the_three_OUT_stats_are_out_on_purpose_and_extrema_still_computes(self):
        assert NA._TIME_AXIS_STATS == {"streak", "window_change", "percentile", "zscore", "yoy_delta"}
        for out in ("extrema", "revision_count", "spread"):
            assert out not in NA._TIME_AXIS_STATS
        h = _handle(_interleaved_rows())
        assert NA._dispatch_stat("extrema", {"series_handle": "s"}, {"s": h})["declined"] is False

    def test_spread_over_an_interleaved_read_refuses_through_its_OWN_gate(self):
        # It is out of _TIME_AXIS_STATS and still cannot be computed over that read -- by the duplicate-leg
        # refusal, whose reason says what is actually wrong with the rows.
        h = _handle(_interleaved_rows())
        res = NA._dispatch_stat("spread", {"series_handle": "s", "near_month": "2026-12",
                                           "far_month": "2027-03"}, {"s": h})
        assert res["declined"] is True and "more than one row" in res["reason"]


# ==================================================================================================
# 7. THE STAT-MINT EXPIRY LABELS
# ==================================================================================================
def _row_of(calls: list[dict]) -> dict:
    return calls[0]["rows"][0]


class TestStatMintLabels:
    def test_a_calendar_derived_figure_carries_its_expiry_AND_its_provenance_kind(self):
        h = _handle(_calendar_rows())
        res = ST.window_change(h["series"], 0, -1)
        row = _row_of(NA._stat_calls("window_change", res, {}, h["unit"], h["kd"], h["labels"]))
        assert row["contract_month"] == "2026-12" and row["settle_kind"] == "settlement"

    def test_a_CURVE_derived_figure_carries_NO_single_delivery_month(self):
        # The doctrine's other half. Five expiries went in, so the derived figure has no one month; the
        # provenance kind is unambiguous and still rides.
        h = _handle(_curve_rows())
        res = ST.extrema(h["series"])
        rows = [c["rows"][0] for c in NA._stat_calls("extrema", res, {}, h["unit"], h["kd"], h["labels"])]
        assert len(rows) == 2
        for row in rows:
            assert "contract_month" not in row and row["settle_kind"] == "settlement"

    def test_a_spread_row_names_BOTH_legs_and_never_writes_a_pair_into_contract_month(self):
        h = _handle(_curve_rows())
        res = ST.spread(h["series"], h["expiries"], "2026-12", "2027-03")
        row = _row_of(NA._stat_calls("spread", res, {}, h["unit"], h["kd"], h["labels"]))
        assert (row["near_month"], row["far_month"]) == ("2026-12", "2027-03")
        assert "contract_month" not in row, "every downstream expiry reader parses that field as a month"
        assert row["value"] == pytest.approx(15.5) and row["unit"] == "spread"

    def test_a_MIXED_provenance_kind_is_dropped_rather_than_picked(self):
        rows = _curve_rows()[:2] + [dict(r, settle_kind="session_close") for r in _curve_rows()[2:]]
        assert "settle_kind" not in NA._handle_labels(rows)

    def test_ANTI_VACUITY_a_label_less_card_mints_the_PRE_WAVE_row_exactly(self):
        h = _handle(_unlabelled_rows())
        res = ST.percentile(h["series"][-1], h["series"])
        row = _row_of(NA._stat_calls("percentile", res, {}, h["unit"], h["kd"], h["labels"]))
        assert set(row) == {"value", "unit", "knowledge_date"}

    def test_the_cash_references_get_no_expiry_label_invented_for_them(self):
        assert "contract_month" not in NA._handle_labels(_cash_rows())

    def test_the_two_axes_drop_the_SAME_rows(self):
        # The alignment guarantee the whole named-leg selection rests on: a null-valued row must vanish
        # from the label axis too, or every expiry after it names the wrong number.
        rows = _curve_rows()
        rows[1] = dict(rows[1], value=None)
        vals, exps = NA._series_axis(rows)
        assert len(vals) == len(exps) == len(CURVE_MONTHS) - 1
        assert exps == [m for m in CURVE_MONTHS if m != "2026-09"]
        assert ST.spread(vals, exps, "2026-12", "2027-03")["value"] == pytest.approx(15.5)


# ==================================================================================================
# 8. KILL-SWITCH PARITY -- the schema arm and the prompt bullet, together or not at all
# ==================================================================================================
def _stats_props() -> dict:
    return NA.stats_tool_schema()["input_schema"]["properties"]


class TestKillSwitchParity:
    def test_ON_the_schema_arm_and_the_prompt_steering_are_BOTH_present(self, monkeypatch):
        monkeypatch.setenv("GRAPHRAG_STATS_TOOL", "on")
        props = _stats_props()
        assert "spread" in props["stat"]["enum"]
        assert "near_month" in props and "far_month" in props
        sp = NA.system_prompt(NA.load_registry())
        assert "stat='spread'" in sp and "near_month" in sp and "far_month" in sp

    def test_OFF_removes_the_tool_AND_all_spread_steering_from_the_prompt(self, monkeypatch):
        monkeypatch.setenv("GRAPHRAG_STATS_TOOL", "off")
        sp = NA.system_prompt(NA.load_registry())
        assert NA.STATS_TOOL_NAME not in sp
        for token in ("stat='spread'", "near_month", "far_month", "CALENDAR SPREAD"):
            assert token not in sp

    def test_the_two_halves_ride_ONE_switch(self, monkeypatch):
        # Parity stated as a biconditional, so a future edit that moves one half behind a second flag
        # fails here rather than shipping a documented-but-absent (or present-but-undocumented) arm.
        for value, expect in (("on", True), ("off", False)):
            monkeypatch.setenv("GRAPHRAG_STATS_TOOL", value)
            sp = NA.system_prompt(NA.load_registry())
            assert ("CALENDAR SPREAD" in sp) is expect
            assert NA._stats_tool_on() is expect

    def test_the_front_month_refusal_is_stated_in_BOTH_places(self, monkeypatch):
        # The doctrine has to reach the model, not just the code: a schema that accepts two month names
        # without saying why both are required invites the model to pass one and mean "the front month".
        monkeypatch.setenv("GRAPHRAG_STATS_TOOL", "on")
        props = _stats_props()
        assert "front-month" in props["near_month"]["description"]
        assert "front month" in NA.system_prompt(NA.load_registry())


# ==================================================================================================
# 9. THE AGENT LOOP END TO END (fake client, stubbed rows -- no spend, no AWS)
# ==================================================================================================
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


def _curve_lookup(months: str = "2026-12,2027-03"):
    return _tu(NA.TOOL_NAME, {"table": EOD, "metric": "settle", "commodity": "corn_cbot",
                              "contract_month": months, "agg": "latest"}, "t1")


def _last_result(client) -> dict:
    return _json.loads(client.sent[-1]["messages"][-1]["content"][0]["content"])


class TestAgentLoop:
    def test_a_spread_turn_injects_a_LABELLED_N_row_that_value_checks_clean(self):
        from leviathan.graphrag import orchestrator as O
        rows = [r for r in _curve_rows() if r["contract_month"] in ("2026-12", "2027-03")]
        client = _FakeClient([
            _rp([_curve_lookup()]),
            _rp([_tu(NA.STATS_TOOL_NAME, {"stat": "spread", "series_handle": "L1",
                                          "near_month": "2026-12", "far_month": "2027-03"}, "t2")]),
            _rp([_txt("The December/March corn spread is 15.5 [N].")]),
        ])
        out = NA.answer_numbers("corn dec-march spread?", asof="2026-06-08", client=client,
                                query_fn=lambda sql: rows)
        stat_call = next(c for c in out["calls"] if (c.get("query") or {}).get("table") == NA.STATS_TOOL_NAME)
        row = stat_call["rows"][0]
        assert row["value"] == pytest.approx(15.5)
        assert (row["near_month"], row["far_month"]) == ("2026-12", "2027-03")
        assert row["settle_kind"] == "settlement" and row["knowledge_date"] == SESSION
        assert stat_call["stat_provenance"]["params"] == {"near_month": "2026-12", "far_month": "2027-03"}
        assert O._verify_numbers_answer(out["answer"], out["calls"])["mismatched"] == 0

    def test_an_INTERLEAVED_turn_injects_NOTHING_and_tells_the_model_how_to_re_scope(self):
        client = _FakeClient([
            _rp([_curve_lookup(",".join(CURVE_MONTHS))]),
            _rp([_tu(NA.STATS_TOOL_NAME, {"stat": "window_change", "series_handle": "L1",
                                          "t1": 0, "t2": -1}, "t2")]),
            _rp([_txt("I cannot compute that over this read.")]),
        ])
        out = NA.answer_numbers("how much has corn moved?", asof="2026-06-08", client=client,
                                query_fn=lambda sql: _interleaved_rows())
        assert [((c.get("query") or {}).get("table")) for c in out["calls"]] == [EOD]   # no [N] injected
        res = _last_result(client)
        assert res["status"] == "declined" and res["guard"] == ST.CURVE_GUARD
        assert "one delivery month" in res["reason"]

    def test_a_spread_asked_for_over_a_CALENDAR_read_is_refused_not_answered(self):
        client = _FakeClient([
            _rp([_curve_lookup("2026-12")]),
            _rp([_tu(NA.STATS_TOOL_NAME, {"stat": "spread", "series_handle": "L1",
                                          "near_month": "2026-12", "far_month": "2027-03"}, "t2")]),
            _rp([_txt("That read only covers one delivery month.")]),
        ])
        out = NA.answer_numbers("corn dec-march spread?", asof="2026-06-08", client=client,
                                query_fn=lambda sql: _calendar_rows())
        assert [((c.get("query") or {}).get("table")) for c in out["calls"]] == [EOD]
        assert _last_result(client)["status"] == "declined"

    def test_an_UNNAMED_leg_is_refused_at_the_loop_and_no_figure_is_minted(self):
        client = _FakeClient([
            _rp([_curve_lookup()]),
            _rp([_tu(NA.STATS_TOOL_NAME, {"stat": "spread", "series_handle": "L1",
                                          "far_month": "2027-03"}, "t2")]),
            _rp([_txt("I need both delivery months.")]),
        ])
        out = NA.answer_numbers("corn carry?", asof="2026-06-08", client=client,
                                query_fn=lambda sql: _curve_rows())
        assert [((c.get("query") or {}).get("table")) for c in out["calls"]] == [EOD]
        res = _last_result(client)
        assert res["status"] == "declined" and "front-month" in res["reason"]
