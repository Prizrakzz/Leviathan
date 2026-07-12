-- silver_wap_table01_revisions - balance_sheet silver table (derived); SILVER-F011 registry-generated DDL.
--
-- GENERATED from the SILVER-F010 registry (configs/silver/tables/silver_wap_table01_revisions.yaml) by
-- leviathan.silver.ddl -- this RETIRES the first-parquet schema inference. Do NOT
-- hand-edit; re-run:  python scripts/silver/generate_ddls_from_registry.py --write
-- partition_mode = flat. recovery: active-release manifest / bounded full relist under the flat root
--
-- Flat physical layout under one LOCATION -- no partition-enumeration (LIST-storm)
-- surface; any hive-partition keys are also in-file data columns.
CREATE EXTERNAL TABLE IF NOT EXISTS silver_wap_table01_revisions (
    release_month       string,
    commodity           string,
    row_label           string,
    marketing_year      string,
    vintage_type        string,
    vintage_status      string,
    month_abbr          string,
    country             string,
    value_mmt           double,
    prior_release_month string,
    prior_value_mmt     double,
    revision_mmt        double
)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/wap_table01_revisions/'
TBLPROPERTIES (
    'EXTERNAL' = 'TRUE',
    'parquet.compression' = 'SNAPPY'
);
