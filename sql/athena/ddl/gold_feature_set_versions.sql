-- Model-purpose feature-set membership for each immutable feature-spine version.
CREATE EXTERNAL TABLE IF NOT EXISTS gold_feature_set_versions (
    feature_set_id       string,
    feature_set_version  string,
    feature_set_sha      string,
    feature              string,
    feature_family       string,
    semantic_scope       string,
    policy               string,
    mechanism            string,
    sources              string,
    source_cadence       string,
    empirical_scope      string,
    groups               string,
    is_label             boolean,
    row_count            bigint,
    commodity_count      bigint,
    non_null_rate        double,
    target_compatibility string,
    missingness_policy   string,
    min_lag_days         int
)
PARTITIONED BY (dataset_version string)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/gold/feature_set_versions/'
TBLPROPERTIES (
    'parquet.compression' = 'SNAPPY',
    'projection.enabled' = 'true',
    'projection.dataset_version.type' = 'injected',
    'storage.location.template' = 's3://leviathan-dev-shahem-001/gold/feature_set_versions/dataset_version=${dataset_version}/'
);
