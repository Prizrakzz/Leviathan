# Phase 6 Completion

Status: complete.

Completed: 2026-06-25

## Scope

Phase 6 replaced era-only experiment selection with model-purpose feature sets
resolved from the Phase 5 semantic catalog. Legacy `feature_tiers.yaml` remains
available for backward compatibility.

GraphRAG was not touched.

## Dataset Version

```text
20260625T105545Z_2bd0f32c
```

## Code And Config

Feature-set config:

```text
configs/features/feature_sets.yaml
```

Selector module:

```text
src/leviathan/features/feature_sets.py
```

Batch task:

```text
jobs/batch/feature_set_task.py
```

Training integration:

```text
jobs/batch/train_commodity.py
jobs/submit/submit_batch_train.py
jobs/utils/register_train_jobdef.py
```

Builder commits:

```text
2a43cdf4 Add governed feature set selection
5555841b Keep feature set summaries outside parquet table prefix
```

## Feature Sets

Configured model-purpose sets:

- `preseason_physical`
- `inseason_weather`
- `crop_condition`
- `official_revision`
- `physical_flow`
- `balance_sheet`
- `processing_economics`
- `planting_incentives`
- `trade_competitiveness`
- `tail_risk`
- `data_quality`
- `diagnostic_market_context`

Core sets exclude labels, `diagnostic_only`, and `excluded_market_signal`.
Economic-driver sets select only `certified_economic_driver` features.

## S3 Outputs

Feature-set membership Parquet:

```text
s3://leviathan-dev-shahem-001/gold/feature_set_versions/dataset_version=20260625T105545Z_2bd0f32c/feature_sets.parquet
```

Feature-set JSON summary:

```text
s3://leviathan-dev-shahem-001/gold/feature_set_manifests/dataset_version=20260625T105545Z_2bd0f32c/feature_sets.json
```

The dataset manifest was patched with the feature-set summary and output keys:

```text
s3://leviathan-dev-shahem-001/gold/feature_spine_manifests/dataset_version=20260625T105545Z_2bd0f32c/manifest.json
```

## Validation Summary

| Metric | Value |
|---|---:|
| Feature sets | 12 |
| Selected membership rows | 4,145 |
| Label rows selected | 0 |
| Core bad-policy rows | 0 |
| Certified economic-driver membership rows | 16 |
| Diagnostic-only membership rows | 2 |
| Fundamental physical membership rows | 4,127 |

Per-set counts:

| Feature set | Features |
|---|---:|
| `balance_sheet` | 6 |
| `crop_condition` | 1 |
| `data_quality` | 53 |
| `diagnostic_market_context` | 2 |
| `inseason_weather` | 2,675 |
| `official_revision` | 2 |
| `physical_flow` | 6 |
| `planting_incentives` | 6 |
| `preseason_physical` | 24 |
| `processing_economics` | 1 |
| `tail_risk` | 1,367 |
| `trade_competitiveness` | 2 |

Athena validation query results:

```text
gold_feature_set_versions: rows=4145, feature_sets=12, label_rows=0, core_bad_policy_rows=0
```

Athena query ids:

```text
summary: 9f480865-b13d-4561-a664-8f4b572b0f9f
by_set:  c014ef3a-305c-4918-ad38-248678e81a4e
```

## Athena

Applied table definition:

```text
gold_feature_set_versions
```

The JSON summary is intentionally stored under `gold/feature_set_manifests/`,
not inside the Parquet table prefix. Athena scans every object under a Hive
partition location, so putting JSON beside Parquet caused `HIVE_BAD_DATA` during
the first smoke query. The stray JSON object was deleted and the task now writes
the summary outside the table prefix.

## Checks

Focused tests:

```text
44 passed
41 passed
```

Commands:

```powershell
C:\Users\User\Desktop\Leviathan\.venv\Scripts\python.exe -m pytest `
  tests\unit\test_storage_paths.py `
  tests\unit\test_features_feature_sets.py `
  tests\unit\test_features_semantic_catalog.py

C:\Users\User\Desktop\Leviathan\.venv\Scripts\python.exe -m py_compile `
  jobs\batch\train_commodity.py `
  jobs\submit\submit_batch_train.py `
  jobs\utils\register_train_jobdef.py `
  jobs\batch\feature_set_task.py `
  src\leviathan\features\feature_sets.py

git diff --check
```

## Known Limitations

- Phase 6 governs and selects the existing Phase 4/5 feature universe. It does
  not add new feature families to gold.
- The train job definition registration helper now supports `feature_set`, but
  the live AWS Batch training job definition should be re-registered only after
  the trainer image is rebuilt with this code.
- `feature_tiers.yaml` remains in place for legacy runs and training-window
  summaries. Governed MLflow experiments should prefer `feature_sets.yaml`.

## Next

Phase 6 is complete. Next is Phase 7: add high-value existing-silver feature
families into gold, starting with WASDE direct revisions, NASS citrus, AMS
cotton quality, UNICA, FNC Colombia, ICCO cocoa, Food CPI, and vegetable-oil
substitution features where the existing silver data supports them.
