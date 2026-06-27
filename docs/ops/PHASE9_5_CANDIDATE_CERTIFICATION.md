# Phase 9.5 Candidate Certification

Phase 9.5 adds a promotion-safety gauntlet between exploratory MLflow runs and
Phase 10 model registration/promotion.

## What Changed

- Added honest extreme-outcome metric accounting:
  - `quintile_directional_accuracy`
  - `quintile_n_extreme_rows`
  - `quintile_n_extreme_independent_country_years`
  - `quintile_directional_accuracy_validated`
- Added candidate certification utilities:
  - leakage audit
  - baseline comparison
  - stress-year summary
  - leave-stress-year-out sensitivity
  - country-blocked validation
  - permutation sanity test
- Added a Batch task:
  - `jobs/batch/certify_model_candidate.py`
- Added a Batch submitter:
  - `jobs/submit/submit_batch_candidate_certification.py`
- Added a reproducible Batch job-definition registrar:
  - `jobs/utils/register_candidate_certification_jobdef.py`

## Why

The best Phase 9 corn candidate showed `1.0` quintile directional accuracy, but
that came from only 14 independent extreme country-years. Snapshot rows repeat
those same annual target observations across multiple stages, so raw row counts
can exaggerate evidence strength.

Phase 9.5 makes that visible before any model is registered.

## Current Dry-Run Finding

Dry-run candidate:

```text
commodity=corn_cbot
feature_set=preseason_physical_plus_psd_vintage
dataset_key=psd_snd_anomaly_snapshot
target_key=psd_production_anomaly_pct
model=lightgbm
cv_policy=expanding_post_2000
model_dataset_version=20260627T190257Z_1a042698_phase9_psd_snapshot_corn
```

Result:

```text
n_extreme_independent_country_years=14
leakage_audit=pass
promotion_gate=warn
recommendation=hold_for_more_validation
```

The candidate remains useful research signal, not a production champion.

## Commands

Register the certification job definition after rebuilding/pushing the trainer
image:

```powershell
.\.venv\Scripts\python.exe jobs\utils\register_candidate_certification_jobdef.py
```

Submit the current corn snapshot-vintage candidate:

```powershell
.\.venv\Scripts\python.exe jobs\submit\submit_batch_candidate_certification.py `
  --commodities corn_cbot `
  --feature-sets preseason_physical_plus_psd_vintage `
  --model-dataset-version 20260627T190257Z_1a042698_phase9_psd_snapshot_corn `
  --dataset-keys psd_snd_anomaly_snapshot `
  --target-keys psd_production_anomaly_pct `
  --models lightgbm `
  --cv-policies expanding_post_2000 `
  --permutation-trials 20
```

Report output:

```text
s3://leviathan-dev-shahem-001/model_artifacts/candidate_certification/candidate_id={candidate_id}/certification_report.json
```

## Phase 10 Entry Gate

Do not register or promote a candidate until:

- leakage audit has zero hard findings;
- permutation sanity test passes;
- independent extreme sample count is reported and reviewed;
- country-blocked diagnostics do not collapse;
- stress-year performance is not misleadingly weak;
- candidate either beats the best baseline on RMSE/MAE or clearly complements
  it on stress/extreme direction.
