-- GENERATED from configs/datasets/datasets.yaml; do not edit by hand.
-- dataset_id=silver_mpoc_trade_stats_monthly
-- registry_sha256=fcc347a2e81b7b5fd3a6b6223801a375b77ec9819afa289ec9f7a1342d2cdce3
CREATE EXTERNAL TABLE IF NOT EXISTS `leviathan_dev`.`silver_mpoc_trade_stats_monthly` (
    `year`       BIGINT,
    `month`      BIGINT,
    `exports_mt` DOUBLE,
    `imports_mt` DOUBLE,
    `source`     STRING
)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/mpoc_trade_stats_monthly/'
TBLPROPERTIES (
    'parquet.compression' = 'SNAPPY'
);
