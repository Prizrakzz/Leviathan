-- GENERATED from configs/datasets/datasets.yaml; do not edit by hand.
-- dataset_id=silver_nass_citrus
-- registry_sha256=fcc347a2e81b7b5fd3a6b6223801a375b77ec9819afa289ec9f7a1342d2cdce3
CREATE EXTERNAL TABLE IF NOT EXISTS `leviathan_dev`.`silver_nass_citrus` (
    `season`              STRING,
    `release_date`        STRING,
    `report_month`        BIGINT,
    `crop`                STRING,
    `state`               STRING,
    `forecast_1000_boxes` DOUBLE,
    `revision_1000_boxes` DOUBLE,
    `hlb_trend_factor`    DOUBLE,
    `source`              STRING
)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/nass_citrus/'
TBLPROPERTIES (
    'parquet.compression' = 'SNAPPY'
);
