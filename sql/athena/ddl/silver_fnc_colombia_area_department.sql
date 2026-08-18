-- GENERATED from live Glue table leviathan_dev.silver_fnc_colombia_area_department; keep in sync with the S3 layout.
--
-- D-LD Tranche 2 (2026-08-18) P0 PIT ANCHOR -- ADDITIVE, gated. `ingest_date` is the 7th
-- non-partition column: the table had no date/month/knowledge column at all, so every numbers
-- as-of lookup raised before any SQL was compiled. The producer now carries the bronze stamp
-- through (transforms/bronze_to_silver/fnc_colombia.AREA_OUTPUT_COLUMNS). This file leads the
-- live catalog until the gated migration lands -- the sagis week_ending_date / conab
-- survey_release_date idiom:
--     ALTER TABLE silver_fnc_colombia_area_department ADD COLUMNS (ingest_date string);
-- ADD COLUMNS is name-based and additive; existing partitions read it as NULL until the
-- bronze->silver re-run republishes them, so run the migration and the producer together.
-- Migration manifest of record (gated, applied: false):
-- sql/athena/migrations/silver/20260818T000000Z_silver_fnc_colombia_area_department_ingest_date_additive.json
CREATE EXTERNAL TABLE IF NOT EXISTS silver_fnc_colombia_area_department (
    leviathan_slug string,
    country        string,
    department     string,
    department_raw string,
    area_ha        double,
    source         string,
    ingest_date    string
)
PARTITIONED BY (commodity string, year int)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/fnc_colombia/area_department'
TBLPROPERTIES (
    'EXTERNAL' = 'TRUE',
    'parquet.compression' = 'SNAPPY',
    'projection.commodity.type' = 'enum',
    'projection.commodity.values' = 'arabica_coffee',
    'projection.enabled' = 'true',
    'projection.year.range' = '2002,2035',
    'projection.year.type' = 'integer',
    'storage.location.template' = 's3://leviathan-dev-shahem-001/silver/fnc_colombia/area_department/commodity=${commodity}/year=${year}'
);
