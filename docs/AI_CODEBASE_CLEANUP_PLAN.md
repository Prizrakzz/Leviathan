# AI Codebase Cleanup Plan

Date: 2026-07-06

## Executive Summary

This plan defines a staged, agent-assisted cleanup of the Leviathan codebase. The goal is not to make the code smaller for its own sake. The goal is to make the project easier to reason about, safer to change, cheaper to operate, and stricter about correctness without breaking the active ML/MLOps, data lake, GraphRAG, and terminal-app work.

The cleanup will use eight focused subagents, one per cleanup dimension:

1. Deduplication and DRY consolidation.
2. Type definition consolidation.
3. Unused code discovery and removal.
4. Circular dependency detection and untangling.
5. Weak type removal.
6. Defensive error-handling cleanup.
7. Deprecated, legacy, fallback, and stale-path removal.
8. AI slop, stubs, larp, and comment cleanup.

Each subagent must first research and write a critical assessment. Only high-confidence recommendations should be implemented, and only after the baseline gates pass. Risky or ambiguous removals stay as recommendations until a human approves them.

## Current Repo Observations

Observed locally:

- Workspace: `C:\Users\User\Desktop\Leviathan`
- Repo state at plan creation: `main...origin/main [ahead 6, behind 72]`
- The worktree is dirty with many modified/untracked files across:
  - `src/leviathan/graphrag/`
  - `apps/terminal/`
  - `infra/terraform/`
  - `jobs/`
  - `configs/`
  - `sql/athena/ddl/`
  - `docs/`
  - `data/`
  - `scratch/`
- Approximate tracked/untracked file surface from `rg --files`: `7869` files.
- Main Python package: `src/leviathan/`
- Terminal app: `apps/terminal/`
- Unit tests: `tests/unit/`, observed `155` unit test files.
- Python tooling:
  - `pytest`
  - `mypy` configured in `pyproject.toml`
  - `ruff` currently configured only for import sorting
- TypeScript tooling:
  - `npm run typecheck`
  - `npm run lint`
  - `npm run test`
  - `npm run build`
- Important cleanup risk: current work overlaps with active GraphRAG/frontend changes. Cleanup must not casually rewrite or delete active work.

## Non-Negotiable Safety Rules

- Do not start cleanup from the currently dirty, behind worktree.
- Do not delete code merely because a static tool flags it.
- Do not remove data-pipeline entrypoints, Batch jobs, Terraform modules, SQL DDLs, or scripts without proving they are not referenced by:
  - tests,
  - job definitions,
  - Terraform,
  - Dockerfiles,
  - docs/runbooks,
  - submitters,
  - S3/Athena/Glue naming contracts,
  - frontend imports,
  - CLI users.
- Do not edit GraphRAG files while another agent is actively changing them unless the user explicitly authorizes it.
- Do not mix behavior changes with mechanical cleanup in the same commit.
- Do not remove defensive error handling if it protects external boundaries:
  - S3/Athena/Glue/Batch APIs,
  - network calls,
  - filesystem reads,
  - user/API input,
  - external data parsing,
  - model/data-contract validation,
  - subprocess boundaries.
- Do not remove comments that explain source assumptions, unit conversions, leakage policy, point-in-time semantics, or operational hazards.
- Every deletion must be recoverable through git.
- Every phase ends with a short report, validation results, and a commit.

## Success Criteria

The cleanup is successful when:

- The repo has a clean, current branch with no accidental conflict with active work.
- Python and TypeScript validation passes.
- Removed code is backed by evidence, not vibes.
- Shared types/config models are consolidated where it reduces complexity.
- Circular imports are either removed or documented with a deliberate boundary.
- Weak types are reduced without fake type assertions.
- Broad `except`, silent fallback, and error-hiding patterns are reduced.
- Legacy/fallback/stale code paths are removed or explicitly quarantined.
- Comments explain durable behavior, not implementation history.
- The codebase is easier to navigate for a new engineer.

## Target Branch Strategy

Use a dedicated branch:

```powershell
git fetch origin
git switch main
git pull --ff-only origin main
git switch -c codex/ai-codebase-cleanup
```

If the current worktree cannot be fast-forwarded safely, stop and preserve it first:

```powershell
git status --short --branch
git branch codex/pre-cleanup-backup
```

If active GraphRAG/frontend work is still dirty, cleanup should happen in a separate clean clone/worktree after the user decides what to preserve.

## Subagent Operating Model

All eight subagents should run research in parallel after Phase 1 baseline. They may read the whole repo but must write separate reports before edits.

Reports should be stored under:

```text
docs/cleanup/ai_cleanup_YYYYMMDD/subagents/
```

Recommended report files:

```text
01_dedup_dry.md
02_type_definitions.md
03_unused_code.md
04_circular_dependencies.md
05_weak_types.md
06_error_handling.md
07_deprecated_legacy.md
08_ai_slop_comments.md
```

Each report must include:

- Scope inspected.
- Tools/commands used.
- Findings grouped by confidence.
- Proposed edits.
- Risk level per edit.
- Files likely affected.
- Tests required.
- Recommendations explicitly deferred.

## Subagent Charters

### Subagent 1: Deduplicate And DRY Consolidation

Objective:

Find repeated logic and consolidate only where it reduces complexity and preserves local clarity.

Primary areas:

- `jobs/batch/`
- `jobs/submit/`
- `jobs/utils/`
- `src/leviathan/storage/`
- `src/leviathan/features/`
- `src/leviathan/model_datasets/`
- `src/leviathan/training/`
- `apps/terminal/src/api/`
- `apps/terminal/src/views/`

Tools:

```powershell
rg -n "put_object|list_objects_v2|start_query_execution|ThreadPoolExecutor|argparse|parse_args|dataset_version|manifest" src jobs tests
```

Optional tools:

- `jscpd` for duplicate TypeScript/Python detection.
- `ruff` rules later expanded for simplification.

High-confidence edit examples:

- Consolidate repeated S3 write/read helpers into `src/leviathan/storage/`.
- Consolidate repeated Batch submitter parameter handling.
- Consolidate repeated dataset-version path builders.
- Consolidate repeated Athena polling helpers.

Do not do:

- Abstract two similar functions that serve different source-specific semantics.
- Introduce a generic framework around every ETL.
- Hide source-specific validation behind vague helpers.

Acceptance:

- Fewer repeated helper implementations.
- No behavior drift in paths, S3 keys, or schemas.
- Tests cover each moved helper.

### Subagent 2: Type Definition Consolidation

Objective:

Find duplicate or near-duplicate type definitions and consolidate into shared models only where ownership is clear.

Primary areas:

- `src/leviathan/schemas/`
- `src/leviathan/common/`
- `src/leviathan/training/`
- `src/leviathan/model_datasets/`
- `src/leviathan/graphrag/api_models.py`
- `apps/terminal/src/api/`
- `apps/terminal/src/api/types.gen.ts`
- `apps/terminal/src/api/schema.ts`

Tools:

```powershell
rg -n "class .*BaseModel|TypedDict|Protocol|dataclass|type .* =|interface |export type|export interface" src apps/terminal/src tests
```

High-confidence edit examples:

- Move repeated dataset manifest shapes into a single Python module.
- Align generated frontend API types with backend response models.
- Use `TypedDict`, `Protocol`, or Pydantic models where dictionaries are passed across module boundaries.

Do not do:

- Hand-edit generated OpenAPI types unless generation is broken.
- Over-centralize source-specific schemas into one mega-schema file.
- Replace clear local dataclasses with generic dictionaries.

Acceptance:

- Shared types are easier to import.
- Type ownership is clear.
- No circular type imports are introduced.

### Subagent 3: Unused Code Discovery And Removal

Objective:

Use static tools and cross-reference checks to identify unused code. Remove only high-confidence dead code.

Tools:

TypeScript:

```powershell
cd apps/terminal
npm exec knip -- --production
npm exec knip
npm run typecheck
npm run test
```

Python:

```powershell
.\.venv\Scripts\python.exe -m pip install vulture deptry
.\.venv\Scripts\vulture.exe src jobs tests --min-confidence 90
.\.venv\Scripts\deptry.exe .
```

Repo search:

```powershell
rg -n "module_name_or_symbol" .
```

High-confidence removal examples:

- Unreferenced local scratch scripts after confirming they are not documented runbooks.
- Unused React components not imported anywhere and not referenced by routes/stories/tests.
- Dead helper functions with no CLI, test, or docs references.

Do not remove:

- Batch entrypoints referenced only by Terraform/job definitions.
- Glue scripts referenced by infrastructure.
- DDLs that are still live Glue/Athena contracts.
- Generated files required by build.
- Scratch files unless explicitly confirmed stale.

Acceptance:

- Deletions have evidence in the report.
- Tests/build pass after deletion.
- No operational entrypoint is removed accidentally.

### Subagent 4: Circular Dependency Detection

Objective:

Detect circular imports/dependencies and untangle them by clarifying boundaries.

Tools:

TypeScript:

```powershell
cd apps/terminal
npm exec madge -- --circular src
```

Python:

```powershell
.\.venv\Scripts\python.exe -m pip install pydeps grimp
.\.venv\Scripts\pydeps.exe src\leviathan --show-deps --noshow
```

Fallback search:

```powershell
rg -n "from leviathan\\.|import leviathan\\." src jobs tests
```

Likely boundary principles:

- `storage` must not depend on `features`, `training`, or GraphRAG.
- `features` may depend on `storage/common/schemas`, not `training`.
- `training` may depend on `features/model_datasets`, not Batch submitters.
- `jobs` are entrypoints and should depend inward, not be imported by core code.
- Frontend `api` must not depend on view components.

High-confidence edit examples:

- Move shared constants to `common`.
- Move type-only imports behind `if TYPE_CHECKING`.
- Split modules that mix CLI side effects with library functions.

Do not do:

- Solve cycles by dynamic imports everywhere.
- Hide cycles with broad import suppression.

Acceptance:

- Madge reports no TS cycles, or accepted cycles are documented.
- Python circular imports are removed or isolated.
- Imports become more directional.

### Subagent 5: Weak Type Removal

Objective:

Reduce weak types such as `Any`, `unknown`, untyped dictionaries, untyped callables, and broad casts.

Tools:

```powershell
rg -n "\\bAny\\b|typing\\.Any|dict\\[str, Any\\]|Dict\\[str, Any\\]|# type: ignore|cast\\(|object\\)|unknown\\b|as any|Record<string, unknown>|Record<string, any>" src jobs tests apps/terminal/src
.\.venv\Scripts\python.exe -m mypy src
cd apps/terminal; npm run typecheck
```

High-confidence edit examples:

- Replace `dict[str, Any]` at module boundaries with `TypedDict` or Pydantic models.
- Replace TypeScript `unknown` response payloads with generated OpenAPI types.
- Replace callback `Callable[..., Any]` with specific protocols.

Do not do:

- Add unsafe `as Foo` casts to silence errors.
- Replace `Any` with `object` without narrowing.
- Pretend external JSON is strongly typed before validation.

Acceptance:

- Weak type count decreases.
- Mypy/typecheck still pass.
- Runtime validation remains at untrusted input boundaries.

### Subagent 6: Error Handling And Defensive Programming Cleanup

Objective:

Remove error hiding while preserving real boundary protection.

Tools:

```powershell
rg -n "except Exception|except BaseException|except:|try:|catch \\(|console\\.error|pass\\s*$|return \\[\\]|return \\{\\}|fallback|silently|best effort|ignore" src jobs tests apps/terminal/src
```

Keep defensive handling for:

- AWS API throttling/retries.
- External HTML/PDF/Excel parsing.
- Optional files or missing source documents.
- User/API input validation.
- Batch worker failure aggregation.
- Model/data validation boundaries.

High-confidence edit examples:

- Replace silent `except Exception: return []` with typed exception, logged failure, or explicit result object.
- Remove redundant `try/except` around deterministic local code.
- Replace fallback defaults with validation errors where data correctness matters.

Do not do:

- Remove retries from network/AWS calls without replacing them with explicit policy.
- Make batch jobs fail on one bad source row if dead-letter behavior is intended.

Acceptance:

- Fewer broad/silent exceptions.
- Errors become observable.
- Tests assert intended failure behavior.

### Subagent 7: Deprecated, Legacy, Fallback, And Stale Code

Objective:

Find old paths, replaced systems, deprecated configs, fallback modes, and stale scripts. Remove only after proving the replacement is active.

Tools:

```powershell
rg -n "deprecated|legacy|fallback|old_|v1|v2|TODO remove|remove later|temporary|compat|backcompat|shim|obsolete|stale|unused|not used|superseded" src jobs configs docs sql infra apps/terminal/src
```

High-confidence edit examples:

- Remove old unused CLI flags after submitters and docs are updated.
- Remove stale frontend components replaced by new routed views.
- Remove outdated DDL files only after live Glue/Athena drift report confirms they are not used.

Do not remove without approval:

- Legacy data readers that preserve old dataset compatibility.
- DDLs for still-existing external tables.
- Migration scripts.
- Anything related to active GraphRAG work while another agent owns it.

Acceptance:

- Legacy surface is smaller.
- Remaining legacy paths are clearly named and documented.
- No active pipeline loses compatibility unexpectedly.

### Subagent 8: AI Slop, Stubs, Larp, And Comments

Objective:

Remove noise and make comments useful for future engineers.

Tools:

```powershell
rg -n "AI|LLM|stub|placeholder|dummy|fake|for now|quick hack|temporary|TODO|FIXME|NOTE:|new version|old version|phase|we now|previous|larp|magic|obviously|just|basically" src jobs configs docs apps/terminal/src tests
```

Keep comments that explain:

- Point-in-time correctness.
- Leakage prevention.
- Source-specific semantics.
- Unit conversions.
- AWS cost hazards.
- Non-obvious algorithmic choices.
- Operational safety.

Remove or rewrite comments that:

- Narrate recent history.
- Describe obvious code.
- Say something was temporary but it is now production.
- Contain bravado, filler, or unclear AI-generated prose.

Acceptance:

- Comments are fewer and better.
- New engineer comprehension improves.
- No source assumptions disappear.

## Phased Execution Roadmap

## Phase 0: Freeze, Sync, And Scope Control

Objective:

Create a clean, safe starting point and prevent cleanup from colliding with active work.

Tasks:

1. Inspect current dirty worktree.
2. Identify active owner areas:
   - GraphRAG.
   - Terminal frontend.
   - Terraform/cost guardrails.
   - ML/model-dataset work.
3. Back up current state if needed.
4. Fast-forward `main` only when safe.
5. Create `codex/ai-codebase-cleanup`.
6. Decide whether GraphRAG is in scope or read-only for this cleanup.

Likely files affected:

- None, unless writing a phase report.

Commands:

```powershell
git status --short --branch
git fetch origin
git log --oneline --left-right --cherry-pick main...origin/main
git branch codex/pre-cleanup-backup
```

Risks:

- Cleaning on top of unmerged work could delete or rewrite another agent's changes.

Validation:

- Clean branch exists.
- Scope exclusions are documented.

Acceptance criteria:

- A clean cleanup branch is ready.
- Dirty work is preserved.
- Active code ownership is clear.

Reversibility:

- Safe and reversible.

Explicitly do not:

- Do not edit code.
- Do not delete files.
- Do not pull over dirty work without a backup.

## Phase 1: Baseline Inventory And Quality Gates

Objective:

Measure the current state before cleanup so regressions are obvious.

Tasks:

1. Count files by language and top-level area.
2. Capture baseline Python tests.
3. Capture baseline TypeScript checks.
4. Capture baseline mypy/ruff status.
5. Capture baseline import/dependency graphs.
6. Capture baseline weak-type and broad-exception counts.
7. Capture baseline duplicate/dead-code reports without edits.

Files likely affected:

```text
docs/cleanup/ai_cleanup_YYYYMMDD/BASELINE.md
docs/cleanup/ai_cleanup_YYYYMMDD/metrics.json
```

Commands:

```powershell
rg --files | Measure-Object
.\.venv\Scripts\python.exe -m pytest tests
.\.venv\Scripts\python.exe -m mypy src
.\.venv\Scripts\python.exe -m ruff check src jobs tests
cd apps/terminal
npm run typecheck
npm run lint
npm run test
npm run build
```

Optional install-only tooling:

```powershell
cd apps/terminal
npm install --save-dev knip madge jscpd

cd C:\Users\User\Desktop\Leviathan
.\.venv\Scripts\python.exe -m pip install vulture deptry grimp pydeps
```

Risks:

- Existing failures may be unrelated to cleanup.
- Installing tools changes lockfiles; do that in a dedicated tooling commit.

Validation:

- Baseline report records pass/fail state honestly.
- Tool additions are committed separately if added.

Acceptance criteria:

- We know what is already broken before cleanup.
- We have repeatable commands for every later phase.

Reversibility:

- Safe and reversible.

Explicitly do not:

- Do not remove unused code yet.
- Do not fix unrelated test failures unless they block all later validation.

## Phase 2: Parallel Subagent Research

Objective:

Run the eight subagent investigations in parallel and produce evidence-backed recommendations.

Tasks:

1. Launch subagents with the charters above.
2. Each subagent writes a report.
3. Each subagent categorizes findings:
   - High confidence.
   - Medium confidence.
   - Needs owner decision.
   - Do not touch.
4. Main agent merges reports into a cleanup ledger.

Files likely affected:

```text
docs/cleanup/ai_cleanup_YYYYMMDD/subagents/*.md
docs/cleanup/ai_cleanup_YYYYMMDD/CLEANUP_LEDGER.md
```

Risks:

- Subagents may disagree.
- Static tools may flag false positives.

Validation:

- Every proposed edit has references and confidence.
- No proposed deletion relies on one tool alone.

Acceptance criteria:

- Cleanup ledger exists.
- High-confidence edits are ranked by risk and value.

Reversibility:

- Safe and reversible.

Explicitly do not:

- Do not implement during research.

## Phase 3: Cleanup Ledger Review And Batch Planning

Objective:

Turn findings into small, reviewable edit batches.

Tasks:

1. Group recommendations by blast radius:
   - Mechanical no-risk.
   - Single-module cleanup.
   - Shared helper/type changes.
   - Behavioral cleanup.
   - Deletion/deprecation.
2. Define one commit per logical change.
3. Define test commands per commit.
4. Mark manual-approval-only items.

Files likely affected:

```text
docs/cleanup/ai_cleanup_YYYYMMDD/CLEANUP_LEDGER.md
```

Risks:

- Combining too many changes makes regressions hard to isolate.

Validation:

- Each proposed commit has a rollback path.

Acceptance criteria:

- Implementation sequence is explicit.
- User can approve/reject risky groups.

Reversibility:

- Safe and reversible.

Explicitly do not:

- Do not start large refactors.

## Phase 4: Mechanical And Low-Risk Cleanup

Objective:

Remove obvious noise with minimal behavior risk.

Candidate tasks:

- Delete confirmed unreferenced scratch files.
- Remove unused frontend components with no imports/routes/tests/stories.
- Remove stale generated artifacts that are intentionally ignored and reproducible.
- Remove obvious AI-slop comments.
- Fix import ordering.
- Remove duplicate comments.

Files likely affected:

- `scratch/`
- `apps/terminal/src/`
- `docs/`
- low-risk tests.

Risks:

- Scratch scripts may be informal runbooks.
- Frontend components may be referenced dynamically.

Validation:

```powershell
.\.venv\Scripts\python.exe -m pytest tests
cd apps/terminal
npm run ci
```

Acceptance criteria:

- No behavior changes.
- Removed files are proven unused.

Reversibility:

- Safe and reversible through git.

Explicitly do not:

- Do not delete Batch/Glue/Terraform/DDL entrypoints in this phase.

## Phase 5: Shared Helper And DRY Consolidation

Objective:

Consolidate repeated logic where doing so reduces real complexity.

Candidate tasks:

- S3 path helpers.
- S3 guarded list/write helpers.
- Athena query/poll helpers.
- Batch parameter parsing helpers.
- Dataset manifest writers.
- Local/S3 artifact writers.

Files likely affected:

- `src/leviathan/storage/`
- `src/leviathan/common/`
- `jobs/batch/`
- `jobs/utils/`
- `jobs/submit/`
- tests under `tests/unit/`.

Risks:

- Centralizing source-specific behavior can accidentally erase semantics.

Validation:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_storage*.py tests/unit/test_*batch*.py tests/unit/test_*dataset*.py
.\.venv\Scripts\python.exe -m pytest tests
```

Acceptance criteria:

- Duplicate helper implementations decrease.
- Source-specific behavior remains explicit.
- No S3 path changes unless tests assert them.

Reversibility:

- Reversible but moderate risk.

Explicitly do not:

- Do not create a mega framework for all ETLs.

## Phase 6: Type Consolidation And Weak-Type Reduction

Objective:

Improve type clarity after helper boundaries are cleaner.

Candidate tasks:

- Shared dataset manifest models.
- Shared training-run metadata models.
- Shared Athena query result row shapes.
- Shared frontend API response types.
- Replace weak `Any`/`unknown` at stable boundaries.

Files likely affected:

- `src/leviathan/schemas/`
- `src/leviathan/common/`
- `src/leviathan/training/`
- `src/leviathan/model_datasets/`
- `apps/terminal/src/api/`

Risks:

- Over-typing external JSON can create false confidence.
- Type-only imports can create runtime cycles if done carelessly.

Validation:

```powershell
.\.venv\Scripts\python.exe -m mypy src
.\.venv\Scripts\python.exe -m pytest tests
cd apps/terminal
npm run typecheck
npm run test
```

Acceptance criteria:

- Weak type count decreases.
- Runtime validation remains for untrusted input.
- Type imports do not introduce cycles.

Reversibility:

- Reversible, moderate risk.

Explicitly do not:

- Do not replace types with unsafe casts.

## Phase 7: Circular Dependency Untangling

Objective:

Make module dependencies directional and easier to reason about.

Candidate tasks:

- Move shared constants/types into lower-level modules.
- Split CLI modules from library modules.
- Convert runtime imports to type-only imports where appropriate.
- Remove frontend cross-layer imports.

Files likely affected:

- `src/leviathan/common/`
- `src/leviathan/storage/`
- `src/leviathan/features/`
- `src/leviathan/training/`
- `src/leviathan/model_datasets/`
- `apps/terminal/src/`

Risks:

- Import changes can break Batch entrypoints only at runtime.

Validation:

```powershell
cd apps/terminal
npm exec madge -- --circular src
npm run ci

cd C:\Users\User\Desktop\Leviathan
.\.venv\Scripts\python.exe -m pytest tests
```

Acceptance criteria:

- Known cycles removed or explicitly documented.
- Entry-point imports still work.

Reversibility:

- Reversible, moderate risk.

Explicitly do not:

- Do not use lazy imports as a blanket workaround.

## Phase 8: Error Handling Cleanup

Objective:

Remove error hiding and make failures intentional.

Candidate tasks:

- Replace silent fallback with explicit validation errors.
- Add structured failure results where batch workers aggregate failures.
- Narrow broad exception handlers.
- Remove redundant local `try/except`.
- Ensure external boundary errors are logged with useful context.

Files likely affected:

- `jobs/batch/`
- `jobs/utils/`
- `src/leviathan/storage/`
- `src/leviathan/transforms/`
- `src/leviathan/features/`
- frontend API/SSE handlers.

Risks:

- Some broad handlers may protect messy external sources.
- Making failures louder may expose existing bad records.

Validation:

```powershell
.\.venv\Scripts\python.exe -m pytest tests
cd apps/terminal
npm run ci
```

Acceptance criteria:

- Broad/silent catches decrease.
- Expected bad input paths are still handled.
- Unexpected errors are no longer swallowed.

Reversibility:

- Reversible, moderate to high risk depending on touched modules.

Explicitly do not:

- Do not remove retries/throttling handling for AWS/network calls.

## Phase 9: Legacy And Fallback Removal

Objective:

Remove old or fallback code paths only after replacements are verified.

Candidate tasks:

- Retire stale model-ready scripts superseded by current PSD/WASDE snapshot tooling.
- Retire stale DDLs only after Glue/Athena drift report confirms replacement.
- Remove old frontend panes/routes after route map confirms no usage.
- Remove deprecated config keys after loaders reject or migrate them.

Files likely affected:

- `configs/`
- `jobs/`
- `sql/athena/ddl/`
- `src/leviathan/model_datasets/`
- `src/leviathan/training/`
- `apps/terminal/src/`

Risks:

- Legacy code may still be used for reproducibility.
- Removing compatibility too early can break old experiment versions.

Validation:

```powershell
.\.venv\Scripts\python.exe jobs\utils\validate_athena_ddl_drift.py
.\.venv\Scripts\python.exe -m pytest tests
cd apps/terminal
npm run ci
```

Acceptance criteria:

- Legacy removals have replacement evidence.
- Experiment reproducibility is preserved or explicitly versioned.

Reversibility:

- Reversible through git, but potentially high risk.

Explicitly do not:

- Do not delete historical S3 data.
- Do not delete Glue/Athena tables as part of code cleanup.

## Phase 10: Final Validation, Documentation, And Merge

Objective:

Prove the cleaned repo is healthy and document what changed.

Tasks:

1. Run full Python validation.
2. Run full terminal-app validation.
3. Run targeted operational checks.
4. Produce final cleanup summary.
5. Push branch.
6. Open PR or merge to main after approval.

Commands:

```powershell
.\.venv\Scripts\python.exe -m pytest tests
.\.venv\Scripts\python.exe -m mypy src
.\.venv\Scripts\python.exe -m ruff check src jobs tests
.\.venv\Scripts\python.exe jobs\utils\validate_athena_ddl_drift.py

cd apps/terminal
npm run ci
npm run build
```

Final report:

```text
docs/cleanup/ai_cleanup_YYYYMMDD/FINAL_REPORT.md
```

Acceptance criteria:

- All agreed tests pass or pre-existing failures are documented.
- Cleanup report links to subagent reports.
- No active work was overwritten.
- Main branch merge/push happens only after review.

Reversibility:

- Safe if merged via PR or clean commit series.

Explicitly do not:

- Do not squash away useful phase history unless the user requests it.

## Recommended Commit Structure

Use small commits:

```text
cleanup: add baseline and subagent reports
cleanup: remove confirmed unused terminal components
cleanup: consolidate storage helpers
cleanup: consolidate dataset manifest types
cleanup: reduce weak types in model dataset boundaries
cleanup: remove circular imports in training modules
cleanup: make batch error handling explicit
cleanup: retire verified stale configs
cleanup: trim comments and stale notes
```

Avoid one giant commit called `cleanup`.

## Manual Approval Gates

Require explicit user approval before:

- Deleting any Batch job entrypoint.
- Deleting any Glue script.
- Deleting or renaming any SQL DDL.
- Deleting any Terraform module.
- Deleting any config that maps a commodity/source/model.
- Removing GraphRAG code while another agent is editing it.
- Removing old model-ready dataset compatibility.
- Removing source-specific ETL fallbacks.

## Tooling Additions To Consider

Python:

- `vulture` for unused Python candidates.
- `deptry` for dependency hygiene.
- `grimp` or `pydeps` for import graph inspection.
- More `ruff` rules beyond import sorting, introduced gradually.

TypeScript:

- `knip` for unused files/exports/dependencies.
- `madge` for circular dependencies.
- `jscpd` for duplicate blocks.

These should be introduced in a separate tooling commit so cleanup diffs stay readable.

## High-Risk Areas

- `src/leviathan/graphrag/`: active, complex, external-service heavy.
- `jobs/batch/`: operational entrypoints, often referenced indirectly.
- `jobs/submit/`: job definitions and command contracts.
- `sql/athena/ddl/`: external table contracts; stale-looking files may still matter.
- `infra/terraform/`: changes affect cloud resources and cost.
- `configs/features/` and `configs/ml/`: model/data contract surface.
- `src/leviathan/model_datasets/`: experiment reproducibility.
- `apps/terminal/src/api/types.gen.ts`: generated API types.

## Definition Of High Confidence

A cleanup item is high confidence only if at least two of the following agree:

- Static tool says unused/duplicated/problematic.
- `rg` confirms no references.
- Tests confirm no behavior loss.
- Build/typecheck confirms no references.
- Docs/config/Terraform/Dockerfiles do not reference it.
- Runtime entrypoint list does not reference it.
- The replacement path is already active and tested.

If only one signal exists, keep it as a recommendation.

## What This Plan Is Not

This is not:

- A rewrite.
- A style-only formatting pass.
- A chance to change model strategy.
- A chance to delete historical S3 data.
- A cleanup of cloud resources.
- A GraphRAG refactor unless explicitly scoped in.

The cleanup should make the current system sharper, not restart it.

