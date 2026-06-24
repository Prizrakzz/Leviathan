# Phase 1 Platform Repair Report

Status: Complete except Terraform drift verification, which is blocked by missing required dev variables.

Completed: 2026-06-24

## Scope

This report implements Phase 1 of the rebased MLflow experiment readiness plan: protect MLflow/Airflow state, repair active Glue catalog drift, and prove Athena can query the live structured tables needed by the plan. GraphRAG was not touched.

## Git State

- Branch: `codex/mlflow-readiness-phase2`
- Head: `e556fb5f6f08836a83bd84a772211f4e7b6bda64`
- Head commit: `Rewrite MLflow readiness plan around legacy gold`

The pre-existing uncommitted v2 scratch work was preserved in `C:\Users\User\Desktop\Leviathan-phase1\data\system_inventory\mlflow_phase1_20260624T161204Z` before live catalog work continued.

## MLflow And Airflow Backup

Backup ID: `2026-06-24T16-12-22Z`

- MLflow DB: `s3://leviathan-dev-shahem-001/mlflow/backups/backend/2026-06-24T16-12-22Z/mlflow.db`
- MLflow manifest: `s3://leviathan-dev-shahem-001/mlflow/backups/backend/2026-06-24T16-12-22Z/manifest.json`
- MLflow SHA-256: `2b153b9ab90bce4e7e79021db5048f63fc18e795b465d735a4800daed83a0934`
- Airflow DB: `s3://leviathan-dev-shahem-001/airflow/backups/backend/2026-06-24T16-12-22Z/airflow.db`
- Airflow manifest: `s3://leviathan-dev-shahem-001/airflow/backups/backend/2026-06-24T16-12-22Z/manifest.json`
- Airflow SHA-256: `ff2002b460b2a1b36fec47a76c366ac5685e2bd0d4570875b52634ce384b75e4`

Both backups passed non-destructive verify-only restore checks on the EC2 host with `PRAGMA integrity_check = ok`.

## Catalog Repair

The pre-apply catalog plan had these action counts:

```json
{
  "noop": 46,
  "create": 8,
  "replace": 1
}
```

Only the two active missing silver tables were applied:

- `silver_wasde`
- `silver_ams_cotton_quality`

The `gold_v2_*` tables were deferred because the rebased plan keeps `gold/feature_spine` as the MLflow path and treats v2 as a future PIT proof. The `silver_conab_coffee` replacement was not applied in this phase.

## Athena Smoke Results

- `silver_wasde` on `2026-05-12`: {'n': '600', 'commodities': '7', 'min_release_date': '2026-05-12', 'max_release_date': '2026-05-12'}
- `silver_wasde` on `1985-01-11`: {'n': '51', 'commodities': '1', 'min_release_date': '1985-01-11', 'max_release_date': '1985-01-11'}
- `silver_ams_cotton_quality`: {'n': '27', 'min_season': '1986', 'max_season': '2025', 'avg_percent_tenderable': '68.99629629629628'}
- `gold_feature_spine` for `corn_cbot`: {'n': '16863', 'features': '459', 'min_crop_year': '1981', 'max_crop_year': '2026'}
- `gold_training_windows`: {'n': '124'}

All smoke queries succeeded.

## Terraform

`terraform plan -detailed-exitcode` was attempted in `infra/terraform/envs/dev`, but Terraform requested values for required variables not present in this worktree:

- `bucket_name`
- `batch_subnet_ids`
- `batch_security_group_ids`

No Terraform apply was run. This remains the only Phase 1 blocker.

## Evidence

- `C:\Users\User\Desktop\Leviathan-phase1\data\system_inventory\mlflow_phase1_20260624T161204Z\phase1_report.json`
- `C:\Users\User\Desktop\Leviathan-phase1\data\system_inventory\mlflow_phase1_20260624T161204Z\catalog_plan_before_apply.json`
- `C:\Users\User\Desktop\Leviathan-phase1\data\system_inventory\mlflow_phase1_20260624T161204Z\ml_platform_backup.json`
- `C:\Users\User\Desktop\Leviathan-phase1\data\system_inventory\mlflow_phase1_20260624T161204Z\mlflow_restore_verify.json`
- `C:\Users\User\Desktop\Leviathan-phase1\data\system_inventory\mlflow_phase1_20260624T161204Z\airflow_restore_verify.json`
- `C:\Users\User\Desktop\Leviathan-phase1\data\system_inventory\mlflow_phase1_20260624T161204Z\terraform_plan_attempt.txt`

## Exit Criteria

- MLflow/Airflow state backed up: pass.
- Backup restore verification: pass.
- Active checked-in DDLs missing from Glue: repaired for the active silver tables.
- Athena validation: pass.
- Terraform replacement-safety check: blocked by missing dev variables.
