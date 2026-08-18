-- silver_food_cpi - macro silver table (source); SILVER-F011 registry-generated DDL.
--
-- GENERATED from the SILVER-F010 registry (configs/silver/tables/silver_food_cpi.yaml) by
-- leviathan.silver.ddl -- this RETIRES the first-parquet schema inference. Do NOT
-- hand-edit; re-run:  python scripts/silver/generate_ddls_from_registry.py --write
-- partition_mode = flat. recovery: active-release manifest / bounded full relist under the flat root
--
-- Flat physical layout under one LOCATION -- no partition-enumeration (LIST-storm)
-- surface; any hive-partition keys are also in-file data columns.
CREATE EXTERNAL TABLE IF NOT EXISTS silver_food_cpi (
    country_iso    string,
    country_name   string,
    year           bigint,
    cpi_yoy_pct    double,
    cpi_yoy_z_5yr  double,
    cpi_yoy_z_10yr double,
    cpi_available  bigint,
    source         string,
    data_date      string,
    release_date   string
)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/food_cpi/'
TBLPROPERTIES (
    'EXTERNAL' = 'TRUE',
    'parquet.compression' = 'SNAPPY'
);
