-- GENERATED from configs/datasets/datasets.yaml; do not edit by hand.
-- dataset_id=silver_sagis_weekly_exports
-- registry_sha256=fcc347a2e81b7b5fd3a6b6223801a375b77ec9819afa289ec9f7a1342d2cdce3
CREATE EXTERNAL TABLE IF NOT EXISTS `leviathan_dev`.`silver_sagis_weekly_exports` (
    `season`          STRING,
    `crop`            STRING,
    `week_number`     BIGINT,
    `week_ending`     STRING,
    `prog_exports_mt` DOUBLE,
    `pct_of_prior_yr` DOUBLE,
    `z_vs_3yr_avg`    DOUBLE,
    `source`          STRING
)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/sagis_weekly_exports/'
TBLPROPERTIES (
    'parquet.compression' = 'SNAPPY'
);
