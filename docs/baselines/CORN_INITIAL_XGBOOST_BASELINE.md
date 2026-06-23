# Initial Corn XGBoost Engineering Baseline

This record preserves the first completed Leviathan MLflow training run. It is
an engineering baseline, not a candidate model.

## Identity

- MLflow run: `29dcc3c021bb42148296128c9b3b96da`
- Experiment: `leviathan-tier1-production`
- Commodity: `corn_cbot`
- Tier: `climate`
- Target: `production_quantity`
- Estimator: XGBoost
- Original prediction date: 2026-06-17

## Recorded result

- Training matrix rows: 184
- Features: 279
- Walk-forward folds: 39
- RMSE: approximately 35.1 million
- MAE: approximately 21.3 million
- Directional accuracy: approximately 51.7%
- Stress-year directional accuracy: approximately 42.9%
- Governance gaps passed: no

## Known limitations

- The target is a trending production level rather than a revision, anomaly, or
  finalization-gap target.
- No fitted model artifact was logged.
- The feature-spine Git SHA is `unknown`.
- Country and stress-year governance gates failed.
- The run must not be promoted or used as a production candidate.

The immutable S3 baseline record contains the exact run metadata, predictions,
training snapshot, checksums, and source URIs.

