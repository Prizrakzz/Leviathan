-- silver_futures_eod - prices silver table (source); SILVER-F011 registry-generated DDL.
--
-- GENERATED from the SILVER-F010 registry (configs/silver/tables/silver_futures_eod.yaml) by
-- leviathan.silver.ddl -- this RETIRES the first-parquet schema inference. Do NOT
-- hand-edit; re-run:  python scripts/silver/generate_ddls_from_registry.py --write
-- partition_mode = registered. recovery: get-partitions reconcile + explicit per-partition locations (ESR as_of=/as_of_date mapping; never MSCK)
--
-- REGISTERED partitions -- DO NOT re-add partition projection. The projected grid is
-- the Jul-2026 S3 LIST-storm class ($134/2 days); partitions carry explicit Glue
-- locations (MSCK cannot repair them). After a DROP+CREATE from this DDL, re-register:
--     python jobs/utils/deproject_glue_table.py --register --tables silver_futures_eod
CREATE EXTERNAL TABLE IF NOT EXISTS silver_futures_eod (
    trade_date      timestamp,
    contract_month  string,
    instrument_kind string,
    raw_symbol      string,
    settle          double,
    settle_kind     string,
    open            double,
    high            double,
    low             double,
    close           double,
    volume          bigint,
    open_interest   bigint,
    unit            string,
    currency        string,
    expiry_date     timestamp,
    source          string,
    dataset         string
)
PARTITIONED BY (leviathan_slug string, trade_year int)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/futures_eod/'
TBLPROPERTIES (
    'EXTERNAL' = 'TRUE',
    'parquet.compression' = 'SNAPPY'
);
