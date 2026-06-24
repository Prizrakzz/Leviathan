-- GENERATED from configs/datasets/datasets.yaml; do not edit by hand.
-- dataset_id=silver_fgis
-- registry_sha256=fcc347a2e81b7b5fd3a6b6223801a375b77ec9819afa289ec9f7a1342d2cdce3
CREATE EXTERNAL TABLE IF NOT EXISTS `leviathan_dev`.`silver_fgis` (
    `week_of_marketing_year` INT,
    `week_ending_date`       DATE,
    `destination_country`    STRING,
    `exports_mt_weekly`      DOUBLE,
    `exports_mt_ctd`         DOUBLE,
    `source`                 STRING
)
PARTITIONED BY (`leviathan_slug` STRING, `marketing_year` INT)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/fgis/'
TBLPROPERTIES (
    'parquet.compression' = 'SNAPPY',
    'projection.enabled' = 'true',
    'projection.leviathan_slug.type' = 'enum',
    'projection.leviathan_slug.values' = 'corn_cbot,soybeans_cbot,hard_red_winter_wheat_kcbt,hard_red_spring_wheat_mgex,soft_red_winter_wheat_cbot',
    'projection.marketing_year.range' = '1982,2035',
    'projection.marketing_year.type' = 'integer',
    'storage.location.template' = 's3://leviathan-dev-shahem-001/silver/fgis/leviathan_slug=${leviathan_slug}/marketing_year=${marketing_year}'
);
