# WASDE Balance Sheet Snapshot Rebuild Plan

## Executive Summary

The recent WASDE snapshot smoke job did not produce bad model evaluations. It produced
no meaningful model evaluations because the selected WASDE feature stack had zero
usable columns after quality gates.

That is a model-ready dataset construction failure, not a final judgment on WASDE,
XGBoost, LightGBM, or the balance-sheet modeling idea.

The current failure mode is clear:

- `silver/wasde/` is rich: hundreds of releases and hundreds of thousands of rows.
- The active corn snapshot matrix is thin: only a few hundred rows and seven WASDE
  dynamic columns.
- Those seven WASDE columns are populated in only about 1.7% to 4.8% of rows.
- The current snapshot surface mixes generic crop-calendar snapshot dates with a
  narrow WASDE adapter that mostly emits `revision_z` columns.
- It does not exploit dense WASDE `estimate` values, stock/use levels, latest
  visible estimates, revision since first forecast, release sequence, or monthly
  release-date rows.

The fix is to rebuild the WASDE model-ready surface around actual point-in-time
release snapshots and balance-sheet targets.

Primary target family for the next serious experiment:

```text
psd_stock_to_use_anomaly_pct
psd_ending_stocks_anomaly_pct
```

Production anomaly should be frozen as a diagnostic target until the balance-sheet
surface is working.

The professional model-ready row grain should be:

```text
contract_key
origin
target_market_year
target_key
as_of_date
snapshot_stage
```

For WASDE experiments, `as_of_date` should primarily be an actual WASDE release date,
not a synthetic June/July placeholder.

Daily inference is still a valid goal, but it should be built after the release-date
snapshot surface is correct. Daily inference rows should forward-fill the latest
known point-in-time values and use grouped validation and sample weights so repeated
daily rows do not masquerade as independent annual outcomes.

## Non-Negotiable Design Rules

1. No more wide sweeps until WASDE feature density passes.
2. No production-target-first modeling for now.
3. No raw futures prices as fundamental features.
4. No same-year final PSD values as same-year features.
5. No feature whose source availability is after `as_of_date`.
6. No train/test split that puts different snapshots from the same
   `(contract_key, origin, target_market_year, target_key)` group on both sides.
7. Every annual outcome group must have controlled sample weight, especially if
   expanded to monthly or daily snapshots.
8. Every failed candidate must explain whether it failed because of data construction,
   feature quality, target quality, CV, model performance, or infrastructure.

## Observed Facts From Current System

These are facts observed from the current code and S3 state during the failed smoke:

- `silver/wasde/` contains 461 parquet release partitions.
- `silver/wasde/` contains about 580,871 rows.
- Corn WASDE silver contains about 67,163 rows.
- Corn WASDE has usable `estimate` and `revision` values for key regions and
  attributes, including United States, Argentina, Brazil, and Ukraine.
- The active corn snapshot matrix for `psd_production_anomaly_pct` contained 482 rows.
- The active matrix contained only seven WASDE dynamic columns:

```text
wasde_latest_revision
wasde_consecutive_revision_count
wasde_production_revision_z
wasde_ending_stocks_revision_z
wasde_exports_revision_z
wasde_domestic_use_revision_z
wasde_total_use_revision_z
```

- The best-populated WASDE dynamic column had only 23 non-null rows out of 482.
- The feature selector correctly dropped the whole pure WASDE stack because all
  selected WASDE features failed the minimum density policy.

Important interpretation:

The gates are not the blocker. The gates are the alarm. The upstream feature surface
is underbuilt.

## Target End State

The rebuilt model-ready system should produce these first-class model surfaces:

```text
corn_wasde_snapshot_solo
corn_wasde_snapshot_with_static
corn_wasde_snapshot_with_substitutes
grains_wasde_snapshot_segment
```

The first serious target keys should be:

```text
psd_stock_to_use_anomaly_pct
psd_ending_stocks_anomaly_pct
```

The first serious model objective should be:

> Given all official balance-sheet and fundamental information visible as of a WASDE
> release date, predict whether the final balance-sheet outcome for that contract
> origin and market year will be abnormally tight or loose.

The primary business evaluation should not be only RMSE. It should include:

- Did the model beat prior-year and trailing baselines?
- Did it catch tightening years?
- Did false negatives fall?
- Did recall and F2 improve for stress events?
- Did performance survive grouped walk-forward CV?
- Did permutation tests collapse toward random?
- Did feature importance make economic sense?

## Proposed Model-Ready Grain

### Snapshot Row Grain

```text
contract_key
origin
target_market_year
target_key
as_of_date
snapshot_stage
```

Example:

```text
corn_cbot, united_states, 2024, psd_stock_to_use_anomaly_pct, 2024-05-10, preseason
corn_cbot, united_states, 2024, psd_stock_to_use_anomaly_pct, 2024-06-12, early_season
corn_cbot, united_states, 2024, psd_stock_to_use_anomaly_pct, 2024-07-12, early_season
corn_cbot, united_states, 2024, psd_stock_to_use_anomaly_pct, 2024-08-12, midseason
```

### Snapshot Stage

The row should be created by a real information date. `snapshot_stage` should be a
derived label, not the source of truth for the row.

Suggested first-pass stage mapping:

```text
May-Jun: preseason
Jul-Aug: early_season
Sep-Oct: midseason
Nov-Dec: late_season
Jan-Feb: post_harvest
Mar-Apr: finalization
```

This mapping can later become crop-calendar aware by origin.

### Annual Outcome Group

The independent validation group is:

```text
contract_key
origin
target_market_year
target_key
```

Every monthly or daily row inside the same group shares the same final target outcome.
Therefore grouped CV and sample weights are mandatory.

## Proposed Feature Families

### Dense WASDE Attribute Features

For each supported WASDE attribute:

```text
production
ending_stocks
exports
imports
domestic_total
total_use
feed
feed_residual
beginning_stocks
total_supply
```

Emit:

```text
wasde_{attribute}_latest
wasde_{attribute}_latest_z_by_release_sequence
wasde_{attribute}_latest_vs_trend_pct
wasde_{attribute}_mom_revision
wasde_{attribute}_revision_since_first
wasde_{attribute}_latest_vs_first_forecast_pct
wasde_{attribute}_consecutive_revision_count
```

Notes:

- `latest` uses the latest visible `estimate` as of `as_of_date`.
- `mom_revision` can use `revision` if reliable, or recompute from estimates inside
  the same market year and attribute.
- `latest_z_by_release_sequence` compares the current estimate to historical
  estimates at the same release sequence, using only prior market years.
- `latest_vs_trend_pct` uses only prior years.

### Cross-Attribute WASDE Balance-Sheet Features

Emit:

```text
wasde_total_supply_estimate
wasde_total_use_estimate
wasde_stock_to_use_estimate
wasde_stock_to_use_mom_revision
wasde_stock_to_use_revision_since_first
wasde_stock_to_use_latest_vs_trend_pct
wasde_stock_to_use_latest_z_by_release_sequence
```

Useful derived identities:

```text
total_supply = beginning_stocks + production + imports
total_use = domestic_total + exports
stock_to_use = ending_stocks / total_use
```

If the source has official total supply/use, prefer the official value, but retain
computed fallback when all components are present.

### Snapshot Timing Features

Emit:

```text
wasde_release_sequence
wasde_visible_release_count
wasde_snapshot_month_code
wasde_months_since_first_forecast
wasde_is_first_estimate
wasde_is_latest_visible_release
months_to_marketing_year_end
```

These features help the model learn that a June forecast and a January estimate do
not carry the same information content.

### Static Features To Join Later

The release-date snapshot should support optional PIT-safe joins of cleaned static
and slower-moving features:

```text
preseason physical context
lagged FAOSTAT/PSD capacity context
ONI/IOD climate context
Pink Sheet economic drivers
FX features
dense weather aggregates
NASS crop progress where relevant
ESR/FGIS physical flow where relevant
```

Static features must be joined by:

```text
country/origin
crop_year or target_market_year
as_of_date availability
```

No same-year final values should be admitted.

### Substitute Features

For `corn_wasde_snapshot_with_substitutes`, add clearly namespaced features:

```text
sub_wheat_wasde_stock_to_use_estimate
sub_wheat_wasde_ending_stocks_revision_since_first
sub_soybeans_wasde_exports_revision_since_first
sub_soybean_meal_wasde_domestic_total_latest_vs_trend_pct
```

Substitute features must obey the same `source_release_date <= as_of_date` rule.

## Phase 0 - Freeze Bad Surfaces And Define The RCA Boundary

### Objective

Stop spending Batch money on model candidates that are failing because the feature
surface is underbuilt.

### Phase 0 Implementation Guardrail

The 2026-06-29 Batch smoke should be recorded with this classification:

```text
failure_class = construction_failure
failure_subclass = zero_usable_wasde_snapshot_features
dataset_version = 20260628T021248Z_phase0_wasde_snapshot
dataset_key = psd_snd_anomaly_snapshot
commodity = corn_cbot
target_key = psd_production_anomaly_pct
feature_set = wasde_monthly_revision
feature_stack = wasde_monthly_revision
model = lightgbm
```

This candidate did not produce valid CV metrics. It should not be cited as evidence
that balance-sheet models, WASDE features, LightGBM, or XGBoost are unproductive.
It is evidence that the current model-ready feature surface is underbuilt.

Operational guardrail:

- no broad snapshot certification grid from this dataset version;
- no production-anomaly-first WASDE snapshot smoke;
- no pure `wasde_monthly_revision` standalone smoke until Phase 2/3 rebuilds the
  release-date feature surface and feature density passes;
- use stock/use and ending-stocks targets for the next controlled smoke.

### Tasks

1. Mark the current failed smoke as a construction failure:
   - training status: `failed_cv`
   - cause: `wasde_monthly_revision selected zero usable features`
   - category: model-ready data failure
2. Freeze production-anomaly experiments as non-primary.
3. Freeze the current pure `wasde_monthly_revision` feature set for serious sweeps.
4. Keep existing S3 artifacts for traceability.
5. Add a short operational note in the relevant docs or manifest explaining why the
   current candidate is diagnostic only.

### Files Likely Affected

```text
docs/WASDE_SNAPSHOT_ANOMALY_MODELING_PLAN.md
docs/FEATURE_DIAGNOSTICS_REMEDIATION_PLAN.md
configs/ml/phase_snapshot_candidate_grid.yaml
configs/features/feature_sets.yaml
```

### S3 Prefixes Affected

Read-only or metadata-only:

```text
s3://leviathan-dev-shahem-001/model_artifacts/snapshot_candidate_certification/
s3://leviathan-dev-shahem-001/gold/model_ready_matrices/
s3://leviathan-dev-shahem-001/gold/model_ready_manifests/
```

No deletion.

### Risks

- Future agents may misread the failed smoke as a model result.
- If not documented, someone may launch wider sweeps on the broken feature stack.

### Validation

- Confirm no active phase grid defaults to pure `wasde_monthly_revision` without a
  density check.
- Confirm production anomaly is not the default target for the next WASDE phase.

### Acceptance Criteria

- Current failed candidate is classified as a feature construction failure.
- No broader Batch sweep is launched from the broken surface.

### Reversibility

Safe and reversible. This is documentation/config hygiene.

### Explicitly Do Not

- Do not delete S3 artifacts.
- Do not prune historical model reports.
- Do not run new model grids.

## Phase 1 - WASDE Source Truth Audit

### Objective

Prove exactly what `silver/wasde/` can support before rebuilding features.

### Tasks

Build a source audit over `silver/wasde/` with grain:

```text
commodity
region
marketing_year
attribute
```

Compute:

```text
release_count
first_release_date
last_release_date
estimate_non_null_count
revision_non_null_count
first_estimate_release_date
last_estimate_release_date
release_months_present
release_sequence_count
region_quality_class
attribute_quality_class
```

For corn specifically, produce origin coverage for:

```text
united_states
argentina
brazil
ukraine
```

And attributes:

```text
production
ending_stocks
exports
imports
domestic_total
total_use
feed
beginning_stocks
total_supply
```

Also audit parser artifacts:

- weird region names that contain numeric fragments;
- duplicate release/commodity/region/market-year/attribute cells;
- conflicting duplicate estimates;
- missing `revision` where estimates are available;
- table type conflicts between US and world tables.

### Files Likely Affected

```text
jobs/utils/audit_wasde_snapshot_inputs.py
src/leviathan/model_datasets/wasde_snapshot_audit.py
tests/unit/test_wasde_snapshot_audit.py
```

### S3 Prefixes Affected

Read:

```text
s3://leviathan-dev-shahem-001/silver/wasde/
```

Write audit artifacts:

```text
s3://leviathan-dev-shahem-001/model_artifacts/wasde_snapshot_audits/dataset_version={version}/
```

Optional local audit outputs:

```text
data/phase_wasde_snapshot/
```

### Risks

- The audit may reveal that some non-US origins have shorter usable histories than
  PSD target histories.
- WASDE region naming may require mapping repairs.
- Revision values may be less reliable than estimates for some attributes.

### Validation

Tests:

```text
tests/unit/test_wasde_snapshot_audit.py::test_source_audit_counts_release_density
tests/unit/test_wasde_snapshot_audit.py::test_source_audit_flags_parser_artifact_regions
tests/unit/test_wasde_snapshot_audit.py::test_source_audit_tracks_revision_vs_estimate_coverage
tests/unit/test_wasde_snapshot_audit.py::test_source_audit_reports_origin_attribute_coverage
```

Data validation:

- corn has non-empty release coverage after 1985;
- each active corn target origin has coverage report;
- no origin is silently dropped;
- audit includes exact missing reasons.

### Acceptance Criteria

- A machine-readable audit exists.
- The audit states which commodity/origin/attribute combinations are fit for:
  - core modeling;
  - secondary sparse features;
  - diagnostic only;
  - blocked.
- Corn balance-sheet attributes have enough coverage to proceed.

### Reversibility

Safe and reversible. This phase is read-only plus new audit artifacts.

### Explicitly Do Not

- Do not rebuild model-ready matrices yet.
- Do not change model targets yet.
- Do not run ML certification jobs.

## Phase 2 - Rebuild Dense WASDE Dynamic Feature Builder

### Objective

Replace the thin WASDE adapter with a dense point-in-time feature builder based on
visible estimates and release sequences, not only sparse `revision_z` columns.

### Tasks

1. Create or refactor the dynamic builder to accept:

```text
wasde_df
snapshot_spine
mapping_config
attribute_config
min_history_years
```

2. Normalize source rows:

```text
release_date
wasde_commodity
wasde_origin
target_market_year
attribute
estimate
revision
table_type
```

3. Deduplicate source rows deterministically:
   - prefer US table for United States;
   - prefer world table for non-US origins;
   - prefer rows with non-null estimate and revision;
   - raise on unresolved conflicting duplicates.

4. Compute release sequence per:

```text
wasde_commodity
wasde_origin
target_market_year
```

5. Compute feature values as of each `as_of_date`:
   - latest visible estimate;
   - latest visible revision;
   - revision since first forecast;
   - month-over-month revision from estimates if source revision is missing;
   - latest vs first forecast percent;
   - consecutive revision count;
   - release sequence;
   - months since first forecast;
   - stock/use estimates and revisions.

6. Compute historical normalizations using only prior market years:
   - z-score at same release sequence;
   - rolling historical z-score;
   - trailing trend percent deviation.

7. Emit explicit feature availability metadata:

```text
source_release_date_max
source_release_count_visible
feature_available_at
feature_source_vintage
```

### Files Likely Affected

```text
src/leviathan/model_datasets/wasde_snapshot_features.py
src/leviathan/model_datasets/wasde_snapshot.py
src/leviathan/model_datasets/wasde_snapshot_mapping.py
configs/ml/wasde_snapshot_mappings.yaml
tests/unit/test_wasde_snapshot_features.py
tests/unit/test_wasde_snapshot_mapping.py
```

### S3 Prefixes Affected

No required writes in this phase except optional local test fixtures.

### Risks

- Recomputed revisions may differ from source-provided `revision`.
- Some attributes may not exist consistently across all regions.
- Z-scores can be unavailable early in history due to insufficient prior years.

### Validation

Tests:

```text
tests/unit/test_wasde_snapshot_features.py::test_latest_estimate_features_are_dense
tests/unit/test_wasde_snapshot_features.py::test_mom_revision_uses_estimate_diff_when_source_revision_missing
tests/unit/test_wasde_snapshot_features.py::test_revision_since_first_forecast
tests/unit/test_wasde_snapshot_features.py::test_stock_to_use_estimate_from_components
tests/unit/test_wasde_snapshot_features.py::test_historical_zscore_uses_only_prior_years
tests/unit/test_wasde_snapshot_features.py::test_latest_vs_trend_uses_only_prior_years
tests/unit/test_wasde_snapshot_features.py::test_future_release_rows_are_rejected
tests/unit/test_wasde_snapshot_features.py::test_duplicate_conflicting_cells_raise
```

Data validation:

- Core latest estimate features should be materially denser than old `_revision_z`
  features.
- Sparse revision features may remain sparse, but they must not be the only core
  features in the set.
- Every non-null feature must have `source_release_date_max <= as_of_date`.

### Acceptance Criteria

- Dense WASDE latest and stock/use features exist.
- Feature quality report no longer shows zero usable WASDE features for corn.
- The builder can explain why any feature is sparse.

### Reversibility

Safe if implemented behind a new builder path or version flag. Existing matrices are
not overwritten.

### Explicitly Do Not

- Do not lower quality gates to force sparse columns through.
- Do not use future releases to fill earlier snapshots.
- Do not include raw futures prices.

## Phase 3 - Build Release-Date Snapshot Matrix

### Objective

Build model-ready rows from real WASDE release dates.

### Tasks

1. Create a snapshot spine from WASDE releases:

```text
contract_key
wasde_commodity
origin
target_market_year
as_of_date = release_date
snapshot_stage = derived_stage(as_of_date)
```

2. Join target outcomes from PSD target panels:

```text
target_key
target_value
target_event_label
target_event_threshold
target_event_direction
is_trainable
```

3. Support these dataset keys:

```text
corn_wasde_snapshot_solo
corn_wasde_snapshot_with_substitutes
grains_wasde_snapshot_segment
```

4. Preserve grouped CV metadata:

```text
cv_group = contract_key + origin + target_market_year + target_key
cv_time = target_market_year
sample_weight = 1.0 / snapshot_count_for_group
```

5. Drop or mark snapshots before the first visible WASDE row for that
   origin/market-year.

6. Record snapshot count per annual group.

### Files Likely Affected

```text
src/leviathan/model_datasets/wasde_snapshot_targets.py
src/leviathan/model_datasets/wasde_snapshot_model_ready.py
src/leviathan/model_datasets/psd_model_ready.py
jobs/batch/build_model_ready_datasets.py
tests/unit/test_wasde_snapshot_targets.py
tests/unit/test_wasde_snapshot_model_ready.py
```

### S3 Prefixes Affected

Write new immutable versions only:

```text
s3://leviathan-dev-shahem-001/gold/model_ready_targets/dataset_version={new_version}/
s3://leviathan-dev-shahem-001/gold/model_ready_matrices/dataset_version={new_version}/
s3://leviathan-dev-shahem-001/gold/model_ready_baselines/dataset_version={new_version}/
s3://leviathan-dev-shahem-001/gold/model_ready_manifests/dataset_version={new_version}/
```

Do not overwrite existing dataset versions.

### Risks

- Snapshot row count increases but independent annual groups do not.
- If sample weights are wrong, years with many releases can dominate.
- Release history may be shorter for Brazil/Ukraine than US.

### Validation

Tests:

```text
tests/unit/test_wasde_snapshot_targets.py::test_release_dates_create_snapshot_rows
tests/unit/test_wasde_snapshot_targets.py::test_snapshot_stage_is_derived_from_release_date
tests/unit/test_wasde_snapshot_model_ready.py::test_sample_weights_sum_to_one_per_annual_group
tests/unit/test_wasde_snapshot_model_ready.py::test_cv_group_blocks_same_annual_outcome
tests/unit/test_wasde_snapshot_model_ready.py::test_no_snapshot_after_target_finalization_if_policy_blocks_it
tests/unit/test_wasde_snapshot_model_ready.py::test_no_duplicate_snapshot_natural_keys
```

Data validation:

- row count increases relative to current 482 for corn;
- snapshot count per group is reasonable;
- no duplicate natural keys;
- `sample_weight` sums to 1.0 per annual group;
- matrix includes non-null dense WASDE features.

### Acceptance Criteria

- Corn release-date matrix exists for stock/use and ending-stocks targets.
- Core WASDE feature density passes quality gates.
- Matrix manifest records source release coverage and target coverage.

### Reversibility

Safe and reversible. New dataset versions are immutable.

### Explicitly Do Not

- Do not replace old annual matrices.
- Do not delete old snapshot matrices.
- Do not treat monthly rows as independent in CV.

## Phase 4 - Balance-Sheet Target Surface

### Objective

Make balance-sheet stress the primary model objective.

### Tasks

1. Promote these targets for active snapshot experiments:

```text
psd_stock_to_use_anomaly_pct
psd_ending_stocks_anomaly_pct
```

2. Treat these as secondary after the first pass:

```text
psd_exports_anomaly_pct
psd_imports_anomaly_pct
psd_domestic_use_anomaly_pct
```

3. Freeze as diagnostic:

```text
psd_production_anomaly_pct
```

4. Define stress event labels:

```text
stock_to_use_tightness_event
ending_stocks_tightness_event
```

5. Use lower-is-stress event direction for stock/use and ending stocks.

6. Review anomaly denominator handling:
   - reject zero or near-zero trend denominator;
   - mark as non-trainable if target is unstable;
   - track excluded reason.

### Files Likely Affected

```text
configs/ml/psd_metric_targets.yaml
configs/ml/target_definitions.yaml
src/leviathan/model_datasets/psd_target_builder.py
src/leviathan/model_datasets/wasde_snapshot_targets.py
tests/unit/test_psd_target_mapping.py
tests/unit/test_wasde_snapshot_targets.py
```

### S3 Prefixes Affected

New immutable target and matrix versions only:

```text
s3://leviathan-dev-shahem-001/gold/model_ready_targets/dataset_version={new_version}/
s3://leviathan-dev-shahem-001/gold/model_ready_matrices/dataset_version={new_version}/
```

### Risks

- Some contracts may not have clean PSD stock/use data.
- Stock/use ratio units may differ by source or commodity.
- Events may be too common or too rare depending on threshold.

### Validation

Tests:

```text
tests/unit/test_psd_target_mapping.py::test_stock_to_use_target_uses_lower_is_stress
tests/unit/test_psd_target_mapping.py::test_ending_stocks_target_uses_lower_is_stress
tests/unit/test_wasde_snapshot_targets.py::test_balance_sheet_event_labels_are_group_constant
tests/unit/test_wasde_snapshot_targets.py::test_near_zero_trend_denominator_marks_non_trainable
```

Data validation:

- event share is reported by origin and decade;
- no target has pathological max/min from tiny denominators;
- trainable group count is sufficient.

### Acceptance Criteria

- Balance-sheet targets become the default for the next WASDE snapshot smoke.
- Production target is no longer the first-line certification target.

### Reversibility

Safe. This changes defaults and new dataset versions, not historical artifacts.

### Explicitly Do Not

- Do not delete production target code.
- Do not pretend production is invalid forever. It is just not the first serious
  model target.

## Phase 5 - Static, Flow, Weather, And Substitute Feature Stacks

### Objective

Combine dense WASDE dynamics with the cleaned feature universe without reintroducing
leakage or garbage columns.

### Candidate Feature Stacks

```text
corn_wasde_snapshot_solo
```

Dense corn WASDE features only.

```text
corn_wasde_snapshot_with_static
```

Dense corn WASDE features plus cleaned static fundamentals.

```text
corn_wasde_snapshot_with_substitutes
```

Dense corn WASDE features plus static fundamentals plus wheat/soy/feed/energy context.

```text
grains_wasde_snapshot_segment
```

Corn, wheat, and rice pooled by segment, but with contract-specific outputs retained.

### Tasks

1. Define explicit feature-stack configs.
2. Namespace substitute features.
3. Join static features with availability controls.
4. Allow feature blocks only if they pass policy:

```text
feature_policy != diagnostic_only
feature_policy != excluded_market_signal
feature_available_at <= as_of_date
```

5. Include missingness flags only where they are known before `as_of_date`.
6. Generate feature membership and quality artifacts for each stack.

### Files Likely Affected

```text
configs/features/feature_sets.yaml
configs/features/feature_taxonomy.yaml
configs/ml/phase_snapshot_candidate_grid.yaml
src/leviathan/model_datasets/wasde_snapshot_static_join.py
src/leviathan/model_datasets/wasde_snapshot_model_ready.py
tests/unit/test_wasde_snapshot_static_join.py
tests/unit/test_wasde_snapshot_model_ready.py
```

### S3 Prefixes Affected

New immutable feature-set artifacts:

```text
s3://leviathan-dev-shahem-001/gold/model_ready_feature_sets/dataset_version={new_version}/
s3://leviathan-dev-shahem-001/gold/model_ready_matrices/dataset_version={new_version}/
```

### Risks

- Static features may be annual and not truly known by early `as_of_date`.
- Substitute features can create accidental target leakage if they include same-year
  final PSD values.
- Too many features relative to annual groups can overfit.

### Validation

Tests:

```text
tests/unit/test_wasde_snapshot_static_join.py::test_static_feature_available_at_must_not_exceed_as_of_date
tests/unit/test_wasde_snapshot_static_join.py::test_same_year_psd_final_context_is_blocked
tests/unit/test_wasde_snapshot_static_join.py::test_substitute_features_are_namespaced
tests/unit/test_wasde_snapshot_model_ready.py::test_composite_stack_has_wasde_and_static_columns
tests/unit/test_wasde_snapshot_model_ready.py::test_diagnostic_only_features_are_excluded
```

Data validation:

- every selected feature has a policy;
- no known leaky feature enters the model-ready matrix;
- feature count is reasonable relative to annual groups;
- sparse feature count is reported.

### Acceptance Criteria

- Three corn stacks are available for smoke:
  - solo;
  - static;
  - substitutes.
- No stack emits zero usable features.

### Reversibility

Safe. New feature-set definitions and new immutable matrices.

### Explicitly Do Not

- Do not combine every possible feature blindly.
- Do not admit `diagnostic_only` or `excluded_market_signal` features into core
  candidates.

## Phase 6 - Daily Inference Viability Report

### Objective

Decide how to support daily inference professionally without lying to ourselves
about sample size.

### Key Principle

Daily inference rows are useful for serving and charting, but they do not create
daily independent labels for annual outcomes.

### Tasks

1. Build a feature availability taxonomy:

```text
daily_updating
weekly_updating
monthly_updating
annual_static
event_release_based
unknown_release_lag
```

2. Classify core sources:

```text
WASDE: monthly/event release, forward-fill after release
NASS crop progress: weekly, forward-fill after report date
ESR/FGIS: weekly, forward-fill after report date
weather: daily, rolling aggregates up to date
Pink Sheet: monthly, release-lagged and forward-filled
FX: daily if source supports it, otherwise current cadence
FAOSTAT/PSD final context: lagged only
```

3. Define daily row grain:

```text
contract_key
origin
target_market_year
target_key
as_of_date
```

4. Define sample weights:

```text
sample_weight = 1.0 / number_of_rows_in_annual_outcome_group
```

5. Decide which sources are ready for daily model-ready and which are not.

### Files Likely Affected

```text
configs/features/feature_taxonomy.yaml
configs/datasets/source_contracts.yaml
src/leviathan/features/availability.py
src/leviathan/model_datasets/wasde_snapshot_model_ready.py
jobs/utils/audit_daily_inference_viability.py
tests/unit/test_features_availability.py
tests/unit/test_wasde_snapshot_model_ready.py
```

### S3 Prefixes Affected

Audit only at first:

```text
s3://leviathan-dev-shahem-001/model_artifacts/daily_inference_viability/
```

No daily matrix should be written until the release-date matrix passes.

### Risks

- Daily rows can falsely inflate apparent sample size.
- Forward-fill logic can leak if release dates are wrong.
- Some sources may not have reliable release dates.

### Validation

Tests:

```text
tests/unit/test_features_availability.py::test_monthly_source_forward_fill_starts_after_release_lag
tests/unit/test_features_availability.py::test_weekly_source_forward_fill_uses_report_date
tests/unit/test_features_availability.py::test_daily_weather_rollups_use_only_prior_days
tests/unit/test_wasde_snapshot_model_ready.py::test_daily_sample_weights_sum_to_one_per_group
```

### Acceptance Criteria

- Daily viability report exists.
- It clearly says which features can be used daily now, which need release-date
  repairs, and which should remain annual/static.
- No daily training matrix is built until release-date snapshot quality passes.

### Reversibility

Safe. Audit-only until explicitly promoted.

### Explicitly Do Not

- Do not train daily rows as independent observations.
- Do not run daily model sweeps yet.

## Phase 7 - Quality Gates And Root-Cause Reporting

### Objective

Make quality gates stricter and more useful, so they tell us exactly what failed.

### Gates

Feature gates:

- no all-null selected features;
- no constant selected features unless explicitly allowed;
- core WASDE latest/stock-use features must pass density thresholds;
- sparse revision features can be secondary, not required core;
- feature count must be sane relative to annual groups;
- non-numeric selected columns are blocked;
- missingness flags must be available at `as_of_date`.

Target gates:

- enough trainable annual groups;
- enough stress events;
- no tiny-denominator anomaly explosions;
- target distribution by origin and decade is reported.

CV gates:

- no annual group appears in both train and validation;
- validation years are strictly after training years;
- sample weights sum to 1.0 per annual group.

Leakage gates:

- no future source release;
- no same-year final PSD context;
- no target-derived label columns;
- no preprocessing fitted on validation data.

### Files Likely Affected

```text
src/leviathan/training/feature_diagnostics.py
src/leviathan/model_datasets/feature_pruning.py
src/leviathan/training/wasde_snapshot_cv.py
jobs/batch/certify_snapshot_model_candidate.py
tests/unit/test_wasde_snapshot_diagnostics.py
tests/unit/test_wasde_snapshot_cv.py
tests/unit/test_training_feature_diagnostics.py
```

### S3 Prefixes Affected

Certification and diagnostics:

```text
s3://leviathan-dev-shahem-001/model_artifacts/snapshot_candidate_certification/
s3://leviathan-dev-shahem-001/model_artifacts/feature_diagnostics/
```

### Risks

- If gates are too strict, they may block early-stage exploration.
- If gates are too loose, they will let broken columns into expensive sweeps.

### Validation

Tests:

```text
tests/unit/test_wasde_snapshot_diagnostics.py::test_zero_usable_features_reports_construction_failure
tests/unit/test_wasde_snapshot_diagnostics.py::test_sparse_core_wasde_features_block_candidate
tests/unit/test_wasde_snapshot_diagnostics.py::test_sparse_secondary_revision_features_warn_only
tests/unit/test_wasde_snapshot_cv.py::test_grouped_cv_never_splits_annual_group
tests/unit/test_training_feature_diagnostics.py::test_preprocessing_is_fold_local
```

### Acceptance Criteria

- A failed candidate report says one of:
  - construction failure;
  - feature quality failure;
  - target quality failure;
  - CV failure;
  - model performance failure;
  - infrastructure failure.
- No more ambiguous "shitty evals" without root cause.

### Reversibility

Safe. This improves reporting and gating.

### Explicitly Do Not

- Do not lower gates globally to make a run pass.
- Do not hide failed features from reports.

## Phase 8 - Controlled Smoke Experiments

### Objective

Run only enough jobs to prove whether the rebuilt surface works.

### Candidate Order

1. `corn_wasde_snapshot_solo`
2. `corn_wasde_snapshot_with_static`
3. `corn_wasde_snapshot_with_substitutes`

Targets:

```text
psd_stock_to_use_anomaly_pct
psd_ending_stocks_anomaly_pct
```

Models:

```text
lightgbm
xgboost
```

Regularized settings only.

### Suggested Initial Hyperparameters

LightGBM:

```text
num_leaves: 7 or 15
max_depth: 3
min_data_in_leaf: 20 or 40
learning_rate: 0.02 or 0.03
n_estimators: 300 to 800 with early stopping
feature_fraction: 0.6 to 0.8
bagging_fraction: 0.7 to 0.9
lambda_l1: 0.1 or 1.0
lambda_l2: 5, 10, or 20
```

XGBoost:

```text
max_depth: 2 or 3
min_child_weight: 10 or 20
learning_rate: 0.02 or 0.03
n_estimators: 300 to 800 with early stopping
subsample: 0.7 to 0.9
colsample_bytree: 0.5 to 0.8
reg_alpha: 0.1 or 1.0
reg_lambda: 5, 10, or 20
```

### Metrics

Report:

```text
aggregate_mae
aggregate_rmse
aggregate_directional_accuracy
stress_event_recall
stress_event_precision
stress_event_f2
false_negative_count
false_positive_count
top_quintile_recall
top_quintile_precision
baseline_delta_mae
baseline_delta_rmse
permutation_sanity_result
```

### Files Likely Affected

```text
configs/ml/phase_snapshot_candidate_grid.yaml
src/leviathan/training/snapshot_candidate_grid.py
jobs/submit/submit_batch_snapshot_certification_grid.py
jobs/batch/certify_snapshot_model_candidate.py
tests/unit/test_snapshot_candidate_grid.py
```

### S3 Prefixes Affected

```text
s3://leviathan-dev-shahem-001/model_artifacts/snapshot_candidate_certification/
```

### Risks

- Balance-sheet labels may still be hard.
- Substitute features may not improve over solo.
- A small number of stress events may make recall unstable.

### Validation

- Smoke job writes a valid report.
- CV folds exist.
- Selected feature count is non-zero.
- No leakage issues.
- Permutation test behaves sensibly.

### Acceptance Criteria

- At least one candidate completes grouped CV.
- Report includes baseline comparison and stress-event recall.
- If no candidate beats baselines, the report gives an actionable reason.

### Reversibility

Safe. This writes new model artifacts only.

### Explicitly Do Not

- Do not launch a wide grid before one candidate completes cleanly.
- Do not promote any model from smoke alone.

## Phase 9 - Root-Cause Loop Before Wider Sweeps

### Objective

If results are still weak, diagnose the reason before trying more models.

### Possible Failure Modes

1. Feature construction failure:
   - selected features sparse;
   - no dense WASDE estimates;
   - substitute features missing.

2. Target quality failure:
   - too few stress events;
   - unstable anomaly denominator;
   - country-specific structural breaks.

3. Validation failure:
   - too few folds;
   - years too sparse;
   - origin coverage uneven.

4. Model failure:
   - underfit;
   - overfit;
   - unstable feature importance;
   - not beating simple baseline.

5. Business framing failure:
   - target not the right proxy for stress;
   - event threshold wrong;
   - regression target too noisy but classifier might work.

### Tasks

For each failed candidate:

- compare against baselines;
- inspect stress years missed;
- inspect false negatives;
- inspect feature importances;
- run permutation sanity;
- run origin-blocked or stress-year leave-out tests if needed;
- decide whether to:
  - prune features;
  - adjust target;
  - change event threshold;
  - move to classifier;
  - pool by segment;
  - stop.

### Files Likely Affected

```text
jobs/utils/summarize_candidate_certification_reports.py
src/leviathan/training/certification_summary.py
src/leviathan/training/wasde_snapshot_cv.py
tests/unit/test_wasde_snapshot_diagnostics.py
```

### S3 Prefixes Affected

```text
s3://leviathan-dev-shahem-001/model_artifacts/snapshot_candidate_certification/
s3://leviathan-dev-shahem-001/model_artifacts/candidate_rankings/
```

### Acceptance Criteria

- Every failed model has a ranked root cause.
- We do not expand to all commodities without a corn-level explanation.

### Reversibility

Safe. Analysis-only plus new reports.

### Explicitly Do Not

- Do not keep launching jobs hoping one works.

## Phase 10 - Daily Inference Surface And Production Promotion

### Objective

Only after release-date snapshots work, build the daily inference and production
promotion path.

### Tasks

1. Build daily feature rows by forward-filling release/event features.
2. Keep grouped CV for training.
3. Store production inference outputs separately from training matrices.
4. Register models in MLflow only if they pass promotion gates.
5. Emit frontend-ready prediction artifacts:

```text
contract_key
origin
target_key
as_of_date
prediction
prediction_interval
stress_probability
alert_flag
top_features
model_version
dataset_version
source_freshness
```

### Files Likely Affected

```text
src/leviathan/inference/
jobs/batch/train_commodity.py
jobs/batch/certify_snapshot_model_candidate.py
src/leviathan/training/tracking.py
docker/leviathan_trainer/Dockerfile
```

### S3 Prefixes Affected

```text
s3://leviathan-dev-shahem-001/model_artifacts/training_snapshots/
s3://leviathan-dev-shahem-001/silver/model_predictions/
s3://leviathan-dev-shahem-001/gold/model_prediction_surfaces/
```

### Promotion Gates

A candidate can be considered for registration only if:

- grouped CV passes;
- no leakage issues;
- feature gates pass;
- beats prior-year or trailing baseline on the chosen target;
- improves stress-event recall or F2;
- permutation sanity passes;
- feature importance is economically plausible;
- model and dataset artifacts are fully reproducible in MLflow.

### Reversibility

Safe until promotion. Promotion should be reversible through MLflow model stage
management.

### Explicitly Do Not

- Do not promote from one corn smoke.
- Do not expose daily inference as production until freshness and fallback behavior
  are tested.

## Test Suite Summary

Minimum new or updated tests:

```text
tests/unit/test_wasde_snapshot_audit.py
tests/unit/test_wasde_snapshot_features.py
tests/unit/test_wasde_snapshot_targets.py
tests/unit/test_wasde_snapshot_model_ready.py
tests/unit/test_wasde_snapshot_static_join.py
tests/unit/test_wasde_snapshot_diagnostics.py
tests/unit/test_wasde_snapshot_cv.py
tests/unit/test_snapshot_candidate_grid.py
tests/unit/test_features_availability.py
```

Critical assertions:

- release-date snapshots are based on actual WASDE releases;
- `snapshot_stage` is derived, not row-generating;
- no future release enters a feature;
- dense WASDE latest features are emitted;
- stock/use features are computed correctly;
- historical z-scores use only prior years;
- sample weights sum to one per annual group;
- grouped CV never splits an annual group;
- same-year final PSD context is blocked;
- diagnostic-only features are excluded;
- failure reports distinguish construction failure from model failure.

## Commands To Run Later

These are examples for later execution after implementation. They should not be
run until the relevant phase is implemented.

Run source audit:

```powershell
.\.venv\Scripts\python.exe jobs\utils\audit_wasde_snapshot_inputs.py `
  --bucket leviathan-dev-shahem-001 `
  --aws-region us-east-1 `
  --commodity corn `
  --output-prefix model_artifacts/wasde_snapshot_audits/dataset_version={version}/
```

Build new immutable snapshot matrix:

```powershell
.\.venv\Scripts\python.exe jobs\batch\build_model_ready_datasets.py `
  --bucket leviathan-dev-shahem-001 `
  --aws-region us-east-1 `
  --source-dataset-version 20260626T010217Z_6725de02_phase7_full `
  --model-dataset-version {new_version} `
  --dataset-mode psd-snapshot `
  --commodities corn_cbot `
  --target-keys psd_stock_to_use_anomaly_pct,psd_ending_stocks_anomaly_pct `
  --compatible-feature-sets corn_wasde_snapshot_solo,corn_wasde_snapshot_with_static,corn_wasde_snapshot_with_substitutes
```

Run targeted tests:

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests\unit\test_wasde_snapshot_features.py `
  tests\unit\test_wasde_snapshot_targets.py `
  tests\unit\test_wasde_snapshot_model_ready.py `
  tests\unit\test_wasde_snapshot_cv.py
```

Submit one smoke only after matrix quality passes:

```powershell
.\.venv\Scripts\python.exe jobs\submit\submit_batch_snapshot_certification_grid.py `
  --include-hypotheses corn_balance_sheet_snapshot_smoke `
  --max-jobs 1
```

## Final Judgment

The next competent move is not more model jobs. It is rebuilding the model-ready
surface so that WASDE's actual monthly balance-sheet information appears as dense,
point-in-time, release-date features.

The short version:

```text
Use real WASDE release dates.
Use balance-sheet targets.
Use dense latest/stock-use features.
Use grouped CV and sample weights.
Run one smoke only after feature density passes.
```

If that still fails, then we will have a real modeling result. Right now, the
failed smoke mostly proves that the current WASDE snapshot feature construction is
too thin.
