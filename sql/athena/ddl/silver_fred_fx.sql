-- GENERATED from configs/datasets/datasets.yaml; do not edit by hand.
-- dataset_id=silver_fred_fx
-- registry_sha256=fcc347a2e81b7b5fd3a6b6223801a375b77ec9819afa289ec9f7a1342d2cdce3
CREATE EXTERNAL TABLE IF NOT EXISTS `leviathan_dev`.`silver_fred_fx` (
    `date`                   STRING,
    `brl_usd`                DOUBLE,
    `brl_usd_pct_change_90d` DOUBLE,
    `ars_usd`                DOUBLE,
    `ars_usd_pct_change_90d` DOUBLE,
    `cny_usd`                DOUBLE,
    `cny_usd_pct_change_90d` DOUBLE,
    `source`                 STRING
)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/fred_fx/'
TBLPROPERTIES (
    'parquet.compression' = 'SNAPPY'
);
