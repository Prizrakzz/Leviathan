-- silver_moex_agro_indices - prices silver table (source); SILVER-F011 registry-generated DDL.
--
-- GENERATED from the SILVER-F010 registry (configs/silver/tables/silver_moex_agro_indices.yaml) by
-- leviathan.silver.ddl -- this RETIRES the first-parquet schema inference. Do NOT
-- hand-edit; re-run:  python scripts/silver/generate_ddls_from_registry.py --write
-- partition_mode = flat. recovery: active-release manifest / bounded full relist under the flat root
--
-- Flat physical layout under one LOCATION -- no partition-enumeration (LIST-storm)
-- surface; any hive-partition keys are also in-file data columns.
CREATE EXTERNAL TABLE IF NOT EXISTS silver_moex_agro_indices (
    secid      string,
    trade_date date,
    close      double,
    currency   string,
    board      string,
    source     string
)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/moex_agro_indices/'
TBLPROPERTIES (
    'EXTERNAL' = 'TRUE',
    'parquet.compression' = 'SNAPPY'
);
