# Phase 9: Model-Ready MLflow Training

## Status

Phase 9 upgrades the training runner to consume Phase 8 model-ready datasets
directly. The code path is implemented and covered by focused unit tests. Runtime
Batch smoke still requires a fresh worker/trainer image containing this commit
and a new `leviathan-dev-train` job-definition revision.

## Implemented

- Added `leviathan.training.model_ready` to load:
  - `gold/model_ready_matrices`
  - `gold/model_ready_manifests`
  - `gold/model_ready_baselines`
  - `gold/feature_set_versions` from the inferred source gold dataset version
- Added leakage-safe feature selection for model-ready matrices.
  - Uses governed feature-set membership.
  - Excludes `label_*`, target columns, baseline columns, and matrix identity columns.
- Extended `jobs/batch/train_commodity.py`.
  - Legacy `gold/feature_matrix` mode remains available.
  - New model-ready mode is activated by `--model-dataset-version`.
  - Model-ready mode uses `target_value` as the label.
  - Model-ready mode refuses `--detrend`, because Phase 8 already materializes anomaly targets.
- Added model-ready MLflow provenance tags:
  - `model_dataset_version`
  - `source_gold_dataset_version`
  - `dataset_key`
  - `target_key`
  - `model_ready_manifest_uri`
  - `model_ready_matrix_uri`
  - `baseline_metrics_uri`
  - `target_config_sha`
- Added fold-aligned baseline comparisons in target space.
- Enriched prediction parquet outputs with model-ready identity columns.
- Updated `jobs/submit/submit_batch_train.py` for model-ready training grids.
- Updated `jobs/utils/register_train_jobdef.py` to register the new train CLI parameters.

## Primary Smoke Command

```powershell
python jobs/batch/train_commodity.py `
  --model-dataset-version 20260626T104732Z_a2576e84_phase8_model_ready `
  --dataset-key annual_physical_anomaly `
  --target-key production_anomaly_pct `
  --commodity corn_cbot `
  --feature-set preseason_physical `
  --model xgboost `
  --min-train-years 10
```

## Batch Smoke Submitter Shape

```powershell
python jobs/submit/submit_batch_train.py `
  --model-dataset-version 20260626T104732Z_a2576e84_phase8_model_ready `
  --commodities corn_cbot `
  --feature-sets preseason_physical `
  --dataset-keys annual_physical_anomaly `
  --target-keys production_anomaly_pct `
  --models xgboost
```

## Runtime To Do

1. Rebuild and push the trainer/worker image with this commit.
2. Register a new `leviathan-dev-train` job-definition revision:

```powershell
python jobs/utils/register_train_jobdef.py
```

3. Submit the one-job Batch smoke above.
4. Confirm:
   - MLflow run appears.
   - Baseline comparison metrics are present.
   - Model artifact logs successfully.
   - Prediction parquet writes to `silver/model_predictions/`.

## Next Phase

Phase 10 should orchestrate controlled experiment sweeps across commodities,
targets, feature sets, and model classes, then compare candidates against the
Phase 8 baselines before any production promotion.
