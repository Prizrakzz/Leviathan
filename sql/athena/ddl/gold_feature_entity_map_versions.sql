-- GENERATED from live Glue table leviathan_dev.gold_feature_entity_map_versions; keep in sync with the S3 layout.
CREATE EXTERNAL TABLE IF NOT EXISTS gold_feature_entity_map_versions (
    feature       string,
    commodity     string,
    country       string,
    crop_year_min bigint,
    crop_year_max bigint,
    row_count     bigint,
    non_null_rate double,
    is_label      boolean
)
PARTITIONED BY (dataset_version string)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/gold/feature_entity_map_versions'
TBLPROPERTIES (
    'EXTERNAL' = 'TRUE',
    'parquet.compression' = 'SNAPPY',
    'projection.dataset_version.type' = 'injected',
    'projection.enabled' = 'true',
    'storage.location.template' = 's3://leviathan-dev-shahem-001/gold/feature_entity_map_versions/dataset_version=${dataset_version}/'
);
