# Phase 7 Model Dataset Inventory

Date: 2026-06-27

This inventory is read-only.  No S3 objects were moved, deleted, or rewritten.

## Model-Ready Versions Observed

Prefix checked:

```text
s3://leviathan-dev-shahem-001/gold/model_ready_manifests/
s3://leviathan-dev-shahem-001/gold/model_ready_matrices/
```

Observed immutable model-ready dataset versions:

| dataset_version | status in code | target source | dataset keys | scope | notes |
| --- | --- | --- | --- | --- | --- |
| `20260627T121215Z_phase5_psd_smoke` | `active` | PSD | `psd_snd_anomaly` | smoke | Current PSD-first research surface. Covers the Phase 5 PSD smoke matrix set. |
| `20260626T104732Z_a2576e84_phase8_model_ready` | `legacy` | FAOSTAT | `annual_physical_anomaly` | full | Engineering benchmark for annual FAOSTAT-derived physical anomaly targets. Not the default futures-linked target surface. |
| `20260626T110249Z_38ffa8b3_phase8_batch_smoke` | `archived_reference` | FAOSTAT | `annual_physical_anomaly` | smoke | Historical Batch smoke artifact. Retained only for replay/debug comparisons. |

## Prediction Families Observed

Prefix checked:

```text
s3://leviathan-dev-shahem-001/silver/model_predictions/
```

Observed model-family partitions:

```text
model_family=psd_production_anomaly/
model_family=tier1_production/
```

Phase 7 adds routing so new model-ready PSD predictions use PSD target-family
prefixes, while legacy FAOSTAT annual anomaly predictions use:

```text
silver/model_predictions/model_family=legacy_faostat_annual_anomaly/
```

This avoids mixing old FAOSTAT training runs with PSD-first runs under generic
`tier1_production`.

## Non-Destructive Governance

The model-ready dataset status registry now lives at:

```text
configs/ml/model_dataset_versions.yaml
```

It is intentionally a local/config control plane, not an S3 mutation.  It lets
submitters resolve `--model-dataset-version latest` to the active PSD surface
without deleting or hiding older immutable data.

Explicit legacy replay remains possible by passing the exact legacy
`--model-dataset-version`; it is just no longer selected as a default.

## Manual Cleanup Later

No cleanup is approved or performed in Phase 7.  If we later choose to archive
or delete old data, the safe sequence is:

1. Snapshot inventory.
2. Mark dataset status in config.
3. Update readers to ignore deprecated defaults.
4. Re-run training/reader tests.
5. Archive to cold storage, if desired.
6. Delete only after explicit manual approval.
