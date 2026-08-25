-- silver_psd_attributes - balance_sheet silver table (source); SILVER-F011 registry-generated DDL.
--
-- GENERATED from the SILVER-F010 registry (configs/silver/tables/silver_psd_attributes.yaml) by
-- leviathan.silver.ddl -- this RETIRES the first-parquet schema inference. Do NOT
-- hand-edit; re-run:  python scripts/silver/generate_ddls_from_registry.py --write
-- partition_mode = flat. recovery: active-release manifest / bounded full relist under the flat root
--
-- Flat physical layout under one LOCATION -- no partition-enumeration (LIST-storm)
-- surface; any hive-partition keys are also in-file data columns.
CREATE EXTERNAL TABLE IF NOT EXISTS silver_psd_attributes (
    leviathan_slug      string,
    country             string,
    market_year         smallint,
    wasde_release_month tinyint,
    release_date        string,
    attribute           string,
    attribute_id        smallint,
    value               double,
    unit                string
)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/psd_attributes/'
TBLPROPERTIES (
    'EXTERNAL' = 'TRUE',
    'parquet.compression' = 'SNAPPY'
);
