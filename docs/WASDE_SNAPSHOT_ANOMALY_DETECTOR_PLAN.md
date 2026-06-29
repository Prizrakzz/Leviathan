# WASDE Snapshot Anomaly Detector Plan

## Executive Summary

The current supervised WASDE snapshot experiments proved something useful but
uncomfortable: the infrastructure is now much better than the model signal. We
fixed the broken annual-shaped WASDE surface enough to produce:

- 2,455 corn WASDE snapshot rows per balance-sheet target.
- 129 independent annual outcome groups.
- 45 usable WASDE revision features.
- zero duplicate snapshot keys.
- zero detected future-release leakage.
- grouped walk-forward CV by annual outcome group.

The models now beat the zero-anomaly baseline on MAE, but they do not yet beat
strong persistence baselines convincingly, especially on downside recall. That
means the next move should not be another blind XGBoost/LightGBM grid.

The better test is to reframe the first production candidate as a point-in-time
WASDE balance-sheet anomaly detector:

```text
Is this WASDE snapshot historically abnormal for this commodity, origin,
season stage, and marketing year context?
```

This is different from asking:

```text
Will the final annual PSD/WASDE outcome be anomalous?
```

The anomaly-detector framing uses snapshot rows honestly. Each WASDE release is
an observed fundamental state. The model does not pretend that twelve monthly
snapshots create twelve independent final-year labels. Final-year outcomes are
used for evaluation and calibration, not as the first training target.

This plan tests whether transparent, leakage-safe WASDE balance-sheet anomaly
scores provide better early-warning value than supervised final-outcome
regression.

## Core Thesis

### Why The Prior Approach Struggled

The supervised annual-outcome framing creates a statistical bottleneck:

```text
snapshot rows:             2,455
independent annual groups:   129
```

Monthly snapshots add useful state information, but the final label is repeated
across many releases for the same `(origin, market_year)`. The model therefore
has more rows than before, but not 2,455 independent targets.

This is why large tree models can look active while still failing to beat
persistence baselines. They are learning from a small number of independent
crop-year outcomes and a large number of correlated within-year views.

### Why Snapshot Anomaly Detection May Work Better

WASDE itself is a monthly balance-sheet state machine. The thing we observe each
month is not just a final annual result. It is a point-in-time official estimate
of:

- production,
- exports,
- imports,
- domestic use,
- feed/residual use where available,
- ending stocks,
- stock-to-use,
- month-over-month revisions,
- revision streaks,
- first-estimate-to-current changes,
- season-stage tightness.

An anomaly detector can ask whether the current state is historically unusual
without requiring the detector to solve the full final-outcome forecasting
problem.

That output is directly useful to the project:

- The frontend can chart anomaly score through the crop year.
- GraphRAG can explain external shocks around high-score periods.
- SHAP/contribution logic can explain which balance-sheet fields drove the
  score.
- Analyst workflows can tolerate some false positives if false negatives are
  reduced.

## Definitions

### Snapshot Row Grain

The target row grain for this detector is:

```text
contract_key
origin
target_market_year
as_of_date
snapshot_stage
```

Optional dimensions:

```text
dataset_version
dataset_key
commodity_group
wasde_commodity
target_family
source_vintage
release_month
release_sequence_in_year
```

### Snapshot Anomaly Score

A snapshot anomaly score is a point-in-time score computed from official
balance-sheet state and revision features available at `as_of_date`.

It may be:

- a z-score,
- a percentile rank,
- a revision shock score,
- a directional stress score,
- a composite balance-sheet stress score,
- a PCA reconstruction error,
- an Isolation Forest score,
- or a calibrated alert probability built on top of transparent scores.

### Final Outcome Event

Final outcome labels are used for evaluation, not for the first anomaly-score
construction pass.

Examples:

```text
final psd_stock_to_use_anomaly_pct <= event_threshold
final psd_ending_stocks_anomaly_pct <= event_threshold
```

The event threshold must be explicit and versioned. Candidate definitions:

- bottom 20% of historical anomaly values by commodity/origin,
- absolute anomaly below `-10%`,
- stock-to-use anomaly below a business-defined stress threshold,
- ending-stocks anomaly below a business-defined stress threshold.

### Alert

An alert is a thresholded anomaly score at a snapshot date:

```text
alert = anomaly_score >= alert_threshold
```

Alert thresholds must be fit only on historical training periods. They cannot be
chosen using the full future test distribution.

## Current Starting Surface

Use the current Phase 3 snapshot model-ready dataset as the first test surface:

```text
model_dataset_version = 20260629T132008Z_phase3_wasde_snapshot_model_ready
dataset_key = corn_wasde_snapshot_solo
commodity = corn_cbot
```

Read-only inputs:

```text
gold/model_ready_matrices/dataset_version=20260629T132008Z_phase3_wasde_snapshot_model_ready/
gold/model_ready_manifests/dataset_version=20260629T132008Z_phase3_wasde_snapshot_model_ready/manifest.json
gold/feature_set_versions/dataset_version=20260629T132008Z_phase3_wasde_snapshot_model_ready/feature_sets.parquet
silver/wasde/
```

Primary evaluation labels:

```text
psd_stock_to_use_anomaly_pct
psd_ending_stocks_anomaly_pct
```

Do not use `psd_production_anomaly_pct` as the first anomaly-detector target.
Production anomaly is still useful, but the immediate hypothesis is that
balance-sheet stress is easier and more economically aligned.

## Non-Goals

- Do not run another broad supervised model grid before this diagnostic path.
- Do not treat monthly snapshots from the same origin/year as independent final
  labels.
- Do not use global full-history scalers, z-scores, percentiles, PCA, or
  Isolation Forest fits.
- Do not leak future release distributions into historical snapshots.
- Do not use futures prices, raw market direction, technical indicators, or COT
  as core fundamental detector inputs.
- Do not touch GraphRAG code or pipelines.
- Do not delete old S3 artifacts.
- Do not build a generic "agriculture is stressed" model as the first target.

## Feature Context Policy

### Weather Feature Policy

The serious weather path for future WASDE snapshot experiments is:

```text
inseason_weather_dense
```

The legacy broad weather set:

```text
inseason_weather
```

must be treated as legacy, diagnostic, or explicit ablation-only. It should not
enter serious anomaly-detector, supervised snapshot, or production-candidate
sweeps by default.

Rationale:

- `inseason_weather` is too wide and sparse for the current ML sample sizes.
- It can inject hundreds of low-coverage regional columns into small annual or
  snapshot-labeled panels.
- `inseason_weather_dense` replaces that with origin/stage aggregates and model
  ready pruning.
- Dense weather keeps the biological stress story while reducing missingness,
  dimensionality, and accidental overfitting.

Allowed uses:

- `inseason_weather_dense` may be used as the default weather context in
  supervised snapshot experiments, substitute/context scopes, and later hybrid
  anomaly models.
- `inseason_weather` may be used only when the run is explicitly marked as a
  diagnostic or ablation run.
- Ultra-sparse `weather_dense_*` features, especially low-coverage NDVI coverage
  share fields, must remain pruned or diagnostic unless a later cross-commodity
  validation proves incremental value.

First anomaly-detector rule:

Do not add dense weather to the first pure WASDE anomaly score build. First prove
whether the official WASDE balance sheet itself carries an abnormal-state signal.
Then test `inseason_weather_dense` as an explanatory or supervised-context block.

### Redundancy And Correlation Policy

WASDE balance-sheet variables are mechanically related. Examples:

```text
ending_stocks
stock_to_use
ending_stocks_to_use_estimate
total_use
domestic_use
exports
revision_since_first
mom_revision
latest_z
latest_vs_trend_z
```

The plan must not allow a composite stress score to become five copies of the
same tightness fact. Correlation is not automatically bad, but unmeasured
correlation can make the score look stronger and broader than it really is.

Required policy:

- Diagnose correlation clusters among score components before interpreting a
  composite.
- Report redundant feature families and mechanically derived fields.
- Measure one-attribute dominance.
- Measure composite contribution concentration.
- Do not drop correlated features blindly; choose economically representative
  components and document the reason.
- If one attribute cluster dominates the composite, report the score as a
  narrow indicator rather than a broad balance-sheet stress signal.

## Detector Families To Test

### 1. Stage-Normalized Level Scores

Purpose:

Detect whether the current level of a balance-sheet variable is unusual for the
same commodity/origin/stage.

Examples:

```text
stock_to_use_stage_z
ending_stocks_stage_z
exports_stage_z
domestic_use_stage_z
production_stage_z
```

Normalization groups:

```text
contract_key + origin + snapshot_stage
contract_key + origin + release_month
contract_key + snapshot_stage
commodity_group + snapshot_stage
```

The first version should prefer specific groups where history is sufficient and
fallback to broader groups only when history is thin.

Minimum history rule:

```text
minimum_prior_observations >= 10
preferred_prior_observations >= 20
```

Leakage rule:

For snapshot `T`, fit the mean/std/median/MAD using only rows with:

```text
as_of_date < T
```

Never fit level normalization on the full dataset.

### 2. Robust Percentile Scores

Purpose:

Handle non-normal balance-sheet distributions where z-scores are unstable.

Examples:

```text
stock_to_use_prior_percentile
ending_stocks_prior_percentile
exports_prior_percentile
```

For tightness variables, low percentile can mean stress:

```text
stock_to_use_tightness_score = 1 - stock_to_use_prior_percentile
ending_stocks_tightness_score = 1 - ending_stocks_prior_percentile
```

Leakage rule:

Percentile rank must be computed against prior observations only.

### 3. Revision Shock Scores

Purpose:

Detect whether the latest WASDE revision is unusually large.

Examples:

```text
production_mom_revision_z
ending_stocks_mom_revision_z
stock_to_use_mom_revision_z
exports_mom_revision_z
domestic_use_mom_revision_z
```

Directional stress interpretation:

```text
production revision down        -> stress up
ending stocks revision down     -> stress up
stock-to-use revision down      -> stress up
exports revision up             -> stress up
domestic use revision up        -> stress up
imports revision down           -> stress up for deficit origins, context-specific
```

Revision scores should use robust normalization where possible:

```text
revision_robust_z = (revision - prior_median) / prior_MAD
```

Fallback:

Use standard z-score only when MAD is zero or unavailable and prior standard
deviation is valid.

### 4. Revision Momentum And Streak Scores

Purpose:

Detect persistent tightening, not only a single large revision.

Examples:

```text
ending_stocks_down_revision_streak
stock_to_use_down_revision_streak
production_down_revision_streak
exports_up_revision_streak
domestic_use_up_revision_streak
```

Potential derived metrics:

```text
revision_direction_3m_sum
revision_direction_6m_sum
revision_magnitude_3m_sum
revision_magnitude_since_first_forecast
current_vs_first_forecast_pct
```

Leakage rule:

Only use release history up to the current snapshot.

### 5. Directional Balance-Sheet Stress Score

Purpose:

Encode commodity-fundamental logic explicitly before asking ML to discover it.

For a corn tightness detector:

```text
stress increases when:
  production falls
  yield falls where available
  exports rise
  domestic/feed/ethanol use rises
  imports fall
  ending stocks fall
  stock-to-use falls
```

Candidate formula:

```text
directional_stress =
    + tightness(stock_to_use)
    + tightness(ending_stocks)
    + shock_down(production_revision)
    + shock_down(ending_stocks_revision)
    + shock_down(stock_to_use_revision)
    + shock_up(exports_revision)
    + shock_up(domestic_use_revision)
```

All components should be normalized to comparable scales before aggregation.

Initial weights:

Use equal weights first. Do not tune many weights on the same small evaluation
sample.

Later weights:

If needed, learn weights using only training windows and strong regularization.

### 6. Composite Balance-Sheet Stress Index

Purpose:

Create one interpretable score from levels, revisions, and streaks.

Candidate inputs:

```text
stock_to_use_tightness_percentile
ending_stocks_tightness_percentile
stock_to_use_mom_revision_shock
ending_stocks_mom_revision_shock
production_down_revision_shock
exports_up_revision_shock
domestic_use_up_revision_shock
revision_streak_score
```

Output:

```text
wasde_balance_sheet_stress_score
wasde_balance_sheet_stress_percentile
wasde_balance_sheet_stress_alert
```

Acceptance:

The composite must be decomposable into feature contributions. If a score
cannot explain why it fired, it is not ready for the analyst-facing system.

### 7. PCA Reconstruction Anomaly

Purpose:

Detect unusual combinations of balance-sheet variables.

Use only after transparent scores exist.

Rules:

- Fit PCA only on prior training snapshots.
- Use standardized features fit only on prior training snapshots.
- Keep component count small.
- Log reconstruction error by snapshot.
- Log top contributing variables to reconstruction error.

Failure mode:

If PCA score is high but transparent stress score is low, classify the event as
an "unusual configuration" rather than a directional tightness alert.

### 8. Isolation Forest

Purpose:

Test whether a non-linear unsupervised detector finds useful anomalies after
transparent detectors establish the baseline.

Rules:

- Fit only on prior snapshots.
- Tune contamination only on historical validation periods.
- Do not choose contamination using the full test period.
- Use compact feature sets, not every available feature.
- Compare against transparent composite score.

Initial stance:

Isolation Forest is optional and second-order. It should not be the first
production candidate.

### 9. Supervised Calibration Layer

Purpose:

Convert transparent anomaly scores into event probabilities after enough
backtest evidence exists.

Examples:

```text
P(final_stock_to_use_event | current_snapshot_scores)
P(final_ending_stocks_event | current_snapshot_scores)
```

Models:

- logistic regression,
- calibrated gradient boosting,
- isotonic calibration on prior folds only.

Rules:

- Use anomaly scores and compact drivers, not hundreds of raw features.
- Group by `(origin, market_year)` during CV.
- Treat this as a later phase, not the first detector.

## Point-In-Time And Leakage Rules

### Rule 1: No Full-History Normalization

Any transformation that learns distribution parameters must be fit on the
training history available before the scored snapshot.

This includes:

- mean,
- standard deviation,
- median,
- MAD,
- percentiles,
- PCA loadings,
- Isolation Forest trees,
- imputation values,
- clipping bounds,
- alert thresholds.

### Rule 2: Snapshot Date Is The Information Boundary

For a row with:

```text
as_of_date = T
```

all input features must satisfy:

```text
feature_available_at <= T
```

If a source has only annual/latest-history values and no release date, either:

- exclude it from this detector, or
- lag it conservatively and mark it as static context.

### Rule 3: Same Annual Outcome Cannot Cross Train/Test

When evaluating against final annual outcomes, all snapshots belonging to the
same annual group must stay in the same fold:

```text
group = contract_key + origin + target_market_year
```

Forbidden split:

```text
train: June 2020 US corn
test:  August 2020 US corn
```

### Rule 4: Snapshot Weights Must Prevent Year Dominance

If one market year has twelve snapshots and another has four, the twelve-snapshot
year should not dominate model metrics just because it has more releases.

Default:

```text
sample_weight = 1 / snapshot_count_for_annual_group
```

Annual-group metrics should be reported alongside snapshot-row metrics.

### Rule 5: Thresholds Are Trained, Not Picked From The Test Set

Alert thresholds must be chosen using only prior data.

Valid:

```text
choose alert threshold from training folds to maximize F2
apply threshold to held-out future folds
```

Invalid:

```text
choose threshold after looking at all years
report historical best threshold
```

### Rule 6: False Positives Need RCA, Not Automatic Rejection

A false positive may be economically meaningful if:

- the snapshot was genuinely tight,
- later revisions normalized the balance sheet,
- policy/weather/export changes reversed the stress,
- the market had a real scare that did not persist.

False positives should be categorized before deciding the detector is bad.

## Evaluation Metrics

### Snapshot-Level Metrics

Use these for operational behavior:

```text
snapshot_alert_rate
top_10pct_snapshot_precision
top_20pct_snapshot_precision
top_30pct_snapshot_precision
alert_persistence_median_months
alert_volatility
```

### Annual-Outcome Metrics

Use these for business usefulness:

```text
event_recall_any_alert
event_recall_by_stage
event_recall_by_august
event_recall_by_september
median_first_alert_lead_months
false_negative_annual_group_count
false_positive_annual_group_count
annual_precision_any_alert
annual_f2_any_alert
```

### Ranking Metrics

Use these to evaluate score quality without relying on one threshold:

```text
precision_at_top_10pct
precision_at_top_20pct
average_precision
roc_auc_optional
event_score_lift_vs_base_rate
```

Average precision is more useful than ROC AUC if stress events are rare.

### Baseline Comparisons

Every detector must beat simple baselines before it matters:

```text
current_stock_to_use_level_only
current_ending_stocks_level_only
prior_year_stock_to_use
prior_year_ending_stocks
last_release_revision_only
zero_anomaly
trailing_mean
trailing_trend
```

If a detector cannot beat current stock-to-use level or prior-year persistence,
it is not adding enough value.

### Correlation And Redundancy Metrics

Every Phase 2 evaluation must include correlation and redundancy diagnostics for
the score components used in each detector.

Required outputs:

```text
score_component_correlation.parquet
score_component_clusters.parquet
composite_component_contributions.parquet
composite_dominance_report.parquet
redundant_feature_family_report.parquet
```

Minimum required checks:

```text
max_abs_pairwise_correlation
high_correlation_pair_count_at_0_90
high_correlation_pair_count_at_0_95
component_cluster_count
largest_cluster_size
top_attribute_contribution_share
top_feature_contribution_share
effective_component_count
```

Interpretation:

- `max_abs_pairwise_correlation` highlights whether the score is mostly
  redundant.
- `largest_cluster_size` shows whether one balance-sheet concept dominates the
  feature space.
- `top_attribute_contribution_share` shows whether the composite is effectively
  a single-attribute score.
- `effective_component_count` should be computed from contribution shares. A
  low value means the composite may be wide in columns but narrow in signal.

Recommended formula:

```text
effective_component_count = 1 / sum(component_share_i ^ 2)
```

Hard interpretation warning:

If `stock_to_use`, `ending_stocks_to_use_estimate`, `ending_stocks`, and their
revision variants form one dominant cluster, do not present the composite as a
general balance-sheet stress score. Present it as a tightness-dominated score
unless exports, demand, supply, and revision-streak components contribute
meaningfully.

Correlation diagnostics must be computed with the same point-in-time discipline
as the detector:

- exploratory full-sample correlation may be reported as descriptive diagnostics;
- any feature dropping, weighting, or threshold tuning must use training folds
  only;
- do not use future correlation structure to select components for historical
  validation folds.

## Root-Cause Analysis Framework

Every run should classify failures into one or more RCA categories.

### 1. Construction Failure

Symptoms:

- zero usable features,
- duplicate keys,
- future feature availability violations,
- missing required WASDE attributes,
- empty output partitions.

Required artifacts:

```text
construction_summary.json
missing_attribute_report.parquet
duplicate_key_report.parquet
availability_violation_report.parquet
```

### 2. Feature Quality Failure

Symptoms:

- too many sparse features,
- constant features,
- unstable normalization groups,
- insufficient prior history,
- stage coverage gaps.

Required artifacts:

```text
feature_quality_report.parquet
normalization_group_coverage.parquet
dropped_features.parquet
score_component_correlation.parquet
score_component_clusters.parquet
composite_dominance_report.parquet
redundant_feature_family_report.parquet
```

Additional required diagnostics:

- correlation clusters among component scores;
- redundant feature families;
- one-attribute dominance;
- composite contribution concentration;
- sparse-score concentration by origin/stage;
- whether high alert scores come from one attribute or several independent
  balance-sheet dimensions.

### 3. Target/Event Definition Failure

Symptoms:

- event rate too high or too low,
- events concentrated in one origin,
- event threshold produces unstable labels,
- final event definition conflicts with economic intuition.

Required artifacts:

```text
target_event_distribution.parquet
event_by_origin_year.parquet
threshold_sensitivity.parquet
```

### 4. Baseline Failure

Symptoms:

- detector beats zero baseline but not prior-year baseline,
- detector recall lower than simple level-based rules,
- detector only works in one stage.

Required artifacts:

```text
baseline_comparison.parquet
metric_by_snapshot_stage.parquet
metric_by_origin.parquet
```

### 5. False Negative Failure

Symptoms:

- known tight years are never flagged,
- alerts come too late,
- detector misses origin-specific events.

Required artifacts:

```text
false_negative_cases.parquet
false_negative_case_notes.md
missing_driver_analysis.parquet
```

Questions to answer:

- Was the WASDE snapshot itself not abnormal before the event?
- Was the event caused by a non-WASDE driver?
- Was the needed attribute missing or mis-mapped?
- Did normalization compare against the wrong stage/origin?
- Was the alert threshold too conservative?

### 6. False Positive Failure

Symptoms:

- too many benign years are flagged,
- stress scores fire on noisy revisions,
- alert persistence is too high.

Required artifacts:

```text
false_positive_cases.parquet
false_positive_case_notes.md
alert_persistence_report.parquet
```

Questions to answer:

- Did later WASDE revisions normalize the balance sheet?
- Was there a genuine temporary stress?
- Was the detector too sensitive to one attribute?
- Did a fallback normalization group cause an exaggerated score?

### 7. Drift Or Regime Failure

Symptoms:

- detector works pre-2000 but fails post-2000,
- performance changes after ethanol demand regime,
- performance differs by origin.

Required artifacts:

```text
metric_by_era.parquet
metric_by_origin.parquet
metric_by_policy_regime_optional.parquet
```

## Experiment Scopes

### Scope A: `corn_wasde_snapshot_solo`

Purpose:

Pure corn detector. This is the cleanest first test.

Inputs:

- corn WASDE levels,
- corn WASDE revisions,
- corn stock/use,
- corn ending stocks,
- corn production/use/export revisions,
- optional static context already in the Phase 3 matrix.

Decision:

This is the benchmark. If this fails badly, do not pretend a broader system is
ready.

### Scope B: `corn_wasde_snapshot_with_substitutes`

Purpose:

Corn detector with economically relevant substitute and demand context.

Candidate added context:

- wheat balance-sheet tightness,
- soybean/feed/oilseed context where relevant,
- energy/input-cost context only if already certified as an economic driver,
- feed demand proxies,
- export competition context.

Decision:

This is likely the strongest quant design if substitution and feed competition
matter. It should be tested only after Scope A has clean detector artifacts.

### Scope C: `grains_wasde_snapshot_segment`

Purpose:

Pool corn, wheat, and rice-like grain balance-sheet behavior while preserving
contract-specific outputs.

Rules:

- include `contract_key`,
- include `commodity_group`,
- include `origin`,
- do not collapse to generic agriculture,
- evaluate per contract and pooled.

Decision:

This tests whether shared balance-sheet mechanics provide more effective sample
size without losing commodity identity.

## Daily Inference Position

Daily inference is allowed, but daily training rows are not the first fix.

For days between WASDE releases:

```text
latest_wasde_snapshot_score is carried forward
score_age_days is incremented
new daily certified features may update separately
```

This gives the frontend and agents a daily signal without pretending that WASDE
changes every day.

Future daily model-ready grain:

```text
contract_key
origin
target_market_year
as_of_date
latest_wasde_release_date
score_age_days
wasde_snapshot_anomaly_score
daily_available_features
```

Training daily rows requires stricter weighting:

```text
sample_weight = 1 / number_of_daily_rows_for_annual_group
```

Do not create daily training data until the release-date detector works.

## Proposed S3 Outputs

First detector outputs:

```text
gold/wasde_snapshot_anomaly_scores/
  dataset_version={version}/
  dataset_key={dataset_key}/
  commodity={commodity}/
  detector_id={detector_id}/
  part-000.parquet
```

Run artifacts:

```text
model_artifacts/wasde_snapshot_anomaly_detection/
  run_id={run_id}/
  detector_report.json
  snapshot_scores.parquet
  top_alerts.parquet
  false_negative_cases.parquet
  false_positive_cases.parquet
  event_recall_by_stage.parquet
  baseline_comparison.parquet
  feature_contributions.parquet
  normalization_group_coverage.parquet
```

Do not overwrite existing supervised candidate certification outputs.

## Proposed Configs

New config:

```text
configs/ml/wasde_snapshot_anomaly_detectors.yaml
```

Suggested contents:

```yaml
detectors:
  stage_level_z:
    type: rolling_stage_zscore
    min_prior_observations: 10
    preferred_prior_observations: 20
    normalization_fallbacks:
      - contract_origin_stage
      - contract_stage
      - commodity_group_stage
    attributes:
      - stock_to_use
      - ending_stocks
      - exports
      - domestic_use
      - production

  revision_shock:
    type: rolling_revision_shock
    robust: true
    min_prior_observations: 10
    attributes:
      - stock_to_use
      - ending_stocks
      - exports
      - domestic_use
      - production

  composite_balance_sheet_stress:
    type: weighted_composite
    components:
      - stock_to_use_tightness_percentile
      - ending_stocks_tightness_percentile
      - stock_to_use_mom_revision_shock
      - ending_stocks_mom_revision_shock
      - production_down_revision_shock
      - exports_up_revision_shock
      - domestic_use_up_revision_shock
    weight_policy: equal_weight_v1
```

Event config:

```yaml
events:
  stock_to_use_tightness:
    target_key: psd_stock_to_use_anomaly_pct
    threshold_policy: bottom_quantile_by_training_window
    quantile: 0.20

  ending_stocks_tightness:
    target_key: psd_ending_stocks_anomaly_pct
    threshold_policy: bottom_quantile_by_training_window
    quantile: 0.20
```

## Proposed Code Surface

Likely new files:

```text
src/leviathan/model_datasets/wasde_snapshot_anomaly_scores.py
src/leviathan/model_datasets/wasde_snapshot_anomaly_eval.py
src/leviathan/model_datasets/wasde_snapshot_anomaly_rca.py
jobs/utils/build_wasde_snapshot_anomaly_scores.py
jobs/batch/wasde_snapshot_anomaly_scores_task.py
jobs/submit/submit_batch_wasde_snapshot_anomaly_scores.py
jobs/utils/register_wasde_snapshot_anomaly_scores_jobdef.py
```

Likely tests:

```text
tests/unit/test_wasde_snapshot_anomaly_scores.py
tests/unit/test_wasde_snapshot_anomaly_eval.py
tests/unit/test_wasde_snapshot_anomaly_rca.py
tests/unit/test_wasde_snapshot_anomaly_leakage.py
```

Likely docs/artifacts:

```text
data/phase_wasde_snapshot/anomaly_detection/
```

## MLflow Tracking

Experiment:

```text
wasde_snapshot_anomaly_detection
```

Required tags:

```text
commodity
dataset_key
detector_id
detector_type
model_dataset_version
fit_policy=rolling_prior_only
uses_future_distribution=false
event_target_key
event_threshold_policy
normalization_policy
min_prior_observations
snapshot_weight_policy
source_gold_dataset_version
```

Required metrics:

```text
event_recall_any_alert
event_recall_by_august
event_recall_by_september
annual_precision_any_alert
annual_f2_any_alert
top_10pct_precision
top_20pct_precision
false_negative_count
false_positive_count
median_first_alert_lead_months
snapshot_alert_rate
baseline_lift_top_20pct
```

Required artifacts:

```text
detector_report.json
snapshot_scores.parquet
top_alerts.parquet
false_negative_cases.parquet
false_positive_cases.parquet
event_recall_by_stage.parquet
baseline_comparison.parquet
feature_contributions.parquet
normalization_group_coverage.parquet
score_component_correlation.parquet
score_component_clusters.parquet
composite_dominance_report.parquet
redundant_feature_family_report.parquet
```

## Phased Implementation Roadmap

### Phase 0 - Anomaly Detector Audit

Objective:

Confirm the available WASDE snapshot feature columns, row grain, event labels,
and evaluation groups before writing detector code.

Tasks:

- Read the Phase 3 model-ready manifest.
- Confirm row uniqueness by:

  ```text
  contract_key, origin, target_market_year, as_of_date, snapshot_stage
  ```

- Confirm `feature_available_at <= as_of_date` if availability columns are
  present.
- Summarize available WASDE level, revision, streak, and stock/use features.
- Summarize independent group counts by origin and target.
- Summarize event rates under candidate event thresholds.
- Produce an audit artifact:

  ```text
  data/phase_wasde_snapshot/anomaly_detection/phase0_audit.json
  ```

Files likely affected:

```text
jobs/utils/audit_wasde_snapshot_anomaly_inputs.py
data/phase_wasde_snapshot/anomaly_detection/
```

Risks:

- Event labels may be too imbalanced.
- Required level fields may be missing from the matrix.
- Stock/use may be derived inconsistently across origins.

Validation:

- no duplicate snapshot keys;
- no missing required ID columns;
- at least 100 independent annual groups for corn solo;
- at least 20 stress events under the first threshold policy.

Acceptance criteria:

- Written audit report.
- Clear go/no-go recommendation for Phase 1.

Reversibility:

Safe and fully reversible. Read-only except local audit artifacts.

Explicitly do not:

- train models;
- tune thresholds;
- write S3 outputs;
- alter existing model-ready datasets.

### Phase 1 - Transparent Detector Prototype

Objective:

Build the first leakage-safe transparent anomaly scores for
`corn_wasde_snapshot_solo`.

Tasks:

- Implement rolling prior-only level z-scores.
- Implement rolling prior-only robust percentiles.
- Implement revision shock scores.
- Implement revision streak scores.
- Implement a simple equal-weight composite stress score.
- Log normalization group coverage.
- Drop or flag scores with insufficient history.

Files likely affected:

```text
configs/ml/wasde_snapshot_anomaly_detectors.yaml
src/leviathan/model_datasets/wasde_snapshot_anomaly_scores.py
tests/unit/test_wasde_snapshot_anomaly_scores.py
```

Risks:

- Stage groups may be too thin.
- Some attributes may be missing or constant.
- Robust z-scores may fail when MAD is zero.

Validation:

- Unit tests prove current row is excluded from its own normalization history.
- Unit tests prove future rows do not affect historical scores.
- Known synthetic revision shocks produce expected signs.
- Composite stress increases when stocks/use fall and exports/use rise.

Acceptance criteria:

- Scores computed for at least 80% of corn snapshots for core attributes.
- No future-distribution leakage.
- Score signs match economic intuition.

Reversibility:

Safe. Adds code and local test artifacts only.

Explicitly do not:

- introduce Isolation Forest;
- tune composite weights;
- promote any score.

### Phase 2 - Rolling Backtest Evaluation

Objective:

Evaluate transparent scores in a way that matches the business use case.

Tasks:

- Implement annual-group-aware event evaluation.
- Implement threshold selection using prior training windows only.
- Report recall by stage and first-alert timing.
- Compare against simple baselines.
- Build missingness and score-coverage diagnostics by detector, target, origin,
  and snapshot stage.
- Build correlation clusters among score components.
- Build redundant feature family diagnostics.
- Build composite component dominance diagnostics.
- Generate false-negative and false-positive case tables.

Files likely affected:

```text
src/leviathan/model_datasets/wasde_snapshot_anomaly_eval.py
src/leviathan/model_datasets/wasde_snapshot_anomaly_rca.py
src/leviathan/model_datasets/wasde_snapshot_anomaly_diagnostics.py
tests/unit/test_wasde_snapshot_anomaly_eval.py
tests/unit/test_wasde_snapshot_anomaly_rca.py
tests/unit/test_wasde_snapshot_anomaly_diagnostics.py
```

Risks:

- A detector may look good at snapshot level but weak at annual-event level.
- Thresholds may be unstable across eras.
- False positives may dominate if composite is too sensitive.
- Composite scores may double-count highly correlated stock/use and ending-stock
  components.
- A high score may be driven by one attribute family, not broad balance-sheet
  stress.

Validation:

- Grouped evaluation never splits the same annual group across train/test.
- Alert thresholds are learned from training folds only.
- Baseline comparison includes prior-year and current-level rules.
- Correlation diagnostics identify high-correlation component clusters.
- Composite dominance diagnostics report top feature and top attribute
  contribution share.
- Score coverage diagnostics explain missing components by stage and origin.

Acceptance criteria:

- Report includes event recall, precision, false negatives, false positives,
  first-alert timing, and baseline lift.
- Report includes missingness, correlation, redundancy, and component-dominance
  diagnostics.
- Composite stress cannot be interpreted as "broad" unless contribution
  concentration is acceptable or explicitly disclosed.
- At least one transparent detector beats a simple baseline on recall or
  early-warning timing without unacceptable false positives.

Reversibility:

Safe. Adds evaluation code and artifacts.

Explicitly do not:

- run full commodity grids;
- train opaque ML detectors;
- claim production readiness.

### Phase 3 - Root-Cause Review

Objective:

Decide whether failures are caused by features, target/event definition,
normalization, thresholds, or economics.

Tasks:

- Review false negatives by origin/year.
- Review false positives by origin/year.
- Classify each miss:

  ```text
  no_wasde_signal
  missing_driver
  bad_mapping
  threshold_too_strict
  stage_normalization_issue
  genuine_temporary_stress
  final_outcome_reversal
  ```

- Produce a casebook markdown/report.

Files likely affected:

```text
data/phase_wasde_snapshot/anomaly_detection/phase3_rca/
docs/WASDE_SNAPSHOT_ANOMALY_DETECTOR_RCA.md
```

Risks:

- RCA may show WASDE state is not enough for early alerts.
- RCA may show the event definition is not aligned with business need.

Validation:

- Every false negative has a reason code.
- Every top false positive has a reason code.
- At least one actionable next step is identified.

Acceptance criteria:

- Clear decision:

  ```text
  proceed_with_corn_solo
  add_substitute_context
  reform_event_definition
  fix_feature_mapping
  stop_this_path
  ```

Reversibility:

Safe. Analysis artifacts only.

Explicitly do not:

- hide bad results;
- move to a wider grid without RCA.

### Phase 4 - Substitute And Segment Scope Tests

Objective:

Test whether economically broader context improves detection.

Scopes:

```text
corn_wasde_snapshot_solo
corn_wasde_snapshot_with_substitutes
grains_wasde_snapshot_segment
```

Tasks:

- Define exact substitute/context features for corn.
- Use `inseason_weather_dense` as the only serious weather context block when
  weather is admitted.
- Keep legacy `inseason_weather` out of serious Phase 4 runs unless the run is
  explicitly labeled `weather_sparse_ablation`.
- Verify dense-weather pruning still removes ultra-sparse coverage-share
  features before matrix build.
- Build or reuse model-ready snapshot surfaces.
- Re-run transparent detectors.
- Compare recall, precision, and first-alert timing.
- Compare per-origin and per-stage behavior.

Files likely affected:

```text
configs/ml/wasde_snapshot_mappings.yaml
configs/ml/wasde_snapshot_anomaly_detectors.yaml
configs/features/feature_sets.yaml
src/leviathan/model_datasets/wasde_snapshot_static_join.py
```

S3 prefixes affected:

```text
gold/model_ready_matrices/dataset_version={new_version}/
gold/wasde_snapshot_anomaly_scores/dataset_version={new_version}/
```

Risks:

- Substitute features may add noise.
- Segment pooling may dilute corn-specific behavior.
- More rows may still not be truly independent if groups are mishandled.
- Accidentally using legacy `inseason_weather` can reintroduce hundreds of
  sparse weather columns and invalidate the cleaned feature-set strategy.

Validation:

- Same grouped CV rules.
- Same threshold rules.
- Compare against solo benchmark.
- Feature-set manifest shows `inseason_weather_dense` for weather context and
  does not include legacy `inseason_weather` unless the run is an explicit
  ablation.
- Dense-weather low-coverage exclusions are recorded.

Acceptance criteria:

- Broader scope must improve at least one core metric without materially
  worsening false negatives:

  ```text
  event_recall_any_alert
  event_recall_by_august
  top_20pct_precision
  false_negative_count
  ```

Reversibility:

Safe if written under new immutable dataset versions.

Explicitly do not:

- replace solo benchmark;
- promote pooled model without per-contract metrics.
- use legacy `inseason_weather` as a default weather block.

### Phase 5 - Optional ML Detectors

Objective:

Test whether ML detectors add value after transparent detectors establish
baselines.

Candidate detectors:

- PCA reconstruction error,
- Isolation Forest,
- regularized logistic calibration over transparent scores.

Tasks:

- Fit only on prior snapshots.
- Use compact feature sets.
- Log feature contributions or reconstruction drivers.
- Compare directly to composite stress score.

Files likely affected:

```text
src/leviathan/model_datasets/wasde_snapshot_anomaly_scores.py
src/leviathan/model_datasets/wasde_snapshot_anomaly_eval.py
tests/unit/test_wasde_snapshot_anomaly_leakage.py
```

Risks:

- Opaque detectors may overfit.
- PCA/Isolation Forest may detect "unusual" but not "tight/stressful".
- Threshold tuning can leak if done carelessly.

Validation:

- Synthetic leakage tests.
- Historical rolling-fit tests.
- Transparent baseline comparison.

Acceptance criteria:

- ML detector must beat transparent composite on at least one major business
  metric and not become less interpretable.

Reversibility:

Safe.

Explicitly do not:

- start with opaque ML;
- use full-history scaler/detector fits.

### Phase 6 - Batch And MLflow Integration

Objective:

Make detector runs reproducible in Batch and trackable in MLflow.

Tasks:

- Add Batch task and submitter.
- Add job definition registration utility.
- Add MLflow experiment logging.
- Write immutable S3 outputs.
- Emit manifest with config SHA, dataset version, detector ID, and leakage
  policy.

Files likely affected:

```text
jobs/batch/wasde_snapshot_anomaly_scores_task.py
jobs/submit/submit_batch_wasde_snapshot_anomaly_scores.py
jobs/utils/register_wasde_snapshot_anomaly_scores_jobdef.py
src/leviathan/training/tracking.py
```

S3 prefixes affected:

```text
gold/wasde_snapshot_anomaly_scores/
model_artifacts/wasde_snapshot_anomaly_detection/
```

Risks:

- Batch image may miss dependencies.
- MLflow server connectivity may fail.
- S3 output version collisions.

Validation:

- Local dry run.
- One Batch smoke run.
- MLflow run contains metrics, tags, and artifact URIs.
- S3 manifest validates.

Acceptance criteria:

- One successful corn solo Batch smoke.
- Report and MLflow run can be reopened and audited.

Reversibility:

Safe if output paths are immutable.

Explicitly do not:

- run wide grids before smoke succeeds.

### Phase 7 - Decision Gate

Objective:

Decide whether anomaly detection becomes the first production candidate path.

Minimum promotion-to-next-stage gate:

```text
no leakage violations
event_recall_any_alert >= 70% OR clear improvement over all baselines
event_recall_by_august >= 50% for in-season usefulness
top_20pct_precision > base_event_rate by meaningful lift
false_negative_count lower than prior-year baseline
interpretable top drivers
stable enough across origins and eras
```

If the detector fails:

- classify failure using RCA,
- decide whether to fix features, event definition, scope, or stop.

If the detector passes:

- create frontend-ready chart requirements,
- create daily carry-forward scoring design,
- define production inference contract.

Reversibility:

Decision phase only. No destructive action.

Explicitly do not:

- deploy to production only because a Batch job succeeded;
- hide weak baseline comparisons.

## Test Plan

### Unit Tests

```text
tests/unit/test_wasde_snapshot_anomaly_scores.py
```

Test cases:

- `test_rolling_zscore_excludes_current_row`
- `test_rolling_zscore_excludes_future_rows`
- `test_percentile_uses_prior_history_only`
- `test_revision_shock_direction_for_tightness`
- `test_composite_stress_increases_when_stock_to_use_falls`
- `test_insufficient_history_returns_null_and_reason`
- `test_fallback_normalization_group_is_recorded`

```text
tests/unit/test_wasde_snapshot_anomaly_eval.py
```

Test cases:

- `test_grouped_eval_keeps_annual_group_together`
- `test_alert_threshold_fit_on_train_only`
- `test_event_recall_any_alert`
- `test_event_recall_by_stage`
- `test_first_alert_lead_months`
- `test_snapshot_weights_sum_to_one_per_annual_group`

```text
tests/unit/test_wasde_snapshot_anomaly_diagnostics.py
```

Test cases:

- `test_component_correlation_clusters_highly_related_scores`
- `test_redundant_feature_family_report_groups_stock_use_variants`
- `test_composite_dominance_reports_top_attribute_share`
- `test_effective_component_count_declines_when_one_component_dominates`
- `test_descriptive_correlation_does_not_select_future_fold_features`
- `test_dense_weather_policy_blocks_legacy_inseason_weather_by_default`
- `test_dense_weather_policy_allows_legacy_weather_only_for_ablation`

```text
tests/unit/test_wasde_snapshot_anomaly_rca.py
```

Test cases:

- `test_false_negative_case_table_contains_required_columns`
- `test_false_positive_case_table_contains_required_columns`
- `test_rca_reason_codes_are_valid`
- `test_baseline_comparison_contains_required_baselines`

```text
tests/unit/test_wasde_snapshot_anomaly_leakage.py
```

Test cases:

- `test_full_history_scaler_is_rejected`
- `test_future_distribution_changes_do_not_change_past_scores`
- `test_same_group_train_test_split_rejected`
- `test_threshold_uses_only_prior_fold`

### Integration Tests

```text
tests/integration/test_wasde_snapshot_anomaly_pipeline.py
```

Test cases:

- local corn solo dry run writes expected files;
- no duplicate keys in output scores;
- report contains metrics and RCA artifact URIs;
- immutable output version refuses overwrite.

### Data Quality Tests

Required checks:

- row count by origin/stage;
- score coverage by feature and stage;
- normalization history count by row;
- score component correlation clusters;
- redundant feature family report;
- composite contribution dominance;
- effective component count;
- dense-weather policy check;
- event rate by origin;
- top alert sanity table;
- false negative table;
- baseline comparison table.

## First Concrete Smoke Run

The first real run should be:

```text
commodity = corn_cbot
dataset_key = corn_wasde_snapshot_solo
model_dataset_version = 20260629T132008Z_phase3_wasde_snapshot_model_ready
event_target_key = psd_stock_to_use_anomaly_pct
detectors =
  stage_level_z
  revision_shock
  composite_balance_sheet_stress
fit_policy = rolling_prior_only
min_prior_observations = 10
snapshot_weight_policy = inverse_snapshots_per_annual_group
```

Primary readout:

```text
event_recall_any_alert
event_recall_by_august
top_20pct_precision
false_negative_count
false_positive_count
median_first_alert_lead_months
baseline_lift_vs_prior_year
baseline_lift_vs_current_stock_to_use
```

## Interpretation Rules

### Good Result

The path is promising if:

- transparent composite beats prior-year and current-level baselines;
- false negatives drop materially;
- alerts happen before late season;
- top drivers make economic sense;
- performance is not concentrated in one origin.

Next action:

Move to substitute context and segment pooling.

### Mixed Result

The path is mixed if:

- recall improves but false positives explode;
- score works only in one stage;
- score works only for one origin;
- stock-to-use works but ending stocks does not.

Next action:

Run RCA before changing model class.

### Bad Result

The path is weak if:

- simple current stock/use level beats the detector;
- prior-year persistence beats the detector on both recall and precision;
- false negatives remain high;
- top alerts are economically nonsensical;
- normalization groups are too thin.

Next action:

Do not run opaque ML. Fix event definition, feature mapping, or scope first.

## Final Position

This anomaly-detector path is not a shortcut around hard modeling. It is a more
honest formulation of the WASDE problem.

The supervised final-outcome model asks a hard question with few independent
labels:

```text
Will the final annual balance-sheet anomaly be bad?
```

The snapshot anomaly detector asks a cleaner point-in-time question:

```text
Is the official balance-sheet state abnormal right now?
```

If this works, it can become the first production-grade fundamental alert layer.
The supervised final-outcome models can remain research candidates and later use
the anomaly scores as compact, interpretable features.
