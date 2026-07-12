-- silver_model_predictions - model_output silver table (generated); SILVER-F011 registry-generated DDL.
--
-- GENERATED from the SILVER-F010 registry (configs/silver/tables/silver_model_predictions.yaml) by
-- leviathan.silver.ddl -- this RETIRES the first-parquet schema inference. Do NOT
-- hand-edit; re-run:  python scripts/silver/generate_ddls_from_registry.py --write
-- partition_mode = registered. recovery: get-partitions reconcile + explicit per-partition locations (ESR as_of=/as_of_date mapping; never MSCK)
--
-- REGISTERED partitions -- DO NOT re-add partition projection. The projected grid is
-- the Jul-2026 S3 LIST-storm class ($134/2 days); partitions carry explicit Glue
-- locations (MSCK cannot repair them). After a DROP+CREATE from this DDL, re-register:
--     python jobs/utils/deproject_glue_table.py --register --tables silver_model_predictions
CREATE EXTERNAL TABLE IF NOT EXISTS silver_model_predictions (
    country                         string,
    crop_year                       bigint,
    snapshot_stage                  string,
    snapshot_policy                 string,
    y_actual                        double,
    y_pred                          double,
    zero_anomaly_baseline           double,
    prior_year_anomaly_baseline     double,
    trailing_mean_anomaly_baseline  double,
    trailing_trend_anomaly_baseline double,
    commodity                       string,
    tier                            string,
    feature_set_id                  string,
    target                          string,
    dataset_key                     string,
    target_key                      string,
    model_dataset_version           string,
    source_dataset_version          string,
    model                           string,
    cv_policy                       string,
    feature_set_sha                 string,
    run_id                          string,
    as_of_date                      string,
    prediction_as_of_date           string
)
PARTITIONED BY (model_family string, prediction_date string)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/model_predictions/'
TBLPROPERTIES (
    'EXTERNAL' = 'TRUE',
    'parquet.compression' = 'SNAPPY'
);
