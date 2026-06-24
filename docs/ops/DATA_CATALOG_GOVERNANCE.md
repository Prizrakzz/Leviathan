# Data Catalog Governance

`configs/datasets/datasets.yaml` is the authoritative registry for structured
datasets used by Leviathan research and model validation. Athena DDL files are
generated artifacts. Do not hand-edit files under `sql/athena/ddl`.

## Registry Contract

Every dataset declares:

- physical S3 prefix and file format;
- schema, natural key, and partition keys;
- owning transform and runtime task;
- timestamps, freshness, and historical range;
- model role and core-fundamental eligibility;
- Athena location, projection, and bounded smoke query.

The loader rejects duplicate IDs, duplicate tables, invalid natural keys,
duplicate prefixes, malformed projection settings, and unsupported types.

## Change Workflow

Generate and test repository DDLs:

```powershell
$env:PYTHONPATH = "$PWD\src"
python scripts/catalog/generate_ddls.py
python -m pytest tests/unit/test_dataset_registry.py `
  tests/unit/test_catalog_ddl.py tests/unit/test_catalog_reconcile.py
```

Create a read-only reconciliation plan:

```powershell
python scripts/catalog/plan_catalog.py `
  --output data/catalog_reconciliation/catalog-plan.json
```

Before any live mutation, back up Glue locally and to S3:

```powershell
python scripts/catalog/backup_catalog.py `
  --output data/catalog_reconciliation/glue-backup.json --upload
```

Apply only the reviewed immutable plan:

```powershell
python scripts/catalog/apply_catalog.py `
  --plan data/catalog_reconciliation/catalog-plan.json `
  --confirm-plan-sha <reviewed-sha> `
  --allow-retire
```

`--allow-retire` is required when the plan contains an explicitly registered
legacy-table retirement. The apply command never mutates or deletes S3 data.

Validate Glue, bounded Parquet footer schemas, and Athena:

```powershell
python scripts/catalog/validate_catalog.py --max-parquet-files 3
python scripts/catalog/validate_catalog.py --skip-parquet --run-athena
```

The schema probe reads Parquet footers with S3 range requests. It does not
download full data files or enumerate the whole bucket.

## Safety Rules

- A registry change must regenerate every DDL deterministically.
- A live apply requires a current Glue backup and matching plan SHA.
- Any registry change after planning invalidates the plan.
- Unknown live tables are blocking drift.
- Retired tables remain recoverable from the S3 catalog backup.
- Empty nullable Parquet columns may physically use Arrow `null`; other type or
  order differences are blocking.
- The deprecated `jobs/run_athena_ddl.py` entrypoint must not be restored.

## S3 Inventory

Terraform manages the weekly `leviathan-dev-weekly` inventory configuration.
It writes current-object Parquet inventory beneath `metadata/s3_inventory/`,
uses SSE-S3, and expires reports after 90 days. AWS may take up to 48 hours to
deliver the first report; this delay does not indicate a failed deployment.
