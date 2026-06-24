-- GENERATED from configs/datasets/datasets.yaml; do not edit by hand.
-- dataset_id=silver_icco_cocoa
-- registry_sha256=fcc347a2e81b7b5fd3a6b6223801a375b77ec9819afa289ec9f7a1342d2cdce3
CREATE EXTERNAL TABLE IF NOT EXISTS `leviathan_dev`.`silver_icco_cocoa` (
    `cocoa_year`          STRING,
    `latest_release_date` STRING,
    `production_kt`       DOUBLE,
    `grindings_kt`        DOUBLE,
    `end_stocks_kt`       DOUBLE,
    `surplus_deficit_kt`  DOUBLE,
    `su_ratio`            DOUBLE,
    `grindings_3yr_trend` DOUBLE,
    `grindings_trend_dev` DOUBLE,
    `source`              STRING
)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/icco_cocoa/'
TBLPROPERTIES (
    'parquet.compression' = 'SNAPPY'
);
