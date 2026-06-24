-- GENERATED from configs/datasets/datasets.yaml; do not edit by hand.
-- dataset_id=silver_modis_ndvi
-- registry_sha256=fcc347a2e81b7b5fd3a6b6223801a375b77ec9819afa289ec9f7a1342d2cdce3
CREATE EXTERNAL TABLE IF NOT EXISTS `leviathan_dev`.`silver_modis_ndvi` (
    `date`              DATE,
    `year`              SMALLINT,
    `period`            TINYINT,
    `commodity`         STRING,
    `country`           STRING,
    `region`            STRING,
    `latitude`          FLOAT,
    `longitude`         FLOAT,
    `ndvi_raw`          FLOAT,
    `ndvi`              FLOAT,
    `pixel_reliability` TINYINT,
    `ndvi_z_score`      FLOAT,
    `baseline_mean`     FLOAT,
    `baseline_std`      FLOAT,
    `ingest_date`       STRING
)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/weather/source=modis_ndvi/'
TBLPROPERTIES (
    'parquet.compression' = 'SNAPPY'
);
