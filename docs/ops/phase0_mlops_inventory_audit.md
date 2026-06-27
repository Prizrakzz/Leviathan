# Phase 0 MLOps Inventory Audit

Date: 2026-06-27

Scope: PSD-first restructuring Phase 0. This report is an inventory and
checkpoint only. It does not implement PSD targets, demote FAOSTAT, rebuild
datasets, change Glue/Athena, or clean S3.

## Executive Summary

Phase 0 confirms the current Leviathan MLOps research surface is functional and
versioned, but the current model-ready target family is still the legacy annual
physical anomaly surface. The active model-ready version is built from the
active gold feature matrix version and contains 83 target/matrix outputs across
31 commodities.

Observed high-confidence facts:

- Active source gold dataset version:
  `20260626T010217Z_6725de02_phase7_full`.
- Active model-ready dataset version:
  `20260626T104732Z_a2576e84_phase8_model_ready`.
- Current model-ready dataset key:
  `annual_physical_anomaly`.
- Current configured targets:
  `production_anomaly_pct`, `yield_anomaly_pct`,
  `area_harvested_anomaly_pct`.
- Current label features in the active feature catalog have source
  `production:faostat`, not PSD.
- `silver/psd/part-000.parquet` is present and broad enough to support a
  future PSD-first target builder, but PSD is currently feature context, not the
  primary model-ready target source.
- MLflow is hosted on EC2 instance `i-012f869a03d7247fa`
  (`leviathan-dev-mlflow-server`) and the local SSM tunnel was verified healthy
  at `http://127.0.0.1:5000/health`.

No S3 objects, Glue tables, Athena DDLs, MLflow runs, or production code were
modified during this Phase 0 inventory. The only repository change made during
this phase is this audit document.

## Local Repository State

Current branch:

```text
main...origin/main
```

Pre-existing dirty/untracked work was present before this audit document was
created. Notable entries included:

```text
M scratch/check_gain_batch.py
?? .kiro/
?? data/experiment_baselines/
?? data/ml_platform_backups/
?? data/system_inventory/as_of_date=2026-06-23/
?? docs/PSD_FIRST_MLOPS_RESTRUCTURING_PLAN.md
?? docs/training_windows.md
?? scratch/*.py
?? scripts/setup_mlflow.sh
?? src/leviathan/graphrag/pilot.py
```

GraphRAG work remains out of scope and was not inspected beyond broad file
search results.

## Code And Config Inventory

### Target Definitions And Model-Ready Builder

Observed files:

- `configs/ml/target_definitions.yaml`
- `src/leviathan/model_datasets/targets.py`
- `src/leviathan/model_datasets/builder.py`
- `src/leviathan/model_datasets/baselines.py`
- `jobs/batch/build_model_ready_datasets.py`
- `jobs/submit/submit_batch_model_ready_datasets.py`

Observed target config:

```text
schema_version: 1
defaults.source_dataset_version: 20260626T010217Z_6725de02_phase7_full
defaults.target_type: trailing_trend_pct_anomaly
defaults.min_history_years: 5
```

Configured target definitions:

| target_key | dataset_key | label_column | target_type | grain |
|---|---|---|---|---|
| `production_anomaly_pct` | `annual_physical_anomaly` | `label_production_quantity` | `trailing_trend_pct_anomaly` | commodity, country, crop_year |
| `yield_anomaly_pct` | `annual_physical_anomaly` | `label_yield` | `trailing_trend_pct_anomaly` | commodity, country, crop_year |
| `area_harvested_anomaly_pct` | `annual_physical_anomaly` | `label_area_harvested` | `trailing_trend_pct_anomaly` | commodity, country, crop_year |

Observed code path:

- `src/leviathan/model_datasets/builder.py` checks whether each
  `TargetDefinition.label_column` exists in the wide gold feature matrix.
- It calls `build_trailing_anomaly_targets(...)` for
  `trailing_trend_pct_anomaly`.
- `src/leviathan/model_datasets/baselines.py` fits the trend only on prior
  years through `history["crop_year"] < crop_year`.
- `_pct_deviation(value, baseline)` returns
  `(value - baseline) / abs(baseline)` and returns null for exactly zero
  denominator.

Phase 1 should inspect this target path more deeply and produce the formal
target-source truth table.

### Label And Feature Computation

Observed files:

- `configs/features/features.yaml`
- `configs/features/feature_taxonomy.yaml`
- `configs/features/feature_groups.yaml`
- `configs/features/feature_sets.yaml`
- `configs/features/crop_calendars.yaml`
- `src/leviathan/features/computations/production.py`
- `src/leviathan/features/computations/sd_balance.py`
- `src/leviathan/features/visibility.py`
- `src/leviathan/features/spine.py`
- `src/leviathan/features/semantic_catalog.py`
- `src/leviathan/features/feature_sets.py`
- `jobs/batch/feature_spine_task.py`
- `jobs/batch/feature_spine_finalize_task.py`
- `jobs/batch/feature_catalog_task.py`
- `jobs/batch/feature_set_task.py`

Observed feature registry counts:

```text
features.yaml feature specs: 36
feature_sets.yaml feature sets: 13
feature_taxonomy.yaml taxonomy rules: 35
feature_groups.yaml groups: 20
```

Observed FAOSTAT feature specs:

| feature family | source | visibility |
|---|---|---|
| `faostat_production_yoy` | `production:faostat` | `prior_history` |
| `faostat_production_trend_dev` | `production:faostat` | `prior_history` |
| `faostat_available` | `production:faostat` | `prior_history` |
| `faostat_labels` | `production:faostat` | `crop_year_direct` |

Observed PSD feature specs:

| feature family | source | visibility |
|---|---|---|
| `psd_ending_stock_su_ratio` | `psd` | `prior_marketing_year` |
| `psd_su_ratio_yoy_delta` | `psd` | `prior_marketing_year` |
| `psd_available` | `psd` | `prior_marketing_year` |

Observed feature sets:

```text
preseason_physical
inseason_weather
crop_condition
official_revision
physical_flow
quality_tenderability
balance_sheet
processing_economics
planting_incentives
trade_competitiveness
tail_risk
data_quality
diagnostic_market_context
```

Governance note:

- `feature_sets.py` blocks `diagnostic_only` and `excluded_market_signal` from
  core feature sets unless explicitly allowed.
- Feature sets do not include other feature sets. They select features by
  catalog rules, policies, scopes, families, groups, sources, and patterns.

### Training And MLflow

Observed files:

- `src/leviathan/training/model_ready.py`
- `src/leviathan/training/cv.py`
- `src/leviathan/training/tracking.py`
- `src/leviathan/training/mlflow_artifacts.py`
- `src/leviathan/training/mlflow_replay.py`
- `jobs/batch/train_commodity.py`
- `jobs/submit/submit_batch_train.py`
- `docker/leviathan_trainer/Dockerfile`
- `scripts/mlflow/verify_run_replay.py`
- `scripts/certification/certify_phase10_readiness.py`
- `scripts/ops/start_mlflow_tunnel.ps1`

Observed trainer behavior:

- Supports model-ready mode through `--model-dataset-version`.
- Uses governed feature-set membership from
  `gold/feature_set_versions/dataset_version={source_version}/`.
- Excludes target/baseline/id columns and any `label_*` columns from training
  features.
- Uses walk-forward CV where each test year trains only on years strictly
  before it.
- Logs reproducibility tags including data fingerprint, feature-set SHA,
  model-ready version, source gold version, target key, dataset key, and target
  config SHA.
- Logs fitted models through the matching MLflow flavor:
  `mlflow.xgboost`, `mlflow.lightgbm`, or `mlflow.sklearn`.
- Writes prediction outputs under `silver/model_predictions/`.

Observed trainer image note:

- `docker/leviathan_trainer/Dockerfile` uses `mlflow-skinny` because the
  trainer is an MLflow client, not the MLflow server.

## S3 Inventory

Bucket: `s3://leviathan-dev-shahem-001/`

Read-only prefix inventory:

| prefix | objects | bytes | observed versions or grouping |
|---|---:|---:|---|
| `gold/feature_spine_versions/` | 67 | 2,534,597 | `20260625T105545Z_2bd0f32c`, `20260626T005517Z_6725de02_smoke_phase7`, `20260626T010217Z_6725de02_phase7_full`, `phase4_smoke_4ed02a22` |
| `gold/feature_matrix_versions/` | 67 | 7,673,417 | same four versions |
| `gold/feature_catalog_versions/` | 4 | 117,536 | same four versions |
| `gold/feature_entity_map_versions/` | 3 | 88,899 | active and prior phase7 versions |
| `gold/feature_group_map_versions/` | 3 | 99,821 | active and prior phase7 versions |
| `gold/feature_set_versions/` | 2 | 99,171 | `20260625T105545Z_2bd0f32c`, `20260626T010217Z_6725de02_phase7_full` |
| `gold/model_ready_targets/` | 32 | 1,087,998 | `20260626T104732Z_a2576e84_phase8_model_ready`, `20260626T110249Z_38ffa8b3_phase8_batch_smoke` |
| `gold/model_ready_matrices/` | 84 | 12,514,710 | same two model-ready versions |
| `gold/model_ready_baselines/` | 2 | 16,640 | same two model-ready versions |
| `gold/model_ready_manifests/` | 2 | 222,423 | same two model-ready versions |
| `silver/psd/` | 2 | 2,343,516 | flat PSD silver table |
| `silver/production/` | 2,375 | 36,257,425 | FAOSTAT production silver partitions |
| `silver/model_predictions/` | 3 | 36,187 | `model_family=tier1_production` |
| `model_artifacts/training_snapshots/` | 5 | 410,090 | five MLflow run snapshots |
| `mlflow/artifacts/` | 26 | 692,934 | experiment `1` artifacts |
| `mlflow/backups/backend/` | 4 | 534,490 | backups `2026-06-23T12-30-57Z`, `2026-06-24T16-12-22Z` |

Current production research surfaces:

- `gold/feature_spine_versions/dataset_version=20260626T010217Z_6725de02_phase7_full/`
- `gold/feature_matrix_versions/dataset_version=20260626T010217Z_6725de02_phase7_full/`
- `gold/feature_catalog_versions/dataset_version=20260626T010217Z_6725de02_phase7_full/`
- `gold/feature_entity_map_versions/dataset_version=20260626T010217Z_6725de02_phase7_full/`
- `gold/feature_group_map_versions/dataset_version=20260626T010217Z_6725de02_phase7_full/`
- `gold/feature_set_versions/dataset_version=20260626T010217Z_6725de02_phase7_full/`
- `gold/model_ready_targets/dataset_version=20260626T104732Z_a2576e84_phase8_model_ready/`
- `gold/model_ready_matrices/dataset_version=20260626T104732Z_a2576e84_phase8_model_ready/`
- `gold/model_ready_baselines/dataset_version=20260626T104732Z_a2576e84_phase8_model_ready/`
- `gold/model_ready_manifests/dataset_version=20260626T104732Z_a2576e84_phase8_model_ready/`

Legacy or confusing candidates for later review:

- `gold/feature_spine_versions/dataset_version=phase4_smoke_4ed02a22/`
- `gold/feature_matrix_versions/dataset_version=phase4_smoke_4ed02a22/`
- `gold/feature_*_versions/dataset_version=20260625T105545Z_2bd0f32c/`
- `gold/feature_*_versions/dataset_version=20260626T005517Z_6725de02_smoke_phase7/`
- `gold/model_ready_* /dataset_version=20260626T110249Z_38ffa8b3_phase8_batch_smoke/`
- `silver/model_predictions/model_family=tier1_production/`

These should not be deleted now. They should be marked or ignored only in a
later manual-approval cleanup phase.

## Active Gold Feature Spine Snapshot

Source:

```text
s3://leviathan-dev-shahem-001/gold/feature_spine_manifests/dataset_version=20260626T010217Z_6725de02_phase7_full/manifest.json
```

Observed summary:

```text
commodity_count: 31
total_spine_rows: 151,927
total_matrix_rows: 4,370
total_label_rows: 11,207
feature_count: 2,722
label_feature_count: 3
universal_feature_count: 9
group_feature_count: 121
commodity_feature_count: 2,592
warning_count: 8
hard_failure_count: 0
training_windows_available: true
training_windows_row_count: 124
```

Source summary includes major inputs such as FAOSTAT, PSD, WASDE, WAP, weather,
ESR, FGIS, NASS crop progress, CONAB, MPOB, SAGIS, UNICA, AMS cotton, COT,
futures prices, FRED FX, ONI/IOD, and Pink Sheet.

Semantic catalog summary:

```text
catalog_rows: 2,722
entity_map_rows: 4,668
group_map_rows: 8,284
unknown_feature_count: 0
policy_counts:
  certified_economic_driver: 7
  diagnostic_only: 2
  fundamental_physical: 2,713
```

Feature set summary:

```text
feature_set_count: 13
selected_row_count: 4,165
preseason_physical: 24 selected rows
inseason_weather: 2,675 selected rows
balance_sheet: 6 selected rows
tail_risk: 1,370 selected rows
```

## Active Feature Catalog Evidence

Active feature catalog:

```text
s3://leviathan-dev-shahem-001/gold/feature_catalog_versions/dataset_version=20260626T010217Z_6725de02_phase7_full/feature_catalog.parquet
```

Observed shape:

```text
2,722 rows x 19 columns
```

Observed FAOSTAT and PSD catalog rows:

| feature | is_label | sources | feature_family | semantic_scope | policy | commodity_count |
|---|---:|---|---|---|---|---:|
| `faostat_available` | false | `production:faostat` | `faostat_production` | `origin_production_history` | `fundamental_physical` | 31 |
| `faostat_production_trend_dev` | false | `production:faostat` | `faostat_production` | `origin_production_history` | `fundamental_physical` | 31 |
| `faostat_production_yoy` | false | `production:faostat` | `faostat_production` | `origin_production_history` | `fundamental_physical` | 31 |
| `label_area_harvested` | true | `production:faostat` | `labels` | `target_label` | `fundamental_physical` | 26 |
| `label_production_quantity` | true | `production:faostat` | `labels` | `target_label` | `fundamental_physical` | 31 |
| `label_yield` | true | `production:faostat` | `labels` | `target_label` | `fundamental_physical` | 26 |
| `psd_available` | false | `psd` | `balance_sheet` | `origin_balance_sheet` | `fundamental_physical` | 31 |
| `psd_ending_stock_su_ratio` | false | `psd` | `balance_sheet` | `origin_balance_sheet` | `fundamental_physical` | 28 |
| `psd_su_ratio_yoy_delta` | false | `psd` | `balance_sheet` | `origin_balance_sheet` | `fundamental_physical` | 28 |

Phase 0 interpretation:

- The active catalog already clearly distinguishes FAOSTAT labels from PSD
  features.
- The target names in model-ready artifacts do not themselves expose this
  distinction. That is a risk for future researchers.

## Active Model-Ready Snapshot

Manifest:

```text
s3://leviathan-dev-shahem-001/gold/model_ready_manifests/dataset_version=20260626T104732Z_a2576e84_phase8_model_ready/manifest.json
```

Observed summary:

```text
requested_commodity_count: 31
processed_commodity_count: 31
skipped_commodity_count: 0
failed_commodity_count: 0
built_target_count: 83
target_row_count: 11,822
matrix_count: 83
baseline_metric_count: 332
target_config_sha: 44e2aa29044cca6cbacece2e5ac8364e52f7db2291a246b9963193955d072c6c
```

Observed target table sample:

```text
s3://leviathan-dev-shahem-001/gold/model_ready_targets/dataset_version=20260626T104732Z_a2576e84_phase8_model_ready/dataset_key=annual_physical_anomaly/commodity=corn_cbot/part-000.parquet
```

Shape:

```text
552 rows x 20 columns
```

Columns:

```text
source_dataset_version
dataset_key
commodity
target_key
target_title
target_unit
country
crop_year
actual_value
target_value
trend_prediction
prior_year_value
trailing_mean_prediction
zero_anomaly_baseline
prior_year_anomaly_baseline
trailing_mean_anomaly_baseline
trailing_trend_anomaly_baseline
history_years
is_trainable
excluded_reason
```

Corn target summary:

| target_key | rows | trainable | min_year | max_year |
|---|---:|---:|---:|---:|
| `area_harvested_anomaly_pct` | 184 | 145 | 1981 | 2026 |
| `production_anomaly_pct` | 184 | 145 | 1981 | 2026 |
| `yield_anomaly_pct` | 184 | 145 | 1981 | 2026 |

Observed matrix sample:

```text
s3://leviathan-dev-shahem-001/gold/model_ready_matrices/dataset_version=20260626T104732Z_a2576e84_phase8_model_ready/dataset_key=annual_physical_anomaly/commodity=corn_cbot/target=production_anomaly_pct/part-000.parquet
```

Shape:

```text
184 rows x 479 columns
```

Observed:

- Matrix includes model-ready identity and target columns such as
  `source_dataset_version`, `dataset_key`, `commodity`, `target_key`, `country`,
  `crop_year`, `target_value`, and `is_trainable`.
- Matrix does not include `label_*` columns.
- Matrix includes PSD feature columns:
  `psd_available`, `psd_ending_stock_su_ratio`, `psd_su_ratio_yoy_delta`.
- Matrix includes FAOSTAT feature columns:
  `faostat_available`, `faostat_production_trend_dev`,
  `faostat_production_yoy`.

Phase 0 interpretation:

- The model-ready matrix correctly removes label columns from model inputs.
- Target-source metadata is still too thin. The target table has
  `source_dataset_version`, but not explicit `target_source`, `source_table`,
  `label_source`, `target_market_year`, or `target_release_context`.

## PSD Silver Snapshot

Path:

```text
s3://leviathan-dev-shahem-001/silver/psd/part-000.parquet
```

Observed shape:

```text
163,707 rows x 18 columns
```

Columns:

```text
leviathan_slug
country
market_year
wasde_release_month
release_date
beginning_stocks_mt
production_mt
imports_mt
exports_mt
ending_stocks_mt
consumption_mt
area_harvested_1000ha
yield_mt_ha
su_ratio
su_ratio_yoy_delta
production_mt_revision
ending_stocks_mt_revision
consumption_mt_revision
```

Observed coverage:

```text
leviathan_slug count: 29
country count: 206
market_year range: 1960 to 2026
release_date range: 1960-01-01 to 2027-03-10
```

Phase 0 interpretation:

- PSD silver is present and suitable for Phase 2/3 design work.
- It has production, imports, exports, ending stocks, consumption, stock-to-use,
  area, yield, revisions, market year, and release date.
- It does not yet drive model-ready target creation.

## Glue And Athena Inventory

Glue database:

```text
leviathan_dev
```

Observed live Glue tables:

```text
58 tables
```

Checked-in Athena DDL files:

```text
58 DDL files under sql/athena/ddl/
```

Observed table-name drift:

```text
Glue-only tables: none
DDL-only tables: none
```

Important limitation:

- Phase 0 only compared table names and broad Glue metadata.
- It did not perform a full schema-by-schema DDL drift audit.
- Some versioned gold tables use injected partition projection. Athena preview
  requires static equality filters on injected partition columns such as
  `dataset_version`.

Relevant gold tables:

```text
gold_feature_catalog
gold_feature_catalog_versions
gold_feature_entity_map_versions
gold_feature_group_map_versions
gold_feature_set_versions
gold_feature_spine
gold_feature_spine_manifests
gold_feature_spine_versions
gold_model_ready_baselines
gold_model_ready_targets
gold_training_windows
gold_training_windows_versions
```

Relevant silver tables include:

```text
silver_production
silver_psd
silver_wasde
silver_wap_table01
silver_wap_table01_revisions
silver_nass_annual
silver_nass_crop_progress
silver_esr
silver_fgis
silver_sagis_cec
silver_sagis_weekly_deliveries
silver_sagis_weekly_exports
silver_unica_biweekly_release_series
silver_model_predictions
```

## MLflow Inventory

MLflow EC2 instance:

| field | value |
|---|---|
| Name | `leviathan-dev-mlflow-server` |
| Instance ID | `i-012f869a03d7247fa` |
| State | `running` |
| Instance type | `t3.medium` |
| Private IP | `172.31.29.109` |
| Public IP | `34.224.216.112` |

Local tunnel:

```text
127.0.0.1:5000 listener active
http://127.0.0.1:5000/health -> 200 OK
```

Access note:

- MLflow is not public.
- Browser access depends on an SSM port-forward tunnel.
- The verified command is:

```powershell
aws ssm start-session `
  --region us-east-1 `
  --target i-012f869a03d7247fa `
  --document-name AWS-StartPortForwardingSession `
  --parameters portNumber=5000,localPortNumber=5000
```

Observed experiments:

| experiment_id | name | artifact_location |
|---:|---|---|
| 0 | `Default` | `s3://leviathan-dev-shahem-001/mlflow/artifacts/0` |
| 1 | `leviathan-tier1-production` | `s3://leviathan-dev-shahem-001/mlflow/artifacts/1` |
| 2 | `leviathan-phase6-feature-set-smoke` | `s3://leviathan-dev-shahem-001/mlflow/artifacts/2` |

Observed run rows:

| experiment | observed runs | notes |
|---|---:|---|
| `leviathan-phase6-feature-set-smoke` | 2 | older feature-set smoke runs |
| `leviathan-tier1-production` | 3 | includes Phase 10 model-ready smoke runs |
| `Default` | 1 | row exists, sparse/blank metadata in REST table |

Known certified Phase 10 run from checked-in completion report:

```text
run_id: c57a0563b725439ea96f7a96b668e8c0
experiment: leviathan-tier1-production
commodity: corn_cbot
dataset_key: annual_physical_anomaly
target_key: production_anomaly_pct
model: xgboost
status: FINISHED
logged_model_id: m-9ea72ff48fef4bb581b14d9696ab3b54
prediction output: s3://leviathan-dev-shahem-001/silver/model_predictions/model_family=tier1_production/prediction_date=2026-06-26/corn_cbot__preseason_physical__annual_physical_anomaly__production_anomaly_pct__xgboost.parquet
```

Phase 0 interpretation:

- MLflow is operational and reachable through the tunnel.
- Current experiments are still legacy naming oriented:
  `leviathan-tier1-production`.
- No PSD-first experiment namespace exists yet.
- Run metadata is sufficient for current Phase 10 certification but will need
  PSD-specific tags in Phase 6 of the restructuring.

## Dataset Registry Inventory

Observed file:

```text
configs/datasets/datasets.yaml
```

Relevant registered derived datasets:

| dataset_key | layer | grain | Athena table |
|---|---|---|---|
| `gold_feature_spine_versions` | gold | dataset_version x commodity x country x crop_year x feature | `gold_feature_spine_versions` |
| `gold_feature_matrix_versions` | gold | dataset_version x commodity x country x crop_year | none |
| `gold_feature_catalog_versions` | gold | dataset_version x feature | `gold_feature_catalog_versions` |
| `gold_feature_set_versions` | gold | dataset_version x feature_set_id x feature | `gold_feature_set_versions` |
| `gold_model_ready_targets` | gold | dataset_version x dataset_key x commodity x country x crop_year x target_key | `gold_model_ready_targets` |
| `gold_model_ready_matrices` | gold | dataset_version x dataset_key x commodity x target_key x country x crop_year | none |
| `gold_model_ready_baselines` | gold | dataset_version x dataset_key x commodity x target_key x baseline_name | `gold_model_ready_baselines` |
| `gold_model_ready_manifests` | gold | dataset_version | none |

Observed source contracts:

```text
configs/datasets/source_contracts.yaml
```

Important source keys:

- `production:faostat`
- `psd`
- `wasde`
- `wap_revisions`
- NASS, ESR, FGIS, SAGIS, UNICA, weather, macro, COT, futures, and other
  feature sources.

## Current Research Surfaces

The current safe research surface is:

```text
silver/*
  -> gold/feature_spine_versions/dataset_version=20260626T010217Z_6725de02_phase7_full
  -> gold/feature_matrix_versions/dataset_version=20260626T010217Z_6725de02_phase7_full
  -> gold/feature_catalog_versions/dataset_version=20260626T010217Z_6725de02_phase7_full
  -> gold/feature_set_versions/dataset_version=20260626T010217Z_6725de02_phase7_full
  -> gold/model_ready_* /dataset_version=20260626T104732Z_a2576e84_phase8_model_ready
  -> MLflow experiment leviathan-tier1-production
```

This is experiment-ready for the legacy annual physical anomaly target family,
not yet for the PSD-first target family.

## Risks And Warnings

1. Target naming can mislead researchers.

   `production_anomaly_pct` does not say that its current label source is
   FAOSTAT. The feature catalog has the source truth, but the model-ready target
   table and MLflow run naming do not make it obvious.

2. PSD is present but not yet the target source.

   `silver/psd` is broad and model-relevant, but current model-ready target
   creation reads label columns from the gold matrix.

3. Old smoke versions can be mistaken for active research surfaces.

   Several smoke or earlier phase versions remain in S3. They should be
   retained for now but later labeled or hidden from default readers.

4. Versioned Athena tables require explicit injected partition filters.

   This is normal for the current DDL design but can surprise users who use
   Athena Preview Table without `WHERE dataset_version = ...`.

5. MLflow names are legacy.

   `leviathan-tier1-production` and `model_family=tier1_production` are not
   wrong, but they will become ambiguous once PSD-first targets exist.

6. Default MLflow experiment has sparse metadata.

   There is one visible run row in `Default` with little useful context from
   the REST inventory. It should be ignored or inspected later, not deleted.

## Open Questions For Phase 1

Phase 1 should answer these with a stricter target-source truth audit:

1. For every current target, should the recommended status be `legacy`,
   `diagnostic`, or `deprecated_later`?
2. Should current `annual_physical_anomaly` remain runnable for historical
   baseline comparisons after PSD targets are implemented?
3. Should FAOSTAT current label rows be split into a separate legacy target
   config to make source provenance explicit?
4. Should model-ready target tables add `target_source`, `label_source`,
   `source_table`, `target_market_year`, and `target_release_context` columns?
5. Should old MLflow runs be left untouched or tagged through a separate
   inventory/annotation mechanism?

## Phase 0 Acceptance Check

| criterion | status |
|---|---|
| No production code changed | pass |
| No configs changed | pass |
| No S3 objects modified | pass |
| No Glue/Athena tables modified | pass |
| No model-ready datasets rebuilt | pass |
| Relevant repo files inventoried | pass |
| Relevant S3 prefixes inventoried | pass |
| Glue table and checked-in DDL names compared | pass |
| MLflow host and experiments inventoried | pass |
| Active versions documented | pass |

## Recommended Next Step

Proceed to Phase 1: Target-Source Truth Audit.

Phase 1 should produce a formal target-source truth table for:

- `production_anomaly_pct`
- `yield_anomaly_pct`
- `area_harvested_anomaly_pct`

It should prove their label source, cadence, year semantics, metadata gaps,
leakage risk, and recommended status before any PSD mapping config is added.
