# AI Cleanup Phase 1 Baseline

Date: 2026-07-06

## Scope

This is the Phase 1 baseline for the AI codebase cleanup plan. It records the current repository state and quality-gate results before any cleanup, deletion, refactor, or tooling-driven rewrite.

No runtime code was intentionally changed during this phase.

## Read-Only Exclusions

Per user instruction, GraphRAG files and AI-agent work areas are read-only for cleanup. They may be counted and reported as part of the baseline, but cleanup subagents must not edit, format, delete, move, or auto-fix them.

Read-only paths:

```text
src/leviathan/graphrag/**
configs/graphrag/**
jobs/submit/submit_eval.py
jobs/utils/load_pg_evidence.py
jobs/utils/load_pg_numbers.py
jobs/submit/submit_batch_load_numbers_pg.py
jobs/batch/build_evidence_task.py
tests/unit/test_answer.py
tests/unit/test_citations.py
tests/unit/test_numbers_query.py
tests/unit/test_providers.py
tests/unit/test_serving_latency.py
tests/unit/test_register.py
tests/unit/test_store.py
tests/unit/test_display.py
tests/unit/test_emf.py
tests/unit/test_geo_routing.py
tests/unit/test_geography.py
tests/unit/test_hf_cache.py
tests/unit/test_suggest.py
tests/unit/test_ux56.py
.claude/**
.kiro/**
```

Currently modified or untracked read-only work observed:

```text
 M jobs/submit/submit_eval.py
 M src/leviathan/graphrag/answer.py
 M src/leviathan/graphrag/api_models.py
 M src/leviathan/graphrag/auth.py
 M src/leviathan/graphrag/citations.py
 M src/leviathan/graphrag/config_check.py
 M src/leviathan/graphrag/eval.py
 M src/leviathan/graphrag/extract.py
 M src/leviathan/graphrag/firing.py
 M src/leviathan/graphrag/numbers/agent.py
 M src/leviathan/graphrag/numbers/query.py
 M src/leviathan/graphrag/orchestrator.py
 M src/leviathan/graphrag/pgstore.py
 M src/leviathan/graphrag/planner.py
 M src/leviathan/graphrag/providers.py
 M src/leviathan/graphrag/rankers.py
 M src/leviathan/graphrag/register.py
 M src/leviathan/graphrag/server.py
 M src/leviathan/graphrag/silverleg.py
 M src/leviathan/graphrag/store.py
 M tests/unit/test_answer.py
 M tests/unit/test_citations.py
 M tests/unit/test_numbers_query.py
 M tests/unit/test_register.py
 M tests/unit/test_store.py
?? .kiro/
?? jobs/utils/load_pg_numbers.py
?? src/leviathan/graphrag/display.py
?? src/leviathan/graphrag/emf.py
?? src/leviathan/graphrag/geography.py
?? src/leviathan/graphrag/hf_cache.py
?? src/leviathan/graphrag/numbers/pgnumbers.py
?? src/leviathan/graphrag/pilot.py
?? tests/unit/test_display.py
?? tests/unit/test_emf.py
?? tests/unit/test_geo_routing.py
?? tests/unit/test_geography.py
?? tests/unit/test_hf_cache.py
?? tests/unit/test_serving_latency.py
?? tests/unit/test_suggest.py
?? tests/unit/test_ux56.py
```

Important interpretation:

The files above must be treated as active work owned outside this cleanup. Subagents may report observations about them as `observed_out_of_scope`, but must not implement recommendations there.

## Git State

Current branch state:

```text
main...origin/main [ahead 6, behind 72]
```

Current HEAD:

```text
ed901850f36804154dab3182a3ae2e5382a16b06
```

Recent commits:

```text
ed901850 feat(apps/terminal): Answer-view MVP — the trust loop (build-plan Phase 3)
698bca4a feat(apps/terminal): fold the frontend into the monorepo (was leviathan-terminal)
1381b3bc feat(graphrag): response_model= on terminal read routes (complete OpenAPI)
500da9fc feat(graphrag): terminal API surface (build-plan Phase 1)
95be0f65 chore(gitignore): keep docs/private/ (UI/UX + build plans) out of the repo
```

Working tree summary:

```text
modified entries: 71
deleted entries: 1
untracked status entries: 100
total porcelain status entries: 172
changed tracked files from git diff --name-only: 72
untracked files from git ls-files --others --exclude-standard: 474
```

Important interpretation:

The checkout is not safe for code cleanup yet. Phase 0 still needs to reconcile or preserve active work before subagents start editing. Phase 1 is still useful because it gives us the baseline failure/pass state.

## File Inventory

```text
repo_total          7870
src                  228
jobs                 167
tests                167
apps/terminal/src    102
infra                 57
sql                   60
configs              145
docs                  45
```

Observed unit test file count:

```text
tests/unit/*.py: 155
```

## Static Cleanup Signal Counts

These are raw `rg` counts. They are not findings by themselves.

```text
weak_types       908
broad_errors    1992
legacy_markers  1374
type_defs        230
```

Cleanup-eligible counts, excluding the read-only paths above:

```text
weak_types       590
broad_errors    1247
legacy_markers  1192
type_defs        165
```

Cleanup-eligible file inventory:

```text
src                 169
jobs                162
tests               153
apps/terminal/src   102
configs             145
docs                 48
sql                  60
infra                57
```

Definitions used:

- `weak_types`: `Any`, `unknown`, `as any`, `Record<string, unknown>`, `type: ignore`, broad casts, and similar weak-type markers.
- `broad_errors`: broad `try`/`except`/`catch`, fallback, ignore, and silent-handling language.
- `legacy_markers`: deprecated, legacy, fallback, temporary, shim, stale, obsolete, and similar markers.
- `type_defs`: Pydantic models, dataclasses, `TypedDict`, `Protocol`, TypeScript interfaces, and exported types.

## Python Quality Gates

### Ruff

Command:

```powershell
.\.venv\Scripts\python.exe -m ruff check src jobs tests
```

Result:

```text
failed
126 errors
123 fixable with --fix
```

Main failure types:

- Import ordering issues across `jobs/` and `tests/`.
- Invalid syntax in `jobs/ingest/discover_unica_wayback.py`.

Notable syntax error:

```text
jobs/ingest/discover_unica_wayback.py:305
invalid-syntax: Invalid assignment target
```

### Mypy

Command:

```powershell
.\.venv\Scripts\python.exe -m mypy src
```

Result:

```text
failed
656 errors in 96 files
checked 223 source files
```

Important environment/config note:

```text
pyproject.toml: [mypy]: python_version: Python 3.9 is not supported (must be 3.10 or higher)
```

Prominent failure families:

- Duplicate definition in `src/leviathan/storage/paths.py`:
  - `bronze_fgis_key` already defined.
- Missing annotations in GraphRAG, causal, feature computation, and dataset modules.
- `Any` return leakage.
- `object` used where numeric/string types are expected.
- Literal type mismatches in GraphRAG extraction schemas.
- Optional crop-calendar handling in weather computations.
- WASDE snapshot mapping and target-builder typing issues.

### Pytest

Command:

```powershell
.\.venv\Scripts\python.exe -m pytest tests
```

Result:

```text
failed during collection
1783 items collected before interruption
2 collection errors
```

Failures:

```text
tests/unit/test_providers.py
ModuleNotFoundError: No module named 'anthropic'

tests/unit/test_serving_latency.py
ModuleNotFoundError: No module named 'anthropic'
```

Warnings:

- FastAPI `on_event` deprecation warnings from `src/leviathan/graphrag/server.py`.

Interpretation:

Python test baseline is blocked by missing `anthropic` in the active venv, not by test assertions. This should be fixed as an environment/dependency issue before using full `pytest tests` as a cleanup regression gate.

## Terminal App Quality Gates

Working directory:

```text
apps/terminal
```

### TypeScript Typecheck

Command:

```powershell
npm run typecheck
```

Result:

```text
passed
```

### ESLint

Command:

```powershell
npm run lint
```

Result:

```text
passed
```

### Vitest

Command:

```powershell
npm run test
```

Result:

```text
passed
23 test files passed
80 tests passed
duration: 155.20s
```

### Production Build

Command:

```powershell
npm run build
```

Result:

```text
passed
vite build completed in 1m 22s
```

## Cleanup Tool Availability

Python venv:

```text
vulture installed: 2.16
deptry missing
grimp missing
pydeps missing
```

Terminal app:

```text
knip not installed as a project dependency
madge not installed as a project dependency
jscpd not installed as a project dependency
```

Recommendation:

Add cleanup tooling in a dedicated tooling commit if we want persistent tool support. Do not mix tool installation with cleanup edits.

## Baseline Assessment

Frontend:

- Healthy at baseline.
- Typecheck, lint, tests, and build all pass.
- Cleanup can safely use `npm run ci` and `npm run build` as regression gates once worktree ownership is settled.

Python:

- Not clean at baseline.
- Full tests are blocked by missing `anthropic`.
- Ruff is blocked by import ordering and one syntax error.
- Mypy has a large existing error surface.

Repo hygiene:

- Cleanup should not proceed with implementation until the dirty/behind state is resolved.
- Many modified/untracked files appear to be active GraphRAG/frontend/platform work.
- Any automated cleanup tool will be dangerous unless scoped and reviewed.
- GraphRAG and AI-agent files are explicitly read-only. Cleanup quality gates may fail because of them, but subagents must not fix them.
- Cleanup-eligible static counts are still large even after exclusions, so the cleanup remains valuable without touching GraphRAG.

## Phase 1 Acceptance Criteria

Status:

```text
complete
```

Criteria:

- Baseline folder exists.
- Git state recorded.
- File inventory recorded.
- Static signal counts recorded.
- Python quality gates run and failures recorded.
- Terminal quality gates run and pass.
- Tool availability recorded.
- No cleanup edits performed.

## Required Next Step

Before Phase 2 subagent research, complete Phase 0 cleanup-readiness properly:

1. Preserve or merge the current dirty work.
2. Pull/reconcile `origin/main`.
3. Decide whether GraphRAG is in scope or read-only.
4. Create a dedicated cleanup branch or worktree.
5. Fix the baseline Python dependency issue if full tests must be a hard gate:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,serve]"
```

Do not run broad cleanup or deletion tools against this dirty checkout.

Phase 2 subagent prompts must include the read-only exclusion list from this baseline. Any finding inside GraphRAG or AI-agent paths must be marked `observed_out_of_scope`.
