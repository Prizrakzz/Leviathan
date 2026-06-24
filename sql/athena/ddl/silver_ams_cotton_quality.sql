-- GENERATED from configs/datasets/datasets.yaml; do not edit by hand.
-- dataset_id=silver_ams_cotton_quality
-- registry_sha256=fcc347a2e81b7b5fd3a6b6223801a375b77ec9819afa289ec9f7a1342d2cdce3
CREATE EXTERNAL TABLE IF NOT EXISTS `leviathan_dev`.`silver_ams_cotton_quality` (
    `commodity`          STRING,
    `season`             BIGINT,
    `geography`          STRING,
    `percent_tenderable` DOUBLE,
    `samples_classed`    DOUBLE,
    `avg_staple`         DOUBLE,
    `avg_micronaire`     DOUBLE,
    `avg_strength`       DOUBLE,
    `source_pages`       STRING,
    `source_raw_key`     STRING,
    `source_file_etag`   STRING,
    `source`             STRING
)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/ams_cotton_quality/'
TBLPROPERTIES (
    'parquet.compression' = 'SNAPPY'
);
