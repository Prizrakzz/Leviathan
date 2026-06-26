# Phase 8 Completion: Model-Ready Annual Anomaly Datasets

Code completed: 2026-06-26
Runtime completed: 2026-06-26

## Scope

Phase 8 created an explicit model-ready dataset layer on top of the validated
Phase 7 gold surface.  The first implemented target family is
`annual_physical_anomaly`, because final production/yield/area levels are mostly
trend and scale.  The ML target is now the residual surprise versus a trailing
expectation.

No GraphRAG files were touched.

## Source Gold Version

```text
20260626T010217Z_6725de02_phase7_full
```

## Model-Ready Version

```text
20260626T104732Z_a2576e84_phase8_model_ready
```

## Implemented Targets

Config:

```text
configs/ml/target_definitions.yaml
```

Implemented target keys:

- `production_anomaly_pct`
- `yield_anomaly_pct`
- `area_harvested_anomaly_pct`

Target construction:

```text
target_value = actual / trailing_linear_trend_prediction - 1
```

Every baseline and trend prediction uses only years strictly before the target
crop year.

## Outputs

Validated S3 outputs for `20260626T104732Z_a2576e84_phase8_model_ready`:

- `gold/model_ready_targets/...`: 31 Parquet target-table objects
- `gold/model_ready_matrices/...`: 83 target-specific wide matrix objects
- `gold/model_ready_baselines/.../baseline_metrics.parquet`: present
- `gold/model_ready_manifests/.../manifest.json`: present

Manifest summary:

```text
requested_commodity_count: 31
processed_commodity_count: 31
skipped_commodity_count: 0
failed_commodity_count: 0
built_target_count: 83
matrix_count: 83
target_row_count: 11,822
baseline_metric_count: 332
```

Example validation for `corn_cbot`:

```text
target table rows: 552
trainable rows: 435
target keys:
  - area_harvested_anomaly_pct
  - production_anomaly_pct
  - yield_anomaly_pct
production anomaly matrix shape: 184 x 479
label columns in model-ready matrix: 0
```

## Added Code

- `src/leviathan/model_datasets/targets.py`
- `src/leviathan/model_datasets/baselines.py`
- `src/leviathan/model_datasets/builder.py`
- `jobs/batch/build_model_ready_datasets.py`
- `jobs/submit/submit_batch_model_ready_datasets.py`

## Added Storage Contracts

- `gold_model_ready_targets`
- `gold_model_ready_matrices`
- `gold_model_ready_baselines`
- `gold_model_ready_manifests`

Athena DDLs:

- `sql/athena/ddl/gold_model_ready_targets.sql`
- `sql/athena/ddl/gold_model_ready_baselines.sql`

The wide model-ready matrices are not given a stable Athena DDL because their
feature columns vary by dataset version, target, and commodity. They are MLflow
training artifacts.

## Tests

Passed:

```powershell
$env:PYTHONPATH='C:\Users\User\Desktop\Leviathan-main-publish\src;C:\Users\User\Desktop\Leviathan-main-publish'
C:\Users\User\Desktop\Leviathan\.venv\Scripts\python.exe -m pytest `
  tests\unit\test_model_ready_datasets.py `
  tests\unit\test_storage_paths.py `
  tests\unit\test_features_feature_sets.py
```

Result:

```text
50 passed
```

## Operational Notes

- The model-ready dataset was built directly from committed local code against
  S3. This is cheap because it reads only versioned wide matrices, not raw
  weather partitions.
- The worker image was rebuilt and pushed after Phase 8 code landed:

```text
668891723125.dkr.ecr.us-east-1.amazonaws.com/leviathan-dev-leviathan-worker:38ffa8b3
668891723125.dkr.ecr.us-east-1.amazonaws.com/leviathan-dev-leviathan-worker:latest
digest: sha256:8471aa8083f845ed2bcf0a0fca0b7e37884caa1785a4fd11bae51d52b0f245cd
```

- Terraform v1.9.8 was used locally to initialize and validate the dev config.
  Validation passed after building the expected local Glue wheel artifact:

```text
dist/leviathan-0.1.0-py3-none-any.whl
```

- A normal Terraform apply was intentionally not run from this checkout because
  there is no Terraform state file or backend configuration present. Applying
  from empty state would risk recreating unrelated infrastructure. The Terraform
  job definition remains committed in code, and the single new Batch job
  definition was registered directly through AWS Batch instead.

Registered Batch job definition:

```text
arn:aws:batch:us-east-1:668891723125:job-definition/leviathan-dev-model-ready-datasets:1
```

Batch smoke version:

```text
20260626T110249Z_38ffa8b3_phase8_batch_smoke
```

Batch smoke job:

```text
job_id: f091de8e-fdc9-485e-9a40-14d7703b0ff9
status: SUCCEEDED
exit_code: 0
log_stream: model-ready-datasets/default/85254b128a744567b98da3d71c26be9b
```

Smoke validation:

```text
commodity: corn_cbot
target_key: production_anomaly_pct
target rows: 184
trainable rows: 145
matrix shape: 184 x 479
label columns in model-ready matrix: 0
baseline metric rows: 4
```

## Next Phase

Phase 9 should update the training runner to consume
`gold/model_ready_matrices` directly, compare every trained model against the
materialized baselines, and log the model-ready dataset manifest URI to MLflow.
