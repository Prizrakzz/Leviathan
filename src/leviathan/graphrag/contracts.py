"""GraphRAG data contracts — the single source of truth for every parquet artifact.

These Pydantic models define the indexing/query exchange schema (GRAPHRAG_PLAN.md
§3.1 chunks, §3.3 entities/relationships/events/quantitative_claims/source_reliability,
§3.7 node_silver_map). Pydantic is the source of truth; the pyarrow schema is *generated*
from it (`arrow_schema`), so the parquet layout can never drift from the validated model.

Design rules (Phase 1 best practices):
  * Every record carries ``schema_version`` — downstream code can detect a contract bump.
  * Invariants are validators, not comments (char offsets ordered, ratios in [0,1],
    enums closed, event_specific edges must name their event).
  * The models encode *structure*; the closed entity/edge *vocabulary* is config
    (``configs/graphrag/entity_vocabulary.yaml``, git-ignored IP), not hardcoded here.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Literal, Optional

import pyarrow as pa
from pydantic import BaseModel, Field, model_validator

SCHEMA_VERSION = "1.1.0"

# ── closed enums (structural; the open vocab is config) ──────────────────────────
ExtractionMethod = Literal["textract", "pdfplumber", "beautifulsoup"]
EvidenceClass = Literal["fact", "reported_claim", "model_inference"]
EdgeScope = Literal["structural", "event_specific"]
Sign = Literal["+", "-", "0"]
Agreement = Literal["agree", "disagree", "unverifiable"]
# Node-model rule (pinned): a graph node is the COMMODITY (or other entity). The metric +
# direction + as-of-date ride on QuantitativeClaim / Relationship — never baked into a node id
# (no `arabica_production` nodes). `Metric` is the closed set of series a claim/edge can concern.
Metric = Literal[
    "production", "area", "yield", "export", "import", "stock", "beginning_stock",
    "consumption", "price", "spread",
    # added v0.4 from the grounded-truth run's metric drift (high-frequency, S/D-relevant):
    "import_tariff", "crush", "harvest_progress", "market_share",
]


class _Base(BaseModel):
    """Common config: reject unknown fields (a typo'd column is a bug, not a silent drop)."""
    model_config = {"extra": "forbid", "frozen": False}
    schema_version: str = SCHEMA_VERSION


# ── nested value objects ─────────────────────────────────────────────────────────
class SourceRef(_Base):
    chunk_id: str
    source: str
    document_date: date
    verbatim_span: str


class ValidityWindow(_Base):
    start_date: Optional[date] = None
    end_date: Optional[date] = None


class SilverReconciliation(_Base):
    table: Optional[str] = None
    queried_value: Optional[float] = None
    agreement: Agreement = "unverifiable"


# ── §3.1 provenance-preserving chunk ──────────────────────────────────────────────
class Chunk(_Base):
    chunk_id: str
    proposition: str                       # working-language (en) normalized statement
    verbatim_span: str                     # EXACT original-language source — provenance anchor
    source_key: str
    page: int = Field(ge=0)
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=0)
    document_date: date                    # first-knowable date — drives PIT
    source: str
    lang: str                              # detected ORIGINAL language
    translated: bool = False
    extraction_method: ExtractionMethod
    ocr: bool                              # = (extraction_method == "textract")
    text_quality: float = Field(ge=0.0, le=1.0)
    # Fix 2 — neighbor context so extraction can preserve cross-sentence relations.
    prev_chunk_id: Optional[str] = None
    next_chunk_id: Optional[str] = None

    @model_validator(mode="after")
    def _check(self) -> "Chunk":
        if self.char_end < self.char_start:
            raise ValueError("char_end must be >= char_start")
        if self.ocr != (self.extraction_method == "textract"):
            raise ValueError("ocr must equal (extraction_method == 'textract')")
        return self


# ── §3.3 entities / relationships / events / quantitative_claims / reliability ────
class Entity(_Base):
    entity_id: str
    type: str                              # one of entity_vocabulary.yaml node types
    canonical_name: str
    aliases: list[str] = Field(default_factory=list)
    mention_count: int = Field(default=0, ge=0)
    first_seen: Optional[date] = None
    last_seen: Optional[date] = None


class Relationship(_Base):
    edge_id: str
    src_entity: str
    dst_entity: str
    relation_type: str                     # one of entity_vocabulary.yaml edge types
    metric: Optional[Metric] = None        # which series the edge moves (e.g. causes → production)
    sign: Sign = "0"                       # direction (↑/↓) of the effect on `metric`
    lag_months: Optional[int] = None
    magnitude: Optional[float] = None
    confidence: float = Field(ge=0.0, le=1.0)
    validity_window: ValidityWindow = Field(default_factory=ValidityWindow)
    evidence_class: EvidenceClass
    edge_scope: EdgeScope
    event_id: Optional[str] = None         # required when edge_scope == event_specific
    sources: list[SourceRef] = Field(default_factory=list)
    support_count: int = Field(default=0, ge=0)
    contradiction_count: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _check(self) -> "Relationship":
        if self.edge_scope == "event_specific" and not self.event_id:
            raise ValueError("event_specific edges must reference an event_id (§3.4)")
        return self


class Event(_Base):
    event_id: str                          # canonical after Phase-4 dedup (Fix 6)
    event_type: str                        # drought|frost|flood|disease|policy|logistics|...
    commodity: str
    country: str
    region: Optional[str] = None
    season_or_date: str
    magnitude: Optional[float] = None
    description: str
    document_date: date
    sources: list[SourceRef] = Field(default_factory=list)


class QuantitativeClaim(_Base):
    claim_id: str
    chunk_id: str
    entity_id: str
    metric: Metric
    value: Optional[float] = None          # None = value-less directional claim ("production fell")
    unit: str
    period: str
    direction: Sign = "0"
    document_date: date
    silver_reconciliation: SilverReconciliation = Field(default_factory=SilverReconciliation)


class SourceReliability(_Base):
    source: str
    commodity: str
    horizon_months: int
    n_obs: int = Field(ge=0)
    directional_hit_rate: float = Field(ge=0.0, le=1.0)
    mean_lead_months: Optional[float] = None
    brier_score: Optional[float] = None
    reliability_score: float = Field(ge=0.0, le=1.0)


# ── §3.7 node → silver semantic layer (Fix 7) ─────────────────────────────────────
class NodeSilverMap(_Base):
    node_id: str
    country: Optional[str] = None
    silver_table: str
    silver_column: str
    filter: dict[str, Any] = Field(default_factory=dict)
    direction_sign: Literal[-1, 1] = 1
    as_of_supported: bool = False          # Fix 3 — does the series carry a release/vintage date?


# ── arrow schema generation (parquet layout is derived, never hand-maintained) ────
_PY_TO_ARROW = {
    "string": pa.string(), "integer": pa.int64(), "number": pa.float64(),
    "boolean": pa.bool_(), "date": pa.date32(),
}


def arrow_schema(model: type[BaseModel]) -> pa.Schema:
    """Derive a flat pyarrow schema from a contract model's JSON schema.

    Nested objects/lists are stored as JSON strings (Athena reads them via json_extract);
    scalars map to native Arrow types. Keeps the parquet layout pinned to the model.
    """
    js = model.model_json_schema()
    props = js.get("properties", {})
    fields = []
    for name, spec in props.items():
        t = spec.get("type")
        if spec.get("format") == "date":   # check BEFORE the generic map ("string" would shadow it)
            fields.append(pa.field(name, pa.date32()))
        elif t in _PY_TO_ARROW:
            fields.append(pa.field(name, _PY_TO_ARROW[t]))
        else:                              # object/array/anyOf(date|null)/etc → JSON string
            fields.append(pa.field(name, pa.string()))
    return pa.schema(fields)


CONTRACTS: dict[str, type[BaseModel]] = {
    "chunks": Chunk,
    "entities": Entity,
    "relationships": Relationship,
    "events": Event,
    "quantitative_claims": QuantitativeClaim,
    "source_reliability": SourceReliability,
    "node_silver_map": NodeSilverMap,
}
