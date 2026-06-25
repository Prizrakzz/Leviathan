-- Feature-to-commodity-group coverage for immutable feature-spine versions.
CREATE EXTERNAL TABLE IF NOT EXISTS gold_feature_group_map_versions (
    feature          string,
    `group`          string,
    commodity_count  bigint,
    row_count        bigint,
    non_null_rate    double,
    semantic_scope   string,
    policy           string
)
PARTITIONED BY (dataset_version string)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/gold/feature_group_map_versions/'
TBLPROPERTIES (
    'parquet.compression' = 'SNAPPY',
    'projection.enabled' = 'true',
    'projection.dataset_version.type' = 'injected',
    'storage.location.template' = 's3://leviathan-dev-shahem-001/gold/feature_group_map_versions/dataset_version=${dataset_version}/'
);
