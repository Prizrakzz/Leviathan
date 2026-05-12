-- silver_weather: external table with partition projection
-- Partition projection resolves S3 paths from metadata — no MSCK REPAIR TABLE needed.
-- Managed programmatically by jobs/athena_utils.py :: ensure_catalog().
-- This file is the canonical DDL reference.

CREATE EXTERNAL TABLE IF NOT EXISTS leviathan_dev.silver_weather (
    date                       DATE,
    day                        INT,
    commodity                  STRING,
    source                     STRING,
    ingest_date                STRING,
    source_file_name           STRING,
    temperature_2m_mean_c      DOUBLE,
    temperature_2m_max_c       DOUBLE,
    temperature_2m_min_c       DOUBLE,
    precipitation_mm           DOUBLE,
    relative_humidity_2m_pct   DOUBLE,
    wind_speed_2m_m_s          DOUBLE,
    solar_radiation_mj_m2_day  DOUBLE
)
PARTITIONED BY (country STRING, region STRING, year INT, month INT)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/weather/source=nasa_power/commodity=cocoa/'
TBLPROPERTIES (
    'projection.enabled'        = 'true',
    'projection.country.type'   = 'enum',
    'projection.country.values' = 'cote_divoire,ghana,ecuador,nigeria,cameroon',
    'projection.region.type'    = 'enum',
    'projection.region.values'  = 'soubre,daloa,abengourou,divo,kumasi_ashanti,sefwi_wiawso_western_north,koforidua_eastern,los_rios_babahoyo,guayas_milagro,manabi_chone,ondo_akure,cross_river_ikom,centre_yaounde,southwest_kumba',
    'projection.year.type'      = 'integer',
    'projection.year.range'     = '1981,2024',
    'projection.month.type'     = 'integer',
    'projection.month.range'    = '1,12',
    'projection.month.digits'   = '2',
    'storage.location.template' = 's3://leviathan-dev-shahem-001/silver/weather/source=nasa_power/commodity=cocoa/country=${country}/region=${region}/year=${year}/month=${month}'
);
