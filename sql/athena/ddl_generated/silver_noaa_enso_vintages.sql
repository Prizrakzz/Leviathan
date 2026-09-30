-- silver_noaa_enso_vintages - climate silver table (source); SILVER-F011 registry-generated DDL.
--
-- GENERATED from the SILVER-F010 registry (configs/silver/tables/silver_noaa_enso_vintages.yaml) by
-- leviathan.silver.ddl -- this RETIRES the first-parquet schema inference. Do NOT
-- hand-edit; re-run:  python scripts/silver/generate_ddls_from_registry.py --write
-- partition_mode = flat. recovery: active-release manifest / bounded full relist under the flat root
--
-- Flat physical layout under one LOCATION -- no partition-enumeration (LIST-storm)
-- surface; any hive-partition keys are also in-file data columns.
CREATE EXTERNAL TABLE IF NOT EXISTS silver_noaa_enso_vintages (
    index_id             string,
    source_url           string,
    season               string,
    year                 bigint,
    month                bigint,
    anom                 double,
    vintage_date         string,
    vintage_evidence_utc string,
    vintage_date_source  string,
    capture_ref          string,
    content_sha256       string,
    is_first_print       boolean,
    official_from        string,
    official_until       string,
    official_statement   string
)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/noaa_enso_vintages/'
TBLPROPERTIES (
    'EXTERNAL' = 'TRUE',
    'parquet.compression' = 'SNAPPY'
);
