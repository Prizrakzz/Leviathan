-- GENERATED from configs/datasets/datasets.yaml; do not edit by hand.
-- dataset_id=silver_noaa_iod
-- registry_sha256=fcc347a2e81b7b5fd3a6b6223801a375b77ec9819afa289ec9f7a1342d2cdce3
CREATE EXTERNAL TABLE IF NOT EXISTS `leviathan_dev`.`silver_noaa_iod` (
    `year`                  BIGINT,
    `month`                 BIGINT,
    `date`                  TIMESTAMP,
    `dmi_value`             FLOAT,
    `iod_dmi_3month_avg`    FLOAT,
    `iod_phase`             STRING,
    `iod_dmi_ethiopia_lag4` FLOAT,
    `source`                STRING
)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/weather/source=noaa_iod/'
TBLPROPERTIES (
    'parquet.compression' = 'SNAPPY'
);
