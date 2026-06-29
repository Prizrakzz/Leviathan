# WASDE Snapshot Anomaly Modeling Plan

## Executive Summary

The previous annual PSD/FAOSTAT-shaped modeling path exposed a structural problem:
the feature universe is not useless, but the model-ready matrix grain is too sparse
and too static for the problem we actually care about.

## Phase 0 Guardrail - 2026-06-29 Smoke Result

The first Batch smoke for the active WASDE snapshot matrix must be treated as a
model-ready construction failure, not a model-performance result.

The failed candidate was:

```text
dataset_key = psd_snd_anomaly_snapshot
commodity = corn_cbot
target_key = psd_production_anomaly_pct
feature_set = wasde_monthly_revision
feature_stack = wasde_monthly_revision
model = lightgbm
```

Certification reached the report-writing path, but CV was skipped because feature
selection returned zero usable columns:

```text
training_status = failed_cv
training_error = feature stack wasde_monthly_revision selected zero usable features
selected_feature_count = 0
```

The matrix itself proved the upstream issue:

```text
row_count = 482
trainable_row_count = 442
WASDE dynamic columns = 7
best WASDE non-null count = 23 rows
best WASDE non-null rate = 4.8%
```

This does not prove that WASDE is useless. `silver/wasde/` contains hundreds of
release partitions and tens of thousands of corn rows. It proves that the current
snapshot model-ready surface is too thin and mostly emits sparse `revision_z`
columns instead of dense release-date balance-sheet features.

Phase 0 decision:

- Freeze `psd_production_anomaly_pct` as the first-line WASDE snapshot target.
- Freeze pure `wasde_monthly_revision` as a serious standalone feature stack until
  the release-date feature rebuild passes density gates.
- Use balance-sheet targets for the next smoke:

```text
psd_stock_to_use_anomaly_pct
psd_ending_stocks_anomaly_pct
```

Future candidate reports should classify failures into:

```text
construction_failure
feature_quality_failure
target_quality_failure
cv_failure
model_performance_failure
infrastructure_failure
```

No wider Batch grid should run from the broken surface.

The current annual supervised grain is effectively:

```text
country, crop_year -> one row
```

That was acceptable for early FAOSTAT-style annual baselines, but it is a poor
fit for WASDE/PSD in-season learning. WASDE lives at a monthly release cadence.
The system should learn from point-in-time official estimate states:

```text
contract_key, origin, target_market_year, target_key, as_of_date, snapshot_stage
```

This plan builds a new model-ready snapshot layer that reuses the existing gold
static features and adds dynamic WASDE snapshot features. It does not rebuild the
entire gold feature spine from scratch.

The first research surfaces are deliberately commodity-specific, not generic
"agri up/down":

1. `corn_wasde_snapshot_solo`
   - Corn only.
   - Best for a pure per-commodity anomaly detector.

2. `corn_wasde_snapshot_with_substitutes`
   - Corn target plus wheat, soy/feed, and energy/input-cost context.
   - Best first quant design for corn because it respects substitution,
     feed demand, ethanol/input costs, and balance-sheet linkages.

3. `grains_wasde_snapshot_segment`
   - Corn, wheat, and rice pooled at the snapshot level.
   - Still produces contract-specific outputs.
   - Tests whether shared grain balance-sheet mechanics help without collapsing
     into a generic agriculture signal.

The primary modeling objective shifts from pure annual regression to
point-in-time stress detection and calibrated alert scoring. Regression anomaly
values remain available, but the business-first outputs are:

```text
corn_cbot production downside risk
corn_cbot ending-stocks tightness risk
corn_cbot stock-to-use tightness risk
corn_cbot export surge risk
corn_cbot domestic-use surge risk
```

The biggest validation requirement is grouped time-aware CV:

```text
group = contract_key + origin + target_market_year
```

The model must never train on June 2020 and test on August 2020 for the same
contract/origin/market year.

Every implementation phase must end with:

```powershell
git status --short
git add <phase files only>
git commit -m "<phase-specific message>"
git push origin main
```

If unrelated local work is present, especially GraphRAG work, the phase must stop
before push and document the blocker rather than pushing unrelated commits.

## Current Findings That Drive This Plan

### Observed

- `silver/wasde/` contains monthly release partitions:
  - 461 parquet partitions.
  - Around 580k long-form rows.
  - Grain is roughly:

    ```text
    release_date, commodity, region, marketing_year, attribute
    ```

- `silver/psd/part-000.parquet` contains around 163k rows, but current mapped
  target rows have only one row per:

  ```text
  leviathan_slug, country, market_year
  ```

- Current PSD model-ready corn balance-sheet matrices were tiny:
  - 241 rows per target.
  - 173 trainable rows.
  - 4 target origins.
  - 67 market years.

- Existing gold/static features are mostly not FAOSTAT-only. They include:
  - weather and dense weather aggregates;
  - ONI/IOD;
  - Pink Sheet input costs and energy;
  - FX;
  - PSD prior balance-sheet features;
  - WASDE revision features;
  - ESR/FGIS physical flow;
  - NASS crop progress;
  - crop condition.

### Inferred

- The main weakness is the annual model-ready matrix grain, not simply the model
  algorithm.
- Current annual features can still be reused as static context.
- WASDE dynamic features must be computed at the snapshot/release grain.
- Monthly snapshot rows increase the number of observed states, but not the
  number of independent crop-year outcomes. Evaluation must treat all snapshots
  for the same contract/origin/year as one validation group.

### Explicit Non-Goals

- Do not build a generic agriculture-wide direction model.
- Do not recompute the entire gold feature spine from scratch.
- Do not use futures price returns, technical indicators, raw market direction,
  or COT positioning as core fundamental features.
- Do not touch GraphRAG code or pipelines.
- Do not delete old S3 artifacts during this plan.
- Do not treat monthly snapshots as independent random rows.

## Target Architecture

### Snapshot Model-Ready Row

The new model-ready row should be:

```text
dataset_version
dataset_key
contract_key
commodity
commodity_group
origin
target_market_year
crop_year
target_key
target_family
target_attribute
as_of_date
snapshot_stage
snapshot_month_code
snapshot_policy
target_value
target_event_label
target_event_direction
sample_weight
is_trainable
excluded_reason
<static annual features>
<dynamic WASDE snapshot features>
```

Natural key:

```text
dataset_version,
dataset_key,
contract_key,
origin,
target_market_year,
target_key,
as_of_date,
snapshot_stage
```

### Snapshot Stages

Use consistent stage labels across commodities:

```text
preseason
early_season
midseason
late_season
post_harvest
finalization
```

Stage assignment should be deterministic from `as_of_date`, crop calendar, and
marketing-year convention. For the first pass, a release-month mapping is
acceptable if it is recorded in the manifest.

### Target Families

Regression target values:

```text
psd_production_anomaly_pct
psd_ending_stocks_anomaly_pct
psd_stock_to_use_anomaly_pct
psd_exports_anomaly_pct
psd_imports_anomaly_pct
psd_domestic_use_anomaly_pct
```

Classification labels:

```text
production_downside_event
ending_stocks_tightness_event
stock_to_use_tightness_event
exports_surge_event
imports_surge_event
domestic_use_surge_event
```

Default event directions:

```text
production: lower_is_stress
ending_stocks: lower_is_stress
stock_to_use: lower_is_stress
exports: higher_is_stress
imports: higher_is_stress
domestic_use: higher_is_stress
```

Default thresholds for initial experiments:

```text
5 percent stress threshold
10 percent stress threshold
bottom quintile or top quintile within target_key/origin history
```

The threshold used by each run must be logged in MLflow and in the model-ready
manifest.

## Feature Architecture

### Static Features Reused From Gold

Static features are annual or crop-year features already present in the existing
gold/model-ready surface. They should be joined to snapshot rows by:

```text
origin + crop_year
```

Static families to reuse:

- `preseason_physical`
- `faostat_` prior-history context only
- `oni_`
- `iod_`
- `pink_sheet_`
- `brl_fx_` / `cny_fx_`
- `weather_dense_`
- `nass_crop_progress` and crop condition summaries where available and
  point-in-time safe for the snapshot date
- `esr_`
- `fgis_`
- `nass_ge_`
- `mpob_`, `unica_`, `conab_`, or other source-specific features only when
  relevant to the commodity family being tested

Static feature rules:

- Same-year final FAOSTAT or final production labels are never allowed.
- A feature with unknown release timing must be conservatively lagged.
- Annual features computed over the full crop year are not allowed in a
  preseason snapshot unless their availability is explicitly prior to the
  snapshot.
- Existing feature quality gates remain active:
  - no all-missing selected features;
  - no target/label-like feature names;
  - no excluded market signals;
  - diagnostic-only features excluded from core training;
  - sparse dense-weather features pruned or marked diagnostic.

### Dynamic WASDE Snapshot Features

Dynamic features are computed directly from `silver/wasde` for each:

```text
contract_key, origin, target_market_year, as_of_date
```

Initial feature families:

#### Estimate Level Features

```text
wasde_<attribute>_latest_estimate
wasde_<attribute>_latest_estimate_z
wasde_<attribute>_latest_vs_trend_z
wasde_<attribute>_latest_vs_first_forecast_pct
```

Attributes:

```text
production
ending_stocks
exports
imports
domestic_total
total_use
feed
feed_residual
```

Only attributes present and meaningful for the commodity should be emitted.

#### Revision Features

```text
wasde_<attribute>_mom_revision
wasde_<attribute>_mom_revision_z
wasde_<attribute>_revision_since_first_forecast
wasde_<attribute>_revision_since_first_forecast_z
wasde_<attribute>_consecutive_revision_count
wasde_<attribute>_revision_direction
```

#### Snapshot Calendar Features

```text
wasde_month_code
wasde_release_count_for_market_year
wasde_months_to_marketing_year_end
wasde_is_first_estimate
wasde_is_final_or_latest
snapshot_stage_code
```

#### Cross-Attribute Balance Features

```text
wasde_stock_to_use_estimate
wasde_stock_to_use_mom_revision
wasde_exports_to_use_estimate
wasde_import_dependency_estimate
wasde_production_minus_use_revision
```

These are especially relevant for balance-sheet stress targets.

### Substitute And Segment Context

For `corn_wasde_snapshot_with_substitutes`, add context from linked markets:

- Wheat:
  - production revision;
  - ending-stocks revision;
  - stock-to-use revision;
  - exports revision.

- Soybeans / soymeal:
  - feed/protein meal context where available;
  - soybean production and exports revision;
  - soybean meal domestic use / exports revision.

- Energy/input costs:
  - Pink Sheet energy z-score;
  - fertilizer z-scores;
  - ethanol/input-cost proxies if already present and certified.

Feature names should be namespaced:

```text
sub_wheat_wasde_ending_stocks_revision_z
sub_soybeans_wasde_exports_revision_z
sub_soybean_meal_wasde_domestic_use_revision_z
driver_pink_sheet_energy_z
```

Substitute features must be visible at the same `as_of_date`.

## Dataset Keys

Add model-ready dataset keys:

```text
corn_wasde_snapshot_solo
corn_wasde_snapshot_with_substitutes
grains_wasde_snapshot_segment
```

Later reusable keys:

```text
oilseeds_wasde_snapshot_segment
softs_wasde_snapshot_segment
commodity_wasde_snapshot_solo
commodity_wasde_snapshot_with_substitutes
```

The first implementation should focus only on the three corn/grain datasets.

## Cross-Validation Architecture

### Required CV

Use grouped walk-forward CV:

```text
group_key = contract_key + origin + target_market_year
time_key = target_market_year
```

Rules:

- Train on market years strictly before test year.
- Test on all snapshots for all groups in the held-out market year.
- No random row split.
- No train/test split across snapshots of the same origin/year.
- Snapshot rows may be downweighted so each origin/year contributes total
  weight around 1.0 across all its snapshots.

### Optional CV Stress Tests

- Leave-one-origin-out.
- Leave-one-contract-out for segment models.
- Leave-one-stress-year-out.
- Rich-vs-sparse origin split.
- Pre-2000 vs post-2000 stability.
- Snapshot-stage blocked evaluation:
  - preseason only;
  - early season only;
  - midseason only;
  - late season only.

## Metrics

### Classification Metrics

Primary:

```text
recall
false_negatives
f2_score
precision
balanced_accuracy
pr_auc
brier_score
calibration_error
```

Why recall/F2 is primary:

- Missing a real stress year is worse than flagging a false positive.
- The product can show alerts that analysts verify.
- False positives are manageable if precision is not absurdly low and the
  explanation layer is good.

### Regression Metrics

Secondary:

```text
mae
rmse
sign_accuracy
rank_correlation
top_quintile_directional_accuracy
tail_recall
```

Regression remains useful for ranking severity, but it should not be the only
promotion gate.

### Baselines

Every run must beat or explain failure against:

- zero-stress probability baseline;
- historical event-rate baseline;
- prior-year persistence baseline;
- trailing event-rate by origin;
- trailing event-rate by target_key;
- latest WASDE revision sign baseline;
- simple threshold baseline on latest WASDE revision z-score.

## Root-Cause Analysis Protocol

Any failed phase must produce a root-cause note before proceeding.

Root-cause categories:

```text
source_mapping_issue
region_normalization_issue
snapshot_generation_issue
target_label_issue
feature_availability_issue
feature_quality_issue
leakage_risk
cv_design_issue
sample_size_issue
class_imbalance_issue
model_capacity_issue
baseline_too_strong
metric_misalignment
infrastructure_issue
```

Minimum RCA fields:

```text
phase
failure_summary
observed_symptom
root_cause_category
evidence
affected_files
affected_s3_prefixes
candidate_fix
validation_to_confirm_fix
decision
```

RCA output path:

```text
data/phase_wasde_snapshot/root_cause_reports/<timestamp>_<phase>.json
```

Do not continue to wider experiments until RCA is resolved or explicitly waived
in the phase manifest.

## Phase 0 - Audit And Inventory

### Objective

Prove exactly what usable WASDE, PSD target, and static feature data exists
before implementing new training surfaces.

### Detailed Tasks

1. Audit `silver/wasde`.
   - Count rows by `commodity`.
   - Count release dates by commodity.
   - Count marketing years by commodity.
   - Count regions by commodity.
   - Count core attributes by commodity:
     - production;
     - ending_stocks;
     - exports;
     - imports;
     - domestic_total;
     - total_use;
     - feed;
     - feed_residual.

2. Audit WASDE region quality.
   - Identify clean canonical region names.
   - Identify numeric/garbled parsed region strings.
   - Identify missing or ambiguous origins.
   - Produce a region mapping candidate table.

3. Audit current PSD target panels.
   - Count annual target rows by contract/origin/target.
   - Confirm target direction and threshold policy.
   - Confirm target values are based on final/latest annual PSD rows only.

4. Audit static gold/model-ready features.
   - Identify which existing feature sets can be joined by `country + crop_year`.
   - Identify feature sets unsafe for snapshot dates.
   - Identify feature sets that need snapshot-aware filtering.

5. Produce inventory report:

```text
data/phase_wasde_snapshot/phase0_inventory_report.json
data/phase_wasde_snapshot/wasde_region_quality.parquet
data/phase_wasde_snapshot/static_feature_reuse_audit.parquet
```

### Files Likely Affected

```text
jobs/utils/audit_wasde_snapshot_inputs.py
src/leviathan/model_datasets/wasde_snapshot_audit.py
tests/unit/test_wasde_snapshot_audit.py
```

### S3 Prefixes Affected

Read-only:

```text
s3://leviathan-dev-shahem-001/silver/wasde/
s3://leviathan-dev-shahem-001/silver/psd/
s3://leviathan-dev-shahem-001/gold/model_ready_matrices/
s3://leviathan-dev-shahem-001/gold/feature_matrix_versions/
```

No writes except optional local audit artifacts unless explicitly requested.

### Validation And Tests

Unit tests:

```text
tests/unit/test_wasde_snapshot_audit.py
  test_counts_core_attributes_by_commodity
  test_flags_garbled_regions
  test_region_quality_report_has_required_columns
  test_static_feature_reuse_audit_blocks_unsafe_sets
```

Data checks:

- `silver/wasde` release count is greater than 400.
- Corn has non-empty production, ending_stocks, exports, imports, and
  domestic_total rows.
- Region quality report separates clean and suspect regions.

### Acceptance Criteria

- We know whether corn, wheat, rice, soybeans, soybean meal, and soybean oil
  are usable for snapshot modeling.
- We know which regions can map to origins.
- We know which static feature sets can be reused.
- No code writes to S3.
- Phase commit pushed to `origin/main`.

### Risks

- WASDE parser may have garbled region rows that make some attributes unusable.
- Commodity/region names may not map cleanly to contract origins.

### Reversibility

Safe and reversible. Audit-only plus local report generation.

### Explicitly Do Not Do

- Do not build model-ready matrices.
- Do not submit training jobs.
- Do not delete old model-ready datasets.
- Do not modify GraphRAG.

## Phase 1 - WASDE Region And Contract Mapping

### Objective

Create a governed mapping from WASDE commodity/region rows to Leviathan
contract/origin contexts.

### Detailed Tasks

1. Add mapping config:

```text
configs/ml/wasde_snapshot_mappings.yaml
```

2. Include initial contract surfaces:

```text
corn_wasde_snapshot_solo
corn_wasde_snapshot_with_substitutes
grains_wasde_snapshot_segment
```

3. Define mappings:

Corn solo:

```text
contract_key: corn_cbot
wasde_commodity: corn
origins:
  united_states -> region aliases: us, united_states
  brazil
  argentina
  ukraine
```

Corn with substitutes:

```text
primary: corn
substitutes:
  wheat
  soybeans
  soybean_meal
drivers:
  pink_sheet_energy
  fertilizer
  fx
```

Grains segment:

```text
contracts:
  corn_cbot
  soft_red_winter_wheat_cbot
  hard_red_winter_wheat_kcbt
  hard_red_spring_wheat_mgex
  rough_rice_cbot
```

4. Store mapping confidence:

```text
high
medium
low
excluded
```

5. Add explicit exclusions for garbled WASDE regions and aggregate rows that
   should not be treated as origins.

6. Add mapping SHA to downstream manifests.

### Files Likely Affected

```text
configs/ml/wasde_snapshot_mappings.yaml
src/leviathan/model_datasets/wasde_snapshot_mapping.py
tests/unit/test_wasde_snapshot_mapping.py
```

### S3 Prefixes Affected

None.

### Validation And Tests

Unit tests:

```text
tests/unit/test_wasde_snapshot_mapping.py
  test_loads_mapping_config
  test_corn_solo_maps_expected_origins
  test_substitute_context_maps_wheat_soy_feed_energy
  test_grains_segment_keeps_contract_specific_outputs
  test_mapping_rejects_unknown_region_without_waiver
  test_mapping_sha_changes_when_config_changes
```

Data validation:

- Every mapped origin has non-empty WASDE rows.
- Every mapped commodity has all required target attributes or documented
  missingness.
- All excluded mappings include a reason.

### Acceptance Criteria

- The mapping config is reviewed and deterministic.
- All initial corn/grain mappings have non-empty WASDE rows.
- Mapping SHA is available for MLflow tags and manifests.
- Phase commit pushed to `origin/main`.

### Risks

- WASDE region names may be inconsistent across old releases.
- Some international regions may be aggregates, not countries.

### Reversibility

Safe and reversible. Config-driven.

### Explicitly Do Not Do

- Do not infer low-confidence region mappings silently.
- Do not map every WASDE row just because it exists.
- Do not collapse contract-specific outputs into one segment-level label.

## Phase 2 - Snapshot Target And Label Builder

### Objective

Build target labels once per annual target group, then expand them to valid
WASDE release snapshots without target leakage.

### Detailed Tasks

1. Reuse current PSD target builder where possible.
2. Add snapshot expansion:

```text
contract_key, origin, target_market_year, target_key
  x valid WASDE release dates
```

3. Add classification labels:

```text
target_event_label
target_event_threshold
target_event_direction
target_event_definition
```

4. Add regression target columns:

```text
target_value
actual_value
trend_prediction
target_anomaly_pct
```

5. Add trainability flags:

```text
is_trainable
excluded_reason
history_years
target_available
```

6. Add sample weights:

```text
sample_weight = 1.0 / number_of_snapshots_for_group
```

7. Add group keys:

```text
cv_group = contract_key + origin + target_market_year
cv_time = target_market_year
```

### Files Likely Affected

```text
src/leviathan/model_datasets/wasde_snapshot_targets.py
src/leviathan/model_datasets/psd_target_builder.py
tests/unit/test_wasde_snapshot_targets.py
```

### S3 Prefixes Affected

Future writes:

```text
gold/model_ready_targets/dataset_version=<version>/dataset_key=corn_wasde_snapshot_solo/
gold/model_ready_targets/dataset_version=<version>/dataset_key=corn_wasde_snapshot_with_substitutes/
gold/model_ready_targets/dataset_version=<version>/dataset_key=grains_wasde_snapshot_segment/
```

### Validation And Tests

Unit tests:

```text
tests/unit/test_wasde_snapshot_targets.py
  test_expands_annual_target_to_release_snapshots
  test_snapshot_target_keeps_same_final_label_per_group
  test_sample_weight_sums_to_one_per_group
  test_downside_event_direction_for_production_and_stocks
  test_upside_event_direction_for_exports_imports_domestic_use
  test_missing_history_marks_not_trainable
  test_no_duplicate_snapshot_target_keys
```

Leakage tests:

- No target label uses releases after final target construction incorrectly.
- Snapshot feature dates must be `<= as_of_date`.
- Training labels can be final outcomes, but features cannot use future
  observations.

### Acceptance Criteria

- Snapshot target panel exists locally for corn solo.
- Every row has group key, target key, as-of date, and event label.
- No duplicate natural keys.
- Sample weights sum to approximately 1.0 per group.
- Phase commit pushed to `origin/main`.

### Risks

- Multiple snapshots per year can create a false sense of sample size.
- Bad threshold definitions can create extreme class imbalance.

### Reversibility

Safe and reversible if written to a new immutable dataset version.

### Explicitly Do Not Do

- Do not train models yet.
- Do not treat snapshots as independent groups.
- Do not overwrite existing annual PSD datasets.

## Phase 3 - Dynamic WASDE Feature Builder

### Objective

Convert long-form WASDE release rows into compact point-in-time features per
contract/origin/market-year/as-of date.

### Detailed Tasks

1. Build normalized source frame:

```text
release_date
commodity
origin
marketing_year_start
attribute
estimate
revision
is_first_estimate
is_final_or_latest
```

2. Compute latest visible values as of each snapshot date.

3. Compute revision features:

```text
mom_revision
revision_since_first_forecast
consecutive_revision_count
revision_z
```

4. Compute estimate context:

```text
latest_estimate
latest_estimate_z
latest_vs_trend_z
latest_vs_first_forecast_pct
```

5. Compute snapshot calendar:

```text
month_code
release_count_for_market_year
months_to_marketing_year_end
is_first_estimate
is_final_or_latest
```

6. Compute cross-attribute balance context.

7. Ensure all features are calculated using only releases:

```text
release_date <= as_of_date
```

8. Emit feature quality metadata:

```text
feature
non_null_rate
constant_rate
min_as_of_date
max_as_of_date
attribute
source_release_count
```

### Files Likely Affected

```text
src/leviathan/model_datasets/wasde_snapshot_features.py
src/leviathan/model_datasets/wasde_snapshot.py
tests/unit/test_wasde_snapshot_features.py
```

### S3 Prefixes Affected

Future writes:

```text
gold/model_ready_feature_sets/dataset_version=<version>/feature_sets.parquet
gold/model_ready_manifests/dataset_version=<version>/manifest.json
```

### Validation And Tests

Unit tests:

```text
tests/unit/test_wasde_snapshot_features.py
  test_latest_visible_estimate_uses_as_of_cutoff
  test_mom_revision_uses_previous_release_only
  test_revision_since_first_forecast
  test_consecutive_revision_count_positive_and_negative
  test_revision_z_uses_prior_years_only
  test_months_to_marketing_year_end
  test_cross_attribute_stock_to_use_estimate
  test_no_feature_uses_future_release
  test_missing_attribute_emits_nan_not_zero
  test_duplicate_long_rows_raise_or_deduplicate_by_policy
```

Data quality tests:

- Feature non-null rate by snapshot stage.
- Constant feature rate.
- Attribute availability by origin.
- Future-release audit.

### Acceptance Criteria

- Corn dynamic WASDE features are non-empty.
- Every feature row has `as_of_date`.
- Future-release leakage audit passes.
- Feature quality report has no all-missing required features.
- Phase commit pushed to `origin/main`.

### Risks

- WASDE region parsing may produce noisy origins.
- Revisions may be missing for first releases.
- Some attributes have structural zeros for some origins.

### Reversibility

Safe and reversible. New code and new immutable artifacts only.

### Explicitly Do Not Do

- Do not impute missing revision values as zero unless zero is explicitly
  source-provided.
- Do not use final/latest flags as target leakage if they imply future status
  relative to the snapshot.

## Phase 4 - Static Feature Join Layer

### Objective

Reuse existing annual/static gold features in snapshot matrices without
recomputing the whole gold feature spine.

### Detailed Tasks

1. Load static model-ready feature matrix for the chosen source dataset version.
2. Select allowed static feature sets:

```text
preseason_physical
corn_preseason_core
inseason_weather_dense
physical_flow
crop_condition
planting_incentives
trade_competitiveness
```

3. Join static features to snapshots by:

```text
origin/country + crop_year
```

4. Enforce feature availability:
   - preseason features allowed at all snapshots if already lag-safe;
   - in-season features allowed only if dated or summarized as available by
     `as_of_date`;
   - annual/full-season summaries excluded from early snapshots unless proven
     point-in-time safe.

5. Produce static feature reuse manifest:

```text
feature
feature_set
policy
source
availability_policy
allowed_snapshot_stages
non_null_rate
decision
reason
```

### Files Likely Affected

```text
src/leviathan/model_datasets/wasde_snapshot_static_join.py
src/leviathan/training/feature_quality.py
tests/unit/test_wasde_snapshot_static_join.py
```

### S3 Prefixes Affected

Read:

```text
gold/model_ready_matrices/dataset_version=<static_version>/
gold/feature_set_versions/dataset_version=<source_gold_version>/
```

Write:

```text
gold/model_ready_manifests/dataset_version=<snapshot_version>/manifest.json
```

### Validation And Tests

Unit tests:

```text
tests/unit/test_wasde_snapshot_static_join.py
  test_static_features_join_many_snapshots_to_one_annual_row
  test_missing_static_features_marks_not_trainable_or_warns
  test_snapshot_stage_policy_blocks_full_season_features
  test_label_like_static_features_blocked
  test_excluded_market_signal_blocked
  test_diagnostic_only_blocked_unless_allowed
  test_join_does_not_duplicate_snapshot_rows
```

Leakage tests:

- No selected static feature has source availability after `as_of_date`.
- Full crop-year features are not present in preseason snapshots unless waived.

### Acceptance Criteria

- Static features can be joined to corn snapshots without duplicate rows.
- Feature quality gates pass for `corn_wasde_snapshot_solo`.
- Any waived feature has a manifest reason.
- Phase commit pushed to `origin/main`.

### Risks

- Some existing in-season features may have been built as full-season aggregates.
- Joining annual features to many snapshots can overstate their importance.

### Reversibility

Safe and reversible. New snapshot layer only.

### Explicitly Do Not Do

- Do not mutate old static matrices.
- Do not silently include unsafe full-season features.

## Phase 5 - Build The Three Corn Snapshot Surfaces

### Objective

Create immutable model-ready datasets for:

```text
corn_wasde_snapshot_solo
corn_wasde_snapshot_with_substitutes
grains_wasde_snapshot_segment
```

### Detailed Tasks

1. Add build config for each dataset surface.

2. `corn_wasde_snapshot_solo`:
   - primary commodity: corn;
   - origins: US, Brazil, Argentina, Ukraine where mapping is clean;
   - dynamic WASDE corn features;
   - corn static features.

3. `corn_wasde_snapshot_with_substitutes`:
   - all solo features;
   - wheat substitute revision context;
   - soybean/soymeal feed context;
   - energy/input-cost drivers;
   - optional FX context.

4. `grains_wasde_snapshot_segment`:
   - corn, wheat, rice contracts;
   - contract-specific rows;
   - categorical identifiers:

```text
contract_key
commodity
commodity_group
origin
target_key
snapshot_stage
```

5. Add categorical encoding strategy:
   - LightGBM can consume categorical columns if configured;
   - otherwise use stable one-hot encoding in model-ready build;
   - encoding manifest must record categories.

6. Write immutable S3 paths:

```text
gold/model_ready_matrices/dataset_version=<version>/dataset_key=<snapshot_key>/commodity=<contract_key>/target=<target_key>/part-000.parquet
gold/model_ready_targets/dataset_version=<version>/dataset_key=<snapshot_key>/commodity=<contract_key>/part-000.parquet
gold/model_ready_manifests/dataset_version=<version>/manifest.json
```

7. Include feature set artifact:

```text
gold/model_ready_feature_sets/dataset_version=<version>/feature_sets.parquet
```

### Files Likely Affected

```text
src/leviathan/model_datasets/wasde_snapshot_model_ready.py
src/leviathan/model_datasets/model_ready_registry.py
jobs/batch/model_ready_datasets_task.py
jobs/submit/submit_batch_model_ready_datasets.py
tests/unit/test_wasde_snapshot_model_ready.py
```

### S3 Prefixes Affected

Write new immutable version only:

```text
gold/model_ready_matrices/dataset_version=<new_snapshot_version>/
gold/model_ready_targets/dataset_version=<new_snapshot_version>/
gold/model_ready_manifests/dataset_version=<new_snapshot_version>/
gold/model_ready_feature_sets/dataset_version=<new_snapshot_version>/
```

### Validation And Tests

Unit tests:

```text
tests/unit/test_wasde_snapshot_model_ready.py
  test_builds_corn_snapshot_solo
  test_builds_corn_snapshot_with_substitutes
  test_builds_grains_segment_with_contract_specific_outputs
  test_snapshot_natural_key_unique
  test_sample_weights_sum_to_one_per_group
  test_target_labels_non_empty
  test_target_class_balance_reported
  test_feature_set_membership_written
  test_manifest_contains_mapping_sha_and_thresholds
```

Integration checks:

- At least 1,000 corn snapshot rows if enough clean WASDE origins/releases are
  available.
- At least 100 positive stress events or a documented class-imbalance warning.
- Feature matrix has no all-missing selected features.
- No target leakage columns selected.

### Acceptance Criteria

- All three model-ready surfaces are written as immutable versions.
- Feature quality reports pass or warnings are explicitly documented.
- Manifests include source versions, mapping SHA, feature-set SHA, target config
  SHA, and snapshot policy.
- Phase commit pushed to `origin/main`.

### Risks

- Snapshot row count may be lower than expected if region mapping is too strict.
- Class imbalance may be severe for 10 percent event thresholds.
- Segment pooling may include low-confidence wheat/rice mappings.

### Reversibility

Safe and reversible if only new dataset versions are written.

### Explicitly Do Not Do

- Do not overwrite annual model-ready datasets.
- Do not promote models.
- Do not broaden to all commodities yet.

## Phase 6 - Grouped Walk-Forward CV And Training Support

### Objective

Make training correctly handle snapshot rows and classification targets.

### Detailed Tasks

1. Add grouped walk-forward splitter:

```text
grouped_walk_forward_cv(
  df,
  time_col="target_market_year",
  group_col="cv_group",
  min_train_years=10
)
```

2. Add classification model support:
   - LightGBM classifier;
   - XGBoost classifier;
   - logistic/ridge classifier baseline.

3. Add sample-weight support.

4. Add categorical feature support:
   - stable one-hot encoding or LightGBM categorical columns;
   - encoding fitted only on training folds;
   - validation categories handled deterministically.

5. Add fold-level artifacts:

```text
fold_metrics.parquet
oof_predictions.parquet
group_assignments.parquet
threshold_metrics.parquet
calibration.parquet
```

6. Add anti-leakage checks:
   - no group appears in both train and test;
   - all train years are strictly before test years;
   - preprocessing fits only on train folds;
   - feature availability <= as_of_date;
   - categorical encoders fit only on train folds.

### Files Likely Affected

```text
src/leviathan/training/cv.py
src/leviathan/training/models.py
src/leviathan/training/certification.py
src/leviathan/training/mlflow_artifacts.py
jobs/batch/train_commodity.py
tests/unit/test_grouped_walk_forward_cv.py
tests/unit/test_snapshot_classification_training.py
```

### S3 Prefixes Affected

Training outputs:

```text
model_artifacts/training_snapshots/<mlflow_run_id>/
model_artifacts/candidate_certification/candidate_id=<candidate_id>/
```

### Validation And Tests

Unit tests:

```text
tests/unit/test_grouped_walk_forward_cv.py
  test_group_never_split_across_train_test
  test_train_years_strictly_before_test_year
  test_snapshot_rows_for_same_year_stay_together
  test_min_train_years_enforced
  test_sample_weights_passed_to_model

tests/unit/test_snapshot_classification_training.py
  test_classifier_training_outputs_probabilities
  test_threshold_metrics_include_recall_precision_f2
  test_encoder_fit_on_train_only
  test_unseen_categories_handled
  test_oof_predictions_include_snapshot_identity
```

### Acceptance Criteria

- Snapshot classifier can train locally on a synthetic matrix.
- Group leakage tests pass.
- Fold artifacts are logged.
- Phase commit pushed to `origin/main`.

### Risks

- Existing trainer may assume regression.
- MLflow schema may need extension for classification metrics.

### Reversibility

Safe if additive and backward-compatible.

### Explicitly Do Not Do

- Do not remove existing regression trainer.
- Do not change annual CV behavior unexpectedly.

## Phase 7 - Feature Diagnostics And Leakage Certification

### Objective

Make the snapshot surfaces safe before launching expensive sweeps.

### Detailed Tasks

1. Run feature diagnostics for each dataset key:

```text
corn_wasde_snapshot_solo
corn_wasde_snapshot_with_substitutes
grains_wasde_snapshot_segment
```

2. Produce diagnostics:
   - row count;
   - trainable row count;
   - unique group count;
   - positive event count;
   - event rate by target;
   - event rate by origin;
   - event rate by snapshot stage;
   - missingness by feature;
   - missingness by stage;
   - constant features;
   - high-correlation feature clusters;
   - target leakage candidates;
   - feature availability violations;
   - sample-weight sanity.

3. Run leakage probes:
   - future-release truncation test;
   - shuffled target permutation;
   - impossible feature audit;
   - train/test group overlap audit.

4. Emit RCA for any failure.

### Files Likely Affected

```text
src/leviathan/training/feature_diagnostics.py
jobs/utils/build_snapshot_feature_diagnostics.py
tests/unit/test_snapshot_feature_diagnostics.py
```

### S3 Prefixes Affected

Optional writes:

```text
model_artifacts/feature_diagnostics/dataset_version=<version>/
```

Local outputs:

```text
data/phase_wasde_snapshot/diagnostics/
```

### Validation And Tests

Unit tests:

```text
tests/unit/test_snapshot_feature_diagnostics.py
  test_reports_group_count_not_only_row_count
  test_reports_event_rate_by_stage
  test_flags_all_missing_features
  test_flags_constant_features
  test_flags_future_availability_violations
  test_flags_group_overlap
  test_writes_root_cause_report_for_failure
```

Acceptance thresholds for first smoke:

- zero group leakage;
- zero future-release violations;
- zero label-like selected features;
- positive event count documented;
- no all-missing required dynamic WASDE features;
- sparse features either pruned or diagnostic-only.

### Acceptance Criteria

- Diagnostics pass for `corn_wasde_snapshot_solo`.
- Any warnings for substitute or segment surfaces are documented.
- RCA exists for every failed validation.
- Phase commit pushed to `origin/main`.

### Risks

- Event labels may be too rare at 10 percent threshold.
- Some stages may have weak or sparse WASDE features.

### Reversibility

Safe and reversible.

### Explicitly Do Not Do

- Do not run full model sweeps before diagnostics pass.

## Phase 8 - Smoke Experiments

### Objective

Run small, cheap experiments to verify the new snapshot modeling machinery and
find whether the direction is promising.

### Detailed Tasks

1. Run one target at a time:

```text
production_downside_event
ending_stocks_tightness_event
stock_to_use_tightness_event
exports_surge_event
domestic_use_surge_event
```

2. Run each dataset key:

```text
corn_wasde_snapshot_solo
corn_wasde_snapshot_with_substitutes
grains_wasde_snapshot_segment
```

3. Use simple models:
   - logistic/ridge classifier baseline;
   - LightGBM shallow classifier;
   - XGBoost shallow classifier.

4. Use conservative hyperparameters:

LightGBM:

```yaml
num_leaves: 7
max_depth: 3
learning_rate: 0.03
n_estimators: 200
min_data_in_leaf: 20
lambda_l1: 0.1
lambda_l2: 5.0
subsample: 0.8
colsample_bytree: 0.7
```

XGBoost:

```yaml
max_depth: 2
learning_rate: 0.03
n_estimators: 200
min_child_weight: 10
reg_alpha: 0.1
reg_lambda: 5.0
subsample: 0.8
colsample_bytree: 0.7
```

5. Log MLflow artifacts:

```text
manifest.json
feature_list.json
fold_metrics.parquet
oof_predictions.parquet
threshold_metrics.parquet
calibration.parquet
leakage_audit.json
feature_importance.parquet
shap_summary.parquet or shap_sample.parquet
```

### Files Likely Affected

```text
configs/ml/phase_snapshot_candidate_grid.yaml
jobs/submit/submit_batch_snapshot_certification_grid.py
jobs/batch/certify_snapshot_model_candidate.py
tests/unit/test_snapshot_candidate_grid.py
```

### S3 Prefixes Affected

```text
model_artifacts/candidate_certification/
model_artifacts/training_snapshots/
```

### Validation And Tests

Smoke criteria:

- Batch job starts and succeeds.
- MLflow run logs metrics and artifacts.
- OOF predictions include snapshot identity.
- Leakage audit passes.
- Recall and F2 are computed.
- Calibration artifacts exist.

### Acceptance Criteria

- At least one successful smoke per dataset key.
- No candidate promoted.
- Phase commit pushed to `origin/main`.

### Risks

- Class imbalance may make metrics unstable.
- Segment model may need categorical support tuning.

### Reversibility

Safe and reversible.

### Explicitly Do Not Do

- Do not launch broad sweeps.
- Do not register production models.

## Phase 9 - Full Snapshot Certification Grid

### Objective

Run the first serious controlled comparison across the three surfaces.

### Detailed Tasks

1. Candidate grid:

```text
dataset_key:
  - corn_wasde_snapshot_solo
  - corn_wasde_snapshot_with_substitutes
  - grains_wasde_snapshot_segment
target_event:
  - production_downside_event
  - ending_stocks_tightness_event
  - stock_to_use_tightness_event
  - exports_surge_event
  - domestic_use_surge_event
models:
  - logistic_ridge
  - lightgbm_classifier
  - xgboost_classifier
cv:
  - grouped_expanding_walk_forward
threshold:
  - 5pct
  - 10pct
  - historical_quintile
```

2. Use staged submission:
   - dry-run;
   - 3-job smoke;
   - 15-job medium grid;
   - full grid only after smoke passes.

3. Generate ranking report:

```text
data/phase_wasde_snapshot/snapshot_candidate_ranking.parquet
data/phase_wasde_snapshot/snapshot_candidate_ranking.md
```

4. Compare:
   - solo vs substitute context;
   - solo vs segment pooling;
   - classifier vs simple baseline;
   - early vs mid vs late snapshot stages.

### Files Likely Affected

```text
src/leviathan/training/snapshot_certification_summary.py
jobs/utils/summarize_snapshot_candidate_reports.py
tests/unit/test_snapshot_certification_summary.py
```

### S3 Prefixes Affected

```text
model_artifacts/candidate_certification/
model_artifacts/candidate_certification_summaries/
```

### Validation And Tests

Certification gates:

- grouped CV pass;
- permutation sanity pass;
- no leakage;
- recall improves over baseline;
- F2 improves over baseline;
- false negatives materially reduced;
- precision not degenerate;
- calibration not pathological;
- feature importances economically plausible.

### Acceptance Criteria

- Full grid results are summarized.
- Best candidate per target is identified.
- Failed candidates have clear failure reasons.
- No model promoted automatically.
- Phase commit pushed to `origin/main`.

### Risks

- Larger grid could increase Batch cost.
- Some candidates may be invalid due to sparse targets.

### Reversibility

Safe. Training artifacts are additive.

### Explicitly Do Not Do

- Do not declare success from recall alone if precision is unusable.
- Do not compare row-level random CV metrics.

## Phase 10 - Root-Cause Review And Model Decision

### Objective

Decide whether the snapshot architecture solved the row-count/modeling problem
or whether the remaining issue is feature/target quality.

### Detailed Tasks

1. Review each target:
   - production downside;
   - ending-stocks tightness;
   - stock-to-use tightness;
   - export surge;
   - domestic-use surge.

2. Review each surface:
   - solo;
   - substitutes;
   - segment.

3. For failures, classify:

```text
insufficient signal
bad target threshold
bad region mapping
bad feature availability
too much class imbalance
too few independent groups
model too weak
model too complex
baseline too strong
```

4. Decide next action:
   - promote to wider validation;
   - revise target threshold;
   - revise feature set;
   - add commodity-specific context;
   - abandon target for now.

5. Produce decision memo:

```text
docs/WASDE_SNAPSHOT_PHASE10_DECISION.md
```

### Files Likely Affected

```text
docs/WASDE_SNAPSHOT_PHASE10_DECISION.md
```

### S3 Prefixes Affected

Read-only:

```text
model_artifacts/candidate_certification/
model_artifacts/training_snapshots/
```

### Validation And Tests

Decision memo must include:

- top candidates;
- failed gates;
- event counts;
- false negatives;
- baseline comparisons;
- feature importance sanity;
- recommended next phase.

### Acceptance Criteria

- We know whether to proceed with snapshot models.
- We know which target/surface/model combinations are promising.
- Phase commit pushed to `origin/main`.

### Risks

- Results may still be weak. That is acceptable if root cause is clear.

### Reversibility

Safe. Documentation and decision only.

### Explicitly Do Not Do

- Do not promote models yet.
- Do not expand to all commodities without a documented winning design.

## Phase 11 - Wider Commodity Adaptation

### Objective

Only after corn/grain snapshot evidence is promising, generalize the design to
other commodity groups.

### Candidate Groups

Oilseeds and veg oils:

```text
soybeans_cbot
soybean_oil_cbot
soybean_meal_cbot
malaysian_crude_palm_oil_cme
canola_ice
french_rapeseed_matif
```

Softs:

```text
cotton
raw_sugar
white_sugar
arabica_coffee
robusta_coffee
```

Rice:

```text
rough_rice_cbot
```

### Detailed Tasks

- Create group-specific substitute mappings.
- Reuse the same snapshot machinery.
- Do not force every group into the same feature set.
- Build group-specific target thresholds if distributions differ.

### Acceptance Criteria

- At least one non-corn group has a clean snapshot matrix.
- Group-specific mappings are reviewed.
- Phase commit pushed to `origin/main`.

### Risks

- Coffee/sugar may be poorly represented in WASDE relative to local sources.
- Palm oil may need MPOB monthly features more than WASDE.

### Reversibility

Safe and reversible if additive.

### Explicitly Do Not Do

- Do not blindly pool all commodities.
- Do not treat proxy mappings as high confidence.

## Phase 12 - Promotion Readiness

### Objective

Promote only candidates that are robust, explainable, and useful for the
frontend/agentic system.

### Promotion Gates

Hard gates:

- grouped CV pass;
- leakage audit pass;
- recall better than baseline;
- F2 better than baseline;
- false negatives materially lower than baseline;
- permutation sanity pass;
- no impossible feature importance;
- minimum independent group count;
- stable enough across origins/stages.

Soft gates:

- precision acceptable for analyst workflow;
- calibration acceptable;
- SHAP explanation makes economic sense;
- model output can be converted into chart-ready time series.

### Model Registry

If a model passes:

- log model with `mlflow.lightgbm.log_model` or `mlflow.xgboost.log_model`;
- register model;
- tag model with:

```text
dataset_key
dataset_version
target_key
target_event
snapshot_policy
mapping_sha
feature_set_sha
cv_scheme
promotion_gate_status
```

No model should move to production without a manual review note.

### Acceptance Criteria

- Production candidate has full MLflow provenance.
- Frontend output contract is known.
- Promotion decision is documented.
- Phase commit pushed to `origin/main`.

### Risks

- A model can look good on recall and still be poorly calibrated.
- Segment pooling may obscure commodity-specific behavior.

### Reversibility

Promotion is reversible if registry aliases are used carefully and old models
remain available.

### Explicitly Do Not Do

- Do not auto-promote from a grid score.
- Do not hide weak calibration behind high recall.

## Commands To Use Later

These are examples for execution phases after implementation exists.

### Audit

```powershell
.\.venv\Scripts\python.exe jobs\utils\audit_wasde_snapshot_inputs.py `
  --bucket leviathan-dev-shahem-001 `
  --output-dir data\phase_wasde_snapshot
```

### Build Snapshot Model-Ready Dataset

```powershell
.\.venv\Scripts\python.exe jobs\submit\submit_batch_model_ready_datasets.py `
  --dataset-keys corn_wasde_snapshot_solo,corn_wasde_snapshot_with_substitutes,grains_wasde_snapshot_segment `
  --source-dataset-version <source_gold_version> `
  --model-dataset-version <new_snapshot_version> `
  --target-source psd `
  --commodities corn_cbot `
  --workers 4 `
  --skip-existing-versioned
```

### Run Snapshot Diagnostics

```powershell
.\.venv\Scripts\python.exe jobs\utils\build_snapshot_feature_diagnostics.py `
  --model-dataset-version <new_snapshot_version> `
  --dataset-keys corn_wasde_snapshot_solo,corn_wasde_snapshot_with_substitutes,grains_wasde_snapshot_segment `
  --output-dir data\phase_wasde_snapshot\diagnostics
```

### Run Smoke Certification

```powershell
.\.venv\Scripts\python.exe jobs\submit\submit_batch_snapshot_certification_grid.py `
  --model-dataset-version <new_snapshot_version> `
  --include-dataset-keys corn_wasde_snapshot_solo `
  --max-jobs 3 `
  --permutation-trials 5 `
  --job-queue leviathan-dev-queue-ondemand
```

### Summarize Reports

```powershell
.\.venv\Scripts\python.exe jobs\utils\summarize_snapshot_candidate_reports.py `
  --model-dataset-version <new_snapshot_version> `
  --output-local data\phase_wasde_snapshot\snapshot_candidate_ranking.parquet
```

## Final Decision Rule

The snapshot plan should continue only if it proves at least one of these:

1. `corn_wasde_snapshot_solo` materially improves corn stress recall without
   unacceptable precision collapse.
2. `corn_wasde_snapshot_with_substitutes` beats solo on at least one corn target
   with economically sensible feature importance.
3. `grains_wasde_snapshot_segment` improves sparse targets without losing
   contract-specific interpretability.

If none of those occur, the root cause is likely not the annual matrix shape
alone. The next review should focus on target definitions, WASDE parse quality,
or whether the desired signal requires additional source-specific data.
