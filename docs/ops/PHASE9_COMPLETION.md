# Phase 9: Model-Ready MLflow Training

## Status

Phase 9 upgrades the training runner to consume Phase 8 model-ready datasets
directly. The code path is implemented, covered by focused unit tests, deployed
to the trainer ECR image, registered in AWS Batch, and smoke-tested successfully.

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

## Runtime Rollout

Trainer image pushed:

```text
668891723125.dkr.ecr.us-east-1.amazonaws.com/leviathan-dev-leviathan-trainer:latest
668891723125.dkr.ecr.us-east-1.amazonaws.com/leviathan-dev-leviathan-trainer:737818a1
digest: sha256:b5a1fd7234f0ab2122ea211ee522315979137be48eaef915bcaf070acc8b2fa7
compressed size: 343,778,471 bytes
```

Batch job definition:

```text
arn:aws:batch:us-east-1:668891723125:job-definition/leviathan-dev-train:5
```

Smoke job:

```text
job_name: train-corn-cbot-preseason-physical-annual-physical-anomaly-production-anomaly-pct-xgboost
job_id: 8412bd1d-ab7e-4644-b7bc-dc377f617c59
status: SUCCEEDED
exit_code: 0
log_stream: leviathan-dev-train/default/44104b5692aa44b3931a98045ea4f100
mlflow_run_id: ba92f81e348d4069ba4367b2e44dffe5
```

Smoke log summary:

```text
rmse=0.3332
directional_accuracy=0.6580459770114943
quintile_directional_accuracy=0.783
gaps_passed=False
folds=29
```

Prediction output:

```text
s3://leviathan-dev-shahem-001/silver/model_predictions/model_family=tier1_production/prediction_date=2026-06-26/corn_cbot__preseason_physical__annual_physical_anomaly__production_anomaly_pct__xgboost.parquet
```

Operational note: the container emitted non-fatal MLflow warnings because `git`
is not installed in the lean trainer image. The run succeeded and Leviathan's
own dataset/model provenance tags were logged by the trainer.

## Next Phase

Phase 10 should orchestrate controlled experiment sweeps across commodities,
targets, feature sets, and model classes, then compare candidates against the
Phase 8 baselines before any production promotion.
