-- GENERATED from configs/datasets/datasets.yaml; do not edit by hand.
-- dataset_id=silver_nass_crop_progress
-- registry_sha256=fcc347a2e81b7b5fd3a6b6223801a375b77ec9819afa289ec9f7a1342d2cdce3
CREATE EXTERNAL TABLE IF NOT EXISTS `leviathan_dev`.`silver_nass_crop_progress` (
    `leviathan_slug`     STRING,
    `state`              STRING,
    `date`               DATE,
    `week_of_year`       BIGINT,
    `pct_planted`        DOUBLE,
    `pct_emerged`        DOUBLE,
    `pct_good_excellent` DOUBLE,
    `pct_poor_very_poor` DOUBLE,
    `pct_harvested`      DOUBLE,
    `source`             STRING
)
PARTITIONED BY (`commodity` STRING, `year` INT)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/nass_crop_progress/'
TBLPROPERTIES (
    'parquet.compression' = 'SNAPPY',
    'projection.commodity.type' = 'enum',
    'projection.commodity.values' = 'corn_cbot,soybeans_cbot,rough_rice_cbot,cotton,soft_red_winter_wheat_cbot,hard_red_spring_wheat_mgex',
    'projection.enabled' = 'true',
    'projection.year.range' = '1979,2035',
    'projection.year.type' = 'integer',
    'storage.location.template' = 's3://leviathan-dev-shahem-001/silver/nass_crop_progress/commodity=${commodity}/year=${year}'
);
