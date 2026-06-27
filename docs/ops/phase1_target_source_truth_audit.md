# Phase 1 Target-Source Truth Audit

Date: 2026-06-27

Scope: PSD-first restructuring Phase 1. This audit proves the source,
coverage, metadata, leakage posture, and recommended future status of the
current supervised target family. It does not implement PSD targets, modify
configs, rebuild datasets, mark old datasets deprecated, or mutate S3/Glue/
Athena/MLflow.

## Executive Summary

The current supervised model-ready target family is confirmed as a FAOSTAT
annual physical anomaly surface, not a PSD target surface.

Current active versions:

- Source gold dataset version:
  `20260626T010217Z_6725de02_phase7_full`
- Model-ready dataset version:
  `20260626T104732Z_a2576e84_phase8_model_ready`

Current model-ready dataset key:

```text
annual_physical_anomaly
```

Current configured targets:

```text
production_anomaly_pct
yield_anomaly_pct
area_harvested_anomaly_pct
```

All three targets are derived from FAOSTAT label features emitted from
`production:faostat`:

| target_key | label_column | true source |
|---|---|---|
| `production_anomaly_pct` | `label_production_quantity` | `production:faostat` |
| `yield_anomaly_pct` | `label_yield` | `production:faostat` |
| `area_harvested_anomaly_pct` | `label_area_harvested` | `production:faostat` |

The active model-ready manifest has 93 target attempt entries, of which 83 were
built:

- `production_anomaly_pct`: 31 built commodities
- `yield_anomaly_pct`: 26 built commodities, 5 skipped missing label
- `area_harvested_anomaly_pct`: 26 built commodities, 5 skipped missing label

The missing yield/area commodities are oil/palm contracts where FAOSTAT label
coverage does not include `label_yield` or `label_area_harvested`:

```text
malaysian_crude_palm_oil_cme
palm_olein_dce
rapeseed_oil_zce
soybean_oil_cbot
soybean_oil_dce
```

The current implementation is mostly technically anti-leakage for annual
experiments:

- Target trend baselines use only prior years.
- Walk-forward CV trains only on years before the test year.
- Model-ready training removes `label_*` columns from model inputs.
- FAOSTAT feature rows use prior-history visibility, while FAOSTAT labels are
  marked `is_label=true`.

However, the target metadata is not explicit enough for professional
futures-linked research. The target tables do not expose `target_source`,
`label_source`, `source_table`, `target_market_year`, `target_release_context`,
or `final_value_policy`. That gap must be closed in the PSD-first target
builder and model-ready dataset schema.

Recommendation: keep the current targets as `legacy_baseline` for comparison
and engineering regression, but do not treat them as the primary target spine
for futures-linked commodity models.

## Current Target Definitions

Observed config:

```text
configs/ml/target_definitions.yaml
```

Observed defaults:

```text
source_dataset_version: 20260626T010217Z_6725de02_phase7_full
min_history_years: 5
target_type: trailing_trend_pct_anomaly
feature_set_policy: compatible_union
baselines:
  - zero_anomaly
  - prior_year
  - trailing_mean
  - trailing_linear_trend
```

Configured targets:

| target_key | dataset_key | title | label_column | actual_column | target_unit | horizon | grain |
|---|---|---|---|---|---|---|---|
| `production_anomaly_pct` | `annual_physical_anomaly` | Production anomaly versus trailing trend | `label_production_quantity` | `production_quantity` | `pct_deviation` | `final_crop_year` | commodity, country, crop_year |
| `yield_anomaly_pct` | `annual_physical_anomaly` | Yield anomaly versus trailing trend | `label_yield` | `yield` | `pct_deviation` | `final_crop_year` | commodity, country, crop_year |
| `area_harvested_anomaly_pct` | `annual_physical_anomaly` | Harvested-area anomaly versus trailing trend | `label_area_harvested` | `area_harvested` | `pct_deviation` | `final_crop_year` | commodity, country, crop_year |

Current compatible feature sets:

```text
preseason_physical
inseason_weather
crop_condition
official_revision
physical_flow
balance_sheet
planting_incentives
trade_competitiveness
tail_risk
data_quality
```

The existing `future_target_families` entries are planned placeholders, not
active model-ready datasets:

```text
official_revision
weekly_or_fortnightly_trajectory
quality_event
anomaly_detection_panel
```

## Target Creation Code Path

Observed files:

- `src/leviathan/model_datasets/targets.py`
- `src/leviathan/model_datasets/builder.py`
- `src/leviathan/model_datasets/baselines.py`
- `jobs/batch/build_model_ready_datasets.py`
- `src/leviathan/training/model_ready.py`

Observed flow:

```text
configs/ml/target_definitions.yaml
  -> TargetDefinition
  -> gold/feature_matrix_versions/{source_dataset_version}/{commodity}
  -> builder checks definition.label_column exists in matrix
  -> build_trailing_anomaly_targets(...)
  -> gold/model_ready_targets/{model_dataset_version}
  -> gold/model_ready_matrices/{model_dataset_version}
```

Important implementation facts:

- `builder.py` skips a target for a commodity if
  `definition.label_column` is missing.
- `builder.py` skips a target for a commodity if the label column exists but is
  entirely null.
- `builder.py` excludes `label_*` columns from the feature columns used in the
  target-specific model-ready matrix.
- `baselines.py` uses `country`, `crop_year`, and the configured label column
  to construct `actual_value`.
- `baselines.py` emits rows with `is_trainable=false` when the actual, trend,
  or history is insufficient.

Current target algorithm:

```text
target_value = (actual_value - trend_prediction) / abs(trend_prediction)
```

This is equivalent to `actual / trend - 1` when the trend prediction is
positive. Exact zero trend denominators currently return null.

## Label Source Evidence

Observed files:

- `src/leviathan/features/computations/production.py`
- `configs/features/features.yaml`
- `configs/features/feature_taxonomy.yaml`
- active feature catalog in S3

`production.py` defines:

```text
_LABEL_VARIABLES = ("production_quantity", "area_harvested", "yield")
```

`compute_faostat_labels(...)` reads:

```text
ctx.inputs.get("production:faostat")
```

It then emits:

```text
label_production_quantity
label_area_harvested
label_yield
```

for matching FAOSTAT source years and model crop years.

`configs/features/features.yaml` defines:

```yaml
- family: faostat_labels
  sources: ["production:faostat"]
  visibility: crop_year_direct
  commodities: all
  is_label: true
```

`configs/features/feature_taxonomy.yaml` classifies all `^label_` features as:

```text
feature_family: labels
semantic_scope: target_label
policy: fundamental_physical
mechanism: supervised_target
sources: ["production:faostat"]
source_cadence: annual
```

Active feature catalog evidence:

| feature | is_label | sources | feature_family | semantic_scope | policy | commodity_count | row_count | first_event_time | last_event_time |
|---|---:|---|---|---|---|---:|---:|---|---|
| `label_area_harvested` | true | `production:faostat` | `labels` | `target_label` | `fundamental_physical` | 26 | 3,535 | 1981-01-01 | 2024-10-01 |
| `label_production_quantity` | true | `production:faostat` | `labels` | `target_label` | `fundamental_physical` | 31 | 4,137 | 1981-01-01 | 2024-10-01 |
| `label_yield` | true | `production:faostat` | `labels` | `target_label` | `fundamental_physical` | 26 | 3,535 | 1981-01-01 | 2024-10-01 |

Conclusion:

```text
The current supervised target labels are FAOSTAT labels.
They are not PSD, NASS, WASDE, or local-agency labels.
```

## Commodity Coverage

Source manifest:

```text
s3://leviathan-dev-shahem-001/gold/model_ready_manifests/dataset_version=20260626T104732Z_a2576e84_phase8_model_ready/manifest.json
```

Manifest summary:

```text
requested_commodity_count: 31
processed_commodity_count: 31
skipped_commodity_count: 0
failed_commodity_count: 0
built_target_count: 83
target_row_count: 11,822
matrix_count: 83
baseline_metric_count: 332
```

The manifest has 93 target attempt entries:

```text
31 commodities x 3 configured targets = 93 attempts
```

Status counts:

| target_key | status | count |
|---|---|---:|
| `production_anomaly_pct` | `built` | 31 |
| `yield_anomaly_pct` | `built` | 26 |
| `yield_anomaly_pct` | `skipped_missing_label` | 5 |
| `area_harvested_anomaly_pct` | `built` | 26 |
| `area_harvested_anomaly_pct` | `skipped_missing_label` | 5 |

Built-only coverage:

| target_key | built commodities | built entries | target rows | trainable rows | missing/skipped commodities |
|---|---:|---:|---:|---:|---|
| `production_anomaly_pct` | 31 | 31 | 4,370 | 3,662 | none |
| `yield_anomaly_pct` | 26 | 26 | 3,726 | 3,130 | `malaysian_crude_palm_oil_cme`, `palm_olein_dce`, `rapeseed_oil_zce`, `soybean_oil_cbot`, `soybean_oil_dce` |
| `area_harvested_anomaly_pct` | 26 | 26 | 3,726 | 3,130 | `malaysian_crude_palm_oil_cme`, `palm_olein_dce`, `rapeseed_oil_zce`, `soybean_oil_cbot`, `soybean_oil_dce` |

Explanation of `83` built targets:

```text
31 production targets
+ 26 yield targets
+ 26 harvested-area targets
= 83 built target outputs
```

The five missing yield/area commodities are oil or palm-product contracts where
the FAOSTAT label surface has production coverage but not yield/area label
coverage. That is not necessarily a data bug. It is a source-grain limitation
that Phase 2/3 should avoid repeating blindly for PSD target design.

## Active Target Table Schema

Sample target table:

```text
s3://leviathan-dev-shahem-001/gold/model_ready_targets/dataset_version=20260626T104732Z_a2576e84_phase8_model_ready/dataset_key=annual_physical_anomaly/commodity=corn_cbot/part-000.parquet
```

Observed shape:

```text
552 rows x 20 columns
```

Observed columns:

```text
source_dataset_version
dataset_key
commodity
target_key
target_title
target_unit
country
crop_year
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
```

Corn target table summary:

| target_key | rows | trainable | min_year | max_year |
|---|---:|---:|---:|---:|
| `area_harvested_anomaly_pct` | 184 | 145 | 1981 | 2026 |
| `production_anomaly_pct` | 184 | 145 | 1981 | 2026 |
| `yield_anomaly_pct` | 184 | 145 | 1981 | 2026 |

Current metadata present:

- source gold dataset version
- dataset key
- commodity
- target key
- target title
- target unit
- country
- crop year
- actual value
- target value
- trend/baseline values
- trainability and exclusion reason

Current metadata missing:

- `target_source`
- `label_source`
- `source_table`
- `source_dataset_key`
- `target_family`
- `target_attribute`
- `target_source_attribute`
- `target_market_year`
- `marketing_year`
- `target_release_context`
- `target_observation_release_date`
- `target_source_vintage`
- `final_value_policy`
- `proxy_scope`
- `mapping_sha`

Phase 3/5 requirement:

PSD-first target rows should include explicit target-source and market-year
metadata. Otherwise future researchers will face the same ambiguity with PSD
targets that now exists with FAOSTAT targets.

## Model-Ready Matrix Evidence

Sample matrix:

```text
s3://leviathan-dev-shahem-001/gold/model_ready_matrices/dataset_version=20260626T104732Z_a2576e84_phase8_model_ready/dataset_key=annual_physical_anomaly/commodity=corn_cbot/target=production_anomaly_pct/part-000.parquet
```

Observed shape:

```text
184 rows x 479 columns
```

Observed:

- No `label_*` columns are present in the matrix.
- PSD feature columns are present:
  - `psd_available`
  - `psd_ending_stock_su_ratio`
  - `psd_su_ratio_yoy_delta`
- FAOSTAT feature columns are present:
  - `faostat_available`
  - `faostat_production_trend_dev`
  - `faostat_production_yoy`

Interpretation:

- The model-ready matrix properly removes labels from the feature set.
- PSD is already usable as prior balance-sheet feature context.
- FAOSTAT is both the current target source and a prior-history feature source.
  That dual role is technically controlled but strategically confusing.

## Leakage-Control Assessment

### Target Trend Leakage

Observed file:

```text
src/leviathan/model_datasets/baselines.py
```

`build_trailing_anomaly_targets(...)` filters prior history as:

```text
history["crop_year"] < crop_year
```

Therefore, the trend prediction for year `Y` is fit only on years before `Y`.
That is correct for the current annual anomaly target math.

### Walk-Forward CV Leakage

Observed file:

```text
src/leviathan/training/cv.py
```

The function documentation and implementation use:

```text
Train on all rows where crop_year < T.
Predict rows where crop_year == T.
```

That is the correct expanding-window anti-leakage design for annual panels.

### Label Leakage Into Features

Observed files:

```text
src/leviathan/model_datasets/builder.py
src/leviathan/training/model_ready.py
```

Safeguards:

- `builder.py` excludes features starting with `label_` from the target
  matrix feature columns.
- `training/model_ready.py` excludes both model-ready identity columns and any
  feature starting with `label_`.
- The sampled corn model-ready matrix has no `label_*` columns.

### Feature Visibility Controls

Observed file:

```text
src/leviathan/features/visibility.py
```

Important visibility classes:

- `crop_year_direct`: in-season rows within crop-year start/end.
- `prior_history`: rows with `year < crop_year`.
- `prior_marketing_year`: rows where `market_year == crop_year + offset` and
  `release_date <= crop-year start`.

Observed PSD/WASDE feature code:

```text
src/leviathan/features/computations/sd_balance.py
```

PSD features use `prior_marketing_year`, which means the current PSD features
are not same-year final PSD target labels. They are prior balance-sheet context
visible before the crop-year start.

Conclusion:

The current annual target pipeline is technically anti-leakage in trend, CV,
label exclusion, and feature visibility. The main issue is target-source
strategy and metadata clarity, not an obvious same-year target leak.

## Year And Marketing-Year Semantics

Current target rows expose:

```text
crop_year
```

Current FAOSTAT label creation maps FAOSTAT `year` to model `crop_year`:

```text
value = indexed.get((crop_year, variable), np.nan)
```

Current target rows do not expose:

```text
calendar_year
marketing_year
target_market_year
source_year
source_release_date
```

PSD silver exposes:

```text
market_year
release_date
wasde_release_month
```

Implication for Phase 3:

PSD-first targets must not silently reuse only `crop_year`. They should expose
both:

- model observation year or crop year
- PSD target market year

and should document the mapping rule between them.

## PSD Readiness Cross-Check

Observed PSD silver:

```text
s3://leviathan-dev-shahem-001/silver/psd/part-000.parquet
```

Observed PSD shape and coverage:

```text
rows: 163,707
columns: 18
PSD slug count: 29
ALL_COMMODITIES count: 31
country count: 206
market_year range: 1960 to 2026
release_date range: 1960-01-01 to 2027-03-10
```

PSD columns:

```text
leviathan_slug
country
market_year
wasde_release_month
release_date
beginning_stocks_mt
production_mt
imports_mt
exports_mt
ending_stocks_mt
consumption_mt
area_harvested_1000ha
yield_mt_ha
su_ratio
su_ratio_yoy_delta
production_mt_revision
ending_stocks_mt_revision
consumption_mt_revision
```

Leviathan commodities missing from PSD slugs:

```text
cocoa
frozen_orange_juice
```

Interpretation:

- PSD is ready for Phase 2 mapping design for most contracts.
- Phase 2 must produce explicit unmapped/proxy-mapped contract handling.
- Cocoa and FCOJ cannot get PSD-first targets from this PSD silver surface
  unless another PSD mapping exists outside `leviathan_slug` or another target
  source is used.
- Coffee, wheat, palm, meal/oil, and regional contracts may require proxy
  warnings even when a PSD slug exists.

Phase 1 does not solve mapping. It only records that mapping is mandatory.

## Target-Source Truth Table

| target_key | dataset_key | label_column | source | source table/prefix | cadence | current year semantics | built commodities | skipped commodities | leakage risk | recommended status |
|---|---|---|---|---|---|---|---:|---|---|---|
| `production_anomaly_pct` | `annual_physical_anomaly` | `label_production_quantity` | `production:faostat` | `silver/production/` / `silver_production` | annual | FAOSTAT `year` mapped to model `crop_year` | 31 | none | low technical leakage, high strategic/source ambiguity | `legacy_baseline` |
| `yield_anomaly_pct` | `annual_physical_anomaly` | `label_yield` | `production:faostat` | `silver/production/` / `silver_production` | annual | FAOSTAT `year` mapped to model `crop_year` | 26 | `malaysian_crude_palm_oil_cme`, `palm_olein_dce`, `rapeseed_oil_zce`, `soybean_oil_cbot`, `soybean_oil_dce` | low technical leakage, high strategic/source ambiguity | `legacy_baseline` |
| `area_harvested_anomaly_pct` | `annual_physical_anomaly` | `label_area_harvested` | `production:faostat` | `silver/production/` / `silver_production` | annual | FAOSTAT `year` mapped to model `crop_year` | 26 | `malaysian_crude_palm_oil_cme`, `palm_olein_dce`, `rapeseed_oil_zce`, `soybean_oil_cbot`, `soybean_oil_dce` | low technical leakage, high strategic/source ambiguity | `legacy_baseline` |

Leakage risk explanation:

- "Low technical leakage" means current trend/CV/label-exclusion controls look
  sound for an annual supervised benchmark.
- "High strategic/source ambiguity" means the current target names and metadata
  can mislead a futures-linked researcher into thinking these are PSD or
  professional S&D targets.

## Recommended Current-Target Status

Do not delete or disable the current targets in Phase 1.

Recommended future classification:

| target_key | recommended_status | reason |
|---|---|---|
| `production_anomaly_pct` | `legacy_baseline` | Useful as a historical engineering benchmark, but FAOSTAT-derived and not the intended futures-linked PSD target spine. |
| `yield_anomaly_pct` | `legacy_baseline` | Useful agronomic benchmark, but FAOSTAT-derived and missing coverage for several oil/palm contracts. |
| `area_harvested_anomaly_pct` | `legacy_baseline` | Useful harvested-area benchmark, but FAOSTAT-derived and missing coverage for several oil/palm contracts. |

Recommended later handling:

- Keep these loadable for regression and baseline comparison.
- Move definitions to an explicit legacy config or mark them with
  `target_source: faostat` and `status: legacy`.
- Do not make them the default model-ready dataset once PSD-first targets are
  available.

## Metadata Requirements For Later Phases

Phase 3/5 should add these fields to PSD-first target rows and manifests:

```text
target_source
label_source
source_table
source_dataset_key
target_family
target_attribute
target_source_attribute
target_market_year
marketing_year
target_release_context
target_observation_release_date
target_source_vintage
final_value_policy
proxy_scope
mapping_sha
```

For legacy FAOSTAT targets, later phases should at least expose:

```text
target_source = faostat
source_table = silver_production
label_source = production:faostat
target_family = legacy_annual_physical_anomaly
target_attribute = production | yield | area_harvested
status = legacy
```

## Risks And Open Questions

1. The current `annual_physical_anomaly` name hides its FAOSTAT source.
2. Current target rows expose `crop_year` but not source year or release
   context.
3. FAOSTAT release lag is not captured in the target metadata.
4. PSD has 29 slugs versus 31 Leviathan commodities; cocoa and FCOJ need a
   non-PSD or explicitly unmapped target strategy.
5. PSD mappings for split/proxy contracts need careful warnings, especially
   wheat, coffee, palm, and derivative oil/meal contracts.
6. The current model-ready manifest has target config SHA and source gold
   version, but not target-source-specific metadata.
7. Future cleanup should avoid mutating old model-ready artifacts until new
   PSD-first artifacts are validated.

## Phase 1 Acceptance Check

| criterion | status |
|---|---|
| Current targets classified by source | pass |
| Label source traced to code and feature catalog | pass |
| Commodity coverage explains 83 built targets | pass |
| Missing commodities for yield/area identified | pass |
| Target metadata gaps listed | pass |
| Leakage controls documented | pass |
| Year/marketing-year semantics documented | pass |
| PSD readiness and missing PSD slugs documented | pass |
| No config changes made | pass |
| No S3/Glue/Athena/MLflow mutations made | pass |

## Recommended Next Step

Proceed to Phase 2: PSD Mapping Config Design.

Phase 2 should define:

- PSD metric target definitions.
- Contract-to-PSD commodity/country/attribute mappings.
- Direct versus proxy mappings.
- Explicit handling for `cocoa` and `frozen_orange_juice`, which are absent
  from the current PSD `leviathan_slug` set.
- Mapping/config SHA so future model-ready manifests and MLflow runs can prove
  which PSD target mapping produced each experiment.
