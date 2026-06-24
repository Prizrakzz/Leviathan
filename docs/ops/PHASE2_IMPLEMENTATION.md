# Phase 2 Implementation Note

Date: 2026-06-23

Phase 2 implementation has started on `codex/mlflow-readiness-phase2`.

Implemented:

- Source certification framework:
  - pure DataFrame certification engine
  - `configs/datasets/source_contracts.yaml`
  - `scripts/certification/certify_sources.py`
- Fundamental feature-policy preflight:
  - allows declared economic drivers such as input costs, FX, and crush margin
  - drops diagnostic-only features such as COT from fitting
  - rejects excluded market signals
  - logs admitted economic drivers to MLflow
- WASDE silver:
  - `leviathan.transforms.bronze_to_silver.usda_wasde`
  - `jobs/batch/wasde_silver_task.py`
  - `silver_wasde` registry/DDL
- CONAB coffee silver repair:
  - raw key and ETag propagated into future bronze reruns
  - revision-aware silver transform
  - survey content fingerprint
  - identical accepted-survey tables block publication
  - `jobs/batch/conab_silver_task.py`
- AMS cotton annual-quality scaffolding:
  - conservative PDF text extractor
  - annual bronze/silver transforms
  - bronze and silver Batch wrappers
  - `silver_ams_cotton_quality` registry/DDL

Not yet complete:

- Glue/Athena deployment for the new/changed tables.
- WASDE silver backfill.
- CONAB bronze refresh and silver backfill.
- AMS cotton bronze/silver backfill.
- Source certification reports from live S3/Athena.
- Phase 2 completion evidence.

Validation run:

- Focused Phase 2 tests: `31 passed`.
- Ruff on new/changed Phase 2 files: passed.
- DDL generation from registry: `49 DDLs`.
- Full unit suite: `1078 passed`, `2 failed` due to missing untracked
  `src/leviathan/graphrag/pilot.py` in this isolated worktree. Those failures
  are unrelated to Phase 2 structured-data work.
