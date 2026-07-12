-- silver_psd - balance_sheet silver table (source); SILVER-F011 registry-generated DDL.
--
-- GENERATED from the SILVER-F010 registry (configs/silver/tables/silver_psd.yaml) by
-- leviathan.silver.ddl -- this RETIRES the first-parquet schema inference. Do NOT
-- hand-edit; re-run:  python scripts/silver/generate_ddls_from_registry.py --write
-- partition_mode = flat. recovery: active-release manifest / bounded full relist under the flat root
--
-- Flat physical layout under one LOCATION -- no partition-enumeration (LIST-storm)
-- surface; any hive-partition keys are also in-file data columns.
CREATE EXTERNAL TABLE IF NOT EXISTS silver_psd (
    leviathan_slug            string,
    country                   string,
    market_year               smallint,
    wasde_release_month       tinyint,
    release_date              string,
    beginning_stocks_mt       double,
    production_mt             double,
    imports_mt                double,
    exports_mt                double,
    ending_stocks_mt          double,
    consumption_mt            double,
    area_harvested_1000ha     double,
    yield_mt_ha               double,
    su_ratio                  double,
    su_ratio_yoy_delta        double,
    production_mt_revision    double,
    ending_stocks_mt_revision double,
    consumption_mt_revision   double
)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/psd/'
TBLPROPERTIES (
    'EXTERNAL' = 'TRUE',
    'parquet.compression' = 'SNAPPY'
);
