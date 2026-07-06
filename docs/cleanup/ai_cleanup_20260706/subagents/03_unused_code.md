# Phase 2 Subagent 03 - Unused Code

## Scope

Read-only unused-code discovery using static references, import graphs, and Vulture where available. GraphRAG and AI-agent paths were excluded from cleanup findings.

No code edits, deletes, installs, AWS calls, S3 mutations, Terraform applies, or formatting tools were run.

## Evidence

- `.venv` has Vulture `2.16`.
- Knip is not installed/configured for `apps/terminal`; it was not installed during this phase.
- Frontend import graph: 99 TypeScript files, 60 imported, 1 production orphan candidate.
- Python import graph: 498 in-scope Python files, 141 source modules, 2 unimported module candidates, 1 parse error.
- Test import check: 159 tests checked, 0 missing in-scope `leviathan.*` import targets.

## High Confidence Findings

### Unused Python import

`jobs/batch/modis_ndvi_raw_to_bronze_task.py` imports `raw_modis_ndvi_key` but does not use it.

Vulture confidence: 90 percent.

Because this is a Batch entrypoint, remove only in a narrow cleanup phase with targeted tests.

### Unused frontend auth barrel

`apps/terminal/src/auth.ts` appears to be an unused auth barrel. In-scope imports go directly to `apps/terminal/src/auth/oidc`.

This file is a likely delete candidate after confirming no external import convention depends on it.

### Broken UNICA discovery script

`jobs/ingest/discover_unica_wayback.py` has a syntax error around an unmatched closing parenthesis. Static references are only itself and cleanup baseline documentation.

This needs a deliberate decision: fix it if the Wayback discovery workflow is still needed, or retire it if it is stale.

### Missing scratch helper references

The folders below are absent:

- `scratch/gain`
- `scratch/conab`
- `scratch/mpob`

Yet configs and ingest scripts reference helpers such as:

- `probe_gain_http.py`
- `build_manifest.py`
- `probe_conab_olalacms.py`

This is a reproducibility problem rather than a normal unused-code problem.

### Top-level scratch files look stale or ad hoc

Many `scratch/*.py` files have no references outside operational notes, and several are untracked.

Treat these as manual-review candidates. Do not bulk delete.

## Medium Confidence Findings

- `src/leviathan/common/glue_bootstrap.py` is unimported and overlaps with `jobs/glue/bootstrap.py`. Glue-related, so manual approval only.
- `src/leviathan/features/ddl.py` is unimported but appears documented as a CLI DDL generator. Manual approval only.
- `jobs/batch/wasde_scanned_task.py` contains `_collect_all_blocks` with no static references. Textract/Batch path, manual approval only.
- `jobs/utils/athena_utils.py` contains `ensure_catalog()` with no code references beyond docstring. It mutates catalog state, so do not remove or run without explicit approval.

## Low Confidence Findings

Vulture low-confidence results include many Pydantic fields, schema models, storage path helpers, and likely dynamic CLI entrypoints. Do not bulk-delete them.

Tracked logs and run artifacts are cleanup candidates, not code:

- `logs/*`
- `pytest_output.txt`
- `mypy_phase2.txt`
- `tf_apply.txt`
- `glue_log*.txt`
- `mlflow.db`

## Recommended Phase 3 Edits

1. Remove the unused `raw_modis_ndvi_key` import after Batch-owner approval.
2. Delete or route through `apps/terminal/src/auth.ts`; simplest likely edit is deleting the unused barrel.
3. Decide whether `jobs/ingest/discover_unica_wayback.py` should be fixed or retired.
4. Reconcile missing scratch helper references by restoring helpers, moving workflows into `jobs/`, or updating stale docs/config guidance.
5. Treat Glue, DDL, Batch, Terraform, and SQL entrypoints as manual-approval-only.

## Validation

- `rg "raw_modis_ndvi_key" jobs src tests`
- `rg "from .*auth|@/auth|src/auth" apps/terminal/src`
- `python -m py_compile jobs/ingest/discover_unica_wayback.py` if fixing.
- Targeted pytest for any touched ingestion or Batch task.
- Frontend `npm run typecheck && npm run test` if frontend auth files change.

