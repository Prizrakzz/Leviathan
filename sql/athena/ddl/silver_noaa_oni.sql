-- GENERATED from configs/datasets/datasets.yaml; do not edit by hand.
-- dataset_id=silver_noaa_oni
-- registry_sha256=fcc347a2e81b7b5fd3a6b6223801a375b77ec9819afa289ec9f7a1342d2cdce3
CREATE EXTERNAL TABLE IF NOT EXISTS `leviathan_dev`.`silver_noaa_oni` (
    `year`                   BIGINT,
    `month`                  BIGINT,
    `season`                 STRING,
    `oni_anom`               DOUBLE,
    `phase`                  STRING,
    `oni_lag3`               DOUBLE,
    `oni_lag6`               DOUBLE,
    `oni_lag9`               DOUBLE,
    `oni_lag12`              DOUBLE,
    `el_nino_flag`           TINYINT,
    `la_nina_flag`           TINYINT,
    `la_nina_brazil_flag`    TINYINT,
    `argentina_la_nina_flag` TINYINT,
    `source`                 STRING
)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/weather/source=noaa_oni/'
TBLPROPERTIES (
    'parquet.compression' = 'SNAPPY'
);
