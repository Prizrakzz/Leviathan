# Phase 10: MLflow Experiment Readiness Certification

## Status

Phase 10 is implemented and smoke-certified for the non-Airflow path. Airflow
orchestration is intentionally deferred.

The certified smoke run proves that a model-ready dataset can train through AWS
Batch, log a fitted MLflow model, produce UI-reviewable artifacts, write
prediction output to S3, and replay predictions from the logged model artifact.

## Implemented

- Added MLflow run-completeness artifacts to `jobs/batch/train_commodity.py`.
  - Fitted final model logging through the matching MLflow flavor.
  - Model signature and input example where supported by MLflow.
  - Compact MLflow tables for CV predictions, folds, slices, baselines, gaps,
    selected features, replay sample, and feature importance.
  - Per-fold stepped metrics keyed by test year.
  - `logs/training.log` and metadata JSON artifacts.
- Added replay verification:
  - `src/leviathan/training/mlflow_replay.py`
  - `scripts/mlflow/verify_run_replay.py`
- Added Phase 10 readiness certification:
  - `scripts/certification/certify_phase10_readiness.py`
- Added MLflow UI tunnel runbook and helper:
  - `docs/ops/MLFLOW_UI_ACCESS.md`
  - `scripts/ops/start_mlflow_tunnel.ps1`
- Deferred Airflow DAG implementation.

## Runtime Rollout

Trainer image rebuilt and pushed:

```text
668891723125.dkr.ecr.us-east-1.amazonaws.com/leviathan-dev-leviathan-trainer:latest
668891723125.dkr.ecr.us-east-1.amazonaws.com/leviathan-dev-leviathan-trainer:phase10-20260626214019
digest: sha256:5424b72e129727b6d00784ec7da657080ab2d9143343d0c160e2c3b88da9c14f
```

Batch job definition:

```text
arn:aws:batch:us-east-1:668891723125:job-definition/leviathan-dev-train:6
```

Smoke job:

```text
job_name: train-corn-cbot-preseason-physical-annual-physical-anomaly-production-anomaly-pct-xgboost
job_id: 3f1193c3-f917-4556-881c-51cfa7ecda3f
status: SUCCEEDED
exit_code: 0
log_stream: leviathan-dev-train/default/9fca112fece94468a29ebdfcf609d18d
mlflow_run_id: c57a0563b725439ea96f7a96b668e8c0
logged_model_id: m-9ea72ff48fef4bb581b14d9696ab3b54
```

Smoke metrics:

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

## Certification

Replay verification:

```text
status: pass
run_id: c57a0563b725439ea96f7a96b668e8c0
n_rows: 145
max_abs_error: 0.0
mean_abs_error: 0.0
model_uri: runs:/c57a0563b725439ea96f7a96b668e8c0/model
```

Readiness certification:

```text
status: pass
failed_check_count: 0
```

Local evidence files:

```text
data/system_inventory/phase10_replay_c57a0563.json
data/system_inventory/phase10_readiness_c57a0563.json
```

## Validation

Focused tests passed:

```text
python -m pytest tests/unit/test_training_mlflow_artifacts.py tests/unit/test_training_tracking.py tests/unit/test_training_model_ready.py tests/unit/test_model_ready_datasets.py tests/unit/test_training_slices.py tests/unit/test_batch_submit.py tests/unit/test_experiment_baseline.py

32 passed
```

Syntax checks passed for the new trainer/replay/certification modules.

The full test suite was also run. Non-GraphRAG tests passed, but the suite has
existing GraphRAG failures in this worktree because `configs/graphrag/*` files
are absent here. GraphRAG was intentionally left untouched.

## Notes

- MLflow 3 stores the fitted model in the logged-model namespace while keeping
  `runs:/<run_id>/model` loading compatibility. The certifier accepts either a
  run artifact model directory or a logged model named `model`.
- The lean trainer image still emits non-fatal warnings because `git` is not
  installed. Leviathan-specific dataset and feature provenance tags are present.
- MLflow UI access remains through SSM port forwarding, not a public port.

## Next Phase

Proceed to controlled experiment portfolio execution: run small, versioned
model sweeps across selected commodities, targets, feature sets, and model
classes, then choose research champions from MLflow evidence.
