-- GENERATED from configs/datasets/datasets.yaml; do not edit by hand.
-- dataset_id=silver_esr
-- registry_sha256=fcc347a2e81b7b5fd3a6b6223801a375b77ec9819afa289ec9f7a1342d2cdce3
CREATE EXTERNAL TABLE IF NOT EXISTS `leviathan_dev`.`silver_esr` (
    `commodity_name`           STRING,
    `country_code`             SMALLINT,
    `week_ending_date`         DATE,
    `outstanding_sales_1000mt` FLOAT,
    `weekly_exports_1000mt`    FLOAT,
    `gross_new_sales_1000mt`   FLOAT,
    `changes_1000mt`           FLOAT,
    `source_unit_id`           SMALLINT,
    `ingest_date`              STRING,
    `source`                   STRING
)
PARTITIONED BY (`commodity_code` INT, `market_year` INT, `as_of_date` STRING)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/production/source=usda_esr/'
TBLPROPERTIES (
    'parquet.compression' = 'SNAPPY',
    'projection.as_of_date.format' = 'yyyyMMdd',
    'projection.as_of_date.range' = '19900101,NOW',
    'projection.as_of_date.type' = 'date',
    'projection.commodity_code.type' = 'enum',
    'projection.commodity_code.values' = '101,102,103,104,107,401,701,801,901,902',
    'projection.enabled' = 'true',
    'projection.market_year.range' = '1990,2035',
    'projection.market_year.type' = 'integer',
    'storage.location.template' = 's3://leviathan-dev-shahem-001/silver/production/source=usda_esr/commodity_code=${commodity_code}/market_year=${market_year}/as_of=${as_of_date}'
);
