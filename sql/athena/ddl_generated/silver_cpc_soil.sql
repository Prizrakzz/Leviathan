-- silver_cpc_soil - weather silver table (source); SILVER-F011 registry-generated DDL.
--
-- GENERATED from the SILVER-F010 registry (configs/silver/tables/silver_cpc_soil.yaml) by
-- leviathan.silver.ddl -- this RETIRES the first-parquet schema inference. Do NOT
-- hand-edit; re-run:  python scripts/silver/generate_ddls_from_registry.py --write
-- partition_mode = projected. recovery: S3 footer only (INV-3: NEVER start-query-execution against this projection.* table)
--
-- LEGACY-QUARANTINED partition projection (INV-3): the projected grid enumerates every
-- candidate partition (the Jul-2026 S3 LIST-storm class). NEVER DROP+CREATE this into a
-- flat or re-projected shape; recovery reads S3 parquet footers, NEVER Athena.
CREATE EXTERNAL TABLE IF NOT EXISTS silver_cpc_soil (
    date        date,
    day         bigint,
    source      string,
    ingest_date string,
    variable    string,
    value       double
)
PARTITIONED BY (commodity string, country string, region string, year int, month int)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/weather/source=cpc_soil/'
TBLPROPERTIES (
    'EXTERNAL' = 'TRUE',
    'parquet.compression' = 'SNAPPY',
    'projection.commodity.type' = 'enum',
    'projection.commodity.values' = 'cocoa,corn_cbot,campinas_corn_reference_bmf,french_wheat_matif,french_maize_matif,hard_red_winter_wheat_kcbt,hard_red_spring_wheat_mgex,soft_red_winter_wheat_cbot,rough_rice_cbot,south_african_white_maize_jse,south_african_yellow_maize_jse,soybeans_cbot,soybean_meal_cbot,soybean_oil_cbot,soybeans_no_1_dce,soybeans_no_2_dce,soybean_meal_dce,soybean_oil_dce,french_rapeseed_matif,canola_ice,rapeseed_oil_zce,rapeseed_meal_zce,malaysian_crude_palm_oil_cme,palm_olein_dce,brazilian_arabica_coffee,arabica_coffee,robusta_coffee,cotton,raw_sugar,white_sugar,frozen_orange_juice',
    'projection.country.type' = 'injected',
    'projection.enabled' = 'true',
    'projection.month.digits' = '2',
    'projection.month.range' = '1,12',
    'projection.month.type' = 'integer',
    'projection.region.type' = 'injected',
    'projection.year.range' = '2000,2035',
    'projection.year.type' = 'integer',
    'storage.location.template' = 's3://leviathan-dev-shahem-001/silver/weather/source=cpc_soil/commodity=${commodity}/country=${country}/region=${region}/year=${year}/month=${month}'
);
