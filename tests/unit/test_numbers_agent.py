"""Numbers SQL agent loop — mocked LLM + injected Athena (no spend).

The load-bearing assertion: even if the model tries to pass its own as-of date, the harness FORCES the caller's
asof — the agent has no lever to see the future.
"""
from __future__ import annotations

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
