-- gold_weather_z — the Phase D-W4 weather z serving table.
--
-- Tall, monthly, PIT-safe standardized weather-stress anomalies, one row per
-- commodity x country x region x year x month x metric. Built transform-upstream by
-- jobs/batch/gold_weather_z_task.py (compute core: leviathan.transforms.gold.weather_z) directly from the
-- silver weather sources (NASA POWER temperatures + CHIRPS precipitation) -- it does NOT read the deferred
-- MLOps gold.feature_spine (doctrine, silverleg.py:16-20) and does NOT un-defer onto the projected
-- silver_nasa_power (the Jul-2026 S3 LIST-storm partition class).
--
-- No projection, non-partitioned physical layout (D-W4): the whole table is flat parquet under one
-- LOCATION, so a query reads the small table without any partition enumeration -- there is no LIST-storm
-- surface here, and no per-partition ADD on refresh (the writer overwrites gold/weather_z/{slug}.parquet).
-- commodity/country/region/year/month are in-file DATA columns (not partition keys), so the query.py:176
-- country-clobber cannot fire (no country partition) either.
--
-- knowledge_semantics = year_month in the numbers registry: the as-of guard is (year*100+month) <= asof_ym
-- (reused wholesale from the ONI year_month path), so a month is citable only once its year-month has
-- passed. country holds the PSD Title-Case surface form ('United States', 'Brazil') so a country_rule=region
-- weather leg resolves against it.
CREATE EXTERNAL TABLE IF NOT EXISTS gold_weather_z (
    commodity string,
    country   string,
    region    string,
    year      int,
    month     int,
    metric    string,
    value     double
)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/gold/weather_z/'
TBLPROPERTIES (
    'EXTERNAL' = 'TRUE',
    'parquet.compression' = 'SNAPPY',
    'classification' = 'parquet'
);
