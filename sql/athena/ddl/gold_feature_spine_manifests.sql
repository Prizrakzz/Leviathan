-- GENERATED from live Glue table leviathan_dev.gold_feature_spine_manifests; keep in sync with the S3 layout.
CREATE EXTERNAL TABLE IF NOT EXISTS gold_feature_spine_manifests (
    task         string,
    dataset_kind string,
    built_at     string,
    git_sha      string,
    params_hash  string,
    crop_years   array<int>,
    summary      struct<requested_commodity_count:int,written_count:int,dry_run_count:int,skipped_count:int,failed_count:int,total_spine_rows:bigint,total_label_rows:bigint,total_matrix_rows:bigint>,
    outputs      struct<feature_spine_prefix:string,feature_matrix_prefix:string,feature_catalog_key:string,manifest_key:string>
)
PARTITIONED BY (dataset_version string)
ROW FORMAT SERDE 'org.openx.data.jsonserde.JsonSerDe'
STORED AS INPUTFORMAT 'org.apache.hadoop.mapred.TextInputFormat'
OUTPUTFORMAT 'org.apache.hadoop.hive.ql.io.IgnoreKeyTextOutputFormat'
LOCATION 's3://leviathan-dev-shahem-001/gold/feature_spine_manifests'
TBLPROPERTIES (
    'EXTERNAL' = 'TRUE',
    'projection.dataset_version.type' = 'injected',
    'projection.enabled' = 'true',
    'storage.location.template' = 's3://leviathan-dev-shahem-001/gold/feature_spine_manifests/dataset_version=${dataset_version}/'
);
