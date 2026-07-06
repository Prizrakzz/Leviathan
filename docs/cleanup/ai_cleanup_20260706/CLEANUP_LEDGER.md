# AI Cleanup Phase 2 Ledger

## Phase

Phase 2 - eight-lane research assessment for codebase cleanup.

## Date

2026-07-06

## Scope Guardrails

This phase was research and documentation only.

No application code was edited. No files were deleted. No S3, Glue, Batch, Athena, Terraform, or AWS mutating commands were run.

GraphRAG and AI-agent paths remain read-only and out of cleanup scope:

- `src/leviathan/graphrag/**`
- `configs/graphrag/**`
- GraphRAG jobs/tests/utilities
- `.claude/**`
- `.kiro/**`

## Reports Written

- `docs/cleanup/ai_cleanup_20260706/subagents/01_dedup_dry.md`
- `docs/cleanup/ai_cleanup_20260706/subagents/02_type_definitions.md`
- `docs/cleanup/ai_cleanup_20260706/subagents/03_unused_code.md`
- `docs/cleanup/ai_cleanup_20260706/subagents/04_circular_dependencies.md`
- `docs/cleanup/ai_cleanup_20260706/subagents/05_weak_types.md`
- `docs/cleanup/ai_cleanup_20260706/subagents/06_error_handling.md`
- `docs/cleanup/ai_cleanup_20260706/subagents/07_deprecated_legacy.md`
- `docs/cleanup/ai_cleanup_20260706/subagents/08_ai_slop_comments.md`

## Highest Priority Cleanup Candidates

These are high-confidence and should be considered first in Phase 3.

1. Remove or fix vacuous test assertions containing `or True`.
2. Strip `utm_source=chatgpt.com` from UNICA manifest URLs after URL equivalence check.
3. Remove the unused `raw_modis_ndvi_key` import from `jobs/batch/modis_ndvi_raw_to_bronze_task.py`.
4. Decide whether `apps/terminal/src/auth.ts` should be deleted or used as the auth barrel.
5. Fix or retire `jobs/ingest/discover_unica_wayback.py`, which has a parse error.
6. Remove the duplicate `bronze_fgis_key` definition in `src/leviathan/storage/paths.py`.
7. Centralize repeated S3 artifact IO helpers used across Batch tasks.
8. Centralize repeated model-ready/gold schema column constants.
9. Make CFTC and MODIS silver jobs fail closed instead of writing partial outputs after read failures.
10. Reconcile stale `scratch/gain/*` references in configs and ingest scripts.

## Manual Approval Only

Do not change these without explicit approval:

- destructive S3 utilities;
- Terraform state, plans, and modules;
- SQL DDL retirement;
- Glue/Athena catalog mutation utilities;
- Batch job definitions and task semantics;
- one-off migration scripts that submit jobs or delete data;
- any GraphRAG or AI-agent files.

## Recommended Phase 3 Shape

Phase 3 should not be a giant cleanup pass. It should make a small, safe set of high-confidence edits:

1. test hygiene and source-manifest hygiene;
2. one or two unused-code removals with targeted tests;
3. one duplicate path-helper cleanup;
4. no infrastructure mutation;
5. no GraphRAG changes.

## Validation Before Phase 3 Completion

Minimum checks for the first cleanup edit batch:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\unit\test_storage_metadata.py tests\unit\test_nasa_power_ingestion.py
rg "chatgpt\\.com|or True" configs tests
rg "bronze_fgis_key" src\leviathan\storage\paths.py
```

If frontend files are touched:

```powershell
cd apps\terminal
npm run typecheck
npm run test
npm run lint
```

If Batch task behavior is touched:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\unit -k "batch or silver or modis or cftc"
```

## Acceptance Criteria

Phase 2 is complete when:

- all eight subagent reports exist;
- the ledger summarizes priority, risk, and validation;
- no application code was changed by this phase;
- out-of-scope GraphRAG/AI files remain untouched by cleanup work.

