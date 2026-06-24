-- GENERATED from configs/datasets/datasets.yaml; do not edit by hand.
-- dataset_id=silver_fnc_colombia_exports_port_type
-- registry_sha256=fcc347a2e81b7b5fd3a6b6223801a375b77ec9819afa289ec9f7a1342d2cdce3
CREATE EXTERNAL TABLE IF NOT EXISTS `leviathan_dev`.`silver_fnc_colombia_exports_port_type` (
    `leviathan_slug`    STRING,
    `country`           STRING,
    `month`             BIGINT,
    `date`              DATE,
    `port`              STRING,
    `port_raw`          STRING,
    `coffee_type`       STRING,
    `coffee_type_raw`   STRING,
    `exports_bags_60kg` DOUBLE,
    `exports_value_usd` DOUBLE,
    `source`            STRING
)
PARTITIONED BY (`commodity` STRING, `year` INT)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/fnc_colombia/exports_port_type/'
TBLPROPERTIES (
    'parquet.compression' = 'SNAPPY',
    'projection.commodity.type' = 'enum',
    'projection.commodity.values' = 'arabica_coffee',
    'projection.enabled' = 'true',
    'projection.year.range' = '2017,2035',
    'projection.year.type' = 'integer',
    'storage.location.template' = 's3://leviathan-dev-shahem-001/silver/fnc_colombia/exports_port_type/commodity=${commodity}/year=${year}'
);
