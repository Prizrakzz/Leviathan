# Phase 1 Completion

Phase 1 of MLflow experiment readiness completed on 2026-06-23.

## Live State

- S3 Inventory configuration: `leviathan-dev-weekly`
- Schedule and format: weekly, Parquet, current object versions
- Destination: `s3://leviathan-dev-shahem-001/metadata/s3_inventory/`
- Inventory retention: 90 days
- Registered datasets: 47
- Live Glue tables: 47
- Post-apply reconciliation: 47 no-ops
- Glue drift findings: 0
- Parquet schema findings: 0
- Athena smoke-query blockers: 0
- Expected Athena warnings: 4

The first inventory report can arrive up to 48 hours after configuration. The
Athena inventory table is deployed and queryable while that initial report is
pending.

Three deferred GraphRAG datasets are registered as `empty_pending_backfill`:
entities, causal edges, and forecasts. Their schema-only Parquet files are
queryable but contain no rows because the text-to-GraphRAG backfill remains
intentionally deferred. Sentiment is populated. These warnings do not block
structured-data or ML experiment readiness.

## Catalog Reconciliation

Applied plan SHA:

```text
11956c7449494986165381f1fd96910f7344d66579d808d2c5bebb8e83853376
```

Registry SHA used by the applied plan:

```text
c12aede0c07e91b71f4a9ddf6945cc0b1e4b1e169dccb743a5cc1004708929b0
```

Current registry SHA after recording deferred empty GraphRAG datasets:

```text
17903b7de7391b5c4763e2d65a4d249d0912f0b1171dd33d814883b89a2b7ba9
```

The applied plan created 10 tables, repaired 10 definitions, retired 3 legacy
definitions, and left 27 tables unchanged. No S3 data was deleted or rewritten.

The pre-change Glue catalog is preserved at:

```text
s3://leviathan-dev-shahem-001/metadata/catalog_reconciliation/backups/phase1-glue-backup.json
```

Retired definitions:

- `production_raw`, which pointed outside the Leviathan data lake;
- `silver_fnc_colombia`, replaced by three grain-specific tables;
- `silver_weather`, replaced by source-specific weather tables.

## Evidence

- `data/catalog_reconciliation/phase1-plan.json`
- `data/catalog_reconciliation/phase1-postapply-glue-validation.json`
- `data/catalog_reconciliation/phase1-postapply-validation.json`
- `data/catalog_reconciliation/phase1-athena-validation.json`

Verification completed with:

- 19 focused registry/catalog tests passing;
- 1,059 repository tests passing when the existing git-ignored GraphRAG
  research configuration is mounted;
- Ruff checks passing for all Phase 1 Python changes;
- Terraform validation passing;
- post-apply Terraform plan reporting no S3 module changes.

Operational instructions are in
`docs/ops/DATA_CATALOG_GOVERNANCE.md`.
