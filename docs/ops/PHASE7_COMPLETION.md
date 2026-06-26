# Phase 7A Completion: Existing-Silver Feature Families

Completed: 2026-06-25

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

## Remaining Runtime Step

These features are implemented in code, but a new immutable gold dataset version
has not yet been built. To make them visible in S3 `gold/feature_spine_versions`
and MLflow feature-set outputs:

1. Rebuild and push the worker image.
2. Run a bounded smoke gold build for one affected commodity.
3. Run the full versioned gold build with `--skip-existing-versioned` only for
   a new dataset version where appropriate.
4. Rebuild semantic catalog and feature-set artifacts for that new dataset
   version.
