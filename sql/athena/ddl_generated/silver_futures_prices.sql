-- silver_futures_prices - prices silver table (source); SILVER-F011 registry-generated DDL.
--
-- GENERATED from the SILVER-F010 registry (configs/silver/tables/silver_futures_prices.yaml) by
-- leviathan.silver.ddl -- this RETIRES the first-parquet schema inference. Do NOT
-- hand-edit; re-run:  python scripts/silver/generate_ddls_from_registry.py --write
-- partition_mode = flat. recovery: active-release manifest / bounded full relist under the flat root
--
-- Flat physical layout under one LOCATION -- no partition-enumeration (LIST-storm)
-- surface; any hive-partition keys are also in-file data columns.
CREATE EXTERNAL TABLE IF NOT EXISTS silver_futures_prices (
    date             timestamp,
    leviathan_slug   string,
    close            float,
    log_return       float,
    price_z_2yr      float,
    realized_vol_30d float,
    momentum_60d     float,
    momentum_1yr     float,
    vol_regime       tinyint,
    source           string,
    unit             string
)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/futures_prices/'
TBLPROPERTIES (
    'EXTERNAL' = 'TRUE',
    'parquet.compression' = 'SNAPPY'
);
