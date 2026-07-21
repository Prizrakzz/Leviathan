-- GENERATED from live Glue table leviathan_dev.silver_nasa_power; keep in sync with the S3 layout.
-- SYNCED 2026-07-21: BF-W1 deproject+compaction (SILVER-F047) collapsed the projected 5-key layout to
-- REGISTERED [commodity, year] partitions; country/region/month became IN-FILE columns (they always
-- existed in the parquet -- the rebuilt catalog just never declared them, which broke every numbers-lane
-- weather lookup with COLUMN_NOT_FOUND until the declaration was restored). The in-file `year` column is
-- deliberately NOT declared (it would collide with the partition key of the same name).
CREATE EXTERNAL TABLE IF NOT EXISTS silver_nasa_power (
    date                     date,
    day                      bigint,
    source                   string,
    ingest_date              string,
    source_file_name         string,
    temperature_2m_mean_c    double,
    temperature_2m_max_c     double,
    temperature_2m_min_c     double,
    precipitation_mm         double,
    relative_humidity_2m_pct double,
    wind_speed_2m_m_s        double,
    country                  string,
    region                   string,
    month                    bigint
)
PARTITIONED BY (commodity string, year int)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/weather/source=nasa_power'
TBLPROPERTIES (
    'EXTERNAL' = 'TRUE',
    'parquet.compression' = 'SNAPPY'
);
