# Phase 2 Subagent 04 - Circular Dependencies

## Scope

Read-only circular-dependency and layering assessment for Python and TypeScript. GraphRAG and AI-agent paths were excluded.

No code edits, deletes, installs, AWS calls, S3 mutations, Terraform applies, or formatting tools were run.

## Evidence

`madge` was not installed, so this phase used manual static checks:

- Python graph: 323 files/modules scanned.
- TypeScript graph: 99 app source files scanned.
- Production TypeScript graph: 63 files scanned.
- Targeted `rg` checks for known forbidden directions.

## Findings

### No direct circular-dependency issue found

No direct cycles were detected in the in-scope Python or TypeScript graphs by the manual scan.

### No major layer violations found

No hits were found for the targeted forbidden directions:

- non-GraphRAG `src/leviathan` importing `jobs`
- `storage` importing `training` or `features`
- `features` importing `jobs` or `training`
- frontend API layer importing views

### Byte order mark parse issues

Two files could not be parsed cleanly by the AST scanner because of a leading byte order mark:

- `src/leviathan/transforms/bronze_to_silver/usda_psd.py`
- `jobs/ingest/discover_unica_wayback.py`

The UNICA file also appears in unused-code findings due to a syntax error.

## Critical Assessment

Circular dependencies are not the immediate cleanup risk. The larger structural issue is duplicated operational helper code, not inverted imports.

The next cleanup phase should not spend time untangling architecture that is not currently tangled. It should install/use a proper cycle checker only as a guardrail after higher-confidence cleanup.

## Recommended Phase 3 Edits

1. Do not refactor layers for circularity yet.
2. Optionally remove the byte order mark in `usda_psd.py` only if a formatter or parser step touches that file for another reason.
3. Resolve the `discover_unica_wayback.py` syntax/BOM issue only after deciding whether the script is still needed.
4. Add a future CI/static-check task for cycles if the project later adds `madge`, `grimp`, or similar tooling.

## Validation

- If `madge` is added later: run it only on `apps/terminal/src`, excluding generated API files if needed.
- If a Python cycle checker is added later: exclude tests, GraphRAG, and CLI-only jobs unless explicitly in scope.
- Run targeted import smoke tests after any architecture refactor.

