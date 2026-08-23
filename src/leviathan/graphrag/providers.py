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


# A per-request WALL-CLOCK read timeout so a hung/half-open connection can never freeze a turn. The
# 2026-07-11 authoritative-run autopsy pinned the eval freeze to the BUFFERED serving_call path
# (`client.messages.create`, non-streaming -- the eval never passes on_token, so answer.py:857-860 takes
# the buffered branch, NOT serving_call_stream): on the deployed image make_client set no explicit client
# timeout, so the SDK's 600s nonstreaming default applied AND was retried by both the SDK's own
# max_retries and tenacity, amplifying a post-transient stalled read into a 29-31min silence with no
# exception for the degrade chain (which only catches RAISES) to see. An explicit httpx READ timeout
# converts "no bytes for 300s" into a raise -> the serving fallback chain / evidence floor
# degrades-and-completes the turn (the path the model=(unavailable) turn already proved works). Streaming
# keeps a SEPARATE serving/SSE half-open-socket hazard; read=300 bounds it there too, but the streaming
# path is NOT what froze the eval. 300s is far above any healthy call (heavy synthesis streams tokens
# continuously, sub-second gaps; TTFT < ~60s) and far below the multi-minute hang. Overridable via
# GRAPHRAG_LLM_READ_TIMEOUT for a slow-network fallback.
def _client_timeout():
    # anthropic.Timeout, NEVER httpx.Timeout (2026-08-23 RCA): anthropic 1.0 vendors its own httpx
    # fork, and a REAL httpx.Timeout instance fails its isinstance checks, falls through to
    # sock.settimeout(<Timeout object>) -> TypeError -> masked as APIConnectionError "Connection
    # error." on EVERY call. That masked crash voided two deck run sets wearing a network-outage
    # costume. On anthropic 0.x anthropic.Timeout IS httpx.Timeout, so this spelling is identical
    # there and correct on both SDK lines.
    read = float(os.environ.get("GRAPHRAG_LLM_READ_TIMEOUT", "300") or 300)
    return anthropic.Timeout(connect=15.0, read=read, write=60.0, pool=15.0)


def make_client():
    """The serving client for the active provider. Bedrock auth is the boto3 credential chain
    (task role in-cloud), Anthropic is the .env/env API key — same resolution the offline path uses.
    Both carry a per-request read timeout so a stalled stream raises instead of hanging (see _client_timeout),
    and pin the SDK's own retry to 0 so the code's tenacity ladder is the SINGLE retry authority — the
    un-pinned SDK max_retries=2 nested under tenacity(4) was pure amplification (12 HTTP attempts per call)."""
    if provider() == "bedrock":
        return anthropic.AnthropicBedrock(aws_region=os.environ.get("AWS_REGION", "us-east-1"),
                                          timeout=_client_timeout(), max_retries=0)
    from leviathan.graphrag import batch_extract as bx
    return anthropic.Anthropic(api_key=bx._api_key(), timeout=_client_timeout(), max_retries=0)


def with_retry(fn):
    """Run fn() under the serving backoff policy (availability errors only). For raw
    client.messages.create loops (the numbers agent) that can't route through serving_call."""
    @retry(retry=retry_if_exception_type(RETRYABLE), reraise=True,
           wait=wait_exponential(multiplier=2, min=2, max=30), stop=stop_after_attempt(4))
    def go():
        return fn()
    return go()


def serving_call(client, system, user, *, model: str, max_tokens: int = 4096, tool: dict,
                 degrade_to: Optional[str] = None,
                 temperature: Optional[float] = None,
                 usage_sink: Optional[list] = None) -> tuple[dict, Optional[str]]:
    """One forced-tool serving call with the full fallback chain. Returns (tool_input, degraded_model)
    where degraded_model is None on the primary path and the ALIAS (e.g. 'claude-haiku-4-5') when the
    degraded attempt served the answer — callers surface that as a visible caveat + trace entry.
    `temperature` is forwarded only when provided (D18: the dispatch planner pins 0; both the primary
    and the degraded attempt carry it so a degraded dispatch stays deterministic too).
    `usage_sink` (D-AM-4): when a list is passed, the extract.Usage of the attempt that SERVED the
    answer is appended — additive, so the return shape and every existing caller stay untouched."""
    _t = {} if temperature is None else {"temperature": temperature}
    try:
        out, _u = with_retry(lambda: ex.call_opus(client, system, user, model=model,
                                                  max_tokens=max_tokens, tool=tool, **_t))
        if usage_sink is not None:
            usage_sink.append(_u)
        return out, None
    except RETRYABLE:
        fallback = resolve_model(degrade_to) if degrade_to else None
        if not fallback or fallback == model:
            raise

        @retry(retry=retry_if_exception_type(RETRYABLE), reraise=True,
               wait=wait_exponential(multiplier=2, min=2, max=8), stop=stop_after_attempt(2))
        def degraded():
            return ex.call_opus(client, system, user, model=fallback, max_tokens=max_tokens, tool=tool, **_t)
        out, _u = degraded()
        if usage_sink is not None:
            usage_sink.append(_u)
        return out, degrade_to


def serving_call_stream(client, system, user, *, model: str, max_tokens: int = 4096, tool: dict,
                        degrade_to: Optional[str] = None, on_token,
                        usage_sink: Optional[list] = None) -> tuple[dict, Optional[str]]:
    """Streaming variant of serving_call: relays the tool's input_json_delta text via `on_token` as the note
    generates, and returns the SAME (tool_input, degraded_model). Robustness is preserved: an availability
    error degrades to the fallback model (buffered — the fast path already failed), and any other stream-path
    error falls back to the buffered `serving_call` on the primary model. So streaming is pure upside.
    `usage_sink` (D-AM-4): same additive contract as serving_call — the serving attempt's Usage is appended."""
    try:
        out, _u = with_retry(lambda: ex.call_opus_stream(client, system, user, model=model,
                                                         max_tokens=max_tokens, tool=tool, on_token=on_token))
        if usage_sink is not None:
            usage_sink.append(_u)
        return out, None
    except RETRYABLE:
        fallback = resolve_model(degrade_to) if degrade_to else None
        if not fallback or fallback == model:
            raise

        @retry(retry=retry_if_exception_type(RETRYABLE), reraise=True,
               wait=wait_exponential(multiplier=2, min=2, max=8), stop=stop_after_attempt(2))
        def degraded():
            return ex.call_opus(client, system, user, model=fallback, max_tokens=max_tokens, tool=tool)
        out, _u = degraded()
        if usage_sink is not None:
            usage_sink.append(_u)
        return out, degrade_to
    except Exception:  # noqa: BLE001 — a streaming-specific failure must never lose the answer
        return serving_call(client, system, user, model=model, max_tokens=max_tokens, tool=tool,
                            degrade_to=degrade_to, usage_sink=usage_sink)


# ── D-AM-4: serving cost arithmetic ───────────────────────────────────────────────────────────────
# OUR OWN price table on purpose — third-party tables (LiteLLM et al.) price cached tokens at the
# full input rate, a measured 3-5x overstatement on cache-heavy serving traffic. Serving prompt
# caches are 5-minute ephemeral => the write premium is 1.25x input (batch_extract's 2x is the
# 1-hour-TTL extraction lane, a DIFFERENT premium — don't unify them). Unknown model => None =>
# the CostUsd metric is ABSENT rather than silently wrong (the DarkRefNodes 0-semantics idiom).
# NOTE: claude-sonnet-5 is INTRO pricing through 2026-08-31; bump to (3.0, 15.0) on Sep 1.
SERVING_PRICES: dict[str, tuple[float, float]] = {   # alias -> ($/MTok input, $/MTok output)
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-opus-5": (5.0, 25.0),
}


def serving_cost_usd(model: str, in_tok: int, out_tok: int,
                     cache_read: int = 0, cache_write: int = 0) -> Optional[float]:
    """Cache-aware cost of one serving call in USD, or None for an unpriced model (metric absent,
    never fabricated). 5-minute-TTL arithmetic: write 1.25x input, read 0.1x input."""
    p = SERVING_PRICES.get(model)
    if p is None:
        return None
    pi, po = p
    return (in_tok * pi + cache_write * pi * 1.25 + cache_read * pi * 0.1 + out_tok * po) / 1e6
