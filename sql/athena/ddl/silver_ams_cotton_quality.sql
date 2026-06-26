-- GENERATED from live Glue table leviathan_dev.silver_ams_cotton_quality; keep in sync with the S3 layout.
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
    source             string
)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/ams_cotton_quality'
TBLPROPERTIES (
    'EXTERNAL' = 'TRUE',
    'parquet.compression' = 'SNAPPY'
);
