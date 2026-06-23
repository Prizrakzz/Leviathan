# ML Platform Backup and Restore

## Backup

The backup command uses SSM and SQLite's online backup API. Services remain
running while consistent database copies are produced.

```powershell
.\.venv\Scripts\python.exe scripts\ops\backup_ml_platform.py `
  --instance-id i-012f869a03d7247fa `
  --bucket leviathan-dev-shahem-001 `
  --aws-region us-east-1 `
  --output data\ml_platform_backups\latest.json
```

Backups are immutable by convention:

```text
mlflow/backups/backend/{backup_id}/mlflow.db
mlflow/backups/backend/{backup_id}/manifest.json
airflow/backups/backend/{backup_id}/airflow.db
airflow/backups/backend/{backup_id}/manifest.json
```

Each manifest records source and backup integrity checks, SHA-256, size,
service status, version, and table counts.

## Non-destructive restore verification

Verification downloads the backup to a temporary path on the EC2 host, checks
its SHA-256 and SQLite integrity, reads table counts, and deletes the temporary
copy. It does not stop a service or modify a live database.

```powershell
.\.venv\Scripts\python.exe scripts\ops\restore_ml_platform.py `
  --service mlflow `
  --instance-id i-012f869a03d7247fa `
  --bucket leviathan-dev-shahem-001 `
  --backup-id 2026-06-23T12-00-00Z
```

Run the same command with `--service airflow`.

## Live restore

Live restoration is intentionally guarded:

```powershell
.\.venv\Scripts\python.exe scripts\ops\restore_ml_platform.py `
  --service mlflow `
  --instance-id i-012f869a03d7247fa `
  --bucket leviathan-dev-shahem-001 `
  --backup-id 2026-06-23T12-00-00Z `
  --apply `
  --confirm-service mlflow
```

The command:

1. Verifies the downloaded backup.
2. Stops the service.
3. Preserves the current database as a rollback copy.
4. Replaces the database atomically.
5. Restores ownership.
6. Restarts the service and checks health.
7. Rolls back automatically when post-restore validation fails.

Do not run `--apply` during routine verification.

