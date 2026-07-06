# Phase 2 Subagent 06 - Error Handling

## Scope

Read-only assessment of broad exception handling, defensive fallbacks, and error hiding. GraphRAG and AI-agent paths were excluded from cleanup recommendations.

No code edits, deletes, AWS calls, S3 mutations, Terraform applies, or formatting tools were run.

## Critical Assessment

The repo has a lot of defensive programming because it talks to external sources, S3, AWS Batch, Glue, Athena, Excel/PDF files, and web downloads. Many broad catches are justified. The real cleanup target is narrower: places where an error is swallowed and the job can still publish partial or misleading artifacts.

## High Confidence Findings

### CFTC silver can publish after failed bronze loads

`jobs/batch/cftc_cot_silver_task.py` logs failed bronze loads and continues to build/write silver.

Risk: a successful Batch exit can represent partial input coverage.

Recommended fix: accumulate failed keys and abort before writing unless a deliberate `--allow-partial` flag is added.

### ML platform restore hides rollback errors

`scripts/ops/restore_ml_platform.py` catches rollback failure and suppresses it.

Risk: operators lose the exact reason both restore and rollback failed.

Recommended fix: capture rollback exception details to stderr and/or structured JSON before re-raising the primary failure.

### Frontend SSE silently drops malformed JSON

`apps/terminal/src/api/sse.ts` catches JSON parse errors and returns false.

Risk: corrupted stream events disappear, making debugging and user-visible state confusing.

Recommended fix: emit an error event or terminate the stream with a clear parse failure path.

## Medium Confidence Findings

- `jobs/batch/modis_ndvi_bronze_to_silver_task.py` can proceed after partial read failures and exit success.
- Backfill orchestrators can continue Glue stages after Batch failures, even if they exit nonzero at the end.
- Terraform MLflow user-data uses broad `|| true` patterns. Some duplicate-admin tolerance is valid, but service/init failures should not be blanket-suppressed.

## Preserve These Patterns

Do not remove broad catches where they are handling:

- S3 existence checks;
- parser coercion for dirty source files;
- weather/raster optional fallback behavior;
- network retries with bounded attempts;
- compatibility paths;
- best-effort metadata/dead-letter writes.

## Recommended Phase 3 Edits

1. Make CFTC silver fail closed on input-read failures by default.
2. Make MODIS silver fail closed on input-read failures by default.
3. Add explicit partial-mode flags only where operationally justified.
4. Improve rollback error reporting in `restore_ml_platform.py`.
5. Make frontend SSE malformed JSON visible to the caller.
6. Review Terraform user-data suppressions with infrastructure owner approval.

## Validation

- Unit tests that simulate one failed bronze read and assert no output write happens.
- SSE test for malformed JSON path.
- Restore script dry-run or mocked subprocess tests.
- Terraform plan only after explicit approval.

