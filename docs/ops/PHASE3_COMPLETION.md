# Phase 3 Completion

Status: complete.

Completed: 2026-06-25

## Scope

Phase 3 preserved and classified the current `gold_v2` scratch work so it no
longer blocks the MLflow readiness path.

GraphRAG was not touched.

## Preservation

The v2 scratch work was committed and pushed to:

```text
codex/gold-v2-scratch-preserved
```

Preservation commit:

```text
52934c66 Preserve gold v2 scratch work
```

## Decision

`gold_v2` remains a future point-in-time design source, not the active MLflow
training surface.

Current MLflow readiness continues through:

```text
gold/feature_spine
gold/feature_matrix
```

Phase 4 should add immutable, versioned outputs around the broad legacy gold
layer rather than routing training through the thin v2 proof.

## Audit

Full file-by-file classification:

```text
docs/ops/PHASE3_V2_SCRATCH_AUDIT.md
```

Summary:

- `adapt_now`: taxonomy, feature sets, cataloging, availability concepts,
  bounded extraction, policy guardrails;
- `future_pit_v2`: thin `feature_spine_v2` builder, `gold_v2` dataset registry
  additions, `gold_v2` path helpers, PIT-specific tests;
- `defer/discard`: anything that implies v2 is already broad enough to replace
  legacy gold.

## Verification

Focused tests:

```text
19 passed
```

Command:

```powershell
C:\Users\User\Desktop\Leviathan\.venv\Scripts\python.exe -m pytest `
  tests\unit\test_source_certification.py `
  tests\unit\test_feature_source_coverage.py `
  tests\unit\test_features_registry.py
```

## Next

Phase 3 is complete. Next is Phase 4: version the broad legacy
`gold/feature_spine` and matching feature matrix for MLflow experiments.
