# Phase 1 Completion

Status: complete except Terraform drift verification, which is blocked by
missing required dev variables.

Completed: 2026-06-24

This record corresponds to Phase 1 of the rebased MLflow experiment readiness
plan. The old Phase 1 numbering from 2026-06-23 is superseded by
`docs/MLFLOW_EXPERIMENT_READINESS_PLAN.md`; older details remain available in
git history.

## Scope

Phase 1 protects the experiment platform and repairs active Glue catalog drift
before broader MLflow work continues.

GraphRAG was not touched.

## State Protection

Backup ID:

```text
2026-06-24T16-12-22Z
```

MLflow:

- database:
  `s3://leviathan-dev-shahem-001/mlflow/backups/backend/2026-06-24T16-12-22Z/mlflow.db`
- manifest:
  `s3://leviathan-dev-shahem-001/mlflow/backups/backend/2026-06-24T16-12-22Z/manifest.json`
- SHA-256:
  `2b153b9ab90bce4e7e79021db5048f63fc18e795b465d735a4800daed83a0934`
- service state: active
- version: MLflow 3.1.4
- table highlights: 2 experiments, 1 run, 32 metrics

Airflow:

- database:
  `s3://leviathan-dev-shahem-001/airflow/backups/backend/2026-06-24T16-12-22Z/airflow.db`
- manifest:
  `s3://leviathan-dev-shahem-001/airflow/backups/backend/2026-06-24T16-12-22Z/manifest.json`
- SHA-256:
  `ff2002b460b2a1b36fec47a76c366ac5685e2bd0d4570875b52634ce384b75e4`
- service state: webserver and scheduler active
- version: Airflow 2.9.3
- table highlights: 7 DAGs

Both backups passed non-destructive verify-only restore checks on the EC2 host
with `PRAGMA integrity_check = ok`.

## Scratch Preservation

The pre-existing uncommitted `gold_v2` scratch work was preserved before live
catalog work continued.

Evidence folder:

```text
data/system_inventory/mlflow_phase1_20260624T161204Z/
```

Preserved files:

- `scratch_preservation_manifest.json`
- `uncommitted_tracked_changes.patch`
- `untracked_files.txt`
- `untracked_files.zip`

## Catalog Reconciliation

The reviewed pre-apply catalog plan had:

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

The `gold_v2_*` tables were deferred because the rebased plan keeps
`gold/feature_spine` as the MLflow path and treats v2 as a future
point-in-time proof. The `silver_conab_coffee` replacement was intentionally
not applied in this phase.

DDL application succeeded through Athena:

- `silver_wasde`:
  `6ae8386f-5ab5-4fee-9fc8-816eb877b69b`
- `silver_ams_cotton_quality`:
  `c7ba88e2-7c00-4374-8a4a-62952a77b366`

Glue now contains both repaired tables:

- `silver_wasde` at
  `s3://leviathan-dev-shahem-001/silver/wasde`
- `silver_ams_cotton_quality` at
  `s3://leviathan-dev-shahem-001/silver/ams_cotton_quality`

## Athena Smoke

All smoke queries succeeded.

| Query | Result |
| --- | --- |
| `silver_wasde` on `2026-05-12` | 600 rows, 7 commodities |
| `silver_wasde` on `1985-01-11` | 51 rows, 1 commodity |
| `silver_ams_cotton_quality` | 27 rows, seasons 1986-2025, average tenderable 68.9963 |
| `gold_feature_spine` for `corn_cbot` | 16,863 rows, 459 features, crop years 1981-2026 |
| `gold_training_windows` | 124 rows |

## Terraform

`terraform plan -detailed-exitcode` was attempted in
`infra/terraform/envs/dev`, but Terraform required values that are not present
in this worktree:

- `bucket_name`
- `batch_subnet_ids`
- `batch_security_group_ids`

No Terraform apply was run. The EC2 replacement-safety check remains blocked
until the approved dev variable values or tfvars file are available.

## Evidence

- `data/system_inventory/mlflow_phase1_20260624T161204Z/phase1_report.json`
- `data/system_inventory/mlflow_phase1_20260624T161204Z/phase1_report.md`
- `data/system_inventory/mlflow_phase1_20260624T161204Z/catalog_plan_before_apply.json`
- `data/system_inventory/mlflow_phase1_20260624T161204Z/ml_platform_backup.json`
- `data/system_inventory/mlflow_phase1_20260624T161204Z/mlflow_restore_verify.json`
- `data/system_inventory/mlflow_phase1_20260624T161204Z/airflow_restore_verify.json`
- `data/system_inventory/mlflow_phase1_20260624T161204Z/terraform_plan_attempt.txt`

## Exit Criteria

- MLflow/Airflow state backed up: pass.
- Backup restore verification: pass.
- Active checked-in DDLs missing from Glue: repaired.
- Athena validation: pass.
- Terraform replacement-safety check: blocked by missing dev variables.
