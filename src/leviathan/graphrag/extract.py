"""GraphRAG extraction core — Opus 4.8 entity/edge extraction over a chunk (the Phase-4 seed).

Pilot use today; the same prompt + schema + mapping become the production extraction node. The model
emits a lightweight ``ChunkExtraction`` via forced tool use; we then MAP it into the strict
``contracts`` models (assigning ids/provenance/defaults) and validate. Anything that does not fit the
closed vocab/edge taxonomy is captured in ``unmapped_*`` / friction — never silently dropped — so the
pilot can MEASURE whether the typed taxonomy is coercing real relationships.

Provider: Anthropic API (``claude-opus-4-8``). Bedrock denies Opus and would leak queries off in-AWS;
extraction is the one step the design routes to the Anthropic API. Follows the ``claude-api`` skill.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, ValidationError

from leviathan.graphrag.contracts import (
    Entity, Event, QuantitativeClaim, Relationship, SourceRef,
)

_CFG = Path(__file__).resolve().parents[3] / "configs" / "graphrag"
MODEL = "claude-opus-4-8"
# Opus 4.8 list price ($/token) — for the cost log.
PRICE_IN, PRICE_OUT = 5.0 / 1e6, 25.0 / 1e6
_CONF_BY_EVIDENCE = {"fact": 0.9, "reported_claim": 0.6, "model_inference": 0.3}


# ── what Opus emits (lightweight; mapped into strict contracts afterward) ─────────
class XEntity(BaseModel):
    id: str
    type: str
    canonical_name: str
    mapped: bool = True


class XRel(BaseModel):
    src: str
    dst: str
    relation_type: str                 # a vocab edge type, or "OTHER" if it doesn't fit
    metric: Optional[str] = None
    sign: str = "0"                    # "+" | "-" | "0"
    evidence_class: str = "reported_claim"
    marker: Optional[str] = None       # the causal-marker phrase, if the link is anchored by one
    verbatim: str = ""
    mapped: bool = True


class XClaim(BaseModel):
    entity: str
    metric: str
    value: Optional[float] = None
    unit: str = ""
    period: str = ""
    direction: str = "0"
    verbatim: str = ""


class XEvent(BaseModel):
    event_type: str
    commodity: str
    country: str
    description: str
    verbatim: str = ""


class ChunkExtraction(BaseModel):
    entities: list[XEntity] = []
    relationships: list[XRel] = []
    events: list[XEvent] = []
    quantitative_claims: list[XClaim] = []
    unmapped_relations: list[str] = []   # relations Opus saw that don't fit the closed taxonomy
    unmapped_entities: list[str] = []    # entities that don't map to a node type


def extraction_tool() -> dict:
    """The forced-tool schema Opus fills (derived from the Pydantic model — single source of truth)."""
    return {
        "name": "emit_extraction",
        "description": "Emit the structured graph extracted from the CURRENT chunk only.",
        "input_schema": ChunkExtraction.model_json_schema(),
    }


# ── prompt (reads the git-ignored vocab/hierarchy IP at runtime) ──────────────────
def _vocab() -> dict:
    return yaml.safe_load((_CFG / "entity_vocabulary.yaml").read_text(encoding="utf-8"))


def build_system_prompt() -> str:
    v = _vocab()
    node_types = list(v.get("nodes", {}).keys())
    edges = list(v.get("edges", {}).keys())
    markers = v.get("causal_markers", [])

    def _members(t: str) -> str:
        # show the FULL list — truncating drops valid nodes (e.g. the softs/tropicals) and produces
        # false "unmapped" signals for commodities that ARE in the vocab.
        return ", ".join(v["nodes"].get(t) or []) or "(open set — mint instances)"

    node_lines = "\n".join(f"  {t}: {_members(t)}" for t in node_types)
    return f"""You are a knowledge-graph extractor building Leviathan's CAUSAL CASCADE graph for
commodity quant researchers. The graph exists to trace how a shock propagates — weather/policy/logistics
shock -> supply-demand balance -> trade flows -> substitute markets -> price/policy. So PRIORITIZE the
relationships that carry a cascade: causal links, cross-commodity substitution/competition, the crush
and biofuel-feedstock chains, supply-demand effects, and policy -> trade effects. Flat mentions matter
less than the edges that connect one commodity/event to another.

Extract ONLY what the CURRENT chunk explicitly states. Use the prior/next chunk as context to resolve
a relation that spans a sentence boundary, but the relation must be anchored in the current chunk.

NODE-MODEL RULE (critical): a node is a COMMODITY/entity. A metric (production, yield, export, price,
stock, consumption, import, area, spread) and its direction ride on the RELATION (`metric`,`sign`) or
a quantitative_claim — NEVER bake a metric into a node id. There is no `arabica_production` node; it is
the `arabica_coffee` node + a `production` metric.

CANONICALIZE entities to these node types (resolve aliases to the canonical term). If an entity does
not map to any node type, set mapped=false AND add it to unmapped_entities.
NODE TYPES:
{node_lines}

RELATIONS — use ONLY these edge types; set `sign` to "+"/"-"/"0" and `metric` to the affected series:
  {", ".join(edges)}
If a real relationship does NOT fit one of these edge types, set relation_type="OTHER", mapped=false,
AND add a short description to unmapped_relations. Do NOT force a bad fit — we are measuring coverage.

CAUSAL anchors (prefer minting a `causes`/`affects_yield_of` edge when the sentence contains one):
  {markers}
If you see a clear causal link with NO anchor phrase, still emit it but leave `marker` null.

Every relation and claim MUST carry the exact `verbatim` source span. evidence_class ∈
{{fact, reported_claim, model_inference}}. Return empty lists where nothing applies. Emit via the
emit_extraction tool only."""


def build_user_message(prev_text: str, current_text: str, next_text: str) -> str:
    return (f"[PRIOR CONTEXT]\n{prev_text or '(none)'}\n\n"
            f"[CURRENT CHUNK — extract from this]\n{current_text}\n\n"
            f"[NEXT CONTEXT]\n{next_text or '(none)'}")


# ── the Opus call (forced tool use) ───────────────────────────────────────────────
@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def cost(self) -> float:
        return self.input_tokens * PRICE_IN + self.output_tokens * PRICE_OUT


def call_opus(client, system: str, user: str, *, model: str = MODEL,
              max_tokens: int = 4096) -> tuple[dict, Usage]:
    """One forced-tool extraction call. Returns (tool_input_dict, usage). Retries are the caller's job
    (kept thin so the unit test can pass a trivial fake client)."""
    resp = client.messages.create(
        model=model, max_tokens=max_tokens, system=system,
        messages=[{"role": "user", "content": user}],
        tools=[extraction_tool()],
        tool_choice={"type": "tool", "name": "emit_extraction"},
    )
    tool_input = next((b.input for b in resp.content if getattr(b, "type", None) == "tool_use"), None)
    if tool_input is None:
        raise ValueError("model returned no tool_use block")
    u = getattr(resp, "usage", None)
    usage = Usage(getattr(u, "input_tokens", 0), getattr(u, "output_tokens", 0)) if u else Usage()
    return tool_input, usage


def parse_extraction(tool_input: dict) -> ChunkExtraction:
    return ChunkExtraction.model_validate(tool_input)


# ── map the loose extraction into strict contracts + collect friction ─────────────
@dataclass
class Friction:
    unmapped_relations: list[str] = field(default_factory=list)   # OTHER-typed or escape-listed
    unmapped_entities: list[str] = field(default_factory=list)
    validation_failures: list[str] = field(default_factory=list)  # would-be records that failed
    causal_without_marker: int = 0                                # would be dropped by the strict rule
    n_entities: int = 0
    n_relationships: int = 0


def _sref(chunk, verbatim: str) -> SourceRef:
    return SourceRef(chunk_id=chunk.chunk_id, source=chunk.source,
                     document_date=chunk.document_date, verbatim_span=verbatim or chunk.verbatim_span[:200])


def to_contracts(x: ChunkExtraction, chunk, *, node_types: set[str], node_members: set[str],
                 edges: set[str]) -> tuple[dict, Friction]:
    """Map → contracts.{Entity,Relationship,Event,QuantitativeClaim}; route the rest to friction."""
    fr = Friction(unmapped_relations=list(x.unmapped_relations), unmapped_entities=list(x.unmapped_entities))
    out: dict[str, list] = {"entities": [], "relationships": [], "events": [], "quantitative_claims": []}

    for e in x.entities:
        if not e.mapped or e.type not in node_types or e.id not in node_members:
            fr.unmapped_entities.append(f"{e.id} ({e.type})")
            continue
        try:
            out["entities"].append(Entity(entity_id=e.id, type=e.type, canonical_name=e.canonical_name))
            fr.n_entities += 1
        except ValidationError as ex:
            fr.validation_failures.append(f"entity {e.id}: {ex.error_count()} err")

    for r in x.relationships:
        if r.relation_type not in edges or not r.mapped:
            fr.unmapped_relations.append(f"{r.src} -[{r.relation_type}]-> {r.dst}")
            continue
        if r.marker is None and r.relation_type in ("causes", "affects_yield_of"):
            fr.causal_without_marker += 1
        sign = r.sign if r.sign in ("+", "-", "0") else "0"
        evidence = r.evidence_class if r.evidence_class in _CONF_BY_EVIDENCE else "reported_claim"
        eid = hashlib.sha1(f"{chunk.chunk_id}|{r.src}|{r.relation_type}|{r.dst}".encode()).hexdigest()[:16]
        try:
            out["relationships"].append(Relationship(
                edge_id=eid, src_entity=r.src, dst_entity=r.dst, relation_type=r.relation_type,
                metric=r.metric or None, sign=sign, confidence=_CONF_BY_EVIDENCE[evidence],
                evidence_class=evidence, edge_scope="structural", sources=[_sref(chunk, r.verbatim)]))
            fr.n_relationships += 1
        except ValidationError as ex:
            fr.validation_failures.append(f"rel {r.src}->{r.dst}: {ex.error_count()} err")

    for i, c in enumerate(x.quantitative_claims):
        direction = c.direction if c.direction in ("+", "-", "0") else "0"
        try:
            out["quantitative_claims"].append(QuantitativeClaim(
                claim_id=f"{chunk.chunk_id}#q{i}", chunk_id=chunk.chunk_id, entity_id=c.entity,
                metric=c.metric, value=c.value, unit=c.unit, period=c.period or "unknown",
                direction=direction, document_date=chunk.document_date))
        except ValidationError as ex:
            fr.validation_failures.append(f"claim {c.entity}/{c.metric}: {ex.error_count()} err")

    for i, ev in enumerate(x.events):
        try:
            out["events"].append(Event(
                event_id=f"{chunk.chunk_id}#e{i}", event_type=ev.event_type, commodity=ev.commodity,
                country=ev.country, season_or_date="unknown", description=ev.description,
                document_date=chunk.document_date, sources=[_sref(chunk, ev.verbatim)]))
        except ValidationError as ex:
            fr.validation_failures.append(f"event {ev.event_type}: {ex.error_count()} err")

    return out, fr


def vocab_sets() -> tuple[set[str], set[str], set[str]]:
    """(node_types, node_members, edges) from the vocab — the closed sets to_contracts checks against."""
    v = _vocab()
    node_types = set(v.get("nodes", {}).keys())
    node_members = {t for terms in v.get("nodes", {}).values() if terms for t in terms}
    edges = set(v.get("edges", {}).keys())
    return node_types, node_members, edges


# ── serialize the GROUNDED TRUTH — full validated records, nothing discarded ──────
def full_records(mapped: dict, chunk) -> dict[str, list[dict]]:
    """All five contract tables as JSON dicts (model_dump) — edge_ids, verbatim sources, dates, the lot.
    This is what gets persisted; the trimmed view below is only a review convenience."""
    return {
        "chunks": [chunk.model_dump(mode="json")],
        "entities": [e.model_dump(mode="json") for e in mapped["entities"]],
        "relationships": [r.model_dump(mode="json") for r in mapped["relationships"]],
        "events": [e.model_dump(mode="json") for e in mapped["events"]],
        "quantitative_claims": [q.model_dump(mode="json") for q in mapped["quantitative_claims"]],
    }


def candidate_gold(mapped: dict, chunk) -> dict:
    """Thin human-review view derived FROM the full records (for seeding gold/extraction.jsonl)."""
    return {
        "id": chunk.chunk_id, "source": chunk.source, "doc": chunk.source_key,
        "chunk": chunk.proposition[:1200],
        "entities": [{"id": e.entity_id, "type": e.type} for e in mapped["entities"]],
        "edges": [{"src": r.src_entity, "rel": r.relation_type, "sign": r.sign, "dst": r.dst_entity,
                   "metric": r.metric, "evidence_class": r.evidence_class} for r in mapped["relationships"]],
        "quant": [{"metric": q.metric, "value": q.value, "unit": q.unit, "direction": q.direction}
                  for q in mapped["quantitative_claims"]],
    }
