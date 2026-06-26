-- Baseline metrics for model-ready target datasets.
CREATE EXTERNAL TABLE IF NOT EXISTS gold_model_ready_baselines (
    dataset_key            string,
    commodity              string,
    target_key             string,
    baseline_name          string,
    n_rows                 bigint,
    rmse                   double,
    mae                    double,
    directional_accuracy   double
)
PARTITIONED BY (dataset_version string)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/gold/model_ready_baselines/'
TBLPROPERTIES (
    'parquet.compression' = 'SNAPPY',
    'projection.enabled' = 'true',
    'projection.dataset_version.type' = 'injected',
    'storage.location.template' = 's3://leviathan-dev-shahem-001/gold/model_ready_baselines/dataset_version=${dataset_version}/'
);
