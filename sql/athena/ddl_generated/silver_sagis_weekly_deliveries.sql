-- silver_sagis_weekly_deliveries - trade_flows silver table (source); SILVER-F011 registry-generated DDL.
--
-- GENERATED from the SILVER-F010 registry (configs/silver/tables/silver_sagis_weekly_deliveries.yaml) by
-- leviathan.silver.ddl -- this RETIRES the first-parquet schema inference. Do NOT
-- hand-edit; re-run:  python scripts/silver/generate_ddls_from_registry.py --write
-- partition_mode = flat. recovery: active-release manifest / bounded full relist under the flat root
--
-- Flat physical layout under one LOCATION -- no partition-enumeration (LIST-storm)
-- surface; any hive-partition keys are also in-file data columns.
CREATE EXTERNAL TABLE IF NOT EXISTS silver_sagis_weekly_deliveries (
    season              string,
    crop                string,
    week_number         bigint,
    week_ending         string,
    prog_total_mt       double,
    prior_prog_total_mt double,
    pct_of_prior_yr     double,
    z_vs_3yr_avg        double,
    source              string,
    week_ending_date    date
)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/sagis_weekly_deliveries/'
TBLPROPERTIES (
    'EXTERNAL' = 'TRUE',
    'parquet.compression' = 'SNAPPY'
);
