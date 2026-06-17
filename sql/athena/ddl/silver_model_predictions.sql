-- Model predictions — one row per (model run, country, crop_year).
-- Written by jobs/batch/train_commodity.py.  Lets you SQL walk-forward
-- predictions alongside the MLflow run metrics, and trace any prediction back to
-- the exact feature set (feature_set_sha) and MLflow run (run_id).
CREATE EXTERNAL TABLE IF NOT EXISTS silver_model_predictions (
    commodity         string,
    country           string,
    crop_year         int,
    y_actual          double,
    y_pred            double,
    tier              string,
    target            string,
    model             string,
    feature_set_sha   string,
    run_id            string,
    as_of_date        string
)
PARTITIONED BY (model_family string, prediction_date string)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/model_predictions/'
TBLPROPERTIES (
    'parquet.compression' = 'SNAPPY',
    'projection.enabled' = 'true',
    'projection.model_family.type' = 'enum',
    'projection.model_family.values' = 'tier1_production,tier2_sd,tier3_spread,anomaly',
    'projection.prediction_date.type' = 'date',
    'projection.prediction_date.format' = 'yyyy-MM-dd',
    'projection.prediction_date.range' = '2026-01-01,2030-12-31',
    'storage.location.template' =
        's3://leviathan-dev-shahem-001/silver/model_predictions/model_family=${model_family}/prediction_date=${prediction_date}/'
);
