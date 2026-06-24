-- GENERATED from configs/datasets/datasets.yaml; do not edit by hand.
-- dataset_id=silver_unica_corn_ethanol
-- registry_sha256=fcc347a2e81b7b5fd3a6b6223801a375b77ec9819afa289ec9f7a1342d2cdce3
CREATE EXTERNAL TABLE IF NOT EXISTS `leviathan_dev`.`silver_unica_corn_ethanol` (
    `harvest_year`           STRING,
    `fortnight_seq`          BIGINT,
    `fortnight_label`        STRING,
    `fortnight_date`         DATE,
    `anhydrous_quinzenal_kl` DOUBLE,
    `hydrous_quinzenal_kl`   DOUBLE,
    `total_quinzenal_kl`     DOUBLE,
    `anhydrous_accum_kl`     DOUBLE,
    `hydrous_accum_kl`       DOUBLE,
    `total_accum_kl`         DOUBLE,
    `source_idm`             STRING,
    `source_position_date`   STRING
)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/unica_corn_ethanol/'
TBLPROPERTIES (
    'parquet.compression' = 'SNAPPY'
);
