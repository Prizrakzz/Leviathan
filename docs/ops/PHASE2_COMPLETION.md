# Phase 2 Completion

Status: complete for source certification coverage. No sources are blocked.
Several sources remain warning-only because exact duplicate scans or projected
Athena row counts were intentionally deferred.

Completed: 2026-06-24

## Scope

Phase 2 certifies existing non-GraphRAG silver sources before they are admitted
to model-ready gold and MLflow experiments. It does not perform new ingestion,
new silver ETL, gold versioning, or model training.

GraphRAG was not touched.

## Implementation

Added:

- `configs/datasets/source_contracts.yaml`
- `src/leviathan/certification/source_certification.py`
- `scripts/certification/certify_sources.py`
- focused unit tests for certification decisions and feature-source coverage

The source contracts cover every source referenced by
`configs/features/features.yaml` and additional high-priority silver sources
planned for later model-ready feature sets.

## Live Certification Result

Report:

```text
data/system_inventory/source_certification_20260624T214850/source_certification_report.json
```

Markdown summary:

```text
data/system_inventory/source_certification_20260624T214850/source_certification_report.md
```

Status counts:

| Status | Count |
| --- | ---: |
| `warn` | 27 |
| `deferred` | 6 |
| `diagnostic_only` | 2 |
| `blocked` | 0 |

Feature registry coverage:

- feature sources referenced by `features.yaml`: 20
- missing source contracts: 0
- extra priority contracts not yet referenced by `features.yaml`: 15

## Important Findings

No active source is blocked by missing S3 prefixes, missing Glue tables, missing
required columns, or missing feature-source contracts.

The warning-only statuses are expected for this Phase 2 run:

- exact duplicate scans were skipped with `--skip-duplicate-checks`;
- partition-projected/heavy tables such as CHIRPS, NASA POWER, CPC soil, and
  ESR are metadata/schema certified and require source-specific bounded
  validation for exact row counts and duplicate checks;
- diagnostic market-context sources remain `diagnostic_only`:
  `futures_prices` and `cot`;
- different-grain tables remain `deferred`, such as FNC area/port details,
  MPOC auxiliary tables, and UNICA annual state.

## Representative Live Counts

| Source | Rows | Date Range |
| --- | ---: | --- |
| `production:faostat` | 683,152 | 1961-2024 |
| `psd` | 163,707 | 1960-01-01 to 2027-03-10 |
| `wasde` | 580,871 | 1985-01-11 to 2026-05-12 |
| `nass_crop_progress` | 141,714 | 1979-04-22 to 2026-05-17 |
| `fgis` | 111,444 | 1983-01-03 to 2026-01-04 |
| `fnc_colombia_monthly` | 1,360 | 1913-01-01 to 2026-04-01 |
| `futures_prices` | 78,268 | 1999-09-14 to 2026-06-05 |
| `cot` | 10,806 | 2006-06-13 to 2025-12-30 |
| `oni` | 915 | 1950-2026 |

## Verification

Focused tests:

```text
12 passed
```

Command:

```powershell
C:\Users\User\Desktop\Leviathan\.venv\Scripts\python.exe -m pytest tests\unit\test_source_certification.py tests\unit\test_feature_source_coverage.py
```

Live certification command:

```powershell
C:\Users\User\Desktop\Leviathan\.venv\Scripts\python.exe scripts\certification\certify_sources.py `
  --contracts configs\datasets\source_contracts.yaml `
  --features configs\features\features.yaml `
  --database leviathan_dev `
  --aws-region us-east-1 `
  --output data\system_inventory\source_certification_20260624T214850\source_certification_report.json `
  --emit-md `
  --skip-duplicate-checks
```

## Exit Criteria

- Every feature family in `configs/features/features.yaml` references a source
  with a certification contract: pass.
- Every priority source has a certification status: pass.
- No source is hard-blocked: pass.
- Diagnostic-only sources are explicit: pass.
- Deferred sources are explicit: pass.
- Machine-readable and human-readable reports exist: pass.

## Next

Phase 2 is complete. Next is Phase 3: preserve and clean the current v2 scratch
work before versioning broad legacy gold.

Before Phase 4 publishes immutable gold, run source-specific bounded duplicate
checks for warning-only sources whose exact uniqueness was intentionally
deferred here.
