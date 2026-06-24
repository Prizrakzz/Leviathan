-- GENERATED from configs/datasets/datasets.yaml; do not edit by hand.
-- dataset_id=silver_unica_annual_state
-- registry_sha256=fcc347a2e81b7b5fd3a6b6223801a375b77ec9819afa289ec9f7a1342d2cdce3
CREATE EXTERNAL TABLE IF NOT EXISTS `leviathan_dev`.`silver_unica_annual_state` (
    `harvest_year`         STRING,
    `state_region`         STRING,
    `cane_crushed_t`       BIGINT,
    `sugar_produced_t`     BIGINT,
    `ethanol_total_m3`     BIGINT,
    `ethanol_hydrous_m3`   BIGINT,
    `ethanol_anhydrous_m3` DOUBLE,
    `source`               STRING
)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/unica_annual_state/'
TBLPROPERTIES (
    'parquet.compression' = 'SNAPPY'
);
