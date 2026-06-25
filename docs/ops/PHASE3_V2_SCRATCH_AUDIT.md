# Phase 3 v2 Scratch Audit

Status: complete.

Completed: 2026-06-25

## Purpose

Phase 3 preserves the current `gold_v2` scratch work without letting it define
the active MLflow training path.

The current MLflow path remains the broad legacy `gold/feature_spine` and the
future versioned legacy-gold layer planned for Phase 4. The preserved v2 work is
an idea bank for taxonomy, feature sets, cataloging, availability rules, and a
future point-in-time rebuild.

GraphRAG was not touched.

## Preservation

The v2 scratch work was committed and pushed to a dedicated backup branch:

```text
codex/gold-v2-scratch-preserved
```

Preservation commit:

```text
52934c66 Preserve gold v2 scratch work
```

Source worktree:

```text
C:\Users\User\Desktop\Leviathan-phase1
```

Base commit before scratch preservation:

```text
fa8d526e Record MLflow Phase 1 platform repair
```

The Phase 1 evidence bundle in `data/system_inventory/mlflow_phase1_*` was not
committed to the v2 preservation branch. Only v2-related code, configs, DDLs,
and tests were preserved.

## Active Main State

Active `main` does not contain the preserved `gold_v2` scratch files. This is
intentional.

Do not route MLflow experiments through:

- `gold_v2/feature_spine`;
- `gold_v2/feature_matrix`;
- `gold_v2_feature_spine`;
- `gold_v2_feature_matrix`;
- `feature_spine_v2_task.py`.

Those pieces remain future PIT design material, not the production training
surface.

## Classification

| File | Classification | Decision |
| --- | --- | --- |
| `configs/datasets/datasets.yaml` | `future_pit_v2` | Contains `gold_v2_*` dataset registry additions. Keep on backup branch; do not register as active MLflow dependencies now. |
| `configs/features/feature_policies.yaml` | `adapt_now` | Policy alias ideas are useful for legacy-gold feature-set governance. Port carefully in Phase 5/6, without enabling market signals in core fitting. |
| `configs/features/feature_groups_v2.yaml` | `adapt_now` | Useful group taxonomy seed. Rename/drop v2 suffix when folded into the legacy-gold catalog path. |
| `configs/features/feature_sets_v2.yaml` | `adapt_now` | Useful model-purpose feature-set seed. Convert to `configs/features/feature_sets.yaml` in Phase 6. |
| `configs/features/feature_taxonomy_v2.yaml` | `adapt_now` | Useful semantic taxonomy seed. Convert to the non-v2 taxonomy in Phase 5. |
| `jobs/batch/feature_catalog_v2_task.py` | `adapt_now` | Useful single-writer catalog task pattern. Port to versioned legacy gold; do not keep v2 output names. |
| `jobs/batch/feature_spine_v2_task.py` | `future_pit_v2` | Thin PIT proof builder. Preserve for later; do not use for broad MLflow experiments. |
| `sql/athena/ddl/gold_v2_feature_catalog.sql` | `adapt_now` | Useful catalog DDL shape. Convert names/paths to versioned legacy-gold catalog tables. |
| `sql/athena/ddl/gold_v2_feature_entity_map.sql` | `adapt_now` | Useful entity-map DDL shape. Convert names/paths to versioned legacy-gold outputs. |
| `sql/athena/ddl/gold_v2_feature_group_map.sql` | `adapt_now` | Useful group-map DDL shape. Convert names/paths to versioned legacy-gold outputs. |
| `src/leviathan/features/availability.py` | `adapt_now` | Source-availability concept is useful. Integrate after Phase 2 certification, but do not overclaim PIT correctness where silver lacks vintages. |
| `src/leviathan/features/catalog_v2.py` | `adapt_now` | Useful catalog generation logic. Rename/generalize for legacy-gold versioned catalog in Phase 5. |
| `src/leviathan/features/extractors.py` | `adapt_now` | Bounded source-loading ideas are useful for Phase 4 performance. Port only the bounded extraction/caching pieces needed by legacy gold. |
| `src/leviathan/features/feature_sets_v2.py` | `adapt_now` | Useful selector concept. Rename/generalize for Phase 6 feature-set selection. |
| `src/leviathan/features/spine_v2.py` | `future_pit_v2` | Thin PIT spine proof. Preserve, but do not treat as feature-parity successor to legacy gold. |
| `src/leviathan/features/taxonomy_v2.py` | `adapt_now` | Useful taxonomy loader. Rename/generalize in Phase 5. |
| `src/leviathan/storage/paths.py` | `future_pit_v2` | Contains `gold_v2` path helper additions. Keep as PIT reference; Phase 4 should add versioned legacy-gold paths instead. |
| `tests/unit/test_batch_feature_catalog_v2_task.py` | `adapt_now` | Useful test pattern for catalog task. Port to legacy-gold catalog task tests. |
| `tests/unit/test_dataset_registry.py` | `future_pit_v2` | v2 registry expectations should remain deferred until PIT v2 returns. |
| `tests/unit/test_features_availability.py` | `adapt_now` | Useful availability adapter tests. Keep concepts, adjust to certified source contracts. |
| `tests/unit/test_features_catalog_v2.py` | `adapt_now` | Useful catalog fixture tests. Port to non-v2 catalog. |
| `tests/unit/test_features_feature_sets_v2.py` | `adapt_now` | Useful feature-set fixture tests. Port to non-v2 feature sets. |
| `tests/unit/test_features_spine_v2.py` | `future_pit_v2` | Tests the thin PIT proof. Preserve but do not run as active MLflow-readiness gate. |
| `tests/unit/test_features_taxonomy_v2.py` | `adapt_now` | Useful taxonomy classification tests. Port to non-v2 taxonomy. |
| `tests/unit/test_training_feature_policy.py` | `adapt_now` | Useful feature-policy guardrail tests. Fold into Phase 6 policy checks. |

## Adapt-Now Work Items

These ideas should be reused in later phases without adopting `gold_v2` as the
training source:

- source availability metadata, limited by actual silver vintage coverage;
- semantic feature taxonomy;
- model-purpose feature sets;
- single-writer feature catalog;
- feature-to-entity and feature-to-group maps;
- bounded extraction and commodity-agnostic source caching;
- immutable path and manifest patterns.

## Future PIT v2 Boundary

Future PIT v2 should resume only after the legacy-gold MLflow path is
experiment-ready.

When resumed, it must target a different goal:

- true point-in-time snapshots;
- explicit source vintages;
- `feature_available_at <= as_of_date` enforcement;
- parity or deliberate replacement of the full legacy feature universe.

It should not be introduced as a thin parallel feature spine with fewer
features than legacy gold.

## Verification

Main-worktree scan confirms no active `gold_v2` scratch files were added to the
MLflow critical path in this phase.

Focused tests were rerun after Phase 3 documentation:

```text
tests/unit/test_source_certification.py
tests/unit/test_feature_source_coverage.py
tests/unit/test_features_registry.py
```

## Next

Phase 3 is complete. Next is Phase 4: version the broad legacy
`gold/feature_spine` and matching feature matrix for MLflow experiments.
