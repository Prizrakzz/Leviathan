# Phase 9 PSD Corn Experiment Completion

Date: 2026-06-27

## Summary

Phase 9 ran the first controlled PSD-first Batch training sweep for:

- Commodity: `corn_cbot`
- Dataset key: `psd_snd_anomaly`
- Target key: `psd_production_anomaly_pct`
- Target source: `psd`
- Feature set successfully tested: `preseason_physical`
- Models: `xgboost`, `lightgbm`
- CV policies: `expanding_full_history`, `expanding_post_2000`, `rolling_25y`

The valid six-job sweep succeeded after fixing a prediction-output key collision. The best run was:

```text
model=lightgbm
cv_policy=expanding_post_2000
rmse=0.3948
mae=0.3021
directional_accuracy=0.6765
quintile_directional_accuracy=1.0000
gaps_passed=True
folds=17
```

This is promising as a directional stress/extreme-outcome signal, but it is not yet a production candidate because it loses to the prior-year anomaly baseline on RMSE.

## Implementation Fix During Phase 9

The first successful preseason sweep revealed that prediction files were keyed only by:

```text
commodity__feature_set__dataset_key__target__model.parquet
```

That caused multiple CV-policy variants for the same model to overwrite one another.

The trainer now writes:

```text
commodity__feature_set__dataset_key__target__model__cv_policy.parquet
```

Updated files:

- `jobs/batch/train_commodity.py`
- `tests/unit/test_training_model_ready.py`
- `sql/athena/ddl/silver_model_predictions.sql`

Live Athena metadata for `leviathan_dev.silver_model_predictions` was also updated with metadata-only ALTER queries so PSD prediction families and richer trainer columns are queryable.

## Infrastructure Used

Trainer image rebuilt and pushed:

```text
668891723125.dkr.ecr.us-east-1.amazonaws.com/leviathan-dev-leviathan-trainer:latest
digest: sha256:2a102a1e99b86225d289df7fdf48622263a38e11f4fa8cf2f88d6ee88fb1c9c9
```

Batch job definition:

```text
leviathan-dev-train:9
arn:aws:batch:us-east-1:668891723125:job-definition/leviathan-dev-train:9
```

Experiment name:

```text
leviathan-psd-phase9-corn-production
```

## Initial 12-Job Grid Result

The originally planned grid included:

- `preseason_physical`
- `psd_monthly_vintage_features`

The six `preseason_physical` jobs succeeded.

The six `psd_monthly_vintage_features` jobs failed with:

```text
ValueError: unknown or empty feature set: psd_monthly_vintage_features
```

Root cause:

- The active source gold feature-set artifact does not contain `psd_monthly_vintage_features`.
- S3 has no `psd_snd_anomaly_snapshot` model-ready matrices yet.
- The active annual `psd_snd_anomaly` matrix for `corn_cbot` does not contain the `psd_production_*` monthly-vintage columns.

Decision:

- Do not rerun the monthly-vintage half until a snapshot/monthly-vintage model-ready dataset is explicitly built.
- Treat this as a valid Phase 9 finding, not a Batch failure.

## Successful Rerun Jobs

After the prediction key fix, the valid six-job preseason sweep was rerun.

| Model | CV Policy | Batch Job ID | Status | MLflow Run ID |
|---|---|---:|---|---|
| xgboost | expanding_full_history | `5b9c7f3e-67e4-4692-8057-60abc0e7995d` | succeeded | `50a45a06366d4bbda524d5878c201e70` |
| xgboost | expanding_post_2000 | `5e6eef9e-5ed1-4243-bbf2-e0bc726884b0` | succeeded | `b5d7f7e893194e33880db4658bd1f89c` |
| xgboost | rolling_25y | `379949c8-de7d-4b8f-ae1a-c73e9ff104b6` | succeeded | `423526e0e6fa44b28a473e26c1904bbf` |
| lightgbm | expanding_full_history | `d6a90b2f-a260-4649-9975-0ae03df941ee` | succeeded | `c9ef4189accd42fba6c94ada44a57a1e` |
| lightgbm | expanding_post_2000 | `8ff4bec7-0267-4e56-bcbc-c2e6f3680cfd` | succeeded | `37d6630c21694fc18605f8f819e5d6e3` |
| lightgbm | rolling_25y | `546cc18c-5329-4a00-8136-16772e1c9380` | succeeded | `5667994098cd42c6ac71112e363699c2` |

## Metrics

Trainer/MLflow metrics from CloudWatch logs:

| Model | CV Policy | Folds | RMSE | Directional Accuracy | Quintile Directional Accuracy | Gaps Passed |
|---|---|---:|---:|---:|---:|---|
| lightgbm | expanding_post_2000 | 17 | 0.3948 | 0.6765 | 1.0000 | true |
| xgboost | expanding_post_2000 | 17 | 0.6185 | 0.6176 | 1.0000 | false |
| lightgbm | rolling_25y | 36 | 1.1285 | 0.6644 | 0.8970 | false |
| xgboost | expanding_full_history | 36 | 1.1507 | 0.6134 | 0.8970 | false |
| lightgbm | expanding_full_history | 36 | 1.1616 | 0.6505 | 0.8620 | false |
| xgboost | rolling_25y | 36 | 1.1648 | 0.6481 | 0.8970 | true |

Baseline comparison from the prediction parquets:

| Model | CV Policy | Rows | Countries | Years | RMSE | MAE | Best Baseline | Best Baseline RMSE | RMSE Delta vs Best |
|---|---|---:|---:|---|---:|---:|---|---:|---:|
| lightgbm | expanding_post_2000 | 68 | 4 | 2010-2026 | 0.3948 | 0.3021 | prior_year_anomaly | 0.2959 | +0.0989 |
| xgboost | expanding_post_2000 | 68 | 4 | 2010-2026 | 0.6185 | 0.4315 | prior_year_anomaly | 0.2959 | +0.3225 |
| lightgbm | rolling_25y | 143 | 4 | 1991-2026 | 1.1285 | 0.5448 | prior_year_anomaly | 0.8220 | +0.3065 |
| xgboost | expanding_full_history | 143 | 4 | 1991-2026 | 1.1507 | 0.4863 | prior_year_anomaly | 0.8220 | +0.3287 |
| lightgbm | expanding_full_history | 143 | 4 | 1991-2026 | 1.1616 | 0.5681 | prior_year_anomaly | 0.8220 | +0.3396 |
| xgboost | rolling_25y | 143 | 4 | 1991-2026 | 1.1648 | 0.4992 | prior_year_anomaly | 0.8220 | +0.3428 |

Interpretation:

- `lightgbm + expanding_post_2000` is the best experimental candidate from this grid.
- The result is useful but not production-ready.
- The model is good at extreme sign direction on this sample.
- The prior-year anomaly baseline is still better on RMSE, so promotion would be premature.

## Prediction Artifacts

Valid Phase 9 CV-suffixed prediction files:

```text
s3://leviathan-dev-shahem-001/silver/model_predictions/model_family=psd_production_anomaly/prediction_date=2026-06-27/corn_cbot__preseason_physical__psd_snd_anomaly__psd_production_anomaly_pct__lightgbm__expanding_full_history.parquet
s3://leviathan-dev-shahem-001/silver/model_predictions/model_family=psd_production_anomaly/prediction_date=2026-06-27/corn_cbot__preseason_physical__psd_snd_anomaly__psd_production_anomaly_pct__lightgbm__expanding_post_2000.parquet
s3://leviathan-dev-shahem-001/silver/model_predictions/model_family=psd_production_anomaly/prediction_date=2026-06-27/corn_cbot__preseason_physical__psd_snd_anomaly__psd_production_anomaly_pct__lightgbm__rolling_25y.parquet
s3://leviathan-dev-shahem-001/silver/model_predictions/model_family=psd_production_anomaly/prediction_date=2026-06-27/corn_cbot__preseason_physical__psd_snd_anomaly__psd_production_anomaly_pct__xgboost__expanding_full_history.parquet
s3://leviathan-dev-shahem-001/silver/model_predictions/model_family=psd_production_anomaly/prediction_date=2026-06-27/corn_cbot__preseason_physical__psd_snd_anomaly__psd_production_anomaly_pct__xgboost__expanding_post_2000.parquet
s3://leviathan-dev-shahem-001/silver/model_predictions/model_family=psd_production_anomaly/prediction_date=2026-06-27/corn_cbot__preseason_physical__psd_snd_anomaly__psd_production_anomaly_pct__xgboost__rolling_25y.parquet
```

Older no-CV files from the pre-fix run still exist under the same prediction date. They were not deleted. Ignore them for Phase 9 analysis:

```text
...__lightgbm.parquet
...__xgboost.parquet
```

Athena verification for the CV-suffixed files returned:

```text
lightgbm expanding_full_history 143 rows
lightgbm expanding_post_2000     68 rows
lightgbm rolling_25y            143 rows
xgboost  expanding_full_history 143 rows
xgboost  expanding_post_2000     68 rows
xgboost  rolling_25y            143 rows
```

## Training Snapshot Artifacts

Each successful run wrote one training snapshot under:

```text
s3://leviathan-dev-shahem-001/model_artifacts/training_snapshots/{mlflow_run_id}/
```

All six run IDs had a snapshot parquet present.

## Validation

Focused regression:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\unit\test_training_model_ready.py
```

Result:

```text
10 passed
```

Full suite:

```powershell
.\.venv\Scripts\python.exe -m pytest tests
```

Result:

```text
1277 passed
```

Athena metadata update:

```text
ALTER TABLE leviathan_dev.silver_model_predictions REPLACE COLUMNS ... SUCCEEDED
ALTER TABLE leviathan_dev.silver_model_predictions SET TBLPROPERTIES ... SUCCEEDED
```

## Promotion Decision

No model should be promoted from this phase.

Reason:

- Best model has good extreme-direction performance.
- Best model does not beat the prior-year anomaly baseline on RMSE.
- Monthly-vintage feature experiments are blocked until the snapshot model-ready dataset exists.
- Only one commodity and one target were tested.

## Next

Phase 9 is complete as a controlled smoke and first research readout.

Recommended next step:

1. Build a real snapshot/monthly-vintage model-ready dataset if we want `psd_monthly_vintage_features` in the experiment grid.
2. Rerun corn with:
   - `preseason_physical`
   - `psd_monthly_vintage_features`
   - potentially a combined physical + vintage feature set
3. Keep `lightgbm + expanding_post_2000` as the first benchmark candidate, not a champion.
4. Do not promote until a candidate beats or clearly complements the prior-year anomaly baseline under the acceptance gates.
