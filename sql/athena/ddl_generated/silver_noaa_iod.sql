-- silver_noaa_iod - climate silver table (source); SILVER-F011 registry-generated DDL.
--
-- GENERATED from the SILVER-F010 registry (configs/silver/tables/silver_noaa_iod.yaml) by
-- leviathan.silver.ddl -- this RETIRES the first-parquet schema inference. Do NOT
-- hand-edit; re-run:  python scripts/silver/generate_ddls_from_registry.py --write
-- partition_mode = flat. recovery: active-release manifest / bounded full relist under the flat root
--
-- Flat physical layout under one LOCATION -- no partition-enumeration (LIST-storm)
-- surface; any hive-partition keys are also in-file data columns.
CREATE EXTERNAL TABLE IF NOT EXISTS silver_noaa_iod (
    year                  bigint,
    month                 bigint,
    date                  timestamp,
    dmi_value             double,
    iod_dmi_3month_avg    double,
    iod_phase             string,
    iod_dmi_ethiopia_lag4 double,
    source                string
)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/weather/source=noaa_iod/'
TBLPROPERTIES (
    'EXTERNAL' = 'TRUE',
    'parquet.compression' = 'SNAPPY'
);
