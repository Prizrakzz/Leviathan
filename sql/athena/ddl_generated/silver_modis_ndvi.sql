-- silver_modis_ndvi - weather silver table (source); SILVER-F011 registry-generated DDL.
--
-- GENERATED from the SILVER-F010 registry (configs/silver/tables/silver_modis_ndvi.yaml) by
-- leviathan.silver.ddl -- this RETIRES the first-parquet schema inference. Do NOT
-- hand-edit; re-run:  python scripts/silver/generate_ddls_from_registry.py --write
-- partition_mode = flat. recovery: active-release manifest / bounded full relist under the flat root
--
-- Flat physical layout under one LOCATION -- no partition-enumeration (LIST-storm)
-- surface; any hive-partition keys are also in-file data columns.
CREATE EXTERNAL TABLE IF NOT EXISTS silver_modis_ndvi (
    date              date,
    year              smallint,
    period            tinyint,
    commodity         string,
    country           string,
    region            string,
    latitude          float,
    longitude         float,
    ndvi_raw          float,
    ndvi              float,
    pixel_reliability tinyint,
    ndvi_z_score      float,
    baseline_mean     float,
    baseline_std      float,
    ingest_date       string
)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/weather/source=modis_ndvi/'
TBLPROPERTIES (
    'EXTERNAL' = 'TRUE',
    'parquet.compression' = 'SNAPPY'
);
