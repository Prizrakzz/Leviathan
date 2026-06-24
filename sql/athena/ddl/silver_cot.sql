-- GENERATED from configs/datasets/datasets.yaml; do not edit by hand.
-- dataset_id=silver_cot
-- registry_sha256=fcc347a2e81b7b5fd3a6b6223801a375b77ec9819afa289ec9f7a1342d2cdce3
CREATE EXTERNAL TABLE IF NOT EXISTS `leviathan_dev`.`silver_cot` (
    `report_date`     STRING,
    `leviathan_slug`  STRING,
    `open_interest`   BIGINT,
    `mm_long`         BIGINT,
    `mm_short`        BIGINT,
    `mm_spread`       BIGINT,
    `mm_net`          BIGINT,
    `mm_pct_oi`       DOUBLE,
    `mm_net_z_3yr`    DOUBLE,
    `mm_pct_oi_z_3yr` DOUBLE,
    `source`          STRING
)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/cot/'
TBLPROPERTIES (
    'parquet.compression' = 'SNAPPY'
);
