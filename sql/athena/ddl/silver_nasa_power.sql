-- GENERATED from live Glue table leviathan_dev.silver_nasa_power; keep in sync with the S3 layout.
CREATE EXTERNAL TABLE IF NOT EXISTS silver_nasa_power (
    date                     date,
    day                      bigint,
    source                   string,
    ingest_date              string,
    source_file_name         string,
    temperature_2m_mean_c    double,
    temperature_2m_max_c     double,
    temperature_2m_min_c     double,
    precipitation_mm         double,
    relative_humidity_2m_pct double,
    wind_speed_2m_m_s        double
)
PARTITIONED BY (commodity string, country string, region string, year int, month int)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/weather/source=nasa_power'
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
    'projection.year.range' = '1981,2035',
    'projection.year.type' = 'integer',
    'storage.location.template' = 's3://leviathan-dev-shahem-001/silver/weather/source=nasa_power/commodity=${commodity}/country=${country}/region=${region}/year=${year}/month=${month}'
);
