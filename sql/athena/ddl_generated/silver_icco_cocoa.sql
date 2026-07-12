-- silver_icco_cocoa - balance_sheet silver table (source); SILVER-F011 registry-generated DDL.
--
-- GENERATED from the SILVER-F010 registry (configs/silver/tables/silver_icco_cocoa.yaml) by
-- leviathan.silver.ddl -- this RETIRES the first-parquet schema inference. Do NOT
-- hand-edit; re-run:  python scripts/silver/generate_ddls_from_registry.py --write
-- partition_mode = flat. recovery: active-release manifest / bounded full relist under the flat root
--
-- Flat physical layout under one LOCATION -- no partition-enumeration (LIST-storm)
-- surface; any hive-partition keys are also in-file data columns.
CREATE EXTERNAL TABLE IF NOT EXISTS silver_icco_cocoa (
    cocoa_year          string,
    latest_release_date string,
    production_kt       double,
    grindings_kt        double,
    end_stocks_kt       double,
    surplus_deficit_kt  double,
    su_ratio            double,
    grindings_3yr_trend double,
    grindings_trend_dev double,
    source              string
)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/icco_cocoa/'
TBLPROPERTIES (
    'EXTERNAL' = 'TRUE',
    'parquet.compression' = 'SNAPPY'
);
