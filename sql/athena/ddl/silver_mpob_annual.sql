-- GENERATED from configs/datasets/datasets.yaml; do not edit by hand.
-- dataset_id=silver_mpob_annual
-- registry_sha256=fcc347a2e81b7b5fd3a6b6223801a375b77ec9819afa289ec9f7a1342d2cdce3
CREATE EXTERNAL TABLE IF NOT EXISTS `leviathan_dev`.`silver_mpob_annual` (
    `year`                       BIGINT,
    `production_cpo_mt`          DOUBLE,
    `closing_stocks_palm_oil_mt` DOUBLE,
    `exports_palm_oil_mt`        DOUBLE,
    `imports_palm_oil_mt`        DOUBLE,
    `ffb_price_myr_per_mt`       DOUBLE,
    `su_ratio`                   DOUBLE,
    `source`                     STRING,
    `commodity`                  STRING
)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/mpob_annual/'
TBLPROPERTIES (
    'parquet.compression' = 'SNAPPY'
);
