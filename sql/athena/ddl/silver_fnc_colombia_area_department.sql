-- GENERATED from configs/datasets/datasets.yaml; do not edit by hand.
-- dataset_id=silver_fnc_colombia_area_department
-- registry_sha256=fcc347a2e81b7b5fd3a6b6223801a375b77ec9819afa289ec9f7a1342d2cdce3
CREATE EXTERNAL TABLE IF NOT EXISTS `leviathan_dev`.`silver_fnc_colombia_area_department` (
    `leviathan_slug` STRING,
    `country`        STRING,
    `department`     STRING,
    `department_raw` STRING,
    `area_ha`        DOUBLE,
    `source`         STRING
)
PARTITIONED BY (`commodity` STRING, `year` INT)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/fnc_colombia/area_department/'
TBLPROPERTIES (
    'parquet.compression' = 'SNAPPY',
    'projection.commodity.type' = 'enum',
    'projection.commodity.values' = 'arabica_coffee',
    'projection.enabled' = 'true',
    'projection.year.range' = '2002,2035',
    'projection.year.type' = 'integer',
    'storage.location.template' = 's3://leviathan-dev-shahem-001/silver/fnc_colombia/area_department/commodity=${commodity}/year=${year}'
);
