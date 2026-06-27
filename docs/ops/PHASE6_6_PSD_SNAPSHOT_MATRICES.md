# Phase 6.6 PSD Snapshot-Stage Model-Ready Matrices

Status: implemented.

Completed: 2026-06-27

## Objective

Add opt-in model-ready matrices that evaluate PSD monthly-vintage features at
explicit snapshot dates while preserving the annual PSD anomaly target labels.

This is for in-season experiments where the label is still an annual PSD
outcome, but the information set changes through the crop year.

## What Changed

New snapshot-stage config:

```text
configs/ml/snapshot_stages.yaml
```

New helper:

```text
src/leviathan/model_datasets/snapshot_stages.py
```

New dataset key:

```text
psd_snd_anomaly_snapshot
```

Snapshot matrices write to the existing immutable model-ready prefix:

```text
gold/model_ready_matrices/dataset_version={version}/dataset_key=psd_snd_anomaly_snapshot/commodity={commodity}/target={target_key}/part-000.parquet
```

## Snapshot Grain

Rows are keyed by:

```text
commodity, country, crop_year, target_key, snapshot_stage, as_of_date
```

The target value is the same annual PSD anomaly repeated across snapshots.
Feature values differ because PSD monthly-vintage features are recomputed with:

```text
release_date <= as_of_date
```

## Initial Feature Scope

The default snapshot feature set is intentionally narrow:

```text
psd_monthly_vintage_features
```

Broader in-season weather, crop progress, flow, and economics features should
join snapshot matrices only after their availability rules are explicitly
defined at the same `as_of_date` grain.

## CLI

Named snapshot stages:

```powershell
.\.venv\Scripts\python.exe jobs\batch\build_model_ready_datasets.py `
  --target-source psd `
  --snapshot-stages early_inseason,midseason `
  --source-dataset-version {gold_dataset_version} `
  --model-dataset-version {model_dataset_version} `
  --commodities corn_cbot `
  --target-keys psd_production_anomaly_pct `
  --compatible-feature-sets psd_monthly_vintage_features `
  --skip-existing-versioned
```

Explicit single as-of date:

```powershell
.\.venv\Scripts\python.exe jobs\batch\build_model_ready_datasets.py `
  --target-source psd `
  --as-of-date 2026-06-01 `
  --source-dataset-version {gold_dataset_version} `
  --model-dataset-version {model_dataset_version} `
  --commodities corn_cbot `
  --target-keys psd_production_anomaly_pct `
  --skip-existing-versioned
```

Use `--snapshot-mode` to request all configured named stages.

## Training Compatibility

Training utilities now preserve optional row identity columns:

```text
snapshot_stage
as_of_date
```

They are excluded from feature selection, but retained for prediction artifacts
and baseline joins.

## What Did Not Change

- Default annual PSD matrices remain `psd_snd_anomaly`.
- FAOSTAT legacy matrices remain unchanged.
- No S3 cleanup or deletion was performed.
- No GraphRAG files were touched.

## Validation

Focused tests cover:

- named snapshot-date resolution;
- explicit as-of-date resolution;
- PSD snapshot matrix construction;
- local CLI writing for `psd_snd_anomaly_snapshot`;
- training-frame preservation of snapshot identity;
- baseline joins on snapshot identity.

Commands:

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests\unit\test_model_ready_snapshot_stages.py `
  tests\unit\test_psd_vintage_features.py `
  tests\unit\test_model_ready_psd_datasets.py `
  tests\unit\test_training_model_ready.py
```

## Next

Phase 7 can proceed with feature-family breadth and experiment execution. For
snapshot experiments, rebuild feature-set artifacts for the chosen source gold
dataset version if the live `gold_feature_set_versions` artifact predates
`psd_monthly_vintage_features`.
