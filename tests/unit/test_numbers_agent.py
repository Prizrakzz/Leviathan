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
    assert "[TRUNCATED at row cap 4: OLDEST kept, NOT the latest print]" in line
    call["truncated"] = False
    assert "TRUNCATED" not in _ev._num_line({"number_calls": [call]})


def test_format_provenance_says_so_when_the_read_hit_the_row_cap():
    # Item 62: at the cap the OLDEST 5,000 rows are kept, so "latest" is honest-looking and wrong.
    line = A.format_provenance([_eod_call([_EOD_ROW] * 4, limit=4)])[0]
    assert "row cap 4 reached" in line and "NOT the latest print" in line
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
