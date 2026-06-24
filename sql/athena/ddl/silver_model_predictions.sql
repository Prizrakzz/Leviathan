-- GENERATED from configs/datasets/datasets.yaml; do not edit by hand.
-- dataset_id=silver_model_predictions
-- registry_sha256=fcc347a2e81b7b5fd3a6b6223801a375b77ec9819afa289ec9f7a1342d2cdce3
CREATE EXTERNAL TABLE IF NOT EXISTS `leviathan_dev`.`silver_model_predictions` (
    `country`         STRING,
    `crop_year`       INT,
    `y_actual`        DOUBLE,
    `y_pred`          FLOAT,
    `commodity`       STRING,
    `tier`            STRING,
    `target`          STRING,
    `model`           STRING,
    `feature_set_sha` STRING,
    `run_id`          STRING,
    `as_of_date`      STRING
)
PARTITIONED BY (`model_family` STRING, `prediction_date` STRING)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/model_predictions/'
TBLPROPERTIES (
    'parquet.compression' = 'SNAPPY',
    'projection.enabled' = 'true',
    'projection.model_family.type' = 'enum',
    'projection.model_family.values' = 'tier1_production,tier2_sd,tier3_spread,anomaly',
    'projection.prediction_date.format' = 'yyyy-MM-dd',
    'projection.prediction_date.range' = '2026-01-01,2035-12-31',
    'projection.prediction_date.type' = 'date',
    'storage.location.template' = 's3://leviathan-dev-shahem-001/silver/model_predictions/model_family=${model_family}/prediction_date=${prediction_date}/'
);
