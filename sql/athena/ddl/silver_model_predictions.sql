-- GENERATED from live Glue table leviathan_dev.silver_model_predictions; keep in sync with the S3 layout.
CREATE EXTERNAL TABLE IF NOT EXISTS silver_model_predictions (
    country         string,
    crop_year       int,
    y_actual        double,
    y_pred          float,
    commodity       string,
    tier            string,
    target          string,
    model           string,
    feature_set_sha string,
    run_id          string,
    as_of_date      string
)
PARTITIONED BY (model_family string, prediction_date string)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/model_predictions'
TBLPROPERTIES (
    'EXTERNAL' = 'TRUE',
    'parquet.compression' = 'SNAPPY',
    'projection.enabled' = 'true',
    'projection.model_family.type' = 'enum',
    'projection.model_family.values' = 'tier1_production,tier2_sd,tier3_spread,anomaly',
    'projection.prediction_date.format' = 'yyyy-MM-dd',
    'projection.prediction_date.range' = '2026-01-01,2035-12-31',
    'projection.prediction_date.type' = 'date',
    'storage.location.template' = 's3://leviathan-dev-shahem-001/silver/model_predictions/model_family=${model_family}/prediction_date=${prediction_date}/'
);
