# Phase 9 PSD Snapshot Vintage Completion

Date: 2026-06-27

## Summary

Implemented the model-ready snapshot path needed to train on USDA PSD monthly
release-vintage features without rebuilding the legacy gold feature spine.

New model-ready dataset version:

```text
20260627T190257Z_1a042698_phase9_psd_snapshot_corn
```

Dataset grain:

```text
commodity, country, crop_year, snapshot_stage, as_of_date, target_key
```

This keeps the supervised target annual while allowing the feature values to
change by point-in-time snapshot.

## Key Implementation

- Added model-ready-specific feature-set artifacts:
  - `gold/model_ready_feature_sets/dataset_version={version}/feature_sets.parquet`
  - `gold/model_ready_feature_set_manifests/dataset_version={version}/feature_sets.json`
- Updated the trainer loader to prefer model-ready feature sets when a
  model-ready manifest declares them, then fall back to source-gold feature
  sets for existing annual datasets.
- Updated the PSD snapshot builder so it can:
  - infer dynamic PSD monthly-vintage feature columns directly from the
    snapshot matrix;
  - build `psd_monthly_vintage_features`;
  - build `preseason_physical_plus_psd_vintage` by repeating static
    `preseason_physical` features across snapshot rows and joining them with
    visible PSD vintage features.
- Added Batch submitter and Terraform parameters for snapshot model-ready
  builds.
- Added AWS Batch job-name sanitization/truncation so long model-ready sweep
  names do not fail submission.
- Added Athena DDL for `gold_model_ready_feature_sets`.

## S3 Outputs

```text
s3://leviathan-dev-shahem-001/gold/model_ready_manifests/dataset_version=20260627T190257Z_1a042698_phase9_psd_snapshot_corn/manifest.json
s3://leviathan-dev-shahem-001/gold/model_ready_baselines/dataset_version=20260627T190257Z_1a042698_phase9_psd_snapshot_corn/baseline_metrics.parquet
s3://leviathan-dev-shahem-001/gold/model_ready_feature_sets/dataset_version=20260627T190257Z_1a042698_phase9_psd_snapshot_corn/feature_sets.parquet
s3://leviathan-dev-shahem-001/gold/model_ready_feature_set_manifests/dataset_version=20260627T190257Z_1a042698_phase9_psd_snapshot_corn/feature_sets.json
s3://leviathan-dev-shahem-001/gold/model_ready_matrices/dataset_version=20260627T190257Z_1a042698_phase9_psd_snapshot_corn/dataset_key=psd_snd_anomaly_snapshot/commodity=corn_cbot/target=psd_production_anomaly_pct/part-000.parquet
s3://leviathan-dev-shahem-001/gold/model_ready_targets/dataset_version=20260627T190257Z_1a042698_phase9_psd_snapshot_corn/dataset_key=psd_snd_anomaly_snapshot/commodity=corn_cbot/part-000.parquet
```

Validation:

```text
matrix rows: 964
matrix columns: 100
snapshot stages: preseason, early_inseason, midseason, late_inseason
duplicate (country, crop_year, snapshot_stage, as_of_date): 0
trainable rows: 884
psd_monthly_vintage_features: 49 features
preseason_physical_plus_psd_vintage: 64 features
```

## Registry

Added the new version to:

```text
configs/ml/model_dataset_versions.yaml
```

as an active PSD snapshot smoke surface for:

```text
dataset_key=psd_snd_anomaly_snapshot
```

`submit_batch_train.py --model-dataset-version latest --dataset-keys psd_snd_anomaly_snapshot`
now resolves to this version.

## Batch Smoke

Trainer image rebuilt and pushed:

```text
668891723125.dkr.ecr.us-east-1.amazonaws.com/leviathan-dev-leviathan-trainer:latest
digest: sha256:f98b84a93898ff713b8cc9fc875d3ec2deaa560e1de4bdbd6781e5314f5fa8f2
```

Registered train job definition:

```text
leviathan-dev-train:10
```

Smoke jobs:

| Feature Set | Job ID | MLflow Run ID | Status |
|---|---|---|---|
| `psd_monthly_vintage_features` | `1dff56cb-2e05-414d-8709-b09513980e90` | `b815611745df4098ad89e3ce9a2b8e4b` | succeeded |
| `preseason_physical_plus_psd_vintage` | `9daa9906-1768-4bc0-bea8-d94931d9e66c` | `0e45564b0db4467ba80ec98aacf79dbd` | succeeded |

Smoke configuration:

```text
commodity=corn_cbot
dataset_key=psd_snd_anomaly_snapshot
target_key=psd_production_anomaly_pct
model=lightgbm
cv_policy=expanding_post_2000
```

## Metrics

| Feature Set | Rows | RMSE | MAE | Directional Accuracy | Quintile Directional Accuracy | Best Baseline | Best Baseline RMSE | RMSE Delta |
|---|---:|---:|---:|---:|---:|---|---:|---:|
| `preseason_physical_plus_psd_vintage` | 272 | 0.4448 | 0.3363 | 0.7031 | 1.0000 | `prior_year_anomaly` | 0.2959 | +0.1489 |
| `psd_monthly_vintage_features` | 272 | 0.5817 | 0.4082 | 0.6875 | 0.9286 | `prior_year_anomaly` | 0.2959 | +0.2858 |

Interpretation:

- Combined static physical context plus PSD revisions improved materially over
  PSD vintage-only features.
- Neither smoke run beats the prior-year anomaly baseline on RMSE.
- The combined run is promising for extreme-direction detection but should not
  be promoted.
- Snapshot rows are stage-conditioned observations. The 272 CV rows are not 272
  independent annual targets; they are four point-in-time views per
  country-year over the same annual target.

## Validation

Focused tests:

```text
83 passed
```

Covered:

- storage paths for model-ready feature sets;
- PSD snapshot feature inference without source-gold PSD vintage membership;
- combined preseason-plus-vintage snapshot features;
- trainer loader preference for model-ready feature-set artifacts;
- model dataset registry resolution for snapshot datasets;
- Batch job-name sanitization.

## Next

Do not promote a model from this smoke.

Recommended next work:

1. Run the same snapshot grid with `xgboost` and `rolling_25y`.
2. Add per-snapshot-stage metric slices so we know whether PSD revisions help
   most at preseason, early season, midseason, or late season.
3. If combined features remain promising, expand to soybeans and wheat before
   any production-candidate discussion.
