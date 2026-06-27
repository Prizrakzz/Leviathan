# Phase 7 Cleanup And Deprecation Completion

Date: 2026-06-27

## Objective

Make the PSD-first model-ready surface the default experiment target while
preserving legacy FAOSTAT model-ready datasets for explicit replay.

## What Changed

- Added `configs/ml/model_dataset_versions.yaml` as the model-ready dataset
  status registry.
- Added `leviathan.model_datasets.version_status` for loading version status,
  selecting the active default, and exposing MLflow-safe status tags.
- Attached dataset status metadata to `load_model_ready_training_dataset`.
- Updated `jobs/submit/submit_batch_train.py` so:
  - `--model-dataset-version latest` resolves only to active/default-allowed
    versions;
  - PSD is the default target source for `latest`;
  - legacy FAOSTAT versions must be passed explicitly.
- Updated `jobs/batch/train_commodity.py` so MLflow runs receive dataset status
  tags and prediction outputs route to target-specific model-family prefixes.
- Added Phase 7 inventory and regression tests.

## Current Status

Active default:

```text
20260627T121215Z_phase5_psd_smoke
```

Legacy retained, not default:

```text
20260626T104732Z_a2576e84_phase8_model_ready
20260626T110249Z_38ffa8b3_phase8_batch_smoke
```

## Safety

No S3 objects were deleted, moved, or overwritten.

This phase is reversible by reverting the code/config change.  The underlying
immutable datasets remain where they are.

## Acceptance Criteria

- `latest` model dataset discovery resolves to the active PSD dataset.
- `latest` refuses legacy FAOSTAT datasets.
- Explicit legacy versions remain loadable.
- MLflow runs include model dataset status tags.
- Prediction outputs are no longer forced into the generic `tier1_production`
  partition when the target family is known.
