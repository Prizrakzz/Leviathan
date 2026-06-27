-- Model-ready-specific feature-set membership.
CREATE EXTERNAL TABLE IF NOT EXISTS gold_model_ready_feature_sets (
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
LOCATION 's3://leviathan-dev-shahem-001/gold/model_ready_feature_sets'
TBLPROPERTIES (
    'EXTERNAL' = 'TRUE',
    'parquet.compression' = 'SNAPPY',
    'projection.enabled' = 'true',
    'projection.dataset_version.type' = 'injected',
    'storage.location.template' = 's3://leviathan-dev-shahem-001/gold/model_ready_feature_sets/dataset_version=${dataset_version}/'
);
