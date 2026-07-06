# Phase 2 Subagent 02 - Type Definitions

## Scope

Read-only assessment of shared type definitions and duplicated schema constants. GraphRAG and AI-agent files were excluded from cleanup recommendations.

No code edits, deletes, AWS calls, S3 mutations, Terraform applies, or formatting tools were run.

## Critical Assessment

The repo already has useful local schema definitions, but the ML/gold/model-ready path has several duplicated column lists and dict shapes. This is dangerous because the pipeline is versioned by manifests and S3 paths, while many contracts are still enforced by repeated lists in separate modules and tests.

The best cleanup is to centralize stable schema constants without changing the data contract.

## High Confidence Findings

### Model-ready column shapes are duplicated

Related column constants and output dict shapes appear across:

- `src/leviathan/model_datasets/baselines.py`
- `src/leviathan/model_datasets/builder.py`
- `src/leviathan/model_datasets/psd_target_builder.py`
- `src/leviathan/model_datasets/psd_model_ready.py`
- `src/leviathan/model_datasets/wasde_snapshot_targets.py`

Tests also assert exact column order in:

- `tests/unit/test_model_datasets_psd_targets.py`
- `tests/unit/test_wasde_snapshot_targets.py`

Risk: a schema change can pass in one builder and fail or silently drift in another.

### `SPINE_COLUMNS` is duplicated

The same feature-spine column definition appears in:

- `src/leviathan/features/spine.py`
- `jobs/batch/feature_catalog_task.py`

Risk: the feature catalog can diverge from the spine contract.

### Baseline/trend helpers are repeated

Helpers like `_finite`, `_pct_deviation`, `_linear_prediction`, and anomaly baseline output columns appear in:

- `src/leviathan/model_datasets/baselines.py`
- `src/leviathan/model_datasets/psd_target_builder.py`

Risk: target anomaly definitions can drift between production-anomaly and PSD-anomaly builders.

## Medium Confidence Findings

- `jobs/batch/build_model_ready_datasets.py` repeats output-record dict shapes.
- `BatchJobRecord` exists in `src/leviathan/common/batch_submit.py`, but submitters still create loosely typed records.
- `jobs/utils/athena_utils.py` would benefit from an `AthenaRow = dict[str, str]` alias rather than a rigid `TypedDict`.

## Do Not Change Yet

- Frontend generated `apps/terminal/src/api/types.gen.ts`.
- SSE/frontend schema types that depend on backend GraphRAG models.
- WASDE dataclasses that encode different concepts even if fields look similar.

## Recommended Phase 3 Edits

1. Add `src/leviathan/model_datasets/schema_columns.py`.
2. Move shared model-ready target/matrix column groups there.
3. Preserve existing exported names as aliases or compositions to avoid wide churn.
4. Import `SPINE_COLUMNS` from `src/leviathan/features/spine.py` inside `jobs/batch/feature_catalog_task.py`.
5. Consider `TypedDict` types for model-ready output records only after column constants are centralized.

## Validation

- `python -m pytest tests/unit/test_model_datasets_psd_targets.py`
- `python -m pytest tests/unit/test_wasde_snapshot_targets.py`
- `python -m pytest tests/unit/test_features_spine.py` if present.
- Any exact-schema tests for feature catalog/model-ready artifacts.

