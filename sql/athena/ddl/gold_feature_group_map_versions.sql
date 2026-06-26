-- GENERATED from live Glue table leviathan_dev.gold_feature_group_map_versions; keep in sync with the S3 layout.
CREATE EXTERNAL TABLE IF NOT EXISTS gold_feature_group_map_versions (
    feature         string,
    group           string,
    commodity_count bigint,
    row_count       bigint,
    non_null_rate   double,
    semantic_scope  string,
    policy          string
)
PARTITIONED BY (dataset_version string)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/gold/feature_group_map_versions'
TBLPROPERTIES (
    'EXTERNAL' = 'TRUE',
    'parquet.compression' = 'SNAPPY',
    'projection.dataset_version.type' = 'injected',
    'projection.enabled' = 'true',
    'storage.location.template' = 's3://leviathan-dev-shahem-001/gold/feature_group_map_versions/dataset_version=${dataset_version}/'
);
