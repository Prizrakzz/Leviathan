-- silver_eex_freight - freight silver table (source); SILVER-F011 registry-generated DDL.
--
-- GENERATED from the SILVER-F010 registry (configs/silver/tables/silver_eex_freight.yaml) by
-- leviathan.silver.ddl -- this RETIRES the first-parquet schema inference. Do NOT
-- hand-edit; re-run:  python scripts/silver/generate_ddls_from_registry.py --write
-- partition_mode = flat. recovery: active-release manifest / bounded full relist under the flat root
--
-- Flat physical layout under one LOCATION -- no partition-enumeration (LIST-storm)
-- surface; any hive-partition keys are also in-file data columns.
CREATE EXTERNAL TABLE IF NOT EXISTS silver_eex_freight (
    trade_date     date,
    symbol         string,
    contract_month string,
    product        string,
    route          string,
    settle_px      double,
    currency       string,
    unit           string,
    volume_lots    double,
    long_name      string,
    source         string
)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/eex_freight/'
TBLPROPERTIES (
    'EXTERNAL' = 'TRUE',
    'parquet.compression' = 'SNAPPY'
);
