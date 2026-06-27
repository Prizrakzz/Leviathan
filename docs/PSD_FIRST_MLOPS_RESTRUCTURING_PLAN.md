# PSD-First MLOps Restructuring Plan

Prepared as a read-only planning pass. No code, S3, Glue, Athena, or MLflow state
was modified during the audit, except for creating this plan document as
requested.

## A. Executive Summary

Leviathan's current MLflow-ready supervised target layer is technically clean
but strategically pointed at the wrong primary truth source for futures-linked
ag-commodity models. The active model-ready dataset version
`20260626T104732Z_a2576e84_phase8_model_ready` is built from the source gold
version `20260626T010217Z_6725de02_phase7_full` and exposes three targets:

- `production_anomaly_pct`
- `yield_anomaly_pct`
- `area_harvested_anomaly_pct`

Observed from code and S3, these targets are derived from FAOSTAT label columns
in the gold feature matrix:

- `label_production_quantity`
- `label_yield`
- `label_area_harvested`

Those labels are emitted by
`src/leviathan/features/computations/production.py::compute_faostat_labels`
from `production:faostat`.

This is not wrong for a historical engineering baseline, but it can mislead
future futures-linked research because FAOSTAT is slow, final, annual, and not
the professional market S&D reference surface. PSD already exists in silver at
`silver/psd/part-000.parquet` with 163,707 rows and columns needed for S&D
targets:

- `production_mt`
- `imports_mt`
- `exports_mt`
- `ending_stocks_mt`
- `consumption_mt`
- `su_ratio`
- `release_date`
- `market_year`

The recommended strategic shift is:

1. Keep the current broad gold feature spine.
2. Demote FAOSTAT from primary target source to optional lagged structural
   feature context.
3. Add a PSD-first target mapping and target builder.
4. Build new immutable model-ready dataset versions with PSD production and
   balance-sheet anomaly targets.
5. Keep existing `annual_physical_anomaly` artifacts as legacy, not delete them.
6. Rebuild MLflow experiment conventions around `target_source=psd`.

Important correction to prior context: current `main` after Phase 10 does log
fitted model artifacts through `src/leviathan/training/mlflow_artifacts.py` and
`jobs/batch/train_commodity.py`. The remaining MLflow work is not basic model
serialization; it is target-aware tagging, artifact metadata, champion
selection, and registry/promotion discipline for PSD-first datasets.

## B. What The Current System Appears To Do

### Current Pipeline

Observed pipeline:

```text
silver/*
  -> gold/feature_spine_versions
  -> gold/feature_matrix_versions
  -> gold/feature_catalog_versions
  -> gold/feature_set_versions
  -> gold/model_ready_targets
  -> gold/model_ready_matrices
  -> gold/model_ready_baselines
  -> MLflow training
```

### Current Target Code Path

Observed files:

- `configs/ml/target_definitions.yaml`
- `src/leviathan/model_datasets/targets.py`
- `src/leviathan/model_datasets/builder.py`
- `src/leviathan/model_datasets/baselines.py`
- `jobs/batch/build_model_ready_datasets.py`
- `src/leviathan/training/model_ready.py`
- `jobs/batch/train_commodity.py`

Observed target definitions:

```yaml
target_key: production_anomaly_pct
dataset_key: annual_physical_anomaly
label_column: label_production_quantity
actual_column: production_quantity

target_key: yield_anomaly_pct
dataset_key: annual_physical_anomaly
label_column: label_yield
actual_column: yield

target_key: area_harvested_anomaly_pct
dataset_key: annual_physical_anomaly
label_column: label_area_harvested
actual_column: area_harvested
```

Observed target algorithm:

```text
target_value = actual_value / trailing_linear_trend_prediction - 1
```

Implemented as:

```text
src/leviathan/model_datasets/baselines.py::build_trailing_anomaly_targets
```

The trailing trend is fitted using only `crop_year < current crop_year`, which
is the correct anti-leakage behavior.

### Current Label Source

Observed from:

- `src/leviathan/features/computations/production.py`
- `configs/features/features.yaml`
- `configs/features/feature_taxonomy.yaml`
- S3 feature catalog sample

Current labels are FAOSTAT labels:

```text
label_production_quantity -> production:faostat
label_area_harvested      -> production:faostat
label_yield               -> production:faostat
```

The feature catalog for version `20260626T010217Z_6725de02_phase7_full`
classifies these as:

```text
feature_family = labels
semantic_scope = target_label
sources        = production:faostat
is_label       = true
```

### Current PSD Role

Observed files:

- `src/leviathan/transforms/bronze_to_silver/usda_psd.py`
- `src/leviathan/features/computations/sd_balance.py`
- `configs/features/features.yaml`
- `configs/features/feature_taxonomy.yaml`
- `configs/datasets/source_contracts.yaml`
- `sql/athena/ddl/silver_psd.sql`

PSD is currently used as feature context, not target truth:

```text
psd_ending_stock_su_ratio
psd_su_ratio_yoy_delta
psd_available
```

PSD feature visibility is `prior_marketing_year`, meaning the feature layer
intentionally uses the prior marketing-year balance sheet visible at crop-year
start. That is correct for features, but not sufficient for labels.

### Current S3 Surfaces

Read-only S3 inventory found:

```text
gold/feature_spine_versions/
  objects: 67
  active full version: 20260626T010217Z_6725de02_phase7_full

gold/feature_matrix_versions/
  objects: 67
  active full version: 20260626T010217Z_6725de02_phase7_full

gold/feature_catalog_versions/
  objects: 4

gold/feature_set_versions/
  objects: 2
  active full version: 20260626T010217Z_6725de02_phase7_full

gold/model_ready_targets/
  objects: 32
  active model-ready version: 20260626T104732Z_a2576e84_phase8_model_ready

gold/model_ready_matrices/
  objects: 84
  active model-ready version: 20260626T104732Z_a2576e84_phase8_model_ready

gold/model_ready_baselines/
  objects: 2

gold/model_ready_manifests/
  objects: 2

silver/model_predictions/
  objects: 3

model_artifacts/training_snapshots/
  objects: 5

silver/psd/
  objects: 2
  main data: silver/psd/part-000.parquet

silver/production/
  objects: 2375
```

Read-only Glue inventory found relevant live tables:

- `silver_psd`
- `silver_production`
- `gold_feature_spine`
- `gold_feature_spine_versions`
- `gold_feature_spine_manifests`
- `gold_feature_catalog`
- `gold_feature_catalog_versions`
- `gold_feature_entity_map_versions`
- `gold_feature_group_map_versions`
- `gold_feature_set_versions`
- `gold_model_ready_targets`
- `gold_model_ready_baselines`
- `gold_training_windows`
- `gold_training_windows_versions`

No live Glue table was observed for `gold_model_ready_matrices`, which matches
the design: wide matrices vary by target/version and are training artifacts.

## C. Where The Current Design May Mislead Future Research

### 1. Target Names Hide Target Source

The key `production_anomaly_pct` does not say FAOSTAT. The model-ready target
table also does not include:

- `target_source`
- `target_family`
- `target_attribute`
- `target_source_table`
- `target_release_context`
- `target_market_year`
- `target_unit`

This can cause future users to believe the target is PSD, WASDE, NASS, or a
generic physical truth.

### 2. Dataset Key Is Too Broad

`annual_physical_anomaly` sounds source-neutral. In practice it currently means
FAOSTAT production/yield/area anomalies.

### 3. FAOSTAT Is Both Feature Context And Target Truth

FAOSTAT features are prior-history safe today:

- `faostat_production_yoy`
- `faostat_production_trend_dev`
- `faostat_available`

But FAOSTAT labels are same-year final outcomes. This is acceptable as labels,
but it should be explicit and not become the primary futures-linked target
truth.

### 4. PSD Features Exist But PSD Targets Do Not

The system already has PSD S&D data and PSD feature computations, but the
model-ready builder only accepts label columns already present in the gold
feature matrix.

### 5. Crop Year And Marketing Year Are Mixed But Not Exposed In Targets

The feature spine uses `crop_year`. PSD silver uses `market_year`. Crop calendars
define `mkt_year_offset`. The current target tables expose only `crop_year`.
PSD-first target rows should expose both the model observation crop year and the
PSD target marketing year.

### 6. Old S3 Prefixes Can Be Misread As Current Research Truth

These should be retained but clearly labeled as legacy once PSD-first datasets
exist:

```text
gold/model_ready_targets/dataset_version=20260626T104732Z_a2576e84_phase8_model_ready/
gold/model_ready_matrices/dataset_version=20260626T104732Z_a2576e84_phase8_model_ready/
gold/model_ready_baselines/dataset_version=20260626T104732Z_a2576e84_phase8_model_ready/
gold/model_ready_manifests/dataset_version=20260626T104732Z_a2576e84_phase8_model_ready/
silver/model_predictions/model_family=tier1_production/
```

No deletion should happen during restructuring.

## D. Proposed PSD-First Target Architecture

### Target Families

Primary family A:

```text
psd_production_anomaly
```

Primary family B:

```text
psd_balance_sheet_anomaly
```

Later families:

```text
psd_revision
local_agency_anomaly
relative_stress
price_or_spread
```

### Target Keys

Initial PSD-first target keys:

```text
psd_production_anomaly_pct
psd_ending_stocks_anomaly_pct
psd_stock_to_use_anomaly_pct
psd_exports_anomaly_pct
psd_imports_anomaly_pct
psd_domestic_use_anomaly_pct
```

Recommended dataset keys:

```text
psd_production_anomaly
psd_balance_sheet_anomaly
```

Rationale:

- Two dataset keys make MLflow sweeps cleaner.
- Production anomaly and balance-sheet anomaly have different interpretation.
- Baselines and promotion criteria can differ by family.
- A single `psd_snd_anomaly` key would be simpler but less clear.

### Required Target Dimensions

New target rows should include at least:

```text
source_dataset_version
model_dataset_version
dataset_key
commodity
contract_key
target_key
target_family
target_source
psd_commodity
psd_country
psd_attribute
country
crop_year
marketing_year
target_market_year
unit
actual_value
target_value
trend_prediction
prior_year_value
trailing_mean_prediction
zero_anomaly_baseline
prior_year_anomaly_baseline
trailing_mean_anomaly_baseline
trailing_trend_anomaly_baseline
history_years
is_trainable
excluded_reason
target_release_context
target_observation_release_date
target_source_vintage
```

`country` should remain the model origin key used by the gold feature matrix.
`psd_country` should preserve the PSD source country mapping after
standardization. For many targets they will match; for global or proxy targets
they may not.

### Target Computation

For each configured PSD metric:

```text
actual_series[country, marketing_year] = final or selected PSD value
trend_prediction[Y] = linear trend fitted on years < Y
target_value[Y] = actual_series[Y] / trend_prediction[Y] - 1
```

Equivalent:

```text
target_value = (actual_value - trend_prediction) / abs(trend_prediction)
```

The existing `build_trailing_anomaly_targets` already implements the core math
for a matrix label column. PSD-first should reuse the math but not require
labels to already be embedded in the gold feature matrix.

### Final PSD Actual Selection

Open question: the current `silver/psd` has multiple `release_date` values for
some `(leviathan_slug, country, market_year)` combinations. For target labels,
we need a documented final-value policy:

Recommended initial policy:

```text
For each (contract_key, psd_country, market_year, psd_attribute),
select the latest release_date available in the silver PSD corpus.
```

Alternative policy:

```text
Use a fixed post-year finalization window, e.g. latest release within
market_year + 18 months, to avoid later historical revisions changing labels.
```

The second policy is more stable but needs explicit target-release metadata.

### Edge Cases

Zero or near-zero trend denominator:

- Mark `excluded_reason = near_zero_trend_denominator`.
- Do not emit trainable targets when `abs(trend_prediction) < eps`.
- Proposed default `eps = 1e-9` for ratio metrics and `eps = 1.0` for MT
  metrics, configurable per target.

Missing histories:

- Keep rows but set `is_trainable = false`.
- Use `excluded_reason = insufficient_history`.
- Preserve `history_years`.

Short histories:

- Default `min_history_years = 5`.
- Require per-target override for sparse commodities.

Unit changes:

- Use `silver/psd` standardized columns in MT, MT/HA, or ratios.
- Store `unit` on every target row.
- Reject target configs whose source column unit is unknown.

Commodity/country remapping:

- Do not rely only on PSD fan-out in `usda_psd.py`.
- Add explicit target mapping from `contract_key` to PSD commodity/country
  rules.

Split commodities:

- Coffee PSD is aggregate coffee. Do not pretend it cleanly splits arabica and
  robusta unless the mapping marks it as proxy.
- Wheat PSD is all wheat. Do not blindly assign aggregate all-wheat production
  to hard/soft/spring wheat without a `proxy_scope = all_wheat` warning.
- Palm oil PSD maps to palm oil; for palm olein contracts, target mapping should
  mark the target as proxy-derived.

Commodities without clean PSD yield/area:

- Do not build PSD yield/area as primary targets unless PSD columns are
  audited by commodity.
- Start with production and S&D balance metrics.

## E. Proposed FAOSTAT Role

### New Role

FAOSTAT should be retained as optional long-run context, not primary target
truth.

Proposed feature families:

```text
faostat_longrun_capacity
faostat_structural_supply_context
faostat_source_disagreement
faostat_data_quality_context
```

Possible feature names:

```text
faostat_capacity_trend_mt
faostat_capacity_trend_dev_lagged
faostat_production_yoy_lagged
faostat_vs_psd_production_gap_pct_lagged
faostat_vs_psd_rank_disagreement_lagged
faostat_available_lagged
faostat_release_lag_years
```

### Leakage Policy

Hard rule:

```text
Same-year FAOSTAT final values cannot predict same-year PSD targets.
```

If release dates are unknown:

```text
Use t-2 by default for FAOSTAT features in PSD target models.
Allow t-1 only if a documented release calendar proves availability.
```

Initial policy recommendation:

- `faostat_data_quality_context`: `diagnostic_only`
- `faostat_source_disagreement`: start as `diagnostic_only`, promote to
  `fundamental_physical` only after leakage tests and economic review
- `faostat_longrun_capacity`: may be `fundamental_physical` if lagged t-2
- `faostat_structural_supply_context`: may be `fundamental_physical` if lagged
  t-2

### Feature Set Implications

Do not leave FAOSTAT in `preseason_physical` implicitly once PSD targets are
primary.

Recommended new explicit feature sets:

```text
faostat_longrun_capacity
faostat_source_disagreement
preseason_physical_plus_faostat_capacity
```

`preseason_physical` should become PSD-first and not include FAOSTAT unless
explicitly stated.

## F. Proposed Config Changes

### New PSD Target Mapping Config

Recommended file:

```text
configs/ml/psd_metric_targets.yaml
```

Reason: target mappings are ML-target definitions, not raw source ingestion
contracts.

Possible schema:

```yaml
schema_version: 1

defaults:
  target_source: psd
  source_table: silver_psd
  min_history_years: 5
  target_type: trailing_trend_pct_anomaly
  final_value_policy: latest_release_in_silver
  denominator_epsilon:
    mt: 1.0
    ratio: 1.0e-9

target_metrics:
  - target_key: psd_production_anomaly_pct
    dataset_key: psd_production_anomaly
    target_family: psd_production_anomaly
    psd_attribute: production
    source_column: production_mt
    unit: mt
    allowed_as_target: true
    allowed_as_feature: false

  - target_key: psd_stock_to_use_anomaly_pct
    dataset_key: psd_balance_sheet_anomaly
    target_family: psd_balance_sheet_anomaly
    psd_attribute: stock_to_use
    source_column: su_ratio
    unit: ratio
    allowed_as_target: true
    allowed_as_feature: true
```

### New Contract-To-PSD Mapping Config

Recommended file:

```text
configs/ml/psd_contract_targets.yaml
```

Possible schema:

```yaml
schema_version: 1

contracts:
  corn_cbot:
    psd_commodity: corn
    psd_slug: corn_cbot
    psd_countries:
      - united_states
      - brazil
      - argentina
      - ukraine
    marketing_year_convention: psd_market_year
    target_market_year_rule: crop_year_plus_calendar_offset
    crop_to_market_year_offset: 0
    proxy_scope: direct
    allowed_targets:
      - psd_production_anomaly_pct
      - psd_ending_stocks_anomaly_pct
      - psd_stock_to_use_anomaly_pct
      - psd_exports_anomaly_pct
      - psd_imports_anomaly_pct
      - psd_domestic_use_anomaly_pct

  soft_red_winter_wheat_cbot:
    psd_commodity: wheat
    psd_slug: soft_red_winter_wheat_cbot
    proxy_scope: all_wheat_proxy
    warning: PSD wheat is all-class aggregate, not SRW-specific.
```

Open question: whether to place contract-level PSD mapping under
`configs/commodities/*.yaml` instead. That would colocate contract metadata, but
the current ML code is config-driven from `configs/ml`, so a central target
mapping is cleaner for now.

### Target Definitions Refactor

Current:

```text
configs/ml/target_definitions.yaml
```

Recommended:

```text
configs/ml/target_definitions.yaml       # active top-level target registry
configs/ml/faostat_legacy_targets.yaml   # old annual physical anomaly targets
configs/ml/psd_metric_targets.yaml       # PSD metric definitions
configs/ml/psd_contract_targets.yaml     # contract/source mapping
```

`target_definitions.yaml` should mark target families:

```yaml
status: active | legacy | deprecated | experimental
target_source: psd | faostat | local_agency
```

### Feature Taxonomy Updates

Likely affected:

- `configs/features/feature_taxonomy.yaml`
- `configs/features/features.yaml`
- `configs/features/feature_sets.yaml`
- `configs/features/feature_groups.yaml`

Recommended taxonomy additions:

```text
faostat_longrun_capacity
faostat_structural_supply_context
faostat_source_disagreement
faostat_data_quality_context
psd_target_context
psd_balance_sheet_target
```

Do not classify PSD target labels as ordinary input features.

## G. Proposed Code Changes

No code changes were made in this planning pass. Future implementation should
touch these areas.

### Target Loading

Likely affected:

- `src/leviathan/model_datasets/targets.py`

Add fields to `TargetDefinition` or add a new `PSDTargetDefinition`:

```text
target_source
target_family
source_table
source_column
psd_attribute
unit
final_value_policy
target_source_metadata
allowed_as_target
allowed_as_feature
status
```

### PSD Target Builder

Likely new module:

```text
src/leviathan/model_datasets/psd_targets.py
```

Responsibilities:

- load `silver/psd`
- apply contract/commodity/country mapping
- select final target value per `(contract, psd_country, target_market_year)`
- compute trailing anomaly with prior years only
- emit target metadata columns
- aggregate or preserve origin rows according to target mapping

### Existing Builder Refactor

Likely affected:

- `src/leviathan/model_datasets/builder.py`
- `jobs/batch/build_model_ready_datasets.py`

Current builder assumes target labels exist in the feature matrix. PSD targets
should not require label columns inside `gold/feature_matrix_versions`. Instead:

```text
feature matrix rows
  join
PSD target panel
  on commodity/origin/crop_year or commodity/psd_country/marketing_year mapping
```

### Model-Ready Matrix Schema

Likely affected:

- `src/leviathan/model_datasets/builder.py`
- `src/leviathan/training/model_ready.py`
- `sql/athena/ddl/gold_model_ready_targets.sql`
- `configs/datasets/datasets.yaml`

Add target metadata to the target table and matrix identity columns:

```text
target_source
target_family
target_attribute
target_unit
target_market_year
target_release_context
target_source_vintage
psd_commodity
psd_country
```

### MLflow Training Tags

Likely affected:

- `jobs/batch/train_commodity.py`
- `src/leviathan/training/model_ready.py`
- `src/leviathan/training/mlflow_artifacts.py`
- `src/leviathan/training/tracking.py`

Add tags:

```text
target_source=psd
target_family
psd_attribute
psd_country_scope
psd_commodity
target_key
dataset_key
model_dataset_version
source_gold_dataset_version
feature_set
feature_set_sha
target_config_sha
psd_mapping_sha
faostat_feature_policy
faostat_lag_policy
cv_scheme=walk_forward_expanding_window
min_train_years
```

### Docker

Likely affected:

- `docker/leviathan_trainer/Dockerfile`

No major new dependencies are expected if PSD target building stays pandas and
pyarrow. If new validation tooling is added, keep the trainer image lean.

## H. Proposed S3 Cleanup And Deprecation Plan

No S3 cleanup should happen during target restructuring.

### Retain As Active For Now

```text
gold/feature_spine_versions/dataset_version=20260626T010217Z_6725de02_phase7_full/
gold/feature_matrix_versions/dataset_version=20260626T010217Z_6725de02_phase7_full/
gold/feature_catalog_versions/dataset_version=20260626T010217Z_6725de02_phase7_full/
gold/feature_entity_map_versions/dataset_version=20260626T010217Z_6725de02_phase7_full/
gold/feature_group_map_versions/dataset_version=20260626T010217Z_6725de02_phase7_full/
gold/feature_set_versions/dataset_version=20260626T010217Z_6725de02_phase7_full/
silver/psd/
silver/production/
```

### Mark Legacy After PSD-First Version Exists

```text
gold/model_ready_targets/dataset_version=20260626T104732Z_a2576e84_phase8_model_ready/
gold/model_ready_matrices/dataset_version=20260626T104732Z_a2576e84_phase8_model_ready/
gold/model_ready_baselines/dataset_version=20260626T104732Z_a2576e84_phase8_model_ready/
gold/model_ready_manifests/dataset_version=20260626T104732Z_a2576e84_phase8_model_ready/
```

Do not delete. Add manifest metadata only:

```json
{
  "status": "legacy",
  "legacy_reason": "FAOSTAT-derived annual production/yield/area targets",
  "replaced_by": "future PSD-first model_dataset_version"
}
```

### Mark Old Predictions As Legacy

Current prediction prefix:

```text
silver/model_predictions/model_family=tier1_production/
```

Recommended future prefixes:

```text
silver/model_predictions/model_family=psd_production_anomaly/
silver/model_predictions/model_family=psd_balance_sheet_anomaly/
```

Keep old predictions but exclude them from PSD-first dashboards unless
explicitly requested.

### Manual-Approval-Only Cleanup Procedure

1. Inventory all objects and write an immutable inventory report.
2. Snapshot manifests and current Glue metadata.
3. Mark legacy/deprecated status in manifests or registry metadata.
4. Update readers to ignore deprecated model-ready versions by default.
5. Run tests and dry-run training.
6. Optionally copy legacy artifacts to archive/cold storage.
7. Delete only after explicit manual approval in a separate operation.

No deletion commands are included as recommended actions in this plan.

## I. Proposed MLflow Restructuring

### New Experiment Names

Recommended:

```text
leviathan-psd-production-anomaly
leviathan-psd-balance-sheet-anomaly
leviathan-legacy-faostat-annual-anomaly
```

Avoid putting both FAOSTAT and PSD target runs in the same default experiment
unless tags are enforced and the UI filters are obvious.

### Run Name Convention

Recommended:

```text
{commodity}-{feature_set}-{dataset_key}-{target_key}-{model}-{model_dataset_version_short}
```

Example:

```text
corn_cbot-preseason_physical-psd_production_anomaly-psd_production_anomaly_pct-xgboost-20260701T...
```

### Required Tags

```text
target_source
target_family
psd_attribute
psd_commodity
psd_country_scope
target_key
dataset_key
model_dataset_version
source_gold_dataset_version
feature_set
feature_set_sha
target_config_sha
psd_mapping_sha
faostat_feature_policy
faostat_lag_policy
cv_scheme
min_train_years
fitted_model_flavor
fitted_model_artifact_path
predictions_uri
snapshot_uri
```

### Required Artifacts

```text
metadata/manifest.json
metadata/target_distribution.json
metadata/leakage_audit.json
metadata/selected_features.json
tables/target_matrix_snapshot.parquet
tables/cv_predictions.parquet
tables/fold_metrics.parquet
tables/baseline_comparison.parquet
tables/feature_importance.parquet
tables/model_replay_sample.parquet
logs/training.log
```

### Distinguishing Old Runs

For old FAOSTAT runs:

```text
target_source=faostat
dataset_status=legacy
target_family=legacy_annual_physical_anomaly
```

If old runs lack tags, create a read-only report that maps run IDs to inferred
status from `model_dataset_version` and `dataset_key`. Do not rewrite MLflow
history until there is a clear migration policy.

## J. Proposed Tests

### Target Computation Tests

File:

```text
tests/unit/test_model_datasets_psd_targets.py
```

Tests:

```text
test_psd_target_config_loads_metric_and_contract_mappings
test_psd_target_builder_selects_latest_final_release_per_market_year
test_psd_target_builder_emits_required_metadata_columns
test_psd_production_anomaly_uses_only_prior_years_for_trend
test_psd_stock_to_use_anomaly_handles_ratio_units
test_psd_target_excludes_near_zero_trend_denominator
test_psd_target_marks_short_history_untrainable
test_psd_target_preserves_market_year_and_crop_year
```

Synthetic fixture:

- one contract
- two countries
- market years 2000-2008
- two release dates per market year
- current-year spike to prove trend ignores current value

Expected assertions:

- trend for year T fits only years `< T`
- latest release selected according to policy
- `target_source == "psd"`
- `target_family` populated
- `psd_attribute` populated
- `is_trainable` false for insufficient history

### PSD Mapping Tests

File:

```text
tests/unit/test_psd_target_mapping.py
```

Tests:

```text
test_contract_mapping_requires_known_contract_key
test_contract_mapping_rejects_unknown_psd_attribute
test_wheat_proxy_mapping_requires_proxy_scope_warning
test_coffee_aggregate_mapping_requires_proxy_scope_warning
test_mapping_sha_changes_when_mapping_changes
```

### FAOSTAT Lag Policy Tests

File:

```text
tests/unit/test_faostat_demotion_policy.py
```

Tests:

```text
test_faostat_capacity_features_use_t_minus_2_when_release_dates_unknown
test_faostat_same_year_values_not_selected_for_psd_target_year
test_faostat_source_disagreement_defaults_to_diagnostic_only
test_faostat_feature_set_excludes_current_year_labels
```

### Feature-Set Selection Tests

Existing file:

```text
tests/unit/test_features_feature_sets.py
```

Add:

```text
test_psd_core_sets_exclude_diagnostic_and_excluded_market_signal
test_preseason_physical_no_longer_includes_faostat_unless_explicit
test_preseason_physical_plus_faostat_capacity_includes_only_lagged_capacity
test_psd_balance_sheet_set_selects_psd_balance_features
```

### Model-Ready Manifest Tests

Existing file:

```text
tests/unit/test_model_ready_datasets.py
```

Add:

```text
test_psd_model_ready_manifest_records_target_source_and_mapping_sha
test_psd_model_ready_matrix_contains_target_metadata
test_legacy_faostat_targets_marked_legacy_when_config_status_legacy
test_model_ready_builder_can_join_external_psd_target_panel
```

### MLflow Tag And Artifact Tests

Existing/new files:

```text
tests/unit/test_training_model_ready.py
tests/unit/test_training_mlflow_artifacts.py
```

Add:

```text
test_training_logs_psd_target_tags
test_training_logs_target_distribution_artifact
test_training_logs_leakage_audit_artifact
test_training_run_name_includes_psd_dataset_key_and_target_key
```

### S3 Reader Deprecation Tests

New file:

```text
tests/unit/test_model_ready_version_selection.py
```

Tests:

```text
test_default_model_ready_selector_ignores_deprecated_versions
test_explicit_legacy_version_can_still_load
test_deprecated_manifest_status_is_respected
```

### Regression Tests

Keep existing tests for:

- `build_trailing_anomaly_targets`
- walk-forward CV
- model-ready feature selection
- feature-set diagnostic policy
- MLflow replay

Do not silently remove FAOSTAT legacy target tests until the old dataset is
explicitly deprecated and tests are renamed to legacy.

## K. Phased Implementation Roadmap

### Phase 0 - Audit And Inventory

Objective:

- Freeze a trustworthy picture of current code, S3, Glue, DDLs, and MLflow
  surfaces before changing target architecture.

Detailed tasks:

- Inventory target definitions and source lineage.
- Inventory S3 gold/model-ready/prediction prefixes.
- Inventory Glue tables and checked-in Athena DDLs.
- Inventory MLflow experiments and run tags for current model-ready runs.
- Write an audit report with observed facts and open questions.

Files/configs likely affected:

- New report under `docs/ops/`.
- No production code.

S3 prefixes affected:

- Read-only:
  - `gold/feature_spine_versions/`
  - `gold/feature_matrix_versions/`
  - `gold/model_ready_targets/`
  - `gold/model_ready_matrices/`
  - `silver/psd/`
  - `silver/production/`
  - `silver/model_predictions/`

Risks:

- None if read-only.

Validation/tests:

- Confirm no staged code changes.
- Confirm no S3 mutations.

Acceptance criteria:

- Audit report identifies current target source as FAOSTAT or explicitly marks
  ambiguity.
- S3 inventory lists active and legacy candidate prefixes.

Reversibility:

- Safe and reversible.

What not to do:

- Do not edit configs.
- Do not rebuild datasets.
- Do not delete S3 objects.

### Phase 1 - Target-Source Truth Audit

Objective:

- Prove, for every existing target, exactly which source produced the label and
  whether the source is acceptable for futures-linked primary modeling.

Detailed tasks:

- Trace `label_*` generation from feature computations.
- Compare gold feature catalog label rows against target definitions.
- Validate current `annual_physical_anomaly` manifest does or does not record
  target source metadata.
- Produce target-source truth table:
  - target key
  - dataset key
  - label column
  - source
  - cadence
  - release lag
  - leakage risk
  - recommended status

Files/configs likely affected:

- New audit report only.
- Later phases may affect `configs/ml/target_definitions.yaml`.

S3 prefixes affected:

- Read-only:
  - `gold/feature_catalog_versions/dataset_version=20260626T010217Z_6725de02_phase7_full/`
  - `gold/model_ready_manifests/dataset_version=20260626T104732Z_a2576e84_phase8_model_ready/`

Risks:

- Confusing feature source with target source if only target names are read.

Validation/tests:

- Use feature catalog `sources` and `is_label`.
- Use target config `label_column`.

Acceptance criteria:

- Current production/yield/area target source is explicitly classified.
- Existing target source metadata gaps are documented.

Reversibility:

- Safe and reversible.

What not to do:

- Do not rename targets yet.
- Do not mark datasets deprecated yet.

### Phase 2 - PSD Mapping Config Design

Objective:

- Design and review the mapping from Leviathan futures contracts to PSD
  commodities, countries, attributes, units, and target permissions.

Detailed tasks:

- Add proposed config schema after review:
  - `configs/ml/psd_metric_targets.yaml`
  - `configs/ml/psd_contract_targets.yaml`
- Define proxy warnings for aggregate PSD mappings.
- Define per-target unit and denominator policies.
- Define active target list and allowed commodities.

Files/configs likely affected:

- `configs/ml/psd_metric_targets.yaml`
- `configs/ml/psd_contract_targets.yaml`
- `configs/ml/target_definitions.yaml`
- Possibly `configs/commodities/*.yaml` if contract metadata should be
  colocated later.

S3 prefixes affected:

- None during config design.

Risks:

- Mapping aggregate PSD wheat/coffee to contract-specific models without proxy
  warnings.
- Building targets for countries that are in PSD but not in the commodity
  geography config.

Validation/tests:

- `tests/unit/test_psd_target_mapping.py`

Acceptance criteria:

- Every active PSD target has a metric definition.
- Every contract target mapping is explicit.
- Proxy mappings are marked.
- Mapping config hash can be computed and logged.

Reversibility:

- Safe and reversible.

What not to do:

- Do not build model-ready datasets yet.
- Do not change MLflow training defaults yet.

### Phase 3 - PSD Target Builder Design

Objective:

- Build PSD target panels from `silver/psd` without requiring PSD labels inside
  the gold feature matrix.

Detailed tasks:

- Implement a PSD target builder module.
- Reuse trailing anomaly math where possible.
- Add metadata columns to target rows.
- Add final-value selection policy.
- Add near-zero denominator handling.
- Add target-source leakage audit output.

Files/configs likely affected:

- `src/leviathan/model_datasets/psd_targets.py`
- `src/leviathan/model_datasets/targets.py`
- `src/leviathan/model_datasets/baselines.py`
- `src/leviathan/model_datasets/builder.py`
- `jobs/batch/build_model_ready_datasets.py`

S3 prefixes affected:

- Future write:
  - `gold/model_ready_targets/dataset_version={new_psd_version}/`
  - `gold/model_ready_matrices/dataset_version={new_psd_version}/`
  - `gold/model_ready_baselines/dataset_version={new_psd_version}/`
  - `gold/model_ready_manifests/dataset_version={new_psd_version}/`

Risks:

- Accidentally using feature-visible prior PSD instead of final PSD labels.
- Misaligning crop year and PSD market year.
- Latest release policy can cause labels to change when PSD history is revised.

Validation/tests:

- `tests/unit/test_model_datasets_psd_targets.py`
- `tests/unit/test_model_ready_datasets.py`

Acceptance criteria:

- PSD target panel builds locally from synthetic data.
- Trend calculation uses only prior years.
- Target rows include source metadata.
- Legacy FAOSTAT targets still build when explicitly selected.

Reversibility:

- Safe if written to new immutable version only.

What not to do:

- Do not overwrite `20260626T104732Z_a2576e84_phase8_model_ready`.
- Do not modify old target parquet files.

### Phase 4 - FAOSTAT Demotion Design

Objective:

- Move FAOSTAT from implicit primary target source to explicit optional feature
  context.

Detailed tasks:

- Mark existing FAOSTAT target definitions as legacy.
- Add lagged FAOSTAT context families.
- Adjust feature taxonomy and feature sets so FAOSTAT inclusion is explicit.
- Add source-disagreement features only if lagged and leakage-audited.

Files/configs likely affected:

- `configs/ml/faostat_legacy_targets.yaml`
- `configs/ml/target_definitions.yaml`
- `configs/features/features.yaml`
- `configs/features/feature_taxonomy.yaml`
- `configs/features/feature_sets.yaml`
- `src/leviathan/features/computations/production.py`

S3 prefixes affected:

- New future gold dataset version only if feature registry changes:
  - `gold/feature_spine_versions/dataset_version={new_version}/`
  - `gold/feature_matrix_versions/dataset_version={new_version}/`
  - `gold/feature_catalog_versions/dataset_version={new_version}/`
  - `gold/feature_set_versions/dataset_version={new_version}/`

Risks:

- Breaking existing feature sets unexpectedly.
- Leakage from same-year FAOSTAT values into PSD target models.

Validation/tests:

- `tests/unit/test_faostat_demotion_policy.py`
- `tests/unit/test_features_feature_sets.py`
- existing feature spine tests.

Acceptance criteria:

- FAOSTAT target definitions are legacy-labeled.
- PSD-first feature sets do not include current-year FAOSTAT labels.
- Any FAOSTAT feature used in training has a documented lag policy.

Reversibility:

- Reversible by using previous immutable gold/model-ready versions.

What not to do:

- Do not delete FAOSTAT silver.
- Do not remove old FAOSTAT code until legacy loading is verified.

### Phase 5 - Model-Ready Matrix Restructuring

Objective:

- Build PSD-first model-ready target tables and matrices with explicit target
  metadata and compatible feature sets.

Detailed tasks:

- Extend matrix identity columns.
- Add target metadata to model-ready targets.
- Add dataset keys:
  - `psd_production_anomaly`
  - `psd_balance_sheet_anomaly`
- Build a new immutable model-ready dataset version.
- Keep old `annual_physical_anomaly` loadable but legacy.

Files/configs likely affected:

- `src/leviathan/model_datasets/builder.py`
- `src/leviathan/training/model_ready.py`
- `jobs/batch/build_model_ready_datasets.py`
- `jobs/submit/submit_batch_model_ready_datasets.py`
- `configs/datasets/datasets.yaml`
- `sql/athena/ddl/gold_model_ready_targets.sql`
- `sql/athena/ddl/gold_model_ready_baselines.sql`

S3 prefixes affected:

- New immutable writes only:
  - `gold/model_ready_targets/dataset_version={new_psd_version}/`
  - `gold/model_ready_matrices/dataset_version={new_psd_version}/`
  - `gold/model_ready_baselines/dataset_version={new_psd_version}/`
  - `gold/model_ready_manifests/dataset_version={new_psd_version}/`

Risks:

- Athena DDL drift if target schema changes.
- Training loader may drop metadata columns unless exclusions are updated.
- Feature-set compatibility may be too broad.

Validation/tests:

- `tests/unit/test_model_ready_datasets.py`
- `tests/unit/test_training_model_ready.py`
- local dry-run model-ready build.

Acceptance criteria:

- New PSD target tables and matrices build without overwriting old versions.
- Manifest records `target_source=psd`, mapping SHA, and config SHA.
- Training loader can train from PSD matrix.

Reversibility:

- Safe and reversible if immutable versioned paths are used.

What not to do:

- Do not make PSD-first dataset the default until dry-run experiments pass.

### Phase 6 - MLflow And Manifest Restructuring

Objective:

- Make MLflow runs and model-ready manifests source-aware, target-family-aware,
  and promotion-ready.

Detailed tasks:

- Back up the MLflow backend database and confirm the S3 artifact root is
  reachable before any MLflow package upgrade.
- Upgrade the EC2 MLflow tracking server from the observed `3.1.4` install to a
  current pinned MLflow 3 release, and record the exact version in the runbook.
- Pin the trainer/client dependency to the same MLflow release family, using
  `mlflow-skinny` in the trainer image because Batch jobs are MLflow clients,
  not the tracking server.
- Rebuild and push the trainer image after the MLflow client pin and PSD
  training changes are present in `main`.
- Verify the SSM tunnel, tracking API, model registry page, metrics charts,
  artifact browser, and logged-model display before launching broad sweeps.
- Add PSD target tags to training.
- Add PSD mapping SHA to run tags and artifacts.
- Add `leakage_audit.json`.
- Add target distribution artifact.
- Update experiment names.
- Add champion-selection report format.
- Run the first PSD Batch smoke only after the server/client versions and
  trainer image are aligned.

Files/configs likely affected:

- `docker/leviathan_trainer/Dockerfile`
- `jobs/batch/train_commodity.py`
- `jobs/submit/submit_batch_train.py`
- `jobs/utils/register_train_jobdef.py`
- `src/leviathan/training/model_ready.py`
- `src/leviathan/training/mlflow_artifacts.py`
- `src/leviathan/training/tracking.py`
- `docs/ops/MLFLOW_UI_ACCESS.md`
- `docs/ops/MLFLOW_AIRFLOW_STATE_RECONCILIATION.md`
- `docs/ops/`

S3 prefixes affected:

- Prediction writes:
  - `silver/model_predictions/model_family=psd_production_anomaly/`
  - `silver/model_predictions/model_family=psd_balance_sheet_anomaly/`
- Training snapshots:
  - `model_artifacts/training_snapshots/{run_id}/`

Risks:

- MLflow backend schema migration risk if the EC2 server is upgraded without a
  fresh SQLite backup.
- MLflow server/client mismatch causing missing artifacts, registry failures, or
  confusing UI behavior.
- Mixing old and new runs in MLflow UI.
- Promoting a model with missing target metadata.

Validation/tests:

- `mlflow --version` on the EC2 tracking host reports the pinned release.
- Trainer container imports the pinned `mlflow-skinny` version and can log a
  fitted LightGBM/XGBoost model.
- SSM tunnel opens `http://localhost:5000`; the UI shows runs, artifacts,
  metric charts, and logged-model entries for the smoke run.
- `tests/unit/test_training_mlflow_artifacts.py`
- `tests/unit/test_training_model_ready.py`
- MLflow replay smoke.

Acceptance criteria:

- MLflow server and trainer client versions are explicitly pinned, documented,
  and compatible.
- MLflow backend backup exists before upgrade and rollback steps are documented.
- One PSD smoke run logs fitted model, tags, artifacts, predictions, and replay
  sample.
- Old FAOSTAT run and new PSD run are clearly distinguishable in MLflow.

Reversibility:

- Mostly safe and reversible if the backend DB is backed up before the MLflow
  upgrade; MLflow runs remain additive.

What not to do:

- Do not upgrade MLflow in place without a backend backup and a rollback path.
- Do not launch broad Batch sweeps until the upgraded UI and trainer image pass a
  one-run PSD smoke.
- Do not expose the MLflow port publicly while improving UI access.
- Do not register/promote production model aliases yet.

### Phase 7 - Cleanup And Deprecation

Objective:

- Prevent future users and jobs from accidentally treating legacy FAOSTAT target
  artifacts as the active PSD-first research surface.

Detailed tasks:

- Mark old model-ready manifests as legacy.
- Add dataset status metadata in configs.
- Update readers to ignore deprecated versions unless explicitly requested.
- Write a legacy dataset inventory.
- Optionally archive old artifacts after manual approval.

Files/configs likely affected:

- `configs/datasets/datasets.yaml`
- possible new `configs/ml/model_dataset_versions.yaml`
- `src/leviathan/training/model_ready.py`
- docs under `docs/ops/`

S3 prefixes affected:

- Metadata-only mark, no deletion:
  - `gold/model_ready_manifests/dataset_version=20260626T104732Z_a2576e84_phase8_model_ready/`

Risks:

- Any manifest rewrite is a mutation. It should be reviewed before execution.
- Deleting old data would break reproducibility.

Validation/tests:

- `tests/unit/test_model_ready_version_selection.py`
- dry-run readers.

Acceptance criteria:

- Deprecated versions are ignored by default discovery.
- Explicit version loading still works.
- No S3 deletion performed.

Reversibility:

- Metadata marking is reversible if versioned.
- S3 deletion is not easily reversible and must be manual-approval-only.

What not to do:

- Do not delete any S3 objects.
- Do not remove old code paths until explicit legacy tests pass.

Safety classification:

- Potentially destructive if cleanup includes deletes. Treat as
  manual-approval-only.

### Phase 8 - Tests

Objective:

- Lock PSD-first behavior and FAOSTAT demotion into regression tests.

Detailed tasks:

- Add PSD mapping tests.
- Add PSD target computation tests.
- Add FAOSTAT lag-policy tests.
- Add feature-set governance tests.
- Add model-ready manifest tests.
- Add MLflow target-tag tests.
- Add deprecated-prefix reader tests.

Files/configs likely affected:

- `tests/unit/test_model_datasets_psd_targets.py`
- `tests/unit/test_psd_target_mapping.py`
- `tests/unit/test_faostat_demotion_policy.py`
- `tests/unit/test_model_ready_datasets.py`
- `tests/unit/test_features_feature_sets.py`
- `tests/unit/test_training_model_ready.py`
- `tests/unit/test_training_mlflow_artifacts.py`

S3 prefixes affected:

- None for unit tests.

Risks:

- Tests may cement wrong PSD mapping if mapping is not reviewed by domain logic.

Validation/tests:

- Full targeted test suite.
- Non-GraphRAG full test suite if feasible.

Acceptance criteria:

- All new tests pass.
- Existing model-ready tests still pass.
- Legacy FAOSTAT targets remain loadable if explicitly requested.

Reversibility:

- Safe and reversible.

What not to do:

- Do not require live AWS for unit tests.

### Phase 9 - Dry-Run Experiment Plan

Objective:

- Prove PSD-first targets train end-to-end before any promotion or cleanup.

Detailed tasks:

- Build PSD-first model-ready dataset locally or in S3 under a new immutable
  version.
- Run one smoke target:
  - `corn_cbot`
  - `psd_production_anomaly_pct`
  - `preseason_physical`
  - `xgboost`
- Run small grid:
  - `corn_cbot`
  - feature sets:
    - `preseason_physical`
    - `balance_sheet`
    - `inseason_weather`
    - `crop_condition`
    - `tail_risk`
  - models:
    - `xgboost`
    - `lightgbm`
- Compare against baselines.

Files/configs likely affected:

- No code if previous phases complete.
- `data/batch_runs/` may record submissions.

S3 prefixes affected:

- Additive:
  - `gold/model_ready_* /dataset_version={new_psd_version}/`
  - `silver/model_predictions/model_family=psd_production_anomaly/`
  - `model_artifacts/training_snapshots/{run_id}/`

Risks:

- Small annual samples can overfit.
- PSD aggregate targets may be proxies for some contracts.

Validation/tests:

- MLflow replay certification.
- Baseline comparison.
- Gap checks.
- Slice checks by country and stress year.

Acceptance criteria:

- Smoke run completes.
- Fitted model artifact replays exactly.
- Baseline comparisons are logged.
- Target metadata tags are present.
- No legacy FAOSTAT target source confusion in MLflow.

Reversibility:

- Safe and reversible; all writes are additive immutable versions/runs.

What not to do:

- Do not promote model to production.
- Do not delete old model-ready datasets.

### Phase 10 - Production Promotion Criteria

Objective:

- Define when a PSD-first model can become a production candidate.

Detailed tasks:

- Define per-target acceptance gates.
- Define champion/challenger registry policy.
- Define model freshness and inference cadence.
- Define frontend chart-readiness fields later, after production-readiness.

Files/configs likely affected:

- `configs/training/acceptable_gaps.yaml`
- potential `configs/ml/promotion_criteria.yaml`
- `docs/ops/`
- MLflow registry scripts if added.

S3 prefixes affected:

- Additive:
  - `silver/model_predictions/model_family=psd_*`
  - future champion manifest prefix, if created

Risks:

- Promoting a model that beats RMSE but fails stress-year direction.
- Promoting aggregate PSD proxy targets as contract-specific truth.

Validation/tests:

- Champion report generation.
- MLflow run completeness check.
- Replay check.
- Slice gap check.
- Baseline comparison.

Acceptance criteria:

- Candidate beats zero/trend baseline.
- Candidate is competitive with prior-year baseline.
- Hard gap checks pass or are explicitly waived.
- SHAP/feature importance is economically plausible.
- Target metadata is complete.
- Model artifact replays.
- Data version, feature set SHA, target config SHA, and PSD mapping SHA are
  logged.

Reversibility:

- Production alias promotion is reversible.
- S3 deletion is out of scope.

What not to do:

- Do not promote based on one headline metric.
- Do not promote if target source or proxy status is ambiguous.

## L. Risks And Open Questions

### Risks

1. PSD latest-release labels may revise historically and change targets.
2. PSD aggregate commodities may not map cleanly to contract-specific futures.
3. Coffee and wheat split contracts need proxy warnings.
4. FAOSTAT source-disagreement features can leak if not conservatively lagged.
5. Annual panels are small; model overfit remains a risk.
6. Athena DDL for `gold_model_ready_targets` must change if target metadata
   columns are added.
7. Old model-ready datasets can mislead researchers if not marked legacy.

### Open Questions

1. Should PSD final labels use latest release in silver or a fixed finalization
   window?
2. Should target `country` be strictly the geography origin, PSD country, or a
   mapping between both?
3. Which contracts should be allowed to use aggregate PSD proxies?
4. Should coffee PSD aggregate be allowed for `arabica_coffee` and
   `robusta_coffee`, or should local agency targets be primary for coffee?
5. Should `su_ratio` be modeled directly as a ratio anomaly, or should stocks
   and use be modeled separately first?
6. Should FAOSTAT capacity features start as `diagnostic_only` until a leakage
   audit proves safety?
7. Should old MLflow runs be backfilled with legacy tags or left untouched with
   a separate run inventory?

## M. Exact Commands For Later After Approval

These commands are examples for later execution after implementation approval.
They were not run during this planning pass.

### Read-Only Inventory Commands

```powershell
aws s3 ls s3://leviathan-dev-shahem-001/gold/model_ready_targets/ --recursive --summarize
aws s3 ls s3://leviathan-dev-shahem-001/gold/model_ready_matrices/ --recursive --summarize
aws s3 ls s3://leviathan-dev-shahem-001/silver/psd/ --recursive --summarize
```

### Local Unit Tests

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests\unit\test_model_datasets_psd_targets.py `
  tests\unit\test_psd_target_mapping.py `
  tests\unit\test_faostat_demotion_policy.py `
  tests\unit\test_model_ready_datasets.py `
  tests\unit\test_features_feature_sets.py `
  tests\unit\test_training_model_ready.py `
  tests\unit\test_training_mlflow_artifacts.py
```

### Future Model-Ready Build Dry Run

```powershell
.\.venv\Scripts\python.exe jobs\batch\build_model_ready_datasets.py `
  --source-dataset-version 20260626T010217Z_6725de02_phase7_full `
  --model-dataset-version YYYYMMDDTHHMMSSZ_psd_first_dry_run `
  --commodities corn_cbot `
  --target-keys psd_production_anomaly_pct `
  --workers 4 `
  --dry-run
```

### Future PSD Smoke Training Run

```powershell
.\.venv\Scripts\python.exe jobs\batch\train_commodity.py `
  --model-dataset-version YYYYMMDDTHHMMSSZ_psd_first `
  --dataset-key psd_production_anomaly `
  --target-key psd_production_anomaly_pct `
  --commodity corn_cbot `
  --feature-set preseason_physical `
  --model xgboost `
  --min-train-years 10 `
  --experiment leviathan-psd-production-anomaly
```

### Future Small Experiment Grid

```powershell
.\.venv\Scripts\python.exe jobs\submit\submit_batch_train.py `
  --model-dataset-version YYYYMMDDTHHMMSSZ_psd_first `
  --commodities corn_cbot `
  --feature-sets preseason_physical,balance_sheet,inseason_weather,crop_condition,tail_risk `
  --dataset-keys psd_production_anomaly `
  --target-keys psd_production_anomaly_pct `
  --models xgboost,lightgbm `
  --experiment leviathan-psd-production-anomaly `
  --dry-run
```

### Manual-Approval-Only Cleanup Notes

No deletion command should be run from this plan.

If cleanup is later approved, first perform only inventory and archive-copy
operations. S3 deletion commands should be written in a separate, reviewed
cleanup runbook with exact approved prefixes and rollback expectations.
