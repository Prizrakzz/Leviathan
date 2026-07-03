"""Typed contracts for the live news/policy agent (GRAPHRAG_PLAN section 7.1).

A LiveEvent is the ONLY thing the live layer may hand to the rest of the system: a typed, provenance-
stamped record extracted from a trusted-source headline. Free news text never flows into prompts or
evidence — the event's `summary` is the single human-written-by-LLM field, and it is register-sanitized
and rendered inside a visibly labeled "live external" block that never counts as corpus grounding.
`driver_id` is never LLM-chosen: extract_live.py maps the enum `event_type` to a causal-DAG driver id
deterministically (the entity-linker principle — the model classifies, code resolves ids).
"""
from __future__ import annotations

from pydantic import BaseModel, Field

# The closed event vocabulary the extractor may emit (enum-locked in the tool schema). Everything else
# is "not a shock we track" and is dropped.
EVENT_TYPES = (
    "export_ban", "export_tax", "export_quota", "import_tariff", "mandate",
    "port_closure", "corridor_disruption", "sanctions",
    "large_sale", "weather_advisory",
)


class LiveEvent(BaseModel):
    """One verified live shock, extracted from a trusted-source headline."""
    event_type: str = Field(description=f"one of {EVENT_TYPES}")
    commodity: str = ""                    # canonical contract id (deterministic alias match; "" = unresolved)
    driver_id: str | None = None           # DAG driver id (deterministic map from event_type; None = context-only)
    country: str = ""
    summary: str = ""                      # one LLM sentence; sanitized before rendering
    headline: str = ""
    source: str = ""                       # domain, e.g. reuters.com
    url: str = ""
    published: str = ""                    # ISO date if the feed carried one
    fetched_at: str = ""                   # ISO timestamp of OUR fetch (audit)
