# Phase 5 Completion

Status: complete.

Completed: 2026-06-25

## Scope

Phase 5 replaced the empirical-only feature catalog with a semantic catalog and
added feature-to-entity and feature-to-group coverage maps for the completed
Phase 4 dataset version.

GraphRAG was not touched.

## Dataset Version

```text
20260625T105545Z_2bd0f32c
```

## Code And Config

Taxonomy config:

```text
configs/features/feature_taxonomy.yaml
```

Group config:

```text
configs/features/feature_groups.yaml
```

Catalog task:

```text
jobs/batch/feature_catalog_task.py
```

Builder commit:

```text
b9a61948 Add semantic feature catalog maps
```

## S3 Outputs

Semantic feature catalog:

```text
s3://leviathan-dev-shahem-001/gold/feature_catalog_versions/dataset_version=20260625T105545Z_2bd0f32c/feature_catalog.parquet
```

Feature/entity map:

```text
s3://leviathan-dev-shahem-001/gold/feature_entity_map_versions/dataset_version=20260625T105545Z_2bd0f32c/feature_entity_map.parquet
```

Feature/group map:

```text
s3://leviathan-dev-shahem-001/gold/feature_group_map_versions/dataset_version=20260625T105545Z_2bd0f32c/feature_group_map.parquet
```

The dataset manifest was patched with the semantic catalog summary and output
keys:

```text
s3://leviathan-dev-shahem-001/gold/feature_spine_manifests/dataset_version=20260625T105545Z_2bd0f32c/manifest.json
```

## Validation Summary

| Metric | Value |
|---|---:|
| Catalog rows | 2,705 |
| Entity-map rows | 4,408 |
| Group-map rows | 8,182 |
| Unknown feature count | 0 |
| Fundamental physical features | 2,696 |
| Certified economic-driver features | 7 |
| Diagnostic-only features | 2 |
| Label features | 3 |
| Athena catalog rows | 2,705 |
| Athena entity-map rows | 4,408 |
| Athena group-map rows | 8,182 |

Top semantic scopes:

| Scope | Features |
|---|---:|
| `origin_stage_weather` | 1,199 |
| `origin_soil_moisture` | 513 |
| `origin_weather` | 429 |
| `origin_stage_remote_sensing` | 424 |
| `origin_perennial_capacity` | 102 |

Policy counts:

```text
certified_economic_driver: 7
diagnostic_only: 2
fundamental_physical: 2696
```

Athena validation query results:

```text
gold_feature_catalog_versions: rows=2705, unknowns=0
gold_feature_entity_map_versions: rows=4408, features=2705
gold_feature_group_map_versions: rows=8182, groups=20
```

## Athena

Applied table definitions:

- `gold_feature_catalog_versions`
- `gold_feature_entity_map_versions`
- `gold_feature_group_map_versions`

The catalog DDL was replaced because the old table schema described the Phase 4
empirical catalog. Dropping and recreating these external tables did not delete
S3 data.

## Checks

Focused tests:

```text
39 passed
```

Commands:

```powershell
python -m pytest `
  tests\unit\test_features_semantic_catalog.py `
  tests\unit\test_storage_paths.py -q

python -m py_compile `
  src\leviathan\features\semantic_catalog.py `
  jobs\batch\feature_catalog_task.py

git diff --check
```

## Known Limitations

- Phase 5 classifies and maps the existing Phase 4 feature universe. It does
  not add new feature families to gold.
- Feature groups are config-driven and intentionally overlapping. They are
  suitable for feature-set selection, not mutually exclusive reporting buckets.
- `diagnostic_only` COT features remain cataloged for slicing/monitoring but
  must stay out of core fundamental feature sets.
- Model-purpose feature sets are still Phase 6.
- Training jobs still need Phase 9 changes to select dataset and feature-set
  versions by default.

## Next

Phase 5 is complete. Next is Phase 6: replace era-based tiers with
model-purpose feature sets and policy-aware feature selection.
