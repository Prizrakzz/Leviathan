-- GENERATED from configs/datasets/datasets.yaml; do not edit by hand.
-- dataset_id=silver_food_cpi
-- registry_sha256=fcc347a2e81b7b5fd3a6b6223801a375b77ec9819afa289ec9f7a1342d2cdce3
CREATE EXTERNAL TABLE IF NOT EXISTS `leviathan_dev`.`silver_food_cpi` (
    `country_iso`    STRING,
    `country_name`   STRING,
    `year`           BIGINT,
    `cpi_yoy_pct`    FLOAT,
    `cpi_yoy_z_5yr`  FLOAT,
    `cpi_yoy_z_10yr` FLOAT,
    `cpi_available`  TINYINT,
    `source`         STRING
)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/food_cpi/'
TBLPROPERTIES (
    'parquet.compression' = 'SNAPPY'
);
