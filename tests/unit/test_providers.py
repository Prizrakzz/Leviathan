"""Provider routing (Anthropic API vs Bedrock) + the production serving fallback chain — all mocked.

Pins: the anthropic default (offline behavior byte-identical), the GRAPHRAG_PROVIDER=bedrock switch
(client class + inference-profile model mapping), the backoff retry (transient 429 -> success),
Sonnet->Haiku degradation with the visible caveat + trace tag, correctness-errors-never-retry, and
the deterministic evidence-only floor in respond() (a UI turn must never 500).
"""
from __future__ import annotations

from types import SimpleNamespace

import anthropic
import httpx
import pytest
import tenacity

from leviathan.causal import schema as cs
from leviathan.graphrag import answer as an
from leviathan.graphrag import graph as g
from leviathan.graphrag import providers as pv


# ── fakes ──────────────────────────────────────────────────────────────────────────────────────────
def _rate_limited() -> anthropic.RateLimitError:
    req = httpx.Request("POST", "https://fake")
    return anthropic.RateLimitError("rate limited", response=httpx.Response(429, request=req), body=None)


def _ok(payload: dict | None = None, stop: str = "tool_use"):
    blk = SimpleNamespace(type="tool_use", input=payload or {"tldr": "t", "mechanism": "m", "sources": []})
    usage = SimpleNamespace(input_tokens=1, output_tokens=1,
                            cache_creation_input_tokens=0, cache_read_input_tokens=0)
    return SimpleNamespace(stop_reason=stop, content=[blk], usage=usage)


class _FakeClient:
    """Scripted client: each messages.create pops the next item (Exception -> raised)."""

    def __init__(self, script):
        self._script = list(script)
        self.calls: list[dict] = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kw):
        self.calls.append(kw)
        item = self._script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch):
    """Zero the exponential waits AND pin the provider to anthropic — the SITE default lives in the
    gitignored params.yaml (flipped to bedrock 2026-07-04), and tests must not depend on it. The
    bedrock-switch test overrides the env itself."""
    monkeypatch.setattr(pv, "wait_exponential", lambda **kw: tenacity.wait_none())
    monkeypatch.setenv("GRAPHRAG_PROVIDER", "anthropic")


_TOOL = {"name": "emit_answer", "input_schema": {"type": "object"}}


# ── provider factory ───────────────────────────────────────────────────────────────────────────────
def test_anthropic_provider_passes_models_through(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API", "sk-test")
    assert pv.provider() == "anthropic"                                   # env pin (fixture) wins
    assert pv.resolve_model("claude-sonnet-4-6") == "claude-sonnet-4-6"   # identity — offline unchanged
    assert isinstance(pv.make_client(), anthropic.Anthropic)
    monkeypatch.delenv("GRAPHRAG_PROVIDER")                               # env unset -> params/site default
    assert pv.provider() in ("anthropic", "bedrock")                      # whatever params.yaml says today


def test_bedrock_switch_maps_profiles_and_client(monkeypatch):
    monkeypatch.setenv("GRAPHRAG_PROVIDER", "bedrock")
    assert pv.provider() == "bedrock"
    assert pv.resolve_model("claude-sonnet-4-6") == "global.anthropic.claude-sonnet-4-6"
    assert pv.resolve_model("claude-haiku-4-5") == "global.anthropic.claude-haiku-4-5-20251001-v1:0"
    assert pv.resolve_model("unmapped-model") == "unmapped-model"          # unknown alias passes through
    assert isinstance(pv.make_client(), anthropic.AnthropicBedrock)


# ── serving_call: the fallback chain ───────────────────────────────────────────────────────────────
def test_transient_throttle_retries_then_succeeds():
    c = _FakeClient([_rate_limited(), _rate_limited(), _ok()])
    out, degraded = pv.serving_call(c, "sys", "user", model="claude-sonnet-4-6", tool=_TOOL)
    assert out["tldr"] == "t" and degraded is None
    assert len(c.calls) == 3 and all(k["model"] == "claude-sonnet-4-6" for k in c.calls)


def test_persistent_throttle_degrades_to_haiku_and_tags():
    c = _FakeClient([_rate_limited()] * 4 + [_ok()])
    out, degraded = pv.serving_call(c, "sys", "user", model="claude-sonnet-4-6", tool=_TOOL,
                                    degrade_to="claude-haiku-4-5")
    assert degraded == "claude-haiku-4-5" and out["tldr"] == "t"
    assert c.calls[-1]["model"] == "claude-haiku-4-5"                      # the rescue ran on Haiku
    assert all(k["model"] == "claude-sonnet-4-6" for k in c.calls[:4])     # after 4 primary attempts


def test_correctness_errors_never_retry_or_degrade():
    c = _FakeClient([_ok(stop="max_tokens")])                              # truncation guard fires
    with pytest.raises(ValueError):
        pv.serving_call(c, "sys", "user", model="claude-sonnet-4-6", tool=_TOOL,
                        degrade_to="claude-haiku-4-5")
    assert len(c.calls) == 1                                               # no retry, no Haiku attempt


def test_raises_when_degraded_also_fails_and_skips_same_model_degrade():
    c = _FakeClient([_rate_limited()] * 6)
    with pytest.raises(anthropic.RateLimitError):
        pv.serving_call(c, "sys", "user", model="claude-sonnet-4-6", tool=_TOOL,
                        degrade_to="claude-haiku-4-5")
    assert len(c.calls) == 6                                               # 4 primary + 2 degraded
    c2 = _FakeClient([_rate_limited()] * 4)
    with pytest.raises(anthropic.RateLimitError):
        pv.serving_call(c2, "sys", "user", model="claude-haiku-4-5", tool=_TOOL,
                        degrade_to="claude-haiku-4-5")                     # degrade == primary -> skip
    assert len(c2.calls) == 4


# ── degraded caveat surfaces in the rendered answer ────────────────────────────────────────────────
def _graph() -> g.CausalGraph:
    coffee = cs.CausalContract(contract="arabica_coffee", aliases=["arabica"],
                               drivers=[cs.Driver(id="frost", type="hazard", sign="+", mechanism="m")])
    return g.CausalGraph({"arabica_coffee": coffee}, silver=set())


def _retrieve(q, contract, *, k, asof=None, near=None):
    return [{"date": "2021-07-20", "source": "GAIN", "source_key": f"s3://{contract}", "text": "frost note"}]


def test_degraded_tag_becomes_visible_caveat_and_trace():
    def degraded_call(system, user, *, model, tool):
        return {"tldr": "t", "mechanism": "m", "sources": [], "_degraded_model": "claude-haiku-4-5"}

    out = an.answer("arabica frost outlook", graph=_graph(), retrieve=_retrieve, call=degraded_call)
    assert out["answer"].startswith("> **Degraded answer.**")
    assert "claude-haiku-4-5" in out["answer"]
    assert out["trace"]["degraded_model"] == "claude-haiku-4-5"
    assert "_degraded_model" not in out["structured"]                      # tag never renders as content


def test_undegraded_answer_carries_no_caveat():
    def clean_call(system, user, *, model, tool):
        return {"tldr": "t", "mechanism": "m", "sources": []}

    out = an.answer("arabica frost outlook", graph=_graph(), retrieve=_retrieve, call=clean_call)
    assert "Degraded answer" not in out["answer"] and "degraded_model" not in out["trace"]


# ── the deterministic floor in respond() ───────────────────────────────────────────────────────────
def test_respond_floors_to_evidence_only_when_reasoner_dies(monkeypatch):
    from leviathan.graphrag import orchestrator as orch
    monkeypatch.setenv("GRAPHRAG_PLANNER", "onehop")   # floor is planner-agnostic; skip the L2 embed load

    def dead_call(system, user, *, model, tool):
        raise RuntimeError("provider hard down")

    res = orch.respond("arabica frost outlook", graph=_graph(), asof="2024-01-01", call=dead_call,
                       retrieve=_retrieve, classify=lambda q, call=None: {"intent": "reasoning"})
    assert res["trace"]["floor"] == "evidence_only"
    assert "RuntimeError" in res["trace"]["error"]
    assert res["answer"].startswith("**Service notice.**")                 # honest banner, not a 500
    assert res["intent"] == "reasoning" and res["intent_decision"]["intent"] == "reasoning"
    assert res["structured"] is None and res["model"] == "(unavailable)"
