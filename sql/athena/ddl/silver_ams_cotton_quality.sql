-- GENERATED from live Glue table leviathan_dev.silver_ams_cotton_quality; keep in sync with the S3 layout.
--
-- AMS-1 (D-LD Tranche 2) WIDEN: release_date is the DERIVED, conservative, never-leak publication
-- stamp (ISO 'YYYY-MM-DD' = Sep 1 of season+1, producer
-- src/leviathan/transforms/bronze_to_silver/ams_cotton_quality.py::ams_release_date). It is the
-- table's ONLY date column and the anchor the numbers as-of guard binds to (knowledge_date_col,
-- semantics vintage, publication_lag_days 0). APPENDED LAST so live Glue catches up with a plain
-- ALTER TABLE ... ADD COLUMNS and the ORDERED hand-DDL-vs-live-Glue drift check stays clean -- the
-- silver_conab_coffee survey_release_date precedent (WIRING_WAVE1). Migration of record:
-- sql/athena/migrations/silver/20260818T000000Z_silver_ams_cotton_quality_release_date_additive.json
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
LOCATION 's3://leviathan-dev-shahem-001/silver/ams_cotton_quality'
TBLPROPERTIES (
    'EXTERNAL' = 'TRUE',
    'parquet.compression' = 'SNAPPY'
);
