-- GENERATED from configs/datasets/datasets.yaml; do not edit by hand.
-- dataset_id=silver_mpoc_exports_by_country
-- registry_sha256=fcc347a2e81b7b5fd3a6b6223801a375b77ec9819afa289ec9f7a1342d2cdce3
CREATE EXTERNAL TABLE IF NOT EXISTS `leviathan_dev`.`silver_mpoc_exports_by_country` (
    `year`       BIGINT,
    `country`    STRING,
    `exports_mt` DOUBLE,
    `source`     STRING
)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/mpoc_exports_by_country/'
TBLPROPERTIES (
    'parquet.compression' = 'SNAPPY'
);
