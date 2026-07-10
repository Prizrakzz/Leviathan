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
import json
import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Optional, get_args

import yaml
from pydantic import BaseModel, ValidationError

from leviathan.graphrag.contracts import (
    Entity,
    Event,
    Metric,
    QuantitativeClaim,
    Relationship,
    SourceRef,
)

_CFG = Path(__file__).resolve().parents[3] / "configs" / "graphrag"
MODEL = "claude-opus-4-8"
SONNET = "claude-sonnet-4-6"
HAIKU = "claude-haiku-4-5"
# list price ($/token) per model: (input, output). Batch halves these at billing time.
PRICES = {"claude-opus-4-8": (5.0 / 1e6, 25.0 / 1e6),
          "claude-sonnet-4-6": (3.0 / 1e6, 15.0 / 1e6),
          "claude-haiku-4-5": (1.0 / 1e6, 5.0 / 1e6)}
PRICE_IN, PRICE_OUT = PRICES[MODEL]   # default (Opus) — back-compat for existing callers


def price(model: str) -> tuple[float, float]:
    return PRICES.get(model, PRICES[MODEL])


_CONF_BY_EVIDENCE = {"fact": 0.9, "reported_claim": 0.6, "model_inference": 0.3}

# synonym drift → canonical Metric (from the grounded-truth run's --diagnose). Recovers claims Opus
# emitted under a near-name without widening the enum.
_METRIC_ALIASES = {
    "harvested_area": "area", "ending_stocks": "stock", "stocks": "stock", "demand": "consumption",
    "import_market_share": "market_share", "export_share": "market_share",
    "crush_capacity": "crush", "crush_capacity_utilization": "crush", "planting_pace": "harvest_progress",
    "price_differential": "spread", "exports": "export", "imports": "import",
}


def _norm_metric(m: str | None) -> str | None:
    return _METRIC_ALIASES.get(m, m) if m else m


# A non-node concept smuggled as an edge endpoint: a metric name (import_tariff, export, ...) or a minted
# policy instrument / dated token. These fragment the graph — every doc mints a different
# `soybean_subsidy_2025` that never joins — so an edge to one is dropped (a real subsidy is an EDGE).
_METRIC_VALUES = {m.lower() for m in get_args(Metric)}
_INSTRUMENT_RE = re.compile(r"(?i)(subsid|tariff|mandate|quota|\bpolicy\b|program|_(?:19|20)\d\d)")


def _is_instrument_endpoint(name: str) -> bool:
    n = name.strip().lower()
    return n in _METRIC_VALUES or bool(_INSTRUMENT_RE.search(name))


# ── edge-class taxonomy (cascade engine) ─────────────────────────────────────────
# PROPAGATING edges carry a shock from one node to another (the cascade scaffolding); REFERENCE edges
# are structural/origin facts that don't propagate; CORROBORATION edges relate claims/series. Used to
# (a) weight retrieval toward cascades and (b) collapse the metric-agnostic `produces` flood without
# ever touching a real cascade edge. Light normalization — we never merge near-duplicate cascades.
PROPAGATING_EDGES = {
    "causes", "affects_yield_of", "teleconnects_to", "amplifies", "dampens", "substitutes_for",
    "competes_with", "crushed_into", "refined_into", "feedstock_for", "diverted_to", "redirects_to",
    "restricts", "subsidizes", "delays", "disrupts",
}
REFERENCE_EDGES = {"produces", "depends_on", "belongs_to_group"}
CORROBORATION_EDGES = {"leads_lags", "correlates_with", "precedes", "confirms", "contradicts", "cited_by"}


def _edge_class(relation_type: str) -> str:
    if relation_type in PROPAGATING_EDGES:
        return "propagating"
    if relation_type in CORROBORATION_EDGES:
        return "corroboration"
    return "reference"   # produces/depends_on/belongs_to_group + any unknown → low-weight, not a cascade


def collapse_reference_edges(rels: list) -> list:
    """Collapse the metric-agnostic `produces` flood (~52% of edges) to ONE edge per (src,dst), metric
    dropped — origin facts don't carry a metric. Every PROPAGATING cascade edge is left untouched (we
    never merge near-duplicate cascades; the multi-hop richness is the asset). Returns a new list."""
    out, seen = [], set()
    for r in rels:
        if r.relation_type == "produces":
            key = (r.src_entity, r.dst_entity)
            if key in seen:
                continue
            seen.add(key)
            r = r.model_copy(update={"metric": None})
        out.append(r)
    return out


def _normalize(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[\s_\-]+", " ", s).strip().lower()


@lru_cache(maxsize=1)
def _region_lookup() -> dict[str, str]:
    """normalized surface form → canonical region, from the harvested configs/graphrag/regions.yaml."""
    p = _CFG / "regions.yaml"
    if not p.exists():
        return {}
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    lk: dict[str, str] = {}
    for canon, meta in (data.get("regions") or {}).items():
        lk[_normalize(canon)] = canon
        for a in (meta or {}).get("aliases", []):
            lk.setdefault(_normalize(a), canon)
    return lk


def _canon_region(name: str) -> Optional[str]:
    return _region_lookup().get(_normalize(name))


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


def _chunk_props() -> dict:
    """The six ChunkExtraction list-fields as a JSON-schema property dict — shared by the lean tool and
    the mini-batch tool. ChunkExtraction fills defaults for any field the model omits."""
    s = {"type": "string"}
    arr = lambda props: {"type": "array", "items": {"type": "object", "properties": props}}  # noqa: E731
    return {
        "entities": arr({"id": s, "type": s, "canonical_name": s, "mapped": {"type": "boolean"}}),
        "relationships": arr({"src": s, "dst": s, "relation_type": s, "metric": s, "sign": s,
                              "evidence_class": s, "marker": s, "verbatim": s, "mapped": {"type": "boolean"}}),
        "events": arr({"event_type": s, "commodity": s, "country": s, "description": s, "verbatim": s}),
        "quantitative_claims": arr({"entity": s, "metric": s, "value": {"type": "number"}, "unit": s,
                                    "period": s, "direction": s, "verbatim": s}),
        "unmapped_relations": {"type": "array", "items": s},
        "unmapped_entities": {"type": "array", "items": s}}


def _lean_schema() -> dict:
    """Hand-written minimal input_schema matching ChunkExtraction's field names/shapes — ~400 tok vs the
    ~1,500-tok auto model_json_schema(). ChunkExtraction fills defaults for any field the model omits."""
    return {"type": "object", "properties": _chunk_props()}


def extraction_tool(lean: bool = False) -> dict:
    """The forced-tool schema. lean=True swaps the verbose auto-schema for a compact hand-written one
    (same field names → parse_extraction still validates)."""
    return {
        "name": "emit_extraction",
        "description": "Emit the structured graph extracted from the CURRENT chunk only.",
        "input_schema": _lean_schema() if lean else ChunkExtraction.model_json_schema(),
    }


def minibatch_extraction_tool(lean: bool = True) -> dict:
    """Forced-tool schema for a MINI-BATCH request: ONE extraction object per labeled [Pk] proposition,
    keyed by prop_index. This amortizes the system+tool prefix across K props (the cacheless cost lever)
    while keeping each proposition atomic — the fix for the blob-of-props recall loss. The per-item
    schema is always the compact `_chunk_props()` (a verbose per-item schema would bloat the very prefix
    the batching is trying to save); `lean` is accepted for call-site symmetry."""
    _ = lean
    item_props = {"prop_index": {"type": "integer", "description": "1-based index of the [Pk] proposition"},
                  **_chunk_props()}
    return {
        "name": "emit_minibatch_extraction",
        "description": ("Emit ONE structured extraction per labeled proposition [P1]..[PK]. Each "
                        "results entry's prop_index MUST equal the [Pk] number; extract each "
                        "proposition INDEPENDENTLY (neighbors are context only)."),
        "input_schema": {"type": "object", "properties": {
            "results": {"type": "array", "items": {"type": "object", "properties": item_props}}}},
    }


# ── compact-output schema (the OUTPUT-token lever — Exp-1 showed output = 72% of the warm call) ──
# Short-key ↔ full-field maps. Output keys are shortened (fewer structural tokens); the re-inflated dict
# uses the canonical field names so parse_extraction / to_contracts are unchanged.
_SHORT_TOP = {"E": "entities", "R": "relationships", "V": "events", "Q": "quantitative_claims",
              "UR": "unmapped_relations", "UE": "unmapped_entities"}
_SHORT_ENT = {"i": "id", "t": "type"}
_SHORT_REL = {"s": "src", "d": "dst", "r": "relation_type", "m": "metric", "g": "sign",
              "c": "evidence_class", "k": "marker"}
_SHORT_CLAIM = {"e": "entity", "m": "metric", "n": "value", "u": "unit", "p": "period", "g": "direction"}
_SHORT_EVENT = {"y": "event_type", "c": "commodity", "o": "country", "x": "description"}


def compact_output_tool(short: bool = False) -> dict:
    """Output-trimmed forced-tool schema. ALWAYS omits `verbatim` (the echoed source span — the biggest
    output term), `canonical_name` (defaults to id) and `mapped` (recomputed) → fewer OUTPUT tokens at ~no
    recall cost (provenance falls to chunk level). `short=True` ALSO shortens the keys (more saving, higher
    model-comprehension risk — the experiment's secondary arm). Same tool NAME so the forced tool_choice is
    unchanged. Pair with build_system_prompt(slim=True) + parse_compact(short=...)."""
    s = {"type": "string"}
    arr = lambda props: {"type": "array", "items": {"type": "object", "properties": props}}  # noqa: E731
    if short:
        top = {"E": arr({"i": s, "t": s}),
               "R": arr({"s": s, "d": s, "r": s, "m": s, "g": s, "c": s, "k": s}),
               "V": arr({"y": s, "c": s, "o": s, "x": s}),
               "Q": arr({"e": s, "m": s, "n": {"type": "number"}, "u": s, "p": s, "g": s}),
               "UR": {"type": "array", "items": s}, "UE": {"type": "array", "items": s}}
        desc = ("Emit the graph from the CURRENT chunk with COMPACT keys (omit verbatim/canonical_name/"
                "mapped). E=entities[i=id,t=type]; R=relationships[s=src,d=dst,r=relation_type,m=metric,"
                "g=sign(+/-/0),c=evidence_class,k=marker]; V=events[y=event_type,c=commodity,o=country,"
                "x=description]; Q=quantitative_claims[e=entity,m=metric,n=value,u=unit,p=period,"
                "g=direction]; UR=unmapped_relations; UE=unmapped_entities.")
    else:
        top = {"entities": arr({"id": s, "type": s}),
               "relationships": arr({"src": s, "dst": s, "relation_type": s, "metric": s, "sign": s,
                                     "evidence_class": s, "marker": s}),
               "events": arr({"event_type": s, "commodity": s, "country": s, "description": s}),
               "quantitative_claims": arr({"entity": s, "metric": s, "value": {"type": "number"},
                                           "unit": s, "period": s, "direction": s}),
               "unmapped_relations": {"type": "array", "items": s},
               "unmapped_entities": {"type": "array", "items": s}}
        desc = "Emit the graph from the CURRENT chunk. Omit verbatim/canonical_name/mapped (chunk-level provenance)."
    return {"name": "emit_extraction", "description": desc, "input_schema": {"type": "object", "properties": top}}


# ── prompt (reads the git-ignored vocab/hierarchy IP at runtime) ──────────────────
def _merge_seed(v: dict, seed: dict) -> None:
    """Additively merge a harvested seed (Phase-1 harvest) into the vocab — new node members + aliases +
    verb_normalization + causal_markers. Idempotent; never removes. Keeps entity_vocabulary.yaml as the
    hand-curated base while the harvest extends it (reversible: delete research_seed.active.yaml)."""
    nodes, aliases = v.setdefault("nodes", {}), v.setdefault("aliases", {})
    for ntype in ("hazard", "climate_driver", "state_marker", "policy_event", "instrument"):
        members = list(nodes.get(ntype) or [])
        for concept, forms in (seed.get(ntype) or {}).items():
            if concept not in members:
                members.append(concept)
            if forms:
                al = aliases.setdefault(concept, [])
                al.extend(f for f in forms if f not in al)
        nodes[ntype] = members
    v.setdefault("verb_normalization", {}).update(seed.get("verb_normalization") or {})
    cm = v.setdefault("causal_markers", [])
    cm.extend(m for m in (seed.get("causal_markers") or []) if m not in cm)


def _vocab() -> dict:
    v = yaml.safe_load((_CFG / "entity_vocabulary.yaml").read_text(encoding="utf-8"))
    seed_p = _CFG / "research_seed.active.yaml"             # pruned seed (harvest output); else the raw seed
    seed_p = seed_p if seed_p.exists() else _CFG / "research_seed.yaml"
    if seed_p.exists():
        _merge_seed(v, yaml.safe_load(seed_p.read_text(encoding="utf-8")) or {})
    return v


_SLIM_NOTE = ("\n\nCOMPACT OUTPUT: OMIT the `verbatim`, `canonical_name`, and `mapped` fields entirely "
              "(provenance is tracked at chunk level; canonical_name defaults to the id). Still add "
              "non-vocab entities to unmapped_entities and non-fitting relations to unmapped_relations.")


def build_system_prompt(lean: bool = False, slim: bool = False) -> str:
    v = _vocab()
    node_types = list(v.get("nodes", {}).keys())
    edges = list(v.get("edges", {}).keys())
    markers = v.get("causal_markers", [])

    def _members(t: str) -> str:
        # show the FULL list — truncating drops valid nodes (e.g. the softs/tropicals) and produces
        # false "unmapped" signals for commodities that ARE in the vocab.
        return ", ".join(v["nodes"].get(t) or []) or "(open set — mint instances)"

    node_lines = "\n".join(f"  {t}: {_members(t)}" for t in node_types)
    if lean:
        # Compact variant (~1.7K tok vs ~4.3K): keeps the recall-drivers (node-model, full node lists,
        # edges, markers, few-shot) but strips verbosity. Pairs with extraction_tool(lean=True).
        return f"""Knowledge-graph extractor for Leviathan's CAUSAL CASCADE graph (commodity quant research).
PRIORITIZE cascade edges: causal links, cross-commodity substitution/competition, crush + biofuel
feedstock, supply-demand, policy->trade. Extract ONLY what the CURRENT chunk states (prior/next = context).

NODE-MODEL: a node is a COMMODITY/entity; the metric (production/yield/export/import/stock/consumption/
area/price/spread/...) + direction ride on the RELATION (metric,sign) or a quantitative_claim — never a
metric-in-node id (no `arabica_production`; use `arabica_coffee` + metric=production).

CANONICALIZE entities to these node TYPES (resolve aliases; if none fits -> mapped=false + add to
unmapped_entities):
{node_lines}

RELATIONS — use ONLY: {", ".join(edges)}. Set sign +/-/0 and metric=the series the DESTINATION moves
(yield/price/export/import/stock/production/...). A price->yield or policy->yield link is a VALID causal
chain — emit it (affects_yield_of/causes, metric=yield); never drop a link for being indirect/multi-hop.
No fit -> relation_type="OTHER", mapped=false, describe in unmapped_relations (do NOT force-fit). Prefer
causes/affects_yield_of when a causal marker is present ({", ".join(markers[:8])}); a causal link with no
marker -> emit with marker=null. evidence_class in {{fact,reported_claim,model_inference}}. Every
relation/claim carries the exact `verbatim`.

HYGIENE: never emit a self-edge (src==dst). A subsidy/tariff/mandate/quota is an EDGE
(subsidizes/restricts) FROM the country/org TO the commodity — do NOT mint a policy node (no
`soybean_subsidy_2025`, `import_tariff_soybeans`). affects_yield_of always has metric=yield.

EXAMPLES:
- "India cotton yield fell due to erratic monsoon": excess_rain -affects_yield_of(-)-> cotton [yield], marker="due to".
- "Russia produced 0.7 mmt more corn": Russia -produces(+)-> corn [production]; claim corn production +0.7 mmt.
- "Snow protected Turkey winter crops from frost": protective_snow_cover -affects_yield_of(+)-> wheat [yield].
- "Sunflower oil glut pressured palm oil": sunflower_oil -substitutes_for(+)-> palm_oil [price].
- "Shrimp farmers bid for the protein": shrimp NOT a node -> mapped=false, add to unmapped_entities.
Emit via emit_extraction only.""" + (_SLIM_NOTE if slim else "")
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
The `metric` is the series the DESTINATION moves (yield, price, production, export, import, stock,
consumption, area, spread). An INDIRECT link is still real: a price → yield effect (farmers substitute
crops), or a policy → yield effect, is a valid causal chain — emit it as affects_yield_of/causes with
metric=yield. NEVER drop a relationship just because it is multi-hop or indirect; those chains are the
whole point of the graph.
If a real relationship does NOT fit one of these edge types, set relation_type="OTHER", mapped=false,
AND add a short description to unmapped_relations. Do NOT force a bad fit — we are measuring coverage.

CAUSAL anchors (prefer minting a `causes`/`affects_yield_of` edge when the sentence contains one):
  {markers}
If you see a clear causal link with NO anchor phrase, still emit it but leave `marker` null.

Every relation and claim MUST carry the exact `verbatim` source span. evidence_class ∈
{{fact, reported_claim, model_inference}}. Return empty lists where nothing applies.

GRAPH HYGIENE (these fragment or corrupt the graph):
- NEVER emit a self-edge — src and dst must differ (no `soybeans -causes-> soybeans`).
- A policy instrument (subsidy, tariff, mandate, quota, biofuel mandate) is an EDGE, not a node: emit
  `country/org -subsidizes|restricts-> commodity`. Do NOT mint a named policy node such as
  `soybean_subsidy_2025` or `import_tariff_soybeans` — those never join across documents.
- `affects_yield_of` moves YIELD by definition → its metric is always `yield` (never price/production).

EXAMPLES (how to fill emit_extraction):
1. "India cotton yield fell in 2017/18 due to erratic monsoon rainfall."
   entities: excess_rain(hazard), cotton(commodity), India(country_origin)
   relationships: [excess_rain -affects_yield_of(-)-> cotton, metric=yield, marker="due to", evidence=reported_claim]
   quantitative_claims: [cotton, metric=yield, direction=-]
2. "Russia produced a record 0.7 mmt more corn than last year."  (origin anchor)
   relationships: [Russia -produces(+)-> corn, metric=production, evidence=fact]
   quantitative_claims: [corn, metric=production, value=0.7, unit=mmt, direction=+]
3. "Favorable snow cover in Turkey protected winter crops against frost."  (BENEFICIAL weather → +)
   entities: protective_snow_cover(beneficial_weather), wheat(commodity), Turkey(country_origin)
   relationships: [protective_snow_cover -affects_yield_of(+)-> wheat, metric=yield, evidence=fact]
4. "Sunflower oil glut in the Black Sea pressured palm oil."  (cross-commodity substitution)
   relationships: [sunflower_oil -substitutes_for(+)-> palm_oil, metric=price]
5. "Shrimp farmers also bid for the protein."  → shrimp is NOT a node type: mapped=false, add
   "shrimp" to unmapped_entities. NEVER force a non-vocab term into a node — we measure coverage.

Emit via the emit_extraction tool only.""" + (_SLIM_NOTE if slim else "")


def build_user_message(prev_text: str, current_text: str, next_text: str) -> str:
    return (f"[PRIOR CONTEXT]\n{prev_text or '(none)'}\n\n"
            f"[CURRENT CHUNK — extract from this]\n{current_text}\n\n"
            f"[NEXT CONTEXT]\n{next_text or '(none)'}")


def build_minibatch_message(props: list[str], *, prev: str = "", next: str = "") -> str:
    """K consecutive propositions in ONE request, each a labeled [Pk] unit. They are each other's local
    context (a coherence gain over the K=1 prev/next), but each relation must be anchored in its own
    [Pk]. Pairs with minibatch_extraction_tool — emit one results entry per [Pk]."""
    labeled = "\n\n".join(f"[P{i + 1}] {p}" for i, p in enumerate(props))
    return ("Extract from EACH labeled proposition below INDEPENDENTLY. The other propositions and the "
            "PRIOR/NEXT context are background only — anchor every relation in its own [Pk]. Return "
            "exactly one results entry per [Pk] (prop_index = k).\n\n"
            f"[PRIOR CONTEXT]\n{prev or '(none)'}\n\n"
            f"[PROPOSITIONS]\n{labeled}\n\n"
            f"[NEXT CONTEXT]\n{next or '(none)'}")


# ── the Opus call (forced tool use) ───────────────────────────────────────────────
# prompt-cache write multipliers (× base input price): 1.25× for the default 5-minute TTL, 2× for 1-hour.
_CACHE_WRITE_MULT = {None: 1.25, "5m": 1.25, "1h": 2.0}
_CACHE_READ_MULT = 0.1
_EXT_CACHE_BETA = "extended-cache-ttl-2025-04-11"   # required for ttl="1h"


@dataclass
class Usage:
    input_tokens: int = 0          # processed at full price (not cached)
    output_tokens: int = 0
    cache_creation: int = 0        # prefix tokens WRITTEN to cache this call (paid the write premium)
    cache_read: int = 0            # prefix tokens SERVED from cache this call (paid 0.1×)

    @property
    def cost(self) -> float:
        """Back-compat: Opus-priced, cache-agnostic (existing callers don't use caching)."""
        return self.input_tokens * PRICE_IN + self.output_tokens * PRICE_OUT

    @property
    def total_input(self) -> int:
        """Full prompt size = uncached + written + read (input_tokens alone is the uncached remainder)."""
        return self.input_tokens + self.cache_creation + self.cache_read

    def cost_for(self, model: str = MODEL, ttl: str | None = None) -> float:
        """True billed cost for `model`, pricing the cache buckets: reads 0.1×, writes 1.25× (5m) / 2× (1h)."""
        pin, pout = price(model)
        return (self.input_tokens * pin
                + self.cache_read * pin * _CACHE_READ_MULT
                + self.cache_creation * pin * _CACHE_WRITE_MULT.get(ttl, 1.25)
                + self.output_tokens * pout)


def _usage_from(u) -> Usage:
    """Read a response usage object into our dataclass, tolerating missing cache fields (sync no-cache
    responses omit them)."""
    if u is None:
        return Usage()
    return Usage(input_tokens=getattr(u, "input_tokens", 0) or 0,
                 output_tokens=getattr(u, "output_tokens", 0) or 0,
                 cache_creation=getattr(u, "cache_creation_input_tokens", 0) or 0,
                 cache_read=getattr(u, "cache_read_input_tokens", 0) or 0)


def call_opus(client, system: str, user: str, *, model: str = MODEL,
              max_tokens: int = 4096, tool: dict | None = None) -> tuple[dict, Usage]:
    """One forced-tool extraction call. Returns (tool_input_dict, usage). Retries are the caller's job
    (kept thin so the unit test can pass a trivial fake client). `tool` defaults to the full schema; pass
    extraction_tool(lean=True) for the lean schema (e.g. the bake-off)."""
    tool = tool or extraction_tool()
    resp = client.messages.create(
        model=model, max_tokens=max_tokens, system=system,
        messages=[{"role": "user", "content": user}],
        tools=[tool],
        tool_choice={"type": "tool", "name": tool["name"]},
    )
    if getattr(resp, "stop_reason", None) == "max_tokens":
        # NEVER silently accept a truncated structured result — a partial tool_use drops trailing fields
        # (this is what swallowed soybeans' inter_commodity + convergence). Caller must raise max_tokens or stream.
        raise ValueError(f"output truncated at max_tokens={max_tokens} (stop_reason=max_tokens); "
                         "raise max_tokens or switch this call to streaming")
    tool_input = next((b.input for b in resp.content if getattr(b, "type", None) == "tool_use"), None)
    if tool_input is None:
        raise ValueError("model returned no tool_use block")
    return tool_input, _usage_from(getattr(resp, "usage", None))


def call_opus_stream(client, system: str, user, *, model: str = MODEL, max_tokens: int = 4096,
                     tool: dict | None = None, on_token=None) -> tuple[dict, Usage]:
    """Streaming forced-tool call — same contract as call_opus (returns (tool_input_dict, usage)), but relays
    the tool's `input_json_delta` text to `on_token` as it generates so the UI can render the note live
    instead of blocking on the full completion. The SDK assembles the final message. A progress callback must
    NEVER break the turn, so its errors are swallowed."""
    tool = tool or extraction_tool()
    with client.messages.stream(
        model=model, max_tokens=max_tokens, system=system,
        messages=[{"role": "user", "content": user}],
        tools=[tool],
        tool_choice={"type": "tool", "name": tool["name"]},
    ) as stream:
        if on_token is not None:
            for event in stream:
                if getattr(event, "type", None) == "content_block_delta":
                    pj = getattr(getattr(event, "delta", None), "partial_json", None)
                    if pj:
                        try:
                            on_token(pj)
                        except Exception:  # noqa: BLE001 — never let a UI callback break generation
                            pass
        final = stream.get_final_message()
    if getattr(final, "stop_reason", None) == "max_tokens":
        raise ValueError(f"output truncated at max_tokens={max_tokens} (stop_reason=max_tokens); raise max_tokens")
    tool_input = next((b.input for b in final.content if getattr(b, "type", None) == "tool_use"), None)
    if tool_input is None:
        raise ValueError("model returned no tool_use block")
    return tool_input, _usage_from(getattr(final, "usage", None))


def _cache_control(ttl: str | None) -> dict:
    cc = {"type": "ephemeral"}
    if ttl == "1h":
        cc["ttl"] = "1h"
    return cc


def _aslist(v) -> list:
    """Tolerate a stringified array (the model occasionally JSON-encodes a list field)."""
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except (json.JSONDecodeError, TypeError):
            return []
    return v if isinstance(v, list) else []


def _drop_none(d: dict) -> dict:
    return {k: v for k, v in d.items() if v is not None}


def parse_compact(tool_input: dict, *, short: bool = False) -> ChunkExtraction:
    """Re-inflate a `compact_output_tool` result into a full ChunkExtraction (verbatim="", canonical_name=id,
    mapped defaulted) and validate via parse_extraction — so to_contracts and all downstream mapping are
    unchanged. Omitted/None fields fall back to the contract defaults. `short=True` expands the short keys."""
    raw = tool_input
    if short:
        raw = {_SHORT_TOP.get(k, k): v for k, v in tool_input.items()}
        raw = {
            "entities": [{_SHORT_ENT.get(k, k): v for k, v in e.items()} for e in _aslist(raw.get("entities")) if isinstance(e, dict)],
            "relationships": [{_SHORT_REL.get(k, k): v for k, v in r.items()} for r in _aslist(raw.get("relationships")) if isinstance(r, dict)],
            "events": [{_SHORT_EVENT.get(k, k): v for k, v in e.items()} for e in _aslist(raw.get("events")) if isinstance(e, dict)],
            "quantitative_claims": [{_SHORT_CLAIM.get(k, k): v for k, v in c.items()} for c in _aslist(raw.get("quantitative_claims")) if isinstance(c, dict)],
            "unmapped_relations": _aslist(raw.get("unmapped_relations")),
            "unmapped_entities": _aslist(raw.get("unmapped_entities"))}
    ents = [_drop_none({"id": e.get("id"), "type": e.get("type"), "canonical_name": e.get("id")})
            for e in _aslist(raw.get("entities")) if isinstance(e, dict)]
    rel_keys = ("src", "dst", "relation_type", "metric", "sign", "evidence_class", "marker")
    rels = [{**_drop_none({k: r.get(k) for k in rel_keys}), "verbatim": ""}
            for r in _aslist(raw.get("relationships")) if isinstance(r, dict)]
    cl_keys = ("entity", "metric", "value", "unit", "period", "direction")
    claims = [{**_drop_none({k: c.get(k) for k in cl_keys}), "verbatim": ""}
              for c in _aslist(raw.get("quantitative_claims")) if isinstance(c, dict)]
    ev_keys = ("event_type", "commodity", "country", "description")
    events = [{**{k: e.get(k, "") for k in ev_keys}, "verbatim": ""}
              for e in _aslist(raw.get("events")) if isinstance(e, dict) and all(e.get(k) for k in ev_keys)]
    return parse_extraction({"entities": ents, "relationships": rels, "quantitative_claims": claims,
                             "events": events, "unmapped_relations": _aslist(raw.get("unmapped_relations")),
                             "unmapped_entities": _aslist(raw.get("unmapped_entities"))})


def call_extract(client, system: str, user: str, *, model: str = SONNET, max_tokens: int = 4096,
                 cache: bool = False, ttl: str | None = None,
                 tool: dict | None = None) -> tuple[dict, Usage]:
    """The PRODUCTION extraction call (forced tool use). When ``cache=True`` the static prefix (tools +
    system) is sent with a ``cache_control`` breakpoint on the last system block — render order is
    tools → system → messages, so one breakpoint caches both. Repeat calls over the same prefix then read
    it at 0.1×. ``ttl="1h"`` uses the 1-hour cache (2× write) + the extended-cache beta header; default is
    the 5-minute TTL. ``tool_choice`` stays forced — it only invalidates the messages tier, never the
    cached tools+system. Returns (tool_input, Usage) with the cache buckets populated. Retries are the
    caller's job (kept thin for the unit fake)."""
    tool = tool or extraction_tool()
    kw: dict = dict(model=model, max_tokens=max_tokens,
                    messages=[{"role": "user", "content": user}],
                    tools=[tool], tool_choice={"type": "tool", "name": tool["name"]})
    if cache:
        kw["system"] = [{"type": "text", "text": system, "cache_control": _cache_control(ttl)}]
        if ttl == "1h":
            kw["extra_headers"] = {"anthropic-beta": _EXT_CACHE_BETA}
    else:
        kw["system"] = system
    resp = client.messages.create(**kw)
    tool_input = next((b.input for b in resp.content if getattr(b, "type", None) == "tool_use"), None)
    if tool_input is None:
        raise ValueError("model returned no tool_use block")
    return tool_input, _usage_from(getattr(resp, "usage", None))


def warm_cache(client, system: str, *, model: str = SONNET, ttl: str | None = None,
               tool: dict | None = None) -> Usage:
    """Pre-warm the tools+system cache with a ``max_tokens=0`` prefill — the API writes the cache at the
    breakpoint and returns immediately (no output billed). ``tool_choice`` is OMITTED: ``max_tokens=0``
    rejects a forced ``{"type":"tool"}`` choice, and tool_choice doesn't affect the tools+system cache
    anyway, so a real forced call reads what this writes. Use before a concurrent fan-out so workers read
    the cache instead of each racing to write it. Returns the Usage (``cache_creation`` should be > 0)."""
    kw: dict = dict(model=model, max_tokens=0,
                    system=[{"type": "text", "text": system, "cache_control": _cache_control(ttl)}],
                    messages=[{"role": "user", "content": "warmup"}],
                    tools=[tool or extraction_tool()])
    if ttl == "1h":
        kw["extra_headers"] = {"anthropic-beta": _EXT_CACHE_BETA}
    resp = client.messages.create(**kw)
    return _usage_from(getattr(resp, "usage", None))


def parse_extraction(tool_input: dict) -> ChunkExtraction:
    # Opus occasionally stringifies a list field in the tool input (`entities`: "[{...}]"); coerce
    # those back before validating so one quirky result can't crash a whole batch retrieval.
    fixed = dict(tool_input)
    for k in ("entities", "relationships", "events", "quantitative_claims",
              "unmapped_relations", "unmapped_entities"):
        if isinstance(fixed.get(k), str):
            try:
                fixed[k] = json.loads(fixed[k])
            except (json.JSONDecodeError, TypeError):
                fixed[k] = []
    return ChunkExtraction.model_validate(fixed)


def parse_minibatch(tool_input: dict) -> list[tuple[int, ChunkExtraction]]:
    """Split a mini-batch tool result into (prop_index, ChunkExtraction) pairs, reusing parse_extraction
    per item. Tolerant: a stringified `results`, a missing/garbled prop_index, or one malformed item
    never sinks the batch — bad items are skipped (the caller scores a missing index as a friction miss)."""
    results = tool_input.get("results")
    if isinstance(results, str):
        try:
            results = json.loads(results)
        except (json.JSONDecodeError, TypeError):
            results = []
    out: list[tuple[int, ChunkExtraction]] = []
    for item in results or []:
        if not isinstance(item, dict):
            continue
        try:
            idx = int(item.get("prop_index"))
        except (TypeError, ValueError):
            continue
        rest = {k: v for k, v in item.items() if k != "prop_index"}
        try:
            out.append((idx, parse_extraction(rest)))
        except Exception:  # noqa: BLE001 — skip a malformed item, keep the rest of the batch
            continue
    return out


# ── map the loose extraction into strict contracts + collect friction ─────────────
@dataclass
class Friction:
    unmapped_relations: list[str] = field(default_factory=list)   # OTHER-typed or escape-listed
    unmapped_entities: list[str] = field(default_factory=list)
    validation_failures: list[str] = field(default_factory=list)  # would-be records that failed
    causal_without_marker: int = 0                                # would be dropped by the strict rule
    causal_without_metric: int = 0                                # causes/affects_yield_of with no metric (soft)
    dangling_endpoints: list[str] = field(default_factory=list)   # edges whose src/dst aren't canonical
    self_loops: int = 0                                           # G1 — src==dst, dropped
    dropped_instrument: int = 0                                   # G2 — metric/instrument-as-node, dropped
    yield_metric_fixed: int = 0                                   # G3 — affects_yield_of metric coerced→yield
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
        if e.type not in node_types:
            fr.unmapped_entities.append(f"{e.id} ({e.type})")
            continue
        # Mapped-ness is decided by OUR vocab, not Opus's self-reported `mapped` flag (it marks valid
        # nodes like `Thailand`/`Pakistan` false when hedging → false-unmapped if we trust it).
        eid, name = e.id, e.canonical_name
        if e.id not in node_members:
            canon = _canon_region(e.id) if e.type == "region" else None  # harvested-region resolution
            if canon is None:
                fr.unmapped_entities.append(f"{e.id} ({e.type})")
                continue
            eid = name = canon
        try:
            out["entities"].append(Entity(entity_id=eid, type=e.type, canonical_name=name))
            fr.n_entities += 1
        except ValidationError as ex:
            fr.validation_failures.append(f"entity {eid}: {ex.error_count()} err")

    for r in x.relationships:
        if r.relation_type not in edges or not r.mapped:
            fr.unmapped_relations.append(f"{r.src} -[{r.relation_type}]-> {r.dst}")
            continue
        if r.src == r.dst:                                    # G1 — a node can't cause/affect itself
            fr.self_loops += 1
            continue
        # G2 — endpoint check: DROP edges whose dangling endpoint is a non-node concept (a metric name or a
        # minted policy instrument); KEEP genuine unmapped commodities (flagged → coverage signal to fold).
        dropped = False
        for end in (r.src, r.dst):
            if end not in node_members and _canon_region(end) is None:
                if _is_instrument_endpoint(end):
                    fr.dropped_instrument += 1
                    fr.dangling_endpoints.append(f"{end} (DROPPED instrument, in {r.src}-[{r.relation_type}]->{r.dst})")
                    dropped = True
                    break
                fr.dangling_endpoints.append(f"{end} (in {r.src}-[{r.relation_type}]->{r.dst})")
        if dropped:
            continue
        metric = _norm_metric(r.metric)
        if r.relation_type == "affects_yield_of":            # G3 — definitionally moves yield
            if metric != "yield":
                fr.yield_metric_fixed += 1
            metric = "yield"
        if metric is None and r.relation_type in ("causes", "affects_yield_of"):  # G4 — soft flag (kept)
            fr.causal_without_metric += 1
        if r.marker is None and r.relation_type in ("causes", "affects_yield_of"):
            fr.causal_without_marker += 1
        sign = r.sign if r.sign in ("+", "-", "0") else "0"
        evidence = r.evidence_class if r.evidence_class in _CONF_BY_EVIDENCE else "reported_claim"
        eid = hashlib.sha1(f"{chunk.chunk_id}|{r.src}|{r.relation_type}|{r.dst}".encode()).hexdigest()[:16]
        try:
            out["relationships"].append(Relationship(
                edge_id=eid, src_entity=r.src, dst_entity=r.dst, relation_type=r.relation_type,
                metric=metric or None, sign=sign, confidence=_CONF_BY_EVIDENCE[evidence],
                evidence_class=evidence, edge_scope="structural", sources=[_sref(chunk, r.verbatim)]))
            fr.n_relationships += 1
        except ValidationError as ex:
            fr.validation_failures.append(f"rel {r.src}->{r.dst}: {ex.error_count()} err")

    for i, c in enumerate(x.quantitative_claims):
        direction = c.direction if c.direction in ("+", "-", "0") else "0"
        try:
            out["quantitative_claims"].append(QuantitativeClaim(
                claim_id=f"{chunk.chunk_id}#q{i}", chunk_id=chunk.chunk_id, entity_id=c.entity,
                metric=_norm_metric(c.metric), value=c.value, unit=c.unit, period=c.period or "unknown",
                direction=direction, document_date=chunk.document_date))
        except ValidationError:
            fr.validation_failures.append(f"claim metric={c.metric!r}")

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
