# ML Platform Phase 0 Change Freeze

Status: Phase 0 complete. Destructive replacement safeguards remain active
until the durable-backend migration in Phase 9.

## Protected live resources

- EC2 instance: `i-012f869a03d7247fa`
- MLflow SQLite: `/home/ec2-user/mlflow/mlflow.db`
- Airflow SQLite: `/home/ec2-user/airflow/airflow.db`
- Root EBS volume: `vol-0f627d7d89a693b9b`
- Security group: `sg-0987fe554fd12afe3`
- MLflow S3 artifact root:
  `s3://leviathan-dev-shahem-001/mlflow/artifacts/`

The exact current values are also captured by the Phase 0 system inventory.

## Temporarily prohibited operations

- Terminating or replacing the MLflow EC2 instance.
- Deleting or recreating its root volume.
- Running an unrestricted Terraform apply while the plan replaces the instance,
  volume, or security group.
- Migrating either SQLite database without a verified backup and restore
  rehearsal.
- Deleting or overwriting a timestamped backend backup.
- Deleting or overwriting the frozen initial MLflow baseline.
- Launching broad experiment sweeps before the current baseline is frozen.

## Permitted operations

- Read-only AWS inspection.
- SSM Run Command for backup and verification.
- SQLite online backups.
- Timestamped S3 uploads.
- Terraform refresh-only state reconciliation.
- Terraform planning.
- Repository tests and documentation updates.

## Release condition

The freeze may be lifted when:

1. Both SQLite stores have checksummed backups.
2. Both backups pass a non-destructive restore verification.
3. Terraform no longer plans replacement of the active ML platform.
4. The system inventory and initial experiment baseline are stored in S3.
