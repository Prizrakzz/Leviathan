-- GENERATED from configs/datasets/datasets.yaml; do not edit by hand.
-- dataset_id=silver_futures_prices
-- registry_sha256=fcc347a2e81b7b5fd3a6b6223801a375b77ec9819afa289ec9f7a1342d2cdce3
CREATE EXTERNAL TABLE IF NOT EXISTS `leviathan_dev`.`silver_futures_prices` (
    `date`             TIMESTAMP,
    `leviathan_slug`   STRING,
    `close`            FLOAT,
    `log_return`       FLOAT,
    `price_z_2yr`      FLOAT,
    `realized_vol_30d` FLOAT,
    `momentum_60d`     FLOAT,
    `momentum_1yr`     FLOAT,
    `vol_regime`       TINYINT,
    `source`           STRING
)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/futures_prices/'
TBLPROPERTIES (
    'parquet.compression' = 'SNAPPY'
);
