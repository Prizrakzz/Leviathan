"""Extractor: calls Claude Haiku via Amazon Bedrock to extract structured
entities from a single text chunk.

The vocabulary (entity_vocabulary.yaml) is loaded once at module import and
injected into every prompt so Haiku resolves commodity names and country names
to canonical leviathan slugs.

Design choices:
- Single API call per chunk (no streaming) — 1024 output tokens covers all
  entity types for chunks ≤512 input tokens.
- Null-safe JSON parse: if Bedrock returns malformed JSON the chunk is skipped
  with a warning; it never crashes the Batch task.
- tenacity retry on ThrottlingException / ServiceUnavailableException with
  exponential backoff (2 → 30 s, 3 attempts).
"""
from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import boto3
import yaml
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from leviathan.transforms.text_to_graphrag.schema import ChunkExtractionResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Model configuration
# ---------------------------------------------------------------------------
_HAIKU_MODEL_ID = "anthropic.claude-haiku-4-5-20251001-v1:0"
_MAX_TOKENS = 1024


# ---------------------------------------------------------------------------
# Vocabulary loading
# ---------------------------------------------------------------------------

def _vocab_path() -> Path:
    """Resolve entity_vocabulary.yaml from workspace root."""
    # Try environment variable first (set by Batch task via LEVIATHAN_BUCKET
    # download), then fall back to local repo path for local development.
    env_path = os.environ.get("ENTITY_VOCAB_PATH")
    if env_path:
        return Path(env_path)
    # Walk up from this file to the repo root, then into configs/sources/
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "configs" / "sources" / "entity_vocabulary.yaml"
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        "entity_vocabulary.yaml not found. Set ENTITY_VOCAB_PATH env var "
        "or ensure configs/sources/entity_vocabulary.yaml is present."
    )


@lru_cache(maxsize=1)
def _load_vocabulary() -> dict:
    with open(_vocab_path(), encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _vocab_summary() -> str:
    """Build a compact vocabulary reference string for the system prompt."""
    vocab = _load_vocabulary()

    commodity_lines = []
    for key, entry in vocab.get("commodities", {}).items():
        canonical = entry.get("canonical", key)
        aliases = entry.get("aliases", [])[:4]  # first 4 aliases only
        commodity_lines.append(f'  "{canonical}": {aliases}')

    country_names = list(vocab.get("countries", {}).keys())
    stress_types = list(vocab.get("stress_types", {}).keys())
    causal_markers = vocab.get("causal_markers", [])[:12]

    return (
        "COMMODITY CANONICAL SLUGS (use these exact strings):\n"
        + "\n".join(commodity_lines)
        + "\n\nCANONICAL COUNTRY NAMES: "
        + ", ".join(country_names)
        + "\n\nSTRESS TYPES: "
        + ", ".join(stress_types)
        + "\n\nCAUSAL MARKERS (only extract links anchored by these exact phrases): "
        + str(causal_markers)
    )


# ---------------------------------------------------------------------------
# System and user prompt templates
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """You are a structured data extractor for agricultural commodity research.

Extract facts ONLY when they are explicitly stated in the provided text.
Do NOT infer, interpret, or add information not present in the text.
Return ONLY a valid JSON object matching the schema below. No explanations, no markdown.

{vocabulary}

OUTPUT SCHEMA (JSON):
{{
  "stress_events": [
    {{
      "commodity": "<canonical slug>",
      "origin": "<canonical country>",
      "stress_type": "<drought|frost|flood|disease|pest|wind|heat_stress|biennial_cycle|planting_delay>",
      "severity": <-1 or 0 or 1>,
      "crop_year": "<YYYY/YY or null>",
      "time_window": "<season/month window or null>"
    }}
  ],
  "causal_links": [
    {{
      "cause": "<brief description of cause>",
      "effect": "<brief description of effect>",
      "cause_commodity": "<canonical slug or null>",
      "cause_origin": "<canonical country or null>",
      "effect_commodity": "<canonical slug or null>",
      "effect_origin": "<canonical country or null>",
      "lag": "<time description or null>",
      "marker": "<exact causal phrase from text>"
      "confidence": "<high|medium|low>"
    }}
  ],
  "production_forecasts": [
    {{
      "commodity": "<canonical slug>",
      "origin": "<canonical country>",
      "value": <number or null>,
      "unit": "<MMT|1000 MT|million bags|null>",
      "crop_year": "<YYYY/YY or null>",
      "direction": "<up|down|unchanged|null>"
    }}
  ],
  "policy_changes": [
    {{
      "country": "<canonical country>",
      "commodity": "<canonical slug>",
      "policy_type": "<export_restriction|import_duty|subsidy|mandate|quota|other>",
      "direction": "<bullish|bearish|neutral>"
    }}
  ],
  "tone": {{
    "commodity": "<canonical slug or null>",
    "origin": "<canonical country or null>",
    "score": <-1 or 0 or 1>,
    "phrases": ["<verbatim phrase 1>", "<verbatim phrase 2>"]
  }}
}}

Rules:
- severity: -1 = mild/minor, 0 = neutral or ambiguous, 1 = severe/significant
- tone score: -1 = bearish concern, 0 = neutral/balanced, 1 = bullish/positive
- Return empty arrays [] for entity types with nothing to extract
- causal_links: ONLY if the text contains one of the listed causal marker phrases
- production_forecasts: ONLY for explicit estimates; not for vague "expected to be lower"
"""


def _user_message(chunk_text: str, source: str, document_date: str, section_name: str) -> str:
    return (
        f"Source: {source}\n"
        f"Document date: {document_date}\n"
        f"Section: {section_name}\n\n"
        f"Text to extract from:\n"
        f"---\n{chunk_text}\n---\n\n"
        "Return the JSON extraction now."
    )


# ---------------------------------------------------------------------------
# Bedrock client (module-level singleton)
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _bedrock_client():
    region = os.environ.get("AWS_REGION", "us-east-1")
    return boto3.client("bedrock-runtime", region_name=region)


# ---------------------------------------------------------------------------
# Retry-wrapped Bedrock invoke
# ---------------------------------------------------------------------------

def _is_throttle_error(exc: Exception) -> bool:
    """Return True for errors that should trigger a retry."""
    if hasattr(exc, "response"):
        code = exc.response.get("Error", {}).get("Code", "")
        return code in ("ThrottlingException", "ServiceUnavailableException",
                        "ModelStreamErrorException", "TooManyRequestsException")
    return False


@retry(
    retry=retry_if_exception_type(Exception),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    reraise=True,
)
def _invoke_haiku(user_content: str) -> str:
    """Call Bedrock Haiku and return the raw text response."""
    vocab_summary = _vocab_summary()
    system_prompt = _SYSTEM_PROMPT.replace("{vocabulary}", vocab_summary)

    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": _MAX_TOKENS,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_content}],
    })
    response = _bedrock_client().invoke_model(
        modelId=_HAIKU_MODEL_ID,
        body=body,
        contentType="application/json",
        accept="application/json",
    )
    result = json.loads(response["body"].read())
    return result["content"][0]["text"]


# ---------------------------------------------------------------------------
# Public extraction function
# ---------------------------------------------------------------------------

_EMPTY_RESULT: dict[str, Any] = {
    "stress_events": [],
    "causal_links": [],
    "production_forecasts": [],
    "policy_changes": [],
    "tone": {"commodity": None, "origin": None, "score": 0, "phrases": []},
}


def extract_chunk(
    chunk_text: str,
    source: str,
    document_date: str,
    section_name: str,
    doc_key: str,
    chunk_index: int,
) -> ChunkExtractionResult:
    """Extract structured entities from one text chunk via Claude Haiku.

    Args:
        chunk_text:    Bounded text (≤1800 chars) to extract from.
        source:        Document source identifier (usda_wasde, usda_wap, …).
        document_date: YYYY-MM-DD publication date of the source document.
        section_name:  Named section label (WHEAT, OILSEEDS, full, …).
        doc_key:       S3 key of the parent document.json.
        chunk_index:   0-based position within the parent document.

    Returns:
        ChunkExtractionResult with provenance fields and extracted entities.
        On extraction failure, returns an empty-entity result (no crash).
    """
    user_msg = _user_message(chunk_text, source, document_date, section_name)

    try:
        raw_text = _invoke_haiku(user_msg)
        extracted = _parse_response(raw_text)
    except Exception as exc:
        logger.warning(
            "Extraction failed for %s chunk %d section=%s: %s",
            doc_key, chunk_index, section_name, exc,
        )
        extracted = _EMPTY_RESULT.copy()

    return ChunkExtractionResult(
        doc_key=doc_key,
        document_date=document_date,
        source=source,
        section_name=section_name,
        chunk_index=chunk_index,
        **extracted,  # type: ignore[arg-type]
    )


def _parse_response(raw_text: str) -> dict[str, Any]:
    """Parse Haiku's JSON response, stripping any markdown fences."""
    text = raw_text.strip()
    # Strip ```json ... ``` fences if present
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON parse error: {exc}  raw={raw_text[:200]!r}") from exc

    # Ensure all required keys are present, defaulting to empty
    return {
        "stress_events": data.get("stress_events") or [],
        "causal_links": data.get("causal_links") or [],
        "production_forecasts": data.get("production_forecasts") or [],
        "policy_changes": data.get("policy_changes") or [],
        "tone": data.get("tone") or _EMPTY_RESULT["tone"],
    }
