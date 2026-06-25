# MLflow Experiment Readiness Plan

Status: Audited rewrite  
Prepared: 2026-06-24  
Scope: Existing Leviathan data, code, S3, Glue/Athena, MLflow, Airflow, and Batch infrastructure  
Primary goal: Make Leviathan ready for reproducible MLflow experimentation using the broad existing `gold/feature_spine`

## 1. Executive Decision

The MLflow training surface should remain the existing broad
`gold/feature_spine` and `gold/feature_matrix`.

`gold_v2` should not replace it in the near term. The useful parts of the v2
work are architectural and governance pieces:

- immutable dataset versions;
- manifests;
- source availability rules;
- source certification reports;
- feature taxonomy;
- model-purpose feature sets;
- feature-policy metadata;
- catalog/entity/group mapping.

Those ideas should be folded around the existing broad gold layer instead of
recomputing all feature ETLs through a new thin v2 builder.

The reason is empirical: live S3 shows that current legacy gold is much broader
than v2.

| Layer | Verified state | Decision |
|---|---:|---|
| `gold/feature_spine` | 31 commodity partitions | Keep as primary feature computation layer |
| `gold/feature_matrix` | 31 commodity partitions, 4,370 total matrix rows | Keep as primary training matrix source |
| Observed matrix feature columns | 2,680 distinct observed columns | Treat as real feature universe to catalog |
| Stored `gold_feature_catalog` | 148 rows, all marked `universal` | Replace with versioned catalog logic |
| `gold_v2` | 8 objects, 3 commodities, 4-7 features per commodity | Keep as proof/future PIT design, not replacement |

The next phase is therefore not "make v2 broad." The next phase is:

```text
Make legacy gold immutable, cataloged, governed, versioned, and MLflow-selectable.
```

## 2. Non-Negotiable Principles

### 2.1 Existing broad gold is the computation layer

The canonical feature computation path remains:

```text
configs/features/features.yaml
src/leviathan/features/computations/
src/leviathan/features/spine.py
jobs/batch/feature_spine_task.py
gold/feature_spine/commodity={commodity}/part-000.parquet
gold/feature_matrix/commodity={commodity}/part-0.parquet
```

New small feature families should be added through that path unless they truly
require multi-snapshot release replay.

### 2.2 v2 is a design source, not the current product

The v2 work remains useful for:

- immutable path conventions;
- dataset manifest shape;
- `feature_available_at` thinking;
- taxonomy and feature-set design;
- catalog/entity/group map design;
- future multi-`as_of_date` replay.

It should not be used as the current MLflow training source because it does not
match legacy feature breadth.

### 2.3 No new ingestion in this readiness phase

Use data already present in S3. Reparsing existing raw files is allowed when the
structured result is missing or defective, but downloading new external data is
out of scope.

### 2.4 GraphRAG is out of scope

Do not touch GraphRAG in this plan. Another workstream owns it.

### 2.5 Fundamental-only modeling policy

The primary track predicts physical fundamentals:

- production anomaly;
- yield anomaly;
- harvested-area anomaly;
- official estimate revision;
- finalization gap;
- physical-flow trajectory;
- stock/use or balance-sheet revision;
- quality/tenderability;
- tail-event probability;
- multivariate physical anomaly score.

It does not predict:

- contract price;
- return;
- calendar spread;
- term structure;
- price-relative mispricing.

Price data may enter only when transformed into a certified economic driver
with a physical mechanism and point-in-time decision lag.

Allowed examples:

- fertilizer and energy costs;
- board crush margin;
- sugar/ethanol allocation economics;
- vegetable-oil substitution premiums;
- FX-driven producer/export incentives;
- producer/internal prices where lagged to planting or investment decisions.

Blocked from core fundamental datasets:

- raw futures prices;
- own-contract returns;
- price momentum;
- calendar spreads;
- term structure;
- COT positioning;
- market volatility regime.

COT and `vol_regime` may be diagnostic-only features for monitoring or slicing,
not core fitting inputs.

## 3. Audited Current State

This section supersedes earlier starting-state claims in this document.

### 3.1 Repository state

The MLflow/gold work is in the `Leviathan-phase1` worktree on branch
`codex/mlflow-readiness-phase2`.

The main `Leviathan` worktree has separate `main`-branch work, including
GraphRAG/causal edits. Do not mix those files into this workstream.

The `Leviathan-phase1` worktree currently contains dirty v2-related scratch
changes. Before implementation continues, useful v2 pieces should be preserved
and the final plan should avoid treating scratch v2 code as production-ready.

### 3.2 S3 and Glue state

Live S3 has the broad gold layer:

- `gold/feature_spine/`;
- `gold/feature_matrix/`;
- `gold/feature_catalog/`;
- `gold/training_windows/`.

Live S3 also has a tiny `gold_v2/` proof:

- one dataset version;
- three commodities;
- eight objects;
- only a handful of features per commodity.

Checked-in Athena DDLs and live Glue are not aligned.

Checked-in DDLs exist for:

- `silver_wasde`;
- `silver_ams_cotton_quality`;
- `gold_v2_feature_spine`;
- `gold_v2_feature_matrix`;
- `gold_v2_dataset_manifests`;
- `gold_v2_feature_catalog`;
- `gold_v2_feature_entity_map`;
- `gold_v2_feature_group_map`.

Live Glue is missing those tables. This is catalog drift. Athena cannot be the
trusted validation surface until the drift is fixed.

### 3.3 Silver state

The important finding is that most of the data is already present in S3. The
main gap is silver-to-gold feature construction and governance, not ingestion.

Present silver prefixes include:

- `silver/ams_cotton_quality/`;
- `silver/conab_coffee/`;
- `silver/cot/`;
- `silver/esr/`;
- `silver/fgis/`;
- `silver/fnc_colombia/`;
- `silver/food_cpi/`;
- `silver/fred_fx/`;
- `silver/futures_prices/`;
- `silver/icco_cocoa/`;
- `silver/mpob/`;
- `silver/mpob_annual/`;
- `silver/mpoc_exports_by_country/`;
- `silver/mpoc_stock_comparison/`;
- `silver/mpoc_trade_stats_monthly/`;
- `silver/nass_annual/`;
- `silver/nass_citrus/`;
- `silver/nass_crop_progress/`;
- `silver/pink_sheet/`;
- `silver/production/`;
- `silver/psd/`;
- `silver/sagis_cec/`;
- `silver/sagis_weekly_deliveries/`;
- `silver/sagis_weekly_exports/`;
- `silver/unica_annual_state/`;
- `silver/unica_biweekly_release_series/`;
- `silver/unica_biweekly_season_history/`;
- `silver/unica_corn_ethanol/`;
- `silver/unica_monthly_ethanol_sales/`;
- `silver/wap_table01/`;
- `silver/wap_table01_revisions/`;
- `silver/wasde/`;
- `silver/weather/`.

High-value silver sources that are present but not fully consumed by gold:

- direct WASDE revision features from `silver/wasde`;
- FCOJ forecast revisions from `silver/nass_citrus`;
- cotton quality/tenderability from `silver/ams_cotton_quality`;
- raw-sugar in-season crush and sugar mix from `silver/unica_*`;
- FNC Colombia monthly coffee features from `silver/fnc_colombia/*`;
- ICCO cocoa balance features from `silver/icco_cocoa`;
- Food CPI policy-risk features from `silver/food_cpi`;
- richer export-pace features across ESR, FGIS, SAGIS, MPOB/MPOC, FNC, UNICA,
  PSD, and WASDE.

### 3.4 Gold state

`gold/feature_spine` is broad and registry-driven.

Current registry families include:

- stage weather and remote sensing;
- FAOSTAT production features and labels;
- PSD stock/use features;
- ONI and IOD;
- Pink Sheet input costs;
- FRED FX;
- COT diagnostics;
- SAGIS weekly and CEC;
- CONAB coffee revisions;
- MPOB fundamentals;
- board crush margin;
- WAP non-US revisions;
- FGIS export pace;
- NASS crop progress;
- ESR exports.

The weak points are:

- outputs are mutable latest paths;
- there is no first-class `dataset_version`;
- the catalog can be overwritten by partial runs;
- scope labels are empirically wrong;
- training reads mutable latest matrices;
- feature sets are era tiers, not model-purpose sets;
- not every existing silver source has a gold feature family;
- point-in-time semantics are coarse annual/crop-year semantics, not full
  historical release replay.

### 3.5 MLflow and Airflow state

MLflow and Airflow run on a single EC2 instance:

```text
Name: leviathan-dev-mlflow-server
Private IP: 172.31.29.109
Instance type: t3.medium
MLflow: port 5000
Airflow: port 8080
```

MLflow uses local SQLite for the backend store and S3 for artifacts:

```text
sqlite:////home/ec2-user/mlflow/mlflow.db
s3://leviathan-dev-shahem-001/mlflow/artifacts/
```

Airflow also uses local SQLite:

```text
sqlite:////home/ec2-user/airflow/airflow.db
```

This is acceptable for development experimentation, but it makes backup,
restore, and Terraform drift protection mandatory before serious sweeps.

### 3.6 Current training path

Training currently reads:

```text
gold/feature_matrix/commodity={commodity}/part-0.parquet
```

Then it:

- resolves features by `configs/features/feature_tiers.yaml`;
- applies `configs/features/feature_policies.yaml`;
- runs walk-forward CV;
- logs metrics and tags to MLflow;
- optionally snapshots the training slice;
- writes predictions to `silver/model_predictions/`.

This is close, but not experiment-ready because the selected data version is
implicit. The run logs a fingerprint after reading the mutable matrix, but the
experimenter cannot intentionally request "dataset version X" yet.

## 4. Target Experiment-Ready State

Leviathan is MLflow experiment-ready when a researcher can:

1. choose a model target;
2. choose a physical entity or contract-facing output;
3. choose an immutable dataset version;
4. choose a reviewed feature set version;
5. launch a training job;
6. compare trials in MLflow;
7. reproduce the exact training matrix later;
8. inspect source fingerprints, feature policies, row counts, and validation
   reports;
9. promote or reject models based on documented metrics and gaps.

Experiment-ready does not mean production-ready.

It means the laboratory is controlled enough that model comparisons are real.

## 5. Data Contracts

### 5.1 Versioned gold contract

Add immutable versions around the existing broad gold outputs:

```text
gold/feature_spine_versions/dataset_version={version}/commodity={commodity}/part-000.parquet
gold/feature_matrix_versions/dataset_version={version}/commodity={commodity}/part-000.parquet
gold/feature_spine_manifests/dataset_version={version}/manifest.json
gold/feature_catalog_versions/dataset_version={version}/feature_catalog.parquet
gold/feature_entity_map_versions/dataset_version={version}/feature_entity_map.parquet
gold/feature_group_map_versions/dataset_version={version}/feature_group_map.parquet
```

Default version format:

```text
YYYYMMDDTHHMMSSZ_{short_git_sha}
```

Rules:

- never overwrite an existing dataset version;
- the mutable latest gold paths may remain for operational compatibility;
- MLflow training must prefer versioned paths;
- old runs must remain reproducible after newer gold builds.

### 5.2 Manifest contract

Each dataset version must publish one manifest containing:

- `dataset_version`;
- build timestamp;
- base Git SHA;
- dirty-worktree flag;
- container image digest when available;
- config SHAs for feature registry, feature params, calendars, geographies,
  dataset registry, feature policies, taxonomy, and feature sets;
- source list;
- source row counts;
- source max dates;
- source object fingerprints;
- source certification statuses;
- waivers;
- commodity list;
- row counts per commodity;
- feature counts per commodity;
- label names;
- label counts;
- validation results;
- feature-policy summary;
- matrix fingerprint;
- catalog fingerprint.

### 5.3 Feature catalog contract

The versioned feature catalog must not infer semantic scope solely from which
commodities happened to be built in a partial run.

Each catalog row should include:

- `dataset_version`;
- `feature`;
- `feature_family`;
- `semantic_scope`;
- `policy`;
- `mechanism`;
- `sources`;
- `groups`;
- `is_label`;
- `entity_count`;
- `commodity_count`;
- `origin_count`;
- `row_count`;
- `non_null_rate`;
- `first_event_time`;
- `last_event_time`;
- `source_cadence`;
- `notes`.

Semantic scope and empirical availability must be separate.

Example:

```text
Brazil coffee frost feature:
  semantic_scope = origin
  empirical availability = only coffee entities
```

It is not "commodity-specific" merely because one run built only coffee.

### 5.4 Feature policy contract

Canonical policy names:

- `fundamental_physical`;
- `certified_economic_driver`;
- `diagnostic_only`;
- `excluded_market_signal`.

The older `allowed_economic_driver` phrase is a legacy alias only. New manifests
and MLflow logs should emit `certified_economic_driver`.

### 5.5 Point-in-time claim boundary

The first experiment-ready versioned legacy gold layer may claim:

```text
This dataset is immutable, fingerprinted, cataloged, policy-governed, and
reproducible for the declared crop-year/as-of convention.
```

It must not yet claim:

```text
This dataset can replay every weekly, monthly, and official-release snapshot
exactly as it appeared historically.
```

Full multi-`as_of_date` historical replay is a future PIT phase. The current
goal is MLflow experiment readiness without throwing away the broad existing
spine.

## 6. Program Phases

### Phase 1: Protect MLflow and Repair Catalog Drift

#### Purpose

Make the experiment platform and Athena validation layer safe enough to trust.

#### Work

- Back up MLflow SQLite and Airflow SQLite through the existing ops scripts.
- Verify restore procedure on a copied backup.
- Ensure Terraform cannot accidentally replace the MLflow/Airflow EC2 instance
  without an explicit recovery plan.
- Register missing Glue tables for checked-in DDLs that correspond to real S3
  outputs:
  - `silver_wasde`;
  - `silver_ams_cotton_quality`.
- Decide whether `gold_v2_*` Glue tables should be registered now as historical
  proof artifacts or removed/deferred from the active registry until v2 returns.
- Regenerate or apply DDLs from `configs/datasets/datasets.yaml`.
- Run Athena smoke queries for live non-GraphRAG tables.

#### Deliverables

- MLflow backup manifest.
- Airflow backup manifest.
- Glue-vs-DDL reconciliation report.
- Updated dataset registry status.
- Athena smoke report.

#### Exit Criteria

- No checked-in active DDL is missing from Glue unless explicitly deferred.
- MLflow/Airflow state is backed up before large experiment sweeps.
- Athena can validate the data this plan depends on.

### Phase 2: Certify Existing Silver Sources

#### Purpose

Confirm which existing silver sources are safe to admit into model-ready gold
features.

#### Work

For each source used or planned for gold features, certify:

- S3 prefix exists;
- Glue table exists where expected;
- row count;
- schema;
- natural key uniqueness;
- date range;
- max source date;
- release/availability date columns;
- duplicate policy;
- known limitations;
- whether the source is admitted, warning-only, deferred, or blocked.

Priority sources:

- FAOSTAT production silver;
- weather silver: CHIRPS, NASA POWER, MODIS NDVI, CPC soil;
- PSD;
- WASDE;
- WAP;
- NASS annual;
- NASS crop progress;
- NASS citrus;
- ESR;
- FGIS;
- SAGIS CEC;
- SAGIS weekly deliveries and exports;
- CONAB coffee;
- FNC Colombia;
- MPOB and MPOC;
- UNICA;
- ICCO cocoa;
- AMS cotton quality;
- Pink Sheet;
- FRED FX;
- futures prices;
- COT;
- Food CPI.

#### Certification Classes

- `pass`: usable in core or certified feature sets.
- `warn`: usable with limitations recorded in the manifest.
- `diagnostic_only`: usable for monitoring/slicing, not core fitting.
- `blocked`: not admitted to model-ready datasets.
- `deferred`: present but not needed for the next MLflow-ready slice.

#### Deliverables

- `source_certification_report.json`.
- Source status summary in the readiness plan.
- Waiver format for known limitations.

#### Exit Criteria

- Every feature family in `configs/features/features.yaml` references a source
  with a certification status.
- New gold dataset versions cannot be published with uncertified sources unless
  the manifest records a waiver.

#### Implementation Status

Phase 2 was implemented on 2026-06-24.

- Certification contracts now live in
  `configs/datasets/source_contracts.yaml`.
- Live certification output:
  `data/system_inventory/source_certification_20260624T214850/source_certification_report.json`.
- Status counts: 27 `warn`, 6 `deferred`, 2 `diagnostic_only`, 0 `blocked`.
- Feature-source coverage: 20 feature-registry sources, 0 missing contracts.
- Warning-only status is expected for this pass because exact duplicate scans
  were skipped and projected/heavy tables such as CHIRPS, NASA POWER, CPC soil,
  and ESR need bounded source-specific validation before immutable gold
  publication.
- See `docs/ops/PHASE2_COMPLETION.md`.

### Phase 3: Preserve and Clean Current v2 Scratch Work

#### Purpose

Keep useful v2 ideas without letting scratch code define the critical path.

#### Work

- Preserve current v2 scratch on a backup branch or commit.
- Classify v2 files into:
  - keep and adapt to legacy gold;
  - keep for future PIT v2;
  - discard or defer.
- Keep/adapt:
  - source availability adapter;
  - taxonomy loader concepts;
  - feature-set selector concepts;
  - catalog/entity/group map concepts;
  - immutable path helper patterns.
- Defer:
  - thin v2 feature builder as production training source;
  - v2 feature matrix as the default MLflow input.

#### Deliverables

- Short preservation note in the plan or commit message.
- Clean worktree before Phase 4 implementation.

#### Exit Criteria

- No ambiguous half-v2 state blocks work on versioned legacy gold.
- Future PIT v2 can be resumed without confusing it with the current MLflow
  readiness path.

#### Implementation Status

Phase 3 was implemented on 2026-06-25.

- v2 scratch was committed and pushed to
  `codex/gold-v2-scratch-preserved`.
- Preservation commit:
  `52934c66 Preserve gold v2 scratch work`.
- File-by-file audit:
  `docs/ops/PHASE3_V2_SCRATCH_AUDIT.md`.
- Completion note:
  `docs/ops/PHASE3_COMPLETION.md`.
- Active `main` keeps `gold/feature_spine` as the MLflow path and does not
  register `gold_v2_*` tables as active MLflow dependencies.
- Reusable ideas are explicitly classified for later adoption: taxonomy,
  feature sets, catalog/entity/group maps, source availability, bounded
  extraction, policy guardrails, and immutable path patterns.

### Phase 4: Version the Broad Legacy Gold Layer

#### Purpose

Make the existing broad gold layer reproducible and selectable by MLflow.

#### Work

- Add storage helpers for:
  - `gold/feature_spine_versions/...`;
  - `gold/feature_matrix_versions/...`;
  - `gold/feature_spine_manifests/...`;
  - `gold/feature_catalog_versions/...`;
  - `gold/training_windows_versions/...`.
- Add Athena DDLs for stable-schema versioned legacy gold tables.
- Extend or wrap `feature_spine_task.py` so it can:
  - build current mutable latest outputs;
  - write immutable versioned copies;
  - refuse overwrites;
  - write one dataset-level manifest;
  - include source certification summaries;
  - include config hashes and source fingerprints.
- Build the versioned matrix only from the matching versioned spine.
- Preserve labels but mark them clearly.
- Validate uniqueness of:

```text
dataset_version, commodity, country, crop_year, feature
```

#### Deliverables

- `gold_feature_spine_versions` DDL.
- Versioned wide matrices under `gold/feature_matrix_versions/...`.
  - These are MLflow/training artifacts, not one stable Athena table, because
    wide feature columns can change by dataset version.
- `gold_feature_spine_manifests` DDL or JSON registry entry.
- `gold_feature_catalog_versions` DDL.
- `gold_training_windows_versions` DDL.
- Versioned S3 outputs for all 31 commodities.
- Manifest for the dataset version.

#### Exit Criteria

- One immutable broad dataset version exists.
- It covers the same 31 commodities as legacy gold.
- Feature counts match or exceed current legacy matrices for the same inputs.
- The mutable latest paths are still readable.
- MLflow can be pointed at the immutable version.

#### Implementation Status

Phase 4 was completed on 2026-06-25.

Published dataset version:

```text
20260625T105545Z_2bd0f32c
```

Live versioned outputs:

- 31 `gold/feature_spine_versions` commodity partitions;
- 31 `gold/feature_matrix_versions` commodity partitions;
- 31 per-commodity manifests;
- one dataset manifest;
- one versioned feature catalog;
- one versioned training-window parquet and markdown summary.

Validation summary:

- 144,346 feature-spine rows;
- 4,370 feature-matrix rows;
- 2,705 feature catalog rows;
- 124 training-window rows;
- 0 hard failures.

Completion record:

```text
docs/ops/PHASE4_COMPLETION.md
```

### Phase 5: Build a Real Feature Taxonomy and Catalog

#### Purpose

Replace the incorrect empirical catalog with a versioned, semantic catalog over
the real feature universe.

#### Work

- Create or adapt `configs/features/feature_taxonomy.yaml`.
- Cover all known emitted feature patterns, including:
  - weather stage features;
  - CHIRPS-derived features;
  - NASA POWER features;
  - GDD;
  - heat stress;
  - drought;
  - frost flags;
  - MODIS NDVI;
  - CPC soil;
  - capacity recovery;
  - FAOSTAT;
  - labels;
  - PSD;
  - WASDE;
  - WAP;
  - ONI;
  - IOD;
  - Pink Sheet;
  - FRED FX;
  - COT;
  - crush margin;
  - vegetable-oil substitution premiums;
  - SAGIS;
  - CONAB;
  - MPOB/MPOC;
  - FGIS;
  - ESR;
  - NASS;
  - NASS citrus;
  - AMS cotton quality;
  - UNICA;
  - FNC;
  - ICCO;
  - Food CPI.
- Build a final single-writer catalog job that reads the complete versioned
  dataset, not one commodity at a time.
- Add feature-to-entity and feature-to-group maps.
- Add group taxonomy:
  - grains;
  - maize complex;
  - wheat complex;
  - oilseeds;
  - soy complex;
  - vegetable oils;
  - palm;
  - coffee;
  - sugar and biofuel;
  - cotton;
  - rice;
  - cocoa;
  - citrus;
  - tree crops;
  - US row crops;
  - South African grains.

#### Deliverables

- `configs/features/feature_taxonomy.yaml`.
- Versioned `feature_catalog`.
- Versioned `feature_entity_map`.
- Versioned `feature_group_map`.
- Tests proving known features do not fall into a vague catch-all category.

#### Exit Criteria

- No observed high-volume feature family is unclassified.
- Scope labels do not change merely because a partial commodity run happened.
- Catalog rows are keyed by `dataset_version`.

### Phase 6: Replace Era Tiers with Model-Purpose Feature Sets

#### Purpose

Let researchers select reviewed feature sets by modeling purpose, not by broad
historical era.

The existing `feature_tiers.yaml` can stay for backward compatibility, but the
MLflow-ready path should use model-purpose sets.

#### Feature Sets

Create `configs/features/feature_sets.yaml` with:

- `preseason_physical`;
- `inseason_weather`;
- `crop_condition`;
- `official_revision`;
- `physical_flow`;
- `balance_sheet`;
- `processing_economics`;
- `planting_incentives`;
- `trade_competitiveness`;
- `tail_risk`;
- `data_quality`;
- `diagnostic_market_context`.

Each feature set declares:

- allowed semantic scopes;
- allowed policies;
- allowed mechanisms;
- blocked policies;
- source families;
- minimum lag;
- target compatibility;
- minimum coverage;
- missingness policy;
- whether labels are excluded;
- feature-set version.

#### Deliverables

- Versioned feature-set config.
- Feature-set selector.
- MLflow tags for `feature_set_id`, `feature_set_version`, and
  `feature_set_sha`.

#### Exit Criteria

- Training can select feature sets by config.
- Core feature sets reject `diagnostic_only` and `excluded_market_signal`
  features.
- Economic-driver feature sets include only certified features.

### Phase 7: Add High-Value Existing-Silver Feature Families to Gold

#### Purpose

Close obvious value gaps using silver data that already exists, without new
ingestion or large architecture work.

#### Add First

These are high-value and should be modest engineering work because silver is
already present:

- WASDE direct revision features:
  - `wasde_latest_revision`;
  - `wasde_consecutive_revision_count`;
  - component-specific production/stocks/use revisions where schema supports.
- NASS citrus features for FCOJ:
  - forecast revision;
  - prior-month forecast change;
  - finalization gap where available.
- AMS cotton quality:
  - `ams_percent_tenderable`;
  - cotton quality flags where sample size supports.
- UNICA raw sugar:
  - sugar mix;
  - cane crush pace;
  - ATR or sugar output pace where source supports.
- FNC Colombia:
  - production pace;
  - export pace;
  - internal/ex-dock price as certified economic driver only where lagged and
    documented.
- ICCO cocoa:
  - grindings trend deviation;
  - stock/use or surplus/deficit context.
- Food CPI:
  - policy-risk z-score features for countries where food-security intervention
    risk matters.
- Vegetable-oil substitution:
  - `veg_oil_soy_palm_premium_z`;
  - `veg_oil_soy_palm_ratio_z`;
  - `veg_oil_rape_palm_premium_z`.

#### Add Carefully

- Richer export-pace features from ESR, FGIS, SAGIS weekly exports, MPOB/MPOC,
  FNC, UNICA, PSD, and WASDE.
- In-season latest NASS crop progress features only for datasets whose target
  has an explicit as-of date.

#### Do Not Add Now

- new external data;
- livestock margins;
- futures calendar spreads;
- term structure;
- price momentum;
- intraday price features;
- GraphRAG-derived features.

#### Deliverables

- Feature registry additions.
- Extractor additions where needed.
- Computation functions.
- Unit tests per feature family.
- Updated taxonomy and feature-set mapping.

#### Exit Criteria

- New features are visible in versioned gold.
- New features have policy metadata.
- New features do not leak future information under the declared as-of rule.

### Phase 8: Build Model-Ready Targets and Datasets

#### Purpose

Move from one overloaded annual matrix to explicit model-ready datasets.

#### Target Families

Required target families:

- official next-release revision;
- official finalization gap;
- yield anomaly versus trailing expectation;
- harvested-area anomaly versus trailing expectation;
- production anomaly versus trailing expectation;
- end-season physical-flow total;
- balance-sheet component revision;
- ending-stock or stock/use revision;
- quality/tenderability event;
- tail-event label;
- multivariate anomaly score.

Final production levels are still useful as labels and reconciliation anchors,
but the primary research target should usually be the residual/anomaly or
revision, not the deterministic production level.

#### Dataset Grains

Create distinct model-ready datasets rather than forcing every model through one
annual matrix:

```text
annual_physical_anomaly:
  physical_commodity x origin x crop_year x as_of_stage

official_revision:
  source x commodity x geography x marketing_year x release_date

weekly_or_fortnightly_trajectory:
  source x commodity x geography x season x observation_date

balance_sheet_revision:
  commodity x geography x marketing_year x release_date x balance_component

quality_event:
  commodity x origin x season x report_date

anomaly_detection_panel:
  entity x observation_date x feature_set
```

#### Baselines

Every supervised dataset must include baseline predictions:

- no-change from current official estimate;
- prior release unchanged;
- prior-year final value;
- trailing mean;
- trailing linear trend;
- seasonal analogue;
- cumulative pace extrapolation for flow datasets.

#### Deliverables

- Target dictionary.
- Dataset builders.
- Dataset manifests.
- Baseline outputs.
- MLflow-ready dataset registry entries.

#### Exit Criteria

- Each dataset has one clear target, horizon, grain, and as-of rule.
- Baselines are materialized, not computed informally in notebooks.
- Datasets can be selected by `dataset_version`.

### Phase 9: Upgrade MLflow Training

#### Purpose

Make MLflow runs reproducible, comparable, and artifact-complete.

#### Work

- Add `--dataset-version` to training jobs.
- Read `gold/feature_matrix_versions/...` by default.
- Support `--feature-set-id` and `--feature-set-version`.
- Keep `--tier` only as backward compatibility.
- Log:
  - dataset version;
  - dataset manifest URI;
  - dataset fingerprint;
  - feature-set SHA;
  - feature policy summary;
  - target definition;
  - training window;
  - model class;
  - hyperparameters;
  - Optuna trial history;
  - CV metrics;
  - slice metrics;
  - baseline comparison;
  - fitted model artifact.
- Store training snapshots under a run-specific immutable path.
- Write predictions to `silver/model_predictions/`.
- Add `silver/model_explanations/` and `silver/model_dependencies/` in a later
  production-readiness phase; do not block experiment readiness on frontend
  chart outputs.

#### Deliverables

- Updated training CLI.
- Updated Batch job definition.
- MLflow artifact logging.
- Fitted model logging.
- Optuna trial logging.
- Baseline comparison logging.

#### Exit Criteria

- A run can be reproduced from MLflow tags and artifacts.
- A fitted model artifact is logged.
- Runs with different dataset or feature-set versions are not ranked as direct
  substitutes unless explicitly compared.

### Phase 10: Orchestration and Readiness Certification

#### Purpose

Make the experiment lifecycle repeatable.

#### Work

- Add or update Airflow DAGs for:
  - source certification;
  - versioned gold build;
  - feature catalog build;
  - training-window build;
  - selected experiment sweeps.
- Keep all DAGs paused until manually enabled.
- Add a readiness certification script that checks:
  - Glue/DDL sync;
  - S3 prefixes exist;
  - source certifications pass or have waivers;
  - versioned gold exists;
  - catalog exists;
  - feature sets validate;
  - MLflow backup exists;
  - one smoke training run succeeds.

#### Deliverables

- Airflow DAGs.
- Readiness certification report.
- Smoke training run.

#### Exit Criteria

- The project can run a controlled MLflow experiment from a versioned dataset
  without manual S3 spelunking.

## 7. Recommended Execution Order

The shortest safe path is:

1. Protect MLflow and Airflow state.
2. Fix Glue/DDL drift for live silver tables.
3. Preserve and clean v2 scratch.
4. Certify existing silver sources.
5. Add versioned legacy-gold registry entries and DDLs.
6. Build one immutable broad gold dataset version.
7. Build versioned catalog/entity/group maps.
8. Add model-purpose feature sets.
9. Add the small high-value existing-silver feature families.
10. Build model-ready target datasets and baselines.
11. Upgrade training to select `dataset_version` and feature-set version.
12. Run one smoke MLflow experiment.
13. Certify readiness.

Parallel work is safe where outputs do not overlap:

- Glue reconciliation can proceed alongside source certification.
- Feature taxonomy can proceed alongside versioned path implementation.
- Training CLI changes can be developed against fixtures before versioned gold
  is written.
- New feature families can be added after the first versioned-gold plumbing is
  proven.

Do not run broad experiment sweeps until versioned gold and the catalog are
published.

## 8. Risks and Mitigations

| Risk | Mitigation |
|---|---|
| v2 work distracts from broad feature readiness | Treat v2 as future PIT design; fold useful pieces into legacy gold |
| Mutable latest gold changes historical experiment results | Train from immutable dataset versions |
| Current catalog lies about universal features | Replace with versioned semantic catalog and single-writer build |
| Checked-in DDLs drift from Glue | Add Glue/DDL certification to Phase 1 |
| MLflow EC2 replacement destroys SQLite state | Backup and restore before Terraform changes |
| Hundreds of weather features overfit annual labels | Add feature sets, coverage gates, dimensionality reduction, and baselines |
| Final production levels are too deterministic | Prefer anomaly, revision, finalization-gap, flow, and tail targets |
| Economic-driver price features leak market shortcuts | Enforce policy classes and target eligibility |
| Short-history sources look more reliable than they are | Surface source history and confidence in manifests and MLflow tags |
| Partial rebuild overwrites global catalog | Single-writer catalog keyed by dataset version |

## 9. Definition of Done

The readiness plan is complete when:

- MLflow and Airflow backend stores are backed up.
- Glue and checked-in DDLs are reconciled for active non-GraphRAG datasets.
- A source certification report exists.
- One immutable broad `gold/feature_spine_versions` dataset exists for all 31
  commodities.
- The matching immutable feature matrix exists.
- A dataset manifest exists.
- A versioned feature catalog exists.
- Feature/entity/group maps exist.
- Feature sets are versioned and policy-governed.
- Training can select `dataset_version` and feature-set version.
- At least one smoke MLflow run logs:
  - fitted model artifact;
  - dataset version;
  - feature-set SHA;
  - metrics;
  - baseline comparison;
  - training snapshot.

## 10. Future PIT v2 Boundary

Full PIT v2 should be restarted only after the legacy-gold MLflow path is
experiment-ready.

The future PIT layer should solve a different problem:

```text
multiple historical as-of snapshots per entity, release, week, or month
```

It should not be justified merely as "cleaner gold." The legacy gold path can
already serve annual crop-year experiments once versioned and governed.

Future PIT v2 should reuse:

- the broad legacy feature registry;
- versioned manifest format;
- source certification report;
- feature taxonomy;
- model-purpose feature sets;
- availability adapter;
- MLflow dataset-version selection.

It should not start from a small hand-picked feature subset.

## 11. Recommended Model Portfolio

This section is not part of the remediation phases. It describes the research
portfolio to investigate after the platform is experiment-ready.

### 11.1 Official Next-Release Revision Models

Research question:

```text
Given all information available before the next official release, will the
estimate revise up or down, and by how much?
```

Targets:

- next estimate minus current estimate;
- revision direction;
- probability of a material revision.

Useful data:

- WASDE;
- WAP;
- SAGIS CEC;
- NASS citrus;
- CONAB;
- crop progress;
- weather and remote sensing;
- ESR and FGIS.

Candidate models:

- no-change baseline;
- regularized linear model;
- XGBoost or LightGBM;
- hierarchical partial-pooling model where histories are sparse.

### 11.2 Yield and Area Anomaly Models

Research question:

```text
How far will yield or harvested area deviate from a trailing expectation?
```

Targets:

- yield anomaly;
- harvested-area anomaly;
- production anomaly decomposed into area and yield.

Useful data:

- stage weather;
- drought and heat stress;
- crop progress;
- NASS annual;
- FAOSTAT;
- ONI/IOD;
- fertilizer and energy drivers;
- planting-incentive features where certified.

Candidate models:

- trailing-trend baseline;
- Ridge or Elastic Net;
- XGBoost or LightGBM;
- quantile boosted trees for uncertainty.

### 11.3 Physical Flow Trajectory Models

Research question:

```text
Given current shipment, sales, delivery, or crush pace, where will the season
finish?
```

Targets:

- end-season export total;
- end-season delivery total;
- end-season crush or production total;
- current official flow assumption minus model-implied final flow.

Useful data:

- ESR;
- FGIS;
- SAGIS weekly;
- MPOB/MPOC;
- FNC;
- UNICA;
- PSD/WASDE balance assumptions.

Candidate models:

- cumulative pace extrapolation;
- same-week historical analogue;
- gradient-boosted model;
- sequence model only where enough weekly/monthly history exists.

### 11.4 Balance-Sheet Revision Models

Research question:

```text
Which balance-sheet components are most likely to revise, and does the implied
stock/use ratio move materially?
```

Targets:

- production revision;
- consumption/use revision;
- export revision;
- ending-stocks revision;
- stock/use revision.

Useful data:

- WASDE;
- PSD;
- WAP;
- flows;
- crop progress;
- weather;
- certified economic drivers.

Candidate models:

- component no-change baseline;
- constrained component regression;
- XGBoost/LightGBM component models;
- reconciliation layer that enforces balance-sheet arithmetic.

### 11.5 Quality and Tenderability Models

Research question:

```text
Is usable/tenderable supply materially different from headline production?
```

Targets:

- percent tenderable;
- quality threshold event;
- quality-adjusted supply anomaly.

Useful data:

- AMS cotton quality;
- weather;
- crop progress;
- production estimates;
- historical quality reports.

Candidate models:

- threshold baseline;
- logistic classifier;
- boosted classifier;
- calibrated probability model.

### 11.6 Tail-Event Classifiers

Research question:

```text
Is the current season entering a materially adverse tail?
```

Targets:

- yield anomaly below threshold;
- downward official revision above threshold;
- crop condition below historical percentile;
- export pace materially below balance assumption;
- tenderable share below threshold;
- simultaneous multi-origin stress.

Useful data:

- weather and remote sensing;
- crop progress;
- official revisions;
- physical flows;
- AMS cotton;
- climate indices;
- certified economic drivers where mechanism supports the target.

Candidate models:

- penalized logistic regression;
- calibrated boosted classifier;
- conformal risk set;
- simple rule ensemble as baseline.

### 11.7 Multivariate Physical Anomaly Detectors

Research question:

```text
Is the current feature combination outside the historical physical manifold?
```

Outputs:

- anomaly score;
- historical percentile;
- contributing feature deviations;
- nearest historical analogues;
- data-quality anomaly flag.

Useful data:

- weather;
- remote sensing;
- crop progress;
- physical flows;
- official revisions;
- stocks and crush;
- quality measures.

Candidate models:

- robust covariance distance;
- Isolation Forest;
- one-class model;
- autoencoder only for large enough weekly/monthly panels.

### 11.8 Source Reliability and Estimate Combination

Research question:

```text
When official and physical sources disagree, which source should receive more
weight at this stage of the season?
```

Outputs:

- combined estimate;
- source weights;
- disagreement score;
- confidence interval.

Useful data:

- current source estimates;
- historical source errors;
- source revision volatility;
- source freshness;
- source availability;
- weather and progress context.

Candidate models:

- inverse historical-error weighting;
- dynamic model averaging;
- Bayesian combination;
- stacked out-of-fold meta-model after upstream models have enough history.

### 11.9 Hierarchical Physical-Commodity Models

Research question:

```text
Can shared biological and balance-sheet structure improve sparse commodity
models without pretending every futures contract is an independent crop?
```

Structure:

```text
global mechanism
  -> physical commodity
    -> origin
      -> crop class or processed product
        -> contract-facing output
```

Candidate models:

- mixed-effects regression;
- hierarchical Bayesian model;
- shared boosted model with entity indicators;
- multi-task model only after simpler baselines are beaten.

### 11.10 Fundamental Relative-Stress Engine

Research question:

```text
Which related physical commodity, origin, or processed product is more
fundamentally stressed?
```

Inputs:

- upstream revision forecasts;
- yield and area anomaly forecasts;
- physical-flow trajectory forecasts;
- stock/use surprise forecasts;
- tail-event probabilities;
- certified substitution-premium features.

Outputs:

- relative physical stress differential;
- confidence in the asymmetry;
- upstream dependency trace;
- component contribution breakdown.

This is not a price-spread model. It is a contract-relevant research layer built
from physical fundamentals.
