"""D-AM Phase 0 (AGENTIC_MODES_WAVE_PLAN 1..4): kind_history audit, legacy-live fold, the
tracekeys registry contract, and usage/cost threading. Hermetic — no S3/Athena/LLM spend."""
from __future__ import annotations

import pathlib
import types

from leviathan.causal import schema as cs
from leviathan.graphrag import answer as an
from leviathan.graphrag import extract as ex
from leviathan.graphrag import graph as g
from leviathan.graphrag import orchestrator as orch
from leviathan.graphrag import providers as pv
from leviathan.graphrag import tracekeys as tk


def _graph() -> g.CausalGraph:
    corn = cs.CausalContract(contract="corn", aliases=["maize"],
                             drivers=[cs.Driver(id="drought", type="hazard", sign="+",
                                                mechanism="dryness cuts yield")])
    return g.CausalGraph({"corn": corn}, silver=set())


def _force(kind):
    return lambda q, call=None: {"intent": kind, "needs_numbers": kind in ("numbers_only", "hybrid"),
                                 "needs_reasoning": kind in ("reasoning", "hybrid")}


def _reason_call(system, user, *, model, tool):
    return {"tldr": "x", "mechanism": "y", "diagram_mermaid": "", "sources": []}


def _retrieve(q, node, *, k, asof=None, near=None):
    return [{"date": "2024-01-01", "source": "usda_wasde", "source_key": f"s3://{node}", "text": "note"}]


# ── D-AM-1: kind_history ───────────────────────────────────────────────────────────────────────────
def test_kind_history_stamped_on_classify_path():
    out = orch.respond("why is corn bid on a drought", graph=_graph(), asof="2024-06-01",
                       classify=_force("reasoning"), call=_reason_call, retrieve=_retrieve)
    assert out["intent_decision"]["kind_history"] == ["classify:None->reasoning"]


def test_kind_history_is_final_before_the_contract_selector():
    """The selector's 'kind is FINAL here' is now a recorded fact: the stamped intent equals the
    last transition's target, and the response_contract decision rides the SAME decided dict."""
    out = orch.respond("why is corn bid on a drought", graph=_graph(), asof="2024-06-01",
                       classify=_force("reasoning"), call=_reason_call, retrieve=_retrieve)
    dec = out["intent_decision"]
    assert dec["kind_history"][-1].endswith(f"->{dec['intent']}")
    assert "response_contract" in dec                        # selector stamped after the pipeline


# ── D-AM-2: the legacy live early-return is folded into the shared pipeline ───────────────────────
def test_legacy_live_fold_carries_full_decision_keys(monkeypatch):
    def _fake_live(q, a, **k):
        return {"answer": "hx", "intent": "live", "trace": {}, "citations": [], "evidence": [],
                "number_calls": [], "structured": None, "contract": None, "contracts": []}
    monkeypatch.setattr(orch, "run_live", _fake_live)

    def _never(q, call=None):
        raise AssertionError("classify must not be consulted on an explicit live ask (fold parity)")
    out = orch.respond("any news on corn today?", graph=_graph(), classify=_never)
    dec = out["intent_decision"]
    assert dec["intent"] == "live" and dec["live_checked"] is True          # old contract preserved
    assert dec["kind_history"] == ["legacy_live:None->live"]                # D-AM-1 audit
    # D-AM-2 acceptance: the lane now carries the same decision keys as every other lane.
    assert "response_contract" in dec and dec["response_contract"]["resolved"] is None


def test_legacy_live_fold_pit_killswitch_still_demotes(monkeypatch):
    """A historical as-of must still never reach the news agent from the legacy leg."""
    called = {"live": False}

    def _fake_live(q, a, **k):
        called["live"] = True
        return {"answer": "", "intent": "live", "trace": {}, "citations": [], "evidence": [],
                "number_calls": [], "structured": None, "contract": None, "contracts": []}
    monkeypatch.setattr(orch, "run_live", _fake_live)
    out = orch.respond("any news on corn today?", graph=_graph(), asof="2024-06-01",
                       classify=_force("reasoning"), call=_reason_call, retrieve=_retrieve)
    assert called["live"] is False and out["intent"] == "reasoning"
    assert out["intent_decision"]["live_suppressed_pit"] is True


# ── D-AM-3: the tracekeys registry is actually load-bearing ───────────────────────────────────────
_EVAL_SRC = (pathlib.Path(__file__).resolve().parents[2]
             / "src" / "leviathan" / "graphrag" / "eval.py").read_text(encoding="utf-8")


def test_eval_record_derives_from_the_registry():
    assert "tk.TRACE_RECORD_KEYS" in _EVAL_SRC and "tk.DECISION_RECORD_KEYS" in _EVAL_SRC


def test_registry_contains_every_known_mint():
    for key in ("fork_basis", "tldr_direction", "record_through", "response_contract", "synth_usage"):
        assert key in tk.TRACE_RECORD_KEYS
    assert dict(tk.DECISION_RECORD_KEYS)["kind_history"] == "kind_history"
    assert dict(tk.DECISION_RECORD_KEYS)["response_contract"] == "response_contract_decision"
    assert len(set(tk.TRACE_RECORD_KEYS)) == len(tk.TRACE_RECORD_KEYS)      # no dup columns


# ── D-AM-4: usage threading + cost arithmetic ─────────────────────────────────────────────────────
def test_serving_call_fills_usage_sink_and_keeps_return_shape(monkeypatch):
    monkeypatch.setattr(ex, "call_opus",
                        lambda *a, **k: ({"ok": 1}, ex.Usage(input_tokens=100, output_tokens=20,
                                                             cache_creation=7, cache_read=900)))
    sink: list = []
    out, degraded = pv.serving_call(object(), "s", "u", model="m", tool={"name": "t"}, usage_sink=sink)
    assert out == {"ok": 1} and degraded is None
    assert len(sink) == 1 and sink[0].cache_read == 900


def test_call_opus_wrapper_attaches_usage_tag(monkeypatch):
    monkeypatch.setattr(pv, "make_client", lambda: object())

    def fake_serving(client, system, user, **kw):
        kw["usage_sink"].append(ex.Usage(input_tokens=10, output_tokens=5, cache_read=3))
        return {"tldr": "x"}, None
    monkeypatch.setattr(pv, "serving_call", fake_serving)
    out = an._call_opus("sys", "user", model="claude-sonnet-4-6", tool={"name": "emit_answer"})
    assert out["_usage"]["in"] == 10 and out["_usage"]["out"] == 5
    assert out["_usage"]["model"] == pv.resolve_model("claude-sonnet-4-6")
    assert an._pop_usage(out) == {"model": pv.resolve_model("claude-sonnet-4-6"),
                                  "in": 10, "out": 5, "cache_read": 3, "cache_write": 0}
    assert "_usage" not in out                                # popped: never renders as content
    assert an._pop_usage("not a dict") is None


def test_serving_cost_arithmetic():
    # sonnet-4-6 at $3/$15: 1M uncached in + 1M out = 3 + 15
    assert pv.serving_cost_usd("claude-sonnet-4-6", 1_000_000, 1_000_000) == 18.0
    # cache write 1.25x, read 0.1x (5-minute-TTL serving arithmetic, NOT the 1h extraction lane's 2x)
    c = pv.serving_cost_usd("claude-sonnet-4-6", 0, 0, cache_read=1_000_000, cache_write=1_000_000)
    assert abs(c - (0.3 + 3.75)) < 1e-9
    assert pv.serving_cost_usd("claude-nonexistent", 1, 1) is None    # absent, never fabricated


def test_synth_usage_reaches_the_onehop_trace():
    def _call(system, user, *, model, tool):
        return {"tldr": "x", "mechanism": "y", "diagram_mermaid": "", "sources": [],
                "_usage": {"model": "claude-sonnet-4-6", "in": 11, "out": 7,
                           "cache_read": 0, "cache_write": 0}}
    out = an.answer("why is corn bid on a drought", graph=_graph(), asof="2024-06-01",
                    call=_call, retrieve=_retrieve)
    assert out["trace"]["synth_usage"]["in"] == 11
    assert "_usage" not in (out.get("structured") or {})


# ── D-AM-5: the synthesis-model seam fills the DEFAULT only ───────────────────────────────────────
def test_synth_model_env_fills_default_only(monkeypatch):
    seen = []

    def _call(system, user, *, model, tool):
        seen.append(model)
        return {"tldr": "x", "mechanism": "y", "diagram_mermaid": "", "sources": []}
    monkeypatch.setenv("GRAPHRAG_SYNTH_MODEL", "claude-sonnet-5")
    an.answer("why is corn bid", graph=_graph(), asof="2024-06-01", call=_call, retrieve=_retrieve)
    assert seen[-1] == "claude-sonnet-5"                       # default filled by env
    an.answer("why is corn bid", graph=_graph(), asof="2024-06-01", call=_call, retrieve=_retrieve,
              model="claude-haiku-4-5")
    assert seen[-1] == "claude-haiku-4-5"                      # explicit caller arg always wins
