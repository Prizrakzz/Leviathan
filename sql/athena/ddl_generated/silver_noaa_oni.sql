-- silver_noaa_oni - climate silver table (source); SILVER-F011 registry-generated DDL.
--
-- GENERATED from the SILVER-F010 registry (configs/silver/tables/silver_noaa_oni.yaml) by
-- leviathan.silver.ddl -- this RETIRES the first-parquet schema inference. Do NOT
-- hand-edit; re-run:  python scripts/silver/generate_ddls_from_registry.py --write
-- partition_mode = flat. recovery: active-release manifest / bounded full relist under the flat root
--
-- Flat physical layout under one LOCATION -- no partition-enumeration (LIST-storm)
-- surface; any hive-partition keys are also in-file data columns.
CREATE EXTERNAL TABLE IF NOT EXISTS silver_noaa_oni (
    year                   bigint,
    month                  bigint,
    season                 string,
    oni_anom               double,
    phase                  string,
    oni_lag3               double,
    oni_lag6               double,
    oni_lag9               double,
    oni_lag12              double,
    el_nino_flag           bigint,
    la_nina_flag           bigint,
    la_nina_brazil_flag    bigint,
    argentina_la_nina_flag bigint,
    source                 string
)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/weather/source=noaa_oni/'
TBLPROPERTIES (
    'EXTERNAL' = 'TRUE',
    'parquet.compression' = 'SNAPPY'
);
