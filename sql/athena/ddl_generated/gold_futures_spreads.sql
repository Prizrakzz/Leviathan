-- gold_futures_spreads - unclassified gold table (source); SILVER-F011 registry-generated DDL.
--
-- GENERATED from the SILVER-F010 registry (configs/silver/tables/gold_futures_spreads.yaml) by
-- leviathan.silver.ddl -- this RETIRES the first-parquet schema inference. Do NOT
-- hand-edit; re-run:  python scripts/silver/generate_ddls_from_registry.py --write
-- partition_mode = flat. recovery: active-release manifest / bounded full relist under the flat root
--
-- Flat physical layout under one LOCATION -- no partition-enumeration (LIST-storm)
-- surface; any hive-partition keys are also in-file data columns.
CREATE EXTERNAL TABLE IF NOT EXISTS gold_futures_spreads (
    spread_id            string,
    trade_date           string,
    spread_value         double,
    unit                 string,
    long_slug            string,
    short_slug           string,
    long_contract_month  string,
    short_contract_month string,
    long_settle          double,
    short_settle         double,
    settle_kind          string,
    is_roll_boundary     string,
    roll_rule_version    string,
    spread_rule_version  string
)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/gold/futures_spreads/'
TBLPROPERTIES (
    'EXTERNAL' = 'TRUE',
    'parquet.compression' = 'SNAPPY'
);
