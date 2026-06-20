# ADR-001 — GraphRAG graph foundation: custom assembly vs Microsoft `graphrag`

- **Status:** Accepted
- **Date:** 2026-06
- **Phase:** GraphRAG Phase 1 (W0). Decided *before* the pipeline is built, so we never
  construct Phases 2–4 on a foundation we'd later rip out (GraphRAG plan, Fix 5 / §2).

## Context

The GraphRAG layer needs a graph store + retrieval substrate. Microsoft `graphrag` is the
obvious candidate framework. But the design's requirements diverge sharply from what that
framework optimizes for:

- **Typed/signed/dated edges** with `evidence_class`, `edge_scope`, `validity_window`,
  `event_id`, `support_count` (contracts in `src/leviathan/graphrag/contracts.py`).
- **Verbatim-span provenance** (our own chunker; `graphrag` owns chunking).
- **Hybrid retrieval** (graph-local + dense + BM25) with **end-to-end PIT time-gating** we must
  audit at every stage.
- A bespoke **cascade traversal engine** (path templates, silver-confirmed joint support,
  confidence decay).
- `graphrag`'s differentiator — **community detection + global/thematic synthesis** — is
  **deferred** (plan Phase 10), and is a *summarization* capability, not the cited, time-gated,
  causal-chain capability we need.

## Decision criteria

| # | Criterion | Weight |
|---|---|---|
| 1 | Stores our rich edge schema (typed/signed/dated + evidence_class/edge_scope/events) natively | high |
| 2 | Lets us replace its chunker + extraction with our verbatim/vocab-constrained pipeline | high |
| 3 | Gives full control of hybrid retrieval + auditable PIT gating | high |
| 4 | Supports arbitrary cascade traversal (depth/beam/templates) over typed edges | high |
| 5 | Provides community detection cheaply *if/when* global search (Phase 10) is built | low |
| 6 | Low maintenance / version-churn risk | med |

## Options

**A. Adopt Microsoft `graphrag`, override the parts that don't fit.** We would override its
chunker, extraction schema, inference client, retriever, and reranker, and bypass its
community/global differentiator — i.e. ~everything. Net: we'd carry a heavy dependency while
using almost none of it, and fight its data model + version churn to shoehorn our schema.

**B. Custom assembly.** `networkx`/`igraph` for the typed graph (full traversal control for the
cascade engine) + **LanceDB** for entity/chunk vectors (embedded, in-AWS, matches the local
`bge-m3` residency posture) + our Pydantic/parquet **contracts** as the schema source of truth.

## Decision — **B (custom).**

Our contracts already define the schema; `networkx`/`igraph` give unconstrained traversal for
the cascade engine; `LanceDB` keeps vectors local/in-AWS (no query egress, consistent with the
embeddings decision). Adopting `graphrag` would mean overriding its entire pipeline to host a
schema it doesn't model, for a framework whose one differentiator we don't use in v1.

**Borrow, don't adopt:** if/when global search ships (Phase 10), pull **`leidenalg`** (the
community-detection algorithm) onto our own graph — a few lines — without taking the framework.

## Consequences

- **(+)** Schema-native; no framework fight; full control of retrieval, PIT, and traversal;
  one fewer heavy dependency; vectors stay in-AWS.
- **(−)** We build graph assembly + retrieval ourselves — but per the override analysis that was
  ~all our code regardless; the framework was saving us little.
- **Revisit if:** a future `graphrag` release natively models typed/temporal/evidence-classed
  edges *and* exposes our override points cleanly — at which point re-running this ADR is cheap.
