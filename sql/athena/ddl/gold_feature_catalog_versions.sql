-- GENERATED from live Glue table leviathan_dev.gold_feature_catalog_versions; keep in sync with the S3 layout.
CREATE EXTERNAL TABLE IF NOT EXISTS gold_feature_catalog_versions (
    feature          string,
    feature_family   string,
    semantic_scope   string,
    empirical_scope  string,
    policy           string,
    mechanism        string,
    sources          string,
    source_cadence   string,
    is_label         boolean,
    entity_count     bigint,
    commodity_count  bigint,
    origin_count     bigint,
    row_count        bigint,
    non_null_rate    double,
    first_event_time string,
    last_event_time  string,
    groups           string,
    notes            string
)
PARTITIONED BY (dataset_version string)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/gold/feature_catalog_versions'
TBLPROPERTIES (
    'EXTERNAL' = 'TRUE',
    'parquet.compression' = 'SNAPPY',
    'projection.dataset_version.type' = 'injected',
    'projection.enabled' = 'true',
    'storage.location.template' = 's3://leviathan-dev-shahem-001/gold/feature_catalog_versions/dataset_version=${dataset_version}/'
);
