-- silver_minagro_grain_exports - trade_flows silver table (source); SILVER-F011 registry-generated DDL.
--
-- GENERATED from the SILVER-F010 registry (configs/silver/tables/silver_minagro_grain_exports.yaml) by
-- leviathan.silver.ddl -- this RETIRES the first-parquet schema inference. Do NOT
-- hand-edit; re-run:  python scripts/silver/generate_ddls_from_registry.py --write
-- partition_mode = flat. recovery: active-release manifest / bounded full relist under the flat root
--
-- Flat physical layout under one LOCATION -- no partition-enumeration (LIST-storm)
-- surface; any hive-partition keys are also in-file data columns.
CREATE EXTERNAL TABLE IF NOT EXISTS silver_minagro_grain_exports (
    as_of_date             date,
    crop_slug              string,
    marketing_year         string,
    prior_marketing_year   string,
    my_cumulative_kt       double,
    month_to_date_kt       double,
    prior_my_cumulative_kt double,
    prior_my_month_kt      double,
    source                 string
)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/minagro_grain_exports/'
TBLPROPERTIES (
    'EXTERNAL' = 'TRUE',
    'parquet.compression' = 'SNAPPY'
);
