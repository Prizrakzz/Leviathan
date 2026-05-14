-- silver_weather: external table with partition projection
-- Partition projection resolves S3 paths from metadata — no MSCK REPAIR TABLE needed.
-- Managed programmatically by jobs/athena_utils.py :: ensure_catalog().
-- This file is the canonical DDL reference.
--
-- commodity: enum projection — all 31 supported commodities
-- country, region: injected projection — values come from WHERE clause predicates;
--   too many unique values across 31 commodities for enum to be practical.
--   Full-scan queries (no WHERE on country/region) perform an S3 LIST and scan all prefixes.

CREATE EXTERNAL TABLE IF NOT EXISTS leviathan_dev.silver_weather (
    date                       STRING,
    day                        INT,
    ingest_date                STRING,
    variable                   STRING,
    value                      DOUBLE
)
PARTITIONED BY (commodity STRING, country STRING, region STRING, year INT, month INT)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/weather/source=nasa_power/'
TBLPROPERTIES (
    'projection.enabled'          = 'true',
    'projection.commodity.type'   = 'enum',
    'projection.commodity.values' = 'cocoa,corn_cbot,campinas_corn_reference_bmf,french_wheat_matif,french_maize_matif,hard_red_winter_wheat_kcbt,hard_red_spring_wheat_mgex,soft_red_winter_wheat_cbot,rough_rice_cbot,south_african_white_maize_jse,south_african_yellow_maize_jse,soybeans_cbot,soybean_meal_cbot,soybean_oil_cbot,soybeans_no_1_dce,soybeans_no_2_dce,soybean_meal_dce,soybean_oil_dce,french_rapeseed_matif,canola_ice,rapeseed_oil_zce,rapeseed_meal_zce,malaysian_crude_palm_oil_cme,palm_olein_dce,brazilian_arabica_coffee,arabica_coffee,robusta_coffee,cotton,raw_sugar,white_sugar,frozen_orange_juice',
    'projection.country.type'     = 'injected',
    'projection.region.type'      = 'injected',
    'projection.year.type'        = 'integer',
    'projection.year.range'       = '1981,2024',
    'projection.month.type'       = 'integer',
    'projection.month.range'      = '1,12',
    'projection.month.digits'     = '2',
    'storage.location.template'   = 's3://leviathan-dev-shahem-001/silver/weather/source=nasa_power/commodity=${commodity}/country=${country}/region=${region}/year=${year}/month=${month}'
);
