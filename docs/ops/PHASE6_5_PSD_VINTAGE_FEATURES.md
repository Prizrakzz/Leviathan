# Phase 6.5 PSD Monthly Vintage Features

Status: implemented.

Completed: 2026-06-27

## Objective

Use USDA PSD monthly release vintages as point-in-time model features without
changing the annual PSD anomaly target policy.

PSD releases are monthly updates to annual marketing-year balance sheets. They
are not independent monthly realized production or stock/use targets. Phase 6.5
therefore adds release-vintage features first and leaves revision/nowcast target
families as a later explicit dataset design.

## Current Policy

Annual PSD target labels remain unchanged:

```text
psd_production_anomaly_pct
psd_ending_stocks_anomaly_pct
psd_stock_to_use_anomaly_pct
psd_exports_anomaly_pct
psd_imports_anomaly_pct
psd_domestic_use_anomaly_pct
```

The target builder still uses the latest available release for completed
marketing years when building final-ish annual anomaly labels.

## Live PSD Silver Audit

Read-only check:

```text
s3://leviathan-dev-shahem-001/silver/psd/
objects: 2
total_size_bytes: 2,343,516
part-000.parquet rows: 163,707
```

Available columns include the Phase 6.5 inputs:

```text
leviathan_slug
country
market_year
wasde_release_month
release_date
production_mt
imports_mt
exports_mt
ending_stocks_mt
consumption_mt
su_ratio
su_ratio_yoy_delta
production_mt_revision
ending_stocks_mt_revision
consumption_mt_revision
```

## New Feature Family

Feature family:

```text
psd_monthly_vintage_features
```

Config:

```text
configs/ml/psd_vintage_features.yaml
```

Computation:

```text
src/leviathan/features/computations/psd_vintages.py
```

Registry entry:

```text
configs/features/features.yaml
```

Taxonomy:

```text
feature_family: psd_monthly_vintage
semantic_scope: official_revision
policy: fundamental_physical
source_cadence: monthly
```

Feature set:

```text
psd_monthly_vintage_features
```

## Feature Names

The first implementation emits metric-specific features for configured PSD
attributes when those columns are present in `silver/psd`:

```text
psd_production_latest_estimate_as_of
psd_production_mom_revision
psd_production_revision_since_first_forecast
psd_production_consecutive_revision_count
psd_production_current_vs_trend
psd_production_month_code
psd_production_release_count_for_market_year
```

The same suffixes are supported for:

```text
psd_ending_stocks
psd_su_ratio
psd_exports
psd_imports
psd_domestic_use
```

## Leakage Controls

For crop year `Y`, the family uses:

```text
market_year = Y
snapshot_date = crop_year_start(Y)
release_date <= snapshot_date
```

For `current_vs_trend`, historical values are also selected point-in-time:

```text
historical market_year < Y
historical release_date <= snapshot_date
```

This prevents future PSD revisions from entering either the current estimate or
the trailing trend baseline.

## What Did Not Change

- No mutation to `silver/psd`.
- No overwrite of existing gold/model-ready dataset versions.
- No new monthly revision target dataset.
- No default promotion of monthly revision/nowcast models.
- No GraphRAG work.

## Validation

Focused tests cover:

- monthly PSD vintage feature calculations;
- future revisions not changing earlier snapshots;
- taxonomy classification before the generic `^psd_` rule;
- registry backing for the new feature family;
- feature-set selection;
- label counts remaining unchanged.

Commands:

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests\unit\test_psd_vintage_features.py `
  tests\unit\test_features_feature_sets.py `
  tests\unit\test_features_spine.py `
  tests\unit\test_model_ready_psd_datasets.py
```

## Next

Build a new immutable gold/model-ready dataset version if we want these features
materialized for actual MLflow sweeps. Then run a narrow comparison:

```text
commodity=corn_cbot
target_key=psd_production_anomaly_pct
feature_set=psd_monthly_vintage_features
models=lightgbm,xgboost
cv_policy=expanding_full_history
```
