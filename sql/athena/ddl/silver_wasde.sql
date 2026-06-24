-- GENERATED from configs/datasets/datasets.yaml; do not edit by hand.
-- dataset_id=silver_wasde
-- registry_sha256=fcc347a2e81b7b5fd3a6b6223801a375b77ec9819afa289ec9f7a1342d2cdce3
CREATE EXTERNAL TABLE IF NOT EXISTS `leviathan_dev`.`silver_wasde` (
    `commodity`                    STRING,
    `table_type`                   STRING,
    `region`                       STRING,
    `marketing_year`               STRING,
    `attribute`                    STRING,
    `unit`                         STRING,
    `estimate`                     DOUBLE,
    `prior_release_date`           STRING,
    `prior_estimate`               DOUBLE,
    `revision`                     DOUBLE,
    `revision_direction`           STRING,
    `months_to_marketing_year_end` INT,
    `is_first_estimate`            BOOLEAN,
    `is_final_or_latest`           BOOLEAN,
    `raw_table_name`               STRING,
    `raw_region`                   STRING,
    `raw_attribute`                STRING,
    `raw_status`                   STRING,
    `raw_projection_month`         STRING,
    `source`                       STRING
)
PARTITIONED BY (`release_date` STRING)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/wasde/'
TBLPROPERTIES (
    'parquet.compression' = 'SNAPPY',
    'projection.enabled' = 'true',
    'projection.release_date.format' = 'yyyy-MM-dd',
    'projection.release_date.interval' = '1',
    'projection.release_date.interval.unit' = 'DAYS',
    'projection.release_date.range' = '1973-01-01,NOW',
    'projection.release_date.type' = 'date',
    'storage.location.template' = 's3://leviathan-dev-shahem-001/silver/wasde/release_date=${release_date}'
);
