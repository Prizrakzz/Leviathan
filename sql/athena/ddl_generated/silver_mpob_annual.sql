-- silver_mpob_annual - balance_sheet silver table (derived); SILVER-F011 registry-generated DDL.
--
-- GENERATED from the SILVER-F010 registry (configs/silver/tables/silver_mpob_annual.yaml) by
-- leviathan.silver.ddl -- this RETIRES the first-parquet schema inference. Do NOT
-- hand-edit; re-run:  python scripts/silver/generate_ddls_from_registry.py --write
-- partition_mode = flat. recovery: active-release manifest / bounded full relist under the flat root
--
-- Flat physical layout under one LOCATION -- no partition-enumeration (LIST-storm)
-- surface; any hive-partition keys are also in-file data columns.
CREATE EXTERNAL TABLE IF NOT EXISTS silver_mpob_annual (
    year                       bigint,
    production_cpo_mt          double,
    closing_stocks_palm_oil_mt double,
    exports_palm_oil_mt        double,
    imports_palm_oil_mt        double,
    ffb_price_myr_per_mt       double,
    su_ratio                   double,
    source                     string,
    commodity                  string
)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/mpob_annual/'
TBLPROPERTIES (
    'EXTERNAL' = 'TRUE',
    'parquet.compression' = 'SNAPPY'
);
