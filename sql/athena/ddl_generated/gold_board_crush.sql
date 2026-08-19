-- gold_board_crush - prices gold table (derived); SILVER-F011 registry-generated DDL.
--
-- GENERATED from the SILVER-F010 registry (configs/silver/tables/gold_board_crush.yaml) by
-- leviathan.silver.ddl -- this RETIRES the first-parquet schema inference. Do NOT
-- hand-edit; re-run:  python scripts/silver/generate_ddls_from_registry.py --write
-- partition_mode = flat. recovery: active-release manifest / bounded full relist under the flat root
--
-- Flat physical layout under one LOCATION -- no partition-enumeration (LIST-storm)
-- surface; any hive-partition keys are also in-file data columns.
CREATE EXTERNAL TABLE IF NOT EXISTS gold_board_crush (
    trade_date           string,
    crush_margin_usd_bu  double,
    meal_value_usd_bu    double,
    oil_value_usd_bu     double,
    bean_cost_usd_bu     double,
    beans_contract_month string,
    meal_contract_month  string,
    oil_contract_month   string,
    beans_settle         double,
    meal_settle          double,
    oil_settle           double,
    settle_kind          string,
    roll_rule_version    string,
    crush_rule_version   string
)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/gold/board_crush/'
TBLPROPERTIES (
    'EXTERNAL' = 'TRUE',
    'parquet.compression' = 'SNAPPY'
);
