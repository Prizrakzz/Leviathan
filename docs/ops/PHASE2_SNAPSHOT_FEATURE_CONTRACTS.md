# Phase 2 Snapshot Feature Contracts

Date: 2026-06-28

## Objective

Harden the PSD snapshot model-ready contract after the Phase 0 source-truth audit.

Phase 0 proved that current PSD silver is latest-bulk balance-sheet data, not archived monthly PSD release history. Phase 1 added WASDE snapshot revision features. Phase 2 makes that distinction enforceable in code and configs.

## Canonical Snapshot Feature Sets

Use these names for new snapshot experiments:

- `wasde_monthly_revision`: monthly official revision features from `silver/wasde/`, clipped by `release_date <= as_of_date`.
- `preseason_physical_plus_wasde_revision`: annual/static preseason physical context plus point-in-time WASDE revisions.
- `psd_balance_sheet_snapshot`: PSD balance-sheet snapshot context only. This is not a true monthly revision signal unless archived monthly PSD releases are ingested later.

## Legacy Aliases

These names remain backward-compatible but should not be used as defaults or future experiment-grid surfaces:

- `psd_monthly_vintage_features`
- `preseason_physical_plus_psd_vintage`

When explicitly requested, the model-ready builder records `snapshot_feature_set_contracts` entries marking them as `legacy_alias` and pointing at the canonical meaning.

## Enforced Rules

Snapshot model-ready builds now fail fast when:

- an unsupported snapshot feature-set id is requested;
- `wasde_monthly_revision` emits zero usable WASDE features;
- `preseason_physical_plus_wasde_revision` lacks either WASDE revision features or preseason physical features;
- `psd_balance_sheet_snapshot` emits zero usable PSD snapshot-context features.

The default snapshot feature set is now `wasde_monthly_revision`, because that is the current source-backed monthly official revision signal.

## What This Phase Does Not Do

- It does not submit training jobs.
- It does not start Phase 10.
- It does not rebuild Docker images.
- It does not delete, overwrite, or archive S3 data.
- It does not remove historical docs that mention earlier PSD-vintage experiments.

## Validation

Focused tests:

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests\unit\test_model_ready_psd_datasets.py `
  tests\unit\test_features_feature_sets.py `
  tests\unit\test_model_dataset_version_status.py `
  tests\unit\test_phase10_grid.py `
  tests\unit\test_psd_vintage_features.py
```

Grid dry-run:

```powershell
.\.venv\Scripts\python.exe jobs\submit\submit_batch_phase10_certification_grid.py `
  --include-hypotheses wasde_revision_signal `
  --permutation-trials 3 `
  --dry-run
```

The dry-run should resolve `psd_snd_anomaly_snapshot` to the active version:

```text
20260628T021248Z_phase0_wasde_snapshot
```

## Acceptance Criteria

- No active future experiment config references `psd_vintage_signal`.
- The Phase 10 grid references `wasde_revision_signal`.
- Snapshot builder defaults to `wasde_monthly_revision`.
- Legacy PSD-vintage aliases are explicit and annotated.
- Empty canonical feature sets fail before training.
