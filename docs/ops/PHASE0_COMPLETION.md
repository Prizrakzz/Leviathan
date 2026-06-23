# Phase 0 Completion Record

Status: Complete

Completed: 2026-06-23

## State protection

Backup ID: `2026-06-23T12-30-57Z`

MLflow and Airflow SQLite databases were backed up with SQLite's online backup
API. Source databases and uploaded copies returned
`PRAGMA integrity_check = ok`.

- MLflow:
  `s3://leviathan-dev-shahem-001/mlflow/backups/backend/2026-06-23T12-30-57Z/`
- Airflow:
  `s3://leviathan-dev-shahem-001/airflow/backups/backend/2026-06-23T12-30-57Z/`

Both backups passed non-destructive restore verification on the EC2 host.

## Infrastructure protection

Terraform now adopts the active `t3.medium` host and its 10 GiB root volume.
The EC2 resource has `prevent_destroy`; AMI and bootstrap drift no longer
schedule replacement.

The 2026-06-23 full Terraform plan contained no action for the active MLflow
EC2 instance, its security group, or its root volume. The plan still contained
unrelated ECR lifecycle, Glue, and Airflow-IAM actions, so it was not applied.
A narrow verification plan for `module.mlflow_server` reported:
`2 to add, 0 to change, 0 to destroy`; both additions are Airflow IAM
resources.

See `docs/ops/MLFLOW_AIRFLOW_STATE_RECONCILIATION.md`.

## System inventory

The snapshot covers 140 logical datasets and the live Glue, Batch, ECR, EC2,
and EBS state.

- JSON:
  `s3://leviathan-dev-shahem-001/metadata/system_inventory/as_of_date=2026-06-23/run_id=2026-06-23T13-39-14Z/inventory.json`
- Parquet:
  `s3://leviathan-dev-shahem-001/metadata/system_inventory/as_of_date=2026-06-23/run_id=2026-06-23T13-39-14Z/inventory_datasets.parquet`
- Logical content SHA-256:
  `645a761fe62da0c8e039ed7775de7eea018597bbabbbfe7f21e3dff0129676a7`

Two independently captured inventories recomputed to this same logical hash.
CloudWatch observation timestamps are retained in the JSON but excluded from
the logical-state hash.

## Experiment baseline

The initial corn XGBoost run is frozen at:

```text
s3://leviathan-dev-shahem-001/model_artifacts/experiment_baselines/
baseline_id=corn-initial-xgboost-20260617/
```

The baseline includes MLflow metadata, predictions, and the training snapshot.
Its record SHA-256 is:

```text
ace8cf7f026bd518fe385028a288b8e56b884a7249541b2c2dc388c9f62ee9b4
```

The record explicitly marks the run as an engineering baseline, not a
production candidate.

## Verification

- Phase 0 unit tests: 19 passed.
- Complete repository suite: 1,040 passed.
- `terraform validate`: passed.
- `git diff --check`: passed; only existing Windows line-ending warnings were
  reported.

The local virtual environment now has the repository-declared `training`
optional dependency group installed for subsequent MLflow experimentation.

## Remaining safeguard

Phase 0 makes the current SQLite-backed system recoverable; it does not make
SQLite on an EC2 root volume the final architecture. Keep backups,
`prevent_destroy`, and the no-unreviewed-apply rule until Phase 9 moves MLflow
and Airflow state to durable backends.
