"""Serving-side model provider — Anthropic API vs Amazon Bedrock — plus the production fallback chain.

SERVING ONLY. The offline/authoring path (Opus extraction, Anthropic Batch chunking, the Opus judge)
stays on the Anthropic API unconditionally: Opus is Bedrock-denied on this account and the Batch/Files
APIs do not exist on Bedrock. Serving (Sonnet 4.6 reasoner/planner + Haiku 4.5 numbers/summary) can run
on either provider:

  provider = GRAPHRAG_PROVIDER env  >  params serving.provider  >  "anthropic"

Bedrock uses the legacy ``anthropic.AnthropicBedrock`` client (bedrock-runtime InvokeModel — the same
auth surface as the in-cloud Haiku chunking IAM grant) with cross-region inference-profile ids; the
Mantle client 404s on profile ids (probed 2026-07-04: legacy passed forced-tool + manual prompt-cache
write->read on both profiles, Mantle failed both). Manual ``cache_control`` blocks work identically on
both providers, so the serving prompt-cache economics carry over unchanged.

The FALLBACK CHAIN (the gap a UI can't ship without — serving previously had zero retries):
  1. typed-exception backoff retry (429 / connection / >=500 incl. 529 overloaded),
  2. one degraded-model attempt (reasoner: Sonnet -> Haiku) tagged so the answer carries a visible
     caveat and the trace records it,
  3. raise — the orchestrator's evidence-only floor is the last resort.
Truncation / no-tool-block ``ValueError`` from call_opus propagates untouched: those are correctness
failures, and retrying or degrading on them would hide real bugs.

Rollback: GRAPHRAG_PROVIDER=anthropic (per-run, instant)."""
from __future__ import annotations

import os
from typing import Optional

import anthropic
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from leviathan.graphrag import extract as ex
from leviathan.graphrag import params as _prm

# Cross-region inference profiles, ACTIVE on this account (Phase 0 probe). params.yaml
# serving.bedrock_models may override; these code defaults are the authority when it doesn't.
BEDROCK_MODELS = {
    "claude-sonnet-4-6": "global.anthropic.claude-sonnet-4-6",
    "claude-haiku-4-5": "global.anthropic.claude-haiku-4-5-20251001-v1:0",
}

# Availability errors only — 429 (Bedrock throttles surface as HTTP 429 through the SDK client),
# network, and >=500 (includes 529 overloaded). 4xx correctness errors never retry.
RETRYABLE = (anthropic.RateLimitError, anthropic.APIConnectionError, anthropic.InternalServerError)


def provider() -> str:
    """'anthropic' | 'bedrock'. Env beats params beats the anthropic default."""
    return os.environ.get("GRAPHRAG_PROVIDER") or str(_prm.get("serving.provider", "anthropic"))


def resolve_model(model: str) -> str:
    """Map a serving alias to the active provider's id (identity on the Anthropic API)."""
    if provider() != "bedrock":
        return model
    mapped = _prm.get("serving.bedrock_models", BEDROCK_MODELS)
    return (mapped.get(model) if isinstance(mapped, dict) else None) or BEDROCK_MODELS.get(model, model)


def make_client():
    """The serving client for the active provider. Bedrock auth is the boto3 credential chain
    (task role in-cloud), Anthropic is the .env/env API key — same resolution the offline path uses."""
    if provider() == "bedrock":
        return anthropic.AnthropicBedrock(aws_region=os.environ.get("AWS_REGION", "us-east-1"))
    from leviathan.graphrag import batch_extract as bx
    return anthropic.Anthropic(api_key=bx._api_key())


def with_retry(fn):
    """Run fn() under the serving backoff policy (availability errors only). For raw
    client.messages.create loops (the numbers agent) that can't route through serving_call."""
    @retry(retry=retry_if_exception_type(RETRYABLE), reraise=True,
           wait=wait_exponential(multiplier=2, min=2, max=30), stop=stop_after_attempt(4))
    def go():
        return fn()
    return go()


def serving_call(client, system, user, *, model: str, max_tokens: int = 4096, tool: dict,
                 degrade_to: Optional[str] = None) -> tuple[dict, Optional[str]]:
    """One forced-tool serving call with the full fallback chain. Returns (tool_input, degraded_model)
    where degraded_model is None on the primary path and the ALIAS (e.g. 'claude-haiku-4-5') when the
    degraded attempt served the answer — callers surface that as a visible caveat + trace entry."""
    try:
        out, _ = with_retry(lambda: ex.call_opus(client, system, user, model=model,
                                                 max_tokens=max_tokens, tool=tool))
        return out, None
    except RETRYABLE:
        fallback = resolve_model(degrade_to) if degrade_to else None
        if not fallback or fallback == model:
            raise

        @retry(retry=retry_if_exception_type(RETRYABLE), reraise=True,
               wait=wait_exponential(multiplier=2, min=2, max=8), stop=stop_after_attempt(2))
        def degraded():
            return ex.call_opus(client, system, user, model=fallback, max_tokens=max_tokens, tool=tool)
        out, _ = degraded()
        return out, degrade_to


def serving_call_stream(client, system, user, *, model: str, max_tokens: int = 4096, tool: dict,
                        degrade_to: Optional[str] = None, on_token) -> tuple[dict, Optional[str]]:
    """Streaming variant of serving_call: relays the tool's input_json_delta text via `on_token` as the note
    generates, and returns the SAME (tool_input, degraded_model). Robustness is preserved: an availability
    error degrades to the fallback model (buffered — the fast path already failed), and any other stream-path
    error falls back to the buffered `serving_call` on the primary model. So streaming is pure upside."""
    try:
        out, _ = with_retry(lambda: ex.call_opus_stream(client, system, user, model=model,
                                                         max_tokens=max_tokens, tool=tool, on_token=on_token))
        return out, None
    except RETRYABLE:
        fallback = resolve_model(degrade_to) if degrade_to else None
        if not fallback or fallback == model:
            raise

        @retry(retry=retry_if_exception_type(RETRYABLE), reraise=True,
               wait=wait_exponential(multiplier=2, min=2, max=8), stop=stop_after_attempt(2))
        def degraded():
            return ex.call_opus(client, system, user, model=fallback, max_tokens=max_tokens, tool=tool)
        out, _ = degraded()
        return out, degrade_to
    except Exception:  # noqa: BLE001 — a streaming-specific failure must never lose the answer
        return serving_call(client, system, user, model=model, max_tokens=max_tokens, tool=tool,
                            degrade_to=degrade_to)
