-- silver_nasa_power - weather silver table (source); SILVER-F011 registry-generated DDL.
--
-- GENERATED from the SILVER-F010 registry (configs/silver/tables/silver_nasa_power.yaml) by
-- leviathan.silver.ddl -- this RETIRES the first-parquet schema inference. Do NOT
-- hand-edit; re-run:  python scripts/silver/generate_ddls_from_registry.py --write
-- partition_mode = registered. recovery: get-partitions reconcile + S3 footer reads (INV-3, post-F047 deprojection: NEVER start-query-execution against this weather table; serving is quarantined to gold_weather_z)
--
-- REGISTERED partitions -- DO NOT re-add partition projection. The projected grid is
-- the Jul-2026 S3 LIST-storm class ($134/2 days); partitions carry explicit Glue
-- locations (MSCK cannot repair them). After a DROP+CREATE from this DDL, re-register:
--     python jobs/utils/deproject_glue_table.py --register --tables silver_nasa_power
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
    wind_speed_2m_m_s        double,
    country                  string,
    region                   string,
    month                    bigint
)
PARTITIONED BY (commodity string, year int)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/weather/source=nasa_power/'
TBLPROPERTIES (
    'EXTERNAL' = 'TRUE',
    'parquet.compression' = 'SNAPPY'
);
