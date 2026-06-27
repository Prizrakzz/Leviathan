# Phase 10 Candidate Certification Grid

Phase 10 is a certification and hypothesis-testing phase, not a promotion phase.
The default grid lives in:

```text
configs/ml/phase10_candidate_grid.yaml
```

It tests the current corn PSD production-anomaly setup against three hypotheses:

- `baseline_hardening_reference`: freeze the current reference candidate.
- `psd_vintage_signal`: compare monthly PSD vintage-only vs preseason plus PSD vintage features.
- `annual_static_feature_ablation`: compare annual static feature families.
- `cv_policy_sensitivity`: check the reference candidate under a rolling window.

The jobs use the existing Batch job definition:

```text
leviathan-dev-certify-model-candidate
```

## Dry Run

```powershell
python jobs/submit/submit_batch_phase10_certification_grid.py `
  --include-hypotheses baseline_hardening_reference `
  --dry-run
```

## Smoke Submit

```powershell
python jobs/submit/submit_batch_phase10_certification_grid.py `
  --include-hypotheses baseline_hardening_reference `
  --permutation-trials 5
```

## Controlled Grid Submit

```powershell
python jobs/submit/submit_batch_phase10_certification_grid.py `
  --include-hypotheses psd_vintage_signal `
  --permutation-trials 20 `
  --max-jobs 10
```

Use `--max-jobs` for staged execution. Do not launch the full grid until the
smoke candidate successfully writes a certification report.

## Summarize Reports

```powershell
python jobs/utils/summarize_candidate_certification_reports.py `
  --output-local data/phase10/candidate_ranking.parquet
```

Optional S3 output:

```powershell
python jobs/utils/summarize_candidate_certification_reports.py `
  --output-s3-key auto
```

## Promotion Rule

Do not register a model from a broad sweep. A candidate must be frozen and rerun
with the full certification gauntlet before `mlflow.register_model` is allowed.
At minimum, the final report must show:

- leakage audit passed;
- permutation sanity passed;
- baseline comparison is acceptable;
- country-blocked and stress-year diagnostics do not collapse;
- bad-year/tail metrics have enough independent country-year evidence;
- feature importance has been reviewed separately for economic sense.
