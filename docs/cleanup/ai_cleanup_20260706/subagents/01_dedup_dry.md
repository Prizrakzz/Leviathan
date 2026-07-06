# Phase 2 Subagent 01 - Deduplication And DRY

## Scope

Read-only assessment of duplicate code and consolidation opportunities across the cleanup-eligible codebase. GraphRAG and AI-agent paths were treated as out of scope.

No code edits, deletes, AWS calls, S3 mutations, Terraform applies, or formatting tools were run.

## Critical Assessment

The codebase has several repeated implementation patterns that are not dangerous by themselves, but now create drift risk because they appear in Batch tasks, source submitters, storage helpers, and versioned gold/model-ready jobs. The highest-value cleanup is not broad abstraction. It is extracting a few narrow, proven helpers around S3 artifact IO, Batch submission, gold/model-ready versioned artifact IO, and Athena execution.

## High Confidence Findings

### Repeated S3 existence/read/write helpers

Existing helper surface:

- `src/leviathan/storage/s3.py`

Repeated local helpers appear in:

- `jobs/batch/conab_coffee_silver_task.py`
- `jobs/batch/fnc_colombia_silver_task.py`
- `jobs/batch/cftc_cot_bronze_task.py`
- multiple other Batch tasks with private `_target_exists`, `_bronze_exists`, `_key_exists`, `_exists`, `_write_parquet`, `_write`, and `_upload_parquet` functions.

Risk: each task can diverge on 404 handling, overwrite behavior, local-root support, and partial-write semantics.

### Batch submitter loops are duplicated

Existing helper:

- `src/leviathan/common/batch_submit.py`

Submitters still hand-roll repeated command loops:

- `jobs/submit/submit_batch_backfill_wasde.py`
- `jobs/submit/submit_batch_wap_backfill.py`
- `jobs/submit/submit_batch_gain_backfill.py`

Risk: inconsistent dry-run behavior, job-name construction, parameter serialization, and AWS Batch error reporting.

### Duplicate storage path helper

`bronze_fgis_key` appears twice in:

- `src/leviathan/storage/paths.py`

Risk: future edits can update one copy and leave the other stale.

### Versioned gold/model-ready jobs repeat artifact IO

Repeated helpers such as `_read_bytes`, `_write_bytes`, `_target_exists`, `_git_sha`, and `_bool_arg` appear in:

- `jobs/batch/build_model_ready_datasets.py`
- `jobs/batch/feature_spine_task.py`
- `jobs/batch/feature_spine_finalize_task.py`
- `jobs/batch/feature_catalog_task.py`
- `jobs/batch/feature_set_task.py`

Risk: version immutability, skip-existing behavior, and manifest behavior can drift between gold/model-ready jobs.

## Medium Confidence Findings

- Athena execution is split between `jobs/utils/athena_utils.py` and private `_run_query` logic in `jobs/run_athena_ddl.py`. `generate_silver_ddls.py` imports private helper behavior.
- Config normalization helpers repeat across `src/leviathan/features/feature_sets.py`, `src/leviathan/model_datasets/psd_targets.py`, and `src/leviathan/model_datasets/targets.py`.
- Manifest IO patterns repeat in ingestion scripts such as WASDE, WAP, and SAGIS fetchers.
- Frontend suggestion-chip styling is duplicated between answer empty state and suggestion-chip components.

## Recommended Phase 3 Edits

1. Add a small shared storage artifact module, for example `src/leviathan/storage/artifact_io.py`, with:
   - `object_exists`
   - `read_bytes`
   - `write_bytes`
   - `read_parquet`
   - `parquet_bytes`
   - `write_parquet`
2. Extend `src/leviathan/common/batch_submit.py` with an override-command submit helper for submitter scripts.
3. Remove the duplicate `bronze_fgis_key` definition and add a path-module duplicate guard test.
4. Add shared config/value helpers only after a small call-site migration proves the shape.
5. Centralize non-GraphRAG Athena query execution.
6. Extract a small frontend chip component only if it reduces duplicated style code without changing UX.

## Manual Approval Required

- Batch task IO behavior changes.
- Any overwrite/skip-existing behavior change.
- Any Terraform, Glue, or DDL-adjacent refactor.

## Validation

- `python -m pytest tests/unit/test_storage_paths.py`
- `python -m pytest tests/unit/test_batch_submit.py`
- Targeted Batch task tests for any migrated tasks.
- Frontend `npm run typecheck`, `npm run test`, and `npm run lint` if UI files are touched.

