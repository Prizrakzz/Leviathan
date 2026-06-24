-- GENERATED from configs/datasets/datasets.yaml; do not edit by hand.
-- dataset_id=silver_psd
-- registry_sha256=fcc347a2e81b7b5fd3a6b6223801a375b77ec9819afa289ec9f7a1342d2cdce3
CREATE EXTERNAL TABLE IF NOT EXISTS `leviathan_dev`.`silver_psd` (
    `leviathan_slug`            STRING,
    `country`                   STRING,
    `market_year`               SMALLINT,
    `wasde_release_month`       TINYINT,
    `release_date`              STRING,
    `beginning_stocks_mt`       DOUBLE,
    `production_mt`             DOUBLE,
    `imports_mt`                DOUBLE,
    `exports_mt`                DOUBLE,
    `ending_stocks_mt`          DOUBLE,
    `consumption_mt`            DOUBLE,
    `area_harvested_1000ha`     DOUBLE,
    `yield_mt_ha`               DOUBLE,
    `su_ratio`                  DOUBLE,
    `su_ratio_yoy_delta`        DOUBLE,
    `production_mt_revision`    DOUBLE,
    `ending_stocks_mt_revision` DOUBLE,
    `consumption_mt_revision`   DOUBLE
)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/psd/'
TBLPROPERTIES (
    'parquet.compression' = 'SNAPPY'
);
