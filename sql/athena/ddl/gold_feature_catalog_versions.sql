-- Semantic feature catalog for each immutable feature-spine dataset version.
CREATE EXTERNAL TABLE IF NOT EXISTS gold_feature_catalog_versions (
    feature            string,
    feature_family     string,
    semantic_scope     string,
    empirical_scope    string,
    policy             string,
    mechanism          string,
    sources            string,
    source_cadence     string,
    is_label           boolean,
    entity_count       bigint,
    commodity_count    bigint,
    origin_count       bigint,
    row_count          bigint,
    non_null_rate      double,
    first_event_time   string,
    last_event_time    string,
    groups             string,
    notes              string
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
