-- GENERATED from live Glue table leviathan_dev.silver_chirps; keep in sync with the S3 layout.
-- SYNCED 2026-07-21: BF-W1 deproject+compaction (SILVER-F047) collapsed the projected 5-key layout to
-- REGISTERED [commodity, year] partitions; country/region/month became IN-FILE columns (nasa_power-class
-- drift -- the compacted parquet always carried them, the rebuilt catalog never declared them). The
-- in-file year and commodity columns are deliberately NOT declared (they would collide with the
-- partition keys of the same names).
CREATE EXTERNAL TABLE IF NOT EXISTS silver_chirps (
    date        date,
    day         bigint,
    source      string,
    ingest_date string,
    variable    string,
    value       double,
    country     string,
    region      string,
    month       bigint
)
PARTITIONED BY (commodity string, year int)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/weather/source=chirps'
TBLPROPERTIES (
    'EXTERNAL' = 'TRUE',
    'parquet.compression' = 'SNAPPY'
);
