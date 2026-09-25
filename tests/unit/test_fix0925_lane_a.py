"""09-25 FIX ROUND 3 -- LANE A, ITEM A-4: THE NUMBERS SEAT'S FAILURE REACHES THE RECORD AND THE PAGE.

MEASURED on the 09-25 tariff turn (deep, board lit; Batch job b372544e, CloudWatch): the numbers agent's ONE
round stopped at max_tokens -- "[numbers-thinking] stop=max_tokens in=162 out=6000 cache_read=102568
cache_write=0" -- the agent's truncation sentinel raised, and `orchestrator.run_hybrid` swallowed the
exception into `{"calls": [], "error": ...}`. The message reached no artifact, the round's spend (priced
$0.1213 at claude-sonnet-5) died inside the agent's own list, and the writer was handed the 68-character
"SILVER NUMBERS (observed values, as-known at asof):\\n(none retrieved)" -- a failed lookup that reads as a
record with nothing in it.

What this deck pins, through the REAL `run_hybrid` (the writer stubbed at `an.answer`, the synthesis-time
join driven exactly as the writer seam drives it):
  * the seat's failure rides the trace as `numbers_error` {kind, error, ms} and the per-answer record lifts
    it (`tracekeys.TRACE_SPLAT_KEYS`, absent on every healthy turn);
  * the caller owns the usage accumulator: a seat that declares `usage_sink` keeps the rounds it spent before
    it raised on `numbers_usage`, priced by the eval's one arithmetic; a seat with HEAD's signature is
    called exactly as HEAD calls it;
  * under GRAPHRAG_STATE_BOARD the numbers block states that the lookup could not be completed (one plain
    clause; every figure is a reading printed this turn), and with the flag off the block is HEAD's.
The first pin drives the REAL agent (its truncation sentinel, armed by GRAPHRAG_NUMBERS_THINKING=adaptive)
with a scripted client; nothing else is stubbed.
"""
from __future__ import annotations

import types

import pytest
from leviathan.graphrag import answer as an
from leviathan.graphrag import eval as ev
from leviathan.graphrag import orchestrator as orch
from leviathan.graphrag import tracekeys as tk
from leviathan.graphrag.numbers import agent as na

QUESTION = ("What has China's tariff on US soybeans done to US export pace and the balance sheet this year, "
            "and what should I watch?")
ASOF = "2026-09-25"
HEAD_BLOCK = "SILVER NUMBERS (observed values, as-known at asof):\n(none retrieved)"


def _writer_capturing(seen: dict):
    def _writer(query, *, extra_resolver=None, **kw):
        ctx, calls = extra_resolver()                    # the synthesis-time join, as the writer seam does
        seen["context"], seen["calls"] = ctx, calls
        return {"answer": "(writer stubbed)", "trace": {}}
    return _writer


class _TruncatingClient:
    """The tariff turn's one round, verbatim in shape: a max_tokens stop with no tool_use block."""
    def __init__(self):
        usage = types.SimpleNamespace(input_tokens=162, output_tokens=6000, cache_read_input_tokens=102568,
                                      cache_creation_input_tokens=0)
        resp = types.SimpleNamespace(content=[types.SimpleNamespace(type="thinking", thinking="...")],
                                     stop_reason="max_tokens", usage=usage)
        self.messages = types.SimpleNamespace(create=lambda **kw: resp)


def test_A4_the_real_agents_truncation_reaches_the_record_and_the_board_block_says_it_failed(monkeypatch):
    seen: dict = {}
    monkeypatch.setattr(an, "answer", _writer_capturing(seen))
    monkeypatch.setenv("GRAPHRAG_NUMBERS_THINKING", "adaptive")
    monkeypatch.setenv("GRAPHRAG_PROVIDER", "anthropic")
    from leviathan.graphrag import providers as pv
    monkeypatch.setattr(pv, "provider", lambda: "anthropic")
    monkeypatch.setattr(pv, "supports_adaptive", lambda m: True)
    monkeypatch.setenv("GRAPHRAG_STATE_BOARD", "on")
    out = orch.run_hybrid(QUESTION, ASOF, graph=None, client=_TruncatingClient(), numbers_model="claude-sonnet-5",
                          query_fn=lambda sql: [])
    err = (out.get("trace") or {}).get("numbers_error")
    assert err and err["kind"] == "RuntimeError", out.get("trace")
    assert "TRUNCATED at max_tokens" in err["error"] and isinstance(err["ms"], int), err
    # the record lifts it verbatim (a splat: absent on a healthy row, present here)
    rec = ev._per_answer_record({"q": {"id": "tariff"}, "out": out}, "single")
    assert rec["numbers_error"] == err
    # THE PAGE: the writer's numbers block now SAYS the lookup failed, in one clause, and names the figures it
    # may still use -- the state block's own; HEAD handed it the bare 68-character "(none retrieved)"
    ctx = seen["context"]
    assert ctx.startswith(HEAD_BLOCK) and len(ctx) > len(HEAD_BLOCK)
    assert an.NUMBERS_BUDGET_MARK in ctx and "could not be completed" in ctx
    assert "Every figure you give is a reading printed this turn, at its own handle" in ctx
    assert "block" not in ctx[len(HEAD_BLOCK):]                   # the clause names no instrument (A-5)
    assert seen["calls"] == []
    # FLAG OFF: the failure is still ON THE RECORD (an observability stamp, absent on every healthy turn), and
    # the block the writer reads is HEAD's to the byte
    monkeypatch.delenv("GRAPHRAG_STATE_BOARD")
    seen.clear()
    out_off = orch.run_hybrid(QUESTION, ASOF, graph=None, client=_TruncatingClient(),
                              numbers_model="claude-sonnet-5", query_fn=lambda sql: [])
    assert (out_off.get("trace") or {}).get("numbers_error", {}).get("kind") == "RuntimeError"
    assert seen["context"] == HEAD_BLOCK


def test_A4_a_seat_that_declares_usage_sink_keeps_its_spend_when_it_raises(monkeypatch):
    """THE CALLER OWNS THE ACCUMULATOR: the rounds the seat spent before it raised ride `numbers_usage` on the
    same key a clean return stamps, so the eval's one arithmetic prices the failed seat -- here the tariff
    turn's own round, $0.1212564 at claude-sonnet-5."""
    row = {"model": "claude-sonnet-5", "in": 162, "out": 6000, "cache_read": 102568, "cache_write": 0}

    def _agent(question, asof, *, usage_sink=None, **kw):
        usage_sink.append(dict(row))
        raise RuntimeError("numbers-thinking turn TRUNCATED at max_tokens=6000")

    monkeypatch.setattr(na, "answer_numbers", _agent)
    monkeypatch.setattr(an, "answer", _writer_capturing({}))
    assert orch._numbers_takes_usage_sink() is True
    tr = orch.run_hybrid(QUESTION, ASOF, graph=None).get("trace") or {}
    assert tr["numbers_usage"] == [row]
    assert tr["numbers_error"]["kind"] == "RuntimeError"
    total, seats = ev._turn_cost_total_usd(tr)
    assert seats is not None and abs(seats["numbers"] - 0.1212564) < 1e-9, seats


def test_A4_a_seat_with_HEADs_signature_is_called_exactly_as_HEAD_calls_it(monkeypatch):
    """No `usage_sink` declared -> no kwarg passed (the signature probe), no TypeError, and the failure is
    still on the record; with no accumulator there is no spend to carry, and none is invented."""
    got: dict = {}

    def _agent(question, asof, **kw):
        got["kwargs"] = sorted(kw)
        raise ValueError("seat fell over")

    monkeypatch.setattr(na, "answer_numbers", _agent)
    monkeypatch.setattr(an, "answer", _writer_capturing({}))
    assert orch._numbers_takes_usage_sink() is False
    tr = orch.run_hybrid(QUESTION, ASOF, graph=None).get("trace") or {}
    assert "usage_sink" not in got["kwargs"], got                   # HEAD's kwargs, and only HEAD's
    assert tr["numbers_error"] == {"kind": "ValueError", "error": "seat fell over", "ms": tr["numbers_error"]["ms"]}
    assert "numbers_usage" not in tr


@pytest.mark.parametrize("board", [False, True])
def test_A4_a_healthy_seat_stamps_nothing_new_and_its_block_is_HEADs(board, monkeypatch):
    call = {"query": {"table": "silver_psd", "metric": "exports_mt", "commodity": "soybeans_cbot",
                      "country": "United States", "period": "2026"},
            "rows": [{"value": 47.2, "unit": "MMT", "knowledge_date": "2026-09-11"}], "status": "ok"}

    def _agent(question, asof, **kw):
        return {"answer": "ok", "calls": [call]}

    seen: dict = {}
    monkeypatch.setattr(na, "answer_numbers", _agent)
    monkeypatch.setattr(an, "answer", _writer_capturing(seen))
    if board:
        monkeypatch.setenv("GRAPHRAG_STATE_BOARD", "on")
    else:
        monkeypatch.delenv("GRAPHRAG_STATE_BOARD", raising=False)
    tr = orch.run_hybrid(QUESTION, ASOF, graph=None).get("trace") or {}
    assert "numbers_error" not in tr
    calls = an._display_stamped([call]) if board else [call]
    assert seen["context"] == orch._numbers_block(calls)
    assert "SCOPE NOTE" not in seen["context"]


def test_A4_the_failure_key_is_a_splat_at_the_registry_tail():
    assert tk.TRACE_SPLAT_KEYS[-1] == "numbers_error"
    assert "numbers_error" not in tk.TRACE_RECORD_KEYS
    off = ev._per_answer_record({"q": {"id": "x"}, "out": {"trace": {}}}, "single")
    assert "numbers_error" not in off
