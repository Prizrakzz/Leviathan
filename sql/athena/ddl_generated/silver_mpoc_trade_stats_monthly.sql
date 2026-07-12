-- silver_mpoc_trade_stats_monthly - trade_flows silver table (source); SILVER-F011 registry-generated DDL.
--
-- GENERATED from the SILVER-F010 registry (configs/silver/tables/silver_mpoc_trade_stats_monthly.yaml) by
-- leviathan.silver.ddl -- this RETIRES the first-parquet schema inference. Do NOT
-- hand-edit; re-run:  python scripts/silver/generate_ddls_from_registry.py --write
-- partition_mode = flat. recovery: active-release manifest / bounded full relist under the flat root
--
-- Flat physical layout under one LOCATION -- no partition-enumeration (LIST-storm)
-- surface; any hive-partition keys are also in-file data columns.
CREATE EXTERNAL TABLE IF NOT EXISTS silver_mpoc_trade_stats_monthly (
    year       bigint,
    month      bigint,
    exports_mt double,
    imports_mt double,
    source     string
)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/mpoc_trade_stats_monthly/'
TBLPROPERTIES (
    'EXTERNAL' = 'TRUE',
    'parquet.compression' = 'SNAPPY'
);
