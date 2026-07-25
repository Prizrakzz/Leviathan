"""F8a (latency RCA 2026-07-25): the serving provider DEFAULT is pinned to anthropic.

`params.yaml` said `serving.provider: bedrock` while serving taskdef :64 set `GRAPHRAG_PROVIDER=anthropic`,
and `providers.provider()` reads env FIRST -- so one env var was the only thing keeping serving off the
`global.` cross-region inference profiles. Deleting it armed three things at once, none observable:
cross-region routing (region-less ARNs, Bedrock invocation logging disabled), the SSE slab regression (the
fine-grained-tool-streaming beta defaults OFF on Bedrock), and no `us.`-scoped fallback. The config now
agrees with reality. What must NOT change: env still wins in BOTH directions, and the Bedrock model map
stays intact for deliberate Bedrock use.
"""
from __future__ import annotations

import pytest
from leviathan.graphrag import params as prm
from leviathan.graphrag import providers as pv


@pytest.fixture(autouse=True)
def _clean_params(monkeypatch):
    """Read the real configs/graphrag/params.yaml, and drop the memo afterwards so a later test that
    re-points GRAPHRAG_PARAMS is unaffected."""
    monkeypatch.delenv("GRAPHRAG_PARAMS", raising=False)
    prm.reload()
    yield
    prm.reload()


def test_params_default_provider_is_anthropic(monkeypatch):
    """Tolerant of a public clone with no params.yaml (the house style) -- but FAILS if the yaml says
    bedrock, which is exactly the drift F8a closes."""
    monkeypatch.delenv("GRAPHRAG_PROVIDER", raising=False)
    assert prm.get("serving.provider", "anthropic") == "anthropic"
    assert pv.provider() == "anthropic"                     # no env var is load-bearing any more
    assert pv.resolve_model("claude-sonnet-4-6") == "claude-sonnet-4-6"      # identity on the API lane


def test_env_still_wins_and_the_bedrock_map_is_intact(monkeypatch):
    """F8a pins the DEFAULT only. A deliberate Bedrock run is still one env var away, and the alias map it
    needs is deliberately left in place."""
    monkeypatch.setenv("GRAPHRAG_PROVIDER", "bedrock")
    assert pv.provider() == "bedrock"
    assert pv.resolve_model("claude-sonnet-4-6") == "global.anthropic.claude-sonnet-4-6"
    assert pv.resolve_model("claude-haiku-4-5") == "global.anthropic.claude-haiku-4-5-20251001-v1:0"
    monkeypatch.setenv("GRAPHRAG_PROVIDER", "anthropic")    # ... and back, per-run, no redeploy
    assert pv.provider() == "anthropic"
