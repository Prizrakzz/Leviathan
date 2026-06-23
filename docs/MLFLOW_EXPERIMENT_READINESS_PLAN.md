# MLflow Experiment Readiness Remediation Plan

Status: Proposed  
Prepared: 2026-06-23  
Scope: Existing Leviathan data and infrastructure only  
Primary goal: Make the platform trustworthy and reproducible for MLflow model experimentation

## 1. Objective

Leviathan should reach a state where a researcher can select a valid target,
select a versioned point-in-time feature set, launch an experiment, compare it
with appropriate baselines, and reproduce every result from immutable data and
configuration.

Experiment-ready means more than "the training script runs." It means:

1. Every training value has a defined business meaning, unit, grain, source,
   and first-knowable timestamp.
2. Every feature is available at the declared forecast as-of date.
3. Every target is appropriate for the physical commodity being modeled.
4. Source revisions, forecasts, flows, and final values are distinguishable.
5. Contract aliases do not create fake independent learning problems.
6. The exact training dataset can be reconstructed and compared across runs.
7. MLflow stores parameters, data lineage, evaluation results, and a fitted
   model artifact.
8. Infrastructure changes cannot silently destroy experiment history.
9. Athena and checked-in DDLs describe the data that actually exists in S3.
10. Price data enters the fundamental track only when it represents a
    point-in-time economic mechanism that changes physical supply, demand,
    processing, storage, trade, or acreage decisions. Price forecasting,
    technical signals, and price-relative mispricing remain out of scope.

The completion of this plan does not imply that any model is production-ready.
It creates the controlled laboratory required to determine which models deserve
promotion later.

## 2. Hard Constraints

### 2.1 Data scope

- Use only data already present in S3.
- New transformations over existing raw, bronze, silver, and gold data are in
  scope.
- Downloading or purchasing new external datasets is out of scope.
- Existing raw documents may be reparsed when the current structured result is
  missing or defective.

### 2.2 Fundamental-only policy

The primary experiment track predicts physical fundamentals, official
revisions, physical flows, quality, or supply-and-demand balances. It does not
predict contract prices, returns, spreads, or mispricing.

Price data is allowed when it is transformed into a point-in-time economic
driver with a documented causal mechanism affecting physical fundamentals.
The governing distinction is the role of the variable, not whether its source
is a futures exchange or a cash-market series.

Allowed economic-transmission examples:

- Board crush margin derived from soybean, soybean-meal, and soybean-oil prices:
  processor profitability changes soybean crush demand and meal/oil output.
- Sugar-versus-ethanol parity: mill allocation economics change sugar output
  and ethanol output from the same cane crop.
- Fertilizer and energy input costs: expected margins affect planted area,
  application rates, drying, processing, and freight.
- Producer or internal prices, when lagged to the planting or investment
  decision window: expected returns can affect acreage, replanting, and crop
  maintenance.
- Exchange rates: producer selling incentives, export pace, input affordability,
  and crop-switching economics.
- Freight or fuel-cost proxies: trade-flow competitiveness and processing costs.
- Product-versus-feedstock margins for oilseeds, sugar, ethanol, or other
  processing chains.

Excluded uses:

- Contract price, return, or spread as a prediction target.
- Price momentum, moving averages, breakouts, technical indicators, or chart
  patterns.
- Price-relative fair-value or mispricing models.
- Calendar spreads or term structure.
- Contemporaneous own-contract prices used as a shortcut for information already
  embedded in the market, unless the experiment specifically studies a
  pre-decision physical response and uses a strictly lagged incentive window.
- CFTC positioning.
- Any price feature whose availability timestamp, economic mechanism, and
  decision lag are undefined.

Every allowed price-derived feature must declare:

- `economic_mechanism`
- `affected_balance_component`
- `decision_window`
- `minimum_lag`
- `source_series`
- `unit_conversion`
- `feature_available_at`
- `eligible_targets`
- `prohibited_targets`

For example, a crush-margin feature may be eligible for soybean crush,
soybean-meal production, soybean-oil production, or ending-stock models. It is
not automatically eligible for predicting the soybean futures price.

Other allowed core inputs include:

- Weather and remote sensing.
- Crop progress and crop condition.
- Official production, area, and yield estimates.
- Official estimate revisions.
- Physical exports, deliveries, crush, stocks, consumption, and trade flows.
- Physical quality and tenderability statistics.
- Climate indices such as ONI and IOD.
- Source availability and data-quality indicators.
- Certified economic-transmission features that satisfy the mechanism and
  point-in-time requirements above.

### 2.3 Operational scope

- Batch experimentation remains the training execution method.
- MLflow remains the experiment tracking and model artifact system.
- Airflow remains the scheduled orchestration surface.
- Athena remains the SQL inspection and validation surface.
- This plan does not require real-time endpoints.
- This plan does not require SageMaker Feature Store or SageMaker endpoints.

## 3. Verified Starting State

The following observations were verified against the live repository and AWS
environment on 2026-06-23.

| Area | Verified state | Consequence |
|---|---|---|
| S3 lake | 2,032,475 objects, approximately 34.63 GB | The lake is substantial; manual object-by-object inspection is impractical without inventory metadata |
| S3 inventory | No S3 Inventory configuration | No cheap, durable whole-bucket audit or daily object manifest |
| S3 versioning | Suspended | Experiment inputs and MLflow bootstrap state have weak recovery protection |
| Gold matrices | 31 commodity matrices | The current training surface covers all configured contracts |
| Empirical feature universe | 2,680 observed feature columns | The real taxonomy is much larger than the stored catalog |
| Empirical scope | 9 universal, 113 shared, 2,558 commodity-specific | The stored feature scope is materially wrong |
| Stored feature catalog | 148 rows, all marked universal | A single-commodity run overwrote the global catalog |
| Crop calendars | 11 of 31 contracts | Twenty contracts have no stage-aware crop calendar |
| Contract targets | 31 contracts map to 13 FAOSTAT items | Many contract models currently share identical physical labels |
| PSD silver | 163,707 rows; all revision columns null | PSD cannot currently train a revision model |
| WASDE bronze | Approximately 473 non-empty releases and 943,000 rows | Existing data can support real release-vintage modeling after normalization |
| CONAB silver | All later survey production values equal the first survey | Current revision fields contain no usable information |
| NASS annual | 14,631 rows across 593 partitions | Strong US final annual source is available |
| NASS crop progress | 141,714 rows across 279 partitions | Rich weekly in-season state data is available but compressed to one annual mean in gold |
| NASS citrus | 2,450 rows, 967 nonzero revisions | Strong FCOJ revision data exists but is absent from gold |
| SAGIS CEC | 2,071 rows, 1,592 nonzero revisions | Strong South African revision data exists |
| SAGIS weekly | 2,668 delivery rows and 1,204 export rows | Physical trajectory data exists |
| FNC monthly | 1,360 rows from 1913 through 2026 | Long coffee production and export history exists |
| UNICA | Annual and fortnightly physical crush, sugar, and ethanol tables exist | Strong raw-sugar in-season features exist but are absent from gold |
| MPOB | 113 monthly rows from 2016-12 through 2026-04 | Palm physical balance data exists |
| ICCO | 15 annual cocoa balance rows | Useful balance context exists, but supervised sample size is small |
| AMS cotton | 27 annual quality PDFs; no bronze or silver | Existing raw files contain Percent Tenderable and quality distributions |
| Athena/Glue | 40 live tables versus 41 checked-in DDLs | Catalog drift prevents Athena from serving as a reliable validation surface |
| MLflow | MLflow 3.1.4, two experiments, one completed run | Experiment tracking is live but barely exercised |
| MLflow models | Zero registered models and no logged fitted model artifact | The train-to-model loop is open |
| Airflow | Seven ingestion DAGs, all paused | No scheduled experiment, retraining, inference, or drift workflow |
| Terraform | A plan would replace the MLflow EC2 instance and security group | A normal apply can destroy the SQLite-backed experiment history |
| MLflow storage | SQLite on a 10 GB delete-on-termination root volume | The experiment system has a single point of failure |
| SageMaker registry/store | No feature groups, model packages, models, or endpoints | Desired-state references to these services are aspirational, not live |

## 4. Goal-State Contract

The platform is MLflow experiment-ready only when all of the following
contracts are satisfied.

### 4.1 Data contract

Every model-ready dataset must publish:

- `dataset_id`
- `dataset_version`
- `entity_type`
- `entity_id`
- `physical_commodity`
- `contract_slug` when applicable
- `origin`
- `target_name`
- `target_horizon`
- `observation_date`
- `as_of_date`
- `release_date`
- `event_time`
- `target_value`
- `target_unit`
- `is_final`
- `source`
- `source_vintage`
- `input_fingerprint`
- `code_git_sha`
- `config_sha`

### 4.2 Point-in-time contract

For every feature value:

```text
feature_available_at <= row_as_of_date
```

No feature may be stamped with crop-year start merely because it belongs to
that crop year. Weather, crop progress, surveys, exports, and official
revisions become visible when their observation or release is available.

### 4.3 Modeling-entity contract

Physical commodities, processed products, origins, and exchange contracts must
be represented separately.

Example:

```text
physical crop: soybeans
processed products: soybean meal, soybean oil
contracts: soybeans_cbot, soybean_meal_cbot, soybean_meal_dce, ...
origins: united_states, brazil, argentina, china
```

A contract may consume a physical-model output. It must not automatically own
an independent copy of a physically identical target.

### 4.4 Experiment contract

Every MLflow run must include:

- Experiment purpose.
- Target definition.
- Forecast horizon.
- As-of policy.
- Physical commodity and entity.
- Feature-set ID and SHA.
- Dataset ID, version, and content fingerprint.
- Source-vintage summary.
- Code Git SHA and dirty-worktree flag.
- Image digest, not only an image tag.
- Full estimator parameters.
- Full tuning-trial history or a linked artifact.
- Baseline metrics.
- Walk-forward and final holdout metrics.
- Slice and tail metrics.
- Prediction artifact.
- Fitted model artifact.
- Feature importance or explanation artifact when supported.
- Validation-gate outcomes.

### 4.5 Recovery contract

- MLflow backend state must survive instance replacement.
- MLflow artifact paths must be versioned and backed up.
- Terraform must be reconcilable without destroying unexported run history.
- Training must use immutable image digests or immutable release tags.

## 5. Program Sequencing

The phases below are intentionally gated.

```text
Phase 0: Protect current state
    |
Phase 1: Establish inventory and catalog truth
    |
Phase 2: Repair source-specific structured data
    |
Phase 3: Define physical entities and target semantics
    |
Phase 4: Build point-in-time gold v2
    |
Phase 5: Build feature taxonomy and model-purpose feature sets
    |
Phase 6: Build model-ready labels and datasets
    |
Phase 7: Add data-quality and leakage certification
    |
Phase 8: Make MLflow experimentation complete and reproducible
    |
Phase 9: Reconcile infrastructure and orchestration
    |
Phase 10: Certify experiment readiness
```

No phase should be bypassed by directly launching a large experiment sweep.

## Phase 0: Protect Current State and Freeze the Baseline

Status: Completed on 2026-06-23. See
`docs/ops/PHASE0_COMPLETION.md` for the live evidence and remaining safeguards.

### Purpose

Prevent loss of experiment history and create a stable baseline against which
all remediation work can be measured.

### Workstreams

#### 0.1 Preserve MLflow and Airflow state

- Stop treating the EC2 root volume as the only durable copy of:
  - `/home/ec2-user/mlflow/mlflow.db`
  - `/home/ec2-user/airflow/airflow.db`
- Create versioned backups under:

```text
mlflow/backups/backend/YYYY-MM-DDTHH-MM-SSZ/mlflow.db
airflow/backups/backend/YYYY-MM-DDTHH-MM-SSZ/airflow.db
```

- Record checksums and SQLite integrity-check results.
- Add a restore script that:
  - verifies the checksum;
  - restores the database;
  - fixes ownership;
  - restarts the service;
  - verifies the health endpoint.

#### 0.2 Reconcile Terraform state before any apply

- Import or refresh the manually changed `t3.medium` instance state.
- Prevent the next apply from replacing the instance solely because the latest
  AMI changed.
- Separate mutable service configuration from instance replacement triggers.
- Decide whether the current instance is adopted or replaced through a planned
  migration.
- Do not apply the currently observed replacement plan.
- Add lifecycle safeguards until migration is complete:
  - `prevent_destroy` on the MLflow instance or durable backend volume;
  - explicit backup precondition;
  - documented migration approval.

#### 0.3 Snapshot the current lake and catalog state

- Generate a one-time logical inventory for:
  - raw source prefixes;
  - bronze source prefixes;
  - silver dataset prefixes;
  - gold datasets;
  - Athena/Glue tables;
  - ECR images;
  - Batch job-definition revisions.
- Save the inventory as timestamped JSON and Parquet under:

```text
metadata/system_inventory/as_of_date=YYYY-MM-DD/
```

#### 0.4 Preserve the current experimental baseline

- Export the existing corn run metadata, predictions, metrics, and training
  snapshot into a read-only baseline record.
- Record that the run:
  - used a production-level target;
  - used 279 features;
  - failed hard governance gaps;
  - did not log a fitted model artifact;
  - had unknown spine Git SHA.

### Deliverables

- MLflow backup and restore scripts.
- Airflow backup and restore scripts.
- Terraform reconciliation note.
- Timestamped system inventory.
- Frozen baseline experiment record.

### Tests

- `PRAGMA integrity_check` returns `ok` for both SQLite databases.
- Restore into a temporary location and query experiments successfully.
- Terraform plan does not unexpectedly destroy the active backend.
- Inventory generation is repeatable and deterministic.

### Exit criteria

- Experiment history can be recovered after EC2 replacement.
- No planned infrastructure operation can silently erase MLflow state.
- The current state is captured well enough to compare later phases.

## Phase 1: Establish S3, Athena, and Schema Truth

### Purpose

Make the physical lake and query catalog agree, and provide a durable inventory
for future audits.

### Workstreams

#### 1.1 Enable S3 Inventory

- Add daily or weekly S3 Inventory for the data-lake bucket.
- Include:
  - key;
  - size;
  - ETag;
  - last modified;
  - storage class;
  - encryption status;
  - replication status when applicable.
- Write inventory to a dedicated prefix outside raw/bronze/silver/gold.
- Register the inventory manifest in Athena.

#### 1.2 Define one authoritative dataset registry

Create a checked-in dataset registry containing:

- Dataset name.
- Layer.
- S3 prefix.
- Natural grain.
- Partition keys.
- Owning transform.
- Athena table.
- Expected schema.
- Primary timestamp fields.
- Expected freshness.
- Expected historical range.
- Whether it is allowed in core fundamental features.
- Whether it is a label, feature source, narrative source, or diagnostic source.

The registry should drive DDL generation and validation instead of scanning an
arbitrary first Parquet file.

#### 1.3 Repair Athena/Glue drift

Explicitly resolve:

- Remove or quarantine legacy `production_raw`, which points to an unrelated
  bucket.
- Recreate `silver_production` from its actual current Parquet schema and
  prefix.
- Recreate weather tables so each source has an accurate schema:
  - NASA POWER;
  - CHIRPS;
  - CPC soil;
  - MODIS NDVI;
  - NOAA ONI;
  - NOAA IOD.
- Split the FNC root into three Athena tables matching its three grains:
  - monthly;
  - area by department;
  - exports by port and type.
- Register the missing ESR and UNICA annual tables.
- Reconcile generated DDLs with live partition projection settings.
- Remove stale table definitions that claim schemas no current Parquet file
  follows.

#### 1.4 Add automated DDL validation

For every registered dataset:

- Compare Glue schema with Parquet schema.
- Compare Glue location with registry location.
- Validate projected partition values against actual path conventions.
- Run a bounded Athena query.
- Check that mixed-schema prefixes are not registered as one table.
- Fail CI or the catalog-deployment job on mismatch.

### Deliverables

- S3 Inventory configuration and Athena table.
- Dataset registry.
- Corrected Athena DDLs.
- Catalog deployment command.
- Catalog drift validator.
- Catalog reconciliation report.

### Tests

- Every registered table can read at least one expected row.
- No table points outside the Leviathan bucket unless explicitly approved.
- No table scans a prefix containing incompatible Parquet schemas.
- Repo DDL count and live table count reconcile.
- Schema validator returns zero blocking mismatches.

### Exit criteria

- Athena is trustworthy for source inspection and experiment validation.
- A researcher can discover every model-relevant dataset through one registry.
- Whole-lake inventory no longer requires paginating two million live objects.

## Phase 2: Repair and Certify Source-Specific Structured Data

### Purpose

Convert the high-value data already present in S3 into clean, revision-aware,
model-ready silver datasets.

### 2A. Normalize the WASDE release archive

#### Problem

The existing WASDE bronze archive is rich but contains parser noise in table,
region, and attribute values. The current PSD silver is a bulk snapshot and
cannot recreate historical monthly revision paths.

#### Required work

- Build a dedicated `silver_wasde` transform from existing WASDE bronze.
- Retain the release grain:

```text
release_date
commodity
table_type
region
marketing_year
attribute
unit
estimate
```

- Add strict allowlists for:
  - supported commodity tables;
  - attributes;
  - geographic aggregates;
  - units.
- Map known table aliases across report eras.
- Reject parser artifacts such as truncated attributes or column placeholders.
- Preserve raw descriptor columns for audit.
- Add:
  - `prior_release_date`;
  - `prior_estimate`;
  - `revision`;
  - `revision_direction`;
  - `months_to_marketing_year_end`;
  - `is_first_estimate`;
  - `is_final_or_latest`.
- Keep source releases immutable.
- Write release-partitioned Parquet to a non-overlapping prefix.

#### Validation

- Compare selected historical releases with known report tables.
- Verify revision arithmetic for corn, wheat, soybeans, meal, oil, cotton, and
  rice.
- Require plausible units and ranges.
- Require one estimate per natural key per release.
- Report retained and rejected row counts by report era.

#### Acceptance criteria

- Decades of nonzero revisions are available.
- No placeholder attributes remain in accepted silver.
- Revision calculations are reproducible from adjacent releases.
- A release available at date T can be reconstructed without later releases.

### 2B. Repair CONAB survey identity and revisions

#### Problem

Different CONAB survey partitions currently yield identical values. This
eliminates the revision signal and suggests incorrect file-to-survey parsing or
selection.

#### Required work

- Trace every silver partition back to:
  - raw S3 key;
  - file ETag;
  - safra year;
  - survey number;
  - worksheet;
  - parser version.
- Confirm that each raw file is distinct and that the parser reads the intended
  current-survey columns.
- Add a survey-content fingerprint.
- Add a validation rule:

```text
if survey_number changes and the entire accepted table is identical,
mark the partition suspicious and block silver publication
```

- Recompute:
  - production revision;
  - area revision;
  - yield revision;
  - revision streak;
  - revision percentage.
- Preserve both national and state/region rows.

#### Acceptance criteria

- Survey tables differ where the official files differ.
- Nonzero revisions appear for historical surveys.
- Identical-survey validation produces no unexplained pass.
- Every value can be traced to a raw file and worksheet.

### 2C. Build AMS cotton quality bronze and silver

#### Problem

Existing raw annual PDFs contain numeric cotton-quality information, including
`Percent Tenderable`, but no structured bronze or silver exists.

#### Required work

- Parse the 27 existing annual-quality PDFs.
- Extract at minimum:
  - crop season;
  - geography;
  - percent tenderable;
  - average staple;
  - samples classed;
  - micronaire distribution when consistently available;
  - strength and leaf/color summaries when consistently available.
- Preserve source page and table number.
- Distinguish US total from state/region tables.
- Build a silver annual-quality table with one row per season and geography.
- Do not claim weekly quality cadence from annual reports.

#### Acceptance criteria

- Percent tenderable is populated for the usable historical seasons.
- Values reconcile with report totals for sampled years.
- Source pages are traceable.
- Dataset documentation states the true annual cadence.

### 2D. Certify existing source-specific silver tables

Each of the following receives a source contract, range checks, date checks,
natural-key uniqueness checks, and revision/flow consistency checks:

- NASS annual.
- NASS crop progress.
- NASS citrus.
- SAGIS CEC.
- SAGIS weekly deliveries.
- SAGIS weekly exports.
- FNC monthly production and exports.
- FNC department area.
- FNC exports by port and type.
- UNICA annual state.
- UNICA fortnightly release series.
- UNICA season history.
- UNICA corn ethanol.
- UNICA monthly ethanol sales.
- MPOB monthly.
- MPOB annual.
- MPOC exports, trade, and stocks.
- ICCO cocoa balance.
- ESR.
- FGIS.
- WAP revisions.
- NOAA ONI.
- NOAA IOD.

Certification must report:

- Historical start and end.
- Row count.
- Natural-key duplicate count.
- Null rate by value column.
- Nonzero revision count.
- Unexpected unit count.
- Unexpected category count.
- Current freshness.
- Known source limitations.

### 2E. Classify economic price drivers and excluded market signals

Do not classify an entire source as fundamental or non-fundamental merely
because it contains prices. Classify each derived feature by its use.

Add one of these policies to every price-related feature:

- `allowed_economic_driver`
- `diagnostic_only`
- `excluded_market_signal`

Examples:

| Feature | Policy | Reason |
|---|---|---|
| Board crush margin | `allowed_economic_driver` | Processing profitability changes physical soybean crush and product output |
| Fertilizer cost index | `allowed_economic_driver` | Input cost affects acreage, application, and expected yield |
| Brent or fuel-cost index | `allowed_economic_driver` | Affects ethanol economics, processing, and freight |
| Lagged BRL or ARS movement | `allowed_economic_driver` | Affects producer selling, input affordability, and export behavior |
| FNC internal producer price | `allowed_economic_driver` for lagged acreage or maintenance studies | Producer returns can affect investment and crop care |
| Own-contract return or momentum | `excluded_market_signal` | Market prediction shortcut, not a physical mechanism |
| Calendar spread or term structure | `excluded_market_signal` | Price-relative market structure is outside the fundamental target |
| CFTC positioning | `diagnostic_only` or `excluded_market_signal` | Positioning describes market behavior rather than physical supply and demand |

Build certified transformations for the currently available economic drivers:

- Soybean board crush margin and its components.
- Fertilizer and energy input-cost indices.
- Brent or fuel-cost transmission variables.
- Lagged producer-price incentive variables where an eligible physical target
  and decision window exist.
- FX-driven selling and input-cost variables.
- Sugar-versus-ethanol allocation economics when the necessary existing price
  series can be aligned from current S3 data.

Each transform must:

- use only values available before the row as-of date;
- apply an explicit decision lag;
- preserve the raw component values used in the calculation;
- use stable physical-unit conversions;
- identify the balance component it can affect;
- avoid using future realized physical outcomes in normalization;
- publish a mechanism-specific name rather than a generic price column.

Add a training preflight that:

- permits `allowed_economic_driver` features only for declared eligible targets;
- rejects `excluded_market_signal` features;
- keeps `diagnostic_only` features out of model fitting;
- reports every admitted price-derived feature and its mechanism in MLflow.

Preserve all current source data in S3. This phase changes feature policy and
transformation semantics, not historical retention.

### Deliverables

- Normalized WASDE silver.
- Repaired CONAB silver.
- AMS cotton bronze and silver.
- Source certification reports.
- Source-level data contracts.
- Economic-driver transforms and mechanism metadata.
- Fundamental-feature policy validator.

### Exit criteria

- All high-value existing physical datasets are numerically usable.
- Defective revision data cannot silently enter gold.
- Every source has a declared grain, cadence, timestamp, and limitation.
- Only certified economic-transmission price features can enter the fundamental
  experiment track.
- Price-prediction and market-signal features remain excluded.

## Phase 3: Define the Physical Commodity and Contract Taxonomy

### Purpose

Stop treating contract slugs as if they were independent biological targets.

### Workstreams

#### 3.1 Create canonical entity dimensions

Add versioned configuration for:

- `physical_commodity`
- `processed_product`
- `contract_slug`
- `origin`
- `crop_class`
- `source_commodity`
- `balance_sheet_family`
- `conversion_relationship`

Example relationships:

```text
maize -> corn_cbot
maize -> campinas_corn_reference_bmf
maize -> french_maize_matif
maize -> south_african_white_maize_jse
maize -> south_african_yellow_maize_jse

soybeans -> soybean_meal
soybeans -> soybean_oil
soybeans -> soybean and product contracts
```

#### 3.2 Separate biological and contract targets

Biological targets:

- Yield anomaly.
- Harvested-area anomaly.
- Production anomaly.
- Crop-condition state.
- Physical output trajectory.

Balance targets:

- Production revision.
- Export revision.
- Consumption/crush revision.
- Ending-stock revision.
- Stock-to-use revision.

Contract-facing outputs:

- Physical supply stress relevant to the contract.
- Contract-specific origin exposure.
- Product balance stress.
- Relative fundamental differential.

#### 3.3 Remove invalid duplicate labels

- Do not train independent coffee-species models against identical generic
  FAOSTAT green-coffee labels.
- Do not train wheat-class models against identical all-wheat labels without a
  class-specific label.
- Do not train meal contracts against bean production as if meal were a crop.
- Do not train white sugar against sugar-cane production as if it represented
  refined-sugar availability.
- Mark proxy labels explicitly and disallow them as primary promotion targets.

#### 3.4 Choose authoritative labels by geography

Priority should follow specificity and finality:

1. Source-specific final national or state estimate.
2. Reconciled official annual source.
3. FAOSTAT final annual value as a long-history fallback.

Examples:

- US crops: NASS annual final values before FAOSTAT.
- Brazil coffee revisions: CONAB.
- Colombia coffee monthly production: FNC.
- South African maize: SAGIS CEC.
- Florida citrus: NASS citrus.
- Malaysia palm: MPOB.
- Brazil sugar: UNICA.

### Deliverables

- Physical commodity taxonomy.
- Contract-to-physical mapping.
- Origin mapping.
- Target dictionary.
- Authoritative-source precedence rules.
- Proxy-label exclusion rules.

### Tests

- Every contract resolves to exactly one physical or product-balance family.
- Every primary target has one authoritative source policy.
- Duplicate label series are reported and justified.
- A processed product cannot accidentally inherit an agricultural area/yield
  target.

### Exit criteria

- Training problems are defined by physical and balance-sheet meaning.
- Contract outputs consume the correct upstream physical signals.
- No experiment can present a proxy label as an undisclosed direct target.

## Phase 4: Build Point-in-Time Gold v2

### Purpose

Replace the annual final-season matrix with a release-aware and as-of-aware
research spine.

### 4.1 Define the long spine grain

Recommended grain:

```text
entity_type
entity_id
physical_commodity
origin
crop_year
as_of_date
feature
feature_value
feature_available_at
source
source_vintage
is_label
```

`event_time` must represent actual availability, not crop-year start.

### 4.2 Define forecast snapshots

Support consistent snapshot policies:

- Preseason.
- Planting.
- Early season.
- Midseason.
- Late season.
- Harvest.
- Each official report release.
- Each weekly or fortnightly physical update.

Snapshots must be generated from data satisfying:

```text
source_release_date <= as_of_date
observation_date <= as_of_date
feature_window_end <= as_of_date
```

### 4.3 Preserve partial-season information

Replace full-season-only features with as-of features such as:

- Stage rainfall observed to date.
- Temperature anomaly observed to date.
- Soil-moisture anomaly observed to date.
- NDVI anomaly observed to date.
- Latest crop condition.
- Change in crop condition over prior weeks.
- Planting/emergence/harvest pace against seasonal norm.
- Cumulative export or delivery pace.
- Latest official revision.
- Number and direction of consecutive revisions.

Do not expose uncompleted stages as completed aggregates.

### 4.4 Build release calendars

Create canonical release calendars from existing data:

- WASDE release date.
- WAP release month.
- NASS crop-progress date.
- NASS citrus release date.
- SAGIS CEC release date.
- CONAB survey date.
- FNC monthly observation date.
- UNICA position date.
- MPOB month.
- ICCO release date or latest-release date.
- ESR and FGIS week-ending date.

### 4.5 Build immutable dataset versions

Write gold v2 under versioned prefixes:

```text
gold_v2/feature_spine/dataset_version={version}/...
gold_v2/feature_matrix/dataset_version={version}/...
gold_v2/dataset_manifests/dataset_version={version}/manifest.json
```

Do not overwrite an existing dataset version.

The manifest must include:

- Code Git SHA.
- Dirty-worktree flag.
- Container image digest.
- Configuration SHAs.
- Input object fingerprints.
- Input source vintages.
- Row and feature counts.
- Time range.
- Validation results.

### 4.6 Repair training and serving symmetry

- Replace "read the latest annual row" with "read the latest certified snapshot
  at or before the requested as-of date."
- Require callers to provide:
  - entity;
  - target;
  - horizon;
  - as-of date;
  - feature-set ID.
- Make it impossible for serving to infer a future-complete season by default.

### Tests

- Truncate all sources at historical date T and rebuild.
- Verify that no value released after T appears.
- Advance T by one release and verify only newly available values change.
- Verify incomplete crop stages remain null or explicitly partial.
- Verify the same snapshot is returned by training and serving loaders.
- Verify every row has `feature_available_at <= as_of_date`.

### Exit criteria

- Historical simulations reproduce what was knowable at each date.
- Full-season weather and progress no longer leak into early-season snapshots.
- Training and inference use the same snapshot builder.

## Phase 5: Rebuild Feature Taxonomy and Feature Sets

### Purpose

Create a meaningful taxonomy for selection, ablation, governance, and reuse.

### 5.1 Separate semantic scope from empirical availability

Semantic scope:

- `global`
- `group`
- `physical_commodity`
- `origin`
- `contract`

Empirical availability:

- Number of entities containing the feature.
- Number of years or releases.
- First and last available dates.
- Non-null rate.
- Source cadence.

A Brazil coffee weather feature is semantically origin-specific even if the
catalog-building run processed only Brazil coffee.

### 5.2 Make the catalog a single-writer output

- Commodity jobs write only their own manifests and matrices.
- A final catalog job reads all completed manifests.
- The final job computes cross-entity coverage.
- The catalog is published only if the expected entity set is complete.
- Partial rebuilds must not overwrite the global catalog.

### 5.3 Add real group membership

The current `group` field is always null. Populate explicit groups such as:

- grains;
- oilseeds;
- soy complex;
- wheat complex;
- maize complex;
- coffee;
- sugar and biofuel;
- palm;
- tree crops;
- US row crops;
- South African grains.

A feature may have multiple group tags. Use a normalized mapping table rather
than forcing one ambiguous string.

### 5.4 Replace era tiers with model-purpose feature sets

Create versioned feature-set definitions for:

- `preseason_physical`
- `inseason_weather`
- `crop_condition`
- `official_revision`
- `physical_flow`
- `balance_sheet`
- `processing_economics`
- `planting_incentives`
- `trade_competitiveness`
- `tail_risk`
- `data_quality`

Each feature set declares:

- Allowed semantic scopes.
- Allowed sources.
- Allowed economic mechanisms and price-feature policies.
- Excluded market-signal classes.
- Required as-of policy.
- Required decision lag for price-derived economic drivers.
- Minimum coverage.
- Missingness policy.
- Target compatibility.
- Feature-set version.

### 5.5 Reduce dimensionality before model fitting

The current matrices contain up to 730 inputs for approximately 220 labels.
Feature engineering must reduce this before tuning.

Required methods:

- Agronomic aggregation from location to weighted origin-stage features.
- Remove zero-variance and near-zero-variance columns.
- Remove duplicate columns.
- Collapse strongly redundant regional measurements when they represent the
  same mechanism.
- Retain source-availability flags separately from source values.
- Apply selection inside each training fold when target-driven selection is
  used.

### 5.6 Complete crop calendars

- Add a calendar only where agronomically defensible.
- Prefer physical-commodity and origin calendars over contract calendars.
- Validate cross-year stage windows.
- Document tree-crop multi-year cycles.
- Contracts without a defensible calendar consume shared physical-model
  outputs instead of inventing one.

### Deliverables

- Global feature catalog v2.
- Feature-to-entity and feature-to-group mapping tables.
- Versioned model-purpose feature-set configs.
- Economic-mechanism and market-signal policy tests.
- Coverage and collinearity reports.
- Physical crop calendars.

### Exit criteria

- Scope labels remain correct under partial rebuilds.
- Feature selection is config-driven and reviewable.
- Fundamental feature sets admit only certified economic-transmission price
  features and reject price-prediction or technical-market features.
- Feature count is proportionate to usable observations.

## Phase 6: Build Model-Ready Targets and Datasets

### Purpose

Produce explicit supervised and unsupervised datasets for experimentation.

### 6.1 Define target families

Required target families:

- Official next-release revision.
- Official finalization gap.
- Yield anomaly versus trailing expectation.
- Harvested-area anomaly versus trailing expectation.
- Production anomaly composed from area and yield.
- End-season physical-flow total.
- Balance-sheet component revision.
- Ending-stock and stock-to-use revision.
- Tail-event labels.

Each target requires:

- Definition.
- Unit.
- Forecast horizon.
- As-of rule.
- Final source.
- Revision policy.
- Eligible entities.
- Minimum sample requirement.

### 6.2 Build no-change and structural baselines

Every supervised dataset must include baseline predictions:

- Current official estimate unchanged.
- Prior release unchanged.
- Prior-year final value.
- Trailing mean.
- Trailing linear trend.
- Seasonal analogue.
- Current cumulative pace extrapolation for flow datasets.

These baselines are dataset artifacts, not informal notebook calculations.

### 6.3 Separate training grains

Create distinct datasets instead of one overloaded matrix:

#### Annual physical anomaly dataset

```text
physical_commodity x origin x crop_year x as_of_stage
```

#### Official revision dataset

```text
source x commodity x geography x marketing_year x release_date
```

#### Weekly/fortnightly trajectory dataset

```text
source x commodity x geography x season x observation_date
```

#### Balance-sheet dataset

```text
commodity x geography x marketing_year x release_date x balance_component
```

#### Unsupervised anomaly dataset

```text
entity x observation_date x standardized physical features
```

### 6.4 Add dataset eligibility gates

Before publishing:

- Minimum number of independent seasons.
- Minimum number of nonzero target changes.
- Maximum feature-to-observation ratio.
- Maximum missingness by required feature family.
- Minimum number of stress/tail events.
- No duplicated target series presented as independent entities.
- No unsupported target unit or source vintage.

### 6.5 Register dataset versions

Create a dataset manifest table containing:

- `dataset_id`
- `dataset_version`
- `target_id`
- `feature_set_id`
- `entity_scope`
- `row_count`
- `feature_count`
- `first_as_of_date`
- `last_as_of_date`
- `positive_tail_count`
- `negative_tail_count`
- `content_fingerprint`
- `manifest_s3_uri`
- `certification_status`

### Deliverables

- Versioned model-ready datasets.
- Target registry.
- Baseline prediction artifacts.
- Dataset manifest table.
- Dataset eligibility reports.

### Exit criteria

- Every experiment target has a valid economic and physical interpretation.
- Baselines are available before any learned model is evaluated.
- Datasets of different grains are not mixed into one annual matrix.
- Ineligible datasets are blocked rather than quietly trained.

## Phase 7: Add Data-Quality, Leakage, and Robustness Certification

### Purpose

Turn data correctness into an automated gate rather than a researcher's
assumption.

### 7.1 Source-level checks

- Schema.
- Natural-key uniqueness.
- Unit consistency.
- Range validity.
- Category allowlists.
- Date monotonicity.
- Revision arithmetic.
- Cumulative-flow monotonicity where expected.
- Final estimate consistency.
- Suspicious identical partitions.

### 7.2 Gold-level checks

- Feature availability is not later than as-of date.
- Labels are not present in feature columns.
- Target-derived transformations are fold-local.
- Source-vintage dates are retained.
- No future-complete stage enters an earlier snapshot.
- Global values are broadcast only when semantically valid.
- Origin-specific values do not leak across origins.

### 7.3 Statistical checks

- Constant features.
- Duplicate features.
- Extreme missingness.
- Implausible discontinuities.
- Target leakage correlations.
- Unexpected target identity across contracts.
- Unrealistic revision distributions.
- Feature-count versus sample-count warning.
- Train/test distribution changes by release era.

### 7.4 Truncate-at-T regression suite

For selected historical dates:

1. Build the dataset with all current data.
2. Build it after truncating inputs at T.
3. Compare the row corresponding to T.
4. Require equality for every feature that should have been known at T.
5. Require absence of every feature first available after T.

Cover:

- WASDE.
- NASS crop progress.
- NASS citrus.
- SAGIS CEC.
- CONAB.
- UNICA.
- MPOB.
- ESR.
- FGIS.
- Weather stages.

### 7.5 Certification artifact

Publish a machine-readable certification:

```text
certified
certified_with_warnings
blocked
```

MLflow training must reject `blocked` dataset versions.

### Exit criteria

- Leakage checks run automatically.
- A dataset cannot be trained merely because Parquet exists.
- Known source defects become explicit blocked certifications.
- Certification is linked to every MLflow run.

## Phase 8: Complete the MLflow Experimentation System

### Purpose

Make every experiment comparable, reproducible, and capable of producing a
deployable fitted artifact.

### 8.1 Define experiment hierarchy

Use separate MLflow experiments by research problem, not one generic production
experiment.

Recommended naming convention:

```text
leviathan/{target_family}/{entity_family}
```

Runs are tagged with physical commodity, origin, target, horizon, and dataset
version.

### 8.2 Build a general experiment runner

The runner must accept:

- Dataset ID and version.
- Feature-set ID and version.
- Target ID.
- Entity filter.
- As-of stage or horizon.
- Estimator adapter.
- Search-space config.
- CV policy.
- Final holdout policy.
- Random seed.
- Experiment name.

It must not infer experimental intent solely from a contract slug.

### 8.3 Fit and log the final model

After cross-validation and model selection:

- Refit the selected configuration on the eligible pre-holdout data.
- Evaluate once on the untouched final holdout.
- Log the fitted model with its signature and input example.
- Log preprocessing and feature-selection objects as one pipeline artifact.
- Store the model under MLflow artifacts.
- Do not register or promote a model that lacks a fitted artifact.

### 8.4 Log full tuning history

- Use nested or child MLflow runs for tuning trials, or log a complete trial
  table artifact.
- Record failed and pruned trials.
- Record trial duration.
- Record search-space version.
- Do not log only the winning parameters.

### 8.5 Add proper evaluation outputs

Required metrics by applicable target:

- Baseline-relative skill.
- Normalized absolute error.
- Directional accuracy.
- Revision-direction accuracy.
- Tail precision, recall, and calibration.
- Quantile or interval loss.
- Prediction-interval coverage.
- Error by origin.
- Error by forecast horizon.
- Error by source/release month.
- Stress-year or tail-event performance.
- Sample count for every metric.

### 8.6 Add run artifacts

- Fold predictions.
- Final holdout predictions.
- Baseline predictions.
- Residual diagnostics.
- Feature coverage report.
- Dataset manifest.
- Feature-set config.
- Trial history.
- Fitted model.
- Model signature.
- Explanation output when supported.
- Validation certification.

### 8.7 Fix provenance

- Fail or warn when Git SHA is unknown.
- Record dirty-worktree state.
- Record ECR image digest.
- Record exact package lock or installed dependency list.
- Record AWS Batch job ID and job-definition revision.
- Record source object fingerprints.

### 8.8 Add a candidate model registry workflow

Experiment readiness requires a clear distinction between:

- experiment run;
- candidate model;
- approved research champion;
- production model.

At this stage:

- Allow a run to be registered as a candidate only after certification passes.
- Use MLflow aliases such as `candidate` and `research_champion`.
- Do not automatically create a production alias.
- Promotion to production remains a later governance decision.

### Deliverables

- General experiment runner.
- Estimator adapter interface.
- Search-space configuration format.
- Complete MLflow logging.
- Fitted model artifacts.
- Candidate registry workflow.
- Experiment comparison report.

### Exit criteria

- A run can be recreated from its tags and artifacts.
- MLflow contains a fitted model, not only predictions.
- Every run compares against stored baselines.
- Hyperparameter history is inspectable.
- Uncertified datasets cannot launch experiments.

## Phase 9: Reconcile Infrastructure and Orchestration

### Purpose

Make the experimentation platform durable and operable without adding expensive
serving infrastructure.

### 9.1 Make MLflow backend durable

Preferred development options:

1. Attach a dedicated persistent encrypted EBS volume and preserve it across
   instance replacement.
2. Move MLflow metadata to a small managed PostgreSQL backend when concurrent
   use justifies it.

Do not continue with the only metadata copy on a delete-on-termination root
volume.

### 9.2 Remove hardcoded MLflow private IPs

- Resolve the tracking endpoint through:
  - private DNS;
  - an internal load balancer;
  - Cloud Map;
  - or a parameter stored in SSM Parameter Store.
- Batch job definitions should not require manual updates after EC2 replacement.

### 9.3 Pin container images

- Use immutable release tags or image digests.
- Record image digest in every run.
- Do not let `latest` change the implementation behind an otherwise identical
  experiment.
- Maintain separate worker and trainer release histories.

### 9.4 Reconcile Airflow configuration

The live Airflow environment currently uses SQLite and SequentialExecutor even
though Terraform comments describe LocalExecutor.

- Make code, environment variables, and live configuration agree.
- Keep SequentialExecutor if only one local task should run at a time.
- Use Airflow primarily to submit and monitor Batch jobs.
- Unpause only validated DAGs.

### 9.5 Add experiment orchestration DAGs

Create DAGs for:

- Dataset build and certification.
- Experiment launch.
- Experiment result aggregation.
- Candidate registration.
- Periodic source freshness checks.

Do not add production inference scheduling until research champions exist.

### 9.6 Add observability

Monitor:

- MLflow and Airflow service health.
- Backend backup age.
- Disk usage.
- Batch queue depth.
- Failed experiment jobs.
- Dataset-certification failures.
- Athena catalog drift.
- Stale source inputs.

### 9.7 Update output tables

Reconcile the current narrow model-prediction DDL with the generalized schema
already described in `desiredstate.md`.

Add:

- `silver_model_predictions`
- `silver_model_explanations`
- `silver_model_dependencies`
- `silver_model_drift_reports`

For experiment readiness, predictions and explanations may initially be
research outputs. Their schemas must already support different target families
and non-contract entities.

### Deliverables

- Durable MLflow backend.
- Stable tracking endpoint.
- Immutable trainer-image releases.
- Reconciled Airflow deployment.
- Experiment DAGs.
- Health and backup monitoring.
- Correct generalized model-output tables.

### Exit criteria

- EC2 replacement does not erase experiments.
- Batch resolves MLflow without a hardcoded private IP.
- A scheduled workflow can build, certify, train, and summarize an experiment.
- Output tables support physical, balance, anomaly, and downstream model types.

## Phase 10: Experiment Readiness Certification

### Purpose

Prove that the system is ready before launching broad model research.

### 10.1 Select representative certification datasets

Use a cross-section of data structures:

- US annual crop plus weekly crop progress.
- Multi-origin annual crop.
- Official monthly revision series.
- Weekly physical-flow series.
- Tree crop.
- Processed-product balance.

The certification exercise validates infrastructure and data contracts. It does
not choose the final model portfolio.

### 10.2 Run end-to-end dry runs

For each certification dataset:

1. Build immutable gold snapshots.
2. Run source and PIT certification.
3. Resolve a versioned feature set.
4. Generate stored baselines.
5. Launch a small experiment.
6. Log complete MLflow metadata.
7. Log a fitted artifact.
8. Recreate predictions from the logged artifact.
9. Query predictions in Athena.
10. Restore MLflow metadata in a temporary environment and find the run.

### 10.3 Reproducibility test

Run the same dataset, configuration, seed, and image twice.

Require:

- Same dataset fingerprint.
- Same feature-set SHA.
- Same fold assignment.
- Deterministic predictions within declared tolerance.
- Same primary metrics within declared tolerance.

### 10.4 Negative tests

Confirm the platform rejects:

- A feature released after the row as-of date.
- A blocked dataset certification.
- A market-derived feature in a fundamental feature set.
- A processed product using an agricultural yield target.
- An unknown Git SHA when strict mode is enabled.
- A mutable unrecorded image reference.
- A target with insufficient independent seasons.
- A suspicious identical CONAB survey.

### 10.5 Final readiness checklist

Data:

- [ ] S3 Inventory is live.
- [ ] Dataset registry covers all model-relevant prefixes.
- [ ] Athena DDL drift is zero.
- [ ] WASDE revisions are normalized.
- [ ] CONAB revisions are repaired or explicitly blocked.
- [ ] AMS cotton quality is structured.
- [ ] Every existing physical source has a certification report.

Semantics:

- [ ] Physical commodity taxonomy is authoritative.
- [ ] Contract-to-physical mappings are explicit.
- [ ] Primary and proxy labels are distinguishable.
- [ ] Source precedence is documented.

Point in time:

- [ ] Gold v2 contains as-of snapshots.
- [ ] Actual availability timestamps are retained.
- [ ] Truncate-at-T tests pass.
- [ ] Training and serving loaders return the same snapshot.

Features:

- [ ] Feature catalog is built by one finalizer.
- [ ] Global, group, physical, origin, and contract scopes are populated.
- [ ] Model-purpose feature sets are versioned.
- [ ] Fundamental sets contain no market-derived inputs.
- [ ] Feature count is controlled relative to sample size.

MLflow:

- [ ] Runs log dataset and feature-set versions.
- [ ] Runs log Git SHA and image digest.
- [ ] Baselines are logged.
- [ ] Trial history is logged.
- [ ] Fitted model artifacts are logged.
- [ ] Candidate registry workflow works.
- [ ] Existing runs survive backend restore.

Infrastructure:

- [ ] Terraform plan is non-destructive or intentionally migratory.
- [ ] MLflow backend is durable.
- [ ] Tracking URI is stable.
- [ ] Airflow live configuration matches code.
- [ ] Experiment DAGs are tested.
- [ ] Backup and service-health alarms exist.

### Definition of done

The program is complete when a researcher can launch a certified experiment
using a versioned dataset and feature set, inspect all trials in MLflow, compare
the result with stored baselines, load the fitted artifact, reproduce its
predictions, and prove that no input was unavailable at the forecast date.

## 6. Cross-Phase Engineering Standards

### 6.1 Immutability

- Raw remains immutable.
- Bronze and silver transforms are reproducible.
- Gold experiment dataset versions are immutable.
- Model artifacts are immutable.
- Mutable aliases may point to immutable versions.

### 6.2 Idempotency

- Rerunning a transform with the same inputs and version produces the same
  content fingerprint.
- Existing versioned outputs are skipped unless an explicit rebuild creates a
  new version.
- Retry behavior cannot duplicate natural keys.

### 6.3 Source lineage

Every derived row must be traceable to:

- Source dataset.
- Source object or release.
- Parser/transform version.
- Configuration version.
- Build job.

### 6.4 Test pyramid

- Unit tests for parsing and feature calculations.
- Contract tests for schemas and natural keys.
- Integration tests over bounded S3 fixtures.
- PIT regression tests.
- Athena smoke tests.
- End-to-end experiment tests.

### 6.5 Change management

- Data-contract changes require a dataset-version increment.
- Feature-definition changes require a feature-set-version increment.
- Target changes require a target-version increment.
- Training-code changes require a new image digest.
- Runs with different target or dataset versions must not be ranked as direct
  substitutes without an explicit comparison study.

## 7. Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Rebuilding gold changes historical experiment results | Preserve immutable dataset versions and existing snapshots |
| WASDE parser-era differences create false revisions | Use era-specific mappings, allowlists, and sampled report reconciliation |
| Source-specific datasets have short histories | Pool only when entities share a defensible mechanism; use simpler baselines and uncertainty |
| Hundreds of regional weather features overwhelm small annual samples | Agronomic aggregation, fold-local selection, and feature-count gates |
| Partial-season features accidentally use full-season normalization | Use as-of-safe trailing baselines and truncate-at-T tests |
| Contract duplication inflates the number of apparent models | Train physical and balance entities, then map outputs to contracts |
| Terraform replaces MLflow before state is durable | Block apply until backup, restore, and state reconciliation pass |
| Mutable ECR tags make runs irreproducible | Pin image digest in Batch and MLflow |
| Market variables leak into the fundamental track | Source policy metadata and training preflight rejection |
| Researcher selects features in the UI without version control | MLflow is for comparison; feature definitions remain in reviewed configuration |

## 8. Recommended Execution Order

The shortest safe critical path is:

1. Protect MLflow state and neutralize destructive Terraform drift.
2. Establish the dataset registry and repair Athena.
3. Build normalized WASDE silver.
4. Repair or block CONAB.
5. Build AMS cotton structured data.
6. Define physical commodity, origin, product, and contract mappings.
7. Build point-in-time gold v2.
8. Rebuild feature taxonomy and model-purpose feature sets.
9. Build certified model-ready datasets and baselines.
10. Complete MLflow logging, fitted artifacts, and trial tracking.
11. Reconcile Airflow and add experiment orchestration.
12. Pass the end-to-end readiness certification.

Parallel work is safe only where outputs do not overlap:

- Athena reconciliation can proceed alongside source certification.
- AMS parsing can proceed alongside WASDE normalization.
- Entity taxonomy can proceed alongside data repairs.
- MLflow runner refactoring can proceed before gold v2 is complete, using
  bounded fixtures.
- Broad experiment sweeps must wait for certified gold v2 datasets.

## 9. Recommended Model Portfolio

This section describes the research portfolio to investigate after the phases
above establish experiment readiness. It is intentionally separate from the
remediation phases.

### 9.1 Official next-release revision models

#### Research question

Given information available immediately before an official release, will the
next estimate be revised up or down, and by how much?

#### Targets

- `next_estimate - current_estimate`
- Revision direction.
- Probability of a revision exceeding a material threshold.

#### Existing data

- WASDE releases.
- WAP revisions.
- SAGIS CEC.
- NASS citrus.
- CONAB after repair.
- Crop progress.
- Weather and remote sensing.
- ESR and FGIS.

#### Candidate approaches

- Regularized linear benchmark.
- Hierarchical partial-pooling regression.
- Gradient-boosted tree model.
- Quantile model for revision intervals.

#### Why it is valuable

The target is explicitly relative to the current official consensus. It is more
actionable and statistically cleaner than predicting a large trending
production level.

### 9.2 Finalization-gap models

#### Research question

How far is the current official estimate likely to finish from the eventual
final estimate?

#### Targets

- `final_estimate - current_estimate`
- Probability current estimate is materially too high.
- Probability current estimate is materially too low.

#### Existing data

- Historical release paths from WASDE.
- NASS citrus forecast history.
- SAGIS CEC estimate sequence.
- CONAB survey sequence after repair.
- WAP revisions.

#### Candidate approaches

- Release-month-specific regularized models.
- Hierarchical models pooling adjacent release months.
- Quantile regression.
- Survival-style convergence model over the estimate sequence.

#### Why it is valuable

It measures remaining official-estimate risk directly and naturally supports a
confidence interval.

### 9.3 Yield and harvested-area anomaly models

#### Research question

Is the crop likely to finish above or below its trailing yield and area
expectation?

#### Targets

- Yield residual versus a trailing expectation.
- Harvested-area residual versus a trailing expectation.
- Tail-event probability for large negative residuals.

#### Existing data

- NASS annual.
- FAOSTAT fallback history.
- Stage weather.
- CHIRPS.
- NASA POWER.
- CPC soil.
- MODIS NDVI.
- NASS crop progress.
- ONI and IOD.

#### Candidate approaches

- Regularized linear benchmark.
- Gradient-boosted trees.
- Hierarchical origin model.
- Quantile regression.
- Calibrated tail classifier.

#### Why it is valuable

It separates agronomic yield shock from acreage abandonment or expansion.
Production can then be composed from understandable physical components.

### 9.4 Physical-flow trajectory models

#### Research question

Given the cumulative path observed so far, where will the season finish?

#### Targets

- End-season exports.
- End-season deliveries.
- End-season crush.
- End-season sugar or ethanol production.
- Remaining volume from the current date.

#### Existing data

- NASS crop progress.
- SAGIS weekly deliveries and exports.
- ESR.
- FGIS.
- UNICA fortnightly.
- FNC monthly exports and production.
- MPOB monthly production, exports, imports, and stocks.

#### Candidate approaches

- Seasonal curve benchmark.
- Dynamic linear model.
- State-space model.
- Gradient-boosted model on curve-position features.
- Functional trajectory model.

#### Why it is valuable

These datasets have many more observations than annual crop models and produce
continually updating in-season signals.

### 9.5 Probabilistic supply-and-demand reconciler

#### Research question

What distribution of ending stocks and stock-to-use is consistent with the
uncertainty in production, trade, and consumption components?

#### Identity

```text
ending stocks =
beginning stocks
+ production
+ imports
- exports
- consumption
```

#### Targets

- Ending-stocks revision.
- Stock-to-use revision.
- Component-level forecast distributions.

#### Existing data

- Normalized WASDE.
- PSD levels.
- WAP.
- ESR and FGIS.
- SAGIS.
- FNC.
- MPOB and MPOC.
- UNICA.
- ICCO.

#### Candidate approaches

- Component models plus constrained reconciliation.
- Probabilistic graphical model.
- Hierarchical Bayesian balance model.
- Quantile component forecasts with accounting reconciliation.

#### Why it is valuable

It enforces physical accounting and avoids an unconstrained model producing an
impossible balance sheet.

### 9.6 Tail-event classifiers

#### Research question

Is the current season or estimate path entering a materially adverse tail?

#### Example labels

- Yield anomaly below minus one standard deviation.
- Official downward revision beyond a material threshold.
- Crop condition below a historical percentile.
- Export pace materially below the official balance assumption.
- Tenderable cotton share below a historical threshold.
- Multi-origin simultaneous stress.

#### Existing data

- Weather and remote sensing.
- Crop progress.
- Official revisions.
- Physical flows.
- AMS cotton quality.
- Climate indices.

#### Candidate approaches

- Penalized logistic baseline.
- Calibrated boosted classifier.
- Hierarchical classifier.
- Conformal risk set or calibrated probability layer.

#### Why it is valuable

The portfolio is primarily valuable in extreme years. Tail recall, precision,
and probability calibration are more relevant than average production RMSE.

### 9.7 Multivariate physical anomaly detectors

#### Research question

Is the current combination of physical observations outside the historical
normal manifold, even if no individual feature is extreme?

#### Existing data

- Weekly and monthly physical panels.
- Weather and remote sensing.
- Crop condition.
- Official revisions.
- Trade and delivery pace.
- Stocks and crush.

#### Candidate approaches

- Robust covariance distance.
- Isolation-based detector.
- One-class model.
- Autoencoder only for sufficiently large weekly/monthly panels.

#### Outputs

- Anomaly score.
- Historical percentile.
- Contributing feature deviations.
- Nearest historical analogues.
- Data-quality anomaly flag separated from economic anomaly.

#### Why it is valuable

It can identify unprecedented combinations and warn when supervised models are
operating outside their training support.

### 9.8 Hierarchical physical-crop models

#### Research question

Can shared biological information improve sparse origin forecasts without
pretending every exchange contract is an independent crop?

#### Structure

```text
global crop mechanism
  -> physical commodity
    -> origin
      -> crop class or product balance
        -> contract-facing output
```

#### Existing data

- Shared weather and climate indices.
- Origin-specific weather.
- Official production histories.
- Source-specific revisions and flows.

#### Candidate approaches

- Mixed-effects model.
- Hierarchical Bayesian model.
- Shared model with entity embeddings or entity indicators.
- Multi-task boosted-tree approximation with carefully designed entity
  features.

#### Why it is valuable

It pools signal where biology is shared while preserving origin and product
differences. It is a better match to the 13 physical FAOSTAT items underlying
31 contract slugs.

### 9.9 Source-reliability and estimate-combination model

#### Research question

When multiple official and physical sources disagree, which source should
receive more weight at this stage of the season?

#### Inputs

- Current source estimates.
- Historical source errors by horizon.
- Source revision volatility.
- Source freshness.
- Source availability.
- Weather and progress context.

#### Outputs

- Combined estimate.
- Source weights.
- Disagreement score.
- Confidence interval.

#### Candidate approaches

- Inverse historical-error weighting baseline.
- Dynamic model averaging.
- Bayesian model combination.
- Stacked out-of-fold meta-model after sufficient upstream histories exist.

#### Why it is valuable

Source disagreement is itself information. A combination layer can exploit
consistent source biases while exposing rather than hiding uncertainty.

### 9.10 Fundamental relative-stress engine

#### Research question

Which related physical commodity, origin, or processed product is more
fundamentally stressed?

#### Inputs

- Certified upstream revision forecasts.
- Yield and area anomaly distributions.
- Physical-flow trajectories.
- Balance-sheet surprise.
- Tail-event probabilities.

#### Outputs

- Relative physical stress differential.
- Confidence in the asymmetry.
- Upstream dependency trace.
- Component contribution breakdown.

#### Candidate approaches

- Begin with transparent arithmetic over certified upstream outputs.
- Add a learned combination model only after enough out-of-fold upstream
  predictions exist.

#### Why it is valuable

It provides contract-relevant relative fundamental research without requiring
price prediction or market-price features.
