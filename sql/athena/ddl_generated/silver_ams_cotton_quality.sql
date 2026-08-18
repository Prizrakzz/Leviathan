-- silver_ams_cotton_quality - quality silver table (source); SILVER-F011 registry-generated DDL.
--
-- GENERATED from the SILVER-F010 registry (configs/silver/tables/silver_ams_cotton_quality.yaml) by
-- leviathan.silver.ddl -- this RETIRES the first-parquet schema inference. Do NOT
-- hand-edit; re-run:  python scripts/silver/generate_ddls_from_registry.py --write
-- partition_mode = flat. recovery: active-release manifest / bounded full relist under the flat root
--
-- Flat physical layout under one LOCATION -- no partition-enumeration (LIST-storm)
-- surface; any hive-partition keys are also in-file data columns.
CREATE EXTERNAL TABLE IF NOT EXISTS silver_ams_cotton_quality (
    commodity          string,
    season             bigint,
    geography          string,
    percent_tenderable double,
    samples_classed    double,
    avg_staple         double,
    avg_micronaire     double,
    avg_strength       double,
    source_pages       string,
    source_raw_key     string,
    source_file_etag   string,
    source             string,
    release_date       string
)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/ams_cotton_quality/'
TBLPROPERTIES (
    'EXTERNAL' = 'TRUE',
    'parquet.compression' = 'SNAPPY'
);
