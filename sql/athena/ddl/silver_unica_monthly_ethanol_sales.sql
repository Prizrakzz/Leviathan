-- GENERATED from configs/datasets/datasets.yaml; do not edit by hand.
-- dataset_id=silver_unica_monthly_ethanol_sales
-- registry_sha256=fcc347a2e81b7b5fd3a6b6223801a375b77ec9819afa289ec9f7a1342d2cdce3
CREATE EXTERNAL TABLE IF NOT EXISTS `leviathan_dev`.`silver_unica_monthly_ethanol_sales` (
    `harvest_year`         STRING,
    `month_num`            BIGINT,
    `month_label`          STRING,
    `month_date`           STRING,
    `is_partial`           BOOLEAN,
    `total_current_m3`     DOUBLE,
    `total_prior_m3`       DOUBLE,
    `external_current_m3`  DOUBLE,
    `external_prior_m3`    DOUBLE,
    `internal_current_m3`  DOUBLE,
    `internal_prior_m3`    DOUBLE,
    `source_idm`           STRING,
    `source_position_date` STRING
)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/unica_monthly_ethanol_sales/'
TBLPROPERTIES (
    'parquet.compression' = 'SNAPPY'
);
