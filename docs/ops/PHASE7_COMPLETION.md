# Phase 7 Completion: Existing-Silver Feature Families

Code completed: 2026-06-25
Runtime completed: 2026-06-26

## Scope

Implemented the first Phase 7 batch of high-value existing-silver feature
families in the broad legacy `gold/feature_spine` path.

No GraphRAG files were touched.

## Added Feature Families

- `wasde_direct_revisions`
  - Source: `silver/wasde/`
  - Features:
    - `wasde_latest_revision`
    - `wasde_consecutive_revision_count`
    - `wasde_production_revision_z`
    - `wasde_ending_stocks_revision_z`
    - `wasde_exports_revision_z`
    - `wasde_total_use_revision_z`
    - `wasde_domestic_use_revision_z`
  - Notes: uses the latest visible marketing-year row before crop-year start,
    capped at the target prior marketing year. This avoids requiring exact
    marketing-year matches when WASDE exposes only older closed years for a
    commodity/attribute before planting.

- `nass_citrus_revisions`
  - Source: `silver/nass_citrus/`
  - Commodity: `frozen_orange_juice`
  - Features:
    - `nass_citrus_forecast_revision_z`
    - `nass_citrus_prior_report_change_z`
    - `nass_citrus_finalization_gap_z`

- `ams_cotton_quality`
  - Source: `silver/ams_cotton_quality/`
  - Commodity: `cotton`
  - Features:
    - `ams_percent_tenderable`
    - `ams_percent_tenderable_z`
    - `ams_avg_staple_z`

- `unica_sugar_biweekly`
  - Source: `silver/unica_biweekly_season_history/`
  - Commodities: `raw_sugar`, `white_sugar`
  - Features:
    - `unica_cane_crush_pace_z`
    - `unica_sugar_output_pace_z`
    - `unica_sugar_mix_pct`
    - `unica_ethanol_mix_pct`

## Governance Updates

- Feature registry now contains 36 families.
- Taxonomy source metadata was updated for implemented Phase 7 families.
- Added a `quality_tenderability` model-purpose feature set.
- Added cotton quality to the `tail_risk` feature set.

## Live S3 Smoke

Validated source reads and feature emission from live S3:

- WASDE corn smoke emitted 68 rows across:
  - `wasde_latest_revision`
  - `wasde_consecutive_revision_count`
  - `wasde_ending_stocks_revision_z`
  - `wasde_exports_revision_z`
  - `wasde_domestic_use_revision_z`
- AMS cotton smoke emitted:
  - `ams_percent_tenderable`
  - `ams_percent_tenderable_z`
  - `ams_avg_staple_z`
- NASS citrus smoke emitted:
  - `nass_citrus_forecast_revision_z`
  - `nass_citrus_prior_report_change_z`
  - `nass_citrus_finalization_gap_z`
- UNICA raw sugar smoke emitted:
  - `unica_cane_crush_pace_z`
  - `unica_sugar_output_pace_z`
  - `unica_sugar_mix_pct`
  - `unica_ethanol_mix_pct`

## Operational Note

`silver/wasde/` has mixed legacy Parquet fragments that can trigger a
`pyarrow.dataset` schema-unification failure during predicate pushdown. The
WASDE extractor now uses a threaded per-file Parquet reader for that source,
then filters by commodity in pandas.

## Tests

Passed:

```powershell
$env:PYTHONPATH='C:\Users\User\Desktop\Leviathan-main-publish\src;C:\Users\User\Desktop\Leviathan-main-publish'
C:\Users\User\Desktop\Leviathan\.venv\Scripts\python.exe -m pytest `
  tests\unit\test_features_computations_phase7.py `
  tests\unit\test_features_feature_sets.py `
  tests\unit\test_feature_source_coverage.py
```

Result:

```text
12 passed
```

## Runtime Rollout

The worker image was rebuilt and pushed to ECR with the Phase 7 code:

```text
668891723125.dkr.ecr.us-east-1.amazonaws.com/leviathan-dev-leviathan-worker:6725de02
668891723125.dkr.ecr.us-east-1.amazonaws.com/leviathan-dev-leviathan-worker:latest
digest: sha256:b842105362d1adc3222bc0e45365f6847e16abb81e923fde52333f9dc46809e4
```

Smoke version:

```text
20260626T005517Z_6725de02_smoke_phase7
```

Smoke jobs ran on `leviathan-dev-queue-ondemand` for:

- `corn_cbot`
- `cotton`
- `frozen_orange_juice`
- `raw_sugar`

All four smoke shards succeeded. The smoke version was finalized through the
dataset manifest and semantic catalog pass. Feature-set generation was deferred
to the full version because a four-commodity subset does not contain every
global feature-set family.

Full immutable gold version:

```text
20260626T010217Z_6725de02_phase7_full
```

The full run submitted 31 sharded on-demand Batch jobs with:

```text
--write-versioned
--versioned-only
--skip-existing-versioned
--workers 4
```

All 31 shards succeeded.

## Full Version Outputs

Validated S3 outputs for `20260626T010217Z_6725de02_phase7_full`:

- `gold/feature_spine_versions/...`: 31 Parquet shard objects
- `gold/feature_matrix_versions/...`: 31 Parquet shard objects
- `gold/feature_spine_commodity_manifests/...`: 31 JSON shard manifests
- `gold/feature_spine_manifests/.../manifest.json`: present
- `gold/feature_catalog_versions/.../feature_catalog.parquet`: present
- `gold/feature_entity_map_versions/.../feature_entity_map.parquet`: present
- `gold/feature_group_map_versions/.../feature_group_map.parquet`: present
- `gold/feature_set_versions/.../feature_sets.parquet`: present
- `gold/feature_set_manifests/.../feature_sets.json`: present
- `gold/training_windows_versions/.../training_windows.parquet`: present
- `gold/training_windows_versions/.../training_windows.md`: present

Validated manifest summary:

```text
commodity_count: 31
total_spine_rows: 151,927
total_matrix_rows: 4,370
total_label_rows: 11,207
feature_count: 2,722
label_feature_count: 3
universal_feature_count: 9
group_feature_count: 121
commodity_feature_count: 2,592
hard_failure_count: 0
warning_count: 8
training_windows_available: true
training_windows_row_count: 124
training_windows_commodity_count: 31
```

Semantic and feature-set validation:

```text
semantic catalog rows: 2,722
unknown taxonomy rows: 0
feature-set rows: 4,165
feature-set count: 13
training-window rows: 124
```

Phase 7 feature families present in the full catalog:

- `wasde_latest_revision`
- `wasde_consecutive_revision_count`
- `wasde_production_revision_z`
- `wasde_ending_stocks_revision_z`
- `wasde_exports_revision_z`
- `wasde_total_use_revision_z`
- `wasde_domestic_use_revision_z`
- `nass_citrus_forecast_revision_z`
- `nass_citrus_prior_report_change_z`
- `nass_citrus_finalization_gap_z`
- `ams_percent_tenderable`
- `ams_percent_tenderable_z`
- `ams_avg_staple_z`
- `unica_cane_crush_pace_z`
- `unica_sugar_output_pace_z`
- `unica_sugar_mix_pct`
- `unica_ethanol_mix_pct`

Trainer-facing validation:

- representative feature-set selections resolved usable columns for corn,
  soybean oil, cotton, raw sugar, and frozen orange juice;
- `jobs/submit/submit_batch_train.py --dry-run` accepted
  `--feature-sets` plus `--dataset-version` and produced the expected Batch
  parameter grid without launching jobs.

Phase 7 exit criteria are satisfied. The next phase is Phase 8: build
explicit model-ready targets and datasets from this versioned gold surface.
