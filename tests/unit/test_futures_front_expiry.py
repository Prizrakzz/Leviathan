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

    def test_a_partial_activity_metric_never_serves_as_the_named_rule(self):
        # THE DANGEROUS CASE. With OI printed on some expiries and not others the rule would fill the
        # missing metric with -1 and fall through to its nearest-month tie-break -- a DIFFERENT, unnamed
        # rule wearing front_month_v2's name. The precondition is asked of the rule module, not restated.
        # RE-BANKED (09-23 fix round, CONTRACT C12): the named rule STILL refuses this frame -- no row is
        # stamped open_interest or front_month_v2 -- and the DECLARED cycle fallback answers instead,
        # under its own method and version, saying how many candidates carried the primary metric.
        rows = [_row("2026-09", "432.25", oi="500000"), _row("2026-12", "447.50", oi=None)]
        out = Q.select_front_expiry(rows, _spec(), _ts())
        assert len(out) == 1
        r = out[0]
        assert r["roll_method"] == Q.CYCLE_FALLBACK_METHOD
        assert r["roll_method"] not in Q.ROLL_METHODS_FRONT
        assert r["roll_rule_version"] == Q.CYCLE_FALLBACK_VERSION != FR.ROLL_RULE_VERSION
        assert r["contract_month"] == "2026-09"      # the nearest delivery NOT in delivery at a July session
        assert r["roll_method_fallback"] == "open_interest->cycle_nearest_eligible"
        assert r["roll_inputs_absent"] == "1 of 2 eligible candidates carried no open_interest"

    def test_an_absent_activity_metric_serves_the_declared_fallback_and_never_the_rules_name(self):
        rows = [_row("2026-09", "432.25"), _row("2026-12", "447.50")]
        out = Q.select_front_expiry(rows, _spec(), _ts())
        assert [r["contract_month"] for r in out] == ["2026-09"]
        assert out[0]["roll_method"] == Q.CYCLE_FALLBACK_METHOD
        assert "open_interest" not in out[0] and "volume" not in out[0]      # inputs stripped as ever

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

    def test_run_never_serves_a_nearest_expiry_under_the_rules_name_when_the_rule_cannot_run(self):
        # RE-BANKED (09-23, C12): the read serves the DECLARED fallback, never the rule's own method.
        rows = [_row("2026-09", "432.25"), _row("2026-12", "447.50")]    # no activity metric anywhere
        got = Q.run(_spec(), query_fn=lambda _sql: rows)
        assert [(r["contract_month"], r["roll_method"]) for r in got] == [
            ("2026-09", Q.CYCLE_FALLBACK_METHOD)]
        assert got[0]["unit"] == "US cents/bushel"                          # unit_overrides still govern

    def test_the_selected_expiry_survives_all_the_way_into_the_writers_numbers_panel(self):
        """D-PQ RENDER, END TO END -- the half the A' wave shipped without.

        The rule ran, the row came back correct, and the writer still quoted a bare level (dpq_probe_v1
        row 1: `expiry_labeled` and `unit_present` both FAILED on a served read). The panel the hybrid
        writer actually reads is `orchestrator._numbers_block` -> `citations.render`, so this pins the
        WHOLE path -- SQL rows in, prompt text out -- rather than trusting that a correct row implies a
        correct prompt. It is exactly the seam where the delivery month was being dropped: on this agg
        the expiry is not in the query at all, because the roll rule chose it."""
        from leviathan.graphrag import orchestrator as ORCH
        rows = [_row("2026-09", "432.25", oi="500000"), _row("2026-12", "447.50", oi="900000")]
        served = Q.run(_spec(), query_fn=lambda _sql: rows)
        panel = ORCH._numbers_block([{"query": _spec().model_dump(exclude_none=True),
                                      "rows": served, "status": "ok"}])
        assert "2026-12" in panel                    # WHICH expiry the anchor picked
        assert "US cents/bushel" in panel            # the exchange unit (ten currencies, no conversion)
        assert "exchange settlement" in panel        # what KIND of print it is
        assert "447.50" in panel or "447.5" in panel


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

    def test_the_card_forbids_quoting_a_settle_without_its_delivery_month(self):
        # D-PQ RENDER (2026-08-07). The read was CORRECT and the answer still quoted a bare level: the
        # anchor picks the expiry FOR the writer, so the card has to say out loud that the picked expiry
        # is not optional decoration. The three-part rule binds front_expiry at least as hard as a
        # named-month read, and the card must say THAT, not just "never quote a level as the price".
        notes = " ".join(str(_card()["notes"]).split()).lower()
        assert "three-part quote is mandatory" in notes
        assert "delivery month" in notes and "unit" in notes
        assert "unattributable" in notes          # the remedy when a label is missing from the row

    def test_the_decline_reason_reaches_the_model_instead_of_a_bare_no_rows(self):
        # An empty front-expiry read is a REASONED absence, not a lake gap, and the recorded failure mode
        # is what the model does with a bare no_rows: reach for another table's price and call it the
        # futures level. The reason is stamped on the payload the reasoner consumes.
        assert "front_month_v2" in Q.FRONT_EXPIRY_DECLINE
        assert "contract_month" in Q.FRONT_EXPIRY_DECLINE
        src = inspect.getsource(A.answer_numbers)
        assert "FRONT_EXPIRY_DECLINE" in src and "FRONT_EXPIRY_AGG" in src


# ==================================================================================================
# OI-GAP REMEDIES (2026-09-07) -- R0 / R1 / R2, each behind its own flag, all DEFAULT OFF.
#
# THE DEFECT, IN ONE PARAGRAPH. `front_month_inputs_present` refuses a session whose roll metric is
# missing on ANY candidate row. On the GLBX tape that refusal fires in two distinct shapes and each
# arm below is one remedy for one shape:
#   PARTIAL   -- the expiring month carries no open interest on its LAST trading day (a market fact,
#                measured on all five partial-OI sessions since 2025, every one an expiry Friday),
#                and palm's 61-month listing strip carries open interest on only its nearest ~14
#                months. The metric is absent on SOME rows; the rule can still be decided by a real
#                print, because the -1 fill sorts BELOW every real one.
#   ALL-BLANK -- the whole session's open interest has not arrived yet (CME publishes stat_type 9 the
#                morning AFTER the session, so the newest session of every payload lands with settle
#                and NULL open interest and heals on the next fire). No row carries the primary
#                metric at all, and the fallback metric is the only remedy.
# The owner's live turn (as-of 2026-09-07, soybeans, "the record carries no front-month soybean
# settlement for this as-of at all") is the ALL-BLANK shape on the 2026-09-04 session.
# ==================================================================================================
def _sess(dt: str, shape):
    """The real session shapes, as build_sql's aliases render them."""
    return [_row(cm, v, dt=dt, oi=oi, vol=vol) for cm, v, oi, vol in shape]


# The REAL 2026-09-04 corn session's SHAPE, on 12 of its 13 expiries: measured 13 rows, 13 settles,
# open_interest NULL on all 13, volume present on all 13. The 13th expiry is omitted because it
# changes nothing this pin asserts -- the defect is that the primary metric is absent on the WHOLE
# session and the fallback metric is present on the whole session, and both hold at 12 as at 13.
# Below it, the REAL clean 2026-09-03 session (12 rows, 12 settles, neither metric missing).
CORN_0904 = [("2026-09", "512.00", None, "75"), ("2026-12", "536.75", None, "161637"),
             ("2027-03", "552.25", None, "35213"), ("2027-05", "559.75", None, "17072"),
             ("2027-07", "562.00", None, "12751"), ("2027-09", "534.75", None, "2744"),
             ("2027-12", "536.25", None, "5737"), ("2028-03", "546.75", None, "466"),
             ("2028-05", "552.00", None, "144"), ("2028-07", "554.00", None, "56"),
             ("2028-09", "515.50", None, "5"), ("2028-12", "514.25", None, "120")]
CORN_0903 = [("2026-09", "515.25", "1461", "186"), ("2026-12", "540.75", "992940", "289479"),
             ("2027-03", "556.00", "369270", "53427"), ("2027-05", "563.25", "137028", "20325"),
             ("2027-07", "566.00", "132489", "17424"), ("2027-09", "537.25", "54032", "4293"),
             ("2027-12", "538.75", "94135", "9940"), ("2028-03", "548.50", "5278", "305"),
             ("2028-05", "553.50", "1177", "163"), ("2028-07", "555.50", "1781", "46"),
             ("2028-09", "515.75", "412", "3"), ("2028-12", "514.25", "2338", "57")]
# the REAL partial shape (2026-03-13 corn): the expiring March contract carries NO open interest on
# its last trading day, every other expiry does.
CORN_0313 = [("2026-03", "452.50", None, "85"), ("2026-05", "462.00", "410000", "51000"),
             ("2026-07", "470.25", "180000", "22000"), ("2026-12", "489.00", "260000", "31000")]


@pytest.fixture()
def flags(monkeypatch):
    def _set(**kw):
        for name, var in (("partial", Q._FE_PARTIAL_FLAG), ("fallback", Q._FE_FALLBACK_FLAG),
                          ("walkback", Q._FE_WALKBACK_FLAG), ("metrics", Q._FE_METRICS_FLAG)):
            monkeypatch.setenv(var, "on" if kw.get(name) else "off")
    return _set


class TestOIGapRed:
    def test_red1_the_owners_turn_the_all_blank_session(self, flags):
        """RED-1. as-of 2026-09-07, the real 2026-09-04 session. Dark at HEAD; served under R1, on
        the NEWEST session, naming the fallback that ran."""
        rows = _sess("2026-09-04", CORN_0904)
        sp = _spec(asof="2026-09-07")
        flags()
        # HEAD: dark. 09-23 (C12): the named rule is still dark and the DECLARED cycle fallback answers --
        # December, because September is inside its own delivery month on a September session.
        dark = Q.select_front_expiry(rows, sp, _ts())
        assert [(r["contract_month"], r["roll_method"]) for r in dark] == [
            ("2026-12", Q.CYCLE_FALLBACK_METHOD)]
        flags(fallback=True)
        out = Q.select_front_expiry(rows, sp, _ts())
        assert len(out) == 1
        r = out[0]
        assert r["front_expiry_session"] == "2026-09-04"
        assert r["sessions_withheld"] == 0
        assert r["roll_method"] == FR.METHOD_VOLUME
        assert r["roll_method_fallback"] == "open_interest->volume"
        assert r["roll_rule_version"] == FR.ROLL_RULE_VERSION
        assert r["contract_month"] == "2026-12"      # the volume leader among eligible expiries
        assert r["value"] == "536.75"
        assert "roll_inputs_partial" not in r        # an ALL-blank frame is not a partial one

    def test_red1_soybeans_the_owner_named_that_board(self, flags):
        flags(fallback=True)
        out = Q.select_front_expiry(_sess("2026-09-04", CORN_0904),
                                    _spec(asof="2026-09-07", commodity="soybeans_cbot"), _ts())
        assert len(out) == 1 and out[0]["roll_method_fallback"] == "open_interest->volume"

    def test_red2_the_partial_frame_is_decided_by_a_real_print_not_by_a_fallback(self, flags):
        """RED-2, CORRECTED BY MEASUREMENT. The first cut of this design walked BACK a session here.
        It does not need to: the row missing open interest is the EXPIRING month on its last trading
        day, and -1 sorts below every real print, so that row cannot win. R0 serves the SAME session
        under the PRIMARY metric, at zero staleness, and STAMPS the partial condition on the row."""
        rows = _sess("2026-03-13", CORN_0313)
        sp = _spec(asof="2026-03-16")
        # HEAD: dark, and R1 alone still refuses it. 09-23 (C12): the named rule is still refused on
        # both, and the DECLARED fallback names May -- March is inside its own delivery month.
        for kw in ({}, {"fallback": True}):
            flags(**kw)
            got = Q.select_front_expiry(rows, sp, _ts())
            assert [(r["contract_month"], r["roll_method"]) for r in got] == [
                ("2026-05", Q.CYCLE_FALLBACK_METHOD)], kw
        flags(partial=True)
        out = Q.select_front_expiry(rows, sp, _ts())
        assert len(out) == 1
        r = out[0]
        assert r["roll_method"] == FR.METHOD_OPEN_INTEREST           # the PRIMARY decided it
        assert "roll_method_fallback" not in r                       # never a fallback when decided
        assert r["roll_inputs_partial"] == "1 of 4 eligible candidates carried no open_interest"
        assert r["sessions_withheld"] == 0 and r["front_expiry_session"] == "2026-03-13"
        assert r["contract_month"] == "2026-05"      # the OI leader, not the nearest month

    def test_the_selection_collapsing_to_the_tie_break_is_still_refused(self, flags):
        """The failure `front_month_inputs_present` exists to catch is UNTOUCHED: when NO eligible
        candidate carries either metric, the -1 fill would let the nearest-month tie-break decide --
        `legacy_lane_front` wearing `front_month_v2`'s name -- and every arm refuses it."""
        rows = _sess("2026-09-04", [(cm, v, None, None) for cm, v, _, _ in CORN_0904])
        sp = _spec(asof="2026-09-07")
        # RE-BANKED (09-23, C12): under EVERY arm the named rule still refuses -- no pick is ever stamped
        # open_interest / volume / front_month_v2 -- and the one row served is the DECLARED fallback.
        for kw in ({}, {"partial": True}, {"fallback": True},
                   {"partial": True, "fallback": True, "walkback": True}):
            flags(**kw)
            got = Q.select_front_expiry(rows, sp, _ts())
            assert [(r["contract_month"], r["roll_method"], r["roll_rule_version"]) for r in got] == [
                ("2026-12", Q.CYCLE_FALLBACK_METHOD, Q.CYCLE_FALLBACK_VERSION)], kw


class TestOIGapWalkBack:
    def test_r2_steps_back_one_session_and_stamps_what_it_withheld(self, flags):
        """The only shape R0 and R1 both refuse: a session carrying NEITHER metric. Measured
        population = palm, 5 as-ofs since 2025-01-01, always depth 1."""
        rows = (_sess("2026-09-04", [(cm, v, None, None) for cm, v, _, _ in CORN_0904])
                + _sess("2026-09-03", CORN_0903))
        sp = _spec(asof="2026-09-07")
        flags(partial=True, fallback=True)
        assert Q.select_front_expiry(rows, sp, _ts()) == []          # no walk: the newest is dead
        flags(partial=True, fallback=True, walkback=True)
        out = Q.select_front_expiry(rows, sp, _ts())
        assert len(out) == 1
        r = out[0]
        assert r["front_expiry_session"] == "2026-09-03"
        assert r["sessions_withheld"] == 1
        assert r["session_age_days"] == 3            # cutoff 2026-09-06 minus the session read
        assert r["value"] == "540.75" and r["contract_month"] == "2026-12"
        assert r["roll_method"] == FR.METHOD_OPEN_INTEREST

    def test_the_row_served_is_the_row_of_the_session_the_rule_actually_ran_on(self, flags):
        """THE LOOKUP IS KEYED ON (SESSION, MONTH), NEVER ON THE MONTH ALONE. The fetch's ORDER BY is
        ASCENDING on the session date, so a month-keyed lookup over a widened rank window holds the
        OLDEST fetched session's row -- and would serve its settle under the NEWEST session's stamp,
        three disagreeing facts on every clean read. The older sessions here carry DIFFERENT settles
        for the same delivery month, so a month-keyed lookup reds this test."""
        old = [(cm, "1.25", oi, vol) for cm, _, oi, vol in CORN_0903]
        rows = (_sess("2026-09-01", old) + _sess("2026-09-02", old) + _sess("2026-09-03", CORN_0903))
        flags(partial=True, fallback=True, walkback=True)
        out = Q.select_front_expiry(rows, _spec(asof="2026-09-04"), _ts())
        assert len(out) == 1
        assert out[0]["front_expiry_session"] == "2026-09-03"
        assert out[0]["sessions_withheld"] == 0
        assert out[0]["value"] == "540.75"           # the NEWEST session's settle, never "1.25"

    def test_the_fence_is_three_sessions_and_past_it_the_answer_is_the_decline(self, flags):
        dead = [(cm, v, None, None) for cm, v, _, _ in CORN_0903]
        rows = (_sess("2026-09-04", dead) + _sess("2026-09-03", dead) + _sess("2026-09-02", dead)
                + _sess("2026-09-01", CORN_0903))    # depth 3 -- one session past the fence
        flags(partial=True, fallback=True, walkback=True)
        assert Q.FRONT_EXPIRY_FENCE == 3
        # RE-BANKED (09-23, C12): past the fence the NAMED rule is still not served (the walk never
        # reaches the one session that could run it); the newest session answers with the DECLARED
        # fallback, stamped as such, at depth 0.
        got = Q.select_front_expiry(rows, _spec(asof="2026-09-07"), _ts())
        assert [(r["front_expiry_session"], r["roll_method"]) for r in got] == [
            ("2026-09-04", Q.CYCLE_FALLBACK_METHOD)]

    def test_a_stale_level_past_the_calendar_bound_is_refused_rather_than_served(self, flags):
        """`sessions_withheld` is structurally blind to a session that NEVER ARRIVED -- a hole in the
        tape costs 0 withheld sessions and N age days. `session_age_days` is the number that can see
        it, and it is bounded for MECHANISM-served rows only."""
        rows = _sess("2026-08-20", [(cm, v, None, vol) for cm, v, _, vol in CORN_0903])
        flags(partial=True, fallback=True, walkback=True)
        assert Q.FRONT_EXPIRY_MAX_SESSION_AGE_DAYS == 7
        assert Q.select_front_expiry(rows, _spec(asof="2026-09-07"), _ts()) == []
        out = Q.select_front_expiry(rows, _spec(asof="2026-08-27"), _ts())     # age 6, inside it
        assert len(out) == 1 and out[0]["session_age_days"] == 6

    def test_a_clean_depth_zero_read_is_never_age_bounded(self, flags):
        """The bound governs the rows the mechanisms CREATE, never the rows that ship today: HEAD
        already serves a 6-day-old session on `canola_ice` after a holiday Monday (measured)."""
        rows = _sess("2026-08-20", CORN_0903)        # metric complete: the shipped path
        flags(partial=True, fallback=True, walkback=True)
        out = Q.select_front_expiry(rows, _spec(asof="2026-09-07"), _ts())
        assert len(out) == 1 and out[0]["session_age_days"] == 17
        assert out[0]["sessions_withheld"] == 0 and "roll_method_fallback" not in out[0]


class TestOIGapGreen:
    def test_a_clean_session_is_unchanged_under_every_flag_combination(self, flags):
        """GREEN. The row dict is EQUAL with all flags off and with all three on, except for the
        three keys the stamps always add. Same contract_month, value, unit, currency, settle_kind."""
        rows = _sess("2026-09-03", CORN_0903)
        sp = _spec(asof="2026-09-04")
        flags()
        base = Q.select_front_expiry(rows, sp, _ts())
        assert len(base) == 1
        flags(partial=True, fallback=True, walkback=True)
        got = Q.select_front_expiry(rows, sp, _ts())
        assert len(got) == 1
        stamps = {"front_expiry_session", "sessions_withheld", "session_age_days"}
        assert set(got[0]) - set(base[0]) == stamps
        assert {k: v for k, v in got[0].items() if k not in stamps} == base[0]
        assert got[0]["sessions_withheld"] == 0
        assert "roll_method_fallback" not in got[0] and "roll_inputs_partial" not in got[0]

    def test_a_clean_session_is_unchanged_on_every_one_of_the_nine_boards(self, flags):
        stamps = {"front_expiry_session", "sessions_withheld", "session_age_days"}
        for slug in ("corn_cbot", "soybeans_cbot", "soft_red_winter_wheat_cbot",
                     "hard_red_winter_wheat_kcbt", "soybean_meal_cbot", "soybean_oil_cbot",
                     "canola_ice", "french_wheat_matif", "malaysian_crude_palm_oil_cme"):
            rows = _sess("2026-09-03", CORN_0903)
            sp = _spec(asof="2026-09-04", commodity=slug)
            flags()
            base = Q.select_front_expiry(rows, sp, _ts())
            flags(partial=True, fallback=True, walkback=True)
            got = Q.select_front_expiry(rows, sp, _ts())
            assert bool(base) == bool(got), slug
            if not base:
                continue                 # the matif cycle / palm floor may decline both arms alike
            assert {k: v for k, v in got[0].items() if k not in stamps} == base[0], slug


class TestOIGapPIT:
    def test_the_compiled_sql_keeps_the_lagged_asof_guard_under_every_flag(self, flags):
        for kw in ({}, {"partial": True}, {"fallback": True}, {"walkback": True},
                   {"partial": True, "fallback": True, "walkback": True}):
            flags(**kw)
            sql = Q.build_sql(_spec(asof="2026-09-07"))
            assert "<= '2026-09-06'" in sql, kw      # publication_lag_days = 1
            # AND THE GUARD SITS INSIDE THE RANKED SUBQUERY, which is the whole PIT argument: the
            # ranking only ever sees sessions the as-of already admitted, so no walk-back depth can
            # reach a post-cutoff session. Pinned on POSITION, not on presence.
            assert sql.index("<= '2026-09-06'") < sql.index(") AS _v"), kw

    def test_a_session_after_the_as_of_is_never_chosen_at_any_depth(self, flags):
        """Belt AND braces: the selector filters on the cutoff ITSELF rather than trusting the caller,
        because the walk is the first code in this branch that can reach a row it did not intend to."""
        rows = (_sess("2026-09-08", CORN_0903) + _sess("2026-09-07", CORN_0903)
                + _sess("2026-09-03", CORN_0903))
        sp = _spec(asof="2026-09-07")                # cutoff 2026-09-06
        for kw in ({}, {"partial": True, "fallback": True, "walkback": True}):
            flags(**kw)
            out = Q.select_front_expiry(rows, sp, _ts())
            assert len(out) == 1, kw
            assert out[0]["knowledge_date"] == "2026-09-03", kw
            if kw:
                assert out[0]["front_expiry_session"] == "2026-09-03"


class TestOIGapPalm:
    """PALM, MEASURED. 428 of 428 sessions dark at HEAD, 100% of as-ofs -- because open interest is
    published on only the nearest ~14 of its 61 listed months (a vendor property) and volume is NULL
    on 100% of its rows BY CONSTRUCTION (`CPO` is the sole SETTLEMENT_TAPE_ROOT: the V2-4 probe
    priced ohlcv-1d at $0.0000, so `build_settlement_bronze` writes volume NULL). The all-rows
    precondition declines although THE ELIGIBLE FRONT MONTH HAS OPEN INTEREST -- 6,267 lots on the
    real 2026-09-03 session."""

    PALM = [("2026-08", "1170.0", "0"), ("2026-09", "1178.0", "6716"),
            ("2026-10", "1181.0", "5030"), ("2026-11", "1184.0", "3567"),
            ("2026-12", "1188.0", "6267"), ("2027-01", "1190.0", "3667"),
            ("2027-06", "1201.0", "2385"), ("2027-10", "1205.0", None),
            ("2028-06", "1210.0", None), ("2031-08", "1220.0", None)]

    def _rows(self, dt="2026-09-03"):
        return [_row(cm, v, dt=dt, oi=oi, vol=None, unit="USD/t") for cm, v, oi in self.PALM]

    def _sp(self, asof="2026-09-04"):
        return _spec(asof=asof, commodity="malaysian_crude_palm_oil_cme")

    def test_head_never_serves_this_board_under_the_rules_name(self, flags):
        # RE-BANKED (09-23, C12): the named rule still declines every session (all-rows precondition);
        # the DECLARED fallback serves the nearest month the rule's own eligibility admits -- the
        # forward-month floor included, so the averaging month itself is never the pick.
        flags()
        got = Q.select_front_expiry(self._rows(), self._sp(), _ts())
        assert [(r["contract_month"], r["roll_method"]) for r in got] == [
            ("2026-10", Q.CYCLE_FALLBACK_METHOD)]

    def test_r0_serves_it_on_the_primary_metric_with_no_rule_table_change(self, flags):
        """THE PALM RE-ROUTE IS NOT NEEDED AND IS NOT SHIPPED. R0 takes this board from 100.0% dark
        to 5.0% over the last 60 days and 0.8% since 2025-01-01, on the metric its own tape actually
        publishes (measured) -- where an all-twelve `DELIVERY_CYCLES` row plus `FORWARD_MONTH_FLOOR`
        1 would reduce the rule to "the nearest listed month one month forward", which IS the
        nearest-listed-expiry tie-break `CURVE_ROW_CAP`'s docstring refuses by name."""
        flags(partial=True)
        out = Q.select_front_expiry(self._rows(), self._sp(), _ts())
        assert len(out) == 1
        r = out[0]
        assert r["roll_method"] == FR.METHOD_OPEN_INTEREST
        assert "roll_method_fallback" not in r
        assert r["contract_month"] == "2026-12"      # the OI leader among ELIGIBLE months
        assert r["roll_inputs_partial"].endswith("carried no open_interest")

    def test_the_rule_table_still_routes_this_board_by_open_interest(self):
        """The un-flagged rule-table change the first cut of this design proposed is NOT here: no
        `ROLL_METHOD_BY_SLUG`, no restored twelve-month cycle, and the lint is green as shipped."""
        assert FR.roll_method_for("malaysian_crude_palm_oil_cme") == FR.METHOD_OPEN_INTEREST
        assert "malaysian_crude_palm_oil_cme" not in FR.DELIVERY_CYCLES
        assert not hasattr(FR, "ROLL_METHOD_BY_SLUG")
        assert FR.lint_roll_rule() == []

    def test_the_forward_month_floor_still_governs_the_selection(self, flags):
        """`FORWARD_MONTH_FLOOR['malaysian_crude_palm_oil_cme'] == 1` exists because this contract's
        settle is the CUMULATIVE AVERAGE of its own delivery month. 2026-09 carries the LARGEST open
        interest on this session (6,716) and must still be ineligible on a 2026-09-03 read."""
        assert FR.forward_month_floor("malaysian_crude_palm_oil_cme") == 1
        flags(partial=True)
        out = Q.select_front_expiry(self._rows(), self._sp(), _ts())
        assert out[0]["contract_month"] >= "2026-10"

    def test_no_metric_fallback_is_ever_offered_for_this_board(self, flags):
        """Volume is NULL on 100% of palm's candidate rows, so a fallback moves it from never to
        never -- and it must never be STAMPED as one either."""
        flags(partial=True, fallback=True, walkback=True)
        out = Q.select_front_expiry(self._rows(), self._sp(), _ts())
        assert len(out) == 1 and "roll_method_fallback" not in out[0]

    def test_the_all_blank_palm_session_walks_back_one(self, flags):
        """The real 2026-09-04 palm session: 60 rows, open interest blank on every one, volume blank
        on every one. Neither metric exists, so R0 and R1 both refuse it and R2 is the only remedy."""
        rows = ([_row(cm, v, dt="2026-09-04", oi=None, vol=None, unit="USD/t")
                 for cm, v, _ in self.PALM] + self._rows("2026-09-03"))
        flags(partial=True, fallback=True)
        assert Q.select_front_expiry(rows, self._sp(asof="2026-09-07"), _ts()) == []
        flags(partial=True, fallback=True, walkback=True)
        out = Q.select_front_expiry(rows, self._sp(asof="2026-09-07"), _ts())
        assert len(out) == 1
        assert out[0]["front_expiry_session"] == "2026-09-03" and out[0]["sessions_withheld"] == 1


# ==================================================================================================
# THE 09-23 FIX ROUND, LANE T (CONTRACT C12) -- THE DECLARED CYCLE FALLBACK AND THE CURVE HEADLINE.
#
# THE MEASURED DEFECT (re-smoke 2026-09-23, deep F4 / max F2; D4): "no front-month level can be named
# this session" while the same turn's curve read served November 2026 at 1,328. The live-edge cause, read
# off the tape itself: open interest lands the morning AFTER the session, so the NEWEST session of every
# GLBX board carries a settle and a NULL open interest on every row. The session shapes below are the
# REAL soybeans_cbot rows (silver/futures_eod trade_year=2026 and 2024, pulled read-only on 2026-09-23):
# (contract_month, settle, open_interest, volume).
# ==================================================================================================
SOY_0901 = [("2026-09", "1306.75", "396", "54"), ("2026-11", "1317.75", "485206", "132324"),
            ("2027-01", "1332.75", "178202", "27697"), ("2027-03", "1337.25", "152580", "18146"),
            ("2027-05", "1340.75", "101173", "10202"), ("2027-07", "1341.50", "58445", "7264"),
            ("2027-08", "1321.00", "7611", "797"), ("2027-09", "1276.25", "4543", "170"),
            ("2027-11", "1260.00", "34772", "3562"), ("2028-01", "1269.00", "1947", "36"),
            ("2028-03", "1265.75", "1091", "9"), ("2028-05", "1266.25", "467", "1"),
            ("2028-07", "1269.00", "826", "1"), ("2028-11", "1224.75", "251", "41"),
            ("2029-11", "1206.50", "10", "2")]
# September's LAST trading day: September still lists, with open interest 0 and ONE lot traded.
SOY_0914 = [("2026-09", "1285.25", "0", "1"), ("2026-11", "1304.25", "483981", "99535"),
            ("2027-01", "1320.25", "201513", "18088"), ("2027-03", "1328.00", "167372", "12958"),
            ("2027-05", "1334.50", "101059", "4246"), ("2027-07", "1338.00", "87017", "3508"),
            ("2027-08", "1319.75", "7823", "629"), ("2027-09", "1278.50", "4813", "94"),
            ("2027-11", "1263.75", "36250", "968"), ("2028-01", "1273.50", "2176", "24"),
            ("2028-03", "1270.75", "1305", "73"), ("2028-05", "1272.00", "497", "3"),
            ("2028-07", "1275.25", "937", "1"), ("2028-11", "1225.75", "293", "3"),
            ("2029-11", "1205.00", "9", "1")]
# The session the deep and max pages read (N2 served 1328.0 / 1344.0 / 1351.75 / 1358.0 of it).
SOY_0921 = [("2026-11", "1328.00", "469448", "97211"), ("2027-01", "1344.00", "211808", "16097"),
            ("2027-03", "1351.75", "170745", "10496"), ("2027-05", "1358.00", "103012", "3615"),
            ("2027-07", "1361.25", "92548", "2220"), ("2027-08", "1342.00", "8869", "708"),
            ("2027-09", "1298.50", "4946", "104"), ("2027-11", "1282.25", "38266", "1717"),
            ("2028-01", "1291.75", "2461", "86"), ("2028-03", "1287.75", "2261", "573"),
            ("2028-05", "1288.25", "575", "77"), ("2028-07", "1291.75", "950", "5"),
            ("2028-11", "1241.50", "300", "2")]
# THE LIVE EDGE: the newest session on the 2026-09-23 fetch, open interest NULL on 13 of 13 rows.
SOY_0922 = [("2026-11", "1325.50", None, "75653"), ("2027-01", "1341.25", None, "17463"),
            ("2027-03", "1348.75", None, "11374"), ("2027-05", "1355.25", None, "3909"),
            ("2027-07", "1359.25", None, "2541"), ("2027-08", "1341.00", None, "623"),
            ("2027-09", "1298.50", None, "90"), ("2027-11", "1282.25", None, "1108"),
            ("2028-01", "1291.75", None, "32"), ("2028-03", "1288.00", None, "73"),
            ("2028-05", "1289.00", None, "66"), ("2028-07", "1292.25", None, "4"),
            ("2029-11", "1204.75", None, "1")]
# The 2024-03-01 as-of turn's session: open interest healed, the named rule runs -> May 2024, 1,140.75.
SOY_20240229 = [("2024-03", "1128.25", "2203", "583"), ("2024-05", "1140.75", "342426", "102797"),
                ("2024-07", "1151.25", "166944", "23327"), ("2024-08", "1148.75", "23068", "3274"),
                ("2024-09", "1138.75", "13147", "1813"), ("2024-11", "1133.25", "120570", "11037"),
                ("2025-01", "1142.75", "10852", "1048"), ("2025-03", "1141.75", "13627", "1985"),
                ("2025-05", "1144.75", "6878", "451"), ("2025-07", "1151.25", "3084", "66"),
                ("2025-11", "1121.50", "3503", "17")]


def _soy(dt, shape, *, strip_oi=False):
    return [_row(cm, v, dt=dt, oi=(None if strip_oi else oi), vol=vol) for cm, v, oi, vol in shape]


def _soy_spec(asof):
    return _spec(asof=asof, commodity="soybeans_cbot")


class TestCycleFallback:
    def test_the_live_edge_session_serves_november_under_the_declared_method(self, flags):
        """D4 CLOSED ON THE REAL SESSION: 2026-09-22, open interest NULL on every row. HEAD declined;
        the read now names November 2026 at 1,325.50 and says which rule it is NOT."""
        flags()
        out = Q.select_front_expiry(_soy("2026-09-22", SOY_0922), _soy_spec("2026-09-23"), _ts())
        assert len(out) == 1
        r = out[0]
        assert (r["contract_month"], r["value"]) == ("2026-11", "1325.50")
        assert r["roll_method"] == Q.CYCLE_FALLBACK_METHOD
        assert r["roll_method"] not in Q.ROLL_METHODS_FRONT
        assert r["roll_rule_version"] == Q.CYCLE_FALLBACK_VERSION
        assert r["front_expiry_session"] == "2026-09-22" and r["session_age_days"] == 0
        assert r["roll_inputs_absent"] == "13 of 13 eligible candidates carried no open_interest"

    def test_REFUTE_septembers_last_trade_with_its_open_interest_stripped_is_november(self, flags):
        """THE BRIEF'S REFUTATION. On 2026-09-14 September still lists (settle 1,285.25, open interest
        0, one lot). At the live edge that session carries no open interest, and a fallback that read
        the rule's eligibility alone (`_month >= _trade_month`) names SEPTEMBER -- a one-lot contract in
        delivery. The fallback never names a contract inside its own delivery month: November."""
        flags()
        out = Q.select_front_expiry(_soy("2026-09-14", SOY_0914, strip_oi=True),
                                    _soy_spec("2026-09-15"), _ts())
        assert [(r["contract_month"], r["value"], r["roll_method"]) for r in out] == [
            ("2026-11", "1304.25", Q.CYCLE_FALLBACK_METHOD)]
        # ...and with the real (healed) open interest the NAMED rule runs and agrees on November
        real = Q.select_front_expiry(_soy("2026-09-14", SOY_0914), _soy_spec("2026-09-15"), _ts())
        assert [(r["contract_month"], r["roll_method"]) for r in real] == [("2026-11", "open_interest")]

    @pytest.mark.parametrize("dt,shape", [("2026-09-01", SOY_0901), ("2026-09-14", SOY_0914),
                                          ("2026-09-21", SOY_0921), ("2026-09-22", SOY_0922)])
    def test_T1_the_september_sweep_never_names_a_contract_in_delivery_or_without_a_settle(
            self, flags, dt, shape):
        flags()
        import datetime as _d
        asof = (_d.date.fromisoformat(dt) + _d.timedelta(days=1)).isoformat()    # the lag-1 cutoff admits dt
        for strip in (False, True):
            out = Q.select_front_expiry(_soy(dt, shape, strip_oi=strip), _soy_spec(asof), _ts())
            assert len(out) == 1, (dt, strip)
            r = out[0]
            assert r["contract_month"] > dt[:7], (dt, strip, r["contract_month"])
            assert r["value"] not in (None, ""), (dt, strip)
            assert r["contract_month"] == "2026-11", (dt, strip)

    def test_T1_the_2024_as_of_open_interest_path_is_unchanged(self, flags):
        """The as-of turn read a HEALED session: the named rule runs, May 2024, 1,140.75 -- exactly the
        page's own tape row -- with no fallback stamp anywhere."""
        flags()
        out = Q.select_front_expiry(_soy("2024-02-29", SOY_20240229), _soy_spec("2024-03-01"), _ts())
        assert len(out) == 1
        r = out[0]
        assert (r["contract_month"], r["value"], r["roll_method"], r["roll_rule_version"]) == (
            "2024-05", "1140.75", "open_interest", FR.ROLL_RULE_VERSION)
        assert "roll_method_fallback" not in r and "roll_inputs_absent" not in r

    def test_a_projection_that_never_carried_the_roll_inputs_keeps_its_decline(self, flags):
        """The S4 cause is a CALLER that never projected the rule's input; the fallback is for a
        publisher that left it EMPTY. A row with no roll-input KEY at all is not a fallback case."""
        flags()
        rows = [{k: v for k, v in r.items() if k not in ("open_interest", "volume")}
                for r in _soy("2026-09-22", SOY_0922)]
        assert Q.select_front_expiry(rows, _soy_spec("2026-09-23"), _ts()) == []

    def test_a_cash_reference_and_a_delivery_cycle_board_never_take_the_fallback(self, flags):
        flags()
        cash = Q.select_front_expiry([_row("2026-09", "1900.0", unit="BRL/60-kg bag")],
                                     _spec(commodity="brazilian_arabica_coffee"), _ts())
        assert cash == []
        # MATIF reads no metric: the named rule itself serves (vacuously present), never the fallback
        matif = Q.select_front_expiry([_row("2026-09", "210.0"), _row("2026-12", "215.0")],
                                      _spec(commodity="french_wheat_matif"), _ts())
        assert matif and matif[0]["roll_method"] == FR.METHOD_DELIVERY_CYCLE

    def test_the_fallback_is_bounded_by_the_same_calendar_age_as_every_mechanism(self, flags):
        flags()
        stale = Q.select_front_expiry(_soy("2026-09-14", SOY_0914, strip_oi=True),
                                      _soy_spec("2026-09-23"), _ts())          # age 8 > 7
        assert stale == []

    def test_T2_front_month_is_reserved_for_the_methods_decided_by_an_activity_print(self):
        """`ROLL_METHODS_FRONT` is exactly the rule module's metric-reading methods, and the fallback's
        method is outside it -- the one set every reader keys the words 'front month' on."""
        assert Q.ROLL_METHODS_FRONT == frozenset(m for m, col in FR.METHOD_METRIC_COL.items() if col)
        assert Q.CYCLE_FALLBACK_METHOD not in Q.ROLL_METHODS_FRONT
        assert Q.CYCLE_FALLBACK_METHOD not in FR.ROLL_METHODS          # never one of the rule's own
        assert Q.CYCLE_FALLBACK_VERSION != FR.ROLL_RULE_VERSION

    def test_T2_the_model_is_told_what_the_row_is_in_the_rows_own_month(self, flags):
        flags()
        row = Q.select_front_expiry(_soy("2026-09-22", SOY_0922), _soy_spec("2026-09-23"), _ts())[0]
        note = Q.cycle_fallback_note(row)
        assert "November 2026" in note and "nearest listed delivery" in note
        assert "open interest" in note and "never as 'the front month'" in note
        named = Q.select_front_expiry(_soy("2026-09-21", SOY_0921), _soy_spec("2026-09-22"), _ts())[0]
        assert Q.cycle_fallback_note(named) == ""                    # a row the rule picked says nothing
        assert Q.cycle_fallback_note({}) == ""

    def test_T2_the_agent_payload_carries_the_note_and_a_named_read_carries_none(self, flags):
        import types as _types

        class _Client:
            def __init__(self):
                self.queue = [
                    _types.SimpleNamespace(
                        content=[_types.SimpleNamespace(
                            type="tool_use", id="t1", name=A.TOOL_NAME,
                            input={"table": TABLE, "metric": "settle", "commodity": "soybeans_cbot",
                                   "agg": FE})],
                        stop_reason="tool_use"),
                    _types.SimpleNamespace(content=[_types.SimpleNamespace(type="text", text="done")],
                                           stop_reason="end_turn")]
                outer = self

                class _M:
                    def create(self, **_kw):
                        return outer.queue.pop(0)
                self.messages = _M()

        flags()
        for rows, asof, expect_note in ((_soy("2026-09-22", SOY_0922), "2026-09-23", True),
                                        (_soy("2026-09-21", SOY_0921), "2026-09-22", False)):
            out = A.answer_numbers("where is CBOT soybeans trading", asof=asof, client=_Client(),
                                   query_fn=lambda _sql, _rows=rows: _rows)
            fe = [c for c in out["calls"] if (c.get("query") or {}).get("agg") == FE]
            assert fe and fe[0]["rows"], asof
            if expect_note:
                assert fe[0]["rows"][0]["roll_method"] == Q.CYCLE_FALLBACK_METHOD
                assert "nearest listed delivery" in fe[0].get("scope_note", "")
            else:
                assert fe[0]["rows"][0]["roll_method"] == "open_interest"
                assert "scope_note" not in fe[0]                    # the named rule's read: HEAD's shape


class TestCurveHeadline:
    """C12 `curve_headline_index`: the reader's headline on a CURVE read is the nearest delivery the
    rule's eligibility admits that is not in delivery -- not the furthest expiry `_row_order_key`
    orders last."""

    def _curve(self, dt, shape):
        return [{"value": v, "knowledge_date": dt, "contract_month": cm, "settle_kind": "settlement",
                 "currency": "USD", "unit": "US cents/bushel"} for cm, v, _oi, _vol in shape]

    def test_the_deep_and_max_pages_N2_headlines_november_not_may(self):
        rows = self._curve("2026-09-21", SOY_0921[:4])         # 1328.0 / 1344.0 / 1351.75 / 1358.0
        i = Q.curve_headline_index(rows, asof="2026-09-23", ts=_ts(), commodity="soybeans_cbot")
        assert i == 0 and rows[i]["contract_month"] == "2026-11" and rows[i]["value"] == "1328.00"

    def test_a_contract_in_its_own_delivery_month_is_never_the_headline(self):
        rows = self._curve("2026-09-14", SOY_0914[:3])
        i = Q.curve_headline_index(rows, asof="2026-09-15", ts=_ts(), commodity="soybeans_cbot")
        assert rows[i]["contract_month"] == "2026-11"

    def test_the_slug_can_ride_the_row_and_without_one_there_is_no_headline(self):
        rows = self._curve("2026-09-21", SOY_0921[:3])
        assert Q.curve_headline_index(rows, asof="2026-09-23", ts=_ts()) is None
        tagged = [dict(r, leviathan_slug="soybeans_cbot") for r in rows]
        assert Q.curve_headline_index(tagged, asof="2026-09-23", ts=_ts()) == 0

    @pytest.mark.parametrize("case", ["one_month", "two_sessions", "undated", "post_cutoff", "no_card"])
    def test_every_non_curve_read_returns_none(self, case):
        rows = self._curve("2026-09-21", SOY_0921[:3])
        ts, asof = _ts(), "2026-09-23"
        if case == "one_month":
            rows = rows[:1]
        elif case == "two_sessions":
            rows[1]["knowledge_date"] = "2026-09-18"
        elif case == "undated":
            rows[1]["knowledge_date"] = ""
        elif case == "post_cutoff":
            asof = "2026-09-21"                                   # cutoff 2026-09-20 < the session read
        elif case == "no_card":
            ts = None
        assert Q.curve_headline_index(rows, asof=asof, ts=ts, commodity="soybeans_cbot") is None

    def test_a_settle_less_row_is_never_the_headline(self):
        rows = self._curve("2026-09-21", SOY_0921[:3])
        rows[0]["value"] = ""
        i = Q.curve_headline_index(rows, asof="2026-09-23", ts=_ts(), commodity="soybeans_cbot")
        assert rows[i]["contract_month"] == "2027-01"
