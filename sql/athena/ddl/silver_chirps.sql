-- GENERATED from configs/datasets/datasets.yaml; do not edit by hand.
-- dataset_id=silver_chirps
-- registry_sha256=fcc347a2e81b7b5fd3a6b6223801a375b77ec9819afa289ec9f7a1342d2cdce3
CREATE EXTERNAL TABLE IF NOT EXISTS `leviathan_dev`.`silver_chirps` (
    `date`        DATE,
    `day`         BIGINT,
    `source`      STRING,
    `ingest_date` STRING,
    `variable`    STRING,
    `value`       DOUBLE
)
PARTITIONED BY (`commodity` STRING, `country` STRING, `region` STRING, `year` INT, `month` INT)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/weather/source=chirps/'
TBLPROPERTIES (
    'parquet.compression' = 'SNAPPY',
    'projection.commodity.type' = 'enum',
    'projection.commodity.values' = 'cocoa,corn_cbot,campinas_corn_reference_bmf,french_wheat_matif,french_maize_matif,hard_red_winter_wheat_kcbt,hard_red_spring_wheat_mgex,soft_red_winter_wheat_cbot,rough_rice_cbot,south_african_white_maize_jse,south_african_yellow_maize_jse,soybeans_cbot,soybean_meal_cbot,soybean_oil_cbot,soybeans_no_1_dce,soybeans_no_2_dce,soybean_meal_dce,soybean_oil_dce,french_rapeseed_matif,canola_ice,rapeseed_oil_zce,rapeseed_meal_zce,malaysian_crude_palm_oil_cme,palm_olein_dce,brazilian_arabica_coffee,arabica_coffee,robusta_coffee,cotton,raw_sugar,white_sugar,frozen_orange_juice',
    'projection.country.type' = 'injected',
    'projection.enabled' = 'true',
    'projection.month.digits' = '2',
    'projection.month.range' = '1,12',
    'projection.month.type' = 'integer',
    'projection.region.type' = 'injected',
    'projection.year.range' = '1981,2035',
    'projection.year.type' = 'integer',
    'storage.location.template' = 's3://leviathan-dev-shahem-001/silver/weather/source=chirps/commodity=${commodity}/country=${country}/region=${region}/year=${year}/month=${month}'
);
