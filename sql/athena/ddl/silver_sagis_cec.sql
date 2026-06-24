-- GENERATED from configs/datasets/datasets.yaml; do not edit by hand.
-- dataset_id=silver_sagis_cec
-- registry_sha256=fcc347a2e81b7b5fd3a6b6223801a375b77ec9819afa289ec9f7a1342d2cdce3
CREATE EXTERNAL TABLE IF NOT EXISTS `leviathan_dev`.`silver_sagis_cec` (
    `production_year`    BIGINT,
    `report_month`       BIGINT,
    `release_date`       STRING,
    `season_type`        STRING,
    `crop`               STRING,
    `scope`              STRING,
    `estimate_number`    BIGINT,
    `area_planted_ha`    DOUBLE,
    `current_estimate_t` DOUBLE,
    `prior_estimate_t`   DOUBLE,
    `prior_year_final_t` DOUBLE,
    `revision_t`         DOUBLE,
    `revision_pct`       DOUBLE,
    `revision_surprise`  DOUBLE,
    `source`             STRING
)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/sagis_cec/'
TBLPROPERTIES (
    'parquet.compression' = 'SNAPPY'
);
