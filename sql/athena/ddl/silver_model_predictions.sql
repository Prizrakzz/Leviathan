-- GENERATED from live Glue table leviathan_dev.silver_model_predictions; keep in sync with the S3 layout.
CREATE EXTERNAL TABLE IF NOT EXISTS silver_model_predictions (
    country         string,
    crop_year       bigint,
    snapshot_stage  string,
    snapshot_policy string,
    y_actual        double,
    y_pred          double,
    zero_anomaly_baseline double,
    prior_year_anomaly_baseline double,
    trailing_mean_anomaly_baseline double,
    trailing_trend_anomaly_baseline double,
    commodity       string,
    tier            string,
    feature_set_id  string,
    target          string,
    dataset_key     string,
    target_key      string,
    model_dataset_version string,
    source_dataset_version string,
    model           string,
    cv_policy       string,
    feature_set_sha string,
    run_id          string,
    as_of_date      string,
    prediction_as_of_date string
)
PARTITIONED BY (model_family string, prediction_date string)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/model_predictions'
-- REGISTERED partitions since 2026-07 — DO NOT re-add partition projection. The projected
-- family x daily-date grid (~29K candidates over a handful of real prediction runs, ~4,800x) is the
-- Jul-2026 S3 LIST-storm class; feature-engineering queries over prediction history would re-fire it.
-- train_commodity._write_predictions registers each new partition via
-- leviathan.storage.glue_partitions.ensure_partition. After a DROP+CREATE from this DDL, re-register:
--   python jobs/utils/deproject_glue_table.py --register --tables silver_model_predictions
TBLPROPERTIES (
    'EXTERNAL' = 'TRUE',
    'parquet.compression' = 'SNAPPY'
);
