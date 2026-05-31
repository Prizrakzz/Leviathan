-- silver_nass_annual: wide USDA NASS annual production features.
-- This table intentionally lives under silver/nass_annual/ so it cannot be
-- picked up by the long-form silver_production table projection.

CREATE EXTERNAL TABLE IF NOT EXISTS leviathan_dev.silver_nass_annual (
    leviathan_slug          STRING,
    country                 STRING,
    state                   STRING,
    marketing_year          INT,
    area_planted_ha         DOUBLE,
    area_harvested_ha       DOUBLE,
    yield_t_ha              DOUBLE,
    production_mt           DOUBLE,
    area_planted_cv_pct     DOUBLE,
    area_harvested_cv_pct   DOUBLE,
    yield_cv_pct            DOUBLE,
    production_cv_pct       DOUBLE,
    source                  STRING
)
PARTITIONED BY (commodity STRING, year INT)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/nass_annual/'
TBLPROPERTIES (
    'projection.enabled'          = 'true',
    'projection.commodity.type'   = 'enum',
    'projection.commodity.values' = 'cocoa,corn_cbot,campinas_corn_reference_bmf,french_wheat_matif,french_maize_matif,hard_red_winter_wheat_kcbt,hard_red_spring_wheat_mgex,soft_red_winter_wheat_cbot,rough_rice_cbot,south_african_white_maize_jse,south_african_yellow_maize_jse,soybeans_cbot,soybean_meal_cbot,soybean_oil_cbot,soybeans_no_1_dce,soybeans_no_2_dce,soybean_meal_dce,soybean_oil_dce,french_rapeseed_matif,canola_ice,rapeseed_oil_zce,rapeseed_meal_zce,malaysian_crude_palm_oil_cme,palm_olein_dce,brazilian_arabica_coffee,arabica_coffee,robusta_coffee,cotton,raw_sugar,white_sugar,frozen_orange_juice',
    'projection.year.type'        = 'integer',
    'projection.year.range'       = '1866,2035',
    'storage.location.template'   = 's3://leviathan-dev-shahem-001/silver/nass_annual/commodity=${commodity}/year=${year}'
);
