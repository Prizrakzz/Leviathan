-- silver_cot - positioning silver table (source); SILVER-F011 registry-generated DDL.
--
-- GENERATED from the SILVER-F010 registry (configs/silver/tables/silver_cot.yaml) by
-- leviathan.silver.ddl -- this RETIRES the first-parquet schema inference. Do NOT
-- hand-edit; re-run:  python scripts/silver/generate_ddls_from_registry.py --write
-- partition_mode = flat. recovery: active-release manifest / bounded full relist under the flat root
--
-- Flat physical layout under one LOCATION -- no partition-enumeration (LIST-storm)
-- surface; any hive-partition keys are also in-file data columns.
CREATE EXTERNAL TABLE IF NOT EXISTS silver_cot (
    report_date     string,
    leviathan_slug  string,
    open_interest   bigint,
    mm_long         bigint,
    mm_short        bigint,
    mm_spread       bigint,
    mm_net          bigint,
    mm_pct_oi       double,
    mm_net_z_3yr    double,
    mm_pct_oi_z_3yr double,
    source          string
)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/cot/'
TBLPROPERTIES (
    'EXTERNAL' = 'TRUE',
    'parquet.compression' = 'SNAPPY'
);
