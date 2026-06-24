-- GENERATED from configs/datasets/datasets.yaml; do not edit by hand.
-- dataset_id=silver_nass_annual
-- registry_sha256=fcc347a2e81b7b5fd3a6b6223801a375b77ec9819afa289ec9f7a1342d2cdce3
CREATE EXTERNAL TABLE IF NOT EXISTS `leviathan_dev`.`silver_nass_annual` (
    `leviathan_slug`        STRING,
    `country`               STRING,
    `state`                 STRING,
    `marketing_year`        BIGINT,
    `area_planted_ha`       DOUBLE,
    `area_harvested_ha`     DOUBLE,
    `yield_t_ha`            DOUBLE,
    `production_mt`         DOUBLE,
    `area_planted_cv_pct`   DOUBLE,
    `area_harvested_cv_pct` DOUBLE,
    `yield_cv_pct`          DOUBLE,
    `production_cv_pct`     DOUBLE,
    `source`                STRING
)
PARTITIONED BY (`commodity` STRING, `year` INT)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/nass_annual/'
TBLPROPERTIES (
    'parquet.compression' = 'SNAPPY',
    'projection.commodity.type' = 'enum',
    'projection.commodity.values' = 'corn_cbot,soybeans_cbot,rough_rice_cbot,cotton,soft_red_winter_wheat_cbot,hard_red_spring_wheat_mgex',
    'projection.enabled' = 'true',
    'projection.year.range' = '1866,2035',
    'projection.year.type' = 'integer',
    'storage.location.template' = 's3://leviathan-dev-shahem-001/silver/nass_annual/commodity=${commodity}/year=${year}'
);
