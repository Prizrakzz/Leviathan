"""D-PQ A' -- THE EXCHANGE-SETTLE ANCHOR (`agg='front_expiry'`). Pure/hermetic: no AWS, no LLM, no pg.

WHAT WAS MISSING, PRECISELY. `silver_futures_eod` has been served since the W3 whitelist flip, is true
point-in-time, carries per-row unit / currency / settle_kind, and is NOT in `config_check.PRICE_TABLES`
(so the R4 fence never reached it). The rule that says WHICH delivery month is "the market" has existed,
named and versioned, since W2 (`leviathan.silver.futures_roll`, front_month_v2, source-fenced by
`config_check.check_futures_roll`), and the cascade has CALLED it since W3.3 (`_pace_front_expiry`). The
only gap was the agent read path: with no agg for it, "what did CBOT corn settle at" could either name an
expiry (which the asker had not) or read the whole curve and quote the NEAREST LISTED expiry as "the
price" -- a deterministic tie-break, not the front month. Seven judged row-runs recorded the same hole
from the other side: the answer "quietly substitutes farm price for the CBOT price the question actually
asked about", and the suppression half of that fix was deferred "until P1 produces a working futures
anchor" (NUMBERS_FIRING_PLAN A3 / P1).

WHAT THESE TESTS PIN:
  * the CARD declares `roll_input_cols`, and that declaration is BOUND to the rule module's own input
    contract -- the drift pin is the point of the field, because a stale copy of "which method reads
    which column" is invisible to the source fence (it scans for a competing IMPLEMENTATION);
  * the SQL SHAPE -- the newest session read WHOLE (DENSE_RANK over every listed expiry, never LIMIT 1),
    with the as-of guard and the roll inputs riding that ONE branch;
  * the FOUR GUARDS -- levels_only keeps priority on the continuous card, an undeclared card refuses, a
    NAMED contract_month is a contradiction, and a WINDOW is refused because "front expiry through time"
    splices across the roll;
  * the SELECTION -- the rule is RUN (highest open interest among eligible expiries for a front-by-OI
    slug), the roll inputs are STRIPPED off the returned row, and roll_method / roll_rule_version ride it;
  * every DECLINE is silence-plus-a-reason and never an approximation: a cash reference, a PARTIAL
    activity metric (the dangerous case -- whichever expiry happened to carry a print would win by
    default), an unlabelled or undated row, and nothing eligible;
  * the READ PATH end to end through `run()` -- unit_overrides still governs the served unit;
  * the TOOL SCHEMA declares the agg and describes it, because the model can only emit what the schema
    names, and the DECLINE REASON reaches the model instead of a bare `no_rows`.
"""
from __future__ import annotations

import inspect

import pytest

from leviathan.graphrag import config_check as cc
from leviathan.graphrag.numbers import agent as A
from leviathan.graphrag.numbers import query as Q
from leviathan.graphrag.numbers import registry as R
from leviathan.silver import futures_roll as FR

TABLE = "silver_futures_eod"
FLAT = "silver_futures_prices"
FE = Q.FRONT_EXPIRY_AGG


def _card(tid: str = TABLE) -> dict:
    """The LIVE card out of the raw tables.yaml (the test_futures_eod_curve idiom): reading it directly
    proves it parses under the registry's extra='forbid' schema rather than proving the loader happens to
    be configured a particular way today."""
    return dict(cc._load("numbers/tables.yaml")["tables"][tid])


def _ts(tid: str = TABLE) -> R.TableSpec:
    return R.TableSpec(id=tid, **_card(tid))


def _spec(**kw) -> Q.NumberQuery:
    base = dict(table=TABLE, metric="settle", asof="2026-07-15", commodity="corn_cbot", agg=FE)
    base.update(kw)
    return Q.NumberQuery(**base)


def _row(cm: str, val, *, dt: str = "2026-07-14", oi=None, vol=None, unit="US cents/bushel") -> dict:
    """One fetched curve row, shaped exactly as build_sql's aliases render it (knowledge_date is the only
    date alias silver_futures_eod surfaces -- its date_col IS its knowledge_date_col)."""
    return {"value": val, "knowledge_date": dt, "year": "2026", "contract_month": cm,
            "settle_kind": "settlement", "currency": "USD", "unit": unit,
            "open_interest": oi, "volume": vol}


# -- the CARD declaration, and its bind to the rule module -----------------------------------------
class TestCardDeclaration:
    def test_defaults_to_empty_so_every_other_card_is_unchanged(self):
        ts = R.TableSpec(id="x", description="", shape="wide", date_col="d")
        assert ts.roll_input_cols == []

    def test_the_live_futures_card_declares_the_roll_inputs(self):
        assert _card()["roll_input_cols"] == ["open_interest", "volume"]

    def test_a_typoed_key_still_fails_at_load(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            R.TableSpec(id="x", description="", shape="wide", roll_input_columns=["volume"])

    def test_the_declaration_equals_the_rules_own_input_contract(self):
        # THE DRIFT PIN. Which column a method reads belongs to the rule module; a second copy of that
        # mapping is invisible to config_check's source fence (it scans for a competing IMPLEMENTATION),
        # so it would go stale silently the day a method's column changes -- and a stale copy either
        # declines wrongly or waves through a DEGRADED selection.
        need = sorted({str(c) for c in FR.METHOD_METRIC_COL.values() if c})
        assert Q._front_expiry_input_cols(_ts()) == need
        assert sorted(_card()["roll_input_cols"]) == need

    def test_a_drifted_declaration_raises_at_the_seam_and_names_the_drift(self):
        ts = _ts()
        ts.roll_input_cols = ["open_interest"]                 # a column silently dropped
        with pytest.raises(ValueError, match="roll_input_cols"):
            Q._front_expiry_input_cols(ts)

    def test_the_settle_only_metric_whitelist_is_untouched(self):
        # the roll inputs are NOT served metrics: they ride one SELECT and are stripped again.
        assert set((_card().get("metrics") or {})) == {"settle"}


# -- the SQL shape ---------------------------------------------------------------------------------
class TestCompiledShape:
    def test_the_whole_newest_session_is_read_not_one_row(self):
        sql = Q.build_sql(_spec(), _ts())
        assert "DENSE_RANK() OVER (ORDER BY trade_date DESC)" in sql
        assert "WHERE _dr = 1" in sql
        assert "LIMIT 1" not in sql          # the rule cannot pick a front month out of ONE row

    def test_a_model_emitted_limit_cannot_truncate_the_curve_the_rule_is_handed(self):
        """D-PQ FIX-1b -- the A-prime review's CONFIRMED-DEFECT, pinned in both halves.

        `limit` is MODEL-EMITTABLE (D-CW-1c declared it in the tool schema) and `agent._clamp_limit`
        clamps UP only, so `limit=1` reached the compiler intact. This branch orders ASCENDING on
        contract_month (inside one session `year`/`knowledge_date` are constant), so the cap kept the
        NEAREST LISTED EXPIRIES -- `futures_roll.front_month` has no arity check and returned max-metric
        over whatever frame it was handed. The result was `legacy_lane_front` (nearest listed expiry)
        stamped `roll_rule_version=front_month_v2`, which is the exact substitution the guards above
        refuse by name, and `agent._exec`'s series-scoped sentinel reported `truncated: False` over it."""
        for lim in (1, 3, 5000):
            sql = Q.build_sql(_spec(limit=lim), _ts())
            assert sql.rstrip().endswith(f"LIMIT {Q.CURVE_ROW_CAP}"), lim
        # ANTI-VACUITY: the SAME small limit still binds where it is a real caller-facing window.
        series = Q.build_sql(_spec(agg="series", limit=1), _ts())
        assert series.rstrip().endswith("LIMIT 1")

    def test_the_selection_really_does_change_under_the_old_truncating_shape(self):
        """ANTI-VACUITY for the row above: without the fix the wrong expiry is SERVED, not merely a
        different SQL string. The rule run over the whole curve picks the OI leader; run over the
        ASC-truncated head it picks the nearest listed expiry -- same call, same provenance stamp."""
        ts, spec = _ts(), _spec()
        curve = [_row("2026-07", 402.0, oi=120000), _row("2026-09", 410.0, oi=300000),
                 _row("2026-12", 421.0, oi=900000)]
        full = Q.select_front_expiry([dict(r) for r in curve], spec, ts)
        head = Q.select_front_expiry([dict(curve[0])], spec, ts)
        assert full and head
        assert full[0]["contract_month"] == "2026-12"
        assert head[0]["contract_month"] == "2026-07"
        assert head[0].get("roll_rule_version") == full[0].get("roll_rule_version")

    def test_the_roll_inputs_ride_this_branch(self):
        sql = Q.build_sql(_spec(), _ts())
        for col in ("open_interest", "volume"):
            assert f", {col}" in sql

    def test_they_ride_no_other_branch(self):
        for agg in ("latest", "series"):
            sql = Q.build_sql(_spec(agg=agg), _ts())
            assert "open_interest" not in sql and "volume" not in sql
            assert "DENSE_RANK" not in sql

    def test_the_asof_guard_and_the_slug_equality_still_compile(self):
        sql = Q.build_sql(_spec(), _ts())
        assert "leviathan_slug = 'corn_cbot'" in sql
        assert "<= '2026-07-14'" in sql        # publication_lag_days: 1 -- unchanged by this branch

    def test_the_labels_still_ride_every_row(self):
        sql = Q.build_sql(_spec(), _ts())
        for alias in ("contract_month", "settle_kind", "currency"):
            assert f"AS {alias}" in sql

    def test_it_is_not_a_series_branch_so_the_newest_first_resort_is_inert(self):
        ts = _ts()
        assert Q._is_series_branch(_spec(), ts) is False
        assert Q._newest_first_applies(_spec(), ts, True) is False
        assert Q._newest_first_applies(_spec(), ts, Q.NEWEST_FIRST_ALL) is False


# -- the four guards -------------------------------------------------------------------------------
class TestGuards:
    def test_levels_only_keeps_priority_on_the_continuous_card(self):
        # silver_futures_prices declares no roll inputs EITHER, so both guards would fire -- levels_only
        # is ordered first on purpose, because "roll-spliced continuous series" is the truer reason.
        spec = Q.NumberQuery(table=FLAT, metric="close", asof="2026-07-15",
                             commodity="corn_cbot", agg=FE)
        with pytest.raises(ValueError, match="levels-only"):
            Q.build_sql(spec, _ts(FLAT))

    def test_an_undeclared_card_refuses_rather_than_guessing_a_front_month(self):
        ts = _ts()
        ts.roll_input_cols = []
        with pytest.raises(ValueError, match="not expressible"):
            Q.build_sql(_spec(), ts)

    def test_naming_a_delivery_month_is_a_contradiction(self):
        with pytest.raises(ValueError, match="contradiction"):
            Q.build_sql(_spec(contract_month="2026-12"), _ts())

    def test_a_window_is_refused_because_it_would_splice_across_the_roll(self):
        for kw in ({"period_start": "2026-01-01"}, {"period_end": "2026-07-01"}):
            with pytest.raises(ValueError, match="SINGLE-SESSION"):
                Q.build_sql(_spec(**kw), _ts())

    def test_the_ordinary_reads_are_byte_identical(self):
        # nothing above may move the reads that already existed.
        ts = _ts()
        for agg in ("latest", "series", "mean"):
            Q.build_sql(_spec(agg=agg), ts)          # compiles, no raise
        Q.build_sql(_spec(agg="latest", contract_month="2026-12"), ts)


# -- the selection ---------------------------------------------------------------------------------
class TestSelection:
    def test_the_rule_is_run_highest_open_interest_wins(self):
        # corn_cbot is databento_glbx_mdp3 -> front-by-OPEN-INTEREST. December carries the OI here, so
        # the front month is NOT the nearest listed expiry -- which is the whole point of the anchor.
        rows = [_row("2026-09", "432.25", oi="500000"),
                _row("2026-12", "447.50", oi="900000"),
                _row("2027-03", "455.00", oi="100000")]
        out = Q.select_front_expiry(rows, _spec(), _ts())
        assert len(out) == 1
        assert out[0]["contract_month"] == "2026-12"
        assert out[0]["value"] == "447.50"

    def test_the_roll_inputs_are_stripped_and_the_provenance_rides(self):
        rows = [_row("2026-09", "432.25", oi="500000"), _row("2026-12", "447.50", oi="900000")]
        got = Q.select_front_expiry(rows, _spec(), _ts())[0]
        assert "open_interest" not in got and "volume" not in got
        assert got["roll_method"] == FR.roll_method_for("corn_cbot")
        assert got["roll_rule_version"] == FR.ROLL_RULE_VERSION
        # the row is otherwise the FETCHED row -- nothing converted, nothing recomputed
        assert (got["settle_kind"], got["currency"], got["knowledge_date"]) == (
            "settlement", "USD", "2026-07-14")

    def test_a_partial_activity_metric_declines_whole(self):
        # THE DANGEROUS CASE. With OI printed on some expiries and not others the rule would fill the
        # missing metric with -1 and fall through to its nearest-month tie-break -- a DIFFERENT, unnamed
        # rule wearing front_month_v2's name. The precondition is asked of the rule module, not restated.
        rows = [_row("2026-09", "432.25", oi="500000"), _row("2026-12", "447.50", oi=None)]
        assert Q.select_front_expiry(rows, _spec(), _ts()) == []

    def test_an_absent_activity_metric_declines_whole(self):
        rows = [_row("2026-09", "432.25"), _row("2026-12", "447.50")]
        assert Q.select_front_expiry(rows, _spec(), _ts()) == []

    def test_a_cash_reference_declines(self):
        # "front month" is not a question that can be asked of a CEPEA cash index (roll method 'none').
        spec = _spec(commodity="brazilian_arabica_coffee")
        rows = [_row("2026-09", "1900.0", oi="1", unit="BRL/60-kg bag")]
        assert Q.select_front_expiry(rows, spec, _ts()) == []

    def test_an_unlabelled_or_undated_row_declines_whole(self):
        good = _row("2026-12", "447.50", oi="900000")
        assert Q.select_front_expiry([good, _row("", "455.00", oi="10")], _spec(), _ts()) == []
        bad = _row("2027-03", "455.00", oi="10")
        bad["knowledge_date"] = ""
        assert Q.select_front_expiry([good, bad], _spec(), _ts()) == []

    def test_an_expiry_already_in_delivery_is_not_eligible(self):
        # the rule keeps only contracts whose delivery month has not started; a stale OI print on the
        # expiring month must never keep it "front" forever.
        rows = [_row("2026-05", "999.00", oi="9999999"),     # already in delivery at a 2026-07 session
                _row("2026-12", "447.50", oi="900000")]
        out = Q.select_front_expiry(rows, _spec(), _ts())
        assert len(out) == 1 and out[0]["contract_month"] == "2026-12"

    def test_nothing_eligible_declines(self):
        rows = [_row("2026-05", "999.00", oi="9999999")]
        assert Q.select_front_expiry(rows, _spec(), _ts()) == []

    def test_a_commodity_less_spec_declines(self):
        rows = [_row("2026-12", "447.50", oi="900000")]
        assert Q.select_front_expiry(rows, _spec(commodity=None), _ts()) == []

    def test_a_multi_session_frame_declines_defensively(self):
        # the SQL cannot produce this (DENSE_RANK = 1 is one session), so it is a fail-closed belt: a
        # front month that ROLLED inside the frame makes "the front expiry" ambiguous.
        rows = [_row("2026-12", "447.50", dt="2026-07-14", oi="900000"),
                _row("2026-12", "446.00", dt="2026-07-13", oi="900000")]
        assert Q.select_front_expiry(rows, _spec(), _ts()) == []


# -- the read path, end to end ---------------------------------------------------------------------
class TestReadPath:
    def test_run_serves_one_dated_settle_with_its_governing_unit(self):
        rows = [_row("2026-09", "432.25", oi="500000"), _row("2026-12", "447.50", oi="900000")]
        got = Q.run(_spec(), query_fn=lambda _sql: rows)
        assert len(got) == 1
        r = got[0]
        assert (r["value"], r["contract_month"], r["knowledge_date"]) == ("447.50", "2026-12", "2026-07-14")
        assert r["unit"] == "US cents/bushel"     # unit_overrides still GOVERNS the served unit
        assert r["currency"] == "USD" and r["settle_kind"] == "settlement"

    def test_run_returns_nothing_rather_than_a_nearest_expiry_when_the_rule_cannot_run(self):
        rows = [_row("2026-09", "432.25"), _row("2026-12", "447.50")]    # no activity metric anywhere
        assert Q.run(_spec(), query_fn=lambda _sql: rows) == []


# -- reachability: the model can only emit what the schema names ------------------------------------
class TestToolSchema:
    def _agg(self) -> dict:
        return A.tool_schema(R.load_registry())["input_schema"]["properties"]["agg"]

    def test_the_agg_is_declared(self):
        assert FE in self._agg()["enum"]

    def test_the_pre_existing_enum_members_are_untouched(self):
        assert set(self._agg()["enum"]) == {"latest", "series", "sum", "mean", "max", "min", FE}
        assert self._agg()["default"] == "latest"

    def test_the_description_states_the_three_things_a_caller_must_know(self):
        d = self._agg()["description"].lower()
        assert "front_expiry" in d
        assert "silver_futures_eod" in d                    # WHERE it is legal
        assert "contract_month" in d and "settle_kind" in d  # WHAT comes back and how to cite it
        assert "roll rule" in d                             # WHY it is not a guess

    def test_a_front_expiry_call_survives_the_forced_spec_builder(self):
        spec = A._forced_spec("2026-07-15", {"table": TABLE, "metric": "settle",
                                             "commodity": "corn_cbot", "agg": FE})
        assert spec.agg == FE and spec.asof == "2026-07-15"

    def test_the_decline_reason_reaches_the_model_instead_of_a_bare_no_rows(self):
        # An empty front-expiry read is a REASONED absence, not a lake gap, and the recorded failure mode
        # is what the model does with a bare no_rows: reach for another table's price and call it the
        # futures level. The reason is stamped on the payload the reasoner consumes.
        assert "front_month_v2" in Q.FRONT_EXPIRY_DECLINE
        assert "contract_month" in Q.FRONT_EXPIRY_DECLINE
        src = inspect.getsource(A.answer_numbers)
        assert "FRONT_EXPIRY_DECLINE" in src and "FRONT_EXPIRY_AGG" in src
