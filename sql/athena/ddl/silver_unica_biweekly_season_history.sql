-- GENERATED from configs/datasets/datasets.yaml; do not edit by hand.
-- dataset_id=silver_unica_biweekly_season_history
-- registry_sha256=fcc347a2e81b7b5fd3a6b6223801a375b77ec9819afa289ec9f7a1342d2cdce3
CREATE EXTERNAL TABLE IF NOT EXISTS `leviathan_dev`.`silver_unica_biweekly_season_history` (
    `harvest_year`         STRING,
    `fortnight_seq`        BIGINT,
    `fortnight_label`      STRING,
    `fortnight_date`       DATE,
    `region`               STRING,
    `cane_crushed_t`       DOUBLE,
    `sugar_produced_t`     DOUBLE,
    `ethanol_total_m3`     DOUBLE,
    `ethanol_anhydrous_m3` DOUBLE,
    `ethanol_hydrous_m3`   DOUBLE,
    `source_idm`           STRING,
    `source_position_date` STRING
)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/unica_biweekly_season_history/'
TBLPROPERTIES (
    'parquet.compression' = 'SNAPPY'
);
