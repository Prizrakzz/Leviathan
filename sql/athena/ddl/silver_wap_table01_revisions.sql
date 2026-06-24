-- GENERATED from configs/datasets/datasets.yaml; do not edit by hand.
-- dataset_id=silver_wap_table01_revisions
-- registry_sha256=fcc347a2e81b7b5fd3a6b6223801a375b77ec9819afa289ec9f7a1342d2cdce3
CREATE EXTERNAL TABLE IF NOT EXISTS `leviathan_dev`.`silver_wap_table01_revisions` (
    `release_month`       STRING,
    `commodity`           STRING,
    `row_label`           STRING,
    `marketing_year`      STRING,
    `vintage_type`        STRING,
    `vintage_status`      STRING,
    `month_abbr`          STRING,
    `country`             STRING,
    `value_mmt`           DOUBLE,
    `prior_release_month` STRING,
    `prior_value_mmt`     DOUBLE,
    `revision_mmt`        DOUBLE
)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/wap_table01_revisions/'
TBLPROPERTIES (
    'parquet.compression' = 'SNAPPY'
);
