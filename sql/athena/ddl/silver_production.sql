-- silver_production: external table with partition projection
-- Partition projection resolves S3 paths from metadata — no MSCK REPAIR TABLE needed.
-- Managed programmatically by jobs/athena_utils.py :: ensure_catalog().
-- This file is the canonical DDL reference.
--
-- commodity: enum projection — all 31 supported commodities

CREATE EXTERNAL TABLE IF NOT EXISTS leviathan_dev.silver_production (
    country          STRING,
    variable         STRING,
    value            DOUBLE,
    unit             STRING,
    flag             STRING,
    is_official      BOOLEAN,
    ingest_date      STRING
)
PARTITIONED BY (source STRING, commodity STRING, year INT)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/production/'
TBLPROPERTIES (
    'projection.enabled'          = 'true',
    'projection.source.type'      = 'enum',
    'projection.source.values'    = 'faostat',
    'projection.commodity.type'   = 'enum',
    'projection.commodity.values' = 'cocoa,corn_cbot,campinas_corn_reference_bmf,french_wheat_matif,french_maize_matif,hard_red_winter_wheat_kcbt,hard_red_spring_wheat_mgex,soft_red_winter_wheat_cbot,rough_rice_cbot,south_african_white_maize_jse,south_african_yellow_maize_jse,soybeans_cbot,soybean_meal_cbot,soybean_oil_cbot,soybeans_no_1_dce,soybeans_no_2_dce,soybean_meal_dce,soybean_oil_dce,french_rapeseed_matif,canola_ice,rapeseed_oil_zce,rapeseed_meal_zce,malaysian_crude_palm_oil_cme,palm_olein_dce,brazilian_arabica_coffee,arabica_coffee,robusta_coffee,cotton,raw_sugar,white_sugar,frozen_orange_juice',
    'projection.year.type'        = 'integer',
    'projection.year.range'       = '1961,2023',
    'storage.location.template'   = 's3://leviathan-dev-shahem-001/silver/production/source=${source}/commodity=${commodity}/year=${year}'
);
