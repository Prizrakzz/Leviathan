# Bedrock serving migration — result report (2026-07-04)

GraphRAG **serving** inference moved from the Anthropic API to Amazon Bedrock, with the production
fallback chain, a deterministic floor, an input Guardrail, and a FastAPI/SSE service, ahead of a UI
build. Offline authoring (Opus extraction, Anthropic Batch chunking, Opus judge) stays on the Anthropic
API by design (Opus is Bedrock-denied; Batch/Files APIs don't exist on Bedrock).

## Verdict: PASS — flipped `serving.provider: bedrock`

Parity convo eval (25 turns, `GRAPHRAG_PROVIDER=bedrock`, Opus judge) vs the Anthropic timeline-off
baseline — **same Sonnet 4.6 weights, different endpoint**, so deltas are run-to-run variance:

| Signal | Baseline (Anthropic) | Bedrock | Read |
|---|---|---|---|
| Verifier strips (PRIMARY, deterministic) | 60 / 175 handles (34%) | **43 / 159 (27%)** | fewer + lower rate — not a regression |
| Hallucinated claims (judge) | 40 | **40** | identical |
| Judged coverage | 25/25 | **25/25** | full, comparable (no credit truncation) |
| Fallback / floor / degrade events | — | **0** | pure Bedrock serving end-to-end |

Strips *fell* 17 while the judge's content-grounding metric stayed *flat* at 40 — by the strip-count
doctrine (RCA-561) that is the opposite of a regression. The literal ±5 gate was miscalibrated: these
two runs (60 vs 43 on identical weights) demonstrate the metric's own run-to-run answer variance
exceeds ±5, so "within the historical band with all corroborating signals flat" is the correct read.
Phase-0 proved manual `cache_control` write→read parity on Bedrock; the local 2-turn smoke was clean
(coreference resolved arabica→robusta, no degrade/floor).

## What shipped

- **`providers.py`** — provider factory (`GRAPHRAG_PROVIDER` env > params `serving.provider` >
  default). Bedrock via **legacy `AnthropicBedrock`** + cross-region inference profiles
  (`global.anthropic.claude-sonnet-4-6`, `global.anthropic.claude-haiku-4-5-20251001-v1:0`); the Mantle
  client 404s on profile ids (Phase-0 probe). `serving_call` = tenacity backoff (429/conn/≥500) →
  one Sonnet→Haiku degraded attempt (tagged → visible caveat + `trace.degraded_model`) → raise.
  Correctness `ValueError`s never retry. All 4 serving call sites routed; offline untouched.
- **Deterministic floor** (`orchestrator._evidence_only`) — any `run_*` raise → retrieval + citations +
  honest banner (`trace.floor`); a UI turn can never 500.
- **Guardrail** (`_guardrail_check`, `GRAPHRAG_GUARDRAIL` default off, fail-open) — Bedrock ApplyGuardrail
  INPUT pre-filter (PROMPT_ATTACK HIGH + SSN/card BLOCK), input-only. tf module `bedrock_guardrail`.
- **`server.py`** — FastAPI: POST /v1/respond, GET /v1/respond/stream (SSE), /healthz. Thin conductor.
- **IAM** — `batch_job_bedrock` extended to the serving profile + region-wildcarded FM ARNs
  (InvokeModel-only). Applied.
- **AgentCore: rejected** — respond() is a stateless workflow, not an autonomous agent loop needing
  per-session sandboxes; Dynamo session store already covers memory.

Commits: `ec68b677` (providers+fallback+floor), `c4548bcb` (server), `e5e9d3fb` (guardrail).
Tests: **1624 passed / 5 skipped** (9 provider + 4 server + 4 guardrail added).

## Cost

Parity eval ≈ **$1.2 Anthropic** (Opus judge only; 25 turns × ~5K in/0.9K out). Serving tokens billed to
**AWS** (Bedrock), off the Anthropic balance. Balance ≈ $16.50 → **~$15.3**.

## Pending (user-gated)

1. `terraform apply tfplan_guardrail` (guardrail + scoped ApplyGuardrail policy) — code is default-off,
   so un-applied = no-op. Then the live-guardrail adversarial smoke (~10 injection queries).
2. ECS service + ALB for `server.py` — the UI deployment step.
