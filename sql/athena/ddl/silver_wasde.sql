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
TBLPROPERTIES (
    'EXTERNAL' = 'TRUE',
    'parquet.compression' = 'SNAPPY',
    'projection.enabled' = 'true',
    'projection.release_date.format' = 'yyyy-MM-dd',
    'projection.release_date.interval' = '1',
    'projection.release_date.interval.unit' = 'DAYS',
    'projection.release_date.range' = '1973-01-01,NOW',
    'projection.release_date.type' = 'date',
    'storage.location.template' = 's3://leviathan-dev-shahem-001/silver/wasde/release_date=${release_date}'
);
