# Phase 8 PSD Acceptance Completion

Date: 2026-06-27

## Objective

Prove the PSD-first model-ready path is safe enough to use for controlled
experiments:

```text
gold feature matrix
-> PSD model-ready matrices
-> governed feature sets
-> walk-forward CV / MLflow artifacts
-> Batch dry-run experiment grid
```

No S3 objects were deleted, moved, or overwritten.

## Active Dataset Checked

```text
model_dataset_version=20260627T121215Z_phase5_psd_smoke
source_gold_dataset_version=20260626T010217Z_6725de02_phase7_full
dataset_key=psd_snd_anomaly
target_source=psd
```

Read-only S3 checks:

```text
s3://leviathan-dev-shahem-001/gold/model_ready_manifests/dataset_version=20260627T121215Z_phase5_psd_smoke/manifest.json
  present, 54,299 bytes

s3://leviathan-dev-shahem-001/gold/model_ready_baselines/dataset_version=20260627T121215Z_phase5_psd_smoke/baseline_metrics.parquet
  present, 7,274 bytes

s3://leviathan-dev-shahem-001/gold/model_ready_matrices/dataset_version=20260627T121215Z_phase5_psd_smoke/
  24 parquet matrices, 8,021,472 bytes
```

Manifest summary observed:

```text
requested_commodity_count=4
processed_commodity_count=4
failed_commodity_count=0
built_target_count=24
target_row_count=3810
matrix_count=24
baseline_metric_count=96
```

## Regression Coverage Added

- Snapshot model-ready matrices now prove explicit `as_of_date` snapshots use
  only PSD releases visible by that date.
- Snapshot model-ready matrices now prove future PSD revisions do not alter
  earlier named snapshot features.
- Governed feature-set tests now include an explicit `excluded_market_signal`
  fixture and prove it enters no model-purpose feature set.
- MLflow artifact tests now run a local SQLite-backed smoke and verify the
  review bundle contains:
  - `metadata/training_summary.json`
  - `metadata/selected_features.json`
  - `tables/cv_predictions.parquet`
  - `tables/fold_metrics.parquet`
  - `tables/model_replay_sample.parquet`
  - `logs/training.log`

## Batch Dry-Run

Command shape checked without submitting jobs:

```powershell
.\.venv\Scripts\python.exe jobs\submit\submit_batch_train.py `
  --commodities corn_cbot `
  --feature-sets preseason_physical,psd_monthly_vintage_features `
  --model-dataset-version latest `
  --target-source psd `
  --dataset-keys psd_snd_anomaly `
  --target-keys psd_production_anomaly_pct `
  --models xgboost,lightgbm `
  --dry-run
```

Result:

```text
latest resolved to 20260627T121215Z_phase5_psd_smoke
4 training tasks generated
0 Batch jobs submitted
```

## Tests

Focused Phase 8 gate:

```text
57 passed
```

Covered files:

```text
tests/unit/test_model_datasets_psd_targets.py
tests/unit/test_model_ready_psd_datasets.py
tests/unit/test_psd_vintage_features.py
tests/unit/test_features_feature_sets.py
tests/unit/test_training_model_ready.py
tests/unit/test_batch_submit.py
tests/unit/test_training_mlflow_artifacts.py
```

Full suite:

```text
1276 passed
```

## Acceptance Status

Phase 8 is accepted.  The PSD-first target path has focused acceptance coverage,
the active S3 model-ready surface passes read-only contract checks, the Batch
experiment grid dry-run resolves to the PSD default, and the full test suite
passes.

## Next

Phase 9 should run the first controlled PSD-first experiment sweep:

- commodity: `corn_cbot`
- dataset: `psd_snd_anomaly`
- target: `psd_production_anomaly_pct`
- feature sets: start with `preseason_physical` and
  `psd_monthly_vintage_features`
- models: `xgboost`, `lightgbm`
- execution: AWS Batch, not laptop compute
