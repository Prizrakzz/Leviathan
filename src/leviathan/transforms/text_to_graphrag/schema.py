"""Schema definitions for the text_to_graphrag extraction pipeline.

One ChunkExtractionResult is produced per text chunk (bounded section or
paragraph split). The writer assembles lists of results into four Parquet
tables: entities, causal_edges, forecasts, sentiment.
"""
from __future__ import annotations

from typing import List, Optional

from typing_extensions import TypedDict


# ---------------------------------------------------------------------------
# Per-entity types (nested inside ChunkExtractionResult)
# ---------------------------------------------------------------------------

class StressEvent(TypedDict):
    """A supply-side stress event explicitly mentioned in the chunk text."""

    commodity: str            # canonical leviathan slug or section-group label
    origin: str               # canonical country name
    stress_type: str          # one of: drought frost flood disease pest wind
                              #          heat_stress biennial_cycle planting_delay
    severity: int             # -1 mild  |  0 neutral/ambiguous  |  1 severe
    crop_year: Optional[str]  # "2021/22" format if stated; null if not mentioned
    window: Optional[str]     # "Aug-Oct", "flowering window", etc.


class CausalLink(TypedDict):
    """A causal relationship anchored by an explicit linguistic marker."""

    cause: str                        # free text description of cause
    effect: str                       # free text description of effect
    cause_commodity: Optional[str]    # canonical slug if identifiable
    cause_origin: Optional[str]       # canonical country if identifiable
    effect_commodity: Optional[str]
    effect_origin: Optional[str]
    lag: Optional[str]                # "three months later", "in the following season"
    marker: str                       # exact phrase from text: "as a result of", etc.
    confidence: str                   # high | medium | low


class ProductionForecast(TypedDict):
    """An explicit production forecast or revision mentioned in the chunk."""

    commodity: str
    origin: str
    value: Optional[float]    # numeric value if stated (in stated unit)
    unit: Optional[str]       # "MMT", "1000 MT", "million bags", etc.
    crop_year: Optional[str]  # "2021/22"
    direction: Optional[str]  # "up" | "down" | "unchanged" if no number given


class PolicyChange(TypedDict):
    """A trade or agricultural policy change mentioned in the chunk."""

    country: str
    commodity: str
    policy_type: str          # export_restriction | import_duty | subsidy |
                              # mandate | quota | other
    direction: str            # bullish | bearish | neutral (relative to price)


class ToneRecord(TypedDict):
    """Overall sentiment of the chunk toward a specific commodity/origin pair."""

    commodity: Optional[str]  # null if the chunk covers multiple commodities
    origin: Optional[str]     # null if global/multi-origin
    score: int                # -1 bearish  |  0 neutral  |  1 bullish
    phrases: List[str]        # up to 3 verbatim phrases driving the score


# ---------------------------------------------------------------------------
# Top-level container returned by the extractor per chunk
# ---------------------------------------------------------------------------

class ChunkExtractionResult(TypedDict):
    """All entities extracted from a single text chunk, plus provenance."""

    # Provenance — written as columns in every output Parquet table
    doc_key: str          # S3 key of the source document.json
    document_date: str    # YYYY-MM-DD parsed from doc path or metadata
    source: str           # usda_wasde | usda_wap | usda_gain | conab | ...
    section_name: str     # WHEAT | OILSEEDS | full | etc.
    chunk_index: int      # 0-based index within the document

    # Extracted entities
    stress_events: List[StressEvent]
    causal_links: List[CausalLink]
    production_forecasts: List[ProductionForecast]
    policy_changes: List[PolicyChange]
    tone: ToneRecord
