# Phase 6 Completion

Status: complete.

Completed: 2026-06-27

## Scope

Phase 6 made PSD-first model experiments operational in AWS Batch and MLflow:

- configurable walk-forward CV policies for expanding and rolling windows;
- Batch submitter fan-out over CV policies;
- PSD target metadata propagated into MLflow tags and model-version tags;
- optional MLflow model registration with safe default model names;
- trainer image and live MLflow server upgraded to MLflow 3.14.0.

GraphRAG was not touched.

## Code Changes

Training CV:

```text
src/leviathan/training/cv.py
tests/unit/test_training_cv.py
```

Training runner, submitter, and Batch job definition helper:

```text
jobs/batch/train_commodity.py
jobs/submit/submit_batch_train.py
jobs/utils/register_train_jobdef.py
tests/unit/test_training_model_ready.py
```

MLflow artifact/model logging:

```text
src/leviathan/training/mlflow_artifacts.py
```

Runtime dependencies:

```text
pyproject.toml
docker/leviathan_trainer/Dockerfile
```

## CV Policies

The trainer now supports:

```text
expanding_full_history
expanding_post_1990
expanding_post_2000
rolling_25y
rolling_30y
```

Default behavior remains `expanding_full_history`, so legacy calls keep the same expanding-window behavior unless a new policy is requested.

## MLflow

The MLflow EC2 service was backed up, restored into a scratch copy for verification, and then upgraded:

```text
instance_id: i-012f869a03d7247fa
service: /etc/systemd/system/mlflow.service
venv: /opt/mlflow-venv-3.14.0
version: mlflow 3.14.0
health: http://localhost:5000/health -> OK
```

Backend backup:

```text
s3://leviathan-dev-shahem-001/mlflow/backups/backend/phase6-mlflow-2026-06-27T14-00-28Z/mlflow.db
s3://leviathan-dev-shahem-001/mlflow/backups/backend/phase6-mlflow-2026-06-27T14-00-28Z/manifest.json
```

Model registration is opt-in through:

```text
--register-model true
--registered-model-name optional
```

If no registered model name is supplied, the trainer uses:

```text
leviathan.{commodity}.{target_key}.{model}
```

Example:

```text
leviathan.corn_cbot.psd_production_anomaly_pct.lightgbm
```

The trainer stores PSD/CV/data tags on both the MLflow run and the registered model version.

## Runtime Image

Final pushed trainer image:

```text
repository: 668891723125.dkr.ecr.us-east-1.amazonaws.com/leviathan-dev-leviathan-trainer
tag: phase6-regtags-20260627152703
digest: sha256:e1d57cecb0ae540366309cf4c7245890f16d97a9a623a74f840c70b0d810d051
latest: same digest
```

Live Batch job definition:

```text
leviathan-dev-train:7
```

The job definition references the `latest` trainer tag and includes the new CV and registration parameters.

## Smoke Runs

Initial smoke exposed an MLflow 3.14 LightGBM dependency issue:

```text
job_id: db09754a-8ddb-40f1-ba0d-6a0af6a84782
result: failed
cause: MLflow 3.14 attempted skops serialization; trainer image intentionally does not include skops
fix: force cloudpickle serialization for logged models
```

No-registration smoke:

```text
job_id: d205c245-2006-445c-ba08-bc5158d4997e
run_id: 2af290c1ddab42aeb3a7ee33a6d38d25
experiment: leviathan-psd-phase6-smoke
status: succeeded
model_registered: false
```

Registration smoke before model-version tag fix:

```text
job_id: 5b9dea64-2d09-4df4-8cb5-52a1c3810ddd
run_id: ad6263ea89d84b87ab32a07ab1eb0ec0
registered_model: leviathan.corn_cbot.psd_production_anomaly_pct.lightgbm
version: 1
status: succeeded
note: model version was created, but version-level tags were empty
```

Final registration smoke:

```text
job_id: 4fb26284-ac61-427b-be85-2b88bc1bddd3
run_id: 6c702fdcc76a4ae39d325d1c621dce6e
registered_model: leviathan.corn_cbot.psd_production_anomaly_pct.lightgbm
version: 2
status: succeeded
```

Version 2 tags verified in MLflow:

```text
commodity=corn_cbot
model=lightgbm
target_key=psd_production_anomaly_pct
dataset_key=psd_snd_anomaly
feature_set_id=preseason_physical
cv_policy=expanding_full_history
model_dataset_version=20260627T121215Z_phase5_psd_smoke
source_gold_dataset_version=20260626T010217Z_6725de02_phase7_full
target_source=psd
target_family=psd_production_anomaly
target_attribute=production_mt
psd_mapping_sha=f2d987f3014f7964d8041dc3d8e1157a9aa5b62597b7bda575c6d0d81fd7477a
```

Prediction output from the successful no-registration smoke:

```text
s3://leviathan-dev-shahem-001/silver/model_predictions/model_family=psd_production_anomaly/prediction_date=2026-06-27/corn_cbot__preseason_physical__psd_snd_anomaly__psd_production_anomaly_pct__lightgbm.parquet
```

## Validation

Focused tests:

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests\unit\test_training_cv.py `
  tests\unit\test_training_mlflow_artifacts.py `
  tests\unit\test_training_model_ready.py `
  tests\unit\test_model_ready_psd_datasets.py `
  tests\unit\test_model_datasets_psd_targets.py `
  tests\unit\test_psd_target_mapping.py
```

Result:

```text
39 passed
```

## Known Notes

- Batch logs still show a Git executable warning from MLflow because the slim trainer image does not include Git. This is non-fatal; run tags still carry explicit dataset and config fingerprints.
- LightGBM model logging intentionally uses `cloudpickle` because the lean trainer image excludes `skops`.
- No model alias or Production stage was assigned in this phase. Registration creates candidate model versions; promotion remains a later explicit decision.

## Next

Phase 6 is complete. Next is the PSD monthly-vintage enhancement: use monthly PSD release history for revision-aware features and targets where it improves research value, without replacing the annual PSD target architecture until the monthly mapping is verified.
