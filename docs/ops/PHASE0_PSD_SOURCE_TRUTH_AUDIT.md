# Phase 0 PSD Source Truth Audit

Date: 2026-06-28

## Objective

Reconcile the PSD/WASDE source truth before continuing the feature diagnostics remediation plan. This phase exists because Phase 1 originally treated `psd_monthly_vintage_features` as if current PSD silver contained monthly release history. S3 verification showed that assumption was wrong.

## Read-Only Audit Utility

The audit can be regenerated without mutating S3:

```powershell
.\.venv\Scripts\python.exe jobs\utils\build_psd_source_truth_audit.py `
  --bucket leviathan-dev-shahem-001 `
  --aws-region us-east-1 `
  --output-json data\feature_diagnostics\phase0_psd_source_truth_audit.json `
  --output-parquet data\feature_diagnostics\phase0_psd_source_truth_audit.parquet
```

The script lists relevant S3 prefixes and reads parquet data only. It does not delete, overwrite, or move any S3 object.

## Verified Findings

### PSD

Current PSD raw/bronze/silver state is latest-bulk, not monthly vintage history:

- Raw PSD has the bulk release at `raw/production/source=usda_psd/release_type=bulk/release_date=2026-05-20/`.
- Bronze PSD has the matching release at `bronze/production/source=usda_psd/release_date=2026-05-20/`.
- Silver PSD is `silver/psd/part-000.parquet`.
- Silver PSD has one logical row per `(leviathan_slug, country, market_year)`.

Conclusion: current PSD can support point-in-time balance-sheet snapshot context, but it cannot support true month-over-month PSD revision features. The old name `psd_monthly_vintage_features` is retained only as a compatibility alias.

### WASDE

WASDE is the correct source for monthly official revision features in the current lake:

- Silver WASDE is partitioned by `release_date` under `silver/wasde/`.
- It includes `prior_estimate`, `revision`, `revision_direction`, and `prior_release_date`.
- It can be clipped by model snapshot date with `release_date <= as_of_date`.

Conclusion: snapshot/in-season model-ready matrices should use WASDE, not PSD, for actual monthly revision signal until PSD monthly archives are explicitly ingested.

## Resulting Design Adjustment

- Canonical PSD snapshot feature set: `psd_balance_sheet_snapshot`.
- Legacy PSD alias: `psd_monthly_vintage_features`.
- New WASDE snapshot feature set: `wasde_monthly_revision`.
- New combined model-ready feature set: `preseason_physical_plus_wasde_revision`.

The combined set is materialized in the model-ready builder because it unions annual static context with snapshot-date dynamic revision features.

## Phase 1 Revision

Phase 1 does not need to be rerun from scratch. Its pruning result remains useful: it proved current PSD monthly revision columns are empty or constant because the source lacks monthly release history.

The corrected next step is additive:

- keep the pruned PSD snapshot surface as a legacy compatibility artifact;
- build a new snapshot model-ready version using WASDE revision features;
- mark the older Phase 1 PSD-only snapshot version as legacy once the WASDE snapshot version is validated.

## Acceptance Criteria

- PSD monthly vintage terminology is no longer used as the canonical name for new snapshot feature sets.
- WASDE snapshot revision features are available in model-ready matrices.
- Existing annual PSD model-ready surfaces remain unchanged.
- No S3 cleanup or deletion is performed in this phase.
