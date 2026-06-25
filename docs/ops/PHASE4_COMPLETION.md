# Phase 4 Completion

Status: complete.

Completed: 2026-06-25

## Scope

Phase 4 wrapped the broad legacy `gold/feature_spine` and
`gold/feature_matrix` in immutable, versioned, MLflow-pinnable dataset outputs.

GraphRAG was not touched.

## Dataset Version

```text
20260625T105545Z_2bd0f32c
```

This version is the first complete broad legacy-gold package for MLflow
experimentation.

## S3 Outputs

Feature spine:

```text
s3://leviathan-dev-shahem-001/gold/feature_spine_versions/dataset_version=20260625T105545Z_2bd0f32c/
```

Feature matrix:

```text
s3://leviathan-dev-shahem-001/gold/feature_matrix_versions/dataset_version=20260625T105545Z_2bd0f32c/
```

Per-commodity manifests:

```text
s3://leviathan-dev-shahem-001/gold/feature_spine_commodity_manifests/dataset_version=20260625T105545Z_2bd0f32c/
```

Dataset manifest:

```text
s3://leviathan-dev-shahem-001/gold/feature_spine_manifests/dataset_version=20260625T105545Z_2bd0f32c/manifest.json
```

Feature catalog:

```text
s3://leviathan-dev-shahem-001/gold/feature_catalog_versions/dataset_version=20260625T105545Z_2bd0f32c/feature_catalog.parquet
```

Training windows:

```text
s3://leviathan-dev-shahem-001/gold/training_windows_versions/dataset_version=20260625T105545Z_2bd0f32c/training_windows.parquet
s3://leviathan-dev-shahem-001/gold/training_windows_versions/dataset_version=20260625T105545Z_2bd0f32c/training_windows.md
```

## Validation Summary

The final dataset manifest reports:

| Metric | Value |
|---|---:|
| Commodities | 31 |
| Feature-spine rows | 144,346 |
| Feature-matrix rows | 4,370 |
| Label rows | 11,207 |
| Feature catalog rows | 2,705 |
| Label features | 3 |
| Universal empirical features | 9 |
| Group empirical features | 114 |
| Commodity empirical features | 2,582 |
| Training-window rows | 124 |
| Training-window commodities | 31 |
| Training-window tiers | 4 |
| Hard failures | 0 |
| Warnings | 8 |

Training-window tiers:

```text
climate
full
fundamentals
trade_condition
```

## Batch Run

The first single-job broad build was interrupted by Fargate Spot after writing
partial versioned outputs. The remaining eight commodities were completed by
sharded on-demand Batch jobs with `--skip-existing-versioned`.

Missing commodities recovered by sharded jobs:

- `malaysian_crude_palm_oil_cme`
- `brazilian_arabica_coffee`
- `arabica_coffee`
- `robusta_coffee`
- `cotton`
- `raw_sugar`
- `white_sugar`
- `frozen_orange_juice`

Finalizer code commit:

```text
7f04b220 Finalize versioned training window metadata
```

## Checks

Focused tests:

```text
49 passed
```

Commands:

```powershell
python -m pytest `
  tests\unit\test_feature_spine_finalize_task.py `
  tests\unit\test_feature_spine_versioning.py `
  tests\unit\test_storage_paths.py -q

python -m py_compile `
  jobs\batch\build_training_windows.py `
  jobs\batch\feature_spine_finalize_task.py

git diff --check
```

S3 validation confirmed:

- 31 feature-spine parquet objects;
- 31 feature-matrix parquet objects;
- 31 per-commodity manifests;
- one dataset manifest;
- one versioned feature catalog;
- two versioned training-window artifacts.

## Known Limitations

- The feature catalog is still empirical: `universal`, `group`, and
  `commodity` scopes are based on observed commodity membership in this dataset
  version.
- Semantic taxonomy, feature/entity maps, and feature/group maps are Phase 5.
- Model-purpose feature sets are Phase 6.
- Training jobs still need Phase 9 changes to require or select
  `dataset_version` and feature-set version by default.
- This version is immutable and reproducible under the current crop-year
  convention, but it does not claim full historical multi-`as_of_date` replay.

## Next

Phase 4 is complete. Next is Phase 5: build the semantic feature taxonomy,
feature/entity map, and feature/group map around this versioned broad gold
dataset.
