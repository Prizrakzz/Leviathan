-- Training-window summaries computed from immutable feature matrix versions.
CREATE EXTERNAL TABLE IF NOT EXISTS gold_training_windows_versions (
    commodity          string,
    tier               string,
    n_features         bigint,
    label_first_year   bigint,
    label_last_year    bigint,
    n_label_years      bigint,
    dense_start_year   double,
    dense_window_years bigint,
    present_families   string
)
PARTITIONED BY (dataset_version string)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/gold/training_windows_versions/'
TBLPROPERTIES (
    'parquet.compression' = 'SNAPPY',
    'projection.enabled' = 'true',
    'projection.dataset_version.type' = 'injected',
    'storage.location.template' = 's3://leviathan-dev-shahem-001/gold/training_windows_versions/dataset_version=${dataset_version}/'
);
