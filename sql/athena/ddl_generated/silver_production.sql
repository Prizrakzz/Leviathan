-- silver_production - production silver table (source); SILVER-F011 registry-generated DDL.
--
-- GENERATED from the SILVER-F010 registry (configs/silver/tables/silver_production.yaml) by
-- leviathan.silver.ddl -- this RETIRES the first-parquet schema inference. Do NOT
-- hand-edit; re-run:  python scripts/silver/generate_ddls_from_registry.py --write
-- partition_mode = projected. recovery: get-partitions inventory + single sargable Athena probe on a registered surface
--
-- LEGACY-QUARANTINED partition projection (INV-3): the projected grid enumerates every
-- candidate partition (the Jul-2026 S3 LIST-storm class). NEVER DROP+CREATE this into a
-- flat or re-projected shape; recovery reads S3 parquet footers, NEVER Athena.
CREATE EXTERNAL TABLE IF NOT EXISTS silver_production (
    country          string,
    country_key      string,
    metric           string,
    unit             string,
    value            double,
    flag             string,
    is_official      boolean,
    note             string,
    source           string,
    dataset          string,
    ingest_date      string,
    source_file_name string
)
PARTITIONED BY (commodity string, year int)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/production/'
TBLPROPERTIES (
    'EXTERNAL' = 'TRUE',
    'parquet.compression' = 'SNAPPY',
    'projection.commodity.type' = 'enum',
    'projection.commodity.values' = 'cocoa,corn_cbot,campinas_corn_reference_bmf,french_wheat_matif,french_maize_matif,hard_red_winter_wheat_kcbt,hard_red_spring_wheat_mgex,soft_red_winter_wheat_cbot,rough_rice_cbot,south_african_white_maize_jse,south_african_yellow_maize_jse,soybeans_cbot,soybean_meal_cbot,soybean_oil_cbot,soybeans_no_1_dce,soybeans_no_2_dce,soybean_meal_dce,soybean_oil_dce,french_rapeseed_matif,canola_ice,rapeseed_oil_zce,rapeseed_meal_zce,malaysian_crude_palm_oil_cme,palm_olein_dce,brazilian_arabica_coffee,arabica_coffee,robusta_coffee,cotton,raw_sugar,white_sugar,frozen_orange_juice,sorghum,peanut,barley,millet,oats,sunflower,rye,cottonseed_oil,cottonseed,sunflower_oil,palm_kernel_oil,palm_kernel,cattle_beef,hogs,broilers_poultry,milk_fluid',
    'projection.enabled' = 'true',
    'projection.year.range' = '1961,2035',
    'projection.year.type' = 'integer'
);
