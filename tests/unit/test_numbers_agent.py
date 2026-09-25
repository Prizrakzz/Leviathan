"""Numbers SQL agent loop — mocked LLM + injected Athena (no spend).

The load-bearing assertion: even if the model tries to pass its own as-of date, the harness FORCES the caller's
asof — the agent has no lever to see the future.
"""
from __future__ import annotations

import json
import types

from leviathan.graphrag.numbers import agent as A


def _tool_use(inp, tid="t1"):
    return types.SimpleNamespace(type="tool_use", name=A.TOOL_NAME, input=inp, id=tid)


def _text(t):
    return types.SimpleNamespace(type="text", text=t)


def _resp(content, stop):
    return types.SimpleNamespace(content=content, stop_reason=stop)


class _Msgs:
    def __init__(self, outer):
        self.outer = outer

    def create(self, **kw):
        self.outer.sent.append(kw)
        return self.outer.queue.pop(0)


class FakeClient:
    def __init__(self, queue):
        self.queue = list(queue)
        self.sent = []
        self.messages = _Msgs(self)


def test_agent_executes_lookup_forces_asof_and_returns_provenance():
    captured = {}

    def query_fn(sql):
        captured["sql"] = sql
        return [{"value": "2462000", "knowledge_date": "2024-01-10"}]

    client = FakeClient([
        _resp([_tool_use({"table": "silver_psd", "metric": "ending_stocks_mt", "commodity": "corn_cbot",
                          "country": "Argentina", "period": "2023", "asof": "2030-01-01"})], "tool_use"),  # sneaky future
        _resp([_text("Argentina corn ending stocks were 2,462,000 MT (released 2024-01-10).")], "end_turn"),
    ])
    out = A.answer_numbers("What were Argentina corn ending stocks?", asof="2024-06-01",
                           client=client, query_fn=query_fn)
    assert "2,462,000" in out["answer"]
    assert len(out["calls"]) == 1 and out["calls"][0]["rows"][0]["value"] == "2462000"
    assert "CAST(release_date AS varchar) <= '2024-06-01'" in captured["sql"]      # forced asof (type-agnostic guard)
    assert "2030" not in captured["sql"]                          # the model's future asof was dropped
    prov = A.format_provenance(out["calls"])
    assert "silver_psd.ending_stocks_mt" in prov[0] and "2462000" in prov[0]


def test_tool_schema_has_no_asof_and_enumerates_tables():
    sch = A.tool_schema(A.load_registry())
    props = sch["input_schema"]["properties"]
    assert "asof" not in props                                   # the model literally cannot set the as-of date
    assert "silver_psd" in props["table"]["enum"] and "silver_esr" in props["table"]["enum"]


def test_system_prompt_lists_tables_units_and_semantics():
    sp = A.system_prompt(A.load_registry())
    assert "silver_psd" in sp and "ending_stocks_mt" in sp and "silver_noaa_oni" in sp
    assert "year_month" in sp and "MT" in sp                     # semantics + units surfaced to the model


def test_lookup_error_is_not_labelled_not_known():
    def failing(sql):
        raise RuntimeError("Unable to verify/create output bucket")   # the exact Fargate failure
    client = FakeClient([
        _resp([_tool_use({"table": "silver_psd", "metric": "ending_stocks_mt", "commodity": "corn_cbot",
                          "period": "2023"})], "tool_use"),
        _resp([_text("The figure is unavailable due to a lookup error.")], "end_turn")])
    out = A.answer_numbers("corn stocks?", asof="2024-06-01", client=client, query_fn=failing)
    assert out["calls"][0]["status"] == "error" and "error" in out["calls"][0]        # errored, not not_known
    assert "(lookup error)" in A.format_provenance(out["calls"])[0]


def test_empty_result_is_not_known():
    client = FakeClient([
        _resp([_tool_use({"table": "silver_psd", "metric": "ending_stocks_mt", "commodity": "corn_cbot",
                          "period": "2023"})], "tool_use"),
        _resp([_text("That value was not known at the as-of date.")], "end_turn")])
    out = A.answer_numbers("q", asof="2023-07-01", client=client, query_fn=lambda sql: [])
    assert out["calls"][0]["status"] == "not_known"                                   # empty + no error = point-in-time
    assert "(not known at asof)" in A.format_provenance(out["calls"])[0]


def test_null_aggregate_on_data_date_table_is_no_rows_not_ok():
    # sum() over zero matched rows returns ONE row with a NULL value (the July-3 b_weather_2012 case:
    # country='us' matched no partition). A null is never a usable value, and for a data_date table the
    # honest status is no_rows (scope mismatch / gap) — NEVER 'ok', NEVER 'not yet published'.
    client = FakeClient([
        _resp([_tool_use({"table": "silver_nasa_power", "metric": "precipitation_mm", "commodity": "corn_cbot",
                          "agg": "sum", "date_start": "2012-07-01", "date_end": "2012-07-31"})], "tool_use"),
        _resp([_text("The figure is unavailable from this lookup (no matching data).")], "end_turn")])
    out = A.answer_numbers("July 2012 Iowa rainfall?", asof="2012-08-01",
                           client=client, query_fn=lambda sql: [{"value": None}])
    assert out["calls"][0]["status"] == "no_rows" and out["calls"][0]["rows"] == []
    assert "(no matching data)" in A.format_provenance(out["calls"])[0]
    sent = json.loads(client.sent[-1]["messages"][-1]["content"][0]["content"])
    assert sent["status"] == "no_rows"                               # the model was told the honest status


def test_empty_on_data_date_table_is_no_rows_vintage_stays_not_known():
    # 'not yet published at the as-of' is a VINTAGE-ONLY determination; data_date tables get no_rows.
    def run(table):
        client = FakeClient([
            _resp([_tool_use({"table": table, "metric": "m", "commodity": "corn_cbot"})], "tool_use"),
            _resp([_text("done")], "end_turn")])
        return A.answer_numbers("q", asof="2023-07-01", client=client, query_fn=lambda sql: [])
    assert run("silver_nasa_power")["calls"][0]["status"] == "no_rows"
    assert run("silver_psd")["calls"][0]["status"] == "not_known"    # vintage: the PIT claim stays legitimate


def test_system_prompt_defines_no_rows_honesty():
    sp = A.system_prompt(A.load_registry())
    assert "no_rows" in sp and "NEVER claim" in sp


# --- J3: dated rows (OUTCOMES_JOIN_PLAN items 54-60a, 91) + J3b truncation sentinel (61-64) ---------
# The defect these pin: a silver_futures_eod series read rendered `settle=511.75@? (latest of 5000 rows)`
# -- a price with no date -- because the renderers read `period`, an alias that card can never emit.

_EOD_ROW = {"value": "511.75", "unit": "usd_cents_per_bushel", "knowledge_date": "2026-07-27"}
_ONI_ROW = {"value": "-0.4", "year": 2026, "month": 6}                    # year_month card: NO date alias
_PR_ROW = {"value": "0.42", "knowledge_date": "2026-01-05", "period": "2025-12-30"}
_FX_ROW = {"value": "5.41", "data_date": "2026-07-27"}                    # date_col, no knowledge_date_col


def _legacy_period_render(r: dict) -> str:
    """The pre-J3 period-slot render, verbatim from eval._row_line, so byte-identity is asserted against
    the real string and not against a paraphrase of it."""
    return f"period={r.get('period', '?')}"


def test_futures_eod_row_renders_dated_not_question_mark():
    # Item 60(i). The whole point: the `@?` shape is gone for the card that produced it.
    tok = A.row_date_token(_EOD_ROW, "silver_futures_eod")
    assert f"settle={_EOD_ROW['value']}@{tok}" == "settle=511.75@trade_date=2026-07-27"
    assert tok != "?" and "?" not in tok


def test_dated_row_is_labelled_with_the_cards_own_trade_date_column():
    # The PIT skeptic's warning (plan item 56a / "THE LABEL IS PART OF THE FIX"): a BARE date on a settle
    # is one the model narrates as a publication date, and the PIT clamp then reads satisfied when it is
    # not. Every emitting path must carry the axis name, and for this card that name is `trade_date` --
    # the exchange session -- resolved from the card, not hardcoded in the renderer.
    assert A.load_registry().tables["silver_futures_eod"].knowledge_date_col == "trade_date"
    for rendered in (A.row_date_label(_EOD_ROW, "silver_futures_eod"),
                     A.row_date_token(_EOD_ROW, "silver_futures_eod"),
                     A.row_known_label(_EOD_ROW, "silver_futures_eod")):
        assert rendered == "trade_date=2026-07-27"
        assert not rendered.startswith("period=")        # never mislabelled as a period
    # ... and the bare value stays available but is NOT what any reader-facing slot emits.
    assert A.row_date(_EOD_ROW) == "2026-07-27"


def test_period_bearing_cards_render_byte_identically_to_the_legacy_render():
    # Item 60(ii). Proves the date fallback is a FALLBACK, not an override: gold_pattern_records splits
    # knowledge_date_col=written_at from period_col=as_of_date, so it carries a real `period` and must be
    # untouched. silver_wasde likewise.
    assert A.row_date_label(_PR_ROW, "gold_pattern_records") == _legacy_period_render(_PR_ROW)
    wasde = {"value": "1234", "knowledge_date": "2025-12-30", "period": "2023/24"}
    assert A.row_date_label(wasde, "silver_wasde") == _legacy_period_render(wasde) == "period=2023/24"
    # ... AND THE `@`-SLOT TOKEN, asserted on `eval._num_line` ITSELF rather than on the primitive.
    # The label-only assertion above cannot fail on the render item 60(ii) is about: `_num_line`'s slot
    # is `value@<token>`, and a token that prefixed `period=` there changed EVERY period-bearing card's
    # line (`=1234@period=2023/24` where the legacy render is `=1234@2023/24`). The proxy passed while
    # the thing it stood for was broken (adversarial finding 6), so the render is pinned directly.
    from leviathan.graphrag import eval as _ev
    out = {"number_calls": [{"query": {"table": "silver_wasde", "metric": "ending_stocks"},
                             "rows": [{"value": "1200", "period": "2022/23"}, wasde], "status": "ok"}]}
    assert _ev._num_line(out) == "silver_wasde.ending_stocks=1234@2023/24 (latest of 2 rows)"
    assert A.row_date_token(wasde, "silver_wasde") == "2023/24"
    # the DATE axes keep their label -- that half of J3 is the fix, and it is unchanged
    assert A.row_date_token(_EOD_ROW, "silver_futures_eod") == "trade_date=2026-07-27"


def test_year_month_cards_stay_undated_and_the_residue_is_pinned():
    # Item 60(iv). silver_noaa_oni / silver_noaa_iod / gold_weather_z carry only year_col/month_col and NO
    # date_col, so `_extras` emits neither date alias and NO fallback can reach them. They KEEP `@?`. This
    # asserts the residue so it stays a known limitation instead of resurfacing as a J3 regression.
    reg = A.load_registry()
    for tid in ("silver_noaa_oni", "silver_noaa_iod", "gold_weather_z"):
        ts = reg.tables[tid]
        assert ts.date_col is None and ts.knowledge_date_col is None and ts.period_col is None
        assert A.row_date_token(_ONI_ROW, tid) == "?"                    # `@?` byte-identical to today
        assert A.row_date_label(_ONI_ROW, tid) == _legacy_period_render(_ONI_ROW) == "period=?"
        assert A.row_known_label(_ONI_ROW, tid) is None                  # no bracket at all, as today
        assert A.row_date_axis(_ONI_ROW) is None and A.row_date(_ONI_ROW) is None


def test_the_fix_is_rendering_not_query_projection():
    # Item 60(iii). The rejected alternatives were both PROJECTION changes (relax `_extras`, or declare
    # `period_col: trade_date`), rejected because they move ORDER BY on seven tables mid-parity-soak. A
    # grep for "no change under query.py" cannot be asserted from a test, so assert the thing that grep was
    # standing in for: the aliases silver_futures_eod projects are UNCHANGED -- still knowledge_date only,
    # still no data_date and no period.
    from leviathan.graphrag.numbers import query as Q
    aliases = [a for _expr, a in Q._extras(A.load_registry().tables["silver_futures_eod"])]
    assert "knowledge_date" in aliases
    assert "data_date" not in aliases and "period" not in aliases


def test_period_slot_and_knowledge_slot_use_different_orders_on_purpose():
    # Item 56a, and the reason it is not academic: gold_futures_outcomes will set period_col=event_date and
    # knowledge_date_col=endpoint_date. A row whose axes DISAGREE must resolve one way in a period slot and
    # the other way in a knowledge slot, or one of the two prints the wrong date under the other's name.
    split = {"value": "3.1", "period": "2026-03-02", "knowledge_date": "2026-05-29"}
    assert A.row_date_axis(split) == "period"                            # period-first
    assert A.row_date_label(split, "gold_pattern_records") == "period=2026-03-02"
    assert A.row_known_label(split, "gold_pattern_records") == "written_at=2026-05-29"   # knowledge-first
    # Both are labelled, so neither can be read as the other.
    assert A.row_date_label(split, "gold_pattern_records") != A.row_known_label(split, "gold_pattern_records")


def test_reach_matches_the_plans_card_by_card_derivation():
    # Item 57: 6 cards date via knowledge_date, 2 via data_date, 3 are unreachable. Pins the reach claim
    # against the live registry so a card edit that silently changes it fails here.
    reg = A.load_registry()
    for tid, col in (("silver_futures_eod", "trade_date"), ("silver_futures_prices", "date"),
                     ("silver_cot", "report_date"), ("silver_mpob", "date"),
                     ("silver_pink_sheet", "date"), ("silver_sagis_weekly_exports", "week_ending_date")):
        ts = reg.tables[tid]
        assert ts.date_col == ts.knowledge_date_col and ts.period_col is None    # the dateless shape
        assert A.row_date_label({"knowledge_date": "2026-07-27"}, tid) == f"{col}=2026-07-27"
    for tid in ("silver_nasa_power", "silver_fred_fx"):
        assert reg.tables[tid].knowledge_date_col is None
        assert A.row_date_label(_FX_ROW, tid) == "date=2026-07-27"


def test_unknown_table_degrades_to_the_alias_name_and_never_raises():
    # A render must survive a table the registry does not know (kill-switched, or a call built by hand).
    assert A.row_date_label(_EOD_ROW, "not_a_real_table") == "knowledge_date=2026-07-27"
    assert A.row_date_label(_EOD_ROW, None) == "knowledge_date=2026-07-27"
    assert A.row_date_token(_ONI_ROW, "not_a_real_table") == "?"


def _eod_call(rows, **q):
    base = {"table": "silver_futures_eod", "metric": "settle", "commodity": "corn_cbot",
            "agg": "series", "limit": 5000}
    base.update(q)
    return {"query": base, "rows": rows, "status": "ok"}


def test_format_provenance_dates_a_futures_row_and_labels_it():
    line = A.format_provenance([_eod_call([_EOD_ROW])])[0]
    assert line == "silver_futures_eod.settle corn_cbot = 511.75 [trade_date=2026-07-27]"
    assert "[2026-07-27]" not in line                    # never a bare, mistakable date


def test_format_provenance_headline_row_is_unchanged_by_j3():
    # J3 IS A RENDER FIX AND STOPS AT THE RENDER (plan item 56 scopes it to eval._num_line/_row_line).
    # Picking the headline row by chronology here would change the DISPLAYED VALUE on every multi-row
    # call on every card -- a value change smuggled inside a render fix, mid-parity-soak. rows[0] is a
    # real defect (the judged-30 RCA (b) class, already fixed in citations.from_number) and it is left
    # standing on purpose, in its own item with its own soak. This test is the pin that keeps it a
    # DECISION rather than a drift.
    rows = [{"value": "400.0", "knowledge_date": "2011-05-02"},
            _EOD_ROW,
            {"value": "450.0", "knowledge_date": "2015-01-05"}]
    line = A.format_provenance([_eod_call(rows)])[0]
    assert "= 400.0 [trade_date=2011-05-02]" in line
    assert not hasattr(A, "_headline_row")      # and the name no longer collides with cascade's


def test_truncation_sentinel_is_scoped_to_series_at_the_cap():
    # J3b, item 63: `agg='latest'` compiles ORDER BY ... DESC LIMIT 1 and cannot truncate; the curve branch
    # dedups per expiry and lands far under the cap. Only an at-cap `agg='series'` read is suspect.
    at_cap = _eod_call([_EOD_ROW] * 4, limit=4)
    assert A.series_truncated(at_cap) is True
    assert A.series_truncated(_eod_call([_EOD_ROW] * 3, limit=4)) is False
    assert A.series_truncated(_eod_call([_EOD_ROW], agg="latest", limit=1)) is False
    assert A.series_truncated(_eod_call([_EOD_ROW] * 4, agg="max", limit=4)) is False
    assert A.series_truncated({"query": {"table": "x"}, "rows": []}) is False       # error call: no agg/limit
    assert A.series_truncated(None) is False


def test_the_engine_stamp_is_the_truncation_authority_and_reaches_the_eval_render():
    # D-OJ-8 (adversarial finding 5). The render-side counter can only see rows that survived `_exec`'s
    # null drop, so a read that came back AT the cap WITH nulls arrives under the cap and the warning is
    # lost. The engine stamps `truncated` at the count the QUERY returned; `series_truncated` reads the
    # stamp first and only falls back to counting for calls minted elsewhere (cascade, fixtures).
    stamped = _eod_call([_EOD_ROW] * 2, limit=4)          # 2 surviving rows: the counter says False ...
    stamped["truncated"] = True                            # ... the ENGINE says the query returned 4
    assert A.series_truncated(stamped) is True
    unstamped = dict(stamped)
    unstamped.pop("truncated")
    assert A.series_truncated(unstamped) is False          # the one-sided fallback, unchanged
    assert A.series_truncated({**_eod_call([_EOD_ROW] * 4, limit=4), "truncated": False}) is False
    # and the clause reaches the render the plan actually names, composed with the J3 date token
    from leviathan.graphrag import eval as _ev
    call = {"query": {"table": "silver_futures_eod", "metric": "settle", "agg": "series", "limit": 4},
            "rows": [_EOD_ROW, _EOD_ROW], "status": "ok", "truncated": True}
    line = _ev._num_line({"number_calls": [call]})
    assert "@trade_date=2026-07-27 (latest of 2 rows)" in line
    # D-PQ FIX-1 (S5's deferred sentinel re-wording): the serving lanes compile newest-first by default,
    # so the cap keeps the NEWEST rows and loses the EARLY end. The old wording is pinned NEGATIVE below --
    # it is now the exact inverse of the truth, and it is the wording a reader uses to discount a current
    # print as stale.
    assert "[TRUNCATED at row cap 4: NEWEST kept, so the EARLY end of the window is missing -- not the " \
           "complete history]" in line
    assert "OLDEST kept" not in line
    call["truncated"] = False
    assert "TRUNCATED" not in _ev._num_line({"number_calls": [call]})


def test_format_provenance_says_so_when_the_read_hit_the_row_cap():
    # Item 62: at the cap the read is not the whole window, so it must not be narrated as the record.
    # D-PQ FIX-1 re-aimed WHICH end is lost -- newest-first is the serving default, so the EARLY end goes.
    line = A.format_provenance([_eod_call([_EOD_ROW] * 4, limit=4)])[0]
    assert "row cap 4 reached" in line and "not the complete history" in line
    assert "NEWEST rows kept" in line and "OLDEST rows kept" not in line
    assert "row cap" not in A.format_provenance([_eod_call([_EOD_ROW] * 3, limit=4)])[0]


def test_format_provenance_leaves_dateless_and_empty_calls_alone():
    # No date alias -> no bracket (unchanged from today), and the status vocabulary is untouched.
    line = A.format_provenance([{"query": {"table": "silver_noaa_oni", "metric": "oni_anomaly",
                                           "agg": "series", "limit": 5000},
                                 "rows": [_ONI_ROW], "status": "ok"}])[0]
    assert line == "silver_noaa_oni.oni_anomaly  = -0.4"
    assert A.format_provenance([{"query": {"table": "t", "metric": "m"}, "rows": [],
                                 "status": "no_rows"}])[0].endswith("(no matching data)")


def test_num_line_error_renders_cause_and_missing_metric_keys():
    """D-RC-15b: an error record's cause text reaches the report, and a model tool call that
    omitted the required `metric` key echoes its raw input keys -- the desk-probe defect rendered
    an unexplainable 'silver_futures_prices.?=ERROR' with the pydantic message dropped."""
    from leviathan.graphrag import eval as _ev
    line = _ev._num_line({"number_calls": [
        {"query": {"table": "silver_futures_prices", "commodity": "corn_cbot"},
         "error": "1 validation error for NumberQuery metric Field required", "rows": [],
         "status": "error"}]})
    assert line.startswith("silver_futures_prices.?=ERROR[")
    assert "Field required" in line
    assert "input keys: ['commodity', 'table']" in line


def test_num_line_error_with_metric_present_no_keys_echo():
    from leviathan.graphrag import eval as _ev
    line = _ev._num_line({"number_calls": [
        {"query": {"table": "silver_futures_prices", "metric": "close"},
         "error": "levels_only", "rows": [], "status": "error"}]})
    assert line == "silver_futures_prices.close=ERROR[levels_only]"


# ====================================================================================================
# D-PQ SCHEMA-1 (2026-08-07) -- THE REJECTED-SPEC MESSAGE.
#
# MEASURED: dcw_probe_v1 row `dcw_nass_conditions_split` burned EIGHT of sixteen lookups on one turn,
# every one of them the same failure -- `metric` omitted on silver_nass_crop_progress -- and every one
# answered with the raw pydantic dump ("1 validation error for NumberQuery / metric / Field required
# [type=missing, input_value={'asof': ...").  The tool schema ALREADY declares metric as required, so
# this was never a missing fence: it was a fence whose refusal taught the model nothing, on the ONE card
# whose shape invites the mistake (five metrics + a free state axis -> "give me Iowa's conditions" names
# a state, not a column).  The model did eventually retry with a metric, but half the call budget was
# gone and the re-scope never happened.
#
# The fence does not move.  `metric` stays required, the call still returns status='error', and nothing
# is queried.  Only the TEXT changes -- to the shape the ESR / period-mismatch scope notes already use on
# this loop: what was omitted, what the legal values are, and what to do next, delivered while the loop
# still has budget to repair itself.
# ====================================================================================================
def _reject(inp, asof="2026-08-07"):
    """Run ONE malformed tool call through the real agent loop and return its payload."""
    client = FakeClient([_resp([_tool_use(inp)], "tool_use"), _resp([_text("done")], "end_turn")])
    out = A.answer_numbers("corn conditions by state", asof=asof, client=client,
                           query_fn=lambda _sql: [])
    assert len(out["calls"]) == 1
    return out["calls"][0]


def test_a_metric_less_call_is_refused_with_a_remedy_not_a_pydantic_dump():
    call = _reject({"table": "silver_nass_crop_progress", "commodity": "corn_cbot", "country": "IA"})
    assert call["status"] == "error" and call["rows"] == []
    err = call["error"]
    assert "validation error" not in err.lower() and "input_value" not in err
    assert "metric" in err and "REJECTED" in err
    assert "ONE lookup = ONE metric" in err                 # the rule the 5-metric card kept losing
    assert "nothing was queried" in err                     # so the model knows the budget cost, and why


def test_the_refusal_names_the_metrics_that_card_actually_serves():
    err = _reject({"table": "silver_nass_crop_progress", "country": "IA"})["error"]
    for m in ("pct_good_excellent", "pct_poor_very_poor", "pct_planted", "pct_emerged", "pct_harvested"):
        assert m in err                                     # reachable by NAME, on the failing call itself


def test_the_fence_itself_is_unmoved_metric_is_still_required():
    sch = A.tool_schema(A.load_registry())["input_schema"]
    assert set(sch["required"]) == {"table", "metric"}


def test_a_data_access_failure_is_still_a_different_message():
    """The two failures must stay distinguishable: 'your call was malformed, re-issue it' vs 'the lookup
    ran and the data access failed'.  Collapsing them would teach the model to retry an outage."""
    def boom(_sql):
        raise RuntimeError("pg connection refused")
    client = FakeClient([_resp([_tool_use({"table": "silver_psd", "metric": "ending_stocks_mt",
                                           "commodity": "corn_cbot"})], "tool_use"),
                         _resp([_text("done")], "end_turn")])
    call = A.answer_numbers("q", asof="2026-08-07", client=client, query_fn=boom)["calls"][0]
    assert call["status"] == "error"
    assert "pg connection refused" in call["error"] and "REJECTED" not in call["error"]


def test_a_non_required_field_error_still_surfaces_its_own_cause():
    # Only a MISSING/blank required field gets the rewritten text; anything else falls back to the raw
    # exception, so no failure class is ever swallowed by the friendlier message.
    err = _reject({"table": "silver_psd", "metric": "ending_stocks_mt", "agg": "not_an_agg"})["error"]
    assert "REJECTED" not in err and "agg" in err


# ══ LANE C (prearm fix r1, 2026-09-17) ═══════════════════════════════════════════════════════════════
# Three instruments, three kill-switches, all default OFF, and the OFF state of each is pinned:
#   GRAPHRAG_STAT_WINDOW       -- the window a computed CHANGE was taken over, on the row that carries it
#   GRAPHRAG_COST_CENSUS       -- the per-round spend census this lane's seat never stamped
#   GRAPHRAG_RV_PAIR_SPREAD    -- the cross-series spread, COMPUTED instead of described
import pytest as _pytest
from leviathan.graphrag.numbers import stats as _ST
from leviathan.graphrag.numbers.registry import load_registry as _load_registry


def _vrow(value, **extra):
    return {"value": value, **extra}


def _usage(i=1, o=2, r=3, w=4):
    return types.SimpleNamespace(input_tokens=i, output_tokens=o,
                                 cache_read_input_tokens=r, cache_creation_input_tokens=w)


def _resp_u(content, stop, usage=None):
    return types.SimpleNamespace(content=content, stop_reason=stop, usage=usage)


# ── the shared drop rule ─────────────────────────────────────────────────────────────────────────────
def test_the_date_axis_drops_exactly_the_rows_the_series_axis_drops():
    """`_series_axis`'s own docstring is the reason this pin exists: a parallel axis built by a second
    loop "would silently misalign the moment the two loops disagreed about a droppable cell". Both now
    read `_cell_float`, so the alignment is structural -- this asserts it on every droppable shape at
    once (None, a bool, a non-numeric string, a comma'd number, and a real 0.0)."""
    rows = [_vrow("1,000", data_date="2026-01-01"), _vrow(None, data_date="2026-02-01"),
            _vrow(True, data_date="2026-03-01"), _vrow("n/a", data_date="2026-04-01"),
            _vrow("2.5", data_date="2026-05-01"), _vrow(0, data_date="2026-06-01")]
    vals, _exps = A._series_axis(rows)
    dates = A._date_axis(rows)
    assert vals == [1000.0, 2.5, 0.0]
    assert dates == ["2026-01-01", "2026-05-01", "2026-06-01"]
    assert len(vals) == len(dates)
    # a row with no date at all contributes "" -- present (so the axes stay aligned) and falsy
    assert A._date_axis([_vrow("1"), _vrow("2", period="2025")]) == ["", "2025"]


# ── the stat window ──────────────────────────────────────────────────────────────────────────────────
def test_the_stat_window_is_off_by_default_and_the_synthetic_query_is_head(monkeypatch):
    monkeypatch.delenv("GRAPHRAG_STAT_WINDOW", raising=False)
    res = {"stat": "window_change", "declined": False, "value": -0.317, "n": 3, "t1": 0, "t2": -1}
    calls = A._stat_calls("window_change", res, {}, "1000 MT", "20260904",
                          dates=["2026-07-08", "2026-08-01", "2026-09-16"])
    assert calls[0]["query"] == {"table": A.STATS_TOOL_NAME, "metric": "window_change"}


def test_the_stat_window_rides_the_period_slot_verbatim(monkeypatch):
    """The measured defect: a window_change over 2026-07-08..2026-09-16 reached the reader as
    'week-on-week'. The row now carries its own window, in the estate's ONE spelling for one (the
    cascade's `..` period token, which `citations._period_label` passes through untouched)."""
    monkeypatch.setenv("GRAPHRAG_STAT_WINDOW", "on")
    res = {"stat": "window_change", "declined": False, "value": -0.317, "n": 3, "t1": 0, "t2": -1}
    q = A._stat_calls("window_change", res, {}, "1000 MT", "20260904",
                      dates=["2026-07-08", "2026-08-01", "2026-09-16"])[0]["query"]
    assert q["period"] == "2026-07-08..2026-09-16"
    from leviathan.graphrag import citations as cit
    assert cit._period_label(q["period"]) == "2026-07-08..2026-09-16"      # never re-prefixed "MY"
    # yoy_delta names the two observations it differenced, not the whole series
    yoy = {"stat": "yoy_delta", "declined": False, "value": 1.0, "n": 3, "periods": 1}
    assert A._stat_calls("yoy_delta", yoy, {}, "%", None,
                         dates=["2024", "2025", "2026"])[0]["query"]["period"] == "2025..2026"
    # streak spans the run's first move to the latest
    stk = {"stat": "streak", "declined": False, "value": 2, "n": 4}
    assert A._stat_calls("streak", stk, {}, "MT", None,
                         dates=["a", "b", "c", "d"])[0]["query"]["period"] == "b..d"


@_pytest.mark.parametrize("dates", [None, [], ["", "", ""], ["2026-01-01", "2026-02-01"]])
def test_an_undated_or_misaligned_axis_mints_no_window_ever(monkeypatch, dates):
    """SILENCE, NEVER A GUESSED SPAN. The `year_month` cards carry no date alias at all (the J3 residue
    pinned earlier in this deck), and a misaligned axis cannot name a window -- both must leave the row
    exactly as HEAD mints it rather than inventing a span."""
    monkeypatch.setenv("GRAPHRAG_STAT_WINDOW", "on")
    res = {"stat": "window_change", "declined": False, "value": 1.0, "n": 3, "t1": 0, "t2": -1}
    assert "period" not in A._stat_calls("window_change", res, {}, "MT", None, dates=dates)[0]["query"]


def test_the_rank_stats_keep_their_own_declared_basis_and_gain_no_window(monkeypatch):
    """`zscore` has declared `z_window` since G4c(iii) and `percentile`/`extrema` are order-independent
    reads of a whole history. The scope is the POSITIONAL stats and the exclusion is deliberate."""
    monkeypatch.setenv("GRAPHRAG_STAT_WINDOW", "on")
    for stat, res in (("percentile", {"stat": "percentile", "declined": False, "value": 6.25, "n": 8}),
                      ("zscore", {"stat": "zscore", "declined": False, "value": -1.2, "n": 10,
                                  "window": 10})):
        rows = A._stat_calls(stat, res, {}, "%", None, dates=[str(i) for i in range(res["n"])])
        assert "period" not in rows[0]["query"], stat


# ── the cost census ──────────────────────────────────────────────────────────────────────────────────
def test_the_cost_census_is_off_by_default_and_writes_no_key(monkeypatch):
    monkeypatch.delenv("GRAPHRAG_COST_CENSUS", raising=False)
    client = FakeClient([_resp_u([_tool_use({"table": "silver_psd", "metric": "ending_stocks_mt",
                                             "commodity": "corn_cbot"})], "tool_use", _usage()),
                         _resp_u([_text("done")], "end_turn", _usage())])
    out = A.answer_numbers("q", asof="2026-08-07", client=client,
                           query_fn=lambda sql: [{"value": "1", "knowledge_date": "2026-01-01"}])
    assert "numbers_usage" not in out


def test_the_cost_census_records_one_row_per_round_with_cache_write(monkeypatch):
    """COST_LATENCY's STEP 1. The five-turn smoke priced at $2.56 against a provable floor of $3.93 and
    THIS seat was the missing $1.30; `cache_creation_input_tokens` -- section 1.4's "single largest
    blind spot" -- is measured nowhere in the estate. One row per ROUND, because the bill is dominated
    by re-reading one 99,207-token prefix once per round."""
    monkeypatch.setenv("GRAPHRAG_COST_CENSUS", "on")
    client = FakeClient([
        _resp_u([_tool_use({"table": "silver_psd", "metric": "ending_stocks_mt",
                            "commodity": "corn_cbot"})], "tool_use", _usage(137, 200, 0, 99207)),
        _resp_u([_text("done")], "end_turn", _usage(12, 340, 99207, 1500))])
    out = A.answer_numbers("q", asof="2026-08-07", client=client, model="claude-sonnet-5",
                           query_fn=lambda sql: [{"value": "1", "knowledge_date": "2026-01-01"}])
    rows = out["numbers_usage"]
    assert len(rows) == 2
    assert rows[0] == {"model": "claude-sonnet-5", "in": 137, "out": 200,
                       "cache_read": 0, "cache_write": 99207}
    assert rows[1]["cache_read"] == 99207 and rows[1]["cache_write"] == 1500


def test_a_usage_object_that_raises_costs_the_census_a_row_and_never_the_turn(monkeypatch):
    """This file's standing law: an instrument never breaks an answer."""
    monkeypatch.setenv("GRAPHRAG_COST_CENSUS", "on")

    class _Boom:
        content = [_text("done")]
        stop_reason = "end_turn"

        @property
        def usage(self):
            raise RuntimeError("no usage on this provider")

    client = FakeClient([_Boom()])
    out = A.answer_numbers("q", asof="2026-08-07", client=client, query_fn=lambda sql: [])
    assert out["answer"] == "done"
    assert "numbers_usage" not in out                      # one row lost, the turn intact


# ── the RV pair spread ───────────────────────────────────────────────────────────────────────────────
_RV_Q = ("Palm oil's supply picture has been shifting. How does that reach soybean oil, and where does "
         "the balance between the two sheets stand this marketing year?")


def _price_rows(vals, unit="USD/mt"):
    return [{"value": str(v), "unit": unit, "data_date": "2026-%02d-01" % (i + 1),
             "knowledge_date": "2026-%02d-01" % (i + 1)} for i, v in enumerate(vals)]


def _pink(metric, agg):
    return {"table": "silver_pink_sheet", "metric": metric, "agg": agg}


def _two_leg_client(agg):
    return FakeClient([
        _resp_u([_tool_use(_pink("palm_oil_cpo_usd_t", agg), "a"),
                 _tool_use(_pink("soybean_oil_usd_t", agg), "b")], "tool_use"),
        _resp_u([_text("read both legs.")], "end_turn")])


def _two_leg_query_fn(palm, soy):
    def qf(sql):
        if "palm_oil_cpo_usd_t" in sql:
            return _price_rows(palm)
        if "soybean_oil_usd_t" in sql:
            return _price_rows(soy)
        return []
    return qf


def test_the_rv_pair_lane_is_off_by_default_everywhere(monkeypatch):
    """OFF: no scope is resolved, no leg runs, no key is written -- and the 247 kB cached system prefix
    does not move by a byte, which is the property that lets this land before an arm cell."""
    monkeypatch.delenv("GRAPHRAG_RV_PAIR_SPREAD", raising=False)
    reg = _load_registry()
    off = A.system_prompt(reg)
    monkeypatch.setenv("GRAPHRAG_RV_PAIR_SPREAD", "on")
    assert len(A.system_prompt(reg)) > len(off)
    monkeypatch.delenv("GRAPHRAG_RV_PAIR_SPREAD", raising=False)
    assert A.system_prompt(reg) == off
    out = A.answer_numbers(_RV_Q, asof="2026-09-16", client=_two_leg_client("latest"),
                           query_fn=_two_leg_query_fn([1117.0], [1638.0]))
    assert "rv_pair_uncomputed" not in out and "rv_pair_spread" not in out
    assert [c["query"]["table"] for c in out["calls"]] == ["silver_pink_sheet"] * 2


def test_two_markets_are_recognised_from_the_questions_own_words():
    assert A.rv_pair_scope(_RV_Q) == ("malaysian_crude_palm_oil_cme", "soybean_oil_cbot")
    assert A.rv_pair_scope("How do corn and wheat balance sheets compare?") == (
        "corn_cbot", "soft_red_winter_wheat_cbot")
    assert A.rv_pair_scope("What are US corn ending stocks?") is None
    assert A.rv_pair_scope("") is None


def test_two_single_date_reads_mint_the_spread_LEVEL_and_deny_the_reader_nothing(monkeypatch):
    """THE SMOKE'S OWN SHAPE. The page printed palm 1,117 and soyoil 1,638 USD/mt from one source and
    month and then said "the gap itself is not a served series". Two `agg='latest'` reads are ONE joined
    observation apiece, so `stats.pair_spread` refuses at its own HISTORY floor.
    RE-BANKED (09-23 fix round, lane T, D5): one shared observation is exactly what a spread LEVEL needs,
    so `stats.pair_level_spread` takes it -- 1,117 - 1,638 = -521 USD/mt (palm named first) -- and the
    turn mints it as a citable row instead of recording a miss. Still no refusal, preface or deletion."""
    monkeypatch.setenv("GRAPHRAG_RV_PAIR_SPREAD", "on")
    out = A.answer_numbers(_RV_Q, asof="2026-09-16", client=_two_leg_client("latest"),
                           query_fn=_two_leg_query_fn([1117.0], [1638.0]))
    assert A.RV_PAIR_UNCOMPUTED_KEY not in out
    # MOVED (09-24 fix round 2, lane T, CONTRACT K8): `rows_minted` and `source` join the record AT ITS
    # TAIL; `legs` keeps its HEAD position and meaning (the rows this leg appended).
    assert out["rv_pair_spread"] == {"legs": 1, "markets": ["malaysian_crude_palm_oil_cme",
                                                            "soybean_oil_cbot"],
                                     "rows_minted": 1, "source": "seat"}
    assert out["answer"] == "read both legs."          # NOT a refusal, NOT a preface, NOT a deletion
    minted = [c for c in out["calls"] if c["query"]["table"] == A.STATS_TOOL_NAME]
    assert [c["query"]["metric"] for c in minted] == ["pair_spread"]      # a level: no rank is minted
    row = minted[0]["rows"][0]
    assert (row["value"], row["unit"], row["data_date"]) == (-521.0, "USD/mt", "2026-01-01")
    assert minted[0]["stat_provenance"]["stat"] == "pair_level_spread"


def test_two_series_reads_mint_the_spread_and_its_rank_as_observed_rows(monkeypatch):
    """THE FIGURE THE TURN OWED: 1,638 - 1,117 = 521 USD/mt, computed by the calculator and minted as a
    citable [N] row that names BOTH legs and the window it was joined over -- never arithmetic in the
    model's head, and never a sentence saying the gap is not served."""
    monkeypatch.setenv("GRAPHRAG_RV_PAIR_SPREAD", "on")
    palm = [1050, 1062, 1071, 1088, 1094, 1101, 1110, 1117]
    soy = [1480, 1502, 1533, 1561, 1580, 1601, 1620, 1638]
    out = A.answer_numbers(_RV_Q, asof="2026-09-16", client=_two_leg_client("series"),
                           query_fn=_two_leg_query_fn(palm, soy))
    assert out["rv_pair_spread"]["legs"] == 2 and A.RV_PAIR_UNCOMPUTED_KEY not in out
    minted = [c for c in out["calls"] if c["query"]["table"] == A.STATS_TOOL_NAME]
    assert [c["query"]["metric"] for c in minted] == ["pair_spread", "percentile"]
    spread, rank = minted[0]["rows"][0], minted[1]["rows"][0]
    assert spread["value"] == float(palm[-1] - soy[-1]) == -521.0   # A minus B, and the legs say which
    assert spread["unit"] == "USD/mt" and spread["leg_a"].endswith("palm_oil_cpo_usd_t")
    assert spread["leg_b"].endswith("soybean_oil_usd_t") and spread["pair_form"] == "difference"
    assert minted[0]["query"]["period"] == "2026-01-01..2026-08-01"
    assert rank["unit"] == "percentile" and 0 <= rank["value"] <= 100
    assert spread["knowledge_date"] == "2026-08-01"       # the LATER leg: the pair is not known before
    # the figures are the calculator's own, never a second derivation at this seam
    dates = [r["data_date"] for r in _price_rows(palm)]
    ref = _ST.pair_spread([float(v) for v in palm], dates, "USD/mt",
                          [float(v) for v in soy], dates, "USD/mt", label_a="a", label_b="b")
    assert spread["value"] == ref["value"]
    assert rank["value"] == _ST.percentile(ref["value"], ref["series"])["value"]


def test_the_pair_leg_refuses_two_tonnage_legs_and_mismatched_units(monkeypatch):
    """A spread is a fact about two PRICE series in one unit. Two stock series are not a spread, and two
    prices in different units are refused by `stats.unit_compatible` -- the module's one policy."""
    monkeypatch.setenv("GRAPHRAG_RV_PAIR_SPREAD", "on")
    tonnes = FakeClient([
        _resp_u([_tool_use({"table": "silver_psd", "metric": "ending_stocks_mt",
                            "commodity": "soybeans_cbot"}, "a"),
                 _tool_use({"table": "silver_psd", "metric": "ending_stocks_mt",
                            "commodity": "corn_cbot"}, "b")], "tool_use"),
        _resp_u([_text("stocks")], "end_turn")])
    out = A.answer_numbers("How do corn and soybean stocks compare?", asof="2026-09-16", client=tonnes,
                           query_fn=lambda sql: [{"value": "100", "unit": "MT",
                                                  "knowledge_date": "2026-01-01"}])
    assert "rv_pair_spread" not in out
    # RE-BANKED (round 2, review M-3): the decline now NAMES THE MARKETS with no price level behind
    # them, in the reader's words, because "served N price leg(s)" counted the wrong thing -- a turn
    # could serve four price legs and be about neither of the markets the question named.
    reason = out[A.RV_PAIR_UNCOMPUTED_KEY]["reason"]
    assert "price LEVEL" in reason and "CBOT corn" in reason and "CBOT soybeans" in reason

    mixed = FakeClient([
        _resp_u([_tool_use(_pink("palm_oil_cpo_usd_t", "series"), "a"),
                 _tool_use(_pink("soybean_oil_usd_t", "series"), "b")], "tool_use"),
        _resp_u([_text("mixed")], "end_turn")])

    def qf(sql):
        if "palm_oil_cpo_usd_t" in sql:
            return _price_rows([1, 2, 3], unit="USD/mt")
        return _price_rows([4, 5, 6], unit="US cents/lb")
    out2 = A.answer_numbers(_RV_Q, asof="2026-09-16", client=mixed, query_fn=qf)
    assert "rv_pair_spread" not in out2 and A.RV_PAIR_UNCOMPUTED_KEY in out2


def test_a_one_market_question_takes_no_branch_even_with_the_flag_lit(monkeypatch):
    monkeypatch.setenv("GRAPHRAG_RV_PAIR_SPREAD", "on")
    out = A.answer_numbers("What is the palm oil price?", asof="2026-09-16",
                           client=FakeClient([_resp_u([_tool_use(_pink("palm_oil_cpo_usd_t", "series"))],
                                                      "tool_use"),
                                              _resp_u([_text("ok")], "end_turn")]),
                           query_fn=lambda sql: _price_rows([1, 2, 3]))
    assert "rv_pair_spread" not in out and A.RV_PAIR_UNCOMPUTED_KEY not in out


def test_the_rv_mandate_asks_for_a_read_shape_and_never_for_a_tool_that_does_not_exist(monkeypatch):
    """`pair_spread` is in `stats.ENGINE_STAT_NAMES`, deliberately outside `STAT_REGISTRY` -- which IS
    the agent's tool enum. A mandate telling the model to CALL it would mint an `unknown stat` error
    round at real cost, so the bullet asks for the read shape the engine leg needs instead."""
    monkeypatch.setenv("GRAPHRAG_RV_PAIR_SPREAD", "on")
    assert "pair_spread" not in _ST.STAT_NAMES and "pair_spread" in _ST.ENGINE_STAT_NAMES
    sp = A.system_prompt(_load_registry())
    assert "TWO MARKETS IS A SPREAD QUESTION" in sp
    assert "pair_spread" not in sp
    assert "agg='series'" in sp


# ══ LANE C (prearm fix ROUND 2, 2026-09-17) ══════════════════════════════════════════════════════════
# The review's FATAL and five MAJORs, each pinned with the measurement that condemned round 1 written
# into the docstring, so a future reader can tell a rule from a preference.
import re as _re


class _NS:
    """A minimal spec stand-in for the two predicates that read attributes off one."""

    def __init__(self, **kw):
        self.__dict__.update(kw)


_HEAD_METRIC_RX = _re.compile(r"(?:^|_)(?:price|prices|usd|settle|close)(?:_|$)|_usd_[a-z]+$|price")
_R2_UNIT_RX = _re.compile(
    r"^\s*(?:us\s*cents?|usd|us\$|\$|eur|gbp|jpy|cad|aud|cny|rmb|myr|zar|brl|inr|ars)\b.*/", _re.I)
_R2_DERIVED_RX = _re.compile(
    r"(?:^|_)(?:z|zscore|z_score|sigma|pct|percent|pctile|percentile|rank|delta|change|diff|spread|"
    r"ratio|share|index|ma|sma|ema|vol|volatility|stdev|yoy|mom|wow|margin|cost|value|premium|basis)"
    r"(?:_|$)|_zscore_|_pct_change")


def _head_is_price_call(call):
    """HEAD's / round-1's `_rv_is_price_call`, re-implemented HERE -- both refuted rules live in this
    file and NEITHER in `agent.py` any more (round 3), so the shipped rule is pinned against the things
    it replaced rather than against a paraphrase of them, and src carries only what ships."""
    if str((call or {}).get("status") or "") != "ok" or not ((call or {}).get("rows") or []):
        return False
    metric = str(((call or {}).get("query") or {}).get("metric") or "").lower()
    unit = str(((call or {}).get("rows") or [{}])[0].get("unit") or "")
    return bool(_HEAD_METRIC_RX.search(metric) or _R2_UNIT_RX.search(unit))


def _r2_is_price_call(call):
    """ROUND 2's rule, re-implemented HERE for the same reason: the ROW's own unit against a
    currency-per-unit regex, with derived metric SPELLINGS refused."""
    if str((call or {}).get("status") or "") != "ok" or not ((call or {}).get("rows") or []):
        return False
    metric = str(((call or {}).get("query") or {}).get("metric") or "").lower()
    if _R2_DERIVED_RX.search(metric):
        return False
    unit = str(((call or {}).get("rows") or [{}])[0].get("unit") or "")
    return bool(_R2_UNIT_RX.search(unit))


def _leg(table, metric, vals, unit, commodity=None, dates=None):
    ds = dates or ["2026-%02d-01" % (i + 1) for i in range(len(vals))]
    rows = [{"value": v, "unit": unit, "data_date": d, "knowledge_date": d}
            for v, d in zip(vals, ds)]
    q = {"table": table, "metric": metric}
    if commodity:
        q["commodity"] = commodity
    return {"query": q, "rows": rows, "status": "ok"}


_R2_SCOPE = ("soybean_oil_cbot", "malaysian_crude_palm_oil_cme")
_R2_PALM = [1050.0, 1062.0, 1071.0, 1088.0, 1094.0, 1101.0, 1110.0, 1117.0]
_R2_SOY = [1480.0, 1502.0, 1533.0, 1561.0, 1580.0, 1601.0, 1620.0, 1638.0]


# ── M-3: THE TWO LEGS ARE THE TWO MARKETS THE QUESTION NAMES ────────────────────────────────────────
def test_a_derived_row_is_not_a_price_leg_and_the_two_measured_mints_are_unproducible():
    """THE TWO FIGURES THE REVIEW RENDERED OUT OF ROUND 1, REPRODUCED AND REFUSED.

      (a) the two z-scores the soyoil turn actually served ([N13] palm 0.269096 sigma, [N14] soyoil
          1.21357 sigma) read as series -> HEAD's rule mints `pair_spread = -0.944474 sigma vs 5-yr
          mean`: a DIFFERENCE OF TWO Z-SCORES served as an observed value with a unit, because
          `_RV_PRICE_METRIC_RX` matched `palm_oil_cpo_usd_t_zscore_5yr` through its `_usd_`;
      (b) two CRUDE OIL legs on the palm/soyoil question -> HEAD's rule mints `2 USD/bbl` while the
          lane's own record names `['malaysian_crude_palm_oil_cme', 'soybean_oil_cbot']`.

    Both are refused now, and for two independent reasons: (a) is not a metric the estate DECLARES to
    be any market's price (round 3 -- round 2 refused it on its unit spelling instead) and (b) fails
    the MARKET test (neither leg prices either of the two markets the question named)."""
    zs = [_leg("silver_pink_sheet", "palm_oil_cpo_usd_t_zscore_5yr",
               [0.10, 0.12, 0.15, 0.18, 0.20, 0.22, 0.25, 0.269096], "sigma vs 5-yr mean"),
          _leg("silver_pink_sheet", "soybean_oil_usd_t_zscore_5yr",
               [0.80, 0.90, 1.00, 1.05, 1.10, 1.15, 1.18, 1.21357], "sigma vs 5-yr mean")]
    assert [_head_is_price_call(c) for c in zs] == [True, True]          # HEAD took them
    assert [A._rv_is_price_call(c) for c in zs] == [False, False]        # ...and this rule does not
    rows, why = A.rv_pair_spread_legs(_R2_SCOPE, zs)
    assert rows == [] and "price LEVEL" in why

    # ROUND 3: brent crude is a PRINTED price on the same card and the estate declares it nobody's RV
    # benchmark, so it is refused ONE STEP EARLIER than round 2 refused it -- by the declaration, not
    # by the market matcher. `cocoa_usd_t` IS a declared benchmark and is still a price of neither
    # market, so the market test keeps a live subject.
    crude = [_leg("silver_pink_sheet", "brent_crude_usd_bbl", [70.0, 71.0, 72.0, 73.0], "USD/bbl"),
             _leg("silver_pink_sheet", "brent_crude_usd_bbl", [68.0, 69.0, 70.0, 71.0], "USD/bbl",
                  commodity="other")]
    assert [_head_is_price_call(c) for c in crude] == [True, True]
    assert [_r2_is_price_call(c) for c in crude] == [True, True]         # round 2 took them...
    assert [A._rv_is_price_call(c) for c in crude] == [False, False]     # ...nobody declares them
    assert [A.rv_leg_market(c, _R2_SCOPE) for c in crude] == [None, None]
    rows, why = A.rv_pair_spread_legs(_R2_SCOPE, crude)
    assert rows == [] and "CBOT soybean oil" in why and "CME palm oil" in why

    off = [_leg("silver_pink_sheet", "cocoa_usd_t", [7000.0, 7100.0, 7200.0, 7300.0], "USD/mt")]
    assert A._rv_is_price_call(off[0]) is True                           # a DECLARED price...
    assert A.rv_leg_market(off[0], _R2_SCOPE) is None                    # ...of neither market
    rows, why = A.rv_pair_spread_legs(_R2_SCOPE, off)
    assert rows == [] and "CBOT soybean oil" in why and "CME palm oil" in why


def test_call_order_selects_nothing_and_the_question_order_fixes_the_sign():
    """THE MIXED TURN: two crude legs arrive FIRST in call order, the two market legs after. Round 1
    would have differenced the crude pair; the market matcher takes the palm and soyoil legs wherever
    they sit, and `leg_a` is the market the QUESTION named first, so the sign is the reader's."""
    calls = [_leg("silver_pink_sheet", "cocoa_usd_t", [7000.0, 7100.0, 7200.0, 7300.0], "USD/mt"),
             _leg("silver_pink_sheet", "brent_crude_usd_bbl", [70.0, 71.0, 72.0, 73.0], "USD/bbl"),
             _leg("silver_pink_sheet", "palm_oil_cpo_usd_t", _R2_PALM, "USD/mt"),
             _leg("silver_pink_sheet", "soybean_oil_usd_t", _R2_SOY, "USD/mt")]
    # THREE declared price levels served (round 3: brent is nobody's declared benchmark and never
    # becomes a candidate at all), and the cocoa leg arrives FIRST in call order.
    assert len(A.rv_pair_candidates(calls)) == 3
    picked = A.rv_pair_candidates(calls, _R2_SCOPE)                   # ...two of them are the markets
    assert [A.rv_leg_market(c, _R2_SCOPE) for c in picked] == list(_R2_SCOPE)
    rows, why = A.rv_pair_spread_legs(_R2_SCOPE, calls)
    assert why is None and rows
    spread = rows[0]["rows"][0]
    assert spread["value"] == _R2_SOY[-1] - _R2_PALM[-1] == 521.0     # soyoil FIRST -> soyoil minus palm
    assert spread["leg_a"].endswith("soybean_oil_usd_t")
    assert spread["leg_b"].endswith("palm_oil_cpo_usd_t")
    # and the reversed question reverses the sign, because the question owns the order
    rev = ("malaysian_crude_palm_oil_cme", "soybean_oil_cbot")
    rows2, _ = A.rv_pair_spread_legs(rev, calls)
    assert rows2[0]["rows"][0]["value"] == -521.0


def test_the_leg_market_is_read_from_the_call_and_never_guessed():
    """Two declared reads and nothing else: the call's own `commodity`, then the METRIC NAME for the
    cards where the market IS the metric (silver_pink_sheet's card says so in those words). A leg that
    answers neither is UNASSIGNED."""
    assert A.rv_leg_market(_leg("silver_pink_sheet", "palm_oil_cpo_usd_t", [1.0], "USD/mt"),
                           _R2_SCOPE) == "malaysian_crude_palm_oil_cme"
    assert A.rv_leg_market(_leg("silver_futures_eod", "settle", [1.0], "US cents/bushel",
                                commodity="soybean_oil_cbot"), _R2_SCOPE) == "soybean_oil_cbot"
    assert A.rv_leg_market(_leg("silver_pink_sheet", "barley_usd_t", [1.0], "USD/mt"),
                           _R2_SCOPE) is None
    assert A.rv_leg_market(_leg("silver_pink_sheet", "palm_oil_cpo_usd_t", [1.0], "USD/mt"),
                           None) is None


def test_the_crush_components_are_never_price_legs():
    """`gold_board_crush` declares four USD/bushel metrics that pass a currency-per-unit unit test. The
    MARGIN is a spread already (a spread of a spread is not a reading) and the three components are
    board constructions, not the market's own printed price -- all four are refused by the property
    that makes them wrong, not by a table whitelist."""
    for m in ("crush_margin_usd_bu", "bean_cost_usd_bu", "oil_value_usd_bu", "meal_value_usd_bu"):
        c = _leg("gold_board_crush", m, [2.5, 2.6, 2.7], "USD/bushel", commodity="soybeans_cbot")
        assert _head_is_price_call(c) is True, m        # HEAD took all four
        assert A._rv_is_price_call(c) is False, m       # ...and this rule takes none


# ── ROUND 3, REVIEW MAJOR-1: THE PRICE-LEG RULE IS PINNED ON THE CORPUS, NOT ON THE REGISTRY ────────
# THE CORPUS ITSELF, banked: every DISTINCT (table, metric, the unit the ROW carried) shape among the
# 372 ok reads of the 2026-09-16 pre-arm smoke that ANY of the three candidate rules classified as a
# price leg, with how many of the 372 reads had that shape. 44 shapes; the 328 reads no rule ever took
# are not here because no rule's count can move on them. Generated from the three
# `prearm_smoke_0916/s3/baseline_*.json` artifacts, which record what each lookup returned at the same
# as-of. `''` is a row that carried NO unit at all -- the shape round 2 could not see.
_R3_CORPUS = [
    ('gold_board_crush', 'crush_margin_usd_bu', '', 2),
    ('gold_board_crush', 'crush_margin_usd_bu', 'USD/bu', 6),
    ('gold_board_crush', 'crush_margin_usd_bu', 'percentile', 6),
    ('gold_board_crush', 'crush_margin_usd_bu', 'sigma', 6),
    ('silver_fred_fx', 'eur_usd', 'local currency per USD', 1),
    ('silver_fred_fx', 'eur_usd', 'percentile', 1),
    ('silver_fred_fx', 'eur_usd', 'sigma', 1),
    ('silver_fred_fx', 'idr_usd', 'local currency per USD', 2),
    ('silver_fred_fx', 'idr_usd', 'percentile', 2),
    ('silver_fred_fx', 'idr_usd', 'sigma', 2),
    ('silver_fred_fx', 'inr_usd', 'local currency per USD', 2),
    ('silver_fred_fx', 'inr_usd', 'percentile', 2),
    ('silver_fred_fx', 'inr_usd', 'sigma', 2),
    ('silver_fred_fx', 'mxn_usd', 'local currency per USD', 1),
    ('silver_fred_fx', 'mxn_usd', 'percentile', 1),
    ('silver_fred_fx', 'mxn_usd', 'sigma', 1),
    ('silver_futures_eod', 'settle', 'EUR/t', 1),
    ('silver_futures_eod', 'settle', 'US cents/bushel', 2),
    ('silver_futures_eod', 'settle change over 1 session', 'EUR/t', 1),
    ('silver_futures_eod', 'settle change over 21 sessions', 'EUR/t', 1),
    ('silver_futures_eod', 'settle change over 5 sessions', 'EUR/t', 1),
    ('silver_futures_eod', 'settle_change_pct', '%', 16),
    ('silver_pink_sheet', 'brent_crude_usd_bbl_zscore_5yr', 'percentile', 2),
    ('silver_pink_sheet', 'brent_crude_usd_bbl_zscore_5yr', 'sigma', 2),
    ('silver_pink_sheet', 'brent_crude_usd_bbl_zscore_5yr', 'z', 6),
    ('silver_pink_sheet', 'brent_crude_usd_bbl_zscore_5yr_pace_change', 'z', 4),
    ('silver_pink_sheet', 'natural_gas_us_usd_mmbtu_zscore_5yr', 'percentile', 1),
    ('silver_pink_sheet', 'natural_gas_us_usd_mmbtu_zscore_5yr', 'sigma', 1),
    ('silver_pink_sheet', 'natural_gas_us_usd_mmbtu_zscore_5yr', 'z', 1),
    ('silver_pink_sheet', 'palm_oil_cpo_usd_t', '', 1),
    ('silver_pink_sheet', 'palm_oil_cpo_usd_t_zscore_5yr', '', 1),
    ('silver_pink_sheet', 'potassium_usd_mt_zscore_5yr', 'z', 1),
    ('silver_pink_sheet', 'potassium_usd_mt_zscore_5yr_pace_change', 'z', 1),
    ('silver_pink_sheet', 'potassium_usd_mt_zscore_5yr_pace_streak', 'months', 1),
    ('silver_pink_sheet', 'soybean_oil_usd_t', '', 2),
    ('silver_pink_sheet', 'soybean_oil_usd_t_zscore_5yr', '', 1),
    ('silver_pink_sheet', 'soybeans_usd_t', '', 2),
    ('silver_pink_sheet', 'soybeans_usd_t_zscore_5yr', '', 1),
    ('silver_pink_sheet', 'urea_usd_mt_zscore_5yr', 'percentile', 1),
    ('silver_pink_sheet', 'urea_usd_mt_zscore_5yr', 'sigma', 1),
    ('silver_pink_sheet', 'urea_usd_mt_zscore_5yr', 'z', 3),
    ('silver_pink_sheet', 'urea_usd_mt_zscore_5yr_pace_change', 'z', 2),
    ('silver_pink_sheet', 'urea_usd_mt_zscore_5yr_pace_streak', 'months', 2),
    ('silver_wasde', 'avg_farm_price', '$/bu', 9),
]


def test_the_price_leg_rule_is_measured_on_the_corpus_and_the_round_2_rule_took_none_of_it():
    """THE DEFECT MAJOR-1 RE-OPENED: round 2's rule was CLOSED ON FIXTURES AND BROKEN ON THE CORPUS.
    It read `rows[0]['unit']` against a currency-per-unit regex, and the number pinned for it (a
    113 -> 37 census over the CARD's declared unit) measured a different field over a set DISJOINT
    from the one the rule could admit: all 37 survivors sit on cards with no `unit_col` and no
    `unit_overrides`, so `query.py` stamps no row unit for any of them and the rule refuses every one.

    MEASURED HERE, over the corpus's own 372 ok reads:
      HEAD/round-1  106  -- every z-score, every pace change, every FX rate
      ROUND 2         6  -- and ZERO on rv_soyoil_palm, the turn this lane exists to fix
      ROUND 3         8  -- the declared benchmarks, and on rv_soyoil_palm exactly the two legs

    Round 2 also took three DERIVED rows it could not see: a windowed change is served under a metric
    name spelled in WORDS ('settle change over 5 sessions'), never in the underscore form its
    derived-spelling belt was written against."""
    head = r2 = r3 = 0
    for tid, metric, unit, n in _R3_CORPUS:
        c = _leg(tid, metric, [1.0], unit)
        head += n if _head_is_price_call(c) else 0
        r2 += n if _r2_is_price_call(c) else 0
        r3 += n if A._rv_is_price_call(c) else 0
    assert (head, r2, r3) == (106, 6, 8), (head, r2, r3)
    # the three derived rows round 2 took on rv_palm_rapeoil, by address
    for m in ("settle change over 1 session", "settle change over 5 sessions",
              "settle change over 21 sessions"):
        c = _leg("silver_futures_eod", m, [1.0], "EUR/t")
        assert _r2_is_price_call(c) is True and A._rv_is_price_call(c) is False, m


def test_the_motivating_turns_two_price_legs_are_found_and_the_false_record_is_gone():
    """rv_soyoil_palm served `silver_pink_sheet.palm_oil_cpo_usd_t = 1117.0` and
    `soybean_oil_usd_t = 1638.0` -- ONE card, ONE month, ONE declared unit (USD/mt), each recorded
    with `unit: null` because the pink sheet stamps no row unit. Round 2 found NEITHER and wrote
    "the turn names two markets and no served read is a price LEVEL for CME palm oil, CBOT soybean
    oil", which is FALSE about that page. The rule now finds both, and the record written instead is
    the CALCULATOR's own -- two `agg='latest'` reads share one observation, which is below
    `MIN_PAIR_SPREAD_N`."""
    palm = _leg("silver_pink_sheet", "palm_oil_cpo_usd_t", [1117.0], "")
    soy = _leg("silver_pink_sheet", "soybean_oil_usd_t", [1638.0], "")
    assert [c["rows"][0]["unit"] for c in (palm, soy)] == ["", ""]      # as the corpus recorded them
    assert [_r2_is_price_call(c) for c in (palm, soy)] == [False, False]
    assert [A._rv_is_price_call(c) for c in (palm, soy)] == [True, True]
    scope = ("malaysian_crude_palm_oil_cme", "soybean_oil_cbot")
    assert [A.rv_leg_market(c, scope) for c in (palm, soy)] == list(scope)
    rows, why = A.rv_pair_spread_legs(scope, [palm, soy])
    # RE-BANKED (09-23, lane T, D5): one shared observation is the spread LEVEL's own shape, so the
    # calculator (`stats.pair_level_spread`) mints it -- 1,117 - 1,638 = -521 USD/mt, off the CARD's
    # declared unit (the rows carry none) -- and there is no record to write at all.
    assert why is None and len(rows) == 1
    assert (rows[0]["rows"][0]["value"], rows[0]["rows"][0]["unit"]) == (-521.0, "USD/mt")


def test_the_card_declares_the_unit_when_the_row_does_not_and_the_spread_then_computes():
    """MAJOR-1's second half. `citations._card_unit` is the fallback `citations.from_number` already
    uses, so the unit this seam hands the calculator and the unit the reader's `## Sources` line
    renders are one fact. Without it both legs arrive with `unit=None` and `stats.pair_spread` refuses
    on BOTH_UNITS_REQUIRED -- correct of the calculator, and a refusal of a spread whose unit the card
    states plainly."""
    from leviathan.graphrag.numbers import stats as _ST
    palm = _leg("silver_pink_sheet", "palm_oil_cpo_usd_t", _R2_PALM, "")
    soy = _leg("silver_pink_sheet", "soybean_oil_usd_t", _R2_SOY, "")
    assert A._rv_leg_unit(palm) == A._rv_leg_unit(soy) == "USD/mt"      # off the CARD, not the row
    # the row's OWN unit still wins where a card stamps one, and an unreadable card knows nothing
    assert A._rv_leg_unit(_leg("silver_futures_eod", "settle", [1.0], "US cents/bushel")) == \
        "US cents/bushel"
    assert A._rv_leg_unit(_leg("no_such_card", "no_such_metric", [1.0], "")) is None
    rows, why = A.rv_pair_spread_legs(_R2_SCOPE, [palm, soy])
    assert why is None and rows
    assert rows[0]["rows"][0]["unit"] == "USD/mt"                       # and the mint is NOT unitless
    assert rows[0]["rows"][0]["value"] == _R2_SOY[-1] - _R2_PALM[-1] == 521.0
    # WHY THE FALLBACK IS LOAD-BEARING, through the calculator itself
    bare = _ST.pair_spread([1.0, 2.0], ["a", "b"], None, [3.0, 4.0], ["a", "b"], None,
                           label_a="x", label_b="y")
    assert bare.get("declined") is True


def test_the_declared_price_register_is_the_estates_own_and_narrows_the_registry_to_sixteen():
    """113 (round 1, the metric name) -> 37 (round 2, the row-unit regex) -> 16 metrics, and the 16
    are not a list this lane keeps: they are `cascade._RV_PRICE_SERIES` and `cascade._RV_EOD_LEVEL`,
    read and never re-typed, both bound to `config_check.SYNTHESIZED_PRICE_LEG_ALLOW` by
    `_check_synthesized_price_legs` -- so a new price surface is adjudicated at build time rather than
    admitted by a spelling at serve time."""
    from leviathan.graphrag.numbers import cascade as _csc
    reg = _load_registry()
    head = r2 = r3 = 0
    for tid, spec in reg.tables.items():
        for m, ms in (getattr(spec, "metrics", {}) or {}).items():
            c = _leg(tid, m, [1.0], str(getattr(ms, "unit", "") or ""))
            head += 1 if _head_is_price_call(c) else 0
            r2 += 1 if _r2_is_price_call(c) else 0
            r3 += 1 if A._rv_is_price_call(c) else 0
    assert (head, r2, r3) == (113, 37, 16), (head, r2, r3)
    assert A._rv_declared_price_legs() == (
        frozenset((_csc._RV_PRICE_TABLE, m) for m, _l in _csc._RV_PRICE_SERIES.values())
        | frozenset((_csc._RV_EOD_TABLE, m) for m, _l in _csc._RV_EOD_LEVEL.values()))
    # THE CASE THAT CONDEMNS A SPELLING BELT: the Cotton A Index IS the estate's declared cotton
    # benchmark, and round 2's derived-metric regex refused it through its `index` token.
    cotton = _leg("silver_pink_sheet", "cotton_a_index_usd_t", [1.0], "USD/mt")
    assert _r2_is_price_call(cotton) is False and A._rv_is_price_call(cotton) is True
    # ...and a real price the estate registers for NO market's RV leg stays out (SEAM B's farm price)
    assert A._rv_is_price_call(_leg("silver_wasde", "avg_farm_price", [1.0], "$/bu")) is False


# ── M-4: THE MINTED ROW NAMES ITS TWO MARKETS ON THE READER'S PAGE ──────────────────────────────────
def test_every_minted_rv_row_names_both_markets_through_the_real_citation_producer():
    """ROUND 1 RENDERED "computed statistic pair_spread 2026-01-01..2026-08-01 = -521 USD/mt" --
    `leg_a`/`leg_b` rode the ROW and nothing on a citation reads them, so a signed magnitude reached
    the reader's `## Sources` belonging to nobody (K9-5's own ruled defect, reintroduced by a new
    mint). The subject now rides `query.commodity`, the one scope slot `citations.from_number` already
    renders for a computed row, resolved through the estate's ONE display producer so no slug leaks."""
    from leviathan.graphrag import citations as cit
    calls = [_leg("silver_pink_sheet", "palm_oil_cpo_usd_t", _R2_PALM, "USD/mt"),
             _leg("silver_pink_sheet", "soybean_oil_usd_t", _R2_SOY, "USD/mt")]
    rows, why = A.rv_pair_spread_legs(("malaysian_crude_palm_oil_cme", "soybean_oil_cbot"), calls)
    assert why is None and len(rows) == 2
    labels = [cit.from_number(r, i + 1).label for i, r in enumerate(rows)]
    # RE-BANKED (09-23, lane T, CONTRACT C1's row-identity law): the SUBJECT names the two SERIES the
    # figure was computed over -- World Bank WORLD benchmarks, in the estate's own declared register
    # words -- never the two CME/CBOT contracts the question was routed to, which these legs are not.
    for lab in labels:
        assert "world crude palm oil minus world soybean oil" in lab, lab
        for slug in ("malaysian_crude_palm_oil_cme", "soybean_oil_cbot", "silver_pink_sheet"):
            assert slug not in lab, lab                   # no machine id reaches the reader's page
    assert labels[0].endswith("= -521 USD/mt")
    assert "2026-01-01..2026-08-01" in labels[0]
    # the MARKETS the question named still ride the row, as routing, beside the series subject
    assert rows[0]["rows"][0]["pair_markets"] == A.rv_pair_subject(
        ("malaysian_crude_palm_oil_cme", "soybean_oil_cbot")) == "CME palm oil minus CBOT soybean oil"
    assert rows[0]["query"]["commodity"] == A.rv_pair_series_subject(calls[0], calls[1], None)
    # ...and the MACHINE identity is untouched on the row, exactly as T1-4 requires of a spread
    assert rows[0]["rows"][0]["leg_a"].endswith("palm_oil_cpo_usd_t")
    assert rows[0]["rows"][0]["leg_b"].endswith("soybean_oil_usd_t")
    # the source card is DELIBERATELY not stamped: this row was computed over TWO cards and naming one
    # would attribute a cross-market difference to one market's source (`cascade._stat_display`'s rule)
    assert "source_table" not in rows[0]["rows"][0] and "source_metric" not in rows[0]["rows"][0]


# ── F-1 / ROUND-2 DOCKET #5: AN EMPTY COUNTRY READ SAYS WHICH AXIS TO RULE OUT ──────────────────────
def test_an_empty_country_read_names_the_spelling_axis_and_a_served_read_does_not():
    """THE MEASUREMENT (pre-arm smoke `served_rows`, 419 reads): every silver_psd / silver_psd_attributes
    read spelled `country='united_states'` returned ZERO rows -- 21 of 21 -- while `country='United
    States'` returned a row on 41 of 41, same metrics, same as-of, several minutes apart on one turn.
    There is no refusal site for this: `query.py` compiles a plain equality and Athena answers it
    honestly with nothing, so a wrong spelling and a real absence are indistinguishable from here.

    This CORRECTS rather than deletes: the NO ROWS marker still says there is no number, and one
    sentence behind it names the one axis to rule out. It never re-spells, never re-runs, and never
    serves a figure."""
    empty = FakeClient([
        _resp_u([_tool_use({"table": "silver_psd", "metric": "su_ratio",
                            "commodity": "corn_cbot", "country": "united_states",
                            "period": "2026"}, "a")], "tool_use"),
        _resp_u([_text("nothing came back.")], "end_turn")])
    out = A.answer_numbers("US corn stocks to use?", asof="2026-09-16", client=empty,
                           query_fn=lambda sql: [])
    note = out["calls"][0]["scope_note"]
    assert note.startswith(A._no_rows_note(out["calls"][0]["status"]))     # the marker still leads
    assert "THE COUNTRY SPELLING IS THE FIRST THING TO RULE OUT" in note
    assert "'united_states'" in note
    assert "never as a fact about whether the source publishes the figure" in note
    assert out["calls"][0]["rows"] == []                                   # and NO figure is served
    # a read that RETURNED a row carries no such note...
    served = FakeClient([
        _resp_u([_tool_use({"table": "silver_psd", "metric": "su_ratio", "commodity": "corn_cbot",
                            "country": "United States", "period": "2026"}, "a")], "tool_use"),
        _resp_u([_text("ok")], "end_turn")])
    out2 = A.answer_numbers("US corn stocks to use?", asof="2026-09-16", client=served,
                            query_fn=lambda sql: [{"value": "0.12", "knowledge_date": "2026-09-04"}])
    assert "THE COUNTRY SPELLING" not in str(out2["calls"][0].get("scope_note") or "")
    # ...and neither does an empty read that named NO country, or one on a card with no country axis
    reg = _load_registry()
    assert A._country_axis_empty(_NS(table="silver_psd", country=""), reg) is False
    assert A._country_axis_empty(_NS(table="silver_mpob", country="Malaysia"), reg) is False
    assert A._country_axis_empty(_NS(table="silver_psd", country="world"), reg) is True


# ── ROUND 3, REVIEW MAJOR-4: THE NOTE'S FIRING IS CENSUSED, AND IT FIRES ONLY WHERE MEASURED ────────
# The pre-arm smoke's 47 empty reads, by class, exactly as `prearm_fix_r3/C_census_country_note.py`
# counts them: (table, metric, the country the call named, how many of the 47).
_R3_EMPTY_CORPUS = [
    ("silver_nass_crop_progress", "pct_harvested", "US", 3),
    ("silver_psd", "ending_stocks_mt", "World", 2),
    ("silver_psd", "ending_stocks_mt", "world", 4),
    ("silver_psd", "production_mt", "World", 3),
    ("silver_psd", "production_mt", "united_states", 1),
    ("silver_psd", "production_mt", "world", 6),
    ("silver_psd", "su_ratio", "World", 2),
    ("silver_psd", "su_ratio", "united_states", 10),
    ("silver_psd", "su_ratio", "world", 4),
    ("silver_psd_attributes", "Feed Dom. Consumption", "united_states", 10),
]


def test_the_empty_country_note_fires_only_on_the_cards_its_hazard_was_measured_on():
    """THE DEFECT (round 2): the note fired on THREE terms -- empty read, a country was named, the
    card has a `country_col` -- and its firing was never censused. Measured over the smoke's own 47
    empty reads it fired on 45, and 3 of those 45 are
    `silver_nass_crop_progress.pct_harvested country='US'` where the SAME corpus shows that card
    returning `ok` TWICE on `country='US'`: the spelling is right, the absence is real and seasonal
    (harvest had not started at the 2026-09-07 as-of), and the note told the model to doubt it. A
    correction firing against a TRUE absence is the class this lane exists to remove, pointed the
    other way -- and it is the only misfire the census found.

    THE FOURTH TERM is `_is_fanout_card` (`cascade.PSD_TABLES`): exactly the cards the hazard was
    measured on, and exactly the cards whose NOTES now spell the country values, so the note's own
    remedy is readable wherever it fires. 45 -> 42, the three misfires gone, 42 of 42 on a card that
    answers the re-read the note asks for. The blast radius falls from the 21 cards with a
    `country_col` to 2."""
    reg = _load_registry()
    fired = sum(n for t, _m, c, n in _R3_EMPTY_CORPUS
                if A._country_axis_empty(_NS(table=t, country=c), reg))
    assert sum(n for _t, _m, _c, n in _R3_EMPTY_CORPUS) == 47 - 2      # 45 fired under round 2
    assert fired == 42
    # THE MISFIRE CLASS, by address: gone, and gone for the right reason
    assert A._country_axis_empty(_NS(table="silver_nass_crop_progress", country="US"), reg) is False
    assert getattr(reg.get("silver_nass_crop_progress"), "country_col", None)   # it HAS a country axis
    assert A._is_fanout_card("silver_nass_crop_progress") is False              # ...and is not measured
    # the 21 `united_states` reads where the note is RIGHT still carry it, on BOTH cards
    for tid in ("silver_psd", "silver_psd_attributes"):
        assert A._country_axis_empty(_NS(table=tid, country="united_states"), reg) is True


def test_the_note_points_at_the_card_line_that_actually_exists():
    """The round-2 wording sent the model to "this card's COUNTRY line in the table list above".
    MEASURED: `country_values` -- the field a card wall would print a country enum from -- is EMPTY on
    ALL 41 cards, so no card wall carries such a line; the two cards this note now reaches state their
    spellings in their NOTES, and those notes are what it names."""
    reg = _load_registry()
    assert not any((getattr(s, "country_values", []) or []) for s in reg.tables.values())
    note = A._country_spelling_note("united_states")
    assert "COUNTRY line" not in note
    assert "Re-read this card's NOTES in the table list above" in note
    for tid in ("silver_psd", "silver_psd_attributes"):
        assert "COUNTRY IS THE SOURCE'S OWN TITLE-CASE NAME HERE" in str(reg.get(tid).notes or "")


# ── THE CENSUS FLAG HAS ONE GRAMMAR (lane F review M1) ──────────────────────────────────────────────
@_pytest.mark.parametrize("spelling", ["on", "ON", "1", "true", "TRUE", "yes", "YES", "off", "0", "",
                                       " on ", "no", "y"])
def test_the_cost_census_reader_agrees_with_dispatch_spelling_for_spelling(monkeypatch, spelling):
    """MEASURED BY LANE F: `GRAPHRAG_COST_CENSUS=yes` was TRUE here and FALSE in `dispatch`, so the
    numbers seat -- the largest -- was stamped while the planner's pop and the judge's usage stayed
    dark, and the Spend panel printed a "total" with two seats silently missing. Half-armed is the
    exact class the pre-arm seams commit exists to close. The pin asserts AGREEMENT, not merely a
    shared default."""
    from leviathan.graphrag import dispatch as _dp
    monkeypatch.setenv("GRAPHRAG_COST_CENSUS", spelling)
    assert A._cost_census_on() is _dp._cost_census_on(), spelling
    assert A._cost_census_on() is (spelling.strip().lower() in ("on", "1", "true"))


def test_the_cost_census_is_off_with_the_name_deleted(monkeypatch):
    monkeypatch.delenv("GRAPHRAG_COST_CENSUS", raising=False)
    from leviathan.graphrag import dispatch as _dp
    assert A._cost_census_on() is False and _dp._cost_census_on() is False


# ── ROUND-2 DOCKET #6: THE PSD su_ratio CARD STATES SCOPE AND DENOMINATOR ───────────────────────────
def test_the_psd_su_ratio_card_states_its_denominator_and_the_row_label_carries_the_marketing_year():
    """THE DEFECT (ANSWER_QUALITY.md / docket #6): the max page's 10.72% could not be reconciled by a
    reader with the WASDE 310 / 4,535 balance sheet printed beside it. THE CAUSE IS THE DENOMINATOR --
    `transforms/bronze_to_silver/usda_psd.py:1334` computes `ending_stocks_mt / consumption_mt`, so
    EXPORTS ARE NOT IN IT: 310 / 0.1072 = 2,892 M bu is US DOMESTIC use, not total use. The same fact
    explains the corn/wheat page's 0.652178 for SRW wheat, which is not a readable stocks-to-use number
    beside a WASDE sheet and IS the right ratio of stocks to domestic consumption."""
    from leviathan.graphrag import citations as cit
    desc = str(_load_registry().get("silver_psd").metrics["su_ratio"].desc or "")
    assert "ending_stocks_mt / consumption_mt" in desc              # the producer's own expression
    assert "EXPORTS ARE NOT IN THE DENOMINATOR" in desc             # ...and what that means, in capitals
    assert "FRACTION OF ONE" in desc and "0.1072 is 10.7%" in desc  # the scale, stated
    assert "SCOPE IS THE COUNTRY AND MARKETING YEAR" in desc        # the scope, stated
    assert "WASDE" in desc
    # ROUND 3, REVIEW MAJOR-2: THE WORKED EXAMPLE PUT THE MISLABEL BACK. The round-2 desc read "US SRW
    # wheat reads 0.652 here" -- and 0.652178 is USDA's ALL-CLASS US wheat sheet read under the SRW
    # key, which is the producer fact this whole lane is built on and exactly the sentence
    # `alias_resolution_note` had just stopped teaching ("never quote one as if it were that class's
    # own balance sheet", nine lines away in the same card's own notes). It shipped ungated, on every
    # PSD su_ratio serve, as the CARD's own example.
    assert "SRW wheat reads" not in desc and "SRW" not in desc
    assert "US ALL-CLASS wheat reads 0.652 here" in desc
    # the class name survives ONLY inside the denial, exactly once: the figure is not that class's
    assert desc.lower().count("soft red winter") == 1
    assert "never soft red winter's own" in desc
    # ...and nothing on this card calls months-of-export-cover a stocks-to-use ratio
    mpob = _load_registry().get("silver_mpob")
    assert str(mpob.metrics["su_ratio"].label or "") == "months of export cover"
    assert "It is NOT a stocks-to-use ratio" in str(mpob.metrics["su_ratio"].desc or "")
    # ...and the ROW LABEL carries the marketing year, through the real citation producer
    call = {"query": {"table": "silver_psd", "metric": "su_ratio", "commodity": "corn_cbot",
                      "country": "United States", "period": "2026", "asof": "2026-09-06"},
            "rows": [{"value": 0.1072, "unit": "ratio", "knowledge_date": "2026-09-04"}],
            "status": "ok"}
    # RE-BANKED (09-23 fix round, D3 + CONTRACT C10): the card now DECLARES the basis
    # (`basis_words`, lane T) and the citation label prints it (lane C's pure correction of a label that
    # omitted it); the marketing year still rides the row label. Asserted on the parts, not the joins,
    # so the label's own layout stays lane C's.
    lab = cit.from_number(call, 1).label
    assert lab.startswith("USDA PSD stocks-to-use ratio") and "CBOT corn United States MY2026 = " in lab
    assert _load_registry().get("silver_psd").metrics["su_ratio"].basis_words in lab


def test_the_psd_country_paragraph_does_not_ask_the_model_to_add_the_countries_up():
    """ROUND 3, REVIEW MAJOR-3. The round-2 country paragraph closed with "Name the countries you need
    and add them up", in the FIRST thing the seat reads, and three things were wrong with it, all
    measured in the shipped files:
      (1) the same system prompt forbids it three times ("never invent or recall a figure", "do NOT do
          the arithmetic yourself -- REQUEST it with the compute_stat tool", "you do NOT do the
          arithmetic"), and the card is read ~250 kB earlier;
      (2) THERE IS NO STAT TO REQUEST -- `stats.STAT_NAMES` is extrema, percentile, revision_count,
          spread, streak, window_change, yoy_delta, zscore and nothing there is a cross-series sum, so
          the instruction can only be satisfied by the model's own arithmetic, which mints a figure
          with no handle;
      (3) the sum it invites is the one the estate DE-DUPLICATES -- `cascade` carries
          `eu_member_deduped` because "a naive cross-country World SUM would double-count such a
          member", and 'European Union' is second in this card's own spelling list.
    The honest half of the same sentence survives; the hand sum does not."""
    from leviathan.graphrag.numbers import stats as _ST
    notes = str(_load_registry().get("silver_psd").notes or "")
    assert "add them up" not in notes
    assert "never a sum you add up here" in notes
    assert "say plainly that the world basis is not served" in notes
    assert "do not write \"the world balance sheet carries no figure at this as-of\"" in notes
    # the measurement behind (2), re-run: no stat the model can request sums two series
    assert not ({"sum", "total", "aggregate", "share", "ratio"} & set(_ST.STAT_NAMES))


# ══ THE 09-23 FIX ROUND, LANE T (D5; OWNER DECISION 9) -- THE PAIR SPREAD ROW, GATED BY A KWARG ══════
# The measured turns: quick rv_soyoil_palm (palm 1,117 / soyoil 1,638 USD/mt) and quick rv_palm_rapeoil
# (palm 1,117 / rapeseed oil 1,474 USD/mt), every leg read ONCE for 2026-08-01, and no spread on either
# page. The caller threads `pair_spread=True` ONLY when the board flag is lit (answer._state_board_on);
# this module reads no environment for it.
_T3_PALM_RAPE_Q = ("Set palm oil against rapeseed oil for me -- whose stocks position moved more this year, "
                   "and how do the two read against each other from here?")


def _pink_leg(metric, value, date="2026-08-01"):
    return {"query": {"table": "silver_pink_sheet", "metric": metric},
            "rows": [{"value": value, "unit": "", "data_date": date, "knowledge_date": date}], "status": "ok"}


def _eod_leg(commodity, value, unit, currency, date="2026-09-21"):
    return {"query": {"table": "silver_futures_eod", "metric": "settle", "commodity": commodity},
            "rows": [{"value": value, "unit": unit, "currency": currency, "knowledge_date": date,
                      "contract_month": "2026-11"}], "status": "ok"}


def test_T3_the_three_measured_pairs_521_357_and_the_refused_one():
    """soyoil/palm 521 USD/mt; palm/rapeseed oil 357 USD/mt; MATIF EUR/t against palm USD/mt REFUSED
    and recorded. Every figure is the calculator's (`stats.pair_level_spread`); the sign is the
    question's own order (palm named first on both measured questions)."""
    palm, soy, rape = (_pink_leg("palm_oil_cpo_usd_t", 1117.0), _pink_leg("soybean_oil_usd_t", 1638.0),
                       _pink_leg("rapeseed_oil_usd_t", 1474.0))
    rows, why = A.rv_pair_spread_legs(A.rv_pair_scope(_RV_Q), [palm, soy])
    assert why is None and rows[0]["rows"][0]["value"] == -521.0
    assert rows[0]["query"]["commodity"] == "world crude palm oil minus world soybean oil"
    matif = _eod_leg("french_rapeseed_matif", 552.0, "EUR/t", "EUR")
    scope = A.rv_pair_scope(_T3_PALM_RAPE_Q)
    assert scope == ("malaysian_crude_palm_oil_cme", "rapeseed_oil_zce")
    rows, why = A.rv_pair_spread_legs(scope, [palm, rape, matif])
    assert why is None and rows[0]["rows"][0]["value"] == -357.0
    assert rows[0]["query"]["commodity"] == "world crude palm oil minus world rapeseed oil"
    assert rows[0]["rows"][0]["leg_b"].endswith("rapeseed_oil_usd_t")      # the MATIF leg is not a leg
    # MATIF rapeseed in EUR/t against palm in USD/mt: refused by the calculator, recorded, never converted
    rows, why = A.rv_pair_spread_legs(("malaysian_crude_palm_oil_cme", "french_rapeseed_matif"),
                                      [palm, matif])
    assert rows == [] and "currenc" in why


def test_the_pair_spread_kwarg_arms_the_leg_without_the_env_and_the_prompt_never_moves(monkeypatch):
    """OWNER DECISION 9 (b): minted only when the board flag is lit, and the flag reaches this module as
    a KWARG. Default False: the turn takes no branch and writes no key (byte-identical). True: the leg
    runs and the level is minted. The SYSTEM BLOCK sent to the model is the same string both ways --
    the kwarg never reaches `system_prompt` (the 255 kB cached numbers prefix)."""
    monkeypatch.delenv("GRAPHRAG_RV_PAIR_SPREAD", raising=False)
    off_client, on_client = _two_leg_client("latest"), _two_leg_client("latest")
    off = A.answer_numbers(_RV_Q, asof="2026-09-16", client=off_client,
                           query_fn=_two_leg_query_fn([1117.0], [1638.0]))
    on = A.answer_numbers(_RV_Q, asof="2026-09-16", client=on_client, pair_spread=True,
                          query_fn=_two_leg_query_fn([1117.0], [1638.0]))
    assert "rv_pair_spread" not in off and A.RV_PAIR_UNCOMPUTED_KEY not in off
    assert [c["query"]["table"] for c in off["calls"]] == ["silver_pink_sheet"] * 2
    assert on["rv_pair_spread"]["legs"] == 1
    assert on["calls"][-1]["rows"][0]["value"] == -521.0
    assert off_client.sent[0]["system"] == on_client.sent[0]["system"]
    assert off_client.sent[0]["tools"] == on_client.sent[0]["tools"]


def test_the_pair_spread_kwarg_is_a_no_op_on_a_one_market_question():
    out = A.answer_numbers("What is the palm oil price?", asof="2026-09-16", pair_spread=True,
                           client=FakeClient([_resp_u([_tool_use(_pink("palm_oil_cpo_usd_t", "latest"))],
                                                      "tool_use"),
                                              _resp_u([_text("ok")], "end_turn")]),
                           query_fn=lambda sql: _price_rows([1117]))
    assert "rv_pair_spread" not in out and A.RV_PAIR_UNCOMPUTED_KEY not in out


def test_a_leg_series_is_named_by_the_declared_register_and_never_by_the_routed_market():
    assert A.rv_leg_words(_pink_leg("palm_oil_cpo_usd_t", 1.0)) == "world crude palm oil"
    assert A.rv_leg_words(_pink_leg("rapeseed_oil_usd_t", 1.0)) == "world rapeseed oil"
    assert A.rv_leg_words(_eod_leg("soybean_oil_cbot", 1.0, "US cents/lb", "USD")) == \
        A._reader_words("soybean_oil_cbot")
    assert A.rv_leg_words({"query": {"table": "no_card", "metric": "x"}}) == ""
    # a leg the register cannot name falls back to the MARKET subject, never to a machine id
    unnamed = {"query": {"table": "no_card", "metric": "x"}}
    assert A.rv_pair_series_subject(unnamed, unnamed, ("malaysian_crude_palm_oil_cme", "soybean_oil_cbot")) \
        == A.rv_pair_subject(("malaysian_crude_palm_oil_cme", "soybean_oil_cbot"))


def test_fix_0923_M3c_the_board_kwarg_arms_the_spread_LEVEL_only_never_the_dark_history_leg():
    """09-23 FIX ROUND, review WT M-3 (c): OWNER DECISION 9 licenses the pair's spread LEVEL on a board-lit
    turn and nothing more. With a full shared history served, HEAD's RV leg (behind its own dark flag)
    mints the history spread AND its percentile rank; `level_only` -- what `answer_numbers` passes when
    the board kwarg is on and GRAPHRAG_RV_PAIR_SPREAD is not -- mints ONE row: the calculator's level at
    the newest shared observation, no history read, no rank."""
    calls = [_leg("silver_pink_sheet", "palm_oil_cpo_usd_t", _R2_PALM, "USD/mt"),
             _leg("silver_pink_sheet", "soybean_oil_usd_t", _R2_SOY, "USD/mt")]
    full, why = A.rv_pair_spread_legs(_R2_SCOPE, calls)
    assert why is None and [r["stat_provenance"]["stat"] for r in full] == ["pair_spread", "pair_spread"]
    lvl, why = A.rv_pair_spread_legs(_R2_SCOPE, calls, level_only=True)
    assert why is None and len(lvl) == 1
    assert lvl[0]["stat_provenance"]["stat"] == "pair_level_spread"
    assert lvl[0]["rows"][0]["value"] == _R2_SOY[-1] - _R2_PALM[-1] == 521.0


def test_fix_0924_MAJOR1_a_CHAINED_stat_through_the_real_agent_prints_HEADs_label_never_a_dated_MY(monkeypatch):
    """09-24 (VERIFY_FINAL MAJOR-1), the verifier's reachability turn: lookup (L1, a source-carrying series)
    -> compute_stat extrema on L1 (L2: the CHAINING handle, which carries no source card) -> compute_stat
    window_change on L2, a stat OF a stat. The numbers MODEL is scripted and no GRAPHRAG flag is set; the
    agent, the calculator, the handles and the citation label are real. The chained row's only date is its
    KNOWLEDGE stamp, and the round printed it as a marketing year ("computed statistic change over the
    window MY2026-09-22 = 20.5 US cents/lb"); HEAD 9bb8d596 printed no period there, and neither does this."""
    import os

    from leviathan.graphrag import citations as C
    from leviathan.graphrag.state import __main__ as M
    for k in [k for k in os.environ if k.startswith("GRAPHRAG_")]:
        monkeypatch.delenv(k)
    mirror = M.mirror_query_fn({"silver_futures_eod": M.tape_fixture_rows("soybean_oil_cbot", sessions=6,
                                                                          last="2026-09-22", base=52.0)})

    def _stat(inp, tid):
        return types.SimpleNamespace(type="tool_use", name=A.STATS_TOOL_NAME, input=inp, id=tid)
    client = FakeClient([
        _resp([_tool_use({"table": "silver_futures_eod", "metric": "settle", "commodity": "soybean_oil_cbot",
                          "agg": "series"}, "a")], "tool_use"),
        _resp([_stat({"stat": "extrema", "series_handle": "L1"}, "b")], "tool_use"),
        _resp([_stat({"stat": "window_change", "series_handle": "L2", "t1": 0, "t2": 1}, "c")], "tool_use"),
        _resp([_text("done.")], "end_turn")])
    out = A.answer_numbers("How far apart were the soybean oil high and low this week?", asof="2026-09-23",
                           client=client, query_fn=lambda sql: mirror(sql) if "futures_eod" in sql else [])
    calls = out["calls"]
    assert [c["query"]["metric"] for c in calls] == ["settle", "extrema_min", "extrema_max", "window_change"]
    chained = calls[3]
    assert not chained["rows"][0].get("source_table")               # the chaining handle carries no card
    cit = C.from_number(chained, 4)
    assert cit.label == "computed statistic change over the window  = 20.5 US cents/lb (official)", cit.label
    assert C.printed_period(chained) == ("", None)
    assert cit.date == "2026-09-22"                                 # the stamp rides [known ...], unmoved
