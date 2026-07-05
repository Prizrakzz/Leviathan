-- GENERATED from live Glue table leviathan_dev.silver_wasde; keep in sync with the S3 layout.
CREATE EXTERNAL TABLE IF NOT EXISTS silver_wasde (
    commodity                    string,
    table_type                   string,
    region                       string,
    marketing_year               string,
    attribute                    string,
    unit                         string,
    estimate                     double,
    prior_release_date           string,
    prior_estimate               double,
    revision                     double,
    revision_direction           string,
    months_to_marketing_year_end int,
    is_first_estimate            boolean,
    is_final_or_latest           boolean,
    raw_table_name               string,
    raw_region                   string,
    raw_attribute                string,
    raw_status                   string,
    raw_projection_month         string,
    source                       string
)
PARTITIONED BY (release_date string)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/wasde'
-- REGISTERED partitions since 2026-07 — DO NOT re-add partition projection. The daily-projected
-- release_date grid (~19.5K candidates over 461 real monthly releases) made any non-sargable query
-- enumerate S3 (the Jul-2026 LIST storm, $134/2 days). After a DROP+CREATE from this DDL, re-register
-- partitions: python jobs/utils/deproject_glue_table.py --register --tables silver_wasde
-- New-partition writers must call leviathan.storage.glue_partitions.ensure_partition after the S3 write.
TBLPROPERTIES (
    'EXTERNAL' = 'TRUE',
    'parquet.compression' = 'SNAPPY'
);
