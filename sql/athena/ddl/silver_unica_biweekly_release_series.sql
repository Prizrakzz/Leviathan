-- GENERATED from configs/datasets/datasets.yaml; do not edit by hand.
-- dataset_id=silver_unica_biweekly_release_series
-- registry_sha256=fcc347a2e81b7b5fd3a6b6223801a375b77ec9819afa289ec9f7a1342d2cdce3
CREATE EXTERNAL TABLE IF NOT EXISTS `leviathan_dev`.`silver_unica_biweekly_release_series` (
    `harvest_year`                 STRING,
    `position_date`                STRING,
    `region`                       STRING,
    `cane_crushed_current_t`       DOUBLE,
    `cane_crushed_prior_t`         DOUBLE,
    `sugar_produced_current_t`     DOUBLE,
    `sugar_produced_prior_t`       DOUBLE,
    `ethanol_total_current_m3`     DOUBLE,
    `ethanol_total_prior_m3`       DOUBLE,
    `ethanol_anhydrous_current_m3` DOUBLE,
    `ethanol_anhydrous_prior_m3`   DOUBLE,
    `ethanol_hydrous_current_m3`   DOUBLE,
    `ethanol_hydrous_prior_m3`     DOUBLE
)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/unica_biweekly_release_series/'
TBLPROPERTIES (
    'parquet.compression' = 'SNAPPY'
);
