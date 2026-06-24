# Phase 3 Taxonomy Implementation

Implemented: 2026-06-24

## Purpose

Phase 3 adds a strict ML entity taxonomy so training problems are defined by
physical and balance-sheet meaning, not by contract slug alone.

The legacy commodity configs remain in place, but the new taxonomy can now
classify each legacy target as direct, proxy, or blocked before Phase 4 builds
point-in-time gold v2.

## Added Configs

- `configs/entities/physical_commodities.yaml`
- `configs/entities/processed_products.yaml`
- `configs/entities/contract_mappings.yaml`
- `configs/entities/target_dictionary.yaml`
- `configs/entities/source_precedence.yaml`
- `configs/entities/proxy_label_rules.yaml`

## Added Code

- `src/leviathan/entities/taxonomy.py`
- `src/leviathan/entities/__init__.py`

## Guardrails

- Every configured contract maps to exactly one physical commodity or processed
  product family.
- Processed-product contracts cannot silently inherit crop production, area, or
  yield targets.
- Wheat-class contracts cannot treat all-wheat FAOSTAT labels as direct labels.
- Arabica and Robusta contracts cannot treat generic green-coffee FAOSTAT
  labels as direct species labels.
- Source precedence prefers repaired source-specific tables such as NASS,
  SAGIS, CONAB, AMS cotton, and MPOB before global fallbacks.

## Phase 4 Dependency

Gold v2 should resolve entity and target semantics through
`load_entity_taxonomy()` before building any model-ready target or feature
matrix.
