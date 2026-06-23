# MLflow and Airflow State Reconciliation

Status: Phase 0 complete

Verified: 2026-06-23

## Live state

- EC2 instance: `i-012f869a03d7247fa`
- Instance type: `t3.medium`
- Root volume: `vol-0f627d7d89a693b9b`, 10 GiB
- Security group: `sg-0987fe554fd12afe3`
- MLflow backend: `/home/ec2-user/mlflow/mlflow.db`
- Airflow backend: `/home/ec2-user/airflow/airflow.db`

The live SQLite databases remain on the EC2 root volume. Phase 0 protects and
backs up that state; it does not claim the final durable-backend migration is
complete.

## Terraform reconciliation

The module now adopts the live host instead of attempting to rebuild it:

- The current AMI and 10 GiB root-volume size are explicit dev inputs.
- AMI and bootstrap-script drift do not trigger instance replacement.
- `user_data_replace_on_change` is disabled.
- `prevent_destroy` protects the active EC2 instance.
- The security-group declaration matches the adopted live group.
- Airflow browser access remains through SSM port forwarding, so port 8080
  does not require inbound VPC access.

`terraform plan` on 2026-06-23 showed no action for:

- `module.mlflow_server.aws_instance.mlflow`
- `module.mlflow_server.aws_security_group.mlflow`
- the root EBS volume attached to the active host

The full repository plan still showed an unrelated replacement of the ECR
lifecycle-policy resource, plus unrelated Glue updates and creation of the
already-declared Airflow IAM policy. That plan was deliberately not applied.

## Recovery evidence

Backup ID: `2026-06-23T12-30-57Z`

- MLflow backup:
  `s3://leviathan-dev-shahem-001/mlflow/backups/backend/2026-06-23T12-30-57Z/`
- Airflow backup:
  `s3://leviathan-dev-shahem-001/airflow/backups/backend/2026-06-23T12-30-57Z/`

Both source databases and both uploaded backup copies returned
`PRAGMA integrity_check = ok`. Both backups also passed non-destructive restore
verification on the live host.

## Apply policy

Do not run an unrestricted apply merely because the MLflow replacement risk is
resolved. Review and approve the remaining non-MLflow actions separately.

The `prevent_destroy` safeguard should remain until Phase 9 migrates tracking
state to a backend whose lifetime is independent of the EC2 root volume.
