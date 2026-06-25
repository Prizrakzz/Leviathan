-- Feature catalog observed for each immutable feature-spine dataset version.
CREATE EXTERNAL TABLE IF NOT EXISTS gold_feature_catalog_versions (
    feature   string,
    scope     string,
    group     string,
    commodity string,
    is_label  boolean
)
PARTITIONED BY (dataset_version string)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/gold/feature_catalog_versions/'
TBLPROPERTIES (
    'parquet.compression' = 'SNAPPY',
    'projection.enabled' = 'true',
    'projection.dataset_version.type' = 'injected',
    'storage.location.template' = 's3://leviathan-dev-shahem-001/gold/feature_catalog_versions/dataset_version=${dataset_version}/'
);
